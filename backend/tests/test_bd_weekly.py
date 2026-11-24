"""backend/bd/weekly.py: the weekly 10, inside the proposal tool (#807).

Moved from BD's tests/test_weekly.py.

  * PURE (as in BD): task_kind, rank_contacts + pick_weekly + pick_next against bd-core.js (node)
    on the shared WEEKLY_CASES and on random contact sets full of ties (the tie-break is score
    desc, id asc); should_run as a table (Thursday 23:59, Friday 15:59 / 16:00, the weekend
    catch-up, Monday, both 2026 DST weeks, run day/hour settings).
  * BD's PARITY block ran the same calls through its in-browser mock (api.js) and compared. The
    mock is gone (#806), so those scenarios are checked here on the fixture seed
    (bd/ops/fixture_seed.py) against lists worked out by hand (below), or on data built in the test.
  * MAINTENANCE (pinned): a due maintenance contact heads the list as a "maintenance" task, most
    overdue first, outside the 5 + 5 split; a not-due one is never picked; the rollover re-creates
    it each Friday; Give Me 10 More puts a contact that came due mid-week first.
  * DATABASE: the split from settings, no refill, ten_more never re-adds, the rollover, the
    unique index and a real race between two connections (the per-owner advisory lock, and the
    index alone), run_due, the business-day override.

THE FIXTURE SEED, worked by hand with bd/priority.py's rules:
  Avery (1) owns 21, 23, 25, 27 (BD) and 30, 31 (maintenance). Her Friday batch 201 (week of Nov 2)
  holds 301 (Hal 30, open), 302 (Dana 21, open), 303 (Priya 25, done).
  Built on FRI NOV 6 for the week of Nov 9 (the rollover snoozes 301 and 302 first):
    31 Nora   maintenance, never followed up: due. Never contacted +40, not confirmed +8 = 48.
    21 Dana   tried Nov 2 (4 days ago: out of the 3-day cool-off). Live call Oct 20, 17 days,
              on the team's quarterly BD cadence (her stored 12 a year is not used) 30 x 17 / 91.25
              = 5.6 -> 6; promised Thu Nov 5, past, +50; quote Oct 15 (22 days) +15; key account
              +20; 1 try since live +5 = 96. Follow-up.
    27 Lena   never contacted +40, key account +20, not confirmed +8 = 68. New.
    23 Marisa live meeting Jun 15, 144 days, 30 x 144 / 91.25 = 47, capped at 40; importance 2 +10;
              not confirmed +8 = 58. Follow-up.
    25 Priya  tried Nov 3 (3 days ago: out of the cool-off). Never reached after 1 try +40 +5; not
              confirmed +8 = 53. New.
    30 Hal    maintenance, followed up Aug 20: due on Aug 20 + 120 days = Fri Dec 18. Left out.
    -> 31 (maintenance) first, then the BD side by score: 21, 27, 23, 25.
  On WED NOV 4 (the seed day) Dana (Nov 2) and Priya (Nov 3) are still cooling off, and 30, 21, 25
  are on this week's list, so Give Me 10 More finds 31 (due, first), 27 (68), 23 (58), then nobody.
  Blair (2) owns 22, 24, 26, 28, 33, none ever reached or confirmed: 48 each, new, by id. 22 and 33
  are both at Prairie Ridge Builders, Inc. (company 11), which takes one slot (#828): 22's.
"""
import datetime as dt
import json
import random
import threading

import pytest

from bd import appsettings, bizdate, weekly
from _node import last_json_line, run_node
from test_bd_core_js import CORE, HARNESS, TODAY, WEEKLY_CASES, contact

AVERY, BLAIR = 1, 2
D = dt.date.fromisoformat


def _harness(cases, tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    proc = run_node(HARNESS, CORE, path)
    assert proc.returncode == 0, "the bd-core harness failed:\n" + proc.stderr
    out = last_json_line(proc.stdout)
    assert out["vm_disagrees"] == []
    return out["results"]


def _slim(picks):
    return [{"contact_id": p["contact_id"], "kind": p["kind"], "score": p["score"], "reason": p["reason"],
             "reasons": p["reasons"]} for p in picks]


# ── pure rules ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("c, kind", [
    ({"last_live_at": None}, "new"), ({}, "new"), ({"last_live_at": ""}, "new"),
    ({"last_live_at": "2026-06-01T10:00:00-05:00"}, "followup"),
    ({"last_live_at": dt.datetime(2026, 6, 1, 15, tzinfo=dt.UTC), "confirmed": False}, "followup"),
    ({"last_live_at": None, "confirmed": False}, "new"),
    # a due maintenance contact is a maintenance task whatever its history; not due, it keeps the old kind
    ({"category": "maintenance", "maintenance_due": True, "last_live_at": None}, "maintenance"),
    ({"category": "maintenance", "maintenance_due": True, "last_live_at": "2026-06-01T10:00:00-05:00"}, "maintenance"),
    ({"category": "maintenance", "maintenance_due": False, "last_live_at": "2026-06-01T10:00:00-05:00"}, "followup"),
    ({"category": "maintenance", "last_live_at": None}, "new"),
    ({"category": "bd", "maintenance_due": True, "last_live_at": None}, "new"),
])
def test_task_kind(c, kind):
    assert weekly.task_kind(c) == kind


def _py_pick(fn, args):
    contacts, interactions, skip, today = args[:4]
    assert interactions is None
    ranked = weekly.rank_contacts(contacts, weekly.facts_from_ids(skip), today)
    if fn == "pickWeekly":
        return weekly.pick_weekly(ranked, *(args[4:6] if len(args) > 4 else ()))
    return weekly.pick_next(ranked, args[4] if len(args) > 4 else None)


