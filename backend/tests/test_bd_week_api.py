"""This Week through the proposal tool's app (#807): GET /api/bd/week, the four task buttons
(POST /api/bd/tasks/{id}/done | snooze | reopen | not-right-person), Give Me 10 More
(POST /api/bd/week/ten-more) and the admin's Run Friday batch now (POST /api/bd/admin/weekly/run).

Moved from BD's tests/test_week_api.py. BD compared one script of calls with its in-browser mock;
the mock is gone (#806), so the first block now checks the fixture seed's week (bd/ops/fixture_seed.py,
today Wed 2026-11-04) against values worked out by hand in the comments. The rest is BD's own: each
rule on data built in the test (who may, the 404s, 409s and 400s, the Friday-only headline, pace,
the weekly meeting box and Central-time edges), on the same paths under /api/bd/.

Everything is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import datetime as dt

import pytest

from bd import pace

AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE, GALE = 1, 2, 3, 4, 5, 6, 7
STAYS = "A maintenance follow-up stays on the list until you log a call, meeting, email or text."


# ── the fixture seed's week, worked by hand ─────────────────────────────────────────────────────
def test_averys_week_on_the_fixture_seed(bd_seeded, bd_as_user):
    """Avery's Friday batch 201 holds 301 (maintenance, Hal 30, open), 302 (follow-up, Dana 21,
    open) and 303 (new, Priya 25, done 18:00 UTC = 12:00 CST on Nov 3)."""
    r = bd_as_user(AVERY).get("/api/bd/week")
    assert r.status_code == 200, r.text
    w = r.json()["week"]
    assert (w["week_start"], w["week_end"]) == ("2026-11-02", "2026-11-08")
    assert w["owner"] == {"id": AVERY, "name": "Avery Quill"}
    # generated 21:00 UTC on Fri Oct 30, which is 16:00 CDT
    assert w["batch"] == {"id": 201, "kind": "friday", "owner": {"id": AVERY, "name": "Avery Quill"},
                          "week_start": "2026-11-02", "generated_at": "2026-10-30T16:00:00-05:00"}
    assert w["batches"] == [w["batch"]]
    assert [(t["id"], t["kind"], t["status"], t["contact"]["id"]) for t in w["tasks"]] == [
        (301, "maintenance", "open", 30), (302, "followup", "open", 21), (303, "new", "done", 25)]
    assert w["tasks"][2]["done_at"] == "2026-11-03T12:00:00-06:00"
    # "N of 10" is the BD tasks of the live Friday batch: 303 done of 302, 303. Due now: 301.
    assert (w["done_count"], w["total"], w["due_count"]) == (1, 2, 1)
    # Pace over Avery's contacts 21, 23, 25 (quarterly, 4 each), 27 (monthly override to Dec 31: 12),
    # 30 (maintenance, the default 3) and 31 (maintenance, 2): 29 a year. Touches this year: 101
    # (call answered, 21), 103 (meeting, 23), 106 (hosted, 30), 107 (call answered, 30) = 4.
    # Nov 4 is day 308 of 365: required = round(10 x 29 x 308 / 365) / 10 = 24.5; 4 / 29 = 14%;
    # 4 - 24.5 = -20.5, which Math.round takes to -20.
    assert w["pace"] == {"year": 2026, "as_of": "2026-11-04", "required_to_date": 24.5, "completed": 4,
                         "target_total": 29, "pct": 14, "delta": -20,
                         "label": "2026 BD Pace: 14% — 20 interactions behind pace"}
    # This week (Nov 2-4) Avery's contacts had a voicemail (102) and a no-answer call (104): no
    # meeting and no touch.
    assert w["weekly_meetings"] == {"count": 0, "goal": 5, "non_dsbc_website": 0, "min": 1}
    assert w["touches_this_week"] == 0


def test_blairs_week_on_the_fixture_seed(bd_seeded, bd_as_user):
    """Blair's batch 202: 304 (new, Rory 22, open) and 305 (follow-up, Sam 28, snoozed to Nov 10)."""
    w = bd_as_user(BLAIR).get("/api/bd/week").json()["week"]
    assert w["owner"] == {"id": BLAIR, "name": "Blair Fenn"}
    assert [(t["id"], t["status"], t["snoozed_until"]) for t in w["tasks"]] == [
        (304, "open", None), (305, "snoozed", "2026-11-10")]
    assert (w["done_count"], w["total"], w["due_count"]) == (0, 2, 0)


@pytest.mark.parametrize("who, query, owner", [
    (AVERY, "", AVERY), (AVERY, "?owner=1", AVERY),
    (DEVON, "", AVERY),                 # a manager: the first active salesperson
    (DEVON, "?owner=2", BLAIR), (EMERY, "", AVERY), (FRANKIE, "?owner=2", BLAIR),
    (DEVON, "?owner=7", GALE),          # a turned-off salesperson's week can still be read by id
])
def test_who_sees_which_week_on_the_fixture_seed(bd_seeded, bd_as_user, who, query, owner):
    r = bd_as_user(who).get("/api/bd/week" + query)
    assert r.status_code == 200, r.text
    assert r.json()["week"]["owner"]["id"] == owner


@pytest.mark.parametrize("who, query, status, message", [
    (AVERY, "?owner=2", 403, "You can see only your own week."),
    (CASEY, "", 403, "The weekly list is the salesperson's."),
    (DEVON, "?owner=3", 404, "Casey Moret has no weekly list. Only salespeople do."),
    (EMERY, "?owner=999", 404, "That user does not exist."),
    (AVERY, "?week_start=2026-11-03", 400, "week_start must be a Monday."),
])
def test_week_refusals_on_the_fixture_seed(bd_seeded, bd_as_user, who, query, status, message):
    r = bd_as_user(who).get("/api/bd/week" + query)
    assert (r.status_code, r.json()["message"]) == (status, message)


def test_the_task_buttons_on_the_fixture_seed(bd_seeded, bd_as_user, monkeypatch):
    monkeypatch.setenv("BD_NOW", "2026-11-04T10:15:00-06:00")
    avery = bd_as_user(AVERY)
    r = avery.post("/api/bd/tasks/302/done", json={})
    assert r.json() == {"ok": True, "task": {"id": 302, "batch_id": 201, "status": "done",
                                             "done_at": "2026-11-04T10:15:00-06:00"},
                        "done_count": 2, "total": 2}
    # 301 is Hal's maintenance task; Hal was followed up on Aug 20 (due again Dec 18), so the task
    # is stale and comes off like any other.
    r = avery.post("/api/bd/tasks/301/snooze", json={"reason": "Not due yet"})
    assert r.json() == {"ok": True, "task": {"id": 301, "status": "snoozed", "snoozed_until": "2026-11-09"},
                        "done_count": 2, "total": 2}
    r = avery.post("/api/bd/tasks/303/reopen", json={})
    assert r.json() == {"ok": True, "task": {"id": 303, "status": "open", "done_at": None, "snoozed_until": None}}
    # Blair's task is not Avery's.
    r = avery.post("/api/bd/tasks/304/done", json={})
    assert (r.status_code, r.json()["message"]) == (403, "That task is on someone else's list.")
    w = avery.get("/api/bd/week").json()["week"]
    assert [(t["id"], t["status"]) for t in w["tasks"]] == [(301, "snoozed"), (302, "done"), (303, "open")]
    assert (w["done_count"], w["total"], w["due_count"]) == (1, 2, 0)


