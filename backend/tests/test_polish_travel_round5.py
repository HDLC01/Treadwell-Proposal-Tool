"""THE FIFTH AUDIT OF "A FAR DISTANCE FILLS TRAVEL LABOR" (2026-10-20, of b14bc98), and Hanz's decision that came with it, held on the real estimate page.

Wichita is 190 miles from the Olathe office, and a crew of 4 for 12 days is 48 man-days. Travel Labor is one round trip for each guy (4 x 6.5 hours x $33 = $858), and since this
round the nights and the per diem days fill themselves the way Kyle's sheet counts them (Polish!B65, `=IF(Local="No", (labor$ - travel$)/rate/8)`): one night and one day of per diem
for every man-day, 48 nights x $70 = $3,360 and 48 days x $45 = $2,160. Each test drives js/polish-estimate.js whole (through tests/js/travel-round5-harness.js, on the real
js/bid-model.js) and reads the page back; the last block breaks a COPY of the page or the model one line at a time and requires a fact to change (never a crash).

  A  A base the Sheets panel demoted keeps a Travel Labor row of its own, so the bid prices the same in the session and after a reload (the audit's script: +$783 between the two).
     Held over every sequence of Sheets actions by test_polish_travel_sequences_reload.py.
  B  A section whose labor (or takeoff) is not a list can be put on show: every sheet, every step. (The model reads it as an empty list; the rail never assumes a list.)
  C  The answers read unreadable tabs (a section with no layout) as they always did: only the carrier's row, no options to follow.
  D  The nights and the per diem days fill on a far job, follow the labor, are the estimator's the moment they type or clear a box, go back to empty when the job goes local, never
     move when a bid merely opens, follow a carrier that moves under a far distance on file, and say so in Kyle's words (the Labor step, the how-note, the Review).
  E  The Travel Labor card's x, and the Add Travel Labor control that brings the line back: the summary no longer says it "comes on" over a job with no line.
  F  The note under an option names the sheet it points to by its name on screen, not by its tab id.
  G  The Epoxy and Seal patch notes move with the takeoff.
(H, the Review's markup card at about 916px, is test_v2_review_table_fits.py.)
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "travel-round5-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]
SECTIONS = ["demotion", "badShapes", "unreadableTabs", "nights", "addTravel", "notes", "patchNote", "xStays"]

LODGING_WORDS = "Follows the man-days on the labor lines above (48): a night for each, Kyle's way."
PER_DIEM_WORDS = "Follows the man-days on the labor lines above (48): a day of per diem for each, Kyle's way."
HOW_SENTENCE = "Nights and per diem days follow the man-days on the labor lines above (48 now), a night and a day of per diem for each man-day, Kyle's way."
HOW_NO_ROW = ("190 mi from Olathe office. That is 70 miles or more, so this is NOT a local job: Lodging and Per Diem come on, and there is no Travel Labor line to price "
              "the drive: add it below.")


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-800:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    got = run()
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "a section of the harness failed: " + "; ".join("%s: %s" % (k, got[k]["error"][:500]) for k in crashed)
    return got


def _fill(guys, hours, cost):
    return {"guys": guys, "days": hours, "auto": True, "follow": "crew", "seed": hours, "typed": False, "hoursTyped": False, "on": True, "cost": cost}


# ── A. a base the Sheets panel demoted keeps its drive: the session and a reload price the same ─────────────────────────────────────────
def test_a_demoted_base_keeps_a_travel_labor_row_so_the_session_and_a_reload_price_the_same(ran):
    """THE AUDIT'S SCRIPT. A far Polish bid (4 x 12, 190 miles), an Epoxy sheet added (a fresh sheet has no Travel Labor row: only the carrier has one), Epoxy made the base (Polish is an
    option now), the miles typed as 300 and then 299 (10 hours at both). At b14bc98 the Polish sheet had NO row in the session (the row had moved to Epoxy) and the root was given a blank one
    when the draft was reopened, which the next answer filled: $40,988 in the session and $41,771 after a reload (+$783), and the drive priced from 299 miles and not from the pick. Now the
    new carrier takes a copy and the demoted Polish keeps its own, on its own crew: both sides price the drive from the pick (4 x 6.5 x $33 = $858), at 300 miles (4 x 10 x $33 = $1,320)
    and at 299, and a plain reopen of what the session saved arms no save and asks nothing. The same on a Combo made Epoxy.

    Mutation: move the row off the demoted base (the new carrier alone has it)."""
    d = ran["demotion"]
    for case in ("addedSheet", "combo"):
        c = d[case]
        for step in ("start", "at300", "at299"):
            assert c["session"][step] == c["reloaded"][step], "%s %s: the session and a reload priced differently" % (case, step)
        assert c["reloaded"]["quiet"] == {"armed": 0, "saves": 0, "asked": 0}, case
        assert c["afterPick"]["carrier"] == "Epoxy" and c["afterPick"]["kinds"] == [["Polish", "option"], ["Epoxy", "base"]], case
        assert c["afterPick"]["drive"]["Polish:option"] == _fill(4, 6.5, 858), "the demoted base keeps the drive it had, on its own crew"
    a = d["addedSheet"]
    assert a["afterPick"]["drive"]["Epoxy:base"] == _fill(4, 6.5, 858), "the new carrier took the job's drive"
    assert [a["session"][s]["root"] for s in ("start", "at300", "at299")] == [40864, 41771, 41771], "the Polish option's own price, from the pick on"
    assert [a["session"][s]["rows"]["Polish:option"]["cost"] for s in ("start", "at300", "at299")] == [858, 1320, 1320]
    assert [a["session"][s]["lump"] for s in ("start", "at300", "at299")] == [39590, 40476, 40476], "the lump sum is the new base's"


# ── B. a section whose labor is not a list can be put on show ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("key", ["labor", "takeoff"])
def test_a_section_whose_labor_or_takeoff_is_not_a_list_opens_and_every_sheet_and_step_can_be_shown(ran, key):
    """An Epoxy section (and an option copy) whose labor or takeoff is a string, a number, an object, a boolean or null: the page opened (the sync reads the lists through a guard) and then
    THREW when the estimator put the section on show (`M.labor.forEach is not a function` in the rail, which every step draws). The model reads such a list as an empty one now, so
    the bid opens as a Combo, as Polish and as Epoxy, and EVERY sheet is put on show at EVERY step (Material, Labor, Review) without a throw. A bid that is sound comes back byte for byte.

    Mutation: leave the list as it was saved (labor; takeoff); read a `tabs` entry that is not a section as one."""
    b = ran["badShapes"]
    assert b["soundTabs"] is True
    # a `tabs` entry that is not a section at all (a number, null, a string) is carried exactly as it was saved, and reading the bid throws nothing
    for kind, got in b["notSections"].items():
        assert got["threw"] is None and got["carried"] is True and got["keys"] == ["Epoxy", "Strange"], kind
    for shape in ("string", "number", "object", "boolean", "null"):
        for job, page in b[shape][key].items():
            assert page["opened"] is True and page["shown"] is True, "%s %s as %s did not open: %s" % (shape, key, job, page.get("error"))
            assert page["threw"] == {}, "%s %s as %s threw when a section was put on show: %s" % (shape, key, job, page["threw"])


def test_the_rail_never_assumes_a_list(ran):
    """The page's own half: the rail's status (drawn for every section on show) is asked of a section whose labor and takeoff are not lists, put there after the model was read as a
    model handed to the page another way would hold them. It answers; it does not throw.

    Mutation: walk the takeoff, or the labor, unguarded."""
    for shape, got in ran["badShapes"]["status"].items():
        assert got == {"answer": {"takeoff": "", "labor": "", "review": ""}}, shape


# ── C. the answers read unreadable tabs as they always did ──────────────────────────────────────────────────────────────────────────────────
def test_an_answer_on_a_bid_whose_sections_cannot_be_read_still_fills_the_carriers_row_and_throws_nothing(ran):
    """A section whose layout is null makes sectionsOf throw. The answers (applyDistance, clearDistance, followDistance, addTravelLabor) never throw for such a bid: the carrier's row is
    filled and taken back, and there are no options to follow and no sections to give a row back from. The guard in followDistanceOptions that says so had no test: delete it and
    applyDistance and clearDistance threw on such a bid, and the same guard in takeBackStrayTravel, which followDistance runs, none either.

    Mutation: delete either guard."""
    u = ran["unreadableTabs"]
    assert u["unreadable"] is True
    assert u["applied"] is None and u["cleared"] is None and u["moved"] is None and u["added"]["added"] is None
    assert u["far"]["miles"] == 190 and u["far"]["row"] == _fill(4, 6.5, 858)
    assert u["after"]["distance"] is None and u["after"]["row"]["days"] == "" and u["after"]["row"]["cost"] == 0
    # ...and the nights the far answer fills are counted from the labor of the root, the one section that can be read (the carrier cannot be asked)
    assert u["far"]["lodging"] == {"on": True, "qty": 48, "auto": True, "follow": "labor", "typed": False, "hand": False}
    # a model with no travel block at all is cleared without a word, and one with no labor at all takes the Travel Labor line as its first
    assert u["bare"] == {"cleared": None} and u["noLabor"] == {"done": True, "rows": 1}


# ── D. the nights and the per diem days fill on a far job ──────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("job", ["epoxy", "polish"])
def test_a_far_answer_fills_the_nights_and_the_per_diem_days_with_the_labors_man_days(ran, job):
    """THE DECISION (Hanz, 2026-10-20, "Fill them automatically"). A NEW far bid (Wichita, a crew of 4 for 12 days): Lodging and Per Diem come on AND are filled, 48 and 48, on auto and
    marked as following the labor: 48 nights x $70 = $3,360 and 48 days x $45 = $2,160 ($5,520), beside the drive's $858. The boxes show 48 and the words under them say what they
    follow, the working says each line follows the labor and says once what that means, and the Review lists the two lines with 48 and their dollars and the same words under each name.

    Mutation: leave the quantities empty (the answer fills no nights); fill a box the estimator typed; fill one they cleared."""
    n = ran["nights"][job]
    line = {"on": True, "qty": 48, "auto": True, "follow": "labor", "typed": False, "hand": False}
    assert n["saved"]["lodging"] == line and n["saved"]["perDiem"] == line
    assert n["saved"]["costs"] == {"lodging": 3360, "per_diem": 2160, "total": 5520}
    assert n["saved"]["drive"] == _fill(4, 6.5, 858)
    assert (n["labor"]["lodgingBox"], n["labor"]["perDiemBox"]) == ("48", "48")
    assert (n["labor"]["lodgingHint"], n["labor"]["perDiemHint"]) == (LODGING_WORDS, PER_DIEM_WORDS)
    how = n["labor"]["how"].split("\n")
    assert "Lodging: 48 nights (follows the labor) x $70.00 = $3,360.00" in how and "Per Diem: 48 days (follows the labor) x $45.00 = $2,160.00" in how
    assert HOW_SENTENCE in how
    r = n["review"]
    assert (r["lodgingQty"], r["lodgingTotal"], r["perDiemQty"], r["perDiemTotal"]) == ("48", "$3,360", "48", "$2,160")
    assert (r["lodgingNote"], r["perDiemNote"]) == (LODGING_WORDS, PER_DIEM_WORDS)


def test_the_nights_follow_the_labor_as_it_changes(ran):
    """Like the crew-following Travel guys: the days on the crew line 12 to 14 make 56 man-days, then the guys 4 to 5 make 70. The boxes, the hints, the working and the charge move with
    them (the sheet counts the cents of the drive too, 70.0019 nights, and the box holds 70).

    Mutation: leave a following line's figure where the first answer put it."""
    d = ran["nights"]["moreDays"]
    assert (d["n"]["lodging"]["qty"], d["n"]["perDiem"]["qty"], d["manDays"]) == (56, 56, 56)
    assert d["n"]["costs"] == {"lodging": 3920, "per_diem": 2520, "total": 6440}
    assert (d["l"]["lodgingBox"], d["l"]["perDiemBox"]) == ("56", "56")
    assert d["l"]["lodgingHint"] == "Follows the man-days on the labor lines above (56): a night for each, Kyle's way."
    g = ran["nights"]["moreGuys"]
    assert (g["n"]["lodging"]["qty"], g["n"]["perDiem"]["qty"], g["manDays"]) == (70, 70, 70)
    assert g["n"]["drive"]["guys"] == 5 and g["l"]["lodgingBox"] == "70" and g["l"]["lodgingHint"] == "Follows the man-days on the labor lines above (70): a night for each, Kyle's way."


