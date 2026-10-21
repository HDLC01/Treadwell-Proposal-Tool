"use strict";
/* ROUND 7 POLISH (2026-10-22), W1 TO W4: THE TRAVEL WORDS AND THE DRIVE SWITCH, run on the REAL estimate page: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it,
 * with the REAL js/bid-model.js beneath it. Every fact below is read off the page after it ran (the model it held, the panels it drew, what it saved). Nothing is a source assertion. EVERY
 * REOPEN IS A JSONB REOPEN (tests/js/_jsonb.js). test_polish_travel_words_polish.py holds each fact and breaks a COPY of the page or the model one line at a time to prove each can change.
 *
 * The real-browser walk of staging on 2026-10-22 passed every round-7 behaviour and found these, all staff-facing, prices right:
 *
 *   w1  A BASE THAT DRIVES ON ITS OWN AND HOLDS NO TRAVEL LABOR LINE (its x took the line away) was told "This sheet's guys drive on their own: its Travel Labor below is one round trip for each
 *       of them" directly above "This sheet has no Travel Labor line", and its Review said "This sheet's own drive is its Travel Labor line, under Labor". With no line the Hotel and Per Diem
 *       sentence is all that is left. A sheet that holds its line keeps both notes whole; an option's words are its own.
 *   w2  A DRIVE OF SEVERAL ROUND TRIPS (a far Gyp with its Mobilizations typed) said "one round trip each" in the summary ("Guys = the most guys on any one labor line above (4 now), one round
 *       trip each.") and under a typed Guys box ("One round trip for each guy.") while three round trips each are charged. The words say the trips the price uses.
 *   w3  A NEW COMBO WHOSE LIBRARY DECLINED TRAVEL (both bases carry their own answer, S) had the carrier say "The Epoxy sheet keeps its own Travel Labor line" while its working says "Travel
 *       Labor on the Epoxy sheet: no line on that sheet, $0". The words name only the bases that hold a line.
 *   w4  A DRIVE LINE SWITCHED OFF KEEPS ITS HOURS while a later answer (the miles, the Gyp card's Mobilizations) leaves an off line alone, so switching it back ON priced a stale figure, with
 *       mobilizations N trips long. A line the TOOL filled is filled again by the rule from the distance and trips on file when it is switched back on; a figure the estimator typed stays
 *       theirs, a line the tool never filled is left for the estimator to fill, and every price is the price of the same bid that was never switched off.
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason.
 *
 * Usage: node travel-words-polish-harness.js <frontend-dir>   ->  one line of JSON
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
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-words-polish-harness.js");
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
const AT = (miles) => ({ ok: true, miles: miles, reason: "" });
const FAR = AT(190);          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
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
/** The text a browser shows for words the page wrote through its esc(): the five entities it writes, `&amp;` last so nothing is decoded twice. */
const shown = (s) => s.replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

/** Every section's Travel Labor row, by `tab:kind`, as a short string. */
function driveRows(b) {
  const m = b.api.root();
  return Object.fromEntries(B.sectionsOf(m).map((e) => [e.tab + ":" + e.kind, driveText(rowIn(e.section))]));
}

/** The markers on one section's Travel Labor row: who filled it, and who put it there. */
function marks(b, tab) {
  const r = rowIn(secOf(b.api.root(), tab));
  return r ? { auto: r.guys_auto === true, follow: r.guys_follow || null, seed: r.hours_seed === undefined ? null : r.hours_seed, typed: r.guys_typed === true || r.hours_typed === true,
    on: r.enabled !== false } : null;
}

