"""THE SHEET BAR: the strip of tabs (and the open sheet's controls under it) that replaced the section strip, the "+ Add option" bar
and, on 2026-10-19, the floating Sheets panel, on the v2 estimate page.

WHAT CHANGED. Sheets phase 1 gave the model copies, fresh sheets of any type, a chosen base bid, renaming and deleting
(js/bid-model.js copySection, addSheet, pickBase, renameSection, deleteSection). Phase 2 gave pages one drag-and-remember helper
(TW.floatPanel). This is the face of it, built from the mockup Hanz approved (2026-10-13):

  * ONE BAR, ON EVERY BID (section#sheets-panel, drawn by B.sheetsPanelHtml, painted by paintSheets). ROW 1 is a strip of tabs, one a
    sheet that is part of the bid: a radio that makes it the base bid, its name and price. ROW 2 is the OPEN sheet only: "Base bid" or what
    it is as an option, the switch "On the proposal as an option", Total or Add / Deduct, the words it prints, Copy, Rename and Delete.
  * "+ Add sheet" is the last tab of the strip. Every type the tool prices is on the menu; a sheet added from it starts ON the
    proposal, and a copy starts OFF.
  * MAKING A SHEET THE BASE asks first ("Make Epoxy the base bid?"), then everything follows: B.pickBase moves the kinds and answers
    work_type, base_tab_id and the old base's tab_opts (ON the proposal, priced as a total), and the lines typed on the Proposal step
    follow the new base by the rule the other two base pickers run (TWPrice.applyBasePick). A combined Epoxy + Polish base is its own
    row and writes work_type "combo" and no base id.
  * Delete takes two presses and is disabled on the base (with the reason beside it). A name is checked when it is committed, never while
    it is typed. Seal sheets are options only: Total, never Add / Deduct, never the base.
  * It does not float. It sits in the flow, in the page's STICKY HEAD: the top bar, then this bar, one block that stays at the top of the screen
    on Material, Labor and Review alike (2026-10-20), above the page heading. The strip scrolls sideways on a narrow screen. No legend line
    stands under it: the base radio says what it means itself.

EVERYTHING RUNS CODE. tests/js/sheets-panel-harness.js boots the real js/polish-estimate.js on the real bid-model.js, library-core.js,
price-lines-core.js and epoxy-takeoff.js and reads every fact off the page after it ran. The CSS is the one thing a headless run cannot lay
out, so it is read as the rules that make the panel float and drop inline. The last tests break a scratch copy of the code in many ways and
require each fact to notice; `break_source` refuses an anchor that is not in the file exactly once.
"""
import html
import pathlib
import re
from html.parser import HTMLParser

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "sheets-panel-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]
SECTIONS = ["list", "copy", "add", "seal", "baseSwitch", "combined", "renameByTab", "deleting", "renaming", "options", "reopen", "unreadable", "focus",
            "markup", "floating", "gypPreset", "limit", "sealMode", "demote", "resets", "unstated", "hiddenOption", "stickyHead", "ownProposal"]
GYP1, GYP2 = 'Gyp (USG 1-8")', "Gyp (USG N12ULTRA)"
LIMIT = "A bid can hold 12 copied sheets at most."
EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)


