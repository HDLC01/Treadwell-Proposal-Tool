"use strict";
/* Execute the real filed-markup-rate -> workbook wiring out of estimate-review.js, and the real
 * "does this row reach the bid?" sentence out of markup.js.
 *
 * WHY EXECUTED. The defect this feature fixes was invisible to source reading: the Markup page's
 * code read perfectly sensibly, and nothing it did ever reached a price. Reading the new code
 * proves no more than reading the old code did, and a source assertion cannot catch an unbound
 * identifier — on 2026-08-12 the CRM board went down on production with `ReferenceError:
 * STAGE_CREATED is not defined` while every test was green. So this runs the writer for real and
 * reports the cellValues / HF writes exactly as `estimate_writer.fill_estimate`'s cell_values step
 * and the live HyperFormula engine would consume them.
 *
 * TWO SOURCES, on purpose. `MARKUP_RATE_TARGETS` lives in estimate-review.js and `PRICES_THE_BID`
 * — the sentence the admin reads — lives in markup.js, because markup.js is not loaded on the
 * estimate page and loading it there would run its whole IIFE against a DOM it does not have. The
 * duplication is real, so the agreement is EXECUTED here rather than trusted: both are lifted out
 * of the shipped files and compared by the pytest module.
 *
 * WHAT IS LIFTED AND WHY IT IS LIFTED TOGETHER. `markupRules` is a module-level `let` that
 * `loadMarkupRules` REASSIGNS. Passing it in as a named dep would give each lifted function its
 * own parameter binding, so a reassignment inside one would be invisible to the other — the same
 * trap taxable-flag-harness.js records for `tabs`/`buildTabs`. The declaration and both functions
 * are therefore lifted into ONE `new Function` body so they share the binding the page gives them.
 * `txAddr`, `layoutIdFor`, `structOpsFor`, `_shiftIdx`, `shiftDecimalText` and
 * `refreshActiveGridFromHF` are all lifted for real too: the structural-edit and copied-tab cases
 * are the whole point, and stubbing the coordinate translation would stub out the thing under test.
 *
 * Usage: node markup-rate-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
// Normalised on read for the reason library-ui-harness.js records: git hands these files out with
// CRLF on a Windows checkout and LF in CI, and a `[\s\S]*?^\}$` lift is anchored on the newline.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const SRC = read(path.join(ROOT, "js", "estimate-review.js"));
const MKSRC = read(path.join(ROOT, "js", "markup.js"));
const NL = String.fromCharCode(10);

function grabFrom(src, re, what) {
  const m = re.exec(src);
  if (!m) throw new Error("could not lift " + what + " — rewrite this harness, don't stub it");
  return m[0];
}
const grab = (re, what) => grabFrom(SRC, re, what);

/** Lift one top-level `function name(...) {...}` out of estimate-review.js and bind `deps` into
 *  it BY NAME. A callee missing from deps at lift time is an unbound identifier inside the copy,
 *  so the order of the lifts below is load-bearing. */
