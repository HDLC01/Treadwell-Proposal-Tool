"""The prevailing wage calculator on the v2 Labor step (Hanz, 2026-10-15).

THE QUESTION. "For the prevailing wage it doesnt do anything right now right? I want you to find the
formula for it in the excel file. Now we need to create a calculator within Labor tab in the v2
estimates for prevailing wage ... it must be a container item like the others."

WHAT THE WORKBOOK HAS (backend/templates/estimate_sheet_5.7.xlsx, read before this was written). On every
priced tab there is a side block, Polish!I47:L54 (Epoxy!I55:L62, Gyp K54:N66), two identical boxes, Cement
Mason and Painter:

    J48  Prevailing Wage Rate    =SUM(J49:J50)               J49 rate + J50 fringes
    J53  1:1 "Entry" Half Wage   =IF((J48/2)<23,23,(J48/2))  "Entry" Laborer for MO "State" Wage ONLY,
                                                             NOT davis-bacon
    I51/I52 notes                Foreman *min. $32, (Entry *min. $23)

NOTHING in the sheet reads those cells. The estimator typed the rate into the labor Rate box by hand, and
D5 "PrevailingWage?" only adds the 5% labor escalation (C46). So the old words under the switch, "Raises
every labor line to the prevailing rate", were not true. The card makes them true.

WHAT IS BUILT. A "Prevailing wage" card above the labor lines on every section's Labor step: the job's
prevailing wage switch in its header (conditions.prevailing_wage, the flag the intake and Review use), one
trade (Cement Mason or Painter, a label), Rate and Fringes boxes that start EMPTY, the rate they add up to,
and the entry half wage. WHILE THE SWITCH IS OFF THE CARD IS ONE LINE (the title, the switch and the words
"Off. Labor lines keep their own rates."); switching it on opens the rest, what was typed is kept while it is
closed, and the switch repaints the card in place so the focus stays on the switch.
While the switch is on and a rate is set, every labor line prices at that rate:
except Travel Labor (it keeps its own rate, as the sheet does) and a line where the estimator typed a rate.
The rate is each line's DEFAULT (B.laborRateOf's `pw`), so the totals, the Review step and the save agree.

EVERYTHING HERE RUNS CODE. tests/js/prevailing-wage-harness.js executes the real bid-model.js and bid-engine.js
and the real estimate page, whole. The last test breaks a scratch copy of the code in a score of ways and
requires the facts to change; `break_source` refuses an anchor that is not in the file exactly once.

NOT CHANGED: a bid that never used the card. It has no `prevailing` key, prices as before, and opening it
writes nothing (the saved-bid ratchet, the chain golden and the save-patch golden stay green, untouched).
"""
import pathlib

import pytest

from _golden_support import break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
HARNESS = TESTS / "js" / "prevailing-wage-harness.js"

# What the page harness boots the real page from, and what each of those declares it needs.
SCRATCH_FRONTEND_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/library-core.js",
                          "js/library-picker.js", "js/work-types.js", "js/epoxy-takeoff.js", "js/gyp-takeoff.js",
                          "js/seal-takeoff.js", "js/price-lines-core.js"]


def _run(frontend=FRONTEND):
    require_node()
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    got = _run()
    for name in ("figures", "rates", "sections", "saved", "page", "sectionPage", "typedAtDefaultPage", "lodging", "steps"):
        assert "error" not in got[name], "%s section failed: %s" % (name, got[name].get("error"))
    return got


# ══ 1. Kyle's two figures ═══════════════════════════════════════════════════════════════════════════
def test_the_card_works_out_the_sheets_two_figures(ran):
    """J48 and J53. Rate 40 + fringes 12 is 52 and half of it, 26, is the entry half wage. Rate 30 + fringes
    10 is 40, half of it is 20, and the $23 floor holds the entry wage at 23.

    Mutation: drop the floor (`return half`) or stop adding the fringes."""
    f = ran["figures"]
    assert f["fortyTwelve"] == {"total": 52, "entry": 26}
    assert f["thirtyTen"] == {"total": 40, "entry": 23}
    assert f["constants"] == {"foreman": 32, "entry": 23}, "the two minimums are named constants, in one place"
    assert f["typedAsText"] == 52.75, "a box holds text: '40.5' and '12.25'"
    assert f["floatJunk"] == 0.3, "0.1 + 0.2 must not reach a price as 0.30000000000000004"
    assert f["nothingTyped"] == {"total": 0, "none": 0}


def _trades(**rates):
    """The two built-in boxes with these figures (key -> (rate, fringes)), as normalizePrevailing returns them."""
    out = []
    for key, label in (("cement_mason", "Cement Mason"), ("painter", "Painter")):
        r, f = rates.get(key, ("", ""))
        out.append({"key": key, "label": label, "rate": r, "fringes": f})
    return out


def test_every_trade_has_a_box_and_the_crew_is_paid_one(ran):
    """Hanz, 2026-10-15: one box per trade, Cement Mason and Painter always (the sheet's two), plus any other
    trade the estimator adds and names. The FIRST shape, one trade per bid, is read into this one.

    Mutation: the first shape's rate is dropped on the way in."""
    f = ran["figures"]
    assert f["trades"] == [["cement_mason", "Cement Mason"], ["painter", "Painter"]]
    n = f["normalised"]
    assert n["badTrade"] == "cement_mason", "an unknown trade reads as the first"
    # the first shape, one trade per bid: its figures land on its trade, and the crew stays paid it
    assert n["painter"] == {"trade": "painter", "trades": _trades(painter=("40", 12))}
    assert n["keepsHalfTyped"] == "12.", "a half typed number must not snap while somebody is typing it"
    assert n["none"] is None and n["notAnObject"] is None and n["list"] is None
    assert n["empty"] == {"trade": "cement_mason", "trades": _trades()}
    # the estimator's own: in order, named, keys minted not typed, built-ins keep their names
    own = n["own"]
    assert own["trade"] == "t2"
    assert own["trades"] == _trades(cement_mason=(40, 12), painter=(30, 9)) + [
        {"key": "t2", "label": "Laborer", "rate": "25", "fringes": 8},
        {"key": "t3", "label": "x" * 60, "rate": "", "fringes": ""}], own["trades"]
    assert n["ownCrewTotal"] == 33, "the crew is paid the trade it picked, one of our own included"
    assert n["goneCrew"] == "cement_mason", "a crew trade that is not on the card reads as the first"
    assert n["newKey"] == "t3"
    # a hand-edited blob: only keys this card can have are read (CodeQL js/remote-property-injection)
    assert n["hostile"] == ["cement_mason", "painter"]


def test_the_rate_is_in_force_only_with_the_switch_on_and_a_rate_set(ran):
    """The switch is the job's own flag, so with it off (or no rate set) every labor price reads as before.

    Mutation: ignore the switch in prevailingApplied."""
    a = ran["figures"]["applied"]
    assert a["onWith52"] == 52
    assert a["offWith52"] == 0, "the switch is off: no prevailing wage"
    assert a["onEmpty"] == 0 and a["onNoBlock"] == 0 and a["noModel"] == 0
    assert a["onlyFringes"] == 9, "the sheet adds whatever is typed"


