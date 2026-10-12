"""Phase 13: a Combo job (Epoxy + Polish) priced end to end in Estimating Tool v2.

WHAT CHANGED. Combo is `ready` in js/work-types.js, so the v2 intake offers it. A Combo bid is TWO base sections of one
estimate: the Polish root and an Epoxy section (js/bid-model.js sectionsForJob). Each is priced on its own profile, the
bid is the engine's combine (each section's total AFTER its own gross profit, summed; never the two sub-totals pooled and
priced once), and the job's travel is charged ONCE, on the section that carries it (the Polish root, as the plan says;
Kyle can override it). The estimate page's section strip lets the estimator work the two sections one after the other,
each with its own takeoff and crew; its Review step shows both sections and the combined figure; and a save writes the
keys the Combo proposal reads (priced_tabs, proposal_lump_sum and the two taxes, sheet_area).

PROVEN BY EXECUTION, three ways.
  1. THE WORKBOOK. In Kyle's workbook a Combo job is the Epoxy tab and the Polish tab each priced on its own, and the
     proposal adds the two totals. The workbook oracle already holds what each tab answered for hundreds of jobs
     (tests/fixtures/oracle). tests/js/combo-v2-proof-harness.js pairs a Polish job with an Epoxy job that answers the same
     job questions, prices the pair through v2 the way the page does (markupChain for the root, priceSection for Epoxy,
     composePricingSnapshot for the pair), and requires the lump sum, both taxes and each tab's own total to equal the sum
     of the two workbook answers, to the cent. The same pairs priced as one pooled chain differ, so the check can fail.
  2. THE PAGE. tests/js/combo-page-harness.js boots js/polish-estimate.js whole on a combo draft. Every figure the page
     shows or saves is set beside the same job priced by hand with no page in it.
  3. THE DOCUMENT. The Combo proposal is rendered from the payload the proposal page composes over the v2 save, and its
     Option 1 and Option 2 lines are the two sections' totals.

Each mutation at the bottom breaks a scratch copy of the page or the model and the check it belongs to goes red.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
PAGE_HARNESS = TESTS / "js" / "combo-page-harness.js"
PROOF_HARNESS = TESTS / "js" / "combo-v2-proof-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js"]


def run_page(frontend=FRONTEND, tmp=None):
    proc = run_node(PAGE_HARNESS, frontend, plan_json(tmp))
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


def run_proof(frontend=FRONTEND):
    proc = run_node(PROOF_HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    require_node()
    return run_page(tmp=tmp_path_factory.mktemp("combo-page"))


@pytest.fixture(scope="module")
def proof():
    require_node()
    return run_proof()


# ── the proof against Kyle's workbook ────────────────────────────────────────────────────────────
def test_a_combo_priced_through_v2_equals_the_workbooks_two_tabs_added_to_the_cent(proof):
    """Each pair is one Polish workbook run and one Epoxy workbook run answering the same job questions. v2 prices the
    pair as a combo; the lump sum, the two taxes and each tab's own total must be the workbook's, exactly."""
    assert proof["wrong"] == [] and proof["wrongCount"] == 0, proof["wrong"]
    assert proof["exact"] == proof["pairs"] >= 150, proof


def test_the_pairs_include_jobs_with_travel_and_with_the_polish_tooling_line_and_are_not_all_alike(proof):
    """A pairing that only ever met jobs with no travel and no tooling would prove less. 129 of the pairs carry a Polish
    tooling figure (the departure the Polish proof predicts: the same dollars in the sub-total), and some carry none."""
    assert proof["folded"] >= 100 and proof["pairs"] - proof["folded"] >= 20, proof
    assert proof["polishCandidates"] >= 60 and proof["epoxyCandidates"] >= 20


def test_pricing_the_two_sections_as_one_pooled_chain_is_a_different_bid(proof):
    """Why combine sums AFTER each section's own gross profit: pooled, the job lands on another GP rung. The same pairs
    priced pooled differ from the workbook in most cases, so agreeing with it is not an accident of the arithmetic."""
    assert proof["pooledDiffers"] >= 100, proof


# ── a combo is two base sections on the model ────────────────────────────────────────────────────
def test_a_combo_job_is_the_polish_root_and_an_epoxy_section_both_bases_and_polish_carries_the_travel(page):
    m = page["model"]
    assert m["tabs"] == ["Epoxy"] and m["kinds"] == [["Polish", "base"], ["Epoxy", "base"]]
    assert m["carrier"] == "Polish", "the job's travel and fees default belong to one section, the first base"
    assert m["rootKindWritten"] == "none", "the Polish root stays the ordinary base it always was"
    assert m["sameAgain"] is True, "asking again changes nothing"


def test_a_new_combo_job_opens_on_polish_with_both_sections_seeded_and_writes_nothing(page):
    o = page["opened"]
    assert o["tabs"] == ["Epoxy"] and o["rootKind"] == "base" and o["epoxyKind"] == "base"
    assert o["strip"] == ['data-section-tab="Polish"', 'data-section-tab="Epoxy"'] and o["stripHidden"] is False
    assert o["activeIs"] == "Polish", "the section that carries the travel is the one the bid opens on"
    assert o["rootTakeoff"] == [[10000, "SF"]], "the intake's Polish area seeds the root"
    assert o["epoxyTakeoff"] == [[6000, "SF"], [300, "LF"]], "the intake's Epoxy area and cove seed the Epoxy section"
    assert o["savesOnOpen"] == 0
    assert o["rootLaborIds"] == ["polishing", "travel"] and o["epoxyLaborIds"] == ["epoxy-install"], (
        "each section gets its own crew from the library, and only the carrier gets Travel")


# ── pricing: each section on its own profile, summed ─────────────────────────────────────────────
def test_the_bar_the_save_and_the_proposals_lump_are_the_two_sections_priced_by_hand_and_added(page):
    p = page["priced"]
    assert p["pagePolish"] == p["handPolish"] > 0 and p["pageEpoxy"] == p["handEpoxy"] > 0
    assert p["barNumber"] == p["handCombined"] == p["lump"] == p["computed"]
    assert p["handCombined"] == p["handPolish"] + p["handEpoxy"] and p["notPooled"] is True
    assert p["savedPolishTotals"] == p["handPolish"] and p["savedEpoxyTotals"] == p["handEpoxy"]
    assert p["taxes"] == p["handTaxes"] and p["taxes"][0] > 0
    assert p["maths"] == "Polish ${:,} + Epoxy ${:,}".format(p["handPolish"], p["handEpoxy"])


def test_a_save_writes_both_sections_as_base_tabs_and_the_keys_the_combo_proposal_reads(page):
    s = page["saved"]
    for key in ("priced_tabs", "proposal_lump_sum", "proposal_sales_tax", "proposal_remodel_tax", "proposal_taxable",
                "proposal_remodel_on", "sheet_area", "cost_snapshot", "computed_bid", "phase_price", "polish_sf"):
        assert key in s["keys"], key
    assert [t[:4] for t in s["pricedTabs"]] == [["Polish", "polish", "base", True], ["Epoxy", "epoxy", "base", True]]
    assert s["pricedTabs"][0][5] == {"polish_sf": 10000} and s["pricedTabs"][1][5] == {"epoxy_sf": 6000, "cove_lf": 300}
    assert s["area"] == {"polish_sf": 10000, "epoxy_sf": 6000, "cove_lf": 300}, "the Area line sums the base sections"
    assert s["polishSf"] == 10000 and s["polishSf2"] == ""
    assert s["savedTabs"] == ["Epoxy"] and s["rootKind"] == "base"
    assert s["cost"]["man_hours"] > 0 and s["phase"] == 0 and s["taxable"] == [True, False]


# ── the travel is charged once ───────────────────────────────────────────────────────────────────
def test_hotel_and_per_diem_are_charged_once_on_polish_and_never_again_on_epoxy(page):
    t = page["travel"]
    assert (t["polishTravel"], t["epoxyTravel"]) == (t["jobTravel"], 0)
    assert t["epoxyAfter"] == t["epoxyBefore"], "the Epoxy section's price does not move when the job's travel does"
    assert t["polishAfter"] > t["polishBefore"]
    assert t["lump"] == t["handLump"] and t["handLump"] - t["handLumpBefore"] == t["polishAfter"] - t["polishBefore"]


def test_the_section_that_does_not_carry_the_travel_says_where_it_is_charged_instead_of_drawing_it(page):
    t = page["travel"]
    assert t["epoxyLaborHasBlock"] is False and t["epoxyLaborHasTravelRow"] is False
    assert t["epoxyLaborNote"] == ("Travel, Hotel and Per Diem are charged once for the whole job, on the Polish section. "
                                   "Open it to change them.")
    assert t["epoxyReviewNote"] is True and t["epoxyReviewHotelLines"] is False


# ── the Review step ──────────────────────────────────────────────────────────────────────────────
def test_the_review_step_shows_both_sections_and_the_combined_figure_above_the_sections_own_cards(page):
    r = page["review"]
    assert r["hasCard"] is True and r["cardFirst"] is True
    t = page["travel"]
    assert r["labels"] == ["Polish", "Epoxy", "Combined base bid"]
    assert (r["polishFigure"], r["epoxyFigure"], r["before"]) == tuple(
        "${:,}".format(n) for n in (t["polishAfter"], t["epoxyAfter"], t["lump"]))
    assert r["hotelHasLodging"] is True, "on the carrier, the Hotel card still lists the job's lodging"


def test_a_figure_typed_on_review_moves_the_whole_bid_card_live(page):
    a = page["review"]["afterContingency"]
    assert a["job"] == a["handJob"] and a["polish"] == a["handPolish"] and a["epoxy"] == a["handEpoxy"]
    assert a["job"] != page["review"]["before"]


# ── editing one section never touches the other ──────────────────────────────────────────────────
def test_editing_epoxy_never_writes_over_the_polish_rows_and_the_area_follows(page):
    i = page["isolated"]
    assert i["rootTakeoff"] == i["rootBefore"] and i["epoxyMeasurement"] == "5500"
    assert i["savedAreas"] == {"polish_sf": 10000, "epoxy_sf": 5500, "cove_lf": 300}


# ── what must not move ───────────────────────────────────────────────────────────────────────────
def test_a_saved_combo_bid_opens_as_saved_and_writes_nothing(page):
    r = page["reopened"]
    assert r["saves"] == 0 and r["armed"] == 0 and r["tabs"] == ["Epoxy"]
    assert r["strip"] == ['data-section-tab="Polish"', 'data-section-tab="Epoxy"']
    assert r["bar"] == "${:,}".format(r["handBar"]), "the reopened bar is the saved job priced by hand"


def test_a_polish_bid_and_an_epoxy_bid_have_no_whole_bid_card_and_read_as_they_did(page):
    s = page["single"]
    assert s["polishCard"] is False and s["epoxyCard"] is False and s["polishTabs"] == "none"
    assert s["polishHotel"] is True and s["epoxyNote"] is False, "a bid with one section is its own carrier"
    assert s["epoxyLaborHasTravelBlock"] is True


# ── a saved job whose type is switched on the intake ─────────────────────────────────────────────
# The intake's job-type radio stays open once an estimate exists, so a saved Epoxy, Polish or Combo bid can be switched.
# The bid must follow the job type: before this, Epoxy to Combo kept pricing Epoxy alone (the Polish root stayed off),
# Polish to Combo added an Epoxy section with no crew row, and Combo to Polish went on pricing both sections.
def _digits(figure):
    return int(figure.replace("$", "").replace(",", ""))


def test_a_saved_epoxy_job_switched_to_combo_turns_the_polish_section_back_on(page):
    s = page["switched"]["epoxyToCombo"]
    assert s["kinds"] == [["Polish", "base"], ["Epoxy", "base"]]
    assert s["strip"] == ['data-section-tab="Polish"', 'data-section-tab="Epoxy"']
    assert s["bar"] == s["handBar"] and s["barOnOpen"] == s["bar"], "the bar is the saved job priced by hand, both sections"


def test_that_switch_is_saved_once_with_both_sections_so_the_proposal_never_sees_the_old_job(page):
    s = page["switched"]["epoxyToCombo"]
    assert s["savesOnOpen"] == 0 and s["saves"] == 1, "the page opens quietly and arms exactly one save"
    assert s["savedPricedTabs"] == [["Polish", "base"], ["Epoxy", "base"]]
    assert s["savedLump"] == _digits(s["bar"])
    again = page["switched"]["epoxyToComboReopen"]
    assert again["saves"] == 0 and again["armed"] == 0, "the switched bid, reopened, writes nothing"


def test_a_saved_polish_job_switched_to_combo_gets_an_epoxy_section_with_its_crew_row(page):
    s = page["switched"]["polishToCombo"]
    assert s["kinds"] == [["Polish", "base"], ["Epoxy", "base"]]
    assert s["epoxyLabor"] == ["epoxy-install"], "the new section is crewed from the library like a new combo's"
    assert s["epoxyTakeoff"] == [[6000, "SF"], [300, "LF"]]
    assert s["bar"] == s["handBar"] and s["saves"] == 1 and s["savesOnOpen"] == 0
    assert s["savedPricedTabs"] == [["Polish", "base"], ["Epoxy", "base"]]


def test_a_saved_combo_job_switched_to_polish_prices_polish_alone_and_keeps_the_epoxy_rows(page):
    sw = page["switched"]
    s = sw["comboToPolish"]
    assert s["kinds"] == [["Polish", "base"], ["Epoxy", "off"]]
    assert s["strip"] == [], "a job with one section has no section strip"
    assert s["bar"] == s["handBar"] and _digits(s["bar"]) < _digits(sw["comboBefore"])
    assert s["savedPricedTabs"] == [["Polish", "base"]] and s["savedLump"] == _digits(s["bar"])
    back = sw["comboToPolishAndBack"]
    assert back["kinds"] == [["Polish", "base"], ["Epoxy", "base"]] and back["bar"] == sw["comboBefore"]
    assert back["epoxyTakeoff"] == [["5500", "SF"], [300, "LF"]], "switching away and back loses no row"


def test_sections_for_job_follows_the_job_type_both_ways_and_leaves_a_plain_polish_bid_alone(page):
    m = page["switchModel"]
    assert m["epoxyToCombo"] == [["Polish", "base"], ["Epoxy", "base"]] and m["carrier"] == "Polish"
    assert m["rootKindAfterCombo"] == "none", "the root's off is lifted, not replaced by a stamp a Polish bid never had"
    assert m["comboToPolish"] == [["Polish", "base"], ["Epoxy", "off"]] and m["rowsKept"] is True
    assert m["plainPolishUnchanged"] is True
    # the fourth is a Gyp job: since Phase 14 it is ready, so a bid that has no Gyp section is given one (the base sheet)
    assert m["toAdd"] == [["Epoxy"], [], [], ['Gyp (USG 1-8")']]


# ── the document ─────────────────────────────────────────────────────────────────────────────────
def _document(page):
    import test_price_block_reconciles as R
    run = R._combo_drive(page["saved"]["pricedTabsFull"])
    return run, R._printed_from(run["payload"])


def test_the_combo_proposal_prints_the_two_sections_totals_and_their_areas_from_the_v2_save(page):
    """The proposal page rebuilds the price from priced_tabs (rebuildPricing) and the Combo template prints each system
    as an Option. Rendered through the real page code and the real renderer: Option 1 is the Epoxy section's total and
    Option 2 the Polish section's, each with its own tax, and the area tokens are the sections' areas."""
    run, lines = _document(page)
    values = run["payload"]["values"]
    p = page["priced"]
    assert values["proposal_lump_sum"] == p["lump"] == p["handCombined"]
    assert (values["proposal_sales_tax"], values["proposal_remodel_tax"]) == tuple(p["handTaxes"])
    assert (values["epoxy_sf"], values["polish_sf"], values["cove_lf"]) == ("6,000", "10,000", "300")
    money = lambda n: "${:,}".format(n)
    printed = [ln.replace("�", "-") for ln in lines if ln.startswith("$")]
    assert any(ln.startswith(money(p["pageEpoxy"])) and "Total" in ln for ln in printed), printed
    assert any(ln.startswith(money(p["pagePolish"])) and "Total" in ln for ln in printed), printed
    assert any("Option 1: Epoxy flooring" in ln for ln in printed) and any("Option 2: Polished Concrete flooring" in ln for ln in printed)
    # the two Total rows add up to the lump sum the page holds
    totals = [int(re.sub(r"[^0-9]", "", ln.split(" ")[0])) for ln in printed if ln.endswith("Total")]
    assert sum(totals) == p["lump"], (totals, p["lump"])


# ── the checks go red when the code changes ──────────────────────────────────────────────────────
PAGE_BREAKS = {
    "combo is not ready in the vocabulary": (
        "js/work-types.js", '    { key: "combo",  label: "Combo (Epoxy + Polish)", tabs: ["epoxy", "polish"], ready: true,',
        '    { key: "combo",  label: "Combo (Epoxy + Polish)", tabs: ["epoxy", "polish"], ready: false,',
        lambda r: r["model"]["tabs"] != ["Epoxy"]),
    "the job's travel is charged on every section": (
        "js/bid-model.js", "      travel: carrier ? travelCosts(model.travel, s.labor).total : 0,",
        "      travel: travelCosts(model.travel, s.labor).total,",
        lambda r: r["travel"]["epoxyTravel"] != 0 or r["priced"]["pageEpoxy"] != r["priced"]["handEpoxy"]),
    "the combined bid takes only the first section": (
        "js/bid-engine.js",
        "      sums = Object.assign({}, sums, Object.fromEntries([[key, tabs.reduce(function (t, x) { return t + num(x.result[key]); }, 0)]]));",
        "      sums = Object.assign({}, sums, Object.fromEntries([[key, tabs.slice(0, 1).reduce(function (t, x) { return t + num(x.result[key]); }, 0)]]));",
        lambda r: r["priced"]["lump"] != r["priced"]["handCombined"]),
    "the Polish root is taken out of a combo": (
        "js/bid-model.js", "    var needsRoot = baseTabs.some(function (rec) { return rec.sheets.indexOf(ROOT_TAB) >= 0; });",
        "    var needsRoot = false;",
        lambda r: r["model"]["kinds"] != [["Polish", "base"], ["Epoxy", "base"]] or r["opened"]["rootKind"] != "base"),
    "the Epoxy tab is saved under another role": (
        "js/bid-model.js", "        id: x.e.tab, name: x.e.tab, role: x.e.role, kind: x.e.kind,",
        '        id: x.e.tab, name: x.e.tab, role: "other", kind: x.e.kind,',
        lambda r: [t[1] for t in r["saved"]["pricedTabs"]] != ["polish", "epoxy"]),
    "the review step has no whole bid card": (
        "js/polish-estimate.js", '    if (live.length < 2) return "";', '    if (true) return "";',
        lambda r: r["review"]["hasCard"] is not True),
    "the whole bid card is not repainted on a keystroke": (
        "js/polish-estimate.js", "    repaintJob();", "    void 0;",
        lambda r: r["review"]["afterContingency"]["job"] != r["review"]["afterContingency"]["handJob"]),
    "a saved Epoxy job switched to Combo keeps the Polish root off": (
        "js/bid-model.js", '    if (needsRoot && out.kind === "off") { out = Object.assign({}, out); delete out.kind; }',
        "    void 0;",
        lambda r: r["switched"]["epoxyToCombo"]["kinds"] != [["Polish", "base"], ["Epoxy", "base"]]),
    "a saved Combo job switched to Polish keeps Epoxy as a base": (
        "js/bid-model.js", 'isObject(s) && s.kind === "base";', 'isObject(s) && s.kind === "never";',
        lambda r: r["switched"]["comboToPolish"]["kinds"] != [["Polish", "base"], ["Epoxy", "off"]]),
    "a section added to a saved bid is not crewed": (
        "js/polish-estimate.js", "    var laborDefaults = (newBid || addsSection) ? loadLaborDefaults() : null;",
        "    var laborDefaults = newBid ? loadLaborDefaults() : null;",
        lambda r: r["switched"]["polishToCombo"]["epoxyLabor"] != ["epoxy-install"]),
    "a switched job type is never saved": (
        "js/polish-estimate.js", "    if (restructured) saveSoon();", "    void 0;",
        lambda r: r["switched"]["epoxyToCombo"]["saves"] != 1),
    "every section draws the travel block": (
        "js/polish-estimate.js", "    try { return B.travelCarrier(ROOT) === activeTab; } catch (err) { return true; }",
        "    return true;",
        lambda r: r["travel"]["epoxyLaborHasBlock"] is not False or r["travel"]["epoxyReviewNote"] is not True),
}


@pytest.mark.parametrize("name", sorted(PAGE_BREAKS))
def test_the_page_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = PAGE_BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(PAGE_HARNESS, frontend, plan_json(tmp_path))
    if proc.returncode != 0:
        return   # the break stopped the page outright: noticed
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name


PROOF_BREAKS = {
    "the job's travel is charged on every section": (
        "js/bid-model.js", "      travel: carrier ? travelCosts(model.travel, s.labor).total : 0,",
        "      travel: travelCosts(model.travel, s.labor).total,"),
    "the combined bid takes only the first section": (
        "js/bid-engine.js",
        "      sums = Object.assign({}, sums, Object.fromEntries([[key, tabs.reduce(function (t, x) { return t + num(x.result[key]); }, 0)]]));",
        "      sums = Object.assign({}, sums, Object.fromEntries([[key, tabs.slice(0, 1).reduce(function (t, x) { return t + num(x.result[key]); }, 0)]]));"),
    "the labor burden forgets the escalation": (
        "js/bid-engine.js", "    var burden = roundUp((labor + escalation) * burden_pct);",
        "    var burden = roundUp((labor) * burden_pct);"),
}


@pytest.mark.parametrize("name", sorted(PROOF_BREAKS))
def test_the_workbook_proof_goes_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new = PROOF_BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new, also=["js/bid-model.js", "js/bid-engine.js"])
    proc = run_node(PROOF_HARNESS, frontend)
    assert proc.returncode == 0, proc.stderr
    got = last_json_line(proc.stdout)
    assert got["wrongCount"] > 0, "the proof did not notice: " + name
