"""Special permissions: one TAB granted to one named member.

Hanz, 2026-10-27: "why is special permissions only linked to items and assemblies? It should be for
the whole tab as well." One checkbox per tab. Ticking a tab gives that person (a) the tab - it shows
in their sidebar and its page opens even if their role is unticked for it on the matrix - and (b)
every admin-only edit inside it.

Claims, each executed through the real app rather than read off the source:
  * the STORE: keys are nav_access.TABS hrefs minus the Admin page; a missing or garbled file grants
    nobody anything; unknown keys and blank emails are dropped; the six ability keys of the first cut
    migrate to the tab each lived on.
  * the GATE: for each grantable route, a member without its tab is refused with the same 403 as
    before, a member with it gets through, an admin gets through - and a grant never opens a route
    that is not grantable.
  * the TAB: a role denied a tab keeps it denied for everyone except the person granted it - in
    /api/me's nav lists, in the nav gate's API refusal, and in the real sidebar auth.js draws.
  * the ROUTES: the grants are edited by admins only, and /api/me tells each caller what they hold.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main
import nav_access
import special_permissions as sp

MARISOL = "marisol@wetreadwell.com"
KYLE = "kyle@wetreadwell.com"
BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
SIDEBAR_HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "tab-grant-sidebar-harness.js"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sp, "_FILE", tmp_path / "special_permissions.json")
    monkeypatch.setattr(sp, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)
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
def test_the_keys_are_every_tab_except_admin_in_matrix_order():
    assert sp.KEYS == tuple(h for h in nav_access.TABS if h != "/admin.html")
    assert "/admin.html" not in sp.KEYS
    cat = sp.catalog()
    assert [c["key"] for c in cat] == list(sp.KEYS)
    assert [c["label"] for c in cat] == [nav_access.TABS[h]["label"] for h in sp.KEYS]
    assert all(c["href"] == c["key"] for c in cat)


def test_absent_file_grants_nobody_anything():
    assert not sp._FILE.exists()
    assert sp.load()["grants"] == {}
    assert sp.grants_for(MARISOL) == []
    assert sp.has(MARISOL, sp.LIBRARY) is False


@pytest.mark.parametrize("raw", ["{not json", "[]", '"a string"', json.dumps({"grants": "nope"})])
def test_garbled_file_grants_nobody_anything(raw):
    sp._FILE.write_text(raw, encoding="utf-8")
    assert sp.load()["grants"] == {}
    assert sp.has(MARISOL, sp.LIBRARY) is False


def test_round_trip_keeps_order_and_author():
    out = sp.save({MARISOL: ["/markup.html", "/library.html"]}, "hanz@wetreadwell.com")
    order = [h for h in sp.KEYS if h in ("/markup.html", "/library.html")]
    assert out["grants"] == {MARISOL: order}  # matrix order, not tick order
    again = sp.load()
    assert again["grants"] == out["grants"]
    assert again["updated_by"] == "hanz@wetreadwell.com"
    assert again["updated_at"]
    assert sp.grants_for(MARISOL) == order


def test_unknown_keys_admin_and_blank_emails_are_dropped_on_save():
    out = sp.save({MARISOL: ["/library.html", "/admin.html", "manage_users", "/nope.html"],
                   "  ": ["/markup.html"], KYLE: ["not_a_key"]}, "h")
    assert out["grants"] == {MARISOL: ["/library.html"]}


def test_unknown_keys_and_blank_emails_are_dropped_on_load():
    """A hand-edited file is not trusted either: the strip runs on read too."""
    sp._FILE.write_text(json.dumps({"version": 2, "grants": {
        MARISOL: ["/library.html", "/admin.html", "users"], "": ["/markup.html"],
        "x@y.com": "/markup.html"}}), encoding="utf-8")
    assert sp.load()["grants"] == {MARISOL: ["/library.html"]}
    assert sp.has(MARISOL, "/admin.html") is False


def test_email_is_case_folded():
    sp.save({"  Marisol@WeTreadwell.com ": ["/markup.html"]}, "h")
    assert sp.load()["grants"] == {MARISOL: ["/markup.html"]}
    assert sp.has("MARISOL@wetreadwell.com", "/markup.html") is True


def test_a_file_saved_by_the_six_ability_version_migrates_to_tabs():
    """Grants ticked on staging before the per-tab change keep working: each old ability key is
    read as the tab it lived on, and an unknown key is dropped."""
    sp._FILE.write_text(json.dumps({"version": 1, "grants": {
        MARISOL: ["items_pricing", "library_lists", "condition_defaults", "bogus"],
        KYLE: ["markup", "notify_recipients", "delete_projects"],
        "sam@wetreadwell.com": ["bogus"]}}), encoding="utf-8")
    grants = sp.load()["grants"]
    assert grants[MARISOL] == ["/library.html"]
    assert grants[KYLE] == [h for h in sp.KEYS
                            if h in ("/markup.html", "/notifications.html", "/portal.html")]
    assert "sam@wetreadwell.com" not in grants
    assert sp.has(KYLE, "/portal.html") and sp.has(MARISOL, "/library.html")


def test_a_moved_href_is_read_as_its_new_tab():
    sp.save({MARISOL: ["/polish-intake.html"]}, "h")
    assert sp.grants_for(MARISOL) == ["/v2-board.html"]


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


# One representative route per route group, each with the tab whose grant opens it.
REPRESENTATIVE = {
    "item pricing": ("/library.html", "patch", "/api/library/items/i1", {"bulk_cost": 12.5}),
    "library lists": ("/library.html", "post", "/api/library/vendors", {"name": "Acme"}),
    "condition defaults": ("/library.html", "put", "/api/condition-defaults/occupied", {"on": True}),
    "markup": ("/markup.html", "delete", "/api/markup/rules/r1", None),
    "notify roster": ("/notifications.html", "delete", "/api/portal/notify-recipients/7", None),
    "delete project": ("/portal.html", "post", "/api/project/d1/delete", None),
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


def test_every_require_grant_names_a_tab_the_representatives_cover():
    src = (BACKEND / "main.py").read_text(encoding="utf-8")
    named = set(re.findall(r"_require_grant\(request, special_permissions\.([A-Z]+)\)", src))
    assert named == {"LIBRARY", "MARKUP", "NOTIFICATIONS", "PROJECTS"}
    assert not re.search(r'_require_grant\(request, "', src), "a grant key is a literal again"
    tabs = {getattr(sp, n) for n in named}
    assert tabs <= set(sp.KEYS)
    assert {t for t, *_ in REPRESENTATIVE.values()} == tabs


@pytest.mark.parametrize("group", list(REPRESENTATIVE))
def test_member_without_the_tab_is_refused(monkeypatch, group):
    _stub_downstream(monkeypatch)
    tab, *call = REPRESENTATIVE[group]
    # Somebody ELSE holding the tab, and Marisol holding every OTHER one, must not open it.
    sp.save({KYLE: [tab], MARISOL: [k for k in sp.KEYS if k != tab]}, "h")
    assert _passed(_as(monkeypatch, "user"), *call) is False


@pytest.mark.parametrize("group", list(REPRESENTATIVE))
def test_member_with_the_tab_passes(monkeypatch, group):
    _stub_downstream(monkeypatch)
    tab, *call = REPRESENTATIVE[group]
    sp.save({MARISOL: [tab]}, "h")
    assert _passed(_as(monkeypatch, "user"), *call) is True


@pytest.mark.parametrize("role", ["admin", "super_admin"])
@pytest.mark.parametrize("group", list(REPRESENTATIVE))
def test_admin_passes_with_no_grants_at_all(monkeypatch, group, role):
    _stub_downstream(monkeypatch)
    _tab, *call = REPRESENTATIVE[group]
    assert _passed(_as(monkeypatch, role, "boss@wetreadwell.com"), *call) is True


def test_a_member_with_every_tab_still_cannot_reach_admin_only_routes(monkeypatch):
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


# ── somebody ELSE's per-project notifications: the two doors that were admin-only ──
# The card promises "the tab and every admin-only edit in it". Setting a colleague's notifications
# on one project is an admin-only edit on Notification Sending (its per-project card) and on Direct
# Projects (the drawer's picks), so each tab's grant must open its own door and no other.
SELF_ONLY = "You can only change your own notifications for a project."


def _override_other(client):
    try:
        r = client.put("/api/portal/proposal/p1/notify-overrides",
                       json={"email": KYLE, "mode": "mute"})
    except _Ran:
        return True
    assert r.status_code == 403 and r.json().get("detail") == SELF_ONLY, r.text
    return False


@pytest.mark.parametrize("held, opens", [
    (["/notifications.html"], True),
    ([k for k in sp.KEYS if k != "/notifications.html"], False),
    ([], False),
])
def test_a_project_override_for_somebody_else_follows_the_notifications_tab(monkeypatch, held, opens):
    _stub_downstream(monkeypatch)
    sp.save({MARISOL: held} if held else {}, "h")
    assert _override_other(_as(monkeypatch, "user")) is opens


def test_a_project_override_for_yourself_needs_no_grant(monkeypatch):
    _stub_downstream(monkeypatch)
    with pytest.raises(_Ran):
        _as(monkeypatch, "user").put("/api/portal/proposal/p1/notify-overrides",
                                     json={"email": MARISOL, "mode": "mute"})


@pytest.mark.parametrize("held, opens", [
    (["/portal.html"], True),
    ([k for k in sp.KEYS if k != "/portal.html"], False),
    ([], False),
])
def test_the_drawers_picks_for_somebody_else_follow_the_direct_projects_tab(monkeypatch, held, opens):
    written = []
    monkeypatch.setattr(main.drafts, "get_notify_picks", lambda pid: {"add": [], "mute": []})
    monkeypatch.setattr(main.drafts, "set_notify_picks",
                        lambda pid, add, mute, actor: (written.append((add, mute)), True)[1])
    monkeypatch.setattr(main.drafts, "latest_revision_no", lambda pid: 0)
    sp.save({MARISOL: held} if held else {}, "h")
    r = _as(monkeypatch, "user").post("/api/draft/d1/notify", json={"add": [KYLE], "mute": []})
    if opens:
        assert r.status_code == 200, r.text
        assert written == [([KYLE], [])]
    else:
        assert r.status_code == 403 and r.json().get("detail") == SELF_ONLY, r.text
        assert written == []


# ── the tab itself: the grant overrides the role's deny for that one person ──
def test_me_nav_lists_drop_a_granted_tab_for_that_person_only(monkeypatch):
    nav_access.save({"user": ["/library.html", "/leads.html", "/history.html"]}, "h")
    sp.save({MARISOL: ["/library.html", "/history.html"]}, "h")
    mine = _as(monkeypatch, "user").get("/api/me").json()
    assert mine["nav_denied"] == ["/leads.html"]
    assert mine["nav_denied_pages"] == {"/leads.html": "/leads.html"}
    kyle = _as(monkeypatch, "user", KYLE).get("/api/me").json()
    assert kyle["nav_denied"] == ["/library.html", "/leads.html", "/history.html"]
    assert set(kyle["nav_denied_pages"]) == {"/library.html", "/leads.html", "/history.html"}
    assert nav_access.denied_paths("user") == ["/library.html", "/leads.html", "/history.html"], (
        "the role's own policy must not change")


def _gate_refused(client, path):
    try:
        r = client.get(path)
    except Exception:  # noqa: BLE001 - the handler ran, so the gate let it through
        return False
    if r.status_code != 403:
        return False
    try:
        return bool(r.json().get("nav_denied"))
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture
def history_sealed(monkeypatch):
    """Every tab hides only since 2026-10-27 (#720), so the nav gate refuses no API route by
    itself. The grant override inside the gate (_nav_policy_for) is still real code: these tests
    put History's old route claim back to prove a granted person gets through it and others don't."""
    monkeypatch.setitem(nav_access.TABS, "/history.html",
                        {**nav_access.TABS["/history.html"], "api": ("/api/history",)})


@pytest.mark.usefixtures("history_sealed")
def test_the_nav_gate_lets_a_granted_person_reach_the_tabs_api(monkeypatch):
    nav_access.save({"user": ["/history.html"]}, "h")
    sp.save({MARISOL: ["/history.html"]}, "h")
    assert _gate_refused(_as(monkeypatch, "user", KYLE), "/api/history") is True
    assert _gate_refused(_as(monkeypatch, "user"), "/api/history") is False


@pytest.mark.usefixtures("history_sealed")
def test_a_grant_of_a_different_tab_leaves_the_gate_shut(monkeypatch):
    nav_access.save({"user": ["/history.html"]}, "h")
    sp.save({MARISOL: ["/library.html"]}, "h")
    assert _gate_refused(_as(monkeypatch, "user"), "/api/history") is True


@pytest.mark.usefixtures("history_sealed")
def test_the_gate_and_me_fail_closed_on_the_grant_when_its_store_throws(monkeypatch):
    """A broken grants store grants nothing: the role's denial stands, and nothing 500s."""
    nav_access.save({"user": ["/history.html"]}, "h")
    sp.save({MARISOL: ["/history.html"]}, "h")
    monkeypatch.setattr(sp, "grants_for", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    c = _as(monkeypatch, "user")
    assert _gate_refused(c, "/api/history") is True
    body = c.get("/api/me").json()
    assert body["ok"] is True and body["nav_denied"] == ["/history.html"]


def _sidebar(tmp_path, me, pathname):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    f = tmp_path / "me.json"
    f.write_text(json.dumps(me), encoding="utf-8")
    proc = subprocess.run(["node", str(SIDEBAR_HARNESS), str(FRONTEND), str(f), pathname],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_real_sidebar_shows_the_granted_tab_and_its_page_opens(monkeypatch, tmp_path):
    """End to end: the REAL /api/me answer, fed to auth.js's real init()."""
    nav_access.save({"user": ["/library.html", "/markup.html"]}, "h")
    sp.save({MARISOL: ["/library.html"]}, "h")
    mine = _as(monkeypatch, "user").get("/api/me").json()
    kyle = _as(monkeypatch, "user", KYLE).get("/api/me").json()

    granted = _sidebar(tmp_path, mine, "/library.html")
    assert granted["refusals"] == 0 and granted["ready"] == "settled"
    assert "/library.html" in granted["entries"]
    assert "/markup.html" not in granted["entries"], "only the granted tab comes back"

    refused = _sidebar(tmp_path, kyle, "/library.html")
    assert refused["refusals"] == 1, "an ungranted member is still refused the page"
    shown = _sidebar(tmp_path, kyle, "/portal.html")
    assert shown["refusals"] == 0 and "/portal.html" in shown["entries"]
    assert "/library.html" not in shown["entries"]


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
    assert all(g["label"] and g["href"] for g in body["grants_catalog"])
    assert "/admin.html" not in [g["key"] for g in body["grants_catalog"]]
    assert body["grants"] == {}
    r = c.put("/api/admin/special-permissions",
              json={"grants": {"Marisol@WeTreadwell.com": ["/library.html", "/admin.html"]}})
    assert r.status_code == 200, r.text
    assert r.json()["grants"] == {MARISOL: ["/library.html"]}
    assert r.json()["updated_by"] == "boss@wetreadwell.com"
    assert sp.has(MARISOL, "/library.html")
    assert logged and logged[-1][2] == "special_permissions_changed"
    assert logged[-1][3] == {"grants": {MARISOL: ["/library.html"]}}


def test_put_rejects_an_unknown_top_level_key(monkeypatch):
    c = _as(monkeypatch, "admin", "boss@wetreadwell.com")
    assert c.put("/api/admin/special-permissions", json={"grant": {}}).status_code == 422


def test_me_carries_the_callers_granted_tabs(monkeypatch):
    sp.save({MARISOL: ["/markup.html", "/library.html"]}, "h")
    assert _as(monkeypatch, "user").get("/api/me").json()["grants"] == \
        [h for h in sp.KEYS if h in ("/markup.html", "/library.html")]
    assert _as(monkeypatch, "user", KYLE).get("/api/me").json()["grants"] == []
    assert _as(monkeypatch, "admin", "boss@wetreadwell.com").get("/api/me").json()["grants"] \
        == list(sp.KEYS)


# ── the pages read tab keys ──────────────────────────────────────────────────
@pytest.mark.parametrize("page,tab", [
    ("js/library.js", "/library.html"), ("js/markup.js", "/markup.html"),
    ("js/notifications.js", "/notifications.html"), ("js/portal.js", "/portal.html")])
def test_each_page_checks_its_tab_key_and_no_old_ability_key(page, tab):
    src = (FRONTEND / page).read_text(encoding="utf-8")
    assert 'grants.indexOf("%s")' % tab in src
    for old in sp.LEGACY_KEYS:
        assert 'indexOf("%s")' % old not in src, (page, old)
