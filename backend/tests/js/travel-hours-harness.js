"use strict";
/* Runs the REAL bid-model.js: THE DISTANCE FILLS TRAVEL LABOR on a job 70 miles or more out, THE WAY KYLE TYPES IT (Hanz,
 * 2026-10-20). The hours are one round trip from the Olathe office at 60 mph, to the half hour; the guys are the CREW'S SIZE
 * (the most guys on any labor line, the fourth hand of "Remove existing joint filler" counted, both base sheets of a Combo),
 * so each guy is charged one round trip, as Kyle types it on 9 of 10 out-of-town sheets of the 2026-10-20 scan. A figure the
 * estimator typed, or cleared, always wins; a switched-off row is left exactly as it is; under 70 miles, or with the miles
 * cleared, only the hours the tool wrote go back to empty; a bid saved before 2026-10-12 on the old man-days auto keeps them.
 *
 * Every answer is asked of the model the way the page asks it: applyDistance / clearDistance on the WHOLE model, then
 * B.syncAutoGuys, which changed() runs after every answer; and a keystroke is typeIn() below, which does what the page's
 * `input` handler does (the page itself is driven in polish-estimate-harness.js). `wichitaBare` is the one case that leaves
 * the sync out, to show the answer fills the guys by itself. The first version of this file (2026-10-20, "Every work day")
 * filled the guys with the MAN-DAYS: 48 x 6.5 x $33 = $10,296 for the example below; it is $858 now.
 *
 * Usage: node travel-hours-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
/** B's function `name`, or null for a tree that does not have it yet: a tree without the carrier-move code then fails the facts below, rather than
 *  stopping this whole run at its first mention. */
const later = (name) => (typeof B[name] === "function" ? B[name] : () => null);
const trvOf = (m) => m.labor.filter((r) => r.id === "travel")[0];
function ask(m, miles) { B.applyDistance(m, { miles: miles, source: "typed", key: "" }); B.syncAutoGuys(m); return m; }
function clear(m) { B.clearDistance(m); B.syncAutoGuys(m); return m; }
/** A keystroke in a Travel Labor box, as the page's `input` handler takes it: the row is marked, typing in an auto Guys box takes it
 *  off auto, the box holds the text as typed, and changed() then runs the sync. `key` is "guys" or "days" (the Hours box). */
function typeIn(m, key, text) {
  const r = trvOf(m);
  B.markTypedByHand(r, key);
  if (key === "guys" && r.guys_auto) r.guys_auto = false;
  r[key] = text;
  B.syncAutoGuys(m);
  return m;
}
function facts(m, row) {
  const r = row || trvOf(m);
  return { hours: r.days, seed: r.hours_seed === undefined ? null : r.hours_seed, auto: !!r.guys_auto,
           follow: r.guys_follow === undefined ? null : r.guys_follow, guys: r.guys, cost: B.laborCost(r), on: B.rowOn(r) };
}
const lineOf = (m, label) => B.travelHow(m).lines.filter((l) => l.indexOf(label) === 0)[0];

// A NEW bid, made the way the page makes it: the library's labor lines seeded onto a bid nobody has saved, every quantity
// emptied (the Travel row opens with no guys, no hours, off auto and with no marker). The crew is then typed as text.
const LIB = [{ id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, favorite: true, default_on: true }];
const seedCtx = (extra) => Object.assign({ saved: undefined, laborRows: B.withCrewFallback(clone(LIB)), laborRate: 33,
  travelRates: null, feesDefault: null, calcRows: null, conditionRows: null, cellValues: {}, split: false,
  asms: [], items: [], reserved: [], sf: {} }, extra || {});
const newBid = () => B.seedNewSections(B.migrateModel(undefined), seedCtx());
const row = (m, id) => m.labor.filter((r) => r.id === id)[0];
/** Polishing 4 guys for 12 days and nothing else on the crew: 4 guys, 48 man-days. */
function crewed(m) {
  const p = row(m, "polishing");
  p.guys = "4"; p.days = "12";
  return m;
}
const RATE = 33;

const out = {};
out.newRow = clone(trvOf(newBid()));

// 1. WICHITA: 190 miles on a new bid with the crew typed. 380 miles round trip at 60 mph is 6.33 hours, to the half hour 6.5;
//    the guys are the crew's 4; 4 x 6.5 x $33 = $858 (the 48 man-days are not the guys). The three travel lines come on.
const w = crewed(newBid()); ask(w, 190);
out.wichita = Object.assign(facts(w), {
  manDays: B.travelManDays(w.labor), crew: B.crewSize(w), expected: 4 * 6.5 * RATE, rate: trvOf(w).rate, local: w.conditions.local,
  lodging: w.travel.lodging.enabled, perDiem: w.travel.per_diem.enabled, source: B.driveHoursSource(w, trvOf(w)),
  words: B.driveHoursSentence(w, trvOf(w)), note: B.driveHoursNote(w, trvOf(w), w.labor),
  hint: B.travelGuysHint(w, trvOf(w), w.labor), how: B.travelHow(w).lines, howText: B.travelHow(w).text });
// ...the answer alone, without changed()'s sync after it: it fills the guys itself.
const wb = crewed(newBid()); B.applyDistance(wb, { miles: 190, source: "typed", key: "" });
out.wichitaBare = facts(wb);
// ...and the shipped model's own Travel row (marker "", on auto: the older man-days kind) is filled just the same, and an answer applied
// in a session puts it on the crew's size too (2026-10-20 audit: left on the man-days it priced 48 x 6.5 x $33 = $10,296). Merely OPENING
// it (migrate, sync) leaves it on its man-days, as it always was.
const sh = B.freshModel();
sh.labor = [{ id: "polishing", label: "Polishing", guys: 4, days: 12, rate: RATE }, trvOf(sh)];
const shOpen = B.migrateModel(clone(sh)); B.syncAutoGuys(shOpen);
out.shippedOpen = facts(shOpen);
ask(sh, 190);
out.shippedRow = facts(sh);
// ...no crew yet: the guys follow the labor lines, which have none, so the line prices nothing until they do.
const nc = newBid(); ask(nc, 190);
out.noCrewYet = Object.assign(facts(nc), { note: B.driveHoursNote(nc, trvOf(nc), nc.labor), how: lineOf(nc, "Travel Labor"),
  hint: B.travelGuysHint(nc, trvOf(nc), nc.labor) });
// ...and the crew typed AFTER the answer moves the guys with it, as the page's changed() does.
crewed(nc); B.syncAutoGuys(nc);
out.crewAfter = facts(nc);
// ...a crew lowered later lowers the guys: the Travel row's own guys are never part of the crew it follows.
const lowered = crewed(newBid()); ask(lowered, 190);
row(lowered, "polishing").guys = "2"; B.syncAutoGuys(lowered);
out.crewLowered = facts(lowered);
// ...one guy reads as one guy.
const one = newBid(); row(one, "polishing").guys = "1"; ask(one, 190);
out.oneGuy = { words: B.driveHoursSentence(one, trvOf(one)), guys: trvOf(one).guys };

