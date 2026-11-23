"""backend/bd/priority.py against frontend/bd/js/bd-core.js (BDCore.scoreContact, reasonText).

Three checks:
  * A HAND-BUILT TABLE of contacts, one or two rules each, with the whole expected answer (score,
    every reason in order, exclusion). Each row runs through priority.py AND through bd-core.js
    (node, the harness test_bd_core_js uses), so the table is checked against the reference too.
  * The shared table of tests/test_bd_core_js.py (imported: a row changed there is changed here).
  * THE MAINTENANCE EXCLUSION (4th, after archived / on the list / tried in the last 3 days): a
    maintenance contact that is not due is excluded ("maintenance, not due yet") but still scored,
    and maintenance_due_reason's three sentences, in Python and in bd-core.js.
  * 300 RANDOM fictional contacts + facts on random days (DST weeks, a leap day, UTC "Z" stamps,
    text numbers, bad frequencies, future dates), scored by both: identical score, reasons and
    exclusion, word for word.
  * THE DATABASE HALF: the fixture seed's contacts_summary rows (dates and aware datetimes) scored
    in Python give what bd-core.js gives for the same contacts as the API sends them (text), and
    a few of them are worked by hand.
"""
import datetime as dt
import json
import random

import pytest

from bd import bizdate
from bd import priority
from _node import last_json_line, run_node
from test_bd_core_js import CORE, HARNESS, PROMISE_CASES, SCORE_CASES, TODAY, contact

DST_DAYS = ["2026-03-06", "2026-03-08", "2026-03-09", "2026-10-30", "2026-11-01", "2026-11-02"]
NEED4 = "needs 4 a year"
CONFIRM = "Needs confirming: still the right person?"


def at(day, hhmm="10:00"):
    """A Central timestamp with the offset that day really has ("...-05:00" in summer)."""
    return bizdate.to_iso_central(dt.datetime.fromisoformat(day + "T" + hhmm).replace(tzinfo=bizdate.BIZ_TZ))


# ── the hand-built table: (id, contact, facts, today, expected) ─────────────────────────────────
def row(score, reasons, excluded=False, why=None):
    return {"score": score, "reasons": reasons, "excluded": excluded, "exclude_reason": why}


