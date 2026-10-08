"use strict";
/* THE ONE VOCABULARY, EXECUTED. Runs the real frontend/js/work-types.js (and the real bid-model.js that
 * derives from it) and reports what they did, plus the copies the table has to stay equal to, lifted out
 * of the page files and evaluated.
 *
 * WHY EXECUTED. Every claim in test_work_types.py is about behaviour or about two sources agreeing, and
 * neither is visible to a grep:
 *
 *   * "appliesTo throws on a job type" is a claim about a call, and "a layout named like an object's
 *     machinery is not a tab" is a claim about a lookup. They are run, with the awkward inputs.
 *   * "a combo job reads the Epoxy AND the Polish defaults" is a claim about what seedDefaultTakeoff,
 *     seedLibraryLabor and travelAppliesToBid DO with a combo job, so they are called with one.
 *   * "the live intake's CONDITIONS equal the table's live rows" compares two data structures, and the
 *     live one lives inside a script that needs a DOM: its declaration is lifted by name and evaluated,
 *     so the comparison reads the intake's real literal and not a retyped copy of it.
 *
 * Nothing here is a copy of the logic under test. The comparisons are the test's.
 *
 * Usage: node work-types-harness.js <frontend-dir>   ->   one line of JSON
 *
 * <frontend-dir> may hold only some of the files. Whatever it lacks is read from the real frontend, which
 * is how the tests break ONE file in a scratch copy and watch these results go red. (A scratch copy that
 * breaks work-types.js has to carry bid-model.js beside it, which requires work-types.js from its own
 * folder: tests/_golden_support.py's `also` does that.)
 */
const fs = require("fs");
const path = require("path");
const L = require("./_lib.js");

const REAL = path.resolve(__dirname, "..", "..", "..", "frontend");
const GIVEN = path.resolve(process.argv[2] || REAL);
const pick = (rel) => (fs.existsSync(path.join(GIVEN, rel)) ? path.join(GIVEN, rel) : path.join(REAL, rel));
const src = (rel) => L.read(pick(rel));

const T = require(pick("js/work-types.js"));
const B = require(pick("js/bid-model.js"));
const INDEX = src("js/index.js");
const REVIEW = src("js/estimate-review.js");

const clone = (v) => JSON.parse(JSON.stringify(v));
/** What a call did: its answer, or the message it threw. */
const tried = (f) => { try { return { ok: f() }; } catch (e) { return { threw: String(e && e.message) }; } };
const evaluate = (code, name) => new Function(code + "\nreturn " + name + ";")();
/** {key: fn(key)} for each key, built without a single `obj[key] = value`: CodeQL's property-injection
 *  query flags those, and a key here is the vocabulary's own or a case name. */
const byKey = (keys, fn) => Object.fromEntries(keys.map((k) => [String(k), fn(k)]));

const out = {};

// ── 1. the data, as the module holds it ──────────────────────────────────────────────────────────
out.data = clone({ SURFACES: T.SURFACES, FIELDS: T.FIELDS, TABS: T.TABS, JOB_TYPES: T.JOB_TYPES,
                   CONDITIONS: T.CONDITIONS });
out.keys = { jobTypes: T.jobTypeKeys(), tabs: T.tabKeys() };
// ── 2. tabsFor and appliesTo ─────────────────────────────────────────────────────────────────────
out.tabsFor = byKey(T.jobTypeKeys(), (k) => T.tabsFor(k));
const refused = ["seal", "leveling", "nonsense", "", " polish", "Polish", undefined, null, 5, {}, [], ["polish"],
                 "constructor", "__proto__", "toString", "hasOwnProperty"];
out.tabsForRefused = refused.map((v) => ({ asked: String(typeof v === "object" ? JSON.stringify(v) : v), r: tried(() => T.tabsFor(v)) }));
{
  const a = T.tabsFor("combo"); a.push("gyp"); a.length = 0;
  out.tabsForIsACopy = T.tabsFor("combo");
}

const LISTS = {
  undefined: undefined, null: null, empty: [], polish: ["polish"], epoxy: ["epoxy"], gyp: ["gyp"],
  sealPolish: ["seal", "polish"], all: ["polish", "seal", "epoxy", "leveling", "gyp"], aString: "polish",
  anObject: { 0: "polish", length: 1 }, aNumber: 3, comboOnly: ["combo"],
};
out.appliesTo = byKey(Object.keys(LISTS), (name) => byKey(T.tabKeys(), (tab) => T.appliesTo(LISTS[name], tab)));
const badLayouts = ["combo", "epoxy ", "Polish", "", undefined, null, 5, {}, ["polish"], "constructor", "__proto__",
                    "toString", "hasOwnProperty", "valueOf"];
