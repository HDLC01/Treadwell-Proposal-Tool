"use strict";
/* THE v2 GYP PATH, PRICED FROM THE LIBRARY THE SEED SCRIPT PLANS, set beside what Kyle's workbook answered.
 *
 *   node gyp-v2-proof-harness.js <frontend dir> <plan.json> <gyp_jobs_golden.json> <oracle dir>
 *
 * TWO PROOFS, ONE PRICER (js/bid-model.js priceSection, the function the estimate page prices a Gyp section with):
 *
 *   JOBS    For every job the recorder typed into a Gyp tab (tests/js/gyp-jobs-recorder.js: the three areas, a
 *           thickness for each, the mix, ISO strip at all areas, the sound mat, moisture tests) this builds the same
 *           job as a v2 Gyp section filed under that tab (a row for each area, the section's `gyp` settings) and
 *           prices it: material is js/gyp-takeoff.js sectionMaterial on the library rows backend/ops/
 *           seed_library_from_workbook.py plans (its --json output). The labor is the figure the workbook's own
 *           labor lines came to (E52), because the hours are typed in v2 and derived from the takeoff in the sheet.
 *   CHAIN   Every vector of the five Gyp oracle files (backend/tests/fixtures/oracle/gyp-*.json), which type the
 *           chain's inputs at its boundary, is priced as a v2 section of that tab: the labor as a crew row priced by
 *           the hour, the fees and contingency as the section's own, the job questions as the model's conditions,
 *           the material figures as the page would hand them over. Equal to the cent on every figure they share.
 *
 * Prints, as its last line, one JSON object: { jobs: [...], chain: [...] }. The test compares each figure with the
 * workbook's and says which differences are declared.
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const golden = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const ORACLE = path.resolve(process.argv[5]);

const B = require(path.join(FRONTEND, "js", "bid-model.js"));
const G = require(path.join(FRONTEND, "js", "gyp-takeoff.js"));
const P = require(path.join(FRONTEND, "js", "bid-profiles.js"));

const items = plan.items;
const asms = plan.assemblies;
const MATS = (tab) => G.matList(tab);

function areaRow(bucket, sf) {
  const a = G.AREA_ASSEMBLIES[bucket];
  const asm = asms.find((x) => x.id === a.id);
  if (!asm) throw new Error("the library has no assembly " + a.id);
  return { assembly_id: asm.id, assembly_name: asm.name, measurement: sf, unit: "SF", bucket: bucket };
}

/** A fresh bid with one Gyp section on `tab`, the Polish root off. */
function modelFor(tab) {
  const base = B.freshModel();
  const root = Object.assign({}, base, { kind: "off" });
  return B.activateSection(root, tab, "base", {});
}

/** The section's own settings for one recorded job. */
function settingsFor(spec, tab) {
  const s = {};
  if (spec.thick) {
    s.thickness = {};
    G.BUCKETS.forEach((b) => { if (spec.thick[b] !== undefined) s.thickness[b] = spec.thick[b]; });
  }
  if (spec.mix !== undefined) s.mix = spec.mix;
  if (spec.isoAll) s.iso_all = true;
  if (spec.moisture !== undefined) s.moisture_tests = spec.moisture;
  if (spec.mat !== undefined && spec.mat !== null) s.sound_mat = MATS(tab)[spec.mat].id;
  return s;
}

function takeoffFor(spec) {
  const rows = [];
  if (spec.soft > 0) rows.push(areaRow("soft", spec.soft));
  if (spec.hard > 0) rows.push(areaRow("hard", spec.hard));
  if (spec.corr > 0) rows.push(areaRow("corridor", spec.corr));
  return rows.length ? rows : [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }];
}

function materialOf(entry) {
  const sec = entry.section;
  return G.sectionMaterial(sec.takeoff, sec.gyp, entry.tab, { items: items, rowPrice: () => null });
}

