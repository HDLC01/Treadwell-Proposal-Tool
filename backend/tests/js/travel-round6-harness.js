"use strict";
/* ROUND 6, PART 1, THE NIGHTS (2026-10-20), run on the REAL estimate page: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, with the REAL
 * js/bid-model.js beneath it. Every fact below is read off the page after it ran: the model it held, the panels it drew, what it saved. Nothing is a source assertion.
 * test_polish_travel_round6.py holds each one to numbers worked out BY HAND (a night is a night of one man, and a Gyp man-day is ten hours) and breaks a COPY of the page or the
 * model one line at a time to prove each fact can change.
 *
 * HANZ'S DECISIONS, 2026-10-12 (match Kyle's workbook EXACTLY per tab, quirks included) and 2026-10-20 (far jobs fill the drive, and FILL THE HOTEL AND PER DIEM NIGHTS
 * AUTOMATICALLY). Round 5 filled the nights from the section that carries the job's travel and counted DAY rows only, which was wrong twice:
 *
 *   N1  A GYP CREW IS ENTERED IN HOURS. Kyle's Gyp tab counts its own nights: Gyp!B64 `=IF(B5="No",((E52-E51)/C46)/10)`, per diem B65 `=B64`, so 4 guys for 120 hours is 48
 *       nights, not 0. `gyp` runs a far Gyp bid (Wichita, 190 miles) through the page: the nights and the per diem days follow the crew's hours, ten to a night, the card and the hints
 *       and the working say so, and the drive stays typed. `gypOption` and `gypCopy` are F3: a far Gyp option, or a copy of the Gyp sheet, priced $0 hotel and per diem under a
 *       note that says it carries its own (an identical copy was $10,536 under its base).
 *   N2  A COMBO'S NIGHTS ARE BOTH CREWS'. The follow figure was the carrier's man-days only: a far Combo (Polish 4 x 12 and Epoxy 4 x 12) filled 48 nights under words that said
 *       "Kyle's way", $71,555 against $81,226 typed as Kyle types it (hotel on every sheet). `combo` runs it: 96, and the hint and the working say where the count comes from.
 *   N4  `cards` pins the words of BOTH travel cards (Lodging and Per Diem), on a Gyp carrier and on every other, and the sentence above the travel block; `legacy` pins that a bid
 *       saved before this change prices as it did (an older-auto line is never converted).
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason; the mutation runs in the test count a section
 * error as a failure of the mutation, never as the mutation being noticed.
 *
 * Usage: node travel-round6-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const B = require(path.join(ROOT, "js", "bid-model.js"));
const E = require(path.join(ROOT, "js", "bid-engine.js"));
const PROFILES = require(path.join(ROOT, "js", "bid-profiles.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));
/** The nights an option's own labor counts: null where the model has no such answer (a tree without the code), so a missing function changes a fact and never crashes the run. */
const optionNights = (m, tab) => (typeof B.optionNights === "function" ? B.optionNights(m, tab) : null);
/** The hours a night is worth on a section's tab: null where the model has no such answer (a tree without the code). */
const nightsDivisor = (m, tab) => (typeof B.nightsDivisor === "function" ? B.nightsDivisor(m, tab) : null);

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in travel-round6-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "changeTo", "MODEL"]);

// The library's labor lines: Travel (built in), one Epoxy crew line, one Gyp pour. The Polish crew is the shipped fallback the page adds. Every crew is paid $33 an hour, so the
// sheet's count (labor dollars over the first row's rate over the tab's hours a night) and a person's count of man-days are the same figure, which is worked out by hand below.
const TRAVEL_ROW = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, sort: -1, favorite: true, default_work_types: [], default_on: true };
const EPOXY_ROW = { id: "epoxy-install", name: "Epoxy install", rate: 33, unit: "days", guys_auto: false, sort: 1, favorite: true, default_work_types: ["epoxy"], default_on: true };
const GYP_ROW = { id: "gyp-pour", name: "Gyp pour", rate: 33, unit: "hours", guys_auto: false, sort: 2, favorite: true, default_work_types: ["gyp"], default_on: true };
const SEAL_ROW = { id: "seal-install", name: "Seal install", rate: 33, unit: "days", guys_auto: false, sort: 3, favorite: true, default_work_types: ["seal"], default_on: true };
const LABOR = [TRAVEL_ROW, EPOXY_ROW, GYP_ROW, SEAL_ROW];
const GYP_TAB = 'Gyp (USG 1-8")';

