"use strict";
/* THE ORDER OF A BID'S SHEETS ACROSS A SAVE AND A RELOAD, on the real estimate page.
 *
 * js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, over the REAL js/bid-model.js. A bid's sections are keys of one
 * object (`model.tabs`), and the draft is stored in a jsonb column, which keeps NO key order: Postgres hands every object back with its keys sorted by
 * length and then by bytes (js/_jsonb.js; PostgreSQL's own documentation shows it). So the same bid, saved and reloaded, listed its sheets in another
 * order than the session that saved it ("Copy1" sorts before 'Gyp (USG 1-8")'; seen on staging: [Gyp (base), Polish 2] in the session and
 * [Polish 2, Gyp (base)] after a reload). Everything that reads the sections in order read the other one: the sheet bar, the sheet the bid opens on,
 * the options of the customer's document and, because the section that carries the job's travel is the FIRST base, the drive and the nights that are
 * charged. Two bases that are both under `tabs` (a Polish copy made the base beside Epoxy) carry the job's travel on whichever the object lists first.
 *
 * Every fact below is read off the page after it ran, once in the session that made the bid and once on a page opened on the blob that session saved,
 * re-keyed as the server returns it (`reloaded`). Nothing is a source assertion. test_v2_sheet_order.py holds each pair to equal, and breaks a copy of
 * the model one line at a time to prove each pair can differ.
 *
 *   comboCopyBase   a far Combo (Polish 6 x 10, Epoxy 4 x 12), the Polish sheet copied, the copy made the base, then the combined Epoxy + copy base: both
 *                   bases are under `tabs`, the root is an option. The carrier, the nights and the lump sum must be the session's after a reload.
 *   epoxyAddPolish  the same pair made from an Epoxy job (the Polish root off) and a fresh Polish sheet.
 *   stripOrder      a Gyp job and a fresh Polish sheet added to it: the order of the sheet bar, and the sheet the bid opens on.
 *   documentOrder   two options added in one order, and what the customer's document lists: the real proposal-review.js rebuildPricing run over the draft
 *                   the page saved, in the session and after a reload and one more save.
 *   lifecycle       one session of add, copy, rename, delete, a copy that takes a freed Copy<N> id, a Gyp sheet that changes preset (its KEY changes), a
 *                   base change and a job-type switch, compared with a reload after EVERY step.
 *   legacy          a bid saved before the order was kept (no `seq` on any section) opens in the order its keys are held in, changes no price when it
 *                   stamps the order, writes nothing on open, and saves the order it opened with.
 *   invariance      every draft the sections above saved, opened with the keys of EVERY object in five orders (as saved, jsonb's, jsonb's reversed, two seeded
 *                   shuffles): the page shows, prices, lists for the document and then saves exactly the same. Nothing else of a saved draft may depend on the
 *                   order of its keys either (a `cell_values`, a `tab_opts`, a row), and this is what holds it.
 *   model           the model alone: the order does not depend on the key order, an unstamped section is newer than a stamped one, a tie is settled by
 *                   the sheet's id, a copy never takes its source's place, a sheet added to a bid with no stamps goes last, a save stamps a bid that has none,
 *                   withSectionOrder stamps once and leaves unreadable tabs as they are.
 *
 * A section that throws reports `{ error }`, so a tree without the code fails an assertion with a reason; the mutation runs in the test count a section
 * error as a failure of the mutation, never as the mutation being noticed.
 *
 * Usage: node sheet-order-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");
const J = require("./_jsonb.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));
const TWPRICE = require(path.join(ROOT, "js", "price-lines-core.js"));
const GYPT = require(path.join(ROOT, "js", "gyp-takeoff.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in sheet-order-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "MODEL"]);

// The library's labor lines: Travel (built in), one Epoxy crew line, one Gyp pour. The Polish crew is the shipped fallback the page adds.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true, default_work_types: [], default_on: true };
const EPOXY_ROW = { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true, default_work_types: ["epoxy"], default_on: true };
const GYP_ROW = { id: "gyp-pour", name: "Gyp pour", rate: 33, unit: "hours", guys_auto: false, sort: 2, favorite: true, default_work_types: ["gyp"], default_on: true };
const LABOR = [TRAVEL_ROW, EPOXY_ROW, GYP_ROW];
const GYP_TAB = 'Gyp (USG 1-8")';
const GYP_FR = "Gyp (FR)";                // another preset of the Gyp tab: the section is re-filed under this key

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const SAVED_ANSWER = { ok: true, miles: 300, reason: "" }; // what a lookup would say; a saved bid never asks
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const comboDraft = () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const epoxyDraft = () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const gypDraft = () => draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 });

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await flush(); };

/** A page on a draft. `extra.reloaded`: the draft is a saved one handed back by the server (jsonb's key order). */
async function open(blob, extra) {
  const opts = Object.assign({ blob: blob, labor: LABOR }, extra || {});
  const b = P.build(opts);
  await b.api.init();
  await settle();
  b.opts = opts;
  return b;
}
/** The same browser opening the draft it saved: localStorage hands back the JSON as it was written, keys in the order the page wrote them. */
const carryOn = (saved, extra) => open(clone(saved), Object.assign({ distance: SAVED_ANSWER }, extra || {}));
/** The draft as the server returns it: every object's keys in jsonb's order. */
const reload = (saved, extra) => open(clone(saved), Object.assign({ distance: SAVED_ANSWER, reloaded: true }, extra || {}));

