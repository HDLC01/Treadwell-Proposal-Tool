"""The Active Projects period filter offers WEEKS as well as months.

Hanz, 2026-08-12: "For the filter adad weeks also please".

WHY A MONTH IS THE WRONG GRAIN ON ITS OWN. This board is read in a weekly sales meeting. On the 28th,
"August" is every bid anybody has touched all month, and the question in the room is what moved since
Monday.

ONE CONTROL, ONE STORED VALUE. Weeks and months share the existing dropdown, separated by two
`<optgroup>`s and distinguished by a `w:` prefix on the value. A second dropdown would have let
somebody select a week in one and a different month in the other, and the board would then show
nothing with two filters that both looked innocent. The prefix also makes the change backwards
compatible: every value stored before today is a bare `YYYY-MM`, which still takes the month branch,
so a rep mid-session keeps their selection across the deploy.

WEEKS START MONDAY, IN CENTRAL. Monday because "this week" has to mean the week the Monday meeting is
in, not one that ended the day before. Central because bucketing on the viewer's clock puts a Friday
evening bid in Kansas into Saturday for anybody an hour east — the same rule the rest of this app
follows for dates, and the reason `bizWeekStart` does its arithmetic on a noon-UTC anchor: subtracting
days from midnight lands on the previous date whenever the week contains a DST change.

EXECUTED, NOT GREPPED. The harness runs the real `bizWeekStart`/`bizWeekLabel` out of shared.js and
the real `applyPeriod`/`populatePeriods` out of portal.js. After the STAGE_CREATED outage this
morning — a constant used but never imported, with every source-text assertion green — a filter whose
correctness is date arithmetic gets tested by running it.

TWO LATENT BUGS THIS SURFACED, both fixed here rather than filed:
  * `new Date(null)` is the epoch, not an invalid date, so `bizYM(null)` returned "1969-12" and the
    dropdown would have offered December 1969 for any row with no activity timestamp. The existing
    month filter had the same hole; it never showed because every row that reaches it has a sent_at.
  * a week crossing new year rendered "Dec 29–Jan 4, 2025", which says January was in 2025. That week
    is offered every January, so it now reads "Dec 29 '25–Jan 4 '26".
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "period-filter-harness.js"
PORTAL_JS = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
PORTAL_HTML = (FRONTEND / "portal.html").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the ask ──────────────────────────────────────────────────────────────────
@needs_node
def test_the_dropdown_offers_weeks_and_months(ran):
    assert ran["dropdown"]["groups"] == ["Weeks", "Months"], (
        "the period dropdown does not group weeks above months: %s" % ran["dropdown"]["groups"])


@needs_node
def test_filtering_by_a_week_keeps_only_that_weeks_rows(ran):
    assert ran["filter"]["thisWeek"] == ["wed", "mon-first-minute"]
    assert ran["filter"]["prevWeek"] == ["sun-last-minute-prev", "prev-week"]


@needs_node
def test_the_two_weeks_people_actually_want_are_named(ran):
    """A date range is right for older weeks and wrong for the current one — "This week" is what
    somebody scans for. Derived from today rather than from the data, so an empty week does not
    shift the labels up onto the wrong row."""
    labels = {o["value"]: o["label"] for o in ran["dropdown"]["options"]}
    assert labels.get("w:" + ran["namedWeeks"]["thisWeek"], "").startswith("This week")
    assert labels.get("w:" + ran["namedWeeks"]["lastWeek"], "").startswith("Last week")


@needs_node
def test_older_weeks_show_their_date_range(ran):
    ranges = [o["label"] for o in ran["dropdown"]["options"]
              if o["value"].startswith("w:") and not o["label"].startswith(("This", "Last"))]
    assert ranges, "no older week was offered, so the range labelling is untested"
    assert any("–" in r for r in ranges), ranges


@needs_node
def test_every_option_carries_its_count(ran):
    """A period with no rows must never be offered, and the count is what tells you which week is
    worth opening."""
    for o in ran["dropdown"]["options"]:
        if o["value"]:
            assert o["label"].rstrip().endswith(")"), "no count on %r" % o["label"]


# ── the date arithmetic, which is where this can quietly be wrong ────────────
@needs_node
def test_every_bucket_is_a_monday_in_central(ran):
    """Including both DST changeovers and a year boundary. Subtracting days from a midnight anchor
    lands on the previous date across a DST change, which is why the anchor is noon UTC."""
    for m in ran["mondays"]:
        assert m["day"] == "Mon", (
            "%s bucketed into %s, which is a %s" % (m["iso"], m["week"], m["day"]))


@needs_node
def test_the_week_boundary_is_midnight_CENTRAL_not_utc(ran):
    """05:00Z is Monday 00:00 in Central in August; 04:59Z is still Sunday. Bucketing on UTC — or on
    the viewer's clock — moves a Sunday evening bid into the wrong week for half the country."""
    b = ran["boundary"]
    assert b["mondayFirstMinute"] == "2026-08-10"
    assert b["oneMinuteEarlier"] == "2026-08-03", (
        "Sunday 23:59 Central was filed under the following week")
    assert b["sundayLastMinute"] == "2026-08-10", (
        "Sunday 23:59 Central was filed under the following week")