# ══ 2. one labor line ═══════════════════════════════════════════════════════════════════════════════
def test_labor_lines_price_at_the_prevailing_rate_and_travel_keeps_its_own(ran):
    """Polishing, Mock-up and Joint filler at 52, Travel Labor at its own 36, and the labor total follows.

    Mutation: ignore `pw` in laborRateOf; treat Travel as a labor line."""
    r = ran["rates"]
    assert r["noPw"]["rates"] == [33, 33, 33, 36] and r["noPw"]["none"] == r["noPw"]["rates"]
    assert r["pw52"]["rates"] == [52, 52, 52, 36]
    # guys x days x rate x 8 hours, and Travel is guys x hours x rate with no 8
    assert r["noPw"]["costs"] == [3 * 5 * 33 * 8, 3 * 0.5 * 33 * 8, 2 * 2 * 33 * 8, 2 * 3 * 36]
    assert r["pw52"]["costs"] == [3 * 5 * 52 * 8, 3 * 0.5 * 52 * 8, 2 * 2 * 52 * 8, 2 * 3 * 36]
    assert r["pw52"]["total"] == sum(r["pw52"]["costs"]) and r["noPw"]["total"] == sum(r["noPw"]["costs"])
    assert r["travelKeeps"] == 36


def test_a_rate_typed_by_hand_wins(ran):
    """Mock-up typed at 40 stays 40 while the other lines follow the card. A cleared box is the line's default
    again, typing 0 is still an answer (0), a line the Labor Calculator filled follows, and a saved bid's row with
    no stamp (nothing to compare its rate to) is never moved.

    Mutation: rateTypedByHand answers false."""
    r = ran["rates"]
    assert r["typedWins"]["mockup"] == 40 and r["typedWins"]["polishing"] == 52
    assert r["typedWins"]["follows"] == [True, False]
    assert r["typedWins"]["rates"] == 3 * 5 * 52 * 8 + 3 * 0.5 * 40 * 8 + 2 * 2 * 52 * 8 + 2 * 3 * 36
    assert r["cleared"] == {"rate": 52, "box": 52, "off": 33}
    assert r["zeroIsTyped"] == {"rate": 0, "cost": 0}
    assert r["unstampedRowIsNeverMoved"] == 33
    assert r["calcRowFollows"] == 52 and r["calcRowTyped"] == 55


def test_switching_it_off_puts_every_line_back_on_its_own_rate(ran):
    """The line keeps its own default under the prevailing one, so nothing has to be remembered."""
    r = ran["rates"]
    assert r["noPw"]["rates"] == [33, 33, 33, 36]
    assert r["junkPw"] == [33, 33, 33], "a pw that is not a positive number is no prevailing wage"
    assert r["offRow"] == 0, "a row switched off still adds nothing"


def test_a_gyp_hours_line_and_the_extra_joint_filler_hand_follow_too(ran):
    """A Gyp pour is priced by the hour with no 8 hour day; the extra hand on Joint Filler (Remove existing)
    is that line's rate.

    Mutation: removeExistingHand reads the line's own rate."""
    r = ran["rates"]
    assert r["gypHours"]["at52"] == r["gypHours"]["expected"] == 4 * 6 * 52
    assert r["gypHours"]["at33"] == pytest.approx(4 * 6 * 33.66)
    assert r["removeExisting"] == {"off": 1 * 2 * 33 * 8, "on": 1 * 2 * 52 * 8, "expected": 832}


def test_the_rate_box_shows_what_the_line_prices_at(ran):
    b = ran["rates"]["box"]
    assert b == {"following": 52, "typed": 40, "travel": 36, "noPw": 33}


# ══ 3. every section of the bid ═════════════════════════════════════════════════════════════════════
def test_every_section_prices_at_the_prevailing_rate(ran):
    """A Polish root, an Epoxy base and a Seal option, through the real chain: each one's labor is its own
    guys x days x 52 x 8 with the switch on, and x 33 x 8 with it off.

    Mutation: leave `pw` out of priceSection's laborTotal (Epoxy and Seal), or out of polishBid's (the root)."""
    s = ran["sections"]
    assert s["off"] == s["expectedOff"] and s["on"] == s["expectedOn"]
    assert s["expectedOn"] == {"Polish": 6240, "Epoxy": 4992, "Seal": 832}
    assert all(s["totalsMove"].values()), "the bid total moves with the labor in every section"


def test_the_five_percent_escalation_is_exactly_what_it_was(ran):
    """The switch still adds 5% of the labor figure and nothing else; off it adds nothing. A switch that is on
    with no rate set prices the labor as before (the escalation is the old behaviour on its own)."""
    s = ran["sections"]
    assert s["escalationOn"] == s["escalationOnExpected"]
    assert s["escalationOff"] == {"Polish": 0, "Epoxy": 0, "Seal": 0}
    assert s["onNoRate"] == {"Epoxy": 3168, "Polish": 3960, "escalation": 198}, s["onNoRate"]


def test_a_rate_typed_on_one_section_wins_there_only(ran):
    t = ran["sections"]["typedOnEpoxy"]
    assert t["Epoxy"] == t["expected"] == 3 * 4 * 40 * 8
    assert t["Polish"] == 6240, "the root's own line still follows the card"


def test_a_save_carries_the_block_and_stamps_the_totals_priced_at_the_prevailing_rate(ran):
    """Mutation: migrateModel stops reading `prevailing` (the save loses the card)."""
    s = ran["sections"]["save"]
    # the save passes the block through as the model holds it; the page's model is always the current shape,
    # because a bid is read through normalizePrevailing when it is opened (blockKept below)
    assert s["carried"] == {"trade": "cement_mason", "rate": 40, "fringes": 12}
    assert s["totalsLabor"] == 6240 and s["epoxyTotalsLabor"] == 4992


def test_the_sheet_counts_nights_over_the_prevailing_rate_and_a_blank_rate_is_not_missing(ran):
    """Polish rev 2 counts Lodging nights from the labor dollars over the first labor rate, so the rate that
    divides them is the prevailing one; and the blockers list does not ask for the rate of a line the prevailing
    wage prices.

    Mutation: leave the prevailing rate out of travelOpts / sheetNights / blockers."""
    s = ran["sections"]
    n = s["rev2Nights"]
    assert n["optsPrevailing"] == 52
    assert n["qty"] == pytest.approx(n["expected"])
    assert s["blockers"] == {"plain": ["Add the rate for Polishing"], "withPw": []}