TABLE = [
    ("never_contacted", contact(1), {}, TODAY, row(40, ["Never contacted"])),
    ("never_reached_one_try", contact(1, attempts_since_live=1, last_attempt_at=at("2026-10-20")), {}, TODAY,
     row(45, ["Never reached after 1 try"])),
    ("never_reached_tries_capped", contact(1, attempts_since_live=5, last_attempt_at=at("2026-10-20")), {}, TODAY,
     row(55, ["Never reached after 5 tries"])),
    # Cadence: 30 days since, interval 91.25: round(9.86) = 10.
    ("cadence_partial", contact(1, last_live_at=at("2026-10-05")), {}, TODAY,
     row(10, ["Last live talk 4 weeks ago; " + NEED4])),
    ("cadence_cap_40", contact(1, last_live_at=at("2024-06-01")), {}, TODAY,
     row(40, ["Last live talk 29 months ago; " + NEED4])),
    # Live talk today: cadence 0 adds nothing and says nothing.
    ("cadence_zero_today", contact(1, last_live_at=at("2026-11-04", "08:00")), {}, TODAY, row(0, [])),
    # Maintenance: interval 120 whatever the frequency; 60 days -> 15; needs 3.
    ("maintenance_interval_120", contact(1, 12, category="maintenance", maintenance_due=True,
                                         last_live_at=at("2026-09-05")), {}, TODAY,
     row(15, ["Last live talk 2 months ago; needs 3 a year"])),
    # Frequency 12: interval 30.4166..., 20 days -> round(19.73) = 20.
    ("frequency_twelve", contact(1, 12, last_live_at=at("2026-10-15")), {}, TODAY,
     row(20, ["Last live talk 2 weeks ago; needs 12 a year"])),
    ("promised_due_today", contact(1, last_live_at=at("2026-10-28"), promised_date="2026-11-04"), {}, TODAY,
     row(52, ["Promised a call by Wed, Nov 4", "Last live talk 7 days ago; " + NEED4])),
    ("next_step_in_7_days", contact(1, last_live_at=at("2026-10-28"), next_step_date="2026-11-11"), {}, TODAY,
     row(27, ["Next step due Wed, Nov 11", "Last live talk 7 days ago; " + NEED4])),
    ("next_step_in_8_days_nothing", contact(1, last_live_at=at("2026-10-28"), next_step_date="2026-11-12"), {}, TODAY,
     row(2, ["Last live talk 7 days ago; " + NEED4])),
    # The EARLIER date wins; on the same day the promise wins the words.
    ("earlier_of_two_dates", contact(1, last_live_at=at("2026-10-28"), promised_date="2026-11-10",
                                     next_step_date="2026-11-03"), {}, TODAY,
     row(52, ["Next step due Tue, Nov 3", "Last live talk 7 days ago; " + NEED4])),
    ("same_day_promise_wins", contact(1, promised_date="2026-11-02", next_step_date="2026-11-02"), {}, TODAY,
     row(90, ["Promised a call by Mon, Nov 2", "Never contacted"])),
    ("quote_30_days_ago", contact(1, last_quote_date="2026-10-05"), {}, TODAY,
     row(55, ["Never contacted", "Recent quote activity (Mon, Oct 5)"])),
    ("quote_31_days_ago_nothing", contact(1, last_quote_date="2026-10-04"), {}, TODAY, row(40, ["Never contacted"])),
    ("quote_as_a_fact", contact(1), {"last_quote_date": "2026-11-01"}, TODAY,
     row(55, ["Never contacted", "Recent quote activity (Sun, Nov 1)"])),
    ("key_account", contact(1, importance=3), {}, TODAY, row(60, ["Never contacted", "Key account"])),
    ("tries_since_live_words", contact(1, last_live_at=at("2026-10-28"), attempts_since_live=2,
                                       last_attempt_at=at("2026-10-30")), {}, TODAY,
     row(12, ["2 tries since the last live talk", "Last live talk 7 days ago; " + NEED4])),
    ("unconfirmed", contact(1, confirmed=False, last_live_at=at("2026-10-28")), {}, TODAY,
     row(10, [CONFIRM, "Last live talk 7 days ago; " + NEED4])),
    # Only `confirmed: false` adds +8: null (unknown) does not.
    ("confirmed_null_no_points", contact(1, confirmed=None), {}, TODAY, row(40, ["Never contacted"])),
    # Equal points keep the order they were added: key account (+20) before... a 20-point cadence.
    ("tie_keeps_rule_order", contact(1, 12, importance=3, last_live_at=at("2026-10-15")), {}, TODAY,
     row(40, ["Last live talk 2 weeks ago; needs 12 a year", "Key account"])),
    ("everything", contact(1, importance=3, confirmed=False, attempts_since_live=4, promised_date="2026-11-01",
                           last_quote_date="2026-10-20", last_attempt_at=at("2026-10-25")), {}, TODAY,
     row(148, ["Promised a call by Sun, Nov 1", "Never reached after 4 tries", "Key account",
               "Recent quote activity (Tue, Oct 20)", CONFIRM])),
    # Exclusions, in order: archived, then on the list, then tried in the last 3 days.
    ("archived", contact(1, archived_at=at("2026-10-01")), {"has_open_task": True}, TODAY,
     row(40, ["Never contacted"], True, "archived")),
    ("on_the_list", contact(1, last_attempt_at=at("2026-11-04", "08:00")), {"has_open_task": True}, TODAY,
     row(40, ["Never contacted"], True, "already in this week's list")),
    ("tried_2_days_ago", contact(1, last_attempt_at=at("2026-11-02")), {"has_open_task": False}, TODAY,
     row(40, ["Never contacted"], True, "tried in the last 3 days")),
    ("tried_3_days_ago_back", contact(1, last_attempt_at=at("2026-11-01")), {}, TODAY, row(40, ["Never contacted"])),
    # Exclusion 4: a maintenance contact is on a list only when due. Excluded, but still scored.
    ("maintenance_not_due", contact(1, 3, category="maintenance", maintenance_due=False,
                                    last_live_at=at("2026-09-05")), {}, TODAY,
     row(15, ["Last live talk 2 months ago; needs 3 a year"], True, "maintenance, not due yet")),
    ("maintenance_due_field_missing_is_not_due", contact(1, 3, category="maintenance"), {}, TODAY,
     row(40, ["Never contacted"], True, "maintenance, not due yet")),
    ("maintenance_due_null_is_not_due", contact(1, 3, category="maintenance", maintenance_due=None), {}, TODAY,
     row(40, ["Never contacted"], True, "maintenance, not due yet")),
    ("maintenance_due_is_in", contact(1, 3, category="maintenance", maintenance_due=True), {}, TODAY,
     row(40, ["Never contacted"])),
    ("maintenance_due_as_a_fact", contact(1, 3, category="maintenance", maintenance_due=False),
     {"maintenance_due": True}, TODAY, row(40, ["Never contacted"])),
    ("bd_ignores_the_due_flag_false", contact(1, maintenance_due=False), {}, TODAY, row(40, ["Never contacted"])),
    # The four exclusions in order: each earlier one wins the reason over "not due yet".
    ("archived_beats_not_due", contact(1, 3, category="maintenance", maintenance_due=False,
                                       archived_at=at("2026-10-01")), {"has_open_task": True}, TODAY,
     row(40, ["Never contacted"], True, "archived")),
    ("on_the_list_beats_not_due", contact(1, 3, category="maintenance", maintenance_due=False,
                                          last_attempt_at=at("2026-11-04", "08:00")), {"has_open_task": True}, TODAY,
     row(40, ["Never contacted"], True, "already in this week's list")),
    ("tried_recently_beats_not_due", contact(1, 3, category="maintenance", maintenance_due=False,
                                             last_attempt_at=at("2026-11-02")), {}, TODAY,
     row(40, ["Never contacted"], True, "tried in the last 3 days")),
    ("due_but_tried_recently", contact(1, 3, category="maintenance", maintenance_due=True,
                                       last_attempt_at=at("2026-11-02")), {}, TODAY,
     row(40, ["Never contacted"], True, "tried in the last 3 days")),
    ("due_but_on_the_list", contact(1, 3, category="maintenance", maintenance_due=True), {"has_open_task": True},
     TODAY, row(40, ["Never contacted"], True, "already in this week's list")),
    # The cooling-off counts Central days: 23:30 CST on Nov 1 is Nov 2 in UTC but Nov 1 here.
    ("cooling_off_central_day", contact(1, last_attempt_at="2026-11-02T05:30:00Z"), {}, TODAY,
     row(40, ["Never contacted"])),
    # Spring forward: Mar 8 2026 has 23 hours; the day count is still 1.
    ("dst_spring_day_count", contact(1, last_live_at=at("2026-03-07", "23:30")), {}, "2026-03-08", row(0, [])),
    ("dst_fall_day_count", contact(1, last_live_at=at("2026-10-31", "23:30"), promised_date="2026-11-02"), {},
     "2026-11-01", row(25, ["Promised a call by Mon, Nov 2"])),
]


