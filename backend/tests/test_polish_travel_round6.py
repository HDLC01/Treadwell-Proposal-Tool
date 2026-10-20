"""ROUND 6, PART 1, THE NIGHTS (2026-10-20), held on the real estimate page: a Gyp crew is entered in HOURS and a Combo has TWO crews.

Round 5 (Hanz: "Fill them automatically") filled a far job's Lodging and Per Diem from the labor of the section that carries the job's travel and counted DAY rows only. Two things
were wrong with that, and each had a skeptic's script that priced it:

  N1  Kyle's Gyp tab counts its own nights: Gyp!B64 is `=IF(B5="No",((E52-E51)/C46)/10)` and per diem B65 is `=B64` (the labor dollars, less the drive's, over the first crew row's
      rate, over TEN hours). A Gyp crew is entered in hours, so v2's man-days (guys x days) counted it as nothing: round 5 made a far Gyp job's nights TYPED and said so. They are
      filled now, 4 guys for 120 hours = 480 man-hours = 48 nights = 48 days of per diem ($3,360 and $2,160), and the Gyp card says they fill in from the crew's hours, ten hours a night,
      as Kyle's Gyp sheet counts them. The Gyp DRIVE stays typed (the Gyp sheet works its own drive time per mobilization). F3 is the same bug in an option: a far Gyp option, or a copy
      of the Gyp sheet, priced $0 hotel and per diem under a note that says it carries its own (an identical copy was $10,536 under its base).
  N2  The follow figure was the CARRIER's man-days only, so a far Combo (Polish 4 x 12 and Epoxy 4 x 12) filled 48 nights under words that said "Kyle's way": $71,555 against
      $81,226 for the 96 Kyle types (13.5% short; all-years scan of his Dropbox: 136 of 140 far jobs with two or more priced sheets carry hotel on every sheet). The job's figure is the
      count of EVERY base section (everything in the lump sum); an option keeps pricing its own and an off section counts nothing.
  N4  Both travel cards' words are pinned, on a Gyp carrier and on every other (reverting the Per Diem Gyp words left the suite green), and so is the sentence above the travel block.

Each test drives js/polish-estimate.js whole (through tests/js/travel-round6-harness.js, on the real js/bid-model.js) and reads the page back; the last block breaks a COPY of the page or the
model one line at a time and requires a fact to change (never a crash). Every figure below is worked out BY HAND: a Gyp man-day is ten hours, every crew is paid $33 an hour, and a following
line equals the same bid with the nights typed (typed lines never reach the code under test).
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-round6-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]
SECTIONS = ["gyp", "gypOption", "gypCopy", "combo", "cards", "legacy", "direct", "words"]
GYP_TAB = 'Gyp (USG 1-8")'

# ── the words, said once ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
# The note under each travel card, and the sentence above the travel block. A Gyp carrier's say the nights fill in from the crew's hours, ten hours a night; every other carrier's say
# from the man-days (a Combo's too: the hint under the box says it is both base sheets').
CARD_LODGING = ("Overnight stays are expected at 70 miles or more from the office, and then the nights fill in from the man-days, a night for each, Kyle's way. "
                "Type your own to use them instead. Under 70 miles this line stays gray.")
CARD_PER_DIEM = ("Meals while the guys are away, expected at 70 miles or more from the office, and then the days fill in from the man-days, a day of per diem for each, Kyle's way. "
                 "Type your own to use them instead. Under 70 miles this line stays gray.")
GYP_CARD_LODGING = ("Overnight stays are expected at 70 miles or more from the office, and then the nights fill in from the crew's hours, 10 hours a night, "
                    "as Kyle's Gyp sheet counts them. Type your own to use them instead. Under 70 miles this line stays gray.")
GYP_CARD_PER_DIEM = ("Meals while the guys are away, expected at 70 miles or more from the office, and then the days fill in from the crew's hours, 10 hours a day, "
                     "a day of per diem for each, as Kyle's Gyp sheet counts them. Type your own to use them instead. Under 70 miles this line stays gray.")
CAP = ("Travel is expected when the job is 70 miles or more from the office. Under 70 miles all three lines below stay gray until you switch one on. "
       "On a far job Travel Labor fills in from the miles, and the nights and per diem days from the man-days; type over any of them to use your own.")
GYP_CAP = ("Travel is expected when the job is 70 miles or more from the office. Under 70 miles all three lines below stay gray until you switch one on. "
           "On a far Gyp job type the drive hours, because the Gyp sheet works its own drive time. The nights and per diem days fill in from the crew's hours, "
           "10 hours a night; type over any of them to use your own.")

# What sits under the Nights and Days boxes (and under the line's name on the Review) while a far answer's figure follows the labor.
GYP_FOLLOW_LODGING = "Follows the crew's hours on the labor lines above, 10 hours a night (48): a night for each, Kyle's way."
GYP_FOLLOW_PER_DIEM = "Follows the crew's hours on the labor lines above, 10 hours a night (48): a day of per diem for each, Kyle's way."
GYP_HOW = "Nights and per diem days follow the crew's hours on the labor lines above, 10 hours a night (48 now), a night and a day of per diem for each, Kyle's way."
COMBO_FOLLOW_LODGING = "Follows the man-days on the labor lines of the base sheets (96): a night for each, Kyle's way."
COMBO_FOLLOW_PER_DIEM = "Follows the man-days on the labor lines of the base sheets (96): a day of per diem for each, Kyle's way."
COMBO_HOW = "Nights and per diem days follow the man-days on the labor lines of the base sheets (96 now), a night and a day of per diem for each man-day, Kyle's way."
ONE_FOLLOW_LODGING = "Follows the man-days on the labor lines above (48): a night for each, Kyle's way."
ONE_FOLLOW_PER_DIEM = "Follows the man-days on the labor lines above (48): a day of per diem for each, Kyle's way."
ONE_HOW = "Nights and per diem days follow the man-days on the labor lines above (48 now), a night and a day of per diem for each man-day, Kyle's way."


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-800:]
    return last_json_line(proc.stdout)


class Ran(dict):
    """The harness's report. A section that threw says so when a test reads it, so one failing section fails the tests that read it and no other."""

    def __getitem__(self, key):
        got = dict.__getitem__(self, key)
        assert not (isinstance(got, dict) and "error" in got), "the %s section of the harness failed: %s" % (key, str(got["error"])[:700])
        return got


@pytest.fixture(scope="module")
def ran():
    require_node()
    return Ran(run())


def _line(qty):
    """A Lodging or Per Diem line a far answer filled: on, on auto, marked as following the labor, nobody's."""
    return {"on": True, "qty": qty, "auto": True, "follow": "labor", "typed": False, "hand": False}


EMPTY_DRIVE = {"guys": "", "days": "", "auto": False, "follow": None, "seed": None, "typed": False, "hoursTyped": False, "on": True, "cost": 0}


