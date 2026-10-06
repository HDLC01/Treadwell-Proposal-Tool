"use strict";
/* THE SAVED ESTIMATE MODEL KEEPS WHAT IT DOES NOT KNOW, AND EVERY WRITER SAVES IT THE SAME WAY.
 *
 * Phase 4 of the v2 estimating program. Two defects stood in the way of every later phase:
 *
 *   1. migrateModel's v2 branch REBUILT the model from a fixed key list, so any key it did not name
 *      was erased by the next save. Nothing writes the other sheets' `tabs`, a rates snapshot or a
 *      profile stamp yet; the moment something does, the first unrelated switch an estimator flips
 *      would erase it. So the model carries what it does not know.
 *   2. The estimate page composed the blob it saves in TWO places (the 600 ms autosave and the
 *      `pagehide` flush) and the two had drifted: the flush skipped the condition cells and the
 *      measured-floor fallback. One buildSavePatch now, and the intake's merge is one patchModel.
 *
 * WHAT THIS EXECUTES, and why nothing here is a source assertion:
 *
 *   * the REAL polish-bid-core.js, over EVERY saved-bid fixture saved-bid-scenarios.js holds (lifted
 *     from that file by name, not copied: a fixture added there is covered here) plus synthetic
 *     models carrying `work_type`, `tabs`, a rates snapshot and a profile stamp;
 *   * the REAL estimate page (polish-estimate.js, whole), saved twice from identical drafts, once by
 *     its timer and once by `pagehide`, and the two writes compared;
 *   * the REAL intake page's save(), run after an estimate save over the same draft.
 *
 * The two pages are driven through the preludes of polish-estimate-harness.js and
 * polish-intake-harness.js (their DOM stubs, clock and TW stand-in), cut off where their own
 * scenarios begin: one stub per page, not two that drift.
 *
 * Every section catches its own failure and reports it as `{error}`, so the same harness can be run
 * over a tree that does not have the functions yet and fail as an assertion instead of a crash.
 *
 * Usage: node model-safety-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");
const G = require("./_golden.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "polish-bid-core.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const fromPairs = (names, fn) => Object.fromEntries(names.map((n) => [n, fn(n)]));
const last = (list) => list[list.length - 1];
/** `undefined` as null, because JSON drops a key whose value is undefined: a fact about something
 *  that went missing has to stay in the output to be asserted on. */
const nn = (v) => (v === undefined ? null : v);
/** A value as JSON text, or null when there is none (what an erased `tabs` looks like). */
const text = (v) => (v === undefined ? null : JSON.stringify(v));

/** Where two values first part, as a sentence, or null when they do not. */
function where(want, got) {
  const d = G.firstDifference(want, got);
  return d ? d.path + ": " + G.show(d.want) + " vs " + G.show(d.got) : null;
}

function deepFreeze(v) {
  if (v && typeof v === "object" && !Object.isFrozen(v)) {
    Object.freeze(v);
    Object.keys(v).forEach((k) => deepFreeze(v[k]));
  }
  return v;
}

// ── the saved-bid fixtures, lifted from the ratchet's own scenarios ───────────────────────────
// `staged`, `plainLabor` and `newest` are the file's own builders; FIXTURES and NEWEST are what
// test_polish_saved_bid_safety.py pins totals for. `ITEMS` is only read by an `opts` value this
// harness never uses.
const SCENARIOS = L.read(path.join(__dirname, "saved-bid-scenarios.js"));
const LIFTED = new Function("clone", "ITEMS", [
  L.grabConst(SCENARIOS, "OLD_TRAVEL"),
  L.liftSource(SCENARIOS, "staged"),
  L.grabConst(SCENARIOS, "FIXTURES"),
  L.grabConst(SCENARIOS, "ADDR_KEY"),
  L.grabConst(SCENARIOS, "RESERVED_ITEMS"),
  L.liftSource(SCENARIOS, "plainLabor"),
  L.liftSource(SCENARIOS, "newest"),
  L.grabConst(SCENARIOS, "NEWEST"),
  "return { FIXTURES: FIXTURES, NEWEST: NEWEST, RESERVED_ITEMS: RESERVED_ITEMS };",
].join("\n"))(clone, []);
const SAVED = Object.assign({}, LIFTED.FIXTURES, LIFTED.NEWEST);

