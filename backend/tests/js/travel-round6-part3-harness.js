"use strict";
/* ROUND 6, PART 3 (2026-10-21), run on the REAL estimate page: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with the REAL js/bid-model.js beneath it.
 * Every fact below is read off the page after it ran: the model it held, the panels it drew, what it saved. Nothing is a source assertion. test_polish_travel_round6_part3.py holds each one and
 * breaks a COPY of the page or the model one line at a time to prove each fact can change. EVERY REOPEN IS A JSONB REOPEN (tests/js/_jsonb.js): the draft comes back as the drafts table hands it.
 *
 *   M3  `m3`: AN OPTION MADE THE CARRIER BY A JOB-TYPE SWITCH BRINGS ITS OWN DRIVE, AS A BASE PICK DOES. Far Polish (4 x 12, 190 miles), an Epoxy sheet added (an option) with a crew of its own
 *       (5 x 10), the x on the Polish carrier's Travel Labor (the job says it has no drive), then Add Travel Labor on the Epoxy option (its own drive, 5 guys x 6.5 hours, filled on its own crew).
 *       Then Epoxy is made the base two ways: the Sheets panel's pick (path A) and the intake's job type (path B). Both end with Epoxy the one base and the job's drive Epoxy's own line; the
 *       pick kept it and dropped the job's answer, the switch took the line off (the release of a blank line nobody typed) and kept the answer: $2,057 apart for the same base. Hanz's decision
 *       of 2026-10-21 stands beside it: after the carrier's x a job-type switch keeps the JOB'S drive removed (no seed, no carry; Add Travel Labor is the way back), which `keeps` holds.
 *   M4  `m4`: THE REVIEW ROW READS TRUE. At the library's own Gyp rate ($33.66) a far Gyp crew of 4 guys for 120 hours is $16,156.80 of labor, which the sheet rounds UP to $16,157 before it
 *       divides: 48.0006 nights, and each line is rounded up to the dollar ($3,361 and $2,161). The Review said "48 nights x $70 = $3,361", and the Labor step's working "48 nights x $70.00
 *       = $3,360.04". Both show the count to as many places as the price needs and say the sheet rounds the dollars up; a whole count (Polish 4 x 12 at $33: 48 x $70 = $3,360) reads as
 *       it did, with nothing added.
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason.
 *
 * Usage: node travel-round6-part3-harness.js <frontend-dir>   ->  one line of JSON
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
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-round6-part3-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "MODEL"]);

// The library's labor lines: Travel (built in), one Epoxy crew line, one Gyp pour at the library's own Gyp rate ($33.66, the Gyp sheets' C45). The Polish crew is the shipped fallback the page adds.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true, default_work_types: [], default_on: true };
const EPOXY_ROW = { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true, default_work_types: ["epoxy"], default_on: true };
const GYP_ROW = { id: "gyp-pour", name: "Gyp pour", rate: 33.66, unit: "hours", guys_auto: false, sort: 2, favorite: true, default_work_types: ["gyp"], default_on: true };
const LABOR = [TRAVEL_ROW, EPOXY_ROW, GYP_ROW];
const GYP_TAB = 'Gyp (USG 1-8")';

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));

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
const flagOf = (b) => b.api.root().no_travel_labor === true;

/** Every section's Travel Labor row, by `tab:kind`, as a short string. */
function driveRows(b) {
  const m = b.api.root();
  return Object.fromEntries(B.sectionsOf(m).map((e) => [e.tab + ":" + e.kind, driveText(rowIn(e.section))]));
}