# ── N1. a Gyp crew is entered in hours: a far Gyp job's nights follow them ──────────────────────────────────────────────────────────────────────────────────
def test_a_far_gyp_job_fills_its_nights_from_the_crews_hours_ten_to_a_night(ran):
    """4 guys for 120 hours at $33 is 480 man-hours, 48 nights at ten hours a night (Gyp!B64: $15,840 / $33 / 10) and 48 days of per diem: $3,360 and $2,160 beside the drive, which stays
    typed (empty, $0). The boxes show 48, the words under them say it is the crew's hours at ten a night, the working says each line follows them and says once what that means, and the
    Review lists the two lines with their dollars and the same words. The price is the price of the same bid with the 48 and the 48 TYPED: $46,088 (it was $35,552 with the nights left at 0).

    Mutation: leave a Gyp carrier's nights typed again; charge the carrier from its own rows; leave the box empty; count the crew in people and not in the sheet's dollars; take every hours row off
    as the drive; divide by 8; say man-days where the hint and the working say the crew's hours."""
    g = ran["gyp"]
    assert g["saved"]["carrier"] == GYP_TAB
    assert g["saved"]["lodging"] == _line(48) and g["saved"]["perDiem"] == _line(48)
    assert g["saved"]["costs"] == {"lodging": 3360, "per_diem": 2160, "total": 5520}
    assert g["saved"]["drive"] == EMPTY_DRIVE, "a Gyp carrier's drive is typed: the distance fills nothing there"
    assert (g["labor"]["lodgingBox"], g["labor"]["perDiemBox"]) == ("48", "48")
    assert (g["labor"]["lodgingHint"], g["labor"]["perDiemHint"]) == (GYP_FOLLOW_LODGING, GYP_FOLLOW_PER_DIEM)
    how = g["labor"]["how"].split("\n")
    assert "Travel Labor: 0 guys x 0 drive hours x $33.00 = $0.00. Type the drive hours." in how
    assert "Lodging: 48 nights (follows the labor) x $70.00 = $3,360.00" in how and "Per Diem: 48 days (follows the labor) x $45.00 = $2,160.00" in how
    assert GYP_HOW in how
    r = g["review"]
    assert (r["lodgingQty"], r["lodgingTotal"], r["perDiemQty"], r["perDiemTotal"]) == ("48", "$3,360", "48", "$2,160")
    assert (r["lodgingNote"], r["perDiemNote"]) == (GYP_FOLLOW_LODGING, GYP_FOLLOW_PER_DIEM)
    assert g["typedFacts"]["costs"] == g["saved"]["costs"], "the typed twin is the same two lines"
    assert g["price"]["lump"] == g["typedPrice"]["lump"] == 46088, "the filled nights price the same as nights typed as the sheet counts them"
    assert g["price"]["sections"][GYP_TAB]["travel"] == 5520


def test_a_far_gyp_jobs_nights_follow_the_crew_as_it_changes(ran):
    """5 guys for 120 hours is 600 man-hours, 60 nights ($4,200 and $2,700); then 4 guys for 150 hours is 60 again. The boxes, the hints and the charge move with them.

    Mutation: leave a following line's figure where the first answer put it; leave the box without a figure."""
    for key in ("moreGuys", "moreHours"):
        m = ran["gyp"][key]
        assert (m["n"]["lodging"], m["n"]["perDiem"]) == (_line(60), _line(60)), key
        assert m["n"]["costs"] == {"lodging": 4200, "per_diem": 2700, "total": 6900}, key
        assert (m["l"]["lodgingBox"], m["l"]["perDiemBox"]) == ("60", "60"), key
        assert m["l"]["lodgingHint"] == "Follows the crew's hours on the labor lines above, 10 hours a night (60): a night for each, Kyle's way.", key


def test_a_gyp_box_the_estimator_typed_or_cleared_is_theirs_and_its_hint_counts_the_hours(ran):
    """Nights typed (10) and the per diem box cleared on a far Gyp bid: a later answer (300 miles) and a later change of the crew (5 guys for 120 hours) leave both as typed, and the hint
    under each says what the sheet would count, text only: 60 man-days (5 x 120 hours over ten).

    Mutation: refill a box the estimator cleared; leave a Gyp crew's hours out of the man-days a hint quotes; divide a Gyp crew's hours by 8."""
    t = ran["gyp"]["typed"]
    assert t["n"]["lodging"] == {"on": True, "qty": "10", "auto": False, "follow": None, "typed": True, "hand": False}
    assert t["n"]["perDiem"] == {"on": True, "qty": "", "auto": False, "follow": None, "typed": True, "hand": False}
    assert t["n"]["costs"] == {"lodging": 700, "per_diem": 0, "total": 700}
    assert (t["l"]["lodgingBox"], t["l"]["perDiemBox"]) == ("10", "")
    assert (t["l"]["lodgingHint"], t["l"]["perDiemHint"]) == ("Man-days from the tasks above: 60.",) * 2


def test_going_local_takes_a_far_gyp_jobs_figure_back_and_a_far_answer_fills_it_again(ran):
    """The miles corrected to 50: both lines switch off and the figure the crew filled goes back to empty (off auto, no marker); 190 again fills 48 and 48.

    Mutation: keep the figure the labor filled when the job goes local."""
    loc = ran["gyp"]["local"]["n"]
    empty = {"on": False, "qty": "", "auto": False, "follow": None, "typed": False, "hand": False}
    assert loc["lodging"] == empty and loc["perDiem"] == empty and loc["costs"]["total"] == 0
    assert (ran["gyp"]["local"]["l"]["lodgingBox"], ran["gyp"]["local"]["l"]["perDiemBox"]) == ("", "")
    assert ran["gyp"]["local"]["l"]["lodgingHint"] == "Man-days from the tasks above: 48."
    far = ran["gyp"]["farAgain"]["n"]
    assert far["lodging"] == _line(48) and far["perDiem"] == _line(48) and far["costs"]["total"] == 5520


def test_a_saved_far_gyp_bid_is_never_moved_by_opening_it(ran):
    """The draft a far Gyp bid saved, reopened plain: the lines still follow (48 and 48), nothing is armed, saved or asked, and the price is the one it was saved at. A far bid saved with its two
    lines ON and BLANK (what a bid held before an answer filled them) is not filled by being opened either: the lines stay blank, nothing is armed, saved or asked, and it opens at $35,552, the
    figure the page of 619f092 gives the same draft.

    Mutation: fill the lines when a bid is opened."""
    r = ran["gyp"]["reopened"]
    assert r["n"]["lodging"] == _line(48) and r["n"]["perDiem"] == _line(48)
    assert (r["armed"], r["saves"], r["asked"]) == (0, 0, 0)
    assert r["price"] == ran["gyp"]["price"]["lump"] == 46088
    b = ran["gyp"]["savedBlank"]
    blank = {"on": True, "qty": "", "auto": False, "follow": None, "typed": False, "hand": False}
    assert b["n"]["lodging"] == blank and b["n"]["perDiem"] == blank and b["quiet"] == {"armed": 0, "saves": 0, "asked": 0}
    assert b["price"] == 35552


# ── F3. a far Gyp option, and a copy of the Gyp sheet, carry their own nights ──────────────────────────────────────────────────────────────────────────────
def test_a_far_gyp_option_prices_its_own_hotel_and_per_diem_from_its_own_crew_hours(ran):
    """A far Polish bid (4 x 12) with a Gyp sheet added as an option, 4 guys for 120 hours: the option's own 48 nights and 48 days are $3,360 and $2,160 ($5,520), as the Epoxy option beside it
    (4 guys for 12 days) is. The Review of the option lists them. The job's own lines (the Polish base's 48) are not the option's: they follow the base. Before, the option's two lines were $0 under a
    note that says it carries its own, and its total was $35,552 where the same sheet carries $46,088.

    Mutation: charge a Gyp option nothing for its hours crew; count its hours over 8."""
    o = ran["gypOption"]
    assert o["gyp"]["layout"] == "gyp" and o["gyp"]["labor"] == 15840
    assert o["gyp"]["nights"] == pytest.approx(48) and o["gyp"]["own"] == {"lodging": 3360, "per_diem": 2160, "total": 5520}
    assert o["gyp"]["travel"] == 5520 and o["gyp"]["total"] == 46088
    r = o["gyp"]["review"]
    assert (r["lodgingQty"], r["lodgingTotal"], r["perDiemQty"], r["perDiemTotal"]) == ("48", "$3,360", "48", "$2,160")
    assert o["gyp"]["baseTravel"] == 5520 and o["gyp"]["jobLines"]["lodging"] == _line(48), "the base's own lines still follow the base"
    e = o["epoxy"]
    assert e["travel"] == 5520 and e["own"] == {"lodging": 3360, "per_diem": 2160, "total": 5520} and e["nights"] == 48, "the Epoxy option beside it is unchanged"
    assert (e["review"]["lodgingQty"], e["review"]["lodgingTotal"]) == ("48", "$3,360")


