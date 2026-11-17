"""Connect Raken (#781): an admin signs the tool in to Raken once, and the server keeps that sign-in.

Everything goes THROUGH THE HTTP API with a fake Raken behind an httpx.MockTransport and a temporary
data folder, because the routes are the contract the page is built against. The claims that cost
something when they are wrong:

  * ONLY AN ADMIN connects, and the callback refuses a state the server did not hand to that admin.
  * THE REFRESH TOKEN IS STORED ENCRYPTED, in one file on the data volume, and the one from EVERY
    token response is saved before its access token is used: Raken rotates refresh tokens and
    rejects the old one, so a token lost between "Raken answered" and "we saved it" is a lost
    connection.
  * RENEWALS RUN UNDER ONE LOCK. Two at once would send the same refresh token twice, and the
    second would be refused (invalid_grant), losing the connection.
  * invalid_grant SAYS "Raken sign-in has expired. An admin must Connect Raken again."
  * RAKEN CALLS RUN ONE AT A TIME with a pause between them; a 429 is retried at most twice.
  * NOTHING SECRET reaches a response or the log.

PUBLIC REPO: every id, code, token, project and number below is made up.
"""
import json
import pathlib
import threading
import time
import urllib.parse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import main
import profiles
import raken
import supabase_client

CLIENT_ID = "made-up-raken-client"
CLIENT_SECRET = "made-up-raken-secret-value"
REDIRECT = "https://tool.example.test/api/raken/callback"
KEY = Fernet.generate_key().decode()
ADMIN = "tester@wetreadwell.com"

PROJECTS = [
    {"uuid": "p-1", "name": "Example Clinic", "number": "26.901"},
    {"uuid": "p-2", "name": "Example Lofts", "number": "G26.902"},
    {"uuid": "p-3", "name": "Example Shop", "number": ""},
    {"uuid": "p-4", "name": "Example Diner", "number": None},
    {"uuid": "p-5", "name": "Example School", "number": "26.903"},
]


# ── the fake Raken ────────────────────────────────────────────────────────────
class FakeRaken:
    """Raken's token endpoint and GET /projects. Refresh tokens rotate on every renewal and an old
    one is refused with 400 invalid_grant, exactly as Raken documents."""

    def __init__(self):
        self.lock = threading.Lock()
        self.n = 0
        self.valid_refresh = set()
        self.valid_access = set()
        self.codes = {"made-up-code"}
        self.refresh_sent = []          # every refresh token a renewal sent, in order
        self.token_calls = 0
        self.project_calls = 0
        self.projects = list(PROJECTS)
        self.page_size = None           # None: whatever the client asks for
        self.code_expires_in = 36000    # the access token from the sign-in
        self.refresh_expires_in = 36000
        self.refresh_delay = 0.0
        self.too_many = 0               # answer this many /projects calls with 429 first
        self.refuse = None              # a JSON body: answer every signed-in /projects call 403 with it
        self.in_flight = 0
        self.max_in_flight = 0
        self.on_projects = None         # a hook run on each /projects call (sees the token used)

    def _issue(self, expires_in):
        with self.lock:
            self.n += 1
            access, refresh = "made-up-access-%d" % self.n, "made-up-refresh-%d" % self.n
            self.valid_access.add(access)
            self.valid_refresh.add(refresh)
        return httpx.Response(200, json={"access_token": access, "refresh_token": refresh,
                                         "token_type": "bearer", "expires_in": expires_in})

    def handle(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            return self._handle(request)
        finally:
            with self.lock:
                self.in_flight -= 1

    def _handle(self, request):
        url = request.url
        if url.host == "app.rakenapp.com" and url.path == "/oauth/token":
            self.token_calls += 1
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
                return httpx.Response(401, json={"error": "invalid_client"})
            if form.get("grant_type") == "authorization_code":
                if form.get("code") not in self.codes or form.get("redirect_uri") != REDIRECT:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.codes.discard(form["code"])
                return self._issue(self.code_expires_in)
            if form.get("grant_type") == "refresh_token":
                sent = form.get("refresh_token")
                self.refresh_sent.append(sent)
                if self.refresh_delay:
                    time.sleep(self.refresh_delay)
                with self.lock:
                    if sent not in self.valid_refresh:
                        return httpx.Response(400, json={"error": "invalid_grant",
                                                         "error_description": "echo " + str(sent)})
                    self.valid_refresh.discard(sent)          # rotation: the old one is dead
                return self._issue(self.refresh_expires_in)
            return httpx.Response(400, json={"error": "unsupported_grant_type"})
        if url.host == "developer.rakenapp.com" and url.path == "/api/projects":
            self.project_calls += 1
            if self.on_projects:
                self.on_projects(request)
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] not in self.valid_access:
                return httpx.Response(401, json={"message": "Unauthorized"})
            if self.refuse is not None:
                return httpx.Response(403, json=self.refuse)
            if self.too_many:
                self.too_many -= 1
                return httpx.Response(429, text="Too Many Requests")
            offset = int(url.params.get("offset", "0"))
            limit = int(url.params.get("limit", "10"))
            if self.page_size:
                limit = min(limit, self.page_size)
            items = self.projects[offset:offset + limit]
            nxt = offset + limit if offset + limit < len(self.projects) else None
            return httpx.Response(200, json={
                "page": {"offset": offset, "limit": limit, "totalElements": len(self.projects),
                         "previous": None, "next": None if nxt is None else "next-url",
                         "nextOffset": nxt},
                "collection": items})
        return httpx.Response(404, json={"message": "not in the fake"})


# ── fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def fake(monkeypatch, tmp_path):
    f = FakeRaken()
    monkeypatch.setenv("RAKEN_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("RAKEN_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("RAKEN_REDIRECT_URI", REDIRECT)
    monkeypatch.setenv("RAKEN_TOKEN_KEY", KEY)
    monkeypatch.setenv("RAKEN_STATUS_TTL_S", "0")
    monkeypatch.setattr(raken, "TOKEN_FILE", tmp_path / "raken_signin.json")
    monkeypatch.setattr(raken, "TRANSPORT", httpx.MockTransport(f.handle))
    monkeypatch.setattr(raken, "sleep", lambda s: None)
    raken.reset_for_tests()
    yield f
    raken.reset_for_tests()


@pytest.fixture
def as_admin(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "a1", "email": e, "role": "admin"})


@pytest.fixture
def as_member(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "u1", "email": e, "role": "user"})


@pytest.fixture
def client():
    return TestClient(main.app)


def start(client):
    r = client.get("/api/raken/connect")
    assert r.status_code == 200, r.text
    url = urllib.parse.urlsplit(r.json()["url"])
    return url, dict(urllib.parse.parse_qsl(url.query))


def connect(client, code="made-up-code"):
    """The whole sign-in, as the browser does it: start, Raken sends the admin back to the
    callback address, the page hands the code and state to the server."""
    _url, q = start(client)
    back = client.get("/api/raken/callback", params={"code": code, "state": q["state"]},
                      headers={"authorization": ""}, follow_redirects=False)
    assert back.status_code in (302, 303), back.text
    landing = urllib.parse.urlsplit(back.headers["location"])
    lq = dict(urllib.parse.parse_qsl(landing.query))
    r = client.post("/api/raken/callback", json={"code": lq["raken_code"], "state": lq["raken_state"]})
    return r


def stored_refresh_token(path):
    """What the data volume holds, decrypted with the key from the environment."""
    blob = json.loads(path.read_text(encoding="utf-8"))
    enc = blob.get("refresh_token")
    return Fernet(KEY.encode()).decrypt(enc.encode()).decode() if enc else None


# ── sign-in ───────────────────────────────────────────────────────────────────
def test_start_sends_the_admin_to_rakens_allow_page(client, fake, as_admin):
    url, q = start(client)
    assert (url.scheme, url.netloc, url.path) == ("https", "app.rakenapp.com", "/oauth/authorize")
    assert q["response_type"] == "code"
    assert q["client_id"] == CLIENT_ID
    assert q["redirect_uri"] == REDIRECT
    assert len(q["state"]) >= 32
    assert "client_secret" not in url.query and CLIENT_SECRET not in url.query
    # Two starts never share a state.
    assert start(client)[1]["state"] != q["state"]


