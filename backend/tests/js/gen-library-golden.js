"use strict";
/* LIBRARY PRICING, RECORDED. The recipe behind backend/tests/fixtures/library_pricing_golden.json.
 *
 * js/library-core.js is the arithmetic every material in the product goes through: a line points at
 * a material, one measured area drives it, and the answer is a number of packs and a cost. Phase 11
 * of the v2 estimating program gives materials three new columns (price breaks, a bulk cost, a
 * coverage basis) and Phase 12 prices Epoxy off them. Every bid already saved, and every Polish bid
 * still to come, prices through priceLine and priceAssembly as they are today, so this records what
 * they answer now, for a few hundred deliberately awkward inputs, before anything moves. See
 * _golden.js for how a golden is made and compared, and gen-chain-golden.js for the sibling that
 * records the Polish bid chain.
 *
 * THE INPUTS are fixed tables and loops (no random numbers), built around one baseline material
 * and varied ONE FIELD AT A TIME, then across the combinations that interact:
 *
 *   * WASTE: absent (a row older than the column, which reads as 5%), null, 0, 5, 7.5, 10, 100,
 *     past 100 (clamped), negative (reads as 5%), and text.
 *   * ROUNDUP: absent (reads as yes), null, true, false, 0, 1, text. CEIL versus fractional.
 *   * BUY_QTY, the pack size: absent (1), 0 and negative (1), whole, fractional, text.
 *   * COVERAGE and UNIT_COST: text a person pastes ("$275", "1,375"), zero, negative, blank.
 *   * THE AREA: 0, null, text, negative, and the round numbers an estimator checks by hand,
 *     where 27,500 / 275 * 1.10 is 110.00000000000001 in floating point and a bare ceil() buys a
 *     spare pack.
 *   * LINES and CATALOGS of every shape: a line with no material, one whose material was deleted,
 *     the legacy `item` key, numbers typed on the line (ignored: the material owns them), a catalog
 *     that is missing, empty, a string, or holds nulls.
 *   * LEGACY ROWS: materials with none of waste_pct, buy_qty or roundup, the way every row written
 *     before those columns exists.
 *
 * WHAT IS NOT HERE. The text builders (money, qtyLabel, explain, costWorking) turn a priced row
 * into words; they are covered by their own tests and no phase of the program changes the
 * arithmetic they describe.
 *
 * Usage: node gen-library-golden.js <frontend-dir> [--write <file> --commit <sha> | --compare <file>]
 */
const fs = require("fs");
const path = require("path");
const G = require("./_golden");

const RECIPE_VERSION = 1;

function loadLib(frontend) {
  const p = path.resolve(frontend, "js", "library-core.js");
  if (!fs.existsSync(p)) throw new Error("js/library-core.js does not exist under " + frontend);
  return require(p);
}

function lbl(v) {
  if (v === undefined) return "undefined";
  if (Object.is(v, -0)) return "-0";
  if (typeof v === "number") return String(v);
  return JSON.stringify(v);
}
const NEG0 = -0;
const GONE = Symbol("the key is left off");

function make(base, over) {
  // Merge, then drop what is marked GONE: no `obj[key] = value` (CodeQL's property-injection query).
  const merged = Object.assign({}, base, over || {});
  return Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== GONE));
}

// One material, fully stated. Every vector varies it from here.
const BASE = { id: "m", name: "Material", unit: "Gal", unit_cost: 100, coverage: 250, buy_qty: 1, waste_pct: 0, roundup: true };
const item = (over) => make(BASE, over);

const AREAS_FEW = [0, 275, 2875, 27500, "12,500"];
const AREAS_SOME = [2750, 2875, 27500, 12500];
const AREAS_ALL = [0, 1, 275, 2750, 2875, 27500, 12500, 8250.5, 100000, "12,500", "$1,200", "", null, undefined, NaN, "abc",
  -5, 0.5, Infinity, true, NEG0];

const DIRTY = ["12,500", "$1,200", " 275 ", "", null, undefined, NaN, Infinity, "abc", "12abc", true, false, {}, [], "0",
  "-5", ".5", 0, NEG0, 1, -1, 0.5, 1e15, 1e-9, 275];

