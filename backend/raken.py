"""Connect Raken (#781): the tool's own sign-in to Raken, and the one way it calls Raken's API.

Project Analytics compares what the Treadwell Projects calendar planned with what Raken recorded
(#777). This module is the Raken half's foundation: an admin connects the tool once, the server keeps
that sign-in, renews it by itself, and every Raken call goes through one careful client. It never
writes anything to Raken.

THE SIGN-IN is Raken's OAuth 2.0 authorization-code flow (developer.rakenapp.com/api/docs):
  1. An admin presses "Connect Raken". GET /api/raken/connect (admin-only) answers with Raken's
     Allow-page address, which carries a STATE: this admin's email and a one-time nonce, encrypted
     and signed with RAKEN_TOKEN_KEY (a Fernet token, so it also carries its own age). The page
     navigates there. (The page cannot simply navigate to /api/raken/connect: this app has no
     cookies, the only credential is the Authorization header, so a navigation carries no identity.)
  2. Raken sends the browser back to RAKEN_REDIRECT_URI, which is /api/raken/callback. That GET
     carries no identity either, so it does NOTHING but bounce the code and state to the Project
     Analytics page (main.py lists it as a public GET for that reason).
  3. The page hands them to POST /api/raken/callback (admin-only). The state must decrypt with our
     key, be under STATE_TTL_S old, name THIS admin, and not have been used already; anything else
     is refused before Raken is asked. Then the code is exchanged for tokens.

THE STORED SIGN-IN is one JSON file on the data volume (TOKEN_FILE), written through
atomic_json.write_json, holding the refresh token encrypted with RAKEN_TOKEN_KEY. The key lives only
in the server environment, never on the volume (which is backed up off the box twice a day). The
access token (about 10 hours) is kept in memory only.

RENEWAL. Raken may hand back a NEW refresh token on any renewal and then refuses the old one with
400 {"error": "invalid_grant"}. So the refresh token from EVERY token response is written to the file
before the access token that came with it is used, and every renewal runs under _RENEW_LOCK, so two
renewals can never send the same refresh token. The container runs ONE uvicorn worker (Dockerfile),
so a process lock is enough; a second worker would need a file lock here. invalid_grant marks the
sign-in expired in the file (the dead token is dropped), and the page says EXPIRED_MESSAGE until an
admin connects again; Raken is not asked again with a token that is known to be dead.

THE CLIENT. Raken limits requests per second, concurrent requests and requests per day, all with a
429, and publishes no figures (they depend on the plan). So calls run ONE AT A TIME under _CALL_LOCK
with CALL_PAUSE_S between them; a 429 waits BACKOFF_S[i] and is retried at most twice, then the call
fails with a plain RakenError. A 429 that says the daily quota is used up is not retried at all.
Nothing loops: paging stops at _PAGE_CAP pages.

SECRETS. The client id, client secret, redirect address and key come only from the environment
(RAKEN_CLIENT_ID, RAKEN_CLIENT_SECRET, RAKEN_REDIRECT_URI, RAKEN_TOKEN_KEY). No token, code, secret,
key or response body is ever logged or returned; log lines carry counts and status codes only.

THE SEAMS for tests: TRANSPORT (an httpx.MockTransport standing in for Raken), TOKEN_FILE (a
temporary folder), `sleep` and `monotonic` (the clock), and reset_for_tests() (a restart).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from atomic_json import write_json

log = logging.getLogger("treadwell.raken")

AUTHORIZE_URL = "https://app.rakenapp.com/oauth/authorize"
TOKEN_URL = "https://app.rakenapp.com/oauth/token"
API_BASE = "https://developer.rakenapp.com/api"

_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
TOKEN_FILE = _DATA_DIR / "raken_signin.json"

# The address the page lands on after the callback bounce.
LANDING_PAGE = "/project-calendar.html"

STATE_TTL_S = 15 * 60          # how long an admin has on Raken's Allow page
CALL_PAUSE_S = 0.25            # the fixed pause between two Raken calls
BACKOFF_S = (2.0, 6.0)         # the waits before the first and second retry of a 429
_TOKEN_SLACK_S = 120           # renew this long before Raken says the access token expires
_PAGE_SIZE = 100
_PAGE_CAP = 50                 # at most this many pages of one listing, so paging can never loop
_CONNECT_TIMEOUT_S = 5.0
_READ_TIMEOUT_S = 20.0

STATE_CONNECTED = "connected"
STATE_NOT_CONNECTED = "not_connected"
STATE_EXPIRED = "expired"

EXPIRED_MESSAGE = "Raken sign-in has expired. An admin must Connect Raken again."
NOT_SET_UP_MESSAGE = "Raken is not set up on this server yet."
NOT_CONNECTED_MESSAGE = "Raken is not connected."
BAD_STATE_MESSAGE = ("That Raken sign-in did not start here, or took too long. "
                     "Press Connect Raken again.")
CODE_REFUSED_MESSAGE = "Raken did not accept that sign-in. Press Connect Raken again."
RATE_LIMITED_MESSAGE = "Raken is limiting requests right now. Try again later."
QUOTA_MESSAGE = "Raken's daily request limit is used up. Try again tomorrow."
UNREACHABLE_MESSAGE = "Raken could not be reached."

# Replaced by tests.
TRANSPORT: Any = None
sleep = time.sleep
monotonic = time.monotonic


class RakenError(RuntimeError):
    """A plain, showable reason a Raken step failed. Its text never holds a secret."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


