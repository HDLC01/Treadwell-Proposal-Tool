"use strict";
/* Runs the PAGE's own engine setup next to the oracle's, and prints both.
 *
 * The oracle (backend/tests/js/workbook-oracle.js) builds Kyle's workbook through
 * docs/excel-parity-audit/engine.js, and its claim is "the same engine the Estimate Review page runs".
 * Three things make that claim true and none of them can be seen from a green run, because a different
 * option or a different alias rule still produces plausible numbers:
 *
 *   - the options HyperFormula.buildEmpty is given,
 *   - the rule that renames a workbook name HyperFormula refuses (Glaze4 becomes Glaze_4),
 *   - the rewrite that carries that rename into every formula.
 *
 * So this file lifts those pieces out of frontend/js/estimate-review.js, RUNS them (buildEmpty against a
 * stand-in that records what it was called with, the page's own aliasFor and HF.rewriteNames on a table
 * of awkward inputs), runs engine.js's versions on the same inputs, and prints
 *     { page: { options, alias, rewrite }, engine: { options, alias, rewrite } }
 * as its last line. test_workbook_oracle.py requires the two halves to be equal.
 */
const path = require("path");
const L = require("./_lib.js");

const REPO = path.resolve(__dirname, "..", "..", "..");
const E = require(path.join(REPO, "docs", "excel-parity-audit", "engine.js"));
const src = L.read(path.join(REPO, "frontend", "js", "estimate-review.js"));

// the page: HF.init against a HyperFormula that only remembers its options
let seen = null;
const standIn = { buildEmpty: (options) => { seen = options; return { addSheet() {}, getSheetId() { return 0; } }; } };
const HF = new Function("HyperFormula", L.grabConst(src, "HF", { where: "estimate-review.js" }) + "\nreturn HF;")(standIn);
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
}));
