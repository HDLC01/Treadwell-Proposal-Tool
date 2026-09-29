"""Backend input checks from the 2026-09-28 security review.

  1. A Basisboard message id is held to [A-Za-z0-9_-]{1,128} before it goes into an outbound
     API path — at the route (400), in leads.fetch_email_text and in basisboard_client itself.
  2. The signed .eml link is fetched only from Basisboard's storage host, over https, and no
     redirect to anywhere else is followed.
  3. An email body is cut to leads._TEXT_CAP BEFORE the regex passes, which are quadratic on
     unclosed markup and read text written by whoever emailed the bid inbox.
  4. Error bodies carry a short sentence; the exception text (paths, SQL, hosts) goes to the log.
  5. The three service-token routes answer 429 past a per-peer window.
"""
import time
from email.message import EmailMessage
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import basisboard_client as bb
import cover_letter_writer
import digest_worker
import drafts
import leads
import main
import notifications
import profiles
import proposal_writer

client = TestClient(main.app)

# What a leak looks like: an absolute server path, SQL, an internal host, a key-shaped string.
_LEAKY = ('relation "public.drafts" does not exist at /app/backend/templates/Direct/x.docx '
          '(https://abcd.supabase.co, sk-ant-oat01-SECRET)')
_LEAK_MARKERS = ("/app/", "relation", "supabase.co", "sk-ant", "SECRET", ".docx")


def _no_leak(text):
    text = str(text)
    return not any(m in text for m in _LEAK_MARKERS)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    leads._TEXT_CACHE.clear()
    main._SERVICE_HITS.clear()
    yield
    leads._TEXT_CACHE.clear()
    main._SERVICE_HITS.clear()


def _boom(name):
    def _f(*a, **k):
        raise AssertionError(f"{name} must not be called")
    return _f


def _raw_eml(plain):
    msg = EmailMessage()
    msg["Subject"] = "Invite"
    msg["From"] = "gc@example.com"
    msg.set_content(plain)
    return msg.as_bytes()


_BAD_IDS = ["../projects", "m1/detail", "m1?filter=x", "a.b", "m1%2Fx", "m1#frag",
            "m1\n", "m 1", "x" * 129, "m1@evil.example"]


# ── 1. message ids ────────────────────────────────────────────────────
def test_is_message_id_takes_the_safe_id_charset_only():
    for good in ["m1", "3f2a9c1e-5b7d-4e0a-9c6b-1d2e3f4a5b6c", "A_b-9", "x" * 128]:
        assert bb.is_message_id(good), good
    for bad in _BAD_IDS + ["", None, 12]:
        assert not bb.is_message_id(bad), bad


def test_basisboard_never_puts_an_unsafe_id_in_a_request_path(monkeypatch):
    paths = []

    class _Sess:
        def __enter__(self):
            return object()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(bb, "_api_key", lambda: "test-key")
    monkeypatch.setattr(bb, "_session", lambda: _Sess())
    monkeypatch.setattr(bb, "_get", lambda client, path, params=None:
                        paths.append(path) or {"url": "https://storage.googleapis.com/b/x"})

    for bad in _BAD_IDS:
        assert bb.get_message_detail(bad) is None, bad
        assert bb.get_message_url(bad) is None, bad
    assert paths == []

    bb.get_message_detail("3f2a-9_B")
    assert bb.get_message_url("3f2a-9_B") == "https://storage.googleapis.com/b/x"
    assert paths == ["/messages/3f2a-9_B/detail", "/messages/3f2a-9_B"]


def test_fetch_email_text_refuses_a_bad_id_without_any_call(monkeypatch):
    # Recorded, not raised: fetch_email_text swallows a reader's exception by design.
    calls = []
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: calls.append(("detail", mid)))
    monkeypatch.setattr(bb, "get_message_url", lambda mid: calls.append(("url", mid)))
    # It strips first (`_txt`), so "m1\n" is read as the safe "m1"; every other bad id stays bad.
    for bad in [b for b in _BAD_IDS if not bb.is_message_id(b.strip())]:
        out = leads.fetch_email_text(bad)
        assert out["ok"] is False and out["error"] == "Invalid message id.", bad
    assert calls == []
    assert not leads._TEXT_CACHE


def test_body_route_answers_400_for_an_id_outside_the_charset(monkeypatch):
    monkeypatch.setattr(leads, "fetch_email_text", _boom("leads.fetch_email_text"))
    for path in ["/api/leads/a.b/body", "/api/leads/m1%3Ffilter%3Dx/body",
                 "/api/leads/m1%0A/body", "/api/leads/" + "x" * 129 + "/body"]:
        r = client.get(path)
        assert r.status_code == 400, (path, r.status_code, r.text)
        assert r.json()["detail"] == "Invalid id."