# ══ 4. a saved bid prices exactly as before ═════════════════════════════════════════════════════════
def test_a_saved_bid_with_no_card_prices_and_saves_exactly_as_before(ran):
    """A bid saved with the prevailing wage switch ON and no `prevailing` key (every saved bid) prices the way it
    did: no pw, the same labor, the same escalation, the same total. It gains no key when migrated or saved, and a
    block stored beside a switch that is off applies nothing and survives a second migration unchanged.

    Mutation: migrateModel invents a block for a bid that has none."""
    s = ran["saved"]
    assert s["migratedHasBlock"] is False and s["savePatchHasBlock"] is False
    assert s["applied"] == 0
    assert (s["labor"], s["total"], s["escalation"]) == (s["laborBefore"], s["totalBefore"], s["escalationBefore"])
    assert s["escalation"] > 0, "the saved bid has the switch on, so the 5% escalation is in this figure"
    # a bid saved in the FIRST shape (one trade per bid) opens in the current one, its figures on its trade
    assert s["blockKept"] == {"trade": "painter", "trades": _trades(painter=(40, 12))} and s["offFlagApplied"] == 0
    assert s["migrateTwice"] is True
    assert s["savedRowRate"] == 33 and s["stampedRowAtZero"] == 33
    assert ran["sections"]["hasBlockOnAFreshSave"] is False, "a model that never used the card saves no block"


# ══ 5. the card on the real page ════════════════════════════════════════════════════════════════════
def test_a_new_bid_opens_with_an_empty_card_above_the_labor_lines_and_writes_nothing(ran):
    """Rate and fringes start EMPTY, like every quantity. The card is a container like the others, at the BOTTOM
    of the Labor step (Hanz, 2026-10-15: "prevailing wage should be at the bottom not at the top"), after the
    labor lines, the travel block and the prevailing-wage caption, with the job's switch in its header, and
    opening the step saves nothing and adds no key.

    Mutation: do not draw the card in laborPanel."""
    f = ran["page"]["fresh"]
    assert f["card"]["rate"] == "" and f["card"]["fringes"] == "", "rate and fringes start empty"
    assert f["card"]["total"] == "" and f["card"]["entry"] == "", "nothing worked out until a rate is typed"
    assert f["card"]["sw"] == "false" and f["flag"] is False
    assert f["card"]["trade"] == "cement_mason"
    assert f["hasBlock"] is False and f["saves"] == 0, "opening the Labor step wrote something"
    assert f["order"] == ['data-lab-card="0"', "data-travel-total", "data-pw-state", "data-pw-card"], (
        "the card is the last thing on the Labor step: %s" % f["order"])
    assert f["rateBoxes"] == ["33", "33", "33", "36"]
    assert "tk pwcard inert off" == f["card"]["cls"], "grayed while the job's switch is off, like the other cards"


def test_while_it_is_off_the_card_is_one_line_with_the_off_words(ran):
    """THE COLLAPSED STATE (Hanz, 2026-10-15). Off, the card is its title and its switch plus the words 'Off. Labor
    lines keep their own rates.'; the Trade, Rate, Fringes, the two figures and the minimums hint are in a body that
    is hidden. No line is repriced and there is no second note under it.

    Mutation: draw the body open while the switch is off; lose the off words."""
    c = ran["page"]["fresh"]["card"]
    assert c["bodyHidden"] is True
    assert c["sub"] == "Off. Labor lines keep their own rates."
    assert c["note"] == "", "no second line while it is closed"
    assert c["sw"] == "false" and c["swClass"] == "mw-sw"
    assert c["caption"] == {"state": "off", "esc": ""}, "the line under the labor lines says off too"


def test_switching_it_on_opens_the_card_in_place_with_the_same_switch_node(ran):
    """THE EXPANDED STATE. Pressing the switch shows the body (Trade, Rate, Fringes, the two figures, the minimums
    hint) and the working note, and the page's panel is not rebuilt: the switch is THE SAME NODE afterwards, so the
    focus that was on it is still on it (a rebuild makes a new node and the focus falls to the page). With no rate
    typed yet no labor line moves, and nothing was written to the model but the flag.

    Mutation: the click rebuilds the panel (changed(true)); the body stays hidden; the switch is not repainted."""
    o = ran["page"]["opened"]
    assert o["sameNode"] is True and o["rebuilt"] == 0
    assert o["card"]["bodyHidden"] is False and o["card"]["cls"] == "tk pwcard"
    assert o["card"]["sw"] == "true" and o["card"]["swClass"] == "mw-sw on"
    assert o["card"]["sub"] == "Cement Mason"
    assert o["card"]["note"] == ("Cement Mason has no rate yet. Type its rate and fringes, or pick another trade "
                                  "with Labor lines use this rate.")
    assert o["card"]["caption"]["state"] == "on" and "5% escalation" in o["card"]["caption"]["esc"]
    assert o["flag"] is True and o["hasBlock"] is False
    assert o["rateBoxes"] == ["33", "33", "33", "36"], "no rate typed, so no line moved"


def test_the_card_says_the_two_notes_in_plain_words(ran):
    text = ran["page"]["hints"]["text"]
    assert "Foreman min. $32, entry min. $23." in text
    assert "1:1 entry laborer, Missouri state wage only, not Davis-Bacon." in text
    assert "Rate plus fringes is the prevailing wage rate." in text
    html = ran["page"]["fresh"]["cardHtml"]
    assert "—" not in html and "–" not in html, "no em or en dash in the card's words"
    assert ran["words"]["hits"] == [], ran["words"]["hits"]


def test_the_card_works_out_52_and_26_then_40_and_23(ran):
    """Rate 40 + fringes 12: 52.00 and 26.00. Rate 30 + fringes 10: 40.00 and the 23.00 minimum, and the lines
    that follow read it.

    Mutation: do not store what is typed (setPrevailing)."""
    p = ran["page"]
    assert p["fortyTwelve"]["card"]["total"] == "$52.00" and p["fortyTwelve"]["card"]["entry"] == "$26.00"
    assert p["fortyTwelve"]["rateBoxes"] == ["52", "52"] and p["fortyTwelve"]["laborTotalText"] == "$7,080"
    assert p["fortyTwelve"]["model"] == {"trade": "cement_mason", "trades": _trades(cement_mason=("40", "12"))}
    assert p["thirtyTen"]["card"]["total"] == "$40.00" and p["thirtyTen"]["card"]["entry"] == "$23.00"
    assert p["thirtyTen"]["rateBoxes"] == ["40", "40"]


