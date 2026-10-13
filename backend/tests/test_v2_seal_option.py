"""Phase 15: Seal as an option on any v2 bid, printed under Options & Unit Prices.

WHAT CHANGED. The estimate page has a "+ Add option" button that offers Seal and Seal (+Jnts) (js/bid-model.js addOption,
js/work-types.js optionSheets). An option is a section of the bid with kind "option": its own takeoff, crew and rates
snapshot, priced on the seal profile through the engine, never added into the lump sum, shown on Review as a card of its own
that says "Option, not in the lump sum", and written into the save as a priced tab (role seal, kind option) with the draft's
tab_opts saying it is an option, which is the key the proposal side reads to print it under Options & Unit Prices. Seal and
Leveling are options on a bid and never a job type (Hanz, 2026-10-07). Leveling is Phase 16.

PROVEN BY EXECUTION, three ways. The prices against Kyle's workbook are tests/test_seal_v2_proof.py's.
  1. THE MODEL. addOption and removeOption, composePricingSnapshot with an option in it, and the vocabulary, run with no page.
  2. THE PAGE. tests/js/seal-page-harness.js boots js/polish-estimate.js whole on a Polish bid and an Epoxy bid, clicks "+ Add
     option", and reads off what the page held, drew and saved. Every price is set beside the same option priced by hand.
  3. THE DOCUMENT. The save the page wrote is opened by the proposal step's own pricing (rebuildPricing) and rendered through
     the real renderer: the option prints under Options & Unit Prices in the words and the money a live-estimate option does.

Each mutation at the bottom breaks a scratch copy of the page or the model and the check it belongs to goes red.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
PAGE_HARNESS = TESTS / "js" / "seal-page-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js"]


def run_page(frontend=FRONTEND, tmp=None):
    proc = run_node(PAGE_HARNESS, frontend, plan_json(tmp))
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    require_node()
    return run_page(tmp=tmp_path_factory.mktemp("seal-page"))


# the document prints an en dash between a figure and its words; a cell the renderer cannot encode reads back as U+FFFD
EN = chr(0x2013)
BAD = chr(0xFFFD)


def _money(n):
    return "${:,}".format(n)


# ── 1. the model ─────────────────────────────────────────────────────────────────────────────────
def test_seal_and_seal_with_joints_are_offered_and_leveling_is_not_yet(page):
    o = page["model"]["offers"]
    assert o["fresh"] == o["sheets"] == ["Seal", "Seal (+Jnts)"] and o["sealOffered"] is True and o["levelingOffered"] is False
    assert o["afterSeal"] == ["Seal (+Jnts)"], "an option the bid holds is not offered again"
    assert o["noModel"] == ["Seal", "Seal (+Jnts)"]


def test_an_option_is_added_as_a_section_of_kind_option_on_the_seal_profile_and_the_bid_handed_in_is_not_touched(page):
    m = page["model"]
    assert m["added"] == {"kind": "option", "layout": "seal", "profile": "seal@1", "pooled": True,
                          "labor": ["seal-install", "seal-jointfill", "seal-mockup"], "takeoff": [["wb-seal-2-coats", 10000]]}
    assert m["addIsPure"] is True


def test_adding_an_option_never_reseeds_anything_else_not_even_a_root_that_stated_nothing(page):
    """seedNewSections seeds the root too when it has stated nothing. Only the new section is taken from that seeding, so the
    estimator's Polish rows are exactly what they were, whether or not they had been saved."""
    assert page["model"]["kept"] is True and page["model"]["blankRootKept"] is True


def test_only_the_offered_sheets_can_be_added_once_each_and_only_an_option_can_be_removed(page):
    r = page["model"]["refuses"]
    for who in ("leveling", "epoxy", "polish"):
        assert "is not offered as an option" in r[who], (who, r[who])
    assert "is already a section" in r["twice"]
    assert r["removeRoot"] == '"Polish" is not an option of this bid' and r["removeBase"] == '"Epoxy" is not an option of this bid'
    assert "has no section" in r["removeUnknown"]
    assert page["model"]["removed"] == {"tabs": {}, "offered": ["Seal", "Seal (+Jnts)"]}, (
        "the bid keeps an empty tabs object, so its next save still writes the whole snapshot")


