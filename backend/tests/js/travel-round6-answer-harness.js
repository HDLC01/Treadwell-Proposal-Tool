"use strict";
/* ROUND 6, PART 2, THE "NO TRAVEL LABOR" ANSWER (2026-10-20), run on the REAL estimate page: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with the
 * REAL js/bid-model.js beneath it. Every fact below is read off the page after it ran: the model it held, the panels it drew, what it saved. Nothing is a source assertion.
 * test_polish_travel_round6_answer.py holds each one to what Hanz decided and breaks a COPY of the page or the model one line at a time to prove each fact can change.
 *
 * EVERY RELOAD HERE IS A JSONB RELOAD. The drafts table stores the blob as jsonb, which hands an object's keys back sorted by their length and then their bytes ("Epoxy" after "Copy1",
 * "Gyp (USG 1-8\")" after both), so a draft that is opened again is not the object the page saved. `jsonbOrder` re-keys every blob that way before the page meets it again, on every
 * `reopen`, so no scenario below can pass on the insertion order of a session.
 *
 * HANZ'S DECISIONS: 2026-10-12 (match Kyle's workbook EXACTLY per tab, quirks included) and 2026-10-20 (far jobs fill the drive, and fill the hotel and per diem nights automatically). The
 * round-5 verification found that a session and a reload of the SAME draft priced $783 apart, and traced it to one line: migrateModel appended a blank Travel Labor row to the root
 * whenever the root had none, even when the root was off (an Epoxy job's Polish) or an option. This file holds the whole of what followed:
 *
 *   X1  `rootCause`, `f1`, `f2`, `s1`: THE BLANK ROW. migrateModel appends the blank Travel row only to a root that CARRIES the job's travel (and the job has not said it has no drive).
 *       The audit's own sequences, run both ways (a session, and a jsonb reload of the draft it saved), now agree: F1 (far Combo, switched to Epoxy, the x on the Epoxy sheet's Travel Labor,
 *       back to Combo, 300 miles) and F2 (far Polish, the x, an Epoxy sheet added and made the base, Add Travel Labor on it, 300 miles, the Polish option's price).
 *   X2  `answer`: THE ANSWER BELONGS TO THE SHEET. The x on the CARRIER's Travel Labor says the job has no drive (the root's `no_travel_labor`); the x on an OPTION's says only that
 *       the option has none and records nothing on the job; the x on a base that does not carry the travel (a leftover row) says nothing. Add Travel Labor is drawn on any sheet that
 *       can hold a drive and has none (the carrier, or an option) and takes back only that sheet's answer. A job-type switch after the carrier's x HONOURS it (the new carrier is not
 *       seeded a row), and a saved bid's flag, which the round-5 x set for ANY row, is read as what it is now (the job's) and dropped when the carrier holds a row. `migrate` is the table.
 *   X3  `keyboard`: the x on a labor line, pressed from the keyboard, leaves focus on a control that exists afterwards.
 *   X4  `handoff` and `holes`: the round-5 lows that reproduce. (b) A Lodging or Per Diem line switched off by hand was filled by a far answer: an answer leaves it alone now and switching it ON fills
 *       it. (c) A labor or takeoff list holding a null threw on open: a null reads as no row. (a), a typed drive edit lost when the base flips back, is left (docs/v2-architecture.md).
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason; the mutation runs in the test count a section error as a
 * failure of the mutation, never as the mutation being noticed.
 *
 * Usage: node travel-round6-answer-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

/** What the drafts table's jsonb column hands back: every object's keys sorted by their length in bytes, then by the bytes (arrays keep their order). */
function jsonbOrder(v) {
  if (Array.isArray(v)) return v.map(jsonbOrder);
  if (v && typeof v === "object") {
    const out = {};
    Object.keys(v).sort((a, b) => {
      const la = Buffer.byteLength(a), lb = Buffer.byteLength(b);
      return la !== lb ? la - lb : Buffer.compare(Buffer.from(a), Buffer.from(b));
    }).forEach((k) => { out[k] = jsonbOrder(v[k]); });
    return out;
  }
  return v;
}

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-round6-answer-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "MODEL"]);

