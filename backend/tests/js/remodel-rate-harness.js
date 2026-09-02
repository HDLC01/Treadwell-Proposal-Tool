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

// `toggles` is the {"<sheet>!<addr>": value} the sheet's own D6/D8 remodel switches read.
// It matters because Kyle's rate cell is =IF(D6="yes",<rate>,0): with the switch off the
// tax is zero whatever rate is typed, and remodelTaxIsOn has to be able to say so.
function harness(tabs, active, toggles) {
  const cellValues = {};
  // A warm cache for every sheet a fixture might sit on. It is asserted to SURVIVE: the override
  // used to delete the active sheet's entry and re-fetch it, which 404s on a copy (a copy has no
  // server-side worksheet) and blanked the tab. See refreshActiveGridFromHF in the real file.
  const sheetCache = {
    Epoxy: { sheet: "Epoxy", cells: [] },
    Copy1: { sheet: "Copy1", cells: [] },
  };
  const refreshCalls = [];
  const setStateCalls = [];
  const hfCalls = [];
  const state = {};
  const clearListeners = [];

  const countySelected = { innerHTML: "" };
  const countyInput = { value: "should-be-cleared" };
  const countyResults = { classList: { removed: false, remove() { this.removed = true; }, add() {} } };
  const countyClearEl = { addEventListener: (t, fn) => clearListeners.push(fn) };
  // The typed-% box and its note. `activeElement` is real state, not decoration:
  // renderRemodelRateField must not write over a box someone is still typing in, and
  // the only way to test that is to actually focus it.
  const rateBox = { value: "", addEventListener: () => {} };
  const rateNote = { textContent: "", className: "" };
  const document = {
    activeElement: null,
    getElementById: (id) => (id === "county-clear" ? countyClearEl
      : id === "remodel-rate" ? rateBox
      : id === "remodel-rate-note" ? rateNote
      : null),
  };

  const toggleValues = toggles || {};
  const HF = {
    ready: true,
    setCellValue(sheet, addr, v) { hfCalls.push([sheet, addr, v]); },
    getValue(sheet, addr) {
      const k = sheet + "!" + addr;
      return Object.prototype.hasOwnProperty.call(toggleValues, k) ? toggleValues[k] : null;
    },
  };
  const TW = { setState: (p) => setStateCalls.push(p) };
  // The fixture's active tab — proves the grid-refresh path fires. Pass "Copy1" to sit on a
  // COPIED tab, which is where the discarded cache used to blank the grid.
  const activeSheet = active || "Epoxy";

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
    // Leaf stubs. refreshActiveGridFromHF itself is LIFTED and runs for real — stubbing it would
    // stub out the very fix these last cases exist to prove.
    sheetGrid: { querySelector: () => null },
    refreshDomFromHF: (data) => refreshCalls.push(data && data.sheet),
    updateTotalBarFromHF: () => {},
  };
  deps.escHtml = lift("escHtml", deps);
  deps.countyRowLabel = lift("countyRowLabel", deps);
  deps.remodelRateTargets = lift("remodelRateTargets", deps);
  deps.refreshActiveGridFromHF = lift("refreshActiveGridFromHF", deps);
  deps.applyRemodelRateOverride = lift("applyRemodelRateOverride", deps);
  // Dependency order matters: `lift` passes deps BY NAME into new Function, so a callee
  // absent from deps at lift time is an unbound identifier inside the lifted copy.
  deps.shiftDecimalText = lift("shiftDecimalText", deps);
  deps.effectiveRemodelRate = lift("effectiveRemodelRate", deps);
  deps.remodelTaxIsOn = lift("remodelTaxIsOn", deps);
  deps.renderRemodelRateField = lift("renderRemodelRateField", deps);
  deps.renderCountyPill = lift("renderCountyPill", deps);
  deps.commitRemodelRate = lift("commitRemodelRate", deps);
  const pickCounty = lift("pickCounty", deps);

  return {
    state, cellValues, sheetCache, refreshCalls, setStateCalls, hfCalls, tabs: tabList,
    countySelected, countyInput, countyResults, clearListeners,
    rateBox, rateNote, document,
    shiftDecimalText: deps.shiftDecimalText,
    effectiveRemodelRate: deps.effectiveRemodelRate,
    remodelTaxIsOn: deps.remodelTaxIsOn,
    renderRemodelRateField: deps.renderRemodelRateField,
    commitRemodelRate: deps.commitRemodelRate,
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
    // the active sheet's grid was re-rendered from HF, and its cache SURVIVED
    gridRefreshedFor: h.refreshCalls,
    cachePreserved: "Epoxy" in h.sheetCache,
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

// ── 10. picking the county while SITTING ON a copied tab ─────────────────────
// The regression case 8 created. Once copies became targets, the override's own refresh reached a
// copy for the first time — and it refreshed by deleting the active sheet's cache and re-running
// showSheet, which for a copy means GET /api/sheet/Copy1 → 404 → "Failed to load Copy1", cache
// gone. Found by driving a real browser against staging; no assertion in cases 1-9 could see it,
// because every one of them sits on a base tab where the refetch happens to succeed.
{
  const h = harness([{ id: "Epoxy" }, { id: "Copy1", source: "Epoxy" }], "Copy1");
  h.pickCounty(OP);
  out.pickedWhileOnACopy = {
    copy1: h.cellValues["Copy1!B81"],
    cachePreserved: "Copy1" in h.sheetCache,
    gridRefreshedFor: h.refreshCalls,
  };
}


// ═══ The typed remodel tax % ══════════════════════════════════════════════════
// Kyle reads the rate off the state's own site for the job's address, so the county
// table is a starting point rather than the answer. Everything below drives the real
// commitRemodelRate / renderRemodelRateField out of estimate-review.js.

// ── 11. the decimal shift is exact, and arithmetic is not ────────────────────
// These rates carry three decimals, which a binary double does not divide or
// multiply cleanly. 7.975 / 100 is exact BY LUCK -- 8.775 and 9.975 are not, and
// the display direction (rate * 100) is worse still. Both directions are listed
// so a green test here cannot be satisfied by a single lucky rate.
{
  const h = harness();
  const shifted = h.shiftDecimalText("7.975", -2);
  out.exactness = {
    shifted: shifted,                                   // "0.07975"
    roundTrip: String(Number(shifted)),                 // still "0.07975"
    // the counterexamples: what a plain /100 and *100 actually produce
    naiveDivision: ["8.775", "9.975", "6.975", "7.15"].map(s => [s, String(Number(s) / 100)]),
    naiveMultiply: ["0.07975", "0.07"].map(s => [s, String(Number(s) * 100)]),
    // a spread of shapes, none of them rounded
    cases: ["7.975", "8.775", "9.975", "7.15", "10", "6.5", "0.5", ".5", "7.", "11.125", "0"]
      .map(s => [s, h.shiftDecimalText(s, -2)]),
    // and back the other way, for painting the box
    backToPct: ["0.07975", "0.08775", "0.09975", "0.1", "0.065", "0.005", "0.07"]
      .map(s => [s, h.shiftDecimalText(s, 2)]),
    // the property that matters: shifting there and back is the identity
    roundTripAll: ["7.975", "8.775", "9.975", "7.15", "6.5", "10", "0.5"]
      .map(s => [s, h.shiftDecimalText(h.shiftDecimalText(s, -2), 2)]),
    refused: ["abc", "7,975", "", ".", "7.9.5", "-3", "7%"].map(s => [s, h.shiftDecimalText(s, -2)]),
  };
}

// ── 12. a typed % with no county at all reaches every rate cell ──────────────
{
  const h = harness([{ id: "Epoxy" }, { id: "Copy1", source: "Epoxy" }]);
  h.rateBox.value = "7.975";
  h.commitRemodelRate();
  out.typedNoCounty = {
    epoxy: h.cellValues["Epoxy!B81"],
    polish: h.cellValues["Polish!B75"],
    copy1: h.cellValues["Copy1!B81"],
    oneGyp: h.cellValues[`${GYP_SHEETS[0]}!B80`],
    effective: h.effectiveRemodelRate(),
    persisted: h.setStateCalls[h.setStateCalls.length - 1].remodel_rate_override,
    // the DOLLAR cells are never touched: the whole-dollar rounding stays Kyle's
    // own ROUNDUP(SUM(...)*B81,0) rather than becoming ours.
    dollarCellsWritten: Object.keys(h.cellValues).filter(k =>
      /!(D81|D75|E80|D77|D78)$/.test(k)),
  };
}

// ── 13. a typed % beats the county table ─────────────────────────────────────
{
  const h = harness();
  h.pickCounty(OP);                       // Overland Park, 9.35%
  h.rateBox.value = "7.975";
  h.commitRemodelRate();
  out.typedBeatsCounty = {
    epoxy: h.cellValues["Epoxy!B81"],
    effective: h.effectiveRemodelRate(),
    countyStillOnState: h.state.county_remodel_rate,
    pill: h.countySelected.innerHTML,
  };
}

// ── 14. clearing the COUNTY does not retract the typed % ─────────────────────
// The estimator got that figure off the site for this address; dropping the county
// is a different act.
{
  const h = harness();
  h.pickCounty(OP);
  h.rateBox.value = "7.975";
  h.commitRemodelRate();
  h.clearListeners.forEach(fn => fn());  // the pill's x
  out.clearCountyKeepsTyped = {
    epoxy: h.cellValues["Epoxy!B81"],
    effective: h.effectiveRemodelRate(),
    countyGone: h.state.county === undefined,
  };
}

// ── 15. a NEW county supersedes the typed %, visibly ─────────────────────────
{
  const h = harness();
  h.rateBox.value = "7.975";
  h.commitRemodelRate();
  h.pickCounty(OP);                       // a new address
  out.newCountyWins = {
    epoxy: h.cellValues["Epoxy!B81"],
    effective: h.effectiveRemodelRate(),
    boxRepainted: h.rateBox.value,        // must show the county's own figure, not 7.975
  };
}

// ── 16. a typo is refused, and the rate in force does not move ───────────────
{
  const h = harness();
  h.pickCounty(OP);
  h.rateBox.value = "seven point nine";
  h.commitRemodelRate();
  out.typoRefused = {
    epoxy: h.cellValues["Epoxy!B81"],     // still the county's 9.35%
    effective: h.effectiveRemodelRate(),
    override: h.state.remodel_rate_override,
    note: h.rateNote.textContent,
    noteClass: h.rateNote.className,
  };
}

// ── 17. emptying the box falls back, rather than pinning 0% ──────────────────
{
  const h = harness();
  h.pickCounty(OP);
  h.rateBox.value = "7.975";
  h.commitRemodelRate();
  h.rateBox.value = "";
  h.commitRemodelRate();
  out.emptiedFallsBack = {
    epoxy: h.cellValues["Epoxy!B81"],     // back to the county's 9.35%
    effective: h.effectiveRemodelRate(),
    override: h.state.remodel_rate_override,
  };
}

// ── 18. the box is not overwritten while someone is typing in it ─────────────
// A re-render that repaints a focused field steals the digits half-typed into it.
{
  const h = harness();
  h.pickCounty(OP);
  h.document.activeElement = h.rateBox;
  h.rateBox.value = "7.9";               // mid-keystroke
  h.renderRemodelRateField();
  const whileFocused = h.rateBox.value;
  h.document.activeElement = null;
  h.renderRemodelRateField();
  out.focusRespected = { whileFocused: whileFocused, afterBlur: h.rateBox.value };
}

// ── 19. with the sheet's own remodel switch off, say so ──────────────────────
// Kyle's cell is =IF(D6="yes",<rate>,0): off means zero tax whatever is typed.
{
  const on = harness([{ id: "Epoxy" }], "Epoxy", { "Epoxy!D6": "yes" });
  on.rateBox.value = "7.975";
  on.commitRemodelRate();

  const off = harness([{ id: "Epoxy" }], "Epoxy", { "Epoxy!D6": "no" });
  off.rateBox.value = "7.975";
  off.commitRemodelRate();

  const none = harness([{ id: "Epoxy" }], "Epoxy", { "Epoxy!D6": "yes" });
  none.renderRemodelRateField();         // nothing typed, no county

  out.switchNotes = {
    onNote: on.rateNote.textContent,
    onIsOn: on.remodelTaxIsOn(),
    offNote: off.rateNote.textContent,
    offIsOn: off.remodelTaxIsOn(),
    // refused or not, the cell still carries the rate -- the switch, not us, zeroes it
    offCell: off.cellValues["Epoxy!B81"],
    unsetNote: none.rateNote.textContent,
  };
}

console.log(JSON.stringify(out));