def test_an_identical_copy_of_a_far_gyp_sheet_prices_the_same_as_its_base(ran):
    """The audit's script: a far Gyp bid (4 x 120 hours, the nights typed as 48 and 48), then the Gyp sheet copied as an alternate. The copy is an option and carries its own 48 nights and 48 days
    ($5,520), so an identical sheet is the same price as its base to the dollar ($46,088); it was $35,552, $10,536 under.

    Mutation: charge a copy of the Gyp sheet no hotel."""
    c = ran["gypCopy"]
    assert c["carrier"] == GYP_TAB and c["copy"] == "Copy1" and c["kinds"] == [["Polish", "off"], [GYP_TAB, "base"], ["Copy1", "option"]]
    assert c["alone"] == {"total": 46088, "travel": 5520}
    assert c["base"] == {"total": 46088, "travel": 5520, "labor": 15840}
    assert c["copied"] == {"total": 46088, "travel": 5520, "labor": 15840}


# ── N2. a Combo's nights are the man-days of every base section ────────────────────────────────────────────────────────────────────────────────────────────
def test_a_far_combo_fills_the_nights_of_both_crews(ran):
    """Wichita, Polish 4 x 12 and Epoxy 4 x 12: 48 + 48 = 96 nights and 96 days of per diem ($6,720 and $4,320, $11,040 with the one $858 drive), on the Polish carrier. The hint under each box, the
    working and the Review all say the count is the man-days of the base sheets and not of the sheet on show. The price is the price of the same bid with 96 and 96 typed, $81,226 (it was
    $71,555, 13.5% short, under words that said "Kyle's way").

    Mutation: count only the carrier's labor; leave the base sheets out of the words."""
    c = ran["combo"]
    assert c["carrier"] == "Polish" and c["bases"] == [["Polish", "base"], ["Epoxy", "base"]]
    assert c["n"]["lodging"] == _line(96) and c["n"]["perDiem"] == _line(96)
    assert c["n"]["costs"] == {"lodging": 6720, "per_diem": 4320, "total": 11040}
    assert c["n"]["drive"] == {"guys": 4, "days": 6.5, "auto": True, "follow": "crew", "seed": 6.5, "typed": False, "hoursTyped": False, "on": True, "cost": 858}, "the drive stays ONE, on the carrier"
    assert (c["l"]["lodgingBox"], c["l"]["perDiemBox"]) == ("96", "96")
    assert (c["l"]["lodgingHint"], c["l"]["perDiemHint"]) == (COMBO_FOLLOW_LODGING, COMBO_FOLLOW_PER_DIEM)
    how = c["l"]["how"].split("\n")
    assert "Lodging: 96 nights (follows the labor) x $70.00 = $6,720.00" in how and "Per Diem: 96 days (follows the labor) x $45.00 = $4,320.00" in how
    assert COMBO_HOW in how
    r = c["review"]
    assert (r["lodgingQty"], r["lodgingTotal"], r["perDiemQty"], r["perDiemTotal"]) == ("96", "$6,720", "96", "$4,320")
    assert (r["lodgingNote"], r["perDiemNote"]) == (COMBO_FOLLOW_LODGING, COMBO_FOLLOW_PER_DIEM)
    assert c["price"]["lump"] == c["typedPrice"]["lump"] == 81226 and c["price"]["rootTravel"] == 11040


def test_a_typed_quantity_on_a_combo_is_told_what_both_base_sheets_count(ran):
    """The hint under a Nights or Days box the estimator typed over says what the sheet would count, text only: 96, the man-days of the base sheets (it said 48, the Polish sheet's alone, which
    invited typing the carrier's figure on a job whose hotel is on both sheets). The working's reference line says the same.

    Mutation: quote only the carrier's man-days under a typed box."""
    h = ran["combo"]["typedHint"]
    assert (h["lodging"], h["perDiem"]) == ("Man-days from the labor lines of the base sheets: 96.",) * 2
    how = h["how"].split("\n")
    assert "Lodging: 96 nights (typed) x $70.00 = $6,720.00" in how
    assert "For reference, the man-days on the labor lines of the base sheets are 96." in how


def test_the_nights_follow_either_base_crew_as_it_changes(ran):
    """The Epoxy crew to 5 guys (60 man-days) moves the figure to 108 (the Polish sheet's 48, which the sheet counts as 48.0019 once the drive is five guys' $1,072.50, and the Epoxy 60): 108.0019
    nights x $70 = $7,560.13, rounded up to $7,561, and x $45 = $4,860.09, up to $4,861. The Polish crew to 6 guys after it is 72 + 60 = 132 ($9,240 and $5,940 with the drive at $1,287), and the box,
    the hints and the working move with it.

    Mutation: leave the other base's labor out of the figure."""
    e = ran["combo"]["moreEpoxy"]
    assert e["manDays"] == [48, 60]
    assert e["n"]["lodging"] == _line(108) and e["n"]["perDiem"] == _line(108)
    assert e["n"]["costs"] == {"lodging": 7561, "per_diem": 4861, "total": 12422}
    p = ran["combo"]["morePolish"]
    assert p["n"]["lodging"] == _line(132) and p["n"]["costs"] == {"lodging": 9240, "per_diem": 5940, "total": 15180}
    assert (p["l"]["lodgingBox"], p["l"]["perDiemBox"]) == ("132", "132")
    assert p["l"]["lodgingHint"] == "Follows the man-days on the labor lines of the base sheets (132): a night for each, Kyle's way."
    assert "Nights and per diem days follow the man-days on the labor lines of the base sheets (132 now), a night and a day of per diem for each man-day, Kyle's way." in p["l"]["how"].split("\n")


def test_an_off_section_counts_nothing_and_the_words_go_back_to_one_sheet(ran):
    """The job type switched from Combo to Polish alone: the Epoxy section goes off, the figure is the Polish crew's 48, and the hint and the working say "the labor lines above" again.

    Mutation: count a section that is off."""
    p = ran["combo"]["polishOnly"]
    assert p["kinds"] == [["Polish", "base"], ["Epoxy", "off"]]
    assert p["n"]["lodging"] == _line(48) and p["n"]["costs"] == {"lodging": 3360, "per_diem": 2160, "total": 5520}
    assert (p["l"]["lodgingBox"], p["l"]["lodgingHint"], p["l"]["perDiemHint"]) == ("48", ONE_FOLLOW_LODGING, ONE_FOLLOW_PER_DIEM)
    assert ONE_HOW in p["l"]["how"].split("\n")
    assert p["cards"]["lodging"] == CARD_LODGING


def test_an_option_beside_a_far_combo_keeps_pricing_its_own_and_is_not_in_the_jobs_figure(ran):
    """A Seal sheet (2 guys for 5 days = 10 man-days) beside the far Combo is priced apart: its own 10 nights and 10 days ($700 and $450) and the job's lines stay 96.

    Mutation: add an option's labor to the job's figure."""
    o = ran["combo"]["withOption"]
    assert o["sealRow"] == "seal-install" and o["optionNights"] == pytest.approx(10)
    assert o["optionOwn"] == {"lodging": 700, "per_diem": 450, "total": 1150} and o["optionTravel"] == 1150
    assert o["n"]["lodging"] == _line(96) and o["n"]["costs"]["total"] == 11040 and o["rootTravel"] == 11040