def test_a_box_the_estimator_typed_or_cleared_is_theirs_and_no_answer_fills_it_again(ran):
    """Nights typed (10) and the per diem box cleared, on a far bid: a later answer (300 miles), a later change of the labor, a save and a plain reopen, and the next answer after that,
    leave both exactly as they were (the marks are saved with the lines), while the drive goes on following the miles (10 hours at 300, 6.5 at 190). A reopen arms no save.

    Mutation: leave no mark when a box is typed in; the page's handler does not mark; the marks are not saved with the line; fill a box that holds a figure."""
    t = ran["nights"]
    typed = {"on": True, "qty": "10", "auto": False, "follow": None, "typed": True, "hand": False}
    cleared = {"on": True, "qty": "", "auto": False, "follow": None, "typed": True, "hand": False}
    for key in ("typedCleared", "typedClearedAfter300", "typedClearedAfterLabor", "typedClearedReopened", "typedClearedReopenedAnswer"):
        assert (t[key]["n"]["lodging"], t[key]["n"]["perDiem"]) == (typed, cleared), key
    assert t["typedCleared"]["n"]["costs"] == {"lodging": 700, "per_diem": 0, "total": 700}
    assert [t[k]["n"]["drive"]["days"] for k in ("typedCleared", "typedClearedAfter300", "typedClearedReopened", "typedClearedReopenedAnswer")] == [6.5, 10, 10, 6.5]
    assert t["typedClearedReopened"]["armed"] == 0 and t["typedClearedReopened"]["saves"] == 0
    assert "Lodging: 10 nights (typed) x $70.00 = $700.00" in t["typedClearedAfter300"]["l"]["how"]
    assert "Per Diem: 0 days x $45.00 = $0.00. Type the days." in t["typedClearedAfter300"]["l"]["how"]
    # ...a figure typed before the marks existed (a bid saved since 2026-10-12: a number in a box that is off auto) is theirs all the same
    nm = t["typedNoMarker"]["n"]["lodging"]
    assert (nm["qty"], nm["auto"], nm["follow"], nm["typed"]) == ("9", False, None, False)
    # ...a keystroke in a box that is NOT on auto (a local job's) is theirs too: typed 7 and cleared stays empty when the far answer comes, while the untouched Lodging fills
    ty = t["typedLocal"]
    assert ty["typed"]["perDiem"] == {"on": False, "qty": "", "auto": False, "follow": None, "typed": True, "hand": False}
    assert ty["after"]["perDiem"] == cleared and ty["after"]["lodging"] == {"on": True, "qty": 48, "auto": True, "follow": "labor", "typed": False, "hand": False}


