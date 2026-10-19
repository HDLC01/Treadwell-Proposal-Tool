"""The Labor step's "how this is worked out" note (Hanz, 2026-10-06), two wording cases.

A far job whose Travel Labor row is switched off must say so, or the note reads "Travel Labor ...
come on" and then "Travel Labor: off, $0" with nothing in between. And the note must not claim a
round trip with no distance behind it. The distance fills Travel Labor's hours again (Hanz,
2026-10-20): a far answer writes them, and the cleared miles take them back, so a cleared bid has
no hours to word. What is left to word is a bid SAVED while the distance wrote the hours (2026-10-06
to 10-12), which carries the figure and the old marker with no distance stored; the harness builds
one. Runs the real engine through travel-how-harness.js.
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


def test_cleared_miles_take_the_hours_the_distance_wrote_back_and_claim_no_round_trip(ran):
    """It used to leave the seeded hours priced with "from an earlier distance" beside them (a bid whose
    distance had filled them). Now the miles cleared are the hours cleared: nothing is priced, so nothing is claimed."""
    text = ran["cleared"]["text"]
    assert "round trip" not in text, text
    assert "Travel Labor: off, $0" in text, text


def test_hours_saved_by_the_old_distance_with_no_distance_stored_say_they_are_from_an_earlier_one(ran):
    text = ran["earlier"]["text"]
    assert "round trip" not in text, text
    assert "from an earlier distance; type the miles or the hours" in text, text


def test_a_rev2_bid_words_the_nights_the_way_the_cost_box_charges_them(ran):
    """Two crew rows, one paid double: the sheet counts 30 nights where guys x days is 20. The note's Lodging and Per
    Diem lines and its total must be the figures the bid is charged, not the people-day count."""
    r = ran["rev2"]
    assert r["charge"] == {"lodging": 3000, "per_diem": 1500, "total": 4500}
    lodging = next(x for x in r["lines"] if x.startswith("Lodging:"))
    diem = next(x for x in r["lines"] if x.startswith("Per Diem:"))
    assert "30 nights x $100.00 = $3,000.00" in lodging, lodging
    assert "30 days x $50.00 = $1,500.00" in diem, diem
    assert any(x.startswith("Nights = ") and "(30 now)" in x and "Guys x days is 20" in x for x in r["lines"]), r["lines"]


def test_a_saved_bid_still_words_the_people_days(ran):
    """The legacy bid is charged by people-days, and the note keeps saying so."""
    r = ran["legacy"]
    assert r["charge"]["lodging"] == 2000
    assert any(x.startswith("Lodging: 20 nights x $100.00 = $2,000.00") for x in r["lines"]), r["lines"]
    assert any(x.startswith("Man-days = guys x days") and "(20 now)" in x for x in r["lines"]), r["lines"]


def test_with_miles_the_round_trip_is_worded_from_them(ran):
    """150 miles is a 300 mile round trip and 5 hours at 60 mph; the sum quotes the trip it was worked from."""
    text = ran["withMiles"]["text"]
    assert "5 drive hours (a 300 mile round trip at 60 mph from the Olathe office)" in text, text
