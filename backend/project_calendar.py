"""The Project Calendar: a READ-ONLY view of the crews' job schedule, which lives in ONE Google
calendar ("Treadwell Projects", America/Chicago).

ONE CALENDAR, EVER. The calendar id comes from PROJECT_CALENDAR_ID and is never written into this
repo (it is public). Nothing here lists calendars, reads `primary`, or takes a calendar id from a
caller: `fetch()` reads the env var and hands exactly that id to the source. The scope is
calendar.events.readonly, so nothing here could write a calendar either.

THE CONNECTION, two ways, the first that is fully configured wins:
  1. AS A PERSON (OAuthUserSource): GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET +
     GOOGLE_OAUTH_REFRESH_TOKEN, made once by backend/google_calendar_oauth.py. This is the live
     setup (decided 2026-11-12): the calendar's owner is a Workspace account whose policy caps
     sharing with outside accounts at free/busy, so a service account would only ever see opaque
     "busy" blocks. Google has no per-calendar OAuth scope, so the guard is this code: it only
     ever asks for PROJECT_CALENDAR_ID's events, with the narrowest read-only scope, and the
     refresh token lives only in the server .env. One or two of the three set is a mistake, not
     a fallback: the calendar reads "not connected" and a warning says how many of the three are missing.
  2. AS A SERVICE ACCOUNT (ServiceAccountSource): GOOGLE_SERVICE_ACCOUNT_JSON (the JSON text) or
     GOOGLE_SERVICE_ACCOUNT_FILE (a path), minted with the JWT bearer grant (PyJWT RS256).
Both share one base (_GoogleSource): events.list paging, a single-flight token cached until a
minute before it expires, a bounded wait, and the backoff after a failure. No key, secret or token
is ever logged. Nothing configured = "not connected": the API answers connected:false and the page
says so; nothing errors.

THE SEAM. A "calendar source" is anything with `list_events(calendar_id, time_min, time_max)`
returning Google-shaped event dicts (an EventList, which also carries the calendar's accessRole).
It raises CalendarError, whose `reason` fetch() turns into a plain message for the page. Tests swap
in a fake by monkeypatching `_make_source`. Everything else - title parsing, dates, colour,
workdays, deadline, sorting, caching, stale serving, project matching - is behind `fetch()`.

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
short plain error. `error` is set ONLY when the read failed; a read that worked but hides what the
page is for (free/busy access) says so in `notice` instead, so an empty month read that way is an
empty month, not a failure. Version 1 stores nothing of its own and never writes to Google.

WHAT THE PAGE SAYS, AND WHAT AN ADMIN DOES ABOUT IT. The MESSAGES are for staff: plain words, no
file paths, no console menus. The fix for each lives here, in .env.example and in the setup
script's own output:
  * "expired or was removed" (signin_revoked): run backend/google_calendar_oauth.py again, signed
    in as the calendar's owner, and replace the three GOOGLE_OAUTH_* lines in the host .env.
  * "free/busy times" (free_busy): the connected account is not the owner. Run the same script
    signed in with the Google account that OWNS the calendar.
  * "API is turned off" (api_disabled): in the Google Cloud project that holds the OAuth client,
    APIs & Services > Library > "Google Calendar API" > Enable.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Protocol, Set, Tuple
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

# The plain words the page shows, one per failure reason. Keyed on CalendarError.reason, never on
# an exception's text.
REASON_UPSTREAM = "upstream"
REASON_SIGNIN = "signin_revoked"
REASON_NOT_SHARED = "not_shared"
REASON_FORBIDDEN = "forbidden"
REASON_FREE_BUSY = "free_busy"
REASON_API_OFF = "api_disabled"

_ERR_UPSTREAM = "Google Calendar could not be reached."
MESSAGES: Dict[str, str] = {
    REASON_UPSTREAM: _ERR_UPSTREAM,
    REASON_SIGNIN: ("The Google sign-in for the Project Calendar has expired or was removed. "
                    "An admin needs to reconnect the Google sign-in."),
    REASON_NOT_SHARED: ("The Treadwell Projects calendar isn't shared with the connected Google "
                        "account. An admin needs to share it with that account."),
    REASON_FORBIDDEN: ("The connected Google account isn't allowed to read the Treadwell Projects "
                       "calendar."),
    # The Workspace policy caps sharing with outside accounts at free/busy, so "share it with
    # more" cannot be followed; connecting as the calendar's owner can.
    REASON_FREE_BUSY: ("The connected Google account can only see free/busy times on this "
                       "calendar, so titles and colours are hidden. An admin needs to reconnect "
                       "the sign-in as the calendar's owner."),
    REASON_API_OFF: ("The Google Calendar API is turned off for the Project Calendar's Google "
                     "sign-in. An admin needs to turn it on."),
}

# A 403 from Google is also how it says "slow down". Those are a passing outage, not a refusal.
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded",
                                 "dailyLimitExceeded"})
# A 403 that means the Calendar API was never enabled in the Cloud project: the legacy
# errors[].reason, and the google.rpc.ErrorInfo reason in error.details[].
_API_OFF_REASONS = frozenset({"accessNotConfigured", "SERVICE_DISABLED"})

OAUTH_ENV = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN")


class RangeError(ValueError):
    """The requested range is not a range this API serves (the route turns it into a 400)."""


class CalendarError(RuntimeError):
    """A failed read of the calendar. `reason` is one of the REASON_* codes; the text is for the
    log only and never holds a key, secret, token or response body. `backing_off` is True when
    Google was not asked at all because a recent failure is still being waited out, so that
    failure must not restart the wait."""

    def __init__(self, reason: str, detail: str = "", backing_off: bool = False):
        super().__init__(detail or reason)
        self.reason = reason if reason in MESSAGES else REASON_UPSTREAM
        self.backing_off = backing_off


def message_for(exc: BaseException) -> str:
    """The page's plain message for a failed read. Anything that is not a CalendarError is an
    unreachable Google."""
    return MESSAGES[exc.reason] if isinstance(exc, CalendarError) else _ERR_UPSTREAM


class EventList(list):
    """The events of one read, plus the calendar's accessRole as Google reported it (None when the
    source does not know)."""
    access_role: Optional[str] = None


# ─── config ───────────────────────────────────────────────────────────────────
# A shared calendar's id ends with this. "primary", or a person's own address, would read that
# person's OWN calendar (with the OAuth sign-in, Hanz's), so neither is ever accepted: the same
# rule backend/google_calendar_oauth.py applies before it opens the browser.
SHARED_CALENDAR_SUFFIX = "@group.calendar.google.com"
_BAD_ID_WARNED: set = set()
_BAD_ID_WARNED_LOCK = threading.Lock()


def is_shared_calendar_id(value: str) -> bool:
    cal = (value or "").strip().lower()
    return bool(cal) and cal != "primary" and cal.endswith(SHARED_CALENDAR_SUFFIX)


def calendar_id() -> str:
    """PROJECT_CALENDAR_ID when it names a shared calendar, else "" (the page then says "not
    connected"). A wrong id is logged once, without its value, which may be someone's address."""
    raw = (os.environ.get("PROJECT_CALENDAR_ID") or "").strip()
    if raw and not is_shared_calendar_id(raw):
        with _BAD_ID_WARNED_LOCK:
            first = raw not in _BAD_ID_WARNED
            _BAD_ID_WARNED.add(raw)
        if first:
            log.warning("project calendar: PROJECT_CALENDAR_ID is not a shared calendar's id (it "
                        "must end with %s); not connected", SHARED_CALENDAR_SUFFIX)
        return ""
    return raw


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


def _oauth_config() -> Tuple[str, Optional[Tuple[str, str, str]], Tuple[str, ...]]:
    """What the environment says about the Google sign-in, read only (it logs nothing):
    ("none", None, ()), ("full", (client_id, client_secret, refresh_token), ()) or
    ("partial", None, <the names of the missing variables>)."""
    vals = tuple((os.environ.get(name) or "").strip() for name in OAUTH_ENV)
    if all(vals):
        return "full", (vals[0], vals[1], vals[2]), ()
    if not any(vals):
        return "none", None, ()
    return "partial", None, _missing_oauth_names()


def _missing_oauth_names() -> Tuple[str, ...]:
    """The NAMES of the sign-in variables that are not set. Built from the constant names alone,
    never from a tuple that also holds the values, so nothing secret can travel toward the log
    line that reports a half-finished setup (CodeQL py/clear-text-logging-sensitive-data)."""
    return tuple(name for name in OAUTH_ENV if not _env_is_set(name))


def _env_is_set(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


# The partial-sign-in gaps already logged, so a half-finished setup warns once per distinct gap,
# not on every request. Emptied once the setup is whole (or gone), so a later gap warns again.
_PARTIAL_WARNED: Set[Tuple[str, ...]] = set()
_PARTIAL_WARNED_LOCK = threading.Lock()


def _warn_partial_once(missing: Tuple[str, ...]) -> None:
    """Log a partial sign-in once per distinct gap. It says HOW MANY of the three are missing and
    names none of them: CodeQL treats the variable name ..._CLIENT_SECRET itself as sensitive data
    (py/clear-text-logging-sensitive-data), and with three variables the count is enough."""
    with _PARTIAL_WARNED_LOCK:
        first = missing not in _PARTIAL_WARNED
        _PARTIAL_WARNED.add(missing)
    if first:
        log.warning("project calendar: the Google sign-in is only partly configured (%d of the 3 "
                    "GOOGLE_OAUTH_* values missing), so the calendar is not connected", len(missing))


def _forget_partial_warnings() -> None:
    with _PARTIAL_WARNED_LOCK:
        _PARTIAL_WARNED.clear()


# ─── the source seam ──────────────────────────────────────────────────────────
class CalendarSource(Protocol):
    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> List[Dict[str, Any]]:
        """Google-shaped event dicts overlapping [time_min, time_max). Raises on any failure,
        a CalendarError when the reason is known."""


def _google_error(resp: Any) -> Tuple[str, FrozenSet[str]]:
    """(OAuth `error`, the API error reasons) out of a Google error body, blank/empty when absent.
    The reasons are every error.errors[].reason and every error.details[].reason (Google's
    ErrorInfo). Only these short codes are ever read out of a body; the body is never logged."""
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 — not JSON: no codes
        return "", frozenset()
    if not isinstance(body, dict):
        return "", frozenset()
    err = body.get("error")
    if isinstance(err, str):
        return err, frozenset()
    reasons = set()
    if isinstance(err, dict):
        for key in ("errors", "details"):
            items = err.get(key)
            for item in (items if isinstance(items, list) else []):
                reason = item.get("reason") if isinstance(item, dict) else None
                if isinstance(reason, str) and reason:
                    reasons.add(reason)
    return "", frozenset(reasons)


class _GoogleSource:
    """What every real source shares: read ONE calendar's events, read-only by scope.

    A subclass only says how to ask the token endpoint for an access token (`_grant_form`). The
    paging, the single-flight token cache, the bounded wait, the backoff and the error reasons
    live here, so the two connections behave the same and are tested once.

    `transport` exists for tests (an httpx.MockTransport); production leaves it None."""

    # Token-endpoint `error` codes (on a 400 or 401) that mean the sign-in itself is broken, so
    # only reconnecting fixes it. None here: for a service account's JWT grant, invalid_grant
    # usually means clock skew or a deleted key, and there is no sign-in to reconnect.
    _SIGNIN_ERRORS: FrozenSet[str] = frozenset()

    def __init__(self, token_uri: str, transport: Any = None):
        self._token_uri = token_uri or TOKEN_URL
        self._transport = transport
        self._token: Optional[str] = None
        self._token_exp = 0.0
        self._lock = threading.Lock()
        self._mint_lock = threading.Lock()
        self._backoff_until = 0.0
        self._backoff_reason = REASON_UPSTREAM

    def _grant_form(self) -> Dict[str, str]:  # pragma: no cover - every subclass defines it
        raise NotImplementedError

    def _client(self):
        import httpx
        return httpx.Client(timeout=httpx.Timeout(_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S),
                            transport=self._transport)

    def _cached_token(self) -> Optional[str]:
        with self._lock:
            if self._token and time.time() < self._token_exp - _TOKEN_SLACK_S:
                return self._token
        return None

    def _backing_off(self) -> CalendarError:
        # Say the same thing the failure said: a revoked sign-in stays "reconnect it".
        return CalendarError(self._backoff_reason, "backing off after a recent Google failure",
                             backing_off=True)

    def _note_failure(self, exc: BaseException) -> None:
        self._backoff_reason = exc.reason if isinstance(exc, CalendarError) else REASON_UPSTREAM
        self._backoff_until = time.time() + _BACKOFF_S

    def _drop_token(self, token: str) -> None:
        """Forget `token`, unless another request has already replaced it."""
        with self._lock:
            if self._token == token:
                self._token = None

    def _access_token(self, client) -> str:
        """A valid access token. The state lock is never held across the network: one request
        mints (single-flight) while the others wait a bounded time and then reuse its token, or
        take its failure: the backoff is set before the mint lock is released, so a burst that
        arrives during a failing mint asks the token endpoint once, not once per request."""
        token = self._cached_token()
        if token:
            return token
        if not self._mint_lock.acquire(timeout=_CONNECT_TIMEOUT_S + _READ_TIMEOUT_S):
            raise CalendarError(REASON_UPSTREAM, "token mint still in progress")
        try:
            if time.time() < self._backoff_until:
                raise self._backing_off()
            token = self._cached_token()          # another request may have minted while we waited
            if token:
                return token
            try:
                return self._mint(client)
            except Exception as exc:
                self._note_failure(exc)
                raise
        finally:
            self._mint_lock.release()

    def _mint(self, client) -> str:
        resp = client.post(self._token_uri, data=self._grant_form())
        if resp.status_code != 200:
            # The body can echo the request: only its `error` code is read, only the status
            # and that code are logged.
            code, _reasons = _google_error(resp)
            if resp.status_code in (400, 401) and code in self._SIGNIN_ERRORS:
                raise CalendarError(REASON_SIGNIN, "token endpoint answered %s %s"
                                    % (resp.status_code, code))
            raise CalendarError(REASON_UPSTREAM, "token endpoint answered %s" % resp.status_code)
        body = resp.json()
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            raise CalendarError(REASON_UPSTREAM, "token endpoint returned no access_token")
        with self._lock:
            self._token = str(token)
            self._token_exp = time.time() + float(body.get("expires_in") or 3600)
            return self._token

    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> EventList:
        if time.time() < self._backoff_until:
            raise self._backing_off()
        try:
            return self._list_events(calendar_id, time_min, time_max)
        except Exception as exc:
            if not (isinstance(exc, CalendarError) and exc.backing_off):
                self._note_failure(exc)
            raise

    @staticmethod
    def _events_page(client, url: str, params: Dict[str, str], token: str):
        """One events.list GET with `token`. The only place the request is written."""
        return client.get(url, params=params, headers={"Authorization": "Bearer " + token,
                                                       "Accept": "application/json"})

    def _list_events(self, calendar_id: str, time_min: str, time_max: str) -> EventList:
        url = "%s/calendars/%s/events" % (API_BASE, quote(calendar_id, safe=""))
        out = EventList()
        with self._client() as client:
            token = self._access_token(client)
            retried = False
            page_token: Optional[str] = None
            for _ in range(_PAGE_CAP):
                params = {"singleEvents": "true", "orderBy": "startTime",
                          "timeZone": "America/Chicago", "timeMin": time_min,
                          "timeMax": time_max, "maxResults": str(_PAGE_SIZE)}
                if page_token:
                    params["pageToken"] = page_token
                resp = self._events_page(client, url, params, token)
                if resp.status_code == 401 and not retried:
                    # A token revoked early (the app's access removed, say): forget it and mint
                    # once more in this request, so a dead sign-in says so (an admin must reconnect it) now
                    # rather than "could not be reached" for a backoff window first.
                    retried = True
                    self._drop_token(token)
                    token = self._access_token(client)
                    resp = self._events_page(client, url, params, token)
                if resp.status_code == 401:
                    self._drop_token(token)       # the next request mints a fresh one
                if resp.status_code == 404:
                    raise CalendarError(REASON_NOT_SHARED, "events.list answered 404")
                if resp.status_code == 403:
                    _code, reasons = _google_error(resp)
                    if reasons & _RATE_LIMIT_REASONS:
                        raise CalendarError(REASON_UPSTREAM, "events.list answered 403 %s"
                                            % ",".join(sorted(reasons & _RATE_LIMIT_REASONS)))
                    if reasons & _API_OFF_REASONS:
                        raise CalendarError(REASON_API_OFF,
                                            "events.list answered 403 (Calendar API not enabled)")
                    raise CalendarError(REASON_FORBIDDEN, "events.list answered 403")
                if resp.status_code != 200:
                    raise CalendarError(REASON_UPSTREAM, "events.list answered %s" % resp.status_code)
                body = resp.json()
                if not isinstance(body, dict):
                    raise CalendarError(REASON_UPSTREAM, "events.list returned no object")
                role = body.get("accessRole")
                if isinstance(role, str) and role and out.access_role is None:
                    out.access_role = role
                out.extend(i for i in (body.get("items") or []) if isinstance(i, dict))
                page_token = body.get("nextPageToken")
                if not page_token:
                    break
            else:
                log.warning("project calendar: stopped after %d pages; the range was truncated",
                            _PAGE_CAP)
        return out


class ServiceAccountSource(_GoogleSource):
    """Reads ONE calendar's events as a Google service account (JWT bearer grant)."""

    def __init__(self, info: Dict[str, Any], transport: Any = None):
        super().__init__(str(info.get("token_uri") or TOKEN_URL), transport)
        self._email = str(info["client_email"])
        self._key = str(info["private_key"])

    def _grant_form(self) -> Dict[str, str]:
        import jwt
        now = int(time.time())
        assertion = jwt.encode({"iss": self._email, "scope": SCOPE, "aud": self._token_uri,
                                "iat": now, "exp": now + 3600},
                               self._key, algorithm="RS256")
        return {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion}


class OAuthUserSource(_GoogleSource):
    """Reads ONE calendar's events as the person who signed in once with
    backend/google_calendar_oauth.py (the refresh-token grant). The scope was fixed at that
    sign-in to calendar.events.readonly; which calendar is read is fixed by fetch()."""

    # A revoked or expired refresh token (invalid_grant), and a deleted, rotated or mistyped
    # OAuth client (invalid_client, deleted_client, unauthorized_client): re-running
    # backend/google_calendar_oauth.py is the only fix, so the page says an admin needs to reconnect the sign-in.
    _SIGNIN_ERRORS = frozenset({"invalid_grant", "invalid_client", "deleted_client",
                                "unauthorized_client"})

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 transport: Any = None):
        super().__init__(TOKEN_URL, transport)
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token

    def _grant_form(self) -> Dict[str, str]:
        return {"client_id": self._client_id, "client_secret": self._client_secret,
                "refresh_token": self._refresh_token, "grant_type": "refresh_token"}


# One real source per process, so its token cache survives between requests. Rebuilt when the
# configuration in the environment changes.
_SOURCE: Dict[str, Any] = {"key": None, "source": None}
_SOURCE_LOCK = threading.Lock()


def _make_source() -> Optional[CalendarSource]:
    """The configured source, or None when nothing (or only part of the sign-in) is configured.

    A full Google sign-in wins over a service account; a partial one connects nothing, so a
    half-finished switch never falls back to the account that only sees free/busy. Tests
    replace this."""
    state, oauth, missing = _oauth_config()
    if state == "partial":
        _warn_partial_once(missing)
        return None
    _forget_partial_warnings()
    if oauth is not None:
        key: Tuple[Any, ...] = ("oauth",) + oauth
        build = lambda: OAuthUserSource(*oauth)  # noqa: E731
    else:
        info = _service_account_info()
        if info is None:
            return None
        key = ("sa", info.get("client_email"), info.get("private_key_id"), info.get("private_key"),
               info.get("token_uri"))
        build = lambda: ServiceAccountSource(info)  # noqa: E731
    with _SOURCE_LOCK:
        if _SOURCE["key"] != key:
            _SOURCE["key"], _SOURCE["source"] = key, build()
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


def rfc3339_midnight(day: _dt.date) -> str:
    """Central midnight at the start of `day`, RFC 3339 (the offset follows DST)."""
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
# shaped events, the notice that read carried or None). Fresh within the TTL; past it, still served
# (stale) when Google fails. An LRU so a person paging through months cannot grow it without bound.
_CACHE: ("cachetools.LRUCache[Tuple[str, str, str], "
         "Tuple[float, str, List[Dict[str, Any]], Optional[str]]]") = cachetools.LRUCache(maxsize=64)
_CACHE_LOCK = threading.Lock()


def cache_clear() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def _response(connected: bool, events: List[Dict[str, Any]], *, stale: bool = False,
              fetched_at: Optional[str] = None, error: Optional[str] = None,
              notice: Optional[str] = None) -> Dict[str, Any]:
    """`error`: the read failed (events are a stale copy, or none). `notice`: the read worked, but
    something about the connection needs fixing (free/busy access). Never the same message."""
    return {"ok": True, "connected": connected, "stale": stale, "fetched_at": fetched_at,
            "error": error, "notice": notice, "events": events}


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
    notice: Optional[str] = None
    if cached is not None and time.monotonic() - cached[0] < _ttl_s():
        fetched_at, events, notice = cached[1], cached[2], cached[3]
    else:
        try:
            raw = source.list_events(cal, rfc3339_midnight(first),
                                     rfc3339_midnight(last + _dt.timedelta(days=1)))
            # Free/busy access is a read that worked but hides what the page is for: keep the
            # (title-less, colourless) blocks Google sent and say how to fix it, as a notice.
            notice = (MESSAGES[REASON_FREE_BUSY]
                      if getattr(raw, "access_role", None) == "freeBusyReader" else None)
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
                _CACHE[key] = (time.monotonic(), fetched_at, events, notice)
        except Exception as exc:  # noqa: BLE001 — a Google failure must never 500 the page
            # A CalendarError's text is written by this module and never holds a secret; any other
            # exception's text might, so only its type is logged.
            log.warning("project calendar: fetch failed (%s: %s)", type(exc).__name__,
                        str(exc)[:120] if isinstance(exc, CalendarError) else "-")
            error = message_for(exc)
            if cached is None:
                return _response(True, [], error=error)
            stale, fetched_at, events, notice = True, cached[1], cached[2], cached[3]

    # Project links are looked up on every request (one query), so a job number saved a moment
    # ago shows up without waiting for the Google cache to expire. Copies, so the cache stays clean.
    matches = _projects_by_job_number(e["job_number"] for e in events if e["job_number"])
    out = []
    for e in events:
        row = dict(e)
        proj = matches.get(e["job_number"]) if e["job_number"] else None
        row["project"] = dict(proj) if proj else None
        out.append(row)
    return _response(True, out, stale=stale, fetched_at=fetched_at, error=error, notice=notice)
