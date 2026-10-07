"""The Labor step's "how this is worked out" note (Hanz, 2026-10-06), two wording cases.

A far job whose Travel Labor row is switched off must say so, or the note reads "Travel Labor ...
come on" and then "Travel Labor: off, $0" with nothing in between. And once the miles are cleared
the seeded drive hours stay priced, so the note must not still claim "round trip at 60 mph" with
no distance behind it. Runs the real engine through travel-how-harness.js.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "travel-how-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_a_far_job_with_travel_labor_switched_off_says_so(ran):
    t = ran["travelOff"]
    assert "Travel Labor was switched off by hand" in t["text"], t["text"]
    assert "Travel Labor: off, $0" in t["text"]


def test_cleared_miles_do_not_claim_a_round_trip(ran):
    text = ran["cleared"]["text"]
    assert "round trip at 60 mph" not in text, text
    assert "from an earlier distance" in text, text


def test_with_miles_the_round_trip_wording_stays(ran):
    assert "round trip at 60 mph" in ran["withMiles"]["text"]