def _random_sets(n_sets=40, seed=1106):
    """Contact sets with many ties: few distinct importances, dates on a handful of days."""
    rnd = random.Random(seed)
    cases = []
    days = [TODAY, "2026-11-06", "2026-03-06", "2026-03-13", "2026-10-30", "2026-11-01"]
    for k in range(n_sets):
        today = rnd.choice(days)
        base = dt.date.fromisoformat(today)
        contacts = []
        for _ in range(rnd.randint(0, 35)):
            cid = rnd.randint(1, 400)
            if any(c["id"] == cid for c in contacts):
                continue
            live = None
            if rnd.random() < 0.55:
                live = bizdate.to_iso_central(dt.datetime.combine(
                    base - dt.timedelta(days=rnd.choice([3, 30, 91, 200, 400])), dt.time(10, 0)).replace(tzinfo=bizdate.BIZ_TZ))
            attempt = None
            if rnd.random() < 0.4:
                attempt = bizdate.to_iso_central(dt.datetime.combine(
                    base - dt.timedelta(days=rnd.choice([0, 1, 2, 3, 9])), dt.time(9, 0)).replace(tzinfo=bizdate.BIZ_TZ))
            contacts.append(contact(cid, rnd.choice([2, 4, 4, 6]), confirmed=rnd.random() < 0.7,
                                    importance=rnd.choice([1, 1, 2, 3]), last_live_at=live,
                                    last_attempt_at=attempt, attempts_since_live=rnd.choice([0, 0, 1, 2]),
                                    category=rnd.choice(["bd", "bd", "maintenance"]),
                                    promised_date=rnd.choice([None, None, None, (base + dt.timedelta(days=rnd.choice([-2, 0, 5]))).isoformat()])))
        rnd.shuffle(contacts)
        ids = [c["id"] for c in contacts]
        skip = rnd.sample(ids, min(len(ids), rnd.randint(0, 6)))
        n_new = rnd.choice([None, 0, 2, 5, 7, 10])
        if n_new is None:
            cases.append({"id": "w%d" % k, "fn": "pickWeekly", "args": [contacts, None, skip, today]})
        else:
            cases.append({"id": "w%d" % k, "fn": "pickWeekly", "args": [contacts, None, skip, today, n_new, 10 - n_new]})
        cases.append({"id": "n%d" % k, "fn": "pickNext", "args": [contacts, None, skip, today, rnd.choice([3, 10])]})
    return cases


def test_picks_match_bd_core_js_on_the_shared_and_random_cases(tmp_path):
    cases = [{"id": "shared:" + cid, "fn": "pickWeekly", "args": args} for cid, args, *_ in WEEKLY_CASES]
    cases.append({"id": "shared:next", "fn": "pickNext",
                  "args": [WEEKLY_CASES[0][1][0], None, [1, 2], TODAY, 10]})
    cases += _random_sets()
    results = _harness(cases, tmp_path)
    ties = 0
    for case in cases:
        want = _slim(results[case["id"]])
        got = _slim(_py_pick(case["fn"], case["args"]))
        assert got == want, case["id"]
        scores = [p["score"] for p in got]
        ties += len(scores) - len(set(scores))
    assert ties > 50, "the random sets should exercise the tie-break"


def test_pick_weekly_split_and_fill():
    def ranked(n_new, n_follow):
        out = [{"contact_id": i, "kind": "new", "score": 50 - i} for i in range(1, n_new + 1)]
        out += [{"contact_id": 100 + i, "kind": "followup", "score": 49 - i} for i in range(1, n_follow + 1)]
        return sorted(out, key=lambda r: (-r["score"], r["contact_id"]))

    def kinds(picks):
        return [p["kind"] for p in picks].count("new"), [p["kind"] for p in picks].count("followup")

    assert kinds(weekly.pick_weekly(ranked(8, 8))) == (5, 5)
    assert kinds(weekly.pick_weekly(ranked(2, 12))) == (2, 8)          # short new: follow-ups fill
    assert kinds(weekly.pick_weekly(ranked(12, 1))) == (9, 1)          # short follow-ups: new fill
    assert kinds(weekly.pick_weekly(ranked(3, 2))) == (3, 2)           # fewer than 10: all of them
    assert kinds(weekly.pick_weekly(ranked(8, 8), 7, 3)) == (7, 3)
    assert kinds(weekly.pick_weekly(ranked(8, 8), 10, 0)) == (8, 2)
    assert weekly.pick_weekly([]) == []
    picks = weekly.pick_weekly(ranked(8, 8))
    assert [p["score"] for p in picks] == sorted((p["score"] for p in picks), reverse=True)
    assert len(weekly.pick_next(ranked(8, 8))) == 10 and len(weekly.pick_next(ranked(8, 8), 3)) == 3


# ── maintenance, pinned to the top (pure) ──────────────────────────────────────────────────────
def due(cid, due_date=None, **kw):
    """A DUE maintenance contact as the view hands it over; never followed up when due_date is None."""
    return contact(cid, 3, category="maintenance", maintenance_due=True, maintenance_due_date=due_date,
                   last_followup_at="2026-07-01T10:00:00-05:00" if due_date else None, **kw)


def waiting(cid, **kw):
    """A maintenance contact that is NOT due yet."""
    return contact(cid, 3, category="maintenance", maintenance_due=False, maintenance_due_date="2027-01-29",
                   last_followup_at="2026-10-01T10:00:00-05:00", **kw)


def _bd(n_new, n_follow, first=1):
    """BD contacts: n_new never reached (score 40 + importance), n_follow reached long ago."""
    out = [contact(first + i, 4, importance=2 + (i % 2)) for i in range(n_new)]
    out += [contact(first + 100 + i, 4, last_live_at="2026-01-05T10:00:00-06:00") for i in range(n_follow)]
    return out


def _ids(picks):
    return [p["contact_id"] for p in picks]


def _kinds(picks):
    return [p["kind"] for p in picks]


def test_pick_weekly_maintenance_first():
    contacts = _bd(8, 8) + [due(500, "2026-10-01"), due(501, "2026-09-15"), waiting(502)]
    ranked = weekly.rank_contacts(contacts, {}, TODAY)
    picks = weekly.pick_weekly(ranked)
    # the two due maintenance contacts, most overdue first, then 5 new + 5 follow-ups by score
    assert _ids(picks)[:2] == [501, 500]
    assert _kinds(picks)[:2] == ["maintenance", "maintenance"]
    assert len(picks) == 12
    bd = picks[2:]
    assert _kinds(bd).count("new") == 5 and _kinds(bd).count("followup") == 5
    assert [(-p["score"], p["contact_id"]) for p in bd] == sorted((-p["score"], p["contact_id"]) for p in bd)
    # the not-due one is nowhere
    assert 502 not in _ids(weekly.pick_weekly(ranked, 100, 100)) and 502 not in _ids(ranked)
    # a maintenance task: normal score, the due reason first, the top two as the chip
    first = picks[0]
    assert first["reasons"][0] == "Follow-up was due Tue, Sep 15"
    assert first["reason"].startswith("Follow-up was due Tue, Sep 15. ")
    assert first["score"] == weekly.priority.score(first["contact"], {"has_open_task": False}, TODAY)["score"]
    assert first["reasons"][1:] == weekly.priority.score(first["contact"], {}, TODAY)["reasons"]