@needs_node
def test_a_row_with_no_activity_produces_no_bucket(ran):
    """`new Date(null)` is the epoch, not NaN. Without an explicit guard the dropdown offers a 1969
    week — and the pre-existing month filter had exactly the same hole."""
    e = ran["empties"]
    assert e["nullIn"] == "" and e["emptyIn"] == "" and e["junkIn"] == ""
    assert e["ymNull"] == "", "bizYM(null) still returns a 1969 month"


@needs_node
def test_a_week_crossing_new_year_names_both_years(ran):
    """"Dec 29–Jan 4, 2025" says January was in 2025. That week is offered every January."""
    label = ran["labels"]["acrossYears"]
    assert "'25" in label and "'26" in label, label


@needs_node
def test_a_week_crossing_a_month_names_both_months(ran):
    assert ran["labels"]["acrossMonths"] == "Aug 31–Sep 6"


@needs_node
def test_a_week_inside_one_month_does_not_repeat_the_month(ran):
    assert ran["labels"]["sameMonth"] == "Aug 10–16"


# ── the ways a filter strands a board ────────────────────────────────────────
@needs_node
def test_the_week_list_is_bounded_and_keeps_the_NEWEST(ran):
    """A year of activity is 52 weeks; a dropdown that long is worse than no week filter. Newest
    first, because nobody opens this page to ask about February."""
    assert ran["capped"]["weekCount"] == ran["weeksOffered"], (
        "%s weeks offered, cap is %s" % (ran["capped"]["weekCount"], ran["weeksOffered"]))
    assert ran["capped"]["values"] == sorted(ran["capped"]["values"], reverse=True), (
        "the offered weeks are not the newest ones")


@needs_node
def test_a_selection_that_is_no_longer_offered_is_dropped(ran):
    """Switching tab changes the pool. A filter left pointing at a week with no rows shows an empty
    board that reads as broken — and a week pushed past the cap is unreachable in the dropdown, so
    the only way back would be Clear."""
    s = ran["staleSelection"]
    assert s["period"] == "" and s["cleared"] is True and s["value"] == ""


@needs_node
def test_a_week_that_fell_past_the_CAP_is_also_dropped(ran):
    """Subtler than a week with no rows: this one still has rows, so a stale check written against
    "does the data contain it" leaves it selected — and because the cap hides it from the dropdown,
    the board is narrowed by a filter you cannot see or change except with Clear.

    A mutation that checked the raw week set instead of the OFFERED set survived until this existed."""
    b = ran["beyondTheCap"]
    assert b["offeredCount"] == ran["weeksOffered"], b
    assert b["cleared"] is True and b["period"] == "", (
        "%s has rows but is past the cap, and stayed selected: %s" % (b["picked"], b))


@needs_node
def test_this_week_is_derived_from_TODAY_not_from_the_newest_row(ran):
    """With rows only from a month ago, nothing may be labelled "This week". Deriving the label from
    the first entry in the list would rename an old week as the live one — and on a board somebody
    runs a Monday meeting from, that is a filter that lies about which week it is showing."""
    n = ran["namedFromToday"]
    assert n["labels"], "the fixture offered no weeks, so this proves nothing"
    assert not n["saysThisWeek"], n["labels"]
    assert not n["saysLastWeek"], n["labels"]


