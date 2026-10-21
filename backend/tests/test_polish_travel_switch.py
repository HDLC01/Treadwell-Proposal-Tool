"""THE JOB'S ONE DRIVE, ON THE REAL ESTIMATE PAGE: the 2026-10-20 audit of the first version of "a far distance fills Travel Labor".

Wichita is 190 miles from the Olathe office: a 380 mile round trip, 6.33 hours at 60 mph, 6.5 to the half hour. Kyle charges each guy of the
crew ONE round trip: a crew of 4 is 4 guys x 6.5 hours x $33 = $858 (the man-days, 48 for 4 guys over 12 days, are not the guys). The first
version filled that right for a new bid and wrong for every bid whose JOB TYPE MOVED, because a job type moves the section that carries the
job's travel (the carrier), and nothing settled the Travel Labor rows when it did. Each test drives js/polish-estimate.js whole (through
tests/js/travel-switch-harness.js, on the real js/bid-model.js) the way the intake's choice reaches it, and reads the page back.

  1  Epoxy switched to Polish or Combo, Gyp to Polish, and the Sheets panel's base change: the new carrier's row is filled on the crew's size
     ($858, where the man-days left 49.5 x 6.5 x $33 = $10,617.75), and the job's ONE drive is priced ONCE: Epoxy switched to Combo had left the
     Epoxy section's filled row priced beside the new one, so Travel was charged twice. A row somebody typed is left as typed and its card says so.
  2  Combo switched to Epoxy: the Travel Labor row goes with the carrier instead of staying on the Polish root, which is off.
  4  The answers (the lookup, the typed miles, the cleared miles, the carrier settling) are handed the WHOLE model, whatever section is on show.
  6  An option copy's Travel Labor follows its OWN lines' guys.
  7  A late distance answer repaints the Review's trip sentence in place.
  8  A cleared Guys box is empty and says so; typed guys are guys.
The model rules under these (and finding 3, an older auto row with no hours) are in test_polish_travel_hours.py.

ROUND 7, PART 1 (Hanz's decisions of 2026-10-21) changed what several of these hold. D1: a far Combo has TWO drives, one per base crew (Kyle's own combo-like
sheets put a drive on both, each its own crew x its own round trip), so a Combo's Epoxy sheet keeps its own Travel Labor, filled on its own crew, and draws its
own Travel card under a note that Hotel and Per Diem are charged once, on the Polish sheet; nothing on a base says its drive is charged elsewhere any more. The job's
ONE drive is still carried when a SINGLE-base job's base moves (Polish to Epoxy), with what the estimator said on it. D2: a Gyp base's drive fills from the miles.

THE THIRD AUDIT (2026-10-20, of 7d32336) is held here too, on the page, and by test_polish_travel_sequences.py over every sequence of switches:
  H  EVERY restructure settles the job's one drive, off sections included (Epoxy to Polish to Combo priced it twice, $1,716), and the Epoxy card no longer
     says its figures "were typed" over the tool's own.
  M  Combo made Polish re-derives the crew-following row's guys, so the draft saves the price a plain reopen shows; a new bid's distance lookup lands whatever
     section is on show; what the estimator typed, cleared or switched off follows the job's drive to a newly seeded carrier instead of being refilled.

THE FOURTH AUDIT (2026-10-20, of c0255de) is held here too, on the page, and by test_polish_travel_hours.py on the model:
  O  An option's Travel Labor (a copy of the carrier, or a base the Sheets panel demoted) follows every distance answer on its own crew: the miles corrected to 50
     emptied the base's drive and left the option's priced, and at 300 miles the base moved to 10 hours while the option stayed at 6.5.
  R  A rate typed on Travel Labor follows the job's drive to the new carrier ($40 read $33 on Epoxy).
  B  A saved bid whose active section's labor is not a list opens (the sync threw as the page opened: no estimate at all).

The last block breaks a COPY of js/polish-estimate.js or js/bid-model.js one line at a time and requires a fact to change: never a crash.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-switch-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]
SECTIONS = ["epoxyBid", "epoxyToPolish", "epoxyToCombo", "epoxyPlain", "gypToPolish", "comboToEpoxy", "typedToCombo", "sheetsCombined",
            "wholeModel", "optionCopy", "comboOptionCopy", "reviewLate", "notes", "epoxyPolishCombo", "comboEpoxyPolishCombo", "staleSaved",
            "comboToPolishSync", "lateLookup", "newCarrierFollows", "renamedCarrier", "nightShiftLine", "optionFollowsMiles", "demotedOptionFollowsMiles",
            "typedRateOnThePage", "corruptLabor"]

CREW_ROW = {"guys": 4, "days": 6.5, "auto": True, "follow": "crew", "seed": 6.5, "typed": False, "hoursTyped": False, "cost": 858}
EMPTY_ROW = {"guys": "", "days": "", "auto": False, "follow": None, "seed": None, "typed": False, "hoursTyped": False, "cost": 0}
TRIP = "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor lines above"
OWN_DRIVE_NOTE = ("This sheet's guys drive on their own: its Travel Labor below is one round trip for each of them, from the miles on the Polish section. "
                  "Hotel and Per Diem are charged once for the whole job, on the Polish section. Open it to change them.")


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    got = run()
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "a section of the harness failed: " + "; ".join("%s: %s" % (k, got[k]["error"][:400]) for k in crashed)
    return got


def _row(job, tab):
    return job["rows"][tab]["row"]


# ── 1. a job type switched in the session ────────────────────────────────────────────────────────
def test_the_epoxy_bid_these_switches_start_from_is_filled_once_on_epoxy(ran):
    """The starting point: a NEW Epoxy bid, the lookup answers 190 miles, the crew typed 4 x 12. Epoxy carries the travel (the Polish root is off),
    its row is the crew's 4 x 6.5 x $33 = $858, and that is the only row priced."""
    b = ran["epoxyBid"]
    assert (b["carrier"], b["jobType"], b["kinds"]) == ("Epoxy", "epoxy", [["Polish", "off"], ["Epoxy", "base"]])
    assert _row(b, "Epoxy") == CREW_ROW and b["pricedOn"] == ["Epoxy"] and b["travelDollars"] == 858
    assert (b["distance"], b["lodging"], b["perDiem"]) == (190, True, True)


def test_an_epoxy_job_switched_to_polish_prices_the_drive_on_the_crew_not_on_the_man_days(ran):
    """THE AUDIT'S HIGH FINDING. The intake's job type is changed to Polish and the estimate reopened. The Polish root is the new carrier and, an
    Epoxy job's root never having been seeded, holds the model's own older man-days row. The distance on file fills its hours AND puts its guys
    on the crew's size: opened, 3 guys (the root's own Polishing) x 6.5 x $33; with the real crew typed, 4 x 6.5 x $33 = $858 in the box, the head,
    the note and the working. Before the fix the guys stayed on the 49.5 man-days: 49.5 x 6.5 x $33 = $10,617.75. The Epoxy row goes off with its
    section and prices nothing. The man-days (49.5) are still the reference for the nights and days, and are never the Travel guys.

    Mutation: leave the older auto row on the man-days when the answer fills it; hand the settling the section on show instead of the model."""
    s = ran["epoxyToPolish"]
    o = s["open"]
    assert (o["job"]["carrier"], o["job"]["jobType"], o["job"]["kinds"]) == ("Polish", "polish", [["Polish", "base"], ["Epoxy", "off"]])
    assert (o["card"]["guysBox"], o["card"]["hoursBox"], o["job"]["travelDollars"]) == ("3", "6.5", 3 * 6.5 * 33)
    assert o["job"]["saves"] == 0 and o["job"]["asked"] == 0, "nothing is looked up for a saved bid; the draft is saved by the first edit"
    w = s["wichita"]
    root = _row(w["job"], "Polish")
    assert root == CREW_ROW and root["cost"] == 858 != 49.5 * 6.5 * 33
    assert w["job"]["pricedOn"] == ["Polish"] and w["job"]["travelDollars"] == 858, "the off Epoxy section prices nothing"
    assert (w["card"]["guysBox"], w["card"]["hoursBox"]) == ("4", "6.5")
    assert w["card"]["hint"] == "Most guys on one labor line above: 4."
    assert w["card"]["note"] == {"text": TRIP + ". Type more trips for a long job.", "hidden": False}
    assert ("Travel Labor: 4 guys x 6.5 drive hours (one 380 mile round trip at 60 mph from the Olathe office, for each guy) x $33.00 = $858.00"
            in w["card"]["how"])
    assert s["manDays"] == 49.5 and s["crew"] == 4, "the man-days are not the guys"
    assert w["job"]["laborTotals"]["Polish"] == 12672 + 396 + 858, "Polishing 4 x 12, the mock-up, and one Travel Labor row"


