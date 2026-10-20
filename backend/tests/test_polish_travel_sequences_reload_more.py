"""THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES, part 5b of 5: the session against a reload, from a local job, with no distance, and with the estimator's say.

Part 5 (test_polish_travel_sequences_reload.py) walks a new far bid and breaks the model to prove the walk can see. This is the rest of its slices, in a file of their own only so
the two run on different workers: the same walk from a 40 mile job and from one whose distance could not be found (the far answer that comes later fills an option's empty row on
both sides alike), and with the estimator's own say on the carrier's Travel Labor row first (3 x 5 typed; the row switched off), which a copy and a demoted base carry.
"""
import pytest

from _node import require_node
from _travel_sequences import explain, run


def _walked(got, judged=80):
    seen = {k: got.get(k) for k in ("runs", "reopens", "plain", "reloadJudged")}
    assert got["runs"] >= 200 and got["reopens"] >= 150 and got["plain"] >= 28 and got.get("reloadJudged", 0) >= judged, "the walk was cut short: %r" % (seen,)


@pytest.mark.parametrize("distance", ["local", "unknown"])
def test_the_session_and_a_reload_agree_on_a_job_that_starts_local_or_with_no_distance(distance):
    """The same walk from a 40 mile job, and from one whose distance could not be found: the far answer that comes later fills an option's empty row on both sides alike."""
    require_node()
    got = run("reload@" + distance, 2)
    _walked(got)
    assert got["violations"] == {} and got["crashes"] == [], explain(got)


@pytest.mark.parametrize("variant", ["Typed", "Off"])
def test_what_the_estimator_said_on_the_carriers_row_prices_the_same_in_the_session_and_after_a_reload(variant):
    """The estimator's own say on the carrier's Travel Labor row first (3 x 5 typed, or the row switched off): a copy and a demoted base carry it, and the session and a reload still price
    the same, at every answer."""
    require_node()
    got = run("reload" + variant, 2)
    _walked(got)
    assert got.get("skipped", 0) == 0 and got["violations"] == {} and got["crashes"] == [], explain(got)