def test_maintenance_does_not_use_up_the_bd_slots():
    """The 5 + 5 is about BD only: BD picks are the same with or without due maintenance contacts,
    and a short BD side is still filled from the other BD side."""
    bd = _bd(8, 8)
    without = weekly.pick_weekly(weekly.rank_contacts(bd, {}, TODAY))
    with_m = weekly.pick_weekly(weekly.rank_contacts(bd + [due(500, "2026-10-01"), due(501)], {}, TODAY))
    assert _ids(with_m)[2:] == _ids(without)
    # 2 new + 12 follow-ups: 2 + 8 BD, after the maintenance ones
    short = weekly.pick_weekly(weekly.rank_contacts(_bd(2, 12) + [due(500, "2026-10-01")], {}, TODAY))
    assert _kinds(short).count("maintenance") == 1 and len(short) == 1 + 10
    assert _kinds(short).count("new") == 2 and _kinds(short).count("followup") == 8
    # only maintenance: just those
    assert _kinds(weekly.pick_weekly(weekly.rank_contacts([due(1), due(2, "2026-10-01")], {}, TODAY))) == \
        ["maintenance", "maintenance"]
    # nobody due, only waiting ones: nothing
    assert weekly.pick_weekly(weekly.rank_contacts([waiting(1), waiting(2)], {}, TODAY)) == []


