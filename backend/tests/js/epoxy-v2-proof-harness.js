"use strict";
/* THE v2 EPOXY PATH, PRICED FROM THE LIBRARY THE SEED SCRIPT PLANS, set beside what Kyle's workbook answered.
 *
 *   node epoxy-v2-proof-harness.js <frontend dir> <plan.json> <epoxy_jobs_golden.json>
 *
 * For every job the recorder typed into the workbook (tests/js/epoxy-jobs-recorder.js), this builds the same job as a
 * v2 Epoxy section (a system row for each system, a same-floor row for each primer, a length row for each cove, one
 * crew row) and prices it the way the estimate page does: js/bid-model.js priceSection, whose material is
 * js/epoxy-takeoff.js sectionMaterial over library-core's priceAssembly, on the library rows backend/ops/
 * seed_library_from_workbook.py plans (its --json output). Nothing is a second copy of a formula.
 *
 * Prints, as its last line, one JSON object: { cases: [{ id, raw, material, tooling, sub_total, total, ... }] }. The
 * test compares each figure with the workbook's and says which differences are declared.
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const golden = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));

const B = require(path.join(FRONTEND, "js", "bid-model.js"));
const L = require(path.join(FRONTEND, "js", "library-core.js"));
const X = require(path.join(FRONTEND, "js", "epoxy-takeoff.js"));

const items = plan.items;
const asms = plan.assemblies;
const norm = (t) => String(t).replace(/\s+/g, " ").trim();
const byName = new Map(asms.map((a) => [norm(a.name), a]));

function asmNamed(name, prefix) {
  const hit = byName.get(norm((prefix || "") + name));
  if (!hit) throw new Error("the library has no assembly called " + (prefix || "") + name);
  return hit;
}

/** The row an estimator would have on the takeoff for a system, a primer or a cove. */
function row(asm, measurement, unit, sameFloor) {
  const r = { assembly_id: asm.id, assembly_name: asm.name, measurement: measurement, unit: unit };
  if (sameFloor) r.same_floor = true;
  return r;
}

/** The v2 section for one recorded job. */
function takeoffFor(spec) {
  const rows = [];
  if (spec.sys1) rows.push(row(asmNamed(spec.sys1), spec.sf1, "SF"));
  if (spec.primer1) rows.push(row(asmNamed(spec.primer1, "Primer: "), spec.sf1, "SF", true));
  if (spec.cove1) rows.push(row(asmNamed(spec.cove1, "Cove: "), spec.lf1, "LF"));
  if (spec.sys2) rows.push(row(asmNamed(spec.sys2), spec.sf2, "SF"));
  if (spec.primer2) rows.push(row(asmNamed(spec.primer2, "Primer: "), spec.sf2, "SF", true));
  if (spec.cove2) rows.push(row(asmNamed(spec.cove2, "Cove: "), spec.lf2, "LF"));
  // a job with a measurement and no system (the sheet prices a patch for it): an unpicked row
  if (!spec.sys1 && spec.sf1 > 0) rows.push({ assembly_id: "", assembly_name: "", measurement: spec.sf1, unit: "SF" });
  if (!spec.sys2 && spec.sf2 > 0) rows.push({ assembly_id: "", assembly_name: "", measurement: spec.sf2, unit: "SF" });
  return rows;
}

function priceRow(r) {
  const asm = asms.find((a) => a.id === r.assembly_id);
  return asm ? L.priceAssembly(asm, items, B.num(r.measurement)) : null;
}

function modelFor(spec) {
  const base = B.freshModel();
  const root = Object.assign({}, base, { kind: "off" });
  let m = B.activateSection(root, "Epoxy", "base", {});
  m.conditions = Object.assign({}, m.conditions, {
    taxable: spec.taxable !== false, prevailing_wage: spec.pw === true, remodel_tax: spec.remodel === true,
  });
  const s = m.tabs.Epoxy;
  s.takeoff = takeoffFor(spec);
  s.labor = (spec.guys !== undefined || spec.days !== undefined)
    ? [{ id: "epoxy-install", label: "Epoxy install", guys: spec.guys === undefined ? 3 : spec.guys,
         days: spec.days === undefined ? 5 : spec.days, rate: 33, unit: "days" }]
    : [{ id: "epoxy-install", label: "Epoxy install", guys: 3, days: 5, rate: 33, unit: "days" }];
  return m;
}

function material(entry) {
  const takeoff = entry.section.takeoff;
  const r = X.sectionMaterial(takeoff, { items: items, sf: B.takeoffSf(takeoff), rowPrice: priceRow });
  return { material: r.material, tooling: r.tooling, _parts: r };
}

/** One cove of a job: what the section charges it (the aggregate follows System 1), and what it would be as quartz and
 *  as silica, so a test can show odd rule 11 happening and not merely agree with it. */
