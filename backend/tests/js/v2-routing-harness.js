"use strict";
/* Run the REAL v2 routing code and report what it did.
 *
 * WHY EXECUTED. Every claim in test_v2_routing_guard.py is about something a grep cannot see:
 *
 *   * isV2Draft must answer like backend/drafts.py _polish_beta on the same values. Two answers to
 *     one question is a project that opens on the wrong screen "but only sometimes"; the harness
 *     lifts the real function out of shared.js and feeds it the cases the Python side is fed.
 *   * The guard at the top of estimate-review.js has to STOP the script before anything writes. The
 *     file is a 5,000-line classic script that needs HyperFormula and a DOM, so what runs here is its
 *     real head, cut at the comment that opens the next section, with a sentinel appended: if the
 *     guard did not throw, the sentinel is reached, and "startup stops" is something that either
 *     happened or did not.
 *   * buildCopy has to leave the spreadsheet's price behind, for every work type. The real
 *     polish-sandbox.js is loaded whole, as a page loads it, and handed a spreadsheet-built draft.
 *   * v2PricingView has to hand back the SAME object for every draft but a stale v2 one, and a
 *     filtered copy for that one, without touching the original.
 *
 * Nothing here is a copy of the logic under test: the functions come out of the page files by name
 * (_lib.js), bound to stubs for the ONLY things they read (the draft id, the stamp, the page).
 *
 * Usage: node v2-routing-harness.js <frontend-dir> <cases.json>   ->   one line of JSON
 *
 * <frontend-dir> may hold only some of the files. Whatever it lacks is read from the real frontend,
 * which is how the tests break ONE file in a scratch copy and watch these results go red.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const L = require("./_lib.js");

const REAL = path.resolve(__dirname, "..", "..", "..", "frontend");
const GIVEN = path.resolve(process.argv[2] || REAL);
const pick = (rel) => (fs.existsSync(path.join(GIVEN, rel)) ? path.join(GIVEN, rel) : path.join(REAL, rel));
const src = (rel) => L.read(pick(rel));

const SHARED = src("shared.js");
const ESTIMATE = src("js/estimate-review.js");
const INDEX = src("js/index.js");
const SANDBOX = src("js/polish-sandbox.js");

const STAMP = new Function(L.grabConst(SHARED, "STAMP", { indent: "  " }) + "\nreturn STAMP;")();
const SHEET_PRICING_KEYS = new Function(
  L.grabConst(SHARED, "SHEET_PRICING_KEYS", { indent: "  " }) + "\nreturn SHEET_PRICING_KEYS;")();

const isV2Draft = L.lift(SHARED, "isV2Draft", {});
const v2PricingView = L.lift(SHARED, "v2PricingView", { isV2Draft, SHEET_PRICING_KEYS });
const copy = (x) => JSON.parse(JSON.stringify(x));
const out = {};

// ── 1. isV2Draft, on the cases the Python side is fed ───────────────────────────────────────────
// A case is {kind: "value", value} (the version, as JSON), {kind: "number", value: "nan" | "inf" |
// "-inf"} (the numbers JSON cannot carry), {kind: "absent"} (a polish_estimate with no version) or
// {kind: "no_estimate"} (a draft with none).
function blobFor(c) {
  if (c.kind === "no_estimate") return {};
  if (c.kind === "absent") return { polish_estimate: {} };
  if (c.kind === "number") {
    const n = { nan: NaN, inf: Infinity, "-inf": -Infinity }[c.value];
    return { polish_estimate: { version: n } };
  }
  return { polish_estimate: { version: c.value } };
}
const cases = process.argv[3] ? JSON.parse(fs.readFileSync(process.argv[3], "utf8")) : [];
out.parity = cases.map((c) => isV2Draft(blobFor(c)));
// The blob shapes around the version: not an object, an estimate that is not an object.
out.oddShapes = [null, undefined, "x", 5, [], [2], { polish_estimate: null }, { polish_estimate: [2] },
  { polish_estimate: "2" }, { polish_estimate: 2 }].map((b) => isV2Draft(b));

// ── 2. the head of estimate-review.js ───────────────────────────────────────────────────────────
const CUT = "// ─── Project Info canonicalization";
const cutAt = ESTIMATE.indexOf(CUT);
if (cutAt < 0) {
  throw new Error("estimate-review.js no longer has the comment '" + CUT + "'. The harness cuts the "
    + "page there, after the v2 guard: repoint the cut to the line that follows the guard.");
}
const HEAD = ESTIMATE.slice(0, cutAt);

/** The head of the page, run against `blob` as the draft in storage and `id` as the draft the page
 *  is on. Reports where it went, whether it stopped, and every write it tried. */
