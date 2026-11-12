"""The Project Calendar: a READ-ONLY view of the crews' job schedule, which lives in ONE Google
calendar ("Treadwell Projects", America/Chicago).

ONE CALENDAR, EVER. The calendar id comes from PROJECT_CALENDAR_ID and is never written into this
repo (it is public). Nothing here lists calendars, reads `primary`, or takes a calendar id from a
caller: `fetch()` reads the env var and hands exactly that id to the source. The service account
is shared that one calendar only, so even a bug here could not read another, and the scope is
calendar.events.readonly, so nothing here could write one either.

THE CONNECTION is a Google service account: its key is GOOGLE_SERVICE_ACCOUNT_JSON (the JSON text)
or GOOGLE_SERVICE_ACCOUNT_FILE (a path). The access token is minted with the OAuth JWT bearer grant
(PyJWT RS256 + httpx, both already dependencies) and cached until a minute before it expires. The
key and the token are never logged. Missing env = "not connected": the API answers
connected:false and the page says so; nothing errors.

THE SEAM. A "calendar source" is anything with `list_events(calendar_id, time_min, time_max)`
returning Google-shaped event dicts. ServiceAccountSource is the real one; tests swap in a fake by
monkeypatching `_make_source`. Everything else - title parsing, dates, colour, workdays, deadline,
sorting, caching, stale serving, project matching - is behind `fetch()`, which the route calls.

THE TITLE CONVENTION is free text typed by the people who book crews, for example
    "26.125, Acme Clinic Psych (6) (Pat)"
    "G25.110, The Example Lofts (3rd and 2nd) - 2nd Mob - (PW) (8) (Sam)"
    "Example Punch - (1) (Lee)"      "Example Shop (3) Night Work"      "Example Patch?"
Job number, Crew size, Mobilization, Crew lead, Punch, prevailing wage and night work are read out
of it (see `parse_title`). Parsing never throws and never drops an event: what does not parse stays
in the title, and `name` is whatever is left once the recognised parts are taken out.

RED MEANS A DURATION. Google colorId "11" (Tomato) marks the bar as the job's Duration and its last
day as the job's Deadline. Every other colour is shown as Google draws it and means nothing here.

DATES ARE CENTRAL. An all-day event's end.date is EXCLUSIVE in Google, so its last day is the day
before. A timed event's start and end are converted to the America/Chicago date. "Today" is never
taken from a naive datetime.now(): the dev box runs ~13 hours ahead of Central.

A GOOGLE FAILURE NEVER 500s THE PAGE. The last good result per requested range is kept in memory
and served with stale:true; with nothing to fall back on the answer is ok:true, events:[], and a
short plain error. Version 1 stores nothing of its own and never writes to Google.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

import cachetools

log = logging.getLogger("treadwell.project_calendar")

CENTRAL = ZoneInfo("America/Chicago")

SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"

# The widest range one request may ask for, in days, inclusive of both ends.
MAX_SPAN_DAYS = 120

# Google's event palette (colorId -> hex), as Google Calendar draws it.
PALETTE: Dict[str, str] = {
    "1": "#7986cb", "2": "#33b679", "3": "#8e24aa", "4": "#e67c73", "5": "#f6bf26",
    "6": "#f4511e", "7": "#039be5", "8": "#616161", "9": "#3f51b5", "10": "#0b8043",
    "11": "#d50000",
}
DURATION_COLOR_ID = "11"  # Tomato: the bar is the job's Duration; its last day is the Deadline.

# Upstream limits. Bounded so a slow Google cannot hold a worker: the page waits at most
# _TIMEOUT per call, and at most _PAGE_CAP pages of _PAGE_SIZE events per range.
_PAGE_SIZE = 250
_PAGE_CAP = 8
_CONNECT_TIMEOUT_S = 5.0
_READ_TIMEOUT_S = 10.0

# Refresh a cached access token this long before Google says it expires.
_TOKEN_SLACK_S = 60
# After a failed call to Google, answer from the cache (or the plain error) without calling Google
# again for this long, so a slow or failing Google cannot queue every request behind it.
_BACKOFF_S = 45.0

_ERR_UPSTREAM = "Google Calendar could not be reached."


class RangeError(ValueError):
    """The requested range is not a range this API serves (the route turns it into a 400)."""


# ─── config ───────────────────────────────────────────────────────────────────
def calendar_id() -> str:
    return (os.environ.get("PROJECT_CALENDAR_ID") or "").strip()


def _ttl_s() -> float:
    try:
        return max(0.0, float(os.environ.get("PROJECT_CALENDAR_TTL_S") or 300))
    except (TypeError, ValueError):
        return 300.0


def _service_account_info() -> Optional[Dict[str, Any]]:
    """The service-account key as a dict, or None when it is not configured or unreadable.

    The reason a key is unusable is logged; the key itself never is."""
    raw = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or "").strip()
    path = (os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE") or "").strip()
    try:
        if not raw and path:
            with open(path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        if not raw:
            return None
        info = json.loads(raw)
    except (OSError, ValueError) as exc:
        log.warning("project calendar: service-account key unreadable (%s)", type(exc).__name__)
        return None
    if not isinstance(info, dict) or not info.get("client_email") or not info.get("private_key"):
        log.warning("project calendar: service-account key is missing client_email/private_key")
        return None
    return info


# ─── the source seam ──────────────────────────────────────────────────────────
class CalendarSource(Protocol):
    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> List[Dict[str, Any]]:
        """Google-shaped event dicts overlapping [time_min, time_max). Raises on any failure."""


class ServiceAccountSource:
    """Reads ONE calendar's events as a Google service account. Read-only by scope.

    `transport` exists for tests (an httpx.MockTransport); production leaves it None."""

    def __init__(self, info: Dict[str, Any], transport: Any = None):
        self._email = str(info["client_email"])
        self._key = str(info["private_key"])
        self._token_uri = str(info.get("token_uri") or TOKEN_URL)
        self._transport = transport
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self._lock = threading.Lock()
        self._mint_lock = threading.Lock()
        self._backoff_until = 0.0

    def _client(self):
        import httpx
        return httpx.Client(timeout=httpx.Timeout(_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S),
                            transport=self._transport)

    def _cached_token(self) -> Optional[str]:
        with self._lock:
            if self._token and time.time() < self._token_exp - _TOKEN_SLACK_S:
                return self._token
        return None

    def _access_token(self, client) -> str:
        """A valid access token. The state lock is never held across the network: one request
        mints (single-flight) while the others wait a bounded time and then reuse its token."""
        token = self._cached_token()
        if token:
            return token
        if not self._mint_lock.acquire(timeout=_CONNECT_TIMEOUT_S + _READ_TIMEOUT_S):
            raise RuntimeError("token mint still in progress")
        try:
            token = self._cached_token()          # another request may have minted while we waited
            if token:
                return token
            import jwt
            now = int(time.time())
            assertion = jwt.encode({"iss": self._email, "scope": SCOPE, "aud": self._token_uri,
                                    "iat": now, "exp": now + 3600},
                                   self._key, algorithm="RS256")
            resp = client.post(self._token_uri, data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion})
            if resp.status_code != 200:
                # The body can echo the request; only the status is logged.
                raise RuntimeError("token endpoint answered %s" % resp.status_code)
            body = resp.json()
            token = body.get("access_token")
            if not token:
                raise RuntimeError("token endpoint returned no access_token")
            with self._lock:
                self._token = str(token)
                self._token_exp = time.time() + float(body.get("expires_in") or 3600)
                return self._token
        finally:
            self._mint_lock.release()

    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> List[Dict[str, Any]]:
        if time.time() < self._backoff_until:
            raise RuntimeError("backing off after a recent Google failure")
        try:
            return self._list_events(calendar_id, time_min, time_max)
        except Exception:
            self._backoff_until = time.time() + _BACKOFF_S
            raise

    def _list_events(self, calendar_id: str, time_min: str, time_max: str) -> List[Dict[str, Any]]:
        url = "%s/calendars/%s/events" % (API_BASE, quote(calendar_id, safe=""))
        out: List[Dict[str, Any]] = []
        with self._client() as client:
            token = self._access_token(client)
            page_token: Optional[str] = None
            for _ in range(_PAGE_CAP):
                params = {"singleEvents": "true", "orderBy": "startTime",
                          "timeZone": "America/Chicago", "timeMin": time_min,
                          "timeMax": time_max, "maxResults": str(_PAGE_SIZE)}
                if page_token:
                    params["pageToken"] = page_token
                resp = client.get(url, params=params,
                                  headers={"Authorization": "Bearer " + token,
                                           "Accept": "application/json"})
                if resp.status_code == 401:
                    # A token revoked early: forget it so the next request mints a fresh one.
                    with self._lock:
                        self._token = None
                if resp.status_code != 200:
                    raise RuntimeError("events.list answered %s" % resp.status_code)
                body = resp.json()
                out.extend(i for i in (body.get("items") or []) if isinstance(i, dict))
                page_token = body.get("nextPageToken")
                if not page_token:
                    break
            else:
                log.warning("project calendar: stopped after %d pages; the range was truncated",
                            _PAGE_CAP)
        return out


# One real source per process, so its token cache survives between requests. Rebuilt if the key
# in the environment changes.
_SOURCE: Dict[str, Any] = {"key": None, "source": None}
_SOURCE_LOCK = threading.Lock()


def _make_source() -> Optional[CalendarSource]:
    """The configured source, or None when no service-account key is configured. Tests replace this."""
    info = _service_account_info()
    if info is None:
        return None
    key = (info.get("client_email"), info.get("private_key_id"), info.get("private_key"))
    with _SOURCE_LOCK:
        if _SOURCE["key"] != key:
            _SOURCE["key"], _SOURCE["source"] = key, ServiceAccountSource(info)
        return _SOURCE["source"]


# ─── title parsing ────────────────────────────────────────────────────────────
_JOB_RE = re.compile(r"^\s*([A-Za-z]?\d+\.\d+)\s*,\s*")
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_MOB_RE = re.compile(r"\b(\d+)\s*(?:st|nd|rd|th)\s+mob\b\.?", re.IGNORECASE)
_PUNCH_RE = re.compile(r"\bpunch\b", re.IGNORECASE)
_NIGHT_RE = re.compile(r"\bnight\s*work\b", re.IGNORECASE)
_INT_RE = re.compile(r"^\s*(\d{1,3})\s*$")
_PW_RE = re.compile(r"^\s*pw\s*$", re.IGNORECASE)
# A crew lead: one or two words of letters (an apostrophe, hyphen or full stop allowed inside).
_NAME_RE = re.compile(r"^\s*([A-Za-z][A-Za-z'.-]*(?: [A-Za-z][A-Za-z'.-]*)?)\s*$")


def _tidy(text: str) -> str:
    """Collapse what stripping leaves behind: runs of separators, empty parens, stray spaces."""
    t = re.sub(r"\(\s*\)", " ", text)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*-\s*(?:-\s*)+", " - ", t)          # "- -" -> "-"
    t = re.sub(r"\s+([,?!])", r"\1", t)
    t = re.sub(r"^[\s,;:-]+|[\s,;:-]+$", "", t)       # leading/trailing separators
    return t.strip()


def parse_title(title: Any) -> Dict[str, Any]:
    """Read the booking convention out of an event title. Never raises.

    Returns name, job_number, crew_size, mobilization, crew_lead, is_punch, prevailing_wage,
    night_work. Anything not recognised stays in `name`; a title with nothing recognisable comes
    back as its own (tidied) name."""
    raw = str(title or "")
    out: Dict[str, Any] = {"name": raw.strip(), "job_number": None, "crew_size": None,
                           "mobilization": None, "crew_lead": None, "is_punch": False,
                           "prevailing_wage": False, "night_work": False}
    try:
        rest = raw
        m = _JOB_RE.match(rest)
        if m:
            out["job_number"] = m.group(1).upper()
            rest = rest[m.end():]

        # The Crew lead is the LAST parenthesis, and only when nothing but whitespace follows it.
        parens = list(_PAREN_RE.finditer(rest))
        if parens and not rest[parens[-1].end():].strip():
            last = parens[-1]
            inner = last.group(1)
            nm = _NAME_RE.match(inner)
            if (nm and not _PW_RE.match(inner) and not _NIGHT_RE.search(inner)
                    and not _PUNCH_RE.search(inner)):
                out["crew_lead"] = nm.group(1)
                rest = rest[:last.start()] + " " + rest[last.end():]

        # Crew size (the last bare integer wins) and the prevailing-wage flag, removed from the name.
        def _paren(match: "re.Match[str]") -> str:
            inner = match.group(1)
            im = _INT_RE.match(inner)
            if im:
                out["crew_size"] = int(im.group(1))
                return " "
            if _PW_RE.match(inner):
                out["prevailing_wage"] = True
                return " "
            return match.group(0)

        rest = _PAREN_RE.sub(_paren, rest)

        mobs = list(_MOB_RE.finditer(rest))
        if mobs:
            out["mobilization"] = int(mobs[-1].group(1))
            rest = _MOB_RE.sub(" ", rest)

        if _NIGHT_RE.search(rest):
            out["night_work"] = True
            rest = _NIGHT_RE.sub(" ", rest)

        # Punch stays in the name: "Example Punch" reads better than "Example".
        out["is_punch"] = bool(_PUNCH_RE.search(raw))

        name = _tidy(rest)
        out["name"] = name or raw.strip()
    except Exception as exc:  # noqa: BLE001 — a title that breaks the parser still shows, as typed
        log.warning("project calendar: title not parsed (%s)", type(exc).__name__)
        out.update(name=raw.strip(), job_number=None, crew_size=None, mobilization=None,
                   crew_lead=None, is_punch=False, prevailing_wage=False, night_work=False)
    return out


# ─── dates ────────────────────────────────────────────────────────────────────
def today_central() -> _dt.date:
    """Today in Central. Never naive datetime.now(): the dev box runs ~13 hours ahead."""
    return _dt.datetime.now(CENTRAL).date()


def _parse_day(value: Any) -> Optional[_dt.date]:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return None
    try:
        return _dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def _to_central(value: Any, tz_name: Any) -> Optional[_dt.datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        when = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        try:
            when = when.replace(tzinfo=ZoneInfo(str(tz_name)) if tz_name else CENTRAL)
        except Exception:  # noqa: BLE001 — an unknown zone name: read it as Central
            when = when.replace(tzinfo=CENTRAL)
    return when.astimezone(CENTRAL)


def event_days(event: Dict[str, Any]) -> Optional[Tuple[_dt.date, _dt.date]]:
    """(start, last_day), inclusive, as Central dates. None when the event has no usable start."""
    start = event.get("start") or {}
    end = event.get("end") or {}
    if not isinstance(start, dict) or not isinstance(end, dict):
        return None
    if start.get("date"):
        first = _parse_day(start.get("date"))
        if first is None:
            return None
        end_excl = _parse_day(end.get("date"))
        last = (end_excl - _dt.timedelta(days=1)) if end_excl else first
        return first, max(first, last)
    begin = _to_central(start.get("dateTime"), start.get("timeZone"))
    if begin is None:
        return None
    finish = _to_central(end.get("dateTime"), end.get("timeZone") or start.get("timeZone"))
    if finish is None or finish <= begin:
        return begin.date(), begin.date()
    last = finish.date()
    # An event that ends exactly at midnight does not occupy the day it ends on.
    if finish.time() == _dt.time(0, 0) and last > begin.date():
        last -= _dt.timedelta(days=1)
    return begin.date(), last


def workdays(first: _dt.date, last: _dt.date) -> int:
    """Monday-to-Friday days in first..last inclusive. Weekends never count."""
    if last < first:
        return 0
    days = (last - first).days + 1
    weeks, extra = divmod(days, 7)
    count = weeks * 5
    wd = first.weekday()
    for i in range(extra):
        if (wd + i) % 7 < 5:
            count += 1
    return count


def parse_range(start: Any, end: Any) -> Tuple[_dt.date, _dt.date]:
    """Validate the query range. Raises RangeError with a plain message."""
    first, last = _parse_day(start), _parse_day(end)
    if first is None or last is None:
        raise RangeError("start and end must be dates written YYYY-MM-DD.")
    if last < first:
        raise RangeError("end must not be before start.")
    if (last - first).days + 1 > MAX_SPAN_DAYS:
        raise RangeError("A range may cover at most %d days." % MAX_SPAN_DAYS)
    return first, last


def _rfc3339_midnight(day: _dt.date) -> str:
    return _dt.datetime(day.year, day.month, day.day, tzinfo=CENTRAL).isoformat()


# ─── one event ────────────────────────────────────────────────────────────────
def _shape(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The contract's event, minus `project`. None for an event that cannot be placed on a day."""
    if str(event.get("status") or "").lower() == "cancelled":
        return None
    days = event_days(event)
    if days is None:
        return None
    first, last = days
    title = str(event.get("summary") or "")
    parsed = parse_title(title)
    color_id = event.get("colorId")
    color_id = str(color_id) if color_id not in (None, "") else None
    is_duration = color_id == DURATION_COLOR_ID
    link = event.get("htmlLink")
    return {
        "id": str(event.get("id") or ""),
        "title": title,
        "name": parsed["name"],
        "job_number": parsed["job_number"],
        "crew_size": parsed["crew_size"],
        "mobilization": parsed["mobilization"],
        "crew_lead": parsed["crew_lead"],
        "is_punch": parsed["is_punch"],
        "prevailing_wage": parsed["prevailing_wage"],
        "night_work": parsed["night_work"],
        "color_id": color_id,
        "color": PALETTE.get(color_id) if color_id else None,
        "is_duration": is_duration,
        "start": first.isoformat(),
        "last_day": last.isoformat(),
        "workdays": workdays(first, last),
        "deadline": last.isoformat() if is_duration else None,
        "project": None,
        "html_link": str(link) if isinstance(link, str) and link else None,
    }


