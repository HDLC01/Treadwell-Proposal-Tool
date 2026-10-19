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
    assert o["strip"]["tabs"] == ['data-section-tab="Epoxy"'], "the Sheets panel is drawn for one sheet too, and lists only Epoxy"
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


def test_the_distance_fills_the_epoxy_sections_travel_labor_on_its_own_crew(ran):
    """THE DISTANCE FILLS TRAVEL LABOR since 2026-10-20, KYLE'S WAY: the hours from the miles, the guys the crew's size, so each guy is
    charged one round trip (Hanz; a scan of Kyle's Dropbox shows he types the crew size on 9 of 10 out-of-town sheets). An Epoxy job's Polish
    root is off and the Epoxy section carries the job's travel, so the row the answer fills is Epoxy's own, with Epoxy's own crew:
    190 miles is 6.5 hours (a 380 mile round trip at 60 mph), and 4 guys for 12 days is a crew of 4 (48 man-days, which are not the guys), so
    the line is 4 x 6.5 x $33 = $858. The root's own Travel row, which goes with the off root, is not the job's and is left alone.

    Mutation: fill the model's own labor and not the carrier section's (BREAKS below)."""
    t = ran["travelFill"]
    b = t["before"]
    assert b["carries"] is True, "the Epoxy section carries the job's travel, so its Labor step draws the distance"
    assert (b["row"]["days"], b["row"]["hours_seed"], b["row"]["guys_auto"], b["row"]["guys_follow"]) == (6.5, 6.5, True, "crew")
    assert (b["hoursBox"], b["guysBox"]) == ("6.5", "0"), "the answer is in and no crew is typed yet"
    a = t["after"]
    assert (a["row"]["guys"], a["guysBox"], a["manDays"], a["cost"]) == (4, "4", 48, 4 * 6.5 * 33)
    assert a["note"]["hidden"] is False
    assert a["note"]["text"] == ("6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor "
                                 "lines above. Type more trips for a long job.")
    assert t["tabs"] == ["Epoxy"] and t["rootKind"] == "off" and t["distance"]["miles"] == 190
    s = t["savedEpoxyTravel"]
    assert (s["days"], s["hours_seed"], s["guys"], s["guys_auto"], s["guys_follow"]) == (6.5, 6.5, 4, True, "crew"), "the save keeps the figures on the Epoxy section"
    # The control (the same job and crew with no distance answer at all) leaves the Epoxy row empty, so the fill above is the answer's;
    # and the off root's Travel row is the same with the answer as without it.
    assert t["controlEpoxyTravel"]["days"] == "" and "hours_seed" not in t["controlEpoxyTravel"]
    assert t["rootTravelUntouched"] is True, t["rootTravel"]


def test_a_job_type_switched_in_the_session_fills_the_new_carriers_travel_labor_from_the_distance_on_file(ran):
    """The 2026-10-20 audit: a Polish bid saved at 190 miles and switched to Epoxy on the intake step opens with the Epoxy section
    carrying the job's travel, and its Travel Labor row is NEW. It read blank while the distance said 190 and Lodging and Per Diem were
    on. The switch is the estimator's own action, so the distance on file fills the new carrier's row by the same rule an answer does:
    6.5 hours, the guys on Epoxy's crew (none typed yet: 0, then the 4 typed, so 4 x 6.5 x $33 = $858), the note under the card, and the
    bid saved once. The root's own row, which goes off with the root, is untouched. A bid whose Travel Labor was left blank is filled the
    same way on a switch, a root row switched off does not stop the new carrier being filled, and the sections after it are as before.

    Mutation: leave B.followDistance out of the page's init (BREAKS below)."""
    j = ran["jobSwitch"]
    s = j["switched"]
    b = s["before"]
    assert (b["carrier"], b["rootKind"], b["tabs"], b["distance"]) == ("Epoxy", "off", ["Epoxy"], 190)
    for key in ("days", "hours_seed", "guys_auto", "guys_follow", "guys"):
        assert b["row"][key] == {"days": 6.5, "hours_seed": 6.5, "guys_auto": True, "guys_follow": "crew", "guys": 0}[key], key
    assert b["rootRow"]["guys"] == 4 and b["rootRow"]["days"] == 6.5, "the off root keeps the row it was saved with"
    assert b["asked"] == 0, "nothing was looked up: the distance on file is what filled it"
    assert s["boxes"]["hours"] == "6.5" and s["boxes"]["guys"] == "0"
    assert s["boxes"]["note"] == ("6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each guy on the labor lines "
                                  "above. It prices once those lines have guys. Type more trips for a long job.")
    assert (s["after"]["row"]["guys"], s["after"]["guysBox"], s["after"]["cost"]) == (4, "4", 4 * 6.5 * 33)
    assert (s["saved"]["days"], s["saved"]["hours_seed"], s["saved"]["guys"], s["saved"]["guys_follow"]) == (6.5, 6.5, 4, "crew")
    assert s["savedKind"] == "off" and s["savedTabs"] == ["Epoxy"] and s["savedDistance"] == 190
    bs = j["blankSwitch"]
    assert (bs["carrier"], bs["row"]["days"], bs["row"]["guys_follow"]) == ("Epoxy", 6.5, "crew")
    assert (bs["rootRow"]["days"], bs["rootRow"]["guys"], bs["rootRow"]["guys_auto"]) == ("", "", False), "the off root's blank row is not the job's"
    orr = j["offRoot"]
    assert (orr["row"]["days"], orr["row"]["guys_follow"]) == (6.5, "crew") and orr["rootRow"]["enabled"] is False and orr["rootRow"]["guys"] == 4


