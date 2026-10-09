"use strict";
/* PHASE 7b, EXECUTED: where a job condition's answer is written and read back, on a draft that is split per
 * sheet and on one that is not, and what a v2 test copy of a split project does with it.
 *
 * Runs the REAL frontend/js/work-types.js, bid-model.js and polish-sandbox.js and reports what they did.
 * Nothing here is a copy of the logic under test; every comparison is the test's (test_v2_condition_cells.py).
 *
 * WHAT IT ANSWERS
 *   rule      the table's own answer, writeCellsFor(condition, job type, split, own), for every condition and
 *             every job type, split and not; what it refuses; what it filters out of the cells a caller hands it.
 *   model     what the v2 model's saves write and its read-back reads, with and without the third and fourth
 *             arguments, from cells a split draft holds.
 *   journey   THE DEFECT, END TO END. A split spreadsheet draft whose Leveling and Gypsum (FR) sheets are
 *             tax-exempt and whose Epoxy sheet is taxable goes through the real buildCopy and then through a
 *             v2 save, built the way the pages build it. The option sheets' answers must come out as they
 *             went in. It uses only calls that exist in the tree before this phase as well, so the same
 *             harness can be pointed at that tree and shown red.
 *
 * Usage: node condition-cells-harness.js <frontend-dir>   ->   one line of JSON
 *
 * <frontend-dir> may hold only some of the files. Whatever it lacks is read from the real frontend, which is
 * how the tests break ONE file in a scratch copy and watch these results go red. (A scratch copy that breaks
 * work-types.js has to carry bid-model.js beside it: tests/_golden_support.py's `also` does that.)
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const L = require("./_lib.js");

const REAL = path.resolve(__dirname, "..", "..", "..", "frontend");
const GIVEN = path.resolve(process.argv[2] || REAL);
const pick = (rel) => (fs.existsSync(path.join(GIVEN, rel)) ? path.join(GIVEN, rel) : path.join(REAL, rel));

const T = require(pick("js/work-types.js"));
const B = require(pick("js/bid-model.js"));
const SANDBOX = L.read(pick("js/polish-sandbox.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
/** What a call did: its answer, or the message it threw. */
const tried = (f) => { try { return { ok: f() }; } catch (e) { return { threw: String(e && e.message) }; } };
/** {key: fn(key)} for each key, built without a single `obj[key] = value` (CodeQL's property-injection query
 *  flags those, and a key here is the vocabulary's own or a case name). */
const byKey = (keys, fn) => Object.fromEntries(keys.map((k) => [String(k), fn(k)]));
/** The listed cells of a map, as {cell: value-or-null}. */
const pickCells = (cv, cells) => Object.fromEntries(cells.map((c) => [c, cv && Object.prototype.hasOwnProperty.call(cv, c) ? cv[c] : null]));
/** A copy of a map without the listed keys. */
const without = (obj, keys) => Object.fromEntries(Object.entries(obj).filter(([k]) => keys.indexOf(k) < 0));

const JOBS = T.jobTypeKeys();
const KEYS = T.CONDITIONS.map((c) => c.key);
const FRESH = B.freshModel().conditions;
const conds = (over) => Object.assign({}, FRESH, over || {});

/** Every tax cell a draft can hold: the four fan-out cells, Remodel's one, and the base sheets' own. */
const TAX_CELLS = ["Epoxy!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8", "Polish!B6",
                   "Epoxy!D6", "Polish!D6", 'Gyp (USG 1-8")!D8'];

const out = {};
// The workbook sheets the vocabulary prices: every sheet it files under a tab. The completeness scan of the
// template reads exactly these.
out.sheets = T.TABS.reduce((all, t) => all.concat(t.sheets), []);