def test_not_right_person_on_the_fixture_seed(bd_seeded, bd_as_user, bd_db, monkeypatch):
    monkeypatch.setenv("BD_NOW", "2026-11-04T10:20:00-06:00")
    r = bd_as_user(CASEY).post("/api/bd/tasks/304/not-right-person", json={"note": " Rory left the company. "})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "task": {"id": 304, "status": "done", "done_at": "2026-11-04T10:20:00-06:00"},
                        "contact": {"id": 22, "confirmed": False, "notes": "Rory left the company."}}
    ev = bd_db.execute("select kind, actor_id, contact_id, detail from bd.events").fetchall()
    assert ev == [{"kind": "unconfirmed", "actor_id": CASEY, "contact_id": 22, "detail": "Rory left the company."}]


def test_a_manual_run_builds_averys_next_week_from_the_fixture_seed(bd_seeded, bd_as_user, bd_db):
    """Next week's list for Avery, built on Wed Nov 4 (scores worked by hand, priority.py's table):
      * Nora (31), maintenance, never followed up: due, so pinned first. Never contacted +40, not
        confirmed +8 = 48.
      * Lena (27): never contacted +40, key account +20, not confirmed +8 = 68 (new).
      * Marisa (23): last live talk Jun 15, 142 days ago; 30 x 142 / 91.25 rounds to 47, capped at
        40; importance 2 +10; not confirmed +8 = 58 (follow-up).
      * Left out: Dana (21, voicemail Nov 2) and Priya (25, no answer Nov 3) were tried in the last 3
        days; Hal (30, maintenance) was followed up on Aug 20, so not due until Dec 18.
    The rollover snoozes this week's open tasks (301, 302) to the new Monday; 303 stays done."""
    r = bd_as_user(EMERY).post("/api/bd/admin/weekly/run", json={"owner": AVERY})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tasks_created"] == 3
    batch = body["batches"][0]
    assert (batch["kind"], batch["week_start"], batch["owner"]) == ("friday", "2026-11-09",
                                                                    {"id": AVERY, "name": "Avery Quill"})
    w = bd_as_user(AVERY).get("/api/bd/week?week_start=2026-11-09").json()["week"]
    assert [(t["contact"]["id"], t["kind"], t["score"]) for t in w["tasks"]] == [
        (31, "maintenance", 48), (27, "new", 68), (23, "followup", 58)]
    assert w["tasks"][0]["reasons"] == ["No follow-up logged yet", "Never contacted",
                                        "Needs confirming: still the right person?"]
    assert (w["done_count"], w["total"], w["due_count"]) == (0, 2, 1)
    rows = {t["id"]: (t["status"], str(t["snoozed_until"]))
            for t in bd_db.execute("select id, status, snoozed_until from bd.tasks where batch_id = 201")}
    assert rows == {301: ("snoozed", "2026-11-09"), 302: ("snoozed", "2026-11-09"), 303: ("done", "None")}
    # Once a week: a second run is refused.
    r = bd_as_user(EMERY).post("/api/bd/admin/weekly/run", json={"owner": AVERY})
    assert (r.status_code, r.json()["message"]) == (409, "A Friday batch already exists for Avery Quill that week.")


# ── helpers for hand-built data ──────────────────────────────────────────────────────────────
def mk_user(db, name, role, active=True):
    email = "%s@example.com" % name.lower().replace(" ", ".")
    return db.execute("insert into bd.users (email, name, role, active) values (%s, %s, %s, %s) returning *",
                      (email, name, role, active)).fetchone()


_n = [0]


def mk_contact(db, owner_id, name=None, category="bd", frequency=None, lead_source="Current Account",
               notes=None, archived=False, confirmed=True):
    _n[0] += 1
    k = _n[0]
    co = db.execute("insert into bd.companies (name, normalized_name) values (%s, %s) returning id",
                    ("Test Company %d" % k, "test company %d" % k)).fetchone()
    return db.execute(
        "insert into bd.contacts (company_id, name, phone, email, category, frequency_per_year, owner_id,"
        " lead_source, notes, confirmed, archived_at)"
        " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, case when %s then bd.bd_now() end) returning id",
        (co["id"], name or "Person %d" % k, "816-555-01%02d" % (k % 100), "person%d@example.com" % k,
         category, frequency, owner_id, lead_source, notes or "", confirmed, archived)).fetchone()["id"]


def mk_batch(db, owner_id, week_start="2026-11-02", kind="friday"):
    return db.execute("insert into bd.task_batches (owner_id, week_start, kind, generated_at)"
                      " values (%s, %s, %s, '2026-10-30T16:00:00-05:00') returning id",
                      (owner_id, week_start, kind)).fetchone()["id"]


def mk_task(db, batch_id, contact_id, status="open", kind="followup", done_at=None, snoozed_until=None):
    return db.execute(
        "insert into bd.tasks (batch_id, contact_id, kind, reason, reasons, score, status, done_at, snoozed_until)"
        " values (%s, %s, %s, 'Key account.', array['Key account'], 50, %s, %s, %s) returning id",
        (batch_id, contact_id, kind, status, done_at, snoozed_until)).fetchone()["id"]


def mk_interaction(db, contact_id, kind, at, outcome=None):
    return db.execute(
        "insert into bd.interactions (contact_id, kind, outcome, occurred_at, summary)"
        " values (%s, %s, %s, %s, 'Test.') returning id", (contact_id, kind, outcome, at)).fetchone()["id"]


@pytest.fixture
def team(bd_db, bd_today):
    """Two salespeople (Sam, Sue), an assistant, a manager, an admin; today Wed 2026-11-04."""
    bd_today("2026-11-04")
    return {
        "sam": mk_user(bd_db, "Sam Seller", "salesperson"),
        "sue": mk_user(bd_db, "Sue Seller", "salesperson"),
        "amy": mk_user(bd_db, "Amy Assist", "assistant"),
        "max": mk_user(bd_db, "Max Manager", "manager"),
        "ada": mk_user(bd_db, "Ada Admin", "admin"),
    }


def as_(bd_as_user, row):
    return bd_as_user(row["email"])


# ── GET /api/bd/week ─────────────────────────────────────────────────────────────────────────
def test_no_token_is_401(bd_client):
    for method, path in (("GET", "/api/bd/week"), ("POST", "/api/bd/tasks/1/done"),
                         ("POST", "/api/bd/tasks/1/snooze"), ("POST", "/api/bd/tasks/1/reopen"),
                         ("POST", "/api/bd/tasks/1/not-right-person"), ("POST", "/api/bd/week/ten-more"),
                         ("POST", "/api/bd/admin/weekly/run")):
        r = bd_client.request(method, path)
        assert r.status_code == 401, (method, path, r.text)


def test_before_the_first_batch_the_week_is_empty(team, bd_as_user, bd_db):
    mk_contact(bd_db, team["sam"]["id"])
    r = as_(bd_as_user, team["sam"]).get("/api/bd/week")
    assert r.status_code == 200, r.text
    week = r.json()["week"]
    assert week["batch"] is None and week["batches"] == [] and week["tasks"] == []
    assert week["done_count"] == 0 and week["total"] == 0
    assert week["week_start"] == "2026-11-02" and week["week_end"] == "2026-11-08"
    assert week["owner"] == {"id": team["sam"]["id"], "name": "Sam Seller"}
    assert week["weekly_meetings"] == {"count": 0, "goal": 5, "non_dsbc_website": 0, "min": 1}
    assert week["touches_this_week"] == 0
    assert week["due_count"] == 0
    assert week["rows"] == []
    assert set(week) == {"week_start", "week_end", "owner", "batch", "batches", "tasks", "rows", "done_count",
                         "total", "due_count", "pace", "weekly_meetings", "touches_this_week"}


def test_the_week_follows_central_time(team, bd_as_user, bd_today):
    # Sunday 2026-11-08 is still last week until Monday in Central.
    bd_today("2026-11-08")
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]
    assert (w["week_start"], w["week_end"]) == ("2026-11-02", "2026-11-08")
    bd_today("2026-11-09")
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]
    assert (w["week_start"], w["week_end"]) == ("2026-11-09", "2026-11-15")
    assert w["pace"]["as_of"] == "2026-11-09"


