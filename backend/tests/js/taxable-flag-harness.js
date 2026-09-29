"use strict";
/* Execute the real Taxable? / Remodel Tax? code out of estimate-review.js.
 *
 * THE RULE (Hanz, 2026-09-30): "for the options we follow each worksheets tax options", and "in
 * the generation of the files, it would have the wording tax or not based off the worksheet".
 * Asked whether an option should follow when the base changes, he chose "Stay independent". So
 * every flag-block sheet -- the eleven priced template sheets and every copy of one -- keeps its
 * OWN two answers, as a literal in `cellValues["<sheet>!<addr>"]`:
 *
 *   * a new project starts every sheet with the intake's answers;
 *   * after that each sheet keeps its own, and changing the base never changes an option;
 *   * a new copy starts with its SOURCE's answers;
 *   * an existing draft opens with exactly the answers (and so the prices) it opened with until
 *     now, and saves at most once doing it.
 *
 * WHY EXECUTED. Every line involved reads perfectly on its own -- `copyTab` clones and replays,
 * `canonicalTarget` shares the project-info block, the split stamps a word -- and the defects this
 * family of bugs has produced were all in how they compose: an answer that never reached a cell, or
 * reached one it should not. Only running them and looking at the cells can tell you. So this runs
 * the SHIPPED functions (lifted by name) and the shipped init() step 3c and grid input listener
 * (grabbed verbatim) against stub DOM / HF, and reports the `cellValues` map and the engine that
 * come out -- what `estimate_writer.fill_estimate` and the live HyperFormula engine consume.
 *
 * THE STUB ENGINE EVALUATES MIRRORS. "An existing draft opens with the same answers" is a claim
 * about what each sheet COMPUTES, and on most layouts the flag cell is `=Epoxy!B6`, `=Polish!B6`,
 * `='Gyp (USG 1-8")'!B8`. So getValue follows a plain mirror to the cell it names, and an empty
 * target reads 0, exactly as HyperFormula does. Nothing else is evaluated.
 *
 * THE FIXTURE IS THE WORKBOOK. The Python test passes the shipped template's own flag cells (and the
 * two seal remodel-rate cells) in argv[4], so the sheets here hold what Kyle's file holds, not what
 * this file's author believed it holds.
 *
 * Usage: node taxable-flag-harness.js <frontend-dir> <sheet-names-json> [<template-cells-json>]
 */
const fs = require("fs");
const path = require("path");

const NL = String.fromCharCode(10);
// Normalised to LF: the frontend is checked out CRLF on Windows, and the region grabs below are
// anchored on "\n".
const SRC = fs.readFileSync(path.join(process.argv[2], "js", "estimate-review.js"), "utf8")
  .replace(/\r\n/g, NL);

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
    // The maps under test. Lifted, never re-typed: a hand-copied address here would agree with
    // itself and with nothing the estimator downloads.
    grab(/^const JOB_FLAG_ADDR = \{[\s\S]*?^\};$/m, "JOB_FLAG_ADDR"),
    grab(/^const JOB_FLAG_LITERAL_LAYOUTS = \{[\s\S]*?^\};$/m, "JOB_FLAG_LITERAL_LAYOUTS"),
    grab(/^const JOB_FLAG_LAYOUTS = \[[\s\S]*?\);$/m, "JOB_FLAG_LAYOUTS"),
    grab(/^const JOB_FLAG_TEMPLATE = \{[\s\S]*?^\};$/m, "JOB_FLAG_TEMPLATE"),
  ].join(NL);
  return new Function(src + NL + "return { CANONICAL_SHEET, GYP_BASE, GYP_SHEETS, SEAL_SHEETS," +
    " BASE_ROLE, PRICED_ROLES, OPTION_ONLY_ROLES, MAX_COPIES, JOB_FLAG_ADDR," +
    " JOB_FLAG_LITERAL_LAYOUTS, JOB_FLAG_LAYOUTS, JOB_FLAG_TEMPLATE };")();
})();
const GB = VOCAB.GYP_BASE;

// init() step 3c, verbatim: the one place a draft is split, and the only caller of the legacy
// fan-out. Grabbed rather than lifted because it lives inside the 120-line async init().
const OPEN_SRC = grab(
  /^  let _flagsHealed = 0;\n[\s\S]*?^  if \(!state\.tax_flags_per_sheet\) \{ state\.tax_flags_per_sheet = true; _flagsHealed\+\+; \}$/m,
  "init() step 3c");

const SHEET_NAMES = process.argv[3]
  ? JSON.parse(process.argv[3])
  : ["Epoxy", "Polish", GB, "Takeoff", "Seal", "Seal (+Jnts)", "Epoxy blank",
     "Stnd Alts", "Leveling"].concat(VOCAB.GYP_SHEETS.slice(1));
