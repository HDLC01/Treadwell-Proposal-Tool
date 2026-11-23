"""The Weekly 10 is ten companies (#828): one slot per company a week, misses counted for the company,
the 3-day rest kept by the company, one row per company on This Week, and the row buttons acting on the
whole row. Through the public seams: the Friday batch (weekly.run_due, the worker's one call, and the
admin's run), Give Me 10 More, GET /api/bd/week, the task buttons and logging a call.

Hanz's answers to #828's open points (2026-11-23), each pinned by a test below:
  * a call nobody answered is a miss, the same as a voicemail;
  * the cadence part of the score stays per person (only misses and the new/follow-up split move);
  * the 3-day rest is the company's (anyone there tried in the last 3 days keeps it off a new list
    and off Give Me 10 More);
  * a row closes when a call, voicemail, meeting or hosted event is logged with anyone there; a
    company is "new" only when nobody there has had a live talk; its score is its best person's,
    with the tries counted for the company.

THE WORLD (made up: example.com emails, 555-01xx phones), Reed Jansen's (RJ) people unless noted, the
batch built Fri 2026-11-27 16:00 Central for the week of Mon Nov 30. Scores by hand with
bd/priority.py's rules (confirmed people, quarterly cadence: interval 365 / 4 = 91.25 days):

  ABC Construction  Jim Ash    never talked live, key account: never contacted +40, key +20 = 60.
                    Sue Baird  live call Jun 1 (179 days before Nov 27): 30 x 179 / 91.25 = 58.8,
                               capped at 40 = 40. Promised Jan 15 and next step Jan 20 2027 are more
                               than 7 days out: no points.
                    Someone there talked live, so ABC is a FOLLOW-UP, though Jim, its best person
                    (60), never has. One slot, Jim's.
  XYZ Builders      Pat Cruz   never contacted = 40. New.
  DEF Supply        Ann Dorn   voicemail Nov 10;  Bob Eads  no-answer call Nov 16. Nobody ever
                    talked live: DEF has 2 misses. Each person: "Never reached after 2 tries" +40,
                    2 tries +10 = 50 (on their own tries it would be 1 try: 45). New; Ann (lower id).
  GHI Paving        Cal Finn   never, key account;  Dee Gold  voicemail Wed Nov 25, 2 days before
                    the batch: GHI rests, Cal included. (On Mon Nov 30 it is back: Cal never
                    reached after GHI's 1 try +40, key +20, 1 try +5 = 65.)
  QRS Foods         Quinn Hale, Rae Ives: maintenance, never followed up, so both due: one row
                    under "Due now", two maintenance tasks, most overdue first (no date: by id),
                    never contacted 40 each, reasons start "No follow-up logged yet".
  JKL Steel         Kim Lowe, Toby Vance's (the other salesperson): never on RJ's list.

  RJ's batch, in order: Quinn (maintenance 40), Rae (maintenance 40), Jim (followup 60), Ann (new 50),
  Pat (new 40). Four rows: QRS under Due now, then ABC, DEF, XYZ: "0 of 3 done", "Due now: 1".
"""
from __future__ import annotations

import datetime as dt
import random

import pytest

from bd import weekly

D = dt.date.fromisoformat
FRIDAY_RUN = "2026-11-27T16:00:00-06:00"
WEEK = "2026-11-30"
STAYS = "A maintenance follow-up stays on the list until you log a call, meeting, email or text."


# ── the world ──────────────────────────────────────────────────────────────────────────────────
def mk_user(db, name, role):
    email = "%s@example.com" % name.lower().replace(" ", ".")
    return db.execute("insert into bd.users (email, name, role) values (%s, %s, %s) returning *",
                      (email, name, role)).fetchone()


def mk_company(db, name):
    return db.execute("insert into bd.companies (name, normalized_name) values (%s, %s) returning id",
                      (name, name.lower())).fetchone()["id"]


_phone = [40]


def mk_person(db, company, owner, name, title="Estimator", category="bd", importance=1, phone=True, **extra):
    _phone[0] = 40 if _phone[0] >= 99 else _phone[0] + 1
    cols = {"company_id": company, "name": name, "title": title, "category": category, "owner_id": owner,
            "importance": importance, "confirmed": True,
            "phone": "913-555-01%02d" % _phone[0] if phone else None,
            "email": "%s@example.com" % name.lower().replace(" ", ".")}
    cols.update(extra)
    names = list(cols)
    return db.execute("insert into bd.contacts (%s) values (%s) returning id" % (
        ", ".join(names), ", ".join(["%s"] * len(names))), [cols[n] for n in names]).fetchone()["id"]


def mk_talk(db, contact_id, kind, at, outcome=None, user=None):
    return db.execute("insert into bd.interactions (contact_id, kind, outcome, occurred_at, user_id)"
                      " values (%s, %s, %s, %s, %s) returning id", (contact_id, kind, outcome, at, user)).fetchone()["id"]


