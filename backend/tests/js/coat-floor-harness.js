"use strict";
/* A COAT TYPED THE FLOOR'S OWN NUMBER STAYS ON THAT FLOOR (2026-10-16).
 *
 *   node coat-floor-harness.js <frontend dir>
 *
 * Drives js/bid-model.js setMeasurement the way the estimate page does (one input event a keystroke, through the
 * same call the page's input handler makes) and reports what takeoffSf counts and what each row holds afterwards.
 */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));

const typeInto = (rows, i, text) => { B.setMeasurement(rows, i, ""); let v = ""; for (const ch of String(text)) { v += ch; B.setMeasurement(rows, i, v); } };
const snap = (rows) => ({ sf: B.takeoffSf(rows), rows: JSON.parse(JSON.stringify(rows)) });
const out = {};

// the job the re-check found: a flake floor, a cove, a primer added beside the floor (so it carries it)
const epoxy = () => [
  { unit: "SF", measurement: "5482", assembly_id: "flake" },
  { unit: "LF", measurement: "562", assembly_id: "cove" },
  { unit: "SF", measurement: "5482", same_floor: true, assembly_id: "wb" },
];
let r = epoxy(); typeInto(r, 2, "5482"); out.retyped = snap(r);
r = epoxy(); typeInto(r, 2, "3000"); out.other = snap(r);
typeInto(r, 2, "5482"); out.backToFloor = snap(r);
r = epoxy(); typeInto(r, 2, "3000"); typeInto(r, 0, "3000"); out.floorMovedToIt = snap(r);
r = epoxy(); typeInto(r, 2, "3000"); typeInto(r, 2, "0"); out.zero = snap(r);

// two rooms of one size, neither ever a coat of the other: two floors, always
r = [{ unit: "SF", measurement: "2000" }, { unit: "SF", measurement: "" }];
typeInto(r, 1, "2000"); out.twoRooms = snap(r);

// two areas (System 1 and System 2): a coat of area 2 rejoins area 2, never area 1, even where the numbers allow it
const areas = () => [
  { unit: "SF", measurement: "4000", floor_area: 1, assembly_id: "s1" },
  { unit: "SF", measurement: "2500", floor_area: 2, assembly_id: "s2" },
  { unit: "SF", measurement: "2500", same_floor: true, same_floor_of: 2, assembly_id: "primer2" },
];
r = areas(); typeInto(r, 2, "2500"); out.area2Retyped = snap(r);
r = areas(); typeInto(r, 2, "4000"); out.area2TypedArea1Number = snap(r);

// a unit change forgets the coat's floor, as it forgets every other floor mark
r = epoxy(); typeInto(r, 2, "3000"); B.adoptTakeoffUnit(r, 2, "LF"); out.unitChanged = snap(r);

console.log(JSON.stringify(out));