@needs_node
def test_a_month_selected_before_this_shipped_still_works(ran):
    """The stored value is a bare "YYYY-MM" for every session that predates the week option, and the
    storage key was deliberately left as `tw_crm_month` so nothing is lost across the deploy."""
    lm = ran["legacyMonthKept"]
    assert lm["period"] == "2026-07" and lm["value"] == "2026-07" and lm["cleared"] is False
    assert ran["filter"]["july"] == ["july"]


@needs_node
def test_an_unknown_week_matches_nothing_rather_than_everything(ran):
    """A filter that silently stops filtering is worse than one that shows nothing: the board would
    look right and be wrong."""
    assert ran["filter"]["unknownWeek"] == []


@needs_node
def test_no_filter_still_means_everything(ran):
    assert len(ran["filter"]["none"]) == 7


# ── wiring a source read is the right tool for ───────────────────────────────
def test_the_storage_key_did_not_change_when_the_variable_was_renamed():
    """MONTH became PERIOD because it now holds either grain. Renaming the KEY too would have
    silently dropped every rep's current selection on deploy."""
    assert 'PERIOD_KEY = "tw_crm_month"' in PORTAL_JS, (
        "the period is stored under a new key, so an in-flight selection is lost on deploy")


def test_the_period_is_in_the_board_signature():
    """renderBoard compares a signature before repainting. Leave the period out and changing the
    filter changes nothing on screen."""
    body = PORTAL_JS[PORTAL_JS.index("function renderBoard"):]
    sig = body[body.index("JSON.stringify"):body.index("])", body.index("JSON.stringify")) + 2]
    assert "PERIOD" in sig, "the period filter is not in BOARD_SIG, so selecting a week is a no-op"


#: Identifiers containing MONTH that portal.js is ALLOWED to declare, each with why.
#
# The bare `MONTH` and anything prefixed off it (`MONTH_KEY`) are the period filter's old names and
# are what this test hunts. Anything else has to be listed here on purpose.
_MONTH_IDENTIFIERS_ALLOWED = {
    # The close-out family's hold window (2026-08-20). Nothing to do with this filter: it is how
    # many months a held bid stops being chased for, and it is asserted against the backend's
    # HOLD_PAUSE_MONTHS by test_not_sent_lost.py.
    "HOLD_MONTHS",
    # Named in HOLD_MONTHS' own comment, as the backend constant it has to equal. Identifiers are
    # collected out of comments as well as code on purpose: a stale name in a comment is how the
    # next reader learns the wrong one.
    "HOLD_PAUSE_MONTHS",
}
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


def test_no_stale_MONTH_identifier_survives():
    """A half-rename leaves one site reading a variable nobody writes — which is exactly how the
    board broke this morning, one unresolved name at a time.

    CHECKED AS WHOLE IDENTIFIERS, not as a substring of the file. The substring form passed for
    nine days and then failed on `HOLD_MONTHS` (2026-08-20), a close-out constant with nothing to
    do with this filter — and a test that fires on an unrelated word is a test people learn to
    edit rather than read. Every identifier carrying MONTH is collected and checked against a
    named allowlist, so re-introducing `MONTH` or `MONTH_KEY` still fails, and so does adding a
    new MONTH-ish name without saying here why it is not this one."""
    found = {n for n in _IDENTIFIER.findall(PORTAL_JS) if "MONTH" in n}
    stale = found - _MONTH_IDENTIFIERS_ALLOWED
    assert not stale, (
        "a MONTH identifier survived the rename, or a new one arrived unannounced: %s"
        % sorted(stale))


def test_the_placeholder_says_period_not_month():
    """The dropdown offers both grains now, so "Any month" would misdescribe it."""
    assert 'Any period' in PORTAL_HTML
    assert '<option value="">Any month</option>' not in PORTAL_HTML
    assert 'aria-label="Filter by activity week or month"' in PORTAL_HTML, (
        "the accessible name still says month only")


def test_clearing_the_filters_clears_the_period():
    """Both halves: the variable is reset AND the stored value is wiped. Asserted as the exact
    assignment, because "PERIOD" appears as a substring of "PERIOD_KEY" — a mutation that deleted
    `PERIOD = ""` and left the key in the list survived a bare containment check."""
    body = PORTAL_JS[PORTAL_JS.index("if (clear) clear.addEventListener"):][:600]
    assert re.search(r'PERIOD\s*=\s*""', body), (
        "Clear does not reset the period, so the board stays narrowed with no visible filter")
    assert "PERIOD_KEY" in body, "Clear resets the variable but leaves the stored value behind"
