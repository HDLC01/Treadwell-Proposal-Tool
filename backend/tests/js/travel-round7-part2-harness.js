"use strict";
/* ROUND 7, PART 2 (2026-10-21), run on the REAL estimate page: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with the REAL js/bid-model.js beneath it.
 * Every fact below is read off the page after it ran: the model it held, the panels it drew, what it saved. Nothing is a source assertion. test_polish_travel_round7_part2.py holds each one and
 * breaks a COPY of the page or the model one line at a time to prove each fact can change. EVERY REOPEN IS A JSONB REOPEN (tests/js/_jsonb.js): the draft comes back as the drafts table hands it.
 *
 *   L1  `whole`: A WHOLE COUNT IS NOT CALLED ROUNDED. At the library's own Gyp rate ($33.66) a far Gyp crew of 4 for 125 hours is $16,830 of labor; with its drive the sheet's count is
 *       (17,688 - 858) / 33.66 / 10 = 50 nights, which floating point carries as 50.00000000000001. 50 x $70 is $3,500 and the line is charged $3,500, so nothing was rounded: the Review says
 *       nothing under the total, and the working on the Labor step said "$3,500.00, rounded up to $3,500" (it compared the bare product with the charge). Both now ask travelQtyShown.
 *   L2  `same`: ONE COUNT, SHOWN ONE WAY. A far Epoxy crew of 5 for 10 days with its drive (5 x 6.5 x $33 = $1,072.50) counts 50 + 0.5 / 264 = 50.0019 nights the sheet's way. Lodging at $70
 *       needs four places to read true ("50.002" x $70 is $3,500.14, the price worked out $3,500.13) and Per Diem at $45 three, so the Review showed the one count as 50.0019 nights beside
 *       50.002 days. The two lines charge the same count, and it is shown the same way on both, on the Review and in the working. A count the estimator typed on one line is its own.
 *   G1  `gypTyped`, `gypOption`: A GYP BASE'S DRIVE FILLS FROM THE MILES (Hanz's D2 of 2026-10-21, built in part 1), and what it does not do: a drive the estimator TYPED on a Gyp base stays
 *       typed through every distance answer and a reload, and a far Gyp OPTION (a copy of the Gyp sheet) prices its own drive, on its own crew, like any option.
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason.
 *
 * Usage: node travel-round7-part2-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");
const J = require("./_jsonb.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-round7-part2-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "MODEL"]);

// The library's labor lines: Travel (built in), one Epoxy crew line, and one Gyp pour, at $33 or at the library's own Gyp rate ($33.66, the Gyp sheets' C45). The Polish crew is the shipped fallback.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true, default_work_types: [], default_on: true };
const EPOXY_ROW = { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true, default_work_types: ["epoxy"], default_on: true };
const gypRow = (rate) => ({ id: "gyp-pour", name: "Gyp pour", rate: rate, unit: "hours", guys_auto: false, sort: 2, favorite: true, default_work_types: ["gyp"], default_on: true });
const LABOR = [TRAVEL_ROW, EPOXY_ROW, gypRow(33)];
const LABOR_GYP_RATE = [TRAVEL_ROW, EPOXY_ROW, gypRow(33.66)];
const GYP_TAB = 'Gyp (USG 1-8")';

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const GYP = () => draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 });
const EPOXY = () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await flush(); };

/** A page on a draft. `extra.distance` is what the lookup answers (a NEW bid asks by itself, a saved one does not). */
async function open(blob, extra) {
  const opts = Object.assign({ blob: blob, labor: LABOR }, extra || {});
  const b = P.build(opts);
  await b.api.init();
  await settle();
  b.opts = opts;
  return b;
}

// ── reading the page (every reader answers null for what is not there: a break changes a fact, it never crashes the run) ────
const secOf = (m, tab) => (tab === B.ROOT_TAB ? m : (m.tabs || {})[tab]);
const rowIn = (sec) => ((sec && sec.labor instanceof Array ? sec.labor : [])).filter((r) => r && r.id === "travel")[0] || null;
const idxIn = (sec, id) => (sec && sec.labor instanceof Array ? sec.labor.findIndex((r) => r && r.id === id) : -1);
const textOf = (b, sel) => { const el = b.doc.querySelector(sel); return el ? el.textContent : null; };
const has = (b, sel) => !!b.doc.querySelector(sel);
const lumpOf = (blob) => (blob && blob.proposal_lump_sum !== undefined && blob.proposal_lump_sum !== null ? blob.proposal_lump_sum : blob && blob.computed_bid ? blob.computed_bid.lump_sum : null);
const driveText = (r) => (r ? r.guys + " x " + r.days + " = $" + B.laborCost(r) : null);