// 2. THE CREW'S SIZE: the most guys on any ONE labor line (not the sum, not the man-days), the fourth hand counted, off lines
//    and the Travel row itself left out, a line with no guys counted as none, an hours line that is not Travel counted.
const cs = crewed(newBid());
const sizes = { polishing4: B.crewSize(cs) };
row(cs, "mockup").guys = "6"; row(cs, "mockup").enabled = false;
sizes.offLineLeftOut = B.crewSize(cs);
row(cs, "mockup").enabled = true;
sizes.mockup6 = B.crewSize(cs);
row(cs, "mockup").guys = "";
trvOf(cs).guys = 9;
sizes.travelRowLeftOut = B.crewSize(cs);
trvOf(cs).guys = "";
cs.labor.push({ id: "night", label: "Night shift", guys: "5", days: "3", rate: RATE, unit: "hours" });
sizes.hoursLineCounts = B.crewSize(cs);
sizes.empty = B.crewSize(newBid());
sizes.noModel = B.crewSize(null);
out.sizes = sizes;
// THE FOURTH HAND of "Remove existing joint filler" is one more guy on the joint-filler line, kept by removeExistingHand and not in
// the line's own Guys: 3 + 1 = 4 beats a crew of 3, only while both conditions are on, only on a line that is on, and only on a line
// that has guys (a line with no guys counts 0).
const hand = (patch) => {
  const m = newBid();
  row(m, "polishing").guys = "3"; row(m, "polishing").days = "5";
  row(m, "jointfill").guys = "3"; row(m, "jointfill").days = "2";
  Object.assign(m.conditions, { joint_filler: true, remove_existing_jf: true });
  if (patch) patch(m);
  return B.crewSize(m);
};
out.hand = {
  on: hand(), noRemoveExisting: hand((m) => { m.conditions.remove_existing_jf = false; }),
  noJointFiller: hand((m) => { m.conditions.joint_filler = false; }),
  lineOff: hand((m) => { row(m, "jointfill").enabled = false; }),
  lineWithNoGuys: hand((m) => { row(m, "jointfill").guys = ""; row(m, "polishing").guys = "2"; }),
  bigger: hand((m) => { row(m, "polishing").guys = "4"; }),
};
// ...and it reaches the line: 4 guys x 6.5 x $33 = $858, where 3 guys would be $643.50.
const hw = newBid();
row(hw, "polishing").guys = "3"; row(hw, "polishing").days = "5"; row(hw, "jointfill").guys = "3"; row(hw, "jointfill").days = "2";
Object.assign(hw.conditions, { joint_filler: true, remove_existing_jf: true });
ask(hw, 190);
out.handLine = facts(hw);
// A COMBO has one crew that drives once: the most over BOTH base sections (Polish 3 x 5, Epoxy 4 x 12), not the carrier's alone and not the sum.
const EP_LIB = B.withCrewFallback([
  { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, favorite: true, default_on: true },
  { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, favorite: true, default_on: true,
    default_work_types: ["epoxy"] }]);
const combo = (polishGuys, epoxyGuys) => {
  const cj = B.seedNewSections(B.activateSection(B.migrateModel(undefined), "Epoxy", "base", {}), seedCtx({ laborRows: EP_LIB }));
  row(cj.tabs.Epoxy, "epoxy-install").guys = String(epoxyGuys); row(cj.tabs.Epoxy, "epoxy-install").days = "12";
  row(cj, "polishing").guys = String(polishGuys); row(cj, "polishing").days = "5";
  return cj;
};
const cj = combo(3, 4); ask(cj, 190);
out.comboJob = Object.assign(facts(cj), { crew: B.crewSize(cj), manDays: B.travelManDays(cj.labor), carrier: B.travelCarrier(cj),
  epoxyHasTravel: cj.tabs.Epoxy.labor.some((r) => r.id === "travel"), words: B.driveHoursSentence(cj, trvOf(cj)),
  hint: B.travelGuysHint(cj, trvOf(cj), cj.labor), howGuys: B.travelHow(cj).lines.filter((l) => l.indexOf("Guys = ") === 0)[0] });
const cj2 = combo(5, 4); ask(cj2, 190);
out.comboPolishBigger = facts(cj2);
const cj3 = combo(3, 4); cj3.tabs.Epoxy.kind = "option"; B.syncAutoGuys(cj3); ask(cj3, 190);
out.comboOptionLeftOut = Object.assign(facts(cj3), { crew: B.crewSize(cj3) });

// 3. A TYPED FIGURE ALWAYS WINS. Hours typed over the 6.5 (text, as the box hands it over) survive a second answer.
const t = crewed(newBid()); ask(t, 190);
typeIn(t, "days", "4");
ask(t, 300);
out.typedHoursSurvive = Object.assign(facts(t), { marked: trvOf(t).hours_typed === true, source: B.driveHoursSource(t, trvOf(t)),
  note: B.driveHoursNote(t, trvOf(t), t.labor), how: lineOf(t, "Travel Labor") });
// ...even when what was typed spells the very digits the tool wrote.
const td = crewed(newBid()); ask(td, 190);
typeIn(td, "days", "6.5");
ask(td, 300);
out.typedSameDigits = facts(td);
// ...and with no marker at all a TEXT figure is still never the tool's (a row from before the markers), even spelling its digits.
const tm = crewed(newBid()); ask(tm, 190);
trvOf(tm).days = "4";
ask(tm, 300);
out.typedTextNoMarker = facts(tm);
const tdn = crewed(newBid()); ask(tdn, 190);
trvOf(tdn).days = "6.5";
ask(tdn, 300);
out.typedSameDigitsNoMarker = facts(tdn);
// ...guys the same: typed guys stay, the hours are filled.
const tg = crewed(newBid());
typeIn(tg, "guys", "2");
ask(tg, 190);
out.typedGuysSurvive = Object.assign(facts(tg), { marked: trvOf(tg).guys_typed === true,
  note: B.driveHoursNote(tg, trvOf(tg), tg.labor), how: lineOf(tg, "Travel Labor") });
// ...typed 0 hours is an answer too (it prices nothing), not a blank to fill.
const tz = crewed(newBid());
typeIn(tz, "days", "0");
ask(tz, 190);
out.typedZeroStays = facts(tz);
// ...typed guys from a row saved before the markers (a number in the box, off auto, no marker) are the estimator's too.
const sg = crewed(newBid()); trvOf(sg).guys = "2";
ask(sg, 190);
out.savedTypedGuys = facts(sg);

// 3b. A CLEARED BOX STAYS EMPTY (Hanz, 2026-10-12; the 2026-10-20 audit found an answer refilling one). Clearing is typing: the
//     marker is there, the box is empty, and no later answer writes into it.
const ch = crewed(newBid()); ask(ch, 190);
typeIn(ch, "days", "");
ask(ch, 300);
out.clearedHours = Object.assign(facts(ch), { marked: trvOf(ch).hours_typed === true, note: B.driveHoursNote(ch, trvOf(ch), ch.labor) });
const cg = crewed(newBid()); ask(cg, 190);
typeIn(cg, "guys", "");
ask(cg, 300);
out.clearedGuys = Object.assign(facts(cg), { marked: trvOf(cg).guys_typed === true });
// ...a box typed in and cleared BEFORE the first answer is cleared all the same.
const cb = crewed(newBid());
typeIn(cb, "days", "5"); typeIn(cb, "days", "");
typeIn(cb, "guys", "3"); typeIn(cb, "guys", "");
ask(cb, 190);
out.clearedBeforeAnswer = facts(cb);
// ...and the mark is saved with the row: a reopened bid (migrate, sync, then an answer) still leaves the cleared boxes empty.
const cr = B.migrateModel(clone(cb)); B.syncAutoGuys(cr);
ask(cr, 300);
out.clearedSurvivesReopen = facts(cr);
// ...typing marks only the Travel row, and typing in the Guys box takes the box off the crew's size.
const mk = crewed(newBid()); ask(mk, 190);
const polBefore = JSON.stringify(row(mk, "polishing"));
B.markTypedByHand(row(mk, "polishing"), "guys"); B.markTypedByHand(row(mk, "polishing"), "days");
out.markNonTravel = { same: JSON.stringify(row(mk, "polishing")) === polBefore, nullRow: String(B.markTypedByHand(null, "guys")) };
B.markTypedByHand(trvOf(mk), "guys");
out.markTravel = { follow: trvOf(mk).guys_follow === undefined ? null : trvOf(mk).guys_follow, typed: trvOf(mk).guys_typed, hoursTyped: trvOf(mk).hours_typed === undefined ? null : trvOf(mk).hours_typed };

// 4. AN UNTOUCHED FIGURE FOLLOWS THE NEXT ANSWER: 190 miles is 6.5 hours, 300 miles is 10.
const u = crewed(newBid()); ask(u, 190); ask(u, 300);
out.untouchedMoves = facts(u);
// ...every answer in turn on one bid: 190, 300, exactly 70 (2.33 hours, to the half 2.5), 69.9 (local), 120.4 (4.01, 4.5).
const seq = crewed(newBid());
out.sequence = [190, 300, 70, 69.9, 120.4].map((mi) => { ask(seq, mi); return [mi, trvOf(seq).days, trvOf(seq).hours_seed, seq.conditions.local]; });

// 5. GOING LOCAL takes the tool's own hours back and leaves typed ones. The line grays again (hours blank, local). The guys stay on the crew.
const lc = crewed(newBid()); ask(lc, 190); ask(lc, 20);
out.goingLocal = Object.assign(facts(lc), { local: lc.conditions.local, note: B.driveHoursNote(lc, trvOf(lc), lc.labor) });
const lk = crewed(newBid()); ask(lk, 190); typeIn(lk, "days", "4"); ask(lk, 20);
out.localKeepsTyped = Object.assign(facts(lk), { local: lk.conditions.local });
// ...and far again fills it again.
ask(lc, 190);
out.backToFar = facts(lc);
// CLEARING the miles is the same: the tool's hours go, typed ones stay.
const cl = crewed(newBid()); ask(cl, 190); clear(cl);
out.cleared = Object.assign(facts(cl), { local: cl.conditions.local, distance: cl.distance === undefined ? null : cl.distance });
const ck = crewed(newBid()); ask(ck, 190); typeIn(ck, "days", "4"); clear(ck);
out.clearedKeepsTyped = facts(ck);

