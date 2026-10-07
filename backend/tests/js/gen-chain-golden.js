"use strict";
/* THE POLISH CHAIN, RECORDED. The recipe behind backend/tests/fixtures/polish_chain_golden.json.
 *
 * Phases 4 to 10 of the v2 estimating program rewrite what sits behind the Polish bid: the model
 * module is renamed, the ROUNDUP and number helpers move to a leaf module, the rates and GP ladder
 * become profile data, the markup chain becomes an engine that runs any sheet's profile, the
 * conditions table is shared by every work type. The Polish number a customer is quoted must not
 * move in any of them, and where it must move (Phase 17, new bids only) the move must show up as a
 * reviewable fixture diff. This is the instrument that makes both true.
 *
 * HOW. A recipe lists INPUTS and nothing else: every answer comes from running the real function
 * (see _golden.js, "no copied code"). The inputs are deterministic tables and loops, no random
 * numbers, so the file regenerates byte for byte. They are chosen for the places this code can be
 * wrong while still looking like a bid:
 *
 *   * BOTH SIDES OF EVERY GP EDGE (B67 is strictly `<`): the sub-total landed on E-1, E and E+1
 *     through three routes (travel alone, material alone, labor alone with and without prevailing
 *     wage), because a refactor that reorders the rounding moves some routes and not others.
 *   * EVERY CONDITION COMBINATION: all 256 settings of the eight job conditions, on one job that
 *     has materials, labor, travel, fees and contingency, so a key that is inert today (local,
 *     bond, dye, joint filler, remove-existing) proves it is inert, and one that starts to matter
 *     shows up.
 *   * THE REMODEL RATE in every shape it arrives in: absent, null, "", 0, "0", "0.07975", 0.07975.
 *     Null and zero mean different things (nobody picked a county / a Missouri county, exempt).
 *   * DIRTY INPUTS: "12,500", "$1,200", "", null, undefined, NaN, Infinity, strings, booleans. The
 *     page hands the engine whatever a person pasted.
 *   * NEGATIVE ZERO. `3 * 0 * -5 * 8` is -0 in JavaScript; the golden keeps it, and the comparison
 *     can tell it from 0.
 *   * THE FLOAT EDGES ROUNDUP guards: 110.00000000000001 and friends.
 *
 * WHAT IS COVERED, by group (the id prefix says which):
 *   chain/      markupChain: the whole bid, Kyle's markup column
 *   gp/ round/ num/ money/ pct/ fmt/   gpPct, roundUp, num, money, money2, pct, fmtSf
 *   labor/ ltot/ hand/ trv/             laborCost, laborTotal, removeExistingHand, travel quantity and cost
 *   take/ dye/ jf/                      takeoffSf, measuredSf, dyeCost, jointFillerCost
 *   cond/ ...                           the conditions: cell writes (with the library's lines), cell
 *                                       read-back, defaults, which cards show
 *   rate/                               the global-default readers (labor rate, fees, lodging, per diem)
 *   model/                              freshModel, migrateModel, blockers, normalizeTravel
 *   calc/ seed/                         the labor calculator, and seeding a new bid's takeoff
 *   newbid/                             what a NEW bid is started with: travel row, company labor
 *                                       rate, lodging and per diem rates, the fees default, the
 *                                       library's default labor lines, and the gates on all of it
 *   const/ exports                      the exported data (RATES, GP_BANDS, CONDITION_CELLS ...) and the
 *                                       type of each name the module exports today (a name that goes
 *                                       missing or changes type fails; a NEW export does not)
 *
 * WHAT IS LEFT OUT ON PURPOSE. Words and pixels (travelHow, distanceNote, sliderHtml) and the
 * distance lookup have their own harnesses and are not what the v2 program restructures. The page
 * itself is covered by the saved-bid ratchet (test_polish_saved_bid_safety.py).
 *
 * WHEN A LATER PHASE MOVES A FUNCTION. The recipe calls functions by their golden NAMES through
 * loadEngine() below. If a phase renames the module or moves a function, adapt loadEngine() so the
 * same names resolve to the new home. Do not edit or drop vectors to make a refactor pass: a vector
 * that changes is the finding.
 *
 * Usage: node gen-chain-golden.js <frontend-dir> [--write <file> --commit <sha> | --compare <file>]
 */
const fs = require("fs");
const path = require("path");
const G = require("./_golden");

const RECIPE_VERSION = 1;

/** The module that holds the Polish bid maths: the model, with the markup chain still inside it until
 *  Phase 8. Phase 5 gave it this name. A tree from before that has it under its old name, so a recipe
 *  run against such a tree needs the generator that tree carries, not this one. */
function loadEngine(frontend) {
  const p = path.resolve(frontend, "js/bid-model.js");
  if (fs.existsSync(p)) return require(p);
  throw new Error("js/bid-model.js does not exist under " + frontend);
}

/** A value as a short, unambiguous id fragment. */
function lbl(v) {
  if (v === undefined) return "undefined";
  if (Object.is(v, -0)) return "-0";
  if (typeof v === "number") return String(v);
  return JSON.stringify(v);
}

const NEG0 = -0;
const GONE = Symbol("the key is left off");

/** `base` with `over` written on, and any key set to GONE removed (absent is not undefined). */
function make(base, over) {
  // Written without a single `obj[key] = value` (CodeQL's property-injection query flags those):
  // merge, then drop what is marked GONE. Key order is the same as writing key by key.
  const merged = Object.assign({}, base, over || {});
  return Object.fromEntries(Object.entries(merged).filter(([, v]) => v !== GONE));
}

// What a person might paste, type or leave behind in a box.
const DIRTY = ["12,500", "$1,200", " 12,500 ", "$1,200.50", "", null, undefined, NaN, Infinity, -Infinity,
  "abc", "12abc", "1e3", true, false, {}, [], [5], "0", "-5", ".5", "5.", "0x10", 0, NEG0, 1, -1, 0.5, 1e15,
  1e-9, 12500];

const CONDITION_KEYS = ["local", "prevailing_wage", "taxable", "remodel_tax", "bond", "dye", "joint_filler",
  "remove_existing_jf"];

function conds(over) {
  return make({ local: false, prevailing_wage: false, taxable: false, remodel_tax: false }, over);
}
function allConds(bits) {
  return Object.fromEntries(CONDITION_KEYS.map((k, i) => [k, bits[i] === "1"]));
}

// The data the module exports, which Phase 8 turns into profile data: every rate, the GP ladder, the
// condition-to-cell table, the shipped defaults. Recorded whole so moving one is a visible change.
const CONSTANTS = ["RATES", "GP_BANDS", "HOURS_PER_DAY", "DYE_COATS", "SHIPPED_LABOR_RATE", "SHIPPED_LODGING_RATE",
  "SHIPPED_PER_DIEM_RATE", "LOCAL_MILES", "TRAVEL_LINE_KEYS", "TRAVEL_LABEL", "CONDITION_CELLS",
  "LIBRARY_LINE_CELLS", "LABOR_CALC_BUILTINS"];

// Every name the module exports at the commit the golden was cut from (origin/staging 3f94ed2).
const EXPORT_NAMES = [
  "CONDITION_CELLS", "DYE_COATS", "GP_BANDS", "HOURS_PER_DAY", "LABOR_CALC_BUILTINS", "LIBRARY_LINE_CELLS",
  "LOCAL_MILES", "RATES", "SHIPPED_LABOR_RATE", "SHIPPED_LODGING_RATE", "SHIPPED_PER_DIEM_RATE",
  "TRAVEL_LABEL", "TRAVEL_LINE_KEYS", "applyDistance", "applyFeesDefault", "applyLaborCalc",
  "applyLaborRate", "applyTravelRates", "blockers", "clearDistance", "conditionCellWrites",
  "conditionShown", "conditionsFromCells", "conditionsUnstated", "copyInto", "dayHours", "distanceKey",
  "distanceNote", "driveHoursFor", "dyeCost", "feesFromRules", "filledIn", "fmtSf", "followLaborDays",
  "freshModel", "gpPct", "isFarMiles", "jointFillerCost", "laborCalcDiffers", "laborCalcValues",
  "laborCost", "laborRateFromRules", "laborRateOrShipped", "laborTotal", "laborUnstated",
  "libraryLaborRow", "manDaysHint", "markupChain", "measuredSf", "migrateModel", "milesOrNull", "money",
  "money2", "normalizeDistance", "normalizeTravel", "num", "pct", "removeExistingHand", "roundUp", "rowOn",
  "seedConditionDefaults", "seedConditionsShown", "seedDefaultTakeoff", "seedLibraryLabor",
  "seedTakeoffSf", "setMeasurement", "sliderHtml", "stampRateDefaults", "takeoffSf", "travelAppliesToBid",
  "travelCosts", "travelCostsSeed", "travelDeclined", "travelHow", "travelLabel", "travelLineCost",
  "travelManDays", "travelQty", "travelRatesFromRules", "travelSeed",
];

function build(frontend, add) {
  const E = loadEngine(frontend);
  const call = (id, fn, ...args) => {
    if (typeof E[fn] !== "function") {
      throw new Error("the engine no longer exports " + fn + "(); point loadEngine() at its new home, " +
        "do not delete the vectors");
    }
    return add(id, fn, E[fn], args);
  };
  const constant = (name) => {
    if (!Object.prototype.hasOwnProperty.call(E, name) || typeof E[name] === "function") {
      throw new Error("the engine no longer exports the constant " + name + "; point loadEngine() at its new home");
    }
    return add("const/" + name, name, () => E[name], []);
  };

  CONSTANTS.forEach(constant);
  // The export surface: the type of each name the module exports today. A name that goes missing or
  // changes type fails here first (a phase that moves a function must point loadEngine() at it); a
  // NEW export does not, because an unrelated change that adds a helper is not a pricing change.
  add("exports", "exportTypes", (names) => Object.fromEntries(names.map((n) =>
    [n, Object.prototype.hasOwnProperty.call(E, n) ? typeof E[n] : "missing"])), [EXPORT_NAMES]);

  groupChain(call);
  groupFormats(call);
  groupLabor(call);
  groupTakeoff(call);
  groupConditions(call);
  groupRates(call);
  groupModel(call);
  groupCalcAndSeed(call);
  groupNewBidSeeding(call);
}