def test_switching_it_on_prices_the_labor_lines_at_52_and_travel_stays(ran):
    """The card's own switch is the job's flag. On: the three lines' Rate boxes read 52 (the stored rates are
    untouched), Polishing costs 3 x 5 x 52 x 8, the labor total follows, Travel Labor stays at its own 36, and
    the 5% escalation is added on that labor.

    Mutation: the Rate box shows the stored rate; the repaint leaves the total on the old rate."""
    o = ran["page"]["on"]
    e = o["expected"]
    assert o["flag"] is True and o["card"]["sw"] == "true" and o["card"]["cls"] == "tk pwcard"
    assert o["rateBoxes"] == ["52", "52", "52", "36"]
    assert o["stored"] == [33, 33], "the line's own rate is kept underneath; switching off needs nothing remembered"
    assert o["polishingCost"] == o["polishingCostBox"] == "$6,240" and e["polishing"] == 6240
    assert o["mockupCost"] == "$624" and o["travelCost"] == "$216"
    assert o["laborTotalText"] == "$7,080" and o["bidLabor"] == e["labor"] == 7080
    assert o["escalation"] == e["escalation"] == 354, "the 5% escalation is still 5% of the labor"
    assert all(w["hidden"] for w in o["warns"]), "no 'Default value' note while every line follows its default"


def test_the_card_moves_the_lines_that_follow_it_without_rebuilding_the_step(ran):
    """Typing in the card repaints in place (a rebuild would take the caret): the following lines' boxes, their
    costs and the labor total move with it.

    Mutation: leave the Rate boxes, the line costs or the labor total out of repaintNumbers."""
    m = ran["page"]["moved"]
    assert m["rebuilt"] == 0
    assert m["card"]["total"] == "$54.00" and m["card"]["entry"] == "$27.00"
    assert m["rateBoxes"] == ["54", "54"]
    assert m["polishingCost"] == "$6,480" and m["expectedPolishing"] == 6480
    assert m["bidLabor"] == 7344 and m["laborTotalText"] == "$7,344"


def test_a_line_typed_by_hand_keeps_its_rate_and_names_the_default(ran):
    """Mock-up typed at 40: its box, cost and the bid keep 40 (3 x 0.5 x 40 x 8), the others stay on 52, the
    warning under it says 'Default value: $52.00' (the prevailing rate is now every line's default), and a later
    move of the card does not touch it.

    Mutation: rateDefaultText ignores the prevailing rate."""
    t = ran["page"]["typed"]
    assert t["rateBoxes"] == ["52", "40"] and t["model"] == "40"
    assert t["mockupCost"] == "$480" and t["expectedMockup"] == 480 and t["polishingCost"] == "$6,240"
    assert t["warns"] == [{"text": "", "hidden": True}, {"text": "Default value: $52.00", "hidden": False}]
    assert t["bidLabor"] == 6240 + 480 + 216
    assert t["afterCardMoves"] == {"mockupBox": "40", "polishingBox": "53"}


def test_a_panel_drawn_afresh_with_the_card_on_comes_up_open_and_at_the_prevailing_rate(ran):
    """Review and back (a new paint of the Labor step, not a repaint): the card is open, the following lines' Rate
    boxes read 52, the typed Mock-up 40 and Travel 36, and the cost box agrees.

    Mutation: the first paint reads the stored rate (laborRateBox); the body is always drawn hidden."""
    a = ran["page"]["afterReturn"]
    assert a["card"]["bodyHidden"] is False and a["card"]["sw"] == "true" and a["card"]["swClass"] == "mw-sw on"
    assert a["rateBoxes"] == ["52", "40", "36"] and a["polishingCost"] == "$6,240"
    assert a["warns"] == [{"text": "", "hidden": True}, {"text": "Default value: $52.00", "hidden": False}]


def test_the_review_step_reads_the_same_rate(ran):
    """Mutation: the Review lines read the line's own rate or its own cost."""
    r = ran["page"]["review"]
    assert r["polishing"] and r["mockup"] and r["travel"], r["sample"]


def test_switching_it_off_gives_every_following_line_its_own_rate_back(ran):
    """Back to 33 on the lines that followed, the typed 40 stays, the escalation goes, Travel is as it was."""
    o = ran["page"]["off"]
    e = o["expected"]
    assert o["flag"] is False and o["card"]["cls"] == "tk pwcard inert off"
    assert o["card"]["total"] == "$52.00", "what was typed in the card stays, ready for the next time"
    assert o["card"]["bodyHidden"] is True and o["card"]["sub"] == "Off. Labor lines keep their own rates."
    assert o["card"]["sw"] == "false" and o["card"]["swClass"] == "mw-sw" and o["card"]["note"] == ""
    assert o["block"] == {"trade": "cement_mason", "trades": _trades(cement_mason=("40", "12"))}, (
        "closing it keeps what was typed")
    assert o["card"]["rate"] == "40" and o["card"]["fringes"] == "12", "the boxes are hidden, never emptied"
    assert o["sameNode"] is True and o["rebuilt"] == 0, "closing it rebuilt the panel and dropped the focus"
    assert o["rateBoxes"] == ["33", "40", "36"]
    assert o["stored"] == [33, "40"]
    assert o["polishingCost"] == "$3,960" and e["polishing"] == 3960
    assert o["bidLabor"] == e["labor"] == 4656 and o["laborTotalText"] == "$4,656"
    assert o["escalation"] == 0
    assert o["warns"][0] == {"text": "", "hidden": True}
    assert o["warns"][1] == {"text": "Default value: $33.00", "hidden": False}


def test_opening_it_again_shows_what_was_stored_and_the_lines_follow_it_again(ran):
    """Closed and opened once more: the trade, the rate and the fringes are on screen as they were typed, the
    figures are worked out, the lines that follow read 52 again, the typed Mock-up stays 40, and the panel was not
    rebuilt on the way.

    Mutation: closing the card clears the block; the repaint leaves the body hidden."""
    r = ran["page"]["reopened"]
    assert r["sameNode"] is True and r["rebuilt"] == 0
    c = r["card"]
    assert c["bodyHidden"] is False and c["sw"] == "true" and c["swClass"] == "mw-sw on"
    assert (c["trade"], c["rate"], c["fringes"]) == ("cement_mason", "40", "12")
    assert (c["total"], c["entry"]) == ("$52.00", "$26.00")
    assert r["rateBoxes"] == ["52", "40", "36"] and r["polishingCost"] == "$6,240"


def test_clearing_a_following_lines_rate_never_writes_the_prevailing_rate_into_it(ran):
    """With the card on, a cleared Rate box goes back to the line's OWN rate in the model (33) and the box keeps
    showing what it prices at (52). If the prevailing rate were written into the line, switching the card off
    would leave that line stuck at 52 as a 'typed' rate.

    Mutation: the clear handler reads the rate with the prevailing wage in force."""
    c = ran["page"]["cleared"]
    assert c["stored"] == 33 and c["box"] == "52" and c["cost"] == "$6,240"
    assert c["afterOff"] == {"stored": 33, "box": "33", "cost": "$3,960"}


