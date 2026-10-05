// Appended to polish-estimate-harness.js's prelude by saved-bid-harness.js: `build`, `blob`, `clone`,
// `B`, `MODEL`, `ITEMS`, `ASMS` and the rest are in scope.

// What the pre-B1 code wrote for a polish bid with every labor row filled in. `Travel` is the OLD
// label; there is no `travel` block, no `distance`, no per-row `enabled`.
const OLD_TRAVEL = { id: "travel", label: "Travel", guys: 6.5, days: 2, rate: 33, unit: "hours",
                     guys_auto: true };
function staged(over) {
  return Object.assign({
    version: 2,
    takeoff: [
      { assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 12500, unit: "SF" },
      { assembly_id: "a2", assembly_name: "Cove Base", measurement: 200, unit: "LF" },
      { assembly_id: "a5", assembly_name: "Densifier Only", measurement: 5000, unit: "SF" },
    ],
    labor: [
      { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
      { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
      { id: "jointfill", label: "Joint filler", guys: 3, days: 1, rate: 33 },
      clone(OLD_TRAVEL),
    ],
    conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false,
                  bond: false, dye: true, joint_filler: true, remove_existing_jf: false },
    contingency: 0, fees: 0, totals: {},
  }, over || {});
}

const FIXTURES = {
  // A. a local job, Travel row typed with 2 hours, dye + joint filler on.
  v2_local_travel_row: { polish_estimate: staged() },
  // B. a FAR job as the old intake saved it: local:false, and nothing to say how far. Lodging and
  //    per diem did not exist, so they must price nothing here.
  v2_far_job_no_distance: { polish_estimate: staged({
    conditions: { local: false, prevailing_wage: false, taxable: true, remodel_tax: true,
                  bond: false, dye: false, joint_filler: false, remove_existing_jf: false } }),
    county_remodel_rate: 0.07975 },
  // C. a Travel row an estimator renamed, and a custom labor line.
  v2_renamed_travel_and_custom_line: { polish_estimate: staged({
    labor: [
      { id: "polishing", label: "Polishing", guys: 4, days: 4, rate: 35 },
      { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 35 },
      { id: "jointfill", label: "Joint filler", guys: 3, days: 1, rate: 35 },
      Object.assign(clone(OLD_TRAVEL), { label: "Drive time", rate: 35, days: 3 }),
      { id: "custom-1", label: "Saw cutting", guys: 2, days: 1, rate: 40 },
    ] }) },
  // D. a draft saved BEFORE Travel existed (no travel row at all).
  v2_before_travel_row: { polish_estimate: staged({
    labor: [
      { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 },
      { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 32.2 },
    ] }) },
  // E. v1: named areas with SF and no assemblies.
  v1_areas: { polish_estimate: { areas: [
    { name: "Warehouse", sf: 9000 }, { name: "Offices", sf: 1500 }],
    polishing: { crew: 3, days: 4 }, conditions: { taxable: true } } },
};

function savedBlob(f) {
  // A full address, so a lookup COULD be asked: a saved bid must not ask it.
  const over = { polish_estimate: clone(f.polish_estimate), address: "1 Water Works Dr",
    city: "Kansas City", state: "KS", zip: "66101" };
  if (f.county_remodel_rate !== undefined) over.county_remodel_rate = f.county_remodel_rate;
  // The old estimate page wrote polish_sf as the takeoff total on every save, and the old intake
  // had no second SF box, no Drawings fields and no local answer. None of those keys are present.
  over.polish_sf = f.polish_estimate.takeoff ? B.takeoffSf(f.polish_estimate.takeoff) : 10500;
  return blob(over);
}

// THE LIBRARY AS IT IS ON STAGING NOW: defaults for every kind, a company labor rate that is not
// the shipped $33, a calculator, a far distance. A saved bid must ignore ALL of it.
const LIBRARY_ON = {
  labor: [
    { id: "travel", name: "Travel", rate: "41.00", unit: "hours", guys_auto: true, favorite: true,
      default_on: false },
    { id: "lab-x", name: "Tint", rate: 0, unit: "days", guys_auto: false, favorite: true,
      default_on: false },
  ],
  conditionDefaults: [{ key: "joint_filler", on: true }, { key: "dye", on: true },
                      { key: "remove_existing_jf", on: true }],
  laborCalc: [
    { line_id: "polishing", mode: "sf", crew: 5, sf_per_day: 1000, hours_per_day: 10,
      guys: null, days: null, rate: null },
  ],
  markupRules: [
    { id: "m1", layout: "global", line_key: "labor_rate", formula: "50", applies: true },
    { id: "m2", layout: "global", line_key: "travel_lodging", formula: "99", applies: true },
    { id: "m3", layout: "global", line_key: "travel_per_diem", formula: "77", applies: true },
  ],
  distance: { ok: true, miles: 150, source: "google" },
  asms: ASMS.map((a) => Object.assign({}, a, { favorite: true, default_on: false })),
};

async function runOne(f, lib) {
  const b = build(Object.assign({ blob: savedBlob(f) }, lib || {}));
  await b.api.init();
  const total = b.api.bid().total;
  b.clock.fire();
  await new Promise((r) => setImmediate(r));          // a late distance answer, if one were asked
  b.clock.fire();
  const M = b.api.model();
  const lastSave = b.rec.saves[b.rec.saves.length - 1];
  return {
    total: total,
    totalAfterSettle: b.api.bid().total,
    saves: b.rec.saves.length,
    savedLump: lastSave ? lastSave.computed_bid.lump_sum : null,
    labels: (M.labor || []).map((r) => r.label),
    rates: (M.labor || []).map((r) => r.rate),
    offRows: (M.labor || []).filter((r) => r.enabled === false).length +
             (M.takeoff || []).filter((r) => r.enabled === false).length,
    takeoffRows: (M.takeoff || []).length,
    travelBlock: M.travel ? JSON.stringify({
      lodging: !!(M.travel.lodging && M.travel.lodging.enabled),
      per_diem: !!(M.travel.per_diem && M.travel.per_diem.enabled) }) : null,
    local: M.conditions && M.conditions.local,
    distanceAsked: (b.rec.distanceBodies || []).length,
  };
}

(async function () {
  const out = { fixtures: {}, withLibrary: {} };
  for (const name of Object.keys(FIXTURES)) {
    out.fixtures[name] = await runOne(FIXTURES[name]);
    out.withLibrary[name] = await runOne(FIXTURES[name], LIBRARY_ON);
  }
  // F. an intake-only blob (no polish_estimate) from the OLD live intake: System 1 SF only.
  {
    const b = build({ blob: { __draft_id: "intake-only", project_name: "Old intake", city: "Olathe",
      state: "KS", work_type: "polish", polish_sf: 8250 } });
    await b.api.init();
    out.fixtures.intake_only_no_estimate = { total: b.api.bid().total,
      sf: B.takeoffSf(b.api.model().takeoff),
      distanceAsked: (b.rec.distanceBodies || []).length };
  }
  // CONTROL: the same library on a genuinely NEW bid DOES act. Without this the withLibrary pass
  // could be green because the stub never reached the page (a vacuous invariant).
  {
    const nb = blob({ polish_sf: 10000, address: "1 Water Works Dr", city: "Kansas City",
      state: "KS", zip: "66101" });
    delete nb.polish_estimate;
    const b = build(Object.assign({ blob: nb }, LIBRARY_ON));
    await b.api.init();
    for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
    const M = b.api.model();
    out.control = { rates: M.labor.map((r) => r.rate), labels: M.labor.map((r) => r.label),
      travel: JSON.stringify({ lodging: !!((M.travel || {}).lodging || {}).enabled,
                               per_diem: !!((M.travel || {}).per_diem || {}).enabled }),
      local: M.conditions.local, takeoffRows: M.takeoff.length,
      offRows: M.labor.filter((r) => r.enabled === false).length };
  }
  // G. B5 low: switching OFF the only SF takeoff row. The floor is still MEASURED; only the price
  //    drops it. polish_sf on file must stay the floor (not 0), and a second page that locks on it
  //    must keep its lock -- the lock decision is B.measuredSf, so the harness reports that too.
  {
    const one = { polish_estimate: { version: 2,
      takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 12500, unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }],
      conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } } };
    const b = build({ blob: savedBlob(one) });
    await b.api.init();
    const before = { total: b.api.bid().total, sf: b.api.bid().sf };
    clickOn(b, '[data-on-tk="0"]');
    b.clock.fire();
    const last = b.rec.saves[b.rec.saves.length - 1];
    const M = b.api.model();
    out.offOnly = { before: before, afterTotal: b.api.bid().total, afterPricedSf: b.api.bid().sf,
      rowEnabled: M.takeoff[0].enabled, savedPolishSf: last.polish_sf,
      computedSf: last.computed_bid.polish_sf,
      measured: B.measuredSf(M.takeoff), priced: B.takeoffSf(M.takeoff),
      sameFloorCarrierOff: B.measuredSf([
        { unit: "SF", measurement: 5000, enabled: false },
        { unit: "SF", measurement: 5000, same_floor: true }]),
      lfOnly: B.measuredSf([{ unit: "LF", measurement: 900 }]) };
    // reopened: nothing re-seeds over the off row, intake's boxes (8,250 / 1,000) are not reapplied
    const re = build({ blob: Object.assign(savedBlob(one), { polish_estimate: M, polish_sf: last.polish_sf,
      polish_2_sf: "" }) });
    await re.api.init();
    out.offOnly.reopenedMeasurement = re.api.model().takeoff.map((r) => r.measurement);
    out.offOnly.reopenedRows = re.api.model().takeoff.length;
  }
  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
