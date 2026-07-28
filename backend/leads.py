"""Lead-inbox state: OUR half of the Basisboard inbox.

Basisboard is read-only for us — we never link, tag, or delete a message there —
so every decision an estimator makes about a lead lives in one table here:

  leads(id text pk, lead_status text, category text, ai jsonb, extract jsonb,
        draft_id text, notes text, meta jsonb, status_by text,
        created_at timestamptz, updated_at timestamptz)
      One row per Basisboard MESSAGE id, created lazily on the first action.
      A message with no row is implicitly `new`, so the inbox works before
      anyone has touched anything (and before the table even exists).

The inbox the page renders is a LEFT merge: live Basisboard messages + whatever
rows we have. That's `merge_inbox()`, and its output keys are the frontend's
contract — renaming one breaks leads.js.

Also here, because they're all "turn a lead into intake" concerns:
  - `fetch_email_text()` — the readable body of a lead email (HTML stripped).
  - `build_base_blob()` — the metadata-only intake blob, which always succeeds.
  - `apply_ai_overlay()` — the ONLY way AI output reaches a draft: whitelisted
    keys, coerced types, non-empty values.
  - the two system prompts the `claude -p` runner in main.py drives.

Conventions follow drafts.py: module-level functions over
`supabase_client.get_client().table(...)`, best-effort with safe defaults (a
missing table degrades the view instead of 500ing), a TTL cache on the list read
that every write clears, and audit rows via `drafts.log_event`.
"""
from __future__ import annotations

import email.utils
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cachetools

import basisboard_client
import drafts as drafts_mod
from supabase_client import get_client

log = logging.getLogger("proposal_tool.leads")

_TABLE = "leads"
_COLUMNS = ("id,lead_status,category,ai,extract,draft_id,notes,meta,status_by,"
            "created_at,updated_at")
# Everything else on the row (id, timestamps) is ours to manage, not a caller's.
_WRITABLE_COLUMNS = frozenset({
    "lead_status", "category", "ai", "extract", "draft_id", "notes", "meta", "status_by",
})
_IN_CHUNK = 100          # ids per PostgREST `in.(...)` filter — keeps the URL sane
_TEXT_CAP = 15_000       # chars of email body handed to the AI / the intake notes
_EML_TIMEOUT = 20.0
_TZ_NAME = "America/Chicago"

# The states read runs on every inbox load; the parsed email text is re-read
# every time a drawer reopens. Both are cheap to hold and expensive to refetch.
_STATES_CACHE: cachetools.TTLCache = cachetools.TTLCache(maxsize=8, ttl=30)
_TEXT_CACHE: cachetools.TTLCache = cachetools.TTLCache(maxsize=64, ttl=600)


# ── small helpers ─────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Who the autopilot writes as. Lives here because merge_inbox reads it back to
# flag machine-made drafts, and leads_worker imports it to write it.
AUTOPILOT_ACTOR = "autopilot"


