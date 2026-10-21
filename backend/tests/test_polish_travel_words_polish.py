"""ROUND 7 POLISH (2026-10-22): FOUR LOW FINDINGS OF THE REAL-BROWSER WALK OF STAGING, all in the travel words and the drive switch, on the real estimate page
(tests/js/travel-words-polish-harness.js runs js/polish-estimate.js over the real js/bid-model.js; every reopen is a jsonb one). The walk passed every round-7 behaviour; these are staff-facing
and the prices were right, except W4's stale figure.

  W1 (X5a)  A BASE THAT DRIVES ON ITS OWN AND HOLDS NO TRAVEL LABOR LINE (its x took the line away: its own answer) was told "This sheet's guys drive on their own: its Travel Labor below is one
            round trip for each of them" directly above "This sheet has no Travel Labor line, so its drive adds nothing to the price", and its Review said "This sheet's own drive is its Travel
            Labor line, under Labor". With no line those clauses go and the Hotel and Per Diem sentence stays. A sheet that holds its line keeps both notes whole.
  W2 (X5b)  A DRIVE OF SEVERAL ROUND TRIPS (a far Gyp with its Mobilizations typed) said "one round trip each" in the how-note's summary and "One round trip for each guy" under a typed Guys box
            while three round trips each were charged. The words say the trips the price uses; hours the estimator typed are one trip's, as they were.
  W3 (A4)   A NEW COMBO WHOSE LIBRARY DECLINED TRAVEL (both bases carry their own answer, S) had the carrier say "The Epoxy sheet keeps its own Travel Labor line" while its working says "no line on
            that sheet". The words name only the bases that hold a line.
  W4 (A5)   A DRIVE LINE SWITCHED OFF KEEPS ITS HOURS (an answer leaves an off line alone), so switching it back ON priced a stale figure, with mobilizations N trips long. A line the TOOL filled is
            filled again by the rule from the distance and trips on file; a figure the estimator typed stays theirs, a line the tool never filled is left to them, and the price is the price of the
            same bid that was never switched off. The only price this file lets move.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-words-polish-harness.js"
SECTIONS = ("w1", "w2", "w3", "w4")
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]

GYP = 'Gyp (USG 1-8")'
GYP_ROW = GYP + ":base"

# W1: the notes under Travel on the Labor step and in the Hotel and Per Diem card of the Review, of a base that does not carry the job's Hotel and Per Diem
OWN_DRIVE_CLAUSE = ("This sheet's guys drive on their own: its Travel Labor below is one round trip for each of them, from the miles on the Polish section. ")
HOTEL_ONCE = "Hotel and Per Diem are charged once for the whole job, on the Polish section."
LABOR_NOTE_LINE = OWN_DRIVE_CLAUSE + HOTEL_ONCE + " Open it to change them."
LABOR_NOTE_NO_LINE = HOTEL_ONCE + " Open it to change them."
REVIEW_NOTE_LINE = HOTEL_ONCE + " This sheet's own drive is its Travel Labor line, under Labor."
REVIEW_NOTE_NO_LINE = HOTEL_ONCE
NONE_WORDS = "This sheet has no Travel Labor line, so its drive adds nothing to the price."
OPTION_NOTE = ("This option is priced apart, so it carries its own Hotel and Per Diem for its own crew when the job is on the road, at the rates set on the Polish section. Open it to change them.")
OPTION_NONE_WORDS = "This option has no Travel Labor line, so its drive adds nothing to its price."

# W2
GUYS_ONE_TRIP = "Guys = the most guys on any one labor line above (4 now), one round trip each."
GUYS_THREE_TRIPS = "Guys = the most guys on any one labor line above (4 now), 3 round trips each, one for each mobilization."
CREW_HINT = "Most guys on one labor line above: 4."
ONE_TRIP_HINT = "One round trip for each guy."

# W3
BID_WORDS = "This bid has no Travel Labor line, so the drive adds nothing to the price."
SHEET_WORDS = "This sheet has no Travel Labor line, so its own crew's drive is not charged. The Epoxy sheet keeps its own Travel Labor line."


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    got = run()
    for k in SECTIONS:
        assert "error" not in got[k], "%s threw: %s" % (k, got[k]["error"][:600])
    return got


# ── W1: a base that holds no Travel Labor line is not told its guys drive on their own ────────────────────────────────────────────────────────────────────────────────────
def test_a_base_whose_travel_line_was_taken_away_is_not_told_its_guys_drive_on_their_own(ran):
    """Far Combo, the x on the Epoxy sheet's drive: its Labor step keeps the Hotel and Per Diem sentence and loses the clause about the drive it no longer has (it stood directly above
    "This sheet has no Travel Labor line"), and so does its Review. A reload of the saved bid draws the same words."""
    w = ran["w1"]
    assert w["x"] is True
    n = w["noLine"]
    assert n["note"] == LABOR_NOTE_NO_LINE and n["noneWords"] == NONE_WORDS and n["add"] is True
    assert n["review"] == REVIEW_NOTE_NO_LINE
    assert "drive on their own" not in n["note"] and "own drive is its Travel Labor line" not in n["review"]
    assert w["reloaded"] == n


def test_a_base_that_holds_its_line_keeps_both_notes_and_add_brings_them_back(ran):
    """The Epoxy sheet with its line says it drives on its own on the Labor step and that its own drive is its Travel Labor line on the Review. Add Travel Labor after the x brings the line back, and
    the words with it. The carrier, which carries the job's Hotel and Per Diem, has no note about another sheet."""
    w = ran["w1"]
    assert w["withLine"]["note"] == LABOR_NOTE_LINE and w["withLine"]["review"] == REVIEW_NOTE_LINE and w["withLine"]["noneWords"] is None and w["withLine"]["add"] is False
    assert w["added"] is True and w["afterAdd"] == w["withLine"]
    assert w["carrier"]["note"] is None


