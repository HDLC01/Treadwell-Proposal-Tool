"use strict";
/* Today's v2 Polish model, set beside Kyle's Polish tab as the oracle recorded it.
 *
 *   node oracle-polish-harness.js [<frontend dir>]
 *
 * For every Polish case in backend/tests/fixtures/oracle/polish.json this runs the model (markupChain,
 * and travelCosts for the lodging cases) on the same inputs, and compares every answer the two share.
 * They must be EQUAL, except where backend/tests/fixtures/oracle/departures.json says they differ, and
 * what it says is checked as hard as the rest:
 *
 *   - a departure with an `explain` is PREDICTED. The sheet's answer is rebuilt from the model plus exactly
 *     what the departure's reason says (tooling folded into the travel input; travel and tooling added to the
 *     remodel tax base) and that has to equal the oracle to the dollar;
 *   - a departure without one is excused only on the keys it lists, and only on cases where its
 *     `appliesWhen` holds;
 *   - every departure has to be SEEN: at least one case where it applies and the answers really differ on one
 *     of its keys. A departure nothing ever shows is not a departure, it is a comment.
 *
 * Prints, as its last line, one JSON object the test reads. <frontend dir> defaults to this repository's
 * frontend; the test hands it a copy with the model deliberately broken to watch this go red. The model file is
 * js/bid-model.js.
 */
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const REPO = path.resolve(HERE, "..", "..", "..");
const FRONTEND = process.argv[2] ? path.resolve(process.argv[2]) : path.join(REPO, "frontend");
const ORACLE = path.join(HERE, "..", "fixtures", "oracle");

const MODEL_FILE = path.join(FRONTEND, "js", "bid-model.js");
if (!fs.existsSync(MODEL_FILE)) throw new Error("no bid-model.js under " + FRONTEND);
const M = require(MODEL_FILE);
// ROUNDUP is js/excel-math.js's. The model re-exports that same function as M.roundUp, so this is the
// very one the model's own numbers come from.
const roundUp = M.roundUp;
const P = require(path.join(REPO, "frontend", "js", "bid-profiles.js"));
const golden = JSON.parse(fs.readFileSync(path.join(ORACLE, "polish.json"), "utf8"));
const dep = JSON.parse(fs.readFileSync(path.join(ORACLE, "departures.json"), "utf8"));

/** Does a departure's `appliesWhen` hold for this case? */
function holds(cond, v) {
  if (cond.allOf) return cond.allOf.every((c) => holds(c, v));
  if (cond.anyOf) return cond.anyOf.some((c) => holds(c, v));
  if (cond.in !== undefined) {
    const x = v.in[cond.in] === undefined ? 0 : v.in[cond.in];
    return "ne" in cond ? x !== cond.ne : x === cond.eq;
  }
  if (cond.answers !== undefined) {
    const x = v.out.answers[cond.answers];
    return "ne" in cond ? x !== cond.ne : x === cond.eq;
  }
  if (cond.out !== undefined) {
    const x = v.out[cond.out];
    return cond.nonzero ? (typeof x === "number" && x !== 0) : x === cond.eq;
  }
  if (cond.rows !== undefined) return new Set((v.rows || []).map((r) => r.rate)).size > 1;
  throw new Error("departures.json: a condition this harness does not know: " + JSON.stringify(cond));
}

// ── what a departure's reason means, as arithmetic ───────────────────────────
// Each explanation has two halves. `input` / `output` rebuild the SHEET's answer from the model's. `check` is
// the other half: it says what the model is doing today and fails when the model has stopped doing it, so a
// model that closes the gap cannot go unnoticed behind an explanation that quietly recomputes the answer.
const EXPLAIN = {
  // D64 adds D55 into the sub-total: the model's travel input is added the same way. The model is handed the
  // tooling too (modelInput), and ignores it today; one that starts reading it would count it twice and fail.
  "tooling-folds-into-travel": {
    input: (v, inp) => Object.assign({}, inp, { travel: inp.travel + (v.in.tooling || 0) }),
  },
  // D75 = ROUNDUP(SUM(D45:D47, D55, D61, D67:D71, D77) * B75): the model's base plus travel and tooling.
  "remodel-base-widened": {
    check: (v, m) => {
      const modelBase = m.labor + m.escalation + m.burden + m.gp + m.super_pto + m.soft_costs + m.contingency + m.fees;
      return m.remodel_tax === roundUp(modelBase * m.remodel_pct) ? null
        : "the model's remodel tax is no longer on labor, escalation, burden, GP, super/PTO, soft costs, contingency and fees alone";
    },
    output: (v, m) => {
      const base = m.labor + m.escalation + m.burden + m.travel + m.gp + m.super_pto + m.soft_costs + m.contingency + m.fees;
      const remodel_tax = roundUp(base * m.remodel_pct);
      const taxes = m.sales_tax + remodel_tax;
      const total = m.total - m.taxes + taxes;
      return Object.assign({}, m, { remodel_tax: remodel_tax, taxes: taxes, total: total, per_sf: m.sf > 0 ? total / m.sf : null });
    },
  },
};

