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
 * Lifts `REMODEL_RATE_CELLS`, `applyRemodelRateOverride`, `escHtml`, `countyRowLabel`,
 * `renderCountyPill`, and `pickCounty` out of the real file and runs them against stub DOM/state.
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

// GYP_BASE + GYP_SHEETS, because REMODEL_RATE_CELLS is built from GYP_SHEETS.map(...) in the
// real source — the fixture must use the SHIPPED variant list, not a hand-typed copy of it.
const GYP_SRC = [
  grab(/^const GYP_BASE = .*$/m, "GYP_BASE"),
  grab(/^const GYP_SHEETS = \[[\s\S]*?\];$/m, "GYP_SHEETS"),
].join(NL);
const { GYP_BASE, GYP_SHEETS } = new Function(GYP_SRC + NL + "return { GYP_BASE, GYP_SHEETS };")();

const REMODEL_RATE_CELLS = new Function(
  "GYP_SHEETS",
  grab(/^const REMODEL_RATE_CELLS = \[[\s\S]*?\];$/m, "REMODEL_RATE_CELLS") + NL +
  "return REMODEL_RATE_CELLS;"
)(GYP_SHEETS);

function harness() {
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

  const deps = {
    document, state, TW, HF, cellValues, sheetCache, activeSheet,
    REMODEL_RATE_CELLS, countySelected, countyInput, countyResults,
    showSheet: (name) => showSheetCalls.push(name),
  };
  deps.escHtml = lift("escHtml", deps);
  deps.countyRowLabel = lift("countyRowLabel", deps);
  deps.applyRemodelRateOverride = lift("applyRemodelRateOverride", deps);
  deps.renderCountyPill = lift("renderCountyPill", deps);
  const pickCounty = lift("pickCounty", deps);

  return {
    state, cellValues, sheetCache, showSheetCalls, setStateCalls, hfCalls,
    countySelected, countyInput, countyResults, clearListeners,
    pickCounty, applyRemodelRateOverride: deps.applyRemodelRateOverride,
    renderCountyPill: deps.renderCountyPill,
  };
}

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

console.log(JSON.stringify(out));