// 6. A BID SAVED BEFORE. A row from 2026-10-12 and after (nothing typed, off auto) is filled when an answer is applied in a
//    session; a pre-2026-10-12 row on the OLD auto keeps its man-days WHILE THE BID MERELY OPENS, and an answer applied in a session
//    that FILLS its hours (empty, or the tool's own figure) puts it on the crew's size like every other row it fills (2026-10-20
//    audit: it used to keep the man-days, so the hours arriving took it from $0 to 48 x 6.5 x $33 = $10,296); a row whose hours were
//    typed is not filled, and keeps its man-days.
const old1 = crewed(newBid());
trvOf(old1).days = 5; trvOf(old1).guys_auto = true; trvOf(old1).guys = 16.5;                 // typed hours, a number, no marker
ask(old1, 300);
out.savedTypedHoursStay = facts(old1);
const old2 = crewed(newBid());
Object.assign(trvOf(old2), { days: 5, hours_seed: 5, guys_auto: true, guys: 16.5 });         // the 2026-10-06 era: the tool's own 5
// ...as SAVED (no answer yet, the distance it was written from still on the bid): the older words and the man-days
const old2open = clone(old2); old2open.distance = { miles: 150, source: "typed", key: "" }; old2open.conditions.local = false;
const old2o = B.migrateModel(old2open); B.syncAutoGuys(old2o);
out.savedMarkerOpen = Object.assign(facts(old2o), { note: B.driveHoursNote(old2o, trvOf(old2o), old2o.labor),
  how: lineOf(old2o, "Travel Labor"), hint: B.travelGuysHint(old2o, trvOf(old2o), old2o.labor), howText: B.travelHow(old2o).text });
ask(old2, 300);
out.savedMarkerFollows = Object.assign(facts(old2), { note: B.driveHoursNote(old2, trvOf(old2), old2.labor),
  how: lineOf(old2, "Travel Labor"), hint: B.travelGuysHint(old2, trvOf(old2), old2.labor), howText: B.travelHow(old2).text });
// the older auto with NO hours yet ($0 as it stands): opened, it is still $0 on the man-days; an answer fills the hours and puts the guys
// on the crew's size, so it prices crew x hours x rate (4 x 6.5 x $33 = $858) and not man-days x hours x rate (48 x 6.5 x $33 = $10,296)
const old3 = crewed(newBid());
Object.assign(trvOf(old3), { days: "", guys_auto: true, guys: "" });
const old3o = B.migrateModel(clone(old3)); B.syncAutoGuys(old3o);
out.savedAutoBlankOpen = Object.assign(facts(old3o), { manDays: B.travelManDays(old3o.labor) });
ask(old3, 190);
out.savedAutoBlankHours = Object.assign(facts(old3), { manDays: B.travelManDays(old3.labor), crew: B.crewSize(old3),
  note: B.driveHoursNote(old3, trvOf(old3), old3.labor), hint: B.travelGuysHint(old3, trvOf(old3), old3.labor) });
// OPENING moves nothing: migrate and sync a saved far job with Travel Labor blank, and the row is what was saved.
const saved = crewed(newBid());
saved.distance = { miles: 190, source: "google", key: "k" }; saved.conditions.local = false;
const savedRow = JSON.stringify(trvOf(saved));
const reopened = B.migrateModel(clone(saved)); B.syncAutoGuys(reopened);
out.openMovesNothing = { same: JSON.stringify(trvOf(reopened)) === savedRow, row: trvOf(reopened) };
// A SAVED crew-size row reopens as it was saved, and keeps following the crew.
const sv = crewed(newBid()); ask(sv, 190);
const svRow = JSON.stringify(trvOf(sv));
const svOpen = B.migrateModel(clone(sv)); B.syncAutoGuys(svOpen);
const svSame = JSON.stringify(trvOf(svOpen)) === svRow;
row(svOpen, "polishing").guys = "6"; B.syncAutoGuys(svOpen);
out.savedCrewRow = { sameOnOpen: svSame, afterCrewChange: facts(svOpen) };

// 7. WHICH SECTION. The Travel Labor row is the carrier's, with the carrier's own crew.
// an Epoxy job: the Polish root is off and Epoxy carries the travel
const ej = B.seedNewSections(B.activateSection(Object.assign(B.migrateModel(undefined), { kind: "off" }), "Epoxy", "base", {}),
  seedCtx({ laborRows: EP_LIB }));
row(ej.tabs.Epoxy, "epoxy-install").guys = "4";
row(ej.tabs.Epoxy, "epoxy-install").days = "12";
const epRowBefore = JSON.stringify(ej.labor.filter((r) => r.id === "travel")[0]);
ask(ej, 190);
const epTravel = ej.tabs.Epoxy.labor.filter((r) => r.id === "travel")[0];
out.epoxyJob = Object.assign(facts(ej, epTravel), { manDays: B.travelManDays(ej.tabs.Epoxy.labor), crew: B.crewSize(ej),
  rootRowUntouched: JSON.stringify(ej.labor.filter((r) => r.id === "travel")[0]) === epRowBefore, carrier: B.travelCarrier(ej) });
// a Gyp job prices its crew by the hour and works its own drive time: left exactly as it was
const GYP = 'Gyp (USG 1-8")';
const gj = B.activateSection(Object.assign(B.migrateModel(undefined), { kind: "off" }), GYP, "base", {});
gj.tabs[GYP].labor = [{ id: "pour", label: "Pour", guys: "4", days: "12", rate: 33, unit: "hours" },
  { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: false }];
const gypBefore = JSON.stringify(gj.tabs[GYP].labor);
ask(gj, 190);
out.gypJob = { untouched: JSON.stringify(gj.tabs[GYP].labor) === gypBefore, local: gj.conditions.local, distance: gj.distance };
// a bid with no Travel Labor row (the library said no): the answer is recorded and nothing throws
const nt = crewed(newBid()); nt.labor = nt.labor.filter((r) => r.id !== "travel"); nt.no_travel_labor = true;
let threw = null;
try { ask(nt, 190); } catch (e) { threw = String(e); }
out.noTravelRow = { threw: threw, distance: nt.distance, rows: nt.labor.map((r) => r.id) };

// 8. A SWITCHED-OFF ROW IS LEFT EXACTLY AS IT IS (the slider on its card, or its default on the Defaults tab): no fill, no take-back, no note.
const off1 = crewed(newBid()); trvOf(off1).enabled = false;
const off1Before = JSON.stringify(trvOf(off1));
ask(off1, 190);
out.offBefore = { untouched: JSON.stringify(trvOf(off1)) === off1Before, distance: off1.distance && off1.distance.miles, local: off1.conditions.local,
  note: B.driveHoursNote(off1, trvOf(off1), off1.labor), how: B.travelHow(off1).text };
const off2 = crewed(newBid()); ask(off2, 190); trvOf(off2).enabled = false;
const off2Before = JSON.stringify(trvOf(off2));
ask(off2, 300);
// ...and an off row that still holds the figures the CURRENT distance gave says nothing in the note (it adds nothing to the bid)
const off4 = crewed(newBid()); ask(off4, 190);
const noteOn = B.driveHoursNote(off4, trvOf(off4), off4.labor); trvOf(off4).enabled = false;
out.offNote = { on: noteOn, off: B.driveHoursNote(off4, trvOf(off4), off4.labor), sentenceOff: B.driveHoursSentence(off4, trvOf(off4)) };
out.offAfterFill = { untouched: JSON.stringify(trvOf(off2)) === off2Before, hours: trvOf(off2).days };
ask(off2, 20);
out.offThenLocal = { untouched: JSON.stringify(trvOf(off2)) === off2Before, hours: trvOf(off2).days };
trvOf(off2).enabled = true;
ask(off2, 300);
out.offThenOnAgain = facts(off2);
// a row the library defaulted OFF (libraryLaborRow writes enabled: false): the same
const LIB_OFF = [{ id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, favorite: true, default_on: false }];
const off3 = B.seedNewSections(B.migrateModel(undefined), seedCtx({ laborRows: B.withCrewFallback(clone(LIB_OFF)) }));
crewed(off3); const off3Before = JSON.stringify(trvOf(off3));
ask(off3, 190);
out.offByDefault = { enabled: trvOf(off3).enabled, untouched: JSON.stringify(trvOf(off3)) === off3Before };

