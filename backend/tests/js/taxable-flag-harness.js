"use strict";
/* Execute the real Taxable? / Remodel Tax? fan-out out of estimate-review.js.
 *
 * WHY EXECUTED. This bug is the canonical example of one a source read cannot find. Every line
 * involved reads perfectly: `copyTab` clones the source and replays its edits, `canonicalTarget`
 * shares the project-info block, the intake writes the estimator's answer to a cell. The defect
 * was that the answer never REACHED three of the four cells that hold it, and on a copied tab it
 * reached none of them -- so the box said "No" while the sheet it was painted from said "Yes" and
 * the customer was billed 9.475% on a tax-exempt job. Nothing about the source text is wrong.
 * Only running it and looking at the cells can tell you.
 *
 * So this harness runs the SHIPPED `copyTab` (not a re-implementation of it) against stub DOM /
 * HF, and inspects the `cellValues` map and the engine writes that come out -- which is exactly
 * what `estimate_writer.fill_estimate`'s cell_values step and the live HyperFormula engine
 * consume. The workbook half -- that each sheet's sales-tax rate really does read the cell being
 * written -- is asserted against the real .xlsx in test_taxable_flag_reaches_every_sheet.py.
 *
 * The grid's cell-edit listener is an anonymous closure inside `makeDataCell`, whose body needs
 * ~40 DOM APIs to instantiate. It is GRABBED verbatim from the file and run as itself instead:
 * the same bytes, including the `addEventListener("input"` it is registered under, so deleting or
 * renaming the fan-out call fails here. What that cannot see is the listener being detached
 * altogether, which is why `test_the_flag_cells_are_ordinary_editable_grid_cells` pins the other
 * half from the workbook.
 *
 * Usage: node taxable-flag-harness.js <frontend-dir> [<sheet-names-json>]   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(process.argv[2], "js", "estimate-review.js"), "utf8");
const NL = String.fromCharCode(10);

function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + what + " -- rewrite this harness, don't stub it");
  return m[0];
}

/** A top-level `function name(...) {...}` out of the real file, bound to `deps` BY NAME.
 *  Dependency order matters: a callee missing from `deps` at lift time is an unbound
 *  identifier inside the lifted copy -- the failure mode that took the board down on prod. */