def test_going_local_takes_back_a_figure_nobody_typed_and_leaves_one_they_did(ran):
    """Per Diem typed (7) on a far bid, then the miles corrected to 50: both lines switch off as they always did, the Lodging the labor filled goes back to EMPTY (off auto, no marker), the
    Per Diem the estimator typed stays (greyed while off). 300 miles again fills the Lodging, and leaves the 7; the miles cleared takes the Lodging back again.

    Mutation: keep the figure the labor filled when the job goes local."""
    t = ran["nights"]
    empty = {"qty": "", "auto": False, "follow": None, "typed": False}
    seven = {"qty": "7", "auto": False, "follow": None, "typed": True}
    loc = t["local"]["n"]
    assert {k: loc["lodging"][k] for k in empty} == empty and loc["lodging"]["on"] is False
    assert {k: loc["perDiem"][k] for k in seven} == seven and loc["perDiem"]["on"] is False
    assert t["local"]["cond"] == {"local": True} and loc["costs"]["total"] == 0 and (t["local"]["l"]["lodgingBox"], t["local"]["l"]["perDiemBox"]) == ("", "7")
    far = t["farAgain"]["n"]
    assert far["lodging"] == {"on": True, "qty": 48, "auto": True, "follow": "labor", "typed": False, "hand": False}
    assert {k: far["perDiem"][k] for k in seven} == seven and far["costs"] == {"lodging": 3360, "per_diem": 315, "total": 3675}
    assert "Nights follow the man-days on the labor lines above (48 now), a night for each man-day, Kyle's way." in t["farAgain"]["l"]["how"].split("\n")
    cl = t["cleared"]["n"]
    assert {k: cl["lodging"][k] for k in empty} == empty and {k: cl["perDiem"][k] for k in seven} == seven


def test_a_saved_bid_never_moves_on_open_and_the_next_answer_fills_it(ran):
    """A bid saved on a far job with Lodging and Per Diem ON and their quantities blank (what a new bid held before this decision), reopened plain: nothing is filled, saved or asked, and
    the price is the one it was saved at ($32,632). The next answer, the miles typed (even the same 190), fills them: 48 and 48 and the price rises by the nights' $5,520 and the
    markups on them ($40,864). A bid that WAS filled keeps following when it is reopened (the marker is saved with the line) and goes back to empty at 50 miles.

    Mutation: fill the lines when a bid is opened."""
    s = ran["nights"]["savedBlank"]
    blank = {"on": True, "qty": "", "auto": False, "follow": None, "typed": False, "hand": False}
    assert s["open"]["n"]["lodging"] == blank and s["open"]["n"]["perDiem"] == blank
    assert (s["open"]["armed"], s["open"]["saves"], s["open"]["asked"]) == (0, 0, 0)
    assert s["before"]["lump"] == 32632 and s["after"]["p"]["lump"] == 40864
    assert s["after"]["n"]["lodging"]["qty"] == 48 and s["after"]["n"]["perDiem"]["follow"] == "labor"
    r = ran["nights"]["reopenedFollowing"]
    assert r["open"]["n"]["lodging"] == {"on": True, "qty": 48, "auto": True, "follow": "labor", "typed": False, "hand": False}
    assert (r["open"]["armed"], r["open"]["saves"], r["open"]["asked"]) == (0, 0, 0)
    assert r["local"]["lodging"]["qty"] == "" and r["local"]["lodging"]["follow"] is None and r["local"]["lodging"]["on"] is False


