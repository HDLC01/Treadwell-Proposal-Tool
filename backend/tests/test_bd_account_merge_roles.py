"""Who may call each route #811 adds under /api/bd/, over HTTP, person by person, on the fixture seed
(bd/ops/fixture_seed.py):

    salesperson  Avery (1), Blair (2)     assistant  Casey (3)     manager  Devon (4)
    admin        Emery (5)                super admin  Frankie (6)
    a staffer signed in to the tool with no BD login, and Gale (7), whose BD login is turned off

The likely-duplicates list, Merge, Undo and Keep separate are the assistant's, the BD admin's and the
super admin's (Q21, Q36); never a salesperson's or the manager's. A refusal is BD's 403 envelope and
changes nothing. Then the page's `can.merge_companies` key agrees with the merge route, person by
person, so the Possible duplicates filter's account pairs show only to someone the server lets in.
"""
from __future__ import annotations

import re

import pytest

ROLES = ("avery", "blair", "casey", "devon", "emery", "frankie")
UID = {"avery": 1, "blair": 2, "casey": 3, "devon": 4, "emery": 5, "frankie": 6}
OK, NO = 200, 403
MERGERS = {"avery": NO, "blair": NO, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}
UNDO = "/api/bd/contacts/accounts/merges/{merge}/undo"

# (label, method, path, body)
TABLE = [
    ("duplicates", "GET", "/api/bd/contacts/accounts/duplicates", None),
    ("merge", "POST", "/api/bd/contacts/accounts/10/merge", {"into": 11, "name_from": 10}),
    ("undo", "POST", UNDO, {}),
    ("keep", "POST", "/api/bd/contacts/accounts/duplicates/keep", {"accounts": [12, 13]}),
]
CASES = [(label, method, path, body, who, MERGERS[who]) for label, method, path, body in TABLE for who in ROLES]


def a_merge(bd_as_user):
    """A merge to undo, made by the admin (Emery): 12 into 13."""
    r = bd_as_user(UID["emery"]).post("/api/bd/contacts/accounts/12/merge", json={"into": 13, "name_from": 13})
    assert r.status_code == 200, r.text
    return r.json()["merge"]["id"]


def _state(db):
    return db.execute(
        "select (select json_agg(c order by c.id) from (select id, name, normalized_name, merged_into, merged_at,"
        "   merged_by from bd.companies) c) as companies,"
        " (select json_agg(c order by c.id) from (select id, company_id, owner_id from bd.contacts) c) as contacts,"
        " (select json_agg(k order by k.account_a) from bd.account_pairs_kept k) as kept,"
        " (select json_agg(e order by e.id) from (select id, kind, data from bd.events) e) as events").fetchone()


@pytest.mark.parametrize("label, method, path, body, who, status", CASES,
                         ids=["%s-%s" % (c[0], c[4]) for c in CASES])
def test_each_route_lets_in_exactly_these_people(bd_seeded, bd_as_user, bd_db, label, method, path, body, who, status):
    if path == UNDO:
        path = UNDO.format(merge=a_merge(bd_as_user))
    before = _state(bd_db)
    r = bd_as_user(UID[who]).request(method, path, **({"json": body} if body is not None else {}))
    assert r.status_code == status, (label, who, r.status_code, r.text)
    if status == NO:
        assert r.json() == {"ok": False, "error": "forbidden", "message": "Your role can't do that."}
        assert _state(bd_db) == before


def test_no_bd_login_and_a_turned_off_login_get_nothing_and_change_nothing(bd_seeded, bd_client, bd_as_user, bd_db):
    from _bd_conftest import bd_token_headers

    merge_id = a_merge(bd_as_user)
    before = _state(bd_db)
    for email, message in (("new.hire@example.com", "You don't have a BD role. Ask a BD admin to add you."),
                           ("gale.ward@example.com", "Your BD login is turned off. Ask a BD admin to turn it back on.")):
        for _label, method, path, body in TABLE:
            url = UNDO.format(merge=merge_id) if path == UNDO else path
            r = bd_client.request(method, url, headers=bd_token_headers(email),
                                  **({"json": body} if body is not None else {}))
            assert (r.status_code, r.json()) == (403, {"ok": False, "error": "forbidden", "message": message}), url
    assert _state(bd_db) == before
    assert bd_db.execute("select count(*) as n from bd.users where email = 'new.hire@example.com'").fetchone()["n"] == 0


def test_the_table_covers_every_route_this_ticket_adds():
    from bd import api

    added = {("GET", "/api/bd/contacts/accounts/duplicates"), ("POST", "/api/bd/contacts/accounts/{id}/merge"),
             ("POST", "/api/bd/contacts/accounts/merges/{id}/undo"), ("POST", "/api/bd/contacts/accounts/duplicates/keep")}
    served = {(m, r.path) for r in api.bd_routes() for m in r.methods if r.endpoint.__module__.endswith("account_merge")}
    assert served == added
    tabled = {(m, re.sub(r"/([0-9]+|\{merge\})(?=/|$)", "/{id}", p)) for _l, m, p, _b in TABLE}
    assert tabled == added


# ── the page's can key agrees with the merge route ──────────────────────────────────────────────
# Expected by hand from Q21 and Q36: the assistant, the BD admin, the super admin.
MERGE_COMPANIES = {"avery": False, "blair": False, "casey": True, "devon": False, "emery": True, "frankie": True}


@pytest.mark.parametrize("who", ROLES)
def test_can_merge_companies_is_true_exactly_when_the_merge_route_lets_the_person_in(bd_seeded, bd_as_user, who):
    client = bd_as_user(UID[who])
    assert client.get("/api/bd/me").json()["can"]["merge_companies"] is MERGE_COMPANIES[who]
    r = client.post("/api/bd/contacts/accounts/10/merge", json={"into": 11, "name_from": 11})
    assert (r.status_code != 403) is MERGE_COMPANIES[who], (who, r.status_code, r.text)
