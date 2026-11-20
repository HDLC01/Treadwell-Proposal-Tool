"""Making a company a maintenance account, moving it back to BD, and Undo (#810, added 2026-11-20).

    POST /api/bd/contacts/accounts/{id}/move          {"to": "maintenance" | "bd"}
    POST /api/bd/contacts/accounts/moves/{id}/undo    the move's id, from the move's answer

Worked by hand on the fixture seed (bd/ops/fixture_seed.py), today Wed 2026-11-04, this week from
Mon Nov 2. Avery's Friday list (batch 201) holds Hal's pinned maintenance follow-up 301, Dana's open
follow-up 302 and Priya's done 303; Blair's (202) Rory's open 304 and Sam's skipped 305.

THE MAIN CASE, built by `tallgrass()`: a made-up company, Tallgrass Millwork, with five people:
    p1  Avery's, an open BD call on her list, last follow-up Apr 18 (200 days ago)   due
    p2  Avery's, a DONE BD call on her list, an email Oct 5 (30 days ago)             not due
    p3  Blair's, an open BD call on his list, never followed up                       due
    p4  Avery's, not on any list, an answered call Jun 7 (150 days ago)               due
    p5  Avery's, not on any list, a voicemail Aug 1 (95 days ago)                      not due
plus six made-up fillers at Juniper Hollow Dental, each with an open BD call on Avery's list, so her
Friday list holds exactly 10 BD calls (302, 303, p1, p2 and the six), 2 of them done.
A maintenance follow-up comes due 120 days after the last one, on day 120 itself (BD's rule).
Everything is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import pytest

AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE = 1, 2, 3, 4, 5, 6
MOVE = "/api/bd/contacts/accounts/%s/move"
UNDO = "/api/bd/contacts/accounts/moves/%s/undo"
AVERYS_LIST, BLAIRS_LIST = 201, 202
NEXT_MONDAY = "2026-11-09"


# ── made-up data ────────────────────────────────────────────────────────────────────────────────
def company(db, name):
    from bd.normalize import normalize_company

    return db.execute("insert into bd.companies (name, normalized_name, city) values (%s, %s, 'Lenexa')"
                      " returning id", (name, normalize_company(name))).fetchone()["id"]


def person(db, company_id, name, owner, category="bd", phone=None, email=None):
    return db.execute(
        "insert into bd.contacts (company_id, name, category, owner_id, frequency_per_year, phone, email)"
        " values (%s, %s, %s, %s, 4, %s, %s) returning id",
        (company_id, name, category, owner, phone, email)).fetchone()["id"]


def logged(db, contact_id, day, kind="call", outcome="answered", user=AVERY):
    db.execute("insert into bd.interactions (contact_id, user_id, kind, outcome, occurred_at)"
               " values (%s, %s, %s, %s, %s)", (contact_id, user, kind, outcome, day + " 15:00:00+00:00"))


def task(db, batch, contact_id, kind="followup", status="open"):
    return db.execute(
        "insert into bd.tasks (batch_id, contact_id, kind, reason, reasons, score, status, done_at)"
        " values (%s, %s, %s, 'Made up.', '{Made up}', 50, %s,"
        " case when %s = 'done' then bd_now() end) returning id",
        (batch, contact_id, kind, status, status)).fetchone()["id"]


def tallgrass(db):
    t = {"company": company(db, "Tallgrass Millwork")}
    t["p1"] = person(db, t["company"], "Arlo Penn", AVERY, phone="913-555-0141", email="arlo@tallgrass.example.com")
    t["p2"] = person(db, t["company"], "Bea Strand", AVERY)
    t["p3"] = person(db, t["company"], "Cole Imrie", BLAIR)
    t["p4"] = person(db, t["company"], "Dell Okafor", AVERY)
    t["p5"] = person(db, t["company"], "Eve Lantz", AVERY)
    logged(db, t["p1"], "2026-04-18")
    logged(db, t["p2"], "2026-10-05", kind="email", outcome=None)
    logged(db, t["p4"], "2026-06-07")
    logged(db, t["p5"], "2026-08-01", kind="voicemail", outcome="voicemail")
    t["t1"] = task(db, AVERYS_LIST, t["p1"])
    t["t2"] = task(db, AVERYS_LIST, t["p2"], kind="new", status="done")
    t["t3"] = task(db, BLAIRS_LIST, t["p3"], kind="new")
    juniper = company(db, "Juniper Hollow Dental")
    t["fillers"] = [task(db, AVERYS_LIST, person(db, juniper, "Filler %d Quint" % n, AVERY), kind="new")
                    for n in range(6)]
    return t


def state(db):
    """Every row a move may touch, every column, in id order."""
    return {table: db.execute("select * from bd.%s order by id" % table).fetchall()
            for table in ("contacts", "tasks", "task_batches", "companies")}


def bd_calls(db, owner, week="2026-11-02"):
    return db.execute(
        "select t.id, t.status from bd.tasks t join bd.task_batches b on b.id = t.batch_id"
        " where b.owner_id = %s and b.week_start = %s and t.kind <> 'maintenance' order by t.id",
        (owner, week)).fetchall()


def events(db):
    return db.execute("select id, kind, actor_id, contact_id, detail, data from bd.events order by id").fetchall()


def move(client, company_id, to, status=200):
    r = client.post(MOVE % company_id, json={"to": to})
    assert r.status_code == status, r.text
    return r.json()


# ── to maintenance ──────────────────────────────────────────────────────────────────────────────
def test_making_a_company_maintenance_moves_every_person_and_nothing_else(bd_seeded, bd_as_user, bd_db):
    t = tallgrass(bd_db)
    before = state(bd_db)
    body = move(bd_as_user(AVERY), t["company"], "maintenance")
    m = body["move"]
    assert set(m) == {"id", "company", "to", "people", "calls_off", "pinned", "undo_until"}
    assert (m["company"], m["to"], m["people"], m["calls_off"], m["pinned"]) == (
        {"id": t["company"], "name": "Tallgrass Millwork"}, "maintenance", 5, 2, 3)
    after = state(bd_db)
    people = [t[k] for k in ("p1", "p2", "p3", "p4", "p5")]
    moved = {r["id"]: (r["category"], r["frequency_per_year"]) for r in after["contacts"] if r["id"] in people}
    assert moved == {pid: ("maintenance", 3) for pid in people}          # 3: maintenance's default
    assert [r for r in after["contacts"] if r["id"] not in people] == \
        [r for r in before["contacts"] if r["id"] not in people]
    assert after["companies"] == before["companies"]


def test_the_open_bd_calls_come_off_and_the_list_is_never_refilled(bd_seeded, bd_as_user, bd_db):
    t = tallgrass(bd_db)
    week_before = bd_as_user(AVERY).get("/api/bd/week").json()["week"]
    assert (week_before["done_count"], week_before["total"], week_before["due_count"]) == (2, 10, 1)
    avery_calls, blair_calls = bd_calls(bd_db, AVERY), bd_calls(bd_db, BLAIR)
    move(bd_as_user(AVERY), t["company"], "maintenance")
    status = {r["id"]: r["status"] for r in bd_calls(bd_db, AVERY)}
    # The same 10 BD calls, none added: p1's open call is off ("taken off", as Not this week is),
    # p2's logged call still counts, everyone else's is as it was.
    assert sorted(status) == [r["id"] for r in avery_calls] and len(status) == 10
    assert status[t["t1"]] == "snoozed" and status[t["t2"]] == "done" and status[302] == "open" \
        and status[303] == "done" and all(status[f] == "open" for f in t["fillers"])
    assert {r["id"]: r["status"] for r in bd_calls(bd_db, BLAIR)} == {304: "open", 305: "snoozed",
                                                                       t["t3"]: "snoozed"}
    assert len(blair_calls) == 3
    snoozed_until = bd_db.execute("select snoozed_until::text as d from bd.tasks where id = %s",
                                  (t["t1"],)).fetchone()["d"]
    assert snoozed_until == NEXT_MONDAY
    week = bd_as_user(AVERY).get("/api/bd/week").json()["week"]
    assert (week["done_count"], week["total"]) == (2, 10)        # logged calls still count; no refill


@pytest.mark.parametrize("p2_status", ["open", "done"])
def test_a_full_list_of_ten_never_grows(bd_seeded, bd_as_user, bd_db, p2_status):
    """A list of 10 BD calls, all open or two done: the move only ever takes calls off."""
    t = tallgrass(bd_db)
    if p2_status == "open":
        bd_db.execute("update bd.tasks set status = 'open', done_at = null where id in (%s, 303)", (t["t2"],))
    done_before = sum(1 for r in bd_calls(bd_db, AVERY) if r["status"] == "done")
    move(bd_as_user(DEVON), t["company"], "maintenance")
    calls = bd_calls(bd_db, AVERY)
    assert len(calls) == 10
    assert sum(1 for r in calls if r["status"] == "done") == done_before
    assert sum(1 for r in calls if r["status"] == "open") == 10 - done_before - (2 if p2_status == "open" else 1)
    assert bd_db.execute("select count(*) as n from bd.tasks t join bd.task_batches b on b.id = t.batch_id"
                         " where b.owner_id = 1 and t.kind <> 'maintenance'").fetchone()["n"] == 10


def test_a_due_person_gets_the_pinned_follow_up_at_once(bd_seeded, bd_as_user, bd_db):
    t = tallgrass(bd_db)
    batches_before = [r["id"] for r in bd_db.execute("select id from bd.task_batches order by id").fetchall()]
    move(bd_as_user(AVERY), t["company"], "maintenance")
    pins = bd_db.execute(
        "select t.contact_id, t.batch_id, t.status, t.reasons, b.owner_id, b.kind, b.week_start::text as ws"
        " from bd.tasks t join bd.task_batches b on b.id = t.batch_id where t.kind = 'maintenance'"
        " and t.contact_id = any(%s) order by t.id",
        ([t[k] for k in ("p1", "p2", "p3", "p4", "p5")],)).fetchall()
    by_person = {p["contact_id"]: p for p in pins}
    # p1 (200 days), p3 (never followed up) and p4 (150 days) are due; p2 (30) and p5 (95) are not.
    assert sorted(by_person) == sorted([t["p1"], t["p3"], t["p4"]])
    assert all(p["status"] == "open" and p["ws"] == "2026-11-02" for p in pins)
    # p4 had no task on Avery's Friday list, so the pin goes there; p1's call that came off is on
    # it, and p3's on Blair's, so theirs go on a small list of their own for this week.
    assert by_person[t["p4"]]["batch_id"] == AVERYS_LIST
    new_batches = bd_db.execute("select id, owner_id, kind, week_start::text as ws from bd.task_batches"
                                " where id <> all(%s) order by id", (batches_before,)).fetchall()
    assert [(b["owner_id"], b["kind"], b["ws"]) for b in new_batches] == [(AVERY, "ten_more", "2026-11-02"),
                                                                          (BLAIR, "ten_more", "2026-11-02")]
    assert by_person[t["p1"]]["batch_id"] == new_batches[0]["id"]
    assert by_person[t["p3"]]["batch_id"] == new_batches[1]["id"]
    assert by_person[t["p1"]]["reasons"][0] == "Follow-up was due Sun, Aug 16"         # Apr 18 + 120
    assert by_person[t["p3"]]["reasons"][0] == "No follow-up logged yet"
    week = bd_as_user(AVERY).get("/api/bd/week").json()["week"]
    assert week["due_count"] == 3 and (week["done_count"], week["total"]) == (2, 10)   # Hal's 301, p1, p4
    blair = bd_as_user(BLAIR).get("/api/bd/week").json()["week"]
    assert blair["due_count"] == 1
    # A pinned follow-up cannot be taken off by hand while the person is due.
    r = bd_as_user(AVERY).post("/api/bd/tasks/%d/snooze" % bd_db.execute(
        "select id from bd.tasks where contact_id = %s and kind = 'maintenance'", (t["p4"],)).fetchone()["id"], json={})
    assert r.status_code == 409


@pytest.mark.parametrize("last,due", [("2026-07-07", True), ("2026-07-08", False)])
def test_day_120_is_due_and_day_119_is_not(bd_seeded, bd_as_user, bd_db, last, due):
    co = company(bd_db, "Prairie Lark Bakery")
    pid = person(bd_db, co, "Gus Hemmer", AVERY)
    logged(bd_db, pid, last)
    move(bd_as_user(AVERY), co, "maintenance")
    pinned = bd_db.execute("select count(*) as n from bd.tasks where contact_id = %s and kind = 'maintenance'",
                           (pid,)).fetchone()["n"]
    assert pinned == (1 if due else 0)


def test_after_the_friday_run_the_pin_and_the_calls_are_on_next_weeks_list(bd_seeded, bd_as_user, bd_db, bd_today):
    """Saturday: the Friday run has made next week's list, so that is the list the move works on."""
    bd_today("2026-11-07")
    co = company(bd_db, "Prairie Lark Bakery")
    due, other = person(bd_db, co, "Gus Hemmer", AVERY), person(bd_db, co, "Ivy Hemmer", AVERY)
    nxt = bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, %s, 'friday')"
                        " returning id", (NEXT_MONDAY,)).fetchone()["id"]
    call = task(bd_db, nxt, other, kind="new")
    filler = task(bd_db, nxt, 21)
    logged(bd_db, other, "2026-10-01", kind="email", outcome=None)
    move(bd_as_user(AVERY), co, "maintenance")
    rows = {r["id"]: r for r in bd_db.execute("select id, batch_id, contact_id, kind, status from bd.tasks"
                                               " where batch_id = %s", (nxt,)).fetchall()}
    assert rows[call]["status"] == "snoozed" and rows[filler]["status"] == "open"
    assert [(r["contact_id"], r["kind"], r["status"]) for r in rows.values() if r["kind"] == "maintenance"] == [
        (due, "maintenance", "open")]


