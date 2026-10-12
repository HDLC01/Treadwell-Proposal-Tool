// The Epoxy tab's takeoff, for Estimating Tool v2: what the Epoxy sheet does BEFORE the markup chain, and
// the library cannot say. No DOM, no fetch, no clock.
//
// WHAT THE LIBRARY SAYS, AND WHAT IT DOES NOT. Almost all of the Epoxy material section is a list of
// products bought by coverage (`ROUNDUP(sf / coverage, 0)` of a kit, `CEILING(sf * lb per sf, 40)` pounds of
// flake), and that is exactly what an assembly of library materials prices (js/library-core.js), so the
// seed (backend/ops/seed_library_from_workbook.py) writes those as items and assemblies and this file does
// not touch them. Four things on the sheet are not that, and they are here:
//
//   1. THE PATCH. D18 and D19 charge $0.10 a square foot of the whole epoxy area, always, whatever the
//      system. It is not a line the estimator picks.
//   2. THE COVE. It rounds twice (gallons = ROUNDUP(lf / 30), then ROUNDUP(gallons / 8) + ROUNDUP(gallons / 4)
//      units of resin), and its aggregate is bought in 50 pound lots from the gallon count, not from the
//      length. Six sizes of epoxy cove and six of WR (urethane) cove, each with its own divisors.
//   3. THE COVE AGGREGATE FOLLOWS SYSTEM 1 (Kyle's odd rule 11, docs/kyle-workbook-odd-rules.md). The cove
//      aggregate is quartz when System 1 is one of the three quartz systems and silica otherwise, in the
//      System 1 cove and in the System 2 cove alike (the System 2 blocks read `$A$22`, System 1's choice).
//      It reproduces it on purpose.
//   4. THE TOOLING. D58 to D62: a moisture test, and tooling and consumables at $0.33 a square foot with a
//      $150 floor. (Demo tooling and plastic are typed quantities the v2 model does not carry.)
//
// THE CONTRACT FOR WHAT IS HERE (docs/v2-architecture.md rule 3, the one Dye and Joint Filler follow). The
// formulas are code. The PRICES they read are editable library rows, the ids in PRICE_ROWS, and the
// constant beside each id is only the FALLBACK for a database the seed has not reached. A test
// (backend/tests/test_epoxy_takeoff.py) holds every constant equal to the row the seed writes and every
// divisor in COVE and TOOLING equal to the cell of the template it was copied from.
//
// LAYER. A leaf above excel-math and library-core: it reads rows and prices, never a model.
(function (root, factory) {
  var isNode = typeof module !== "undefined" && module.exports;
  var deps = {
    math: isNode ? require("./excel-math.js") : root.TWExcelMath,
    lib: isNode ? require("./library-core.js") : root.TWLib
  };
  if (!deps.math) throw new Error("epoxy-takeoff.js needs excel-math.js loaded before it");
  if (!deps.lib) throw new Error("epoxy-takeoff.js needs library-core.js loaded before it");
  var api = factory(deps);
  root.TWEpoxyTakeoff = api;
  if (isNode) module.exports = api;
})(typeof self !== "undefined" ? self : this, function (deps) {
  "use strict";

  var math = deps.math;
  var lib = deps.lib;
  var num = math.num;
  var roundUp = math.roundUp;
  var ceiling = math.ceiling;

  // ── the price rows, and their fallbacks ───────────────────────────────────────
  /** The library rows the formulas below read their prices from. `fallback` is the cost of ONE unit (one
   *  gallon, one SF, one pound) and is what stands when the row is not in the library or cannot say. Each is
   *  the figure of the template's cell at the seed, to the four places a library cost has. */
  var PRICE_ROWS = {
    patch:    { id: "wb-epoxy-patch",         cell: "C18",  fallback: 0.1 },
    coveRez:  { id: "wb-epoxy-cove-rez",      cell: "T152", fallback: 88.8308 },
    coveWr:   { id: "wb-epoxy-cove-wr",       cell: "T167", fallback: 66.6952 },
    silica:   { id: "wb-epoxy-cove-silica",   cell: "W145", fallback: 0.44 },
    q28:      { id: "wb-epoxy-cove-q28",      cell: "W148", fallback: 0.47 },
    zincCap:  { id: "wb-epoxy-cove-zinc-cap", cell: "W150", fallback: 0.75 }
  };

  /** The price of one unit of a price row: the library row's cost over its pack when it has one worth
   *  using, else the fallback. Answers { cost, from: "library" | "fallback" }. */
  function unitPrice(items, key) {
    var spec = PRICE_ROWS[key];
    if (!spec) throw new Error("epoxy-takeoff: " + key + " is not a price row");
    var row = lib.findItem(items, spec.id);
    var cost = row ? lib.num(row.unit_cost) : null;
    if (cost !== null && cost > 0) return { cost: cost / lib.buyQty(row), from: "library" };
    return { cost: spec.fallback, from: "fallback" };
  }

  // ── the cove ──────────────────────────────────────────────────────────────────
  // One entry per cove assembly the seed writes (Cove 1 Options, Epoxy!S125 to S136). `per` is how far a unit
  // goes: linear feet a gallon covers for an epoxy cove (C125, C130, C135, C141, `(21/2)` in C147, `(13/2)` in
  // C152), linear feet a kit covers for a WR cove (M125, M130, M135, M141, `35/2` in M147, `26/2` in M152).
  // `lbs` is the pounds of aggregate bought for each gallon (C126, C131, C136, C142, C148, C153), and `cap` is
  // whether a zinc cap rides with it (the "+ Cap" options).
  var COVE = {
    "wb-epoxy-cove-epoxy-4in":          { kind: "epoxy", per: 30,   lbs: 25, cap: false },
    "wb-epoxy-cove-epoxy-6in":          { kind: "epoxy", per: 20,   lbs: 25, cap: false },
    "wb-epoxy-cove-epoxy-4in-plus-cap": { kind: "epoxy", per: 15,   lbs: 25, cap: true },
    "wb-epoxy-cove-epoxy-6in-plus-cap": { kind: "epoxy", per: 10,   lbs: 25, cap: true },
    "wb-epoxy-cove-epoxy-8in":          { kind: "epoxy", per: 10.5, lbs: 20, cap: false },
    "wb-epoxy-cove-epoxy-8in-plus-cap": { kind: "epoxy", per: 6.5,  lbs: 21, cap: true },
    "wb-epoxy-cove-wr-4in":             { kind: "wr", per: 35,   cap: false },
    "wb-epoxy-cove-wr-6in":             { kind: "wr", per: 25,   cap: false },
    "wb-epoxy-cove-wr-4in-plus-cap":    { kind: "wr", per: 26,   cap: true },
    "wb-epoxy-cove-wr-6in-plus-cap":    { kind: "wr", per: 18,   cap: true },
    "wb-epoxy-cove-wr-8in":             { kind: "wr", per: 17.5, cap: false },
    "wb-epoxy-cove-wr-8in-plus-cap":    { kind: "wr", per: 13,   cap: true }
  };

  /** Zinc cap comes in 8 foot sticks (E137: `CEILING(lf * 1, 8)`) at 0.75 a foot. */
  var CAP_STICK_LF = 8;
  /** Aggregate comes in 50 pound bags (E126: `CEILING(gallons * lbs, 50)`). */
  var AGGREGATE_BAG_LB = 50;

  /** The cove variant an assembly id names, or null (an ordinary assembly). */
  function coveVariant(assemblyId) {
    return Object.prototype.hasOwnProperty.call(COVE, assemblyId) ? COVE[assemblyId] : null;
  }

  /** One cove, from its length: the lines a sheet block prices and what they come to. `quartz` is whether the
   *  aggregate is priced as quartz (System 1 is a quartz system), `prices` the unit price of each price row
   *  ({ coveRez, coveWr, silica, q28, zincCap }). Every ROUNDUP and CEILING is the sheet's, in the sheet's
   *  order: the length goes to gallons, the gallons to resin units, the gallons to pounds of aggregate. */
  function coveCost(variant, lf, quartz, prices) {
    var len = num(lf);
    var lines = [];
    if (!(len > 0)) return { total: 0, lines: lines };
    var total = 0;
    if (variant.kind === "epoxy") {
      var gallons = roundUp(len / variant.per);
      var units = roundUp(gallons / 8) + roundUp(gallons / 4);
      var resin = units * prices.coveRez;
      lines.push({ role: "Cove liquids", qty: units, cost: resin });
      var lbs = ceiling(gallons * variant.lbs, AGGREGATE_BAG_LB);
      var agg = lbs * (quartz ? prices.q28 : prices.silica);
      lines.push({ role: "Aggregate", qty: lbs, cost: agg });
      total = resin + agg;
    } else {
      var kits = roundUp(len / variant.per);
      var wr = kits * prices.coveWr;
      lines.push({ role: "Cove liquids", qty: kits, cost: wr });
      total = wr;
    }
    if (variant.cap) {
      var feet = ceiling(len, CAP_STICK_LF);
      var cap = feet * prices.zincCap;
      lines.push({ role: "Cap", qty: feet, cost: cap });
      total += cap;
    }
    return { total: total, lines: lines };
  }

  // ── System 1 ──────────────────────────────────────────────────────────────────
  var SYSTEM_PREFIX = "wb-epoxy-sys-";
  var WALL_PREFIX = "wb-epoxy-sys-walls-";
  /** The three systems Epoxy!A22 is compared with in every cove aggregate (`$R$189`, `$R$190`, `$R$191`). */
  var QUARTZ_SYSTEMS = [
    "wb-epoxy-sys-40-s-q28-quartz-double-broadcast",
    "wb-epoxy-sys-hybrid-quartz-double-broadcast-standard-texture",
    "wb-epoxy-sys-trowel-hybrid-quartz-double-broadcast-orange-peel-texture-trowel-texture"
  ];

  function isOn(row) { return !(row && row.enabled === false); }

  /** Is System 1 a quartz system? System 1 is the first row of the takeoff that is on and is one of the
   *  seeded floor systems (a wall system is never System 1, and an assembly Kyle composed himself is not
   *  recognised, so it reads as no quartz, which is the sheet's own "anything else"). */
  function systemOneIsQuartz(takeoff) {
    var rows = takeoff instanceof Array ? takeoff : [];
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var id = r && r.assembly_id;
      if (!r || !isOn(r) || typeof id !== "string") continue;
      if (id.indexOf(SYSTEM_PREFIX) !== 0 || id.indexOf(WALL_PREFIX) === 0) continue;
      return QUARTZ_SYSTEMS.indexOf(id) >= 0;
    }
    return false;
  }

  // ── the tooling ───────────────────────────────────────────────────────────────
  /** Epoxy!D58 to D62. `moisture` is B58 (`ROUNDUP(IF(B45>2000, B45/1000, 2), 0)` tests) at C58, and
   *  `consumables` is D59 (`ROUNDUP(IF(B59*C59>150, B59*C59, 150), 0)`, B59 = the area, C59 = 0.33). */
  var TOOLING = { moistureCost: 35, moistureMinTests: 2, moistureEverySf: 1000, moistureAfterSf: 2000,
                  consumablesPerSf: 0.33, consumablesMin: 150 };

  /** The tooling a bid of `sf` square feet carries: 0 for no area (a bid for nothing has no tooling; the sheet
   *  charges its minimums even then, which is the one difference, written in docs/v2-architecture.md). */
  function toolingCost(sf) {
    var a = num(sf);
    if (!(a > 0)) return 0;
    var tests = roundUp(a > TOOLING.moistureAfterSf ? a / TOOLING.moistureEverySf : TOOLING.moistureMinTests);
    var moisture = roundUp(tests * TOOLING.moistureCost);
    var perSf = a * TOOLING.consumablesPerSf;
    var consumables = roundUp(perSf > TOOLING.consumablesMin ? perSf : TOOLING.consumablesMin);
    return moisture + consumables;
  }

  // ── the patch ─────────────────────────────────────────────────────────────────
  /** D18 + D19: the patch price times the whole epoxy area, from the library row when it is there. */
  function patchCost(items, sf) {
    var a = num(sf);
    if (!(a > 0)) return 0;
    return a * unitPrice(items, "patch").cost;
  }

  // ── one cove row, shaped like the library's own priced row ────────────────────
  function pricesOf(items) {
    return {
      coveRez: unitPrice(items, "coveRez").cost, coveWr: unitPrice(items, "coveWr").cost,
      silica: unitPrice(items, "silica").cost, q28: unitPrice(items, "q28").cost,
      zincCap: unitPrice(items, "zincCap").cost
    };
  }

  /** A cove takeoff row priced, in the shape priceAssembly answers (rows, total, priced_lines, broken_lines,
   *  per_unit) so every caller that reads a row's price keeps working. A cove with no length yet prices no
   *  lines, not zero. */
  function priceCoveRow(assemblyId, lf, ctx) {
    var variant = coveVariant(assemblyId);
    if (!variant) throw new Error("epoxy-takeoff: " + assemblyId + " is not a cove assembly");
    var items = (ctx && ctx.items) || [];
    var len = num(lf);
    if (!(len > 0)) return { rows: [], total: 0, per_unit: null, priced_lines: 0, broken_lines: 0, cove: true };
    var r = coveCost(variant, len, !!(ctx && ctx.quartz), pricesOf(items));
    return {
      rows: r.lines.map(function (l) { return { ok: true, priced: true, role: l.role, qty: l.qty, cost: l.cost }; }),
      total: r.total, per_unit: r.total / len, priced_lines: r.lines.length, broken_lines: 0, cove: true
    };
  }

  /** THE COVE, BOUGHT ONCE FOR THE SECTION (the cove half of library-core's pricePool, which cannot do it: a cove row
   *  has no library item). `results[i]` is what takeoff row `rows[i]` priced to (priceCoveRow's answer for a cove row,
   *  anything else for the rest); the answer is a new array of the same length. Every cove assembly that sits on
   *  two or more ON rows is priced ONCE at the lengths ADDED TOGETHER (the sheet's two ROUNDUPs happen on the whole
   *  length, as they do for one cove of that length), and each line of that cove (liquids, aggregate, cap) goes back to
   *  the rows in proportion to their length, in whole ten-thousandths (library-core allocate), so the rows add up to
   *  the pooled cove exactly. A cove on one row, an OFF row, a row with no length and every other row come back as the
   *  very object they went in as. `ctx` is `{ items, quartz, on }` (`on[i] === false` leaves row i out). */
  function poolCoves(results, rows, ctx) {
    var out = results.slice();
    var items = (ctx && ctx.items) || [];
    var quartz = !!(ctx && ctx.quartz);
    var groups = new Map();
    results.forEach(function (res, i) {
      var r = rows[i];
      if (!res || !res.cove || !r || r.item_id || typeof r.assembly_id !== "string" || !coveVariant(r.assembly_id)) return;
      if (ctx && ctx.on && ctx.on[i] === false) return;
      var lf = num(r.measurement);
      if (!(lf > 0)) return;
      var key = r.assembly_id;                      // one purchase per cove assembly
      var g = groups.get(key);
      if (!g) { g = { id: r.assembly_id, list: [] }; groups.set(key, g); }
      g.list.push({ i: i, lf: lf });
    });
    groups.forEach(function (g) {
      var list = g.list;
      if (list.length < 2) return;
      var lf = list.reduce(function (t, l) { return t + l.lf; }, 0);
      var whole = priceCoveRow(g.id, lf, { items: items, quartz: quartz });
      var weights = list.map(function (l) { return l.lf; });
      var split = whole.rows.map(function (line) { return lib.allocate(line.cost, weights); });
      list.forEach(function (l, k) {
        var share = l.lf / lf, total = 0;
        var lines = whole.rows.map(function (line, j) {
          total += split[j][k];
          return { ok: true, priced: true, role: line.role, qty: line.qty * share, cost: split[j][k] };
        });
        out[l.i] = { rows: lines, total: total, per_unit: total / l.lf, priced_lines: lines.length, broken_lines: 0, cove: true,
                     pooled: { lines: list.length, lf: lf, cost: whole.total, share: share } };
      });
    });
    return out;
  }

  // ── the section's material ────────────────────────────────────────────────────
  /** The Epoxy section's material and tooling: its takeoff priced, the patch, and the tooling.
   *
   *  `ctx.rowPrice(row)` prices an ordinary row (the page's own, so a coverage typed on a bid still counts) and
   *  answers what priceAssembly does or null; a cove row is priced HERE, because the library cannot. `ctx.items`
   *  is the library's materials, `ctx.sf` the area the bid prices (the page's takeoffSf). Answers
   *  { material, tooling, patch, cove, rows } where `material` is the raw sum the chain rounds up (D40).
   *
   *  `ctx.pool` BUYS EACH MATERIAL ONCE FOR THE WHOLE SECTION (library-core's pricePool): the rows that are on are
   *  priced first (a cove by its own formula, an ordinary row by `ctx.rowPrice`, which must then answer each row
   *  ALONE), and the pool then adds up what the rows buy of the same material. A cove is pooled the same way by
   *  `poolCoves` (the same cove on two areas is one length), since the library's pool has no item to add up.
   *  `ctx.poolCoves` alone pools just the cove.
   *  `ctx.skip` are item ids never pooled (pricePool's). A caller whose `ctx.rowPrice` already answers pooled
   *  figures (the estimate page's does) does not set `pool`. */
  function sectionMaterial(takeoff, ctx) {
    var rows = takeoff instanceof Array ? takeoff : [];
    var items = (ctx && ctx.items) || [];
    var quartz = systemOneIsQuartz(rows);
    var sum = 0, cove = 0;
    var priced = rows.map(function (r) {
      if (!r || !isOn(r)) return null;
      var id = r.assembly_id;
      return coveVariant(id) ? priceCoveRow(id, r.measurement, { items: items, quartz: quartz })
                             : ctx.rowPrice(r);
    });
    var on = rows.map(function (r) { return !!r && isOn(r); });
    if (ctx && ctx.pool) priced = lib.pricePool(priced, { on: on, skip: ctx.skip });
    // `ctx.poolCoves` pools only the cove (a caller whose `ctx.rowPrice` already answers pooled figures for the
    // ordinary rows, as the estimate page's does, still has its cove priced HERE, so it must be pooled here too)
    if (ctx && (ctx.pool || ctx.poolCoves)) priced = poolCoves(priced, rows, { items: items, quartz: quartz, on: on });
    priced.forEach(function (p) {
      if (!p) return;
      sum += p.total;
      if (p.cove) cove += p.total;
    });
    var patch = patchCost(items, ctx.sf);
    return { material: sum + patch, tooling: toolingCost(ctx.sf), patch: patch, cove: cove };
  }

  return {
    PRICE_ROWS: PRICE_ROWS, COVE: COVE, QUARTZ_SYSTEMS: QUARTZ_SYSTEMS, TOOLING: TOOLING,
    SYSTEM_PREFIX: SYSTEM_PREFIX, WALL_PREFIX: WALL_PREFIX,
    CAP_STICK_LF: CAP_STICK_LF, AGGREGATE_BAG_LB: AGGREGATE_BAG_LB,
    unitPrice: unitPrice, coveVariant: coveVariant, coveCost: coveCost, priceCoveRow: priceCoveRow, poolCoves: poolCoves,
    systemOneIsQuartz: systemOneIsQuartz, toolingCost: toolingCost, patchCost: patchCost,
    sectionMaterial: sectionMaterial
  };
});