// 9. A JOB TYPE SWITCHED IN THE SESSION puts the distance already on file on the NEW carrier's blank row (B.followDistance); a bid with no
//    distance on file, a local one, a typed or cleared box, and a switched-off row are all left as they are.
const fd = crewed(newBid()); fd.distance = { miles: 190, source: "google", key: "k" }; fd.conditions.local = false;
const fdBefore = JSON.stringify(trvOf(fd));
out.followDistance = { before: facts(fd), noDistance: (() => { const m = crewed(newBid()); const b = JSON.stringify(trvOf(m)); B.followDistance(m); return JSON.stringify(trvOf(m)) === b; })() };
B.followDistance(fd); B.syncAutoGuys(fd);
out.followDistance.after = facts(fd);
out.followDistance.changed = JSON.stringify(trvOf(fd)) !== fdBefore;
const fdLocal = crewed(newBid()); fdLocal.distance = { miles: 20, source: "google", key: "k" };
const fdLocalBefore = JSON.stringify(trvOf(fdLocal)); B.followDistance(fdLocal);
out.followDistance.local = JSON.stringify(trvOf(fdLocal)) === fdLocalBefore;
const fdTyped = crewed(newBid()); fdTyped.distance = { miles: 190, source: "google", key: "k" };
typeIn(fdTyped, "days", ""); typeIn(fdTyped, "guys", "2"); B.followDistance(fdTyped);
out.followDistance.typed = facts(fdTyped);
const fdOff = crewed(newBid()); fdOff.distance = { miles: 190, source: "google", key: "k" }; trvOf(fdOff).enabled = false;
const fdOffBefore = JSON.stringify(trvOf(fdOff)); B.followDistance(fdOff);
out.followDistance.off = JSON.stringify(trvOf(fdOff)) === fdOffBefore;
out.followDistance.noModel = String(B.followDistance(null));

// 10. THE OTHER TWO LINES ARE AS THEY WERE: switched on by the answer, a hand flip never moved, quantities typed.
const ln = crewed(newBid()); ln.travel.lodging.hand = true; ln.travel.lodging.enabled = false;
ask(ln, 190);
out.lines = { lodging: ln.travel.lodging.enabled, perDiem: ln.travel.per_diem.enabled, lodgingQty: ln.travel.lodging.qty,
  perDiemQty: ln.travel.per_diem.qty, lodgingAuto: ln.travel.lodging.qty_auto, perDiemAuto: ln.travel.per_diem.qty_auto };

// 11. WORDS. A figure the distance wrote says the trip and who it is charged to; one it wrote for a distance that has gone says so;
//     a typed one says typed; a crew of none says what to type.
const wd = crewed(newBid()); ask(wd, 190);
const stale = crewed(newBid()); Object.assign(trvOf(stale), { days: 5, hours_seed: 5, guys_auto: true, guys: 48 });
stale.distance = { miles: 190, source: "typed", key: "" };             // 190 miles would give 6.5, not the 5 it holds
const gone = crewed(newBid()); Object.assign(trvOf(gone), { days: 5, hours_seed: 5, guys_auto: true, guys: 48 });
const frac = crewed(newBid()); ask(frac, 120.4);
out.words = {
  tool: lineOf(wd, "Travel Labor"), staleSource: B.driveHoursSource(stale, trvOf(stale)), stale: lineOf(stale, "Travel Labor"),
  goneSource: B.driveHoursSource(gone, trvOf(gone)), gone: lineOf(gone, "Travel Labor"),
  areTools: [B.driveHoursAreTools(trvOf(wd)), B.driveHoursAreTools({ days: "6.5", hours_seed: 6.5 }),
             B.driveHoursAreTools({ days: 6.5, hours_seed: "" }), B.driveHoursAreTools({ days: 6.5 }), B.driveHoursAreTools(null),
             B.driveHoursAreTools({ days: 6.5, hours_seed: 6.5, hours_typed: true })],
  fractional: B.driveHoursSentence(frac, trvOf(frac)),
  followsCrew: [B.followsCrew(trvOf(wd)), B.followsCrew({ guys_auto: true }), B.followsCrew({ guys_auto: false, guys_follow: "crew" }), B.followsCrew(null)],
};

// 12. BAD INPUT. An answer with no usable miles records nothing and changes nothing; no model is no model.
const bad = crewed(newBid()); const badBefore = JSON.stringify(bad);
B.applyDistance(bad, { miles: "abc", source: "typed", key: "" });
B.applyDistance(bad, null);
out.badInput = { unchanged: JSON.stringify(bad) === badBefore, nullModel: B.applyDistance(null, { miles: 190 }),
  clearNull: String(B.clearDistance(undefined)) };

// 13. PRICED: no hours is $0 until the figure is there, and the cost is guys x hours x the line's own rate.
const pr = crewed(newBid());
out.pricedBefore = B.laborCost(trvOf(pr));
ask(pr, 190);
out.pricedAfter = B.laborCost(trvOf(pr));
trvOf(pr).rate = 40;
out.pricedAtOwnRate = B.laborCost(trvOf(pr));

// 14. A CARRIER MOVE, on the model alone (the page runs the same call after a job type switch and a base change; travel-switch-harness.js
//     drives it through the real page). The job's drive is one trip, so ONE Travel Labor row is priced for it: `followDistance(model,
//     fromTab)` carries the row to a new carrier that has none, fills the new carrier's row, and takes back the filled row an old carrier
//     keeps while it is still a base. An Epoxy job (the Polish root off, Epoxy carrying the travel, crew 4 x 12), asked 190 miles:
const epoxyJob = () => {
  const m = B.seedNewSections(B.activateSection(Object.assign(B.migrateModel(undefined), { kind: "off" }), "Epoxy", "base", {}),
    seedCtx({ laborRows: EP_LIB }));
  row(m.tabs.Epoxy, "epoxy-install").guys = "4";
  row(m.tabs.Epoxy, "epoxy-install").days = "12";
  ask(m, 190);
  return m;
};
const sectionOf = (m, tab) => (tab === B.ROOT_TAB ? m : m.tabs[tab]);
const travelIn = (m, tab) => (sectionOf(m, tab).labor || []).filter((r) => r.id === "travel")[0] || null;
const factsIn = (m, tab) => (travelIn(m, tab) ? facts(m, travelIn(m, tab)) : null);
const countIn = (m, tab) => (sectionOf(m, tab).labor || []).filter((r) => r.id === "travel").length;
/** What the page does on a job type switch: the sections follow the job type, then the distance on file settles the rows, given the carrier
 *  the job had. */
const switchTo = (m, jobType, noFrom) => {
  const before = B.travelCarrier(m);
  const next = B.sectionsForJob(m, jobType, { rules: [] });
  B.followDistance(next, noFrom ? undefined : before);
  B.syncAutoGuys(next);
  return next;
};
/** The Travel Labor dollars the sections that are part of the bid carry: the job's one drive is priced once when this is one row's worth. */
const drive$ = (m) => B.sectionsOf(m).filter((e) => e.kind !== "off").reduce((t, e) => t + (travelIn(m, e.tab) ? B.laborCost(travelIn(m, e.tab)) : 0), 0);
const tabsOf = (m) => B.sectionsOf(m).map((e) => [e.tab, e.kind]);

// (a) Epoxy to Polish: the Polish root is the new carrier and holds the model's own older man-days row (the root of an Epoxy job is never
//     seeded). The answer on file puts it on the crew's size: 4 guys x 6.5 hours x $33 = $858, where the man-days left 49.5 x 6.5 x $33.
const ep = switchTo(epoxyJob(), "polish");
row(ep, "polishing").guys = "4"; row(ep, "polishing").days = "12"; B.syncAutoGuys(ep);
out.moveEpoxyToPolish = { carrier: B.travelCarrier(ep), root: factsIn(ep, B.ROOT_TAB), epoxy: factsIn(ep, "Epoxy"), drive: drive$(ep),
  manDays: B.travelManDays(ep.labor), kinds: tabsOf(ep), rootRows: countIn(ep, B.ROOT_TAB) };
