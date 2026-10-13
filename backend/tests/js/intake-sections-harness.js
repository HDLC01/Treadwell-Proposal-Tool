"use strict";
/* EVERY SECTION'S QUANTITY BOXES ON THE v2 INTAKE EDIT THE TAKEOFF OF THE SECTION THAT OWNS THEM
 * (Hanz, 2026-10-13: "I changed the values but didn't pull in the estimate", an Epoxy job whose
 * "Epoxy floor SF" was changed to 331133 and whose Epoxy takeoff still held 1000).
 *
 * The page under test is js/polish-intake.js, executed through polish-intake-harness.js's own prelude (its DOM
 * stub, clock, sandbox stub and function lifting, so there is one stub and not two), with the REAL
 * js/bid-model.js and js/work-types.js underneath. A project is opened with a saved model that has the section a
 * job type is priced on (made by B.sectionsForJob, the way the estimate page makes it), an estimator types into a
 * box, the page's own timer fires, and every figure below is what the page SAVED.
 *
 * Usage: node intake-sections-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");

const BASE = path.join(__dirname, "polish-intake-harness.js");
const code = fs.readFileSync(BASE, "utf8").replace(/\r\n/g, "\n");
const MARK = "(async function () {\n  // ── the five toggles, from the data the page ships";
const at = code.indexOf(MARK);
if (at < 0) throw new Error("polish-intake-harness.js scenario block moved; update the marker");
const head = code.slice(0, at);

const SCENARIOS = String.raw`
// Appended to polish-intake-harness.js's prelude: P (bid-model), W (work-types), blob, build, FORM_VALUES, LABOR and the
// rest are in scope.
const clone = (x) => JSON.parse(JSON.stringify(x));
const BOXES = P.boxNames();
const FORM_ALL = Object.assign({}, FORM_VALUES, Object.fromEntries(BOXES.map((n) => [n, ""])));

// An Epoxy floor of two separate areas (what a new bid seeds), each a carrier with a line that follows it, and the
// cove as two linear-foot rows. System 1 = 1000, System 2 = 500, Cove 1 = 120, Cove 2 = 40.
const EPOXY_ROWS = () => [
  { assembly_id: "s1", assembly_name: "System One", measurement: 1000, unit: "SF", floor_area: 1 },
  { kind: "item", item_id: "e2", item_name: "Coat B", coverage: "", measurement: 1000, unit: "SF", same_floor: true, same_floor_of: 1 },
  { assembly_id: "s3", assembly_name: "Cove", measurement: 120, unit: "LF" },
  { assembly_id: "s1", assembly_name: "System One", measurement: 500, unit: "SF", floor_area: 2 },
  { kind: "item", item_id: "e2", item_name: "Coat B", coverage: "", measurement: 500, unit: "SF", same_floor: true, same_floor_of: 2 },
  { assembly_id: "", assembly_name: "", measurement: 40, unit: "LF" },
];
const POLISH_ROWS = () => [
  { assembly_id: "asm-sp", assembly_name: "Salt & Pepper polish", measurement: 7000, unit: "SF" },
];
const GYP_ROWS = () => [
  { assembly_id: "wb-gyp-area-soft", assembly_name: "Gypsum: soft surfaces", measurement: 4000, unit: "SF", bucket: "soft" },
  { assembly_id: "wb-gyp-area-hard", assembly_name: "Gypsum: hard surfaces over the sound mat", measurement: 2000, unit: "SF", bucket: "hard" },
];
const GYP_TAB = 'Gyp (USG 1-8")';

// A saved model with the section(s) a job type is priced on, and the takeoffs given (rows for root, Epoxy, Gyp).
const modelFor = (job, rows) => {
  const m = clone(P.sectionsForJob(P.migrateModel(null), job, { rules: [] }));
  if (rows.root) m.takeoff = clone(rows.root);
  if (rows.epoxy) m.tabs.Epoxy.takeoff = clone(rows.epoxy);
  if (rows.gyp) m.tabs[GYP_TAB].takeoff = clone(rows.gyp);
  return m;
};

// What the page's readForm hands save(): the fixture's fields, and a box's CURRENT text only when the estimator
// typed into it (the real readForm takes every named input; the page decides which box counts as typed).
const open = async (job, model, draft) => {
  const holder = {};
  const b = build({
    blob: blob(Object.assign({ work_type: job, polish_estimate: model }, draft || {})),
    formValues: FORM_ALL,
    readForm: () => {
      const v = Object.assign({}, FORM_VALUES);
      BOXES.forEach((n) => { const f = holder.b.dom.fields[n]; if (f && (f.fromUser || f.value !== "")) v[n] = f.value; });
      return v;
    },
  });
  holder.b = b;
  await b.api.boot();
  return b;
};
const typeInto = (bb, name, value) => {
  bb.dom.fields[name].value = String(value);
  bb.dom.fields[name].fromUser = true;
  bb.dom.nodes["intake-form"].listeners.filter((l) => l.type === "input")
    .forEach((l) => l.handler({ target: bb.dom.fields[name] }));
};
const blurBox = (bb, name) => bb.dom.nodes["intake-form"].listeners.filter((l) => l.type === "change")
  .forEach((l) => l.handler({ target: bb.dom.fields[name] }));
const settle = (bb) => bb.clock.fire();
const shown = (bb) => Object.fromEntries(BOXES.map((n) => [n, bb.dom.fields[n].value]));
const saved = (bb) => bb.store.blob.polish_estimate;
const rowsOf = (bb, tab) => (tab === "Polish" ? saved(bb).takeoff : saved(bb).tabs[tab].takeoff);
const figs = (rows) => rows.map((r) => ({ id: r.assembly_id || r.item_id || "", m: r.measurement, u: r.unit,
  carrier: r.floor_area || 0, follows: r.same_floor ? (r.same_floor_of || 0) : null }));
const measuresOf = (rows) => rows.map((r) => r.measurement);
const draftKeys = (bb) => ({ s1: bb.store.blob.system_1_sf, s2: bb.store.blob.system_2_sf,
  c1: bb.store.blob.cove_1_lf, c2: bb.store.blob.cove_2_lf, p1: bb.store.blob.polish_sf, p2: bb.store.blob.polish_2_sf,
  g1: bb.store.blob.gyp_soft_sf, g2: bb.store.blob.gyp_hard_sf, g3: bb.store.blob.gyp_corridor_sf });

(async function () {
  // ── 0. THE ONE MAPPING, from the vocabulary ───────────────────────────────────────────────────────────
  out.homes = Object.fromEntries(BOXES.map((n) => [n, W.fieldHome(n)]));
  out.homeOfNothing = W.fieldHome("project_name");
  out.gypAssemblies = P.GYP_AREA_ASSEMBLIES.map((a) => [a.bucket, a.id, a.name]);
  out.gypBuckets = P.GYP_BUCKETS;

  // ── 1. AN EPOXY JOB: the boxes mirror the Epoxy section, and typing changes ITS rows ──────────────────
  {
    const model = modelFor("epoxy", { epoxy: EPOXY_ROWS() });
    const rootBefore = clone(model.takeoff);
    const b = await open("epoxy", model, { system_1_sf: 1000, system_2_sf: 500, cove_1_lf: 120, cove_2_lf: 40 });
    out.epoxyPainted = shown(b);
    out.epoxyNoSave = b.rec.saves.length;

    // THE BUG: System 1 typed as 331133 (a figure far from what the takeoff holds)
    typeInto(b, "system_1_sf", 331133);
    settle(b);
    out.sys1 = { epoxy: figs(rowsOf(b, "Epoxy")), draft: draftKeys(b), shown: shown(b),
      rootUntouched: JSON.stringify(saved(b).takeoff) === JSON.stringify(rootBefore),
      kind: saved(b).kind, tabKind: saved(b).tabs.Epoxy.kind,
      values: P.measuredSfValues(rowsOf(b, "Epoxy")), priced: P.takeoffSf(rowsOf(b, "Epoxy")) };

    // System 2 and both cove boxes, one after another
    typeInto(b, "system_2_sf", 800);
    settle(b);
    out.sys2 = { measures: measuresOf(rowsOf(b, "Epoxy")), draft: draftKeys(b), shown: shown(b) };
    typeInto(b, "cove_1_lf", 200);
    settle(b);
    out.cove1 = { measures: measuresOf(rowsOf(b, "Epoxy")), draft: draftKeys(b) };
    typeInto(b, "cove_2_lf", 60);
    settle(b);
    out.cove2 = { measures: measuresOf(rowsOf(b, "Epoxy")), draft: draftKeys(b), shown: shown(b),
      lfValues: P.measuredLfValues(rowsOf(b, "Epoxy")) };
  }

  // ── 2. TYPING 0 OR NOTHING DELETES NOTHING (Hanz typed 0 into System 2 and the cove boxes) ─────────────
  {
    const model = modelFor("epoxy", { epoxy: EPOXY_ROWS() });
    const rowsBefore = JSON.stringify(model.tabs.Epoxy.takeoff);
    out.zero = {};
    for (const [label, name, value] of [["s2zero", "system_2_sf", 0], ["s2blank", "system_2_sf", ""],
      ["c1zero", "cove_1_lf", 0], ["c2blank", "cove_2_lf", ""], ["s1neg", "system_1_sf", -5], ["c2zero", "cove_2_lf", "0"]]) {
      const b = await open("epoxy", clone(model), { system_1_sf: 1000, system_2_sf: 500, cove_1_lf: 120, cove_2_lf: 40 });
      typeInto(b, name, value);
      settle(b);
      const m = saved(b);
      out.zero[label] = { rowsSame: JSON.stringify(m.tabs.Epoxy.takeoff) === rowsBefore, rowCount: m.tabs.Epoxy.takeoff.length,
        draft: draftKeys(b), saves: b.rec.saves.length };
      // leaving the box repaints the row's figure back
      blurBox(b, name);
      out.zero[label].afterBlur = b.dom.fields[name].value;
    }
  }

  // ── 3. A BOX NOBODY TYPED IN NEVER WRITES, even one holding another figure ─────────────────────────────
  {
    const model = modelFor("epoxy", { epoxy: EPOXY_ROWS() });
    const b = await open("epoxy", model, { system_1_sf: 1000, system_2_sf: 500, cove_1_lf: 120, cove_2_lf: 40 });
    b.dom.fields.system_1_sf.value = "777";          // set, but no input event: a stale paint
    b.api.save();
    out.untyped = { measures: measuresOf(rowsOf(b, "Epoxy")), s1: b.store.blob.system_1_sf };
    // the typed mark is good for ONE save: a later unrelated save does not re-send the figure
    typeInto(b, "system_1_sf", 1200);
    settle(b);
    const once = measuresOf(rowsOf(b, "Epoxy"));
    b.api.save();                                    // the box still says 1200; the takeoff is changed elsewhere
    const moved = clone(saved(b));
    moved.tabs.Epoxy.takeoff[0].measurement = 4321;
    b.store.blob.polish_estimate = moved;
    b.api.save();
    out.markOnce = { once, after: measuresOf(rowsOf(b, "Epoxy")) };
  }

  // ── 4. A THIRD AREA IS LEFT ALONE, with a plain line and a link to the Takeoff ─────────────────────────
  {
    const rows = EPOXY_ROWS().concat([
      { assembly_id: "s1", assembly_name: "System One", measurement: 250, unit: "SF", floor_area: 3 },
    ]);
    const b = await open("epoxy", modelFor("epoxy", { epoxy: rows }), { system_1_sf: 1000, system_2_sf: 500 });
    out.third = { text: b.dom.nodes["sf-areas-note"].textContent, hidden: b.dom.nodes["sf-areas-note"].hidden,
      rowHidden: b.dom.nodes["sf-takeoff-row"].hidden, href: b.dom.nodes["sf-takeoff-link"].href || "" };
    typeInto(b, "system_2_sf", 900);
    settle(b);
    out.third.measures = measuresOf(rowsOf(b, "Epoxy"));
  }

  // ── 5. NOTHING MEASURED YET: the boxes seed the takeoff on the estimate page, as for any new bid ───────
  {
    const blank = modelFor("epoxy", {});
    const b = await open("epoxy", blank, {});
    typeInto(b, "system_1_sf", 5000);
    typeInto(b, "cove_1_lf", 80);
    settle(b);
    out.unmeasured = { draft: draftKeys(b), epoxyRows: rowsOf(b, "Epoxy").map((r) => [r.unit, r.measurement]),
      rootKind: saved(b).kind };
  }

  // ── 6. A GYP JOB: each box is its own area of the Gyp section ───────────────────────────────────────────
  {
    const b = await open("gyp", modelFor("gyp", { gyp: GYP_ROWS() }), { gyp_soft_sf: 4000, gyp_hard_sf: 2000 });
    out.gypPainted = shown(b);
    typeInto(b, "gyp_hard_sf", 2600);
    typeInto(b, "gyp_corridor_sf", 900);             // no corridor row yet: it is added as the library's area assembly
    settle(b);
    const rows = rowsOf(b, GYP_TAB);
    out.gyp = { rows: rows.map((r) => [r.assembly_id, r.measurement, r.bucket, r.unit]), draft: draftKeys(b),
      areas: P.gypAreaFields ? null : null };
    // zero into soft: nothing
    const z = await open("gyp", modelFor("gyp", { gyp: GYP_ROWS() }), {});
    typeInto(z, "gyp_soft_sf", 0);
    settle(z);
    out.gypZero = { rows: rowsOf(z, GYP_TAB).map((r) => [r.bucket, r.measurement]) };
  }

  // ── 7. A COMBO JOB: the Polish boxes edit the root, the Epoxy boxes edit the Epoxy section ──────────────
  {
    const mk = () => modelFor("combo", { root: POLISH_ROWS(), epoxy: EPOXY_ROWS() });
    const draft = { polish_sf: 7000, system_1_sf: 1000, system_2_sf: 500, cove_1_lf: 120, cove_2_lf: 40 };
    const b = await open("combo", mk(), draft);
    out.comboPainted = shown(b);
    typeInto(b, "polish_sf", 9000);
    settle(b);
    out.comboPolish = { root: measuresOf(rowsOf(b, "Polish")), epoxy: measuresOf(rowsOf(b, "Epoxy")), draft: draftKeys(b) };
    typeInto(b, "system_1_sf", 3500);
    settle(b);
    out.comboEpoxy = { root: measuresOf(rowsOf(b, "Polish")), epoxy: measuresOf(rowsOf(b, "Epoxy")), draft: draftKeys(b) };
    // both at once, in ONE save
    const c = await open("combo", mk(), draft);
    typeInto(c, "polish_sf", 8000);
    typeInto(c, "system_2_sf", 650);
    settle(c);
    out.comboBoth = { root: measuresOf(rowsOf(c, "Polish")), epoxy: measuresOf(rowsOf(c, "Epoxy")), saves: c.rec.saves.length };
  }

  // ── 8. A POLISH JOB IS WHAT IT WAS: the root, polish_sf the priced area, polish_2_sf blank ─────────────
  {
    const b = await open("polish", { version: 2, takeoff: POLISH_ROWS().concat([
      { assembly_id: "asm-sp", assembly_name: "Dock", measurement: 3000, unit: "SF" }]), labor: clone(LABOR),
      conditions: { local: true, prevailing_wage: false, taxable: true, remodel_tax: false } }, { polish_sf: 7000, polish_2_sf: 3000 });
    out.polishPainted = shown(b);
    typeInto(b, "polish_sf", 8000);
    settle(b);
    out.polish = { rows: measuresOf(saved(b).takeoff), draft: draftKeys(b), hasTabs: saved(b).tabs !== undefined };
  }

  // ── 9. A BOX OF A SECTION THAT IS NOT PART OF THE BID WRITES NOTHING ────────────────────────────────────
  {
    // An Epoxy job's Polish root is off. A polish box typed (a leftover from another job type) must not reach it.
    const model = modelFor("epoxy", { root: POLISH_ROWS(), epoxy: EPOXY_ROWS() });
    const b = await open("epoxy", model, { polish_sf: 7000, system_1_sf: 1000 });
    typeInto(b, "polish_sf", 9999);
    settle(b);
    out.offRoot = { root: measuresOf(saved(b).takeoff), kind: saved(b).kind, epoxy: measuresOf(rowsOf(b, "Epoxy")) };
  }

  // ── 10. THE FLUSH BEFORE THE REPAINT: type, tab away inside the 600ms, and the figure survives ──────────
  {
    const b = await open("epoxy", modelFor("epoxy", { epoxy: EPOXY_ROWS() }), { system_1_sf: 1000, system_2_sf: 500, cove_1_lf: 120, cove_2_lf: 40 });
    typeInto(b, "system_1_sf", 2222);
    blurBox(b, "system_1_sf");                       // the timer has NOT fired yet
    const afterBlur = b.dom.fields.system_1_sf.value;
    settle(b);
    out.blurRace = { afterBlur, measures: measuresOf(rowsOf(b, "Epoxy")), shown: b.dom.fields.system_1_sf.value };
  }

  // ── 11. THE DOOR ITSELF (B.patchModel's boxes), with no page in front of it ─────────────────────────────
  {
    const m = modelFor("epoxy", { epoxy: EPOXY_ROWS() });
    const before = JSON.stringify(m);
    const epoxyRows = (x) => JSON.stringify(x.tabs.Epoxy.takeoff);
    const none = P.patchModel(m, { boxes: { cove_1_lf: 0, cove_2_lf: "", system_1_sf: 0, system_2_sf: -1 } });
    const typedModel = P.patchModel(m, { boxes: { system_1_sf: 4100, cove_1_lf: 150 } });
    const g = modelFor("gyp", { gyp: GYP_ROWS() });
    const gNone = P.patchModel(g, { boxes: { gyp_soft_sf: 0, gyp_hard_sf: "", gyp_corridor_sf: 0 } });
    // only one cove row measured: cove 2 ADDS the second, as System 2 adds the second area
    const oneCove = modelFor("epoxy", { epoxy: EPOXY_ROWS().slice(0, 3) });
    const addedCove = P.patchModel(oneCove, { boxes: { cove_2_lf: 30 } });
    // the sf_areas pair keeps meaning the two Polish boxes
    const p = modelFor("polish", { root: POLISH_ROWS() });
    const viaPair = P.patchModel(p, { sf_areas: [8100, 600] });
    out.direct = {
      zeroLeavesRows: epoxyRows(none) === epoxyRows(m), gypZeroLeavesRows: JSON.stringify(gNone.tabs[GYP_TAB].takeoff) === JSON.stringify(g.tabs[GYP_TAB].takeoff),
      pure: JSON.stringify(m) === before, moved: epoxyRows(typedModel) !== epoxyRows(m),
      typedMeasures: measuresOf(typedModel.tabs.Epoxy.takeoff), addedCove: addedCove.tabs.Epoxy.takeoff.filter((r) => r.unit === "LF").map((r) => r.measurement),
      pairRoot: measuresOf(viaPair.takeoff),
    };
  }

  // ── 12. A SECTION THAT WAS STARTED BUT NEVER MEASURED (the estimate page seeds a NEW section only) ───────────────────
  // The estimator opened the estimate before typing a floor, edited something (the section now holds Travel and a blank
  // takeoff row), went back to the intake and typed System 1. The estimate page will never seed that section again, so
  // the figure has to reach the takeoff from here.
  {
    const startedModel = (job, rows) => {
      const m = modelFor(job, {});
      const sec = job === "gyp" ? m.tabs[GYP_TAB] : m.tabs.Epoxy;
      sec.labor = clone(LABOR);
      if (rows) sec.takeoff = clone(rows);
      return m;
    };
    const BLANK_SF = () => [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }];
    const cells = (rows) => rows.map((r) => [r.assembly_id || "-", r.unit, r.measurement, r.enabled === false ? "off" : ""].join("|"));
    out.started = {};

    // System 1 alone
    const a = await open("epoxy", startedModel("epoxy", BLANK_SF()), {});
    typeInto(a, "system_1_sf", 5000);
    settle(a);
    out.started.sys1 = { rows: cells(rowsOf(a, "Epoxy")), draft: draftKeys(a), shown: shown(a).system_1_sf,
      isNew: P.isNewSection(saved(a).tabs.Epoxy, false) };

    // all four boxes, in ONE save
    const all = await open("epoxy", startedModel("epoxy", BLANK_SF()), {});
    typeInto(all, "system_1_sf", 5000);
    typeInto(all, "system_2_sf", 3000);
    typeInto(all, "cove_1_lf", 80);
    typeInto(all, "cove_2_lf", 40);
    settle(all);
    out.started.all = { sf: P.measuredSfValues(rowsOf(all, "Epoxy")), lf: P.measuredLfValues(rowsOf(all, "Epoxy")),
      count: rowsOf(all, "Epoxy").length, draft: draftKeys(all) };

    // a cove assembly already picked, its length not typed: the figure goes INTO it, no row is added beside it
    const COVE_PICKED = () => [{ assembly_id: "s3", assembly_name: "Cove E", measurement: "", unit: "LF" }];
    const picked = await open("epoxy", startedModel("epoxy", [
      { assembly_id: "s1", assembly_name: "System One", measurement: 1000, unit: "SF" }].concat(COVE_PICKED())), { system_1_sf: 1000 });
    typeInto(picked, "cove_1_lf", 150);
    settle(picked);
    out.started.picked = { rows: cells(rowsOf(picked, "Epoxy")), shown: shown(picked).cove_1_lf, lf: P.takeoffLf(rowsOf(picked, "Epoxy")) };

    // the same on a section nothing is measured in: the picked floor row and the picked cove row take the two figures
    const pickedBoth = await open("epoxy", startedModel("epoxy", [
      { assembly_id: "s1", assembly_name: "System One", measurement: "", unit: "SF" }].concat(COVE_PICKED())), {});
    typeInto(pickedBoth, "system_1_sf", 5000);
    typeInto(pickedBoth, "cove_1_lf", 150);
    settle(pickedBoth);
    out.started.pickedBoth = { rows: cells(rowsOf(pickedBoth, "Epoxy")) };

    // THE DEFAULTS OF A BID OPENED WITH NO FLOOR: two picked square-foot lines and a picked cove line, all blank. A new bid
    // seeds them as one floor (the first carries it, the other follows it, marked same_floor); so does this.
    const DEFAULTS = () => [
      { assembly_id: "s1", assembly_name: "System One", measurement: "", unit: "SF" },
      { assembly_id: "s3", assembly_name: "Cove E", measurement: "", unit: "LF" },
      { kind: "item", item_id: "e2", item_name: "Coat B", coverage: "", measurement: "", unit: "SF" },
    ];
    const marks = (rows) => rows.map((r) => [r.assembly_id || r.item_id || "-", r.unit, r.measurement,
      r.floor_area ? "area" + r.floor_area : "", r.same_floor ? "of" + r.same_floor_of : ""].join("|"));
    const d1 = await open("epoxy", startedModel("epoxy", DEFAULTS()), {});
    typeInto(d1, "system_1_sf", 5000);
    settle(d1);
    out.started.defaults1 = { rows: marks(rowsOf(d1, "Epoxy")), priced: P.takeoffSf(rowsOf(d1, "Epoxy")),
      sf: P.measuredSfValues(rowsOf(d1, "Epoxy")) };
    const d2 = await open("epoxy", startedModel("epoxy", DEFAULTS()), {});
    typeInto(d2, "system_1_sf", 5000);
    typeInto(d2, "system_2_sf", 3000);
    typeInto(d2, "cove_1_lf", 150);
    settle(d2);
    // what a NEW bid is given for the same library and the same two floors (the lines the intake just made are these)
    const fresh = P.seedDefaultTakeoff([{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }],
      [{ id: "s1", name: "System One", unit: "SF", favorite: true, default_work_types: [] },
       { id: "s3", name: "Cove E", unit: "LF", favorite: true, default_work_types: [] }],
      [{ id: "e2", name: "Coat B", coverage_basis: "SF", favorite: true, default_work_types: [] }], [], 5000, 3000, "epoxy");
    out.started.defaults2 = { rows: marks(rowsOf(d2, "Epoxy")), priced: P.takeoffSf(rowsOf(d2, "Epoxy")),
      sf: P.measuredSfValues(rowsOf(d2, "Epoxy")), lf: P.takeoffLf(rowsOf(d2, "Epoxy")), fresh: marks(fresh) };

    // a picked row is preferred to a bare one, and a row that is switched off never carries the floor
    const prefer = await open("epoxy", startedModel("epoxy", [
      { assembly_id: "s1", assembly_name: "System One", measurement: 1000, unit: "SF" },
      { assembly_id: "", assembly_name: "", measurement: "", unit: "LF" }].concat(COVE_PICKED())), { system_1_sf: 1000 });
    typeInto(prefer, "cove_1_lf", 150);
    settle(prefer);
    out.started.prefer = { rows: cells(rowsOf(prefer, "Epoxy")) };
    const off = await open("epoxy", startedModel("epoxy", [
      { assembly_id: "s1", assembly_name: "System One", measurement: "", unit: "SF", enabled: false }]), {});
    typeInto(off, "system_1_sf", 900);
    settle(off);
    out.started.off = { rows: cells(rowsOf(off, "Epoxy")) };

    // Cove 2 goes BELOW Cove 1: a blank picked row above the measured one is not filled (it would swap the two boxes)
    const second = await open("epoxy", startedModel("epoxy", [
      { assembly_id: "s1", assembly_name: "System One", measurement: 1000, unit: "SF" }].concat(COVE_PICKED(),
      [{ assembly_id: "s4", assembly_name: "Cove F", measurement: 120, unit: "LF" }])), { system_1_sf: 1000 });
    typeInto(second, "cove_2_lf", 40);
    settle(second);
    out.started.second = { rows: cells(rowsOf(second, "Epoxy")), lf: P.measuredLfValues(rowsOf(second, "Epoxy")),
      shown: [shown(second).cove_1_lf, shown(second).cove_2_lf] };

    // Cove 2 typed when no cove is measured: the figure is counted ONCE and reads back as the first length
    const lone = await open("epoxy", startedModel("epoxy", [
      { assembly_id: "s1", assembly_name: "System One", measurement: 1000, unit: "SF" }]), { system_1_sf: 1000 });
    typeInto(lone, "cove_2_lf", 123);
    settle(lone);
    out.started.lone = { lf: P.takeoffLf(rowsOf(lone, "Epoxy")), values: P.measuredLfValues(rowsOf(lone, "Epoxy")) };

    // a started Gyp section: each box is its own area
    const g = await open("gyp", startedModel("gyp"), {});
    typeInto(g, "gyp_soft_sf", 4000);
    typeInto(g, "gyp_hard_sf", 2000);
    settle(g);
    out.started.gyp = { areas: rowsOf(g, GYP_TAB).filter((r) => P.num(r.measurement) > 0).map((r) => [r.bucket, r.measurement]),
      draft: draftKeys(g) };

    // a Combo bid: the Epoxy half was started and never measured, the Polish root is measured and stays as it is
    const cm = modelFor("combo", { root: POLISH_ROWS() });
    cm.tabs.Epoxy.labor = clone(LABOR);
    const cb = await open("combo", cm, { polish_sf: 7000 });
    typeInto(cb, "system_1_sf", 5000);
    settle(cb);
    out.started.combo = { epoxy: cells(rowsOf(cb, "Epoxy")), root: measuresOf(rowsOf(cb, "Polish")) };

    // the root is left to the estimate page even when nothing is measured: it seeds the library's default takeoff,
    // which a figure written here first would stop
    const root = await open("polish", null, {});
    typeInto(root, "polish_sf", 5000);
    settle(root);
    out.started.root = { rows: cells(saved(root).takeoff), draft: draftKeys(root).p1 };
  }

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
`;

const m = new Module(BASE, module);
m.filename = BASE;
m.paths = Module._nodeModulePaths(path.dirname(BASE));
m._compile(head + SCENARIOS, BASE);
