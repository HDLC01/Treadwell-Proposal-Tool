"""
One-time Google sign-in for the Project Calendar. Run LOCALLY, on your own PC, never on the server.

Before the first run, in Google Cloud (signed in as the calendar's owner):
    1. APIs & Services > Library: enable "Google Calendar API" (without it every read is a 403).
    2. OAuth consent screen: user type "Internal" (or External, then "Publish app").
    3. Credentials > Create OAuth client ID, type "Desktop app"; download its JSON. A "Web
       application" client is refused: only a Desktop client may redirect to any loopback port.
Then sign in, in the browser, with the Google account that OWNS the calendar.

Usage:
    backend/.venv/Scripts/python.exe backend/google_calendar_oauth.py \
        --client-file <the downloaded OAuth client JSON> [--out <path>] [--calendar-id <id>]

It opens your browser at Google's consent page (scope calendar.events.readonly only), catches the
answer on a loopback address on this PC (127.0.0.1, a port the OS picks), swaps it for a refresh
token, reads the Project Calendar once to prove it works, and writes three lines

    GOOGLE_OAUTH_CLIENT_ID=...
    GOOGLE_OAUTH_CLIENT_SECRET=...
    GOOGLE_OAUTH_REFRESH_TOKEN=...

to --out, owner-only where the OS allows it. The default is OUTSIDE the repo, in your home folder:
~/.treadwell/google-calendar-oauth.env (the folder is made owner-only too). An --out inside the
repo is refused unless git ignores it (checked with `git check-ignore`; without git, refused), so
the secrets cannot end up in a commit of this public repo. Copy the lines into the host .env.

The calendar id comes from --calendar-id or PROJECT_CALENDAR_ID. It must be the shared Project
Calendar's own id, which ends with @group.calendar.google.com (Google Calendar > the calendar's
Settings > Integrate calendar > Calendar ID). "primary", anyone's own main calendar, is refused
before the browser opens.

When the server's Project Calendar page reports a problem, the fix is:
  * the sign-in "has expired or was removed": run this script again and replace the three lines;
  * "can only see free/busy times": run it again, signed in as the calendar's OWNER;
  * "the Google Calendar API is turned off": step 1 above, in the project that holds the client.

It prints the file's PATH, never its contents: no client secret, code, access token or refresh
token is ever printed. The browser wait gives up after five minutes.
"""
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_CALENDAR_SUFFIX = "@group.calendar.google.com"
WAIT_S = 5 * 60

_CLOSE_PAGE = (b"<!doctype html><meta charset=utf-8><title>Project Calendar</title>"
               b"<p style='font-family:sans-serif'>Done. You can close this tab.</p>")


class SetupError(Exception):
    """A plain, printable reason the setup stopped. Never carries a secret."""


# ─── pure helpers (tested without a browser or a network) ─────────────────────
def parse_client_file(text: str) -> Tuple[str, str]:
    """(client_id, client_secret) from a Google OAuth Desktop client's JSON ("installed")."""
    try:
        data = json.loads(text)
    except ValueError:
        raise SetupError("The client file is not JSON. Download it again from Google Cloud "
                         "(APIs & Services > Credentials).") from None
    if not isinstance(data, dict):
        raise SetupError("The client file is not a Google OAuth client.")
    block = data.get("installed")
    if not isinstance(block, dict) and isinstance(data.get("web"), dict):
        # Only a Desktop client gets Google's any-port loopback redirect; a Web client's random
        # port is refused in the browser (redirect_uri_mismatch) and the wait would just time out.
        raise SetupError("This is a Web application client; create an OAuth client ID of type "
                         "Desktop app.")
    if not isinstance(block, dict):
        raise SetupError("The client file has no \"installed\" section. Use the JSON of an OAuth "
                         "client ID (type Desktop app), not a service-account key.")
    cid = str(block.get("client_id") or "").strip()
    secret = str(block.get("client_secret") or "").strip()
    if not cid or not secret:
        raise SetupError("The client file is missing client_id or client_secret.")
    return cid, secret


def new_state() -> str:
    return secrets.token_urlsafe(32)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_pkce() -> Tuple[str, str]:
    """(code_verifier, S256 code_challenge). The verifier is 86 unreserved characters (RFC 7636
    allows 43 to 128)."""
    verifier = secrets.token_urlsafe(64)
    return verifier, pkce_challenge(verifier)


def build_auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",       # a refresh token, not only a one-hour access token
        "prompt": "consent",            # ask again, so Google issues a refresh token every time
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


def code_from_callback(query: Mapping[str, Any], expected_state: str) -> str:
    """The authorization code from the loopback redirect's query, after checking its state."""
    def one(name: str) -> str:
        v = query.get(name)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else ""
        return str(v or "")

    # Bytes, not str: compare_digest raises TypeError on a non-ASCII str, and any local request
    # can reach the loopback port while the script waits.
    if not secrets.compare_digest(one("state").encode("utf-8"), expected_state.encode("utf-8")):
        raise SetupError("The answer from the browser did not match this sign-in (state "
                         "mismatch). Nothing was saved. Run the script again.")
    if one("error"):
        raise SetupError("Google did not grant access (%s). Nothing was saved."
                         % one("error")[:60])
    code = one("code")
    if not code:
        raise SetupError("The browser came back without a code. Nothing was saved.")
    return code