def test_a_carrier_that_moves_under_a_far_distance_on_file_brings_the_lines_under_the_rule(ran):
    """A Polish bid saved far with blank lines, opened as Epoxy (the job type switched in the session): the new carrier's crew (5 x 10 days) gives 50 man-days, and Lodging and Per Diem
    follow them, charged on the Epoxy carrier as the price charges them. A line the estimator typed (9 nights) is carried through the same switch as theirs.

    ROUND 6, PART 3 (M2, 2026-10-21): the Epoxy tab counts its nights the sheet's way, from its labor DOLLARS (Epoxy!B65 `((D53-D52)/C47)/8`), as every tab does now: the crew's $13,200 and the drive's
    five guys x 6.5 hours, $1,072.50, round up to $14,273, so 50.0019 nights where the head count says 50, and the lines charge a dollar more each, $3,501 and $2,251 (this test pinned $3,500 and $2,250,
    the head count the Epoxy tab no longer charges; Hanz, 2026-10-21: "Let them re-price"). The box still shows 50: it holds the figure to two places. The working shows the count to the places
    the price needs (M4): "50.0019 nights x $70.00 = $3,500.13, rounded up to $3,501", where "50 nights" times $70 was not the $3,500.13 it printed.

    Mutation: leave the nights out of the carrier's settling."""
    m = ran["nights"]["carrierMoved"]
    assert m["n"]["carrier"] == "Epoxy" and m["manDays"] == 50
    assert m["n"]["lodging"]["qty"] == 50 and m["n"]["lodging"]["follow"] == "labor" and m["n"]["perDiem"]["follow"] == "labor"
    assert m["n"]["costs"] == {"lodging": 3501, "per_diem": 2251, "total": 5752}
    assert "Lodging: 50.0019 nights (follows the labor) x $70.00 = $3,500.13, rounded up to $3,501" in m["l"]["how"].split("\n"), "worked out on the Epoxy carrier's own labor, as the price is"
    t = ran["nights"]["carrierMovedTyped"]["n"]
    assert t["lodging"]["qty"] == "9" and t["lodging"]["typed"] is True and t["lodging"]["follow"] is None and t["perDiem"]["qty"] == 50


def test_an_option_counts_its_own_nights_whatever_the_jobs_lines_follow(ran):
    """An option is priced apart: its Lodging and Per Diem are its own man-days at the job's rates (optionTravelCosts), so the job's lines following the labor, or being typed over, move
    nothing in it. A far Polish bid copied as an option: the option's travel is $5,520 (48 x $70 + 48 x $45), the same as the base's lines, and typing 3 nights on the base's Lodging
    leaves the option's price where it was.

    Mutation: charge an option the quantity the job's line holds."""
    o = ran["nights"]["option"]
    assert o["copy"] == "Copy1" and o["own"] == 5520 and o["ownLines"] == {"lodging": 3360, "per_diem": 2160, "total": 5520}
    assert o["travel"] == 5520 and o["baseTravel"] == 5520 and o["baseLines"] == 5520
    assert o["afterTyped"]["total"] == o["total"] == 40864


def test_the_older_auto_line_is_never_converted_in_either_direction(ran):
    """A bid saved before 2026-10-12 has Lodging and Per Diem on auto with no marker: they follow the man-days as they always did. An answer applied in a session leaves them exactly that:
    no marker is written going far, and going local does not empty them (they switch off, as ever, and keep their figure).

    Mutation: take every auto line back when the job goes local."""
    o = ran["nights"]["olderAuto"]
    for step in ("open", "local", "far"):
        for k in ("lodging", "perDiem"):
            assert o[step][k]["follow"] is None and o[step][k]["auto"] is True and o[step][k]["qty"] == 48, (step, k)
    assert o["open"]["lodging"]["on"] is True and o["local"]["lodging"]["on"] is False and o["far"]["lodging"]["on"] is True


def test_a_late_lookup_fills_the_boxes_in_place_and_the_lookup_button_empties_them_in_place(ran):
    """A new bid's own lookup lands after the first paint, with the Labor step on show: the boxes show 48 and 48 with no rebuild. The lookup BUTTON then answering "30 miles" takes the
    figure back, and the boxes are emptied in place too (a box that left auto is written from the model unless the estimator is in it).

    Mutation: leave a box that left auto as it was drawn."""
    ll = ran["nights"]["lookupLand"]
    assert ll["before"]["l"]["lodgingBox"] == "" and ll["before"]["n"]["lodging"]["on"] is False
    assert (ll["landed"]["l"]["lodgingBox"], ll["landed"]["l"]["perDiemBox"], ll["landed"]["written"]) == ("48", "48", "1")
    assert ll["landed"]["n"]["costs"]["total"] == 5520
    assert (ll["local"]["l"]["lodgingBox"], ll["local"]["l"]["perDiemBox"]) == ("", "")
    assert ll["local"]["n"]["lodging"]["qty"] == "" and ll["local"]["n"]["lodging"]["on"] is False


