"use strict";
/* Runs the REAL bid-model.js: THE DISTANCE FILLS TRAVEL LABOR on a job 70 miles or more out (Hanz, 2026-10-20; asked how,
 * he chose "Every work day (Kyle's sheet math)"). The hours are one round trip from the Olathe office at 60 mph, to the
 * half hour; the guys are the crew's man-days (guys_auto on); a typed figure always wins; under 70 miles, or with the miles
 * cleared, only the figure the tool wrote goes back to empty.
 *
 * Every answer is asked of the model the way the page asks it: applyDistance / clearDistance on the WHOLE model, then
 * B.syncAutoGuys, which changed() runs after every answer. `wichitaBare` is the one case that leaves the sync out, to
 * show the answer fills the guys by itself. This file replaced the harness that pinned "a distance answer fills NO hours"
 * (2026-10-12): each of its cases is here again, under the new rule.
 *
 * Usage: node travel-hours-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const B = require(path.join(path.resolve(process.argv[2]), "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
const trvOf = (m) => m.labor.filter((r) => r.id === "travel")[0];
function ask(m, miles) { B.applyDistance(m, { miles: miles, source: "typed", key: "" }); B.syncAutoGuys(m); return m; }
function clear(m) { B.clearDistance(m); B.syncAutoGuys(m); return m; }
function facts(m, row) {
  const r = row || trvOf(m);
  return { hours: r.days, seed: r.hours_seed === undefined ? null : r.hours_seed, auto: !!r.guys_auto, guys: r.guys,
           cost: B.laborCost(r), on: B.rowOn(r) };
}

// A NEW bid, made the way the page makes it: the library's labor lines seeded onto a bid nobody has saved, every quantity
// emptied (the Travel row opens with no guys, no hours, off auto and with no marker). The crew is then typed as text.
const LIB = [{ id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, favorite: true, default_on: true }];
const seedCtx = (extra) => Object.assign({ saved: undefined, laborRows: B.withCrewFallback(clone(LIB)), laborRate: 33,
  travelRates: null, feesDefault: null, calcRows: null, conditionRows: null, cellValues: {}, split: false,
  asms: [], items: [], reserved: [], sf: {} }, extra || {});
const newBid = () => B.seedNewSections(B.migrateModel(undefined), seedCtx());
/** Polishing 4 guys for 12 days and nothing else on the crew: 48 man-days. */
function crewed(m) {
  const p = m.labor.filter((r) => r.id === "polishing")[0];
  p.guys = "4"; p.days = "12";
  return m;
}
const RATE = 33;

const out = {};
out.newRow = clone(trvOf(newBid()));

// 1. WICHITA: 190 miles on a new bid with the crew typed. 380 miles round trip at 60 mph is 6.33 hours, to the half hour 6.5;
//    the guys are the 48 man-days; 48 x 6.5 x $33 = $10,296. The three travel lines come on, and the line is on, not gray.
const w = crewed(newBid()); ask(w, 190);
out.wichita = Object.assign(facts(w), {
  manDays: B.travelManDays(w.labor), expected: 48 * 6.5 * RATE, rate: trvOf(w).rate, local: w.conditions.local,
  lodging: w.travel.lodging.enabled, perDiem: w.travel.per_diem.enabled, source: B.driveHoursSource(w, trvOf(w)),
  words: B.driveHoursSentence(B.driveHoursSource(w, trvOf(w))), note: B.driveHoursNote(w, trvOf(w), w.labor),
  how: B.travelHow(w).lines[0] });
// ...the answer alone, without changed()'s sync after it: it fills the guys itself.
const wb = crewed(newBid()); B.applyDistance(wb, { miles: 190, source: "typed", key: "" });
out.wichitaBare = facts(wb);
// ...and the shipped model's own Travel row (marker "", on auto) takes it just the same.
const sh = B.freshModel();
sh.labor = [{ id: "polishing", label: "Polishing", guys: 4, days: 12, rate: RATE }, trvOf(sh)];
ask(sh, 190);
out.shippedRow = facts(sh);
// ...no crew yet: the guys follow the man-days, so there are none, and the line prices nothing until there are.
const nc = newBid(); ask(nc, 190);
out.noCrewYet = Object.assign(facts(nc), { note: B.driveHoursNote(nc, trvOf(nc), nc.labor), how: B.travelHow(nc).lines[0] });
// ...and the crew typed AFTER the answer moves the guys with it, as the page's changed() does.
crewed(nc); B.syncAutoGuys(nc);
out.crewAfter = facts(nc);

