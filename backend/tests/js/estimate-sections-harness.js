"use strict";
/* THE ESTIMATE FOLLOWS A FIGURE TYPED ON THE INTAKE, FOR EVERY SECTION (Hanz, 2026-10-13).
 *
 * The intake's boxes edit the takeoff of the section that owns each quantity, but they cannot reprice: the library
 * lives on the estimate page. So the draft's price snapshot (computed_bid, priced_tabs) still says the old floor
 * until the estimate page opens and saves once. Until 2026-10-13 that check looked at the Polish root alone, so an
 * Epoxy job's new floor was priced on screen and the snapshot the proposal reads stayed old.
 *
 * The page under test is js/polish-estimate.js, executed whole through polish-estimate-harness.js's own prelude (one DOM
 * stub, one fetch stub), with the REAL js/bid-model.js and js/library-core.js. A bid is opened and saved by the page;
 * what the intake does to it is the real door (B.patchModel with the typed boxes); the page is opened again on that,
 * and what it does on open is read: how many saves it queued, and what the last one wrote.
 *
 * Usage: node estimate-sections-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");

const BASE = path.join(__dirname, "polish-estimate-harness.js");
const code = fs.readFileSync(BASE, "utf8").replace(/\r\n/g, "\n");
const MARK = "(async function () {\n  // ── A. the takeoff row";
const at = code.indexOf(MARK);
if (at < 0) throw new Error("polish-estimate-harness.js scenario block moved; update the marker");
const head = code.slice(0, at);

const SCENARIOS = String.raw`
// Appended to polish-estimate-harness.js's prelude: build, blob, clone, B, L, ASMS, ITEMS and the rest are in scope.
// A library whose coverages divide the floors used below, so a price moving with the floor is not a pack boundary.
const ITEMS2 = [
  { id: "e1", name: "Coat A", unit: "Gal", buy_qty: 1, unit_cost: 20, coverage: 100, waste_pct: 0 },
  { id: "e2", name: "Coat B", unit: "Gal", buy_qty: 1, unit_cost: 30, coverage: 250, waste_pct: 0 },
];
const ASMS2 = [
  { id: "s1", name: "System One", unit: "SF", favorite: true, lines: [{ item_id: "e1", coverage: 100, waste_pct: 0, roundup: true }] },
  { id: "s2", name: "System Two", unit: "SF", favorite: true, lines: [{ item_id: "e2", coverage: 250, waste_pct: 0, roundup: true }] },
  { id: "s3", name: "Cove E", unit: "LF", lines: [{ item_id: "e1", coverage: 100, waste_pct: 0, roundup: true }] },
];
const open = async (blb) => {
  const b = build({ asms: clone(ASMS2), items: clone(ITEMS2), blob: blb });
  await b.api.init();
  return b;
};
// A bid opened and then saved once by the page (an edit), so the draft holds the price snapshot the page writes.
const opened = async (blb) => {
  const b = await open(blb);
  b.clock.fire();                                // the seeding's own save, if the page queued one
  b.api.changed(false);
  b.clock.fire();
  return b;
};
// What the intake's save does to the saved draft when the estimator types into boxes: the typed figures into the model
// by the one door (B.patchModel), and the same figure under the box's own draft key. The price snapshot is NOT touched.
const intakeTyped = (blb, boxes) => {
  const next = clone(blb);
  next.polish_estimate = B.patchModel(next.polish_estimate, { boxes: boxes });
  Object.keys(boxes).forEach((k) => { next[k] = boxes[k]; });
  return next;
};
const snapOf = (blb, tab) => (blb.priced_tabs || []).filter((t) => t.id === tab)[0];

(async function () {
  const out = {};

  // ── 1. AN EPOXY JOB: System 1 and the cove typed on the intake reach the estimate ────────────────────────
  {
    const first = await opened(blob({ work_type: "epoxy", polish_estimate: null,
      system_1_sf: 5000, system_2_sf: 3000, cove_1_lf: 100, cove_2_lf: 40 }));
    const savedBlob = clone(first.store.blob);
    const before = first.api.activeBid().total;
    out.epoxyBefore = { total: before, sf: snapOf(savedBlob, "Epoxy").sf, lump: savedBlob.computed_bid.lump_sum,
      carriers: first.api.model().takeoff.filter((r) => r.floor_area).map((r) => r.measurement) };

    // the control: opening the saved bid again writes nothing
    const again = await open(savedBlob);
    again.clock.fire();
    out.epoxyReopen = { saves: again.rec.saves.length };

    // the intake types System 1 = 331133
    const typed = intakeTyped(savedBlob, { system_1_sf: 331133 });
    const page = await open(typed);
    const modelOnOpen = page.api.model();
    out.epoxyTyped = { savesBeforeTimer: page.rec.saves.length,
      areas: B.measuredSfValues(modelOnOpen.takeoff), total: page.api.activeBid().total };
    page.clock.fire();
    const w = page.store.blob;
    out.epoxyTyped.saves = page.rec.saves.length;
    out.epoxyTyped.snap = snapOf(w, "Epoxy").sf;
    out.epoxyTyped.lump = w.computed_bid && w.computed_bid.lump_sum;
    out.epoxyTyped.tabTotal = snapOf(w, "Epoxy").total;
    out.epoxyTyped.sheetArea = w.sheet_area;

    // the cove alone (a different key of the same snapshot)
    const cove = await open(intakeTyped(savedBlob, { cove_1_lf: 250 }));
    cove.clock.fire();
    out.epoxyCove = { saves: cove.rec.saves.length, snap: snapOf(cove.store.blob, "Epoxy").sf };
  }

  // ── 2. A COMBO JOB: the Polish box moves the root's snapshot, the Epoxy box the Epoxy section's ─────────
  {
    const first = await opened(blob({ work_type: "combo", polish_estimate: null,
      polish_sf: 7000, system_1_sf: 5000, system_2_sf: 3000, cove_1_lf: 100 }));
    const savedBlob = clone(first.store.blob);
    out.comboBefore = { rootSf: savedBlob.computed_bid.polish_sf, epoxySf: snapOf(savedBlob, "Epoxy").sf };
    const again = await open(savedBlob);
    again.clock.fire();
    out.comboReopen = { saves: again.rec.saves.length };

    const rootTyped = await open(intakeTyped(savedBlob, { polish_sf: 9000 }));
    rootTyped.clock.fire();
    const rb = rootTyped.store.blob;
    out.comboRoot = { saves: rootTyped.rec.saves.length, polishSf: rb.polish_sf, computedPolishSf: rb.computed_bid.polish_sf,
      epoxy: snapOf(rb, "Epoxy").sf };

    const epoxyTyped = await open(intakeTyped(savedBlob, { system_1_sf: 6500 }));
    epoxyTyped.clock.fire();
    const eb = epoxyTyped.store.blob;
    out.comboEpoxy = { saves: epoxyTyped.rec.saves.length, polishSf: eb.polish_sf, epoxy: snapOf(eb, "Epoxy").sf };
  }

  // ── 3. A POLISH JOB IS WHAT IT WAS ─────────────────────────────────────────────────────────────────────
  {
    const first = await opened(blob({ work_type: "polish", polish_estimate: null, polish_sf: 7000 }));
    const savedBlob = clone(first.store.blob);
    const again = await open(savedBlob);
    again.clock.fire();
    const typed = await open(intakeTyped(savedBlob, { polish_sf: 9000 }));
    typed.clock.fire();
    out.polish = { reopenSaves: again.rec.saves.length, typedSaves: typed.rec.saves.length,
      polishSf: typed.store.blob.polish_sf, computed: typed.store.blob.computed_bid.polish_sf };
    // a draft that never had a snapshot writes nothing on open
    const bare = clone(savedBlob);
    delete bare.computed_bid;
    const none = await open(intakeTyped(bare, {}));
    none.clock.fire();
    out.polish.noSnapshotSaves = none.rec.saves.length;
  }

  // ── 4. THE CHECK ITSELF, on a Gyp section (the page needs the whole seeded library for that job) ───────
  {
    const m = B.sectionsForJob(B.migrateModel(null), "gyp", { rules: [] });
    const tab = 'Gyp (USG 1-8")';
    const withRows = clone(m);
    withRows.tabs[tab].takeoff = [
      { assembly_id: "wb-gyp-area-soft", assembly_name: "soft", measurement: 4000, unit: "SF", bucket: "soft" },
      { assembly_id: "wb-gyp-area-hard", assembly_name: "hard", measurement: 2000, unit: "SF", bucket: "hard" },
    ];
    const snap = { priced_tabs: [{ id: tab, sf: { gyp_soft_sf: 4000, gyp_hard_sf: 2000, gyp_corridor_sf: 0 } }] };
    const typed = B.patchModel(withRows, { boxes: { gyp_hard_sf: 3100 } });
    out.gypCheck = { agrees: B.snapshotBehind(withRows, snap), moved: B.snapshotBehind(typed, snap),
      noSnapshot: B.snapshotBehind(typed, {}) };
  }

  // ── 5. A SECTION THE ESTIMATOR STARTED BUT NEVER MEASURED (this page seeds a NEW section only) ────────────────────────
  // The bid is opened with no floor typed and edited once, so the Epoxy section holds Travel and a blank takeoff row. The
  // page will never seed it again; a floor typed on the intake afterwards has to be in the takeoff already.
  {
    const first = await opened(blob({ work_type: "epoxy", polish_estimate: null }));
    const savedBlob = clone(first.store.blob);
    const sec = savedBlob.polish_estimate.tabs.Epoxy;
    const base = await open(savedBlob);
    const page = await open(intakeTyped(savedBlob, { system_1_sf: 5000 }));
    page.clock.fire();
    // what the same floor is priced at when it is typed BEFORE the estimate is ever opened (a new bid)
    const fresh = await open(blob({ work_type: "epoxy", polish_estimate: null, system_1_sf: 5000 }));
    out.started = { labor: (sec.labor || []).map((r) => r.id), isNew: B.isNewSection(sec, false), fresh: fresh.api.activeBid().total,
      before: { sf: B.takeoffSf(base.api.model().takeoff), total: base.api.activeBid().total },
      after: { sf: B.takeoffSf(page.api.model().takeoff), total: page.api.activeBid().total, snap: (snapOf(page.store.blob, "Epoxy") || {}).sf } };

    // the same bid with a floor and a cove assembly picked, its length not typed yet: the intake's figure prices it
    const withFloor = await opened(blob({ work_type: "epoxy", polish_estimate: null, system_1_sf: 5000 }));
    const sv = clone(withFloor.store.blob);
    const rowsOf = (x) => x.polish_estimate.tabs.Epoxy.takeoff;
    rowsOf(sv).push({ assembly_id: "s3", assembly_name: "Cove E", measurement: "", unit: "LF" });
    const baseCove = await open(sv);
    const right = clone(sv);
    rowsOf(right)[rowsOf(right).length - 1].measurement = 150;
    const rightCove = await open(right);
    const typedBlob = intakeTyped(sv, { cove_1_lf: 150 });
    const typedCove = await open(typedBlob);
    out.startedCove = { rows: rowsOf(typedBlob).length, rowsBefore: rowsOf(sv).length, without: baseCove.api.activeBid().total,
      right: rightCove.api.activeBid().total, typed: typedCove.api.activeBid().total };
  }

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
`;

const m = new Module(BASE, module);
m.filename = BASE;
m.paths = Module._nodeModulePaths(path.dirname(BASE));
m._compile(head + SCENARIOS, BASE);
