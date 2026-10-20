"use strict";
/* THE JOB'S ONE DRIVE, OVER EVERY SEQUENCE OF SWITCHES: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with the REAL
 * js/bid-model.js beneath it. A hand-picked scenario can only hold the switches somebody thought of; the 2026-10-20 audits of the "far distance fills Travel
 * Labor" work each found that the scenarios held every switch but the next one (Epoxy to Polish to Combo priced the drive twice, $1,716 where Kyle types $858),
 * so this walks EVERY sequence of job types (Polish, Epoxy, Combo, Gyp) and Sheets base changes up to a depth, on a NEW far bid (Wichita, 190 miles), on a local one
 * (40 miles) and on one whose distance is unknown, and judges the page after every step. A step is the intake's job type reaching the estimate page (the saved draft
 * is reopened as that type, which is how the page meets it), optionally followed by the crew typed on the new carrier; or a base change made on the Sheets panel.
 *
 * THE RULE (Hanz, 2026-10-20): on a job 70 or more miles from the Olathe office there is EXACTLY ONE priced drive for the job: the Travel Labor row of the section that
 * carries the job's travel, crew size (the most guys on any labor line of the base sections, a Combo's both) x one round trip's hours x rate. Hotel and Per Diem as
 * they were. A figure the estimator typed, a box they cleared and a row they switched off are theirs: never refilled, and they FOLLOW the job's drive when the
 * carrier changes. A box they are standing in is never written. A plain reopen changes nothing.
 *
 * WHAT IS CHECKED AFTER EVERY STEP (the code in the report is the one the test file names):
 *   ONE_DRIVE        no more than one priced Travel Labor row on the sections that are a BASE of the bid (an option is priced apart and carries its own).
 *   MAN_DAYS         no Travel Labor row on a live section that the tool filled and that is priced on the MAN-DAYS (the older auto: 49.5 x 6.5 x $33 = $10,617.75).
 *   FAR_CARRIER      a far job's carrier (a Gyp carrier excepted: its drive is typed) has a Travel Labor row, and one nobody touched is exactly the rule:
 *                    the crew's size on auto, the round trip's hours, the markers that say so.
 *   GYP_UNFILLED     a Gyp carrier's row the estimator did not touch is empty.
 *   LOCAL            a job under 70 miles, or with no distance, prices no Travel Labor row nobody touched.
 *   OWNED            (a typed / cleared / switched-off row) it is on the carrier, with what was typed, and no other section's row prices anything (a copy of the
 *                    carrier's sheet made a base beside it holds a repeat of the row, which is given back: the drive is typed once and charged once).
 *   STALE            a Travel Labor row nobody touched, on a section that is not the carrier and is not an option, is empty and carries none of the fill's markers
 *                    (the old carrier gave it back; an off section's row waits empty for the day its job type returns).
 *   ONE_ROW          no section holds two Travel Labor rows.
 *   PLAIN_REOPEN     a step that is only a reopen (the job type the draft already is) arms no save, writes nothing, and leaves every row and the price as saved.
 *   REOPEN_AGREES    the price the draft saved (proposal_lump_sum, or computed_bid.lump_sum) is the price a plain reopen of it shows, and the rows are the same.
 *   CRASH            the page threw.
 *
 * THE FOURTH AUDIT (2026-10-20, of c0255de) added the DISTANCE as a step (the estimator corrects the miles AFTER the job was restructured, a sheet was copied or a base was
 * demoted), and these two rules, judged right after every distance step on every sheet that is an OPTION (an option is priced apart and has a Travel Labor row of its own when
 * it is a copy of the carrier or a demoted base: every answer reaches it, by the carrier's rule, on its own crew):
 *   OPT_FOLLOWS      a Travel Labor row of an option that is on and whose hours box nobody typed in holds, after the answer, the hours the answer gives (a far job: one round trip's;
 *                    under 70 miles or no distance: none and no marker), and one whose Guys box nobody typed in is on the option's OWN lines' crew (far) or, when its hours box is
 *                    not typed in either, emptied whole (under 70 miles: no guys, no marker).
 *   OPT_OWNED        an option's row that was switched off is exactly as it was, and a box that was typed in or cleared holds what it held.
 * (LOCAL, judged on every live section, options included, already says that a job under 70 miles prices no row nobody touched.)
 *
 * HANZ'S DECISION OF THE FIFTH AUDIT ("Fill them automatically", 2026-10-20) added NIGHTS, judged after every step of every walk (a walk never types in the Lodging or Per Diem box, so none
 * of its lines is the estimator's, but in the `nightsTyped` mode, which types in both first and judges them as the estimator's: they hold what was typed, through every step):
 *   NIGHTS           the job's Lodging and Per Diem, on a job 70 miles or more out, hold the summed man-days of EVERY base section (round 6: Kyle carries hotel on every sheet of a Combo), each
 *                    section counted with its own tab's divisor (guys x days, as a person counts them, and a crew entered in hours over the hours a night is worth on its tab: a Gyp crew's
 *                    hours over 10), on auto and marked as following the labor; under 70 miles, or with no distance, they hold nothing (empty, off auto, no marker). An option is priced apart
 *                    and a section that is off counts nothing. (Round 5 made a Gyp carrier's nights typed, because the man-days then counted day rows only: that exception is gone.)
 *
 * THE FIFTH AUDIT (2026-10-20, of b14bc98) added the RELOAD, which every other step lacks: a step of the walk always starts from the draft the step before SAVED, so every walk above
 * is "reload, then step" and could never see a Sheets panel action that prices differently in the session than after a reload (a base the pick demoted lost its Travel Labor row
 * in the session, and migrateModel gave the root a blank one on the next open: +$783 between the two). In `reload` mode every sheets action (a base change, a copy, a sheet
 * added) is judged one more way, after every step it ends:
 *   RELOAD_AGREES    the SAME distance answer typed in the session that made the change, and typed after a plain reopen of the draft that session saved, leaves the same prices (the lump
 *                    sum a save writes, the root sheet's bid, every other section's) and the same Travel Labor rows, for each of the four answers (50, 300, 190 and cleared).
 *
 * ROUND 6, PART 2 (2026-10-20) added the ANSWER: the x on a Travel Labor line and Add Travel Labor, as steps of the walk. The verification of round 5 found a session and a reload of the SAME draft
 * pricing $783 apart (F1: a far Combo, switched to Epoxy, the x on the Epoxy sheet's Travel Labor, back to Combo; F2: a far Polish, the x, an Epoxy sheet made the base, Add Travel Labor on it,
 * the Polish option read) and traced it to migrateModel appending a blank Travel Labor row to a root that was off or an option. The walks above could not see it, for two reasons that are fixed:
 * `shape` LEFT BLANK ROWS OUT of "as it was" (so a reopen that put one back looked the same), and no step pressed the x. Now a plain reopen is judged on every row, the blob a reload is judged on is
 * re-keyed as the drafts table's jsonb column hands it back (key length, then bytes), and:
 *   ANSWER_OWNER     the root's `no_travel_labor` is the JOB's answer: it is set only while the section that carries the job's travel holds no Travel Labor line. An option's x and a leftover row's x
 *                    record nothing on the job, a job-type switch after the carrier's x does not seed the new carrier a line, and a flag over a carrier that holds a line is a violation.
 *   ANSWER_HELD      the job's answer HOLDS (decided 2026-10-20; Hanz, 2026-10-21: "a job-type switch keeps the drive REMOVED, no seed, no carry, Add Travel Labor is the way back"): after the x
 *                    on the carrier's line and until Add Travel Labor on the carrier, a job-type switch or a crew typed leaves the job with no drive: the flag still set, and no line on the carrier
 *                    (not seeded to a new section, not carried to it, not a blank one the new carrier already held filled by the distance on file). A Sheets action (a base pick, a copy, a sheet
 *                    added) ends the rule: an option made the base can hold a line of its own, and then the job has a drive (the answer goes). So does a job-type switch that makes an OPTION holding
 *                    a line of its own the carrier (round 6, part 3, M3: it brings its own drive, exactly as the base pick does; promotedOwnLine).
 *   DEMOTED_KEEPS    a base the Sheets panel's pick demotes to an option keeps the Travel Labor line it held (the fifth audit's decision). The blank line a reload gave a demoted root is gone, so a session
 *                    and a reload now agree even on a demotion that loses the line, and RELOAD_AGREES no longer says so: this says what the session must hold.
 *   (FAR_CARRIER     no longer calls a far carrier with no line a violation while the job's answer says it has no drive.)
 *
 * THE SIXTH ROUND (2026-10-20, item C2) made every reopen go through the SERVER'S key order (js/_jsonb.js: the draft's jsonb column keeps no key order, so every object of a reopened blob
 * has its keys sorted by length and then by bytes), and added the one walk that had never been possible: a SESSION that does not reload. Every other walk starts each step from the draft
 * the step before saved, reopened, so a bid it is judging was always read back from the server before anything was done to it, and a Sheets action that puts a sheet into the bid
 * (a copy, a fresh sheet) always acted on sheets the server had already put in its own order. In `session` mode ONE page carries a whole path of Sheets actions (and job switches, which
 * the intake makes on the same browser's copy of the draft: localStorage keeps the order it was written in), and after every prefix of every path the page is judged against a reload:
 *   SESSION_AGREES   the bid the session made, and a page opened on the blob it saved with every object's keys in jsonb's order, hold the same prices (the lump sum a save writes, the root
 *                    sheet's bid, every other section's), the same sheets in the same order with the same kinds, the same carrier, the same priced_tabs (the order the customer's document
 *                    and the proposal's sidebar list them in) and the same Travel Labor rows; and each of the four distance answers (50, 300, 190, cleared) typed on a page opened on the
 *                    blob as the session saved it, and on a page opened on it after the server, leaves the same prices and rows. The report marks a divergence "PRICES DIFFER" when a
 *                    price is not the same (`priced`), and "same prices, other rows or order" when only the sheets or the rows are.
 *
 * ROUND 6, PART 3 (2026-10-21, M1) put the ANSWER walks under the server's order too. Until the sheet-order work was merged they re-keyed a reloaded blob as jsonb does EXCEPT the sheets under
 * `tabs`, which they kept in the order they were saved (a tree without `seq` reads them back in another order, and every reopen would have reported the sheet bar moving); every reopen now goes
 * through reopen(), sheets and all. And the one shape that order decides a PRICE on is a step of its own: THE EPOXY + POLISH-COPY PAIR (`pair`, pairOfCopy), the two bases an Epoxy sheet and a copy
 * of the Polish root, both under `tabs`, the root an option. Which of the two carries the job's travel (crew, drive, nights) is their order alone, and jsonb hands "Copy1" back before "Epoxy".
 * It is a step of the `answer` and `session` walks, judged after it as every Sheets action is (RELOAD_AGREES there, SESSION_AGREES here, DEMOTED_KEEPS in both), and two of the `answers`
 * sequences build it with Epoxy added first, so the reload moves it.
 *
 * MODES (argv[3]): far | farplain | local | unknown | nightsTyped | typed | clearHours | clearGuys | off | rate | mixed | sheets | sheetsTyped | sheetsClearHours | sheetsClearGuys |
 *   sheetsOff | sheetsRate | dist | distTyped | distClearHours | distClearGuys | distOff | distRate | reload | answer | answerJobs | answerSheets | answers | session | audit54.
 *   answers               the fifteen sequences of the answer's own (F1, F2, S1 of the round-5 verification and the ones around them, and the Epoxy + Polish-copy pair: ANSWER_SEQUENCES),
 *                         every rule judged after every step.
 *   answer, answerJobs, answerSheets   the steps of `reload` plus the ANSWER (the x on the carrier's Travel Labor line, the x on an option's, Add Travel Labor on the carrier, on an option),
 *                         with RELOAD_AGREES judged after every Sheets action, x and Add, against a JSONB reload of the draft the session saved. `answer` takes every kind of step, two deep,
 *                         the Epoxy + Polish-copy pair among them;
 *                         `answerJobs` the four job types and the answer, three deep (F1's family: switch, x, switch back); `answerSheets` the Sheets actions and the answer, three deep (F2's family).
 *   far, local, unknown   steps are the four job types, each plain or with the crew typed on the new carrier.
 *   farplain              the same far job, with the four job types only (no crew typed): the deeper walk.
 *   nightsTyped           the estimator's say on the job's NIGHTS is applied first (Lodging typed 10, Per Diem typed over and cleared, on the Labor step of the carrier), then the steps are the
 *                         far mode's. A typed line is THEIRS (round 6, N4): through every sequence after it, on a far job, under 70 miles and with no distance (nightsTyped@local,
 *                         nightsTyped@unknown), Lodging holds "10" and Per Diem holds nothing, both typed, off auto, with no follow marker: no answer fills them, no crew changes them.
 *   typed, clearHours, clearGuys, off, rate   the estimator's variant is applied to the carrier's Travel Labor row first, then the steps are the four job types. (`rate` types $40
 *                         over the line's $33 and nothing else: the guys and the hours stay on the distance, and the typed rate follows the job's drive.)
 *   mixed                 the steps are the four job types and, once on any path, ONE of the variants (anywhere in the sequence).
 *   sheets                the steps are the four job types, and the Sheets panel's base changes, and a copy of the carrier, whatever the panel offers.
 *   sheetsTyped, sheetsClearHours, sheetsClearGuys, sheetsOff, sheetsRate   the same steps, with the estimator's variant applied to the carrier's row first.
 *   dist                  the `sheets` steps, and the miles corrected: typed as 50 (local), 300 (farther), 190 (far) or cleared (the lookup finds nothing), at every point of every
 *                         sequence, so every distance answer arrives after copies, base demotions and job switches.
 *   distTyped, distClearHours, distClearGuys, distOff, distRate   the same steps, with the estimator's variant applied to the carrier's row first (a copy carries it).
 *   reload                the `sheets` steps and a fresh Epoxy sheet added, and RELOAD_AGREES judged after every sheets action (the session against a reload, four answers each).
 *   reloadTyped, reloadClearHours, reloadClearGuys, reloadOff, reloadRate   the same, with the estimator's variant applied to the carrier's row first.
 *   session               the job types, the Sheets panel's base changes, a copy of the carrier, a fresh Epoxy or Polish sheet and the Epoxy + Polish-copy pair, in ONE continuous session
 *                         (see above), judged against a reload after every prefix of every sequence.
 *   audit54               the 54 sequences the 2026-10-20 audit found pricing the drive twice at 7d32336, with their exact dollars.
 * Any mode but audit54 takes a distance after an at-sign (typed@local, sheetsOff@unknown, mixed@local): the same walk on a 40 mile job or one with no distance.
 * argv[4] is the depth (the number of steps after the start).
 *
 * Usage: node travel-sequence-harness.js <frontend-dir> <mode> [depth]   ->  one line of JSON:
 *   { mode, depth, runs, reopens, plain, reloads, reordered, [sessions, reloadJudged], violations: { CODE: n }, priced: { CODE: n }, pricedSamples: [...], samples, crashes }
 *   (`reloads`: reopens made through the server's key order; `reordered`: how many brought the sheets back in another order; `priced`: how many divergences moved a price.)
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");
const J = require("./_jsonb.js");

const ROOT = path.resolve(process.argv[2]);
const RAW_MODE = process.argv[3] || "far";
const MODE = RAW_MODE.split("@")[0];
const DIST_MODE = RAW_MODE.indexOf("@") >= 0 ? RAW_MODE.split("@")[1] : "";     // "typed@local": the same walk on a job of that distance
const DEPTH = Number(process.argv[4] || 3);
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-sequence-harness.js");
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

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const DISTANCES = { far: { ok: true, miles: 190, reason: "" }, local: { ok: true, miles: 40, reason: "" }, unknown: { ok: false, miles: null, reason: "not_found" } };
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const DRAFTS = {
  epoxy: () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" }),
  polish: () => draftOf("polish", { polish_sf: 5000 }),
  combo: () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" }),
  gyp: () => draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 }),
};
const TYPES = ["epoxy", "polish", "combo", "gyp"];
// The crew a new bid is given on its first carrier, and the (bigger) one typed by a "+crew" step on the carrier a job type leaves it with.
const START_CREW = { epoxy: ["Epoxy", "epoxy-install", "4", "12"], polish: ["Polish", "polishing", "4", "12"], combo: ["Polish", "polishing", "4", "12"], gyp: [GYP_TAB, "gyp-pour", "4", "12"] };
const STEP_CREW = { epoxy: ["Epoxy", "epoxy-install", "5", "12"], polish: ["Polish", "polishing", "6", "12"], combo: ["Polish", "polishing", "6", "12"], gyp: [GYP_TAB, "gyp-pour", "5", "12"] };
const VARIANTS = ["typed", "clearHours", "clearGuys", "off", "rate"];
/** `nightsTyped`: the estimator's own say on the job's NIGHTS (Lodging typed 10, Per Diem cleared) on the carrier's Labor step, before any switch. Typed lines are THEIRS: through every sequence they hold what was typed. */
const NIGHTS_TYPED = MODE === "nightsTyped";
/** The variant a mode starts from, or "": the variant modes, and the sheets and dist modes that name one (sheetsTyped, sheetsOff, distRate, ...). */
const MODE_VARIANT = (function () {
  if (VARIANTS.indexOf(MODE) >= 0) return MODE;
  const m = /^(?:sheets|dist|reload)(Typed|ClearHours|ClearGuys|Off|Rate)$/.exec(MODE);
  return m ? m[1].charAt(0).toLowerCase() + m[1].slice(1) : "";
})();
const DIST = MODE === "dist" || /^dist(Typed|ClearHours|ClearGuys|Off|Rate)$/.test(MODE);
const RELOAD = MODE === "reload" || /^reload(Typed|ClearHours|ClearGuys|Off|Rate)$/.test(MODE);
/** The ANSWER walks (round 6, part 2): the x and Add Travel Labor are steps, and the reload a step is judged against is a jsonb one. */
const ANSWER = MODE === "answer" || MODE === "answerJobs" || MODE === "answerSheets" || MODE === "answers";
const SESSION = MODE === "session";
const SHEETS = MODE === "sheets" || /^sheets(Typed|ClearHours|ClearGuys|Off|Rate)$/.test(MODE) || DIST || RELOAD || SESSION;      // a distance walk takes every step of the Sheets walk too
/** The miles a distance step types: under 70 (local), 300 (farther than the 190 a new bid starts on), 190 again, and the box cleared (the lookup then finds nothing). */
const DIST_TEXT = { local: "50", farther: "300", far: "190", cleared: "" };

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await flush(); };