def test_more_than_ten_due_grows_the_batch():
    contacts = _bd(8, 8) + [due(500 + i, "2026-%02d-%02d" % (6 + i // 20, 1 + i % 20)) for i in range(13)]
    picks = weekly.pick_weekly(weekly.rank_contacts(contacts, {}, TODAY))
    assert _kinds(picks).count("maintenance") == 13
    assert len(picks) == 13 + 10
    assert _kinds(picks)[:13] == ["maintenance"] * 13 and "maintenance" not in _kinds(picks)[13:]
    # a custom split still means the BD picks only
    small = weekly.pick_weekly(weekly.rank_contacts(contacts, {}, TODAY), 2, 1)
    assert len(small) == 13 + 3


def test_maintenance_order_is_most_overdue_first_never_followed_up_first():
    contacts = [due(9, "2026-10-20"), due(7, "2026-09-01"), due(5), due(3), due(8, "2026-10-20"),
                contact(1, importance=3, confirmed=False), waiting(11)]
    ranked = weekly.rank_contacts(contacts, {}, TODAY)
    # never followed up (lower id first), then the earliest date, a shared date by id, then BD
    assert _ids(ranked) == [3, 5, 7, 8, 9, 1]
    assert [r["reasons"][0] for r in ranked[:5]] == [
        "No follow-up logged yet", "No follow-up logged yet", "Follow-up was due Tue, Sep 1",
        "Follow-up was due Tue, Oct 20", "Follow-up was due Tue, Oct 20"]
    # a due maintenance contact with a LOW score still beats a BD contact with a high one
    assert ranked[0]["score"] < ranked[-1]["score"]
    # due today says so
    assert weekly.rank_contacts([due(1, TODAY)], {}, TODAY)[0]["reasons"][0] == "Follow-up due today"
    # a database row holds a date, not text: same order
    rows = [dict(c, maintenance_due_date=(dt.date.fromisoformat(c["maintenance_due_date"])
                                          if c.get("maintenance_due_date") else None)) for c in contacts]
    assert _ids(weekly.rank_contacts(rows, {}, TODAY)) == _ids(ranked)


def test_maintenance_on_a_list_is_skipped():
    contacts = [due(1, "2026-10-01"), due(2, "2026-10-02"), contact(3)]
    ranked = weekly.rank_contacts(contacts, weekly.facts_from_ids([1]), TODAY)
    assert _ids(ranked) == [2, 3]


def test_ten_more_is_the_same_ranking():
    contacts = _bd(8, 8) + [due(500, "2026-10-01"), due(501, "2026-09-15")]
    ranked = weekly.rank_contacts(contacts, {}, TODAY)
    nxt = weekly.pick_next(ranked)
    assert _ids(nxt)[:2] == [501, 500] and len(nxt) == 10
    assert _ids(weekly.pick_next(ranked, 1)) == [501]
    assert _ids(weekly.pick_next(ranked, 2)) == [501, 500]


def test_maintenance_picks_match_bd_core_js(tmp_path):
    contacts = [due(9, "2026-10-20"), due(7, "2026-09-01"), due(5), due(3), due(8, "2026-10-20"), waiting(11),
                due(12, TODAY)] + _bd(8, 8)
    cases = [
        {"id": "w", "fn": "pickWeekly", "args": [contacts, None, [], TODAY]},
        {"id": "w_skip", "fn": "pickWeekly", "args": [contacts, None, [3, 1], TODAY]},
        {"id": "w_split", "fn": "pickWeekly", "args": [contacts, None, [], TODAY, 2, 1]},
        {"id": "n", "fn": "pickNext", "args": [contacts, None, [], TODAY, 10]},
        {"id": "n3", "fn": "pickNext", "args": [contacts, None, [], TODAY, 3]},
        {"id": "n_skip", "fn": "pickNext", "args": [contacts, None, [3, 5, 100], TODAY, 10]},
    ]
    results = _harness(cases, tmp_path)
    for case in cases:
        assert _slim(_py_pick(case["fn"], case["args"])) == _slim(results[case["id"]]), case["id"]


def test_weekly_settings_defaults():
    assert weekly.weekly_settings({}) == {"new_count": 5, "followup_count": 5, "run_day": "friday",
                                          "run_hour": 16, "enabled": True}
    w = weekly.weekly_settings({"weekly": {"new_count": 6, "followup_count": 4, "run_day": "Saturday",
                                           "run_hour": 9, "enabled": False}})
    assert w == {"new_count": 6, "followup_count": 4, "run_day": "saturday", "run_hour": 9, "enabled": False}
    assert weekly.weekly_settings(appsettings.defaults())["run_hour"] == 16


# ── should_run ─────────────────────────────────────────────────────────────────────────────────
SHOULD_RUN = [
    # (id, now, last_run_week, kwargs, expected week_start or None)
    ("thursday_23_59", "2026-11-05T23:59:59-06:00", None, {}, None),
    ("friday_15_59", "2026-11-06T15:59:59-06:00", None, {}, None),
    ("friday_16_00", "2026-11-06T16:00:00-06:00", None, {}, "2026-11-09"),
    ("friday_16_00_last_week_built", "2026-11-06T16:00:00-06:00", "2026-11-02", {}, "2026-11-09"),
    ("friday_16_00_already_built", "2026-11-06T16:00:00-06:00", "2026-11-09", {}, None),
    ("friday_23_59", "2026-11-06T23:59:59-06:00", "2026-11-02", {}, "2026-11-09"),
    ("saturday_catch_up", "2026-11-07T09:00:00-06:00", "2026-11-02", {}, "2026-11-09"),
    ("sunday_catch_up", "2026-11-08T23:59:59-06:00", None, {}, "2026-11-09"),
    ("saturday_done", "2026-11-07T09:00:00-06:00", "2026-11-09", {}, None),
    ("monday_new_week", "2026-11-09T00:00:00-06:00", "2026-11-02", {}, None),
    ("utc_input_15_59_cst", "2026-11-06T21:59:59Z", None, {}, None),
    ("utc_input_16_00_cst", "2026-11-06T22:00:00Z", None, {}, "2026-11-09"),
    ("naive_is_central", dt.datetime(2026, 11, 6, 16, 0), None, {}, "2026-11-09"),
    ("aware_datetime", dt.datetime(2026, 11, 6, 22, 0, tzinfo=dt.UTC), None, {}, "2026-11-09"),
    # Spring forward (Sun 2026-03-08): Friday Mar 6 is CST (UTC-6), Friday Mar 13 is CDT (UTC-5).
    ("dst_spring_fri_before_15_59", "2026-03-06T21:59:00Z", None, {}, None),
    ("dst_spring_fri_before_16_00", "2026-03-06T22:00:00Z", None, {}, "2026-03-09"),
    ("dst_spring_sunday_after_jump", "2026-03-08T03:30:00-05:00", None, {}, "2026-03-09"),
    ("dst_spring_fri_after_15_59", "2026-03-13T20:59:00Z", "2026-03-09", {}, None),
    ("dst_spring_fri_after_16_00", "2026-03-13T21:00:00Z", "2026-03-09", {}, "2026-03-16"),
    # Fall back (Sun 2026-11-01): Friday Oct 30 is CDT, Friday Nov 6 is CST.
    ("dst_fall_fri_before_15_59", "2026-10-30T20:59:00Z", None, {}, None),
    ("dst_fall_fri_before_16_00", "2026-10-30T21:00:00Z", None, {}, "2026-11-02"),
    ("dst_fall_repeated_hour", "2026-11-01T01:30:00-06:00", "2026-10-26", {}, "2026-11-02"),
    ("dst_fall_fri_after_15_30_cst", "2026-11-06T21:30:00Z", "2026-11-02", {}, None),
    # Settings: off, another day and hour.
    ("disabled", "2026-11-06T17:00:00-06:00", None, {"enabled": False}, None),
    ("saturday_9_before", "2026-11-07T08:59:00-06:00", None, {"run_day": "saturday", "run_hour": 9}, None),
    ("saturday_9_at", "2026-11-07T09:00:00-06:00", None, {"run_day": "saturday", "run_hour": 9}, "2026-11-09"),
    ("friday_hour_18", "2026-11-06T17:00:00-06:00", None, {"run_hour": 18}, None),
    ("sunday_midnight", "2026-11-08T00:00:00-06:00", None, {"run_day": "sunday", "run_hour": 0}, "2026-11-09"),
    ("sunday_23_built", "2026-11-08T23:00:00-06:00", "2026-11-09", {"run_day": "sunday", "run_hour": 0}, None),
    ("sunday_run_next_monday", "2026-11-09T08:00:00-06:00", "2026-11-09", {"run_day": "sunday", "run_hour": 0}, None),
]


@pytest.mark.parametrize("cid, now, last, kw, want", SHOULD_RUN, ids=[s[0] for s in SHOULD_RUN])
def test_should_run(cid, now, last, kw, want):
    got = weekly.should_run(now, D(last) if isinstance(last, str) else last, **kw)
    assert got == (D(want) if want else None)


def test_should_run_refuses_bad_settings():
    with pytest.raises(ValueError):
        weekly.should_run("2026-11-06T16:00:00-06:00", None, run_day="funday")
    # Finding: a run day before Friday built NEXT week's list and its rollover snoozed the list
    # still being worked (a Monday run snoozed the whole list on the Monday it starts). Only the
    # end of the week may hold the run.
    for day in ("monday", "tuesday", "wednesday", "thursday"):
        with pytest.raises(ValueError):
            weekly.should_run("2026-11-09T08:00:00-06:00", "2026-11-09", run_day=day, run_hour=8)
    assert weekly.ALLOWED_RUN_DAYS == ("friday", "saturday", "sunday")
    with pytest.raises(ValueError):
        weekly.should_run("2026-11-06T16:00:00-06:00", None, run_hour=24)


def test_run_moment_follows_dst():
    assert weekly.run_moment(D("2026-03-04")).astimezone(dt.UTC).hour == 22     # CST
    assert weekly.run_moment(D("2026-03-11")).astimezone(dt.UTC).hour == 21     # CDT
    assert weekly.run_moment(D("2026-10-28")).astimezone(dt.UTC).hour == 21     # CDT
    assert weekly.run_moment(D("2026-11-04")).astimezone(dt.UTC).hour == 22     # CST


# ── the database ───────────────────────────────────────────────────────────────────────────────
def _tasks(db, batch_id):
    return db.execute("select * from bd.tasks where batch_id = %s order by id", (batch_id,)).fetchall()


def _picked(db, batch_id):
    return [(r["contact_id"], r["kind"]) for r in _tasks(db, batch_id)]


AVERYS_NOV_9 = [(31, "maintenance", 48), (21, "followup", 96), (27, "new", 68), (23, "followup", 58),
                (25, "new", 53)]


def test_the_friday_build_on_the_fixture_seed(bd_seeded, bd_db, bd_today):
    day = bd_today("2026-11-06")
    res = weekly.build_batch(bd_db, AVERY, day)
    rows = _tasks(bd_db, res["batch"]["id"])
    assert res["batch"]["week_start"] == D("2026-11-09") and res["batch"]["kind"] == "friday"
    assert [(r["contact_id"], r["kind"], r["score"]) for r in rows] == AVERYS_NOV_9
    assert res["tasks_created"] == 5 and res["snoozed"] == 2
    assert rows[0]["reasons"] == ["No follow-up logged yet", "Never contacted",
                                  "Needs confirming: still the right person?"]
    # Dana's parts, most points first: promised (50), key account (20), the quote (15), the cadence
    # (6: 17 days is "2 weeks ago", 4 a year), one try (5).
    assert rows[1]["reasons"] == ["Promised a call by Thu, Nov 5", "Key account",
                                  "Recent quote activity (Thu, Oct 15)",
                                  "Last live talk 2 weeks ago; needs 4 a year", "1 try since the last live talk"]
    assert all(r["status"] == "open" and r["snoozed_until"] is None for r in rows)


def test_blairs_friday_build_on_the_fixture_seed(bd_seeded, bd_db, bd_today):
    res = weekly.build_batch(bd_db, BLAIR, bd_today("2026-11-06"))
    assert [(r["contact_id"], r["kind"], r["score"]) for r in _tasks(bd_db, res["batch"]["id"])] == [
        (22, "new", 48), (24, "new", 48), (26, "new", 48), (28, "new", 48)]
    assert res["snoozed"] == 1                       # 304; 305 was already snoozed


# Data built in the test: a salesperson with `n_new` never-reached contacts and `n_follow` last
# talked to on 2025-11-04 (a year before: the cadence is capped at 40), each at a company of their own
# (the split counts companies, #828). Everyone is confirmed and of importance 1, so every score is 40
# and only the kinds differ.
def _salesperson(db, n_new, n_follow):
    uid = db.execute("insert into bd.users (email, name, role) values ('pat.test@example.com',"
                     " 'Pat Test', 'salesperson') returning id").fetchone()["id"]
    for k in range(n_new + n_follow):
        co = db.execute("insert into bd.companies (name, normalized_name) values (%s, %s) returning id",
                        ("Test Supply Co %d" % k, "test supply co %d" % k)).fetchone()["id"]
        cid = db.execute("insert into bd.contacts (company_id, name, phone, email, category, owner_id,"
                         " confirmed) values (%s, %s, %s, %s, 'bd', %s, true) returning id",
                         (co, "Person %d" % k, "816-555-01%02d" % k, "person%d@example.com" % k,
                          uid)).fetchone()["id"]
        if k >= n_new:
            db.execute("insert into bd.interactions (contact_id, kind, occurred_at)"
                       " values (%s, 'meeting', '2025-11-04T10:00:00-06:00')", (cid,))
    return uid


def _kind_counts(db, batch_id):
    kinds = [r["kind"] for r in _tasks(db, batch_id)]
    return kinds.count("new"), kinds.count("followup")


def test_the_split_follows_settings(bd_db, bd_today):
    day = bd_today("2026-11-06")
    pat = _salesperson(bd_db, 8, 8)
    appsettings.store(bd_db, {"weekly": {"new_count": 7, "followup_count": 3}})
    assert _kind_counts(bd_db, weekly.build_batch(bd_db, pat, day)["batch"]["id"]) == (7, 3)


def test_five_and_five_by_default(bd_db, bd_today):
    pat = _salesperson(bd_db, 8, 8)
    assert _kind_counts(bd_db, weekly.build_batch(bd_db, pat, bd_today("2026-11-06"))["batch"]["id"]) == (5, 5)


def test_short_side_is_filled(bd_db, bd_today):
    """Two never-reached contacts: the follow-ups fill the other three slots."""
    pat = _salesperson(bd_db, 2, 12)
    assert _kind_counts(bd_db, weekly.build_batch(bd_db, pat, bd_today("2026-11-06"))["batch"]["id"]) == (2, 8)


def test_the_rollover_closes_earlier_weeks_as_snoozed(bd_seeded, bd_db, bd_today):
    res = weekly.build_batch(bd_db, AVERY, bd_today("2026-11-06"))
    assert res["snoozed"] == 2
    rows = [(r["id"], r["status"], r["snoozed_until"]) for r in _tasks(bd_db, 201)]
    assert rows == [(301, "snoozed", D("2026-11-09")), (302, "snoozed", D("2026-11-09")), (303, "done", None)]
    # Blair's list is not Avery's: her open 304 stays open.
    assert bd_db.execute("select status from bd.tasks where id = 304").fetchone()["status"] == "open"


def test_never_refills(bd_seeded, bd_db, bd_today):
    """Skipping tasks leaves the slots empty: a second build is refused, and Give Me 10 More never
    brings the skipped names back (on the seed nobody else is left)."""
    day = bd_today("2026-11-09")
    res = weekly.build_batch(bd_db, AVERY, day, week_start="2026-11-09")
    bid = res["batch"]["id"]
    assert len(_tasks(bd_db, bid)) == 5
    bd_db.execute("update bd.tasks set status = 'snoozed', snoozed_until = '2026-11-16' where batch_id = %s"
                  " and contact_id in (27, 23)", (bid,))
    with pytest.raises(weekly.BatchExists):
        weekly.build_batch(bd_db, AVERY, day, week_start="2026-11-09")
    assert len(_tasks(bd_db, bid)) == 5
    with pytest.raises(weekly.NothingLeft):
        weekly.ten_more(bd_db, AVERY, day)


def test_the_friday_batch_has_every_due_maintenance_contact_first(bd_seeded, bd_db, bd_today):
    bd_today("2026-11-06")
    due_ids = [r["id"] for r in bd_db.execute(
        "select id from bd.contacts_summary where owner_id = 1 and category = 'maintenance' and maintenance_due"
        " order by id").fetchall()]
    assert due_ids == [31]                             # Hal (30) was followed up on Aug 20
    rows = _tasks(bd_db, weekly.build_batch(bd_db, AVERY, "2026-11-06")["batch"]["id"])
    assert [r["kind"] for r in rows] == ["maintenance", "followup", "new", "followup", "new"]
    assert rows[0]["contact_id"] == 31


def test_not_due_maintenance_is_never_picked(bd_seeded, bd_db, bd_today):
    for d in ("2026-11-04", "2026-11-06"):
        day = bd_today(d)
        assert 30 not in {p["contact_id"] for p in weekly.rank(bd_db, AVERY, day)}
    # Give Me 10 More on the seed day, to the end of the list: 31, 27, 23, never Hal.
    day = bd_today("2026-11-04")
    assert [p["contact_id"] for p in weekly.ten_more(bd_db, AVERY, day)["picks"]] == [31, 27, 23]
    with pytest.raises(weekly.NothingLeft):
        weekly.ten_more(bd_db, AVERY, day)
    # Nor Friday's build.
    picked = {r["contact_id"] for r in _tasks(bd_db, weekly.build_batch(bd_db, AVERY, "2026-11-06")["batch"]["id"])}
    assert picked == {31, 21, 27, 23, 25}


def test_a_maintenance_contact_that_is_not_due_comes_on_when_it_falls_due(bd_seeded, bd_db, bd_today):
    """Hal (30) falls due on Fri 2026-12-18 (followed up 2026-08-20 + 120 days)."""
    before = {p["contact_id"] for p in weekly.rank(bd_db, AVERY, bd_today("2026-12-17"))}
    after = {p["contact_id"]: p for p in weekly.rank(bd_db, AVERY, bd_today("2026-12-18"))}
    assert 30 not in before and after[30]["kind"] == "maintenance"
    assert after[30]["reasons"][0] == "Follow-up due today"


def test_rollover_recreates_a_due_maintenance_task(bd_seeded, bd_db, bd_today):
    """Friday after Friday a due maintenance contact is back on the list: the rollover snoozes last
    week's task, the next build makes a new one, until a follow-up is logged."""
    first = weekly.build_batch(bd_db, AVERY, bd_today("2026-11-06"))
    m1 = [r for r in _tasks(bd_db, first["batch"]["id"]) if r["kind"] == "maintenance"]
    assert [r["contact_id"] for r in m1] == [31]
    second = weekly.build_batch(bd_db, AVERY, bd_today("2026-11-13"))
    assert second["batch"]["week_start"] == D("2026-11-16")
    assert [r["status"] for r in _tasks(bd_db, first["batch"]["id"]) if r["kind"] == "maintenance"] == ["snoozed"]
    m2 = [r for r in _tasks(bd_db, second["batch"]["id"]) if r["kind"] == "maintenance"]
    assert [r["contact_id"] for r in m2] == [31]
    assert m2[0]["status"] == "open" and m2[0]["id"] > m1[0]["id"]
    # An email clears Nora for good (her clock restarts), so the next Friday nobody is pinned.
    bd_db.execute("insert into bd.interactions (contact_id, kind, direction, occurred_at, user_id)"
                  " values (31, 'email', 'out', '2026-11-16T10:00:00-06:00', 1)")
    third = weekly.build_batch(bd_db, AVERY, bd_today("2026-11-20"))
    assert [r["contact_id"] for r in _tasks(bd_db, third["batch"]["id"]) if r["kind"] == "maintenance"] == []


def test_a_forced_re_run_recreates_the_maintenance_tasks(bd_seeded, bd_db, bd_today):
    day = bd_today("2026-11-06")
    first = weekly.build_batch(bd_db, AVERY, day)
    second = weekly.build_batch(bd_db, AVERY, day, force=True)
    assert _picked(bd_db, second["batch"]["id"])[0] == (31, "maintenance")
    assert {r["status"] for r in _tasks(bd_db, first["batch"]["id"])} == {"snoozed"}


def test_ten_more_puts_a_mid_week_due_contact_first(bd_seeded, bd_db, bd_today):
    """The week of 2026-12-14 was built on Fri 12-11 (Nora and the four BD contacts on it); Hal falls
    due on Fri 12-18, so he is not on the list and is the extra ten's only name."""
    weekly.build_batch(bd_db, AVERY, bd_today("2026-12-11"))
    res = weekly.ten_more(bd_db, AVERY, bd_today("2026-12-18"))
    assert res["batch"]["kind"] == "ten_more" and res["batch"]["week_start"] == D("2026-12-14")
    rows = _tasks(bd_db, res["batch"]["id"])
    assert [(r["contact_id"], r["kind"]) for r in rows] == [(30, "maintenance")]
    assert rows[0]["reasons"][0] == "Follow-up due today"


def test_ten_more_on_the_seed_day_never_re_adds(bd_seeded, bd_db, bd_today):
    """Wed Nov 4: 30, 21, 25 are on this week's list (in any state); Dana and Priya also cool off.
    The extra ten is Nora (due, first), Lena (68), Marisa (58), then nobody; the Friday 10's counts
    never move (303 done of 302, 303)."""
    from bd.routers.week import friday_counts

    day = bd_today("2026-11-04")
    res = weekly.ten_more(bd_db, AVERY, day)
    assert res["batch"]["kind"] == "ten_more" and res["batch"]["week_start"] == D("2026-11-02")
    assert [(p["contact_id"], p["kind"], p["score"]) for p in res["picks"]] == [
        (31, "maintenance", 48), (27, "new", 68), (23, "followup", 58)]
    assert res["tasks_created"] == 3
    with pytest.raises(weekly.NothingLeft):
        weekly.ten_more(bd_db, AVERY, day)
    assert friday_counts(bd_db, AVERY, D("2026-11-02")) == {"done_count": 1, "total": 2}


def test_force_replaces_the_batch(bd_seeded, bd_db, bd_today):
    day = bd_today("2026-11-06")
    first = weekly.build_batch(bd_db, AVERY, day)["batch"]["id"]
    with pytest.raises(weekly.BatchExists) as exc:
        weekly.build_batch(bd_db, AVERY, day)
    assert exc.value.batch_id == first and exc.value.week_start == D("2026-11-09")
    second = weekly.build_batch(bd_db, AVERY, day, force=True)
    assert second["replaced"] == [first]
    old = bd_db.execute("select replaced_at from bd.task_batches where id = %s", (first,)).fetchone()
    assert old["replaced_at"] is not None
    assert {r["status"] for r in _tasks(bd_db, first)} == {"snoozed"}
    assert weekly.last_friday_week(bd_db, AVERY) == D("2026-11-09")


def test_the_unique_index_refuses_a_second_live_friday_batch(bd_seeded, bd_db):
    from psycopg.errors import UniqueViolation

    with pytest.raises(UniqueViolation):
        bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, '2026-11-02', 'friday')")
    # Give Me 10 More batches may repeat; a replaced Friday batch frees the slot.
    bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, '2026-11-02', 'ten_more')")
    bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, '2026-11-02', 'ten_more')")
    bd_db.execute("update bd.task_batches set replaced_at = bd_now() where id = 201")
    bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, '2026-11-02', 'friday')")
    with pytest.raises(UniqueViolation):
        bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, '2026-11-02', 'friday')")
    # Another owner's Friday batch of the same week is fine (Blair's 202 already is one).
    idx = bd_db.execute("select indexdef from pg_indexes where indexname = 'task_batches_one_friday_key'").fetchone()
    assert "UNIQUE" in idx["indexdef"] and "replaced_at IS NULL" in idx["indexdef"]


