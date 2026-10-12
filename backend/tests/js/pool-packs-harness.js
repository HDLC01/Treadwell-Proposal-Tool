"use strict";
/* A MATERIAL USED ON SEVERAL TAKEOFF ROWS IS BOUGHT ONCE FOR THE SECTION (Hanz, 2026-10-13, "Buy packs for the whole job").
 *
 * Everything below is what the code answered, run under node on the REAL files:
 *
 *   unit    library-core's pricePool on small libraries whose every figure can be worked by hand: the pooled pack count,
 *           the split back to the rows (largest remainder, ten-thousandths), an OFF row, a reserved item, a coverage
 *           typed on one bid (`pool_of`), a price ladder shared by two materials, and a row nothing pools with.
 *   model   which sections carry the stamp that turns the pool on (bid-model.js poolsPacks): a new bid's root, a made
 *           section, a SAVED root and a saved section (never).
 *   page    js/polish-estimate.js whole (through polish-estimate-harness.js's own boot code), on the library the seed
 *           script plans, which is Kyle's real one: an Epoxy job whose System 1 and System 2 buy the same flake and the
 *           same primer, against the same floor as one area; the rows' costs against the section's material; a saved
 *           section with no stamp; an OFF row; a reserved material; and the Polish root.
 *
 * Usage: node pool-packs-harness.js <frontend-dir> <plan.json>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
const LIB = require(path.join(ROOT, "js", "library-core.js"));
const X = require(path.join(ROOT, "js", "epoxy-takeoff.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const flush = () => new Promise((r) => setImmediate(r));
const near = (a, b) => Math.abs(a - b) < 1e-9;
const tenThousandths = (n) => Math.round(n * 1e4);

// ═══ 1. UNIT: library-core pricePool ═════════════════════════════════════════════════════════════════════════
const item = (over) => Object.assign({ id: "A", name: "Coat A", unit: "Gal", buy_qty: 1, unit_cost: 100, coverage: 100,
  waste_pct: 0, roundup: true }, over || {});
const asmOf = (id) => ({ id: "asm-" + id, name: "Asm " + id, unit: "SF", lines: [{ item_id: id }] });
const priceAt = (items, id, area) => LIB.priceAssembly(asmOf(id), items, area);
const costs = (results) => results.map((r) => (r ? r.total : null));
const sum = (xs) => xs.reduce((t, x) => t + (x || 0), 0);

function unit() {
  const out = {};

  // one material on two rows: 1.5 + 1.3 = 2.8 gallons, bought as 3, not as 2 + 2
  {
    const items = [item()];
    const alone = [priceAt(items, "A", 150), priceAt(items, "A", 130)];
    const pooled = LIB.pricePool(alone);
    out.once = { alone: costs(alone), aloneTotal: sum(costs(alone)), pooled: costs(pooled), pooledTotal: sum(costs(pooled)),
      pack: pooled[0].rows[0].pooled, perUnit: pooled[0].per_unit, area: 150, aloneUntouched: alone[0].total,
      sumsExactly: tenThousandths(sum(costs(pooled))) === 3000000 };
  }

  // the split is by what each row NEEDED, the leftover ten-thousandths to the biggest fractions
  {
    const items = [item({ id: "Z", unit_cost: 1, coverage: 3 })];
    const three = LIB.pricePool([priceAt(items, "Z", 1), priceAt(items, "Z", 1), priceAt(items, "Z", 1)]);
    out.remainder = { parts: costs(three), sum: sum(costs(three)), exact: tenThousandths(sum(costs(three))) === 10000 };
    const items2 = [item()];
    const two = LIB.pricePool([priceAt(items2, "A", 150), priceAt(items2, "A", 130)]);
    out.biggestFraction = costs(two);
  }
  out.allocate = {
    thirds: LIB.allocate(1, [1, 1, 1]), uneven: LIB.allocate(300, [1.5, 1.3]), none: LIB.allocate(5, []),
    zeroWeights: LIB.allocate(7, [0, 0]), offGrain: LIB.allocate(1 / 3, [1, 2]),
  };

  // a row nothing pools with is the very object it went in as
  {
    const items = [item(), item({ id: "B", name: "Coat B" })];
    const a = priceAt(items, "A", 150), b = priceAt(items, "B", 150);
    const pooled = LIB.pricePool([a, b]);
    out.untouched = { same: pooled[0] === a && pooled[1] === b };
    const nulls = LIB.pricePool([null, a, null]);
    out.nulls = { length: nulls.length, first: nulls[0], middle: nulls[1] === a };
  }

  // an OFF row buys nothing and takes no share
  {
    const items = [item()];
    const rows = [priceAt(items, "A", 150), priceAt(items, "A", 130), priceAt(items, "A", 120)];
    const pooled = LIB.pricePool(rows, { on: [true, false, true] });
    out.off = { costs: costs(pooled), offIsTheSameObject: pooled[1] === rows[1],
      // 1.5 + 1.2 = 2.7 gallons -> 3, shared between rows 0 and 2 only
      onTotal: pooled[0].total + pooled[2].total };
  }

  // a reserved item is never pooled
  {
    const items = [item()];
    const rows = [priceAt(items, "A", 150), priceAt(items, "A", 130)];
    const pooled = LIB.pricePool(rows, { skip: ["A"] });
    out.skip = { same: pooled[0] === rows[0] && pooled[1] === rows[1], costs: costs(pooled) };
  }

  // a coverage typed on one bid is the same material: its copy carries `pool_of`
  {
    const real = item();
    const copy = Object.assign({}, real, { id: "__cov0", pool_of: "A", coverage: 50 });
    const items = [real, copy];
    const a = priceAt(items, "A", 150);                // 1.5 gallons
    const b = priceAt(items, "__cov0", 100);           // 100 / 50 = 2 gallons
    const pooled = LIB.pricePool([a, b]);
    out.poolOf = { alone: [a.total, b.total], pooled: costs(pooled), packs: (pooled[0].rows[0].pooled || {}).packs,
      withoutPoolOf: costs(LIB.pricePool([priceAt([real, Object.assign({}, copy, { pool_of: undefined })], "A", 150),
        priceAt([real, Object.assign({}, copy, { pool_of: undefined })], "__cov0", 100)])) };
  }

  // a fractional purchase (roundup off) has no packs to round, but its break is judged on the whole
  {
    const items = [item({ id: "N", roundup: false, unit_cost: 10, coverage: 10, price_breaks: [{ min_qty: 20, unit_cost: 8 }] })];
    const alone = [priceAt(items, "N", 105), priceAt(items, "N", 95)];      // 10.5 + 9.5 units, each under the break
    const pooled = LIB.pricePool(alone);
    out.fractional = { alone: sum(costs(alone)), pooled: costs(pooled), pooledTotal: sum(costs(pooled)),
      exact: near(sum(costs(pooled)), 160), breakNamed: pooled[0].rows[0].price_break };
  }

  // a price ladder two DIFFERENT materials sit on: each keeps its own packs, the break is judged on both
  {
    const ladder = { unit: "Bag", unit_cost: 100, price_breaks: [{ min_qty: 6, unit_cost: 90 }], waste_pct: 0 };
    const items = [item(Object.assign({ id: "F1", coverage: 100 }, ladder)), item(Object.assign({ id: "F2", coverage: 50 }, ladder)),
      item(Object.assign({ id: "F3", coverage: 50 }, ladder, { unit_cost: 101 }))];
    const a = priceAt(items, "F1", 200), b = priceAt(items, "F2", 200);    // 2 bags and 4 bags: neither reaches 6 alone
    const pooled = LIB.pricePool([a, b]);
    const other = LIB.pricePool([a, priceAt(items, "F3", 200)]);           // another price: not the same ladder
    out.ladder = { alone: [a.total, b.total], pooled: costs(pooled), packs: [pooled[0].rows[0].packs, pooled[1].rows[0].packs],
      packCost: pooled[0].rows[0].pack_cost, breakNamed: pooled[1].rows[0].price_break || null,
      otherLadder: costs(other), otherSame: other[0] === a };
    // ... and the same two lines of ONE assembly (a system's two broadcasts), which is how the sheet reads them
    const asm = { id: "sys", name: "System", unit: "SF", lines: [{ item_id: "F1" }, { item_id: "F2" }] };
    const one = LIB.priceAssembly(asm, items, 200);
    const both = LIB.pricePool([one]);
    out.ladderInOneRow = { alone: one.total, pooled: both[0].total, priced: both[0].priced_lines, broken: both[0].broken_lines };
  }

  // a line that cannot price is left exactly as it is, and the rest still pool
  {
    const items = [item()];
    const broken = LIB.priceAssembly({ id: "x", name: "X", unit: "SF", lines: [{ item_id: "gone" }, { item_id: "A" }] }, items, 150);
    const other = priceAt(items, "A", 130);
    const pooled = LIB.pricePool([broken, other]);
    out.brokenLine = { reasons: pooled[0].rows.map((r) => r.reason || "ok"), broken: pooled[0].broken_lines, costs: costs(pooled) };
  }

  // the Bulk Discount switch: the pool buys at the bulk cost the lines were priced at
  {
    const items = [item({ bulk_cost: 80 })];
    const alone = [LIB.priceAssembly(asmOf("A"), items, 150, { bulk: true }), LIB.priceAssembly(asmOf("A"), items, 130, { bulk: true })];
    const pooled = LIB.pricePool(alone);
    out.bulk = { alone: sum(costs(alone)), pooled: sum(costs(pooled)), bulk: pooled[0].rows[0].bulk };
  }

  // the exports a caller reads
  out.exports = { pricePool: typeof LIB.pricePool, allocate: typeof LIB.allocate, poolId: typeof LIB.poolId };
  return out;
}

// ═══ 2. MODEL: which sections carry the stamp ════════════════════════════════════════════════════════════════
function model() {
  const out = {};
  const nothing = { saved: null, sf: {}, lf: {} };
  const fresh = B.seedNewSections(B.migrateModel(null), nothing);
  out.newBid = { root: fresh.pool_packs, poolsPacks: B.poolsPacks(fresh) };

  // a SAVED bid: the blob states labor and conditions, so nothing of it is new
  const savedBlob = { version: 2, takeoff: [{ assembly_id: "a1", measurement: 5000, unit: "SF" }],
    labor: [{ id: "polishing", label: "Polishing", guys: 2, days: 3, rate: 40 }], conditions: { local: true },
    contingency: 0, fees: 0, totals: {} };
  const saved = B.seedNewSections(B.migrateModel(clone(savedBlob)), { saved: clone(savedBlob), sf: {}, lf: {} });
  out.savedBid = { root: saved.pool_packs === undefined ? "absent" : saved.pool_packs, poolsPacks: B.poolsPacks(saved) };

  // a section made now
  const made = B.activateSection(Object.assign({}, B.freshModel(), { kind: "off" }), "Epoxy", "base", {});
  out.activated = { stamp: made.tabs.Epoxy.pool_packs, poolsPacks: B.poolsPacks(made.tabs.Epoxy) };
  // ... and a saved section that has no stamp is not touched by seeding, empty or not
  const unstamped = clone(made);
  delete unstamped.tabs.Epoxy.pool_packs;
  unstamped.tabs.Epoxy.takeoff = [{ assembly_id: "x", assembly_name: "X", measurement: 4000, unit: "SF" }];
  const reseeded = B.seedNewSections(unstamped, { saved: { version: 2, labor: [{ id: "x" }] }, sf: {}, lf: {} });
  out.savedSection = { stamp: reseeded.tabs.Epoxy.pool_packs === undefined ? "absent" : reseeded.tabs.Epoxy.pool_packs,
    poolsPacks: B.poolsPacks(reseeded.tabs.Epoxy) };

  // the stamp rides through a save and a reload
  const roundTrip = B.migrateModel(JSON.parse(JSON.stringify(fresh)));
  out.roundTrip = { root: roundTrip.pool_packs };
  const tabbed = B.migrateModel(JSON.parse(JSON.stringify(made)));
  out.roundTripTab = { stamp: tabbed.tabs.Epoxy.pool_packs };

  // only exactly true pools
  out.strict = [true, false, undefined, null, 1, "true", {}].map((v) => B.poolsPacks({ pool_packs: v }))
    .concat([B.poolsPacks(null), B.poolsPacks(undefined), B.poolsPacks([])]);
  return out;
}

// ═══ 3. PAGE: the estimate page on Kyle's real library ═══════════════════════════════════════════════════════
function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in pool-packs-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}
const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "MODEL", "ITEMS", "ASMS"]);

const asms = plan.assemblies;
const items = plan.items;
const norm = (t) => String(t).replace(/\s+/g, " ").trim();
const asmNamed = (n) => asms.find((a) => norm(a.name) === norm(n));
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
  default_work_types: [], default_on: true };
const laborRows = [TRAVEL_ROW].concat(plan.labor.map((r) => Object.assign({}, r, { default_on: true, owner_email: "kyle@wetreadwell.com" })));
const calcRows = plan.labor_calc.map((r) => Object.assign({}, r, { days: null, rate: null, sf_per_day: null, crew: null }));

const SYSTEM = asmNamed("MACRO Flake Single Broadcast");
const DOUBLE = asmNamed("micro Flake Double Broadcast");
const QUARTZ = asmNamed("40-S (Q28) Quartz Double Broadcast");
const PRIMER = asmNamed("Primer: MVP (@ 12 mils)");

/** A takeoff the way the seeding writes it: each area is its OWN copy of the lines, the first carrying the floor. */
function areaRows(systemAsm, areas, withPrimer) {
  const rows = [];
  areas.forEach((sf, k) => {
    const tag = k + 1;
    rows.push({ assembly_id: systemAsm.id, assembly_name: systemAsm.name, measurement: sf, unit: "SF", floor_area: tag });
    if (withPrimer) {
      rows.push({ assembly_id: PRIMER.id, assembly_name: PRIMER.name, measurement: sf, unit: "SF", same_floor: true, same_floor_of: tag });
    }
  });
  return rows;
}

