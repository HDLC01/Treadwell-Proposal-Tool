"""Read-only Basisboard client.

Scope (deliberately): READ the projects/bids that already exist in Basisboard so
the proposal tool can show a pipeline CRM, a lead inbox, and an analytics
dashboard. No writes — nothing here creates, updates, or deletes anything in
Basisboard.

Conventions (mirrors dropbox_client.py): env-gated `is_configured()`, public
getters return a dict and never raise, generic client-facing errors (detail goes
to the server log only), inert when `BASISBOARD_API_KEY` is unset.

Money: every amount Basisboard sends is an integer count of CENTS. `_dollars()`
converts at the shaping boundary so no caller has to remember.

Architecture / performance:
  - One pooled `httpx.Client` per build (keep-alive connection reuse) shared
    across a small thread pool, so the ~13 calls a cold build needs run
    CONCURRENTLY instead of serially (measured ~13s -> ~4s).
  - Layered: transport (`_get`, retry/backoff) -> resource fetchers
    (`_fetch_stages/_users/_project_ids/_projects`) -> assembler (`_build_pipeline`)
    -> cached, coalesced entry point (`get_pipeline`). Each layer is reusable on
    its own (e.g. a future webhook handler can call a single resource fetcher).
  - Caches: stages/users (rarely change) 5 min; the assembled pipeline 60 s.
    A build lock coalesces concurrent cold requests into one fetch.

Read contract (https://api.basisboard.com/v1, `Authorization: Bearer <key>`):
  GET /stages                            -> {"stages":[{id,name,color,order}]}
  GET /users?offset=N                    -> {"users":[{id,firstName,lastName,email}]}
                                            (paged ~13 at a time, no total — read
                                             until a page comes back empty)
  GET /custom-field-settings             -> the custom fields, incl. the one holding
                                            a project's trades
  GET /projects/ids?limit&offset&sort[bidDeadline]=DESC
                                         -> {"projectIds":[...], "paging":{"total"}}
  GET /projects?filter[projectIds][]=... -> {"projects":[{id,name,location,city,region,
                                              quote,stageId,estimatorIds,customFields,
                                              bidInviteIds,awardedById,awardedAt,submittedAt,
                                              lostAt,createdAt,wonAmount,submittedAmount,
                                              pendingAmount,lostAmount,archivedAt,deletedAt}],
                                             "bidInvitesMap":{id:{companyId,bidDeadlineAt}},
                                             "companiesMap":{id:{name,...}}}
  GET /messages?filter[status]=unlinked&limit&offset
                                         -> {"messages":[{id,subject,fromEmail,createdAt,
                                              platformId,communicationType,status,isSpam,
                                              project{name,location,region,addressLine,city},
                                              company{name},bidDeadlineAt,distance,travelTime,
                                              scrapedIndicator{},groupedMessages[],
                                              suggestedGroupedMessages[],duplicateMessagesCount}],
                                             "paging":{"total"}}
                                            (most sub-objects/fields are frequently null)
  GET /messages/stats?timeFrame=this-month
                                         -> {received,automaticallyProcessed,duplicatesProcessed}
  GET /messages/{id}/detail              -> {"message":{id,subject,fromEmail,createdAt,
                                              communicationType,body:"<full HTML email>"}}
  GET /messages/{id}                     -> {"url": "<signed .eml URL, expires in 15 min>"}
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

import cachetools

log = logging.getLogger("proposal_tool.basisboard")

_DEFAULT_BASE = "https://api.basisboard.com/v1"
_TIMEOUT = 15.0
_PAGE = 50                # ids per /projects/ids page AND ids per /projects fetch
# Analytics reads the whole history, so it asks for bigger pages. At 50 that is
# ~136 requests, enough of a burst to earn 429s and back off into a two-minute
# build; at these sizes it's ~45 requests and about ten seconds. Basisboard
# serves 500 ids and 150 detail rows happily — 100 detail rows keeps the query
# string well clear of the length a gateway will refuse.
_ANALYTICS_ID_PAGE = 500
_ANALYTICS_DETAIL_PAGE = 100
_CONCURRENCY = 8          # max parallel requests per build
_RETRIES = 4              # extra attempts on a transient (429 / 5xx / transport) error
_BACKOFF_BASE = 0.5       # seconds; doubles per attempt unless the server says otherwise
_TRANSIENT = {429, 500, 502, 503, 504}
_USER_PAGE_CAP = 40       # /users has no total; stop asking eventually regardless

# Basisboard stores every money field as integer CENTS. Nothing outside this
# module should ever see one, so the conversion happens in the shapers.
_CENTS = 100.0

# stages/users change rarely; the assembled pipeline is cached briefly so a page
# refresh doesn't re-fetch everything. _BUILD_LOCK coalesces concurrent cold
# builds so 10 simultaneous loads trigger ONE fetch, not 10.
_meta_cache = cachetools.TTLCache(maxsize=8, ttl=300)
_pipeline_cache = cachetools.TTLCache(maxsize=1, ttl=60)
_BUILD_LOCK = threading.Lock()

# The lead inbox is a separate read with its own cadence, so it gets its own
# cache + lock: a slow inbox build must never block (or be blocked by) the CRM
# board, and one view going stale shouldn't evict the other.
_inbox_cache = cachetools.TTLCache(maxsize=4, ttl=60)
_INBOX_LOCK = threading.Lock()

# Analytics reads the whole bid history — ~45 requests — so it gets a longer
# TTL and keeps its last good snapshot past expiry: a reader gets those numbers
# instantly while one background thread fetches the new ones. The TTL is fixed
# at import; ANALYTICS_TTL_S is a deploy-time knob, not a per-request one.
def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ.get(name) or default)))
    except (TypeError, ValueError):
        return default


_analytics_cache = cachetools.TTLCache(maxsize=1, ttl=_env_int("ANALYTICS_TTL_S", 300, 60, 3600))
_ANALYTICS_REFRESH_LOCK = threading.Lock()
_analytics_last_good: Dict[str, Any] = {}
_analytics_state: Dict[str, Any] = {"building": False, "error": ""}

# Whatever custom field currently holds the trades. Resolved by name at runtime;
# this is the id observed in Treadwell's account, kept as the fallback.
_TRADE_FIELD_FALLBACK = "8674aa0e-5dba-45d3-bad1-bf857e60c2d2"


class _Pacer:
    """A shared minimum gap between requests, so we stay under Basisboard's rate
    limit instead of discovering it.

    Retrying a 429 is the cure; not causing it is the treatment. Reading the full
    bid history is ~45 requests and a thread pool will fire them as fast as it
    can, which Basisboard answers with 429s. Every request waits its turn here,
    and a 429 widens the gap for everyone (recovering slowly afterwards) so the
    limit is found once rather than on every page."""

    def __init__(self, min_interval: float = 0.05, max_interval: float = 0.6):
        self._lock = threading.Lock()
        self._floor = min_interval
        self._ceiling = max_interval
        self._interval = min_interval
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            due = max(now, self._next_at)
            self._next_at = due + self._interval
            # Ease back toward the floor while things are going well.
            self._interval = max(self._floor, self._interval * 0.98)
        delay = due - now
        if delay > 0:
            time.sleep(delay)

    def back_off(self) -> None:
        with self._lock:
            self._interval = min(self._ceiling, max(self._floor, self._interval) * 2)


_PACER = _Pacer()


# ── config ────────────────────────────────────────────────────────────
def _api_key() -> str:
    return (os.environ.get("BASISBOARD_API_KEY") or "").strip()


def _api_base() -> str:
    return (os.environ.get("BASISBOARD_API_BASE") or _DEFAULT_BASE).rstrip("/")


def _max_projects() -> int:
    """How many (most-recent) projects to pull for the board. The org has
    thousands of all-time bids; the pipeline view shows a recent, capped window."""
    try:
        return max(1, min(500, int(os.environ.get("BASISBOARD_MAX_PROJECTS") or 300)))
    except (TypeError, ValueError):
        return 300


def _max_messages() -> int:
    """How many (most-recent) inbox messages to pull. The org receives ~700 a
    month; the lead inbox shows a recent, capped window like the pipeline does."""
    try:
        return max(1, min(500, int(os.environ.get("BASISBOARD_MAX_MESSAGES") or 200)))
    except (TypeError, ValueError):
        return 200


def _analytics_max_projects() -> int:
    """How much bid history the dashboard totals. Separate knob from the board's:
    the pipeline shows a recent window on purpose, while "All time" here means
    all time, and the org has ~3,400 bids. The default clears that with room —
    a truncated history would quietly understate every past year."""
    return _env_int("ANALYTICS_MAX_PROJECTS", 6000, 1, 20000)


def is_configured() -> bool:
    return bool(_api_key())


# ── transport ─────────────────────────────────────────────────────────
@contextmanager
def _session():
    """A pooled httpx.Client carrying auth; reused across the build's threads."""
    import httpx
    client = httpx.Client(
        timeout=_TIMEOUT,
        headers={"Authorization": f"Bearer {_api_key()}", "Accept": "application/json"},
        limits=httpx.Limits(max_connections=_CONCURRENCY, max_keepalive_connections=_CONCURRENCY),
    )
    try:
        yield client
    finally:
        client.close()


