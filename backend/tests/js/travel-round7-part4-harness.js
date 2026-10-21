"use strict";
/* ROUND 7, PART 4 (2026-10-21): THE ROUND-7 AUDIT'S REMAINING FINDINGS, run on the REAL estimate page: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with the
 * REAL js/bid-model.js beneath it. Every fact below is read off the page after it ran (the model it held, the panels it drew, what it saved). Nothing is a source assertion. EVERY REOPEN IS A
 * JSONB REOPEN (tests/js/_jsonb.js): the draft comes back as the drafts table hands it. test_polish_travel_round7_part4.py holds each fact and breaks a COPY of the page or the model one line at a
 * time to prove each can change. (Part 3's F1 is held by travel-round7-part3-harness.js, where part 4's P1 was withdrawn by the pass-2 audit's A2.)
 *
 *   mobs     P2 (F2): A GYP DRIVE IS A ROUND TRIP FOR EACH MOBILIZATION, as Kyle's Gyp travel line multiplies the round trip by them (Gyp (USG 1-8")!B51 `=((B6*2)/60)*T28`). Far Gyp
 *            (190 miles), crew 4 x 120 hours: the drive is 4 x 6.5 with the Mobilizations box blank and 4 x 19.5 with 3 typed; it follows the box both ways, moves with the miles (3 x 10 at
 *            300 miles), keeps hours the estimator typed, and a copy of the Gyp sheet follows its own box. The table (`sheet`) is the model's drive hours beside the sheet's own B51 for
 *            90, 180, 190 and 300 miles at 1 to 4 mobilizations.
 *   bothX    P3 (F3): THE x ON BOTH DRIVES OF A COMBO IS THE JOB'S ANSWER (J), as the x on a single-base job's drive is: a later job-type switch keeps the drive removed (D3), a new Gyp section
 *            included; Add Travel Labor on a base takes it back.
 *   legacy   P4 (F7): A FAR COMBO SAVED UNDER THE ONE-DRIVE LAW (its one drive on the carrier, no line and no answer on the Epoxy base) OPENS WITH THE EPOXY BASE'S DRIVE FILLED BY THE RULE (D1
 *            and "let them re-price"): the open, the session and a jsonb reload price two drives; the carrier keeps its own crew's drive. One whose Epoxy x was pressed (S) is left as it is.
 *            `guard`: the model handed the old shape without the open (B.followDistance alone) still carries the job's one drive to the one base left, on that base's crew.
 *            THE PASS-2 AUDIT'S A1: the open SAVES a drive it gives that prices something (`openSave`, `leftAtOnce`: the timer, and the page left inside the debounce window), so the price the
 *            Review and the Proposal read is the price the bar shows; and the job's one drive the estimator switched off, or whose Guys or Hours box they cleared, is said on the line the Epoxy
 *            base is given too, so no drive they took away comes back and nothing is saved (`said`: off, clearedHours, clearedGuys, beside `removed`, the same bid with no drive at all, and
 *            `typed`, figures typed, which the Epoxy crew's own drive does not take; `typedLocal` the same at 40 miles, where the line given is empty and the open writes nothing).
 *   addTarget P5 (F4): ADD TRAVEL LABOR PUTS THE LINE ON THE SHEET IT WAS PRESSED ON, though another sheet is put on show while the library answers.
 *   words    P6 (F5): AFTER THE x ON THE CARRIER'S OWN DRIVE OF A COMBO the carrier's Labor step says THIS SHEET has no Travel Labor line and that the Epoxy sheet keeps its own, never that the bid
 *            has none or that the drive adds nothing; after the x on both drives (J) it says the bid has none.
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason.
 *
 * Usage: node travel-round7-part4-harness.js <frontend-dir>   ->  one line of JSON
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
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-round7-part4-harness.js");
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
const AT = (miles) => ({ ok: true, miles: miles, reason: "" });
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const COMBO = () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const POLISH = () => draftOf("polish", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const GYP = () => draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 });
const CREW_POLISH = ["Polish", "polishing", "4", "12"];
const CREW_EPOXY = ["Epoxy", "epoxy-install", "5", "12"];
const CREW_GYP = [GYP_TAB, "gyp-pour", "4", "120"];

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await flush(); };

/** A page on a draft. `extra.distance` is what the lookup answers (a NEW bid asks by itself, a saved one does not). */
async function open(blob, extra) {
  const opts = Object.assign({ blob: blob, labor: LABOR }, extra || {});
  const b = P.build(opts);
  await b.api.init();
  await settle();
  b.opts = opts;           // what the library and the lookup answer is read from here each time the page asks, so a step can change it after the page is open
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

/** The job's answer (J) and each sheet's own (S), as the model holds them. */
function answersOf(m) {
  const sheets = {};
  B.sectionsOf(m).forEach((e) => { if (e.section && e.section.sheet_no_travel_labor === true) sheets[e.tab] = true; });
  return { job: m.no_travel_labor === true, sheets: sheets };
}
const answers = (b) => answersOf(b.api.root());

/** Every section's Travel Labor row, by `tab:kind`, as a short string. */
function rowsOf(m) {
  return Object.fromEntries(B.sectionsOf(m).map((e) => [e.tab + ":" + e.kind, driveText(rowIn(e.section))]));
}
const driveRows = (b) => rowsOf(b.api.root());

/** The markers on one section's Travel Labor row: who filled it, whose it is. */
function marks(b, tab) {
  const r = rowIn(secOf(b.api.root(), tab));
  return r ? { auto: r.guys_auto === true, follow: r.guys_follow || null, seed: r.hours_seed === undefined ? null : r.hours_seed, typed: r.guys_typed === true || r.hours_typed === true,
    hand: r.hand_added === true } : null;
}

/** What one section's Travel Labor row says, box by box: its figures, its switch, and which box the estimator's hand is on. */
function says(b, tab) {
  const r = rowIn(secOf(b.api.root(), tab));
  return r ? { guys: r.guys, hours: r.days, on: r.enabled !== false, guysTyped: r.guys_typed === true, hoursTyped: r.hours_typed === true, follow: r.guys_follow || null } : null;
}

/** The figure the bid bar shows, as a number (the whole job's lump sum on a bid of several sheets), or null when it shows none. */
function barOf(b) {
  const el = b.doc.getElementById("bid-total");
  const n = el ? Number(String(el.textContent).replace(/[^0-9.]/g, "")) : NaN;
  return isFinite(n) && n > 0 ? n : null;
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

/** The estimator types in the Travel Labor line of the section `tab`, on its Labor step: `say` is { guys, hours, rate }, each typed when it is given. Answers whether there was a line to type in. */
function typeDrive(b, tab, say) {
  b.api.show(tab);
  b.api.go(1);
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  if (i < 0) return false;
  const box = (k) => '[data-lab="' + i + '"][data-k="' + k + '"]';
  if (say.guys !== undefined && has(b, box("guys"))) P.typeInto(b, box("guys"), say.guys);
  if (say.hours !== undefined && has(b, box("days"))) P.typeInto(b, box("days"), say.hours);
  if (say.rate !== undefined && has(b, box("rate"))) P.typeInto(b, box("rate"), say.rate);
  b.api.saveSoon();
  b.clock.fire();
  return true;
}

/** The Mobilizations box of the Gyp card, typed on the Material step of the section `tab`. Answers whether the card drew it. */
function typeMobs(b, tab, value) {
  b.api.show(tab);
  b.api.go(0);
  if (!has(b, '[data-gyp="mobs"]')) return false;
  P.typeInto(b, '[data-gyp="mobs"]', value);
  b.api.saveSoon();
  b.clock.fire();
  return true;
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

/** The page's draft, saved now, reopened through the server, with whether the reopen armed a save. */
async function reload(b) {
  b.api.saveSoon();
  b.clock.fire();
  const r = await reopen(clone(b.store.blob));
  r.quiet = { armed: r.clock.armed(), saves: r.rec.saves.length };
  return r;
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

/** The x on the Travel Labor line of the section `tab`. Answers false when the page draws no such x. */
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

/** The switch on the Travel Labor line of the section `tab`, flipped on its card. Answers whether the page drew it. */
function flipDrive(b, tab) {
  b.api.show(tab);
  b.api.go(1);
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  if (i < 0 || !has(b, '[data-on-lab="' + i + '"]')) return false;
  P.clickOn(b, '[data-on-lab="' + i + '"]');
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

/** What the Labor step of the section `tab` draws about the drive: the Travel Labor card's note on where its hours came from and its fill words, the travel block's caption, the Add Travel
 *  Labor control with the words above it, and the how-it-is-worked-out note. */
async function laborFacts(b, tab) {
  b.api.show(tab);
  b.api.go(1);
  await settle();
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  const html = panelHtml(b);
  const cap = /<p class="cap">(Travel is expected[^<]*)<\/p>/.exec(html);
  const cardNote = /<p class="hint trvnote">(Drive time is expected[^<]*)<\/p>/.exec(html);
  const none = /<div class="trvadd" data-trv-none[^>]*><p class="cap">([^<]*)<\/p>/.exec(html);
  return { src: i >= 0 ? textOf(b, '[data-trv-src="' + i + '"]') : null, cap: cap ? cap[1] : null, cardNote: cardNote ? cardNote[1] : null,
    add: has(b, "[data-add-travel]"), none: attrOf(b, "[data-trv-none]", "data-trv-none"), noneWords: none ? none[1] : null, how: textOf(b, "[data-trv-how]") };
}

/** The Gyp card's Mobilizations hint, on the Material step of the section `tab`. */
async function mobsHint(b, tab) {
  b.api.show(tab);
  b.api.go(0);
  await settle();
  const m = /data-gyp="mobs"[^>]*>\s*<p class="hint">([^<]*)<\/p>/.exec(panelHtml(b));
  return m ? m[1] : null;
}

/** The Review's trip sentence under the Travel Labor row of the section `tab`. */
async function reviewTrip(b, tab) {
  b.api.show(tab);
  b.api.go(2);
  await settle();
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  return i >= 0 ? textOf(b, '[data-rv="lab.' + i + '.drive"]') : null;
}

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

/** WHAT THE ESTIMATOR SAID ON THE JOB'S ONE DRIVE of a Combo saved under the one-drive law, said on the Polish carrier's card by the page itself before the Epoxy line is taken off: the switch flipped
 *  off, the Hours box cleared, the Guys box cleared, 7 guys x 3.25 hours typed; and `removed`, the x on it (the job's answer, J), which the one-drive law left as no line at all. */
const ONE_DRIVE_SAYS = {
  off: (b) => flipDrive(b, B.ROOT_TAB),
  clearedHours: (b) => typeDrive(b, B.ROOT_TAB, { hours: "" }),
  clearedGuys: (b) => typeDrive(b, B.ROOT_TAB, { guys: "" }),
  typed: (b) => typeDrive(b, B.ROOT_TAB, { guys: "7", hours: "3.25" }),
  removed: (b) => pressX(b, B.ROOT_TAB),
};

/** A FAR COMBO SAVED UNDER THE ONE-DRIVE LAW (before round 7): built from a Combo made now, its Epoxy base's Travel Labor line taken off and the job's one drive on the Polish root for the bigger
 *  crew (Epoxy's 5), as the one-drive law left it, and SAVED THAT WAY BY THE PAGE, so the draft holds the one-drive price (its lump sum and each sheet's total, which the Review and the Proposal
 *  read) as a Combo saved before round 7 does: far Polish 4 x 12 and Epoxy 5 x 12 at 190 miles, $90,422. `extra` is put on the Epoxy section (its own answer, for one), `miles` is the distance it
 *  was saved on, and `say` (ONE_DRIVE_SAYS) is what the estimator said on the job's one drive before it was saved. */
async function oneDriveCombo(extra, miles, polishCrew, say) {
  const crew = polishCrew || CREW_POLISH;
  const b = await newBid(COMBO(), [crew, CREW_EPOXY], miles === undefined ? FAR : AT(miles));
  if (say) await ONE_DRIVE_SAYS[say](b);
  const m = b.api.root();
  m.tabs.Epoxy.labor = m.tabs.Epoxy.labor.filter((r) => !(r && r.id === "travel"));
  // the one drive was the bigger crew's (a Guys box the estimator typed in, or cleared, holds what they left)
  m.labor.filter((r) => r && r.id === "travel" && r.guys_follow === "crew").forEach((r) => { r.guys = Math.max(Number(crew[2]), Number(CREW_EPOXY[2])); });
  // the x on the job's one drive was the JOB's answer: the one-drive law left no line and no answer on any sheet
  if (say === "removed") { delete m.sheet_no_travel_labor; m.no_travel_labor = true; }
  Object.assign(m.tabs.Epoxy, extra || {});
  b.api.saveSoon();
  b.clock.fire();
  return clone(b.store.blob);
}

/** THE OPEN OF A COMBO SAVED UNDER THE ONE-DRIVE LAW, as the estimator meets it (the pass-2 audit's A1): what the page armed and showed before anything ran, what the open saved once its timer
 *  ran (the price the Review and the Proposal read), a jsonb reload of that, and 300 miles typed after it. */
async function openOneDrive(saved) {
  const o = await reopen(saved);
  const opened = { armed: o.clock.armed(), saves: o.rec.saves.length, bar: barOf(o), rows: driveRows(o), polish: says(o, B.ROOT_TAB), epoxy: says(o, "Epoxy"), answers: answers(o) };
  o.clock.fire();
  const kept = { saves: o.rec.saves.length, lump: lumpOf(o.store.blob) };
  const r = await reopen(clone(o.store.blob));
  const reloaded = { quiet: { armed: r.clock.armed(), saves: r.rec.saves.length }, bar: barOf(r), rows: driveRows(r), epoxy: says(r, "Epoxy") };
  await typeMiles(r, 300);
  const at300 = { rows: driveRows(r), bar: barOf(r) };
  return { opened: opened, kept: kept, reloaded: reloaded, at300: at300 };
}

async function main() {
  // ═══ P2 (F2). A GYP DRIVE IS A ROUND TRIP FOR EACH MOBILIZATION ═════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("mobs", async () => {
    const b = await newBid(GYP(), [CREW_GYP]);
    const blank = { rows: driveRows(b), src: (await laborFacts(b, GYP_TAB)).src, nights: B.jobNights(b.api.root()).count, price: prices(b) };
    const typed3 = typeMobs(b, GYP_TAB, "3");
    const three = { rows: driveRows(b), marks: marks(b, GYP_TAB), nights: B.jobNights(b.api.root()).count, price: prices(b) };
    const labor = await laborFacts(b, GYP_TAB);
    const trip = await reviewTrip(b, GYP_TAB);
    const hint = await mobsHint(b, GYP_TAB);
    // a jsonb reload prices the same, and opens quietly
    const r = await reload(b);
    const reloaded = { quiet: r.quiet, state: state(r) };
    // the miles move it, three trips at a time: 300 miles, 3 x 10 hours; in the session and after the reload alike
    await typeMiles(b, 300);
    await typeMiles(r, 300);
    const at300 = { session: driveRows(b), reload: driveRows(r) };
    await typeMiles(b, 190);
    // the box cleared: one trip again
    typeMobs(b, GYP_TAB, "");
    const cleared = driveRows(b);
    // a figure the estimator typed is theirs: 5 hours typed, then 2 mobilizations, then 300 miles
    typeDrive(b, GYP_TAB, { hours: "5" });
    typeMobs(b, GYP_TAB, "2");
    await typeMiles(b, 300);
    const typedHours = { rows: driveRows(b), marks: marks(b, GYP_TAB) };
    // a copy of the Gyp sheet (an option, priced apart) follows its OWN Mobilizations box: far Gyp with 3 typed, copied, and 2 typed on the copy
    const c = await newBid(GYP(), [CREW_GYP]);
    typeMobs(c, GYP_TAB, "3");
    const copy = await copySheet(c, GYP_TAB);
    const copied = driveRows(c);
    const copyTyped2 = copy ? typeMobs(c, copy, "2") : false;
    const copyState = { rows: driveRows(c), mobs: copy ? ((secOf(c.api.root(), copy) || {}).gyp || {}).mobs : null };
    const cr = await reload(c);
    const copyReloaded = { quiet: cr.quiet, rows: driveRows(cr) };
    // ...and a later answer (300 miles) reaches each by its own count of trips: the base 3 x 10, the copy 2 x 10
    await typeMiles(cr, 300);
    const copyAt300 = driveRows(cr);
    // the x on the Gyp drive, and Add Travel Labor: the line it brings back is filled for the mobilizations on the card (3 trips)
    const x = await newBid(GYP(), [CREW_GYP]);
    typeMobs(x, GYP_TAB, "3");
    const xPressed = await pressX(x, GYP_TAB);
    const addPressed = await pressAdd(x, GYP_TAB);
    const readded = { x: xPressed, add: addPressed, rows: driveRows(x), marks: marks(x, GYP_TAB) };
    // a far job at 180 miles, whose round trip is a whole 6 hours: 3 trips are the sheet's own 18
    const s = await newBid(GYP(), [CREW_GYP], AT(180));
    typeMobs(s, GYP_TAB, "3");
    const at180 = driveRows(s);
    // THE TABLE: the model's drive hours for a far answer of `miles` with `mobs` on the Gyp card, beside the Gyp sheet's own travel hours (B51: the miles there and back over 60 mph, times the
    // mobilizations). Model-level: the saved Gyp bid, its Mobilizations box set, the distance answered.
    const saved = clone(s.store.blob);
    const table = [];
    [90, 180, 190, 300].forEach((miles) => {
      [1, 2, 3, 4].forEach((mobs) => {
        const m = B.withSectionOrder(B.migrateModel(clone(saved.polish_estimate)), saved.priced_tabs);
        const g = secOf(m, GYP_TAB);
        g.gyp = Object.assign({}, g.gyp, { mobs: String(mobs) });
        const row = rowIn(g);
        // the row the tool filled, given back to the answer
        if (row) { row.days = ""; delete row.hours_seed; }
        B.applyDistance(m, { miles: miles, source: "typed", key: "" });
        const r2 = rowIn(secOf(m, GYP_TAB));
        table.push({ miles: miles, mobs: mobs, hours: r2 ? r2.days : null, sheet: ((miles * 2) / 60) * mobs });
      });
    });
    return { blank: blank, typed3: typed3, three: three, labor: labor, trip: trip, hint: hint, reloaded: reloaded, at300: at300, cleared: cleared, typedHours: typedHours,
      copy: copy, copied: copied, copyTyped2: copyTyped2, copyState: copyState, copyReloaded: copyReloaded, copyAt300: copyAt300, readded: readded, at180: at180, table: table };
  });

  // ═══ P3 (F3). THE x ON BOTH DRIVES OF A COMBO IS THE JOB'S ANSWER (J) ═══════════════════════════════════════════════════════════════════════════════════════════════
  await section("bothX", async () => {
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const x1 = await pressX(b, "Epoxy");
    const afterOne = answers(b);
    const x2 = await pressX(b, B.ROOT_TAB);
    const afterBoth = state(b);
    const r = await reload(b);
    const reloaded = { quiet: r.quiet, state: state(r) };
    // the job type moved, three times: Epoxy, then Gyp (a new section), then Polish, then Combo again. No base is given a drive.
    const e = await switchJob(b, "epoxy");
    const toEpoxy = state(e);
    const g = await switchJob(e, "gyp");
    const toGyp = state(g);
    const p = await switchJob(g, "polish");
    const toPolish = state(p);
    const c = await switchJob(p, "combo");
    typeCrew(c, "Epoxy", "epoxy-install", "5", "12");
    c.api.saveSoon();
    c.clock.fire();
    const toCombo = state(c);
    // ...and from the other end: the x on the carrier's drive first, then Epoxy's
    const o = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    await pressX(o, B.ROOT_TAB);
    await pressX(o, "Epoxy");
    const otherOrder = answers(o);
    // Add Travel Labor on a base takes the job's answer back; the other base says it has none as its own answer again
    const added = await pressAdd(c, "Epoxy");
    const afterAdd = { state: state(c), marks: marks(c, "Epoxy") };
    const ar = await reload(c);
    return { x1: x1, x2: x2, afterOne: afterOne, afterBoth: afterBoth, reloaded: reloaded, toEpoxy: toEpoxy, toGyp: toGyp, toPolish: toPolish, toCombo: toCombo, otherOrder: otherOrder,
      added: added, afterAdd: afterAdd, addReloaded: state(ar) };
  });

  // ═══ P4 (F7). A FAR COMBO SAVED UNDER THE ONE-DRIVE LAW OPENS WITH EVERY BASE'S DRIVE ═══════════════════════════════════════════════════════════════════════════════════
  await section("legacy", async () => {
    const saved = await oneDriveCombo();
    const o = await reopen(saved);
    const opened = { quiet: { armed: o.clock.armed(), saves: o.rec.saves.length }, rows: driveRows(o), answers: answers(o), marks: marks(o, "Epoxy"),
      bid: { root: o.api.bid().total, epoxy: (o.api.sectionBids().Epoxy || {}).total }, epoxy: await laborFacts(o, "Epoxy") };
    // THE OPEN SAVES WHAT IT GIVES (the pass-2 audit's A1): nothing typed, the save the open armed runs, and the draft holds the price the bar shows, which is what the Review and the Proposal
    // read; and the page left at once (Continue to proposal inside the debounce window) writes it on the way out.
    const shown = barOf(o);
    o.clock.fire();
    const openSave = { bar: shown, saves: o.rec.saves.length, lump: lumpOf(o.store.blob), pricedTabs: (o.store.blob.priced_tabs || []).map((t) => [t.id, t.kind, t.total]) };
    const quick = await reopen(saved);
    const quickBar = barOf(quick);
    quick.win.fire("pagehide");
    const leftAtOnce = { bar: quickBar, flushed: quick.rec.flushed, saves: quick.rec.saves.length, lump: lumpOf(quick.store.blob) };
    // WHAT THE ESTIMATOR SAID ON THE JOB'S ONE DRIVE (the pass-2 audit's A1): switched off, its Hours or Guys box cleared, figures typed; and the same bid with no drive at all (the x)
    const said = {};
    for (const k of ["off", "clearedHours", "clearedGuys", "typed", "removed"]) said[k] = await openOneDrive(await oneDriveCombo(undefined, undefined, undefined, k));
    // ...and figures typed on the one drive of a job 40 miles out (typed hours are priced on a local job): the Epoxy line is given empty, so only the carrier's own drive is priced
    said.typedLocal = await openOneDrive(await oneDriveCombo(undefined, 40, undefined, "typed"));
    // the session goes on (the crew retyped) and saves; a jsonb reload of what it saved, and of the draft as it was saved under the one-drive law, price the same
    typeCrew(o, "Epoxy", "epoxy-install", "5", "12");
    const session = state(o);
    const r = await reload(o);
    const again = await reopen(saved);
    // made Epoxy by the intake, and Epoxy picked alone: the Epoxy base keeps its own drive; made Polish, the root keeps its own
    const e = await reopen(Object.assign(clone(saved), { work_type: "epoxy" }));
    e.api.saveSoon();
    e.clock.fire();
    const p = await reopen(Object.assign(clone(saved), { work_type: "polish" }));
    p.api.saveSoon();
    p.clock.fire();
    // the same Combo whose Epoxy x was pressed (the sheet's own answer, S): left as it is
    const s = await reopen(await oneDriveCombo({ sheet_no_travel_labor: true }));
    const sheetSaid = { quiet: { armed: s.clock.armed(), saves: s.rec.saves.length }, rows: driveRows(s), answers: answers(s) };
    // the same Combo on a local job (40 miles): the Epoxy base is given its line, and the rule fills nothing into it
    const l = await reopen(await oneDriveCombo(undefined, 40), { distance: AT(40) });
    const local = { rows: driveRows(l), quiet: { armed: l.clock.armed(), saves: l.rec.saves.length } };
    // THE GUARD (model-level): the old shape handed to the model WITHOUT the open's fill, the job type Epoxy, and B.followDistance alone: the job's one drive goes to the one base left, on ITS
    // crew. The Polish crew is 6 here, so the one drive was 6 guys and the Epoxy crew's own 5 is the one a carried drive must be put on.
    const old6 = await oneDriveCombo(undefined, undefined, ["Polish", "polishing", "6", "12"]);
    const m0 = B.withSectionOrder(B.migrateModel(clone(old6.polish_estimate)), old6.priced_tabs);
    const kinds = B.sectionKinds(m0);
    const m1 = B.sectionsForJob(m0, "epoxy", { rules: [] });
    B.followDistance(m1, B.ROOT_TAB, kinds);
    return { opened: opened, openSave: openSave, leftAtOnce: leftAtOnce, said: said, session: session, sessionReloaded: { quiet: r.quiet, state: state(r) }, savedReloaded: state(again),
      toEpoxy: state(e), toPolish: state(p), sheetSaid: sheetSaid, local: local, guard: { rows: rowsOf(m1), answers: answersOf(m1) } };
  });

  // ═══ P5 (F4). ADD TRAVEL LABOR GOES ON THE SHEET IT WAS PRESSED ON ═════════════════════════════════════════════════════════════════════════════════════════════════
  await section("addTarget", async () => {
    // Add pressed on the sheet `from`, the sheet `to` put on show while the library answers, and the library let answer.
    const slow = async (b, from, to) => {
      let open_ = null;
      b.opts.laborGate = new Promise((res) => { open_ = res; });
      b.api.show(from);
      b.api.go(1);
      const drawn = has(b, "[data-add-travel]");
      if (drawn) P.clickOn(b, "[data-add-travel]");
      await settle();
      b.api.show(to);
      b.api.go(1);
      await settle();
      open_();
      await settle();
      delete b.opts.laborGate;
      b.api.saveSoon();
      b.clock.fire();
      return drawn;
    };
    // (a) far Combo, the x on the Epoxy drive, Add pressed on Epoxy, the Polish sheet (which holds its line) opened while the library answers
    const a = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    await pressX(a, "Epoxy");
    const pressedA = await slow(a, "Epoxy", B.ROOT_TAB);
    // (the Polish root is still the sheet on show: the page's view of the root is the model itself)
    const sideA = { pressed: pressedA, rootOnShow: a.api.model() === a.api.root(), state: state(a), marks: marks(a, "Epoxy") };
    const ar = await reload(a);
    // (b) the x on both drives (the job's answer), Add pressed on Epoxy, the Polish sheet (no line either) opened while the library answers
    const bb = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    await pressX(bb, "Epoxy");
    await pressX(bb, B.ROOT_TAB);
    const pressedB = await slow(bb, "Epoxy", B.ROOT_TAB);
    const sideB = { pressed: pressedB, state: state(bb), marks: marks(bb, "Epoxy") };
    // (c) the other way round: the x on the Polish drive, Add pressed on Polish, the Epoxy sheet opened while the library answers
    const c = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    await pressX(c, B.ROOT_TAB);
    const pressedC = await slow(c, B.ROOT_TAB, "Epoxy");
    const sideC = { pressed: pressedC, state: state(c), marks: marks(c, B.ROOT_TAB) };
    return { a: sideA, aReloaded: { quiet: ar.quiet, state: state(ar) }, b: sideB, c: sideC };
  });

  // ═══ P6 (F5). THE CARRIER'S OWN DRIVE TAKEN AWAY ON A COMBO: THE WORDS SAY THIS SHEET HAS NO LINE ══════════════════════════════════════════════════════════════════════
  await section("words", async () => {
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const x = await pressX(b, B.ROOT_TAB);
    const carrier = await laborFacts(b, B.ROOT_TAB);
    const epoxyDrive = driveRows(b)["Epoxy:base"];
    const r = await reload(b);
    const reloaded = await laborFacts(r, B.ROOT_TAB);
    // ...and with both drives taken away the job has none (J): the words say the bid has no line
    await pressX(b, "Epoxy");
    const both = await laborFacts(b, B.ROOT_TAB);
    // a single-base job's x (J), as before
    const p = await newBid(POLISH(), [CREW_POLISH]);
    await pressX(p, B.ROOT_TAB);
    const single = await laborFacts(p, B.ROOT_TAB);
    // A SHEET NAME THE ESTIMATOR TYPED is said as text, never as markup (round 7, pass-2 audit A3): the carrier's words name the other base by its label.
    const h = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    h.api.root().tabs.Epoxy.label = '<b data-x="1">Big</b> Epoxy';
    await pressX(h, B.ROOT_TAB);
    await laborFacts(h, B.ROOT_TAB);
    const block = /<div class="trvadd"[^>]*>[\s\S]*?<\/div>/.exec(panelHtml(h));
    const hostile = { block: !!block, raw: !!block && block[0].indexOf('<b data-x=') >= 0, escaped: !!block && block[0].indexOf("&lt;b data-x=") >= 0 };
    return { x: x, carrier: carrier, epoxyDrive: epoxyDrive, reloaded: reloaded, both: both, single: single, hostile: hostile };
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