@pytest.fixture
def world(bd_db, bd_today, monkeypatch):
    from bd import config

    monkeypatch.setattr(config, "BD_WEEKLY_ENABLED", True)      # as on prod: the Friday batch runs
    bd_today("2026-11-27")
    _phone[0] = 40                                              # Jim is 913-555-0141, Sue -0142, ...
    db = bd_db
    u = {key: mk_user(db, name, role) for key, name, role in (
        ("rj", "Reed Jansen", "salesperson"), ("toby", "Toby Vance", "salesperson"),
        ("mona", "Mona Park", "manager"), ("ava", "Ava Lin", "assistant"),
        ("abe", "Abe Cole", "admin"), ("sky", "Sky Hart", "super_admin"))}
    rj, toby = u["rj"]["id"], u["toby"]["id"]
    co = {key: mk_company(db, name) for key, name in (
        ("abc", "ABC Construction"), ("xyz", "XYZ Builders"), ("def", "DEF Supply"), ("ghi", "GHI Paving"),
        ("qrs", "QRS Foods"), ("jkl", "JKL Steel"))}
    p = {}
    p["jim"] = mk_person(db, co["abc"], rj, "Jim Ash", "Project Manager", importance=3)
    p["sue"] = mk_person(db, co["abc"], rj, "Sue Baird", "Owner", promised_date="2027-01-15",
                         next_step="Send the floor samples", next_step_date="2027-01-20")
    p["pat"] = mk_person(db, co["xyz"], rj, "Pat Cruz")
    p["ann"] = mk_person(db, co["def"], rj, "Ann Dorn")
    p["bob"] = mk_person(db, co["def"], rj, "Bob Eads")
    p["cal"] = mk_person(db, co["ghi"], rj, "Cal Finn", importance=3)
    p["dee"] = mk_person(db, co["ghi"], rj, "Dee Gold")
    p["quinn"] = mk_person(db, co["qrs"], rj, "Quinn Hale", "Plant Manager", category="maintenance")
    p["rae"] = mk_person(db, co["qrs"], rj, "Rae Ives", "Maintenance Lead", category="maintenance")
    p["kim"] = mk_person(db, co["jkl"], toby, "Kim Lowe")
    mk_talk(db, p["sue"], "call", "2026-06-01T15:00:00Z", "answered", rj)       # 10:00 CDT
    mk_talk(db, p["ann"], "voicemail", "2026-11-10T16:00:00Z", "voicemail", rj)
    mk_talk(db, p["bob"], "call", "2026-11-16T16:00:00Z", "no_answer", rj)
    mk_talk(db, p["dee"], "voicemail", "2026-11-25T16:00:00Z", "voicemail", rj)  # Wed 10:00 CST
    return {"u": u, "co": co, "p": p, "rj": rj, "toby": toby}


@pytest.fixture
def built(world, bd_db, bd_today):
    """The Friday batch run at Fri Nov 27 16:00 Central, then today is Mon Nov 30, 10:00."""
    done = weekly.run_due(bd_db, now=FRIDAY_RUN)
    assert sorted(b["owner_id"] for b in done) == sorted([world["rj"], world["toby"]])
    world["batch"] = next(b["batch_id"] for b in done if b["owner_id"] == world["rj"])
    tasks = bd_db.execute("select id, contact_id from bd.tasks where batch_id = %s order by id",
                          (world["batch"],)).fetchall()
    world["t"] = {name: next((t["id"] for t in tasks if t["contact_id"] == cid), None)
                  for name, cid in world["p"].items()}
    bd_today(WEEK)
    return world


def as_(bd_as_user, world, who):
    return bd_as_user(world["u"][who]["email"])


def tasks_of(db, batch_id):
    return [(r["contact_id"], r["kind"], r["score"]) for r in db.execute(
        "select contact_id, kind, score from bd.tasks where batch_id = %s order by id", (batch_id,)).fetchall()]


def companies_of(db, batch_id):
    return [r["company_id"] for r in db.execute(
        "select c.company_id from bd.tasks t join bd.contacts c on c.id = t.contact_id"
        " where t.batch_id = %s and t.kind <> 'maintenance' order by t.id", (batch_id,)).fetchall()]


def get_week(client, owner=None):
    q = "?week_start=" + WEEK + ("&owner=%d" % owner if owner else "")
    r = client.get("/api/bd/week" + q)
    assert r.status_code == 200, r.text
    return r.json()["week"]


def row_of(week, company_id):
    rows = [r for r in week["rows"] if r["company"]["id"] == company_id]
    assert len(rows) == 1, rows
    return rows[0]


def headline(week):
    return week["done_count"], week["total"], week["due_count"]


# ── the Friday batch picks companies ─────────────────────────────────────────────────────────
def test_the_friday_batch_gives_abc_one_slot_and_counts_in_companies(built, bd_db):
    p = built["p"]
    assert tasks_of(bd_db, built["batch"]) == [
        (p["quinn"], "maintenance", 40), (p["rae"], "maintenance", 40),
        (p["jim"], "followup", 60),         # ABC: Sue talked live once, so a follow-up; Jim leads it
        (p["ann"], "new", 50),              # DEF: 2 misses for the company, not 1 for Ann
        (p["pat"], "new", 40)]
    reasons = {r["contact_id"]: r["reasons"] for r in bd_db.execute(
        "select contact_id, reasons from bd.tasks where batch_id = %s", (built["batch"],)).fetchall()}
    assert reasons[p["ann"]] == ["Never reached after 2 tries"]
    assert reasons[p["jim"]] == ["Never contacted", "Key account"]
    assert reasons[p["quinn"]] == ["No follow-up logged yet", "Never contacted"]
    # GHI rests: Dee was tried two days before the batch, so Cal (60) stays off too.
    assert built["t"]["cal"] is None and built["t"]["sue"] is None
    co = built["co"]
    assert companies_of(bd_db, built["batch"]) == [co["abc"], co["def"], co["xyz"]]