def test_a_saved_combo_is_never_moved_by_opening_it(ran):
    """The draft a far Combo saved, reopened plain: the lines follow 96 and 96, nothing is armed, saved or asked, and the price is the one it was saved at ($81,226). The same Combo saved with its
    lines on and blank is not filled by being opened: it stays blank and opens at $63,323, the figure the page of 619f092 gives that draft.

    Mutation: fill the lines when a bid is opened."""
    r = ran["combo"]["reopened"]
    assert r["n"]["lodging"] == _line(96) and (r["armed"], r["saves"], r["asked"]) == (0, 0, 0) and r["price"] == 81226
    b = ran["combo"]["savedBlank"]
    blank = {"on": True, "qty": "", "auto": False, "follow": None, "typed": False, "hand": False}
    assert b["n"]["lodging"] == blank and b["n"]["perDiem"] == blank and b["quiet"] == {"armed": 0, "saves": 0, "asked": 0}
    assert b["price"] == 63323


# ── N4. the words on BOTH cards, on a Gyp carrier and on every other ───────────────────────────────────────────────────────────────────────────────────────
def test_both_travel_cards_say_where_their_quantity_comes_from_on_a_gyp_carrier_and_on_every_other(ran):
    """The Lodging card and the Per Diem card each say it (a Gyp carrier's: the crew's hours, ten hours a night, as Kyle's Gyp sheet counts them; every other carrier's: the man-days), and the sentence
    above the travel block keeps the Gyp DRIVE honest (typed, because the Gyp sheet works its own drive time) while saying the nights fill in. Round 5's Gyp words ("Type the nights: a Gyp crew
    is entered in hours, so they do not fill in by themselves") are gone.

    Mutation: revert the Lodging Gyp words; revert the Per Diem Gyp words; revert the Gyp sentence above the block; revert the other carriers' Lodging words; their Per Diem words; their sentence."""
    c = ran["cards"]
    assert c["gyp"]["carrier"] == GYP_TAB and c["polish"]["carrier"] == "Polish" and c["epoxy"]["carrier"] == "Epoxy"
    assert c["gyp"]["lodging"] == GYP_CARD_LODGING and c["gyp"]["perDiem"] == GYP_CARD_PER_DIEM and c["gyp"]["cap"] == GYP_CAP
    for k in ("polish", "epoxy"):
        assert c[k]["lodging"] == CARD_LODGING and c[k]["perDiem"] == CARD_PER_DIEM and c[k]["cap"] == CAP, k
    for words in (c["gyp"]["lodging"], c["gyp"]["perDiem"], c["gyp"]["cap"]):
        assert "do not fill in by themselves" not in words


# ── a bid saved before this change prices as it did ────────────────────────────────────────────────────────────────────────────────────────────────────────
# Pinned from the page of 619f092, the parent of this change (the same fixtures run over `git archive 619f092 frontend`): the totals and travel a bid saved on the OLDER auto (on auto, no marker)
# opened at then, and the same Combo with its nights typed. Nothing is converted: the older line follows the carrier's man-days, day rows only, as it always did.
LEGACY_PINNED = {
    "gypOlderAuto": {"lump": 35552, "travel": 0, "qty": 0},
    "polishOlderAuto": {"lump": 40864, "travel": 5520, "qty": 48},
    "comboOlderAuto": {"lump": 71555, "travel": 5520, "qty": 48},
}


@pytest.mark.parametrize("name", sorted(LEGACY_PINNED))
def test_a_bid_saved_on_the_older_auto_opens_at_the_price_it_was_saved_at(ran, name):
    """The older auto lines (a bid saved before 2026-10-12: on auto, no marker) are never converted, in either direction: a Gyp carrier's still count day rows only (its crew in hours is none: $0 hotel, as
    it was saved), a Polish carrier's its own 48, and a Combo's the CARRIER's 48 (not the 96 a line that follows counts). Nothing is armed or saved by opening one.

    Mutation: count a crew's hours on the older auto line; sum the bases on the older auto line."""
    got = ran["legacy"][name]
    pinned = LEGACY_PINNED[name]
    assert got["lump"] == pinned["lump"] and got["travel"] == pinned["travel"], (name, got)
    assert got["lodging"]["qty"] == pinned["qty"] and got["lodging"]["follow"] is None and got["lodging"]["auto"] is True, (name, got["lodging"])
    assert got["perDiem"]["qty"] == pinned["qty"] and got["perDiem"]["follow"] is None, (name, got["perDiem"])
    assert (got["armed"], got["saves"]) == (0, 0), (name, got)


def test_nights_the_estimator_typed_on_a_combo_are_theirs_whatever_the_crews(ran):
    """The same Combo with 96 and 96 typed: typed is the estimator's, $81,226, $11,040 of hotel and per diem, and nothing converts it.

    Mutation: let a typed quantity follow the labor."""
    got = ran["legacy"]["comboTyped"]
    assert got["lump"] == 81226 and got["travel"] == 11040
    assert got["lodging"] == {"on": True, "qty": "96", "auto": False, "follow": None, "typed": True, "hand": False}


def test_a_line_that_follows_and_one_on_the_older_auto_are_each_charged_their_own_way(ran):
    """The same Combo with its Lodging following the labor and its Per Diem on the older auto (no marker): the Lodging is the two crews' 96 ($6,720) and the Per Diem is the carrier's own 48
    ($2,160), as an older line always was. The marker, not the bid, says which rule a line is charged by.

    Mutation: charge an older auto line the job's figure."""
    m = ran["legacy"]["comboOneFollows"]
    assert m["lodging"] == _line(96) and m["perDiem"] == {"on": True, "qty": 48, "auto": True, "follow": None, "typed": False, "hand": False}
    assert m["costs"] == {"lodging": 6720, "per_diem": 2160, "total": 8880}


# ── the model's own count: a crew in hours, each profile's divisor, the sheet's dollars ───────────────────────────────────────────────────────────────────
def test_the_man_days_count_a_crew_in_hours_only_when_a_tab_says_what_a_night_is_worth(ran):
    """travelManDays of the rows alone is what it always was (an hours row counts nothing: pinned by the chain golden). Told the hours a night is worth (the section's profile divisor), a crew row
    entered in hours counts guys x hours over it (4 x 120 / 10 = 48; over 8 it is 60), a switched-off row counts nothing, the drive never counts, and day rows are guys x days beside it (15 + 48).

    Mutation: count the drive's hours as crew; count a switched-off row; ignore the divisor."""
    m = ran["direct"]["manDays"]
    assert m["legacy"] == 0 and m["gyp"] == pytest.approx(48) and m["over8"] == pytest.approx(60) and m["off"] == 0 and m["withDays"] == pytest.approx(63)