def test_an_epoxy_job_switched_to_combo_gives_each_base_crew_its_own_drive(ran):
    """ROUND 7 (Hanz, 2026-10-21, D1). The root is the new carrier (the first base) and Epoxy is STILL a base: each crew drives. Opened, the Epoxy sheet keeps its own
    drive (its crew of 4: 4 x 6.5 x $33 = $858) and the root, made a base, is filled on ITS crew (the root's own Polishing of 3: $643.50); with the Polish crew typed 4 x
    12 it is $858 + $858 = $1,716. The Epoxy sheet's own Labor step draws its own Travel Labor card (the note on where its hours came from, its own crew's hint) under the
    words that Hotel and Per Diem are charged once, on the Polish sheet. The saved bid holds both, and a reopen of it as Combo changes and saves nothing. Until round 7 the
    switch took Epoxy's drive back so ONE row was priced ($858) and the Epoxy card said to leave its line empty: the one-drive law Hanz replaced.

    Mutation: take a base's drive back; draw a base's drive as a leftover (BREAKS below)."""
    s = ran["epoxyToCombo"]
    o = s["open"]
    assert (o["job"]["carrier"], o["job"]["jobType"], o["job"]["kinds"]) == ("Polish", "combo", [["Polish", "base"], ["Epoxy", "base"]])
    assert o["job"]["pricedOn"] == ["Polish", "Epoxy"] and o["job"]["travelDollars"] == 643.5 + 858, "opened, each base prices its own crew's drive"
    assert _row(o["job"], "Epoxy") == CREW_ROW and _row(o["job"], "Polish")["guys"] == 3
    assert o["card"]["hint"] == "Most guys on one labor line above: 3."
    w = s["wichita"]["job"]
    assert w["pricedOn"] == ["Polish", "Epoxy"] and w["travelDollars"] == 1716
    assert _row(w, "Polish") == CREW_ROW and _row(w, "Epoxy") == CREW_ROW
    assert (w["rows"]["Polish"]["count"], w["rows"]["Epoxy"]["count"]) == (1, 1)
    assert w["laborTotals"] == {"Polish": 12672 + 396 + 858, "Epoxy": 12672 + 858}, "the Epoxy section carries its crew and its own drive"
    e = s["epoxyStep"]
    assert e["note"] == TRIP + ". Type more trips for a long job." and e["stray"] is None and e["cardCost"] == "$858"
    assert e["travelNote"] == OWN_DRIVE_NOTE and e["genericHint"] is True and e["hint"] == "Most guys on one labor line above: 4."
    assert s["saved"]["Polish"] == CREW_ROW and s["saved"]["Epoxy"] == CREW_ROW
    r = s["reopened"]
    assert r["job"]["saves"] == 0 and r["job"]["asked"] == 0 and r["job"]["pricedOn"] == ["Polish", "Epoxy"]
    assert _row(r["job"], "Polish") == CREW_ROW and _row(r["job"], "Epoxy") == CREW_ROW


def test_a_combo_switched_to_epoxy_leaves_epoxy_its_own_drive(ran):
    """THE AUDIT'S MEDIUM FINDING, under round 7's law. A Combo (Polish 4 guys, Epoxy 5) has two drives (D1: $858 + $1,072.50). Switched to Epoxy, the root is off and
    gives back what the distance filled on it (its row stays, emptied), and Epoxy, the remaining base, keeps ITS OWN drive, filled on its crew (5 x 6.5 x $33 =
    $1,072.50, then 4 x 6.5 x $33 = $858 with a crew of 4); Lodging and Per Diem stay on and the how-note says the line and its guys. The saved bid reopens as it was
    left. (Until round 7 Epoxy had no Travel Labor row on the Combo and the root's was carried to it; the audit's finding was that row stranded on the off root.)

    Mutation: leave the off root's fill on it (BREAKS below)."""
    s = ran["comboToEpoxy"]
    c = s["combo"]
    assert c["carrier"] == "Polish" and c["pricedOn"] == ["Polish", "Epoxy"] and c["travelDollars"] == 858 + 1072.5, "the starting Combo: each crew's own drive"
    assert (_row(c, "Polish")["guys"], _row(c, "Epoxy")["guys"]) == (4, 5)
    o = s["open"]
    assert (o["job"]["carrier"], o["job"]["jobType"], o["job"]["kinds"]) == ("Epoxy", "epoxy", [["Polish", "off"], ["Epoxy", "base"]])
    epoxy, root = o["job"]["rows"]["Epoxy"], o["job"]["rows"]["Polish"]
    assert epoxy["count"] == 1 and (epoxy["row"]["guys"], epoxy["row"]["days"], epoxy["row"]["follow"], epoxy["row"]["cost"]) == (5, 6.5, "crew", 1072.5)
    assert root["count"] == 1 and root["row"] == EMPTY_ROW, "the off root keeps its row, its fill given back"
    assert o["job"]["pricedOn"] == ["Epoxy"] and o["job"]["travelDollars"] == 1072.5
    assert (o["job"]["lodging"], o["job"]["perDiem"]) == (True, True)
    assert "Travel Labor: off, $0" not in o["card"]["how"], "Lodging and Per Diem are on, and so is Travel Labor"
    assert "Travel Labor: 5 guys x 6.5 drive hours" in o["card"]["how"] and "= $1,072.50" in o["card"]["how"]
    assert (o["card"]["guysBox"], o["card"]["hoursBox"], o["card"]["hint"]) == ("5", "6.5", "Most guys on one labor line above: 5.")
    w = s["wichita"]["job"]
    assert _row(w, "Epoxy") == CREW_ROW and w["pricedOn"] == ["Epoxy"] and w["travelDollars"] == 858
    assert s["wichita"]["card"]["how"].count("Travel Labor: 4 guys x 6.5 drive hours") == 1
    r = s["reopened"]["job"]
    assert r["saves"] == 0 and r["asked"] == 0 and r["pricedOn"] == ["Epoxy"] and _row(r, "Epoxy") == CREW_ROW


def test_a_gyp_jobs_drive_fills_and_switched_to_polish_prices_the_drive_on_the_crew(ran):
    """ROUND 7 (Hanz, 2026-10-21, D2): a far Gyp bid's drive FILLS from the miles like the others, on its crew's size read off its crew lines (the pour, 4 guys entered in hours):
    4 x 6.5 x $33 = $858 beside the pour's $1,584, and the card says where its hours came from. (It was left empty, "the Gyp sheet works its own drive time", and a far Gyp quote
    priced no drive.) Switched to Polish, the root holds the older man-days row and the distance on file puts it on the crew's size: opened 3 guys, with the crew typed 4 x 6.5 x
    $33 = $858 (the first version said 49.5 x 6.5 x $33 = $10,617.75). The off Gyp section gives its fill back.

    Mutation: leave the older auto row on the man-days when the answer fills it."""
    s = ran["gypToPolish"]
    assert s["gyp"]["pricedOn"] == ['Gyp (USG 1-8")'] and s["gyp"]["travelDollars"] == 858 and s["gyp"]["distance"] == 190
    assert _row(s["gyp"], 'Gyp (USG 1-8")') == CREW_ROW and s["gyp"]["laborTotals"] == {'Gyp (USG 1-8")': 1584 + 858}, "the typed pour and the crew's own drive"
    assert s["gypCard"] == TRIP + ". A round trip for each mobilization typed on the Gyp card.", "a Gyp drive's trips are its mobilizations (round 7, part 4, P2)"
    o = s["open"]
    assert (o["job"]["carrier"], o["job"]["jobType"]) == ("Polish", "polish")
    assert o["job"]["saves"] == 0 and o["job"]["asked"] == 0
    assert (o["card"]["guysBox"], o["card"]["hoursBox"], o["job"]["travelDollars"]) == ("3", "6.5", 3 * 6.5 * 33)
    w = s["wichita"]
    assert _row(w["job"], "Polish") == CREW_ROW and w["job"]["pricedOn"] == ["Polish"] and w["job"]["travelDollars"] == 858
    assert w["card"]["hint"] == "Most guys on one labor line above: 4."
    assert _row(w["job"], 'Gyp (USG 1-8")') == EMPTY_ROW