def test_the_week_shows_one_row_per_company(built, bd_as_user):
    w = get_week(as_(bd_as_user, built, "rj"))
    co, p, t = built["co"], built["p"], built["t"]
    assert [(r["company"]["name"], r["section"], r["kind"], r["status"], r["task_ids"]) for r in w["rows"]] == [
        ("QRS Foods", "due", "maintenance", "open", [t["quinn"], t["rae"]]),
        ("ABC Construction", "ten", "followup", "open", [t["jim"]]),
        ("DEF Supply", "ten", "new", "open", [t["ann"]]),
        ("XYZ Builders", "ten", "new", "open", [t["pat"]])]
    assert headline(w) == (0, 3, 1)
    abc = row_of(w, co["abc"])
    assert abc["id"] == t["jim"] and abc["batch_id"] == built["batch"]
    assert (abc["score"], abc["reason"], abc["misses"]) == (60, "Never contacted. Key account.", 0)
    assert abc["last_live_at"] == "2026-06-01T10:00:00-05:00"
    assert abc["company"] == {"id": co["abc"], "name": "ABC Construction"}
    # The person to call first, then the others the salesperson owns there.
    assert abc["people"] == [
        {"id": p["jim"], "name": "Jim Ash", "title": "Project Manager", "phone": "913-555-0141",
         "phone_e164": "+19135550141", "email": "jim.ash@example.com", "confirmed": True,
         "last_live_at": None, "attempts_since_live": 0, "promised_date": None, "next_step": None,
         "next_step_date": None, "task_id": t["jim"], "not_right_person": False},
        {"id": p["sue"], "name": "Sue Baird", "title": "Owner", "phone": "913-555-0142",
         "phone_e164": "+19135550142", "email": "sue.baird@example.com", "confirmed": True,
         "last_live_at": "2026-06-01T10:00:00-05:00", "attempts_since_live": 0,
         "promised_date": "2027-01-15", "next_step": "Send the floor samples",
         "next_step_date": "2027-01-20", "task_id": None, "not_right_person": False}]
    d = row_of(w, co["def"])
    assert (d["misses"], d["last_live_at"]) == (2, None)
    assert [(x["name"], x["attempts_since_live"]) for x in d["people"]] == [("Ann Dorn", 1), ("Bob Eads", 1)]
    q = row_of(w, co["qrs"])
    assert [x["task_id"] for x in q["people"]] == [t["quinn"], t["rae"]]
    # Every row and person has exactly the contract's WeekRow keys (docs/bd/api-contract.md).
    from test_bd_serialize import WEEK_ROW_PERSON_SPEC, WEEK_ROW_SPEC, check_shape

    for r in w["rows"]:
        check_shape(r, WEEK_ROW_SPEC)
        for person in r["people"]:
            check_shape(person, WEEK_ROW_PERSON_SPEC)


def test_a_salespersons_row_shows_only_the_people_they_own(built, bd_db, bd_as_user):
    """Toby owns a third person at ABC: RJ's row does not list him, but a miss on him is ABC's."""
    co = built["co"]
    tess = mk_person(bd_db, co["abc"], built["toby"], "Tess Kerr")
    mk_talk(bd_db, tess, "voicemail", "2026-11-30T15:00:00Z", "voicemail", built["toby"])
    abc = row_of(get_week(as_(bd_as_user, built, "rj")), co["abc"])
    assert [x["name"] for x in abc["people"]] == ["Jim Ash", "Sue Baird"]
    assert abc["misses"] == 1


# ── misses count for the company ─────────────────────────────────────────────────────────────
def test_misses_count_for_the_company_and_a_live_talk_resets_them(built, bd_as_user, monkeypatch):
    monkeypatch.setenv("BD_NOW", "2026-11-30T10:00:00-06:00")
    rj = as_(bd_as_user, built, "rj")
    co, p, t = built["co"], built["p"], built["t"]

    def log(who, kind, outcome=None):
        body = {"kind": kind}
        if outcome:
            body["outcome"] = outcome
        r = rj.post("/api/bd/contacts/%d/interactions" % p[who], json=body)
        assert r.status_code == 200, r.text
        return r.json()

    # A voicemail on Jim closes ABC's row and "N of 10 done" moves by one.
    out = log("jim", "voicemail")
    assert out["task"]["id"] == t["jim"] and out["task"]["status"] == "done"
    w = get_week(rj)
    assert row_of(w, co["abc"])["status"] == "done" and headline(w) == (1, 3, 1)
    # A call nobody answered with Sue the same day: the row stays closed, the count stays at 1, and
    # ABC has 2 misses since Sue's live talk in June.
    assert log("sue", "call", "no_answer")["task"] is None
    w = get_week(rj)
    assert headline(w) == (1, 3, 1)
    assert row_of(w, co["abc"])["misses"] == 2
    # A voicemail on Pat at XYZ is XYZ's miss, never ABC's.
    log("pat", "voicemail")
    w = get_week(rj)
    assert (row_of(w, co["abc"])["misses"], row_of(w, co["xyz"])["misses"]) == (2, 1)
    assert headline(w) == (2, 3, 1)
    # A live talk with either one sets ABC back to 0.
    log("sue", "call", "answered")
    w = get_week(rj)
    assert row_of(w, co["abc"])["misses"] == 0
    assert row_of(w, co["abc"])["last_live_at"] == "2026-11-30T10:00:00-06:00"
    assert headline(w) == (2, 3, 1)


def test_misses_are_counted_by_their_central_date(built, bd_db, bd_as_user, bd_today):
    """Two voicemails late on Mon Nov 30: 23:30 Central is still Nov 30 (05:30 UTC on Dec 1), 00:30
    Central is Dec 1. On Nov 30 ABC has 1 miss; on Dec 1, 2."""
    p, co = built["p"], built["co"]
    mk_talk(bd_db, p["jim"], "voicemail", "2026-12-01T05:30:00Z", "voicemail", built["rj"])
    mk_talk(bd_db, p["sue"], "voicemail", "2026-12-01T06:30:00Z", "voicemail", built["rj"])
    rj = as_(bd_as_user, built, "rj")
    assert row_of(get_week(rj), co["abc"])["misses"] == 1
    bd_today("2026-12-01")
    assert row_of(get_week(rj), co["abc"])["misses"] == 2


# ── a row closes once; the buttons act on the whole row ──────────────────────────────────────
@pytest.mark.parametrize("kind, outcome", [("call", "answered"), ("call", "no_answer"), ("voicemail", None),
                                           ("meeting", None), ("hosted", None)])
