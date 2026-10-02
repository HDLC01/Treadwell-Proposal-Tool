"use strict";
/* Execute the estimate screen's "Hard Bid? is always No" rule out of the shipped estimate-review.js.
 *
 * Hanz, 2026-10-03: "We also need to remove the hard bid discount. Even on active projects and
 * direct projects." He chose to remove ONLY the automatic switch (Kyle's 2.5% / 4% formula on the
 * "Hard Bid?" cell) and to keep the row where an estimator types his own discount.
 *
 * WHAT IS EXECUTED, AND WHY IT IS ALL OF IT. The screen's price is whatever the HyperFormula engine
 * computes from the values it is handed. So this lifts the REAL `HF` object (only its HyperFormula
 * instance is replaced, by a recorder of `setCellContents`), the real `isHardBidFlagCell` /
 * `dropHardBidFlags` with the real coordinate and copy resolution under them, and the real
 * "Apply saved overrides" replay out of init(), and reports exactly which cells reach the engine.
 *
 * BEFORE AND AFTER IN ONE RUN. "Before" is the same lifted code with `isHardBidFlagCell` answering
 * false for everything and `dropHardBidFlags` dropping nothing -- which is precisely what the page
 * did until this change -- so the comparison is between two executions, not against a hand copy.
 *
 * Usage: node no-hard-bid-harness.js <frontend-dir> <fixtures-json>  ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const FIXTURES = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
// Normalised on read: git hands these files out CRLF on Windows and LF in CI, and the lifts below
// are anchored on the newline.
const SRC = fs.readFileSync(path.join(ROOT, "js", "estimate-review.js"), "utf8").replace(/\r\n/g, "\n");
const NL = "\n";

function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + what + " -- rewrite this harness, don't stub it");
  return m[0];
}
function lift(name, deps) {
  const re = new RegExp("^function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}", "m");
  const src = grab(re, name);
  const names = Object.keys(deps);
  return new Function(...names, src + NL + "return " + name + ";")(...names.map(k => deps[k]));
}

const { HARD_BID_FLAG_LAYOUTS, HARD_BID_FLAG_ADDR } = new Function(
  grab(/^const HARD_BID_FLAG_LAYOUTS = \[[\s\S]*?\];$/m, "HARD_BID_FLAG_LAYOUTS") + NL +
  grab(/^const HARD_BID_FLAG_ADDR = .*;$/m, "HARD_BID_FLAG_ADDR") + NL +
  "return { HARD_BID_FLAG_LAYOUTS, HARD_BID_FLAG_ADDR };")();
const HF_SRC = grab(/^const HF = \{[\s\S]*?^\};$/m, "the HF engine wrapper");
const REPLAY_SRC = grab(
  /^  \/\/ Apply saved overrides\n  for \(const \[key, val\] of Object\.entries\(cellValues\)\) \{[\s\S]*?\n  \}$/m,
  "init()'s saved-override replay");

const SHEETS = ["Epoxy", "Polish", 'Gyp (USG 1-8")', "Seal", "Seal (+Jnts)", "Epoxy blank", "Leveling"];

function run(fx, enforce) {
  const state = { tab_copies: (fx.tab_copies || []).slice(), tab_structs: (fx.tab_structs || []).slice() };
  const cellValues = Object.assign({}, fx.cell_values);
  const deps = { state, cellValues };
  deps.structOpsFor = new Function("state",
    grab(/^function structOpsFor\(sheetId\) .*$/m, "structOpsFor") + NL + "return structOpsFor;")(state);
  deps._shiftIdx = lift("_shiftIdx", deps);
  deps.txAddr = lift("txAddr", deps);
  deps.layoutIdFor = lift("layoutIdFor", deps);
  deps.HARD_BID_FLAG_LAYOUTS = HARD_BID_FLAG_LAYOUTS;
  deps.HARD_BID_FLAG_ADDR = HARD_BID_FLAG_ADDR;
  const isFlag = enforce ? lift("isHardBidFlagCell", deps) : () => false;
  deps.isHardBidFlagCell = isFlag;
  const drop = enforce ? lift("dropHardBidFlags", deps) : () => 0;

  const writes = {};
  let calls = 0;
  const HF = new Function("HyperFormula", "isHardBidFlagCell", HF_SRC + NL + "return HF;")(null, isFlag);
  const names = SHEETS.concat(state.tab_copies.map(c => c.id));
  HF.instance = {
    setCellContents(a, v) {
      const col = (() => { let n = a.col + 1, s = ""; while (n > 0) { n--; s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26); } return s; })();
      writes[names[a.sheet] + "!" + col + (a.row + 1)] = v;
      calls++;
      return [];
    },
  };
  names.forEach((n, i) => { HF.sheetIdByName[n] = i; });
  HF.ready = true;

  const dropped = drop();
  new Function("cellValues", "HF", REPLAY_SRC)(cellValues, HF);
  const replayed = Object.assign({}, writes);
  // A keystroke or an AI answer reaching the engine directly, after load, on every flag cell.
  const direct = {};
  for (const k of fx.direct || []) {
    const cut = k.indexOf("!");
    const before = calls;
    HF.setCellValue(k.slice(0, cut), k.slice(cut + 1), "Yes");
    direct[k] = calls > before;
  }
  return { writes: replayed, dropped, kept: cellValues, direct,
           isFlag: Object.fromEntries((fx.probe || []).map(k => {
             const cut = k.indexOf("!");
             return [k, !!isFlag(k.slice(0, cut), k.slice(cut + 1))];
           })) };
}

const out = { layouts: HARD_BID_FLAG_LAYOUTS, fixtures: {} };
for (const name in FIXTURES) {
  out.fixtures[name] = { before: run(FIXTURES[name], false), after: run(FIXTURES[name], true) };
}
console.log(JSON.stringify(out));
