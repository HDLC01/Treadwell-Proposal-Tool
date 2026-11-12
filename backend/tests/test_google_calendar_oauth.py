"""The one-time Google sign-in script for the Project Calendar (backend/google_calendar_oauth.py).

Only its pure parts and its offline paths are exercised: no browser, no network. The claims that
cost something when they are wrong:

  * The consent URL asks for exactly the read-only events scope, offline access (a refresh token)
    and a fresh consent, with a state and a PKCE S256 challenge that matches the verifier.
  * An answer whose state does not match is refused, so a stray redirect cannot plant a code.
  * The script never prints the client secret, the code or any token: only the file's path.

PUBLIC REPO: every id, secret and token below is made up.
"""
import base64
import datetime as _dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import urllib.parse

import httpx
import pytest

import google_calendar_oauth as g
import project_calendar as pc

CLIENT_ID = "made-up-client.apps.example"
SECRET = "made-up-client-secret-4d2b"
REFRESH = "made-up-refresh-token-81aa"
CODE = "made-up-auth-code-55e0"
ACCESS = "made-up-access-token-0c7d"
CAL = "made-up-project-calendar@group.calendar.google.com"


# ── the consent URL ───────────────────────────────────────────────────────────
def test_the_auth_url_carries_every_required_parameter():
    verifier, challenge = g.new_pkce()
    url = g.build_auth_url(CLIENT_ID, "http://127.0.0.1:53111/", "s-123", challenge)
    parts = urllib.parse.urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "accounts.google.com",
                                                        "/o/oauth2/v2/auth")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
    assert q == {"client_id": CLIENT_ID, "redirect_uri": "http://127.0.0.1:53111/",
                 "response_type": "code",
                 "scope": "https://www.googleapis.com/auth/calendar.events.readonly",
                 "access_type": "offline", "prompt": "consent", "state": "s-123",
                 "code_challenge": challenge, "code_challenge_method": "S256"}
    assert SECRET not in url


def test_the_pkce_challenge_is_the_s256_of_the_verifier():
    verifier, challenge = g.new_pkce()
    assert 43 <= len(verifier) <= 128
    assert set(verifier) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    want = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == want and "=" not in challenge
    # RFC 7636 appendix B's worked example.
    assert g.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == \
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_each_sign_in_gets_a_fresh_state_and_verifier():
    assert g.new_state() != g.new_state()
    assert len(g.new_state()) >= 32
    assert g.new_pkce()[0] != g.new_pkce()[0]


# ── the loopback answer ───────────────────────────────────────────────────────
def test_a_matching_state_yields_the_code():
    q = urllib.parse.parse_qs("state=s-123&code=%s&scope=x" % CODE)
    assert g.code_from_callback(q, "s-123") == CODE


@pytest.mark.parametrize("query", ["state=s-999&code=" + CODE, "code=" + CODE,
                                   "state=&code=" + CODE])
def test_a_state_mismatch_is_refused(query):
    with pytest.raises(g.SetupError) as exc:
        g.code_from_callback(urllib.parse.parse_qs(query, keep_blank_values=True), "s-123")
    assert "state" in str(exc.value) and CODE not in str(exc.value)


@pytest.mark.parametrize("state", ["é", "s-12é", "☃"])
def test_a_non_ascii_state_is_a_plain_mismatch_not_a_crash(state):
    """Any local request can reach the loopback port while the script waits. A state such as
    %C3%A9 decodes to a non-ASCII string, which compare_digest refuses with a TypeError."""
    with pytest.raises(g.SetupError) as exc:
        g.code_from_callback({"state": [state], "code": [CODE]}, "s-123")
    assert "state" in str(exc.value) and "Nothing was saved" in str(exc.value)


def test_a_refusal_or_a_missing_code_is_refused():
    with pytest.raises(g.SetupError, match="access_denied"):
        g.code_from_callback({"state": ["s-1"], "error": ["access_denied"]}, "s-1")
    with pytest.raises(g.SetupError, match="without a code"):
        g.code_from_callback({"state": ["s-1"]}, "s-1")


# ── the client file ───────────────────────────────────────────────────────────
def test_the_client_file_is_read_from_a_desktop_client():
    text = json.dumps({"installed": {"client_id": CLIENT_ID, "client_secret": SECRET,
                                     "redirect_uris": ["http://localhost"]}})
    assert g.parse_client_file(text) == (CLIENT_ID, SECRET)


