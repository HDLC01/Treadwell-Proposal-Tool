// Make HyperFormula's ROUNDUP and CEILING behave the way Excel's do.
//
// Load this on EVERY page that builds a HyperFormula engine, BEFORE the engine is built.
// Registration is global to HyperFormula, so it must happen once and early.
//
// ── WHY THIS FILE EXISTS ─────────────────────────────────────────────────────
//
// Excel quietly cleans a result that is a hair off a round number before using it. HyperFormula
// does not. The estimate workbook wraps almost every subtotal in ROUNDUP(...,0), so a value
// like 19320.000000000004 — the ordinary consequence of adding 17774.4 + 386.4 + 1159.2 in
// binary floating point — rounds UP to 19321 in the browser and stays 19320 in Excel.
//
// The error is always upward, because ROUNDUP only ever goes one way. It compounds through the
// sheet's subtotal chain, so a bid can be several dollars high by the time it reaches the total.
//
// ── THE EVIDENCE ─────────────────────────────────────────────────────────────
//
// Audited against Excel itself on six real Treadwell estimates taken from the Dropbox folder:
// every rounding cell and every headline total, 10,208 cells, compared to the cent. Each engine
// configuration measured in its own process so nothing could leak between them.
//
//     what shipped before ......... 98 cells wrong
//     smartRounding: false ........ 97 cells wrong
//     precisionRounding: 10 ....... 97 cells wrong
//     this file .................... 0 cells wrong
//
// The worst were not polish. Epoxy!D88 — the epoxy total base bid — read $15,219 where the
// workbook says $15,213, and $11,033 where it says $11,029.
//
// So the two settings that looked like cheap fixes are not fixes at all; they move one cell out
// of ninety-eight. Overriding the two functions is what actually closes it.
//
// The harness is in docs/excel-parity-audit/ and is re-runnable on any workbook.
//
// ── WHY 12 SIGNIFICANT DIGITS ────────────────────────────────────────────────
//
// IEEE 754 doubles carry ~15-17 significant digits, and the noise from adding decimal money
// values shows up in the last two or three. Snapping to 12 removes the noise while leaving
// untouched any figure a person could have typed or any legitimate fraction of a cent. Round to
// fewer and real precision would be lost; round to more and the noise survives.
(function () {
  "use strict";

  if (typeof HyperFormula === "undefined") {
    // The page forgot to load HyperFormula first. Say so loudly: silently skipping would leave
    // the bids a few dollars high with nothing to explain it.
    console.error("xl-excel-rounding: HyperFormula is not loaded yet — Excel-compatible " +
                  "ROUNDUP/CEILING were NOT registered, so totals may read high.");
    return;
  }

  // The node build exports these on the module; the browser UMD bundle hangs them off the class.
  var Plugin = HyperFormula.FunctionPlugin;
  var ArgType = HyperFormula.FunctionArgumentType;
  if (!Plugin || !ArgType) {
    console.error("xl-excel-rounding: this HyperFormula build does not expose FunctionPlugin; " +
                  "ROUNDUP/CEILING left as-is, so totals may read high.");
    return;
  }

  function snap(x) {
    var n = Number(x);
    if (!isFinite(n)) return n;
    return Number(n.toPrecision(12));
  }

  function ExcelRounding() { Plugin.apply(this, arguments); }
  ExcelRounding.prototype = Object.create(Plugin.prototype);
  ExcelRounding.prototype.constructor = ExcelRounding;

  ExcelRounding.prototype.roundup = function (ast, state) {
    var self = this;
    return this.runFunction(ast.args, state, this.metadata("ROUNDUP"), function (value, places) {
      var p = Math.trunc(places || 0);
      var f = Math.pow(10, p);
      // Snap twice: once on the incoming value, once after scaling. Scaling by a power of ten
      // reintroduces exactly the noise we are trying to remove.
      var s = snap(snap(value) * f);
      return (s >= 0 ? Math.ceil(s) : Math.floor(s)) / f;
    });
  };

  ExcelRounding.prototype.ceilingFn = function (ast, state) {
    return this.runFunction(ast.args, state, this.metadata("CEILING"), function (value, sig) {
      var s = (sig === undefined || sig === null) ? 1 : Number(sig);
      if (s === 0) return 0;                   // Excel returns 0, not an error
      return Math.ceil(snap(snap(value) / s)) * s;
    });
  };

  ExcelRounding.implementedFunctions = {
    ROUNDUP: {
      method: "roundup",
      parameters: [
        { argumentType: ArgType.NUMBER },
        { argumentType: ArgType.NUMBER, defaultValue: 0 },
      ],
    },
    CEILING: {
      method: "ceilingFn",
      parameters: [
        { argumentType: ArgType.NUMBER },
        { argumentType: ArgType.NUMBER, defaultValue: 1 },
      ],
    },
  };

  try {
    // The built-ins have to go first; registering a duplicate name is rejected.
    HyperFormula.unregisterFunction("ROUNDUP");
    HyperFormula.unregisterFunction("CEILING");
    HyperFormula.registerFunctionPlugin(ExcelRounding, {
      enGB: { ROUNDUP: "ROUNDUP", CEILING: "CEILING" },
    });
    window.TW_EXCEL_ROUNDING = true;          // asserted by the page tests
  } catch (e) {
    console.error("xl-excel-rounding: registration failed, totals may read high", e);
  }
})();