/** A page on a draft. `extra.distance` is what the lookup answers (a NEW bid asks by itself, a saved one does not). */
async function open(blob, extra) {
  const opts = Object.assign({ blob: blob, labor: LABOR }, extra || {});
  const b = P.build(opts);
  await b.api.init();
  await settle();
  b.opts = opts;           // what the lookup answers is read from here each time the page asks, so a step can change it after the page is open
  return b;
}

/** A page on a SAVED draft, reopened: the draft comes back from the server, whose jsonb column keeps no key order, so every object's keys are in jsonb's
 *  order (js/_jsonb.js) and not in the order the page that saved it wrote them. Every step of a walk starts from one, and so does every plain reopen.
 *  The report counts them (`reloads`) and the ones whose sheets came back in ANOTHER order than they were saved in (`reordered`), so a walk that stopped
 *  re-keying, or whose bids never had sheets that jsonb moves, cannot pass as one that was held to the server's order. */
function reopen(saved, extra) {
  const tabsOf = (blob) => Object.keys(((blob && blob.polish_estimate) || {}).tabs || {}).join("|");
  report.reloads = (report.reloads || 0) + 1;
  if (tabsOf(saved) !== tabsOf(J.reloaded(saved))) report.reordered = (report.reordered || 0) + 1;
  return open(saved, Object.assign({ reloaded: true }, extra || {}));
}