out.appliesToRefused = [];
badLayouts.forEach((layout) => {
  ["empty", "polish", "undefined"].forEach((list) => {
    out.appliesToRefused.push({ layout: String(typeof layout === "object" ? JSON.stringify(layout) : layout),
                                list, r: tried(() => T.appliesTo(LISTS[list], layout)) });
  });
});

// ── 3. the readers ───────────────────────────────────────────────────────────────────────────────
out.views = { jobTypes: {}, module: {} };
out.views.jobTypes = byKey(T.jobTypeKeys(), (jt) => clone({
  tabs: T.tabsFor(jt),
  fields: T.fieldsFor(jt).map((f) => f.name),
  scopes: T.scopesFor(jt),
  conditions: T.conditionsFor(jt).map((c) => c.key),
  asked: byKey(T.SURFACES, (s) => T.conditionsFor(jt, s).map((c) => c.key)),
  why: byKey(T.SURFACES, (s) => T.conditionsFor(jt, s).map((c) => c.why)),
  rows: T.SURFACES.map((s) => T.conditionsFor(jt, s)),
  cells: T.cellsFor(jt),
}));
out.views.module = clone({
  copyableCells: T.copyableCells(), modelDefaults: T.modelDefaults(), reservedItems: T.reservedItems(),
  itemIds: Object.fromEntries(T.CONDITIONS.map((c) => [c.key, T.itemIdOf(c.key)])),
});
out.refusals = {
  conditionsForJob: tried(() => T.conditionsFor("seal")),
  conditionsForSurface: tried(() => T.conditionsFor("polish", "v3")),
  conditionsForSurfaceProto: tried(() => T.conditionsFor("polish", "constructor")),
  cellsFor: tried(() => T.cellsFor("combo ")),
  fieldsFor: tried(() => T.fieldsFor(undefined)),
  scopesFor: tried(() => T.scopesFor("tab")),
  tab: tried(() => T.tab("combo")),
  jobType: tried(() => T.jobType("seal")),
  condition: tried(() => T.condition("hard_bid")),
  conditionProto: tried(() => T.condition("constructor")),
  itemIdOf: tried(() => T.itemIdOf("nonsense")),
};
out.lookups = {
  isJobType: ["polish", "combo", "seal", "constructor", undefined].map((v) => T.isJobType(v)),
  isTab: ["polish", "combo", "seal", "constructor", undefined].map((v) => T.isTab(v)),
  tabOfSheet: Object.fromEntries(["Polish", "Epoxy", "Epoxy blank", "Seal", "Seal (+Jnts)", "Leveling", 'Gyp (USG 1-8")',
    "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)", "Takeoff", "Stnd Alts", "constructor",
    "__proto__", ""].map((s) => [s, T.tabOfSheet(s)])),
};
// The readers hand out copies: a caller that edits what it got must not edit the next caller's.
{
  const cells = T.cellsFor("polish"); cells[0].cells.push("Edited!A1"); cells[0].on = "Edited";
  const rows = T.conditionsFor("polish", "live"); rows[0].label = "Edited"; rows.length = 0;
  const defaults = T.modelDefaults(); defaults.local = "Edited";
  const reserved = T.reservedItems(); reserved.dye = "Edited";
  out.copies = clone({
    cells: T.cellsFor("polish")[0], row: T.conditionsFor("polish", "live")[0].label, rows: T.conditionsFor("polish", "live").length,
    local: T.modelDefaults().local, reserved: T.reservedItems().dye,
  });
}