class SignInExpired(RakenError):
    def __init__(self):
        super().__init__(EXPIRED_MESSAGE, 409)


# ─── config ───────────────────────────────────────────────────────────────────
def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _fernet():
    """The Fernet built from RAKEN_TOKEN_KEY, or None when the key is missing or not a Fernet key.
    Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    """
    from cryptography.fernet import Fernet
    key = _env("RAKEN_TOKEN_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None


def is_configured() -> bool:
    """All four settings present and the key usable. Logs nothing about which one is missing: the
    names include ..._SECRET, which CodeQL treats as sensitive in a log line."""
    return all(_env(n) for n in ("RAKEN_CLIENT_ID", "RAKEN_CLIENT_SECRET", "RAKEN_REDIRECT_URI")) \
        and _fernet() is not None


def _require_configured():
    if not is_configured():
        raise RakenError(NOT_SET_UP_MESSAGE, 503)


# ─── the state (who started the sign-in) ──────────────────────────────────────
_STATE_SHAPE = re.compile(r"[A-Za-z0-9_-]{40,4096}={0,2}")
_USED_NONCES: Dict[str, float] = {}
_NONCE_LOCK = threading.Lock()


def start_url(admin_email: str) -> str:
    """Raken's Allow-page address for this admin, carrying a fresh one-time state."""
    _require_configured()
    payload = json.dumps({"e": (admin_email or "").strip().lower(),
                          "n": secrets.token_urlsafe(16)})
    state = _fernet().encrypt(payload.encode("utf-8")).decode("ascii")
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": _env("RAKEN_CLIENT_ID"),
        "redirect_uri": _env("RAKEN_REDIRECT_URI"),
        "state": state,
    })


def _check_state(state: str, admin_email: str) -> None:
    """Refuse a state this server did not hand to this admin in the last STATE_TTL_S, or one
    already used. Raises RakenError(400)."""
    from cryptography.fernet import InvalidToken
    state = str(state or "")
    # Exactly one Fernet token and nothing after it: base64 decoding stops at the padding, so a
    # state with characters appended would otherwise decrypt as the original.
    if not _STATE_SHAPE.fullmatch(state):
        raise RakenError(BAD_STATE_MESSAGE, 400)
    try:
        raw = _fernet().decrypt(state.encode("ascii"), ttl=STATE_TTL_S)
        data = json.loads(raw.decode("utf-8"))
    except (InvalidToken, ValueError, UnicodeEncodeError, TypeError):
        raise RakenError(BAD_STATE_MESSAGE, 400) from None
    who = str(data.get("e") or "").encode("utf-8")
    me = (admin_email or "").strip().lower().encode("utf-8")
    if not who or not secrets.compare_digest(who, me):
        raise RakenError(BAD_STATE_MESSAGE, 400)
    nonce = str(data.get("n") or "")
    now = time.time()
    with _NONCE_LOCK:
        for n, until in list(_USED_NONCES.items()):
            if until < now:
                del _USED_NONCES[n]
        if not nonce or nonce in _USED_NONCES:
            raise RakenError(BAD_STATE_MESSAGE, 400)
        _USED_NONCES[nonce] = now + STATE_TTL_S