const secOf = (m, tab) => (tab === B.ROOT_TAB ? m : (m.tabs || {})[tab]);
const travelRows = (sec) => ((sec && sec.labor) || []).filter((r) => r && r.id === "travel");
const idxIn = (sec, id) => (sec && sec.labor ? sec.labor.findIndex((r) => r && r.id === id) : -1);
const blank = (v) => v === undefined || v === null || String(v).trim() === "";
const cost = (r) => B.laborCost(r);
/** Whose row is it? The estimator's when it is switched off, or a box was typed in or cleared (the markers saved with the row). Written out here and not
 *  asked of the model, so the check does not agree with a model that has the same mistake in it. */
const owned = (r) => !!r && (r.enabled === false || r.guys_typed === true || r.hours_typed === true);
const fmtRow = (r) => (r ? r.guys + "x" + r.days + (r.enabled === false ? " OFF" : "") + (r.guys_typed ? " Tg" : "") + (r.hours_typed ? " Th" : "") +
  (r.guys_follow ? " crew" : "") + " =$" + cost(r) : "none");
const lumpOf = (blob) => {
  if (blob && blob.proposal_lump_sum !== undefined && blob.proposal_lump_sum !== null) return blob.proposal_lump_sum;
  return blob && blob.computed_bid ? blob.computed_bid.lump_sum : null;
};
const typeOfBlob = (blob) => {
  try { return B.baseOf(B.migrateModel(blob.polish_estimate)).jobType; } catch (e) { return null; }
};

/** What the page holds, read off its WHOLE model. */
function facts(b) {
  const m = b.api.root();
  const entries = B.sectionsOf(m);
  const miles = m.distance ? B.milesOrNull(m.distance.miles) : null;
  return { m: m, entries: entries, carrier: B.travelCarrier(m), miles: miles, far: miles !== null && miles >= B.LOCAL_MILES,
    jobType: B.baseOf(m).jobType };
}

/** The same facts as a string, for "is it as it was". EVERY Travel Labor row counts, a blank one too (round 6, part 2): this used to leave a row with nothing in it out ("migrateModel puts one back on a
 *  section whose draft was saved without, and it prices nothing"), which is exactly how a reopen that appended a blank row to an off root looked the same as the page that saved it, and the next far
 *  answer filled and priced that row (+$783 between a session and a reload). The answer is part of it: the job's `no_travel_labor`. */
function shape(b) {
  const f = facts(b);
  return JSON.stringify({ car: f.carrier, said: f.m.no_travel_labor === true, kinds: f.entries.map((e) => [e.tab, e.kind]),
    rows: f.entries.map((e) => [e.tab, travelRows(e.section).map((r) => [r.guys, r.days, !!r.guys_auto, r.guys_follow === undefined ? null : r.guys_follow,
      r.hours_seed === undefined ? null : r.hours_seed, r.guys_typed === true, r.hours_typed === true, r.enabled === false, cost(r)])]) });
}

function typeCrew(b, tab, rowId, guys, days) {
  const i = idxIn(secOf(b.api.root(), tab), rowId);
  [["guys", guys], ["days", days]].forEach((kv) => {
    const sel = '[data-lab="' + i + '"][data-k="' + kv[0] + '"]';
    if (i >= 0 && b.doc.querySelector(sel)) P.typeInto(b, sel, kv[1]);
  });
}

/** The estimator's own say on the carrier's Travel Labor row, through its boxes and slider on the Labor step. False when there is no row to say it on. */
function applyVariant(b, name) {
  const m = b.api.root();
  const car = B.travelCarrier(m);
  const i = idxIn(secOf(m, car), "travel");
  if (i < 0) return false;
  b.api.show(car);
  b.api.go(1);
  const sel = (k) => '[data-lab="' + i + '"][data-k="' + k + '"]';
  if (name === "typed") { P.typeInto(b, sel("guys"), "3"); P.typeInto(b, sel("days"), "5"); }
  else if (name === "clearHours") P.typeInto(b, sel("days"), "");
  else if (name === "clearGuys") P.typeInto(b, sel("guys"), "");
  else if (name === "off") P.clickOn(b, '[data-on-lab="' + i + '"]');
  else if (name === "rate") P.typeInto(b, sel("rate"), "40");
  else throw new Error("no such variant " + name);
  return true;
}

/** The estimator's own say on the job's nights, through the two boxes on the Labor step of the sheet that carries the job's travel: Lodging typed as 10, Per Diem typed over and cleared.
 *  False when the step has no such boxes. */
function applyNights(b) {
  b.api.show(B.travelCarrier(b.api.root()));
  b.api.go(1);
  const lodging = '[data-trv="lodging"][data-k="qty"]', perDiem = '[data-trv="per_diem"][data-k="qty"]';
  if (!b.doc.querySelector(lodging) || !b.doc.querySelector(perDiem)) return false;
  P.typeInto(b, lodging, "10");
  P.typeInto(b, perDiem, "7");
  P.typeInto(b, perDiem, "");
  return true;
}

/** What the carrier's row must read for each variant, wherever the carrier is. */
function variantHolds(name, r) {
  if (!r) return false;
  if (name === "typed") return r.guys === "3" && r.days === "5" && r.guys_typed === true && r.hours_typed === true && r.guys_auto === false && r.enabled !== false;
  if (name === "clearHours") return r.days === "" && r.hours_typed === true;
  if (name === "clearGuys") return r.guys === "" && r.guys_typed === true;
  if (name === "off") return r.enabled === false;
  if (name === "rate") return String(r.rate) === "40";
  return false;
}

/** Every Travel Labor row of every sheet that is an option (and not the one that carries the job's travel, nor a Gyp sheet, whose drive is typed), as it stands: the row's whole
 *  JSON, by the sheet and the row's place on it. What a distance step is compared against. */
function optionRows(b) {
  const f = facts(b);
  const out = [];
  f.entries.forEach((e) => {
    if (e.kind !== "option" || e.tab === f.carrier || e.layout === "gyp") return;
    travelRows(e.section).forEach((r, i) => { if (r.unit === "hours") out.push({ tab: e.tab, i: i, json: JSON.stringify(r) }); });
  });
  return out;
}

/** OPT_FOLLOWS and OPT_OWNED, judged right after the miles were typed: `d.before` is optionRows from before the keystroke, `d.miles` what the distance is now (null: none). */
function judgeOptions(b, d) {
  const bad = [];
  const f = facts(b);
  const far = d.miles !== null && d.miles >= B.LOCAL_MILES;
  const hours = far ? B.driveHoursFor(d.miles) : "";
  f.entries.forEach((e) => {
    if (e.kind !== "option" || e.tab === f.carrier || e.layout === "gyp") return;
    const crew = B.ownCrewSize(f.m, e.section.labor);
    travelRows(e.section).forEach((r, i) => {
      if (r.unit !== "hours") return;
      const was = d.before.filter((x) => x.tab === e.tab && x.i === i)[0];
      const wasRow = was ? JSON.parse(was.json) : null;
      const at = e.tab + " " + fmtRow(r) + " at " + (d.miles === null ? "no distance" : d.miles + " miles");
      if (r.enabled === false) {
        if (was && JSON.stringify(r) !== was.json) bad.push(["OPT_OWNED", e.tab + " was switched off and the answer moved it: " + was.json.slice(0, 120) + " -> " + JSON.stringify(r).slice(0, 120)]);
        return;
      }
      if (r.guys_typed === true && wasRow && String(r.guys) !== String(wasRow.guys)) bad.push(["OPT_OWNED", at + ": the Guys box was typed (" + wasRow.guys + ") and the answer wrote " + r.guys]);
      if (r.hours_typed === true && wasRow && String(r.days) !== String(wasRow.days)) bad.push(["OPT_OWNED", at + ": the Hours box was typed (" + wasRow.days + ") and the answer wrote " + r.days]);
      if (r.hours_typed !== true) {
        if (far && !(r.days === hours && r.hours_seed === hours)) bad.push(["OPT_FOLLOWS", at + ": the hours are not " + hours]);
        if (!far && !(blank(r.days) && typeof r.hours_seed !== "number")) bad.push(["OPT_FOLLOWS", at + ": the hours of a job under 70 miles were not taken back"]);
      }
      // (A row the distance never filled has nothing to take back: a blank row, such as the shipped older man-days one an Epoxy bid's off root keeps, is left as it is by a job under 70 miles.)
      const wasFilled = !!wasRow && ((typeof wasRow.days === "number" && wasRow.days === wasRow.hours_seed) || wasRow.guys_follow === "crew");
      if (r.guys_typed !== true) {
        if (far && !(r.guys_follow === "crew" && r.guys_auto === true && Number(r.guys) === crew)) bad.push(["OPT_FOLLOWS", at + ": the guys are not the option's own crew of " + crew]);
        if (!far && wasFilled && r.hours_typed !== true && !(blank(r.guys) && !r.guys_follow && !r.guys_auto)) bad.push(["OPT_FOLLOWS", at + ": the fill was not taken back whole"]);
      }
    });
  });
  return bad;
}

