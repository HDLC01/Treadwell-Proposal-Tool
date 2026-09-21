"use strict";
/* Run the REAL polish bid engine out of frontend/js/polish-bid-core.js and report what it says.
 *
 * WHY THE VECTORS LIVE HERE. test_polish_markup_parity.py re-derives every one of these numbers in
 * Python by transliterating Kyle's formulas, then compares. If each side owned its own input list
 * the two could drift apart and still agree line for line — the test would be comparing two
 * different jobs and passing. So the inputs are declared once, here, and the pytest reads them
 * back out of the JSON alongside the answers.
 *
 * The vectors are chosen for the places this chain can be wrong while still looking like a bid:
 *
 *   * BOTH SIDES OF EVERY GP EDGE. B67 uses strictly `<`, so 6,500 belongs to the 45% band, not
 *     the 52% one. Each edge vector lands the sub-total EXACTLY on the boundary — the material
 *     figures below are back-solved for that, which is why they look arbitrary.
 *   * THE HARD-BID GATE, all four ways: the 60k rule, the local-and-13k rule, the else-less IF
 *     that yields nothing, and a line that is genuinely NEGATIVE (ROUNDUP away from zero).
 *   * THE TWO TAX BASES. Sales tax on materials only; the remodel tax on the labor side and the
 *     markups and never on materials. Every tax vector carries real materials AND real labor, so
 *     swapping the two bases moves the answer instead of cancelling out.
 *   * THE REMODEL TAX'S RATE, which is the ONE figure this engine does not take from the sheet.
 *     B75 hardcodes 10%; Kansas charges the state 6.5% plus the county portion on commercial
 *     remodel LABOR, so markupChain takes `remodel_rate` from the project's county. Vectors
 *     below pin a real county rate, a lower one, the no-county fallback in all three shapes it
 *     arrives in, a Missouri county's explicit 0 (exempt, and NOT the fallback), a rate handed in
 *     with the toggle OFF (which must stay untaxed), and that 10% is no longer reachable at all.
 *   * CONTINGENCY, which is not just added at the end — it sits inside the super/PTO, soft-cost
 *     and remodel-tax bases, so a bid with a contingency has more than the contingency added.
 *
 * Usage: node polish-bid-harness.js   ->  one line of JSON
 */
const path = require("path");

const CORE = path.join(__dirname, "..", "..", "..", "frontend", "js", "polish-bid-core.js");
const P = require(CORE);

const OFF = { local: false, hard_bid: false, prevailing_wage: false,
              taxable: false, remodel_tax: false };
function cond(over) { return Object.assign({}, OFF, over || {}); }

// A job with materials AND labor on it, used for every on/off pair below so the only thing that
// differs between the two vectors is the flag being tested.
const JOB = { material: 12000, labor: 8000, contingency: 0, sf: 12500 };
function job(over) { return Object.assign({}, JOB, over || {}); }

/* Sub-totals are back-solved: with no labor, D64 = m + ROUNDUP(m*2%). 6,371 lands on 6,499 and
 * 6,372 on 6,500 — one dollar of material either side of a $520 swing in GP. */