def check_tokens(tokens: Mapping[str, Any]) -> str:
    """The refresh token out of the code exchange's answer, or a SetupError saying what is wrong."""
    granted = str(tokens.get("scope") or "").split()
    if granted and SCOPE not in granted:
        raise SetupError("The calendar permission was not ticked on Google's consent page. "
                         "Nothing was saved. Run the script again and allow it.")
    refresh = str(tokens.get("refresh_token") or "")
    if not refresh:
        raise SetupError("Google sent no refresh token, so the server could not stay signed in. "
                         "Nothing was saved. Remove this app's access at "
                         "https://myaccount.google.com/permissions and run the script again.")
    return refresh


def check_calendar_id(calendar_id: Optional[str]) -> str:
    """The Project Calendar's id, or a SetupError. Only a shared calendar's id is accepted (it
    ends with @group.calendar.google.com): "primary", or anyone's own address, would read a
    person's own calendar instead."""
    cal = (calendar_id or "").strip()
    if not cal:
        raise SetupError("No calendar to check: pass --calendar-id or set PROJECT_CALENDAR_ID.")
    if cal.lower() == "primary" or not cal.lower().endswith(SHARED_CALENDAR_SUFFIX):
        raise SetupError("That is not the Project Calendar's id. Use the shared calendar's own id, "
                         "which ends with %s (Google Calendar > the calendar's Settings > "
                         "Integrate calendar > Calendar ID). \"primary\", your own main calendar, "
                         "is never read. Nothing was saved." % SHARED_CALENDAR_SUFFIX)
    return cal


def default_out() -> Path:
    """Where the three lines go by default: the home folder, outside any repo."""
    return Path.home() / ".treadwell" / "google-calendar-oauth.env"


def check_out_path(path: Path, repo: Path = REPO_ROOT,
                   run: Callable[..., Any] = subprocess.run) -> Path:
    """The absolute --out path, or a SetupError when it is inside the repo and git does not ignore
    it (this repo is public). Asked of git itself (`git check-ignore -q`); if git cannot answer, a
    path inside the repo is refused. A path outside the repo is never checked."""
    target = Path(path).expanduser().resolve()
    root = Path(repo).resolve()
    try:
        rel = target.relative_to(root)
    except ValueError:
        return target
    try:
        done = run(["git", "check-ignore", "-q", rel.as_posix()], cwd=str(root),
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=15)
        ignored = done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ignored = False
    if not ignored:
        raise SetupError("%s is inside the repository and git does not ignore it, so the secrets "
                         "could end up in a commit. Nothing was saved. Leave --out off (the "
                         "default is %s) or pick a folder outside the repository."
                         % (target, default_out()))
    return target


def env_text(client_id: str, client_secret: str, refresh_token: str) -> str:
    return ("GOOGLE_OAUTH_CLIENT_ID=%s\nGOOGLE_OAUTH_CLIENT_SECRET=%s\n"
            "GOOGLE_OAUTH_REFRESH_TOKEN=%s\n" % (client_id, client_secret, refresh_token))


def _ensure_folder(folder: Path) -> None:
    """Make `folder` (and its parents) when missing. A folder made here is owner-only where the
    OS supports it (0700 on POSIX); one that already exists is left as it is."""
    if folder.is_dir():
        return
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(str(folder), 0o700)


