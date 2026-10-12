"use strict";
/* SYSTEM 1 AND SYSTEM 2 ARE TWO SEPARATE TAKEOFF AREAS FROM THE START (Hanz, 2026-10-13, "Separate areas").
 *
 * The page under test is executed whole (js/polish-estimate.js, through polish-estimate-harness.js's own
 * prelude, the way takeoff-unit-harness.js does it: everything above that file's scenario block is reused,
 * so there is one DOM stub and one fetch stub, not two). The REAL js/bid-model.js and js/library-core.js run
 * underneath. A new bid is opened on that page with System 1 and System 2 typed on the intake, so the takeoff
 * the page seeds is the one the estimator gets; every answer below is what the code did.
 *
 * What intake does with its two boxes is also run for real, at the one place it reaches the model: the boxes
 * show B.measuredSfValues(takeoff), and a typed figure goes in through B.patchModel(model, {sf_areas}).
 * (js/polish-intake.js's own box behaviour is run by polish-intake-harness.js.)
 *
 * Usage: node system2-areas-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");

const BASE = path.join(__dirname, "polish-estimate-harness.js");
const code = fs.readFileSync(BASE, "utf8").replace(/\r\n/g, "\n");
const MARK = "(async function () {\n  // ── A. the takeoff row";
const at = code.indexOf(MARK);
if (at < 0) throw new Error("polish-estimate-harness.js scenario block moved; update the marker");
const head = code.slice(0, at);

const SCENARIOS = String.raw`
// Appended to polish-estimate-harness.js's prelude: build, blob, clone, B, L, ASMS, ITEMS, expectedChain and
// the rest are in scope.

// A library whose coverages DIVIDE the floors used below (every pack is whole at 3,000 / 3,500 / 4,000 /
// 5,000 / 8,000 SF), so "two areas price what one combined floor prices" is a statement about the rows and
// not about where a pack happens to round up. The real library's rounding is measured separately (packs).
const EVEN_ITEMS = [
  { id: "e1", name: "Coat A", unit: "Gal", buy_qty: 1, unit_cost: 20, coverage: 100, waste_pct: 0 },
  { id: "e2", name: "Coat B", unit: "Gal", buy_qty: 1, unit_cost: 30, coverage: 250, waste_pct: 0 },
  { id: "e3", name: "Densifier E", unit: "Pail", buy_qty: 1, unit_cost: 50, coverage: 50, waste_pct: 0, favorite: true },
];
const EVEN_ASMS = [
  { id: "s1", name: "System One", unit: "SF", favorite: true, lines: [{ item_id: "e1", coverage: 100, waste_pct: 0, roundup: true }] },
  { id: "s2", name: "System Two", unit: "SF", favorite: true, lines: [{ item_id: "e2", coverage: 250, waste_pct: 0, roundup: true }] },
  { id: "s3", name: "Cove E", unit: "LF", favorite: true, lines: [{ item_id: "e1", coverage: 100, waste_pct: 0, roundup: true }] },
];

const NEW_BID = (sf1, sf2) => blob({ polish_estimate: null, polish_sf: sf1, polish_2_sf: sf2 });
// The first row that carries an area; a takeoff with no area marks (a saved one) has the first plain SF row.
const carrierIndex = (rows) => { const i = rows.findIndex((r) => r.floor_area === 1);
  return i >= 0 ? i : rows.findIndex((r) => r.unit === "SF" && !r.same_floor); };
const shape = (m) => m.takeoff.map((r) => ({ id: r.assembly_id || r.item_id || "", m: r.measurement, u: r.unit,
  carrier: r.floor_area || 0, follows: r.same_floor ? (r.same_floor_of || 0) : null }));
const open = async (blb, asms, items) => {
  const b = build({ asms: clone(asms), items: clone(items), blob: blb });
  await b.api.init();
  b.clock.fire();
  return b;
};
const totalOf = (b) => b.api.activeBid().total;
// What intake's save() does with a figure the estimator typed into a box: the narrow door patchModel gives it.
const typed = (model, a1, a2) => B.patchModel(model, { sf_areas: [a1, a2] });
const view = (m) => ({ rows: shape(m), values: B.measuredSfValues(m.takeoff), areas: B.measuredSfAreas(m.takeoff),
  measured: B.measuredSf(m.takeoff), priced: B.takeoffSf(m.takeoff) });

(async function () {
  const out = {};

  // ── 1. A NEW BID, SYSTEM 1 5,000 + SYSTEM 2 3,000: two areas, each with its own copy of the defaults ──
  const two = await open(NEW_BID(5000, 3000), EVEN_ASMS, EVEN_ITEMS);
  const twoModel = two.api.model();
  out.seeded = Object.assign(view(twoModel), { total: totalOf(two) });

  // THE TOTAL EQUALS WHAT ONE COMBINED 8,000 SF FLOOR PRICES (every pack is whole in this library)
  const combined = await open(NEW_BID(8000, ""), EVEN_ASMS, EVEN_ITEMS);
  out.combined = Object.assign(view(combined.api.model()), { total: totalOf(combined) });

  // ── 2. THE REAL LIBRARY ROUNDS EACH AREA'S PACKS: the one place two areas can cost more than one ───────
  {
    const realAsms = clone(ASMS).map((a) => { if (a.id === "a1" || a.id === "a5") a.favorite = true; return a; });
    const realItems = clone(ITEMS).map((it) => { if (it.id === "i1") it.favorite = true; return it; });
    const r2 = await open(NEW_BID(5000, 3000), realAsms, realItems);
    const r1 = await open(NEW_BID(8000, ""), realAsms, realItems);
    out.packs = { two: totalOf(r2), one: totalOf(r1), twoPriced: B.takeoffSf(r2.api.model().takeoff),
                  onePriced: B.takeoffSf(r1.api.model().takeoff) };
  }

  // ── 3. WHAT THE INTAKE BOXES SHOW, AND TYPING INTO EACH ───────────────────────────────────────────────
  const baseModel = clone(twoModel);
  const sys2 = typed(baseModel, 5000, 3500);
  out.sys2 = Object.assign(view(sys2), { rowCount: sys2.takeoff.length, was: baseModel.takeoff.length });
  const sys1 = typed(baseModel, 4000, 3000);
  out.sys1 = Object.assign(view(sys1), { rowCount: sys1.takeoff.length });
  // both boxes at once (a save carries both when both were typed)
  out.both = view(typed(baseModel, 6000, 2000));
  // clearing a box never deletes: blank, zero and negative write nothing
  out.cleared = {};
  [["", ""], [0, 0], [-5, -5], [5000, ""], ["", 3000]].forEach(([a, b2], n) => {
    out.cleared["c" + n] = Object.assign(view(typed(baseModel, a, b2)), { rowCount: typed(baseModel, a, b2).takeoff.length });
  });

  // the typed model prices what a combined floor of the same total prices (8,500 SF, whole packs)
  const sys2Blob = clone(two.store.blob);
  sys2Blob.polish_estimate = sys2;
  sys2Blob.polish_sf = 8500;
  const sys2Page = await open(sys2Blob, EVEN_ASMS, EVEN_ITEMS);
  const comb85 = await open(NEW_BID(8500, ""), EVEN_ASMS, EVEN_ITEMS);
  out.sys2Priced = { total: totalOf(sys2Page), combined: totalOf(comb85) };

  // ── 4. TWO AREAS THAT HOLD THE SAME NUMBER ARE STILL TWO AREAS ────────────────────────────────────────
  const equal = await open(NEW_BID(4000, 4000), EVEN_ASMS, EVEN_ITEMS);
  const eqModel = equal.api.model();
  const eq1 = typed(eqModel, 5000, 4000);
  const eq2 = typed(eqModel, 4000, 5000);
  out.equal = { seeded: view(eqModel), sys1: view(eq1), sys2: view(eq2) };

  // ── 5. RELOAD: the saved bid opens as saved, the boxes read what they read before ─────────────────────
  const saved = clone(two.store.blob);
  const reopened = build({ asms: clone(EVEN_ASMS), items: clone(EVEN_ITEMS), blob: saved });
  await reopened.api.init();
  out.reload = Object.assign(view(reopened.api.model()), { total: totalOf(reopened), saves: reopened.rec.saves.length,
    savedValues: B.measuredSfValues(saved.polish_estimate.takeoff), savedPolishSf: saved.polish_sf });

  // ── 6. ONE AREA FIRST, THE SECOND TYPED LATER: it gets its own copy of the defaults, not a bare row ───
  const one = await open(NEW_BID(5000, ""), EVEN_ASMS, EVEN_ITEMS);
  const oneModel = one.api.model();
  const added = typed(oneModel, 5000, 3000);
  out.late = Object.assign(view(added), { before: oneModel.takeoff.length, rowCount: added.takeoff.length });
  const lateBlob = clone(one.store.blob);
  lateBlob.polish_estimate = added; lateBlob.polish_sf = 8000;
  out.late.total = totalOf(await open(lateBlob, EVEN_ASMS, EVEN_ITEMS));
  const lateAgain = typed(added, 5000, 3000);
  out.late.idempotent = JSON.stringify(lateAgain.takeoff) === JSON.stringify(added.takeoff);

  // ── 7. A SAVED COMBINED-CARRIER BID (made before the areas were separate) opens and edits as it always did ──
  {
    const old = clone(twoModel);
    old.takeoff = [
      { assembly_id: "s1", assembly_name: "System One", measurement: 8000, unit: "SF" },
      { assembly_id: "s3", assembly_name: "Cove E", measurement: "", unit: "LF" },
      { kind: "item", item_id: "e3", item_name: "Densifier E", coverage: "", measurement: 8000, unit: "SF", same_floor: true },
    ];
    const oldBlob = clone(two.store.blob);
    oldBlob.polish_estimate = clone(old); oldBlob.polish_sf = 8000; oldBlob.polish_2_sf = "";
    const o = build({ asms: clone(EVEN_ASMS), items: clone(EVEN_ITEMS), blob: oldBlob });
    await o.api.init();
    const om = o.api.model();
    const asSaved = JSON.stringify(om.takeoff) === JSON.stringify(old.takeoff);
    const s2 = typed(om, 8000, 3000);
    const s1 = typed(om, 9000, "");
    out.old = { asSaved: asSaved, view: view(om), saves: o.rec.saves.length, total: totalOf(o),
                sys2: Object.assign(view(s2), { rowCount: s2.takeoff.length }), sys1: view(s1) };
  }

  // ── 8. EVERY DEFAULT OFF, AND A LIBRARY OF LINEAR FEET: the plain System rows, one per area ──────────────
  {
    const allOff = clone(EVEN_ASMS).map((a) => Object.assign(a, { default_on: false }));
    const off = await open(NEW_BID(5000, 3000), allOff.filter((a) => a.unit === "SF"), clone(EVEN_ITEMS).map((i) => Object.assign(i, { favorite: false })));
    out.allOff = Object.assign(view(off.api.model()), { total: totalOf(off) });
    const lfOnly = await open(NEW_BID(5000, 3000), EVEN_ASMS.filter((a) => a.unit === "LF"), clone(EVEN_ITEMS).map((i) => Object.assign(i, { favorite: false })));
    out.lfOnly = view(lfOnly.api.model());
  }

  // ── 9. A DELETED CARRIER: the rows that followed its area still hold that area ───────────────────────────
  {
    const m = clone(twoModel);
    const gone = carrierIndex(m.takeoff);
    m.takeoff.splice(gone, 1);
    out.carrierGone = Object.assign(view(m), { typed: view(typed(m, 4500, 3000)) });
  }

  // ── 10. A UNIT CHANGE TAKES THE ROW OUT OF ITS AREA ───────────────────────────────────────────────────────
  {
    const m = clone(twoModel);
    const i = carrierIndex(m.takeoff);
    B.adoptTakeoffUnit(m.takeoff, i, "LF");
    out.unitChange = { row: m.takeoff[i], values: B.measuredSfValues(m.takeoff) };
  }

  // ── 11. THE PAGE'S OWN SETMEASUREMENT: typing into a carrier moves only its own area ─────────────────────
  {
    const b = await open(NEW_BID(4000, 4000), EVEN_ASMS, EVEN_ITEMS);
    b.api.go(0);
    const first = carrierIndex(b.api.model().takeoff);
    typeInto(b, '[data-tk="' + first + '"][data-k="measurement"]', "5000");
    out.typedCarrier = view(b.api.model());
  }

  // ── 12. A ROW ADDED BESIDE A MEASURED ONE IN AN EPOXY SECTION COVERS EVERY AREA, NOT ONLY THE FIRST ───────
  {
    const ep = await open(blob({ work_type: "epoxy", polish_estimate: null, system_1_sf: 5000, system_2_sf: 3000 }),
      EVEN_ASMS, EVEN_ITEMS);
    ep.api.go(0);
    const before = ep.api.model().takeoff.length;
    ep.api.addPickedTakeoffRow({ kind: "item", id: "e1", name: "Coat A" });
    const em = ep.api.model();
    out.pickedBeside = Object.assign(view(em), { before: before, rowCount: em.takeoff.length,
      total: totalOf(ep) });
    // the floor each area gives the row that was picked (Coat A is not a default of this library)
    out.pickedBeside.coatA = em.takeoff.filter((r) => r.item_id === "e1")
      .map((r) => ({ m: r.measurement, follows: r.same_floor ? (r.same_floor_of || 0) : null, on: r.enabled !== false }));
    // a bid with ONE area keeps adding one row, and a saved unmarked bid keeps following its one carrier
    const single = await open(blob({ work_type: "epoxy", polish_estimate: null, system_1_sf: 5000, system_2_sf: "" }),
      EVEN_ASMS, EVEN_ITEMS);
    single.api.go(0);
    const sb = single.api.model().takeoff.length;
    single.api.addPickedTakeoffRow({ kind: "item", id: "e1", name: "Coat A" });
    out.pickedBesideOne = { before: sb, rowCount: single.api.model().takeoff.length, rows: shape(single.api.model()) };
  }

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
`;

const m = new Module(BASE, module);
m.filename = BASE;
m.paths = Module._nodeModulePaths(path.dirname(BASE));
m._compile(head + SCENARIOS, BASE);