// ── the jobs ──────────────────────────────────────────────────────────────────
const jobs = [];
golden.cases.forEach((c) => {
  const m = modelFor(c.tab);
  const sec = m.tabs[c.tab];
  sec.takeoff = takeoffFor(c.in);
  sec.gyp = settingsFor(c.in, c.tab);
  // the sheet's own labor dollars, as hours at $1
  sec.labor = c.out.E52 > 0 ? [{ id: "gyp-labor", label: "Crew", guys: 1, days: c.out.E52, rate: 1, unit: "hours" }] : [];
  const bid = B.priceSection(m, c.tab, { material: (e) => materialOf(e) });
  const raw = materialOf({ tab: c.tab, section: sec });
  jobs.push({
    id: c.id, raw: { gyp: raw.gyp, extras: raw.extras, sand: raw.sand, soundMat: raw.soundMat },
    rolls: raw.soundMatRolls, truckload: raw.truckload, tooling: raw.tooling,
    bags: raw.figures.bags, tons: raw.figures.tons, areas: raw.figures.areas,
    hours: G.sheetHours(raw.figures, 0, 0),
    priceable: bid.priceable !== false, material: bid.material, material_escalation: bid.material_escalation,
    shipping: bid.shipping, material_total: bid.material_total, sub_total: bid.sub_total, gp: bid.gp,
    taxes: bid.taxes, total: bid.total,
  });
});

// ── the chain: every vector the workbook oracle recorded for the five Gyp tabs ─────────────────────────────────
const KEYS = {
  materialSubTotal: "material", materialEscalation: "material_escalation", shipping: "shipping",
  materialTotal: "material_total", escalation: "escalation", burden: "burden", subTotal: "sub_total",
  gpPct: "gp_pct", gp: "gp", superPto: "super_pto", softPct: "soft_pct", softCosts: "soft_costs",
  salesTaxPct: "sales_tax_pct", salesTax: "sales_tax", remodelTax: "remodel_tax", taxes: "taxes", bond: "bond",
  feesAndBond: "fees_and_bond", total: "total", perSf: "per_sf", remodelPct: "remodel_pct",
};
const same = (a, b) => {
  const x = a === false ? 0 : a, y = b === false ? 0 : b;
  return (typeof x === "number" && typeof y === "number") ? (x === y || Math.abs(x - y) < 1e-9) : x === y;
};

/** THE SHEET'S OWN LODGING, through a v2 section (the oracle's `travel: "template"` vectors: Gyp!B64 `=IF(B5="No",((E52-E51)/C46)/10)`, per diem B65 `=B64`). The vector's crew rows are
 *  typed as a Gyp crew is typed in v2, in HOURS (a day of the sheet's `hoursPerDay`, ten, each), at their own rates, and the drive as its own row; the job is answered far by the model's own
 *  distance answer, so the Lodging and Per Diem lines come on and FOLLOW THE LABOR (a new bid's lines open empty and off auto, and a far answer fills them), and the section is priced as the page
 *  prices it. What comes back is the quantity the lines are charged for, each line's dollars and the chain's figures, each beside the workbook's, and what a head count (guys x hours over ten)
 *  would have said, so the rule that was picked is pinned against the one that was not. */