// ── synthetic models: what a later phase will write beside the keys migrateModel knows ────────
// Section shape is the program plan's (layout, kind, profile "<id>@<rev>", takeoff, labor, a rates
// snapshot, totals). Tab names are the workbook's own, quotes and brackets included, so "byte
// identical" is tested on keys that are awkward to round-trip.
const TABS = {
  "Epoxy": {
    layout: "epoxy", kind: "base", profile: "epoxy@1",
    takeoff: [{ assembly_id: "e1", assembly_name: "Flake system", measurement: 4000, unit: "SF" }],
    labor: [{ id: "installing", label: "Installing", guys: 3, days: 2, rate: 33 }],
    contingency: 0, fees: 0,
    rates: { shipping: "2%", escalation: "5%", burden: "12%", version: 1 },
    totals: { total: 18250, sf: 4000 }, preset: null,
  },
  'Gyp (USG 1-8")': {
    layout: "gyp", kind: "base", profile: "gyp@2",
    takeoff: [{ assembly_id: "g1", assembly_name: "Underlayment", measurement: 9000, unit: "SF" }],
    labor: [], contingency: 150, fees: 0, rates: { version: 2 }, totals: {}, preset: "usg-n12-1/8",
  },
  "Seal (+Jnts)": {
    layout: "seal", kind: "option", profile: "seal@1",
    takeoff: [], labor: [], contingency: 0, fees: 0, rates: { version: 1 }, totals: { total: 0 },
  },
};
const SNAPSHOT = { labor_rate: 33, lodging: 70, per_diem: 45, fees: 0, sales_tax: 0.09475,
                   source: "markups@2026-10-07" };
const BASE = LIFTED.NEWEST.v2_travel_block_far_job.polish_estimate;       // a real, fully populated model
const withExtras = (extra) => Object.assign(clone(BASE), clone(extra));
const EVERYTHING = { work_type: "combo", tabs: TABS, rates: SNAPSHOT, profile: "polish@1", a_null: null };
const SYNTHETIC = {
  synthetic_work_type: withExtras({ work_type: "combo" }),
  synthetic_tabs: withExtras({ tabs: TABS }),
  synthetic_rates_snapshot: withExtras({ rates: SNAPSHOT }),
  synthetic_profile_stamp: withExtras({ profile: "polish@1" }),
  // a falsy value is still a value somebody saved
  synthetic_falsy_unknowns: withExtras({ a_null: null, a_false: false, a_zero: 0, an_empty_string: "",
                                         an_empty_list: [], an_empty_object: {} }),
  synthetic_all_together: withExtras(EVERYTHING),
  // no version: read as a partial v2, which must carry them too
  synthetic_unversioned_partial: { conditions: { taxable: false }, tabs: clone(TABS), work_type: "gyp" },
};

// A model stating EVERY key migrateModel's v2 branch normalises, so the keys it comes back with ARE
// the known ones, worked out here rather than typed a second time.
const MAXIMAL = {
  version: 2,
  takeoff: [{ assembly_id: "a1", assembly_name: "A", measurement: 100, unit: "SF" }],
  labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: 33 }],
  conditions: { local: true }, contingency: 100, fees: 25, totals: { total: 1 },
  no_travel_labor: true, conditions_shown: { dye: false }, cond_cov: { joint_filler: 3000 },
  travel: { lodging: { enabled: true, qty: 3, rate: 90 } },
  distance: { miles: 12, source: "typed", key: "" }, fees_default: 25,
};
const KNOWN = Object.keys(B.migrateModel(clone(MAXIMAL))).sort();