def test_body_route_still_reads_a_good_id(monkeypatch):
    seen = []
    monkeypatch.setattr(leads, "fetch_email_text",
                        lambda mid: seen.append(mid) or {"ok": True, "text": "Body"})
    r = client.get("/api/leads/3f2a9c1e-5b7d-4e0a/body")
    assert r.status_code == 200 and r.json()["text"] == "Body"
    assert seen == ["3f2a9c1e-5b7d-4e0a"]


# ── 2. the .eml host ──────────────────────────────────────────────────
def test_eml_url_allowlist():
    for ok in ["https://storage.googleapis.com/bb/x.eml?X-Goog-Signature=abc",
               "https://bb-mail.storage.googleapis.com/x.eml",
               "https://STORAGE.googleapis.com/x",
               "https://storage.googleapis.com:443/x"]:
        assert leads._eml_url_ok(ok), ok
    for bad in ["http://storage.googleapis.com/x",
                "https://storage.googleapis.com.evil.example/x",
                "https://evilstorage.googleapis.com/x",
                "https://storage.googleapis.com@evil.example/x",
                "https://user:pw@storage.googleapis.com/x",
                "https://storage.googleapis.com:8443/x",
                "https://127.0.0.1:8888/api/admin/users",
                "https://169.254.169.254/latest/meta-data",
                "http://treadwell-proposal-tool:8888/api/drafts",
                "file:///etc/passwd", "", "not a url", None]:
        assert not leads._eml_url_ok(bad), bad


def _fake_client(served):
    class _Resp:
        status_code, content = 200, _raw_eml("Fetched.")

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            served.append(str(url))
            return _Resp()

    return _Client


@pytest.mark.parametrize("link", [
    "https://127.0.0.1:8888/api/admin/users",
    "http://storage.googleapis.com/bb/x.eml",          # right host, plain http
    "http://169.254.169.254/latest/meta-data/",
    "https://storage.googleapis.com.evil.example/x.eml",
])
def test_an_eml_link_off_the_storage_host_is_never_fetched(monkeypatch, link):
    served = []
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: None)
    monkeypatch.setattr(bb, "get_message_url", lambda mid: link)
    monkeypatch.setattr(httpx, "Client", _fake_client(served))
    out = leads.fetch_email_text("m1")
    assert out["ok"] is False
    assert served == []


def _mock_transport_client(monkeypatch, handler):
    real = httpx.Client

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)

    monkeypatch.setattr(httpx, "Client", factory)


def test_a_redirect_off_the_storage_host_is_not_followed(monkeypatch):
    sent = []

    def handler(request):
        sent.append(str(request.url))
        if request.url.host == "storage.googleapis.com":
            return httpx.Response(302, headers={"Location": "http://127.0.0.1:8888/api/drafts"})
        return httpx.Response(200, content=_raw_eml("Internal data."))

    monkeypatch.setattr(bb, "get_message_detail", lambda mid: None)
    monkeypatch.setattr(bb, "get_message_url",
                        lambda mid: "https://storage.googleapis.com/bb/x.eml?sig=1")
    _mock_transport_client(monkeypatch, handler)

    out = leads.fetch_email_text("m1")
    assert out["ok"] is False and "Internal data." not in out["text"]
    assert sent == ["https://storage.googleapis.com/bb/x.eml?sig=1"]


def test_a_redirect_within_the_storage_host_is_still_followed(monkeypatch):
    def handler(request):
        if request.url.path == "/bb/old.eml":
            return httpx.Response(302, headers={
                "Location": "https://storage.googleapis.com/bb/new.eml"})
        return httpx.Response(200, content=_raw_eml("Moved but fine."))

    monkeypatch.setattr(bb, "get_message_detail", lambda mid: None)
    monkeypatch.setattr(bb, "get_message_url",
                        lambda mid: "https://storage.googleapis.com/bb/old.eml")
    _mock_transport_client(monkeypatch, handler)

    out = leads.fetch_email_text("m1")
    assert out["ok"] is True and "Moved but fine." in out["text"]


# ── 3. the body is cut before the regex passes ────────────────────────
class _Spy:
    """Stands in for a compiled pattern and records the length of every string it is run on."""

    def __init__(self, real, seen):
        self.real, self.seen = real, seen

    def sub(self, repl, s, *a, **k):
        self.seen.append(len(s))
        return self.real.sub(repl, s, *a, **k)


def _spy_all(monkeypatch):
    seen = []
    for name in ("_COMMENT_RE", "_SCRIPT_RE", "_BR_RE", "_CELL_RE", "_BLOCK_RE", "_TAG_RE",
                 "_SPACES_RE", "_BLANKS_RE"):
        monkeypatch.setattr(leads, name, _Spy(getattr(leads, name), seen))
    return seen


