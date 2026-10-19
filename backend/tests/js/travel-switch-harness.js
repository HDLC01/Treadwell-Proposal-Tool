"use strict";
/* THE JOB'S ONE DRIVE, ON THE REAL ESTIMATE PAGE: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with
 * the REAL js/bid-model.js beneath it. Every fact below is read off the page after it ran: the model it held, the panels it drew, what
 * it saved. Nothing is a source assertion.
 *
 * The 2026-10-20 audit of 77b5fbb (the far distance fills Travel Labor, Kyle's way: one round trip for each guy of the crew). Each
 * finding is a section here, and test_polish_travel_switch.py holds them to the numbers (Wichita, 190 miles, a crew of 4: $858):
 *   1  A JOB TYPE SWITCHED IN THE SESSION (the intake's choice reaching the estimate page) or a base change on the Sheets panel gives
 *      the bid a new carrier, and the job's ONE drive is priced ONCE, on the crew's size: Epoxy to Polish, Epoxy to Combo (no second
 *      charge), Gyp to Polish, the Sheets panel's Epoxy to the combined pair, and a typed row the old carrier keeps.
 *   2  Combo to Epoxy: the Travel Labor row goes with the carrier.
 *   4  The answers are handed the WHOLE model (ROOT), never the section on show (M): a panel left on another section.
 *   6  An option copy's Travel Labor follows its OWN lines.
 *   7  The Review's trip sentence is repainted when a late answer lands on it.
 *   8  The notes: a cleared Guys box, and typed guys, are worded as guys.
 * (3, a saved bid on the older man-days auto with no hours, is a model rule and is held in travel-hours-harness.js.)
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason; the
 * mutation runs in the test count a section error as a failure of the mutation, never as the mutation being noticed.
 *
 * Usage: node travel-switch-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-switch-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "MODEL"]);

// The library's labor lines: Travel (built in), one Epoxy crew line, one Gyp pour. The Polish crew (Polishing, Mock-up, Joint filler) is the
// shipped fallback the page adds when the library lists none of them.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true,
  default_work_types: [], default_on: true };
const EPOXY_ROW = { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true,
  default_work_types: ["epoxy"], default_on: true };
const GYP_ROW = { id: "gyp-pour", name: "Gyp pour", rate: 33, unit: "hours", guys_auto: false, sort: 2, favorite: true,
  default_work_types: ["gyp"], default_on: true };
const LABOR = [TRAVEL_ROW, EPOXY_ROW, GYP_ROW];
const GYP_TAB = 'Gyp (USG 1-8")';

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const LOST = { ok: false, miles: null, reason: "not_found" };   // the lookup has no answer
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } },
  ADDR, extra || {}));
const epoxyDraft = () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const comboDraft = () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const gypDraft = () => draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 });
const polishDraft = () => draftOf("polish", { polish_sf: 5000 });

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await flush(); };

/** A page on a draft. `extra.distance` is what the lookup answers (a NEW bid asks by itself, a saved one does not). */
async function open(blob, extra) {
  const b = P.build(Object.assign({ blob: blob, labor: LABOR }, extra || {}));
  await b.api.init();
  await settle();
  return b;
}

// ── reading the page (every reader answers null for what is not there: a break changes a fact, it never crashes the run) ────
const secOf = (m, tab) => (tab === B.ROOT_TAB ? m : (m.tabs || {})[tab]);
const rowIn = (sec) => ((sec && sec.labor) || []).filter((r) => r.id === "travel")[0] || null;
const idxIn = (sec, id) => (sec && sec.labor ? sec.labor.findIndex((r) => r.id === id) : -1);
const boxOf = (b, i, k) => { const el = b.doc.querySelector('[data-lab="' + i + '"][data-k="' + k + '"]'); return el ? String(el.value) : null; };
const textOf = (b, sel) => { const el = b.doc.querySelector(sel); return el ? el.textContent : null; };
const hiddenOf = (b, sel) => { const el = b.doc.querySelector(sel); return el ? !!el.hidden : null; };
const rowFacts = (r) => (r ? { guys: r.guys, days: r.days, auto: !!r.guys_auto, follow: r.guys_follow === undefined ? null : r.guys_follow,
  seed: r.hours_seed === undefined ? null : r.hours_seed, typed: r.guys_typed === true, hoursTyped: r.hours_typed === true,
  cost: B.laborCost(r) } : null);

