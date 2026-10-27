"""POST /api/portal/deposit/{deposit_id}/reveal -- the drawer's Show button for a bank number
(bank_crypto.py, portal repo, 2026-09-29). The drawer's own /api/portal/proposal/{id} no longer
carries routing_number/account_number at all; this is the one route that can still get them, one
deposit at a time.

Three things this file has to prove, none of them satisfied by reading the source:
  * the proxy forwards the SIGNED-IN caller's own email as staff_email -- never one the client
    supplies, or a member could claim someone else's reveal in the portal's audit log.
  * the response is never cached (Cache-Control: no-store) -- it carries the plaintext numbers.
  * the nav gate never refuses this route: /portal.html is LOCKED, and since 2026-10-27 (Hanz chose
    "hides the tab only" for every tab) no TABS entry claims an API route at all.
"""
import pytest
from fastapi.testclient import TestClient

import main
import nav_access

client = TestClient(main.app)


def _wire(monkeypatch, role="admin", email="tester@wetreadwell.com"):
    """Stub the caller's profile (role) and capture what main._portal was handed, mirroring
    test_followup_proxies.py's _wire -- this file's proxy is the same shape as those."""
    cap = {}
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": role})

    def fake_portal(path, method="GET", body=None):
        cap.update(path=path, method=method, body=body)
        return {"ok": True, "routing_number": "021000021", "account_number": "000123456789",
                "account_type": "checking"}

    monkeypatch.setattr(main, "_portal", fake_portal)
    return cap


def test_reveal_forwards_the_signed_in_users_own_email_never_a_client_supplied_one(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/deposit/dep-1/reveal",
                    json={"staff_email": "somebody-else@wetreadwell.com"})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/deposit/dep-1/reveal"
    assert cap["method"] == "POST"
    assert cap["body"] == {"staff_email": "tester@wetreadwell.com"}, (
        "a client-supplied staff_email must never reach the portal: %r" % cap["body"])


def test_reveal_response_is_never_cached(monkeypatch):
    _wire(monkeypatch)
    r = client.post("/api/portal/deposit/dep-1/reveal", json={})
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store", (
        "this response carries the plaintext bank numbers and must never be cached: %r"
        % r.headers.get("cache-control"))


def test_reveal_returns_what_the_portal_sent(monkeypatch):
    _wire(monkeypatch)
    body = client.post("/api/portal/deposit/dep-1/reveal", json={}).json()
    assert body["routing_number"] == "021000021"
    assert body["account_number"] == "000123456789"
    assert body["account_type"] == "checking"


def test_an_unsafe_deposit_id_is_refused(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/deposit/..%2Fevil/reveal", json={})
    assert r.status_code != 200
    assert cap == {}, "an unsafe id must never reach _portal: %r" % cap


# ── the real nav-access gate, not a source-text grep ──────────────────────────
@pytest.fixture(autouse=True)
def _isolate_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)
    main._profile_cache_clear()
    yield
    main._profile_cache_clear()


def _as(monkeypatch, role, email="staffer@wetreadwell.com"):
    monkeypatch.setattr(main, "_user_email", lambda request: email)
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": email, "role": role, "status": "active"})
    main._profile_cache_clear()
    return TestClient(main.app)


def test_portal_html_cannot_actually_be_denied_so_this_route_is_reachable_by_any_signed_in_role(
        monkeypatch):
    """/portal.html is in nav_access.LOCKED — it is HOME_PAGE in auth.js, and sanitize() drops it
    from a deny map on save() (see test_nav_access.py::test_portal_html_can_never_actually_be_
    denied). So calling save({"user": ["/portal.html"]}) here would silently persist NOTHING, and a
    test that then asserted a 403 would be asserting something save() can never produce — proven
    wrong the first time this was tried. The honest claim for TODAY is the opposite one: every
    signed-in role reaches this route, because the board can never be taken away from any of
    them. That is not a new hole this feature opens — the same signed-in accounts already saw
    these numbers, unmasked, in the drawer's own JSON before this change."""
    nav_access.save({"user": ["/portal.html"]}, "k@x.com")
    c = _as(monkeypatch, "user")
    monkeypatch.setattr(main, "_portal", lambda path, method="GET", body=None: {"ok": True})
    r = c.post("/api/portal/deposit/dep-1/reveal", json={})
    assert r.status_code == 200, r.text


def test_the_gate_does_not_refuse_the_route_even_if_the_board_were_denied(monkeypatch):
    """/portal.html claimed /api/portal/deposit/ until 2026-10-27, when Hanz chose "hides the tab
    only" for every tab and every TABS "api" tuple went empty. Bypasses save()'s LOCKED filter by
    monkeypatching nav_access.get() directly: even a policy denying the board refuses nothing at the
    nav gate. The route stays behind sign-in, as it always was."""
    monkeypatch.setattr(nav_access, "get", lambda: {"deny": {"user": ["/portal.html"]}})
    c = _as(monkeypatch, "user")
    _wire(monkeypatch, role="user", email="staffer@wetreadwell.com")   # stub portal, no network
    main._profile_cache_clear()
    r = c.post("/api/portal/deposit/dep-1/reveal", json={})
    assert r.status_code == 200, r.text
    assert not r.json().get("nav_denied"), r.text