def test_friday_counts_only_and_ten_more_batches_follow(team, bd_as_user, bd_db):
    db = bd_db
    sam = team["sam"]["id"]
    fri = mk_batch(db, sam)
    c = [mk_contact(db, sam) for _ in range(5)]
    t1 = mk_task(db, fri, c[0], "done", done_at="2026-11-02T09:30:00-06:00")
    t2 = mk_task(db, fri, c[1], "snoozed", snoozed_until="2026-11-09")
    t3 = mk_task(db, fri, c[2])
    more = db.execute("insert into bd.task_batches (owner_id, week_start, kind, generated_at)"
                      " values (%s, '2026-11-02', 'ten_more', '2026-11-04T10:00:00-06:00') returning id",
                      (sam,)).fetchone()["id"]
    t4 = mk_task(db, more, c[3], "done", done_at="2026-11-04T10:30:00-06:00")
    t5 = mk_task(db, more, c[4])
    # Another week and another owner never show up.
    mk_task(db, mk_batch(db, sam, "2026-10-26"), c[0], "done")
    mk_task(db, mk_batch(db, team["sue"]["id"]), mk_contact(db, team["sue"]["id"]))

    w = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]
    assert [b["id"] for b in w["batches"]] == [fri, more]
    assert w["batch"]["id"] == more and w["batch"]["kind"] == "ten_more"
    assert w["batch"]["generated_at"] == "2026-11-04T10:00:00-06:00"
    assert w["batches"][0]["generated_at"] == "2026-10-30T16:00:00-05:00"
    assert [t["id"] for t in w["tasks"]] == [t1, t2, t3, t4, t5]
    # "N of 10" is the Friday batch only: 1 done of 3 (a snoozed task stays in the total).
    assert (w["done_count"], w["total"]) == (1, 3)
    task = w["tasks"][0]
    assert set(task) == {"id", "batch_id", "contact", "kind", "reason", "reasons", "score", "status",
                         "done_at", "snoozed_until"}
    assert task["reasons"] == ["Key account"] and task["score"] == 50 and task["kind"] == "followup"
    assert set(task["contact"]) == {"id", "name", "title", "company", "phone", "phone_e164", "email",
                                    "category", "confirmed", "lead_source", "last_live_at", "cadence_status"}
    assert w["tasks"][1]["snoozed_until"] == "2026-11-09"

    # Done on a ten_more task: the headline does not move.
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/done" % t5, json={})
    assert r.status_code == 200 and (r.json()["done_count"], r.json()["total"]) == (1, 3)
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/done" % t3, json={})
    assert (r.json()["done_count"], r.json()["total"]) == (2, 3)


# ── maintenance tasks: the counts and due_count ─────────────────────────────────────────────
def _maintenance_week(db, team, week_start="2026-11-02"):
    """Sam's week: a live Friday batch of two maintenance tasks (one open, one done) and three BD
    tasks (done, snoozed, open), plus a ten_more batch with one open maintenance task and one open BD
    task. Returns the ids."""
    sam = team["sam"]["id"]
    fri = mk_batch(db, sam, week_start)
    more = db.execute("insert into bd.task_batches (owner_id, week_start, kind, generated_at)"
                      " values (%s, %s, 'ten_more', '2026-11-04T10:00:00-06:00') returning id",
                      (sam, week_start)).fetchone()["id"]

    def m():
        return mk_contact(db, sam, category="maintenance", frequency=3)

    ids = {
        "m_open": mk_task(db, fri, m(), "open", kind="maintenance"),
        "m_done": mk_task(db, fri, m(), "done", kind="maintenance", done_at="2026-11-03T09:00:00-06:00"),
        "bd_done": mk_task(db, fri, mk_contact(db, sam), "done", done_at="2026-11-03T09:30:00-06:00"),
        "bd_snoozed": mk_task(db, fri, mk_contact(db, sam), "snoozed", snoozed_until="2026-11-09"),
        "bd_open": mk_task(db, fri, mk_contact(db, sam), "open"),
        "more_m_open": mk_task(db, more, m(), "open", kind="maintenance"),
        "more_bd_open": mk_task(db, more, mk_contact(db, sam), "open"),
    }
    ids["fri"], ids["more"] = fri, more
    return ids


def _contact_of(db, task_id):
    return db.execute("select contact_id from bd.tasks where id = %s", (task_id,)).fetchone()["contact_id"]


def test_counts_leave_maintenance_out(team, bd_as_user, bd_db):
    """done_count and total are the live Friday batch's BD tasks: the maintenance ones, done or
    not, are not part of 'N of 10'; the buttons answer with the same BD-only numbers."""
    from bd.routers.week import friday_counts

    ids = _maintenance_week(bd_db, team)
    sam = as_(bd_as_user, team["sam"])
    w = sam.get("/api/bd/week").json()["week"]
    assert (w["done_count"], w["total"]) == (1, 3)                      # BD only: 1 done of 3
    assert [t["kind"] for t in w["tasks"]].count("maintenance") == 3    # but they are all listed
    r = sam.post("/api/bd/tasks/%d/done" % ids["bd_open"], json={})
    assert r.status_code == 200 and (r.json()["done_count"], r.json()["total"]) == (2, 3)
    r = sam.post("/api/bd/tasks/%d/snooze" % ids["more_bd_open"], json={})
    assert (r.json()["done_count"], r.json()["total"]) == (2, 3)        # a ten_more task: same
    r = sam.post("/api/bd/tasks/%d/reopen" % ids["bd_open"], json={})
    assert r.status_code == 200
    assert friday_counts(bd_db, team["sam"]["id"], dt.date(2026, 11, 2)) == {"done_count": 1, "total": 3}
    # Only maintenance tasks on the live Friday batch: 0 of 0.
    sue = team["sue"]["id"]
    fri = mk_batch(bd_db, sue)
    mk_task(bd_db, fri, mk_contact(bd_db, sue, category="maintenance", frequency=3), "done", kind="maintenance")
    w = as_(bd_as_user, team["sue"]).get("/api/bd/week").json()["week"]
    assert (w["done_count"], w["total"], w["due_count"]) == (0, 0, 0)
    assert len(w["tasks"]) == 1


def test_due_count(team, bd_as_user, bd_db):
    """due_count = open maintenance tasks on the week's lists, any batch; done, snoozed, another week
    and another owner do not count."""
    db = bd_db
    ids = _maintenance_week(db, team)
    sam = as_(bd_as_user, team["sam"])
    assert sam.get("/api/bd/week").json()["week"]["due_count"] == 2        # m_open + more_m_open
    mk_task(db, mk_batch(db, team["sam"]["id"], "2026-10-26"),
            mk_contact(db, team["sam"]["id"], category="maintenance", frequency=3), "open", kind="maintenance")
    mk_task(db, mk_batch(db, team["sue"]["id"]), mk_contact(db, team["sue"]["id"], category="maintenance",
                                                            frequency=3), "open", kind="maintenance")
    assert sam.get("/api/bd/week").json()["week"]["due_count"] == 2
    assert sam.get("/api/bd/week?week_start=2026-10-26").json()["week"]["due_count"] == 1
    assert as_(bd_as_user, team["sue"]).get("/api/bd/week").json()["week"]["due_count"] == 1
    # A manager sees the same number; a week with no list says 0.
    assert as_(bd_as_user, team["max"]).get(
        "/api/bd/week?owner=%d" % team["sam"]["id"]).json()["week"]["due_count"] == 2
    assert sam.get("/api/bd/week?week_start=2026-11-09").json()["week"]["due_count"] == 0
    # "Not the right person" takes one off; so does logging an email (a maintenance task closes on any
    # kind but a note).
    r = sam.post("/api/bd/tasks/%d/not-right-person" % ids["m_open"], json={})
    assert r.status_code == 200
    assert sam.get("/api/bd/week").json()["week"]["due_count"] == 1
    cid = _contact_of(db, ids["more_m_open"])
    r = sam.post("/api/bd/contacts/%d/interactions" % cid, json={"kind": "note", "summary": "Thinking."})
    assert r.status_code == 200 and r.json()["task"] is None
    assert sam.get("/api/bd/week").json()["week"]["due_count"] == 1
    r = sam.post("/api/bd/contacts/%d/interactions" % cid, json={"kind": "email", "summary": "Sent the update."})
    assert r.status_code == 200 and r.json()["task"]["id"] == ids["more_m_open"]
    w = sam.get("/api/bd/week").json()["week"]
    assert w["due_count"] == 0 and (w["done_count"], w["total"]) == (1, 3)
    # Reopen is unchanged: a done maintenance task can be reopened and is due again.
    assert sam.post("/api/bd/tasks/%d/reopen" % ids["m_done"], json={}).status_code == 200
    assert sam.get("/api/bd/week").json()["week"]["due_count"] == 1


