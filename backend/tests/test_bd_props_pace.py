"""Generated (property) coverage for backend/bd/pace.py, the annual pace bar.

tests/test_bd_pace.py pins a fixed case table and 300 random cases against bd-core.js. This file adds
invariants that must hold for EVERY input, found by hypothesis (deterministic on CI: conftest.py
registers the "ci" profile), and fills the gaps that table leaves:

  * js_round is floor(x + 1/2) on exact values: ties go towards +infinity, it is monotone and
    shifts with whole numbers;
  * pace_from_totals: year/as_of follow the date; required_to_date stays within [0, target], never
    goes down as the year goes on and is the whole target on Dec 31; delta and pct are exactly the
    JavaScript roundings of the exact quantities; pct is never negative and never falls when more
    is completed; the label has exactly the three shapes pace_label documents;
  * is_touch: kind meeting/hosted, or a call answered / meeting_set, and nothing else, whatever a
    `counts_as_touch` flag says;
  * freq_of: a positive number passes through, anything else is the category default;
  * pace(): agrees with an independent oracle that counts the touches itself (other owners'
    contacts, other years, later days, Central-day shifts of UTC timestamps), and with
    pace_from_totals over the same sums;
  * ONE batched node run of pace_from_totals-shaped cases through BDCore.pace.

Fictional data only; every date is passed in, nothing reads a clock.
"""
import calendar
import datetime as dt
import json
import re
import tempfile
from fractions import Fraction
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from bd import pace
from _node import last_json_line, run_node
from test_bd_core_js import CORE, HARNESS

DASH = "—"
FIRST = dt.date(2024, 1, 1)
LAST = dt.date(2030, 12, 31)

# ── strategies ───────────────────────────────────────────────────────────────────────────────
dates = st.dates(min_value=FIRST, max_value=LAST)
# Jan 1, Feb 28/29 and Dec 31 of leap and common years, so the edges are always in the mix.
edge_dates = st.sampled_from([dt.date(y, m, d) for y in (2024, 2025, 2026, 2028, 2029, 2030)
                              for (m, d) in ((1, 1), (2, 28), (3, 1), (12, 31))]
                             + [dt.date(2024, 2, 29), dt.date(2028, 2, 29)])
any_date = st.one_of(dates, edge_dates)
# A target is a whole number or a half (exact in JavaScript's floats too), 0..2000.
targets = st.one_of(st.integers(0, 2000), st.integers(0, 4000).map(lambda n: Fraction(n, 2)))
completed_counts = st.integers(0, 3000)
ratios = st.integers(-10_000, 10_000).flatmap(lambda n: st.integers(1, 40).map(lambda d: Fraction(n, d)))


