"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES: the third audit's acceptance test (2026-10-20, of 7d32336), part 1 of 4.

A hand-picked scenario can only hold the switches somebody thought of, and each audit of "a far distance fills Travel Labor" found that the scenarios held every switch
but the next one: Epoxy to Polish to Combo priced the drive twice ($858 + $858 = $1,716 where Kyle types $858), a Combo made Polish saved a price a plain reopen then
contradicted, a typed or cleared or switched-off Travel Labor was refilled on the carrier a switch gave the bid. So tests/js/travel-sequence-harness.js WALKS every
sequence of job types (Polish, Epoxy, Combo, Gyp), each plain or with the crew typed on the new carrier, on a NEW far bid (Wichita, 190 miles: a crew of 4 is 4 x 6.5 x
$33 = $858) and judges the real estimate page after every step:

    DOUBLE          no base section prices more than one Travel Labor row (round 7: ONE_DRIVE, "one priced row on all the bases together", until Hanz's D1 of 2026-10-21 gave a
                    far Combo one drive per base crew)
    MAN_DAYS        no row the tool filled is priced on the man-days
    FAR_BASES       a far job's every base has a Travel Labor row (unless the job or the sheet said it has no drive), and one nobody touched is exactly ITS OWN crew's size x one
                    round trip; a Gyp base too (round 7, D2: it was FAR_CARRIER, and GYP_UNFILLED held a Gyp carrier's row empty)
    STALE           no section that is neither a base nor an option (off) holds a row the distance filled
    ONE_ROW         no section holds two Travel Labor rows
    PLAIN_REOPEN    a plain reopen arms no save, writes nothing and moves no row
    REOPEN_AGREES   the price the draft saved (proposal_lump_sum) is the price a plain reopen of it shows

At 7d32336 the same depth-4 walk (18,724 pages) priced the drive twice in 564 of them (the audit's own fuzz found the same 564), left a filled row on a section that does not
carry the travel in 12,022, left a far carrier on the wrong crew in 158, filled a Gyp carrier in 152 and saved a price (or rows) a plain reopen contradicted in 386; at depth 3
ONE_DRIVE broke in exactly the 54 sequences AUDIT54 lists. The committed slices are the exhaustive ones that run in about a minute; the whole depth-4 walk (which takes
minutes) was run for the commit message and has no violation.

This file also walks a local job (40 miles) and a job whose distance could not be found, where no drive is priced at all. Part 2
(test_polish_travel_sequences_owned.py) walks the same sequences with the estimator's own typed / cleared / switched-off Travel Labor and with the Sheets panel's base changes. Part 3 (test_polish_travel_sequences_mutations.py) breaks a copy of the model one line at a time and
requires the walk to go red, so a clean walk is never a walk that cannot see. Part 4 (test_polish_travel_sequences_distance.py, the fourth audit, of c0255de) adds the
miles corrected AFTER the sheets were restructured, copied and demoted as a step of the walk, and holds every option's Travel Labor to the answer.
"""
import pytest

from _node import require_node
from _travel_sequences import explain, run

# The 54 sequences the audit found pricing the drive twice, and what each prices now. A "+" is the crew typed on the carrier of that step (5 guys on Epoxy, 6 on the
# Polish root); the start crew is 4. Every one is ONE row: the crew of the bid as it is x 6.5 hours x $33 (4 guys $858, 5 guys $1,072.50, 6 guys $1,287); a Combo's crew
# is the most guys on any one line of EITHER base.
AUDIT54 = {
    "epoxy epoxy polish combo": 858, "epoxy epoxy polish combo+": 1287, "epoxy epoxy polish+ combo": 1287, "epoxy epoxy polish+ combo+": 1287,
    "epoxy epoxy+ polish combo": 1072.5, "epoxy epoxy+ polish combo+": 1287, "epoxy epoxy+ polish+ combo": 1287, "epoxy epoxy+ polish+ combo+": 1287,
    "epoxy polish polish combo": 858, "epoxy polish polish combo+": 1287, "epoxy polish polish+ combo": 1287, "epoxy polish polish+ combo+": 1287,
    "epoxy polish combo": 858, "epoxy polish combo combo": 858, "epoxy polish combo combo+": 1287, "epoxy polish combo+": 1287,
    "epoxy polish combo+ combo": 1287, "epoxy polish combo+ combo+": 1287, "epoxy polish+ polish combo": 1287, "epoxy polish+ polish combo+": 1287,
    "epoxy polish+ polish+ combo": 1287, "epoxy polish+ polish+ combo+": 1287, "epoxy polish+ combo": 1287, "epoxy polish+ combo combo": 1287,
    "epoxy polish+ combo combo+": 1287, "epoxy polish+ combo+": 1287, "epoxy polish+ combo+ combo": 1287, "epoxy polish+ combo+ combo+": 1287,
    "epoxy gyp polish combo": 858, "epoxy gyp polish combo+": 1287, "epoxy gyp polish+ combo": 1287, "epoxy gyp polish+ combo+": 1287,
    "epoxy gyp+ polish combo": 858, "epoxy gyp+ polish combo+": 1287, "epoxy gyp+ polish+ combo": 1287, "epoxy gyp+ polish+ combo+": 1287,
    "polish epoxy polish combo+": 1287, "polish epoxy polish+ combo+": 1287, "polish epoxy+ polish combo": 1072.5, "polish epoxy+ polish combo+": 1287,
    "polish epoxy+ polish+ combo": 1287, "polish epoxy+ polish+ combo+": 1287,
    "combo epoxy polish combo+": 1287, "combo epoxy polish+ combo+": 1287, "combo epoxy+ polish combo": 1072.5, "combo epoxy+ polish combo+": 1287,
    "combo epoxy+ polish+ combo": 1287, "combo epoxy+ polish+ combo+": 1287,
    "gyp epoxy polish combo+": 1287, "gyp epoxy polish+ combo+": 1287, "gyp epoxy+ polish combo": 1072.5, "gyp epoxy+ polish combo+": 1287,
    "gyp epoxy+ polish+ combo": 1287, "gyp epoxy+ polish+ combo+": 1287,
}


@pytest.fixture(scope="module")
def audit54():
    require_node()
    return run("audit54")


def test_the_54_sequences_the_audit_found_pricing_the_drive_twice_price_it_once_and_break_no_rule(audit54):
    """The sequences are the audit's, one by one, each judged by every rule after every step (158 pages), and each ends on the Combo with ONE row priced:
    the crew of the bid as it is x 6.5 hours x $33, exactly. Before the fix each was two rows ($643.50 + $858, $1,287 + $1,287, $858 + $1,072.50, ...)."""
    assert audit54["sequences"] == 54 and audit54["runs"] >= 150
    assert audit54["violations"] == {} and audit54["crashes"] == [], explain(audit54)
    got = {line: v["dollars"] for line, v in audit54["exact"].items()}
    assert got == AUDIT54
    assert {v["carrier"] for v in audit54["exact"].values()} == {"Polish"} and {v["jobType"] for v in audit54["exact"].values()} == {"combo"}


def test_every_far_sequence_of_job_types_to_depth_three_breaks_no_rule():
    """EVERY sequence of the four job types, each plain or with the crew typed on the new carrier, three steps deep from each of the four starts: 2,340 pages,
    each judged after its step, 1,792 of them reopened plain to hold the draft to what the page showed. The 54 sequences above are among them."""
    require_node()
    got = run("far", 3)
    assert got["runs"] >= 2300 and got["plain"] >= 290 and got["reopens"] >= 1700, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


def test_every_far_sequence_of_plain_job_switches_to_depth_four_breaks_no_rule():
    """The deeper walk of the same job: four steps, the four job types only (no crew typed): 1,364 pages. Four steps is what the audit's own fuzz went to
    (a switch, a switch back, and two more), where the double-priced sequences were found."""
    require_node()
    got = run("farplain", 4)
    assert got["runs"] >= 1360 and got["plain"] >= 340 and got["reopens"] >= 760, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("mode", ["local", "unknown"])
def test_a_job_under_seventy_miles_or_with_no_distance_prices_no_drive_through_any_sequence(mode):
    """40 miles (and a lookup that finds nothing): no Travel Labor row that nobody touched prices anything, whatever the job type does, and the rest of the rules hold:
    292 pages each, two steps deep."""
    require_node()
    got = run(mode, 2)
    assert got["runs"] >= 290 and got["plain"] >= 36 and got["reopens"] >= 220, "the walk was cut short: %r" % ({k: got[k] for k in ("runs", "plain", "reopens")},)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)
