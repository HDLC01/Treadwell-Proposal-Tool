"use strict";
/* A GYP JOB ON THE REAL ESTIMATE PAGE: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it,
 * on the library backend/ops/seed_library_from_workbook.py plans.
 *
 * Phase 14 of the v2 estimating program. A v2 Gyp job is a Gyp SECTION of the bid with the Polish root marked off, filed
 * under the workbook tab of the preset the estimator chose, and the page's Material, Labor and Review panels edit it.
 * Every fact below is read off the page after it ran: the model it held, the panels it drew, what it saved. Nothing is a
 * source assertion. The price it shows is set beside the same job priced by hand with no page in it.
 *
 * Usage: node gyp-page-harness.js <frontend-dir> <plan.json>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
const LIB = require(path.join(ROOT, "js", "library-core.js"));
const G = require(path.join(ROOT, "js", "gyp-takeoff.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in gyp-page-harness.js");
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
const FIRST = 'Gyp (USG 1-8")';
const FR = "Gyp (FR)";

const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
  default_work_types: [], default_on: true };
const laborRows = [TRAVEL_ROW].concat(plan.labor.map((r) => Object.assign({}, r, { default_on: true, owner_email: "kyle@wetreadwell.com" })));
const calcRows = plan.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));

/** A draft the way the v2 intake leaves it for a Gyp job: the answers it asks and the three areas it asked. */
function gypDraft(extra) {
  return P.blob(Object.assign({
    work_type: "gyp", gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000,
    polish_estimate: { version: 2, conditions: { taxable: true, prevailing_wage: false, remodel_tax: false } },
  }, extra || {}));
}

const flush = () => new Promise((r) => setImmediate(r));
const text = (built, id) => built.doc.getElementById(id).textContent;
const html = (built, id) => built.doc.getElementById(id).innerHTML;
const money = (s) => Number(String(s).replace(/[^0-9]/g, ""));

