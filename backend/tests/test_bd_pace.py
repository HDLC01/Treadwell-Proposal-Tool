"""backend/bd/pace.py against frontend/bd/js/bd-core.js (BDCore.pace, weeklyProgress).

Two checks:
  * the SAME case table as tests/test_bd_core_js.py (imported, so a row changed there is a row
    changed here), run through pace.py in plain Python;
  * a few hundred random cases run through BOTH pace.py and bd-core.js itself (node, the same
    harness test_bd_core_js uses), which must agree on every field. That is what catches a
    rounding difference: JavaScript's Math.round sends halves towards +infinity (-14.5 -> -14).
"""
import json
import random

import pytest

from bd import pace
from _node import last_json_line, run_node
from test_bd_core_js import CORE, HARNESS, PACE_CASES, act, contact

DASH = "—"


@pytest.mark.parametrize("cid, args, expected", PACE_CASES, ids=[c[0] for c in PACE_CASES])
def test_pace_matches_the_shared_table(cid, args, expected):
    got = pace.pace(*args)
    assert got["year"] == int(args[2][:4]) and got["as_of"] == args[2]
    for key, value in expected.items():
        assert got[key] == value, "%s: %s is %r, expected %r" % (cid, key, got[key], value)
    assert set(got) == {"year", "as_of", "required_to_date", "completed", "target_total", "pct",
                        "delta", "label"}


def test_weekly_progress_matches_the_shared_table():
    tasks = [{"status": "done"}] * 7 + [{"status": "open"}, {"status": "snoozed"}, {"status": "open"}]
    assert pace.weekly_progress(tasks) == {"done": 7, "total": 10, "label": "7 of 10 done"}
    assert pace.weekly_progress([]) == {"done": 0, "total": 0, "label": "0 of 0 done"}
    assert pace.weekly_progress(None) == {"done": 0, "total": 0, "label": "0 of 0 done"}


@pytest.mark.parametrize("x, want", [(0.5, 1), (1.5, 2), (2.5, 3), (-0.5, 0), (-14.5, -14),
                                     (-14.6, -15), (-14.4, -14), (12.49, 12), (0, 0)])
def test_js_round_sends_halves_up(x, want):
    from fractions import Fraction
    assert pace.js_round(Fraction(str(x))) == want


def test_a_half_behind_rounds_towards_plus_infinity():
    # target 10 on 2026-02-19 (day 50): required = round(10 * 10 * 50 / 365) / 10 = 13.7;
    # completed - required is never a tie there, so build the tie directly: 61 - 75.5 = -14.5.
    from fractions import Fraction
    assert pace.js_round(61 - Fraction(755, 10)) == -14
    got = pace.pace_from_totals(10, 61, "2026-01-01")
    assert got["required_to_date"] == 0.0 and got["delta"] == 61
    # 1 of 8 is 12.5%: a positive half goes up.
    assert pace.pace_from_totals(8, 1, "2026-01-01")["pct"] == 13


def test_pace_from_totals_equals_pace():
    contacts = [contact(i, (i % 5) + 1) for i in range(1, 30)]
    ints = [act(3, "call", "2026-04-0%d" % d, "answered") for d in range(1, 8)]
    full = pace.pace(contacts, ints, "2026-11-04")
    assert pace.pace_from_totals(full["target_total"], full["completed"], "2026-11-04") == full


@pytest.mark.parametrize("value, category, want", [
    (5, "bd", 5), (0, "bd", 4), (None, "bd", 4), (-2, "bd", 4), ("6", "bd", 6), ("x", "bd", 4),
    ("", "maintenance", 3), (0, "maintenance", 3), (2, "maintenance", 2), (float("nan"), "bd", 4)])
def test_freq_of_falls_back_to_the_category_default(value, category, want):
    assert pace.freq_of({"frequency_per_year": value, "category": category}) == want


def test_the_counting_rule_ignores_a_counts_as_touch_flag():
    assert pace.is_touch({"kind": "meeting"}) and pace.is_touch({"kind": "hosted"})
    assert pace.is_touch({"kind": "call", "outcome": "answered"})
    assert pace.is_touch({"kind": "call", "outcome": "meeting_set"})
    for i in ({"kind": "call", "outcome": "no_answer"}, {"kind": "voicemail", "outcome": "voicemail"},
              {"kind": "email", "counts_as_touch": True}, {"kind": "sms"}, {"kind": "note"}, None, {}):
        assert not pace.is_touch(i)


