"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 3 of 4: the walk goes red when the code is wrong.

A clean walk (parts 1 and 2) proves the rule only if the walk could have seen a break. Each entry below breaks a COPY of js/bid-model.js or js/polish-estimate.js on one line
(break_source refuses unless the line is there exactly once, so no entry can pass by applying nowhere), runs a short slice of the same walk against the copy, and requires the
rule the line keeps to be reported. The first entries are the third audit's own findings put back one at a time (2026-10-20, of 7d32336): the take-back skipping the sections
that are off, the estimator's typed / cleared / switched-off row left on the old base and the new base filled beside it. ROUND 7 (Hanz's decisions of 2026-10-21) put the walk
under one drive per base crew (D1) and a Gyp base filled (D2), and the entries after the third audit's break those: the one-drive law put back, a Gyp base left unfilled, a
second drive carried onto a base that holds its own, and a base that stays a base handed the old base's typed drive.
"""
import pytest

from _golden_support import break_source, copy_unmodified
from _node import require_node
from _travel_sequences import PAGE_FILES, explain, run

STRAY_GUARD = 'if (e.kind === "option" || !isObject(e.section) || drives.indexOf(e.tab) >= 0) return;'
TAKE_BACK_CALL = "    takeBackStrayTravel(model, carriedFrom);"
ELSE_OWNED = 'return followOwnedRow(model, from, to) ? from : "";'
LEGACY_CARRY = "    return !!e && !travelRowsIn(e.section).length;"
CLEARED = "delete row.hours_seed; delete row.guys_follow; delete row.guys_typed; delete row.hours_typed;"
SHIFT_ONCE = "    if (!mine.length || theirs.length) return false;"
DRIVES = "      if (list.length) return list;"
FILL_OWN = "    if (row) followDistanceOnRow(model, row, lines, miles, false);"
INIT_FOLLOW = "if (restructured) B.followDistance(ROOT, carrierBefore, kindsBefore);"
BASE_FOLLOW = "    B.followDistance(ROOT, carrierBefore, kindsBefore);"       # four spaces: init's own call has one space before the B
SECTIONS_OF = "    tabIdsInOrder(tabs).forEach(function (id) {"

# (Round 7 retired three entries with the one-drive law. "The settling does not re-derive the guys": since Hanz's D1 a base's drive is its own crew's from the start, so a restructure
# that keeps the base moves no guys and a carried drive is refilled where it lands; the sync is held by test_polish_travel_round7.py's Combo saved under the one-drive law and by
# test_polish_travel_hours.py. "A copy of the carrier's typed row made a base keeps pricing the drive beside it": a copy made a base keeps its OWN line now, the base it came from too,
# and a carried copy is given back where it is carried (test_polish_travel_hours.py breaks both). ONE_DRIVE and FAR_CARRIER are DOUBLE and FAR_BASES.)
# name -> (file, old, new, mode, depth, the rules the walk must report)
BREAKS = {
    "the take-back is only for a base (off sections keep the row the distance filled)": (
        "js/bid-model.js", STRAY_GUARD, 'if (e.kind !== "base" || !isObject(e.section) || drives.indexOf(e.tab) >= 0) return;', "far", 2, {"STALE"}),
    "the take-back never runs": (
        "js/bid-model.js", TAKE_BACK_CALL, "    void carriedFrom;", "far", 2, {"STALE"}),
    "an emptied row keeps its fill markers": (
        "js/bid-model.js", CLEARED, "delete row.hours_seed; delete row.guys_typed; delete row.hours_typed;", "far", 2, {"STALE"}),
    "what the estimator typed stays on the old carrier": (
        "js/bid-model.js", ELSE_OWNED, 'return "";', "typed", 2, {"OWNED"}),
    "a box the estimator cleared (hours) is refilled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, 'return "";', "clearHours", 2, {"OWNED"}),
    "a box the estimator cleared (guys) is refilled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, 'return "";', "clearGuys", 2, {"OWNED"}),
    "a row the estimator switched off is refilled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, 'return "";', "off", 2, {"OWNED"}),
    "a job type switch is not settled": (
        "js/polish-estimate.js", INIT_FOLLOW, "void carrierBefore;", "far", 2, {"FAR_BASES", "STALE"}),
    "a base change on the Sheets panel is not settled": (
        "js/polish-estimate.js", BASE_FOLLOW, "    void carrierBefore;", "reload", 2, {"FAR_BASES", "STALE", "PROMOTED"}),
    # round 7 (Hanz's decisions of 2026-10-21): every base crew drives its own (D1), a Gyp base's drive fills (D2)
    "only the first base drives (the one-drive law)": (
        "js/bid-model.js", DRIVES, "      if (list.length) return list.slice(0, 1);", "far", 2, {"FAR_BASES"}),
    "a Gyp base's drive is not filled": (
        "js/bid-model.js", FILL_OWN, '    if (row && e.layout !== "gyp") followDistanceOnRow(model, row, lines, miles, false);', "far", 2, {"FAR_BASES"}),
    "a new base that holds its own drive is carried a second one": (
        "js/bid-model.js", SHIFT_ONCE, "    if (!mine.length) return false;", "far", 2, {"DOUBLE", "ONE_ROW"}),
    "a base that stays a base is carried the old base's typed drive": (
        "js/bid-model.js", LEGACY_CARRY, "    return true;", "typed", 2, {"OWNED"}),
    # round 6, item C2: every reopen of a walk is the server's (jsonb keeps no key order), so a plain reopen that lists the sheets in the order their keys come back in moves the sheets
    "the sheets are listed in the order the server returns their keys (the code before the order was kept)": (
        "js/bid-model.js", SECTIONS_OF, "    Object.keys(tabs).forEach(function (id) {", "far", 2, {"PLAIN_REOPEN", "REOPEN_AGREES"}),
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