function lift(name, deps) {
  const re = new RegExp("^function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name + " -- rewrite this harness, don't stub it");
  const names = Object.keys(deps);
  return new Function(...names, m[0] + NL + "return " + name + ";")(...names.map(k => deps[k]));
}

/** A one-line `const name = ...;` / `function name() { ... }`, evaluated with its own deps. */
function liftExpr(re, name, deps) {
  const names = Object.keys(deps);
  return new Function(...names, grab(re, name) + NL + "return " + name + ";")(...names.map(k => deps[k]));
}

// ── the SHIPPED vocabulary ──────────────────────────────────────────────────
// Sheet names, role maps and the flag maps all come out of the real file, so this harness
// cannot disagree with the app about which sheet holds which answer.
const VOCAB = (() => {
  const src = [
    grab(/^const CANONICAL_SHEET = .*$/m, "CANONICAL_SHEET"),
    grab(/^const GYP_BASE = .*$/m, "GYP_BASE"),
    grab(/^const GYP_SHEETS = \[[\s\S]*?\];$/m, "GYP_SHEETS"),
    grab(/^const SEAL_SHEETS = \[[\s\S]*?\];$/m, "SEAL_SHEETS"),
    grab(/^const BASE_ROLE = \{[\s\S]*?\};$/m, "BASE_ROLE"),
    grab(/^GYP_SHEETS\.forEach\(\(s\) => \{ BASE_ROLE.*$/m, "the gyp role loop"),
    grab(/^SEAL_SHEETS\.forEach\(\(s\) => \{ BASE_ROLE.*$/m, "the seal role loop"),
    grab(/^const PRICED_ROLES = new Set\(\[[^\]]*\]\);$/m, "PRICED_ROLES"),
    grab(/^const OPTION_ONLY_ROLES = new Set\(\[[^\]]*\]\);$/m, "OPTION_ONLY_ROLES"),
    grab(/^const MAX_COPIES = .*$/m, "MAX_COPIES"),
    // The three maps under test. Lifted, never re-typed: a hand-copied address here would
    // agree with itself and with nothing the estimator downloads.
    grab(/^const JOB_FLAG_ADDR = \{[\s\S]*?^\};$/m, "JOB_FLAG_ADDR"),
    grab(/^const JOB_FLAG_LITERAL_LAYOUTS = \{[\s\S]*?^\};$/m, "JOB_FLAG_LITERAL_LAYOUTS"),
    grab(/^const JOB_FLAG_LAYOUTS = \[[\s\S]*?\);$/m, "JOB_FLAG_LAYOUTS"),
  ].join(NL);
  return new Function(src + NL + "return { CANONICAL_SHEET, GYP_BASE, GYP_SHEETS, SEAL_SHEETS," +
    " BASE_ROLE, PRICED_ROLES, OPTION_ONLY_ROLES, MAX_COPIES, JOB_FLAG_ADDR," +
    " JOB_FLAG_LITERAL_LAYOUTS, JOB_FLAG_LAYOUTS };")();
})();

// The workbook's own tab list, handed in by the Python test so the fixture is anchored to the
// shipped .xlsx rather than to a list typed in here. The fallback keeps the harness runnable on
// its own; the test always passes the real one.
const SHEET_NAMES = process.argv[3]
  ? JSON.parse(process.argv[3])
  : ["Epoxy", "Polish", VOCAB.GYP_BASE, "Takeoff", "Seal", "Seal (+Jnts)", "Epoxy blank",
     "Stnd Alts", "Leveling"].concat(VOCAB.GYP_SHEETS.slice(1));

// Every sheet that can hold a flag, with the two flag rows populated the way the shipped
// template populates them: a literal on the four independent sheets, the real mirror formula
// everywhere else. Taken from JOB_FLAG_LITERAL_LAYOUTS so the fixture cannot drift from the fix.
const GYPish = (n) => /^Gyp/i.test(n);
function templateGrid(name) {
  const gyp = GYPish(name);
  const tRow = gyp ? 8 : 6;
  const rRow = gyp ? 8 : 6;
  const taxLiteral = VOCAB.JOB_FLAG_LITERAL_LAYOUTS.taxable.indexOf(name) >= 0;
  const remLiteral = VOCAB.JOB_FLAG_LITERAL_LAYOUTS.remodel.indexOf(name) >= 0;
  const taxMirror = gyp ? "='" + VOCAB.GYP_BASE + "'!B8" : "=Epoxy!B6";
  const remMirror = "=Epoxy!D6";
  const cells = [
    // the project-info cells the A1:D10 skip exists to protect
    { addr: "B1", row: 1, col: 2, value: "Westport Commons" },
    { addr: "B2", row: 2, col: 2, value: "2026-09-04" },
    { addr: "B3", row: 3, col: 2, value: "1200 Main St" },
    // the flag block
    { addr: "B" + tRow, row: tRow, col: 2,
      value: taxLiteral ? "Yes" : null, formula: taxLiteral ? null : taxMirror },
    { addr: "D" + rRow, row: rRow, col: 4,
      value: remLiteral ? "No" : null, formula: remLiteral ? null : remMirror },
    // a cell well outside A1:D10, to prove ordinary edits are untouched by any of this
    { addr: "E20", row: 20, col: 5, value: 4200 },
  ];
  return cells;
}

/** One page's worth of state: the shipped copyTab, cell-edit listener and fan-out, wired to
 *  stub DOM/HF. `opts.cellValues` seeds a draft; `opts.tabCopies` seeds copies made earlier. */
function harness(opts) {
  opts = opts || {};
  const sheets = SHEET_NAMES.slice();
  const state = Object.assign({
    work_type: "epoxy", base_tab_id: null, tab_copies: [], tab_labels: {}, tab_order: [],
    tab_opts: {}, tab_structs: [], lock_overrides: {},
  }, opts.state || {});
  state.tab_copies = (opts.tabCopies || state.tab_copies || []).slice();
  state.tab_structs = (opts.tabStructs || state.tab_structs || []).slice();
  const cellValues = Object.assign({}, opts.cellValues || {});
  const activeSheet = opts.activeSheet || "Epoxy";

  const sheetCache = {};
  for (const n of sheets) sheetCache[n] = { sheet: n, cells: templateGrid(n) };
  // A copy seeded into the fixture gets a cache entry the same way init()'s rehydration and
  // copyTab both build one -- cloned from its source. Without it refreshActiveGridFromHF has
  // nothing to redraw and the "sitting on a copy" cases would prove nothing.
  for (const c of state.tab_copies) {
    const src = sheetCache[c.source];
    if (src && !sheetCache[c.id]) sheetCache[c.id] = { sheet: c.id, cells: src.cells };
  }

  // A stub engine that actually REMEMBERS values, because "the copy's box said No while its own
  // engine held Yes" is the report, and only a reading engine can show that.
  const hfValues = {};
  const hfCalls = [];
  const hfSheets = new Set(sheets);
  const HF = {
    ready: true,
    createSheet(name) { if (hfSheets.has(name)) return false; hfSheets.add(name); return true; },
    loadSheet(name, cells) {
      hfValues[name] = {};
      for (const c of (cells || [])) {
        hfValues[name][c.addr] = c.formula != null ? c.formula : c.value;
      }
    },
    setCellValue(sheet, addr, v) {
      hfCalls.push([sheet, addr, v]);
      (hfValues[sheet] = hfValues[sheet] || {})[addr] = v;
      return [];
    },
    getValue(sheet, addr) {
      const s = hfValues[sheet];
      return s && Object.prototype.hasOwnProperty.call(s, addr) ? s[addr] : null;
    },
  };
  for (const n of sheets) HF.loadSheet(n, sheetCache[n].cells);
  for (const k of Object.keys(cellValues)) {
    const i = k.indexOf("!");
    if (i > 0) HF.setCellValue(k.slice(0, i), k.slice(i + 1), cellValues[k]);
  }
  hfCalls.length = 0;               // the seeding above is fixture, not behaviour

  const setStateCalls = [];
  const TW = { setState: (p) => {
    try { setStateCalls.push(JSON.parse(JSON.stringify(p))); } catch (e) { setStateCalls.push(p); }
  } };
  const alerts = [];
  const shown = [];
  const refreshCalls = [];

  let tabs = [];
  const deps = {
    // shipped constants
    CANONICAL_SHEET: VOCAB.CANONICAL_SHEET, GYP_BASE: VOCAB.GYP_BASE,
    GYP_SHEETS: VOCAB.GYP_SHEETS, BASE_ROLE: VOCAB.BASE_ROLE,
    PRICED_ROLES: VOCAB.PRICED_ROLES, OPTION_ONLY_ROLES: VOCAB.OPTION_ONLY_ROLES,
    MAX_COPIES: VOCAB.MAX_COPIES, JOB_FLAG_ADDR: VOCAB.JOB_FLAG_ADDR,
    JOB_FLAG_LITERAL_LAYOUTS: VOCAB.JOB_FLAG_LITERAL_LAYOUTS,
    JOB_FLAG_LAYOUTS: VOCAB.JOB_FLAG_LAYOUTS,
    // page state
    state, cellValues, sheetCache, sheets, HF, TW, activeSheet,
    tabs,                                  // replaced below with the live array
    alert: (m) => alerts.push(m),
    // leaf stubs. `refreshActiveGridFromHF` itself is LIFTED and runs for real -- stubbing it
    // would stub out the cache-preservation the copy path depends on.
    sheetGrid: { querySelector: () => null },
    refreshDomFromHF: (data) => refreshCalls.push(data && data.sheet),
    updateTotalBarFromHF: () => {},
    renderTabs: () => {},
    showSheet: (id) => { shown.push(id); },
    propagateChangesToDom: () => {},
    _bulkWrite: false,
    // Covered end to end by remodel-rate-harness.js; recorded here only so copyTab dropping the
    // call is still a failure somewhere.
    remodelCalls: [],
    effectiveRemodelRate: () => null,
  };
  deps.tabs = tabs;
  deps.applyRemodelRateOverride = (r) => { deps.remodelCalls.push(r); };

  // ── lift, in dependency order ──────────────────────────────────────────────
  deps.labelFor = liftExpr(/^const labelFor = .*$/m, "labelFor", { state });
  deps._shiftIdx = lift("_shiftIdx", deps);
  deps.structOpsFor = liftExpr(/^function structOpsFor\(sheetId\) .*$/m, "structOpsFor", { state });
  deps.txAddr = lift("txAddr", deps);
  deps.roleFor = lift("roleFor", deps);
  deps.layoutIdFor = lift("layoutIdFor", deps);
  deps.isPricedRole = liftExpr(/^const isPricedRole = .*$/m, "isPricedRole",
                               { PRICED_ROLES: VOCAB.PRICED_ROLES });
  deps.isOptionOnlyRole = liftExpr(/^const isOptionOnlyRole = .*$/m, "isOptionOnlyRole",
                                   { OPTION_ONLY_ROLES: VOCAB.OPTION_ONLY_ROLES });
  deps.pricedTabs = liftExpr(/^function pricedTabs\(\) .*$/m, "pricedTabs",
                             { tabs, isPricedRole: deps.isPricedRole });
  deps.basePricedTabs = liftExpr(/^const basePricedTabs = .*$/m, "basePricedTabs",
                                 { pricedTabs: deps.pricedTabs, isOptionOnlyRole: deps.isOptionOnlyRole });
  deps.resolveBaseTab = lift("resolveBaseTab", deps);
  deps.isProjectInfoCell = lift("isProjectInfoCell", deps);
  deps.canonicalSheetFor = lift("canonicalSheetFor", deps);
  deps.canonicalTarget = lift("canonicalTarget", deps);
  deps.canonicalKey = lift("canonicalKey", deps);
  deps.allLabels = lift("allLabels", deps);
  deps.uniqueLabel = lift("uniqueLabel", deps);
  deps.nextCopyId = lift("nextCopyId", deps);
  deps.orderedIds = lift("orderedIds", deps);
  deps.refreshActiveGridFromHF = lift("refreshActiveGridFromHF", deps);
  // THE UNITS UNDER TEST
  deps.jobFlagAddrFor = lift("jobFlagAddrFor", deps);
  deps.jobFlagKindFor = lift("jobFlagKindFor", deps);
  deps.jobFlagTargets = lift("jobFlagTargets", deps);
  deps.jobFlagAnswer = lift("jobFlagAnswer", deps);
  deps.applyJobFlag = lift("applyJobFlag", deps);
  deps.applyJobFlags = lift("applyJobFlags", deps);

  // buildTabs is the ONE thing stubbed rather than lifted, and only because the shipped one
  // REASSIGNS the module-level `tabs` (`tabs = orderedIds().map(...)`), which inside a lifted
  // copy would rebind its own parameter and leave every other lifted function holding the old
  // array. Same composition, mutated in place, over the real orderedIds/roleFor/labelFor.
  deps.buildTabs = function buildTabs() {
    const byId = {};
    for (const id of sheets) byId[id] = { id, label: deps.labelFor(id), role: deps.roleFor(id), kind: "base" };
    for (const c of state.tab_copies)
      byId[c.id] = { id: c.id, label: deps.labelFor(c.id), role: c.role || "epoxy", kind: "copy", source: c.source };
    const next = deps.orderedIds().map(id => byId[id]).filter(Boolean);
    tabs.length = 0;
    for (const t of next) tabs.push(t);
  };
  deps.buildTabs();

  const copyTab = lift("copyTab", deps);

  // The grid's cell-edit listener, verbatim. See the header for why it is grabbed rather than
  // reached through makeDataCell.
  const listenerSrc = (() => {
    const m = /inp\.addEventListener\("input", (\(e\) => \{[\s\S]*?\n  \})\);/.exec(SRC);
    if (!m) throw new Error("the grid's input listener moved -- rewrite this harness");
    return m[1];
  })();
  /** Type `newVal` into `sheet`'s `addr`, through the real listener. */
  function typeInto(sheet, addr, newVal, originalVal) {
    const cell = { addr };
    const addrKey = deps.canonicalKey(sheet, addr);
    const names = ["cellValues", "addrKey", "original", "HF", "canonicalTarget", "sheet", "cell",
                   "isPctCell", "_bulkWrite", "propagateChangesToDom", "updateTotalBarFromHF",
                   "jobFlagKindFor", "applyJobFlag"];
    const vals = [cellValues, addrKey, originalVal === undefined ? "" : originalVal, HF,
                  deps.canonicalTarget, sheet, cell, false, false,
                  deps.propagateChangesToDom, deps.updateTotalBarFromHF,
                  deps.jobFlagKindFor, deps.applyJobFlag];
    const fn = new Function(...names, "return " + listenerSrc + ";")(...vals);
    fn({ target: { value: newVal } });
  }

  return {
    state, cellValues, sheetCache, tabs, hfCalls, hfValues, setStateCalls, alerts, shown,
    refreshCalls, remodelCalls: deps.remodelCalls, copyTab, typeInto,
    jobFlagTargets: deps.jobFlagTargets, jobFlagAnswer: deps.jobFlagAnswer,
    jobFlagKindFor: deps.jobFlagKindFor, applyJobFlags: deps.applyJobFlags,
    applyJobFlag: deps.applyJobFlag, canonicalTarget: deps.canonicalTarget,
    hfAt: (s, a) => HF.getValue(s, a),
  };
}

const out = {};
out.sheetNames = SHEET_NAMES;
out.literalLayouts = VOCAB.JOB_FLAG_LITERAL_LAYOUTS;
out.flagAddr = VOCAB.JOB_FLAG_ADDR;

// ── 1. the target list on a bid with no copies ──────────────────────────────
// Four cells for Taxable, one for Remodel, and NOT ONE mirror sheet among them.
{
  const h = harness();
  out.baseTargets = {
    taxable: h.jobFlagTargets("taxable"),
    remodel: h.jobFlagTargets("remodel"),
  };
}

// ── 2. the answer reaches every literal sheet, and no mirror ────────────────
{
  const h = harness({ cellValues: { "Epoxy!B6": "No" } });
  const before = Object.keys(h.cellValues).length;
  const changed = h.applyJobFlags();
  out.baseFanout = {
    written: h.cellValues,
    changed: changed,
    seededCount: before,
    // the on-screen engine got the same answer, cell for cell
    hfMatches: h.hfCalls.every(([s, a, v]) => h.cellValues[s + "!" + a] === v),
    hfCallCount: h.hfCalls.length,
  };
}

// ── 3. a TAXABLE job is still taxable -- the fix did not just switch tax off ─
{
  const h = harness({ cellValues: { "Epoxy!B6": "Yes" } });
  h.applyJobFlags();
  out.taxableStaysTaxable = h.cellValues;
}

// ── 4. an untouched draft collects nothing ──────────────────────────────────
// Every one of these cells already holds the template's own default, so writing them back would
// only grow the blob. Same rule the remodel-rate self-heal applies to itself.
{
  const h = harness();
  const changed = h.applyJobFlags();
  out.untouched = { changed: changed, keys: Object.keys(h.cellValues) };
}

// ── 5. THE REPORT: copy a tab on a tax-exempt job ───────────────────────────
// One case per copyable source layout. `copyTab` is the shipped one.
{
  const perSource = {};
  for (const src of SHEET_NAMES) {
    if (src === "Takeoff" || src === "Stnd Alts" || src === "Specs+Dwgs+Addn" ||
        src === "validation" || src === "Unit Layouts") continue;
    const h = harness({ cellValues: { "Epoxy!B6": "No", "Epoxy!D6": "Yes" } });
    h.applyJobFlags();                       // the answer, as the page would already hold it
    h.copyTab(src);
    const copy = h.state.tab_copies[h.state.tab_copies.length - 1];
    const gyp = /^Gyp/i.test(src);
    const tAddr = gyp ? "B8" : "B6";
    const rAddr = gyp ? "D8" : "D6";
    const tKey = copy ? copy.id + "!" + tAddr : "";
    const rKey = copy ? copy.id + "!" + rAddr : "";
    perSource[src] = {
      copyId: copy ? copy.id : null,
      // What the DOWNLOADED workbook gets: an explicit answer, or nothing (leaving the clone's
      // own cell -- a literal 'Yes' on four layouts, a live mirror on the rest). Written as
      // present/absent booleans as well as values, because JSON drops an undefined.
      taxWritten: tKey in h.cellValues, remodelWritten: rKey in h.cellValues,
      taxCellValue: copy && (tKey in h.cellValues) ? h.cellValues[tKey] : null,
      remodelCellValue: copy && (rKey in h.cellValues) ? h.cellValues[rKey] : null,
      // What the ENGINE behind the on-screen chip and total holds. This is the number Kyle saw
      // disagree with the box: 'Yes' in the engine, "No" on screen.
      taxInEngine: copy ? h.hfAt(copy.id, tAddr) : null,
      remodelInEngine: copy ? h.hfAt(copy.id, rAddr) : null,
      // the copy's cache survived the fan-out's grid refresh (see remodel-rate case 10)
      cacheAlive: copy ? !!h.sheetCache[copy.id] : false,
      // and the remodel RATE stamp still runs on a copy
      remodelRateApplied: h.remodelCalls.length,
    };
  }
  out.copies = perSource;
}

// ── 6. a copy of a copy, and a copy made BEFORE the answer was given ────────
{
  const h = harness({ cellValues: { "Epoxy!B6": "No" } });
  h.copyTab("Epoxy");                                    // copy first...
  const c1 = h.state.tab_copies[0].id;
  h.copyTab(c1);                                         // ...and a copy of the copy
  const c2 = h.state.tab_copies[1].id;
  out.copyChain = {
    c1: h.cellValues[c1 + "!B6"], c2: h.cellValues[c2 + "!B6"],
    c1Engine: h.hfAt(c1, "B6"), c2Engine: h.hfAt(c2, "B6"),
  };

  // ...and the other order: the copies already existed, the answer arrives now.
  const h2 = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" },
                                   { id: "Copy2", source: "Copy1", role: "epoxy" },
                                   { id: "Copy3", source: VOCAB.GYP_BASE, role: "gyp" }],
                       cellValues: { "Epoxy!B6": "No" } });
  h2.applyJobFlags();
  out.answerAfterCopy = {
    copy1: h2.cellValues["Copy1!B6"], copy2: h2.cellValues["Copy2!B6"],
    copy3: h2.cellValues["Copy3!B8"],
    copy3NotB6: h2.cellValues["Copy3!B6"] === undefined,   // B6 on a gyp layout is "Miles Away"
  };
}