# ── E. the Travel Labor card's x, and the control that brings the line back ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("job", ["polishFar", "epoxyFar"])
def test_the_travel_labor_line_the_cards_x_took_away_can_be_added_back_and_the_summary_says_what_is_true(ran, job):
    """The card's x takes the line away, the Add labor pop-up leaves Travel out on purpose ("it has its own block"), and that block had no control: nothing brought the line back, and the
    summary said "Travel Labor, Lodging and Per Diem come on" over a job with no line ("Travel Labor: off, $0" under it). Now, with no Travel Labor line on the section that carries the
    job's travel, the travel block says so and draws an Add Travel Labor button; the summary says Lodging and Per Diem come on and that there is no line to price the drive, and its
    working line says "no line on this bid". The button restores a fresh row (the one a new bid is seeded with: the library's name and rate, empty), filled by the rule on a far job (4
    guys x 6.5 hours x $33 = $858 on the Polish and the Epoxy carrier alike), and the control and the extra words go. A second press adds nothing. The row is on the saved draft.

    Mutation: never draw the control; the control does nothing; the row is not filled; a second line is added; the summary still claims Travel Labor."""
    a = ran["addTravel"][job]
    tab = "Polish:base" if job == "polishFar" else "Epoxy:base"
    assert a["before"]["rows"][tab] == _fill(4, 6.5, 858) and a["before"]["button"] is False
    assert "Travel Labor, Lodging and Per Diem come on." in a["before"]["how"]
    rem = a["removed"]
    assert rem["rows"][tab] is None and rem["button"] is True and rem["block"] is True and rem["words"] is True
    lines = rem["how"].split("\n")
    assert lines[0] == HOW_NO_ROW and "Travel Labor: no line on this bid, $0" in lines
    assert "Travel Labor, Lodging and Per Diem come on" not in rem["how"] and "Travel Labor: off, $0" not in rem["how"]
    add = a["added"]
    assert add["rows"][tab] == _fill(4, 6.5, 858) and add["button"] is False
    assert (add["guysBox"], add["hoursBox"], add["rate"], add["label"]) == ("4", "6.5", 33, "Travel Labor")
    # (round 7: the line Add brings back carries `hand_added`, the mark that keeps it when an option is made a base under the job's answer: the round-6 audit's F-C, Hanz 2026-10-21)
    assert add["keys"] == ["days", "guys", "guys_auto", "guys_follow", "hand_added", "hours_seed", "id", "label", "rate", "rate_default", "unit"]
    assert "Travel Labor, Lodging and Per Diem come on." in add["how"] and "no line" not in add["how"]
    assert a["addedAgain"] == {"returned": False, "count": 1}
    assert a["reopened"]["rows"][tab] == _fill(4, 6.5, 858), "the restored row is on the draft"


def test_a_gyp_carriers_line_comes_back_filled_and_a_double_press_reads_the_library_once(ran):
    """A Gyp carrier's drive FILLS from the miles like the others (round 7, Hanz 2026-10-21, D2), so the line the control brings back on a 190 mile job is filled on the crew's size read off
    the crew lines (entered in hours): 4 x 6.5 x $33 = $858. Until round 7 the Gyp sheet's drive was typed and the line came back as the empty row a new bid holds. Pressed twice before the
    library has answered, the control reads the library once and adds one line.

    Mutation: leave a Gyp carrier's added line empty; let a second press read the library again."""
    g = ran["addTravel"]["gypFar"]
    assert g["carrier"] == 'Gyp (USG 1-8")' and g["count"] == 1
    assert g["row"] == _fill(4, 6.5, 858)
    assert g["libraryReads"] == 1


def test_a_travel_labor_line_added_back_on_a_local_job_comes_up_empty(ran):
    """The rule fills a far job's row and nothing else: on a 40 mile job the restored line is the empty one a new bid holds (no guys, no hours, no marker, switched on and grey), and the
    summary of a local job says no line until it is there.

    Mutation: fill the added line whatever the distance."""
    a = ran["addTravel"]["polishLocal"]
    empty = {"guys": "", "days": "", "auto": False, "follow": None, "seed": None, "typed": False, "hoursTyped": False, "on": True, "cost": 0}
    assert a["before"]["rows"]["Polish:base"] == empty and a["removed"]["rows"]["Polish:base"] is None and a["removed"]["button"] is True
    assert "Travel Labor: no line on this bid, $0" in a["removed"]["how"].split("\n")
    assert a["added"]["rows"]["Polish:base"] == empty and a["added"]["button"] is False and a["added"]["lump"] == a["removed"]["lump"]
    assert "Travel Labor: off, $0" in a["added"]["how"].split("\n")


# ── F. the note under an option names the sheet by its name on screen ───────────────────────────────────────────────────────────────────────
def test_the_note_under_an_option_names_the_carrier_by_its_name_on_screen(ran):
    """A copy of the Polish sheet (id Copy1, named "Polish copy" on the sheet bar) made the base: the Polish root is an option, and its Labor step and its Review card said "at the rates
    set on the Copy1 section", a tab id nobody sees. They name the sheet as the sheet bar does. (A Combo's other base names its carrier too: since round 7 its crew drives on its own,
    Hanz's D1 of 2026-10-21, and the note says so, and that Hotel and Per Diem are charged once, on the Polish section.)

    Mutation: name the section by its tab id."""
    n = ran["notes"]
    assert n["copyId"] == "Copy1" and n["labor"]["carrier"] == "Copy1" and n["labor"]["label"] == "Polish copy"
    assert n["labor"]["note"] == ("This option is priced apart, so it carries its own Hotel and Per Diem for its own crew when the job is on the road, "
                                  "at the rates set on the Polish copy section. Open it to change them.")
    assert n["review"] == "rates set on the Polish copy section"
    assert n["comboNote"] == ("This sheet's guys drive on their own: its Travel Labor below is one round trip for each of them, from the miles on the Polish section. "
                              "Hotel and Per Diem are charged once for the whole job, on the Polish section. Open it to change them.")


