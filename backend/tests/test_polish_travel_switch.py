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

THE THIRD AUDIT (2026-10-20, of 7d32336) is held here too, on the page, and by test_polish_travel_sequences.py over every sequence of switches:
  H  EVERY restructure settles the job's one drive, off sections included (Epoxy to Polish to Combo priced it twice, $1,716), and the Epoxy card no longer
     says its figures "were typed" over the tool's own.
  M  Combo made Polish re-derives the crew-following row's guys, so the draft saves the price a plain reopen shows; a new bid's distance lookup lands whatever
     section is on show; what the estimator typed, cleared or switched off follows the job's drive to a newly seeded carrier instead of being refilled.

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
            "comboToPolishSync", "lateLookup", "newCarrierFollows", "renamedCarrier", "nightShiftLine"]

CREW_ROW = {"guys": 4, "days": 6.5, "auto": True, "follow": "crew", "seed": 6.5, "typed": False, "hoursTyped": False, "cost": 858}
EMPTY_ROW = {"guys": "", "days": "", "auto": False, "follow": None, "seed": None, "typed": False, "hoursTyped": False, "cost": 0}
TRIP = "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor lines above"
STRAY_EMPTY = "The job's drive is charged once, on the Polish section. Leave this line empty: anything typed here is charged a second time."
STRAY_TYPED = ("The job's drive is charged once, on the Polish section. This line holds figures that were typed, so it was left as typed and "
               "still adds to this section's labor. Clear it, or remove the line, if the drive is already charged there.")
STRAY_FILLED = ("The job's drive is charged once, on the Polish section. This line still holds the drive the distance filled, so it adds to this "
                "section's labor as well. Clear it, or remove the line.")


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


def test_an_epoxy_job_switched_to_combo_prices_the_drive_once(ran):
    """The root is the new carrier (the first base) and Epoxy is STILL a base, so the row the distance filled on Epoxy was priced beside the root's:
    Travel charged twice ($858 on Epoxy and $10,617.75 on the root before the fix). Now the carrier move fills the root's row on the crew's size
    and TAKES BACK the one on Epoxy (guys and hours empty, no marker): one row priced, $858, whichever crew is typed. The Epoxy sheet's own Labor
    step still shows its leftover row, with the words that the job's drive is charged once, on the Polish section, and that the line is to be
    left empty. The saved bid holds exactly that, and a reopen of it as Combo changes and saves nothing.

    Mutation: leave the take-back out of the carrier move; leave the words off the leftover row's card."""
    s = ran["epoxyToCombo"]
    o = s["open"]
    assert (o["job"]["carrier"], o["job"]["jobType"], o["job"]["kinds"]) == ("Polish", "combo", [["Polish", "base"], ["Epoxy", "base"]])
    assert o["job"]["pricedOn"] == ["Polish"] and o["job"]["travelDollars"] == 858, "opened, the drive is already priced once"
    assert _row(o["job"], "Epoxy") == EMPTY_ROW and _row(o["job"], "Polish") == CREW_ROW
    assert o["card"]["hint"] == "Most guys on one labor line of the base sheets: 4."
    w = s["wichita"]["job"]
    assert w["pricedOn"] == ["Polish"] and w["travelDollars"] == 858
    assert _row(w, "Polish") == CREW_ROW and _row(w, "Epoxy") == EMPTY_ROW
    assert (w["rows"]["Polish"]["count"], w["rows"]["Epoxy"]["count"]) == (1, 1)
    assert w["laborTotals"] == {"Polish": 12672 + 396 + 858, "Epoxy": 12672}, "the Epoxy section carries its crew and no drive"
    e = s["epoxyStep"]
    assert e["note"] == STRAY_EMPTY and e["cardCost"] == "$0"
    assert e["genericHint"] is False, "the card does not promise a fill it will not get"
    assert e["hint"] == "One round trip for each guy."
    assert s["saved"]["Polish"] == CREW_ROW and s["saved"]["Epoxy"] == EMPTY_ROW
    r = s["reopened"]
    assert r["job"]["saves"] == 0 and r["job"]["asked"] == 0 and r["job"]["pricedOn"] == ["Polish"]
    assert _row(r["job"], "Polish") == CREW_ROW and _row(r["job"], "Epoxy") == EMPTY_ROW