def _retry_after(resp) -> Optional[float]:
    """The server's own instruction on when to come back, if it sent one."""
    raw = (resp.headers.get("retry-after") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, min(30.0, float(raw)))              # seconds form
    except ValueError:
        return None                                          # HTTP-date form; back off normally


def _get(client, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Authenticated GET, retrying transient errors with exponential backoff.
    Raises otherwise (the assembler wraps everything).

    The backoff matters: a burst of parallel reads earns a 429, and asking for
    the whole bid history is exactly such a burst. We are a guest on their rate
    limit, so we wait as long as they ask and give up slowly rather than
    hammering. `client` is a pooled httpx.Client."""
    import httpx
    last: Exception = RuntimeError("no attempt")
    for attempt in range(_RETRIES + 1):
        _PACER.wait()
        try:
            resp = client.get(_api_base() + path, params=params)
        except httpx.TransportError as exc:                 # network blip / timeout
            last, pause = exc, None
        else:
            if resp.status_code not in _TRANSIENT:
                resp.raise_for_status()
                return resp.json()
            if resp.status_code == 429:
                _PACER.back_off()
            last = httpx.HTTPStatusError(f"transient {resp.status_code}",
                                         request=resp.request, response=resp)
            pause = _retry_after(resp)
        if attempt < _RETRIES:
            time.sleep(pause if pause is not None else _BACKOFF_BASE * (2 ** attempt))
    raise last


# ── resource fetchers (each reusable on its own) ──────────────────────
def _fetch_stages(client) -> Dict[str, Dict[str, Any]]:
    cached = _meta_cache.get("stages")
    if cached is None:
        cached = {s["id"]: s for s in (_get(client, "/stages").get("stages") or []) if s.get("id")}
        _meta_cache["stages"] = cached
    return cached


def _fetch_users(client) -> Dict[str, str]:
    """id -> display name for every user, paging until the list runs out.

    /users pages (13 at a time in the accounts we've seen) and this used to read
    only the first page, so estimators past the thirteenth silently lost their
    name — they'd show as blank on the board and would be missing from the
    analytics estimator filter entirely. Page size isn't hardcoded: keep asking
    until a page comes back empty or short."""
    cached = _meta_cache.get("users")
    if cached is None:
        cached = {}
        offset = 0
        for _ in range(_USER_PAGE_CAP):
            batch = _get(client, "/users", {"offset": offset}).get("users") or []
            if not batch:
                break
            before = len(cached)
            for u in batch:
                if not u.get("id"):
                    continue
                name = " ".join(p for p in (u.get("firstName"), u.get("lastName")) if p).strip()
                cached[u["id"]] = name or (u.get("email") or "")
            # An endpoint that ignored `offset` would hand back page one forever;
            # no new ids means we're going in circles, so stop.
            if len(cached) == before:
                break
            offset += len(batch)
        _meta_cache["users"] = cached
    return cached


def _ids_page(client, offset: int, sort: bool, page: int = _PAGE) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": page, "offset": offset}
    if sort:
        params["sort[bidDeadline]"] = "DESC"
    return _get(client, "/projects/ids", params)


def _fetch_project_ids(client, cap: int, ex: Optional[ThreadPoolExecutor] = None,
                       page: int = _PAGE):
    """Most-recent project ids up to `cap`. The first page (needed for `total`)
    is sequential; the rest fetch in parallel. Falls back to unsorted if the
    sort param is rejected. Returns (ids, total)."""
    sort = True
    try:
        first = _ids_page(client, 0, True, page)
    except Exception:                                   # noqa: BLE001 — retry unsorted
        sort, first = False, _ids_page(client, 0, False, page)
    ids: List[str] = list(first.get("projectIds") or first.get("ids") or [])
    total = (first.get("paging") or {}).get("total", len(ids))
    offsets = list(range(page, min(cap, total), page))
    if offsets:
        if ex is not None:
            pages = [f.result() for f in
                     [ex.submit(_ids_page, client, o, sort, page) for o in offsets]]
        else:
            pages = [_ids_page(client, o, sort, page) for o in offsets]
        for pg in pages:
            ids.extend(pg.get("projectIds") or pg.get("ids") or [])
    return ids[:cap], total


def _fetch_projects(client, ids: List[str], ex: Optional[ThreadPoolExecutor] = None) -> List[Dict[str, Any]]:
    """Batch-fetch project details by id (50/req), in parallel when an executor
    is given."""
    chunks = [ids[i:i + _PAGE] for i in range(0, len(ids), _PAGE)]

    def fetch(chunk):
        return _get(client, "/projects", {"filter[projectIds][]": chunk}).get("projects") or []

    if ex is not None:
        results = [f.result() for f in [ex.submit(fetch, c) for c in chunks]]
    else:
        results = [fetch(c) for c in chunks]
    out: List[Dict[str, Any]] = []
    for r in results:
        out.extend(r)
    return out


def _messages_page(client, status: str, offset: int) -> Dict[str, Any]:
    params: Dict[str, Any] = {"limit": _PAGE, "offset": offset}
    if status:
        params["filter[status]"] = status
    return _get(client, "/messages", params)


def _fetch_messages(client, status: str = "unlinked", cap: Optional[int] = None,
                    ex: Optional[ThreadPoolExecutor] = None):
    """Inbox messages for `status`, in Basisboard's own order, up to `cap`
    (default `_max_messages()`). The first page is sequential because it carries
    `paging.total`; the rest fetch in parallel when an executor is given.
    Returns (messages, total)."""
    cap = _max_messages() if cap is None else max(1, cap)
    first = _messages_page(client, status, 0)
    msgs: List[Dict[str, Any]] = list(first.get("messages") or [])
    total = (first.get("paging") or {}).get("total", len(msgs))
    offsets = list(range(_PAGE, min(cap, total), _PAGE))
    if offsets:
        if ex is not None:
            pages = [f.result() for f in [ex.submit(_messages_page, client, status, o) for o in offsets]]
        else:
            pages = [_messages_page(client, status, o) for o in offsets]
        for pg in pages:
            msgs.extend(pg.get("messages") or [])
    return msgs[:cap], total


def _fetch_message_stats(client, time_frame: str = "this-month") -> Dict[str, Any]:
    """Inbox counters (received / automaticallyProcessed / duplicatesProcessed).
    Meta-cached — they're a header stat, not something worth re-fetching per load."""
    key = f"msg_stats:{time_frame}"
    cached = _meta_cache.get(key)
    if cached is None:
        cached = _get(client, "/messages/stats", {"timeFrame": time_frame}) or {}
        _meta_cache[key] = cached
    return cached


# ── shaping + assembly ────────────────────────────────────────────────
def _dollars(cents: Any) -> Optional[float]:
    """Basisboard money fields are integer cents. Convert at the boundary so no
    caller can forget: the CRM board rendered `quote` straight through and showed
    every bid at a hundred times its real value."""
    if cents is None:
        return None
    try:
        return round(float(cents) / _CENTS, 2)
    except (TypeError, ValueError):
        return None


def _shape_project(p: Dict[str, Any], stages: Dict[str, Dict[str, Any]],
                   users: Dict[str, str]) -> Dict[str, Any]:
    st = stages.get(p.get("stageId")) or {}
    return {
        "id": p.get("id"),
        "name": p.get("name") or "Untitled",
        "location": p.get("location") if (p.get("location") and p.get("location") != "N/A") else "",
        "value": _dollars(p.get("quote")),
        "stage_id": p.get("stageId"),
        "stage_name": st.get("name") or "Unstaged",
        "stage_color": st.get("color") or "#5c403f",
        "stage_order": st.get("order", 9999),
        "estimators": [users.get(uid) for uid in (p.get("estimatorIds") or []) if users.get(uid)],
        "awarded": bool(p.get("awardedAt")),
        "archived": bool(p.get("archivedAt")),
    }


def _build_pipeline() -> Dict[str, Any]:
    """Fetch everything concurrently over one pooled client, then shape + sort."""
    with _session() as client, ThreadPoolExecutor(max_workers=_CONCURRENCY) as ex:
        f_stages = ex.submit(_fetch_stages, client)
        f_users = ex.submit(_fetch_users, client)
        pids, total = _fetch_project_ids(client, _max_projects(), ex)
        raw = _fetch_projects(client, pids, ex)
        stages, users = f_stages.result(), f_users.result()

    # Pipeline view = active bids: drop deleted + archived.
    shaped = [_shape_project(p, stages, users) for p in raw
              if not p.get("deletedAt") and not p.get("archivedAt")]
    shaped.sort(key=lambda x: (x["stage_order"], x["name"].lower()))
    stage_cols = sorted(
        ({"id": s.get("id"), "name": s.get("name"), "color": s.get("color"),
          "order": s.get("order", 9999)} for s in stages.values()),
        key=lambda s: s["order"],
    )
    return {"ok": True, "configured": True, "projects": shaped, "stages": stage_cols,
            "shown": len(shaped), "total": total}


def get_pipeline() -> Dict[str, Any]:
    """Read-only pipeline: active projects with stage + estimator names, plus the
    ordered stage columns. Cached 60 s; concurrent cold builds are coalesced.
    Returns {"ok": True, ...} or {"ok": False, "error": "<generic>"} — never raises."""
    if not is_configured():
        return {"ok": False, "configured": False, "error": "Basisboard is not configured"}
    cached = _pipeline_cache.get("pipeline")
    if cached is not None:
        return cached
    with _BUILD_LOCK:
        cached = _pipeline_cache.get("pipeline")        # another thread may have built it
        if cached is not None:
            return cached
        try:
            result = _build_pipeline()
        except Exception as exc:  # noqa: BLE001 — read view must never 500 the page
            log.warning("Basisboard get_pipeline failed: %s", exc)
            return {"ok": False, "configured": True, "error": "Couldn't reach Basisboard"}
        _pipeline_cache["pipeline"] = result
        return result


# ── inbox (lead messages) ─────────────────────────────────────────────
def _build_inbox(status: str) -> Dict[str, Any]:
    """Fetch the message pages + the stats header over one pooled client."""
    with _session() as client, ThreadPoolExecutor(max_workers=_CONCURRENCY) as ex:
        f_stats = ex.submit(_fetch_message_stats, client)
        messages, total = _fetch_messages(client, status, _max_messages(), ex)
        try:
            stats = f_stats.result()
        except Exception as exc:  # noqa: BLE001 — a header counter is not worth failing the inbox
            log.info("Basisboard message stats unavailable: %s", exc)
            stats = {}
    return {"ok": True, "configured": True, "messages": messages, "stats": stats,
            "shown": len(messages), "total": total}


def get_inbox(status: str = "unlinked") -> Dict[str, Any]:
    """Read-only lead inbox: raw Basisboard messages (unshaped — `leads.merge_inbox`
    owns the row shape) plus the month-to-date stats. Cached 60 s; concurrent cold
    builds are coalesced. Returns {"ok": True, ...} or {"ok": False, ...} — never
    raises, and always carries `messages`/`stats` so callers can iterate blindly."""
    if not is_configured():
        return {"ok": False, "configured": False, "messages": [], "stats": {},
                "error": "Basisboard is not configured"}
    cached = _inbox_cache.get(status)
    if cached is not None:
        return cached
    with _INBOX_LOCK:
        cached = _inbox_cache.get(status)            # another thread may have built it
        if cached is not None:
            return cached
        try:
            result = _build_inbox(status)
        except Exception as exc:  # noqa: BLE001 — read view must never 500 the page
            log.warning("Basisboard get_inbox failed: %s", exc)
            return {"ok": False, "configured": True, "messages": [], "stats": {},
                    "error": "Couldn't reach Basisboard"}
        _inbox_cache[status] = result
        return result


def get_message_detail(message_id: str) -> Optional[Dict[str, Any]]:
    """One message WITH its full HTML body (`{"message": {..., "body": "<html>"}}`).
    Deliberately uncached: bodies run tens of KB and are read once, when a lead
    drawer opens. Returns None on any failure — never raises."""
    if not (is_configured() and message_id):
        return None
    try:
        with _session() as client:
            return _get(client, f"/messages/{message_id}/detail")
    except Exception as exc:  # noqa: BLE001
        log.warning("Basisboard message detail %s failed: %s", message_id, exc)
        return None


def get_message_url(message_id: str) -> Optional[str]:
    """Signed URL to the raw .eml. NEVER cached — it expires after 15 minutes, so
    every read mints a fresh one. Returns None on any failure — never raises."""
    if not (is_configured() and message_id):
        return None
    try:
        with _session() as client:
            return (_get(client, f"/messages/{message_id}") or {}).get("url") or None
    except Exception as exc:  # noqa: BLE001
        log.warning("Basisboard message url %s failed: %s", message_id, exc)
        return None


# ── analytics dataset ─────────────────────────────────────────────────
# The third view, alongside the pipeline board and the lead inbox. It ships the
# whole (capped) bid history as flat rows so the BROWSER can filter and total
# them — which is the entire point of the feature. Basisboard's own analytics
# offers four fixed groupings and no way to cross them; ours lets an estimator
# ask for epoxy + gyp, Greg + Troy, awarded this quarter, in one go, and get an
# answer without a round trip.
def _fetch_trade_field_id(client) -> str:
    """UUID of the custom field holding a project's trades.

    Resolved by NAME rather than pinned, because a custom field is a customer
    setting and Kyle can recreate one. The pinned id is the fallback so a settings
    outage costs us nothing."""
    cached = _meta_cache.get("trade_field")
    if cached:
        return cached
    field_id = _TRADE_FIELD_FALLBACK
    try:
        payload = _get(client, "/custom-field-settings") or {}
        fields = payload.get("customFieldSettings") or payload.get("customFields") \
            or payload.get("settings") or []
        if isinstance(fields, dict):
            fields = list(fields.values())
        for f in fields:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            name = str(f.get("name") or "").strip().lower()
            if name in ("trade", "trades", "system type", "system types"):
                field_id = f["id"]
                break
    except Exception as exc:  # noqa: BLE001 — the fallback id is a fine answer
        log.info("Basisboard custom-field settings unavailable, using the pinned "
                 "trade field: %s", exc)
    _meta_cache["trade_field"] = field_id
    return field_id


def _fetch_projects_full(client, ids: List[str], ex: Optional[ThreadPoolExecutor] = None,
                         page: int = _PAGE):
    """Like `_fetch_projects`, but keeps the sidecar maps the plain fetch throws
    away. A project doesn't name its companies or carry a bid deadline — both
    live on the bid invites, which arrive alongside the rows.
    Returns (projects, bid_invites, companies)."""
    chunks = [ids[i:i + page] for i in range(0, len(ids), page)]

    def fetch(chunk):
        return _get(client, "/projects", {"filter[projectIds][]": chunk}) or {}

    if ex is not None:
        results = [f.result() for f in [ex.submit(fetch, c) for c in chunks]]
    else:
        results = [fetch(c) for c in chunks]

    projects: List[Dict[str, Any]] = []
    invites: Dict[str, Any] = {}
    companies: Dict[str, Any] = {}
    for r in results:
        projects.extend(r.get("projects") or [])
        invites.update(r.get("bidInvitesMap") or {})
        companies.update(r.get("companiesMap") or {})
    return projects, invites, companies


def _parse_trades(value: Any) -> List[str]:
    """A project's trades. The field is normally a list of short tags
    (["Epoxy"], ["Epoxy","Polish"]) but comes back as "" on untagged projects."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _shape_analytics_row(p: Dict[str, Any], invites: Dict[str, Any],
                         trade_field_id: str) -> Dict[str, Any]:
    """One project, flattened to what the dashboard totals. Ids stay ids — the
    browser joins them against the dimension lists, which keeps the payload small
    and the filters exact."""
    company_ids: List[str] = []
    deadlines: List[str] = []
    for bid in (p.get("bidInviteIds") or []):
        inv = invites.get(bid)
        if not isinstance(inv, dict):
            continue
        cid = inv.get("companyId")
        if cid and cid not in company_ids:
            company_ids.append(cid)
        due = inv.get("bidDeadlineAt") or inv.get("scrapedBidDeadlineAt")
        if due:
            deadlines.append(due)

    loc = p.get("location")
    return {
        "id": p.get("id"),
        "name": p.get("name") or "Untitled",
        "city": p.get("city") or "",
        "region": p.get("region") or "",
        "location": loc if (loc and loc != "N/A") else "",
        "stage_id": p.get("stageId") or "",
        "estimator_ids": [u for u in (p.get("estimatorIds") or []) if u],
        "company_ids": company_ids,
        "awarded_by_id": p.get("awardedById") or "",
        "trades": _parse_trades((p.get("customFields") or {}).get(trade_field_id)),
        "awarded_at": p.get("awardedAt"),
        "submitted_at": p.get("submittedAt"),
        "lost_at": p.get("lostAt"),
        "created_at": p.get("createdAt"),
        # Projects carry no deadline of their own; the latest invite's is the one
        # the estimating team works to.
        "bid_deadline_at": max(deadlines) if deadlines else None,
        "quote": _dollars(p.get("quote")),
        "won_amount": _dollars(p.get("wonAmount")),
        "pending_amount": _dollars(p.get("pendingAmount")),
        "submitted_amount": _dollars(p.get("submittedAmount")),
        "lost_amount": _dollars(p.get("lostAmount")),
        "archived": bool(p.get("archivedAt")),
    }


def _unnamed(kind: str, ident: str) -> str:
    """A label for an id we can't resolve. /users lists the ACTIVE users, so a
    bid an ex-estimator owned has an id with no record behind it; the same goes
    for a company that's been merged away. They still own real history, so they
    get a bucket — tagged with the id so two different unknowns don't collapse
    into one line in the filter."""
    return "Unknown " + kind + " (" + str(ident)[:8] + ")"


def _analytics_dimensions(rows: List[Dict[str, Any]], stages: Dict[str, Dict[str, Any]],
                          users: Dict[str, str], companies: Dict[str, Any]) -> Dict[str, Any]:
    """The filter vocabularies, derived from the rows themselves so a filter can
    never offer an option that matches nothing (or miss one that does)."""
    est_ids, co_ids, trades = set(), set(), set()
    for r in rows:
        est_ids.update(r["estimator_ids"])
        co_ids.update(r["company_ids"])
        if r["awarded_by_id"]:
            co_ids.add(r["awarded_by_id"])
        trades.update(r["trades"])

    def company_name(cid: str) -> str:
        c = companies.get(cid)
        return (c.get("name") if isinstance(c, dict) else None) or _unnamed("company", cid)

    def estimator_name(uid: str) -> str:
        return users.get(uid) or _unnamed("estimator", uid)

    return {
        # Every stage, including the empty ones: the board's columns shouldn't
        # appear and vanish as the date window moves.
        "stages": sorted(
            ({"id": s.get("id"), "name": s.get("name") or "Unstaged",
              "color": s.get("color") or "#5c403f", "order": s.get("order", 9999)}
             for s in stages.values()),
            key=lambda s: (s["order"], s["name"]),
        ),
        "estimators": sorted(
            ({"id": uid, "name": estimator_name(uid)} for uid in est_ids),
            key=lambda u: u["name"].lower(),
        ),
        "companies": sorted(
            ({"id": cid, "name": company_name(cid)} for cid in co_ids),
            key=lambda c: c["name"].lower(),
        ),
        "trades": sorted(trades, key=lambda t: t.lower()),
    }


def _build_analytics() -> Dict[str, Any]:
    """Fetch the bid history concurrently over one pooled client, then shape."""
    with _session() as client, ThreadPoolExecutor(max_workers=_CONCURRENCY) as ex:
        f_stages = ex.submit(_fetch_stages, client)
        f_users = ex.submit(_fetch_users, client)
        f_trade = ex.submit(_fetch_trade_field_id, client)
        pids, total = _fetch_project_ids(client, _analytics_max_projects(), ex,
                                         page=_ANALYTICS_ID_PAGE)
        raw, invites, companies = _fetch_projects_full(client, pids, ex,
                                                       page=_ANALYTICS_DETAIL_PAGE)
        stages, users, trade_field = f_stages.result(), f_users.result(), f_trade.result()

    # Analytics is the HISTORY, so archived bids stay — dropping them (as the
    # pipeline board does, to show only live work) would quietly erase closed
    # years from every total.
    rows = [_shape_analytics_row(p, invites, trade_field)
            for p in raw if not p.get("deletedAt")]
    rows.sort(key=lambda r: (r.get("created_at") or ""), reverse=True)

    out = {"ok": True, "configured": True,
           "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "stale": False, "projects": rows,
           "shown": len(rows), "total": total, "truncated": total > len(rows)}
    out.update(_analytics_dimensions(rows, stages, users, companies))
    return out


def _refresh_analytics() -> None:
    """Rebuild off the request thread.

    Reading the whole history is ~45 paced requests over about ten seconds — fast
    for what it is, still far too slow to hold a page load open, and slower again
    whenever Basisboard asks us to back off. No reader ever waits on it."""
    try:
        result = _build_analytics()
        _analytics_cache["analytics"] = result
        _analytics_last_good["snapshot"] = result
        _analytics_state["error"] = ""
        log.info("Basisboard analytics ready: %d of %d bids",
                 result.get("shown", 0), result.get("total", 0))
    except Exception as exc:  # noqa: BLE001 — a stale snapshot may still be serving
        _analytics_state["error"] = "Couldn't reach Basisboard"
        log.warning("Basisboard analytics build failed: %s", exc)
    finally:
        _analytics_state["building"] = False
        try:
            _ANALYTICS_REFRESH_LOCK.release()
        except RuntimeError:                                # already released
            pass


def _spawn(fn, name: str) -> None:
    """Run `fn` off the request thread. A seam of its own so a test can take the
    job and run it itself — patching threading.Thread wholesale also replaces the
    workers inside ThreadPoolExecutor, and the build then waits on futures no
    thread will ever complete."""
    threading.Thread(target=fn, name=name, daemon=True).start()


def _start_refresh() -> bool:
    """Kick off one background build. False if one is already running."""
    if not _ANALYTICS_REFRESH_LOCK.acquire(blocking=False):
        return False
    _analytics_state["building"] = True
    try:
        _spawn(_refresh_analytics, "bb-analytics-build")
    except Exception:                       # noqa: BLE001 — never leave it "building"
        _analytics_state["building"] = False
        _ANALYTICS_REFRESH_LOCK.release()
        raise
    return True


def get_analytics() -> Dict[str, Any]:
    """Read-only analytics dataset: every (capped) bid as a flat row, plus the
    filter vocabularies. Cached ~5 min.

    Never blocks. A cold build reads the entire bid history — ~45 requests paced
    under Basisboard's rate limit, ten seconds or so when they're feeling
    generous — so the first caller starts it and gets `building: true`,
    and an expired cache serves the last good snapshot while the new one is
    fetched behind it. Returns {"ok": True, ...} or {"ok": False, ...} — never
    raises."""
    if not is_configured():
        return {"ok": False, "configured": False, "error": "Basisboard is not configured"}

    cached = _analytics_cache.get("analytics")
    if cached is not None:
        return cached

    stale = _analytics_last_good.get("snapshot")
    if stale is not None:
        _start_refresh()
        return dict(stale, stale=True)

    # Nothing to serve yet. Start (or join) a build and say so, carrying forward
    # any previous failure: a Basisboard outage would otherwise read as a build
    # that just never finishes, and the reader would never learn why.
    _start_refresh()
    out: Dict[str, Any] = {
        "ok": True, "configured": True, "building": True, "stale": False,
        "generated_at": None, "projects": [], "stages": [], "estimators": [],
        "companies": [], "trades": [], "shown": 0, "total": 0, "truncated": False,
    }
    if _analytics_state.get("error"):
        out["last_error"] = _analytics_state["error"]
    return out