def test_the_crew_is_paid_the_trade_picked_and_typing_another_trade_moves_nothing(ran):
    """Each trade works out its own figures; only the one marked "Labor lines use this rate" sets the lines.

    Mutation: prevailingTotal stops following the picked trade (it reads the first)."""
    t = ran["page"]["trade"]
    typed = t["typedPainter"]
    assert typed["sameBid"] is True and typed["box"] == "52", "typing the painter's figures moved the crew"
    assert (typed["painterTotal"], typed["painterEntry"]) == ("$40.00", "$23.00")
    assert t["model"]["trade"] == "painter" and t["card"]["trade"] == "painter" and t["card"]["sub"].startswith("Painter")
    assert t["box"] == "40" and t["travel"] == "36" and t["movedBid"] is True
    assert t["crewClass"] == ["pwtrade", "pwtrade paid"]


def test_the_first_figures_typed_pick_their_trade_and_the_note_names_it(ran):
    """Found in review: with Cement Mason picked and empty, typing only the Painter box moved nothing and the note
    said "no rate yet", so a painting job went out at the lines' own rates. Now the first figures typed pick their
    trade; once the picked trade has a rate, another trade's figures move nothing.

    Mutation: drop the auto-pick in setPrevailing; the note stops naming the trade."""
    t = ran["trades"]
    assert t["noRate"]["note"].startswith("Cement Mason has no rate yet."), t["noRate"]
    a = t["autoPick"]
    assert a["trade"] == "painter" and a["box"] == "40" and a["paid"] == "pwtrade paid"
    assert a["note"].startswith("Labor lines price at $40.00") and a["sub"].startswith("Painter")
    assert t["afterOther"] == {"trade": "painter", "box": "40"}


def test_a_trade_name_with_markup_in_it_is_drawn_as_text(ran):
    h = ran["trades"]["hostile"]
    assert h["rawImg"] is False and h["escaped"] is True
    assert h["sub"].startswith("Painter"), "the header names the trade the lines use, not the newest"


def test_removing_a_trade_from_the_middle_leaves_every_later_box_on_its_own_trade(ran):
    m = ran["trades"]["middle"]
    assert m["keys"] == ["cement_mason", "painter", "t1", "t3"]
    assert m["third"] == {"key": "t3", "label": "Third", "rate": "20", "fringes": "5"}
    assert m["removes"] == 2, "only the estimator's own trades can be removed"


def test_a_trade_of_our_own_can_be_added_named_paid_and_removed(ran):
    """Hanz, 2026-10-15: "there is a prevailing wage for others apart from the painter and mason ... we can label
    it on our own". + Add a trade adds a box with a name box; paying the crew it moves the lines; removing it puts
    the crew back on the first trade. The sheet's two cannot be removed.

    Mutation: the Remove button does nothing; + Add a trade does nothing."""
    a = ran["page"]["added"]
    assert a["names"] == 1, "a new trade has a name box, and only it does"
    assert a["model"]["trades"][2] == {"key": "t1", "label": "", "rate": "", "fringes": ""}
    p = a["picked"]
    assert p["box"] == "33" and p["sub"].startswith("Laborer") and p["total"] == "$33.00"
    assert p["model"]["trade"] == "t1" and p["model"]["trades"][2]["label"] == "Laborer"
    r = a["removed"]
    assert r["boxes"] == 2 and r["builtinsHaveNoRemove"] == 0
    assert r["model"]["trade"] == "cement_mason" and len(r["model"]["trades"]) == 2
    assert r["box"] == "52", "with our trade gone the crew is paid the cement mason rate again"


def test_the_switch_answers_the_keyboard_and_the_save_carries_the_card(ran):
    """Mutation: take `[data-cond]` out of the keydown handler; the autosave stops carrying the block."""
    p = ran["page"]
    k = p["keyboard"]
    assert (k["before"], k["after"]) == (True, False), "Space on the switch flips the job's flag"
    assert k["bodyHiddenAfter"] is True and k["caption"] == "off"
    assert k["sameNode"] is True and k["rebuilt"] == 0, "the keyboard press rebuilt the panel under the focus"
    assert p["saved"]["block"] == {"trade": "painter",
                                   "trades": _trades(cement_mason=("40", "12"), painter=("30", "10"))}


def test_the_card_and_the_rate_are_on_every_sections_labor_step(ran):
    """An Epoxy base and a Seal option of the same job: the card is drawn on each Labor step with the same
    figures, each line's box reads 52, its cost and the section's own bid use 52, and the stored rate is untouched.

    Mutation: do not draw the card in laborPanel; price a section without the prevailing rate."""
    sp = ran["sectionPage"]
    for tab in ("Epoxy", "Seal"):
        d = sp[tab]
        assert d["card"] is True and d["total"] == "$52.00", tab
        assert d["rateBox"] == "52" and d["stored"] == 33, tab
        money = "${:,}".format(sp["expected"][tab])
        assert d["cost"] == money and d["laborTotal"] == money, tab
        assert d["sectionBidLabor"] == sp["expected"][tab], tab


def test_the_conditions_own_words_say_only_what_each_screen_does(ran):
    """The words under the switch were 'Raises every labor line to the prevailing rate', which the sheet never did
    (Polish C46 only adds the 5% escalation; the estimator types the rate into the labor lines). Only the v2 Labor
    step's card sets the rate, so the live intake says what the workbook does and tells the estimator to type the
    rate, and the v2 intake says the lines follow the rate typed on the Labor step. js/work-types.js holds both
    (`why` for the live screen, `wording.v2Intake`); js/index.js keeps the live literal and test_work_types holds
    the two equal.

    Mutation: the live sentence goes back to claiming the lines are set (a screen where nothing sets them)."""
    w = ran["figures"]["words"]
    assert w["live"] == "Adds the 5% labor escalation. Type the prevailing rate on the labor lines yourself."
    assert w["v2Intake"] == "Adds the 5% labor escalation. Type the prevailing rate on the Labor step and the labor lines follow it."
    assert ran["figures"]["why"] == w["live"]
    for text in w.values():
        assert "\u2014" not in text and "\u2013" not in text, "no em or en dash in the words"


# ══ a typed rate that IS the line's default, the nights hint, and the step pips ═══════════════════════
def test_a_rate_typed_to_the_lines_own_default_is_marked_so_the_numbers_need_not_say_it(ran):
    """Typing 33 on a line whose default is 33 looks exactly like a line that follows its default, so the one
    place a Rate box is written (B.setLaborRate) marks that case on the row (`rate_typed`). The mark makes the line
    the estimator's own: it prices at 33 while the card says 52, its box says 33, and it survives a reload. Any
    other rate says it already by the numbers, so no mark is written on it, and the mark goes the moment the rate
    is something else (a different number, blank). A saved bid's row with no default to compare to is never
    marked: its rate is already read as typed.

    Mutation: do not mark it; do not read the mark."""
    r = ran["rates"]["typedAtDefault"]
    a = r["atDefault"]
    assert a["mark"] is True and a["rate"] == "33"
    assert a["atPrevailing"] == 33 and a["follows"] is False and a["box"] == "33" and a["isTyped"] is True
    assert a["cost"] == 3 * 5 * 33 * 8 and a["atZero"] == 33
    assert r["other"] == {"marked": False, "atPrevailing": 34}
    assert r["cleared"] == {"marked": False, "rate": "", "follows": True, "atPrevailing": 52}
    assert r["backTo"] == {"mark": True, "atPrevailing": 33}, "typed 34 then 33 again is typed 33"
    assert r["noDefault"] == {"marked": False, "atPrevailing": 33}
    assert r["calcRow"] == {"mark": True, "atPrevailing": 50}, "a Labor Calculator line, typed to its filled rate"
    assert r["notARow"] == "no throw"
    assert r["reopened"] == {"mark": True, "rate": "33", "atPrevailing": 33, "bidLabor": 3960, "expected": 3960}, \
        "the mark rides the saved row through migrateModel, and the reloaded bid prices the typed 33"


