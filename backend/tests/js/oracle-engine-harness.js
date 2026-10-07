"use strict";
/* Runs the PAGE's own engine setup next to the oracle's, and prints both.
 *
 *   node oracle-engine-harness.js [<repo root>]
 *
 * The oracle (backend/tests/js/workbook-oracle.js) builds Kyle's workbook through
 * docs/excel-parity-audit/engine.js, and its claim is "the same engine the Estimate Review page runs".
 * Five things make that claim true and none of them can be seen from a green run, because a different
 * option, alias rule or load still produces plausible numbers:
 *
 *   - the options HyperFormula.buildEmpty is given,
 *   - the rule that renames a workbook name HyperFormula refuses (Glaze4 becomes Glaze_4),
 *   - the rewrite that carries that rename into every formula,
 *   - the block that registers the workbook's named expressions (which name is refused, which scope is
 *     kept, what happens when even the alias will not register),
 *   - HF.loadSheet, which turns a sheet's cells into the grid the engine is given,
 *   - and the ORDER of it all: every sheet added, then the names, then the cells.
 *
 * So this file lifts those pieces out of frontend/js/estimate-review.js and RUNS them. The first three
 * against a stand-in that records what buildEmpty was given, the page's own aliasFor and HF.rewriteNames on
 * a table of awkward inputs. The last three against a RECORDING stand-in for HyperFormula: the page's own HF.init,
 * its own named-expression block (cut out of the boot function by its brackets and run as it is) and its own
 * HF.loadSheet are run on a small fixture, and engine.js's build() is run on the same fixture against a second
 * recorder. Every call each of them made to the engine (buildEmpty, addSheet, getSheetId,
 * isItPossibleToAddNamedExpression, addNamedExpression with or without a scope, setSheetContent with the grid)
 * is kept in order, and the two lists have to be equal. The page's boot order cannot be run here (the boot
 * function is the whole page), so it is read from the source: init, then the names block, then no sheet loaded
 * in between.
 *
 * The stand-in answers the way the real engine does where it matters: it refuses a name shaped like a cell
 * address (Glaze4, AB12) and one other name, and it throws for two, so every branch of the page's block is taken.
 *
 * It prints
 *     { pin, sriOfAbc, twoTagsError,
 *       page: { options, alias, rewrite }, engine: { options, alias, rewrite },
 *       load: { fixture, page: { calls, aliases, registered }, engine: { calls, aliases, registered, warnings },
 *               order } }
 * as its last line. test_workbook_oracle.py requires the two halves to be equal.
 *
 * The optional argument is a directory laid out like the repository (docs/excel-parity-audit/engine.js,
 * frontend/js/estimate-review.js, frontend/estimate-review.html): the tests hand it a scratch copy with one
 * line changed to see this go red.
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(__dirname, "..", "..", "..");
const E = require(path.join(ROOT, "docs", "excel-parity-audit", "engine.js"));
const src = L.read(path.join(ROOT, "frontend", "js", "estimate-review.js"));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

const PAGE_HF_SOURCE = L.grabConst(src, "HF", { where: "estimate-review.js" }) + "\nreturn HF;";

// ── the options, the alias rule and the rewrite ──────────────────────────────
// the page: HF.init against a HyperFormula that only remembers its options
let seen = null;
const standIn = { buildEmpty: (options) => { seen = options; return { addSheet() {}, getSheetId() { return 0; } }; } };
const HF = new Function("HyperFormula", PAGE_HF_SOURCE)(standIn);
HF.init(["Epoxy"]);
if (seen === null) throw new Error("HF.init did not call HyperFormula.buildEmpty");

// the page's alias rule is an arrow function inside init(); lift its text and run it
const aliasText = L.grab(src, /const aliasFor = \(name\) => \{[\s\S]*?\n\s*\};/, "the aliasFor arrow in init()");
const pageAlias = new Function(aliasText + "\nreturn aliasFor;")();

const NAMES = ["Glaze4", "Glaze10", "Silica", "AT_Clear_Satin_w_Grit", "AB12", "x"];
const FORMULAS = ["=SUM(Glaze4)", "=Glaze4*2+Glaze45", "=xGlaze4+Glaze4", "=Epoxy!Glaze4+Glaze4.x", "=Glaze4(Glaze4)",
  "=Silica+Glaze4", "just text", 12, null, "=Glaze4"];

HF.nameAliases = { Glaze4: "Glaze_4", AB12: "AB_12" };
const table = new Map([["Glaze4", "Glaze_4"], ["AB12", "AB_12"]]);
const rewrite = E.makeRewriter(table);

// the pin the oracle holds the installed bytes to, read by engine.js (the test reads it again in Python)
let twoTagsError = null;
try {
  E.pinnedSri('<script src="https://cdn/hyperformula@2.7.1/dist/x.js" integrity="sha384-A"></script>' +
              '<script src="https://cdn/hyperformula@2.7.1/dist/y.js" integrity="sha384-B"></script>');
} catch (e) { twoTagsError = String(e.message); }

// ── loading: the page's block and HF.loadSheet against engine.js's build ─────
/** A HyperFormula that does nothing but remember every call made to it, in order, and answers the way the real
 *  one does where it matters. The first sheet it hands out has id 0, which is falsy, on purpose: it is the id
 *  a careless `if (scopeId)` would drop. */
