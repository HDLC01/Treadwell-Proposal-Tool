"""The Labor step's "how this is worked out" note (Hanz, 2026-10-06), two wording cases.

A far job whose Travel Labor row is switched off must say so, or the note reads "Travel Labor ...
come on" and then "Travel Labor: off, $0" with nothing in between. And once the miles are cleared
the seeded drive hours stay priced, so the note must not still claim "round trip at 60 mph" with
no distance behind it. Only a bid SAVED while the distance filled the hours carries that marker
(since 2026-10-12 the distance fills none), so the harness builds one. Runs the real engine through
travel-how-harness.js.
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


def test_with_miles_the_round_trip_wording_stays(ran):
    assert "round trip at 60 mph" in ran["withMiles"]["text"]
