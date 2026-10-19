"""THE DISTANCE FILLS TRAVEL LABOR on a job 70 miles or more out (Hanz, 2026-10-20).

"For jobs outside the local scope we need to automatically turn on travel time ... it would auto
calculate based on the miles from the treadwell office ... its just an estimate though." Asked how, he
chose "Every work day (Kyle's sheet math)": Kyle's Epoxy row 52 / Polish row 44 is Travel, with Guys =
(A47*B47)+(A48*B48)+... (the crew's MAN-DAYS), the Hours typed beside his note "Drive Time: ?", the Rate
$33, and the line is guys x hours x rate. So a far answer fills the line's two boxes the way the sheet
reads them: the hours from the miles (one round trip at 60 mph, to the half hour) and the guys from the
crew's man-days (guys_auto on). A typed figure always wins.

This REVERSES 2026-10-12, when the answer was made to fill nothing ("nights, days, guys and hours should
have nothing when it starts"), for Travel Labor on a far job only. This file used to pin "the distance
fills NO hours"; each of those cases is here again under the new rule. The page-level half (the lookup,
the typed miles, the Labor note, the Review, a saved bid opening unchanged) is in test_polish_estimate_page.py
and test_polish_saved_bid_safety.py. Runs the real engine through travel-hours-harness.js.

The last block breaks a COPY of js/bid-model.js one line at a time and requires the harness to notice:
the fill, the typed-wins rule, the guys, the take-back, the carrier section.
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
    """The harness's new bid is made by the page's own seeding (seedNewSections): guys and hours empty,
    off auto, no marker. The distance is what fills it, never the opening."""
    r = ran["newRow"]
    assert r["guys"] == "" and r["days"] == "" and r["guys_auto"] is False and "hours_seed" not in r


def test_wichita_190_miles_fills_6_5_hours_and_the_crews_48_man_days(ran):
    """190 miles is a 380 mile round trip: 6.33 hours at 60 mph, 6.5 to the half hour. Four guys for twelve days
    is 48 man-days, so the line is 48 x 6.5 x $33 = $10,296, switched on and not gray (a far job), with the
    three travel lines on and the trip said in words.

    Mutation: leave the fill out of applyDistance, or put the hours or the guys fill back to nothing."""
    w = ran["wichita"]
    assert (w["hours"], w["seed"], w["auto"], w["guys"]) == (6.5, 6.5, True, 48)
    assert w["manDays"] == 48 and w["on"] is True and w["local"] is False
    assert w["cost"] == w["expected"] == 10296 and w["rate"] == 33
    assert w["lodging"] is True and w["perDiem"] is True
    assert w["source"] == {"hours": 6.5, "roundTrip": 380, "mph": 60}
    assert w["words"] == "6.5 hrs: a 380 mile round trip at 60 mph from the Olathe office"
    assert "Travel Labor is the man-days on the labor lines above (48) x those hours, the way Kyle's sheet works it" in w["note"]
    assert "crew" not in w["note"].lower(), "the estimate page never says crew: its column is Guys"
    assert w["note"].startswith(w["words"] + ". ")
    assert w["how"] == ("Travel Labor: 48 man-days x 6.5 drive hours (a 380 mile round trip at 60 mph from the "
                        "Olathe office) x $33.00 = $10,296.00")


def test_the_answer_fills_the_guys_by_itself_and_not_only_through_the_page_sync(ran):
    """applyDistance alone, with no syncAutoGuys after it: the guys are already the 48 man-days."""
    assert ran["wichitaBare"] == {"hours": 6.5, "seed": 6.5, "auto": True, "guys": 48, "cost": 10296, "on": True}


def test_the_shipped_models_own_travel_row_is_filled_the_same(ran):
    """freshModel's Travel row (marker "", on auto) is not a different case from a new bid's row."""
    assert ran["shippedRow"] == {"hours": 6.5, "seed": 6.5, "auto": True, "guys": 48, "cost": 10296, "on": True}


def test_with_no_crew_typed_yet_the_hours_are_there_and_the_line_prices_nothing_until_the_crew_is(ran):
    """The guys follow the man-days, and there are none yet: 0 x 6.5 x $33. The words say what to type, and the
    figure moves with the crew once it is typed, as the page's changed() keeps it."""
    n = ran["noCrewYet"]
    assert (n["hours"], n["guys"], n["auto"], n["cost"]) == (6.5, 0, True, 0)
    assert n["how"].endswith("= $0.00. The guys follow the man-days, so type the days on the labor lines above.")
    assert "so it prices once those lines have days" in n["note"] and "crew" not in n["note"].lower()
    assert ran["crewAfter"] == {"hours": 6.5, "seed": 6.5, "auto": True, "guys": 48, "cost": 10296, "on": True}