def required_exact(target, day):
    """round(10 x target x day_of_year / days_in_year) / 10 with integer arithmetic only."""
    scaled = Fraction(10) * Fraction(target) * day.timetuple().tm_yday / (366 if calendar.isleap(day.year) else 365)
    return Fraction((scaled + Fraction(1, 2)) // 1, 10)


def exact(x: float) -> Fraction:
    """A short decimal float (13.7) as the exact decimal it prints as."""
    return Fraction(repr(x))


# ── js_round ─────────────────────────────────────────────────────────────────────────────────
@given(ratios)
def test_js_round_is_floor_of_x_plus_a_half(x):
    r = pace.js_round(x)
    assert isinstance(r, int)
    assert r - Fraction(1, 2) <= x < r + Fraction(1, 2)       # the nearest whole number, tie up


@given(st.integers(-5000, 5000))
def test_js_round_sends_every_half_towards_plus_infinity(n):
    assert pace.js_round(Fraction(2 * n + 1, 2)) == n + 1     # 14.5 -> 15, -14.5 -> -14, -0.5 -> 0
    assert pace.js_round(n) == n


@given(ratios, ratios)
def test_js_round_is_monotone(a, b):
    lo, hi = sorted((a, b))
    assert pace.js_round(lo) <= pace.js_round(hi)


@given(ratios, st.integers(-500, 500))
def test_js_round_shifts_with_whole_numbers(x, k):
    assert pace.js_round(x + k) == pace.js_round(x) + k


# ── pace_from_totals ─────────────────────────────────────────────────────────────────────────
@given(targets, completed_counts, any_date, st.booleans())
def test_the_year_and_as_of_follow_the_date(target, completed, day, as_text):
    got = pace.pace_from_totals(target, completed, day.isoformat() if as_text else day)
    assert got["year"] == day.year
    assert got["as_of"] == day.isoformat()
    assert got["completed"] == completed
    assert set(got) == {"year", "as_of", "required_to_date", "completed", "target_total", "pct",
                        "delta", "label"}
    assert got["target_total"] == target                      # echoed exactly (whole or half)


@given(targets, completed_counts, any_date)
def test_required_to_date_is_the_rounded_share_of_the_target_and_stays_inside_it(target, completed, day):
    got = pace.pace_from_totals(target, completed, day)
    required = exact(got["required_to_date"])
    assert required == required_exact(target, day)
    assert 0 <= required <= Fraction(target)
    assert (required * 10).denominator == 1                   # one decimal, nothing finer


@given(targets, st.integers(2024, 2030), st.integers(1, 366), st.integers(1, 366))
def test_required_to_date_never_goes_down_as_the_year_goes_on(target, year, a, b):
    ndays = (dt.date(year, 12, 31) - dt.date(year, 1, 1)).days + 1
    early, late = sorted((min(a, ndays), min(b, ndays)))
    d1 = dt.date(year, 1, 1) + dt.timedelta(days=early - 1)
    d2 = dt.date(year, 1, 1) + dt.timedelta(days=late - 1)
    r1 = pace.pace_from_totals(target, 0, d1)["required_to_date"]
    r2 = pace.pace_from_totals(target, 0, d2)["required_to_date"]
    assert r1 <= r2


@given(targets, completed_counts, st.integers(2024, 2030))
def test_on_the_last_day_of_the_year_the_whole_target_is_required(target, completed, year):
    got = pace.pace_from_totals(target, completed, dt.date(year, 12, 31))
    assert exact(got["required_to_date"]) == Fraction(target)
    assert got["delta"] == pace.js_round(completed - Fraction(target))


@given(targets, completed_counts, any_date)
def test_delta_is_the_rounded_gap_between_completed_and_required(target, completed, day):
    got = pace.pace_from_totals(target, completed, day)
    assert got["delta"] == pace.js_round(completed - exact(got["required_to_date"]))
    assert isinstance(got["delta"], int)


@given(targets, completed_counts, any_date)
def test_pct_is_the_rounded_percent_of_the_target_and_zero_without_one(target, completed, day):
    got = pace.pace_from_totals(target, completed, day)
    if target == 0:
        assert got["pct"] == 0                                # no target is 0%, never a division
    else:
        assert got["pct"] == pace.js_round(Fraction(100 * completed) / Fraction(target))
        assert got["pct"] >= 0
        share = Fraction(100 * completed) / Fraction(target)
        assert (got["pct"] == 100) == (Fraction(199, 2) <= share < Fraction(201, 2))


@given(targets, st.integers(0, 3000), st.integers(0, 3000), any_date)
def test_pct_never_falls_when_more_is_completed(target, a, b, day):
    lo, hi = sorted((a, b))
    assert pace.pace_from_totals(target, lo, day)["pct"] <= pace.pace_from_totals(target, hi, day)["pct"]
    # and the gap to the schedule grows with it
    assert pace.pace_from_totals(target, lo, day)["delta"] <= pace.pace_from_totals(target, hi, day)["delta"]


@given(any_date)
def test_missing_totals_are_zero(day):
    got = pace.pace_from_totals(None, None, day)
    assert (got["target_total"], got["completed"], got["pct"], got["required_to_date"]) == (0, 0, 0, 0.0)
    assert got["delta"] == 0 and got["label"] == "%d BD Pace: 0%% %s right on pace" % (day.year, DASH)


@given(targets, completed_counts, any_date)
def test_the_label_is_pace_label_of_the_numbers_beside_it(target, completed, day):
    got = pace.pace_from_totals(target, completed, day)
    assert got["label"] == pace.pace_label(got["year"], got["pct"], got["delta"])


LABEL = re.compile(r"^(\d{4}) BD Pace: (\d+)% " + DASH + r" (?:right on pace|(\d+) (interactions?) "
                                                          r"(ahead of pace|behind pace))$")


@given(st.integers(1900, 2999), st.integers(0, 100_000), st.integers(-5000, 5000))
def test_the_label_has_exactly_three_shapes(year, pct, delta):
    label = pace.pace_label(year, pct, delta)
    m = LABEL.match(label)
    assert m, label
    assert int(m.group(1)) == year and int(m.group(2)) == pct
    assert ("right on pace" in label) == (delta == 0)
    assert ("ahead" in label) == (delta > 0)
    assert ("behind" in label) == (delta < 0)
    if delta != 0:
        assert int(m.group(3)) == abs(delta)
        assert (m.group(4) == "interaction") == (abs(delta) == 1)   # singular only for one
        assert "-" not in label.split(DASH, 1)[1]                    # never "-3 interactions"


# ── is_touch ─────────────────────────────────────────────────────────────────────────────────
kinds = st.sampled_from(["meeting", "hosted", "call", "voicemail", "email", "sms", "note", "task",
                         "Meeting", "CALL", "", None, "visit"])
outcomes = st.sampled_from(["answered", "meeting_set", "no_answer", "voicemail", "busy", "Answered",
                            "", None, "left_message"])
flags = st.one_of(st.none(), st.booleans(), st.integers(-2, 2), st.just("true"), st.just("false"))


@given(kinds, outcomes, flags, st.booleans(), st.booleans())
def test_is_touch_is_the_counting_rule_and_never_the_flag(kind, outcome, flag, with_flag, with_outcome):
    i = {"kind": kind}
    if with_outcome:
        i["outcome"] = outcome
    if with_flag:
        i["counts_as_touch"] = flag
    effective_outcome = outcome if with_outcome else None
    want = kind in ("meeting", "hosted") or (kind == "call" and effective_outcome in ("answered", "meeting_set"))
    assert pace.is_touch(i) is want


@given(st.sampled_from([None, {}, [], 0, ""]))
def test_is_touch_is_false_for_nothing(i):
    assert pace.is_touch(i) is False


# ── freq_of ──────────────────────────────────────────────────────────────────────────────────
categories = st.sampled_from(["bd", "maintenance", "other", "", None, "Maintenance"])


def default_for(category):
    return pace.MAINTENANCE_TOUCHES if category == "maintenance" else pace.DEFAULT_FREQUENCY_BD


def test_the_two_category_defaults_are_the_documented_ones():
    assert (pace.MAINTENANCE_TOUCHES, pace.DEFAULT_FREQUENCY_BD) == (3, 4)


@given(st.one_of(st.integers(1, 1000), st.floats(min_value=0.001, max_value=1e6, allow_nan=False)),
       categories)
def test_a_positive_number_passes_through_whatever_the_category(freq, category):
    got = pace.freq_of({"frequency_per_year": freq, "category": category})
    assert got == freq and got > 0


@given(st.one_of(st.integers(1, 1000), st.integers(1, 2000).map(lambda n: n / 2)), categories)
def test_a_positive_number_written_as_text_passes_through(freq, category):
    assert pace.freq_of({"frequency_per_year": str(freq), "category": category}) == freq
    assert pace.freq_of({"frequency_per_year": " %s " % freq, "category": category}) == freq


bad_values = st.one_of(st.just(None), st.just(""), st.just("  "), st.just(float("nan")), st.just("nan"),
                       st.just("abc"), st.just("-"), st.integers(-1000, 0),
                       st.floats(max_value=0, allow_nan=False, allow_infinity=False),
                       st.integers(1, 1000).map(lambda n: "-%d" % n), st.just("0"), st.just([]), st.just({}))


@given(bad_values, categories)
def test_zero_missing_negative_or_not_a_number_falls_back_to_the_category_default(value, category):
    assert pace.freq_of({"frequency_per_year": value, "category": category}) == default_for(category)


@given(categories)
def test_a_contact_without_a_frequency_gets_the_category_default(category):
    assert pace.freq_of({"category": category}) == default_for(category)
    assert pace.freq_of({"category": category, "frequency_per_year": None}) == default_for(category)


def test_no_contact_at_all_is_a_bd_contact():
    assert pace.freq_of(None) == pace.DEFAULT_FREQUENCY_BD
    assert pace.freq_of({}) == pace.DEFAULT_FREQUENCY_BD


# ── pace(): the full port against an oracle that counts for itself ───────────────────────────
freq_values = st.one_of(st.integers(1, 60), st.integers(1, 60).map(lambda n: n / 2),
                        st.sampled_from([None, 0, -3, "6", "x", ""]))
contact_specs = st.lists(st.tuples(freq_values, st.sampled_from(["bd", "maintenance"])), max_size=12)
touch_pairs = st.sampled_from([("call", "answered"), ("call", "meeting_set"), ("call", "no_answer"),
                               ("voicemail", "voicemail"), ("meeting", None), ("hosted", None),
                               ("email", None), ("note", None), ("sms", None)])
# How an interaction's date is written, and how many days it moves the CENTRAL day:
#   a bare date                 is that Central date as it is;
#   T10:00:00-06:00             10:00 or 11:00 in Central, the same day (winter or summer);
#   T12:00:00Z                  06:00 or 07:00 in Central, the same day;
#   T03:00:00Z                  21:00 or 22:00 in Central, the day BEFORE.
shapes = st.sampled_from([("%s", 0), ("%sT10:00:00-06:00", 0), ("%sT12:00:00Z", 0), ("%sT03:00:00Z", -1)])
interaction_specs = st.lists(
    st.tuples(st.integers(0, 14), touch_pairs, st.integers(-400, 400), shapes, flags),
    max_size=40)


def build(cspecs, ispecs, today):
    contacts = [{"id": n + 1, "frequency_per_year": f, "category": cat} for n, (f, cat) in enumerate(cspecs)]
    interactions, central_days = [], []
    for k, (cid, (kind, outcome), off, (fmt, shift), flag) in enumerate(ispecs):
        written = today + dt.timedelta(days=off)
        interactions.append({"id": 900 + k, "contact_id": cid, "kind": kind, "outcome": outcome,
                             "occurred_at": fmt % written.isoformat(), "counts_as_touch": flag})
        central_days.append(written + dt.timedelta(days=shift))
    return contacts, interactions, central_days


def oracle(contacts, interactions, central_days, today):
    target = sum(Fraction(pace.freq_of(c)) for c in contacts)
    ids = {c["id"] for c in contacts}
    done = 0
    for i, day in zip(interactions, central_days, strict=True):
        live = i["kind"] in ("meeting", "hosted") or (i["kind"] == "call"
                                                      and i["outcome"] in ("answered", "meeting_set"))
        if live and i["contact_id"] in ids and day.year == today.year and day <= today:
            done += 1
    return target, done


@given(contact_specs, interaction_specs, any_date)
def test_pace_counts_this_years_touches_of_these_contacts_up_to_today(cspecs, ispecs, today):
    contacts, interactions, central_days = build(cspecs, ispecs, today)
    target, done = oracle(contacts, interactions, central_days, today)
    got = pace.pace(contacts, interactions, today)
    assert got["completed"] == done
    assert got["target_total"] == target
    assert got == pace.pace_from_totals(target, done, today)
    assert pace.pace(contacts, interactions, today.isoformat()) == got      # text or date, same answer


@given(contact_specs, interaction_specs, any_date, st.integers(0, 365))
def test_the_count_never_falls_as_today_moves_on_within_the_year(cspecs, ispecs, today, ahead):
    later = min(today + dt.timedelta(days=ahead), dt.date(today.year, 12, 31))
    contacts, interactions, _ = build(cspecs, ispecs, today)
    first = pace.pace(contacts, interactions, today)
    second = pace.pace(contacts, interactions, later)
    assert first["completed"] <= second["completed"]
    assert first["target_total"] == second["target_total"]
    assert first["required_to_date"] <= second["required_to_date"]


@given(contact_specs, interaction_specs, any_date)
def test_other_peoples_touches_and_untouched_lists_change_nothing(cspecs, ispecs, today):
    contacts, interactions, _ = build(cspecs, ispecs, today)
    stranger = {"id": 10_000, "kind": "meeting", "outcome": None, "contact_id": 10_000,
                "occurred_at": today.isoformat()}
    assert pace.pace(contacts, interactions + [stranger], today) == pace.pace(contacts, interactions, today)
    none_owned = pace.pace([], interactions, today)
    assert (none_owned["target_total"], none_owned["completed"], none_owned["pct"]) == (0, 0, 0)
    assert pace.pace(None, None, today) == none_owned


def test_a_day_boundary_and_a_year_boundary_are_read_in_central_time():
    c = [{"id": 1, "frequency_per_year": 4, "category": "bd"}]
    # 04:00Z on Jan 1 is 22:00 Central on Dec 31: last year's touch, even though UTC says 2026.
    late = {"contact_id": 1, "kind": "meeting", "occurred_at": "2026-01-01T04:00:00Z"}
    # 06:30Z on Jan 1 is 00:30 Central on Jan 1: this year's touch.
    early = {"contact_id": 1, "kind": "meeting", "occurred_at": "2026-01-01T06:30:00Z"}
    assert pace.pace(c, [late], "2026-01-01")["completed"] == 0
    assert pace.pace(c, [early], "2026-01-01")["completed"] == 1
    assert pace.pace(c, [late], "2025-12-31")["completed"] == 1
    # an unreadable date is not a touch and does not raise
    junk = {"contact_id": 1, "kind": "meeting", "occurred_at": "not a date"}
    assert pace.pace(c, [junk, {"contact_id": 1, "kind": "meeting", "occurred_at": None}],
                     "2026-06-01")["completed"] == 0


# ── weekly_progress ──────────────────────────────────────────────────────────────────────────
@given(st.lists(st.sampled_from(["done", "open", "snoozed", "skipped", None]), max_size=30))
def test_weekly_progress_counts_done_tasks_and_keeps_everything_in_the_total(statuses):
    got = pace.weekly_progress([{"status": s} for s in statuses])
    assert got == {"done": statuses.count("done"), "total": len(statuses),
                   "label": "%d of %d done" % (statuses.count("done"), len(statuses))}
    assert 0 <= got["done"] <= got["total"]


# ── one batched node run against BDCore.pace ─────────────────────────────────────────────────
day_offsets = st.integers(0, (LAST - FIRST).days).map(lambda n: FIRST + dt.timedelta(days=n))
node_freqs = st.sampled_from([None, 0, -1, 1, 2, 3, 4, 4, 6, 12, 26, 52, 0.5, 1.5, 2.5, 7.5, 100, 200])
node_case = st.tuples(day_offsets, st.lists(st.tuples(node_freqs, st.sampled_from(["bd", "maintenance"])),
                                            max_size=4),
                      st.integers(0, 150), st.integers(0, 3))
FIXED_NODE_CASES = [(d, [(25, "bd"), (1.5, "bd")], c, 1) for d in (
    dt.date(2024, 1, 1), dt.date(2024, 2, 29), dt.date(2024, 12, 31), dt.date(2025, 1, 1),
    dt.date(2025, 12, 31), dt.date(2028, 2, 29), dt.date(2030, 12, 31)) for c in (0, 13, 40)]


def node_input(d, cspecs, completed, extra):
    """Contacts, plus `completed` live touches on Jan 1 (counted), `extra` last-year ones, `extra`
    ones the day after today (same year only), and non-touches (never counted)."""
    contacts = [{"id": n + 1, "frequency_per_year": f, "category": cat} for n, (f, cat) in enumerate(cspecs)]
    jan1 = "%d-01-01T10:00:00-06:00" % d.year
    ints = [{"contact_id": 1, "kind": "meeting", "occurred_at": jan1}] * completed
    ints += [{"contact_id": 1, "kind": "hosted", "occurred_at": "%d-12-31" % (d.year - 1)}] * extra
    tomorrow = d + dt.timedelta(days=1)
    if tomorrow.year == d.year:
        ints += [{"contact_id": 1, "kind": "call", "outcome": "answered",
                  "occurred_at": tomorrow.isoformat()}] * extra
    ints += [{"contact_id": 1, "kind": "email", "occurred_at": jan1},
             {"contact_id": 1, "kind": "call", "outcome": "no_answer", "occurred_at": jan1}] * extra
    return contacts, ints, d.isoformat()


@settings(max_examples=5)
@given(st.lists(node_case, min_size=50, max_size=200))
def test_pace_agrees_with_bd_core_js_on_a_generated_batch(batch):
    cases = []
    for k, (d, cspecs, completed, extra) in enumerate(batch + FIXED_NODE_CASES):
        cases.append({"id": "gen:%d" % k, "fn": "pace", "args": list(node_input(d, cspecs, completed, extra))})
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "cases.json"
        path.write_text(json.dumps(cases), encoding="utf-8")
        proc = run_node(HARNESS, CORE, path)
    assert proc.returncode == 0, proc.stderr
    js = last_json_line(proc.stdout)["results"]
    diffs = []
    for case in cases:
        got = pace.pace(*case["args"])
        if got != js[case["id"]]:
            diffs.append("%s: python %r != js %r" % (case["id"], got, js[case["id"]]))
    assert not diffs, "\n".join(diffs[:10])


# ── gaps found by mutation testing ───────────────────────────────────────────────────────────
@given(categories)
def test_a_boolean_frequency_is_its_number_like_javascripts_number(category):
    # Number(true) is 1 (a real frequency); Number(false) is 0 (no frequency: the category default)
    assert pace.freq_of({"frequency_per_year": True, "category": category}) == 1
    assert pace.freq_of({"frequency_per_year": False, "category": category}) == default_for(category)


@given(st.one_of(st.integers(1, 1000), st.floats(min_value=0.001, max_value=1e6, allow_nan=False)))
def test_a_numeric_frequency_comes_back_as_the_same_kind_of_number(freq):
    got = pace.freq_of({"frequency_per_year": freq, "category": "bd"})
    assert type(got) is type(freq)                            # a whole 6.0 stays 6.0, 6 stays 6


@given(st.integers(1, 1000))
def test_a_whole_number_written_as_text_comes_back_as_an_int(n):
    assert type(pace.freq_of({"frequency_per_year": str(n), "category": "bd"})) is int
    assert type(pace.freq_of({"frequency_per_year": "%d.0" % n, "category": "bd"})) is int
    assert type(pace.freq_of({"frequency_per_year": "%d.5" % n, "category": "bd"})) is float


@given(targets, completed_counts, any_date)
def test_whole_totals_are_reported_as_ints_and_half_totals_as_floats(target, completed, day):
    t = pace.pace_from_totals(target, completed, day)["target_total"]
    assert t == target
    assert type(t) is (int if Fraction(target).denominator == 1 else float)   # JSON 4, not 4.0


@given(targets, any_date, st.sampled_from(["T23:30:00Z", "T00:00:00-06:00", " ", "T10:00:00"]))
def test_a_timestamp_text_for_today_is_read_by_its_first_ten_characters(target, day, tail):
    # "today" may arrive as a longer ISO string; only its date part counts, never a Central shift
    got = pace.pace_from_totals(target, 3, day.isoformat() + tail)
    assert got == pace.pace_from_totals(target, 3, day)
    assert got["as_of"] == day.isoformat()


@given(st.integers(1900, 2999), st.integers(0, 100_000))
def test_the_label_says_interaction_for_exactly_one_and_interactions_for_two_or_more(year, pct):
    # random deltas almost never land on +-1, so pin the singular/plural boundary explicitly
    d = "%d BD Pace: %d%% %s " % (year, pct, DASH)
    assert pace.pace_label(year, pct, 1) == d + "1 interaction ahead of pace"
    assert pace.pace_label(year, pct, -1) == d + "1 interaction behind pace"
    assert pace.pace_label(year, pct, 2) == d + "2 interactions ahead of pace"
    assert pace.pace_label(year, pct, -2) == d + "2 interactions behind pace"
    assert pace.pace_label(year, pct, 0) == d + "right on pace"


def test_weekly_progress_of_nothing_and_of_a_generator():
    assert pace.weekly_progress(None) == {"done": 0, "total": 0, "label": "0 of 0 done"}
    assert pace.weekly_progress([]) == {"done": 0, "total": 0, "label": "0 of 0 done"}
    got = pace.weekly_progress({"status": s} for s in ("done", "open", "done"))
    assert got == {"done": 2, "total": 3, "label": "2 of 3 done"}