def test_an_option_with_no_line_has_its_own_words(ran):
    """An option is priced apart and carries its own Hotel and Per Diem: its words were never about a sheet that drives on its own, and still are not."""
    w = ran["w1"]
    assert w["copy"] == "Copy1" and w["xo"] is True
    assert w["option"]["note"] == OPTION_NOTE and w["option"]["noneWords"] == OPTION_NONE_WORDS and w["option"]["add"] is True


# ── W2: the words say the trips the price uses ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_summary_says_one_round_trip_each_until_the_mobilizations_make_it_more(ran):
    """Far Gyp, crew 4 x 120 hours, 190 miles. The Mobilizations box blank: one round trip, 4 x 6.5. Three typed: three round trips of 6.5 hours, 4 x 19.5 = $2,574, and the summary of
    how the guys are counted says so. It said "one round trip each" beside the three trips of the line above it."""
    w = ran["w2"]
    assert w["one"]["row"] == "4 x 6.5 = $858" and w["one"]["guys"] == GUYS_ONE_TRIP
    assert w["typed3"] is True and w["three"]["row"] == "4 x 19.5 = $2574"
    assert w["three"]["guys"] == GUYS_THREE_TRIPS and "one round trip each" not in w["three"]["guys"]
    assert "(3 round trips of 380 miles at 60 mph from the Olathe office, 6.5 hrs each, one for each mobilization, for each guy)" in w["how"], "the working line already said it"


def test_the_hint_under_a_typed_guys_box_says_the_trips_the_hours_are(ran):
    """The Guys box typed on the far Gyp: its hint said "One round trip for each guy." over hours that are three trips (and two, after the box moves to 2). Hours the estimator typed are
    their own, one trip's as they always were; a Polish bid's typed guys read as before; and a box on the crew's size says nothing of trips, as before."""
    w = ran["w2"]
    assert w["one"]["hint"] == CREW_HINT and w["three"]["hint"] == CREW_HINT
    assert w["guysTyped"]["row"] == "4 x 19.5 = $2574" and w["guysTyped"]["hint"] == "3 round trips for each guy, one for each mobilization."
    assert w["twoTrips"]["row"] == "4 x 13 = $1716" and w["twoTrips"]["hint"] == "2 round trips for each guy, one for each mobilization."
    assert w["hoursTyped"]["row"] == "4 x 5 = $660" and w["hoursTyped"]["hint"] == ONE_TRIP_HINT
    assert w["polish"] == {"guys": GUYS_ONE_TRIP, "hint": ONE_TRIP_HINT}