// 2. A TYPED FIGURE ALWAYS WINS. Hours typed over the 6.5 (text, as the box hands it over) survive a second answer.
const t = crewed(newBid()); ask(t, 190);
trvOf(t).days = "4";
ask(t, 300);
out.typedHoursSurvive = Object.assign(facts(t), { source: B.driveHoursSource(t, trvOf(t)), note: B.driveHoursNote(t, trvOf(t), t.labor),
  how: B.travelHow(t).lines[0] });
// ...even when what was typed spells the very digits the tool wrote.
const td = crewed(newBid()); ask(td, 190);
trvOf(td).days = "6.5";
ask(td, 300);
out.typedSameDigits = facts(td);
// ...guys the same: typed guys stay, the hours are filled.
const tg = crewed(newBid()); trvOf(tg).guys = "2";
ask(tg, 190);
out.typedGuysSurvive = facts(tg);
// ...typed 0 hours is an answer too (it prices nothing), not a blank to fill.
const tz = crewed(newBid()); trvOf(tz).days = "0";
ask(tz, 190);
out.typedZeroStays = facts(tz);

// 3. AN UNTOUCHED FIGURE FOLLOWS THE NEXT ANSWER: 190 miles is 6.5 hours, 300 miles is 10.
const u = crewed(newBid()); ask(u, 190); ask(u, 300);
out.untouchedMoves = facts(u);
// ...every answer in turn on one bid: 190, 300, exactly 70 (2.33 hours, to the half 2.5), 69.9 (local), 120.4 (4.01, 4.5).
const seq = crewed(newBid());
out.sequence = [190, 300, 70, 69.9, 120.4].map((mi) => { ask(seq, mi); return [mi, trvOf(seq).days, trvOf(seq).hours_seed, seq.conditions.local]; });

// 4. GOING LOCAL takes the tool's own hours back and leaves typed ones. The line grays again (hours blank, local).
const lc = crewed(newBid()); ask(lc, 190); ask(lc, 20);
out.goingLocal = Object.assign(facts(lc), { local: lc.conditions.local, note: B.driveHoursNote(lc, trvOf(lc), lc.labor) });
const lk = crewed(newBid()); ask(lk, 190); trvOf(lk).days = "4"; ask(lk, 20);
out.localKeepsTyped = Object.assign(facts(lk), { local: lk.conditions.local });
// ...and far again fills it again.
ask(lc, 190);
out.backToFar = facts(lc);
// CLEARING the miles is the same: the tool's hours go, typed ones stay.
const cl = crewed(newBid()); ask(cl, 190); clear(cl);
out.cleared = Object.assign(facts(cl), { local: cl.conditions.local, distance: cl.distance === undefined ? null : cl.distance });
const ck = crewed(newBid()); ask(ck, 190); trvOf(ck).days = "4"; clear(ck);
out.clearedKeepsTyped = facts(ck);

// 5. A BID SAVED BEFORE. A row from 2026-10-12 and after (nothing typed, off auto) is filled when an answer is applied in a
//    session; a pre-2026-10-12 row on auto with hours typed keeps them; a row carrying the old marker follows the answer.
const old1 = crewed(newBid());
trvOf(old1).days = 5; trvOf(old1).guys_auto = true; trvOf(old1).guys = 16.5;                 // typed hours, a number, no marker
ask(old1, 300);
out.savedTypedHoursStay = facts(old1);
const old2 = crewed(newBid());
Object.assign(trvOf(old2), { days: 5, hours_seed: 5, guys_auto: true, guys: 16.5 });         // the 2026-10-06 era: the tool's own 5
ask(old2, 300);
out.savedMarkerFollows = facts(old2);
// OPENING moves nothing: migrate and sync a saved far job with Travel Labor blank, and the row is what was saved.
const saved = crewed(newBid());
saved.distance = { miles: 190, source: "google", key: "k" }; saved.conditions.local = false;
const savedRow = JSON.stringify(trvOf(saved));
const reopened = B.migrateModel(clone(saved)); B.syncAutoGuys(reopened);
out.openMovesNothing = { same: JSON.stringify(trvOf(reopened)) === savedRow, row: trvOf(reopened) };

// 6. WHICH SECTION. The Travel Labor row is the carrier's, with the carrier's own crew.
const EP_LIB = B.withCrewFallback([
  { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, favorite: true, default_on: true },
  { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, favorite: true, default_on: true,
    default_work_types: ["epoxy"] }]);
// an Epoxy job: the Polish root is off and Epoxy carries the travel
const ej = B.seedNewSections(B.activateSection(Object.assign(B.migrateModel(undefined), { kind: "off" }), "Epoxy", "base", {}),
  seedCtx({ laborRows: EP_LIB }));