# ─── project matching ─────────────────────────────────────────────────────────
def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes") if value is not None else False


def _projects_by_job_number(job_numbers: Iterable[str]) -> Dict[str, Dict[str, str]]:
    """{job number: {"id", "name"}} for the tool Projects carrying these job numbers.

    ONE projected query per request (four scalars per draft, never the blob), filtered to the job
    numbers on screen. Archived drafts are a fallback only; the earliest draft wins, which is the
    home scope of a scope group. Any failure means no matches: the calendar still renders."""
    wanted = sorted({j for j in job_numbers if j})[:200]
    if not wanted:
        return {}
    try:
        from supabase_client import get_client
        res = (get_client().table("drafts")
               .select("id,created_at,job_number:data->>job_number,"
                       "project_name:data->>project_name,archived:data->>archived")
               .is_("deleted_at", "null")
               .in_("data->>job_number", wanted)
               .execute())
        rows = res.data or []
    except Exception as exc:  # noqa: BLE001
        log.warning("project calendar: project lookup failed (%s)", type(exc).__name__)
        return {}
    best: Dict[str, Tuple[Tuple[int, str, str], Dict[str, str]]] = {}
    for r in rows:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        job = str(r.get("job_number") or "").strip().upper()
        if job not in wanted:
            continue
        rank = (1 if _truthy(r.get("archived")) else 0, str(r.get("created_at") or ""), str(r["id"]))
        if job not in best or rank < best[job][0]:
            best[job] = (rank, {"id": str(r["id"]),
                                "name": str(r.get("project_name") or "").strip() or job})
    return {job: proj for job, (_rank, proj) in best.items()}