// ── driving the page as a person does ────────────────────────────────────────────────────────────────────────
const attr = (s) => String(s).replace(/"/g, "&quot;");
const unattr = (s) => String(s).replace(/&quot;/g, '"').replace(/&amp;/g, "&");
const secOf = (m, tab) => (tab === B.ROOT_TAB ? m : (m.tabs || {})[tab]);
const idxIn = (sec, id) => (sec && sec.labor instanceof Array ? sec.labor.findIndex((r) => r && r.id === id) : -1);

function typeCrew(b, tab, rowId, guys, days) {
  b.api.show(tab);
  b.api.go(1);
  const i = idxIn(secOf(b.api.root(), tab), rowId);
  [["guys", guys], ["days", days]].forEach((kv) => {
    const sel = '[data-lab="' + i + '"][data-k="' + kv[0] + '"]';
    if (i >= 0 && b.doc.querySelector(sel)) P.typeInto(b, sel, kv[1]);
  });
}
const clickIf = (b, sel) => { const el = b.doc.querySelector(sel); if (el) P.clickEl(b, el); return !!el; };
const sheetSel = (act, tab) => '[data-sh-act="' + act + '"][data-sh-tab="' + attr(tab) + '"]';

async function newBid(draft, crews, distance) {
  const b = await open(draft, { distance: distance || FAR });
  b.api.go(1);
  await settle();
  crews.forEach((c) => typeCrew(b, c[0], c[1], c[2], c[3]));
  b.clock.fire();
  return b;
}
async function openSheet(b, tab) {
  b.api.go(1);
  clickIf(b, '[data-section-tab="' + attr(tab) + '"]');
  await settle();
}
async function copySheet(b, tab) {
  await openSheet(b, tab);
  clickIf(b, sheetSel("copy", tab));
  await settle();
  b.clock.fire();
}
async function addSheet(b, sheet) {
  b.api.go(1);
  if (b.doc.querySelector('[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]');
  clickIf(b, '[data-sh-act="add"][data-sh-sheet="' + attr(sheet) + '"]');
  await settle();
  b.clock.fire();
}
async function makeBase(b, value) {
  if (value === "combined") {
    // THE PAIR PRICED TOGETHER is a button on the bar of either sheet of it (the strip's "Epoxy + Polish" radio until 2026-10-21): open one of the pair when the sheet on show is not.
    const pair = B.combinedPair(b.api.root());
    if (!pair) return false;
    if (!b.doc.querySelector('[data-sh-act="combine"]')) await openSheet(b, pair[0]);
    if (!clickIf(b, '[data-sh-act="combine"]')) return false;
  } else {
    const el = b.doc.querySelector('[data-sh-base="' + attr(value) + '"]');
    if (!el) return false;
    b.doc.fire("change", { target: el });
  }
  clickIf(b, '[data-sh-act="base-yes"]');
  await settle();
  b.clock.fire();
  return true;
}
async function renameSheet(b, tab, name) {
  await openSheet(b, tab);
  clickIf(b, sheetSel("rename", tab));
  const el = b.doc.querySelector('[data-sh-name="' + attr(tab) + '"]');
  if (el) { el.value = name; b.doc.fire("input", { target: el }); }
  clickIf(b, sheetSel("rename-save", tab));
  await settle();
  b.clock.fire();
}
async function deleteSheet(b, tab) {
  await openSheet(b, tab);
  clickIf(b, sheetSel("delete", tab));
  clickIf(b, sheetSel("delete", tab));
  await settle();
  b.clock.fire();
}

// ── reading the page ─────────────────────────────────────────────────────────────────────────────────────────
const lumpOf = (blob) => (blob && blob.proposal_lump_sum !== undefined && blob.proposal_lump_sum !== null ? blob.proposal_lump_sum : blob && blob.computed_bid ? blob.computed_bid.lump_sum : null);
const panelOf = (b) => String((b.doc.getElementById("sheets-panel") || {}).innerHTML || "");
/** The sheet bar's tabs, left to right (one row to a sheet: the pair priced together is a button on a sheet's bar, not a row). */
const stripOf = (b) => [...panelOf(b).matchAll(/data-sh-row="([^"]*)"/g)].map((m) => unattr(m[1]));
/** The sheet the bid is on after it opens. */
const openOf = (b) => { const m = /data-sh-row="([^"]*)"[^>]*data-sh-cur="1"/.exec(panelOf(b)); return m ? unattr(m[1]) : null; };

/** Every price the page holds, and what a save then writes. A save is forced, so this runs after everything else is read. */
function prices(b) {
  const bids = b.api.sectionBids();
  const root = b.api.bid().total;
  b.api.saveSoon();
  b.clock.fire();
  const saved = b.store.blob;
  return { lump: lumpOf(saved), root: root, sections: Object.fromEntries(Object.keys(bids).sort().map((k) => [k, bids[k].total])),
    pricedTabs: (saved.priced_tabs || []).map((t) => t.id), pricedKinds: (saved.priced_tabs || []).map((t) => t.kind) };
}

/** What the customer's document lists as options for a draft: the real proposal-review.js rebuildPricing, run over the saved draft (the page's own
 *  state load is the draft; its payload sync, which patches a payload that is not there yet, answers nothing). The rooms it makes, in order. */
const PROPOSAL = L.read(path.join(ROOT, "js", "proposal-review.js"));
const IND = { indent: "  ", where: "proposal-review.js" };
const REBUILD_SRC = [
  L.grabConst(PROPOSAL, "GYP_BASE", IND), L.grabConst(PROPOSAL, "fmtUSD", IND),
  L.grabConst(PROPOSAL, "OPTION_ONLY_ROLES", IND), L.grabConst(PROPOSAL, "COMBINED_BASE_ROLES", IND), L.grabConst(PROPOSAL, "roleOfTab", IND),
  L.grabConst(PROPOSAL, "isOptionOnlyTab", IND), L.grabConst(PROPOSAL, "inCombinedBase", IND),
  L.liftSource(PROPOSAL, "baseAreaFrom", IND), L.liftSource(PROPOSAL, "rebuildPricing", IND),
].join("\n");
const makeRebuild = new Function("state", "TW", "document", "TWPrice", "syncPayloadPricing", REBUILD_SRC + "\nreturn rebuildPricing;");
function documentOptions(saved) {
  const state = clone(saved);
  const rebuild = makeRebuild(state, { setState: () => ({}) }, { querySelector: () => ({ textContent: "" }) }, TWPRICE, () => null);
  rebuild();
  return (state.rooms || []).map((r) => r.id + (r.is_base ? " (base)" : ""));
}

/** Everything one page shows that depends on the order of the sheets. `withDoc`: also what the document lists. */
function facts(b, withDoc) {
  const m = b.api.root();
  const entries = B.sectionsOf(m);
  const out = { order: entries.map((e) => e.tab), kinds: entries.map((e) => e.kind), carrier: B.travelCarrier(m), strip: stripOf(b), open: openOf(b),
    bases: B.baseOf(m).ids, jobType: B.baseOf(m).jobType };
  out.prices = prices(b);
  if (withDoc) out.document = documentOptions(b.store.blob);
  return out;
}

const out = {};
/** Every draft a session saved, for the `invariance` section: [{ label, saved }]. */
const SAVED_BLOBS = [];
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}
/** The session's facts, and the facts of the blob it saved after the server has had it. `again`: the reloaded page is edited (a crew figure typed) and
 *  saved, and the result is reloaded once more. */
