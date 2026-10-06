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

// ── THE NEWEST SHAPES ───────────────────────────────────────────────────────────────────────────
// Everything above is a bid saved BEFORE Kyle's B1-B8 batches. What staging's page writes TODAY holds
// more: the Lodging / Per Diem block, a saved distance, the Labor Calculator's `calc_default` and
// `hours_per_day`, `rate_default` stamps, rows saved switched off (a library default with
// default_on false), `same_floor` rows, the bid's own coverage (a row's `coverage`, an assembly row's
// `line_cov`, the model's `cond_cov`), Fees + Textura with its `fees_default`, `no_travel_labor`,
// `conditions_shown`, and a stale `totals` snapshot the page must never price from.
//
// Written from a real one: the structure of the first fixture below is what a NEW bid with the
// library's defaults on saves after its first edit (captured from this harness's own `control`
// scenario). The totals are pinned in test_polish_saved_bid_safety.py from origin/staging at the
// commit named there, so the v2 program's refactors (the model passthrough, the save patch, the
// profile engine, multi-section estimates) cannot move a bid somebody already saved.
const ADDR_KEY = "1 water works dr|kansas city|ks|66101";          // savedBlob's address, as distanceKey writes it
const RESERVED_ITEMS = [
  { id: "dye", name: "Dye", unit: "SF", buy_qty: 1, unit_cost: 0.14, coverage: 1, waste_pct: 0, roundup: false },
  { id: "joint-filler-kit", name: "Joint Filler (10 gal kit)", unit: "Kit", buy_qty: 1, unit_cost: 500,
    coverage: 3500, waste_pct: 0, roundup: true },
];
function plainLabor(over) {
  return [
    { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33, rate_default: 33 },
    { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33, rate_default: 33 },
    { id: "jointfill", label: "Joint filler", guys: 3, days: 1, rate: 33, rate_default: 33 },
  ].concat(over || []);
}
function newest(over) {
  return Object.assign({
    version: 2,
    takeoff: [
      { assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 12500, unit: "SF" },
      { assembly_id: "a2", assembly_name: "Cove Base", measurement: 200, unit: "LF" },
      { assembly_id: "a5", assembly_name: "Densifier Only", measurement: 5000, unit: "SF" },
    ],
    labor: plainLabor(),
    conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false, bond: false,
                  dye: false, joint_filler: false, remove_existing_jf: false },
    contingency: 0, fees: 0, totals: {},
  }, over || {});
}