def test_a_combo_switched_to_epoxy_carries_the_travel_labor_row_to_epoxy(ran):
    """THE AUDIT'S MEDIUM FINDING. A Combo (Polish root carrying the travel, Epoxy's crew 5 guys) switched to Epoxy: the root is off and Epoxy,
    which never had a Travel Labor row (the carrier holds the job's), is the carrier. The filled row was stranded on the off root while Lodging and
    Per Diem stayed on and the how-note said "Travel Labor: off, $0". Now the row goes WITH the carrier: Epoxy holds it, filled on its own crew
    (5 x 6.5 x $33 = $1,072.50, then 4 x 6.5 x $33 = $858 with a crew of 4), the root keeps none, and the how-note says the line and its guys.
    The saved bid reopens as it was left.

    Mutation: leave the carry out of the carrier move."""
    s = ran["comboToEpoxy"]
    c = s["combo"]
    assert c["carrier"] == "Polish" and c["pricedOn"] == ["Polish"] and _row(c, "Polish")["guys"] == 5, "the starting Combo: one crew of 5"
    o = s["open"]
    assert (o["job"]["carrier"], o["job"]["jobType"], o["job"]["kinds"]) == ("Epoxy", "epoxy", [["Polish", "off"], ["Epoxy", "base"]])
    epoxy, root = o["job"]["rows"]["Epoxy"], o["job"]["rows"]["Polish"]
    assert epoxy["count"] == 1 and (epoxy["row"]["guys"], epoxy["row"]["days"], epoxy["row"]["follow"], epoxy["row"]["cost"]) == (5, 6.5, "crew", 1072.5)
    assert root["count"] == 0 and root["row"] is None, "the row moved: the off root keeps none"
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


def test_a_gyp_job_is_never_filled_and_switched_to_polish_prices_the_drive_on_the_crew(ran):
    """A far Gyp bid fills nothing (the Gyp sheet works its own drive time; its crew is typed in hours), so the starting bid prices no drive. Switched
    to Polish, the root holds the older man-days row and the distance on file puts it on the crew's size: opened 3 guys, with the crew typed 4 x 6.5 x
    $33 = $858 (the first version said 49.5 x 6.5 x $33 = $10,617.75). The off Gyp section keeps its empty row.

    Mutation: leave the older auto row on the man-days when the answer fills it."""
    s = ran["gypToPolish"]
    assert s["gyp"]["pricedOn"] == [] and s["gyp"]["travelDollars"] == 0 and s["gyp"]["distance"] == 190
    assert _row(s["gyp"], 'Gyp (USG 1-8")') == EMPTY_ROW and s["gyp"]["laborTotals"] == {'Gyp (USG 1-8")': 1584}, "the typed pour is priced, the drive is not"
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