function runHead(blob, id) {
  const rec = { replaced: [], assigned: [], writes: [], main: null, reached: false, error: null };
  const TW = {
    getState: () => blob,
    isV2Draft,
    isThisDraft: L.lift(SHARED, "isThisDraft", { getDraftId: () => id, STAMP }),
    withDraft: L.lift(SHARED, "withDraft", { getDraftId: () => id }),
    // Anything that writes. None of these may be called: the guard stands before all of them.
    setState: () => { rec.writes.push("setState"); },
    setLocalState: () => { rec.writes.push("setLocalState"); },
    flushState: () => { rec.writes.push("flushState"); },
  };
  const main = { set innerHTML(v) { rec.main = v; }, get innerHTML() { return rec.main; } };
  const document = { querySelector: (sel) => (sel === "main" ? main : null) };
  const window = { location: { replace: (u) => rec.replaced.push(u), assign: (u) => rec.assigned.push(u) } };
  try {
    new Function("TW", "document", "window", "__rec", HEAD + "\n__rec.reached = true;")(TW, document, window, rec);
  } catch (e) {
    rec.error = String((e && e.message) || e);
  }
  return rec;
}

// isThisDraft on its own: a blob is this page's only when its stamp names the draft the page is on.
const ownedBy = (id) => L.lift(SHARED, "isThisDraft", { getDraftId: () => id, STAMP });
out.ownership = {
  match: ownedBy("d1")({ [STAMP]: "d1" }),
  other: ownedBy("d2")({ [STAMP]: "d1" }),
  unstamped: ownedBy("d1")({ project_name: "x" }),
  emptyStamp: ownedBy("d1")({ [STAMP]: "" }),
  noDraftId: ownedBy(null)({ [STAMP]: "d1" }),
  notBlobs: [null, undefined, "d1", 5].map((b) => ownedBy("d1")(b)),
};

const FILLED = { project_name: "Nearman Creek (beta test)", work_type: "polish" };
const stamped = (o) => Object.assign({ [STAMP]: "d1" }, FILLED, o || {});
out.estimate = {
  v2: runHead(stamped({ polish_estimate: { version: 2 } }), "d1"),
  v2Text: runHead(stamped({ polish_estimate: { version: "2" } }), "d1"),
  // Another project's v2 blob in storage while a link opens "d9": shared.js is about to fetch d9 and
  // reload, so this first run must leave it alone.
  anotherProjects: runHead(stamped({ polish_estimate: { version: 2 } }), "d9"),
  unstamped: runHead(Object.assign({}, FILLED, { polish_estimate: { version: 2 } }), "d1"),
  spreadsheet: runHead(stamped({ priced_tabs: [{ id: "Polish", total: 9000 }] }), "d1"),
  oldPolishEstimate: runHead(stamped({ polish_estimate: { areas: [] } }), "d1"),
  versionOne: runHead(stamped({ polish_estimate: { version: 1 } }), "d1"),
  // The existing "no project" stop comes first and is not replaced by a redirect.
  noProject: runHead({ [STAMP]: "d1", polish_estimate: { version: 2 } }, "d1"),
};

