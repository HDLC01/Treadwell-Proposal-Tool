// The Labor step's "how this is worked out" note, run on the real engine (bid-model.js).
// Two wording cases the staging review found: a far job with Travel Labor switched off, and the
// note after the miles are cleared while the seeded drive hours stay priced.
const path = require("path");
const B = require(path.join(process.argv[2], "js", "bid-model.js"));

function far(miles) {
  const M = B.freshModel();
  M.labor[0].guys = 3; M.labor[0].days = 5;
  B.applyDistance(M, { miles: miles, source: "typed" });
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

console.log(JSON.stringify({
  travelOff: { text: offHow.text, hand: offHow.hand },
  cleared: { text: clearedHow.text },
  withMiles: { text: stillHow.text },
}));