/** Every section's Travel Labor row, by `tab:kind`, as a short string. */
function driveRows(b) {
  const m = b.api.root();
  return Object.fromEntries(B.sectionsOf(m).map((e) => [e.tab + ":" + e.kind, driveText(rowIn(e.section))]));
}

/** The markers on one section's Travel Labor row: who filled it. */
function marks(b, tab) {
  const r = rowIn(secOf(b.api.root(), tab));
  return r ? { auto: r.guys_auto === true, follow: r.guys_follow || null, seed: r.hours_seed === undefined ? null : r.hours_seed,
    guysTyped: r.guys_typed === true, hoursTyped: r.hours_typed === true } : null;
}

/** Every price the page holds: the root sheet's own bid, each other section's, and what a save writes (the lump sum). A save is forced, so run it after everything else is read. */
function prices(b) {
  const bids = b.api.sectionBids();
  const root = b.api.bid();
  b.api.saveSoon();
  b.clock.fire();
  return { lump: lumpOf(b.store.blob), root: root.total, sections: Object.fromEntries(Object.keys(bids).sort().map((k) => [k, bids[k].total])) };
}

/** What the page saves and prices, as one comparable thing. */
function state(b) {
  return { rows: driveRows(b), price: prices(b) };
}

function typeCrew(b, tab, rowId, guys, days) {
  b.api.show(tab);
  b.api.go(1);
  const i = idxIn(secOf(b.api.root(), tab), rowId);
  [["guys", guys], ["days", days]].forEach((kv) => {
    const sel = '[data-lab="' + i + '"][data-k="' + kv[0] + '"]';
    if (i >= 0 && b.doc.querySelector(sel)) P.typeInto(b, sel, kv[1]);
  });
}

/** A NEW bid on the page: the lookup answers (`distance`), the crew is typed as a person types it on the Labor step, the draft is saved. */
async function newBid(blob, crew, extra) {
  const b = await open(blob, Object.assign({ distance: FAR }, extra || {}));
  b.api.go(1);
  await settle();
  if (crew) typeCrew(b, crew[0], crew[1], crew[2], crew[3]);
  b.api.saveSoon();
  b.clock.fire();
  return b;
}

/** The saved draft reopened on a page of its own, on the Labor step, AS THE DRAFTS TABLE HANDS IT BACK (jsonb key order). The lookup would say 300 miles, which a saved bid never asks for. */
async function reopen(saved, extra) {
  const b = await open(J.reloaded(saved), Object.assign({ distance: { ok: true, miles: 300, reason: "" } }, extra || {}));
  b.api.go(1);
  await settle();
  return b;
}

/** The page's draft, saved now, reopened through the server. */
async function reload(b, extra) {
  b.api.saveSoon();
  b.clock.fire();
  return reopen(clone(b.store.blob), extra);
}

/** The miles typed on the Labor step of the sheet that carries the job's travel. */
async function typeMiles(b, miles) {
  b.api.show(B.travelCarrier(b.api.root()));
  b.api.go(1);
  P.typeInto(b, "[data-dist-miles]", String(miles));
  await settle();
  b.clock.fire();
}

/** A copy of the sheet `tab`, made from its bar. Answers the new sheet's id. */
async function copySheet(b, tab) {
  b.api.show(tab);
  b.api.go(1);
  await settle();
  const before = Object.keys(b.api.root().tabs || {});
  P.clickOn(b, '[data-sh-act="copy"]');
  await settle();
  b.clock.fire();
  return Object.keys(b.api.root().tabs || {}).filter((k) => before.indexOf(k) < 0)[0] || null;
}

/** What the page says about the job's Hotel and Per Diem lines on the section `tab`: on the Labor step the two lines of the working ("Lodging: ... nights ... x $70.00 = ..."), and on the
 *  Review step each line's quantity, rate, total and the words under the total. */
