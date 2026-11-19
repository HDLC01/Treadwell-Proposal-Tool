"""Who may call each route #808 moves under /api/bd/, over HTTP, role by role: BD's checks unchanged.

One table: the routes the contact page and Add contact add (the contacts list, the possible-duplicate
person check, create and archive; the companies type-ahead, one company, create and patch), and what
each BD role gets on the fixture seed (bd/ops/fixture_seed.py). Admins and super admins pass every
role check. None of these routes has an own-list rule, so the other salesperson gets what the first
gets. A refusal is BD's 403 envelope. The routes the contact page shares with This Week (one contact,
its timeline, logging, editing and deleting an entry, confirm) are in test_bd_this_week_roles.py.

    salesperson  Avery (1), Blair (2)
    assistant    Casey (3)        manager  Devon (4)
    admin        Emery (5)        super admin  Frankie (6)
"""
from __future__ import annotations

import re

import pytest

ROLES = ("avery", "blair", "casey", "devon", "emery", "frankie")
UID = {"avery": 1, "blair": 2, "casey": 3, "devon": 4, "emery": 5, "frankie": 6}

# (label, method, path, body, {who: status})  200 / 201 = let in, 403 = refused
OK, NEW, NO = 200, 201, 403
EVERYONE = {who: OK for who in ROLES}
TABLE = [
    ("contacts", "GET", "/api/bd/contacts", None, EVERYONE),
    ("duplicates", "GET", "/api/bd/contacts/duplicates?company=Bluestem%20Logistics", None, EVERYONE),
    ("add_contact", "POST", "/api/bd/contacts", {"company": {"name": "Tallgrass Dental"}, "name": "Rae Lindgren"},
     {"avery": NEW, "blair": NEW, "casey": NEW, "devon": NO, "emery": NEW, "frankie": NEW}),
    ("archive", "POST", "/api/bd/contacts/32/archive", {"archived": True},
     {"avery": OK, "blair": OK, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}),
    ("companies", "GET", "/api/bd/companies?q=cedar", None, EVERYONE),
    ("company", "GET", "/api/bd/companies/16", None, EVERYONE),
    ("add_company", "POST", "/api/bd/companies", {"name": "Tallgrass Dental"},
     {"avery": NEW, "blair": NEW, "casey": NEW, "devon": NO, "emery": NEW, "frankie": NEW}),
    ("patch_company", "PATCH", "/api/bd/companies/16", {"city": "Lenexa"},
     {"avery": OK, "blair": OK, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}),
]

CASES = [(label, method, path, body, who, want[who]) for label, method, path, body, want in TABLE for who in ROLES]


@pytest.mark.parametrize("label, method, path, body, who, status", CASES,
                         ids=["%s-%s" % (c[0], c[4]) for c in CASES])
def test_each_route_lets_in_exactly_the_roles_bd_lets_in(bd_seeded, bd_as_user, label, method, path, body,
                                                         who, status):
    kw = {"json": body} if body is not None else {}
    r = bd_as_user(UID[who]).request(method, path, **kw)
    assert r.status_code == status, (label, who, r.status_code, r.text)
    if status == NO:
        assert r.json() == {"ok": False, "error": "forbidden", "message": "Your role can't do that."}


def test_a_refused_write_changes_nothing(bd_seeded, bd_as_user, bd_db):
    devon = bd_as_user(UID["devon"])
    devon.post("/api/bd/contacts", json={"company": {"name": "Tallgrass Dental"}, "name": "Rae Lindgren"})
    devon.post("/api/bd/contacts/32/archive", json={"archived": True})
    devon.post("/api/bd/companies", json={"name": "Tallgrass Dental"})
    devon.patch("/api/bd/companies/16", json={"city": "Olathe"})
    assert bd_db.execute("select count(*) as n from bd.contacts").fetchone()["n"] == 13
    assert bd_db.execute("select count(*) as n from bd.companies").fetchone()["n"] == 9
    assert bd_db.execute("select archived_at from bd.contacts where id = 32").fetchone()["archived_at"] is None
    assert bd_db.execute("select city from bd.companies where id = 16").fetchone()["city"] == "Lenexa"
    assert bd_db.execute("select count(*) as n from bd.events").fetchone()["n"] == 0


def test_an_assistant_adds_a_contact_and_a_note_but_cannot_log_a_call(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(UID["casey"])
    r = casey.post("/api/bd/contacts", json={"company": {"id": 16}, "name": "Rae Lindgren",
                                             "email": "rae.lindgren@bluestem.example.com"})
    assert r.status_code == 201, r.text
    cid = r.json()["contact"]["id"]
    assert cid == 34
    r = casey.post("/api/bd/contacts/%d/interactions" % cid, json={"kind": "note", "summary": "Front desk gave her name."})
    assert r.status_code == 200, r.text
    assert (r.json()["interaction"]["kind"], r.json()["interaction"]["summary"]) == ("note", "Front desk gave her name.")
    for kind, outcome in (("call", "answered"), ("call", "no_answer"), ("voicemail", None), ("meeting", None),
                          ("email", None)):
        body = {"kind": kind} if outcome is None else {"kind": kind, "outcome": outcome}
        r = casey.post("/api/bd/contacts/%d/interactions" % cid, json=body)
        assert r.status_code == 403 and r.json() == {"ok": False, "error": "forbidden",
                                                     "message": "Assistants can add notes only."}, kind
    kinds = [row["kind"] for row in bd_db.execute("select kind from bd.interactions where contact_id = %s", (cid,))]
    assert kinds == ["note"]


def test_the_table_covers_every_route_this_stage_moved():
    from bd import api

    moved = {("GET", "/api/bd/contacts"), ("GET", "/api/bd/contacts/duplicates"), ("POST", "/api/bd/contacts"),
             ("POST", "/api/bd/contacts/{id}/archive"), ("GET", "/api/bd/companies"),
             ("GET", "/api/bd/companies/{id}"), ("POST", "/api/bd/companies"), ("PATCH", "/api/bd/companies/{id}")}
    served = {(m, r.path) for r in api.bd_routes() for m in r.methods}
    assert moved <= served
    tabled = {(m, re.sub(r"/[0-9]+(?=/|$)", "/{id}", p.split("?")[0])) for _l, m, p, _b, _w in TABLE}
    assert tabled == moved
