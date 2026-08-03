"""The Bid Calendar's date arithmetic, exercised under node.

A calendar is almost entirely date maths, and every wrong answer looks plausible on
screen: a fortnight with fifteen columns, a bid filed a day early because its deadline is
7pm Central and therefore tomorrow in UTC, a "next month" button that lands back where it
started. None of that announces itself — you have to count.

So the whole engine lives in frontend/js/calendar-core.js as pure functions and is pinned
here. The two classes of bug it exists to prevent:

  * DST. A local-time `new Date(y, m, d)` stepped with `setDate(+1)` produces a 23- or
    25-hour day twice a year, so a range spanning a change comes out with a duplicated or
    a missing column. The engine parses "YYYY-MM-DD" as UTC midnight and steps in whole
    UTC days, which has no such days.
  * Zone. Deadlines arrive as UTC timestamps. A bid due at 7pm Central is stamped the NEXT
    day in UTC, so bucketing on the raw ISO string files it under the wrong day — and at a
    month boundary, the wrong page of the calendar. TWAgg.decorate() stamps the Central day
    once, up front, and this engine never touches a timezone again.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "calendar-core.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                               reason="node is not installed")


def run(script: str):
    """Run `script` with `C` bound to the module; returns its printed JSON.

    `out` escapes every non-ASCII character before printing. The range label contains an
    en dash, and node on Windows writes stdout in the console code page — so decoding it
    as UTF-8 mangles the dash and decoding it as the locale only works by luck of which
    code page is active. Emitting pure ASCII \\uXXXX and letting json.loads put the
    character back makes the comparison independent of both."""
    prelude = (
        "const C = require(%s);\n"
        "const out = (v) => console.log(JSON.stringify(v).replace(\n"
        "  /[\\u0080-\\uffff]/g,\n"
        "  (c) => '\\\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')));\n"
        % json.dumps(str(CORE))
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── day arithmetic ────────────────────────────────────────────────────
def test_the_module_loads():
    """A syntax error would make every test below fail with the same opaque message."""
    assert run("out(typeof C.rangeFor)") == "function"


def test_days_step_without_drifting():
    assert run('out(C.addDays("2026-08-03", 1))') == "2026-08-04"
    assert run('out(C.addDays("2026-08-03", -1))') == "2026-08-02"
    assert run('out(C.addDays("2026-12-31", 1))') == "2027-01-01"
    assert run('out(C.addDays("2027-01-01", -1))') == "2026-12-31"
    assert run('out(C.addDays("2028-02-28", 1))') == "2028-02-29", "2028 is a leap year"
    assert run('out(C.addDays("2026-02-28", 1))') == "2026-03-01", "2026 is not"


@pytest.mark.parametrize("day", [
    "2026-02-31",       # Date.UTC rolls this to March 3 — it must be rejected, not moved
    "2026-13-01",
    "2026-00-10",
    "2026-08-00",
    "not-a-date",
    "",
])
def test_an_impossible_day_is_rejected_rather_than_quietly_moved(day):
    """`Date.UTC(2026, 1, 31)` happily returns March 3rd. Without the round-trip check a
    malformed day would become a real one three days away and every total computed from
    it would be silently wrong."""
    assert run('out(isNaN(C.ms(%s)))' % json.dumps(day)) is True


def test_a_step_across_spring_forward_is_still_one_day():
    """US DST begins 2026-03-08. In local time that day is 23 hours long."""
    assert run('out(C.addDays("2026-03-07", 1))') == "2026-03-08"
    assert run('out(C.addDays("2026-03-08", 1))') == "2026-03-09"
    assert run('out(C.diffDays("2026-03-07", "2026-03-09"))') == 2


def test_a_step_across_fall_back_is_still_one_day():
    """US DST ends 2026-11-01. In local time that day is 25 hours long."""
    assert run('out(C.addDays("2026-10-31", 1))') == "2026-11-01"
    assert run('out(C.addDays("2026-11-01", 1))') == "2026-11-02"
    assert run('out(C.diffDays("2026-10-31", "2026-11-02"))') == 2


def test_weeks_start_on_sunday():
    """Sunday-first because that is how the estimating week is read here, and because the
    seven column headers have to line up with every row."""
    assert run('out(C.startOfWeek("2026-08-03"))') == "2026-08-02"   # Mon -> Sun
    assert run('out(C.startOfWeek("2026-08-02"))') == "2026-08-02"   # already Sunday
    assert run('out(C.startOfWeek("2026-08-08"))') == "2026-08-02"   # Sat -> same week
    assert run('out(C.dow("2026-08-02"))') == 0
    assert run('out([C.isWeekend("2026-08-02"), C.isWeekend("2026-08-08"), '
                   'C.isWeekend("2026-08-05")])') == [True, True, False]


def test_month_ends_are_right_including_february():
    assert run('out(C.endOfMonth("2026-08-14"))') == "2026-08-31"
    assert run('out(C.endOfMonth("2026-02-05"))') == "2026-02-28"
    assert run('out(C.endOfMonth("2028-02-05"))') == "2028-02-29"
    assert run('out(C.endOfMonth("2026-12-01"))') == "2026-12-31"


# ── the visible range ─────────────────────────────────────────────────
def test_the_two_week_range_matches_what_basisboard_shows():
    """Sanity anchor against the real thing: on 2026-08-03 Basisboard's calendar reads
    "Aug 2 - Aug 15". If ours disagrees, one of us is filing bids on the wrong day."""
    got = run('const r = C.rangeFor("2026-08-03","two");'
              'out([r.from, r.to, r.days.length, C.rangeLabel(r,"two")])')
    assert got == ["2026-08-02", "2026-08-15", 14, "Aug 2 – Aug 15"]


@pytest.mark.parametrize("mode,length", [("week", 7), ("two", 14)])
def test_a_range_is_always_whole_weeks(mode, length):
    got = run('const r = C.rangeFor("2026-08-05",%s);'
              'out([r.days.length, C.dow(r.from), C.dow(r.to)])' % json.dumps(mode))
    assert got == [length, 0, 6], "a range must start Sunday and end Saturday"


@pytest.mark.parametrize("anchor", ["2026-03-08", "2026-03-14", "2026-11-01", "2026-11-07"])
def test_a_range_spanning_a_dst_change_has_no_missing_or_duplicated_day(anchor):
    """THE bug this engine exists to prevent. Local-time day stepping produces 13 or 15
    columns here, or repeats one — and the repeat is the nasty one, because the bids on
    the duplicated day get drawn twice and the count above the grid disagrees with the
    grid."""
    got = run('const r = C.rangeFor(%s,"two");'
              'out([r.days.length, new Set(r.days).size])' % json.dumps(anchor))
    assert got == [14, 14]


def test_month_view_is_padded_to_whole_weeks():
    """The leading and trailing days are real days and their bids are shown: a deadline on
    the 31st matters just as much when you're looking at the following month."""
    got = run('const r = C.rangeFor("2026-08-15","month");'
              'out([r.from, r.to, r.days.length, C.dow(r.from), C.dow(r.to)])')
    assert got == ["2026-07-26", "2026-09-05", 42, 0, 6]


