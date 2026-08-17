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
 *   * THE TWO TAX BASES. Sales tax on materials only; the remodel tax on the labour side and the
 *     markups and never on materials. Every tax vector carries real materials AND real labour, so
 *     swapping the two bases moves the answer instead of cancelling out.
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

// A job with materials AND labour on it, used for every on/off pair below so the only thing that
// differs between the two vectors is the flag being tested.
const JOB = { material: 12000, labor: 8000, contingency: 0, sf: 12500 };
function job(over) { return Object.assign({}, JOB, over || {}); }

/* Sub-totals are back-solved: with no labour, D64 = m + ROUNDUP(m*2%). 6,371 lands on 6,499 and
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

  // ── remodel tax on and off ─────────────────────────────────────────────────
  // Both carry $12,000 of material, so a remodel base that wrongly included D33 would come out
  // ~$1,224 higher and the recomputation in the pytest would catch it. That is the whole reason
  // these vectors are not material-free.
  { label: "remodel: 10% on labour + markups, never on materials",
    input: job({ conditions: cond({ remodel_tax: true }) }) },
  { label: "not a remodel: no remodel-tax line",
    input: job({ conditions: cond() }) },

  // ── prevailing wage on and off ─────────────────────────────────────────────
  { label: "prevailing wage: 5% escalation, and burden on labour PLUS escalation",
    input: { material: 6372, labor: 4000, contingency: 0,
             conditions: cond({ prevailing_wage: true }), sf: 9000 } },
  { label: "no prevailing wage: no escalation line",
    input: { material: 6372, labor: 4000, contingency: 0, conditions: cond(), sf: 9000 } },

  // ── contingency ────────────────────────────────────────────────────────────
  // $5,000 of contingency adds MORE than $5,000 to the bid: it is inside the super/PTO, soft-cost
  // and remodel-tax bases. Paired with the same job at zero so the pytest can see the difference.
  { label: "contingency 5,000, remodel + tax on: it feeds three markup bases",
    input: job({ contingency: 5000,
                 conditions: cond({ taxable: true, remodel_tax: true }) }) },
  { label: "contingency 0, otherwise identical",
    input: job({ contingency: 0,
                 conditions: cond({ taxable: true, remodel_tax: true }) }) },

  // ── the area ───────────────────────────────────────────────────────────────
  { label: "no area typed yet: per SF is null, not 0",
    input: job({ sf: 0, conditions: cond({ taxable: true }) }) },
  { label: "an area typed: per SF is the bid divided by it",
    input: job({ sf: 12500, conditions: cond({ taxable: true }) }) },

  // ── a whole realistic job, every condition on, raw sums with cents on them ─
  { label: "everything on, unrounded takeoff and labour sums",
    input: { material: 18450.75, labor: 15467.2, contingency: 2500,
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
// threshold the formulas name.
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

// ── the model: fresh, migrated, and what is blocking it ──────────────────────
out.fresh = P.freshModel();

// A v1 draft, shaped like the ones on staging: named areas, worksheet-row materials, and labour
// keyed polishing/mockup/joint_filler where `crew` is the GUYS COUNT.
const V1 = {
  areas: [{ name: "Main sales floor", sf: 9000 }, { name: "Back of house", sf: "3,500" }],
  system: "S&P",
  tooling: "traditional",
  conditions: { local: false, hard_bid: true, prevailing_wage: true,
                taxable: true, remodel_tax: true },
  materials: { 17: { qty: 12500, cost: 0.15 }, 29: { qty: 4, cost: 500 } },
  added: [{ name: "Stair nosing infill", qty: 46, cost: 12.5 }],
  labour: { polishing: { crew: 4, days: 6, rate: 32.2 },
            mockup: { crew: 2, days: 1, rate: 32.2 },
            joint_filler: { crew: 2, days: 2, rate: 32.2 } },
  adds: { ram_board: 240, cove_4: 60 },
  options: { salt_pepper: true, dye: true }
};

const MIGRATIONS = [
  { label: "a v1 draft off staging", before: V1 },
  { label: "v1 with no labour block at all", before: { areas: [{ sf: 9000 }] } },
  { label: "v1 with no areas", before: { areas: [], labour: {} } },
  { label: "nothing saved yet", before: null },
  { label: "a v2 model missing half its keys", before: { version: 2, takeoff: [], labor: null } },
  { label: "a v2 model with one condition saved", before: { version: 2, conditions: { taxable: false } } },
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
  { label: "a labour row with guys and a rate but no days",
    says: P.blockers({ version: 2,
      takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000,
                  unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: "", rate: 32.2 }],
      conditions: {}, contingency: 0 }) },
  { label: "ready to price: a switched-off labour row is not half-filled",
    says: P.blockers({ version: 2,
      takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000,
                  unit: "SF" }],
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 },
              { id: "jointfill", label: "Joint filler", guys: 3, days: 0, rate: 32.2 },
              { id: "mockup", label: "Mock-up", guys: "", days: "", rate: "" }],
      conditions: {}, contingency: 0 }) },
  { label: "a model that is not a model at all", says: P.blockers(null) }
];

console.log(JSON.stringify(out));
