// Excel's number rules for the bid maths: one small file with no dependencies.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT IS HERE. The helpers every part of the bid maths needs that are about numbers and text and
// not about a work type: reading a number out of whatever a person typed (num), Excel's ROUNDUP and
// CEILING (roundUp, ceiling), whole-dollar, cents, percent and area text (money, money2, pct, fmtSf),
// and two small primitives (copyInto, isBlank). They sat at the top of the model module (js/bid-model.js,
// which was then still named for Polish alone) until Phase 5 of the v2 program moved them here, so that
// the model and the markup engine Phase 8 adds read ONE copy. js/bid-model.js binds them to the names
// it always used and exports them again under those names, so no caller changed.
//
// WHAT MAKES IT A LEAF (docs/v2-architecture.md, sections 3 to 5). It depends on nothing. It never
// touches the DOM, `fetch` or the clock. It holds no rate, no work type and no cell address: those
// are data for a profile, and a helper belongs in here only when two modules need it. Everything
// below was moved without a change to what it does, except `ceiling`, which is new (read it).
//
// ROUNDUP, ONCE ON THE BID SIDE. `roundUp` is the one bid-side ROUNDUP. js/markup-core.js keeps its
// own `excelRoundUp(n, digits)` because the markup formula engine needs the digits argument and has
// to load on a page that loads nothing else; backend/tests/test_roundup_parity_js.py holds the two,
// and the Python copy in pricing.py, equal on the same inputs. The workbook engine's ROUNDUP and
// CEILING (js/xl-excel-rounding.js) are a different job: they make HyperFormula agree with Excel.
(function (root, factory) {
  var api = factory();
  root.TWExcelMath = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /** A number from anything a person might type or paste. 0 when it isn't one.
   *
   *  Deliberately unlike library-core's num(), which returns null: every caller here is
   *  ARITHMETIC, and one null in the middle of the chain would poison every line below it. An
   *  empty labor row has to cost nothing, not NaN. Tolerates "$1,200" and " 12,500 " because
   *  these values get pasted out of spreadsheets. */
  function num(raw) {
    if (raw === null || raw === undefined || raw === "") return 0;
    if (typeof raw === "number") return isFinite(raw) ? raw : 0;
    if (typeof raw === "boolean") return 0;
    var s = String(raw).replace(/[$,\s]/g, "");
    if (s === "" || !/^-?\d*\.?\d+$/.test(s)) return 0;
    var n = parseFloat(s);
    return isFinite(n) ? n : 0;
  }

  /** Copy one row's own keys onto `dst`, refusing the three names that would write to a prototype
   *  instead of the row. Rows arrive from saved drafts and the library, so a key is user data. A
   *  hostile "__proto__" is dropped (it never was a real field); every ordinary key copies as before,
   *  so a JSON-serialised row keeps its exact shape. */
  function copyInto(dst, src) {
    // No hand-written `dst[k] =` on a user-supplied k (CodeQL js/remote-property-injection): the own
    // entries are filtered first, Object.fromEntries builds them as plain data properties, and only
    // then does Object.assign copy that clean object -- the same own-key, set-based copy as before.
    var safe = Object.entries(src || {}).filter(function (e) {
      return e[0] !== "__proto__" && e[0] !== "constructor" && e[0] !== "prototype";
    });
    return Object.assign(dst, Object.fromEntries(safe));
  }

  /** Excel's ROUNDUP(n, 0): away from zero, so -1.2 becomes -2.
   *
   *  Float-guarded to twelve significant figures first. 27,500 × 1.10 is 110.00000000000001 in
   *  IEEE-754 and a bare ceil() would buy a whole extra dollar off the back of the error — on
   *  exactly the round numbers an estimator checks by hand. Twelve figures is far finer than any
   *  money on this screen and far coarser than the noise. */
  function roundUp(n) {
    var v = num(n);
    var g = parseFloat(v.toPrecision(12));
    return g >= 0 ? Math.ceil(g) : -Math.ceil(-g);
  }

  /** Excel's CEILING(n, significance): the smallest multiple of `significance` that is not below
   *  `n`. CEILING(7, 5) is 10, CEILING(4.2, 0.5) is 4.5, and CEILING(n, 1) is the whole-unit ceiling
   *  the Item Library takes for a pack count (backend/tests/test_excel_math.py holds the two equal).
   *
   *  NEW IN PHASE 5, and the one function here that was not moved: nothing on the bid side called it
   *  yet, and the Epoxy tab needs it (78 of its formulas are CEILING, e.g. `=CEILING(C125*C126,50)`;
   *  Phase 8). It is the workbook engine's own CEILING (js/xl-excel-rounding.js) without HyperFormula
   *  around it, so a bid priced here and a sheet evaluated there agree: the value and then the
   *  quotient are each snapped to twelve significant figures before the ceil, which makes
   *  110.00000000000001 over 1 come out 110 and not 111. A significance of 0 gives 0, as Excel does,
   *  and a missing one is 1. Like roundUp, the inputs go through num(), so text that is not a number
   *  reads as 0 and an empty box costs nothing.
   *
   *  A negative number with a positive significance rounds toward zero (CEILING(-2.5, 2) is -2), as
   *  in Excel. A negative significance is not a thing Kyle's sheets do, so the arithmetic is simply
   *  the engine's and nothing more is promised for it. */
  function ceiling(n, significance) {
    var s = (significance === undefined || significance === null) ? 1 : num(significance);
    if (s === 0) return 0;
    var v = parseFloat(num(n).toPrecision(12));
    var q = parseFloat((v / s).toPrecision(12));
    return Math.ceil(q) * s;
  }

  /** Whole dollars: "$15,681". Every line of the chain is already an integer (ROUNDUP put it
   *  there), so decimals here would only be float dust. */
  function money(n) {
    var v = num(n);
    var r = Math.round(Math.abs(v));
    return (v < 0 && r !== 0 ? "-$" : "$") + r.toLocaleString("en-US");
  }

  /** Dollars and cents: "$32.20". For the things a person types — an hourly rate, a price per SF
   *  — where the cents are the number. */
  function money2(n) {
    var v = num(n);
    var s = Math.abs(v).toLocaleString("en-US",
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (v < 0 && parseFloat(s.replace(/,/g, "")) !== 0 ? "-$" : "$") + s;
  }

  /** A rate as a percentage: 0.45 -> "45%", -0.025 -> "-2.5%", 0.09475 -> "9.475%".
   *
   *  Float noise is stripped first (0.027 × 100 is 2.7000000000000006 in IEEE-754), then the
   *  trailing zeros go, so a whole percentage reads as one. Precision is KEPT rather than
   *  rounded to a tidy two places: 9.475% is the Kansas sales-tax rate and 9.5% is a different
   *  bid on a 40,000 SF floor. */
  function pct(n) {
    var v = num(n) * 100;
    var s = parseFloat(v.toPrecision(12)).toFixed(4);
    s = s.replace(/0+$/, "").replace(/\.$/, "");
    return s + "%";
  }

  /** An area for reading: 12500 -> "12,500". */
  function fmtSf(n) {
    return num(n).toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  /** True for null, undefined and text that is only whitespace. 0 and false are values, not blanks. */
  function isBlank(v) {
    return v === null || v === undefined || (typeof v === "string" && v.replace(/\s/g, "") === "");
  }

  return {
    num: num, copyInto: copyInto, roundUp: roundUp, ceiling: ceiling,
    money: money, money2: money2, pct: pct, fmtSf: fmtSf,
    isBlank: isBlank
  };
});