def run_page(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return run_page()


@pytest.mark.parametrize("section", SECTIONS)
def test_no_section_of_the_harness_failed(ran, section):
    """A section that threw reports it instead of crashing, so running this over a tree without the panel fails an assertion with
    a reason."""
    assert "error" not in ran[section], ran[section].get("error")


# ── 1. the panel lists every sheet, and clicking one opens it ────────────────────────────────────────────────
def test_the_panel_lists_every_sheet_that_is_part_of_the_bid_with_its_price_and_opens_the_one_clicked(ran):
    p = ran["list"]
    assert p["before"]["rows"] == ["Polish", "Copy1", "Seal"] and p["before"]["tabs"] == ["Polish", "Copy1", "Seal"]
    assert p["before"]["open"] == "Polish" and "Base bid" in p["before"]["now"]
    assert p["shown"] == {"polish": "${:,}".format(p["prices"]["polish"]), "copy": "${:,}".format(p["prices"]["copy"])}, (
        "the price on a row is the figure the page prices that sheet at")
    assert p["prices"]["polish"] != p["prices"]["copy"], "the fixture tells the two sheets apart by their areas"
    a = p["after"]
    assert a["open"] == "Copy1" and a["takeoffOnShow"] == 7777, "clicking a sheet puts it on show: the steps below edit it"
    assert a["activeBid"] == a["copyBid"] == p["prices"]["copy"]
    assert "Polish copy" in a["now"], "and the line above the step rail says which sheet that is"


def test_a_base_radio_is_on_every_sheet_that_can_be_the_base_and_says_what_it_means_itself(ran):
    p = ran["list"]
    assert p["before"]["radios"] == 2, "Polish and its copy have one, the Seal sheet does not"
    lg = p["legend"]
    assert lg["gone"] is True, "the legend line, with its red-ringed dot, is back: a footer line in a block that stays on screen is height lost to every step"
    assert lg["radios"] == lg["titled"] == lg["named"] == 2, "each radio's title and its accessible name say what the base bid does"
    assert ran["combined"]["button"]["titled"] is True, "so does the button that makes Epoxy + Polish the base together"
    assert ran["markup"]["legendAnywhere"] is False, "in none of the eleven states the bar can be in"


def test_the_one_line_under_the_bar_is_the_note_about_copies(ran):
    assert ran["list"]["copiesNote"] is True, "a bid that holds a copy still says copies print on the proposal and are not in the Excel download"


def test_add_sheet_is_the_last_tab_of_the_strip_and_the_picker_opens_under_it(ran):
    assert ran["list"]["addAtEnd"] is True
    assert ran["list"]["tabs"]["addInStrip"] is True and ran["list"]["tabs"]["addLast"] is True


def test_the_strip_has_one_tab_a_sheet_the_open_one_selected_and_the_base_radio_checked(ran):
    """(b) One tab per sheet in the order the model lists them, only the open one selected, the base's radio checked and its tab
    marked, and ROW 2 is the open sheet's bar and nobody else's."""
    t = ran["list"]["tabs"]
    assert t["tablist"] is True and t["roles"] == 3, "Polish, its copy and the Seal sheet: one tab each"
    assert t["selected"] == 1 and t["polishMarked"] is True, "the open sheet is the selected tab, and it is the base"
    assert t["polishChecked"] is True and t["copyChecked"] is False and t["copyMarked"] is False
    assert t["selectedAfter"] is True and t["openBars"] == 1 and t["barIsOpenSheet"] is True, "opening another tab moves the selection and the bar"


# ── the review findings on the tab strip (2026-10-19) ──────────────────────────────────────────────────────────────
def test_a_repaint_keeps_the_strips_scroll_and_a_new_open_tab_is_scrolled_to_only_as_far_as_it_takes(ran):
    s = ran["stripKeeps"]
    assert s["kept"]["repainted"] and s["kept"]["newNode"], "the fixture did not rebuild the strip, so this proves nothing"
    assert s["kept"].get("scrollLeft") == 150, "a repaint threw the strip back to the left"
    r = s["reach"]
    assert r["right"] == 500 + 120 - 300 + 8, "a tab off the right edge is scrolled to, with a little room"
    assert r["left"] == 100 - 8, "a tab off the left edge is scrolled to"
    assert r["inView"] == 50 and r["noLayout"] == 7, "a tab in view, or a node with no layout, leaves the strip alone"


def test_the_tabs_are_walked_with_the_arrow_keys(ran):
    k = ran["stripKeeps"]["keys"]
    names = k["names"]
    assert len(names) == 3
    assert k["right"] == {"focused": names[1], "prevented": True}
    assert k["wrap"] == {"focused": names[0], "prevented": True} and k["leftWrap"] == {"focused": names[2], "prevented": True}
    assert k["left"] == {"focused": names[0], "prevented": True}
    assert k["home"]["focused"] == names[0] and k["end"]["focused"] == names[2]
    assert k["enter"] == {"focused": None, "prevented": False} and k["space"]["prevented"] is False, "Enter and Space are the button's own"


def test_a_refused_add_is_said_in_the_flow_under_the_strip_and_the_picker_is_in_the_flow_too(ran):
    n = ran["stripKeeps"]["notice"]
    assert n["pickerOpen"] and n["pickerHasList"] and n["flowAfterBox"] and n["openBarAfter"]
    assert n["inBox"] is None, "the refusal is inside the picker's box, over the open sheet"
    assert n["inFlow"] and "could not be added" in n["inFlow"]
    page = (FRONTEND / "polish-estimate.html").read_text(encoding="utf-8")
    add_rule = re.search(r"\.sheets \.sh-add\{([^}]*)\}", page).group(1)
    assert "position:static" in add_rule and "absolute" not in add_rule, "nothing may be laid over the open sheet's controls"


def test_the_page_heading_does_not_repeat_the_logo_of_the_top_bar():
    page = (FRONTEND / "polish-estimate.html").read_text(encoding="utf-8")
    head = page[page.index('<div class="head">'):page.index('<span class="beta">')]
    assert "<img" not in head and "bison" not in head, "the heading still carries its own logo"
    assert "Estimating Tool v2" in head and 'id="proj-line"' in head
    assert page.count("treadwell-bison.svg") == 2, "the top bar's brand and the tab icon are the only two left"


# ── 2. Copy ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_copy_adds_a_sheet_that_prices_like_its_source_starts_off_the_proposal_and_opens(ran):
    c = ran["copy"]
    assert c["tabs"] == ["Copy1"] and c["kind"] == "option" and c["label"] == "Polish copy" and c["source"] == "Polish"
    assert c["copyTotal"] == c["rootTotal"] > 0, "a copy prices exactly like the sheet it was copied from"
    assert c["rows"] == ["Polish", "Copy1"] and c["open"] == "Copy1"
    assert c["tabOpts"] == {"Copy1": {"show_system": True, "show_diff": False, "is_option": False, "show": True, "price_mode": "total"}}, (
        "a copy starts OFF the proposal: trying something prints nothing until it is switched on")
    assert c["summary"] == "Not on the proposal" and "Polish copy" in c["nowLine"]
    assert c["savedKinds"] == [["Polish", "Polish", "base"], ["Copy1", "Polish copy", "option"]]
    assert c["lump"] == c["rootTotal"] and c["baseTabId"] == "Polish", "a copy is never in the lump sum"
    assert c["copyAgain"] == ["Copy1", "Copy2"], "a copy can be copied"


# ── 3. + Add sheet ───────────────────────────────────────────────────────────────────────────────────────────
def test_add_sheet_offers_a_type_and_the_sheet_it_adds_starts_on_the_proposal_as_a_total(ran):
    a = ran["add"]
    assert a["menuHasClose"] is True and a["menuTagged"] == 2, "Seal and Seal (+Jnts) are tagged as options only"
    assert a["startsFrom"] == "It starts from this bid's 17,500 SF."
    e = a["afterEpoxy"]
    assert e["tabs"] == ["Epoxy"] and e["kind"] == "option" and e["open"] == "Epoxy"
    assert e["tabOpts"] == {"Epoxy": {"show_system": True, "show_diff": False, "is_option": True, "show": True, "price_mode": "total"}}
    assert e["switchOn"] is True and e["menuClosed"] is True and e["busy"] is False, "ON, as a total, menu closed once it is added"
    s = a["secondPolish"]
    assert s["tabs"] == ["Epoxy", "Copy1"] and s["sheet"] == "Polish" and s["label"] == "Polish 2" and s["kind"] == "option"
    assert s["tabOpts"]["is_option"] is True, "a second Polish sheet is a Copy id, and it starts ON like any added sheet"
    assert a["lump"] == a["rootTotal"], "options never change the lump sum"
    assert a["pricedKinds"] == [["Polish", "base"], ["Epoxy", "option"], ["Copy1", "option"]] and a["alert"] == ""


# ── 4. Seal ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_seal_sheet_offers_total_only_and_is_never_the_base(ran):
    s = ran["seal"]
    assert s["noBaseRadio"] is True and s["slotSaysWhy"] is True and s["baseRadios"] == 1 and s["polishRadioChecked"] is True
    assert s["noModePair"] is True and s["note"] is True and s["switchOn"] is True
    assert s["stillTotal"] == "total", "asked for Add / Deduct, a Seal sheet stays a total"


# ── 5. making Epoxy the base ─────────────────────────────────────────────────────────────────────────────────
def test_picking_a_base_asks_first_and_cancelling_writes_nothing(ran):
    b = ran["baseSwitch"]
    assert b["confirm"]["words"] == {
        "title": "Make Epoxy the base bid?",
        "body": "The job becomes an Epoxy job and the proposal switches to the Epoxy format. Polish becomes an option on the proposal, "
                "priced as a total."}
    assert b["confirm"]["nothingChanged"] is True and b["confirm"]["saves"] == 0, "nothing moves until the estimator says yes"
    assert b["cancelled"] == {"confirmGone": True, "saves": 0}


def test_making_epoxy_the_base_writes_the_work_type_and_the_base_id_and_moves_the_lump_sum(ran):
    b = ran["baseSwitch"]
    assert b["draft"]["work_type"] == "epoxy" and b["draft"]["base_tab_id"] == "Epoxy"
    assert b["kinds"] == [["Polish", "option"], ["Epoxy", "base"]] and b["jobType"] == "epoxy"
    assert b["lump"] == b["hand"] == b["epoxyBefore"] != b["polishTotal"], (
        "the lump sum is the Epoxy section priced by hand with no page in it, and it is not Polish's")
    assert b["bar"] == b["lump"] and b["savedBase"] == "Epoxy" and b["savedWorkType"] == "epoxy"
    assert b["maths"] == "Epoxy ${:,} · Polish ${:,} option (not in the lump sum)".format(b["lump"], b["polishTotal"])
    assert b["rows"]["epoxy"] is True, "Epoxy is the row marked Base bid"


def test_the_old_base_stays_on_the_proposal_as_an_option_priced_as_a_total(ran):
    b = ran["baseSwitch"]
    assert b["draft"]["polishOpt"] == {"show_system": True, "show_diff": False, "is_option": True, "show": True, "price_mode": "total"}
    assert b["draft"]["epoxyOpt"]["is_option"] is False and b["draft"]["epoxyOpt"]["price_mode"] == "deduct", (
        "the new base is no option, and what the estimator set on it is kept for the day it is one again")
    assert b["pricedTabs"][0] == ["Polish", "option", b["polishTotal"]] and b["rows"]["polish"] == "Option, total"


def test_the_lines_typed_on_the_proposal_step_follow_the_new_base_by_the_shared_rule(ran):
    """TWPrice.applyBasePick, the rule the live estimate and the proposal's own picker run: his words stay, the words for the system
    and the amount become the new base's."""
    b = ran["baseSwitch"]
    assert b["lines2"] == {"base": "Our price, ⟦amount⟧ – Epoxy flooring as described above ⟦tax⟧"}
    assert b["optionsKept"] == {"Epoxy": {"label": "mine"}}, "an option's own price override is not the base line's and is not touched"


def test_a_base_change_that_moves_the_travel_fills_the_new_carriers_blank_travel_labor_from_the_distance_on_file(ran):
    """The 2026-10-20 audit's rule, for the Sheets panel's way of switching the job type: a far Polish bid (190 miles on file) whose Travel
    Labor was left blank, made an Epoxy base, moves the job's travel to Epoxy and the row with it, and the blank row is filled by the rule an
    answer follows: 6.5 hours (a 380 mile round trip), the guys on the base crew, Epoxy's 3. A change that keeps the carrier (the combined
    pair: Polish stays the first base) fills nothing; a row somebody typed in is left alone; a row already filled keeps its figures. Nothing
    is looked up.

    Mutation: leave B.followDistance out of makeBase (BREAKS below)."""
    t = ran["baseTravel"]
    b = t["blank"]
    assert b["before"] == {"carrier": "Polish", "row": {"days": "", "guys": "", "guys_auto": False}}, "blank, untouched, no marker"
    # (the demoted Polish root KEEPS its Travel Labor row since the fifth audit: it is an option, priced apart with a drive of its own, and moving the row left it none
    # until a reload; the new carrier took a copy)
    assert (b["carrier"], b["rootHasTravel"], b["epoxyHasTravel"], b["asked"]) == ("Epoxy", True, True, 0)
    assert b["row"] == {"days": 6.5, "guys": 3, "guys_auto": True, "guys_follow": "crew", "hours_seed": 6.5}
    ty = t["typed"]
    assert (ty["carrier"], ty["epoxyHasTravel"]) == ("Epoxy", True)
    assert (ty["row"]["days"], ty["row"]["guys"], ty["row"]["guys_auto"], ty["row"].get("guys_follow")) == ("4", "2", False, None), "typed figures stay"
    k = t["keepsCarrier"]
    assert (k["carrier"], k["row"]["days"], k["row"]["guys"], k["row"].get("guys_follow")) == ("Polish", "", "", None), "the carrier did not move"
    f = t["filled"]
    assert (f["carrier"], f["row"]["days"], f["row"]["guys"], f["row"]["guys_follow"]) == ("Epoxy", 6.5, 3, "crew")


def test_the_strip_holds_sheets_only_and_the_pair_is_made_the_base_from_either_sheets_bar(ran):
    """Hanz, 2026-10-21: "The Epoxy + Polish should not be a default Sheet". The combined base-bid choice was a dashed tab drawn FIRST in the
    strip whenever the bid held an Epoxy and a Polish sheet, so an Epoxy bid with a Polish option read as a bid holding a sheet nobody made.
    The strip holds the sheets and "+ Add sheet"; the pair is priced together as the base from the bar of either sheet of it, never from a
    copy, and the button goes once the pair is the base."""
    c = ran["combined"]
    assert c["tab"]["none"] is True, "the strip draws an Epoxy + Polish tab again"
    assert c["tab"]["rows"] == ["Polish", "Epoxy", "Copy1"], "one tab a sheet, in the model's order"
    b = c["button"]
    assert b["onPolish"] is True and b["onEpoxy"] is True, "either sheet of the pair offers it"
    assert b["onCopy"] is False, "a copy of Polish is not the pair's Polish: its bar does not offer it"
    assert b["says"] == "Make Epoxy + Polish the base ${:,}".format(c["lump"]), "it says what it does and what the pair comes to"
    assert c["noButtonOnceCombined"] is True and c["stillNoTab"] is True, "once the pair is the base the button goes, and no tab comes back"
    together = "Epoxy + Polish together, ${:,}".format(c["lump"])
    assert "In the base bid" in c["bars"]["epoxy"] and together in c["bars"]["epoxy"] and together in c["bars"]["polish"], (
        "each sheet of a combined base says so, and what the pair comes to")


def test_making_the_pair_the_base_asks_first_puts_the_caret_on_the_answer_and_cancelling_moves_nothing(ran):
    c = ran["combined"]
    assert c["confirm"] == {"title": "Make Epoxy + Polish (combined) the base bid?",
                            "body": "The job becomes a Combo job and the proposal switches to the Combo format."}
    assert c["focus"]["asked"] == ["confirm|yes"], "the question is drawn above the bar: the caret goes to its answer, not behind it"
    assert c["focus"]["cancelled"] == ["Epoxy|combine"], "Cancel puts the caret back on the button that asked"
    assert c["cancelled"] == {"kinds": [["Polish", "base"], ["Epoxy", "option"], ["Copy1", "option"]], "button": True}
    assert c["focus"]["made"] == ["Epoxy|open"], "once it is made the button is gone, so the caret goes to the open sheet's tab"


def test_a_combined_epoxy_and_polish_base_writes_combo_and_no_base_id_and_sums_the_pair(ran):
    c = ran["combined"]
    assert c["draft"] == {"work_type": "combo", "base_tab_id": None}, "no sheet is the base on its own"
    assert c["kinds"] == [["Polish", "base"], ["Epoxy", "base"], ["Copy1", "option"]] and c["jobType"] == "combo"
    assert c["savedBase"] is None and c["savedWorkType"] == "combo"
    assert c["lump"] == c["polishTotal"] + c["epoxyTotal"], "the pair is summed"
    assert c["baseTabs"] == 2, "both sheets of the pair are marked as the base in the strip"


def test_a_double_click_on_a_tab_renames_the_sheet(ran):
    """Hanz, 2026-10-21: "Double clicking the sheet container should allow me to rename it", as a worksheet's tab does. The first press opens
    the sheet and redraws the strip, so the second press lands on a NEW button: the page knows it by the browser's count of presses (detail)."""
    r = ran["renameByTab"]
    assert r["titled"] is True, "every tab says it can be renamed with a double-click"
    assert r["afterOne"] == {"open": "Copy1", "naming": None}, "one press opens the sheet and nothing else"
    assert r["afterTwo"]["open"] == "Copy1" and r["afterTwo"]["naming"] == {"tab": "Copy1", "value": r["copyLabel"]}
    assert r["afterTwo"]["focus"] == ["Copy1|name"], "the caret is in the name box, ready to type"
    assert r["afterDbl"] == {"label": "Gara", "naming": None}, "the dblclick that follows the second press leaves what was typed alone"


def test_a_dblclick_on_a_sheet_that_is_not_open_opens_it_and_renames_it_and_esc_drops_the_name(ran):
    r = ran["renameByTab"]
    assert r["dblOther"] == {"open": "Polish", "naming": {"tab": "Polish", "value": "Polish"}}
    assert r["afterEsc"] == {"open": "Polish", "naming": None}


def test_f2_on_a_tab_renames_it_from_the_keyboard(ran):
    r = ran["renameByTab"]
    assert r["f2"] == {"open": "Copy1", "naming": {"tab": "Copy1", "value": "Gara"}, "prevented": True}
    assert r["savedLabel"] == "Garage"


def test_going_from_the_combined_base_to_one_sheet_makes_the_other_an_option_on_the_proposal(ran):
    back = ran["combined"]["back"]
    assert back["body"].startswith("The job becomes an Epoxy job") and back["body"].endswith("priced as a total.")
    assert back["work_type"] == "epoxy" and back["base_tab_id"] == "Epoxy"
    assert back["polishOpt"]["is_option"] is True and back["polishOpt"]["price_mode"] == "total"
    assert back["kinds"] == [["Polish", "option"], ["Epoxy", "base"], ["Copy1", "option"]]


# ── 6. delete ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_base_cannot_be_deleted_its_button_is_disabled_and_the_sentence_says_why(ran):
    b = ran["deleting"]["base"]
    assert b["disabled"] is True and b["why"] is True
    assert b["tabs"] == ["Copy1"] and b["armed"] is False, "pressing it anyway arms nothing and deletes nothing"
    assert "cannot be deleted" in b["alert"], "the model's own refusal is shown"


def test_delete_takes_two_presses_a_click_elsewhere_puts_it_back_and_the_draft_forgets_the_sheet(ran):
    d = ran["deleting"]
    assert d["armed"]["label"] == "Click again to delete" and d["armed"]["warns"] is True and d["armed"]["still"] == ["Copy1"]
    assert d["disarmed"] == "Delete", "a click anywhere else on the panel puts it back"
    a = d["after"]
    assert a["tabs"] == [] and a["rows"] == ["Polish"] and a["open"] == "Polish", "the open sheet was the one deleted, so the base opens"
    assert a["tabOpts"] == {} and a["tabNotes"] == {"Other": ["kept"]} and a["options"] == {}, (
        "its proposal settings, its notes and its own price override go; another sheet's are left")
    assert a["pricedTabs"] == ["Polish"], "with one sheet left only the base's tab is there"


# ── 7. rename ────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_name_is_not_checked_while_it_is_typed_only_when_it_is_committed(ran):
    r = ran["renaming"]
    assert r["started"] == {"input": True, "hasNote": True}
    assert r["midWord"]["error"] is False, "never scold someone mid-word"
    assert r["retyped"]["errorNode"] is True, "typing again takes an old message down"


@pytest.mark.parametrize("case,message", [
    ("blank", "Enter a sheet name."),
    ("taken", '"polish" is already the name of a sheet.'),
    ("badChar", 'A sheet name cannot have any of these: ! : \\ / ? * [ ] "'),
    ("tooLong", "A sheet name can have 31 characters at most."),
])
def test_a_name_that_will_not_do_says_why_keeps_what_was_typed_and_changes_nothing(ran, case, message):
    c = ran["renaming"]["refused"][case]
    assert html.unescape(c["msg"]) == message
    assert c["prevented"] is True and c["stillRenaming"] is True and c["draftKept"] is True and c["label"] == "Polish copy"


def test_a_good_name_is_saved_shown_everywhere_the_sheet_is_named_and_esc_drops_one(ran):
    r = ran["renaming"]
    assert r["cancelled"] == {"label": "Polish copy", "input": False, "saves": 0}
    assert r["saved"] == {"label": "Garage floor", "key": ["Copy1"], "pricedName": "Garage floor"}, "the key never changes"
    assert r["shownName"] is True and "Garage floor" in r["now"] and "Garage floor" in r["maths"]


# ── 8. the switch, Total or Add / Deduct, and the words ──────────────────────────────────────────────────────
def test_the_switch_puts_an_option_on_or_off_the_proposal_and_dims_what_does_not_apply(ran):
    o = ran["options"]
    assert o["start"] == {"summary": "Not on the proposal", "switchOff": True, "inert": True}
    assert o["on"]["opt"]["is_option"] is True and o["on"]["opt"]["show"] is True and o["on"]["summary"] == "Option, total"
    assert o["on"]["inert"] is False
    assert o["off"]["opt"]["is_option"] is False and o["off"]["summary"] == "Not on the proposal"


def test_add_or_deduct_shows_the_figure_the_proposal_will_print_the_option_less_the_base(ran):
    o = ran["options"]
    assert o["deduct"]["opt"]["price_mode"] == "deduct" and o["deduct"]["checked"] is True
    assert o["deduct"]["summary"] == "Option, " + o["expectDeduct"] and o["expectDeduct"] == "Deduct (${:,})".format(o["base"] - o["cheap"])
    assert o["add"]["summary"] == "Option, " + o["expectAdd"] and o["expectAdd"] == "Add ${:,}".format(o["dear"] - o["base"])


def test_the_words_an_option_prints_are_saved_as_typed_without_redrawing_under_the_caret_and_capped_at_400(ran):
    o = ran["options"]
    assert o["boxOpen"] == {"box": True, "ph": "Polish 800 Grit"}, "the grey text is what the option prints now"
    assert o["typed"] == {"opt": "Grind and polish to 400 grit", "redraws": 0}
    assert o["capped"] == 400
    assert o["collapsed"] == {"preview": "Grind and polish to 400 grit", "expanded": "false"}


# ── 9. saved bids ────────────────────────────────────────────────────────────────────────────────────────────
def test_a_saved_bid_with_a_chosen_base_opens_as_saved_and_writes_nothing(ran):
    """The Epoxy bid was made Epoxy-based on the page; opened again its job type is epoxy, which is the route that used to move
    the bases (sectionsForJob). It must leave the estimator's choice alone."""
    r = ran["reopen"]["afterSwitch"]
    assert r["saves"] == 0 and r["armed"] == 0 and r["workType"] == "epoxy"
    assert r["kinds"] == [["Polish", "option"], ["Epoxy", "base"]] and r["rows"] == ["Polish", "Epoxy"]
    assert r["bar"] == r["expectBar"], "the reopened bar is the Epoxy base priced by hand"
    c = ran["reopen"]["copyBase"]
    assert c["saves"] == 0 and c["armed"] == 0 and c["kinds"] == [["Polish", "option"], ["Copy1", "base"]] and c["rows"] == ["Polish", "Copy1"]


def test_a_bid_whose_other_sheets_cannot_be_read_shows_its_first_sheet_says_so_and_offers_nothing_else(ran):
    u = ran["unreadable"]
    assert u["rows"] == ["Polish"] and u["warn"] is True
    assert u["addDisabled"] is True and u["addWhy"] is True
    assert u["price"] == u["bid"], "the sheet that can be read still prices"


# ── 10. the keyboard ─────────────────────────────────────────────────────────────────────────────────────────
def test_the_caret_goes_back_to_the_control_it_was_on_after_the_panel_is_redrawn(ran):
    """The panel is rebuilt on every change, and a rebuilt control has no caret: a keyboard user who pressed the switch would be
    dropped back to the top of the page. The page puts it back by data-sh-key."""
    f = ran["focus"]
    assert f["afterSwitch"] == ["Copy1|on"]
    assert f["afterRename"] == ["Copy1|name"], "Rename puts the caret in the box"
    assert f["afterCancel"] == ["Copy1|rename"], "and Cancel puts it back on Rename, which is where it came from"
    assert f["afterCopy"] == ["Copy2|open"], "a new sheet opens, with the caret on its name"


# ── 11. the markup ───────────────────────────────────────────────────────────────────────────────────────────
def test_what_a_sheet_is_called_and_what_it_prints_is_escaped_and_no_dash_is_drawn(ran):
    m = ran["markup"]
    assert m["escaped"] is True and m["placeholder"] is True and m["icons"] is True and m["noDash"] is True
    assert m["gypAttr"] is True, "a Gyp sheet's own name has a quote mark in it"
    assert m["noNowLine"] is True, "the Open sheet line is gone: the bar under the tabs says the same"
    assert m["deduct"] == "Option, Deduct ($20)"


def test_the_words_a_base_change_says_name_the_job_and_what_happens_to_the_old_base(ran):
    w = ran["markup"]["confirmWords"]
    assert w["same"]["body"] == "The job stays Polish. Polish becomes an option on the proposal, priced as a total."
    assert w["epoxy"]["body"].startswith("The job becomes an Epoxy job and the proposal switches to the Epoxy format.")
    assert w["combo"]["body"] == "The job becomes a Combo job and the proposal switches to the Combo format."
    assert ran["markup"]["pair"] == ["Epoxy", "Polish"] and ran["markup"]["pairNone"] is None


def test_an_option_the_draft_holds_nothing_for_is_on_and_a_hidden_one_is_not(ran):
    assert ran["markup"]["optionIsOn"] == [True, False, False, True]
    assert ran["markup"]["patch"]["tab_opts"]["a"] == {"keep": 1}, "another sheet's settings ride along untouched"
    assert ran["markup"]["patch"]["tab_opts"]["b"]["price_mode"] == "deduct"


# ── 12. it does not float: a strip of tabs in the flow ──────────────────────────────────────────────────
def test_the_bar_is_not_floated_and_keeps_no_lane_on_the_page(ran):
    """(b) Nothing registers it with TW.floatPanel (the proposal editor's use of that helper is untouched), there is no fixed rule, grip or
    reserved lane for it, and it sits in the sticky head under the top bar: above the step rail, and no longer inside #main."""
    f = ran["floating"]
    assert f["floats"] == [], "no TW.floatPanel call under tw_v2sheets_pos or any other key"
    assert f["floatKeyInPage"] is False and f["fixedRule"] is False and f["gripRule"] is False and f["wideLane"] is False
    assert f["markupHasPanelFirst"] is True and f["beforeMain"] is True, "in the flow it sits above the step rail, in front of #main"


def test_the_strip_scrolls_sideways_and_the_page_does_not(ran):
    assert ran["floating"]["scrolls"] is True


def test_the_old_strip_and_option_bar_are_gone_and_the_page_loads_the_base_pick_rule(ran):
    assert ran["floating"]["oldStripGone"] is True and ran["floating"]["loadsPriceRule"] is True


def test_no_new_copy_in_the_panel_uses_a_dash(ran):
    """House rule: new words for users have no em or en dash. The harness drew the bar in eleven states (a
    confirm, a name being refused, Delete armed, the Add menu, a combined base, a bid that cannot be read) and the text of all of them is read."""
    states = ran["markup"]["states"]
    assert len(states) == 11 and all(isinstance(s, str) and s for s in states)
    for text in states:
        assert EM_DASH not in text and EN_DASH not in text


# ── 13. review findings (Sheets phase 3): the Gyp preset, the limit, Seal, and what a press clears ───────────────
def test_a_gyp_sheet_is_added_from_the_menu_by_its_id_with_the_quote_mark_in_it(ran):
    """The stub DOM now hands an attribute back DECODED, as a browser does: the Add menu's Gyp row says Gyp (USG 1-8&quot;) in the markup
    and the page has to read Gyp (USG 1-8"). Before, no test could press that row ('cannot be added to a bid')."""
    assert ran["gypPreset"]["added"] == {"rows": ["Polish", GYP1], "open": GYP1, "on": True, "alert": ""}


def test_changing_a_gyp_sheets_preset_keeps_its_proposal_settings_its_words_and_everything_else_the_draft_held_for_it(ran):
    """THE DEFECT. Add menu, Gyp (it adds the FIRST preset), the switch OFF, words typed in Description, then another preset on the Material
    step. The preset renames the sheet's key, and nothing carried the draft's tab_opts, notes, price override or typed line across: the sheet
    came back with fresh settings and an option the estimator had switched OFF printed on the customer's proposal."""
    g = ran["gypPreset"]
    assert g["before"]["is_option"] is False and g["before"]["desc"] == "my gyp words"
    assert g["open"] == GYP2
    assert g["keys"] == {"opts": [GYP2], "notes": [GYP2, "Other"], "options": [GYP2, "Other"], "lines": ["option:" + GYP2]}, (
        "everything follows the new key and nothing is left under the old preset")
    assert g["opt"] == g["before"], "OFF stays OFF, with its words"
    assert g["notes"] == ["a note"] and g["option"] == {"label": "mine"} and g["line"] == "my line"
    assert g["otherKept"] == [["kept"], {"label": "kept"}], "another sheet's are left alone"
    assert g["row"]["switchOff"] is True and g["row"]["switchOn"] is False and g["row"]["preview"] == "my gyp words", (
        "and the panel shows it: the switch is off and the words are there")
    assert g["saved"]["tabs"] == [GYP2] and g["saved"]["opts"] == [GYP2] and g["saved"]["entry"]["is_option"] is False, (
        "the next save finds an entry for the sheet, so it writes none: no second, fresh one that is ON")


def test_switching_back_to_the_first_preset_brings_the_same_settings_back_with_nothing_left_behind(ran):
    g = ran["gypPreset"]
    b = g["back"]
    assert b["opts"] == [GYP1] and b["entry"] == g["before"] and b["notes"] == [GYP1, "Other"] and b["options"] == [GYP1, "Other"]


def test_the_add_menu_lists_each_type_once_and_gyp_is_one_row(ran):
    assert ran["add"]["menuLabels"] == ["Polish", "Epoxy", "Gyp", "Seal", "Seal (+Jnts)"]


def test_the_excel_hint_is_drawn_only_when_the_bid_holds_a_copy(ran):
    assert ran["add"]["excel"] == [False, False, True], "none on a bid of one sheet or with an added sheet, there once a copy exists"


def test_at_twelve_copies_the_refusal_is_said_in_the_panel_beside_the_button_not_at_the_top_of_the_page(ran):
    """With the panel floating and the page scrolled, the page's own alert is out of sight (it measured -90px). The refusal is a line of
    the panel: under the sheet's own buttons for Copy, under the Add sheet button for Add."""
    l = ran["limit"]
    assert l["last"] == "Copy12"
    c = l["copyRefused"]
    assert c["copies"] == 12 and c["inRow"] == "The sheet could not be copied: " + LIMIT
    assert c["inAddBlock"] is None and c["alert"] == "", "said once, in the row that was pressed"
    a = l["addRefused"]
    assert a["inAddBlock"] == "The sheet could not be added: " + LIMIT and a["inRow"] is None and a["alert"] == ""
    assert a["menuOpen"] is True, "the menu stays open so another type can be chosen"


def test_a_refusal_goes_on_the_next_click_and_when_a_sheet_goes_in(ran):
    """It used to stay at the top of the page through every later successful action."""
    l = ran["limit"]
    assert l["copyRefused"]["inRow"] is not None and l["addRefused"]["inAddBlock"] is not None, "it was there to be taken down"
    assert l["afterClick"] is None
    assert l["added"] == {"inAddBlock": None, "epoxy": True}


def test_a_seal_option_the_proposal_step_left_on_add_or_deduct_is_a_total_when_the_page_opens(ran):
    """The panel offers a Seal sheet no Total / Add or Deduct pair and says it is priced as a total, while the proposal printed what the draft
    said. Put back before the first paint; the words stay, and a copy of Polish keeps its Add / Deduct."""
    s = ran["sealMode"]
    assert s["written"]["Seal"] == {"show_system": True, "show_diff": False, "is_option": True, "show": True, "price_mode": "total",
                                    "desc": "seal words"}
    assert s["written"]["Copy1"]["price_mode"] == "deduct"
    assert s["noPair"] is True and s["writesOnOpen"] == 1
    assert s["plainWritesOnOpen"] == 0, "a bid with its Seal on a total writes nothing on open"


def test_the_old_base_goes_on_the_proposal_as_a_total_with_its_words_whatever_it_had_held(ran):
    """The fixture's old base used to hold nothing, so forcing the total was never seen: here it held Add / Deduct and was hidden."""
    d = ran["demote"]
    assert d["written"] == dict(d["before"], is_option=True, show=True, price_mode="total")
    assert d["summary"] == "Option, total"


def test_a_press_clears_a_base_change_waiting_for_its_yes_and_a_name_being_typed_and_its_refusal(ran):
    r = ran["resets"]
    assert r["askedA"] is True and r["afterOpen"] is False, "opening another sheet drops a base change that was asked for"
    assert r["refused"] == {"input": True, "error": True} and r["afterOpenName"] == {"input": False, "error": False}
    assert r["askedC"] is True and r["afterCopy"] is False, "copying a sheet does too"
    assert r["withMenu"] is True and r["afterAdd"] is False, "so does adding one, though opening the menu alone does not"


def test_an_option_the_draft_has_said_nothing_about_is_priced_as_a_total_and_opening_it_writes_nothing(ran):
    u = ran["unstated"]
    for case in ("noEntry", "noMode"):
        assert u[case] == {"total": True, "deduct": False, "summary": "Option, total", "saves": 0}, case


def test_the_switch_brings_back_an_option_the_proposal_step_had_hidden(ran):
    h = ran["hiddenOption"]
    assert h["hidden"] == {"on": False, "summary": "Not on the proposal"}
    assert h["shown"] == {"on": True, "summary": "Option, total"}
    assert h["written"] == {"show_system": True, "show_diff": False, "is_option": True, "show": True, "price_mode": "total", "desc": "kept words"}, (
        "on means shown too: a switch that left show false would stay stuck on Not on the proposal")
    assert h["off"]["on"] is False and h["off"]["opt"]["is_option"] is False and h["off"]["opt"]["desc"] == "kept words"


def test_the_caret_goes_to_the_name_box_when_a_name_is_refused_and_back_to_rename_when_it_is_saved(ran):
    f = ran["focus"]
    assert f["afterRefusedName"] == ["Copy2|name"] and f["afterSavedName"] == ["Copy2|rename"]


# ── 24. ITS OWN PROPOSAL (Create Multiple Proposals, plan step 5): several base bids picked on the v2 strip ──────────────────────────
# The v2 side of the Proposal step's Base Bid checkboxes. A switch on an option's bar ("Its own proposal") ticks the sheet in the draft's
# base_tab_ids (B.proposalBasePatch, TWPrice.toggleBaseId's rule ordered by the bid's sections); the model is not touched, so nothing is
# repriced. Once two sheets are base bids each tab says "Bid N" and the scope bar says the proposals are made on the Proposal step.
_OWN_KINDS = [["Polish", "base"], ["Epoxy", "option"], ["Copy1", "option"], ["Seal", "option"]]


def test_its_own_proposal_is_offered_on_an_option_that_can_be_a_base_and_never_on_the_base_or_a_seal_sheet(ran):
    s = ran["ownProposal"]["start"]
    assert s["offered"] == {"Polish": None, "Epoxy": "false", "Copy1": "false", "Seal": None}, (
        "the base is Base Bid 1 already and a Seal sheet is never a base: neither has the switch")
    assert s["bids"] == {}, "a bid of one proposal draws no Bid tag"
    assert "Create the proposals" not in s["scope"] and s["blobIds"] == "absent", "opening the page ticks nothing"


def test_switching_a_sheet_on_ticks_it_after_the_base_tags_bid_n_and_reprices_nothing(ran):
    o = ran["ownProposal"]
    one = o["one"]
    assert one["ids"] == ["Polish", "Epoxy"] and one["base"] == "Polish", "the pricing base stays Base Bid 1"
    assert one["checked"] == "true" and one["switchTag"] is True
    assert one["bids"] == {"Polish": 1, "Epoxy": 2}
    assert one["kinds"] == o["kinds0"] == _OWN_KINDS and one["lump"] == o["lump0"], "the switch changes no kind and no price"
    assert one["scope"].endswith("2 base bids, each its own proposal: Base Bid 1 Polish , Base Bid 2 Epoxy . Create the proposals on the Proposal step.")


def test_a_second_sheet_is_the_next_bid_and_switching_it_off_takes_only_it_out(ran):
    o = ran["ownProposal"]
    assert o["two"]["ids"] == ["Polish", "Epoxy", "Copy1"] and o["two"]["bids"] == {"Polish": 1, "Epoxy": 2, "Copy1": 3}
    assert "3 base bids" in o["two"]["scope"]
    assert o["offAgain"] == {"ids": ["Polish", "Epoxy"], "bids": {"Polish": 1, "Epoxy": 2}, "checked": "false"}


def test_making_a_ticked_sheet_the_base_makes_it_base_bid_1_and_the_old_base_stays_its_own_proposal(ran):
    w = ran["ownProposal"]["swapped"]
    assert w["base"] == "Epoxy" and w["ids"] == ["Epoxy", "Polish", "Copy1"], "base_tab_id stays in base_tab_ids, first"
    assert w["bids"] == {"Epoxy": 1, "Polish": 2, "Copy1": 3}


def test_the_combined_pair_as_the_base_is_one_proposal_and_refuses_the_switch(ran):
    c = ran["ownProposal"]["combined"]
    assert c["base"] is None and c["ids"] == [] and c["bids"] == {}, "a combined base leaves no sheet ticked"
    assert c["disabled"] is True, "the switch is drawn, refused, and says why"
    assert c["pressed"] == {"ids": [], "notice": True}, "a press that got through anyway writes nothing and says why"
    assert "Create the proposals" not in c["scope"]


def test_the_own_proposal_rule_is_pure_ordered_by_the_bid_and_refuses_what_cannot_be_a_proposal(ran):
    p = ran["ownProposal"]["pure"]
    assert p["tick"] == {"base_tab_id": "Polish", "base_tab_ids": ["Polish", "Copy1"]}
    assert p["order"] == {"base_tab_id": "Polish", "base_tab_ids": ["Polish", "Epoxy", "Copy1"]}, "Bid N follows the sheets' order"
    assert p["untick"] == {"base_tab_id": "Polish", "base_tab_ids": ["Polish", "Copy1"]}
    assert p["again"] is None and p["base"] is None, "a press that changes nothing, and unticking the base, are refused"
    assert p["seal"] is None and p["unknown"] is None and p["pair"] is None and p["off"] is None
    assert p["stateUntouched"] is True
    assert p["idsNever"] == ["Polish"] and p["idsSeal"] == ["Polish", "Epoxy"], "a Seal sheet or a sheet gone is never a base bid"


def test_deleting_a_ticked_sheet_forgets_its_tick_so_the_next_copy_of_that_id_is_no_base_bid(ran):
    """A Copy<N> id is handed out again after a delete (nextCopyId), so a tick left in base_tab_ids would make the next copy a base bid
    of its own proposal that nobody switched on. B.optionLeftoverPatch (deleteSection's patch, and a new copy's) forgets it."""
    d = ran["ownProposal"]["deleted"]
    assert d["afterDelete"] == {"ids": ["Polish"], "tabs": ["Epoxy", "Seal"]}, "the saved draft forgets the deleted sheet's tick"
    r = d["recopied"]
    assert r["tabs"] == ["Copy1", "Epoxy", "Seal"] and r["ids"] == ["Polish"], "the new copy is handed the same id, unticked"
    assert r["own"] == "false" and r["tagged"] is False and "Create the proposals" not in r["scope"]
    assert d["staleCopy"] == {"ids": ["Polish"], "tabs": ["Copy1", "Epoxy"]}, "a stale tick a saved draft still holds goes when the id is reused"
    assert d["pure"] == {"base_tab_ids": ["Polish", "Epoxy"]} and d["pureNone"] == {}


# ── 14. the sticky head: the top bar and the sheet bar, ONE block pinned to the top of the screen ─────────────────────────────────────
# Hanz, 2026-10-20, with a screenshot: "The sheets should lie below the 4 tabs in the header nav bar ... that means its present in Material Labor
# and review for easier navigation ... that header bar when estimating in v2 should be sticky". The bar left #main and went under the top bar, and
# the two are one block (div.v2head) that stays at the top while the steps scroll under it. A headless run lays nothing out, so the markup and the
# CSS are read as the page ships them, and every check below is shown to go red by breaking a copy of the page's text (STATIC_BREAKS, at the end).
PAGE = (FRONTEND / "polish-estimate.html").read_text(encoding="utf-8")


class _Node:
    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.kids = tag, dict(attrs), []

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def walk(self):
        yield self
        for kid in self.kids:
            yield from kid.walk()


class _Tree(HTMLParser):
    """The page's elements as a tree (void elements closed, comments dropped), so 'first child' and 'sibling' mean what a browser's DOM means."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.open = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.open[-1].kids.append(node)
        if tag not in self.VOID:
            self.open.append(node)

    def handle_startendtag(self, tag, attrs):
        self.open[-1].kids.append(_Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.open) - 1, 0, -1):
            if self.open[i].tag == tag:
                del self.open[i:]
                return


def _page_tree(page):
    tree = _Tree()
    tree.feed(page)
    tree.close()
    return tree.root


def _style(page):
    return page[page.index("<style>"):page.index("</style>")]


def _css_rules(css):
    """[(media, selector, {property: value})] for every rule, comments removed. `media` is the prelude of the @media block a rule is in (None at the
    top level), so `(max-width:760px),(max-height:640px)` reads as one string and a rule inside it knows where it is."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []

    def read(text, media):
        i, n = 0, len(text)
        while i < n:
            j = text.find("{", i)
            if j < 0:
                break
            prelude, depth, k = text[i:j].strip(), 1, j + 1
            while k < n and depth:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
            body = text[j + 1:k - 1]
            if prelude.startswith("@media"):
                read(body, re.sub(r"\s+", " ", prelude[len("@media"):].strip()))
            elif not prelude.startswith("@"):
                decls = {}
                for part in body.split(";"):
                    if ":" in part:
                        prop, value = part.split(":", 1)
                        decls[prop.strip()] = re.sub(r"\s+", " ", value.strip())
                for selector in prelude.split(","):
                    out.append((media, re.sub(r"\s+", " ", selector.strip()), decls))
            i = k

    read(css, None)
    return out


def _decls(rules, selector, media=None):
    """The declarations of every rule with exactly this selector (inside exactly this @media prelude), later rules winning."""
    merged = {}
    for m, sel, decls in rules:
        if sel == selector and m == media:
            merged.update(decls)
    return merged


# the overlays the shell draws, where they say their z-index: the sticky head must sit under every one of them
OVERLAYS = {"#tw-toasts": "auth.js", "#tw-sidebar": "auth.js", "#tw-notif-panel": "auth.js", ".tw-ov": "shared.js"}


def _overlay_floor():
    floor = {}
    for selector, rel in OVERLAYS.items():
        found = re.search(re.escape(selector) + r"\{[^}]*?z-index:(\d+)", (FRONTEND / rel).read_text(encoding="utf-8"))
        assert found, "%s lost its z-index in %s: this test cannot tell what the head has to sit under" % (selector, rel)
        floor[selector] = int(found.group(1))
    return floor


def check_head_structure(page):
    """The sticky head is the first thing in the body, the top bar and then the sheet bar are its only two children, the page heading comes after
    it, and the sheet bar is in neither #main nor the page column. Raises AssertionError naming the fact that failed."""
    root = _page_tree(page)
    body = next(n for n in root.walk() if n.tag == "body")
    assert len(body.kids) >= 2, "the body is empty"
    head, wrap = body.kids[0], body.kids[1]
    assert head.tag == "div" and head.attrs.get("id") == "v2head" and head.classes() == ["v2head"], "the first thing in the body is not the sticky head"
    assert [(k.tag, k.attrs.get("id"), k.classes()) for k in head.kids] == [("header", None, ["topbar"]), ("section", "sheets-panel", ["sheets"])], (
        "the sticky head does not hold the top bar and then the sheet bar, as siblings")
    bar, sheets = head.kids
    assert [k.classes() for k in bar.kids] == [["brand"], ["progress"]], "nothing but .brand and .progress may be in the header: auth.js destroys the rest"
    assert "hidden" in sheets.attrs, "the sheet bar is not hidden before init has drawn it"
    assert wrap.tag == "div" and wrap.classes() == ["wrap"], "the page column does not come right after the sticky head"
    title = wrap.kids[0]
    assert title.classes() == ["head"] and any(n.tag == "h1" for n in title.walk()), "the page heading is not the first thing after the sticky head"
    main = next(n for n in root.walk() if n.attrs.get("id") == "main")
    assert "hidden" in main.attrs and main.kids[0].attrs.get("id") == "rail", "#main no longer opens on the step rail"
    for outside in (main, wrap):
        assert not any(n.attrs.get("id") == "sheets-panel" for n in outside.walk()), "the sheet bar is back inside the page column"


def check_head_sticky_css(page):
    """position:sticky; top:0; a background; over the page and under every overlay; running edge to edge inside the body's side padding."""
    style = _style(page)
    rules = _css_rules(style)
    head = _decls(rules, ".v2head")
    assert head.get("position") == "sticky", "the head is not position:sticky"
    assert head.get("top") in ("0", "0px"), "the head is not pinned to the top of the screen: top is %r" % head.get("top")
    z = int(head.get("z-index", "0"))
    bid_bar = int(re.search(r"\.bid\{[^}]*z-index:(\d+)", style).group(1))
    floor = _overlay_floor()
    assert bid_bar < z < min(floor.values()), "z-index %d must be over the page (the bid bar is %d) and under every overlay %r" % (z, bid_bar, floor)
    assert head.get("background", "").replace(" ", "") not in ("", "transparent", "none"), "page content would show through the head as it scrolls under it"
    for prop in ("left", "right", "width", "min-width", "max-width"):
        assert prop not in head, "the head sets %s: it has to follow the page column, which the sidebar's body margin-left moves" % prop
    side = _decls(rules, "body")["padding"].split()[1]
    assert head.get("margin", "").split()[1:2] == ["-" + side], "the head does not take the body's %s side padding back, so it would not run edge to edge" % side
    assert _decls(rules, "header.topbar").get("margin") == "0", "the top bar still has a margin of its own inside the head"


def check_head_fallback_css(page):
    """On a narrow screen OR a short one the head is in the normal flow, and the scroll padding goes back to nothing there."""
    rules = _css_rules(_style(page))
    static = [m for m, sel, d in rules if sel == ".v2head" and m is not None and d.get("position") == "static"]
    conditions = {c.replace(" ", "") for m in static for c in m.split(",")}
    assert {"(max-width:820px)", "(max-height:540px)"} <= conditions, (
        "the head is not in the normal flow on a narrow (820px) AND on a short (540px) screen, each on its own: %r" % sorted(conditions))
    for media in static:
        assert _decls(rules, "html", media).get("scroll-padding-top") == "0", "the scroll padding is not put back to nothing where the head is static"


def check_head_compact_css(page):
    """Everything in the head is height that never scrolls away: the top bar, the sheet bar and the open sheet's bar are padded short, the open sheet's
    controls share a row with what the sheet is, and the notes and warnings are small and do not force a row of their own."""
    rules = _css_rules(_style(page))

    def vertical(selector):
        value = _decls(rules, selector).get("padding", "")
        top = value.split()[0] if value else ""
        assert top.endswith("px"), "%s has no padding in px: %r" % (selector, value)
        return float(top[:-2])

    assert vertical("header.topbar") <= 10, "the top bar is as tall as the intake page's, which does not stay on screen"
    assert vertical(".sheets") <= 8, "the sheet bar is padded like a page section"
    assert vertical(".sheets .sh-open") <= 8, "the open sheet's bar is padded like a card"
    assert _decls(rules, ".sheets .sh-body").get("display") == "contents", "the open sheet's controls have a row of their own again"
    for selector in (".sheets .sh-hint", ".sheets .sh-empty", ".sheets .sh-note", ".sheets .sh-warn", ".sheets .sh-confirm"):
        size = _decls(rules, selector).get("font-size", "")
        assert size.endswith("px") and float(size[:-2]) <= 11.5, "%s is %r: not small" % (selector, size)
    assert _decls(rules, ".sheets .sh-note").get("flex") == "1 1 auto", "a note takes a whole row to itself again"


def check_scroll_padding_css(page):
    """html's scroll-padding-top is derived from the head's height, which the page keeps in --v2head-h."""
    pad = _decls(_css_rules(_style(page)), "html").get("scroll-padding-top", "")
    assert "var(--v2head-h" in pad, "html's scroll-padding-top is not the head's height (--v2head-h): %r" % pad
    # ...and none while focus is in the head itself (2026-10-20 audit: each keystroke in Rename, and each Tab, scrolled the page ~100px up)
    assert re.search(r"html:has\(#v2head :focus-within\)\{scroll-padding-top:0\}", _style(page)), (
        "typing or tabbing inside the head would scroll the page: no zero padding while focus is in it")


def check_head_height_cap(page):
    """The head never covers most of the window: past 70% of it the head scrolls inside itself (the Add-sheet list and a description box grow it)."""
    head = _decls(_css_rules(_style(page)), ".v2head")
    assert head.get("max-height") == "70vh" and head.get("overflow-y") == "auto", (
        "the head has no height cap: %r / %r" % (head.get("max-height"), head.get("overflow-y")))


def test_the_head_never_grows_past_most_of_the_window():
    check_head_height_cap(PAGE)


def test_the_sticky_head_holds_the_top_bar_then_the_sheets_and_sits_above_the_page_heading():
    """Hanz asked for the sheets directly under the four steps in the top bar, above the page title, on every step. They are siblings in one block
    because auth.js folds the burger, brand, steps and bell into header.topbar and destroys whatever else is inside it."""
    check_head_structure(PAGE)


def test_the_sticky_head_is_pinned_to_the_top_over_the_page_and_under_every_overlay():
    check_head_sticky_css(PAGE)


def test_the_head_is_in_the_normal_flow_on_a_narrow_or_a_short_screen():
    """Pinned there it would leave the step a sliver: 760px wide and under (a phone), or 640px tall and under. The order is the same either way."""
    check_head_fallback_css(PAGE)


def test_scroll_padding_is_the_heads_height_so_nothing_scrolled_to_stops_behind_it():
    check_scroll_padding_css(PAGE)
    js = (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")
    assert 'setProperty("--v2head-h"' in js, "nothing writes the custom property the CSS reads"


def test_the_head_is_kept_compact_one_tight_row_for_the_open_sheet_and_small_notes():
    """Hanz's brief for the sticky block: no legend line, the open sheet's bar one tight row while nothing is being renamed, confirmed or
    described, and the note about copies and the warnings kept but small."""
    check_head_compact_css(PAGE)


def test_the_sheet_bar_is_not_shown_before_init_draws_it(ran):
    """The page is behind "Loading the item library" until init: the bar is hidden by the page's own markup, shown the first time it has been drawn
    (once, never hidden again), and a page that cannot read its library never shows it."""
    s = ran["stickyHead"]
    assert s["before"] == {"hidden": True, "empty": True, "mainHidden": True}
    a = s["after"]
    assert a["hidden"] is False and a["drawn"] is True and a["mainHidden"] is False
    assert a["drawnFirst"] is True and a["shows"] == 1 and a["hides"] == 0, "shown before it was drawn, or shown and hidden again"
    assert a["readyFirst"] is True, "the bar was shown while the page still said it was loading"
    assert s["stayed"] == {"hidden": True, "writes": 0, "said": True}, "a page that could not load its library drew or showed the bar"


def test_the_heads_height_is_kept_in_the_property_the_scroll_padding_reads(ran):
    """A ResizeObserver on #v2head writes the height, rounded up, to --v2head-h on the html element; a repaint of the bar measures nothing when there
    is an observer; a head with no height (not laid out) leaves the last good figure."""
    s = ran["stickyHead"]
    assert s["watched"] == {"made": 1, "targets": [["v2head"]], "resizeListeners": 0}
    assert s["heights"] == {"idle": "", "first": "120px", "second": "151px", "none": "151px"}


def test_a_control_in_the_head_is_focused_without_scrolling_the_page(ran):
    """THE DEFECT A REAL BROWSER SHOWED. html's scroll-padding-top is the head's height, which puts the head's own controls inside the padded-off band, so
    a plain focus() on one of them scrolled the page to bring it out of the band: a click on Add sheet, Rename or a tab, and the arrow keys along the
    tabs, threw a scrolled page up by hundreds of pixels or to the top (headless Chrome on the real page, 2026-10-20). The caret goes back to the
    control by focus({ preventScroll: true }), and the arrow keys walk the tabs the same way and bring the tab into the strip by hand (the strip
    scrolls, the page does not)."""
    assert ran["focus"]["options"]["n"] >= 5 and ran["focus"]["options"]["noScroll"] is True
    k = ran["stripKeeps"]["keys"]
    assert k["opts"] == {"n": 6, "noScroll": True}, "six arrow-key moves, none of which may scroll the page"
    assert k["revealed"] == 350 - 300 + 8, "the strip is scrolled to the tab by hand"


def test_a_browser_with_no_resize_observer_is_told_by_the_repaint_and_by_the_window_resize(ran):
    s = ran["stickyHead"]
    assert s["fallback"] == {"resizeListeners": 1, "painted": "161px", "resized": "189px"}
    assert s["noRoot"] is True, "a document with no html element to write to threw"


# ── red without the code ─────────────────────────────────────────────────────────────────────────────────────
BREAKS = {
    "a base change writes no work type": (
        "js/polish-estimate.js", "    TW.setState(patch);", "    TW.setState({ tab_opts: patch.tab_opts });",
        lambda r: r["baseSwitch"]["draft"]["work_type"] != "epoxy" or r["baseSwitch"]["draft"]["base_tab_id"] != "Epoxy"),
    "a base change does not ask first": (
        "js/polish-estimate.js", "    sheetsUi.confirm = { row: row, ids: ids };", "    sheetsUi.confirm = { row: row, ids: ids }; makeBase(); return;",
        lambda r: r["baseSwitch"]["confirm"]["nothingChanged"] is not True or r["baseSwitch"]["confirm"]["saves"] != 0),
    "the Proposal step's lines do not follow the base": (
        "js/polish-estimate.js", "    if (PR && from !== to && st.price_overrides && typeof st.price_overrides === \"object\") {",
        "    if (false) {", lambda r: "Epoxy flooring" not in r["baseSwitch"]["lines2"].get("base", "")),
    "the old base is not put on the proposal": (
        "js/bid-model.js", '      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: true, show: true, price_mode: "total" });',
        '      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: false, show: true, price_mode: "total" });',
        lambda r: r["baseSwitch"]["draft"]["polishOpt"]["is_option"] is not True),
    "the combined pair is given a base id": (
        "js/bid-model.js", "    var patch = { work_type: baseOf(out).jobType, base_tab_id: want.length === 1 ? want[0] : null };",
        "    var patch = { work_type: baseOf(out).jobType, base_tab_id: want[0] };",
        lambda r: r["combined"]["draft"]["base_tab_id"] is not None),
    "a copy starts on the proposal": (
        "js/bid-model.js", "             patch: newOptionPatch(isObject(ctx) ? ctx.state : undefined, id, optionSettings(false)) };",
        "             patch: newOptionPatch(isObject(ctx) ? ctx.state : undefined, id, optionSettings(true)) };",
        lambda r: r["copy"]["tabOpts"]["Copy1"]["is_option"] is not False),
    "an added sheet starts off the proposal": (
        "js/bid-model.js", "             patch: newOptionPatch(c.state, id, optionSettings(true)) };",
        "             patch: newOptionPatch(c.state, id, optionSettings(false)) };",
        lambda r: r["add"]["afterEpoxy"]["tabOpts"]["Epoxy"]["is_option"] is not True),
    "a seal sheet can be priced as an add or deduct": (
        "js/polish-estimate.js", '    var want = mode === "deduct" && e.role !== "seal" ? "deduct" : "total";',
        '    var want = mode === "deduct" ? "deduct" : "total";', lambda r: r["seal"]["stillTotal"] != "total"),
    "a seal sheet can be the base": (
        "js/bid-model.js", "      return { e: e, base: base, inBase: inBase, opt: opt, optOnly: optOnly, canBase: !optOnly, price: price, on: on, mode: mode,",
        "      return { e: e, base: base, inBase: inBase, opt: opt, optOnly: optOnly, canBase: true, price: price, on: on, mode: mode,",
        lambda r: r["seal"]["noBaseRadio"] is not True),
    "the base can be deleted": (
        "js/polish-estimate.js", '    if (held.root || held.kind === "base") {', "    if (false) {",
        lambda r: "cannot be deleted" not in r["deleting"]["base"]["alert"]),
    "the base's delete button is live": (
        "js/bid-model.js", "        var locked = r.base || r.inBase || e.root;", "        var locked = false;",
        lambda r: r["deleting"]["base"]["disabled"] is not True),
    "a sheet is deleted by one press": (
        "js/polish-estimate.js", "    if (sheetsUi.armed !== tab) { sheetsUi.armed = tab; paintSheets(); return; }", "    void 0;",
        lambda r: r["deleting"]["armed"]["still"] != ["Copy1"]),
    "a click elsewhere leaves delete armed": (
        "js/polish-estimate.js", '    if (sheetsUi.armed && shWhat !== "delete") { sheetsUi.armed = null; paintSheets(); }', "    void 0;",
        lambda r: r["deleting"]["disarmed"] != "Delete"),
    "a name is checked while it is typed": (
        "js/polish-estimate.js", "      sheetsUi.draft = el.value;",
        "      sheetsUi.draft = el.value; sheetsUi.error = \"too soon\"; lastSheets = null; paintSheets();",
        lambda r: r["renaming"]["midWord"]["error"] is not False),
    "the derived figure is the wrong way round": (
        "js/bid-model.js", "            var d = Math.round(price) - Math.round(baseTotal);", "            var d = Math.round(baseTotal) - Math.round(price);",
        lambda r: r["options"]["deduct"]["summary"] != "Option, " + r["options"]["expectDeduct"]),
    "the words are not capped": (
        "js/polish-estimate.js", '    TW.setState(B.tabOptPatch(TW.getState(), tab, { desc: String(text || "").slice(0, 400) }));',
        '    TW.setState(B.tabOptPatch(TW.getState(), tab, { desc: String(text || "") }));', lambda r: r["options"]["capped"] != 400),
    "the words redraw the panel under the caret": (
        "js/polish-estimate.js", '    TW.setState(B.tabOptPatch(TW.getState(), tab, { desc: String(text || "").slice(0, 400) }));',
        '    TW.setState(B.tabOptPatch(TW.getState(), tab, { desc: String(text || "").slice(0, 400) })); lastSheets = null; paintSheets();',
        lambda r: r["options"]["typed"]["redraws"] != 0),
    "the caret is not put back": (
        "js/polish-estimate.js", "    if (want) focusSheetsKey(want);", "    void want;",
        lambda r: r["focus"]["afterSwitch"] != ["Copy1|on"]),
    "a repaint throws the strip back to the left": (
        "js/polish-estimate.js", "      if (newStrip && left) newStrip.scrollLeft = left;", "      void newStrip;",
        lambda r: r["stripKeeps"]["kept"].get("scrollLeft") != 150),
    "the open tab is never scrolled to": (
        "js/polish-estimate.js", "    else if (end > from + strip.clientWidth) strip.scrollLeft = end - strip.clientWidth + pad;", "    else void end;",
        lambda r: r["stripKeeps"]["reach"]["right"] != 628),
    "the arrow keys do nothing": (
        "js/polish-estimate.js", '    if (k !== "ArrowLeft" && k !== "ArrowRight" && k !== "Home" && k !== "End") return;', "    return;",
        lambda r: r["stripKeeps"]["keys"]["right"]["focused"] is None),
    "a refused add is laid inside the picker": (
        "js/bid-model.js", '    if (isObject(v.notice) && v.notice.at === "add") flow += noticeHtml(v.notice);',
        '    if (isObject(v.notice) && v.notice.at === "add") add += noticeHtml(v.notice);',
        lambda r: r["stripKeeps"]["notice"]["inBox"] is not None),
    "the strip does not scroll": (
        "polish-estimate.html", "    .sheets .sh-strip{overflow-x:auto;overflow-y:hidden;", "    .sheets .sh-strip{overflow-x:visible;overflow-y:hidden;",
        lambda r: r["floating"]["scrolls"] is not True),
    "the base's tab is not marked": (
        "js/bid-model.js", '(r.base || r.inBase ? " base" : "")', '""',
        lambda r: r["list"]["tabs"]["polishMarked"] is not True or r["combined"]["baseTabs"] != 2),
    "every tab is selected": (
        "js/bid-model.js", """'<button type="button" class="sh-name" role="tab" aria-selected="' + (open ? "true" : "false") + '" data-section-tab="'""",
        """'<button type="button" class="sh-name" role="tab" aria-selected="true" data-section-tab="'""",
        lambda r: r["list"]["tabs"]["selected"] != 1),
    "the bar is floated again": (
        "js/polish-estimate.js", "  function sheetsChanged(", "  function initSheetsPanelDrag() { TW.floatPanel($(\"sheets-panel\"), { handle: \"sh-head\", key: \"tw_v2sheets_pos\", width: 256 }); }\n  initSheetsPanelDrag();\n  function sheetsChanged(",
        lambda r: r["floating"]["floats"] != []),
    # --- the review findings ---
    "a preset change leaves the sheet's settings under the old key": (
        "js/polish-estimate.js", "        if (Object.keys(carried).length) TW.setState(carried);", "        void carried;",
        lambda r: r["gypPreset"].get("opt") != r["gypPreset"]["before"] or r["gypPreset"]["saved"]["entry"]["is_option"] is not False),
    "the Add menu lists no Gyp": (
        "js/bid-model.js", '        .filter(function (k) { if (k.role !== "gyp") return true; var first = !seenGyp; seenGyp = true; return first; })',
        '        .filter(function (k) { return k.role !== "gyp"; })',
        lambda r: "Gyp" not in r["add"]["menuLabels"]),
    "the Excel hint is always drawn": (
        "js/bid-model.js", "    if (f.rows.some(function (r) { return COPY_ID.test(r.e.tab); })) {", "    if (true) {",
        lambda r: r["add"]["excel"][0] is not False),
    "an option with no stored mode is priced as an Add or Deduct": (
        "js/bid-model.js", '      var mode = !optOnly && held.price_mode === "deduct" ? "deduct" : "total";',
        '      var mode = !optOnly && held.price_mode !== "total" ? "deduct" : "total";',
        lambda r: r["unstated"]["noEntry"]["total"] is not True or r["unstated"]["noMode"]["total"] is not True),
    "the old base keeps the mode it held": (
        "js/bid-model.js", '      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: true, show: true, price_mode: "total" });',
        '      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: true, show: true });',
        lambda r: r["demote"]["written"].get("price_mode") != "total"),
    "the old base stays hidden": (
        "js/bid-model.js", '      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: true, show: true, price_mode: "total" });',
        '      var kept = Object.assign(optionSettings(true), entryOf(id), { is_option: true, price_mode: "total" });',
        lambda r: r["demote"]["written"].get("show") is not True),
    "the switch leaves a hidden option hidden": (
        "js/polish-estimate.js", "    TW.setState(B.tabOptPatch(st, tab, on ? { is_option: false } : { is_option: true, show: true }));",
        "    TW.setState(B.tabOptPatch(st, tab, on ? { is_option: false } : { is_option: true }));",
        lambda r: r["hiddenOption"]["shown"]["on"] is not True),
    "a press clears nothing waiting in the panel": (
        "js/polish-estimate.js", '    sheetsUi.confirm = null; sheetsUi.armed = null; sheetsUi.renaming = null; sheetsUi.error = ""; sheetsUi.notice = null;',
        "    void 0;",
        lambda r: r["resets"]["afterOpen"] is not False or r["resets"]["afterOpenName"]["input"] is not False or r["resets"]["afterCopy"] is not False
        or r["resets"]["afterAdd"] is not False),
    "a saved name leaves the caret nowhere": (
        "js/polish-estimate.js", '    sheetsChanged(activeTab, tab + "|rename");', "    sheetsChanged(activeTab);",
        lambda r: r["focus"]["afterSavedName"] != ["Copy2|rename"]),
    "a refused copy is said at the top of the page": (
        "js/polish-estimate.js", '      sheetsUi.notice = { at: tab, text: "The sheet could not be copied: " + (err && err.message) };',
        '      say("The sheet could not be copied: " + (err && err.message));',
        lambda r: r["limit"]["copyRefused"]["inRow"] is None),
    "a refused add is said at the top of the page": (
        "js/polish-estimate.js", '      sheetsUi.notice = { at: "add", text: "The sheet could not be added: " + (err && err.message) };',
        '      say("The sheet could not be added: " + (err && err.message));',
        lambda r: r["limit"]["addRefused"]["inAddBlock"] is None),
    "a base change that moves the travel leaves the new carrier's blank row blank": (
        "js/polish-estimate.js", "    B.followDistance(ROOT, carrierBefore, kindsBefore);", "    void carrierBefore;",
        lambda r: r["baseTravel"]["blank"]["row"]["days"] != 6.5),
    # (round 7, Hanz's D1 of 2026-10-21: what is filled is a sheet that BECAME a base; a base that stays a base keeps its own, filled or blank. It was "only when the carrier moved".)
    "every base change fills the distance, even on a base that stays a base": (
        "js/bid-model.js", "      return { drives: list.map(function (k) { return k.tab; }), kindOf: function (tab) { return kinds.get(tab); } };",
        "      return { drives: [], kindOf: function (tab) { return kinds.get(tab); } };",
        lambda r: r["baseTravel"]["keepsCarrier"]["row"]["days"] != ""),
    "a refusal stays through the next click": (
        "js/polish-estimate.js", '    if (sheetsUi.notice && shWhat !== "copy" && shWhat !== "add") { sheetsUi.notice = null; paintSheets(); }',
        "    void 0;", lambda r: r["limit"]["afterClick"] is not None),
    "a Seal option on add or deduct is left as it was": (
        "js/polish-estimate.js", "    if (Object.keys(sealTotals).length) TW.setState(sealTotals);", "    void sealTotals;",
        lambda r: r["sealMode"]["written"]["Seal"]["price_mode"] != "total"),
    # --- the sticky head (2026-10-20) ---
    "the bar is shown before init draws it": (
        "polish-estimate.html", ' id="sheets-panel" aria-label="Sheets on this bid" hidden></section>',
        ' id="sheets-panel" aria-label="Sheets on this bid"></section>',
        lambda r: r["stickyHead"]["before"]["hidden"] is not True),
    "the bar is never shown": (
        "js/polish-estimate.js", "    if (shown) el.hidden = false;", "    void shown;",
        lambda r: r["stickyHead"]["after"]["hidden"] is not False),
    "the bar is shown before it is drawn": (
        "js/polish-estimate.js", "    var drew = html !== lastSheets;", "    var drew = html !== lastSheets; el.hidden = false;",
        lambda r: r["stickyHead"]["after"]["drawnFirst"] is not True),
    "the bar is shown while the page is still loading": (
        "js/polish-estimate.js", "  watchHead();", '  watchHead(); $("sheets-panel").hidden = false;',
        lambda r: r["stickyHead"]["before"]["hidden"] is not True or r["stickyHead"]["after"]["readyFirst"] is not True),
    "a control in the head is focused with a scrolling focus": (
        "js/polish-estimate.js", "      if (all[i].focus) all[i].focus({ preventScroll: true });", "      if (all[i].focus) all[i].focus();",
        lambda r: r["focus"]["options"]["noScroll"] is not True),
    "the arrow keys focus a tab with a scrolling focus": (
        "js/polish-estimate.js", "      tabs[to].focus({ preventScroll: true });", "      tabs[to].focus();",
        lambda r: r["stripKeeps"]["keys"]["opts"]["noScroll"] is not True),
    "the arrow keys do not bring the tab into the strip": (
        "js/polish-estimate.js",
        '      stripReveal(panel.querySelector("[data-sh-strip]"), typeof tabs[to].closest === "function" ? tabs[to].closest("li") : null);',
        "      void 0;",
        lambda r: r["stripKeeps"]["keys"]["revealed"] != 58),
    "the head is not observed": (
        "js/polish-estimate.js", "      try { headObserver = new RO(syncHeadHeight); headObserver.observe(head); } catch (err) { headObserver = null; }",
        "      headObserver = null;",
        lambda r: r["stickyHead"]["watched"]["made"] != 1 or r["stickyHead"]["heights"]["idle"] != ""),
    "the head's height is never written": (
        "js/polish-estimate.js", '    if (h > 0) root.style.setProperty("--v2head-h", h + "px");', "    void h;",
        lambda r: r["stickyHead"]["heights"]["first"] != "120px" or r["stickyHead"]["fallback"]["painted"] != "161px"),
    "the head's height is rounded down": (
        "js/polish-estimate.js", '    var h = box && typeof box.height === "number" ? Math.ceil(box.height) : 0;',
        '    var h = box && typeof box.height === "number" ? Math.floor(box.height) : 0;',
        lambda r: r["stickyHead"]["heights"]["second"] != "151px"),
    "a head with no height wipes the last one": (
        "js/polish-estimate.js", '    if (h > 0) root.style.setProperty("--v2head-h", h + "px");', '    root.style.setProperty("--v2head-h", h + "px");',
        lambda r: r["stickyHead"]["heights"]["none"] != "151px"),
    "the window's resize is listened to even with an observer": (
        "js/polish-estimate.js", '    if (!headObserver) window.addEventListener("resize", syncHeadHeight);',
        '    window.addEventListener("resize", syncHeadHeight);',
        lambda r: r["stickyHead"]["watched"]["resizeListeners"] != 0),
    "a browser without an observer is never told of a resize": (
        "js/polish-estimate.js", '    if (!headObserver) window.addEventListener("resize", syncHeadHeight);', "    void 0;",
        lambda r: r["stickyHead"]["fallback"]["resized"] != "189px"),
    "a repaint does not tell a browser without an observer": (
        "js/polish-estimate.js", "    if (!headObserver && (drew || shown)) syncHeadHeight();", "    void drew;",
        lambda r: r["stickyHead"]["fallback"]["painted"] != "161px"),
    "a repaint measures the head even with an observer": (
        "js/polish-estimate.js", "    if (!headObserver && (drew || shown)) syncHeadHeight();", "    if (drew || shown) syncHeadHeight();",
        lambda r: r["stickyHead"]["heights"]["idle"] != ""),
    "a document with no html element throws": (
        "js/polish-estimate.js",
        '    if (!head || !root || !root.style || typeof root.style.setProperty !== "function" || typeof head.getBoundingClientRect !== "function") return;',
        '    if (!head || typeof head.getBoundingClientRect !== "function") return;',
        lambda r: r["stickyHead"]["noRoot"] is not True),
    "the legend line is back": (
        "js/bid-model.js", "    if (f.rows.some(function (r) { return COPY_ID.test(r.e.tab); })) {",
        "    h += '<p class=\"sh-hint\"><span class=\"rdot\"></span> marks the base bid, which sets the lump sum and the job type.</p>';\n"
        "    if (f.rows.some(function (r) { return COPY_ID.test(r.e.tab); })) {",
        lambda r: r["list"]["legend"]["gone"] is not True or r["markup"]["legendAnywhere"] is not False),
    "the base radio no longer says what it means": (
        "js/bid-model.js", "          '\" title=\"Base bid: ' + BASE_MEANS + '\">' : \"\") + '</span>';",
        "          '\" title=\"Base bid\">' : \"\") + '</span>';",
        lambda r: r["list"]["legend"]["titled"] != 2),
    "the combine button no longer says what it means": (
        "js/bid-model.js", "          key(t, \"combine\") + ' title=\"Base bid: Epoxy and Polish together. It ' + BASE_MEANS + '\">' + ic(\"layers\", 12) +",
        "          key(t, \"combine\") + '>' + ic(\"layers\", 12) +",
        lambda r: r["combined"]["button"]["titled"] is not True),
    "the strip draws the Epoxy + Polish tab again": (
        "js/bid-model.js", "    f.rows.forEach(function (r) { tabs.push(tabHtml(r)); });",
        "    if (f.pair) tabs.push('<li class=\"sh sh-tab combined\" data-sh-row=\"combined\" role=\"presentation\"><span class=\"sh-nm\">Epoxy + Polish</span></li>');\n"
        "    f.rows.forEach(function (r) { tabs.push(tabHtml(r)); });",
        lambda r: r["combined"]["tab"]["none"] is not True),
    "a sheet outside the pair offers the combine button": (
        "js/bid-model.js", "        var combine = !!f.pair && !f.unreadable && f.baseIds.length !== 2 && f.pair.indexOf(t) >= 0;",
        "        var combine = !!f.pair && !f.unreadable && f.baseIds.length !== 2;",
        lambda r: r["combined"]["button"]["onCopy"] is not False),
    "the combine button stays once the pair is the base": (
        "js/bid-model.js", "        var combine = !!f.pair && !f.unreadable && f.baseIds.length !== 2 && f.pair.indexOf(t) >= 0;",
        "        var combine = !!f.pair && !f.unreadable && f.pair.indexOf(t) >= 0;",
        lambda r: r["combined"]["noButtonOnceCombined"] is not True),
    "a combined base's sheet does not say what the pair comes to": (
        "js/bid-model.js", "      else if (r.inBase) s += '<span class=\"pill\">In the base bid</span><span class=\"sh-sum\">Epoxy + Polish together' +",
        "      else if (r.inBase) s += '<span class=\"pill\">In the base bid</span><span class=\"sh-sum\">' +",
        lambda r: "Epoxy + Polish together" not in r["combined"]["bars"]["epoxy"]),
    "the caret is left behind the question": (
        "js/polish-estimate.js", '    if (act === "combine") { askBase("combined", "confirm|yes"); return; }',
        '    if (act === "combine") { askBase("combined"); return; }',
        lambda r: r["combined"]["focus"]["asked"] != ["confirm|yes"]),
    "cancelling the pair loses the caret": (
        "js/polish-estimate.js", '      sheetsUi.focus = row === "combined" ? activeTab + "|combine" : (row ? row + "|base" : null);',
        '      sheetsUi.focus = row ? row + "|base" : null;',
        lambda r: r["combined"]["focus"]["cancelled"] != ["Epoxy|combine"]),
    "the second press of a double-click does not rename": (
        "js/polish-estimate.js", '      if (e.detail >= 2 && secTab.getAttribute("data-section-tab") === activeTab) {',
        '      if (false) {',
        lambda r: r["renameByTab"]["afterTwo"]["naming"] is None),
    "a dblclick does not rename": (
        "js/polish-estimate.js", '    if (secTab) renameFromTab(secTab.getAttribute("data-section-tab"), secTab.getAttribute("data-sh-key"));',
        '    void secTab;',
        lambda r: r["renameByTab"]["dblOther"]["naming"] is None),
    "F2 does not rename": (
        "js/polish-estimate.js", '    if (k === "F2") {', '    if (k === "F2" && false) {',
        lambda r: r["renameByTab"]["f2"]["naming"] is None),
    "a dblclick throws away what was typed": (
        "js/polish-estimate.js", "    if (tab === null || tab === undefined || sheetsUi.renaming === tab) return;",
        "    if (tab === null || tab === undefined) return;",
        lambda r: r["renameByTab"]["afterDbl"]["label"] != "Gara"),
    "a tab does not say it can be renamed": (
        "js/bid-model.js", "' title=\"Double-click to rename\" aria-current=\"'", "' aria-current=\"'",
        lambda r: r["renameByTab"]["titled"] is not True),
    "the note about copies is gone": (
        "js/bid-model.js", "      h += '<p class=\"sh-hint\">Copies print on the proposal. The Excel download does not include them.</p>';",
        "      h += '';",
        lambda r: r["list"]["copiesNote"] is not True),
    # Its own proposal (Create Multiple Proposals, plan step 5)
    "the own-proposal switch does nothing": (
        "js/polish-estimate.js", '    if (act === "own") { toggleOwnProposal(tab); return; }', '    if (act === "own") { return; }',
        lambda r: r["ownProposal"]["one"]["ids"] != ["Polish", "Epoxy"]),
    "the page does not pass the ticked sheets to the panel": (
        "js/polish-estimate.js", "      baseIds: st && Array.isArray(st.base_tab_ids) ? st.base_tab_ids : undefined,", "      baseIds: undefined,",
        lambda r: r["ownProposal"]["one"]["bids"] != {"Polish": 1, "Epoxy": 2} or r["ownProposal"]["one"]["checked"] != "true"),
    "no Bid tag on the strip": (
        "js/bid-model.js", "          (r.bid ? '<span class=\"sh-bidtag\" data-sh-bid=\"'", "          (false ? '<span class=\"sh-bidtag\" data-sh-bid=\"'",
        lambda r: r["ownProposal"]["one"]["bids"] != {"Polish": 1, "Epoxy": 2}),
    "a base change drops the ticked sheets": (
        "js/polish-estimate.js", "      patch.base_tab_ids = PR.moveBaseId(st, from, to, order, true);", "",
        lambda r: r["ownProposal"]["swapped"]["ids"] != ["Epoxy", "Polish", "Copy1"]),
    "the scope bar does not say where the proposals are made": (
        "js/polish-estimate.js", "    if (bidIds.length >= 2) {", "    if (false) {",
        lambda r: "Create the proposals on the Proposal step" not in r["ownProposal"]["one"]["scope"]),
    "a combined base is given proposals": (
        "js/bid-model.js", "    if (ps === null || ps.base === null || tab === ps.base) return null;", "    if (ps === null || tab === ps.base) return null;",
        lambda r: r["ownProposal"]["pure"]["pair"] is not None),
    "a Seal sheet is offered its own proposal": (
        "js/bid-model.js", "    return !!e && e.kind !== \"off\" && !types.tab(types.tabOfSheet(e.sheet)).optionOnly;", "    return !!e && e.kind !== \"off\";",
        lambda r: r["ownProposal"]["pure"]["seal"] is not None or r["ownProposal"]["pure"]["idsSeal"] != ["Polish", "Epoxy"]),
    "a deleted sheet's own-proposal tick is kept": (
        "js/bid-model.js", "    if (Array.isArray(st.base_tab_ids) && st.base_tab_ids.indexOf(tab) >= 0) {", "    if (false) {",
        lambda r: r["ownProposal"]["deleted"]["afterDelete"]["ids"] != ["Polish"] or r["ownProposal"]["deleted"]["recopied"]["own"] != "false"),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    # A BREAK IS NOTICED BY A FACT THAT CHANGED, never by a crash. A page that fails to boot, or a section that throws, has no facts to
    # compare, and counting that as noticed let three entries pass without a single assertion having seen the behaviour they break.
    assert proc.returncode == 0, "the break stopped the page outright, so no fact noticed it: " + name
    got = last_json_line(proc.stdout)
    crashed = sorted(k for k, v in got.items() if isinstance(v, dict) and "error" in v)
    assert not crashed, "the break crashed %s instead of changing a fact: %s" % (", ".join(crashed), name)
    assert noticed(got), "the checks did not notice: " + name


# ── the markup and CSS checks, shown to go red: the page's text is broken in a copy, and the check that owns the fact must refuse it ───────
def _swap(old, new):
    def mutate(page):
        assert page.count(old) == 1, "the mutation anchor %r appears %d times in the page, not once" % (old, page.count(old))
        return page.replace(old, new)
    return mutate


_SHEETS_LINE = re.compile(r'\n *<section class="sheets" id="sheets-panel"[^\n]*</section>')


def _sheets_into_main(page):
    line = _SHEETS_LINE.search(page).group(0)
    return page.replace(line, "", 1).replace('<div id="main" hidden>', '<div id="main" hidden>' + line, 1)


def _sheets_above_the_bar(page):
    line = _SHEETS_LINE.search(page).group(0)
    return page.replace(line, "", 1).replace('\n    <header class="topbar">', line + '\n    <header class="topbar">', 1)


_MEDIA = "@media (max-width:820px),(max-height:540px){"
_HEAD = ".v2head{position:sticky;top:0;z-index:30;margin:0 -22px 22px;background:var(--surf);"
STATIC_BREAKS = {
    "the sheets go back inside #main": (check_head_structure, _sheets_into_main),
    "the sheets come above the top bar": (check_head_structure, _sheets_above_the_bar),
    "the sheets are shown before init": (check_head_structure, _swap(' id="sheets-panel" aria-label="Sheets on this bid" hidden></section>',
                                                                     ' id="sheets-panel" aria-label="Sheets on this bid"></section>')),
    "the head is not sticky": (check_head_sticky_css, _swap(".v2head{position:sticky;", ".v2head{position:relative;")),
    "the head is pinned below the top": (check_head_sticky_css, _swap("top:0;z-index:30;", "top:12px;z-index:30;")),
    "the head covers a modal": (check_head_sticky_css, _swap(_HEAD, _HEAD.replace("z-index:30", "z-index:20000"))),
    "the head hides behind the bid bar": (check_head_sticky_css, _swap(_HEAD, _HEAD.replace("z-index:30", "z-index:5"))),
    "content shows through the head": (check_head_sticky_css, _swap(_HEAD, _HEAD.replace("background:var(--surf);", ""))),
    "the head does not take the body's side padding back": (check_head_sticky_css, _swap(_HEAD, _HEAD.replace("margin:0 -22px 22px", "margin:0 0 22px"))),
    "the top bar keeps a margin of its own": (check_head_sticky_css, _swap("justify-content:space-between;gap:12px;margin:0;",
                                                                         "justify-content:space-between;gap:12px;margin:0 -22px 22px;")),
    "a narrow screen keeps the head pinned": (check_head_fallback_css, _swap(_MEDIA, "@media (max-height:540px){")),
    "a short screen keeps the head pinned": (check_head_fallback_css, _swap(_MEDIA, "@media (max-width:820px){")),
    "the head is static only when the screen is narrow AND short": (check_head_fallback_css, _swap(
        _MEDIA, "@media (max-width:820px) and (max-height:540px){")),
    "typing in the head scrolls the page": (check_scroll_padding_css, _swap("    html:has(#v2head :focus-within){scroll-padding-top:0}\n", "")),
    "the head can grow past the window": (check_head_height_cap, _swap(";max-height:70vh;overflow-y:auto}", "}")),
    "the scroll padding stays where the head is static": (check_head_fallback_css, _swap("      html{scroll-padding-top:0}\n", "")),
    "the scroll padding is a fixed number": (check_scroll_padding_css, _swap("calc(var(--v2head-h,0px) + 6px)", "64px")),
    "the top bar is as tall as the intake page's": (check_head_compact_css, _swap("padding:8px 24px;border-bottom", "padding:16px 24px;border-bottom")),
    "the sheet bar is padded like a page section": (check_head_compact_css, _swap(".sheets{margin:0;padding:8px max(22px", ".sheets{margin:0;padding:16px max(22px")),
    "the open sheet's bar is padded like a card": (check_head_compact_css, _swap("padding:7px 12px;box-shadow:var(--shadow)}", "padding:11px 14px;box-shadow:var(--shadow)}")),
    "the open sheet's controls get a row of their own": (check_head_compact_css, _swap(".sheets .sh-body{display:contents}", ".sheets .sh-body{display:flex}")),
    "a note takes a whole row": (check_head_compact_css, _swap(".sheets .sh-note{margin:0;flex:1 1 auto;", ".sheets .sh-note{margin:0;flex:1 1 100%;")),
    "the note about copies is body-sized": (check_head_compact_css, _swap(".sheets .sh-hint{margin:5px 2px 0;font-size:11px", ".sheets .sh-hint{margin:5px 2px 0;font-size:13px")),
}


@pytest.mark.parametrize("name", sorted(STATIC_BREAKS))
def test_the_markup_and_css_checks_go_red_when_the_page_changes(name):
    check, mutate = STATIC_BREAKS[name]
    check(PAGE)                                      # it passes on the page as shipped
    # The mutation is made OUTSIDE pytest.raises: an anchor that no longer matches has to fail this test, not pass it
    # (2026-10-20 audit: with the anchor check inside, an edited anchor let 22 of these pass with nothing mutated).
    mutated = mutate(PAGE)
    assert mutated != PAGE, "the mutation changed nothing"
    with pytest.raises(AssertionError):
        check(mutated)