const CELL_SHAPED = /^[A-Za-z]+[0-9]+$/;
const REFUSED_FOR_ANOTHER_REASON = new Set(["Reserved"]);   // its alias is Reserved_n
const THROWS_WHEN_ADDED = new Set(["Refused", "Zed_9"]);    // Zed9 is cell-shaped and its alias Zed_9 throws too

function recorder() {
  const calls = [];
  const note = (name, args) => calls.push([name].concat(Array.from(args)));
  const ids = new Map();
  const HyperFormula = {
    buildEmpty() {
      note("buildEmpty", arguments);
      return {
        addSheet(name) { note("addSheet", arguments); ids.set(name, ids.size); return name; },
        getSheetId(name) { note("getSheetId", arguments); return ids.get(name); },
        isItPossibleToAddNamedExpression(name) {
          note("isItPossibleToAddNamedExpression", arguments);
          return !CELL_SHAPED.test(name) && !REFUSED_FOR_ANOTHER_REASON.has(name);
        },
        addNamedExpression(name) {
          note("addNamedExpression", arguments);
          if (THROWS_WHEN_ADDED.has(name)) throw new Error("the stand-in refuses " + name);
        },
        setSheetContent() { note("setSheetContent", arguments); },
      };
    },
  };
  // undefined would vanish into null in JSON, and `scope` being absent or undefined is exactly what is compared
  const tagged = () => JSON.parse(JSON.stringify(calls, (k, v) => (v === undefined ? "<undefined>" : v)));
  return { HyperFormula: HyperFormula, calls: tagged };
}

const FIXTURE = {
  order: ["Epoxy", "Polish", "Seal (+Jnts)"],
  names: [
    { name: "Silica", expression: "=Epoxy!$W$145", scope: null },
    { name: "Glaze4", expression: "=Epoxy!$T$153", scope: null },          // cell-shaped: registered as Glaze_4
    { name: "AB12", expression: "=Epoxy!$A$12", scope: null },             // cell-shaped: registered as AB_12
    { name: "Reserved", expression: "=Epoxy!$A$13", scope: null },         // refused, no digits: registered as Reserved_n
    { name: "Local_Rate", expression: "=Epoxy!$C$47", scope: "Epoxy" },    // belongs to the first sheet, id 0
    { name: "Orphan", expression: "=Epoxy!$A$2", scope: "No such tab" },   // a scope the workbook does not have
    { name: "Refused", expression: "=Epoxy!$A$3", scope: null },           // the engine throws
    { name: "Zed9", expression: "=Epoxy!$A$4", scope: null },              // cell-shaped, and the alias throws too
  ],
  sheets: {
    "Epoxy": { cells: [
      { addr: "A1", row: 1, col: 1, value: "Local?" },
      { addr: "D1", row: 1, col: 4, value: null },
      { addr: "B2", row: 2, col: 2, isFormula: true, formula: "=SUM(Glaze4)+Glaze4*2+Glaze45+AB12+xGlaze4", value: 5 },
      { addr: "F2", row: 2, col: 6, value: true },
      { addr: "C3", row: 3, col: 3, value: 12.5 },
      { addr: "E4", row: 4, col: 5, isFormula: true, formula: "=Epoxy!Glaze4+Glaze4.x+Silica+Reserved", value: 0 },
      { addr: "G5", row: 5, col: 7, value: "=Glaze4" },
    ] },
    "Polish": { cells: [] },
    "Seal (+Jnts)": { cells: [
      { addr: "A1", row: 1, col: 1, value: 0 },
      { addr: "B6", row: 6, col: 2, isFormula: true, formula: "='Gyp (USG 1-8\")'!B5&\"Glaze4\"&Glaze4", value: "x" },
    ] },
  },
};