// The library's labor lines: Travel (built in), one Epoxy crew line, one Gyp pour. The Polish crew is the shipped fallback the page adds. Every crew is paid $33 an hour.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true, default_work_types: [], default_on: true };
const EPOXY_ROW = { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true, default_work_types: ["epoxy"], default_on: true };
const GYP_ROW = { id: "gyp-pour", name: "Gyp pour", rate: 33, unit: "hours", guys_auto: false, sort: 2, favorite: true, default_work_types: ["gyp"], default_on: true };
const LABOR = [TRAVEL_ROW, EPOXY_ROW, GYP_ROW];

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const SF = { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" };
const comboDraft = () => draftOf("combo", SF);
const polishDraft = () => draftOf("polish", { polish_sf: 5000 });
const epoxyDraft = () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const CREW = { polish: ["Polish", "polishing", "4", "12"], epoxy: ["Epoxy", "epoxy-install", "4", "12"] };

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
const boxOf = (b, sel) => { const el = b.doc.querySelector(sel); return el ? String(el.value) : null; };
const textOf = (b, sel) => { const el = b.doc.querySelector(sel); return el ? el.textContent : null; };
const has = (b, sel) => !!b.doc.querySelector(sel);
const lumpOf = (blob) => (blob && blob.proposal_lump_sum !== undefined && blob.proposal_lump_sum !== null ? blob.proposal_lump_sum : blob && blob.computed_bid ? blob.computed_bid.lump_sum : null);
const rowFacts = (r) => (r ? { guys: r.guys, days: r.days, auto: !!r.guys_auto, follow: r.guys_follow === undefined ? null : r.guys_follow,
  seed: r.hours_seed === undefined ? null : r.hours_seed, typed: r.guys_typed === true, hoursTyped: r.hours_typed === true, on: r.enabled !== false, cost: B.laborCost(r) } : null);
/** The drive as a short string: "4 x 6.5 = $858", or null for no line. */
const driveText = (r) => (r ? r.guys + " x " + r.days + " = $" + B.laborCost(r) : null);

/** Every price the page holds: the root sheet's own bid, each other section's, and what a save writes (the lump sum). A save is forced, so run it after everything else is read. */
function prices(b) {
  const m = b.api.root();
  const bids = b.api.sectionBids();
  const root = b.api.bid();
  b.api.saveSoon();
  b.clock.fire();
  return { lump: lumpOf(b.store.blob), root: root.total, sections: Object.fromEntries(Object.keys(bids).sort().map((k) => [k, bids[k].total])), miles: m.distance ? m.distance.miles : null };
}

/** Every section's Travel Labor row, by `tab:kind`, as a short string. */
function driveRows(b) {
  const m = b.api.root();
  return Object.fromEntries(B.sectionsOf(m).map((e) => [e.tab + ":" + e.kind, driveText(rowIn(e.section))]));
}

/** The root's `no_travel_labor`, as the page holds it. */
const flagOf = (b) => b.api.root().no_travel_labor === true;
const savedFlag = (blob) => !!(blob && blob.polish_estimate && blob.polish_estimate.no_travel_labor === true);

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
  const b = await open(jsonbOrder(clone(saved)), Object.assign({ distance: { ok: true, miles: 300, reason: "" } }, extra || {}));
  b.api.go(1);
  await settle();
  return b;
}