def test_the_line_is_priced_at_its_own_rate_and_is_nothing_without_the_fill(ran):
    assert ran["pricedBefore"] == 0 and ran["pricedAfter"] == 10296
    assert ran["pricedAtOwnRate"] == 48 * 6.5 * 40, "guys x hours x the line's own rate, never a second rate"


# ── a typed figure always wins ───────────────────────────────────────────────────────────────────
def test_hours_the_estimator_typed_survive_a_second_answer(ran):
    """6.5 filled, 4 typed over it (text, as the box hands it over), 300 miles answered: still 4, the marker
    still the 6.5 the tool wrote, the guys still follow the crew, and no source note is claimed for them.

    Mutation: let the answer overwrite a figure that is neither empty nor the tool's own."""
    t = ran["typedHoursSurvive"]
    assert (t["hours"], t["seed"], t["guys"], t["cost"]) == ("4", 6.5, 48, 48 * 4 * 33)
    assert t["source"] is None and t["note"] == ""
    assert t["how"].endswith("x 4 drive hours (typed) x $33.00 = $6,336.00")


def test_hours_that_spell_the_digits_the_tool_wrote_are_still_the_estimators(ran):
    """"6.5" typed over a 6.5 the tool wrote is text; the tool's own is a number. The two are not the same figure.

    Mutation: tell the tool's figure from a typed one by its digits alone (the 2026-10-06 rule)."""
    assert ran["typedSameDigits"]["hours"] == "6.5"


def test_typed_guys_survive_and_the_hours_are_still_filled(ran):
    """Two guys typed (off auto) before the answer: the answer fills the hours and leaves the 2 alone.

    Mutation: put the guys on the man-days whatever was typed."""
    g = ran["typedGuysSurvive"]
    assert (g["hours"], g["auto"], g["guys"], g["cost"]) == (6.5, False, "2", 2 * 6.5 * 33)


def test_typed_zero_hours_is_an_answer_and_not_a_blank_to_fill(ran):
    z = ran["typedZeroStays"]
    assert z["hours"] == "0" and z["seed"] is None and z["cost"] == 0


def test_an_untouched_figure_follows_the_next_answer(ran):
    """190 miles wrote 6.5; 300 miles moves it to 10 (a 600 mile round trip is exactly 10 hours); the marker moves with it.

    Mutation: stop writing the marker, so the next answer takes the tool's own figure for a typed one."""
    assert ran["untouchedMoves"] == {"hours": 10, "seed": 10, "auto": True, "guys": 48, "cost": 48 * 10 * 33, "on": True}


def test_every_answer_in_turn_on_one_bid(ran):
    """190 -> 6.5, 300 -> 10, exactly 70 -> 2.5 (2.33 hours is far), 69.9 -> local and empty, 120.4 -> 4.5."""
    assert ran["sequence"] == [[190, 6.5, 6.5, False], [300, 10, 10, False], [70, 2.5, 2.5, False],
                               [69.9, "", "", True], [120.4, 4.5, 4.5, False]]


# ── going local, and clearing the miles ──────────────────────────────────────────────────────────
def test_going_local_takes_the_tools_hours_back_and_the_line_grays(ran):
    """Under 70 miles the figure the tool wrote goes back to empty (the marker with it), so the card is untouched
    again and grays as it always did. The guys stay on the man-days: a derived count that prices nothing without hours.

    Mutation: leave the tool's hours on a local job."""
    g = ran["goingLocal"]
    assert (g["hours"], g["seed"], g["cost"], g["local"], g["note"]) == ("", "", 0, True, "")
    assert g["guys"] == 48 and g["auto"] is True