// (b) Epoxy to Combo: the root is the carrier and Epoxy is still a base. Epoxy's filled row is taken back (guys and hours empty, every
//     marker gone), so the drive is priced once.
const ec = switchTo(epoxyJob(), "combo");
row(ec, "polishing").guys = "4"; row(ec, "polishing").days = "12"; B.syncAutoGuys(ec);
const ecRow = travelIn(ec, "Epoxy");
out.moveEpoxyToCombo = { carrier: B.travelCarrier(ec), root: factsIn(ec, B.ROOT_TAB), epoxy: factsIn(ec, "Epoxy"), drive: drive$(ec),
  epoxyKeys: ecRow ? Object.keys(ecRow).sort() : null, kinds: tabsOf(ec), rootRows: countIn(ec, B.ROOT_TAB), epoxyRows: countIn(ec, "Epoxy") };
// ...with no carrier handed to followDistance (a caller that does not know which section carried the travel) the same rows are settled: it
// finds the filled row on the section that is a base and no longer the carrier by looking.
const ecPlain = switchTo(epoxyJob(), "combo", true);
row(ecPlain, "polishing").guys = "4"; row(ecPlain, "polishing").days = "12"; B.syncAutoGuys(ecPlain);
out.moveEpoxyToComboInferred = { root: factsIn(ecPlain, B.ROOT_TAB), epoxy: factsIn(ecPlain, "Epoxy"), drive: drive$(ecPlain),
  rootRows: countIn(ecPlain, B.ROOT_TAB), epoxyRows: countIn(ecPlain, "Epoxy") };
// (c) Combo to Epoxy: the root carries the travel and its row is filled; Epoxy has none. The row goes with the carrier, to Epoxy, and is
//     filled by the rule: the root, which is off now, keeps none.
const comboJob = () => { const cj = combo(4, 4); ask(cj, 190); return cj; };
const ce = switchTo(comboJob(), "epoxy");
out.moveComboToEpoxy = { carrier: B.travelCarrier(ce), root: factsIn(ce, B.ROOT_TAB), epoxy: factsIn(ce, "Epoxy"), drive: drive$(ce),
  rootHasRow: !!travelIn(ce, B.ROOT_TAB), kinds: tabsOf(ce), how: B.travelHow(B.sectionView(ce, "Epoxy")).lines[0] };
// ...and with no carrier handed in the stranded row is found: the first Travel Labor row of an off or base section that is not the carrier.
const ceNo = switchTo(comboJob(), "epoxy", true);
out.moveComboToEpoxyInferred = { epoxy: factsIn(ceNo, "Epoxy"), rootHasRow: !!travelIn(ceNo, B.ROOT_TAB), drive: drive$(ceNo) };
// ...never an option's row (an option is priced apart and its row is its own), and never a row for a bid whose library said no Travel Labor.
const opn = comboJob(); opn.kind = "option";
const opnTo = B.sectionsForJob(opn, "epoxy", { rules: [] }); opnTo.tabs.Epoxy.labor = opnTo.tabs.Epoxy.labor.filter((r) => r.id !== "travel");
opnTo.kind = "option";
B.followDistance(opnTo); B.syncAutoGuys(opnTo);
out.moveOptionNotCarried = { epoxyHasRow: !!travelIn(opnTo, "Epoxy"), rootKeepsRow: !!travelIn(opnTo, B.ROOT_TAB), kinds: tabsOf(opnTo) };
const nol = comboJob(); nol.no_travel_labor = true;
const nolTo = switchTo(nol, "epoxy", true);
out.moveNoTravelLabor = { epoxyHasRow: !!travelIn(nolTo, "Epoxy"), rootKeepsRow: !!travelIn(nolTo, B.ROOT_TAB) };
// (d) WHAT THE ESTIMATOR SAID FOLLOWS THE JOB'S DRIVE (2026-10-20 audit; before it, a typed row was left on the old carrier and priced beside the new
//     carrier's filled one: $858 + $495). Epoxy to Combo with Epoxy's row typed 3 guys x 5 hours: the root takes the typed row, markers and all, and Epoxy gives
//     the row back empty; the drive is priced once, as typed.
const marksOf = (r) => (r ? { typed: r.guys_typed === true, hoursTyped: r.hours_typed === true, off: r.enabled === false, keys: Object.keys(r).sort() } : null);
const marksIn = (m, tab) => marksOf(travelIn(m, tab));
const typedEpoxy = () => {
  const m = epoxyJob(); const r = travelIn(m, "Epoxy");
  B.markTypedByHand(r, "guys"); r.guys_auto = false; r.guys = "3"; B.markTypedByHand(r, "days"); r.days = "5";
  return m;
};
const etc = switchTo(typedEpoxy(), "combo");
row(etc, "polishing").guys = "4"; row(etc, "polishing").days = "12"; B.syncAutoGuys(etc);
out.moveTypedFollows = { root: factsIn(etc, B.ROOT_TAB), rootMarks: marksIn(etc, B.ROOT_TAB), epoxy: factsIn(etc, "Epoxy"), epoxyMarks: marksIn(etc, "Epoxy"),
  drive: drive$(etc), rootRows: countIn(etc, B.ROOT_TAB), epoxyRows: countIn(etc, "Epoxy") };
// ...a box CLEARED follows too (the next answer never refills it, wherever the job's drive is), and so does a row switched OFF.
const clearedEpoxy = (key) => {
  const m = epoxyJob(); const r = travelIn(m, "Epoxy");
  B.markTypedByHand(r, key);
  if (key === "guys") r.guys_auto = false;
  r[key] = "";
  return m;
};
const ech = switchTo(clearedEpoxy("days"), "combo"); row(ech, "polishing").guys = "4"; row(ech, "polishing").days = "12"; B.syncAutoGuys(ech);
const ecg = switchTo(clearedEpoxy("guys"), "combo"); row(ecg, "polishing").guys = "4"; row(ecg, "polishing").days = "12"; B.syncAutoGuys(ecg);
out.moveClearedFollows = { hours: { root: factsIn(ech, B.ROOT_TAB), rootMarks: marksIn(ech, B.ROOT_TAB), epoxy: factsIn(ech, "Epoxy"), drive: drive$(ech) },
  guys: { root: factsIn(ecg, B.ROOT_TAB), rootMarks: marksIn(ecg, B.ROOT_TAB), epoxy: factsIn(ecg, "Epoxy"), drive: drive$(ecg) } };
ask(ech, 300); ask(ecg, 300);        // ...and a later answer leaves what was cleared empty, on the new carrier
out.moveClearedStaysEmpty = { hours: factsIn(ech, B.ROOT_TAB), guys: factsIn(ecg, B.ROOT_TAB) };
// (e) a row switched OFF follows the carrier too (the slider is the estimator's), and an option's row is its own (the old carrier is an option, not a base,
//     afterwards).
const offEpoxy = () => { const m = epoxyJob(); travelIn(m, "Epoxy").enabled = false; return m; };
const eo = offEpoxy();
const eoBefore = JSON.stringify(travelIn(eo, "Epoxy"));
const eoc = switchTo(eo, "combo");
out.moveOffFollows = { root: factsIn(eoc, B.ROOT_TAB), rootMarks: marksIn(eoc, B.ROOT_TAB), epoxy: factsIn(eoc, "Epoxy"), epoxyMarks: marksIn(eoc, "Epoxy"),
  drive: drive$(eoc), movedFigures: JSON.stringify(Object.assign({}, travelIn(eoc, B.ROOT_TAB), { guys: 0 })) === JSON.stringify(Object.assign(JSON.parse(eoBefore), { guys: 0 })) };
const op = epoxyJob();
const opBefore = JSON.stringify(travelIn(op, "Epoxy"));
delete op.kind; op.tabs.Epoxy.kind = "option";            // the Polish root is the base now and Epoxy an option, priced apart
B.followDistance(op, "Epoxy");
out.moveOptionStays = { carrier: B.travelCarrier(op), same: JSON.stringify(travelIn(op, "Epoxy")) === opBefore };
// (f) a carrier that did not move, however it is asked, takes nothing back and carries nothing; no model is no model.
const same = epoxyJob();
const sameBefore = JSON.stringify(same);
B.followDistance(same, "Epoxy");
out.moveSameCarrier = { same: JSON.stringify(same) === sameBefore };
out.moveNoModel = String(B.followDistance(null, "Polish"));
// (h) the old carrier keeps no other row (a root that holds only Travel Labor): the row is COPIED, and the two sections never share one object.
const only = comboJob();
only.labor = only.labor.filter((r) => r.id === "travel");
const onlyTo = switchTo(only, "epoxy");
out.moveCopy = { rootKeeps: !!travelIn(onlyTo, B.ROOT_TAB), epoxy: factsIn(onlyTo, "Epoxy"),
  aliased: !!travelIn(onlyTo, B.ROOT_TAB) && travelIn(onlyTo, B.ROOT_TAB) === travelIn(onlyTo, "Epoxy") };