def test_sign_in_round_trip_then_status_counts_project_numbers(client, fake, as_admin):
    assert client.get("/api/raken/status").json()["state"] == "not_connected"
    r = connect(client)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    s = client.get("/api/raken/status").json()
    assert s["state"] == "connected"
    assert s["projects"] == 5 and s["with_number"] == 3
    assert s["message"] == "Connected: 5 Raken projects, 3 with Raken's Project Number filled in"
    assert s["examples"] == ["26.901", "G26.902", "26.903"]


def test_the_callback_bounce_carries_only_the_code_state_and_error_to_the_page(client, fake):
    back = client.get("/api/raken/callback",
                      params={"code": "c", "state": "s", "extra": "<script>"},
                      headers={"authorization": ""}, follow_redirects=False)
    assert back.status_code in (302, 303)
    loc = back.headers["location"]
    assert loc.startswith("/project-calendar.html?")
    assert dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query)) == {
        "raken_code": "c", "raken_state": "s"}
    assert fake.token_calls == 0, "the bounce must never exchange anything"


def test_status_pages_through_every_project(client, fake, as_admin):
    fake.projects = [{"uuid": "p%d" % i, "name": "Example %d" % i,
                      "number": "26.%03d" % i if i % 2 else ""} for i in range(23)]
    fake.page_size = 10
    connect(client)
    s = client.get("/api/raken/status").json()
    assert s["projects"] == 23 and s["with_number"] == 11
    assert len(s["examples"]) == 5


def test_project_numbers_are_trimmed_and_counted_once_per_project(client, fake, as_admin):
    fake.projects = [{"uuid": "a", "number": " 26.901 "}, {"uuid": "b", "number": "   "},
                     {"uuid": "c", "number": "26.901"}]
    connect(client)
    s = client.get("/api/raken/status").json()
    assert s["projects"] == 3 and s["with_number"] == 2
    assert s["examples"] == ["26.901"]


def test_a_mismatched_state_is_refused_and_nothing_is_stored(client, fake, as_admin):
    _url, q = start(client)
    state = q["state"]
    mid = len(state) // 2
    flipped = state[:mid] + ("A" if state[mid] != "A" else "B") + state[mid + 1:]
    for bad in (state + "x", flipped, "", "made-up-state"):
        r = client.post("/api/raken/callback", json={"code": "made-up-code", "state": bad})
        assert r.status_code == 400, bad
        assert "Connect Raken again" in r.json()["detail"]
    assert fake.token_calls == 0
    assert not raken.TOKEN_FILE.exists()
    assert client.get("/api/raken/status").json()["state"] == "not_connected"


def test_a_state_handed_to_another_admin_is_refused(client, fake, as_admin, monkeypatch):
    _url, q = start(client)
    monkeypatch.setattr(supabase_client, "verify_token", lambda a: "other-admin@wetreadwell.com")
    r = client.post("/api/raken/callback", json={"code": "made-up-code", "state": q["state"]})
    assert r.status_code == 400
    assert fake.token_calls == 0


def test_a_state_is_good_for_one_sign_in_only(client, fake, as_admin):
    _url, q = start(client)
    fake.codes.add("made-up-code-2")
    assert client.post("/api/raken/callback",
                       json={"code": "made-up-code", "state": q["state"]}).status_code == 200
    r = client.post("/api/raken/callback", json={"code": "made-up-code-2", "state": q["state"]})
    assert r.status_code == 400


def test_a_member_cannot_start_finish_or_read_the_connection(client, fake, as_member):
    assert client.get("/api/raken/connect").status_code == 403
    assert client.post("/api/raken/callback",
                       json={"code": "made-up-code", "state": "x"}).status_code == 403
    assert client.get("/api/raken/status").status_code == 403
    assert fake.token_calls == 0


def test_signed_out_the_routes_answer_401(client, fake, real_verify_token, monkeypatch):
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    for method, path in (("get", "/api/raken/connect"), ("post", "/api/raken/callback"),
                         ("get", "/api/raken/status")):
        r = getattr(client, method)(path, headers={"authorization": ""})
        assert r.status_code == 401, path
    # Raken's redirect back carries no identity: that GET only bounces to the page.
    r = client.get("/api/raken/callback", params={"code": "c", "state": "s"},
                   headers={"authorization": ""}, follow_redirects=False)
    assert r.status_code == 303
    assert fake.token_calls == 0