def test_every_day_in_a_range_is_unique_and_consecutive():
    got = run('const r = C.rangeFor("2026-08-03","two");'
              'let ok = true;'
              'for (let i = 1; i < r.days.length; i++)'
              '  if (C.diffDays(r.days[i-1], r.days[i]) !== 1) ok = false;'
              'out([ok, new Set(r.days).size === r.days.length])')
    assert got == [True, True]


def test_an_unknown_mode_falls_back_to_two_weeks():
    """A stale sessionStorage value must not produce a zero-day grid."""
    assert run('out(C.rangeFor("2026-08-03","fortnight").days.length)') == 14
    assert run('out(C.modeOf("nonsense").id)') == "two"


# ── paging ────────────────────────────────────────────────────────────
def test_paging_a_fortnight_moves_exactly_a_fortnight():
    got = run('out([C.shift("2026-08-03","two",1), C.shift("2026-08-03","two",-1)])')
    assert got == ["2026-08-16", "2026-07-19"]


def test_paging_a_month_moves_by_month_not_by_28_days():
    """A padded month grid spans 42 days. Stepping by the grid length would skip
    fortnights; stepping by 28 could land back inside the month you started in and the
    header would repeat itself."""
    got = run('out([C.shift("2026-08-15","month",1), C.shift("2026-08-15","month",-1),'
              'C.shift("2026-12-10","month",1), C.shift("2026-01-10","month",-1)])')
    assert got == ["2026-09-01", "2026-07-01", "2027-01-01", "2025-12-01"]