def test_every_profiles_divisor_is_the_one_its_own_tabs_lodging_formula_divides_by(ran):
    """Checked against the workbook's own formulas (the figure after the last slash of each tab's lodging quantity cell): the five Gyp tabs divide by 10, and every other priced tab by 8, Leveling
    included, though a Leveling day is ten hours (the sheet divides by 8 all the same). The model answers the same for a section of each tab, and counts the hours of a crew row on it by that figure:
    two guys for 40 hours (80 man-hours) is 10 nights over 8 on Seal, Seal (+Jnts), Leveling and Epoxy blank, never 8 (a ten hour day would say so), and 8.0006 on a Gyp option, which counts the
    sheet's dollars ($2,693 over $33.66 over 10).

    Mutation: let a profile's divisor drift from its tab's formula (Gyp 8; Leveling 10); divide a Leveling crew's hours by its ten hour day; divide every tab by 8."""
    d = ran["direct"]
    tabs = {f["tab"]: f for f in d["formulas"]}
    assert len(tabs) == 11
    for tab, f in tabs.items():
        want = 10 if tab.startswith("Gyp") else 8
        assert f["divisor"] == want == f["profile"], (tab, f)
    assert tabs["Leveling"]["dayHours"] == 10 and tabs["Leveling"]["divisor"] == 8, "Leveling: ten hour days, lodging still divided by 8"
    assert d["root"]["divisor"] == 8
    s = d["sections"]
    for tab in ("Epoxy", "Seal", "Seal (+Jnts)", "Leveling", "Epoxy blank"):
        assert s[tab]["divisor"] == 8 and s[tab]["people"] == pytest.approx(10) and s[tab]["nights"] == pytest.approx(10), tab
    assert s[GYP_TAB]["divisor"] == 10 and s[GYP_TAB]["people"] == pytest.approx(8)
    assert s[GYP_TAB]["nights"] == pytest.approx(2693 / 33.66 / 10), "a Gyp option counts the sheet's dollars, over the first row's rate, over 10"


def test_a_gyp_sections_nights_are_the_sheets_dollars_and_not_a_head_count(ran):
    """Two crew rows paid two rates (the oracle's `mixedRates` set in hours: $6,969 of labor): the sheet counts 6,969 / 33.66 / 10 = 20.704 nights where a person counts 19. A drive row
    ($605.88) is taken off the labor before it is divided: (5,655 - 605.88) / 33.66 / 10 = 15.0004 where 150 hours over ten is 15. The Polish way is unchanged: every hours row is the drive there,
    whatever it is called.

    Mutation: count a Gyp section's people instead of its dollars; take the crew off as drive."""
    s = ran["direct"]["sheet"]
    assert s["mixed"] == pytest.approx(6969 / 33.66 / 10) and s["mixedPeople"] == pytest.approx(19)
    assert s["withDrive"] == pytest.approx((5655 - 605.88) / 33.66 / 10) and s["withDrivePeople"] == pytest.approx(15)
    assert s["polishWay"] == pytest.approx(15.0), "a Polish section counts guys x days; its hours row (named grinder) is drive time"


def test_the_words_give_both_figures_when_the_sheets_count_is_not_the_head_count(ran):
    """The sheet counts labor DOLLARS over the first row's rate, so a row paid another rate reads as extra days, and the words under the boxes and in the working say both figures. A Gyp crew (3 guys
    for 50 hours at $33.66 and 2 for 20 at $48: $6,969) is 20.7 nights where guys x hours over ten is 19; a Combo's Polish sheet (2 guys for 5 days at $33 and 2 at $66: $7,920 over $33 over 8) is 30 where
    guys x days is 20, and its Epoxy sheet (3 guys for 4 days) is 12: 42 between the two bases where the head count is 32. A box the estimator typed is told the sheet's count, text only, in the hint and in
    the working's reference line, with the same words for where it comes from.

    Mutation: say guys x days of a crew in hours; name one sheet on a Combo (in the box's hint, in the working, in the typed hint)."""
    w = ran["words"]
    g, c = w["gypFollowing"], w["comboFollowing"]
    assert g["job"]["count"] == pytest.approx(6969 / 33.66 / 10) and g["job"]["days"] == 19 and g["job"]["sections"] == 1
    assert g["lodgingHint"] == "Follows the labor above as the sheet counts it (20.7; guys x hours over 10 is 19): a night for each, Kyle's way."
    assert g["perDiemHint"] == "Follows the labor above as the sheet counts it (20.7; guys x hours over 10 is 19): a day of per diem for each, Kyle's way."
    assert g["following"] == ["Nights and per diem days follow the labor above as the sheet counts it (20.7 now; guys x hours over 10 is 19), a night and a day of per diem for each, Kyle's way."]
    assert c["job"]["count"] == pytest.approx(42) and c["job"]["days"] == 32 and c["job"]["sections"] == 2
    assert c["lodgingHint"] == "Follows the labor of the base sheets as the sheet counts it (42; guys x days is 32): a night for each, Kyle's way."
    assert c["perDiemHint"] == "Follows the labor of the base sheets as the sheet counts it (42; guys x days is 32): a day of per diem for each, Kyle's way."
    assert c["following"] == ["Nights and per diem days follow the labor of the base sheets as the sheet counts it (42 now; guys x days is 32), a night and a day of per diem for each, Kyle's way."]
    gt, ct = w["gypTyped"], w["comboTyped"]
    assert gt["lodgingHint"] == gt["perDiemHint"] == "Nights from the labor above, as the sheet counts them: 20.7."
    assert gt["reference"] == ["For reference, the labor lines above count 20.7 nights the way the sheet does (guys x hours over 10 is 19)."]
    assert ct["lodgingHint"] == ct["perDiemHint"] == "Nights from the labor of the base sheets, as the sheet counts them: 42."
    assert ct["reference"] == ["For reference, the labor lines of the base sheets count 42 nights the way the sheet does (guys x days is 32)."]


def test_a_gyp_crew_at_the_librarys_rate_reads_as_man_days_though_the_sheet_charges_a_dollar_more(ran):
    """At the library's own $33.66 the sheet rounds the labor UP to the dollar before it divides, so 4 guys for 120 hours count 48.0006 nights where a head count says 48, and the lines charge a dollar
    more each ($3,361 and $2,161). Both counts read 48, so the words say 48 in the plain way ("Man-days from the tasks above: 48." under a typed box, "the man-days on the labor lines above are 48." in the
    working), not "as the sheet counts them" with the same number on both sides. A line on the OLDER auto keeps the exactness it always had: a rev 3 Polish root at 48.0019 nights against guys x days 48
    still reads "Nights counted from the labor above, as the sheet does."

    Mutation: tell a typed box a rounding is a different count (in the hint; in the working's reference); read an older auto line's rounding as the same count."""
    f, t = ran["words"]["gypRealFollowing"], ran["words"]["gypRealTyped"]
    assert f["job"]["count"] == pytest.approx(16157 / 33.66 / 10) and f["job"]["days"] == 48
    assert f["costs"] == {"lodging": 3361, "per_diem": 2161, "total": 5522}, "the sheet's own figure: 48.0006 nights, each line rounded up"
    assert f["lodgingHint"] == GYP_FOLLOW_LODGING
    assert t["lodgingHint"] == t["perDiemHint"] == "Man-days from the tasks above: 48."
    assert t["reference"] == ["For reference, the man-days on the labor lines above are 48."]
    o = ran["words"]["olderAutoNear"]
    assert o["job"]["count"] == pytest.approx(12672.5 / 33 / 8) and o["job"]["days"] == 48
    assert o["hint"] == "Nights counted from the labor above, as the sheet does."


def test_the_working_is_worked_out_of_the_whole_model_whatever_section_the_panel_hands_it(ran):
    """A Combo (Polish 4 x 12, Epoxy 5 x 10) asked through the view of its Epoxy section, with the whole model beside it, counts 48 + 50 = 98 man-days between its two bases and says so in the
    working; asked of the model itself it says the same. (A view alone would read the Epoxy rows as the root's too: 100.)

    Mutation: ask the view and not the whole model."""
    h = ran["direct"]["how"]
    sentence = ("Nights and per diem days follow the man-days on the labor lines of the base sheets (98 now), a night and a day of per diem for each man-day, Kyle's way.")
    assert h["carrier"] == "Polish" and h["job"]["sections"] == 2 and h["job"]["days"] == 98 and h["job"]["sheet"] is True
    assert h["whole"] == [sentence] and h["plain"] == [sentence]