// The shipped workbook's own cells for the flag block (and the two seal remodel-rate cells), as
// {sheet: {addr: value-or-formula}}. The fallback rebuilds them from JOB_FLAG_TEMPLATE so the
// harness still runs on its own; the Python test always passes the real ones.
const WB_CELLS = process.argv[4] ? JSON.parse(process.argv[4]) : (() => {
  const o = {};
  for (const flag in VOCAB.JOB_FLAG_TEMPLATE) {
    for (const s in VOCAB.JOB_FLAG_TEMPLATE[flag]) {
      const t = VOCAB.JOB_FLAG_TEMPLATE[flag][s];
      const at = (n) => /^Gyp/i.test(n) ? VOCAB.JOB_FLAG_ADDR[flag].gyp : VOCAB.JOB_FLAG_ADDR[flag].epoxy;
      const tgt = t.charAt(0) === "=" ? t.slice(1) : null;
      const ref = tgt && /[^A-Za-z0-9]/.test(tgt) ? "'" + tgt + "'" : tgt;
      (o[s] = o[s] || {})[at(s)] = tgt ? "=" + ref + "!" + at(tgt) : t;
    }
  }
  o.Seal = Object.assign(o.Seal || {}, { B75: '=IF(D6="yes",0.1,0)' });
  o["Seal (+Jnts)"] = Object.assign(o["Seal (+Jnts)"] || {}, { B75: "=Seal!B75" });
  return o;
})();

const MIRROR = /^=(?:'([^']+)'|([A-Za-z0-9 ()+\-]+))!\$?([A-Z]+)\$?(\d+)$/;
const rowOf = (a) => parseInt(/(\d+)$/.exec(a)[1], 10);
const colOf = (a) => /^([A-Z]+)/.exec(a)[1].split("").reduce((x, ch) => x * 26 + ch.charCodeAt(0) - 64, 0);

function templateGrid(name) {
  const cells = [
    // the project-info cells the A1:D10 skip exists to protect
    { addr: "B1", row: 1, col: 2, value: "Westport Commons" },
    { addr: "B2", row: 2, col: 2, value: "2026-09-04" },
    { addr: "B3", row: 3, col: 2, value: "1200 Main St" },
    // a cell well outside A1:D10, to prove ordinary edits are untouched by any of this
    { addr: "E20", row: 20, col: 5, value: 4200 },
  ];
  const own = WB_CELLS[name] || {};
  for (const a in own) {
    const v = own[a];
    const f = typeof v === "string" && v.charAt(0) === "=";
    cells.push({ addr: a, row: rowOf(a), col: colOf(a), value: f ? null : v, formula: f ? v : null,
                 isFormula: f });
  }
  return cells;
}

