"use strict";
/* The on/off slider's arithmetic, out of the REAL frontend/js/bid-model.js. One line of JSON.
 *
 * A row switched off (`enabled: false`) must add $0 BEFORE the chain rounds (D31 and D45 are
 * ROUNDUPs of the raw sums), must drop out of Travel's man-days, must not block Review, and a
 * library default saved OFF must seed the bid's row switched off. Every claim is proved by
 * comparing against the bid of a model that never had the row at all. */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));

const crew = [
  { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33.1 },
  { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33.1 },
  { id: "extra", label: "Extra", guys: 2, days: 1.3, rate: 41.77 },
];
const off = (rows, i) => rows.map((r, k) => (k === i ? Object.assign({}, r, { enabled: false }) : r));
const gone = (rows, i) => rows.filter((_, k) => k !== i);
const chain = (labor, takeoff) => B.markupChain({
  material: 1234.5678, labor: B.laborTotal(labor), contingency: 0, fees: 0,
  conditions: { local: true, taxable: true }, sf: B.takeoffSf(takeoff), remodel_rate: null });

const tk = [{ assembly_id: "a", measurement: 1000, unit: "SF" },
            { assembly_id: "b", measurement: 333.3, unit: "SF" }];
const tkOff = tk.map((r, i) => (i === 1 ? Object.assign({}, r, { enabled: false }) : r));

const seeded = B.seedLibraryLabor(B.freshModel().labor, [
  { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, favorite: true,
    default_on: false },
  { id: "l1", name: "Grinding", rate: 40, unit: "days", favorite: true, default_on: false },
  { id: "l2", name: "Sealing", rate: 40, unit: "days", favorite: true, default_on: true },
  { id: "l3", name: "Old row", rate: 40, unit: "days", favorite: true },     // column absent
]);
const byId = (id) => seeded.filter((r) => r.id === id)[0];

const trv = [{ id: "polishing", guys: 3, days: 5 }, { id: "mockup", guys: 3, days: 0.5 },
             { id: "travel", unit: "hours", guys: "", days: 2, guys_auto: true }];

const model = (labor, takeoff) => Object.assign(B.freshModel(), { labor: labor, takeoff: takeoff });
const rowOnly = [{ assembly_id: "a", assembly_name: "A", measurement: 500, unit: "SF" }];

console.log(JSON.stringify({
  costOff: B.laborCost({ guys: 3, days: 5, rate: 33, enabled: false }),
  costAbsentIsOn: B.laborCost({ guys: 3, days: 5, rate: 33 }),
  costTrueIsOn: B.laborCost({ guys: 3, days: 5, rate: 33, enabled: true }),
  // Skipped BEFORE rounding: the whole chain equals the chain of the model without the row.
  chainOff: chain(off(crew, 2), tk), chainGone: chain(gone(crew, 2), tk),
  chainOnAllRows: chain(crew, tk), chainWith: chain(off(crew, 0), tk),
  chainWithout0: chain(gone(crew, 0), tk),
  // Zeroing AFTER the rounding would differ: prove the two are not the same number.
  roundedAfterWouldBe: B.roundUp(B.laborTotal(crew), 0) - B.laborCost(crew[2]),
  roundedBefore: B.roundUp(B.laborTotal(gone(crew, 2)), 0),
  areaOff: B.takeoffSf(tkOff), areaGone: B.takeoffSf(tk.slice(0, 1)),
  manDays: B.travelManDays(trv), manDaysOff: B.travelManDays(off(trv, 0)),
  manDaysGone: B.travelManDays(gone(trv, 0)),
  // Blockers: a half-filled row that is OFF must not stop Review; ON it must.
  blockedOn: B.blockers(model([{ id: "x", label: "Half", guys: 2, days: "", rate: 33 }], rowOnly)),
  blockedOff: B.blockers(model([{ id: "x", label: "Half", guys: 2, days: "", rate: 33,
                                  enabled: false }], rowOnly)),
  blockedTakeoffOff: B.blockers(model(crew, [Object.assign({}, rowOnly[0], { enabled: false })])),
  // Seeding: default_on false -> enabled:false; true and absent -> no key at all.
  seedTravelOff: byId("travel").enabled, seedL1Off: byId("l1").enabled,
  seedL2HasKey: "enabled" in byId("l2"), seedL3HasKey: "enabled" in byId("l3"),
  // The shared component.
  slider: B.sliderHtml(true, 'data-x="1"', "Hi <b>", "T\"t"),
  sliderOff: B.sliderHtml(false, 'data-x="1"', "Hi"),
  rowOn: [B.rowOn({}), B.rowOn({ enabled: true }), B.rowOn({ enabled: false }), B.rowOn(null)],
}));