def test_a_rejected_code_says_so_plainly(client, fake, as_admin):
    r = connect(client, code="made-up-wrong-code")
    assert r.status_code == 400
    assert "Connect Raken again" in r.json()["detail"]
    assert client.get("/api/raken/status").json()["state"] == "not_connected"


def test_not_set_up_on_the_server_says_so(client, fake, as_admin, monkeypatch):
    monkeypatch.delenv("RAKEN_TOKEN_KEY")
    s = client.get("/api/raken/status").json()
    assert s["state"] == "not_connected" and s["configured"] is False
    r = client.get("/api/raken/connect")
    assert r.status_code == 503
    assert "not set up" in r.json()["detail"]


def test_a_key_that_is_not_a_fernet_key_counts_as_not_set_up(client, fake, as_admin, monkeypatch):
    monkeypatch.setenv("RAKEN_TOKEN_KEY", "not-a-real-key")
    assert client.get("/api/raken/status").json()["configured"] is False
    assert client.get("/api/raken/connect").status_code == 503


# ── storage ───────────────────────────────────────────────────────────────────
def test_the_refresh_token_is_stored_encrypted_in_one_file(client, fake, as_admin):
    connect(client)
    files = list(raken.TOKEN_FILE.parent.iterdir())
    assert files == [raken.TOKEN_FILE], "one file, and no temp file left behind"
    text = raken.TOKEN_FILE.read_text(encoding="utf-8")
    assert "made-up-refresh-" not in text and "made-up-access-" not in text
    assert stored_refresh_token(raken.TOKEN_FILE) == "made-up-refresh-1"


def test_the_sign_in_survives_a_restart(client, fake, as_admin):
    connect(client)
    raken.reset_for_tests()          # a restart: nothing in memory, only the file
    s = client.get("/api/raken/status").json()
    assert s["state"] == "connected" and s["projects"] == 5
    assert fake.refresh_sent == ["made-up-refresh-1"]


def test_a_stored_sign_in_unreadable_with_the_current_key_must_be_connected_again(
        client, fake, as_admin, monkeypatch):
    connect(client)
    raken.reset_for_tests()
    monkeypatch.setenv("RAKEN_TOKEN_KEY", Fernet.generate_key().decode())
    s = client.get("/api/raken/status").json()
    assert s["state"] == "expired"
    assert s["message"] == "Raken sign-in has expired. An admin must Connect Raken again."


# ── renewal ───────────────────────────────────────────────────────────────────
def test_every_renewal_saves_the_rotated_refresh_token_before_its_access_token_is_used(
        client, fake, as_admin):
    fake.code_expires_in = 0
    fake.refresh_expires_in = 0          # every call needs a renewal
    seen = []

    def check(request):
        # At the moment Raken is called with an access token, the file already holds the refresh
        # token that came back WITH it.
        token = request.headers["authorization"][7:]
        seen.append((token, stored_refresh_token(raken.TOKEN_FILE)))
    fake.on_projects = check

    connect(client)
    for _ in range(3):
        assert client.get("/api/raken/status").json()["state"] == "connected"
    assert fake.refresh_sent == ["made-up-refresh-1", "made-up-refresh-2", "made-up-refresh-3"]
    for token, stored in seen:
        assert token.replace("access", "refresh") == stored
    assert stored_refresh_token(raken.TOKEN_FILE) == "made-up-refresh-4"


def test_invalid_grant_means_an_admin_must_connect_again(client, fake, as_admin, caplog):
    fake.code_expires_in = 0
    connect(client)
    fake.valid_refresh.clear()           # revoked, or rotated by someone else
    s = client.get("/api/raken/status").json()
    assert s["state"] == "expired"
    assert s["message"] == "Raken sign-in has expired. An admin must Connect Raken again."
    assert stored_refresh_token(raken.TOKEN_FILE) is None, "the dead token is not kept"
    calls = fake.token_calls
    # It stays expired, across a restart, and Raken is not asked again with a dead token.
    raken.reset_for_tests()
    assert client.get("/api/raken/status").json()["state"] == "expired"
    assert fake.token_calls == calls
    # Connecting again fixes it.
    fake.codes.add("made-up-code-2")
    assert connect(client, code="made-up-code-2").status_code == 200
    assert client.get("/api/raken/status").json()["state"] == "connected"


