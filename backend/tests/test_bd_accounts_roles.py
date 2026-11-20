"""Who may call each route #810 adds under /api/bd/, over HTTP, person by person, on the fixture seed
(bd/ops/fixture_seed.py):

    salesperson  Avery (1), Blair (2)     assistant  Casey (3)     manager  Devon (4)
    admin        Emery (5)                super admin  Frankie (6)

The account list, both tabs and the search are open to every BD role. Moving a company (and undoing
your own move) is the salesperson's, the manager's and the admins'; never the assistant's (Q5). A
refusal is BD's 403 envelope and changes nothing. Then the page's `can.move_company` key agrees with
the move route, person by person, so the "..." menu shows its item only to someone the server lets in.
Nobody without a BD login, or with a turned-off one, gets past the door (tests/test_bd_authz_matrix.py
checks that for every route).
"""
from __future__ import annotations

import re

import pytest

ROLES = ("avery", "blair", "casey", "devon", "emery", "frankie")
UID = {"avery": 1, "blair": 2, "casey": 3, "devon": 4, "emery": 5, "frankie": 6}
OK, NO = 200, 403
EVERYONE = {who: OK for who in ROLES}
MOVERS = {"avery": OK, "blair": OK, "casey": NO, "devon": OK, "emery": OK, "frankie": OK}
UNDO = "/api/bd/contacts/accounts/moves/{move}/undo"

# (label, method, path, body, {who: status})
TABLE = [
    ("bd_tab", "GET", "/api/bd/contacts/accounts", None, EVERYONE),
    ("maintenance_tab", "GET", "/api/bd/contacts/accounts?category=maintenance", None, EVERYONE),
    ("search", "GET", "/api/bd/contacts/search?q=bluestem", None, EVERYONE),
    ("to_maintenance", "POST", "/api/bd/contacts/accounts/16/move", {"to": "maintenance"}, MOVERS),
    ("to_bd", "POST", "/api/bd/contacts/accounts/17/move", {"to": "bd"}, MOVERS),
    ("undo", "POST", UNDO, {}, MOVERS),
]
CASES = [(label, method, path, body, who, want[who]) for label, method, path, body, want in TABLE for who in ROLES]


def own_move(bd_as_user, who):
    """A move to undo: the caller's own when they may move, else the admin's (Emery's)."""
    mover = UID[who] if MOVERS[who] == OK else UID["emery"]
    r = bd_as_user(mover).post("/api/bd/contacts/accounts/17/move", json={"to": "bd"})
    assert r.status_code == 200, r.text
    return r.json()["move"]["id"]


@pytest.mark.parametrize("label, method, path, body, who, status", CASES,
                         ids=["%s-%s" % (c[0], c[4]) for c in CASES])
def test_each_route_lets_in_exactly_these_people(bd_seeded, bd_as_user, label, method, path, body, who, status):
    if path == UNDO:
        path = UNDO.format(move=own_move(bd_as_user, who))
    r = bd_as_user(UID[who]).request(method, path, **({"json": body} if body is not None else {}))
    assert r.status_code == status, (label, who, r.status_code, r.text)
    if status == NO:
        assert r.json() == {"ok": False, "error": "forbidden", "message": "Your role can't do that."}


def _state(db):
    return db.execute(
        "select (select json_agg(c order by c.id) from (select id, category, frequency_per_year, company_id"
        "   from bd.contacts) c) as contacts,"
        " (select json_agg(t order by t.id) from (select id, batch_id, status, snoozed_until from bd.tasks) t) as tasks,"
        " (select count(*) from bd.task_batches) as batches,"
        " (select json_agg(e order by e.id) from (select id, kind, data from bd.events) e) as events").fetchone()


def test_the_assistant_is_refused_every_move_and_undo_and_nothing_changes(bd_seeded, bd_as_user, bd_db):
    move_id = own_move(bd_as_user, "casey")              # Emery's move, for Casey to try to undo
    before = _state(bd_db)
    casey = bd_as_user(UID["casey"])
    for label, method, path, body, want in TABLE:
        if method == "POST":
            url = UNDO.format(move=move_id) if path == UNDO else path
            assert casey.request(method, url, json=body).status_code == NO, label
    assert _state(bd_db) == before


def test_no_bd_login_and_a_turned_off_login_move_nothing(bd_seeded, bd_client, bd_db):
    from _bd_conftest import bd_token_headers

    before = _state(bd_db)
    for email, message in (("new.hire@example.com", "You don't have a BD role. Ask a BD admin to add you."),
                           ("gale.ward@example.com", "Your BD login is turned off. Ask a BD admin to turn it back on.")):
        r = bd_client.post("/api/bd/contacts/accounts/16/move", json={"to": "maintenance"},
                           headers=bd_token_headers(email))
        assert (r.status_code, r.json()) == (403, {"ok": False, "error": "forbidden", "message": message})
    assert _state(bd_db) == before


def test_the_table_covers_every_route_this_ticket_adds():
    from bd import api

    added = {("GET", "/api/bd/contacts/accounts"), ("GET", "/api/bd/contacts/search"),
             ("POST", "/api/bd/contacts/accounts/{id}/move"), ("POST", "/api/bd/contacts/accounts/moves/{id}/undo")}
    served = {(m, r.path) for r in api.bd_routes() for m in r.methods}
    assert added <= served
    tabled = {(m, re.sub(r"/([0-9]+|\{move\})(?=/|$)", "/{id}", p.split("?")[0])) for _l, m, p, _b, _w in TABLE}
    assert tabled == added


# ── the page's can key agrees with the move route ──────────────────────────────────────────────
# Expected by hand from Q5: salesperson, manager, admin, super admin; not the assistant.
MOVE_COMPANY = {"avery": True, "blair": True, "casey": False, "devon": True, "emery": True, "frankie": True}


@pytest.mark.parametrize("who", ROLES)
def test_can_move_company_is_true_exactly_when_the_move_route_lets_the_person_in(bd_seeded, bd_as_user, who):
    client = bd_as_user(UID[who])
    assert client.get("/api/bd/me").json()["can"]["move_company"] is MOVE_COMPANY[who]
    r = client.post("/api/bd/contacts/accounts/16/move", json={"to": "maintenance"})
    assert (r.status_code != 403) is MOVE_COMPANY[who], (who, r.status_code, r.text)