def test_typing_the_default_on_the_page_keeps_the_line_at_that_rate_while_the_prevailing_wage_is_on(ran):
    """THE REVIEWER'S SCENARIO. Prevailing wage on, 40 + 12 = 52, Polishing 3 x 5. Type 33 into its Rate box: the
    box, the cost, the labor total and the bid all say 33 (3 x 5 x 33 x 8 = $3,960), not the 52 the box used to flip
    back to; the note under the box names the default it differs from; a move of the card's rate leaves it alone
    (and the note follows); Review, the save and a panel drawn afresh agree; the mark goes with a cleared box
    (whether `input` fired or only `change`), a different number is typed on the numbers alone, and typing 33
    again marks it once more.

    Mutation: the Rate box skips B.setLaborRate (the page); the mark is not written or not read (the model);
    the change handler leaves the mark on a cleared box."""
    p = ran["typedAtDefaultPage"]
    assert p["following"]["box"] == "52" and p["following"]["cost"] == "$6,240" and p["following"]["mark"] is None
    # (the card's fringes go from 12 to 13 after "blurred", so the default the line differs from is $52.00, then $53.00)
    for step, default in (("typing", "$52.00"), ("blurred", "$52.00"), ("cardMoved", "$53.00"), ("afterReturn", "$53.00")):
        s = p[step]
        assert (s["box"], s["cost"], s["costBox"], s["laborTotal"]) == ("33", "$3,960", "$3,960", "$3,960"), step
        assert s["bidLabor"] == 3960 and s["rate"] == "33" and s["mark"] is True, step
        assert s["warn"] == "Default value: " + default and s["warnHidden"] is False, step
    assert p["review"]["typed"] is True, p["review"]["sample"]
    assert p["saved"] == {"rate": "33", "mark": True}, "the save carries the typed rate and its mark"
    for step in ("clearedByChange", "clearedByTyping"):
        s = p[step]
        assert (s["box"], s["cost"], s["bidLabor"]) == ("53", "$6,360", 6360), step
        assert s["mark"] is None and s["rate"] == 33 and s["warnHidden"] is True, step
    assert p["typedAgain"]["mark"] is True and p["typedAgain"]["cost"] == "$3,960"
    assert p["thirtyFour"]["mark"] is None and p["thirtyFour"]["cost"] == "$4,080" and p["thirtyFour"]["box"] == "34"
    assert p["backToThirtyThree"]["mark"] is True and p["backToThirtyThree"]["cost"] == "$3,960"
    off = p["cardOff"]
    assert (off["box"], off["cost"], off["bidLabor"], off["warnHidden"]) == ("33", "$3,960", 3960, True), \
        "switched off, the line is still at 33 and no prevailing note is shown"


def test_the_lodging_hint_counts_nights_over_the_prevailing_rate_like_the_page_prices_them(ran):
    """Polish rev 2, not local, 40 + 12, Polishing following the card (52) and Mock-up typed at 40: the sheet counts
    (6,240 + 480) / 52 / 8 = 16.15 nights, and that is what the Lodging hint says under a typed box, the same as
    the working lines and the price. It said 16.82 (the count at $33) because lodgingHint left the prevailing rate
    out of sheetNights. With the switch off the count is the old one, 16.82.

    Mutation: leave opts.prevailing out of the call in lodgingHint."""
    d = ran["lodging"]
    assert d["on"]["count"] == pytest.approx(d["expectedOn"]) and round(d["expectedOn"], 2) == 16.15
    assert d["on"]["hint"] == "Nights from the labor above, as the sheet counts them: 16.15."
    assert d["on"]["auto"] == "Nights counted from the labor above, as the sheet does."
    assert d["page"]["on"] == d["on"]["hint"], "the page draws the same hint"
    assert d["off"]["count"] == pytest.approx(d["expectedOff"]) and round(d["expectedOff"], 2) == 16.82
    assert d["off"]["hint"] == d["page"]["off"] == "Nights from the labor above, as the sheet counts them: 16.82."


def test_the_step_pips_count_a_line_the_prevailing_wage_prices(ran):
    """A saved bid from before the rate stamp has a labor line with guys 3, days 5 and a BLANK rate, which only
    the prevailing wage prices (the card is on at 52, so $6,240, and blockers() asks for nothing). The Labor and
    Review pips are ok then, as they would be for any priced line; with the switch off the same line prices
    nothing, blockers() asks for its rate, and both pips stay grey.

    Mutation: stepStatus prices the labor without the prevailing rate."""
    s = ran["steps"]
    assert s["on"]["bidLabor"] == 6240 and s["on"]["blockers"] == [] and s["on"]["rate"] == ""
    assert s["on"]["step"] == {"takeoff": "ok", "labor": "ok", "review": "ok"}
    assert s["off"]["bidLabor"] == 0 and s["off"]["blockers"] == ["Add the rate for Polishing"]
    assert s["off"]["step"] == {"takeoff": "ok", "labor": "", "review": ""}


