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
    for name in ("figures", "rates", "sections", "saved", "page", "sectionPage"):
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


def test_one_trade_per_bid_and_it_is_only_a_label(ran):
    f = ran["figures"]
    assert f["trades"] == [["cement_mason", "Cement Mason"], ["painter", "Painter"]]
    n = f["normalised"]
    assert n["badTrade"] == "cement_mason", "an unknown trade reads as the first"
    assert n["painter"] == {"trade": "painter", "rate": "40", "fringes": 12}
    assert n["keepsHalfTyped"] == "12.", "a half typed number must not snap while somebody is typing it"
    assert n["none"] is None and n["notAnObject"] is None and n["list"] is None
    assert n["empty"] == {"trade": "cement_mason", "rate": "", "fringes": ""}


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
    assert s["blockKept"] == {"trade": "painter", "rate": 40, "fringes": 12} and s["offFlagApplied"] == 0
    assert s["migrateTwice"] is True
    assert s["savedRowRate"] == 33 and s["stampedRowAtZero"] == 33
    assert ran["sections"]["hasBlockOnAFreshSave"] is False, "a model that never used the card saves no block"


# ══ 5. the card on the real page ════════════════════════════════════════════════════════════════════
def test_a_new_bid_opens_with_an_empty_card_above_the_labor_lines_and_writes_nothing(ran):
    """Rate and fringes start EMPTY, like every quantity. The card is a container like the others, ahead of the
    first labor line, with the job's switch in its header, and opening the step saves nothing and adds no key.

    Mutation: do not draw the card in laborPanel."""
    f = ran["page"]["fresh"]
    assert f["card"]["rate"] == "" and f["card"]["fringes"] == "", "rate and fringes start empty"
    assert f["card"]["total"] == "" and f["card"]["entry"] == "", "nothing worked out until a rate is typed"
    assert f["card"]["sw"] == "false" and f["flag"] is False
    assert f["card"]["trade"] == "cement_mason"
    assert f["hasBlock"] is False and f["saves"] == 0, "opening the Labor step wrote something"
    assert f["order"] == ["data-pw-card", 'data-lab-card="0"'], "the card sits above the labor lines"
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
    assert o["card"]["note"] == "On, with no rate yet. Type the rate and fringes to set the labor lines."
    assert o["card"]["caption"]["state"] == "on" and "5% escalation" in o["card"]["caption"]["esc"]
    assert o["flag"] is True and o["hasBlock"] is False
    assert o["rateBoxes"] == ["33", "33", "33", "36"], "no rate typed, so no line moved"


def test_the_card_says_the_two_notes_in_plain_words(ran):
    text = ran["page"]["hints"]["text"]
    assert "Foreman min. $32, entry min. $23." in text
    assert "1:1 entry laborer, Missouri state wage only, not Davis-Bacon." in text
    assert "Rate plus fringes." in text
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
    assert p["fortyTwelve"]["model"] == {"trade": "cement_mason", "rate": "40", "fringes": "12"}
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
    assert o["block"] == {"trade": "cement_mason", "rate": "40", "fringes": "12"}, "closing it keeps what was typed"
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


def test_the_trade_is_a_label_that_prices_nothing(ran):
    t = ran["page"]["trade"]
    assert t["model"]["trade"] == "painter" and t["card"]["trade"] == "painter" and t["card"]["sub"].startswith("Painter")
    assert t["sameBid"] is True


def test_the_switch_answers_the_keyboard_and_the_save_carries_the_card(ran):
    """Mutation: take `[data-cond]` out of the keydown handler; the autosave stops carrying the block."""
    p = ran["page"]
    k = p["keyboard"]
    assert (k["before"], k["after"]) == (True, False), "Space on the switch flips the job's flag"
    assert k["bodyHiddenAfter"] is True and k["caption"] == "off"
    assert k["sameNode"] is True and k["rebuilt"] == 0, "the keyboard press rebuilt the panel under the focus"
    assert p["saved"]["block"] == {"trade": "painter", "rate": "40", "fringes": "12"}


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


def test_the_conditions_own_words_say_what_it_does(ran):
    """The words under the switch on the intake were 'Raises every labor line to the prevailing rate', which the
    sheet never did. They say what it does now (js/work-types.js; js/index.js keeps the same literal, and
    test_work_types holds the two equal)."""
    assert ran["figures"]["why"] == "Sets the labor lines to the prevailing rate and adds the 5% labor escalation."


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
        PAGE, '    var html = prevailingCard();', '    var html = "";',
        lambda r: "error" in r["page"] or r["sectionPage"]["Epoxy"]["card"] is False),
    "typing in the card stores nothing": (
        PAGE, "      setPrevailing(pwField, el.value);", "      void pwField;",
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
        PAGE, '      el.textContent = pwSum > 0 ? B.money2(B.entryHalfWage(pwSum)) : "";',
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
        PAGE, """'</div><div data-pw-body' + (on ? "" : " hidden") + '><div class="tk-g lab-g pw-g">' +""",
        """'</div><div data-pw-body><div class="tk-g lab-g pw-g">' +""",
        lambda r: r["page"]["fresh"]["card"]["bodyHidden"] is False),
    "the card is always drawn closed": (
        PAGE, """'</div><div data-pw-body' + (on ? "" : " hidden") + '><div class="tk-g lab-g pw-g">' +""",
        """'</div><div data-pw-body hidden><div class="tk-g lab-g pw-g">' +""",
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