def _harness(cases, tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    proc = run_node(HARNESS, CORE, path)
    assert proc.returncode == 0, "the bd-core harness failed:\n" + proc.stderr
    out = last_json_line(proc.stdout)
    assert out["vm_disagrees"] == []
    return out["results"]


@pytest.mark.parametrize("cid, c, facts, today, expected", TABLE, ids=[t[0] for t in TABLE])
def test_the_table_in_python(cid, c, facts, today, expected):
    assert priority.score(c, facts, today) == expected


def test_the_table_is_what_bd_core_js_says(tmp_path):
    results = _harness([{"id": t[0], "fn": "scoreContact", "args": [t[1], t[2], t[3]]} for t in TABLE], tmp_path)
    wrong = {t[0]: results[t[0]] for t in TABLE if results[t[0]] != t[4]}
    assert not wrong, wrong


def test_the_table_covers_every_factor_and_exclusion():
    reasons = " | ".join(r for t in TABLE for r in t[4]["reasons"])
    for words in ("Never contacted", "Never reached after", "Last live talk", "Promised a call by",
                  "Next step due", "Recent quote activity", "Key account", "since the last live talk", CONFIRM):
        assert words in reasons, words
    assert {t[4]["exclude_reason"] for t in TABLE} == {None, "archived", "already in this week's list",
                                                       "tried in the last 3 days", "maintenance, not due yet"}
    assert len(TABLE) >= 20


# ── the due reason: the first reason of a maintenance task ─────────────────────────────────────
def due(cid, due_date=None, followed_up="2026-07-01T10:00:00-05:00", **kw):
    """A due maintenance contact as the view hands it over (date text); never followed up when
    due_date is None."""
    return contact(cid, 3, category="maintenance", maintenance_due=True, maintenance_due_date=due_date,
                   last_followup_at=followed_up if due_date else None, **kw)


DUE_REASONS = [
    ("never_followed_up", due(1), TODAY, "No follow-up logged yet"),
    ("due_today", due(1, TODAY), TODAY, "Follow-up due today"),
    ("was_due_yesterday", due(1, "2026-11-03"), TODAY, "Follow-up was due Tue, Nov 3"),
    ("was_due_months_ago", due(1, "2026-05-21"), TODAY, "Follow-up was due Thu, May 21"),
    ("was_due_last_year", due(1, "2025-12-31"), TODAY, "Follow-up was due Wed, Dec 31"),
    # No follow-up at all wins over a stray date; no date at all says the same.
    ("no_followup_wins", contact(1, 3, category="maintenance", maintenance_due=True,
                                 maintenance_due_date="2026-10-01", last_followup_at=None), TODAY,
     "No follow-up logged yet"),
    ("no_date_says_never", contact(1, 3, category="maintenance", maintenance_due=True,
                                   last_followup_at="2026-07-01T10:00:00-05:00"), TODAY,
     "No follow-up logged yet"),
]
# What a database row holds (a date, an aware datetime) reads the same as its text.
DUE_REASONS_FROM_THE_DATABASE = [
    ("a_date_object", due(1, dt.date(2026, 10, 23)), TODAY, "Follow-up was due Fri, Oct 23"),
    ("today_as_a_date", due(1, TODAY), dt.date.fromisoformat(TODAY), "Follow-up due today"),
    ("an_aware_datetime", contact(1, 3, category="maintenance", maintenance_due=True,
                                  maintenance_due_date=dt.date(2026, 10, 23),
                                  last_followup_at=dt.datetime(2026, 6, 25, 14, 5, tzinfo=dt.UTC)), TODAY,
     "Follow-up was due Fri, Oct 23"),
]


@pytest.mark.parametrize("cid, c, today, want", DUE_REASONS + DUE_REASONS_FROM_THE_DATABASE,
                         ids=[d[0] for d in DUE_REASONS + DUE_REASONS_FROM_THE_DATABASE])
def test_maintenance_due_reason(cid, c, today, want):
    assert priority.maintenance_due_reason(c, today) == want


def test_maintenance_due_reason_matches_bd_core_js(tmp_path):
    results = _harness([{"id": d[0], "fn": "maintenanceDueReason", "args": [d[1], d[2]]} for d in DUE_REASONS], tmp_path)
    assert {d[0]: results[d[0]] for d in DUE_REASONS} == {d[0]: d[3] for d in DUE_REASONS}


def test_maintenance_due_reason_needs_today():
    with pytest.raises(ValueError):
        priority.maintenance_due_reason(due(1), None)


@pytest.mark.parametrize("cid, c, facts, score, reasons", SCORE_CASES, ids=[c[0] for c in SCORE_CASES])
def test_the_shared_table(cid, c, facts, score, reasons):
    got = priority.score(c, facts, TODAY)
    if score is not None:
        assert got["score"] == score
    if reasons is not None:
        assert got["reasons"][:len(reasons)] == reasons


@pytest.mark.parametrize("cid, date, score", PROMISE_CASES, ids=[c[0] for c in PROMISE_CASES])
def test_the_shared_promise_window(cid, date, score):
    c = contact(1, last_live_at="2026-10-28T10:00:00-05:00", promised_date=date)
    assert priority.score(c, {}, TODAY)["score"] == score


@pytest.mark.parametrize("reasons, text", [
    ([], ""),
    (None, ""),
    (["Never contacted"], "Never contacted."),
    (["Promised a call by Fri, Nov 6", "Key account", "Third"], "Promised a call by Fri, Nov 6. Key account."),
    ([CONFIRM, "Never contacted"], CONFIRM + " Never contacted."),
    (["Done.", "Really!"], "Done. Really!"),
])
def test_reason_text(reasons, text):
    assert priority.reason_text(reasons) == text


def test_reason_text_matches_bd_core_js(tmp_path):
    cases = [[], ["a"], ["a.", "b?", "c"], ["x!", "y"], [CONFIRM, "Key account"]]
    results = _harness([{"id": str(n), "fn": "reasonText", "args": [c]} for n, c in enumerate(cases)], tmp_path)
    assert [results[str(n)] for n in range(len(cases))] == [priority.reason_text(c) for c in cases]


def test_today_is_required():
    with pytest.raises(ValueError):
        priority.score(contact(1), {}, None)


# ── random cases through bd-core.js itself ─────────────────────────────────────────────────────
RANDOM_DAYS = [TODAY, "2026-11-06", "2026-01-01", "2026-12-31", "2028-02-29"] + DST_DAYS


def _moment(rnd, today, back_days, ahead_days=0):
    """A random moment around `today`, written as the app writes it (Central + offset), or now
    and then as UTC "Z" text or a bare date."""
    base = dt.datetime.fromisoformat(today + "T12:00").replace(tzinfo=bizdate.BIZ_TZ)
    t = base + dt.timedelta(seconds=rnd.randint(-back_days * 86400, ahead_days * 86400))
    pick = rnd.random()
    if pick < 0.1:
        return t.astimezone(bizdate.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if pick < 0.15:
        return t.astimezone(bizdate.BIZ_TZ).date().isoformat()
    return bizdate.to_iso_central(t)


def _date(rnd, today, lo, hi):
    return (dt.date.fromisoformat(today) + dt.timedelta(days=rnd.randint(lo, hi))).isoformat()


def _random_cases(n=300, seed=20261106):
    rnd = random.Random(seed)
    cases = []
    for k in range(n):
        today = rnd.choice(RANDOM_DAYS)
        c = {"id": k + 1, "name": "Person %d" % (k + 1),
             "category": rnd.choice(["bd", "bd", "maintenance"]),
             "frequency_per_year": rnd.choice([None, 0, -2, 1, 2, 3, 4, 4, 4, 6, 12, 52, "4", "abc", 2.5]),
             "confirmed": rnd.choice([True, True, False, None]),
             "importance": rnd.choice([None, 1, 1, 2, 3, "3", 0, 5]),
             "attempts_since_live": rnd.choice([None, 0, 0, 1, 2, 3, 4, 7]),
             "last_live_at": None if rnd.random() < 0.3 else _moment(rnd, today, 900, 3),
             "last_attempt_at": None if rnd.random() < 0.3 else _moment(rnd, today, 12, 1),
             "promised_date": None if rnd.random() < 0.6 else _date(rnd, today, -40, 15),
             "next_step_date": None if rnd.random() < 0.6 else _date(rnd, today, -40, 15),
             "last_quote_date": None if rnd.random() < 0.7 else _date(rnd, today, -60, 3),
             "touches_this_year": rnd.randint(0, 5)}
        if rnd.random() < 0.05:
            c["archived_at"] = _moment(rnd, today, 30)
        # The follow-up clock a maintenance contact brings (field absent, null, true or false, as
        # a stored row, a stale object and a hand-built dict give it), so exclusion 4 is reached.
        due_flag = rnd.choice([True, True, False, None, "absent"])
        if due_flag != "absent":
            c["maintenance_due"] = due_flag
        if rnd.random() < 0.7:
            c["last_followup_at"] = _moment(rnd, today, 400)
            c["maintenance_due_date"] = _date(rnd, today, -90, 30)
        facts = rnd.choice([{}, {"has_open_task": False}, {"has_open_task": True},
                            {"has_open_task": False, "last_quote_date": _date(rnd, today, -35, 0)},
                            {"has_open_task": False, "maintenance_due": True},
                            {"has_open_task": False, "maintenance_due": False}])
        cases.append({"id": "r%d" % k, "fn": "scoreContact", "args": [c, facts, today]})
    return cases


def test_random_contacts_score_exactly_as_bd_core_js(tmp_path):
    cases = _random_cases()
    results = _harness(cases, tmp_path)
    wrong = []
    for case in cases:
        want = results[case["id"]]
        got = priority.score(*case["args"])
        if json.dumps(got, sort_keys=True) != json.dumps(want, sort_keys=True):
            wrong.append((case["args"], want, got))
    assert not wrong, "%d of %d differ; first: %r" % (len(wrong), len(cases), wrong[:3])
    # The random set really reaches every branch.
    joined = " | ".join(r for c in cases for r in results[c["id"]]["reasons"])
    for words in ("Never contacted", "Never reached after", "Last live talk", "Promised a call by",
                  "Next step due", "Recent quote activity", "Key account", "since the last live talk", CONFIRM,
                  "months ago", "weeks ago", "days ago"):
        assert words in joined, words
    whys = {results[c["id"]]["exclude_reason"] for c in cases}
    assert whys == {None, "archived", "already in this week's list", "tried in the last 3 days",
                    "maintenance, not due yet"}
    # ... and exclusion 4 really is the only thing between a maintenance contact and the list.
    due_in = [c for c in cases if c["args"][0]["category"] == "maintenance"
              and not results[c["id"]]["excluded"]]
    assert len(due_in) > 10
    assert all(c["args"][0].get("maintenance_due") or c["args"][1].get("maintenance_due") for c in due_in)


def test_random_due_reasons_match_bd_core_js(tmp_path):
    rnd = random.Random(1110)
    cases = []
    for k in range(60):
        today = rnd.choice(RANDOM_DAYS)
        followed = rnd.random() < 0.8
        c = contact(k + 1, 3, category="maintenance", maintenance_due=True,
                    last_followup_at=_moment(rnd, today, 400) if followed else None,
                    maintenance_due_date=_date(rnd, today, -200, 0) if rnd.random() < 0.9 else None)
        cases.append({"id": "d%d" % k, "fn": "maintenanceDueReason", "args": [c, today]})
    results = _harness(cases, tmp_path)
    wrong = [(c["args"], results[c["id"]], priority.maintenance_due_reason(*c["args"])) for c in cases
             if results[c["id"]] != priority.maintenance_due_reason(*c["args"])]
    assert not wrong, wrong[:3]
    assert "No follow-up logged yet" in results.values()
    assert any(r.startswith("Follow-up was due") for r in results.values())


# -- the database half: the fixture seed's rows ---------------------------------------------------
# Worked by hand on Wed Nov 4 with no open task (bd/ops/fixture_seed.py):
#   Dana (21)  live call Oct 20 (15 days, x 30 / 91.25 = 4.93 -> 5); promised a call by Thu Nov 5,
#              within 7 days, +25 (her next step, Nov 6, is the later date); quote Oct 15 (20 days)
#              +15; key account +20; the Nov 2 voicemail is 1 try since +5 = 70; tried 2 days ago.
#   Priya (25) never reached after 1 try +40 +5; not confirmed +8 = 53; tried yesterday.
#   Lena (27)  never contacted +40; key account +20; not confirmed +8 = 68.
#   Hal (30)   maintenance; live call Aug 20 (76 days, x 30 / 120 = 19); not confirmed +8 = 27;
#              followed up Aug 20, due Dec 18: not due yet.
#   Nora (31)  maintenance, never followed up (due); never contacted +40; not confirmed +8 = 48.
DB_WORKED = {
    21: (70, True, "tried in the last 3 days"),
    25: (53, True, "tried in the last 3 days"),
    27: (68, False, None),
    30: (27, True, "maintenance, not due yet"),
    31: (48, False, None),
}


def _seed_rows(db):
    return {r["id"]: r for r in db.execute("select * from bd.contacts_summary order by id").fetchall()}


def test_the_fixture_seeds_rows_worked_by_hand(bd_seeded, bd_db):
    rows = _seed_rows(bd_db)
    for cid, (score, excluded, why) in DB_WORKED.items():
        got = priority.score(rows[cid], {"has_open_task": False}, bd_seeded["today"])
        assert (got["score"], got["excluded"], got["exclude_reason"]) == (score, excluded, why), cid
    assert priority.score(rows[27], {"has_open_task": False}, bd_seeded["today"])["reasons"] == [
        "Never contacted", "Key account", CONFIRM]
    # On this week's list already: that exclusion comes before "tried in the last 3 days".
    assert priority.score(rows[21], {"has_open_task": True}, bd_seeded["today"])["exclude_reason"] ==         "already in this week's list"


def test_the_fixture_seeds_rows_score_like_bd_core_js(bd_seeded, bd_db, tmp_path):
    """contacts_summary rows hold dates and aware datetimes; bd-core.js gets the same contacts as
    the API sends them (serialize.contact: text). Both must agree, for every contact, with and
    without an open task."""
    from bd import serialize

    rows = _seed_rows(bd_db)
    today = bd_seeded["today"].isoformat()
    cases = []
    for cid, row in rows.items():
        for facts in ({"has_open_task": False}, {"has_open_task": True}):
            cases.append({"id": "%d:%s" % (cid, facts["has_open_task"]), "fn": "scoreContact",
                          "args": [serialize.contact(row), facts, today], "row": cid})
    results = _harness([{k: v for k, v in c.items() if k != "row"} for c in cases], tmp_path)
    wrong = []
    for case in cases:
        got = priority.score(rows[case["row"]], case["args"][1], bd_seeded["today"])
        if got != results[case["id"]]:
            wrong.append((case["id"], results[case["id"]], got))
    assert not wrong, wrong[:3]
    assert len(rows) == 13