// ── 1. the table's rule ──────────────────────────────────────────────────────────────────────────
out.rule = {
  table: clone(T.CONDITIONS.map((c) => ({ key: c.key, cells: c.cells, perSheet: c.perSheet || null }))),
  have: ["isSplit", "isPerSheet", "baseSheets", "writeCellsFor"].map((n) => [n, typeof T[n]]),
  grid: byKey(KEYS, (k) => byKey(JOBS, (j) => ({
    unsplit: tried(() => T.writeCellsFor(k, j, false)),
    split: tried(() => T.writeCellsFor(k, j, true)),
  }))),
  // The cells a caller that knows better hands in: only real "Sheet!A1" addresses survive.
  own: {
    real: tried(() => T.writeCellsFor("taxable", "polish", true, ["Polish!B6", "Epoxy!B6"])),
    filtered: tried(() => T.writeCellsFor("taxable", "polish", true,
      ["Polish!B6", "bad", "__proto__", "A1", "Sheet!A1;DROP", "Sheet!A1\n", "!A1", "Sheet!", "X!AAAA1", "X!A123456",
       "Gyp (FR)!B8", 7, null, undefined, {}])),
    empty: tried(() => T.writeCellsFor("taxable", "polish", true, [])),
    // `own` is for a split draft only: an unsplit one writes its cells whatever the caller hands in
    ignoredWhenUnsplit: tried(() => T.writeCellsFor("taxable", "polish", false, ["Polish!B6"])),
    ignoredForAConditionNoSheetOwns: tried(() => T.writeCellsFor("local", "polish", true, ["Polish!B6"])),
    notAList: tried(() => T.writeCellsFor("taxable", "polish", true, "Epoxy!B6")),
    // a caller that edits the answer it was handed must not edit the next caller's
    isACopy: tried(() => {
      const a = T.writeCellsFor("taxable", "polish", false); a.push("Edited!A1"); a.length = 0;
      const b = T.writeCellsFor("taxable", "polish", true); b.push("Edited!A1");
      return { unsplit: T.writeCellsFor("taxable", "polish", false), split: T.writeCellsFor("taxable", "polish", true),
               baseSheets: (() => { const s = T.baseSheets("combo"); s.push("Edited"); return T.baseSheets("combo"); })() };
    }),
  },
  refusals: {
    noSplit: tried(() => T.writeCellsFor("taxable", "polish")),
    noJob: tried(() => T.writeCellsFor("taxable", undefined, true)),
    aTab: tried(() => T.writeCellsFor("taxable", "seal", true)),
    aLookalike: tried(() => T.writeCellsFor("taxable", "Polish", true)),
    noCondition: tried(() => T.writeCellsFor(undefined, "polish", true)),
    notACondition: tried(() => T.writeCellsFor("hard_bid", "polish", true)),
    splitOne: tried(() => T.writeCellsFor("taxable", "polish", 1)),
    splitYes: tried(() => T.writeCellsFor("taxable", "polish", "yes")),
    splitNull: tried(() => T.writeCellsFor("taxable", "polish", null)),
    baseSheetsATab: tried(() => T.baseSheets("seal")),
    baseSheetsNothing: tried(() => T.baseSheets()),
    isPerSheetNotACondition: tried(() => T.isPerSheet("hard_bid")),
  },
  isSplit: [undefined, null, {}, { tax_flags_per_sheet: true }, { tax_flags_per_sheet: false }, { tax_flags_per_sheet: 1 },
            { tax_flags_per_sheet: "" }, "abc", 5, [], { tax_flags_per_sheet: undefined }]
    .map((d) => tried(() => T.isSplit(d))),
  isPerSheet: byKey(KEYS, (k) => tried(() => T.isPerSheet(k))),
  baseSheets: byKey(JOBS, (j) => tried(() => T.baseSheets(j))),
  copyable: tried(() => T.copyableCells()),
};