def test_each_closing_kind_with_anyone_there_closes_the_row(built, bd_as_user, monkeypatch, kind, outcome):
    monkeypatch.setenv("BD_NOW", "2026-11-30T11:00:00-06:00")
    rj = as_(bd_as_user, built, "rj")
    body = {"kind": kind, **({"outcome": outcome} if outcome else {})}
    r = rj.post("/api/bd/contacts/%d/interactions" % built["p"]["sue"], json=body)     # Sue has no task
    assert r.status_code == 200, r.text
    assert r.json()["task"]["id"] == built["t"]["jim"]
    w = get_week(rj)
    assert row_of(w, built["co"]["abc"])["status"] == "done" and headline(w) == (1, 3, 1)


@pytest.mark.parametrize("kind", ["email", "sms", "note"])
def test_an_email_a_text_or_a_note_leaves_the_row_open(built, bd_as_user, kind):
    rj = as_(bd_as_user, built, "rj")
    r = rj.post("/api/bd/contacts/%d/interactions" % built["p"]["sue"], json={"kind": kind, "summary": "Hi."})
    assert r.status_code == 200, r.text
    assert r.json()["task"] is None
    assert row_of(get_week(rj), built["co"]["abc"])["status"] == "open"


def legacy_week(db, world):
    """A week built before #828 (inserted directly): RJ's Friday list for Nov 30 holds Jim AND Sue at
    ABC, then Pat."""
    b = db.execute("insert into bd.task_batches (owner_id, week_start, kind, generated_at) values"
                   " (%s, %s, 'friday', '2026-11-27T16:00:00-06:00') returning id", (world["rj"], WEEK)).fetchone()["id"]
    ids = {}
    for name, kind in (("jim", "new"), ("sue", "followup"), ("pat", "new")):
        ids[name] = db.execute("insert into bd.tasks (batch_id, contact_id, kind, reason, reasons, score)"
                               " values (%s, %s, %s, 'Old.', array['Old'], 50) returning id",
                               (b, world["p"][name], kind)).fetchone()["id"]
    return b, ids


def statuses(db, ids):
    return [db.execute("select status from bd.tasks where id = %s", (i,)).fetchone()["status"] for i in ids]


def test_a_legacy_week_with_two_people_at_abc_is_one_row(world, bd_db, bd_as_user, bd_today, monkeypatch):
    bd_today(WEEK)
    monkeypatch.setenv("BD_NOW", "2026-11-30T09:00:00-06:00")
    batch, t = legacy_week(bd_db, world)
    rj = as_(bd_as_user, world, "rj")
    w = get_week(rj)
    assert [(r["company"]["name"], r["task_ids"]) for r in w["rows"]] == [
        ("ABC Construction", [t["jim"], t["sue"]]), ("XYZ Builders", [t["pat"]])]
    assert [x["task_id"] for x in row_of(w, world["co"]["abc"])["people"]] == [t["jim"], t["sue"]]
    assert headline(w) == (0, 2, 0) and len(w["tasks"]) == 3
    # "Done, nothing to log" on Sue's task closes the whole row: 1 of 2.
    r = rj.post("/api/bd/tasks/%d/done" % t["sue"], json={})
    assert r.status_code == 200, r.text
    assert (r.json()["done_count"], r.json()["total"]) == (1, 2)
    assert statuses(bd_db, [t["jim"], t["sue"], t["pat"]]) == ["done", "done", "open"]
    r = rj.post("/api/bd/tasks/%d/done" % t["jim"], json={})
    assert (r.status_code, r.json()["message"]) == (409, "That task is already done.")
    # Reopen on Jim's task opens both.
    assert rj.post("/api/bd/tasks/%d/reopen" % t["jim"], json={}).status_code == 200
    assert statuses(bd_db, [t["jim"], t["sue"]]) == ["open", "open"]
    # "Not this week" on Jim's takes the whole row off; the list is not refilled.
    r = rj.post("/api/bd/tasks/%d/snooze" % t["jim"], json={"reason": "Closed for the holiday"})
    assert r.status_code == 200 and (r.json()["done_count"], r.json()["total"]) == (0, 2)
    assert statuses(bd_db, [t["jim"], t["sue"], t["pat"]]) == ["snoozed", "snoozed", "open"]
    w = get_week(rj)
    assert row_of(w, world["co"]["abc"])["status"] == "snoozed" and len(w["tasks"]) == 3
    assert bd_db.execute("select count(*) as n from bd.task_batches").fetchone()["n"] == 1
    # A call logged with Sue closes the row of every task there at once (reopened first).
    rj.post("/api/bd/tasks/%d/reopen" % t["sue"], json={})
    out = rj.post("/api/bd/contacts/%d/interactions" % world["p"]["sue"], json={"kind": "voicemail"}).json()
    assert out["task"]["id"] == t["sue"]
    assert statuses(bd_db, [t["jim"], t["sue"]]) == ["done", "done"]
    assert headline(get_week(rj)) == (1, 2, 0)


def test_a_legacy_week_half_done_before_the_deploy_stays_done(world, bd_db, bd_as_user, bd_today, monkeypatch):
    """RJ's Nov 30 list was built before #828 and he left Jim a voicemail on Monday morning, so Jim's
    task is done and Sue's still open when #828 deploys. Under #828 the ABC row was closed by that
    voicemail: it reads done, "1 of 2 done" does not go back to 0, and the row's buttons treat it as
    done until it is reopened."""
    bd_today(WEEK)
    monkeypatch.setenv("BD_NOW", "2026-11-30T11:00:00-06:00")
    batch, t = legacy_week(bd_db, world)
    bd_db.execute("update bd.tasks set status = 'done', done_at = '2026-11-30T09:15:00-06:00' where id = %s",
                  (t["jim"],))
    rj = as_(bd_as_user, world, "rj")
    w = get_week(rj)
    assert row_of(w, world["co"]["abc"])["status"] == "done" and headline(w) == (1, 2, 0)
    r = rj.post("/api/bd/tasks/%d/done" % t["sue"], json={})
    assert (r.status_code, r.json()["message"]) == (409, "That task is already done.")
    r = rj.post("/api/bd/tasks/%d/snooze" % t["sue"], json={})
    assert (r.status_code, r.json()["message"]) == (409, "Only an open task can be skipped.")
    assert statuses(bd_db, [t["jim"], t["sue"]]) == ["done", "open"]
    assert rj.post("/api/bd/tasks/%d/reopen" % t["sue"], json={}).status_code == 200
    assert statuses(bd_db, [t["jim"], t["sue"]]) == ["open", "open"]
    assert headline(get_week(rj)) == (0, 2, 0)