const ADDR = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
const FAR = { ok: true, miles: 190, reason: "" };          // Wichita: a 380 mile round trip, 6.33 hours, 6.5 to the half hour
const CONDITIONS = { taxable: true, prevailing_wage: false, remodel_tax: false };
const draftOf = (workType, extra) => P.blob(Object.assign({ work_type: workType, polish_estimate: { version: 2, conditions: CONDITIONS } }, ADDR, extra || {}));
const gypDraft = () => draftOf("gyp", { gyp_soft_sf: 9000, gyp_hard_sf: 6000, gyp_corridor_sf: 2000 });
const comboDraft = () => draftOf("combo", { polish_sf: 5000, system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });
const polishDraft = () => draftOf("polish", { polish_sf: 5000 });
const epoxyDraft = () => draftOf("epoxy", { system_1_sf: 6000, system_2_sf: "", cove_1_lf: 300, cove_2_lf: "" });

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
const dec = (s) => String(s).replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const secOf = (m, tab) => (tab === B.ROOT_TAB ? m : (m.tabs || {})[tab]);
const rowIn = (sec) => ((sec && sec.labor instanceof Array ? sec.labor : [])).filter((r) => r && r.id === "travel")[0] || null;
const idxIn = (sec, id) => (sec && sec.labor instanceof Array ? sec.labor.findIndex((r) => r && r.id === id) : -1);
const boxOf = (b, sel) => { const el = b.doc.querySelector(sel); return el ? String(el.value) : null; };
const textOf = (b, sel) => { const el = b.doc.querySelector(sel); return el ? el.textContent : null; };
const panelHtml = (b) => String((b.doc.getElementById("panels") || {}).innerHTML || "");
const lumpOf = (blob) => (blob && blob.proposal_lump_sum !== undefined && blob.proposal_lump_sum !== null ? blob.proposal_lump_sum : blob && blob.computed_bid ? blob.computed_bid.lump_sum : null);
const rowFacts = (r) => (r ? { guys: r.guys, days: r.days, auto: !!r.guys_auto, follow: r.guys_follow === undefined ? null : r.guys_follow,
  seed: r.hours_seed === undefined ? null : r.hours_seed, typed: r.guys_typed === true, hoursTyped: r.hours_typed === true, on: r.enabled !== false, cost: B.laborCost(r) } : null);
const lineFacts = (l) => (l ? { on: !!l.enabled, qty: l.qty, auto: l.qty_auto !== false, follow: l.qty_follow === undefined ? null : l.qty_follow, typed: l.qty_typed === true,
  hand: l.hand === true } : null);
/** The words of one travel card (Lodging or Per Diem): the paragraph under it, which says where its quantity comes from. */
const cardNote = (b, key) => {
  const h = panelHtml(b);
  const at = h.indexOf('data-trv-card="' + key + '"');
  if (at < 0) return null;
  const m = /<p class="hint trvnote">([\s\S]*?)<\/p>/.exec(h.slice(at));
  return m ? dec(m[1]) : null;
};
/** The sentence above the travel block ("Travel is expected when the job is 70 miles or more from the office ..."). */
const capNote = (b) => { const m = /<p class="cap">(Travel is expected[\s\S]*?)<\/p>/.exec(panelHtml(b)); return m ? dec(m[1]) : null; };

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
  const root = b.api.bid();
  b.api.saveSoon();
  b.clock.fire();
  return { lump: lumpOf(b.store.blob), root: root.total, rootTravel: root.travel,
    sections: Object.fromEntries(Object.keys(bids).map((k) => [k, { total: bids[k].total, travel: bids[k].travel }])), miles: m.distance ? m.distance.miles : null };
}

/** What the page holds about the job's nights: the two lines, what the carrier is charged for them, and the drive. */
function nightsFacts(b) {
  const m = b.api.root();
  const car = B.travelCarrier(m);
  const sec = secOf(m, car);
  return { carrier: car, lodging: lineFacts(m.travel.lodging), perDiem: lineFacts(m.travel.per_diem),
    costs: B.travelCosts(m.travel, sec.labor, B.travelOpts(m, car)), drive: rowFacts(rowIn(sec)) };
}
/** What the Labor step of the carrier shows under its Lodging and Per Diem cards. */
const laborFacts = (b) => ({ lodgingBox: boxOf(b, '[data-trv="lodging"][data-k="qty"]'), perDiemBox: boxOf(b, '[data-trv="per_diem"][data-k="qty"]'),
  lodgingHint: textOf(b, '[data-hint-trv="lodging"]'), perDiemHint: textOf(b, '[data-hint-trv="per_diem"]'), how: textOf(b, "[data-trv-how]") });
/** What the Review step says: the quantity, the dollars and the words under the name of each line the job charges. */
async function reviewFacts(b) {
  b.api.go(2);
  await settle();
  return { lodgingNote: textOf(b, '[data-rv="trv.lodging.note"]'), perDiemNote: textOf(b, '[data-rv="trv.per_diem.note"]'),
    lodgingQty: textOf(b, '[data-rv="trv.lodging.q"]'), perDiemQty: textOf(b, '[data-rv="trv.per_diem.q"]'),
    lodgingTotal: textOf(b, '[data-rv="trv.lodging.tot"]'), perDiemTotal: textOf(b, '[data-rv="trv.per_diem.tot"]') };
}

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