const VECTORS = [
  // ── the GP bands, both sides of all four edges (B67 is strictly `<`) ────────
  { label: "GP 52%: sub-total 6,499, a dollar under the edge",
    input: { material: 6371, labor: 0, contingency: 0, conditions: cond(), sf: 10000 } },
  { label: "GP 45%: sub-total exactly 6,500",
    input: { material: 6372, labor: 0, contingency: 0, conditions: cond(), sf: 10000 } },
  { label: "GP 45%: sub-total 14,999",
    input: { material: 14704, labor: 0, contingency: 0, conditions: cond(), sf: 10000 } },
  { label: "GP 35%: sub-total exactly 15,000",
    input: { material: 14705, labor: 0, contingency: 0, conditions: cond(), sf: 10000 } },
  { label: "GP 35%: sub-total 22,499",
    input: { material: 22057, labor: 0, contingency: 0, conditions: cond(), sf: 10000 } },
  { label: "GP 32%: sub-total exactly 22,500",
    input: { material: 22058, labor: 0, contingency: 0, conditions: cond(), sf: 10000 } },
  { label: "GP 32%: sub-total 32,499",
    input: { material: 31861, labor: 0, contingency: 0, conditions: cond(), sf: 10000 } },
  { label: "GP 30%: sub-total exactly 32,500",
    input: { material: 31862, labor: 0, contingency: 0, conditions: cond(), sf: 10000 } },
  { label: "GP 30% at 60,000 with hard bid OFF, so no give-back",
    input: { material: 58823, labor: 0, contingency: 0, conditions: cond(), sf: 40000 } },

  // ── the hard-bid gate ──────────────────────────────────────────────────────
  { label: "hard bid + local, sub-total 12,999: one dollar under the 13k rule",
    input: { material: 8351, labor: 4000, contingency: 0,
             conditions: cond({ hard_bid: true, local: true }), sf: 9000 } },
  { label: "hard bid + local, sub-total exactly 13,000: -2.5%, a NEGATIVE line",
    input: { material: 8352, labor: 4000, contingency: 0,
             conditions: cond({ hard_bid: true, local: true }), sf: 9000 } },
  { label: "hard bid, NOT local, sub-total 13,000: the local gate withholds it",
    input: { material: 8352, labor: 4000, contingency: 0,
             conditions: cond({ hard_bid: true }), sf: 9000 } },
  { label: "hard bid, not local, sub-total 59,999: the else-less IF, so nothing",
    input: { material: 36861, labor: 20000, contingency: 0,
             conditions: cond({ hard_bid: true }), sf: 30000 } },
  { label: "hard bid, not local, sub-total exactly 60,000: -4%",
    input: { material: 36862, labor: 20000, contingency: 0,
             conditions: cond({ hard_bid: true }), sf: 30000 } },
  { label: "hard bid + local at 60,000: the bigger give-back wins, not -2.5%",
    input: { material: 36862, labor: 20000, contingency: 0,
             conditions: cond({ hard_bid: true, local: true }), sf: 30000 } },
  { label: "local, no hard bid, sub-total 70,000: local alone gives nothing back",
    input: { material: 46666, labor: 20000, contingency: 0,
             conditions: cond({ local: true }), sf: 30000 } },

  // ── sales tax on and off, same job otherwise ───────────────────────────────
  { label: "taxable: 9.475% on the MATERIAL total only",
    input: job({ conditions: cond({ taxable: true }) }) },
  { label: "not taxable: no sales-tax line at all",
    input: job({ conditions: cond() }) },

  // ── the remodel tax: on/off, and the RATE the county supplies ──────────────
  // Every one of these carries $12,000 of material, so a remodel base that wrongly included D33
  // would come out several hundred dollars higher and the recomputation in the pytest would catch
  // it. That is the whole reason these vectors are not material-free.
  //
  // The RATE is deliberately NOT the sheet's B75 10%. 0.07975 is Johnson County KS (6.5% state +
  // 1.475% county) out of backend/reference_tax.py, the figure Hanz and Kyle both quote. 0.0715 is
  // a lower county portion: the engine prices whatever rate it is handed, so it has to move.
  { label: "remodel at Johnson County's 7.975%: on labor + markups, never on materials",
    input: job({ remodel_rate: 0.07975, conditions: cond({ remodel_tax: true }) }) },
  { label: "remodel at a lower county rate of 7.15%: the tax follows the county",
    input: job({ remodel_rate: 0.0715, conditions: cond({ remodel_tax: true }) }) },
  // NULL IS NOT ZERO, and the next four vectors are the whole reason that distinction exists.
  //
  // Absent / null / "" is "nobody has picked a county yet" → stand up the Kansas STATE rate, 6.5%,
  // until they do. An under-charge an estimator can correct beats the sheet's invented 10%, which
  // they would have no reason to question. All three shapes must bid the SAME.
  { label: "remodel with no county picked yet: the 6.5% state floor, not the sheet's 10%",
    input: job({ conditions: cond({ remodel_tax: true }) }) },
  { label: "remodel with a null county rate: still the 6.5% floor",
    input: job({ remodel_rate: null, conditions: cond({ remodel_tax: true }) }) },
  { label: "remodel with an empty-string county rate: still the 6.5% floor",
    input: job({ remodel_rate: "", conditions: cond({ remodel_tax: true }) }) },
  // An explicit 0 is "we know the county, and its rate is nothing." Missouri taxes remodel LABOR
  // as exempt, so a Missouri county carries no remodel rate ON PURPOSE and the page passes 0.
  // Fall that 0 back to 6.5% and every Missouri remodel is charged a Kansas tax it does not owe.
  { label: "remodel in Missouri, county rate an explicit 0: exempt labor, so no tax at all",
    input: job({ remodel_rate: 0, conditions: cond({ remodel_tax: true }) }) },
  // A rate on the input is a lookup result, not a decision. Only the toggle charges the tax.
  { label: "a county rate supplied with the remodel toggle OFF: nothing is taxed",
    input: job({ remodel_rate: 0.07975, conditions: cond() }) },
  { label: "not a remodel: no remodel-tax line",
    input: job({ conditions: cond() }) },

  // ── prevailing wage on and off ─────────────────────────────────────────────
  { label: "prevailing wage: 5% escalation, and burden on labor PLUS escalation",
    input: { material: 6372, labor: 4000, contingency: 0,
             conditions: cond({ prevailing_wage: true }), sf: 9000 } },
  { label: "no prevailing wage: no escalation line",
    input: { material: 6372, labor: 4000, contingency: 0, conditions: cond(), sf: 9000 } },

  // ── contingency ────────────────────────────────────────────────────────────
  // $5,000 of contingency adds MORE than $5,000 to the bid: it is inside the super/PTO, soft-cost
  // and remodel-tax bases. Paired with the same job at zero so the pytest can see the difference.
  { label: "contingency 5,000, remodel + tax on: it feeds three markup bases",
    input: job({ contingency: 5000, remodel_rate: 0.07975,
                 conditions: cond({ taxable: true, remodel_tax: true }) }) },
  { label: "contingency 0, otherwise identical",
    input: job({ contingency: 0, remodel_rate: 0.07975,
                 conditions: cond({ taxable: true, remodel_tax: true }) }) },

  // ── the area ───────────────────────────────────────────────────────────────
  { label: "no area typed yet: per SF is null, not 0",
    input: job({ sf: 0, conditions: cond({ taxable: true }) }) },
  { label: "an area typed: per SF is the bid divided by it",
    input: job({ sf: 12500, conditions: cond({ taxable: true }) }) },

  // ── a whole realistic job, every condition on, raw sums with cents on them ─
  { label: "everything on, unrounded takeoff and labor sums",
    input: { material: 18450.75, labor: 15467.2, contingency: 2500, remodel_rate: 0.07975,
             conditions: { local: true, hard_bid: true, prevailing_wage: true,
                           taxable: true, remodel_tax: true }, sf: 14200 } },

  // ── the states the screen opens and closes in ──────────────────────────────
  { label: "nothing entered at all",
    input: { material: 0, labor: 0, contingency: 0, conditions: cond({ local: true, taxable: true }),
             sf: 0 } },
  { label: "pasted out of a spreadsheet, dollar signs and commas and all",
    input: { material: "$12,000.50", labor: "8,000", contingency: "1,000",
             conditions: cond({ taxable: true }), sf: "12,500" } }
];

