"use strict";
/* THE FIFTH AUDIT OF "A FAR DISTANCE FILLS TRAVEL LABOR" (2026-10-20, of b14bc98), and Hanz's decision that came with it, run on the REAL estimate page: js/polish-estimate.js,
 * whole, booted the way polish-estimate-harness.js boots it, with the REAL js/bid-model.js beneath it. Every fact below is read off the page after it ran: the model it
 * held, the panels it drew, what it saved. Nothing is a source assertion. test_polish_travel_round5.py holds each one to its numbers and breaks a copy of the page or the model
 * one line at a time to prove each fact can change.
 *
 *   A  A BASE THE SHEETS PANEL DEMOTED KEEPS A TRAVEL LABOR ROW OF ITS OWN, so the bid prices the same in the session and after a reload. Moving the row to the new carrier left the
 *      demoted sheet with none until the draft was reopened (migrateModel then gives a root a blank one, which the next answer fills): far Polish 4 x 12, 190 miles, Epoxy added
 *      and made the base, the miles typed as 300 and then 299, was $783 apart. `demotion` runs the audit's script and the same on a Combo, in the session and reloaded.
 *   B  A SECTION WHOSE LABOR IS NOT A LIST CAN BE PUT ON SHOW: `badShapes` opens a Combo whose Epoxy labor (and takeoff) is a string, a number, an object, a boolean or null, as each job
 *      type, and puts EVERY section on show at every step; before, the first panel threw (`M.labor.forEach is not a function`).
 *   C  The unreadable-tabs guard of the answers: `unreadableTabs` (a section with no layout).
 *   D  NIGHTS AND PER DIEM DAYS FILL ON A FAR JOB (Hanz: "Fill them automatically"): `nights` (Wichita, 4 guys x 12 days: 48 nights x $70 = $3,360 and 48 days x $45 = $2,160), the figure
 *      following a labor change, a typed or cleared box staying theirs, a local answer taking the untouched figure back, a saved bid that never moves on open, a carrier that moves under a
 *      far distance on file, an option that counts its own, and the words on the Labor step and the Review.
 *   E  `addTravel`: the Travel Labor card's x, and the control that brings the line back.
 *   F  `notes`: the note under an option names the sheet by its name on screen, not by its tab id.
 *   G  `patchNote`: the Epoxy and Seal patch notes move with the takeoff.
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason; the mutation runs in the test count a section error as a
 * failure of the mutation, never as the mutation being noticed.
 *
 * Usage: node travel-round5-harness.js <frontend-dir>   ->  one line of JSON
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
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-round5-harness.js");
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

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const LOST = { ok: false, miles: null, reason: "not_found" };
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const epoxyDraft = () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const comboDraft = () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const polishDraft = () => draftOf("polish", { polish_sf: 5000 });

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
const lineFacts = (l) => (l ? { on: !!l.enabled, qty: l.qty, auto: l.qty_auto !== false, follow: l.qty_follow === undefined ? null : l.qty_follow, typed: l.qty_typed === true,
  hand: l.hand === true } : null);

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

/** The saved draft reopened on a page of its own, on the Labor step. The lookup would say 300 miles, which a saved bid never asks for. */
async function reopen(saved, extra) {
  const b = await open(clone(saved), Object.assign({ distance: { ok: true, miles: 300, reason: "" } }, extra || {}));
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

/** Every price the page holds: the root sheet's own bid, each other section's, and what a save writes (the lump sum). A save is forced, so run it after everything else is read. */
function prices(b) {
  const m = b.api.root();
  const bids = b.api.sectionBids();
  b.api.saveSoon();
  b.clock.fire();
  return { lump: lumpOf(b.store.blob), root: b.api.bid().total, sections: Object.fromEntries(Object.keys(bids).map((k) => [k, bids[k].total])),
    miles: m.distance ? m.distance.miles : null };
}

/** Every section's Travel Labor row, by sheet. */
function driveRows(b) {
  const m = b.api.root();
  return Object.fromEntries(B.sectionsOf(m).map((e) => [e.tab + ":" + e.kind, rowFacts(rowIn(e.section))]));
}

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

async function addSheet(b, sheet) {
  b.api.go(1);
  if (has(b, '[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]');
  P.clickOn(b, '[data-sh-act="add"][data-sh-sheet="' + sheet + '"]');
  await settle();
  b.clock.fire();
}

async function makeBase(b, value) {
  b.doc.fire("change", { target: P.need(b, '[data-sh-base="' + value + '"]') });
  P.clickOn(b, '[data-sh-act="base-yes"]');
  await settle();
  b.clock.fire();
}

async function main() {
  // ═══ A. A BASE THE SHEETS PANEL DEMOTED KEEPS A TRAVEL LABOR ROW OF ITS OWN: the session and a reload price the same ═══════════════════════════════════
  // The audit's script: a far Polish bid (4 x 12, 190 miles), an Epoxy sheet added (a fresh sheet holds no Travel Labor row: only the carrier has one), Epoxy made the base
  // (Polish is an option now), the miles typed as 300 and then 299 (the drive is 10 hours at both). Run in ONE session, and again with a plain reopen of the saved draft between the
  // base change and the miles. The two must agree at every step.
  const demotion = async (start) => {
    const s = await newBid(start.draft, start.crew);
    const a = await reopen(s.saved, { distance: { ok: true, miles: 300, reason: "" } });
    if (start.add) {
      await addSheet(a, start.add);
      a.api.show(start.add);
      a.api.go(1);
      typeCrew(a, start.add, start.addRow, "4", "12");
      a.clock.fire();
    }
    await makeBase(a, start.pick);
    const afterPick = { carrier: B.travelCarrier(a.api.root()), kinds: B.sectionsOf(a.api.root()).map((e) => [e.tab, e.kind]), drive: driveRows(a) };
    const saved = clone(a.store.blob);
    // THE SESSION: the miles are typed on the page that made the change.
    const session = { start: Object.assign({ rows: driveRows(a) }, prices(a)) };
    await typeMiles(a, "300"); session.at300 = Object.assign({ rows: driveRows(a) }, prices(a));
    await typeMiles(a, "299"); session.at299 = Object.assign({ rows: driveRows(a) }, prices(a));
    // THE RELOAD: the draft as it was saved after the change, opened again plain, then the same miles.
    const r = await reopen(saved, { distance: { ok: true, miles: 300, reason: "" } });
    const quiet = { armed: r.clock.armed(), saves: r.rec.saves.length, asked: (r.rec.distanceBodies || []).length };
    const reloaded = { start: Object.assign({ rows: driveRows(r) }, prices(r)), quiet: quiet };
    await typeMiles(r, "300"); reloaded.at300 = Object.assign({ rows: driveRows(r) }, prices(r));
    await typeMiles(r, "299"); reloaded.at299 = Object.assign({ rows: driveRows(r) }, prices(r));
    return { afterPick: afterPick, session: session, reloaded: reloaded };
  };
  await section("demotion", async () => ({
    addedSheet: await demotion({ draft: polishDraft(), crew: ["Polish", "polishing", "4", "12"], add: "Epoxy", addRow: "epoxy-install", pick: "Epoxy" }),
    combo: await demotion({ draft: comboDraft(), crew: ["Polish", "polishing", "4", "12"], pick: "Epoxy" }),
  }));

  // ═══ B. A SECTION WHOSE LABOR OR TAKEOFF IS NOT A LIST CAN BE PUT ON SHOW ═════════════════════════════════════════════════════════════════════════════
  await section("badShapes", async () => {
    const combo = await newBid(comboDraft(), ["Polish", "polishing", "4", "12"]);
    const copied = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
    const copyPage = await reopen(copied.saved);
    P.clickOn(copyPage, '[data-sh-act="copy"]');
    await settle();
    copyPage.clock.fire();
    const withCopy = clone(copyPage.store.blob);
    /** Open the bid, then put EVERY section on show and open all three steps of each: what threw, by sheet and step. */
    const walk = async (blob, as) => {
      const res = { opened: false, shown: false, threw: {} };
      let b;
      try {
        b = await reopen(Object.assign(clone(blob), as ? { work_type: as } : {}));
        const main = b.doc.getElementById("main");
        res.opened = true;
        res.shown = !!main && !main.hidden;
      } catch (e) { res.error = String((e && e.message) || e).slice(0, 120); return res; }
      B.sectionsOf(b.api.root()).forEach((e) => {
        [0, 1, 2].forEach((step) => {
          try { b.api.show(e.tab); b.api.go(step); } catch (err) { res.threw[e.tab + "#" + step] = String((err && err.message) || err).slice(0, 80); }
        });
      });
      return res;
    };
    const res = {};
    for (const kv of [["string", "x"], ["number", 5], ["object", {}], ["boolean", true], ["null", null]]) {
      res[kv[0]] = {};
      for (const key of ["labor", "takeoff"]) {
        const cell = {};
        for (const as of ["combo", "polish", "epoxy"]) {
          const blob = clone(combo.saved);
          blob.polish_estimate.tabs.Epoxy[key] = kv[1];
          cell[as] = await walk(blob, as);
        }
        const blob = clone(withCopy);
        blob.polish_estimate.tabs.Copy1[key] = kv[1];
        cell.optionCopy = await walk(blob, "polish");
        res[kv[0]][key] = cell;
      }
    }
    // ...and a bid that is sound comes back byte for byte: reading it as lists changes nothing that is a list.
    res.soundTabs = JSON.stringify(B.migrateModel(clone(combo.saved.polish_estimate)).tabs) === JSON.stringify(combo.saved.polish_estimate.tabs);
    // ...and a saved `tabs` holding something that is not a section at all (a number, null, a string) is carried exactly as it was: only a section is read as lists.
    res.notSections = {};
    for (const kv of [["number", 5], ["null", null], ["string", "x"]]) {
      const blob = clone(combo.saved.polish_estimate);
      blob.tabs = Object.assign({}, blob.tabs, { Strange: kv[1] });
      try { const m = B.migrateModel(blob); res.notSections[kv[0]] = { threw: null, carried: JSON.stringify(m.tabs.Strange) === JSON.stringify(kv[1]), keys: Object.keys(m.tabs) }; }
      catch (e) { res.notSections[kv[0]] = { threw: String((e && e.message) || e).slice(0, 80) }; }
    }
    // THE PAGE NEVER ASSUMES A LIST EITHER: the rail's status, asked of a section whose labor and takeoff are not lists (put there after the model was read, as a model handed to the page
    // another way would hold them): it answers, and does not throw.
    res.status = {};
    for (const kv of [["string", "x"], ["null", null], ["object", {}]]) {
      const b = await reopen(clone(combo.saved), {});
      b.api.show("Epoxy");
      const sec = b.api.root().tabs.Epoxy;
      sec.labor = kv[1];
      sec.takeoff = kv[1];
      try { res.status[kv[0]] = { answer: b.api.stepStatus() }; } catch (e) { res.status[kv[0]] = { threw: String((e && e.message) || e).slice(0, 80) }; }
    }
    return res;
  });

  // ═══ C. THE ANSWERS READ UNREADABLE TABS AS THEY ALWAYS DID: a section with no layout ════════════════════════════════════════════════════════════════
  await section("unreadableTabs", async () => {
    const make = () => {
      const m = B.freshModel();
      m.labor = [{ id: "polishing", label: "Polishing", guys: 4, days: 12, rate: 33 },
                 { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: false }];
      m.travel = { lodging: { label: "Lodging", enabled: false, qty: "", qty_auto: false, rate: 70 }, per_diem: { label: "Per Diem", enabled: false, qty: "", qty_auto: false, rate: 45 } };
      m.tabs = { Epoxy: { layout: null, kind: "option", profile: "epoxy@1", takeoff: [], labor: [{ id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: false }],
                 contingency: 0, fees: 0, totals: {} } };      // a null `layout`: sectionsOf throws, so the sections cannot be read
      return m;
    };
    const attempt = (fn) => { try { fn(); return null; } catch (e) { return String((e && e.message) || e).slice(0, 100); } };
    const m = make();
    const readable = attempt(() => B.sectionsOf(m));
    const applied = attempt(() => B.applyDistance(m, { miles: 190, source: "typed", key: "" }));
    const far = { miles: m.distance && m.distance.miles, row: rowFacts(rowIn(m)), lodging: lineFacts(m.travel.lodging) };
    const cleared = attempt(() => B.clearDistance(m));
    const after = { distance: m.distance === undefined ? null : m.distance, row: rowFacts(rowIn(m)), lodging: lineFacts(m.travel.lodging) };
    const moved = attempt(() => B.followDistance(make(), "Polish"));
    const added = (() => { const n = make(); return { added: attempt(() => B.addTravelLabor(n, B.freshTravelRow([], 33))), rows: n.labor.length }; })();
    // a model with no travel block at all is cleared without a word, and one with no labor at all takes the line as its first
    const bare = { cleared: attempt(() => B.clearDistance({ conditions: {} })) };
    const noLabor = (() => { const n = B.freshModel(); delete n.labor; return { done: B.addTravelLabor(n, B.freshTravelRow([], 33)), rows: (n.labor || []).length }; })();
    return { unreadable: !!readable, applied: applied, far: far, cleared: cleared, after: after, moved: moved, added: added, bare: bare, noLabor: noLabor };
  });

  // ═══ D. NIGHTS AND PER DIEM DAYS FILL ON A FAR JOB ═══════════════════════════════════════════════════════════════════════════════════════════════════
  const nightsFacts = (b) => {
    const m = b.api.root();
    const car = B.travelCarrier(m);
    const sec = secOf(m, car);
    const costs = B.travelCosts(m.travel, sec.labor, B.travelOpts(m, car));
    return { carrier: car, lodging: lineFacts(m.travel.lodging), perDiem: lineFacts(m.travel.per_diem), costs: costs, drive: rowFacts(rowIn(sec)) };
  };
  const labor = (b) => ({ lodgingBox: boxOf(b, '[data-trv="lodging"][data-k="qty"]'), perDiemBox: boxOf(b, '[data-trv="per_diem"][data-k="qty"]'),
    lodgingHint: textOf(b, '[data-hint-trv="lodging"]'), perDiemHint: textOf(b, '[data-hint-trv="per_diem"]'), how: textOf(b, "[data-trv-how]") });
  await section("nights", async () => {
    const res = {};
    // Wichita, 190 miles, four guys for twelve days, on an Epoxy bid and on a Polish one.
    for (const kv of [["epoxy", epoxyDraft(), ["Epoxy", "epoxy-install", "4", "12"]], ["polish", polishDraft(), ["Polish", "polishing", "4", "12"]]]) {
      const s = await newBid(kv[1], kv[2]);
      const b = s.page;
      b.api.go(1);
      const facts = { saved: nightsFacts(b), labor: labor(b) };
      b.api.go(2);
      await settle();
      facts.review = { lodgingNote: textOf(b, '[data-rv="trv.lodging.note"]'), perDiemNote: textOf(b, '[data-rv="trv.per_diem.note"]'),
        lodgingQty: textOf(b, '[data-rv="trv.lodging.q"]'), perDiemQty: textOf(b, '[data-rv="trv.per_diem.q"]'),
        lodgingTotal: textOf(b, '[data-rv="trv.lodging.tot"]'), perDiemTotal: textOf(b, '[data-rv="trv.per_diem.tot"]') };
      res[kv[0]] = facts;
    }
    // FOLLOWING THE LABOR: the days on the crew line change (12 to 14), then the guys (4 to 5): the nights and the per diem days are the man-days each time.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const b = s.page;
      b.api.go(1);
      typeCrew(b, "Polish", "polishing", "4", "14");
      res.moreDays = { n: nightsFacts(b), l: labor(b), manDays: B.travelManDays(b.api.root().labor) };
      typeCrew(b, "Polish", "polishing", "5", "14");
      res.moreGuys = { n: nightsFacts(b), l: labor(b), manDays: B.travelManDays(b.api.root().labor) };
    }
    // THE ESTIMATOR'S BOX IS THEIRS: nights typed (10), per diem cleared; a later answer (300 miles) and a later labor change leave both alone, and what follows still follows.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const b = s.page;
      b.api.go(1);
      P.typeInto(b, '[data-trv="lodging"][data-k="qty"]', "10");
      P.typeInto(b, '[data-trv="per_diem"][data-k="qty"]', "");
      res.typedCleared = { n: nightsFacts(b), l: labor(b) };
      await typeMiles(b, "300");
      res.typedClearedAfter300 = { n: nightsFacts(b), l: labor(b) };
      typeCrew(b, "Polish", "polishing", "4", "14");
      res.typedClearedAfterLabor = { n: nightsFacts(b) };
      // ...saved and reopened: the marks are saved with the lines, and a plain reopen moves nothing
      b.clock.fire();
      const r = await reopen(b.store.blob);
      res.typedClearedReopened = { n: nightsFacts(r), armed: r.clock.armed(), saves: r.rec.saves.length };
      await typeMiles(r, "190");
      res.typedClearedReopenedAnswer = { n: nightsFacts(r) };
    }
    // TYPED ON A LOCAL JOB: the Per Diem box is greyed, not disabled, and a line that is NOT on auto takes the keystroke through its own path: it is marked theirs there too (typed 7 and
    // then cleared, so only the mark can tell it from a box nobody touched), and the far answer that comes later fills the Lodging (untouched) and leaves the Per Diem empty.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"], { ok: true, miles: 40, reason: "" });
      const b = s.page;
      b.api.go(1);
      P.typeInto(b, '[data-trv="per_diem"][data-k="qty"]', "7");
      P.typeInto(b, '[data-trv="per_diem"][data-k="qty"]', "");
      const typed = nightsFacts(b);
      await typeMiles(b, "300");
      res.typedLocal = { typed: typed, after: nightsFacts(b), l: labor(b) };
    }
    // A FIGURE TYPED BEFORE THE MARKERS EXISTED (a bid saved since 2026-10-12): off auto, a number in the box, no `qty_typed`. It is theirs all the same, and a far answer leaves it.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const old = clone(s.saved);
      const l = old.polish_estimate.travel.lodging;
      l.qty_auto = false; l.qty = "9"; delete l.qty_follow; delete l.qty_typed;
      const b = await reopen(old);
      await typeMiles(b, "300");
      res.typedNoMarker = { n: nightsFacts(b) };
    }
    // A SAVED BID THAT WAS FILLED keeps following after a reopen (the marker is saved with the line), moves nothing on open, and goes back to empty when the miles are corrected to 50.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const b = await reopen(s.saved);
      const open = { n: nightsFacts(b), armed: b.clock.armed(), saves: b.rec.saves.length, asked: (b.rec.distanceBodies || []).length };
      await typeMiles(b, "50");
      res.reopenedFollowing = { open: open, local: nightsFacts(b) };
    }
    // GOING LOCAL, and the miles cleared: the figure nobody typed goes back to empty, the typed one stays (greyed: the line is off), and a far answer fills the first again.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const b = s.page;
      b.api.go(1);
      P.typeInto(b, '[data-trv="per_diem"][data-k="qty"]', "7");
      await typeMiles(b, "50");
      res.local = { n: nightsFacts(b), l: labor(b), cond: { local: b.api.root().conditions.local } };
      await typeMiles(b, "300");
      res.farAgain = { n: nightsFacts(b), l: labor(b) };
      b.opts.distance = LOST;
      await typeMiles(b, "");
      res.cleared = { n: nightsFacts(b), l: labor(b) };
    }
    // A SAVED BID NEVER MOVES ON OPEN: a bid saved far with Lodging and Per Diem on and their quantities blank (what a new bid held before this) is reopened plain: nothing is filled, saved or
    // asked, and the price is the one it was saved at. The next answer (the miles typed) fills them.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const old = clone(s.saved);
      ["lodging", "per_diem"].forEach((k) => { const l = old.polish_estimate.travel[k]; l.qty_auto = false; l.qty = ""; delete l.qty_follow; delete l.qty_typed; });
      const b = await reopen(old);
      const open = { n: nightsFacts(b), armed: b.clock.armed(), saves: b.rec.saves.length, asked: (b.rec.distanceBodies || []).length };
      const before = prices(b);
      await typeMiles(b, "190");
      res.savedBlank = { open: open, before: before, after: { n: nightsFacts(b), p: prices(b) } };
    }
    // A CARRIER THAT MOVES UNDER A FAR DISTANCE ON FILE (the job type switched in the session): a Polish bid saved far with blank lines, opened as Epoxy, is filled by the new carrier's labor.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const old = clone(s.saved);
      ["lodging", "per_diem"].forEach((k) => { const l = old.polish_estimate.travel[k]; l.qty_auto = false; l.qty = ""; delete l.qty_follow; delete l.qty_typed; });
      const e = await reopen(Object.assign(old, { work_type: "epoxy" }));
      typeCrew(e, "Epoxy", "epoxy-install", "5", "10");
      res.carrierMoved = { n: nightsFacts(e), l: labor(e), manDays: B.travelManDays(secOf(e.api.root(), "Epoxy").labor) };
      // ...and one the estimator typed stays theirs through the same switch
      const t = clone(s.saved);
      B.markTravelQtyTyped(t.polish_estimate.travel.lodging); t.polish_estimate.travel.lodging.qty = "9";
      const e2 = await reopen(Object.assign(t, { work_type: "epoxy" }));
      typeCrew(e2, "Epoxy", "epoxy-install", "5", "10");
      res.carrierMovedTyped = { n: nightsFacts(e2) };
    }
    // THE LOOKUP LANDS WHILE THE LABOR STEP IS ON SHOW (a new bid asks by itself, after the first paint): the boxes show the figure in place, with no rebuild, and the lookup
    // BUTTON answering "local" later takes the figure back and empties the box in place.
    {
      let release;
      const gate = new Promise((r) => { release = r; });
      const b = await open(polishDraft(), { distance: FAR, distanceGate: gate });
      b.api.go(1);
      await settle();
      typeCrew(b, "Polish", "polishing", "4", "12");
      const before = { n: nightsFacts(b), l: labor(b) };
      release();
      await settle();
      const landed = { n: nightsFacts(b), l: labor(b), written: b.doc.querySelector('[data-trv="lodging"][data-k="qty"]').attrs["data-auto"] };
      b.opts.distance = { ok: true, miles: 30, reason: "" };
      P.clickOn(b, "[data-dist-lookup]");
      await settle();
      res.lookupLand = { before: before, landed: landed, local: { n: nightsFacts(b), l: labor(b) } };
    }
    // AN OPTION COUNTS ITS OWN: a far Polish bid copied as an option, the base's lines following the labor: the option's price is what it was (its own nights from its own labor).
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const b = await reopen(s.saved);
      P.clickOn(b, '[data-sh-act="copy"]');
      await settle();
      b.clock.fire();
      const copy = B.sectionsOf(b.api.root()).filter((e) => e.kind === "option")[0].tab;
      const m = b.api.root();
      const own = B.optionTravelCosts(m.travel, secOf(m, copy).labor);
      const sb = b.api.sectionBids();
      res.option = { copy: copy, total: sb[copy].total, travel: sb[copy].travel, own: own.total, ownLines: own, baseTravel: b.api.bid().travel,
        baseLines: B.travelCosts(m.travel, m.labor, B.travelOpts(m, B.ROOT_TAB)).total };
      // typing the base's nights does not move the option's
      b.api.show(B.ROOT_TAB);
      b.api.go(1);
      P.typeInto(b, '[data-trv="lodging"][data-k="qty"]', "3");
      res.option.afterTyped = { total: b.api.sectionBids()[copy].total };
    }
    // THE OLDER AUTO LINE (a bid saved before 2026-10-12) is never converted: no marker, in either direction.
    {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const old = clone(s.saved);
      ["lodging", "per_diem"].forEach((k) => { const l = old.polish_estimate.travel[k]; l.qty_auto = true; l.qty = 48; delete l.qty_follow; delete l.qty_typed; });
      const b = await reopen(old);
      const open = nightsFacts(b);
      await typeMiles(b, "50");
      const local = nightsFacts(b);
      await typeMiles(b, "300");
      res.olderAuto = { open: open, local: local, far: nightsFacts(b) };
    }
    return res;
  });

  // ═══ E. THE TRAVEL LABOR CARD'S x TAKES THE LINE AWAY, AND THE CARD'S ADD BRINGS IT BACK ═════════════════════════════════════════════════════════════════
  await section("addTravel", async () => {
    const run = async (draft, crew, tab, distance) => {
      const s = await newBid(draft, crew, distance);
      const b = s.page;
      b.api.go(1);
      const res = { before: { rows: driveRows(b), button: has(b, "[data-add-travel]"), how: textOf(b, "[data-trv-how]") } };
      const at = idxIn(secOf(b.api.root(), tab), "travel");
      P.clickOn(b, '[data-del-lab="' + at + '"]');
      res.removed = { rows: driveRows(b), button: has(b, "[data-add-travel]"), card: has(b, '[data-lab="' + at + '"][data-k="guys"]') && at >= 0,
        how: textOf(b, "[data-trv-how]"), block: has(b, "[data-trv-none]"), words: /This bid has no Travel Labor line/.test(b.doc.getElementById("panels").innerHTML),
        lump: prices(b).lump };
      // the summary says what is true: Lodging and Per Diem come on (they do), Travel Labor is not claimed
      if (has(b, "[data-add-travel]")) P.clickOn(b, "[data-add-travel]");
      await settle();
      const row = rowIn(secOf(b.api.root(), tab));
      const k = idxIn(secOf(b.api.root(), tab), "travel");
      res.added = { rows: driveRows(b), button: has(b, "[data-add-travel]"), how: textOf(b, "[data-trv-how]"), lump: prices(b).lump,
        guysBox: boxOf(b, '[data-lab="' + k + '"][data-k="guys"]'), hoursBox: boxOf(b, '[data-lab="' + k + '"][data-k="days"]'), rate: row && row.rate, label: row && row.label,
        keys: row ? Object.keys(row).sort() : null };
      // a second press adds nothing: the control is gone, and a stale press is refused by the model
      const again = B.addTravelLabor(b.api.root(), B.freshTravelRow([], 33));
      res.addedAgain = { returned: again, count: (secOf(b.api.root(), tab).labor || []).filter((r) => r.id === "travel").length };
      // saved and reopened: the row is on the draft
      b.clock.fire();
      const r = await reopen(b.store.blob);
      res.reopened = { rows: driveRows(r) };
      return res;
    };
    // a Gyp carrier's drive is typed (the Gyp sheet works its own drive time): the line comes back EMPTY on a far job
    const gyp = await (async () => {
      const gypTab = 'Gyp (USG 1-8")';
      const s = await newBid(draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 }), [gypTab, "gyp-pour", "4", "12"], FAR);
      const b = s.page;
      b.api.go(1);
      const at = idxIn(secOf(b.api.root(), gypTab), "travel");
      P.clickOn(b, '[data-del-lab="' + at + '"]');
      const reads = () => (b.rec.calls || []).filter((c) => /api\/library\/labor$/.test(c.url)).length;
      const before = reads();
      if (has(b, "[data-add-travel]")) { P.clickOn(b, "[data-add-travel]"); P.clickOn(b, "[data-add-travel]"); }
      await settle();
      const row = rowIn(secOf(b.api.root(), gypTab));
      return { carrier: B.travelCarrier(b.api.root()), row: rowFacts(row), count: (secOf(b.api.root(), gypTab).labor || []).filter((r) => r.id === "travel").length, libraryReads: reads() - before };
    })();
    return {
      gypFar: gyp,
      polishFar: await run(polishDraft(), ["Polish", "polishing", "4", "12"], "Polish", FAR),
      epoxyFar: await run(epoxyDraft(), ["Epoxy", "epoxy-install", "4", "12"], "Epoxy", FAR),
      polishLocal: await run(polishDraft(), ["Polish", "polishing", "4", "12"], "Polish", { ok: true, miles: 40, reason: "" }),
    };
  });

  // ═══ F. THE NOTE UNDER AN OPTION NAMES THE SHEET BY ITS NAME ON SCREEN ═════════════════════════════════════════════════════════════════════════════════
  await section("notes", async () => {
    const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
    const b = await reopen(s.saved);
    P.clickOn(b, '[data-sh-act="copy"]');
    await settle();
    b.clock.fire();
    const copy = B.sectionsOf(b.api.root()).filter((e) => e.kind === "option")[0];
    await makeBase(b, copy.tab);
    b.api.show(B.ROOT_TAB);
    b.api.go(1);
    const labor = { carrier: B.travelCarrier(b.api.root()), label: copy.label, note: textOf(b, "[data-travel-note]") };
    b.api.go(2);
    await settle();
    const review = b.doc.getElementById("panels").innerHTML;
    const m = /rates set on the ([^<]*?) section/.exec(review.replace(/&#39;/g, "'"));
    // ...and a Combo's other base, which is not an option, names the carrier too
    const c = await newBid(comboDraft(), ["Polish", "polishing", "4", "12"]);
    c.page.api.show("Epoxy");
    c.page.api.go(1);
    const comboNote = textOf(c.page, "[data-travel-note]");
    return { copyId: copy.tab, labor: labor, review: m ? m[0] : null, comboNote: comboNote };
  });

  // ═══ G. THE PATCH NOTE MOVES WITH THE TAKEOFF ═══════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("patchNote", async () => {
    const res = {};
    for (const kv of [["epoxy", "Epoxy", "[data-epoxy-patch]"], ["seal", "Seal", "[data-seal-patch]"]]) {
      const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
      const b = await reopen(s.saved);
      await addSheet(b, kv[1]);
      const tab = B.sectionsOf(b.api.root()).filter((e) => e.sheet === kv[1])[0].tab;
      b.api.show(tab);
      b.api.go(0);
      const sec = secOf(b.api.root(), tab);
      const first = (sec.takeoff || []).findIndex((r) => r && r.unit !== "LF");
      const emptyNote = textOf(b, kv[2]);
      // the area is typed into the first measured row, as a person types it
      const rowSel = '[data-tk="' + Math.max(first, 0) + '"][data-k="measurement"]';
      P.typeInto(b, rowSel, "2000");
      const typedNote = textOf(b, kv[2]);
      // ...and what the step says when it is drawn again from the model, the figure the note must already hold
      b.api.go(1);
      b.api.go(0);
      res[kv[0]] = { tab: tab, rows: (sec.takeoff || []).length, emptyNote: emptyNote, typedNote: typedNote, redrawnNote: textOf(b, kv[2]), sf: B.takeoffSf(sec.takeoff) };
    }
    return res;
  });

  // ═══ ROUND-5 AUDIT, MEDIUM 2: A TRAVEL LABOR LINE TAKEN AWAY WITH ITS x STAYS AWAY AFTER A RELOAD ═══════════════════════════════════════════════════════
  // migrateModel appended a blank Travel row to a bid with none, so a reload brought the line back and the next far answer priced it (+$783).
  await section("xStays", async () => {
    const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
    const a = await reopen(s.saved);
    const i = idxIn(secOf(a.api.root(), B.ROOT_TAB), "travel");
    P.clickOn(a, '[data-del-lab="' + i + '"]');
    await settle();
    a.api.saveSoon();
    a.clock.fire();
    const afterX = clone(a.store.blob);
    await typeMiles(a, "300");
    const session = prices(a);
    const r = await reopen(afterX);
    const rowAfterReload = rowFacts(rowIn(secOf(r.api.root(), B.ROOT_TAB)));
    await typeMiles(r, "300");
    const reloaded = prices(r);
    r.api.go(1);
    const addShown = has(r, '[data-add-travel="1"]');
    if (addShown) P.clickOn(r, '[data-add-travel="1"]');
    await settle();
    return { flag: !!(afterX.polish_estimate && afterX.polish_estimate.no_travel_labor === true), session: session.lump, reloaded: reloaded.lump,
             rowAfterReload: rowAfterReload, addShown: addShown, added: rowFacts(rowIn(secOf(r.api.root(), B.ROOT_TAB))),
             flagAfterAdd: r.api.root().no_travel_labor === true };
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
