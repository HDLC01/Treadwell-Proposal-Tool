"use strict";
/* Execute the four-tab deferral out of estimate-review.js, and report what it actually does.
 *
 * WHY EXECUTED. The change this guards makes init() stop loading four of the sixteen worksheets
 * before the screen opens. Everything that can go wrong with it is a RUNTIME reachability
 * question -- does some writer land on a sheet the engine does not have yet, does a copied tab
 * lose the source it is rehydrated from, does the late load wipe what was stamped in while the
 * sheet was empty -- and none of those are visible in the source. A "the Set has four names in
 * it" assertion would pass with the replay deleted, which is the one mistake that silently
 * changes a price.
 *
 * WHAT IS LIFTED AND WHY IT IS LIFTED TOGETHER. `deferredTabs` is a module-level `let` that
 * init() REASSIGNS and loadDeferredIntoEngine MUTATES. Passing it in as a named dep would give
 * the lifted function its own parameter binding and the mutation would be invisible -- the trap
 * markup-rate-harness.js records for `markupRules`. So the declaration and the function are
 * lifted into ONE `new Function` body and share the binding.
 *
 * BASE_ROLE is lifted rather than retyped for the reason markup-rate-harness.js gives about
 * GYP_SHEETS: a hand-copied list lets the fixture agree with itself while disagreeing with the
 * workbook, and "none of the four is priced" is the load-bearing half of the safety argument.
 *
 * Usage: node deferred-tabs-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
// Normalised on read for the reason library-ui-harness.js records: git hands these files out with
// CRLF on a Windows checkout and LF in CI, and a `[\s\S]*?^\}$` lift is anchored on the newline.
const SRC = fs.readFileSync(path.join(ROOT, "js", "estimate-review.js"), "utf8").replace(/\r\n/g, "\n");
const NL = String.fromCharCode(10);

function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + what + " -- rewrite this harness, don't stub it");
  return m[0];
}

// ── the shipped role table, not a copy of it ─────────────────────────────────
const ROLE_SRC = [
  grab(/^const CANONICAL_SHEET = .*$/m, "CANONICAL_SHEET"),
  grab(/^const GYP_BASE = .*$/m, "GYP_BASE"),
  grab(/^const GYP_SHEETS = \[[\s\S]*?\];$/m, "GYP_SHEETS"),
  grab(/^const SEAL_SHEETS = .*$/m, "SEAL_SHEETS"),
  grab(/^const BASE_ROLE = .*$/m, "BASE_ROLE"),
  grab(/^GYP_SHEETS\.forEach\(.*$/m, "the gyp BASE_ROLE fan-out"),
  grab(/^SEAL_SHEETS\.forEach\(.*$/m, "the seal BASE_ROLE fan-out"),
].join(NL);
const { BASE_ROLE, CANONICAL_SHEET, GYP_BASE } =
  new Function(ROLE_SRC + NL + "return { BASE_ROLE, CANONICAL_SHEET, GYP_BASE };")();

// ── the list under test ──────────────────────────────────────────────────────
const { DEFERRABLE_TABS } = new Function(
  grab(/^const DEFERRABLE_TABS = .*$/m, "DEFERRABLE_TABS") + NL + "return { DEFERRABLE_TABS };")();

/** Build a fresh copy of the deferral machinery bound to a given page state.
 *
 *  `deferredTabs`, `deferrableNow` and `loadDeferredIntoEngine` go into ONE body so the `let`
 *  they share is the same binding the page gives them. `state`, `sheetCache`, `cellValues` and
 *  `HF` come in as deps because those ARE the page state this scenario is setting up. */
function build(page) {
  const body = [
    grab(/^const DEFERRABLE_TABS = .*$/m, "DEFERRABLE_TABS"),
    grab(/^function deferrableNow\(\) \{[\s\S]*?\n\}/m, "deferrableNow"),
    grab(/^let deferredTabs = .*$/m, "deferredTabs"),
    grab(/^function loadDeferredIntoEngine\([^)]*\) \{[\s\S]*?\n\}/m, "loadDeferredIntoEngine"),
    "return {",
    "  deferrableNow,",
    "  loadDeferredIntoEngine,",
    "  setDeferred: (names) => { deferredTabs = new Set(names); },",
    "  peek: () => Array.from(deferredTabs),",
    "};",
  ].join(NL);
  const deps = { state: page.state, sheetCache: page.sheetCache, cellValues: page.cellValues,
                 HF: page.HF };
  const names = Object.keys(deps);
  return new Function(...names, body)(...names.map((k) => deps[k]));
}

/** A HyperFormula stand-in that records the ORDER of what it was asked to do. Order is the whole
 *  question here: a replay that runs before setSheetContent is a replay that gets wiped. */