/** A SAVED Epoxy bid holding `rows`, stamped to pool or not. Nothing is seeded onto it (it states a takeoff and a crew). */
function epoxyBlob(rows, pooled) {
  const section = { layout: "epoxy", kind: "base", profile: "epoxy@1", takeoff: rows,
    labor: [{ id: "epoxy-install", label: "Epoxy install", guys: 3, days: 5, rate: 33, unit: "days" }],
    contingency: 0, fees: 0, totals: {} };
  if (pooled === true) section.pool_packs = true;
  return P.blob({ work_type: "epoxy", polish_estimate: { version: 2, kind: "off",
    takeoff: [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }],
    conditions: { taxable: true, prevailing_wage: false, remodel_tax: false }, tabs: { Epoxy: section } } });
}

async function open(blb, extra) {
  const b = P.build(Object.assign({ blob: blb, asms: asms, items: items, labor: laborRows, laborCalc: calcRows }, extra || {}));
  await b.api.init();
  await flush();
  return b;
}

/** What the page says an Epoxy job costs, and the pieces: the bid, the section's material, and every row's own cost. */
async function epoxyPrice(rows, pooled) {
  const b = await open(epoxyBlob(clone(rows), pooled));
  const api = b.api, m = api.model(), t = m.takeoff;
  const rowCosts = t.map((r) => { const p = api.rowPrice(r, t); return p ? p.total : null; });
  return { total: api.activeBid().total, material: api.materialTotal(), tooling: api.activeBid().tooling,
    rowCosts: rowCosts, rowSum: sum(rowCosts), patch: X.patchCost(api.items(), B.takeoffSf(t)),
    sf: B.takeoffSf(t), stamped: B.poolsPacks(B.sectionOf(api.model(), "Epoxy").section), saves: b.rec.saves.length };
}

