"""Special permissions: one admin-only ability granted to one named member.

Three claims, each executed through the real app rather than read off the source:
  * the STORE: a missing or garbled file grants nobody anything; unknown keys and blank emails are
    dropped on the way in and on the way out; emails are case-folded.
  * the GATE: for each grantable ability, a member without it is refused with the same 403 as
    before, a member with it gets through, an admin gets through - and a grant never opens a route
    that is not grantable.
  * the ROUTES: the grants are edited by admins only, and /api/me tells each caller what they hold.
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
import special_permissions as sp

MARISOL = "marisol@wetreadwell.com"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "_FILE", tmp_path / "special_permissions.json")
    monkeypatch.setattr(sp, "_DATA_DIR", tmp_path)
    main._profile_cache_clear()
    yield
    main._profile_cache_clear()


def _as(monkeypatch, role, email=MARISOL):
    monkeypatch.setattr(main, "_user_email", lambda request: email)
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": email, "role": role, "status": "active"})
    main._profile_cache_clear()
    return TestClient(main.app)


# ── the store ────────────────────────────────────────────────────────────────
def test_absent_file_grants_nobody_anything():
    assert not sp._FILE.exists()
    assert sp.load()["grants"] == {}
    assert sp.grants_for(MARISOL) == []
    assert sp.has(MARISOL, "items_pricing") is False


@pytest.mark.parametrize("raw", ["{not json", "[]", '"a string"', json.dumps({"grants": "nope"})])
def test_garbled_file_grants_nobody_anything(raw):
    sp._FILE.write_text(raw, encoding="utf-8")
    assert sp.load()["grants"] == {}
    assert sp.has(MARISOL, "items_pricing") is False


def test_round_trip_keeps_order_and_author():
    out = sp.save({MARISOL: ["markup", "items_pricing"]}, "hanz@wetreadwell.com")
    assert out["grants"] == {MARISOL: ["items_pricing", "markup"]}  # GRANTS order, not tick order
    again = sp.load()
    assert again["grants"] == out["grants"]
    assert again["updated_by"] == "hanz@wetreadwell.com"
    assert again["updated_at"]
    assert sp.grants_for(MARISOL) == ["items_pricing", "markup"]


def test_unknown_keys_and_blank_emails_are_dropped_on_save():
    out = sp.save({MARISOL: ["items_pricing", "manage_users", "nav_access"], "  ": ["markup"],
                   "kyle@wetreadwell.com": ["not_a_key"]}, "h")
    assert out["grants"] == {MARISOL: ["items_pricing"]}


def test_unknown_keys_and_blank_emails_are_dropped_on_load():
    """A hand-edited file is not trusted either: the strip runs on read too."""
    sp._FILE.write_text(json.dumps({"version": 1, "grants": {
        MARISOL: ["items_pricing", "users"], "": ["markup"], "x@y.com": "markup"}}),
        encoding="utf-8")
    assert sp.load()["grants"] == {MARISOL: ["items_pricing"]}
    assert sp.has(MARISOL, "users") is False


def test_email_is_case_folded():
    sp.save({"  Marisol@WeTreadwell.com ": ["markup"]}, "h")
    assert sp.load()["grants"] == {MARISOL: ["markup"]}
    assert sp.has("MARISOL@wetreadwell.com", "markup") is True


# ── the gate ─────────────────────────────────────────────────────────────────
class _Ran(Exception):
    """Raised by the stubbed store call: proof the handler got past its gate."""


def _stub_downstream(monkeypatch):
    def ran(*a, **k):
        raise _Ran()
    monkeypatch.setattr(main.library, "update_item", ran)
    monkeypatch.setattr(main.library, "create_vendor", ran)
    monkeypatch.setattr(main.markup, "delete_rule", ran)
    monkeypatch.setattr(main.condition_defaults, "set_default", ran)
    monkeypatch.setattr(main, "_portal", ran)
    monkeypatch.setattr(main, "_portal_visibility", ran)


# One representative route per ability.
REPRESENTATIVE = {
    "items_pricing": ("patch", "/api/library/items/i1", {"bulk_cost": 12.5}),
    "library_lists": ("post", "/api/library/vendors", {"name": "Acme"}),
    "markup": ("delete", "/api/markup/rules/r1", None),
    "condition_defaults": ("put", "/api/condition-defaults/occupied", {"on": True}),
    "notify_recipients": ("delete", "/api/portal/notify-recipients/7", None),
    "delete_projects": ("post", "/api/project/d1/delete", None),
}


def _call(client, method, path, body):
    kw = {} if body is None else {"json": body}
    return getattr(client, method)(path, **kw)


def _passed(client, method, path, body):
    try:
        r = _call(client, method, path, body)
    except _Ran:
        return True
    assert r.status_code == 403, (path, r.status_code, r.text)
    assert r.json().get("detail") == "Admin access required."
    return False


def test_every_grant_key_has_a_representative_route():
    assert set(REPRESENTATIVE) == set(sp.KEYS)


@pytest.mark.parametrize("key", list(REPRESENTATIVE))
def test_member_without_the_grant_is_refused(monkeypatch, key):
    _stub_downstream(monkeypatch)
    # Somebody ELSE holding the grant, and Marisol holding every OTHER one, must not open it.
    sp.save({"kyle@wetreadwell.com": [key], MARISOL: [k for k in sp.KEYS if k != key]}, "h")
    assert _passed(_as(monkeypatch, "user"), *REPRESENTATIVE[key]) is False


@pytest.mark.parametrize("key", list(REPRESENTATIVE))
def test_member_with_the_grant_passes(monkeypatch, key):
    _stub_downstream(monkeypatch)
    sp.save({MARISOL: [key]}, "h")
    assert _passed(_as(monkeypatch, "user"), *REPRESENTATIVE[key]) is True


@pytest.mark.parametrize("role", ["admin", "super_admin"])
@pytest.mark.parametrize("key", list(REPRESENTATIVE))
def test_admin_passes_with_no_grants_at_all(monkeypatch, key, role):
    _stub_downstream(monkeypatch)
    assert _passed(_as(monkeypatch, role, "boss@wetreadwell.com"), *REPRESENTATIVE[key]) is True


def test_a_member_with_every_grant_still_cannot_reach_admin_only_routes(monkeypatch):
    sp.save({MARISOL: list(sp.KEYS)}, "h")
    c = _as(monkeypatch, "user")
    for method, path, body in (
            ("patch", "/api/admin/users/u2/role", {"role": "admin"}),
            ("get", "/api/admin/users", None),
            ("get", "/api/admin/special-permissions", None),
            ("put", "/api/admin/special-permissions", {"grants": {MARISOL: list(sp.KEYS)}}),
            ("put", "/api/admin/nav-access", {"deny": {}}),
            ("delete", "/api/admin/projects/p1", None)):
        r = _call(c, method, path, body)
        assert r.status_code == 403, (path, r.status_code)


def test_item_edit_without_admin_fields_needs_no_grant(monkeypatch):
    """The gate only fires on the admin-only fields; an ordinary edit stays open to everyone."""
    _stub_downstream(monkeypatch)
    with pytest.raises(_Ran):
        _as(monkeypatch, "user").patch("/api/library/items/i1", json={"name": "Primer"})


# ── the routes ───────────────────────────────────────────────────────────────
def test_grants_routes_are_admin_only(monkeypatch):
    c = _as(monkeypatch, "user")
    assert c.get("/api/admin/special-permissions").status_code == 403
    assert c.put("/api/admin/special-permissions", json={"grants": {}}).status_code == 403
    assert not sp._FILE.exists()


def test_admin_reads_and_writes_the_grants(monkeypatch):
    logged = []
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: logged.append(a))
    c = _as(monkeypatch, "admin", "boss@wetreadwell.com")
    r = c.get("/api/admin/special-permissions")
    assert r.status_code == 200
    body = r.json()
    assert [g["key"] for g in body["grants_catalog"]] == list(sp.KEYS)
    assert all(g["label"] and g["description"] for g in body["grants_catalog"])
    assert body["grants"] == {}
    r = c.put("/api/admin/special-permissions",
              json={"grants": {"Marisol@WeTreadwell.com": ["items_pricing", "bogus"]}})
    assert r.status_code == 200, r.text
    assert r.json()["grants"] == {MARISOL: ["items_pricing"]}
    assert r.json()["updated_by"] == "boss@wetreadwell.com"
    assert sp.has(MARISOL, "items_pricing")
    assert logged and logged[-1][2] == "special_permissions_changed"
    assert logged[-1][3] == {"grants": {MARISOL: ["items_pricing"]}}


def test_put_rejects_an_unknown_top_level_key(monkeypatch):
    c = _as(monkeypatch, "admin", "boss@wetreadwell.com")
    assert c.put("/api/admin/special-permissions", json={"grant": {}}).status_code == 422


def test_me_carries_the_callers_grants(monkeypatch):
    sp.save({MARISOL: ["markup", "items_pricing"]}, "h")
    assert _as(monkeypatch, "user").get("/api/me").json()["grants"] == ["items_pricing", "markup"]
    assert _as(monkeypatch, "user", "kyle@wetreadwell.com").get("/api/me").json()["grants"] == []
    assert _as(monkeypatch, "admin", "boss@wetreadwell.com").get("/api/me").json()["grants"] \
        == list(sp.KEYS)