function lift(name, deps) {
  const re = new RegExp("^(?:async )?function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name);
  const names = Object.keys(deps);
  return new Function(...names, m[0] + NL + "return " + name + ";")(...names.map(k => deps[k]));
}

// ── the shipped gyp variant list, not a hand-typed copy of it ────────────────
// MARKUP_RATE_TARGETS and MARKUP_LAYOUT_OF are both extended by a GYP_SHEETS.forEach in the real
// source. Retyping the five names here would let the fixture agree with itself while disagreeing
// with the workbook — which is the shape of the PR #432 hole this table exists to close.
const GYP_SRC = [
  grab(/^const GYP_BASE = .*$/m, "GYP_BASE"),
  grab(/^const GYP_SHEETS = \[[\s\S]*?\];$/m, "GYP_SHEETS"),
].join(NL);
const { GYP_BASE, GYP_SHEETS } =
  new Function(GYP_SRC + NL + "return { GYP_BASE, GYP_SHEETS };")();

const MARKUP_RATE_TARGETS = new Function(
  "GYP_SHEETS",
  grab(/^const MARKUP_RATE_TARGETS = \{[\s\S]*?^\};$/m, "MARKUP_RATE_TARGETS") + NL +
  grab(/^GYP_SHEETS\.forEach\(\(s\) => \{ MARKUP_RATE_TARGETS.*$/m, "gyp target extension") + NL +
  "return MARKUP_RATE_TARGETS;"
)(GYP_SHEETS);

const MARKUP_LAYOUT_OF = new Function(
  "GYP_SHEETS",
  grab(/^const MARKUP_LAYOUT_OF = \{[\s\S]*?^\};$/m, "MARKUP_LAYOUT_OF") + NL +
  grab(/^GYP_SHEETS\.forEach\(\(s\) => \{ MARKUP_LAYOUT_OF.*$/m, "gyp layout extension") + NL +
  "return MARKUP_LAYOUT_OF;"
)(GYP_SHEETS);

// ── the estimate page's writer ───────────────────────────────────────────────
/** @param tabs      the live tab bar, base tabs and copies, read fresh inside markupRateTargets
 *  @param active    which tab the estimator is sitting on (pass a copy id to exercise the
 *                   copied-tab refresh, the only place the discarded-cache bug was ever visible)
 *  @param st        state overrides — tab_copies for the copy chains, tab_structs for
 *                   inserted/deleted rows
 *  @param hfReady   false to prove the .xlsx path still gets written when the engine is not up */
function harness(tabs, active, st, hfReady) {
  const cellValues = {};
  const hfCalls = [];
  const refreshCalls = [];
  const fetches = [];
  const state = Object.assign({ tab_copies: [], tab_structs: [] }, st || {});
  // Warm caches, asserted to SURVIVE: refreshActiveGridFromHF used to delete the active sheet's
  // entry and re-fetch, which 404s on a copy (a copy has no server-side worksheet) and rendered
  // "Failed to load".
  const sheetCache = { Epoxy: { sheet: "Epoxy", cells: [] }, Polish: { sheet: "Polish", cells: [] },
                       Copy1: { sheet: "Copy1", cells: [] }, Copy2: { sheet: "Copy2", cells: [] } };
  const HF = {
    ready: hfReady === undefined ? true : !!hfReady,
    setCellValue(sheet, addr, v) { hfCalls.push([sheet, addr, v]); },
  };
  const tabList = tabs || [];
  const activeSheet = active || "Epoxy";

  const deps = {
    state, cellValues, sheetCache, HF, activeSheet, tabs: tabList,
    MARKUP_RATE_TARGETS, MARKUP_LAYOUT_OF, GYP_SHEETS, GYP_BASE,
    console: { warn: () => {} },
    TW: { authHeaders: () => ({ Authorization: "Bearer test" }) },
    // Leaf stubs. refreshActiveGridFromHF itself is LIFTED and runs for real.
    sheetGrid: { querySelector: () => null },
    refreshDomFromHF: (data) => refreshCalls.push(data && data.sheet),
    updateTotalBarFromHF: () => {},
    fetch: null,          // replaced per scenario
    fetches,
  };
  deps.fetch = (url, opts) => {
    fetches.push([url, opts && opts.headers ? Object.keys(opts.headers) : []]);
    return deps._fetchImpl(url, opts);
  };
  deps._fetchImpl = () => Promise.reject(new Error("no fetch configured"));

  // ── lift, in dependency order ─────────────────────────────────────────────
  deps._shiftIdx = lift("_shiftIdx", deps);
  deps.structOpsFor = new Function("state",
    grab(/^function structOpsFor\(sheetId\) .*$/m, "structOpsFor") + NL +
    "return structOpsFor;")(state);
  deps.txAddr = lift("txAddr", deps);
  deps.layoutIdFor = lift("layoutIdFor", deps);
  deps.refreshActiveGridFromHF = lift("refreshActiveGridFromHF", deps);
  deps.shiftDecimalText = lift("shiftDecimalText", deps);
  deps.rateTextFrom = new Function(
    "shiftDecimalText",
    grab(/^const _RATE_LITERAL_RE = .*$/m, "_RATE_LITERAL_RE") + NL +
    grab(/^function rateTextFrom\(formula\) \{[\s\S]*?\n\}/m, "rateTextFrom") + NL +
    "return rateTextFrom;"
  )(deps.shiftDecimalText);
  deps.markupRateTargets = lift("markupRateTargets", deps);

  // THE UNIT UNDER TEST, lifted as one body so `markupRules` is the SAME binding both functions
  // see — see the header. `setRules` is how a scenario files a rule without going through fetch.
  const writerNames = Object.keys(deps);
  const writer = new Function(
    ...writerNames,
    grab(/^let markupRules = \[\];$/m, "markupRules") + NL +
    grab(/^async function loadMarkupRules\(\) \{[\s\S]*?\n\}/m, "loadMarkupRules") + NL +
    grab(/^function applyMarkupRates\(\) \{[\s\S]*?\n\}/m, "applyMarkupRates") + NL +
    "return { loadMarkupRules, applyMarkupRates," + NL +
    "         setRules: (r) => { markupRules = r; }," + NL +
    "         peekRules: () => markupRules };"
  )(...writerNames.map(k => deps[k]));

  return {
    state, cellValues, hfCalls, refreshCalls, sheetCache, fetches, tabs: tabList,
    setFetch: (fn) => { deps._fetchImpl = fn; },
    rateTextFrom: deps.rateTextFrom,
    markupRateTargets: deps.markupRateTargets,
    shiftDecimalText: deps.shiftDecimalText,
    loadMarkupRules: writer.loadMarkupRules,
    applyMarkupRates: writer.applyMarkupRates,
    setRules: writer.setRules,
    peekRules: writer.peekRules,
  };
}

// ── the Markup page's own half ───────────────────────────────────────────────
// Lifted out of the IIFE, so the regexes allow the two-space indent. `reachSentence` reads the
// module-level `LAYOUT`, which is why it is lifted together with a settable one.
const MK = (() => {
  const g = (re, what) => grabFrom(MKSRC, re, what);
  const PRICES_THE_BID = new Function(
    g(/^  var PRICES_THE_BID = \{[\s\S]*?^  \};$/m, "PRICES_THE_BID") + NL +
    "return PRICES_THE_BID;")();
  const body = [
    g(/^  var LAYOUT_NOUN = \{[\s\S]*?^  \};$/m, "LAYOUT_NOUN"),
    g(/^  function nounFor\(layout\) .*$/m, "nounFor"),
    g(/^  var _RATE_LITERAL_RE = .*$/m, "markup.js _RATE_LITERAL_RE"),
    g(/^  function ratePctFrom\(formula\) \{[\s\S]*?^  \}$/m, "ratePctFrom"),
    g(/^  function reachSentence\(r\) \{[\s\S]*?^  \}$/m, "reachSentence"),
  ].join(NL);
  const api = new Function(
    "PRICES_THE_BID",
    "var LAYOUT = '';" + NL + body + NL +
    "return { ratePctFrom, reachSentence, setLayout: (l) => { LAYOUT = l; } };"
  )(PRICES_THE_BID);
  // The built-in constants, so the round trip is asserted against the strings the page actually
  // ships rather than against a retyped copy of them.
  const BUILTIN = new Function(
    g(/^  var GP_5_BANDS = .*$/m, "GP_5_BANDS") + NL +
    g(/^  var HARD_BID = "IF\(hard_bid_on[\s\S]*?;$/m, "HARD_BID") + NL +
    g(/^  var GYP_SOFT_COSTS = '[\s\S]*?;$/m, "GYP_SOFT_COSTS") + NL +
    g(/^  var F = function \(formula\) .*$/m, "F") + NL +
    g(/^  var NOT_ON_TAB = .*$/m, "NOT_ON_TAB") + NL +
    g(/^  var BUILTIN = \{[\s\S]*?^  \};$/m, "BUILTIN") + NL +
    "return BUILTIN;")();
  return Object.assign({ PRICES_THE_BID, BUILTIN }, api);
})();

const ALL_LAYOUTS = ["Epoxy", "Polish", "Seal", "Seal (+Jnts)", "Leveling", "Epoxy blank"]
  .concat(GYP_SHEETS);
const BASE_TABS = ALL_LAYOUTS.map((id) => ({ id, kind: "base" }));
const rule = (layout, line_key, formula, extra) =>
  Object.assign({ id: layout + "/" + line_key, layout, line_key, formula, applies: true },
                extra || {});
/** Every flat line filed at one rate on every markup layout — the fan-out fixture. */
const filedEverywhere = (formula) => {
  const out = [];
  for (const L of ["polish", "seal", "epoxy", "leveling", "gyp"]) {
    for (const k of ["super_pto", "soft_costs", "bond"]) out.push(rule(L, k, formula));
  }
  return out;
};

const out = {};
out.gypSheetCount = GYP_SHEETS.length;
out.gypSheets = GYP_SHEETS;
out.targetTable = MARKUP_RATE_TARGETS;
out.layoutOf = MARKUP_LAYOUT_OF;
out.pricesTheBid = MK.PRICES_THE_BID;
out.builtin = MK.BUILTIN;

// ── 1. FILING NOTHING CHANGES NOTHING — the day-one invariant ────────────────
// markup_rules is verified empty on production (0 rows, 0 deleted). Shipping this must not move
// one existing price until an admin files a rate, and that is asserted rather than reasoned about.
{
  const h = harness(BASE_TABS.concat([{ id: "Copy1", source: "Epoxy", kind: "copy" },
                                      { id: "Copy2", source: "Gyp (FR)", kind: "copy" }]),
                    "Epoxy",
                    { tab_copies: [{ id: "Copy1", source: "Epoxy" },
                                   { id: "Copy2", source: "Gyp (FR)" }] });
  const changed = h.applyMarkupRates();
  out.nothingFiled = {
    changed, cellValues: h.cellValues, hfCalls: h.hfCalls.length,
    refreshCalls: h.refreshCalls,
    targetCount: h.markupRateTargets().length,
  };
}

// ── 2. every degenerate row shape is also a no-op ────────────────────────────
// `applies:false` is the one that is NOT arithmetic: markup.py stores "this line does not exist on
// this tab" (applies=false, formula=NULL) apart from "it exists and prices to nothing"
// (applies=true, formula='0') on purpose, and the writer leaves the cell alone rather than turning
// the first into the second. The tab goes on charging the template's rate; the Markup page's own
// row says so (case 11).
{
  const shapes = {
    appliesFalse: [rule("epoxy", "super_pto", null, { applies: false })],
    appliesFalseWithFormula: [rule("epoxy", "super_pto", "4%", { applies: false })],
    formulaNull: [rule("epoxy", "super_pto", null)],
    formulaEmpty: [rule("epoxy", "super_pto", "")],
    formulaBlank: [rule("epoxy", "super_pto", "  ")],
    otherLayout: [rule("combo", "super_pto", "4%")],
    otherLine: [rule("epoxy", "escalation", "4%")],
  };
  out.degenerate = {};
  for (const name in shapes) {
    const h = harness(BASE_TABS);
    h.setRules(shapes[name]);
    out.degenerate[name] = { changed: h.applyMarkupRates(),
                             keys: Object.keys(h.cellValues), hf: h.hfCalls.length };
  }
}

// ── 3. THE DEFERRAL, by line key and not by formula shape ────────────────────
// "45%" IS a bare percent. It passes the literal guard, and would flatten a 5-, 6- or 7-tier GP
// ladder to one rate — pricing plausibly and wrongly with nothing on screen to show it. Same for a
// gyp soft-costs percent, which would delete a local/away branch, a job-size taper and Kyle's own
// "error" sentinel.
{
  const h = harness(BASE_TABS.concat([{ id: "Copy1", source: "Epoxy", kind: "copy" }]),
                    "Epoxy", { tab_copies: [{ id: "Copy1", source: "Epoxy" }] });
  h.setRules([
    rule("epoxy", "gp", "45%"),
    rule("epoxy", "hard_bid", "-2.5%"),
    rule("polish", "gp", "30%"),
    rule("gyp", "soft_costs", "9%"),
    rule("gyp", "hard_bid", "4%"),
    rule("leveling", "gp", "0.32"),
  ]);
  out.deferredLinesReachNothing = {
    changed: h.applyMarkupRates(),
    keys: Object.keys(h.cellValues),
    hf: h.hfCalls.length,
    // structural, not behavioural: no layout's map may carry either key at all
    keysPerLayout: Object.fromEntries(
      Object.keys(MARKUP_RATE_TARGETS).map(L => [L, Object.keys(MARKUP_RATE_TARGETS[L])])),
  };
}

// ── 4. THE ROUND TRIP: filing a line's own built-in reprices nothing ─────────
// Every built-in string comes from markup.js's own BUILTIN, and the parsed text must land on the
// .xlsx literal EXACTLY. The naive route — `TWMarkup.run("2.7%")` — returns
// 0.027000000000000003 and 0.040999999999999995, and Kyle's ROUNDUP turns that into a dollar more
// on a round sub-total. The pytest module compares each parsed value against the workbook itself.
{
  const rules = [];
  for (const L in MK.BUILTIN) {
    for (const k in MK.BUILTIN[L]) {
      const b = MK.BUILTIN[L][k];
      if (b && b.formula) rules.push(rule(L, k, b.formula));
    }
  }
  const h = harness(BASE_TABS);
  h.setRules(rules);
  out.builtinsFiled = {
    changed: h.applyMarkupRates(),
    cellValues: h.cellValues,
    // what each built-in string parses to, keyed "<layout>/<line_key>"
    parsed: Object.fromEntries(rules.map(r =>
      [r.layout + "/" + r.line_key, h.rateTextFrom(r.formula)])),
    hfMatchesCellValues: h.hfCalls.every(([s, a, v]) => h.cellValues[s + "!" + a] === v),
    everyWriteIsAFormula: Object.values(h.cellValues).every(v => /^=\d/.test(v)),
  };
}

// ── 5. THE FAN-OUT, by EQUALITY. A superset is the PR #432 bug ──────────────
// One filed `seal` row reaches two tabs; one filed `gyp` row reaches five. `epoxy` covers Epoxy
// AND 'Epoxy blank' at DIFFERENT addresses. 'Seal (+Jnts)'!B78 is a mirror of Seal!B78 and must
// stay one; gyp B75 is Kyle's expression and must stay one.
{
  const h = harness(BASE_TABS);
  h.setRules(filedEverywhere("4%"));
  out.fanOut = {
    changed: h.applyMarkupRates(),
    written: Object.keys(h.cellValues).sort(),
    values: h.cellValues,
    hfWritten: h.hfCalls.map(([s, a, v]) => s + "!" + a + " -> " + v).sort(),
  };
}

// ── 6. copies, copies of copies, and structural edits ───────────────────────
{
  // (a) a copy of Polish takes the polish rate at the polish address
  const a = harness([{ id: "Polish" }, { id: "Copy1", source: "Polish", kind: "copy" }],
                    "Polish", { tab_copies: [{ id: "Copy1", source: "Polish" }] });
  a.setRules([rule("polish", "super_pto", "4%")]);
  a.applyMarkupRates();

  // (b) a copy OF a copy resolves through the chain to the gyp layout
  const b = harness([{ id: "Gyp (FR)" }, { id: "Copy1", source: "Gyp (FR)", kind: "copy" },
                     { id: "Copy2", source: "Copy1", kind: "copy" }],
                    "Copy2", { tab_copies: [{ id: "Copy1", source: "Gyp (FR)" },
                                            { id: "Copy2", source: "Copy1" }] });
  b.setRules([rule("gyp", "super_pto", "5%"), rule("gyp", "bond", "1%")]);
  b.applyMarkupRates();

  // A DISTINCT rate per line, so the assertions can tell WHICH line wrote a cell. With one rate
  // on both, a soft-costs value that had slid up into the deleted super_pto's address would be
  // byte-identical to the bug it is meant to rule out. `bond` is filed too and must reach
  // NOTHING: it is unwired while Kyle's D84 double-counts the tax rows, and a structural edit is
  // no reason for that to change.
  const distinct = [rule("polish", "super_pto", "4%"), rule("polish", "soft_costs", "7%"),
                    rule("polish", "bond", "1%")];

  // (c) two rows inserted above the rate cells MOVE them: B69/B70/B78 -> B71/B72/B80
  const c = harness([{ id: "Polish" }, { id: "Copy1", source: "Polish", kind: "copy" }],
                    "Copy1",
                    { tab_copies: [{ id: "Copy1", source: "Polish" }],
                      tab_structs: [{ sheet: "Copy1", kind: "insert_rows", at: 10, count: 2 }] });
  c.setRules(distinct);
  c.applyMarkupRates();

  // (d) a DELETE covering row 69 drops THAT target rather than writing at a stale address — the
  //     case that keeps the screen, the .xlsx and the lock preset agreeing about a cell that is no
  //     longer there. soft_costs (B70 -> B69) and bond (B78 -> B77) still move, so B69 must hold
  //     the SOFT-COSTS rate and 4% must appear nowhere on the copy.
  const d = harness([{ id: "Polish" }, { id: "Copy1", source: "Polish", kind: "copy" }],
                    "Copy1",
                    { tab_copies: [{ id: "Copy1", source: "Polish" }],
                      tab_structs: [{ sheet: "Copy1", kind: "delete_rows", at: 69, count: 1 }] });
  d.setRules(distinct);
  d.applyMarkupRates();

  out.copies = {
    copyOfPolish: { copy1: a.cellValues["Copy1!B69"], base: a.cellValues["Polish!B69"] },
    copyOfCopy: { copy2super: b.cellValues["Copy2!B74"],
                  copy1super: b.cellValues["Copy1!B74"], baseSuper: b.cellValues["Gyp (FR)!B74"],
                  // Reported as a BOOLEAN, not as the value: JSON.stringify drops an undefined
                  // key, so "the assertion read a missing key" and "bond was excluded" would be
                  // the same green.
                  bondWrittenAnywhere: Object.keys(b.cellValues).some(k => /!B83$/.test(k)) },
    insertedRows: {
      moved: [c.cellValues["Copy1!B71"], c.cellValues["Copy1!B72"]],
      bondMoved: c.cellValues["Copy1!B80"] === undefined ? null : c.cellValues["Copy1!B80"],
      staleWritten: ["B69", "B70"]
        .filter(a2 => Object.prototype.hasOwnProperty.call(c.cellValues, "Copy1!" + a2)),
      base: [c.cellValues["Polish!B69"], c.cellValues["Polish!B70"]],
      baseBond: c.cellValues["Polish!B78"] === undefined ? null : c.cellValues["Polish!B78"],
    },
    deletedRow: {
      copyCells: Object.fromEntries(Object.entries(d.cellValues)
        .filter(([k]) => k.startsWith("Copy1!")).sort()),
      superPtoRateAnywhereOnTheCopy: Object.entries(d.cellValues)
        .some(([k, v]) => k.startsWith("Copy1!") && v === "=0.04"),
      base: [d.cellValues["Polish!B69"], d.cellValues["Polish!B70"]],
    },
  };
}

// ── 7. sitting on a COPIED tab: the grid repaints and the cache SURVIVES ────
// The only place the discarded-cache bug was ever visible was a real browser on a copy.
{
  const h = harness([{ id: "Epoxy" }, { id: "Copy1", source: "Epoxy", kind: "copy" }], "Copy1",
                    { tab_copies: [{ id: "Copy1", source: "Epoxy" }] });
  h.setRules([rule("epoxy", "super_pto", "4%")]);
  h.applyMarkupRates();
  out.onACopy = {
    copy1: h.cellValues["Copy1!B75"],
    cachePreserved: "Copy1" in h.sheetCache,
    gridRefreshedFor: h.refreshCalls,
  };

  // …and sitting on a tab that is NOT written still leaves the write in place for the .xlsx.
  const off = harness([{ id: "Polish" }], "Takeoff");
  off.setRules([rule("epoxy", "super_pto", "4%")]);
  off.applyMarkupRates();
  out.offScreenSheet = { epoxy: off.cellValues["Epoxy!B75"], refreshCalls: off.refreshCalls };
}

// ── 8. applied twice is a no-op the second time ─────────────────────────────
// `changed` is what init() saves on, so an idempotent second apply must not collect a save. It is
// also what makes reopening a draft cheap: the rate is already in cellValues.
{
  const h = harness(BASE_TABS);
  h.setRules(filedEverywhere("4%"));
  const first = h.applyMarkupRates();
  const second = h.applyMarkupRates();
  out.idempotent = { first, second, keys: Object.keys(h.cellValues).length };
}

{
  const h = harness(BASE_TABS);
  h.cellValues["Epoxy!B75"] = "=0.025";
  h.setRules(filedEverywhere("4%"));
  out.savedDraftCellsWin = {
    changed: h.applyMarkupRates(),
    epoxySuperPto: h.cellValues["Epoxy!B75"],
    epoxySoftCosts: h.cellValues["Epoxy!B76"],
    wroteSkippedCell: h.hfCalls.some((c) => c.sheet === "Epoxy" && c.addr === "B75"),
  };
}

// ── 9. the .xlsx still gets the write when HyperFormula is not up ───────────
{
  const h = harness(BASE_TABS, "Epoxy", null, false);
  h.setRules([rule("epoxy", "super_pto", "4%")]);
  out.hfNotReady = { changed: h.applyMarkupRates(), epoxy: h.cellValues["Epoxy!B75"],
                     hf: h.hfCalls.length };
}

// ── 10. THE PARSER, adversarially ───────────────────────────────────────────
// The `%` is REQUIRED. Without it the same digits mean a 100x different rate depending on a sign
// the admin may forget — "0.5" would read as fifty percent while a bare "3" was refused, which is
// backwards from anyone's intuition. Refusing to parse and refusing to write are two different
// facts, so both are recorded.
{
  const h = harness(BASE_TABS);
  const accept = ["3%", "13%", "2.7%", "16%", "4.1%", "0%", " 2.7 % ", "0.5%", ".5%", "99.9%",
                  "2.70%", "10%"];
  const refuse = ["", " ", ".", "%", "0", "3", "1", "0.5", ".5", "0.03", "-4%", "+4%", "1/3",
                  "100%", "150%", "abc", "4%%", "2.7.5%", "4 %x", "=4%",
                  "MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 30%))",
                  "IF(hard_bid_on, IF(subtotal>=60000, -4%, IF(local, IF(subtotal>=13000, -2.5%, 0), 0)), 0)",
                  'IF(OR(B5="Yes",B5="No"), IF(B5="Yes",.09,.1) - IF(E69>334900,.05,IF(E69>234450,.035,0)), "error")',
                  null, undefined];
  const wroteFor = (formula) => {
    const g = harness(BASE_TABS);
    g.setRules([rule("epoxy", "super_pto", formula)]);
    g.applyMarkupRates();
    return Object.keys(g.cellValues);
  };
  out.parser = {
    accepted: accept.map(s => [s, h.rateTextFrom(s)]),
    refused: refuse.map(s => [String(s), h.rateTextFrom(s)]),
    // a refusal must also leave cellValues untouched
    refusedWroteNothing: refuse.map(s => [String(s), wroteFor(s)]),
    acceptedWrote: accept.map(s => [s, wroteFor(s)]),
  };
}

// ── 11. the Markup page's own sentence, for every state a row can be in ─────
{
  const row = (line_key, o) => Object.assign(
    { line_key, editable: true, applies: true, formula: "" }, o || {});
  const say = (layout, r) => { MK.setLayout(layout); return MK.reachSentence(r); };
  out.reachSentence = {
    // gp / hard_bid: no address anywhere
    gpPolish: say("polish", row("gp", { formula: "MARKUP(BAND(subtotal, 6500,52%))" })),
    hardBidEpoxy: say("epoxy", row("hard_bid", { formula: "-2.5%" })),
    // bond: unwired on EVERY layout while Kyle's D84 double-counts the tax rows
    bondEpoxy: say("epoxy", row("bond", { formula: "1%" })),
    bondGyp: say("gyp", row("bond", { formula: "0%" })),
    // gyp soft costs: the per-(layout, line) hole
    gypSoftCosts: say("gyp", row("soft_costs", { formula: "9%" })),
    polishSoftCosts: say("polish", row("soft_costs", { formula: "16%" })),
    // nothing filed
    unfiled: say("epoxy", row("super_pto")),
    // filed and reaching, with the resolved percent echoed back
    filed: say("epoxy", row("super_pto", { formula: "4%" })),
    filedSeal: say("seal", row("soft_costs", { formula: "0.5%" })),
    filedGypSuper: say("gyp", row("super_pto", { formula: "4.1%" })),
    // filed but unparseable — the workbook keeps its own rate
    unparseable: say("epoxy", row("super_pto", { formula: "0.04" })),
    // switched off on a line the workbook DOES read: the honest, uncomfortable one
    switchedOff: say("epoxy", row("super_pto", { applies: false })),
    // a read-only line gets nothing appended: test_markup_page.py compares those two strings
    // against markup.py character for character.
    readOnly: say("polish", row("contingency", { editable: false })),
    // an unknown layout falls back to "this tab" and claims nothing
    unknownLayout: say("combo", row("super_pto", { formula: "4%" })),
  };
  // ratePctFrom must agree with rateTextFrom about WHICH formulas reach the workbook. Two copies
  // of one rule in two files; the pytest module asserts they never disagree.
  const h = harness(BASE_TABS);
  const probe = ["3%", "13%", "2.7%", "16%", "4.1%", "0%", " 2.7 % ", "0.5%", ".5%", "99.9%",
                 "", ".", "%", "0", "3", "0.5", "0.03", "-4%", "1/3", "100%", "abc", "4%%",
                 "MARKUP(BAND(subtotal, 6500,52%))"];
  out.parserAgreement = probe.map(s => [s, h.rateTextFrom(s), MK.ratePctFrom(s)]);
}

// ── 12. the fetch: one GET, and any failure prices nothing ──────────────────
{
  const ok = harness(BASE_TABS);
  ok.setFetch(() => Promise.resolve({
    ok: true, status: 200,
    json: () => Promise.resolve({ ok: true, rules: [rule("epoxy", "super_pto", "4%")],
                                  layouts: ["polish"], line_keys: ["super_pto"] }),
  }));

  const bad = harness(BASE_TABS);
  bad.setFetch(() => Promise.resolve({ ok: false, status: 500, json: () => Promise.reject() }));

  const thrown = harness(BASE_TABS);
  thrown.setFetch(() => Promise.reject(new Error("offline")));

  const junk = harness(BASE_TABS);
  junk.setFetch(() => Promise.resolve({ ok: true, status: 200,
                                        json: () => Promise.resolve({ ok: true }) }));

  Promise.all([ok.loadMarkupRules(), bad.loadMarkupRules(), thrown.loadMarkupRules(),
               junk.loadMarkupRules()]).then((counts) => {
    out.load = {
      counts,
      okUrl: ok.fetches[0][0],
      okSentAuth: ok.fetches[0][1],
      okApplied: ok.applyMarkupRates(),
      okEpoxy: ok.cellValues["Epoxy!B75"],
      badApplied: bad.applyMarkupRates(),
      badKeys: Object.keys(bad.cellValues),
      thrownApplied: thrown.applyMarkupRates(),
      junkApplied: junk.applyMarkupRates(),
    };
    // ── 13. the userFormula gate, executed ────────────────────────────────
    // refreshDomFromHF repaints a cell only when the template cell is a formula OR cellValues
    // holds a "="-prefixed string. All 27 targets are PLAIN numbers in the template, so this
    // predicate is the entire reason the write is `=0.04` and not `0.04`. Executed, from the
    // shipped line, so a change to the gate fails here instead of on a bid.
    const gateSrc = grab(/^    const userFormula = typeof uVal === "string".*$/m, "userFormula gate");
    const gate = new Function("uVal", gateSrc + NL + "return userFormula;");
    out.userFormulaGate = [["=0.04", gate("=0.04")], ["=0", gate("=0")], ["0.04", gate(0.04)],
                           ["'0.04'", gate("0.04")], ["null", gate(null)]];
    console.log(JSON.stringify(out));
  }).catch((e) => { console.error((e && e.stack) || String(e)); process.exit(1); });
}