// (g) a carrier moved under a LOCAL job (or none on file) fills nothing, and the row still goes with the carrier.
const loc = comboJob(); B.applyDistance(loc, { miles: 20, source: "typed", key: "" }); B.syncAutoGuys(loc);
const lo = switchTo(loc, "epoxy");
out.moveLocal = { epoxy: factsIn(lo, "Epoxy"), rootHasRow: !!travelIn(lo, B.ROOT_TAB), local: lo.conditions.local };

// 14b. THE THIRD AUDIT'S SETTLING (2026-10-20, of 7d32336). Every restructure settles the job's one drive; the page (init and the Sheets panel) calls
//      followDistance(model, fromTab) after every one of them, and test_polish_travel_sequences.py walks every sequence of them on the real page.
//      Written to be run exactly the way init() runs it: the sections follow the job type, a NEW section is seeded from the library (it is given a blank
//      Travel Labor row when it is the carrier), then the settling, then the sync.
const switchSeeded = (m, jobType) => {
  const before = B.travelCarrier(m);
  const next = B.seedNewSections(B.sectionsForJob(m, jobType, { rules: [] }), seedCtx({ saved: m, laborRows: EP_LIB }));
  B.followDistance(next, before);
  B.syncAutoGuys(next);
  return next;
};
// (i) EVERY SECTION THAT IS NOT THE CARRIER GIVES THE FILLED ROW BACK, OFF SECTIONS TOO. Epoxy to Polish to Combo priced the drive twice: Epoxy's filled row
//     was left on the off section and was priced again the day Combo turned the section back on ($1,716).
const seqRows = (m) => ({ polish: factsIn(m, B.ROOT_TAB), epoxy: factsIn(m, "Epoxy"), epoxyKeys: (travelIn(m, "Epoxy") ? Object.keys(travelIn(m, "Epoxy")).sort() : null),
  drive: drive$(m), carrier: B.travelCarrier(m), kinds: tabsOf(m) });
const s1 = switchTo(epoxyJob(), "polish");
row(s1, "polishing").guys = "4"; row(s1, "polishing").days = "12"; B.syncAutoGuys(s1);
const s2 = switchTo(s1, "combo");
const s3 = switchTo(s2, "epoxy");
const s4 = switchTo(s3, "combo");
out.settleSequence = { toPolish: seqRows(s1), toCombo: seqRows(s2), toEpoxy: seqRows(s3), toComboAgain: seqRows(s4) };
// ...an OFF section's row is given back directly, an option's is not, and a row the estimator typed on an off section is theirs.
const offSec = epoxyJob(); offSec.tabs.Epoxy.kind = "off"; delete offSec.kind;      // the root is the carrier; Epoxy is off and holds the filled row
B.takeBackStrayTravel(offSec);
const optSec = epoxyJob(); optSec.tabs.Epoxy.kind = "option"; delete optSec.kind;
const optBefore = JSON.stringify(travelIn(optSec, "Epoxy"));
B.takeBackStrayTravel(optSec);
const typedOff = typedEpoxy(); typedOff.tabs.Epoxy.kind = "off"; delete typedOff.kind;
const typedOffBefore = JSON.stringify(travelIn(typedOff, "Epoxy"));
B.takeBackStrayTravel(typedOff);
const offBase = epoxyJob(); delete offBase.kind; travelIn(offBase, "Epoxy").enabled = false;      // the root carries; Epoxy is a BASE whose row is switched off
const offBaseBefore = JSON.stringify(travelIn(offBase, "Epoxy"));
B.takeBackStrayTravel(offBase);
out.takeBackOff = { off: factsIn(offSec, "Epoxy"), offKeys: travelIn(offSec, "Epoxy") ? Object.keys(travelIn(offSec, "Epoxy")).sort() : null, option: JSON.stringify(travelIn(optSec, "Epoxy")) === optBefore,
  typedOff: JSON.stringify(travelIn(typedOff, "Epoxy")) === typedOffBefore, offRowStays: JSON.stringify(travelIn(offBase, "Epoxy")) === offBaseBefore };
// (ii) A NEW CARRIER IS A NEWLY SEEDED SECTION WITH A BLANK TRAVEL LABOR ROW, and what the estimator said on the old carrier follows the job's drive to it:
//      Polish (crew 4 x 12, 190 miles) switched to Epoxy. A row nobody touched is filled fresh: 4 x 6.5 x $33. Typed 3 x 5, a cleared box and a row
//      switched off all move to Epoxy, and are not filled (the audit: all three read $858 on the new carrier).
const polishFar = () => { const m = crewed(newBid()); ask(m, 190); return m; };
const toEpoxy = (m) => {
  const n = switchSeeded(m, "epoxy");
  row(n.tabs.Epoxy, "epoxy-install").guys = "4"; row(n.tabs.Epoxy, "epoxy-install").days = "12"; B.syncAutoGuys(n);
  return { epoxy: factsIn(n, "Epoxy"), epoxyMarks: marksIn(n, "Epoxy"), root: factsIn(n, B.ROOT_TAB), rootMarks: marksIn(n, B.ROOT_TAB), drive: drive$(n),
    epoxyRows: countIn(n, "Epoxy"), rootRows: countIn(n, B.ROOT_TAB), _model: n };
};
const seeded = { auto: toEpoxy(polishFar()) };
const sTyped = polishFar(); typeIn(sTyped, "guys", "3"); typeIn(sTyped, "days", "5"); seeded.typed = toEpoxy(sTyped);
const sHours = polishFar(); typeIn(sHours, "days", ""); seeded.clearedHours = toEpoxy(sHours);
const sGuys = polishFar(); typeIn(sGuys, "guys", ""); seeded.clearedGuys = toEpoxy(sGuys);
const sOff = polishFar(); trvOf(sOff).enabled = false; seeded.off = toEpoxy(sOff);
// ...a later answer still leaves what moved alone (the typed 3 x 5, the empty box), and the sections moving on again carry it on (Epoxy back to Polish).
ask(seeded.typed._model, 300); ask(seeded.clearedHours._model, 300);
seeded.laterAnswer = { typed: factsIn(seeded.typed._model, "Epoxy"), clearedHours: factsIn(seeded.clearedHours._model, "Epoxy") };
const backToPolish = switchSeeded(seeded.typed._model, "polish");
seeded.backToPolish = { root: factsIn(backToPolish, B.ROOT_TAB), rootMarks: marksIn(backToPolish, B.ROOT_TAB), epoxy: factsIn(backToPolish, "Epoxy"),
  epoxyMarks: marksIn(backToPolish, "Epoxy"), drive: drive$(backToPolish) };
Object.keys(seeded).forEach((k) => { if (seeded[k] && seeded[k]._model) delete seeded[k]._model; });
out.followsSeeded = seeded;
// (iii) WHEN THE NEW CARRIER'S OWN ROW IS THE ESTIMATOR'S TOO, both are theirs and both stay (nothing to choose between): Epoxy typed 3 x 5, the root typed 2 x 4.
const both = typedEpoxy();
{ const r = travelIn(both, B.ROOT_TAB); B.markTypedByHand(r, "guys"); r.guys_auto = false; r.guys = "2"; B.markTypedByHand(r, "days"); r.days = "4"; }
const bothTo = switchTo(both, "combo");
out.ownedBothStay = { root: factsIn(bothTo, B.ROOT_TAB), epoxy: factsIn(bothTo, "Epoxy"), drive: drive$(bothTo) };
// (iv) THE COPY CASE FOR AN ESTIMATOR'S ROW: a root that holds only Travel Labor cannot give it away, so the row is copied, and the copy the old carrier keeps
//      is released (it was the estimator's, and must not stay priced beside the one that arrived).
const onlyTyped = comboJob();
onlyTyped.labor = onlyTyped.labor.filter((r) => r.id === "travel");
{ const r = travelIn(onlyTyped, B.ROOT_TAB); B.markTypedByHand(r, "guys"); r.guys_auto = false; r.guys = "3"; B.markTypedByHand(r, "days"); r.days = "5"; }
const onlyTypedTo = switchTo(onlyTyped, "epoxy");
out.copyReleased = { epoxy: factsIn(onlyTypedTo, "Epoxy"), epoxyMarks: marksIn(onlyTypedTo, "Epoxy"), root: factsIn(onlyTypedTo, B.ROOT_TAB), rootMarks: marksIn(onlyTypedTo, B.ROOT_TAB),
  aliased: travelIn(onlyTypedTo, "Epoxy") === travelIn(onlyTypedTo, B.ROOT_TAB), drive: drive$(onlyTypedTo) };