def _race(url, monkeypatch, without_lock):
    """Two connections build Avery's Friday batch at the same moment."""
    from bd import db as dbmod

    barrier = threading.Barrier(2, timeout=30)
    if without_lock:
        # Both pass the "is there a batch?" check before either inserts: only the index stops one.
        monkeypatch.setattr(weekly, "_lock_owner", lambda conn, owner_id: barrier.wait())
    results = []

    def worker():
        conn = dbmod.direct(url, autocommit=False)
        try:
            if not without_lock:
                barrier.wait()
            try:
                with conn.transaction():
                    res = weekly.build_batch(conn, AVERY, D("2026-11-06"))
                results.append(("built", res["batch"]["id"]))
            except weekly.BatchExists as exc:
                # Under the lock the loser waits, then SEES the batch (and names it); the index
                # alone refuses its insert, so it never saw one.
                results.append(("exists", exc.batch_id))
        except Exception as exc:  # reported below
            results.append(("error", repr(exc)))
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    return sorted(results)


@pytest.mark.parametrize("without_lock", [False, True], ids=["with_the_lock", "index_alone"])
def test_a_race_builds_one_batch(bd_seeded, bd_db, bd_db_url, bd_today, monkeypatch, without_lock):
    """The per-owner advisory lock makes the second builder wait and then see the batch; with the
    lock taken away, the one-Friday-per-week unique index alone still refuses the second."""
    import _bd_db

    bd_today("2026-11-06")
    results = _race(_bd_db.app_login_url(bd_db_url), monkeypatch, without_lock)
    assert [r[0] for r in results] == ["built", "exists"], results
    assert results[1][1] == (None if without_lock else results[0][1]), results
    live = bd_db.execute("select id from bd.task_batches where owner_id = 1 and week_start = '2026-11-09'"
                         " and kind = 'friday'").fetchall()
    assert [r["id"] for r in live] == [results[0][1]]
    # The loser's rollover rolled back with it; the winner's stands, once.
    assert bd_db.execute("select count(*) as n from bd.tasks where batch_id = %s",
                         (results[0][1],)).fetchone()["n"] == 5


