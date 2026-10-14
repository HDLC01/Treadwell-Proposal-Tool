"""The distance answer fills NO drive hours on a bid (Hanz, 2026-10-12: "nights, days, guys and hours
should have nothing when it starts").

From 2026-10-06 the distance answer wrote a round trip at 60 mph into a new bid's Travel Labor hours
(150 miles -> 5), after the walk that read "7.5 x 0 x $33 = $0". That is gone: the answer still decides
local or far (the travel lines gray or come on), and the hours are typed. Runs the real engine.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "travel-hours-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_a_far_distance_turns_the_lines_on_but_fills_no_hours(ran):
    """Mutation: put the seedTravelHours call back in applyDistance (hours become 5) and this goes red."""
    assert ran["newAt150"] == {"hours": "", "local": False, "lodging": True, "perDiem": True}
    assert ran["stillEmptyAt200"] == ""


def test_hours_the_estimator_typed_stay_theirs(ran):
    assert ran["typedStays"] == 3


def test_a_local_job_and_a_return_to_local_carry_no_hours(ran):
    assert ran["localHours"] == ""
    assert ran["backToLocal"] == ""


def test_a_bid_saved_with_distance_filled_hours_keeps_them(ran):
    """5 hours saved with the old `hours_seed` marker: a new distance answer does not move it."""
    assert ran["savedKeepsItsHours"] == 5


def test_travel_labor_prices_nothing_until_the_hours_are_typed(ran):
    # The harness gives Travel the crew's 16.5 man-days (3 x 5 + 3 x 0.5) as its guys: no hours is $0,
    # and 5 typed hours is 16.5 x 5 x $33 = $2,722.50.
    assert ran["costWithNoHours"] == 0
    assert ran["costWithTypedHours"] == 2722.5