/** What the job holds, from the WHOLE model: its carrier, and for every section its kind and its Travel Labor row. The job's drive is
 *  priced once when only one row of the sections that are part of the bid has a cost: `pricedOn` lists them and `travelDollars` sums them. */
function jobFacts(b) {
  const m = b.api.root();
  const entries = B.sectionsOf(m);
  const live = entries.filter((e) => e.kind !== "off");
  const rows = {};
  entries.forEach((e) => { rows[e.tab] = { kind: e.kind, row: rowFacts(rowIn(e.section)), count: (e.section.labor || []).filter((r) => r.id === "travel").length }; });
  return { carrier: B.travelCarrier(m), jobType: B.baseOf(m).jobType, kinds: entries.map((e) => [e.tab, e.kind]), rows: rows,
    pricedOn: live.filter((e) => rowIn(e.section) && B.laborCost(rowIn(e.section)) > 0).map((e) => e.tab),
    travelDollars: live.reduce((t, e) => t + (rowIn(e.section) ? B.laborCost(rowIn(e.section)) : 0), 0),
    distance: m.distance && m.distance.miles, lodging: !!(m.travel && m.travel.lodging.enabled), perDiem: !!(m.travel && m.travel.per_diem.enabled),
    saves: b.rec.saves.length, asked: (b.rec.distanceBodies || []).length,
    laborTotals: Object.fromEntries(live.map((e) => [e.tab, B.laborTotal(e.section.labor, m.conditions, 0)])) };
}

/** The Travel Labor card of the section that carries the job's travel, as the Labor step draws it: boxes, hint, note, how-note. */
function cardFacts(b) {
  const m = b.api.root();
  const i = idxIn(secOf(m, B.travelCarrier(m)), "travel");
  if (i < 0) return null;
  return { guysBox: boxOf(b, i, "guys"), hoursBox: boxOf(b, i, "days"), hint: textOf(b, '[data-hint-lab="' + i + '"]'),
    note: { text: textOf(b, "[data-trv-src]"), hidden: hiddenOf(b, "[data-trv-src]") }, how: textOf(b, "[data-trv-how]") };
}