def test_a_default_is_read_for_a_section_by_its_own_tab_and_a_bare_tab_key_is_still_refused_as_a_job_type(page):
    """A section is one tab, and an option tab is not a job type: seeding a Seal option used to throw from tabsFor. It is named
    `{ tab }` now, which says "exactly this tab"; the bare string "seal" still throws, so a job type's defaults can never be read
    under a tab's name by mistake."""
    w = page["model"]["workTypes"]
    assert w["sealOwn"] is True and w["polishRowOnSeal"] is False and w["emptyOnSeal"] is True and w["combo"] is True
    assert "tabsFor() was asked about" in w["bareSealStillThrows"] and "not a tab" in w["notATab"]
    assert w["kindOfSection"] == ["polish", "epoxy", "gyp", {"tab": "seal"}], (
        "Polish, Epoxy and Gyp sections read a job type's defaults exactly as they always did")


def test_the_snapshot_prices_the_option_apart_and_the_lump_sum_is_the_base_alone(page):
    s = page["model"]["snapshot"]
    assert s["lump"] == s["handLump"] == s["computed"], "the option is not in the lump sum"
    assert s["tabs"] == [["Polish", "polish", "base", s["handLump"], "Seal-page Polish 800 Grit"],
                         ["Seal", "seal", "option", s["sealTotal"], "Sealed Concrete"]] and s["sealPriced"] == s["sealTotal"]
    assert s["area"] == {"polish_sf": 10000}, "an option adds no area"


def test_the_snapshot_says_the_option_is_an_option_and_keeps_what_the_estimator_set_in_the_proposal_step(page):
    s = page["model"]["snapshot"]
    assert s["tabOpts"] == {"Seal": {"show_system": True, "show_diff": False, "is_option": True, "show": True, "price_mode": "total"}}
    assert s["keptOpts"] == {"Seal": {"is_option": False, "show": False, "price_mode": "deduct"}, "Other": {"is_option": True}}, (
        "an entry the draft already holds is never rewritten, and nothing else of the draft's tab_opts is lost")


def test_a_bid_that_never_had_an_option_still_writes_what_it_always_wrote_and_one_that_lost_its_last_option_writes_it_all(page):
    s = page["model"]["snapshot"]
    assert s["singleKeys"] == ["polish_estimate", "polish_sf", "polish_2_sf", "computed_bid"]
    assert s["afterRemoveKeys"][:5] == ["polish_estimate", "polish_sf", "polish_2_sf", "computed_bid", "priced_tabs"]
    assert s["afterRemoveTabs"] == ["Polish"] and s["afterRemoveHasOpts"] is False, (
        "the price snapshot the removed option was in is overwritten, so the proposal stops listing it")
    assert s["keys"][-1] == "tab_opts" and s["keys"][:13] == s["afterRemoveKeys"]


def test_the_seal_tabs_own_flag_cells_are_written_from_the_shared_job_conditions_so_it_answers_as_the_base_does(page):
    """Phase 7b's known gap, closed: Local also writes Seal!B4 ('Seal (+Jnts)'!B4 mirrors it, and Seal's lodging line reads
    it) and Renovation also writes Seal!B10 (the patch is IF(B10="New", ...), and a blank takes the Reno branch), through
    the same table the live intake and the v2 model both read. Taxable, Prevailing wage and Remodel tax stay formulas on the
    Seal tabs that mirror Epoxy, so they are not written."""
    c = page["model"]["cells"]
    assert c["localOff"] == ["No", "No", "No"] and c["localOn"] == ["Yes", "Yes", "Yes"], "Seal answers Local as Epoxy and Polish do"
    assert c["reno"] == ["New", "New", "New"], "a job that never said is New in every sheet, never blank"
    assert c["tableLocal"][-1] == "Seal!B4" and c["tableReno"][-1] == "Seal!B10"
    assert c["carried"] == [["reno", ["Epoxy!B10", "Polish!B10", "Seal!B10"]]]
    assert c["splitStillWritesSeal"] == ["Yes", "New"], "the split rule is about the two tax answers only"
    assert c["sealTaxStillAMirror"] == [False, False, False]