/** Every price the page holds: the root sheet's own bid and what a save writes (the lump sum). A save is forced, so run it after everything else is read. */
function prices(b) {
  const root = b.api.bid();
  b.api.saveSoon();
  b.clock.fire();
  return { lump: lumpOf(b.store.blob), root: root.total };
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

/** The estimator types in the Travel Labor line of the section `tab`, on its Labor step: `say` is { guys, hours }, each typed when it is given. Answers whether there was a line to type in. */
function typeDrive(b, tab, say) {
  b.api.show(tab);
  b.api.go(1);
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  if (i < 0) return false;
  const box = (k) => '[data-lab="' + i + '"][data-k="' + k + '"]';
  if (say.guys !== undefined && has(b, box("guys"))) P.typeInto(b, box("guys"), say.guys);
  if (say.hours !== undefined && has(b, box("days"))) P.typeInto(b, box("days"), say.hours);
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
async function newBid(blob, crews, distance, extra) {
  const b = await open(blob, Object.assign({ distance: distance || FAR }, extra || {}));
  b.api.go(1);
  await settle();
  (crews || []).forEach((c) => typeCrew(b, c[0], c[1], c[2], c[3]));
  b.api.saveSoon();
  b.clock.fire();
  return b;
}

/** The saved draft reopened on a page of its own, on the Labor step, AS THE DRAFTS TABLE HANDS IT BACK (jsonb key order). The lookup would say 300 miles, which a saved bid never asks for. */
async function reopen(saved, extra) {
  const b = await open(J.reloaded(saved), Object.assign({ distance: AT(300) }, extra || {}));
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

/** The switch on a labor line of the section `tab` (the Travel Labor line unless `rowId` says another), flipped on its card. Answers whether the page drew it. */
function flip(b, tab, rowId) {
  b.api.show(tab);
  b.api.go(1);
  const i = idxIn(secOf(b.api.root(), tab), rowId || "travel");
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

/** What the Labor step of the section `tab` says about the drive: the note under Travel (a section that does not carry the job's travel), the Add Travel Labor control with the words above it,
 *  the how-it-is-worked-out note, the Travel Labor card's hint under its Guys box and its note on where its hours came from. */
async function laborFacts(b, tab) {
  b.api.show(tab);
  b.api.go(1);
  await settle();
  const i = idxIn(secOf(b.api.root(), tab), "travel");
  const html = panelHtml(b);
  const none = /<div class="trvadd" data-trv-none[^>]*><p class="cap">([^<]*)<\/p>/.exec(html);
  return { note: textOf(b, "[data-travel-note]"), add: has(b, "[data-add-travel]"), none: attrOf(b, "[data-trv-none]", "data-trv-none"), noneWords: none ? shown(none[1]) : null,
    how: textOf(b, "[data-trv-how]"), hint: i >= 0 ? textOf(b, '[data-hint-lab="' + i + '"]') : null, src: i >= 0 ? textOf(b, '[data-trv-src="' + i + '"]') : null };
}

/** The sentence the Hotel and Per Diem card of the Review says in its first row, for a section that does not carry the job's travel: the note about where Hotel and Per Diem are charged. */
async function reviewNote(b, tab) {
  b.api.show(tab);
  b.api.go(2);
  await settle();
  const html = panelHtml(b);
  const card = html.indexOf('data-rev="travel"');
  const end = card >= 0 ? html.indexOf("</table>", card) : -1;
  const m = card >= 0 && end > card ? /<tbody><tr[^>]*><td>([^<]*)<\/td>/.exec(html.slice(card, end)) : null;
  return m ? shown(m[1]) : null;
}

/** The "Guys = ..." line of the how-it-is-worked-out note, or null when it says none. */
const guysLine = (how) => String(how || "").split("\n").filter((l) => l.indexOf("Guys = ") === 0)[0] || null;

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

async function main() {
  // ═══ W1. A BASE THAT HOLDS NO TRAVEL LABOR LINE IS NOT TOLD ITS GUYS DRIVE ON THEIR OWN ═════════════════════════════════════════════════════════════════════════════
  await section("w1", async () => {
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const words = async (page, tab) => { const l = await laborFacts(page, tab); return { note: l.note, noneWords: l.noneWords, add: l.add, review: await reviewNote(page, tab) }; };
    const withLine = await words(b, "Epoxy");
    const x = await pressX(b, "Epoxy");
    const noLine = await words(b, "Epoxy");
    const reloaded = await words(await reload(b), "Epoxy");
    // the carrier carries the job's Hotel and Per Diem, so it has no note about another sheet
    const carrier = await words(b, B.ROOT_TAB);
    // Add Travel Labor brings the line back and the words with it
    const added = await pressAdd(b, "Epoxy");
    const afterAdd = await words(b, "Epoxy");
    // an option holds no line of its own: its words are its own (it is priced apart), and say nothing about guys that drive on their own
    const copy = await copySheet(b, "Epoxy");
    const xo = copy ? await pressX(b, copy) : false;
    const option = copy ? await words(b, copy) : null;
    return { withLine: withLine, x: x, noLine: noLine, reloaded: reloaded, carrier: carrier, added: added, afterAdd: afterAdd, copy: copy, xo: xo, option: option };
  });

  // ═══ W2. A DRIVE OF SEVERAL ROUND TRIPS SAYS THE TRIPS THE PRICE USES ═════════════════════════════════════════════════════════════════════════════════════════════════
  await section("w2", async () => {
    const b = await newBid(GYP(), [CREW_GYP]);
    const read = async () => { const l = await laborFacts(b, GYP_TAB); return { guys: guysLine(l.how), hint: l.hint, row: driveRows(b)[GYP_TAB + ":base"] }; };
    const one = await read();                       // the Mobilizations box blank: one round trip
    const typed3 = typeMobs(b, GYP_TAB, "3");
    const three = await read();                     // three round trips of 6.5 hours, 19.5, for each guy
    const how = (await laborFacts(b, GYP_TAB)).how;
    typeDrive(b, GYP_TAB, { guys: "4" });
    const guysTyped = await read();                 // the Guys box typed: the hint under it says what the hours are
    typeMobs(b, GYP_TAB, "2");
    const twoTrips = await read();                  // the box moves the hours, and the words follow it
    typeDrive(b, GYP_TAB, { hours: "5" });
    const hoursTyped = await read();                // the hours are the estimator's: they are not trips of the tool's
    // a Polish bid and a Combo's drive are one round trip each, and say so
    const p = await newBid(POLISH(), [CREW_POLISH]);
    const pl = await laborFacts(p, B.ROOT_TAB);
    typeDrive(p, B.ROOT_TAB, { guys: "4" });
    const polish = { guys: guysLine(pl.how), hint: (await laborFacts(p, B.ROOT_TAB)).hint };
    return { one: one, typed3: typed3, three: three, how: how, guysTyped: guysTyped, twoTrips: twoTrips, hoursTyped: hoursTyped, polish: polish };
  });

  // ═══ W3. THE WORDS NAME ONLY THE BASES THAT HOLD A TRAVEL LABOR LINE ═════════════════════════════════════════════════════════════════════════════════════════════════
  await section("w3", async () => {
    // The library's Travel row says no on every work type: a NEW far Combo is seeded with no drive, and each base says it has none as its own answer (S).
    const declinedLabor = [Object.assign({}, TRAVEL_ROW, { favorite: false }), EPOXY_ROW, GYP_ROW];
    const b = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY], FAR, { labor: declinedLabor });
    const answers = { rows: driveRows(b), sheets: B.sectionsOf(b.api.root()).filter((e) => e.section && e.section.sheet_no_travel_labor === true).map((e) => e.tab), job: b.api.root().no_travel_labor === true };
    const carrier = await laborFacts(b, B.ROOT_TAB);
    const epoxy = await laborFacts(b, "Epoxy");
    const epoxyNote = await reviewNote(b, "Epoxy");
    const reloaded = await laborFacts(await reload(b), B.ROOT_TAB);
    // ...and a Combo whose Epoxy sheet still holds its line keeps naming it after the x on the Polish drive (round 7, part 4, P6)
    const k = await newBid(COMBO(), [CREW_POLISH, CREW_EPOXY]);
    const x = await pressX(k, B.ROOT_TAB);
    const kept = await laborFacts(k, B.ROOT_TAB);
    // ...and with the Epoxy line gone too, the job has no drive (J) and the words say the bid has none
    await pressX(k, "Epoxy");
    const both = await laborFacts(k, B.ROOT_TAB);
    return { answers: answers, carrier: carrier, epoxy: epoxy, epoxyNote: epoxyNote, reloaded: reloaded, x: x, kept: kept, both: both };
  });

  // ═══ W4. A TOOL-FILLED DRIVE LINE SWITCHED BACK ON IS FILLED AGAIN BY THE RULE ═══════════════════════════════════════════════════════════════════════════════════════
  await section("w4", async () => {
    const res = {};
    // (a) THE MILES MOVE WHILE THE LINE IS OFF. Far Polish 4 x 12 at 190 miles: 4 x 6.5. The switch off, 300 miles typed (an off line is left alone), the switch on: 4 x 10, and the price is
    //     the price of the same bid that was never switched off.
    const a = await newBid(POLISH(), [CREW_POLISH]);
    const aBefore = driveRows(a);
    const aOff = flip(a, B.ROOT_TAB);
    await typeMiles(a, 300);
    const aStale = { rows: driveRows(a), marks: marks(a, B.ROOT_TAB) };
    const aOn = flip(a, B.ROOT_TAB);
    const aDone = { rows: driveRows(a), marks: marks(a, B.ROOT_TAB), price: prices(a) };
    const aNever = await newBid(POLISH(), [CREW_POLISH], AT(300));
    const aReload = await reload(a);
    res.miles = { before: aBefore, off: aOff, stale: aStale, on: aOn, done: aDone, never: { rows: driveRows(aNever), price: prices(aNever) },
      reloaded: { rows: driveRows(aReload), price: prices(aReload) } };

    // (b) THE MOBILIZATIONS MOVE WHILE THE LINE IS OFF. Far Gyp, 3 typed: 4 x 19.5. Off, 2 typed (an off line is left alone), on: 4 x 13, three trips no longer.
    const g = await newBid(GYP(), [CREW_GYP]);
    typeMobs(g, GYP_TAB, "3");
    const gBefore = driveRows(g)[GYP_TAB + ":base"];
    flip(g, GYP_TAB);
    typeMobs(g, GYP_TAB, "2");
    const gStale = driveRows(g)[GYP_TAB + ":base"];
    flip(g, GYP_TAB);
    const gDone = { row: driveRows(g)[GYP_TAB + ":base"], marks: marks(g, GYP_TAB), price: prices(g) };
    const gNever = await newBid(GYP(), [CREW_GYP]);
    typeMobs(gNever, GYP_TAB, "2");
    res.trips = { before: gBefore, stale: gStale, done: gDone, never: { row: driveRows(gNever)[GYP_TAB + ":base"], price: prices(gNever) } };

    // (c) WHAT THE ESTIMATOR TYPED STAYS THEIRS. Hours typed (5): off, 300 miles, on: still 4 x 5. Guys typed (7) over the tool's hours: the hours are filled again (7 x 10), the guys stay.
    const t = await newBid(POLISH(), [CREW_POLISH]);
    typeDrive(t, B.ROOT_TAB, { hours: "5" });
    flip(t, B.ROOT_TAB);
    await typeMiles(t, 300);
    flip(t, B.ROOT_TAB);
    const typedHours = { rows: driveRows(t), marks: marks(t, B.ROOT_TAB) };
    const u = await newBid(POLISH(), [CREW_POLISH]);
    typeDrive(u, B.ROOT_TAB, { guys: "7" });
    flip(u, B.ROOT_TAB);
    await typeMiles(u, 300);
    flip(u, B.ROOT_TAB);
    const typedGuys = { rows: driveRows(u), marks: marks(u, B.ROOT_TAB) };
    res.typed = { hours: typedHours, guys: typedGuys };

    // (d) THE JOB WENT LOCAL WHILE THE LINE WAS OFF. 40 miles typed: the line is left alone while it is off, and the tool's hours go back to empty when it is switched on (the rule at 40 miles
    //     fills nothing), as they would have had it been on.
    const l = await newBid(POLISH(), [CREW_POLISH]);
    flip(l, B.ROOT_TAB);
    await typeMiles(l, 40);
    const lStale = driveRows(l);
    flip(l, B.ROOT_TAB);
    const lDone = { rows: driveRows(l), marks: marks(l, B.ROOT_TAB), price: prices(l) };
    const lNever = await newBid(POLISH(), [CREW_POLISH], AT(40));
    res.local = { stale: lStale, done: lDone, never: { rows: driveRows(lNever), price: prices(lNever) } };

    // (e) AN OPTION'S OWN DRIVE (a copy of the Polish sheet, priced apart) is refilled the same way: 300 miles while it is off, then on. And gone local, an option's fill nobody touched goes
    //     back WHOLE (the rule of a row off the bases: guys and hours both empty), where a base keeps its guys.
    const o = await newBid(POLISH(), [CREW_POLISH]);
    const copy = await copySheet(o, B.ROOT_TAB);
    const optBefore = driveRows(o)[copy + ":option"];
    flip(o, copy);
    await typeMiles(o, 300);
    const optStale = driveRows(o)[copy + ":option"];
    flip(o, copy);
    const optDone = driveRows(o)[copy + ":option"];
    flip(o, copy);
    await typeMiles(o, 40);
    flip(o, copy);
    const optLocal = { row: driveRows(o)[copy + ":option"], marks: marks(o, copy) };
    res.option = { copy: copy, before: optBefore, stale: optStale, done: optDone, local: optLocal };

    // (f) A LINE THE TOOL NEVER FILLED IS NOT FILLED BY THE SWITCH. A far saved bid whose Travel Labor line is blank and off (the library's default, or the estimator): the switch brings it back
    //     blank, as it always did, for the estimator to fill (the how-note says to type the guys and the hours).
    const nb = await newBid(POLISH(), [CREW_POLISH]);
    const saved = clone(nb.store.blob);
    const sr = saved.polish_estimate.labor.filter((r) => r && r.id === "travel")[0];
    sr.days = "";
    delete sr.hours_seed;
    sr.enabled = false;
    const blank = await reopen(saved);
    const blankBefore = { rows: driveRows(blank), marks: marks(blank, B.ROOT_TAB) };
    flip(blank, B.ROOT_TAB);
    res.blank = { before: blankBefore, after: { rows: driveRows(blank), marks: marks(blank, B.ROOT_TAB), price: prices(blank) } };

    // (g) A CREW LINE'S SWITCH IS NOT A DRIVE: Polish switched off and on again moves no price and no figure on the drive.
    const c = await newBid(POLISH(), [CREW_POLISH]);
    const cBefore = { rows: driveRows(c), price: prices(c) };
    flip(c, B.ROOT_TAB, "polishing");
    flip(c, B.ROOT_TAB, "polishing");
    res.crew = { before: cBefore, after: { rows: driveRows(c), price: prices(c) } };
    return res;
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