const out = { vectors: [], labor: [], migrations: [] };

for (const v of VECTORS) {
  out.vectors.push({ label: v.label, input: v.input, out: P.markupChain(v.input) });
}

// ── laborCost: guys x days x rate x EIGHT HOURS ──────────────────────────────
// The first row is Kyle's own screenshot. It is what pins HOURS_PER_DAY: at 10 hours the same row
// costs $4,830, and nothing else in this file would notice.
const LABOR_ROWS = [
  { label: "Kyle's screenshot: 3 guys x 5 days x $32.20", row: { guys: 3, days: 5, rate: 32.2 } },
  { label: "the template's half-day mock-up", row: { guys: 3, days: 0.5, rate: 32.2 } },
  { label: "pasted as text", row: { guys: "3", days: "5", rate: "$32.20" } },
  { label: "no days yet costs nothing", row: { guys: 3, days: "", rate: 32.2 } },
  { label: "an empty row costs nothing", row: {} },
  { label: "a bigger crew on a longer job", row: { guys: 4, days: 6, rate: 35 } },
  { label: "half a guy is arithmetic, not a person", row: { guys: 1.5, days: 2, rate: 30 } }
];
for (const l of LABOR_ROWS) {
  out.labor.push({ label: l.label, row: l.row, cost: P.laborCost(l.row) });
}
out.laborTotal = {
  rows: [{ guys: 3, days: 5, rate: 32.2 }, { guys: 3, days: 0.5, rate: 32.2 },
         { guys: 3, days: "", rate: 32.2 }],
  total: P.laborTotal([{ guys: 3, days: 5, rate: 32.2 }, { guys: 3, days: 0.5, rate: 32.2 },
                       { guys: 3, days: "", rate: 32.2 }]),
  // Unrounded on purpose: D45 is where the sheet rounds, and markupChain does that.
  empty: P.laborTotal([]),
  nothing: P.laborTotal(null)
};

// ── takeoffSf: LF rows measure a different thing and must not join the area ──
out.takeoff = {
  mixed: P.takeoffSf([{ measurement: 9000, unit: "SF" }, { measurement: 240, unit: "LF" },
                      { measurement: "3,500", unit: "SF" }]),
  lfOnly: P.takeoffSf([{ measurement: 240, unit: "LF" }]),
  empty: P.takeoffSf([]),
  nothing: P.takeoffSf(null)
};

// ── the display helpers ──────────────────────────────────────────────────────
out.formats = {
  money: [P.money(15681), P.money(0), P.money(1234.6), P.money(-1235), P.money("")],
  money2: [P.money2(32.2), P.money2(0), P.money2(1234.567), P.money2(-32.2)],
  pct: [P.pct(0.027), P.pct(0.45), P.pct(-0.025), P.pct(0), P.pct(0.09475), P.pct(0.16),
        P.pct(-0.04), P.pct(0.07975)],
  sf: [P.fmtSf(12500), P.fmtSf(0), P.fmtSf("1,632.5")],
  // ROUNDUP is away from zero, which is the only reason the negative hard-bid line is right.
  roundUp: [P.roundUp(1.2), P.roundUp(-1.2), P.roundUp(1), P.roundUp(-1), P.roundUp(0),
            P.roundUp(110.00000000000001), P.roundUp(0.0001), P.roundUp("")],
  num: [P.num("1,200"), P.num("$32.20"), P.num(""), P.num(null), P.num("abc"), P.num(true)]
};

// ── the constants, and the two banded rates, PROBED rather than read ─────────
// The pytest pulls the sheet's own numbers out of the B67/B68/B74/B75/C46 formula text and checks
// them against these. A constant that agrees with the workbook and a function that ignores it
// would both pass a source read, so the bands are answered by the real gpPct/hardBidPct at every
// threshold the formulas name. RATES.SHEET_REMODEL is the exception that proves the rule: it is
// pinned to B75's 10% and nothing prices from it, which the remodel vectors above demonstrate.
out.constants = { rates: P.RATES, gpBands: P.GP_BANDS, hoursPerDay: P.HOURS_PER_DAY };
out.gpProbe = {};
[0, 1, 6499, 6500, 6501, 14999, 15000, 15001, 22499, 22500, 22501, 32499, 32500, 32501,
 60000, 100000].forEach(function (v) { out.gpProbe[v] = P.gpPct(v); });
out.hardBidProbe = [];
[[false, false], [false, true], [true, false], [true, true]].forEach(function (pair) {
  [0, 12999, 13000, 13001, 59999, 60000, 60001].forEach(function (v) {
    out.hardBidProbe.push({ hard_bid: pair[0], local: pair[1], sub: v,
                            pct: P.hardBidPct(v, { hard_bid: pair[0], local: pair[1] }) });
  });
});

// ── dye and joint filler: fixed formulas keyed on the polished area (Polish!E25/E29) ──
//
// Neither is a library item -- no coverage, no pack size, no vendor -- so they are not routed
// through priceAssembly/priceLine. dyeCost is a flat rate times the area; jointFillerCost is
// ROUNDUP(area / 3500) kits at a flat rate per kit. The vectors below cover: an area that
// divides evenly into 3500 (exactly one kit, and separately exactly two, so a false ceiling
// could not slip a kit in on a round number), an area that does NOT divide evenly (needs the
// round-up), an area of 0, and area not yet entered (null/undefined) -- each read against the
// condition both ON and OFF, since OFF must price at exactly 0 whatever the area is.
out.dyeJointFiller = {
  dye: {
    on_3500: P.dyeCost(3500, true),
    on_12500: P.dyeCost(12500, true),
    on_0: P.dyeCost(0, true),
    on_null: P.dyeCost(null, true),
    on_undefined: P.dyeCost(undefined, true),
    off_3500: P.dyeCost(3500, false),
  },
  jointFiller: {
    on_3500: P.jointFillerCost(3500, true),     // divides evenly -- exactly one kit
    on_3501: P.jointFillerCost(3501, true),     // one SF over -- must round UP to two kits
    on_7000: P.jointFillerCost(7000, true),     // divides evenly -- exactly two, not three
    on_0: P.jointFillerCost(0, true),
    on_null: P.jointFillerCost(null, true),
    on_undefined: P.jointFillerCost(undefined, true),
    off_3500: P.jointFillerCost(3500, false),
    off_7000: P.jointFillerCost(7000, false),
  },
};

