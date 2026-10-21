"use strict";
/* ROUND 7, PART 1 (2026-10-21): TWO DRIVES ON A COMBO, AND THE ANSWER MODEL THEY NEED, run on the REAL estimate page: js/polish-estimate.js, whole, booted the way
 * polish-estimate-harness.js boots it, with the REAL js/bid-model.js beneath it. Every fact below is read off the page after it ran (the model it held, the panels it drew,
 * what it saved). Nothing is a source assertion. EVERY REOPEN IS A JSONB REOPEN (tests/js/_jsonb.js): the draft comes back as the drafts table hands it.
 * test_polish_travel_round7.py holds each fact to Hanz's decisions of 2026-10-21 and breaks a COPY of the page or the model one line at a time to prove each can change.
 *
 *   D1  `combo`, `single`: A FAR COMBO HAS TWO DRIVES, ONE PER BASE CREW. Kyle's own combo-like estimates put a drive on BOTH sheets, each its own crew x its own round trip
 *       ("Epoxy trv 4x4; Polish trv 6x4"). Far Combo, Polish 4 x 12 and Epoxy 5 x 12, 190 miles (a 6.5 hour round trip): the Polish sheet's Travel Labor is 4 x 6.5 = $858 and the
 *       Epoxy sheet's 5 x 6.5 = $1,072.50, each filled on the far answer and each its own. The job's Lodging and Per Diem stay ONE pair of lines, their nights summed over both bases
 *       (round 6). Each base's own Travel card is on its Labor step and its drive is under its own section on the Review. A single-base job keeps one drive.
 *   D2  `gyp`: A GYP BASE'S DRIVE FILLS FROM THE MILES like Polish and Epoxy: its crew's size (the most guys on one of its crew lines, entered in hours) x the round trip x the rate.
 *   J/S `sheet`, `rootSheet`, `job`: THE ANSWERS. The x on the drive of a single-base job says the job has no drive (the root's `no_travel_labor`, J) and survives a job-type switch
 *       (D3). On a two-base Combo the x on one base's drive is THAT SHEET's answer (`sheet_no_travel_labor` on the section, S): the other base keeps its drive, Add Travel Labor on
 *       the sheet takes it back, and when the job goes back to one base the remaining base keeps its own answer.
 *   P   `promotion`: AN OPTION MADE A BASE (the round-6 audit's F-C). A job-type switch or a base pick that turns an option into a base keeps a drive line the estimator added
 *       (Add Travel Labor) or typed on it; a line the TOOL filled (a copy's, a demoted base's) is refilled by the rule of its new role, and while the job says it has no drive (J)
 *       it is released, not re-added.
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason.
 *
 * Usage: node travel-round7-harness.js <frontend-dir>   ->  one line of JSON
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
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-round7-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "MODEL"]);

// The library's labor lines: Travel (built in), one Epoxy crew line and one Gyp pour, each at $33. The Polish crew is the shipped fallback the page adds.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true, default_work_types: [], default_on: true };
const EPOXY_ROW = { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true, default_work_types: ["epoxy"], default_on: true };
const GYP_ROW = { id: "gyp-pour", name: "Gyp pour", rate: 33, unit: "hours", guys_auto: false, sort: 2, favorite: true, default_work_types: ["gyp"], default_on: true };
const LABOR = [TRAVEL_ROW, EPOXY_ROW, GYP_ROW];
const GYP_TAB = 'Gyp (USG 1-8")';

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const LOCAL = { ok: true, miles: 40, reason: "" };
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const COMBO = () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const POLISH = () => draftOf("polish", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const EPOXY = () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const GYP = () => draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 });

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
const attrOf = (b, sel, name) => { const el = b.doc.querySelector(sel); return el ? el.getAttribute(name) : null; };
const has = (b, sel) => !!b.doc.querySelector(sel);
const lumpOf = (blob) => (blob && blob.proposal_lump_sum !== undefined && blob.proposal_lump_sum !== null ? blob.proposal_lump_sum : blob && blob.computed_bid ? blob.computed_bid.lump_sum : null);
const driveText = (r) => (r ? r.guys + " x " + r.days + " = $" + B.laborCost(r) : null);
const panelHtml = (b) => String((b.doc.getElementById("panels") || {}).innerHTML || "");
const q = (sel) => sel.replace(/"/g, "&quot;");

/** The job's answer (J) and each sheet's own (S), as the page holds them. */
function answers(b) {
  const m = b.api.root();
  const sheets = {};
  B.sectionsOf(m).forEach((e) => { if (e.section && e.section.sheet_no_travel_labor === true) sheets[e.tab] = true; });
  return { job: m.no_travel_labor === true, sheets: sheets };
}

