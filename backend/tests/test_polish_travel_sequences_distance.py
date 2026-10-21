"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 4 of 4: the miles corrected AFTER the sheets were restructured, copied and demoted (the fourth audit, 2026-10-20, of c0255de).

Parts 1 to 3 walk the job types, the estimator's own say and the Sheets panel's base changes, and never correct the miles afterwards, so they could not see what the fourth audit
found: the answer only ever reached the carrier's Travel Labor. A sheet that is an OPTION (a copy of the carrier, or a base the Sheets panel demoted) holds a row of its own, and a far
Polish bid copied as an option and corrected to 50 miles dropped the base's drive and went on pricing the option's ($30,872 against $32,632), and at 300 miles the base moved to 10
hours while the option stayed at 6.5. tests/js/travel-sequence-harness.js now takes the DISTANCE as a step: the miles typed as 50 (local), 300 (farther), 190 (far) or cleared (the lookup
finds nothing), on the real estimate page, at every point of every sequence of job types, copies and base changes. Two rules are judged right after it, on every option:

    OPT_FOLLOWS     the row holds what the answer gives: the hours (a far job's one round trip; none and no marker under 70 miles or with no distance), the guys on the option's OWN
                    lines (far), and a row the distance filled and nobody touched taken back WHOLE (empty, no marker) when the job goes local or the miles are cleared
    OPT_OWNED       a row that was switched off is exactly as it was, and a box the estimator typed in or cleared holds what it held

(LOCAL, judged on every live section, says that a job under 70 miles prices no row nobody touched; at c0255de the same walk broke it in 147 of 4,043 pages and OPT_FOLLOWS in 396.)
`dist` is the walk with nothing said; distTyped, distClearHours, distClearGuys, distOff and distRate say something on the carrier's row first, and a copy carries it. The committed
slices are the exhaustive ones that run in about a minute; the variants were also walked three steps deep (4,043 pages each) for the commit message, with no violation.

The last block breaks a COPY of js/bid-model.js one line at a time and requires the walk to report the rule the line keeps.
"""
import pytest

from _golden_support import break_source, copy_unmodified
from _node import require_node
from _travel_sequences import PAGE_FILES, explain, run


def test_every_distance_answer_after_every_sequence_of_switches_copies_and_base_changes_breaks_no_rule():
    """The four job types, the Sheets panel's base changes, a copy of the carrier and the four distance steps, three steps deep from each of the four starts: 4,043 pages, each judged
    after its step by every rule, 3,265 of them reopened plain to hold the draft to what the page showed. A copy made on a far job and corrected to 50 miles, to 300, cleared and
    typed again: the option's drive is what the base's is, on its own crew, at every one."""
    require_node()
    got = run("dist", 3)
    assert got["runs"] >= 4000 and got["plain"] >= 400 and got["reopens"] >= 3200, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("variant", ["Typed", "ClearHours", "ClearGuys", "Off", "Rate"])
def test_what_the_estimator_said_survives_every_distance_answer_after_every_switch_copy_and_base_change(variant):
    """The estimator's say on the carrier's row (typed 3 x 5, a cleared box, switched off, or a rate typed over $33), then every sequence of job switches, copies, base changes and
    distance answers two steps deep: 410 pages each. A copy carries the row; the answers leave the box typed in or cleared and the row switched off exactly as it was on the option, the
    box nobody typed in follows the answer, and the carrier's row is the estimator's wherever the carrier is."""
    require_node()
    got = run("dist" + variant, 2)
    assert got["runs"] >= 410 and got["plain"] >= 42 and got["reopens"] >= 330, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got.get("skipped", 0) == 0 and got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("distance", ["local", "unknown"])
def test_a_far_answer_after_a_local_start_fills_the_options_empty_rows_too(distance):
    """The same walk from a bid that starts on a 40 mile job, or whose distance could not be found: a copy holds an EMPTY Travel Labor row, and the far answer that comes later (190,
    300) fills it by the carrier's rule like the base's, on the option's own crew; the answers that go local again take it back. 410 pages each, two steps deep."""
    require_node()
    got = run("dist@" + distance, 2)
    assert got["runs"] >= 410 and got["plain"] >= 42 and got["reopens"] >= 330, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


# ── red without the code: break a COPY of the model one line at a time ───────────────────────────
FILLS = "var fills = !row.hours_typed && (isBlank(row.days) || wrote);"
GUYS_ON = 'if (!row.guys_typed && !row.guys_auto && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }'
OFF_GUARD = "if (!rowOn(row)) return;   // switched off: no fill and no take-back"
ESTIMATORS = "return !!row && (!rowOn(row) || !travelRowIsHandsOff(row) || travelRateIsTyped(row));"
OPTION_ROW = 'if (isTravelRow(r) && r.unit === "hours") followDistanceOnRow(model, r, rows, miles, true);'
SYNC = 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? ownCrewSize(model, lines) : manDays;'

# name -> (old, new, mode, depth, the rules the walk must report)
BREAKS = {
    "an answer never reaches an option's Travel Labor": (
        "followDistanceOptions(model, miles);", "void miles;", "dist", 2, {"LOCAL", "OPT_FOLLOWS"}),
    "clearing the miles never reaches an option's Travel Labor": (
        "followDistanceOptions(model, null);", "void model;", "dist", 2, {"LOCAL", "OPT_FOLLOWS"}),
    "an option keeps its fill markers when the job goes local": (
        "if (own && travelRowIsAutoFilled(row)) clearQuantities(row);", "if (false) clearQuantities(row);", "dist", 2, {"OPT_FOLLOWS"}),
    "an option's empty row is not filled by a far answer": (
        OPTION_ROW, OPTION_ROW.replace('r.unit === "hours")', 'r.unit === "hours" && travelRowIsAutoFilled(r))'), "dist@local", 2, {"OPT_FOLLOWS"}),
    # (round 7, D1: every drive follows its own section's crew, a base's as an option's, so the break reaches the bases too)
    "a drive's guys follow the job's base crew": (
        SYNC, 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? crewSize(model) : manDays;', "dist", 2, {"OPT_FOLLOWS", "FAR_BASES"}),
    "a switched-off option row is filled": (OFF_GUARD, "void 0;", "distOff", 2, {"OPT_OWNED"}),
    "a typed option row is overwritten by the next answer": (FILLS, "var fills = true;", "distTyped", 2, {"OPT_OWNED"}),
    "a cleared option guys box is refilled by the next answer": (
        GUYS_ON, 'if (!row.guys_auto && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }', "distClearGuys", 2, {"OPT_OWNED"}),
    "a rate the estimator typed stays behind on the old carrier": (
        ESTIMATORS, "return !!row && (!rowOn(row) || !travelRowIsHandsOff(row));", "rate", 2, {"OWNED"}),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_walk_reports_the_rule_when_the_line_that_keeps_it_is_broken(tmp_path, name):
    """The break must be SEEN: the walk reports the named rule (a crash of the page is not seeing it: a break that stopped the page has nothing to compare)."""
    require_node()
    old, new, mode, depth, rules = BREAKS[name]
    frontend = break_source(tmp_path, "js/bid-model.js", old, new)
    copy_unmodified(frontend, PAGE_FILES)
    got = run(mode, depth, frontend)
    assert not got["crashes"], "the break crashed the page instead of breaking a rule: %s\n%s" % (name, explain(got))
    assert rules & set(got["violations"]), "the walk did not notice: %s\n%s" % (name, explain(got))