// ── 7. a copy of a MIRROR layout keeps its mirror ───────────────────────────
// Polish/Seal/'Seal (+Jnts)'/'Epoxy blank'!B6 and the three mirroring gyp B8 are live references.
// openpyxl's copy_worksheet keeps `=Epoxy!B6` pointing at Epoxy, so the clone already follows the
// master; stamping a literal there would fork it for good.
{
  const h = harness({ cellValues: { "Epoxy!B6": "No" } });
  h.applyJobFlags();
  h.copyTab("Polish");
  h.copyTab("Gyp (USG N12ULTRA)");
  const ids = h.state.tab_copies.map(c => c.id);
  out.mirrorCopies = {
    polishCopyWritten: ids.map(i => h.cellValues[i + "!B6"]).filter(v => v !== undefined).length,
    gypVariantCopyWritten: ids.map(i => h.cellValues[i + "!B8"]).filter(v => v !== undefined).length,
    // the clone still carries the reference, so it answers "No" without being written
    polishCopyEngine: h.hfAt(ids[0], "B6"),
    gypVariantCopyEngine: h.hfAt(ids[1], "B8"),
  };
}

// ── 8. typing in the box, through the real listener ─────────────────────────
{
  // ...on the master
  const a = harness();
  a.typeInto("Epoxy", "B6", "No", "Yes");
  // ...on a MIRROR tab, whose keystroke canonicalTarget has always routed to the master. The
  // open tab is Polish, which is NOT one of the four written cells -- so this is the case that
  // would silently keep showing the pre-edit total.
  const b = harness({ activeSheet: "Polish" });
  b.typeInto("Polish", "B6", "No", "Yes");
  // ...on a COPY, which is what Kyle tried and which could not work before
  const c = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }],
                      activeSheet: "Copy1" });
  c.typeInto("Copy1", "B6", "No", "Yes");
  // ...on a GYP tab, whose flag is B8 and whose canonical is the gyp base, not Epoxy
  const d = harness({ state: { work_type: "gyp", base_tab_id: VOCAB.GYP_BASE },
                      activeSheet: "Gyp (USG N25 1-4\")" });
  d.typeInto("Gyp (USG N25 1-4\")", "B8", "No", "Yes");
  // ...and retyping the ORIGINAL answer has to reach every cell too, or the copies keep the
  // answer that was just retracted (the delete-on-revert branch would have done exactly that).
  const e = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }] });
  e.typeInto("Epoxy", "B6", "No", "Yes");
  e.typeInto("Epoxy", "B6", "Yes", "Yes");
  out.typed = {
    master: a.cellValues, mirrorTab: b.cellValues, onACopy: c.cellValues,
    gypTab: d.cellValues,
    // The open tab is redrawn from the engine in every case -- including the three where the
    // tab being typed on is NOT one of the four written cells. Its own B6 is a mirror and its
    // totals recompute from it, so without this the price on screen stays at the old one.
    gridRefreshed: { master: a.refreshCalls, mirrorTab: b.refreshCalls,
                     onACopy: c.refreshCalls, gypTab: d.refreshCalls },
    cachesAlive: [a, b, c, d].every(h => Object.keys(h.sheetCache).length > 0),
    revert: { epoxy: e.cellValues["Epoxy!B6"], copy: e.cellValues["Copy1!B6"] },
    // the remodel twin: same box, one row across
    remodelOnACopy: (() => {
      const h = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }] });
      h.typeInto("Copy1", "D6", "Yes", "No");
      return { epoxy: h.cellValues["Epoxy!D6"], copy: h.cellValues["Copy1!D6"],
               copyEngine: h.hfAt("Copy1", "D6") };
    })(),
  };
}