/** The same job priced without the page: a section built by hand, the engine and the library, nothing of the page in it. */
function priceByHand(tab, rows, settings, labor, over) {
  const o = over || {};
  const m = B.activateSection(Object.assign({}, B.freshModel(), { kind: "off" }), tab, "base", {});
  m.conditions = Object.assign({}, m.conditions, { taxable: true, prevailing_wage: false, remodel_tax: false }, o.conditions || {});
  m.tabs[tab].takeoff = rows;
  m.tabs[tab].gyp = settings;
  m.tabs[tab].labor = labor;
  if (o.travel) m.travel = o.travel;
  return B.priceSection(m, tab, {
    material: (e) => G.sectionMaterial(e.section.takeoff, e.section.gyp, e.tab, {
      items: items,
      rowPrice: (row) => { const a = asms.find((x) => x.id === row.assembly_id); return a ? LIB.priceAssembly(a, items, B.num(row.measurement)) : null; },
    }),
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

  // ── 1. a new Gyp job opens as a Gyp section on the base sheet, seeded from the intake's three boxes ──
  const b = await open(gypDraft());
  const m0 = b.api.model();
  out.opened = {
    tabs: Object.keys(m0.tabs || {}), rootKind: m0.kind, kind: m0.tabs && m0.tabs[FIRST] && m0.tabs[FIRST].kind,
    takeoff: m0.takeoff.map((r) => [r.assembly_name, r.measurement, r.unit, r.bucket]),
    laborIds: m0.labor.map((r) => r.id), laborUnits: m0.labor.map((r) => r.unit), laborGuys: m0.labor.map((r) => r.guys),
    laborRates: m0.labor.map((r) => r.rate),
    // The Sheets panel (Sheets phase 3) is drawn on every bid; the strip of tabs has its one tab.
    strip: {
             tabs: (b.doc.getElementById("sheets-panel").innerHTML.match(/data-section-tab="([^"]*)"/g) || []) },
    card: html(b, "panels").indexOf("data-gyp-card") >= 0,
    cardSheets: (html(b, "panels").match(/<option value="Gyp[^"]*"/g) || []).length,
    placeholders: (html(b, "panels").match(/data-gyp="thickness\.[a-z]+"[^>]*placeholder="([^"]*)"/g) || []).length,
    panelHasPolishCards: /Dye|Joint filler/.test(html(b, "panels")),
    hasPatch: html(b, "panels").indexOf("data-epoxy-patch") >= 0,
    savesOnOpen: b.rec.saves.length,
    gypSettings: m0.tabs[FIRST].gyp === undefined ? "none" : m0.tabs[FIRST].gyp,
  };

  // ── 2. the page's price is the price by hand, and what the save writes ──
  const api = b.api;
  b.clock.fire();
  const sec = () => api.model();
  const rows1 = clone(sec().takeoff);
  // a crew typed on the labor step: the pour, 8 guys for 6 hours, and the prep, 8 for 4
  api.go(1);
  const idx = (id) => api.model().labor.findIndex((r) => r.id === id);
  P.typeInto(b, '[data-lab="' + idx("gyp-pour") + '"][data-k="guys"]', "8");
  P.typeInto(b, '[data-lab="' + idx("gyp-pour") + '"][data-k="days"]', "6");
  P.typeInto(b, '[data-lab="' + idx("gyp-prep") + '"][data-k="guys"]', "8");
  P.typeInto(b, '[data-lab="' + idx("gyp-prep") + '"][data-k="days"]', "4");
  api.changed(false);
  b.clock.fire();
  const labor1 = clone(api.model().labor);
  const byHand = priceByHand(FIRST, rows1, {}, labor1, { travel: clone(api.model().travel) });
  const saved = b.rec.saves[b.rec.saves.length - 1];
  const stamp = saved.polish_estimate.tabs[FIRST];
  out.priced = {
    barNumber: money(text(b, "bid-total")), byHand: byHand.total, pageBid: api.activeBid().total,
    handMaterial: byHand.material, pageMaterial: api.activeBid().material,
    handTooling: byHand.tooling, pageTooling: api.activeBid().tooling,
    shippingByHand: byHand.shipping, pageShipping: api.activeBid().shipping,
    escalationByHand: byHand.escalation, pageEscalation: api.activeBid().escalation,
    savedKeys: Object.keys(saved).sort(),
    pricedTabs: (saved.priced_tabs || []).map((t) => [t.id, t.role, t.kind, t.v2, t.total, t.system_desc, t.sf]),
    pricedTabsFull: clone(saved.priced_tabs || []),
    lump: saved.proposal_lump_sum, computed: saved.computed_bid && saved.computed_bid.lump_sum,
    sheetArea: saved.sheet_area, rootKind: saved.polish_estimate.kind, savedTabs: Object.keys(saved.polish_estimate.tabs || {}),
    stampTotal: stamp.totals.total, stampProfile: stamp.profile,
    laborSaved: stamp.labor.map((r) => [r.id, r.guys, r.days, r.unit]),
    inert: (html(b, "panels").match(/class="tk lab[^"]*inert[^"]*"/g) || []).length,
    caption: (html(b, "panels").match(/data-gyp-hours[^>]*>([^<]*)/) || [])[1] || null,
  };

  // ── 3. the Material step: the card, the caption and the bags, in the page's own words ──
  api.go(0);
  out.material = {
    card: html(b, "panels").indexOf("data-gyp-card") >= 0,
    caption: (html(b, "panels").match(/data-gyp-cap[^>]*>([\s\S]*?)<\/p>/) || [])[1] || null,
    truck: (html(b, "panels").match(/data-gyp-truck[^>]*>([^<]*)/) || [])[1] || null,
    rowCosts: (html(b, "panels").match(/data-cost-for="\d+">([^<]*)</g) || []),
    materialTotal: (html(b, "panels").match(/data-mat-total>([^<]*)</) || [])[1],
  };

  // ── 4. a thickness typed in an area box reprices live and is kept on the section, and a blank goes back to the sheet's ──
  const before = api.activeBid().total;
  P.typeInto(b, '[data-gyp="thickness.soft"]', "1.5");
  const afterThick = api.activeBid().total;
  const withThick = priceByHand(FIRST, clone(api.model().takeoff), { thickness: { soft: "1.5" } }, clone(api.model().labor), { travel: clone(api.model().travel) });
  const keptSettings = clone(api.model().tabs[FIRST].gyp);
  P.typeInto(b, '[data-gyp="thickness.soft"]', "");
  out.thickness = { before: before, after: afterThick, byHand: withThick.total, kept: keptSettings, backToBefore: api.activeBid().total,
    bar: money(text(b, "bid-total")) };

  // ── 5. the mix, the sound mat and ISO strip at all areas each reprice the way the hand-priced job does ──
  P.changeTo(b, '[data-gyp="mix"]', "1.4");
  const mix14 = api.activeBid().total;
  const mixHand = priceByHand(FIRST, clone(api.model().takeoff), { mix: 1.4 }, clone(api.model().labor), { travel: clone(api.model().travel) });
  P.changeTo(b, '[data-gyp="mix"]', "1.8");
  P.changeTo(b, '[data-gyp="sound_mat"]', "wb-gyp-sound-mat-sc-190-1-8in-roll");
  const matGrass = api.activeBid().total;
  const matHand = priceByHand(FIRST, clone(api.model().takeoff), { sound_mat: "wb-gyp-sound-mat-sc-190-1-8in-roll" }, clone(api.model().labor), { travel: clone(api.model().travel) });
  P.changeTo(b, '[data-gyp="sound_mat"]', "wb-gyp-sound-mat-sam-n12-1-8in-roll");
  P.clickOn(b, "[data-gyp-iso]");
  const iso = api.activeBid().total;
  const isoHand = priceByHand(FIRST, clone(api.model().takeoff), { iso_all: true }, clone(api.model().labor), { travel: clone(api.model().travel) });
  P.clickOn(b, "[data-gyp-iso]");
  P.typeInto(b, '[data-gyp="moisture_tests"]', "5");
  const moist = api.activeBid();
  const moistHand = priceByHand(FIRST, clone(api.model().takeoff), { moisture_tests: "5" }, clone(api.model().labor), { travel: clone(api.model().travel) });
  P.typeInto(b, '[data-gyp="moisture_tests"]', "");
  out.settings = {
    mix: [mix14, mixHand.total, mix14 !== before], mat: [matGrass, matHand.total, matGrass !== before],
    iso: [iso, isoHand.total, iso !== before], moisture: [moist.total, moistHand.total, moist.tooling, moistHand.tooling],
    after: api.activeBid().total, restored: api.activeBid().total === before, settings: clone(api.model().tabs[FIRST].gyp),
  };

  // ── 6. the sheet (preset) moves the section to another workbook tab: the key, the bag, the primer, the mat, the truckload ──
  P.changeTo(b, '[data-gyp="preset"]', FR);
  const frModel = api.model();
  const frGyp = (frModel.tabs && frModel.tabs[FR] && frModel.tabs[FR].gyp) || {};
  const frHand = priceByHand(FR, clone(frModel.takeoff), clone(frGyp), clone(frModel.labor), { travel: clone(frModel.travel) });
  b.clock.fire();
  const frSaved = b.rec.saves[b.rec.saves.length - 1];
  out.preset = {
    tabs: Object.keys(frSaved.polish_estimate.tabs || {}), bid: api.activeBid().total, byHand: frHand.total, bar: money(text(b, "bid-total")),
    pricedTabs: (frSaved.priced_tabs || []).map((t) => [t.id, t.role, t.kind, t.system_desc]),
    stamp: frSaved.polish_estimate.tabs[FR] && frSaved.polish_estimate.tabs[FR].profile,
    rowsKept: clone(api.model().takeoff).map((r) => [r.measurement, r.bucket]),
    laborKept: api.model().labor.filter((r) => r.guys !== "").map((r) => [r.id, r.guys, r.days]),
    truckload: G.matFigures(items, FR, G.matIdOf(FR, frGyp)).truckload,
    cardSelected: (html(b, "panels").match(/<option value="Gyp \(FR\)" selected/g) || []).length,
    matOptions: (html(b, "panels").match(/<option value="wb-gyp-[^"]*"/g) || []).length,
  };
  P.changeTo(b, '[data-gyp="preset"]', FIRST);
  b.clock.fire();
  const backSaved = b.rec.saves[b.rec.saves.length - 1];
  out.preset.back = { tabs: Object.keys(backSaved.polish_estimate.tabs || {}), bid: api.activeBid().total, restored: api.activeBid().total === before,
    priced: (backSaved.priced_tabs || []).map((t) => t.id) };

  // ── 7. the Review step: the Gyp lines, the escalation that is always on, the material escalation row ──
  api.go(2);
  const review = html(b, "panels");
  out.review = {
    hasLines: ["Primer", "Sand", "Sound mat"].map((w) => review.indexOf(">" + w + "<") >= 0),
    escalationLabel: review.indexOf("Labor escalation (always on for Gyp)") >= 0,
    noPrevailingSwitch: review.indexOf('data-cond="prevailing_wage"') < 0,
    materialEscalationRow: review.indexOf('data-mk="material_escalation"') >= 0,
    shippingNoRate: /Shipping<\/td><td class="q r"><\/td><td class="u"><\/td><td class="rt r"><\/td>/.test(review),
    tooling: review.indexOf("Tooling and consumables") >= 0,
    total: (/data-mk="total">([^<]*)</.exec(review) || [])[1],
    noDye: !/Dye/.test(review),
  };

  // ── 8. a thickness that cannot be worked out is NO PRICE, in the page's words, never a bid on the part that could be ──
  api.go(0);
  P.typeInto(b, '[data-gyp="thickness.hard"]', "0");
  const bad = api.activeBid();
  out.noPrice = { priceable: bad.priceable, line: bad.line, reason: bad.reason, bar: text(b, "bid-total"),
    caption: b.doc.querySelector("[data-gyp-cap]").innerHTML };
  P.typeInto(b, '[data-gyp="thickness.hard"]', "");

  // ── 9. an area row picked from the pop-up carries its area; a Gyp bid with a Polish assembly row treats it as an extra ──
  const area = asms.find((a) => a.id === G.AREA_ASSEMBLIES.corridor.id);
  const g2 = await open(gypDraft({ gyp_soft_sf: 4000, gyp_hard_sf: "", gyp_corridor_sf: "" }));
  g2.api.addPickedTakeoffRow({ kind: "asm", id: area.id, name: area.name });
  const added = g2.api.model().takeoff[g2.api.model().takeoff.length - 1];
  out.picked = { bucket: added.bucket, id: added.assembly_id, unit: added.unit, rows: g2.api.model().takeoff.map((r) => r.bucket) };
  g2.api.setAssembly(g2.api.model().takeoff.length - 1, asms.find((a) => a.id === G.AREA_ASSEMBLIES.hard.id).name);
  out.picked.afterRename = g2.api.model().takeoff[g2.api.model().takeoff.length - 1].bucket;

  // ── 10. a saved Gyp bid opens as it was saved and writes nothing ──
  const reopen = await open(clone(b.store.blob));
  out.reopened = {
    saves: reopen.rec.saves.length, armed: reopen.clock.armed(), total: reopen.api.activeBid().total,
    tabs: Object.keys(reopen.api.model().tabs || {}), takeoffRows: reopen.api.model().takeoff.length,
    card: html(reopen, "panels").indexOf("data-gyp-card") >= 0,
  };

  // ── 11. a Polish job is untouched: no card, no section, the root priced as it always was ──
  const pol = await open(P.blob({ work_type: "polish" }));
  out.polish = {
    tabs: pol.api.model().tabs === undefined ? "none" : Object.keys(pol.api.model().tabs),
    card: html(pol, "panels").indexOf("data-gyp-card") >= 0, bid: pol.api.bid().total,
  };

  // ── 12. a Gyp area assembly picked into a POLISH bid is priced as any assembly is (no Gyp section to price it against) ──
  const pa = await open(P.blob({ work_type: "polish" }));
  pa.api.addPickedTakeoffRow({ kind: "asm", id: area.id, name: area.name });
  const pRow = pa.api.model().takeoff[pa.api.model().takeoff.length - 1];
  pRow.measurement = "1000";
  const viaPage = pa.api.rowPrice(pRow, pa.api.model().takeoff);
  const viaLib = LIB.priceAssembly(area, items, 1000);
  out.polishWithArea = { areaFlag: viaPage.area === undefined ? "none" : viaPage.area, lines: [viaPage.priced_lines, viaPage.broken_lines],
    libLines: [viaLib.priced_lines, viaLib.broken_lines], total: [viaPage.total, viaLib.total] };
  const gypRow = b.api.model().takeoff[0];
  out.polishWithArea.gypFlag = (b.api.rowPrice(gypRow, b.api.model().takeoff) || {}).area;

  // ── 13. a Gyp job whose intake typed no area opens with the one blank row, and no price yet ──
  const empty = await open(gypDraft({ gyp_soft_sf: "", gyp_hard_sf: "", gyp_corridor_sf: "" }));
  out.empty = { rows: empty.api.model().takeoff.map((r) => [r.assembly_id, r.measurement]), bar: text(empty, "bid-total") };

  // ── 14. the labor rows are ordinary crew lines priced by the hour: not dimmed, no drive-time words ──
  const labPanel = (() => { api.go(1); return html(b, "panels"); })();
  out.laborCards = {
    pourHint: labPanel.indexOf("Hours on the job.") >= 0, driveHint: (labPanel.match(/Drive time, each way counted\./g) || []).length,
    hourCards: (labPanel.match(/data-lab-card="\d+"/g) || []).length,
  };
  return out;
}

main().then((out) => console.log(JSON.stringify(out))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
