"use strict";
/* A TAKEOFF ROW'S UNIT COMES FROM ITEMS & ASSEMBLIES (Hanz, 2026-10-12: "Unit should be pulled from
 * the items and assemblies tab").
 *
 * The page under test is executed whole (js/polish-estimate.js, through polish-estimate-harness.js's own
 * prelude, the way condition-cells-takeoff-harness.js does it: everything above that file's scenario block
 * is reused, so there is one DOM stub and one fetch stub, not two). The REAL js/bid-model.js,
 * js/library-core.js and js/library-picker.js run underneath. Every answer below is what the page did.
 *
 * Usage: node takeoff-unit-harness.js <frontend-dir>   ->  one line of JSON
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
// Appended to polish-estimate-harness.js's prelude: build, blob, clone, B, need, txt, typeInto, clickOn,
// popup, tick, pressAdd and the rest are in scope.
const EM_DASH = String.fromCharCode(0x2014);

// One of every case the library can be in. Each material is bought in gallons (item.unit) on purpose: the
// unit the row takes must come from the COVERAGE BASIS, never from the pack.
const MATS = [
  { id: "u-sf",   name: "SF Floor Coat",   unit: "Gal", buy_qty: 1, unit_cost: 50,  coverage: 100, coverage_basis: "sf" },
  { id: "u-lf",   name: "LF Cove Coat",    unit: "Gal", buy_qty: 1, unit_cost: 100, coverage: 50,  coverage_basis: "lf" },
  { id: "u-none", name: "Unset Coat",      unit: "Gal", buy_qty: 1, unit_cost: 50,  coverage: 100, coverage_basis: null },
  { id: "u-each", name: "Counted Coat",    unit: "Gal", buy_qty: 1, unit_cost: 50,  coverage: 100, coverage_basis: "each" },
  { id: "u-d1",   name: "Twin Coat",       unit: "Gal", buy_qty: 1, unit_cost: 50,  coverage: 100, coverage_basis: "sf" },
  { id: "u-d2",   name: "Twin Coat Cove",  unit: "Gal", buy_qty: 1, unit_cost: 50,  coverage: 100, coverage_basis: "lf" },
];
const ASMS2 = [
  { id: "x-lf",   name: "LF Cove System",   unit: "LF", lines: [{ item_id: "u-lf", coverage: 50, waste_pct: 0, roundup: true }] },
  { id: "x-sf",   name: "SF Floor System",  unit: "SF", lines: [{ item_id: "u-sf", coverage: 100, waste_pct: 0, roundup: true }] },
  { id: "x-none", name: "Unset System",     unit: "",   lines: [{ item_id: "u-sf", coverage: 100, waste_pct: 0, roundup: true }] },
];
const TWIN_ASMS = ASMS2.concat([
  { id: "x-t1", name: "Twin System", unit: "SF", lines: [{ item_id: "u-sf", coverage: 100, waste_pct: 0, roundup: true }] },
  { id: "x-t2", name: "Twin System", unit: "LF", lines: [{ item_id: "u-lf", coverage: 50, waste_pct: 0, roundup: true }] },
]);
const TWIN_MATS = MATS.concat([
  { id: "u-t1", name: "Twin Material", unit: "Gal", buy_qty: 1, unit_cost: 50, coverage: 100, coverage_basis: "sf" },
  { id: "u-t2", name: "Twin Material", unit: "Gal", buy_qty: 1, unit_cost: 50, coverage: 100, coverage_basis: "lf" },
]);

const BLANK = { kind: "new", pick_name: "", measurement: "", unit: "SF" };
function withTakeoff(rows) {
  const m = clone(MODEL);
  m.takeoff = clone(rows);
  return blob({ polish_estimate: m });
}
async function open(rows, over) {
  const b = build(Object.assign({ items: TWIN_MATS, asms: TWIN_ASMS, blob: withTakeoff(rows) }, over || {}));
  await b.api.init();
  b.api.go(0);
  return b;
}
/** What a row's Unit field shows and says, read off the page. */
function face(b, i) {
  const box = b.doc.querySelector('[data-unit-for="' + i + '"]');
  const hint = b.doc.querySelector('[data-unithint-for="' + i + '"]');
  return { text: box ? box.textContent : null, boxTag: box ? box.tag : null,
           hint: hint ? hint.textContent : null,
           note: hint ? /(^| )note( |$)/.test(hint.className || hint.attrs["class"] || "") : null,
           href: hint ? hint.attrs.href : null,
           model: (b.api.model().takeoff[i] || {}).unit };
}
const NAMES = { "u-sf": "SF Floor Coat", "u-lf": "LF Cove Coat", "u-none": "Unset Coat", "u-each": "Counted Coat",
                "x-lf": "LF Cove System", "x-sf": "SF Floor System", "x-none": "Unset System" };

