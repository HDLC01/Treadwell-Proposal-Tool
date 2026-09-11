"use strict";
/* Execute the real applyHeuristics() + the real txAddr() struct-op translation out of
 * estimate-review.js.
 *
 * Kyle, on WhatsApp: "There's some sort of bug because when I went back to the estimate sheet it
 * changed all of my numbers and I can't get it to reset." / "Changed the labor somehow."
 *
 * ROOT CAUSE. applyHeuristics wrote Epoxy!A47/B47/C47 (crew, days, hourly rate) as raw literal
 * template addresses -- the one coordinate-dependent read/write in this file that skipped
 * txAddr, which every sibling function (totalCellsFor, sfFieldsFor, the struct-op rekeying
 * itself) already goes through. Its blank-check (`cellValues[addr] === undefined`) runs inside
 * autofillFromIntake's IIFE, which fires on EVERY load of Estimate Review, not just the first.
 * So once a row/column insert or delete on Epoxy moved the real labor cells somewhere else, the
 * OLD address kept reading as "blank" forever and the heuristic silently reseeded a fresh
 * SF-derived crew/days/rate value into whatever unrelated cell now occupied it -- on every single
 * revisit ("can't get it to reset"), with the wrong value cascading through the sheet's totals
 * ("changed all of my numbers").
 *
 * WHY EXECUTED. txAddr's index math (_shiftIdx, insert vs delete, returning null for a deleted
 * coordinate) is exactly the kind of off-by-one a source read glosses over, and the fix's
 * correctness hinges on it doing the right thing, not merely on "some txAddr call was added".
 * Both txAddr and applyHeuristics are lifted verbatim out of the shipped file and run for real,
 * the same way markup-rate-harness.js and taxable-flag-harness.js run their coordinate-dependent
 * writers instead of trusting a re-implementation of the shift math.
 *
 * Usage: node kyle2-labor-heuristic-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
// Normalised on read: git hands this file out with CRLF on a Windows checkout and LF in CI, and
// the `[\s\S]*?\n\}` lift below is anchored on a bare \n.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const SRC = read(path.join(ROOT, "js", "estimate-review.js"));
const NL = String.fromCharCode(10);

function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + what + " -- rewrite this harness, don't stub it");
  return m[0];
}

/** Lift one top-level `function name(...) {...}` out of estimate-review.js and bind `deps` into
 *  it BY NAME. A callee missing from deps at lift time is an unbound identifier inside the copy,
 *  so the order of the lifts below is load-bearing. */
function lift(name, deps) {
  const re = new RegExp("^(?:async )?function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name);
  const names = Object.keys(deps);
  return new Function(...names, m[0] + NL + "return " + name + ";")(...names.map(k => deps[k]));
}

/** Same, but for a one-line `function name(...) { return ...; }` body (structOpsFor is defined
 *  on one line, not the multi-line `\n}`-anchored shape `lift` expects). */
function liftOneLiner(name, deps) {
  const re = new RegExp("^function " + name + "\\([^)]*\\) \\{.*\\}$", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name);
  const names = Object.keys(deps);
  return new Function(...names, m[0] + NL + "return " + name + ";")(...names.map(k => deps[k]));
}

function harness(opts) {
  opts = opts || {};
  const state = { tab_structs: opts.tabStructs || [] };
  const deps = { state };
  deps._shiftIdx = lift("_shiftIdx", deps);
  deps.structOpsFor = liftOneLiner("structOpsFor", deps);
  deps.txAddr = lift("txAddr", deps);
  deps.applyHeuristics = lift("applyHeuristics", deps);

  const cellValues = Object.assign({}, opts.cellValues || {});
  const putIfBlank = (addr, val) => { if (cellValues[addr] === undefined) cellValues[addr] = val; };

  return {
    cellValues,
    run(intake) { deps.applyHeuristics(intake, putIfBlank); },
  };
}

const out = {};

// ── 1. no struct ops: unchanged behaviour on the plain template addresses ───────────────────
{
  const h = harness({});
  h.run({ work_type: "epoxy", system_1_sf: 8000, cell_values: {} });
  out.noStructOps = {
    a47: h.cellValues["Epoxy!A47"], b47: h.cellValues["Epoxy!B47"], c47: h.cellValues["Epoxy!C47"],
  };
}

// ── 2. THE INCIDENT: two rows inserted above the labor block -> A47/B47/C47 are now A49/B49/C49.
// A cell that legitimately moved INTO the vacated Epoxy!A47 (e.g. the estimator's own edit at
// what is now row 47) must survive untouched -- the pre-fix bug clobbered exactly this cell.
{
  const tabStructs = [{ sheet: "Epoxy", kind: "insert_rows", at: 20, count: 2 }];
  const survivorAtOldAddress = { "Epoxy!A47": "DO NOT TOUCH -- real data now at this address" };
  const h = harness({ tabStructs, cellValues: survivorAtOldAddress });
  h.run({ work_type: "epoxy", system_1_sf: 8000, cell_values: {} });
  out.rowsInserted = {
    oldA47Untouched: h.cellValues["Epoxy!A47"],
    oldB47StillBlank: h.cellValues["Epoxy!B47"],
    oldC47StillBlank: h.cellValues["Epoxy!C47"],
    newA49: h.cellValues["Epoxy!A49"],
    newB49: h.cellValues["Epoxy!B49"],
    newC49: h.cellValues["Epoxy!C49"],
  };
}

// ── 3. a column inserted at column 1 shifts A47->B47, C47(rate)->D47, AND the D5 prevailing-wage
// read has to follow the same shift (D5 -> E5) or the rate heuristic picks the wrong default.
{
  const tabStructs = [{ sheet: "Epoxy", kind: "insert_cols", at: 1, count: 1 }];
  const cell_values = { "Epoxy!E5": "Yes" };   // PW flag, already at its post-shift address
  const h = harness({ tabStructs, cellValues: { "Epoxy!E5": "Yes" } });
  h.run({ work_type: "epoxy", system_1_sf: 8000, cell_values });
  out.colInserted = {
    b47: h.cellValues["Epoxy!B47"], c47: h.cellValues["Epoxy!C47"],
    laborRate: h.cellValues["Epoxy!D47"],   // old C47, PW should select 48.00 not the 33.00 default
  };
}

// ── 4. the labor row is deleted outright -> txAddr returns null -> the write is skipped
// entirely, rather than landing at a stale address nobody will ever look at again.
{
  const tabStructs = [{ sheet: "Epoxy", kind: "delete_rows", at: 47, count: 1 }];
  const h = harness({ tabStructs, cellValues: {} });
  h.run({ work_type: "epoxy", system_1_sf: 8000, cell_values: {} });
  out.rowDeleted = { writtenAnywhere: Object.keys(h.cellValues) };
}

// ── 5. gyp jobs are still skipped entirely regardless of struct ops (unchanged guard) ────────
{
  const tabStructs = [{ sheet: "Epoxy", kind: "insert_rows", at: 20, count: 2 }];
  const h = harness({ tabStructs, cellValues: {} });
  h.run({ work_type: "gyp", system_1_sf: 8000, cell_values: {} });
  out.gypSkipped = { writtenAnywhere: Object.keys(h.cellValues) };
}

process.stdout.write(JSON.stringify(out) + NL);