def test_archived_people_move_too_but_are_not_counted(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set archived_at = bd_now() where id = 28")
    body = move(bd_as_user(BLAIR), 16, "maintenance")
    assert body["move"]["people"] == 2
    cats = {r["id"]: r["category"] for r in bd_db.execute(
        "select id, category from bd.contacts where company_id = 16").fetchall()}
    assert cats == {27: "maintenance", 28: "maintenance", 29: "maintenance"}


def test_a_company_on_both_tabs_moves_only_its_bd_people(bd_seeded, bd_as_user, bd_db):
    tobin = person(bd_db, 16, "Tobin Reyes", EMERY, category="maintenance")
    bd_db.execute("update bd.contacts set frequency_per_year = 2 where id = %s", (tobin,))
    body = move(bd_as_user(EMERY), 16, "maintenance")
    assert body["move"]["people"] == 3
    assert bd_db.execute("select category, frequency_per_year from bd.contacts where id = %s",
                         (tobin,)).fetchone() == {"category": "maintenance", "frequency_per_year": 2}
    bd_tab = bd_as_user(EMERY).get("/api/bd/contacts/accounts").json()
    m_tab = bd_as_user(EMERY).get("/api/bd/contacts/accounts?category=maintenance").json()
    assert 16 not in [a["id"] for a in bd_tab["items"]]
    assert [(a["id"], a["people_count"]) for a in m_tab["items"]] == [(16, 4), (17, 2)]


def test_the_move_writes_one_event_with_ids_and_counts_only(bd_seeded, bd_as_user, bd_db):
    t = tallgrass(bd_db)
    before = events(bd_db)
    body = move(bd_as_user(AVERY), t["company"], "maintenance")
    new = events(bd_db)[len(before):]
    assert len(new) == 1
    ev = new[0]
    assert (ev["id"], ev["kind"], ev["actor_id"], ev["contact_id"], ev["detail"]) == (
        body["move"]["id"], "company_moved", AVERY, None, None)
    d = ev["data"]
    assert set(d) == {"company_id", "to", "people", "contacts", "tasks_off", "pins", "batches"}
    assert (d["company_id"], d["to"], d["people"]) == (t["company"], "maintenance", 5)
    assert d["contacts"] == [[t[k], 4] for k in ("p1", "p2", "p3", "p4", "p5")]   # the frequency before
    assert d["tasks_off"] == sorted([t["t1"], t["t3"]]) and len(d["pins"]) == 3 and len(d["batches"]) == 2
    # Nothing but ids, counts and the direction: no name, phone, email, company name or note.
    assert all(isinstance(v, int) for k in ("tasks_off", "pins", "batches") for v in d[k])
    text = repr(ev).lower()
    for secret in ("arlo", "penn", "913-555-0141", "5550141", "tallgrass", "made up", "lenexa"):
        assert secret not in text, secret


# ── back to BD ──────────────────────────────────────────────────────────────────────────────────
def test_moving_back_to_bd_removes_the_pin_and_adds_nothing(bd_seeded, bd_as_user, bd_db):
    before = state(bd_db)
    tasks_before = len(before["tasks"])
    body = move(bd_as_user(BLAIR), 17, "bd")
    assert {k: body["move"][k] for k in ("to", "people", "calls_off", "pinned")} == {
        "to": "bd", "people": 2, "calls_off": 1, "pinned": 0}
    after = state(bd_db)
    cats = {r["id"]: (r["category"], r["frequency_per_year"]) for r in after["contacts"] if r["id"] in (30, 31)}
    assert cats == {30: ("bd", 4), 31: ("bd", 4)}                   # 4: the quarterly BD cadence
    hal = [r for r in after["tasks"] if r["id"] == 301][0]
    assert (hal["status"], str(hal["snoozed_until"])) == ("snoozed", NEXT_MONDAY)
    assert len(after["tasks"]) == tasks_before and after["task_batches"] == before["task_batches"]
    assert [r for r in after["tasks"] if r["id"] != 301] == [r for r in before["tasks"] if r["id"] != 301]
    week = bd_as_user(AVERY).get("/api/bd/week").json()["week"]
    assert week["due_count"] == 0 and (week["done_count"], week["total"]) == (1, 2)
    ev = events(bd_db)[-1]
    assert ev["data"] == {"company_id": 17, "to": "bd", "people": 2, "contacts": [[30, 3], [31, 2]],
                          "tasks_off": [301], "pins": [], "batches": []}
    tabs = {tab: [a["id"] for a in bd_as_user(AVERY).get(
        "/api/bd/contacts/accounts?category=" + tab).json()["items"]] for tab in ("bd", "maintenance")}
    assert 17 in tabs["bd"] and tabs["maintenance"] == []


# ── undo ────────────────────────────────────────────────────────────────────────────────────────
def test_undo_puts_back_exactly_what_was_there(bd_seeded, bd_as_user, bd_db):
    t = tallgrass(bd_db)
    before = state(bd_db)
    weeks_before = {who: bd_as_user(who).get("/api/bd/week").json()["week"] for who in (AVERY, BLAIR)}
    avery = bd_as_user(AVERY)
    mid = move(avery, t["company"], "maintenance")["move"]["id"]
    assert state(bd_db) != before
    r = avery.post(UNDO % mid, json={})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "undone": {"id": mid, "company": {"id": t["company"], "name": "Tallgrass Millwork"},
                                                "to": "maintenance", "people": 5}}
    assert state(bd_db) == before                                  # the calls that came off are back too
    assert {who: bd_as_user(who).get("/api/bd/week").json()["week"] for who in (AVERY, BLAIR)} == weeks_before
    ev = events(bd_db)[-1]
    assert (ev["kind"], ev["actor_id"], ev["contact_id"], ev["data"]) == (
        "company_move_undone", AVERY, None, {"move_id": mid, "company_id": t["company"], "to": "maintenance",
                                             "people": 5})