def test_a_web_application_client_is_refused_before_the_browser_opens():
    """Only a Desktop client gets Google's any-port loopback redirect. A Web client's random-port
    redirect is refused in the browser (redirect_uri_mismatch) and the script would wait five
    minutes for an answer that never comes."""
    text = json.dumps({"web": {"client_id": CLIENT_ID, "client_secret": SECRET,
                               "redirect_uris": ["http://localhost"]}})
    with pytest.raises(g.SetupError) as exc:
        g.parse_client_file(text)
    assert "Web application" in str(exc.value) and "Desktop app" in str(exc.value)
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize("text", [
    "{not json",
    "[]",
    json.dumps({"type": "service_account", "client_email": "x@made-up.iam.example"}),
    json.dumps({"installed": {"client_id": CLIENT_ID}}),
    json.dumps({"web": {"client_secret": SECRET}}),
    json.dumps({"installed": "nope"}),
])
def test_a_malformed_client_file_is_refused_without_echoing_it(text):
    with pytest.raises(g.SetupError) as exc:
        g.parse_client_file(text)
    assert SECRET not in str(exc.value)


# ── the code exchange ─────────────────────────────────────────────────────────
def test_the_code_exchange_sends_the_verifier_and_the_redirect():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["form"] = {k: v[0] for k, v in urllib.parse.parse_qs(request.content.decode()).items()}
        return httpx.Response(200, json={"access_token": ACCESS, "refresh_token": REFRESH,
                                         "scope": g.SCOPE, "expires_in": 3599})

    tokens = g.exchange_code(CLIENT_ID, SECRET, CODE, "v-abc", "http://127.0.0.1:5/",
                             transport=httpx.MockTransport(handler))
    assert seen["url"] == "https://oauth2.googleapis.com/token"
    assert seen["form"] == {"client_id": CLIENT_ID, "client_secret": SECRET, "code": CODE,
                            "code_verifier": "v-abc", "redirect_uri": "http://127.0.0.1:5/",
                            "grant_type": "authorization_code"}
    assert g.check_tokens(tokens) == REFRESH


def test_a_refused_code_says_why_without_the_body():
    transport = httpx.MockTransport(lambda r: httpx.Response(
        400, json={"error": "invalid_grant", "error_description": "echo " + CODE}))
    with pytest.raises(g.SetupError) as exc:
        g.exchange_code(CLIENT_ID, SECRET, CODE, "v", "http://127.0.0.1:5/", transport=transport)
    assert "invalid_grant" in str(exc.value)
    assert CODE not in str(exc.value) and SECRET not in str(exc.value)


def test_no_refresh_token_is_refused():
    with pytest.raises(g.SetupError, match="no refresh token"):
        g.check_tokens({"access_token": ACCESS, "scope": g.SCOPE})


def test_a_consent_without_the_calendar_box_ticked_is_refused():
    with pytest.raises(g.SetupError, match="not ticked"):
        g.check_tokens({"access_token": ACCESS, "refresh_token": REFRESH, "scope": "openid email"})


# ── the env file ──────────────────────────────────────────────────────────────
def test_the_env_file_holds_exactly_the_three_lines(tmp_path):
    path = g.write_env_file(tmp_path / "sub" / "out.env", g.env_text(CLIENT_ID, SECRET, REFRESH))
    assert path.is_absolute()
    assert path.read_text(encoding="utf-8").splitlines() == [
        "GOOGLE_OAUTH_CLIENT_ID=" + CLIENT_ID,
        "GOOGLE_OAUTH_CLIENT_SECRET=" + SECRET,
        "GOOGLE_OAUTH_REFRESH_TOKEN=" + REFRESH]
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600


def test_the_file_is_owner_only_before_a_secret_is_written(tmp_path, monkeypatch):
    """An existing --out file keeps its old mode through os.open, so on POSIX a 0644 file would
    hold the secrets world-readable until a chmod after the close. The mode must be narrowed on
    the open descriptor, while the file is still empty."""
    p = tmp_path / "out.env"
    p.write_text("old stuff\n", encoding="utf-8")
    # Left at the mode a new file gets (0644 under the usual umask on the Linux CI box): readable
    # by others, as a hand-made file is. No chmod here, so no world-readable mode is ever set.
    seen = []
    real = getattr(os, "fchmod", None)

    def fchmod(fd, mode):
        seen.append((mode, os.fstat(fd).st_size))
        if real is not None:
            real(fd, mode)

    monkeypatch.setattr(os, "fchmod", fchmod, raising=False)
    g.write_env_file(p, g.env_text(CLIENT_ID, SECRET, REFRESH))
    assert seen == [(0o600, 0)], "the mode was not narrowed before the secrets were written"
    assert REFRESH in p.read_text(encoding="utf-8")
    if os.name == "posix":
        assert (p.stat().st_mode & 0o777) == 0o600