def test_a_row_the_estimator_typed_follows_the_job_s_drive_and_the_cards_say_what_is_true(ran):
    """THE THIRD AUDIT (2026-10-20). Epoxy's own Travel Labor was typed (3 guys, 5 hours: marked as theirs). It is the JOB'S drive, so the switch to Combo
    carries it to the Polish root, the new carrier: that Labor step shows the typed boxes, and Travel is priced once, as typed ($495). It used to be left
    on Epoxy and priced beside the root's own fill ($858 + $495 = $1,353). The Epoxy sheet gives its row back empty and its card says to leave the line
    empty. Typing figures in that leftover row changes what the card says (they say they were typed), live, and a row the estimator typed on a section
    that is turned off is theirs: nothing gives it back.

    Mutation: leave what the estimator typed on the old carrier; take a row back whatever was typed in it; leave the words off the card; never repaint them."""
    t = ran["typedToCombo"]
    assert t["job"]["pricedOn"] == ["Polish"] and t["job"]["travelDollars"] == 495
    polish = _row(t["job"], "Polish")
    assert (polish["guys"], polish["days"], polish["auto"], polish["follow"], polish["typed"], polish["hoursTyped"], polish["cost"]) == (
        "3", "5", False, None, True, True, 495)
    assert _row(t["job"], "Epoxy") == EMPTY_ROW, "the old carrier gave the row back"
    assert (t["rootCard"]["guysBox"], t["rootCard"]["hoursBox"], t["rootCard"]["hint"]) == ("3", "5", "One round trip for each guy.")
    assert t["epoxyStep"] == {"note": STRAY_EMPTY, "guysBox": "", "hoursBox": ""}
    assert t["typedHere"]["note"] == STRAY_TYPED
    assert t["cleared"]["note"] == STRAY_EMPTY
    both = _row(t["bothTypedThenPolish"]["job"], "Epoxy")
    assert (both["guys"], both["days"], both["typed"], both["hoursTyped"], both["cost"]) == ("2", "4", True, True, 264), (
        "what the estimator typed on a section is theirs, and it is not given back when the section goes off")
    assert t["bothTypedThenPolish"]["job"]["pricedOn"] == ["Polish"], "an off section prices nothing"


def test_the_sheets_panels_base_change_settles_the_travel_rows_too(ran):
    """An Epoxy base with the Polish sheet an option (Epoxy's row filled, $858), made the combined pair on the Sheets panel: the carrier moves to the
    Polish root (the first base) and the same settling runs as for a job type switch: the root's older row goes on the crew's size, Epoxy's filled
    row (still a base) is taken back, and the drive is priced once, $858.

    Mutation: leave the settling out of makeBase, or hand it the section on show."""
    s = ran["sheetsCombined"]
    b, a = s["before"], s["after"]
    assert (b["carrier"], b["pricedOn"], b["travelDollars"]) == ("Epoxy", ["Epoxy"], 858)
    assert b["kinds"] == [["Polish", "option"], ["Epoxy", "base"]]
    assert (a["carrier"], a["jobType"], a["kinds"]) == ("Polish", "combo", [["Polish", "base"], ["Epoxy", "base"]])
    assert _row(a, "Polish") == CREW_ROW and _row(a, "Epoxy") == EMPTY_ROW
    assert a["pricedOn"] == ["Polish"] and a["travelDollars"] == 858
    assert s["card"]["guysBox"] == "4" and s["card"]["hoursBox"] == "6.5"


# ── 9. the third audit: every restructure settles the job's one drive ────────────────────────────
def test_epoxy_to_polish_to_combo_prices_the_drive_once_and_the_epoxy_card_says_what_is_true(ran):
    """THE HIGH FINDING, on the page. A new far Epoxy bid switched to Polish (crew 4 x 12 typed on its Polishing) and then to Combo: the drive is $858 at
    BOTH steps. The take-back only ran when the carrier moved and only on a base, so Epoxy's filled row stayed on the section while Polish switched it
    off, and was priced again when Combo turned it back on beside the root's ($858 + $858 = $1,716). The Epoxy sheet's Labor step now says to leave its
    line empty; it said its figures "were typed" over the tool's own. A plain reopen of the result moves and saves nothing.

    Mutation: take back only from bases; leave the words off the card (BREAKS below)."""
    s = ran["epoxyPolishCombo"]
    p = s["polish"]
    assert (p["carrier"], p["pricedOn"], p["travelDollars"]) == ("Polish", ["Polish"], 858)
    assert _row(p, "Epoxy") == EMPTY_ROW, "Epoxy is OFF at this step and still gave its row back"
    c = s["combo"]
    assert (c["carrier"], c["jobType"], c["pricedOn"], c["travelDollars"]) == ("Polish", "combo", ["Polish"], 858)
    assert _row(c, "Polish") == CREW_ROW and _row(c, "Epoxy") == EMPTY_ROW
    e = s["epoxyStep"]
    assert e["note"] == STRAY_EMPTY and "typed" not in e["note"].replace("anything typed here", ""), "the card does not call the tool's figures typed"
    assert e["cardCost"] == "$0" and e["hint"] == "One round trip for each guy."
    r = s["reopened"]
    assert (r["saves"], r["asked"], r["pricedOn"], r["travelDollars"]) == (0, 0, ["Polish"], 858)
    assert _row(r, "Polish") == CREW_ROW and _row(r, "Epoxy") == EMPTY_ROW and s["card"]["guysBox"] == "4"