/** Every price the page holds: the root sheet's own bid, each other section's, and what a save writes (the lump sum). A save is forced, so run it after everything else is read. */
function prices(b) {
  const bids = b.api.sectionBids();
  const root = b.api.bid();
  b.api.saveSoon();
  b.clock.fire();
  return { lump: lumpOf(b.store.blob), root: root.total, sections: Object.fromEntries(Object.keys(bids).sort().map((k) => [k, bids[k].total])) };
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
async function newBid(blob, crew, distance) {
  const b = await open(blob, { distance: distance || FAR });
  b.api.go(1);
  await settle();
  if (crew) typeCrew(b, crew[0], crew[1], crew[2], crew[3]);
  b.clock.fire();
  return { saved: clone(b.store.blob), page: b };
}

/** The saved draft reopened on a page of its own, on the Labor step, AS THE DRAFTS TABLE HANDS IT BACK (jsonb key order). The lookup would say 300 miles, which a saved bid never asks for. */
async function reopen(saved, extra) {
  const b = await open(J.reloaded(saved), Object.assign({ distance: { ok: true, miles: 300, reason: "" } }, extra || {}));
  b.api.go(1);
  await settle();
  return b;
}

async function addSheet(b, sheet) {
  b.api.go(1);
  if (b.doc.querySelector('[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]');
  P.clickOn(b, '[data-sh-act="add"][data-sh-sheet="' + String(sheet).replace(/"/g, "&quot;") + '"]');
  await settle();
  b.clock.fire();
}

async function makeBase(b, value) {
  b.doc.fire("change", { target: P.need(b, '[data-sh-base="' + String(value).replace(/"/g, "&quot;") + '"]') });
  P.clickOn(b, '[data-sh-act="base-yes"]');
  await settle();
  b.clock.fire();
}

/** The x on the Travel Labor line of the section `tab`, pressed on the page (the section is put on show first). Answers false when the page draws no such x. */
async function pressX(b, tab) {
  b.api.show(tab);
  b.api.go(1);
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  if (i < 0 || !has(b, '[data-del-lab="' + i + '"]')) return false;
  P.clickOn(b, '[data-del-lab="' + i + '"]');
  await settle();
  b.api.saveSoon();
  b.clock.fire();
  return true;
}

/** Add Travel Labor, pressed on the section `tab`. Answers whether the page drew the button there. */
async function pressAdd(b, tab) {
  b.api.show(tab);
  b.api.go(1);
  if (!has(b, "[data-add-travel]")) return false;
  P.clickOn(b, "[data-add-travel]");
  await settle();
  b.api.saveSoon();
  b.clock.fire();
  return true;
}

/** What the page says about the job's Hotel and Per Diem lines on the section `tab`: on the Review step the quantity, the total and the words under the total; on the Labor step the two
 *  lines of the working ("Lodging: ... nights ... x $70.00 = ..."). */
async function reviewFacts(b, tab) {
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
  // ═══ M3. AN OPTION MADE THE CARRIER BRINGS ITS OWN DRIVE, BY A BASE PICK AND BY A JOB-TYPE SWITCH ALIKE ═════════════════════════════════════════════════════════════════
  await section("m3", async () => {
    const s = await newBid(draftOf("polish", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" }), ["Polish", "polishing", "4", "12"]);
    const b = await reopen(s.saved);
    await addSheet(b, "Epoxy");
    typeCrew(b, "Epoxy", "epoxy-install", "5", "10");
    b.api.saveSoon();
    b.clock.fire();
    const x = await pressX(b, B.ROOT_TAB);
    const added = await pressAdd(b, "Epoxy");
    const start = { x: x, added: added, flag: flagOf(b), rows: driveRows(b) };
    const saved = clone(b.store.blob);
    // A: the Sheets panel's pick
    const a = await reopen(saved);
    await makeBase(a, "Epoxy");
    const pick = { carrier: B.travelCarrier(a.api.root()), flag: flagOf(a), rows: driveRows(a), price: prices(a) };
    // B: the intake's job type, reaching the estimate page on the saved draft
    const j = await reopen(Object.assign(clone(saved), { work_type: "epoxy" }));
    j.api.saveSoon();
    j.clock.fire();
    const sw = { carrier: B.travelCarrier(j.api.root()), flag: flagOf(j), rows: driveRows(j), price: prices(j) };
    // ...and each path's draft reopened plain, and then the miles corrected to 300: the two still agree
    const after = async (blob) => {
      const r = await reopen(blob);
      const quiet = { armed: r.clock.armed(), saves: r.rec.saves.length };
      const rows = driveRows(r);
      const p = prices(r);
      r.api.show(B.travelCarrier(r.api.root()));
      r.api.go(1);
      P.typeInto(r, "[data-dist-miles]", "300");
      await settle();
      return { quiet: quiet, rows: rows, price: p, at300: { rows: driveRows(r), price: prices(r) } };
    };
    return { start: start, pick: pick, switched: sw, pickReopened: await after(clone(a.store.blob)), switchReopened: await after(clone(j.store.blob)) };
  });

  // HANZ'S DECISION OF 2026-10-21, beside M3: after the carrier's x a job-type switch keeps the JOB's drive removed. A far Polish bid, the x on its carrier, then the job type Epoxy: the new Epoxy
  // section is the carrier and is seeded no line (no seed), none is carried to it (no carry), the answer is still said, and Add Travel Labor is drawn on it (the way back).
  await section("keeps", async () => {
    const s = await newBid(draftOf("polish", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" }), ["Polish", "polishing", "4", "12"]);
    const b = await reopen(s.saved);
    const x = await pressX(b, B.ROOT_TAB);
    const j = await reopen(Object.assign(clone(b.store.blob), { work_type: "epoxy" }));
    j.api.saveSoon();
    j.clock.fire();
    const car = B.travelCarrier(j.api.root());
    j.api.show(car);
    j.api.go(1);
    return { x: x, carrier: car, flag: flagOf(j), rows: driveRows(j), addShown: has(j, "[data-add-travel]") };
  });

  // ═══ M4. THE REVIEW'S HOTEL AND PER DIEM ROWS READ TRUE ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("m4", async () => {
    // a far Gyp bid at the library's own Gyp rate: 4 guys for 120 hours
    const g = await newBid(draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 }), [GYP_TAB, "gyp-pour", "4", "120"]);
    const gyp = await reviewFacts(g.page, GYP_TAB);
    // a far Polish bid, 4 guys for 12 days at $33 and a drive of 4 x 6.5: 48 nights exactly, 48 x $70 = $3,360
    const p = await newBid(draftOf("polish", { polish_sf: 5000 }), ["Polish", "polishing", "4", "12"]);
    const polish = await reviewFacts(p.page, B.ROOT_TAB);
    return { gyp: gyp, polish: polish };
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
