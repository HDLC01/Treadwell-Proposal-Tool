"use strict";
/* THE MAN HOURS AND BUDGET BLOCK, PRICED THROUGH v2, for the jobs the workbook has answered.
 *
 *   node man-hours-parity-harness.js <frontend dir> <plan.json> <recorded_job.json> <epoxy_jobs_golden.json>
 *
 * The jobs are built and priced by the harnesses that already prove v2's price is the workbook's: the recorded real job
 * (recorded-job-parity-harness.js, its `epoxy` and `polish`) and the 440 Epoxy jobs of the golden (epoxy-v2-proof-harness.js,
 * its `modelFor` and `material`). Their code is loaded as it is, cut before its own run; nothing of how a job is built is
 * copied here. Each bid that harness prices through B.priceSection or B.polishBid is caught on its way out, and
 * B.manHourBudget is asked for the block over the section's own labor rows and that bid. Three variants of the recorded job
 * reach the rows the recorded job does not have: a drive and the fourth hand of Remove existing joint filler on the Polish
 * job, a drive, a second crew line and a contingency on the Epoxy job, and the Epoxy crew on 10 hour days.
 *
 * Prints, as its last line, { recorded: { epoxy, polish }, variants: {...}, golden: [{ id, block, chain, labor }] }. The test
 * evaluates the workbook's own formulas for the block over the same inputs and compares.
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const Lib = require("./_lib.js");

const FRONTEND = path.resolve(process.argv[2]);
const JOB = process.argv[4];
const GOLDEN = process.argv[5];
const B = require(path.join(FRONTEND, "js", "bid-model.js"));
const clone = (v) => JSON.parse(JSON.stringify(v));

// ── every bid the borrowed harnesses price, caught on its way out ─────────────────────────────────────────────
let caught = null;
const realPriceSection = B.priceSection, realPolishBid = B.polishBid;
B.priceSection = function (model, tab, ctx) {
  const bid = realPriceSection.apply(this, arguments);
  caught = { model: model, tab: tab, ctx: ctx, bid: bid, price: realPriceSection };
  return bid;
};
B.polishBid = function (model, tab, ctx) {
  const bid = realPolishBid.apply(this, arguments);
  caught = { model: model, tab: tab, ctx: ctx, bid: bid, price: realPolishBid };
  return bid;
};

function loadPrelude(file, exportNames, argv4) {
  const base = path.join(__dirname, file);
  const code = Lib.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in man-hours-parity-harness.js");
  const saved = process.argv[4];
  process.argv[4] = argv4;               // each borrowed harness reads its fixture from argv[4] as it loads
  try {
    const m = new Module(base, module);
    m.filename = base;
    m.paths = Module._nodeModulePaths(path.dirname(base));
    m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
    return m.exports;
  } finally {
    process.argv[4] = saved;
  }
}

const R = loadPrelude("recorded-job-parity-harness.js", ["epoxy", "polish", "job"], JOB);
const G = loadPrelude("epoxy-v2-proof-harness.js", ["modelFor", "material", "golden"], GOLDEN);

const CHAIN = ["sub_total", "gp", "hard_bid", "super_pto", "soft_costs", "contingency", "sales_tax", "remodel_tax", "taxes",
  "fees_and_bond", "total", "sf"];

/** The block for a caught bid, with what the workbook side needs: the chain's lines, the rows, the job's questions. */
function report(c) {
  const s = B.sectionOf(c.model, c.tab).section;
  const chain = {};
  CHAIN.forEach((k) => { chain[k] = c.bid[k] === undefined ? 0 : c.bid[k]; });
  return { block: B.manHourBudget(s.labor, c.model.conditions, B.prevailingApplied(c.model), c.bid), chain: chain,
           labor: clone(s.labor), conditions: clone(c.model.conditions || {}) };
}

/** The caught job with its rows changed by `edit`, priced again by the same engine on the same material. */
function variant(c, edit) {
  const m = clone(c.model);
  edit(B.sectionOf(m, c.tab).section, m);
  const bid = c.price(m, c.tab, c.ctx);
  return report({ model: m, tab: c.tab, bid: bid });
}

const out = { recorded: {}, variants: {} };

R.epoxy(R.job.epoxy.in, R.job.epoxy.adjust);
const epoxyJob = caught;
out.recorded.epoxy = report(epoxyJob);
R.polish(R.job.polish.in, R.job.polish.adjust);
const polishJob = caught;
out.recorded.polish = report(polishJob);

out.variants.polishDriveAndHand = variant(polishJob, (s, m) => {
  s.labor.push({ id: "travel", label: "Travel Labor", guys: 3, days: 6.5, rate: 33, unit: "hours" });
  m.conditions.remove_existing_jf = true;
});
out.variants.epoxyDriveAndSecondCrew = variant(epoxyJob, (s) => {
  // first in the list and not the crew's size, so a block that took the drive for the crew line would show it
  s.labor.unshift({ id: "travel", label: "Travel Labor", guys: 2, days: 6.5, rate: 35, unit: "hours" });
  s.labor.push({ id: "epoxy-cove", label: "Cove crew", guys: 2, days: 3, rate: 33, unit: "days" });
  s.contingency = 750;                   // D77, which the recorded job left at nothing
});
out.variants.epoxyTenHourDays = variant(epoxyJob, (s) => {
  s.labor.forEach((r) => { r.hours_per_day = 10; });
});

out.golden = G.golden.cases.map((gc) => {
  const m = G.modelFor(gc.in);
  B.priceSection(m, "Epoxy", { material: (e) => { const r = G.material(e); return { material: r.material, tooling: r.tooling }; } });
  return Object.assign({ id: gc.id }, report(caught));
});

console.log(JSON.stringify(out));