/** The page's named-expression block, cut out of the boot function between its own brackets: from the `try {`
 *  that holds `const nameData = await _namedReady;` to the end of the `catch` that follows it. It reads three
 *  free names (HF, _namedReady, console); a fourth added to the page is a ReferenceError here, which is the
 *  signal to extend this harness and not to stub the new name. */
function liftNamesBlock(text) {
  const needle = "const nameData = await _namedReady;";
  const at = text.indexOf(needle);
  if (at < 0 || text.indexOf(needle, at + 1) >= 0) {
    throw new Error("the named-expression block of estimate-review.js is gone or appears twice -- rewrite this harness, don't stub it");
  }
  const open = text.lastIndexOf("try {", at);
  if (open < 0) throw new Error("the named-expression block is no longer inside a try -- rewrite this harness, don't stub it");
  const tryEnd = L.balanced(text, open + "try ".length);
  const after = /^\s*catch\s*\(\s*\w+\s*\)\s*\{/.exec(text.slice(tryEnd + 1));
  if (!after) throw new Error("the named-expression block no longer ends in a catch -- rewrite this harness, don't stub it");
  return text.slice(open, L.balanced(text, tryEnd + after[0].length) + 1);
}

function clone(x) { return JSON.parse(JSON.stringify(x)); }

async function loadedByThePage(fixture) {
  const rec = recorder();
  const page = new Function("HyperFormula", PAGE_HF_SOURCE)(rec.HyperFormula);
  page.init(fixture.order);
  const said = [];
  const register = new AsyncFunction("HF", "_namedReady", "console", liftNamesBlock(src));
  await register(page, Promise.resolve({ names: clone(fixture.names) }), { log: (...a) => said.push(a), warn: () => {} });
  for (const name of fixture.order) page.loadSheet(name, clone(fixture.sheets[name].cells));
  const line = said.length ? /Registered (\d+)\/(\d+) named expressions/.exec(String(said[0][0])) : null;
  if (!line) throw new Error("the page's named-expression block no longer says 'Registered N/M named expressions' -- rewrite this harness");
  return { calls: rec.calls(), aliases: Object.assign({}, page.nameAliases), registered: [Number(line[1]), Number(line[2])] };
}

function loadedByTheEngine(fixture) {
  const rec = recorder();
  const wb = E.build(rec.HyperFormula, clone(fixture));
  return { calls: rec.calls(), aliases: Object.fromEntries(wb.aliases), registered: [wb.namesRegistered, fixture.names.length],
    warnings: wb.warnings.length };
}

/** The order the page's boot function does things in, read from its source: HF.init, then the names, with no
 *  HF.loadSheet in between. engine.js does the same in the same order (see the call lists above). */
function bootOrder(text) {
  const init = text.indexOf("HF.init(sheets);");
  const names = text.indexOf("const nameData = await _namedReady;");
  if (init < 0 || names < 0) throw new Error("HF.init(sheets) or the names block moved -- rewrite this harness, don't stub it");
  const firstLoad = text.indexOf("HF.loadSheet(", init);
  return { init: init, names: names, firstLoad: firstLoad,
    ok: init < names && firstLoad > names };
}

async function main() {
  const page = await loadedByThePage(FIXTURE);
  const engine = loadedByTheEngine(FIXTURE);
  console.log(JSON.stringify({
    pin: E.pagePin(),
    sriOfAbc: E.sriOf(Buffer.from("abc")),
    twoTagsError: twoTagsError,
    page: {
      options: seen,
      alias: NAMES.map((n) => pageAlias(n)),
      rewrite: FORMULAS.map((f) => HF.rewriteNames(f)),
    },
    engine: {
      options: E.PAGE_OPTIONS,
      alias: NAMES.map((n) => E.aliasFor(n)),
      rewrite: FORMULAS.map((f) => rewrite(f)),
    },
    load: {
      fixture: { names: FIXTURE.names.length, sheets: FIXTURE.order.length },
      page: page,
      engine: engine,
      order: bootOrder(src),
    },
  }));
}

main().catch((e) => { console.error(e && e.stack ? e.stack : String(e)); process.exit(1); });