def test_paging_forward_then_back_returns_to_the_same_range():
    for mode in ("week", "two", "month"):
        got = run('const a = C.rangeFor("2026-08-05",%(m)s);'
                  'const f = C.shift("2026-08-05",%(m)s,1);'
                  'const b = C.rangeFor(C.shift(f,%(m)s,-1),%(m)s);'
                  'out([a.from, a.to, b.from, b.to])' % {"m": json.dumps(mode)})
        assert got[0:2] == got[2:4], f"{mode} paging is not reversible: {got}"


def test_the_label_carries_the_year_only_when_the_range_straddles_one():
    assert run('out(C.rangeLabel(C.rangeFor("2026-08-03","two"),"two"))') == "Aug 2 – Aug 15"
    straddle = run('out(C.rangeLabel(C.rangeFor("2026-12-28","two"),"two"))')
    assert straddle == "Dec 27, 2026 – Jan 9, 2027"
    assert run('out(C.rangeLabel(C.rangeFor("2026-08-15","month"),"month"))') == "Aug 2026"


def test_the_month_label_names_the_month_you_are_looking_at_not_the_padding():
    """A padded August grid begins in July. Labelling it off `from` would call August
    "July 2026" every time the 1st isn't a Sunday."""
    assert run('out(C.rangeLabel(C.rangeFor("2026-08-01","month"),"month"))') == "Aug 2026"
    assert run('out(C.rangeLabel(C.rangeFor("2026-05-31","month"),"month"))') == "May 2026"


def test_today_is_only_current_when_it_is_in_view():
    """Drives the Today button's disabled state."""
    got = run('out([C.isCurrent(C.rangeFor("2026-08-03","two"), "2026-08-03"),'
              'C.isCurrent(C.rangeFor("2026-08-03","two"), "2026-08-15"),'
              'C.isCurrent(C.rangeFor("2026-08-03","two"), "2026-08-16"),'
              'C.isCurrent(C.rangeFor("2026-08-03","two"), "2026-08-01")])')
    assert got == [True, True, False, False]


# ── urgency ───────────────────────────────────────────────────────────
def test_today_reads_as_urgently_as_overdue():
    """A bid due at 2pm today is not a calmer problem than one that closed at 5pm
    yesterday, and colouring it as "soon" invites somebody to leave it."""
    got = run('out([C.urgency("2026-08-02","2026-08-03"), C.urgency("2026-08-03","2026-08-03"),'
              'C.urgency("2026-08-04","2026-08-03"), C.urgency("2026-08-05","2026-08-03"),'
              'C.urgency("2026-08-06","2026-08-03"), C.urgency("","2026-08-03")])')
    assert got == ["late", "late", "soon", "soon", "calm", "none"]


# ── bucketing ─────────────────────────────────────────────────────────
ROWS = """
const rows = [
  {id:"a", name:"Alpha",   _bd:"2026-08-04", bid_deadline_at:"2026-08-04T19:00:00Z", quote:100, estimator_ids:["u1"]},
  {id:"b", name:"Bravo",   _bd:"2026-08-04", bid_deadline_at:"2026-08-04T14:00:00Z", quote:200, estimator_ids:[]},
  {id:"c", name:"Charlie", _bd:"2026-08-09", bid_deadline_at:"2026-08-09T14:00:00Z", quote:50,  estimator_ids:["u2"]},
  {id:"d", name:"Delta",   _bd:"",           bid_deadline_at:null,                   quote:900, estimator_ids:["u1"]},
  {id:"e", name:"Echo",    _bd:"2026-09-30", bid_deadline_at:"2026-09-30T14:00:00Z", quote:70,  estimator_ids:[]},
];
const range = C.rangeFor("2026-08-03","two");
const b = C.bucket(rows, range);
"""


def test_bids_land_on_their_deadline_day():
    got = run(ROWS + 'out([b.byDay["2026-08-04"].map(r=>r.id), b.byDay["2026-08-09"].map(r=>r.id)])')
    assert got == [["b", "a"], ["c"]]


