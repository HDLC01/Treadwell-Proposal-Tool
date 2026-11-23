"""Who may call each route #807 moves under /api/bd/, over HTTP, role by role: BD's checks unchanged.

One table: every route This Week and its call dialog use, and what each BD role gets on the fixture
seed (bd/ops/fixture_seed.py). Admins and super admins pass every role check. The rows that say
"own" are the salesperson's own-list or own-entry rules: Avery owns batch 201 (tasks 301-303) and
logged interaction 101; Blair is the other salesperson. A refusal is BD's 403 envelope.

    salesperson  Avery (1), Blair (2)
    assistant    Casey (3)        manager  Devon (4)
    admin        Emery (5)        super admin  Frankie (6)
"""
from __future__ import annotations

import pytest

ROLES = ("avery", "blair", "casey", "devon", "emery", "frankie")
UID = {"avery": 1, "blair": 2, "casey": 3, "devon": 4, "emery": 5, "frankie": 6}

# (label, method, path, body, {who: status})  200 = let in, 403 = refused
OK, NO = 200, 403
TABLE = [
    ("week", "GET", "/api/bd/week", None,
     {"avery": OK, "blair": OK, "casey": NO, "devon": OK, "emery": OK, "frankie": OK}),
    ("ten_more", "POST", "/api/bd/week/ten-more", {},
     {"avery": OK, "blair": OK, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}),
    ("done", "POST", "/api/bd/tasks/302/done", {},                 # own list only
     {"avery": OK, "blair": NO, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}),
    ("snooze", "POST", "/api/bd/tasks/302/snooze", {},
     {"avery": OK, "blair": NO, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}),
    ("reopen", "POST", "/api/bd/tasks/303/reopen", {},
     {"avery": OK, "blair": NO, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}),
    ("not_right_person", "POST", "/api/bd/tasks/302/not-right-person", {},   # any list
     {"avery": OK, "blair": OK, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}),
    ("timeline", "GET", "/api/bd/contacts/21/interactions", None,
     {"avery": OK, "blair": OK, "casey": OK, "devon": OK, "emery": OK, "frankie": OK}),
    ("log_call", "POST", "/api/bd/contacts/21/interactions", {"kind": "call", "outcome": "answered"},
     {"avery": OK, "blair": OK, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}),
    ("log_note", "POST", "/api/bd/contacts/21/interactions", {"kind": "note", "summary": "Front desk."},
     {"avery": OK, "blair": OK, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}),
    ("edit_entry", "PATCH", "/api/bd/interactions/101", {"summary": "Edited."},   # own entry only
     {"avery": OK, "blair": NO, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}),
    ("delete_entry", "DELETE", "/api/bd/interactions/101", None,
     {"avery": NO, "blair": NO, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}),
    ("contact", "GET", "/api/bd/contacts/21", None,
     {"avery": OK, "blair": OK, "casey": OK, "devon": OK, "emery": OK, "frankie": OK}),
    ("patch_contact", "PATCH", "/api/bd/contacts/21", {"next_step": "Send the sample board"},
     {"avery": OK, "blair": OK, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}),
    ("patch_cadence", "PATCH", "/api/bd/contacts/21",
     {"cadence_override": "monthly", "cadence_override_until": "2027-01-31"},
     {"avery": OK, "blair": OK, "casey": OK, "devon": OK, "emery": OK, "frankie": OK}),
    ("confirm", "POST", "/api/bd/contacts/21/confirm", {"confirmed": True},
     {"avery": OK, "blair": OK, "casey": OK, "devon": NO, "emery": OK, "frankie": OK}),
    ("weekly_run", "POST", "/api/bd/admin/weekly/run", {"owner": 1},
     {"avery": NO, "blair": NO, "casey": NO, "devon": NO, "emery": OK, "frankie": OK}),
]

REFUSALS = {
    ("week", "casey"): "The weekly list is the salesperson's.",
    ("done", "blair"): "That task is on someone else's list.",
    ("snooze", "blair"): "That task is on someone else's list.",
    ("reopen", "blair"): "That task is on someone else's list.",
    ("log_call", "casey"): "Assistants can add notes only.",
    ("edit_entry", "blair"): "Only the person who logged this can change it.",
    ("edit_entry", "casey"): "Only the person who logged this can change it.",
    ("edit_entry", "devon"): "Only the person who logged this can change it.",
    ("patch_contact", "devon"): "Managers can change only how often to follow up.",
}

CASES = [(label, method, path, body, who, want[who]) for label, method, path, body, want in TABLE for who in ROLES]


@pytest.mark.parametrize("label, method, path, body, who, status", CASES,
                         ids=["%s-%s" % (c[0], c[4]) for c in CASES])
def test_each_route_lets_in_exactly_the_roles_bd_lets_in(bd_seeded, bd_as_user, label, method, path, body,
                                                         who, status):
    kw = {"json": body} if body is not None else {}
    r = bd_as_user(UID[who]).request(method, path, **kw)
    assert r.status_code == status, (label, who, r.status_code, r.text)
    if status == NO:
        assert r.json() == {"ok": False, "error": "forbidden",
                            "message": REFUSALS.get((label, who), "Your role can't do that.")}


def test_the_table_covers_every_route_this_stage_moved():
    from bd import api

    moved = {(m, p) for m, p in (("GET", "/api/bd/week"), ("POST", "/api/bd/week/ten-more"),
                                 ("POST", "/api/bd/tasks/{id}/done"), ("POST", "/api/bd/tasks/{id}/snooze"),
                                 ("POST", "/api/bd/tasks/{id}/reopen"),
                                 ("POST", "/api/bd/tasks/{id}/not-right-person"),
                                 ("GET", "/api/bd/contacts/{id}/interactions"),
                                 ("POST", "/api/bd/contacts/{id}/interactions"),
                                 ("PATCH", "/api/bd/interactions/{id}"), ("DELETE", "/api/bd/interactions/{id}"),
                                 ("GET", "/api/bd/contacts/{id}"), ("PATCH", "/api/bd/contacts/{id}"),
                                 ("POST", "/api/bd/contacts/{id}/confirm"), ("POST", "/api/bd/admin/weekly/run"))}
    served = {(m, r.path) for r in api.bd_routes() for m in r.methods}
    assert moved <= served
    import re
    tabled = {(m, re.sub(r"/[0-9]+(?=/|$)", "/{id}", p)) for _l, m, p, _b, _w in TABLE}
    assert tabled == moved