def write_env_file(path: Path, text: str) -> Path:
    """Write the three lines, owner-only where the OS supports it (0600 on POSIX; on Windows the
    file keeps the folder's permissions). A missing folder is made owner-only too. Returns the
    absolute path.

    An existing file keeps its old mode through os.open, so the mode is narrowed on the open
    descriptor BEFORE anything is written: a 0644 file never holds the secrets."""
    path = Path(path).expanduser().resolve()
    _ensure_folder(path.parent)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if hasattr(os, "fchmod"):             # POSIX; Windows (before 3.13) has none and needs none
        try:
            os.fchmod(fd, 0o600)
        except OSError as exc:
            os.close(fd)
            raise SetupError("Could not make %s owner-only (%s). Nothing was saved."
                             % (path, type(exc).__name__)) from None
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _server():
    """The server's own project_calendar module, so the check reads the way the page does."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import project_calendar
    return project_calendar


def month_bounds(today: _dt.date) -> Tuple[str, str]:
    """[first of this month, first of next month) at Central midnight, RFC 3339."""
    pc = _server()
    first = today.replace(day=1)
    nxt = (first + _dt.timedelta(days=32)).replace(day=1)
    return pc.rfc3339_midnight(first), pc.rfc3339_midnight(nxt)


def summarize(events: Any) -> Dict[str, Any]:
    """What the check prints: the access role, how many events, how many carry a title."""
    live = [e for e in (events or []) if isinstance(e, dict)
            and str(e.get("status") or "").lower() != "cancelled"]
    return {"access_role": getattr(events, "access_role", None) or "unknown",
            "events": len(live),
            "titled": sum(1 for e in live if str(e.get("summary") or "").strip())}


# ─── the network steps ────────────────────────────────────────────────────────
def exchange_code(client_id: str, client_secret: str, code: str, verifier: str,
                  redirect_uri: str, transport: Any = None) -> Dict[str, Any]:
    import httpx
    with httpx.Client(timeout=20.0, transport=transport) as client:
        resp = client.post(TOKEN_URL, data={
            "client_id": client_id, "client_secret": client_secret, "code": code,
            "code_verifier": verifier, "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"})
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code != 200 or not isinstance(body, dict):
        err = body.get("error") if isinstance(body, dict) else None
        raise SetupError("Google refused the code (HTTP %s%s). Nothing was saved."
                         % (resp.status_code, ", " + str(err)[:60] if err else ""))
    return body


def verify(client_id: str, client_secret: str, refresh_token: str, calendar_id: str,
           today: Optional[_dt.date] = None, transport: Any = None) -> Dict[str, Any]:
    """Read this month of the one calendar through the server's own OAuthUserSource."""
    pc = _server()
    src = pc.OAuthUserSource(client_id, client_secret, refresh_token, transport=transport)
    lo, hi = month_bounds(today or pc.today_central())
    try:
        events = src.list_events(calendar_id, lo, hi)
    except Exception as exc:  # noqa: BLE001 — say it plainly, never the exception's text
        # The page's message says WHAT is wrong; here, at the console, also say HOW to fix it.
        how = {pc.REASON_API_OFF: " Turn it on in Google Cloud, in the project that holds the "
                                  "OAuth client: APIs & Services > Library > Google Calendar API "
                                  "> Enable. Then run this script again.",
               pc.REASON_SIGNIN: " Run this script again."}
        reason = exc.reason if isinstance(exc, pc.CalendarError) else None
        raise SetupError("The sign-in was saved, but reading the calendar failed: %s%s"
                         % (pc.message_for(exc), how.get(reason, ""))) from None
    return summarize(events)


def _wait_for_code(state: str, client_id: str, challenge: str,
                   open_browser: bool = True) -> Tuple[str, str]:
    """(code, redirect_uri). Serves ONE loopback redirect, then stops; gives up after WAIT_S."""
    got: Dict[str, Any] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        timeout = 5    # a browser's idle pre-connect must not hold the one-thread server

        def do_GET(self):  # noqa: N802 — the stdlib's name
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            got["query"] = urllib.parse.parse_qs(parsed.query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(_CLOSE_PAGE)

        def log_message(self, *args):    # the default logs the request line, code included
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1.0
    redirect_uri = "http://127.0.0.1:%d/" % server.server_address[1]
    url = build_auth_url(client_id, redirect_uri, state, challenge)
    print("Opening your browser to sign in to Google. If it does not open, paste this address:")
    print(url)
    if open_browser:
        webbrowser.open(url)
    deadline = time.monotonic() + WAIT_S
    try:
        while "query" not in got:
            if time.monotonic() > deadline:
                raise SetupError("Gave up after %d minutes waiting for the browser. Nothing was "
                                 "saved." % (WAIT_S // 60))
            server.handle_request()
    finally:
        server.server_close()
    return code_from_callback(got["query"], state), redirect_uri


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="One-time Google sign-in for the Project Calendar.")
    ap.add_argument("--client-file", required=True,
                    help="the OAuth client JSON downloaded from Google Cloud (Desktop app)")
    ap.add_argument("--out", default=None,
                    help="where to write the three env lines (default: %s, outside the repo; "
                         "a path inside the repo must be git-ignored)" % default_out())
    ap.add_argument("--calendar-id", default=None,
                    help="the calendar to check, ending with %s (default: PROJECT_CALENDAR_ID)"
                         % SHARED_CALENDAR_SUFFIX)
    args = ap.parse_args(argv)

    try:
        # Everything that can be refused is refused here, before the browser opens.
        cal = check_calendar_id(args.calendar_id or os.environ.get("PROJECT_CALENDAR_ID"))
        out = check_out_path(Path(args.out) if args.out else default_out())
        try:
            text = Path(args.client_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise SetupError("Could not read the client file (%s)." % type(exc).__name__) from None
        client_id, client_secret = parse_client_file(text)

        state = new_state()
        verifier, challenge = new_pkce()
        code, redirect_uri = _wait_for_code(state, client_id, challenge)
        tokens = exchange_code(client_id, client_secret, code, verifier, redirect_uri)
        refresh = check_tokens(tokens)

        path = write_env_file(out, env_text(client_id, client_secret, refresh))
        print("Saved the sign-in to: %s" % path)
        print("Copy its three lines into the host .env, then delete the file.")

        result = verify(client_id, client_secret, refresh, cal)
    except SetupError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1

    print("Calendar access role: %s" % result["access_role"])
    print("Events this month: %d (%d with a title)" % (result["events"], result["titled"]))
    if result["access_role"] == "freeBusyReader":
        print("WARNING: this account only sees free/busy, so titles and colours are hidden. "
              "Run the script again and sign in with the Google account that owns the calendar.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