// ── 4. what bid-model.js derives from it ─────────────────────────────────────────────────────────
const wt = ["polish", "epoxy", "combo", "gyp", undefined];
const ROWS = {
  none: {}, empty: { default_work_types: [] }, polish: { default_work_types: ["polish"] },
  epoxy: { default_work_types: ["epoxy"] }, seal: { default_work_types: ["seal"] }, gyp: { default_work_types: ["gyp"] },
  epoxyPolish: { default_work_types: ["epoxy", "polish"] }, aString: { default_work_types: "polish" },
  sealLeveling: { default_work_types: ["seal", "leveling"] },
};
out.bid = {
  conditionCells: clone(B.CONDITION_CELLS), carried: clone(B.CARRIED_CELLS),
  freshConditions: clone(B.freshModel().conditions),
  applies: byKey(Object.keys(ROWS), (name) => byKey(wt, (j) => B.workTypeApplies(ROWS[name], j))),
  appliesRefused: byKey(["seal", "leveling", "nonsense", "Polish", "constructor"],
                        (j) => tried(() => B.workTypeApplies(ROWS.polish, j))),
};

// A combo job reads the Epoxy list AND the Polish list. The defaults a new bid opens with, per job type.
{
  const blank = () => [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }];
  const ASMS = [
    { id: "p", name: "Polish only", unit: "SF", favorite: true, default_work_types: ["polish"] },
    { id: "e", name: "Epoxy only", unit: "SF", favorite: true, default_work_types: ["epoxy"] },
    { id: "g", name: "Gyp only", unit: "SF", favorite: true, default_work_types: ["gyp"] },
    { id: "s", name: "Seal only", unit: "SF", favorite: true, default_work_types: ["seal"] },
    { id: "a", name: "Every tab", unit: "SF", favorite: true },
  ];
  const ITEMS = [
    { id: "ip", name: "Polish item", favorite: true, default_work_types: ["polish"] },
    { id: "ie", name: "Epoxy item", favorite: true, default_work_types: ["epoxy"] },
    { id: "dye", name: "Dye", favorite: true },
  ];
  out.bid.takeoff = byKey(wt, (j) => {
    const args = [blank(), ASMS, ITEMS, ["dye"], 8000, ""];
    if (j !== undefined) args.push(j);
    return B.seedDefaultTakeoff(...args).map((r) => r.assembly_id || r.item_id || "(blank)");
  });
  out.bid.takeoffRefused = tried(() => B.seedDefaultTakeoff(blank(), ASMS, ITEMS, ["dye"], 8000, "", "seal"));

  const LABOR = [
    { id: "polishing", label: "Polishing", guys: 3, days: "", rate: 33 },
    { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: true },
  ];
  const ROWS_LABOR = [
    { id: "lp", name: "Polish saw", rate: 41, unit: "days", favorite: true, default_work_types: ["polish"] },
    { id: "le", name: "Epoxy mixer", rate: 42, unit: "days", favorite: true, default_work_types: ["epoxy"] },
    { id: "lg", name: "Gyp pump", rate: 43, unit: "days", favorite: true, default_work_types: ["gyp"] },
    { id: "la", name: "Everyone", rate: 44, unit: "days", favorite: true },
    { id: "travel", rate: 33, favorite: true, default_work_types: ["epoxy"] },
  ];
  out.bid.labor = byKey(wt, (j) => B.seedLibraryLabor(clone(LABOR), clone(ROWS_LABOR), 50, j).map((r) => r.id));
  out.bid.travel = byKey(wt, (j) => ({
    epoxyOnly: B.travelAppliesToBid({ favorite: true, default_work_types: ["epoxy"] }, j),
    declined: B.travelDeclined([{ id: "travel", favorite: true, default_work_types: ["epoxy"] }], j),
  }));
}

