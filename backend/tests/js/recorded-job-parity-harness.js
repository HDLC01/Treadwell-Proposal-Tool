"use strict";
/* A REAL JOB, PRICED THROUGH v2, SET BESIDE WHAT KYLE'S WORKBOOK PRICED IT AT (Hanz, 2026-10-16: "we just need the
 * price to be the same to the centavos").
 *
 *   node recorded-job-parity-harness.js <frontend dir> <plan.json> <recorded_job.json>
 *
 * The recorded job (tests/fixtures/recorded_job_2026_10.json) is a Polish + Epoxy job Kyle priced on his workbook and
 * proposed in October 2026, anonymised: its inputs as he typed them and every figure his sheet answered. This builds
 * the same job as v2 would hold it, on the library backend/ops/seed_library_from_workbook.py plans (--json), and prices
 * it with js/bid-model.js (priceSection for Epoxy, polishBid for Polish), the epoxy-takeoff and seal-takeoff modules
 * and library-core, the page's own engines. Kyle's typed overrides (a supplier discount, a shipping rate, a discount
 * line) go in as the section's `adjust`, the way the Review step's boxes write them.
 *
 * Prints, as its last line, { epoxy: {...figures}, polish: {...figures} }.
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const job = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));

const B = require(path.join(FRONTEND, "js", "bid-model.js"));
const L = require(path.join(FRONTEND, "js", "library-core.js"));
const X = require(path.join(FRONTEND, "js", "epoxy-takeoff.js"));
const SL = require(path.join(FRONTEND, "js", "seal-takeoff.js"));

const items = plan.items;
const asms = plan.assemblies;
const norm = (t) => String(t).replace(/\s+/g, " ").trim();
const byName = new Map(asms.map((a) => [norm(a.name), a]));
function asmNamed(name) {
  const hit = byName.get(norm(name));
  if (!hit) throw new Error("the library has no assembly called " + name);
  return hit;
}
const row = (asm, m, unit, sameFloor) => Object.assign({ assembly_id: asm.id, assembly_name: asm.name, measurement: m, unit: unit },
  sameFloor ? { same_floor: true } : {});

const FIGURES = ["material", "shipping", "material_total", "labor", "burden", "tooling", "sub_total", "gp", "hard_bid",
  "super_pto", "soft_costs", "sales_tax", "remodel_tax", "total"];
const pick = (r) => Object.fromEntries(FIGURES.map((k) => [k, r[k] === undefined ? 0 : r[k]]));

// ── Epoxy ──────────────────────────────────────────────────────────────────────────────────────────────────────────
function epoxy(spec, adjust, cond) {
  const root = Object.assign({}, B.freshModel(), { kind: "off" });
  const m = B.activateSection(root, "Epoxy", "base", {});
  m.conditions = Object.assign({}, m.conditions, { taxable: true, remodel_tax: true, prevailing_wage: false, local: true },
    cond || {});
  const s = m.tabs.Epoxy;
  s.takeoff = [row(asmNamed(spec.system), spec.sf, "SF")];
  if (spec.primer) s.takeoff.push(row(asmNamed("Primer: " + spec.primer), spec.sf, "SF", true));
  if (spec.cove) s.takeoff.push(row(asmNamed("Cove: " + spec.cove), spec.lf, "LF"));
  s.labor = [{ id: "epoxy-install", label: "Epoxy install", guys: spec.guys, days: spec.days, rate: spec.rate, unit: "days" }];
  if (adjust) s.adjust = adjust;
  // the library as this section buys it: the page's itemsFor is exactly this (library-core itemsForBid over the
  // section's materialAdjust)
  const lib = L.itemsForBid(items, B.materialAdjust(s.adjust));
  const priceRow = (r) => { const a = asms.find((x) => x.id === r.assembly_id); return a ? L.priceAssembly(a, lib, B.num(r.measurement)) : null; };
  const r = B.priceSection(m, "Epoxy", {
    material: (e) => {
      const t = e.section.takeoff;
      const mat = X.sectionMaterial(t, { items: lib, sf: B.takeoffSf(t), rowPrice: priceRow, pool: B.poolsPacks(e.section) });
      return { material: mat.material, tooling: mat.tooling };
    },
    remodel_rate: spec.remodel_rate,
  });
  return Object.assign(pick(r), { raw_material: X.sectionMaterial(s.takeoff, { items: lib, sf: B.takeoffSf(s.takeoff),
    rowPrice: priceRow, pool: B.poolsPacks(s) }).material });
}

// ── Polish ─────────────────────────────────────────────────────────────────────────────────────────────────────────
function polish(spec, adjust, profile) {
  const m = B.freshModel();
  m.profile = profile || "polish-rev3@1";
  m.conditions = Object.assign({}, m.conditions, { taxable: true, remodel_tax: true, prevailing_wage: false, local: true,
    dye: !!spec.dye, joint_filler: !!spec.joint_filler });
  m.takeoff = [row(asmNamed(spec.system), spec.sf, "SF")];
  m.labor = spec.labor.map((l) => ({ id: l.id, label: l.label, guys: l.guys, days: l.days, rate: spec.rate, unit: "days" }));
  if (adjust) m.adjust = adjust;
  const sf = B.takeoffSf(m.takeoff);
  // the page's polishMaterialIn: the takeoff rows, Dye and Joint Filler by the job's conditions (bid-model's dyeCost and
  // jointFillerCost, which test_polish_estimate_page.py pins equal to the reserved library rows), and the patch line
  const rows = m.takeoff.reduce((t, r) => t + L.priceAssembly(asmNamed(spec.system), items, B.num(r.measurement)).total, 0);
  const mat = rows + B.dyeCost(sf, !!spec.dye) + B.jointFillerCost(sf, !!spec.joint_filler);
  const patch = B.polishPatchOn(m, B.ROOT_TAB) ? SL.patchCost(items, sf, spec.reno === true) : 0;
  const r = B.polishBid(m, B.ROOT_TAB, { material: () => ({ material: mat, patch: patch }), remodel_rate: spec.remodel_rate });
  return Object.assign(pick(r), { raw_material: mat + patch, patch: patch });
}

const out = {
  epoxy: epoxy(job.epoxy.in, job.epoxy.adjust),
  epoxyNoOverrides: epoxy(job.epoxy.in, null),
  polish: polish(job.polish.in, job.polish.adjust),
};

// THE SAME JOB AS A HARD BID (Hanz, 2026-10-17): the Review step's Hard bid switch (the section's adjust.hard_bid), Kyle's
// rule in his own words: 4% from a $60,000 sub-total, 2.5% on a local job from $13,000, until a discount is typed.
const KYLE = { supplier_pct: "20", ship_pct: "6" };
const big = Object.assign({}, job.epoxy.in, { sf: job.epoxy.in.sf * 3, lf: job.epoxy.in.lf * 3, days: job.epoxy.in.days * 3 });
const ruleOn = (() => {
  const rev3 = B.freshModel(); rev3.profile = "polish-rev3@1";
  const rev2 = B.freshModel(); rev2.profile = "polish-rev2@1";
  const ep = B.activateSection(Object.assign({}, B.freshModel(), { kind: "off" }), "Epoxy", "base", {});
  const gy = B.activateSection(Object.assign({}, B.freshModel(), { kind: "off" }), 'Gyp (USG 1-8")', "base", {});
  return { rev3: B.hardBidRuleOn(rev3, B.ROOT_TAB), rev2: B.hardBidRuleOn(rev2, B.ROOT_TAB),
           epoxy: B.hardBidRuleOn(ep, "Epoxy"), gyp: B.hardBidRuleOn(gy, 'Gyp (USG 1-8")'), nothing: B.hardBidRuleOn(rev3, "Nope") };
})();
out.hardBid = {
  epoxy: epoxy(job.epoxy.in, Object.assign({ hard_bid: true }, KYLE)),
  epoxyTyped: epoxy(job.epoxy.in, Object.assign({ hard_bid: true }, job.epoxy.adjust)),
  epoxyDollars: epoxy(job.epoxy.in, Object.assign({ hard_bid: true, discount_amt: "500" }, KYLE)),
  epoxyNotLocal: epoxy(job.epoxy.in, Object.assign({ hard_bid: true }, KYLE), { local: false }),
  epoxyBig: epoxy(big, { hard_bid: true }),
  epoxyBigOff: epoxy(big, null),
  polish: polish(job.polish.in, { hard_bid: true }),
  polishRev2: polish(job.polish.in, { hard_bid: true }, "polish-rev2@1"),
  ruleOn: ruleOn,
  kept: { on: B.normalizeAdjust({ hard_bid: true }), notTrue: B.normalizeAdjust({ hard_bid: "true" }),
          ruleKeepsIt: B.materialOnlyAdjust({ hard_bid: true, gp_pct: "30" }) },
};
console.log(JSON.stringify(out));