def test_without_fchmod_the_file_is_still_written(tmp_path, monkeypatch):
    """Windows has no os.fchmod (before 3.13): the write must not depend on it."""
    monkeypatch.delattr(os, "fchmod", raising=False)
    p = g.write_env_file(tmp_path / "out.env", g.env_text(CLIENT_ID, SECRET, REFRESH))
    assert REFRESH in p.read_text(encoding="utf-8")


def test_rewriting_the_env_file_replaces_it(tmp_path):
    p = tmp_path / "out.env"
    p.write_text("old stuff\n" * 50, encoding="utf-8")
    g.write_env_file(p, g.env_text(CLIENT_ID, SECRET, REFRESH))
    assert "old stuff" not in p.read_text(encoding="utf-8")


def test_the_default_output_is_in_the_home_folder_outside_the_repo(monkeypatch, tmp_path):
    real = g.default_out()
    assert real == pathlib.Path.home() / ".treadwell" / "google-calendar-oauth.env"
    with pytest.raises(ValueError):
        real.resolve().relative_to(g.REPO_ROOT.resolve())
    monkeypatch.setattr(g.Path, "home", staticmethod(lambda: tmp_path / "home"))
    assert g.default_out() == tmp_path / "home" / ".treadwell" / "google-calendar-oauth.env"


def test_a_new_output_folder_is_made_owner_only(tmp_path):
    p = g.write_env_file(tmp_path / "home" / ".treadwell" / "out.env",
                         g.env_text(CLIENT_ID, SECRET, REFRESH))
    assert p.parent.is_dir() and REFRESH in p.read_text(encoding="utf-8")
    if os.name == "posix":
        assert (p.parent.stat().st_mode & 0o777) == 0o700


def test_main_writes_to_the_home_folder_by_default(monkeypatch, tmp_path, capsys):
    home = tmp_path / "home"
    monkeypatch.setattr(g.Path, "home", staticmethod(lambda: home))
    rc, _out = _run_main(monkeypatch, tmp_path, out=None)
    want = home / ".treadwell" / "google-calendar-oauth.env"
    assert rc == 0 and REFRESH in want.read_text(encoding="utf-8")
    assert str(want.resolve()) in capsys.readouterr().out


# ── --out inside the repo ─────────────────────────────────────────────────────
def test_an_out_inside_the_repo_that_git_does_not_ignore_is_refused():
    seen = []

    def run(cmd, **kw):
        seen.append((cmd, kw.get("cwd")))
        return subprocess.CompletedProcess(cmd, 1)

    with pytest.raises(g.SetupError) as exc:
        g.check_out_path(g.REPO_ROOT / "backend" / "made-up.env", run=run)
    assert "inside the repository" in str(exc.value) and "Nothing was saved" in str(exc.value)
    assert seen == [(["git", "check-ignore", "-q", "backend/made-up.env"], str(g.REPO_ROOT))]


def test_an_out_inside_the_repo_that_git_ignores_is_allowed():
    run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0)  # noqa: E731
    target = g.REPO_ROOT / ".google-calendar-oauth.env"
    assert g.check_out_path(target, run=run) == target.resolve()


@pytest.mark.parametrize("boom", [FileNotFoundError("git"), subprocess.TimeoutExpired("git", 15)])
def test_without_git_an_out_inside_the_repo_is_refused(boom):
    def run(cmd, **kw):
        raise boom

    with pytest.raises(g.SetupError, match="inside the repository"):
        g.check_out_path(g.REPO_ROOT / ".google-calendar-oauth.env", run=run)


def test_git_errors_are_a_refusal_not_a_pass():
    run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 128)  # noqa: E731
    with pytest.raises(g.SetupError):
        g.check_out_path(g.REPO_ROOT / ".google-calendar-oauth.env", run=run)


def test_an_out_outside_the_repo_never_asks_git(tmp_path):
    run = lambda *a, **k: pytest.fail("git was asked about a path outside the repo")  # noqa: E731
    assert g.check_out_path(tmp_path / "out.env", run=run) == (tmp_path / "out.env").resolve()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_real_git_check_tells_an_ignored_file_from_a_tracked_folder():
    g.check_out_path(g.REPO_ROOT / ".google-calendar-oauth.env")
    with pytest.raises(g.SetupError):
        g.check_out_path(g.REPO_ROOT / "backend" / "made-up-calendar-sign-in.txt")