# ── G. the patch note moves with the takeoff ────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sheet,drawn,typed", [("epoxy", "$500", "$200"), ("seal", "$250", "$100")])
def test_the_patch_note_on_the_material_step_moves_with_the_takeoff(ran, sheet, drawn, typed):
    """The patch is a price a square foot of the whole area, and the note under the rows says what it comes to. It was written once, when the step was drawn, and stayed there while the
    area was typed: an Epoxy sheet read "Patch $500" over 2,000 SF (it is $200) until the step was entered again. The paragraph is keyed and written again whenever the takeoff moves, in
    place (the same words the step has when it is drawn afresh). Epoxy $0.10 a square foot, Seal $0.05.

    Mutation: leave the note as it was drawn (Epoxy; Seal)."""
    p = ran["patchNote"][sheet]
    assert p["sf"] == 2000 and p["emptyNote"] == drawn
    assert p["typedNote"] == typed == p["redrawnNote"]


# ── red without the code: break a COPY of the page or the model one line at a time ──────────────────────────────────────────────────────────
DEMOTED = '    try { demoted = sectionOf(out, fromTab).kind === "option"; } catch (err) { demoted = false; }'
GUARD = "if (entries === null) return;   // unreadable tabs (a section with no layout): there are no options to follow, only the root's row (followDistanceHours)"
GUARD_BACK = "if (entries === null) return;   // unreadable tabs (a section with no layout): there are no sections to give a row back from"
FILL_IF = "if (l.qty_typed !== true && l.qty_auto === false && !filledIn(l.qty)) {"
SYNC_QTY = "if (l && l.qty_auto !== false) l.qty = qtyFollows(l) ? laborFollowQty(model, l) : days;"
NORMALIZE_TYPED = "if (l.qty_typed === true) out[k].qty_typed = true;"
NORMALIZE_FOLLOW = 'if (l.qty_follow === "labor" && out[k].qty_auto && l.qty_typed !== true) out[k].qty_follow = "labor";'
OWN_LINE = "function ownLineCost(line) { return (line && rowOn(line)) ? roundUp(days * num(line.rate)) : 0; }"
SYNC_OPEN = "      var carrier = multi ? sectionOf(model, travelCarrier(model)).section : model;"
HOW_DECISION = ('        (tr ? "Travel Labor, Lodging and Per Diem come on." : "Lodging and Per Diem come on, and there is no Travel Labor line to price the drive: add it below.");')
RAIL_LABOR = "    (M.labor instanceof Array ? M.labor : []).forEach(function (r) { if (B.laborCost(r, pwStep) > 0) lab += 1; });"
RAIL_TAKEOFF = "    (M.takeoff instanceof Array ? M.takeoff : []).forEach(function (r) {"
CAP_EPOXY = 'if (epoxyCapEl && capEntry && capEntry.role === "epoxy") epoxyCapEl.innerHTML = epoxyCaptionText(capEntry);'
CAP_SEAL = 'if (sealCapEl && capEntry && capEntry.role === "seal" && SL) sealCapEl.innerHTML = sealCaptionText(capEntry);'
HANDLER_MARK = "          B.markTravelQtyTyped(tline);"
REPAINT_LEFT = "          if (document.activeElement !== el && el.value !== v) el.value = v;"
HINT_FIRST = "esc(B.travelQtyHint(ROOT, activeTab, key, l, M.labor))"
HINT_REPAINT = "if (l) el.textContent = B.travelQtyHint(ROOT, activeTab, key, l, M.labor);"
FOLLOW_NOTE = 'var followNote = !ownTravel && B.qtyFollows(tl) ? B.travelFollowWords(ROOT, activeTab, k, M.labor) : "";'
CONTROL = "      html += (travelRows || addTravelHtml()) + travelCard(\"lodging\") + travelCard(\"per_diem\");"
CLICK = '    if (t.closest("[data-add-travel]")) { addTravelLaborPress(); return; }'
ADD_FILL = "    if (miles !== null) followDistanceOnRow(model, added, holder.labor, miles, !drive);"
ADD_ONCE = "    if (holder.labor.some(function (r) { return isTravelRow(r); })) return false;"
ADD_FRESH = "    return stampRateDefaults([laborRowStartsEmpty(seed)])[0];"
HOW_NO_LINE = 'lines.push(tr ? "Travel Labor: off, $0" : "Travel Labor: no line on this bid, $0");'
HOW_FOLLOWED = "    if (followed.length) {"
NOTE_NAME = "    var name = carrierName();"

# (Round-5 audit, medium: a far Gyp job's nights were TYPED, because a Gyp crew is entered in hours and the man-days counted day rows only. SUPERSEDED in round 6 by Hanz's decision to fill
# them: Kyle's Gyp tab counts its own nights from those hours, ten to a night (Gyp!B64), so a Gyp carrier's nights follow the crew like every carrier's and the card says so. The Gyp DRIVE
# stayed typed until round 7, when Hanz's D2 (2026-10-21) filled it from the miles too. Held by test_polish_travel_round6.py, the sequence walk's NIGHTS rule, and test_gyp_v2_proof.py's 40 lodging vectors.)


def test_a_travel_labor_line_taken_away_stays_away_after_a_reload_and_add_brings_it_back(ran):
    """Round-5 audit, medium: the x took the row away, a reload appended a blank one back (migrateModel), and the next far answer priced it: the session and a
    reload of the same bid priced $783 apart. The x is the answer (no_travel_labor); Add Travel Labor takes it back."""
    x = ran["xStays"]
    assert "error" not in x, x.get("error")
    assert x["flag"] is True, "the x did not record that the job has no Travel Labor"
    assert x["rowAfterReload"] is None, "a reload brought the removed Travel Labor line back"
    assert x["session"] == x["reloaded"], "the session and a reload price the same bid differently: %r vs %r" % (x["session"], x["reloaded"])
    assert x["addShown"] is True and x["added"] is not None and x["added"]["guys"] not in ("", None), "Add Travel Labor did not bring the line back filled"
    assert x["flagAfterAdd"] is False, "Add Travel Labor left the 'no Travel Labor' answer in place"