def test_the_saved_crew_size_row_reopens_as_saved_and_keeps_following_the_sections_crew(ran):
    """The bid saved after the switch (the Epoxy section's Travel Labor on the crew's size, the marker saved with the row), reopened: the row
    is exactly as saved, nothing is saved or looked up, and it keeps following the section's crew (6 guys typed on Epoxy install are 6 on
    Travel Labor: 6 x 6.5 x $33). The rule is the row's, not the session's.

    Mutation: leave the crew marker out of syncAutoGuys (test_polish_travel_hours.py runs it on the model)."""
    r = ran["jobSwitch"]["reopened"]
    assert (r["carrier"], r["saves"], r["asked"]) == ("Epoxy", 0, 0)
    assert (r["row"]["days"], r["row"]["guys"], r["row"]["guys_auto"], r["row"]["guys_follow"], r["row"]["hours_seed"]) == (6.5, 4, True, "crew", 6.5)
    assert (r["after"]["row"]["guys"], r["after"]["guysBox"], r["after"]["cost"]) == (6, "6", 6 * 6.5 * 33)


def test_a_box_cleared_on_the_epoxy_sections_travel_labor_is_marked_on_that_row_and_stays_empty(ran):
    """The page edits a section through its view, so a keystroke in the Epoxy section's Travel Labor box must leave its mark on THAT row and
    not on the off root's: the Hours box cleared, then the button's 300 mile answer, and the box is still empty (the tool's 6.5 would have
    become 10). The root's own row, which goes off with the root, is as it was saved and carries no mark.

    Mutation: leave the mark out of the page's input handler (BREAKS below)."""
    c = ran["jobSwitch"]["clearedOnSection"]
    assert (c["row"]["days"], c["hoursBox"], c["row"]["hours_typed"]) == ("", "", True)
    assert c["rootRow"]["days"] == 6.5 and "hours_typed" not in c["rootRow"] and "guys_typed" not in c["rootRow"]


