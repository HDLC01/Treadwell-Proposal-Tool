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
    """Once, and truthfully whoever switched it off (the slider on the card, or its default on the Defaults tab): the distance fills
    nothing into an off row, and the words say what to do.

    Mutation: leave the sentence out, or say it twice."""
    t = ran["travelOff"]
    assert "Travel Labor was switched off by hand" in t["text"], t["text"]
    assert t["text"].count("switched off") == 1, t["text"]
    assert "or by its default" in t["text"] and "Switch it on and type the guys and the hours." in t["text"], t["text"]
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
    """150 miles is a 300 mile round trip and 5 hours at 60 mph; the sum quotes the trip it was worked from. (This bid carries the
    OLDER Travel row, on auto: its guys are still the man-days, and the line says so.)"""
    text = ran["withMiles"]["text"]
    assert "5 drive hours (one 300 mile round trip at 60 mph from the Olathe office)" in text, text
    assert "Travel Labor: 16.5 man-days x 5 drive hours" in text and "Man-days = guys x days on the labor lines above (16.5 now)." in text, text


def test_a_new_bids_travel_guys_are_worded_as_guys_one_round_trip_each_and_never_as_man_days(ran):
    """The row a far answer fills on a NEW bid has its guys on the crew's size (4 guys, 5 days of Polishing = 20 man-days): the line says
    4 guys, charges the trip to each, and one line says where the guys came from. The 20 man-days appear only as the reference for the
    nights and days the estimator types, never as the Travel guys.

    Mutation: word the crew's size as man-days again, or let the Travel row's auto flag put the man-days line back."""
    c = ran["crewBid"]
    assert (c["guys"], c["follow"]) == (4, "crew")
    assert ("Travel Labor: 4 guys x 5 drive hours (one 300 mile round trip at 60 mph from the Olathe office, for each guy) "
            "x $33.00 = $660.00") in c["lines"]
    assert "Guys = the most guys on any one labor line above (4 now), one round trip each." in c["lines"]
    assert "Man-days = guys x days on the labor lines above (20 now)." not in c["lines"]
    assert "crew" not in c["text"].lower(), "the estimate page's column is Guys, never Crew"


def test_the_remove_existing_hand_is_in_the_crew_and_the_how_note_gives_the_lodging_hint_s_nights(ran):
    """The 2026-10-20 audit's case: Polishing 3 x 5 and Joint filler 3 x 2 with Remove existing joint filler on, priced the sheet's way.
    Guys x days is 21 and the sheet's nights count the fourth hand too, 23. The Travel guys are the CREW (3 + the hand = 4), so there is
    no man-days figure to disagree with; the Lodging hint says 23, and the how-note's reference line says the same 23 (and what guys x days
    is), where it used to say only "the man-days are 21" beside a hint that said 23.

    Mutation: leave the hand out of the crew; let the how-note quote the man-days beside a hint that quotes the sheet's nights."""
    h = ran["handBid"]
    assert (h["crew"], h["travelGuys"], h["manDays"], h["sheetNights"]) == (4, 4, 21, 23)
    assert h["lodgingHint"] == "Nights from the labor above, as the sheet counts them: 23." == h["perDiemHint"]
    assert h["guysHint"] == "Most guys on one labor line above: 4."
    reference = [x for x in h["lines"] if x.startswith("For reference")]
    assert reference == ["For reference, the labor lines above count 23 nights the way the sheet does (guys x days is 21)."], h["lines"]
    assert not any("Guys x days is" in x for x in h["lines"]), "the Travel guys are not claimed to be man-days"
    assert not any(x.startswith("Nights = ") for x in h["lines"]), "no nights are on auto, so nothing explains them as if they were"


def test_nights_on_auto_are_explained_in_the_same_figure_and_the_travel_guys_stay_out_of_it(ran):
    """The same bid with Lodging and Per Diem on auto (an older bid's lines): the nights line explains the sheet's 23 (guys x days is 21,
    said as that and nothing else), the lines charge 23, and the hint agrees. The Travel row is on the crew's size and adds no man-days claim."""
    a = ran["handAuto"]
    assert any(x.startswith("Nights = ") and "(23 now)" in x and "Guys x days is 21" in x for x in a["lines"]), a["lines"]
    assert any(x.startswith("Lodging: 23 nights") for x in a["lines"]) and any(x.startswith("Per Diem: 23 days") for x in a["lines"])
    assert a["lodgingHint"] == "Nights counted from the labor above, as the sheet does."
    assert any(x.startswith("Travel Labor: 4 guys x 5 drive hours") for x in a["lines"])
