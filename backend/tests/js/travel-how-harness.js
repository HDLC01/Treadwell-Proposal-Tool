// The Labor step's "how this is worked out" note, run on the real engine (bid-model.js).
// Two wording cases the staging review found: a far job with Travel Labor switched off, and the
// note after the miles are cleared while the seeded drive hours stay priced (a bid saved while the
// distance still wrote the hours).
const path = require("path");
const B = require(path.join(process.argv[2], "js", "bid-model.js"));

function far(miles) {
  const M = B.freshModel();
  M.labor[0].guys = 3; M.labor[0].days = 5;
  B.applyDistance(M, { miles: miles, source: "typed" });
  // The distance no longer fills the drive hours (2026-10-12). What this note still has to word is a
  // bid SAVED while it did: 5 hours carrying the old `hours_seed` marker.
  M.labor.forEach((r) => { if (r.id === "travel") { r.days = 5; r.hours_seed = 5; } });
  return M;
}

const off = far(150);
off.labor.forEach((r) => { if (r.id === "travel") r.enabled = false; });
const offHow = B.travelHow(off);

const cleared = far(150);
B.clearDistance(cleared);
const clearedHow = B.travelHow(cleared);

const still = far(150);
const stillHow = B.travelHow(still);

// A bid priced by Polish rev 2 counts auto Lodging and Per Diem the sheet's way (from labor dollars), so a crew with a
// prevailing-wage row owes more nights than it has man-days. The note has to say what the cost box and the bid charge.
function mixed(profile) {
  const M = B.freshModel();
  if (profile) M.profile = profile;
  M.takeoff = [{ assembly_id: "a", assembly_name: "Polish - S&P", measurement: 10000, unit: "SF" }];
  M.labor = [{ id: "a", label: "A", guys: 2, days: 5, rate: 33 }, { id: "b", label: "B", guys: 2, days: 5, rate: 66 }];
  M.travel = { lodging: { enabled: true, qty_auto: true, rate: 100 }, per_diem: { enabled: true, qty_auto: true, rate: 50 } };
  return M;
}
const rev2 = mixed("polish-rev2@1"), legacy = mixed();
const rev2Charge = B.travelCosts(rev2.travel, rev2.labor, B.travelOpts(rev2, B.ROOT_TAB));
const legacyCharge = B.travelCosts(legacy.travel, legacy.labor, B.travelOpts(legacy, B.ROOT_TAB));

console.log(JSON.stringify({
  rev2: { lines: B.travelHow(rev2).lines, charge: rev2Charge },
  legacy: { lines: B.travelHow(legacy).lines, charge: legacyCharge },
  travelOff: { text: offHow.text, hand: offHow.hand },
  cleared: { text: clearedHow.text },
  withMiles: { text: stillHow.text },
}));
