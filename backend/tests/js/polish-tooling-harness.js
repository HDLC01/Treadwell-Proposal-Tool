"use strict";
/* The model's Polish tooling (bid-model.js polishTooling), set beside what Kyle's Polish tab charged for the same
 * job, as backend/tests/fixtures/polish_tooling_oracle.json recorded it.
 *
 *   node polish-tooling-harness.js [<frontend dir>]
 *
 * For every recorded case (a square footage, linear footage, Dye, New or Reno, polish system and kind) this runs the
 * model and compares each line the tab has: the rate (C51), tooling and consumables (D51), demo tooling (D52),
 * slurry hardener (D53), plastic (D54) and the total (D55). They must be EQUAL to the cent. The one case that is
 * not is a bid with no area at all, where the sheet charges its $150 minimum and the model charges nothing (see
 * polishTooling); it is counted apart and has to differ.
 *
 * It also reads what the root of a MODEL charges (rootTooling): the sheet's figure for a bid stamped
 * polish-rev2@1, and nothing for every other, and what polishSystemOf makes of an assembly's name.
 * Prints, as its last line, one JSON object the test reads. <frontend dir> defaults to this repository's frontend;
 * the test hands it a copy with the model deliberately broken to watch this go red.
 */
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const REPO = path.resolve(HERE, "..", "..", "..");
const FRONTEND = process.argv[2] ? path.resolve(process.argv[2]) : path.join(REPO, "frontend");
const M = require(path.join(FRONTEND, "js", "bid-model.js"));
const golden = JSON.parse(fs.readFileSync(path.join(HERE, "..", "fixtures", "polish_tooling_oracle.json"), "utf8"));

const out = { cases: golden.cases.length, exact: 0, noArea: { cases: 0, sheetMinimum: 0, modelCharges: 0 }, mismatches: [], seen: {} };
const lines = [["rate", "C51", true], ["consumables", "D51"], ["demo", "D52"], ["slurry", "D53"], ["plastic", "D54"], ["total", "D55"]];

for (const c of golden.cases) {
  const got = M.polishTooling(c.in.sf, c.in.lf, {
    dye: c.in.dye, reno: c.in.reno, system: c.in.system === "S&P" ? "sp" : c.in.system, traditional: c.in.traditional,
  });
  if (c.in.sf === 0) {
    out.noArea.cases++;
    if (c.out.D51 === 150) out.noArea.sheetMinimum++;
    if (got.total !== 0) out.noArea.modelCharges++;
    continue;
  }
  const bad = [];
  for (const [mine, cell, isRate] of lines) {
    const want = c.out[cell];
    const ok = isRate ? Math.abs(got[mine] - want) < 1e-9 : got[mine] === want;
    if (!ok) bad.push({ line: mine, cell: cell, sheet: want, model: got[mine] });
  }
  if (bad.length) { if (out.mismatches.length < 12) out.mismatches.push({ in: c.in, bad: bad }); out.bad = (out.bad || 0) + 1; }
  else out.exact++;
  // which lines of the tab were actually in play (a line that no case moves is a line nothing checks)
  if (c.out.D51 > 150) out.seen.consumablesAboveMinimum = (out.seen.consumablesAboveMinimum || 0) + 1;
  if (c.out.D51 === 150) out.seen.consumablesAtMinimum = (out.seen.consumablesAtMinimum || 0) + 1;
  if (c.out.D53 > 0) out.seen.slurry = (out.seen.slurry || 0) + 1;
  if (c.out.D54 > 0) out.seen.plastic = (out.seen.plastic || 0) + 1;
  if (c.in.reno && !c.in.dye && c.in.sf > 4999 && c.out.D54 > 0) out.seen.plasticRenoLegOnTheSheet = (out.seen.plasticRenoLegOnTheSheet || 0) + 1;
  if (c.in.reno && !c.in.dye && c.in.sf <= 4999 && c.out.D54 === 0) out.seen.plasticRenoLegIdleUnder5k = (out.seen.plasticRenoLegIdleUnder5k || 0) + 1;
}

// ── a model's root: the sheet's tooling for polish-rev2@1, nothing for every other ─────────────────────────────
const rows = (names, sf, lf) => names.map((n) => ({ assembly_id: "x", assembly_name: n, measurement: sf, unit: "SF" }))
  .concat(lf ? [{ assembly_id: "", assembly_name: "", measurement: lf, unit: "LF" }] : []);
function root(profile, takeoff, conditions) {
  const m = { version: 2, takeoff: takeoff, labor: [], conditions: Object.assign({ dye: false }, conditions || {}), contingency: 0, fees: 0 };
  if (profile !== undefined) m.profile = profile;
  return m;
}
const REV2 = "polish-rev2@1";
out.root = {
  rev2: M.rootTooling(root(REV2, rows(["Polish - S&P"], 10000))),
  rev2ByHand: M.polishTooling(10000, 0, { system: "sp" }).total,
  noStamp: M.rootTooling(root(undefined, rows(["Polish - S&P"], 10000))),
  legacyStamp: M.rootTooling(root("polish-legacy@1", rows(["Polish - S&P"], 10000))),
  // `polish@1` is the stamp a section of another build carried; the root does not read it
  otherStamp: M.rootTooling(root("polish@1", rows(["Polish - S&P"], 10000))),
  rev2NoArea: M.rootTooling(root(REV2, [])),
  rev2Dye: M.rootTooling(root(REV2, rows(["Polish - S&P"], 2000, 400), { dye: true })),
  rev2DyeByHand: M.polishTooling(2000, 400, { system: "sp", dye: true }).total,
  rev2OffRowIsNotArea: M.rootTooling(root(REV2, [{ assembly_id: "x", assembly_name: "Polish - S&P", measurement: 10000, unit: "SF", enabled: false }])),
  profileOfNothing: M.rootProfile({ version: 2 }).stamp,
  profileOfRev2: M.rootProfile({ version: 2, profile: REV2 }).stamp,
  profileOfJunk: M.rootProfile({ version: 2, profile: "polish-rev2@2" }).stamp,
  profileOfNull: M.rootProfile(null).stamp,
};
out.system = {
  none: M.polishSystemOf(rows(["Epoxy thing"], 10)),
  empty: M.polishSystemOf([]),
  cream: M.polishSystemOf(rows(["Polish - Cream"], 10)),
  sp: M.polishSystemOf(rows(["Polish - S&P"], 10)),
  salt: M.polishSystemOf(rows(["Salt and pepper polish"], 10)),
  aggregate: M.polishSystemOf(rows(["Polish - Large Aggregate"], 10)),
  firstNamedWins: M.polishSystemOf(rows(["Polish - Cream", "Polish - S&P"], 10)),
  traditional: M.polishSystemOf(rows(["Traditional S&P polish"], 10)),
  offRowIgnored: M.polishSystemOf([{ assembly_name: "Polish - Cream", measurement: 5, unit: "SF", enabled: false }, ...rows(["Polish - Large Aggregate"], 5)]),
};
console.log(JSON.stringify(out));