def test_undo_of_a_move_back_to_bd(bd_seeded, bd_as_user, bd_db):
    before = state(bd_db)
    devon = bd_as_user(DEVON)
    mid = move(devon, 17, "bd")["move"]["id"]
    assert devon.post(UNDO % mid).status_code == 200
    assert state(bd_db) == before


def test_only_the_person_who_moved_it_can_undo_it(bd_seeded, bd_as_user, bd_db):
    t = tallgrass(bd_db)
    mid = move(bd_as_user(AVERY), t["company"], "maintenance")["move"]["id"]
    after = state(bd_db)
    for who in (BLAIR, DEVON, EMERY, FRANKIE):
        r = bd_as_user(who).post(UNDO % mid, json={})
        assert (r.status_code, r.json()) == (403, {"ok": False, "error": "forbidden",
                                                   "message": "Only the person who made this move can undo it."})
    assert state(bd_db) == after


@pytest.mark.parametrize("seconds,status", [(119, 200), (121, 409)])
def test_the_undo_window_is_two_minutes(bd_seeded, bd_as_user, bd_db, seconds, status):
    mid = move(bd_as_user(AVERY), 17, "bd")["move"]["id"]
    bd_db.execute("update bd.events set at = bd_now() - %s * interval '1 second' where id = %s", (seconds, mid))
    after = state(bd_db)
    r = bd_as_user(AVERY).post(UNDO % mid)
    assert r.status_code == status, r.text
    if status == 409:
        assert r.json()["message"] == "It's too late to undo this move." and state(bd_db) == after