/** Every rule above, asked of one page. `ctx.variant` is the estimator's variant on this path, if any. Returns [[code, detail], ...]. */
function judge(b, ctx) {
  const bad = [];
  const f = facts(b);
  const m = f.m;
  const live = f.entries.filter((e) => e.kind !== "off");
  const carrierEntry = f.entries.filter((e) => e.tab === f.carrier)[0];
  const note = (code, detail) => bad.push([code, detail]);

  f.entries.forEach((e) => { if (travelRows(e.section).length > 1) note("ONE_ROW", e.tab + " holds " + travelRows(e.section).length + " Travel Labor rows"); });

  const priced = [];
  f.entries.filter((e) => e.kind === "base").forEach((e) => travelRows(e.section).forEach((r) => { if (cost(r) > 0) priced.push(e.tab + " " + fmtRow(r)); }));
  if (priced.length > 1) note("ONE_DRIVE", priced.join(" + ") + " (carrier " + f.carrier + ")");

  live.forEach((e) => travelRows(e.section).forEach((r) => {
    if (cost(r) > 0 && r.guys_auto === true && !r.guys_follow && !owned(r)) note("MAN_DAYS", e.tab + " " + fmtRow(r) + " is on the man-days");
  }));

  const crow = travelRows(carrierEntry && carrierEntry.section)[0] || null;
  // THE JOB'S ANSWER (round 6, part 2): `no_travel_labor` says the job has no drive, which is what a carrier with no line is when it is set, so that carrier is not a violation. It is the carrier's
  // answer and nobody else's: set while the carrier holds a Travel Labor line, it is a flag that has outlived its meaning (an option's x, a leftover row's x, a job-type switch that seeded a line).
  if (m.no_travel_labor === true && crow) note("ANSWER_OWNER", "the job says it has no drive (no_travel_labor) and the carrier " + f.carrier + " holds " + fmtRow(crow));
  if (ctx && ctx.said === true) {
    if (m.no_travel_labor !== true) note("ANSWER_HELD", "the job said it has no drive (the x on the carrier) and the answer is gone");
    if (crow) note("ANSWER_HELD", "the job said it has no drive (the x on the carrier) and the carrier " + f.carrier + " holds " + fmtRow(crow));
  }
  if (f.far && carrierEntry && carrierEntry.layout !== "gyp") {
    if (!crow) { if (m.no_travel_labor !== true) note("FAR_CARRIER", "carrier " + f.carrier + " has no Travel Labor row at " + f.miles + " miles"); }
    else if (!owned(crow)) {
      const hours = B.driveHoursFor(f.miles);
      const ok = crow.guys_follow === "crew" && crow.guys_auto === true && crow.days === hours && crow.hours_seed === hours && crow.guys === B.crewSize(m);
      if (!ok) note("FAR_CARRIER", "carrier " + f.carrier + " row " + fmtRow(crow) + " is not the crew (" + B.crewSize(m) + ") x " + hours + " hours");
    }
  }
  if (f.far && carrierEntry && carrierEntry.layout === "gyp" && crow && !owned(crow) && (!blank(crow.days) || !blank(crow.guys) || crow.guys_follow || cost(crow) > 0)) {
    note("GYP_UNFILLED", "Gyp carrier row " + fmtRow(crow) + " was filled");
  }
  if (!f.far) {
    live.forEach((e) => travelRows(e.section).forEach((r) => { if (!owned(r) && cost(r) > 0) note("LOCAL", e.tab + " " + fmtRow(r) + " prices a drive on a " + (f.miles === null ? "job with no distance" : f.miles + " mile job")); }));
  }

  f.entries.filter((e) => e.tab !== f.carrier && e.kind !== "option").forEach((e) => travelRows(e.section).forEach((r) => {
    if (!owned(r) && (!blank(r.days) || r.guys_follow || typeof r.hours_seed === "number")) note("STALE", e.tab + " (" + e.kind + ") still holds the filled row " + fmtRow(r));
  }));

  // NIGHTS. Counted here from the rows of EVERY base section (everything in the lump sum), each by its own tab's divisor, and not asked of the model, so the check does not agree
  // with a model that has the same mistake in it. A section's man-days are guys x days over its day rows and guys x hours over the hours a night is worth on its tab (10 on a Gyp
  // tab, whose crew is entered in hours; 8 on every other) over its crew rows in hours; the drive is never one. An option counts apart, and an off section counts nothing.
  if (m.travel) {
    const nightHours = (e) => (e.layout === "gyp" ? 10 : 8);
    let manDays = 0;
    f.entries.filter((e) => e.kind === "base").forEach((e) => {
      (e.section.labor instanceof Array ? e.section.labor : []).forEach((r) => {
        if (!r || r.enabled === false || r.id === "travel") return;
        if (r.unit === "hours") manDays += (Number(r.guys) || 0) * (Number(r.days) || 0) / nightHours(e);
        else manDays += (Number(r.guys) || 0) * (Number(r.days) || 0);
      });
    });
    manDays = Math.round(manDays * 100) / 100;
    ["lodging", "per_diem"].forEach((k) => {
      const l = m.travel[k];
      if (!l) return;
      const says = k + " " + JSON.stringify({ qty: l.qty, auto: l.qty_auto, follow: l.qty_follow, typed: l.qty_typed });
      // A TYPED LINE IS THE ESTIMATOR'S (`nightsTyped`): it holds exactly what they left, whatever the distance, the carrier or the other base's crew do: never filled, never emptied, never followed.
      if (ctx && ctx.nights) {
        const want = k === "lodging" ? "10" : "";
        if (!(l.qty_typed === true && l.qty_auto === false && l.qty_follow === undefined && String(blank(l.qty) ? "" : l.qty) === want)) {
          note("NIGHTS", says + " was left by the estimator as " + JSON.stringify(want) + " and the walk changed it");
        }
        return;
      }
      if (f.far) {
        if (!(l.qty_auto === true && l.qty_follow === "labor" && Number(l.qty) === manDays)) {
          note("NIGHTS", says + " on a " + f.miles + " mile job whose bases (carrier " + f.carrier + ") have " + manDays + " man-days between them");
        }
      } else if (!(l.qty_auto === false && l.qty_follow === undefined && blank(l.qty))) {
        note("NIGHTS", says + " on a job " + (f.miles === null ? "with no distance" : "of " + f.miles + " miles") + ": nothing was to be filled");
      }
    });
  }

  if (ctx && ctx.variant) {
    if (!crow || !variantHolds(ctx.variant, crow)) note("OWNED", ctx.variant + " is not what carrier " + f.carrier + " holds: " + fmtRow(crow) + " " + JSON.stringify(crow));
    f.entries.filter((e) => e.tab !== f.carrier && e.kind !== "option").forEach((e) => travelRows(e.section).forEach((r) => {
      if (cost(r) > 0) note("OWNED", ctx.variant + " was left priced on " + e.tab + " (" + e.kind + "): " + fmtRow(r));
    }));
  }
  return bad;
}

/** The price the page would save for the model it holds, by forcing a save. Run after everything else is read: it arms and fires a timer. */
function lumpNow(b) {
  b.api.saveSoon();
  b.clock.fire();
  return lumpOf(b.store.blob);
}

const report = { mode: RAW_MODE, depth: DEPTH, runs: 0, reopens: 0, plain: 0, violations: {}, priced: {}, pricedSamples: [], samples: {}, crashes: [] };
/** A divergence in the PRICES (a customer is charged by them), kept apart from the rest: the path, what was compared, and the prices on each side. The twenty shortest paths. */
function notePriced(code, label, when, left, right) {
  report.priced[code] = (report.priced[code] || 0) + 1;
  const list = report.pricedSamples;
  if (list.length < 20 || label.length < list[list.length - 1].label.length) {
    list.push({ code: code, label: label, when: when, left: left, right: right });
    list.sort((x, y) => x.label.length - y.label.length || (x.label < y.label ? -1 : 1));
    if (list.length > 20) list.pop();
  }
}
function record(code, label, detail) {
  const v = (report.violations[code] = (report.violations[code] || 0) + 1);
  const s = (report.samples[code] = report.samples[code] || []);
  if (s.length < 12 || label.length < s[s.length - 1][0].length) { s.push([label, detail]); s.sort((x, y) => x[0].length - y[0].length || (x[0] < y[0] ? -1 : 1)); if (s.length > 12) s.pop(); }
  return v;
}

/** The section an answer step is about, on the page `b`: "carrier" is the section that carries the job's travel, "option" the first option (which is not the carrier). `want` says whether it must
 *  hold a Travel Labor line ("row", the x) or not ("none", Add Travel Labor). null when the bid has no such section. */
function answerTarget(b, which, want) {
  const m = b.api.root();
  let entries;
  try { entries = B.sectionsOf(m); } catch (e) { return null; }
  const carrier = B.travelCarrier(m);
  const held = (e) => travelRows(e.section).length > 0;
  const fit = entries.filter((e) => (which === "carrier" ? e.tab === carrier : e.kind === "option" && e.tab !== carrier) && (want === "row" ? held(e) : !held(e)));
  return fit.length ? fit[0].tab : null;
}

