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
    guys   the CREW'S SIZE: the most guys on any labor line of the sheet, the fourth hand of "Remove existing joint filler" counted;
           on auto, following the crew as it is typed. EVERY BASE SHEET has its own (round 7, Hanz 2026-10-21, D1: a Combo's
           Epoxy and Polish crews travel separately, each its own crew x its own round trip; until then one drive, on the
           carrier, for the most guys over both base sheets), a Gyp base included (D2: it was typed and never filled)

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
    # (since round 7, part 4, P2, the source also says how many round trips the hours are, each one's hours, and whether the section is a Gyp one, whose trips are its mobilizations)
    assert w["source"] == {"hours": 6.5, "roundTrip": 380, "mph": 60, "trips": 1, "each": 6.5, "gyp": False}
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


def test_the_shipped_models_own_auto_row_is_the_older_kind_that_opens_on_its_man_days_and_an_answer_puts_on_the_crew(ran):
    """freshModel's Travel row is on auto WITHOUT the crew marker: it is the row every bid saved before 2026-10-12 holds, and the row a Polish
    root that was never seeded (an Epoxy job's) still holds. Merely opening it leaves its guys on the man-days (48), as it always was. An answer
    applied in a session FILLS its hours, and a row the answer fills goes on the crew's size like every other: 4 guys x 6.5 x $33 = $858. (The
    2026-10-20 audit: left on the man-days, the hours arriving took it from $0 to 48 x 6.5 x $33 = $10,296.) A new bid's row is made off auto by
    the seeding and is the case above.

    Mutation: leave the older auto row on the man-days when the answer fills it."""
    o = ran["shippedOpen"]
    assert (o["hours"], o["auto"], o["follow"], o["guys"], o["cost"]) == ("", True, None, 48, 0)
    s = ran["shippedRow"]
    assert (s["hours"], s["seed"], s["auto"], s["follow"], s["guys"], s["cost"]) == (6.5, 6.5, True, "crew", 4, 858)


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


