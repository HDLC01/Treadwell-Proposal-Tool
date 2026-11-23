"""The BD CRM's place in the proposal tool's nav (#806, spec #802 Q10, Q26, Q31).

  * nav_access.py has ONE BD CRM tab. It lists every BD page and owns no API route (hide-only: the
    BD API is guarded by BD role, Q31). It is drawn on the Admin page and grantable on Special
    permissions. BD's old login page is never gated.
  * The BD switch (BD_ENABLED) off: /api/me tells the sidebar to leave the row out, for every role,
    admins included, in `nav_off`. It is not a policy denial, so the Admin page still draws the
    BD CRM switch and nothing paints a refusal card.
  * Who sees the row, end to end (the REAL /api/me answer fed to the REAL auth.js init()): an admin
    does; a member whose role the Admin page denies the tab does not; the same member with a Special
    permissions grant does; with the user role ticked (nothing denied) every member does.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

import main
import nav_access
import special_permissions as sp
from _node import require_node, run_node
from bd import config as bd_config

MARISOL = "marisol@wetreadwell.com"
KYLE = "kyle@wetreadwell.com"
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "tab-grant-sidebar-harness.js"

BD_TAB = "/bd/"
# BD's eight pages (spec #802): This Week (the folder and its index), Contacts, one contact, Add
# contact, Potential BD Contacts, Analytics and BD's own Admin. The eighth, BD's login page, is
# replaced by the tool's sign-in and is never gated.
BD_PAGES = ["/bd/", "/bd/index.html", "/bd/contacts.html", "/bd/contact.html", "/bd/add.html",
            "/bd/review.html", "/bd/analytics.html", "/bd/admin.html"]


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "_FILE", tmp_path / "special_permissions.json")
    monkeypatch.setattr(sp, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    main._profile_cache_clear()
    yield
    main._profile_cache_clear()


def _as(monkeypatch, role, email=MARISOL):
    monkeypatch.setattr(main, "_user_email", lambda request: email)
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": email, "role": role, "status": "active"})
    main._profile_cache_clear()
    return TestClient(main.app)


# ── the tab ──────────────────────────────────────────────────────────────────
def test_there_is_exactly_one_bd_tab_and_it_lists_every_bd_page():
    bd_tabs = [h for h in nav_access.TABS if h.startswith("/bd")]
    assert bd_tabs == [BD_TAB], bd_tabs
    tab = nav_access.TABS[BD_TAB]
    assert tab["label"] == "BD CRM"
    assert list(tab["pages"]) == BD_PAGES


def test_the_bd_tab_owns_no_api_route():
    """Hide-only (Q31): the BD API answers by BD role, never by this table."""
    assert nav_access.TABS[BD_TAB]["api"] == ()
    nav_access.save({"user": [BD_TAB]}, "h")
    assert nav_access.denied_api_prefixes("user") == []
    assert not nav_access.is_api_denied("user", "/api/bd/me")


def test_the_bd_tab_is_on_the_admin_page_deniable_and_grantable():
    row = [r for r in nav_access.capability_table() if r["href"] == BD_TAB]
    assert row == [{"href": BD_TAB, "label": "BD CRM", "pages": BD_PAGES, "api": [],
                    "locked": False, "no_sidebar": False}]
    assert BD_TAB in sp.KEYS
    assert {"key": BD_TAB, "label": "BD CRM", "href": BD_TAB} in sp.catalog()
    saved = nav_access.save({"user": [BD_TAB]}, "h")
    assert saved["deny"] == {"user": [BD_TAB]}


def test_denying_the_tab_refuses_every_bd_page_and_no_tool_page():
    nav_access.save({"user": [BD_TAB]}, "h")
    for page in BD_PAGES:
        assert nav_access.page_denied("user", page) == BD_TAB, page
    assert nav_access.denied_page_map("user") == {p: BD_TAB for p in BD_PAGES}
    for page in ("/admin.html", "/analytics.html", "/portal.html", "/index.html"):
        assert nav_access.page_denied("user", page) is None, page


def test_bd_s_old_login_page_is_never_gated():
    assert "/bd/login.html" in nav_access.ALWAYS_OPEN_PAGES
    nav_access.save({"user": list(nav_access.TABS)}, "h")
    assert nav_access.page_denied("user", "/bd/login.html") is None


# ── the switch ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", ["user", "admin", "super_admin"])
def test_switch_off_tells_every_sidebar_to_leave_the_row_out(monkeypatch, role):
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    body = _as(monkeypatch, role).get("/api/me").json()
    assert body["ok"] is True
    assert body["nav_off"] == [BD_TAB]
    # not a policy denial: no refusal card, and the role's own policy is untouched
    assert BD_TAB not in body["nav_denied"]
    assert not set(BD_PAGES) & set(body["nav_denied_pages"])


@pytest.mark.parametrize("role", ["user", "admin", "super_admin"])
def test_switch_on_leaves_the_row_to_the_nav_policy(monkeypatch, role):
    body = _as(monkeypatch, role).get("/api/me").json()
    assert body["nav_off"] == []


def test_switch_off_without_a_profile_row_still_leaves_the_row_out(monkeypatch):
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    monkeypatch.setattr(main, "_user_email", lambda request: "newcomer@wetreadwell.com")
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: None)
    monkeypatch.setattr(main.profiles, "ensure_profile", lambda *a, **k: None)
    body = TestClient(main.app).get("/api/me").json()
    assert body["nav_off"] == [BD_TAB]


# ── who sees the row: the real /api/me, through the real auth.js ─────────────
def _sidebar(tmp_path, me, pathname="/portal.html"):
    require_node()
    f = tmp_path / ("me-%s.json" % abs(hash(json.dumps(me, sort_keys=True))))
    f.write_text(json.dumps(me), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f, pathname)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _sees_row(monkeypatch, tmp_path, role, email=MARISOL):
    me = _as(monkeypatch, role, email).get("/api/me").json()
    out = _sidebar(tmp_path, me)
    assert "/portal.html" in out["entries"], "vacuity: the harness drew no sidebar"
    return BD_TAB in out["entries"]


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_an_admin_sees_the_row(monkeypatch, tmp_path, role):
    nav_access.save({"user": [BD_TAB]}, "h")
    assert _sees_row(monkeypatch, tmp_path, role) is True


def test_a_member_whose_role_is_denied_the_tab_does_not(monkeypatch, tmp_path):
    nav_access.save({"user": [BD_TAB]}, "h")
    assert _sees_row(monkeypatch, tmp_path, "user", KYLE) is False


def test_the_same_member_with_a_special_permissions_grant_does(monkeypatch, tmp_path):
    nav_access.save({"user": [BD_TAB]}, "h")
    sp.save({MARISOL: [BD_TAB]}, "h")
    assert _sees_row(monkeypatch, tmp_path, "user", MARISOL) is True
    assert _sees_row(monkeypatch, tmp_path, "user", KYLE) is False, "the grant is for one person only"


def test_ticking_the_user_role_on_the_admin_page_shows_it_to_every_member(monkeypatch, tmp_path):
    nav_access.save({"user": [BD_TAB]}, "h")
    nav_access.save({}, "h")          # the Admin page's box ticked again: nothing denied
    assert _sees_row(monkeypatch, tmp_path, "user", KYLE) is True
    assert _sees_row(monkeypatch, tmp_path, "user", MARISOL) is True


@pytest.mark.parametrize("role", ["user", "admin", "super_admin"])
def test_with_the_switch_off_nobody_sees_the_row(monkeypatch, tmp_path, role):
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    sp.save({MARISOL: [BD_TAB]}, "h")
    assert _sees_row(monkeypatch, tmp_path, role) is False


def test_a_denied_member_standing_on_a_bd_page_gets_the_refusal_card(monkeypatch, tmp_path):
    nav_access.save({"user": [BD_TAB]}, "h")
    me = _as(monkeypatch, "user", KYLE).get("/api/me").json()
    for page in ("/bd/", "/bd/index.html", "/bd/admin.html"):
        out = _sidebar(tmp_path, me, page)
        assert out["refusals"] == 1, page


# ── the words ────────────────────────────────────────────────────────────────
def test_the_glossary_s_bd_role_lists_the_five_bd_roles():
    """Q29: super admin is the fifth BD role, the one bd/auth.py already has."""
    text = (pathlib.Path(__file__).resolve().parents[2] / "GLOSSARY.md").read_text(encoding="utf-8")
    entry = text[text.index("**BD role**:"):]
    entry = entry[:entry.index("\n\n")]
    assert "salesperson, assistant, manager, admin or super admin" in entry, entry