// ── 1. the round-trip laws, over every fixture ────────────────────────────────────────────────
function lawsFor(model) {
  const v1 = !model.version && model.areas instanceof Array;
  const input = clone(model);
  const once = B.migrateModel(input);
  const again = B.migrateModel(B.migrateModel(clone(model)));
  const plain = B.migrateModel(clone(model));
  const unknown = Object.keys(model).filter((k) => KNOWN.indexOf(k) < 0);
  return {
    kind: v1 ? "v1" : "v2",
    outKeys: Object.keys(once).sort(),
    // every key that went in came back
    missing: Object.keys(model).filter((k) => !has(once, k)),
    unknown: unknown,
    // ...and the ones migrateModel does not know came back equal, not just present
    unknownChanged: unknown.filter((k) => has(once, k) && !G.same(once[k], model[k])),
    tabsIdentical: has(model, "tabs") ? JSON.stringify(once.tabs) === JSON.stringify(model.tabs) : null,
    idempotent: G.same(plain, again),
    idempotentDiff: where(plain, again),
    // reading a saved model never edits it
    inputUntouched: G.same(input, model),
  };
}

function fixturesSection() {
  return {
    saved: fromPairs(Object.keys(SAVED), (n) => lawsFor(SAVED[n].polish_estimate)),
    synthetic: fromPairs(Object.keys(SYNTHETIC), (n) => lawsFor(SYNTHETIC[n])),
  };
}

function hostileSection() {
  // JSON.parse makes `__proto__` an OWN key, which is exactly what a hostile draft looks like.
  const text = '{"version":2,"takeoff":[],"labor":[],"conditions":{},"__proto__":{"polluted":true},' +
    '"constructor":{"x":1},"prototype":{"y":2},"fine":{"kept":1}}';
  const got = B.migrateModel(JSON.parse(text));
  return {
    ownProto: has(got, "__proto__"), ownConstructor: has(got, "constructor"),
    ownPrototype: has(got, "prototype"),
    protoIsObjectPrototype: Object.getPrototypeOf(got) === Object.prototype,
    leaked: ({}).polluted === undefined ? null : ({}).polluted,
    fine: has(got, "fine") ? got.fine : null,
  };
}