def test_each_base_of_a_combo_drives_its_own_crew(ran):
    """ROUND 7 (Hanz, 2026-10-21, D1): A FAR COMBO HAS TWO DRIVES, ONE PER BASE CREW. Polish 3 guys and Epoxy 4 guys: the Polish sheet's Travel Labor is
    the Polish crew's, 3 x 6.5 = $643.50, and the Epoxy sheet holds its own, the Epoxy crew's, 4 x 6.5 = $858; each says "the labor lines above" (its own),
    and the how-note on the carrier names the Epoxy sheet's drive too. Polish 5 against Epoxy 4 is 5 on Polish. An Epoxy sheet that is an OPTION is not a
    base: the Polish drive is its own 3. crewSize still reads the most over the bases (4), but no drive is filled with it now. UNTIL ROUND 7 one crew drove once,
    the most over both base sheets (4 on Polish, nothing on Epoxy, "the labor lines of the base sheets"): Kyle's own combo-like estimates put a drive on BOTH
    sheets, each its own crew x its own round trip ("Epoxy trv 4x4; Polish trv 6x4"), so that figure was the wrong one.

    Mutation: fill a base's drive with the biggest crew of the bases; leave the second base without a line (BREAKS below)."""
    c = ran["comboJob"]
    assert c["carrier"] == "Polish" and c["epoxyHasTravel"] is True and c["manDays"] == 15 and c["crew"] == 4
    assert (c["hours"], c["guys"], c["cost"]) == (6.5, 3, 643.5)
    assert c["epoxy"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}
    assert c["words"].endswith("for each of the 3 guys on the labor lines above")
    assert c["epoxyWords"].endswith("for each of the 4 guys on the labor lines above")
    assert c["hint"] == "Most guys on one labor line above: 3."
    assert c["howGuys"] == "Guys = the most guys on any one labor line above (3 now), one round trip each."
    assert c["howEpoxy"] == "Travel Labor on the Epoxy sheet: 4 guys x 6.5 drive hours x $33.00 = $858.00 (that sheet's own guys)."
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
    man-days (48), exactly as they were: no crew marker is put on it. The answer did not FILL this row (its hours are the estimator's), so
    only a row it fills goes on the crew.

    Mutation: put an older auto row on the crew whether or not the answer filled it."""
    s = ran["savedTypedHoursStay"]
    assert (s["hours"], s["seed"], s["auto"], s["follow"], s["guys"]) == (5, None, True, None, 48)


def test_a_bid_saved_with_the_tools_own_hours_opens_on_its_man_days_and_a_new_answer_puts_it_on_the_crew(ran):
    """5 hours saved with the old `hours_seed` marker (2026-10-06 to 10-12, when the distance wrote them) are the tool's figure still. AS SAVED
    (the bid merely opens) it prices on the man-days and says so in the older words. A new answer moves the hours (300 miles is 10), and since it
    fills the row it puts the guys on the crew's size too: 4 x 10 x $33 = $1,320, in the crew's words.

    Mutation: leave the older auto row on the man-days when the answer fills it."""
    o = ran["savedMarkerOpen"]
    assert (o["hours"], o["seed"], o["follow"], o["guys"], o["cost"]) == (5, 5, None, 48, 48 * 5 * 33)
    assert "Travel Labor is the man-days on the labor lines above (48) x those hours" in o["note"]
    assert o["how"] == ("Travel Labor: 48 man-days x 5 drive hours (one 300 mile round trip at 60 mph from the Olathe office) "
                        "x $33.00 = $7,920.00")
    assert o["hint"] == "Man-days from the tasks above."
    assert "Man-days = guys x days on the labor lines above (48 now)." in o["howText"]
    s = ran["savedMarkerFollows"]
    assert (s["hours"], s["seed"], s["auto"], s["follow"], s["guys"], s["cost"]) == (10, 10, True, "crew", 4, 4 * 10 * 33)
    assert s["note"] == ("10 hrs: one 600 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor lines above. "
                         "Type more trips for a long job.")
    assert s["how"] == ("Travel Labor: 4 guys x 10 drive hours (one 600 mile round trip at 60 mph from the Olathe office, for each guy) "
                        "x $33.00 = $1,320.00")
    assert s["hint"] == "Most guys on one labor line above: 4."
    assert "Man-days = guys x days" not in s["howText"], "the Travel guys are a head count now, not man-days"


def test_an_older_auto_row_with_no_hours_gets_the_hours_and_goes_on_the_crew(ran):
    """A pre-2026-10-12 row on auto with no hours (2026-10-20 audit, finding 3): opened, it is $0 on the man-days (48). The answer fills the
    hours and puts the guys on the crew's size (4, not the 48 man-days) with the marker, so it prices 4 x 6.5 x $33 = $858 and not the
    $10,296 the old man-days gave once the hours arrived. Its note says the crew's words.

    Mutation: leave the older auto row on the man-days when the answer fills it."""
    o = ran["savedAutoBlankOpen"]
    assert (o["hours"], o["follow"], o["guys"], o["manDays"], o["cost"]) == ("", None, 48, 48, 0), "opening moves nothing"
    a = ran["savedAutoBlankHours"]
    assert (a["hours"], a["auto"], a["follow"], a["guys"], a["manDays"], a["crew"], a["cost"]) == (6.5, True, "crew", 4, 48, 4, 858)
    assert a["note"].startswith("6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys")
    assert a["hint"] == "Most guys on one labor line above: 4."


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


def test_a_gyp_jobs_drive_fills_from_the_miles_on_its_crews_size(ran):
    """ROUND 7 (Hanz, 2026-10-21, D2): A GYP BASE'S DRIVE FILLS FROM THE MILES like Polish and Epoxy. Its crew is priced by the hour, and its crew's size is
    read off its crew lines the same way (the most guys on one line: a pour of 4 guys entered in hours is 4), so a far answer fills 4 x 6.5 x $33 = $858. It
    was left exactly as it was (the Gyp sheet works its own drive time), and a far Gyp quote priced no drive until somebody typed one.

    Mutation: leave a Gyp base out of the fill (BREAKS below)."""
    g = ran["gypJob"]
    assert g["untouched"] is False and g["local"] is False and g["distance"]["miles"] == 190
    assert g["row"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}


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


# ── a carrier move: the job's one drive is priced once (2026-10-20 audit of the first version) ───
# The page runs `followDistance(model, fromTab)` after a job type switch and after a base change on the Sheets panel; here it is run on the model alone
# (the page, through its own handlers, is in test_polish_travel_switch.py). An Epoxy job, 190 miles, crew 4 x 12: Wichita is $858.
def test_an_epoxy_job_switched_to_polish_prices_the_drive_on_the_crew_and_not_on_the_man_days(ran):
    """The Polish root of an Epoxy job is never seeded, so it holds the model's own older man-days row. When it becomes the carrier the answer on
    file fills it and puts it on the crew's size: 4 guys x 6.5 hours x $33 = $858. Before the fix its hours were filled and its guys stayed on the
    49.5 man-days: 49.5 x 6.5 x $33 = $10,617.75. The old Epoxy row goes off with its section and prices nothing.

    Mutation: leave the older auto row on the man-days when the answer fills it."""
    m = ran["moveEpoxyToPolish"]
    assert m["carrier"] == "Polish" and m["kinds"] == [["Polish", "base"], ["Epoxy", "off"]]
    assert m["root"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}
    assert m["manDays"] == 49.5, "the man-days are not the guys: the old figure would have been 49.5 x 6.5 x $33"
    assert m["drive"] == 858, "the Epoxy row is on a section that is off, so it prices nothing"
    assert m["rootRows"] == 1, "the root keeps its one Travel Labor row"


def test_an_epoxy_job_switched_to_combo_gives_each_base_crew_its_own_drive(ran):
    """ROUND 7 (Hanz, 2026-10-21, D1). The root is the new carrier (the first base) and Epoxy is STILL a base: each crew drives, so Epoxy KEEPS its own
    drive (its crew of 4 x 6.5 = $858) and the root, which became a base, is filled on its own crew (4 x 6.5 = $858): two drives, $1,716. Until round 7 the
    switch took Epoxy's drive back (emptied, markers cleared) so ONE row was priced for the job; that was the one-drive law Hanz replaced. A caller that
    does not name the old carrier (or the sections as they were) gets the same: both bases are settled as bases.

    Mutation: take a base's drive back as if it were a leftover (BREAKS below)."""
    filledFour = {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}
    m = ran["moveEpoxyToCombo"]
    assert m["carrier"] == "Polish" and m["kinds"] == [["Polish", "base"], ["Epoxy", "base"]]
    assert m["root"] == filledFour and m["epoxy"] == filledFour
    assert m["epoxyKeys"] == ["days", "guys", "guys_auto", "guys_follow", "hours_seed", "id", "label", "rate", "unit"], "the Epoxy drive is its own fill"
    assert m["drive"] == 1716 and m["rootRows"] == 1 and m["epoxyRows"] == 1, "each base holds its one row, and each is priced"
    n = ran["moveEpoxyToComboInferred"]
    assert (n["root"]["cost"], n["epoxy"]["cost"], n["drive"], n["rootRows"], n["epoxyRows"]) == (858, 858, 1716, 1, 1)


def test_a_combo_switched_to_epoxy_leaves_epoxy_its_own_drive_and_the_off_root_gives_its_fill_back(ran):
    """ROUND 7 (Hanz, 2026-10-21, D1). On the Combo both bases drove; switched to Epoxy, the remaining base KEEPS ITS OWN drive (4 guys x 6.5 x $33 = $858,
    the Epoxy crew's) and the root, which is off now, gives back what the distance filled on it (its row stays, emptied): the how-note shows Epoxy's line. Until
    round 7 Epoxy had no row on the Combo and the root's row was carried to it; a base that stays a base now keeps its own, and nothing is carried between bases.

    Mutation: carry the old carrier's row onto a base that drives already; leave the off root's fill on it (BREAKS below)."""
    m = ran["moveComboToEpoxy"]
    assert m["carrier"] == "Epoxy" and m["kinds"] == [["Polish", "off"], ["Epoxy", "base"]]
    assert m["epoxy"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}
    assert m["rootHasRow"] is True and m["root"] == EMPTIED and m["drive"] == 858
    assert m["how"] == ("Travel Labor: 4 guys x 6.5 drive hours (one 380 mile round trip at 60 mph from the Olathe office, for each guy) "
                        "x $33.00 = $858.00")
    n = ran["moveComboToEpoxyInferred"]
    assert n["epoxy"] == m["epoxy"] and n["rootHasRow"] is True and n["drive"] == 858, "a caller that does not name the old carrier gets the same"
    assert ran["moveOptionNotCarried"] == {"epoxyHasRow": False, "rootKeepsRow": True, "kinds": [["Polish", "option"], ["Epoxy", "base"]]}, (
        "an option's Travel Labor row is its own: it is never carried to the carrier")
    assert ran["moveNoTravelLabor"] == {"epoxyHasRow": False, "rootKeepsRow": True}, (
        "a bid whose library said no Travel Labor has no row to carry")


TYPED_ROOT = {"hours": "5", "seed": 6.5, "auto": False, "follow": None, "guys": "3", "cost": 3 * 5 * 33, "on": True}
EMPTIED = {"hours": "", "seed": None, "auto": False, "follow": None, "guys": "", "cost": 0, "on": True}
EMPTIED_KEYS = ["days", "guys", "guys_auto", "id", "label", "rate", "unit"]
TYPED_KEYS = ["days", "guys", "guys_auto", "guys_typed", "hours_seed", "hours_typed", "id", "label", "rate", "unit"]


FILLED_FOUR = {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}
FILLED_KEYS = ["days", "guys", "guys_auto", "guys_follow", "hours_seed", "id", "label", "rate", "unit"]


def test_a_row_the_estimator_typed_on_a_base_that_stays_a_base_stays_its_own(ran):
    """ROUND 7 (Hanz, 2026-10-21, D1). Epoxy's row was typed (3 guys, 5 hours, both marked): it is theirs, and it is the EPOXY CREW's drive. The switch to Combo
    keeps Epoxy a base, so it keeps what was typed, markers and all, and the root, which became a base, drives its own crew: 4 x 6.5 = $858 beside the typed $495.
    Until round 7 there was one drive for the job, so the typed row went to the new carrier and Epoxy gave its row back ($495 in all); the third audit's "$858 +
    $495" was a double charge under that law and is the two crews' two drives under Hanz's. What the estimator typed still follows the job's drive when a
    SINGLE-base job's base moves (test_what_the_estimator_said_follows_a_newly_seeded_carrier_and_only_a_row_nobody_touched_is_filled).

    Mutation: carry the typed row off a base that stays a base (BREAKS below)."""
    t = ran["moveTypedFollows"]
    assert t["epoxy"] == TYPED_ROOT and t["epoxyMarks"] == {"typed": True, "hoursTyped": True, "off": False, "keys": TYPED_KEYS}
    assert t["root"] == FILLED_FOUR and t["rootMarks"]["keys"] == FILLED_KEYS
    assert t["drive"] == 495 + 858 and t["rootRows"] == 1 and t["epoxyRows"] == 1


def test_a_cleared_box_on_a_base_that_stays_a_base_is_never_refilled(ran):
    """ROUND 7 (D1). The Hours box cleared on Epoxy, or the Guys box: the empty box is the estimator's answer for the Epoxy crew, and Epoxy stays a base on the
    switch to Combo, so it keeps it ($0); the root, a base now, drives its own crew ($858). A later answer (300 miles) leaves the cleared box empty and moves only
    the tool's own figure. (Until round 7 the cleared box moved to the root with the job's one drive.)

    Mutation: refill a box the estimator cleared."""
    c = ran["moveClearedFollows"]
    h, g = c["hours"], c["guys"]
    assert (h["epoxy"]["hours"], h["epoxy"]["cost"]) == ("", 0) and (g["epoxy"]["guys"], g["epoxy"]["cost"]) == ("", 0)
    assert h["root"] == FILLED_FOUR and g["root"] == FILLED_FOUR and h["drive"] == g["drive"] == 858
    s = ran["moveClearedStaysEmpty"]
    assert s["hours"]["hours"] == "" and s["guys"]["guys"] == "" and s["guys"]["hours"] == 10, "the answer moved the tool's hours, never the box they cleared"


def test_a_switched_off_row_on_a_base_that_stays_a_base_stays_off(ran):
    """ROUND 7 (D1). The slider is the estimator's too: Epoxy's Travel Labor switched off, the switch to Combo, and Epoxy, still a base, keeps its row
    switched off with the figures it held; the root, a base now, drives its own crew (the shipped mock-up's 3 guys: 3 x 6.5 = $643.50), the only drive priced.
    (Until round 7 the switched-off row moved to the root with the job's one drive, and nothing was priced.)

    Mutation: switch a row the estimator switched off back on, or fill it."""
    o = ran["moveOffFollows"]
    assert o["epoxyMarks"]["off"] is True and o["epoxy"]["on"] is False and o["epoxy"]["cost"] == 0
    assert o["root"]["on"] is True and o["root"]["follow"] == "crew" and o["root"]["guys"] == 3 and o["drive"] == 643.5


def test_an_options_row_and_a_carrier_that_did_not_move_are_left_alone(ran):
    """An old carrier that is an OPTION afterwards keeps its own row (an option is priced apart, for its own crew). A carrier handed in that is the
    carrier already moves nothing and takes nothing back, and no model is no model.

    Mutation: take back an option's row; run the move when the carrier did not."""
    assert ran["moveOptionStays"] == {"carrier": "Polish", "same": True}
    assert ran["moveSameCarrier"] == {"same": True}
    assert ran["moveNoModel"] == "null"


def test_a_row_is_copied_and_never_shared_when_the_old_carrier_keeps_no_other_row(ran):
    """A root that holds only Travel Labor cannot give it away and still have a labor list, so the row is COPIED, as pickBase's move does: both
    sections have a row, and they are two objects (a figure typed into one is never typed into the other).

    Mutation: hand the new carrier the old carrier's own row object."""
    c = ran["moveCopy"]
    assert c["rootKeeps"] is True and c["epoxy"] is not None and c["aliased"] is False


def test_a_carrier_move_under_a_local_job_fills_nothing(ran):
    """Under 70 miles there is nothing to fill: Combo to Epoxy leaves Epoxy its own row (round 7: it was a base, and drives its own crew), empty of hours, on
    the crew it follows, and the root, off now, keeps its own."""
    m = ran["moveLocal"]
    assert m["local"] is True and m["rootHasRow"] is True
    assert (m["epoxy"]["hours"], m["epoxy"]["cost"]) == ("", 0)


# ── the third audit (2026-10-20, of 7d32336): EVERY restructure settles the job's one drive ─────────────────────────────────────
def test_every_section_that_is_off_gives_the_filled_row_back_and_every_base_drives_its_own(ran):
    """THE HIGH FINDING, under round 7's law. Epoxy to Polish to Combo once priced the drive twice for ONE crew: Epoxy's row, filled for the Epoxy job and left on the
    section when Polish switched it off, was priced again the day Combo turned the section back on. Every Travel Labor row the distance filled and nobody touched,
    on a section that is OFF, is still emptied with its markers when the job restructures, so a sheet that comes back is filled afresh for its own crew. What changed
    (Hanz, 2026-10-21, D1) is that a Combo's two bases are two crews, and each drives: through Epoxy -> Polish -> Combo -> Epoxy -> Combo the drives priced are
    $858, $858 + $858, $858 and $858 + $858, each base its own crew of 4 x 6.5, and the sheet that is off at each step holds an empty row. (Until round 7 the
    Combo's second base gave its drive back and one row was priced every time.)

    Mutation: leave an off section's fill on it; take a base's drive back (BREAKS below)."""
    s = ran["settleSequence"]
    for step, carrier in (("toPolish", "Polish"), ("toCombo", "Polish"), ("toEpoxy", "Epoxy"), ("toComboAgain", "Polish")):
        assert s[step]["carrier"] == carrier, step
    assert [s[k]["drive"] for k in ("toPolish", "toCombo", "toEpoxy", "toComboAgain")] == [858, 1716, 858, 1716], "each base crew's own drive, every time"
    assert s["toPolish"]["epoxy"] == EMPTIED and s["toPolish"]["epoxyKeys"] == EMPTIED_KEYS, "Epoxy is OFF here and gives its row back"
    assert s["toCombo"]["epoxy"] == FILLED_FOUR and s["toComboAgain"]["epoxy"] == FILLED_FOUR, "a base again: its own crew's drive, filled afresh"
    assert s["toEpoxy"]["polish"] == EMPTIED and s["toComboAgain"]["polish"] == FILLED_FOUR
    t = ran["takeBackOff"]
    assert t["off"] == EMPTIED and t["offKeys"] == EMPTIED_KEYS, "an off section's filled row is taken back, markers and all"
    assert t["option"] is True, "an option's row is its own"
    assert t["typedOff"] is True, "a row the estimator typed is theirs, on an off section too"
    assert t["offRowStays"] is True, "a row the estimator switched off is theirs, on a base that does not carry the travel (its own drive, round 7)"


def test_the_estimators_row_is_told_from_one_the_distance_filled(ran):
    """travelRowIsTheEstimators: a box typed in or cleared (the markers, a figure in a Guys box that is off auto, hours that are not the tool's) or a row switched
    off. A blank row and one the distance filled are nobody's. The two readings never overlap: a row is not both filled and the estimator's.

    Mutation: let typed hours count as the tool's (BREAKS below)."""
    a = ran["autoFilled"]
    assert a["estimators"] == {"crewRow": False, "crewBlankHours": False, "legacyWithToolHours": False, "legacyBlank": False, "empty": False,
                               "typedGuysMarked": True, "typedGuysNoMarker": True, "clearedGuys": True, "typedHoursMarked": True,
                               "clearedHoursMarked": True, "typedHoursNoMarker": True, "off": True, "offEmpty": True, "noRow": False}
    for k, v in a["estimators"].items():
        if k in a and v is True:
            assert a[k] is False, k + ": a row cannot be both the tool's fill and the estimator's"


def test_what_the_estimator_said_follows_a_newly_seeded_carrier_and_only_a_row_nobody_touched_is_filled(ran):
    """THE MEDIUM FINDING. A Polish job (crew 4 x 12, 190 miles) switched to Epoxy: Epoxy is a NEW section and the library gives it a blank Travel Labor row
    as the carrier. A row nobody touched is filled fresh: 4 x 6.5 x $33 = $858. But a typed 3 x 5, a cleared box and a switched-off row all MOVE to Epoxy with
    the job's drive and are NOT filled (the audit: the new carrier's blank row was auto-filled to $858 in all three cases), and the old carrier gives the row
    back empty. A later answer leaves what moved alone, and the row follows the carrier on again.

    Mutation: leave what the estimator said on the old carrier (BREAKS below)."""
    f = ran["followsSeeded"]
    assert f["auto"]["epoxy"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 4, "cost": 858, "on": True}
    assert f["auto"]["root"] == EMPTIED and f["auto"]["drive"] == 858
    assert f["typed"]["epoxy"] == TYPED_ROOT and f["typed"]["epoxyMarks"]["keys"] == TYPED_KEYS and f["typed"]["drive"] == 495
    assert f["clearedHours"]["epoxy"]["hours"] == "" and f["clearedHours"]["epoxyMarks"]["hoursTyped"] is True and f["clearedHours"]["drive"] == 0
    assert f["clearedGuys"]["epoxy"]["guys"] == "" and f["clearedGuys"]["epoxyMarks"]["typed"] is True and f["clearedGuys"]["drive"] == 0
    assert f["off"]["epoxy"]["on"] is False and f["off"]["epoxyMarks"]["off"] is True and f["off"]["drive"] == 0
    for name in ("typed", "clearedHours", "clearedGuys", "off"):
        assert f[name]["root"] == EMPTIED and f[name]["rootMarks"]["keys"] == EMPTIED_KEYS, name + ": the old carrier gives the row back"
        assert (f[name]["epoxyRows"], f[name]["rootRows"]) == (1, 1), name
    assert f["laterAnswer"]["typed"] == TYPED_ROOT and f["laterAnswer"]["clearedHours"]["hours"] == ""
    b = f["backToPolish"]
    assert b["root"] == TYPED_ROOT and b["rootMarks"]["typed"] is True and b["epoxy"] == EMPTIED and b["drive"] == 495, "and it follows the carrier back"


def test_when_the_new_carriers_own_row_is_the_estimators_too_both_stay(ran):
    """Epoxy typed 3 x 5 and the root typed 2 x 4, switched to Polish (a single-base job's one base moves, so the job's drive would follow it): neither is the tool's to
    move, and there is nothing to choose between them, so both stay exactly as typed, and the drive priced is the new base's own 2 x 4. (Switched to Combo, both are bases
    since round 7 and each keeps its own anyway.)

    Mutation: let the old carrier's row replace a new carrier's row that is the estimator's too (BREAKS below)."""
    b = ran["ownedBothStay"]
    assert b["root"]["guys"] == "2" and b["root"]["hours"] == "4" and b["epoxy"] == TYPED_ROOT
    assert b["drive"] == 2 * 4 * 33


def test_a_section_that_holds_only_its_travel_labor_row_hands_the_estimators_over_and_is_never_left_with_nothing(ran):
    """A root (or any section) whose only labor row is Travel Labor: the rows change places, so each section keeps its one row and no labor list is left
    empty (an empty root reads as the four shipped rows). The typed row goes to the new base; the lone section keeps an empty one. (A SINGLE-base job's switch,
    Epoxy to Polish and Polish to Epoxy, since round 7: the job's one drive follows its one base, and a Combo's bases each keep their own.)

    Mutation: leave what the estimator said on the old carrier (BREAKS below)."""
    o = ran["ownedFromLoneRow"]
    assert o["root"] == TYPED_ROOT and o["epoxy"] == EMPTIED and o["epoxyRows"] == 1 and o["drive"] == 495
    c = ran["copyReleased"]
    assert c["epoxy"] == TYPED_ROOT and c["root"] == EMPTIED and c["rootMarks"]["keys"] == EMPTIED_KEYS and c["aliased"] is False and c["drive"] == 495, (
        "a COPY (the old carrier keeps no other row) is released: the estimator's row is not left priced on both")


def test_the_callers_name_for_the_old_carrier_beats_looking_for_it(ran):
    """An Epoxy job (the Polish root is off and holds its own blank Travel Labor row, first in the order) whose Epoxy row was typed 3 x 5, switched to Gyp.
    Named, the old carrier is Epoxy and its typed row goes with the job's drive. Looked for, the first section that is not the carrier and holds a row is the
    ROOT, whose blank row would be carried instead, and the typed row would be stranded.

    Mutation: look for the old carrier even when the caller names it (BREAKS below)."""
    n = ran["namedBeatsLooked"]
    assert n["carrier"] == 'Gyp (USG 1-8")'
    assert n["named"]["gyp"] == TYPED_ROOT and n["named"]["gypMarks"]["keys"] == TYPED_KEYS and n["named"]["epoxy"] is None and n["named"]["rootRows"] == 1
    assert n["looked"]["gyp"]["cost"] == 0 and n["looked"]["epoxy"] == TYPED_ROOT, "the proof the two readings differ: the lookup strands the typed row"


def test_a_gyp_base_is_filled_like_any_other_and_what_the_estimator_typed_goes_to_it(ran):
    """ROUND 7 (Hanz, 2026-10-21, D2). A Gyp base's drive fills from the miles like Polish and Epoxy: an Epoxy job switched to Gyp gives the new Gyp base its own
    row filled by the rule (6.5 hours, its crew's size: 0 until a crew line has guys, then 4 x 6.5 x $33 = $858 with a pour of 4), and the Epoxy section, off now,
    gives its fill back. Carried to a Gyp section that had no row (the job's one drive follows its one base), the row is filled there on Gyp's crew. What the estimator
    typed goes to Gyp as theirs. Until round 7 a Gyp base's drive was typed and the distance never filled it (the fill given back wherever it landed).

    Mutation: leave a Gyp base out of the fill (BREAKS below)."""
    g = ran["gypNeverFilled"]
    assert g["carrier"] == 'Gyp (USG 1-8")' and g["epoxy"] == EMPTIED
    assert g["gypNoCrew"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 0, "cost": 0, "on": True}
    assert g["gyp"] == FILLED_FOUR and g["drive"] == 858
    c = ran["gypCarriedUnfilled"]
    assert c["gyp"] == {"hours": 6.5, "seed": 6.5, "auto": True, "follow": "crew", "guys": 0, "cost": 0, "on": True} and c["gypKeys"] == FILLED_KEYS
    t = ran["gypTypedFollows"]
    assert t["gyp"] == TYPED_ROOT and t["gypMarks"]["typed"] is True and t["epoxy"] == EMPTIED


def test_followDistance_never_throws_for_a_section_it_cannot_find_or_read(ran):
    """The caller's name for a section the model does not have, and a bid whose sections cannot be read (a saved `tabs` that is not well formed), have
    nothing to carry: the job is settled as far as it can be and nothing throws (the page runs this on init, where a throw is a blank estimate).

    Mutation: let the carry throw (BREAKS below)."""
    n = ran["followNeverThrows"]
    assert n["namelessThrew"] is None and n["brokenThrew"] is None and n["namelessRowKept"] is True


def test_a_restructure_that_keeps_the_carrier_keeps_its_own_crew_and_fills_nothing(ran):
    """THE SECOND MEDIUM FINDING, under round 7's law. A Combo (Polish 4 guys, Epoxy 6) made Polish keeps the root as the carrier. The root's drive is the Polish crew's
    own, 4 x 6.5 = $858, on the Combo and after the switch alike (round 7, D1: each base its own crew; until then it read the Combo's bigger 6 guys, $1,287, and the
    settling had to re-derive it), and the Epoxy section, off now, gives its own drive back (its row stays, emptied). A carrier that stayed fills NOTHING, so a far bid
    saved with a blank row is not filled by it.

    Mutation: settle a carrier that stayed as if it had moved (BREAKS below)."""
    k = ran["carrierKept"]
    assert k["before"] == FILLED_FOUR and k["after"] == FILLED_FOUR
    assert k["crew"] == 4 and k["carrier"] == "Polish" and k["epoxyRows"] == 1 and k["epoxy"] == EMPTIED and k["drive"] == 858
    assert ran["carrierKeptFillsNothing"] == EMPTIED


def test_a_repeat_of_the_carriers_typed_row_on_a_section_that_is_off_is_given_back_but_a_different_one_stays(ran):
    """A section that holds an exact repeat of the carrier's row is what the job's one drive leaves behind when it is CARRIED to a new base as a copy (the old base kept no
    other row). On a section that is OFF, a row that REPEATS the carrier's exactly (the same guys, hours and hands on them) is that leftover and is given back (emptied,
    markers gone); one that says something else (typed 2 x 4) is the estimator's own choice and stays. (Every clause of "exactly" is pinned ALONE in
    test_a_copy_is_given_back_only_when_it_repeats_the_carriers_row_in_every_respect.)

    ON A BASE (round 7, part 3: the round-7 audit's F1; part 4, P1). The copy made a base beside the carrier, settled as the page settles it (followDistance), gives the repeat back too, and
    drives its OWN crew on the TRIP the estimator typed: 4 x 5 = $660 beside the carrier's typed 3 x 5 = $495 (Kyle's sheets carry the same trip on both crews, each its own guys). Round 7,
    part 1 pinned $495 + $495 here, "a base keeps its own drive (D1)", and that was wrong: the copy's 3 guys are not that sheet's crew, they are the tool's copy (copySection marks it
    `tool_copy`) of the one figure the estimator typed once, on the carrier's sheet. Part 3 gave the whole copy back and refilled it from the miles, 4 x 6.5 = $858, a trip nobody typed for
    it; part 4 keeps the typed 5 hours (marked typed) and puts the guys on the copy's own crew of 4. A copy that says something else (2 x 4) does not repeat the carrier's and stays.

    Mutation: leave the repeat on its off section (BREAKS below); never give a copy on a base back (test_polish_travel_round7_part3.py)."""
    c = ran["copyRepeat"]
    s = c["same"]
    assert s["kinds"] == [["Polish", "base"], ["Copy1", "off"]]
    assert s["root"] == TYPED_ROOT and s["copy"] == EMPTIED and s["copyMarks"]["keys"] == EMPTIED_KEYS and s["drive"] == 495
    d = c["different"]
    assert d["root"] == TYPED_ROOT and d["copy"]["guys"] == "2" and d["copy"]["hours"] == "4" and d["copy"]["cost"] == 2 * 4 * 33 and d["drive"] == 495
    b = c["base"]
    assert b["kinds"] == [["Polish", "base"], ["Copy1", "base"]]
    assert b["root"] == TYPED_ROOT and b["copy"] == dict(FILLED_FOUR, hours="5", cost=4 * 5 * 33) and b["copyMarks"]["hoursTyped"] is True and b["copyMarks"]["typed"] is False
    assert b["copyMarks"]["keys"] == sorted(FILLED_KEYS + ["hours_typed"]) and b["drive"] == 495 + 4 * 5 * 33
    bd = c["baseDifferent"]
    assert bd["kinds"] == [["Polish", "base"], ["Copy1", "base"]]
    assert bd["root"] == TYPED_ROOT and bd["copy"]["guys"] == "2" and bd["copy"]["hours"] == "4" and bd["copy"]["cost"] == 2 * 4 * 33 and bd["drive"] == 495 + 2 * 4 * 33


def test_an_options_own_crew_counts_the_fourth_hand_of_remove_existing_joint_filler(ran):
    """ownCrewSize is the crew an option's Travel Labor follows: its own lines' most guys, and the fourth hand of Remove existing joint filler counts through
    the joint-filler line exactly as it does for the job's crew (Polishing 3 and Joint filler 3 + 1 are a crew of 4, where the lines alone say 3).

    Mutation: leave the job's conditions out of an option's own crew (BREAKS below)."""
    o = ran["optionHand"]
    assert o == {"withHand": 4, "noConditions": 3, "noModel": 3}


def test_which_rows_the_distance_filled_and_so_may_be_taken_back(ran):
    """A row the distance filled and nobody typed in (the crew's size or the older man-days, with the tool's own hours or none) can be taken
    back. A row with any figure of the estimator's in it cannot: typed guys (marked, or a figure in a box off auto), cleared guys, hours typed
    (marked, or text that is not the tool's number). A row nothing was ever written in is not a filled row, so there is nothing to take back.

    Mutation: let typed guys, typed hours, or a cleared box count as filled."""
    a = ran["autoFilled"]
    assert (a["crewRow"], a["crewBlankHours"], a["legacyWithToolHours"]) == (True, True, True)
    assert (a["legacyBlank"], a["empty"], a["noRow"]) == (False, False, False)
    assert (a["typedGuysMarked"], a["typedGuysNoMarker"], a["clearedGuys"]) == (False, False, False)
    assert (a["typedHoursMarked"], a["typedHoursNoMarker"], a["clearedHoursMarked"]) == (False, False, False)


def test_an_options_travel_labor_follows_its_own_lines_not_the_base_crew(ran):
    """A copy of the carrier made as an OPTION carries its own Travel Labor row (priced apart, for its own crew). Its guys follow the option's OWN
    labor lines: 6 guys typed on the copy's Polishing are 6 on its Travel Labor, 6 x 6.5 x $33 = $1,287, while the base crew, and the base's own row,
    stay 4. (The first version made them 4: the option's row followed the base crew.) The words say "above" for an option's own lines, and since round 7 for a
    base's too (each base drives its own crew, D1: a Combo's carrier said "the labor lines of the base sheets" while its one drive was the bigger crew of both).

    Mutation: make an option's crew-following row follow the job's base crew."""
    o = ran["optionCrew"]
    assert o["copyKind"] == "option" and o["baseCrew"] == 4 and o["ownCrew"] == 6 and o["noModel"] == 0
    assert (o["copy"]["guys"], o["copy"]["follow"], o["copy"]["cost"]) == (6, "crew", 6 * 6.5 * 33)
    assert (o["root"]["guys"], o["root"]["cost"]) == (4, 858)
    w = ran["optionWords"]
    assert (w["guys"], w["jobCrew"]) == (6, 4)
    assert w["own"].endswith("for each of the 6 guys on the labor lines above") and w["base"] == w["own"]
    assert w["ownHint"] == w["baseHint"] == "Most guys on one labor line above: 6."
    assert w["ownNote"].endswith("for each of the 6 guys on the labor lines above. Type more trips for a long job.")


# ── the notes say what the guys are ──────────────────────────────────────────────────────────────
def test_typed_guys_are_worded_as_guys_one_round_trip_each_and_never_as_man_days(ran):
    """The 2026-10-20 audit: a typed count read "2 man-days (typed)" in the how-note beside a hint "Man-days from the tasks above: 48." that invited typing
    48, which charges every man-day a round trip. A typed Travel Labor count is guys: "2 guys (typed)", the hint says "One round trip for each guy.", and
    the man-days appear only as the reference for the nights and days typed in the two lines below.

    Mutation: word a typed count as man-days again; put the man-days back in the hint."""
    t = ran["notesTyped"]
    assert t["how"] == ("Travel Labor: 2 guys (typed) x 6.5 drive hours (one 380 mile round trip at 60 mph from the Olathe office) x $33.00 = $429.00")
    assert t["hint"] == "One round trip for each guy."
    assert "man-days" not in t["how"] and "Man-days" not in t["hint"]
    assert "The guys are typed, so Travel Labor is your guys x those hours." in t["note"]
    assert "For reference, the man-days on the labor lines above are 48." in t["howText"], "the reference is for the nights and days typed below"
    assert "crew" not in (t["note"] + t["hint"] + t["howText"]).lower(), "the estimate page's column is Guys, never Crew"
    # ...and when the nights and days are NOT typed, a far answer fills them (the fifth audit's decision), so the words say they follow the labor, with the man-days as the figure
    f = ran["notesFollowing"]
    assert f["how"] == t["how"], "the Travel guys are worded the same either way"
    assert "Nights and per diem days follow the man-days on the labor lines above (48 now), a night and a day of per diem for each man-day, Kyle's way." in f["lines"]
    assert not any(x.startswith("For reference") for x in f["lines"]), "nothing is typed below, so there is no reference to give"
    assert "crew" not in f["howText"].lower() and "man-days (typed)" not in f["howText"]


def test_a_cleared_guys_box_is_empty_and_says_so_and_never_the_guys_are_typed(ran):
    """The Guys box cleared: it is EMPTY. The note under the card says the box is empty and Travel Labor adds nothing until the guys are typed (it used
    to say "The guys are typed, so Travel Labor is your guys x those hours" over an empty box); the how-note says "0 guys" and what to do.

    Mutation: say the guys are typed whether or not there is a figure in the box."""
    c = ran["notesCleared"]
    assert "The guys are typed" not in c["note"]
    assert c["note"] == ("6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office. The Guys box is empty, so Travel Labor adds nothing until you "
                         "type the guys. Type more trips for a long job, or type over the hours to use your own.")
    assert c["hint"] == "One round trip for each guy."
    assert c["how"] == ("Travel Labor: 0 guys x 6.5 drive hours (one 380 mile round trip at 60 mph from the Olathe office) x $33.00 = $0.00. Type the guys.")


def test_the_hint_under_the_guys_box_for_every_kind_of_box(ran):
    """The crew's size says so; a bid saved before 2026-10-12 still on auto says the figure IS the man-days (unchanged); a Travel Labor box that is
    empty or typed says what its guys are; another hours line, and no row, are worded as the man-days hint words them.

    Mutation: put the man-days hint back under a typed Travel Labor box."""
    h = ran["hints"]
    assert h["crew"] == "Most guys on one labor line above: 4."
    assert h["legacyAuto"] == "Man-days from the tasks above."
    assert h["emptyNewBid"] == "One round trip for each guy."
    assert h["otherHoursLine"] == "Man-days from the tasks above: 48." and h["noRow"] == "Man-days from the tasks above: 48."


def test_the_words_on_a_row_left_on_a_base_that_does_not_carry_the_travel(ran):
    """The job's drive is charged once, on the carrier, so the card of a leftover Travel Labor row says so, by the name of the carrier: an empty row
    (taken back) says leave it empty; one with figures somebody typed (hours alone is enough) says it was left as typed, still adds to this section's
    labor, and how to clear it.

    Mutation: say the same thing whatever the row holds."""
    s = ran["strayWords"]
    assert s["empty"] == "The job's drive is charged once, on the Polish section. Leave this line empty: anything typed here is charged a second time."
    assert s["typed"] == s["hoursOnly"].replace("Polish", "Copy1") == (
        "The job's drive is charged once, on the Copy1 section. This line holds figures that were typed, so it was left as typed and still adds "
        "to this section's labor. Clear it, or remove the line, if the drive is already charged there.")
    assert s["noRow"] == s["empty"]
    # THE THIRD AUDIT: figures nobody typed are never called typed. A bid saved before the take-back can still hold the drive the distance filled on a section
    # that does not carry the travel (a card that said "figures that were typed" over the tool's own $858), and a row switched off adds nothing.
    assert s["filled"] == s["filledOld"] == (
        "The job's drive is charged once, on the Polish section. This line still holds the drive the distance filled, so it adds to this section's labor "
        "as well. Clear it, or remove the line.")
    assert "typed" not in s["filled"]
    assert s["off"] == ("The job's drive is charged once, on the Polish section. This line holds figures but is switched off, so it adds nothing to "
                        "this section's labor.")
    assert s["offEmpty"] == s["empty"]
    for words in s.values():
        assert "crew" not in words.lower() and "labour" not in words.lower(), "the estimate page's column is Guys, never Crew"


# ── the other two lines, bad input, words ────────────────────────────────────────────────────────
def test_lodging_and_per_diem_come_on_by_the_answer_a_hand_flip_never_moves_and_their_quantities_follow_the_labor(ran):
    """Switched on by the answer, and a hand flip never moved (Lodging flipped off by hand stays off, whatever the miles). Their QUANTITIES are a different box: until
    2026-10-20 they opened empty and were typed, and a far answer left them so; now a far answer fills a quantity nobody typed with the sheet's count of the labor (4 guys x 12
    days: 48 nights and 48 days of per diem), on auto and marked as following (`qty_follow`). A LINE THE ESTIMATOR SWITCHED OFF IS LEFT ALONE (round 6, part 2: it used to be filled
    while it was off, "hand flip or none: the quantity does not depend on the switch", which a hand flip does not say and Travel Labor does not do): Lodging stays empty and off auto, and the
    page fills it the moment the estimator switches it ON (test_polish_travel_round6_answer.py).

    Mutation: leave the Per Diem quantity empty; fill a line that is switched off (test_polish_travel_round6_answer.py)."""
    ln = ran["lines"]
    assert ln["lodging"] is False and ln["perDiem"] is True and ln["lodgingHand"] is True
    assert ln["manDays"] == 48 and ln["perDiemQty"] == 48 and ln["perDiemAuto"] is True and ln["perDiemFollow"] == "labor"
    assert ln["lodgingQty"] == "" and ln["lodgingAuto"] is False and ln["lodgingFollow"] is None, "an answer filled a line that is switched off"


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


# ── the fourth audit (2026-10-20, of c0255de): an option follows the answers, the settling's order, a typed rate, every clause of a repeat, a malformed bid ──
def filled(hours, guys, rate=33):
    """A Travel Labor row the distance filled: the tool's hours, the guys on the crew (marked), nobody's box typed in."""
    return {"hours": hours, "seed": hours, "auto": True, "follow": "crew", "guys": guys, "cost": guys * hours * rate, "on": True}


def core(row):
    """The facts every reading of a row shares (an option's carries its markers and its keys besides)."""
    return {k: row[k] for k in ("hours", "seed", "auto", "follow", "guys", "cost", "on")}


def test_an_options_travel_labor_follows_every_distance_answer_on_its_own_crew(ran):
    """THE FOURTH AUDIT'S MEDIUM FINDING. A far Polish bid (the job's crew is 4, the copy's own Polishing 6) copied as an option holds a Travel Labor row of its own, and only the
    carrier's followed an answer: corrected to 50 miles the base dropped its drive ($30,872 on the page) and the option went on pricing its 6.5 hours ($32,632), and at 300 miles the
    base went to 10 hours while the option stayed at 6.5. Now every answer reaches the option's row by the carrier's rule, on the option's OWN lines' crew: 300 miles is 10 hours for
    the base's 4 and the option's 6; 50 miles takes the option's drive back WHOLE (empty, no marker; the carrier's row loses only its hours and keeps its crew marker); 190 again fills
    it again (an empty row is filled by a far answer, so a number typed digit by digit, 3, 30, 300, ends where typing 300 does); clearing the miles takes it back; and the answer
    alone, with no sync after it, puts the option's guys on its own lines.

    Mutation: leave the options out of an answer; out of clearing the miles; keep an option's markers when the job goes local; put its guys on the base crew; fill only what was filled."""
    f = ran["optionsFollow"]
    assert "error" not in f, f.get("error")
    assert f["crewOfJob"] == 4 and f["ownCrew"] == 6
    assert [k for k, _ in f["start"]["kinds"]] == ["Polish", "Copy1"] and f["start"]["kinds"][1][1] == "option"
    for step, hours in (("start", 6.5), ("farther", 10), ("farAgain", 6.5), ("digitsFar", 10)):
        assert f[step]["base"] == filled(hours, 4), step
        assert core(f[step]["option"]) == filled(hours, 6), step + ": the option's own crew, not the base's"
    for step in ("local", "cleared", "digitsLocal"):
        assert f[step]["base"] == {"hours": "", "seed": "", "auto": True, "follow": "crew", "guys": 4, "cost": 0, "on": True}, step + ": the carrier keeps its crew marker"
        assert f[step]["option"] == dict(EMPTIED, typed=False, hoursTyped=False, keys=EMPTIED_KEYS), step + ": the option's drive is taken back whole"
    assert f["cleared"]["distance"] is None
    assert core(f["bare"]) == filled(10, 6), "the answer alone fills the option's guys on its own lines"


def test_what_the_estimator_typed_cleared_or_switched_off_on_an_option_is_left_alone_by_every_answer(ran):
    """The copy carries the row the carrier had, so each estimator's variant reaches the option as it was: typed 3 x 5 (both boxes marked), the hours box cleared, the guys box cleared, the
    row switched off. Through 300 miles, 50, 190 and the miles cleared, the box they typed or cleared stays as it was and the row they switched off stays exactly as it was (figures,
    markers, off), while a box nobody typed in still follows the answer (the cleared Guys box's hours: 6.5, 10, empty, 6.5, empty) and the guys of a row on the crew keep following
    the option's own lines.

    Mutation: fill a switched-off option row; overwrite what was typed; refill a cleared box."""
    o = ran["optionsOwned"]
    assert "error" not in o, o.get("error")
    steps = ("start", "far300", "local50", "far190", "cleared")
    for step in steps:
        t = o["typed"][step]
        assert (t["guys"], t["hours"], t["typed"], t["hoursTyped"], t["cost"], t["on"]) == ("3", "5", True, True, 495, True), step
        c = o["clearedHours"][step]
        assert (c["hours"], c["hoursTyped"], c["guys"], c["follow"], c["cost"]) == ("", True, 4, "crew", 0), step
        g = o["clearedGuys"][step]
        assert (g["guys"], g["typed"], g["cost"]) == ("", True, 0), step
        off = o["off"][step]
        assert (off["on"], off["guys"], off["hours"], off["seed"], off["follow"], off["cost"]) == (False, 4, 6.5, 6.5, "crew", 0), step
        assert "enabled" in off["keys"]
    assert [o["clearedGuys"][s]["hours"] for s in steps] == [6.5, 10, "", 6.5, ""], "the box nobody typed in follows the answer, the cleared one does not"


def test_a_sheet_the_sheets_panel_demoted_keeps_following_the_answers_as_an_option(ran):
    """THE AUDIT'S SECOND ROUTE. A Combo (Polish 4 guys, Epoxy 5), Epoxy made the base (Polish becomes an option; the new carrier takes the job's Travel Labor row and, since the
    fifth audit, the demoted Polish KEEPS its own, on its own crew of 4: a copy went and nothing moved), the bid reopened (nothing to add: migrateModel finds the row it
    holds), Polish made the base again: Epoxy is an option holding the drive it was filled with (5 x 6.5 x $33) and Polish carries 4 x 6.5.
    The miles corrected to 50 emptied Polish's hours and left the option's 6.5 hours priced; now the option's drive goes (empty, no marker), and at 300 miles it is 5 x 10 x $33 =
    $1,650 beside the base's $1,320.

    Mutation: leave the options out of an answer."""
    d = ran["optionsDemoted"]
    assert "error" not in d, d.get("error")
    assert d["epoxyBase"]["carrier"] == "Epoxy" and d["epoxyBase"]["epoxy"] == filled(6.5, 5), "the new carrier took the job's drive"
    assert d["epoxyBase"]["polish"] == filled(6.5, 4), "the demoted Polish keeps a Travel Labor row of its own, filled, on its own crew (a copy went to the carrier)"
    p = d["polishBase"]
    assert (p["carrier"], p["kinds"]) == ("Polish", [["Polish", "base"], ["Epoxy", "option"]])
    assert p["polish"] == filled(6.5, 4) and p["epoxy"] == filled(6.5, 5)
    assert d["local"]["epoxy"] == EMPTIED and d["local"]["polish"]["hours"] == ""
    assert d["farther"]["polish"] == filled(10, 4) and d["farther"]["epoxy"] == filled(10, 5)


def test_an_options_empty_row_is_filled_by_a_far_answer_and_a_gyp_option_is_too(ran):
    """An option's row that nobody has filled or typed in (the copy was made on a local job) is a row like the carrier's empty one, and a far answer fills it: 4 x 6.5 x $33 beside the
    base's. A Gyp option follows the answers like any other since round 7 (Hanz, 2026-10-21, D2: a Gyp base's drive fills, so a demoted Gyp base must follow the miles too): far, its
    own crew of 4 x 6.5 x $33; under 70 miles the fill goes back whole. (It was left alone, as a Gyp carrier was.)

    Mutation: fill only a row the distance has filled before; leave a Gyp option out of the answers (BREAKS below)."""
    b = ran["optionBlankFilled"]
    assert "error" not in b, b.get("error")
    assert b["before"]["hours"] == "" and b["before"]["keys"] == EMPTIED_KEYS
    assert b["base"] == filled(6.5, 4) and core(b["option"]) == filled(6.5, 4)
    g = ran["optionGyp"]
    assert "error" not in g, g.get("error")
    assert g["untouchedFar"] is False and g["far"] == filled(6.5, 4) and g["local"] == EMPTIED and g["base"]["hours"] == ""


def test_the_repeat_a_carried_drive_leaves_behind_is_given_back_switched_on_and_no_other(ran):
    """THE FOURTH AUDIT'S LOW FINDING, under round 7's law. The job's one drive is CARRIED when a single-base job's base moves, and it goes as a COPY when the old base keeps no other row:
    a Polish job whose root holds only its Travel Labor, switched OFF, switched to Epoxy. The new base holds the switched-off row (its guys put on the Epoxy crew, 0 until typed), and
    the root, off now, holds a repeat of it, which is given back AT THE CARRY, while it still reads as one: empty, no marker, switched ON again (releaseTravelRow). The sync that follows
    puts the copy's guys on the new crew and never touches a section that is off, so a repeat looked for after it is not one any more (the round-7 walk found the repeat of a switched-off
    row left on the root; the audit's case was the reverse, a repeat on a base compared before the sync). A switched-off row on a sheet the drive was NOT carried from is that sheet's
    own and stays (round 7's walk found a root's typed row given back because a copy of the root made the base held the same figures).

    Mutation: leave the carry's repeat; give a repeat back from a sheet the drive was not carried from; leave a given-back row switched off (BREAKS below)."""
    d = ran["duplicateOff"]
    assert "error" not in d, d.get("error")
    assert d["epoxy"]["on"] is False and (d["epoxy"]["guys"], d["epoxy"]["hours"], d["epoxy"]["follow"]) == (0, 6.5, "crew") and d["epoxyMarks"]["off"] is True
    assert d["root"] == EMPTIED and d["rootMarks"]["keys"] == EMPTIED_KEYS and d["rootRows"] == 1, "given back, switched on, empty, markers gone"
    assert d["drive"] == 0
    n = d["notCarried"]
    assert n["epoxy"]["on"] is False and n["epoxyMarks"]["off"] is True and n["epoxy"]["guys"] == 4, "a sheet the drive was not carried from keeps its own"


def test_a_copy_is_given_back_only_when_it_repeats_the_carriers_row_in_every_respect(ran):
    """THE FOURTH AUDIT'S TEST GAP. The carrier's Travel Labor is typed 3 x 5 (both boxes marked), its sheet is copied and the copy put OFF (round 7: the repeat is looked for on a
    section that is off, what a carried drive leaves behind; a base keeps its own drive). A copy that says exactly what the carrier's row says is the leftover and is given back (emptied,
    switched on). A copy that says something else is the estimator's own choice and stays, and it is told from the carrier's by ANY one thing: its guys (2), its hours (4), the Guys box
    being on auto, the row being switched off, its guys or its hours not carrying the typed marker. Each of those is checked alone, so a clause that goes missing from the comparison
    gives a copy back that the estimator wrote. (A section that is off is not in the bid, so the job's Travel Labor is the carrier's $495 whatever the copy holds.) A switched-off
    carrier row and a copy switched off too are the same row, and it is switched on again when given back.

    Mutation: leave the guys, the hours, the auto flag, the switch, or either typed marker out of the comparison; leave a given-back row switched off."""
    r = ran["repeatVariants"]
    assert "error" not in r, r.get("error")
    s = r["same"]
    assert s["copy"] == EMPTIED and s["copyMarks"]["keys"] == EMPTIED_KEYS and s["root"] == TYPED_ROOT and s["drive"] == 495
    kept = {                    # what the copy's row still holds: (guys, hours, cost, on), and what the job's Travel Labor adds up to (the carrier's $495: the copy is off)
        "guysOnly": (("2", "5", 330, True), 495),
        "hoursOnly": (("3", "4", 396, True), 495),
        "autoOnly": (("3", "5", 495, True), 495),
        "offOnly": (("3", "5", 0, False), 495),
        "guysMarkerOnly": (("3", "5", 495, True), 495),
        "hoursMarkerOnly": (("3", "5", 495, True), 495),
    }
    for name, (figures, drive) in kept.items():
        c = r[name]["copy"]
        assert c != EMPTIED, name + ": a row that differs is the estimator's and stays"
        assert (c["guys"], c["hours"], c["cost"], c["on"]) == figures, name
        assert r[name]["root"] == TYPED_ROOT and r[name]["drive"] == drive, name
    assert r["autoOnly"]["copy"]["auto"] is True and r["offOnly"]["copyMarks"]["off"] is True
    assert r["guysMarkerOnly"]["copyMarks"]["typed"] is False and r["hoursMarkerOnly"]["copyMarks"]["hoursTyped"] is False
    b = r["bothOff"]
    assert b["copy"] == EMPTIED and b["copyMarks"]["keys"] == EMPTIED_KEYS, "the copy of a switched-off row is given back and is switched on again"
    assert b["root"]["on"] is False and b["rootMarks"]["off"] is True and (b["root"]["guys"], b["root"]["hours"]) == ("3", "5")


def test_a_typed_rate_follows_the_jobs_drive_like_typed_guys_and_hours(ran):
    """THE FOURTH AUDIT'S LOW FINDING. $40 typed on Polish's Travel Labor (the guys and hours still on the distance), the job switched to Epoxy: the row read $33. The old carrier's row was
    not the estimator's, so it was taken back and the new carrier was filled at its own rate. A rate over the default the row was filled with, or one marked typed (setLaborRate marks the
    case a number cannot tell: a typed $33 over a default of $33), makes the row the estimator's: it goes to the new carrier with the job's drive (the rows change places, markers and rate
    and all), whose boxes are then filled by the rule (4 x 6.5 x $40 = $1,040, 4 x 10 x $40 at 300 miles), and it follows the carrier back. The old carrier is left holding the new
    carrier's former row, at its own rate. A row with no default to compare to (the older row the Polish root of an Epoxy or Gyp job holds, a bid saved before the stamp) is told by the
    way the box holds the figure, as the Hours box is: a rate typed over it is text and is the estimator's, a number says nothing. Both rows typed on an Epoxy job switched to Combo: both stay,
    and since round 7 each base drives its own crew at its own rate (D1: $45 on Polish, $40 on Epoxy; until then one drive, the carrier's, and Epoxy's was given back).

    Mutation: make a typed rate not the estimator's; lose the marker; take a number over an unknown default for a typed one, or a text rate over it for a number."""
    t = ran["typedRate"]
    assert "error" not in t, t.get("error")
    a = t["typed40"]
    assert a["toEpoxy"]["carrier"] == "Epoxy" and a["toEpoxy"]["drive"] == 1040
    assert a["toEpoxy"]["epoxy"] == {"rate": "40", "marked": False, "hours": 6.5, "guys": 4, "follow": "crew", "cost": 4 * 6.5 * 40}
    assert a["toEpoxy"]["root"] == {"rate": 33, "marked": False, "hours": "", "guys": "", "follow": None, "cost": 0}, "the old carrier holds the new carrier's former row"
    assert a["later300"]["epoxy"] == {"rate": "40", "marked": False, "hours": 10, "guys": 4, "follow": "crew", "cost": 4 * 10 * 40}, "a later answer moves the hours, never the rate"
    assert a["backToPolish"]["carrier"] == "Polish" and a["backToPolish"]["drive"] == 1600
    assert a["backToPolish"]["root"]["rate"] == "40" and a["backToPolish"]["root"]["cost"] == 1600 and a["backToPolish"]["epoxy"]["rate"] == 33
    m = t["markedAtDefault"]
    assert m["toEpoxy"]["epoxy"]["marked"] is True and m["toEpoxy"]["epoxy"]["rate"] == "33" and m["toEpoxy"]["root"]["marked"] is False and m["toEpoxy"]["drive"] == 858
    assert m["backToPolish"]["root"]["marked"] is True and m["backToPolish"]["epoxy"]["marked"] is False
    u = t["untouched"]
    assert u["toEpoxy"]["epoxy"]["rate"] == 33 and u["toEpoxy"]["drive"] == 858 and u["backToPolish"]["drive"] == 1320, "no typed rate: as before"
    x = t["unstampedText"]      # a row never stamped with a default (the Polish root of an Epoxy or Gyp job, a bid saved before the stamp): the rate typed over it is text
    assert x["toEpoxy"]["epoxy"]["rate"] == "40" and x["toEpoxy"]["epoxy"]["cost"] == 1040 and x["toEpoxy"]["root"]["rate"] == 33 and x["backToPolish"]["root"]["cost"] == 1600
    n = t["unstampedNumber"]    # ...and a NUMBER over a default nobody knows says nothing: the rate stays on the row the old carrier is given back
    assert n["toEpoxy"]["epoxy"]["rate"] == 33 and n["toEpoxy"]["epoxy"]["cost"] == 858 and n["toEpoxy"]["root"]["rate"] == 40
    b = t["bothTyped"]
    assert b["root"] == {"rate": "45", "marked": False, "hours": 6.5, "guys": 4, "follow": "crew", "cost": 4 * 6.5 * 45}
    assert b["epoxy"] == {"rate": "40", "marked": False, "hours": 6.5, "guys": 4, "follow": "crew", "cost": 4 * 6.5 * 40} and b["drive"] == 4 * 6.5 * 45 + 4 * 6.5 * 40
    r = ran["rateRows"]
    assert r == {"typedOverDefault": True, "typedText": True, "atDefault": False, "markedAtDefault": True, "blank": False, "zero": True, "noDefaultAtShipped": False,
                 "noDefaultOther": False, "noDefaultText": True, "noRow": False, "estimatorsFilled": True, "autoFilledStill": True, "estimatorsAtDefault": False}


def test_a_section_whose_labor_is_not_a_list_never_makes_the_answers_or_the_settling_throw(ran):
    """THE FOURTH AUDIT'S ROBUSTNESS FINDING. A saved bid is whatever was saved: migrateModel carries `tabs` through as they came, so a section can hold a string, a number, an object or a
    boolean where its labor lines should be. syncAutoGuys walked them with `.forEach` and threw, and the page runs it as it opens (a blank estimate: test_polish_travel_switch.py opens
    such a bid). The settling, the sync and every answer pass over the section, whether it is a base or an option, and everything that can be read is settled all the same (the carrier's
    drive 4 x 10 x $33 at 300 miles).

    Mutation: walk the lines of a section whatever they are (the sync, and the helper the options use)."""
    c = ran["corruptLabor"]
    assert "error" not in c, c.get("error")
    assert sorted(c) == ["boolean", "number", "object", "string"]
    for kind, v in c.items():
        assert v["calls"] == {"sync": None, "settle": None, "settleMoved": None, "answer": None, "cleared": None}, kind
        assert v["optionCalls"] == {"sync": None, "answer": None, "cleared": None}, kind
        assert v["settledRoot"] == filled(10, 4) and v["optionBase"] == filled(10, 4), kind


# ── red without the code: break a COPY of the model one line at a time ───────────────────────────
# (Round 7, Hanz 2026-10-21: every base crew drives its own (D1), a Gyp base fills (D2), and the job's one drive is carried only on a single-base job. The entries for the
# Gyp carrier's guard and a Gyp carrier keeping its fill are gone with them; the release of the row a swap leaves on the old base, and the settling's order of the sync and the
# take-back, are redundant now (the take-back reads only sections that are off, which hold no fill nobody touched by then, and the sync does not touch them), so a break of either
# changes nothing a scenario can see and they are not listed.)
FILLS = "var fills = !row.hours_typed && (isBlank(row.days) || wrote);"
FILL = "if (fills) { row.days = hours; row.hours_seed = hours; }"
GUYS_ON = 'if (!row.guys_typed && !row.guys_auto && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }'
LEGACY_ON = 'if (!row.guys_typed && row.guys_auto && !row.guys_follow && fills) row.guys_follow = "crew";'
GUYS_SET = "if (followsCrew(row)) row.guys = ownCrewSize(model, rows);"
SYNC = 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? ownCrewSize(model, lines) : manDays;'
CARRY_CALL = 'var carriedFrom = carriesOneDrive(model, was, drives, arrived) ? carryTravelRow(model, was.drives[0], was.kindOf(drives[0])) : "";'
TAKE_BACK_CALL = "    takeBackStrayTravel(model, carriedFrom);"
LOOKED_FOR = '    if (!from) { try { from = strandedTravelTab(model, travelCarrier(model)); } catch (err) { from = ""; } }'
CARRY_FROM = 'var from = typeof fromTab === "string" && fromTab !== "" ? fromTab : strandedTravelTab(model, to);'
STRANDED_SKIP = 'if (e.tab === carrier || drives.indexOf(e.tab) >= 0 || e.kind === "option" || !isObject(e.section)) continue;'
CARRY_NO_DRIVE = '      if (model.no_travel_labor === true || sheetSaidNoDrive(toSection)) return "";'
BASES_BEFORE = "      return { drives: list.map(function (k) { return k.tab; }), kindOf: function (tab) { return kinds.get(tab); } };"

STRAY_GUARD = 'if (e.kind === "option" || !isObject(e.section) || drives.indexOf(e.tab) >= 0) return;'
STRAY_ROW = "if (rowOn(r) && travelRowIsAutoFilled(r)) clearQuantities(r);"
TYPED_GUYS = "if (travelGuysAreTyped(row)) return false;"
TYPED_HOURS = "return isBlank(row.days) || driveHoursAreTools(row);"
TYPED_MARKS = "if (!row || row.guys_typed === true || row.hours_typed === true) return false;"
NOTHING_WRITTEN = "return travelRowIsHandsOff(row) && (driveHoursAreTools(row) || followsCrew(row));"
ELSE_OWNED = 'return followOwnedRow(model, from, to) ? from : "";'
OWNED_BOTH = "if (!travelRowIsTheEstimators(row) || theirs.some(travelRowIsTheEstimators)) return false;"
SWAP = "from.labor[from.labor.indexOf(row)] = leaves;"
SYNC_CALL = "syncAutoGuys(model);"
CATCH_CARRY = '} catch (err) { return ""; /* nothing to carry */ }'
OWN_CREW = "return mostGuysOn(rows, isObject(model) && isObject(model.conditions) ? model.conditions : {}, 0);"
STRAY_FILLED = "if (travelRowIsAutoFilled(row)) {"
STRAY_OFF = 'if (!rowOn(row)) return where + " This line holds figures but is switched off'
ESTIMATORS = "return !!row && (!rowOn(row) || !travelRowIsHandsOff(row) || travelRateIsTyped(row));"
TYPED_RATE = 'return row.rate_typed === true || (own !== null ? num(row.rate) !== own : typeof row.rate === "string");'
REPEAT_GIVEN_BACK = "else if (repeatsOn(e.tab) && travelRowRepeats(r, carrierRow)) releaseTravelRow(r);"
REPEATS_ON = 'var repeatsOn = function (tab) { return typeof carriedFrom !== "string" || carriedFrom === tab; };'
COPY_RELEASED = "        if (!demoted) travelRowsIn(fromSection).forEach(releaseTravelRow);"
CLEARED = "delete row.hours_seed; delete row.guys_follow; delete row.guys_typed; delete row.hours_typed;"
COPY_NOT_SHARED = "to.labor = (to.labor instanceof Array ? to.labor : []).concat(rest.length ? mine : mine.map(jsonCopy));"
NOTE_TYPED = "return head + (filledIn(row.guys)"
HINT_TYPED = 'if (isTravelRow(row) && !row.guys_auto) return "One round trip for each guy.";'
HOW_UNIT = 'lines.push("Travel Labor: " + qty(tr.guys) + (oldAuto ? " man-days" : " guys") +'
WHERE = 'return "the labor lines above";'
HINT_WHERE = 'return "Most guys on one labor line above" + (n > 0 ? ": " + plainNum(n) : "") + ".";'
STRAY_TYPED = "if (row && (filledIn(row.guys) || filledIn(row.days))) {"
SHIFT_CASE = "if (!mine.length || theirs.length) return false;"
TAKE_BACK = 'if (wrote) { row.days = ""; row.hours_seed = ""; }'
EVERY_BASE = "    driveEntries(model).forEach(function (e) { fillOwnDrive(model, e, miles); });"
OWN_LINES = "    var lines = laborLinesOf(e.section);"
FILL_ARRIVALS = "    if (miles !== null) fillArrivals(model, arrived, miles);"
OPTIONS_SKIP = 'if (e.kind !== "option" || drives.indexOf(e.tab) >= 0 || !isObject(e.section)) return;'
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
        FILLS, "var fills = true;", lambda g: g["typedHoursSurvive"]["hours"] != "4"),
    "a cleared hours box is refilled by the next answer": (
        FILLS, "var fills = isBlank(row.days) || wrote;",
        lambda g: g["clearedHours"]["hours"] != ""),
    "the marker is not written, so the next answer cannot move the tool's figure": (
        FILL, "if (fills) { row.days = hours; }",
        lambda g: g["untouchedMoves"]["hours"] != 10),
    "the tool's figure is told from a typed one by its digits alone": (
        TOOLS, "!isBlank(row.hours_seed) && num(row.days) === num(row.hours_seed)",
        lambda g: g["typedSameDigitsNoMarker"]["hours"] != "6.5"),
    "the guys are never put on the crew": (
        GUYS_ON, "void 0;", lambda g: g["wichita"]["cost"] != 858),
    "typed guys are put on the crew": (
        GUYS_ON, 'if (!row.guys_auto) { row.guys_auto = true; row.guys_follow = "crew"; }',
        lambda g: g["typedGuysSurvive"]["guys"] != "2"),
    "the older auto row the answer fills is left on the man-days": (
        LEGACY_ON, "void 0;",
        lambda g: g["savedAutoBlankHours"]["guys"] != 4 or g["shippedRow"]["guys"] != 4 or g["savedMarkerFollows"]["guys"] != 4),
    "the older auto row is put on the crew whether or not the answer filled it": (
        LEGACY_ON, 'if (!row.guys_typed && row.guys_auto && !row.guys_follow) row.guys_follow = "crew";',
        lambda g: g["savedTypedHoursStay"]["guys"] != 48 or g["savedTypedHoursStay"]["follow"] is not None),
    "a cleared guys box is refilled by the next answer": (
        GUYS_ON, 'if (!row.guys_auto && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }',
        lambda g: g["clearedGuys"]["guys"] != ""),
    "the answer leaves the guys to the page's sync": (
        GUYS_SET, "if (followsCrew(row)) void 0;", lambda g: g["wichitaBare"]["guys"] != 4),
    "the guys are the man-days and not the crew's size": (
        GUYS_SET, "if (followsCrew(row)) row.guys = travelManDays(rows);", lambda g: g["wichitaBare"]["guys"] != 4),
    "a drive's guys follow the bases' biggest crew when an answer fills them": (
        GUYS_SET, "if (followsCrew(row)) row.guys = crewSize(model);",
        lambda g: g["optionsFollow"]["bare"]["guys"] != 6 or g["comboJob"]["guys"] != 3),
    "the page's sync puts the guys on the man-days": (
        SYNC, 'if (r && r.unit === "hours" && r.guys_auto) r.guys = manDays;', lambda g: g["crewAfter"]["guys"] != 4),
    "the sync leaves a reopened crew row to follow nothing": (
        SYNC, 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? r.guys : manDays;',
        lambda g: g["savedCrewRow"]["afterCrewChange"]["guys"] != 6),
    "a crew-following row follows the bases' biggest crew and not its own lines": (
        SYNC, 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? crewSize(model) : manDays;',
        lambda g: g["optionCrew"]["copy"]["guys"] != 6 or g["optionCrew"]["copy"]["cost"] != 6 * 6.5 * 33 or g["comboJob"]["guys"] != 3),
    "the bases' crew is read from the carrier's lines only": (
        CREW_LINES, "live.slice(0, 1).forEach(function (e) { lists.push(e.section.labor); });",
        lambda g: g["comboJob"]["crew"] != 4),
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
    # --- round 7 (Hanz, 2026-10-21): every base crew drives its own (D1), a Gyp base included (D2) ---
    "a Gyp base is left out of the fill": (
        EVERY_BASE, '    driveEntries(model).forEach(function (e) { if (e.layout !== "gyp") fillOwnDrive(model, e, miles); });',
        lambda g: g["gypJob"]["row"]["hours"] != 6.5),
    "only the carrier's drive is filled": (
        EVERY_BASE, "    driveEntries(model).slice(0, 1).forEach(function (e) { fillOwnDrive(model, e, miles); });",
        lambda g: g["comboJob"]["epoxy"]["hours"] != 6.5),
    "the fill lands on the model's own rows, not the section's": (
        OWN_LINES, "    var lines = laborLinesOf(model);",
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
    "the distance on file is not put on a base that arrived": (
        FILL_ARRIVALS, "    void miles;",
        lambda g: g["followDistance"]["after"]["hours"] != 6.5 or g["moveEpoxyToCombo"]["root"]["hours"] != 6.5),
    "a base that stayed a base is filled as if it had arrived": (
        BASES_BEFORE, "      return { drives: [], kindOf: function (tab) { return kinds.get(tab); } };",
        lambda g: g["carrierKeptFillsNothing"] != EMPTIED),
    # --- the single-base carry: the job's one drive follows its one base ---
    "the row does not go with a single-base job's base": (
        CARRY_CALL, 'var carriedFrom = "";',
        lambda g: g["copyReleased"]["epoxy"] != TYPED_ROOT or g["followsSeeded"]["typed"]["epoxy"] != TYPED_ROOT),
    "an off section keeps the drive the distance filled on it": (
        TAKE_BACK_CALL, "    void carriedFrom;",
        lambda g: g["settleSequence"]["toPolish"]["epoxy"] != EMPTIED or g["moveComboToEpoxy"]["root"] != EMPTIED),
    "a stranded row is not looked for when the old carrier is not named": (
        LOOKED_FOR, "    void from;",
        lambda g: g["namedBeatsLooked"]["looked"]["gyp"] is None),
    "an option's row is carried to a new base": (
        STRANDED_SKIP, 'if (e.tab === carrier || drives.indexOf(e.tab) >= 0 || !isObject(e.section)) continue;',
        lambda g: g["moveOptionNotCarried"]["epoxyHasRow"] is not False),
    "a job that said it has no drive has its old base's row carried to the new one": (
        CARRY_NO_DRIVE, '      if (sheetSaidNoDrive(toSection)) return "";',
        lambda g: g["moveNoTravelLaborNamed"]["epoxyHasRow"] is not False),
    "an option gives its row back": (
        STRAY_GUARD, 'if (!isObject(e.section) || drives.indexOf(e.tab) >= 0) return;',
        lambda g: g["moveOptionStays"]["same"] is not True or g["takeBackOff"]["option"] is not True),
    "a base gives its own drive back": (
        STRAY_GUARD, 'if (e.kind === "option" || !isObject(e.section)) return;',
        lambda g: g["moveEpoxyToCombo"]["epoxy"]["cost"] != 858 or g["moveEpoxyToCombo"]["drive"] != 1716),
    "an off section keeps the row the distance filled": (
        STRAY_GUARD, 'if (e.kind !== "base" || !isObject(e.section) || drives.indexOf(e.tab) >= 0) return;',
        lambda g: g["takeBackOff"]["off"] != EMPTIED or g["settleSequence"]["toPolish"]["epoxy"] != EMPTIED),
    "a switched-off row is taken back": (
        STRAY_ROW, "if (travelRowIsAutoFilled(r)) clearQuantities(r);",
        lambda g: g["duplicateOff"]["notCarried"]["epoxy"]["guys"] != 4),
    "a row taken back keeps its markers": (
        CLEARED, "delete row.hours_seed; delete row.guys_typed; delete row.hours_typed;",
        lambda g: g["settleSequence"]["toPolish"]["epoxy"]["follow"] is not None or "guys_follow" in g["settleSequence"]["toPolish"]["epoxyKeys"]),
    "a row taken back keeps the hours the tool wrote": (
        CLEARED, "delete row.guys_follow; delete row.guys_typed; delete row.hours_typed;",
        lambda g: g["settleSequence"]["toPolish"]["epoxy"]["seed"] is not None),
    "typed guys are taken back": (
        TYPED_GUYS, "void 0;", lambda g: g["autoFilled"]["typedGuysNoMarker"] is not False or g["autoFilled"]["estimators"]["typedGuysNoMarker"] is not True),
    "typed hours are taken back": (
        TYPED_HOURS, "return true;",
        lambda g: g["autoFilled"]["typedHoursNoMarker"] is not False or g["autoFilled"]["estimators"]["typedHoursNoMarker"] is not True),
    "a marked row is taken back": (
        TYPED_MARKS, "if (!row) return false;",
        lambda g: g["autoFilled"]["clearedHoursMarked"] is not False or g["autoFilled"]["typedHoursMarked"] is not False),
    "a row nothing was written in counts as filled": (
        NOTHING_WRITTEN, "return travelRowIsHandsOff(row);",
        lambda g: g["autoFilled"]["empty"] is not False or g["autoFilled"]["legacyBlank"] is not False),
    "a copy of the row shares its object with the old base": (
        COPY_NOT_SHARED, "to.labor = (to.labor instanceof Array ? to.labor : []).concat(mine);",
        lambda g: g["moveCopy"]["aliased"] is not False),
    "a new base that has a row of its own is given a second one": (
        SHIFT_CASE, "if (!mine.length) return false;",
        lambda g: g["moveEpoxyToPolish"]["rootRows"] != 1),
    "what the estimator typed stays behind on a single-base job's old base": (
        ELSE_OWNED, 'return "";',
        lambda g: g["followsSeeded"]["typed"]["epoxy"] != TYPED_ROOT or g["followsSeeded"]["typed"]["drive"] != 495),
    "what the estimator cleared is refilled on a single-base job's new base": (
        ELSE_OWNED, 'return "";',
        lambda g: g["followsSeeded"]["clearedHours"]["epoxy"]["hours"] != "" or g["followsSeeded"]["clearedGuys"]["epoxy"]["guys"] != ""),
    "a row the estimator switched off stays behind on a single-base job's old base": (
        ELSE_OWNED, 'return "";',
        lambda g: g["followsSeeded"]["off"]["epoxyMarks"]["off"] is not True),
    "a repeat on an off section is not given back": (
        REPEAT_GIVEN_BACK, "else void r;",
        lambda g: g["copyRepeat"]["same"]["copy"] != EMPTIED),
    # round 7, part 3 (the round-7 audit's F1): the tool's copy made a base beside the row it repeats is given back and drives its own crew
    "a copy made a base beside the row it repeats is not given back": (
        "    var gaveBack = giveBackRepeatedCopies(model, arrived);", "    var gaveBack = [];",
        lambda g: g["copyRepeat"]["base"]["copy"] != FILLED_FOUR or g["copyRepeat"]["base"]["drive"] != 495 + 858),
    "a repeat is given back from a section the drive was not carried from": (
        REPEATS_ON, "var repeatsOn = function (tab) { return true; };",
        lambda g: g["duplicateOff"]["notCarried"]["epoxy"]["on"] is not False),
    "a copy the old base keeps of the carried row is not given back": (
        COPY_RELEASED, "        void demoted;",
        lambda g: g["copyReleased"]["root"] != EMPTIED or g["duplicateOff"]["root"] != EMPTIED),
    "the estimator's row overwrites a new base's row that is the estimator's too": (
        OWNED_BOTH, "if (!travelRowIsTheEstimators(row)) return false;",
        lambda g: g["ownedBothStay"]["root"]["guys"] != "2" or g["ownedBothStay"]["drive"] != 2 * 4 * 33),
    "the old base keeps the estimator's row when it is handed over": (
        SWAP, "void leaves;",
        lambda g: g["followsSeeded"]["typed"]["root"] != EMPTIED),
    "the caller's name for the old base is ignored": (
        CARRY_FROM, "var from = strandedTravelTab(model, to);",
        lambda g: g["namedBeatsLooked"]["named"]["gyp"] != TYPED_ROOT),
    "the settling leaves a carried row's guys on the old crew": (
        SYNC_CALL, "void model;",
        lambda g: g["localCarry"]["epoxy"]["guys"] != 0),
    "the carry throws for a section it cannot find or read": (
        CATCH_CARRY, "} catch (err) { throw err; }",
        lambda g: g["followNeverThrows"]["namelessThrew"] is not None or g["followNeverThrows"]["brokenThrew"] is not None),
    "an option's own crew leaves the job's conditions out": (
        OWN_CREW, "return mostGuysOn(rows, {}, 0);",
        lambda g: g["optionHand"]["withHand"] != 4),
    "a switched-off row is not the estimator's": (
        ESTIMATORS, "return !!row && (!travelRowIsHandsOff(row) || travelRateIsTyped(row));",
        lambda g: g["autoFilled"]["estimators"]["off"] is not True or g["followsSeeded"]["off"]["epoxyMarks"]["off"] is not True),
    # --- the fourth audit (2026-10-20, of c0255de): an option follows every answer ---
    "an answer never reaches an option's Travel Labor": (
        "followDistanceOptions(model, miles);", "void miles;",
        lambda g: g["optionsFollow"]["farther"]["option"]["hours"] != 10 or g["optionsDemoted"]["farther"]["epoxy"]["hours"] != 10),
    "clearing the miles never reaches an option's Travel Labor": (
        "followDistanceOptions(model, null);", "void model;",
        lambda g: g["optionsFollow"]["cleared"]["option"]["hours"] != "" or g["optionsFollow"]["cleared"]["option"]["keys"] != EMPTIED_KEYS),
    "an option keeps its fill markers when the job goes local": (
        "if (own && travelRowIsAutoFilled(row)) clearQuantities(row);", "if (false) clearQuantities(row);",
        lambda g: g["optionsFollow"]["local"]["option"]["keys"] != EMPTIED_KEYS or g["optionsDemoted"]["local"]["epoxy"] != EMPTIED),
    "an option's empty row is not filled by a far answer": (
        '        if (isTravelRow(r) && r.unit === "hours") followDistanceOnRow(model, r, rows, miles, true, driveTripsOf(e));',
        '        if (isTravelRow(r) && r.unit === "hours" && travelRowIsAutoFilled(r)) followDistanceOnRow(model, r, rows, miles, true, driveTripsOf(e));',
        lambda g: g["optionsFollow"]["farAgain"]["option"]["hours"] != 6.5 or g["optionBlankFilled"]["option"]["hours"] != 6.5),
    "a Gyp option is left out of the answers": (
        OPTIONS_SKIP, 'if (e.kind !== "option" || drives.indexOf(e.tab) >= 0 || e.layout === "gyp" || !isObject(e.section)) return;',
        lambda g: g["optionGyp"]["far"]["hours"] != 6.5),
    "a switched-off option row is filled": (
        OFF_GUARD, "void 0;",
        lambda g: g["optionsOwned"]["off"]["far300"]["hours"] != 6.5),
    "a typed option row is overwritten by the next answer": (
        FILLS, "var fills = true;",
        lambda g: g["optionsOwned"]["typed"]["far300"]["hours"] != "5"),
    "a cleared option guys box is refilled by the next answer": (
        GUYS_ON, 'if (!row.guys_auto && !filledIn(row.guys)) { row.guys_auto = true; row.guys_follow = "crew"; }',
        lambda g: g["optionsOwned"]["clearedGuys"]["far300"]["guys"] != ""),
    # --- what a given-back row is left as ---
    "a given-back row is left switched off": (
        "    delete row.enabled;", "    void row;",
        lambda g: g["duplicateOff"]["root"]["on"] is not True or "enabled" in g["duplicateOff"]["rootMarks"]["keys"]
        or g["repeatVariants"]["bothOff"]["copy"]["on"] is not True),
    # --- every clause of "repeats the carrier's row" ---
    "a copy that says other guys is given back": (
        'same("guys") && ', "",
        lambda g: g["repeatVariants"]["guysOnly"]["copy"]["guys"] != "2"),
    "a copy that says other hours is given back": (
        'same("days") && ', "",
        lambda g: g["repeatVariants"]["hoursOnly"]["copy"]["hours"] != "4"),
    "a copy on auto when the carrier's is not is given back": (
        '!!row.guys_auto === !!carrierRow.guys_auto && ', "",
        lambda g: g["repeatVariants"]["autoOnly"]["copy"]["auto"] is not True),
    "a copy switched off when the carrier's is on is given back": (
        "(row.enabled === false) === (carrierRow.enabled === false) &&", "true &&",
        lambda g: g["repeatVariants"]["offOnly"]["copy"]["on"] is not False),
    "a copy whose guys were not typed by hand when the carrier's were is given back": (
        "(row.guys_typed === true) === (carrierRow.guys_typed === true) && ", "",
        lambda g: g["repeatVariants"]["guysMarkerOnly"]["copy"]["guys"] != "3"),
    "a copy whose hours were not typed by hand when the carrier's were is given back": (
        "(row.hours_typed === true) === (carrierRow.hours_typed === true);", "true;",
        lambda g: g["repeatVariants"]["hoursMarkerOnly"]["copy"]["hours"] != "5"),
    # --- a typed rate follows the job's drive ---
    "a rate the estimator typed does not make the row theirs": (
        ESTIMATORS, "return !!row && (!rowOn(row) || !travelRowIsHandsOff(row));",
        lambda g: g["typedRate"]["typed40"]["toEpoxy"]["epoxy"]["rate"] != "40" or g["rateRows"]["estimatorsFilled"] is not True),
    "a rate typed to the line's own default is told from one that follows it": (
        TYPED_RATE, 'return (own !== null ? num(row.rate) !== own : typeof row.rate === "string");',
        lambda g: g["rateRows"]["markedAtDefault"] is not True or g["typedRate"]["markedAtDefault"]["toEpoxy"]["epoxy"]["marked"] is not True),
    "a number over a default nobody knows is taken for typed": (
        TYPED_RATE, "return row.rate_typed === true || num(row.rate) !== own;",
        lambda g: g["rateRows"]["noDefaultAtShipped"] is not False or g["rateRows"]["noDefaultOther"] is not False
        or g["typedRate"]["unstampedNumber"]["toEpoxy"]["epoxy"]["rate"] != 33),
    "a text rate over a default nobody knows is not taken for typed": (
        TYPED_RATE, "return row.rate_typed === true || (own !== null ? num(row.rate) !== own : false);",
        lambda g: g["rateRows"]["noDefaultText"] is not True or g["typedRate"]["unstampedText"]["toEpoxy"]["epoxy"]["rate"] != "40"),
    "a rate at the line's own default is taken for typed": (
        TYPED_RATE, "return row.rate_typed === true || own !== null;",
        lambda g: g["rateRows"]["atDefault"] is not False or g["typedRate"]["untouched"]["toEpoxy"]["epoxy"]["rate"] != 33),
    # --- a saved bid is whatever was saved ---
    "the sync walks a labor that is not a list": (
        "var lines = laborLinesOf(s.section);", "var lines = s.section.labor || [];",
        lambda g: "error" in g["corruptLabor"] or any(v["calls"]["sync"] is not None for v in g["corruptLabor"].values())),
    "the options walk a labor that is not a list": (
        "return isObject(section) && Array.isArray(section.labor) ? section.labor : [];", "return isObject(section) && section.labor ? section.labor : [];",
        lambda g: "error" in g["corruptLabor"] or any(v["optionCalls"]["answer"] is not None or v["calls"]["sync"] is not None for v in g["corruptLabor"].values())),
    # --- the notes ---
    "figures nobody typed are called typed on a leftover row": (
        STRAY_FILLED, "if (false) {",
        lambda g: "typed" in g["strayWords"]["filled"] or "typed" in g["strayWords"]["filledOld"]),
    "a leftover row that is switched off says it adds to the labor": (
        STRAY_OFF, 'if (false) return where + " This line holds figures but is switched off',
        lambda g: "still adds" in g["strayWords"]["off"]),
    "a cleared guys box says the guys are typed": (
        NOTE_TYPED, "return head + (true",
        lambda g: "The guys are typed" in g["notesCleared"]["note"]),
    "a typed Travel Labor box says man-days": (
        HINT_TYPED, "void 0;", lambda g: g["notesTyped"]["hint"] != "One round trip for each guy."),
    "a typed count is worded as man-days": (
        HOW_UNIT, 'lines.push("Travel Labor: " + qty(tr.guys) + (crewFollow ? " guys" : " man-days") +',
        lambda g: "man-days (typed)" in g["notesTyped"]["how"]),
    "a base's guys are said to be the base sheets'": (
        WHERE, 'return baseCount(model) > 1 ? "the labor lines of the base sheets" : "the labor lines above";',
        lambda g: g["comboJob"]["words"].endswith("base sheets")),
    "the hint under a base's guys says the base sheets'": (
        HINT_WHERE, 'return "Most guys on one labor line" + (baseCount(model) > 1 ? " of the base sheets" : " above") + (n > 0 ? ": " + plainNum(n) : "") + ".";',
        lambda g: g["comboJob"]["hint"] != "Most guys on one labor line above: 3."),
    "a leftover row says the same whatever it holds": (
        STRAY_TYPED, "if (false) {", lambda g: "left as typed" not in g["strayWords"]["typed"]),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_rule_goes_red_when_the_model_changes(tmp_path, name):
    """Each change is a line the fill depends on, broken in a scratch copy of js/bid-model.js; the harness must show
    it. The anchor line must exist exactly once (break_source refuses otherwise), so none can pass by applying nowhere."""
    old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, "js/bid-model.js", old, new)
    got = _run(frontend)
    assert noticed(got), name