def test_an_undo_once_is_enough(bd_seeded, bd_as_user, bd_db):
    mid = move(bd_as_user(AVERY), 17, "bd")["move"]["id"]
    assert bd_as_user(AVERY).post(UNDO % mid).status_code == 200
    after = state(bd_db)
    r = bd_as_user(AVERY).post(UNDO % mid)
    assert (r.status_code, r.json()["message"]) == (409, "This move is already undone.")
    assert state(bd_db) == after


def test_a_later_move_makes_the_earlier_one_stale(bd_seeded, bd_as_user, bd_db):
    avery = bd_as_user(AVERY)
    first = move(avery, 17, "bd")["move"]["id"]
    move(avery, 17, "maintenance")
    after = state(bd_db)
    r = avery.post(UNDO % first)
    assert (r.status_code, r.json()["message"]) == (409, "Something changed since this move, so it can't be undone.")
    assert state(bd_db) == after


def test_a_later_move_of_someone_new_still_makes_the_earlier_one_stale(bd_seeded, bd_as_user, bd_db):
    """Kaw Valley goes to BD. Then a newcomer is added and the company is made maintenance again, and
    Hal and Nora are put back to BD by hand, so everything the first move changed looks as it left it.
    It is still not the company's latest move, so it cannot be undone."""
    avery = bd_as_user(AVERY)
    first = move(avery, 17, "bd")["move"]["id"]
    bd_db.execute("insert into bd.contacts (company_id, name, category, owner_id, frequency_per_year)"
                  " values (17, 'Mae Corrin', 'bd', 1, 4)")
    second = move(avery, 17, "maintenance")["move"]
    assert second["people"] == 3
    bd_db.execute("update bd.contacts set category = 'bd' where id in (30, 31)")    # as the first left them
    after = state(bd_db)
    r = avery.post(UNDO % first)
    assert (r.status_code, r.json()["message"]) == (409, "Something changed since this move, so it can't be undone.")
    assert state(bd_db) == after