/** One page's worth of state, wired to stub DOM/HF. `opts.cellValues` seeds a draft,
 *  `opts.tabCopies` copies made earlier, `opts.deferred` sheets init() left out of the engine. */
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
  const deferred = new Set(opts.deferred || []);

  const sheetCache = {};
  for (const n of sheets) if (!deferred.has(n)) sheetCache[n] = { sheet: n, cells: templateGrid(n) };
  for (const c of state.tab_copies) {
    const src = sheetCache[c.source] || { cells: templateGrid(c.source) };
    if (!sheetCache[c.id]) sheetCache[c.id] = { sheet: c.id, cells: src.cells };
  }

  // A stub engine that REMEMBERS values and follows plain mirrors (see the header).
  const hfValues = {};
  const hfCalls = [];
  const hfSheets = new Set(sheets);
  const HF = {
    ready: true,
    createSheet(name) { if (hfSheets.has(name)) return false; hfSheets.add(name); return true; },
    loadSheet(name, cells) {
      hfValues[name] = {};
      for (const c of (cells || [])) hfValues[name][c.addr] = c.formula != null ? c.formula : c.value;
    },
    setCellValue(sheet, addr, v) {
      hfCalls.push([sheet, addr, v]);
      (hfValues[sheet] = hfValues[sheet] || {})[addr] = v;
      return [];
    },
    raw(sheet, addr) {
      const s = hfValues[sheet];
      return s && Object.prototype.hasOwnProperty.call(s, addr) ? s[addr] : null;
    },
    getValue(sheet, addr, depth) {
      const v = HF.raw(sheet, addr);
      const m = typeof v === "string" ? MIRROR.exec(v.trim()) : null;
      if (m && (depth || 0) < 8) {
        const t = HF.getValue(m[1] || m[2], m[3] + m[4], (depth || 0) + 1);
        return t == null ? 0 : t;
      }
      return v;
    },
  };
  for (const n of sheets) if (!deferred.has(n)) HF.loadSheet(n, sheetCache[n].cells);
  for (const c of state.tab_copies) HF.loadSheet(c.id, sheetCache[c.id].cells);
  for (const k of Object.keys(cellValues)) {
    const i = k.indexOf("!");
    if (i > 0 && hfValues[k.slice(0, i)]) HF.setCellValue(k.slice(0, i), k.slice(i + 1), cellValues[k]);
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
    CANONICAL_SHEET: VOCAB.CANONICAL_SHEET, GYP_BASE: GB,
    GYP_SHEETS: VOCAB.GYP_SHEETS, BASE_ROLE: VOCAB.BASE_ROLE,
    PRICED_ROLES: VOCAB.PRICED_ROLES, OPTION_ONLY_ROLES: VOCAB.OPTION_ONLY_ROLES,
    MAX_COPIES: VOCAB.MAX_COPIES, JOB_FLAG_ADDR: VOCAB.JOB_FLAG_ADDR,
    JOB_FLAG_LITERAL_LAYOUTS: VOCAB.JOB_FLAG_LITERAL_LAYOUTS,
    JOB_FLAG_LAYOUTS: VOCAB.JOB_FLAG_LAYOUTS, JOB_FLAG_TEMPLATE: VOCAB.JOB_FLAG_TEMPLATE,
    state, cellValues, sheetCache, sheets, HF, TW, activeSheet,
    tabs,
    alert: (m) => alerts.push(m),
    // leaf stubs. `refreshActiveGridFromHF` itself is LIFTED and runs for real.
    sheetGrid: { querySelector: () => null },
    refreshDomFromHF: (data) => refreshCalls.push(data && data.sheet),
    updateTotalBarFromHF: () => {},
    renderTabs: () => {},
    showSheet: (id) => { shown.push(id); },
    propagateChangesToDom: () => {},
    _bulkWrite: false,
    // Covered end to end by remodel-rate-harness.js / markup-rate-harness.js; recorded here only so
    // copyTab dropping either call is still a failure somewhere. In the dependency list at all
    // because `lift` binds by name.
    remodelCalls: [],
    effectiveRemodelRate: () => null,
    markupCalls: [],
  };
  deps.tabs = tabs;
  deps.applyRemodelRateOverride = (r) => { deps.remodelCalls.push(r); };
  deps.applyMarkupRates = () => { deps.markupCalls.push(true); return 0; };

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
  deps.jobFlagAddrFor = lift("jobFlagAddrFor", deps);
  deps.jobFlagKindFor = lift("jobFlagKindFor", deps);
  deps.isProjectInfoCell = lift("isProjectInfoCell", deps);
  deps.isSharedInfoCell = lift("isSharedInfoCell", deps);
  deps.canonicalSheetFor = lift("canonicalSheetFor", deps);
  deps.canonicalTarget = lift("canonicalTarget", deps);
  deps.canonicalKey = lift("canonicalKey", deps);
  deps.allLabels = lift("allLabels", deps);
  deps.uniqueLabel = lift("uniqueLabel", deps);
  deps.nextCopyId = lift("nextCopyId", deps);
  deps.orderedIds = lift("orderedIds", deps);
  deps.refreshActiveGridFromHF = lift("refreshActiveGridFromHF", deps);
  // the legacy one-answer-per-job fan-out, still run once on a draft that was never split
  deps.jobFlagTargets = lift("jobFlagTargets", deps);
  deps.jobFlagAnswer = lift("jobFlagAnswer", deps);
  deps.applyJobFlag = lift("applyJobFlag", deps);
  deps.applyJobFlags = lift("applyJobFlags", deps);
  // THE UNITS UNDER TEST
  deps.jobFlagValue = lift("jobFlagValue", deps);
  deps.jobFlagWord = lift("jobFlagWord", deps);
  deps.applySheetFlag = lift("applySheetFlag", deps);
  deps.ownJobFlags = lift("ownJobFlags", deps);
  deps.copyJobFlags = lift("copyJobFlags", deps);
  deps.jobFlagCellsFor = lift("jobFlagCellsFor", deps);
  deps.baseFlagSheets = lift("baseFlagSheets", deps);
  deps.applyAutofillJobFlags = lift("applyAutofillJobFlags", deps);
  deps.ownSealJointsRemodelRate = lift("ownSealJointsRemodelRate", deps);

  // buildTabs is the ONE thing stubbed rather than lifted, and only because the shipped one
  // REASSIGNS the module-level `tabs`, which inside a lifted copy would rebind its own parameter
  // and leave every other lifted function holding the old array. Same composition, mutated in
  // place, over the real orderedIds/roleFor/labelFor.
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

  /** init() step 3c, as the page runs it on open. Returns what it changed (0 = no save). */
  const openDraft = new Function("state", "applyJobFlags", "ownSealJointsRemodelRate", "ownJobFlags",
    OPEN_SRC + NL + "return _flagsHealed;").bind(null, state, deps.applyJobFlags,
    deps.ownSealJointsRemodelRate, deps.ownJobFlags);

  // The grid's cell-edit listener, verbatim.
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
                   "jobFlagKindFor", "applySheetFlag", "jobFlagWord", "refreshActiveGridFromHF"];
    const vals = [cellValues, addrKey, originalVal === undefined ? "" : originalVal, HF,
                  deps.canonicalTarget, sheet, cell, false, false,
                  deps.propagateChangesToDom, deps.updateTotalBarFromHF,
                  deps.jobFlagKindFor, deps.applySheetFlag, deps.jobFlagWord,
                  deps.refreshActiveGridFromHF];
    const fn = new Function(...names, "return " + listenerSrc + ";")(...vals);
    fn({ target: { value: newVal } });
  }

  // The PROPOSAL's read of the same two answers: the closure inside snapshotLumpSumsToState,
  // grabbed verbatim and bound to the same lifted helpers.
  const taxFlagsFor = (() => {
    const m = /const taxFlagsFor = (\(id\) => \{[\s\S]*?\n  \});/.exec(SRC);
    if (!m) throw new Error("snapshotLumpSumsToState's taxFlagsFor moved -- rewrite this harness");
    const names = ["layoutIdFor", "JOB_FLAG_LAYOUTS", "txAddr", "jobFlagAddrFor", "HF"];
    return new Function(...names, "return " + m[1] + ";")(
      deps.layoutIdFor, VOCAB.JOB_FLAG_LAYOUTS, deps.txAddr, deps.jobFlagAddrFor, HF);
  })();

  /** Every flag-block sheet on the page (templates and copies). */
  const flagSheetIds = () => tabs.map(t => t.id)
    .filter(id => Object.keys(deps.jobFlagCellsFor(id)).length > 0);
  /** What each flag-block sheet COMPUTES for its two answers, through the engine. */
  const engineAnswers = () => {
    const o = {};
    for (const id of flagSheetIds()) {
      const fc = deps.jobFlagCellsFor(id);
      o[id] = {};
      for (const flag in fc) {
        const cut = fc[flag].lastIndexOf("!");
        const v = HF.getValue(fc[flag].slice(0, cut), fc[flag].slice(cut + 1));
        o[id][flag] = v == null ? null : String(v);
      }
    }
    return o;
  };
  /** The same, as the sheet's own tax formulas READ it: taxed unless "no", remodel only if "yes". */
  const pricedAs = () => {
    const e = engineAnswers();
    const o = {};
    for (const id in e) o[id] = {
      taxable: String(e[id].taxable == null ? "" : e[id].taxable).trim().toLowerCase() !== "no",
      remodel: String(e[id].remodel == null ? "" : e[id].remodel).trim().toLowerCase() === "yes",
    };
    return o;
  };
  /** Each flag-block sheet's OWN literal, or null where it has none. */
  const ownAnswers = () => {
    const o = {};
    for (const id of flagSheetIds()) {
      const fc = deps.jobFlagCellsFor(id);
      o[id] = {};
      for (const flag in fc) o[id][flag] = fc[flag] in cellValues ? cellValues[fc[flag]] : null;
    }
    return o;
  };

  return {
    state, cellValues, sheetCache, tabs, hfCalls, hfValues, setStateCalls, alerts, shown,
    refreshCalls, remodelCalls: deps.remodelCalls, copyTab, typeInto, openDraft,
    jobFlagTargets: deps.jobFlagTargets, jobFlagAnswer: deps.jobFlagAnswer,
    jobFlagKindFor: deps.jobFlagKindFor, applyJobFlags: deps.applyJobFlags,
    jobFlagValue: deps.jobFlagValue, jobFlagCellsFor: deps.jobFlagCellsFor,
    baseFlagSheets: deps.baseFlagSheets, applyAutofillJobFlags: deps.applyAutofillJobFlags,
    ownSealJointsRemodelRate: deps.ownSealJointsRemodelRate,
    canonicalTarget: deps.canonicalTarget, canonicalKey: deps.canonicalKey,
    HF, hfAt: (s, a) => HF.getValue(s, a), hfRaw: (s, a) => HF.raw(s, a),
    taxFlagsFor, flagSheetIds, engineAnswers, pricedAs, ownAnswers,
  };
}

