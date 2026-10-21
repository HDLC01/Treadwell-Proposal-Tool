"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 3 of 4: the walk goes red when the code is wrong.

A clean walk (parts 1 and 2) proves the rule only if the walk could have seen a break. Each entry below breaks a COPY of js/bid-model.js or js/polish-estimate.js on one line
(break_source refuses unless the line is there exactly once, so no entry can pass by applying nowhere), runs a short slice of the same walk against the copy, and requires the
rule the line keeps to be reported. The first entries are the third audit's own findings put back one at a time (2026-10-20, of 7d32336): the take-back skipping the sections
that are off, the estimator's typed / cleared / switched-off row left on the old base and the new base filled beside it. ROUND 7 (Hanz's decisions of 2026-10-21) put the walk
under one drive per base crew (D1) and a Gyp base filled (D2), and the entries after the third audit's break those: the one-drive law put back, a Gyp base left unfilled, a
second drive carried onto a base that holds its own, and a base that stays a base handed the old base's typed drive. ROUND 7, PART 3 (the round-7 audit's F1) holds what the
estimator said once to one base (SAID_TWICE), and its entries break that: the tool's copy never given back, the copies the pick and a Sheets copy make never marked as the
tool's, the estimator's own row given back in place of the copy, and a copy given back that repeats no other base's row. ROUND 7, PART 4 changed two of the laws: the copy given back
keeps the trip it held, the hours and the rate the estimator typed (COPY_TRIP; part 3 refilled it from the round trip and put its rate back), and a Gyp drive is a round trip for each
mobilization on its card (FAR_BASES on a Gyp base, OPT_FOLLOWS on a copy of the Gyp sheet, every Gyp walk starting on two); the last entries break those.
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
FILL_OWN = "    if (row) followDistanceOnRow(model, row, lines, miles, false, driveTripsOf(e));"
INIT_FOLLOW = "if (restructured) B.followDistance(ROOT, carrierBefore, kindsBefore);"
BASE_FOLLOW = "    B.followDistance(ROOT, carrierBefore, kindsBefore);"       # four spaces: init's own call has one space before the B
SECTIONS_OF = "    tabIdsInOrder(tabs).forEach(function (id) {"
GIVE_BACK = "    var gaveBack = giveBackRepeatedCopies(model, arrived);"
MARK_PICK = "    if (keep === true) travelRowsIn(to).forEach(markToolCopy);"
MARK_COPY = "    travelRowsIn(body).forEach(markToolCopy);"
ONLY_COPIES = '        if (!isToolCopy(r) || say === "") return;'
ONLY_REPEATS = "        if (!repeats) return;"
KEEP_TRIP = "    if (isBlank(row.days)) {"
GIVEN_BACK = "    delete row.hand_added;"
TRIPS = '    var hours = trip === "" ? "" : trip * (trips === undefined ? 1 : trips);'
OPTION_TRIPS = '        if (isTravelRow(r) && r.unit === "hours") followDistanceOnRow(model, r, rows, miles, true, driveTripsOf(e));'

# (Round 7 retired three entries with the one-drive law. "The settling does not re-derive the guys": since Hanz's D1 a base's drive is its own crew's from the start, so a restructure
# that keeps the base moves no guys and a carried drive is refilled where it lands; the sync is held by test_polish_travel_round7.py's Combo saved under the one-drive law and by
# test_polish_travel_hours.py. "A copy of the carrier's typed row made a base keeps pricing the drive beside it": a copy made a base keeps its OWN line now, the base it came from too,
# and a carried copy is given back where it is carried (test_polish_travel_hours.py breaks both); since round 7, part 3 a copy made a base BESIDE the base whose line it repeats gives
# the repeat back (SAID_TWICE and the entries at the end). ONE_DRIVE and FAR_CARRIER are DOUBLE and FAR_BASES.)
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
        "js/bid-model.js", FILL_OWN, '    if (row && e.layout !== "gyp") followDistanceOnRow(model, row, lines, miles, false, driveTripsOf(e));', "far", 2, {"FAR_BASES"}),
    "a new base that holds its own drive is carried a second one": (
        "js/bid-model.js", SHIFT_ONCE, "    if (!mine.length) return false;", "far", 2, {"DOUBLE", "ONE_ROW"}),
    "a base that stays a base is carried the old base's typed drive": (
        "js/bid-model.js", LEGACY_CARRY, "    return true;", "typed", 2, {"OWNED"}),
    # round 6, item C2: every reopen of a walk is the server's (jsonb keeps no key order), so a plain reopen that lists the sheets in the order their keys come back in moves the sheets
    "the sheets are listed in the order the server returns their keys (the code before the order was kept)": (
        "js/bid-model.js", SECTIONS_OF, "    Object.keys(tabs).forEach(function (id) {", "far", 2, {"PLAIN_REOPEN", "REOPEN_AGREES"}),
    # round 7, part 3 (the round-7 audit's F1): what the estimator said once is on one base; the tool's copy of it is given back when its sheet becomes a base beside the one holding it
    "the tool's copy of a say another base holds is never given back": (
        "js/bid-model.js", GIVE_BACK, "    var gaveBack = [];", "said", 0, {"SAID_TWICE"}),
    "the copy the pick hands the new base is not marked as the tool's": (
        "js/bid-model.js", MARK_PICK, "    void keep;", "said", 0, {"SAID_TWICE"}),
    "a Sheets copy of a sheet is not marked as the tool's": (
        "js/bid-model.js", MARK_COPY, "    void body;", "said", 0, {"SAID_TWICE"}),
    "the estimator's own row is given back as if the tool had copied it": (
        "js/bid-model.js", ONLY_COPIES, '        if (say === "") return;', "said", 0, {"OWNED", "PROMOTED"}),
    "a copy that repeats no other base's row is given back": (
        "js/bid-model.js", ONLY_REPEATS, "        void repeats;", "sheetsTyped", 3, {"OWNED"}),
    # round 7, part 4 (P1: Kyle's sheets carry the same trip on both crews, each its own guys): the copy given back keeps the trip it held; (P2) a Gyp drive is a round trip for each mobilization
    "a copy given back is refilled from the round trip (part 3's rule)": (
        "js/bid-model.js", KEEP_TRIP, "    if (true) {", "said", 0, {"COPY_TRIP"}),
    "a copy given back is put back to its own default rate (part 3's rule)": (
        "js/bid-model.js", GIVEN_BACK, "    delete row.hand_added; row.rate = 33; delete row.rate_typed;", "said", 0, {"COPY_TRIP"}),
    "a Gyp base's drive is one round trip whatever the mobilizations": (
        "js/bid-model.js", TRIPS, "    var hours = trip;", "far", 2, {"FAR_BASES"}),
    "a far answer gives a Gyp option one round trip whatever its own mobilizations": (
        "js/bid-model.js", OPTION_TRIPS, '        if (isTravelRow(r) && r.unit === "hours") followDistanceOnRow(model, r, rows, miles, true, 1);', "dist", 2, {"OPT_FOLLOWS"}),
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