def test_combo_to_epoxy_to_polish_to_combo_prices_one_drive_on_the_crew_of_the_bid_as_it_is(ran):
    """The audit's own example (combo to epoxy to polish to combo went $858, then $1,930.50). One Travel Labor row is priced at every step, on the crew of
    the bid AS IT IS: 4 on the Combo (Polish's Polishing), 5 once the job is Epoxy and Epoxy's crew of 5 is typed, 4 again when Polish alone is the bid,
    and 5 on the Combo again (a Combo's crew is the biggest of both bases): $858, $1,072.50, $858, $1,072.50.

    Mutation: leave the settling out of a restructure that keeps the carrier; take back only from bases (BREAKS below)."""
    steps = {x["at"]: x["job"] for x in ran["comboEpoxyPolishCombo"]}
    order = ("start", "epoxy", "polish", "combo")
    assert [steps[k]["pricedOn"] for k in order] == [["Polish"], ["Epoxy"], ["Polish"], ["Polish"]]
    assert [steps[k]["travelDollars"] for k in order] == [858, 1072.5, 858, 1072.5]
    assert [steps[k]["carrier"] for k in order] == ["Polish", "Epoxy", "Polish", "Polish"]
    assert _row(steps["combo"], "Epoxy") == EMPTY_ROW and _row(steps["polish"], "Epoxy") == EMPTY_ROW


def test_a_bid_saved_with_the_filled_row_left_on_a_section_that_does_not_carry_the_travel_is_not_moved_by_a_reopen(ran):
    """A bid saved by the build before the take-back, a Combo whose Epoxy section still holds the filled row: a plain reopen is not a switch, so nothing
    is saved, asked or emptied, and the card says what the row IS: the drive the distance filled, still adding to the section's labor. (The audit
    caught the card saying "figures that were typed" over the tool's own $858.)

    Mutation: call the tool's figures typed on the card (BREAKS below)."""
    s = ran["staleSaved"]
    assert s["quiet"] == {"armed": 0, "saves": 0, "asked": 0}
    assert s["opened"]["pricedOn"] == ["Epoxy"] and _row(s["opened"], "Epoxy") == CREW_ROW, "the reopen leaves the row as it was saved"
    assert s["note"] == STRAY_FILLED and "were typed" not in s["note"]


def test_combo_made_polish_re_derives_the_guys_and_the_draft_saves_the_price_a_plain_reopen_shows(ran):
    """THE SECOND FINDING. A Combo (Polish's crew of 4, Epoxy's crew of 6: the job's crew is 6, $1,287) switched to Polish keeps the root as the carrier, so
    nothing re-synced the root's crew-following Travel Labor: it read 6 guys ($1,287) over a crew of 4, and the draft saved a price a plain reopen then
    disagreed with ($33,514 and $32,632 on the audit's bid). Now the row is the Polish crew's 4 x 6.5 x $33 = $858 when the page opens, the draft saves
    it, and the plain reopen of the saved draft shows the same price, the same rows, and arms and saves nothing.

    Mutation: leave the sync out of the settling (BREAKS below)."""
    s = ran["comboToPolishSync"]
    assert _row(s["combo"], "Polish")["guys"] == 6 and s["combo"]["travelDollars"] == 6 * 6.5 * 33
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


def test_the_card_of_a_leftover_row_names_the_carrier_by_its_name_on_screen(ran):
    """The Polish sheet was renamed "Main floor": the Epoxy sheet's leftover Travel Labor row says the drive is charged on the Main floor section, not
    on "Polish" (the key nobody sees).

    Mutation: name the carrier by its tab id (BREAKS below)."""
    r = ran["renamedCarrier"]
    assert r["carrier"] == "Polish"
    assert r["note"] == "The job's drive is charged once, on the Main floor section. Leave this line empty: anything typed here is charged a second time."