const clone = (o) => JSON.parse(JSON.stringify(o));
const out = {};
out.sheetNames = SHEET_NAMES;
out.literalLayouts = VOCAB.JOB_FLAG_LITERAL_LAYOUTS;
out.flagAddr = VOCAB.JOB_FLAG_ADDR;
out.flagLayouts = VOCAB.JOB_FLAG_LAYOUTS;
out.template = VOCAB.JOB_FLAG_TEMPLATE;

// The intake's pre-split cells for an exempt, remodel job: exactly what index.js writes.
const INTAKE_EXEMPT_REMODEL = {
  "Epoxy!B6": "No", "Leveling!B6": "No", [GB + "!B8"]: "No", "Gyp (FR)!B8": "No", "Epoxy!D6": "Yes",
};

// ── 1. the legacy fan-out, which a never-split draft still gets once ────────
// Four cells for Taxable, one for Remodel, and no mirror sheet among them.
{
  const h = harness();
  out.legacyTargets = { taxable: h.jobFlagTargets("taxable"), remodel: h.jobFlagTargets("remodel") };
  const f = harness({ cellValues: { "Epoxy!B6": "No" } });
  f.applyJobFlags();
  out.legacyFanout = f.cellValues;
}

// ── 2. A NEW PROJECT: every flag-block sheet starts with the intake's answers ─
{
  const h = harness({ state: { work_type: "gyp", base_tab_id: GB }, cellValues: INTAKE_EXEMPT_REMODEL });
  const first = h.openDraft();
  const afterFirst = clone(h.cellValues);
  const second = h.openDraft();
  out.newProject = {
    first, second, marker: h.state.tax_flags_per_sheet === true,
    own: h.ownAnswers(), engine: h.engineAnswers(),
    unchangedBySecondOpen: JSON.stringify(afterFirst) === JSON.stringify(h.cellValues),
    gypMilesAwayUntouched: !((GB + "!B6") in h.cellValues) && !("Gyp (FR)!B6" in h.cellValues),
    written: h.cellValues,
  };
  // ...and one nobody touched on the intake: the intake's defaults ARE the template's (Taxable on,
  // Remodel off), so every sheet gets those.
  const u = harness();
  out.newProjectUntouched = { first: u.openDraft(), second: u.openDraft(), own: u.ownAnswers() };
  // ...and the two sheets init() defers still get theirs, off the template map, with nothing in the
  // engine to read them from.
  const d = harness({ cellValues: INTAKE_EXEMPT_REMODEL, deferred: ["Leveling", "Epoxy blank"] });
  d.openDraft();
  out.newProjectDeferred = { leveling: d.ownAnswers()["Leveling"], blank: d.ownAnswers()["Epoxy blank"] };
}

