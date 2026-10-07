// THE ONE VOCABULARY: what a job is, what a workbook tab is, which quantities a job asks for, and which
// conditions a job answers. Pure data and a few readers. No DOM, no fetch, no clock, no dependency.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHY THIS FILE EXISTS. Until Phase 7 of the v2 estimating program the list of work types was written
// down more than ten times across JavaScript and Python, and the job conditions (prevailing wage,
// taxable, dye and so on) in nine more places, each with its own shape and each kept equal to the others
// by hand. The copies had already disagreed: the live intake wrote the Taxable answer to four workbook
// cells and the v2 model wrote one, so a tax-exempt Leveling or Gypsum option on a v2 bid kept charging
// 9.475%. A fact now has ONE home, and a page reads it from here (docs/v2-architecture.md, section 7).
//
// THREE WORDS, AND THEY ARE NOT THE SAME THING.
//
//   JOB TYPE   what the intake's Work Type radios pick and what a project is called: epoxy, polish, combo,
//              gyp. A job type is priced on one or more TABS (a combo job is Epoxy plus Polish). Only
//              polish is `ready` in Estimating Tool v2 so far; the others wait for their phase.
//   TAB        a family of sheets in Kyle's workbook that share one markup layout: polish, seal, epoxy,
//              leveling, gyp. The Markups page files its rules by tab, and the Defaults tab of Items and
//              Assemblies scopes a default by tab. Seal and Leveling are `optionOnly`: they are priced as
//              OPTIONS on a bid and are never a job type or a base bid (Hanz, 2026-10-07).
//   CONDITION  one of the yes/no questions a job answers (local, prevailing wage, taxable, ...), each of
//              which writes literals into workbook cells and some of which move the price.
//
// A DEFAULT'S WORK TYPES ARE TABS. `default_work_types` on a library row lists tab keys, and an empty
// list means every tab. `appliesTo` reads it, and it THROWS when it is asked about a job type such as
// "combo": a combo job has no tab of its own, so a default filed under that name could never be read
// (the Markups page already refuses it by name). Resolve a job type to its tabs first, with `tabsFor`.
//
// WHERE EACH SCREEN GETS ITS QUESTIONS. `asked_on` says, for each of three screens, the 1-based position
// of the question on that screen and 0 when the screen does not ask it: `live` is the live intake
// (js/index.js), `v2Intake` is Estimating Tool v2's intake (js/polish-intake.js), `v2Takeoff` is the
// Takeoff step's condition cards and the Defaults tab's list of them (js/polish-estimate.js and
// js/library.js). The three screens list them in three different orders, so the order is data too.
// Local job is asked on no v2 screen: the Labor step works the driving miles out and sets it.
//
// WHAT READS THIS, AND WHAT STILL HOLDS ITS OWN COPY. Read from here: js/bid-model.js (CONDITION_CELLS, the
// fresh model's conditions, which defaults apply to a bid), js/polish-intake.js (CONDITIONS),
// js/polish-estimate.js (CONDITION_CARDS), js/library.js (WORK_TYPES, appliesToWorkType and the Takeoff
// condition defaults) and js/polish-sandbox.js (COPYABLE_CELLS). The live intake (js/index.js) keeps its
// own CONDITIONS and SCOPE_BY_WORK_TYPE until Phase 9 moves it onto js/intake-scope.js, and
// test_work_types.py executes both and requires them equal to the rows below. Python is pinned to this
// file by test_work_types_python_pin.py, which runs node and compares markup.TABS, library.WORK_TYPES,
// leads._WORK_TYPES and _QUANTITY_KEYS, both TEMPLATE_PICKER tables, info_sheet_writer's area keys,
// condition_defaults.KEYS and library.RESERVED_ITEM_IDS.
//
// LOOKUPS KEYED BY DATA use a Map and never `obj[key] = value`: a key that came from a draft must not be
// able to name its way onto an object's machinery (CodeQL flags the write, and it is right to).
(function (root, factory) {
  var api = factory();
  root.TWWorkTypes = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /** `value` and everything inside it frozen, so a reader that edits what it was handed fails loudly
   *  (this file is strict) instead of changing the vocabulary for every other page. */
  function deepFreeze(value) {
    if (value && typeof value === "object" && !Object.isFrozen(value)) {
      Object.freeze(value);
      Object.keys(value).forEach(function (k) { deepFreeze(value[k]); });
    }
    return value;
  }

  // ── the screens that ask a job question ──────────────────────────────────────────────────────
  var SURFACES = ["live", "v2Intake", "v2Takeoff"];

  // ── the quantities a job asks for, in the live intake's order ────────────────────────────────
  // `name` is the intake's own field name, which is also the key a saved draft holds it under (so it is a
  // contract: renaming one orphans saved projects). `scope` is the intake's data-scope token: "epoxy",
  // "polish" and "cove" fields live in the two-system block, "gyp" fields in the gypsum box. `system` is
  // 1 or 2 for the block's two systems and 0 for gypsum. `snapshot` is the key the estimate screen files
  // the same quantity under in `sheet_area` and on each priced tab (AREA_SF_CELLS, GYP_SF_CELLS in
  // js/estimate-review.js), or null when the sheet has no cell for it: Polish has ONE area cell, so a
  // second polish system is typed on the intake and goes nowhere.
  var FIELDS = [
    { name: "system_1_sf",     scope: "epoxy",  unit: "SF", system: 1, snapshot: "epoxy_sf" },
    { name: "polish_sf",       scope: "polish", unit: "SF", system: 1, snapshot: "polish_sf" },
    { name: "cove_1_lf",       scope: "cove",   unit: "LF", system: 1, snapshot: "cove_lf" },
    { name: "system_2_sf",     scope: "epoxy",  unit: "SF", system: 2, snapshot: "epoxy_sf_2" },
    { name: "polish_2_sf",     scope: "polish", unit: "SF", system: 2, snapshot: null },
    { name: "cove_2_lf",       scope: "cove",   unit: "LF", system: 2, snapshot: "cove_lf_2" },
    { name: "gyp_soft_sf",     scope: "gyp",    unit: "SF", system: 0, snapshot: "gyp_soft_sf" },
    { name: "gyp_hard_sf",     scope: "gyp",    unit: "SF", system: 0, snapshot: "gyp_hard_sf" },
    { name: "gyp_corridor_sf", scope: "gyp",    unit: "SF", system: 0, snapshot: "gyp_corridor_sf" }
  ];

  // ── the tabs of Kyle's workbook, in the order markup.TABS lists them ─────────────────────────
  // `sheets` are the workbook tab ids the tab covers; the first is its base sheet. 'Epoxy blank' is the
  // Epoxy layout with its rows left empty and is filed under epoxy for markup (MARKUP_LAYOUT_OF in
  // js/estimate-review.js), and the five Gyp sheets are variants of one gypsum product that all carry
  // the gyp layout. `area` and `cove` name the intake fields whose quantities feed the tab: the Seal
  // sheets ARE the Polish layout and snapshot their area under the same key, which is why seal lists
  // polish_sf. `role` is what a priced tab is called on a proposal, and `markupLayout` is the
  // markup_rules layout an admin files its rates under (both equal the key today).
  var TABS = [
    { key: "polish",   label: "Polish",   role: "polish",   markupLayout: "polish",   optionOnly: false,
      sheets: ["Polish"],
      area: ["polish_sf"], cove: [] },
    { key: "seal",     label: "Seal",     role: "seal",     markupLayout: "seal",     optionOnly: true,
      sheets: ["Seal", "Seal (+Jnts)"],
      area: ["polish_sf"], cove: [] },
    { key: "epoxy",    label: "Epoxy",    role: "epoxy",    markupLayout: "epoxy",    optionOnly: false,
      sheets: ["Epoxy", "Epoxy blank"],
      area: ["system_1_sf", "system_2_sf"], cove: ["cove_1_lf", "cove_2_lf"] },
    { key: "leveling", label: "Leveling", role: "leveling", markupLayout: "leveling", optionOnly: true,
      sheets: ["Leveling"],
      area: [], cove: [] },
    { key: "gyp",      label: "Gyp",      role: "gyp",      markupLayout: "gyp",      optionOnly: false,
      sheets: ['Gyp (USG 1-8")', "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"],
      area: ["gyp_soft_sf", "gyp_hard_sf", "gyp_corridor_sf"], cove: [] }
  ];

  // ── the job types, in the live intake's order ────────────────────────────────────────────────
  // `tabs` are the tabs the job is priced on (the first is the base); `ready` is whether Estimating Tool
  // v2 prices it yet. `proposalKey` is the work-type half of the keys of TEMPLATE_PICKER in
  // backend/proposal_writer.py and backend/cover_letter_writer.py, and `audiences` are the audiences that
  // table has a template for: null means the template ignores the audience (gypsum). Combo's GC template
  // is the GC resinous document, for want of a GC combo one. `fields` are the intake quantity fields the
  // job shows, `thickness` is whether the intake asks for a system thickness (a resin question).
  var JOB_TYPES = [
    { key: "epoxy",  label: "Epoxy",  tabs: ["epoxy"], ready: false,
      proposalKey: "epoxy", audiences: ["Direct", "GC"],
      fields: ["system_1_sf", "cove_1_lf", "system_2_sf", "cove_2_lf"], thickness: true },
    { key: "polish", label: "Polish", tabs: ["polish"], ready: true,
      proposalKey: "polish", audiences: ["Direct", "GC"],
      fields: ["polish_sf", "polish_2_sf"], thickness: false },
    { key: "combo",  label: "Combo (Epoxy + Polish)", tabs: ["epoxy", "polish"], ready: false,
      proposalKey: "combo", audiences: ["Direct", "GC"],
      fields: ["system_1_sf", "polish_sf", "cove_1_lf", "system_2_sf", "polish_2_sf", "cove_2_lf"],
      thickness: true },
    { key: "gyp",    label: "Gyp (Gypsum Underlayment)", tabs: ["gyp"], ready: false,
      proposalKey: "gyp", audiences: [null],
      fields: ["gyp_soft_sf", "gyp_hard_sf", "gyp_corridor_sf"], thickness: false }
  ];

  var ALL_JOBS = ["epoxy", "polish", "combo", "gyp"];

  // ── the job conditions: ONE table, in the order the questions first appear ───────────────────
  // key, label and why are what a screen shows. `default` is what a new job answers (the live intake's
  // `def`, and the v2 model's fresh answer for the ones it carries; the two agreed, and this is where they
  // are now held equal). `scope` is the job types that are asked. `cells` are the workbook cells the
  // answer is written to, as "Sheet!A1" addresses, and `on` / `off` are the literals written: BOTH are
  // always written and never a blank for "off", because Kyle's formulas read a blank Yes/No cell as
  // whatever their IF falls through to (Polish!C17 is IF(B10="New",0.05,0.15), so a blank B10 takes the
  // Reno branch and triples the patch material rate). The FIRST cell is the one a screen reads the switch
  // back from. `needs` names a condition this one means nothing without. `model` is whether the v2
  // estimate model carries the answer in its `conditions`; the ones it does not carry are written to the
  // workbook with their default only while the cell is blank (Renovation and Bulk discount are asked on
  // the live intake alone). `item_id` is the reserved library item that prices the condition, for the
  // three the Takeoff step carries. `wording` replaces `why` on a screen that words it differently.
  //
  // TAXABLE WRITES FOUR CELLS, and that is the whole of Kyle's tax-exempt bug on the base tabs. The
  // sales-tax rate is `=IF($B$6="no",0,0.09475)` on every priced sheet, and each sheet reads its OWN
  // flag. Polish, Seal, 'Seal (+Jnts)' and 'Epoxy blank' mirror Epoxy!B6, so writing it carries them;
  // Leveling!B6, 'Gyp (USG 1-8")'!B8 and 'Gyp (FR)'!B8 are independent literals that nothing wrote, so a
  // tax-exempt Gypsum or Leveling bid carried 9.475% it should not have. The other three Gyp variants
  // mirror the gyp base. Epoxy!B6 stays FIRST. Prevailing wage and remodel tax really are Epoxy-only:
  // Epoxy!D5 and Epoxy!D6 are the only literals either has, and every other sheet's is =Epoxy!.
  //
  // THINGS READ OUT OF THE TEMPLATE, not assumed. Polish!B4 holds its own Yes/No, so Local writes both.
  // Polish!D5, B6 and D6 are the formulas =Epoxy!D5, =Epoxy!B6, =Epoxy!D6, so the Polish tab is never
  // written for them. Epoxy!D41 is compared against V136 and V137 by all six of its consumers, which read
  // "BULK Discount ON" and "Bulk Discount OFF", mixed case and inconsistent with each other: any other
  // casing silently takes the OFF branch. Polish!H36 is not a second dye switch (it holds the label
  // "Dye?"), so Dye writes the material cell E25 only. NO HARD BID: Hanz, 2026-10-03, removed the switch,
  // and nothing may write Epoxy!B5 or Polish!B5 (estimate_writer HARD_BID_FLAG_CELLS).
  var CONDITIONS = [
    { key: "local", label: "Local job", scope: ALL_JOBS,
      why: "Under 70 miles. Off means travel and lodging get added.",
      default: true, cells: ["Epoxy!B4", "Polish!B4"], on: "Yes", off: "No", needs: null,
      model: true, item_id: null, asked_on: { live: 1, v2Intake: 0, v2Takeoff: 0 } },
    { key: "prevailing_wage", label: "Prevailing wage", scope: ALL_JOBS,
      why: "Raises every labor line to the prevailing rate.",
      default: false, cells: ["Epoxy!D5"], on: "Yes", off: "No", needs: null,
      model: true, item_id: null, asked_on: { live: 2, v2Intake: 1, v2Takeoff: 0 } },
    { key: "taxable", label: "Taxable", scope: ALL_JOBS,
      why: "Adds sales tax. The bid you see already includes it.",
      default: true, cells: ["Epoxy!B6", "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8"],
      on: "Yes", off: "No", needs: null,
      model: true, item_id: null, asked_on: { live: 3, v2Intake: 2, v2Takeoff: 0 } },
    // The live intake's sentence, kept as it was written (its dash is U+2014). Estimating Tool v2's
    // intake has its own wording because the county box is not "below" there.
    { key: "remodel_tax", label: "Remodel tax", scope: ALL_JOBS,
      why: "Occupied remodel. Taxed at the county rate \u2014 pick the county below.",
      wording: { v2Intake: "Occupied remodel. Adds the county remodel rate on top." },
      default: false, cells: ["Epoxy!D6"], on: "Yes", off: "No", needs: null,
      model: true, item_id: null, asked_on: { live: 4, v2Intake: 3, v2Takeoff: 0 } },
    // BOND HAS NO CELL: the sheet's bond rate is a hardcoded number, not a Yes/No flag, so there is no
    // literal to write and nothing for an intake to read back. It is a model answer only, and the one
    // condition the Review step could always flip safely.
    { key: "bond", label: "Bond", scope: ALL_JOBS,
      why: "Bond premium on the running total. The sheet ships this at 0% either way.",
      default: false, cells: [], on: null, off: null, needs: null,
      model: true, item_id: null, asked_on: { live: 0, v2Intake: 4, v2Takeoff: 0 } },
    { key: "reno", label: "Renovation", scope: ["epoxy", "polish", "combo"],
      why: "Existing floor, not new construction. Triples the patch material rate.",
      default: false, cells: ["Epoxy!B10", "Polish!B10"], on: "Reno", off: "New", needs: null,
      model: false, item_id: null, asked_on: { live: 5, v2Intake: 0, v2Takeoff: 0 } },
    { key: "dye", label: "Dye", scope: ["polish", "combo"],
      why: "Two coats of dye across the polished area.",
      default: false, cells: ["Polish!E25"], on: "Yes", off: "No", needs: null,
      model: true, item_id: "dye", asked_on: { live: 6, v2Intake: 0, v2Takeoff: 3 } },
    // OFF BY DEFAULT SINCE 2026-09-19. It shipped on because Kyle's template ships Polish!E29 = "Yes", a
    // faithful reading of the workbook and the wrong default for a tool that prices the line itself: the
    // kit costs $500 per 3,500 sq ft, so on a 17,500 SF floor "on by default" was $2,500 nobody chose.
    { key: "joint_filler", label: "Joint filler", scope: ["polish", "combo"],
      why: "One kit per 3,500 sq ft. Off until the job needs it.",
      default: false, cells: ["Polish!E29"], on: "Yes", off: "No", needs: null,
      model: true, item_id: "joint-filler-kit", asked_on: { live: 7, v2Intake: 0, v2Takeoff: 1 } },
    { key: "remove_existing_jf", label: "Remove existing joint filler", scope: ["polish", "combo"],
      why: "Adds a fourth hand to the joint-filler crew.",
      default: false, cells: ["Polish!F29"], on: "Yes", off: "No", needs: "joint_filler",
      model: true, item_id: "remove-existing-jf", asked_on: { live: 8, v2Intake: 0, v2Takeoff: 2 } },
    { key: "bulk_discount", label: "Bulk material discount", scope: ["epoxy", "combo"],
      why: "Swaps six epoxy material rows onto bulk pricing.",
      default: false, cells: ["Epoxy!D41"], on: "BULK Discount ON", off: "Bulk Discount OFF", needs: null,
      model: false, item_id: null, asked_on: { live: 9, v2Intake: 0, v2Takeoff: 0 } }
  ];

  deepFreeze(FIELDS);
  deepFreeze(TABS);
  deepFreeze(JOB_TYPES);
  deepFreeze(CONDITIONS);
  deepFreeze(SURFACES);

  // ── lookups, by Map ──────────────────────────────────────────────────────────────────────────
  function indexBy(rows, keyOf) {
    var m = new Map();
    rows.forEach(function (r) { m.set(keyOf(r), r); });
    return m;
  }
  var jobByKey = indexBy(JOB_TYPES, function (j) { return j.key; });
  var tabByKey = indexBy(TABS, function (t) { return t.key; });
  var fieldByName = indexBy(FIELDS, function (f) { return f.name; });
  var conditionByKey = indexBy(CONDITIONS, function (c) { return c.key; });
  var tabBySheet = new Map();
  TABS.forEach(function (t) { t.sheets.forEach(function (s) { tabBySheet.set(s, t); }); });

  function listOf(rows) { return rows.map(function (r) { return r.key; }); }

  function isJobType(key) { return typeof key === "string" && jobByKey.has(key); }
  function isTab(key) { return typeof key === "string" && tabByKey.has(key); }

  /** The words a refusal uses for a value it was handed, whatever that value is. */
  function said(v) {
    try { return typeof v === "string" ? JSON.stringify(v) : String(v); } catch (e) { return "that value"; }
  }

  function jobRecord(key, who) {
    if (!isJobType(key)) {
      throw new Error("work-types.js: " + who + "() was asked about " + said(key) + ", which is not a job type (" +
        listOf(JOB_TYPES).join(", ") + ")" + (isTab(key) ? "; it is a tab, and a tab is not a job type" : ""));
    }
    return jobByKey.get(key);
  }

  function jobType(key) { return jobRecord(key, "jobType"); }

  function tab(key) {
    if (!isTab(key)) {
      throw new Error("work-types.js: tab() was asked about " + said(key) + ", which is not a tab (" +
        listOf(TABS).join(", ") + ")");
    }
    return tabByKey.get(key);
  }

  function condition(key) {
    if (typeof key !== "string" || !conditionByKey.has(key)) {
      throw new Error("work-types.js: condition() was asked about " + said(key) + ", which is not a job condition (" +
        listOf(CONDITIONS).join(", ") + ")");
    }
    return conditionByKey.get(key);
  }

  // ── the readers ──────────────────────────────────────────────────────────────────────────────
  function jobTypeKeys() { return listOf(JOB_TYPES); }
  function tabKeys() { return listOf(TABS); }

  /** The tabs a job type is priced on, as a new array: ["polish"] for polish, ["epoxy", "polish"] for a
   *  combo job. THROWS on anything that is not a job type, a tab included, and on a missing argument:
   *  there is no default, because a default is how a gypsum job once read the Polish defaults. */
  function tabsFor(jobTypeKey) { return jobRecord(jobTypeKey, "tabsFor").tabs.slice(); }

  /** Does a default scoped to `defaultWorkTypes` apply to the tab `layout`?
   *
   *  AN EMPTY LIST MEANS EVERY TAB, and so does anything that is not a list: every row set before the
   *  Defaults tab had work types carries none, and it keeps applying everywhere exactly as it did.
   *
   *  `layout` is a TAB KEY, checked first and whatever the list holds, so a caller that hands it a job
   *  type ("combo") is told at once rather than when a list that names a tab finally arrives. A combo job
   *  reads the lists of both its tabs: `tabsFor("combo").some(...)`. */
  function appliesTo(defaultWorkTypes, layout) {
    if (!isTab(layout)) {
      throw new Error("work-types.js: appliesTo() was asked about " + said(layout) + ", which is not a tab (" +
        listOf(TABS).join(", ") + "). A job type has no defaults of its own: resolve it with tabsFor() first.");
    }
    if (!Array.isArray(defaultWorkTypes) || !defaultWorkTypes.length) return true;
    return defaultWorkTypes.indexOf(layout) !== -1;
  }

  /** The tab a workbook sheet id belongs to ("Seal (+Jnts)" is seal), or null for a sheet that is not
   *  priced (Takeoff, Stnd Alts, Specs+Dwgs+Addn, ...). */
  function tabOfSheet(sheetId) {
    var t = tabBySheet.get(sheetId);
    return t ? t.key : null;
  }

  /** The quantity fields a job type shows, in the intake's order. */
  function fieldsFor(jobTypeKey) {
    return jobRecord(jobTypeKey, "fieldsFor").fields.map(function (name) { return fieldByName.get(name); });
  }

  /** The intake's data-scope tokens a job type shows in the two-system block ("epoxy", "polish",
   *  "cove"), which is js/index.js's SCOPE_BY_WORK_TYPE. Gypsum has its own box and shows none. */
  function scopesFor(jobTypeKey) {
    var out = [];
    fieldsFor(jobTypeKey).forEach(function (f) {
      if (f.scope !== "gyp" && out.indexOf(f.scope) === -1) out.push(f.scope);
    });
    return out;
  }

  /** The conditions a job type is asked, as plain rows in table order. With `surface` (one of "live",
   *  "v2Intake", "v2Takeoff") only the ones that screen asks, in that screen's order, and `why` is the
   *  screen's own wording where it has one. */
  function conditionsFor(jobTypeKey, surface) {
    var job = jobRecord(jobTypeKey, "conditionsFor");
    var rows = CONDITIONS.filter(function (c) { return c.scope.indexOf(job.key) !== -1; });
    if (surface === undefined) return rows.map(function (c) { return Object.assign({}, c); });
    if (SURFACES.indexOf(surface) === -1) {
      throw new Error("work-types.js: conditionsFor() was asked about the screen " + said(surface) +
        ", which is not one of " + SURFACES.join(", "));
    }
    return rows
      .filter(function (c) { return c.asked_on[surface] > 0; })
      .sort(function (a, b) { return a.asked_on[surface] - b.asked_on[surface]; })
      .map(function (c) {
        var row = Object.assign({}, c);
        if (c.wording && typeof c.wording[surface] === "string") row.why = c.wording[surface];
        return row;
      });
  }

  /** The workbook cells a job type writes: one record per condition it is asked that has any, in table
   *  order, as { key, cells, on, off, default, model } with the arrays copied. A job type writes
   *  exactly the cells the live intake writes for it, because both come from the same rows. */
  function cellsFor(jobTypeKey) {
    var job = jobRecord(jobTypeKey, "cellsFor");
    return CONDITIONS
      .filter(function (c) { return c.scope.indexOf(job.key) !== -1 && c.cells.length > 0; })
      .map(function (c) {
        return { key: c.key, cells: c.cells.slice(), on: c.on, off: c.off, default: c.default, model: c.model };
      });
  }

  /** Every cell any condition writes, in table order and without repeats. A test copy of a bid keeps
   *  these from its source: the job's answers, whatever the job type. */
  function copyableCells() {
    var out = [];
    CONDITIONS.forEach(function (c) {
      c.cells.forEach(function (cell) { if (out.indexOf(cell) === -1) out.push(cell); });
    });
    return out;
  }

  /** What the v2 estimate model starts its `conditions` with: the default of every condition the model
   *  carries, in table order, as a new object. */
  function modelDefaults() {
    return Object.fromEntries(CONDITIONS
      .filter(function (c) { return c.model; })
      .map(function (c) { return [c.key, c.default]; }));
  }

  /** The reserved library items that price a condition, as { itemId: conditionKey }, in table order. */
  function reservedItems() {
    return Object.fromEntries(CONDITIONS
      .filter(function (c) { return c.item_id; })
      .map(function (c) { return [c.item_id, c.key]; }));
  }

  /** The reserved library item id that prices one condition, or null when it has none. */
  function itemIdOf(conditionKey) { return condition(conditionKey).item_id; }

  return {
    SURFACES: SURFACES, FIELDS: FIELDS, TABS: TABS, JOB_TYPES: JOB_TYPES, CONDITIONS: CONDITIONS,
    jobTypeKeys: jobTypeKeys, tabKeys: tabKeys, isJobType: isJobType, isTab: isTab,
    jobType: jobType, tab: tab, condition: condition,
    tabsFor: tabsFor, appliesTo: appliesTo, tabOfSheet: tabOfSheet,
    fieldsFor: fieldsFor, scopesFor: scopesFor,
    conditionsFor: conditionsFor, cellsFor: cellsFor, copyableCells: copyableCells,
    modelDefaults: modelDefaults, reservedItems: reservedItems, itemIdOf: itemIdOf
  };
});