def test_no_regex_pass_reads_more_than_the_cap_of_an_html_body(monkeypatch):
    seen = _spy_all(monkeypatch)
    text = leads._html_to_text("<p>" + "x" * 100_000 + "</p>")
    assert seen and max(seen) <= leads._TEXT_CAP
    assert text.endswith("[truncated]")


def test_no_regex_pass_reads_more_than_the_cap_of_a_plain_eml_body(monkeypatch):
    from email import message_from_bytes
    msg = message_from_bytes(_raw_eml("line of scope\n" * 10_000))     # ~140,000 chars
    seen = _spy_all(monkeypatch)
    text = leads._eml_body_text(msg)
    assert seen and max(seen) <= leads._TEXT_CAP
    assert text.endswith("[truncated]") and text.count("[truncated]") == 1


def test_a_hostile_body_is_read_in_bounded_time(monkeypatch):
    """120,000 chars of unclosed comments: ~15 s through the passes uncut, ~0.25 s cut."""
    monkeypatch.setattr(bb, "get_message_detail", lambda mid: {"message": {
        "subject": "S", "fromEmail": "a@b.c", "body": "<!--" * 30_000}})
    monkeypatch.setattr(bb, "get_message_url", lambda mid: None)
    t0 = time.perf_counter()
    leads.fetch_email_text("m1")
    assert time.perf_counter() - t0 < 5.0


def test_a_cut_body_is_marked_once_and_the_prompt_cap_leaves_it_alone():
    body = "word " * 5_000                                   # 25,000 chars, no markup
    text = leads._html_to_text(body)
    assert text.endswith("[truncated]") and text.count("[truncated]") == 1
    assert len(text) <= leads._TEXT_CAP + len("\n\n[truncated]")
    assert leads._cap(text) == text                        # prequalify's _cap: unchanged
    # A cut that lands in whitespace leaves the text a few chars short of the cap, so text plus
    # marker is just over it — the length a second _cap used to slice into, printing
    # "[truncat" and then a second marker.
    edge = leads._html_to_text("a" * 14_990 + " " * 10 + "b" * 100)
    assert leads._TEXT_CAP < len(edge) < leads._TEXT_CAP + len("\n\n[truncated]")
    assert leads._cap(edge) == edge and leads._cap(edge).count("[trunc") == 1
    short = leads._html_to_text("<p>Scope: epoxy</p>")
    assert short == "Scope: epoxy"                          # an uncut body gains no marker


# ── 4. error bodies ───────────────────────────────────────────────────
def _raise(*a, **k):
    raise RuntimeError(_LEAKY)


@pytest.mark.parametrize("method,path,target,attr,body", [
    ("get", "/api/drafts", drafts, "list_drafts", None),
    ("get", "/api/trash", drafts, "list_trashed", None),
    ("get", "/api/history", drafts, "list_events", None),
    ("put", "/api/draft/d1", drafts, "save_draft", {"data": {}}),
    ("post", "/api/draft/d1/archive", drafts, "set_archived", {"archived": True}),
    ("post", "/api/draft/d1/test", drafts, "set_test_flag", {"is_test": True}),
    ("get", "/api/notifications", notifications, "get_notifications", None),
    ("post", "/api/notifications/seen", notifications, "mark_seen", None),
])
def test_a_failed_store_call_returns_a_sentence_not_the_exception(
        monkeypatch, method, path, target, attr, body):
    monkeypatch.setattr(target, attr, _raise)
    monkeypatch.setattr(main.leads_worker, "ensure_started", lambda **k: False)
    kw = {"json": body} if body is not None else {}
    r = getattr(client, method)(path, **kw)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is False and j["error"]
    assert _no_leak(r.text), r.text


def test_a_failed_digest_run_does_not_echo_the_exception(monkeypatch):
    monkeypatch.setattr(main, "_require_admin", lambda request: None)
    monkeypatch.setattr(digest_worker, "set_hooks", lambda **k: None)
    monkeypatch.setattr(digest_worker, "run_once", _raise)
    r = client.post("/api/admin/digest/run")
    assert r.status_code == 502
    assert r.json()["detail"].startswith("Digest failed")
    assert _no_leak(r.text), r.text


_GEN = {
    "work_type": "epoxy", "audience": "Direct",
    "values": {"job_name": "Leak QA", "project_name": "Leak QA", "city_state": "Olathe, KS",
               "epoxy_sf": "1000", "lump_sum": "$10,000.00"},
}


def _missing(*a, **k):
    raise FileNotFoundError("Proposal template not found: /app/backend/templates/Direct/x.docx")


def _skip_workbook(monkeypatch):
    # The estimate workbook is filled before the proposal and costs seconds; neither test reads it.
    monkeypatch.setattr(main.estimate_writer, "fill_estimate", lambda *a, **k: b"PK")