async function addSheet(b, sheet) {
  b.api.go(1);
  if (b.doc.querySelector('[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]');
  P.clickOn(b, '[data-sh-act="add"][data-sh-sheet="' + String(sheet).replace(/"/g, "&quot;") + '"]');
  await settle();
  b.clock.fire();
}

async function main() {
  // ═══ N1. A GYP CREW IS ENTERED IN HOURS: a far Gyp job's nights follow them, ten hours to a night ═══════════════════════════════════════════════════════════
  // Wichita, 4 guys for 120 hours at $33: 480 man-hours, 48 nights at ten hours a night (Gyp!B64: $15,840 / $33 / 10), 48 days of per diem. 48 x $70 = $3,360 and 48 x $45 = $2,160.
  await section("gyp", async () => {
    const res = {};
    const s = await newBid(gypDraft(), [GYP_TAB, "gyp-pour", "4", "120"]);
    const b = s.page;
    b.api.go(1);
    await settle();
    res.saved = nightsFacts(b);
    res.labor = laborFacts(b);
    res.cards = { lodging: cardNote(b, "lodging"), perDiem: cardNote(b, "per_diem"), cap: capNote(b) };
    res.review = await reviewFacts(b);
    res.price = prices(b);
    // THE SAME BID WITH THE NIGHTS TYPED, as an estimator who counted them would: the price a following line must equal (typed lines never reach the code under test).
    {
      const t = await newBid(gypDraft(), [GYP_TAB, "gyp-pour", "4", "120"]);
      t.page.api.go(1);
      P.typeInto(t.page, '[data-trv="lodging"][data-k="qty"]', "48");
      P.typeInto(t.page, '[data-trv="per_diem"][data-k="qty"]', "48");
      res.typedPrice = prices(t.page);
      res.typedFacts = nightsFacts(t.page);
    }
    // FOLLOWING THE CREW: 5 guys is 60 nights, then 4 guys for 150 hours is 60 too.
    {
      const m = await newBid(gypDraft(), [GYP_TAB, "gyp-pour", "4", "120"]);
      m.page.api.go(1);
      typeCrew(m.page, GYP_TAB, "gyp-pour", "5", "120");
      res.moreGuys = { n: nightsFacts(m.page), l: laborFacts(m.page) };
      typeCrew(m.page, GYP_TAB, "gyp-pour", "4", "150");
      res.moreHours = { n: nightsFacts(m.page), l: laborFacts(m.page) };
    }
    // THE ESTIMATOR'S BOX IS THEIRS: nights typed (10) and per diem cleared stay theirs through a later answer (300 miles) and a later change of the crew.
    {
      const t = await newBid(gypDraft(), [GYP_TAB, "gyp-pour", "4", "120"]);
      const tb = t.page;
      tb.api.go(1);
      P.typeInto(tb, '[data-trv="lodging"][data-k="qty"]', "10");
      P.typeInto(tb, '[data-trv="per_diem"][data-k="qty"]', "");
      await typeMiles(tb, "300");
      typeCrew(tb, GYP_TAB, "gyp-pour", "5", "120");
      res.typed = { n: nightsFacts(tb), l: laborFacts(tb) };
    }
    // GOING LOCAL takes the figure the crew filled back to empty, and a far answer fills it again.
    {
      const g = await newBid(gypDraft(), [GYP_TAB, "gyp-pour", "4", "120"]);
      await typeMiles(g.page, "50");
      res.local = { n: nightsFacts(g.page), l: laborFacts(g.page) };
      await typeMiles(g.page, "190");
      res.farAgain = { n: nightsFacts(g.page), l: laborFacts(g.page) };
    }
    // A SAVED BID NEVER MOVES ON OPEN: the draft the far bid saved, reopened plain, arms no save, asks nothing and prices as saved.
    {
      const r = await reopen(s.saved);
      res.reopened = { n: nightsFacts(r), armed: r.clock.armed(), saves: r.rec.saves.length, asked: (r.rec.distanceBodies || []).length, price: prices(r).lump };
    }
    // ...and a far bid saved with its two lines ON and BLANK (what a bid held before an answer filled them) is not filled by being opened: nothing filled, saved or asked.
    {
      const old = clone(s.saved);
      ["lodging", "per_diem"].forEach((k) => { const l = old.polish_estimate.travel[k]; l.qty_auto = false; l.qty = ""; delete l.qty_follow; delete l.qty_typed; });
      const r = await reopen(old);
      const quiet = { armed: r.clock.armed(), saves: r.rec.saves.length, asked: (r.rec.distanceBodies || []).length };
      res.savedBlank = { n: nightsFacts(r), quiet: quiet, price: prices(r).lump };
    }
    return res;
  });

  // ═══ F3. A FAR GYP OPTION, AND A COPY OF THE GYP SHEET, CARRY THEIR OWN NIGHTS ═══════════════════════════════════════════════════════════════════════════
  // A far Polish bid (4 x 12) with a Gyp sheet added as an option, 4 guys for 120 hours: the option's own hotel and per diem are 48 x $70 and 48 x $45 = $5,520, as the Epoxy option
  // beside it (4 x 12 days) is. Before, the Gyp option's two lines were $0 under a note that says it carries its own.
  await section("gypOption", async () => {
    const s = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
    const run = async (sheet, crewRow, guys, days) => {
      const b = await reopen(s.saved);
      await addSheet(b, sheet);
      const tab = B.sectionsOf(b.api.root()).filter((e) => e.kind === "option")[0].tab;
      b.api.show(tab);
      b.api.go(1);
      await settle();
      typeCrew(b, tab, crewRow, guys, days);
      const m = b.api.root();
      const bids = b.api.sectionBids();
      const own = B.optionTravelCosts(m.travel, secOf(m, tab).labor, optionNights(m, tab));
      const review = await reviewFacts(b);
      return { tab: tab, layout: B.sectionsOf(m).filter((e) => e.tab === tab)[0].layout, labor: bids[tab].labor, travel: bids[tab].travel, total: bids[tab].total,
        own: own, nights: optionNights(m, tab), review: review, baseTravel: b.api.bid().travel,
        jobLines: { lodging: lineFacts(m.travel.lodging), perDiem: lineFacts(m.travel.per_diem) } };
    };
    return { gyp: await run(GYP_TAB, "gyp-pour", "4", "120"), epoxy: await run("Epoxy", "epoxy-install", "4", "12") };
  });
  // An identical copy of a far Gyp base (4 x 120 hours, the nights typed as 48 and 48) is the same price as the base, to the dollar.
  await section("gypCopy", async () => {
    const s = await newBid(gypDraft(), [GYP_TAB, "gyp-pour", "4", "120"]);
    const b = await reopen(s.saved);
    const car = B.travelCarrier(b.api.root());
    b.api.show(car);
    b.api.go(1);
    await settle();
    P.typeInto(b, '[data-trv="lodging"][data-k="qty"]', "48");
    P.typeInto(b, '[data-trv="per_diem"][data-k="qty"]', "48");
    await settle();
    const before = b.api.sectionBids()[car];
    P.clickOn(b, '[data-sh-act="copy"]');
    await settle();
    b.clock.fire();
    const bids = b.api.sectionBids();
    const copy = Object.keys(bids).filter((k) => k !== car)[0];
    return { carrier: car, copy: copy, kinds: B.sectionsOf(b.api.root()).map((e) => [e.tab, e.kind]),
      base: { total: bids[car].total, travel: bids[car].travel, labor: bids[car].labor }, alone: { total: before.total, travel: before.travel },
      copied: bids[copy] ? { total: bids[copy].total, travel: bids[copy].travel, labor: bids[copy].labor } : null };
  });

  // ═══ N2. A COMBO'S NIGHTS ARE THE MAN-DAYS OF EVERY BASE SECTION ═══════════════════════════════════════════════════════════════════════════════════════
  // Wichita, a Combo of Polish 4 x 12 and Epoxy 4 x 12: 48 + 48 = 96 nights and 96 days of per diem (Kyle carries hotel on every sheet): 96 x $70 = $6,720, 96 x $45 = $4,320.
  await section("combo", async () => {
    const res = {};
    const make = async () => {
      const s = await newBid(comboDraft(), ["Polish", "polishing", "4", "12"]);
      const b = await reopen(s.saved, { distance: FAR });
      b.api.show("Epoxy");
      b.api.go(1);
      await settle();
      typeCrew(b, "Epoxy", "epoxy-install", "4", "12");
      await settle();
      b.clock.fire();
      return b;
    };
    const b = await make();
    const car = B.travelCarrier(b.api.root());
    b.api.show(car);
    b.api.go(1);
    await settle();
    res.carrier = car;
    res.bases = B.sectionsOf(b.api.root()).map((e) => [e.tab, e.kind]);
    res.n = nightsFacts(b);
    res.l = laborFacts(b);
    res.cards = { lodging: cardNote(b, "lodging"), perDiem: cardNote(b, "per_diem"), cap: capNote(b) };
    res.review = await reviewFacts(b);
    res.price = prices(b);
    // THE SAME BID WITH BOTH CREWS' NIGHTS TYPED (96 and 96), the price Kyle's way gives: the following lines must equal it.
    {
      const t = await make();
      t.api.show(B.travelCarrier(t.api.root()));
      t.api.go(1);
      await settle();
      P.typeInto(t, '[data-trv="lodging"][data-k="qty"]', "96");
      P.typeInto(t, '[data-trv="per_diem"][data-k="qty"]', "96");
      await settle();
      res.typedPrice = prices(t);
      // ...and a typed line says where the sheet's count comes from (the man-days of both base sheets)
      res.typedHint = { lodging: textOf(t, '[data-hint-trv="lodging"]'), perDiem: textOf(t, '[data-hint-trv="per_diem"]'), how: textOf(t, "[data-trv-how]") };
    }
    // FOLLOWING EITHER CREW: the Epoxy crew to 5 guys (60 man-days) moves the figure to 48 + 60, and the Polish crew to 6 guys (72) after it to 72 + 60.
    {
      const m = await make();
      typeCrew(m, "Epoxy", "epoxy-install", "5", "12");
      res.moreEpoxy = { n: nightsFacts(m), manDays: [B.travelManDays(secOf(m.api.root(), "Polish").labor), B.travelManDays(secOf(m.api.root(), "Epoxy").labor)] };
      m.api.show("Polish");
      m.api.go(1);
      await settle();
      typeCrew(m, "Polish", "polishing", "6", "12");
      res.morePolish = { n: nightsFacts(m), l: laborFacts(m) };
    }
    // AN OFF SECTION COUNTS NOTHING: the job type switched to Polish alone (the Epoxy section goes off) is the Polish crew's 48.
    {
      const m = await make();
      const saved = clone(m.store.blob);
      const p = await reopen(Object.assign(saved, { work_type: "polish" }), { distance: FAR });
      p.api.show("Polish");
      p.api.go(1);
      await settle();
      res.polishOnly = { kinds: B.sectionsOf(p.api.root()).map((e) => [e.tab, e.kind]), n: nightsFacts(p), l: laborFacts(p), cards: { lodging: cardNote(p, "lodging") } };
    }
    // AN OPTION IS PRICED APART: a Seal sheet (2 guys for 5 days) beside the far Combo carries its own 10 nights and the job's lines stay 96.
    {
      const m = await make();
      await addSheet(m, "Seal");
      const seal = B.sectionsOf(m.api.root()).filter((e) => e.layout === "seal")[0];
      m.api.show(seal.tab);
      m.api.go(1);
      await settle();
      const first = (seal.section.labor || []).findIndex((r) => r && r.id !== "travel");
      const sealRowId = first >= 0 ? seal.section.labor[first].id : null;
      if (sealRowId) typeCrew(m, seal.tab, sealRowId, "2", "5");
      const root = m.api.root();
      const bids = m.api.sectionBids();
      res.withOption = { n: nightsFacts(m), optionNights: optionNights(root, seal.tab), optionTravel: bids[seal.tab].travel, sealRow: sealRowId,
        optionOwn: B.optionTravelCosts(root.travel, secOf(root, seal.tab).labor, optionNights(root, seal.tab)), rootTravel: m.api.bid().travel };
    }
    // THE SAVED DRAFT, reopened plain: nothing is armed, saved or asked, and the bid prices as it did.
    {
      const r = await reopen(clone(b.store.blob), { distance: FAR });
      res.reopened = { n: nightsFacts(r), armed: r.clock.armed(), saves: r.rec.saves.length, asked: (r.rec.distanceBodies || []).length, price: prices(r).lump };
    }
    // ...and the same Combo saved with its lines on and blank is not filled by being opened.
    {
      const old = clone(b.store.blob);
      ["lodging", "per_diem"].forEach((k) => { const l = old.polish_estimate.travel[k]; l.qty_auto = false; l.qty = ""; delete l.qty_follow; delete l.qty_typed; });
      const r = await reopen(old, { distance: FAR });
      const quiet = { armed: r.clock.armed(), saves: r.rec.saves.length, asked: (r.rec.distanceBodies || []).length };
      res.savedBlank = { n: nightsFacts(r), quiet: quiet, price: prices(r).lump };
    }
    return res;
  });

  // ═══ N4. THE WORDS ON BOTH TRAVEL CARDS ARE PINNED, ON A GYP CARRIER AND ON EVERY OTHER ═══════════════════════════════════════════════════════════════════
  await section("cards", async () => {
    const res = {};
    const seen = async (name, draft, crew) => {
      const s = await newBid(draft, crew);
      s.page.api.show(B.travelCarrier(s.page.api.root()));
      s.page.api.go(1);
      await settle();
      res[name] = { carrier: B.travelCarrier(s.page.api.root()), lodging: cardNote(s.page, "lodging"), perDiem: cardNote(s.page, "per_diem"), cap: capNote(s.page) };
    };
    await seen("gyp", gypDraft(), [GYP_TAB, "gyp-pour", "4", "120"]);
    await seen("polish", polishDraft(), ["Polish", "polishing", "4", "12"]);
    await seen("epoxy", epoxyDraft(), ["Epoxy", "epoxy-install", "4", "12"]);
    return res;
  });

  // ═══ A BID SAVED BEFORE THIS CHANGE PRICES AS IT DID ═══════════════════════════════════════════════════════════════════════════════════════════════════
  // The lines on the OLDER auto (on auto, no marker: a bid saved before 2026-10-12) are never converted: a Gyp carrier's still count day rows only (a crew in hours is none), and a
  // Combo's still count the carrier's. The totals are pinned from the page of 619f092 (the parent of this change) in test_polish_travel_round6.py.
  await section("legacy", async () => {
    const res = {};
    const older = (saved) => {
      const old = clone(saved);
      ["lodging", "per_diem"].forEach((k) => { const l = old.polish_estimate.travel[k]; l.qty_auto = true; l.qty = 48; delete l.qty_follow; delete l.qty_typed; });
      return old;
    };
    const facts = async (name, saved, extra) => {
      const b = await reopen(saved, Object.assign({ distance: FAR }, extra || {}));
      const car = B.travelCarrier(b.api.root());
      const quiet = { armed: b.clock.armed(), saves: b.rec.saves.length };      // read before the price forces a save
      const price = prices(b);
      res[name] = { carrier: car, lodging: lineFacts(b.api.root().travel.lodging), perDiem: lineFacts(b.api.root().travel.per_diem), lump: price.lump,
        armed: quiet.armed, saves: quiet.saves, travel: price.sections[car] ? price.sections[car].travel : price.rootTravel };
    };
    const gyp = await newBid(gypDraft(), [GYP_TAB, "gyp-pour", "4", "120"]);
    await facts("gypOlderAuto", older(gyp.saved));
    const polish = await newBid(polishDraft(), ["Polish", "polishing", "4", "12"]);
    await facts("polishOlderAuto", older(polish.saved));
    // a Combo whose Epoxy crew was typed too (4 x 12 beside the Polish 4 x 12), its lines on the older auto
    const cs = await newBid(comboDraft(), ["Polish", "polishing", "4", "12"]);
    const cb = await reopen(cs.saved, { distance: FAR });
    cb.api.show("Epoxy");
    cb.api.go(1);
    await settle();
    typeCrew(cb, "Epoxy", "epoxy-install", "4", "12");
    cb.clock.fire();
    await facts("comboOlderAuto", older(clone(cb.store.blob)));
    // ...and the same Combo with the nights TYPED (96 and 96): typed is the estimator's, whatever the crews
    const typed = clone(cb.store.blob);
    ["lodging", "per_diem"].forEach((k) => { const l = typed.polish_estimate.travel[k]; l.qty_auto = false; l.qty = "96"; l.qty_typed = true; delete l.qty_follow; });
    await facts("comboTyped", typed);
    // ONE LINE FOLLOWS AND THE OTHER IS THE OLDER AUTO: each is charged by its own kind (the Lodging the two crews' 96, the Per Diem the carrier's own 48, as it always was).
    {
      const mixed = clone(cb.store.blob);
      const pd = mixed.polish_estimate.travel.per_diem;
      pd.qty_auto = true; pd.qty = 48; delete pd.qty_follow; delete pd.qty_typed;
      const b = await reopen(mixed, { distance: FAR });
      const m = b.api.root();
      const car = B.travelCarrier(m);
      res.comboOneFollows = { lodging: lineFacts(m.travel.lodging), perDiem: lineFacts(m.travel.per_diem), costs: B.travelCosts(m.travel, secOf(m, car).labor, B.travelOpts(m, car)) };
    }
    return res;
  });

  // ═══ THE MODEL'S OWN COUNT, with no page: a crew in hours, and each tab's own divisor ═══════════════════════════════════════════════════════════════════
  await section("direct", async () => {
    const res = {};
    const crew = { id: "gyp-pour", guys: 4, days: 120, rate: 33, unit: "hours" };      // 4 guys, 120 hours: 480 man-hours
    const drive = { id: "travel", guys: 3, days: 7, rate: 33, unit: "hours" };         // the drive is never a night
    res.manDays = {
      // asked of the rows alone (no tab to say what a night is worth), an hours row counts nothing, as it always did
      legacy: B.travelManDays([crew, drive]),
      // told the hours a night is worth (10 on Gyp), the crew's hours count and the drive does not
      gyp: B.travelManDays([crew, drive], 10),
      over8: B.travelManDays([crew, drive], 8),
      off: B.travelManDays([Object.assign({}, crew, { enabled: false }), drive], 10),
      withDays: B.travelManDays([{ id: "x", guys: 3, days: 5 }, crew, drive], 10),
    };
    // EVERY PROFILE'S OWN DIVISOR, against its own tab's lodging formula (the figure after the last slash of `lodgingQty`), and what the model answers for a section of that tab.
    const tabs = PROFILES.priced.slice();
    res.formulas = tabs.map((tab) => {
      const f = PROFILES.sheets[tab].outputs.lodgingQty.formula;
      const m = /\/(\d+)\)$/.exec(f);
      return { tab: tab, formula: f, divisor: m ? Number(m[1]) : null, profile: E.forTab(tab).profile.quirks.lodgingDivisor, dayHours: E.forTab(tab).profile.quirks.dayHours };
    });
    const hoursCrew = { id: "crew", label: "Crew", guys: 2, days: 40, rate: 33.66, unit: "hours" };      // 2 guys, 40 hours
    res.sections = {};
    ["Epoxy", "Seal", "Seal (+Jnts)", "Leveling", "Epoxy blank", GYP_TAB].forEach((tab) => {
      const base = B.activateSection(B.freshModel(), tab, tab === "Epoxy" || tab === GYP_TAB ? "base" : "option", {});
      base.tabs[tab].labor = [clone(hoursCrew)];
      res.sections[tab] = { divisor: nightsDivisor(base, tab), nights: optionNights(base, tab), people: B.travelManDays(base.tabs[tab].labor, nightsDivisor(base, tab)) };
    });
    res.root = { divisor: nightsDivisor(B.freshModel(), B.ROOT_TAB) };
    // THE SHEET'S OWN COUNT, for a Gyp crew paid two rates (Gyp!B64: the labor dollars, less the drive's, over the first row's rate, over 10): the oracle's `mixedRates` row set,
    // in hours (a ten hour day each), whose labor is $6,969, so 20.704 nights where a person counts 19.
    const gyp = E.resolveProfile("gyp");
    const mixed = [{ id: "a", guys: 3, days: 50, rate: 33.66, unit: "hours" }, { id: "b", guys: 2, days: 20, rate: 48, unit: "hours" }];
    const withDrive = [{ id: "a", guys: 3, days: 50, rate: 33.66, unit: "hours" }, { id: "travel", guys: 1, days: 18, rate: 33.66, unit: "hours" }];
    res.sheet = { mixed: B.sheetNights(mixed, {}, 0, gyp), mixedPeople: B.travelManDays(mixed, 10), withDrive: B.sheetNights(withDrive, {}, 0, gyp), withDrivePeople: B.travelManDays(withDrive, 10),
      // the Polish way is the old way: every hours row is the drive, whatever its name
      polishWay: B.sheetNights([{ id: "a", guys: 3, days: 5, rate: 33 }, { id: "grinder", guys: 2, days: 10, rate: 33, unit: "hours" }]) };
    // THE WORKING IS WORKED OUT OF THE WHOLE MODEL, whatever section the panel hands it: a Combo (Polish 4 x 12, Epoxy 5 x 10) asked through the view of its Epoxy section, with the whole model beside
    // it, counts 48 + 50 = 98 man-days between the two bases, where the view alone would read the Epoxy rows as the root's too.
    {
      const m = B.activateSection(B.freshModel(), "Epoxy", "base", {});
      m.profile = "polish-rev3@1";
      m.labor = [{ id: "polishing", label: "Polishing", guys: 4, days: 12, rate: 33 }, { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours", guys_auto: false }];
      m.tabs.Epoxy.labor = [{ id: "epoxy-install", label: "Epoxy install", guys: 5, days: 10, rate: 33 }];
      m.travel = { lodging: { label: "Lodging", enabled: false, qty: "", qty_auto: false, rate: 70 }, per_diem: { label: "Per Diem", enabled: false, qty: "", qty_auto: false, rate: 45 } };
      B.applyDistance(m, { miles: 190, source: "typed" });
      B.syncAutoGuys(m);
      const follow = (lines) => lines.filter((l) => /follow the/.test(l));
      res.how = { carrier: B.travelCarrier(m), job: B.jobNights(m), whole: follow(B.travelHow(B.sectionView(m, "Epoxy"), m).lines), plain: follow(B.travelHow(m).lines) };
    }
    return res;
  });

  // ═══ THE WORDS WHEN THE SHEET'S COUNT IS NOT THE HEAD COUNT: a crew paid two rates, on a Gyp bid and on a Combo ═══════════════════════════════════════════
  // The sheet counts labor DOLLARS over the first row's rate, so a row paid another rate reads as extra days, and the words say both figures. A Gyp crew (3 guys for 50 hours at $33.66 and 2 for 20 at
  // $48: $6,969) is 20.7 nights where guys x hours over ten is 19; a Combo's Polish sheet (2 guys for 5 days at $33 and 2 at $66: $7,920 over $33 over 8) is 30 nights where guys x days is 20, and its
  // Epoxy sheet (3 guys for 4 days) is 12, so the two bases are 42 where the head count is 32.
  await section("words", async () => {
    const res = {};
    const lines = () => ({ lodging: { label: "Lodging", enabled: false, qty: "", qty_auto: false, rate: 70 }, per_diem: { label: "Per Diem", enabled: false, qty: "", qty_auto: false, rate: 45 } });
    const farAnswer = (m) => { B.applyDistance(m, { miles: 190, source: "typed" }); B.syncAutoGuys(m); return m; };
    const typedLines = (m) => { ["lodging", "per_diem"].forEach((k) => { B.markTravelQtyTyped(m.travel[k]); m.travel[k].qty = "10"; }); return m; };
    const gyp = () => {
      const m = B.activateSection(Object.assign({}, B.freshModel(), { kind: "off" }), GYP_TAB, "base", {});
      m.tabs[GYP_TAB].labor = [{ id: "a", label: "A", guys: 3, days: 50, rate: 33.66, unit: "hours" }, { id: "b", label: "B", guys: 2, days: 20, rate: 48, unit: "hours" }];
      m.travel = lines();
      return m;
    };
    const combo = () => {
      const m = B.activateSection(B.freshModel(), "Epoxy", "base", {});
      m.profile = "polish-rev3@1";
      m.labor = [{ id: "a", label: "A", guys: 2, days: 5, rate: 33 }, { id: "b", label: "B", guys: 2, days: 5, rate: 66 }];
      m.tabs.Epoxy.labor = [{ id: "epoxy-install", label: "Epoxy install", guys: 3, days: 4, rate: 33 }];
      m.travel = lines();
      return m;
    };
    const pick = (ls, re) => ls.filter((l) => re.test(l));
    // As the page asks: the hints with the carrier's own rows, the working through the view of the section on show with the whole model beside it.
    const read = (m, tab) => {
      const rows = tab === B.ROOT_TAB ? m.labor : m.tabs[tab].labor;
      const how = B.travelHow(B.sectionView(m, tab), m).lines;
      return { job: B.jobNights(m), costs: B.travelCosts(m.travel, rows, B.travelOpts(m, tab)), lodgingHint: B.travelQtyHint(m, tab, "lodging", m.travel.lodging, rows), perDiemHint: B.travelQtyHint(m, tab, "per_diem", m.travel.per_diem, rows),
        following: pick(how, /follow the/), reference: pick(how, /^For reference/) };
    };
    res.gypFollowing = read(farAnswer(gyp()), GYP_TAB);
    res.gypTyped = read(typedLines(farAnswer(gyp())), GYP_TAB);
    res.comboFollowing = read(farAnswer(combo()), B.ROOT_TAB);
    res.comboTyped = read(typedLines(farAnswer(combo())), B.ROOT_TAB);
    // THE LIBRARY'S OWN GYP RATE, $33.66: the sheet rounds the labor UP to the dollar before it divides, so 4 guys for 120 hours count 48.0006 nights where a head count says 48, and charge a dollar
    // more on each line ($3,361 and $2,161). Both counts read 48, and a typed box is told so in the plain words, not "as the sheet counts them".
    const real = () => {
      const m = gyp();
      m.tabs[GYP_TAB].labor = [{ id: "a", label: "A", guys: 4, days: 120, rate: 33.66, unit: "hours" }];
      return m;
    };
    res.gypRealFollowing = read(farAnswer(real()), GYP_TAB);
    res.gypRealTyped = read(typedLines(farAnswer(real())), GYP_TAB);
    // A LINE ON THE OLDER AUTO keeps the exactness it always had: a rev 3 root (Polishing 4 x 12, a drive of 5 guys x 6.5 hours = $1,072.50) counts 48.0019 nights where guys x days is 48, and the
    // line says so ("as the sheet does"), as a bid saved before 2026-10-12 always read.
    const older = combo();
    older.tabs.Epoxy.kind = "off";
    older.labor = [{ id: "polishing", label: "Polishing", guys: 4, days: 12, rate: 33 }, { id: "travel", label: "Travel Labor", guys: 5, days: 6.5, rate: 33, unit: "hours", guys_auto: false }];
    older.travel = { lodging: { label: "Lodging", enabled: true, qty: 48, qty_auto: true, rate: 70 }, per_diem: { label: "Per Diem", enabled: true, qty: 48, qty_auto: true, rate: 45 } };
    res.olderAutoNear = { job: B.jobNights(older), hint: B.travelQtyHint(older, B.ROOT_TAB, "lodging", older.travel.lodging, older.labor) };
    return res;
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
