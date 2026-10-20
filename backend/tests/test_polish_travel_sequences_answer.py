"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 6: the ANSWER (round 6, part 2, 2026-10-20).

The round-5 verification found a session and a reload of the SAME draft pricing $783 apart (F1: a far Combo, switched to Epoxy, the x on the Epoxy sheet's Travel Labor, switched back to Combo;
F2: a far Polish, the x, an Epoxy sheet made the base, Add Travel Labor on it, the Polish option read). Every walk before this one is blind to it, for two reasons: no step presses the x, and
`shape` LEFT BLANK ROWS OUT of "as it was", so a reopen that appended a blank Travel Labor row to an off root looked the same as the page that saved it. Now:

  * a plain reopen is judged on every Travel Labor row, blank ones too (PLAIN_REOPEN, REOPEN_AGREES, in EVERY mode), and on the job's answer;
  * the x on the carrier's line, the x on an option's, and Add Travel Labor on the carrier and on an option are steps of the walk;
  * a Sheets action, an x and an Add are judged against a reload of the draft the session saved, RE-KEYED AS THE DRAFTS TABLE'S jsonb COLUMN HANDS IT BACK (key length, then bytes): the same
    distance answer (50, 300, 190 miles, or the box cleared) typed in the session and after the reload must leave the same prices and the same Travel Labor rows (RELOAD_AGREES);
  * ANSWER_OWNER: the root's `no_travel_labor` is the JOB's answer, the carrier's and nobody else's. Set while the section that carries the job's travel holds a Travel Labor line, it is a flag
    that has outlived its meaning (an option's x, a leftover row's x, a job-type switch that seeded the new carrier a line the job had said it does not have).

`answerJobs` is F1's family (three steps among the four job types and the answer), `answerSheets` F2's (the Sheets actions and the answer), `answer` every kind of step two deep, and `answers` the
ten sequences of the answer's own, the audit's three among them. (The order of a bid's SHEETS under a reload is the sheets-order work's, round 6, C1: the walk keeps the sheets in the order they were
saved and re-keys everything else.) The last block breaks a COPY of the page or the model one line at a time and requires the walk to report the rule the line keeps.
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
    """The ten sequences (the audit's F1, F2 and S1, an option's x and Add, the root that is an option, a switch after the carrier's x, a base pick around it): every rule after every step. None may be
    skipped (a step the page offers nothing to press on would shorten the sequence without a word)."""
    require_node()
    got = run("answers", 0)
    _walked(got, 40, 5, 19)
    assert got["sequences"] == 10 and got.get("skipped", 0) == 0, "a sequence was cut short: %r" % ({k: got.get(k) for k in ("sequences", "skipped")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)