def test_a_missing_proposal_template_does_not_print_the_server_path(monkeypatch):
    _skip_workbook(monkeypatch)
    monkeypatch.setattr(proposal_writer, "fill_proposal", _missing)
    r = client.post("/api/generate", json=_GEN)
    assert r.status_code == 500
    assert r.json()["detail"] == "Proposal template not found."
    assert _no_leak(r.text), r.text


def test_a_missing_cover_letter_template_does_not_print_the_server_path(monkeypatch):
    _skip_workbook(monkeypatch)
    monkeypatch.setattr(cover_letter_writer, "fill_cover_letter", _missing)
    r = client.post("/api/generate", json=dict(_GEN, cover_letter_enabled=True))
    assert r.status_code == 500
    assert r.json()["detail"] == "Cover letter template not found."
    assert _no_leak(r.text), r.text


def test_the_cover_letter_template_route_404s_without_the_path(monkeypatch):
    monkeypatch.setattr(cover_letter_writer, "describe_template", _missing)
    r = client.get("/api/coverletter-template?work_type=epoxy&audience=Direct")
    assert r.status_code == 404
    assert r.json()["detail"] == "Cover letter template not found."
    assert _no_leak(r.text), r.text


@pytest.mark.parametrize("fn,call", [
    ("ban_user", "update_user_by_id"),
    ("unban_user", "update_user_by_id"),
    ("delete_user", "delete_user"),
])
def test_profile_admin_actions_do_not_echo_the_auth_error(monkeypatch, fn, call):
    admin = SimpleNamespace(**{call: _raise})
    monkeypatch.setattr(profiles, "get_by_id", lambda uid: {"id": uid, "email": "u@x.com"})
    monkeypatch.setattr(profiles, "_can_act", lambda actor, target: None)
    monkeypatch.setattr(profiles, "get_auth_client",
                        lambda: SimpleNamespace(auth=SimpleNamespace(admin=admin)))
    out = getattr(profiles, fn)({"email": "hanz@wetreadwell.com"}, "u2")
    assert out["ok"] is False and out["error"]
    assert _no_leak(out["error"]), out["error"]


# ── 5. the service-token routes ───────────────────────────────────────
def _svc_calls():
    return [lambda: client.get("/api/admin/proposal-pdf?draft_id=d1"),
            lambda: client.post("/api/admin/deposit-invoice", json={}),
            lambda: client.post("/api/admin/signed-contract")]


def test_the_service_routes_answer_429_past_the_window(monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN", "the-real-token")
    monkeypatch.setattr(main, "_SERVICE_RATE_MAX", 3)
    first = [call().status_code for call in _svc_calls()]         # a bad token each time
    assert first == [401, 401, 401]
    for call in _svc_calls():                                      # one window across all three
        r = call()
        assert r.status_code == 429, r.text
        assert int(r.headers["Retry-After"]) >= 1


def test_x_forwarded_for_cannot_buy_a_fresh_window(monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN", "the-real-token")
    monkeypatch.setattr(main, "_SERVICE_RATE_MAX", 2)
    codes = [client.get("/api/admin/proposal-pdf?draft_id=d1",
                        headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
             for i in range(4)]
    assert codes == [401, 401, 429, 429]


def _req(host):
    return SimpleNamespace(client=SimpleNamespace(host=host),
                           url=SimpleNamespace(path="/api/admin/proposal-pdf"))


def test_each_peer_has_its_own_window_and_it_slides(monkeypatch):
    clock = [1000.0]
    fake_time = SimpleNamespace(**{k: getattr(time, k) for k in dir(time) if not k.startswith("_")})
    fake_time.monotonic = lambda: clock[0]                          # main's own `time` only
    monkeypatch.setattr(main, "time", fake_time)
    monkeypatch.setattr(main, "_SERVICE_RATE_MAX", 2)

    main._service_rate_check(_req("172.18.0.1"))                   # nginx side
    main._service_rate_check(_req("172.18.0.1"))
    with pytest.raises(HTTPException) as over:
        main._service_rate_check(_req("172.18.0.1"))
    assert over.value.status_code == 429

    main._service_rate_check(_req("172.20.0.5"))                   # the portal: untouched

    clock[0] += main._SERVICE_RATE_WINDOW                          # the window slides past
    main._service_rate_check(_req("172.18.0.1"))


def test_the_window_is_generous_for_the_portal():
    """The portal's heaviest real burst is three calls per approval, each a 1-3 s render."""
    assert main._SERVICE_RATE_MAX >= 60 and main._SERVICE_RATE_WINDOW <= 60


def test_a_good_token_still_gets_through_under_the_limit(monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN", "the-real-token")
    monkeypatch.setattr(drafts, "load_draft", lambda draft_id: None)
    r = client.get("/api/admin/proposal-pdf?draft_id=d1",
                   headers={"X-Service-Token": "the-real-token"})
    assert r.status_code == 404                                     # past the gate, no such draft