def test_a_plain_reopen_and_a_switch_that_keeps_the_carrier_fill_nothing(ran):
    """The other half of the same rule. The same Polish bid opened as Polish (a plain reopen) is exactly as saved: the crew-size row as it
    was, no save, no lookup. A Polish bid whose Travel Labor was left blank is left blank by a plain reopen. Switching Polish to Combo keeps
    the root as the carrier (the first base), so its blank row is not filled; and a switch with no distance on file has nothing to follow.

    Mutation: fill on every restructure and not only when the carrier changed (BREAKS below)."""
    j = ran["jobSwitch"]
    p = j["plain"]
    assert (p["carrier"], p["tabs"], p["saves"], p["asked"]) == ("Polish", [], 0, 0)
    assert (p["row"]["days"], p["row"]["guys"], p["row"]["guys_follow"]) == (6.5, 4, "crew")
    bp = j["blankPlain"]
    assert (bp["row"]["days"], bp["row"]["guys"], bp["row"]["guys_auto"], bp["saves"], bp["asked"]) == ("", "", False, 0, 0)
    assert "hours_seed" not in bp["row"]
    c = j["combo"]
    assert (c["carrier"], c["tabs"], c["row"]["days"], c["row"]["guys"], c["rootKind"]) == ("Polish", ["Epoxy"], "", "", "base")
    assert "hours_seed" not in c["row"] and "guys_follow" not in c["row"]
    nd = j["noDistance"]
    assert (nd["carrier"], nd["row"]["days"], nd["row"]["guys"], nd.get("distance")) == ("Epoxy", "", "", None)


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
    assert ran["polish"] == {"tabs": "none", "kind": "base", "bid": ran["polish"]["bid"], "activeBid": ran["polish"]["bid"]}
    assert ran["polish"]["bid"] > 0
    # Gyp is ready since Phase 14: its job opens on a Gyp section filed under the base sheet (test_v2_gyp.py holds the rest)
    assert ran["gyp"] == {"tabs": ['Gyp (USG 1-8")']}