/** Take a step from the draft `saved`: returns the page after it, saved, plus the label's piece. `step` is { job, crew } | { variant } | { base } | { copy } | { x } | { addTravel }. */
async function take(saved, step, distanceAnswer) {
  const here = typeOfBlob(saved);
  const answer = { distance: Object.assign({}, distanceAnswer, { miles: distanceAnswer.miles === null ? null : 300 }) };
  if (step.job) {
    const b = await reopen(Object.assign(clone(saved), { work_type: step.job }), answer);
    b.api.go(1);
    await settle();
    const plain = step.job === here && !step.crew;
    const quiet = { armed: b.clock.armed(), saves: b.rec.saves.length, asked: (b.rec.distanceBodies || []).length };
    if (step.crew) { const c = STEP_CREW[step.job]; typeCrew(b, c[0], c[1], c[2], c[3]); }
    const was = plain ? shape(b) : null;
    if (!plain) b.clock.fire();
    return { b: b, plain: plain, quiet: quiet, was: was, piece: step.job + (step.crew ? "+crew" : ""), step: step };
  }
  // The lookup a CLEARED box asks again finds nothing (the estimator took the miles away); every other step's lookup is never asked of a saved bid.
  const b = await reopen(Object.assign(clone(saved), { work_type: here }), step.dist === "cleared" ? { distance: DISTANCES.unknown } : answer);
  b.api.go(1);
  await settle();
  if (step.dist !== undefined) {
    // The miles typed on the Labor step of the sheet that carries the job's travel, which is where the box is.
    b.api.show(B.travelCarrier(b.api.root()));
    b.api.go(1);
    if (!b.doc.querySelector("[data-dist-miles]")) return null;
    const before = optionRows(b);
    P.typeInto(b, "[data-dist-miles]", DIST_TEXT[step.dist]);
    await settle();
    b.clock.fire();
    const d = b.api.root().distance;
    return { b: b, plain: false, piece: "{" + step.dist + "}", dist: { before: before, miles: d ? B.milesOrNull(d.miles) : null }, step: step };
  }
  if (step.variant) {
    if (!applyVariant(b, step.variant)) return null;
    b.clock.fire();
    return { b: b, plain: false, piece: "[" + step.variant + "]", step: step };
  }
  if (step.x) {
    // THE x ON A TRAVEL LABOR LINE (round 6, part 2): the carrier's says the job has no drive, an option's says only that the option has none. Skipped when the bid has no such line to press it on.
    const tab = answerTarget(b, step.x, "row");
    if (tab === null) return null;
    b.api.show(tab);
    b.api.go(1);
    const i = idxIn(secOf(b.api.root(), tab), "travel");
    if (i < 0 || !b.doc.querySelector('[data-del-lab="' + i + '"]')) return null;
    P.clickOn(b, '[data-del-lab="' + i + '"]');
    await settle();
    b.clock.fire();
    return { b: b, plain: false, piece: "x:" + step.x, step: step };
  }
  if (step.addTravel) {
    // ADD TRAVEL LABOR on the carrier, or on an option that has none: skipped when the page draws no such button there.
    const tab = answerTarget(b, step.addTravel, "none");
    if (tab === null) return null;
    b.api.show(tab);
    b.api.go(1);
    if (!b.doc.querySelector("[data-add-travel]")) return null;
    P.clickOn(b, "[data-add-travel]");
    await settle();
    b.clock.fire();
    return { b: b, plain: false, piece: "addTravel:" + step.addTravel, step: step };
  }
  if (!(await sheetsAction(b, step))) return null;
  return { b: b, plain: false, piece: stepLabel(step), step: step };
}

/** THE EPOXY + POLISH-COPY PAIR (round 6, part 3, M1), made on the page `b` with the Sheets panel's own controls: the two bases are an Epoxy sheet and a COPY of the Polish root, and the root is
 *  an option. Both bases live under `tabs`, so which of them carries the job's travel (the first base) is decided by their order alone, and a reload hands `tabs` back in jsonb's order ("Copy1"
 *  before "Epoxy"): only each section's `seq` keeps it (the sheet-order work, round 6, C1; a far Combo of Epoxy 4 x 12 and a Polish copy 6 x 10 as the two bases was $78,628 as saved and
 *  $81,086 with the copy first). Made as the estimator makes it: an Epoxy sheet from the Add menu when the bid has none, a copy of the root from the root's bar when the bid holds none, the copy
 *  made the base (its radio, and yes), then "Make Epoxy + Polish the base" on the copy's bar. Its yes is left to sheetsAction, which saves after it. False when a control is not there, when the
 *  root is off (a Gyp or Epoxy job: the root would not be an option) and when the bases are that pair already (nothing would change). */
async function pairOfCopy(b) {
  const entries = () => B.sectionsOf(b.api.root());
  const copyOfRoot = () => entries().filter((e) => !e.root && e.role === "polish" && e.source === B.ROOT_TAB);
  if (entries()[0].kind === "off") return false;
  const bases = B.baseOf(b.api.root()).ids;
  if (bases.length === 2 && copyOfRoot().some((e) => bases.indexOf(e.tab) >= 0) && entries().some((e) => e.role === "epoxy" && bases.indexOf(e.tab) >= 0)) return false;
  if (!entries().some((e) => e.role === "epoxy")) {
    b.api.go(1);
    await settle();
    if (b.doc.querySelector('[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]');
    const add = '[data-sh-act="add"][data-sh-sheet="Epoxy"]';
    if (!b.doc.querySelector(add)) return false;
    P.clickOn(b, add);
    await settle();
  }
  if (!copyOfRoot().length) {
    const rootTab = '[data-section-tab="' + attrOf(B.ROOT_TAB) + '"]';
    if (b.doc.querySelector(rootTab)) { P.clickOn(b, rootTab); await settle(); }
    if (!b.doc.querySelector('[data-sh-act="copy"]')) return false;
    P.clickOn(b, '[data-sh-act="copy"]');
    await settle();
    if (!copyOfRoot().length) return false;
  }
  const copy = copyOfRoot().filter((e) => e.kind === "base")[0] || copyOfRoot()[0];
  if (copy.kind !== "base") {
    const radio = '[data-sh-base="' + attrOf(copy.tab) + '"]';
    if (!b.doc.querySelector(radio)) return false;
    b.doc.fire("change", { target: P.need(b, radio) });
    if (!b.doc.querySelector('[data-sh-act="base-yes"]')) return false;
    P.clickOn(b, '[data-sh-act="base-yes"]');
    await settle();
  }
  const pair = B.combinedPair(b.api.root());
  if (!pair || pair.indexOf(copy.tab) < 0) return false;
  const copyTab = '[data-section-tab="' + attrOf(copy.tab) + '"]';
  if (b.doc.querySelector(copyTab)) { P.clickOn(b, copyTab); await settle(); }
  if (!b.doc.querySelector('[data-sh-act="combine"]')) return false;
  P.clickOn(b, '[data-sh-act="combine"]');
  return true;
}

/** The Sheets panel's actions, made on an open page `b`: a copy of the sheet on show, a fresh sheet from the Add menu, a base change (a sheet's radio, or the "Make Epoxy + Polish the base" button for the
 *  pair, and then its yes), and the Epoxy + Polish-copy pair (pairOfCopy: several of them in a row, then its yes). The page is saved after it. False when the control is not there (the panel does not offer it at
 *  this state). A FRESH SHEET is an option that starts on the proposal. It holds no Travel Labor row: only the section that carries the job's travel has one. */
async function sheetsAction(b, step) {
  if (step.pair) {
    if (!(await pairOfCopy(b))) return false;
    if (!b.doc.querySelector('[data-sh-act="base-yes"]')) return false;
    P.clickOn(b, '[data-sh-act="base-yes"]');
  } else if (step.copy) {
    const sel = '[data-sh-act="copy"]';
    if (!b.doc.querySelector(sel)) return false;
    P.clickOn(b, sel);
  } else if (step.add) {
    b.api.go(1);
    await settle();
    if (b.doc.querySelector('[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]');
    const sel = '[data-sh-act="add"][data-sh-sheet="' + step.add + '"]';
    if (!b.doc.querySelector(sel)) return false;
    P.clickOn(b, sel);
  } else {
    if (step.base === "combined") {
      // THE PAIR PRICED TOGETHER is asked from the bar of either sheet of it (the strip's "Epoxy + Polish" tab until 2026-10-21): open one of the
      // pair when the sheet on show is not, then press its "Make Epoxy + Polish the base".
      const pair = B.combinedPair(b.api.root());
      if (!pair) return false;
      if (!b.doc.querySelector('[data-sh-act="combine"]')) {
        const tabSel = '[data-section-tab="' + pair[0] + '"]';
        if (!b.doc.querySelector(tabSel)) return false;
        P.clickOn(b, tabSel);
        await settle();
      }
      if (!b.doc.querySelector('[data-sh-act="combine"]')) return false;
      P.clickOn(b, '[data-sh-act="combine"]');
    } else {
      b.doc.fire("change", { target: P.need(b, '[data-sh-base="' + step.base + '"]') });
    }
    if (!b.doc.querySelector('[data-sh-act="base-yes"]')) return false;
    P.clickOn(b, '[data-sh-act="base-yes"]');
  }
  await settle();
  b.clock.fire();
  return true;
}

/** The context a path carries after a step. In the ANSWER walks `said` is true from the x on the carrier's line until the job's drive is back or a Sheets action ends the rule (a base pick can
 *  promote an option that holds a line of its own, a copy or a sheet added changes what the carrier is next to); a variant starts a context of its own. */
function nextCtx(ctx, step) {
  if (!ANSWER) return ctx;
  if (step.x === "carrier") return Object.assign({}, ctx, { said: true });
  if (step.addTravel === "carrier" || step.base !== undefined || step.copy || step.add || step.pair) return Object.assign({}, ctx, { said: null });
  return ctx;
}

/** ROUND 6, PART 3 (M3): did the job-type switch that ended a step make an OPTION that held a Travel Labor line of its own the carrier? Then it brought its own drive, as the Sheets panel's pick does
 *  (sectionsForJob settles the job's answer as pickBase does), and ANSWER_HELD ends with it. `parentSaved` is the draft before the step, read as the page would read it (migrateModel); `b` the page after. */
function promotedOwnLine(parentSaved, b) {
  if (!parentSaved || !parentSaved.polish_estimate) return false;
  let before, carrier;
  try { before = B.sectionsOf(B.migrateModel(clone(parentSaved.polish_estimate))); carrier = B.travelCarrier(b.api.root()); } catch (e) { return false; }
  const was = before.filter((e) => e.tab === carrier)[0];
  return !!was && was.kind === "option" && travelRows(was.section).length > 0;
}

/** The context to judge a step's page by and to carry on from it: nextCtx's, and ANSWER_HELD ended by a job-type switch that promoted an option holding its own line (promotedOwnLine). */
function ctxAfter(ctx, step, parentSaved, b) {
  return ANSWER && ctx && ctx.said === true && step.job && promotedOwnLine(parentSaved, b) ? Object.assign({}, ctx, { said: null }) : ctx;
}

/** A step as the walk's labels say it. */
function stepLabel(step) {
  return step.job ? step.job + (step.crew ? "+crew" : "") : step.variant ? "[" + step.variant + "]" : step.copy ? "copy" : step.add ? "add:" + step.add : step.x ? "x:" + step.x :
    step.addTravel ? "addTravel:" + step.addTravel : step.pair ? "pair:" + step.pair : step.dist !== undefined ? "{" + step.dist + "}" : "base:" + step.base;
}

/** The base changes the Sheets panel of this page offers, other than the base it already has: one sheet to a radio, and the pair priced
 *  together. The pair is a button on the bar of either sheet of it, drawn only while one of them is on show, so it is offered whenever the bid
 *  HAS the pair and it is not the base already, and first, where its tab stood in the strip before 2026-10-21. */
function basePicks(b) {
  const html = String((b.doc.getElementById("sheets-panel") || {}).innerHTML || "");
  const out = [];
  const have = B.baseOf(b.api.root()).ids;
  const pair = B.combinedPair(b.api.root());
  if (pair && !(have.length === 2 && pair.every((id) => have.indexOf(id) >= 0))) out.push("combined");
  [...html.matchAll(/data-sh-base="([^"]*)"/g)].forEach((mm) => {
    const v = mm[1].replace(/&quot;/g, '"').replace(/&amp;/g, "&");
    const ids = v === "combined" ? B.combinedPair(b.api.root()) : [v];
    if (!ids || (ids.length === have.length && ids.every((id) => have.indexOf(id) >= 0))) return;
    if (out.indexOf(mm[1]) < 0) out.push(mm[1]);
  });
  return out;
}

