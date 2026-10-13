"use strict";
/* THE v2 SEAL OPTION, PRICED FROM THE LIBRARY THE SEED SCRIPT PLANS, set beside what Kyle's workbook answered.
 *
 *   node seal-v2-proof-harness.js <frontend dir> <plan.json> <seal_jobs_golden.json> <oracle dir>
 *
 * TWO PROOFS, ONE PRICER (js/bid-model.js priceSection, the function the estimate page prices an option with):
 *
 *   CHAIN   Every vector of the two Seal oracle files (backend/tests/fixtures/oracle/seal.json and seal-jnts.json), which
 *           type the chain's inputs at its boundary, is priced as an OPTION section filed under that tab (kind "option",
 *           the seal profile): the material and tooling as the page hands them over, the labor as a crew row, the fees and
 *           contingency the section's own, the job questions the model's conditions. The vectors v2 has no box for are
 *           counted and named: a Hard Bid answer (Hanz removed the switch, 2026-10-03), a typed bond rate, and the sheet's
 *           own lodging (v2 takes Hotel and Per Diem from the lines the estimator types).
 *   JOBS    For every job the recorder typed into a Seal tab (tests/js/seal-jobs-recorder.js: the area, New or Reno, one
 *           coat of sealer or two, joint filler on or off, the crew's days) this builds the same job as a v2 option over the
 *           library backend/ops/seed_library_from_workbook.py plans and prices it: the takeoff is one of the four seeded
 *           assemblies, and the patch and the tooling are js/seal-takeoff.js sectionMaterial's.
 *
 * Prints, as its last line, one JSON object: { chain: [...], jobs: [...] }. The test compares each figure
 * with the workbook's.
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const golden = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const ORACLE = path.resolve(process.argv[5]);

const B = require(path.join(FRONTEND, "js", "bid-model.js"));
const S = require(path.join(FRONTEND, "js", "seal-takeoff.js"));
const LIB = require(path.join(FRONTEND, "js", "library-core.js"));

const items = plan.items;
const asms = plan.assemblies;

/** A bid whose only section is a Seal option on `tab`: the Polish root off, so the option carries the job's travel (the
 *  oracle types the travel into the chain, and the section that carries the job's travel is the one that takes it). */
function modelFor(tab) {
  const root = Object.assign({}, B.freshModel(), { kind: "off" });
  return B.activateSection(root, tab, "option", {});
}

const same = (a, b) => {
  const x = a === false ? 0 : a, y = b === false ? 0 : b;
  return (typeof x === "number" && typeof y === "number") ? (x === y || Math.abs(x - y) < 1e-9) : x === y;
};

// ── the chain: every vector the workbook oracle recorded for the two Seal tabs ──────────────────────────────────
const KEYS = {
  shipping: "shipping", materialTotal: "material_total", escPct: "esc_pct", escalation: "escalation", burden: "burden",
  subTotal: "sub_total", gpPct: "gp_pct", gp: "gp", superPto: "super_pto", softPct: "soft_pct", softCosts: "soft_costs",
  salesTaxPct: "sales_tax_pct", salesTax: "sales_tax", remodelTax: "remodel_tax", taxes: "taxes", bond: "bond",
  feesAndBond: "fees_and_bond", total: "total", perSf: "per_sf", remodelPct: "remodel_pct", materialSubTotal: "material",
};