def test_a_merge_of_an_open_row_into_a_done_one_keeps_it_done(built, bd_db, bd_as_user, monkeypatch):
    """#811's merge after #828: Pat's voicemail closed XYZ's row (1 of 3). An admin then merges ABC
    (Jim's row, open) into XYZ. Both tasks sit on one XYZ row now, which stays done: 1 of 2, never 0."""
    monkeypatch.setenv("BD_NOW", "2026-11-30T10:00:00-06:00")
    co, p, t = built["co"], built["p"], built["t"]
    rj = as_(bd_as_user, built, "rj")
    assert rj.post("/api/bd/contacts/%d/interactions" % p["pat"], json={"kind": "voicemail"}).status_code == 200
    assert headline(get_week(rj)) == (1, 3, 1)
    r = as_(bd_as_user, built, "abe").post("/api/bd/contacts/accounts/%d/merge" % co["abc"],
                                           json={"into": co["xyz"], "name_from": co["xyz"]})
    assert r.status_code == 200, r.text
    w = get_week(rj)
    xyz = row_of(w, co["xyz"])
    assert (xyz["status"], sorted(xyz["task_ids"])) == ("done", sorted([t["jim"], t["pat"]]))
    assert headline(w) == (1, 2, 1)


def test_a_follow_up_companys_never_reached_best_person_reads_the_companys_tries(world, bd_db):
    """Sue (live talk Jun 1) then got a voicemail on Nov 10 and a call nobody answered on Nov 16: ABC
    has 2 misses since its last live talk. Jim, ABC's best person, was never tried himself: the 40
    points for never having a live talk are his own, the tries part (2 x 5) is the company's, and the
    chip says what the row's misses line says, "2 tries since the last live talk", never "Never
    reached after 2 tries" (#828's example). 40 + key 20 + 10 = 70. DEF (nobody there ever talked
    live) still reads "Never reached after 2 tries"."""
    p = world["p"]
    mk_talk(bd_db, p["sue"], "voicemail", "2026-11-10T16:00:00Z", "voicemail", world["rj"])
    mk_talk(bd_db, p["sue"], "call", "2026-11-16T16:00:00Z", "no_answer", world["rj"])
    done = weekly.run_due(bd_db, now=FRIDAY_RUN)
    batch = next(b["batch_id"] for b in done if b["owner_id"] == world["rj"])
    rows = {r["contact_id"]: r for r in bd_db.execute(
        "select contact_id, kind, score, reason, reasons from bd.tasks where batch_id = %s", (batch,)).fetchall()}
    jim = rows[p["jim"]]
    assert (jim["kind"], jim["score"]) == ("followup", 70)
    assert jim["reasons"] == ["2 tries since the last live talk", "Key account"]
    assert jim["reason"] == "2 tries since the last live talk. Key account."
    assert rows[p["ann"]]["reasons"] == ["Never reached after 2 tries"]


def test_a_due_maintenance_person_keeps_their_own_3_day_rest(world, bd_db):
    """Maintenance stays as it was (#828 "Kept as they are"): the company's 3-day rest is for the BD
    picks. Quinn at QRS got a voicemail on Wed Nov 25, two days before the batch; Rae there is still
    due and gets her pinned follow-up, as before #828."""
    p = world["p"]
    mk_talk(bd_db, p["quinn"], "voicemail", "2026-11-25T16:00:00Z", "voicemail", world["rj"])
    done = weekly.run_due(bd_db, now=FRIDAY_RUN)
    batch = next(b["batch_id"] for b in done if b["owner_id"] == world["rj"])
    assert [(c, k) for c, k, _s in tasks_of(bd_db, batch) if k == "maintenance"] == [(p["rae"], "maintenance")]


def test_after_a_legacy_week_the_next_friday_batch_is_built_per_company(world, bd_db, bd_today):
    batch, _t = legacy_week(bd_db, world)
    bd_today("2026-12-04")
    done = weekly.run_due(bd_db, now="2026-12-04T16:00:00-06:00")
    rj_batch = next(b["batch_id"] for b in done if b["owner_id"] == world["rj"])
    cos = companies_of(bd_db, rj_batch)
    assert len(cos) == len(set(cos)) and world["co"]["abc"] in cos


def test_a_ten_more_row_and_a_friday_row_close_together(built, bd_db, bd_as_user, monkeypatch):
    """Give Me 10 More adds companies; done on one never moves the 10's count."""
    monkeypatch.setenv("BD_NOW", "2026-11-30T10:00:00-06:00")
    rj = as_(bd_as_user, built, "rj")
    r = rj.post("/api/bd/week/ten-more", json={})
    assert r.status_code == 200, r.text
    w = r.json()["week"]
    ghi = row_of(w, built["co"]["ghi"])
    assert ghi["section"] == "more" and ghi["task_ids"] and headline(w) == (0, 3, 1)
    r = rj.post("/api/bd/tasks/%d/done" % ghi["id"], json={})
    assert (r.json()["done_count"], r.json()["total"]) == (0, 3)