// ── 3. AN EXISTING DRAFT opens with the answers (so the prices) it had ──────
// The shape a draft saved by the job-wide build is in: the fan-out already reached the four
// literals and the literal-layout copies, the mirror sheets and mirror-layout copies follow by
// formula, and one gyp base D8 fork from an older build.
{
  const copies = [{ id: "Copy1", source: "Epoxy", role: "epoxy" },
                  { id: "Copy2", source: "Polish", role: "polish" },
                  { id: "Copy3", source: "Gyp (FR)", role: "gyp" },
                  { id: "Copy4", source: "Seal (+Jnts)", role: "seal" },
                  { id: "Copy5", source: "Gyp (USG N12ULTRA)", role: "gyp" },
                  { id: "Copy6", source: "Copy2", role: "polish" }];
  const saved = Object.assign({}, INTAKE_EXEMPT_REMODEL, {
    "Copy1!B6": "No", "Copy1!D6": "Yes", "Copy3!B8": "No", "Epoxy!E20": 5200 });
  const h = harness({ state: { work_type: "epoxy", base_tab_id: "Epoxy" }, cellValues: saved,
                      tabCopies: copies });
  const before = { engine: h.engineAnswers(), priced: h.pricedAs(), proposal: {} };
  for (const id of h.flagSheetIds()) before.proposal[id] = h.taxFlagsFor(id);
  const cvBefore = clone(h.cellValues);
  const first = h.openDraft();
  const cvAfter = clone(h.cellValues);
  const after = { engine: h.engineAnswers(), priced: h.pricedAs(), proposal: {} };
  for (const id of h.flagSheetIds()) after.proposal[id] = h.taxFlagsFor(id);
  const second = h.openDraft();
  out.existing = {
    before, after, first, second, cvBefore, cvAfter, own: h.ownAnswers(), copies,
    marker: h.state.tax_flags_per_sheet === true,
    // the one save: init() persists when step 3c reports a change, and only then
    savesOnFirst: first > 0 ? 1 : 0, savesOnSecond: second > 0 ? 1 : 0,
    untouchedCellKept: h.cellValues["Epoxy!E20"],
  };
  // A draft from BEFORE the job-wide fix (the intake wrote Epoxy!B6 alone, a copy was made): it
  // opens the way the job-wide build opened it -- healed -- and is frozen there.
  const old = harness({ cellValues: { "Epoxy!B6": "No" },
                        tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }] });
  old.openDraft();
  out.legacyUnhealed = old.ownAnswers();
  // ...and one already split that was edited later is not re-healed: the marker stops the fan-out.
  const split = harness({ state: { tax_flags_per_sheet: true },
                          cellValues: { "Epoxy!B6": "No", "Leveling!B6": "Yes" } });
  const n = split.openDraft();
  out.splitNotReHealed = { leveling: split.cellValues["Leveling!B6"], changed: n > 0 };
}

// ── 4. EACH SHEET KEEPS ITS OWN: typing, through the real listener ──────────
{
  const h = harness({ state: { work_type: "epoxy", base_tab_id: "Epoxy" },
                      tabCopies: [{ id: "Copy1", source: "Polish", role: "polish" }],
                      activeSheet: "Polish" });
  h.openDraft();
  h.hfCalls.length = 0;
  h.typeInto("Polish", "B6", "No", "Yes");               // an option says exempt
  const optionCalls = h.hfCalls.slice(); h.hfCalls.length = 0;
  const afterOption = h.ownAnswers();
  h.typeInto("Epoxy", "B6", "No", "Yes");                // the base flips...
  h.typeInto("Epoxy", "B6", "Yes", "Yes");               // ...and back (the old delete-on-revert trap)
  h.typeInto("Epoxy", "D6", "Yes", "No");                // the base turns remodel on
  const baseCalls = h.hfCalls.slice(); h.hfCalls.length = 0;
  h.typeInto("Copy1", "D6", "Yes", "No");                // a copy answers for itself
  h.typeInto("Gyp (USG N25 1-4\")", "B8", "No", "Yes");  // a mirroring gyp variant, its own B8
  h.typeInto("Gyp (USG N25 1-4\")", "D8", "Yes", "No");  // ...and its own D8, not the gyp base's
  const otherCalls = h.hfCalls.slice();
  // the picker's blank, and a space: stamped as the word that prices the same (taxed unless
  // "no", remodel only if "yes"), never a blank that would fall back to a mirror
  h.typeInto("Seal", "B6", "", "Yes");
  h.typeInto("Seal", "D6", " ", "No");
  const blank = { taxable: h.cellValues["Seal!B6"], remodel: h.cellValues["Seal!D6"] };
  out.independent = {
    afterOption, final: h.ownAnswers(), engine: h.engineAnswers(),
    optionCalls, baseCalls, otherCalls, blank,
    epoxyKeptAfterRevert: h.cellValues["Epoxy!B6"],
    refreshed: h.refreshCalls.length > 0,
    proposal: { Epoxy: h.taxFlagsFor("Epoxy"), Polish: h.taxFlagsFor("Polish"),
                Copy1: h.taxFlagsFor("Copy1"), Seal: h.taxFlagsFor("Seal") },
    cellValues: h.cellValues, copies: h.state.tab_copies,
  };
}