def test_snooze_and_done_refuse_a_maintenance_task(team, bd_as_user, bd_db):
    db = bd_db
    ids = _maintenance_week(db, team)
    sam = as_(bd_as_user, team["sam"])
    before = db.execute("select id, status, done_at, snoozed_until, snooze_reason from bd.tasks order by id").fetchall()
    for action in ("snooze", "done"):
        r = sam.post("/api/bd/tasks/%d/%s" % (ids["m_open"], action), json={})
        assert r.status_code == 409, (action, r.text)
        assert r.json() == {"ok": False, "error": "conflict", "message": STAYS}
        # the rule is about the kind, not the state: a done or snoozed one gets the same sentence
        r = sam.post("/api/bd/tasks/%d/%s" % (ids["m_done"], action), json={})
        assert r.status_code == 409 and r.json()["message"] == STAYS
        # an admin on Sam's list gets it too; the other roles' refusals still come first
        r = as_(bd_as_user, team["ada"]).post("/api/bd/tasks/%d/%s" % (ids["more_m_open"], action), json={})
        assert r.status_code == 409 and r.json()["message"] == STAYS
        for who in ("amy", "max"):
            r = as_(bd_as_user, team[who]).post("/api/bd/tasks/%d/%s" % (ids["m_open"], action), json={})
            assert r.status_code == 403 and r.json()["message"] == "Your role can't do that."
        r = as_(bd_as_user, team["sue"]).post("/api/bd/tasks/%d/%s" % (ids["m_open"], action), json={})
        assert r.status_code == 403 and r.json()["message"] == "That task is on someone else's list."
        r = as_(bd_as_user, team["ada"]).post("/api/bd/tasks/99999/%s" % action, json={})
        assert r.status_code == 404
    after = db.execute("select id, status, done_at, snoozed_until, snooze_reason from bd.tasks order by id").fetchall()
    assert after == before
    # BD tasks still work, on the live batch and on a ten_more batch.
    r = sam.post("/api/bd/tasks/%d/done" % ids["bd_open"], json={})
    assert r.status_code == 200 and r.json()["task"]["status"] == "done"
    r = sam.post("/api/bd/tasks/%d/snooze" % ids["more_bd_open"], json={"reason": "Out of office"})
    assert r.status_code == 200 and r.json()["task"]["status"] == "snoozed"
    # "Not the right person" still works on a maintenance task (it flags the contact and closes it).
    r = sam.post("/api/bd/tasks/%d/not-right-person" % ids["m_open"], json={"note": "Moved on."})
    assert r.status_code == 200 and r.json()["task"]["status"] == "done"
    assert r.json()["contact"]["confirmed"] is False
    # Reopen is unchanged, and a reopened maintenance task is again refused.
    r = sam.post("/api/bd/tasks/%d/reopen" % ids["m_open"], json={})
    assert r.status_code == 200 and r.json()["task"]["status"] == "open"
    r = sam.post("/api/bd/tasks/%d/reopen" % ids["m_open"], json={})
    assert r.status_code == 409 and r.json()["message"] == "That task is already open."
    assert sam.post("/api/bd/tasks/%d/snooze" % ids["m_open"], json={}).status_code == 409


def test_a_stale_maintenance_task_can_be_taken_off(team, bd_as_user, bd_db):
    """The 409 is for a task whose contact is STILL due. One whose contact is no longer due (a
    contact that became a BD contact, or one reopened after its follow-up) is not pinned."""
    db = bd_db
    ids = _maintenance_week(db, team)
    sam = as_(bd_as_user, team["sam"])
    assert sam.post("/api/bd/tasks/%d/snooze" % ids["m_open"], json={}).status_code == 409
    assert sam.post("/api/bd/tasks/%d/done" % ids["more_m_open"], json={}).status_code == 409
    db.execute("update bd.contacts set category = 'bd' where id = %s", (_contact_of(db, ids["m_open"]),))
    r = sam.post("/api/bd/tasks/%d/snooze" % ids["m_open"], json={"reason": "Now BD"})
    assert r.status_code == 200 and r.json()["task"]["status"] == "snoozed"
    mk_interaction(db, _contact_of(db, ids["more_m_open"]), "email", "2026-11-03T09:00:00-06:00")
    r = sam.post("/api/bd/tasks/%d/done" % ids["more_m_open"], json={})
    assert r.status_code == 200 and r.json()["task"]["status"] == "done"
    assert sam.get("/api/bd/week").json()["week"]["due_count"] == 0
    mk_interaction(db, _contact_of(db, ids["m_done"]), "meeting", "2026-11-03T10:00:00-06:00")
    assert sam.post("/api/bd/tasks/%d/reopen" % ids["m_done"], json={}).status_code == 200
    assert sam.post("/api/bd/tasks/%d/done" % ids["m_done"], json={}).status_code == 200


def test_changing_the_owner_keeps_the_pin_on_one_list(team, bd_as_user, bd_db):
    """A contact with an open maintenance task changes hands. The old owner's task is snoozed; the
    new owner gets the pin from Give Me 10 More, so one list shows it and one task is open."""
    db = bd_db
    ids = _maintenance_week(db, team)
    sam, sue, ada = (as_(bd_as_user, team[k]) for k in ("sam", "sue", "ada"))
    cid = _contact_of(db, ids["m_open"])
    r = ada.patch("/api/bd/contacts/%d" % cid, json={"owner_id": team["sue"]["id"]})
    assert r.status_code == 200, r.text
    t = db.execute("select status, snoozed_until from bd.tasks where id = %s", (ids["m_open"],)).fetchone()
    assert (t["status"], str(t["snoozed_until"])) == ("snoozed", "2026-11-09")
    assert db.execute("select status from bd.tasks where id = %s", (ids["more_m_open"],)).fetchone()["status"] == "open"
    assert sam.get("/api/bd/week").json()["week"]["due_count"] == 1
    r = sue.post("/api/bd/week/ten-more", json={})
    assert r.status_code == 200, r.text
    w = r.json()["week"]
    assert w["due_count"] == 1 and w["tasks"][0]["kind"] == "maintenance" and w["tasks"][0]["contact"]["id"] == cid
    assert db.execute("select count(*) as n from bd.tasks where contact_id = %s and kind = 'maintenance'"
                      " and status = 'open'", (cid,)).fetchone()["n"] == 1
    assert ada.patch("/api/bd/contacts/%d" % cid, json={"owner_id": team["sue"]["id"]}).status_code == 200
    assert sue.get("/api/bd/week").json()["week"]["due_count"] == 1