// ── the model: fresh, migrated, and what is blocking it ──────────────────────
out.fresh = P.freshModel();

// A v1 draft, shaped like the ones on staging: named areas, worksheet-row materials, and labor
// keyed polishing/mockup/joint_filler where `crew` is the GUYS COUNT.
const V1 = {
  areas: [{ name: "Main sales floor", sf: 9000 }, { name: "Back of house", sf: "3,500" }],
  system: "S&P",
  tooling: "traditional",
  conditions: { local: false, hard_bid: true, prevailing_wage: true,
                taxable: true, remodel_tax: true },
  materials: { 17: { qty: 12500, cost: 0.15 }, 29: { qty: 4, cost: 500 } },
  added: [{ name: "Stair nosing infill", qty: 46, cost: 12.5 }],
  // `labour`, not `labor`, and it is not a typo to tidy: this is v1 SAVED DATA, and migrateModel
  // reads `model.labour`. Renamed to match the prose around it, the migration silently finds
  // nothing and every row falls back to the fresh-model seed — which is what "crew is the guys
  // count" going red actually means.
  labour: { polishing: { crew: 4, days: 6, rate: 32.2 },
            mockup: { crew: 2, days: 1, rate: 32.2 },
            joint_filler: { crew: 2, days: 2, rate: 32.2 } },
  adds: { ram_board: 240, cove_4: 60 },
  options: { salt_pepper: true, dye: true }
};

// A v2 sandbox saved on 2026-09-10, the day before Travel became a fourth labor row (#491): only
// the original three rows, an estimator-typed value that must survive (4 guys on Polishing, not
// the fresh-model default of 3), and a custom row added via "+ Add a labor line" that the Travel
// backfill must leave alone. This is "Akoya Omakase (beta test)" in miniature.
const STALE_V2_NO_TRAVEL = {
  version: 2,
  takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000,
              unit: "SF" }],
  labor: [
    { id: "polishing", label: "Polishing", guys: 4, days: 6, rate: 33.0 },
    { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33.0 },
    { id: "jointfill", label: "Joint filler", guys: 2, days: 3, rate: 33.0 },
    { id: "u_1699999999_1", label: "Demo prep", guys: 2, days: 1, rate: 40 }
  ],
  conditions: { taxable: false },
  contingency: 500
};

// The narrow window between Travel shipping (2026-09-12, priced like a crew row: no `unit`, blank
// rate, guys typed by hand) and the same day's correction to the sheet's own Guys × HOURS × $33.
// A sandbox opened in that window holds the first shape, and left alone would bill a 2-hour drive
// as 16 hours and then price it at nothing, its rate being blank. The typed `guys: 6` is the part
// that must survive: nothing auto-filled it back then, so somebody put it there on purpose.
const TRAVEL_PRE_HOURS = {
  version: 2,
  takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000,
              unit: "SF" }],
  labor: [
    { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33.0 },
    { id: "travel", label: "Travel", guys: 6, days: 2, rate: "" }
  ],
  conditions: {},
  contingency: 0
};

const MIGRATIONS = [
  { label: "a v1 draft off staging", before: V1 },
  { label: "v1 with no labor block at all", before: { areas: [{ sf: 9000 }] } },
  { label: "v1 with no areas", before: { areas: [], labour: {} } },
  { label: "nothing saved yet", before: null },
  { label: "a v2 model missing half its keys", before: { version: 2, takeoff: [], labor: null } },
  { label: "a v2 model with one condition saved", before: { version: 2, conditions: { taxable: false } } },
  { label: "a v2 draft saved before Travel existed", before: STALE_V2_NO_TRAVEL },
  { label: "a v2 draft saved while Travel was priced per day", before: TRAVEL_PRE_HOURS },
  { label: "garbage", before: "not a model" },
  { label: "a number", before: 7 },
  { label: "an array", before: [] }
];
for (const m of MIGRATIONS) {
  out.migrations.push({ label: m.label, before: m.before, after: P.migrateModel(m.before) });
}

// Migrating twice must be the same as migrating once, or every save would reshape the model again.
out.migrationIsIdempotent = JSON.stringify(P.migrateModel(P.migrateModel(V1)))
  === JSON.stringify(P.migrateModel(V1));

// Same idempotency check, aimed at the Travel backfill specifically: re-migrating an
// already-backfilled draft must not push a second Travel row onto the end.
out.staleLaborBackfillIsIdempotent = JSON.stringify(P.migrateModel(P.migrateModel(STALE_V2_NO_TRAVEL)))
  === JSON.stringify(P.migrateModel(STALE_V2_NO_TRAVEL));
// The same question for the row-already-there case, which takes the other branch entirely: one
// appends a row, the other rewrites fields on a row that exists, and only the first was covered.
out.travelFieldBackfillIsIdempotent =
  JSON.stringify(P.migrateModel(P.migrateModel(TRAVEL_PRE_HOURS)))
  === JSON.stringify(P.migrateModel(TRAVEL_PRE_HOURS));