// ── 5. THE TWO OPTION SHAPES, end to end from the sheet ─────────────────────
// Base taxable (Yes / No), one option exempt (No / No), one option remodel-only (No / Yes). The
// cellValues go through the real fill_estimate and the flags into the real document on the Python
// side.
{
  const h = harness({ state: { work_type: "epoxy", base_tab_id: "Epoxy" },
                      tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }] });
  h.openDraft();
  h.typeInto("Polish", "B6", "No", "Yes");               // Polish: exempt option
  h.typeInto("Seal", "B6", "No", "Yes");                 // Seal: remodel-only option
  h.typeInto("Seal", "D6", "Yes", "No");
  h.typeInto("Copy1", "B6", "No", "Yes");                // a copy of the base, exempt
  out.optionShapes = {
    cellValues: h.cellValues, copies: h.state.tab_copies,
    flags: { Epoxy: h.taxFlagsFor("Epoxy"), Polish: h.taxFlagsFor("Polish"),
             Seal: h.taxFlagsFor("Seal"), Copy1: h.taxFlagsFor("Copy1"),
             "Seal (+Jnts)": h.taxFlagsFor("Seal (+Jnts)") },
  };
}

// ── 6. A NEW COPY starts with its SOURCE's answers, then keeps its own ─────
{
  const perSource = {};
  for (const src of SHEET_NAMES) {
    if (VOCAB.JOB_FLAG_LAYOUTS.indexOf(src) < 0) continue;
    const h = harness({ state: { work_type: /^Gyp/.test(src) ? "gyp" : "epoxy" } });
    h.openDraft();
    const gyp = /^Gyp/i.test(src);
    const tA = gyp ? "B8" : "B6", rA = gyp ? "D8" : "D6";
    // the SOURCE answers differently from the template and from Epoxy: exempt, remodel on
    h.typeInto(src, tA, "No", "Yes");
    h.typeInto(src, rA, "Yes", "No");
    h.copyTab(src);
    const copy = h.state.tab_copies[h.state.tab_copies.length - 1];
    const id = copy ? copy.id : null;
    const beforeSrcChange = id ? { t: h.cellValues[id + "!" + tA], r: h.cellValues[id + "!" + rA] } : null;
    h.typeInto(src, tA, "Yes", "No");                     // the source changes afterwards...
    perSource[src] = {
      copyId: id,
      copyTaxable: beforeSrcChange && beforeSrcChange.t,
      copyRemodel: beforeSrcChange && beforeSrcChange.r,
      copyTaxableAfterSourceChanged: id ? h.cellValues[id + "!" + tA] : null,   // ...the copy does not
      engine: id ? { t: h.hfAt(id, tA), r: h.hfAt(id, rA) } : null,
      epoxyUntouched: src === "Epoxy" ? null : [h.cellValues["Epoxy!B6"], h.cellValues["Epoxy!D6"]],
      cacheAlive: id ? !!h.sheetCache[id] : false,
      remodelRateApplied: h.remodelCalls.length,
      gypMilesAwayUntouched: id ? !((id + "!B6") in h.cellValues) || !gyp : false,
    };
  }
  out.copies = perSource;
  // a copy of a copy
  const h = harness();
  h.openDraft();
  h.typeInto("Polish", "B6", "No", "Yes");
  h.copyTab("Polish");
  const c1 = h.state.tab_copies[0].id;
  h.copyTab(c1);
  const c2 = h.state.tab_copies[1].id;
  out.copyChain = { c1: h.cellValues[c1 + "!B6"], c2: h.cellValues[c2 + "!B6"], c2Engine: h.hfAt(c2, "B6") };
}

