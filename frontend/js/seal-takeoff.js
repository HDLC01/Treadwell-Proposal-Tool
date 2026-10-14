// The Seal tabs' takeoff, for Estimating Tool v2: what the Seal and Seal (+Jnts) sheets do BEFORE the markup chain
// and a library row cannot say. No DOM, no fetch, no clock. The Seal option is the smallest of the option tabs, and
// this file is the smallest of the takeoff leaves beside js/epoxy-takeoff.js and js/gyp-takeoff.js.
//
// WHAT THE LIBRARY SAYS, AND WHAT IT DOES NOT. The Seal sheet's material is a patch, two lines of sealer and, on
// Seal (+Jnts), a kit of joint filler for every 3,500 square feet. The sealer and the joint filler are ordinary
// library materials (an assembly of them prices exactly as the sheet does: the sealer is $0.15 a square foot a
// coat, the kit is the library's own `joint-filler-kit`), so the seed (backend/ops/seed_library_from_workbook.py)
// writes them as items and assemblies and this file does not touch them. Two things on the sheet are not that, and
// they are here:
//
//   1. THE PATCH. D17 charges a price a square foot of the whole area, always, and the price is
//      IF(B10="New", 0.05, 0.15): a new floor pays a third of a renovation. It is not a line the estimator picks.
//      The answer comes from the job (`ctx.reno`, which the page reads off the draft's Renovation cell), and both
//      prices are editable library rows.
//   2. THE TOOLING. D51: tooling and consumables at $0.27 a square foot with a $150 floor, ROUNDed UP. (The sheet's
//      demo tooling, slurry hardener and plastic are typed quantities the v2 model does not carry.)
//
// THE CONTRACT FOR WHAT IS HERE (docs/v2-architecture.md rule 3, the one Dye, Joint Filler and the Epoxy patch
// follow). The formulas are code. The PRICES they read are editable library rows, the ids in PRICE_ROWS, and the
// constant beside each id is only the FALLBACK for a database the seed has not reached. A test
// (backend/tests/test_seal_takeoff.py) holds every constant equal to the row the seed writes and equal to the cell
// of the template it was copied from.
//
// LAYER. A leaf above excel-math and library-core: it reads rows and prices, never a model.
(function (root, factory) {
  var isNode = typeof module !== "undefined" && module.exports;
  var deps = {
    math: isNode ? require("./excel-math.js") : root.TWExcelMath,
    lib: isNode ? require("./library-core.js") : root.TWLib
  };
  if (!deps.math) throw new Error("seal-takeoff.js needs excel-math.js loaded before it");
  if (!deps.lib) throw new Error("seal-takeoff.js needs library-core.js loaded before it");
  var api = factory(deps);
  root.TWSealTakeoff = api;
  if (isNode) module.exports = api;
})(typeof self !== "undefined" ? self : this, function (deps) {
  "use strict";

  var math = deps.math;
  var lib = deps.lib;
  var num = math.num;
  var roundUp = math.roundUp;

  // ── the price rows, and their fallbacks ───────────────────────────────────────
  /** The library rows the formulas below read their prices from. `fallback` is the cost of ONE square foot and is
   *  what stands when the row is not in the library or cannot say. `cell` is where the template holds it: both
   *  patch prices are the two branches of Seal!C17. */
  var PRICE_ROWS = {
    patchNew:  { id: "wb-seal-patch-new",  cell: "C17", fallback: 0.05 },
    patchReno: { id: "wb-seal-patch-reno", cell: "C17", fallback: 0.15 }
  };

  /** The price of one square foot of a price row: the library row's cost over its pack when it has one worth using,
   *  else the fallback. Answers { cost, from: "library" | "fallback" }. */
  function unitPrice(items, key) {
    var spec = PRICE_ROWS[key];
    if (!spec) throw new Error("seal-takeoff: " + key + " is not a price row");
    var row = lib.findItem(items, spec.id);
    var cost = row ? lib.num(row.unit_cost) : null;
    if (cost !== null && cost > 0) return { cost: cost / lib.buyQty(row), from: "library" };
    return { cost: spec.fallback, from: "fallback" };
  }

  // ── the tooling ───────────────────────────────────────────────────────────────
  /** Seal!D51 = ROUNDUP(IF(B51*C51 > 150, B51*C51, 150), 0), where B51 is the area and C51 is 0.27. */
  var TOOLING = { perSf: 0.27, min: 150 };

  /** The tooling a bid of `sf` square feet carries: 0 for no area (a bid for nothing has no tooling; the sheet
   *  charges its minimum even then, which is the one difference, written in docs/v2-architecture.md). */
  function toolingCost(sf) {
    var a = num(sf);
    if (!(a > 0)) return 0;
    var perSf = a * TOOLING.perSf;
    return roundUp(perSf > TOOLING.min ? perSf : TOOLING.min);
  }

  // ── the patch ─────────────────────────────────────────────────────────────────
  /** D17: the patch price times the whole area. `reno` is the job's Renovation answer (B10 reads "Reno"): the
   *  renovation price when it is true, the new-floor price otherwise. */
  function patchCost(items, sf, reno) {
    var a = num(sf);
    if (!(a > 0)) return 0;
    return a * unitPrice(items, reno ? "patchReno" : "patchNew").cost;
  }

  // ── the section's material ────────────────────────────────────────────────────
  var isOn = function (row) { return !(row && row.enabled === false); };

  /** The Seal section's material and tooling: its takeoff priced, the patch, and the tooling.
   *
   *  `ctx.rowPrice(row)` prices an ordinary row (the page's own, so a coverage typed on a bid and the section's
   *  pooled purchase still count) and answers what priceAssembly does or null. `ctx.items` is the library's
   *  materials, `ctx.sf` the area the bid prices (the page's takeoffSf) and `ctx.reno` the job's Renovation answer.
   *  Answers { material, tooling, patch } where `material` is the raw sum the chain rounds up (D31). */
  function sectionMaterial(takeoff, ctx) {
    var rows = takeoff instanceof Array ? takeoff : [];
    var items = (ctx && ctx.items) || [];
    var sum = 0;
    rows.forEach(function (r) {
      if (!r || !isOn(r)) return;
      var p = ctx.rowPrice(r);
      if (p) sum += p.total;
    });
    var patch = patchCost(items, ctx.sf, !!ctx.reno);
    return { material: sum + patch, tooling: toolingCost(ctx.sf), patch: patch };
  }

  // ── the starting takeoff ──────────────────────────────────────────────────────
  /** The assembly a NEW option opens with, by the sheet it is: both sheets ship with the two sealer lines filled in
   *  (Seal!D20 and D21, "Grind + Seal = 2 Coats"), and Seal (+Jnts) ships with the joint filler on (E29 = Yes). */
  var DEFAULT_ASSEMBLY = {
    "Seal": "wb-seal-2-coats",
    "Seal (+Jnts)": "wb-seal-jnts-2-coats"
  };

  /** The takeoff rows a new Seal option starts with: one row, the sheet's own default assembly over `sf` square
   *  feet. `asms` is the library's assemblies; null when the tab is not a Seal sheet or the library does not have
   *  the assembly (the seed writes it), so the page falls back to the ordinary default takeoff. */
  function seedTakeoff(tab, asms, sf) {
    var id = Object.prototype.hasOwnProperty.call(DEFAULT_ASSEMBLY, tab) ? DEFAULT_ASSEMBLY[tab] : null;
    if (!id) return null;
    var asm = (asms instanceof Array ? asms : []).filter(function (a) { return a && a.id === id; })[0];
    if (!asm) return null;
    var area = num(sf);
    return [{ assembly_id: asm.id, assembly_name: asm.name, measurement: area > 0 ? area : "", unit: "SF" }];
  }

  return {
    PRICE_ROWS: PRICE_ROWS, TOOLING: TOOLING, DEFAULT_ASSEMBLY: DEFAULT_ASSEMBLY,
    unitPrice: unitPrice, toolingCost: toolingCost, patchCost: patchCost,
    sectionMaterial: sectionMaterial, seedTakeoff: seedTakeoff
  };
});