def test_a_plain_reopen_changes_nothing(ran):
    """The other half of the rule: a saved bid opened as the job type it already is moves nothing, saves nothing and looks nothing up. The Epoxy
    bid keeps its filled row; the saved Epoxy to Combo bid and the saved Combo to Epoxy bid each reopen exactly as they were left (checked in
    their own tests above); and a switch that is only a reopen of the same sections fills nothing.

    Mutation: settle the rows on every restructure, even one that keeps the carrier (test_epoxy_estimate_page.py runs it on the page)."""
    p = ran["epoxyPlain"]
    assert (p["carrier"], p["saves"], p["asked"], p["jobType"]) == ("Epoxy", 0, 0, "epoxy")
    assert _row(p, "Epoxy") == CREW_ROW and p["pricedOn"] == ["Epoxy"]


def test_a_row_the_estimator_typed_on_a_base_that_stays_a_base_stays_its_own_and_the_cards_say_what_is_true(ran):
    """ROUND 7 (Hanz, 2026-10-21, D1). Epoxy's own Travel Labor was typed (3 guys, 5 hours: marked as theirs). It is the Epoxy crew's drive, and the switch to Combo keeps
    Epoxy a base, so it stays on Epoxy as typed ($495), and the Polish root, made a base, drives its own crew ($858): $1,353, two crews, two drives. (The third audit called
    $858 + $495 a double charge, under the one-drive law Hanz replaced; the typed row then went to the root and Epoxy's card said to leave its line empty.) The Epoxy sheet's
    Labor step shows its own typed boxes under the words that Hotel and Per Diem are charged once, on the Polish sheet, and typing over them, or clearing them, moves its own
    cost and nothing says the drive is charged elsewhere. A row the estimator typed on a section that is turned off is theirs: nothing gives it back.

    Mutation: carry the typed row off a base that stays a base; take a row back whatever was typed in it (BREAKS below)."""
    t = ran["typedToCombo"]
    assert t["job"]["pricedOn"] == ["Polish", "Epoxy"] and t["job"]["travelDollars"] == 858 + 495
    epoxy = _row(t["job"], "Epoxy")
    assert (epoxy["guys"], epoxy["days"], epoxy["auto"], epoxy["follow"], epoxy["typed"], epoxy["hoursTyped"], epoxy["cost"]) == (
        "3", "5", False, None, True, True, 495)
    assert _row(t["job"], "Polish") == CREW_ROW, "the root, a base now, drives its own crew"
    assert (t["rootCard"]["guysBox"], t["rootCard"]["hoursBox"], t["rootCard"]["hint"]) == ("4", "6.5", "Most guys on one labor line above: 4.")
    assert t["epoxyStep"] == {"stray": None, "travelNote": OWN_DRIVE_NOTE, "guysBox": "3", "hoursBox": "5", "cost": "$495"}
    assert t["typedHere"] == {"stray": None, "guysBox": "2", "hoursBox": "4", "cost": "$264"}
    assert t["cleared"] == {"stray": None, "guysBox": "", "hoursBox": "", "cost": "$0"}
    both = _row(t["bothTypedThenPolish"]["job"], "Epoxy")
    assert (both["guys"], both["days"], both["typed"], both["hoursTyped"], both["cost"]) == ("2", "4", True, True, 264), (
        "what the estimator typed on a section is theirs, and it is not given back when the section goes off")
    assert t["bothTypedThenPolish"]["job"]["pricedOn"] == ["Polish"], "an off section prices nothing"


def test_the_sheets_panels_base_change_settles_the_travel_rows_too(ran):
    """An Epoxy base with the Polish sheet an option (Epoxy's row filled, $858), made the combined pair on the Sheets panel: the carrier moves to the Polish root (the
    first base) and the same settling runs as for a job type switch. The root, an option made a base, holds the older row the tool filled, which its new role refills on
    the crew's size; Epoxy, still a base, keeps its own drive (round 7, D1): $858 + $858.

    Mutation: leave the settling out of makeBase, or hand it the section on show."""
    s = ran["sheetsCombined"]
    b, a = s["before"], s["after"]
    assert (b["carrier"], b["pricedOn"], b["travelDollars"]) == ("Epoxy", ["Epoxy"], 858)
    assert b["kinds"] == [["Polish", "option"], ["Epoxy", "base"]]
    assert (a["carrier"], a["jobType"], a["kinds"]) == ("Polish", "combo", [["Polish", "base"], ["Epoxy", "base"]])
    assert _row(a, "Polish") == CREW_ROW and _row(a, "Epoxy") == CREW_ROW
    assert a["pricedOn"] == ["Polish", "Epoxy"] and a["travelDollars"] == 1716
    assert s["card"]["guysBox"] == "4" and s["card"]["hoursBox"] == "6.5"


# ── 9. the third audit: every restructure settles the job's one drive ────────────────────────────
def test_epoxy_to_polish_to_combo_gives_the_off_sheet_its_fill_back_and_each_base_its_own_drive(ran):
    """THE HIGH FINDING, on the page, under round 7's law. A new far Epoxy bid switched to Polish (crew 4 x 12 typed on its Polishing) and then to Combo. At Polish the
    Epoxy section is OFF and gives back what the distance filled on it ($858: one drive). The audit found that fill kept on the off section and priced again when Combo
    turned it back on, the same crew's drive twice. At Combo the Epoxy sheet is a base again and is filled AFRESH for its own crew (round 7, D1): $858 + $858, two crews,
    and its Labor step says where its hours came from, never that they were typed. A plain reopen of the result moves and saves nothing.

    Mutation: leave the fill on a section that is off (BREAKS below)."""
    s = ran["epoxyPolishCombo"]
    p = s["polish"]
    assert (p["carrier"], p["pricedOn"], p["travelDollars"]) == ("Polish", ["Polish"], 858)
    assert _row(p, "Epoxy") == EMPTY_ROW, "Epoxy is OFF at this step and gave its fill back"
    c = s["combo"]
    assert (c["carrier"], c["jobType"], c["pricedOn"], c["travelDollars"]) == ("Polish", "combo", ["Polish", "Epoxy"], 1716)
    assert _row(c, "Polish") == CREW_ROW and _row(c, "Epoxy") == CREW_ROW
    e = s["epoxyStep"]
    assert e["note"] == TRIP + ". Type more trips for a long job." and e["stray"] is None and "typed" not in e["note"]
    assert e["cardCost"] == "$858" and e["hint"] == "Most guys on one labor line above: 4."
    r = s["reopened"]
    assert (r["saves"], r["asked"], r["pricedOn"], r["travelDollars"]) == (0, 0, ["Polish", "Epoxy"], 1716)
    assert _row(r, "Polish") == CREW_ROW and _row(r, "Epoxy") == CREW_ROW and s["card"]["guysBox"] == "4"


def test_combo_to_epoxy_to_polish_to_combo_prices_each_base_crews_own_drive(ran):
    """The audit's own example (combo to epoxy to polish to combo went $858, then $1,930.50 with the same crew charged twice). ROUND 7 (D1): each base crew's own drive at every
    step, on its own crew AS IT IS. The Combo starts with Polish's 4 ($858) and an Epoxy sheet whose crew is not typed yet (its drive filled, 0 guys, $0); Epoxy alone with its crew of
    5 typed, $1,072.50; Polish alone, $858 (Epoxy, off, gives its fill back); and the Combo again, Polish's 4 and Epoxy's 5 each their own: $858 + $1,072.50 = $1,930.50. (Until round
    7 one row was priced for the bigger crew: $858, $1,072.50, $858, $1,072.50.)

    Mutation: leave the fill on a section that is off (BREAKS below)."""
    steps = {x["at"]: x["job"] for x in ran["comboEpoxyPolishCombo"]}
    order = ("start", "epoxy", "polish", "combo")
    assert [steps[k]["pricedOn"] for k in order] == [["Polish"], ["Epoxy"], ["Polish"], ["Polish", "Epoxy"]]
    assert [steps[k]["travelDollars"] for k in order] == [858, 1072.5, 858, 1930.5]
    assert [steps[k]["carrier"] for k in order] == ["Polish", "Epoxy", "Polish", "Polish"]
    assert _row(steps["polish"], "Epoxy") == EMPTY_ROW and _row(steps["epoxy"], "Polish") == EMPTY_ROW, "the sheet that is off holds its row with its fill given back"
    assert _row(steps["combo"], "Epoxy")["guys"] == 5 and _row(steps["start"], "Epoxy")["guys"] == 0