# ── red without the code: break a COPY of the page or the model one line at a time ──────────────────────────────────────────────────────────
MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"
PROFILES = "js/bid-profiles.js"


def close(a, b):
    return a is not None and abs(a - b) < 1e-6


# the same anchors test_polish_travel_round5.py breaks for a Polish bid, which a Gyp bid and a Combo share
FILL_IF = "if (l.qty_typed !== true && l.qty_auto === false && !filledIn(l.qty)) {"
SYNC_QTY = "if (l && l.qty_auto !== false) l.qty = qtyFollows(l) ? laborFollowQty(model, l) : days;"
SYNC_OPEN = "      var carrier = multi ? sectionOf(model, travelCarrier(model)).section : model;"
FOLLOW_LIST = "      list = bases.length ? bases : live.slice(0, 1);"
OWN_NIGHTS = "    return profile ? sheetNights(rows, model.conditions, prevailingApplied(model), profile) : travelManDays(rows, entryDivisor(entry));"
FOLLOW_GUARD = "    if (qtyFollows(line) && opts && opts.follow !== undefined) return opts.follow;"
SHEET_TRAVEL = '      if (crewByHour ? isTravelRow(r) : r.unit === "hours") { travelLabor += laborCost(r, pw); continue; }'
SHEET_DIVIDE = "    return engine.lodgingNights(profile, roundUp(laborTotal(rows, conditions, pw)), travelLabor, rate || SHIPPED_LABOR_RATE);"
DIVISOR = "    var d = p ? Number(p.quirks.lodgingDivisor) : NaN;"
CARRIER_COST = "      travel: carrier ? travelCosts(model.travel, s.labor, travelOpts(model, e.tab)).total : 0,"
OPTION_COST = '    if (!carrier && e.kind === "option") input.travel = optionTravelCosts(model.travel, s.labor, ownNights(model, e)).total;'
GYP_HINT = ("      if (same) return \"Follows the crew's hours on the labor lines above, \" + hours + \" hours a night (\" + shown(job.days) + \"): \" + each + \" for each, Kyle's way.\";")
ONE_HINT = ("    if (same) return \"Follows the man-days on \" + (multi ? \"the labor lines of the base sheets\" : \"the labor lines above\") + \" (\" + shown(job.days) + \"): \" + each + \" for each, Kyle's way.\";")
GYP_DIFFERS_HINT = ("      return \"Follows the labor above as the sheet counts it (\" + shown(job.count) + \"; guys x hours over \" + hours + \" is \" + shown(job.days) + \"): \" + each + \" for each, Kyle's way.\";")
ONE_DIFFERS_HINT = ("    return \"Follows the labor \" + (multi ? \"of the base sheets\" : \"above\") + \" as the sheet counts it (\" + shown(job.count) + \"; guys x days is \" + shown(job.days) + \"): \" + each + \" for each, Kyle's way.\";")
GYP_DIFFERS_HOW = ("          ? what + \" the labor above as the sheet counts it (\" + qty(job.count) + \" now; guys x hours over \" + nightHours + \" is \" + qty(job.days) + \"), \" + each + \" for each, Kyle's way.\"")
ONE_DIFFERS_HOW = ("          ? what + \" the labor \" + (multi ? \"of the base sheets\" : \"above\") + \" as the sheet counts it (\" + qty(job.count) + \" now; guys x days is \" + qty(job.days) + \"), \" + each + \" for each, Kyle's way.\"")
TYPED_MULTI_HINT = '                 : "Nights from the labor of the base sheets, as the sheet counts them: " + (Math.round(nights * 100) / 100) + ".";'
TYPED_REFERENCE = ('        lines.push("For reference, " + where + " count " + qty(job.count) + " nights the way the sheet does (" + (gypCarrier ? "guys x hours over " + nightHours : "guys x days") + " is " +')
GYP_HOW_LINE = ("          : what + \" the crew's hours on the labor lines above, \" + nightHours + \" hours a night (\" + (job.days > 0 ? qty(job.days) + \" now\" : \"none yet\") + \"), \" + each + \" for each, Kyle's way.\" +")
HOW_WHERE = '    var where = multi ? "the labor lines of the base sheets" : "the labor lines above";'
CARD_GYP_LODGING = ('        ? (isNight ? "Overnight stays are expected at 70 miles or more from the office, and then the nights fill in from the crew\'s hours, " +').replace("\\'", "'")
CARD_GYP_PER_DIEM = '          : "Meals while the guys are away, expected at 70 miles or more from the office, and then the days fill in from the crew\'s hours, " +'.replace("\\'", "'")
CARD_LODGING_LINE = '        ? "Overnight stays are expected at 70 miles or more from the office, and then the nights fill in from the man-days, a night for each, " +'
CARD_PER_DIEM_LINE = '        : "Meals while the guys are away, expected at 70 miles or more from the office, and then the days fill in from the man-days, a day of " +'
CAP_GYP = "          ? 'On a far Gyp job type the drive hours, because the Gyp sheet works its own drive time. The nights and per diem days fill in from the crew\\'s hours, ' +"
CAP_LINE = "          : 'On a far job Travel Labor fills in from the miles, and the nights and per diem days from the man-days; type over any of them to use your own.</p>');"
REVIEW_QTY = "      var qty = ownTravel ? B.optionNights(ROOT, activeTab) : B.travelQty(tl, M.labor, B.travelOpts(ROOT, activeTab));"

