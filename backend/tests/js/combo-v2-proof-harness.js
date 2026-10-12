"use strict";
/* A COMBO JOB PRICED THROUGH v2, SET BESIDE WHAT KYLE'S WORKBOOK ANSWERED FOR EACH OF ITS TWO TABS.
 *
 *   node combo-v2-proof-harness.js <frontend dir>
 *
 * In the live workbook a Combo job is the Epoxy tab and the Polish tab each filled in and each priced on its own, and
 * the proposal's price is the two totals added (proposal-review.js rebuildPricing: `N(eB.total) + N(pB.total)`). The
 * oracle (backend/tests/fixtures/oracle/polish.json and epoxy.json) typed hundreds of jobs into the boundary of each
 * tab's chain and recorded what its cells answered. So the workbook's answer for a COMBO of one Polish job and one
 * Epoxy job is already on record: the Polish total plus the Epoxy total, the two sales taxes added, the two remodel
 * taxes added.
 *
 * For every pair this builds the job as v2 builds a combo (js/bid-model.js sectionsForJob: the Polish root and an Epoxy
 * section, both bases), gives each section the inputs its workbook run was typed with, and prices it the way the
 * estimate page does: the root through markupChain, the Epoxy section through priceSection, the pair put together by
 * composePricingSnapshot (the engine's combine: each section's total after its OWN gross profit, summed). The
 * figures the proposal reads (proposal_lump_sum, the two taxes, each tab's total in priced_tabs) have to be equal to
 * the workbook's, to the dollar and so to the cent.
 *
 * WHICH JOBS. A pair needs the two tabs to be answering the same job-level questions (Taxable?, Prevailing wage?,
 * Remodel tax? and its rate), because the model holds those once. The v2 combo charges the job's travel ONCE, on the
 * Polish section (the plan default), so the Epoxy side is a vector with no travel typed in. What the Polish model
 * cannot do (the hard bid, the bond, a remodel tax that widens its base) is not paired: those are the Polish
 * departures test_polish_model_vs_oracle.py already declares. The Polish tooling line (D55) IS handled the way that
 * test proves it, as the same dollars in the sub-total through the travel input (a `fold` pair).
 *
 * Prints, as its last line, one JSON object.
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = path.resolve(process.argv[2]);
const ORACLE = path.join(__dirname, "..", "fixtures", "oracle");
const B = require(path.join(FRONTEND, "js", "bid-model.js"));
const E = require(path.join(FRONTEND, "js", "bid-engine.js"));

const polish = JSON.parse(fs.readFileSync(path.join(ORACLE, "polish.json"), "utf8"));
const epoxy = JSON.parse(fs.readFileSync(path.join(ORACLE, "epoxy.json"), "utf8"));

const chain = (d) => d.vectors.filter((v) => !v.id.startsWith("lodging/"));
const answers = (v) => v.out.answers;

/** A Polish vector the v2 root can price (see the header): no hard bid, no bond, and no remodel tax whose base would widen. */
function polishOk(v) {
  const i = v.in, a = answers(v);
  if (a.hardBid || i.bondPct) return false;
  if (a.remodel && v.out.remodelPct > 0 && ((i.travel || 0) !== 0 || (i.tooling || 0) !== 0)) return false;
  return true;
}

/** An Epoxy vector the v2 section can price with the job's travel on the other section: no hard bid, no bond, no
 *  travel typed, and the sheet's own travel switch said local (so it is not charging a lodging template). */
function epoxyOk(v) {
  const i = v.in, a = answers(v);
  if (a.hardBid || i.bondPct) return false;
  if ((i.travel || 0) !== 0) return false;
  return a.local !== false;
}

const key = (v) => JSON.stringify([!!answers(v).taxable, !!answers(v).prevailingWage, !!answers(v).remodel,
  answers(v).remodel ? v.out.remodelPct : 0]);

const P = chain(polish).filter(polishOk);
const X = chain(epoxy).filter(epoxyOk);

/** The pairs, in a fixed order: each Polish vector with up to three Epoxy vectors that answer the same job questions,
 *  chosen by a fixed stride so every run prices the same jobs. */
const pairs = [];
P.forEach((p, pi) => {
  const same = X.filter((x) => key(x) === key(p));
  if (!same.length) return;
  const picked = new Set();
  for (let k = 0; k < 3 && picked.size < same.length; k++) picked.add((pi * 7 + k * 11) % same.length);
  picked.forEach((j) => pairs.push([p, same[j]]));
});

const crew = (labor) => (labor ? [{ id: "crew", label: "Crew", guys: 1, days: labor / 8, rate: 1, unit: "days" }] : []);
const sfRow = (sf) => [{ assembly_id: "", assembly_name: "", measurement: sf, unit: "SF" }];

