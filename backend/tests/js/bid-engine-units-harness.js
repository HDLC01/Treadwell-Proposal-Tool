"use strict";
/* The bid engine's own behaviour, as a table of answers: profiles and `extends`, reading a filed Markups rule,
 * what is unpriceable, combining the tabs of a job, and every call that must throw.
 *
 *   node bid-engine-units-harness.js [<frontend dir>]
 *
 * Prints one JSON object; backend/tests/test_bid_engine.py reads it. Where a case needs profile data the real
 * module does not have (a profile that extends itself, a quirk nobody reads), the engine's own source is loaded
 * a second time against a stand-in for bid-profiles.js, so the real engine code runs on made-up data.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const HERE = __dirname;
const REPO = path.resolve(HERE, "..", "..", "..");
const FRONTEND = process.argv[2] ? path.resolve(process.argv[2]) : path.join(REPO, "frontend");
const J = (f) => path.join(FRONTEND, "js", f);

const E = require(J("bid-engine.js"));
const roundUp = require(J("excel-math.js")).roundUp;
const P = require(J("bid-profiles.js"));
const K = require(J("markup-core.js"));
const M = require(J("bid-model.js"));

/** The real engine source, loaded again with `profiles` standing in for bid-profiles.js. */
function engineOn(profiles) {
  const src = fs.readFileSync(J("bid-engine.js"), "utf8");
  const mod = { exports: {} };
  const req = (name) => {
    if (name === "./bid-profiles.js") return profiles;
    return require(J(name.replace(/^\.\//, "")));
  };
  vm.runInNewContext("(function (module, require, self) {" + src + "\n})", {})(mod, req, undefined);
  return mod.exports;
}

function thrown(fn) {
  try { fn(); return null; } catch (e) { return { name: e && e.name, message: String(e && e.message) }; }
}
const clone = (o) => JSON.parse(JSON.stringify(o));
const rule = (layout, line_key, formula, extra) => Object.assign({ layout, line_key, formula, applies: true }, extra || {});

const out = {};

// ── profiles ─────────────────────────────────────────────────────────────────
{
  const polish = E.resolveProfile("polish"), seal = E.resolveProfile("seal"), legacy = E.resolveProfile("polish-legacy");
  out.extends = {
    chains: Object.fromEntries(Object.keys(P.profiles).map((id) => [id, E.resolveProfile(id).chain])),
    sealOnlyDiffersInGp: Object.keys(seal.rates).filter((k) => seal.rates[k] !== polish.rates[k]),
    sealQuirksSame: JSON.stringify(seal.quirks) === JSON.stringify(polish.quirks),
    legacyQuirksDiffer: Object.keys(legacy.quirks).filter((k) => legacy.quirks[k] !== polish.quirks[k]).sort(),
    legacyRatesSame: JSON.stringify(legacy.rates) === JSON.stringify(polish.rates),
    frozen: Object.isFrozen(polish) && Object.isFrozen(polish.quirks) && Object.isFrozen(polish.rates),
    sameObjectTwice: E.resolveProfile("polish") === polish,
    gypDropsShipPct: !("ship_pct" in E.resolveProfile("gyp").rates) && !("hard_bid" in E.resolveProfile("gyp").rates),
    globalsFilledIn: ["labor_rate", "travel_lodging", "travel_per_diem", "fees_textura", "bond", "sales_tax"]
      .every((k) => typeof polish.rates[k] === "string"),
    levelingLaborRate: E.resolveProfile("leveling").rates.labor_rate,
    stamps: Object.fromEntries(Object.keys(P.profiles).map((id) => [id, E.resolveProfile(id).stamp])),
  };
  out.data = {
    jsonRoundTrip: JSON.stringify(JSON.parse(JSON.stringify(P.profiles))) === JSON.stringify(P.profiles),
    noFunctionsOrUndefined: !/undefined|function/.test(JSON.stringify(P.profiles)) &&
      (function walk(o) { return o === null || typeof o !== "object" ? typeof o !== "function" && o !== undefined
        : Object.keys(o).every((k) => walk(o[k])); })(P.profiles),
    quirkNames: P.quirks,
    everyProfileStatesEveryQuirk: Object.keys(P.profiles).every((id) => E.resolveProfile(id) && true),
    everyRateParses: Object.keys(P.profiles).every((id) => {
      const r = E.resolveProfile(id);
      return Object.keys(r.rates).every((k) => K.validate(r.rates[k]).ok);
    }),
    everyDefaultParses: Object.keys(P.defaults).every((k) => K.validate(P.defaults[k]).ok),
    everyTabHasAProfile: P.priced.every((t) => E.forTab(t).profile.id === P.tabs[t].profile),
    onlyGypTabsHaveATruckload: P.priced.every((t) => (E.forTab(t).truckload !== null) === (E.forTab(t).profile.layout === "gyp")),
  };
}

// ── bad calls throw, and say what to give ────────────────────────────────────
out.throws = {
  resolveNothing: thrown(() => E.resolveProfile()),
  resolveUnknown: thrown(() => E.resolveProfile("nonesuch")),
  forTabUnknown: thrown(() => E.forTab("Combo")),
  priceNoProfile: thrown(() => E.priceChain(undefined, {})),
  priceProfileWithoutLayout: thrown(() => E.priceChain({ quirks: {}, rates: {} }, {})),
  priceUnknownId: thrown(() => E.priceChain("nonesuch", {})),
  gypWithoutTruckload: thrown(() => E.priceChain("gyp", { gyp: 1000 })),
  ruleNumberNoLayout: thrown(() => E.ruleNumber([], undefined, "gp")),
  ruleNumberEmptyLayout: thrown(() => E.ruleNumber([], "", "gp")),
  ruleNumberUnknownLine: thrown(() => E.ruleNumber([], "polish", "escalation")),
  compileNoProfile: thrown(() => E.compileRates(undefined, [])),
  combineEmpty: thrown(() => E.combine([])),
  combineNoLayout: thrown(() => E.combine([{ result: E.priceChain("polish", { material: 1000 }) }])),
  combineNoResult: thrown(() => E.combine([{ layout: "polish" }])),
  defaultUnknown: thrown(() => E.defaultNumber("nonesuch")),
  bandsOfNotABand: thrown(() => E.bandsOf("2.7%")),
};

// ── the loader checks what it needs ──────────────────────────────────────────
{
  const src = fs.readFileSync(J("bid-engine.js"), "utf8");
  const run = (missing) => thrown(() => {
    const req = (name) => (name === missing ? undefined : require(J(name.replace(/^\.\//, ""))));
    vm.runInNewContext("(function (module, require, self) {" + src + "\n})", {})({ exports: {} }, req, undefined);
  });
  out.loader = {
    noMath: run("./excel-math.js"), noProfiles: run("./bid-profiles.js"), noMarkup: run("./markup-core.js"),
  };
  const model = fs.readFileSync(J("bid-model.js"), "utf8");
  out.loader.modelNeedsEngine = thrown(() => {
    const req = (name) => (name === "./bid-engine.js" ? undefined : require(J(name.replace(/^\.\//, ""))));
    vm.runInNewContext("(function (module, require, self) {" + model + "\n})", {})({ exports: {} }, req, undefined);
  });
}

// ── bad profile data is refused when it is resolved ──────────────────────────
{
  const base = clone(P);
  const bad = (edit) => { const p = clone(base); edit(p); return thrown(() => engineOn(p).resolveProfile("child")); };
  const withChild = (p, child) => { p.profiles.child = Object.assign({ rev: 1, layout: "polish", label: "x" }, child); };
  out.badData = {
    loops: bad((p) => { withChild(p, { extends: "other" }); p.profiles.other = { rev: 1, layout: "polish", extends: "child" }; }),
    selfLoop: bad((p) => withChild(p, { extends: "child" })),
    extendsNothing: bad((p) => withChild(p, { extends: "ghost" })),
    unknownQuirk: bad((p) => withChild(p, { extends: "polish", quirks: { aQuirkNobodyReads: true } })),
    missingQuirk: bad((p) => { p.quirks = p.quirks.concat(["aNewQuirk"]); withChild(p, { extends: "polish" }); }),
  };
}

// ── reading a filed rule ─────────────────────────────────────────────────────
{
  const r = (formula, layout, line, extra) => E.ruleNumber([rule(layout || "polish", line || "super_pto", formula, extra)], layout || "polish", line || "super_pto");
  out.rules = {
    nothingFiled: E.ruleNumber([], "polish", "super_pto"),
    notAList: E.ruleNumber(undefined, "polish", "super_pto"),
    otherLayout: E.ruleNumber([rule("epoxy", "super_pto", "4%")], "polish", "super_pto"),
    switchedOff: E.ruleNumber([rule("polish", "super_pto", "4%", { applies: false })], "polish", "super_pto"),
    blank: [null, "", "   "].map((f) => E.ruleNumber([rule("polish", "super_pto", f)], "polish", "super_pto")),
    percent: r("2.7%"),
    percentIsSnapped: r("2.7%").value === 0.027 && 2.7 / 100 !== 0.027,
    fourPointOne: r("4.1%").value === 0.041,
    zeroIsARate: r("0%"),
    dollarFigureForARate: r("500"),
    negativeRate: r("-5%"),
    parseError: r("(2.7%"),
    wordsNotAFormula: r("a lot"),
    unboundName: r("nobody * 2%"),
    gpLadder: r("MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 30%))", "polish", "gp"),
    gpFlat: r("MARKUP(30%)", "polish", "gp"),
    gpBare: r("45%", "polish", "gp"),
    gpDollars: r("MARKUP(5000)", "polish", "gp"),
    gpAtJob: E.ruleNumber([rule("polish", "gp", "MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 30%))")], "polish", "gp", { subtotal: 10000, sub_total: 10000 }),
    dollars: r("33", "global", "labor_rate"),
    dollarSign: r("$33.50", "global", "labor_rate"),
    percentWhereDollars: r("5%", "global", "labor_rate"),
    negativeDollars: r("-3", "global", "fees_textura"),
    zeroDollars: r("0", "global", "fees_textura"),
    dollarsAreReadFromGlobalOnly: E.ruleNumber([rule("polish", "labor_rate", "40")], "polish", "labor_rate"),
    bondFromGlobalForAnyLayout: E.ruleNumber([rule("global", "bond", "1%")], "gyp", "bond"),
    bondOnALayoutIsNotRead: E.ruleNumber([rule("gyp", "bond", "1%")], "gyp", "bond"),
    gypSoftWithSheetNames: r(P.profiles.gyp.rates.soft_costs, "gyp", "soft_costs"),
  };
}

// ── compiling the rules for a profile, and pricing with them ─────────────────
{
  const job = { material: 12000, labor: 6000, sf: 10000, conditions: { taxable: true } };
  const builtIn = E.priceChain("polish", job);
  const filedSuper = E.compileRates("polish", [rule("polish", "super_pto", "4%")]);
  const filedGp = E.compileRates("seal", [rule("seal", "gp", "MARKUP(30%)")]);
  const broken = E.compileRates("polish", [rule("polish", "super_pto", "500"), rule("polish", "soft_costs", "(2.7%")]);
  const mixed = E.compileRates("polish", [rule("polish", "gp", "MARKUP(30%)"), rule("polish", "soft_costs", "oops")]);
  const filedGlobal = E.compileRates("leveling", [rule("global", "labor_rate", "40"), rule("global", "bond", "2%")]);
  const switchedOff = E.compileRates("polish", [rule("polish", "super_pto", "4%", { applies: false })]);
  const local = { conditions: { local: false, taxable: true }, labor: 8000, material: 1000 };
  out.compile = {
    nothing: E.compileRates("polish", []),
    stamp: filedSuper.profile,
    filedSuper: filedSuper,
    switchedOffFilesNothing: switchedOff,
    builtInSuper: builtIn.super_pto,
    filedSuperPrices: E.priceChain("polish", job, filedSuper).super_pto,
    filedSuperIsFourPercentOfTheBase: E.priceChain("polish", job, filedSuper).super_pto ===
      roundUp((builtIn.sub_total + builtIn.gp + builtIn.contingency + builtIn.sales_tax + builtIn.fees) * 0.04),
    onlyTheFiledLineMoved: ["gp", "sub_total", "sales_tax", "burden"].every((k) => E.priceChain("polish", job, filedSuper)[k] === builtIn[k]),
    filedGpRate: E.priceChain("seal", job, filedGp).gp_pct,
    sealBuiltInGpRate: E.priceChain("seal", job).gp_pct,
    broken: broken,
    brokenPrices: (() => { const r = E.priceChain("polish", job, broken); return { priceable: r.priceable, line: r.line, reason: r.reason, total: r.total, keys: Object.keys(r) }; })(),
    mixedUnpriceable: Object.keys(mixed.unpriceable),
    mixedFiled: mixed.filed,
    mixedPrices: (() => { const r = E.priceChain("polish", job, mixed); return { priceable: r.priceable, reason: r.reason, total: r.total }; })(),
    absentSnapshotIsTheBuiltIns: JSON.stringify(E.priceChain("polish", job)) === JSON.stringify(E.priceChain("polish", job, undefined)) &&
      JSON.stringify(E.priceChain("polish", job)) === JSON.stringify(E.priceChain("polish", job, { rates: {}, unpriceable: {} })),
    filedGlobal: filedGlobal,
    lodgingAtBuiltInRate: E.priceChain("leveling", local).lodging_qty,
    lodgingAtFiledRate: E.priceChain("leveling", local, filedGlobal).lodging_qty,
    filedBondPrices: E.priceChain("leveling", job, filedGlobal).bond_pct,
    // a ladder filed on a profile's layout reaches every profile of that layout
    epoxyLayoutRulesReachBlank: E.priceChain("epoxy-blank", job, E.compileRates("epoxy-blank", [rule("epoxy", "super_pto", "5%")])).super_pto > E.priceChain("epoxy-blank", job).super_pto,
    // the legacy bond has no input: a typed bond rate on a bid is ignored, and a compiled one is read
    legacyIgnoresTypedBond: E.priceChain("polish-legacy", Object.assign({ bond_pct: 0.02 }, job)).bond,
    sheetTakesTypedBond: E.priceChain("polish", Object.assign({ bond_pct: 0.02 }, job)).bond,
  };
}

// ── a job on several tabs ────────────────────────────────────────────────────
{
  // Two floors of the same size and a sub-total just under a gross profit rung each: pooled, the pair would
  // land a rung lower and pay a smaller margin.
  const epoxy = E.priceChain("epoxy", { material: 6000, labor: 5000, sf: 5000, conditions: { taxable: true } });
  const polish = E.priceChain("polish", { material: 12000, labor: 6000, sf: 5000, conditions: { taxable: true } });
  const both = E.combine([{ layout: "epoxy", result: epoxy }, { layout: "polish", result: polish }]);
  const pooledInput = { material: 18000, labor: 11000, sf: 10000, conditions: { taxable: true } };
  const pooled = E.priceChain("polish", pooledInput);
  const broken = E.priceChain("polish", { material: 1000 }, { unpriceable: { soft_costs: "oops" }, rates: {} });
  out.combine = {
    epoxyTotal: epoxy.total, polishTotal: polish.total, epoxyGpPct: epoxy.gp_pct, polishGpPct: polish.gp_pct,
    total: both.total, sumOfTotals: epoxy.total + polish.total, parts: both.parts, priceable: both.priceable,
    sumsGp: both.sums.gp === epoxy.gp + polish.gp,
    sumsEveryLine: Object.keys(both.sums).every((k) => both.sums[k] === (epoxy[k] || 0) + (polish[k] || 0)),
    pooledTotal: pooled.total, pooledGpPct: pooled.gp_pct, pooledSub: pooled.sub_total,
    brokenPart: E.combine([{ layout: "epoxy", result: epoxy }, { layout: "polish", result: broken }]),
    single: E.combine([{ layout: "epoxy", result: epoxy }]).total === epoxy.total,
  };
}

// ── the model reads the engine's numbers ─────────────────────────────────────
out.model = {
  rates: { SHIPPING: M.RATES.SHIPPING, ESCALATION: M.RATES.ESCALATION, BURDEN: M.RATES.BURDEN, SUPER_PTO: M.RATES.SUPER_PTO,
           SOFT_COSTS: M.RATES.SOFT_COSTS, SALES_TAX: M.RATES.SALES_TAX, BOND: M.RATES.BOND, FEES: M.RATES.FEES,
           SHEET_REMODEL: M.RATES.SHEET_REMODEL, KS_STATE: M.RATES.KS_STATE },
  literals: { SHIPPING: 0.02, ESCALATION: 0.05, BURDEN: 0.12, SUPER_PTO: 0.027, SOFT_COSTS: 0.16, SALES_TAX: 0.09475, BOND: 0,
              FEES: 0, SHEET_REMODEL: 0.10, KS_STATE: 0.065 },
  shipped: { labor: M.SHIPPED_LABOR_RATE, lodging: M.SHIPPED_LODGING_RATE, perDiem: M.SHIPPED_PER_DIEM_RATE },
  gpBands: M.GP_BANDS,
  bandsOfLegacy: E.bandsOf(E.resolveProfile("polish-legacy").rates.gp),
  bandsOfSeal: E.bandsOf(E.resolveProfile("seal").rates.gp),
  bandsOfGyp: E.bandsOf(E.resolveProfile("gyp").rates.gp),
  markupChainKeys: Object.keys(M.markupChain({})),
  markupChainPicksEngine: (() => {
    const input = { material: 12345, labor: 6789, travel: 100, fees: 250, contingency: 125.5, sf: 9000,
      conditions: { prevailing_wage: true, taxable: true, remodel_tax: true }, remodel_rate: 0.07975 };
    const m = M.markupChain(input), e = E.priceChain("polish-legacy", input);
    return Object.keys(m).every((k) => m[k] === e[k]);
  })(),
  seedLibraryLaborPlainIds: (() => {
    // ids that collide with Object.prototype names are ordinary ids, not "already seen"
    const rows = [{ id: "constructor", favorite: true, rate: 33, label: "x" }, { id: "toString", favorite: true, rate: 33, label: "y" }];
    return M.seedLibraryLabor([], rows, undefined, "polish").map((r) => String(r.id));
  })(),
};

console.log(JSON.stringify(out));