def test_central_dates_decide_the_year():
    c = [contact(1, 4)]
    # 23:30 Central on Dec 31 is already Jan 1 in UTC: it is last year's touch.
    late = act(1, "call", "2025-12-31T23:30:00-06:00", "answered")
    utc_new_year = act(1, "call", "2026-01-01T05:30:00Z", "answered")   # 23:30 Central, Dec 31
    first = act(1, "meeting", "2026-01-01T00:10:00-06:00")
    assert pace.pace(c, [late, utc_new_year, first], "2026-01-01")["completed"] == 1
    # A touch dated after today does not count yet.
    future = act(1, "meeting", "2026-01-02T08:00:00-06:00")
    assert pace.pace(c, [first, future], "2026-01-01")["completed"] == 1


def test_labels():
    assert pace.pace_label(2026, 68, -15) == "2026 BD Pace: 68% " + DASH + " 15 interactions behind pace"
    assert pace.pace_label(2026, 90, 1) == "2026 BD Pace: 90% " + DASH + " 1 interaction ahead of pace"
    assert pace.pace_label(2026, 50, 0) == "2026 BD Pace: 50% " + DASH + " right on pace"


# ── random cases through bd-core.js itself ───────────────────────────────────────────────────
def _random_cases(n=300, seed=20261104):
    rnd = random.Random(seed)
    kinds = [("call", "answered"), ("call", "meeting_set"), ("call", "no_answer"),
             ("voicemail", "voicemail"), ("meeting", None), ("hosted", None), ("email", None),
             ("note", None), ("sms", None)]
    cases = []
    for k in range(n):
        year = rnd.choice([2025, 2026, 2027, 2028])
        today = "%d-%02d-%02d" % (year, rnd.randint(1, 12), rnd.randint(1, 28))
        if rnd.random() < 0.1:
            today = "%d-12-31" % year
        contacts = []
        for cid in range(1, rnd.randint(0, 60) + 1):
            freq = rnd.choice([None, 0, 1, 2, 3, 4, 4, 4, 6, 12, 52, -1])
            contacts.append(contact(cid, freq, category=rnd.choice(["bd", "bd", "maintenance"])))
        ints = []
        for _ in range(rnd.randint(0, 120)):
            kind, outcome = rnd.choice(kinds)
            d = "%d-%02d-%02dT%02d:%02d:00%s" % (rnd.choice([year - 1, year, year, year + 1]),
                                                 rnd.randint(1, 12), rnd.randint(1, 28),
                                                 rnd.randint(0, 23), rnd.randint(0, 59),
                                                 rnd.choice(["-06:00", "-05:00", "Z"]))
            ints.append(act(rnd.randint(1, 70), kind, d, outcome))
        cases.append({"id": "rand:%d" % k, "fn": "pace", "args": [contacts, ints, today]})
    # Exact halves on delta: target 10 on day 1 gives required 0.0; build ties around .5 too.
    for k, (target, completed, day) in enumerate([(151, 61, "2026-07-02"), (73, 7, "2026-02-06"),
                                                  (365, 0, "2026-01-02"), (1, 0, "2026-07-02")]):
        cases.append({"id": "tie:%d" % k, "fn": "pace",
                      "args": [[contact(i, 1) for i in range(1, target + 1)],
                               [act(1, "meeting", "2026-01-01T10:00:00-06:00") for _ in range(completed)], day]})
    return cases


def test_pace_agrees_with_bd_core_js_on_random_cases(tmp_path):
    cases = _random_cases()
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    proc = run_node(HARNESS, CORE, path)
    assert proc.returncode == 0, proc.stderr
    js = last_json_line(proc.stdout)["results"]
    diffs = []
    for case in cases:
        want = js[case["id"]]
        got = pace.pace(*case["args"])
        if got != want:
            diffs.append("%s: python %r != js %r" % (case["id"], got, want))
    assert not diffs, "\n".join(diffs[:20])
