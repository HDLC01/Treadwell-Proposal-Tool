"""THE SHEETS PANEL: the floating widget that replaced the section strip and the "+ Add option" bar on the v2 estimate page.

WHAT CHANGED. Sheets phase 1 gave the model copies, fresh sheets of any type, a chosen base bid, renaming and deleting
(js/bid-model.js copySection, addSheet, pickBase, renameSection, deleteSection). Phase 2 gave pages one drag-and-remember helper
(TW.floatPanel). This is the face of it, built from the mockup Hanz approved (2026-10-13):

  * ONE PANEL, ON EVERY BID (aside#sheets-panel, drawn by B.sheetsPanelHtml, painted by paintSheets). One row per sheet that is part of
    the bid: its name and price, a radio that makes it the base bid, "Base bid" or what it is as an option, and, for the one sheet
    that is open, the switch "On the proposal as an option", Total or Add / Deduct, the words it prints, Copy, Rename and Delete.
  * "Add sheet" is the first thing under the hint. Every type the tool prices is on the menu; a sheet added from it starts ON the
    proposal, and a copy starts OFF.
  * MAKING A SHEET THE BASE asks first ("Make Epoxy the base bid?"), then everything follows: B.pickBase moves the kinds and answers
    work_type, base_tab_id and the old base's tab_opts (ON the proposal, priced as a total), and the lines typed on the Proposal step
    follow the new base by the rule the other two base pickers run (TWPrice.applyBasePick). A combined Epoxy + Polish base is its own
    row and writes work_type "combo" and no base id.
  * Delete takes two presses and is disabled on the base (with the reason beside it). A name is checked when it is committed, never while
    it is typed. Seal sheets are options only: Total, never Add / Deduct, never the base.
  * It floats above 1400px under its own key (tw_v2sheets_pos) and sits in the flow above the estimate below that.

EVERYTHING RUNS CODE. tests/js/sheets-panel-harness.js boots the real js/polish-estimate.js on the real bid-model.js, library-core.js,
price-lines-core.js and epoxy-takeoff.js and reads every fact off the page after it ran. The CSS is the one thing a headless run cannot lay
out, so it is read as the rules that make the panel float and drop inline. The last tests break a scratch copy of the code in many ways and
require each fact to notice; `break_source` refuses an anchor that is not in the file exactly once.
"""
import html
import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "sheets-panel-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]
SECTIONS = ["list", "copy", "add", "seal", "baseSwitch", "combined", "deleting", "renaming", "options", "reopen", "unreadable", "focus",
            "markup", "floating", "gypPreset", "limit", "sealMode", "demote", "resets", "unstated", "hiddenOption"]
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


def test_a_base_radio_is_on_every_sheet_that_can_be_the_base_and_the_hint_says_what_it_means(ran):
    p = ran["list"]
    assert p["before"]["radios"] == 2, "Polish and its copy have one, the Seal sheet does not"
    assert p["hasHint"] is True, "the hint names the base bid, and says copies are not in the Excel download"


def test_add_sheet_is_the_first_control_under_the_hint_above_the_list(ran):
    assert ran["list"]["addAtTop"] is True


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


def test_a_combined_epoxy_and_polish_base_is_its_own_row_and_writes_combo_and_no_base_id(ran):
    c = ran["combined"]
    assert c["hadRow"] is True
    assert c["confirm"] == {"title": "Make Epoxy + Polish (combined) the base bid?",
                            "body": "The job becomes a Combo job and the proposal switches to the Combo format."}
    assert c["draft"] == {"work_type": "combo", "base_tab_id": None}, "no sheet is the base on its own"
    assert c["kinds"] == [["Polish", "base"], ["Epoxy", "base"]] and c["jobType"] == "combo"
    assert c["savedBase"] is None and c["savedWorkType"] == "combo"
    assert c["lump"] == c["polishTotal"] + c["epoxyTotal"], "the pair is summed"
    assert c["checked"] is True and c["pills"] == 2 and c["rowPrice"] == "${:,}".format(c["lump"]) and c["rowType"] == "COMBINED"