async function page() {
  const out = {};

  // THE FLOORS the program measured on Kyle's real library: 5,000 + 3,000, 1,000 + 1,000 and two odd ones, with the same
  // flake and the same primer in each area, against one area of the same floor
  out.pairs = [];
  for (const [a, b] of [[5000, 3000], [1000, 1000], [2500, 1500], [1234, 4321], [700, 300]]) {
    const two = await epoxyPrice(areaRows(SYSTEM, [a, b], true), true);
    const one = await epoxyPrice(areaRows(SYSTEM, [a + b], true), true);
    const rowByRow = await epoxyPrice(areaRows(SYSTEM, [a, b], true), false);
    out.pairs.push({ areas: [a, b], twoTotal: two.total, oneTotal: one.total, rowByRowTotal: rowByRow.total,
      twoMaterial: two.material, oneMaterial: one.material, rowByRowMaterial: rowByRow.material, sf: [two.sf, one.sf],
      stamped: [two.stamped, rowByRow.stamped], saves: two.saves });
  }

  // a double-broadcast system (two flake lines of one item) and a pair of different systems that share the primer
  {
    const two = await epoxyPrice(areaRows(DOUBLE, [5000, 3000], true), true);
    const one = await epoxyPrice(areaRows(DOUBLE, [8000], true), true);
    out.double = { two: two.total, one: one.total, twoMaterial: two.material, oneMaterial: one.material };
    // System 1 the flake, System 2 the quartz: different systems that still buy the same primer
    const mixed = [
      { assembly_id: SYSTEM.id, assembly_name: SYSTEM.name, measurement: 5000, unit: "SF", floor_area: 1 },
      { assembly_id: PRIMER.id, assembly_name: PRIMER.name, measurement: 5000, unit: "SF", same_floor: true, same_floor_of: 1 },
      { assembly_id: QUARTZ.id, assembly_name: QUARTZ.name, measurement: 3000, unit: "SF", floor_area: 2 },
      { assembly_id: PRIMER.id, assembly_name: PRIMER.name, measurement: 3000, unit: "SF", same_floor: true, same_floor_of: 2 }];
    const m = await epoxyPrice(mixed, true), n = await epoxyPrice(mixed, false);
    out.mixed = { pooled: m.material, rowByRow: n.material, rowsSumToMaterial: near(m.rowSum + m.patch, m.material) };
  }

  // THE ROWS ADD UP TO THE SECTION: every row shows its share, and the shares and the patch are the section's material
  {
    const p = await epoxyPrice(areaRows(SYSTEM, [5000, 3000], true), true);
    const q = await epoxyPrice(areaRows(SYSTEM, [5000, 3000], true), false);
    out.rows = { costs: p.rowCosts, sum: p.rowSum, patch: p.patch, material: p.material, adds: near(p.rowSum + p.patch, p.material),
      everyRowPriced: p.rowCosts.every((c) => c > 0), unpooledAdds: near(q.rowSum + q.patch, q.material),
      moved: p.rowCosts.map((c, i) => Math.abs(c - q.rowCosts[i]) > 0.005) };
  }

  // a SAVED section with no stamp prices each row's packs on its own, exactly as before the pool
  {
    const rows = areaRows(SYSTEM, [5000, 3000], true);
    const saved = await epoxyPrice(rows, false);
    out.savedSection = { stamped: saved.stamped, material: saved.material,
      // the old number, worked out row by row with no pool anywhere in it
      byRow: sum(clone(rows).map((r) => { const a = asms.find((x) => x.id === r.assembly_id); return LIB.priceAssembly(a, items, B.num(r.measurement)).total; })) + saved.patch };
  }

  // an OFF row takes no share and buys nothing: turning area 2 off prices area 1 alone
  {
    const rows = areaRows(SYSTEM, [5000, 3000], true).map((r, i) => (i >= 2 ? Object.assign({}, r, { enabled: false }) : r));
    const off = await epoxyPrice(rows, true);
    const first = await epoxyPrice(areaRows(SYSTEM, [5000], true), true);
    out.off = { material: off.material, alone: first.material, offRowCosts: off.rowCosts.slice(2), sf: [off.sf, first.sf] };
  }

  // a RESERVED material (dye) in two rows is never pooled: it belongs to its own condition card
  {
    const dyeAsm = { id: "a-dye", name: "Dye Coat", unit: "SF", lines: [{ item_id: "dye" }] };
    const dyeItem = { id: "dye", name: "Dye, per coat", unit: "Gal", buy_qty: 1, unit_cost: 10, coverage: 1, waste_pct: 0, roundup: true };
    const model0 = clone(P.MODEL);
    model0.pool_packs = true;
    model0.takeoff = [{ assembly_id: "a-dye", assembly_name: "Dye Coat", measurement: 5000.3, unit: "SF", floor_area: 1 },
      { assembly_id: "a-dye", assembly_name: "Dye Coat", measurement: 3000.3, unit: "SF", floor_area: 2 }];
    const b = await open(P.blob({ polish_estimate: model0 }), { asms: clone(P.ASMS).concat([dyeAsm]), items: clone(P.ITEMS).concat([dyeItem]) });
    const t = b.api.model().takeoff;
    const costsNow = t.map((r) => b.api.rowPrice(r, t).total);
    const aloneCosts = [5000.3, 3000.3].map((a) => LIB.priceAssembly(dyeAsm, [dyeItem], a).total);
    out.reserved = { costs: costsNow, alone: aloneCosts, reservedIds: b.api.RESERVED_ITEM_IDS.slice() };
  }

  // A COVERAGE TYPED ON ONE ROW of a bid is still the same material: OPF (i1) on the first row's line at 300 SF a gallon,
  // on the second at the library's 275, bought once. Worked by hand: the gallons each row needs added, then rounded up.
  {
    const m0 = clone(P.MODEL);
    m0.pool_packs = true;
    m0.takeoff = [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 5000, unit: "SF", floor_area: 1, line_cov: { 0: 300 } },
      { assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 3000, unit: "SF", floor_area: 2 }];
    const b = await open(P.blob({ polish_estimate: m0 }), { asms: clone(P.ASMS), items: clone(P.ITEMS) });
    const t = b.api.model().takeoff;
    const rc = t.map((r) => b.api.rowPrice(r, t).total);
    const gallons = Math.ceil(parseFloat(((5000 / 300 + 3000 / 275) * 1.05).toPrecision(12)));
    const kits = Math.ceil(parseFloat(((8000 / 775) * 1.05).toPrecision(12)));
    out.typedCoverage = { rowSum: sum(rc), expected: gallons * 85.3827 + kits * 382.4475, gallons: gallons, kits: kits };
  }

  // THE POLISH ROOT pools too (its rows are priced by the same wrapper): the Polish assembly in two areas
  {
    const area = (sf, tag) => ({ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: sf, unit: "SF", floor_area: tag });
    const priceRoot = async (rows, pooled) => {
      const m0 = clone(P.MODEL);
      m0.takeoff = rows;
      if (pooled) m0.pool_packs = true;
      const b = await open(P.blob({ polish_estimate: m0 }), { asms: clone(P.ASMS), items: clone(P.ITEMS) });
      const t = b.api.model().takeoff;
      const rc = t.map((r) => b.api.rowPrice(r, t).total);
      return { total: b.api.bid().total, material: b.api.materialTotal(), rowSum: sum(rc), rowCosts: rc };
    };
    const two = await priceRoot([area(5000, 1), area(3000, 2)], true);
    const one = await priceRoot([area(8000, 1)], true);
    const rowByRow = await priceRoot([area(5000, 1), area(3000, 2)], false);
    out.root = { two: two.total, one: one.total, rowByRow: rowByRow.total, rowsAdd: near(two.rowSum, two.material),
      rowByRowAdds: near(rowByRow.rowSum, rowByRow.material), twoMaterial: two.material, oneMaterial: one.material };
  }
  return out;
}

async function main() {
  const out = { unit: unit(), model: model() };
  out.page = await page();
  return out;
}

main().then((out) => console.log(JSON.stringify(out))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