# ── W3: the words name only the bases that hold a line ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_combo_whose_library_declined_travel_is_not_told_the_other_sheet_keeps_a_line(ran):
    """The library's Travel row says no on every work type: a NEW far Combo has no drive on either base, and each says so as its own answer. The carrier said "The Epoxy sheet keeps its own Travel Labor
    line" (and its working "This sheet has no Travel Labor line, so its own crew's drive is not charged") beside "Travel Labor on the Epoxy sheet: no line on that sheet, $0". Neither base holds a
    line, so it says the bid has none; a reload draws the same words."""
    w = ran["w3"]
    assert w["answers"] == {"rows": {"Polish:base": None, "Epoxy:base": None}, "sheets": ["Polish", "Epoxy"], "job": False}, "the premise: both bases carry their own answer and no line"
    c = w["carrier"]
    assert c["add"] is True and c["none"] == "" and c["noneWords"] == BID_WORDS
    how = c["how"].split("\n")
    assert how[0].endswith("so this is NOT a local job: Lodging and Per Diem come on, and there is no Travel Labor line to price the drive: add it below.")
    assert how[1] == "Travel Labor: no line on this bid, $0"
    assert how[2] == "Travel Labor on the Epoxy sheet: no line on that sheet, $0."
    for words in (c["noneWords"], c["how"]):
        assert "keeps its own Travel Labor line" not in words and "its own crew's drive is not charged" not in words
    assert w["reloaded"]["noneWords"] == BID_WORDS and w["reloaded"]["none"] == "" and w["reloaded"]["how"] == c["how"]


def test_the_epoxy_side_of_that_combo_says_the_same_in_its_own_words(ran):
    """The second base of the same bid (it holds no line either): its Labor step and its Review leave out the clauses about a drive it does not have (W1), and say what is true of the sheet."""
    w = ran["w3"]
    assert w["epoxy"]["noneWords"] == NONE_WORDS and w["epoxy"]["note"] == LABOR_NOTE_NO_LINE and w["epoxyNote"] == REVIEW_NOTE_NO_LINE


def test_a_base_that_does_hold_a_line_is_still_named(ran):
    """The x on the Polish drive of an ordinary far Combo: the Epoxy sheet holds its line (5 x 6.5), so the carrier still says so (round 7, part 4, P6), in its words and its working. With the Epoxy
    line gone too (the job's answer), it says the bid has none."""
    w = ran["w3"]
    assert w["x"] is True
    k = w["kept"]
    assert k["noneWords"] == SHEET_WORDS and k["none"] == "sheet"
    assert "The Epoxy sheet keeps its own Travel Labor line." in k["how"]
    assert "Travel Labor on the Epoxy sheet: 5 guys x 6.5 drive hours x $33.00 = $1,072.50 (that sheet's own guys)." in k["how"]
    assert w["both"]["noneWords"] == BID_WORDS and w["both"]["none"] == ""


# ── W4: a tool-filled drive line switched back on is filled again by the rule ────────────────────────────────────────────────────────────────────────────────────────────────
def test_switching_a_drive_back_on_after_the_miles_moved_prices_the_rule_and_not_the_stale_hours(ran):
    """Far Polish 4 x 12 at 190 miles: 4 x 6.5. The switch off, 300 miles typed (an off line is left alone: it still holds 6.5), the switch on: 4 x 10, and the bid is the bid of the same job
    that was never switched off ($41,771; it was $40,864 with the stale figure). A jsonb reload of what was saved agrees."""
    m = ran["w4"]["miles"]
    assert m["before"] == {"Polish:base": "4 x 6.5 = $858"} and m["off"] is True and m["on"] is True
    assert m["stale"]["rows"] == {"Polish:base": "4 x 6.5 = $0"} and m["stale"]["marks"]["on"] is False, "an answer leaves a line that is switched off alone"
    assert m["done"]["rows"] == {"Polish:base": "4 x 10 = $1320"} and m["done"]["marks"] == {"auto": True, "follow": "crew", "seed": 10, "typed": False, "on": True}
    assert m["done"]["price"] == m["never"]["price"] and m["done"]["price"]["lump"] == 41771
    assert m["reloaded"] == {"rows": m["done"]["rows"], "price": m["done"]["price"]}


def test_switching_a_gyp_drive_back_on_after_the_mobilizations_moved_prices_the_trips_on_file(ran):
    """Far Gyp, 3 mobilizations: 4 x 19.5. Off, 2 typed on the Gyp card (the off line is left alone, three trips long), on: 4 x 13, two trips, the price of the same bid with 2 typed from the start."""
    t = ran["w4"]["trips"]
    assert t["before"] == "4 x 19.5 = $2574" and t["stale"] == "4 x 19.5 = $0"
    assert t["done"]["row"] == "4 x 13 = $1716" and t["done"]["marks"] == {"auto": True, "follow": "crew", "seed": 13, "typed": False, "on": True}
    assert t["done"]["price"] == t["never"]["price"] and t["never"]["row"] == "4 x 13 = $1716"