def test_a_saved_combo_whose_epoxy_base_holds_its_drive_is_not_moved_by_a_reopen(ran):
    """A Combo whose Epoxy section holds the drive the distance filled (a bid saved before the take-back, which round 7 makes the right shape: D1, each base its own crew's drive),
    opened plainly: a plain reopen is not a switch, so nothing is saved, asked or emptied, and the Epoxy card says what the row IS: its own drive, where its hours came from, never
    that it was typed and never that it is charged elsewhere. (The audit caught the card saying "figures that were typed" over the tool's own $858; until round 7 the card called
    the row a leftover of the job's one drive.)

    Mutation: draw a base's drive as a leftover (BREAKS below)."""
    s = ran["staleSaved"]
    assert s["quiet"] == {"armed": 0, "saves": 0, "asked": 0}
    assert s["opened"]["pricedOn"] == ["Epoxy"] and _row(s["opened"], "Epoxy") == CREW_ROW, "the reopen leaves the row as it was saved"
    assert s["note"] == TRIP + ". Type more trips for a long job." and s["stray"] is None


def test_combo_made_polish_re_derives_the_guys_and_the_draft_saves_the_price_a_plain_reopen_shows(ran):
    """THE SECOND FINDING. A Combo (Polish's crew of 4, Epoxy's crew of 6) switched to Polish keeps the root as the carrier. Under the one-drive law the root's row read the
    Combo's bigger crew, 6 guys ($1,287), over a crew of 4, and the draft saved a price a plain reopen then disagreed with ($33,514 and $32,632 on the audit's bid). Since round 7
    the root's drive is the Polish crew's own on the Combo too (D1). The row is 4 x 6.5 x $33 = $858 when the page opens, the Epoxy sheet (off now) gives its drive back, the
    draft saves it, and the plain reopen of the saved draft shows the same price, the same rows, and arms and saves nothing.

    Mutation: leave the settling out of a restructure that keeps the carrier (BREAKS below)."""
    s = ran["comboToPolishSync"]
    # (round 7, D1: on the Combo each base drives its own crew, Polish's 4 and Epoxy's 6, where the one drive read the bigger 6 on Polish)
    assert (_row(s["combo"], "Polish")["guys"], _row(s["combo"], "Epoxy")["guys"]) == (4, 6) and s["combo"]["travelDollars"] == 858 + 6 * 6.5 * 33
    assert _row(s["opened"]["job"], "Epoxy") == EMPTY_ROW, "Epoxy, off now, gave its own drive back"
    o = s["opened"]
    assert _row(o["job"], "Polish") == CREW_ROW and o["job"]["travelDollars"] == 858
    assert (o["card"]["guysBox"], o["card"]["hint"]) == ("4", "Most guys on one labor line above: 4.")
    assert s["savedLump"] is not None and s["savedLump"] == s["reopenedLump"], "the draft saved the price a plain reopen of it shows"
    assert _row(s["reopened"], "Polish") == CREW_ROW and s["reopened"]["pricedOn"] == ["Polish"]
    assert s["quiet"] == {"armed": 0, "saves": 0}


def test_a_new_bids_distance_lookup_lands_whatever_is_on_show_or_has_replaced_the_model(ran):
    """THE THIRD FINDING. A NEW bid's distance lookup is in flight when the estimator opens another sheet's tab (or copies a sheet): the answer was dropped,
    leaving a 190 mile job with no distance, no Lodging, no Per Diem and no Travel Labor. The answer belongs to the whole model: it lands on the bid as it is
    NOW, on a Combo with Epoxy on show, on an Epoxy bid with its own tab clicked, and on the model a Sheets action replaced. The estimator's own typed miles
    still win over an answer that is on its way.

    Mutation: drop the answer when the section on show is not the one the lookup started on; let a late answer overwrite typed miles (BREAKS below)."""
    l = ran["lateLookup"]
    for name in ("stay", "epoxyTab", "epoxyBid", "sheets"):
        r = l[name]
        assert (r["distance"], r["lodging"], r["perDiem"], r["asked"]) == (190, True, True, 1), name
        assert (r["row"]["days"], r["row"]["seed"], r["row"]["follow"], r["row"]["auto"]) == (6.5, 6.5, "crew", True), name
    assert (l["epoxyTab"]["carrier"], l["epoxyBid"]["carrier"], l["sheets"]["carrier"]) == ("Polish", "Epoxy", "Polish")
    t = l["typedWins"]
    assert (t["distance"], t["lodging"], t["perDiem"]) == (10, False, False) and t["row"] == EMPTY_ROW and t["asked"] == 1


def test_what_the_estimator_typed_cleared_or_switched_off_follows_a_newly_seeded_carrier_and_is_not_filled(ran):
    """THE FOURTH FINDING, on the page. A Polish bid (crew 4 x 12, 190 miles) is switched to Epoxy: Epoxy is a NEW section with a blank Travel Labor row.
    Said nothing about, it is filled ($858). But the Travel Labor typed 3 x 5, a box cleared, and a row switched off all go to Epoxy with the job's drive
    and are NOT filled (all three read $858 on the audit's build), the Polish root gives its row back empty, the boxes show what was typed, and the saved
    bid reopens as it was left.

    Mutation: leave what the estimator said on the old carrier (BREAKS below)."""
    f = ran["newCarrierFollows"]
    a = f["auto"]["after"]["job"]
    assert _row(a, "Epoxy") == CREW_ROW and a["travelDollars"] == 858 and _row(a, "Polish") == EMPTY_ROW

    def epoxy(name, when="opened"):
        return _row(f[name][when]["job"], "Epoxy")
    t = epoxy("typed")
    assert (t["guys"], t["days"], t["typed"], t["hoursTyped"], t["cost"]) == ("3", "5", True, True, 495)
    assert (f["typed"]["opened"]["card"]["guysBox"], f["typed"]["opened"]["card"]["hoursBox"]) == ("3", "5")
    assert f["typed"]["opened"]["job"]["travelDollars"] == 495
    h = epoxy("clearHours")
    assert (h["days"], h["hoursTyped"], h["cost"]) == ("", True, 0) and f["clearHours"]["opened"]["card"]["hoursBox"] == ""
    assert epoxy("clearHours", "after")["guys"] == 4 and f["clearHours"]["after"]["job"]["travelDollars"] == 0, "the guys follow the crew, the empty hours price nothing"
    g = epoxy("clearGuys")
    assert (g["guys"], g["typed"], g["cost"]) == ("", True, 0) and f["clearGuys"]["opened"]["card"]["guysBox"] == ""
    o = epoxy("off", "after")
    assert (o["guys"], o["days"], o["cost"]) == (4, 6.5, 0) and f["off"]["after"]["job"]["pricedOn"] == [] and f["off"]["after"]["job"]["travelDollars"] == 0
    for name in ("typed", "clearHours", "clearGuys", "off"):
        assert _row(f[name]["opened"]["job"], "Polish") == EMPTY_ROW, name + ": the old carrier gave the row back"
        assert f[name]["reopened"]["job"]["saves"] == 0 and f[name]["reopened"]["job"]["asked"] == 0, name
        assert _row(f[name]["reopened"]["job"], "Epoxy") == _row(f[name]["after"]["job"], "Epoxy"), name + ": the saved bid reopens as it was left"


def test_the_note_on_the_second_bases_travel_names_the_carrier_by_its_name_on_screen(ran):
    """The Polish sheet was renamed "Main floor": the Epoxy sheet's travel note (its own drive, round 7) says the miles, Hotel and Per Diem are on the Main floor section, not
    on "Polish" (the key nobody sees).

    Mutation: name the carrier by its tab id (BREAKS below)."""
    r = ran["renamedCarrier"]
    assert r["carrier"] == "Polish" and r["stray"] is None
    assert r["note"] == OWN_DRIVE_NOTE.replace("Polish section", "Main floor section")