// ── 9. an ORDINARY cell edit is untouched by all of this ────────────────────
// The fan-out must fire for two addresses per layout and nothing else -- including the cells
// around them in the same block (Local?, Hard Bid?, Prevailing Wage, Miles Away).
{
  const h = harness();
  h.typeInto("Epoxy", "E20", "5000", "4200");
  h.typeInto("Epoxy", "B4", "No", "Yes");           // Local? -- NOT ours (see Issue 5)
  h.typeInto("Epoxy", "B5", "Yes", "No");           // Hard Bid? -- likewise
  h.typeInto("Epoxy", "D5", "Yes", "No");           // Prevailing Wage -- a mirror everywhere
  h.typeInto(VOCAB.GYP_BASE, "B6", "12", "0");      // "Miles Away" on a gyp layout, NOT Taxable
  out.ordinaryEdits = h.cellValues;
  out.kinds = {
    epoxyB6: h.jobFlagKindFor("Epoxy", "B6"),
    epoxyD6: h.jobFlagKindFor("Epoxy", "D6"),
    epoxyB4: h.jobFlagKindFor("Epoxy", "B4"),
    gypB6: h.jobFlagKindFor(VOCAB.GYP_BASE, "B6"),
    gypB8: h.jobFlagKindFor(VOCAB.GYP_BASE, "B8"),
    gypD8: h.jobFlagKindFor(VOCAB.GYP_BASE, "D8"),
    takeoffB6: h.jobFlagKindFor("Takeoff", "B6"),
    copyOfGypB8: (() => {
      const g = harness({ tabCopies: [{ id: "Copy1", source: "Gyp (FR)", role: "gyp" }] });
      return [g.jobFlagKindFor("Copy1", "B8"), g.jobFlagKindFor("Copy1", "B6")];
    })(),
  };
}