const NEWEST = {
  // 1. A FAR JOB, saved with its distance and both travel lines ON (auto quantities), a Travel Labor
  //    row carrying the new-bid markers (`hours_seed`, `guys_auto`, `rate_default`), and a `totals`
  //    snapshot that is deliberately wrong: the page prices from the model, never from that.
  v2_travel_block_far_job: { polish_estimate: newest({
    labor: plainLabor([{ id: "travel", label: "Travel Labor", guys: 19.5, days: 5, rate: 33, unit: "hours",
                         guys_auto: true, hours_seed: 5, rate_default: 33 }]),
    conditions: { local: false, prevailing_wage: false, taxable: true, remodel_tax: true, bond: false,
                  dye: true, joint_filler: true, remove_existing_jf: false },
    travel: { lodging: { label: "Lodging", enabled: true, qty: 19.5, qty_auto: true, rate: 70, rate_default: 70 },
              per_diem: { label: "Per Diem", enabled: true, qty: 19.5, qty_auto: true, rate: 45, rate_default: 45 } },
    distance: { miles: 150, source: "google", key: ADDR_KEY },
    conditions_shown: {},
    totals: { total: 11111, sub_total: 99, gp: 5 } }),
    extra: { county_remodel_rate: 0.07975 } },

  // 2. TYPED QUANTITIES AND HAND FLIPS: lodging typed (12 nights at $85) and flipped by hand, per diem
  //    switched OFF by hand on a far job, Travel Labor with typed Guys and typed hours, a distance the
  //    estimator typed. None of it may be re-derived on open.
  v2_travel_typed_and_hand_flipped: { polish_estimate: newest({
    labor: [
      { id: "polishing", label: "Polishing", guys: 4, days: 4, rate: 35, rate_default: 33 },
      { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 35, rate_default: 33 },
      { id: "jointfill", label: "Joint filler", guys: 3, days: 1, rate: 35, rate_default: 33 },
      { id: "travel", label: "Travel Labor", guys: 6, days: 4, rate: 41, unit: "hours", guys_auto: false,
        hours_seed: "", rate_default: 33 },
    ],
    conditions: { local: false, prevailing_wage: true, taxable: true, remodel_tax: false, bond: false,
                  dye: false, joint_filler: false, remove_existing_jf: false },
    travel: { lodging: { label: "Lodging", enabled: true, qty: 12, qty_auto: false, rate: 85, hand: true, rate_default: 70 },
              per_diem: { label: "Per Diem", enabled: false, qty: 19.5, qty_auto: true, rate: 52, hand: true, rate_default: 45 } },
    distance: { miles: 82.3, source: "typed", key: "" } }) },

  // 3. LABOR CALCULATOR ROWS. A "From SF" line whose days the calculator filled for 13,000 SF and
  //    whose takeoff has since grown to 20,000: opening must NOT re-follow (that happens only when
  //    the SF changes in a session). A line the estimator typed over (calculator said 1 day, the bid
  //    says 2), a fixed line on 10-hour days, a custom line.
  v2_labor_calculator_rows: { polish_estimate: newest({
    takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 20000, unit: "SF" }],
    labor: [
      { id: "polishing", label: "Polishing", guys: 5, days: 13, rate: 50, hours_per_day: 10,
        calc_default: { guys: 5, days: 13, rate: 50, hours_per_day: 10, sf_per_day: 1000 } },
      { id: "mockup", label: "Mock-up", guys: 3, days: 2, rate: 50,
        calc_default: { guys: 3, days: 1, rate: 50, hours_per_day: 8 } },
      { id: "jointfill", label: "Joint filler", guys: 2, days: 3, rate: 50, hours_per_day: 10,
        calc_default: { guys: 2, days: 3, rate: 50, hours_per_day: 10 } },
      { id: "travel", label: "Travel Labor", guys: 0, days: "", rate: 50, unit: "hours", guys_auto: true,
        enabled: false, hours_seed: "", rate_default: 50 },
      { id: "lab-x", label: "Saw cutting", guys: 2, days: 1, rate: 40, unit: "days", guys_auto: false,
        rate_default: 40 },
    ] }) },

  // 4. DEFAULT ROWS, as a new bid with the library's defaults saves them: one ON default carries the
  //    floor, the others are `same_floor` (priced, not counted twice), a default with default_on false
  //    is saved `enabled: false`, an item default, a labor default switched off, a card hidden.
  v2_default_rows_saved: { polish_estimate: newest({
    takeoff: [
      { assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF" },
      { assembly_id: "a3", assembly_name: "Grind & Seal", measurement: 10000, unit: "SF", same_floor: true },
      { assembly_id: "a5", assembly_name: "Densifier Only", measurement: 10000, unit: "SF", same_floor: true, enabled: false },
      { assembly_id: "a2", assembly_name: "Cove Base", measurement: "", unit: "LF", enabled: false },
      { kind: "item", item_id: "i1", item_name: "OPF", coverage: "", measurement: 10000, unit: "SF", same_floor: true, enabled: false },
    ],
    labor: plainLabor([
      { id: "travel", label: "Travel Labor", guys: 19.5, days: "", rate: 33, unit: "hours", guys_auto: true,
        enabled: false, hours_seed: "", rate_default: 33 },
      { id: "lab-x", label: "Tint", guys: 2, days: 2, rate: 50, unit: "days", guys_auto: false, enabled: false, rate_default: 50 },
      { id: "lab-y", label: "Saw", guys: 2, days: 1, rate: 50, unit: "days", guys_auto: false, rate_default: 50 },
    ]),
    conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false, bond: false,
                  dye: true, joint_filler: true, remove_existing_jf: true },
    travel: { lodging: { label: "Lodging", enabled: false, qty: 19.5, qty_auto: true, rate: 70, rate_default: 70 },
              per_diem: { label: "Per Diem", enabled: false, qty: 19.5, qty_auto: true, rate: 45, rate_default: 45 } },
    conditions_shown: { dye: false } }) },

  // 5. THIS BID'S OWN COVERAGE: an assembly row with a coverage typed on two of its lines
  //    (`line_cov`, keyed by the line's position), a material row with its own `coverage`, and the
  //    Joint Filler and Dye cards' coverage (`cond_cov`) over the library's reserved rows.
  v2_coverage_overrides: { polish_estimate: newest({
    takeoff: [
      { assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 12500, unit: "SF", line_cov: { 0: 300, 1: 700 } },
      { kind: "item", item_id: "i4", item_name: "Densifier", coverage: 500, measurement: 5000, unit: "SF" },
      { assembly_id: "a2", assembly_name: "Cove Base", measurement: 200, unit: "LF", line_cov: { 0: "150" } },
    ],
    conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false, bond: false,
                  dye: true, joint_filler: true, remove_existing_jf: false },
    cond_cov: { joint_filler: 3000, dye: 2 } }),
    opts: { items: ITEMS.concat(RESERVED_ITEMS) } },

  // 6. FEES + TEXTURA AND CONTINGENCY, a library that said "no Travel Labor" (so the page must not
  //    put the row back), travel rates the bid kept from the day it was saved, a hidden Dye card.
  v2_fees_contingency_no_travel_labor: { polish_estimate: newest({
    labor: plainLabor(),
    no_travel_labor: true,
    fees: 750, fees_default: 750, contingency: 1200,
    conditions: { local: true, prevailing_wage: true, taxable: true, remodel_tax: false, bond: false,
                  dye: false, joint_filler: true, remove_existing_jf: false },
    travel: { lodging: { label: "Lodging", enabled: false, qty: 19.5, qty_auto: true, rate: 65, rate_default: 65 },
              per_diem: { label: "Per Diem", enabled: false, qty: 19.5, qty_auto: true, rate: 40, rate_default: 40 } },
    conditions_shown: { dye: false } }) },

  // 7. WHERE THE REMODEL RATE COMES FROM: a rate typed for this address beats the county's, and a
  //    county that was picked with no rate (Missouri) is an explicit zero, not the Kansas floor.
  v2_remodel_rate_override_wins: { polish_estimate: newest({
    conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: true, bond: false,
                  dye: false, joint_filler: false, remove_existing_jf: false } }),
    extra: { remodel_rate_override: 0.0715, county_remodel_rate: 0.07975 } },
  v2_remodel_county_without_a_rate: { polish_estimate: newest({
    conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: true, bond: false,
                  dye: false, joint_filler: false, remove_existing_jf: false } }),
    extra: { county: "Jackson" } },
};

