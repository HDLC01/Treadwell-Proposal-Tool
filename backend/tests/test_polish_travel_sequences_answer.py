"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 6: the ANSWER (round 6, part 2, 2026-10-20).

The round-5 verification found a session and a reload of the SAME draft pricing $783 apart (F1: a far Combo, switched to Epoxy, the x on the Epoxy sheet's Travel Labor, switched back to Combo;
F2: a far Polish, the x, an Epoxy sheet made the base, Add Travel Labor on it, the Polish option read). Every walk before this one is blind to it, for two reasons: no step presses the x, and
`shape` LEFT BLANK ROWS OUT of "as it was", so a reopen that appended a blank Travel Labor row to an off root looked the same as the page that saved it. Now:

  * a plain reopen is judged on every Travel Labor row, blank ones too (PLAIN_REOPEN, REOPEN_AGREES, in EVERY mode), and on the job's answer;
  * the x on the carrier's line, the x on an option's, and Add Travel Labor on the carrier and on an option are steps of the walk;
  * a Sheets action, an x and an Add are judged against a reload of the draft the session saved, RE-KEYED AS THE DRAFTS TABLE'S jsonb COLUMN HANDS IT BACK (key length, then bytes): the same
    distance answer (50, 300, 190 miles, or the box cleared) typed in the session and after the reload must leave the same prices and the same Travel Labor rows (RELOAD_AGREES);
  * ANSWER_OWNER: the root's `no_travel_labor` is the JOB's answer, the carrier's and nobody else's. Set while the section that carries the job's travel holds a Travel Labor line, it is a flag
    that has outlived its meaning (an option's x, a leftover row's x, a job-type switch that seeded the new carrier a line the job had said it does not have);
  * ANSWER_HELD: the answer HOLDS (decided 2026-10-20; Hanz, 2026-10-21: "a job-type switch keeps the drive REMOVED", no seed, no carry, Add Travel Labor is the way back). After the x on the
    carrier's line, and until Add Travel Labor on the carrier or a Sheets action, a job-type switch or a crew typed leaves the job no drive: the flag still set and no line on the carrier, not seeded
    to a new section, not carried to it, not a blank one the new carrier already held filled by the distance on file. A switch that makes an OPTION holding a line of its own the carrier ends the
    rule as a base pick does (round 6, part 3, M3): that line is the option's own drive, and the job has one;
  * DEMOTED_KEEPS: a base the Sheets panel's pick demotes to an option keeps the Travel Labor line it held. The blank line a reload gave a demoted root is gone, so a session and a reload now agree even
    on a demotion that loses its line; the two part-5 entries that put that loss back (test_polish_travel_sequences_reload.py) now see it through this rule.

`answerJobs` is F1's family (three steps among the four job types and the answer), `answerSheets` F2's (the Sheets actions and the answer), `answer` every kind of step two deep, and `answers` the
twenty-four sequences of the answer's own, the audit's three among them (twenty-two until round 7, part 4 added the x on both drives of a Combo, P3).