def _biz_tz():
    """Treadwell's business timezone. Bid deadlines arrive as UTC instants but are
    read as Central calendar dates everywhere else in the app (TW.fmtBizDate)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_TZ_NAME)
    except Exception as exc:  # noqa: BLE001 — tzdata missing (not in the image)
        # Falling back to UTC silently would date every deadline stamped after
        # 7pm Central a day late, and look correct while doing it. tzdata is in
        # requirements.txt, so this only fires on a bare interpreter — say so.
        log.warning("No tz database for %s (%s); bid dates will use UTC and may "
                    "be a day late. Install tzdata.", _TZ_NAME, exc)
        return timezone.utc


def _txt(value: Any) -> str:
    """Basisboard writes the literal string "N/A" into scraped fields it couldn't
    fill. Collapse that (and None) to "" so absence has exactly one representation
    and the frontend decides how to show it."""
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.upper() in ("N/A", "NULL", "NONE") else s


def _or_none(value: Any) -> Optional[str]:
    return _txt(value) or None


def _int0(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _num_or_none(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _cache_clear() -> None:
    """Drop the cached lead states — called after every write, so a Qualify click
    shows up on the next list load instead of up to 30 s later."""
    _STATES_CACHE.clear()


# ── state store ───────────────────────────────────────────────────────
def get_lead_states(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Our rows for `ids`, keyed by message id. Missing ids simply have no entry.

    Returns {} on ANY failure (including the table not existing yet), which makes
    the inbox degrade to every message reading as `new` rather than 500ing."""
    wanted = sorted({str(i) for i in (ids or []) if i})
    if not wanted:
        return {}
    key = tuple(wanted)
    cached = _STATES_CACHE.get(key)
    if cached is not None:
        return cached

    out: Dict[str, Dict[str, Any]] = {}
    try:
        sb = get_client()
        for chunk in _chunks(wanted, _IN_CHUNK):
            res = sb.table(_TABLE).select(_COLUMNS).in_("id", list(chunk)).execute()
            for row in (res.data or []):
                if row.get("id"):
                    out[str(row["id"])] = row
    except Exception as exc:  # noqa: BLE001 — pre-migration or a blip; not a page error
        log.warning("leads: state read failed (%s) — inbox degrades to all-new", exc)
        return {}
    _STATES_CACHE[key] = out
    return out