function build(frontend, add) {
  const L = loadLib(frontend);
  const call = (id, fn, ...args) => {
    if (typeof L[fn] !== "function") {
      throw new Error("library-core no longer exports " + fn + "(); point loadLib() at its new home, do not delete the vectors");
    }
    return add(id, fn, L[fn], args);
  };
  // The type of each name the module exports today: one that goes missing or changes type fails, a
  // NEW export does not (an unrelated change that adds a helper is not a pricing change).
  const EXPORT_NAMES = ["buyQty", "costWorking", "explain", "findItem", "money", "num", "perUnit", "price4",
    "priceAssembly", "priceLine", "qty4", "qtyLabel", "qtyText", "wastePct"];
  add("exports", "exportTypes", (names) => Object.fromEntries(names.map((n) =>
    [n, Object.prototype.hasOwnProperty.call(L, n) ? typeof L[n] : "missing"])), [EXPORT_NAMES]);

  // ── the small helpers ─────────────────────────────────────────────────────
  DIRTY.forEach((v, i) => call("num/" + i + "/" + lbl(v), "num", v));
  [undefined, null, {}, ...[0, 5, 7.5, 10, 100, 150, -1, "10", "", "abc", true, " 12 ", "$5", null,
    undefined, NEG0, NaN, 99.9999, "100"].map((w) => ({ waste_pct: w }))].forEach((row, i) => {
    call("waste/" + i, "wastePct", row);
  });
  [undefined, null, {}, ...[GONE, undefined, null, 0, 1, 5, 7, 2.5, -1, "5", "abc", "1,000", NaN, 0.5, "0", " 3 "]
    .map((b) => make({}, { buy_qty: b }))].forEach((row, i) => call("buy/" + i, "buyQty", row));
  const CATALOG = [item({ id: "a" }), null, item({ id: "b" }), undefined, item({ id: 7 }), item({ id: "" })];
  [["a", CATALOG], ["b", CATALOG], ["c", CATALOG], [7, CATALOG], ["7", CATALOG], ["", CATALOG], [null, CATALOG],
   [undefined, CATALOG], ["a", []], ["a", undefined], ["a", null], ["a", "abc"], ["a", {}], [0, CATALOG]]
    .forEach(([id, items], i) => call("find/" + i + "/" + lbl(id), "findItem", items, id));

  // ── one line against one material, one field at a time ────────────────────
  const line = { item_id: "m" };
  const one = (id, over, areas) => {
    const it = item(over);
    areas.forEach((a) => call("line/" + id + "/area-" + lbl(a), "priceLine", line, [it], a));
  };
  one("baseline", {}, AREAS_ALL);
  one("baselineFractional", { roundup: false }, AREAS_ALL);

  [GONE, undefined, null, 0, 5, 7.5, 10, 100, 150, -1, "10", "", "abc", true, " 12 ", "$5", NEG0, NaN, 99.9999]
    .forEach((w, i) => one("waste/" + i + "/" + (w === GONE ? "absent" : lbl(w)), { waste_pct: w }, AREAS_FEW));
  [GONE, undefined, null, true, false, 0, 1, "false", "", "yes", NaN]
    .forEach((r, i) => one("roundup/" + i + "/" + (r === GONE ? "absent" : lbl(r)), { roundup: r }, AREAS_FEW));
  [GONE, undefined, null, 0, 1, 5, 7, 2.5, -1, "5", "abc", "1,000", NaN, 0.5, "0"]
    .forEach((b, i) => one("buy/" + i + "/" + (b === GONE ? "absent" : lbl(b)), { buy_qty: b }, AREAS_FEW));
  [275, "275", "$275", "1,375", 0, -5, null, "", "abc", undefined, GONE, 0.5, 1e9, 1e-9, NaN, true, 3500, " 125 "]
    .forEach((c, i) => one("coverage/" + i + "/" + (c === GONE ? "absent" : lbl(c)), { coverage: c }, AREAS_FEW));
  [85.3827, "85.3827", "$85.38", 0, -1, null, "", "abc", undefined, GONE, 1e6, 0.0001, NaN, true, "1,234.5", 79.7574, 382.4475]
    .forEach((c, i) => one("cost/" + i + "/" + (c === GONE ? "absent" : lbl(c)), { unit_cost: c }, AREAS_FEW));

  // ── the fields that interact ──────────────────────────────────────────────
  for (const waste of [0, 5, 10]) {
    for (const roundup of [true, false]) {
      for (const buy of [1, 5, 7]) {
        for (const cov of [275, 125]) {
          one("cross/w" + waste + "/r" + roundup + "/b" + buy + "/c" + cov,
            { waste_pct: waste, roundup: roundup, buy_qty: buy, coverage: cov, unit_cost: 85.3827 }, AREAS_SOME);
        }
      }
    }
  }
  // Kyle's printed sheet, at 2,875 SF with no waste and single-unit packs: 11 gal / $939.21 and so on
  one("kyle/opf", { unit_cost: 85.3827, coverage: 275, waste_pct: 0 }, [2875]);
  one("kyle/glaze", { unit_cost: 79.7574, coverage: 125, waste_pct: 0 }, [2875]);
  one("kyle/armor", { unit_cost: 382.4475, coverage: 775, waste_pct: 0, unit: "Kit" }, [2875]);
  // a LEGACY row: written before waste_pct, buy_qty and roundup existed
  const LEGACY = { id: "m", name: "Old OPF", unit: "Gal", unit_cost: 85.3827, coverage: 275 };
  AREAS_FEW.concat([2750, 12500]).forEach((a) => call("line/legacy/area-" + lbl(a), "priceLine", line, [LEGACY], a));
  const LEGACY_BARE = { id: "m", unit_cost: 50, coverage: 100 };
  AREAS_FEW.forEach((a) => call("line/legacyBare/area-" + lbl(a), "priceLine", line, [LEGACY_BARE], a));

  // ── lines and catalogs of every shape ─────────────────────────────────────
  const m = item({});
  const LINES = {
    empty: {}, nullLine: null, undefLine: undefined, stringLine: "abc",
    blankId: { item_id: "" }, nullId: { item_id: null }, zeroId: { item_id: 0 }, missing: { item_id: "gone" },
    legacyKey: { item: "m" }, legacyMissing: { item: "gone" }, bothKeys: { item_id: "m", item: "other" },
    idBeatsLegacy: { item_id: "gone", item: "m" },
    numbersOnTheLineAreIgnored: { item_id: "m", coverage: 999, waste_pct: 50, roundup: false, buy_qty: 9, unit_cost: 1 },
    roleOnly: { role: "Top coat" },
    wrongType: { item_id: 5 },
  };
  for (const name of Object.keys(LINES)) call("line/shape/" + name, "priceLine", LINES[name], [m], 2875);
  const CATALOGS = { normal: [m], undef: undefined, nul: null, empty: [], string: "abc", object: {}, number: 5,
    withNulls: [null, undefined, m], other: [item({ id: "x" })], twoSameId: [item({ id: "m", unit_cost: 1 }), item({ id: "m", unit_cost: 2 })],
    numericId: [item({ id: 5 })] };
  for (const name of Object.keys(CATALOGS)) call("line/catalog/" + name, "priceLine", line, CATALOGS[name], 2875);
  call("line/noArguments", "priceLine");

  // ── whole assemblies ──────────────────────────────────────────────────────
  const OPF = item({ id: "i1", name: "OPF", unit_cost: 85.3827, coverage: 275, waste_pct: 0 });
  const GLAZE = item({ id: "i2", name: "Glaze #4", unit_cost: 79.7574, coverage: 125, waste_pct: 0 });
  const ARMOR = item({ id: "i3", name: "Armor Top Satin", unit: "Kit", unit_cost: 382.4475, coverage: 775, waste_pct: 0 });
  const DENS = item({ id: "i4", name: "Densifier", unit: "Pail", unit_cost: 100, coverage: 1000, waste_pct: 5 });
  const PACK = item({ id: "i5", name: "Pail", buy_qty: 5, unit_cost: 398.787, coverage: 125, waste_pct: 5 });
  const FRAC = item({ id: "i6", name: "Bulk gypsum", roundup: false, buy_qty: 7, unit_cost: 89.99, coverage: 40, waste_pct: 10 });
  const NOCOV = item({ id: "i7", name: "No coverage", coverage: 0 });
  const NOCOST = item({ id: "i8", name: "No cost", unit_cost: null });
  const LEGACY_ITEM = { id: "i9", name: "Legacy", unit: "Gal", unit_cost: 60, coverage: 300 };
  const ITEMS = [OPF, GLAZE, ARMOR, DENS, PACK, FRAC, NOCOV, NOCOST, LEGACY_ITEM];
  const lines = (...ids) => ids.map((id) => ({ role: "r", item_id: id }));
  const ASSEMBLIES = {
    kyleFlake: { name: "MACRO Flake Single Broadcast", lines: lines("i1", "i2", "i3") },
    empty: { name: "Empty", lines: [] },
    noLines: { name: "No lines key" },
    nullAsm: null, undefAsm: undefined, stringAsm: "abc",
    oneLine: { lines: lines("i1") },
    packsAndFractions: { lines: lines("i4", "i5", "i6") },
    brokenMixed: { lines: [{ item_id: "i1" }, { item_id: "deleted" }, {}, { item_id: "i7" }, { item_id: "i8" }, { item_id: "i3" }] },
    allBroken: { lines: [{ item_id: "deleted" }, { item_id: "i7" }, { item_id: "i8" }] },
    onlyUnfilled: { lines: [{}, { item_id: "" }, { item: null }] },
    legacyKey: { lines: [{ item: "i1" }, { item_id: "i9" }] },
    withNullLines: { lines: [null, undefined, { item_id: "i1" }] },
    legacyItem: { lines: lines("i9") },
    sameMaterialTwice: { lines: lines("i1", "i1") },
    everything: { lines: lines("i1", "i2", "i3", "i4", "i5", "i6", "i9") },
    linesNotArray: { lines: "abc" },
  };
  for (const name of Object.keys(ASSEMBLIES)) {
    AREAS_ALL.forEach((a, i) => {
      // the full set of areas on the assemblies that matter, a short list on the oddities
      const full = ["kyleFlake", "packsAndFractions", "brokenMixed", "everything"].includes(name);
      if (full || [0, 4, 5, 9, 11, 13].includes(i)) call("asm/" + name + "/area-" + lbl(a), "priceAssembly", ASSEMBLIES[name], ITEMS, a);
    });
  }
  call("asm/noItems", "priceAssembly", ASSEMBLIES.kyleFlake, undefined, 2875);
  call("asm/emptyItems", "priceAssembly", ASSEMBLIES.kyleFlake, [], 2875);
  call("asm/noArguments", "priceAssembly");
}

G.main({
  script: "gen-library-golden.js",
  generator: "backend/tests/js/gen-library-golden.js",
  recipeVersion: RECIPE_VERSION,
  build: build,
}, process.argv);
