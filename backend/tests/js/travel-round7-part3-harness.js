"use strict";
/* ROUND 7, PART 3 (2026-10-21): ONE FIGURE THE ESTIMATOR TYPED IS PRICED ON ONE BASE (the round-7 audit's F1), run on the REAL estimate page: js/polish-estimate.js, whole, booted the way
 * polish-estimate-harness.js boots it, with the REAL js/bid-model.js beneath it. Every fact below is read off the page after it ran (the model it held, what it priced, what it saved). Nothing is
 * a source assertion. EVERY REOPEN IS A JSONB REOPEN (tests/js/_jsonb.js): the draft comes back as the drafts table hands it. test_polish_travel_round7_part3.py holds each fact and breaks a COPY
 * of the model one line at a time to prove each can change.
 *
 * THE FINDING. Far (190 miles) Polish, crew 4 x 12, its Travel Labor typed 7 guys x 3.25 hours ($750.75). An Epoxy sheet added (crew 5 x 12) and made the base: the job's one drive follows its one
 * base, so the Epoxy base takes a COPY of the typed row and the demoted Polish option keeps its own (round 6). Then the job type Combo (or "Make Epoxy + Polish the base"): both are bases, and since
 * Hanz's D1 of 2026-10-21 each base keeps its own drive, so the Epoxy crew of 5 was priced the Polish crew's typed 7 x 3.25 on top of the Polish row ($90,416), a figure nobody typed for that sheet.
 * Round 6 gave the repeat back ($88,911, the Epoxy crew with no drive at all).
 *
 * THE RULE (round 7, part 3). A Travel Labor row the TOOL copied (the job's one drive following a base pick while the old base keeps its own, or a Sheets copy of a sheet) is marked as the tool's copy
 * (`tool_copy`), and the mark goes the moment the estimator types in the row (its Guys, Hours or Rate box). When a sheet becomes a base beside another base and a base's row is the tool's copy of what
 * the other base's row says (the same typed or cleared guys and hours, typed rate and switch), the copy is GIVEN BACK and the base drives its own crew (D1): one figure the estimator typed once is
 * priced on one base. Of two copies, the one on the sheet that became a base gives its back. The copy given back is EMPTY AND NOBODY'S, at its line's own default rate, and the distance on file
 * refills it on its own crew, like every base's drive nobody typed on. (Part 4's P1 kept the trip the estimator typed on the copy given back, its hours marked typed and its rate; the pass-2 audit's
 * A2 found that it priced one typed trip on the Epoxy crew by one route only, the pick and then the Combo, where the pair made at once, the intake's Combo and a new Combo gave that crew the rule's
 * trip, and that it froze hours nobody typed on that sheet, so a local job went on charging them. Withdrawn: every way a base arrives beside a typed drive gives it the rule's drive.) The sections:
 *   picked     the finding, by the intake's job type and by the pair made on the Sheets panel: Polish keeps 7 x 3.25, Epoxy is its own crew of 5 on the rule's round trip, 5 x 6.5 = $1,072.50, the
 *              bid priced exactly as the same sheets made the pair at once (`direct`, the natural oracle: the Epoxy sheet never handed a copy, and nothing typed on it)
 *   routes     the pass-2 audit's A2: the intake's job type Combo straight from the typed Polish bid, and a new Combo whose Polish drive is typed, give the Epoxy crew the same drive; and the
 *              pick-then-Combo and the pair made at once follow 300 miles and then a local 40 alike (the Epoxy crew's drive moves, then is taken back; the typed one stays)
 *   epoxyFirst far Epoxy typed, a Polish sheet added and made the base, then the pair
 *   sheetCopy  far Polish typed, the sheet copied, the job made Epoxy (the typed drive goes with it), then the copy and Epoxy made the pair: the copy gives its repeat back
 *   copyAlone  a copy made the base by itself keeps the typed row, as its source prices; and beside an Epoxy base that does not hold it, it keeps it still
 *   handTyped  a far Combo whose two drives the estimator typed alike, on each sheet (4 x 4), keeps both through a pick and the pair again: no copy, nothing given back
 *   retyped    the estimator types in the Epoxy base's copy before the Combo: it is theirs on that sheet, and stays
 *   hoursOnly  only the hours typed (the guys on the crew): the copy given back is refilled from the miles, its hours the rule's
 *   noTrip     no hours typed (the guys alone, a rate alone, the Hours box cleared): the copy given back is refilled from the miles on its own crew, at its own default rate
 *   rated      the rate typed ($40) as well: the copy given back is filled at its own default rate ($33); typed again on the copy, it is the estimator's there and stays at $40
 *   twoCopies  two copies on the two bases (an Epoxy drive copied to a Polish sheet, then to a second Epoxy sheet): the one on the sheet that became a base gives its repeat back
 *   fillCopied the distance's own fill copied by the pick: nothing the estimator said, so it is not marked, and each crew drives its own
 *   diverged   the original changed after the pick (other guys, other hours, another rate, switched off): the copy says something no other base says, and stays
 *   switched   the copy's switch flipped on its own card makes it the estimator's on that sheet: both drives off, the Combo leaves both off
 *   added      a drive the estimator added (Add Travel Labor) and typed, copied by the pick: given back, the copy loses the mark of an added line
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason.
 *
 * Usage: node travel-round7-part3-harness.js <frontend-dir>   ->  one line of JSON
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
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-round7-part3-harness.js");
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

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const COMBO = () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const POLISH = () => draftOf("polish", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
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
const has = (b, sel) => !!b.doc.querySelector(sel);
const lumpOf = (blob) => (blob && blob.proposal_lump_sum !== undefined && blob.proposal_lump_sum !== null ? blob.proposal_lump_sum : blob && blob.computed_bid ? blob.computed_bid.lump_sum : null);
const driveText = (r) => (r ? r.guys + " x " + r.days + " = $" + B.laborCost(r) : null);
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

/** The markers on one section's Travel Labor row: who filled it, whose it is, and whether it is the tool's copy of another sheet's. */
function marks(b, tab) {
  const r = rowIn(secOf(b.api.root(), tab));
  return r ? { auto: r.guys_auto === true, follow: r.guys_follow || null, seed: r.hours_seed === undefined ? null : r.hours_seed, typed: r.guys_typed === true || r.hours_typed === true,
    hand: r.hand_added === true, copy: r.tool_copy === true, rate: r.rate === undefined ? null : r.rate } : null;
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

/** A fresh sheet from the Sheets panel's Add menu. Answers the new sheet's id. */
async function addSheet(b, sheet) {
  b.api.go(1);
  const before = Object.keys(b.api.root().tabs || {});
  if (b.doc.querySelector('[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]');
  P.clickOn(b, '[data-sh-act="add"][data-sh-sheet="' + q(String(sheet)) + '"]');
  await settle();
  b.clock.fire();
  return Object.keys(b.api.root().tabs || {}).filter((k) => before.indexOf(k) < 0)[0] || null;
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

/** The labor total of the section `tab` (its drive included), as the price reads it. */
const laborOf = (b, tab) => B.laborTotal(secOf(b.api.root(), tab).labor, b.api.root().conditions);

/** THE FINDING'S BID up to the base pick: far Polish 4 x 12, its Travel Labor said on (`say`), an Epoxy sheet added with its crew 5 x 12, and Epoxy made the base (yes). */
async function pickedBid(say) {
  const b = await newBid(POLISH(), [["Polish", "polishing", "4", "12"]]);
  typeDrive(b, B.ROOT_TAB, say);
  await addSheet(b, "Epoxy");
  typeCrew(b, "Epoxy", "epoxy-install", "5", "12");
  await makeBase(b, "Epoxy");
  return b;
}
const TYPED = { guys: "7", hours: "3.25" };

/** THE NATURAL PAIR (the pass-2 audit's A2): far Polish 4 x 12, its Travel Labor typed 7 x 3.25, an Epoxy sheet added with its crew 5 x 12, and "Make Epoxy + Polish the base" at once: the Epoxy
 *  sheet is never handed a copy of the typed drive, and nothing is typed on it. */
async function directPair() {
  const d = await newBid(POLISH(), [["Polish", "polishing", "4", "12"]]);
  typeDrive(d, B.ROOT_TAB, TYPED);
  await addSheet(d, "Epoxy");
  typeCrew(d, "Epoxy", "epoxy-install", "5", "12");
  await makeBase(d, "combined");
  return d;
}

/** The end of a path, as a test reads it: the page's state, the marks on the named sections' rows, and the same after a jsonb reload (and whether the reload armed a save). */
async function ending(b, tabs) {
  const mk = Object.fromEntries(tabs.map((t) => [t, marks(b, t)]));
  const s = state(b);
  const r = await reload(b);
  return { state: s, marks: mk, reloaded: state(r), quiet: r.quiet };
}

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

async function main() {
  // ═══ THE FINDING: the Polish crew's typed drive copied to Epoxy by the pick, then both made bases ══════════════════════════════════════════════════════════════════════════
  await section("picked", async () => {
    const b = await pickedBid(TYPED);
    const afterPick = { rows: driveRows(b), marks: { polish: marks(b, B.ROOT_TAB), epoxy: marks(b, "Epoxy") } };
    // ...the intake's job type Combo
    const c = await switchJob(b, "combo");
    const epoxyLabor = laborOf(c, "Epoxy");
    const combo = await ending(c, [B.ROOT_TAB, "Epoxy"]);
    // ...300 miles typed, in the session and after a reload: the Epoxy crew's own drive moves, the typed one stays
    const cr = await reload(c);
    await typeMiles(c, 300);
    await typeMiles(cr, 300);
    const at300 = { session: state(c), reload: state(cr) };
    // ...or "Make Epoxy + Polish the base" on the Sheets panel, in the same session as the pick
    const p = await pickedBid(TYPED);
    await makeBase(p, "combined");
    const pair = await ending(p, [B.ROOT_TAB, "Epoxy"]);
    // THE ORACLE (the pass-2 audit's A2: the natural pair, nothing typed on it): the same sheets made the pair at once from the Polish base, the Epoxy sheet never handed a copy (it is given its
    // own line, filled on its own crew)
    const d = await directPair();
    const direct = await ending(d, [B.ROOT_TAB, "Epoxy"]);
    return { afterPick: afterPick, combo: combo, epoxyLabor: epoxyLabor, at300: at300, pair: pair, direct: direct };
  });

  // ═══ EVERY ROUTE TO THE PAIR (the pass-2 audit's A2): the Epoxy crew's drive beside the typed Polish one is the same whichever way the Epoxy base arrived ═══════════════════════════════
  await section("routes", async () => {
    // the intake's job type Combo straight from the typed Polish bid (the Epoxy section is new: the library seeds it)
    const i = await newBid(POLISH(), [["Polish", "polishing", "4", "12"]]);
    typeDrive(i, B.ROOT_TAB, TYPED);
    const ic = await switchJob(i, "combo");
    typeCrew(ic, "Epoxy", "epoxy-install", "5", "12");
    ic.api.saveSoon();
    ic.clock.fire();
    const intake = await ending(ic, [B.ROOT_TAB, "Epoxy"]);
    // a new Combo, the trip typed on the Polish drive alone
    const f = await newBid(COMBO(), [["Polish", "polishing", "4", "12"], ["Epoxy", "epoxy-install", "5", "12"]]);
    typeDrive(f, B.ROOT_TAB, TYPED);
    const fresh = await ending(f, [B.ROOT_TAB, "Epoxy"]);
    // the pick then the Combo, and the pair made at once, as the miles move: 300, then a local job (40)
    const picked = await switchJob(await pickedBid(TYPED), "combo");
    const pair = await directPair();
    const miles = {};
    for (const m of [300, 40]) {
      await typeMiles(picked, m);
      await typeMiles(pair, m);
      miles[m] = { picked: state(picked), pair: state(pair), pickedMarks: marks(picked, "Epoxy"), pairMarks: marks(pair, "Epoxy") };
    }
    return { intake: intake, fresh: fresh, miles: miles };
  });

  // ═══ THE SAME FROM EPOXY: far Epoxy typed, a Polish sheet added and made the base, then the pair ═════════════════════════════════════════════════════════════════════════
  await section("epoxyFirst", async () => {
    const b = await newBid(EPOXY(), [["Epoxy", "epoxy-install", "5", "10"]]);
    typeDrive(b, "Epoxy", TYPED);
    const polish = await addSheet(b, "Polish");
    typeCrew(b, polish, "polishing", "4", "12");
    await makeBase(b, polish);
    const afterPick = { rows: driveRows(b), marks: { epoxy: marks(b, "Epoxy"), polish: marks(b, polish) } };
    await makeBase(b, "combined");
    return Object.assign({ polish: polish, afterPick: afterPick }, await ending(b, ["Epoxy", polish]));
  });

  // ═══ A SHEETS COPY: far Polish typed, the sheet copied, the job made Epoxy (the typed drive goes with the job's base), then the copy and Epoxy made the pair ════════════════
  await section("sheetCopy", async () => {
    const b = await newBid(POLISH(), [["Polish", "polishing", "3", "12"]]);
    typeDrive(b, B.ROOT_TAB, TYPED);
    const copy = await copySheet(b, B.ROOT_TAB);
    const afterCopy = { rows: driveRows(b), marks: { polish: marks(b, B.ROOT_TAB), copy: copy ? marks(b, copy) : null } };
    const e = await switchJob(b, "epoxy");
    typeCrew(e, "Epoxy", "epoxy-install", "5", "10");
    e.api.saveSoon();
    e.clock.fire();
    const asEpoxy = { rows: driveRows(e), marks: { epoxy: marks(e, "Epoxy"), copy: copy ? marks(e, copy) : null }, pair: B.combinedPair(e.api.root()) };
    await makeBase(e, "combined");
    return Object.assign({ copy: copy, afterCopy: afterCopy, asEpoxy: asEpoxy }, await ending(e, ["Epoxy", copy]));
  });

  // ═══ A COPY MADE THE BASE BY ITSELF keeps the typed row, as its source prices; beside an Epoxy base that does not hold it, still ═════════════════════════════════════════
  await section("copyAlone", async () => {
    const b = await newBid(POLISH(), [["Polish", "polishing", "4", "12"]]);
    typeDrive(b, B.ROOT_TAB, TYPED);
    const copy = await copySheet(b, B.ROOT_TAB);
    await makeBase(b, copy);
    const alone = { rows: driveRows(b), marks: marks(b, copy) };
    const c = await switchJob(b, "combo");
    typeCrew(c, "Epoxy", "epoxy-install", "5", "12");
    c.api.saveSoon();
    c.clock.fire();
    return Object.assign({ copy: copy, alone: alone }, await ending(c, [copy, "Epoxy"]));
  });

  // ═══ TYPED ALIKE ON EACH SHEET: a far Combo whose two drives the estimator typed 4 x 4, each on its own sheet, keeps both ═════════════════════════════════════════════════════
  await section("handTyped", async () => {
    const b = await newBid(COMBO(), [["Polish", "polishing", "4", "12"], ["Epoxy", "epoxy-install", "5", "12"]]);
    typeDrive(b, B.ROOT_TAB, { guys: "4", hours: "4" });
    typeDrive(b, "Epoxy", { guys: "4", hours: "4" });
    await makeBase(b, B.ROOT_TAB);
    const picked = driveRows(b);
    await makeBase(b, "combined");
    return Object.assign({ picked: picked }, await ending(b, [B.ROOT_TAB, "Epoxy"]));
  });

  // ═══ TYPED IN THE COPY: the estimator types in the Epoxy base's copy before the Combo, and it is theirs on that sheet ══════════════════════════════════════════════════════
  await section("retyped", async () => {
    const b = await pickedBid(TYPED);
    const before = marks(b, "Epoxy");
    typeDrive(b, "Epoxy", { guys: "7" });
    const after = marks(b, "Epoxy");
    const c = await switchJob(b, "combo");
    return Object.assign({ before: before, after: after }, await ending(c, [B.ROOT_TAB, "Epoxy"]));
  });

  // ═══ ONLY THE HOURS TYPED (the guys on each crew): the copy's hours are given back too ════════════════════════════════════════════════════════════════════════════════════
  await section("hoursOnly", async () => {
    const b = await pickedBid({ hours: "3.25" });
    const afterPick = { rows: driveRows(b), marks: marks(b, "Epoxy") };
    const c = await switchJob(b, "combo");
    return Object.assign({ afterPick: afterPick }, await ending(c, [B.ROOT_TAB, "Epoxy"]));
  });

  // ═══ NO TRIP TYPED: a copy whose hours the estimator did not type is given back and refilled from the miles, as every copy is: the guys alone typed (7), a rate alone typed ($40: the
  // copy is filled at its own default rate), and the Hours box cleared (a cleared box is that sheet's say, not the Epoxy crew's) ═══════════════════════════════════════════════════════
  await section("noTrip", async () => {
    const one = async (say) => {
      const b = await pickedBid(say);
      const afterPick = { rows: driveRows(b), marks: marks(b, "Epoxy") };
      const c = await switchJob(b, "combo");
      return Object.assign({ afterPick: afterPick }, await ending(c, [B.ROOT_TAB, "Epoxy"]));
    };
    return { guys: await one({ guys: "7" }), rate: await one({ rate: "40" }), cleared: await one({ hours: "" }) };
  });

  // ═══ THE RATE TYPED TOO ($40 over $33): the copy given back is filled at its own default rate; typed again on the copy, it is theirs ═══════════════════════════════════════
  await section("rated", async () => {
    const say = { guys: "7", hours: "3.25", rate: "40" };
    const b = await pickedBid(say);
    const afterPick = { rows: driveRows(b), marks: marks(b, "Epoxy") };
    const c = await switchJob(b, "combo");
    const given = await ending(c, [B.ROOT_TAB, "Epoxy"]);
    const t = await pickedBid(say);
    typeDrive(t, "Epoxy", { rate: "40" });
    const retypedMarks = marks(t, "Epoxy");
    const k = await switchJob(t, "combo");
    const kept = await ending(k, [B.ROOT_TAB, "Epoxy"]);
    return { afterPick: afterPick, given: given, retypedMarks: retypedMarks, kept: kept };
  });

  // ═══ TWO COPIES ON THE TWO BASES: the one on the sheet that became a base gives its repeat back ═════════════════════════════════════════════════════════════════════════════
  await section("twoCopies", async () => {
    const b = await newBid(EPOXY(), [["Epoxy", "epoxy-install", "5", "10"]]);
    typeDrive(b, "Epoxy", TYPED);
    const polish = await addSheet(b, "Polish");
    typeCrew(b, polish, "polishing", "4", "12");
    const epoxy2 = await addSheet(b, "Epoxy");
    typeCrew(b, epoxy2, "epoxy-install", "6", "8");
    await makeBase(b, polish);
    await makeBase(b, epoxy2);
    const beforePair = { rows: driveRows(b), marks: { epoxy: marks(b, "Epoxy"), polish: marks(b, polish), epoxy2: marks(b, epoxy2) }, pair: B.combinedPair(b.api.root()) };
    await makeBase(b, "combined");
    return Object.assign({ polish: polish, epoxy2: epoxy2, beforePair: beforePair }, await ending(b, [polish, epoxy2]));
  });

  // ═══ THE DISTANCE'S OWN FILL COPIED: nothing the estimator said, so not the tool's copy of a say; each crew drives its own ═══════════════════════════════════════════════════
  await section("fillCopied", async () => {
    const b = await pickedBid({});
    const afterPick = { rows: driveRows(b), marks: { polish: marks(b, B.ROOT_TAB), epoxy: marks(b, "Epoxy") } };
    const c = await switchJob(b, "combo");
    return Object.assign({ afterPick: afterPick }, await ending(c, [B.ROOT_TAB, "Epoxy"]));
  });

  // ═══ THE ORIGINAL CHANGED AFTER THE PICK: the copy says something no other base says (other guys, other hours, another rate, the original switched off), and stays ═══════════════
  await section("diverged", async () => {
    const one = async (change) => {
      const b = await pickedBid(TYPED);
      if (change === "off") flipDrive(b, B.ROOT_TAB);
      else typeDrive(b, B.ROOT_TAB, change === "guys" ? { guys: "6" } : change === "hours" ? { hours: "4" } : { rate: "45" });
      const c = await switchJob(b, "combo");
      return await ending(c, [B.ROOT_TAB, "Epoxy"]);
    };
    return { guys: await one("guys"), hours: await one("hours"), rate: await one("rate"), off: await one("off") };
  });

  // ═══ THE COPY'S SWITCH FLIPPED ON ITS OWN CARD: the estimator's on that sheet. Both drives off, the Combo leaves both off ═══════════════════════════════════════════════════════
  await section("switched", async () => {
    const b = await pickedBid(TYPED);
    const flipped = flipDrive(b, "Epoxy");
    const after = marks(b, "Epoxy");
    flipDrive(b, B.ROOT_TAB);
    const c = await switchJob(b, "combo");
    const offOn = (tab) => (rowIn(secOf(c.api.root(), tab)) || {}).enabled === false;
    return Object.assign({ flipped: flipped, after: after, off: { polish: offOn(B.ROOT_TAB), epoxy: offOn("Epoxy") } }, await ending(c, [B.ROOT_TAB, "Epoxy"]));
  });

  // ═══ A DRIVE THE ESTIMATOR ADDED AND TYPED, copied by the pick: given back, the copy loses the mark of an added line ════════════════════════════════════════════════════════
  await section("added", async () => {
    const b = await newBid(POLISH(), [["Polish", "polishing", "4", "12"]]);
    const x = await pressX(b, B.ROOT_TAB);
    const add = await pressAdd(b, B.ROOT_TAB);
    typeDrive(b, B.ROOT_TAB, TYPED);
    await addSheet(b, "Epoxy");
    typeCrew(b, "Epoxy", "epoxy-install", "5", "12");
    await makeBase(b, "Epoxy");
    const afterPick = { rows: driveRows(b), marks: marks(b, "Epoxy") };
    const c = await switchJob(b, "combo");
    return Object.assign({ x: x, add: add, afterPick: afterPick }, await ending(c, [B.ROOT_TAB, "Epoxy"]));
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