def test_each_seal_sheet_is_named_in_the_live_estimates_words_and_the_joints_one_says_so(page):
    assert page["model"]["desc"] == {"seal": "Sealed Concrete", "jnts": "Sealed Concrete with Joint Filler"}


# ── 2. the page ──────────────────────────────────────────────────────────────────────────────────
def test_a_bid_with_no_option_hides_its_strip_offers_add_option_and_writes_nothing_by_being_opened(page):
    f = page["fresh"]
    assert f["stripHidden"] is True and f["barHidden"] is False and f["barButtons"] == ["+ Add option"]
    assert f["choicesShown"] == [] and f["noTabsKey"] is True
    assert f["savesOnOpen"] == 0 and f["armedOnOpen"] == 0


def test_add_option_opens_a_menu_of_the_two_seal_sheets(page):
    assert page["menu"] == {"choices": ["Seal", "Seal (+Jnts)"], "toggleLabel": "Cancel"}


def test_choosing_seal_adds_an_option_seeded_like_a_new_section_that_carries_no_travel(page):
    a = page["added"]
    assert a["tabs"] == ["Seal"] and a["kind"] == "option" and a["layout"] == "seal" and a["profile"] == a["snapshot"] == "seal@1"
    assert a["pooled"] is True
    assert a["takeoff"] == [["wb-seal-2-coats", 10000, "SF"]], "the sheet's own default, over what the base measures"
    assert a["laborIds"] == ["seal-install", "seal-jointfill", "seal-mockup"] and a["noTravelRow"] is True
    assert a["strip"] == ["Polish", "Seal"] and a["stripHidden"] is False and a["activeIsSeal"] is True
    assert "Seal (option)" in a["stripLabel"]
    assert a["barAfter"] == {"remove": ["Seal"], "choices": [], "menuClosed": True} and a["saved"] is True
    assert a["materialPanel"] == {"hasPatchCaption": True, "hasRow": True, "noDyeCard": True}, (
        "the option's Material step is the ordinary takeoff, with the patch the sheet always charges, and none of Polish's cards")
    assert a["laborPanel"]["noTravelBlock"] is True and "charged once for the whole job, on the Polish section" in a["laborPanel"]["note"]


def test_the_option_is_priced_apart_by_the_seal_profile_and_the_lump_sum_is_the_base_alone(page):
    p = page["priced"]
    assert p["pageSeal"] == p["handSeal"] > 0 and p["pagePolish"] == p["handPolish"] > 0
    assert p["sealIsPriceable"] is True
    assert p["lump"] == p["computed"] == p["bar"] == p["baseLumpBefore"] == p["pagePolish"], (
        "adding an option does not move the lump sum, the bar or the save")
    assert p["sealTotals"] == p["handSeal"], "the section's totals are stamped from its own bid"
    assert p["taxes"] == p["handPolishTaxes"], "the option's taxes are not in the base's"
    assert p["material"] == 3500 and p["tooling"] == 2700, (
        "a new floor's patch, two coats of sealer, and tooling at $0.27 a square foot")
    assert p["maths"] == "Polish {} · Seal {} option (not in the lump sum)".format(_money(p["pagePolish"]), _money(p["pageSeal"]))


