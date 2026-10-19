"use strict";
/* A SEAL OPTION ON THE REAL ESTIMATE PAGE: js/polish-estimate.js, whole, booted the way combo-page-harness.js boots it, on the
 * Seal library backend/ops/seed_library_from_workbook.py plans and a small Polish library of its own.
 *
 * Phase 15 of the v2 estimating program. "+ Add option" offers Seal and Seal (+Jnts); an option is a section of the bid
 * with kind "option", priced on its own profile through the engine, never added into the lump sum, shown on Review as its
 * own card, and written into the save as a priced tab (role seal, kind option) with the draft's tab_opts saying it is an
 * option, which is what the proposal side prints under Options & Unit Prices. Every fact below is read off the page after it
 * ran: the model it held, the panels it drew, what it saved. Nothing is a source assertion, and every price is set beside
 * the same option priced by hand with no page in it.
 *
 * Usage: node seal-page-harness.js <frontend-dir> <plan.json>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
const LIB = require(path.join(ROOT, "js", "library-core.js"));
const SL = require(path.join(ROOT, "js", "seal-takeoff.js"));
const X = require(path.join(ROOT, "js", "epoxy-takeoff.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in seal-page-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "need", "MODEL"]);

// ── the library: the Seal rows the seed plans, a small Polish library, and a crew for each ──
const POLISH_ITEMS = [
  { id: "sl-i1", name: "Seal-page OPF", unit: "Gal", buy_qty: 1, unit_cost: 85.3827, coverage: 275, default_work_types: ["polish"] },
];
const POLISH_ASMS = [
  { id: "sl-a1", name: "Seal-page Polish 800 Grit", unit: "SF", default_work_types: ["polish"], lines: [
    { item_id: "sl-i1", coverage: 275, waste_pct: 5, roundup: true }] },
];
const asms = plan.assemblies.concat(POLISH_ASMS);
const items = plan.items.concat(POLISH_ITEMS);
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
  default_work_types: [], default_on: true };
const POLISH_CREW = { id: "polishing", name: "Polishing", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true,
  default_work_types: ["polish"], default_on: true };
const laborRows = [TRAVEL_ROW, POLISH_CREW].concat(plan.labor.map((r) => Object.assign({}, r, { default_on: true })));
const calcRows = plan.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));
const asmNamed = (n) => asms.find((a) => a.name === n);
const polishAsm = asmNamed("Seal-page Polish 800 Grit");

const OFF = { taxable: true, prevailing_wage: false, remodel_tax: false, dye: false, joint_filler: false, remove_existing_jf: false };
function polishDraft(extra) {
  return P.blob(Object.assign({
    work_type: "polish", polish_sf: 10000, polish_2_sf: "",
    polish_estimate: { version: 2, conditions: Object.assign({}, OFF) },
  }, extra || {}));
}

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 12; i++) await flush(); };
const html = (b, id) => b.doc.getElementById(id).innerHTML;
const text = (b, id) => b.doc.getElementById(id).textContent;
const money = (n) => "$" + Math.round(n).toLocaleString("en-US");

async function open(draft, extra) {
  const b = P.build(Object.assign({ blob: draft, asms: asms, items: items, labor: laborRows, laborCalc: calcRows }, extra || {}));
  await b.api.init();
  await settle();
  return b;
}

const rowPriceOf = (row) => {
  const a = asms.find((x) => x.id === row.assembly_id);
  return a ? LIB.priceAssembly(a, items, B.num(row.measurement)) : null;
};

/** The Seal option priced WITHOUT THE PAGE: priceSection with the seal takeoff's own material, from the saved model. */
function sealByHand(model, tab, reno) {
  return B.priceSection(model, tab, {
    material: (e) => {
      const r = SL.sectionMaterial(e.section.takeoff, {
        items: items, sf: B.takeoffSf(e.section.takeoff), reno: !!reno, rowPrice: (row) => rowPriceOf(row),
      });
      return { material: r.material, tooling: r.tooling };
    },
  });
}