# ─── the one function the route calls ─────────────────────────────────────────
# The last good result per (calendar, range): (monotonic time it was fetched, ISO fetched_at,
# shaped events). Fresh within the TTL; past it, still served (stale) when Google fails. An LRU so a
# person paging through months cannot grow it without bound.
_CACHE: "cachetools.LRUCache[Tuple[str, str, str], Tuple[float, str, List[Dict[str, Any]]]]" = \
    cachetools.LRUCache(maxsize=64)
_CACHE_LOCK = threading.Lock()


def cache_clear() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _response(connected: bool, events: List[Dict[str, Any]], *, stale: bool = False,
              fetched_at: Optional[str] = None, error: Optional[str] = None) -> Dict[str, Any]:
    return {"ok": True, "connected": connected, "stale": stale, "fetched_at": fetched_at,
            "error": error, "events": events}


def fetch(start: Any, end: Any) -> Dict[str, Any]:
    """The whole feature: events overlapping [start, end] (inclusive, Central), shaped per the
    contract. Raises RangeError for a bad range; otherwise never raises."""
    first, last = parse_range(start, end)
    cal = calendar_id()
    source = _make_source() if cal else None
    if not cal or source is None:
        return _response(False, [])

    key = (cal, first.isoformat(), last.isoformat())
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    stale = False
    error: Optional[str] = None
    if cached is not None and time.monotonic() - cached[0] < _ttl_s():
        fetched_at, events = cached[1], cached[2]
    else:
        try:
            raw = source.list_events(cal, _rfc3339_midnight(first),
                                     _rfc3339_midnight(last + _dt.timedelta(days=1)))
            events = []
            for item in raw or []:
                if not isinstance(item, dict):
                    continue
                shaped = _shape(item)
                if shaped is None:
                    continue
                # Google filters by the window already; re-checked here so the contract holds
                # whatever the source returned.
                if shaped["last_day"] < key[1] or shaped["start"] > key[2]:
                    continue
                events.append(shaped)
            events.sort(key=lambda e: (e["start"], e["title"].lower(), e["title"], e["id"]))
            fetched_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with _CACHE_LOCK:
                _CACHE[key] = (time.monotonic(), fetched_at, events)
        except Exception as exc:  # noqa: BLE001 — a Google failure must never 500 the page
            log.warning("project calendar: fetch failed (%s: %s)", type(exc).__name__,
                        str(exc)[:120] if isinstance(exc, RuntimeError) else "-")
            error = _ERR_UPSTREAM
            if cached is None:
                return _response(True, [], error=error)
            stale, fetched_at, events = True, cached[1], cached[2]

    # Project links are looked up on every request (one query), so a job number saved a moment
    # ago shows up without waiting for the Google cache to expire. Copies, so the cache stays clean.
    matches = _projects_by_job_number(e["job_number"] for e in events if e["job_number"])
    out = []
    for e in events:
        row = dict(e)
        proj = matches.get(e["job_number"]) if e["job_number"] else None
        row["project"] = dict(proj) if proj else None
        out.append(row)
    return _response(True, out, stale=stale, fetched_at=fetched_at, error=error)