// ── 3. the test copy ─────────────────────────────────────────────────────────────────────────────
// The sandbox reads the cells a test copy keeps off the one vocabulary (js/work-types.js copyableCells)
// as it parses, so the real module is handed to the window it runs against, under its real global name.
const win = { TWWorkTypes: require(pick("js/work-types.js")) };
vm.runInNewContext(SANDBOX, { window: win, document: { getElementById: () => null }, console });
const SB = win.TWPolishSandbox;

// The job-condition cells, as the live intake's CONDITIONS table writes them: lifted out of
// index.js and evaluated, so a condition added there shows up here.
const CONDITIONS = new Function(L.grabConst(INDEX, "CONDITIONS", { indent: "  " }) + "\nreturn CONDITIONS;")();
const conditionCells = [];
CONDITIONS.forEach((c) => c.cells.forEach((cell) => { if (conditionCells.indexOf(cell) < 0) conditionCells.push(cell); }));

/** A draft built by the SPREADSHEET workflow, the way the estimate screen and the proposal step
 *  leave one: the intake answers, the sheet's own cells, and every derived key. */
function spreadsheetBlob(workType) {
  const tabs = {
    epoxy: [{ id: "Epoxy", name: "Epoxy", role: "epoxy", kind: "base", total: 18670 }],
    polish: [{ id: "Polish", name: "Polish", role: "polish", kind: "base", total: 13265 }],
    combo: [{ id: "Epoxy", name: "Epoxy", role: "epoxy", kind: "base", total: 18670 },
            { id: "Polish", name: "Polish", role: "polish", kind: "base", total: 13265 }],
    gyp: [{ id: 'Gyp (USG 1-8")', name: "Gyp", role: "gyp", kind: "base", total: 22400 }],
  }[workType];
  const base = workType === "combo" ? null : tabs[0].id;
  const cells = { "Epoxy!B1": "Nearman Creek", "Epoxy!E20": 4000, "Polish!E18": 2875, "Epoxy!E34": 120,
                  'Gyp (USG 1-8")!E20': 1000, "Polish!C25": 1.2, "Epoxy!D77": 450 };
  conditionCells.forEach((c, i) => { cells[c] = i % 2 ? "Yes" : "No"; });
  return {
    // what a person typed, on either intake form
    project_name: "Nearman Creek", address: "1200 Kaw Dr", city: "Overland Park", state: "KS",
    zip: "66210", city_state: "Overland Park, KS", architect: "HOK", approx_start_date: "2026-10-01",
    bid_date: "2026-09-20", deadline: "2026-09-20", source: "Referral", work_areas: "Warehouse",
    audience: "Direct", work_type: workType,
    contact_name: "Dave", contact_email: "dave@example.com", contact_phone: "913-555-0101",
    contact_notes: "Call first", drawings_dated: "2026-08-15", spec_section: "033543", finish_tag: "PC",
    plan_sheet: "A900", addenda_count: 2,
    system_1_sf: 4000, system_2_sf: 0, polish_sf: 2875, polish_2_sf: 0, cove_1_lf: 120, cove_2_lf: 0,
    gyp_soft_sf: workType === "gyp" ? 1000 : "", gyp_hard_sf: "", gyp_corridor_sf: "",
    system_thickness: 40, num_systems: 2,
    county: "Johnson County, KS", county_tax_rate: 0.01475, county_remodel_rate: 0.07975,
    county_notes: "county floor", remodel_rate_override: 0.0935,
    // the sheet's own working, and the job conditions among it
    cell_values: cells,
    // everything the estimate screen derives from the sheet
    priced_tabs: tabs, rooms: [{ id: tabs[0].id, is_base: true }], base_tab_id: base,
    proposal_lump_sum: tabs[0].total, proposal_sales_tax: 1500, proposal_remodel_tax: 800,
    proposal_taxable: true, proposal_remodel_on: false, sheet_area: { epoxy_sf: 4000 },
    hf_lump_sums: { epoxy: 18670, polish: 13265, combined: 31935, gyp: 0 },
    cost_snapshot: { costs: 9000, man_hours: 120 }, phase_price: 4500,
    computed_bid: { lump_sum: 11111, full_bid: { total_base_bid: 11111, sales_tax: 1, remodel_tax: 2 } },
    alternate_computed_bid: null,
    // the proposal and the files built from them, and what was done with them
    tab_opts: { Polish: { is_option: true } }, tab_copies: [], tab_labels: {}, tab_order: [],
    tab_notes: {}, tab_structs: [], lock_overrides: {}, tax_flags_per_sheet: true,
    system_name: "Treadwell MACRO Flake", texture: "Smooth", scope_notes: "Grind and coat.",
    schedule_notes: "One week.", exclusions: "Moving furniture.", notes_text: "A note",
    estimator_name: "Kyle Loseke", tax_layout: "BROKEN_OUT", tax_inclusion: "INCLUDED",
    price_overrides: { lines: {} }, price_lines: [{ label: "Joint filler", amount: 1500 }],
    extras: [], paragraph_overrides: [], paragraph_overrides_all: {},
    proposal_payload: { values: { total_formatted: "$18,670" } }, proposal_payload_key: "k.k",
    generate_result: { docx_download_url: "/api/file/OLD" }, generated_lump_sum: "$18,670",
    lump_sum_display: "$18,670.00", dropbox_result: { folder: "/Estimating/old" },
    portal_message: "Hi Dave", portal_emails: ["dave@example.com"], require_deposit: true,
    job_number: "26-101", info_cell_values: { "Info!B58": 9000 }, notify_picks: { sent: [] },
    won: { at: "2026-09-24" }, handed_off: { at: "2026-09-25" },
    closed_lost: null, on_hold: null,
    // what the server owns, and shared.js's stamp
    is_test: false, archived: false, assigned_estimator: "kyle@wetreadwell.com", [STAMP]: "src-1",
  };
}