/** The miles typed on the Labor step of the sheet that carries the job's travel, where the box is. */
async function typeMiles(b, v) {
  b.api.show(B.travelCarrier(b.api.root()));
  b.api.go(1);
  P.typeInto(b, "[data-dist-miles]", v);
  await settle();
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

async function copyActive(b) {
  P.clickOn(b, '[data-sh-act="copy"]');
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

const addShown = (b, tab) => { b.api.show(tab); b.api.go(1); return has(b, "[data-add-travel]"); };

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

/** What one pass over a draft shows: the rows, the price, and (typed afterwards) the 300 mile answer. `b` is a page on the draft. */
async function readBid(b) {
  const rows = driveRows(b);
  const flag = flagOf(b);
  const carrier = B.travelCarrier(b.api.root());
  const open = prices(b);
  await typeMiles(b, "300");
  return { carrier: carrier, flag: flag, rows: rows, open: open, at300: { rows: driveRows(b), price: prices(b) } };
}

async function main() {
  // ═══ X1. THE ROOT CAUSE: migrateModel's blank Travel row ═══════════════════════════════════════════════════════════════════════════════════════════
  // The saved draft right after the job type is switched from Combo to Epoxy holds NO Travel row on the (off) Polish root: the row went with the carrier. migrateModel then put a blank one
  // back on every open (the root had none and the job had not said no), and the next far answer filled and priced it: the session had no such row, the reload did.
  await section("rootCause", async () => {
    const s = await newBid(comboDraft(), CREW.polish);
    const sw = await reopen(Object.assign(clone(s.saved), { work_type: "epoxy" }));
    sw.api.saveSoon();
    sw.clock.fire();
    const afterSwitch = clone(sw.store.blob);
    const rootRows = (blob) => (B.migrateModel(jsonbOrder(clone(blob.polish_estimate))).labor || []).filter((r) => r.id === "travel").length;
    const res = { savedRootRows: ((afterSwitch.polish_estimate.labor || []).filter((r) => r.id === "travel")).length, migratedRootRows: rootRows(afterSwitch),
      savedKinds: B.sectionsOf(B.migrateModel(clone(afterSwitch.polish_estimate))).map((e) => e.tab + ":" + e.kind), flag: savedFlag(afterSwitch) };
    // a plain reopen of that draft writes nothing and moves no row: what the page holds is what was saved
    const again = await reopen(afterSwitch);
    res.reopenRows = driveRows(again);
    res.reopenQuiet = { armed: again.clock.armed(), saves: again.rec.saves.length };
    // THE TABLE: a root that does not carry the job's travel is never given the row, whatever it holds; a root that does carry it still is (a stale draft saved before 2026-09-12 has none).
    const crew = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 }];
    const section0 = (kind, rows) => ({ layout: "epoxy", kind: kind, profile: "epoxy@1", takeoff: [], labor: rows, contingency: 0, fees: 0, totals: {} });
    const epoxyRows = [{ id: "epoxy-install", label: "Epoxy install", guys: 2, days: 3, rate: 33 }, { id: "travel", label: "Travel Labor", guys: 2, days: 6.5, rate: 33, unit: "hours", guys_auto: false }];
    const root = (over) => Object.assign({ version: 2, takeoff: [], labor: clone(crew), conditions: { local: true }, contingency: 0, fees: 0, totals: {} }, over || {});
    const count = (m) => (m.labor || []).filter((r) => r.id === "travel").length;
    const table = {
      "an off root (an Epoxy job's Polish)": root({ kind: "off", tabs: { Epoxy: section0("base", clone(epoxyRows)) } }),
      "a root that is an option beside an Epoxy base": root({ kind: "option", tabs: { Epoxy: section0("base", clone(epoxyRows)) } }),
      "a stale draft with no sections (saved before 2026-09-12)": root({}),
      "a root that is the base beside an Epoxy option": root({ tabs: { Epoxy: section0("option", clone(epoxyRows)) } }),
      "a root whose sections cannot be read": root({ tabs: { Epoxy: Object.assign(section0("base", clone(epoxyRows)), { layout: null }) } }),
      "a root that carries the travel and said it has no drive": root({ no_travel_labor: true }),
      "an off root that carries nothing and said it has no drive": root({ kind: "off", no_travel_labor: true, tabs: { Epoxy: section0("base", []) } }),
    };
    res.table = Object.fromEntries(Object.keys(table).map((k) => [k, count(B.migrateModel(clone(table[k])))]));
    return res;
  });

  // F1. far Combo (4 x 12, 190 miles) -> intake: job type Epoxy -> [A: nothing | B: the page is refreshed once] -> x on the Epoxy sheet's Travel Labor -> intake: Combo again -> 300 miles typed.
  const f1 = async (refresh) => {
    const s = await newBid(comboDraft(), CREW.polish);
    let p2 = await reopen(Object.assign(clone(s.saved), { work_type: "epoxy" }));
    p2.api.saveSoon();
    p2.clock.fire();
    if (refresh) p2 = await reopen(p2.store.blob);
    const pressed = await pressX(p2, "Epoxy");
    const flag = savedFlag(p2.store.blob);
    const p3 = await reopen(Object.assign(clone(p2.store.blob), { work_type: "combo" }));
    return Object.assign({ pressed: pressed, flagAfterX: flag }, await readBid(p3));
  };
  await section("f1", async () => ({ A: await f1(false), B: await f1(true) }));

  // THE ORACLE for F1 and F2: the same far Combo (and Polish) with the x pressed on the carrier's Travel Labor and nothing else done. Whatever the bid is after any sequence that ends with no
  // drive on a Combo, it prices as this does.
  await section("oracle", async () => {
    const c = await newBid(comboDraft(), CREW.polish);
    const b = await reopen(c.saved);
    const pressed = await pressX(b, B.ROOT_TAB);
    const saved = clone(b.store.blob);
    const again = await reopen(saved);
    return { combo: Object.assign({ pressed: pressed, flagAfterX: savedFlag(saved) }, await readBid(again)) };
  });

  // F2. far Polish (4 x 12) -> x on its Travel Labor -> an Epoxy sheet added and made the base -> Add Travel Labor on the Epoxy carrier -> [reload] -> 300 miles typed: the Polish OPTION.
  await section("f2", async () => {
    const s = await newBid(polishDraft(), CREW.polish);
    const b = await reopen(s.saved);
    const x = await pressX(b, B.ROOT_TAB);
    await addSheet(b, "Epoxy");
    await makeBase(b, "Epoxy");
    const flagBeforeAdd = flagOf(b);
    const added = await pressAdd(b, "Epoxy");
    b.api.saveSoon();
    b.clock.fire();
    const saved = clone(b.store.blob);
    const flagAfterAdd = flagOf(b);
    await typeMiles(b, "300");
    const session = { rows: driveRows(b), price: prices(b) };
    const r = await reopen(saved);
    const reopened = driveRows(r);
    await typeMiles(r, "300");
    return { pressedX: x, flagBeforeAdd: flagBeforeAdd, added: added, flagAfterAdd: flagAfterAdd, session: session, reopened: reopened, reloaded: { rows: driveRows(r), price: prices(r) } };
  });

  // S1 (the auditor's second route): far Polish -> an Epoxy sheet added as an alternate -> intake: job type Epoxy -> [A: nothing | B: refreshed once] -> x on the Epoxy carrier's Travel Labor
  // -> intake: job type back to Polish -> 300 miles typed.
  const s1 = async (refresh) => {
    const s = await newBid(draftOf("polish", SF), CREW.polish);
    const p1 = await reopen(s.saved);
    await addSheet(p1, "Epoxy");
    p1.api.saveSoon();
    p1.clock.fire();
    let p2 = await reopen(Object.assign(clone(p1.store.blob), { work_type: "epoxy" }));
    p2.api.saveSoon();
    p2.clock.fire();
    const afterSwitch = { carrier: B.travelCarrier(p2.api.root()), rows: driveRows(p2) };
    if (refresh) p2 = await reopen(p2.store.blob);
    const pressed = await pressX(p2, "Epoxy");
    const flag = savedFlag(p2.store.blob);
    const p3 = await reopen(Object.assign(clone(p2.store.blob), { work_type: "polish" }));
    return Object.assign({ afterSwitch: afterSwitch, pressed: pressed, flagAfterX: flag }, await readBid(p3));
  };
  await section("s1", async () => ({ A: await s1(false), B: await s1(true) }));

  // ═══ X2. THE ANSWER BELONGS TO THE SHEET ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("answer", async () => {
    const res = {};
    // 1. THE CARRIER'S x says the job has no drive: it stays away through a reload, Add Travel Labor is drawn on the carrier, and pressing it takes the answer back.
    {
      const s = await newBid(polishDraft(), CREW.polish);
      const b = await reopen(s.saved);
      const before = { rows: driveRows(b), price: prices(b).lump };
      const pressed = await pressX(b, B.ROOT_TAB);
      const afterX = { flag: flagOf(b), rows: driveRows(b), addShown: addShown(b, B.ROOT_TAB), saved: savedFlag(b.store.blob) };
      const r = await reopen(b.store.blob);
      const reloaded = { flag: flagOf(r), rows: driveRows(r), addShown: addShown(r, B.ROOT_TAB), quiet: { armed: r.clock.armed(), saves: r.rec.saves.length } };
      const added = await pressAdd(r, B.ROOT_TAB);
      res.carrier = { before: before, pressed: pressed, afterX: afterX, reloaded: reloaded, added: added, afterAdd: { flag: flagOf(r), rows: driveRows(r), saved: savedFlag(r.store.blob), price: prices(r).lump } };
    }
    // 2. AN OPTION'S x says only that the option has none. A far Polish bid copied as an option (Copy1, its own Travel Labor row, the copy of the carrier's): its x records nothing on the job,
    //    the carrier keeps its row, a reload does not bring the option's back, Add Travel Labor is drawn on the option, and pressing it adds a row to the option alone.
    {
      const s = await newBid(polishDraft(), CREW.polish);
      const b = await reopen(s.saved);
      await copyActive(b);
      const copy = B.sectionsOf(b.api.root()).filter((e) => e.kind === "option")[0].tab;
      const before = { rows: driveRows(b), addOnOption: addShown(b, copy), addOnCarrier: addShown(b, B.ROOT_TAB) };
      const pressed = await pressX(b, copy);
      const afterX = { flag: flagOf(b), rows: driveRows(b), saved: savedFlag(b.store.blob), addOnOption: addShown(b, copy), addOnCarrier: addShown(b, B.ROOT_TAB) };
      const r = await reopen(b.store.blob);
      const reloaded = { flag: flagOf(r), rows: driveRows(r), addOnOption: addShown(r, copy) };
      const added = await pressAdd(r, copy);
      res.option = { copy: copy, before: before, pressed: pressed, afterX: afterX, reloaded: reloaded, added: added,
        afterAdd: { flag: flagOf(r), rows: driveRows(r), saved: savedFlag(r.store.blob) } };
      // ...and the answer that comes after: 300 miles reaches the option's new row by its own crew, in the session and after a reload
      await typeMiles(r, "300");
      const r2 = await reopen(r.store.blob);
      await typeMiles(r2, "300");
      res.option.at300 = { session: { rows: driveRows(r), price: prices(r) }, reloaded: { rows: driveRows(r2), price: prices(r2) } };
    }
    // 3. THE ROOT THAT IS AN OPTION (a far Polish bid with an Epoxy sheet made the base: the demoted Polish keeps its own row): its x is the option's, not the job's.
    {
      const s = await newBid(polishDraft(), CREW.polish);
      const b = await reopen(s.saved);
      await addSheet(b, "Epoxy");
      await makeBase(b, "Epoxy");
      const before = { rows: driveRows(b), flag: flagOf(b), carrier: B.travelCarrier(b.api.root()) };
      const pressed = await pressX(b, B.ROOT_TAB);
      const afterX = { flag: flagOf(b), rows: driveRows(b), saved: savedFlag(b.store.blob), addOnOption: addShown(b, B.ROOT_TAB), addOnCarrier: addShown(b, "Epoxy") };
      const r = await reopen(b.store.blob);
      const reloaded = { flag: flagOf(r), rows: driveRows(r), addOnOption: addShown(r, B.ROOT_TAB) };
      const added = await pressAdd(r, B.ROOT_TAB);
      res.optionRoot = { before: before, pressed: pressed, afterX: afterX, reloaded: reloaded, added: added, afterAdd: { flag: flagOf(r), rows: driveRows(r), saved: savedFlag(r.store.blob) } };
    }
    // 4. A BASE THAT DOES NOT CARRY THE TRAVEL (a leftover row on a Combo's Epoxy base, typed by the estimator): its x says nothing about the job, and Add Travel Labor is never drawn there
    //    (the job's drive is charged once, on the carrier).
    {
      const s = await newBid(comboDraft(), CREW.polish);
      const stray = clone(s.saved);
      stray.polish_estimate.tabs.Epoxy.labor.push({ id: "travel", label: "Travel Labor", guys: "2", days: "3", rate: 33, unit: "hours", guys_auto: false, guys_typed: true, hours_typed: true });
      const b = await reopen(stray);
      const before = { rows: driveRows(b), addOnStray: addShown(b, "Epoxy") };
      const pressed = await pressX(b, "Epoxy");
      const afterX = { flag: flagOf(b), rows: driveRows(b), saved: savedFlag(b.store.blob), addOnStray: addShown(b, "Epoxy") };
      const r = await reopen(b.store.blob);
      res.stray = { before: before, pressed: pressed, afterX: afterX, reloaded: { flag: flagOf(r), rows: driveRows(r) } };
    }
    // 5. AN OPTION'S ADD TAKES BACK ONLY THE OPTION'S ANSWER, AND FILLS THE LINE ON THE OPTION'S OWN CREW. Far Polish (4 x 12) copied as an option whose Polishing the estimator made 2 x 12; the x on
    //    the CARRIER's line (the job says it has no drive), the x on the option's, then Add Travel Labor on the option: the job's answer is still said (flag on, the carrier has no line), and the
    //    option's new line is 2 guys x 6.5 hours (its own crew) = $429, not the base's 4.
    {
      const s = await newBid(polishDraft(), CREW.polish);
      const b = await reopen(s.saved);
      await copyActive(b);
      const copy = B.sectionsOf(b.api.root()).filter((e) => e.kind === "option")[0].tab;
      typeCrew(b, copy, "polishing", "2", "12");
      b.api.saveSoon();
      b.clock.fire();
      await pressX(b, B.ROOT_TAB);
      await pressX(b, copy);
      const before = { flag: flagOf(b), rows: driveRows(b), addOnOption: addShown(b, copy), addOnCarrier: addShown(b, B.ROOT_TAB) };
      const added = await pressAdd(b, copy);
      const afterAdd = { flag: flagOf(b), rows: driveRows(b), saved: savedFlag(b.store.blob) };
      const r = await reopen(b.store.blob);
      res.optionKeepsJobAnswer = { before: before, added: added, afterAdd: afterAdd, reloaded: { flag: flagOf(r), rows: driveRows(r) } };
    }
    // 6. THE JOB IS HANDED A LINE: a far Polish bid copied as an option (its own line), the x on the carrier (the job says it has no drive), then the option made the base: the new carrier holds a line
    //    of its own, so the job has a drive and the answer is gone (it was the carrier's, and the carrier is another section now). The model's pickBase says it too, on a bid the page has not
    //    settled, and a reload agrees.
    {
      const s = await newBid(polishDraft(), CREW.polish);
      const b = await reopen(s.saved);
      await copyActive(b);
      const copy = B.sectionsOf(b.api.root()).filter((e) => e.kind === "option")[0].tab;
      await pressX(b, B.ROOT_TAB);
      const said = { flag: flagOf(b), rows: driveRows(b) };
      const model = clone(b.api.root());
      const picked = B.pickBase(model, [copy], { state: {} });
      const modelSays = { flag: picked.model.no_travel_labor === true, inputFlag: model.no_travel_labor === true };
      await makeBase(b, copy);
      const after = { flag: flagOf(b), rows: driveRows(b), carrier: B.travelCarrier(b.api.root()), saved: savedFlag(b.store.blob) };
      const r = await reopen(b.store.blob);
      res.promoted = { said: said, modelSays: modelSays, after: after, reloaded: { flag: flagOf(r), rows: driveRows(r) } };
    }
    // 7. A NEW EPOXY BID'S OFF ROOT HOLDS THE SHIPPED FOUR ROWS (it is not seeded: it is off), Travel among them, blank. The x on the Epoxy carrier says the job has no drive; switched to Combo, the root
    //    becomes the carrier and its blank line is taken off it (the distance on file would have filled it to $858 and put the drive back); a reload agrees.
    {
      const s = await newBid(epoxyDraft(), CREW.epoxy);
      const b = await reopen(s.saved);
      const start = { rows: driveRows(b), flag: flagOf(b) };
      await pressX(b, "Epoxy");
      const c = await reopen(Object.assign(clone(b.store.blob), { work_type: "combo" }));
      const toCombo = { carrier: B.travelCarrier(c.api.root()), flag: flagOf(c), rows: driveRows(c), addOnCarrier: addShown(c, B.travelCarrier(c.api.root())), price: prices(c).lump };
      const r = await reopen(c.store.blob);
      res.newEpoxy = { start: start, toCombo: toCombo, reloaded: { flag: flagOf(r), rows: driveRows(r), price: prices(r).lump } };
    }
    // 8. THE MODEL'S OWN ANSWERS, with no page to settle or re-sync anything after them (the page repairs some of what a wrong model does, so these are read straight off the model).
    {
      const s = await newBid(polishDraft(), CREW.polish);
      const saved = s.saved.polish_estimate;
      const m0 = B.migrateModel(clone(saved));
      const withCopy = B.copySection(m0, B.ROOT_TAB, { state: {} }).model;
      const copy = B.sectionsOf(withCopy).filter((e) => e.kind === "option")[0].tab;
      const optionRow = (m) => rowIn(m.tabs[copy]);
      // an option whose crew is 2 x 12 (the base's is 4 x 12) and that holds no Travel Labor line of its own
      const m1 = clone(withCopy);
      m1.tabs[copy].labor.forEach((r) => { if (r.id === "polishing") r.guys = "2"; });
      m1.tabs[copy].labor = m1.tabs[copy].labor.filter((r) => r.id !== "travel");
      const optionWithoutLine = B.travelLaborCanBeAdded(m1, copy);
      const added = B.addTravelLabor(m1, B.freshTravelRow(LABOR, 33), copy);
      const addOnOption = { added: added, guys: optionRow(m1) ? optionRow(m1).guys : null, hours: optionRow(m1) ? optionRow(m1).days : null, flag: m1.no_travel_labor === true };
      // ...a sheet that already holds a line, a base that does not carry the travel (a Combo's Epoxy) and a sheet the bid does not have are refused
      const comboModel = B.migrateModel(clone((await newBid(comboDraft(), CREW.polish)).saved.polish_estimate));
      // (a carrier that holds no line, so that a sheet the bid does not have would be given one if the answer fell back to the carrier)
      const carrierWithoutLine = clone(comboModel);
      carrierWithoutLine.labor = carrierWithoutLine.labor.filter((r) => r.id !== "travel");
      const refused = { holdsOne: B.addTravelLabor(clone(withCopy), B.freshTravelRow(LABOR, 33), copy), strayBase: B.addTravelLabor(clone(comboModel), B.freshTravelRow(LABOR, 33), "Epoxy"),
        unknownTab: B.addTravelLabor(carrierWithoutLine, B.freshTravelRow(LABOR, 33), "Nope") };
      // the x on an option when the CARRIER holds no line (and the job has not said so): the option's x says nothing about the job; the carrier's says it
      const m3 = clone(withCopy);
      m3.labor = m3.labor.filter((r) => r.id !== "travel");
      const m4 = clone(m3);
      const optionX = { said: B.travelLaborRemoved(m3, copy), flag: m3.no_travel_labor === true };
      const carrierX = { said: B.travelLaborRemoved(m4, B.ROOT_TAB), flag: m4.no_travel_labor === true };
      const canAdd = { carrier: B.travelLaborCanBeAdded(m3, B.ROOT_TAB), option: B.travelLaborCanBeAdded(m3, copy), carrierWithLine: B.travelLaborCanBeAdded(clone(withCopy), B.ROOT_TAB), optionWithLine: B.travelLaborCanBeAdded(clone(withCopy), copy), optionWithoutLine: optionWithoutLine,
        strayBase: B.travelLaborCanBeAdded(clone(comboModel), "Epoxy"), unknown: B.travelLaborCanBeAdded(clone(comboModel), "Nope") };
      // a job that said it has no drive is not seeded one on the section a job-type switch adds (a job that did not say so is)
      const seed = (flag) => {
        const m = B.migrateModel(clone(saved));
        if (flag) m.no_travel_labor = true;
        let out = B.sectionsForJob(m, "epoxy", { rules: [] });
        out = B.seedNewSections(out, { saved: saved, laborRows: LABOR, laborRate: 33, sf: { Epoxy: [6000, ""] }, lf: { Epoxy: [300, ""] }, asms: [], items: [], reserved: [], split: false });
        return rowIn(out.tabs.Epoxy) !== null;
      };
      res.direct = { copy: copy, addOnOption: addOnOption, refused: refused, optionX: optionX, carrierX: carrierX, canAdd: canAdd, seeded: { said: seed(true), notSaid: seed(false) } };
    }
    return res;
  });

  // A JOB TYPE SWITCHED AFTER THE CARRIER'S x HONOURS IT (decided 2026-10-20: "the job has no drive" is the job's, so the new carrier is not seeded a row and no row is carried to it; Add
  // Travel Labor on the carrier takes the answer back). Far Polish -> x -> intake: Epoxy (a new section) -> [reload] -> intake: Polish again. The session equals a reload at every step.
  await section("switchAfterX", async () => {
    const s = await newBid(polishDraft(), CREW.polish);
    const b = await reopen(s.saved);
    const priceWith = prices(b).lump;
    await pressX(b, B.ROOT_TAB);
    const priceAfterX = prices(b).lump;
    const afterX = clone(b.store.blob);
    const e = await reopen(Object.assign(clone(afterX), { work_type: "epoxy" }));
    typeCrew(e, "Epoxy", "epoxy-install", "4", "12");
    e.api.saveSoon();
    e.clock.fire();
    const toEpoxy = { carrier: B.travelCarrier(e.api.root()), flag: flagOf(e), rows: driveRows(e), addOnCarrier: addShown(e, "Epoxy"), price: prices(e).lump, saved: savedFlag(e.store.blob) };
    const er = await reopen(e.store.blob);
    const quiet = { armed: er.clock.armed(), saves: er.rec.saves.length };       // read BEFORE prices(), which forces a save
    const epoxyReloaded = { flag: flagOf(er), rows: driveRows(er), price: prices(er).lump, quiet: quiet };
    const back = await reopen(Object.assign(clone(e.store.blob), { work_type: "polish" }));
    const toPolish = { carrier: B.travelCarrier(back.api.root()), flag: flagOf(back), rows: driveRows(back), price: prices(back).lump };
    const backReloaded = await reopen(back.store.blob);
    // ...and Add Travel Labor on the Epoxy carrier takes the answer back: the next far answer fills the line like any other
    const e2 = await reopen(Object.assign(clone(afterX), { work_type: "epoxy" }));
    typeCrew(e2, "Epoxy", "epoxy-install", "4", "12");
    const added = await pressAdd(e2, "Epoxy");
    const afterAdd = { added: added, flag: flagOf(e2), rows: driveRows(e2), saved: savedFlag(e2.store.blob) };
    const e2r = await reopen(e2.store.blob);
    return { priceWith: priceWith, priceAfterX: priceAfterX, afterX: { flag: savedFlag(afterX), rows: driveRows(await reopen(afterX)) }, toEpoxy: toEpoxy, epoxyReloaded: epoxyReloaded, toPolish: toPolish,
      polishReloaded: { flag: flagOf(backReloaded), rows: driveRows(backReloaded), price: prices(backReloaded).lump },
      afterAdd: afterAdd, afterAddReloaded: { flag: flagOf(e2r), rows: driveRows(e2r) } };
  });

  // A SAVED BID'S FLAG: the round-5 x set the root's `no_travel_labor` for ANY Travel row (an option's own, a leftover's), so a saved bid can hold the flag over a carrier that has its row.
  // The flag is the job's answer now, and is dropped on open when the carrier holds a row (the price does not move: the flag prices nothing); the library's own decline and the carrier's x are
  // kept. Each case is the model's reading of the saved bid, and its price is read before and after.
  await section("migrate", async () => {
    const crew = { id: "polishing", label: "Polishing", guys: 4, days: 12, rate: 33 };
    const drive = { id: "travel", label: "Travel Labor", guys: 4, days: 6.5, rate: 33, unit: "hours", guys_auto: true, guys_follow: "crew", hours_seed: 6.5 };
    const sec = (kind, rows) => ({ layout: "epoxy", kind: kind, profile: "epoxy@1", takeoff: [], labor: rows, contingency: 0, fees: 0, totals: {} });
    const base = (over) => Object.assign({ version: 2, takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 5000, unit: "SF" }], labor: [clone(crew)],
      conditions: { local: false, taxable: true }, contingency: 0, fees: 0, totals: {}, distance: { miles: 190, source: "typed", key: "" } }, over);
    const cases = {
      "the carrier (the root) holds a row": base({ labor: [clone(crew), clone(drive)], no_travel_labor: true }),
      "the carrier (the root) holds no row": base({ no_travel_labor: true }),
      "an Epoxy carrier holds a row, the root is off": base({ kind: "off", no_travel_labor: true, tabs: { Epoxy: sec("base", [clone(drive)]) } }),
      "an Epoxy carrier holds no row, the root is off": base({ kind: "off", no_travel_labor: true, tabs: { Epoxy: sec("base", []) } }),
      "the root carries and an option holds a row": base({ no_travel_labor: true, tabs: { Epoxy: sec("option", [clone(drive)]) } }),
      "the sections cannot be read, the root holds a row": base({ labor: [clone(crew), clone(drive)], no_travel_labor: true, tabs: { Epoxy: Object.assign(sec("base", []), { layout: null }) } }),
    };
    const res = {};
    Object.keys(cases).forEach((name) => {
      const m = B.migrateModel(clone(cases[name]));
      // the carrier of the bid the model reads (the root when its sections cannot be read), and how many Travel Labor rows it holds
      let at = B.ROOT_TAB;
      try { at = B.travelCarrier(m); } catch (e) { at = B.ROOT_TAB; }
      let held = secOf(m, at);
      try { held = B.sectionOf(m, at).section; } catch (e) { held = m; }
      res[name] = { flag: m.no_travel_labor === true, carrier: at, carrierRows: ((held && held.labor) || []).filter((r) => r.id === "travel").length,
        rootRows: (m.labor || []).filter((r) => r.id === "travel").length, rootLabor: B.laborTotal(m.labor, m.conditions) };
    });
    // THE LEGACY ROW (a Travel row in the shape of 2026-09-12: no unit, no rate) is upgraded whether or not the flag is on the bid: the upgrade is not the flag's to stop.
    const legacy = (flag) => {
      const m = base({ labor: [clone(crew), { id: "travel", label: "Travel", guys: 2, days: 2, rate: "" }] });
      if (flag) m.no_travel_labor = true;
      const g = B.migrateModel(m);
      const r = (g.labor || []).filter((x) => x.id === "travel")[0];
      return { unit: r ? r.unit : null, rate: r ? r.rate : null, cost: r ? B.laborCost(r) : null, flag: g.no_travel_labor === true };
    };
    res.legacy = { plain: legacy(false), flagged: legacy(true) };
    // THE FLAG ALONE never moves a price: a saved bid with it and a row priced $0 more or less than the same bid without it
    const priced = (flag) => {
      const m = base({ labor: [clone(crew), clone(drive)] });
      if (flag) m.no_travel_labor = true;
      const g = B.migrateModel(m);
      return B.laborTotal(g.labor, g.conditions);
    };
    res.priceWithFlag = priced(true);
    res.priceWithoutFlag = priced(false);
    // idempotent
    res.idempotent = Object.keys(cases).every((name) => JSON.stringify(B.migrateModel(B.migrateModel(clone(cases[name])))) === JSON.stringify(B.migrateModel(clone(cases[name]))));
    return res;
  });

  // A SAVED BID NEVER MOVES ON OPEN: a far job saved with its drive and `no_travel_labor` over it, the shape the round-5 x left (it set the flag for ANY Travel line, an option's own included). The flag
  // prices nothing, so the bid opens at the price the parent of this change (f8ba775) gives it, 39,742, with the flag and without it, with its Travel line as it was, and the page saves nothing on
  // opening it. (The saved-bid ratchet's own fixtures feed the golden of the page's saves, which this change must not recut, so the pin lives here.)
  await section("savedBid", async () => {
    const model = (flag) => {
      const m = { version: 2,
        takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 12500, unit: "SF" },
                  { assembly_id: "a2", assembly_name: "Cove Base", measurement: 200, unit: "LF" },
                  { assembly_id: "a5", assembly_name: "Densifier Only", measurement: 5000, unit: "SF" }],
        labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33, rate_default: 33 },
                { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33, rate_default: 33 },
                { id: "jointfill", label: "Joint filler", guys: 3, days: 1, rate: 33, rate_default: 33 },
                { id: "travel", label: "Travel Labor", guys: 3, days: 6.5, rate: 33, unit: "hours", guys_auto: true, guys_follow: "crew", hours_seed: 6.5, rate_default: 33 }],
        conditions: { local: false, prevailing_wage: false, taxable: true, remodel_tax: false, bond: false, dye: false, joint_filler: false, remove_existing_jf: false },
        contingency: 0, fees: 0, totals: {},
        travel: { lodging: { label: "Lodging", enabled: true, qty: 19.5, qty_auto: true, qty_follow: "labor", rate: 70, rate_default: 70 },
                  per_diem: { label: "Per Diem", enabled: true, qty: 19.5, qty_auto: true, qty_follow: "labor", rate: 45, rate_default: 45 } },
        distance: { miles: 190, source: "google", key: "1 water works dr|kansas city|ks|66101" } };
      if (flag) m.no_travel_labor = true;
      return m;
    };
    const blobOf = (flag) => P.blob({ polish_estimate: model(flag), address: "1 Water Works Dr", city: "Kansas City", state: "KS", zip: "66101", polish_sf: B.takeoffSf(model(flag).takeoff) });
    const one = async (flag) => {
      const b = await open(blobOf(flag), { labor: undefined });
      const total = b.api.bid().total;
      b.clock.fire();
      const m = b.api.root();
      return { total: total, flag: m.no_travel_labor === true, row: rowFacts(rowIn(m)), saves: b.rec.saves.length };      // saves read BEFORE anything forces one
    };
    return { withFlag: await one(true), withoutFlag: await one(false) };
  });

  // THE FLAG'S GUARD ON A CARRIER MOVE: a bid whose job said it has no drive does not have a stranded row carried to the new carrier when no carrier is named (followDistance with one argument),
  // and one that did not say so does. (strandedTravelTab is not exported: this is what it answers through followDistance.)
  await section("stranded", async () => {
    const make = (flag) => {
      const m = B.migrateModel({ version: 2, takeoff: [{ assembly_id: "a1", assembly_name: "A", measurement: 5000, unit: "SF" }],
        labor: [{ id: "polishing", label: "Polishing", guys: 4, days: 12, rate: 33 }, { id: "travel", label: "Travel Labor", guys: 4, days: 6.5, rate: 33, unit: "hours", guys_auto: true, guys_follow: "crew", hours_seed: 6.5 }],
        conditions: { local: false, taxable: true }, contingency: 0, fees: 0, totals: {}, distance: { miles: 190, source: "typed", key: "" } });
      const e = B.sectionsForJob(m, "epoxy", { rules: [] });
      e.tabs.Epoxy.labor = [{ id: "epoxy-install", label: "Epoxy install", guys: 4, days: 12, rate: 33 }];
      if (flag) e.no_travel_labor = true;
      return e;
    };
    const run = (flag) => {
      const m = make(flag);
      B.followDistance(m);
      return { epoxyRow: !!rowIn(m.tabs.Epoxy), rootRow: !!rowIn(m), flag: m.no_travel_labor === true };
    };
    return { said: run(true), notSaid: run(false) };
  });

  // ═══ X3. THE x ON A LABOR LINE, FROM THE KEYBOARD ══════════════════════════════════════════════════════════════════════════════════════════════════
  // Tab to a labor row's x and press Enter: the button is a <button>, so the press is a click, the row goes, and the panel is drawn again. The button is destroyed with the panel, and focus
  // falls to <body>. The page puts it on a control that exists afterwards: the next row's x, else the previous row's, else the Add Travel Labor button (when the Travel line was the one
  // that went), else the Add labor line.
  await section("keyboard", async () => {
    const press = async (b, i) => {
      const focused = [];
      const realQs = b.doc.querySelector;
      b.doc.querySelector = (sel) => {
        const el = realQs(sel);
        if (el) el.focus = () => { focused.push(el); };
        return el;
      };
      const sel = '[data-del-lab="' + i + '"]';
      const gone = (b.api.model().labor[i] || {}).id;
      P.clickOn(b, sel);
      b.doc.querySelector = realQs;
      await settle();
      const live = (el) => b.doc.querySelectorAll("[data-del-lab]").concat(b.doc.querySelectorAll("[data-add-lab]"), b.doc.querySelectorAll("[data-add-travel]")).indexOf(el) >= 0;
      const what = (el) => (el.attrs["data-del-lab"] !== undefined ? "x:" + el.attrs["data-del-lab"] : el.attrs["data-add-travel"] !== undefined ? "add-travel" : el.attrs["data-add-lab"] !== undefined ? "add-lab" : "other");
      return { removed: gone, focused: focused.map(what), alive: focused.every(live), rows: b.api.model().labor.map((r) => r.id) };
    };
    const res = {};
    const page = async () => {
      const s = await newBid(polishDraft(), CREW.polish);
      const b = await reopen(s.saved);
      b.api.show(B.ROOT_TAB);
      b.api.go(1);
      return b;
    };
    {
      const b = await page();
      res.start = b.api.model().labor.map((r) => r.id);
      res.middle = await press(b, 1);          // not the last row: the row that moved up into its place has an x
    }
    {
      const b = await page();
      const last = b.api.model().labor.length - 1;
      res.last = await press(b, last);         // the last row (the Travel Labor line): the row before it
    }
    {
      // down to two rows, then the one that is not Travel: one row is left, which draws no x, so the Add labor line takes it
      const b = await page();
      while (b.api.model().labor.length > 2) {
        const at = b.api.model().labor.findIndex((r) => r.id !== "travel");
        await press(b, at);
      }
      const at = b.api.model().labor.findIndex((r) => r.id !== "travel");
      res.toOne = await press(b, at);
    }
    {
      // down to two rows, then the Travel line: one row is left and the Add Travel Labor button stands where the line was
      const b = await page();
      while (b.api.model().labor.length > 2) {
        const at = b.api.model().labor.findIndex((r) => r.id !== "travel");
        await press(b, at);
      }
      res.travelToOne = await press(b, b.api.model().labor.findIndex((r) => r.id === "travel"));
    }
    return res;
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