function modelInput(v) {
  const i = v.in, a = v.out.answers;
  return {
    material: i.material || 0, labor: i.labor || 0, travel: i.travel || 0, fees: i.fees || 0,
    contingency: i.contingency || 0, sf: i.sf,
    tooling: i.tooling || 0,                       // the model has no such input today; see EXPLAIN
    conditions: { prevailing_wage: a.prevailingWage, taxable: a.taxable, remodel_tax: a.remodel },
    // The sheet types its own 10%, the model is handed the county's rate. Give it the rate the sheet used,
    // so what is compared is the chain and not a choice of rate.
    remodel_rate: a.remodel ? v.out.remodelPct : undefined,
  };
}

function same(a, b) {
  if (typeof a === "number" && typeof b === "number") return a === b || Math.abs(a - b) < 1e-9;
  return a === b;
}

function predict(v, skip) {
  const active = dep.departures.filter((d) => d.explain && d.id !== skip && holds(d.appliesWhen, v));
  let input = modelInput(v);
  for (const d of active) if (EXPLAIN[d.explain].input) input = EXPLAIN[d.explain].input(v, input);
  let m = M.markupChain(input);
  const problems = [];
  for (const d of active) {
    const e = EXPLAIN[d.explain];
    const problem = e.check ? e.check(v, m) : null;
    if (problem) problems.push({ key: "(" + d.id + ")", oracle: "the model as the departure describes it", model: problem });
    if (e.output) m = e.output(v, m);
  }
  return { m: m, problems: problems };
}

function chainDiffs(v, predicted) {
  const out = [];
  for (const key of Object.keys(dep.outputKeys)) {
    const want = v.out[key], got = predicted.m[dep.outputKeys[key]];
    if (!same(want, got)) out.push({ key: key, oracle: want, model: got });
  }
  return out.concat(predicted.problems);
}

function lodgingModel(v) {
  const rows = v.rows.map((r) => ({ guys: r.guys, days: r.days, rate: r.rate }));
  const on = !v.out.answers.local;
  const travel = {
    lodging: { enabled: on, qty_auto: true, rate: P.sheets.Polish.rates.lodgingRate.value },
    per_diem: { enabled: on, qty_auto: true, rate: P.sheets.Polish.rates.perDiemRate.value },
  };
  return M.travelCosts(travel, rows);
}

function lodgingDiffs(v, c) {
  const out = [];
  for (const key of Object.keys(dep.lodgingKeys)) {
    const want = v.out[key], got = c[dep.lodgingKeys[key]];
    if (!same(want, got)) out.push({ key: key, oracle: want, model: got });
  }
  return out;
}

// ── run every case ───────────────────────────────────────────────────────────
const summary = {
  model: path.basename(MODEL_FILE),
  chain: { vectors: 0, exact: 0, excused: 0, unexplained: [] },
  lodging: { vectors: 0, exact: 0, excused: 0, unexplained: [] },
  departures: Object.fromEntries(dep.departures.map((d) => [d.id, { applies: 0, seen: 0 }])),
};

for (const v of golden.vectors) {
  const lodging = v.id.startsWith("lodging/");
  const bucket = lodging ? summary.lodging : summary.chain;
  bucket.vectors++;
  const mine = dep.departures.filter((d) => (d.scope === "lodging") === lodging && holds(d.appliesWhen, v));
  let diffs;
  if (lodging) {
    diffs = lodgingDiffs(v, lodgingModel(v));
  } else {
    diffs = chainDiffs(v, predict(v, null));
    // Seen: does the departure really change the answer? Predict without it and look at its keys.
    for (const d of mine.filter((x) => x.explain)) {
      const without = chainDiffs(v, predict(v, d.id));
      if (without.some((x) => d.keys.includes(x.key))) summary.departures[d.id].seen++;
    }
  }
  const allowed = new Set();
  for (const d of mine) {
    summary.departures[d.id].applies++;
    if (!d.explain) for (const k of d.keys) allowed.add(k);
  }
  for (const d of mine.filter((x) => !x.explain)) {
    if (diffs.some((x) => d.keys.includes(x.key))) summary.departures[d.id].seen++;
  }
  const loose = diffs.filter((x) => !allowed.has(x.key));
  if (loose.length) {
    if (bucket.unexplained.length < 25) bucket.unexplained.push({ id: v.id, diffs: loose });
    bucket.unexplainedCount = (bucket.unexplainedCount || 0) + 1;
  } else if (diffs.length) bucket.excused++;
  else bucket.exact++;
}
console.log(JSON.stringify(summary));