// ── 2. patchModel ─────────────────────────────────────────────────────────────────────────────
function patchSection() {
  if (typeof B.patchModel !== "function") return { missing: true };
  const existing = withExtras(EVERYTHING);
  existing.conditions = Object.assign({}, existing.conditions, { taxable: true, remodel_tax: false, dye: true });
  existing.conditions_shown = { joint_filler: false };
  const patch = { conditions: { taxable: false, remodel_tax: true }, conditions_shown: { dye: false } };
  const migrated = B.migrateModel(clone(existing));
  const without = (m) => { const c = clone(m); delete c.conditions; delete c.conditions_shown; return c; };

  const got = B.patchModel(clone(existing), clone(patch));
  const smuggle = { conditions: {}, takeoff: [{ assembly_id: "x", measurement: 1, unit: "SF" }],
    labor: [{ id: "evil" }], tabs: { evil: 1 }, version: 7, fees: 999, work_type: "gyp", totals: { total: 1 },
    conditions_shown: "not an object" };
  const smuggled = B.patchModel(clone(existing), clone(smuggle));

  let pureThrew = null;
  try { B.patchModel(deepFreeze(clone(existing)), deepFreeze(clone(patch))); } catch (e) { pureThrew = String(e); }

  const MINT = {
    undef: undefined, nul: null, emptyObject: {}, v1: clone(SAVED.v1_areas.polish_estimate),
    partialConditions: { conditions: { taxable: false } },
    partialTakeoff: { takeoff: [{ assembly_id: "a1", assembly_name: "A", measurement: 5, unit: "SF" }],
                      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: 33 }] },
    v2NoLabor: { version: 2, takeoff: [{ assembly_id: "a1", assembly_name: "A", measurement: 5, unit: "SF" }],
                 conditions: {} },
    v2WithLabor: { version: 2, takeoff: [], labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: 33 }] },
  };
  return {
    conditions: got.conditions,
    expectedConditions: Object.assign({}, migrated.conditions, patch.conditions),
    shown: got.conditions_shown,
    // everything the patch does not own is exactly what migrateModel gave it
    restDiff: where(without(migrated), without(got)),
    tabsIdentical: JSON.stringify(got.tabs) === JSON.stringify(existing.tabs),
    extrasKept: Object.keys(EVERYTHING).filter((k) => !has(got, k)).length === 0,
    // a patch that tries to state what the intake does not own
    smuggledRestDiff: where(without(migrated), without(smuggled)),
    smuggledConditions: smuggled.conditions,
    smuggledShown: smuggled.conditions_shown,
    pureThrew: pureThrew,
    idempotent: G.same(B.patchModel(B.patchModel(clone(existing), clone(patch)), clone(patch)),
                       B.patchModel(clone(existing), clone(patch))),
    inputsUntouched: (function () {
      const e = clone(existing), p = clone(patch);
      B.patchModel(e, p);
      return G.same(e, existing) && G.same(p, patch);
    })(),
    mint: fromPairs(Object.keys(MINT), (n) => {
      // `undefined` and null are saved states too (nothing under `polish_estimate` yet)
      const g = B.patchModel(MINT[n] == null ? MINT[n] : clone(MINT[n]), clone(patch));
      return { version: g.version, hasLabor: has(g, "labor"), unstated: B.laborUnstated(MINT[n]),
               taxable: g.conditions.taxable, shown: g.conditions_shown, hasTakeoff: g.takeoff instanceof Array };
    }),
  };
}