def test_main_refuses_an_out_inside_the_repo_before_the_browser(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(g, "_wait_for_code", lambda *a: pytest.fail("the browser was opened"))
    monkeypatch.setattr(g.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    out = g.REPO_ROOT / "backend" / "made-up-out.env"
    rc = g.main(["--client-file", str(tmp_path / "x.json"), "--out", str(out),
                 "--calendar-id", CAL])
    assert rc == 1 and "inside the repository" in capsys.readouterr().err
    assert not out.exists()


# ── the calendar id ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("cal", ["primary", "PRIMARY", "someone@made-up.example",
                                 "made-up@group.calendar.example",
                                 "made-up@group.calendar.google.com.example"])
def test_a_calendar_id_that_is_not_a_shared_calendar_is_refused(cal):
    with pytest.raises(g.SetupError) as exc:
        g.check_calendar_id(cal)
    assert "@group.calendar.google.com" in str(exc.value)


def test_a_shared_calendar_id_is_accepted():
    assert g.check_calendar_id("  " + CAL + " ") == CAL


@pytest.mark.parametrize("cal", ["primary", "someone@made-up.example"])
def test_main_refuses_a_bad_calendar_id_before_the_browser(monkeypatch, tmp_path, capsys, cal):
    monkeypatch.setattr(g, "_wait_for_code", lambda *a: pytest.fail("the browser was opened"))
    rc = g.main(["--client-file", str(tmp_path / "x.json"), "--out", str(tmp_path / "o.env"),
                 "--calendar-id", cal])
    assert rc == 1 and "@group.calendar.google.com" in capsys.readouterr().err
    assert not (tmp_path / "o.env").exists()


# ── the check read and what gets printed ──────────────────────────────────────
def test_the_month_bounds_use_the_servers_own_central_midnight(monkeypatch):
    monkeypatch.setattr(pc, "rfc3339_midnight", lambda day: "made-up " + day.isoformat())
    assert g.month_bounds(_dt.date(2026, 12, 31)) == ("made-up 2026-12-01", "made-up 2027-01-01")


def test_the_month_bounds_are_central_midnights():
    assert g.month_bounds(_dt.date(2026, 11, 12)) == ("2026-11-01T00:00:00-05:00",
                                                      "2026-12-01T00:00:00-06:00")
    assert g.month_bounds(_dt.date(2026, 12, 31)) == ("2026-12-01T00:00:00-06:00",
                                                      "2027-01-01T00:00:00-06:00")