# ── Give Me 10 More ──────────────────────────────────────────────────────────────────────────
def test_give_me_10_more_adds_companies_not_on_the_lists_and_keeps_the_rest_per_company(
        built, bd_db, bd_as_user, monkeypatch):
    """On Mon Nov 30: GHI is out of its rest (Dee, 5 days ago) and comes on with Cal (65). STU Tile
    (Uma, Vic) and WXY Glass (Wyn) were added on Saturday; Vic got a voicemail on Sat Nov 28, so STU
    rests (Uma too). ABC was marked done with nothing logged: Sue never comes back for it."""
    monkeypatch.setenv("BD_NOW", "2026-11-30T10:00:00-06:00")
    rj_id, co = built["rj"], built["co"]
    stu, wxy = mk_company(bd_db, "STU Tile"), mk_company(bd_db, "WXY Glass")
    uma = mk_person(bd_db, stu, rj_id, "Uma Pell")
    vic = mk_person(bd_db, stu, rj_id, "Vic Rand")
    wyn = mk_person(bd_db, wxy, rj_id, "Wyn Sato")
    mk_talk(bd_db, vic, "voicemail", "2026-11-28T16:00:00Z", "voicemail", rj_id)
    rj = as_(bd_as_user, built, "rj")
    assert rj.post("/api/bd/tasks/%d/done" % built["t"]["jim"], json={}).status_code == 200
    r = rj.post("/api/bd/week/ten-more", json={})
    assert r.status_code == 200, r.text
    more = bd_db.execute("select id from bd.task_batches where kind = 'ten_more'").fetchone()["id"]
    assert tasks_of(bd_db, more) == [(built["p"]["cal"], "new", 65), (wyn, "new", 40)]
    assert uma not in [c for c, _k, _s in tasks_of(bd_db, more)]
    assert headline(r.json()["week"]) == (1, 3, 1)
    # Pressed again: nobody is left (STU still rests, everyone else is on a list in some state).
    r = rj.post("/api/bd/week/ten-more", json={})
    assert (r.status_code, r.json()["message"]) == (409, "Everyone on your list is already covered this week.")


def test_give_me_10_more_counts_ten_companies(world, bd_db, bd_today, bd_as_user):
    """Twelve companies with two never-reached people each and no list yet: ten companies, ten tasks."""
    bd_today(WEEK)
    for k in range(12):
        c = mk_company(bd_db, "Test Company %02d" % k)
        mk_person(bd_db, c, world["rj"], "Person %02dA" % k)
        mk_person(bd_db, c, world["rj"], "Person %02dB" % k)
    weekly.ten_more(bd_db, world["rj"], D(WEEK))
    more = bd_db.execute("select id from bd.task_batches where kind = 'ten_more'").fetchone()["id"]
    cos = companies_of(bd_db, more)
    # QRS's two due maintenance people head the list (one company), then 9 BD companies.
    kinds = [k for _c, k, _s in tasks_of(bd_db, more)]
    assert kinds.count("maintenance") == 2 and len(cos) == 9 and len(set(cos)) == 9


# ── the split is counted in companies ────────────────────────────────────────────────────────
def test_five_new_and_five_follow_up_companies(world, bd_db, bd_today):
    """Six "new" companies (two never-reached people each, 40) and six "follow-up" companies (one
    person met a year ago, 40, and one never-reached key account, 60). A follow-up company's best person
    is the never-reached one, yet the company is a follow-up: 5 + 5 companies, best first."""
    bd_today("2026-11-27")
    rj = mk_user(bd_db, "Lee Moss", "salesperson")["id"]
    new_cos, follow_cos = [], []
    for k in range(6):
        c = mk_company(bd_db, "New Co %d" % k)
        mk_person(bd_db, c, rj, "New %dA" % k)
        mk_person(bd_db, c, rj, "New %dB" % k)
        new_cos.append(c)
    for k in range(6):
        c = mk_company(bd_db, "Old Co %d" % k)
        met = mk_person(bd_db, c, rj, "Met %d" % k)
        mk_talk(bd_db, met, "meeting", "2025-11-04T16:00:00Z")
        mk_person(bd_db, c, rj, "Key %d" % k, importance=3)
        follow_cos.append(c)
    res = weekly.build_batch(bd_db, rj, D("2026-11-27"))
    rows = tasks_of(bd_db, res["batch"]["id"])
    assert [k for _c, k, _s in rows] == ["followup"] * 5 + ["new"] * 5
    assert [s for _c, _k, s in rows] == [60] * 5 + [40] * 5
    assert companies_of(bd_db, res["batch"]["id"]) == follow_cos[:5] + new_cos[:5]


def test_settings_split_is_in_companies(world, bd_db, bd_today):
    from bd import appsettings

    bd_today("2026-11-27")
    appsettings.store(bd_db, {"weekly": {"new_count": 2, "followup_count": 1}})
    res = weekly.build_batch(bd_db, world["rj"], D("2026-11-27"))
    p = world["p"]
    assert tasks_of(bd_db, res["batch"]["id"]) == [
        (p["quinn"], "maintenance", 40), (p["rae"], "maintenance", 40),
        (p["jim"], "followup", 60), (p["ann"], "new", 50), (p["pat"], "new", 40)]
    appsettings.store(bd_db, {"weekly": {"new_count": 1, "followup_count": 0}})
    res = weekly.build_batch(bd_db, world["rj"], D("2026-11-27"), week_start="2026-12-07")
    assert [k for _c, k, _s in tasks_of(bd_db, res["batch"]["id"])] == ["maintenance", "maintenance", "new"]