// ── 3. buildSavePatch, as a pure function ─────────────────────────────────────────────────────
function savePatchSection() {
  if (typeof B.buildSavePatch !== "function") return { missing: true };
  const bidOf = (m) => B.markupChain({ material: 10000, labor: B.laborTotal(m.labor, m.conditions), travel: 0,
    contingency: m.contingency, fees: m.fees, conditions: m.conditions, sf: B.takeoffSf(m.takeoff),
    remodel_rate: null });
  const model = withExtras(EVERYTHING);
  model.conditions = Object.assign({}, model.conditions, { taxable: false, dye: true, joint_filler: true, local: true });
  const bid = bidOf(model);
  const state = { cell_values: { "Epoxy!E20": 5000, "Polish!B4": "stale" }, polish_sf: 1, other: "kept" };
  const library = {
    dye: { unit_price: 0.14, coverage: 2, waste_pct: 0, roundup: false, buy_qty: 1 },
    joint_filler: { unit_price: 500, coverage: 3000, waste_pct: 0, roundup: true, buy_qty: 1 },
  };
  const ctx = { bid: bid, library: library };

  let frozenThrew = null, patch = null;
  try {
    patch = B.buildSavePatch(deepFreeze(clone(model)), deepFreeze(clone(state)), deepFreeze(clone(ctx)));
  } catch (e) { frozenThrew = String(e); }
  const throwsOn = (fn) => { try { fn(); return false; } catch (e) { return true; } };

  const plainModel = clone(model), plainState = clone(state), plainCtx = clone(ctx);
  const live = B.buildSavePatch(plainModel, plainState, plainCtx);
  const off = clone(model);
  off.takeoff = [{ assembly_id: "a1", assembly_name: "A", measurement: 12500, unit: "SF", enabled: false }];
  const offBid = bidOf(off);
  const offPatch = B.buildSavePatch(off, state, { bid: offBid });
  const noLibrary = B.buildSavePatch(model, state, { bid: bid });

  return {
    frozenThrew: frozenThrew,
    keys: patch ? Object.keys(patch).sort() : null,
    modelExpected: patch ? where(Object.assign(clone(model), { totals: bid }), patch.polish_estimate) : "no patch",
    totalsAreTheBid: patch ? G.same(patch.polish_estimate.totals, bid) : false,
    // the model it was handed is not the object it saved, and was not edited to stamp `totals`
    modelCopied: live.polish_estimate !== plainModel,
    modelUntouched: G.same(plainModel, model) && G.same(plainState, state) && G.same(plainCtx, ctx),
    tabsIdentical: patch ? JSON.stringify(patch.polish_estimate.tabs) === JSON.stringify(model.tabs) : false,
    cells: patch ? {
      foreignKept: nn(patch.cell_values["Epoxy!E20"]), taxable: nn(patch.cell_values["Epoxy!B6"]),
      localOverwritesStale: nn(patch.cell_values["Polish!B4"]), dyeRate: nn(patch.cell_values["Polish!C25"]),
      dyeRateSecondCoat: nn(patch.cell_values["Polish!C26"]), jfRate: nn(patch.cell_values["Polish!C29"]),
      jfQty: nn(patch.cell_values["Polish!B29"]),
    } : null,
    noLibraryWritesNoLibraryCells: !has(noLibrary.cell_values, "Polish!C25") && !has(noLibrary.cell_values, "Polish!C29"),
    polishSf: patch ? { saved: patch.polish_sf, priced: bid.sf } : null,
    polish2Sf: patch ? patch.polish_2_sf : null,
    floor: { pricedSf: offBid.sf, saved: offPatch.polish_sf, computedSf: offPatch.computed_bid.polish_sf },
    computed: patch ? patch.computed_bid : null,
    expectedComputed: { lump_sum: bid.total, price_per_sf: bid.per_sf, polish_sf: bid.sf,
      full_bid: { total_base_bid: bid.total, sales_tax: bid.sales_tax, remodel_tax: bid.remodel_tax } },
    throwsWithoutBid: throwsOn(() => B.buildSavePatch(model, state, {})),
    throwsWithoutCtx: throwsOn(() => B.buildSavePatch(model, state)),
    throwsWithoutModel: throwsOn(() => B.buildSavePatch(null, state, ctx)),
  };
}

// ── the two pages' preludes ───────────────────────────────────────────────────────────────────
/** A page harness's own prelude (DOM stub, fake clock, TW stand-in, `build`, `blob`) as a module,
 *  cut off where its scenarios begin, handing back the names a scenario here needs. */
function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in model-safety-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}
let ESTIMATE = null, INTAKE = null;
const est = () => ESTIMATE || (ESTIMATE = loadPrelude("polish-estimate-harness.js",
  ["build", "blob", "typeInto", "clickEl", "need", "switchNode", "MODEL", "ITEMS"]));
const ink = () => INTAKE || (INTAKE = loadPrelude("polish-intake-harness.js", ["build", "blob", "clickSwitch"]));

const CELLS = ["Epoxy!B6", "Epoxy!B4", "Polish!B4", "Polish!C25", "Polish!C29", "Polish!B29", "Epoxy!D6"];