def test_who_may_see_which_week(team, bd_as_user, bd_db):
    sam, sue = team["sam"], team["sue"]
    mk_batch(bd_db, sue["id"])
    assert as_(bd_as_user, sam).get("/api/bd/week").json()["week"]["owner"]["id"] == sam["id"]
    assert as_(bd_as_user, sam).get("/api/bd/week?owner=%d" % sam["id"]).status_code == 200
    r = as_(bd_as_user, sam).get("/api/bd/week?owner=%d" % sue["id"])
    assert r.status_code == 403 and r.json() == {"ok": False, "error": "forbidden",
                                                 "message": "You can see only your own week."}
    for who in ("max", "ada"):
        c = as_(bd_as_user, team[who])
        assert c.get("/api/bd/week").json()["week"]["owner"]["id"] == sam["id"]
        w = c.get("/api/bd/week?owner=%d" % sue["id"]).json()["week"]
        assert w["owner"] == {"id": sue["id"], "name": "Sue Seller"} and w["batch"]["kind"] == "friday"
    r = as_(bd_as_user, team["amy"]).get("/api/bd/week")
    assert r.status_code == 403 and r.json() == {"ok": False, "error": "forbidden",
                                                 "message": "The weekly list is the salesperson's."}


def test_the_default_owner_skips_an_inactive_salesperson(team, bd_as_user, bd_db):
    bd_db.execute("update bd.users set active = false where id = %s", (team["sam"]["id"],))
    w = as_(bd_as_user, team["max"]).get("/api/bd/week").json()["week"]
    assert w["owner"]["id"] == team["sue"]["id"]
    w = as_(bd_as_user, team["max"]).get("/api/bd/week?owner=%d" % team["sam"]["id"]).json()["week"]
    assert w["owner"]["id"] == team["sam"]["id"]


@pytest.mark.parametrize("owner", ["999999", "abc", "-1", "99999999999999999999999"])
def test_an_unknown_owner_is_404(team, bd_as_user, owner):
    r = as_(bd_as_user, team["max"]).get("/api/bd/week", params={"owner": owner})
    assert r.status_code == 404 and r.json() == {"ok": False, "error": "not_found",
                                                 "message": "That user does not exist."}


@pytest.mark.parametrize("who", ["amy", "max", "ada"])
def test_an_owner_who_is_not_a_salesperson_is_404(team, bd_as_user, who):
    r = as_(bd_as_user, team["ada"]).get("/api/bd/week?owner=%d" % team[who]["id"])
    assert r.status_code == 404
    assert r.json()["message"] == "%s has no weekly list. Only salespeople do." % team[who]["name"]


@pytest.mark.parametrize("value", ["2026-11-03", "2026-11-08", "nope", "2026-13-02", "2026-11-2",
                                   "2026-11-02T00:00:00"])
def test_week_start_must_be_a_monday(team, bd_as_user, value):
    r = as_(bd_as_user, team["sam"]).get("/api/bd/week", params={"week_start": value})
    assert r.status_code == 400
    assert r.json() == {"ok": False, "error": "bad_request", "message": "week_start must be a Monday.",
                        "fields": {"week_start": "Pick a Monday."}}


def test_an_earlier_week_shows_that_weeks_batch(team, bd_as_user, bd_db):
    sam = team["sam"]["id"]
    old = mk_batch(bd_db, sam, "2026-10-26")
    mk_task(bd_db, old, mk_contact(bd_db, sam), "done")
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week?week_start=2026-10-26").json()["week"]
    assert w["batch"]["id"] == old and (w["done_count"], w["total"]) == (1, 1)
    assert (w["week_start"], w["week_end"]) == ("2026-10-26", "2026-11-01")
    assert w["pace"]["as_of"] == "2026-11-04"


# ── pace and the meeting box ─────────────────────────────────────────────────────────────────
def test_pace_counts_every_owned_contact_and_only_touches(team, bd_as_user, bd_db):
    db = bd_db
    sam = team["sam"]["id"]
    a = mk_contact(db, sam, frequency=6)                      # BD: the stored 6 is not used
    db.execute("update bd.contacts set cadence_override = 'monthly', cadence_override_until = '2026-12-31'"
               " where id = %s", (a,))                        # a BD number is derived: monthly = 12
    b = mk_contact(db, sam, category="maintenance")          # default 3
    c = mk_contact(db, sam)                                   # the global cadence (quarterly) = 4
    gone = mk_contact(db, sam, frequency=12, archived=True)  # archived: not counted
    other = mk_contact(db, team["sue"]["id"], frequency=10)
    for cid in (a, b, c, gone, other):
        mk_interaction(db, cid, "call", "2026-03-02T10:00:00-06:00", "answered")
    mk_interaction(db, a, "meeting", "2026-05-02T10:00:00-05:00")
    mk_interaction(db, a, "hosted", "2026-06-02T10:00:00-05:00")
    mk_interaction(db, a, "call", "2026-06-03T10:00:00-05:00", "meeting_set")
    mk_interaction(db, a, "voicemail", "2026-06-04T10:00:00-05:00", "voicemail")
    mk_interaction(db, a, "call", "2026-06-05T10:00:00-05:00", "no_answer")
    for kind in ("email", "sms", "note"):
        mk_interaction(db, a, kind, "2026-06-06T10:00:00-05:00")
    mk_interaction(db, a, "call", "2025-12-31T23:30:00-06:00", "answered")   # last year (Central)
    mk_interaction(db, a, "call", "2026-11-05T09:00:00-06:00", "answered")   # tomorrow
    got = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]["pace"]
    # 12 + 3 + 4 = 19 a year; touches: 3 calls answered in March + meeting + hosted + meeting_set = 6.
    # Day 308 of 365: round(10 x 19 x 308 / 365) / 10 = 16.0; 6 / 19 = 32%; 6 - 16 = -10.
    assert got["target_total"] == 19 and got["completed"] == 6
    assert got["required_to_date"] == 16.0 and got["pct"] == 32 and got["delta"] == -10
    assert got == pace.pace_from_totals(19, 6, "2026-11-04")


def test_the_meeting_box_and_touches_this_week(team, bd_as_user, bd_db, bd_today):
    db = bd_db
    sam = team["sam"]["id"]
    own = mk_contact(db, sam, lead_source="Current Account")
    dsbc = mk_contact(db, sam, lead_source="DSBC Sales")
    web = mk_contact(db, sam, lead_source="Website Lead")
    misc = mk_contact(db, sam, lead_source="Other/Misc")
    gone = mk_contact(db, sam, archived=True)
    other = mk_contact(db, team["sue"]["id"])
    mk_interaction(db, own, "meeting", "2026-11-02T00:10:00-06:00")          # Monday just after midnight
    mk_interaction(db, dsbc, "hosted", "2026-11-03T12:00:00-06:00")
    mk_interaction(db, web, "call", "2026-11-03T13:00:00-06:00", "meeting_set")
    mk_interaction(db, misc, "meeting", "2026-11-04T08:00:00-06:00")
    mk_interaction(db, own, "call", "2026-11-04T09:00:00-06:00", "answered")  # a touch, not a meeting
    mk_interaction(db, own, "voicemail", "2026-11-04T09:30:00-06:00", "voicemail")
    mk_interaction(db, own, "email", "2026-11-04T09:40:00-06:00")
    mk_interaction(db, own, "meeting", "2026-11-01T23:59:00-06:00")          # Sunday: last week
    mk_interaction(db, own, "meeting", "2026-11-02T05:30:00Z")               # 23:30 Sun Central: last week
    mk_interaction(db, own, "meeting", "2026-11-06T10:00:00-06:00")          # Friday: not yet
    mk_interaction(db, gone, "meeting", "2026-11-03T10:00:00-06:00")
    mk_interaction(db, other, "meeting", "2026-11-03T10:00:00-06:00")
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]
    assert w["weekly_meetings"] == {"count": 4, "goal": 5, "non_dsbc_website": 2, "min": 1}
    assert w["touches_this_week"] == 5
    mk_interaction(db, own, "meeting", "2026-11-09T05:30:00Z")
    bd_today("2026-11-08")
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]
    assert w["weekly_meetings"]["count"] == 6 and w["touches_this_week"] == 7
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week?week_start=2026-11-16").json()["week"]
    assert w["weekly_meetings"]["count"] == 0 and w["touches_this_week"] == 0