def test_going_local_leaves_typed_hours_alone(ran):
    """Mutation: take every hours figure back on a local job, typed ones too."""
    k = ran["localKeepsTyped"]
    assert (k["hours"], k["local"], k["cost"]) == ("4", True, 48 * 4 * 33)


def test_far_again_fills_again(ran):
    assert ran["backToFar"]["hours"] == 6.5 and ran["backToFar"]["seed"] == 6.5


def test_clearing_the_miles_is_the_same(ran):
    """The miles cleared: unknown, local, the distance gone, the tool's hours with it; typed hours stay.

    Mutation: leave the take-back out of clearDistance."""
    c = ran["cleared"]
    assert (c["hours"], c["seed"], c["local"], c["distance"]) == ("", "", True, None)
    assert ran["clearedKeepsTyped"]["hours"] == "4"


# ── a bid saved before ───────────────────────────────────────────────────────────────────────────
def test_a_bid_saved_with_typed_hours_keeps_them(ran):
    """A pre-2026-10-12 row on auto with 5 hours typed (a number, no marker): a new answer leaves the 5."""
    s = ran["savedTypedHoursStay"]
    assert (s["hours"], s["seed"], s["auto"], s["guys"]) == (5, None, True, 48)


def test_a_bid_saved_with_the_tools_own_hours_follows_a_new_answer(ran):
    """5 hours saved with the old `hours_seed` marker (2026-10-06 to 10-12, when the distance wrote them) are the
    tool's figure still, so a new answer moves them: 300 miles is 10. It used to be pinned the other way round."""
    s = ran["savedMarkerFollows"]
    assert (s["hours"], s["seed"], s["cost"]) == (10, 10, 48 * 10 * 33)


def test_opening_a_saved_far_bid_with_travel_labor_blank_moves_nothing(ran):
    """migrateModel and the page's sync on open: the row is exactly what was saved. The fill runs when an answer is
    applied in a session, never when a bid opens. (The page proves the same through a real open.)"""
    o = ran["openMovesNothing"]
    assert o["same"] is True and o["row"]["days"] == "" and o["row"]["guys"] == ""


# ── which section ────────────────────────────────────────────────────────────────────────────────
def test_an_epoxy_job_fills_the_epoxy_sections_row_with_the_epoxy_crew(ran):
    """The Polish root is off and Epoxy carries the job's travel: its Travel row is the one filled, on its own crew
    (4 x 12), and the root's row is not touched.

    Mutation: fill the row of whatever section the model is, not the carrier's."""
    e = ran["epoxyJob"]
    assert e["carrier"] == "Epoxy" and e["rootRowUntouched"] is True
    assert (e["hours"], e["guys"], e["manDays"], e["cost"]) == (6.5, 48, 48, 10296)


def test_a_combo_job_fills_the_first_bases_row_with_that_bases_crew(ran):
    """Polish and Epoxy are both bases; the first, Polish, carries the travel: its crew is 3 x 5 = 15 man-days, not
    Epoxy's 48 and not 63."""
    c = ran["comboJob"]
    assert c["carrier"] == "Polish" and c["epoxyHasTravel"] is False
    assert (c["hours"], c["guys"], c["manDays"], c["cost"]) == (6.5, 15, 15, 15 * 6.5 * 33)


def test_a_gyp_job_is_left_exactly_as_it_was(ran):
    """A Gyp crew is priced by the hour, so it has no man-days to follow, and the Gyp sheet works its own drive time.
    The answer is still recorded (far, not local); the Travel row is not touched.

    Mutation: take the Gyp carrier out of the guard."""
    g = ran["gypJob"]
    assert g["untouched"] is True and g["local"] is False and g["distance"]["miles"] == 190


def test_a_bid_with_no_travel_labor_row_takes_the_answer_and_nothing_throws(ran):
    n = ran["noTravelRow"]
    assert n["threw"] is None and n["distance"]["miles"] == 190 and "travel" not in n["rows"]