const GYP_TRAVEL_RATE = 33.66;
function lodgingVector(tab, v) {
  const i = v.in, a = v.out.answers, o = v.out;
  const m = modelFor(tab);
  m.conditions = Object.assign({}, m.conditions, {
    local: !!a.local, taxable: !!a.taxable, prevailing_wage: !!a.prevailingWage, remodel_tax: !!a.remodel,
  });
  const sec = m.tabs[tab];
  sec.takeoff = [{ assembly_id: "", assembly_name: "", measurement: i.sf, unit: "SF" }];
  sec.labor = v.rows.map((r, n) => ({ id: "gyp-crew-" + n, label: "Crew " + (n + 1), guys: r.guys, days: Math.round(r.days * v.hoursPerDay * 1e6) / 1e6, rate: r.rate, unit: "hours" }));
  if (i.travelLabor) {
    sec.labor.push({ id: "travel", label: "Travel Labor", guys: 1, days: Math.round((i.travelLabor / GYP_TRAVEL_RATE) * 1e6) / 1e6, rate: GYP_TRAVEL_RATE, unit: "hours" });
  }
  sec.contingency = i.contingency || 0;
  sec.fees = i.fees || 0;
  // A NEW bid's lines (empty, off auto) at the tab's own rates, C64 and C65; a far answer then switches them on and fills them, a local one leaves them off.
  m.travel = B.travelCostsSeed(70, 45);
  ["lodging", "per_diem"].forEach((k) => { m.travel[k].qty_auto = false; m.travel[k].qty = ""; });
  B.applyDistance(m, { miles: a.local ? 30 : 190, source: "typed", key: "" });
  const r = B.priceSection(m, tab, {
    material: () => ({ gyp: 0, extras: 0, sand: 0, soundMat: 0, soundMatRolls: 0, tooling: 0 }),
  });
  const opts = B.travelOpts(m, tab);
  const line = m.travel.lodging;
  const qty = B.travelQty(line, sec.labor, opts);
  const costs = B.travelCosts(m.travel, sec.labor, opts);
  const people = B.travelManDays(sec.labor, 10);
  const wrong = [];
  if (B.roundUp(B.laborTotal(sec.labor)) !== i.labor) wrong.push("labor: workbook " + i.labor + ", v2 rows " + B.roundUp(B.laborTotal(sec.labor)));
  if (a.local) {
    if (line.enabled) wrong.push("a local job has its Lodging on");
  } else {
    if (!(line.enabled && line.qty_auto === true && line.qty_follow === "labor")) wrong.push("the far job's nights are not following the labor");
    if (!same(qty, o.lodgingQty)) wrong.push("nights: workbook " + o.lodgingQty + ", v2 " + qty);
  }
  if (costs.lodging !== o.lodging) wrong.push("lodging: workbook " + o.lodging + ", v2 " + costs.lodging);
  if (costs.per_diem !== o.perDiem) wrong.push("per diem: workbook " + o.perDiem + ", v2 " + costs.per_diem);
  if (costs.total !== o.travel) wrong.push("travel: workbook " + o.travel + ", v2 " + costs.total);
  Object.keys(KEYS).forEach((k) => {
    if (o[k] !== undefined && o[k] !== null && !same(o[k], r[KEYS[k]])) wrong.push(k + ": workbook " + o[k] + ", v2 " + r[KEYS[k]]);
  });
  return { tab: tab, id: v.id, lodging: true, far: !a.local, wrong: wrong, nights: a.local ? null : qty, sheetNights: a.local ? null : o.lodgingQty,
    lodgingCost: costs.lodging, perDiemCost: costs.per_diem, sheet: { lodging: o.lodging, perDiem: o.perDiem, travel: o.travel },
    // what counting people (guys x hours over ten) would have charged: the rule that was not picked
    people: { nights: people, lodging: B.roundUp(people * 70), perDiem: B.roundUp(people * 45) } };
}