@pytest.mark.parametrize("change", ["call_logged", "call_reopened", "person_edited"])
def test_a_change_since_the_move_makes_it_stale(bd_seeded, bd_as_user, bd_db, change):
    t = tallgrass(bd_db)
    avery = bd_as_user(AVERY)
    mid = move(avery, t["company"], "maintenance")["move"]["id"]
    if change == "call_logged":            # a follow-up closes the pin it made
        r = avery.post("/api/bd/contacts/%d/interactions" % t["p4"], json={"kind": "call", "outcome": "answered"})
    elif change == "call_reopened":        # a call it took off is put back by hand
        r = avery.post("/api/bd/tasks/%d/reopen" % t["t1"], json={})
    else:                                  # a person is moved back by hand
        r = avery.patch("/api/bd/contacts/%d" % t["p5"], json={"category": "bd"})
    assert r.status_code in (200, 201), r.text
    after = state(bd_db)
    r = avery.post(UNDO % mid)
    assert (r.status_code, r.json()["message"]) == (409, "Something changed since this move, so it can't be undone.")
    assert state(bd_db) == after


@pytest.mark.parametrize("path", [UNDO % 999999, UNDO % "abc", UNDO % 0])
def test_undo_of_no_such_move_is_404(bd_seeded, bd_as_user, path):
    r = bd_as_user(AVERY).post(path)
    assert (r.status_code, r.json()) == (404, {"ok": False, "error": "not_found", "message": "That move does not exist."})


