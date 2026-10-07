"use strict";
/* Runs the REAL bid-model.js: Travel follows the library row's favorite + work types. */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));
function ids(rows) { return rows.map(function (r) { return r.id; }); }
function seed(rows, wt) { return ids(B.seedLibraryLabor(B.freshModel().labor, rows, undefined, wt)); }
const T = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true };
const out = {};
out.noRow = seed([]);
out.noRowAtAll = seed(null);
out.absentFavorite = seed([Object.assign({}, T)]);
out.nullFavorite = seed([Object.assign({}, T, { favorite: null, default_work_types: [] })]);
out.favoriteTrue = seed([Object.assign({}, T, { favorite: true })]);
out.removed = seed([Object.assign({}, T, { favorite: false })]);
out.scopedPolish = seed([Object.assign({}, T, { favorite: true, default_work_types: ["epoxy", "polish"] })]);
out.scopedEpoxy = seed([Object.assign({}, T, { favorite: true, default_work_types: ["epoxy"] })]);
out.scopedEpoxyBidIsEpoxy = seed([Object.assign({}, T, { favorite: true, default_work_types: ["epoxy"] })], "epoxy");
out.customScopedElsewhere = seed([
  { id: "c1", name: "C1", rate: 40, unit: "days", favorite: true, default_work_types: ["epoxy"] },
  { id: "c2", name: "C2", rate: 40, unit: "days", favorite: true, default_work_types: [] }]);
out.declined = {
  removed: B.travelDeclined([Object.assign({}, T, { favorite: false })], "polish"),
  scoped: B.travelDeclined([Object.assign({}, T, { favorite: true, default_work_types: ["gyp"] })], "polish"),
  absent: B.travelDeclined([Object.assign({}, T)], "polish"),
  noRow: B.travelDeclined([], "polish"),
};
// The marker keeps a reload from appending Travel back; a saved bid WITHOUT it still gets it.
const m = B.freshModel();
m.labor = B.seedLibraryLabor(m.labor, [Object.assign({}, T, { favorite: false })], undefined, "polish");
m.no_travel_labor = true;
const reloaded = B.migrateModel(JSON.parse(JSON.stringify(m)));
out.reloadKeepsItOff = ids(reloaded.labor);
out.reloadMarker = reloaded.no_travel_labor === true;
const stale = B.freshModel();
stale.labor = stale.labor.filter(function (r) { return r.id !== "travel"; });
out.staleDraftStillBackfilled = ids(B.migrateModel(JSON.parse(JSON.stringify(stale))).labor);
console.log(JSON.stringify(out));