out.sandbox = {
  copyableKeys: SB.COPYABLE_KEYS.slice(),
  copyableCells: SB.COPYABLE_CELLS.slice(),
  conditionCells,
  sheetPricingKeys: SHEET_PRICING_KEYS.slice(),
  byWorkType: {},
};
["epoxy", "polish", "combo", "gyp"].forEach((wt) => {
  const source = spreadsheetBlob(wt);
  const before = copy(source);
  const made = SB.buildCopy(source, "src-1");
  out.sandbox.byWorkType[wt] = {
    source: before,
    sourceKeys: Object.keys(source),
    copy: made,
    keys: Object.keys(made),
    // The copy is a new object that shares nothing it could change in the source by mutation.
    sourceUntouched: JSON.stringify(source) === JSON.stringify(before),
    cellKeys: Object.keys(made.cell_values || {}),
  };
});
// A source holding nothing at all, and one holding no cells: the copy still comes out, marked.
out.sandbox.empty = SB.buildCopy({}, "src-2");
out.sandbox.noCells = SB.buildCopy({ project_name: "X (beta test)", cell_values: {} }, "src-3");
out.sandbox.oneCell = SB.buildCopy({ project_name: "Y", cell_values: { "Epoxy!B6": "No", "Epoxy!E20": 9 } }, "src-4");
// A key named like an object's own machinery must not be able to name its way into the copy.
out.sandbox.hostile = SB.buildCopy(JSON.parse(
  '{"project_name":"Z","__proto__":{"polluted":true},"constructor":{"x":1},'
  + '"cell_values":{"__proto__":{"y":1},"Epoxy!B6":"Yes"}}'), "src-5");
out.sandbox.hostilePolluted = ({}).polluted === undefined && ({}).y === undefined ? false : true;