def test_a_day_is_ordered_earliest_deadline_first():
    """The order you work the day in. Bravo is due at 14:00 and Alpha at 19:00, so Bravo
    leads even though Alpha comes first in the input."""
    assert run(ROWS + 'out(b.byDay["2026-08-04"].map(r=>r.name))') == ["Bravo", "Alpha"]


def test_a_bid_with_no_deadline_goes_to_the_tray_not_the_bin():
    """Basisboard's calendar hides these. They are exactly the ones that go quiet and get
    forgotten, so losing them here would reproduce the bug we're fixing."""
    assert run(ROWS + 'out(b.undated.map(r=>r.id))') == ["d"]


def test_a_bid_due_outside_the_range_is_counted_but_not_shown():
    """Distinct from having no deadline, and the two must never be conflated: Echo belongs
    to another page of the calendar, Delta belongs to nobody's day."""
    got = run(ROWS + 'out([b.outside, b.undated.map(r=>r.id).includes("e")])')
    assert got == [1, False]


def test_every_day_in_the_range_gets_a_bucket_even_when_empty():
    """The grid renders from the range, so a missing key would throw rather than draw an
    empty Tuesday."""
    got = run(ROWS + 'out([Object.keys(b.byDay).length, range.days.every(d => !!b.byDay[d])])')
    assert got == [14, True]


def test_the_day_header_totals_what_is_in_the_day():
    got = run(ROWS + 'out(C.dayLoad(b.byDay["2026-08-04"]))')
    assert got == {"count": 2, "value": 300}


def test_a_missing_quote_counts_as_zero_not_nan():
    """One bid with no value would otherwise turn the whole day's total into "$NaN"."""
    got = run('out(C.dayLoad([{quote:100},{quote:null},{quote:undefined},{}]))')
    assert got == {"count": 4, "value": 100}


# ── the summary strip ─────────────────────────────────────────────────
def test_the_summary_counts_only_what_is_in_view():
    """A summary that includes filtered-out or off-range bids reads as a bug the first
    time somebody checks the arithmetic against the grid."""
    got = run(ROWS + 'out(C.summarize(b, "2026-08-04"))')
    assert got["bids"] == 3, "Echo is off-range and must not be counted"
    assert got["value"] == 350
    assert got["due_today"] == 2
    assert got["undated"] == 1


def test_the_summary_counts_unassigned_bids_including_undated_ones():
    """"Nobody owns this" is a job to do, and it doesn't stop being one because the bid
    also has no deadline."""
    # In view: Alpha (u1), Bravo (nobody), Charlie (u2) -> one unassigned. Echo is
    # off-range so it isn't counted at all, and Delta is undated but DOES have an
    # estimator — which is the case worth pinning, because the tray's rows have to be
    # included without being assumed ownerless.
    assert run(ROWS + 'out(C.summarize(b, "2026-08-04").unassigned)') == 1

    # An undated bid with nobody on it counts too, even though it sits on no day.
    orphan = ROWS.replace('quote:900, estimator_ids:["u1"]', 'quote:900, estimator_ids:[]')
    assert orphan != ROWS, "the substitution stopped matching — this test would be hollow"
    assert run(orphan + 'out(C.summarize(b, "2026-08-04").unassigned)') == 2


def test_an_empty_dataset_summarizes_to_zeroes_rather_than_throwing():
    got = run('const r = C.rangeFor("2026-08-03","two");'
              'out(C.summarize(C.bucket([], r), "2026-08-03"))')
    assert got == {"bids": 0, "value": 0, "due_today": 0, "due_soon": 0,
                   "unassigned": 0, "undated": 0}


def test_bucketing_tolerates_a_null_row_list():
    """The page paints before the first fetch lands."""
    assert run('out(C.bucket(null, C.rangeFor("2026-08-03","two")).undated)') == []


def test_hasEstimator_is_false_for_every_shape_of_empty():
    got = run('out([C.hasEstimator({estimator_ids:["u1"]}), C.hasEstimator({estimator_ids:[]}),'
              'C.hasEstimator({}), C.hasEstimator(null)])')
    assert got == [True, False, False, False]