BREAKS = {
    "the x does not record the answer": (
        "js/polish-estimate.js", "      if (B.isTravelRow(gone)) B.travelLaborRemoved(ROOT, activeTab);", "      void gone;",
        lambda g: g["xStays"]["flag"] is False or g["xStays"]["rowAfterReload"] is not None or g["xStays"]["session"] != g["xStays"]["reloaded"]),
    "Add does not take the answer back": (
        "js/bid-model.js", "        delete model.no_travel_labor;", "        void 0;",
        lambda g: g["xStays"]["flagAfterAdd"] is not False),
    "a base the pick demoted loses its row to the new carrier": (
        "js/bid-model.js", DEMOTED, "    demoted = false;",
        lambda g: g["demotion"]["addedSheet"]["afterPick"]["drive"]["Polish:option"] is None
        or g["demotion"]["addedSheet"]["session"]["at300"] != g["demotion"]["addedSheet"]["reloaded"]["at300"]),
    # B
    "a section's labor that is not a list is left as it was saved": (
        "js/bid-model.js", "      if (badLabor) section.labor = s.labor instanceof Array ? withoutHoles(s.labor) : [];", "      void badLabor;",
        lambda g: any(p["threw"] or not p["opened"] for shape in ("string", "number", "object", "boolean", "null") for p in g["badShapes"][shape]["labor"].values())),
    "a section's takeoff that is not a list is left as it was saved": (
        "js/bid-model.js", "      if (badTakeoff) section.takeoff = s.takeoff instanceof Array ? withoutHoles(s.takeoff) : [];", "      void badTakeoff;",
        lambda g: any(p["threw"] or not p["opened"] for shape in ("string", "number", "object", "boolean", "null") for p in g["badShapes"][shape]["takeoff"].values())),
    "the rail walks a labor that is not a list": (
        "js/polish-estimate.js", RAIL_LABOR, "    M.labor.forEach(function (r) { if (B.laborCost(r, pwStep) > 0) lab += 1; });",
        lambda g: any("threw" in v for v in g["badShapes"]["status"].values())),
    "the rail walks a takeoff that is not a list": (
        "js/polish-estimate.js", RAIL_TAKEOFF, "    M.takeoff.forEach(function (r) {",
        lambda g: any("threw" in v for v in g["badShapes"]["status"].values())),
    "a tabs entry that is not a section is read as one": (
        "js/bid-model.js", "      if (!isObject(s)) return;", "      void s;",
        lambda g: any(v["threw"] is not None for v in g["badShapes"]["notSections"].values())),
    "the nights of a bid whose sections cannot be read are not counted from the root": (
        "js/bid-model.js", "    if (!list.length) {", "    if (false) {",
        lambda g: g["unreadableTabs"]["far"]["lodging"]["qty"] != 48),
    # C
    "the answers walk the options of a bid whose sections cannot be read": (
        "js/bid-model.js", GUARD, "void entries;",
        lambda g: g["unreadableTabs"]["applied"] is not None or g["unreadableTabs"]["cleared"] is not None),
    "the settling gives rows back from sections that cannot be read": (
        "js/bid-model.js", GUARD_BACK, "void entries;",
        lambda g: g["unreadableTabs"]["moved"] is not None),
    # D
    "a far answer fills no nights": (
        "js/bid-model.js", "    followDistanceNights(model, miles);", "    void miles;",
        lambda g: g["nights"]["polish"]["saved"]["lodging"]["qty"] != 48),
    "a box the estimator cleared is refilled by the next answer": (
        "js/bid-model.js", FILL_IF, "if (l.qty_auto === false && !filledIn(l.qty)) {",
        lambda g: g["nights"]["typedClearedAfter300"]["n"]["perDiem"]["qty"] != ""),
    "a figure the estimator typed is overwritten by the next answer": (
        "js/bid-model.js", FILL_IF, "if (l.qty_typed !== true && l.qty_auto === false) {",
        lambda g: g["nights"]["typedNoMarker"]["n"]["lodging"]["qty"] != "9"),
    "going local keeps the figure the labor filled": (
        "js/bid-model.js", "      } else if (qtyFollows(l)) {", "      } else if (false) {",
        lambda g: g["nights"]["local"]["n"]["lodging"]["qty"] != "" or g["nights"]["reopenedFollowing"]["local"]["lodging"]["qty"] != ""),
    "the nights do not follow the labor when it changes": (
        "js/bid-model.js", SYNC_QTY, "if (l && l.qty_auto !== false && !qtyFollows(l)) l.qty = days;",
        lambda g: g["nights"]["moreDays"]["n"]["lodging"]["qty"] != 56),
    "typing in a box leaves no mark": (
        "js/bid-model.js", "    line.qty_typed = true;", "    void line;",
        lambda g: g["nights"]["typedClearedAfter300"]["n"]["perDiem"]["qty"] != "" or g["nights"]["typedCleared"]["n"]["perDiem"]["typed"] is not True),
    "the page does not mark the box that was typed in": (
        "js/polish-estimate.js", HANDLER_MARK, "          void tline;",
        lambda g: g["nights"]["typedClearedAfter300"]["n"]["perDiem"]["qty"] != ""),
    "a box that was not on auto is not marked when it is typed in": (
        "js/polish-estimate.js", HANDLER_MARK, "          if (tline.qty_auto !== false) B.markTravelQtyTyped(tline);",
        lambda g: g["nights"]["typedLocal"]["after"]["perDiem"]["qty"] != ""),
    "the mark is not saved with the line": (
        "js/bid-model.js", NORMALIZE_TYPED, "void l;",
        lambda g: g["nights"]["typedClearedReopenedAnswer"]["n"]["perDiem"]["qty"] != ""),
    "the marker of a line that follows is not saved with it": (
        "js/bid-model.js", NORMALIZE_FOLLOW, "void l;",
        lambda g: g["nights"]["reopenedFollowing"]["local"]["lodging"]["qty"] != ""),
    "a carrier that moves does not bring the nights under the rule": (
        "js/bid-model.js", "    if (miles !== null && (arrived.length || !carrierKept(model, fromTab))) followDistanceNights(model, miles);", "    void miles;",
        lambda g: g["nights"]["carrierMoved"]["n"]["lodging"]["follow"] != "labor"),
    "an option is charged the quantity the job's line holds": (
        "js/bid-model.js", OWN_LINE, "function ownLineCost(line) { return (line && rowOn(line)) ? roundUp(travelQty(line, rows) * num(line.rate)) : 0; }",
        lambda g: g["nights"]["option"]["afterTyped"]["total"] != g["nights"]["option"]["total"]),
    "the older auto line is emptied when the job goes local": (
        "js/bid-model.js", "      } else if (qtyFollows(l)) {", "      } else if (l.qty_auto !== false) {",
        lambda g: g["nights"]["olderAuto"]["local"]["lodging"]["qty"] != 48),
    "a box that left auto without a keystroke keeps what it was drawn with": (
        "js/polish-estimate.js", REPAINT_LEFT, "          void v;",
        lambda g: g["nights"]["lookupLand"]["local"]["l"]["lodgingBox"] != ""),
    "the lines are filled when a bid merely opens": (
        "js/bid-model.js", SYNC_OPEN, "      followDistanceNights(model, model.distance ? model.distance.miles : null);\n" + SYNC_OPEN,
        lambda g: g["nights"]["savedBlank"]["open"]["n"]["lodging"]["qty"] != ""),
    "the Review says nothing of where a following quantity came from": (
        "js/polish-estimate.js", FOLLOW_NOTE, 'var followNote = "";',
        lambda g: g["nights"]["polish"]["review"]["lodgingNote"] != LODGING_WORDS),
    "the hint under a box is drawn without the words of a line that follows": (
        "js/polish-estimate.js", HINT_FIRST, "esc(B.lodgingHint(ROOT, activeTab, auto, M.labor))",
        lambda g: g["nights"]["polish"]["labor"]["lodgingHint"] != LODGING_WORDS),
    "the hint under a box is not repainted with the labor": (
        "js/polish-estimate.js", HINT_REPAINT, "if (l) el.textContent = B.lodgingHint(ROOT, activeTab, l.qty_auto !== false, M.labor);",
        lambda g: g["nights"]["moreDays"]["l"]["lodgingHint"] != "Follows the man-days on the labor lines above (56): a night for each, Kyle's way."),
    "the working does not say the lines follow the labor": (
        "js/bid-model.js", HOW_FOLLOWED, "    if (false) {",
        lambda g: HOW_SENTENCE not in g["nights"]["polish"]["labor"]["how"].split("\n")),
    # E
    "the Add Travel Labor control is never drawn": (
        "js/polish-estimate.js", CONTROL, '      html += travelRows + travelCard("lodging") + travelCard("per_diem");',
        lambda g: g["addTravel"]["polishFar"]["removed"]["button"] is not True),
    "the Add Travel Labor control does nothing": (
        "js/polish-estimate.js", CLICK, '    if (t.closest("[data-add-travel]")) { return; }',
        lambda g: g["addTravel"]["polishFar"]["added"]["rows"]["Polish:base"] is None),
    "the Travel Labor line that is added back is not filled by the distance": (
        "js/bid-model.js", ADD_FILL, "    void miles;",
        lambda g: g["addTravel"]["polishFar"]["added"]["rows"]["Polish:base"] is None or g["addTravel"]["polishFar"]["added"]["rows"]["Polish:base"]["cost"] != 858),
    "a second Travel Labor line is added": (
        "js/bid-model.js", ADD_ONCE, "    void 0;",
        lambda g: g["addTravel"]["polishFar"]["addedAgain"]["count"] != 1),
    "the Travel Labor line that is added back is not the one a new bid holds": (
        "js/bid-model.js", ADD_FRESH, "    return seed;",
        lambda g: g["addTravel"]["polishLocal"]["added"]["keys"] != ["days", "guys", "guys_auto", "id", "label", "rate", "rate_default", "unit"]),
    "the summary claims Travel Labor comes on over a job with no line": (
        "js/bid-model.js", HOW_DECISION, '        "Travel Labor, Lodging and Per Diem come on.";',
        lambda g: "Travel Labor, Lodging and Per Diem come on" in g["addTravel"]["polishFar"]["removed"]["how"]),
    "the summary calls a missing line a switched-off one": (
        "js/bid-model.js", HOW_NO_LINE, 'lines.push("Travel Labor: off, $0");',
        lambda g: "Travel Labor: off, $0" in g["addTravel"]["polishFar"]["removed"]["how"]),
    # (round 7, D2: the break is the old rule now, a Gyp carrier's added line left empty)
    "a Gyp carrier's added line is not filled by the distance": (
        "js/bid-model.js", ADD_FILL,
        '    if (miles !== null && (readableSections(model) || []).every(function (e) { return e.section !== holder || e.layout !== "gyp"; })) '
        'followDistanceOnRow(model, added, holder.labor, miles, !drive);',
        lambda g: g["addTravel"]["gypFar"]["row"]["days"] != 6.5),
    "a second press of the control reads the library again": (
        "js/polish-estimate.js", "    if (travelAdding) return;", "    void travelAdding;",
        lambda g: g["addTravel"]["gypFar"]["libraryReads"] != 1),
    # F
    "the note names the section by its tab id": (
        "js/polish-estimate.js", NOTE_NAME, "    var name = B.travelCarrier(ROOT);",
        lambda g: "Copy1" in g["notes"]["labor"]["note"]),
    # G
    "the Epoxy patch note is left as it was drawn": (
        "js/polish-estimate.js", CAP_EPOXY, "void epoxyCapEl;",
        lambda g: g["patchNote"]["epoxy"]["typedNote"] != "$200"),
    "the Seal patch note is left as it was drawn": (
        "js/polish-estimate.js", CAP_SEAL, "void sealCapEl;",
        lambda g: g["patchNote"]["seal"]["typedNote"] != "$100"),
}


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