/** Every section's Travel Labor row, by `tab:kind`, as a short string. */
function driveRows(b) {
  const m = b.api.root();
  return Object.fromEntries(B.sectionsOf(m).map((e) => [e.tab + ":" + e.kind, driveText(rowIn(e.section))]));
}

/** The markers on one section's Travel Labor row: who filled it, and who put it there. */
function marks(b, tab) {
  const r = rowIn(secOf(b.api.root(), tab));
  return r ? { auto: r.guys_auto === true, follow: r.guys_follow || null, seed: r.hours_seed === undefined ? null : r.hours_seed, typed: r.guys_typed === true || r.hours_typed === true,
    hand: r.hand_added === true } : null;
}

/** Every price the page holds: the root sheet's own bid, each other section's, and what a save writes (the lump sum). A save is forced, so run it after everything else is read. */
function prices(b) {
  const bids = b.api.sectionBids();
  const root = b.api.bid();
  b.api.saveSoon();
  b.clock.fire();
  return { lump: lumpOf(b.store.blob), root: root.total, sections: Object.fromEntries(Object.keys(bids).sort().map((k) => [k, bids[k].total])) };
}

/** What the page saves and prices, as one comparable thing: the rows, the answers and every price. */
function state(b) {
  return { rows: driveRows(b), answers: answers(b), price: prices(b) };
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

/** A NEW bid on the page: the lookup answers (`distance`), each crew is typed as a person types it on the Labor step, the draft is saved. */
async function newBid(blob, crews, distance) {
  const b = await open(blob, { distance: distance || FAR });
  b.api.go(1);
  await settle();
  (crews || []).forEach((c) => typeCrew(b, c[0], c[1], c[2], c[3]));
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
async function reload(b) {
  b.api.saveSoon();
  b.clock.fire();
  return reopen(clone(b.store.blob));
}

/** The intake's job type reaching the estimate page on the saved draft. */
async function switchJob(b, jobType) {
  b.api.saveSoon();
  b.clock.fire();
  const j = await reopen(Object.assign(clone(b.store.blob), { work_type: jobType }));
  j.api.saveSoon();
  j.clock.fire();
  return j;
}

async function addSheet(b, sheet) {
  b.api.go(1);
  if (b.doc.querySelector('[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]');
  P.clickOn(b, '[data-sh-act="add"][data-sh-sheet="' + q(String(sheet)) + '"]');
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

/** The Sheets panel's base pick: one sheet's radio, or "combined" (the "Make Epoxy + Polish the base" button on a sheet of the pair), then yes. */
async function makeBase(b, value) {
  if (value === "combined") {
    const pair = B.combinedPair(b.api.root());
    b.api.show(pair[0]);
    b.api.go(1);
    await settle();
    P.clickOn(b, '[data-sh-act="combine"]');
  } else {
    b.doc.fire("change", { target: P.need(b, '[data-sh-base="' + q(String(value)) + '"]') });
  }
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

/** The miles typed on the Labor step of the sheet that carries the job's travel. */
async function typeMiles(b, miles) {
  b.api.show(B.travelCarrier(b.api.root()));
  b.api.go(1);
  P.typeInto(b, "[data-dist-miles]", String(miles));
  await settle();
  b.clock.fire();
}

/** What the Labor step of the section `tab` draws about the drive: the note under Travel, whether the section's Travel Labor card sits in the travel block, the card's
 *  note on where its hours came from, the hint under its Guys box, the Add Travel Labor control, the miles box and the Lodging card, and the two sentences on the travel block. */
async function laborFacts(b, tab) {
  b.api.show(tab);
  b.api.go(1);
  await settle();
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  const html = panelHtml(b);
  const sep = html.indexOf("trvsep");
  const card = i >= 0 ? html.indexOf('data-lab-card="' + i + '"') : -1;
  const cap = /<p class="cap">(Travel is expected[^<]*)<\/p>/.exec(html);
  const cardNote = /<p class="hint trvnote">(Drive time is expected[^<]*)<\/p>/.exec(html);
  return { note: textOf(b, "[data-travel-note]"), card: card >= 0 && sep >= 0 && card > sep, how: textOf(b, "[data-trv-how]"),
    src: i >= 0 ? textOf(b, '[data-trv-src="' + i + '"]') : null, hint: i >= 0 ? textOf(b, '[data-hint-lab="' + i + '"]') : null,
    add: has(b, "[data-add-travel]"), none: attrOf(b, "[data-trv-none]", "data-trv-none"), miles: has(b, "[data-dist-miles]"), lodging: has(b, '[data-trv-card="lodging"]'),
    cap: cap ? cap[1] : null, cardNote: cardNote ? cardNote[1] : null };
}

/** What the Review step of the section `tab` says about the drive (the Travel Labor row of its Labor card: the trip sentence, the working, the total) and about Hotel and Per Diem. */
async function reviewFacts(b, tab) {
  b.api.show(tab);
  b.api.go(2);
  await settle();
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  const html = panelHtml(b);
  const card = html.indexOf('data-rev="travel"');
  const hotel = card >= 0 ? html.slice(card, html.indexOf("</table>", card)) : "";
  const one = (k) => textOf(b, '[data-rv="lab.' + i + "." + k + '"]');
  return { drive: i >= 0 ? { sentence: one("drive"), q: one("q"), w: one("w"), tot: one("tot") } : null,
    lodging: textOf(b, '[data-rv="trv.lodging.q"]'), hotelOnce: hotel.indexOf("charged once for the whole job") >= 0,
    ownDrive: hotel.indexOf("own drive is its Travel Labor line, under Labor.") >= 0 };
}

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

const CREW_POLISH = ["Polish", "polishing", "4", "12"];
const CREW_EPOXY = ["Epoxy", "epoxy-install", "5", "12"];

async function main() {
  // ═══ D1. A FAR COMBO HAS TWO DRIVES, ONE PER BASE CREW ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("combo", async () => {
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const m = b.api.root();
    const session = { rows: driveRows(b), marks: { polish: marks(b, B.ROOT_TAB), epoxy: marks(b, "Epoxy") }, answers: answers(b),
      lodging: { qty: m.travel.lodging.qty, follow: m.travel.lodging.qty_follow || null, on: m.travel.lodging.enabled === true },
      perDiem: { qty: m.travel.per_diem.qty, follow: m.travel.per_diem.qty_follow || null }, nights: B.jobNights(m).count,
      epoxyLabor: B.laborTotal(m.tabs.Epoxy.labor, m.conditions), carrier: B.travelCarrier(m) };
    const labor = { polish: await laborFacts(b, B.ROOT_TAB), epoxy: await laborFacts(b, "Epoxy") };
    const review = { polish: await reviewFacts(b, B.ROOT_TAB), epoxy: await reviewFacts(b, "Epoxy") };
    const price = prices(b);
    const r = await reload(b);
    const reopened = { quiet: { armed: r.clock.armed(), saves: r.rec.saves.length }, state: state(r) };
    // 300 miles typed in the session and after the reload: each base's drive follows the answer on its own crew (4 x 10 and 5 x 10)
    await typeMiles(b, 300);
    await typeMiles(r, 300);
    return { session: session, labor: labor, review: review, price: price, reopened: reopened, at300: { session: state(b), reload: state(r) } };
  });

  // The same crews as ONE base: far Polish 4 x 12 keeps one drive, and so does far Epoxy 5 x 12 (each its own crew, as before).
  await section("single", async () => {
    const p = await newBid(POLISH(), [CREW_POLISH]);
    const e = await newBid(EPOXY(), [CREW_EPOXY]);
    return { polish: driveRows(p), epoxy: driveRows(e), epoxyCarrier: B.travelCarrier(e.api.root()) };
  });

  // ═══ D2. A GYP BASE'S DRIVE FILLS FROM THE MILES ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("gyp", async () => {
    const b = await newBid(GYP(), [[GYP_TAB, "gyp-pour", "4", "120"]]);
    const filled = { rows: driveRows(b), marks: marks(b, GYP_TAB) };
    const labor = await laborFacts(b, GYP_TAB);
    // the crew's size is read off its crew lines, entered in hours: 6 guys on the pour
    typeCrew(b, GYP_TAB, "gyp-pour", "6", "120");
    b.api.saveSoon();
    b.clock.fire();
    const grown = driveRows(b);
    const r = await reload(b);
    const reloaded = { quiet: { armed: r.clock.armed(), saves: r.rec.saves.length }, rows: driveRows(r) };
    const local = await newBid(GYP(), [[GYP_TAB, "gyp-pour", "4", "120"]], LOCAL);
    return { filled: filled, labor: labor, grown: grown, reloaded: reloaded, local: driveRows(local) };
  });

  // ═══ S. THE x ON ONE BASE'S DRIVE OF A COMBO IS THAT SHEET'S ANSWER ═══════════════════════════════════════════════════════════════════════════════════════════════
  await section("sheet", async () => {
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const x = await pressX(b, "Epoxy");
    const afterX = state(b);
    const labor = await laborFacts(b, "Epoxy");
    const r = await reload(b);
    const reloaded = state(r);
    await typeMiles(b, 300);
    await typeMiles(r, 300);
    const at300 = { session: state(b), reload: state(r) };
    // back to one base: the job type Epoxy keeps the Epoxy sheet's own answer (no drive), and Add Travel Labor takes it back
    const e = await switchJob(b, "epoxy");
    const oneBase = { state: state(e), labor: await laborFacts(e, "Epoxy") };
    const eReloaded = state(await reload(e));
    const added = await pressAdd(e, "Epoxy");
    const afterAdd = { added: added, state: state(e), marks: marks(e, "Epoxy") };
    return { x: x, afterX: afterX, labor: labor, reloaded: reloaded, at300: at300, oneBase: oneBase, oneBaseReloaded: eReloaded, afterAdd: afterAdd };
  });

  // ...and the x on the CARRIER's drive of a Combo (the Polish root) is the Polish sheet's answer, not the job's: Epoxy keeps its drive, and a reload gives the root no blank row.
  await section("rootSheet", async () => {
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const x = await pressX(b, B.ROOT_TAB);
    const afterX = state(b);
    const r = await reload(b);
    const reloaded = { quiet: { armed: r.clock.armed(), saves: r.rec.saves.length }, state: state(r) };
    await typeMiles(b, 300);
    await typeMiles(r, 300);
    const polish = await switchJob(b, "polish");
    return { x: x, afterX: afterX, reloaded: reloaded, at300: { session: state(b), reload: state(r) }, polish: state(polish) };
  });

  // ═══ J. THE x ON A SINGLE-BASE JOB'S DRIVE IS THE JOB'S ANSWER, AND A SWITCH KEEPS THE DRIVE REMOVED (D3) ═════════════════════════════════════════════════════════
  await section("job", async () => {
    const b = await newBid(POLISH(), [CREW_POLISH]);
    const x = await pressX(b, B.ROOT_TAB);
    const c = await switchJob(b, "combo");
    typeCrew(c, "Epoxy", "epoxy-install", "5", "12");
    c.api.saveSoon();
    c.clock.fire();
    const combo = { state: state(c), addOnPolish: (await laborFacts(c, B.ROOT_TAB)).add, addOnEpoxy: (await laborFacts(c, "Epoxy")).add };
    const comboReloaded = state(await reload(c));
    // Add Travel Labor on the Epoxy sheet: the job has a drive again, on Epoxy; the Polish sheet goes on saying it has none, now as its own answer
    const added = await pressAdd(c, "Epoxy");
    const afterAdd = { added: added, state: state(c), marks: marks(c, "Epoxy") };
    const addReloaded = state(await reload(c));
    const p = await switchJob(c, "polish");
    return { x: x, combo: combo, comboReloaded: comboReloaded, afterAdd: afterAdd, addReloaded: addReloaded, backToPolish: state(p) };
  });

  // ═══ P. AN OPTION MADE A BASE (the round-6 audit's F-C) ═══════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("promotion", async () => {
    const res = {};
    // (a) a TOOL-FILLED line under the job's "no drive": far Combo, Polish picked alone (the Epoxy base is demoted to an option and keeps its own 5 x 6.5), the x on the
    //     Polish drive (the job says it has no drive), then Epoxy made the base by the Sheets panel's pick, and by the intake's job type. The line is released both ways.
    const start = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    await makeBase(start, B.ROOT_TAB);
    const demoted = driveRows(start);
    const xa = await pressX(start, B.ROOT_TAB);
    const savedA = clone(start.store.blob);
    const pick = await reopen(savedA);
    await makeBase(pick, "Epoxy");
    const sw = await reopen(Object.assign(clone(savedA), { work_type: "epoxy" }));
    sw.api.saveSoon();
    sw.clock.fire();
    res.toolUnderJob = { demoted: demoted, x: xa, before: answers(start), pick: state(pick), switched: state(sw), pickReloaded: state(await reload(pick)), switchReloaded: state(await reload(sw)) };

    // (b) a line the estimator ADDED under the job's "no drive": far Polish 4 x 12, an Epoxy sheet added (5 x 12), the x on the Polish drive, Add Travel Labor on the Epoxy
    //     option (its own drive, 5 x 6.5), then Epoxy made the base both ways. The line is kept, and the job has a drive again (round 6, part 3, M3).
    const p = await newBid(POLISH(), [CREW_POLISH]);
    await addSheet(p, "Epoxy");
    typeCrew(p, "Epoxy", "epoxy-install", "5", "12");
    const xb = await pressX(p, B.ROOT_TAB);
    const addedB = await pressAdd(p, "Epoxy");
    const savedB = clone(p.store.blob);
    const pickB = await reopen(savedB);
    await makeBase(pickB, "Epoxy");
    const swB = await reopen(Object.assign(clone(savedB), { work_type: "epoxy" }));
    swB.api.saveSoon();
    swB.clock.fire();
    res.addedUnderJob = { x: xb, added: addedB, marks: marks(p, "Epoxy"), pick: state(pickB), switched: state(swB), pickReloaded: state(await reload(pickB)), switchReloaded: state(await reload(swB)) };
    // ...and made ONE OF A PAIR of bases (the combined pick, and the job type Combo): the job has a drive again, on Epoxy, and the Polish sheet, which has none, goes on saying so as its own
    //     answer (S), so a reload does not give the root a blank line.
    const pairB = await reopen(savedB);
    await makeBase(pairB, "combined");
    const comboB = await reopen(Object.assign(clone(savedB), { work_type: "combo" }));
    comboB.api.saveSoon();
    comboB.clock.fire();
    res.addedUnderJobPair = { pick: state(pairB), switched: state(comboB), pickReloaded: state(await reload(pairB)), switchReloaded: state(await reload(comboB)) };

    // (c) a copy's TOOL-FILLED line under the job's "no drive", and a TYPED one: far Polish 4 x 12 copied (the copy holds the drive the tool filled), the x on the Polish
    //     drive, the copy made the base. Released; and with 3 x 5 typed on the copy's line first, kept.
    const c = await newBid(POLISH(), [CREW_POLISH]);
    const copy = await copySheet(c, B.ROOT_TAB);
    const xc = await pressX(c, B.ROOT_TAB);
    const savedC = clone(c.store.blob);
    const pickC = await reopen(savedC);
    await makeBase(pickC, copy);
    const t = await reopen(savedC);
    const ti = idxIn(secOf(t.api.root(), copy), "travel");
    t.api.show(copy);
    t.api.go(1);
    if (ti >= 0) { P.typeInto(t, '[data-lab="' + ti + '"][data-k="guys"]', "3"); P.typeInto(t, '[data-lab="' + ti + '"][data-k="days"]', "5"); }
    t.api.saveSoon();
    t.clock.fire();
    await makeBase(t, copy);
    res.copyUnderJob = { copy: copy, x: xc, toolPick: state(pickC), typedPick: state(t), typedMarks: marks(t, copy), toolReloaded: state(await reload(pickC)), typedReloaded: state(await reload(t)) };

    // (d) NOT under the job's answer: a tool-filled line is refilled by its new role, and the old base's TYPED line is not swapped onto it. Far Combo, Polish picked alone
    //     (Epoxy an option with its own 5 x 6.5), 3 x 5 typed on the Polish drive, then Epoxy made the base: Epoxy keeps its own crew's drive, the Polish option its typed one.
    const d = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    await makeBase(d, B.ROOT_TAB);
    const di = idxIn(d.api.root(), "travel");
    d.api.show(B.ROOT_TAB);
    d.api.go(1);
    P.typeInto(d, '[data-lab="' + di + '"][data-k="guys"]', "3");
    P.typeInto(d, '[data-lab="' + di + '"][data-k="days"]', "5");
    d.api.saveSoon();
    d.clock.fire();
    await makeBase(d, "Epoxy");
    const dSession = state(d);
    const dReloaded = state(await reload(d));
    await typeMiles(d, 300);
    res.refill = { session: dSession, epoxyMarks: marks(d, "Epoxy"), reloaded: dReloaded, at300: driveRows(d) };
    return res;
  });

  // ═══ A SHEET THAT BECOMES A BASE WITH NO TRAVEL LABOR LINE IS GIVEN ITS OWN (D1) ═══════════════════════════════════════════════════════════════════════════════════
  // Far Polish 4 x 12, the library's Travel at $36 an hour, the Epoxy sheet added (an option: a fresh sheet holds no Travel Labor line) and its crew typed 5 x 12. Then the pair is made the base
  // by the Sheets panel, and the job type made Combo by the intake. The Epoxy sheet becomes a base with no line, so it is given one at the bid's own Travel rate ($36, the root's line's
  // default) and the distance on file fills it on its own crew: 5 x 6.5 x $36 = $1,170. A reload prices the same.
  await section("added", async () => {
    const LAB36 = [Object.assign({}, TRAVEL_ROW, { rate: 36 }), EPOXY_ROW, GYP_ROW];
    const b = await open(POLISH(), { distance: FAR, labor: LAB36 });
    b.api.go(1);
    await settle();
    typeCrew(b, CREW_POLISH[0], CREW_POLISH[1], CREW_POLISH[2], CREW_POLISH[3]);
    await addSheet(b, "Epoxy");
    typeCrew(b, "Epoxy", "epoxy-install", "5", "12");
    b.api.saveSoon();
    b.clock.fire();
    const before = driveRows(b);
    const saved = clone(b.store.blob);
    const again = async (page) => { page.api.saveSoon(); page.clock.fire(); return state(await reopen(clone(page.store.blob), { labor: LAB36 })); };
    const pick = await reopen(saved, { labor: LAB36 });
    await makeBase(pick, "combined");
    const sw = await reopen(Object.assign(clone(saved), { work_type: "combo" }), { labor: LAB36 });
    sw.api.saveSoon();
    sw.clock.fire();
    return { before: before, pick: state(pick), pickMarks: marks(pick, "Epoxy"), switched: state(sw), switchMarks: marks(sw, "Epoxy"),
      pickReloaded: await again(pick), switchReloaded: await again(sw) };
  });

  // ═══ A COPY OF A SHEET IS A NEW SHEET: it takes neither the sheet's own answer (S) nor the mark of a line the estimator added ═══════════════════════════════════════════
  await section("copies", async () => {
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const x = await pressX(b, "Epoxy");
    const first = await copySheet(b, "Epoxy");
    const afterFirst = { answers: answers(b), rows: driveRows(b) };
    const added = await pressAdd(b, "Epoxy");
    const second = await copySheet(b, "Epoxy");
    return { x: x, added: added, first: first, second: second, afterFirst: afterFirst, answers: answers(b), rows: driveRows(b),
      epoxyMarks: marks(b, "Epoxy"), secondMarks: second ? marks(b, second) : null };
  });

  // ═══ THE LIBRARY'S DECLINE ON A NEW COMBO IS EACH SHEET'S OWN ANSWER (S) ═══════════════════════════════════════════════════════════════════════════════════════════
  // The library's Travel row put on Polish bids only, then on Epoxy bids only: a new far Combo seeds the drive on the sheet the library puts it on, and the other sheet says it has none, as
  // its own answer and not the job's. A reload agrees.
  await section("declined", async () => {
    const bid = async (types) => {
      const lab = [Object.assign({}, TRAVEL_ROW, { default_work_types: types }), EPOXY_ROW, GYP_ROW];
      const b = await open(COMBO(), { distance: FAR, labor: lab });
      b.api.go(1);
      await settle();
      [CREW_POLISH, CREW_EPOXY].forEach((c) => typeCrew(b, c[0], c[1], c[2], c[3]));
      b.api.saveSoon();
      b.clock.fire();
      const r = await reopen(clone(b.store.blob), { labor: lab });
      return { session: state(b), quiet: { armed: r.clock.armed(), saves: r.rec.saves.length }, reloaded: state(r) };
    };
    return { polishOnly: await bid(["polish"]), epoxyOnly: await bid(["epoxy"]) };
  });

  // ═══ A COMBO SAVED UNDER THE ONE-DRIVE LAW (before round 7) ═══════════════════════════════════════════════════════════════════════════════════════════════════════
  // The job's one drive sat on the carrier, for the bigger crew (Epoxy's 5 here), and the Epoxy sheet holds no Travel Labor line. Opened plainly, nothing is asked, and since round
  // 7, part 4 (P4) the Epoxy base is given its own drive on open, filled by the rule on its own crew (5 x 6.5), which the open saves once (the pass-2 audit's A1): until then it offered Add
  // Travel Labor and priced no drive. Switched to Epoxy,
  // the Epoxy base keeps that drive, and the reload prices the same. Made Polish, the root keeps its own. (test_polish_travel_round7_part4.py holds the rest: the session, the reloads, a sheet
  // that said it has none, and the one-drive carry on a model that never went through the open.)
  await section("legacy", async () => {
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const saved = clone(b.store.blob);
    const pe = saved.polish_estimate;
    pe.tabs.Epoxy.labor = pe.tabs.Epoxy.labor.filter((r) => !(r && r.id === "travel"));
    pe.labor.filter((r) => r && r.id === "travel").forEach((r) => { r.guys = 5; });
    const o = await reopen(saved);
    const opened = { quiet: { armed: o.clock.armed(), saves: o.rec.saves.length }, rows: driveRows(o), epoxy: await laborFacts(o, "Epoxy"),
      bid: { root: o.api.bid().total, epoxy: (o.api.sectionBids().Epoxy || {}).total } };
    const e = await reopen(Object.assign(clone(saved), { work_type: "epoxy" }));
    e.api.saveSoon();
    e.clock.fire();
    const toEpoxy = { state: state(e), marks: marks(e, "Epoxy"), reloaded: state(await reload(e)) };
    const p = await reopen(Object.assign(clone(saved), { work_type: "polish" }));
    p.api.saveSoon();
    p.clock.fire();
    const toPolish = { state: state(p), reloaded: state(await reload(p)) };
    // ...and with the Sheets panel: Epoxy picked alone, the Polish root an option that keeps its own drive (a copy goes to Epoxy)
    const k = await reopen(saved);
    await makeBase(k, "Epoxy");
    const picked = { state: state(k), reloaded: state(await reload(k)) };
    return { opened: opened, toEpoxy: toEpoxy, toPolish: toPolish, picked: picked };
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