async function travelFacts(b, tab) {
  b.api.show(tab);
  b.api.go(1);
  await settle();
  const how = String(textOf(b, "[data-trv-how]") || "").split("\n");
  const working = (name) => how.filter((l) => l.indexOf(name + ": ") === 0)[0] || null;
  b.api.go(2);
  await settle();
  const one = (k) => ({ qty: textOf(b, '[data-rv="trv.' + k + '.q"]'), rate: textOf(b, '[data-rv="trv.' + k + '.rate"]'), total: textOf(b, '[data-rv="trv.' + k + '.tot"]'),
    up: textOf(b, '[data-rv="trv.' + k + '.up"]') });
  const m = b.api.root();
  return { lodging: one("lodging"), perDiem: one("per_diem"), working: { lodging: working("Lodging"), perDiem: working("Per Diem") },
    nights: B.jobNights(m).count, costs: B.travelCosts(m.travel, secOf(m, tab).labor, B.travelOpts(m, tab)) };
}

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

async function main() {
  // ═══ L1. A WHOLE COUNT IS NOT CALLED ROUNDED ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("whole", async () => {
    const g = await newBid(GYP(), [GYP_TAB, "gyp-pour", "4", "125"], { labor: LABOR_GYP_RATE });
    return Object.assign(await travelFacts(g, GYP_TAB), { drive: driveRows(g) });
  });

  // ═══ L2. ONE COUNT, SHOWN ONE WAY ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("same", async () => {
    const e = await newBid(EPOXY(), ["Epoxy", "epoxy-install", "5", "10"]);
    const both = await travelFacts(e, "Epoxy");
    // a count the estimator typed on one line is that line's own: Lodging typed 10 nights, Per Diem still following the labor
    e.api.show("Epoxy");
    e.api.go(1);
    await settle();
    if (has(e, '[data-trv="lodging"][data-k="qty"]')) P.typeInto(e, '[data-trv="lodging"][data-k="qty"]', "10");
    e.clock.fire();
    const typed = await travelFacts(e, "Epoxy");
    // ...and after a jsonb reload the two rows read as they did
    const r = await reload(e);
    const reloaded = await travelFacts(r, "Epoxy");
    return { both: both, typed: typed, reloaded: reloaded, drive: driveRows(e) };
  });

  // ═══ G1. A DRIVE TYPED ON A GYP BASE STAYS TYPED ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("gypTyped", async () => {
    const g = await newBid(GYP(), [GYP_TAB, "gyp-pour", "4", "120"]);
    const filled = { rows: driveRows(g), marks: marks(g, GYP_TAB) };
    // 3 guys x 5 hours typed on the Gyp sheet's own Travel Labor line
    g.api.show(GYP_TAB);
    g.api.go(1);
    const i = idxIn(secOf(g.api.root(), GYP_TAB), "travel");
    if (i >= 0) { P.typeInto(g, '[data-lab="' + i + '"][data-k="guys"]', "3"); P.typeInto(g, '[data-lab="' + i + '"][data-k="days"]', "5"); }
    g.api.saveSoon();
    g.clock.fire();
    const typed = { rows: driveRows(g), marks: marks(g, GYP_TAB), price: prices(g) };
    const answers = {};
    for (const miles of [300, 50, 190]) { await typeMiles(g, miles); answers[miles] = driveRows(g); }
    const r = await reload(g);
    const reloaded = { rows: driveRows(r), marks: marks(r, GYP_TAB), price: prices(r) };
    await typeMiles(r, 300);
    return { filled: filled, typed: typed, answers: answers, reloaded: reloaded, reloadedAt300: driveRows(r) };
  });

  // ═══ G1. A FAR GYP OPTION PRICES ITS OWN DRIVE ════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("gypOption", async () => {
    const g = await newBid(GYP(), [GYP_TAB, "gyp-pour", "4", "120"]);
    const copy = await copySheet(g, GYP_TAB);
    const made = { copy: copy, rows: driveRows(g), marks: copy ? marks(g, copy) : null };
    // the option's own crew, 6 guys for 100 hours: its drive follows its own guys
    if (copy) typeCrew(g, copy, "gyp-pour", "6", "100");
    g.api.saveSoon();
    g.clock.fire();
    const own = { rows: driveRows(g), price: prices(g), drive: copy ? B.laborCost(rowIn(secOf(g.api.root(), copy))) : null,
      labor: copy ? B.laborTotal(secOf(g.api.root(), copy).labor, g.api.root().conditions) : null };
    const r = await reload(g);
    const reloaded = state(r);
    await typeMiles(g, 300);
    await typeMiles(r, 300);
    const at300 = { session: state(g), reload: state(r) };
    await typeMiles(g, 50);
    return { made: made, own: own, reloaded: reloaded, at300: at300, local: driveRows(g), localMarks: copy ? marks(g, copy) : null };
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