/** The Polish root priced without the page. */
function polishByHand(model, reno) {
  const alone = model.takeoff.map((r) => (B.rowOn(r) ? rowPriceOf(r) : null));
  const bought = B.poolsPacks(model) ? LIB.pricePool(alone, { on: model.takeoff.map((r) => B.rowOn(r)) }) : alone;
  // A NEW bid's Polish root is polish-rev3 (2026-10-16), whose chain takes the sheet's patch line (D17): the Seal module's
  // patchCost over the same library, at the New rate unless the job answers Reno (these drafts answer neither, as the page reads it).
  const patch = B.polishPatchOn(model, B.ROOT_TAB) ? SL.patchCost(items, B.takeoffSf(model.takeoff), !!reno) : 0;
  return B.markupChain({
    material: bought.reduce((t, p) => t + (p ? p.total : 0), 0), patch: patch, labor: B.laborTotal(model.labor, model.conditions),
    travel: B.travelCosts(model.travel, model.labor, B.travelOpts(model, "Polish")).total,
    tooling: B.rootTooling(model), contingency: model.contingency, fees: model.fees,
    conditions: model.conditions, sf: B.takeoffSf(model.takeoff),
  }, B.rootProfile(model).stamp);
}

const last = (l) => l[l.length - 1];
const crewOn = (w, id, guys, days) => {
  const at = w.api.model().labor.findIndex((r) => r.id === id);
  P.typeInto(w, '[data-lab="' + at + '"][data-k="guys"]', guys);
  P.typeInto(w, '[data-lab="' + at + '"][data-k="days"]', days);
};
const tabsIn = (h) => (h.match(/data-section-tab="([^"]*)"/g) || []).map((s) => /"([^"]*)"/.exec(s)[1]);
// THE SHEETS PANEL (Sheets phase 3) replaced the strip of section buttons and the "+ Add option" bar. The choices in its "Add sheet" menu
// carry data-sh-sheet (every sheet the tool prices, not only the options), a sheet's own Delete button is on its row once that row is
// open, and the panel is drawn on every bid, so what hides for one sheet is the "Open sheet" line.
const addButtons = (h) => (h.match(/data-sh-sheet="([^"]*)"/g) || []).map((s) => /"([^"]*)"/.exec(s)[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&"));
const deleteSel = (tab) => '[data-sh-act="delete"][data-sh-tab="' + tab + '"]';
const openSheet = (b, tab) => P.clickEl(b, P.need(b, '[data-section-tab="' + tab + '"]'));
const openTab = (h) => ((/data-section-tab="([^"]*)"[^>]*aria-current="true"/.exec(h)) || [])[1] || null;
const pressAdd = (b, sheet) => {
  P.clickEl(b, P.need(b, '[data-sh-act="add-menu"]'));
  return P.clickEl(b, P.need(b, '[data-sh-act="add"][data-sh-sheet="' + sheet + '"]'));
};

async function main() {
  const out = {};

  // ── 1. a bid with no option: the strip hides itself, "+ Add option" is there, nothing is saved by opening ──
  const b = await open(polishDraft());
  const api = b.api;
  api.go(0);
  api.setAssembly(0, polishAsm.name);
  api.changed(true);
  api.go(1);
  crewOn(b, "polishing", "3", "5");
  api.changed(false);
  b.clock.fire();
  const savesBeforeOption = b.rec.saves.length;
  const baseLump = api.bid().total;
  out.fresh = {
    rows: tabsIn(html(b, "sheets-panel")),
    addButton: P.need(b, '[data-sh-act="add-menu"]').textContent,
    choicesShown: addButtons(html(b, "sheets-panel")), baseLump: baseLump,
    noTabsKey: api.model().tabs === undefined,
  };
  // the same page opened and left alone writes nothing
  const quiet = await open(polishDraft());
  out.fresh.savesOnOpen = quiet.rec.saves.length; out.fresh.armedOnOpen = quiet.clock.armed();

  // ── 2. "+ Add option" offers the two Seal sheets; choosing one adds a seeded option section ──
  P.clickEl(b, P.need(b, '[data-sh-act="add-menu"]'));
  const menuHtml = html(b, "sheets-panel");
  out.menu = { choices: addButtons(menuHtml), hasClose: /aria-label="Close" data-sh-act="add-close"/.test(menuHtml),
               onlyOptionsAreTaggedSo: (menuHtml.match(/<span class="pill">Option only<\/span>/g) || []).length,
               levelingComing: /disabled><span>Leveling<\/span><span class="pill">Coming<\/span>/.test(menuHtml),
               gypLabel: (/data-sh-sheet="Gyp[^"]*"[^>]*><span>([^<]*)</.exec(menuHtml) || [])[1] };
  P.clickEl(b, P.need(b, '[data-sh-act="add"][data-sh-sheet="Seal"]'));
  await settle();
  const m1 = api.model();
  const tabs1 = b.api.model();
  const ROOTM = (() => { api.show("Polish"); return api.model(); })();
  const sealSec = ROOTM.tabs.Seal;
  out.added = {
    tabs: Object.keys(ROOTM.tabs), kind: sealSec.kind, layout: sealSec.layout, profile: sealSec.profile,
    snapshot: sealSec.rates && sealSec.rates.profile, pooled: sealSec.pool_packs === true,
    takeoff: sealSec.takeoff.map((r) => [r.assembly_id, r.measurement, r.unit]),
    laborIds: sealSec.labor.map((r) => r.id), noTravelRow: !sealSec.labor.some((r) => r.id === "travel"),
    strip: tabsIn(html(b, "sheets-panel")),
    activeIsSeal: openTab(html(b, "sheets-panel")) === "Seal",
    // what the open sheet's bar (row 2 under the tabs) says: it was the "Open sheet" line above the step rail
    // (the bar ends at the line under it, the note about copies or the one-sheet hint, or at the end of the markup: the legend line that
    // used to stand under every bar is gone, so a missing marker is not an index of -1 to slice by)
    stripLabel: (() => { const h = html(b, "sheets-panel"); const o = h.indexOf('class="sh-open"'); const ends = ['<p class="sh-hint"', '<p class="sh-empty"'].map((s) => h.indexOf(s, o)).filter((i) => i >= 0); return o < 0 ? "" : h.slice(o, ends.length ? Math.min.apply(null, ends) : h.length).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim(); })(),
    barAfter: { choices: addButtons(html(b, "sheets-panel")), menuClosed: /data-sh-act="add-menu"[^>]*aria-expanded="false"/.test(html(b, "sheets-panel")) },
    saved: b.clock.armed() > 0,
  };
  // the page now shows the Seal section; its panels are the ordinary takeoff and labor panels
  api.show("Seal");
  api.go(0);
  out.added.materialPanel = {
    hasPatchCaption: html(b, "panels").indexOf("data-seal-patch") >= 0, hasRow: html(b, "panels").indexOf("Seal, 2 coats") >= 0,
    noDyeCard: html(b, "panels").indexOf("data-cond=") < 0,
  };
  api.go(1);
  out.added.laborPanel = { noTravelBlock: html(b, "panels").indexOf("data-trv-how") < 0,
    note: /data-travel-note>([^<]*)</.test(html(b, "panels")) ? /data-travel-note>([^<]*)</.exec(html(b, "panels"))[1] : null };

  // ── 3. the option is priced on its own, and the lump sum is the base alone ──
  crewOn(b, "seal-install", "3", "2");
  api.changed(false);
  b.clock.fire();
  const saved = last(b.rec.saves);
  const root = clone(saved.polish_estimate);
  const handSeal = sealByHand(root, "Seal", false);
  const handPolish = polishByHand(root);
  const bids = api.sectionBids();
  const barText = text(b, "bid-total");
  out.priced = {
    pageSeal: bids.Seal.total, handSeal: handSeal.total, pagePolish: api.bid().total, handPolish: handPolish.total,
    baseLumpBefore: baseLump, lump: saved.proposal_lump_sum, computed: saved.computed_bid && saved.computed_bid.lump_sum,
    sealTotals: root.tabs.Seal.totals.total, bar: Number(barText.replace(/[^0-9]/g, "")),
    maths: text(b, "maths"), taxes: [saved.proposal_sales_tax, saved.proposal_remodel_tax],
    handPolishTaxes: [handPolish.sales_tax, handPolish.remodel_tax], material: bids.Seal.material, tooling: bids.Seal.tooling,
    sealIsPriceable: bids.Seal.priceable !== false,
  };

  // ── 4. the save: a priced tab for the option, the proposal's option switch, and nothing added to the area ──
  out.saved = {
    keys: Object.keys(saved).sort(),
    pricedTabs: (saved.priced_tabs || []).map((t) => [t.id, t.role, t.kind, t.v2, t.total, t.sales_tax, t.remodel, t.system_desc]),
    pricedTabsFull: clone(saved.priced_tabs || []),
    tabOpts: clone(saved.tab_opts), area: saved.sheet_area, polishSf: saved.polish_sf,
    cost: saved.cost_snapshot, taxable: [saved.proposal_taxable, saved.proposal_remodel_on],
    sealArea: (saved.priced_tabs || []).filter((t) => t.id === "Seal").map((t) => t.sf)[0],
  };

  // ── 5. the Review step: the option's own card, in its own colour, with its own total, said not to be in the lump sum ──
  api.show("Polish");
  api.go(2);
  const review = html(b, "panels");
  // REVIEW SHOWS ONE SHEET (Hanz, 2026-10-19): with Polish open it is Polish's own cards; the Seal option has no card of its own here.
  out.review = {
    noOptionCard: review.indexOf("data-option-card") < 0 && review.indexOf("Seal option") < 0 && review.indexOf("data-opt-sec") < 0,
    handFigure: money(handSeal.total),
    noWholeBidCard: review.indexOf("data-job-card") < 0,
    keys: Array.from(review.matchAll(/data-rev="([a-z]+)"/g)).map((m) => m[1]),
    markupTotal: (/data-mk="total">([^<]*)</.exec(review) || [])[1],
    noteOnBase: review.indexOf("data-option-note") >= 0,
  };
  api.show("Seal");
  api.go(2);
  const sealReview = html(b, "panels");
  out.review.onSeal = {
    note: /data-option-note><b>([^<]*)<\/b>/.exec(sealReview) ? /data-option-note><b>([^<]*)<\/b>/.exec(sealReview)[1] : null,
    markupTotal: (/data-mk="total">([^<]*)</.exec(sealReview) || [])[1], toolingCard: sealReview.indexOf("Tooling and consumables") >= 0,
    noOptionCard: sealReview.indexOf("data-option-card") < 0, noteFirst: sealReview.indexOf("data-option-note") >= 0 && sealReview.indexOf("data-option-note") < sealReview.indexOf("Takeoff and Material"),
  };
  // a figure typed on Review moves the option card live
  api.show("Polish");
  api.go(2);
  P.typeInto(b, "[data-contingency]", "1000");
  const nowRoot = clone(api.model());
  out.review.live = {
    base: money(polishByHand(nowRoot).total), baseOnPage: (b.doc.querySelector('[data-mk="total"]') || { textContent: null }).textContent,
  };

  // ── 6. what the Proposal step set on the option survives the next save of this page ──
  b.store.blob.tab_opts = { Seal: { show_system: true, show_diff: false, is_option: true, show: false, price_mode: "deduct", desc: "My own words" } };
  api.show("Seal");
  api.go(1);
  crewOn(b, "seal-install", "3", "3");
  api.changed(false);
  b.clock.fire();
  const keep = last(b.rec.saves).tab_opts;
  out.kept = { tabOpts: clone(keep) };

  // ── 7. the second Seal sheet, added beside the first ──
  api.show("Polish");
  P.clickEl(b, P.need(b, '[data-sh-act="add-menu"]'));
  out.second = { choicesBefore: addButtons(html(b, "sheets-panel")) };
  P.clickEl(b, P.need(b, '[data-sh-act="add"][data-sh-sheet="Seal (+Jnts)"]'));
  await settle();
  out.second.alert = text(b, "alert");
  api.show("Polish");
  const m2 = api.model();
  out.second.tabs = Object.keys(m2.tabs);
  // The second Seal-type sheet is filed under a Copy<N> id, with its sheet and its name in its own keys (the bid already has a section of
  // the Seal tab, so the sheet's own name is not its key): everything the draft keeps for it is keyed by that id.
  const jntsId = Object.keys(m2.tabs).filter((k) => k !== "Seal")[0];
  out.second.id = jntsId;
  out.second.sheet = m2.tabs[jntsId].sheet; out.second.label = m2.tabs[jntsId].label;
  out.second.jntsTakeoff = m2.tabs[jntsId].takeoff.map((r) => [r.assembly_id, r.measurement]);
  out.second.bar = { rows: tabsIn(html(b, "sheets-panel")), addStillThere: /data-sh-act="add-menu"/.test(html(b, "sheets-panel")) };
  b.clock.fire();
  const savedTwo = last(b.rec.saves);
  out.second.pricedTabs = (savedTwo.priced_tabs || []).map((t) => [t.id, t.kind, t.system_desc]);
  out.second.lump = savedTwo.proposal_lump_sum;

  // ── 8. taking an option off: the first press arms, the second removes; the proposal side forgets it ──
  // The Proposal step has left things under both options' ids, and under a manual line that is neither's.
  b.store.blob.tab_notes = Object.fromEntries([["Seal", ["Old manual note from the removed option"]], [jntsId, ["The other option's note"]]]);
  b.store.blob.price_overrides = {
    options: Object.fromEntries([["Seal", { label: "Mine", amount: 9999 }], [jntsId, { label: "Other", amount: 1 }]]),
    lines: { "option:Seal": "old words" },
    lines2: Object.fromEntries([["option:Seal", "$9,999 – Sealed Concrete, my old words"], ["option:Seal:sales_tax", "old tax words"],
              ["option:" + jntsId, "the other line"], ["manual:0", "a manual line"]]),
    before: Object.fromEntries([["option:Seal", ["typed above"]], ["option:" + jntsId, ["typed above the other"]]]),
    after: { "option:Seal:total": ["typed below"] },
    line_props: { "option:Seal": { bullet: true } }, before_props: {}, after_props: {},
  };
  // A sheet's Delete is on its own row once that row is open.
  openSheet(b, "Seal");
  P.clickEl(b, P.need(b, deleteSel("Seal")));
  out.remove = { armedLabel: P.need(b, deleteSel("Seal")).textContent, stillThere: Object.keys(api.model().tabs) };
  // a click anywhere else on the panel puts it back
  P.clickEl(b, P.need(b, '[data-sh-act="desc"][data-sh-tab="Seal"]'));
  out.remove.disarmedLabel = P.need(b, deleteSel("Seal")).textContent;
  out.remove.addStillOffered = /data-sh-act="add-menu"/.test(html(b, "sheets-panel"));
  P.clickEl(b, P.need(b, deleteSel("Seal")));
  P.clickEl(b, P.need(b, deleteSel("Seal")));
  b.clock.fire();
  out.remove.leftovers = { tabNotes: clone(b.store.blob.tab_notes), price: clone(b.store.blob.price_overrides) };
  const savedRm = last(b.rec.saves);
  const mr = clone(savedRm.polish_estimate);
  out.remove.after = {
    tabs: Object.keys(mr.tabs), pricedTabs: (savedRm.priced_tabs || []).map((t) => t.id),
    tabOptsKeys: Object.keys(savedRm.tab_opts || {}), lump: savedRm.proposal_lump_sum, baseLump: polishByHand(mr).total,
    openAfter: openTab(html(b, "sheets-panel")), rows: tabsIn(html(b, "sheets-panel")),
  };
  // and the last one, then the Open sheet line hides itself again and the price snapshot still covers the base
  openSheet(b, jntsId);
  P.clickEl(b, P.need(b, deleteSel(jntsId)));
  P.clickEl(b, P.need(b, deleteSel(jntsId)));
  b.clock.fire();
  const savedNone = last(b.rec.saves);
  out.remove.none = {
    tabsKey: clone(api.model().tabs), pricedTabs: (savedNone.priced_tabs || []).map((t) => [t.id, t.kind]),
    lump: savedNone.proposal_lump_sum, rows: tabsIn(html(b, "sheets-panel")),
    addOffered: /data-sh-act="add-menu"/.test(html(b, "sheets-panel")), tabOptsKeys: Object.keys(savedNone.tab_opts || {}),
    bar: text(b, "bid-total"),
  };

  // ── 9. a saved bid that holds an option opens as saved and writes nothing ──
  const reopen = await open(clone(savedTwo ? clone(b.store.blob) : b.store.blob));
  out.reopened = { saves: reopen.rec.saves.length, armed: reopen.clock.armed() };
  const withOpt = clone(saved);
  const wb = await open(P.blob(Object.assign({ work_type: "polish", polish_sf: 10000 }, { polish_estimate: clone(withOpt.polish_estimate), tab_opts: clone(withOpt.tab_opts) })));
  out.reopenedWithOption = {
    saves: wb.rec.saves.length, armed: wb.clock.armed(), strip: tabsIn(html(wb, "sheets-panel")),
    bar: text(wb, "bid-total"),
    handBar: money(polishByHand(clone(withOpt.polish_estimate)).total),
  };

  // ── 10. an Epoxy job takes the option too: the option is seeded from the Epoxy area and the Epoxy section carries the travel ──
  const epx = await open(P.blob({ work_type: "epoxy", system_1_sf: 6000, cove_1_lf: 300,
    polish_estimate: { version: 2, conditions: Object.assign({}, OFF) } }));
  epx.api.go(0);
  epx.api.setAssembly(0, asmNamed("MACRO Flake Single Broadcast").name);
  epx.api.changed(true);
  pressAdd(epx, "Seal (+Jnts)");
  await settle();
  epx.api.show("Epoxy");
  const me = epx.api.model();
  out.epoxyJob = {
    tabs: Object.keys(me.tabs), kinds: B.sectionsOf(me).map((e) => [e.tab, e.kind]), carrier: B.travelCarrier(me),
    jntsTakeoff: me.tabs["Seal (+Jnts)"].takeoff.map((r) => [r.assembly_id, r.measurement]),
    jntsLaborIds: me.tabs["Seal (+Jnts)"].labor.map((r) => r.id),
  };

  // ── 11. a renovation pays the renovation patch ──
  const rn = await open(polishDraft({ cell_values: { "Polish!B10": "Reno" } }));
  rn.api.go(0); rn.api.setAssembly(0, polishAsm.name); rn.api.changed(true);
  pressAdd(rn, "Seal");
  await settle();
  rn.api.show("Seal");
  const nw = await open(polishDraft({ cell_values: { "Polish!B10": "New" } }));
  nw.api.go(0); nw.api.setAssembly(0, polishAsm.name); nw.api.changed(true);
  pressAdd(nw, "Seal");
  await settle();
  nw.api.show("Seal");
  const sf10k = 10000;
  out.reno = {
    renoOn: rn.api.jobIsReno(), newOn: nw.api.jobIsReno(),
    renoMaterial: rn.api.sectionBids().Seal.material, newMaterial: nw.api.sectionBids().Seal.material,
    expectedDifference: sf10k * (0.15 - 0.05),
    renoCaption: /\(a renovation\)/.test((rn.api.go(0), html(rn, "panels"))), newCaption: /\(new concrete\)/.test((nw.api.go(0), html(nw, "panels"))),
    blankIsNew: (await open(polishDraft())).api.jobIsReno(),
  };

  // ── 12. the library cannot be read: the option is still added, with the shipped defaults and a reason nowhere hidden ──
  const bare = await open(polishDraft(), { items: [], asms: [], labor: [], laborCalc: [] });
  pressAdd(bare, "Seal");
  await settle();
  out.bare = { tabs: Object.keys(bare.api.model().tabs || {}), alert: text(bare, "alert") };

  // ── 13. the model, without a page ──
  out.model = modelFacts();

  return out;
}

/** What js/bid-model.js and js/work-types.js say about options, with no page in the way. */
function modelFacts() {
  const W = require(path.join(ROOT, "js", "work-types.js"));
  const threw = (f) => { try { f(); return null; } catch (e) { return String(e && e.message); } };
  const base = B.freshModel();
  base.takeoff = [{ assembly_id: polishAsm.id, assembly_name: polishAsm.name, measurement: 10000, unit: "SF" }];
  base.labor = base.labor.map((r) => (r.id === "polishing" ? Object.assign({}, r, { guys: 3, days: 5 }) : r));
  const ctx = { asms: asms, items: items, reserved: [], laborRows: laborRows, laborRate: 33, calcRows: calcRows,
    sf: { Seal: [10000, ""], "Seal (+Jnts)": [10000, ""] },
    takeoffRows: (e, sfs) => SL.seedTakeoff(e.tab, asms, sfs[0]) };
  const before = JSON.stringify(base);
  const withSeal = B.addOption(base, "Seal", ctx);
  const rootKeys = (m) => JSON.stringify(Object.assign({}, m, { tabs: undefined }));
  // a root that has stated nothing would be reseeded by seedNewSections: adding an option must not do that to it
  const blank = B.freshModel();
  blank.labor = [];
  const blankPlus = B.addOption(blank, "Seal", ctx);
  // the composition: a base and an option
  const bid = B.markupChain({ material: 3000, labor: 4000, travel: 0, contingency: 0, fees: 0, conditions: base.conditions, sf: 10000 });
  const sealBid = sealByHand(withSeal, "Seal", false);
  const comp = B.composePricingSnapshot(withSeal, { bid: bid, bids: { Seal: sealBid } });
  const compOpts = B.composePricingSnapshot(withSeal, { bid: bid, bids: { Seal: sealBid },
    tabOpts: { Seal: { is_option: false, show: false, price_mode: "deduct" }, Other: { is_option: true } } });
  const emptyTabs = B.removeOption(withSeal, "Seal");
  const single = B.composePricingSnapshot(base, { bid: bid });
  const afterRemove = B.composePricingSnapshot(emptyTabs, { bid: bid, bids: {} });
  const sealOnlyBase = Object.assign(B.freshModel(), { kind: "off" });
  return {
    offers: { fresh: B.optionsToOffer(base), afterSeal: B.optionsToOffer(withSeal), noModel: B.optionsToOffer(null),
              sheets: W.optionSheets(), levelingOffered: W.tab("leveling").offered, sealOffered: W.tab("seal").offered },
    addIsPure: JSON.stringify(base) === before,
    kept: rootKeys(withSeal) === rootKeys(base), blankRootKept: rootKeys(blankPlus) === rootKeys(blank),
    added: { kind: withSeal.tabs.Seal.kind, layout: withSeal.tabs.Seal.layout, profile: withSeal.tabs.Seal.profile,
             labor: withSeal.tabs.Seal.labor.map((r) => r.id), takeoff: withSeal.tabs.Seal.takeoff.map((r) => [r.assembly_id, r.measurement]),
             pooled: withSeal.tabs.Seal.pool_packs },
    refuses: {
      leveling: threw(() => B.addOption(base, "Leveling", ctx)), epoxy: threw(() => B.addOption(base, "Epoxy", ctx)),
      polish: threw(() => B.addOption(base, "Polish", ctx)), twice: threw(() => B.addOption(withSeal, "Seal", ctx)),
      removeRoot: threw(() => B.removeOption(withSeal, "Polish")), removeUnknown: threw(() => B.removeOption(withSeal, "Seal (+Jnts)")),
      removeBase: threw(() => B.removeOption(B.sectionsForJob(base, "combo", {}), "Epoxy")),
    },
    removed: { tabs: emptyTabs.tabs, offered: B.optionsToOffer(emptyTabs) },
    // an option on a job on the road carries its own Lodging and Per Diem (the Seal tab's B58 and B59): 3 men for 5 days
    // of crew, no material, $70 and $45. The workbook's answers for that job are 11,011 local and 15,293 away.
    lodging: (() => {
      const price = (away, typedQty) => {
        const m = B.activateSection(B.freshModel(), "Seal", "option", {});
        m.conditions = Object.assign({}, m.conditions, { local: !away, taxable: true, prevailing_wage: false, remodel_tax: false });
        m.tabs.Seal.takeoff = [{ assembly_id: "", assembly_name: "", measurement: 10000, unit: "SF" }];
        m.tabs.Seal.labor = [{ id: "crew", label: "Crew", guys: 3, days: 5, rate: 33 }];
        m.travel = B.travelCostsSeed(70, 45);
        m.travel.lodging = Object.assign({}, m.travel.lodging, { enabled: away, qty_auto: false, qty: typedQty });
        m.travel.per_diem = Object.assign({}, m.travel.per_diem, { enabled: away, qty_auto: false, qty: typedQty });
        return B.priceSection(m, "Seal", { material: () => ({ material: 0, tooling: 0 }) }).total;
      };
      return { local: price(false, 1), away: price(true, 1), awayOtherTypedQty: price(true, 40) };
    })(),
    workTypes: { sealOwn: B.workTypeApplies({ default_work_types: ["seal"] }, { tab: "seal" }),
                 polishRowOnSeal: B.workTypeApplies({ default_work_types: ["polish"] }, { tab: "seal" }),
                 emptyOnSeal: B.workTypeApplies({ default_work_types: [] }, { tab: "seal" }),
                 combo: B.workTypeApplies({ default_work_types: ["epoxy"] }, "combo"),
                 bareSealStillThrows: threw(() => B.workTypeApplies({ default_work_types: [] }, "seal")),
                 notATab: threw(() => B.workTypeApplies({ default_work_types: [] }, { tab: "nothing" })),
                 kindOfSection: [B.kindOfSection("polish"), B.kindOfSection("epoxy"), B.kindOfSection("gyp"), B.kindOfSection("seal")] },
    snapshot: {
      keys: Object.keys(comp), lump: comp.proposal_lump_sum, handLump: bid.total, computed: comp.computed_bid.lump_sum,
      tabs: comp.priced_tabs.map((t) => [t.id, t.role, t.kind, t.total, t.system_desc]), area: comp.sheet_area,
      tabOpts: comp.tab_opts, keptOpts: compOpts.tab_opts, singleKeys: Object.keys(single),
      afterRemoveKeys: Object.keys(afterRemove), afterRemoveTabs: afterRemove.priced_tabs.map((t) => t.id), afterRemoveHasOpts: "tab_opts" in afterRemove,
      sealTotal: sealBid.total, sealPriced: comp.priced_tabs[1].total,
    },
    desc: { seal: B.composePricingSnapshot(withSeal, { bid: bid, bids: { Seal: sealBid } }).priced_tabs[1].system_desc,
            jnts: B.composePricingSnapshot(B.addOption(withSeal, "Seal (+Jnts)", ctx), { bid: bid, bids: { Seal: sealBid, "Seal (+Jnts)": sealBid } }).priced_tabs[2].system_desc },
    // the Seal tab's own flag cells, written from the shared job conditions (Phase 7b's known gap, closed)
    cells: (() => {
      const w = (cond, split) => B.conditionCellWrites(Object.assign({}, B.freshModel().conditions, cond), {}, {}, !!split);
      const away = w({ local: false });
      const home = w({ local: true });
      return {
        localOff: [away["Seal!B4"], away["Epoxy!B4"], away["Polish!B4"]], localOn: [home["Seal!B4"], home["Epoxy!B4"], home["Polish!B4"]],
        reno: [home["Seal!B10"], home["Polish!B10"], home["Epoxy!B10"]],
        carried: B.CARRIED_CELLS && B.CARRIED_CELLS.map((c) => [c.key, c.cells]),
        tableLocal: W.condition("local").cells, tableReno: W.condition("reno").cells,
        splitStillWritesSeal: [w({}, true)["Seal!B4"], w({}, true)["Seal!B10"]],
        sealTaxStillAMirror: ["Seal!B6", "Seal!D5", "Seal!D6"].map((a) => a in home),
      };
    })(),
    sealOnlyKinds: B.sectionsOf(B.activateSection(sealOnlyBase, "Seal", "option", {})).map((e) => [e.tab, e.kind]),
  };
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
