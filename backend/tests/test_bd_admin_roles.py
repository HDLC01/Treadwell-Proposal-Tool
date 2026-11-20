"""Who may call each route #809 moves under /api/bd/, over HTTP, role by role: BD's checks unchanged.

One table: the People routes, the settings save, the telephony status, the unmatched calls, the
workbook import and its history, and the two unbuilt sections (Potential BD Contacts and Analytics,
503 "not built yet" after the role check), with what each BD role gets on the fixture seed
(bd/ops/fixture_seed.py). Admins and super admins pass every role check. A refusal is BD's 403
envelope and changes nothing.

    salesperson  Avery (1), Blair (2)
    assistant    Casey (3)        manager  Devon (4)
    admin        Emery (5)        super admin  Frankie (6)

Then the People table's two rules from #802:
  * it changes BD logins only, never the proposal tool's profiles, roles, sidebar (nav) policy or
    Special permissions (Q30's other half: BD's Admin page is not the tool's Admin page);
  * a proposal-tool admin gets no BD role from being one, and is added on BD's People table like
    anyone else (Q30). Only a super admin changes another admin (Q29) is in test_bd_admin_api.py.
"""
from __future__ import annotations

import io
import re

import pytest

ROLES = ("avery", "blair", "casey", "devon", "emery", "frankie")
UID = {"avery": 1, "blair": 2, "casey": 3, "devon": 4, "emery": 5, "frankie": 6}

OK, NO, NOT_BUILT = 200, 403, 503
EVERYONE = {who: OK for who in ROLES}
ADMINS = {"avery": NO, "blair": NO, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}
ASSISTANT = {"avery": NO, "blair": NO, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}
IMPORTERS = {"avery": OK, "blair": OK, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}
UPLOAD = object()          # the body is a made-up CSV upload, as the Admin page sends it
CSV = b"Company,Name,Email\nTallgrass Dental,Rae Lindgren,rae.lindgren@tallgrass.example.com\n"

# (label, method, path, body, {who: status})
TABLE = [
    ("people", "GET", "/api/bd/admin/users", None, ADMINS),
    ("add_person", "POST", "/api/bd/admin/users", {"email": "nell.ash@example.com", "role": "salesperson"}, ADMINS),
    ("change_person", "PATCH", "/api/bd/admin/users/1", {"name": "Avery Q."}, ADMINS),
    ("settings", "PUT", "/api/bd/admin/settings", {"bd_cadence": "monthly"}, ADMINS),
    ("telephony", "GET", "/api/bd/admin/telephony", None, ADMINS),
    ("unmatched", "GET", "/api/bd/admin/unmatched-calls", None, ASSISTANT),
    ("attach", "POST", "/api/bd/admin/unmatched-calls/801/attach", {"contact_id": 32, "outcome": "answered"},
     ASSISTANT),
    ("dismiss", "POST", "/api/bd/admin/unmatched-calls/801/dismiss", {}, ASSISTANT),
    ("import", "POST", "/api/bd/admin/import", UPLOAD, IMPORTERS),
    ("imports", "GET", "/api/bd/admin/imports", None, IMPORTERS),
    ("candidates", "GET", "/api/bd/review/candidates", None, {who: NOT_BUILT for who in ROLES}),
    ("add_candidate", "POST", "/api/bd/review/candidates/601/add", {},
     {"avery": NOT_BUILT, "blair": NOT_BUILT, "casey": NOT_BUILT, "devon": NO, "emery": NOT_BUILT,
      "frankie": NOT_BUILT}),
    ("ignore_candidate", "POST", "/api/bd/review/candidates/601/ignore", {},
     {"avery": NOT_BUILT, "blair": NOT_BUILT, "casey": NOT_BUILT, "devon": NO, "emery": NOT_BUILT,
      "frankie": NOT_BUILT}),
    ("analytics", "GET", "/api/bd/analytics", None,
     {"avery": NO, "blair": NO, "casey": NO, "devon": NOT_BUILT, "emery": NOT_BUILT, "frankie": NOT_BUILT}),
    ("analytics_csv", "GET", "/api/bd/analytics/export.csv", None,
     {"avery": NO, "blair": NO, "casey": NO, "devon": NOT_BUILT, "emery": NOT_BUILT, "frankie": NOT_BUILT}),
]