# ══ red without the code: break a COPY and watch each fact notice ═══════════════════════════════════
MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"
MUTATIONS = {
    "laborRateOf ignores the prevailing rate": (
        MODEL, "    if (laborFollowsPrevailing(row, pw)) return num(pw);", "    void pw;",
        lambda r: r["rates"]["pw52"]["rates"] == [33, 33, 33, 36] and r["sections"]["on"] == r["sections"]["off"]),
    "a typed rate no longer wins": (
        MODEL, "    return own === null || num(row.rate) !== own;", "    return false;",
        lambda r: r["rates"]["typedWins"]["mockup"] == 52 and r["sections"]["typedOnEpoxy"]["Epoxy"] == 4992),
    "travel labor is moved too": (
        MODEL, '  function isTravelRow(row) { return !!row && String(row.id) === "travel"; }',
        "  function isTravelRow(row) { return false; }",
        lambda r: r["rates"]["travelKeeps"] == 52),
    "a section is priced without the prevailing rate": (
        MODEL, "      labor: laborTotal(s.labor, model.conditions, prevailingApplied(model)),",
        "      labor: laborTotal(s.labor, model.conditions),",
        lambda r: r["sections"]["on"]["Epoxy"] == 3168 and r["sections"]["on"]["Seal"] == 528),
    "the Polish root is priced without the prevailing rate": (
        MODEL, "    var labor = laborTotal(s.labor, model.conditions, prevailingApplied(model));",
        "    var labor = laborTotal(s.labor, model.conditions);",
        lambda r: r["sections"]["on"]["Polish"] == 3960),
    "the entry wage has no floor": (
        MODEL, "    return half < PREVAILING.ENTRY_MIN ? PREVAILING.ENTRY_MIN : half;", "    return half;",
        lambda r: r["figures"]["thirtyTen"]["entry"] == 20 and r["page"]["thirtyTen"]["card"]["entry"] == "$20.00"),
    "the fringes are not added": (
        MODEL, "    return parseFloat((num(p.rate) + num(p.fringes)).toPrecision(12));",
        "    return parseFloat(num(p.rate).toPrecision(12));",
        lambda r: r["figures"]["fortyTwelve"]["total"] == 40 and r["page"]["fortyTwelve"]["card"]["total"] == "$40.00"),
    "the switch is not asked": (
        MODEL, "    if (!(model.conditions && model.conditions.prevailing_wage)) return 0;", "    void model;",
        lambda r: r["figures"]["applied"]["offWith52"] == 52 and r["page"]["off"]["rateBoxes"][0] == "52"),
    "migrate stops reading the block": (
        MODEL, "      if (pwBlock) out.prevailing = pwBlock;", "      void pwBlock;",
        lambda r: r["saved"]["blockKept"] is None and r["sections"]["save"]["carried"] is None),
    "migrate invents a block for a bid that has none": (
        MODEL, "      if (pwBlock) out.prevailing = pwBlock;",
        "      out.prevailing = pwBlock || normalizePrevailing({});",
        lambda r: r["saved"]["migratedHasBlock"] is True),
    "the nights are counted without the prevailing rate": (
        MODEL, "    if (pw > 0) opts.prevailing = pw;", "    void pw;",
        lambda r: r["sections"]["rev2Nights"]["optsPrevailing"] is None),
    "the sheet nights ignore the prevailing rate in the labor dollars": (
        MODEL, "    return engine.lodgingNights(REV2, roundUp(laborTotal(rows, conditions, pw)), travelLabor, rate || SHIPPED_LABOR_RATE);",
        "    return engine.lodgingNights(REV2, roundUp(laborTotal(rows, conditions)), travelLabor, rate || SHIPPED_LABOR_RATE);",
        lambda r: abs(r["sections"]["rev2Nights"]["qty"] - r["sections"]["rev2Nights"]["expected"]) > 0.01),
    "the blockers ask for a rate the prevailing wage supplies": (
        MODEL, '      if (!filledIn(row.rate) && !(laborRateOf(row, prevailingApplied(m)) > 0)) missing.push("rate");',
        '      if (!filledIn(row.rate) && !(laborRateOf(row) > 0)) missing.push("rate");',
        lambda r: r["sections"]["blockers"]["withPw"] == ["Add the rate for Polishing"]),
    "the extra Joint Filler hand is paid the line's own rate": (
        MODEL, "      return laborCost({ guys: 1, days: r.days, rate: laborRateOf(r, pw), unit: r.unit,",
        "      return laborCost({ guys: 1, days: r.days, rate: laborRateOf(r), unit: r.unit,",
        lambda r: r["rates"]["removeExisting"]["on"] == 528),
    "the Rate box shows the stored rate": (
        PAGE, "      esc(nv(B.laborRateBox(r, pw))) + '\"></span>' +", "      esc(nv(r.rate)) + '\"></span>' +",
        lambda r: r["page"]["afterReturn"]["rateBoxes"][:1] == ["33"]),
    "the Labor step draws no card": (
        PAGE, '    html += prevailingCard();', '    void 0;',
        lambda r: "error" in r["page"] or r["sectionPage"]["Epoxy"]["card"] is False),
    "typing in the card stores nothing": (
        PAGE, '      setPrevailing(pwField, el.value, parseInt(el.getAttribute("data-pw-i"), 10));', "      void pwField;",
        lambda r: r["page"]["fortyTwelve"]["card"]["total"] == ""),
    "the line costs do not repaint on the prevailing rate": (
        PAGE, '        el.getAttribute("data-lcost-for"), 10)], pwNow));',
        '        el.getAttribute("data-lcost-for"), 10)]));',
        lambda r: r["page"]["moved"]["polishingCost"] != "$6,480"),
    "the labor total does not repaint on the prevailing rate": (
        PAGE, '    one("[data-labor-total]", moneyAuto(B.laborTotal(M.labor, M.conditions, pwNow)));',
        '    one("[data-labor-total]", moneyAuto(B.laborTotal(M.labor, M.conditions)));',
        lambda r: r["page"]["moved"]["laborTotalText"] != "$7,344"),
    "the Rate boxes do not repaint when the card moves": (
        PAGE, "      var v = nv(B.laborRateBox(r, pwNow));", "      var v = nv(r.rate);",
        lambda r: r["page"]["moved"]["rateBoxes"] != ["54", "54"]),
    "the entry half wage does not repaint": (
        PAGE, '      el.textContent = sum > 0 ? B.money2(B.entryHalfWage(sum)) : "";',
        "      el.textContent = el.textContent;",
        lambda r: r["page"]["moved"]["card"]["entry"] != "$27.00"),
    "a cleared box writes the prevailing rate into the line": (
        PAGE, "        var back = B.laborRateOf(rateRow);", "        var back = B.laborRateOf(rateRow, B.prevailingApplied(M));",
        lambda r: r["page"]["cleared"]["stored"] == 52 and r["page"]["cleared"]["afterOff"]["box"] == "52"),
    "the review cost ignores the prevailing rate": (
        PAGE, "      var cost = B.laborCost(r, pwRev);", "      var cost = B.laborCost(r);",
        lambda r: r["page"]["review"]["polishing"] is False),
    "the review rate ignores the prevailing rate": (
        PAGE, "B.money2(B.laborRateOf(r, pwRev)),", "B.money2(B.laborRateOf(r)),",
        lambda r: r["page"]["review"]["polishing"] is False),
    "the default note ignores the prevailing rate": (
        PAGE, "    if (B.num(pw) > 0 && !B.isTravelRow(row)) {", "    if (false) {",
        lambda r: r["page"]["typed"]["warns"][1]["text"] != "Default value: $52.00"),
    "the switch does not answer the keyboard": (
        PAGE, 'var sw = t.closest("[data-on-tk]") || t.closest("[data-on-lab]") || t.closest("[data-on-trv]") ||',
        'var sw = t.closest("[data-on-tk]") || t.closest("[data-on-lab]") || t.closest("[data-on-trv]") || null; var unused =',
        lambda r: r["page"]["keyboard"]["after"] is True),
    "the card is drawn open while the switch is off": (
        PAGE, """'</div><div data-pw-body' + (on ? "" : " hidden") + '><div class="pwtrades">' +""",
        """'</div><div data-pw-body><div class="pwtrades">' +""",
        lambda r: r["page"]["fresh"]["card"]["bodyHidden"] is False),
    "the card is always drawn closed": (
        PAGE, """'</div><div data-pw-body' + (on ? "" : " hidden") + '><div class="pwtrades">' +""",
        """'</div><div data-pw-body hidden><div class="pwtrades">' +""",
        lambda r: r["page"]["afterReturn"]["card"]["bodyHidden"] is True),
    "switching it does not show or hide the body": (
        PAGE, 'document.querySelectorAll("[data-pw-body]").forEach(function (el) { el.hidden = !pwOn; });',
        'document.querySelectorAll("[data-pw-body]").forEach(function (el) { el.hidden = el.hidden; });',
        lambda r: r["page"]["opened"]["card"]["bodyHidden"] is True and r["page"]["off"]["card"]["bodyHidden"] is False),
    "pressing the card's switch rebuilds the panel": (
        PAGE, 'changed(cond.getAttribute("data-pw-sw") === null);', "changed(true);",
        lambda r: r["page"]["opened"]["sameNode"] is False and r["page"]["opened"]["rebuilt"] >= 1
        and r["page"]["keyboard"]["sameNode"] is False),
    "the card's switch is not repainted in place": (
        PAGE, 'el.setAttribute("aria-checked", pwOn ? "true" : "false");', "void pwOn;",
        lambda r: r["page"]["off"]["card"]["sw"] == "true" and r["page"]["opened"]["card"]["sw"] == "false"),
    "the closed card loses its off words": (
        PAGE, 'if (!(M.conditions || {}).prevailing_wage) return "Off. Labor lines keep their own rates.";',
        'if (!(M.conditions || {}).prevailing_wage) return "";',
        lambda r: r["page"]["fresh"]["card"]["sub"] == "" and r["page"]["off"]["card"]["sub"] == ""),
    "the caption under the labor lines is not repainted": (
        PAGE, 'document.querySelectorAll("[data-pw-state]").forEach(function (el) { el.textContent = pwOn ? "on" : "off"; });',
        "void pwOn;",
        lambda r: r["page"]["opened"]["card"]["caption"]["state"] == "off"),
    "a rate typed to the line's default is not marked": (
        MODEL, "    if (!isBlank(value) && own !== null && num(value) === own) row.rate_typed = true;",
        "    if (false) row.rate_typed = true;",
        lambda r: r["rates"]["typedAtDefault"]["atDefault"]["atPrevailing"] == 52
        and r["typedAtDefaultPage"]["typing"]["cost"] == "$6,240"),
    "the typed mark is not read": (
        MODEL, "    if (row.rate_typed === true) return true;", "    void row;",
        lambda r: r["rates"]["typedAtDefault"]["atDefault"]["atPrevailing"] == 52
        and r["typedAtDefaultPage"]["blurred"]["cost"] == "$6,240"),
    "the Rate box does not go through setLaborRate": (
        PAGE, 'if (k === "rate") B.setLaborRate(M.labor[j], el.value);', 'if (false) B.setLaborRate(M.labor[j], el.value);',
        lambda r: r["typedAtDefaultPage"]["typing"]["cost"] == "$6,240" and r["typedAtDefaultPage"]["afterReturn"]["mark"] is None),
    "a cleared box keeps the typed mark": (
        PAGE, "delete rateRow.rate_typed;", "void rateRow;",
        lambda r: r["typedAtDefaultPage"]["clearedByChange"]["mark"] is True
        and r["typedAtDefaultPage"]["clearedByChange"]["box"] == "33"),
    "the step pips price the labor without the prevailing rate": (
        PAGE, "M.labor.forEach(function (r) { if (B.laborCost(r, pwStep) > 0) lab += 1; });",
        "M.labor.forEach(function (r) { if (B.laborCost(r) > 0) lab += 1; });",
        lambda r: r["steps"]["on"]["step"]["labor"] == "" and r["steps"]["on"]["step"]["review"] == ""),
    "the crew is not paid the trade picked": (
        MODEL, "    if (p.trades instanceof Array) p = prevailingCrewTrade(p) || {};",
        "    if (p.trades instanceof Array) p = p.trades[0] || {};",
        lambda r: r["page"]["trade"]["box"] != "40" or r["figures"]["normalised"]["ownCrewTotal"] != 33),
    "the first shape's rate is dropped": (
        MODEL, "      legacy.rate = box(p.rate);", "      void legacy;",
        lambda r: r["figures"]["normalised"]["painter"]["trades"][1]["rate"] != "40"),
    "Remove does nothing": (
        PAGE, "      if (removePrevailingTrade(parseInt(pwDel.getAttribute(\"data-pw-del\"), 10))) changed(true);",
        "      void pwDel;",
        lambda r: r["page"]["added"]["removed"]["boxes"] != 2),
    "+ Add a trade does nothing": (
        PAGE, "      var at = addPrevailingTrade();", "      var at = 2;",
        lambda r: "error" in r["page"] or r["page"]["added"]["model"]["trades"][2:] == []),
    "typing another trade's figures never picks it": (
        PAGE, "        !(B.prevailingTotal(B.prevailingCrewTrade(cur)) > 0)) cur.trade = t.key;",
        "        false) cur.trade = t.key;",
        lambda r: r["trades"]["autoPick"]["trade"] != "painter"),
    "the note does not name the trade": (
        PAGE, 'if (!(total > 0)) return pwTradeLabel(M.prevailing) + " has no rate yet.',
        'if (!(total > 0)) return "On, with no rate yet." + " has no rate yet.',
        lambda r: not r["trades"]["noRate"]["note"].startswith("Cement Mason")),
    "the lodging hint counts nights without the prevailing rate": (
        MODEL, "var days = travelManDays(rows), nights = sheetNights(rows, opts.conditions, opts.prevailing);",
        "var days = travelManDays(rows), nights = sheetNights(rows, opts.conditions);",
        lambda r: r["lodging"]["on"]["hint"].endswith("16.82.") and r["lodging"]["page"]["on"].endswith("16.82.")),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_facts_go_red_when_the_code_changes(tmp_path, name):
    """Each change is the kind a refactor makes by accident, applied to a scratch copy of the page and the core.
    The anchor must be in the file exactly once (break_source refuses otherwise)."""
    rel, old, new, noticed = MUTATIONS[name]
    # one line of text, found exactly once: the indentation is not part of the anchor
    frontend = break_source(tmp_path, rel, old.strip(), new.strip())
    copy_unmodified(frontend, SCRATCH_FRONTEND_FILES)
    got = _run(frontend)
    try:
        seen = noticed(got)
    except (KeyError, TypeError):
        seen = True      # the section did not even finish: the real run reports that as a failure too
    assert seen, "the facts did not notice: " + name