async function sessionAndReload(b, opts) {
  const o = opts || {};
  const session = facts(b, o.doc);
  const saved = clone(b.store.blob);
  SAVED_BLOBS.push({ label: o.label || "", saved: clone(saved) });
  const r = await reload(saved);
  r.api.go(1);
  await settle();
  const reloaded = facts(r, o.doc);
  const res = { session: session, reload: reloaded };
  if (o.again) {
    typeCrew(r, o.again[0], o.again[1], o.again[2], o.again[3]);
    r.clock.fire();
    const second = await reload(clone(r.store.blob));
    second.api.go(1);
    await settle();
    res.reloadTwice = facts(second, o.doc);
    res.editedOnce = facts(r, o.doc);
  }
  return res;
}

async function main() {
  // ═══ comboCopyBase: both bases under `tabs`, the root an option ═══════════════════════════════════════════════
  await section("comboCopyBase", async () => {
    const b = await newBid(comboDraft(), [["Polish", "polishing", "6", "10"], ["Epoxy", "epoxy-install", "4", "12"]]);
    await copySheet(b, "Polish");                         // Copy1, a Polish copy, an option
    const afterCopy = await sessionAndReload(b, { label: "comboCopyBase: after the copy" });
    await makeBase(b, "Copy1");                           // the copy is the base; Polish and Epoxy become options
    const copyBase = await sessionAndReload(b, { label: "comboCopyBase: the copy the base" });
    const made = await makeBase(b, "combined");           // Epoxy + the copy: both bases are under `tabs`, the Polish root an option
    const res = await sessionAndReload(b, { doc: true, again: ["Epoxy", "epoxy-install", "5", "12"], label: "comboCopyBase" });
    res.steps = { afterCopy: afterCopy, copyBase: copyBase };
    res.madeCombined = made;
    return res;
  });

  // ═══ epoxyAddPolish: the same pair from an Epoxy job and a fresh Polish sheet ═════════════════════════════════
  await section("epoxyAddPolish", async () => {
    const b = await newBid(epoxyDraft(), [["Epoxy", "epoxy-install", "4", "12"]]);
    await addSheet(b, "Polish");                          // a Polish sheet beside the root is a Copy<N>
    const copyId = B.sectionsOf(b.api.root()).filter((e) => e.role === "polish" && !e.root)[0];
    if (copyId) { typeCrew(b, copyId.tab, "polishing", "6", "10"); b.clock.fire(); }
    const made = await makeBase(b, "combined");
    const res = await sessionAndReload(b, { doc: true, label: "epoxyAddPolish" });
    res.madeCombined = made;
    res.copyId = copyId ? copyId.tab : null;
    return res;
  });

  // ═══ stripOrder: a Gyp job and a fresh Polish sheet ═══════════════════════════════════════════════════════════
  await section("stripOrder", async () => {
    const b = await newBid(gypDraft(), [[GYP_TAB, "gyp-pour", "4", "12"]]);
    await addSheet(b, "Polish");
    return await sessionAndReload(b, { doc: true, label: "stripOrder" });
  });

  // ═══ documentOrder: two options, added in one order ═══════════════════════════════════════════════════════════
  await section("documentOrder", async () => {
    const b = await newBid(gypDraft(), [[GYP_TAB, "gyp-pour", "4", "12"]]);
    await addSheet(b, "Epoxy");                           // the Epoxy sheet, then
    await addSheet(b, "Polish");                          // a Polish one: Copy1
    // an option with nothing in it prices nothing, and a document prints only an option that has a price: give each a crew
    typeCrew(b, "Epoxy", "epoxy-install", "3", "5");
    typeCrew(b, "Copy1", "polishing", "3", "4");
    b.clock.fire();
    return await sessionAndReload(b, { doc: true, again: [GYP_TAB, "gyp-pour", "5", "12"], label: "documentOrder" });
  });

  // ═══ lifecycle: every way a sheet comes, goes and changes, a reload after each ════════════════════════════════
  await section("lifecycle", async () => {
    let b = await newBid(comboDraft(), [["Polish", "polishing", "6", "10"], ["Epoxy", "epoxy-install", "4", "12"]]);
    const steps = [];
    const note = async (name) => { steps.push(Object.assign({ step: name }, await sessionAndReload(b, { doc: true, label: "lifecycle: " + name }))); };
    await note("start");
    await addSheet(b, GYP_TAB);                           await note("add Gyp");
    await copySheet(b, "Epoxy");                          await note("copy Epoxy (Copy1)");
    await copySheet(b, "Polish");                         await note("copy Polish (Copy2)");
    await renameSheet(b, "Copy1", "Garage");              await note("rename Copy1");
    await deleteSheet(b, "Copy2");                        await note("delete Copy2");
    await copySheet(b, "Epoxy");                          await note("copy Epoxy again (takes the freed Copy2)");
    await openSheet(b, GYP_TAB);                          // the Material step's Gyp card moves the sheet to another preset: its KEY changes
    b.api.go(0);
    if (GYPT.tabs().indexOf(GYP_FR) >= 0) P.changeTo(b, '[data-gyp="preset"]', GYP_FR);
    b.clock.fire();                                       await note("change the Gyp sheet to another preset (its key changes)");
    await makeBase(b, GYP_FR);                            await note("make Gyp the base");
    await makeBase(b, "combined");                        await note("make the Epoxy + Polish pair the base");
    // the intake's job type moves, and the estimate page opens on the same browser's copy of the draft (the session goes on)
    const saved = clone(b.store.blob);
    b = await carryOn(Object.assign(clone(saved), { work_type: "epoxy" }));
    b.api.go(1);
    await settle();
    b.clock.fire();
    await note("job type switched to Epoxy");
    return { steps: steps };
  });

  // ═══ legacy: a bid saved before the order was kept ════════════════════════════════════════════════════════════
  await section("legacy", async () => {
    const b = await newBid(comboDraft(), [["Polish", "polishing", "6", "10"], ["Epoxy", "epoxy-install", "4", "12"]]);
    await copySheet(b, "Polish");
    await copySheet(b, "Epoxy");
    await makeBase(b, "Copy1");
    await makeBase(b, "combined");
    // what an old save looks like once the server has had it: no `seq` anywhere, keys in jsonb's order
    const old = clone(b.store.blob);
    Object.keys(old.polish_estimate.tabs).forEach((id) => { delete old.polish_estimate.tabs[id].seq; });
    const held = J.reloaded(old);
    const keyOrder = Object.keys(held.polish_estimate.tabs);
    // opened plain: nothing is written, asked or armed
    const p = await open(clone(held), { distance: SAVED_ANSWER });
    p.api.go(1);
    await settle();
    const quiet = { armed: p.clock.armed(), saves: p.rec.saves.length, asked: (p.rec.distanceBodies || []).length };
    const opened = { order: B.sectionsOf(p.api.root()).map((e) => e.tab), seqs: B.sectionsOf(p.api.root()).filter((e) => !e.root).map((e) => e.section.seq) };
    const factsOpen = facts(p, true);
    const savedBlob = clone(p.store.blob);
    const savedSeqs = Object.keys(savedBlob.polish_estimate.tabs).map((id) => [id, savedBlob.polish_estimate.tabs[id].seq]);
    // the same bid with the order the keys are held in written down by hand, 1..n: stamping it changes nothing
    const byHand = clone(held);
    Object.keys(byHand.polish_estimate.tabs).forEach((id, i) => { byHand.polish_estimate.tabs[id].seq = i + 1; });
    const h = await open(clone(byHand), { distance: SAVED_ANSWER });
    h.api.go(1);
    await settle();
    const factsByHand = facts(h, true);
    // and what the saved order does after the next reload
    const again = await reload(savedBlob);
    again.api.go(1);
    await settle();
    return { keyOrder: keyOrder, quiet: quiet, opened: opened, facts: factsOpen, savedSeqs: savedSeqs, byHand: factsByHand, reloadOfSaved: facts(again, true) };
  });

  // ═══ model: the order, on the model alone ═════════════════════════════════════════════════════════════════════
  await section("model", async () => {
    const stamp = (m, seqs) => { Object.keys(seqs).forEach((id) => { m.tabs[id].seq = seqs[id]; }); return m; };
    const base = () => {
      let m = B.freshModel();
      m = B.activateSection(m, "Epoxy", "option", { rules: [] });
      m = B.addSheet(m, "Polish", { state: {} }).model;               // Copy1
      m = B.copySection(m, "Epoxy", { state: {} }).model;             // Copy2
      m = B.activateSection(m, GYP_TAB, "option", { rules: [] });
      return m;
    };
    const m0 = base();
    const ids = (m) => B.sectionsOf(m).map((e) => e.tab);
    const seqs = (m) => Object.fromEntries(Object.keys(m.tabs).map((id) => [id, m.tabs[id].seq === undefined ? null : m.tabs[id].seq]));
    // the same sheets with their keys in every order the server or a browser might hand them over
    const permutations = (a) => (a.length <= 1 ? [a] : a.flatMap((x, i) => permutations(a.slice(0, i).concat(a.slice(i + 1))).map((p) => [x].concat(p))));
    const reorder = (m, keys) => { const c = clone(m); c.tabs = Object.fromEntries(keys.map((k) => [k, c.tabs[k]])); return c; };
    const keys = Object.keys(m0.tabs);
    const stampedOrders = permutations(keys).map((p) => ids(reorder(m0, p)).join(" | "));
    const viaServer = ids(J.reloaded(m0));
    // an unstamped section is newer than a stamped one (it was put there by something that kept no order); the unstamped keep the order their keys are held in
    const mixed = clone(m0);
    mixed.tabs = Object.fromEntries(Object.keys(mixed.tabs).map((k) => [k, mixed.tabs[k]]));
    delete mixed.tabs.Copy1.seq; delete mixed.tabs.Epoxy.seq;
    const mixedKeysAB = ids(reorder(mixed, ["Epoxy", "Copy1", "Copy2", GYP_TAB]));
    const mixedKeysBA = ids(reorder(mixed, ["Copy1", "Epoxy", "Copy2", GYP_TAB]));
    // two sections with one stamp: settled by the sheet's id, whatever the keys' order
    const tie = clone(m0);
    Object.keys(tie.tabs).forEach((k) => { tie.tabs[k].seq = 7; });
    const tieOrders = permutations(Object.keys(tie.tabs)).map((p) => ids(reorder(tie, p)).join(" | "));
    // a bid saved before the order was kept: no stamps at all, the order the keys are held in
    const legacy = clone(m0);
    Object.keys(legacy.tabs).forEach((k) => { delete legacy.tabs[k].seq; });
    const legacyHeld = Object.keys(reorder(legacy, ["Copy2", "Epoxy", GYP_TAB, "Copy1"]).tabs);
    const legacyOrder = ids(reorder(legacy, ["Copy2", "Epoxy", GYP_TAB, "Copy1"]));
    // stamping it once
    const stampedOnce = B.withSectionOrder ? B.withSectionOrder(reorder(legacy, ["Copy2", "Epoxy", GYP_TAB, "Copy1"])) : null;
    const stampedTwice = stampedOnce && B.withSectionOrder(stampedOnce);
    // a copy takes its own place, last, whatever the source's was
    const copied = B.copySection(m0, "Epoxy", { state: {} });
    const copyOfCopy = B.copySection(copied.model, copied.id, { state: {} });
    // an option added to a bid (the Seal sheets) goes last too
    const optioned = B.addOption(m0, "Seal", { state: {} });
    // a freed Copy<N> id handed out again goes last
    const freed = B.deleteSection(m0, "Copy1", { state: {} }).model;
    const reused = B.copySection(freed, "Epoxy", { state: {} });
    // sections that cannot be read are carried as they are
    const hostile = clone(m0);
    hostile.tabs.Strange = 5;
    const hostileStamped = B.withSectionOrder ? B.withSectionOrder(hostile) : null;
    const unreadable = clone(legacy);                                  // objects, but one names no layout: sectionsOf throws, and the bid is carried as it was saved
    delete unreadable.tabs.Epoxy.layout;
    const unreadableStamped = B.withSectionOrder ? B.withSectionOrder(unreadable) : null;
    // a sheet added to a bid saved before the order was kept goes LAST, whatever order its keys are held in (the sections already here are stamped first)
    const oldBid = reorder(legacy, ["Copy2", "Epoxy", GYP_TAB, "Copy1"]);
    const oldAdd = B.copySection(oldBid, "Epoxy", { state: {} });
    const oldFresh = B.addSheet(oldBid, "Seal", { state: {} });
    // a save carries the order: a bid with no stamps is composed into a draft whose sections hold 1..n, and whose priced_tabs list them in that order
    const composeModel = (() => {
      let m = B.freshModel();
      m = B.activateSection(m, "Epoxy", "base", { rules: [] });
      m = B.copySection(m, "Epoxy", { state: {} }).model;             // Copy1
      m = B.copySection(m, "Polish", { state: {} }).model;            // Copy2
      m = reorder(m, ["Copy2", "Epoxy", "Copy1"]);
      Object.keys(m.tabs).forEach((k) => { delete m.tabs[k].seq; });
      return m;
    })();
    const CTX = { material: () => 1000, remodel_rate: null };
    const composed = (() => {
      try {
        const snap = B.composePricingSnapshot(composeModel, { bid: B.polishBid(composeModel, "Polish", CTX), bids: B.priceTabs(composeModel, CTX) });
        return { seqs: seqs(snap.polish_estimate), pricedTabs: snap.priced_tabs.map((t) => t.id), keys: Object.keys(snap.polish_estimate.tabs) };
      } catch (e) { return { error: String(e && e.message || e) }; }
    })();
    return {
      stamped: seqs(m0), order: ids(m0), stampedOrders: stampedOrders, viaServer: viaServer,
      mixed: { keysAB: mixedKeysAB, keysBA: mixedKeysBA },
      tieOrders: tieOrders,
      legacy: { held: legacyHeld, order: legacyOrder },
      stampedOnce: stampedOnce ? { seqs: seqs(stampedOnce), order: ids(stampedOnce) } : null,
      stampedTwiceSame: stampedOnce ? stampedTwice === stampedOnce : null,
      alreadyStampedSame: B.withSectionOrder ? B.withSectionOrder(m0) === m0 : null,
      copy: { id: copied.id, seqs: seqs(copied.model), order: ids(copied.model), copyOfCopy: { id: copyOfCopy.id, seqs: seqs(copyOfCopy.model), order: ids(copyOfCopy.model) } },
      reused: { id: reused.id, order: ids(reused.model), seqs: seqs(reused.model) },
      option: { order: ids(optioned), seqs: seqs(optioned) },
      hostile: hostileStamped ? { same: hostileStamped === hostile, strange: hostileStamped.tabs.Strange, seqsUntouched: Object.keys(hostileStamped.tabs).filter((k) => k !== "Strange").every((k) => hostileStamped.tabs[k].seq === hostile.tabs[k].seq) } : null,
      unreadable: unreadableStamped ? { same: unreadableStamped === unreadable } : null,
      oldBid: { held: Object.keys(oldBid.tabs), copy: { id: oldAdd.id, order: ids(oldAdd.model), seqs: seqs(oldAdd.model) }, fresh: { id: oldFresh.id, order: ids(oldFresh.model), seqs: seqs(oldFresh.model) } },
      composed: composed,
    };
  });

  // ═══ invariance: nothing a saved draft shows or does depends on the order of any object's keys ════════════════════
  await section("invariance", async () => {
    const rng = (seed) => { let a = seed >>> 0; return () => { a = (a + 0x6D2B79F5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; };
    const rekey = (v, order) => {
      if (Array.isArray(v)) return v.map((x) => rekey(x, order));
      if (v && typeof v === "object") {
        const o = {};
        order(Object.keys(v)).forEach((k) => { Object.defineProperty(o, k, { value: rekey(v[k], order), enumerable: true, writable: true, configurable: true }); });
        return o;
      }
      return v;
    };
    const shuffled = (seed) => { const r = rng(seed); return (ks) => { const a = ks.slice(); for (let j = a.length - 1; j > 0; j--) { const k = Math.floor(r() * (j + 1)); const t = a[j]; a[j] = a[k]; a[k] = t; } return a; }; };
    const canon = (v) => JSON.stringify(v, (k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.keys(x).sort().map((kk) => [kk, x[kk]])) : x));
    const shown = async (blob) => {
      const b = await open(blob, { distance: SAVED_ANSWER });
      b.api.go(1);
      await settle();
      const f = facts(b, true);                                      // forces a save: what it writes is read below
      return { order: f.order, kinds: f.kinds, carrier: f.carrier, bases: f.bases, strip: f.strip, prices: f.prices, document: f.document, saved: canon(b.store.blob) };
    };
    const subjects = SAVED_BLOBS.filter((x) => x.label);
    const differ = [];
    let compared = 0;
    for (let i = 0; i < subjects.length; i++) {
      const s = subjects[i];
      const base = await shown(clone(s.saved));
      const variants = [["jsonb", (ks) => ks.slice().sort(J.compareKeys)], ["jsonb reversed", (ks) => ks.slice().sort(J.compareKeys).reverse()],
                        ["shuffle 1", shuffled(i * 131 + 17)], ["shuffle 2", shuffled(i * 131 + 7936)]];
      for (const v of variants) {
        const got = await shown(rekey(clone(s.saved), v[1]));
        compared++;
        const fields = Object.keys(base).filter((k) => JSON.stringify(base[k]) !== JSON.stringify(got[k]));
        if (fields.length) differ.push({ label: s.label, variant: v[0], fields: fields });
      }
    }
    return { blobs: subjects.length, compared: compared, differ: differ };
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