// ── 7. the AI autofill's two answers land on the BASE ───────────────────────
{
  const polish = harness({ state: { work_type: "polish", base_tab_id: "Polish" } });
  polish.openDraft();
  polish.applyAutofillJobFlags({ taxable: "No", remodel: "Yes" });
  const gyp = harness({ state: { work_type: "gyp", base_tab_id: GB } });
  gyp.openDraft();
  gyp.applyAutofillJobFlags({ taxable: "No" });
  const combo = harness({ state: { work_type: "combo", base_tab_id: null } });
  combo.openDraft();
  combo.applyAutofillJobFlags({ taxable: "No" });
  const unsplit = harness({ cellValues: { "Epoxy!B6": "No" } });
  unsplit.applyAutofillJobFlags({});
  out.autofill = {
    polish: { own: polish.ownAnswers(), bases: polish.baseFlagSheets() },
    gyp: { base: gyp.cellValues[GB + "!B8"], fr: gyp.cellValues["Gyp (FR)!B8"], epoxy: gyp.cellValues["Epoxy!B6"] },
    combo: { bases: combo.baseFlagSheets(), epoxy: combo.cellValues["Epoxy!B6"],
             polish: combo.cellValues["Polish!B6"], seal: combo.cellValues["Seal!B6"] },
    unsplitFansOut: unsplit.cellValues["Leveling!B6"],
  };
}

// ── 8. 'Seal (+Jnts)' prices remodel off its OWN D6 ──────────────────────────
{
  const h = harness({ tabCopies: [{ id: "Copy1", source: "Seal (+Jnts)", role: "seal" }] });
  h.openDraft();
  const typed = harness({ cellValues: { "Seal!B75": "0.08" } });
  typed.openDraft();
  const county = harness({ cellValues: { "Seal!B75": '=IF(D6="yes",0.07975,0)' } });
  county.openDraft();
  const already = harness({ state: { tax_flags_per_sheet: true } });
  already.openDraft();
  out.sealJoints = {
    template: h.cellValues["Seal (+Jnts)!B75"], copy: h.cellValues["Copy1!B75"],
    templateSealUntouched: !("Seal!B75" in h.cellValues),
    typedNumberLeftAlone: !("Seal (+Jnts)!B75" in typed.cellValues),
    county: county.cellValues["Seal (+Jnts)!B75"],
    notOnASplitDraft: !("Seal (+Jnts)!B75" in already.cellValues),
  };
}

// ── 9. where each tab's two cells are, for the intake (priced_tabs[].flag_cells) ─
{
  const h = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" },
                                  { id: "Copy2", source: "Gyp (FR)", role: "gyp" }],
                      tabStructs: [{ sheet: "Copy1", kind: "insert_rows", at: 2, count: 2 }] });
  out.flagCells = {
    epoxy: h.jobFlagCellsFor("Epoxy"), gyp: h.jobFlagCellsFor(GB),
    movedCopy: h.jobFlagCellsFor("Copy1"), gypCopy: h.jobFlagCellsFor("Copy2"),
    takeoff: h.jobFlagCellsFor("Takeoff"),
  };
}

// ── 10. an ORDINARY cell edit is untouched by all of this ───────────────────
{
  const h = harness();
  h.typeInto("Epoxy", "E20", "5000", "4200");
  h.typeInto("Epoxy", "B4", "No", "Yes");           // Local? -- NOT ours (see Issue 5)
  h.typeInto("Epoxy", "B5", "Yes", "No");           // Hard Bid? -- likewise
  h.typeInto("Epoxy", "D5", "Yes", "No");           // Prevailing Wage -- a mirror everywhere
  h.typeInto(GB, "B6", "12", "0");                  // "Miles Away" on a gyp layout, NOT Taxable
  out.ordinaryEdits = h.cellValues;
  out.kinds = {
    epoxyB6: h.jobFlagKindFor("Epoxy", "B6"), epoxyD6: h.jobFlagKindFor("Epoxy", "D6"),
    epoxyB4: h.jobFlagKindFor("Epoxy", "B4"), gypB6: h.jobFlagKindFor(GB, "B6"),
    gypB8: h.jobFlagKindFor(GB, "B8"), gypD8: h.jobFlagKindFor(GB, "D8"),
    takeoffB6: h.jobFlagKindFor("Takeoff", "B6"),
    copyOfGypB8: (() => {
      const g = harness({ tabCopies: [{ id: "Copy1", source: "Gyp (FR)", role: "gyp" }] });
      return [g.jobFlagKindFor("Copy1", "B8"), g.jobFlagKindFor("Copy1", "B6")];
    })(),
  };
}

// ── 11. the project-info redirect keeps working where it is RIGHT ───────────
{
  const h = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }] });
  const g = harness();
  out.projectInfo = {
    b1: h.canonicalTarget("Copy1", "B1"), b3: h.canonicalTarget("Copy1", "B3"),
    gypB2: g.canonicalTarget("Gyp (USG N12ULTRA)", "B2"),
    // ...and the two flags are the one exception, on every layout
    copyB6: h.canonicalTarget("Copy1", "B6"), polishB6: g.canonicalTarget("Polish", "B6"),
    polishD6Key: g.canonicalKey("Polish", "D6"),
    gypVariantB8: g.canonicalTarget("Gyp (USG N12ULTRA)", "B8"),
    gypVariantD8: g.canonicalTarget("Gyp (USG N12ULTRA)", "D8"),
    gypVariantB6: g.canonicalTarget("Gyp (USG N12ULTRA)", "B6"),   // Miles Away IS shared
  };
  h.typeInto("Copy1", "B1", "New Name", "Westport Commons");
  out.projectInfo.typedB1 = { onMaster: h.cellValues["Epoxy!B1"], forkedOntoTheCopy: "Copy1!B1" in h.cellValues };
}