// (v) THE CALLER'S NAME FOR THE OLD CARRIER BEATS LOOKING FOR IT. An Epoxy job (the Polish root is off and holds its own blank Travel Labor row, first in the
//     order) whose Epoxy row was typed 3 x 5, switched to Gyp: looked for, the first section that is not the carrier and holds a row is the ROOT, and its blank
//     row would be carried; named, it is Epoxy's typed row that goes with the job's drive.
const GYP_SHEET = 'Gyp (USG 1-8")';
const toGyp = typedEpoxy();
const toGypNext = B.sectionsForJob(toGyp, "gyp", { rules: [] });
B.followDistance(toGypNext, "Epoxy");
const toGypLooked = B.sectionsForJob(typedEpoxy(), "gyp", { rules: [] });
B.followDistance(toGypLooked);
out.namedBeatsLooked = { carrier: B.travelCarrier(toGypNext), named: { gyp: factsIn(toGypNext, GYP_SHEET), gypMarks: marksIn(toGypNext, GYP_SHEET), epoxy: factsIn(toGypNext, "Epoxy"),
  rootRows: countIn(toGypNext, B.ROOT_TAB) }, looked: { gyp: factsIn(toGypLooked, GYP_SHEET), epoxy: factsIn(toGypLooked, "Epoxy") } };
// (vi) A GYP CARRIER IS NEVER FILLED, NOT EVEN BY A ROW THAT ARRIVES FILLED: Epoxy (filled) to Gyp gives Gyp an empty row (its drive is typed), and Epoxy's goes
//      back too. What the estimator typed does go to Gyp.
const eg = switchSeeded(epoxyJob(), "gyp");
out.gypNeverFilled = { gyp: travelIn(eg, GYP_SHEET) ? factsIn(eg, GYP_SHEET) : null, epoxy: factsIn(eg, "Epoxy"), drive: drive$(eg), carrier: B.travelCarrier(eg) };
const egTyped = switchSeeded(typedEpoxy(), "gyp");
out.gypTypedFollows = { gyp: factsIn(egTyped, GYP_SHEET), gypMarks: marksIn(egTyped, GYP_SHEET), epoxy: factsIn(egTyped, "Epoxy") };
// ...also when the Gyp section is new and has no Travel Labor row at all, so the old carrier's row is CARRIED to it (and so arrives filled): it is emptied there.
const egCarried = switchTo(epoxyJob(), "gyp");
out.gypCarriedUnfilled = { gyp: factsIn(egCarried, GYP_SHEET), gypKeys: travelIn(egCarried, GYP_SHEET) ? Object.keys(travelIn(egCarried, GYP_SHEET)).sort() : null, drive: drive$(egCarried) };
// ...and a section that holds ONLY its Travel Labor row hands the estimator's over like any other (no section is ever left with an empty labor list).
const lone = typedEpoxy();
lone.tabs.Epoxy.labor = lone.tabs.Epoxy.labor.filter((r) => r.id === "travel");
const loneTo = switchTo(lone, "combo");
out.ownedFromLoneRow = { root: factsIn(loneTo, B.ROOT_TAB), epoxy: factsIn(loneTo, "Epoxy"), epoxyRows: (loneTo.tabs.Epoxy.labor || []).length, drive: drive$(loneTo) };
// (vii) NEVER THROWS: a name for a section the model does not have, and a bid whose sections cannot be read, have nothing to carry and are settled as far
//       as they can be.
const nameless = comboJob(); let namelessThrew = null;
try { B.followDistance(nameless, "NoSuchSheet"); } catch (e) { namelessThrew = String(e); }
const broken = comboJob(); broken.tabs = { Epoxy: { layout: "polish", kind: "base" } }; let brokenThrew = null;
try { B.followDistance(broken, "Epoxy"); B.followDistance(broken); } catch (e) { brokenThrew = String(e); }
out.followNeverThrows = { namelessThrew: namelessThrew, brokenThrew: brokenThrew, namelessRowKept: !!travelIn(nameless, B.ROOT_TAB) };
// (viii) A CARRIER KEPT STILL SETTLES THE GUYS AND THE OLD ROWS: a Combo (Polish 4 guys, Epoxy 6) made Polish keeps the root as the carrier; its guys follow the
//        crew of the bid as it is now (4, not the Combo's 6), and Epoxy, off now, gives back anything the distance filled there.
const kc = combo(4, 6); ask(kc, 190);
const kcBefore = facts(kc);
const kcNext = B.sectionsForJob(kc, "polish", { rules: [] });
B.followDistance(kcNext, "Polish");
out.carrierKept = { before: kcBefore, after: facts(kcNext), crew: B.crewSize(kcNext), carrier: B.travelCarrier(kcNext), epoxyRows: countIn(kcNext, "Epoxy"),
  drive: drive$(kcNext) };
// ...and a carrier kept fills nothing: a far bid saved with the root's Travel Labor blank stays blank through a switch that keeps it.
const kb = combo(4, 4); kb.distance = { miles: 190, source: "google", key: "k" }; kb.conditions.local = false;
const kbNext = B.sectionsForJob(kb, "polish", { rules: [] });
B.followDistance(kbNext, "Polish");
out.carrierKeptFillsNothing = facts(kbNext);
// (ix) THE FOURTH HAND OF AN OPTION'S OWN CREW: Remove existing joint filler adds a hand on the option's joint-filler line, as it does for the job's crew.
const oh = newBid();
row(oh, "polishing").guys = "3"; row(oh, "polishing").days = "5"; row(oh, "jointfill").guys = "3"; row(oh, "jointfill").days = "2";
Object.assign(oh.conditions, { joint_filler: true, remove_existing_jf: true });
out.optionHand = { withHand: later("ownCrewSize")(oh, oh.labor), noConditions: later("ownCrewSize")({}, oh.labor), noModel: later("ownCrewSize")(null, oh.labor) };

// (x) A COPY OF THE CARRIER'S SHEET carries the row the carrier had, the estimator's typed 3 x 5 included (it is priced apart, as an option). Made a base beside the
//     carrier it would charge the drive a second time, so a row that REPEATS the carrier's exactly is given back when its section is a base that does not carry the
//     travel; one that says something else (typed 2 x 4) is theirs and stays.
const copyTyped = (typeGuys, typeDays) => {
  const m = crewed(newBid()); ask(m, 190);
  typeIn(m, "guys", "3"); typeIn(m, "days", "5");
  const made = B.copySection(m, "Polish", { state: {} });
  const n = made.model;
  if (typeGuys) { const r = travelIn(n, made.id); r.guys = typeGuys; r.days = typeDays; }
  n.tabs[made.id].kind = "base";
  B.takeBackStrayTravel(n);
  return { id: made.id, root: factsIn(n, B.ROOT_TAB), copy: factsIn(n, made.id), copyMarks: marksIn(n, made.id), drive: drive$(n), kinds: tabsOf(n) };
};
out.copyRepeat = { same: copyTyped(), different: copyTyped("2", "4") };

// 15. AN OPTION IS PRICED APART, FOR ITS OWN CREW (2026-10-20 audit): a copy of the carrier made as an option carries its own Travel Labor row,
//     and its guys follow the option's OWN labor lines and not the base crew the job's one drive is charged for.
const oc = crewed(newBid()); ask(oc, 190);
const madeCopy = B.copySection(oc, "Polish", { state: {} });
const ocm = madeCopy.model;
row(sectionOf(ocm, madeCopy.id), "polishing").guys = "6";
B.syncAutoGuys(ocm);
const copyRow = travelIn(ocm, madeCopy.id);
out.optionCrew = { copy: facts(ocm, copyRow), root: facts(ocm), baseCrew: B.crewSize(ocm), ownCrew: later("ownCrewSize")(ocm, sectionOf(ocm, madeCopy.id).labor),
  noModel: later("ownCrewSize")(null, []), copyKind: sectionOf(ocm, madeCopy.id).kind };