function stepsFor(page, path) {
  const used = path.some((p) => p.variant);
  const out = [];
  if (MODE === "far" || MODE === "local" || MODE === "unknown" || NIGHTS_TYPED) {
    TYPES.forEach((t) => { out.push({ job: t }); out.push({ job: t, crew: true }); });
  } else if (MODE === "mixed") {
    TYPES.forEach((t) => out.push({ job: t }));
    if (!used) VARIANTS.forEach((v) => out.push({ variant: v }));
  } else if (ANSWER) {
    // The job types (not in answerSheets), the Sheets actions (not in answerJobs: no sheet but the job's own, so no option to press anything on), and the answer.
    if (MODE !== "answerSheets") TYPES.forEach((t) => out.push({ job: t }));
    if (MODE !== "answerJobs") { basePicks(page).forEach((v) => out.push({ base: v })); out.push({ copy: true }); out.push({ add: "Epoxy" }); }
    if (MODE === "answer") out.push({ pair: "copy" });          // the Epoxy + Polish-copy pair (pairOfCopy): two bases under `tabs`, the root an option
    (MODE === "answerJobs" ? ["carrier"] : ["carrier", "option"]).forEach((w) => { out.push({ x: w }); out.push({ addTravel: w }); });
  } else if (SHEETS) {
    TYPES.forEach((t) => out.push({ job: t }));
    basePicks(page).forEach((v) => out.push({ base: v }));
    out.push({ copy: true });
    if (RELOAD || SESSION) out.push({ add: "Epoxy" });
    if (SESSION) out.push({ add: "Polish" });                // beside the root a Polish sheet is a Copy<N>: with an Epoxy base it is the other half of a pair that lives under `tabs`
    if (SESSION) out.push({ pair: "copy" });                 // the Epoxy + Polish-copy pair (pairOfCopy): bases Epoxy and a copy of the root, the root an option
    if (DIST) Object.keys(DIST_TEXT).forEach((k) => out.push({ dist: k }));
  } else {
    TYPES.forEach((t) => out.push({ job: t }));
  }
  return out;
}

/** The miles typed on the Labor step of the sheet that carries the job's travel, on the page `b`, and what the page then holds: every price (the lump sum a save writes, the root
 *  sheet's own bid, every other section's) and the shape of the Travel Labor rows. null when there is no box to type in. */
async function answerOn(b, dist) {
  b.api.show(B.travelCarrier(b.api.root()));
  b.api.go(1);
  if (!b.doc.querySelector("[data-dist-miles]")) return null;
  P.typeInto(b, "[data-dist-miles]", DIST_TEXT[dist]);
  await settle();
  b.clock.fire();
  const bids = b.api.sectionBids();
  return { lump: lumpOf(b.store.blob), root: b.api.bid().total, sections: Object.fromEntries(Object.keys(bids).sort().map((k) => [k, bids[k].total])), shape: shape(b) };
}

/** RELOAD_AGREES: a Sheets panel action (a base change, a copy, a sheet added) ends a step; the same answer to the distance, typed in the session that made the change and typed
 *  after a plain reopen of what that session saved, must leave the same prices and the same Travel Labor rows. Each side is built again from the parent's draft (the walk's own page
 *  is never typed on, so what its children are built from does not move). */
async function judgeReload(parentSaved, step, distanceAnswer, label) {
  for (const dist of Object.keys(DIST_TEXT)) {
    const answer = dist === "cleared" ? DISTANCES.unknown : distanceAnswer;
    const live = await take(parentSaved, step, distanceAnswer);
    const made = await take(parentSaved, step, distanceAnswer);
    if (!live || !made) return;
    const saved = clone(made.b.store.blob);
    const reopened = await reopen(saved, { distance: Object.assign({}, answer, { miles: answer.miles === null ? null : 300 }) });
    reopened.api.go(1);
    await settle();
    // A cleared box asks the lookup again, and the lookup finds nothing (the estimator took the miles away): on the page that made the change as on the reopened one.
    if (dist === "cleared") live.b.opts.distance = DISTANCES.unknown;
    const inSession = await answerOn(live.b, dist);
    const afterReload = await answerOn(reopened, dist);
    if (JSON.stringify(inSession) !== JSON.stringify(afterReload)) {
      // PRICES are what a customer is charged; the rest (the rows, the order of the sheets) is what the estimator reads. Said first, so a report tells the two apart.
      const priced = !inSession || !afterReload || JSON.stringify([inSession.lump, inSession.root, inSession.sections]) !== JSON.stringify([afterReload.lump, afterReload.root, afterReload.sections]);
      if (priced) notePriced("RELOAD_AGREES", label, "after {" + dist + "}", inSession && [inSession.lump, inSession.root, inSession.sections], afterReload && [afterReload.lump, afterReload.root, afterReload.sections]);
      record("RELOAD_AGREES", label, (priced ? "PRICES DIFFER: " : "same prices, other rows or order: ") + "after {" + dist + "} typed in the session " +
        JSON.stringify(inSession).slice(0, 170) + " VS after a reload " + JSON.stringify(afterReload).slice(0, 170));
    }
  }
}

/** DEMOTED_KEEPS (the fifth audit's decision, held by a rule of its own since round 6, part 2): a base the Sheets panel's pick DEMOTES to an option keeps the Travel Labor line it held, so the option prices its
 *  own drive from the moment of the pick (moveTravelLabor gives the new carrier a COPY). Until round 6 the walk saw a demotion that lost its line only through RELOAD_AGREES (the reload then gave the root a blank line,
 *  which the next answer filled, and the session had none); that blank line is gone, so a session and a reload now agree on a demotion that loses the line, and this says what the session must hold. */
function demotedKeeps(b, savedBefore) {
  const bad = [];
  let before;
  try { before = B.sectionsOf(B.migrateModel(clone(savedBefore.polish_estimate))); } catch (e) { return bad; }
  const after = facts(b).entries;
  before.forEach((e0) => {
    const e1 = after.filter((e) => e.tab === e0.tab)[0];
    if (e0.kind === "base" && e1 && e1.kind === "option" && travelRows(e0.section).length > 0 && travelRows(e1.section).length === 0) {
      bad.push(["DEMOTED_KEEPS", e0.tab + " was a base holding a Travel Labor line and is an option holding none"]);
    }
  });
  return bad;
}

async function judgeStep(label, got, parent, ctx, leaf, distanceAnswer) {
  const b = got.b;
  report.runs++;
  judge(b, ctx).forEach(([code, detail]) => record(code, label, detail));
  if (got.dist) judgeOptions(b, got.dist).forEach(([code, detail]) => record(code, label, detail));
  if (got.step && (got.step.base !== undefined || got.step.pair) && parent && parent.saved) demotedKeeps(b, parent.saved).forEach(([code, detail]) => record(code, label, detail));
  // THE SHEETS ACTIONS ARE JUDGED ONE MORE WAY, in the `reload` mode: the session against a reload (RELOAD_AGREES).
  if ((RELOAD || ANSWER) && parent && parent.saved && got.step && (got.step.base !== undefined || got.step.copy || got.step.add || got.step.x || got.step.addTravel || got.step.pair)) {
    report.reloadJudged = (report.reloadJudged || 0) + 1;
    await judgeReload(parent.saved, got.step, distanceAnswer, label);
  }
  if (got.plain) {
    report.plain++;
    if (got.quiet.armed !== 0 || got.quiet.saves !== 0 || got.quiet.asked !== 0) {
      record("PLAIN_REOPEN", label, "armed " + got.quiet.armed + " saves " + got.quiet.saves + " lookups " + got.quiet.asked);
    }
    if (parent && got.was !== parent.shape) record("PLAIN_REOPEN", label, "the rows moved: " + got.was.slice(0, 160) + " VS " + parent.shape.slice(0, 160));
    if (parent && lumpNow(b) !== parent.lump) {
      notePriced("REOPEN_AGREES", label, "a plain reopen", parent.lump, lumpOf(b.store.blob));
      record("REOPEN_AGREES", label, "PRICES DIFFER: the plain reopen prices " + lumpOf(b.store.blob) + ", the draft saved " + parent.lump);
    }
  } else if (leaf) {
    // A step that ended the path is reopened plain too (every other step has a plain child, which holds the same question).
    const saved = clone(b.store.blob);
    const again = await reopen(saved, { distance: DISTANCES.far });
    again.api.go(1);
    await settle();
    report.reopens++;
    const quiet = again.clock.armed() === 0 && again.rec.saves.length === 0;
    const same = shape(again) === shape(b);
    const lump = lumpNow(again);
    if (!quiet || !same || lump !== lumpOf(saved)) {
      if (lump !== lumpOf(saved)) notePriced("REOPEN_AGREES", label, "a reopen at the end of the path", lumpOf(saved), lump);
      record("REOPEN_AGREES", label, (lump !== lumpOf(saved) ? "PRICES DIFFER: " : "") + (quiet ? "" : "the reopen armed a save; ") +
        (same ? "" : "the rows moved on reopen: " + shape(b).slice(0, 150) + " VS " + shape(again).slice(0, 150) + "; ") +
        (lump === lumpOf(saved) ? "" : "saved " + lumpOf(saved) + " reopened " + lump));
    }
  }
}