// ═════════════════════════════════════════════════════════════════════════════
// markupChain
// ═════════════════════════════════════════════════════════════════════════════
function groupChain(call) {
  const JOB_A = { material: 12000, labor: 8000, contingency: 0, sf: 12500 };
  const JOB_B = { material: 18450.75, labor: 15467.2, travel: 1155.4, fees: 750.25, contingency: 2500,
                  sf: 14200, remodel_rate: 0.07975 };
  const EDGES = [6500, 15000, 22500, 32500];

  // ── the GP edges, three routes ────────────────────────────────────────────
  // Travel alone: sub_total is the travel figure itself, so E-1, E and E+1 land exactly.
  for (const e of EDGES) {
    for (const d of [-1, 0, 1]) {
      call("chain/edge/travel/" + (e + d), "markupChain",
        { material: 0, labor: 0, travel: e + d, contingency: 0, conditions: conds(), sf: 10000 });
    }
  }
  for (const v of [0, 1, 60000, 100000]) {
    call("chain/edge/travel/" + v, "markupChain",
      { material: 0, labor: 0, travel: v, contingency: 0, conditions: conds(), sf: 10000 });
  }
  // Material alone: m + ROUNDUP(m * 2%) is the sub-total. Back-solved: 6,371 -> 6,499 and so on.
  for (const m of [6371, 6372, 6373, 14704, 14705, 14706, 22057, 22058, 22059, 31861, 31862, 31863]) {
    call("chain/edge/material/" + m, "markupChain",
      { material: m, labor: 0, contingency: 0, conditions: conds(), sf: 10000 });
  }
  // Labor alone: labor + ROUNDUP(labor * 12%) (+ the 5% escalation under prevailing wage). The
  // burden steps by 0.12 a dollar, so 15,000 and 32,500 have no input one dollar short; the next
  // one down is used.
  const LABOR_EDGE = {
    false: [5802, 5803, 5804, 13391, 13392, 13393, 20088, 20089, 20090, 29016, 29017, 29018],
    true: [5525, 5526, 5527, 12753, 12754, 12755, 19131, 19132, 19133, 27634, 27635, 27636],
  };
  for (const pw of ["false", "true"]) {
    for (const l of LABOR_EDGE[pw]) {
      call("chain/edge/labor/pw-" + pw + "/" + l, "markupChain",
        { material: 0, labor: l, contingency: 0, conditions: conds({ prevailing_wage: pw === "true" }), sf: 10000 });
    }
  }

  // ── every setting of the eight job conditions, on one full job ─────────────
  for (let n = 0; n < 256; n++) {
    const bits = n.toString(2).padStart(8, "0");
    call("chain/cond256/" + bits, "markupChain", Object.assign({}, JOB_B, { conditions: allConds(bits) }));
  }
  // and the three that the chain reads, on the plain job, with and without a county rate
  for (const rate of [null, 0.07975]) {
    for (let n = 0; n < 8; n++) {
      const c = conds({ prevailing_wage: !!(n & 1), taxable: !!(n & 2), remodel_tax: !!(n & 4) });
      call("chain/live3/rate-" + lbl(rate) + "/" + n, "markupChain",
        make(JOB_A, { remodel_rate: rate, conditions: c }));
    }
  }

  // ── the remodel rate, in every shape it arrives in ─────────────────────────
  const RATES = [GONE, null, "", 0, "0", "0.07975", 0.07975, 0.1, 0.0715, "abc", NaN, -0.01, true, " 0.065 ",
    "7.975%", 0.065, 1];
  RATES.forEach((r, i) => {
    for (const on of [true, false]) {
      call("chain/remodel/" + i + "/" + (r === GONE ? "absent" : lbl(r)) + "/" + (on ? "on" : "off"), "markupChain",
        make(JOB_A, { remodel_rate: r, conditions: conds({ remodel_tax: on }) }));
    }
  });

  // ── dirty values in each numeric field, one at a time ──────────────────────
  const SWEEP = ["12,500", "$1,200", "", null, undefined, NaN, Infinity, "abc", true, -500, 0.4, 1e15,
    "$1,200.50", 0, NEG0, GONE];
  const ALL_ON = conds({ prevailing_wage: true, taxable: true, remodel_tax: true });
  for (const field of ["material", "labor", "sf", "fees", "contingency", "travel"]) {
    SWEEP.forEach((v, i) => {
      call("chain/dirty/" + field + "/" + i + "/" + (v === GONE ? "absent" : lbl(v)), "markupChain",
        make(Object.assign({}, JOB_B, { conditions: ALL_ON }), { [field]: v }));
    });
  }

  // ── travel, fees and contingency, on and off, under every reading condition combination ──
  for (const travel of [0, 1234.5]) {
    for (const fees of [0, 750.25]) {
      for (const contingency of [0, 500]) {
        for (let n = 0; n < 8; n++) {
          const c = conds({ prevailing_wage: !!(n & 1), taxable: !!(n & 2), remodel_tax: !!(n & 4) });
          call("chain/tfc/t" + travel + "/f" + fees + "/c" + contingency + "/" + n, "markupChain",
            { material: 12000, labor: 8000, travel, fees, contingency, sf: 12500, remodel_rate: 0.07975,
              conditions: c });
        }
      }
    }
  }

  // ── the shape of the input and of the conditions ───────────────────────────
  const SHAPES = [
    ["noArgument", []], ["undefined", [undefined]], ["null", [null]], ["empty", [{}]], ["string", ["abc"]],
    ["number", [5]], ["array", [[]]],
    ["conditionsNull", [make(JOB_A, { conditions: null })]],
    ["conditionsString", [make(JOB_A, { conditions: "yes" })]],
    ["conditionsTruthyNotBoolean", [make(JOB_A, { remodel_rate: 0.07975,
      conditions: { taxable: 1, remodel_tax: "yes", prevailing_wage: "false" } })]],
    ["conditionsFalsyNotBoolean", [make(JOB_A, { conditions: { taxable: 0, remodel_tax: "", prevailing_wage: null } })]],
    ["conditionsMissing", [make(JOB_A, { conditions: GONE })]],
    ["onlyConditions", [{ conditions: { taxable: true } }]],
  ];
  for (const [name, args] of SHAPES) call("chain/shape/" + name, "markupChain", ...args);

  // ── the float edges ROUNDUP guards, and the signs ──────────────────────────
  const FLOATS = [12000.0000000001, 12000.00000000001, 12000.000000001, 0.1 + 0.2, 27500 * 1.1, 110.00000000000001,
    362.00000000000006, 220.22000000000003, 4999.999999999999, 5000.000000000001, 8000.000000000002];
  FLOATS.forEach((v, i) => {
    call("chain/float/material/" + i, "markupChain", make(JOB_A, { material: v, conditions: ALL_ON }));
    call("chain/float/labor/" + i, "markupChain", make(JOB_A, { labor: v, conditions: ALL_ON }));
  });
  const NEGATIVES = [{ material: -100 }, { labor: -500 }, { contingency: -250 }, { fees: -75 }, { travel: -300 },
    { sf: -1 }, { material: -100, labor: -500, contingency: -250, fees: -75, travel: -300 },
    { material: -20000, labor: -9000 }];
  NEGATIVES.forEach((over, i) => {
    call("chain/negative/" + i, "markupChain", make(Object.assign({}, JOB_B, { conditions: ALL_ON }), over));
  });
  call("chain/big/1", "markupChain", make(JOB_A, { material: 1e9, labor: 1e8, sf: 1e7, conditions: ALL_ON }));
  call("chain/big/2", "markupChain", make(JOB_A, { material: 1e15, labor: 1e15, conditions: ALL_ON }));
  call("chain/tiny/1", "markupChain", make(JOB_A, { material: 0.0001, labor: 0.0001, sf: 0.0001, conditions: ALL_ON }));

  // ── gpPct on its own ───────────────────────────────────────────────────────
  const GP = [];
  for (const e of EDGES) GP.push(e - 1, e, e + 1);
  GP.push(0, 1, 60000, 100000, 6499.5, 6500.5, 14999.99, 22499.999999, "6,500", "$15,000", "", null, undefined,
    NaN, "abc", -1, Infinity, -Infinity, true, NEG0);
  GP.forEach((v, i) => call("gp/" + i + "/" + lbl(v), "gpPct", v));
}

// ═════════════════════════════════════════════════════════════════════════════
// roundUp, num, money, money2, pct, fmtSf
// ═════════════════════════════════════════════════════════════════════════════
function groupFormats(call) {
  const ROUND = DIRTY.concat([1.2, -1.2, 1, -1, 0.0001, 110.00000000000001, -110.00000000000001, 0.1 + 0.2,
    1.0000000000001, 1.00000000001, 2.0000000000000004, 362.00000000000006, 220.22000000000003, -0.0000001,
    1e21, 123456789012.5, 1e-12, 4999.999999999999, 5000.000000000001, 1e15 + 0.5, -1e-13, 9007199254740993,
    0.5, 99.5, 2.5, -2.5, 27500 * 1.1]);
  ROUND.forEach((v, i) => call("round/" + i + "/" + lbl(v), "roundUp", v));
  DIRTY.forEach((v, i) => call("num/" + i + "/" + lbl(v), "num", v));

  const MONEY = DIRTY.concat([15681, 1234.6, -1235, -0.4, 0.5, 999999.5, 1e9, 1234567.891, -1234567.891, 0.004,
    0.005, 0.006, -0.5, -0.004, 1e21, 32.2, -32.2, 1234.567]);
  MONEY.forEach((v, i) => {
    call("money/" + i + "/" + lbl(v), "money", v);
    call("money2/" + i + "/" + lbl(v), "money2", v);
  });

  const PCT = [0, 0.027, 0.45, 0.09475, -0.025, 0.07975, 0.065, 1, 1.5, 0.0000001, 0.123456789, 0.1, 0.16,
    0.30000000000000004, 1e-7, "0.45", "45%", "", null, NaN, undefined, NEG0, -0.0000001, 0.52, 0.3, 2.7e-2];
  PCT.forEach((v, i) => call("pct/" + i + "/" + lbl(v), "pct", v));

  const FMT = [12500, 0, "1,632.5", 12500.126, 0.001, -5, 1e6, 1234567.891, "", null, undefined, NaN, "abc",
    8250.5, 100, 0.5, NEG0, 1e21];
  FMT.forEach((v, i) => call("fmt/" + i + "/" + lbl(v), "fmtSf", v));
}