def test_going_from_the_combined_base_to_one_sheet_makes_the_other_an_option_on_the_proposal(ran):
    back = ran["combined"]["back"]
    assert back["body"].startswith("The job becomes an Epoxy job") and back["body"].endswith("priced as a total.")
    assert back["work_type"] == "epoxy" and back["base_tab_id"] == "Epoxy"
    assert back["polishOpt"]["is_option"] is True and back["polishOpt"]["price_mode"] == "total"
    assert back["kinds"] == [["Polish", "option"], ["Epoxy", "base"]]


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
    assert a["pricedTabs"] == ["Polish"] and a["nowHidden"] is True, "with one sheet left the Open sheet line hides again"


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
    assert m["oneSheetNow"] == "", "one sheet has nothing to tell apart"
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


# ── 12. it floats, and drops inline ──────────────────────────────────────────────────────────────────────────
def test_the_panel_floats_under_its_own_key_and_the_page_keeps_a_lane_for_it(ran):
    f = ran["floating"]
    assert f["floats"] == [{"id": "sheets-panel", "opts": {"handle": "sh-head", "draggingClass": "sh-dragging",
                                                           "key": "tw_v2sheets_pos", "width": 256}}], (
        "its own key: the rail on step 3 and the cheat sheet keep theirs")
    wide = f["wide"].replace(" ", "")
    for decl in ("body{padding-right:288px}", "position:fixed", "width:256px", "z-index:10", "overflow-y:auto",
                 "max-height:calc(100dvh-260px)", ".sheets.sh-dragging{opacity:.93}"):
        assert decl in wide, "above 1400px the panel lost " + decl


def test_below_1400px_the_panel_drops_into_the_flow_above_the_estimate_bounded_and_as_a_grid_of_cards(ran):
    f = ran["floating"]
    narrow = f["narrow"].replace(" ", "")
    for decl in (".sheets{margin:0014px;max-height:40dvh;overflow-y:auto}", "grid-template-columns:repeat(auto-fill,minmax(240px,1fr))"):
        assert decl in narrow, "below 1400px the panel lost " + decl
    assert "position:fixed" not in narrow
    assert f["markupHasPanelFirst"] is True, "in the flow it sits above the step rail"


def test_the_old_strip_and_option_bar_are_gone_and_the_page_loads_the_base_pick_rule(ran):
    assert ran["floating"]["oldStripGone"] is True and ran["floating"]["loadsPriceRule"] is True


def test_no_new_copy_in_the_panel_uses_a_dash(ran):
    """House rule: new words for users have no em or en dash. The harness drew the panel and the Open sheet line in twelve states (a
    confirm, a name being refused, Delete armed, the Add menu, a combined base, a bid that cannot be read) and the text of all of them is read."""
    states = ran["markup"]["states"]
    assert len(states) == 12 and all(isinstance(s, str) and s for s in states)
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
        "js/bid-model.js", "          var locked = r.base || r.inBase || e.root;", "          var locked = false;",
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
    "the panel is not registered to float": (
        "js/polish-estimate.js", "  initSheetsPanelDrag();", "  void 0;", lambda r: r["floating"]["floats"] == []),
    "the panel does not drop inline": (
        "polish-estimate.html", "      .sheets{margin:0 0 14px;max-height:40dvh;overflow-y:auto}", "      .sheets{margin:0 0 14px}",
        lambda r: ".sheets{margin:0014px;max-height:40dvh;overflow-y:auto}" not in r["floating"]["narrow"].replace(" ", "")),
    "the page keeps no lane for the panel": (
        "polish-estimate.html", "      body{padding-right:288px}", "      body{padding-right:0}",
        lambda r: "body{padding-right:288px}" not in r["floating"]["wide"].replace(" ", "")),
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
    "a refusal stays through the next click": (
        "js/polish-estimate.js", '    if (sheetsUi.notice && shWhat !== "copy" && shWhat !== "add") { sheetsUi.notice = null; paintSheets(); }',
        "    void 0;", lambda r: r["limit"]["afterClick"] is not None),
    "a Seal option on add or deduct is left as it was": (
        "js/polish-estimate.js", "    if (Object.keys(sealTotals).length) TW.setState(sealTotals);", "    void sealTotals;",
        lambda r: r["sealMode"]["written"]["Seal"]["price_mode"] != "total"),
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