def test_only_travel_labors_row_says_the_drive_is_charged_elsewhere(ran):
    """Another hours line on a base that does not carry the travel (a night shift, 5 guys x 3 hours) is an ordinary line: it does not say the job's
    drive is charged once somewhere else. Only Travel Labor's own row does.

    Mutation: let any hours line say it (BREAKS below)."""
    n = ran["nightShiftLine"]
    assert n["strayAt"] == [n["travelAt"]] and n["nightAt"] != n["travelAt"] and n["rows"] == 3


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
    DRAWN = {"text", "hint", "how", "drive", "review", "note", "strayNote", "gypCard"}   # what the page wrote on screen, not the model's own markers

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


# ── red without the code: break a COPY of the page or the model one line at a time ───────────────
FILL_GUYS = 'if (!row.guys_typed && row.guys_auto && !row.guys_follow && fills) row.guys_follow = "crew";'
CARRY_CALL = "carryTravelRow(model, fromTab);"
TAKE_BACK_CALL = "takeBackStrayTravel(model);"
STRAY_ROW = "if (rowOn(r) && travelRowIsAutoFilled(r)) clearQuantities(r);"
STRAY_GUARD = 'if (e.kind === "option" || !isObject(e.section) || (e.tab === carrier && e.layout !== "gyp")) return;'
SYNC = "r.guys = followsCrew(r) ? (s.option ? ownCrewSize(model, s.section.labor) : crewSize(model)) : manDays;"
SYNC_CALL = "syncAutoGuys(model);"
ELSE_OWNED = "followOwnedRow(model, from, to);"
INIT_FOLLOW = "if (restructured) B.followDistance(ROOT, carrierBefore);"
BASE_FOLLOW = "    B.followDistance(ROOT, carrierBefore);"          # four spaces: init's call is `if (restructured) B.followDistance(...)`, one space before the B
LOOKUP_GUARD = '    if (!force && ROOT.distance && ROOT.distance.source === "typed") { paintDistance(); return; }'
CARRIER_NAME = "return B.sectionOf(ROOT, tab).label || tab;"
STRAY_ONLY_TRAVEL = 'var stray = travelRow && r.id === "travel" && holdsStrayTravel();'
FIRST_DRAWN = "var ownCrew = activeIsOption();     // first drawing"
REVIEW_NAME = "var nameCell = B.isTravelRow(r)"
STRAY_MARKUP = "? '<p class=\"hint trvnote\" data-trv-stray=\"' + i + '\">' + esc(B.strayTravelNote(carrierName(), r)) + '</p>'"
STRAY_IS = 'return B.sectionOf(ROOT, activeTab).kind === "base" && B.travelCarrier(ROOT) !== activeTab;'
HINT_REPAINT = "if (travelLike(r)) el.textContent = B.travelGuysHint(M, r, M.labor, ownCrew);"
NOTE_REPAINT = 'var note = r ? B.driveHoursNote(M, r, M.labor, ownCrew) : "";'
REVIEW_SENTENCE = "var drive = B.driveHoursSentence(M, r, activeIsOption());"
EMPTY_WORDS = 'return where + " Leave this line empty: anything typed here is charged a second time.";'

