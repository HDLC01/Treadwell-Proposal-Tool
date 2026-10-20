"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 5 of 5: the session against a reload, and the nights (the fifth audit, 2026-10-20, of b14bc98).

Every walk before this one starts each step from the draft the step before SAVED: it is always "reload, then step". So none of them could see a Sheets panel action that prices
differently in the session than after a reload, and the fifth audit found one: a base the Sheets panel DEMOTED lost its Travel Labor row in the session (the row moved to the new
carrier), while a reload gave the root a blank one (migrateModel) which the next distance answer filled. Far Polish 4 x 12, 190 miles, an Epoxy sheet added and made the base, the
miles typed as 300 and then 299: the Polish option was $40,988 in the session and $41,771 after a reload, +$783 and nothing else different.

tests/js/travel-sequence-harness.js now has a `reload` mode (and `reloadTyped`, `reloadOff`, ... with the estimator's own say on the carrier's row first). After EVERY Sheets action
(a base change, a copy, a fresh sheet added) the walk judges one more rule, in every sequence it reaches:

    RELOAD_AGREES   the same distance answer (50, 300, 190 miles, or the box cleared) typed in the session that made the change, and typed after a plain reopen of the draft that
                    session saved, leaves the same prices (the lump sum a save writes, the root sheet's bid, every other section's) and the same Travel Labor rows

At b14bc98 the depth-2 walk of the far job reported it in 18 sequences (Combo then Epoxy made the base, Gyp then Combo then Epoxy, ...); it is clean now, and so is the depth-3 walk
(1,548 pages, 700 Sheets actions, four answers each, run for the commit message: it takes two minutes, which is why the committed slices are two steps deep).

The same walks also judge NIGHTS after every step, Hanz's decision of the same day ("Fill them automatically"): a far job's Lodging and Per Diem hold the man-days of EVERY base section
(round 6: a Combo's hotel is on both sheets, and a Gyp crew entered in hours is counted ten hours to a night), each section counted with its own tab's divisor, on auto and marked as
following the labor; a job under 70 miles, or with no distance, fills nothing. An option is priced apart and counts nothing in it, and a section that is off counts nothing.
(Every older walk is judged by it too: none of them types in those boxes.)

The local, no-distance and estimator-said slices are in test_polish_travel_sequences_reload_more.py (a second file only so the two run on different workers).
The last block breaks a COPY of js/bid-model.js one line at a time and requires the walk to report the rule the line keeps.
"""
import pytest

from _golden_support import break_source, copy_unmodified
from _node import require_node
from _travel_sequences import PAGE_FILES, explain, run


def _walked(got, judged=80):
    seen = {k: got.get(k) for k in ("runs", "reopens", "plain", "reloadJudged")}
    assert got["runs"] >= 200 and got["reopens"] >= 150 and got["plain"] >= 28 and got.get("reloadJudged", 0) >= judged, "the walk was cut short: %r" % (seen,)


def test_a_sheets_action_prices_the_same_in_the_session_and_after_a_reload_at_every_distance_answer():
    """The four job types, the Sheets panel's base changes, a copy of the carrier and a fresh Epoxy sheet, two steps deep from each of the four starts: 211 pages, 87 Sheets actions,
    each judged four ways (the miles typed as 50, 300, 190 and cleared), in the session and after a reload. A base demoted by the pick keeps its Travel Labor row, so the option prices
    its own drive from the moment of the pick, as it does after a reload."""
    require_node()
    got = run("reload", 2)
    _walked(got)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


# ── red without the code: break a COPY of the model one line at a time ───────────────────────────
DEMOTED = '    try { demoted = sectionOf(out, fromTab).kind === "option"; } catch (err) { demoted = false; }'
NIGHTS_ANSWER = "    followDistanceNights(model, miles);"
NIGHTS_LOCAL = "      } else if (qtyFollows(l)) {"
NIGHTS_SYNC = "if (l && l.qty_auto !== false) l.qty = qtyFollows(l) ? laborFollowQty(model, l) : days;"
NIGHTS_BASES = "      list = bases.length ? bases : live.slice(0, 1);"
NIGHTS_GYP = "      if (far) {"
NIGHTS_DIVIDE = "    return engine.lodgingNights(profile, roundUp(laborTotal(rows, conditions, pw)), travelLabor, rate || SHIPPED_LABOR_RATE);"

# name -> (old, new, mode, depth, the rules the walk must report)
BREAKS = {
    "a base the pick demoted loses its Travel Labor row to the new carrier": (
        DEMOTED, "    demoted = false;", "reload", 2, {"RELOAD_AGREES"}),
    "a base the pick demoted loses its row (the estimator's typed one)": (
        DEMOTED, "    demoted = false;", "reloadTyped", 2, {"RELOAD_AGREES"}),
    "a far answer fills no nights": (
        NIGHTS_ANSWER, "    void miles;", "far", 1, {"NIGHTS"}),
    "going local keeps the figure the labor filled": (
        NIGHTS_LOCAL, "      } else if (false) {", "dist", 1, {"NIGHTS"}),
    "the nights do not follow the labor when it changes": (
        NIGHTS_SYNC, "if (l && l.qty_auto !== false && !qtyFollows(l)) l.qty = days;", "far", 2, {"NIGHTS"}),
    # round 6: the job's figure is every base section's, each by its own tab's rule
    "a Gyp carrier's nights are typed again": (
        NIGHTS_GYP, '      if (far && (entryOrNull(model, carrierTabOf(model)) || {}).layout !== "gyp") {', "far", 1, {"NIGHTS"}),
    "the job's nights count only the carrier": (
        NIGHTS_BASES, "      list = live.slice(0, 1);", "far", 1, {"NIGHTS"}),
    "a section that is off is counted in the job's nights": (
        NIGHTS_BASES, '      list = entries.filter(function (e) { return e.kind === "base" || e.kind === "off"; });', "far", 1, {"NIGHTS"}),
    "an option is counted in the job's nights": (
        NIGHTS_BASES, "      list = live;", "sheets", 1, {"NIGHTS"}),
    "a Gyp crew's nights are divided by the Polish tab's 8": (
        NIGHTS_DIVIDE, "    return engine.lodgingNights(REV2, roundUp(laborTotal(rows, conditions, pw)), travelLabor, rate || SHIPPED_LABOR_RATE);", "far", 1, {"NIGHTS"}),
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
