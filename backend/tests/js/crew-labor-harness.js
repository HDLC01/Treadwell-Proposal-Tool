"use strict";
/* Runs the REAL bid-model.js: the shipped crew fallback, the old four rows, the sheet's order. */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));
const ids = (rows) => rows.map((r) => r.id);
const flat = (rows) => rows.map((r) => [r.id, r.label, r.guys, r.days, r.rate]);
const out = {};
out.rows = B.shippedCrewRows();
out.calc = B.shippedCrewCalc();
out.legacy = flat(B.legacyLabor());
out.fresh = flat(B.freshModel().labor);
const travel = { id: "travel", name: "Travel Labor", rate: 33, unit: "hours", favorite: true };
const added = (rows) => ["travel"].concat(ids(rows).filter((i) => i !== "travel"));
// no crew line listed at all: the library cannot answer, so the shipped three are added
out.fallbackWhenNoneListed = added(B.withCrewFallback([travel]));
// ONE crew line listed (even unfavorited) means the library answered: nothing is added back
out.fallbackWhenOneListed = added(B.withCrewFallback([travel, { id: "polishing", favorite: false }]));
out.crewFirst = ids(B.crewFirst([{ id: "c1" }, { id: "travel" }, { id: "jointfill" },
  { id: "polishing" }, { id: "mockup" }]));
console.log(JSON.stringify(out));
