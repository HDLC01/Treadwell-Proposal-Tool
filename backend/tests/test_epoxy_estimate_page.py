"""Phase 12: an Epoxy job on the real estimate page, and the model pieces under it.

WHAT CHANGED. Estimating Tool v2's intake offers Epoxy (js/work-types.js `ready: true`). A v2 Epoxy job is an Epoxy
SECTION of the bid with the Polish root marked off (B.sectionsForJob), and the estimate page's Material, Labor and Review
panels edit whichever section is on show (B.sectionView: the section's takeoff, labor, contingency and fees, and the
model's own everything else). The page prices the section through the engine (js/epoxy-takeoff.js for what the sheet does
before its chain) and saves the proposal's keys through B.composePricingSnapshot.

PROVEN BY EXECUTION. tests/js/epoxy-page-harness.js boots js/polish-estimate.js whole (through polish-estimate-harness.js's
own boot code) on the library the seed script plans, and every fact below is read off what the page held, drew and saved.
The price it shows is set beside the same job priced by hand with no page in it. The model pieces run on the real
js/bid-model.js under node.

Each mutation at the bottom breaks a scratch copy of the page or the model and the check it belongs to goes red.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "epoxy-page-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js"]


def run(frontend=FRONTEND, tmp=None):
    proc = run_node(HARNESS, frontend, plan_json(tmp))
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return run(tmp=tmp_path_factory.mktemp("page"))


# ── a new Epoxy job ──────────────────────────────────────────────────────────
def test_a_new_epoxy_job_opens_as_an_epoxy_section_with_the_polish_root_off(ran):
    o = ran["opened"]
    assert o["tabs"] == ["Epoxy"] and o["rootKind"] == "off"
    assert o["strip"]["hidden"] is True, "the bid is one section, so there is no strip to switch with"
    assert o["savesOnOpen"] == 0, "opening a job writes nothing until somebody edits it"


def test_the_intakes_quantities_seed_the_takeoff_and_the_library_seeds_the_crew(ran):
    o = ran["opened"]
    assert [(r["measurement"], r["unit"], r["assembly_id"]) for r in o["takeoff"]] == [(6000, "SF", ""), (300, "LF", "")]
    assert o["laborIdsAll"] == ["travel", "epoxy-install"], "Travel stays built in, and the Epoxy crew line is the library's"
    assert o["laborGuys"] == ["", ""], "a new bid opens with the crew's guys empty; only the rate is the library's"
    assert o["travelRowOnSection"] is True


def test_the_epoxy_section_is_drawn_without_polishs_questions_and_with_the_patch(ran):
    o = ran["opened"]
    assert o["panelHasPatch"] is True
    assert o["panelHasPolishCards"] is False, "dye, joint filler and remove existing are Polish's questions"


# ── pricing ──────────────────────────────────────────────────────────────────
def test_the_price_on_the_page_is_the_price_by_hand_and_is_what_the_save_writes(ran):
    p = ran["priced"]
    assert p["barNumber"] == p["byHand"] == p["pageBid"] == p["lump"] == p["computed"] == p["epoxyTotals"]
    assert p["pageMaterial"] == p["handMaterial"] > 0 and p["pageTooling"] == p["handTooling"] > 0, (
        "the material includes the cove and the patch, and the tooling reaches the chain")
    assert p["stamp"] == "epoxy@1"


def test_a_save_writes_the_proposals_keys_for_an_epoxy_base_and_no_polish(ran):
    p = ran["priced"]
    for key in ("priced_tabs", "proposal_lump_sum", "proposal_sales_tax", "proposal_remodel_tax", "sheet_area",
                "cost_snapshot", "computed_bid", "phase_price"):
        assert key in p["savedKeys"], key
    assert p["pricedTabs"] == [["Epoxy", "epoxy", "base", True, p["lump"], {"epoxy_sf": 6000, "cove_lf": 300}]]
    assert p["sheetArea"] == {"epoxy_sf": 6000, "cove_lf": 300}
    assert p["polishSf"] == "absent", "an Epoxy bid has no Polish square feet to write"
    assert p["rootKind"] == "off" and p["savedTabs"] == ["Epoxy"] and p["rootHasNoTotals"] is True


def test_the_review_step_is_the_epoxy_sections_own(ran):
    r = ran["review"]
    assert r["hasTooling"] is True and r["toolingAmount"] == "$2,190", "the moisture test and tooling are on the review"
    assert (r["superPct"], r["softPct"]) == ("3%", "13%"), "Epoxy's super and PTO and soft costs, not Polish's 2.7% and 16%"
    assert r["shipPct"] == "9%", "Epoxy's shipping tier for $11,991 of material"
    assert r["noDye"] is True and r["total"] == "$29,547"


def test_the_labor_step_edits_the_epoxy_crew_and_the_price_follows(ran):
    lab = ran["labor"]
    assert [r[0] for r in lab["rows"]] == ["travel", "epoxy-install"]
    assert lab["after"] > lab["before"] and lab["after"] == lab["byHandAfter"]
    assert lab["savedDays"] == "9" and lab["rootLaborUntouched"] == 4, "the day went to the Epoxy section, not the root"


def test_a_row_added_beside_a_measured_one_shares_the_floor_in_a_section_other_than_the_root(ran):
    s = ran["sameFloor"]
    assert s["added"] == {"sameFloor": True, "measurement": 6000, "unit": "SF"}
    assert s["area"] == s["carrier"] == 6000, "the primer is the same floor and is not added to the area again"


def test_a_cove_row_on_the_page_is_priced_by_the_sheets_formula_and_follows_system_one(ran):
    c = ran["cove"]
    assert c["row"] == pytest.approx(c["direct"]) and c["row"] > c["silica"] > 0, (
        "System 1 is a quartz system, so the cove aggregate is priced as quartz")


def test_editing_a_section_beside_the_polish_root_never_writes_over_the_roots_rows(ran):
    b = ran["both"]
    assert b["stripTabs"] == ['data-section-tab="Polish"', 'data-section-tab="Epoxy"']
    assert b["epoxyMeasurement"] == "5500", "the number typed on the Epoxy tab is the Epoxy section's"
    assert b["rootTakeoff"] == b["rootBefore"] and len(b["rootTakeoff"]) == 3, "the root's own takeoff is as it was"
    assert "polishing" in b["rootLaborIds"] and b["epoxyLaborIds"] == ["epoxy-install"]


def test_the_add_pop_up_offers_the_work_types_own_rows_first_in_an_epoxy_section_and_leaves_the_roots_order_alone(ran):
    p = ran["picker"]
    assert p["epoxyLastTagged"] < p["epoxyFirstUntagged"], "the rows filed for no work type come after every epoxy row"
    assert p["epoxyLastTagged"] == p["epoxyRows"] - 1, "every epoxy row is above every other row, and the epoxy rows are all there"
    assert p["polishAaaBeforeMacro"] is True and p["epoxyAaaBeforeMacro"] is False, (
        "the root lists in plain name order, where AAA comes before MACRO; the Epoxy section puts MACRO above it")


# ── what must not move ───────────────────────────────────────────────────────
def test_a_saved_epoxy_bid_opens_as_saved_and_writes_nothing(ran):
    r = ran["reopened"]
    assert r["saves"] == 0 and r["armed"] == 0 and r["tabs"] == ["Epoxy"] and r["takeoffRows"] == 2
    assert r["total"] == ran["labor"]["after"]


def test_a_polish_job_is_untouched_and_a_gyp_job_is_given_its_own_section(ran):
    assert ran["polish"] == {"tabs": "none", "kind": "base", "strip": True, "bid": ran["polish"]["bid"], "activeBid": ran["polish"]["bid"]}
    assert ran["polish"]["bid"] > 0
    # Gyp is ready since Phase 14: its job opens on a Gyp section filed under the base sheet (test_v2_gyp.py holds the rest)
    assert ran["gyp"] == {"tabs": ['Gyp (USG 1-8")']}


def test_the_strip_lists_what_the_bid_is_made_of_and_never_the_polish_root_of_an_epoxy_job(ran):
    s = ran["strip"]
    assert s["hidden"] is False
    assert s["tabs"] == ['data-section-tab="Epoxy"', 'data-section-tab="Seal"']
    assert s["sealPanelIsTakeoff"] is True and s["epoxyPanelIsTakeoff"] is True, "both are edited on the page's own panels (Seal since Phase 15)"


# ── the model pieces, run on the real model ─────────────────────────────────────────────────────
MODEL = FRONTEND / "js" / "bid-model.js"


def _node(code: str):
    import subprocess
    proc = subprocess.run([require_node(), "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_section_view_answers_the_sections_keys_from_the_section_and_the_rest_from_the_model():
    got = _node("""
      const B = require(%s);
      const m = B.activateSection(Object.assign({}, B.freshModel(), { kind: "off" }), "Epoxy", "base", {});
      const v = B.sectionView(m, "Epoxy");
      v.takeoff = [{ assembly_id: "a", measurement: 5, unit: "SF" }];
      v.fees = 12; v.contingency = 7; v.labor = [{ id: "x" }];
      v.travel = { marker: true }; v.custom = "kept";
      const thrown = (f) => { try { f(); return null; } catch (e) { return String(e.message); } };
      console.log(JSON.stringify({
        section: m.tabs.Epoxy.takeoff.length + ":" + m.tabs.Epoxy.fees + ":" + m.tabs.Epoxy.contingency + ":" + m.tabs.Epoxy.labor[0].id,
        rootKeysUntouched: m.fees === 0 || m.fees === undefined ? "root fees untouched" : m.fees,
        rootTakeoffIsNotTheSections: m.takeoff.length !== 1 || m.takeoff[0].assembly_id !== "a",
        jobKeysGoToTheModel: m.travel.marker === true && m.custom === "kept",
        readsThrough: v.conditions === m.conditions && v.version === m.version,
        rootViewIsTheModel: B.sectionView(m, "Polish") === m,
        unknown: thrown(() => B.sectionView(m, "Gyp (FR)")),
      }));
    """ % json.dumps(str(MODEL)))
    assert got["section"] == "1:12:7:x"
    assert got["rootKeysUntouched"] == "root fees untouched" and got["rootTakeoffIsNotTheSections"] is True
    assert got["jobKeysGoToTheModel"] is True and got["readsThrough"] is True and got["rootViewIsTheModel"] is True
    assert "no section" in got["unknown"]


def test_the_sections_a_job_type_needs():
    got = _node("""
      const B = require(%s);
      const thrown = (f) => { try { f(); return null; } catch (e) { return String(e.message); } };
      const fresh = B.freshModel();
      const epoxy = B.sectionsForJob(fresh, "epoxy", {});
      const again = B.sectionsForJob(epoxy, "epoxy", {});
      const polish = B.sectionsForJob(fresh, "polish", {});
      console.log(JSON.stringify({
        epoxyTabs: Object.keys(epoxy.tabs), epoxyRoot: epoxy.kind, epoxyKind: epoxy.tabs.Epoxy.kind, stamp: epoxy.tabs.Epoxy.profile,
        callersModelUntouched: fresh.tabs === undefined && fresh.kind === undefined,
        idempotent: again === epoxy, polishIsTheSameObject: polish === fresh,
        sections: B.sectionsOf(epoxy).map((e) => [e.tab, e.kind]), active: B.activeSections(epoxy).map((e) => e.tab),
        carrier: B.travelCarrier(epoxy),
        combo: thrown(() => B.sectionsForJob(fresh, "combo", {})), gyp: thrown(() => B.sectionsForJob(fresh, "gyp", {})),
        seal: thrown(() => B.sectionsForJob(fresh, "seal", {})), none: thrown(() => B.sectionsForJob(fresh, "", {})),
        keepsTheSection: B.sectionsForJob(Object.assign({}, epoxy, { tabs: Object.assign({}, epoxy.tabs, { Epoxy: Object.assign({}, epoxy.tabs.Epoxy, { fees: 99 }) }) }), "epoxy", {}).tabs.Epoxy.fees,
      }));
    """ % json.dumps(str(MODEL)))
    assert got["epoxyTabs"] == ["Epoxy"] and got["epoxyRoot"] == "off" and got["epoxyKind"] == "base" and got["stamp"] == "epoxy@1"
    assert got["callersModelUntouched"] is True and got["idempotent"] is True and got["polishIsTheSameObject"] is True
    assert got["sections"] == [["Polish", "off"], ["Epoxy", "base"]] and got["active"] == ["Epoxy"] and got["carrier"] == "Epoxy"
    assert got["combo"] is None, "Combo is ready since Phase 13 (test_v2_combo.py holds what it builds)"
    assert got["gyp"] is None, "Gyp is ready since Phase 14 (test_v2_gyp.py holds what it builds and the refusal of a type that is not)"
    assert "not a job type" in got["seal"] and "not a job type" in got["none"]
    assert got["keepsTheSection"] == 99, "a section that is already there is never replaced"


def test_the_intakes_cove_lengths_seed_length_rows_once_and_never_over_a_measured_row():
    got = _node("""
      const B = require(%s);
      const base = B.sectionsForJob(B.freshModel(), "epoxy", {});
      const ctx = (lf) => ({ saved: {}, laborRows: null, laborRate: 33, travelRates: null, feesDefault: null, conditionRows: null,
        cellValues: {}, split: false, asms: [], items: [], reserved: [], sf: { Epoxy: [6000, 2500] }, lf: lf, calcRows: null });
      const seeded = B.seedNewSections(base, ctx({ Epoxy: [300, 120] }));
      const measuredLf = JSON.parse(JSON.stringify(base));
      measuredLf.tabs.Epoxy.takeoff = [{ assembly_id: "x", measurement: 40, unit: "LF" }];
      const keep = B.seedNewSections(measuredLf, ctx({ Epoxy: [300] }));
      const none = B.seedNewSections(base, ctx({}));
      console.log(JSON.stringify({
        rows: seeded.tabs.Epoxy.takeoff.map((r) => [r.measurement, r.unit]),
        measured: keep.tabs.Epoxy.takeoff.map((r) => [r.assembly_id, r.measurement, r.unit]),
        noLf: none.tabs.Epoxy.takeoff.map((r) => [r.measurement, r.unit]),
        caller: base.tabs.Epoxy.takeoff.length,
      }));
    """ % json.dumps(str(MODEL)))
    assert got["rows"] == [[6000, "SF"], [2500, "SF"], [300, "LF"], [120, "LF"]]
    assert got["noLf"] == [[6000, "SF"], [2500, "SF"]]
    assert got["caller"] == 1, "seeding never edits the model it was handed"


def test_the_strip_can_leave_out_a_section_that_is_not_part_of_the_bid():
    got = _node("""
      const B = require(%s);
      const m = B.sectionsForJob(B.freshModel(), "epoxy", {});
      const bids = { Polish: { total: 1 }, Epoxy: { total: 5000, priceable: true } };
      console.log(JSON.stringify({
        all: (B.sectionSwitcherHtml(m, "Epoxy", bids).match(/data-section-tab="([^"]*)"/g) || []).length,
        live: B.sectionSwitcherHtml(m, "Epoxy", bids, { skipOff: true }),
      }));
    """ % json.dumps(str(MODEL)))
    assert got["all"] == 2, "without the option the strip lists every section, as it always did"
    assert got["live"] == "", "one live section needs no strip"


# ── red without the code ─────────────────────────────────────────────────────
BREAKS = {
    "the page never adds the Epoxy section": (
        "js/polish-estimate.js", "      if (jobSections) ROOT = B.sectionsForJob(ROOT, jobType, { rules: await loadMarkupRules() });",
        "      void jobSections;",
        lambda r: r["opened"]["tabs"] != ["Epoxy"] or "error" in r),
    "a cove row is priced like a library assembly": (
        "js/polish-estimate.js", "    if (E.coveVariant(asm.id)) {", "    if (false) {",
        lambda r: abs(r["cove"]["row"] - r["cove"]["direct"]) > 1),
    "the strip lists the off root": (
        "js/polish-estimate.js", "    el.innerHTML = B.sectionSwitcherHtml(ROOT, activeTab, allBids(), { skipOff: true });",
        "    el.innerHTML = B.sectionSwitcherHtml(ROOT, activeTab, allBids());",
        lambda r: "Polish" in "".join(r["strip"]["tabs"])),
    "the work type's own rows are not offered first": (
        "js/polish-estimate.js", "      if (layout !== null && (row.default_work_types || []).indexOf(layout) >= 0) entry.first = true;",
        "      void layout;", lambda r: not r["picker"]["epoxyLastTagged"] < r["picker"]["epoxyFirstUntagged"]),
    "a row added beside a measured one is a second floor": (
        "js/polish-estimate.js", "      if (carrier) { row.measurement = carrier.measurement; row.same_floor = true; }",
        "      void carrier;", lambda r: r["sameFloor"]["added"]["sameFloor"] is not True),
    "the review prints the root's chain": (
        "js/polish-estimate.js", "    var b = activeBid();\n    var blk = B.blockers(M);", "    var b = bid();\n    var blk = B.blockers(M);",
        lambda r: r["review"]["total"] != "$29,547" or r["review"]["superPct"] != "3%"),
    "the bar prices the root, not the section": (
        "js/polish-estimate.js", "    if (activeTab === B.ROOT_TAB) return bid();\n    var all = sectionBids();",
        "    return bid();\n    var all = sectionBids();",
        lambda r: r["labor"]["after"] != r["labor"]["byHandAfter"] or r["priced"]["pageBid"] != r["priced"]["byHand"]),
    "the page saves from the view, not the model": (
        "js/polish-estimate.js", "      return B.buildSavePatch(ROOT, now, priceCtx());", "      return B.buildSavePatch(M, now, priceCtx());",
        lambda r: r["both"]["rootTakeoff"] != r["both"]["rootBefore"] or r["priced"]["rootKind"] != "off" or "error" in r),
    "the labor step edits the root": (
        "js/bid-model.js", "      get: function (target, key) { return Reflect.get(ownerOf(target, key), key); },",
        "      get: function (target, key) { return Reflect.get(target, key); },",
        lambda r: r["labor"]["after"] == r["labor"]["before"] or "error" in r),
    "the sections of an epoxy job leave the root on": (
        "js/bid-model.js", '      out = e.root ? Object.assign({}, out, { kind: "off" }) : withSectionKind(out, e.tab, "off");',
        "      out = e.root ? out : withSectionKind(out, e.tab, \"off\");",
        lambda r: r["opened"]["rootKind"] != "off" or r["priced"]["lump"] != r["priced"]["byHand"] or r["priced"]["pricedTabs"][0][0] != "Epoxy"),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_page_or_the_model_changes(tmp_path, name):
    rel, old, new, noticed = BREAKS[name]
    if "\n" in old:
        # break_source anchors one line: use the first line, as the second only disambiguates by eye
        first, second = old.split("\n")
        new_first, new_second = new.split("\n")
        src = (FRONTEND / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")
        assert src.count(old) == 1, name
        target = tmp_path / "frontend" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.replace(old, new).encode("utf-8"))
        frontend = tmp_path / "frontend"
        copy_unmodified(frontend, [rel])
    else:
        frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend, plan_json(tmp_path))
    if proc.returncode != 0:
        return                                               # a crash is the loudest way to go red
    assert noticed(last_json_line(proc.stdout)), "the checks did not notice: " + name