// ── 4. the estimate page, saved two ways from identical drafts ────────────────────────────────
async function estimateSection() {
  const E = est();
  const TOTAL_SF = 17500;                     // the SF rows of the page's own MODEL: 12,500 + 5,000
  const withModel = (extra, mutate) => {
    const m = Object.assign(clone(E.MODEL), clone(extra || {}));
    if (mutate) mutate(m);
    return m;
  };
  const typeMeasure = (b) => E.typeInto(b, '[data-tk="0"][data-k="measurement"]', "12000");
  const SCENARIOS_ESTIMATE = {
    // a plain takeoff edit
    typed: { model: withModel(), sf: TOTAL_SF, drive: typeMeasure },
    // Sales tax flipped on the Review step, then the tab closed inside the debounce window
    condition: { model: withModel({ conditions: { local: true, prevailing_wage: false, taxable: true,
      remodel_tax: false, bond: false } }), sf: TOTAL_SF,
      drive: (b) => { b.api.go(2); b.doc.fire("click", { target: E.switchNode("taxable") }); } },
    // the only SF row switched off: the measured floor stays on file
    onlyRowOff: { model: withModel({}, (m) => { m.takeoff = [{ assembly_id: "a1",
      assembly_name: "Polish 800 Grit", measurement: 12500, unit: "SF" }]; }), sf: 12500,
      drive: (b) => { b.api.go(0); E.clickEl(b, E.need(b, '[data-on-tk="0"]')); } },
    // Dye and Joint Filler on, with the library's reserved rows present
    library: { model: withModel({ conditions: { local: true, prevailing_wage: false, taxable: true,
      remodel_tax: false, bond: false, dye: true, joint_filler: true, remove_existing_jf: false } }),
      sf: TOTAL_SF, items: E.ITEMS.concat(LIFTED.RESERVED_ITEMS), drive: typeMeasure },
    // a model that carries what migrateModel does not know
    withTabs: { model: withModel(EVERYTHING), sf: TOTAL_SF, drive: typeMeasure },
  };
  const pick = (s) => ({
    polish_sf: s.polish_sf, polish_2_sf: s.polish_2_sf, lump: s.computed_bid.lump_sum,
    computedSf: s.computed_bid.polish_sf,
    cells: s.cell_values ? Object.fromEntries(CELLS.filter((c) => has(s.cell_values, c)).map((c) => [c, s.cell_values[c]])) : null,
    modelKeys: Object.keys(s.polish_estimate).sort(),
    tabs: text(s.polish_estimate.tabs),
    taxable: s.polish_estimate.conditions.taxable,
    totalsTotal: s.polish_estimate.totals && s.polish_estimate.totals.total,
  });
  /** `way`: "autosave" (the timer fires), "pagehide" (the tab closes inside the debounce window), or
   *  "both" (the timer fires, THEN the tab closes). The page never clears its timer handle once the
   *  timer has fired, so its pagehide handler runs after every edit, not only inside the window. */
  async function run(sc, way) {
    const b = E.build({ blob: E.blob({ polish_estimate: clone(sc.model), polish_sf: sc.sf }),
                        items: sc.items });
    await b.api.init();
    const before = b.rec.saves.length;
    sc.drive(b);
    const armed = b.clock.armed();
    let first = null;
    if (way === "pagehide") {
      b.win.fire("pagehide");
    } else {
      b.clock.fire();
      first = last(b.rec.saves.slice(before)) || null;
      if (way === "both") b.win.fire("pagehide");
    }
    return { saved: last(b.rec.saves.slice(before)) || null, first: first, count: b.rec.saves.length - before,
             flushed: b.rec.flushed, armed: armed, armedAfter: b.clock.armed() };
  }
  const names = Object.keys(SCENARIOS_ESTIMATE);
  const results = [];
  for (const name of names) {
    const sc = SCENARIOS_ESTIMATE[name];
    const a = await run(sc, "autosave");
    const p = await run(sc, "pagehide");
    const both = await run(sc, "both");
    results.push([name, {
      armed: a.armed, savesAutosave: a.count, savesPagehide: p.count, flushedByPagehide: p.flushed,
      equal: !!(a.saved && p.saved) && G.same(a.saved, p.saved),
      diff: a.saved && p.saved ? where(a.saved, p.saved) : "a path saved nothing",
      // the tab closing AFTER the autosave must leave the draft as the autosave wrote it
      settled: !!(both.first && both.saved) && G.same(both.first, both.saved),
      settledDiff: both.first && both.saved ? where(both.first, both.saved) : "nothing was saved",
      autosave: a.saved ? pick(a.saved) : null, pagehide: p.saved ? pick(p.saved) : null,
      sentTabs: text(sc.model.tabs),
      expectedSf: sc.sf,
    }]);
  }
  return Object.fromEntries(results);
}