def test_the_save_writes_the_option_as_a_priced_tab_and_says_it_is_an_option(page):
    s = page["saved"]
    for key in ("priced_tabs", "tab_opts", "proposal_lump_sum", "proposal_sales_tax", "proposal_remodel_tax", "computed_bid", "sheet_area"):
        assert key in s["keys"], key
    p = page["priced"]
    assert [t[:5] for t in s["pricedTabs"]] == [["Polish", "polish", "base", True, p["handPolish"]],
                                                 ["Seal", "seal", "option", True, p["handSeal"]]]
    assert s["pricedTabs"][1][7] == "Sealed Concrete"
    assert s["tabOpts"] == {"Seal": {"show_system": True, "show_diff": False, "is_option": True, "show": True, "price_mode": "total"}}
    assert s["area"] == {"polish_sf": 10000} and s["sealArea"] == {"polish_sf": 10000}, "an option adds no area to the proposal's"
    assert s["taxable"] == [True, False]


def test_review_shows_each_option_as_its_own_card_with_its_own_total_and_says_it_is_not_in_the_lump_sum(page):
    r = page["review"]
    assert r["hasOptionCard"] is True
    assert "Option, not in the lump sum" in r["optionCardText"] and "Seal option total" in r["optionCardText"]
    assert r["figure"] == r["handFigure"] == _money(page["priced"]["handSeal"])
    assert r["keys"] == ["option", "takeoff", "labor", "travel", "markup"], "the option's card has its own colour key"
    assert r["noWholeBidCard"] is True, "one base and an option have nothing to add up"
    assert r["markupTotal"] == _money(page["priced"]["handPolish"]), "the base's own card says the base's price"
    assert r["openButton"] is True


def test_the_option_open_on_review_says_so_first_and_shows_its_own_cards_with_its_tooling(page):
    o = page["review"]["onSeal"]
    assert o["note"] == "Option, not in the lump sum." and o["optionCardFirst"] is True and o["toolingCard"] is True
    assert o["markupTotal"] == _money(page["priced"]["handSeal"])


def test_a_figure_typed_on_review_moves_the_base_and_the_option_card_stays_its_own(page):
    l = page["review"]["live"]
    assert l["base"] == l["baseOnPage"]


def test_what_the_estimator_set_on_the_option_in_the_proposal_step_survives_the_next_save(page):
    assert page["kept"]["tabOpts"] == {"Seal": {"show_system": True, "show_diff": False, "is_option": True, "show": False,
                                                 "price_mode": "deduct", "desc": "My own words"}}


def test_seal_with_joints_can_be_added_beside_seal_and_opens_on_the_joint_filler_assembly(page):
    s = page["second"]
    assert s["choicesBefore"] == ["Seal (+Jnts)"] and s["tabs"] == ["Seal", "Seal (+Jnts)"]
    assert s["jntsTakeoff"] == [["wb-seal-jnts-2-coats", 10000]]
    assert s["bar"] == {"remove": ["Seal", "Seal (+Jnts)"], "addMenu": False}, "with both held there is nothing left to offer"
    assert s["pricedTabs"] == [["Polish", "base", "Seal-page Polish 800 Grit"], ["Seal", "option", "Sealed Concrete"],
                               ["Seal (+Jnts)", "option", "Sealed Concrete with Joint Filler"]]
    assert _money(s["lump"]) == page["review"]["live"]["base"], "the lump sum is the base priced by hand, neither option is in it"


def test_removing_an_option_takes_two_presses_and_the_proposal_side_forgets_it(page):
    r = page["remove"]
    assert r["armedLabel"] == "Click again to remove Seal option" and r["stillThere"] == ["Seal", "Seal (+Jnts)"]
    assert r["disarmedLabel"] == "Remove Seal option", "a click anywhere else puts it back"
    assert r["nothingToOffer"] is True
    a = r["after"]
    assert a["tabs"] == ["Seal (+Jnts)"] and a["pricedTabs"] == ["Polish", "Seal (+Jnts)"] and a["tabOptsKeys"] == ["Seal (+Jnts)"]
    assert a["lump"] == a["baseLump"], "removing an option does not move the lump sum"
    n = r["none"]
    assert n["stripHidden"] is True and n["tabsKey"] == {} and n["pricedTabs"] == [["Polish", "base"]]
    assert n["tabOptsKeys"] == [] and n["menuOffers"] is True
    assert n["lump"] == a["lump"] and n["bar"] == _money(n["lump"])


