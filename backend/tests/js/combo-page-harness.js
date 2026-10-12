"use strict";
/* A COMBO JOB (Epoxy + Polish) ON THE REAL ESTIMATE PAGE: js/polish-estimate.js, whole, booted the way
 * epoxy-page-harness.js boots it, on the Epoxy library backend/ops/seed_library_from_workbook.py plans and a small
 * Polish library of its own.
 *
 * Phase 13 of the v2 estimating program. A v2 Combo job is TWO base sections of one bid: the Polish root and an Epoxy
 * section. Each is priced on its own profile through the engine, the bid is the engine's combine (each section's total
 * after its OWN gross profit, summed), and the job's travel is charged once, on the section that carries it. Every fact
 * below is read off the page after it ran: the model it held, the panels it drew, what it saved. Nothing is a source
 * assertion, and every price is set beside the same job priced by hand with no page in it.
 *
 * Usage: node combo-page-harness.js <frontend-dir> <plan.json>   ->  one line of JSON
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
const E = require(path.join(ROOT, "js", "bid-engine.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in combo-page-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js",
  ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "popup", "MODEL"]);

// ── the library: the Epoxy rows the seed plans, and a small Polish library ──
const POLISH_ITEMS = [
  { id: "cp-i1", name: "Combo OPF", unit: "Gal", buy_qty: 1, unit_cost: 85.3827, coverage: 275, default_work_types: ["polish"] },
  { id: "cp-i3", name: "Combo Armor Top", unit: "Kit", buy_qty: 1, unit_cost: 382.4475, coverage: 775, default_work_types: ["polish"] },
];
const POLISH_ASMS = [
  { id: "cp-a1", name: "Combo Polish 800 Grit", unit: "SF", default_work_types: ["polish"], lines: [
    { item_id: "cp-i1", coverage: 275, waste_pct: 5, roundup: true },
    { item_id: "cp-i3", coverage: 775, waste_pct: 0, roundup: true }] },
];
const asms = plan.assemblies.concat(POLISH_ASMS);
const items = plan.items.concat(POLISH_ITEMS);
const norm = (t) => String(t).replace(/\s+/g, " ").trim();
const asmNamed = (n) => asms.find((a) => norm(a.name) === norm(n));

const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
  default_work_types: [], default_on: true };
const POLISH_CREW = { id: "polishing", name: "Polishing", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true,
  default_work_types: ["polish"], default_on: true };
const laborRows = [TRAVEL_ROW, POLISH_CREW].concat(plan.labor.map((r) => Object.assign({}, r, { default_on: true, owner_email: "kyle@wetreadwell.com" })));
const calcRows = plan.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));

/** A draft the way the v2 intake leaves it for a Combo job: the answers it asks and the quantities it asked. Dye and joint
 *  filler are off, so the Polish root's material is its takeoff alone (the page prices them off the library otherwise). */
function comboDraft(extra) {
  return P.blob(Object.assign({
    work_type: "combo", polish_sf: 10000, polish_2_sf: "", system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "",
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false, dye: false,
      joint_filler: false, remove_existing_jf: false } },
  }, extra || {}));
}

const flush = () => new Promise((r) => setImmediate(r));
const html = (built, id) => built.doc.getElementById(id).innerHTML;
const text = (built, id) => built.doc.getElementById(id).textContent;

async function open(draft, extra) {
  const b = P.build(Object.assign({ blob: draft, asms: asms, items: items, labor: laborRows, laborCalc: calcRows }, extra || {}));
  await b.api.init();
  await flush();
  return b;
}

function rowPriceOf(row) {
  const a = asms.find((x) => x.id === row.assembly_id);
  return a ? LIB.priceAssembly(a, items, B.num(row.measurement)) : null;
}

/** THE SAME JOB PRICED WITHOUT THE PAGE: the Polish root through markupChain (what the page's bid() is), the Epoxy section
 *  through priceSection (the engine's epoxy profile), both from the saved model, then the engine's combine. Nothing of the
 *  page's own pricing, and nothing of composePricingSnapshot, is in it. */
