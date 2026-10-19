"use strict";
/* AN EPOXY JOB ON THE REAL ESTIMATE PAGE: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js
 * boots it, on the library backend/ops/seed_library_from_workbook.py plans.
 *
 * Phase 12 of the v2 estimating program. A v2 Epoxy job is an Epoxy SECTION of the bid with the Polish root marked off,
 * and the page's Material, Labor and Review panels edit whichever section is on show. Every fact below is read off the
 * page after it ran: the model it held, the panels it drew, what it saved. Nothing is a source assertion.
 *
 * Usage: node epoxy-page-harness.js <frontend-dir> <plan.json>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
const LIB = require(path.join(ROOT, "js", "library-core.js"));
const X = require(path.join(ROOT, "js", "epoxy-takeoff.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in epoxy-page-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js",
  ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "popup", "MODEL"]);

const asms = plan.assemblies;
const items = plan.items;
const norm = (t) => String(t).replace(/\s+/g, " ").trim();
const asmNamed = (n) => asms.find((a) => norm(a.name) === norm(n));

// What the library's labor list and the Labor Calculator hold: the one Epoxy crew line the seed plans.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
  default_work_types: [], default_on: true };
const laborRows = [TRAVEL_ROW].concat(plan.labor.map((r) => Object.assign({}, r, { default_on: true, owner_email: "kyle@wetreadwell.com" })));
const calcRows = plan.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));

/** A draft the way the v2 intake leaves it for an Epoxy job: the answers it asks and the quantities it asked. */
function epoxyDraft(extra) {
  return P.blob(Object.assign({
    work_type: "epoxy", system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "",
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false } },
  }, extra || {}));
}

const flush = () => new Promise((r) => setImmediate(r));
const text = (built, id) => built.doc.getElementById(id).textContent;
const html = (built, id) => built.doc.getElementById(id).innerHTML;
// THE SHEETS PANEL replaced the strip of section buttons (Sheets phase 3): it lists every sheet that is part of the bid, one
// data-section-tab each, and is drawn for a bid with one sheet too. Only the "Open sheet" line above the step rail hides for one.
const panelTabs = (built) => (html(built, "sheets-panel").match(/data-section-tab="([^"]*)"/g) || []);

/** The same job priced without the page: a section built by hand, the engine and the library, nothing of the page in it. */
function priceByHand(rows, over) {
  const o = over || {};
  const m = B.activateSection(Object.assign({}, B.freshModel(), { kind: "off" }), "Epoxy", "base", {});
  m.conditions = Object.assign({}, m.conditions, { taxable: true, prevailing_wage: false, remodel_tax: false }, o.conditions || {});
  m.tabs.Epoxy.takeoff = rows;
  m.tabs.Epoxy.labor = o.labor || [{ id: "epoxy-install", label: "Epoxy install", guys: 3, days: 5, rate: 33, unit: "days" }];
  if (o.travel) m.travel = o.travel;
  return B.priceSection(m, "Epoxy", {
    material: (e) => {
      const t = e.section.takeoff;
      const r = X.sectionMaterial(t, { items: items, sf: B.takeoffSf(t), pool: B.poolsPacks(e.section),
        rowPrice: (row) => { const a = asms.find((x) => x.id === row.assembly_id); return a ? LIB.priceAssembly(a, items, B.num(row.measurement)) : null; } });
      return { material: r.material, tooling: r.tooling };
    },
  });
}

async function open(draft, extra) {
  const b = P.build(Object.assign({ blob: draft, asms: asms, items: items, labor: laborRows, laborCalc: calcRows }, extra || {}));
  await b.api.init();
  await flush();
  return b;
}

