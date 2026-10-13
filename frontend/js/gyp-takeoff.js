// The Gyp tabs' takeoff, for Estimating Tool v2: what a Gyp sheet does BEFORE the markup chain, and the library
// cannot say. No DOM, no fetch, no clock.
//
// WHAT THE SHEET DOES (Gyp (USG 1-8")!B23:E36, and the same cells on the four other Gyp tabs). A Gyp job is three
// AREAS (soft surfaces, hard surfaces over a sound mat, corridors), each poured to its own thickness at one mix
// design. From those the sheet works out what the engine's gyp-split chain takes (gyp, extras, sand, soundMat, the sound
// mat's rolls and the tooling; js/bid-engine.js):
//
//   1. GYPSUM, `gyp`. Bags are `(SF / yield) * (1 + 3%)` and are NEVER rounded up (odd rule 7), so 1,000 SF of soft
//      surface is 25.75 bags and not 26. The yield of a bag depends on the thickness: a bag covers 240 SF of one
//      eighth of an inch (G15 = G14 * 6), so `240 / eighths`, where hard surfaces get 12 more (S52). A 3000 psi mix
//      (1.4) is `ROUND(240 / (eighths * 1.1764705915999), 0)`, a whole number of SF a bag.
//   2. EXTRAS, `extras`. Primer is `(soft + corridor) / 1200` gallons, ISO strip is `hard / (1200 * 1.8)` rolls (or
//      every area, when "ISO Strip at All Areas" is Yes), joint tape is `hard / 240` rolls. These are fractional too.
//      Anything else a takeoff row buys is an extra (the sheet's blank lines E30, E31 are priced like them).
//   3. SAND, `sand`. `(sand pounds a bag * ALL the fractional bags / 2000) * (1 + 10%)` tons, 180 pounds a bag at
//      1.8 and 140 at 1.4. It is worked out from the fractional bags, so it is not a whole number either.
//   4. TOOLING, the chain's `tooling`. E57 + E58: a moisture test is $35 a test and the number of tests is typed
//      (the sheet leaves it blank), and tooling and consumables are $0.04 a square foot of ALL the areas. Each is its
//      own ROUNDUP.
//   5. SOUND MAT, `soundMat` and `soundMatRolls`. `ROUNDUP(hard SF / SF per roll * (1 + 4%), 0)` rolls at the
//      product's price. The ROLLS matter beyond the price: the mat ships free once they reach a truckload (odd rule
//      6), and a truckload depends on the product on the first four tabs and is a typed 448 on Gyp (FR).
//
// FIVE TABS, FIVE PRESETS. The five Gyp tabs differ in a short list of things and a preset is exactly that list,
// keyed by the workbook tab id, which is also the id a v2 Gyp section is filed under (so a bid priced on Gyp (FR)
// is "Gyp (FR)" on the proposal, as it is in the spreadsheet). USG N12 1/8" ('Gyp (USG 1-8")') is the default.
// What a tab changes: the gypsum bag and its price (Levelrock 2500 at 14.08, or Treadstone FR25 at 14.65), the
// primer (USG 53 gallon drum or Treadstone TP1), the ISO strip (price and how far a roll goes), the sound mat it
// opens on and the catalogue it offers, the default thickness of each area (N25 pours 1 1/4" soft, 1" hard) and its
// truckload.
//
// THE CONTRACT FOR WHAT IS HERE (docs/v2-architecture.md rule 3, the one Dye, Joint Filler and the Epoxy cove
// follow). The formulas are code. The PRICES they read are editable library rows, the ids in each preset, and the
// number beside each id is only the FALLBACK for a database the seed has not reached. A test
// (backend/tests/test_gyp_takeoff.py) holds every fallback equal to the template cell it was copied from and to
// the row the seed writes, and every constant below equal to its cell.
//
// LAYER. A leaf above excel-math and library-core: it reads rows and prices, never a model.
(function (root, factory) {
  var isNode = typeof module !== "undefined" && module.exports;
  var deps = {
    math: isNode ? require("./excel-math.js") : root.TWExcelMath,
    lib: isNode ? require("./library-core.js") : root.TWLib
  };
  if (!deps.math) throw new Error("gyp-takeoff.js needs excel-math.js loaded before it");
  if (!deps.lib) throw new Error("gyp-takeoff.js needs library-core.js loaded before it");
  var api = factory(deps);
  root.TWGypTakeoff = api;
  if (isNode) module.exports = api;
})(typeof self !== "undefined" ? self : this, function (deps) {
  "use strict";

  var math = deps.math;
  var lib = deps.lib;
  var num = math.num;
  var roundUp = math.roundUp;
  var has = Object.prototype.hasOwnProperty;

  // ── the constants of the sheet, each pinned to its cell by a test ─────────────────────────────
  /** Gyp (USG 1-8")!G14 * 6 (G15): the SF one bag covers at an eighth of an inch. */
  var YIELD_PER_EIGHTH = 240;
  /** S52 and S54 read `G15 + 12`: a hard surface gets 12 more SF an eighth out of a bag. */
  var HARD_EXTRA = 12;
  /** R54:T54: `ROUND(yield / (eighths * 1.1764705915999), 0)`, the 3000 psi mix's yield. */
  var STRONG_MIX_FACTOR = 1.1764705915999;
  /** G18, G19, G20: gypsum waste, sand waste, sound mat waste. */
  var WASTE = { gyp: 0.03, sand: 0.1, soundMat: 0.04 };
  /** The mix design is typed in G11: 1.8 is 2500 psi, 1.4 is 3000+ psi (P52, P54). The pounds of sand a bag takes
   *  (Q52, Q54) go with it. */
  var MIXES = [{ mix: 1.8, label: "2500 psi (1.8)", sandLb: 180 }, { mix: 1.4, label: "3000+ psi (1.4)", sandLb: 140 }];
  /** B27 `(F23 + F25) / 1200`: a gallon of primer covers 1200 SF of soft surface and corridor. */
  var PRIMER_SF = 1200;
  /** B29 `F24 / 240`: a roll of joint tape per 240 SF of hard surface. */
  var TAPE_SF = 240;
  /** Sand is bought by the ton (B33 `/2000`). */
  var POUNDS_A_TON = 2000;
  /** C57 (a moisture test) and C58 (tooling and consumables a square foot of B58 `=B43`). */
  var TOOLING = { moistureTest: 35, consumablesPerSf: 0.04 };

  // ── the five presets ──────────────────────────────────────────────────────────────────────────
  var BASE_TAB = 'Gyp (USG 1-8")';

  /** A sound mat as the library holds it: its row, and what the sheet's own table says (price a roll, SF a roll),
   *  which is the fallback and what a test holds the row to. `truckload` is H36 for this product. */
  function mat(id, price, sf, truckload, cell) {
    return { id: id, price: price, sf: sf, truckload: truckload, cell: cell };
  }

  // The USG and GrassWorx table (O37:Q44 on the four tabs that carry it; the same on each). A truckload is a
  // function of the product (H36), and the tab that opens on a product has that product's truckload.
  var MATS_USG = [
    mat("wb-gyp-sound-mat-sam-n12-1-8in-roll",        237.12, 494, 280, "37"),
    mat("wb-gyp-sound-mat-sam-n25-1-4in-roll",        244.75, 445, 208, "38"),
    mat("wb-gyp-sound-mat-sam-n40-3-8in-roll",        214.5,  330, 208, "39"),
    mat("wb-gyp-sound-mat-sam-n12-ultra-3-16in-roll", 236.16, 369, 260, "40"),
    mat("wb-gyp-sound-mat-sc-190-1-8in-roll",         117,    300, 384, "42"),
    mat("wb-gyp-sound-mat-sc-250-1-4in-roll",         105,    250, 384, "43"),
    mat("wb-gyp-sound-mat-sc-50-hp-3-8in-roll",       73.2,   120, 384, "44")
  ];
  // Gyp (FR): the GrassWorx mats (N37:P39) and its own Treadstone ones (N42:P44); a truckload is a typed 448.
  var MATS_FR = [
    mat("wb-gyp-sound-mat-sc-190-1-8in-roll",              117,   300, 448, "37"),
    mat("wb-gyp-sound-mat-sc-250-1-4in-roll",              105,   250, 448, "38"),
    mat("wb-gyp-sound-mat-sc-50-hp-3-8in-roll",            73.2,  120, 448, "39"),
    mat("wb-gyp-sound-mat-treadstone-r1-1-8in-roll",       199.8, 370, 448, "42"),
    mat("wb-gyp-sound-mat-elite-1-4in-roll",               216,   400, 448, "43"),
    mat("wb-gyp-sound-mat-elite-duo-3-8in-roll",           299.5, 333, 448, "44")
  ];

  /** One priced row a preset reads: its library id, the figure the sheet holds for ONE unit (a gallon, a roll, a
   *  bag, a ton: the fallback), and the template cell it came from. */
  function row(id, fallback, cell) { return { id: id, fallback: fallback, cell: cell }; }

  // The ids come from backend/ops/seed_library_from_workbook.py, which a test holds them to.
  var USG_BAG = row("wb-gyp-levelrock-2500-bag", 14.08, "D23");
  var USG_PRIMER = row("wb-gyp-usg-primer-53-gallon-drum", 891 / 53, "D27");
  var USG_ISO = row("wb-gyp-iso-strip-3-inch-adhesive-roll", 48.75, "D28");
  var TAPE = row("wb-gyp-joint-tape-roll", 5.75, "D29");
  var SAND = row("wb-gyp-sand-per-ton", 35, "D33");

  function preset(extra) {
    return Object.assign({
      bag: USG_BAG, primer: USG_PRIMER, iso: USG_ISO, isoSf: 1200 * 1.8, tape: TAPE, sand: SAND,
      mats: MATS_USG, defaultMat: MATS_USG[0].id,
      // the default thickness of each area, G10, I10, K10 (K10 is `=G10` on four tabs and typed on Gyp (FR))
      thickness: { soft: 0.75, hard: 0.75, corridor: 0.75 },
      // K10 is `=G10` on four tabs: a corridor box left blank pours at the soft surface's thickness, typed or not
      corridorFollowsSoft: true
    }, extra);
  }

  /** The presets, by workbook tab id. `defaultMat` is what A36 opens on. */
  var PRESETS = {
    'Gyp (USG 1-8")': preset({}),
    "Gyp (USG N12ULTRA)": preset({ defaultMat: "wb-gyp-sound-mat-sam-n12-ultra-3-16in-roll" }),
    'Gyp (USG N25 1-4")': preset({ defaultMat: "wb-gyp-sound-mat-sam-n25-1-4in-roll",
                                   thickness: { soft: 1.25, hard: 1, corridor: 1.25 } }),
    "Gyp (GWorx SC190)": preset({ defaultMat: "wb-gyp-sound-mat-sc-190-1-8in-roll" }),
    "Gyp (FR)": preset({
      bag: row("wb-gyp-treadstone-fr25-bag", 14.65, "D23"),
      primer: row("wb-gyp-treadstone-primer-tp1-gallon", 27.9, "D27"),
      iso: row("wb-gyp-iso-strip-roll", 27, "D28"), isoSf: 1200,
      mats: MATS_FR, defaultMat: "wb-gyp-sound-mat-treadstone-r1-1-8in-roll",
      corridorFollowsSoft: false   // Gyp (FR)!K10 is a typed 0.75, not `=G10`
    })
  };

  var BUCKETS = ["soft", "hard", "corridor"];
  /** The three area rows of a takeoff, as library assemblies (backend/ops/seed_library_from_workbook.py). */
  var AREA_ASSEMBLIES = {
    soft: { id: "wb-gyp-area-soft", name: "Gypsum: soft surfaces", cell: "F23" },
    hard: { id: "wb-gyp-area-hard", name: "Gypsum: hard surfaces over the sound mat", cell: "F24" },
    corridor: { id: "wb-gyp-area-corridor", name: "Gypsum: corridors", cell: "F25" }
  };

  function presetOf(tab) {
    if (typeof tab !== "string" || !has.call(PRESETS, tab)) {
      throw new Error("gyp-takeoff: " + String(tab) + " is not a Gyp tab (" + Object.keys(PRESETS).join(", ") + ")");
    }
    return PRESETS[tab];
  }

  function isOn(r) { return !(r && r.enabled === false); }

  /** The area an assembly id names, "soft", "hard" or "corridor", or null for any other assembly. */
  function bucketOfAssembly(assemblyId) {
    for (var i = 0; i < BUCKETS.length; i++) if (AREA_ASSEMBLIES[BUCKETS[i]].id === assemblyId) return BUCKETS[i];
    return null;
  }

  /** The area a takeoff row belongs to: the `bucket` mark it carries, else the area its assembly names. */
  function bucketOfRow(r) {
    if (!r) return null;
    if (BUCKETS.indexOf(r.bucket) >= 0) return r.bucket;
    return bucketOfAssembly(r.assembly_id);
  }

  // ── the library's price of one unit ──────────────────────────────────────────────────────────
  /** The price of ONE unit of a preset row (a gallon, a roll, a bag, a ton): the library row's cost over its pack
   *  when it has one worth using, else the fallback. Answers { cost, from: "library" | "fallback" }. */
  function unitPrice(items, spec) {
    var r = lib.findItem(items, spec.id);
    var cost = r ? lib.num(r.unit_cost) : null;
    if (cost !== null && cost > 0) return { cost: cost / lib.buyQty(r), from: "library" };
    return { cost: spec.fallback, from: "fallback" };
  }

  function matList(tab) { return presetOf(tab).mats; }

  /** The sound mat a product id names on this tab, or null when the tab does not offer it. */
  function matSpec(tab, id) {
    var list = matList(tab);
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  /** What a sound mat is, as the library holds it and the sheet falls back to: { id, price (a roll), sf (a roll),
   *  truckload, from }. The row's own coverage and cost win when the library has them. */
  function matFigures(items, tab, id) {
    var spec = matSpec(tab, id);
    if (!spec) return null;
    var r = lib.findItem(items, id);
    var cost = r ? lib.num(r.unit_cost) : null;
    var cov = r ? lib.num(r.coverage) : null;
    var fromLib = cost !== null && cost > 0 && cov !== null && cov > 0;
    return {
      id: id, price: fromLib ? cost / lib.buyQty(r) : spec.price, sf: fromLib ? cov : spec.sf,
      truckload: spec.truckload, from: fromLib ? "library" : "fallback"
    };
  }

  // ── what an estimator typed, read against the preset ─────────────────────────────────────────
  /** The mix a section holds: 1.8 unless it says 1.4. */
  function mixOf(settings) {
    var m = num(settings && settings.mix);
    return m === 1.4 ? 1.4 : 1.8;
  }

  /** The thickness of one area, in inches: what was typed, else the preset's own. A box that is blank falls back to
   *  the preset, exactly as a coverage box falls back to the library. 0 and negatives are not a thickness.
   *  The one exception is the corridor on a tab whose K10 reads `=G10`: blank there is the SOFT surface's thickness
   *  (typed, else the preset's), because that is what the workbook pours. */
  function thicknessOf(tab, settings, bucket) {
    var typed = settings && settings.thickness ? settings.thickness[bucket] : undefined;
    var blank = (typed === undefined || typed === null || typed === "");
    if (blank && bucket === "corridor" && presetOf(tab).corridorFollowsSoft) return thicknessOf(tab, settings, "soft");
    var t = blank ? presetOf(tab).thickness[bucket] : num(typed);
    return t > 0 ? t : null;
  }

  /** The sound mat a section is priced with: the one it holds if the tab offers it, else the tab's own. */
  function matIdOf(tab, settings) {
    var held = settings && settings.sound_mat;
    return (held && matSpec(tab, held)) ? held : presetOf(tab).defaultMat;
  }

  /** Excel's ROUND(n, 0): half away from zero, on a value snapped to twelve significant figures as roundUp is. */
  function xlRound(n) {
    var g = parseFloat(num(n).toPrecision(12));
    return g >= 0 ? Math.floor(g + 0.5) : -Math.floor(-g + 0.5);
  }

  // ── the bags ─────────────────────────────────────────────────────────────────────────────────
  /** SF a bag covers in one area: `240 / eighths` (hard: `252 / eighths`) at a 2500 psi mix, and the sheet's own
   *  ROUND(... / (eighths * 1.1764705915999)) at 3000+ psi. null when the thickness is not usable (the sheet divides
   *  by zero there) or the 3000 psi yield rounds to nothing. */
  function yieldPerBag(bucket, thickness, mix) {
    var eighths = num(thickness) * 8;
    if (!(eighths > 0)) return null;
    var base = YIELD_PER_EIGHTH + (bucket === "hard" ? HARD_EXTRA : 0);
    var y = mix === 1.4 ? xlRound(base / (eighths * STRONG_MIX_FACTOR)) : base / eighths;
    return y > 0 ? y : null;
  }

  /** The bags one area takes, with waste and NOT rounded up (odd rule 7). */
  function bagsFor(sf, yieldBag) {
    return (num(sf) / yieldBag) * (1 + WASTE.gyp);
  }

  // ── the section's areas, and its figures ─────────────────────────────────────────────────────
  /** The square feet of each area: the rows that are on, by the area they name. Rows of no area are the extras'. */
  function areasOf(takeoff) {
    var out = { soft: 0, hard: 0, corridor: 0 };
    (takeoff instanceof Array ? takeoff : []).forEach(function (r) {
      var b = bucketOfRow(r);
      if (!b || !isOn(r) || r.unit === "LF") return;
      var sf = num(r.measurement);
      // A negative figure is a slip, not an area. The area is named by an explicit branch (never `out[name] +=`), because
      // the row's mark came out of a saved draft.
      if (!(sf > 0)) return;
      if (b === "soft") out.soft += sf;
      else if (b === "hard") out.hard += sf;
      else out.corridor += sf;
    });
    return out;
  }

  /** Everything the Gyp sheet works out from a takeoff and the section's settings, for the preset `tab`:
   *    { areas, bags: {soft, hard, corridor, total}, tons, rolls, truckload, mat, parts, problem }
   *  `problem` is plain words when an area that has square feet cannot be priced (no usable thickness), and then
   *  nothing is priced from it (the caller says no price, never a wrong one). `parts` are the dollar figures the
   *  chain takes: { gyp, primer, iso, tape, sand, soundMat }. */
  /** E57 + E58: `ROUNDUP(tests * 35, 0) + ROUNDUP(SF * 0.04, 0)`, where the SF is every area (B43 is `=F22`). */
  function toolingCost(sf, tests) {
    return roundUp(num(tests) * TOOLING.moistureTest) + roundUp(num(sf) * TOOLING.consumablesPerSf);
  }

  function figures(takeoff, settings, tab, items) {
    var p = presetOf(tab);
    var areas = areasOf(takeoff);
    var mix = mixOf(settings);
    var bags = { soft: 0, hard: 0, corridor: 0, total: 0 };
    var problem = null;
    BUCKETS.forEach(function (b) {
      if (!(areas[b] > 0)) return;
      var t = thicknessOf(tab, settings, b);
      var y = t === null ? null : yieldPerBag(b, t, mix);
      if (y === null) {
        if (!problem) problem = "the " + (b === "corridor" ? "corridor" : b + " surface") + " area has no usable thickness";
        return;
      }
      bags[b] = bagsFor(areas[b], y);
    });
    bags.total = bags.soft + bags.hard + bags.corridor;

    var isoAll = !!(settings && settings.iso_all);
    var primerGal = (areas.soft + areas.corridor) / PRIMER_SF;
    var isoRolls = (isoAll ? areas.soft + areas.hard + areas.corridor : areas.hard) / p.isoSf;
    var tapeRolls = areas.hard / TAPE_SF;
    var sandLb = MIXES.filter(function (m) { return m.mix === mix; })[0].sandLb;
    var tons = ((sandLb * bags.total) / POUNDS_A_TON) * (1 + WASTE.sand);

    var matId = matIdOf(tab, settings);
    var m = matFigures(items, tab, matId);
    var rolls = areas.hard > 0 ? roundUp((areas.hard / m.sf) * (1 + WASTE.soundMat)) : 0;

    var parts = {
      gyp: bags.total * unitPrice(items, p.bag).cost,
      primer: primerGal * unitPrice(items, p.primer).cost,
      iso: isoRolls * unitPrice(items, p.iso).cost,
      tape: tapeRolls * unitPrice(items, p.tape).cost,
      sand: tons * unitPrice(items, p.sand).cost,
      soundMat: rolls * m.price
    };
    var tooling = toolingCost(areas.soft + areas.hard + areas.corridor, settings && settings.moisture_tests);
    return { areas: areas, bags: bags, primerGal: primerGal, isoRolls: isoRolls, tapeRolls: tapeRolls, tons: tons,
             rolls: rolls, truckload: m.truckload, mat: m, parts: parts, tooling: tooling, problem: problem };
  }

  // ── one area row, shaped like the library's own priced row ───────────────────────────────────
  /** An area row priced, in the shape priceAssembly answers (rows, total, priced_lines, broken_lines, per_unit) so
   *  every caller that reads a row's price keeps working. It is the GYPSUM of that area at its thickness; the
   *  primer, tape, sand and sound mat are the section's (they depend on more than one row) and are listed under
   *  the takeoff. A row with no area, or an area with no usable thickness, prices no lines, not zero. */
  function priceAreaRow(assemblyId, sf, ctx) {
    var bucket = bucketOfAssembly(assemblyId);
    if (!bucket) throw new Error("gyp-takeoff: " + assemblyId + " is not a Gyp area assembly");
    var empty = { rows: [], total: 0, per_unit: null, priced_lines: 0, broken_lines: 0, area: true };
    var area = num(sf);
    if (!(area > 0)) return empty;
    var tab = ctx.tab, items = (ctx && ctx.items) || [];
    var t = thicknessOf(tab, ctx.settings, bucket);
    var y = t === null ? null : yieldPerBag(bucket, t, mixOf(ctx.settings));
    if (y === null) return Object.assign({}, empty, { broken_lines: 1 });
    var bags = bagsFor(area, y);
    var cost = bags * unitPrice(items, presetOf(tab).bag).cost;
    return {
      rows: [{ ok: true, priced: true, role: "Gypsum bags", qty: bags, cost: cost }],
      total: cost, per_unit: cost / area, priced_lines: 1, broken_lines: 0, area: true
    };
  }

  // ── the section's material, as the engine takes it ───────────────────────────────────────────
  /** The Gyp section's material, split the way the chain wants it: { gyp, extras, sand, soundMat, soundMatRolls,
   *  truckload, tooling } (the engine's gyp-split inputs, and the tooling line) and `unpriceable` in plain words when an area cannot be worked out.
   *
   *  `tab` is the section's workbook tab id (its preset), `settings` the section's `gyp` block, `ctx.items` the
   *  library's materials and `ctx.rowPrice(row)` prices a row that is NOT an area (the page's own, so a coverage
   *  typed on a bid still counts) and answers what priceAssembly does or null. Those rows are EXTRAS: they take the
   *  extras' 8% escalation and 10% shipping, like the sheet's blank lines E30 and E31. */
  function sectionMaterial(takeoff, settings, tab, ctx) {
    var rows = takeoff instanceof Array ? takeoff : [];
    var items = (ctx && ctx.items) || [];
    var f = figures(rows, settings, tab, items);
    var other = 0;
    rows.forEach(function (r) {
      if (!r || !isOn(r) || bucketOfRow(r)) return;
      var p = ctx && typeof ctx.rowPrice === "function" ? ctx.rowPrice(r) : null;
      if (p) other += p.total;
    });
    var out = {
      gyp: f.parts.gyp, extras: f.parts.primer + f.parts.iso + f.parts.tape + other, sand: f.parts.sand,
      soundMat: f.parts.soundMat, soundMatRolls: f.rolls, truckload: f.truckload, tooling: f.tooling,
      parts: f.parts, figures: f
    };
    if (f.problem) out.unpriceable = f.problem;
    return out;
  }

  // ── the sheet's own labor hours, for the page to quote ───────────────────────────────────────
  /** What the sheet works the labor hours out to (Gyp (USG 1-8")!B45:B51), so the estimator can see the figure the
   *  workbook would have, beside the hours they type. Crews are A45:A49 and A51; `mobs` is the mobilizations
   *  (T28, a typed input), `miles` the distance (B6). Pre-pour hours are typed on the sheet and so here. */
  var CREWS = { prePour: 8, prep: 8, mat: 7, pour: 8, unload: 2, travel: 8 };
  var HOURS = { prepPerMob: 4, matSfPerHour: 595, poursPerHour: 75, unloadPerMob: 2, mph: 60 };

  function sheetHours(f, mobs, miles) {
    var m = num(mobs);
    return {
      prePour: null,
      prep: m * HOURS.prepPerMob,
      mat: f.areas.hard / HOURS.matSfPerHour,
      pour: f.bags.total / HOURS.poursPerHour,
      unload: m * HOURS.unloadPerMob,
      travel: ((num(miles) * 2) / HOURS.mph) * m
    };
  }

  // ── seeding the takeoff from the intake ──────────────────────────────────────────────────────
  /** The takeoff rows a new Gyp bid starts with, from the intake's three area boxes: one row for each area that
   *  has square feet, as the library's area assemblies. `asms` is the library's assemblies; an area assembly the
   *  library does not have is left out (the seed writes them). [] when nothing was typed. */
  function seedTakeoff(asms, soft, hard, corridor) {
    var typed = { soft: soft, hard: hard, corridor: corridor };
    var rows = [];
    BUCKETS.forEach(function (b) {
      var sf = num(typed[b]);
      if (!(sf > 0)) return;
      var asm = (asms instanceof Array ? asms : []).filter(function (a) { return a && a.id === AREA_ASSEMBLIES[b].id; })[0];
      if (!asm) return;
      rows.push({ assembly_id: asm.id, assembly_name: asm.name, measurement: sf, unit: "SF", bucket: b });
    });
    return rows;
  }

  return {
    PRESETS: PRESETS, BASE_TAB: BASE_TAB, BUCKETS: BUCKETS, AREA_ASSEMBLIES: AREA_ASSEMBLIES, MIXES: MIXES,
    YIELD_PER_EIGHTH: YIELD_PER_EIGHTH, HARD_EXTRA: HARD_EXTRA, STRONG_MIX_FACTOR: STRONG_MIX_FACTOR,
    WASTE: WASTE, PRIMER_SF: PRIMER_SF, TAPE_SF: TAPE_SF, POUNDS_A_TON: POUNDS_A_TON, TOOLING: TOOLING,
    CREWS: CREWS, HOURS: HOURS, toolingCost: toolingCost,
    presetOf: presetOf, tabs: function () { return Object.keys(PRESETS); },
    bucketOfAssembly: bucketOfAssembly, bucketOfRow: bucketOfRow, areasOf: areasOf,
    unitPrice: unitPrice, matList: matList, matSpec: matSpec, matFigures: matFigures,
    mixOf: mixOf, thicknessOf: thicknessOf, matIdOf: matIdOf, xlRound: xlRound,
    yieldPerBag: yieldPerBag, bagsFor: bagsFor, figures: figures, priceAreaRow: priceAreaRow,
    sectionMaterial: sectionMaterial, sheetHours: sheetHours, seedTakeoff: seedTakeoff
  };
});