def test_the_meeting_box_follows_settings(team, bd_as_user, bd_db):
    import json
    bd_db.execute("insert into bd.settings (key, value) values ('weekly_meeting_goal', %s::jsonb),"
                  " ('non_dsbc_website_min', %s::jsonb)", (json.dumps(7), json.dumps(2)))
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]
    assert w["weekly_meetings"]["goal"] == 7 and w["weekly_meetings"]["min"] == 2


# ── the task buttons ─────────────────────────────────────────────────────────────────────────
@pytest.fixture
def sams_list(team, bd_db):
    db = bd_db
    sam = team["sam"]["id"]
    fri = mk_batch(db, sam)
    ids = {s: mk_task(db, fri, mk_contact(db, sam, notes="Met at the expo." if s == "open2" else None),
                      s[:-1] if s[-1].isdigit() else s)
           for s in ("open1", "open2", "done1", "snoozed1")}
    db.execute("update bd.tasks set done_at = '2026-11-03T09:00:00-06:00' where id = %s", (ids["done1"],))
    db.execute("update bd.tasks set snoozed_until = '2026-11-09' where id = %s", (ids["snoozed1"],))
    ids["sue"] = mk_task(db, mk_batch(db, team["sue"]["id"]), mk_contact(db, team["sue"]["id"]))
    return ids


def test_done(team, sams_list, bd_as_user, bd_db, monkeypatch):
    monkeypatch.setenv("BD_NOW", "2026-11-04T10:15:00-06:00")
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/done" % sams_list["open1"], json={})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "task": {"id": sams_list["open1"], "batch_id": r.json()["task"]["batch_id"],
                                             "status": "done", "done_at": "2026-11-04T10:15:00-06:00"},
                        "done_count": 2, "total": 4}
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/done" % sams_list["open1"])
    assert r.status_code == 409 and r.json() == {"ok": False, "error": "conflict",
                                                 "message": "That task is already done."}
    # A snoozed task can be marked done; that clears the snooze.
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/done" % sams_list["snoozed1"])
    assert r.status_code == 200 and r.json()["done_count"] == 3
    row = bd_db.execute("select status, snoozed_until from bd.tasks where id = %s", (sams_list["snoozed1"],)).fetchone()
    assert row == {"status": "done", "snoozed_until": None}


def test_done_stamps_the_central_offset_of_the_moment(team, sams_list, bd_as_user, monkeypatch, bd_today):
    bd_today(None)
    monkeypatch.setenv("BD_NOW", "2026-10-30T21:00:00Z")      # CDT: 16:00 -05:00
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/done" % sams_list["open1"])
    assert r.json()["task"]["done_at"] == "2026-10-30T16:00:00-05:00"


@pytest.mark.parametrize("action", ["done", "snooze", "reopen"])
def test_only_the_salesperson_on_the_list_or_an_admin(team, sams_list, bd_as_user, action):
    tid = sams_list["open1"] if action != "reopen" else sams_list["done1"]
    for who in ("amy", "max"):
        r = as_(bd_as_user, team[who]).post("/api/bd/tasks/%d/%s" % (tid, action), json={})
        assert r.status_code == 403 and r.json() == {"ok": False, "error": "forbidden",
                                                     "message": "Your role can't do that."}
    r = as_(bd_as_user, team["sue"]).post("/api/bd/tasks/%d/%s" % (tid, action), json={})
    assert r.status_code == 403 and r.json()["message"] == "That task is on someone else's list."
    r = as_(bd_as_user, team["ada"]).post("/api/bd/tasks/%d/%s" % (tid, action), json={})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("action", ["done", "snooze", "reopen", "not-right-person"])
@pytest.mark.parametrize("tid", ["999999", "abc", "0", "99999999999999999999999"])
def test_an_unknown_task_is_404(team, bd_as_user, action, tid):
    r = as_(bd_as_user, team["ada"]).post("/api/bd/tasks/%s/%s" % (tid, action), json={})
    assert r.status_code == 404 and r.json() == {"ok": False, "error": "not_found",
                                                 "message": "That task does not exist."}


def test_an_unknown_task_is_404_before_the_role_check(team, bd_as_user):
    r = as_(bd_as_user, team["max"]).post("/api/bd/tasks/999999/done", json={})
    assert r.status_code == 404


def test_snooze(team, sams_list, bd_as_user, bd_db):
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/snooze" % sams_list["open1"],
                                         json={"reason": "  Out of office until the 16th  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "task": {"id": sams_list["open1"], "status": "snoozed",
                                             "snoozed_until": "2026-11-09"}, "done_count": 1, "total": 4}
    row = bd_db.execute("select snooze_reason from bd.tasks where id = %s", (sams_list["open1"],)).fetchone()
    assert row["snooze_reason"] == "Out of office until the 16th"
    for tid in (sams_list["open1"], sams_list["done1"]):
        r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/snooze" % tid, json={})
        assert r.status_code == 409 and r.json()["message"] == "Only an open task can be skipped."
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/snooze" % sams_list["open2"])
    assert r.status_code == 200
    assert bd_db.execute("select snooze_reason from bd.tasks where id = %s", (sams_list["open2"],)).fetchone() \
        == {"snooze_reason": None}


def test_snooze_runs_to_the_monday_after_the_tasks_week(team, bd_as_user, bd_db):
    sam = team["sam"]["id"]
    tid = mk_task(bd_db, mk_batch(bd_db, sam, "2026-10-26"), mk_contact(bd_db, sam))
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/snooze" % tid, json={})
    assert r.json()["task"]["snoozed_until"] == "2026-11-02"
    assert (r.json()["done_count"], r.json()["total"]) == (0, 1)


@pytest.mark.parametrize("body, field, message", [
    ({"reason": 5}, "reason", "Type the reason as text."),
    ({"reason": ["a"]}, "reason", "Type the reason as text."),
    ({"reason": "x" * 501}, "reason", "Keep the reason under 500 characters."),
    (["reason"], "body", "Send a JSON object."),
    ("text", "body", "Send a JSON object."),
])
def test_snooze_bad_input_is_400(team, sams_list, bd_as_user, bd_db, body, field, message):
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/snooze" % sams_list["open1"], json=body)
    assert r.status_code == 400
    assert r.json() == {"ok": False, "error": "bad_request", "message": "Some fields need fixing.",
                        "fields": {field: message}}
    assert bd_db.execute("select status from bd.tasks where id = %s", (sams_list["open1"],)).fetchone()["status"] == "open"


def test_malformed_json_is_400(team, sams_list, bd_as_user):
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/snooze" % sams_list["open1"], content=b"{nope",
                                          headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["error"] == "bad_request"


def test_reopen(team, sams_list, bd_as_user, bd_db):
    for key in ("done1", "snoozed1"):
        r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/reopen" % sams_list[key], json={})
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True, "task": {"id": sams_list[key], "status": "open", "done_at": None,
                                                 "snoozed_until": None}}
        row = bd_db.execute("select status, done_at, snoozed_until, snooze_reason from bd.tasks where id = %s",
                            (sams_list[key],)).fetchone()
        assert row == {"status": "open", "done_at": None, "snoozed_until": None, "snooze_reason": None}
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/reopen" % sams_list["open1"], json={})
    assert r.status_code == 409 and r.json() == {"ok": False, "error": "conflict",
                                                 "message": "That task is already open."}