@pytest.mark.parametrize("seed", [828, 829, 830, 831])
def test_no_weeks_ten_ever_holds_two_rows_for_one_company(bd_db, bd_today, seed):
    """Random worlds: companies of one to four people, random live talks, misses and tries, some
    maintenance. Every BD pick of the Friday batch and of Give Me 10 More is a different company."""
    rnd = random.Random(seed)
    bd_today("2026-11-27")
    rj = mk_user(bd_db, "Rand Seller", "salesperson")["id"]
    for k in range(18):
        c = mk_company(bd_db, "Random Co %d" % k)
        cat = "maintenance" if rnd.random() < 0.15 else "bd"
        for j in range(rnd.randint(1, 4)):
            pid = mk_person(bd_db, c, rj, "Rand %d %d" % (k, j), category=cat, importance=rnd.choice([1, 1, 2, 3]))
            for _ in range(rnd.randint(0, 2)):
                kind, outcome = rnd.choice([("call", "answered"), ("call", "no_answer"), ("voicemail", "voicemail"),
                                            ("meeting", None), ("email", None)])
                day = dt.date(2026, 11, 27) - dt.timedelta(days=rnd.choice([1, 2, 5, 30, 200]))
                mk_talk(bd_db, pid, kind, "%sT16:00:00Z" % day.isoformat(), outcome)
    res = weekly.build_batch(bd_db, rj, D("2026-11-27"))
    cos = companies_of(bd_db, res["batch"]["id"])
    assert len(cos) == len(set(cos)) and len(cos) <= 10
    bd_today(WEEK)
    try:
        more = weekly.ten_more(bd_db, rj, D(WEEK))
    except weekly.NothingLeft:
        return
    extra = companies_of(bd_db, more["batch"]["id"])
    assert len(extra) == len(set(extra)) and not set(extra) & set(cos)


# ── maintenance: one row per company under Due now ───────────────────────────────────────────
def test_qrs_foods_is_one_row_under_due_now_until_both_are_followed_up(built, bd_as_user, monkeypatch):
    monkeypatch.setenv("BD_NOW", "2026-11-30T10:00:00-06:00")
    rj = as_(bd_as_user, built, "rj")
    co, p, t = built["co"], built["p"], built["t"]
    # Neither button takes a due row off by hand.
    for action in ("done", "snooze"):
        r = rj.post("/api/bd/tasks/%d/%s" % (t["rae"], action), json={})
        assert (r.status_code, r.json()["message"]) == (409, STAYS)
    assert rj.post("/api/bd/contacts/%d/interactions" % p["quinn"],
                   json={"kind": "call", "outcome": "answered"}).json()["task"]["id"] == t["quinn"]
    w = get_week(rj)
    qrs = row_of(w, co["qrs"])
    assert qrs["status"] == "open" and headline(w) == (0, 3, 1)      # Rae is still due
    assert rj.post("/api/bd/contacts/%d/interactions" % p["rae"],
                   json={"kind": "email", "summary": "Checking in."}).json()["task"]["id"] == t["rae"]
    w = get_week(rj)
    assert row_of(w, co["qrs"])["status"] == "done" and headline(w) == (0, 3, 0)


def test_due_now_counts_companies(world, bd_db, bd_today, bd_as_user):
    """Two maintenance companies with two due people each and one with one: Due now: 3."""
    bd_today("2026-11-27")
    rj = world["rj"]
    for name, n in (("TUV Dairy", 2), ("Ozark Mills", 1)):
        c = mk_company(bd_db, name)
        for k in range(n):
            mk_person(bd_db, c, rj, "%s %d" % (name.split()[0], k), category="maintenance")
    weekly.run_due(bd_db, now=FRIDAY_RUN)
    bd_today(WEEK)
    w = get_week(as_(bd_as_user, world, "rj"))
    due = [r for r in w["rows"] if r["section"] == "due"]
    assert [(r["company"]["name"], len(r["task_ids"])) for r in due] == [
        ("QRS Foods", 2), ("TUV Dairy", 2), ("Ozark Mills", 1)]
    assert headline(w) == (0, 3, 3)