function comboFor(p, x) {
  const a = answers(p);
  const m = B.sectionsForJob(B.freshModel(), "combo", {});
  m.conditions = Object.assign({}, m.conditions, { taxable: !!a.taxable, prevailing_wage: !!a.prevailingWage, remodel_tax: !!a.remodel });
  // the Polish root: the job's travel is typed on it, and its tooling (which the Polish chain has no line for) is carried
  // as the same dollars in the travel input, the way the departure's own proof does
  m.takeoff = sfRow(p.in.sf);
  m.labor = crew(p.in.labor);
  m.contingency = p.in.contingency || 0;
  m.fees = p.in.fees || 0;
  const t = (p.in.travel || 0) + (p.in.tooling || 0);
  m.travel = B.travelCostsSeed(33, 45);
  m.travel.lodging = { label: "Lodging", enabled: t > 0, qty: 1, qty_auto: false, rate: t };
  // the Epoxy section
  const s = m.tabs.Epoxy;
  s.takeoff = sfRow(x.in.sf);
  s.labor = crew(x.in.labor);
  s.contingency = x.in.contingency || 0;
  s.fees = x.in.fees || 0;
  return m;
}

const rateOf = (p) => (answers(p).remodel ? p.out.remodelPct : undefined);

/** What the estimate page hands composePricingSnapshot (polish-estimate.js priceCtx): the root's markupChain and the
 *  other sections' priceTabs. Material and tooling are what the oracle typed into each chain's boundary. */
function priceCtx(m, p, x) {
  const bid = B.markupChain({
    material: p.in.material || 0, labor: B.laborTotal(m.labor, m.conditions),
    travel: B.travelCosts(m.travel, m.labor).total, contingency: m.contingency, fees: m.fees,
    conditions: m.conditions, sf: B.takeoffSf(m.takeoff), remodel_rate: rateOf(p),
  });
  const bids = B.priceTabs(m, {
    material: () => ({ material: x.in.material || 0, tooling: x.in.tooling || 0 }), remodel_rate: rateOf(p),
  });
  return { bid: bid, bids: bids };
}

const wrong = [];
let exact = 0, folded = 0, pooledDiffers = 0;
pairs.forEach(([p, x]) => {
  const m = comboFor(p, x);
  const ctx = priceCtx(m, p, x);
  const snap = B.composePricingSnapshot(m, ctx);
  const want = { total: p.out.total + x.out.total, sales: p.out.salesTax + x.out.salesTax, remodel: p.out.remodelTax + x.out.remodelTax };
  const tab = (id) => (snap.priced_tabs || []).filter((t) => t.id === id)[0] || {};
  const got = {
    lump: snap.proposal_lump_sum, computed: snap.computed_bid && snap.computed_bid.lump_sum,
    sales: snap.proposal_sales_tax, remodel: snap.proposal_remodel_tax,
    polish: tab("Polish").total, epoxy: tab("Epoxy").total,
    polishSales: tab("Polish").sales_tax, epoxySales: tab("Epoxy").sales_tax,
    polishRemodel: tab("Polish").remodel, epoxyRemodel: tab("Epoxy").remodel,
  };
  const diffs = [];
  const eq = (name, a, b) => { if (a !== b) diffs.push(name + ": workbook " + b + ", v2 " + a); };
  eq("lump", got.lump, want.total);
  eq("computed", got.computed, want.total);
  eq("sales tax", got.sales, want.sales);
  eq("remodel tax", got.remodel, want.remodel);
  eq("Polish tab", got.polish, p.out.total);
  eq("Epoxy tab", got.epoxy, x.out.total);
  eq("Polish sales", got.polishSales, p.out.salesTax);
  eq("Epoxy sales", got.epoxySales, x.out.salesTax);
  eq("Polish remodel", got.polishRemodel, p.out.remodelTax);
  eq("Epoxy remodel", got.epoxyRemodel, x.out.remodelTax);
  if ((p.in.tooling || 0) > 0) folded++;
  if (diffs.length) wrong.push({ id: p.id + " + " + x.id, diffs: diffs });
  else exact++;
  // THE ROAD NOT TAKEN: the two sections' money pooled into one Polish chain. It is a different bid whenever the pool
  // lands on another gross-profit rung, which is what combine exists to avoid.
  const pooled = B.markupChain({
    material: (p.in.material || 0) + (x.in.material || 0) + (x.in.tooling || 0), labor: (p.in.labor || 0) + (x.in.labor || 0),
    travel: (p.in.travel || 0) + (p.in.tooling || 0), contingency: (p.in.contingency || 0) + (x.in.contingency || 0),
    fees: (p.in.fees || 0) + (x.in.fees || 0), conditions: m.conditions, sf: p.in.sf + x.in.sf, remodel_rate: rateOf(p),
  });
  if (pooled.total !== want.total) pooledDiffers++;
});

console.log(JSON.stringify({
  polishCandidates: P.length, epoxyCandidates: X.length, pairs: pairs.length, exact: exact, folded: folded,
  pooledDiffers: pooledDiffers, wrong: wrong.slice(0, 25), wrongCount: wrong.length,
  engineHasCombine: typeof E.combine === "function",
}));