// ── 2. the v2 model, on cells a split draft holds ────────────────────────────────────────────────
// A split draft after the estimate screen has run: every sheet has its OWN answer, and they differ.
const SPLIT_CELLS = {
  "Epoxy!B6": "Yes", "Epoxy!D6": "No", "Polish!B6": "Yes", "Polish!D6": "No",
  "Leveling!B6": "No", "Gyp (FR)!B8": "No", 'Gyp (USG 1-8")!B8': "Yes", 'Gyp (USG 1-8")!D8': "Yes",
};
out.model = {
  // writes: split or not, taxable on or off, remodel on or off
  writes: {
    unsplitOn: pickCells(B.conditionCellWrites(conds({ taxable: true, remodel_tax: true }), {}, undefined), TAX_CELLS),
    unsplitOff: pickCells(B.conditionCellWrites(conds({ taxable: false, remodel_tax: false }), {}, undefined, false), TAX_CELLS),
    splitOn: pickCells(B.conditionCellWrites(conds({ taxable: true, remodel_tax: true }), SPLIT_CELLS, undefined, true), TAX_CELLS),
    splitOff: pickCells(B.conditionCellWrites(conds({ taxable: false, remodel_tax: false }), SPLIT_CELLS, undefined, true), TAX_CELLS),
    // a split draft with no cells at all writes the base's own two and nothing else tax
    splitEmpty: pickCells(B.conditionCellWrites(conds({ taxable: false, remodel_tax: true }), {}, undefined, true), TAX_CELLS),
    // every other condition writes the same cells whether or not the draft is split
    otherCells: (() => {
      const un = B.conditionCellWrites(conds({ local: false, dye: true }), {}, undefined, false);
      const sp = B.conditionCellWrites(conds({ local: false, dye: true }), {}, undefined, true);
      const drop = (cv) => Object.fromEntries(Object.entries(cv).filter(([k]) => TAX_CELLS.indexOf(k) < 0));
      return { same: JSON.stringify(drop(un)) === JSON.stringify(drop(sp)), keys: Object.keys(drop(sp)).sort() };
    })(),
    // idempotent: writing twice is writing once
    twice: (() => {
      const once = B.conditionCellWrites(conds({ taxable: false }), SPLIT_CELLS, undefined, true);
      return JSON.stringify(once) === JSON.stringify(B.conditionCellWrites(conds({ taxable: false }), once, undefined, true));
    })(),
    inputsUntouched: (() => {
      const cells = clone(SPLIT_CELLS); const c = conds({ taxable: false });
      B.conditionCellWrites(c, cells, undefined, true);
      return JSON.stringify(cells) === JSON.stringify(SPLIT_CELLS) && JSON.stringify(c) === JSON.stringify(conds({ taxable: false }));
    })(),
  },
  // reads: the cell wins, from the base's own cell on a split draft
  reads: {
    // the model's answers are the opposite of the cells', so a read that never happened shows
    split: B.conditionsFromCells({ taxable: false, remodel_tax: true }, SPLIT_CELLS, true),
    splitBaseSaysNo: B.conditionsFromCells({ taxable: true, remodel_tax: true },
      { "Epoxy!B6": "Yes", "Polish!B6": "No", "Epoxy!D6": "Yes", "Polish!D6": "No" }, true),
    splitEpoxyOnly: B.conditionsFromCells({ taxable: true, remodel_tax: false }, { "Epoxy!B6": "No", "Epoxy!D6": "Yes" }, true),
    splitOptionsOnly: B.conditionsFromCells({ taxable: true }, { "Leveling!B6": "No", "Gyp (FR)!B8": "No" }, true),
    unsplit: B.conditionsFromCells({ taxable: false, remodel_tax: true }, SPLIT_CELLS),
    unsplitExplicit: B.conditionsFromCells({ taxable: false, remodel_tax: true }, SPLIT_CELLS, false),
    // first cell that holds an answer
    localSecond: B.conditionsFromCells({ local: true }, { "Polish!B4": "No" }),
    localFirst: B.conditionsFromCells({ local: false }, { "Epoxy!B4": "Yes", "Polish!B4": "No" }),
    taxableSecond: B.conditionsFromCells({ taxable: true }, { "Leveling!B6": "No" }),
  },
  // Renovation: the model carries no answer, and a save carries the cells' own
  reno: {
    polishOnly: pickCells(B.conditionCellWrites(conds(), { "Polish!B10": "Reno" }, undefined), ["Epoxy!B10", "Polish!B10"]),
    epoxyOnly: pickCells(B.conditionCellWrites(conds(), { "Epoxy!B10": "Reno" }, undefined), ["Epoxy!B10", "Polish!B10"]),
    bothNew: pickCells(B.conditionCellWrites(conds(), { "Epoxy!B10": "New", "Polish!B10": "New" }, undefined), ["Epoxy!B10", "Polish!B10"]),
    firstWins: pickCells(B.conditionCellWrites(conds(), { "Epoxy!B10": "New", "Polish!B10": "Reno" }, undefined), ["Epoxy!B10", "Polish!B10"]),
    firstIsSpaces: pickCells(B.conditionCellWrites(conds(), { "Epoxy!B10": "  ", "Polish!B10": "Reno" }, undefined), ["Epoxy!B10", "Polish!B10"]),
    blank: pickCells(B.conditionCellWrites(conds(), {}, undefined), ["Epoxy!B10", "Polish!B10"]),
    secondIsSpelledOddly: pickCells(B.conditionCellWrites(conds(), { "Polish!B10": " RENO " }, undefined), ["Epoxy!B10", "Polish!B10"]),
    // saved twice, as the page does on every edit: it stays Reno
    survivesTwoSaves: (() => {
      const first = B.conditionCellWrites(conds(), { "Polish!B10": "Reno" }, undefined);
      return pickCells(B.conditionCellWrites(conds(), first, undefined), ["Epoxy!B10", "Polish!B10"]);
    })(),
  },
};