function fakeHF(ready) {
  const log = [];
  return {
    ready: ready !== false,
    log,
    loadSheet: (name, cells) => log.push(["loadSheet", name, (cells || []).length]),
    setCellValue: (sheet, addr, val) => log.push(["setCellValue", sheet + "!" + addr, val]),
  };
}

const out = { DEFERRABLE_TABS: Array.from(DEFERRABLE_TABS), CANONICAL_SHEET, GYP_BASE };

// Which of the four carry a priced role, read out of the shipped BASE_ROLE. Must be none.
out.pricedAmongDeferrable = Array.from(DEFERRABLE_TABS).filter((n) => BASE_ROLE[n] !== undefined);

// ── 1. an ordinary draft defers all four ─────────────────────────────────────
{
  const api = build({ state: { tab_copies: [] }, sheetCache: {}, cellValues: {}, HF: fakeHF() });
  out.plain = Array.from(api.deferrableNow()).sort();
}

// ── 2. a tab somebody COPIED keeps its eager load ────────────────────────────
//
// Copies are rehydrated from `sheetCache[c.source]`. Defer the source and the rehydrate finds
// nothing, gives up on it as an orphan, and leaves a tab on the bar whose /api/sheet/Copy1 404s.
{
  const api = build({
    state: { tab_copies: [{ id: "Copy1", source: "Leveling", role: "epoxy" }] },
    sheetCache: {}, cellValues: {}, HF: fakeHF(),
  });
  out.withLevelingCopy = Array.from(api.deferrableNow()).sort();
}
{
  // Two of the four copied at once, plus a copy of an eager tab (which changes nothing).
  const api = build({
    state: { tab_copies: [{ id: "Copy1", source: "Epoxy blank" },
                          { id: "Copy2", source: "Unit Layouts" },
                          { id: "Copy3", source: "Epoxy" }] },
    sheetCache: {}, cellValues: {}, HF: fakeHF(),
  });
  out.withTwoCopies = Array.from(api.deferrableNow()).sort();
}

// ── 3. the late load puts back what was stamped in while the sheet was empty ─
//
// applyJobFlags writes Leveling!B6 and Leveling!D6; applyRemodelRateOverride writes Leveling!B77.
// All three go into cellValues before they touch the engine, and all three are inside the sheet
// setSheetContent is about to replace.
{
  const HF = fakeHF();
  const cellValues = {
    "Epoxy!B6": "No",                                  // another sheet -- must NOT be replayed
    // An address Leveling does NOT have. Without it the "only this sheet" assertion is
    // vacuous: the replay passes `name` as the sheet, so every key it writes starts with
    // "Leveling!" whether or not it filtered -- and dropping the filter stayed green.
    "Stnd Alts!Z99": "leak",
    "Leveling!B6": "No",                               // applyJobFlags
    "Leveling!D6": "No",                               // applyJobFlags
    "Leveling!B77": '=IF(D6="yes",0.07975,0)',         // applyRemodelRateOverride
    "Copy1!B6": "No",                                  // a copy OF Leveling -- its own sheet
  };
  const api = build({
    state: { tab_copies: [] },
    sheetCache: { Leveling: { cells: [{ row: 1, col: 1, value: 1 }, { row: 2, col: 1, value: 2 }] } },
    cellValues, HF,
  });
  api.setDeferred(["Leveling", "Epoxy blank"]);
  out.replay = {
    returned: api.loadDeferredIntoEngine("Leveling"),
    log: HF.log,
    stillDeferred: api.peek().sort(),
  };
}

// ── 4. a tab init() DID load is never re-loaded ──────────────────────────────
//
// setSheetContent replaces the sheet wholesale, so running this on an eager tab would throw away
// every edit the estimator has typed since the page opened.
{
  const HF = fakeHF();
  const api = build({
    state: { tab_copies: [] },
    sheetCache: { Epoxy: { cells: [{ row: 1, col: 1, value: 1 }] } },
    cellValues: { "Epoxy!B6": "No" }, HF,
  });
  api.setDeferred(["Leveling"]);
  out.eagerTabUntouched = { returned: api.loadDeferredIntoEngine("Epoxy"), log: HF.log };
}

// ── 5. a copied tab never arrives here either ────────────────────────────────
{
  const HF = fakeHF();
  const api = build({
    state: { tab_copies: [{ id: "Copy1", source: "Epoxy" }] },
    sheetCache: { Copy1: { cells: [{ row: 1, col: 1, value: 1 }] } },
    cellValues: { "Copy1!B6": "No" }, HF,
  });
  api.setDeferred(["Leveling"]);
  out.copyUntouched = { returned: api.loadDeferredIntoEngine("Copy1"), log: HF.log };
}