# ── the other two lines, bad input, words ────────────────────────────────────────────────────────
def test_lodging_and_per_diem_are_as_they_were(ran):
    """Switched on by the answer, a hand flip never moved, and their quantities still open empty and typed."""
    ln = ran["lines"]
    assert ln["lodging"] is False and ln["perDiem"] is True
    assert ln["lodgingQty"] == "" and ln["perDiemQty"] == "" and ln["lodgingAuto"] is False and ln["perDiemAuto"] is False


def test_an_answer_with_no_usable_miles_changes_nothing(ran):
    b = ran["badInput"]
    assert b["unchanged"] is True and b["nullModel"] is None and b["clearNull"] == "undefined"


def test_the_words_say_where_the_hours_came_from(ran):
    """The tool's figure says the trip; a figure this distance would not give keeps the older, plainer words; one with
    no distance behind it says so; and only a number the tool wrote is the tool's."""
    w = ran["words"]
    assert w["tool"].startswith("Travel Labor: 48 man-days x 6.5 drive hours (a 380 mile round trip at 60 mph from the "
                                "Olathe office) x $33.00")
    assert w["staleSource"] is None and "(round trip at 60 mph)" in w["stale"]
    assert w["goneSource"] is None and "(from an earlier distance; type the miles or the hours)" in w["gone"]
    assert w["areTools"] == [True, False, False, False, False]
    assert w["fractional"] == "4.5 hrs: a 240.8 mile round trip at 60 mph from the Olathe office"


# ── red without the code: break a COPY of the model one line at a time ───────────────────────────
FILL = "if (isBlank(row.days) || wrote) { row.days = hours; row.hours_seed = hours; }"
GUYS_ON = "if (!row.guys_auto && !filledIn(row.guys)) row.guys_auto = true;"
GUYS_SET = "if (row.guys_auto) row.guys = travelManDays(held.rows);"
TAKE_BACK = 'if (wrote) { row.days = ""; row.hours_seed = ""; }'
GYP_GUARD = 'if (layout === "gyp") return null;'
TOOLS = 'typeof row.days === "number" && typeof row.hours_seed === "number" && row.days === row.hours_seed'

MUTATIONS = {
    "the answer fills no hours": (
        FILL, "void hours;", lambda g: g["wichita"]["hours"] != 6.5),
    "the answer is never applied to Travel Labor": (
        "followDistanceHours(model, miles);", "void miles;", lambda g: g["wichita"]["hours"] != 6.5),
    "a typed figure is overwritten by the next answer": (
        FILL, "row.days = hours; row.hours_seed = hours;", lambda g: g["typedHoursSurvive"]["hours"] != "4"),
    "the marker is not written, so the next answer cannot move the tool's figure": (
        FILL, "if (isBlank(row.days) || wrote) { row.days = hours; }", lambda g: g["untouchedMoves"]["hours"] != 10),
    "the tool's figure is told from a typed one by its digits alone": (
        TOOLS, "!isBlank(row.hours_seed) && num(row.days) === num(row.hours_seed)",
        lambda g: g["typedSameDigits"]["hours"] != "6.5"),
    "the guys are never put on the man-days": (
        GUYS_ON, "void 0;", lambda g: g["wichita"]["cost"] != 10296),
    "typed guys are put on the man-days": (
        GUYS_ON, "row.guys_auto = true;", lambda g: g["typedGuysSurvive"]["guys"] != "2"),
    "the answer leaves the guys to the page's sync": (
        GUYS_SET, "void 0;", lambda g: g["wichitaBare"]["guys"] != 48),
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
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_rule_goes_red_when_the_model_changes(tmp_path, name):
    """Each change is a line the fill depends on, broken in a scratch copy of js/bid-model.js; the harness must show
    it. The anchor line must exist exactly once (break_source refuses otherwise), so none can pass by applying nowhere."""
    old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, "js/bid-model.js", old, new)
    got = _run(frontend)
    assert noticed(got), name