const chain = [];
[["Seal", "seal"], ["Seal (+Jnts)", "seal-jnts"]].forEach(([tab, slug]) => {
  const oracle = JSON.parse(fs.readFileSync(path.join(ORACLE, slug + ".json"), "utf8"));
  oracle.vectors.forEach((v) => {
    const i = v.in, a = v.out.answers;
    const skip = a.hardBid ? "hard bid"
      : i.bondPct ? "bond"
      : (i.travel === "template" || (i.travel === undefined && !a.local)) ? "lodging" : null;
    if (skip) { chain.push({ tab: tab, id: v.id, skipped: skip }); return; }
    const m = modelFor(tab);
    m.conditions = Object.assign({}, m.conditions, {
      local: !!a.local, taxable: !!a.taxable, prevailing_wage: !!a.prevailingWage, remodel_tax: !!a.remodel,
    });
    const sec = m.tabs[tab];
    sec.takeoff = [{ assembly_id: "", assembly_name: "", measurement: i.sf, unit: "SF" }];
    sec.labor = i.labor ? [{ id: "seal-labor", label: "Crew", guys: 1, days: i.labor, rate: 1, unit: "hours" }] : [];
    sec.contingency = i.contingency || 0;
    sec.fees = i.fees || 0;
    m.travel = B.travelCostsSeed(70, 45);
    m.travel.lodging = { label: "Lodging", enabled: !!i.travel, qty: 1, qty_auto: false, rate: i.travel || 0 };
    // Seal (+Jnts) reads its remodel RATE from Seal (B75 is =Seal!B75) and its remodel answer from the same cell the case
    // typed on the (+Jnts) tab: a remodel job with no rate typed is priced at Seal's rate, 0 (bid-engine-harness.js says why)
    let rate = a.remodel && i.remodelPct !== undefined ? i.remodelPct : undefined;
    if (tab === "Seal (+Jnts)" && a.remodel && i.remodelPct === undefined) rate = 0;
    const r = B.priceSection(m, tab, {
      material: () => ({ material: i.material || 0, tooling: i.tooling || 0 }),
      remodel_rate: rate,
    });
    const wrong = r.priceable === false ? ["unpriceable: " + r.reason]
      : Object.keys(KEYS).filter((k) => v.out[k] !== undefined && v.out[k] !== null && !same(v.out[k], r[KEYS[k]]))
        .map((k) => k + ": workbook " + v.out[k] + ", v2 " + r[KEYS[k]]);
    chain.push({ tab: tab, id: v.id, wrong: wrong, kind: B.sectionsOf(m).filter((e) => e.tab === tab)[0].kind,
                 profile: B.sectionsOf(m).filter((e) => e.tab === tab)[0].profile, total: r.total, gpPct: r.gp_pct });
  });
});

// ── the jobs: typed into the template, priced through the library ───────────────────────────────────────────────
const assemblyFor = (tab, spec) => {
  const jf = spec.jf !== undefined ? spec.jf : tab === "Seal (+Jnts)";
  const coats = spec.coats === 1 ? 1 : 2;
  const id = "wb-seal-" + (jf ? "jnts-" : "") + (coats === 1 ? "1-coat" : "2-coats");
  const asm = asms.find((x) => x.id === id);
  if (!asm) throw new Error("the library plan has no assembly " + id);
  return asm;
};

const jobs = [];
golden.cases.forEach((c) => {
  const spec = c.in;
  const sf = spec.sf;
  const asm = assemblyFor(c.tab, spec);
  const m = modelFor(c.tab);
  const sec = m.tabs[c.tab];
  sec.takeoff = [{ assembly_id: asm.id, assembly_name: asm.name, measurement: sf, unit: "SF" }];
  // the sheet's own labor dollars, as hours at $1: the days a job types are the estimator's in v2, so what is proved is
  // the material, the tooling and everything after them
  sec.labor = c.out.labor > 0 ? [{ id: "seal-labor", label: "Crew", guys: 1, days: c.out.labor, rate: 1, unit: "hours" }] : [];
  const material = (entry) => S.sectionMaterial(entry.section.takeoff, {
    items: items, sf: B.takeoffSf(entry.section.takeoff), reno: !!spec.reno,
    rowPrice: (row) => LIB.priceAssembly(asm, items, B.num(row.measurement)),
  });
  const raw = material({ section: sec });
  const r = B.priceSection(m, c.tab, { material: material });
  jobs.push({
    id: c.id, tab: c.tab, material_raw: raw.material, patch: raw.patch, tooling_in: raw.tooling,
    priceable: r.priceable !== false, material: r.material, material_total: r.material_total, tooling: r.tooling,
    labor: r.labor, sub_total: r.sub_total, gp_pct: r.gp_pct, sales_tax: r.sales_tax, remodel_tax: r.remodel_tax,
    total: r.total, kind: B.sectionsOf(m).filter((e) => e.tab === c.tab)[0].kind,
  });
});

console.log(JSON.stringify({ chain: chain, jobs: jobs }));