// ── 6. once, and only once ───────────────────────────────────────────────────
{
  const HF = fakeHF();
  const api = build({
    state: { tab_copies: [] },
    sheetCache: { Leveling: { cells: [{ row: 1, col: 1, value: 1 }] } },
    cellValues: { "Leveling!B6": "No" }, HF,
  });
  api.setDeferred(["Leveling"]);
  const first = api.loadDeferredIntoEngine("Leveling");
  const callsAfterFirst = HF.log.length;
  const second = api.loadDeferredIntoEngine("Leveling");
  out.onceOnly = { first, second, callsAfterFirst, callsAfterSecond: HF.log.length };
}

// ── 7. the engine not being up is not a licence to forget the tab ────────────
//
// `HF.ready` false means the load cannot happen now. It still must not leave the name sitting in
// deferredTabs claiming it did.
{
  const HF = fakeHF(false);
  const api = build({
    state: { tab_copies: [] }, sheetCache: { Leveling: { cells: [] } }, cellValues: {}, HF,
  });
  api.setDeferred(["Leveling"]);
  out.engineNotReady = { returned: api.loadDeferredIntoEngine("Leveling"), log: HF.log };
}

// EMITTED AT THE BOTTOM, not here: scenario 8 is asynchronous by nature (it exists to
// interleave two showSheet calls) and a synchronous write here printed the report before
// that scenario had an answer -- the key was simply absent, which reads as "not tested"
// rather than as a failure.

// ── 8. a slow tab must not paint over the tab you switched to ──────────────
//
// THIS RACE IS WHAT THE DEFERRAL ABOVE MADE REACHABLE. Before it, every tab was already in
// sheetCache and showSheet never awaited anything; now four tabs fetch on click, so a second
// click can complete while the first is still on the wire. showSheet sets activeSheet at the
// top and, without a guard, renders at the bottom whatever IT fetched -- leaving the grid
// showing one sheet while activeSheet, the tab bar and the badge say another.
//
// That mismatch is not cosmetic: every structural op reads activeSheet, so "Delete row 55" on
// the grid in front of the estimator deletes row 55 from the OTHER sheet and persists it.
//
// EXECUTED WITH A FETCH THE TEST CONTROLS, because the bug only exists in the interleaving.
// A source assertion on "activeSheet !== name" would pass with the line in the wrong place.
(function () {
  const rendered = [];
  let releaseSlow;
  const slow = new Promise((res) => { releaseSlow = res; });

  const body = [
    grab(/^let activeSheet = .*$/m, "activeSheet"),
    grab(/^async function showSheet\(name\) \{[\s\S]*?^\}/m, "showSheet"),
    "return { showSheet, active: () => activeSheet };",
  ].join(NL);

  const el = () => ({ textContent: "", className: "", querySelectorAll: () => [] });
  const deps = {
    tabBar: { querySelectorAll: () => [] },
    badge: el(), sheetGrid: el(),
    HF: { unregisterAll: () => {} },
    syncFormulaBar: () => {},
    labelFor: (n) => n,
    renderSheet: (data) => { rendered.push(data && data.name); },
    loadDeferredIntoEngine: () => {},
    _clearRangeSel: () => {},
    _activeCellInput: null, _rangeSel: null, _rangeEls: [],
    sheetCache: { Epoxy: { name: "Epoxy" } },   // Epoxy cached, Leveling not
    TW: { authHeaders: () => ({}) },
    fetch: (url) => url.indexOf("Leveling") !== -1
      ? slow.then(() => ({ ok: true, json: async () => ({ name: "Leveling" }) }))
      : Promise.resolve({ ok: true, json: async () => ({ name: "Epoxy" }) }),
  };
  const names = Object.keys(deps);
  const api = new Function(...names, body)(...names.map((k) => deps[k]));

  out.sheetSwitchRace = (async () => {
    const first = api.showSheet("Leveling");   // starts, parks on the slow fetch
    await api.showSheet("Epoxy");              // cached, completes immediately
    const afterSwitch = rendered.slice();
    releaseSlow();                             // Leveling finally arrives
    await first;
    return {
      renderedInOrder: rendered.slice(),
      renderedBeforeTheSlowOneLanded: afterSwitch,
      activeSheetAtEnd: api.active(),
      // THE ONE THAT MATTERS: whatever is painted last must be the tab activeSheet names,
      // because that is the sheet a structural op will edit.
      gridMatchesActiveSheet: rendered[rendered.length - 1] === api.active(),
      // and the stale one must never have painted at all
      staleNeverPainted: rendered.indexOf("Leveling") === -1,
    };
  })();
})();

(async () => {
  out.sheetSwitchRace = await out.sheetSwitchRace;
  process.stdout.write(JSON.stringify(out) + NL);
})();
