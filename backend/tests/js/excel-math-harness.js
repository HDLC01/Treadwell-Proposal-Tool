"use strict";
/* The shared number helpers (js/excel-math.js), EXECUTED. The last line printed is one line of JSON.
 *
 * Usage: node excel-math-harness.js <frontend-dir>
 *
 * It prints what the helpers DID with the inputs below, never what they should do. The expected
 * answers are written out by hand in test_excel_math.py from Excel's own rules, so the test is not a
 * second copy of the formulas. The same harness runs against a scratch frontend with one line of one
 * file broken, which is how that test proves every assertion in it can fail.
 *
 * It needs, beside excel-math.js, the two modules whose behaviour is tied to it:
 *   js/bid-model.js     re-exports the helpers (is it the SAME function, or a copy?)
 *   js/library-core.js  its pack count is a CEIL with the same twelve-figure guard as `ceiling`
 */
const path = require("path");

const frontend = path.resolve(process.argv[2] || "");
const M = require(path.join(frontend, "js", "excel-math.js"));
const B = require(path.join(frontend, "js", "bid-model.js"));
const L = require(path.join(frontend, "js", "library-core.js"));

const out = {};

// ── the surface ──────────────────────────────────────────────────────────────
out.exports = Object.fromEntries(Object.keys(M).sort().map((k) => [k, typeof M[k]]));

// ── one function, or a copy? ─────────────────────────────────────────────────
const RE_EXPORTED = ["num", "roundUp", "copyInto", "money", "money2", "pct", "fmtSf"];
out.sameFunction = Object.fromEntries(RE_EXPORTED.map((k) => [k, B[k] === M[k]]));

// ── num: whatever a person types or pastes ───────────────────────────────────
const NUM_INPUTS = [
  ["12,500", "12,500"], ["$1,200", "$1,200"], [" 12,500 ", " 12,500 "], ["$1,200.50", "$1,200.50"],
  ["empty text", ""], ["null", null], ["undefined", undefined], ["NaN", NaN], ["Infinity", Infinity],
  ["-Infinity", -Infinity], ["abc", "abc"], ["12abc", "12abc"], ["1e3", "1e3"], ["true", true],
  ["false", false], ["-5", "-5"], [".5", ".5"], ["5.", "5."], ["0x10", "0x10"], ["zero", 0],
  ["one", 1], ["half", 0.5],
];
out.num = Object.fromEntries(NUM_INPUTS.map(([label, v]) => [label, M.num(v)]));

// ── roundUp: Excel's ROUNDUP(n, 0). The long sweep is test_roundup_parity_js.py; these are the named cases ──
const ROUNDUP_INPUTS = [
  ["27,500 x 1.10 (dust)", 110.00000000000001], ["724 sf with dye (dust)", 362.00000000000006],
  ["a real fraction", 220.22000000000003], ["hard-bid give-back", -1234.2], ["PR 450's case", -856.8],
  ["zero", 0], ["text with a comma", "1,234.1"], ["null", null], ["one cent over a dollar", 1.01],
];
out.roundUp = Object.fromEntries(ROUNDUP_INPUTS.map(([label, v]) => [label, M.roundUp(v)]));

// ── ceiling: Excel's CEILING(n, significance) ────────────────────────────────
const CEILING_CASES = [
  ["7 to 5", 7, 5], ["10 to 5", 10, 5], ["0 to 5", 0, 5], ["4.2 to 0.5", 4.2, 0.5],
  ["2.5 to 1", 2.5, 1], ["2.5, significance left out", 2.5, undefined],
  ["2.5, significance null", 2.5, null],
  ["dust over 1", 110.00000000000001, 1], ["-2.5 to 2", -2.5, 2], ["1234.1 to 100", 1234.1, 100],
  ["significance 0", 1234, 0], ["text with a dollar sign", "$1,200.40", 1],
  ["null number", null, 5], ["undefined number", undefined, 5], ["text that is no number", "abc", 5],
  ["0.234 to 0.01", 0.234, 0.01],
  // 0.07 / 0.01 is 7.000000000000001 and 0.27 / 0.09 is 3.0000000000000004 in IEEE-754, with both
  // operands clean: a bare ceil buys an 8th cent and a 4th step of 0.09. Only the quotient guard helps.
  ["0.07 to 0.01 (quotient dust)", 0.07, 0.01],
  ["0.27 to 0.09 (quotient dust)", 0.27, 0.09],
  // 0.1 * 3 is 0.30000000000000004 and its quotient by 0.1 is 3.0000000000000004: a bare ceil, 4 steps.
  ["three steps of 0.1 (value and quotient dust)", 0.1 * 3, 0.1],
];
out.ceiling = Object.fromEntries(CEILING_CASES.map(([label, n, s]) => [label, M.ceiling(n, s)]));