// ── 4. the pricing view ─────────────────────────────────────────────────────────────────────────
const V2 = { version: 2, totals: { total: 14224 } };
const SHEET_TABS = [{ id: "Polish", name: "Polish", role: "polish", kind: "base", total: 13265 }];
const stale = () => ({
  project_name: "Nearman Creek (beta test)", work_type: "polish", polish_estimate: copy(V2),
  priced_tabs: copy(SHEET_TABS), rooms: [{ id: "Polish", is_base: true }], base_tab_id: "Polish",
  proposal_lump_sum: 13265, proposal_sales_tax: 900, proposal_remodel_tax: 0, proposal_taxable: true,
  proposal_remodel_on: false, sheet_area: { polish_sf: 2875 }, hf_lump_sums: { polish: 13265 },
  cost_snapshot: { costs: 1, man_hours: 2 }, phase_price: 4500,
  computed_bid: { lump_sum: 14224, full_bid: { total_base_bid: 14224, sales_tax: 1, remodel_tax: 2 } },
  price_overrides: { lines: {} }, tab_opts: {}, cell_values: { "Epoxy!B6": "Yes" },
});
const view = {};
{
  const b = stale();
  const before = JSON.stringify(b);
  const v = v2PricingView(b);
  view.stale = { same: v === b, keys: Object.keys(v), originalUntouched: JSON.stringify(b) === before,
                 computedBidShared: v.computed_bid === b.computed_bid,
                 nestedShared: v.price_overrides === b.price_overrides && v.cell_values === b.cell_values,
                 total: v.computed_bid && v.computed_bid.full_bid.total_base_bid };
}
{
  const b = spreadsheetBlob("polish");
  view.plainSheet = { same: v2PricingView(b) === b };
}
{
  const b = Object.assign(stale(), { polish_estimate: { areas: [] } });
  view.oldPolishEstimate = { same: v2PricingView(b) === b };
}
{
  const b = stale();
  b.priced_tabs = [{ id: "Polish", total: 14224, v2: true }];
  view.allMarked = { same: v2PricingView(b) === b };
}
{
  const b = stale();
  b.priced_tabs = [{ id: "Polish", total: 14224, v2: true }, { id: "Epoxy", total: 1 }];
  view.someMarked = { same: v2PricingView(b) === b, keys: Object.keys(v2PricingView(b)) };
}
{
  const b = stale();
  b.priced_tabs = [{ id: "Polish", total: 14224, v2: "yes" }];
  view.markIsExactlyTrue = { same: v2PricingView(b) === b };
}
{
  const b = stale();
  b.priced_tabs = [];
  view.emptyTabsStaleTotal = { same: v2PricingView(b) === b, keys: Object.keys(v2PricingView(b)) };
}
{
  const b = stale();
  b.priced_tabs = [null];
  view.nullTab = { same: v2PricingView(b) === b, keys: Object.keys(v2PricingView(b)) };
}
{
  const b = { project_name: "Clean v2", polish_estimate: copy(V2), computed_bid: { lump_sum: 1 } };
  view.cleanV2 = { same: v2PricingView(b) === b };
}
{
  const b = Object.assign(stale(), { polish_estimate: { version: "2" } });
  view.textVersion = { same: v2PricingView(b) === b, keys: Object.keys(v2PricingView(b)) };
}
view.notObjects = [null, undefined, "x", 5].map((x) => v2PricingView(x) === x);
out.view = view;