# ── not the right person ─────────────────────────────────────────────────────────────────────
def test_not_the_right_person_keeps_the_row_open_while_someone_else_can_be_called(built, bd_db, bd_as_user):
    rj = as_(bd_as_user, built, "rj")
    p, t, co = built["p"], built["t"], built["co"]
    r = rj.post("/api/bd/tasks/%d/not-right-person" % t["jim"], json={"contact_id": p["jim"], "note": "Retired."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task"] == {"id": t["jim"], "status": "open", "done_at": None}
    assert body["contact"] == {"id": p["jim"], "confirmed": False, "notes": "Retired."}
    abc = row_of(get_week(rj), co["abc"])
    assert abc["status"] == "open" and abc["id"] == t["jim"]
    # Sue, who can still be called, is now first: the row's Call and Next up's Call dial her, not Jim.
    assert [(x["name"], x["confirmed"], x["not_right_person"]) for x in abc["people"]] == [
        ("Sue Baird", True, False), ("Jim Ash", False, True)]
    # Sue is not the right person either: nobody is left to call, so the row closes.
    r = rj.post("/api/bd/tasks/%d/not-right-person" % t["jim"], json={"contact_id": p["sue"]})
    assert r.status_code == 200 and r.json()["task"]["status"] == "done"
    assert r.json()["contact"]["id"] == p["sue"]
    w = get_week(rj)
    assert row_of(w, co["abc"])["status"] == "done" and headline(w) == (1, 3, 1)
    kinds = bd_db.execute("select kind, contact_id from bd.events order by id").fetchall()
    assert [(e["kind"], e["contact_id"]) for e in kinds] == [("unconfirmed", p["jim"]), ("unconfirmed", p["sue"])]


def test_not_the_right_person_with_nobody_else_closes_the_row(built, bd_as_user):
    rj = as_(bd_as_user, built, "rj")
    r = rj.post("/api/bd/tasks/%d/not-right-person" % built["t"]["pat"], json={})
    assert r.json()["task"]["status"] == "done"
    assert headline(get_week(rj)) == (1, 3, 1)


def test_someone_with_no_phone_is_nobody_left_to_call(built, bd_db, bd_as_user):
    mk_person(bd_db, built["co"]["xyz"], built["rj"], "Val Ward", phone=False)
    rj = as_(bd_as_user, built, "rj")
    r = rj.post("/api/bd/tasks/%d/not-right-person" % built["t"]["pat"], json={})
    assert r.json()["task"]["status"] == "done"


@pytest.mark.parametrize("value", ["pat", 999999, "x", True])
def test_not_the_right_person_names_someone_on_the_row(built, bd_db, bd_as_user, value):
    before = bd_db.execute("select confirmed from bd.contacts order by id").fetchall()
    cid = built["p"][value] if value == "pat" else value
    r = as_(bd_as_user, built, "rj").post("/api/bd/tasks/%d/not-right-person" % built["t"]["jim"],
                                          json={"contact_id": cid})
    assert r.status_code == 400, r.text
    assert r.json()["fields"] == {"contact_id": "Pick someone on this row."}
    assert bd_db.execute("select confirmed from bd.contacts order by id").fetchall() == before


# ── who may: every changed route, over HTTP ──────────────────────────────────────────────────
OK, NO = 200, 403
WHO = ("rj", "toby", "mona", "ava", "abe", "sky", "nobody")
ROLE_TABLE = [
    ("week", "GET", "/api/bd/week?owner={rj}&week_start=2026-11-30", None,
     {"rj": OK, "toby": NO, "mona": OK, "ava": NO, "abe": OK, "sky": OK, "nobody": NO}),
    ("ten_more", "POST", "/api/bd/week/ten-more", {"owner": "{rj}"},
     {"rj": OK, "toby": NO, "mona": NO, "ava": NO, "abe": OK, "sky": OK, "nobody": NO}),
    ("done", "POST", "/api/bd/tasks/{jim_t}/done", {},
     {"rj": OK, "toby": NO, "mona": NO, "ava": NO, "abe": OK, "sky": OK, "nobody": NO}),
    ("snooze", "POST", "/api/bd/tasks/{jim_t}/snooze", {},
     {"rj": OK, "toby": NO, "mona": NO, "ava": NO, "abe": OK, "sky": OK, "nobody": NO}),
    ("reopen", "POST", "/api/bd/tasks/{jim_t}/reopen", {},
     {"rj": OK, "toby": NO, "mona": NO, "ava": NO, "abe": OK, "sky": OK, "nobody": NO}),
    ("not_right_person", "POST", "/api/bd/tasks/{jim_t}/not-right-person", {"contact_id": "{sue}"},
     {"rj": OK, "toby": OK, "mona": NO, "ava": OK, "abe": OK, "sky": OK, "nobody": NO}),
    ("log_call", "POST", "/api/bd/contacts/{sue}/interactions", {"kind": "voicemail"},
     {"rj": OK, "toby": OK, "mona": NO, "ava": NO, "abe": OK, "sky": OK, "nobody": NO}),
]
ROLE_REFUSALS = {
    ("week", "toby"): "You can see only your own week.",
    ("week", "ava"): "The weekly list is the salesperson's.",
    ("ten_more", "toby"): "You can ask for more only on your own list.",
    ("done", "toby"): "That task is on someone else's list.",
    ("snooze", "toby"): "That task is on someone else's list.",
    ("reopen", "toby"): "That task is on someone else's list.",
    ("log_call", "ava"): "Assistants can add notes only.",
}
ROLE_CASES = [(label, m, path, body, who, want[who]) for label, m, path, body, want in ROLE_TABLE for who in WHO]


def _fill(value, ids):
    if isinstance(value, str):
        text = value.format(**ids)
        return int(text) if text.isdigit() and value.startswith("{") else text
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    return value


def _state(db):
    return db.execute(
        "select (select json_agg(t order by t.id) from (select id, batch_id, status, done_at, snoozed_until"
        "   from bd.tasks) t) as tasks, (select count(*) from bd.task_batches) as batches,"
        " (select json_agg(c order by c.id) from (select id, confirmed, notes from bd.contacts) c) as contacts,"
        " (select count(*) from bd.interactions) as interactions, (select count(*) from bd.events) as events"
        ).fetchone()


@pytest.mark.parametrize("label, method, path, body, who, status", ROLE_CASES,
                         ids=["%s-%s" % (c[0], c[4]) for c in ROLE_CASES])
def test_who_may_use_each_changed_route(built, bd_db, bd_as_user, bd_client, label, method, path, body, who, status):
    from _bd_conftest import bd_token_headers

    ids = {"rj": built["rj"], "jim_t": built["t"]["jim"], "sue": built["p"]["sue"]}
    if label == "reopen":        # a closed row to reopen
        bd_db.execute("update bd.tasks set status = 'done', done_at = bd.bd_now() where id = %s", (built["t"]["jim"],))
    url, payload = _fill(path, ids), _fill(body, ids)
    before = _state(bd_db)
    kw = {"json": payload} if payload is not None else {}
    if who == "nobody":
        r = bd_client.request(method, url, headers=bd_token_headers("new.hire@example.com"), **kw)
    else:
        r = as_(bd_as_user, built, who).request(method, url, **kw)
    assert r.status_code == status, (label, who, r.status_code, r.text)
    if status == NO:
        message = ("You don't have a BD role. Ask a BD admin to add you." if who == "nobody"
                   else ROLE_REFUSALS.get((label, who), "Your role can't do that."))
        assert r.json() == {"ok": False, "error": "forbidden", "message": message}
        assert _state(bd_db) == before
    elif label == "week":
        assert row_of(r.json()["week"], built["co"]["abc"])["score"] == 60     # the manager sees it too
