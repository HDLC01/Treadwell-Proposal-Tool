"""Travel Labor on a NEW bid prices once the job is far (walk 2026-10-06: "7.5 x 0 x $33 = $0").

The 7.5 was Guys (the crew's man-days), the 0 was Hours (Polish B44 = Epoxy!B52, which Kyle's sheet
leaves at 0, "Drive Time: ?"). The distance answer now fills the hours with a round trip at 60 mph
to the half hour -- new bids only (the Travel row opts in with `hours_seed`). Runs the real engine.
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


def test_a_new_far_bid_prices_travel_labor(ran):
    # 150 mi -> 5 h round trip; 16.5 man-days (3x5 + 3x0.5) x 5 h x $33 = $2,722.50, not $0.
    assert ran["newAt150"] == {"hours": 5, "cost": 2722.5}


def test_the_hours_follow_the_distance_until_the_estimator_types_their_own(ran):
    assert ran["followsDistance"] == 7
    assert ran["typedStays"] == 3


def test_a_local_job_and_a_return_to_local_carry_no_hours(ran):
    assert ran["localHours"] == ""
    assert ran["backToLocal"] == ""


def test_a_saved_travel_row_is_never_filled(ran):
    assert ran["saved"] == ""