// ── 4b. what Continue takes off the STORED copy ─────────────────────────────────────────────────
// v2SheetKeysOut(blob) is the patch that makes the stored draft say what the view let the page read:
// one `undefined` per hidden key, which setState's merge applies and JSON.stringify leaves out. The
// real function, lifted with the real view it stands on.
//
// THE LAW, run on every draft below: apply the patch the way setState does (Object.assign onto the
// stored blob, then the JSON round trip every write goes through) and what is stored equals what the
// view handed the page. A patch that took too little leaves the customer's portal pricing the
// spreadsheet's rooms; one that took too much costs a page a key it was still reading.
const v2SheetKeysOut = L.lift(SHARED, "v2SheetKeysOut", { v2PricingView, SHEET_PRICING_KEYS });
const sameBlob = (x, y) => {
  const kx = Object.keys(x).sort();
  const ky = Object.keys(y).sort();
  return JSON.stringify(kx) === JSON.stringify(ky) && kx.every((k) => JSON.stringify(x[k]) === JSON.stringify(y[k]));
};
const storedAfter = (b) => JSON.parse(JSON.stringify(Object.assign(copy(b), v2SheetKeysOut(b))));
const withTabs = (tabs) => Object.assign(stale(), { priced_tabs: tabs });
const KEYS_OUT_CASES = {
  stale: stale(),
  plainSheet: spreadsheetBlob("polish"),
  oldPolishEstimate: Object.assign(stale(), { polish_estimate: { areas: [] } }),
  allMarked: withTabs([{ id: "Polish", total: 14224, v2: true }]),
  someMarked: withTabs([{ id: "Polish", total: 14224, v2: true }, { id: "Epoxy", total: 1 }]),
  markIsExactlyTrue: withTabs([{ id: "Polish", total: 14224, v2: "yes" }]),
  emptyTabsStaleTotal: withTabs([]),
  nullTab: withTabs([null]),
  cleanV2: { project_name: "Clean v2", polish_estimate: copy(V2), computed_bid: { lump_sum: 1 } },
  textVersion: Object.assign(stale(), { polish_estimate: { version: "2" } }),
  // Only the keys the draft actually holds: a copy with no `rooms` is not handed a `rooms` to drop.
  someKeysOnly: { project_name: "Few keys", polish_estimate: copy(V2), rooms: [], phase_price: 1,
                  computed_bid: { lump_sum: 1 } },
};
const keysOut = {};
Object.keys(KEYS_OUT_CASES).forEach((name) => {
  const b = KEYS_OUT_CASES[name];
  const before = JSON.stringify(b);
  const patch = v2SheetKeysOut(b);
  keysOut[name] = {
    keys: Object.keys(patch),
    allUndefined: Object.keys(patch).every((k) => patch[k] === undefined),
    originalUntouched: JSON.stringify(b) === before,
    // The law.
    storedEqualsView: sameBlob(storedAfter(b), v2PricingView(b)),
    // Idempotent: once the keys are off the stored copy there is nothing left to take off.
    nothingLeftToTake: Object.keys(v2SheetKeysOut(storedAfter(b))),
  };
});
// A throw is reported, not allowed to end the run: it is one more thing a broken patch can do.
keysOut.notObjects = [null, undefined, "x", 5].map((x) => {
  try { return Object.keys(v2SheetKeysOut(x)); } catch (e) { return "threw"; }
});
// A key named like an object's own machinery (JSON.parse makes both own properties) must not be able
// to name its way into the patch: every key in it is a name from SHEET_PRICING_KEYS.
{
  const hostile = JSON.parse('{"polish_estimate":{"version":2},"rooms":[],"__proto__":{"x":1},'
                             + '"constructor":{"y":1},"computed_bid":{"lump_sum":1}}');
  const patch = v2SheetKeysOut(hostile);
  keysOut.hostile = { keys: Object.keys(patch), inheritsFromBlob: ({}).x !== undefined || ({}).y !== undefined,
                      patchPrototypeIsPlain: Object.getPrototypeOf(patch) === Object.prototype };
}
out.keysOut = keysOut;

// ── 5. what the spreadsheet's snapshot writes ───────────────────────────────────────────────────
// Read out of the real snapshotLumpSumsToState: every `state.<key> =` in it. The list in shared.js
// has to hold all of them (but the engine's own computed_bid and alternate_computed_bid).
const SNAP = L.liftSource(ESTIMATE, "snapshotLumpSumsToState", { indent: "", where: "estimate-review.js" });
const assigned = [];
const re = /\bstate\.([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)/g;
let m;
while ((m = re.exec(SNAP))) if (assigned.indexOf(m[1]) < 0) assigned.push(m[1]);
out.snapshotKeys = assigned;

process.stdout.write(JSON.stringify(out));