// ── 12. structural edits: the split follows the row, or skips it ────────────
{
  const moved = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }],
                          tabStructs: [{ sheet: "Copy1", kind: "insert_rows", at: 2, count: 2 }],
                          cellValues: { "Epoxy!B6": "No" } });
  moved.openDraft();
  const gone = harness({ tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }],
                         tabStructs: [{ sheet: "Copy1", kind: "delete_rows", at: 6, count: 1 }],
                         cellValues: { "Epoxy!B6": "No" } });
  gone.openDraft();
  out.structural = {
    movedWritten: moved.cellValues["Copy1!B8"], movedRemodel: moved.cellValues["Copy1!D8"],
    movedNotAtStale: moved.cellValues["Copy1!B6"] === undefined,
    goneWrittenAnywhere: Object.keys(gone.cellValues).filter(k => k.indexOf("Copy1!") === 0),
  };
}

// ── 13. the legacy two-store rule, which decides what a never-split draft opens with ─
{
  const gypJob = harness({ state: { work_type: "gyp", base_tab_id: GB },
                           cellValues: { "Epoxy!B6": "Yes", [GB + "!B8"]: "No" } });
  gypJob.openDraft();
  const forked = harness({ state: { work_type: "epoxy", base_tab_id: "Epoxy" },
                           cellValues: { "Epoxy!D6": "No", [GB + "!D8"]: "Yes" } });
  forked.openDraft();
  out.legacyStores = {
    gypJob: gypJob.ownAnswers(), forked: forked.ownAnswers(),
    blankAnswer: harness().jobFlagAnswer("taxable"),
  };
}

// ── 14. the PROPOSAL reads each tab's own two answers ───────────────────────
{
  const shipped = harness();
  const flipped = harness({ cellValues: { "Epoxy!B6": "No", "Epoxy!D6": " YES " } });
  const copy = harness({ cellValues: { "Copy1!B6": "no" },
                         tabCopies: [{ id: "Copy1", source: "Epoxy", role: "epoxy" }] });
  const gyp = harness({ cellValues: { [GB + "!B8"]: "No", [GB + "!D8"]: "Yes" } });
  out.proposalFlags = {
    shipped: shipped.taxFlagsFor("Epoxy"), flipped: flipped.taxFlagsFor("Epoxy"),
    copy: copy.taxFlagsFor("Copy1"), copySource: copy.taxFlagsFor("Epoxy"),
    gyp: gyp.taxFlagsFor(GB), noBlock: shipped.taxFlagsFor("Takeoff"),
  };
}

// ── 15. the autofill CLICK, through the shipped handler ─────────────────────
// Everything above calls applyAutofillJobFlags directly. This runs the real click handler
// around it -- the loop that holds the AI's two tax answers back from Epoxy's own cells -- with
// the network and the banner stubbed.
const AUTOFILL_SRC = grab(
  /^document\.getElementById\("autofill-btn"\)\.addEventListener\("click", async \(e\) => \{[\s\S]*?\n\}\);$/m,
  "the autofill click handler");
async function autofillClick(h, reply) {
  let handler = null;
  const btn = { textContent: "AI Autofill", disabled: false, innerHTML: "",
                addEventListener: (type, fn) => { if (type === "click") handler = fn; } };
  const banners = [];
  const deps = {
    document: { getElementById: (id) => (id === "autofill-btn" ? btn : null) },
    state: h.state, callAutofillEndpoint: async () => reply, cellValues: h.cellValues, HF: h.HF,
    jobFlagKindFor: h.jobFlagKindFor, applyAutofillJobFlags: h.applyAutofillJobFlags,
    escHtml: (s) => String(s == null ? "" : s), icon: () => "", TW: { setState() {} },
    sysNameInput: { value: "" }, texInput: { value: "" }, activeSheet: null, sheetCache: {},
    showSheet: async () => {}, setTimeout: () => 0,
    showAutofillBanner: (html, kind) => banners.push({ html, kind }), console,
  };
  const names = Object.keys(deps);
  new Function(...names, AUTOFILL_SRC)(...names.map(k => deps[k]));
  if (!handler) throw new Error("the autofill handler never registered -- rewrite this harness");
  await handler({ target: btn });
  return banners;
}

(async () => {
  const h = harness({ state: { work_type: "polish", base_tab_id: "Polish" } });
  h.openDraft();
  const banners = await autofillClick(h, { ok: true, cell_values: {
    "Epoxy!B6": "No", "Epoxy!D6": "Yes", "Epoxy!B4": "No", texture: "Smooth" } });
  out.autofillClick = {
    bannerKind: banners.length ? banners[banners.length - 1].kind : null,
    banner: banners.length ? banners[banners.length - 1].html : "",
    polish: { taxable: h.cellValues["Polish!B6"], remodel: h.cellValues["Polish!D6"] },
    epoxy: { taxable: h.cellValues["Epoxy!B6"], remodel: h.cellValues["Epoxy!D6"] },
    epoxyB4: h.cellValues["Epoxy!B4"],
  };
  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