function savedBlob(f) {
  // A full address, so a lookup COULD be asked: a saved bid must not ask it.
  const over = { polish_estimate: clone(f.polish_estimate), address: "1 Water Works Dr",
    city: "Kansas City", state: "KS", zip: "66101" };
  if (f.county_remodel_rate !== undefined) over.county_remodel_rate = f.county_remodel_rate;
  if (f.extra) Object.assign(over, clone(f.extra));       // a key the draft carries beside the estimate
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
  const b = build(Object.assign({ blob: savedBlob(f) }, lib || {}, f.opts || {}));
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
    // What the page is holding after it opened, for the newest shapes' own assertions: every saved
    // figure the page could re-derive, and must not.
    laborDays: (M.labor || []).map((r) => r.days),
    laborGuys: (M.labor || []).map((r) => r.guys),
    laborHoursPerDay: (M.labor || []).map((r) => r.hours_per_day === undefined ? null : r.hours_per_day),
    calcDefaults: (M.labor || []).map((r) => r.calc_default ? JSON.stringify(r.calc_default) : null),
    rateDefaults: (M.labor || []).map((r) => r.rate_default === undefined ? null : r.rate_default),
    travelDetail: M.travel ? JSON.stringify(M.travel) : null,
    distance: M.distance ? JSON.stringify(M.distance) : null,
    takeoff: (M.takeoff || []).map((r) => [r.measurement, r.enabled === false, !!r.same_floor,
      r.coverage === undefined ? null : r.coverage, r.line_cov ? JSON.stringify(r.line_cov) : null]),
    condCov: M.cond_cov ? JSON.stringify(M.cond_cov) : null,
    conditionsShown: M.conditions_shown ? JSON.stringify(M.conditions_shown) : null,
    fees: M.fees,
    feesDefault: M.fees_default === undefined ? null : M.fees_default,
    contingency: M.contingency,
    noTravelLabor: !!M.no_travel_labor,
    sf: b.api.bid().sf,
  };
}

/** Save the bid (the 600 ms autosave, forced), then open what was saved in a fresh page. The saved
 *  bid must come to the same total, and opening it must still write nothing: a save/reopen that
 *  drifted would move a customer's price on the SECOND open of a bid, which no single-open test sees. */
async function roundTrip(f, lib) {
  const first = build(Object.assign({ blob: savedBlob(f) }, lib || {}, f.opts || {}));
  await first.api.init();
  first.api.saveSoon();
  first.clock.fire();
  const saved = first.rec.saves[first.rec.saves.length - 1];
  const again = build(Object.assign({ blob: clone(first.store.blob) }, lib || {}, f.opts || {}));
  await again.api.init();
  const totalAgain = again.api.bid().total;
  again.clock.fire();
  return {
    totalFirst: first.api.bid().total,
    savedLump: saved ? saved.computed_bid.lump_sum : null,
    savedSf: saved ? saved.polish_sf : null,
    totalAgain: totalAgain,
    savesAgain: again.rec.saves.length,
    cellsKeepTheConditions: saved ? JSON.stringify(saved.cell_values) : null,
  };
}

(async function () {
  const out = { fixtures: {}, withLibrary: {}, newest: { fixtures: {}, withLibrary: {}, roundTrip: {} } };
  for (const name of Object.keys(FIXTURES)) {
    out.fixtures[name] = await runOne(FIXTURES[name]);
    out.withLibrary[name] = await runOne(FIXTURES[name], LIBRARY_ON);
  }
  // The newest shapes: opened plain, opened with a library full of defaults (a saved bid ignores
  // all of it), and saved-then-reopened.
  for (const name of Object.keys(NEWEST)) {
    out.newest.fixtures[name] = await runOne(NEWEST[name]);
    out.newest.withLibrary[name] = await runOne(NEWEST[name], LIBRARY_ON);
    out.newest.roundTrip[name] = await roundTrip(NEWEST[name]);
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