# name -> (file, old, new, a fact that must change). Each is one line, which break_source requires to be there exactly once.
BREAKS = {
    # N1: a Gyp crew in hours
    "a Gyp carrier's nights are typed again": (
        MODEL, "      if (far) {", '      if (far && (entryOrNull(model, carrierTabOf(model)) || {}).layout !== "gyp") {',
        lambda g: g["gyp"]["saved"]["lodging"]["follow"] is None),
    "a crew in hours counts nothing in the man-days": (
        MODEL, "    var hourly = num(hoursPerNight) > 0 ? num(hoursPerNight) : 0;", "    var hourly = 0;",
        lambda g: g["direct"]["manDays"]["gyp"] != 48 or g["gyp"]["typed"]["l"]["lodgingHint"] != "Man-days from the tasks above: 60."),
    "the drive is counted as crew": (
        MODEL, "        if (hourly && !isTravelRow(r) && rowOn(r)) t += num(r.guys) * num(r.days) / hourly;",
        "        if (hourly && rowOn(r)) t += num(r.guys) * num(r.days) / hourly;",
        lambda g: g["direct"]["manDays"]["gyp"] != 48),
    "a switched-off crew row counts": (
        MODEL, "        if (hourly && !isTravelRow(r) && rowOn(r)) t += num(r.guys) * num(r.days) / hourly;",
        "        if (hourly && !isTravelRow(r)) t += num(r.guys) * num(r.days) / hourly;",
        lambda g: g["direct"]["manDays"]["off"] != 0),
    "every tab's hours are divided by 8": (
        MODEL, DIVISOR, "    var d = 8;",
        lambda g: g["direct"]["sections"][GYP_TAB]["divisor"] != 10 or g["gyp"]["typed"]["l"]["lodgingHint"] != "Man-days from the tasks above: 60."),
    "a Leveling crew's hours are divided by its ten hour day": (
        MODEL, DIVISOR, "    var d = p ? Number(p.quirks.dayHours) : NaN;",
        lambda g: g["direct"]["sections"]["Leveling"]["divisor"] != 8),
    "a Gyp section counts people and not the sheet's dollars": (
        MODEL, '    if (entry.layout === "gyp") return profileOf(entry);', '    if (entry.layout === "gyp") return null;',
        lambda g: not close(g["direct"]["sections"][GYP_TAB]["nights"], 2693 / 33.66 / 10)),
    "every hours row is taken off as the drive on a Gyp tab": (
        MODEL, SHEET_TRAVEL, '      if (r.unit === "hours") { travelLabor += laborCost(r, pw); continue; }',
        lambda g: not close(g["direct"]["sheet"]["mixed"], 6969 / 33.66 / 10)),
    "the sheet's nights are divided by the Polish tab's 8 on every tab": (
        MODEL, SHEET_DIVIDE, "    return engine.lodgingNights(REV2, roundUp(laborTotal(rows, conditions, pw)), travelLabor, rate || SHIPPED_LABOR_RATE);",
        lambda g: not close(g["direct"]["sheet"]["mixed"], 6969 / 33.66 / 10) or g["gyp"]["saved"]["lodging"]["qty"] != 48),
    "a profile's divisor drifts from its tab's formula (Gyp)": (
        PROFILES, '        escalationAlwaysOn: true, hasHardBid: false, shippingRule: "gyp-split", lodgingDivisor: 10, dayHours: 10',
        '        escalationAlwaysOn: true, hasHardBid: false, shippingRule: "gyp-split", lodgingDivisor: 8, dayHours: 10',
        lambda g: any(f["divisor"] != f["profile"] for f in g["direct"]["formulas"])),
    "a profile's divisor drifts from its tab's formula (Leveling)": (
        PROFILES, "      quirks: { escalationInSubtotal: false, dayHours: 10 },", "      quirks: { escalationInSubtotal: false, dayHours: 10, lodgingDivisor: 10 },",
        lambda g: any(f["divisor"] != f["profile"] for f in g["direct"]["formulas"])),
    # the follow figure is the job's: every base section together
    "a line that follows is charged the carrier's own rows": (
        MODEL, FOLLOW_GUARD, "    void opts;",
        lambda g: g["combo"]["price"]["lump"] != 81226 or g["gyp"]["price"]["lump"] != 46088),
    "the job's figure counts only the carrier": (
        MODEL, FOLLOW_LIST, "      list = live.slice(0, 1);",
        lambda g: g["combo"]["n"]["lodging"]["qty"] != 96),
    "a section that is off is counted": (
        MODEL, FOLLOW_LIST, '      list = entries.filter(function (e) { return e.kind === "base" || e.kind === "off"; });',
        lambda g: g["combo"]["polishOnly"]["n"]["lodging"]["qty"] != 48),
    "an option is counted in the job's figure": (
        MODEL, FOLLOW_LIST, "      list = live;",
        lambda g: g["combo"]["withOption"]["n"]["lodging"]["qty"] != 96),
    "the box holds no figure": (
        MODEL, "    return Math.round(jobFollowQty(model) * 100) / 100;", "    return 0;",
        lambda g: g["gyp"]["saved"]["lodging"]["qty"] != 48),
    "the page prices the carrier from its own rows": (
        MODEL, CARRIER_COST, "      travel: carrier ? travelCosts(model.travel, s.labor).total : 0,",
        lambda g: g["gyp"]["price"]["lump"] != 46088),
    "the figure does not follow the crew when it changes": (
        MODEL, SYNC_QTY, "if (l && l.qty_auto !== false && !qtyFollows(l)) l.qty = days;",
        lambda g: g["gyp"]["moreGuys"]["n"]["lodging"]["qty"] != 60 or g["combo"]["morePolish"]["n"]["lodging"]["qty"] != 132),
    "a box the estimator cleared is refilled by the next answer": (
        MODEL, FILL_IF, "if (l.qty_auto === false && !filledIn(l.qty)) {",
        lambda g: g["gyp"]["typed"]["n"]["perDiem"]["qty"] != ""),
    "going local keeps the figure the labor filled": (
        MODEL, "      } else if (qtyFollows(l)) {", "      } else if (false) {",
        lambda g: g["gyp"]["local"]["n"]["lodging"]["qty"] != ""),
    "the lines are filled when a bid merely opens": (
        MODEL, SYNC_OPEN, "      followDistanceNights(model, model.distance ? model.distance.miles : null);\n" + SYNC_OPEN,
        lambda g: g["gyp"]["savedBlank"]["n"]["lodging"]["qty"] != "" or g["combo"]["savedBlank"]["n"]["lodging"]["qty"] != ""),
    # an option counts its own
    "a Gyp option is charged nothing for its hours crew": (
        MODEL, OWN_NIGHTS, "    return travelManDays(rows);",
        lambda g: g["gypOption"]["gyp"]["travel"] != 5520 or g["gypCopy"]["copied"]["travel"] != 5520),
    "an option is charged by the older man-days": (
        MODEL, OPTION_COST, '    if (!carrier && e.kind === "option") input.travel = optionTravelCosts(model.travel, s.labor).total;',
        lambda g: g["gypOption"]["gyp"]["travel"] != 5520),
    "a Gyp option counts people and not the sheet's dollars": (
        MODEL, '    var profile = entry.layout === "gyp" ? sheetCountProfile(entry) : null;', "    var profile = null;",
        lambda g: not close(g["direct"]["sections"][GYP_TAB]["nights"], 2693 / 33.66 / 10)),
    "the Review shows an option's nights as day rows": (
        PAGE, REVIEW_QTY, "      var qty = ownTravel ? B.travelManDays(M.labor) : B.travelQty(tl, M.labor, B.travelOpts(ROOT, activeTab));",
        lambda g: g["gypOption"]["gyp"]["review"]["lodgingQty"] != "48"),
    # the words
    "the Gyp hint says man-days": (
        MODEL, GYP_HINT, "      if (same) return \"Follows the man-days on the labor lines above (\" + shown(job.days) + \"): \" + each + \" for each, Kyle's way.\";",
        lambda g: g["gyp"]["labor"]["lodgingHint"] != GYP_FOLLOW_LODGING or g["gyp"]["review"]["perDiemNote"] != GYP_FOLLOW_PER_DIEM),
    "the Combo hint names one sheet": (
        MODEL, ONE_HINT, "    if (same) return \"Follows the man-days on the labor lines above (\" + shown(job.days) + \"): \" + each + \" for each, Kyle's way.\";",
        lambda g: g["combo"]["l"]["lodgingHint"] != COMBO_FOLLOW_LODGING or g["combo"]["review"]["lodgingNote"] != COMBO_FOLLOW_LODGING),
    "the working says man-days for a Gyp crew": (
        MODEL, GYP_HOW_LINE, "          : what + \" the man-days on the labor lines above (\" + (job.days > 0 ? qty(job.days) + \" now\" : \"none yet\") + \"), \" + each + \" for each, Kyle's way.\" +",
        lambda g: GYP_HOW not in g["gyp"]["labor"]["how"].split("\n")),
    "the working names one sheet on a Combo": (
        MODEL, HOW_WHERE, '    var where = "the labor lines above";',
        lambda g: COMBO_HOW not in g["combo"]["l"]["how"].split("\n")
        or "For reference, the man-days on the labor lines of the base sheets are 96." not in g["combo"]["typedHint"]["how"].split("\n")),
    "the working is asked of the section on show": (
        MODEL, "    var W = whole || M;", "    var W = M;",
        lambda g: g["direct"]["how"]["whole"] != g["direct"]["how"]["plain"]),
    "a typed box on a Combo is told the carrier's man-days": (
        MODEL, "    var multi = !auto && !!entry && baseCount(model) > 1 && carrierTabOf(model) === tab;", "    var multi = false;",
        lambda g: g["combo"]["typedHint"]["lodging"] != "Man-days from the labor lines of the base sheets: 96."),
    "a typed box leaves a crew's hours out of the man-days": (
        MODEL, "      days = travelManDays(rows, entry && !auto ? entryDivisor(entry) : undefined);", "      days = travelManDays(rows);",
        lambda g: g["gyp"]["typed"]["l"]["lodgingHint"] != "Man-days from the tasks above: 60."),
    # the words when the sheet's count is not the head count
    "a crew in hours is told guys x days when the sheet's count differs": (
        MODEL, GYP_DIFFERS_HINT, "      return \"Follows the labor above as the sheet counts it (\" + shown(job.count) + \"; guys x days is \" + shown(job.days) + \"): \" + each + \" for each, Kyle's way.\";",
        lambda g: g["words"]["gypFollowing"]["lodgingHint"] != "Follows the labor above as the sheet counts it (20.7; guys x hours over 10 is 19): a night for each, Kyle's way."),
    "a Combo is told one sheet when the sheet's count differs": (
        MODEL, ONE_DIFFERS_HINT, ONE_DIFFERS_HINT.replace('(multi ? \"of the base sheets\" : \"above\")', '\"above\"'),
        lambda g: g["words"]["comboFollowing"]["lodgingHint"] != "Follows the labor of the base sheets as the sheet counts it (42; guys x days is 32): a night for each, Kyle's way."),
    "the working tells a Gyp crew guys x days when the sheet's count differs": (
        MODEL, GYP_DIFFERS_HOW, "          ? what + \" the labor above as the sheet counts it (\" + qty(job.count) + \" now; guys x days is \" + qty(job.days) + \"), \" + each + \" for each, Kyle's way.\"",
        lambda g: not g["words"]["gypFollowing"]["following"][0].endswith("(20.7 now; guys x hours over 10 is 19), a night and a day of per diem for each, Kyle's way.")),
    "the working names one sheet on a Combo when the sheet's count differs": (
        MODEL, ONE_DIFFERS_HOW, ONE_DIFFERS_HOW.replace('(multi ? \"of the base sheets\" : \"above\")', '\"above\"'),
        lambda g: "of the base sheets as the sheet counts it" not in g["words"]["comboFollowing"]["following"][0]),
    "a typed box on a Combo is told one sheet when the sheet's count differs": (
        MODEL, TYPED_MULTI_HINT, TYPED_MULTI_HINT.replace("of the base sheets", "above"),
        lambda g: g["words"]["comboTyped"]["lodgingHint"] != "Nights from the labor of the base sheets, as the sheet counts them: 42."),
    "the typed reference tells a Gyp crew guys x days": (
        MODEL, TYPED_REFERENCE, TYPED_REFERENCE.replace('(gypCarrier ? "guys x hours over " + nightHours : "guys x days")', '"guys x days"'),
        lambda g: g["words"]["gypTyped"]["reference"] != ["For reference, the labor lines above count 20.7 nights the way the sheet does (guys x hours over 10 is 19)."]),
    "a typed box calls a rounding a different count": (
        MODEL, "    var one = nights === null || Math.abs(nights - days) < (auto ? 1e-9 : 0.005);", "    var one = nights === null || Math.abs(nights - days) < 1e-9;",
        lambda g: g["words"]["gypRealTyped"]["lodgingHint"] != "Man-days from the tasks above: 48."),
    "the working's reference calls a rounding a different count": (
        MODEL, "      if (job.sheet && Math.abs(job.count - job.days) >= 0.005) {", "      if (job.sheet && Math.abs(job.count - job.days) >= 1e-9) {",
        lambda g: g["words"]["gypRealTyped"]["reference"] != ["For reference, the man-days on the labor lines above are 48."]),
    "an older auto line reads a rounding as the same count": (
        MODEL, "    var one = nights === null || Math.abs(nights - days) < (auto ? 1e-9 : 0.005);", "    var one = nights === null || Math.abs(nights - days) < 0.005;",
        lambda g: g["words"]["olderAutoNear"]["hint"] != "Nights counted from the labor above, as the sheet does."),
    # N1: the Gyp DRIVE stays typed
    "a far answer fills a Gyp carrier's drive": (
        MODEL, '    if (layout === "gyp") return null;', "    void layout;",
        lambda g: g["gyp"]["saved"]["drive"]["days"] != ""),
    # N4: the cards, both of them, on a Gyp carrier and on every other
    "the Gyp Lodging card says the man-days": (
        PAGE, CARD_GYP_LODGING, CARD_GYP_LODGING.replace("the crew's hours, ", "the man-days, "),
        lambda g: g["cards"]["gyp"]["lodging"] != GYP_CARD_LODGING),
    "the Gyp Per Diem card says the man-days": (
        PAGE, CARD_GYP_PER_DIEM, CARD_GYP_PER_DIEM.replace("the crew's hours, ", "the man-days, "),
        lambda g: g["cards"]["gyp"]["perDiem"] != GYP_CARD_PER_DIEM),
    "the Gyp sentence above the travel block says the nights are typed": (
        PAGE, CAP_GYP, CAP_GYP.replace("fill in from the crew\\'s hours, ", "are typed, because a crew in hours does not count, "),
        lambda g: g["cards"]["gyp"]["cap"] != GYP_CAP),
    "the Lodging card of every other carrier loses its words": (
        PAGE, CARD_LODGING_LINE, CARD_LODGING_LINE.replace("a night for each, ", "a night each, "),
        lambda g: g["cards"]["polish"]["lodging"] != CARD_LODGING or g["cards"]["epoxy"]["lodging"] != CARD_LODGING),
    "the Per Diem card of every other carrier loses its words": (
        PAGE, CARD_PER_DIEM_LINE, CARD_PER_DIEM_LINE.replace("a day of ", "a day for "),
        lambda g: g["cards"]["polish"]["perDiem"] != CARD_PER_DIEM or g["cards"]["epoxy"]["perDiem"] != CARD_PER_DIEM),
    "the sentence above the travel block of every other carrier loses its words": (
        PAGE, CAP_LINE, CAP_LINE.replace("from the man-days;", "from the crew;"),
        lambda g: g["cards"]["polish"]["cap"] != CAP or g["cards"]["epoxy"]["cap"] != CAP),
    # a bid saved before this change
    "an older auto line counts a crew's hours": (
        MODEL, "    return travelManDays(rows);", "    return travelManDays(rows, 10);",
        lambda g: g["legacy"]["gypOlderAuto"]["lump"] != 35552),
    "an older auto line is charged the job's figure": (
        MODEL, FOLLOW_GUARD, "    if (opts && opts.follow !== undefined) return opts.follow;",
        lambda g: g["legacy"]["comboOneFollows"]["costs"]["per_diem"] != 2160),
    "a typed quantity follows the labor": (
        MODEL, "    if (line.qty_auto === false) return num(line.qty);", "    void line;",
        lambda g: g["legacy"]["comboTyped"]["lump"] != 81226),
}


def test_no_fact_a_break_looks_for_is_already_changed_on_the_real_tree(ran):
    """The other half of every entry below: the fact it reads is NOT changed on the tree as it is (a break that is "noticed" because its check was already true would prove nothing)."""
    already = sorted(name for name, (_rel, _old, _new, noticed) in BREAKS.items() if noticed(ran))
    assert already == [], "these breaks are noticed on the real tree, so they prove nothing: %s" % already


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    """Each change is a line a fact above depends on, broken in a scratch copy of the page or the model; a FACT must change. A break that stops the harness, or makes a section throw, is
    not counted as noticed: it has no facts to compare."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the break stopped the harness outright, so no fact noticed it: " + name + "\n" + proc.stderr[-600:]
    got = last_json_line(proc.stdout)
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "the break crashed %s instead of changing a fact: %s (%s)" % (", ".join(crashed), name, "; ".join(got[k]["error"][:200] for k in crashed))
    assert noticed(got), "the scenarios did not notice: " + name