def test_the_strip_lists_what_the_bid_is_made_of_and_never_the_polish_root_of_an_epoxy_job(ran):
    s = ran["strip"]
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
    "the panel lists the off root": (
        "js/bid-model.js", '    var list = entries.filter(function (e) { return e.kind !== "off"; });',
        "    var list = entries.slice();",
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
    "the distance fills the model's own Travel Labor row and not the carrier section's": (
        "js/bid-model.js", "        holder = carrier.section;", "        holder = model;",
        lambda r: r["travelFill"]["before"]["row"]["days"] != 6.5 or r["travelFill"]["rootTravelUntouched"] is not True),
    "the distance on file is not put on the new carrier's row after a job type switch": (
        "js/polish-estimate.js", "if (carrierMoved) B.followDistance(ROOT);", "void 0;",
        lambda r: r["jobSwitch"]["switched"]["before"]["row"]["days"] != 6.5 or r["jobSwitch"]["blankSwitch"]["row"]["days"] != 6.5),
    "a box cleared on the Epoxy section's Travel Labor is refilled by the next answer": (
        "js/polish-estimate.js", 'if (k === "guys" || k === "days") B.markTypedByHand(M.labor[j], k);', "void 0;",
        lambda r: r["jobSwitch"]["clearedOnSection"]["hoursBox"] != ""),
    "every restructure fills the distance, even one that keeps the carrier": (
        "js/polish-estimate.js", "var carrierMoved = restructured && openingTab() !== carrierBefore;", "var carrierMoved = restructured;",
        lambda r: r["jobSwitch"]["combo"]["row"]["days"] != ""),
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


# ── the override boxes on the Review step (Hanz, 2026-10-16) ─────────────────────────────────────────────────────────
# Driven through the page: each box typed as a person types it, the figures read off the step afterwards, and every
# price held to the engines (priceSection over the library the bid buys), never to a number typed here.
def test_the_hard_bid_switch_fills_the_discount_with_kyles_rule_and_a_typed_figure_still_wins(ran):
    """Hanz, 2026-10-17: "lets make the hard bid have those rules but still overridable in the review tab". The switch is on
    the Discount line of an Epoxy section's Review step; on, the box shows the rule's figure greyed and the rule prices."""
    h = ran["hardBid"]
    b = h["before"]
    assert b["switchShown"] and b["aria"] == "false" and b["hardBid"] == 0 and b["adjust"] == "absent"
    assert b["placeholder"] == "0" and "4% off from $60,000" in b["note"]

    on = h["on"]
    assert on["stored"] == {"hard_bid": True} and on["aria"] == "true" and on["sameNode"], "the switch was redrawn"
    assert on["subTotal"] >= 13000, "the fixture is too small for the rule to give anything, so this proves nothing"
    assert on["hardBid"] == on["handHardBid"] != 0 and on["total"] == on["handTotal"]
    assert on["rulePct"] == pytest.approx(-0.025)
    assert on["placeholder"] == "2.5" and "takes 2.5% off" in on["note"]
    assert on["rowOff"] == "" and on["shown"].replace(",", "").lstrip("-$") == str(-on["hardBid"])

    t = h["typed"]
    assert t["hardBid"] == t["hand"] != t["ruleWas"], "a typed 3% did not replace the rule"
    assert h["cleared"]["hardBid"] == h["cleared"]["rule"], "clearing the box did not go back to the rule"

    off = h["off"]
    assert off["aria"] == "false" and off["adjust"] == "absent" and not off["savedHasKey"]
    assert off["hardBid"] == 0 and off["total"] == b["total"] and off["placeholder"] == "0"


def test_the_review_step_offers_every_box_with_the_rule_greyed_in(ran):
    a = ran["adjust"]["before"]
    assert a["adjust"] == "absent" and a["total"] == a["hand"]
    assert all(present for _k, present in a["boxes"]) and a["bulkSwitch"] is False, "the Bulk switch is gone (2026-10-20)"
    assert a["gpPlaceholder"] == "35" and a["gpUsed"] == 0.35, "the greyed GP is the rule the bid is using"
    assert a["shipPlaceholder"] == "9" and a["shipUsed"] == 0.09


def test_the_supplier_discount_reprices_the_materials_as_the_engines_do(ran):
    s = ran["adjust"]["supplier"]
    assert s["stored"] == {"supplier_pct": "20"}
    assert s["material"] == s["hand"]["material"] < 11991 and s["total"] == s["hand"]["total"]
    assert (s["materialShown"], s["totalShown"]) == ("$10,253", "$30,527"), "repainted in place"
    # KYLE'S GP LADDER, NOT A BUG: the cheaper materials take the sub-total under $15,000, where the sheet's GP steps up
    # from 35% to 45%, so this job's total RISES with a discount. The engines and the page agree on it.
    assert s["fell"] is False


def test_an_unusable_box_is_named_and_left_out_and_clearing_it_takes_the_name_away(ran):
    a = ran["adjust"]
    assert a["gpBad"]["warn"] == {"text": "not a number, so it is not used", "hidden": False}
    assert a["gpBad"]["sameAsBefore"] is True
    assert a["gpCleared"]["warn"]["hidden"] is True and a["gpCleared"]["stored"] == {"supplier_pct": "20"}


def test_a_discount_bigger_than_the_labor_and_markup_is_refused_on_the_page(ran):
    h = ran["adjust"]["discountHuge"]
    assert h["refused"] is True and h["hardBid"] == 0
    assert h["warn"] == {"text": "more than the labor and markup it comes off, so it is not used", "hidden": False}


def test_the_discount_line_prices_shows_and_the_dollars_win(ran):
    a = ran["adjust"]
    assert a["discountAmt"]["hardBid"] == -1500 and a["discountAmt"]["shown"] == "-$1,500"
    assert a["discountAmt"]["total"] == a["discountAmt"]["hand"] and a["discountAmt"]["warn"]["hidden"] is True
    assert a["dollarsWin"]["hardBid"] == -1500, "with both typed, the dollars are the line"
    assert a["percent"]["hardBid"] < 0 and a["percent"]["total"] == a["percent"]["hand"]


def test_there_is_no_bulk_switch_and_a_saved_bulk_answer_buys_nothing_at_bulk(ran):
    """Hanz, 2026-10-20: "Remove all bulk discount toggle in the V2 estimates". No bid on either database had it on."""
    n = ran["adjust"]["noBulk"]
    assert n["drawn"] is False, "the Review step still draws a Bulk Discount switch"
    assert "bulk" not in (n["kept"] or {}), "the model still keeps a saved bulk answer"
    assert n["same"] is True, "a saved bulk answer still changes the price"


def test_the_save_carries_the_boxes_and_the_proposal_is_the_bid_shown(ran):
    s = ran["adjust"]["saved"]
    assert s["adjust"] == {"discount_pct": "3", "supplier_pct": "20"}
    assert s["lump"] == s["total"]


def test_clearing_every_box_puts_the_bid_back_exactly(ran):
    c = ran["adjust"]["cleared"]
    assert c["adjust"] == "absent" and c["savedHasKey"] is False
    assert c["total"] == ran["adjust"]["before"]["total"]


def test_the_save_names_the_height_of_the_cove_the_bid_bought(ran):
    """The proposal reads it before falling back to 6 (test_cove_height_v2.py)."""
    assert ran["priced"]["coveHeight"] == "4"