// ── 10. the project-info redirect keeps working where it is RIGHT ───────────
// The A1:D10 skip and the canonical redirect exist to share project name / bid date / address
// across tabs. This fix must not fork that block.
{
  const h = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }] });
  out.projectInfoStillShared = {
    b1: h.canonicalTarget("Copy1", "B1"),
    b2: h.canonicalTarget("Copy1", "B2"),
    b3: h.canonicalTarget("Copy1", "B3"),
    gypB2: harness().canonicalTarget("Gyp (USG N12ULTRA)", "B2"),
  };
  h.typeInto("Copy1", "B1", "New Name", "Westport Commons");
  out.projectInfoStillShared.typedB1 = { onMaster: h.cellValues["Epoxy!B1"],
                                         forkedOntoTheCopy: "Copy1!B1" in h.cellValues };
}

// ── 11. structural edits: the write follows the row, or is skipped ──────────
{
  // two rows inserted above the flag block -> Epoxy's B6 is now B8
  const moved = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }],
                          tabStructs: [{ sheet: "Copy1", kind: "insert_rows", at: 2, count: 2 }],
                          cellValues: { "Epoxy!B6": "No" } });
  moved.applyJobFlags();
  // the flag ROW deleted outright -> txAddr returns null and the target is dropped, never
  // written at a stale address
  const gone = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }],
                         tabStructs: [{ sheet: "Copy1", kind: "delete_rows", at: 6, count: 1 }],
                         cellValues: { "Epoxy!B6": "No" } });
  gone.applyJobFlags();
  out.structural = {
    movedTargets: moved.jobFlagTargets("taxable").filter(t => t[0] === "Copy1"),
    movedWritten: moved.cellValues["Copy1!B8"],
    movedNotAtStale: moved.cellValues["Copy1!B6"] === undefined,
    goneTargets: gone.jobFlagTargets("taxable").filter(t => t[0] === "Copy1"),
    goneWrittenAnywhere: Object.keys(gone.cellValues).filter(k => k.indexOf("Copy1!") === 0),
    // the remodel toggle on the same shifted tab moves with it (D6 -> D8)
    movedRemodelTargets: moved.jobFlagTargets("remodel").filter(t => t[0] === "Copy1"),
  };
}

