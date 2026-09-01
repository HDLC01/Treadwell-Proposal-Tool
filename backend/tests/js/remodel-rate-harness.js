"use strict";
/* Execute the real county-picker → remodel-tax-cell wiring out of estimate-review.js.
 *
 * WHY EXECUTED. The bug this fixes was invisible to source reading too: the OLD picker code read
 * perfectly reasonably ("set county_remodel_rate, show a hint") — the defect was that nothing it
 * did ever reached the workbook. The only way to prove the NEW code actually reaches the formula
 * cell is to run pickCounty/applyRemodelRateOverride for real and inspect the resulting
 * cellValues/HF writes, exactly the way `main.py`'s cell_values write step and the live HF engine
 * would consume them.
 *
 * Lifts `REMODEL_RATE_BY_LAYOUT`, `remodelRateTargets`, `applyRemodelRateOverride`, `escHtml`,
 * `countyRowLabel`, `renderCountyPill`, and `pickCounty` out of the real file and runs them
 * against stub DOM/state.
 *
 * 2026-09-02: the target list stopped being a constant. It had named only Epoxy/Polish/Gyp while
 * Seal!B75, Leveling!B77 and "Epoxy blank"!B78 also carry `=IF(D6="yes",0.1,0)` in the shipped
 * template, and COPIED tabs — the ordinary way to add a priced proposal option — are cloned from
 * the pristine template by the backend and so arrived holding the 10% placeholder. Cases 6-9
 * below are those four holes; each one was a real number on a real customer's proposal.
 *
 * Usage: node remodel-rate-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(process.argv[2], "js", "estimate-review.js"), "utf8");
const NL = String.fromCharCode(10);

function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + what + " — rewrite this harness, don't stub it");
  return m[0];
}

function lift(name, deps) {
  const re = new RegExp("^function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name);
  const names = Object.keys(deps);
  return new Function(...names, m[0] + NL + "return " + name + ";")(...names.map(k => deps[k]));
}

// GYP_BASE + GYP_SHEETS, because REMODEL_RATE_BY_LAYOUT is extended by a GYP_SHEETS.forEach in
// the real source — the fixture must use the SHIPPED variant list, not a hand-typed copy of it.
const GYP_SRC = [
  grab(/^const GYP_BASE = .*$/m, "GYP_BASE"),
  grab(/^const GYP_SHEETS = \[[\s\S]*?\];$/m, "GYP_SHEETS"),
].join(NL);
const { GYP_BASE, GYP_SHEETS } = new Function(GYP_SRC + NL + "return { GYP_BASE, GYP_SHEETS };")();

// The layout→cell map plus the GYP_SHEETS.forEach line that extends it — lifted together so the
// fixture uses the SHIPPED table, including the gyp variants, not a hand-typed copy.
const REMODEL_RATE_BY_LAYOUT = new Function(
  "GYP_SHEETS",
  grab(/^const REMODEL_RATE_BY_LAYOUT = \{[\s\S]*?^\};$/m, "REMODEL_RATE_BY_LAYOUT") + NL +
  grab(/^GYP_SHEETS\.forEach\(\(s\) => \{ REMODEL_RATE_BY_LAYOUT.*$/m, "gyp extension") + NL +
  "return REMODEL_RATE_BY_LAYOUT;"
)(GYP_SHEETS);

function harness(tabs) {
  const cellValues = {};
  const sheetCache = { Epoxy: { stale: true } };
  const showSheetCalls = [];
  const setStateCalls = [];
  const hfCalls = [];
  const state = {};
  const clearListeners = [];

  const countySelected = { innerHTML: "" };
  const countyInput = { value: "should-be-cleared" };
  const countyResults = { classList: { removed: false, remove() { this.removed = true; }, add() {} } };
  const countyClearEl = { addEventListener: (t, fn) => clearListeners.push(fn) };
  const document = { getElementById: (id) => (id === "county-clear" ? countyClearEl : null) };

  const HF = {
    ready: true,
    setCellValue(sheet, addr, v) { hfCalls.push([sheet, addr, v]); },
  };
  const TW = { setState: (p) => setStateCalls.push(p) };
  const activeSheet = "Epoxy";   // the fixture's active tab — proves the cache-bust path fires

  // `tabs` is the live tab bar (base tabs + copies). Passed by reference and read fresh inside
  // remodelRateTargets, so a test can push a copy onto it and re-run the override — which is
  // exactly the "copy the tab, THEN pick the county" sequence that shipped a 10% option.
  const tabList = tabs || [];
  // Real signature, trivial bodies: no fixture here has structural row/col edits, so txAddr is
  // identity. layoutIdFor walks a copy back to the template sheet it was cloned from.
  const txAddr = (_id, addr) => addr;
  const layoutIdFor = (id) => {
    const t = tabList.find(x => x.id === id);
    return t && t.source ? layoutIdFor(t.source) : id;
  };

  const deps = {
    document, state, TW, HF, cellValues, sheetCache, activeSheet,
    REMODEL_RATE_BY_LAYOUT, countySelected, countyInput, countyResults,
    tabs: tabList, txAddr, layoutIdFor,
    showSheet: (name) => showSheetCalls.push(name),
  };
  deps.escHtml = lift("escHtml", deps);
  deps.countyRowLabel = lift("countyRowLabel", deps);
  deps.remodelRateTargets = lift("remodelRateTargets", deps);
  deps.applyRemodelRateOverride = lift("applyRemodelRateOverride", deps);
  deps.renderCountyPill = lift("renderCountyPill", deps);
  const pickCounty = lift("pickCounty", deps);

  return {
    state, cellValues, sheetCache, showSheetCalls, setStateCalls, hfCalls, tabs: tabList,
    countySelected, countyInput, countyResults, clearListeners,
    pickCounty, applyRemodelRateOverride: deps.applyRemodelRateOverride,
    remodelRateTargets: deps.remodelRateTargets,
    renderCountyPill: deps.renderCountyPill,
  };
}

const OP = { kind: "city", name: "Overland Park", state: "KS", rate: 0.0935, remodel_rate: 0.0935, notes: "" };

const out = {};
out.gypSheetCount = GYP_SHEETS.length;

// ── 1. picking a city writes the real formula into every remodel-tax cell ────
{
  const h = harness();
  h.pickCounty({ kind: "city", name: "Overland Park", state: "KS", rate: 0.0935, remodel_rate: 0.0935, notes: "" });
  out.pickedCity = {
    epoxy: h.cellValues["Epoxy!B81"],
    polish: h.cellValues["Polish!B75"],
    gyp: Object.fromEntries(GYP_SHEETS.map(s => [s, h.cellValues[`${s}!B80`]])),
    cellCount: Object.keys(h.cellValues).length,
    // every write also reached the live HF engine, same shape
    hfMatchesCellValues: h.hfCalls.every(([sheet, addr, v]) => h.cellValues[`${sheet}!${addr}`] === v),
    hfCallCount: h.hfCalls.length,
    // the active sheet's cache was busted and the grid re-rendered
    activeSheetCacheBusted: !("Epoxy" in h.sheetCache),
    showSheetCalledWith: h.showSheetCalls,
    // state carries what the proposal step reads ({{county}})
    stateCounty: h.state.county,
    stateCountyTaxRate: h.state.county_tax_rate,
    stateCountyRemodelRate: h.state.county_remodel_rate,
    persistedRemodelRate: h.setStateCalls[h.setStateCalls.length - 1].county_remodel_rate,
    // the pill no longer says "(enter in K81)" — it says the rate was applied
    pillHtml: h.countySelected.innerHTML,
  };
}

// ── 2. a COUNTY row (no override) reverts every cell to Kyle's own 10% placeholder ──
{
  const h = harness();
  h.pickCounty({ kind: "county", name: "Butler", state: "KS", rate: 0.065, remodel_rate: null, notes: "" });
  out.pickedCountyNoOverride = {
    epoxy: h.cellValues["Epoxy!B81"],
    polish: h.cellValues["Polish!B75"],
    oneGyp: h.cellValues[`${GYP_SHEETS[0]}!B80`],
    stateCountyRemodelRate: h.state.county_remodel_rate,
  };
}

// ── 3. clearing the pill reverts to the placeholder AND clears state ─────────
{
  const h = harness();
  h.pickCounty({ kind: "city", name: "Overland Park", state: "KS", rate: 0.0935, remodel_rate: 0.0935, notes: "" });
  const clear = h.clearListeners[h.clearListeners.length - 1];
  clear();
  out.cleared = {
    epoxy: h.cellValues["Epoxy!B81"],
    stateHasCounty: "county" in h.state,
    stateHasRemodelRate: "county_remodel_rate" in h.state,
    pillCleared: h.countySelected.innerHTML === "",
  };
}

// ── 4. a stale draft (rate only ever reached state, never cellValues) self-heals ──
{
  const h = harness();
  // Simulate exactly what a draft saved BEFORE this fix looks like: county_remodel_rate is set,
  // cellValues has nothing for these addresses at all.
  h.state.county = "Overland Park, KS";
  h.state.county_remodel_rate = 0.0935;
  h.applyRemodelRateOverride(h.state.county_remodel_rate != null ? h.state.county_remodel_rate : null);
  out.staleDraftSelfHeals = {
    epoxy: h.cellValues["Epoxy!B81"],
    polish: h.cellValues["Polish!B75"],
  };
}

// ── 5. every toggle reference is LOCAL (D6 on Epoxy/Polish, D8 on every Gyp variant) ──
{
  const h = harness();
  h.pickCounty({ kind: "city", name: "Overland Park", state: "KS", rate: 0.0935, remodel_rate: 0.0935, notes: "" });
  out.toggleShape = {
    epoxy: h.cellValues["Epoxy!B81"],
    polish: h.cellValues["Polish!B75"],
    gyp: h.cellValues[`${GYP_SHEETS[0]}!B80`],
  };
}

// ── 6. the three layouts the old list wrongly claimed had no remodel line ────
// Seal!B75, Leveling!B77 and "Epoxy blank"!B78 all hold `=IF(D6="yes",0.1,0)` in the shipped
// workbook. Until 2026-09-02 the override skipped all three, so anything priced on one of them
// billed Kyle's 10% placeholder while the pill said the picked rate was applied automatically.
{
  const h = harness();
  h.pickCounty(OP);
  out.previouslyMissedLayouts = {
    seal: h.cellValues["Seal!B75"],
    leveling: h.cellValues["Leveling!B77"],
    epoxyBlank: h.cellValues["Epoxy blank!B78"],
  };
}

// ── 7. "Seal (+Jnts)" is NOT written, on purpose ─────────────────────────────
// Its B75 is `=Seal!B75` — a mirror. Writing a literal there would fork the two sheets, which is
// the same independent-cell divergence found in Kyle's own filed workbooks. Absence here is a
// deliberate design decision, so it gets an assertion rather than being left to chance.
{
  const h = harness();
  h.pickCounty(OP);
  out.sealJointsLeftAsMirror = {
    written: Object.keys(h.cellValues).some(k => k.startsWith("Seal (+Jnts)!")),
  };
}

// ── 8. copy the tab, THEN pick the county ────────────────────────────────────
// The backend clones a copied tab from the PRISTINE template, so its rate cell arrives at 10%.
// addCopy's cellValues replay cannot help here — the copy exists before any override does.
{
  const h = harness([
    { id: "Epoxy" }, { id: "Polish" },
    { id: "Copy1", source: "Epoxy" }, { id: "Copy2", source: "Polish" },
  ]);
  h.pickCounty(OP);
  out.copyThenPick = {
    copy1: h.cellValues["Copy1!B81"],     // epoxy layout → B81
    copy2: h.cellValues["Copy2!B75"],     // polish layout → B75
    base: h.cellValues["Epoxy!B81"],
  };
}

// ── 9. a copy of a copy resolves through the chain to its template layout ────
{
  const h = harness([
    { id: "Epoxy" },
    { id: "Copy1", source: "Epoxy" },
    { id: "Copy2", source: "Copy1" },
    { id: "Copy3", source: "Seal" },
  ]);
  h.pickCounty(OP);
  out.copyChain = {
    copy2: h.cellValues["Copy2!B81"],           // Copy1 → Epoxy → B81
    copy3: h.cellValues["Copy3!B75"],           // Seal layout → B75
    targetCount: h.remodelRateTargets().length, // 10 layouts + 3 copies, no duplicates
  };
}

console.log(JSON.stringify(out));
