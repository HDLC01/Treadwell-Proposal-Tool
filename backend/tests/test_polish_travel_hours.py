"""THE DISTANCE FILLS TRAVEL LABOR on a job 70 miles or more out, THE WAY KYLE TYPES IT (Hanz, 2026-10-20).

"For jobs outside the local scope we need to automatically turn on travel time ... it would auto
calculate based on the miles from the treadwell office ... its just an estimate though." The template's Travel
row (Epoxy row 52, Polish row 44) is Guys = (A47*B47)+(A48*B48)+... (the crew's MAN-DAYS) x the Hours typed beside
his note "Drive Time: ?" x $33. The first version of this fill took that formula at its word, and a read-only scan of
every estimate workbook in Kyle's Dropbox (276 out-of-town jobs, 489 real sheets) showed it is not how he works: on 9 of
10 out-of-town sheets he TYPED OVER the formula with the crew size, so each guy is charged ONE round trip, and typed the
round trip's drive hours (median 5.5; most often 4, 6, 5.5, 7 and 5), while hotel and food were charged for every
man-day on the same jobs. So a far answer fills the line's two boxes the way he types them:

    hours  one round trip at 60 mph, to the half hour (190 miles -> 6.5)
    guys   the CREW'S SIZE: the most guys on any labor line, the fourth hand of "Remove existing joint filler" counted,
           the most over both base sheets of a Combo; on auto, following the crew as it is typed

Wichita, 190 miles, four guys for twelve days: 4 x 6.5 x $33 = $858 (the version this replaces said 48 x 6.5 x $33 = $10,296).

Also pinned here, each from an auditor's reproduction on the page harness: a figure the estimator typed OR CLEARED always
wins (the typing leaves a marker on the row, saved with it); a switched-off row is left exactly as it is; a job type
switched in the session fills the new carrier's blank row (B.followDistance); a bid saved before 2026-10-12 on the old
man-days auto keeps them; and a saved bid never moves on open. The page-level half (the lookup landing over a box somebody
is typing in, the notes, the Review, the Gyp wording) is in test_polish_estimate_page.py, test_epoxy_estimate_page.py and
test_v2_gyp.py. Runs the real engine through travel-hours-harness.js.

The last block breaks a COPY of js/bid-model.js one line at a time and requires the harness to notice: the fill, the
typed-wins and cleared-wins rules, crew size against man-days, the sum against the most, the fourth hand, the carrier
section, the off row, the take-back.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from _golden_support import break_source

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "travel-hours-harness.js"


def _run(frontend=FRONTEND):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(HARNESS), str(frontend)], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran():
    return _run()


# ── the fill ─────────────────────────────────────────────────────────────────────────────────────
def test_a_new_bids_travel_row_opens_empty_and_off_auto(ran):
    """The harness's new bid is made by the page's own seeding (seedNewSections): guys and hours empty, off auto, no
    marker of any kind. The distance is what fills it, never the opening."""
    r = ran["newRow"]
    assert r["guys"] == "" and r["days"] == "" and r["guys_auto"] is False
    for marker in ("hours_seed", "guys_follow", "guys_typed", "hours_typed"):
        assert marker not in r, marker


def test_wichita_190_miles_with_four_guys_is_858_dollars_not_ten_thousand(ran):
    """190 miles is a 380 mile round trip: 6.33 hours at 60 mph, 6.5 to the half hour. The guys are the crew's size, 4
    (Polishing, 4 guys for 12 days is 48 man-days, which are NOT the guys), so the line is 4 x 6.5 x $33 = $858: each guy is
    charged one round trip. The line is on and not gray (a far job), the three travel lines are on, and the trip is said in
    words that never use the word crew (the estimate page's column is Guys).

    Mutation: leave the fill out of applyDistance; put the guys on the man-days instead of the crew."""
    w = ran["wichita"]
    assert (w["hours"], w["seed"], w["auto"], w["follow"], w["guys"]) == (6.5, 6.5, True, "crew", 4)
    assert w["manDays"] == 48 and w["crew"] == 4 and w["on"] is True and w["local"] is False
    assert w["cost"] == w["expected"] == 858 and w["rate"] == 33
    assert w["lodging"] is True and w["perDiem"] is True
    assert w["source"] == {"hours": 6.5, "roundTrip": 380, "mph": 60}
    assert w["words"] == "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor lines above"
    assert w["note"] == w["words"] + ". Type more trips for a long job."
    assert "crew" not in w["note"].lower() and "man-days" not in w["note"], "the note claims no man-days and never says crew"
    assert w["hint"] == "Most guys on one labor line above: 4."
    assert w["how"][0] == ("Travel Labor: 4 guys x 6.5 drive hours (one 380 mile round trip at 60 mph from the Olathe office, "
                           "for each guy) x $33.00 = $858.00")
    assert "Guys = the most guys on any one labor line above (4 now), one round trip each." in w["how"]
    assert "man-days" not in w["how"][0], "the Travel guys are a head count, never worded as man-days"


def test_the_answer_fills_the_guys_by_itself_and_not_only_through_the_page_sync(ran):
    """applyDistance alone, with no syncAutoGuys after it: the guys are already the crew's 4.

    Mutation: leave the guys to the page's sync."""
    assert ran["wichitaBare"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}


def test_the_shipped_models_own_auto_row_is_the_older_kind_and_keeps_its_man_days(ran):
    """freshModel's Travel row is on auto WITHOUT the crew marker: it is the row every bid saved before 2026-10-12 holds, so its guys
    stay the man-days and a far answer fills only its hours. (A new bid's row is made off auto by the seeding and is the case above.)"""
    s = ran["shippedRow"]
    assert (s["hours"], s["seed"], s["auto"], s["follow"], s["guys"], s["cost"]) == (6.5, 6.5, True, None, 48, 48 * 6.5 * 33)


def test_with_no_crew_typed_yet_the_hours_are_there_and_the_line_prices_nothing_until_the_guys_are(ran):
    """The guys follow the labor lines, and none has guys yet: 0 x 6.5 x $33. The words say what to type, and the figure moves
    with the crew once it is typed, as the page's changed() keeps it.

    Mutation: take the guys off the crew after the answer (the sync)."""
    n = ran["noCrewYet"]
    assert (n["hours"], n["guys"], n["auto"], n["follow"], n["cost"]) == (6.5, 0, True, "crew", 0)
    assert n["how"].endswith("= $0.00. The guys follow the labor lines above, so type the guys there.")
    assert "It prices once those lines have guys." in n["note"] and "crew" not in n["note"].lower()
    assert n["hint"] == "Most guys on one labor line above."
    assert ran["crewAfter"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}


def test_a_crew_lowered_later_lowers_the_guys_and_the_travel_row_is_never_part_of_the_crew(ran):
    """Polishing goes from 4 guys to 2: the Travel guys follow to 2. Were the Travel row's own 4 counted in the crew it follows,
    they would hold at 4 for ever.

    Mutation: count the Travel row among the lines the crew is read from."""
    assert ran["crewLowered"]["guys"] == 2 and ran["crewLowered"]["cost"] == 2 * 6.5 * 33


def test_one_guy_reads_as_one_guy(ran):
    assert ran["oneGuy"] == {"words": "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for the one guy on the labor lines above",
                             "guys": 1}


def test_the_line_is_priced_at_its_own_rate_and_is_nothing_without_the_fill(ran):
    assert ran["pricedBefore"] == 0 and ran["pricedAfter"] == 858
    assert ran["pricedAtOwnRate"] == 4 * 6.5 * 40, "guys x hours x the line's own rate, never a second rate"


# ── the crew's size ──────────────────────────────────────────────────────────────────────────────
def test_the_crew_is_the_most_guys_on_any_one_line_not_the_sum_and_not_the_man_days(ran):
    """Polishing 4 guys: 4. A mock-up line of 6 guys that is switched OFF is not driving anywhere: still 4; on, it is 6. The
    Travel row's own guys (9) are left out. A non-Travel hours line (a night shift, 5 guys) counts. No lines is none, and no
    model is none.

    Mutation: sum the lines; count a switched-off line; count the Travel row."""
    s = ran["sizes"]
    assert s == {"polishing4": 4, "offLineLeftOut": 4, "mockup6": 6, "travelRowLeftOut": 4, "hoursLineCounts": 5, "empty": 0, "noModel": 0}


def test_the_fourth_hand_on_the_joint_filler_line_counts_as_a_guy(ran):
    """Remove existing joint filler is one more hand on the joint-filler line (the model keeps it in removeExistingHand and not
    in the line's Guys; Kyle's A42 is IF(F29="NO",3,4)). A crew of three whose joint-filler line has three is FOUR with it on, three
    without either condition; a line that is off or has no guys adds none (a line with no guys counts 0). The line prices at 4 guys.

    Mutation: leave the hand out of the crew."""
    h = ran["hand"]
    assert h == {"on": 4, "noRemoveExisting": 3, "noJointFiller": 3, "lineOff": 3, "lineWithNoGuys": 2, "bigger": 4}
    assert ran["handLine"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}


def test_a_combo_has_one_crew_the_most_over_both_base_sheets(ran):
    """Polish 3 guys and Epoxy 4 guys: the carrier is Polish, but one crew drives once, so it is 4 (not the carrier's 3, not the sum 7),
    and the words say whose lines they are. Polish 5 against Epoxy 4 is 5. An Epoxy sheet that is an OPTION is not the base crew: 3.

    Mutation: read the carrier's lines only; sum the sections."""
    c = ran["comboJob"]
    assert c["carrier"] == "Polish" and c["epoxyHasTravel"] is False and c["manDays"] == 15
    assert (c["hours"], c["guys"], c["crew"], c["cost"]) == (6.5, 4, 4, 858)
    assert c["words"].endswith("for each of the 4 guys on the labor lines of the base sheets")
    assert c["hint"] == "Most guys on one labor line of the base sheets: 4."
    assert c["howGuys"] == "Guys = the most guys on any one labor line of the base sheets (4 now), one round trip each."
    assert ran["comboPolishBigger"]["guys"] == 5
    assert (ran["comboOptionLeftOut"]["guys"], ran["comboOptionLeftOut"]["crew"]) == (3, 3)


# ── a typed figure always wins, and so does a cleared one ────────────────────────────────────────
def test_hours_the_estimator_typed_survive_a_second_answer(ran):
    """6.5 filled, 4 typed over it (text, as the box hands it over, with the row marked), 300 miles answered: still 4, the
    marker still the 6.5 the tool wrote, the guys still follow the crew, and no source note is claimed for the hours.

    Mutation: let the answer overwrite a figure that is neither empty nor the tool's own."""
    t = ran["typedHoursSurvive"]
    assert (t["hours"], t["seed"], t["guys"], t["cost"], t["marked"]) == ("4", 6.5, 4, 4 * 4 * 33, True)
    assert t["source"] is None and t["note"] == ""
    assert t["how"] == "Travel Labor: 4 guys x 4 drive hours (typed) x $33.00 = $528.00"
    # and a row from before the markers: a TEXT figure is still never the tool's
    assert ran["typedTextNoMarker"]["hours"] == "4"


def test_hours_that_spell_the_digits_the_tool_wrote_are_still_the_estimators(ran):
    """"6.5" typed over a 6.5 the tool wrote is text; the tool's own is a number. The two are not the same figure, with or without the mark.

    Mutation: tell the tool's figure from a typed one by its digits alone (the 2026-10-06 rule)."""
    assert ran["typedSameDigits"]["hours"] == "6.5"
    assert ran["typedSameDigitsNoMarker"]["hours"] == "6.5"


def test_typed_guys_survive_and_the_hours_are_still_filled(ran):
    """Two guys typed (off auto, marked) before the answer: the answer fills the hours and leaves the 2 alone, in the note too.
    A row saved before the markers with a number typed in the Guys box is the estimator's the same.

    Mutation: put the guys on the crew whatever was typed."""
    g = ran["typedGuysSurvive"]
    assert (g["hours"], g["auto"], g["follow"], g["guys"], g["cost"], g["marked"]) == (6.5, False, None, "2", 2 * 6.5 * 33, True)
    assert "The guys are typed, so Travel Labor is your guys x those hours." in g["note"]
    assert "for each guy" not in g["how"], "typed guys are not described as the crew's size"
    assert ran["savedTypedGuys"]["guys"] == "2" and ran["savedTypedGuys"]["follow"] is None


def test_typed_zero_hours_is_an_answer_and_not_a_blank_to_fill(ran):
    z = ran["typedZeroStays"]
    assert z["hours"] == "0" and z["seed"] is None and z["cost"] == 0


def test_a_cleared_hours_box_stays_empty_after_the_next_answer(ran):
    """Hanz, 2026-10-12: a cleared box stays empty. The audit found a later answer refilling it (an empty box read as nobody's yet).
    Clearing is typing, so the row is marked and the 300 mile answer leaves the hours empty, the cost nothing and the note quiet.

    Mutation: leave the typed guard off the hours fill; leave the marker out of markTypedByHand."""
    c = ran["clearedHours"]
    assert (c["hours"], c["marked"], c["cost"], c["note"]) == ("", True, 0, "")
    assert c["seed"] == 6.5, "the 6.5 the tool once wrote is only remembered, never written back"


def test_a_cleared_guys_box_stays_empty_after_the_next_answer(ran):
    """The Guys box cleared, then a 300 mile answer: the guys stay empty (typed, off the crew), the tool's own hours still move to 10,
    and the line prices nothing until somebody types the guys.

    Mutation: leave the typed guard off the guys fill; leave the marker out of markTypedByHand."""
    c = ran["clearedGuys"]
    assert (c["guys"], c["auto"], c["follow"], c["marked"]) == ("", False, None, True)
    assert (c["hours"], c["seed"], c["cost"]) == (10, 10, 0)


def test_a_box_typed_in_and_cleared_before_the_first_answer_is_cleared_all_the_same(ran):
    assert ran["clearedBeforeAnswer"] == {"hours": "", "seed": None, "auto": False, "follow": None, "guys": "", "cost": 0, "on": True}


def test_the_cleared_mark_is_saved_with_the_row_and_holds_after_a_reopen(ran):
    """Migrate, sync, then an answer: the reopened bid's cleared boxes are still empty. The rule is not session memory."""
    assert ran["clearedSurvivesReopen"] == ran["clearedBeforeAnswer"]


def test_typing_marks_only_the_travel_row_and_typing_guys_takes_the_box_off_the_crew(ran):
    """markTypedByHand leaves every other row exactly as it found it (and a null row is no row); on the Travel row, typing in the Guys
    box leaves guys_typed and takes the crew marker away, and the Hours box mark is separate.

    Mutation: leave the crew marker on a typed Guys box."""
    assert ran["markNonTravel"] == {"same": True, "nullRow": "null"}
    assert ran["markTravel"] == {"follow": None, "typed": True, "hoursTyped": None}


# ── an untouched figure follows, going local, clearing the miles ─────────────────────────────────
def test_an_untouched_figure_follows_the_next_answer(ran):
    """190 miles wrote 6.5; 300 miles moves it to 10 (a 600 mile round trip is exactly 10 hours); the marker moves with it.

    Mutation: stop writing the marker, so the next answer takes the tool's own figure for a typed one."""
    assert ran["untouchedMoves"] == {"hours": 10, "seed": 10, "auto": True, "follow": "crew", "guys": 4, "cost": 4 * 10 * 33, "on": True}


def test_every_answer_in_turn_on_one_bid(ran):
    """190 -> 6.5, 300 -> 10, exactly 70 -> 2.5 (2.33 hours is far), 69.9 -> local and empty, 120.4 -> 4.5."""
    assert ran["sequence"] == [[190, 6.5, 6.5, False], [300, 10, 10, False], [70, 2.5, 2.5, False],
                               [69.9, "", "", True], [120.4, 4.5, 4.5, False]]


def test_going_local_takes_the_tools_hours_back_and_the_line_grays(ran):
    """Under 70 miles the hours the tool wrote go back to empty (the marker with them), so the card is untouched again and grays
    as it always did. The guys stay on the crew: a count that prices nothing without hours.

    Mutation: leave the tool's hours on a local job."""
    g = ran["goingLocal"]
    assert (g["hours"], g["seed"], g["cost"], g["local"], g["note"]) == ("", "", 0, True, "")
    assert g["guys"] == 4 and g["auto"] is True and g["follow"] == "crew"


def test_going_local_leaves_typed_hours_alone(ran):
    """Mutation: take every hours figure back on a local job, typed ones too."""
    k = ran["localKeepsTyped"]
    assert (k["hours"], k["local"], k["cost"]) == ("4", True, 4 * 4 * 33)


def test_far_again_fills_again(ran):
    assert ran["backToFar"]["hours"] == 6.5 and ran["backToFar"]["seed"] == 6.5


def test_clearing_the_miles_is_the_same(ran):
    """The miles cleared: unknown, local, the distance gone, the tool's hours with it; typed hours stay.

    Mutation: leave the take-back out of clearDistance."""
    c = ran["cleared"]
    assert (c["hours"], c["seed"], c["local"], c["distance"]) == ("", "", True, None)
    assert ran["clearedKeepsTyped"]["hours"] == "4"


# ── a bid saved before ───────────────────────────────────────────────────────────────────────────
def test_a_bid_saved_with_typed_hours_on_the_old_auto_keeps_them_and_its_man_days(ran):
    """A pre-2026-10-12 row on auto with 5 hours typed (a number, no marker): a new answer leaves the 5, and its guys are still the
    man-days (48), exactly as they were: no crew marker is put on it."""
    s = ran["savedTypedHoursStay"]
    assert (s["hours"], s["seed"], s["auto"], s["follow"], s["guys"]) == (5, None, True, None, 48)


def test_a_bid_saved_with_the_tools_own_hours_follows_a_new_answer_and_keeps_its_man_days(ran):
    """5 hours saved with the old `hours_seed` marker (2026-10-06 to 10-12, when the distance wrote them) are the tool's figure still,
    so a new answer moves them: 300 miles is 10. Its guys stay the man-days, and its notes still say so in the older words."""
    s = ran["savedMarkerFollows"]
    assert (s["hours"], s["seed"], s["follow"], s["guys"], s["cost"]) == (10, 10, None, 48, 48 * 10 * 33)
    assert "Travel Labor is the man-days on the labor lines above (48) x those hours" in s["note"]
    assert s["how"] == ("Travel Labor: 48 man-days x 10 drive hours (one 600 mile round trip at 60 mph from the Olathe office) "
                        "x $33.00 = $15,840.00")
    assert s["hint"] == "Man-days from the tasks above."
    assert "Man-days = guys x days on the labor lines above (48 now)." in s["howText"]


def test_an_older_auto_row_with_no_hours_gets_the_hours_and_keeps_its_man_days(ran):
    """A pre-2026-10-12 row on auto with no hours: the answer fills the hours, the guys stay the man-days (48, not the crew's 4) and
    carry no marker, so the bid prices as the row always meant.

    Mutation: put the guys on the crew whatever the row followed."""
    a = ran["savedAutoBlankHours"]
    assert (a["hours"], a["follow"], a["guys"], a["manDays"], a["crew"], a["cost"]) == (6.5, None, 48, 48, 4, 48 * 6.5 * 33)


def test_opening_a_saved_far_bid_with_travel_labor_blank_moves_nothing(ran):
    """migrateModel and the page's sync on open: the row is exactly what was saved. The fill runs when an answer is
    applied in a session, never when a bid opens. (The page proves the same through a real open.)"""
    o = ran["openMovesNothing"]
    assert o["same"] is True and o["row"]["days"] == "" and o["row"]["guys"] == ""


def test_a_saved_crew_size_row_reopens_as_saved_and_keeps_following_the_crew(ran):
    """The row a far answer wrote, saved and reopened (migrate, sync): identical, markers and all. A crew changed in the reopened bid
    moves its guys (4 to 6).

    Mutation: leave the crew marker out of the sync, so a reopened row follows nothing."""
    s = ran["savedCrewRow"]
    assert s["sameOnOpen"] is True
    assert (s["afterCrewChange"]["guys"], s["afterCrewChange"]["follow"], s["afterCrewChange"]["cost"]) == (6, "crew", 6 * 6.5 * 33)


# ── which section ────────────────────────────────────────────────────────────────────────────────
def test_an_epoxy_job_fills_the_epoxy_sections_row_with_the_epoxy_crew(ran):
    """The Polish root is off and Epoxy carries the job's travel: its Travel row is the one filled, on its own crew (4 guys, whose 12
    days are 48 man-days), and the root's row is not touched.

    Mutation: fill the row of whatever section the model is, not the carrier's."""
    e = ran["epoxyJob"]
    assert e["carrier"] == "Epoxy" and e["rootRowUntouched"] is True
    assert (e["hours"], e["guys"], e["crew"], e["manDays"], e["cost"]) == (6.5, 4, 4, 48, 858)


def test_a_gyp_job_is_left_exactly_as_it_was(ran):
    """A Gyp crew is priced by the hour and the Gyp sheet works its own drive time, so the answer leaves its Travel row alone. The
    answer is still recorded (far, not local).

    Mutation: take the Gyp carrier out of the guard."""
    g = ran["gypJob"]
    assert g["untouched"] is True and g["local"] is False and g["distance"]["miles"] == 190


def test_a_bid_with_no_travel_labor_row_takes_the_answer_and_nothing_throws(ran):
    n = ran["noTravelRow"]
    assert n["threw"] is None and n["distance"]["miles"] == 190 and "travel" not in n["rows"]


# ── a switched-off row ───────────────────────────────────────────────────────────────────────────
def test_a_switched_off_row_is_left_exactly_as_it_is_no_fill_no_note(ran):
    """Travel Labor off (the slider on its card, or its default on the Defaults tab): a far answer fills nothing into it and the row is
    byte for byte what it was; an off row that held the tool's figures keeps them through a new answer and a local one, with no note;
    switch it on and the next answer is the one that fills it. The Labor step says once that it is off.

    Mutation: take the switched-off guard out of followDistanceHours; let the note speak for an off row."""
    b = ran["offBefore"]
    assert b["untouched"] is True and b["distance"] == 190 and b["local"] is False and b["note"] == ""
    assert b["how"].count("Travel Labor was switched off by hand, or by its default") == 1
    assert "Switch it on and type the guys and the hours." in b["how"] and "Travel Labor: off, $0" in b["how"]
    a = ran["offAfterFill"]
    assert a == {"untouched": True, "hours": 6.5}
    n = ran["offNote"]
    assert n["on"].startswith("6.5 hrs: one 380 mile round trip") and n["off"] == "", "an off row says nothing"
    assert n["sentenceOff"].startswith("6.5 hrs"), "the Review never lists an off row, so only the note is quiet"
    assert ran["offThenLocal"] == {"untouched": True, "hours": 6.5}
    assert ran["offThenOnAgain"] == {"hours": 10, "seed": 10, "auto": True, "follow": "crew", "guys": 4, "cost": 4 * 10 * 33, "on": True}
    assert ran["offByDefault"] == {"enabled": False, "untouched": True}


# ── a job type switched in the session ───────────────────────────────────────────────────────────
def test_the_distance_on_file_fills_a_new_carriers_blank_row_and_nothing_else(ran):
    """followDistance: a far distance already on the model fills the blank Travel row (hours 6.5, the guys on the crew: 4 x 6.5 x
    $33 = $858). A model with no distance on file, a local one, a box typed or cleared, a switched-off row and no model are all left
    as they are.

    Mutation: leave followDistance out; apply the distance to a row that is off."""
    f = ran["followDistance"]
    assert f["before"]["hours"] == "" and f["before"]["guys"] == "" and f["changed"] is True
    assert f["after"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}
    assert f["noDistance"] is True and f["local"] is True and f["off"] is True and f["noModel"] == "null"
    assert (f["typed"]["hours"], f["typed"]["guys"], f["typed"]["cost"]) == ("", "2", 0)


# ── the other two lines, bad input, words ────────────────────────────────────────────────────────
def test_lodging_and_per_diem_are_as_they_were(ran):
    """Switched on by the answer, a hand flip never moved, and their quantities still open empty and typed."""
    ln = ran["lines"]
    assert ln["lodging"] is False and ln["perDiem"] is True
    assert ln["lodgingQty"] == "" and ln["perDiemQty"] == "" and ln["lodgingAuto"] is False and ln["perDiemAuto"] is False


def test_an_answer_with_no_usable_miles_changes_nothing(ran):
    b = ran["badInput"]
    assert b["unchanged"] is True and b["nullModel"] is None and b["clearNull"] == "undefined"


def test_the_words_say_where_the_hours_came_from_and_who_the_trip_is_charged_to(ran):
    """The tool's figure says the trip and charges it to each guy; a figure this distance would not give keeps the older, plainer
    words; one with no distance behind it says so; only a number the tool wrote is the tool's; and a fractional trip is said as it is."""
    w = ran["words"]
    assert w["tool"] == ("Travel Labor: 4 guys x 6.5 drive hours (one 380 mile round trip at 60 mph from the Olathe office, "
                         "for each guy) x $33.00 = $858.00")
    assert w["staleSource"] is None and "(round trip at 60 mph)" in w["stale"]
    assert w["goneSource"] is None and "(from an earlier distance; type the miles or the hours)" in w["gone"]
    assert w["areTools"] == [True, False, False, False, False, False]
    assert w["followsCrew"] == [True, False, False, False]
    assert w["fractional"] == "4.5 hrs: one 240.8 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor lines above"


# ── red without the code: break a COPY of the model one line at a time ───────────────────────────
FILL = "if (!row.hours_typed && (isBlank(row.days) || wrote)) { row.days = hours; row.hours_seed = hours; }"
GUYS_ON = 'if (!row.guys_typed && !row.guys_auto && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }'
GUYS_SET = "if (followsCrew(row)) row.guys = crewSize(model);"
SYNC = "if (r && r.unit === \"hours\" && r.guys_auto) r.guys = followsCrew(r) ? crewSize(model) : manDays;"
TAKE_BACK = 'if (wrote) { row.days = ""; row.hours_seed = ""; }'
GYP_GUARD = 'if (layout === "gyp") return null;'
TOOLS = 'typeof row.days === "number" && typeof row.hours_seed === "number" && row.days === row.hours_seed'
OFF_GUARD = "if (!rowOn(row)) return;   // switched off: no fill and no take-back"
CREW_LINES = "(bases.length ? bases : live.slice(0, 1)).forEach(function (e) { lists.push(e.section.labor); });"
CREW_SKIP = "if (!r || isTravelRow(r) || !rowOn(r)) return;"
MARK_GUYS = 'if (key === "guys") { row.guys_typed = true; delete row.guys_follow; }'
MARK_HOURS = 'else if (key === "days") { row.hours_typed = true; }'
NOTE_OFF = 'if (!row || !rowOn(row)) return "";'

MUTATIONS = {
    "the answer fills no hours": (
        FILL, "void hours;", lambda g: g["wichita"]["hours"] != 6.5),
    "the answer is never applied to Travel Labor": (
        "    followDistanceHours(model, miles);", "    void miles;", lambda g: g["wichita"]["hours"] != 6.5),
    "a typed figure is overwritten by the next answer": (
        FILL, "{ row.days = hours; row.hours_seed = hours; }", lambda g: g["typedHoursSurvive"]["hours"] != "4"),
    "a cleared hours box is refilled by the next answer": (
        FILL, "if (isBlank(row.days) || wrote) { row.days = hours; row.hours_seed = hours; }",
        lambda g: g["clearedHours"]["hours"] != ""),
    "the marker is not written, so the next answer cannot move the tool's figure": (
        FILL, "if (!row.hours_typed && (isBlank(row.days) || wrote)) { row.days = hours; }",
        lambda g: g["untouchedMoves"]["hours"] != 10),
    "the tool's figure is told from a typed one by its digits alone": (
        TOOLS, "!isBlank(row.hours_seed) && num(row.days) === num(row.hours_seed)",
        lambda g: g["typedSameDigitsNoMarker"]["hours"] != "6.5"),
    "the guys are never put on the crew": (
        GUYS_ON, "void 0;", lambda g: g["wichita"]["cost"] != 858),
    "typed guys are put on the crew": (
        GUYS_ON, 'if (!row.guys_auto) { row.guys_auto = true; row.guys_follow = "crew"; }',
        lambda g: g["typedGuysSurvive"]["guys"] != "2"),
    "the older auto row is put on the crew": (
        GUYS_ON, 'if (!row.guys_typed && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }',
        lambda g: g["savedAutoBlankHours"]["guys"] != 48),
    "a cleared guys box is refilled by the next answer": (
        GUYS_ON, 'if (!row.guys_auto && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }',
        lambda g: g["clearedGuys"]["guys"] != ""),
    "the answer leaves the guys to the page's sync": (
        GUYS_SET, "if (followsCrew(row)) void 0;", lambda g: g["wichitaBare"]["guys"] != 4),
    "the guys are the man-days and not the crew's size": (
        GUYS_SET, "if (followsCrew(row)) row.guys = travelManDays(held.rows);", lambda g: g["wichitaBare"]["guys"] != 4),
    "the page's sync puts the guys on the man-days": (
        SYNC, "if (r && r.unit === \"hours\" && r.guys_auto) r.guys = manDays;", lambda g: g["crewAfter"]["guys"] != 4),
    "the sync leaves a reopened crew row to follow nothing": (
        SYNC, "if (r && r.unit === \"hours\" && r.guys_auto && !followsCrew(r)) r.guys = manDays;",
        lambda g: g["savedCrewRow"]["afterCrewChange"]["guys"] != 6),
    "the crew is read from the carrier's lines only": (
        CREW_LINES, "live.slice(0, 1).forEach(function (e) { lists.push(e.section.labor); });",
        lambda g: g["comboJob"]["guys"] != 4),
    "the crew is the sum of the guys on every line": (
        "if (guys > most) most = guys;", "most += guys;", lambda g: g["sizes"]["mockup6"] != 6),
    "the fourth hand is left out of the crew": (
        'if (r.id === "jointfill" && cond.joint_filler && cond.remove_existing_jf) guys += 1;', "void 0;",
        lambda g: g["hand"]["on"] != 4),
    "the Travel row's own guys are part of the crew": (
        CREW_SKIP, "if (!r || !rowOn(r)) return;", lambda g: g["crewLowered"]["guys"] != 2),
    "a switched-off line counts in the crew": (
        CREW_SKIP, "if (!r || isTravelRow(r)) return;", lambda g: g["sizes"]["offLineLeftOut"] != 4),
    "a job under 70 miles keeps the tool's hours": (
        TAKE_BACK, "void 0;", lambda g: g["goingLocal"]["hours"] != ""),
    "a job under 70 miles loses typed hours too": (
        TAKE_BACK, '{ row.days = ""; row.hours_seed = ""; }', lambda g: g["localKeepsTyped"]["hours"] != "4"),
    "clearing the miles leaves the tool's hours": (
        "followDistanceHours(model, null);", "void 0;", lambda g: g["cleared"]["hours"] != ""),
    "a Gyp carrier is filled like the rest": (
        GYP_GUARD, "void 0;", lambda g: g["gypJob"]["untouched"] is False),
    "the fill lands on the model's own rows, not the carrier's": (
        "holder = carrier.section;", "holder = model;",
        lambda g: g["epoxyJob"]["hours"] != 6.5 or g["epoxyJob"]["rootRowUntouched"] is False),
    "a switched-off row is filled": (
        OFF_GUARD, "void 0;", lambda g: g["offBefore"]["untouched"] is False),
    "a switched-off row speaks in the note": (
        NOTE_OFF, 'if (!row) return "";', lambda g: g["offNote"]["off"] != ""),
    "typing in the Guys box leaves no mark": (
        MARK_GUYS, 'if (key === "guys") { delete row.guys_follow; }', lambda g: g["clearedGuys"]["guys"] != ""),
    "typing in the Hours box leaves no mark": (
        MARK_HOURS, 'else if (key === "days") { }', lambda g: g["clearedHours"]["hours"] != ""),
    "typing in the Guys box leaves it on the crew's size": (
        MARK_GUYS, 'if (key === "guys") { row.guys_typed = true; }', lambda g: g["markTravel"]["follow"] is not None),
    "the distance on file is not put on a new carrier's row": (
        "if (miles !== null) followDistanceHours(model, miles);", "void miles;",
        lambda g: g["followDistance"]["after"]["hours"] != 6.5),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_rule_goes_red_when_the_model_changes(tmp_path, name):
    """Each change is a line the fill depends on, broken in a scratch copy of js/bid-model.js; the harness must show
    it. The anchor line must exist exactly once (break_source refuses otherwise), so none can pass by applying nowhere."""
    old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, "js/bid-model.js", old, new)
    got = _run(frontend)
    assert noticed(got), name