const chain = [];
P.priced.filter((t) => t.indexOf("Gyp") === 0).forEach((tab) => {
  const slug = P.sheets[tab].slug;
  const oracle = JSON.parse(fs.readFileSync(path.join(ORACLE, slug + ".json"), "utf8"));
  oracle.vectors.forEach((v) => {
    const i = v.in, a = v.out.answers;
    // THE SHEET'S OWN LODGING (the vectors that ask the template for it) is priced through a v2 section with the nights left to follow the labor: lodgingVector.
    if (i.travel === "template" && !i.bondPct) { chain.push(lodgingVector(tab, v)); return; }
    // The chain's own inputs the v2 model has no box for: a typed bond rate (bond is 0 and unwired), and a far job whose travel the vector does not give at all (none is recorded).
    // (The Hard Bid question changes nothing on a Gyp tab, so those vectors are priced like any other.)
    const skip = i.bondPct ? "bond" : (i.travel === undefined && !a.local ? "lodging" : null);
    if (skip) { chain.push({ tab: tab, id: v.id, skipped: skip }); return; }
    const m = modelFor(tab);
    m.conditions = Object.assign({}, m.conditions, {
      local: !!a.local, taxable: !!a.taxable, prevailing_wage: !!a.prevailingWage, remodel_tax: !!a.remodel,
    });
    const sec = m.tabs[tab];
    sec.takeoff = [{ assembly_id: "", assembly_name: "", measurement: i.sf, unit: "SF" }];
    sec.labor = i.labor ? [{ id: "gyp-labor", label: "Crew", guys: 1, days: i.labor, rate: 1, unit: "hours" }] : [];
    sec.contingency = i.contingency || 0;
    sec.fees = i.fees || 0;
    m.travel = B.travelCostsSeed(33, 45);
    m.travel.lodging = { label: "Lodging", enabled: !!i.travel, qty: 1, qty_auto: false, rate: i.travel || 0 };
    const r = B.priceSection(m, tab, {
      // What the page hands the pricer, with the figures the oracle typed: gypsum, extras, sand, sound mat and its
      // rolls. The truckload is left to the tab (the section carries no mat of its own here).
      material: () => ({
        gyp: i.gyp || 0, extras: i.extras || 0, sand: i.sand || 0, soundMat: i.soundMat || 0,
        soundMatRolls: i.soundMatRolls || 0, tooling: i.tooling || 0,
      }),
      remodel_rate: a.remodel && i.remodelPct !== undefined ? i.remodelPct : undefined,
    });
    const wrong = Object.keys(KEYS).filter((k) => v.out[k] !== undefined && v.out[k] !== null && !same(v.out[k], r[KEYS[k]]))
      .map((k) => k + ": workbook " + v.out[k] + ", v2 " + r[KEYS[k]]);
    chain.push({ tab: tab, id: v.id, wrong: wrong, truckload: P.tabs[tab].truckload, rolls: i.soundMatRolls });
  });
});

// ── the oracle's two probes of the odd rules (odd rules 6 and 7), through the same section ─────────────────────
// `sound-mat-truckload`: $10,000 of sound mat at 279, 280 and 281 rolls, the shipping the workbook charged. And
// `bags-fractional-sand-follows`: 1,000, 2,000 and 500 SF in the three areas at the tab's own default thickness, the
// bags and the sand the workbook worked out.
const probes = [];
P.priced.filter((t) => t.indexOf("Gyp") === 0).forEach((tab) => {
  const oracle = JSON.parse(fs.readFileSync(path.join(ORACLE, P.sheets[tab].slug + ".json"), "utf8"));
  oracle.probes.forEach((probe) => {
    probe.steps.forEach((step) => {
      if (probe.id === "sound-mat-truckload") {
        const m = modelFor(tab);
        m.tabs[tab].takeoff = [{ assembly_id: "", assembly_name: "", measurement: 1000, unit: "SF" }];
        const r = B.priceSection(m, tab, { material: () => ({ gyp: 0, extras: 0, sand: 0, soundMat: step.set.E36, soundMatRolls: step.set.B36 }) });
        probes.push({ probe: probe.id, tab: tab, label: step.label, rolls: step.set.B36, truckload: step.got.H36, workbook: step.got.E40, v2: r.shipping });
      } else if (probe.id === "bags-fractional-sand-follows") {
        const m = modelFor(tab);
        m.tabs[tab].takeoff = [areaRow("soft", step.set.F23), areaRow("hard", step.set.F24), areaRow("corridor", step.set.F25)];
        const f = G.sectionMaterial(m.tabs[tab].takeoff, m.tabs[tab].gyp, tab, { items: items, rowPrice: () => null }).figures;
        probes.push({ probe: probe.id, tab: tab, label: step.label, workbook: { bags: [step.got.B23, step.got.B24, step.got.B25], total: step.got.H33, tons: step.got.B33 },
          v2: { bags: [f.bags.soft, f.bags.hard, f.bags.corridor], total: f.bags.total, tons: f.tons } });
      }
    });
  });
});

console.log(JSON.stringify({ jobs: jobs, chain: chain, probes: probes }));