ej.tabs.Epoxy.labor.filter((r) => r.id === "epoxy-install")[0].guys = "4";
ej.tabs.Epoxy.labor.filter((r) => r.id === "epoxy-install")[0].days = "12";
const epRowBefore = JSON.stringify(ej.labor.filter((r) => r.id === "travel")[0]);
ask(ej, 190);
const epTravel = ej.tabs.Epoxy.labor.filter((r) => r.id === "travel")[0];
out.epoxyJob = Object.assign(facts(ej, epTravel), { manDays: B.travelManDays(ej.tabs.Epoxy.labor),
  rootRowUntouched: JSON.stringify(ej.labor.filter((r) => r.id === "travel")[0]) === epRowBefore, carrier: B.travelCarrier(ej) });
// a combo job (two bases): the first base, the Polish root, carries the travel, so ITS crew is the man-days (3 x 5, not Epoxy's 48)
const cj = B.seedNewSections(B.activateSection(B.migrateModel(undefined), "Epoxy", "base", {}), seedCtx({ laborRows: EP_LIB }));
cj.tabs.Epoxy.labor.filter((r) => r.id === "epoxy-install")[0].guys = "4";
cj.tabs.Epoxy.labor.filter((r) => r.id === "epoxy-install")[0].days = "12";
const cp = cj.labor.filter((r) => r.id === "polishing")[0]; cp.guys = "3"; cp.days = "5";
ask(cj, 190);
out.comboJob = Object.assign(facts(cj), { manDays: B.travelManDays(cj.labor), carrier: B.travelCarrier(cj),
  epoxyHasTravel: cj.tabs.Epoxy.labor.some((r) => r.id === "travel") });
// a Gyp job prices its crew by the hour, so there are no man-days to follow: left exactly as it was
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

// 7. THE OTHER TWO LINES ARE AS THEY WERE: switched on by the answer, a hand flip never moved.
const ln = crewed(newBid()); ln.travel.lodging.hand = true; ln.travel.lodging.enabled = false;
ask(ln, 190);
out.lines = { lodging: ln.travel.lodging.enabled, perDiem: ln.travel.per_diem.enabled, lodgingQty: ln.travel.lodging.qty,
  perDiemQty: ln.travel.per_diem.qty, lodgingAuto: ln.travel.lodging.qty_auto, perDiemAuto: ln.travel.per_diem.qty_auto };

// 8. WORDS. A figure the distance wrote says the trip; one it wrote for a distance that has gone says so; a typed one says typed.
const wd = crewed(newBid()); ask(wd, 190);
const stale = crewed(newBid()); Object.assign(trvOf(stale), { days: 5, hours_seed: 5, guys_auto: true, guys: 48 });
stale.distance = { miles: 190, source: "typed", key: "" };             // 190 miles would give 6.5, not the 5 it holds
const gone = crewed(newBid()); Object.assign(trvOf(gone), { days: 5, hours_seed: 5, guys_auto: true, guys: 48 });
const frac = crewed(newBid()); ask(frac, 120.4);
out.words = {
  tool: B.travelHow(wd).lines[0], staleSource: B.driveHoursSource(stale, trvOf(stale)), stale: B.travelHow(stale).lines[0],
  goneSource: B.driveHoursSource(gone, trvOf(gone)), gone: B.travelHow(gone).lines[0],
  areTools: [B.driveHoursAreTools(trvOf(wd)), B.driveHoursAreTools({ days: "6.5", hours_seed: 6.5 }),
             B.driveHoursAreTools({ days: 6.5, hours_seed: "" }), B.driveHoursAreTools({ days: 6.5 }), B.driveHoursAreTools(null)],
  fractional: B.driveHoursSentence(B.driveHoursSource(frac, trvOf(frac))),
};

// 9. BAD INPUT. An answer with no usable miles records nothing and changes nothing; no model is no model.
const bad = crewed(newBid()); const badBefore = JSON.stringify(bad);
B.applyDistance(bad, { miles: "abc", source: "typed", key: "" });
B.applyDistance(bad, null);
out.badInput = { unchanged: JSON.stringify(bad) === badBefore, nullModel: B.applyDistance(null, { miles: 190 }),
  clearNull: String(B.clearDistance(undefined)) };

// 10. PRICED: no hours is $0 until the figure is there, and the cost is guys x hours x the line's own rate.
const pr = crewed(newBid());
out.pricedBefore = B.laborCost(trvOf(pr));
ask(pr, 190);
out.pricedAfter = B.laborCost(trvOf(pr));
trvOf(pr).rate = 40;
out.pricedAtOwnRate = B.laborCost(trvOf(pr));

console.log(JSON.stringify(out));