// Travel priced per HOUR: 6 man-days × 2 hours × $33 = $396, NOT ×8 (which would be $3,168).
out.travelHourlyCost = {
  perHour: P.laborCost({ guys: 6, days: 2, rate: 33, unit: "hours" }),
  perDay: P.laborCost({ guys: 6, days: 2, rate: 33 }),
  hoursPerDay: P.HOURS_PER_DAY
};
// A44's man-day sum, over rows that are not themselves travel.
out.travelManDays = {
  sheetScreenshot: P.travelManDays([
    { guys: 3, days: 5 }, { guys: 3, days: 0.5 }, { guys: 3, days: 0.5 },
    { guys: 99, days: 99, unit: "hours" }
  ]),
  blanksContributeNothing: P.travelManDays([{ guys: 3, days: "" }, { guys: "", days: 4 }]),
  empty: P.travelManDays([])
};
// An hours row with no hours is UNUSED, not unfinished — the carve-out that keeps Review reachable.
out.travelBlockers = {
  noHours: P.blockers({ version: 2,
    takeoff: [{ assembly_id: "a1", measurement: 100, unit: "SF" }],
    labor: [{ id: "travel", label: "Travel", guys: 18, days: "", rate: 33, unit: "hours" }] }),
  // A travel row that IS being used is checked like any other. Carries `unit`/`guys_auto`/a rate
  // so migrateModel leaves it alone — a blank rate cannot be used to prove this, because the
  // migration fills one in from the sheet before blockers ever sees the row.
  hoursButNoGuys: P.blockers({ version: 2,
    takeoff: [{ assembly_id: "a1", measurement: 100, unit: "SF" }],
    labor: [{ id: "travel", label: "Travel", guys: "", days: 2, rate: 33,
              unit: "hours", guys_auto: false }] }),
  crewRowStillChecked: P.blockers({ version: 2,
    takeoff: [{ assembly_id: "a1", measurement: 100, unit: "SF" }],
    labor: [{ id: "polishing", label: "Polishing", guys: 3, days: "", rate: 33 }] })
};

out.blockers = [
  { label: "a fresh model", model: P.freshModel(), says: P.blockers(P.freshModel()) },
  { label: "a measurement with no assembly picked",
    model: null,
    says: P.blockers({ version: 2,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: 9000, unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 }],
      conditions: {}, contingency: 0 }) },
  { label: "an assembly with no measurement",
    says: P.blockers({ version: 2,
      takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: "",
                  unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 }],
      conditions: {}, contingency: 0 }) },
  { label: "an assembly with no measurement and no name either",
    says: P.blockers({ version: 2,
      takeoff: [{ assembly_id: "a1", assembly_name: "", measurement: 0, unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 }],
      conditions: {}, contingency: 0 }) },
  { label: "every takeoff row empty",
    says: P.blockers({ version: 2,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" },
                { assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 }],
      conditions: {}, contingency: 0 }) },
  { label: "a labor row with guys and a rate but no days",
    says: P.blockers({ version: 2,
      takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000,
                  unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: "", rate: 32.2 }],
      conditions: {}, contingency: 0 }) },
  { label: "ready to price: a switched-off labor row is not half-filled",
    says: P.blockers({ version: 2,
      takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000,
                  unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 },
              { id: "jointfill", label: "Joint filler", guys: 3, days: 0, rate: 32.2 },
              { id: "mockup", label: "Mock-up", guys: "", days: "", rate: "" }],
      conditions: {}, contingency: 0 }) },
  { label: "a model that is not a model at all", says: P.blockers(null) }
];

// ── the library's default labor lines ────────────────────────────────────────
//
// public.library_labor is what Library -> Default Items & Assemblies writes, and what
// GET /api/library/labor hands back. Its rows are shaped the way that endpoint returns them --
// `name` not `label`, a PostgREST numeric that can arrive as TEXT, and the audit columns -- so a
// mapping that only works on a hand-tidied row shows up here rather than on staging.
const LIB_ROWS = [
  { id: "lab-densify", name: "Densify", rate: "40.00", unit: "days", guys_auto: false,
    sort: 0, notes: null, owner_email: "hanz@wetreadwell.com",
    created_at: "2026-09-17T14:00:00Z", updated_at: "2026-09-17T14:00:00Z" },
  { id: "lab-night", name: "Night shift premium", rate: 12.5, unit: "hours", guys_auto: true,
    sort: 1, notes: "after 6pm", owner_email: "hanz@wetreadwell.com",
    created_at: "2026-09-17T14:01:00Z", updated_at: "2026-09-17T14:01:00Z" }
];

const seeded = P.seedLibraryLabor(P.freshModel().labor, LIB_ROWS);
const inputArray = P.freshModel().labor;
const inputBefore = JSON.stringify(inputArray);
P.seedLibraryLabor(inputArray, LIB_ROWS);