def test_only_travel_labors_card_sits_in_the_second_bases_travel_block(ran):
    """Another hours line on a base that does not carry the job's Hotel and Per Diem (a night shift, 5 guys x 3 hours) is an ordinary line: it stays with the labor lines, and only
    Travel Labor's own card is drawn in the sheet's travel block (round 7: the base's own drive). Nothing on it says the drive is charged elsewhere.

    Mutation: draw any hours line in the travel block (BREAKS below)."""
    n = ran["nightShiftLine"]
    assert n["inTravelBlock"] == [n["travelAt"]] and n["nightAt"] != n["travelAt"] and n["strayAt"] == [] and n["rows"] == 3


# ── 4. the answers get the whole model ───────────────────────────────────────────────────────────
def test_the_answers_are_handed_the_whole_model_whatever_section_is_on_show(ran):
    """The Labor step of the carrier (the Polish root of a Combo, with the miles box) is drawn, and then the Epoxy sheet is put on show WITHOUT a
    redraw, so M is a view of the Epoxy section while the box is still there to type in, press and clear. The estimator typing 190 miles fills the
    ROOT's Travel Labor (6.5 hours, the crew's 4: $858), the lookup's 300 miles moves the tool's hours to 10 ($1,320), and clearing the miles takes
    them back (empty, $0) and drops the distance. Handed a section view, the answer finds no Travel Labor row in the section on show and fills
    nothing: the same three lines on the page, each reverted in turn, go red here (the carrier settling after a job type switch, and after a base
    change, are held by the two tests above).

    Mutation: hand applyDistance, clearDistance or followDistance the section on show instead of the model."""
    w = ran["wholeModel"]
    assert w["noMilesBefore"] == EMPTY_ROW, "the starting Combo has no distance and an empty Travel Labor row"
    assert w["typed"]["distance"] == 190 and w["typed"]["row"] == CREW_ROW
    assert w["lookup"]["distance"] == 300 and w["lookup"]["row"]["days"] == 10 and w["lookup"]["row"]["seed"] == 10
    assert w["lookup"]["row"]["cost"] == 4 * 10 * 33
    assert w["cleared"]["before"] == CREW_ROW
    assert w["cleared"]["distance"] is None and w["cleared"]["after"]["days"] == "" and w["cleared"]["after"]["cost"] == 0
    assert w["cleared"]["after"]["seed"] == "", "the tool's own hours go back to empty"


# ── 6. an option copy's travel follows its own lines ─────────────────────────────────────────────
def test_an_option_copys_travel_labor_follows_its_own_lines_on_the_page(ran):
    """A copy of the Polish sheet (an option, priced apart) carries its own Travel Labor row, a copy of the carrier's (4 guys). 6 guys typed on the
    copy's Polishing are 6 on its Travel Labor, in the box, the hint and the note (6 x 6.5 x $33 = $1,287) while the job's crew, and the base's
    own row, stay 4 (the first version made the copy's 4: it followed the base crew). Its card is its own: no word that the drive is charged
    elsewhere. In a Combo the copy's words say "above" (its own lines), not "the base sheets'".

    Mutation: make an option's crew-following row follow the job's base crew; say the base sheets' lines for an option."""
    o = ran["optionCopy"]
    assert (o["id"], o["kind"], o["crewOfJob"]) == ("Copy1", "option", 4)
    assert o["copyBefore"] == CREW_ROW
    a = o["copyAfter"]
    assert (a["guys"], a["follow"], a["cost"]) == (6, "crew", 6 * 6.5 * 33)
    assert o["root"]["guys"] == 4 and o["root"]["cost"] == 858
    assert o["guysBox"] == "6" and o["hint"] == "Most guys on one labor line above: 6."
    assert o["note"].endswith("for each of the 6 guys on the labor lines above. Type more trips for a long job.")
    assert o["strayNote"] is None, "an option's Travel Labor is its own: the card does not say the drive is charged elsewhere"
    c = ran["comboOptionCopy"]
    assert (c["guys"], c["jobCrew"]) == (6, 4)
    # ...the words as the copy's card is FIRST DRAWN, before anything is typed (the repaint is checked after the typing, below): its own lines, "above"
    assert c["firstDrawn"]["hint"] == "Most guys on one labor line above: 4."
    assert c["firstDrawn"]["note"] == ("6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor lines "
                                       "above. Type more trips for a long job.")
    # ...and only Travel Labor's row of the Review carries the keyed trip sentence: no other labor line of the Review has one
    assert len(c["reviewDriveKeys"]) == 1 and c["reviewLaborRows"] == 2
    assert c["hint"] == "Most guys on one labor line above: 6."
    assert c["note"].endswith("for each of the 6 guys on the labor lines above. Type more trips for a long job.")
    assert c["review"] == "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 6 guys on the labor lines above"


# ── 7. the Review's trip sentence ────────────────────────────────────────────────────────────────
def test_a_late_distance_answer_repaints_the_reviews_trip_sentence_in_place(ran):
    """The estimator is on the Review step when the lookup lands (a slow service). The figures of the working were repainted in place already
    (26 hours, 4 x 6.5, $858); the trip sentence under the line's name was written once, at the first paint, and stayed empty until the step
    was left and entered again. It is a keyed figure now, drawn (empty) on Travel Labor's row from the start, so the repaint writes it.

    Mutation: write the sentence as plain text instead of a keyed figure."""
    r = ran["reviewLate"]
    assert r["step"] == 2
    assert r["before"] == {"q": "0", "tot": "$0", "drive": ""}, "before the answer: the figures are empty, and the keyed sentence is there to be written"
    assert r["after"] == {"q": "26", "tot": "$858", "drive": TRIP}


# ── 8. the notes ─────────────────────────────────────────────────────────────────────────────────
def test_the_notes_on_the_page_say_guys_for_typed_guys_and_empty_for_a_cleared_box(ran):
    """Through the page's own boxes, 190 miles and a crew of 4. Typing 2 in the Guys box: the card's hint says one round trip for each guy (not "Man-days
    from the tasks above: 48", which invited typing 48), the note says the guys are typed, the how-note says "2 guys (typed)" and the cost is
    2 x 6.5 x $33 = $429. Clearing the box: the note says the Guys box is empty and Travel Labor adds nothing until the guys are typed (it must never
    say the guys are typed over an empty box), the how-note says 0 guys and what to do. The crew's size, untouched, says its own words.

    Mutation: say the guys are typed whether or not the box holds a figure; word a typed count as man-days; put the man-days back in the hint."""
    n = ran["notes"]
    t = n["typed"]
    assert (t["row"]["guys"], t["row"]["typed"], t["row"]["auto"], t["row"]["cost"], t["box"]) == ("2", True, False, 2 * 6.5 * 33, "2")
    assert t["card"]["hint"] == "One round trip for each guy."
    assert t["card"]["note"]["text"].endswith("The guys are typed, so Travel Labor is your guys x those hours. Type more trips for a long job, or "
                                              "type over the hours to use your own.")
    assert "Travel Labor: 2 guys (typed) x 6.5 drive hours" in t["card"]["how"] and "man-days (typed)" not in t["card"]["how"]
    c = n["cleared"]
    assert (c["row"]["guys"], c["row"]["typed"], c["row"]["cost"], c["box"]) == ("", True, 0, "")
    assert "The guys are typed" not in c["card"]["note"]["text"]
    assert "The Guys box is empty, so Travel Labor adds nothing until you type the guys." in c["card"]["note"]["text"]
    assert c["card"]["hint"] == "One round trip for each guy."
    assert "Travel Labor: 0 guys x 6.5 drive hours" in c["card"]["how"] and "= $0.00. Type the guys." in c["card"]["how"]
    f = n["crewFollowing"]["card"] if "card" in n["crewFollowing"] else n["crewFollowing"]
    assert f["hint"] == "Most guys on one labor line above: 4." and f["note"]["text"].startswith(TRIP)