BREAKS = {
    # --- the model, seen through the page ---
    "the older auto row the answer fills is left on the man-days": (
        "js/bid-model.js", FILL_GUYS, "void 0;",
        lambda g: g["epoxyToPolish"]["wichita"]["job"]["travelDollars"] != 858 or g["gypToPolish"]["wichita"]["job"]["travelDollars"] != 858),
    "the row does not go with the carrier": (
        "js/bid-model.js", CARRY_CALL, "void fromTab;",
        lambda g: g["comboToEpoxy"]["open"]["job"]["rows"]["Epoxy"]["count"] != 1),
    "the old carrier keeps charging the drive": (
        "js/bid-model.js", TAKE_BACK_CALL, "void fromTab;",
        lambda g: g["epoxyToCombo"]["wichita"]["job"]["travelDollars"] != 858 or g["sheetsCombined"]["after"]["travelDollars"] != 858),
    "a row is taken back whatever was typed in it": (
        "js/bid-model.js", STRAY_ROW, "if (rowOn(r)) clearQuantities(r);",
        lambda g: _row(g["typedToCombo"]["bothTypedThenPolish"]["job"], "Epoxy")["guys"] != "2"),
    # --- the third audit (2026-10-20, of 7d32336) ---
    "the take-back only runs for a base": (
        "js/bid-model.js", STRAY_GUARD, 'if (e.kind !== "base" || !isObject(e.section) || (e.tab === carrier && e.layout !== "gyp")) return;',
        lambda g: _row(g["epoxyPolishCombo"]["polish"], "Epoxy") != EMPTY_ROW or g["epoxyPolishCombo"]["combo"]["travelDollars"] != 858),
    "a restructure that keeps the carrier is not settled": (
        "js/polish-estimate.js", INIT_FOLLOW, "if (restructured && openingTab() !== carrierBefore) B.followDistance(ROOT, carrierBefore);",
        lambda g: g["comboToPolishSync"]["opened"]["job"]["rows"]["Polish"]["row"]["guys"] != 4),
    "the settling leaves the guys on the old crew": (
        "js/bid-model.js", SYNC_CALL, "void model;",
        lambda g: g["comboToPolishSync"]["opened"]["job"]["rows"]["Polish"]["row"]["guys"] != 4 or g["comboToPolishSync"]["savedLump"] != g["comboToPolishSync"]["reopenedLump"]),
    "what the estimator typed is left on the old carrier": (
        "js/bid-model.js", ELSE_OWNED, "void from;",
        lambda g: g["typedToCombo"]["job"]["travelDollars"] != 495 or g["newCarrierFollows"]["typed"]["opened"]["job"]["travelDollars"] != 495),
    "what the estimator cleared is refilled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, "void from;",
        lambda g: _row(g["newCarrierFollows"]["clearHours"]["opened"]["job"], "Epoxy")["days"] != ""),
    "a row the estimator switched off is filled on the new carrier": (
        "js/bid-model.js", ELSE_OWNED, "void from;",
        lambda g: g["newCarrierFollows"]["off"]["after"]["job"]["travelDollars"] != 0),
    "the lookup's answer is dropped when another section is on show": (
        "js/polish-estimate.js", LOOKUP_GUARD,
        '    if (M !== ROOT || (!force && ROOT.distance && ROOT.distance.source === "typed")) { paintDistance(); return; }',
        lambda g: g["lateLookup"]["epoxyTab"]["distance"] != 190 or g["lateLookup"]["epoxyBid"]["distance"] != 190),
    "a late lookup overwrites the miles the estimator typed": (
        "js/polish-estimate.js", LOOKUP_GUARD, "    if (false) { paintDistance(); return; }",
        lambda g: g["lateLookup"]["typedWins"]["distance"] != 10),
    "the leftover row names the carrier by its tab id": (
        "js/polish-estimate.js", CARRIER_NAME, "return tab;",
        lambda g: "Main floor" not in (g["renamedCarrier"]["note"] or "")),
    "any hours line says the drive is charged elsewhere": (
        "js/polish-estimate.js", STRAY_ONLY_TRAVEL, "var stray = travelRow && holdsStrayTravel();",
        lambda g: g["nightShiftLine"]["strayAt"] != [g["nightShiftLine"]["travelAt"]]),
    "the first drawing of an option's card does not know it is an option's": (
        "js/polish-estimate.js", FIRST_DRAWN, "var ownCrew = false;     // first drawing",
        lambda g: g["comboOptionCopy"]["firstDrawn"]["hint"].endswith("base sheets: 4.")),
    "the Review keys a trip sentence on every labor line": (
        "js/polish-estimate.js", REVIEW_NAME, "var nameCell = true",
        lambda g: len(g["comboOptionCopy"]["reviewDriveKeys"]) != 1),
    "an option's crew-following row follows the base crew": (
        "js/bid-model.js", SYNC, "r.guys = followsCrew(r) ? crewSize(model) : manDays;",
        lambda g: g["optionCopy"]["copyAfter"]["guys"] != 6),
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
    "an option's guys are said to be the base sheets'": (
        "js/bid-model.js", 'return !own && baseCount(model) > 1 ? "the labor lines of the base sheets" : "the labor lines above";',
        'return baseCount(model) > 1 ? "the labor lines of the base sheets" : "the labor lines above";',
        lambda g: g["comboOptionCopy"]["hint"].endswith("base sheets: 6.") or g["comboOptionCopy"]["review"].endswith("base sheets")),
    "a leftover row says the same whatever it holds": (
        "js/bid-model.js", "if (row && (filledIn(row.guys) || filledIn(row.days))) {", "if (false) {",
        lambda g: g["typedToCombo"]["typedHere"]["note"] != STRAY_TYPED),
    "a leftover row is never told to stay empty": (
        "js/bid-model.js", EMPTY_WORDS, 'return where + " This line holds figures that were typed.";',
        lambda g: g["epoxyToCombo"]["epoxyStep"]["note"] != STRAY_EMPTY),
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
        "js/polish-estimate.js", INIT_FOLLOW, "if (restructured) B.followDistance(M, carrierBefore);",
        lambda g: g["epoxyToPolish"]["open"]["job"]["rows"]["Polish"]["row"]["days"] != 6.5),
    "a base change settles the rows on the section on show": (
        "js/polish-estimate.js", BASE_FOLLOW, "    B.followDistance(M, carrierBefore);",
        lambda g: g["sheetsCombined"]["after"]["pricedOn"] != ["Polish"] or _row(g["sheetsCombined"]["after"], "Polish")["cost"] != 858),
    "the Review's trip sentence is plain text and not a keyed figure": (
        "js/polish-estimate.js", 'rv("lab." + i + ".drive", drive)', "esc(drive)",
        lambda g: not g["reviewLate"]["after"]["drive"]),
    "a leftover row's card does not say where the drive is charged": (
        "js/polish-estimate.js", STRAY_MARKUP, "? ''",
        lambda g: g["epoxyToCombo"]["epoxyStep"]["note"] is None or g["typedToCombo"]["epoxyStep"]["note"] is None),
    "a leftover row is never recognised as one": (
        "js/polish-estimate.js", STRAY_IS, "return false;",
        lambda g: g["epoxyToCombo"]["epoxyStep"]["note"] is None),
    "an option's card is told the drive is charged elsewhere": (
        "js/polish-estimate.js", STRAY_IS, 'return B.sectionOf(ROOT, activeTab).kind !== "off" && B.travelCarrier(ROOT) !== activeTab;',
        lambda g: g["optionCopy"]["strayNote"] is not None),
    "a leftover row's words are never repainted": (
        "js/polish-estimate.js", "if (r) el.textContent = B.strayTravelNote(carrierName(), r);", "void r;",
        lambda g: g["typedToCombo"]["typedHere"]["note"] != STRAY_TYPED),
    "the hint repaint does not know the row is an option's": (
        "js/polish-estimate.js", HINT_REPAINT, "if (travelLike(r)) el.textContent = B.travelGuysHint(M, r, M.labor);",
        lambda g: g["comboOptionCopy"]["hint"].endswith("base sheets: 6.")),
    "the note repaint does not know the row is an option's": (
        "js/polish-estimate.js", NOTE_REPAINT, 'var note = r ? B.driveHoursNote(M, r, M.labor) : "";',
        lambda g: "base sheets" in g["comboOptionCopy"]["note"]),
    "the Review does not know the row is an option's": (
        "js/polish-estimate.js", REVIEW_SENTENCE, "var drive = B.driveHoursSentence(M, r);",
        lambda g: g["comboOptionCopy"]["review"].endswith("base sheets")),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is a line the one-drive rules depend on, broken in a scratch copy of the page or the model; a FACT must change. A break that
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