// ── 12. the two canonical stores, and which wins ────────────────────────────
// `canonicalSheetFor` splits project info by FAMILY: an epoxy-family keystroke lands on Epoxy!B6,
// a gyp one on the gyp base's B8. A draft made before this fix can hold two different explicit
// answers, and only in one shape -- the intake wrote Epoxy!B6 and the estimator then typed the
// real answer into the gyp tab, which is the workaround being handed out for this bug.
{
  const gypJob = harness({
    state: { work_type: "gyp", base_tab_id: VOCAB.GYP_BASE },
    cellValues: { "Epoxy!B6": "Yes", [VOCAB.GYP_BASE + "!B8"]: "No" },
  });
  const epoxyJob = harness({
    state: { work_type: "epoxy", base_tab_id: "Epoxy" },
    cellValues: { "Epoxy!B6": "No", [VOCAB.GYP_BASE + "!B8"]: "Yes" },
  });
  const onlyGyp = harness({
    state: { work_type: "gyp", base_tab_id: VOCAB.GYP_BASE },
    cellValues: { [VOCAB.GYP_BASE + "!B8"]: "No" },
  });
  gypJob.applyJobFlags(); epoxyJob.applyJobFlags(); onlyGyp.applyJobFlags();
  out.twoStores = {
    gypJobAnswer: gypJob.cellValues["Epoxy!B6"],
    gypJobGyp: gypJob.cellValues[VOCAB.GYP_BASE + "!B8"],
    epoxyJobAnswer: epoxyJob.cellValues[VOCAB.GYP_BASE + "!B8"],
    epoxyJobEpoxy: epoxyJob.cellValues["Epoxy!B6"],
    onlyGypReaches: onlyGyp.cellValues["Epoxy!B6"],
    blankAnswer: harness().jobFlagAnswer("taxable"),
    emptyStringIsNoAnswer: harness({ cellValues: { "Epoxy!B6": "" } }).jobFlagAnswer("taxable"),
  };
}