def test_nothing_on_these_cards_says_crew_or_labour(ran):
    """The estimate page's column is Guys, never Crew, and the English spelling of labor is not used (test_polish_estimate_page.py holds the page
    to it in general): every note, hint and how-note these scenarios drew, checked for the words."""
    words = []
    DRAWN = {"text", "hint", "how", "drive", "review", "note", "strayNote", "gypCard", "travelNote", "stray"}   # what the page wrote on screen, not the model's own markers

    def walk(v, key=None):
        if isinstance(v, str):
            if key in DRAWN:
                words.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, k if k in DRAWN or key in DRAWN else None)
        elif isinstance(v, list):
            for x in v:
                walk(x, key)

    walk(ran)
    assert len(words) > 30, "the sample is too small to be checking anything: %d strings" % len(words)
    text = "\n".join(words).lower()
    assert "crew" not in text, [w for w in words if "crew" in w.lower()][:3]
    assert "labour" not in text


# ── 10. the fourth audit (2026-10-20, of c0255de) ────────────────────────────────────────────────
def _filled_row(hours, guys=4):
    return {"guys": guys, "days": hours, "auto": True, "follow": "crew", "seed": hours, "typed": False, "hoursTyped": False, "cost": guys * hours * 33}


LOCAL_CARRIER_ROW = {"guys": 4, "days": "", "auto": True, "follow": "crew", "seed": "", "typed": False, "hoursTyped": False, "cost": 0}


def test_an_option_copys_drive_follows_the_miles_the_estimator_types(ran):
    """THE AUDIT'S MEDIUM FINDING, on the page. A far Polish bid (crew 4 x 12, Wichita 190 miles: the base is $32,632), its sheet copied as an option ($40,864, with the travel an option
    carries for itself). The estimator corrects the miles on the Labor step. Before, only the base's Travel Labor followed: at 50 miles the base fell to $30,872 and the option stayed
    at $32,632 (its 6.5 hour drive still priced in it), and at 300 miles the base moved to 10 hours ($33,582) while the option stayed at 6.5 ($40,864). Now the option's drive follows
    the miles on its own crew: 50 miles is $30,872 on both (the option's row is emptied, no marker), 300 miles is 4 x 10 x $33 = $1,320 on both ($33,582 and $41,771), the miles
    cleared is $30,872 on both again, and 190 typed again gives back the figures the bid started with. The draft the page saved reopens to the same prices and saves nothing.

    (The figures at 190 and 300 miles are the base's own Lodging and Per Diem more than the first audit's: since 2026-10-20 a far answer fills them with the labor's 48 man-days,
    $3,360 + $2,160 inside the markups, as the option's own lines always charged theirs, so on the same crew the base and its copy price the same: $40,864 and $41,771, where the
    base was $32,632 and $33,582 with its nights left empty. Nothing about the drive moved.)

    Mutation: leave the options out of an answer."""
    o = ran["optionFollowsMiles"]
    assert o["copyTab"] == "Copy1"
    expect = (
        ("start", 190, (40864, 40864), _filled_row(6.5), _filled_row(6.5)),
        ("local", 50, (30872, 30872), LOCAL_CARRIER_ROW, EMPTY_ROW),
        ("farther", 300, (41771, 41771), _filled_row(10), _filled_row(10)),
        ("cleared", None, (30872, 30872), LOCAL_CARRIER_ROW, EMPTY_ROW),
        ("again", 190, (40864, 40864), _filled_row(6.5), _filled_row(6.5)),
    )
    for step, miles, totals, base, option in expect:
        s = o[step]
        assert (s["miles"], (s["totals"]["base"], s["totals"]["option"])) == (miles, totals), step
        assert s["baseRow"] == base and s["optionRow"] == option, step
    r = o["reopened"]
    assert (r["totals"]["base"], r["totals"]["option"]) == (40864, 40864) and r["optionRow"] == _filled_row(6.5)
    assert r["saves"] == 0 and r["armed"] == 0, "a plain reopen of what was saved changes and saves nothing"


def test_a_demoted_bases_drive_follows_the_miles_as_an_option_on_the_page(ran):
    """THE AUDIT'S SECOND ROUTE. A Combo, Epoxy made the base on the Sheets panel (Polish is an option), the bid reopened and Epoxy's crew of 5 typed, Polish made the base again: Epoxy is
    an option holding the drive it was filled with (5 x 6.5 x $33) and the base is Polish's 4 x 6.5. The miles corrected to 50 took the base's drive away and left Epoxy's priced
    ($39,197 where the base is $30,872); the miles typed as 300 moved the base to 10 hours and left Epoxy's at 6.5 ($49,278). Now Epoxy's drive goes with the miles (its row
    emptied, $37,044) and comes back at 300 miles on its own 5 guys (5 x 10 x $33 = $1,650, $50,383).

    (The base's totals at 190 and 300 miles, $40,864 and $41,771, carry its own Lodging and Per Diem on the labor's 48 man-days now: a far answer fills them, 2026-10-20.)

    (Round 6, part 3, M2, 2026-10-21: Epoxy counts its nights from its own labor DOLLARS, Epoxy!B65, as every tab does now. With a drive of five guys x 6.5 hours, $1,072.50, its labor rounds up to
    $14,273, 50.0019 nights where 5 x 10 is 50, a dollar more on each of its Lodging and Per Diem: $49,281 at 190 miles where the head count priced it $49,278, and $48,440 for the Epoxy BASE of the
    added-sheet route where it was $48,437. At 300 miles the drive is a whole $1,650 and the count is 50 again.)

    Mutation: leave the options out of an answer."""
    d = ran["demotedOptionFollowsMiles"]
    assert d["epoxyBase"] == {"carrier": "Epoxy", "kinds": [["Polish", "option"], ["Epoxy", "base"]]}
    for step, totals, polish, epoxy in (
            ("start", (40864, 49281), _filled_row(6.5), _filled_row(6.5, 5)),
            ("local", (30872, 37044), LOCAL_CARRIER_ROW, EMPTY_ROW),
            ("farther", (41771, 50383), _filled_row(10), _filled_row(10, 5))):
        s = d[step]
        assert (s["carrier"], s["kinds"]) == ("Polish", [["Polish", "base"], ["Epoxy", "option"]]), step
        assert (s["totals"]["base"], s["totals"]["option"]) == totals, step
        assert s["polishRow"] == polish and s["epoxyRow"] == epoxy, step
    # THE ROUTE THAT NEEDED THE FIFTH AUDIT: the base demoted in favour of a sheet that was ADDED (a fresh sheet holds no Travel Labor row: only the carrier has one). The row used to
    # MOVE to the new carrier, so the demoted Polish had no drive to follow the miles with, in the session, whatever this test's name said. It keeps its row now (Epoxy took a copy):
    # 4 x 6.5 x $33 from the pick, emptied whole at 50 miles (no marker), 4 x 10 x $33 at 300, while Epoxy, the base, goes 5 x 6.5, nothing, 5 x 10. (`totals.base` is the root sheet's own
    # bid, the demoted Polish option here; `totals.option` is Epoxy's, the base.)
    a = d["addedSheet"]
    carrier_local = {"guys": 5, "days": "", "auto": True, "follow": "crew", "seed": "", "typed": False, "hoursTyped": False, "cost": 0}
    for step, totals, polish, epoxy in (
            ("start", (40864, 48440), _filled_row(6.5), _filled_row(6.5, 5)),
            ("local", (30872, 36165), EMPTY_ROW, carrier_local),
            ("farther", (41771, 49542), _filled_row(10), _filled_row(10, 5))):
        s = a[step]
        assert (s["carrier"], s["kinds"]) == ("Epoxy", [["Polish", "option"], ["Epoxy", "base"]]), step
        assert (s["totals"]["base"], s["totals"]["option"]) == totals, step
        assert s["polishRow"] == polish and s["epoxyRow"] == epoxy, step


