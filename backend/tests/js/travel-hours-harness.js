"use strict";
/* Runs the REAL polish-bid-core.js: a new bid takes a distance answer, a saved bid does too. */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "polish-bid-core.js"));
function trv(m) { return m.labor.filter(function (r) { return r.id === "travel"; })[0]; }
function priced(m) {
  m.labor[0].days = 5;                 // 3 guys x 5 days polishing -> 15 man-days
  m.labor.forEach(function (r) { if (r.id === "travel") r.guys = B.travelManDays(m.labor); });
  return B.laborCost(trv(m));
}
const out = {};
const a = B.freshModel(); B.applyDistance(a, { miles: 150, source: "typed", key: "" });
out.newAt150 = { hours: trv(a).days, cost: priced(a) };
B.applyDistance(a, { miles: 200, source: "typed", key: "" });
out.followsDistance = trv(a).days;
trv(a).days = 3; B.applyDistance(a, { miles: 300, source: "typed", key: "" });
out.typedStays = trv(a).days;
const l = B.freshModel(); B.applyDistance(l, { miles: 30, source: "typed", key: "" });
out.localHours = trv(l).days;
const b = B.freshModel(); B.applyDistance(b, { miles: 150, source: "typed", key: "" });
B.applyDistance(b, { miles: 20, source: "typed", key: "" });
out.backToLocal = trv(b).days;
// a SAVED travel row (no hours_seed) is never filled
const s = B.freshModel(); delete trv(s).hours_seed;
B.applyDistance(s, { miles: 150, source: "typed", key: "" });
out.saved = trv(s).days;
console.log(JSON.stringify(out));