def _fake_google(role="owner", events_status=200, token_status=200, events_body=None):
    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            if token_status != 200:
                return httpx.Response(token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": ACCESS, "expires_in": 3600})
        if events_status != 200:
            return httpx.Response(events_status,
                                  json=events_body or {"error": {"code": events_status}})
        return httpx.Response(200, json={"accessRole": role, "items": [
            {"id": "a", "summary": "Example Diner (4)"},
            {"id": "b", "summary": ""},
            {"id": "c"},
            {"id": "d", "summary": "Example Gone", "status": "cancelled"}]})
    return httpx.MockTransport(handler)


def test_the_check_counts_events_and_titles_through_the_servers_own_source():
    got = g.verify(CLIENT_ID, SECRET, REFRESH, "made-up@group.calendar.google.com",
                   today=_dt.date(2026, 11, 12), transport=_fake_google("owner"))
    assert got == {"access_role": "owner", "events": 3, "titled": 1}


@pytest.mark.parametrize("kw,words", [
    ({"events_status": 404}, "isn't shared"),
    ({"events_status": 403}, "isn't allowed"),
    ({"token_status": 400}, "reconnect the Google sign-in"),
    ({"token_status": 400}, "Run this script again."),
    ({"events_status": 403, "events_body": {"error": {
        "code": 403, "errors": [{"domain": "usageLimits", "reason": "accessNotConfigured"}],
        "status": "PERMISSION_DENIED"}}}, "Google Calendar API is turned off"),
    # The page's message says what is wrong; the console also says where to fix it.
    ({"events_status": 403, "events_body": {"error": {
        "code": 403, "errors": [{"domain": "usageLimits", "reason": "accessNotConfigured"}],
        "status": "PERMISSION_DENIED"}}}, "APIs & Services > Library > Google Calendar API"),
])
def test_a_failed_check_says_which_failure_in_plain_words(kw, words):
    with pytest.raises(g.SetupError) as exc:
        g.verify(CLIENT_ID, SECRET, REFRESH, "made-up@group.calendar.google.com",
                 today=_dt.date(2026, 11, 12), transport=_fake_google(**kw))
    assert words in str(exc.value)
    assert REFRESH not in str(exc.value) and SECRET not in str(exc.value)


def _run_main(monkeypatch, tmp_path, role="owner", out="out.env"):
    """main() end to end with the browser, Google and the check replaced."""
    client_file = tmp_path / "client_secret_made_up.json"
    client_file.write_text(json.dumps({"installed": {"client_id": CLIENT_ID,
                                                     "client_secret": SECRET}}), encoding="utf-8")
    monkeypatch.setattr(g, "_wait_for_code", lambda state, cid, ch: (CODE, "http://127.0.0.1:5/"))
    monkeypatch.setattr(g, "exchange_code", lambda *a, **k: {
        "access_token": ACCESS, "refresh_token": REFRESH, "scope": g.SCOPE})
    monkeypatch.setattr(g, "verify", lambda *a, **k: {"access_role": role, "events": 7,
                                                      "titled": 7 if role != "freeBusyReader" else 0})
    args = ["--client-file", str(client_file), "--calendar-id", CAL]
    if out:
        out = tmp_path / out
        args += ["--out", str(out)]
    return g.main(args), out


def test_main_prints_the_path_and_never_a_secret(monkeypatch, tmp_path, capsys):
    rc, out = _run_main(monkeypatch, tmp_path)
    printed = capsys.readouterr()
    text = printed.out + printed.err
    assert rc == 0
    assert str(out.resolve()) in text
    assert "Calendar access role: owner" in text and "Events this month: 7 (7 with a title)" in text
    for secret in (SECRET, REFRESH, CODE, ACCESS):
        assert secret not in text, "printed: %s" % secret
    assert REFRESH in out.read_text(encoding="utf-8")


def test_main_warns_when_the_account_only_sees_free_busy(monkeypatch, tmp_path, capsys):
    rc, _out = _run_main(monkeypatch, tmp_path, role="freeBusyReader")
    text = capsys.readouterr().out
    assert rc == 1 and "free/busy" in text and SECRET not in text and REFRESH not in text
    # The Workspace policy forbids sharing more than free/busy with outside accounts, so the only
    # advice that works is signing in as the owner.
    assert "See all event details" not in text
    assert "owns the calendar" in text


def test_the_env_example_names_the_project_calendar_and_the_home_folder_file():
    """GLOSSARY.md lists "Schedule" under Avoid for the Project Calendar."""
    example = (pathlib.Path(g.__file__).resolve().parent / ".env.example").read_text(encoding="utf-8")
    block = example[example.index("# Project Calendar"):example.index("PROJECT_CALENDAR_TTL_S")]
    assert "crews' job schedule" not in block
    assert "ONE Google calendar, the\n# Project Calendar" in block
    assert "~/.treadwell/google-calendar-oauth.env" in block
    assert ".google-calendar-oauth.env (git-ignored)" not in block
    assert "@group.calendar.google.com" in block and '"primary"' in block


def test_the_docstring_gives_the_new_default_and_the_calendar_id_rule():
    assert "~/.treadwell/google-calendar-oauth.env" in g.__doc__
    assert "git check-ignore" in g.__doc__
    assert "@group.calendar.google.com" in g.__doc__ and '"primary"' in g.__doc__


def test_the_setup_steps_say_to_turn_on_the_calendar_api():
    """Without the API enabled in the client's Cloud project every read is a 403."""
    assert "Google Calendar API" in g.__doc__
    example = (pathlib.Path(g.__file__).resolve().parent / ".env.example").read_text(encoding="utf-8")
    assert "Google Calendar API" in example


def test_main_without_a_calendar_id_stops_before_the_browser(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("PROJECT_CALENDAR_ID", raising=False)
    monkeypatch.setattr(g, "_wait_for_code", lambda *a: pytest.fail("the browser was opened"))
    rc = g.main(["--client-file", str(tmp_path / "x.json"), "--out", str(tmp_path / "o.env")])
    assert rc == 1 and "calendar-id" in capsys.readouterr().err
    assert not (tmp_path / "o.env").exists()