def test_what_the_estimator_typed_stays_theirs_when_the_line_is_switched_back_on(ran):
    """Hours typed (5): off, 300 miles, on: still 4 x 5. Guys typed (7) over the tool's hours: the tool's hours are filled again (7 x 10) and the guys stay the estimator's."""
    t = ran["w4"]["typed"]
    assert t["hours"]["rows"] == {"Polish:base": "4 x 5 = $660"} and t["hours"]["marks"]["typed"] is True
    assert t["guys"]["rows"] == {"Polish:base": "7 x 10 = $2310"} and t["guys"]["marks"] == {"auto": False, "follow": None, "seed": 10, "typed": True, "on": True}


def test_a_line_switched_back_on_when_the_job_went_local_gives_the_tools_hours_back(ran):
    """40 miles typed while the line was off, then on: the rule at 40 miles fills nothing, so the tool's hours go back to empty as they would have had the line been on (4 x blank), and the bid is
    the bid of the same job at 40 miles ($30,872; $32,632 with the stale 6.5 hours priced on a local job)."""
    l = ran["w4"]["local"]
    assert l["stale"] == {"Polish:base": "4 x 6.5 = $0"}
    assert l["done"]["rows"] == {"Polish:base": "4 x  = $0"} and l["done"]["marks"] == {"auto": True, "follow": "crew", "seed": "", "typed": False, "on": True}
    assert l["done"]["price"] == l["never"]["price"] and l["done"]["price"]["lump"] == 30872


def test_an_options_drive_is_refilled_the_same_way_and_goes_back_whole_when_the_job_goes_local(ran):
    """A copy of the Polish sheet (an option, priced apart) holds its own drive: 300 miles while it is off, then on: 4 x 10. Gone local and switched back on, an option's fill nobody touched goes back
    WHOLE (guys and hours both empty, every marker gone), as the same answer gives it when the line is on; a base keeps its guys (the test above)."""
    o = ran["w4"]["option"]
    assert o["copy"] == "Copy1" and o["before"] == "4 x 6.5 = $858" and o["stale"] == "4 x 6.5 = $0"
    assert o["done"] == "4 x 10 = $1320"
    assert o["local"] == {"row": " x  = $0", "marks": {"auto": False, "follow": None, "seed": None, "typed": False, "on": True}}


def test_a_line_the_tool_never_filled_is_not_filled_by_the_switch_and_a_crew_line_is_no_drive(ran):
    """A far bid whose Travel Labor line is blank and off (the library's default or the estimator's): the switch brings it back blank, as it always did, for the estimator to fill; the how-note says
    to type the guys and the hours. And Polish switched off and on again moves no price and no figure on the drive."""
    b = ran["w4"]["blank"]
    assert b["before"]["rows"] == {"Polish:base": "4 x  = $0"} and b["before"]["marks"]["on"] is False and b["before"]["marks"]["seed"] is None
    assert b["after"]["rows"] == {"Polish:base": "4 x  = $0"} and b["after"]["marks"]["on"] is True and b["after"]["marks"]["seed"] is None
    c = ran["w4"]["crew"]
    assert c["after"] == c["before"]


# ── red without the code: break a COPY of the page or the model one line at a time; a fact must change, never a crash ───────────────────────────────────────────────────
OWN_LINE = "      var ownLine = (M.labor instanceof Array ? M.labor : []).some(function (r) { return B.isTravelRow(r); });"
HINT_TRIPS = '    if (trips > 1) return plainNum(trips) + " round trips for each guy, one for each mobilization.";'
HOW_GUYS = '      lines.push("Guys = the most guys on any one labor line above (" + qty(tr.guys) + " now), " + (trips > 1 ? qty(trips) + " round trips each, one for each mobilization" : "one round trip each") + ".");'
OTHERS = "    return drives.filter(function (e) { return e.tab !== tab && travelRowsIn(e.section).length > 0; }).map(function (e) { return e.label; });"
SWITCH_GUARD = '    if (!isObject(model) || !isTravelRow(row) || !driveHoursAreTools(row)) return model;'
SWITCH_FILL = "    followDistanceOnRow(model, row, rows, d ? milesOrNull(d.miles) : null, !isDriveTab(model, tab), driveTripsOf(e));"
SWITCH_CALL = "        if (B.rowOn(M.labor[ol])) B.followDriveSwitchedOn(ROOT, activeTab, M.labor[ol]);"