// ── isBlank ──────────────────────────────────────────────────────────────────
const BLANK_INPUTS = [
  ["null", null], ["undefined", undefined], ["empty text", ""], ["spaces", "   "], ["tab and newline", "\t\n"],
  ["zero", 0], ["the text 0", "0"], ["false", false], ["an empty array", []], ["a letter", "a"], ["a space then a letter", " a "],
];
out.isBlank = Object.fromEntries(BLANK_INPUTS.map(([label, v]) => [label, M.isBlank(v)]));

// ── copyInto: rows arrive from saved drafts, so a key is user data ───────────
(function () {
  const hostile = JSON.parse('{"__proto__": {"polluted": "yes"}, "constructor": 7, "prototype": 8, "label": "Polish", "n": 0}');
  const dst = { keep: 1 };
  const returned = M.copyInto(dst, hostile);
  const fresh = {};
  out.copyInto = {
    returnsDestination: returned === dst,
    keys: Object.keys(dst).sort(),
    label: dst.label,
    zeroKept: dst.n === 0,
    prototypeUntouched: Object.getPrototypeOf(dst) === Object.prototype,
    nothingPolluted: fresh.polluted === undefined && dst.polluted === undefined,
    constructorIsStillObject: dst.constructor === Object,
    nullSource: Object.keys(M.copyInto({ a: 1 }, null)),
    undefinedSource: Object.keys(M.copyInto({ a: 1 }, undefined)),
    laterKeyWins: M.copyInto({ a: 1, b: 2 }, { b: 3 }).b,
    sourceUntouched: JSON.stringify(Object.keys(hostile).sort()),
  };
})();

// ── the text helpers ─────────────────────────────────────────────────────────
out.text = {
  money: [M.money(15681), M.money(0), M.money(-1500), M.money(-0.4), M.money(1234.5), M.money("$1,200"), M.money(null)],
  money2: [M.money2(32.2), M.money2(0), M.money2(-0.001), M.money2(-4.5), M.money2(1234.5), M.money2("abc")],
  pct: [M.pct(0.45), M.pct(-0.025), M.pct(0.09475), M.pct(0.027), M.pct(0), M.pct(1), M.pct("abc")],
  fmtSf: [M.fmtSf(12500), M.fmtSf(1234.567), M.fmtSf(0), M.fmtSf("12,500"), M.fmtSf(null)],
};

// ── the pack count the Item Library takes is this leaf's CEILING (significance 1) ─────────────────
// priceLine returns `needed`, `buy_qty` and `packs`, so nothing is recomputed here: the leaf is asked
// about the very quotient the library rounded, and the two must agree.
(function () {
  const coverages = [100, 125, 200, 275, 350, 775, 1500, 3500];
  const areas = [1, 99, 100, 101, 275, 2875, 12345.678, 27500, 40000, 123456];
  const packs = [1, 2, 5, 10];
  const wastes = [0, 5, 10, 15];
  let total = 0, disagree = [], bites = 0;
  for (const cov of coverages) for (const buy of packs) for (const waste of wastes) {
    const item = { id: "x", coverage: cov, unit_cost: 10, buy_qty: buy, waste_pct: waste, roundup: true };
    for (const area of areas) {
      const r = L.priceLine({ item_id: "x" }, [item], area);
      total++;
      const viaLeaf = M.ceiling(r.needed / r.buy_qty, 1);
      if (viaLeaf !== r.packs) disagree.push([cov, buy, waste, area, r.packs, viaLeaf]);
      if (Math.ceil(r.needed / r.buy_qty) !== r.packs) bites++;      // a bare ceil would have said something else
    }
  }
  out.packCount = { total, disagree: disagree.slice(0, 5), disagreeCount: disagree.length, bites };
})();

console.log(JSON.stringify(out));