// ── 13. a remodel toggle a previous version already forked is kept in step ──
// The gyp base's D8 is `=Epoxy!D6`, but canonicalTarget has always routed a gyp tab's Remodel
// keystroke onto it, so drafts exist carrying a literal there. Left alone it would outrank the
// master and go on charging a remodel tax the estimator switched off.
{
  const forked = harness({
    state: { work_type: "epoxy", base_tab_id: "Epoxy" },
    cellValues: { "Epoxy!D6": "No", [VOCAB.GYP_BASE + "!D8"]: "Yes" },
  });
  forked.applyJobFlags();
  const clean = harness({ cellValues: { "Epoxy!D6": "Yes" } });
  clean.applyJobFlags();
  out.forkedRemodel = {
    keptInStep: forked.cellValues[VOCAB.GYP_BASE + "!D8"],
    master: forked.cellValues["Epoxy!D6"],
    // and with no fork present, the mirror is left strictly alone
    cleanTargets: clean.jobFlagTargets("remodel"),
    cleanKeys: Object.keys(clean.cellValues),
  };
}

// ── 14. the self-heal a real in-flight draft needs ──────────────────────────
// Exactly the shape Kyle's job is in right now: the intake wrote Epoxy!B6="No", a copy was made,
// and nothing else was ever written. Re-opening the draft has to fix all of it.
{
  const h = harness({ cellValues: { "Epoxy!B6": "No" },
                      tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }] });
  const changed = h.applyJobFlags();
  const again = h.applyJobFlags();       // idempotent: opening a healed draft saves nothing
  out.selfHeal = {
    changed: changed, changedOnSecondOpen: again,
    written: h.cellValues,
    copyEngine: h.hfAt("Copy1", "B6"),
  };
}

console.log(JSON.stringify(out));