// ...and the words: an option's guys are the lines of its own section ("above"), a Combo's carrier reads the base sheets'.
const cc = combo(3, 4); ask(cc, 190);
const ccCopy = B.copySection(cc, "Polish", { state: {} });
row(sectionOf(ccCopy.model, ccCopy.id), "polishing").guys = "6"; B.syncAutoGuys(ccCopy.model);
const ccRow = travelIn(ccCopy.model, ccCopy.id);
out.optionWords = { own: B.driveHoursSentence(ccCopy.model, ccRow, true), base: B.driveHoursSentence(ccCopy.model, ccRow, false),
  ownHint: B.travelGuysHint(ccCopy.model, ccRow, sectionOf(ccCopy.model, ccCopy.id).labor, true),
  baseHint: B.travelGuysHint(ccCopy.model, ccRow, sectionOf(ccCopy.model, ccCopy.id).labor, false),
  ownNote: B.driveHoursNote(ccCopy.model, ccRow, sectionOf(ccCopy.model, ccCopy.id).labor, true),
  guys: ccRow.guys, jobCrew: B.crewSize(ccCopy.model) };

// 16. THE NOTES SAY WHAT THE GUYS ARE (2026-10-20 audit). A typed count is GUYS, one round trip each ("2 guys (typed)"), never man-days; the hint
//     under the box says so and never quotes the man-days beside it; a cleared Guys box is EMPTY and says that, never "the guys are typed".
const nTyped = crewed(newBid()); ask(nTyped, 190); typeIn(nTyped, "guys", "2");
out.notesTyped = { note: B.driveHoursNote(nTyped, trvOf(nTyped), nTyped.labor), hint: B.travelGuysHint(nTyped, trvOf(nTyped), nTyped.labor),
  how: lineOf(nTyped, "Travel Labor"), howText: B.travelHow(nTyped).text };
const nCleared = crewed(newBid()); ask(nCleared, 190); typeIn(nCleared, "guys", "");
out.notesCleared = { note: B.driveHoursNote(nCleared, trvOf(nCleared), nCleared.labor), hint: B.travelGuysHint(nCleared, trvOf(nCleared), nCleared.labor),
  how: lineOf(nCleared, "Travel Labor") };
// the hint under every other kind of Guys box: the crew's size, the older man-days auto, a new bid's empty row, and another hours line
const nNew = crewed(newBid());
const nOld = crewed(newBid()); Object.assign(trvOf(nOld), { guys_auto: true, guys: "" }); B.syncAutoGuys(nOld);
out.hints = {
  crew: B.travelGuysHint(w, trvOf(w), w.labor), legacyAuto: B.travelGuysHint(nOld, trvOf(nOld), nOld.labor),
  emptyNewBid: B.travelGuysHint(nNew, trvOf(nNew), nNew.labor),
  otherHoursLine: B.travelGuysHint(nNew, { id: "night", label: "Night shift", guys: "5", days: "3", rate: RATE, unit: "hours" }, nNew.labor),
  noRow: B.travelGuysHint(nNew, null, nNew.labor),
};
// the words on a leftover row: an empty one says leave it empty, a typed one says it was left as typed and what to do about it
out.strayWords = { empty: later("strayTravelNote")("Polish", { guys: "", days: "" }), typed: later("strayTravelNote")("Copy1", { guys: "3", days: "5" }),
  hoursOnly: later("strayTravelNote")("Polish", { guys: "", days: "5" }), noRow: later("strayTravelNote")("Polish", null),
  // ...and what the third audit found said "typed" over figures nobody typed: the drive the distance filled that a bid saved earlier still holds, and a
  // row that is switched off (it adds nothing, so it must not say it does)
  filled: later("strayTravelNote")("Polish", { guys: 4, days: 6.5, guys_auto: true, guys_follow: "crew", hours_seed: 6.5 }),
  filledOld: later("strayTravelNote")("Polish", { guys: 16.5, days: 5, guys_auto: true, hours_seed: 5 }),
  off: later("strayTravelNote")("Polish", { guys: "3", days: "5", enabled: false }), offEmpty: later("strayTravelNote")("Polish", { guys: "", days: "", enabled: false }) };
out.autoFilled = {
  crewRow: later("travelRowIsAutoFilled")({ guys: 4, days: 6.5, guys_auto: true, guys_follow: "crew", hours_seed: 6.5 }),
  crewBlankHours: later("travelRowIsAutoFilled")({ guys: 4, days: "", guys_auto: true, guys_follow: "crew", hours_seed: "" }),
  legacyWithToolHours: later("travelRowIsAutoFilled")({ guys: 16.5, days: 5, guys_auto: true, hours_seed: 5 }),
  legacyBlank: later("travelRowIsAutoFilled")({ guys: 16.5, days: "", guys_auto: true, hours_seed: "" }),
  empty: later("travelRowIsAutoFilled")({ guys: "", days: "", guys_auto: false }),
  typedGuysMarked: later("travelRowIsAutoFilled")({ guys: "3", days: 6.5, guys_auto: false, guys_typed: true, hours_seed: 6.5 }),
  typedGuysNoMarker: later("travelRowIsAutoFilled")({ guys: "3", days: 6.5, guys_auto: false, hours_seed: 6.5 }),
  clearedGuys: later("travelRowIsAutoFilled")({ guys: "", days: 6.5, guys_auto: false, guys_typed: true, hours_seed: 6.5 }),
  typedHoursMarked: later("travelRowIsAutoFilled")({ guys: 4, days: "5", guys_auto: true, guys_follow: "crew", hours_seed: 6.5, hours_typed: true }),
  clearedHoursMarked: later("travelRowIsAutoFilled")({ guys: 4, days: "", guys_auto: true, guys_follow: "crew", hours_seed: 6.5, hours_typed: true }),
  typedHoursNoMarker: later("travelRowIsAutoFilled")({ guys: 4, days: "5", guys_auto: true, guys_follow: "crew", hours_seed: 6.5 }),
  noRow: later("travelRowIsAutoFilled")(null),
};
// ...and the same rows asked the other way: whose row is it? The estimator's when a box was typed in or cleared, hours were typed over the tool's, or the row is
// switched off; a blank row and one the distance filled are nobody's.
out.autoFilled.estimators = {
  crewRow: later("travelRowIsTheEstimators")({ guys: 4, days: 6.5, guys_auto: true, guys_follow: "crew", hours_seed: 6.5 }),
  crewBlankHours: later("travelRowIsTheEstimators")({ guys: 4, days: "", guys_auto: true, guys_follow: "crew", hours_seed: "" }),
  legacyWithToolHours: later("travelRowIsTheEstimators")({ guys: 16.5, days: 5, guys_auto: true, hours_seed: 5 }),
  legacyBlank: later("travelRowIsTheEstimators")({ guys: 16.5, days: "", guys_auto: true, hours_seed: "" }),
  empty: later("travelRowIsTheEstimators")({ guys: "", days: "", guys_auto: false }),
  typedGuysMarked: later("travelRowIsTheEstimators")({ guys: "3", days: 6.5, guys_auto: false, guys_typed: true, hours_seed: 6.5 }),
  typedGuysNoMarker: later("travelRowIsTheEstimators")({ guys: "3", days: 6.5, guys_auto: false, hours_seed: 6.5 }),
  clearedGuys: later("travelRowIsTheEstimators")({ guys: "", days: 6.5, guys_auto: false, guys_typed: true, hours_seed: 6.5 }),
  typedHoursMarked: later("travelRowIsTheEstimators")({ guys: 4, days: "5", guys_auto: true, guys_follow: "crew", hours_seed: 6.5, hours_typed: true }),
  clearedHoursMarked: later("travelRowIsTheEstimators")({ guys: 4, days: "", guys_auto: true, guys_follow: "crew", hours_seed: 6.5, hours_typed: true }),
  typedHoursNoMarker: later("travelRowIsTheEstimators")({ guys: 4, days: "5", guys_auto: true, guys_follow: "crew", hours_seed: 6.5 }),
  off: later("travelRowIsTheEstimators")({ guys: 4, days: 6.5, guys_auto: true, guys_follow: "crew", hours_seed: 6.5, enabled: false }),
  offEmpty: later("travelRowIsTheEstimators")({ guys: "", days: "", guys_auto: false, enabled: false }),
  noRow: later("travelRowIsTheEstimators")(null),
};

console.log(JSON.stringify(out));
