"use strict";
/* Runs the REAL bid-model.js: a distance answer decides local or far and fills NO hours (Hanz, 2026-10-12). */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));
function trv(m) { return m.labor.filter(function (r) { return r.id === "travel"; })[0]; }
const out = {};
// A shipped model at 150 miles: the three lines come on, and Travel Labor's Hours stay empty.
const a = B.freshModel(); B.applyDistance(a, { miles: 150, source: "typed", key: "" });
out.newAt150 = { hours: trv(a).days, local: a.conditions.local, lodging: a.travel.lodging.enabled,
                 perDiem: a.travel.per_diem.enabled };
// ...at a further distance still empty; hours TYPED by the estimator are theirs and stay.
B.applyDistance(a, { miles: 200, source: "typed", key: "" });
out.stillEmptyAt200 = trv(a).days;
trv(a).days = 3; B.applyDistance(a, { miles: 300, source: "typed", key: "" });
out.typedStays = trv(a).days;
const l = B.freshModel(); B.applyDistance(l, { miles: 30, source: "typed", key: "" });
out.localHours = trv(l).days;
const b = B.freshModel(); B.applyDistance(b, { miles: 150, source: "typed", key: "" });
B.applyDistance(b, { miles: 20, source: "typed", key: "" });
out.backToLocal = trv(b).days;
// A bid saved while the distance still wrote the hours carries its figure and the old marker; a new
// distance answer leaves that figure exactly as saved.
const s = B.freshModel(); trv(s).days = 5; trv(s).hours_seed = 5;
B.applyDistance(s, { miles: 300, source: "typed", key: "" });
out.savedKeepsItsHours = trv(s).days;
// The same through the pricing: with the crew typed and no hours, Travel Labor is $0 until hours are typed.
function priced(m) {
  m.labor[0].days = 5;                 // 3 guys x 5 days polishing -> 15 man-days
  m.labor.forEach(function (r) { if (r.id === "travel") r.guys = B.travelManDays(m.labor); });
  return B.laborCost(trv(m));
}
const p = B.freshModel(); B.applyDistance(p, { miles: 150, source: "typed", key: "" });
out.costWithNoHours = priced(p);
trv(p).days = 5;
out.costWithTypedHours = B.laborCost(trv(p));
console.log(JSON.stringify(out));