@pytest.fixture
def weekly_on(monkeypatch):
    """BD_WEEKLY_ENABLED on, as in prod: settings.weekly.enabled takes its default from it (a stored
    setting wins), and run_due builds nothing while it is false."""
    from bd import config

    monkeypatch.setattr(config, "BD_WEEKLY_ENABLED", True)


def test_run_due_builds_nothing_by_default_with_the_flag_off(bd_seeded, bd_db, bd_today):
    bd_today("2026-11-06")
    assert weekly.run_due(bd_db, "2026-11-06T16:00:00-06:00") == []


@pytest.mark.usefixtures("weekly_on")
def test_run_due(bd_seeded, bd_db, bd_today):
    bd_today("2026-11-06")
    assert weekly.run_due(bd_db, "2026-11-06T15:59:00-06:00") == []
    built = weekly.run_due(bd_db, "2026-11-06T16:00:00-06:00")
    assert [(b["owner_id"], b["week_start"], b["tasks_created"]) for b in built] == [
        (AVERY, D("2026-11-09"), 5), (BLAIR, D("2026-11-09"), 4)]
    assert weekly.run_due(bd_db, "2026-11-06T16:05:00-06:00") == []
    assert weekly.run_due(bd_db, "2026-11-07T10:00:00-06:00") == []