function byHand(model, remodelRate) {
  // each row ALONE, then bought once for the section when it is stamped to pool (library-core pricePool)
  const alone = model.takeoff.map((r) => (B.rowOn(r) ? rowPriceOf(r) : null));
  const bought = B.poolsPacks(model) ? LIB.pricePool(alone, { on: model.takeoff.map((r) => B.rowOn(r)) }) : alone;
  const rootMaterial = bought.reduce((t, p) => t + (p ? p.total : 0), 0);
  const polish = B.markupChain({
    material: rootMaterial, labor: B.laborTotal(model.labor, model.conditions),
    travel: B.travelCosts(model.travel, model.labor).total, contingency: model.contingency, fees: model.fees,
    conditions: model.conditions, sf: B.takeoffSf(model.takeoff), remodel_rate: remodelRate,
  });
  const epoxy = B.priceSection(model, "Epoxy", {
    material: (e) => {
      const t = e.section.takeoff;
      const r = X.sectionMaterial(t, { items: items, sf: B.takeoffSf(t), pool: B.poolsPacks(e.section), rowPrice: (row) => rowPriceOf(row) });
      return { material: r.material, tooling: r.tooling };
    },
    remodel_rate: remodelRate,
  });
  const combined = E.combine([{ layout: "polish", result: polish }, { layout: "epoxy", result: epoxy }]);
  return { polish: polish, epoxy: epoxy, combined: combined };
}

const money = (n) => "$" + Math.round(n).toLocaleString("en-US");