def upsert_lead(message_id: str, fields: Dict[str, Any],
                actor_email: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Create-or-patch one lead row. Only `_WRITABLE_COLUMNS` are honoured, so a
    caller can hand this a whole request body without laundering it first.

    Stamps `status_by` whenever `lead_status` moves and logs a
    `lead_status_changed` event — callers should NOT log that event again.
    Returns the stored row, or None if the write failed (missing table, blip)."""
    if not message_id:
        return None
    patch = {k: v for k, v in (fields or {}).items() if k in _WRITABLE_COLUMNS}
    if not patch:
        return None
    if "lead_status" in patch:
        patch.setdefault("status_by", actor_email)
    patch["id"] = str(message_id)
    patch["updated_at"] = _now_iso()

    try:
        res = get_client().table(_TABLE).upsert(patch, on_conflict="id").execute()
    except Exception as exc:  # noqa: BLE001
        log.warning("leads: upsert %s failed: %s", message_id, exc)
        return None
    _cache_clear()
    row = (res.data or [None])[0]

    if "lead_status" in patch:
        # project_id ties the event to the draft when one exists so History can
        # link it; a status change with no draft yet is still worth recording.
        drafts_mod.log_event(
            _txt(patch.get("draft_id")) or _txt((row or {}).get("draft_id")) or None,
            actor_email, "lead_status_changed",
            {"lead_id": patch["id"], "lead_status": patch.get("lead_status"),
             "category": patch.get("category")},
        )
    return row


# ── inbox merge (the frontend's row contract) ─────────────────────────
def merge_inbox(messages: List[Dict[str, Any]],
                states: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """LEFT-merge live Basisboard messages onto our lead rows.

    One flat dict per message. These keys ARE the frontend contract (leads.js
    renders them by name) — add freely, never rename. Absent Basisboard values
    are "" for text and None for timestamps/numbers; never the string "N/A"."""
    rows: List[Dict[str, Any]] = []
    for msg in (messages or []):
        mid = _txt(msg.get("id"))
        if not mid:
            continue
        state = (states or {}).get(mid) or {}
        ai = state.get("ai")
        ai = ai if isinstance(ai, dict) else {}
        proj = msg.get("project") or {}
        company = msg.get("company") or {}
        rows.append({
            "id": mid,
            "subject": _txt(msg.get("subject")),
            "from_email": _txt(msg.get("fromEmail")),
            "company": _txt(company.get("name")),
            "project_name": _txt(proj.get("name")),
            "location": _txt(proj.get("location")),
            "address_line": _txt(proj.get("addressLine")),
            "city": _txt(proj.get("city")),
            "region": _txt(proj.get("region")),
            "bid_deadline_at": _or_none(msg.get("bidDeadlineAt")),
            "communication_type": _txt(msg.get("communicationType")),
            "platform": _txt(msg.get("platformId")),
            "distance": _txt(msg.get("distance")),
            "travel_time": _txt(msg.get("travelTime")),
            "created_at": _or_none(msg.get("createdAt")),
            "is_spam": bool(msg.get("isSpam")),
            "duplicate_count": _int0(msg.get("duplicateMessagesCount")),
            "grouped": [
                {"id": _txt(g.get("id")), "subject": _txt(g.get("subject")),
                 "created_at": _or_none(g.get("createdAt"))}
                for g in (msg.get("groupedMessages") or []) if _txt(g.get("id"))
            ],
            "lead_status": _txt(state.get("lead_status")) or "new",
            "category": _txt(state.get("category")),
            "draft_id": _or_none(state.get("draft_id")),
            "ai_score": _num_or_none(ai.get("fit_score")),
            "ai_recommendation": _txt(ai.get("recommendation")),
            "ai_summary": _txt(ai.get("summary")),
            "has_ai": bool(ai),
            # A draft nobody asked for should say so. The autopilot stamps itself
            # as the actor when it moves the lead, so there's nothing extra to store.
            "lead_auto": _txt(state.get("status_by")) == AUTOPILOT_ACTOR,
        })
    return rows


# ── email body -> plain text ──────────────────────────────────────────
_COMMENT_RE = re.compile(r"(?s)<!--.*?-->")
_SCRIPT_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_CELL_RE = re.compile(r"(?i)</t[dh]\s*>")
_BLOCK_RE = re.compile(
    r"(?i)</(p|div|tr|li|ul|ol|h[1-6]|table|thead|tbody|blockquote|section|article|pre)\s*>")
_TAG_RE = re.compile(r"(?s)<[^>]*>")
_SPACES_RE = re.compile(r"[ \t\xa0]{2,}")
_BLANKS_RE = re.compile(r"\n{3,}")


def _collapse(text: str) -> str:
    """Normalise newlines, squeeze runs of spaces and blank lines. Marketing HTML
    unwraps into hundreds of empty lines otherwise, which is pure prompt tax."""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    s = "\n".join(_SPACES_RE.sub(" ", line).strip() for line in s.split("\n"))
    return _BLANKS_RE.sub("\n\n", s).strip()


def _html_to_text(raw: str) -> str:
    """Strip HTML to readable text without pulling in a parser dependency.
    Good enough for prompt input and an escaped <pre> — it is never re-rendered
    as markup, so imperfect nesting can't hurt anything."""
    if not raw:
        return ""
    s = _COMMENT_RE.sub(" ", raw)
    s = _SCRIPT_RE.sub(" ", s)          # drop the CONTENT of script/style, not just the tags
    s = _BR_RE.sub("\n", s)
    s = _CELL_RE.sub(" ", s)            # table cells read as one line, not one line each
    s = _BLOCK_RE.sub("\n", s)
    s = _TAG_RE.sub("", s)
    return _collapse(html.unescape(s))


def _cap(text: str) -> str:
    if len(text) <= _TEXT_CAP:
        return text
    return text[:_TEXT_CAP].rstrip() + "\n\n[truncated]"


def _decode_part(part) -> str:
    """Bytes -> str for one .eml part, honouring its declared charset. Bad or
    unknown charsets fall back to utf-8; replacement chars beat an exception."""
    payload = part.get_payload(decode=True)
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


def _eml_body_text(msg) -> str:
    """Walk a parsed .eml for its readable body: every text/plain part if there is
    one (that's the sender's own plain rendering), else the HTML parts stripped."""
    plain: List[str] = []
    html_parts: List[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if "attachment" in (part.get("Content-Disposition") or "").lower():
            continue
        ctype = (part.get_content_type() or "").lower()
        if ctype == "text/plain":
            plain.append(_decode_part(part))
        elif ctype == "text/html":
            html_parts.append(_decode_part(part))
    if any(p.strip() for p in plain):
        return _collapse("\n".join(plain))
    return _html_to_text("\n".join(html_parts))


def _eml_header(msg, name: str) -> str:
    """Decode a possibly RFC-2047-encoded header (=?utf-8?B?...?=) to text."""
    raw = msg.get(name)
    if not raw:
        return ""
    try:
        from email.header import decode_header, make_header
        return _txt(str(make_header(decode_header(raw))))
    except Exception:  # noqa: BLE001 — a malformed header is not worth failing on
        return _txt(raw)


def _download_eml(message_id: str) -> Optional[bytes]:
    """GET the raw .eml behind a freshly minted signed URL. The URL expires after
    15 minutes, so a 403 means "stale link", not "forbidden" — mint a new one and
    try once more."""
    import httpx
    for attempt in range(2):
        url = basisboard_client.get_message_url(message_id)
        if not url:
            return None
        try:
            with httpx.Client(timeout=_EML_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url)
        except httpx.TransportError as exc:
            log.warning("leads: .eml fetch %s transport error: %s", message_id, exc)
            return None
        if resp.status_code == 403 and attempt == 0:
            continue
        if resp.status_code >= 400:
            log.warning("leads: .eml fetch %s -> HTTP %s", message_id, resp.status_code)
            return None
        return resp.content
    return None


def _text_from_detail(message_id: str) -> Optional[Dict[str, Any]]:
    """Preferred path: /messages/{id}/detail carries the body inline, so there's
    no signed URL to expire and no MIME to walk."""
    payload = basisboard_client.get_message_detail(message_id)
    msg = (payload or {}).get("message") or {}
    text = _cap(_html_to_text(msg.get("body") or ""))
    if not text:
        return None
    return {"ok": True, "subject": _txt(msg.get("subject")),
            "from": _txt(msg.get("fromEmail")), "text": text, "via": "detail"}


def _text_from_eml(message_id: str) -> Optional[Dict[str, Any]]:
    """Fallback: download the raw .eml and parse it with the stdlib."""
    raw = _download_eml(message_id)
    if not raw:
        return None
    from email import message_from_bytes
    msg = message_from_bytes(raw)
    text = _cap(_eml_body_text(msg))
    if not text:
        return None
    return {"ok": True, "subject": _eml_header(msg, "Subject"),
            "from": _eml_header(msg, "From"), "text": text, "via": "eml"}


def fetch_email_text(message_id: str) -> Dict[str, Any]:
    """Readable text of one lead email: {"ok", "subject", "from", "text"}.

    Never raises and never returns HTML — the text goes straight into a prompt and
    into an escaped <pre>, so foreign markup has no way into our pages. Cached for
    10 minutes because the drawer refetches on every open."""
    mid = _txt(message_id)
    if not mid:
        return {"ok": False, "subject": "", "from": "", "text": "",
                "error": "No message id."}
    cached = _TEXT_CACHE.get(mid)
    if cached is not None:
        return cached

    result: Optional[Dict[str, Any]] = None
    for reader in (_text_from_detail, _text_from_eml):
        try:
            result = reader(mid)
        except Exception as exc:  # noqa: BLE001 — try the next path, then give up
            log.warning("leads: %s failed for %s: %s", reader.__name__, mid, exc)
            result = None
        if result:
            break
    if not result:
        return {"ok": False, "subject": "", "from": "", "text": "",
                "error": "Couldn't load the email body."}
    _TEXT_CACHE[mid] = result
    return result


# ── location / date parsing ───────────────────────────────────────────
_STATE_ABBRS = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_state(*candidates: Any) -> str:
    """Two-letter state out of "Edgerton, KS, United States of America" or
    "Kansas". Only an ALREADY-uppercase token counts as an abbreviation —
    otherwise the words "in", "or" and "me" would each name a state."""
    for candidate in candidates:
        text = _txt(candidate)
        if not text:
            continue
        for token in re.split(r"[,\s]+", text):
            token = token.strip(".")
            if len(token) == 2 and token.isupper() and token in _STATE_ABBRS:
                return token
        bare = text.strip().upper()
        if len(bare) == 2 and bare in _STATE_ABBRS:      # region fields like "ks"
            return bare
        low = text.lower()
        for name, abbr in _STATE_NAMES.items():
            if re.search(r"\b" + re.escape(name) + r"\b", low):
                return abbr
    return ""


def _parse_zip(*candidates: Any) -> str:
    for candidate in candidates:
        match = _ZIP_RE.search(_txt(candidate))
        if match:
            return match.group(1)
    return ""


def _city_state(city: Any, state: Any) -> str:
    """The combined "City, ST" the estimate sheet (C3), the proposal token and the
    tax lookup all read — intake builds it the same way on submit."""
    return ", ".join(p for p in (_txt(city), _txt(state).upper()) if p)


def _biz_date(value: Any) -> str:
    """UTC ISO instant -> YYYY-MM-DD in Central. Basisboard stamps deadlines in
    UTC; every date this app shows a human is a Central calendar date."""
    text = _txt(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(_biz_tz()).date().isoformat()


def _parse_from(from_email: Any) -> Tuple[str, str]:
    """(display name, address) out of a From value like
    '"Lorena Fonseca (Lemartec Corporation a MasTec company)" <team@buildingconnected.com>'.
    The trailing parenthetical is the sending COMPANY, not part of a person's
    name, so it doesn't belong in the intake contact field."""
    name, addr = email.utils.parseaddr(_txt(from_email))
    name = re.sub(r"\s*\([^)]*\)\s*$", "", (name or "").strip()).strip(' "\'')
    addr = (addr or "").strip()
    if name.lower() == addr.lower():
        name = ""
    return name, addr


# ── intake blob ───────────────────────────────────────────────────────
def build_base_blob(msg: Dict[str, Any], email_text: str, draft_id: str) -> Dict[str, Any]:
    """The metadata-only intake blob for a lead — everything we can fill without
    asking an AI anything. This ALWAYS succeeds, which is the point: a bad or
    unavailable AI run costs the estimator some typing, never the draft.

    `apply_ai_overlay()` layers the extracted values on top of this."""
    msg = msg or {}
    proj = msg.get("project") or {}
    subject = _txt(msg.get("subject"))
    location = _txt(proj.get("location"))
    city = _txt(proj.get("city"))
    state = _parse_state(location, proj.get("region"))
    contact_name, contact_email = _parse_from(msg.get("fromEmail"))
    bid_date = _biz_date(msg.get("bidDeadlineAt"))

    return {
        "project_name": _txt(proj.get("name")) or subject,
        "address": _txt(proj.get("addressLine")),
        "city": city,
        "state": state,
        "zip": _parse_zip(location, proj.get("addressLine")),
        "city_state": _city_state(city, state),
        "architect": "",
        "contact_name": contact_name,
        "contact_email": contact_email,
        "contact_phone": "",
        "contact_notes": "",
        # bid_date is the single project date on intake; `deadline` mirrors it for
        # the Projects list and the bell's due-date reminders.
        "bid_date": bid_date,
        "deadline": bid_date,
        "approx_start_date": "",
        "source": "email",
        "audience": "GC",                  # bid invites come from GCs; the AI may flip it
        "work_type": "epoxy",              # the AI may flip it; the estimator always can
        "num_systems": 2,                  # the estimate sheet's fixed two-system model
        # The full email lands in `notes` because Estimate Review's Autofill reads
        # state.notes — that's the lead text the flag inference needs.
        "notes": email_text or "",
        "lead_id": _txt(msg.get("id")),
        "lead_auto": False,                # the autopilot flips this on its own creations
        "__draft_id": draft_id,
    }


_QUANTITY_KEYS = (
    "system_1_sf", "polish_sf", "cove_1_lf",
    "system_2_sf", "polish_2_sf", "cove_2_lf",
    "gyp_soft_sf", "gyp_hard_sf", "gyp_corridor_sf",
)
# The COMPLETE set of intake fields an AI run may write. Anything else it invents
# is dropped — the AI prefills a form, it does not get to author the project.
_ALLOWED_INTAKE_KEYS = frozenset({
    "bid_date", "project_name", "address", "city", "state", "zip", "architect",
    "contact_name", "contact_email", "contact_phone", "work_type", "audience",
    "approx_start_date", "contact_notes",
} | set(_QUANTITY_KEYS))

_WORK_TYPES = ("epoxy", "polish", "combo", "gyp")
_AUDIENCES = {"direct": "Direct", "gc": "GC"}
_NUM_JUNK_RE = re.compile(r"[$,\s]")


def _to_number(value: Any):
    """"~12,500 sf" / "$12,500" / 12500.0 -> 12500. Returns None when there's no
    clean number, so a garbage quantity is dropped rather than written as 0."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        cleaned = _NUM_JUNK_RE.sub("", _txt(value))
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        if not match:
            return None
        number = float(match.group(0))
    if number != number or number in (float("inf"), float("-inf")) or number < 0:
        return None
    return int(number) if number.is_integer() else number


def _coerce_intake(key: str, raw: Any):
    """One AI value -> a value the intake form can hold, or None to drop it."""
    if raw is None:
        return None
    if key in _QUANTITY_KEYS:
        return _to_number(raw)
    if isinstance(raw, bool):
        return None
    value = _txt(raw)
    if not value:
        return None
    if key == "work_type":
        low = value.lower()
        return low if low in _WORK_TYPES else None
    if key == "audience":
        return _AUDIENCES.get(value.lower())
    if key in ("bid_date", "approx_start_date"):
        return value if _DATE_RE.match(value) else None
    if key == "state":
        # Run it back through the parser so "Kansas" becomes KS and a non-state
        # (a county, a country) is dropped instead of truncated to two letters.
        return _parse_state(value)
    return value


def apply_ai_overlay(blob: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
    """Layer an AI extraction onto a base blob: whitelisted keys only, non-empty
    values only, types coerced. Returns a new dict — the base is never mutated."""
    out = dict(blob or {})
    for key, raw in (ai or {}).items():
        if key not in _ALLOWED_INTAKE_KEYS:
            continue
        value = _coerce_intake(key, raw)
        if value is None or value == "":
            continue
        out[key] = value
    # Derived fields last: the AI may have moved city/state/bid_date, and intake
    # itself keeps these two in lockstep on submit.
    out["city_state"] = _city_state(out.get("city"), out.get("state"))
    out["deadline"] = _txt(out.get("bid_date")) or _txt(out.get("deadline"))
    return out


# ── AI prompts (style: main.py's _AUTOFILL_SYSTEM_PROMPT) ─────────────
_PREQUAL_SYSTEM_PROMPT = (
    "You're a lead screener for Treadwell, a commercial flooring contractor based "
    "in Olathe, Kansas. Treadwell installs EPOXY/resinous floor systems, POLISHED "
    "CONCRETE, and GYPSUM UNDERLAYMENTS — nothing else. Given one lead email "
    "(scraped metadata + the email text), decide whether it is worth an "
    "estimator's time.\n\n"
    "Return STRICT JSON only (no markdown fences, no prose before or after). "
    "Top-level shape:\n"
    "{\n"
    '  "fit_score":              0-100,   // 0 = irrelevant, 100 = ideal Treadwell job\n'
    '  "recommendation":         "pursue|review|pass",\n'
    '  "work_type_guess":        "epoxy|polish|combo|gyp|none",\n'
    '  "flooring_scope_present": true|false,  // does the scope include work we self-perform?\n'
    '  "scope_signals":          ["<phrase quoted from the email>", ...],\n'
    '  "audience_guess":         "GC|Direct",\n'
    '  "location_ok":            true|false|null,  // from the GIVEN distance/travel time\n'
    '  "deadline_days":          <int>|null,       // days from today to the bid deadline\n'
    '  "deadline_feasible":      true|false|null,\n'
    '  "is_noise":               true|false,\n'
    '  "summary":                "<= 2 sentences, what this lead is>",\n'
    '  "reasoning":              {"<key>": "<short why-this-value>", ...}\n'
    "}\n"
    "\n"
    "Rules:\n"
    "- Distance and travel time are FACTS supplied in the input. Never guess "
    "geography, never estimate a drive from a city name, and never contradict "
    "the supplied numbers. If they're absent, set location_ok to null.\n"
    "- Treadwell's sweet spot is roughly within 1 hour of Olathe, KS. Under ~60 "
    "miles is comfortable; 60-120 is workable but worth flagging; beyond that, "
    "say so in the reasoning rather than silently scoring it down.\n"
    "- recommendation = \"pass\" whenever there is NO flooring scope Treadwell "
    "self-performs (roofing, drywall-only, sitework, carpet/VCT-only, "
    "waterproofing-only, etc.). \"review\" when the scope is plausible but "
    "unclear. \"pursue\" only when a concrete epoxy / polish / gypsum scope is "
    "actually present.\n"
    "- is_noise = true for replies to Treadwell's OWN proposals (subjects "
    "starting \"Re: TREADWELL Proposal\"), out-of-office autoreplies, delivery "
    "receipts, platform notifications, and marketing blasts. Noise gets "
    "recommendation \"pass\" and a low fit_score.\n"
    "- NEVER invent square footages, prices, or dates. If the email doesn't state "
    "a quantity, don't imply one; scope_signals must quote text that is really "
    "there.\n"
    "- deadline_days: compute it from the bid deadline given in the input. Null "
    "when no deadline was supplied. deadline_feasible = false only when the "
    "deadline is already past or is inside ~2 business days.\n"
    "- audience_guess: \"GC\" when the sender is a general contractor inviting "
    "subs (BuildingConnected, ISQFT, \"bid invitation\", \"we are bidding\"); "
    "\"Direct\" when the sender is the owner, tenant, architect, or facility.\n"
    "- reasoning: one short phrase per meaningful key, citing the input it came "
    "from. Keep it terse — this is an audit trail, not an essay."
)

_EXTRACT_SYSTEM_PROMPT = (
    "You're an intake assistant for Treadwell, a commercial epoxy/polished-"
    "concrete/gypsum-underlayment flooring contractor in Olathe, Kansas. Given "
    "one lead email (scraped metadata + the email text), extract the project "
    "details an estimator would otherwise retype into the intake form.\n\n"
    "Return STRICT JSON only (no markdown fences, no prose before or after). "
    "Include ONLY the keys you actually found — OMIT anything unknown, never "
    "null-fill and never guess. Allowed keys:\n"
    "{\n"
    '  "project_name":      "<job/business name>",\n'
    '  "address":           "<street address only>",\n'
    '  "city":              "<city>",\n'
    '  "state":             "<2-letter, e.g. KS>",\n'
    '  "zip":               "<5-digit>",\n'
    '  "architect":         "<architect or design firm>",\n'
    '  "contact_name":      "<person to reply to>",\n'
    '  "contact_email":     "<their email>",\n'
    '  "contact_phone":     "<their phone>",\n'
    '  "bid_date":          "YYYY-MM-DD",  // when the bid is due\n'
    '  "approx_start_date": "YYYY-MM-DD",  // when work would start on site\n'
    '  "work_type":         "epoxy|polish|combo|gyp",\n'
    '  "audience":          "Direct|GC",\n'
    '  "system_1_sf":       <number>,  // epoxy SF, system 1\n'
    '  "polish_sf":         <number>,  // polished concrete SF, system 1\n'
    '  "cove_1_lf":         <number>,  // epoxy cove base LF, system 1\n'
    '  "system_2_sf":       <number>,  // epoxy SF, second area (only if two are described)\n'
    '  "polish_2_sf":       <number>,  // polished concrete SF, second area\n'
    '  "cove_2_lf":         <number>,  // epoxy cove base LF, second area\n'
    '  "gyp_soft_sf":       <number>,  // gypsum underlayment, soft-covering areas\n'
    '  "gyp_hard_sf":       <number>,  // gypsum underlayment, hard-covering areas\n'
    '  "gyp_corridor_sf":   <number>,  // gypsum underlayment, corridors\n'
    '  "contact_notes":     "<2-3 sentence summary of the lead for the estimator>",\n'
    '  "reasoning":         {"<key>": "<short why-this-value>", ...}\n'
    "}\n"
    "\n"
    "Rules:\n"
    "- Any key not in the list above is IGNORED. Don't invent fields, don't "
    "return the intake form's other inputs, don't wrap the object in an envelope.\n"
    "- Quantities ONLY when the email states them explicitly ('approx. 12,500 SF "
    "of epoxy'). If a number is a room count, a page count, a dollar amount, or a "
    "plan reference, it is NOT a quantity — omit it. The estimator types "
    "quantities they take off the drawings.\n"
    "- work_type: \"epoxy\" for resinous/epoxy/urethane floor systems, \"polish\" "
    "for polished or sealed concrete, \"combo\" when BOTH are in scope, \"gyp\" "
    "for gypsum underlayment / Gyp-Crete. Omit the key if the email doesn't say.\n"
    "- audience: \"GC\" when a general contractor is inviting subs, \"Direct\" "
    "when the owner, tenant, architect, or facility is asking us directly.\n"
    "- Dates must be YYYY-MM-DD. Convert \"Thursday, July 30th\" using the year "
    "from the email's own date. Omit a date you can't pin to a real day.\n"
    "- The scraped metadata block is trustworthy for project name, address, city, "
    "state and bid deadline — prefer the EMAIL BODY only when it clearly "
    "corrects or completes it.\n"
    "- Prefer a person's own signature block over the platform sender for "
    "contact_name/email/phone (a BuildingConnected invite is sent by the "
    "platform on the estimator's behalf).\n"
    "- contact_notes: what the job is, who's asking, and anything an estimator "
    "must not miss (walkthrough required, prevailing wage, phasing, night work). "
    "2-3 sentences, no fluff.\n"
    "- reasoning: one short phrase per key you filled, citing where it came from."
)


def build_prompt_input(msg: Dict[str, Any], email_text: str) -> str:
    """The plain-text block both lead prompts consume: the scraped metadata
    Basisboard already computed, then the email itself."""
    msg = msg or {}
    proj = msg.get("project") or {}
    company = msg.get("company") or {}
    none = "(none)"
    body = _cap((email_text or "").strip()) or "(email body unavailable — judge from the metadata only)"
    return (
        f"Today: {datetime.now(_biz_tz()).date().isoformat()} (America/Chicago)\n"
        f"Subject: {_txt(msg.get('subject')) or none}\n"
        f"From: {_txt(msg.get('fromEmail')) or none}\n"
        f"Company: {_txt(company.get('name')) or none}\n"
        f"Project name: {_txt(proj.get('name')) or none}\n"
        f"Project location: {_txt(proj.get('location')) or none}\n"
        f"Address line: {_txt(proj.get('addressLine')) or none}\n"
        f"City: {_txt(proj.get('city')) or none}\n"
        f"Region: {_txt(proj.get('region')) or none}\n"
        f"Distance from the Olathe office: {_txt(msg.get('distance')) or none}\n"
        f"Travel time from the Olathe office: {_txt(msg.get('travelTime')) or none}\n"
        f"Bid deadline: {_txt(msg.get('bidDeadlineAt')) or none}\n"
        f"Communication type: {_txt(msg.get('communicationType')) or none}\n"
        f"Platform: {_txt(msg.get('platformId')) or none}\n"
        f"Received: {_txt(msg.get('createdAt')) or none}\n"
        f"Marked spam by the platform: {'yes' if msg.get('isSpam') else 'no'}\n"
        f"\nEmail body:\n{body}\n"
    )