def test_a_saved_bid_that_holds_an_option_opens_as_saved_and_writes_nothing(page):
    r = page["reopenedWithOption"]
    assert r["saves"] == 0 and r["armed"] == 0 and r["strip"] == ["Polish", "Seal"] and r["remove"] == ["Seal"]
    assert r["bar"] == r["handBar"], "the reopened bar is the saved base priced by hand, without the option"
    assert page["reopened"] == {"saves": 0, "armed": 0}


def test_an_epoxy_job_takes_the_option_too_and_the_epoxy_section_carries_the_travel(page):
    e = page["epoxyJob"]
    assert e["kinds"] == [["Polish", "off"], ["Epoxy", "base"], ["Seal (+Jnts)", "option"]] and e["carrier"] == "Epoxy"
    assert e["jntsTakeoff"] == [["wb-seal-jnts-2-coats", 6000]], "seeded from the Epoxy area"
    assert e["jntsLaborIds"] == ["seal-install", "seal-jointfill", "seal-mockup"]


def test_a_renovation_pays_the_renovation_patch_and_a_job_that_never_said_is_a_new_floor(page):
    r = page["reno"]
    assert r["renoOn"] is True and r["newOn"] is False and r["blankIsNew"] is False
    assert r["renoMaterial"] - r["newMaterial"] == pytest.approx(r["expectedDifference"]), "$0.15 a SF against $0.05"
    assert r["renoCaption"] is True and r["newCaption"] is True


def test_an_option_is_still_added_when_the_library_cannot_answer(page):
    assert page["bare"]["tabs"] == ["Seal"]


# ── 3. the document ──────────────────────────────────────────────────────────────────────────────
def _drive(**case):
    import test_price_block_reconciles as R
    return R, R._drive(work_type="polish", blocks=R._template_blocks("polish", "Direct"), rebuild=True,
                       total=0.0, sales_tax=0.0, remodel_tax=0.0, **case)


def _printed(R, res):
    body = json.loads(json.dumps(res["payload"]))
    body["values"] = dict(R._NARRATIVE, **body["values"])
    return R._price_rows(R._render(body))


def test_a_generated_proposal_prints_the_option_under_options_and_unit_prices_with_the_options_own_price(page):
    """The page's save, opened by the proposal step's own pricing and rendered by the real renderer. The option prints in
    the same words and the same money a live-estimate option does: the same line is printed from a room shaped the way
    the Estimate step's snapshot shapes it."""
    s = page["saved"]
    R, res = _drive(state={"priced_tabs": s["pricedTabsFull"], "tab_opts": s["tabOpts"]})
    rooms = res["payload"]["rooms"]
    assert [r["id"] for r in rooms] == ["Polish", "Seal"] and rooms[0]["is_base"] is True and rooms[1]["is_base"] is False
    assert rooms[1]["bid"]["total"] == page["priced"]["handSeal"] and rooms[0]["bid"]["total"] == page["priced"]["handPolish"]
    rows = _printed(R, res)
    line = ("{} " + EN + " Sealed Concrete as described above (material sales tax INCLUDED)").format(_money(page["priced"]["handSeal"]))
    printed = [l.replace(BAD, EN) for l in rows["options"]]
    assert printed == [line], printed
    assert "Options" in rows["all"], "under the Options heading"
    # the base's own price block is the base alone
    assert rows["total"] == page["priced"]["handPolish"] and _money(page["priced"]["handSeal"]) not in " ".join(rows["all"][:rows["all"].index("Options")])
    # the same option, shaped as the live Estimate step shapes it, prints the same line
    live_room = {"id": "Seal", "name": "Seal", "is_base": False, "show": True, "price_mode": "total", "option_desc": "Sealed Concrete",
                 "system_desc": "Sealed Concrete", "base_total": rooms[0]["bid"]["total"],
                 "bid": {"total": page["priced"]["handSeal"], "sales_tax": rooms[1]["bid"]["sales_tax"], "remodel": 0,
                         "taxable": True, "remodel_on": False}}
    live = R._drive(work_type="polish", blocks=R._template_blocks("polish", "Direct"), total=float(rooms[0]["bid"]["total"]),
                    sales_tax=float(rooms[0]["bid"]["sales_tax"]), remodel_tax=0.0, taxable=True, remodel_on=False,
                    rooms=[rooms[0], live_room])
    assert [l.replace(BAD, EN) for l in _printed(R, live)["options"]] == printed