ROUND 7, PART 1 (2026-10-21, Hanz's decisions D1 to D3): a far Combo has two drives, one per base crew, so the answer is three answers. The x on the drive of a SINGLE-base job is the job's
(`no_travel_labor`, J), and holds through every switch (D3); the x on one base's drive of a Combo is that sheet's (`sheet_no_travel_labor`, S), and the remaining base keeps it when the job goes
back to one base; an option's x records nothing (O). The walk judges the answers as TRANSITIONS, the page after a step against the draft the step started from, after every step of every walk:
ANSWER_OWNER (who may set an answer, and that none is said over a line), ANSWER_HELD (an answer said goes only with Add Travel Labor on its sheet, or a base an option became bringing a line
the estimator added or typed) and PROMOTED (the round-6 audit's F-C: an option made a base keeps a line the estimator added or typed, and a line the tool filled is released while the job says
it has no drive). Until round 7 a Sheets action ENDED the rule, and so did a job-type switch that promoted an option holding a line: no step is exempt any more (the audit's F-D). The steps
`x:base` and `addTravel:base` press them on the Combo's second base, and the answers' own sequences gained five (the sheet's answer both ways, the job's held through a Combo, a tool line
released on promotion by a pick and by a switch); two older ones now press Add before the x they ended on, because the line the x was pressed on is released.

ROUND 6, PART 3 (2026-10-21, M1): the sheets are re-keyed with everything else. Until the sheet-order work (each section's `seq`) was merged, these walks kept the sheets under `tabs` in the order they were
saved, because a tree without it reads them back in jsonb's; now every reopen is the server's, sheets and all (tests/js/_jsonb.js, `run` refuses a walk none of whose reopens moved the sheets). The one
shape that order decides a PRICE on is a step of its own, THE EPOXY + POLISH-COPY PAIR (`pair`: bases Epoxy and a copy of the Polish root, the root an option, both bases under `tabs`, so the carrier
is their order alone): a step of the `answer` walk and of the session walk, and two of the `answers` sequences, which add the Epoxy sheet first so that a reload hands "Copy1" back ahead of it. A session
and a jsonb reload price the same after every step of them (RELOAD_AGREES), and the walk sees it when the model lists the sheets in the server's key order (the last entry of BREAKS).

The last block breaks a COPY of the page or the model one line at a time and requires the walk to report the rule the line keeps.
"""
import pytest

from _golden_support import break_source, copy_unmodified
from _node import require_node
from _travel_sequences import PAGE_FILES, explain, run


def _walked(got, runs, reopens, judged):
    seen = {k: got.get(k) for k in ("runs", "reopens", "plain", "reloadJudged", "sequences", "skipped")}
    assert got["runs"] >= runs and got["reopens"] >= reopens and got.get("reloadJudged", 0) >= judged, "the walk was cut short: %r" % (seen,)


@pytest.mark.parametrize("mode, depth, runs, reopens, judged", [
    ("answerJobs", 3, 500, 300, 100),
    ("answerSheets", 3, 400, 300, 400),
    ("answer", 2, 250, 190, 120),
])
def test_the_answer_walks_are_clean(mode, depth, runs, reopens, judged):
    """The job types, the Sheets actions and the answer (the x on the carrier's line and on an option's, Add Travel Labor on the carrier and on an option): every rule after every step, and a session
    against a jsonb reload after every Sheets action, x and Add, at four distance answers each. F1 is `combo -> epoxy -> x:carrier -> combo` in `answerJobs`, F2 `combo -> x:carrier -> base:Epoxy
    -> addTravel:carrier` in `answerSheets`."""
    require_node()
    got = run(mode, depth)
    _walked(got, runs, reopens, judged)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("distance", ["local", "unknown"])
def test_the_answer_walk_is_clean_on_a_job_that_starts_local_or_with_no_distance(distance):
    """The same walk from a 40 mile job and from one whose distance could not be found: the far answer that comes later fills a Travel Labor line the answer put back, on both sides alike."""
    require_node()
    got = run("answer@" + distance, 2)
    _walked(got, 250, 190, 120)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


def test_the_answers_own_sequences_are_clean_and_none_is_cut_short():
    """The twenty-four sequences (the audit's F1, F2 and S1, an option's x and Add, the root that is an option, a switch after the carrier's x, an option made the base after it, a base pick around
    it, the Epoxy + Polish-copy pair, twice, an option holding its own drive made the carrier by a job-type switch and by a base pick, and since round 7 a Combo sheet's own answer on either
    base, the job's answer held through a Combo and taken back on its second base, a tool line released on promotion by a pick and by a switch, and since round 7, part 4 the x on both drives
    of a Combo, in either order, held through the switches after it, a new Gyp section among them, and taken back by Add): every rule after every step. None may be skipped (a step the page
    offers nothing to press on would shorten the sequence without a word)."""
    require_node()
    got = run("answers", 0)
    _walked(got, 55, 8, 30)
    assert got["sequences"] == 24 and got.get("skipped", 0) == 0, "a sequence was cut short: %r" % ({k: got.get(k) for k in ("sequences", "skipped")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


# ── red without the code: break a COPY of the page or the model one line at a time ──────────────────────────────────────────────────────────────────────────
APPEND = "if (!said && model.sheet_no_travel_labor !== true && carrierTabOf(model) === ROOT_TAB) out.labor = laborIn.concat([travelSeed()]);"
RELEASE = "      if (model.no_travel_labor === true || sheetSaidNoDrive(e.section)) {"
OPTION_X = "      if (B.isTravelRow(gone)) B.travelLaborRemoved(ROOT, activeTab);"
CARRIER_X = "    else model.no_travel_labor = true;"
SHEET_X = "    if (drives.length > 1) hit.section.sheet_no_travel_labor = true;"
ADD_ON_A_BASE = "    if (drive) {"
ADD_HANDS_ON = "          if (e.section !== holder && isObject(e.section) && !travelRowsIn(e.section).length) e.section.sheet_no_travel_labor = true;"
CARRY_REFUSED = '      if (model.no_travel_labor === true || sheetSaidNoDrive(toSection)) return "";'
KEEP_ADDED = '        releaseNobodysTravelRow(model, tab, wasKind === "option");'
FRESH_LINE = "        e.section.labor.push(freshDriveRow(model));"
SECTIONS_OF = "    tabIdsInOrder(tabs).forEach(function (id) {"
LAST_X = "    if (drives.length > 1 && !drivesHoldTravel(model)) {"

# (Until round 7 the settling of the answer when an option that holds a line is made the base was held on the page alone (test_polish_travel_round6_answer.py): the walk ended its rule at
# a Sheets action. Since Hanz's decisions of 2026-10-21 no step is exempt (the round-6 audit's F-D) and PROMOTED judges every promotion, so the walk sees it: the last entries below.)

# name -> (file, old, new, mode, depth, the rules the walk must report)
BREAKS = {
    "a reload appends the blank row to an off root and to a root that is an option (every older walk sees it too)": (
        "js/bid-model.js", APPEND, "if (!said && model.sheet_no_travel_labor !== true) out.labor = laborIn.concat([travelSeed()]);", "answerSheets", 2,
        {"PLAIN_REOPEN", "REOPEN_AGREES", "RELOAD_AGREES"}),
    "the blank row of a reload is priced differently from the session (F1, F2)": (
        "js/bid-model.js", APPEND, "if (!said && model.sheet_no_travel_labor !== true) out.labor = laborIn.concat([travelSeed()]);", "answers", 0,
        {"RELOAD_AGREES", "REOPEN_AGREES", "PLAIN_REOPEN"}),
    "an option's x says the job has no drive": (
        "js/polish-estimate.js", OPTION_X, "      if (B.isTravelRow(gone)) ROOT.no_travel_labor = true;", "answers", 0, {"ANSWER_OWNER"}),
    "the x on a single-base job's drive is not recorded": (
        "js/bid-model.js", CARRIER_X, "    else void model;", "answers", 0, {"ANSWER_HELD", "FAR_BASES"}),
    "an option's Add takes back the job's answer": (
        "js/bid-model.js", ADD_ON_A_BASE, "    if (true) {", "answers", 0, {"ANSWER_HELD"}),
    "a new base keeps a blank line the job said it does not have": (
        "js/bid-model.js", RELEASE, "      if (sheetSaidNoDrive(e.section)) {", "answerJobs", 2, {"ANSWER_HELD"}),
    "a job-type switch seeds the new base a line and the blank one is not taken off": (
        "js/bid-model.js", RELEASE, "      if (sheetSaidNoDrive(e.section)) {", "answers", 0, {"ANSWER_HELD"}),
    # round 7 (Hanz's decisions of 2026-10-21): the sheet's answer, the job's held, and an option made a base
    "the x on one base's drive of a Combo is the job's answer": (
        "js/bid-model.js", SHEET_X, "    if (false) hit.section.sheet_no_travel_labor = true;", "answers", 0, {"ANSWER_OWNER"}),
    "Add on one base under the job's answer leaves the other base nothing to say": (
        "js/bid-model.js", ADD_HANDS_ON, "          void e;", "answers", 0, {"ANSWER_HELD", "FAR_BASES"}),
    "a job-type switch carries a drive onto a sheet that said it has none": (
        "js/bid-model.js", CARRY_REFUSED, '      if (model.no_travel_labor === true) return "";', "answers", 0, {"ANSWER_HELD"}),
    "an option made the base under the job's answer keeps the line the tool filled": (
        "js/bid-model.js", RELEASE, "      if (false) {", "answers", 0, {"PROMOTED"}),
    "an option made the base under the job's answer loses the line the estimator added": (
        "js/bid-model.js", KEEP_ADDED, "        releaseNobodysTravelRow(model, tab, false);", "answers", 0, {"PROMOTED"}),
    "an option made a base with no line is given none": (
        "js/bid-model.js", FRESH_LINE, "        void freshDriveRow;", "reload", 2, {"PROMOTED", "FAR_BASES"}),
    # round 7, part 4 (P3: the round-7 audit's F3): the x on the last base's drive of a Combo is the job's answer, which a later switch holds (D3)
    "the x on both drives of a Combo leaves the job without its answer": (
        "js/bid-model.js", LAST_X, "    if (false) {", "answers", 0, {"ANSWER_OWNER"}),
    # round 6, part 3 (M1): the Epoxy + Polish-copy pair's carrier is the order of its two bases, which a reload hands back in jsonb's order; the answers' own sequences see the code from before `seq`
    "the sheets are listed in the order the server returns their keys (the pair's carrier moves on a reload)": (
        "js/bid-model.js", SECTIONS_OF, "    Object.keys(tabs).forEach(function (id) {", "answers", 0, {"RELOAD_AGREES"}),
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