function coveOf(spec, n, takeoff) {
  const name = spec["cove" + n];
  if (!name) return null;
  const id = asmNamed(name, "Cove: ").id;
  const lf = spec["lf" + n];
  const price = (quartz) => X.priceCoveRow(id, lf, { items: items, quartz: quartz }).total;
  return { actual: price(X.systemOneIsQuartz(takeoff)), quartz: price(true), silica: price(false) };
}

const out = [];
golden.cases.forEach((c) => {
  const m = modelFor(c.in);
  const raw = material(m.tabs.Epoxy ? { section: m.tabs.Epoxy } : null);
  const bid = B.priceSection(m, "Epoxy", { material: (e) => { const r = material(e); return { material: r.material, tooling: r.tooling }; } });
  out.push({
    id: c.id, raw: raw.material, patch: raw._parts.patch, cove: raw._parts.cove,
    material: bid.material, tooling: bid.tooling, material_total: bid.material_total, labor: bid.labor,
    sub_total: bid.sub_total, gp: bid.gp, sales_tax: bid.sales_tax, remodel_tax: bid.remodel_tax, taxes: bid.taxes,
    total: bid.total, priceable: bid.priceable !== false,
    cove1: coveOf(c.in, 1, m.tabs.Epoxy.takeoff), cove2: coveOf(c.in, 2, m.tabs.Epoxy.takeoff),
  });
});

// ── the chain: every Epoxy vector the workbook oracle recorded, through the v2 section ────────────────────────
// The oracle types a material, a labor figure, tooling, travel, fees and contingency into the boundary of the chain
// (tests/js/workbook-oracle.js). Here each is handed to a v2 Epoxy section the way the page would hold it: the labor
// as a crew row, the travel as a Lodging line typed in, the fees and contingency as the section's own, the job
// questions as the model's conditions, the square feet as a takeoff row. What the oracle typed as material and
// tooling is what the takeoff would have produced, and is handed straight in: the takeoff is proved by the jobs above.
const chain = [];
if (process.argv[5]) {
  const oracle = JSON.parse(fs.readFileSync(process.argv[5], "utf8"));
  const KEYS = { shipPct: "ship_pct", shipping: "shipping", materialTotal: "material_total", escPct: "esc_pct",
    escalation: "escalation", burden: "burden", subTotal: "sub_total", gpPct: "gp_pct", gp: "gp", superPto: "super_pto",
    softCosts: "soft_costs", salesTaxPct: "sales_tax_pct", salesTax: "sales_tax", remodelTax: "remodel_tax",
    taxes: "taxes", bond: "bond", feesAndBond: "fees_and_bond", total: "total", perSf: "per_sf", remodelPct: "remodel_pct" };
  const same = (a, b) => {
    const x = a === false ? 0 : a, y = b === false ? 0 : b;
    return (typeof x === "number" && typeof y === "number") ? (x === y || Math.abs(x - y) < 1e-9) : x === y;
  };
  oracle.vectors.forEach((v) => {
    const i = v.in, a = v.out.answers;
    const skip = a.hardBid ? "hard bid" : (i.bondPct ? "bond" : (i.travel === "template" || i.travel === undefined && !a.local ? "lodging" : null));
    if (skip) { chain.push({ id: v.id, skipped: skip }); return; }
    const base = B.freshModel();
    const m = B.activateSection(Object.assign({}, base, { kind: "off" }), "Epoxy", "base", {});
    m.conditions = Object.assign({}, m.conditions, { taxable: !!a.taxable, prevailing_wage: !!a.prevailingWage, remodel_tax: !!a.remodel });
    const sec = m.tabs.Epoxy;
    sec.takeoff = [{ assembly_id: "", assembly_name: "", measurement: i.sf, unit: "SF" }];
    sec.labor = i.labor ? [{ id: "crew", label: "Crew", guys: 1, days: i.labor / 8, rate: 1, unit: "days" }] : [];
    sec.contingency = i.contingency || 0;
    sec.fees = i.fees || 0;
    m.travel = B.travelCostsSeed(33, 45);
    m.travel.lodging = { label: "Lodging", enabled: !!i.travel, qty: 1, qty_auto: false, rate: i.travel || 0 };
    const r = B.priceSection(m, "Epoxy", {
      material: () => ({ material: i.material || 0, tooling: i.tooling || 0 }),
      remodel_rate: a.remodel && i.remodelPct !== undefined ? i.remodelPct : undefined,
    });
    const wrong = Object.keys(KEYS).filter((k) => v.out[k] !== undefined && v.out[k] !== null && !same(v.out[k], r[KEYS[k]]))
      .map((k) => k + ": workbook " + v.out[k] + ", v2 " + r[KEYS[k]]);
    chain.push({ id: v.id, wrong: wrong });
  });
}
console.log(JSON.stringify({ cases: out, chain: chain }));