@pytest.mark.usefixtures("weekly_on")
def test_run_due_refuses_a_run_day_before_friday(bd_seeded, bd_db, bd_today):
    """Finding: with run_day monday the worker snoozed the current week's list on its Monday. Such
    a setting can no longer be saved, and one stored anyway builds nothing and closes nothing:
    run_due raises (the worker logs the tick as failed)."""
    bd_today("2026-11-09")
    appsettings.store(bd_db, {"weekly": {"run_day": "monday", "run_hour": 8}})
    with pytest.raises(ValueError):
        weekly.run_due(bd_db, "2026-11-09T08:00:00-06:00")
    assert bd_db.execute("select count(*) as n from bd.task_batches where week_start > '2026-11-02'").fetchone()["n"] == 0
    assert [r["status"] for r in _tasks(bd_db, 201)] == ["open", "open", "done"]


@pytest.mark.usefixtures("weekly_on")
def test_run_due_one_owner_failing_never_costs_the_others_their_batch(bd_seeded, bd_db, bd_today, monkeypatch):
    """Finding: one owner's exception rolled back every other owner's batch on every tick. Each
    owner is built on its own now: Avery's batch stands, Blair's failure is reported and retried."""
    bd_today("2026-11-06")
    real = weekly.build_batch

    def flaky(conn, owner, *a, **kw):
        if weekly._owner_id(owner) == BLAIR:
            conn.execute("select 1")
            raise RuntimeError("boom")
        return real(conn, owner, *a, **kw)

    monkeypatch.setattr(weekly, "build_batch", flaky)
    failed = []
    built = weekly.run_due(bd_db, "2026-11-06T16:00:00-06:00", failed=failed)
    assert [(b["owner_id"], b["week_start"]) for b in built] == [(AVERY, D("2026-11-09"))]
    assert failed == [BLAIR]
    fridays = bd_db.execute("select owner_id from bd.task_batches where kind = 'friday'"
                            " and week_start = '2026-11-09' order by owner_id").fetchall()
    assert [r["owner_id"] for r in fridays] == [AVERY]
    # The next tick tries Blair again (Avery is done); once the fault is gone she gets her list.
    monkeypatch.setattr(weekly, "build_batch", real)
    again = weekly.run_due(bd_db, "2026-11-06T16:01:00-06:00")
    assert [b["owner_id"] for b in again] == [BLAIR]