def test_two_renewals_at_once_send_the_refresh_token_once(client, fake, as_admin):
    fake.code_expires_in = 0             # the first status call after sign-in must renew
    fake.refresh_delay = 0.2             # hold the renewal open so the second one arrives during it
    connect(client)
    out = []

    def go():
        out.append(client.get("/api/raken/status").json())
    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert [s["state"] for s in out] == ["connected", "connected"]
    assert fake.refresh_sent == ["made-up-refresh-1"], "one renewal, the original token once"


def test_concurrent_renewals_never_reuse_a_refresh_token(client, fake, as_admin):
    fake.code_expires_in = 0
    fake.refresh_expires_in = 0          # every caller renews, one after another
    fake.refresh_delay = 0.05
    connect(client)
    out = []

    def go():
        out.append(client.get("/api/raken/status").json()["state"])
    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert out == ["connected"] * 4
    assert len(fake.refresh_sent) == len(set(fake.refresh_sent)), fake.refresh_sent
    assert fake.refresh_sent[0] == "made-up-refresh-1"
    assert fake.max_in_flight == 1, "Raken was called in parallel"


# ── a data volume that cannot be written ──────────────────────────────────────
def _volume_full(*_a, **_k):
    raise OSError(28, "No space left on device")


@pytest.mark.parametrize("when", ["connect", "renewal", "expiry"])
def test_a_store_that_cannot_be_written_never_answers_500(client, fake, as_admin, monkeypatch, when):
    """A full or read-only data volume makes the sign-in impossible to keep. The routes say so in
    plain words; they never answer 500, and the reason never carries the OS error's text."""
    client = TestClient(main.app, raise_server_exceptions=False)
    if when == "connect":
        monkeypatch.setattr(raken, "write_json", _volume_full)
        r = connect(client)
        assert r.status_code == 503, r.text
        assert r.json()["detail"] == "Raken sign-in could not be saved."
        assert client.get("/api/raken/status").json()["state"] == "not_connected"
        return
    fake.code_expires_in = 0                 # the next status call must renew
    assert connect(client).status_code == 200
    if when == "expiry":
        fake.valid_refresh.clear()           # the renewal is refused, and marking it fails too
    monkeypatch.setattr(raken, "write_json", _volume_full)
    r = client.get("/api/raken/status")
    assert r.status_code == 200, r.text
    s = r.json()
    if when == "renewal":
        assert s["state"] == "connected"
        assert s["error"] == "Raken sign-in could not be saved."
        assert "projects" not in s, "an access token whose refresh token was not saved is not used"
    else:
        assert s["state"] == "expired"
        assert s["message"] == "Raken sign-in has expired. An admin must Connect Raken again."
    assert "No space left" not in r.text