async function main() {
  const out = {};
  const flake = asmNamed("MACRO Flake Single Broadcast");
  const cove = asmNamed("Cove: Epoxy 4\"");

  // ── 1. a new Epoxy job opens as an Epoxy section, seeded, with no Polish in it ──
  const b = await open(epoxyDraft());
  const m0 = b.api.model();
  const root0 = b.api.state();
  out.opened = {
    tabs: Object.keys(m0.tabs || {}), rootKind: m0.kind, takeoff: clone(m0.takeoff),
    laborIds: m0.labor.map((r) => r.id), laborGuys: m0.labor.map((r) => r.guys),
    strip: { tabs: panelTabs(b) },
    panelHasPatch: html(b, "panels").indexOf("data-epoxy-patch") >= 0,
    panelHasPolishCards: /Dye|Joint filler/.test(html(b, "panels")),
    profile: m0.tabs ? undefined : null, savesOnOpen: b.rec.saves.length,
    travelRowOnSection: m0.labor.some((r) => r.id === "travel"), laborIdsAll: m0.labor.map((r) => r.id),
  };
  out.opened.profile = b.api.model().tabs === undefined ? null : undefined;

  // ── 2. the estimator picks the system and the cove; the page's price is the hand-priced one ──
  const api = b.api;
  api.setAssembly(0, flake.name);
  api.setAssembly(1, cove.name);
  api.changed(true);
  b.clock.fire();
  const rows = clone(api.model().takeoff);
  const byHand = priceByHand(rows, { labor: clone(api.model().labor), travel: clone(root0.polish_estimate ? api.model().travel : null) });
  const barNumber = Number(text(b, "bid-total").replace(/[^0-9]/g, ""));
  const saved = b.rec.saves[b.rec.saves.length - 1];
  out.priced = {
    barNumber: barNumber, byHand: byHand.total, handMaterial: byHand.material, handTooling: byHand.tooling,
    pageBid: api.activeBid().total, pageMaterial: api.activeBid().material, pageTooling: api.activeBid().tooling,
    materialTotalOnPanel: text(b, "panels").indexOf("Material total") >= 0,
    savedKeys: Object.keys(saved).sort(),
    pricedTabs: (saved.priced_tabs || []).map((t) => [t.id, t.role, t.kind, t.v2, t.total, t.sf]),
    lump: saved.proposal_lump_sum, computed: saved.computed_bid && saved.computed_bid.lump_sum,
    sheetArea: saved.sheet_area, polishSf: saved.polish_sf === undefined ? "absent" : saved.polish_sf,
    coveHeight: saved.cove_height_v2,
    rootKind: saved.polish_estimate.kind, savedTabs: Object.keys(saved.polish_estimate.tabs || {}),
    epoxyTotals: saved.polish_estimate.tabs && saved.polish_estimate.tabs.Epoxy.totals.total,
    stamp: saved.polish_estimate.tabs && saved.polish_estimate.tabs.Epoxy.profile,
    rootHasNoTotals: saved.polish_estimate.totals === undefined || Object.keys(saved.polish_estimate.totals || {}).length === 0,
  };

  // ── 3. the Review step is the Epoxy section's: its tooling, its 3 percent and 13 percent, none of Polish's ──
  api.go(2);
  const review = html(b, "panels");
  out.review = {
    hasTooling: review.indexOf("Tooling and consumables") >= 0,
    // the rate each line was priced with (2026-10-16: shown in a keyed span beside its override box)
    superPct: (/data-mkrate="super_pct">([^<]*)</.exec(review) || [])[1],
    softPct: (/data-mkrate="soft_pct">([^<]*)</.exec(review) || [])[1],
    shipPct: (/data-mkrate="ship_pct">([^<]*)</.exec(review) || [])[1],
    toolingAmount: (/data-mk="tooling">([^<]*)</.exec(review) || [])[1],
    total: (/data-mk="total">([^<]*)</.exec(review) || [])[1],
    noDye: !/Dye/.test(review),
  };

  // ── 4. the Labor step edits the Epoxy crew line, and a day typed there reaches the price ──
  api.go(1);
  const before = api.activeBid().total;
  const crew = api.model().labor.findIndex((r) => r.id === "epoxy-install");
  // A new bid opens with the crew's guys and days empty (only the rate is filled), so the crew is typed in: three guys, nine days.
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="guys"]', "3");
  P.typeInto(b, '[data-lab="' + crew + '"][data-k="days"]', "9");
  api.changed(false);
  const after = api.activeBid().total;
  out.labor = {
    rows: api.model().labor.map((r) => [r.id, r.guys, r.days]),
    editedSection: has(b.api.state(), "polish_estimate") ? null : undefined,
    before: before, after: after,
    byHandAfter: priceByHand(clone(api.model().takeoff), { labor: clone(api.model().labor), travel: clone(api.model().travel) }).total,
  };
  b.clock.fire();
  const afterSave = b.rec.saves[b.rec.saves.length - 1];
  out.labor.savedDays = afterSave.polish_estimate.tabs.Epoxy.labor.filter((r) => r.id === "epoxy-install")[0].days;
  out.labor.rootLaborUntouched = afterSave.polish_estimate.labor.length;

  // ── 5. a row added beside a measured one starts as the same floor, and is not counted twice ──
  api.go(0);
  api.addPickedTakeoffRow({ kind: "asm", id: asmNamed("Primer: MVP (@ 12 mils)").id, name: asmNamed("Primer: MVP (@ 12 mils)").name });
  const mdl = api.model();
  const added = mdl.takeoff[mdl.takeoff.length - 1];
  out.sameFloor = { added: { sameFloor: !!added.same_floor, measurement: added.measurement, unit: added.unit },
                    area: B.takeoffSf(mdl.takeoff), carrier: B.num(mdl.takeoff[0].measurement) };

  // ── 6. a saved Epoxy bid opens as it was saved and writes nothing ──
  const reopen = await open(clone(b.store.blob));
  out.reopened = {
    saves: reopen.rec.saves.length, armed: reopen.clock.armed(),
    total: reopen.api.activeBid().total, takeoffRows: reopen.api.model().takeoff.length,
    tabs: Object.keys(reopen.api.model().tabs || {}),
  };

  // ── 7. a Polish job is untouched: no section is added and the page prices the root as it always did ──
  const pol = await open(P.blob({ work_type: "polish" }));
  out.polish = {
    tabs: pol.api.model().tabs === undefined ? "none" : Object.keys(pol.api.model().tabs),
    kind: pol.api.model().kind === undefined ? "base" : pol.api.model().kind,
    bid: pol.api.bid().total, activeBid: pol.api.activeBid().total,
  };

  // ── 8. a job type v2 cannot price yet adds nothing (a Gyp draft is opened as it is) ──
  const gyp = await open(P.blob({ work_type: "gyp" }));
  out.gyp = { tabs: gyp.api.model().tabs === undefined ? "none" : Object.keys(gyp.api.model().tabs) };

  // ── 9. a bid with an Epoxy base and a Seal option: the strip lists those two, never the Polish root ──
  const withSeal = clone(b.store.blob);
  withSeal.polish_estimate.tabs.Seal = { layout: "seal", kind: "option", profile: "seal@1", takeoff: [], labor: [],
    contingency: 0, fees: 0, totals: {} };
  const two = await open(withSeal);
  out.strip = {
    html: html(two, "sheets-panel"),
    tabs: panelTabs(two),
  };
  const sealBtn = two.doc.querySelector('[data-section-tab="Seal"]');
  P.clickEl(two, sealBtn);
  // the Seal option is edited on the page's own panels since Phase 15: its Material step is the takeoff with the patch
  out.strip.sealPanelIsTakeoff = html(two, "panels").indexOf("data-seal-patch") >= 0 && html(two, "panels").indexOf("Priced with seal@1") < 0;
  P.clickEl(two, two.doc.querySelector('[data-section-tab="Epoxy"]'));
  out.strip.epoxyPanelIsTakeoff = html(two, "panels").indexOf("data-epoxy-patch") >= 0;

  // ── 10. a cove row prices from its length, by the sheet's formula, on the page ──
  const c = await open(epoxyDraft({ system_1_sf: 6000, cove_1_lf: 777 }));
  c.api.setAssembly(0, asmNamed("40-S (Q28) Quartz Double Broadcast").name);
  c.api.setAssembly(1, asmNamed("Cove: Epoxy 8\" + Cap").name);
  c.api.changed(true);
  const coveRow = c.api.model().takeoff[1];
  out.cove = { row: c.api.rowPrice(coveRow, c.api.model().takeoff).total,
               direct: X.priceCoveRow(coveRow.assembly_id, 777, { items: items, quartz: true }).total,
               silica: X.priceCoveRow(coveRow.assembly_id, 777, { items: items, quartz: false }).total };

  // ── 11. a Polish base with an Epoxy base beside it: editing Epoxy never touches the root's rows in what is saved ──
  const both = P.blob({ work_type: "combo", polish_estimate: Object.assign(clone(P.MODEL), { tabs: { Epoxy: {
    layout: "epoxy", kind: "base", profile: "epoxy@1", takeoff: [{ assembly_id: flake.id, assembly_name: flake.name, measurement: 4000, unit: "SF" }],
    labor: [{ id: "epoxy-install", label: "Epoxy install", guys: 3, days: 4, rate: 33, unit: "days" }], contingency: 0, fees: 0, totals: {} } } }) });
  const w = await open(both);
  const rootBefore = clone(w.api.state().polish_estimate.takeoff);
  P.clickEl(w, w.doc.querySelector('[data-section-tab="Epoxy"]'));
  P.typeInto(w, '[data-tk="0"][data-k="measurement"]', "5500");
  w.clock.fire();
  const savedBoth = w.rec.saves[w.rec.saves.length - 1].polish_estimate;
  out.both = {
    rootTakeoff: savedBoth.takeoff.map((r) => [r.assembly_name, r.measurement]),
    rootBefore: rootBefore.map((r) => [r.assembly_name, r.measurement]),
    epoxyMeasurement: savedBoth.tabs.Epoxy.takeoff[0].measurement,
    rootLaborIds: savedBoth.labor.map((r) => r.id), epoxyLaborIds: savedBoth.tabs.Epoxy.labor.map((r) => r.id),
    stripTabs: panelTabs(w),
  };

  // ── 12. the add pop-up offers the work type's own assemblies and materials first, in a section other than the root ──
  const extra = { asms: asms.concat([{ id: "zz-untagged-asm", name: "AAA untagged assembly", unit: "SF", lines: [], default_work_types: [] }]),
                  items: items.concat([{ id: "zz-untagged-item", name: "AAA untagged material", unit: "Gallon", buy_qty: 1, unit_cost: 1, coverage: 100, default_work_types: [] }]) };
  const keysOf = (built) => { P.clickOn(built, "[data-add-row]"); return P_popup(built).querySelectorAll("[data-pk]").map((e) => e.attrs["data-pk"]); };
  const P_popup = (built) => P.popup(built);
  const ep = await open(epoxyDraft(), extra);
  const epKeys = keysOf(ep);
  const forEpoxy = (r) => (r.default_work_types || []).indexOf("epoxy") >= 0;
  const taggedIds = new Set(asms.filter(forEpoxy).map((a) => "asm:" + a.id).concat(items.filter(forEpoxy).map((i) => "item:" + i.id)));
  const firstUntagged = epKeys.findIndex((k) => k.indexOf("zz-untagged") >= 0);
  const lastTagged = epKeys.map((k, i) => (taggedIds.has(k) ? i : -1)).reduce((a, b) => Math.max(a, b), -1);
  const po = await open(P.blob({ work_type: "polish" }), extra);
  const poKeys = keysOf(po);
  out.picker = { epoxyFirstUntagged: firstUntagged, epoxyLastTagged: lastTagged, total: epKeys.length, epoxyRows: taggedIds.size,
                 polishAaaBeforeMacro: poKeys.indexOf("asm:zz-untagged-asm") < poKeys.indexOf("asm:wb-epoxy-sys-macro-flake-single-broadcast"),
                 epoxyAaaBeforeMacro: epKeys.indexOf("asm:zz-untagged-asm") < epKeys.indexOf("asm:wb-epoxy-sys-macro-flake-single-broadcast") };
  out.adjust = await adjustSection();
  out.hardBid = await hardBidSection();
  out.travelFill = await travelFillSection();
  return out;
}