def test_reopen_after_an_archive_closed_it_forgets_the_archive(team, sams_list, bd_as_user, bd_db):
    bd_db.execute("update bd.tasks set status = 'snoozed', closed_by_archive = true where id = %s",
                  (sams_list["open1"],))
    as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/reopen" % sams_list["open1"], json={})
    assert bd_db.execute("select closed_by_archive from bd.tasks where id = %s",
                         (sams_list["open1"],)).fetchone()["closed_by_archive"] is False


def test_not_right_person(team, sams_list, bd_as_user, bd_db, monkeypatch):
    monkeypatch.setenv("BD_NOW", "2026-11-04T10:20:00-06:00")
    tid = sams_list["open2"]
    cid = _contact_of(bd_db, tid)
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/not-right-person" % tid,
                                         json={"note": " Laura moved to the Wichita plant. "})
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "task": {"id": tid, "status": "done", "done_at": "2026-11-04T10:20:00-06:00"},
                        "contact": {"id": cid, "confirmed": False,
                                    "notes": "Met at the expo.\nLaura moved to the Wichita plant."}}
    ev = bd_db.execute("select kind, actor_id, contact_id, detail from bd.events").fetchall()
    assert ev == [{"kind": "unconfirmed", "actor_id": team["sam"]["id"], "contact_id": cid,
                   "detail": "Laura moved to the Wichita plant."}]
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]
    t = [x for x in w["tasks"] if x["id"] == tid][0]
    assert t["status"] == "done" and t["contact"]["confirmed"] is False
    assert (w["done_count"], w["total"]) == (2, 4)


def test_not_right_person_without_a_note(team, sams_list, bd_as_user, bd_db):
    tid = sams_list["open1"]
    r = as_(bd_as_user, team["amy"]).post("/api/bd/tasks/%d/not-right-person" % tid)
    assert r.status_code == 200, r.text
    assert r.json()["contact"]["notes"] == "" and r.json()["contact"]["confirmed"] is False
    ev = bd_db.execute("select kind, actor_id, detail from bd.events").fetchone()
    assert ev == {"kind": "unconfirmed", "actor_id": team["amy"]["id"], "detail": None}
    # Done already: it stays done (no 409 here).
    r = as_(bd_as_user, team["amy"]).post("/api/bd/tasks/%d/not-right-person" % tid, json={"note": "Retired."})
    assert r.status_code == 200 and r.json()["contact"]["notes"] == "Retired."


def test_not_right_person_access(team, sams_list, bd_as_user):
    r = as_(bd_as_user, team["max"]).post("/api/bd/tasks/%d/not-right-person" % sams_list["open1"], json={})
    assert r.status_code == 403 and r.json()["message"] == "Your role can't do that."
    # The contract names no task owner here: another salesperson may flag the person on Sam's list.
    r = as_(bd_as_user, team["sue"]).post("/api/bd/tasks/%d/not-right-person" % sams_list["open1"], json={})
    assert r.status_code == 200, r.text
    for who in ("amy", "ada"):
        r = as_(bd_as_user, team[who]).post("/api/bd/tasks/%d/not-right-person" % sams_list["sue"], json={})
        assert r.status_code == 200, r.text


def test_not_right_person_refuses_before_looking_the_task_up(team, bd_as_user):
    r = as_(bd_as_user, team["max"]).post("/api/bd/tasks/999999/not-right-person", json={})
    assert r.status_code == 403


@pytest.mark.parametrize("body, field, message", [
    ({"note": 12}, "note", "Type the note as text."),
    ({"note": "x" * 2001}, "note", "Keep the note under 2000 characters."),
    ([1], "body", "Send a JSON object."),
])
def test_not_right_person_bad_input_is_400(team, sams_list, bd_as_user, bd_db, body, field, message):
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/not-right-person" % sams_list["open1"], json=body)
    assert r.status_code == 400 and r.json()["fields"] == {field: message}
    assert bd_db.execute("select count(*) as n from bd.events").fetchone()["n"] == 0
    assert bd_db.execute("select status from bd.tasks where id = %s", (sams_list["open1"],)).fetchone()["status"] == "open"


def test_done_and_reopen_refuse_a_non_object_body(team, sams_list, bd_as_user):
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/done" % sams_list["open1"], json=[1])
    assert r.status_code == 400 and r.json()["fields"] == {"body": "Send a JSON object."}
    r = as_(bd_as_user, team["sam"]).post("/api/bd/tasks/%d/reopen" % sams_list["done1"], json="x")
    assert r.status_code == 400 and r.json()["fields"] == {"body": "Send a JSON object."}


# ── POST /api/bd/week/ten-more ───────────────────────────────────────────────────────────────
def _ids(db, sql, *params):
    return [r["id"] for r in db.execute(sql, params).fetchall()]


def _ids_of(team, body):
    """{"owner": "SAM"} -> {"owner": <Sam's id>} (upper-case names are team members)."""
    return {k: (team[v.lower()]["id"] if isinstance(v, str) and v.isupper() else v) for k, v in body.items()}


def test_ten_more_builds_a_batch_of_the_next_ten_and_answers_the_week(team, bd_as_user, bd_db):
    sam = team["sam"]["id"]
    for _ in range(13):
        mk_contact(bd_db, sam)
    mk_contact(bd_db, team["sue"]["id"])                    # Sue's: never on Sam's list
    r = as_(bd_as_user, team["sam"]).post("/api/bd/week/ten-more", json={})
    assert r.status_code == 200, r.text
    w = r.json()["week"]
    assert [b["kind"] for b in w["batches"]] == ["ten_more"] and w["batch"]["kind"] == "ten_more"
    assert w["batch"]["week_start"] == "2026-11-02" and w["batch"]["owner"]["id"] == sam
    assert len(w["tasks"]) == 10 and {t["batch_id"] for t in w["tasks"]} == {w["batch"]["id"]}
    assert (w["done_count"], w["total"]) == (0, 0)       # never the Friday headline
    w2 = as_(bd_as_user, team["sam"]).post("/api/bd/week/ten-more", json={"owner": sam}).json()["week"]
    assert len(w2["batches"]) == 2 and len(w2["tasks"]) == 13
    assert len({t["contact"]["id"] for t in w2["tasks"]}) == 13
    r = as_(bd_as_user, team["sam"]).post("/api/bd/week/ten-more")
    assert r.status_code == 409 and r.json() == {
        "ok": False, "error": "conflict", "message": "Everyone on your list is already covered this week."}
    assert len(_ids(bd_db, "select id from bd.task_batches where owner_id = %s", sam)) == 2


@pytest.mark.parametrize("who, body, status, message", [
    ("amy", {}, 403, "Your role can't do that."),
    ("max", {"owner": "SAM"}, 403, "Your role can't do that."),
    ("sam", {"owner": "SUE"}, 403, "You can ask for more only on your own list."),
    ("sam", {"owner": 99999}, 404, "That user does not exist."),
    ("sam", {"owner": "AMY"}, 404, "Amy Assist has no weekly list. Only salespeople do."),
    ("ada", {"owner": "MAX"}, 404, "Max Manager has no weekly list. Only salespeople do."),
])
def test_ten_more_refusals_in_order(team, bd_as_user, bd_db, who, body, status, message):
    mk_contact(bd_db, team["sam"]["id"])
    mk_contact(bd_db, team["sue"]["id"])
    r = as_(bd_as_user, team[who]).post("/api/bd/week/ten-more", json=_ids_of(team, body))
    assert (r.status_code, r.json()["message"]) == (status, message)
    assert _ids(bd_db, "select id from bd.task_batches") == []