out.libraryLabor = {
  // THE SEAM, both halves of it: the table's `name` becomes the model's `label`, and everything
  // an estimator types starts empty.
  mapped: LIB_ROWS.map(function (r) { return P.libraryLaborRow(r); }),
  // PostgREST hands numeric back as a string. A rate that stayed a string would price fine
  // (num() coerces) and then read back as a string off the saved draft forever.
  rateType: typeof P.libraryLaborRow(LIB_ROWS[0]).rate,
  // ADDED BESIDE. The four built-in rows come first, in their own order, then the library's in
  // the order the server sent them.
  seededIds: seeded.map(function (r) { return r.id; }),
  seededLabels: seeded.map(function (r) { return r.label; }),
  // …and the built-in four are the same objects' worth of data they always were.
  builtInsUntouched:
    JSON.stringify(seeded.slice(0, 4)) === JSON.stringify(P.freshModel().labor),
  // A new array. Seeding the model the page is holding must not rewrite the array it was handed.
  inputUntouched: JSON.stringify(inputArray) === inputBefore,
  isANewArray: seeded !== inputArray,
  // TRAVEL IS OVERRIDDEN IN PLACE, NEVER DUPLICATED, and `travel` is the one reserved id that
  // beats the "already on the model wins" rule. The row the Defaults tab edits carries that id;
  // skipped, the edit would do nothing, and pushed, migrateModel -- which finds Travel by that
  // exact id -- would start backfilling onto whichever of two rows it reached first.
  travelIsOverriddenInPlace: (function () {
    const rows = P.seedLibraryLabor(P.freshModel().labor,
      [{ id: "travel", name: "Drive time", rate: 99, unit: "days", guys_auto: false }]);
    const travel = rows.filter(function (r) { return r.id === "travel"; });
    return { count: travel.length, label: travel[0].label, rate: travel[0].rate,
             unit: travel[0].unit, guysAuto: travel[0].guys_auto,
             rowCount: rows.length,
             // The sheet's own position, which is where the estimator reads it.
             at: rows.map(function (r) { return r.id; }).indexOf("travel"),
             ids: rows.map(function (r) { return r.id; }) };
  })(),
  // PRODUCTION, WHERE THE TABLE DOES NOT EXIST. list_labor() answers [] and never raises, so the
  // library hands back nothing and Travel has to be the sheet's own $33.00/hr row exactly as it
  // was before any of this. This is the state prod is in until the DDL runs.
  travelWithNoStoredRow: (function () {
    const rows = P.seedLibraryLabor(P.freshModel().labor,
      [{ id: "lab-densify", name: "Densify", rate: 40, unit: "days", guys_auto: false }]);
    const t = rows.filter(function (r) { return r.id === "travel"; })[0];
    return { count: rows.filter(function (r) { return r.id === "travel"; }).length,
             label: t.label, rate: t.rate, unit: t.unit, guysAuto: t.guys_auto };
  })(),
  // travelSeed WITH NOTHING IS THE SHIPPED ROW. Everything above rests on this: a stored row is
  // an OVERRIDE of it, so the two have to be the same shape and the no-row answer has to be the
  // figure off Kyle's Polish tab.
  shippedTravel: P.travelSeed(),
  // …and a stored row is read the way the API actually serves one: numeric as TEXT.
  storedTravelFromText: P.travelSeed({ id: "travel", name: "Travel", rate: "41.50",
                                       unit: "hours", guys_auto: true }),
  // A RATE OF ZERO IS AN ANSWER, not a blank. Travel written off on local work is a thing an
  // admin can mean, and falling back to 33.00 there would quietly re-price every new bid.
  storedTravelAtZero: P.travelSeed({ id: "travel", name: "Travel", rate: 0, unit: "hours",
                                     guys_auto: true }),
  // A rate that is not a number at all falls back rather than poisoning the row with NaN.
  storedTravelWithJunkRate: P.travelSeed({ id: "travel", name: "Travel", rate: "not a number",
                                           unit: "hours", guys_auto: true }),
  // AND A BLANK ONE IS NOT ZERO, which is a different check from the one above and the reason
  // `isBlank` is there at all: Number("") and Number(null) are both 0 and both isFinite, so a
  // guard written as `!isFinite(rate)` alone reads an empty rate as travel being FREE and prices
  // every new bid's travel at nothing. Three shapes, because a row can arrive short in three ways.
  storedTravelWithEmptyRate: P.travelSeed({ id: "travel", name: "Travel", rate: "",
                                            unit: "hours", guys_auto: true }),
  storedTravelWithNullRate: P.travelSeed({ id: "travel", name: "Travel", rate: null,
                                           unit: "hours", guys_auto: true }),
  storedTravelWithNoRateKey: P.travelSeed({ id: "travel", name: "Travel", unit: "hours" }),
  // …and a blank NAME or UNIT falls back the same way rather than drawing an anonymous line or
  // multiplying by a unit the estimate has no branch for.
  storedTravelWithBlankText: P.travelSeed({ id: "travel", name: "   ", rate: 44, unit: "" }),
  // THE ID IS NEVER READ OFF THE ROW, and this is the fixture that can tell. Every other one
  // here hands in `id: "travel"`, where "reserve the id" and "copy the row's id" agree and a
  // mutation between them is invisible. `travel` is what migrateModel's backfill finds this line
  // by on every draft ever saved: a row that arrived with another id -- a caller's mistake, a
  // renamed primary key -- must still produce THE Travel row rather than a stray labor line with
  // no backfill and no way for the Defaults tab to address it.
  travelSeedIgnoresAForeignId: P.travelSeed({ id: "lab-7f3a", name: "Drive time", rate: 44,
                                              unit: "hours", guys_auto: true }),
  // QUANTITIES ARE THE BID'S. Overlaying the library's rate onto Travel must not touch what
  // somebody typed for how much of it this job needs.
  travelKeepsItsQuantities: (function () {
    const model = P.freshModel().labor.map(function (r) {
      return r.id === "travel" ? Object.assign({}, r, { guys: 6, days: 2 }) : r;
    });
    const t = P.seedLibraryLabor(model,
      [{ id: "travel", name: "Travel", rate: 44, unit: "hours", guys_auto: true }])
      .filter(function (r) { return r.id === "travel"; })[0];
    return { guys: t.guys, days: t.days, rate: t.rate };
  })(),
  // Nothing to add, in all three shapes "nothing" arrives in.
  emptyList: P.seedLibraryLabor(P.freshModel().labor, []).map(function (r) { return r.id; }),
  missingList: P.seedLibraryLabor(P.freshModel().labor, null)
    .map(function (r) { return r.id; }),
  rowsWithoutIds: P.seedLibraryLabor(P.freshModel().labor,
    [{ name: "No id at all", rate: 5 }, null]).map(function (r) { return r.id; })
};