def landing_for(params: Dict[str, str]) -> str:
    """Where the callback bounce sends the browser: the page, with ONLY the code, state and error
    Raken sent, renamed so they cannot collide with the page's own parameters."""
    out = {}
    for name in ("code", "state", "error"):
        v = params.get(name)
        if v:
            out["raken_" + name] = str(v)[:2048]
    return LANDING_PAGE + ("?" + urllib.parse.urlencode(out) if out else "")


# ─── the stored sign-in ───────────────────────────────────────────────────────
# In memory: the access token and when to stop using it. The refresh token lives only in the file.
_ACCESS: Dict[str, Any] = {"token": None, "until": 0.0}
_RENEW_LOCK = threading.Lock()
_FILE_LOCK = threading.Lock()


def _read_file() -> Dict[str, Any]:
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("raken: the stored sign-in is unreadable (%s)", type(exc).__name__)
        return {"expired": True}
    return data if isinstance(data, dict) else {"expired": True}


def _write_file(refresh_token: Optional[str], expired: bool = False) -> None:
    payload: Dict[str, Any] = {"version": 1, "expired": bool(expired),
                               "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if refresh_token:
        payload["refresh_token"] = _fernet().encrypt(refresh_token.encode("utf-8")).decode("ascii")
    with _FILE_LOCK:
        write_json(TOKEN_FILE, payload)


def _stored_refresh_token() -> Tuple[str, Optional[str]]:
    """(state, refresh token or None) from the file."""
    from cryptography.fernet import InvalidToken
    data = _read_file()
    enc = data.get("refresh_token")
    if data.get("expired") or (data and not enc):
        return STATE_EXPIRED, None
    if not enc:
        return STATE_NOT_CONNECTED, None
    try:
        return STATE_CONNECTED, _fernet().decrypt(str(enc).encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeEncodeError):
        # The key changed since it was saved: only a new sign-in can fix that.
        log.warning("raken: the stored sign-in cannot be read with the current key")
        return STATE_EXPIRED, None


def signin_state() -> str:
    if not is_configured():
        return STATE_NOT_CONNECTED
    return _stored_refresh_token()[0]


def _http():
    import httpx
    return httpx.Client(timeout=httpx.Timeout(_READ_TIMEOUT_S, connect=_CONNECT_TIMEOUT_S),
                        transport=TRANSPORT)


def _oauth_error(resp) -> str:
    """The OAuth `error` code of a token response, "" when there is none. Nothing else is read."""
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001 - not JSON
        return ""
    err = body.get("error") if isinstance(body, dict) else None
    return err if isinstance(err, str) else ""


def _token_request(form: Dict[str, str]) -> Dict[str, Any]:
    """POST the token endpoint. Answers its JSON body, raises RakenError or SignInExpired."""
    form = dict(form, client_id=_env("RAKEN_CLIENT_ID"), client_secret=_env("RAKEN_CLIENT_SECRET"))
    try:
        with _http() as http:
            resp = http.post(TOKEN_URL, data=form)
    except Exception as exc:  # noqa: BLE001 - any network failure is "unreachable"
        log.warning("raken: token endpoint unreachable (%s)", type(exc).__name__)
        raise RakenError(UNREACHABLE_MESSAGE) from None
    if resp.status_code != 200:
        code = _oauth_error(resp)
        log.warning("raken: token endpoint answered %s %s", resp.status_code,
                    code if code in ("invalid_grant", "invalid_client", "invalid_request") else "")
        if resp.status_code == 400 and code == "invalid_grant":
            raise SignInExpired()
        raise RakenError(UNREACHABLE_MESSAGE)
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not body.get("access_token"):
        log.warning("raken: token endpoint answered without an access token")
        raise RakenError(UNREACHABLE_MESSAGE)
    return body


def _keep_access(body: Dict[str, Any]) -> str:
    try:
        lifetime = float(body.get("expires_in") or 0)
    except (TypeError, ValueError):
        lifetime = 0.0
    _ACCESS["token"] = str(body["access_token"])
    _ACCESS["until"] = monotonic() + lifetime - _TOKEN_SLACK_S
    return _ACCESS["token"]


def finish_sign_in(code: str, state: str, admin_email: str) -> None:
    """Check the state, exchange the code, save the refresh token. Raises RakenError."""
    _require_configured()
    _check_state(state, admin_email)
    if not code:
        raise RakenError(CODE_REFUSED_MESSAGE, 400)
    with _RENEW_LOCK:
        try:
            body = _token_request({"grant_type": "authorization_code", "code": str(code),
                                   "redirect_uri": _env("RAKEN_REDIRECT_URI")})
        except SignInExpired:
            raise RakenError(CODE_REFUSED_MESSAGE, 400) from None
        refresh = body.get("refresh_token")
        if not refresh:
            log.warning("raken: the sign-in answered without a refresh token")
            raise RakenError(CODE_REFUSED_MESSAGE, 400)
        _write_file(str(refresh))                      # saved BEFORE the access token is used
        _keep_access(body)
    _forget_summary()
    log.info("raken: connected")


def _renew() -> str:
    """A fresh access token from the stored refresh token. Call with _RENEW_LOCK held."""
    state, refresh = _stored_refresh_token()
    if state != STATE_CONNECTED or not refresh:
        _ACCESS["token"] = None
        if state == STATE_EXPIRED:
            raise SignInExpired()
        raise RakenError(NOT_CONNECTED_MESSAGE, 409)
    try:
        body = _token_request({"grant_type": "refresh_token", "refresh_token": refresh})
    except SignInExpired:
        _ACCESS["token"] = None
        _write_file(None, expired=True)
        log.warning("raken: the sign-in was refused at renewal; an admin must connect again")
        raise
    # Raken may rotate it; when it does not, the one we sent stays good.
    _write_file(str(body.get("refresh_token") or refresh))   # saved BEFORE the access token is used
    log.info("raken: sign-in renewed (refresh token %s)",
             "rotated" if body.get("refresh_token") and body.get("refresh_token") != refresh
             else "kept")
    return _keep_access(body)


def access_token() -> str:
    """A usable access token, renewing under the lock when the one in memory is stale. A second
    caller that waited on the lock reuses the token the first one got, never renewing again with
    the refresh token the first one already spent."""
    _require_configured()
    with _RENEW_LOCK:
        token = _ACCESS.get("token")
        if token and monotonic() < _ACCESS["until"]:
            return token
        return _renew()


# ─── the client ───────────────────────────────────────────────────────────────
_CALL_LOCK = threading.Lock()
_LAST_CALL: Dict[str, float] = {"at": float("-inf")}
_CALLS: Dict[str, int] = {"n": 0}


def _is_quota(resp) -> bool:
    try:
        text = resp.text or ""
    except Exception:  # noqa: BLE001
        return False
    return "limit exceeded" in text.lower()


def get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET one Raken API path, one call at a time with CALL_PAUSE_S between calls. A 401 renews
    the sign-in and tries once more; a 429 is retried at most len(BACKOFF_S) times. Raises
    RakenError (or SignInExpired) with a plain message."""
    with _CALL_LOCK:
        renewed = False
        tries_429 = 0
        while True:   # bounded: at most one renewal and len(BACKOFF_S) retries, then it raises
            token = access_token()
            wait = _LAST_CALL["at"] + CALL_PAUSE_S - monotonic()
            if wait > 0:
                sleep(wait)
            try:
                with _http() as http:
                    resp = http.get(API_BASE + path, params=params or {},
                                    headers={"Authorization": "Bearer " + token,
                                             "Accept": "application/json"})
            except Exception as exc:  # noqa: BLE001
                log.warning("raken: GET %s unreachable (%s)", path, type(exc).__name__)
                raise RakenError(UNREACHABLE_MESSAGE) from None
            finally:
                _LAST_CALL["at"] = monotonic()
                _CALLS["n"] += 1
            if resp.status_code == 401 and not renewed:
                renewed = True
                with _RENEW_LOCK:
                    if _ACCESS.get("token") == token:
                        _ACCESS["token"] = None
                continue
            if resp.status_code == 429:
                if _is_quota(resp):
                    log.warning("raken: GET %s refused, daily quota used up", path)
                    raise RakenError(QUOTA_MESSAGE, 429)
                if tries_429 >= len(BACKOFF_S):
                    log.warning("raken: GET %s still 429 after %d retries", path, tries_429)
                    raise RakenError(RATE_LIMITED_MESSAGE, 429)
                sleep(BACKOFF_S[tries_429])
                tries_429 += 1
                continue
            if resp.status_code != 200:
                log.warning("raken: GET %s answered %s", path, resp.status_code)
                raise RakenError(UNREACHABLE_MESSAGE)
            try:
                return resp.json()
            except ValueError:
                raise RakenError(UNREACHABLE_MESSAGE) from None


def list_all(path: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every item of a paged Raken collection ({"page": {...nextOffset}, "collection": [...]}),
    page after page, never in parallel, at most _PAGE_CAP pages."""
    items: List[Dict[str, Any]] = []
    offset = 0
    for _ in range(_PAGE_CAP):
        body = get(path, dict(params or {}, limit=_PAGE_SIZE, offset=offset))
        coll = body.get("collection") if isinstance(body, dict) else None
        items.extend(x for x in (coll if isinstance(coll, list) else []) if isinstance(x, dict))
        page = body.get("page") if isinstance(body, dict) else None
        nxt = page.get("nextOffset") if isinstance(page, dict) else None
        if not isinstance(nxt, int) or nxt <= offset:
            return items
        offset = nxt
    log.warning("raken: GET %s stopped after %d pages", path, _PAGE_CAP)
    return items


# ─── status, for the Connect Raken control ────────────────────────────────────
_SUMMARY: Dict[str, Any] = {"at": float("-inf"), "body": None}
_SUMMARY_LOCK = threading.Lock()


def _summary_ttl_s() -> float:
    try:
        return max(0.0, float(os.environ.get("RAKEN_STATUS_TTL_S") or 600))
    except (TypeError, ValueError):
        return 600.0


def _forget_summary() -> None:
    with _SUMMARY_LOCK:
        _SUMMARY["at"], _SUMMARY["body"] = float("-inf"), None


def _project_summary() -> Dict[str, Any]:
    """How many Raken projects there are, how many carry a Project Number, and up to five of the
    numbers: the check on real data that Raken's Project Number holds our Job numbers."""
    with _SUMMARY_LOCK:
        if _SUMMARY["body"] is not None and monotonic() - _SUMMARY["at"] < _summary_ttl_s():
            return dict(_SUMMARY["body"])
    before = _CALLS["n"]
    projects = list_all("/projects")
    numbers = [str(p.get("number") or "").strip() for p in projects]
    with_number = [n for n in numbers if n]
    examples: List[str] = []
    for n in with_number:
        if n not in examples:
            examples.append(n)
        if len(examples) == 5:
            break
    body = {"projects": len(projects), "with_number": len(with_number), "examples": examples,
            "message": "Connected: %d Raken project%s, %d with a Project Number"
                       % (len(projects), "" if len(projects) == 1 else "s", len(with_number))}
    log.info("raken: status read %d projects in %d calls", len(projects), _CALLS["n"] - before)
    with _SUMMARY_LOCK:
        _SUMMARY["at"], _SUMMARY["body"] = monotonic(), dict(body)
    return body


def status() -> Dict[str, Any]:
    """connected / not_connected / expired, with a plain message, and the project counts when
    connected. Never raises; a failed read keeps state "connected" and says why in `error`."""
    if not is_configured():
        return {"ok": True, "configured": False, "state": STATE_NOT_CONNECTED,
                "message": NOT_SET_UP_MESSAGE}
    state = signin_state()
    if state == STATE_NOT_CONNECTED:
        return {"ok": True, "configured": True, "state": state, "message": NOT_CONNECTED_MESSAGE}
    if state == STATE_EXPIRED:
        return {"ok": True, "configured": True, "state": state, "message": EXPIRED_MESSAGE}
    try:
        summary = _project_summary()
    except SignInExpired:
        return {"ok": True, "configured": True, "state": STATE_EXPIRED, "message": EXPIRED_MESSAGE}
    except RakenError as exc:
        return {"ok": True, "configured": True, "state": STATE_CONNECTED,
                "message": "Connected.", "error": exc.message}
    return dict(summary, ok=True, configured=True, state=STATE_CONNECTED)


def reset_for_tests() -> None:
    """Forget everything held in memory, as a restart does. The file stays."""
    _ACCESS["token"], _ACCESS["until"] = None, 0.0
    _LAST_CALL["at"] = float("-inf")
    _CALLS["n"] = 0
    with _NONCE_LOCK:
        _USED_NONCES.clear()
    _forget_summary()