(async function () {
  const out = {};

  // ── 1. THE ROW'S OWN SEARCH: each case of library row, typed into an undecided row ──────────────
  out.search = {};
  for (const id of Object.keys(NAMES)) {
    const b = await open([BLANK]);
    typeInto(b, '[data-tk="0"][data-k="pick"]', NAMES[id]);
    typeInto(b, '[data-tk="0"][data-k="measurement"]', "200");
    out.search[id] = face(b, 0);
  }

  // ── 2. THE ADD-LINE POP-UP: the same six, ticked ───────────────────────────────────────────────
  out.popup = {};
  for (const id of Object.keys(NAMES)) {
    const b = await open([BLANK]);
    clickOn(b, "[data-add-row]");
    tick(b, (id.charAt(0) === "x" ? "asm:" : "item:") + id);
    pressAdd(b);
    const last = b.api.model().takeoff.length - 1;
    out.popup[id] = face(b, last);
  }

  // ── 3. PRICED PER LF: an LF material measured at 200 is 200 LF, and 4 gallons at 50 LF a gallon ─
  {
    const b = await open([BLANK]);
    typeInto(b, '[data-tk="0"][data-k="pick"]', "LF Cove Coat");
    typeInto(b, '[data-tk="0"][data-k="measurement"]', "200");
    out.pricedPerLf = { unit: b.api.model().takeoff[0].unit,
                        lf: B.takeoffLf(b.api.model().takeoff), sf: B.takeoffSf(b.api.model().takeoff),
                        cost: txt(b, '[data-cost-for="0"]'), perUnit: txt(b, '[data-perunit-for="0"]') };
    const s = await open([BLANK]);
    typeInto(s, '[data-tk="0"][data-k="pick"]', "SF Floor Coat");
    typeInto(s, '[data-tk="0"][data-k="measurement"]', "200");
    out.pricedPerSf = { unit: s.api.model().takeoff[0].unit,
                        lf: B.takeoffLf(s.api.model().takeoff), sf: B.takeoffSf(s.api.model().takeoff),
                        cost: txt(s, '[data-cost-for="0"]'), perUnit: txt(s, '[data-perunit-for="0"]') };
  }

  // ── 4. NOTHING PICKED YET ──────────────────────────────────────────────────────────────────────
  {
    const b = await open([BLANK]);
    out.noPick = face(b, 0);
  }

  // ── 5. THE CONTROL IS NOT EDITABLE ────────────────────────────────────────────────────────────
  {
    const b = await open([BLANK]);
    typeInto(b, '[data-tk="0"][data-k="pick"]', "LF Cove Coat");
    out.control = { selects: b.doc.querySelectorAll('select[data-tk="0"]').length,
                    unitInputs: b.doc.querySelectorAll('[data-tk="0"][data-k="unit"]').length,
                    tag: face(b, 0).boxTag };
    // a stray change event aimed at a unit (an old bookmarked tab, a script) must not move the row
    b.doc.fire("change", { target: { getAttribute: (k) => ({ "data-tk": "0", "data-k": "unit" }[k] || null),
                                     matches: () => false, closest: () => null, value: "SF" } });
    out.control.unitAfterStrayChange = b.api.model().takeoff[0].unit;
  }

  // ── 6. SAVED BIDS: the saved unit is kept, a differing one says so, and nothing is repriced ────
  {
    const saved = [
      { kind: "item", item_id: "u-lf", item_name: "LF Cove Coat", coverage: "", measurement: 200, unit: "SF" },
      { assembly_id: "x-lf", assembly_name: "LF Cove System", measurement: 200, unit: "SF" },
      { kind: "item", item_id: "u-sf", item_name: "SF Floor Coat", coverage: "", measurement: 5000, unit: "SF" },
      { assembly_id: "x-sf", assembly_name: "SF Floor System", measurement: 5000, unit: "LF" },
      { assembly_id: "x-none", assembly_name: "Unset System", measurement: 100, unit: "LF" },
    ];
    const plain = await open(saved);
    const rows = saved.map((r, i) => face(plain, i));
    const modelUnits = plain.api.model().takeoff.map((r) => r.unit);
    // re-typing the same name on a saved row must not re-stamp it
    typeInto(plain, '[data-tk="0"][data-k="pick"]', "LF Cove Coat");
    const afterRetype = plain.api.model().takeoff[0].unit;
    // and a row that does change its pick follows the library
    typeInto(plain, '[data-tk="2"][data-k="pick"]', "LF Cove Coat");
    const afterNewPick = face(plain, 2);
    out.saved = { rows: rows, modelUnits: modelUnits, afterRetype: afterRetype, afterNewPick: afterNewPick };
  }

  // ── 7. A NEW BID'S DEFAULTS: a favorite material takes its coverage basis ────────────────────────
  {
    const items = MATS.map((m) => Object.assign({}, m, { favorite: true }));
    const rows = B.seedDefaultTakeoff([clone(BLANK)], [], items, [], 5000, 0, "polish");
    out.seeded = rows.map((r) => ({ id: r.item_id, unit: r.unit, measurement: r.measurement }));
  }

  // ── 8. TWO LIBRARY ROWS OF ONE NAME: the pop-up gives each the unit of the one that was ticked ──
  {
    const b = await open([BLANK]);
    clickOn(b, "[data-add-row]");
    tick(b, "item:u-t1"); tick(b, "item:u-t2"); tick(b, "asm:x-t1"); tick(b, "asm:x-t2");
    pressAdd(b);
    out.twins = b.api.model().takeoff.map((r) => ({ id: r.item_id || r.assembly_id, unit: r.unit }))
      .filter((r) => /^(u-t|x-t)/.test(r.id));
  }

  // ── 9. A ROW CHANGING ITS PICK: the box repaints in place and a re-type changes nothing ─────────
  {
    const b = await open([BLANK]);
    typeInto(b, '[data-tk="0"][data-k="pick"]', "LF Cove Coat");
    const first = face(b, 0);
    typeInto(b, '[data-tk="0"][data-k="pick"]', "LF Cove Coat");
    const same = face(b, 0);
    typeInto(b, '[data-tk="0"][data-k="pick"]', "SF Floor Coat");
    const second = face(b, 0);
    typeInto(b, '[data-tk="0"][data-k="pick"]', "LF Cove System");
    const third = face(b, 0);
    out.repick = { first: first, same: same, second: second, third: third };
  }

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
`;

const m = new Module(BASE, module);
m.filename = BASE;
m.paths = Module._nodeModulePaths(path.dirname(BASE));
m._compile(head + SCENARIOS, BASE);
