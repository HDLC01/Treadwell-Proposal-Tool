"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 3 of 3: the walk goes red when the code is wrong.

A clean walk (parts 1 and 2) proves the rule only if the walk could have seen a break. Each entry below breaks a COPY of js/bid-model.js or js/polish-estimate.js on one line
(break_source refuses unless the line is there exactly once, so no entry can pass by applying nowhere), runs a short slice of the same walk against the copy, and requires the
rule the line keeps to be reported. The first entries are the third audit's own findings put back one at a time (2026-10-20, of 7d32336): the take-back only from a base, the
estimator's typed / cleared / switched-off row left on the old carrier and the new carrier filled beside it, the guys left on the old crew.
"""
import pytest

from _golden_support import break_source, copy_unmodified
from _node import require_node
from _travel_sequences import PAGE_FILES, explain, run

STRAY_GUARD = 'if (e.kind === "option" || !isObject(e.section) || (e.tab === carrier && e.layout !== "gyp")) return;'
TAKE_BACK_CALL = "takeBackStrayTravel(model);"
SYNC_CALL = "syncAutoGuys(model);"
ELSE_OWNED = "followOwnedRow(model, from, to);"
CLEARED = "delete row.hours_seed; delete row.guys_follow; delete row.guys_typed; delete row.hours_typed;"
REPEAT_GIVEN_BACK = "else if (e.tab !== carrier && travelRowRepeats(r, carrierRow)) releaseTravelRow(r);"
INIT_FOLLOW = "if (restructured) B.followDistance(ROOT, carrierBefore);"
BASE_FOLLOW = "    B.followDistance(ROOT, carrierBefore);"       # four spaces: init's own call has one space before the B

# name -> (file, old, new, mode, depth, the rules the walk must report)
BREAKS = {
    "the take-back is only for a base (off sections keep the row the distance filled)": (
        "js/bid-model.js", STRAY_GUARD, 'if (e.kind !== "base" || !isObject(e.section) || (e.tab === carrier && e.layout !== "gyp")) return;', "far", 2, {"STALE"}),
    "the take-back never runs": (
        "js/bid-model.js", TAKE_BACK_CALL, "void fromTab;", "far", 2, {"ONE_DRIVE", "STALE"}),
    "the settling does not re-derive the guys": (
        "js/bid-model.js", SYNC_CALL, "void model;", "far", 2, {"FAR_CARRIER", "REOPEN_AGREES"}),
    "an emptied row keeps its fill markers": (
        "js/bid-model.js", CLEARED, "delete row.hours_seed; delete row.guys_typed; delete row.hours_typed;", "far", 2, {"STALE"}),
    "what the estimator typed stays on the old carrier": (
        "js/bid-model.js", ELSE_OWNED, "void from;", "typed", 2, {"OWNED"}),
    "a box the estimator cleared (hours) is refilled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, "void from;", "clearHours", 2, {"OWNED"}),
    "a box the estimator cleared (guys) is refilled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, "void from;", "clearGuys", 2, {"OWNED"}),
    "a row the estimator switched off is refilled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, "void from;", "off", 2, {"OWNED"}),
    "a copy of the carrier's typed row made a base keeps pricing the drive beside it": (
        "js/bid-model.js", REPEAT_GIVEN_BACK, "else void r;", "sheetsTyped", 3, {"ONE_DRIVE", "OWNED"}),
    "a job type switch is not settled": (
        "js/polish-estimate.js", INIT_FOLLOW, "void carrierBefore;", "far", 2, {"FAR_CARRIER"}),
    "a base change on the Sheets panel is not settled": (
        "js/polish-estimate.js", BASE_FOLLOW, "    void carrierBefore;", "sheets", 3, {"FAR_CARRIER", "ONE_DRIVE", "STALE"}),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_walk_reports_the_rule_when_the_line_that_keeps_it_is_broken(tmp_path, name):
    """The break must be SEEN: the walk reports the named rule (a crash of the page is not seeing it: a break that stopped the page has nothing to compare)."""
    require_node()
    rel, old, new, mode, depth, rules = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    got = run(mode, depth, frontend)
    assert not got["crashes"], "the break crashed the page instead of breaking a rule: %s\n%s" % (name, explain(got))
    assert rules & set(got["violations"]), "the walk did not notice: %s\n%s" % (name, explain(got))