// ═════════════════════════════════════════════════════════════════════════════
// labor and travel
// ═════════════════════════════════════════════════════════════════════════════
const CREW = () => [
  { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
  { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
  { id: "jointfill", label: "Joint filler", guys: 3, days: 1, rate: 33 },
];
const TRAVEL_ROW = (over) => make({ id: "travel", label: "Travel Labor", guys: 18, days: 5, rate: 33,
                                    unit: "hours", guys_auto: true }, over);

/** The labor-row sets that laborTotal, travel and the man-day sum are asked about. */
function rowsets() {
  const c = CREW();
  return {
    none: [], null: null, undef: undefined, str: "abc", obj: {}, num5: 5,
    crew: CREW(),
    crewTravel: CREW().concat([TRAVEL_ROW()]),
    crewOff: [c[0], make(c[1], { enabled: false }), c[2]],
    crewHpd10: [make(CREW()[0], { hours_per_day: 10 }), CREW()[1], CREW()[2]],
    jfOff: [CREW()[0], CREW()[1], make(CREW()[2], { enabled: false })],
    jfHours: [CREW()[0], make(CREW()[2], { unit: "hours" })],
    jfHpd10: [CREW()[0], make(CREW()[2], { hours_per_day: 10 })],
    twoJf: CREW().concat([{ id: "jointfill", label: "Joint filler 2", guys: 2, days: 2, rate: 40 }]),
    noJf: [CREW()[0], CREW()[1]],
    holes: [null, undefined, {}, { guys: 2, days: 2, rate: 40 }],
    dirty: [{ guys: "3", days: "5", rate: "$32.20" }, { guys: "", days: "x", rate: null }, { guys: 1.5, days: 2.25, rate: 30.125 }],
    negative: [{ guys: -1, days: 2, rate: 30 }, { guys: 2, days: 2, rate: -30 }],
    manyTravel: [CREW()[0], TRAVEL_ROW(), TRAVEL_ROW({ id: "travel2", guys: 4, days: 2 })],
  };
}

function groupLabor(call) {
  // ── one row's cost: guys x days x rate x 8, an hours row not multiplied ────
  const BASE = { guys: 3, days: 5, rate: 32.2 };
  const POOL = ["3", "$32.20", "", null, undefined, NaN, Infinity, "abc", true, -2, 0, NEG0, 0.5, 1e9, GONE];
  for (const field of ["guys", "days", "rate"]) {
    POOL.forEach((v, i) => {
      call("labor/" + field + "/" + i + "/" + (v === GONE ? "absent" : lbl(v)), "laborCost", make(BASE, { [field]: v }));
    });
  }
  [undefined, "days", "hours", "Hours", "HOURS", "", null, 5, GONE].forEach((u, i) => {
    call("labor/unit/" + i + "/" + (u === GONE ? "absent" : lbl(u)), "laborCost", make(BASE, { unit: u }));
  });
  for (const unit of [GONE, "hours"]) {
    [undefined, 8, 10, "10", 12, 0, null, "abc", 10.0001, 9, " 10 "].forEach((h, i) => {
      call("labor/hpd/" + (unit === GONE ? "days" : unit) + "/" + i + "/" + lbl(h), "laborCost",
        make(BASE, { unit: unit, hours_per_day: h }));
    });
  }
  [undefined, true, false, null, 0, "false", "", 1].forEach((en, i) => {
    call("labor/enabled/" + i + "/" + lbl(en), "laborCost", make(BASE, { enabled: en }));
    call("labor/enabledHours/" + i + "/" + lbl(en), "laborCost", make(BASE, { unit: "hours", enabled: en }));
  });
  // the product of a zero and a negative is negative zero; the comparison must see it
  [{ guys: 3, days: 0, rate: -5 }, { guys: -1, days: 0, rate: 5 }, { guys: 0, days: -2, rate: 5 },
   { guys: 3, days: -0, rate: 5 }, { guys: -3, days: -0, rate: -5 }].forEach((row, i) => {
    call("labor/negzero/" + i, "laborCost", row);
  });
  for (const [name, v] of [["undefined", undefined], ["null", null], ["string", "abc"], ["array", []], ["number", 5],
                           ["empty", {}]]) {
    call("labor/shape/" + name, "laborCost", v);
  }

  // ── the rows added up, with the fourth hand on the joint-filler line ──────
  const R = rowsets();
  const COND = [[undefined, "undef"], [null, "null"], [{}, "empty"], [{ joint_filler: true }, "jf"],
    [{ joint_filler: true, remove_existing_jf: true }, "jf+remove"], [{ remove_existing_jf: true }, "remove"]];
  for (const rowName of Object.keys(R)) {
    for (const [cond, cName] of COND) {
      call("ltot/" + rowName + "/" + cName, "laborTotal", R[rowName], cond);
    }
  }
  for (const [name, cond] of [["truthyOne", { joint_filler: 1, remove_existing_jf: 1 }],
                              ["truthyString", { joint_filler: "yes", remove_existing_jf: "yes" }],
                              ["falsyString", { joint_filler: "", remove_existing_jf: "" }]]) {
    call("ltot/crew/" + name, "laborTotal", rowsets().crew, cond);
  }
  call("ltot/noArguments", "laborTotal");
  const BOTH = { joint_filler: true, remove_existing_jf: true };
  for (const rowName of ["crew", "twoJf", "jfOff", "jfHours", "jfHpd10", "noJf", "holes", "none", "null", "str"]) {
    call("hand/" + rowName, "removeExistingHand", rowsets()[rowName], BOTH);
  }
  call("hand/noConditions", "removeExistingHand", rowsets().crew);
  call("hand/onlyRemove", "removeExistingHand", rowsets().crew, { remove_existing_jf: true });
  call("hand/onlyJf", "removeExistingHand", rowsets().crew, { joint_filler: true });

  // ── man-days, and what a travel line is charged ───────────────────────────
  for (const rowName of Object.keys(R)) call("trv/mandays/" + rowName, "travelManDays", rowsets()[rowName]);

  const LINES = {
    undef: undefined, null: null, empty: {}, onNoRate: { enabled: true },
    auto70: { enabled: true, qty_auto: true, rate: 70 },
    autoOff: { enabled: false, qty_auto: true, rate: 70 },
    autoNoFlag: { qty_auto: true, rate: 70 },
    typed3: { enabled: true, qty_auto: false, qty: 3, rate: 70 },
    typedStrings: { enabled: true, qty_auto: false, qty: "5", rate: "45" },
    typedJunk: { enabled: true, qty_auto: false, qty: "abc", rate: 70 },
    typedBlank: { enabled: true, qty_auto: false, qty: "", rate: 70 },
    autoIgnoresQty: { enabled: true, qty_auto: true, qty: 99, rate: 45 },
    autoZeroRate: { enabled: true, qty_auto: true, rate: 0 },
    autoBlankRate: { enabled: true, qty_auto: true, rate: "" },
    autoNegativeRate: { enabled: true, qty_auto: true, rate: -10 },
    autoThirds: { enabled: true, qty_auto: true, rate: 33.333 },
    autoSmallRate: { enabled: true, qty_auto: true, rate: 0.333 },
    autoStringFlag: { enabled: true, qty_auto: "false", rate: 70 },
    enabledString: { enabled: "true", qty_auto: true, rate: 70 },
    typedFraction: { enabled: true, qty_auto: false, qty: 2.5, rate: 70.1 },
  };
  const ROWS = ["none", "crew", "crewOff", "dirty", "crewTravel"];
  for (const lineName of Object.keys(LINES)) {
    for (const rowName of ROWS) {
      call("trv/cost/" + lineName + "/" + rowName, "travelLineCost", LINES[lineName], rowsets()[rowName]);
    }
    for (const rowName of ["none", "crew"]) {
      call("trv/qty/" + lineName + "/" + rowName, "travelQty", LINES[lineName], rowsets()[rowName]);
    }
  }
  const TRAVELS = {
    undef: undefined, null: null, empty: {}, string: "abc",
    lodgingOnly: { lodging: { enabled: true, qty_auto: true, rate: 70 } },
    perDiemOnly: { per_diem: { enabled: true, qty_auto: true, rate: 45 } },
    both: { lodging: { enabled: true, qty_auto: true, rate: 70 }, per_diem: { enabled: true, qty_auto: true, rate: 45 } },
    bothOff: { lodging: { enabled: false, qty_auto: true, rate: 70 }, per_diem: { enabled: false, qty_auto: true, rate: 45 } },
    typed: { lodging: { enabled: true, qty_auto: false, qty: 12, rate: 85 }, per_diem: { enabled: true, qty_auto: false, qty: 12.5, rate: 52.25 } },
    mixed: { lodging: { enabled: true, qty_auto: true, rate: 70 }, per_diem: { enabled: true, qty_auto: false, qty: 3, rate: 45 } },
    roundsUp: { lodging: { enabled: true, qty_auto: false, qty: 3, rate: 70.01 }, per_diem: { enabled: true, qty_auto: false, qty: 1, rate: 44.001 } },
    junkLines: { lodging: "x", per_diem: 5 },
  };
  for (const tName of Object.keys(TRAVELS)) {
    for (const rowName of ["none", "crew", "crewOff", "dirty"]) {
      call("trv/costs/" + tName + "/" + rowName, "travelCosts", TRAVELS[tName], rowsets()[rowName]);
    }
  }
  call("trv/costs/noArguments", "travelCosts");

  // ── the saved travel block, read as a full one ─────────────────────────────
  const BLOCKS = [undefined, null, "abc", 5, [], {},
    { lodging: { enabled: true } },
    { lodging: { enabled: true, qty: "5", qty_auto: false, rate: "85" }, per_diem: { hand: true, enabled: false, rate: "abc" } },
    { lodging: { label: "  ", enabled: "true", qty: null, qty_auto: true, rate: "", rate_default: "99" } },
    { lodging: { label: "Hotel", enabled: true, qty: 4, qty_auto: false, rate: 0, hand: true, rate_default: 70 } },
    { per_diem: { enabled: true, qty: undefined, qty_auto: undefined, rate: NaN, rate_default: NaN } },
    { lodging: { enabled: true, hand: "yes", rate: -5 }, per_diem: { enabled: false, hand: false, rate: 33.333 } },
    { lodging: null, per_diem: "x" }];
  BLOCKS.forEach((b, i) => call("trv/normalize/" + i, "normalizeTravel", b));
}

// ═════════════════════════════════════════════════════════════════════════════
// the takeoff, dye and joint filler
// ═════════════════════════════════════════════════════════════════════════════
function groupTakeoff(call) {
  const TAKEOFF = {
    none: [], null: null, undef: undefined, str: "abc", num: 7, obj: {},
    sf: [{ unit: "SF", measurement: 12500 }],
    sfTwo: [{ unit: "SF", measurement: 9000 }, { unit: "SF", measurement: 3500 }],
    lfOnly: [{ unit: "LF", measurement: 240 }],
    mixed: [{ unit: "SF", measurement: 9000 }, { unit: "LF", measurement: 240 }, { unit: "SF", measurement: "3,500" }],
    sameFloor: [{ unit: "SF", measurement: 10000 }, { unit: "SF", measurement: 10000, same_floor: true },
                { unit: "SF", measurement: 10000, same_floor: true }],
    carrierOff: [{ unit: "SF", measurement: 5000, enabled: false }, { unit: "SF", measurement: 5000, same_floor: true }],
    offRow: [{ unit: "SF", measurement: 5000, enabled: false }, { unit: "SF", measurement: 2500 }],
    allOff: [{ unit: "SF", measurement: 5000, enabled: false }],
    dirty: [{ unit: "SF", measurement: "abc" }, { unit: "SF", measurement: "" }, { unit: "SF", measurement: null },
            { unit: "SF", measurement: "$1,200" }],
    lowerUnit: [{ unit: "sf", measurement: 100 }, { unit: "Sf", measurement: 100 }, { measurement: 100 },
                { unit: " SF", measurement: 100 }],
    holes: [null, undefined, {}, { unit: "SF", measurement: 50 }],
    negative: [{ unit: "SF", measurement: -500 }, { unit: "SF", measurement: 1000 }],
    sameFloorFalsy: [{ unit: "SF", measurement: 100, same_floor: false }, { unit: "SF", measurement: 100, same_floor: 0 },
                     { unit: "SF", measurement: 100, same_floor: "" }],
    enabledOddities: [{ unit: "SF", measurement: 100, enabled: null }, { unit: "SF", measurement: 100, enabled: 0 },
                      { unit: "SF", measurement: 100, enabled: "false" }, { unit: "SF", measurement: 100, enabled: undefined }],
    onlySameFloor: [{ unit: "SF", measurement: 8000, same_floor: true }, { unit: "SF", measurement: 9000, same_floor: true }],
    itemRows: [{ kind: "item", item_id: "i1", measurement: 4000, unit: "SF", coverage: 500 }, { assembly_id: "a1", measurement: 6000, unit: "SF" }],
    floats: [{ unit: "SF", measurement: 0.1 }, { unit: "SF", measurement: 0.2 }],
  };
  for (const name of Object.keys(TAKEOFF)) {
    call("take/sf/" + name, "takeoffSf", TAKEOFF[name]);
    call("take/measured/" + name, "measuredSf", TAKEOFF[name]);
  }
  call("take/sf/noArguments", "takeoffSf");

  const AREAS = [0, 1, 3499, 3500, 3501, 7000, 7001, 12500, 17500, 35000, 35001, "12,500", "", null, undefined, NaN,
    -3500, "abc", 1e6, 0.5, NEG0];
  AREAS.forEach((a, i) => {
    for (const on of [true, false, undefined]) {
      call("dye/" + i + "/" + lbl(a) + "/" + lbl(on), "dyeCost", a, on);
      call("jf/" + i + "/" + lbl(a) + "/" + lbl(on), "jointFillerCost", a, on);
    }
  });
}

// ═════════════════════════════════════════════════════════════════════════════
// the conditions: workbook cells, defaults, which cards show
// ═════════════════════════════════════════════════════════════════════════════
function groupConditions(call) {
  const ALL_OFF = allConds("00000000");
  const ALL_ON = allConds("11111111");

  // ── what each condition writes into Kyle's workbook ────────────────────────
  call("cond/cells/allOff", "conditionCellWrites", ALL_OFF, {}, undefined);
  call("cond/cells/allOn", "conditionCellWrites", ALL_ON, {}, undefined);
  CONDITION_KEYS.forEach((k) => {
    call("cond/cells/only-" + k, "conditionCellWrites", make(ALL_OFF, { [k]: true }), {}, undefined);
    call("cond/cells/all-but-" + k, "conditionCellWrites", make(ALL_ON, { [k]: false }), {}, undefined);
  });
  call("cond/cells/undefinedConditions", "conditionCellWrites", undefined, {}, undefined);
  call("cond/cells/nullConditions", "conditionCellWrites", null, undefined, undefined);
  call("cond/cells/emptyConditions", "conditionCellWrites", {}, null, undefined);
  call("cond/cells/truthyNotBoolean", "conditionCellWrites",
    { taxable: 1, dye: "yes", local: 0, joint_filler: "", remodel_tax: "false", prevailing_wage: [] }, {}, undefined);
  call("cond/cells/keepsOtherCells", "conditionCellWrites", ALL_ON,
    { "Polish!B25": 0.5, "Epoxy!B4": "Maybe", "Other!A1": "kept", "Polish!E25": "No" }, undefined);
  call("cond/cells/unknownConditionKey", "conditionCellWrites", { taxable: true, bond: true, nonsense: true }, {}, undefined);

  // the library's own figures for the two priced lines (Dye, Joint Filler), written into the cells
  const SEED_DYE = { unit_price: 0.14, coverage: 1, waste_pct: 0, roundup: false, buy_qty: 1 };
  const SEED_JF = { unit_price: 500, coverage: 3500, waste_pct: 0, roundup: true, buy_qty: 1 };
  const LIBS = {
    absent: undefined, empty: {}, null_: null,
    dyeNull: { dye: null }, jfNull: { joint_filler: null },
    dyeUndefined: { dye: undefined }, jfUndefined: { joint_filler: undefined },
    seeds: { dye: SEED_DYE, joint_filler: SEED_JF },
    dyePriced: { dye: { unit_price: 0.2, coverage: 2, waste_pct: 5, roundup: false, buy_qty: 1 } },
    dyeWaste: { dye: { unit_price: 0.14, coverage: 1, waste_pct: 10, roundup: false, buy_qty: 1 } },
    dyeRoundup: { dye: { unit_price: 0.14, coverage: 1, waste_pct: 0, roundup: true, buy_qty: 1 } },
    dyeRoundupPack: { dye: { unit_price: 30, coverage: 100, waste_pct: 0, roundup: true, buy_qty: 5 } },
    dyeNoCoverage: { dye: { unit_price: 0.14, coverage: 0, waste_pct: 0, roundup: false, buy_qty: 1 } },
    dyeRoundupUndefined: { dye: { unit_price: 0.14, coverage: 1, waste_pct: 0, buy_qty: 1 } },
    jfPriced: { joint_filler: { unit_price: 450, coverage: 3000, waste_pct: 10, roundup: true, buy_qty: 1 } },
    jfFractional: { joint_filler: { unit_price: 500, coverage: 3500, waste_pct: 0, roundup: false, buy_qty: 1 } },
    jfPack: { joint_filler: { unit_price: 900, coverage: 3500, waste_pct: 0, roundup: true, buy_qty: 2 } },
    jfWasteNoRound: { joint_filler: { unit_price: 500, coverage: 3500, waste_pct: 5, roundup: false, buy_qty: 1 } },
    jfNoCoverage: { joint_filler: { unit_price: 500, coverage: "", waste_pct: 0, roundup: true, buy_qty: 1 } },
    jfDirty: { joint_filler: { unit_price: "$450", coverage: "3,000", waste_pct: "10", roundup: true, buy_qty: "2" } },
    bothPriced: { dye: { unit_price: 0.2, coverage: 2, waste_pct: 5, roundup: false, buy_qty: 1 },
                  joint_filler: { unit_price: 450, coverage: 3000, waste_pct: 10, roundup: true, buy_qty: 1 } },
  };
  for (const name of Object.keys(LIBS)) {
    call("cond/library/" + name, "conditionCellWrites", ALL_ON, {}, LIBS[name]);
  }
  // a quantity formula an earlier save wrote is replaced when the library goes back to the template's
  call("cond/library/replacesEarlierFormula", "conditionCellWrites", ALL_ON,
    { "Polish!B29": "=ROUNDUP(IF(E29=\"yes\",(E18*(1+10/100)/3000),0),0)" }, { joint_filler: SEED_JF });
  call("cond/library/leavesTemplateFormula", "conditionCellWrites", ALL_ON, {}, { joint_filler: SEED_JF });

  // ── the read-back: the cell wins over the model, a blank is not an answer ──
  const CELL_VALUES = ["Yes", "No", "yes", "no", " YES ", "", null, undefined, "maybe", 1, true, 0, "Y"];
  CELL_VALUES.forEach((v, i) => {
    call("cond/fromCells/taxable/" + i + "/" + lbl(v), "conditionsFromCells", { taxable: true, local: true },
      { "Epoxy!B6": v });
    call("cond/fromCells/jf/" + i + "/" + lbl(v), "conditionsFromCells", { joint_filler: false },
      { "Polish!E29": v });
  });
  call("cond/fromCells/allYes", "conditionsFromCells", ALL_OFF, {
    "Epoxy!B4": "Yes", "Epoxy!D5": "Yes", "Epoxy!B6": "Yes", "Epoxy!D6": "Yes", "Polish!E25": "Yes",
    "Polish!E29": "Yes", "Polish!F29": "Yes" });
  call("cond/fromCells/allNo", "conditionsFromCells", ALL_ON, {
    "Epoxy!B4": "No", "Epoxy!D5": "No", "Epoxy!B6": "No", "Epoxy!D6": "No", "Polish!E25": "No",
    "Polish!E29": "No", "Polish!F29": "No" });
  call("cond/fromCells/polishB4IsNotRead", "conditionsFromCells", { local: true }, { "Polish!B4": "No" });
  call("cond/fromCells/undefinedBoth", "conditionsFromCells", undefined, undefined);
  call("cond/fromCells/nullCells", "conditionsFromCells", { taxable: true }, null);
  call("cond/fromCells/stringCells", "conditionsFromCells", { taxable: true }, "abc");
  call("cond/fromCells/bondUntouched", "conditionsFromCells", { bond: true, taxable: true }, { "Epoxy!B6": "No" });

  // ── the company's answers, written over a NEW bid's conditions ─────────────
  const SEED_ROWS = {
    undef: undefined, null_: null, string: "abc", none: [],
    jf: [{ key: "joint_filler", on: true }],
    dyeAndJf: [{ key: "dye", on: true }, { key: "joint_filler", on: true }],
    allThree: [{ key: "joint_filler", on: true }, { key: "dye", on: true }, { key: "remove_existing_jf", on: true }],
    offAgain: [{ key: "joint_filler", on: true }, { key: "joint_filler", on: false }],
    unknownKey: [{ key: "zzz", on: true }],
    bondRow: [{ key: "bond", on: true }],
    noKey: [{ on: true }],
    nullRow: [null, undefined, { key: "dye", on: true }],
    truthyOn: [{ key: "dye", on: "false" }, { key: "joint_filler", on: 1 }, { key: "remove_existing_jf", on: 0 }],
    missingOn: [{ key: "dye" }],
    prototypeKey: [{ key: "constructor", on: true }, { key: "toString", on: true }],
  };
  const BASE_CONDS = { local: true, prevailing_wage: false, taxable: true, remodel_tax: false, bond: false, dye: false,
                       joint_filler: false, remove_existing_jf: false };
  for (const name of Object.keys(SEED_ROWS)) {
    call("cond/seed/" + name, "seedConditionDefaults", BASE_CONDS, SEED_ROWS[name]);
  }
  call("cond/seed/undefinedConditions", "seedConditionDefaults", undefined, SEED_ROWS.jf);
  call("cond/seed/nullConditions", "seedConditionDefaults", null, SEED_ROWS.dyeAndJf);

  // ── has anything been saved at all? ────────────────────────────────────────
  const SAVED = [undefined, null, {}, { a: 1 }, { version: 2 }, "abc", "", 0, 7, [], [1], { a: undefined }, { conditions: {} },
    { constructor: 1 }];
  SAVED.forEach((s, i) => call("cond/unstated/" + i + "/" + lbl(s), "conditionsUnstated", s));

  // ── which condition cards a new bid shows ──────────────────────────────────
  const SHOWN = {
    undef: undefined, none: [], string: "abc",
    dyeHidden: [{ key: "dye", listed: false }],
    jfListed: [{ key: "joint_filler", listed: true }],
    bondHidden: [{ key: "bond", listed: false }],
    twoHidden: [{ key: "remove_existing_jf", listed: false }, { key: "dye", listed: false }],
    noKey: [{ listed: false }], nullRow: [null, { key: "dye", listed: false }],
    listedMissing: [{ key: "dye" }], listedNull: [{ key: "dye", listed: null }],
    nonCellKey: [{ key: "local", listed: false }, { key: "taxable", listed: false }],
  };
  for (const name of Object.keys(SHOWN)) call("cond/shown/rows/" + name, "seedConditionsShown", SHOWN[name]);
  const MODELS = {
    undef: undefined, null_: null, empty: {},
    onAndHidden: { conditions: { dye: true }, conditions_shown: { dye: false } },
    offAndHidden: { conditions: { dye: false }, conditions_shown: { dye: false } },
    shownTrue: { conditions_shown: { dye: true } },
    emptyMap: { conditions_shown: {} },
    noConditions: { conditions_shown: { joint_filler: false } },
    mapNull: { conditions: { dye: false }, conditions_shown: null },
  };
  for (const name of Object.keys(MODELS)) {
    for (const key of ["dye", "joint_filler"]) {
      call("cond/shown/model/" + name + "/" + key, "conditionShown", MODELS[name], key);
    }
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// the global defaults: labor rate, fees, lodging, per diem
// ═════════════════════════════════════════════════════════════════════════════
function groupRates(call) {
  [undefined, null, "", 0, -5, 33, 50, "50", "$50", "abc", NaN, Infinity, 0.01, "0", true, 33.5, " 40 "].forEach((v, i) => {
    call("rate/orShipped/" + i + "/" + lbl(v), "laborRateOrShipped", v);
  });

  const rule = (key, formula, over) => make({ id: "r", layout: "global", line_key: key, formula: formula, applies: true }, over);
  const RULE_SETS = {
    undef: undefined, null_: null, string: "abc", object: {}, empty: [],
    nullEntry: [null],
    plain: [rule("labor_rate", "50")],
    dollars: [rule("labor_rate", "$50")],
    cents: [rule("labor_rate", "33.50")],
    spaces: [rule("labor_rate", "  $ 41.25  ")],
    expression: [rule("labor_rate", "=50*2")],
    percent: [rule("labor_rate", "50%")],
    zero: [rule("labor_rate", "0")],
    blank: [rule("labor_rate", "")],
    formulaNull: [rule("labor_rate", null)],
    formulaUndefined: [rule("labor_rate", undefined)],
    formulaNumber: [rule("labor_rate", 55)],
    off: [rule("labor_rate", "50", { applies: false })],
    appliesMissing: [rule("labor_rate", "50", { applies: undefined })],
    otherLayout: [rule("labor_rate", "50", { layout: "polish" })],
    otherKey: [rule("overhead", "50")],
    firstWins: [rule("labor_rate", "40"), rule("labor_rate", "60")],
    offThenOn: [rule("labor_rate", "40", { applies: false }), rule("labor_rate", "60")],
    badThenGood: [rule("labor_rate", "abc"), rule("labor_rate", "60")],
    withFees: [rule("fees_textura", "750"), rule("labor_rate", "40")],
    feesZero: [rule("fees_textura", "0")],
    feesDollars: [rule("fees_textura", "$1,200")],
    feesDecimal: [rule("fees_textura", "1200.5")],
    feesOff: [rule("fees_textura", "750", { applies: false })],
    feesJunk: [rule("fees_textura", "lots")],
    lodgingAndPerDiem: [rule("travel_lodging", "99"), rule("travel_per_diem", "77")],
    lodgingOnly: [rule("travel_lodging", "$85.5")],
    perDiemOnly: [rule("travel_per_diem", "52")],
    lodgingOff: [rule("travel_lodging", "99", { applies: false }), rule("travel_per_diem", "77")],
    lodgingZero: [rule("travel_lodging", "0"), rule("travel_per_diem", "-5")],
    lodgingJunk: [rule("travel_lodging", "a lot"), rule("travel_per_diem", null)],
    lodgingOtherLayout: [rule("travel_lodging", "99", { layout: "epoxy" })],
    lodgingTwice: [rule("travel_lodging", "99"), rule("travel_lodging", "120")],
    everything: [rule("labor_rate", "40"), rule("fees_textura", "500"), rule("travel_lodging", "90"), rule("travel_per_diem", "60")],
  };
  for (const name of Object.keys(RULE_SETS)) {
    call("rate/laborRule/" + name, "laborRateFromRules", RULE_SETS[name]);
    call("rate/feesRule/" + name, "feesFromRules", RULE_SETS[name]);
    call("rate/travelRule/" + name, "travelRatesFromRules", RULE_SETS[name]);
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// the model: fresh, migrated, blocked
// ═════════════════════════════════════════════════════════════════════════════
const V1_DRAFT = {
  areas: [{ name: "Main sales floor", sf: 9000 }, { name: "Back of house", sf: "3,500" }],
  system: "S&P", tooling: "traditional",
  conditions: { local: false, prevailing_wage: true, taxable: true, remodel_tax: true },
  materials: { 17: { qty: 12500, cost: 0.15 }, 29: { qty: 4, cost: 500 } },
  added: [{ name: "Stair nosing infill", qty: 46, cost: 12.5 }],
  labour: { polishing: { crew: 4, days: 6, rate: 32.2 }, mockup: { crew: 2, days: 1, rate: 32.2 },
            joint_filler: { crew: 2, days: 2, rate: 32.2 } },
  adds: { ram_board: 240, cove_4: 60 }, options: { salt_pepper: true, dye: true },
};
const STALE_V2_NO_TRAVEL = {
  version: 2,
  takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000, unit: "SF" }],
  labor: [{ id: "polishing", label: "Polishing", guys: 4, days: 6, rate: 33 },
          { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
          { id: "jointfill", label: "Joint filler", guys: 2, days: 3, rate: 33 },
          { id: "u_1699999999_1", label: "Demo prep", guys: 2, days: 1, rate: 40 }],
  conditions: { taxable: false }, contingency: 500,
};
const TRAVEL_PRE_HOURS = {
  version: 2,
  takeoff: [{ assembly_id: "a1", assembly_name: "Salt & Pepper polish", measurement: 9000, unit: "SF" }],
  labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
          { id: "travel", label: "Travel", guys: 6, days: 2, rate: "" }],
  conditions: {}, contingency: 0,
};
/** A v2 model the way the page writes it today: calculator rows, default rows switched off, a travel
 *  block, a distance, the unit price snapshot. Captured from a real new bid on staging. */
const CURRENT_SHAPE = {
  version: 2,
  takeoff: [
    { assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 10000, unit: "SF", same_floor: true, enabled: false },
    { assembly_id: "a2", assembly_name: "Cove Base", measurement: "", unit: "LF", enabled: false },
    { assembly_id: "", assembly_name: "", measurement: 10000, unit: "SF" },
  ],
  labor: [
    { id: "polishing", label: "Polishing", guys: 5, days: 10, rate: 50, hours_per_day: 10,
      calc_default: { guys: 5, days: 10, rate: 50, hours_per_day: 10, sf_per_day: 1000 } },
    { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 50, rate_default: 50 },
    { id: "jointfill", label: "Joint filler", guys: 3, days: "", rate: 50, rate_default: 50 },
    { id: "travel", label: "Travel Labor", guys: 51.5, days: 5, rate: 41, unit: "hours", guys_auto: true,
      enabled: false, hours_seed: 5, rate_default: 41 },
    { id: "lab-x", label: "Tint", guys: "", days: "", rate: 50, unit: "days", guys_auto: false, enabled: false, rate_default: 50 },
  ],
  conditions: { local: false, prevailing_wage: false, taxable: true, remodel_tax: false, bond: false, dye: true,
                joint_filler: true, remove_existing_jf: true },
  contingency: 0, fees: 0,
  travel: { lodging: { label: "Lodging", enabled: true, qty: 51.5, qty_auto: true, rate: 99, rate_default: 99 },
            per_diem: { label: "Per Diem", enabled: true, qty: 51.5, qty_auto: true, rate: 77, rate_default: 77 } },
  totals: { total: 72397, sf: 10000, per_sf: 7.2397 },
  conditions_shown: {},
  distance: { miles: 150, source: "google", key: "1 water works dr|kansas city|ks|66101" },
};

function groupModel(call) {
  call("model/fresh", "freshModel");

  const MIGRATE = {
    null_: null, undef: undefined, string: "not a model", number: 7, array: [], emptyObject: {}, boolTrue: true,
    v1: V1_DRAFT,
    v1NoLabor: { areas: [{ sf: 9000 }] },
    v1NoAreas: { areas: [], labour: {} },
    v2HalfKeys: { version: 2, takeoff: [], labor: null },
    v2OneCondition: { version: 2, conditions: { taxable: false } },
    v2StaleNoTravel: STALE_V2_NO_TRAVEL,
    v2TravelPreHours: TRAVEL_PRE_HOURS,
    partialConditions: { conditions: { taxable: false, dye: true } },
    partialTakeoff: { takeoff: [{ assembly_id: "a1", measurement: 100, unit: "SF" }] },
    partialLabor: { labor: [{ id: "polishing", guys: 2, days: 3, rate: 40 }] },
    partialContingency: { contingency: 500 },
    partialJunk: { foo: 1 },
    currentShape: CURRENT_SHAPE,
    // keys the model does not know: kept as saved since Phase 4 (until then they were dropped, and this
    // vector recorded that: it is the one vector Phase 4 moved)
    unknownKeys: Object.assign({}, STALE_V2_NO_TRAVEL, { tabs: { Epoxy: { layout: "epoxy", takeoff: [] } }, custom_key: 1 }),
    noTravelLabor: { version: 2, takeoff: [], labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: 33 }],
                     no_travel_labor: true, conditions: {} },
    noTravelLaborFalse: { version: 2, takeoff: [], labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: 33 }],
                          no_travel_labor: false, conditions: {} },
    condCov: { version: 2, takeoff: [], labor: [{ id: "travel", label: "Travel", guys: "", days: "", rate: 33 }],
               cond_cov: { joint_filler: 3000, dye: "", bond: 9, other: 1 }, conditions: {} },
    condCovEmpty: { version: 2, cond_cov: { joint_filler: "", dye: null } },
    conditionsShown: { version: 2, conditions_shown: { dye: false, joint_filler: true, local: false } },
    distanceTyped: { version: 2, distance: { miles: "85.26", source: "typed", key: "k" } },
    distanceJunk: { version: 2, distance: { miles: "abc", source: "x", key: 5 } },
    feesDefault: { version: 2, fees: "", fees_default: "750", contingency: "" },
    feesDefaultZero: { version: 2, fees: 0, fees_default: 0 },
    travelOnly: { version: 2, travel: { lodging: { enabled: true, qty_auto: false, qty: 3, rate: 90 } } },
    renamedTravel: { version: 2, labor: [{ id: "travel", label: "Drive time", guys: "", days: 2, rate: 35 }] },
    relabelTravel: { version: 2, labor: [{ id: "travel", label: "Travel", guys: 6, days: 2, rate: 33, unit: "hours", guys_auto: false }] },
    versionString: { version: "2", takeoff: [], labor: [] },
    versionThree: { version: 3, takeoff: [], labor: [] },
    sharesReferences: { version: 2, takeoff: [{ assembly_id: "a1", measurement: 1, unit: "SF" }],
                        labor: [{ id: "polishing", guys: 1, days: 1, rate: 1 }], totals: { total: 5 } },
  };
  for (const name of Object.keys(MIGRATE)) call("model/migrate/" + name, "migrateModel", MIGRATE[name]);

  const TK = [{ assembly_id: "a1", assembly_name: "A", measurement: 100, unit: "SF" }];
  const LB = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }];
  const BLOCK = {
    fresh: null,
    noTakeoff: { version: 2, takeoff: [], labor: LB },
    measureNoAssembly: { version: 2, takeoff: [{ assembly_id: "", assembly_name: "", measurement: 9000, unit: "SF" }], labor: LB },
    assemblyNoMeasure: { version: 2, takeoff: [{ assembly_id: "a1", assembly_name: "Salt", measurement: "", unit: "SF" }], labor: LB },
    assemblyNoMeasureNoName: { version: 2, takeoff: [{ assembly_id: "a1", assembly_name: "", measurement: 0, unit: "SF" }], labor: LB },
    itemRow: { version: 2, takeoff: [{ kind: "item", item_id: "i1", measurement: 100, unit: "SF" }], labor: LB },
    itemRowNoMeasure: { version: 2, takeoff: [{ kind: "item", item_id: "i1", item_name: "OPF", measurement: "", unit: "SF" }], labor: LB },
    offRow: { version: 2, takeoff: [{ assembly_id: "", measurement: 9000, unit: "SF", enabled: false }], labor: LB },
    laborNoDays: { version: 2, takeoff: TK, labor: [{ id: "polishing", label: "Polishing", guys: 3, days: "", rate: 33 }] },
    laborNoGuysNoDays: { version: 2, takeoff: TK, labor: [{ id: "polishing", label: "Polishing", guys: "", days: "", rate: 33 }] },
    laborOnlyRate: { version: 2, takeoff: TK, labor: [{ id: "polishing", label: "", guys: "", days: "", rate: 33 }] },
    namedAddedLine: { version: 2, takeoff: TK, labor: [{ id: "u_2", label: "Mobilize", guys: "", days: "", rate: 33 }] },
    travelNoHours: { version: 2, takeoff: TK, labor: [{ id: "travel", label: "Travel", guys: 18, days: "", rate: 33, unit: "hours", guys_auto: true }] },
    travelNoGuys: { version: 2, takeoff: TK, labor: [{ id: "travel", label: "Travel", guys: "", days: 2, rate: 33, unit: "hours", guys_auto: false }] },
    travelOff: { version: 2, takeoff: TK, labor: [{ id: "travel", label: "Travel", guys: "", days: 2, rate: "", unit: "hours", guys_auto: false, enabled: false }] },
    laborOff: { version: 2, takeoff: TK, labor: [{ id: "polishing", label: "Polishing", guys: 3, days: "", rate: 33, enabled: false }] },
    laborMissingRate: { version: 2, takeoff: TK, labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: "" }] },
    currentShape: CURRENT_SHAPE,
    garbage: "abc",
  };
  call("model/blockers/fresh", "blockers", { version: 2 });
  for (const name of Object.keys(BLOCK)) {
    if (name === "fresh") continue;
    call("model/blockers/" + name, "blockers", BLOCK[name]);
  }
  call("model/blockers/null", "blockers", null);
  call("model/blockers/noArgument", "blockers");
}