def test_an_admin_asks_for_more_on_any_list(team, bd_as_user, bd_db):
    mk_contact(bd_db, team["sue"]["id"])
    r = as_(bd_as_user, team["ada"]).post("/api/bd/week/ten-more", json={"owner": team["sue"]["id"]})
    assert r.status_code == 200 and r.json()["week"]["owner"]["id"] == team["sue"]["id"]
    assert len(r.json()["week"]["tasks"]) == 1
    # No owner (a body that is not an object has none): the first active salesperson, Sam, who has
    # nobody to suggest.
    r = as_(bd_as_user, team["ada"]).post("/api/bd/week/ten-more", json=[1])
    assert r.status_code == 409


def test_ten_more_is_this_central_weeks(team, bd_as_user, bd_db, bd_today):
    mk_contact(bd_db, team["sam"]["id"])
    bd_today("2026-11-08")                                  # Sunday: still the week of Nov 2
    w = as_(bd_as_user, team["sam"]).post("/api/bd/week/ten-more", json={}).json()["week"]
    assert w["week_start"] == "2026-11-02" and w["batch"]["week_start"] == "2026-11-02"
    assert w["batch"]["generated_at"].startswith("2026-11-08T")


def test_ten_more_reads_the_clock_once(team, bd_as_user, bd_db, bd_today, monkeypatch):
    """A press straddling Sunday midnight is answered with the week the batch was built in."""
    from bd import weekly as weeklymod

    sam = team["sam"]["id"]
    for _ in range(3):
        mk_contact(bd_db, sam)
    bd_today("2026-11-08")                                  # Sunday
    real = weeklymod.ten_more

    def across_midnight(conn, owner, day, *a, **kw):
        res = real(conn, owner, day, *a, **kw)
        monkeypatch.setenv("BD_TODAY", "2026-11-09")        # Monday begins while it builds
        return res

    monkeypatch.setattr(weeklymod, "ten_more", across_midnight)
    r = as_(bd_as_user, team["sam"]).post("/api/bd/week/ten-more", json={})
    assert r.status_code == 200, r.text
    w = r.json()["week"]
    assert w["week_start"] == "2026-11-02"
    assert [b["kind"] for b in w["batches"]] == ["ten_more"] and len(w["tasks"]) == 3


# ── POST /api/bd/admin/weekly/run ────────────────────────────────────────────────────────────
def test_weekly_run_builds_next_weeks_batch_once(team, bd_as_user, bd_db, bd_today):
    bd_today("2026-11-06")
    sam = team["sam"]["id"]
    contacts = [mk_contact(bd_db, sam) for _ in range(12)]
    old = mk_batch(bd_db, sam)                              # this week's Friday batch
    t_open = mk_task(bd_db, old, contacts[0])
    t_done = mk_task(bd_db, old, contacts[1], status="done", done_at="2026-11-03T10:00:00-06:00")
    r = as_(bd_as_user, team["ada"]).post("/api/bd/admin/weekly/run", json={"owner": sam})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"ok", "batches", "tasks_created"} and body["tasks_created"] == 10
    b = body["batches"][0]
    assert b["kind"] == "friday" and b["week_start"] == "2026-11-09" and b["owner"]["id"] == sam
    assert b["generated_at"].startswith("2026-11-06T")
    rows = {x["id"]: x for x in bd_db.execute("select * from bd.tasks where batch_id = %s", (old,)).fetchall()}
    assert rows[t_open]["status"] == "snoozed" and str(rows[t_open]["snoozed_until"]) == "2026-11-09"
    assert rows[t_done]["status"] == "done"
    r = as_(bd_as_user, team["ada"]).post("/api/bd/admin/weekly/run", json={"owner": sam, "force": False})
    assert r.status_code == 409
    assert r.json()["message"] == "A Friday batch already exists for Sam Seller that week."
    assert len(_ids(bd_db, "select id from bd.task_batches where week_start = '2026-11-09'")) == 1
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week?week_start=2026-11-09").json()["week"]
    assert w["batch"]["id"] == b["id"] and (w["done_count"], w["total"]) == (0, 10)


def test_weekly_run_force_keeps_the_old_batch_and_snoozes_its_open_tasks(team, bd_as_user, bd_db, bd_today):
    bd_today("2026-11-06")
    sam = team["sam"]["id"]
    for _ in range(4):
        mk_contact(bd_db, sam)
    first = as_(bd_as_user, team["ada"]).post("/api/bd/admin/weekly/run", json={"owner": sam}).json()["batches"][0]
    r = as_(bd_as_user, team["ada"]).post("/api/bd/admin/weekly/run", json={"owner": sam, "force": "yes"})
    assert r.status_code == 200 and r.json()["tasks_created"] == 4
    second = r.json()["batches"][0]
    assert second["id"] > first["id"]
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week?week_start=2026-11-09").json()["week"]
    assert [x["id"] for x in w["batches"]] == [first["id"], second["id"]] and w["batch"]["id"] == second["id"]
    assert {t["status"] for t in w["tasks"] if t["batch_id"] == first["id"]} == {"snoozed"}
    assert (w["done_count"], w["total"]) == (0, 4)       # the live (latest) Friday batch only


def test_weekly_run_for_this_week_and_the_default_owner(team, bd_as_user, bd_db):
    mk_contact(bd_db, team["sam"]["id"])
    r = as_(bd_as_user, team["ada"]).post("/api/bd/admin/weekly/run", json={"week_start": "2026-11-02"})
    assert r.status_code == 200, r.text
    b = r.json()["batches"][0]
    assert (b["owner"]["id"], b["week_start"]) == (team["sam"]["id"], "2026-11-02")
    w = as_(bd_as_user, team["sam"]).get("/api/bd/week").json()["week"]
    assert w["batch"]["id"] == b["id"] and (w["done_count"], w["total"]) == (0, 1)


def test_weekly_run_on_nobody_still_makes_the_batch(team, bd_as_user, bd_db):
    r = as_(bd_as_user, team["ada"]).post("/api/bd/admin/weekly/run", json={"owner": team["sue"]["id"]})
    assert r.status_code == 200 and r.json()["tasks_created"] == 0


MONDAY = {"week_start": "Pick a Monday."}


@pytest.mark.parametrize("who, body, status, message, fields", [
    ("sam", {"owner": "SAM"}, 403, "Your role can't do that.", None),
    ("max", {"owner": "SAM"}, 403, "Your role can't do that.", None),
    ("amy", {"owner": "SAM"}, 403, "Your role can't do that.", None),
    ("ada", {"owner": 99999}, 404, "That user does not exist.", None),
    ("ada", {"owner": "MAX", "week_start": "nope"}, 404, "Max Manager has no weekly list. Only salespeople do.", None),
    ("ada", {"owner": "SAM", "week_start": "2026-11-10"}, 400, "week_start must be a Monday.", MONDAY),
    ("ada", {"owner": "SAM", "week_start": "11/09/2026"}, 400, "week_start must be a Monday.", MONDAY),
    ("ada", {"owner": "SAM", "week_start": 20261109}, 400, "week_start must be a Monday.", MONDAY),
    ("ada", {"owner": "SAM", "week_start": "2026-11-16"}, 400, "week_start must be this Monday or next Monday.",
     {"week_start": "Pick this Monday or next Monday."}),
])
def test_weekly_run_refusals_in_order(team, bd_as_user, bd_db, who, body, status, message, fields):
    r = as_(bd_as_user, team[who]).post("/api/bd/admin/weekly/run", json=_ids_of(team, body))
    assert (r.status_code, r.json()["message"], r.json().get("fields")) == (status, message, fields)
    assert _ids(bd_db, "select id from bd.task_batches") == []


@pytest.mark.parametrize("value, truthy", [
    (None, False), (False, False), (0, False), (0.0, False), ("", False), (float("nan"), False),
    (True, True), (1, True), (-1, True), ("0", True), ("false", True), ([], True), ({}, True),
])
def test_force_and_week_start_use_javascripts_truthiness(value, truthy):
    from bd.routers.admin import _js_truthy
    assert _js_truthy(value) is truthy
