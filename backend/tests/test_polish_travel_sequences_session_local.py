"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 6 (continued): a session that never reloads, against a reload, on a job under 70 miles and on one with no distance (round 6, item C2).

The same walk as test_polish_travel_sequences_session.py (read that docstring for what it asks, what it found at 619f092 and why it exists), on a 40 mile job (`session@local`) and on a
bid whose distance lookup finds nothing (`session@unknown`). The paths are the same and so is the rule, but a job under 70 miles fills no drive, so here the sheets' order can only move
a price through what a typed answer brings: the walk types the four answers (50, 300, 190 and cleared) after every prefix, as it does on the far job.

A file of its own (round 6, item O4) so that `--dist loadfile` runs it on another worker than the far job's walk and the mutation walks.
"""
import pytest

from _node import require_node
from _travel_sequences import explain, run, session_walked


@pytest.mark.parametrize("distance", ["@local", "@unknown"])
def test_a_session_that_never_reloaded_and_a_reload_of_what_it_saved_agree_after_every_prefix(distance):
    """The four job types, a copy of the carrier, a fresh Epoxy or Polish sheet and every base change the panel offers, two steps deep from each of the four starts: 276 pages, each
    judged as it stands and after the miles typed as 50, 300, 190 and cleared, on the draft as the session saved it and on the draft as the server returns it. A 40 mile job and one
    whose distance could not be found."""
    require_node()
    got = run("session" + distance, 2)
    session_walked(got)
    assert got["violations"] == {} and got["crashes"] == [] and got["priced"] == {}, explain(got)