def test_an_event_that_is_not_a_move_cannot_be_undone(bd_seeded, bd_as_user, bd_db):
    avery = bd_as_user(AVERY)
    mid = move(avery, 17, "bd")["move"]["id"]
    assert avery.post(UNDO % mid).status_code == 200
    undo_event = events(bd_db)[-1]["id"]
    assert avery.post(UNDO % undo_event).status_code == 404


# ── refusals ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,body,status,message,fields", [
    (MOVE % 16, {}, 400, "Some fields need fixing.", {"to": "Use maintenance or bd."}),
    (MOVE % 16, {"to": "vip"}, 400, "Some fields need fixing.", {"to": "Use maintenance or bd."}),
    (MOVE % 16, ["maintenance"], 400, "Some fields need fixing.", {"body": "Send a JSON object."}),
    (MOVE % 999999, {"to": "maintenance"}, 404, "That company does not exist.", None),
    (MOVE % "abc", {"to": "maintenance"}, 404, "That company does not exist.", None),
    (MOVE % 17, {"to": "maintenance"}, 409, "Nobody at this company is a BD contact.", None),
    (MOVE % 16, {"to": "bd"}, 409, "Nobody at this company is a maintenance contact.", None),
])
def test_a_move_that_cannot_happen_changes_nothing(bd_seeded, bd_as_user, bd_db, path, body, status, message,
                                                   fields):
    before, ev_before = state(bd_db), events(bd_db)
    r = bd_as_user(AVERY).post(path, json=body)
    assert r.status_code == status, r.text
    assert r.json()["message"] == message and r.json().get("fields") == fields
    assert state(bd_db) == before and events(bd_db) == ev_before


# ── the company type-ahead is untouched ─────────────────────────────────────────────────────────
TYPE_AHEAD = (b'{"ok":true,"total":1,"items":[{"id":16,"name":"Bluestem Logistics","city":"Lenexa",'
              b'"industry":"Warehousing","created_at":"2026-11-04T09:00:00-06:00","contact_count":3}]}')


def test_the_company_type_ahead_answers_byte_for_byte_as_before(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.companies set created_at = '2026-11-04 15:00:00+00'")
    casey = bd_as_user(CASEY)
    assert casey.get("/api/bd/companies?q=bluestem").content == TYPE_AHEAD
    whole = casey.get("/api/bd/companies").content
    move(bd_as_user(AVERY), 16, "maintenance")
    assert casey.get("/api/bd/companies?q=bluestem").content == TYPE_AHEAD
    assert casey.get("/api/bd/companies").content == whole