// ── 3. the test copy, through the real polish-sandbox.js ─────────────────────────────────────────
const win = { TWWorkTypes: T };
vm.runInNewContext(SANDBOX, { window: win, document: { getElementById: () => null }, console });
const SB = win.TWPolishSandbox;

/** A split spreadsheet draft the way the estimate screen leaves one: the intake's answers, every sheet's own
 *  tax cells (they differ), and every derived key the copy must leave behind. */
function splitSource(over) {
  const full = Object.assign({
    project_name: "Nearman Creek", work_type: "polish", audience: "Direct", polish_sf: 2875,
    tax_flags_per_sheet: true, base_tab_id: "Polish",
    priced_tabs: [{ id: "Polish", total: 13265, flag_cells: { taxable: "Polish!B6", remodel: "Polish!D6" } }],
    proposal_lump_sum: 13265, computed_bid: { lump_sum: 11111 },
    cell_values: Object.assign({ "Epoxy!B4": "Yes", "Polish!B4": "Yes", "Epoxy!D5": "No", "Epoxy!B10": "New",
                                 "Polish!B10": "New", "Polish!E25": "No", "Polish!E29": "No", "Polish!F29": "No",
                                 "Epoxy!E20": 4000 }, SPLIT_CELLS),
  }, over || {});
  // a key handed in as undefined is a key the draft does not have
  return Object.fromEntries(Object.entries(full).filter(([, v]) => v !== undefined));
}
out.sandbox = (() => {
  const source = splitSource();
  const before = JSON.stringify(source);
  const copy = SB.buildCopy(source, "src-1");
  const unsplit = SB.buildCopy(splitSource({ tax_flags_per_sheet: undefined }), "src-2");
  return {
    keys: Object.keys(copy).sort(),
    marker: copy.tax_flags_per_sheet === undefined ? null : copy.tax_flags_per_sheet,
    unsplitHasNoMarker: !Object.prototype.hasOwnProperty.call(unsplit, "tax_flags_per_sheet"),
    taxCells: pickCells(copy.cell_values, TAX_CELLS),
    sheetCellDropped: !Object.prototype.hasOwnProperty.call(copy.cell_values || {}, "Epoxy!E20"),
    derivedLeftBehind: ["priced_tabs", "base_tab_id", "proposal_lump_sum", "computed_bid"]
      .filter((k) => Object.prototype.hasOwnProperty.call(copy, k)),
    sourceUntouched: JSON.stringify(source) === before,
    copyableKeysHasMarker: SB.COPYABLE_KEYS.indexOf("tax_flags_per_sheet") !== -1,
    copyableCells: SB.COPYABLE_CELLS.slice(),
  };
})();

// ── 4. THE JOURNEY: copy a split project, open it in v2, save, look at the option sheets ────────
/** A v2 save of `draft`, built the way the Takeoff step builds it: the model is read off the draft with the
 *  cell winning, then buildSavePatch writes the cells. `split` is the draft's own mark. */
