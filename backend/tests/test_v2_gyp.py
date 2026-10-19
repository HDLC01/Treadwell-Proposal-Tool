"""Phase 14: a Gyp job on the real estimate page, the v2 intake's gypsum box, and the model pieces under them.

WHAT CHANGED. Estimating Tool v2 prices Gyp (js/work-types.js `ready: true`). A v2 Gyp job is a Gyp SECTION of the bid
with the Polish root marked off, filed under the workbook tab of the PRESET the estimator chose (USG N12 1/8" is the
default; the other four are the four other Gyp sheets, Gyp (FR) among them). The estimate page's Material, Labor and
Review panels edit it, the Material panel carries a Gyp card (sheet, mix, a thickness for each area, sound mat, ISO
strip, moisture tests, mobilizations), and the page prices it through js/gyp-takeoff.js and the engine's gyp-split chain.
That the price equals Kyle's workbook is test_gyp_v2_proof.py; that the pieces are the template's is test_gyp_takeoff.py.

PROVEN BY EXECUTION. tests/js/gyp-page-harness.js boots js/polish-estimate.js whole (through polish-estimate-harness.js's
own boot code) on the library the seed script plans, and every fact below is read off what the page held, drew and saved.
The price it shows is set beside the same job priced by hand with no page in it. The model pieces run on the real
js/bid-model.js under node. Each mutation at the bottom breaks a scratch copy of the page or the model and the check
it belongs to goes red.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "gyp-page-harness.js"
MODEL = FRONTEND / "js" / "bid-model.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js"]
FIRST = 'Gyp (USG 1-8")'
FR = "Gyp (FR)"


def run(frontend=FRONTEND, tmp=None):
    proc = run_node(HARNESS, frontend, plan_json(tmp))
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return run(tmp=tmp_path_factory.mktemp("page"))


def _node(code: str, model=MODEL):
    """Run `code` under node. The tokens __MODEL__ (the model module's path), __FIRST__ and __FR__ (the two sheets) are
    replaced by JSON literals first."""
    import subprocess
    node = require_node()
    code = (code.replace("__MODEL__", json.dumps(str(model))).replace("__FIRST__", json.dumps(FIRST))
            .replace("__FR__", json.dumps(FR)).replace("__TYPES__", json.dumps(str(FRONTEND / "js" / "work-types.js"))))
    proc = subprocess.run([node, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ── a new Gyp job ────────────────────────────────────────────────────────────────────────────────
def test_a_new_gyp_job_opens_as_a_section_on_the_base_sheet_with_the_polish_root_off(ran):
    o = ran["opened"]
    assert o["tabs"] == [FIRST] and o["rootKind"] == "off" and o["kind"] == "base"
    assert len(o["strip"]["tabs"]) == 1, "the Sheets panel is drawn for one sheet too, with that sheet's row"
    assert o["savesOnOpen"] == 0, "opening a job writes nothing until somebody edits it"
    assert o["gypSettings"] == "none", "the sheet's own defaults are the preset's, so nothing is stated until somebody types"


def test_the_intakes_three_areas_seed_the_takeoff_as_the_librarys_area_rows(ran):
    o = ran["opened"]
    assert o["takeoff"] == [["Gypsum: soft surfaces", 9000, "SF", "soft"],
                            ["Gypsum: hard surfaces over the sound mat", 6000, "SF", "hard"],
                            ["Gypsum: corridors", 2000, "SF", "corridor"]]


def test_the_crew_is_five_lines_priced_by_the_hour_and_travel_with_nothing_typed_yet(ran):
    o = ran["opened"]
    assert o["laborIds"] == ["travel", "gyp-mat", "gyp-pour", "gyp-prep", "gyp-prepour", "gyp-unload"]
    assert o["laborUnits"] == ["hours"] * 6, "a Gyp crew is guys x hours x rate"
    assert o["laborGuys"] == [""] * 6, "a new bid opens with guys and hours empty; only the rate is the library's"
    assert o["laborRates"][1:] == [33.66] * 5, "the Gyp sheet's own labor rate"


def test_the_gyp_card_is_drawn_with_five_sheets_and_the_sheets_own_thicknesses_as_placeholders(ran):
    o = ran["opened"]
    assert o["card"] is True and o["cardSheets"] == 5 and o["placeholders"] == 3
    assert o["panelHasPolishCards"] is False, "dye, joint filler and remove existing are Polish's questions"
    assert o["hasPatch"] is False, "the patch is an Epoxy charge"


# ── pricing ──────────────────────────────────────────────────────────────────────────────────────
def test_the_price_on_the_page_is_the_price_by_hand_and_is_what_the_save_writes(ran):
    p = ran["priced"]
    assert p["barNumber"] == p["byHand"] == p["pageBid"] == p["lump"] == p["computed"] == p["stampTotal"] > 0
    assert p["pageMaterial"] == p["handMaterial"] > 0 and p["pageTooling"] == p["handTooling"] > 0
    assert p["pageShipping"] == p["shippingByHand"] and p["pageEscalation"] == p["escalationByHand"] > 0
    assert p["stampProfile"] == "gyp@1"


def test_a_save_writes_the_proposals_keys_for_a_gyp_base_and_no_polish(ran):
    p = ran["priced"]
    for key in ("priced_tabs", "proposal_lump_sum", "proposal_sales_tax", "proposal_remodel_tax", "sheet_area",
                "cost_snapshot", "computed_bid", "phase_price"):
        assert key in p["savedKeys"], key
    assert "polish_sf" not in p["savedKeys"], "a Gyp bid has no Polish area to write"
    # one priced tab, the Gyp one, marked v2, named by the sheet's own title, with its three areas
    assert p["pricedTabs"] == [[FIRST, "gyp", "base", True, p["lump"], 'N12 1/8" + 3/4" Gyp',
                                {"gyp_soft_sf": 9000, "gyp_hard_sf": 6000, "gyp_corridor_sf": 2000}]]
    assert p["sheetArea"] == {"gyp_soft_sf": 9000, "gyp_hard_sf": 6000, "gyp_corridor_sf": 2000}
    assert p["rootKind"] == "off" and p["savedTabs"] == [FIRST]


def test_the_labor_a_gyp_crew_is_typed_in_hours_and_reaches_the_price_and_the_save(ran):
    p = ran["priced"]
    assert [r for r in p["laborSaved"] if r[1] != ""] == [["gyp-pour", "8", "6", "hours"], ["gyp-prep", "8", "4", "hours"]]


def test_only_travel_is_dimmed_on_a_local_job_and_a_crew_line_is_not_drive_time(ran):
    """laborInert and the card's wording were written for the one hours row there was, Travel. A Gyp crew line is also
    priced by the hour and is none of those things."""
    assert ran["priced"]["inert"] == 1, "one card is dimmed on a local job, and it is Travel's"
    c = ran["laborCards"]
    assert c["pourHint"] is True and c["driveHint"] == 1 and c["hourCards"] == 6


def test_the_labor_step_quotes_the_hours_the_sheet_would_work_out(ran):
    cap = ran["priced"]["caption"]
    assert "Prep, prime and seal 0 hours (4 hours a mobilization)" in cap
    assert "Mat time 10.08 hours (the hard surfaces at 595 SF an hour)" in cap     # 6,000 SF / 595
    assert "Pour 5.74 hours (430.39 bags at 75 an hour)" in cap
    assert "The sheet's crews are 8, 8, 7, 8 and 2 guys." in cap
    assert "—" not in cap, "plain words: no em dashes"


def test_the_material_step_says_what_is_added_and_how_the_sound_mat_ships(ran):
    m = ran["material"]
    assert m["card"] is True
    for word in ("Primer 9.17 gallons", "ISO strip 2.78 rolls", "Joint tape 25 rolls", "Sand 42.61 tons", "Sound mat 13 rolls"):
        assert word in m["caption"], word
    assert "ships free from 280 rolls" in m["caption"] and "this job has 13" in m["caption"]
    assert "430.39 in all" in m["caption"], "bags are not rounded up"
    assert m["truck"] == "A truckload is 280 rolls; this job has 13."
    assert len(m["rowCosts"]) == 3 and "$11,067" in m["materialTotal"]


# ── the card's boxes ─────────────────────────────────────────────────────────────────────────────
def test_a_thickness_typed_in_an_area_reprices_live_is_kept_and_a_blank_goes_back_to_the_sheets(ran):
    t = ran["thickness"]
    assert t["after"] > t["before"] and t["after"] == t["byHand"], "thicker soft surface, more bags, the hand-priced figure"
    assert t["kept"] == {"thickness": {"soft": "1.5"}}
    assert t["backToBefore"] == t["before"] == t["bar"], "a blank box is the sheet's own thickness again"


def test_the_mix_the_sound_mat_iso_strip_and_moisture_tests_each_reprice_as_the_hand_priced_job_does(ran):
    s = ran["settings"]
    for name in ("mix", "mat", "iso"):
        page, hand, moved = s[name]
        assert page == hand and moved is True, name
    assert s["moisture"][0] == s["moisture"][1] and s["moisture"][2] == s["moisture"][3] == 855, "5 tests at $35 added to $680"
    assert s["after"] == ran["thickness"]["before"] and s["restored"] is True
    assert s["settings"]["mix"] == 1.8 and s["settings"]["sound_mat"] == "wb-gyp-sound-mat-sam-n12-1-8in-roll"


def test_choosing_another_sheet_moves_the_section_to_that_tab_and_keeps_every_row_and_hour(ran):
    p = ran["preset"]
    assert p["tabs"] == [FR] and p["stamp"] == "gyp@1"
    assert p["bid"] == p["byHand"] == p["bar"], "the page prices Gyp (FR) as the section filed under it"
    assert p["pricedTabs"] == [[FR, "gyp", "base", "Treadstone FR25 + R1 mat"]], "the proposal sees the sheet that was chosen"
    assert p["rowsKept"] == [[9000, "soft"], [6000, "hard"], [2000, "corridor"]]
    assert p["laborKept"] == [["gyp-pour", "8", "6"], ["gyp-prep", "8", "4"]]
    assert p["truckload"] == 448 and p["cardSelected"] == 1 and p["matOptions"] == 6, "Gyp (FR) offers its own six mats"
    b = p["back"]
    assert b["tabs"] == [FIRST] and b["priced"] == [FIRST] and b["restored"] is True, "and back again loses nothing"


def test_the_review_step_shows_the_gyp_lines_and_the_escalation_that_is_always_on(ran):
    r = ran["review"]
    assert r["hasLines"] == [True, True, True]
    assert r["escalationLabel"] is True and r["noPrevailingSwitch"] is True, "Gyp adds the 5% whatever prevailing wage says"
    assert r["materialEscalationRow"] is True and r["shippingNoRate"] is True, "20% and 10% are not one shipping rate"
    assert r["tooling"] is True and r["noDye"] is True and r["total"] == "$35,020"


def test_a_thickness_that_cannot_be_worked_out_is_no_price_in_plain_words_never_a_bid_on_the_part_that_could_be(ran):
    n = ran["noPrice"]
    assert n["priceable"] is False and n["line"] == "material" and n["bar"] == "no price"
    assert n["reason"] == "the hard surface area has no usable thickness"
    assert n["caption"] == "Cannot be priced yet: the hard surface area has no usable thickness."


# ── rows ─────────────────────────────────────────────────────────────────────────────────────────
def test_an_area_row_picked_from_the_pop_up_or_typed_by_name_carries_its_area(ran):
    p = ran["picked"]
    assert p["bucket"] == "corridor" and p["id"] == "wb-gyp-area-corridor" and p["unit"] == "SF"
    assert p["rows"] == ["soft", "corridor"]
    assert p["afterRename"] == "hard", "pointing the row at another area changes its mark with it"


def test_a_saved_gyp_bid_opens_as_saved_and_writes_nothing(ran):
    r = ran["reopened"]
    assert r["saves"] == 0 and r["armed"] == 0 and r["tabs"] == [FIRST] and r["takeoffRows"] == 3 and r["card"] is True
    assert r["total"] == ran["priced"]["lump"] or r["total"] > 0


def test_a_polish_job_is_untouched_and_a_gyp_area_in_a_polish_bid_is_priced_as_any_assembly(ran):
    assert ran["polish"] == {"tabs": "none", "card": False, "bid": ran["polish"]["bid"]} and ran["polish"]["bid"] > 0
    w = ran["polishWithArea"]
    assert w["areaFlag"] == "none" and w["lines"] == w["libLines"] and w["total"][0] == w["total"][1], (
        "there is no Gyp section to price the area against, so the library prices it")
    assert w["gypFlag"] is True, "in a Gyp section the same assembly is priced by the sheet's formula"


def test_a_gyp_job_with_no_area_typed_opens_with_the_one_blank_row_and_no_price(ran):
    e = ran["empty"]
    assert e["rows"] == [["", ""]] and e["bar"] in ("no price", "—", "")


# ── the document ─────────────────────────────────────────────────────────────────────────────────
def test_the_gyp_proposal_prints_the_v2_price_and_the_three_areas_from_the_v2_save(ran):
    """The proposal page rebuilds the price from priced_tabs (rebuildPricing) and the Gyp template prints the base as one
    line with its tax and total, and the three areas as sentences. Rendered through the real page code and the real
    renderer: the price on the paper is the price the estimate page saved, and the areas are the section's three."""
    import re
    import test_price_block_reconciles as R
    p = ran["priced"]
    run = R._drive(work_type="gyp", blocks=R._template_blocks("gyp", "Direct"), rebuild=True, total=0.0, sales_tax=0.0,
                   remodel_tax=0.0, state={"priced_tabs": p["pricedTabsFull"]})
    values = run["payload"]["values"]
    assert values["proposal_lump_sum"] == p["lump"] and values["proposal_sales_tax"] > 0 and values["proposal_remodel_tax"] == 0
    assert (values["gyp_soft_sf"], values["gyp_hard_sf"], values["gyp_corridor_sf"], values["sqft"]) == ("9,000", "6,000", "2,000", "17,000")
    printed = [ln.replace("�", "-") for ln in R._printed_from(run["payload"]) if ln.startswith("$") or "Based on" in ln]
    money = lambda n: "${:,}".format(n)
    assert any(ln.startswith(money(p["lump"] - values["proposal_sales_tax"])) and "Gypsum Underlayment System" in ln for ln in printed), printed
    assert any(ln.startswith(money(values["proposal_sales_tax"])) and "Material Sales Tax" in ln for ln in printed), printed
    assert any(ln.startswith(money(p["lump"])) and ln.endswith("Total") for ln in printed), printed
    assert [re.search(r"Based on ([\d,]+) sf", ln).group(1) for ln in printed if "Based on" in ln] == ["9,000", "6,000", "2,000"]


# ── the model ────────────────────────────────────────────────────────────────────────────────────
def test_sections_for_job_gives_a_gyp_job_its_section_and_counts_any_of_the_five_sheets_as_it():
    got = _node("""
      const B = require(__MODEL__);
      const fresh = B.freshModel();
      const gyp = B.sectionsForJob(fresh, "gyp", {});
      const again = B.sectionsForJob(gyp, "gyp", {});
      const fr = B.moveSectionSheet(gyp, __FIRST__, __FR__);
      const stillFr = B.sectionsForJob(fr, "gyp", {});
      const polish = B.sectionsForJob(gyp, "polish", {});
      const combo = B.sectionsForJob(gyp, "combo", {});
      const back = B.sectionsForJob(polish, "gyp", {});
      console.log(JSON.stringify({
        tabs: Object.keys(gyp.tabs), root: gyp.kind, kind: gyp.tabs[__FIRST__].kind, profile: gyp.tabs[__FIRST__].profile,
        role: B.sectionsOf(gyp).map((e) => e.role),
        idempotent: again === gyp, frKeepsItself: stillFr === fr, frTabs: Object.keys(stillFr.tabs),
        toAdd: [B.sectionsToAdd(fresh, "gyp"), B.sectionsToAdd(gyp, "gyp"), B.sectionsToAdd(fr, "gyp")],
        carrier: B.travelCarrier(gyp), callerUntouched: fresh.tabs === undefined && fresh.kind === undefined,
        toPolish: B.sectionsOf(polish).map((e) => [e.tab, e.kind]), toCombo: B.sectionsOf(combo).map((e) => [e.tab, e.kind]),
        backToGyp: B.sectionsOf(back).map((e) => [e.tab, e.kind]),
        leaving: [B.sectionsLeaving(gyp, "polish"), B.sectionsLeaving(gyp, "gyp"), B.sectionsLeaving(fr, "epoxy")],
      }));
    """)
    assert got["tabs"] == [FIRST] and got["root"] == "off" and got["kind"] == "base" and got["profile"] == "gyp@1"
    assert got["role"] == ["polish", "gyp"] and got["carrier"] == FIRST and got["callerUntouched"] is True
    assert got["idempotent"] is True
    # a bid already on Gyp (FR) has its Gyp section: asking again must not add a second one under the first sheet,
    # which would price the job twice
    assert got["frKeepsItself"] is True and got["frTabs"] == [FR]
    assert got["toAdd"] == [[FIRST], [], []]
    # a bid whose job type moved away has its Gyp base marked off and its rows kept; moving back turns it on
    assert got["toPolish"] == [["Polish", "base"], [FIRST, "off"]]
    assert got["toCombo"] == [["Polish", "base"], [FIRST, "off"], ["Epoxy", "base"]]
    assert got["backToGyp"] == [["Polish", "off"], [FIRST, "base"]]
    assert got["leaving"] == [[FIRST], [], [FR]]


def test_a_section_moves_to_another_sheet_of_its_tab_and_keeps_its_place_rows_and_settings():
    got = _node("""
      const B = require(__MODEL__);
      const thrown = (f) => { try { f(); return null; } catch (e) { return String(e.message); } };
      let m = B.sectionsForJob(B.freshModel(), "gyp", {});
      m = B.activateSection(m, "Seal", "option", {});
      m.tabs[__FIRST__].takeoff = [{ assembly_id: "x", measurement: 5, unit: "SF", bucket: "hard" }];
      m.tabs[__FIRST__].gyp = { mix: 1.4, sound_mat: "wb-gyp-sound-mat-sc-190-1-8in-roll" };
      m.tabs[__FIRST__].contingency = 250;
      const before = JSON.stringify(m);
      const fr = B.moveSectionSheet(m, __FIRST__, __FR__);
      const both = Object.assign({}, m, { tabs: Object.assign({}, m.tabs, { [__FR__]: JSON.parse(JSON.stringify(m.tabs[__FIRST__])) }) });
      console.log(JSON.stringify({
        order: Object.keys(fr.tabs), section: fr.tabs[__FR__], callerUntouched: JSON.stringify(m) === before,
        same: B.moveSectionSheet(m, __FIRST__, __FIRST__) === m,
        sectionsRead: B.sectionsOf(fr).map((e) => [e.tab, e.kind, e.profile, e.role]),
        toOtherTab: thrown(() => B.moveSectionSheet(m, __FIRST__, "Epoxy")), toNothing: thrown(() => B.moveSectionSheet(m, __FIRST__, "Nonsense")),
        root: thrown(() => B.moveSectionSheet(m, "Polish", __FR__)), missing: thrown(() => B.moveSectionSheet(m, __FR__, __FIRST__)),
        taken: thrown(() => B.moveSectionSheet(both, __FIRST__, __FR__)),
        label: [B.sheetLabel(__FIRST__), B.sheetLabel(__FR__), B.sheetLabel("Epoxy"), B.sheetLabel(undefined)],
      }));
    """)
    assert got["order"] == [FR, "Seal"], "the section keeps its place among the others"
    s = got["section"]
    assert s["profile"] == "gyp@1" and s["contingency"] == 250 and s["takeoff"][0]["bucket"] == "hard"
    assert s["gyp"] == {"mix": 1.4, "sound_mat": "wb-gyp-sound-mat-sc-190-1-8in-roll"}
    assert got["callerUntouched"] is True and got["same"] is True
    assert got["sectionsRead"] == [["Polish", "off", "polish-legacy@1", "polish"], [FR, "base", "gyp@1", "gyp"],
                                   ["Seal", "option", "seal@1", "seal"]]
    assert "not another sheet" in got["toOtherTab"] and "not another sheet" in got["toNothing"]
    assert "is the root of the model" in got["root"] and "no section" in got["missing"]
    assert got["taken"] is not None and "already a section" in got["taken"]
    assert got["label"] == ['N12 1/8" + 3/4" Gyp', "Treadstone FR25 + R1 mat", "Epoxy", "undefined"]


def test_priceSection_takes_the_truckload_from_the_material_and_a_material_that_says_no_is_no_price():
    got = _node("""
      const B = require(__MODEL__);
      const m = B.sectionsForJob(B.freshModel(), "gyp", {});
      const sec = m.tabs[__FIRST__];
      sec.takeoff = [{ assembly_id: "", measurement: 1000, unit: "SF" }];
      sec.labor = [{ id: "l", guys: 1, days: 1000, rate: 1, unit: "hours" }];
      const price = (mat) => B.priceSection(m, __FIRST__, { material: () => mat });
      const base = { gyp: 1000, extras: 100, sand: 100, soundMat: 10000 };
      const mk = (over) => price(Object.assign({}, base, over));
      console.log(JSON.stringify({
        tabsOwn: [mk({ soundMatRolls: 279 }).shipping, mk({ soundMatRolls: 280 }).shipping],
        matSays: [mk({ soundMatRolls: 279, truckload: 208 }).shipping, mk({ soundMatRolls: 208, truckload: 208 }).shipping,
                  mk({ soundMatRolls: 207, truckload: 208 }).shipping],
        zero: mk({ soundMatRolls: 100, truckload: 0 }).shipping,
        no: price({ gyp: 1, unpriceable: "the soft surface area has no usable thickness" }),
        emptyReason: price({ gyp: 1, unpriceable: "" }).priceable,
        tooling: [mk({ soundMatRolls: 1, tooling: 0 }).tooling, mk({ soundMatRolls: 1, tooling: 77 }).tooling],
      }));
    """)
    # shipping = 20% of the gypsum (200) + 10% of (extras 100 + the mat when short of a truckload): 200 + 10 + 1000 or 200 + 10
    assert got["tabsOwn"] == [1210, 210], "the first tab's own 280 rolls decides, with no truckload from the material"
    assert got["matSays"] == [210, 210, 1210], "the mat's own truckload (208) decides: 279 and 208 are not short of it, 207 is"
    assert got["zero"] == 1210, "a truckload of nothing is not a truckload: the tab's own 280 stands and 100 rolls are short of it"
    assert got["no"]["priceable"] is False and got["no"]["line"] == "material"
    assert got["no"]["reason"] == "the soft surface area has no usable thickness" and got["no"]["total"] is None
    assert got["emptyReason"] is True, "an empty reason is not a refusal"
    assert got["tooling"] == [0, 77], "the tooling the material carries reaches the chain"


def test_a_gyp_sections_area_line_is_its_three_areas_and_a_row_with_no_mark_is_soft():
    got = _node("""
      const B = require(__MODEL__);
      const rows = [
        { measurement: 100, unit: "SF", bucket: "soft" }, { measurement: 200, unit: "SF", bucket: "hard" },
        { measurement: 50, unit: "SF", bucket: "corridor" }, { measurement: 10, unit: "SF" },
        { measurement: 999, unit: "SF", bucket: "hard", enabled: false }, { measurement: 999, unit: "LF", bucket: "soft" },
        { measurement: 999, unit: "SF", bucket: "soft", same_floor: true }, { measurement: 7, unit: "SF", bucket: "nonsense" },
        null, {}, { measurement: "12", unit: "SF", bucket: "hard" },
      ];
      console.log(JSON.stringify({ areas: B.gypAreaFields(rows), none: B.gypAreaFields([]), junk: B.gypAreaFields(null) }));
    """)
    assert got["areas"] == {"gyp_soft_sf": 117, "gyp_hard_sf": 212, "gyp_corridor_sf": 50}
    assert got["none"] == got["junk"] == {"gyp_soft_sf": 0, "gyp_hard_sf": 0, "gyp_corridor_sf": 0}


def test_a_sections_own_starting_takeoff_comes_from_the_page_and_an_empty_answer_leaves_the_blank_row():
    got = _node("""
      const B = require(__MODEL__);
      const base = B.sectionsForJob(B.freshModel(), "gyp", {});
      const ctx = (hook, sf) => ({ saved: {}, laborRows: null, laborRate: 33, travelRates: null, feesDefault: null, conditionRows: null,
        cellValues: {}, split: false, asms: [], items: [], reserved: [], sf: sf, lf: {}, calcRows: null, takeoffRows: hook });
      const seen = [];
      const rows = [{ assembly_id: "wb-gyp-area-soft", measurement: 5, unit: "SF", bucket: "soft" }];
      const seeded = B.seedNewSections(base, ctx((e, sfs) => { seen.push([e.tab, e.role, sfs]); return rows; }, { [__FIRST__]: [5, 6, 7] }));
      const emptyAnswer = B.seedNewSections(base, ctx(() => [], { [__FIRST__]: [5, 6, 7] }));
      const nullAnswer = B.seedNewSections(base, ctx(() => null, { [__FIRST__]: [5, 6] }));
      const noHook = B.seedNewSections(base, ctx(undefined, { [__FIRST__]: [5, 6] }));
      console.log(JSON.stringify({ seen: seen, seeded: seeded.tabs[__FIRST__].takeoff, empty: emptyAnswer.tabs[__FIRST__].takeoff,
        same: JSON.stringify(nullAnswer.tabs[__FIRST__].takeoff) === JSON.stringify(noHook.tabs[__FIRST__].takeoff),
        callerUntouched: base.tabs[__FIRST__].takeoff.length }));
    """)
    assert got["seen"] == [[FIRST, "gyp", [5, 6, 7]]], "the hook is handed the section's entry and every figure the intake typed for it"
    assert got["seeded"] == [{"assembly_id": "wb-gyp-area-soft", "measurement": 5, "unit": "SF", "bucket": "soft"}]
    assert got["empty"] == [{"assembly_id": "", "assembly_name": "", "measurement": "", "unit": "SF"}]
    assert got["same"] is True and got["callerUntouched"] == 1


def test_a_job_type_that_is_not_ready_is_refused_by_the_model(tmp_path):
    """Gyp was the last job type to be ready (Phase 14), so the refusal is proved on a scratch vocabulary with Gyp marked
    not ready: pricing it would be a guess."""
    require_node()
    old = 'tabs: ["gyp"], ready: true,'
    frontend = break_source(tmp_path, "js/work-types.js", old, 'tabs: ["gyp"], ready: false,', also=["js/bid-model.js"])
    got = _node("""
      const B = require(__MODEL__);
      const thrown = (f) => { try { f(); return null; } catch (e) { return String(e.message); } };
      const fresh = B.freshModel();
      console.log(JSON.stringify({ gyp: thrown(() => B.sectionsForJob(fresh, "gyp", {})), add: B.sectionsToAdd(fresh, "gyp"),
        polish: B.sectionsForJob(fresh, "polish", {}) === fresh }));
    """, model=frontend / "js" / "bid-model.js")
    assert "not ready" in got["gyp"] and got["add"] == [] and got["polish"] is True


# ── the intake, the cells ────────────────────────────────────────────────────────────────────────
def test_the_v2_intake_shows_the_three_gypsum_boxes_for_a_gyp_job_only():
    require_node()
    proc = run_node(TESTS / "js" / "polish-intake-harness.js", FRONTEND)
    assert proc.returncode == 0, proc.stderr
    boxes = last_json_line(proc.stdout)["jobTypes"]["savedDrafts"]["gypBoxes"]
    assert boxes == {"gypJob": {"gyp": "", "systems": "none"}, "polishJob": {"gyp": "none", "systems": ""}}


def test_the_local_job_condition_writes_the_gyp_sheets_own_local_cells_so_a_far_gyp_job_is_not_priced_as_local():
    got = _node("""
      const T = require(__TYPES__);
      console.log(JSON.stringify({ local: T.condition("local").cells, gypLocal: T.writeCellsFor("local", "gyp", false),
        polishLocal: T.writeCellsFor("local", "polish", false) }));
    """)
    assert got["local"] == ["Epoxy!B4", "Polish!B4", 'Gyp (USG 1-8")!B5', "Gyp (FR)!B5", "Seal!B4"]
    assert 'Gyp (USG 1-8")!B5' in got["gypLocal"] and "Gyp (FR)!B5" in got["gypLocal"]


# ── red without the code ─────────────────────────────────────────────────────────────────────────
MUTATIONS = {
    "a Gyp area row is priced as a library assembly": (
        "js/polish-estimate.js", "    if (G && G.bucketOfAssembly(asm.id)) {", "    if (false) {",
        lambda r: r["polishWithArea"].get("gypFlag") is not True),
    "the page hands a Gyp section a plain sum": (
        "js/polish-estimate.js", '    if (entry.role === "gyp" && G) {', "    if (false) {",
        lambda r: r["priced"]["pageBid"] != r["priced"]["byHand"] or r["noPrice"]["priceable"] is not False),
    "a thickness typed in the card is ignored": (
        "js/polish-estimate.js", "      next = { thickness: Object.assign({}, held.thickness, Object.fromEntries([[area, value]])) };",
        "      next = {};",
        lambda r: r["thickness"]["after"] != r["thickness"]["byHand"]),
    "the sheet box does not move the section": (
        "js/polish-estimate.js", "      ROOT = B.moveSectionSheet(ROOT, e.tab, value);", "      void 0;",
        lambda r: r["preset"]["tabs"] != [FR]),
    "a Gyp crew line is dimmed like Travel": (
        "js/polish-estimate.js", '    return !!(r && r.unit === "hours") && (r.id === "travel" || !gypOpen());',
        '    return !!(r && r.unit === "hours");',
        lambda r: r["priced"]["inert"] != 1 or r["laborCards"]["driveHint"] != 1),
    "the escalation switch is drawn on a Gyp bid": (
        "js/polish-estimate.js", '    labRows.push([gypRev ? "Labor escalation (always on for Gyp)" : { raw: condSwitch("prevailing_wage", "Labor escalation") },',
        '    labRows.push([{ raw: condSwitch("prevailing_wage", "Labor escalation") },',
        lambda r: r["review"]["escalationLabel"] is not True),
    "an area row carries no mark": (
        "js/polish-estimate.js", "    if (area) row.bucket = area; else delete row.bucket;", "    void 0;",
        lambda r: r["picked"].get("bucket") != "corridor"),
    "the intake's three areas do not seed the takeoff": (
        "js/polish-estimate.js", "        return entry.role === \"gyp\" && G ? G.seedTakeoff(ASMS, sfs[0], sfs[1], sfs[2]) : null;",
        "        return null;",
        lambda r: r["opened"]["takeoff"] != [["Gypsum: soft surfaces", 9000, "SF", "soft"],
                                             ["Gypsum: hard surfaces over the sound mat", 6000, "SF", "hard"],
                                             ["Gypsum: corridors", 2000, "SF", "corridor"]]),
    "the area line is the soft area alone": (
        "js/bid-model.js", '    if (e.role === "gyp") return gypAreaFields(rows);',
        '    if (e.role === "gyp") return { gyp_soft_sf: takeoffSf(rows) };',
        lambda r: r["priced"]["sheetArea"] != {"gyp_soft_sf": 9000, "gyp_hard_sf": 6000, "gyp_corridor_sf": 2000}),
    "the proposal names a Gyp system by its first row": (
        "js/bid-model.js", '    if (entry && (entry.role === "gyp" || entry.role === "seal")) {', "    if (false) {",
        lambda r: r["priced"]["pricedTabs"][0][5] != 'N12 1/8" + 3/4" Gyp'),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    broken = run(frontend=frontend, tmp=tmp_path)
    assert noticed(broken), "the checks did not notice: " + name