// ═════════════════════════════════════════════════════════════════════════════
// the labor calculator, and seeding a new bid's takeoff
// ═════════════════════════════════════════════════════════════════════════════
function groupCalcAndSeed(call) {
  const CFGS = {
    undef: undefined, null_: null, empty: {}, noMode: { mode: "x", crew: 3 }, string: "abc",
    sf: { mode: "sf", crew: 5, sf_per_day: 1000, hours_per_day: 10 },
    sfNoRate: { mode: "sf", crew: 5, sf_per_day: 0 },
    sfNoCrew: { mode: "sf", crew: 0, sf_per_day: 800 },
    sfOwnRate: { mode: "sf", crew: 4, sf_per_day: 750, rate: 38.5, hours_per_day: 8 },
    sfHpd12: { mode: "sf", crew: 2, sf_per_day: 500, hours_per_day: 12 },
    sfStrings: { mode: "sf", crew: "3", sf_per_day: "1,000", rate: "$40" },
    fixed: { mode: "fixed", guys: 3, days: 2 },
    fixedNoDays: { mode: "fixed", guys: 3 },
    fixedOwnRate: { mode: "fixed", guys: 2, days: 1.5, rate: 45, hours_per_day: 10 },
    fixedBlank: { mode: "fixed", guys: "", days: "" },
  };
  for (const name of Object.keys(CFGS)) {
    for (const [sf, dflt] of [[10000, 33], [0, 33], [8250.5, undefined], [null, 50], ["12,500", "x"]]) {
      call("calc/values/" + name + "/" + lbl(sf) + "/" + lbl(dflt), "laborCalcValues", CFGS[name], sf, dflt);
    }
  }

  const rows = () => [
    { id: "polishing", label: "Polishing", guys: 3, days: "", rate: 33 },
    { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
    { id: "jointfill", label: "Joint filler", guys: 3, days: "", rate: 33 },
    { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: true },
    { id: "lab-x", label: "Tint", guys: "", days: "", rate: 33, unit: "days" },
  ];
  const CALC = [
    { line_id: "polishing", mode: "sf", crew: 5, sf_per_day: 1000, hours_per_day: 10 },
    { line_id: "jointfill", mode: "fixed", guys: 2, days: 3 },
    { line_id: "travel", mode: "fixed", guys: 2, days: 2 },
    { line_id: "lab-x", mode: "fixed", guys: 1, days: 1, rate: 50 },
    { line_id: "unknown", mode: "fixed", guys: 1, days: 1 },
    { line_id: "mockup", mode: "nope" },
  ];
  call("calc/apply/all", "applyLaborCalc", rows(), CALC, 10000, 33);
  call("calc/apply/noSf", "applyLaborCalc", rows(), CALC, 0, 33);
  call("calc/apply/noCfgs", "applyLaborCalc", rows(), undefined, 10000, 33);
  call("calc/apply/emptyCfgs", "applyLaborCalc", rows(), [], 10000, 33);
  call("calc/apply/noRows", "applyLaborCalc", undefined, CALC, 10000, 33);
  call("calc/apply/nullEntries", "applyLaborCalc", [null, { id: "polishing", guys: 3, days: "", rate: 33 }],
    [null, { line_id: "polishing", mode: "sf", crew: 2, sf_per_day: 400 }], 9000, 40);
  call("calc/apply/numericIds", "applyLaborCalc", [{ id: 7, guys: 1, days: "", rate: 33 }],
    [{ line_id: 7, mode: "fixed", guys: 2, days: 2 }], 100, 33);

  // days follow the takeoff until somebody types over them
  const followed = (days, calcDays, spd) => [{ id: "polishing", label: "Polishing", guys: 5, days: days, rate: 50,
    calc_default: { guys: 5, days: calcDays, rate: 50, hours_per_day: 10, sf_per_day: spd } }];
  [[10, 10, 1000, 20000], [10, 10, 1000, 0], [10, 10, 1000, 10000], [12, 10, 1000, 20000], ["", "", 1000, 5000],
   ["", 10, 1000, 5000], [10, "", 1000, 5000], [10, 10, 0, 20000], [10, 10, undefined, 20000],
   ["10", 10, 1000, 20000], [10, 10, 333, 1000], [10, 10, 1000, "abc"], [10, 10, 1000, null]]
    .forEach(([d, cd, spd, sf], i) => call("calc/follow/" + i, "followLaborDays", followed(d, cd, spd), sf));
  call("calc/follow/noMarker", "followLaborDays", [{ id: "polishing", guys: 5, days: 10, rate: 50 }], 20000);
  call("calc/follow/noRows", "followLaborDays", undefined, 20000);
  call("calc/follow/nullRow", "followLaborDays", [null, undefined], 20000);

  const DIFFERS = [undefined, null, {}, { guys: 5, days: 10, rate: 50 }, followed(10, 10, 1000)[0],
    followed(12, 10, 1000)[0], Object.assign(followed(10, 10, 1000)[0], { rate: 51 }),
    Object.assign(followed(10, 10, 1000)[0], { guys: 4, hours_per_day: 8 }),
    { guys: 5, days: 10, rate: 50, hours_per_day: 10, calc_default: { guys: 5, days: 10, rate: 50, hours_per_day: 10 } },
    { guys: 5, days: 10, rate: 50, hours_per_day: 8, calc_default: { guys: 5, days: 10, rate: 50, hours_per_day: 10 } },
    { guys: "5", days: "10", rate: "50", calc_default: { guys: 5, days: 10, rate: 50, hours_per_day: 8 } }];
  DIFFERS.forEach((row, i) => call("calc/differs/" + i, "laborCalcDiffers", row));
  [undefined, null, {}, { hours_per_day: 10 }, { hours_per_day: "10" }, { hours_per_day: 12 }, { hours_per_day: 8 },
   { hours_per_day: 10.5 }].forEach((row, i) => call("calc/dayHours/" + i, "dayHours", row));

  // ── seeding a new bid's takeoff from the intake's square feet ──────────────
  const blankRow = () => ({ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" });
  const SEED = {
    blankBoth: [[blankRow()], 8250, 1000], blankOne: [[blankRow()], 8250, ""], blankSecond: [[blankRow()], "", 4000],
    blankNone: [[blankRow()], "", ""], blankZeroes: [[blankRow()], 0, 0],
    blankDirty: [[blankRow()], "8,250", "$1,000"], blankNegative: [[blankRow()], -5, 100],
    noRows: [[], 8250, 1000], undefRows: [undefined, 8250, 1000], nullRows: [null, 8250, ""], stringRows: ["abc", 100, 100],
    alreadyMeasured: [[{ assembly_id: "a1", measurement: 5000, unit: "SF" }], 8250, 1000],
    alreadyMeasuredLf: [[{ assembly_id: "", measurement: 900, unit: "LF" }], 8250, 1000],
    pickedNoMeasure: [[{ assembly_id: "a1", assembly_name: "A", measurement: "", unit: "SF" }], 8250, ""],
    lfBlank: [[{ assembly_id: "", measurement: "", unit: "LF" }], 8250, ""],
    noUnitBlank: [[{ assembly_id: "", measurement: "" }], 8250, ""],
    holes: [[null, blankRow()], 8250, ""],
  };
  for (const name of Object.keys(SEED)) call("seed/takeoffSf/" + name, "seedTakeoffSf", ...SEED[name]);

  const ASMS = [
    { id: "a1", name: "Polish 800 Grit", unit: "SF", favorite: true },
    { id: "a2", name: "Cove Base", unit: "LF", favorite: true },
    { id: "a3", name: "Densifier Only", unit: "SF", favorite: true, default_on: false },
    { id: "a4", name: "Not a default", unit: "SF", favorite: false },
    { id: "a5", name: "Epoxy only", unit: "SF", favorite: true, default_work_types: ["epoxy"] },
    { id: "a6", name: "Polish and seal", unit: "sf", favorite: true, default_work_types: ["seal", "polish"] },
    { id: "a7", name: "Lowercase lf", unit: "lf", favorite: true },
  ];
  const ITEMS = [
    { id: "i1", name: "OPF", favorite: true },
    { id: "dye", name: "Dye", favorite: true },
    { id: "joint-filler-kit", name: "Joint filler kit", favorite: true },
    { id: "i2", name: "Not favorite", favorite: false },
    { id: "i3", name: "Item off", favorite: true, default_on: false },
  ];
  const RESERVED = ["dye", "joint-filler-kit", "remove-existing"];
  const DEFAULTS = {
    none: [[blankRow()], [], [], RESERVED, 8250, 1000],
    asmsOnly: [[blankRow()], ASMS, [], RESERVED, 8250, 1000],
    itemsOnly: [[blankRow()], [], ITEMS, RESERVED, 8250, ""],
    both: [[blankRow()], ASMS, ITEMS, RESERVED, 8250, 1000],
    bothNoSf: [[blankRow()], ASMS, ITEMS, RESERVED, "", ""],
    onlyOffDefaults: [[blankRow()], [ASMS[2]], [ITEMS[4]], RESERVED, 5000, ""],
    onlyLfDefaults: [[blankRow()], [ASMS[1], ASMS[6]], [], RESERVED, 5000, ""],
    alreadyHasRows: [[{ assembly_id: "a1", measurement: 100, unit: "SF" }], ASMS, ITEMS, RESERVED, 8250, 1000],
    alreadyHasItem: [[{ item_id: "i1", measurement: "", unit: "SF" }], ASMS, ITEMS, RESERVED, 8250, 1000],
    noReservedList: [[blankRow()], [], ITEMS, undefined, 8250, ""],
    junkCatalogs: [[blankRow()], "abc", null, undefined, 8250, ""],
  };
  for (const name of Object.keys(DEFAULTS)) call("seed/default/" + name, "seedDefaultTakeoff", ...DEFAULTS[name]);

  // typing into a measurement keeps the same-floor rows honest (it writes into the rows in place).
  // setMeasurement returns nothing, so its whole answer is the rows as the call left them, which the
  // golden keeps as `after` on each of these vectors.
  const floor = () => [
    { assembly_id: "a1", measurement: 10000, unit: "SF" },
    { assembly_id: "a3", measurement: 10000, unit: "SF", same_floor: true },
    { assembly_id: "a2", measurement: 300, unit: "LF" },
    { assembly_id: "a4", measurement: 10000, unit: "SF", same_floor: true, enabled: false },
  ];
  [[0, 12000], [1, 4000], [2, 350], [3, 99], [0, ""], [0, "9,000"], [9, 5], [-1, 5]].forEach(([i, v], n) => {
    call("seed/setMeasurement/" + n, "setMeasurement", floor(), i, v);
  });
  call("seed/setMeasurement/offCarrier", "setMeasurement", [
    { unit: "SF", measurement: 100, enabled: false }, { unit: "SF", measurement: 100, same_floor: true }], 0, 200);
  call("seed/setMeasurement/noRows", "setMeasurement", undefined, 0, 5);

  // Which rows a carrier drags and which it leaves alone: one layout per promise in the comment on
  // setMeasurement, each the rows as they stand BEFORE the typing (the arguments are [rows, i, value]).
  const sf = (m, over) => Object.assign({ unit: "SF", measurement: m }, over);
  const DRAG = {
    // the first default is switched OFF, so a same-floor row can sit ABOVE the row that carries the area
    sameFloorAbove: [[sf(10000, { same_floor: true, enabled: false }), sf(10000), sf(10000, { same_floor: true })], 1, 12000],
    // a plain SF row and an LF row that happen to hold the same number are somebody else's work
    plainRowsSameNumber: [[sf(10000), sf(10000), { unit: "LF", measurement: 10000 }, sf(10000, { same_floor: true })], 0, 12000],
    // a same-floor row that already holds something else is left alone
    sameFloorHoldsOther: [[sf(10000), sf(10000, { same_floor: true }), sf(7500, { same_floor: true })], 0, 12000],
    // typing into an LF row never drags the floor, even when the two numbers match
    lfCarrierSameNumber: [[{ unit: "LF", measurement: 10000 }, sf(10000, { same_floor: true })], 0, 12000],
    // the page keeps what was typed ("9,000"), so rows are compared as numbers, not as text
    typedAsText: [[sf("9,000"), sf(9000, { same_floor: true }), sf("9,000", { same_floor: true })], 0, "12,000"],
    // a hole in the list is stepped over
    nullRowInList: [[null, sf(10000), sf(10000, { same_floor: true })], 1, 12000],
  };
  for (const name of Object.keys(DRAG)) call("seed/setMeasurement/" + name, "setMeasurement", ...DRAG[name]);
}

// ═════════════════════════════════════════════════════════════════════════════
// what a NEW bid is started with: the company defaults written onto it, once
// ═════════════════════════════════════════════════════════════════════════════
function groupNewBidSeeding(call) {
  // the Travel row, from the library's stored row
  const TRAVEL_ROWS = {
    undef: undefined, empty: {}, named: { name: "Travel", rate: 41 }, renamed: { name: "Drive time", rate: "", unit: "days", guys_auto: false },
    blankRate: { rate: "" }, zeroRate: { rate: 0 }, stringRate: { rate: "44.5", unit: "hours" },
    junk: { rate: "abc", unit: "" }, autoZero: { guys_auto: 0 }, autoYes: { guys_auto: "yes" }, blankName: { name: " " },
    travelLabor: { name: "Travel Labor", rate: 35 },
  };
  for (const name of Object.keys(TRAVEL_ROWS)) {
    call("newbid/travelSeed/" + name, "travelSeed", TRAVEL_ROWS[name]);
    call("newbid/travelSeed/" + name + "/dflt50", "travelSeed", TRAVEL_ROWS[name], 50);
  }
  [[], [99, 77], ["abc", 0], [-1, null], ["", ""], [50], [0.5, 45.5]].forEach((args, i) => {
    call("newbid/travelCostsSeed/" + i, "travelCostsSeed", ...args);
  });

  // the two travel rates, onto a new bid's lodging and per diem lines
  const TRAVEL_BLOCKS = {
    undef: undefined, null_: null,
    shipped: { lodging: { label: "Lodging", enabled: false, qty: "", qty_auto: true, rate: 70 },
               per_diem: { label: "Per Diem", enabled: false, qty: "", qty_auto: true, rate: 45 } },
    typed: { lodging: { label: "Lodging", enabled: true, qty: 4, qty_auto: false, rate: 85 },
             per_diem: { label: "Per Diem", enabled: false, qty: "", qty_auto: true, rate: 52 } },
    oneLine: { lodging: { enabled: true, rate: 70 } },
    junkLine: { lodging: "x", per_diem: null },
  };
  const RATE_PAIRS = { undef: undefined, null_: null, empty: {}, both: { lodging: 99, per_diem: 77 },
                       partial: { lodging: null, per_diem: 60 }, junk: { lodging: "x", per_diem: -3 } };
  for (const t of Object.keys(TRAVEL_BLOCKS)) {
    for (const r of Object.keys(RATE_PAIRS)) call("newbid/travelRates/" + t + "/" + r, "applyTravelRates", TRAVEL_BLOCKS[t], RATE_PAIRS[r]);
  }

  // the company labor rate, onto the crew rows and a Travel row that is still on the shipped $33
  const LABOR_SETS = {
    undef: undefined, none: [], crewTravel: rowsets().crewTravel,
    travelTyped: CREW().concat([TRAVEL_ROW({ rate: 41 })]),
    travelBlank: CREW().concat([TRAVEL_ROW({ rate: "" })]),
    custom: CREW().concat([{ id: "u_1", label: "Saw cutting", guys: 2, days: 1, rate: 40 }]),
    nullEntries: [null, CREW()[0]],
  };
  for (const name of Object.keys(LABOR_SETS)) {
    for (const rate of [50, undefined, "x"]) call("newbid/laborRate/" + name + "/" + lbl(rate), "applyLaborRate", LABOR_SETS[name], rate);
  }
  const STAMP = {
    undef: undefined, crew: CREW(), calc: [make(CREW()[0], { calc_default: { guys: 3, days: 5, rate: 33, hours_per_day: 8 } })],
    already: [make(CREW()[0], { rate_default: 28 })], nulls: [null, CREW()[1]], blankRate: [{ id: "x", rate: "" }],
  };
  for (const name of Object.keys(STAMP)) call("newbid/stampRateDefaults/" + name, "stampRateDefaults", STAMP[name]);

  // the Fees + Textura default
  const MODELS = { undef: undefined, null_: null, plain: { fees: 0, a: 1 }, withDefault: { fees: 100, fees_default: 50 }, nested: { fees: 0, takeoff: [{ a: 1 }] } };
  for (const name of Object.keys(MODELS)) {
    [750, 0, null, "", "abc", -5, "750", NaN, "1,200"].forEach((f, i) => {
      call("newbid/feesDefault/" + name + "/" + i + "/" + lbl(f), "applyFeesDefault", MODELS[name], f);
    });
  }

  // a stored library_labor row turned into a labor row, and the defaults added beside the built-ins
  const LIB_ROWS = {
    undef: undefined, empty: {}, tint: { id: "lab-x", name: "Tint", rate: 0, unit: "days", guys_auto: false },
    ownRate: { id: "lab-y", name: "Saw", rate: 41, unit: "days" }, zeroString: { id: "z", name: "Z", rate: "0" },
    junkRate: { id: "j", name: "J", rate: "abc" }, off: { id: "o", name: "Off", rate: 35, default_on: false },
    autoOne: { id: "a", name: "A", rate: 30, guys_auto: 1 },
  };
  for (const name of Object.keys(LIB_ROWS)) {
    for (const d of [undefined, null, 50]) call("newbid/libraryLaborRow/" + name + "/" + lbl(d), "libraryLaborRow", LIB_ROWS[name], d);
  }
  const LIBRARY = {
    notArray: undefined, empty: [],
    travelDeclined: [{ id: "travel", name: "Travel", rate: 33, favorite: false }],
    travelEpoxyOnly: [{ id: "travel", name: "Travel", rate: 33, favorite: true, default_work_types: ["epoxy"] }],
    travelAllowed: [{ id: "travel", name: "Travel", rate: 33 }],
    travelOwnRate: [{ id: "travel", name: "Travel", rate: 41, unit: "hours", guys_auto: true, default_on: false }],
    customFavorites: [{ id: "lab-x", name: "Tint", rate: 0, unit: "days", favorite: true },
                      { id: "lab-y", name: "Saw", rate: 41, unit: "days", favorite: true, default_work_types: ["polish"] }],
    customEpoxyOnly: [{ id: "lab-e", name: "Epoxy only", rate: 40, favorite: true, default_work_types: ["epoxy"] }],
    customNotFavorite: [{ id: "lab-n", name: "Not a default", rate: 40, favorite: false }],
    duplicatesBuiltIn: [{ id: "polishing", name: "Polishing again", rate: 99, favorite: true }],
    nullAndNoId: [null, { name: "No id", favorite: true }, { id: null, favorite: true }],
    everything: [{ id: "travel", name: "Travel", rate: 41, favorite: true }, { id: "lab-x", name: "Tint", rate: 0, favorite: true },
                 { id: "lab-off", name: "Off", rate: 35, favorite: true, default_on: false }],
  };
  for (const name of Object.keys(LIBRARY)) {
    for (const wt of [undefined, "polish", "epoxy"]) {
      call("newbid/seedLabor/" + name + "/" + lbl(wt), "seedLibraryLabor", rowsets().crewTravel, LIBRARY[name], 50, wt);
    }
  }
  call("newbid/seedLabor/noDefaultRate", "seedLibraryLabor", rowsets().crewTravel, LIBRARY.customFavorites, undefined, "polish");
  call("newbid/seedLabor/emptyLabor", "seedLibraryLabor", undefined, LIBRARY.customFavorites, 50, "polish");

  // does the stored Travel row put Travel on a new bid of this work type?
  const TR_STORED = [undefined, {}, { favorite: false }, { favorite: true }, { favorite: null }, { default_work_types: ["epoxy"] },
    { default_work_types: ["polish"] }, { default_work_types: [] }, { default_work_types: "polish" }, { favorite: false, default_work_types: ["polish"] }];
  TR_STORED.forEach((row, i) => {
    for (const wt of [undefined, "polish", "epoxy"]) call("newbid/travelApplies/" + i + "/" + lbl(wt), "travelAppliesToBid", row, wt);
  });
  const DECLINED = { notArray: undefined, empty: [], declined: [{ id: "travel", favorite: false }], plain: [{ id: "travel" }],
                     otherRow: [{ id: "x" }], epoxyOnly: [{ id: "travel", default_work_types: ["epoxy"] }], numericId: [{ id: "travel" }, null] };
  for (const name of Object.keys(DECLINED)) {
    for (const wt of [undefined, "polish", "epoxy"]) call("newbid/travelDeclined/" + name + "/" + lbl(wt), "travelDeclined", DECLINED[name], wt);
  }

  // has anybody ever stated a labor row?
  const UNSTATED = [undefined, null, {}, { version: 2 }, { version: 2, labor: [] }, { version: 2, labor: [{}] }, { version: 1 },
    { labor: [1] }, "abc", 0, { version: "2", labor: [] }, { version: 2, labor: "x" }, { version: 2, labor: null }];
  UNSTATED.forEach((s, i) => call("newbid/laborUnstated/" + i + "/" + lbl(s), "laborUnstated", s));
}

G.main({
  script: "gen-chain-golden.js",
  generator: "backend/tests/js/gen-chain-golden.js",
  recipeVersion: RECIPE_VERSION,
  build: build,
}, process.argv);