function v2Save(draft, change) {
  const split = !!draft.tax_flags_per_sheet;
  const model = B.migrateModel(draft.polish_estimate);
  model.conditions = B.conditionsFromCells(model.conditions, draft.cell_values, split);
  if (change) Object.assign(model.conditions, change);
  const bid = B.markupChain({ material: 5000, labor: 4000, sf: 2875, conditions: model.conditions,
                              remodel_rate: 0.07975 });
  const patch = B.buildSavePatch(model, draft, { bid });
  return { patch, model };
}
/** The split source's own cells with some overridden. */
const sourceCells = (over) => Object.assign({}, splitSource().cell_values, over);
function journey(source, change) {
  const copy = SB.buildCopy(source, "src-1");
  const first = v2Save(copy, change);
  // and again, on what the first save wrote (the page saves on every edit)
  const second = v2Save(Object.assign({}, copy, first.patch), null);
  return {
    copyKeys: Object.keys(copy).sort(),
    taxable: first.model.conditions.taxable,
    remodel: first.model.conditions.remodel_tax,
    cells: pickCells(first.patch.cell_values, TAX_CELLS),
    cellsAgain: pickCells(second.patch.cell_values, TAX_CELLS),
    total: first.patch.computed_bid.lump_sum,
  };
}
out.journey = {
  // THE TASK'S OWN CASE: Leveling and Gypsum (FR) tax-exempt, Epoxy taxable, split.
  split: journey(splitSource({ cell_values: without(splitSource().cell_values, ["Polish!B6", "Polish!D6"]) })),
  // the same with the base sheet's own answer in the draft: Polish is tax-exempt
  baseExempt: journey(splitSource({ cell_values: Object.assign({}, splitSource().cell_values, { "Polish!B6": "No" }) })),
  // and flipped by the estimator in v2: the base sheet's answer moves, the options' do not
  flipped: journey(splitSource(), { taxable: false, remodel_tax: true }),
  // a draft that is NOT split keeps the fan-out: every literal follows the one answer
  unsplit: journey(splitSource({ tax_flags_per_sheet: undefined })),
  // A SPLIT PROJECT WHOSE JOB IS NOT POLISH. v2 prices a polish bid, so it reads Polish!B6 and Polish!D6, and the
  // source's own base answer (changed on the grid after the split stamped Polish's) has to be in them.
  epoxyBased: journey(splitSource({ work_type: "epoxy", cell_values: sourceCells({
    "Epoxy!B6": "No", "Epoxy!D6": "Yes", "Polish!B6": "Yes", "Polish!D6": "No" }) })),
  epoxyBasedNoPolish: journey(splitSource({ work_type: "epoxy", cell_values: without(sourceCells({
    "Epoxy!B6": "No", "Epoxy!D6": "Yes" }), ["Polish!B6", "Polish!D6"]) })),
  gypBased: journey(splitSource({ work_type: "gyp", cell_values: sourceCells({
    'Gyp (USG 1-8")!B8': "No", 'Gyp (USG 1-8")!D8': "Yes", "Polish!B6": "Yes", "Polish!D6": "No" }) })),
  // a combo job has a Polish base of its own: its answer is what v2 reads, whatever Epoxy's says
  comboBased: journey(splitSource({ work_type: "combo", cell_values: sourceCells({
    "Epoxy!B6": "No", "Epoxy!D6": "Yes", "Polish!B6": "Yes", "Polish!D6": "No" }) })),
  // a source whose job the vocabulary does not know is read as the polish job v2 prices
  unknownJob: journey(splitSource({ work_type: "seal", cell_values: sourceCells({
    "Epoxy!B6": "No", "Epoxy!D6": "Yes", "Polish!B6": "Yes", "Polish!D6": "No" }) })),
  // an epoxy source that is NOT split: the fan-out is untouched
  epoxyUnsplit: journey(splitSource({ work_type: "epoxy", tax_flags_per_sheet: undefined, cell_values: sourceCells({
    "Epoxy!B6": "No", "Epoxy!D6": "Yes", "Polish!B6": "Yes", "Polish!D6": "No" }) })),
};

// ── 5. the cells the LIVE intake writes, lifted out of js/index.js and evaluated ─────────────────
// The known gaps in test_v2_condition_cells.py say "the live intake does not write them either", and this is
// what that is checked against: the page's own literal, until Phase 9 moves it onto the table.
const INDEX = L.read(pick("js/index.js"));
out.live = {
  cells: Array.from(new Set(
    new Function(L.grabConst(INDEX, "CONDITIONS", { indent: "  " }) + "\nreturn CONDITIONS;")()
      .flatMap((c) => c.cells))),
};

process.stdout.write(JSON.stringify(out) + "\n");