// ── the gate: whose labor is it? ─────────────────────────────────────────────
//
// laborUnstated is the ONLY thing standing between an admin editing the default list and an
// estimator's finished bid. Every shape a saved blob actually arrives in is asked here, and the
// v1 row is the one that matters most: a v1 draft keeps its crew under `labour`, so reading the
// missing `labor` as "never stated" would inject defaults into a bid with real crew numbers.
out.laborUnstated = [
  { label: "nothing saved at all", saved: undefined },
  { label: "null", saved: null },
  { label: "a v2 model that states no labor", saved: { version: 2, conditions: {} } },
  { label: "a v2 model with an empty labor array", saved: { version: 2, labor: [] } },
  { label: "a v2 model with labor on it",
    saved: { version: 2, labor: [{ id: "polishing", label: "Polishing", guys: 3 }] } },
  { label: "a v1 draft, whose crew lives under `labour`", saved: V1 },
  { label: "a version-less partial blob", saved: { conditions: { taxable: false } } },
  { label: "a string", saved: "not a model" }
].map(function (c) { return { label: c.label, unstated: P.laborUnstated(c.saved) }; });

// ── AN EXISTING ESTIMATE MUST NOT CHANGE ─────────────────────────────────────
//
// The hard constraint, stated as a round trip. SAVED_WITH_LIB_ROW is a real estimator's work: the
// four built-in rows with their own numbers typed in, Travel already in its current shape (so the
// migration has nothing legitimate to do), and one library default they kept and then edited --
// its rate is 55, not the library's 40, and its hours are typed.
//
// NOT VACUOUS: `wouldHaveAdded` seeds the very same array with the very same library list and
// shows two rows arriving. The library has rows that COULD have landed on this bid; the gate is
// what stops them. Without that counterexample "nothing was added" would also pass against an
// empty library, which proves nothing at all.
const SAVED_WITH_LIB_ROW = {
  version: 2,
  takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000,
              unit: "SF" }],
  labor: [
    { id: "polishing", label: "Polishing", guys: 4, days: 6, rate: 33.0 },
    { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33.0 },
    { id: "jointfill", label: "Joint filler", guys: 2, days: 3, rate: 33.0 },
    { id: "travel", label: "Travel", guys: 18, days: 2, rate: 33.0,
      unit: "hours", guys_auto: true },
    { id: "lab-densify", label: "Densify", guys: 2, days: 1, rate: 55, unit: "days",
      guys_auto: false }
  ],
  conditions: { taxable: false },
  contingency: 500,
  fees: 0,
  totals: {}
};
out.savedLaborIsUntouchable = {
  unstated: P.laborUnstated(SAVED_WITH_LIB_ROW),
  saved: SAVED_WITH_LIB_ROW.labor,
  afterMigrate: P.migrateModel(JSON.parse(JSON.stringify(SAVED_WITH_LIB_ROW))).labor,
  wouldHaveAdded: P.seedLibraryLabor(SAVED_WITH_LIB_ROW.labor, LIB_ROWS)
    .map(function (r) { return r.id; }),
  // REQUIREMENT 3, at the only level this module can answer it: the row is the BID's now. Nothing
  // in the migration or the seeding consults the library about a row already on the model, so a
  // default deleted from the library (the empty list here) leaves it exactly where it is.
  survivesAnEmptyLibrary: P.seedLibraryLabor(
    P.migrateModel(JSON.parse(JSON.stringify(SAVED_WITH_LIB_ROW))).labor, [])
    .map(function (r) { return r.id; })
};

// ── the condition defaults: the merge, the gate, and the bid that must not move ───────────────
//
// The three Takeoff conditions stopped being "built in" on 2026-09-18 (Hanz, twice). Their
// answers for a NEW bid are editable on the Library page's Defaults tab and stored in
// `condition_defaults`; freshModel() still states what the tool SHIPS, and a stored row is an
// override of one key.
//
// EVERY LIBRARY ROW HERE DISAGREES WITH THE SHIPPED ANSWER, deliberately. All three ship OFF
// since 2026-09-19 -- joint filler moved that day, because it had started carrying a real $500
// kit per 3,500 sq ft -- so all three rows here say on. A fixture that agreed with freshModel
// could not tell a merge that works from one that does nothing at all.
const COND_ROWS = [
  { key: "joint_filler", on: true },
  { key: "dye", on: true },
  { key: "remove_existing_jf", on: true }
];

const condInput = P.freshModel().conditions;
const condInputBefore = JSON.stringify(condInput);
P.seedConditionDefaults(condInput, COND_ROWS);