BREAKS = {
    # --- W1 ---
    "a base with no line is told its guys drive on their own": (
        "js/polish-estimate.js", OWN_LINE, "      var ownLine = true;",
        lambda g: g["w1"]["noLine"]["note"] != LABOR_NOTE_NO_LINE or g["w1"]["noLine"]["review"] != REVIEW_NOTE_NO_LINE),
    "a base with a line is not told it": (
        "js/polish-estimate.js", OWN_LINE, "      var ownLine = false;",
        lambda g: g["w1"]["withLine"]["note"] != LABOR_NOTE_LINE or g["w1"]["withLine"]["review"] != REVIEW_NOTE_LINE),
    # --- W2 ---
    "the hint under a typed Guys box says one round trip over several": (
        "js/bid-model.js", HINT_TRIPS, "    void trips;",
        lambda g: g["w2"]["guysTyped"]["hint"] != "3 round trips for each guy, one for each mobilization."),
    "the summary says one round trip over several": (
        "js/bid-model.js", HOW_GUYS,
        '      lines.push("Guys = the most guys on any one labor line above (" + qty(tr.guys) + " now), one round trip each.");',
        lambda g: g["w2"]["three"]["guys"] != GUYS_THREE_TRIPS),
    "hours the estimator typed are counted as the tool's trips": (
        "js/bid-model.js", "    return src && src.trips > 1 ? src.trips : 1;", "    return driveTripsOf(entryHolding(model, row));",
        lambda g: g["w2"]["hoursTyped"]["hint"] != ONE_TRIP_HINT),
    # --- W3 ---
    "the words name a base that holds no line": (
        "js/bid-model.js", OTHERS,
        "    return drives.filter(function (e) { return e.tab !== tab; }).map(function (e) { return e.label; });",
        lambda g: g["w3"]["carrier"]["noneWords"] != BID_WORDS or "keeps its own Travel Labor line" in g["w3"]["carrier"]["how"]),
    "a base that holds a line is not named": (
        "js/bid-model.js", OTHERS, "    return [];",
        lambda g: g["w3"]["kept"]["noneWords"] != SHEET_WORDS),
    # --- W4 ---
    "a drive switched back on keeps its stale hours (the page)": (
        "js/polish-estimate.js", SWITCH_CALL, "        void ol;",
        lambda g: g["w4"]["miles"]["done"]["rows"] != {"Polish:base": "4 x 10 = $1320"}),
    "a drive switched back on is filled for one trip whatever the mobilizations": (
        "js/bid-model.js", SWITCH_FILL, "    followDistanceOnRow(model, row, rows, d ? milesOrNull(d.miles) : null, !isDriveTab(model, tab), 1);",
        lambda g: g["w4"]["trips"]["done"]["row"] != "4 x 13 = $1716"),
    "an option's drive switched back on is treated as a base's": (
        "js/bid-model.js", SWITCH_FILL, "    followDistanceOnRow(model, row, rows, d ? milesOrNull(d.miles) : null, false, driveTripsOf(e));",
        lambda g: g["w4"]["option"]["local"]["row"] != " x  = $0"),
    "a drive switched back on is filled from no distance": (
        "js/bid-model.js", SWITCH_FILL, "    followDistanceOnRow(model, row, rows, null, !isDriveTab(model, tab), driveTripsOf(e));",
        lambda g: g["w4"]["miles"]["done"]["rows"] != {"Polish:base": "4 x 10 = $1320"}),
    "a line the tool never filled is filled by the switch": (
        "js/bid-model.js", SWITCH_GUARD, "    if (!isObject(model) || !isTravelRow(row)) return model;",
        lambda g: g["w4"]["blank"]["after"]["rows"] != {"Polish:base": "4 x  = $0"}),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is a line this file depends on, broken in a scratch copy of the page or the model; a FACT must change. A break that stops the harness, or makes a section throw, is not counted as
    noticed: it has no facts to compare."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the break stopped the harness outright, so no fact noticed it: " + name + "\n" + proc.stderr[-600:]
    got = last_json_line(proc.stdout)
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "the break crashed %s instead of changing a fact: %s" % (", ".join(crashed), name)
    assert noticed(got), "the scenarios did not notice: " + name