async function walk(label, got, path, depth, ctx, distanceAnswer) {
  const b = got.b;
  const saved = clone(b.store.blob);
  const node = { shape: shape(b), lump: lumpOf(saved), saved: saved };
  if (depth === 0) return;
  const steps = stepsFor(b, path);
  for (const step of steps) {
    let child = null;
    const childLabel = label + " -> " + stepLabel(step);
    try { child = await take(saved, step, distanceAnswer); } catch (e) {
      report.crashes.push([childLabel, String((e && e.stack) || e).slice(0, 400)]);
      record("CRASH", childLabel, String((e && e.message) || e).slice(0, 200));
      continue;
    }
    if (!child) continue;
    const ctx2 = ctxAfter(step.variant ? { variant: step.variant } : nextCtx(ctx, step), step, saved, child.b);
    try { await judgeStep(childLabel, child, node, ctx2, depth === 1, distanceAnswer); } catch (e) {
      report.crashes.push([childLabel, String((e && e.stack) || e).slice(0, 400)]);
      record("CRASH", childLabel, "while judging: " + String((e && e.message) || e).slice(0, 200));
      continue;
    }
    await walk(childLabel, child, path.concat([step]), depth - 1, ctx2, distanceAnswer);
  }
}

// ── THE SESSION AGAINST A RELOAD (mode `session`) ────────────────────────────────────────────────────────────────────────────────────────────────────────
const attrOf = (s) => String(s).replace(/"/g, "&quot;");

/** One step of a session, made on the page that has carried the path so far. A Sheets action is made on the page itself; a job switch is the intake's, so the draft is saved and the
 *  estimate page is opened again on the SAME browser's copy of it (what localStorage hands back keeps the order the page wrote). Returns the page the session goes on with, or null
 *  when the panel does not offer the step here. */
async function advance(b, step, distanceAnswer) {
  if (step.job) {
    b.clock.fire();
    const saved = clone(b.store.blob);
    const next = await open(Object.assign(clone(saved), { work_type: step.job }), { distance: Object.assign({}, distanceAnswer, { miles: distanceAnswer.miles === null ? null : 300 }) });
    next.api.go(1);
    await settle();
    next.clock.fire();
    return next;
  }
  b.api.go(1);
  await settle();
  // A copy is a copy of the sheet that carries the job's travel, as in every other walk (its page opens on the carrier); a session is on whatever sheet the last action left open.
  if (step.copy) {
    const tab = '[data-section-tab="' + attrOf(B.travelCarrier(b.api.root())) + '"]';
    if (b.doc.querySelector(tab)) { P.clickOn(b, tab); await settle(); }
  }
  return (await sheetsAction(b, step)) ? b : null;
}

/** A new bid, and the steps of a path made one after the other on ONE page. null when a step is not offered. */
async function replaySession(start, steps, distanceAnswer) {
  let b = (await newBid(start, distanceAnswer)).b;
  for (const step of steps) {
    b = await advance(b, step, distanceAnswer);
    if (!b) return null;
  }
  return b;
}

/** What a session and a reload must agree on (SESSION_AGREES): every price, the sheets in order with their kinds, the carrier and the Travel Labor rows (`shape`), and the order
 *  priced_tabs lists the sheets in. A save is forced, so this runs after everything else is read. */
function sessionFacts(b) {
  const bids = b.api.sectionBids();
  const root = b.api.bid().total;
  const lump = lumpNow(b);
  return { lump: lump, root: root, sections: Object.fromEntries(Object.keys(bids).sort().map((k) => [k, bids[k].total])),
    priced: (b.store.blob.priced_tabs || []).map((t) => t.id + ":" + t.kind), shape: shape(b) };
}
const pricesOf = (f) => JSON.stringify(f ? [f.lump, f.root, f.sections] : null);

function compareSession(label, when, session, reload) {
  if (JSON.stringify(session) === JSON.stringify(reload)) return;
  const priced = pricesOf(session) !== pricesOf(reload);
  if (priced) notePriced("SESSION_AGREES", label, when, session && [session.lump, session.root, session.sections], reload && [reload.lump, reload.root, reload.sections]);
  record("SESSION_AGREES", label, (priced ? "PRICES DIFFER " : "same prices, other rows or order ") + when + ": in the session " + JSON.stringify(session).slice(0, 190) +
    " VS after a reload " + JSON.stringify(reload).slice(0, 190));
}

/** SESSION_AGREES, asked of the page a session has reached: as it stands, and after each of the four distance answers (typed on the draft as the session saved it, and on the draft as the
 *  server returns it). The session's own page is never typed on, so the path goes on from where it is. */
async function judgeSessionNode(label, b, distanceAnswer) {
  const lookup = (answer) => ({ distance: Object.assign({}, answer, { miles: answer.miles === null ? null : 300 }) });
  const here = sessionFacts(b);
  const saved = clone(b.store.blob);
  const r = await reopen(saved, lookup(distanceAnswer));
  r.api.go(1);
  await settle();
  report.sessions = (report.sessions || 0) + 1;
  compareSession(label, "as saved", here, sessionFacts(r));
  for (const dist of Object.keys(DIST_TEXT)) {
    const answer = dist === "cleared" ? DISTANCES.unknown : distanceAnswer;
    const same = await open(clone(saved), lookup(answer));          // the same browser's copy: the order the session wrote
    const after = await reopen(saved, lookup(answer));              // the server's
    same.api.go(1);
    after.api.go(1);
    await settle();
    // A cleared box asks the lookup again, and the lookup finds nothing (the estimator took the miles away).
    if (dist === "cleared") { same.opts.distance = DISTANCES.unknown; after.opts.distance = DISTANCES.unknown; }
    compareSession(label, "after {" + dist + "}", await answerOn(same, dist), await answerOn(after, dist));
  }
}

/** Every path of Sheets actions and job switches up to `depth`, each replayed in one continuous session and judged (judgeSessionNode) after every prefix. */
async function walkSession(start, steps, depth, distanceAnswer) {
  const label = "start:" + start + steps.map((st) => " -> " + stepLabel(st)).join("");
  let b = null;
  try { b = await replaySession(start, steps, distanceAnswer); } catch (e) {
    report.crashes.push([label, String((e && e.stack) || e).slice(0, 400)]);
    record("CRASH", label, String((e && e.message) || e).slice(0, 200));
    return;
  }
  if (!b) return;
  report.runs++;
  try { await judgeSessionNode(label, b, distanceAnswer); } catch (e) {
    report.crashes.push([label, String((e && e.stack) || e).slice(0, 400)]);
    record("CRASH", label, "while judging: " + String((e && e.message) || e).slice(0, 200));
    return;
  }
  if (depth === 0) return;
  for (const step of stepsFor(b, steps)) await walkSession(start, steps.concat([step]), depth - 1, distanceAnswer);
}

/** The 54 sequences the audit of 7d32336 found pricing the drive twice: start type, then steps (a "+" is the crew typed on the new carrier). */
const AUDIT54 = [
  "epoxy epoxy polish combo", "epoxy epoxy polish combo+", "epoxy epoxy polish+ combo", "epoxy epoxy polish+ combo+", "epoxy epoxy+ polish combo", "epoxy epoxy+ polish combo+",
  "epoxy epoxy+ polish+ combo", "epoxy epoxy+ polish+ combo+", "epoxy polish polish combo", "epoxy polish polish combo+", "epoxy polish polish+ combo", "epoxy polish polish+ combo+",
  "epoxy polish combo", "epoxy polish combo combo", "epoxy polish combo combo+", "epoxy polish combo+", "epoxy polish combo+ combo", "epoxy polish combo+ combo+",
  "epoxy polish+ polish combo", "epoxy polish+ polish combo+", "epoxy polish+ polish+ combo", "epoxy polish+ polish+ combo+", "epoxy polish+ combo", "epoxy polish+ combo combo",
  "epoxy polish+ combo combo+", "epoxy polish+ combo+", "epoxy polish+ combo+ combo", "epoxy polish+ combo+ combo+", "epoxy gyp polish combo", "epoxy gyp polish combo+",
  "epoxy gyp polish+ combo", "epoxy gyp polish+ combo+", "epoxy gyp+ polish combo", "epoxy gyp+ polish combo+", "epoxy gyp+ polish+ combo", "epoxy gyp+ polish+ combo+",
  "polish epoxy polish combo+", "polish epoxy polish+ combo+", "polish epoxy+ polish combo", "polish epoxy+ polish combo+", "polish epoxy+ polish+ combo", "polish epoxy+ polish+ combo+",
  "combo epoxy polish combo+", "combo epoxy polish+ combo+", "combo epoxy+ polish combo", "combo epoxy+ polish combo+", "combo epoxy+ polish+ combo", "combo epoxy+ polish+ combo+",
  "gyp epoxy polish combo+", "gyp epoxy polish+ combo+", "gyp epoxy+ polish combo", "gyp epoxy+ polish combo+", "gyp epoxy+ polish+ combo", "gyp epoxy+ polish+ combo+",
];

/** THE ANSWER'S OWN SEQUENCES (round 6, part 2): the ones the round-5 verification found, and the ones around them. A string is a job type ("epoxy", a "+" after it types the crew on the new
 *  carrier), anything else a step. Each is judged after every step by every rule above, and a Sheets action, an x and an Add are judged against a jsonb reload too. The audit's own labels:
 *    F1  far Combo -> Epoxy -> the x on the Epoxy carrier's Travel Labor -> Combo again (a session and a reload priced it $783 apart once the distance was typed)
 *    F2  far Polish -> the x -> an Epoxy sheet added and made the base -> Add Travel Labor on it (the demoted Polish option, $40,988 in the session and $41,771 after a reload)
 *    S1  far Polish -> an Epoxy sheet added -> job type Epoxy -> the x on the Epoxy carrier -> job type Polish
 *  and the answer's owner: an option's x, the root that is an option, a switch after the carrier's x, and Add on the carrier and on an option. */
const ANSWER_SEQUENCES = [
  { start: "combo", steps: ["epoxy", { x: "carrier" }, "combo"] },
  { start: "combo", steps: ["epoxy+", { x: "carrier" }, "combo+"] },
  { start: "polish", steps: [{ x: "carrier" }, { add: "Epoxy" }, { base: "Epoxy" }, { addTravel: "carrier" }] },
  { start: "polish", steps: [{ add: "Epoxy" }, "epoxy", { x: "carrier" }, "polish"] },
  { start: "polish", steps: [{ copy: true }, { x: "option" }, { addTravel: "option" }, { x: "carrier" }, { addTravel: "carrier" }] },
  { start: "polish", steps: [{ add: "Epoxy" }, { base: "Epoxy" }, { x: "option" }, { addTravel: "option" }, { base: "Polish" }] },
  { start: "polish", steps: [{ x: "carrier" }, "epoxy", "polish", "combo", "gyp", "polish"] },
  { start: "epoxy", steps: [{ x: "carrier" }, "combo", { addTravel: "carrier" }, "epoxy", "polish"] },
  { start: "combo", steps: [{ base: "Epoxy" }, { x: "carrier" }, { base: "Polish" }, { x: "carrier" }, { addTravel: "carrier" }] },
  { start: "gyp", steps: [{ x: "carrier" }, "polish", { addTravel: "carrier" }, "gyp"] },
  { start: "polish", steps: [{ copy: true }, { x: "carrier" }, { base: "Copy1" }, { x: "carrier" }] },
  { start: "polish", steps: [{ copy: true }, { x: "carrier" }, { x: "option" }, { addTravel: "option" }, "epoxy", "polish"] },
  { start: "epoxy", steps: [{ x: "carrier" }, "combo", "gyp", "epoxy+", "polish+"] },
  // THE EPOXY + POLISH-COPY PAIR (round 6, part 3, M1): an Epoxy sheet added first, so a reload's jsonb order puts the copy ("Copy1") before it and only `seq` keeps Epoxy the carrier; then the
  // job's answer on that carrier, a job-type switch and the answer taken back; and a Combo whose copy is made after its Epoxy base and paired, the demoted root's own line taken off and added back, and two switches.
  { start: "polish", steps: [{ add: "Epoxy" }, { pair: "copy" }, { x: "carrier" }, "combo", { addTravel: "carrier" }] },
  { start: "combo", steps: [{ pair: "copy" }, { x: "option" }, { addTravel: "option" }, "epoxy", "combo"] },
  // AN OPTION MADE THE CARRIER BRINGS ITS OWN DRIVE (round 6, part 3, M3): far Polish, an Epoxy option, the x on the Polish carrier, Add Travel Labor on the Epoxy option, then Epoxy made the base by
  // the intake's job type, and by the Sheets panel's pick. Both hand the job the option's own line (the answer goes), and the switch back to Polish carries that drive to the root, as a job's drive
  // follows its carrier.
  { start: "polish", steps: [{ add: "Epoxy" }, { x: "carrier" }, { addTravel: "option" }, "epoxy", "polish"] },
  { start: "polish", steps: [{ add: "Epoxy" }, { x: "carrier" }, { addTravel: "option" }, { base: "Epoxy" }] },
];

async function newBid(start, distanceAnswer) {
  const c = START_CREW[start];
  const b = await open(DRAFTS[start](), { distance: distanceAnswer });
  b.api.go(1);
  await settle();
  typeCrew(b, c[0], c[1], c[2], c[3]);
  b.clock.fire();
  return { b: b };
}

async function main() {
  const distanceKey = DIST_MODE || (MODE === "local" ? "local" : MODE === "unknown" ? "unknown" : "far");
  if (!DISTANCES[distanceKey]) throw new Error("no such distance " + distanceKey);
  const distanceAnswer = DISTANCES[distanceKey];
  if (MODE === "audit54") {
    const exact = {};
    for (const line of AUDIT54) {
      const words = line.split(" ");
      let got = await newBid(words[0], DISTANCES.far);
      let label = "start:" + words[0];
      let parent = { shape: shape(got.b), lump: lumpOf(got.b.store.blob) };
      judge(got.b, null).forEach(([code, detail]) => record(code, label, detail));
      for (const w of words.slice(1)) {
        const step = { job: w.replace("+", ""), crew: w.indexOf("+") >= 0 };
        label += " -> " + w;
        got = await take(clone(got.b.store.blob), step, DISTANCES.far);
        await judgeStep(label, got, parent, null, false);
        parent = { shape: shape(got.b), lump: lumpOf(got.b.store.blob) };
      }
      const f = facts(got.b);
      exact[line] = { dollars: f.entries.filter((e) => e.kind === "base").reduce((t, e) => t + travelRows(e.section).reduce((s, r) => s + cost(r), 0), 0),
        carrier: f.carrier, jobType: f.jobType };
    }
    report.exact = exact;
    report.sequences = AUDIT54.length;
    return;
  }
  if (MODE === "answers") {
    report.sequences = 0;
    for (const seq of ANSWER_SEQUENCES) {
      let got = await newBid(seq.start, distanceAnswer);
      let label = "start:" + seq.start;
      let parent = { shape: shape(got.b), lump: lumpOf(got.b.store.blob), saved: clone(got.b.store.blob) };
      let ctx = null;
      judge(got.b, ctx).forEach(([code, detail]) => record(code, label, detail));
      report.runs++;
      for (let i = 0; i < seq.steps.length; i++) {
        const s = seq.steps[i];
        const step = typeof s === "string" ? { job: s.replace("+", ""), crew: s.indexOf("+") >= 0 } : s;
        label += " -> " + stepLabel(step);
        ctx = nextCtx(ctx, step);
        let next = null;
        try { next = await take(parent.saved, step, distanceAnswer); } catch (e) {
          report.crashes.push([label, String((e && e.stack) || e).slice(0, 400)]);
          record("CRASH", label, String((e && e.message) || e).slice(0, 200));
          break;
        }
        if (!next) { report.skipped = (report.skipped || 0) + 1; (report.skippedAt = report.skippedAt || []).push(label); break; }     // the page offers nothing to press (it is what the walk would skip)
        ctx = ctxAfter(ctx, step, parent.saved, next.b);
        try { await judgeStep(label, next, parent, ctx, i === seq.steps.length - 1, distanceAnswer); } catch (e) {
          report.crashes.push([label, String((e && e.stack) || e).slice(0, 400)]);
          record("CRASH", label, "while judging: " + String((e && e.message) || e).slice(0, 200));
          break;
        }
        got = next;
        parent = { shape: shape(got.b), lump: lumpOf(got.b.store.blob), saved: clone(got.b.store.blob) };
      }
      report.sequences++;
    }
    return;
  }
  if (SESSION) {
    for (const start of TYPES) await walkSession(start, [], DEPTH, distanceAnswer);
    return;
  }
  const starts = TYPES;
  for (const start of starts) {
    let first = await newBid(start, distanceAnswer);
    let ctx = null;
    const label0 = "start:" + start;
    if (MODE_VARIANT) {
      const reopened = await reopen(first.b.store.blob, { distance: distanceAnswer });
      reopened.api.go(1);
      await settle();
      if (!applyVariant(reopened, MODE_VARIANT)) { report.skipped = (report.skipped || 0) + 1; continue; }
      reopened.clock.fire();
      first = { b: reopened };
      ctx = { variant: MODE_VARIANT };
    }
    if (NIGHTS_TYPED) {
      const reopened = await reopen(first.b.store.blob, { distance: distanceAnswer });
      reopened.api.go(1);
      await settle();
      if (!applyNights(reopened)) { report.skipped = (report.skipped || 0) + 1; continue; }
      reopened.clock.fire();
      first = { b: reopened };
      ctx = { nights: true };
    }
    const label = label0 + (ctx ? "[" + (MODE_VARIANT || "nights") + "]" : "");
    report.runs++;
    judge(first.b, ctx).forEach(([code, detail]) => record(code, label, detail));
    await walk(label, first, [], DEPTH, ctx, distanceAnswer);
  }
}

main().then(() => {
  report.crashes = report.crashes.slice(0, 5);
  console.log(JSON.stringify(report));
}).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