// What a save writes into the workbook cells, and what it leaves alone.
{
  const ALL_OFF = Object.fromEntries(Object.keys(B.freshModel().conditions).map((k) => [k, false]));
  const ALL_ON = Object.fromEntries(Object.keys(B.freshModel().conditions).map((k) => [k, true]));
  out.cellWrites = {
    allOff: B.conditionCellWrites(ALL_OFF, {}, undefined),
    allOn: B.conditionCellWrites(ALL_ON, {}, undefined),
    renoYes: B.conditionCellWrites(ALL_OFF, { "Epoxy!B10": "Reno" }, undefined),
    renoSpaced: B.conditionCellWrites(ALL_OFF, { "Epoxy!B10": "  reno " }, undefined),
    renoNew: B.conditionCellWrites(ALL_ON, { "Epoxy!B10": "New", "Polish!B10": "Reno" }, undefined),
    renoOnlyOnPolish: B.conditionCellWrites(ALL_OFF, { "Polish!B10": "Reno" }, undefined),
    renoNumber: B.conditionCellWrites(ALL_OFF, { "Epoxy!B10": 0 }, undefined),
    renoAskedByTheModelIsIgnored: B.conditionCellWrites(Object.assign({}, ALL_OFF, { reno: true }), {}, undefined),
    keepsOtherCells: B.conditionCellWrites(ALL_ON, { "Epoxy!B1": "Nearman", "Epoxy!D41": "BULK Discount ON" }, undefined),
  };
  out.fromCells = {
    reno: B.conditionsFromCells({}, { "Epoxy!B10": "Reno" }),
    taxableOnly: B.conditionsFromCells({}, { "Leveling!B6": "No", 'Gyp (FR)!B8': "No" }),
    taxable: B.conditionsFromCells({ taxable: true }, { "Epoxy!B6": "No", "Leveling!B6": "Yes" }),
    // PHASE 7b: a condition with several cells is answered by the first cell that holds an answer.
    localSecondOnly: B.conditionsFromCells({ local: true }, { "Polish!B4": "No" }),
    localFirstWins: B.conditionsFromCells({ local: false }, { "Epoxy!B4": "Yes", "Polish!B4": "No" }),
  };
}

// ── 5. the copies the table has to stay equal to, lifted and evaluated ───────────────────────────
// The live intake (js/index.js) keeps its own literals until Phase 9: its job conditions, which quantity
// fields each work type shows, and the names of the two systems' fields.
out.live = {
  conditions: clone(evaluate(L.grabConst(INDEX, "CONDITIONS", { indent: "  " }), "CONDITIONS")),
  scopeByWorkType: clone(evaluate(L.grabConst(INDEX, "SCOPE_BY_WORK_TYPE", { indent: "  " }), "SCOPE_BY_WORK_TYPE")),
  systemFieldNames: byKey([1, 2], (k) => clone(L.lift(INDEX, "systemFieldNames", {}, { indent: "  " })(k))),
};

// The estimate screen's own role sets, sheet-to-layout map and area cells.
{
  const consts = ["GYP_BASE", "GYP_SHEETS", "SEAL_SHEETS", "BASE_ROLE", "MARKUP_LAYOUT_OF", "AREA_SF_CELLS",
                  "GYP_SF_CELLS", "PRICED_ROLES", "OPTION_ONLY_ROLES", "COMBINED_BASE_ROLES"]
    .map((n) => L.grabConst(REVIEW, n)).join("\n");
  const forEaches = [
    L.grab(REVIEW, /^GYP_SHEETS\.forEach\(\(s\) => \{ BASE_ROLE\[s\] = "gyp"; \}\);.*$/m, "the gyp base roles"),
    L.grab(REVIEW, /^SEAL_SHEETS\.forEach\(\(s\) => \{ BASE_ROLE\[s\] = "seal"; \}\);.*$/m, "the seal base roles"),
    L.grab(REVIEW, /^GYP_SHEETS\.forEach\(\(s\) => \{ MARKUP_LAYOUT_OF\[s\] = "gyp"; \}\);$/m, "the gyp markup layouts"),
  ].join("\n");
  const run = new Function(consts + "\n" + forEaches + "\n" + "return { BASE_ROLE, MARKUP_LAYOUT_OF, AREA_SF_CELLS, " +
    "GYP_SF_CELLS, GYP_SHEETS, SEAL_SHEETS, PRICED_ROLES: [...PRICED_ROLES], OPTION_ONLY_ROLES: [...OPTION_ONLY_ROLES], " +
    "COMBINED_BASE_ROLES: [...COMBINED_BASE_ROLES] };");
  out.review = clone(run());
}

// ── 6. the table is frozen all the way down ─────────────────────────────────────────────────────
// LAST, on purpose: if a break lets one of these edits succeed, the table is changed for the rest of
// this run, and everything above has already been read. A reader that edits what it was handed fails
// here (this file is strict) instead of changing the vocabulary for every other page.
out.frozen = {
  jobType: tried(() => { T.JOB_TYPES[0].label = "x"; }),
  tabCells: tried(() => { T.TABS[0].sheets.push("x"); }),
  conditionCells: tried(() => { T.CONDITIONS[2].cells.push("x"); }),
  askedOn: tried(() => { T.CONDITIONS[0].asked_on.live = 9; }),
  list: tried(() => { T.CONDITIONS.push({}); }),
};

process.stdout.write(JSON.stringify(out) + "\n");