async function main() {
  const out = {};
  const flake = asmNamed("MACRO Flake Single Broadcast");
  const cove = asmNamed("Cove: Epoxy 4\"");
  const polishAsm = asmNamed("Combo Polish 800 Grit");

  // ── 1. a new Combo job opens as two base sections, seeded, on the Polish root ──
  const b = await open(comboDraft());
  const api = b.api;
  const m0 = api.model();
  out.opened = {
    tabs: Object.keys(m0.tabs || {}), rootKind: m0.kind === undefined ? "base" : m0.kind,
    epoxyKind: m0.tabs && m0.tabs.Epoxy && m0.tabs.Epoxy.kind,
    strip: (html(b, "sections").match(/data-section-tab="([^"]*)"/g) || []), stripHidden: !!b.doc.getElementById("sections").hidden,
    activeIs: html(b, "sections").indexOf('aria-current="true">Polish') >= 0 ? "Polish" : "other",
    rootTakeoff: clone(m0.takeoff).map((r) => [r.measurement, r.unit]),
    epoxyTakeoff: clone(m0.tabs.Epoxy.takeoff).map((r) => [r.measurement, r.unit]),
    rootLaborIds: m0.labor.map((r) => r.id), epoxyLaborIds: m0.tabs.Epoxy.labor.map((r) => r.id),
    savesOnOpen: b.rec.saves.length, bar: text(b, "bid-total"), maths: text(b, "maths"),
  };

  // ── 2. the estimator works Polish, then Epoxy; each section has its own takeoff and crew ──
  api.go(0);
  api.setAssembly(0, polishAsm.name);
  api.changed(true);
  api.go(1);
  const pl = api.model().labor.findIndex((r) => r.id === "polishing");
  P.typeInto(b, '[data-lab="' + pl + '"][data-k="guys"]', "3");
  P.typeInto(b, '[data-lab="' + pl + '"][data-k="days"]', "5");
  api.changed(true);
  P.clickEl(b, P.need(b, '[data-section-tab="Epoxy"]'));
  api.go(0);
  api.setAssembly(0, flake.name);
  api.setAssembly(1, cove.name);
  api.changed(true);
  api.go(1);
  const ep = api.model().labor.findIndex((r) => r.id === "epoxy-install");
  P.typeInto(b, '[data-lab="' + ep + '"][data-k="guys"]', "3");
  P.typeInto(b, '[data-lab="' + ep + '"][data-k="days"]', "9");
  api.changed(false);
  b.clock.fire();
  const saved = b.rec.saves[b.rec.saves.length - 1];
  const root = clone(saved.polish_estimate);
  const hand = byHand(root, undefined);
  const bids = api.sectionBids();
  const bar = Number(text(b, "bid-total").replace(/[^0-9]/g, ""));
  out.priced = {
    barNumber: bar, handCombined: hand.polish.total + hand.epoxy.total, handPolish: hand.polish.total, handEpoxy: hand.epoxy.total,
    pagePolish: api.bid().total, pageEpoxy: bids.Epoxy.total,
    lump: saved.proposal_lump_sum, computed: saved.computed_bid && saved.computed_bid.lump_sum,
    savedPolishTotals: root.totals && root.totals.total, savedEpoxyTotals: root.tabs.Epoxy.totals.total,
    maths: text(b, "maths"),
    taxes: [saved.proposal_sales_tax, saved.proposal_remodel_tax],
    handTaxes: [hand.polish.sales_tax + hand.epoxy.sales_tax, hand.polish.remodel_tax + hand.epoxy.remodel_tax],
    notPooled: hand.polish.total + hand.epoxy.total === hand.combined.total,
  };

  // ── 3. the save writes the proposal's keys for TWO base sections ──
  out.saved = {
    keys: Object.keys(saved).sort(),
    pricedTabs: (saved.priced_tabs || []).map((t) => [t.id, t.role, t.kind, t.v2, t.total, t.sf]),
    pricedTabsFull: clone(saved.priced_tabs || []),
    area: saved.sheet_area, polishSf: saved.polish_sf, polishSf2: saved.polish_2_sf,
    rootKind: root.kind === undefined ? "base" : root.kind, savedTabs: Object.keys(root.tabs),
    cost: saved.cost_snapshot, phase: saved.phase_price,
    taxable: [saved.proposal_taxable, saved.proposal_remodel_on],
  };

  // ── 4. the job's travel is charged once: on the Polish section, and not again on Epoxy ──
  const noTravel = byHand(clone(root), undefined);
  const m1 = api.model();             // the Epoxy view; its `travel` is the job's
  m1.travel.lodging.enabled = true; m1.travel.lodging.qty_auto = false; m1.travel.lodging.qty = 4; m1.travel.lodging.rate = 100;
  m1.travel.per_diem.enabled = true; m1.travel.per_diem.qty_auto = false; m1.travel.per_diem.qty = 4; m1.travel.per_diem.rate = 50;
  api.changed(false);
  b.clock.fire();
  const savedT = b.rec.saves[b.rec.saves.length - 1];
  const rootT = clone(savedT.polish_estimate);
  const handT = byHand(rootT, undefined);
  out.travel = {
    jobTravel: 600, polishTravel: api.bid().travel, epoxyTravel: api.sectionBids().Epoxy.travel,
    epoxyBefore: noTravel.epoxy.total, epoxyAfter: api.sectionBids().Epoxy.total,
    polishBefore: noTravel.polish.total, polishAfter: api.bid().total,
    lump: savedT.proposal_lump_sum, handLump: handT.polish.total + handT.epoxy.total,
    handLumpBefore: noTravel.polish.total + noTravel.epoxy.total,
  };
  // the Epoxy section's Labor step has no travel block, and its Review says where travel is charged
  api.go(1);
  const epoxyLabor = html(b, "panels");
  out.travel.epoxyLaborHasBlock = epoxyLabor.indexOf("data-trv-how") >= 0;
  out.travel.epoxyLaborNote = /data-travel-note>([^<]*)</.exec(epoxyLabor);
  out.travel.epoxyLaborNote = out.travel.epoxyLaborNote && out.travel.epoxyLaborNote[1];
  out.travel.epoxyLaborHasTravelRow = /data-lab="[0-9]+"[^>]*>\s*[^]*?Travel Labor/.test(epoxyLabor);
  api.go(2);
  const epoxyReview = html(b, "panels");
  out.travel.epoxyReviewNote = epoxyReview.indexOf("charged once for the whole job, on the Polish section") >= 0;
  out.travel.epoxyReviewHotelLines = /Hotel<\/td>/.test(epoxyReview);

  // ── 5. the Review step shows both sections and the combined total ──
  P.clickEl(b, P.need(b, '[data-section-tab="Polish"]'));
  api.go(2);
  const review = html(b, "panels");
  const card = /data-job-card>([^]*?)<\/table>/.exec(review);
  out.review = {
    hasCard: !!card, labels: card ? Array.from(card[1].matchAll(/<td>([^<]*)<\/td>/g)).map((m) => m[1]) : [],
    before: (/data-job-total>([^<]*)</.exec(review) || [])[1],
    polishFigure: (/data-job-sec="Polish">([^<]*)</.exec(review) || [])[1],
    epoxyFigure: (/data-job-sec="Epoxy">([^<]*)</.exec(review) || [])[1],
    // the card comes before the section's own cards
    cardFirst: review.indexOf("data-job-card") >= 0 && review.indexOf("data-job-card") < review.indexOf("Takeoff and Material"),
    hotelHasLodging: /Hotel<\/td>/.test(review),
  };
  // a figure typed on Review moves the card's figures live
  P.typeInto(b, "[data-contingency]", "1000");
  const nowHand = byHand(clone(api.model()), undefined);
  const live = (sel) => (b.doc.querySelector(sel) || { textContent: null }).textContent;
  out.review.afterContingency = {
    job: live("[data-job-total]"), polish: live('[data-job-sec="Polish"]'), epoxy: live('[data-job-sec="Epoxy"]'),
    handJob: money(nowHand.polish.total + nowHand.epoxy.total), handPolish: money(nowHand.polish.total), handEpoxy: money(nowHand.epoxy.total),
  };

  // ── 6. editing one section never touches the other's rows in what is saved ──
  const rootRowsBefore = clone(api.model().takeoff);
  P.clickEl(b, P.need(b, '[data-section-tab="Epoxy"]'));
  api.go(0);
  P.typeInto(b, '[data-tk="0"][data-k="measurement"]', "5500");
  b.clock.fire();
  const savedE = b.rec.saves[b.rec.saves.length - 1].polish_estimate;
  out.isolated = {
    rootTakeoff: savedE.takeoff.map((r) => [r.assembly_name, r.measurement]),
    rootBefore: rootRowsBefore.map((r) => [r.assembly_name, r.measurement]),
    epoxyMeasurement: savedE.tabs.Epoxy.takeoff[0].measurement,
    savedAreas: b.rec.saves[b.rec.saves.length - 1].sheet_area,
  };

  // ── 7. a saved combo bid opens as it was saved and writes nothing ──
  const reopen = await open(clone(b.store.blob));
  const reopenedHand = byHand(clone(b.store.blob.polish_estimate), undefined);
  out.reopened = {
    handBar: Math.round(reopenedHand.polish.total + reopenedHand.epoxy.total),
    saves: reopen.rec.saves.length, armed: reopen.clock.armed(), tabs: Object.keys(reopen.api.model().tabs || {}),
    strip: (html(reopen, "sections").match(/data-section-tab="([^"]*)"/g) || []),
    bar: text(reopen, "bid-total"),
  };

  // ── 8. a Polish job and an Epoxy job have no whole-bid card and read as they did ──
  const pol = await open(P.blob({ work_type: "polish" }));
  pol.api.go(2);
  const epx = await open(P.blob({ work_type: "epoxy", system_1_sf: 6000, cove_1_lf: 300,
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false } } }));
  epx.api.go(2);
  out.single = {
    polishCard: html(pol, "panels").indexOf("data-job-card") >= 0, epoxyCard: html(epx, "panels").indexOf("data-job-card") >= 0,
    polishHotel: /Hotel and Per Diem/.test(html(pol, "panels")),
    epoxyNote: html(epx, "panels").indexOf("charged once for the whole job") >= 0,
    polishTabs: pol.api.model().tabs === undefined ? "none" : Object.keys(pol.api.model().tabs),
  };
  epx.api.go(1);
  out.single.epoxyLaborHasTravelBlock = html(epx, "panels").indexOf("data-trv-how") >= 0;

  // ── 9. the model path: a combo job the model builds has both sections as bases and Polish still the carrier ──
  const m = B.sectionsForJob(B.freshModel(), "combo", {});
  out.model = {
    tabs: Object.keys(m.tabs || {}), kinds: B.sectionsOf(m).map((e) => [e.tab, e.kind]),
    carrier: B.travelCarrier(m), sameAgain: JSON.stringify(B.sectionsForJob(m, "combo", {})) === JSON.stringify(m),
    rootKindWritten: m.kind === undefined ? "none" : m.kind,
  };

  // ── 10. a SAVED job whose type is switched on the intake: the bid follows the job type ──
  // Each starting bid is a real saved one (worked on the page, then read back from the draft), so the switch is made on
  // what a draft holds. The rest of each fact is the page after it opened: the strip, the bar, the crew, the saves.
  const workedBid = async (workType, extra, fill) => {
    const w = await open(P.blob(Object.assign({ work_type: workType }, extra)));
    fill(w);
    w.api.changed(false);
    w.clock.fire();
    return clone(w.store.blob);
  };
  const crewOn = (w, id, guys, days) => {
    const at = w.api.model().labor.findIndex((r) => r.id === id);
    P.typeInto(w, '[data-lab="' + at + '"][data-k="guys"]', guys);
    P.typeInto(w, '[data-lab="' + at + '"][data-k="days"]', days);
  };
  const epoxyDraft = await workedBid("epoxy", { system_1_sf: 6000, cove_1_lf: 300,
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false, dye: false, joint_filler: false, remove_existing_jf: false } } },
  (w) => { w.api.go(0); w.api.setAssembly(0, flake.name); w.api.setAssembly(1, cove.name); w.api.changed(true); w.api.go(1); crewOn(w, "epoxy-install", "3", "9"); });
  const polishDraft = await workedBid("polish", { polish_sf: 10000,
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false, dye: false, joint_filler: false, remove_existing_jf: false } } },
  (w) => { w.api.go(0); w.api.setAssembly(0, polishAsm.name); w.api.changed(true); w.api.go(1); crewOn(w, "polishing", "3", "5"); });
  const comboDraftSaved = clone(b.store.blob);

  const snap = (w) => {
    const m = w.api.model();
    const last = w.rec.saves.length ? w.rec.saves[w.rec.saves.length - 1] : null;
    const shown = last ? clone(last.polish_estimate) : clone(m);
    return {
      bar: text(w, "bid-total"), strip: (html(w, "sections").match(/data-section-tab="([^"]*)"/g) || []),
      kinds: B.sectionsOf(m).map((e) => [e.tab, e.kind]), saves: w.rec.saves.length,
      handBar: money((() => { const h = byHand(shown, undefined); return B.activeSections(shown).reduce((t, e) => t + (e.root ? h.polish.total : h.epoxy.total), 0); })()),
      epoxyLabor: m.tabs && m.tabs.Epoxy ? m.tabs.Epoxy.labor.map((r) => r.id) : null,
      epoxyTakeoff: m.tabs && m.tabs.Epoxy ? clone(m.tabs.Epoxy.takeoff).map((r) => [r.measurement, r.unit]) : null,
      savedPricedTabs: last ? (last.priced_tabs || []).map((t) => [t.id, t.kind]) : null,
      savedLump: last ? last.proposal_lump_sum : null,
    };
  };
  const switched = async (draft, to) => {
    const w = await open(Object.assign(clone(draft), to));
    const before = snap(w);   // what is on screen the moment it opens
    w.clock.fire();           // and what the one save the switch arms writes
    return { w: w, got: Object.assign(snap(w), { barOnOpen: before.bar, savesOnOpen: before.saves }) };
  };
  const toCombo = Object.assign({ work_type: "combo", polish_sf: 10000, system_1_sf: 6000, cove_1_lf: 300 });
  const eToC = await switched(epoxyDraft, toCombo);
  const pToC = await switched(polishDraft, toCombo);
  const cToP = await switched(comboDraftSaved, { work_type: "polish" });
  // the switched bid is the one saved: reopening it writes nothing, and a second switch back and forth keeps the rows
  const eToCReopen = await open(clone(eToC.w.store.blob));
  const cToPBack = await switched(clone(cToP.w.store.blob), { work_type: "combo" });
  out.switched = {
    epoxyToCombo: eToC.got, polishToCombo: pToC.got, comboToPolish: cToP.got,
    epoxyToComboReopen: { saves: eToCReopen.rec.saves.length, armed: eToCReopen.clock.armed(), kinds: B.sectionsOf(eToCReopen.api.model()).map((e) => [e.tab, e.kind]) },
    comboToPolishAndBack: { kinds: cToPBack.got.kinds, bar: cToPBack.got.bar, epoxyTakeoff: cToPBack.got.epoxyTakeoff },
    comboBefore: text(b, "bid-total"),
    polishBase: B.activeSections(polishDraft.polish_estimate).length, epoxyBase: B.activeSections(epoxyDraft.polish_estimate).length,
  };
  // the model path: switching does not lose rows, and a polish job with no other section is left exactly as it was
  const mEpoxy = B.sectionsForJob(B.freshModel(), "epoxy", {});
  const mCombo = B.sectionsForJob(mEpoxy, "combo", {});
  const mPolish = B.sectionsForJob(mCombo, "polish", {});
  const plain = B.freshModel();
  out.switchModel = {
    epoxyToCombo: B.sectionsOf(mCombo).map((e) => [e.tab, e.kind]), carrier: B.travelCarrier(mCombo),
    comboToPolish: B.sectionsOf(mPolish).map((e) => [e.tab, e.kind]), rowsKept: !!mPolish.tabs.Epoxy && mPolish.tabs.Epoxy.takeoff.length === mCombo.tabs.Epoxy.takeoff.length,
    rootKindAfterCombo: mCombo.kind === undefined ? "none" : mCombo.kind,
    plainPolishUnchanged: B.sectionsForJob(plain, "polish", {}) === plain,
    toAdd: [B.sectionsToAdd(plain, "combo"), B.sectionsToAdd(mCombo, "combo"), B.sectionsToAdd(plain, "polish"), B.sectionsToAdd(plain, "gyp")],
  };
  return out;
}

main().then((out) => console.log(JSON.stringify(out))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