@pytest.mark.usefixtures("weekly_on")
def test_run_due_in_one_transaction_keeps_the_built_owners(bd_seeded, bd_db_url, bd_today, monkeypatch):
    """The worker's case: a pooled-style connection with autocommit OFF (one implicit transaction)
    and commit=True. A later owner's failure must not roll back the earlier owner's batch, even
    when the connection is then rolled back as a whole."""
    import _bd_db
    from bd import db as dbmod

    bd_today("2026-11-06")
    url = _bd_db.app_login_url(bd_db_url)
    real = weekly.build_batch

    def flaky(conn, owner, *a, **kw):
        if weekly._owner_id(owner) == BLAIR:
            raise RuntimeError("boom")
        return real(conn, owner, *a, **kw)

    monkeypatch.setattr(weekly, "build_batch", flaky)
    conn = dbmod.direct(url, autocommit=False)
    try:
        failed = []
        built = weekly.run_due(conn, "2026-11-06T16:00:00-06:00", commit=True, failed=failed)
        conn.rollback()                    # whatever happens to the rest of the tick
    finally:
        conn.close()
    assert [b["owner_id"] for b in built] == [AVERY] and failed == [BLAIR]
    check = dbmod.direct(url, autocommit=True)
    try:
        rows = check.execute("select owner_id from bd.task_batches where kind = 'friday'"
                             " and week_start = '2026-11-09'").fetchall()
    finally:
        check.close()
    assert [r["owner_id"] for r in rows] == [AVERY]


def test_ten_more_on_the_weekend_skips_next_weeks_open_list(bd_seeded, bd_db, bd_today):
    """Finding: after Friday 16:00 built next week's list, Give Me 10 More on Saturday picked
    people who are open on it. Anyone open on a later week's list is left out now. A contact Avery
    adds on Saturday (never reached, not confirmed: 48) is the only one left for the extra ten."""
    bd_today("2026-11-06")
    nxt = weekly.build_batch(bd_db, AVERY, "2026-11-06")["batch"]["id"]
    assert {r["contact_id"] for r in _tasks(bd_db, nxt)} == {31, 21, 27, 23, 25}
    co = bd_db.execute("insert into bd.companies (name, normalized_name) values ('Test Mill', 'test mill')"
                       " returning id").fetchone()["id"]
    added = bd_db.execute("insert into bd.contacts (company_id, name, phone, email, category, owner_id)"
                          " values (%s, 'Kit Test', '913-555-0150', 'kit@example.com', 'bd', 1) returning id",
                          (co,)).fetchone()["id"]
    day = bd_today("2026-11-07")
    res = weekly.ten_more(bd_db, AVERY, day)
    assert [(p["contact_id"], p["kind"], p["score"]) for p in res["picks"]] == [(added, "new", 48)]
    # This week's lists in any state are 30, 21, 25 (batch 201) and the extra ten's `added`.
    assert set(weekly.load_facts(bd_db, AVERY, D("2026-11-02"), any_status=True)) == {
        30, 21, 25, added, 31, 27, 23}
    # A done one on next week's list no longer counts there (only OPEN tasks of a later week do).
    bd_db.execute("update bd.tasks set status = 'done' where batch_id = %s", (nxt,))
    assert set(weekly.load_facts(bd_db, AVERY, D("2026-11-02"), any_status=True)) == {30, 21, 25, added}
    # The Friday build's facts (open tasks of that week only): the rollover snoozed 301 and 302,
    # 303 is done, and only the extra ten's task is open.
    assert set(weekly.load_facts(bd_db, AVERY, D("2026-11-02"), any_status=False)) == {added}


def test_a_forced_re_run_closes_a_reopened_task_of_a_replaced_batch(bd_seeded, bd_db, bd_today):
    """Finding: force, reopen a task of the now-replaced batch, force again: the reopened task stayed
    open (the rollover skipped replaced batches) and its contact was left out of the new list. Every
    Friday batch of the week closes now."""
    day = bd_today("2026-11-04")
    first = weekly.build_batch(bd_db, AVERY, day, week_start="2026-11-02", force=True)
    assert [(r["id"], r["status"]) for r in _tasks(bd_db, 201)] == [
        (301, "snoozed"), (302, "snoozed"), (303, "done")]
    bd_db.execute("update bd.tasks set status = 'open', snoozed_until = null where id = 301")
    second = weekly.build_batch(bd_db, AVERY, day, week_start="2026-11-02", force=True)
    assert second["replaced"] == [first["batch"]["id"]]
    row = bd_db.execute("select status, snoozed_until from bd.tasks where id = 301").fetchone()
    assert (row["status"], row["snoozed_until"]) == ("snoozed", D("2026-11-02"))
    assert bd_db.execute("select count(*) as n from bd.tasks t join bd.task_batches b on b.id = t.batch_id"
                         " where b.week_start = '2026-11-02' and b.kind = 'friday' and t.status = 'open'"
                         " and b.owner_id = 1 and b.id <> %s", (second["batch"]["id"],)).fetchone()["n"] == 0


def test_run_due_catches_up_and_respects_off(bd_seeded, bd_db, bd_today):
    bd_today("2026-11-07")
    appsettings.store(bd_db, {"weekly": {"enabled": False}})
    assert weekly.run_due(bd_db, "2026-11-07T10:00:00-06:00") == []
    appsettings.store(bd_db, {"weekly": {"enabled": True}})
    built = weekly.run_due(bd_db, "2026-11-07T10:00:00-06:00")
    assert [(b["owner_id"], b["week_start"]) for b in built] == [(AVERY, D("2026-11-09")), (BLAIR, D("2026-11-09"))]


def test_scoring_day_overrides_the_connection_for_its_own_transaction(bd_seeded, bd_db, bd_today):
    """The session's business date is 2026-11-04; ranking as of 2026-11-13 must equal ranking on a
    connection whose business date IS 2026-11-13, and leave the session at 2026-11-04."""
    as_of_13 = _slim(weekly.rank(bd_db, AVERY, "2026-11-13"))
    assert bd_db.execute("select bd_today() as d").fetchone()["d"] == D("2026-11-04")
    bd_today("2026-11-13")
    assert _slim(weekly.rank(bd_db, AVERY, "2026-11-13")) == as_of_13
    bd_today("2026-11-04")
    assert _slim(weekly.rank(bd_db, AVERY, "2026-11-04")) != as_of_13


def test_bad_arguments(bd_seeded, bd_db):
    with pytest.raises(ValueError):
        weekly.build_batch(bd_db, AVERY, "2026-11-06", week_start="2026-11-10")
    with pytest.raises(ValueError):
        weekly.build_batch(bd_db, AVERY, "2026-11-06", kind="monthly")
    with pytest.raises(ValueError):
        weekly.build_batch(bd_db, AVERY, None)


def test_the_weekly_batch_never_calls_the_model():
    import pathlib
    src = (pathlib.Path(weekly.__file__)).read_text(encoding="utf-8") + \
        (pathlib.Path(weekly.priority.__file__)).read_text(encoding="utf-8")
    for word in ("subprocess", "claude", "anthropic", "datetime.now(", "date.today("):
        assert word not in src.lower(), word