// ── 5. the intake page's save, alone and after an estimate save ───────────────────────────────
async function intakeSection() {
  const E = est(), I = ink();
  const intakeModel = (extra) => Object.assign({ version: 2,
    takeoff: [{ assembly_id: "asm-sp", assembly_name: "Salt & Pepper polish", measurement: 12500, unit: "SF" }],
    labor: [{ id: "polishing", label: "Polishing", guys: 4, days: 3, rate: 32.2 }],
    conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } }, clone(extra || {}));

  // (a) the intake alone, over a model that carries what it does not know
  const a = I.build({ blob: I.blob({ polish_estimate: intakeModel(EVERYTHING) }) });
  await a.api.boot();
  I.clickSwitch(a, "taxable");
  a.clock.fire();
  const alone = last(a.rec.saves).polish_estimate;

  // (b) the cross-page law: an estimate save, then an intake save, over one draft
  const start = Object.assign(clone(E.MODEL), clone(EVERYTHING));
  const e = E.build({ blob: E.blob({ polish_estimate: clone(start), polish_sf: 17500 }) });
  await e.api.init();
  E.typeInto(e, '[data-tk="0"][data-k="measurement"]', "12000");
  e.clock.fire();
  const afterEstimate = clone(e.store.blob);
  const i = I.build({ blob: clone(afterEstimate) });
  await i.api.boot();
  I.clickSwitch(i, "prevailing_wage");
  i.clock.fire();
  const afterIntake = last(i.rec.saves);
  const tabsOf = (m) => text((m || {}).tabs);
  return {
    alone: {
      tabsIdentical: tabsOf(alone) === JSON.stringify(TABS),
      extrasMissing: Object.keys(EVERYTHING).filter((k) => !has(alone, k)),
      taxableFlipped: alone.conditions.taxable === false,
      takeoffKept: alone.takeoff.length === 1 && alone.takeoff[0].measurement === 12500,
      version: alone.version,
    },
    cross: {
      tabsBefore: JSON.stringify(TABS),
      tabsAfterEstimate: tabsOf(afterEstimate.polish_estimate),
      tabsAfterIntake: tabsOf(afterIntake.polish_estimate),
      extrasMissingAfterEstimate: Object.keys(EVERYTHING).filter((k) => !has(afterEstimate.polish_estimate, k)),
      extrasMissingAfterIntake: Object.keys(EVERYTHING).filter((k) => !has(afterIntake.polish_estimate, k)),
      measurementAfterEstimate: afterEstimate.polish_estimate.takeoff[0].measurement,
      measurementAfterIntake: afterIntake.polish_estimate.takeoff[0].measurement,
      prevailingWageAfterIntake: afterIntake.polish_estimate.conditions.prevailing_wage,
      saves: { estimate: e.rec.saves.length, intake: i.rec.saves.length },
    },
  };
}

(async function () {
  // each section on its own, so one that throws (or whose function is not there yet) reports it
  const attempt = async (fn) => {
    try { return await fn(); } catch (e) { return { error: String((e && e.stack) || e) }; }
  };
  const sections = [["fixtures", fixturesSection], ["hostile", hostileSection], ["patch", patchSection],
                    ["savePatch", savePatchSection], ["estimate", estimateSection], ["intake", intakeSection]];
  const done = [];
  for (const [name, fn] of sections) done.push([name, await attempt(fn)]);
  console.log(JSON.stringify(Object.assign({
    names: { saved: Object.keys(SAVED), synthetic: Object.keys(SYNTHETIC) },
    known: { keys: KNOWN, maximalKeys: Object.keys(MAXIMAL).sort(),
             exported: B.MODEL_KEYS ? Array.from(B.MODEL_KEYS).sort() : null },
  }, Object.fromEntries(done))));
})().catch((err) => { console.error((err && err.stack) || err); process.exit(1); });