def test_an_option_the_estimator_hid_in_the_proposal_step_does_not_print_and_a_removed_one_never_did(page):
    s = page["saved"]
    hidden = {"Seal": dict(s["tabOpts"]["Seal"], show=False)}
    R, res = _drive(state={"priced_tabs": s["pricedTabsFull"], "tab_opts": hidden})
    assert _printed(R, res)["options"] == []
    only_base = [t for t in s["pricedTabsFull"] if t["id"] == "Polish"]
    R, res = _drive(state={"priced_tabs": only_base, "tab_opts": {}})
    assert _printed(R, res)["options"] == []


def test_the_option_and_the_base_both_go_to_the_customers_portal_as_rooms_the_option_is_never_summed_into(page):
    s = page["saved"]
    R, res = _drive(state={"priced_tabs": s["pricedTabsFull"], "tab_opts": s["tabOpts"]})
    v = res["payload"]["values"]
    assert v["proposal_lump_sum"] == page["priced"]["handPolish"], "the lump sum the document prints is the base alone"
    assert [r["id"] for r in res["payload"]["rooms"]] == ["Polish", "Seal"]


# ── the checks go red when the code changes ──────────────────────────────────────────────────────
PAGE_BREAKS = {
    "an option is added into the lump sum": (
        "js/bid-model.js",
        '    var isBase = function (e) { return e.kind === "base" && !types.tab(types.tabOfSheet(e.root ? ROOT_TAB : e.tab)).optionOnly; };',
        '    var isBase = function (e) { return e.kind !== "off"; };',
        lambda r: r["priced"]["lump"] != r["priced"]["pagePolish"] or r["model"]["snapshot"]["lump"] != r["model"]["snapshot"]["handLump"]),
    "the save does not say the option is an option": (
        "js/bid-model.js", "      out.tab_opts = opts;", "      void opts;",
        lambda r: "tab_opts" in r["saved"]["keys"] or r["model"]["snapshot"]["tabOpts"] is not None),
    "an entry in tab_opts is rewritten over the estimators edits": (
        "js/bid-model.js", "        if (has.call(heldOpts, id)) return;", "        void 0;",
        lambda r: r["model"]["snapshot"]["keptOpts"]["Seal"]["is_option"] is True),
    "the option is named by its first row": (
        "js/bid-model.js", '    if (entry && (entry.role === "gyp" || entry.role === "seal")) {', '    if (entry && entry.role === "gyp") {',
        lambda r: r["model"]["desc"]["seal"] != "Sealed Concrete"),
    "a bid that lost its last option is saved as a single bid": (
        "js/bid-model.js", '    var single = entries.length === 1 && root.kind === "base" && !isObject(model.tabs);',
        '    var single = entries.length === 1 && root.kind === "base";',
        lambda r: r["model"]["snapshot"]["afterRemoveTabs"] != ["Polish"] or r["remove"]["none"]["pricedTabs"] != [["Polish", "base"]]),
    "an added option takes the whole seeded model, root included": (
        "js/bid-model.js", "    out.tabs = copyInto(copyInto({}, out.tabs), Object.fromEntries([[tabId, seeded.tabs[tabId]]]));",
        "    out = seeded;", lambda r: r["model"]["blankRootKept"] is not True),
    "any sheet can be added as an option": (
        "js/bid-model.js", "    if (types.optionSheets().indexOf(tabId) < 0) {", "    if (false) {",
        lambda r: not (r["model"]["refuses"]["leveling"] or "").count("not offered")),
    "a section is not read by its own tab": (
        "js/bid-model.js", '    if (workType && typeof workType === "object") {', "    if (false) {",
        lambda r: r["model"]["workTypes"]["sealOwn"] is not True),
    "the table stops writing Seal's Local cell": (
        "js/work-types.js", '''default: true, cells: ["Epoxy!B4", "Polish!B4", 'Gyp (USG 1-8")!B5', "Gyp (FR)!B5", "Seal!B4"], on: "Yes", off: "No", needs: null,''',
        '''default: true, cells: ["Epoxy!B4", "Polish!B4", 'Gyp (USG 1-8")!B5', "Gyp (FR)!B5"], on: "Yes", off: "No", needs: null,''',
        lambda r: r["model"]["cells"]["localOff"][0] != "No"),
    "the table stops writing Seal's Renovation cell": (
        "js/work-types.js", '''default: false, cells: ["Epoxy!B10", "Polish!B10", "Seal!B10"], on: "Reno", off: "New", needs: null,''',
        '''default: false, cells: ["Epoxy!B10", "Polish!B10"], on: "Reno", off: "New", needs: null,''',
        lambda r: r["model"]["cells"]["reno"][0] != "New"),
    "seal is not offered in the vocabulary": (
        "js/work-types.js", "      offered: true,", "      offered: false,",
        lambda r: r["menu"]["choices"] != ["Seal", "Seal (+Jnts)"]),
    "the option's card is coloured as the markup card": (
        "js/polish-estimate.js", """      html += '<div data-rev="option" class="rev" data-option-card="' + esc(e.tab) + '"><div class="rev-h">' + esc(e.tab) +""",
        """      html += '<div data-rev="markup" class="rev" data-option-card="' + esc(e.tab) + '"><div class="rev-h">' + esc(e.tab) +""",
        lambda r: r["review"]["keys"] != ["option", "takeoff", "labor", "travel", "markup"]),
    "the card does not say the option is not in the lump sum": (
        "js/polish-estimate.js", '  var OPTION_NOT_IN_SUM = "Option, not in the lump sum";', '  var OPTION_NOT_IN_SUM = "Option";',
        lambda r: "Option, not in the lump sum" not in r["review"]["optionCardText"]),
    "an option is removed by one press": (
        "js/polish-estimate.js", "    if (removeArmed !== tab) { removeArmed = tab; paintOptionBar(); return; }", "    void 0;",
        lambda r: r["remove"]["stillThere"] != ["Seal", "Seal (+Jnts)"]),
    "a removed option's settings stay on the draft": (
        "js/polish-estimate.js", "Object.keys(held).filter(function (k) { return k !== tab; })", "Object.keys(held).filter(function (k) { return true; })",
        lambda r: "Seal" in r["remove"]["after"]["tabOptsKeys"]),
    "the patch ignores a renovation on the page": (
        "js/polish-estimate.js", "        items: ITEMS, sf: B.takeoffSf(takeoff), reno: jobIsReno(),", "        items: ITEMS, sf: B.takeoffSf(takeoff), reno: false,",
        lambda r: r["reno"]["renoMaterial"] == r["reno"]["newMaterial"]),
    "the option section is not edited on the page's own panels": (
        "js/polish-estimate.js", '    return !!e && (e.role === "polish" || e.role === "epoxy" || e.role === "gyp" || e.role === "seal");',
        '    return !!e && (e.role === "polish" || e.role === "epoxy" || e.role === "gyp");',
        lambda r: r["added"]["materialPanel"]["hasPatchCaption"] is not True),
}


@pytest.mark.parametrize("name", sorted(PAGE_BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = PAGE_BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(PAGE_HARNESS, frontend, plan_json(tmp_path))
    if proc.returncode != 0:
        return   # the break stopped the page outright: noticed
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name