CASES = [(label, method, path, body, who, want[who]) for label, method, path, body, want in TABLE for who in ROLES]


@pytest.fixture(autouse=True)
def sign_in_domain(monkeypatch):
    import supabase_client

    monkeypatch.setattr(supabase_client, "ALLOWED_DOMAIN", "example.com")


def call(client, method, path, body):
    if body is UPLOAD:
        return client.request(method, path, files={"file": ("people.csv", io.BytesIO(CSV), "text/csv")},
                              data={"dry_run": "true"})
    return client.request(method, path, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize("label, method, path, body, who, status", CASES,
                         ids=["%s-%s" % (c[0], c[4]) for c in CASES])
def test_each_route_lets_in_exactly_the_roles_bd_lets_in(bd_seeded, bd_as_user, label, method, path, body,
                                                         who, status):
    r = call(bd_as_user(UID[who]), method, path, body)
    assert r.status_code == status, (label, who, r.status_code, r.text)
    if status == NO:
        assert r.json() == {"ok": False, "error": "forbidden", "message": "Your role can't do that."}
    if status == NOT_BUILT:
        assert r.json()["error"] == "unavailable" and "not built yet" in r.json()["message"]


def _state(db):
    return db.execute(
        "select (select json_agg(u order by u.id) from (select id, email, name, role, active from bd.users) u) as users,"
        " (select count(*) from bd.settings) as settings, (select count(*) from bd.events) as events,"
        " (select count(*) from bd.imports) as imports, (select count(*) from bd.contacts) as contacts,"
        " (select count(*) from bd.interactions) as interactions,"
        " (select status from bd.unmatched_calls where id = 801) as call").fetchone()


@pytest.mark.parametrize("who", ["avery", "blair", "casey", "devon"])
def test_a_refused_write_changes_nothing(bd_seeded, bd_as_user, bd_db, who):
    before = _state(bd_db)
    client = bd_as_user(UID[who])
    for label, method, path, body, want in TABLE:
        if method != "GET" and want[who] == NO:
            assert call(client, method, path, body).status_code == NO, label
    after = _state(bd_db)
    # The refused caller's own sign-in may refresh their last_seen_at; nothing else moves.
    assert after == before


def test_the_table_covers_every_route_this_ticket_moved():
    from bd import api

    moved = {("GET", "/api/bd/admin/users"), ("POST", "/api/bd/admin/users"), ("PATCH", "/api/bd/admin/users/{id}"),
             ("PUT", "/api/bd/admin/settings"), ("GET", "/api/bd/admin/telephony"),
             ("GET", "/api/bd/admin/unmatched-calls"), ("POST", "/api/bd/admin/unmatched-calls/{id}/attach"),
             ("POST", "/api/bd/admin/unmatched-calls/{id}/dismiss"), ("POST", "/api/bd/admin/import"),
             ("GET", "/api/bd/admin/imports")}
    unbuilt = {("GET", "/api/bd/review/candidates"), ("POST", "/api/bd/review/candidates/{id}/add"),
               ("POST", "/api/bd/review/candidates/{id}/ignore"), ("GET", "/api/bd/analytics"),
               ("GET", "/api/bd/analytics/export.csv")}
    served = {(m, r.path) for r in api.bd_routes() for m in r.methods}
    assert moved | unbuilt <= served
    tabled = {(m, re.sub(r"/[0-9]+(?=/|$)", "/{id}", p.split("?")[0])) for _l, m, p, _b, _w in TABLE}
    assert tabled == moved | unbuilt


def test_none_of_the_moved_routes_is_a_placeholder_any_more():
    from bd.routers import pending

    assert not [p for _m, p in pending.PENDING if p.startswith("/api/bd/admin/")]


# ── the Admin page's can keys agree with the routes they stand for ─────────────────────────────
# The Admin page shows a section only when /api/bd/me's can says so (it never reads a role name).
# Expected by hand from BD's role checks:
#   admin       People, settings, telephony           admins
#   admin_area  the unmatched calls (the Admin page)  assistant, admins
#   import      the import and its history            salesperson, assistant, admins
#   analytics   the Analytics section                 manager, admins
#   manage_admins  adds an admin or changes an admin's   the super admin alone (Q29): the People table
#                  login                                 offers the admin roles, and an admin's row, only
#                                                        to them. Checked by re-saving the super admin's
#                                                        own role, which changes nothing: a plain admin
#                                                        is refused it (an admin's login), anyone else
#                                                        is refused the People routes.
KEY_ROUTES = {
    "admin": [("GET", "/api/bd/admin/users"), ("GET", "/api/bd/admin/telephony")],
    "admin_area": [("GET", "/api/bd/admin/unmatched-calls")],
    "import": [("GET", "/api/bd/admin/imports")],
    "analytics": [("GET", "/api/bd/analytics")],
    "manage_admins": [("PATCH", "/api/bd/admin/users/6", {"role": "super_admin"})],
}
KEY_TABLE = {
    "admin": {"avery": False, "blair": False, "casey": False, "devon": False, "emery": True, "frankie": True},
    "admin_area": {"avery": False, "blair": False, "casey": True, "devon": False, "emery": True, "frankie": True},
    "import": {"avery": True, "blair": True, "casey": True, "devon": False, "emery": True, "frankie": True},
    "analytics": {"avery": False, "blair": False, "casey": False, "devon": True, "emery": True, "frankie": True},
    "manage_admins": {"avery": False, "blair": False, "casey": False, "devon": False, "emery": False,
                      "frankie": True},
}
KEY_CASES = [(key, who) for key in KEY_TABLE for who in ROLES]


@pytest.mark.parametrize("key, who", KEY_CASES, ids=["%s-%s" % c for c in KEY_CASES])
def test_each_can_key_is_true_exactly_when_its_route_lets_the_person_in(bd_seeded, bd_as_user, key, who):
    client = bd_as_user(UID[who])
    assert client.get("/api/bd/me").json()["can"][key] is KEY_TABLE[key][who]
    for method, path, *body in KEY_ROUTES[key]:
        r = client.request(method, path, json=body[0] if body else None)
        assert (r.status_code != 403) is KEY_TABLE[key][who], (key, who, path, r.status_code, r.text)


# ── the People table changes BD logins only (#802, Q30) ────────────────────────────────────────
TOOL_WRITERS = ("ensure_profile", "set_role", "set_status", "set_estimator", "ban_user", "unban_user", "delete_user")


@pytest.fixture
def tool_people(bd_app, monkeypatch):
    """The proposal tool's own people, as files and a profile store the test can compare byte for
    byte: the sidebar policy (BD CRM hidden from the plain user role, Q10), a Special permissions
    grant, and every profile the gate reads. Every profiles writer is replaced by a recorder."""
    import json

    import nav_access
    import profiles
    import special_permissions

    nav_access.save({"user": ["/bd/"]}, by="frankie.oduya@example.com")
    special_permissions.save({"avery.quill@example.com": ["/bd/"]}, by="frankie.oduya@example.com")
    bd_app.tool_roles.update({"frankie.oduya@example.com": "super_admin", "emery.stoll@example.com": "admin",
                              "tia.admin@example.com": "admin"})
    writes = []
    for name in TOOL_WRITERS:
        monkeypatch.setattr(profiles, name, lambda *a, _n=name, **k: writes.append(_n))

    def snapshot():
        return (nav_access._FILE.read_bytes(), special_permissions._FILE.read_bytes(),
                json.dumps(bd_app.tool_roles, sort_keys=True).encode())

    return {"snapshot": snapshot, "writes": writes}


def test_the_people_table_never_touches_the_tools_people(bd_seeded, bd_as_user, bd_client, tool_people):
    before = tool_people["snapshot"]()
    frankie = bd_as_user(6)
    assert frankie.get("/api/bd/admin/users").status_code == 200
    # Add a plain person, a proposal-tool admin and a BD admin; change roles, sign-ins and names.
    for email, role in (("nell.ash@example.com", "salesperson"), ("tia.admin@example.com", "assistant"),
                        ("ola.vane@example.com", "admin")):
        assert frankie.post("/api/bd/admin/users", json={"email": email, "role": role}).status_code == 200
    for uid, change in ((1, {"role": "manager"}), (4, {"active": False}), (5, {"role": "super_admin"}),
                        (8, {"name": "Nell A."}), (9, {"role": "manager", "active": False})):
        r = frankie.patch("/api/bd/admin/users/%d" % uid, json=change)
        assert r.status_code == 200, r.text
    assert frankie.put("/api/bd/admin/settings", json={"bd_cadence": "weekly"}).status_code == 200
    assert tool_people["snapshot"]() == before
    assert tool_people["writes"] == []


def test_a_tool_admin_is_no_bd_admin_and_is_added_like_anyone_else(bd_seeded, bd_as_user, bd_client, bd_db,
                                                                    tool_people):
    tia = {"Authorization": "Bearer test:tia.admin@example.com"}
    # A proposal-tool admin with no BD login: no BD role, no People table.
    for path in ("/api/bd/me", "/api/bd/admin/users"):
        r = bd_client.get(path, headers=tia)
        assert (r.status_code, r.json()["message"]) == (403, "You don't have a BD role. Ask a BD admin to add you.")
    # A plain BD admin adds them like anyone else: the role they are given, never admin from the tool.
    r = bd_as_user(5).post("/api/bd/admin/users", json={"email": "tia.admin@example.com", "role": "salesperson"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "salesperson"
    assert bd_client.get("/api/bd/me", headers=tia).json()["user"]["role"] == "salesperson"
    r = bd_client.get("/api/bd/admin/users", headers=tia)
    assert (r.status_code, r.json()["message"]) == (403, "Your role can't do that.")
    assert bd_client.get("/api/bd/me", headers=tia).json()["can"]["admin"] is False
    # Making them a BD admin is the super admin's, as for anyone (Q29).
    r = bd_as_user(5).patch("/api/bd/admin/users/8", json={"role": "admin"})
    assert (r.status_code, r.json()["message"]) == (403, "Only a super admin can change an admin.")
    assert bd_as_user(6).patch("/api/bd/admin/users/8", json={"role": "admin"}).status_code == 200
    assert bd_client.get("/api/bd/admin/users", headers=tia).status_code == 200


def test_the_tools_super_admin_role_gives_no_bd_super_admin(bd_seeded, bd_app, bd_as_user, tool_people):
    """Emery is the tool's admin AND a BD admin: still only a BD admin, so adding an admin is refused.
    Avery, a BD salesperson, made the tool's super admin: still no People table."""
    r = bd_as_user(5).post("/api/bd/admin/users", json={"email": "ola.vane@example.com", "role": "admin"})
    assert (r.status_code, r.json()["message"]) == (403, "Only a super admin can add an admin.")
    import main

    bd_app.tool_roles["avery.quill@example.com"] = "super_admin"
    main._profile_cache_clear()
    r = bd_as_user(1).get("/api/bd/admin/users")
    assert (r.status_code, r.json()["message"]) == (403, "Your role can't do that.")
