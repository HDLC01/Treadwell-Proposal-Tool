"""The staff side of attachments: a proxy that must not touch the bytes, and must not be public.

The portal owns attachments — the thread they hang off, the volume they live on, the allow-list
and the size caps. These routes exist only because the staff browser is on a different origin and
holds no portal admin token. So what is worth testing here is exactly what a proxy can get wrong:
changing what it forwards, swallowing what comes back, and being reachable by somebody who should
not reach it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402


class _Resp:
    def __init__(self, status=200, content=b"", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}


class _Client:
    """Stands in for httpx.Client, recording the one call it is given."""

    seen: dict = {}

    def __init__(self, **kw):
        _Client.seen = {"init": kw}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url, content=None):
        _Client.seen.update(method=method, url=url, content=content)
        return _Resp(201, b"BYTES-BACK",
                     {"content-type": "image/jpeg",
                      "content-disposition": 'inline; filename="slab.jpg"',
                      "set-cookie": "portal_session=secret"})


@pytest.fixture
def wired(monkeypatch):
    import httpx
    monkeypatch.setenv("PORTAL_ADMIN_URL", "http://portal:8898")
    monkeypatch.setenv("SERVICE_TOKEN", "svc")
    monkeypatch.setattr(httpx, "Client", _Client)
    return _Client


@pytest.mark.anyio
async def test_the_bytes_are_forwarded_unchanged(wired):
    """Not re-encoded, not parsed, not validated. A proxy that "helpfully" decoded a JPEG would be
    a second, weaker copy of a rule the portal already owns — and the two would drift."""
    blob = bytes(range(256))
    await main._portal_raw("/api/admin/proposal/p1/upload?name=slab.jpg", "POST", blob, "image/jpeg")
    assert wired.seen["content"] == blob
    assert wired.seen["init"]["headers"]["Content-Type"] == "image/jpeg"
    assert wired.seen["init"]["headers"]["X-Service-Token"] == "svc"
    assert wired.seen["url"] == "http://portal:8898/api/admin/proposal/p1/upload?name=slab.jpg"


@pytest.mark.anyio
async def test_the_portals_own_answer_comes_back_whole(wired):
    """Status, content type and Content-Disposition all survive, because they are what make a
    .docx download under its real name instead of rendering as gibberish. And the portal's REFUSAL
    wording survives with them — "that kind of file cannot be attached" is a sentence the
    estimator can act on; a 502 invented on the way past is not."""
    r = await main._portal_raw("/api/admin/proposal/p1/file/x", "GET", b"", "")
    assert r.status_code == 201
    assert r.body == b"BYTES-BACK"
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["content-disposition"] == 'inline; filename="slab.jpg"'


@pytest.mark.anyio
async def test_a_header_we_did_not_ask_for_does_not_come_back(wired):
    """Only three headers are copied. A blanket copy would forward the portal's own Set-Cookie
    onto this origin, which is a session-fixation vector nobody would think to look for in a file
    download."""
    r = await main._portal_raw("/api/admin/proposal/p1/file/x", "GET", b"", "")
    assert "set-cookie" not in {k.lower() for k in r.headers}


@pytest.mark.anyio
async def test_an_unconfigured_portal_says_so_rather_than_timing_out(monkeypatch):
    monkeypatch.delenv("PORTAL_ADMIN_URL", raising=False)
    monkeypatch.setenv("SERVICE_TOKEN", "svc")
    with pytest.raises(main.HTTPException) as e:
        await main._portal_raw("/x", "POST", b"", "")
    assert e.value.status_code == 503


@pytest.mark.anyio
async def test_the_upload_gets_longer_than_the_json_proxy_allows(wired):
    """A 15 MB photograph over the VPS link would time out on the 20 seconds the JSON proxy
    allows, and the estimator would see a perfectly good upload fail."""
    await main._portal_raw("/x", "POST", b"0" * 10, "image/jpeg")
    assert wired.seen["init"]["timeout"] >= 60


# ── the routes are not public ────────────────────────────────────────────────

@pytest.mark.parametrize("path,method", [
    ("/api/portal/proposal/p1/upload", "POST"),
    ("/api/portal/proposal/p1/file/abc", "GET"),
])
def test_neither_new_route_is_reachable_without_a_token(path, method):
    """The whole point of routing attachments through this app rather than linking straight at the
    portal is that the staff browser has a Supabase token and no portal session. If either route
    slipped into the public set, an unauthenticated caller could read a customer's photographs."""
    assert not main._auth_is_public(path, method), path
    assert path not in main._AUTH_PUBLIC_PATHS


# ── the publish body ─────────────────────────────────────────────────────────

def test_publish_attachments_are_forwarded_but_not_decoded():
    """Forwarded whole, deliberately. The portal decodes the base64, checks the type and enforces
    the 10 MB total — putting a second copy of any of that here is how the two ends stop agreeing
    about which files are allowed."""
    import inspect
    src = inspect.getsource(main.api_portal_publish)
    assert 'body["attachments"] = payload.attachments[:10]' in src
    assert "b64decode" not in src, (
        "the tool started decoding attachments — that is the portal's rule to own")


def test_a_send_with_nothing_attached_carries_the_byte_for_byte_legacy_body():
    """Every optional field on this route is forwarded only when it has a value, so a send that
    uses none of them produces exactly the request the portal has always received. Worth pinning:
    this route is the one action in the product that must not fail."""
    import inspect
    src = inspect.getsource(main.api_portal_publish)
    assert "if payload and payload.attachments:" in src


def test_the_model_defaults_to_no_attachments():
    """A caller that omits the field forwards nothing — same contract as no_followups and the
    notify picks beside it."""
    assert main.PortalPublishIn().attachments == []