def test_a_rate_typed_on_travel_labor_follows_the_job_to_the_new_carrier_on_the_page(ran):
    """The audit's own probe. $40 typed on Polish's Travel Labor (4 x 6.5 x $40 = $1,040, the guys and hours left on the distance), then the saved bid reopened as Epoxy, Combo and Polish
    with the crew typed on the carrier: the carrier's row is $1,040 each time (on Epoxy it read 4 x 6.5 x $33 = $858: the typed rate stayed behind on a row that was given back).

    Mutation: make a typed rate not the estimator's (test_polish_travel_hours.py runs it on the model too)."""
    r = ran["typedRateOnThePage"]
    assert r["polish"]["rate"] == "40" and r["polish"]["row"]["cost"] == 1040
    for job, carrier in (("epoxy", "Epoxy"), ("combo", "Polish"), ("polish", "Polish")):
        assert (r[job]["carrier"], r[job]["rate"], r[job]["row"]["cost"]) == (carrier, "40", 4 * 6.5 * 40), job
        assert (r[job]["row"]["guys"], r[job]["row"]["days"], r[job]["row"]["follow"]) == (4, 6.5, "crew"), job


def test_a_saved_bid_whose_active_sections_labor_is_not_a_list_opens(ran):
    """A saved bid is whatever was saved, and migrateModel carries a section under `tabs` through as it came. Epoxy's labor was a string, a number, an object or a boolean, with a stated
    takeoff (so nothing reseeds it): syncAutoGuys walked it with `.forEach` and threw as the page opened, as a Combo, as Polish (the bid it was saved as was still a Combo when the sync
    first ran) and as Epoxy, and the estimator got no estimate. The page opens, shows its estimate, and the carrier's drive is as it was saved (4 x 6.5 x $33).
    THE FIFTH AUDIT'S HALF: the sync's guard (laborLinesOf) let such a bid OPEN, and the first panel to touch the section threw when the estimator put it on show
    (`M.labor.forEach is not a function`). A section's labor that is not a list now reads as an empty one in the model (migrateModel), so the section is put on show
    and all three steps open. (The sync's own guard is held on the model, in test_polish_travel_hours.py: the page never hands it such a section any more.)

    Mutation: read a section's labor that is not a list as itself (the model); walking it unguarded in the sync is test_polish_travel_hours.py's."""
    c = ran["corruptLabor"]
    assert sorted(c) == ["boolean", "number", "object", "string"]
    for kind, jobs in c.items():
        assert sorted(jobs) == ["combo", "epoxy", "polish"], kind
        for job, page in jobs.items():
            assert page["opened"] is True and page.get("shown") is True, "%s opened as %s: %s" % (kind, job, page.get("error"))
            assert page["showedEpoxy"] is True, "%s opened as %s and threw when Epoxy was put on show: %s" % (kind, job, page.get("showError"))
        assert jobs["combo"]["carrier"] == "Polish" and jobs["combo"]["root"] == CREW_ROW and jobs["polish"]["root"] == CREW_ROW, kind
        assert jobs["epoxy"]["carrier"] == "Epoxy", kind


# ── red without the code: break a COPY of the page or the model one line at a time ───────────────
FILL_GUYS ='if (!row.guys_typed && row.guys_auto && !row.guys_follow && fills) row.guys_follow = "crew";'
CARRY_CALL = 'var carriedFrom = carriesOneDrive(model, was, drives, arrived) ? carryTravelRow(model, was.drives[0], was.kindOf(drives[0])) : "";'
TAKE_BACK_CALL = "takeBackStrayTravel(model, carriedFrom);"
STRAY_ROW = "if (rowOn(r) && travelRowIsAutoFilled(r)) clearQuantities(r);"
STRAY_GUARD = 'if (e.kind === "option" || !isObject(e.section) || drives.indexOf(e.tab) >= 0) return;'
SYNC = 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? ownCrewSize(model, lines) : manDays;'
ELSE_OWNED = 'return followOwnedRow(model, from, to) ? from : "";'
INIT_FOLLOW = "if (restructured) B.followDistance(ROOT, carrierBefore, kindsBefore);"
BASE_FOLLOW = "    B.followDistance(ROOT, carrierBefore, kindsBefore);"          # four spaces: init's call is `if (restructured) B.followDistance(...)`, one space before the B
LOOKUP_GUARD = '    if (!force && ROOT.distance && ROOT.distance.source === "typed") { paintDistance(); return; }'
CARRIER_NAME = "return B.sectionOf(ROOT, tab).label || tab;"
REVIEW_NAME = "var nameCell = B.isTravelRow(r)"
STRAY_IS = 'return B.sectionOf(ROOT, activeTab).kind !== "option" && !B.isDriveTab(ROOT, activeTab);'
OWN_DRIVE_IS = "try { return B.isDriveTab(ROOT, activeTab) && B.travelCarrier(ROOT) !== activeTab; } catch (err) { return false; }"
TRAVEL_BLOCK = 'if ((r || {}).id === "travel" && (carries || ownDrive)) travelRows += laborCard(r, i);'
CREW_WHERE = 'return "the labor lines above";'