def test_a_data_folder_that_is_a_file_fails_the_connect_plainly(client, fake, as_admin, monkeypatch,
                                                                 tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(raken, "TOKEN_FILE", blocker / "raken_signin.json")
    client = TestClient(main.app, raise_server_exceptions=False)
    r = connect(client)
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "Raken sign-in could not be saved."


# ── the client: one at a time, a pause, a bounded 429 ─────────────────────────
def test_calls_are_paused_and_a_429_is_retried_at_most_twice(client, fake, as_admin, monkeypatch):
    slept = []
    monkeypatch.setattr(raken, "sleep", slept.append)
    connect(client)
    fake.too_many = 2
    calls = fake.project_calls
    s = client.get("/api/raken/status").json()
    assert s["state"] == "connected" and s["projects"] == 5
    assert fake.project_calls - calls == 3
    assert len([x for x in slept if x >= raken.BACKOFF_S[0]]) == 2


def test_a_429_that_persists_fails_plainly_and_does_not_loop(client, fake, as_admin):
    connect(client)
    fake.too_many = 99
    calls = fake.project_calls
    s = client.get("/api/raken/status").json()
    assert s["state"] == "connected"
    assert "projects" not in s
    assert s["error"] == "Raken is limiting requests right now. Try again later."
    assert fake.project_calls - calls == 3, "one call and two retries, then stop"


# ── Raken's Public API not turned on for the account ──────────────────────────
# Raken signs the admin in, then refuses every data call with this until Raken turns the Public
# API on for the company. The message text is made up so a leak of it would show.
NOT_PROVISIONED = {"message": "made-up refusal text 7731", "code": "API_KEY_NOT_FOUND"}
NOT_PROVISIONED_LINE = ("Raken has not turned on its Public API for Treadwell's account yet. "
                        "Raken has to enable it; nothing needs to change here.")


def test_an_account_without_the_public_api_says_raken_has_to_turn_it_on(client, fake, as_admin,
                                                                         caplog):
    caplog.set_level("DEBUG")
    connect(client)
    fake.refuse = NOT_PROVISIONED
    r = client.get("/api/raken/status")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["state"] == "not_provisioned"
    assert s["message"] == NOT_PROVISIONED_LINE
    assert "error" not in s and "projects" not in s
    # The sign-in is fine: it is kept, not marked expired, and works once Raken turns the API on.
    assert stored_refresh_token(raken.TOKEN_FILE) == "made-up-refresh-1"
    assert json.loads(raken.TOKEN_FILE.read_text(encoding="utf-8"))["expired"] is False
    for leak in ("made-up refusal text 7731", "API_KEY_NOT_FOUND"):
        assert leak not in r.text and leak not in caplog.text, leak
    fake.refuse = None
    s = client.get("/api/raken/status").json()
    assert s["state"] == "connected" and s["projects"] == 5


@pytest.mark.parametrize("body", [
    {"message": "made-up refusal text 7731", "code": "MADE_UP_OTHER_CODE"},
    {"message": "made-up refusal text 7731"},
    {"message": "made-up refusal text 7731", "code": "api_key_not_found"},
])
def test_any_other_403_keeps_the_plain_could_not_be_reached(client, fake, as_admin, caplog, body):
    caplog.set_level("DEBUG")
    connect(client)
    fake.refuse = body
    r = client.get("/api/raken/status")
    s = r.json()
    assert s["state"] == "connected"
    assert s["error"] == "Raken could not be reached."
    assert stored_refresh_token(raken.TOKEN_FILE) == "made-up-refresh-1"
    for leak in ("made-up refusal text 7731", "MADE_UP_OTHER_CODE", "api_key_not_found"):
        assert leak not in r.text and leak not in caplog.text, leak


def test_there_is_a_fixed_pause_between_calls(client, fake, as_admin, monkeypatch):
    fake.projects = [{"uuid": "p%d" % i, "number": ""} for i in range(25)]
    fake.page_size = 10
    connect(client)
    slept = []
    monkeypatch.setattr(raken, "sleep", slept.append)
    monkeypatch.setattr(raken, "monotonic", lambda: 1000.0)    # no time passes between calls
    client.get("/api/raken/status")
    assert slept.count(raken.CALL_PAUSE_S) >= 2, slept


# ── secrets ───────────────────────────────────────────────────────────────────
def test_the_env_example_names_the_four_settings_with_no_values():
    example = (pathlib.Path(raken.__file__).resolve().parent / ".env.example").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in example.splitlines()]
    for name in ("RAKEN_CLIENT_ID", "RAKEN_CLIENT_SECRET", "RAKEN_REDIRECT_URI", "RAKEN_TOKEN_KEY"):
        assert name + "=" in lines, name



def test_nothing_secret_reaches_a_response_or_the_log(client, fake, as_admin, caplog):
    caplog.set_level("DEBUG")
    fake.code_expires_in = 0
    bodies = []
    _url, q = start(client)
    bodies.append(json.dumps(q))
    r = client.post("/api/raken/callback", json={"code": "made-up-code", "state": q["state"]})
    bodies.append(r.text)
    bodies.append(client.get("/api/raken/status").text)
    fake.valid_refresh.clear()
    raken.reset_for_tests()
    bodies.append(client.get("/api/raken/status").text)
    everything = "\n".join(bodies) + "\n" + caplog.text
    for secret in (CLIENT_SECRET, KEY, "made-up-refresh-", "made-up-access-"):
        assert secret not in everything, secret
    assert "made-up-code" not in caplog.text
    assert "SECRET" not in caplog.text