/** THE DISTANCE FILLS THE EPOXY SECTION'S TRAVEL LABOR (Hanz, 2026-10-20: "Every work day (Kyle's sheet math)"). An Epoxy job's
 *  Polish root is off and the Epoxy section carries the job's travel, so the Travel Labor row the answer fills is Epoxy's own, on
 *  Epoxy's own crew (Kyle's Epoxy row 52): 4 guys for 12 days is 48 man-days, and the line is 48 x the 6.5 hours of a 380 mile
 *  round trip x $33. Driven through the real page: the lookup lands on a new Epoxy bid, the crew is typed as a person types it,
 *  and the save is read back. The root's own Travel row, which is off with the root, is never touched. */
async function travelFillSection() {
  const draft = epoxyDraft({ address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" });
  const b = await open(draft, { distance: { ok: true, miles: 190, reason: "" } });
  b.api.go(1);
  for (let i = 0; i < 6; i++) await flush();
  const model = () => b.api.model();
  const ti = () => model().labor.findIndex((r) => r.id === "travel");
  const ci = () => model().labor.findIndex((r) => r.id === "epoxy-install");
  const box = (k) => String(P.need(b, '[data-lab="' + ti() + '"][data-k="' + k + '"]').value);
  const src = () => P.need(b, "[data-trv-src]");
  const before = { row: clone(model().labor[ti()]), hoursBox: box("days"), guysBox: box("guys"), carries: !!b.doc.querySelector("[data-dist]") };
  P.typeInto(b, '[data-lab="' + ci() + '"][data-k="guys"]', "4");
  P.typeInto(b, '[data-lab="' + ci() + '"][data-k="days"]', "12");
  const row = model().labor[ti()];
  const after = { row: clone(row), guysBox: box("guys"), cost: B.laborCost(row), manDays: B.travelManDays(model().labor),
                  note: { text: src().textContent, hidden: src().hidden } };
  b.clock.fire();
  const saved = b.rec.saves[b.rec.saves.length - 1].polish_estimate;
  // THE CONTROL: the same job with the same crew typed and no distance answer at all. The off root's own Travel row is whatever the
  // page makes of it (its guys follow the root's man-days on open), and the answer must leave it exactly as that.
  const ctl = await open(draft);
  ctl.api.go(1);
  const cm = () => ctl.api.model();
  const cci = cm().labor.findIndex((r) => r.id === "epoxy-install");
  P.typeInto(ctl, '[data-lab="' + cci + '"][data-k="guys"]', "4");
  P.typeInto(ctl, '[data-lab="' + cci + '"][data-k="days"]', "12");
  ctl.clock.fire();
  const controlSaved = ctl.rec.saves[ctl.rec.saves.length - 1].polish_estimate;
  const rootTravel = (m) => JSON.stringify(m.labor.filter((r) => r.id === "travel")[0]);
  return { before: before, after: after, tabs: Object.keys(saved.tabs || {}), rootKind: saved.kind,
           savedEpoxyTravel: clone(saved.tabs.Epoxy.labor.filter((r) => r.id === "travel")[0]),
           rootTravelUntouched: rootTravel(saved) === rootTravel(controlSaved), rootTravel: rootTravel(saved),
           controlEpoxyTravel: clone(controlSaved.tabs.Epoxy.labor.filter((r) => r.id === "travel")[0]),
           distance: saved.distance };
}

/** THE HARD BID SWITCH on the Review step's Discount line (Hanz, 2026-10-17), driven through the page: by click and by the
 *  keyboard, with a discount typed over the rule and cleared again. Every figure is held to priceSection over the same
 *  section with the same `adjust`, worked out without the page. */
async function hardBidSection() {
  const b = await open(epoxyDraft());
  const api = b.api;
  api.setAssembly(0, asmNamed("MACRO Flake Single Broadcast").name);
  api.setAssembly(1, asmNamed("Cove: Epoxy 4\"").name);
  api.changed(true);
  b.clock.fire();
  api.go(2);
  const section = () => api.model().tabs.Epoxy;
  const hand = (adj) => {
    const m = clone(api.model());
    if (adj) m.tabs.Epoxy.adjust = adj; else delete m.tabs.Epoxy.adjust;
    const lib = LIB.itemsForBid(items, B.materialAdjust(m.tabs.Epoxy.adjust));
    const priceRow = (r) => { const a = asms.find((x) => x.id === r.assembly_id); return a ? LIB.priceAssembly(a, lib, B.num(r.measurement)) : null; };
    return B.priceSection(m, "Epoxy", { material: (e) => {
      const t = e.section.takeoff;
      const r = X.sectionMaterial(t, { items: lib, sf: B.takeoffSf(t), rowPrice: priceRow, pool: B.poolsPacks(e.section) });
      return { material: r.material, tooling: r.tooling };
    } });
  };
  const box = () => P.need(b, '[data-adj="discount_pct"]');
  const ph = () => String(box().placeholder || box().attrs.placeholder || "");
  const note = () => (b.doc.querySelector("[data-hbnote]") || {}).textContent || null;
  const sw = () => b.doc.querySelector("[data-adj-hb]");
  const o = {};
  const before = api.activeBid();
  o.before = { switchShown: !!sw(), aria: sw() && sw().attrs["aria-checked"], placeholder: ph(), note: note(),
    hardBid: before.hard_bid || 0, total: before.total, adjust: section().adjust === undefined ? "absent" : section().adjust };

  const node = sw();
  P.clickOn(b, "[data-adj-hb]");
  const on = api.activeBid();
  const want = hand({ hard_bid: true });
  o.on = { stored: clone(section().adjust), aria: sw().attrs["aria-checked"], sameNode: sw() === node,
    hardBid: on.hard_bid, handHardBid: want.hard_bid, rulePct: want.hard_bid_pct, total: on.total, handTotal: want.total,
    subTotal: on.sub_total, placeholder: ph(), note: note(),
    shown: (b.doc.querySelector("[data-mkdisc]") || {}).textContent, rowOff: (b.doc.querySelector("[data-disc-row]") || {}).className };

  P.typeInto(b, '[data-adj="discount_pct"]', "3");
  o.typed = { hardBid: api.activeBid().hard_bid, hand: hand({ hard_bid: true, discount_pct: "3" }).hard_bid,
    ruleWas: on.hard_bid };
  P.typeInto(b, '[data-adj="discount_pct"]', "");
  o.cleared = { hardBid: api.activeBid().hard_bid, rule: on.hard_bid };

  node.click = function () { b.doc.fire("click", { target: node, preventDefault() {} }); };
  b.doc.fire("keydown", { target: node, key: " ", preventDefault() {} });
  b.clock.fire();
  const last = b.rec.saves[b.rec.saves.length - 1];
  o.off = { aria: sw().attrs["aria-checked"], adjust: section().adjust === undefined ? "absent" : clone(section().adjust),
    savedHasKey: Object.prototype.hasOwnProperty.call(last.polish_estimate.tabs.Epoxy, "adjust"),
    hardBid: api.activeBid().hard_bid || 0, total: api.activeBid().total, placeholder: ph(), note: note() };
  return o;
}

/** THE OVERRIDE BOXES ON THE REVIEW STEP, driven through the page (Hanz, 2026-10-16). An Epoxy job with the flake system
 *  and a cove: each box typed the way a person types it, and what the page then priced, showed and saved read back. The
 *  section's price is also worked out without the page (priceSection over the library the bid buys: itemsForBid), so
 *  every figure the page shows is held to the engines, never to a number typed into this file. */
async function adjustSection() {
  const flake = asmNamed("MACRO Flake Single Broadcast");
  const cove = asmNamed("Cove: Epoxy 4\"");
  const b = await open(epoxyDraft());
  const api = b.api;
  api.setAssembly(0, flake.name);
  api.setAssembly(1, cove.name);
  api.changed(true);
  b.clock.fire();
  api.go(2);
  const section = () => api.model().tabs.Epoxy;
  // what the step SHOWS now: the element's own text, which the repaint writes (the panel's markup is what was first drawn)
  const mk = (key) => { const el = b.doc.querySelector('[data-mk="' + key + '"]'); return el ? el.textContent : null; };
  const warn = (key) => { const el = b.doc.querySelector('[data-adjwarn="' + key + '"]'); return el ? { text: el.textContent, hidden: !!el.hidden } : null; };
  const box = (key) => P.need(b, '[data-adj="' + key + '"]');
  const hand = (adj) => {
    const m = clone(api.model());
    if (adj) m.tabs.Epoxy.adjust = adj; else delete m.tabs.Epoxy.adjust;
    const lib = LIB.itemsForBid(items, B.materialAdjust(m.tabs.Epoxy.adjust));
    const priceRow = (r) => { const a = asms.find((x) => x.id === r.assembly_id); return a ? LIB.priceAssembly(a, lib, B.num(r.measurement)) : null; };
    return B.priceSection(m, "Epoxy", { material: (e) => {
      const t = e.section.takeoff;
      const r = X.sectionMaterial(t, { items: lib, sf: B.takeoffSf(t), rowPrice: priceRow, pool: B.poolsPacks(e.section) });
      return { material: r.material, tooling: r.tooling };
    } });
  };
  const o = {};
  const before = api.activeBid();
  o.before = { total: before.total, hand: hand(null).total, adjust: section().adjust === undefined ? "absent" : section().adjust,
    boxes: ["ship_pct", "gp_pct", "super_pct", "soft_pct", "discount_pct", "discount_amt", "supplier_pct", "polycrete_pct"]
      .map((k) => [k, !!b.doc.querySelector('[data-adj="' + k + '"]')]),
    bulkSwitch: !!b.doc.querySelector("[data-adj-bulk]"),
    gpPlaceholder: String(box("gp_pct").placeholder || box("gp_pct").attrs.placeholder || ""), gpUsed: before.gp_pct,
    shipPlaceholder: String(box("ship_pct").placeholder || box("ship_pct").attrs.placeholder || ""), shipUsed: before.ship_pct };

  // the supplier discount: the materials, the sub-total and everything under them move; the page equals the engines
  P.typeInto(b, '[data-adj="supplier_pct"]', "20");
  const s = api.activeBid();
  o.supplier = { stored: clone(section().adjust), material: s.material, hand: hand({ supplier_pct: "20" }), total: s.total,
    materialShown: mk("material"), totalShown: mk("total"), fell: s.total < before.total };
  o.supplier.hand = { material: o.supplier.hand.material, total: o.supplier.hand.total };

  // an unusable GP: named under its box, left out of the price
  P.typeInto(b, '[data-adj="gp_pct"]', "abc");
  o.gpBad = { warn: warn("gp_pct"), total: api.activeBid().total, sameAsBefore: api.activeBid().total === s.total };
  P.typeInto(b, '[data-adj="gp_pct"]', "");
  o.gpCleared = { warn: warn("gp_pct"), stored: clone(section().adjust) };

  // a discount in dollars bigger than the labor and markup: refused and named; a sane one priced and shown
  P.typeInto(b, '[data-adj="discount_amt"]', "1,000,000");
  o.discountHuge = { warn: warn("discount_amt"), hardBid: api.activeBid().hard_bid || 0, total: api.activeBid().total,
    refused: !!api.activeBid().discount_refused };
  P.typeInto(b, '[data-adj="discount_amt"]', "$1,500");
  const d = api.activeBid();
  o.discountAmt = { hardBid: d.hard_bid, shown: (b.doc.querySelector("[data-mkdisc]") || {}).textContent, warn: warn("discount_amt"),
    hand: hand({ supplier_pct: "20", discount_amt: "$1,500" }).total, total: d.total };
  P.typeInto(b, '[data-adj="discount_pct"]', "3");
  o.dollarsWin = { hardBid: api.activeBid().hard_bid };
  P.typeInto(b, '[data-adj="discount_amt"]', "");
  o.percent = { hardBid: api.activeBid().hard_bid, hand: hand({ supplier_pct: "20", discount_pct: "3" }).total,
    total: api.activeBid().total };

  // the Bulk Discount switch, by click and by the keyboard, repainted where it is
  const sw = () => P.need(b, "[data-adj-bulk]");
  const node = sw();
  P.clickOn(b, "[data-adj-bulk]");
  o.bulkClick = { stored: section().adjust.bulk === true, aria: sw().attrs["aria-checked"], sameNode: sw() === node,
    total: api.activeBid().total, hand: hand(clone(section().adjust)).total };
  node.click = function () { b.doc.fire("click", { target: node, preventDefault() {} }); };
  b.doc.fire("keydown", { target: node, key: " ", preventDefault() {} });
  o.bulkKey = { stored: section().adjust.bulk === true, aria: sw().attrs["aria-checked"] };

  // the save carries the boxes, and the proposal's lump sum is the bid the Review step shows
  b.clock.fire();
  const saved = b.rec.saves[b.rec.saves.length - 1];
  o.saved = { adjust: saved.polish_estimate.tabs.Epoxy.adjust, lump: saved.proposal_lump_sum, total: api.activeBid().total };

  // every box cleared: the section holds no `adjust` and prices exactly as it did before anything was typed
  ["supplier_pct", "discount_pct"].forEach((k) => P.typeInto(b, '[data-adj="' + k + '"]', ""));
  b.clock.fire();
  const last = b.rec.saves[b.rec.saves.length - 1];
  o.cleared = { adjust: section().adjust === undefined ? "absent" : clone(section().adjust),
    savedHasKey: Object.prototype.hasOwnProperty.call(last.polish_estimate.tabs.Epoxy, "adjust"), total: api.activeBid().total };
  return o;
}

main().then((out) => console.log(JSON.stringify(out))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