# RETIRED IN ROUND 7 (Hanz's decisions of 2026-10-21, D1), with the law they held: the leftover row's words on a BASE (every base drives its own crew, so a base never holds a
# leftover; the words are drawn only on a section that is off, which the page never keeps on show: paintSections), and the four breaks of the `own` flag (the first drawing,
# the hint and note repaints, the Review's sentence), since every drive's words are its own section's crew's whether the row is an option's or a base's ("the labor lines of
# the base sheets" was the one drive of a Combo). The model's own words are held in test_polish_travel_hours.py. And the settling's own sync (followDistance's syncAutoGuys): since D1 a
# Combo made Polish keeps the root's drive on the Polish crew it already had, so no scenario here moves on it; a carried drive put on the new base's crew holds it, on the page in
# test_polish_travel_round7.py (a Combo saved under the one-drive law, made Epoxy) and on the model in test_polish_travel_hours.py.
BREAKS = {
    # --- the model, seen through the page ---
    "the older auto row the answer fills is left on the man-days": (
        "js/bid-model.js", FILL_GUYS, "void 0;",
        lambda g: g["epoxyToPolish"]["wichita"]["job"]["travelDollars"] != 858 or g["gypToPolish"]["wichita"]["job"]["travelDollars"] != 858),
    "the job's one drive does not follow its one base": (
        "js/bid-model.js", CARRY_CALL, 'var carriedFrom = "";',
        lambda g: g["newCarrierFollows"]["typed"]["opened"]["job"]["travelDollars"] != 495 or g["typedRateOnThePage"]["epoxy"]["rate"] != "40"),
    "a section that is off keeps the drive it was filled with": (
        "js/bid-model.js", TAKE_BACK_CALL, "void carriedFrom;",
        lambda g: _row(g["epoxyPolishCombo"]["polish"], "Epoxy") != EMPTY_ROW or _row(g["comboToEpoxy"]["open"]["job"], "Polish") != EMPTY_ROW),
    "a row is taken back whatever was typed in it": (
        "js/bid-model.js", STRAY_ROW, "if (rowOn(r)) clearQuantities(r);",
        lambda g: _row(g["typedToCombo"]["bothTypedThenPolish"]["job"], "Epoxy")["guys"] != "2"),
    "a restructure that keeps the carrier is not settled": (
        "js/polish-estimate.js", INIT_FOLLOW, "if (restructured && openingTab() !== carrierBefore) B.followDistance(ROOT, carrierBefore, kindsBefore);",
        lambda g: g["epoxyPolishCombo"]["combo"]["travelDollars"] != 1716 or _row(g["comboToPolishSync"]["opened"]["job"], "Epoxy") != EMPTY_ROW),
    "what the estimator typed is left on the old carrier": (
        "js/bid-model.js", ELSE_OWNED, 'return "";',
        lambda g: g["newCarrierFollows"]["typed"]["opened"]["job"]["travelDollars"] != 495),
    "what the estimator cleared is refilled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, 'return "";',
        lambda g: _row(g["newCarrierFollows"]["clearHours"]["opened"]["job"], "Epoxy")["days"] != ""),
    "a row the estimator switched off is filled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, 'return "";',
        lambda g: g["newCarrierFollows"]["off"]["after"]["job"]["travelDollars"] != 0),
    # --- round 7 (Hanz's decisions of 2026-10-21, D1): every base crew drives its own ---
    "a base other than the carrier gives its drive back (the one-drive law)": (
        "js/bid-model.js", STRAY_GUARD, 'if (e.kind === "option" || !isObject(e.section) || e.tab === carrier) return;',
        lambda g: g["epoxyToCombo"]["open"]["job"]["pricedOn"] != ["Polish", "Epoxy"] or g["sheetsCombined"]["after"]["travelDollars"] != 1716),
    "a drive follows the biggest crew of both bases": (
        "js/bid-model.js", SYNC, 'if (r && r.unit === "hours" && r.guys_auto) r.guys = followsCrew(r) ? crewSize(model) : manDays;',
        lambda g: g["optionCopy"]["copyAfter"]["guys"] != 6 or _row(g["comboToPolishSync"]["combo"], "Polish")["guys"] != 4),
    "a drive's guys are said to be the base sheets'": (
        "js/bid-model.js", CREW_WHERE, 'return baseCount(model) > 1 ? "the labor lines of the base sheets" : "the labor lines above";',
        lambda g: "base sheets" in (g["epoxyToCombo"]["epoxyStep"]["note"] or "") or g["comboOptionCopy"]["review"].endswith("base sheets")),
    "a base's own drive is drawn as a leftover of the job's one drive": (
        "js/polish-estimate.js", STRAY_IS, 'return B.sectionOf(ROOT, activeTab).kind !== "option" && B.travelCarrier(ROOT) !== activeTab;',
        lambda g: g["epoxyToCombo"]["epoxyStep"]["stray"] is not None or g["staleSaved"]["stray"] is not None),
    "an option's card is told the drive is charged elsewhere": (
        "js/polish-estimate.js", STRAY_IS, 'return B.sectionOf(ROOT, activeTab).kind !== "off" && !B.isDriveTab(ROOT, activeTab);',
        lambda g: g["optionCopy"]["strayNote"] is not None),
    "the second base is not told its guys drive on their own": (
        "js/polish-estimate.js", OWN_DRIVE_IS, "try { return false; } catch (err) { return false; }",
        lambda g: g["epoxyToCombo"]["epoxyStep"]["travelNote"] != OWN_DRIVE_NOTE),
    "the second base's travel card is drawn among its labor lines": (
        "js/polish-estimate.js", TRAVEL_BLOCK, 'if ((r || {}).id === "travel" && carries) travelRows += laborCard(r, i);',
        lambda g: g["nightShiftLine"]["inTravelBlock"] != [g["nightShiftLine"]["travelAt"]]),
    "any hours line is drawn in the second base's travel block": (
        "js/polish-estimate.js", TRAVEL_BLOCK, 'if (travelLike(r) && (carries || ownDrive)) travelRows += laborCard(r, i);',
        lambda g: g["nightShiftLine"]["inTravelBlock"] != [g["nightShiftLine"]["travelAt"]]),
    # --- the third audit (2026-10-20, of 7d32336) ---
    "the lookup's answer is dropped when another section is on show": (
        "js/polish-estimate.js", LOOKUP_GUARD,
        '    if (M !== ROOT || (!force && ROOT.distance && ROOT.distance.source === "typed")) { paintDistance(); return; }',
        lambda g: g["lateLookup"]["epoxyTab"]["distance"] != 190 or g["lateLookup"]["epoxyBid"]["distance"] != 190),
    "a late lookup overwrites the miles the estimator typed": (
        "js/polish-estimate.js", LOOKUP_GUARD, "    if (false) { paintDistance(); return; }",
        lambda g: g["lateLookup"]["typedWins"]["distance"] != 10),
    "the note names the carrier by its tab id": (
        "js/polish-estimate.js", CARRIER_NAME, "return tab;",
        lambda g: "Main floor" not in (g["renamedCarrier"]["note"] or "")),
    "the Review keys a trip sentence on every labor line": (
        "js/polish-estimate.js", REVIEW_NAME, "var nameCell = true",
        lambda g: len(g["comboOptionCopy"]["reviewDriveKeys"]) != 1),
    "a cleared guys box says the guys are typed": (
        "js/bid-model.js", "return head + (filledIn(row.guys)", "return head + (true",
        lambda g: "The guys are typed" in g["notes"]["cleared"]["card"]["note"]["text"]),
    "a typed count is worded as man-days": (
        "js/bid-model.js", 'lines.push("Travel Labor: " + qty(tr.guys) + (oldAuto ? " man-days" : " guys") +',
        'lines.push("Travel Labor: " + qty(tr.guys) + (crewFollow ? " guys" : " man-days") +',
        lambda g: "man-days (typed)" in g["notes"]["typed"]["card"]["how"]),
    "the hint under a typed Travel Labor box quotes the man-days": (
        "js/bid-model.js", 'if (isTravelRow(row) && !row.guys_auto) return "One round trip for each guy.";', "void 0;",
        lambda g: g["notes"]["typed"]["card"]["hint"] != "One round trip for each guy."),
    # --- the fourth audit (2026-10-20, of c0255de) ---
    "an answer never reaches an option's Travel Labor": (
        "js/bid-model.js", "followDistanceOptions(model, miles);", "void miles;",
        lambda g: g["optionFollowsMiles"]["local"]["totals"]["option"] != 30872 or g["demotedOptionFollowsMiles"]["local"]["totals"]["option"] != 37044),
    "clearing the miles never reaches an option's Travel Labor": (
        "js/bid-model.js", "followDistanceOptions(model, null);", "void model;",
        lambda g: g["optionFollowsMiles"]["cleared"]["totals"]["option"] != 30872),
    "a rate the estimator typed stays on the old carrier": (
        "js/bid-model.js", "return !!row && (!rowOn(row) || !travelRowIsHandsOff(row) || travelRateIsTyped(row));",
        "return !!row && (!rowOn(row) || !travelRowIsHandsOff(row));",
        lambda g: g["typedRateOnThePage"]["epoxy"]["rate"] != "40"),
    "a base demoted in favour of a fresh sheet loses its Travel Labor row to the new carrier": (
        "js/bid-model.js", '    try { demoted = sectionOf(out, fromTab).kind === "option"; } catch (err) { demoted = false; }', "    demoted = false;",
        lambda g: g["demotedOptionFollowsMiles"]["addedSheet"]["start"]["polishRow"] is None),
    "a section's labor that is not a list is not read as an empty one": (
        "js/bid-model.js", "      if (badLabor) section.labor = s.labor instanceof Array ? withoutHoles(s.labor) : [];", "      void badLabor;",
        lambda g: any(page.get("showedEpoxy") is not True for jobs in g["corruptLabor"].values() for page in jobs.values())),
    # --- the page ---
    "the lookup's answer is handed the section on show": (
        "js/polish-estimate.js", 'B.applyDistance(ROOT, { miles: miles, source: "google", key: key });',
        'B.applyDistance(M, { miles: miles, source: "google", key: key });',
        lambda g: g["wholeModel"]["lookup"]["row"]["days"] != 10),
    "the typed miles are handed the section on show": (
        "js/polish-estimate.js", 'B.applyDistance(ROOT, { miles: typedMiles, source: "typed", key: addressKey() });',
        'B.applyDistance(M, { miles: typedMiles, source: "typed", key: addressKey() });',
        lambda g: g["wholeModel"]["typed"]["row"]["days"] != 6.5),
    "the cleared miles are handed the section on show": (
        "js/polish-estimate.js", "B.clearDistance(ROOT);", "B.clearDistance(M);",
        lambda g: g["wholeModel"]["cleared"]["after"]["days"] != ""),
    "a job type switch settles the rows on the section on show": (
        "js/polish-estimate.js", INIT_FOLLOW, "if (restructured) B.followDistance(M, carrierBefore, kindsBefore);",
        lambda g: g["epoxyToPolish"]["open"]["job"]["rows"]["Polish"]["row"]["days"] != 6.5),
    "a base change settles the rows on the section on show": (
        "js/polish-estimate.js", BASE_FOLLOW, "    B.followDistance(M, carrierBefore, kindsBefore);",
        lambda g: g["sheetsCombined"]["after"]["pricedOn"] != ["Polish", "Epoxy"] or _row(g["sheetsCombined"]["after"], "Polish")["cost"] != 858),
    "the Review's trip sentence is plain text and not a keyed figure": (
        "js/polish-estimate.js", 'rv("lab." + i + ".drive", drive)', "esc(drive)",
        lambda g: not g["reviewLate"]["after"]["drive"]),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is a line the travel rules depend on, broken in a scratch copy of the page or the model; a FACT must change. A break that
    stops the harness, or makes a section throw, is not counted as noticed: it has no facts to compare."""
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