out.conditionDefaults = {
  shipped: P.freshModel().conditions,
  seeded: P.seedConditionDefaults(P.freshModel().conditions, COND_ROWS),
  // The five conditions answered on Intake are not in the vocabulary and must come through
  // untouched — the merge writes the three it was handed and nothing else.
  intakeFiveUntouched: (function () {
    const a = P.freshModel().conditions;
    const b = P.seedConditionDefaults(a, COND_ROWS);
    return ["local", "hard_bid", "prevailing_wage", "taxable", "remodel_tax", "bond"]
      .every(function (k) { return a[k] === b[k]; });
  })(),
  // A NEW OBJECT. Seeding the conditions the page is holding must not rewrite the object it was
  // handed — the same rule seedLibraryLabor follows for its array.
  inputUntouched: JSON.stringify(condInput) === condInputBefore,
  isANewObject: P.seedConditionDefaults(condInput, COND_ROWS) !== condInput,
  // A KEY THE MODEL DOES NOT CARRY IS SKIPPED, not added. migrateModel whitelists condition keys
  // against freshModel().conditions and DROPS every other one, so a key seeded here would look
  // applied on screen and come back missing on the next load.
  offVocabularyIgnored: (function () {
    const m = P.seedConditionDefaults(P.freshModel().conditions,
      [{ key: "reno", on: true }, { key: "made_up", on: true }]);
    return !("reno" in m) && !("made_up" in m) &&
      JSON.stringify(m) === JSON.stringify(P.freshModel().conditions);
  })(),
  // Nothing to apply, in every shape "nothing" arrives in — including a row with no key at all
  // and a null in the list, which is what a half-written response looks like.
  emptyList: P.seedConditionDefaults(P.freshModel().conditions, []),
  missingList: P.seedConditionDefaults(P.freshModel().conditions, null),
  rowsWithoutKeys: P.seedConditionDefaults(P.freshModel().conditions,
    [{ on: true }, null, { key: "", on: true }])
};

// ── the gate: is there any saved work to protect? ─────────────────────────────────────────────
//
// conditionsUnstated is the ONLY thing standing between a Defaults-tab edit and an estimator's
// saved answers, and it is STRICTER than laborUnstated on purpose. An empty `labor` array is a
// shape a real model holds and genuinely means "no rows chosen"; `conditions` has no equivalent,
// because migrateModel backfills every key from freshModel on the way out — so a saved v2 blob
// that omitted `conditions` was still SHOWN an answer and its next save wrote that answer into
// Kyle's workbook. Only "nothing saved whatsoever" is seedable.
out.conditionsUnstated = [
  { label: "nothing saved at all", saved: undefined },
  { label: "null", saved: null },
  { label: "an empty blob", saved: {} },
  { label: "a v2 model that states no conditions", saved: { version: 2, labor: [] } },
  { label: "a v2 model with conditions on it",
    saved: { version: 2, conditions: { joint_filler: false } } },
  { label: "a v1 draft, whose conditions predate these three", saved: V1 },
  { label: "the beta intake's first save: conditions and no version",
    saved: { conditions: { taxable: false } } },
  { label: "a string", saved: "not a model" }
].map(function (c) { return { label: c.label, unstated: P.conditionsUnstated(c.saved) }; });

// ── AN EXISTING ESTIMATE'S ANSWERS ARE THE ESTIMATOR'S WORK ───────────────────────────────────
//
// Hanz's rule for this feature, verbatim: changing a default must not change any estimate that
// already exists. Stated here as a round trip through the real migration.
//
// EVERY ONE OF THE THREE SAVED ANSWERS DISAGREES WITH THE LIBRARY ROW ABOVE, which is what makes
// this non-vacuous: `wouldHaveChanged` applies the same rows to the same model and shows all
// three moving. The library has answers that COULD have landed on this bid; the gate is what
// stops them. Without that counterexample "nothing changed" would also pass against a library
// that happened to agree, which proves nothing.
//
// joint_filler is the one that bites either way, and the direction reversed on 2026-09-19 when
// it stopped shipping on. It now SHIPS off, so the bid at risk is one where somebody deliberately
// turned it ON -- a careless default would quietly take a $500 kit per 3,500 sq ft back out, and
// the downloaded workbook would say No in Polish!E29 with nothing on screen admitting it.
const SAVED_WITH_CONDITIONS = {
  version: 2,
  takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000,
              unit: "SF" }],
  labor: [
    { id: "polishing", label: "Polishing", guys: 4, days: 6, rate: 33.0 },
    { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33.0 },
    { id: "jointfill", label: "Joint filler", guys: 2, days: 3, rate: 33.0 },
    { id: "travel", label: "Travel", guys: 18, days: 2, rate: 33.0,
      unit: "hours", guys_auto: true }
  ],
  // ALL THREE THE OPPOSITE OF COND_ROWS ABOVE, which is what keeps `wouldHaveChanged`
  // meaningful: the library has an answer for every one of them that COULD have landed on this
  // bid, and the gate is the only thing stopping it. joint_filler flipped here on 2026-09-19 to
  // stay opposite when the library row flipped.
  conditions: { local: false, hard_bid: true, prevailing_wage: true, taxable: false,
                remodel_tax: true, bond: true,
                joint_filler: false, dye: false, remove_existing_jf: false },
  contingency: 500,
  fees: 0,
  totals: {}
};
const savedClone = function () {
  return JSON.parse(JSON.stringify(SAVED_WITH_CONDITIONS));
};
out.savedConditionsAreUntouchable = {
  unstated: P.conditionsUnstated(SAVED_WITH_CONDITIONS),
  saved: SAVED_WITH_CONDITIONS.conditions,
  afterMigrate: P.migrateModel(savedClone()).conditions,
  // THE COUNTEREXAMPLE. The same three rows applied to the same model move all three answers, so
  // "afterMigrate equals saved" is a fact about the gate and not about the fixture.
  wouldHaveChanged: P.seedConditionDefaults(P.migrateModel(savedClone()).conditions, COND_ROWS),
  // …and a brand new bid DOES take them, or the feature does nothing at all.
  freshTakesThem: P.seedConditionDefaults(P.freshModel().conditions, COND_ROWS),
  // Migrating twice is migrating once, for conditions as for everything else this model carries.
  migrationIsIdempotent: JSON.stringify(P.migrateModel(P.migrateModel(savedClone())).conditions)
    === JSON.stringify(P.migrateModel(savedClone()).conditions)
};

console.log(JSON.stringify(out));