/** The crew typed on the sheet `tab`, line `rowId`, through the boxes of the Labor step on screen. */
function typeCrew(b, tab, rowId, guys, days) {
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

/** The saved draft reopened on another job type: what the intake's choice does when it reaches the estimate page. The lookup would say
 *  300 miles, which a saved bid never asks for. */
async function reopenAs(saved, workType, extra) {
  const b = await open(Object.assign(clone(saved), { work_type: workType }), Object.assign({ distance: { ok: true, miles: 300, reason: "" } }, extra || {}));
  b.api.go(1);
  await settle();
  return b;
}

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

async function main() {
  // A NEW far Epoxy bid, crew 4 x 12 on Epoxy install, saved: the bid the Epoxy switches below start from.
  const epoxy = await newBid(epoxyDraft(), ["Epoxy", "epoxy-install", "4", "12"]);
  await section("epoxyBid", async () => jobFacts(epoxy.page));

  // ═══ 1. A JOB TYPE SWITCHED IN THE SESSION: the job's one drive is priced once, on the crew's size ═══════════════════════════
  // Epoxy to Polish: the Polish root (never seeded on an Epoxy job: its Travel Labor row is the shipped model's older man-days auto row)
  // is the new carrier.
  await section("epoxyToPolish", async () => {
    const b = await reopenAs(epoxy.saved, "polish");
    const open = { job: jobFacts(b), card: cardFacts(b) };
    typeCrew(b, B.ROOT_TAB, "polishing", "4", "12");
    return { open: open, wichita: { job: jobFacts(b), card: cardFacts(b) }, manDays: B.travelManDays(b.api.root().labor), crew: B.crewSize(b.api.root()) };
  });

  // Epoxy to Combo: the root is the new carrier and Epoxy is still a base. One row priced, not two.
  await section("epoxyToCombo", async () => {
    const b = await reopenAs(epoxy.saved, "combo");
    const open = { job: jobFacts(b), card: cardFacts(b) };
    typeCrew(b, B.ROOT_TAB, "polishing", "4", "12");
    const res = { open: open, wichita: { job: jobFacts(b), card: cardFacts(b) } };
    // ...and the Epoxy sheet's own Labor step: the row it was left holding says the drive is charged on the Polish sheet.
    b.api.show("Epoxy");
    b.api.go(1);
    const ei = idxIn(b.api.root().tabs.Epoxy, "travel");
    res.epoxyStep = { note: textOf(b, '[data-trv-stray="' + ei + '"]'), hint: textOf(b, '[data-hint-lab="' + ei + '"]'),
      genericHint: /There the hours fill in/.test(b.doc.getElementById("panels").innerHTML), cardCost: textOf(b, '[data-lcost-for="' + ei + '"]') };
    b.clock.fire();
    res.saved = Object.fromEntries(B.sectionsOf(clone(b.store.blob.polish_estimate)).map((e) => [e.tab, rowFacts(rowIn(e.section))]));
    // A plain reopen of THAT saved bid, as the job type it is now: nothing moves, nothing is saved or asked.
    const again = await reopenAs(b.store.blob, "combo");
    res.reopened = { job: jobFacts(again), card: cardFacts(again) };
    return res;
  });

  // A plain reopen of the Epoxy bid as the job type it already is changes nothing: no restructure, no save, no lookup.
  await section("epoxyPlain", async () => jobFacts(await reopenAs(epoxy.saved, "epoxy")));

  // Gyp to Polish: a Gyp carrier is never filled (the Gyp sheet works its own drive time), and the Polish root, holding the older row, is.
  await section("gypToPolish", async () => {
    const gyp = await newBid(gypDraft(), [GYP_TAB, "gyp-pour", "4", "12"]);
    const res = { gyp: jobFacts(gyp.page), gypCard: textOf(gyp.page, "[data-trv-src]") };
    const b = await reopenAs(gyp.saved, "polish");
    const open = { job: jobFacts(b), card: cardFacts(b) };
    typeCrew(b, B.ROOT_TAB, "polishing", "4", "12");
    return Object.assign(res, { open: open, wichita: { job: jobFacts(b), card: cardFacts(b) } });
  });

  // ═══ 2. COMBO TO EPOXY: the Travel Labor row goes with the carrier ═════════════════════════════════════════════════════════
  await section("comboToEpoxy", async () => {
    const combo = await newBid(comboDraft(), ["Polish", "polishing", "4", "12"]);
    // (the Epoxy sheet's own crew, typed through its own Labor step)
    combo.page.api.show("Epoxy");
    combo.page.api.go(1);
    typeCrew(combo.page, "Epoxy", "epoxy-install", "5", "12");
    combo.page.clock.fire();
    const res = { combo: jobFacts(combo.page) };
    const b = await reopenAs(combo.page.store.blob, "epoxy");
    res.open = { job: jobFacts(b), card: cardFacts(b) };
    typeCrew(b, "Epoxy", "epoxy-install", "4", "12");
    res.wichita = { job: jobFacts(b), card: cardFacts(b) };
    b.clock.fire();
    // ...and saved: the reopened bid is as it was left, with nothing moved or saved again.
    const again = await reopenAs(b.store.blob, "epoxy");
    res.reopened = { job: jobFacts(again), card: cardFacts(again) };
    return res;
  });

  // ═══ 1b. A TYPED ROW THE OLD CARRIER KEEPS is left as typed, and its card says so ═══════════════════════════════════════════
  await section("typedToCombo", async () => {
    const typed = await newBid(epoxyDraft(), ["Epoxy", "epoxy-install", "4", "12"]);
    const ti = idxIn(typed.page.api.root().tabs.Epoxy, "travel");
    typeCrew(typed.page, "Epoxy", "travel", "3", "5");
    typed.page.clock.fire();
    const b = await reopenAs(typed.page.store.blob, "combo");
    typeCrew(b, B.ROOT_TAB, "polishing", "4", "12");
    const job = jobFacts(b);
    b.api.show("Epoxy");
    b.api.go(1);
    const i = idxIn(b.api.root().tabs.Epoxy, "travel");
    const res = { job: job, epoxyStep: { note: textOf(b, '[data-trv-stray="' + i + '"]'), guysBox: boxOf(b, i, "guys"), hoursBox: boxOf(b, i, "days") } };
    // Typing in the leftover row changes what its card says (an empty one says to leave it empty; a typed one says it was left as typed).
    typeCrew(b, "Epoxy", "travel", "", "");
    res.cleared = { note: textOf(b, '[data-trv-stray="' + i + '"]') };
    res.typedAt = ti;
    return res;
  });

  // ═══ 1c. THE SHEETS PANEL'S BASE CHANGE is a carrier move too: Epoxy base with Polish an option, made the combined pair ═════
  await section("sheetsCombined", async () => {
    const optionBlob = clone(epoxy.saved);
    optionBlob.polish_estimate.kind = "option";
    const b = await open(optionBlob, { distance: { ok: true, miles: 300, reason: "" } });
    b.api.go(1);
    await settle();
    const before = jobFacts(b);
    b.doc.fire("change", { target: P.need(b, '[data-sh-base="combined"]') });
    P.clickOn(b, '[data-sh-act="base-yes"]');
    await settle();
    b.api.show(B.ROOT_TAB);            // the Polish root now carries the job's travel: open its Labor step
    b.api.go(1);
    typeCrew(b, B.ROOT_TAB, "polishing", "4", "12");
    return { before: before, after: jobFacts(b), card: cardFacts(b) };
  });

  // ═══ 4. THE ANSWERS GET THE WHOLE MODEL, WHATEVER IS ON SHOW ═══════════════════════════════════════════════════════════════
  // A Combo whose Labor step (the carrier's: the Polish root, with the miles box) is drawn, and then another section is put on show
  // WITHOUT a redraw: a panel left up while M is a view of the Epoxy section. The box is still there to type in, press and clear.
  await section("wholeModel", async () => {
    const noMiles = await newBid(comboDraft(), ["Polish", "polishing", "4", "12"], LOST);
    const farCombo = await newBid(comboDraft(), ["Polish", "polishing", "4", "12"], FAR);
    const staleOpen = async (saved, extra) => {
      const b = await open(clone(saved), extra);
      b.api.go(1);
      await settle();
      b.api.show("Epoxy");             // M is now a view of the Epoxy section; the panel on screen is still the Polish one
      return b;
    };
    const rootRow = (b) => rowFacts(rowIn(b.api.root()));
    const typedMiles = await staleOpen(noMiles.saved);
    if (typedMiles.doc.querySelector("[data-dist-miles]")) P.typeInto(typedMiles, "[data-dist-miles]", "190");
    const lookedUp = await staleOpen(farCombo.saved, { distance: { ok: true, miles: 300, reason: "" } });
    if (lookedUp.doc.querySelector("[data-dist-lookup]")) P.clickOn(lookedUp, "[data-dist-lookup]");
    await settle();
    const clearedMiles = await staleOpen(farCombo.saved);
    const clearedBefore = rootRow(clearedMiles);
    if (clearedMiles.doc.querySelector("[data-dist-miles]")) P.typeInto(clearedMiles, "[data-dist-miles]", "");
    return {
      noMilesBefore: rowFacts(rowIn(noMiles.page.api.root())),
      typed: { row: rootRow(typedMiles), distance: typedMiles.api.root().distance && typedMiles.api.root().distance.miles },
      lookup: { row: rootRow(lookedUp), distance: lookedUp.api.root().distance && lookedUp.api.root().distance.miles },
      cleared: { before: clearedBefore, after: rootRow(clearedMiles), distance: clearedMiles.api.root().distance === undefined ? null : clearedMiles.api.root().distance },
    };
  });

  // ═══ 6. AN OPTION COPY'S TRAVEL LABOR FOLLOWS ITS OWN LINES ════════════════════════════════════════════════════════════════
  const copyOf = async (page, tab) => {
    const sel = '[data-sh-act="copy"][data-sh-tab="' + tab + '"]';
    if (page.doc.querySelector(sel)) P.clickOn(page, sel);
    await settle();
    page.api.go(1);
    await settle();
  };
  await section("optionCopy", async () => {
    const polish = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
    await copyOf(polish.page, "Polish");
    const copyId = Object.keys(polish.page.api.root().tabs || {})[0];
    const copyBefore = rowFacts(rowIn(secOf(polish.page.api.root(), copyId)));
    typeCrew(polish.page, copyId, "polishing", "6", "12");
    const copySec = secOf(polish.page.api.root(), copyId);
    const i = idxIn(copySec, "travel");
    return { id: copyId, kind: copySec.kind, copyBefore: copyBefore, copyAfter: rowFacts(rowIn(copySec)), root: rowFacts(rowIn(polish.page.api.root())),
      crewOfJob: B.crewSize(polish.page.api.root()), guysBox: boxOf(polish.page, i, "guys"), hint: textOf(polish.page, '[data-hint-lab="' + i + '"]'),
      note: textOf(polish.page, "[data-trv-src]"), strayNote: textOf(polish.page, '[data-trv-stray="' + i + '"]') };
  });
  // A Combo's option copy says "above": its guys are its own section's lines, not "the base sheets'".
  await section("comboOptionCopy", async () => {
    const combo = await newBid(comboDraft(), ["Polish", "polishing", "4", "12"]);
    await copyOf(combo.page, "Polish");
    const copyId = Object.keys(combo.page.api.root().tabs || {}).filter((k) => k !== "Epoxy")[0];
    typeCrew(combo.page, copyId, "polishing", "6", "12");
    const row = rowIn(secOf(combo.page.api.root(), copyId));
    const i = idxIn(secOf(combo.page.api.root(), copyId), "travel");
    const res = { hint: textOf(combo.page, '[data-hint-lab="' + i + '"]'), note: textOf(combo.page, "[data-trv-src]"), guys: row && row.guys,
      jobCrew: B.crewSize(combo.page.api.root()) };
    // ...and the Review of that option says the same in its trip sentence
    combo.page.api.go(2);
    await settle();
    res.review = textOf(combo.page, '[data-rv="lab.' + i + '.drive"]');
    return res;
  });

  // ═══ 7. THE REVIEW'S TRIP SENTENCE IS REPAINTED WHEN A LATE ANSWER LANDS ON IT ══════════════════════════════════════════════
  await section("reviewLate", async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    const b = await open(epoxyDraft(), { distance: FAR, distanceGate: gate });
    b.api.go(1);
    await settle();
    typeCrew(b, "Epoxy", "epoxy-install", "4", "12");
    b.api.go(2);
    await settle();
    const cell = (k) => textOf(b, '[data-rv="' + k + '"]');
    const at = () => idxIn(b.api.root().tabs.Epoxy, "travel");
    const snap = () => ({ q: cell("lab." + at() + ".q"), tot: cell("lab." + at() + ".tot"), drive: cell("lab." + at() + ".drive") });
    const before = snap();
    release();
    await settle();
    return { before: before, after: snap(), step: b.api.at() };
  });

  // ═══ 8. THE NOTES SAY GUYS WHEN THE GUYS ARE TYPED, AND SAY EMPTY WHEN THEY ARE CLEARED ═════════════════════════════════════
  await section("notes", async () => {
    const run = async (text) => {
      const b = await open(polishDraft(), { distance: FAR });
      b.api.go(1);
      await settle();
      typeCrew(b, B.ROOT_TAB, "polishing", "4", "12");
      const i = idxIn(b.api.root(), "travel");
      if (text !== null && b.doc.querySelector('[data-lab="' + i + '"][data-k="guys"]')) P.typeInto(b, '[data-lab="' + i + '"][data-k="guys"]', text);
      return { row: rowFacts(rowIn(b.api.root())), card: cardFacts(b), box: boxOf(b, i, "guys") };
    };
    return { typed: await run("2"), cleared: await run(""), crewFollowing: await run(null) };
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
