"use strict";
/* WHAT THE ESTIMATE PAGE WRITES, recorded whole, so the multi-section change can be shown to leave a
 * single-Polish bid's save exactly as it was.
 *
 * Phase 10 of the v2 estimating program moves two things into the model: the new-bid seeding the page's
 * init() used to do inline (seedNewSections) and the composition of the derived keys a save writes
 * (composePricingSnapshot, behind buildSavePatch). Neither may change a byte of what a Polish bid saves or
 * what a new Polish bid opens holding. This harness runs the REAL page (polish-estimate.js, whole, through
 * polish-estimate-harness.js's own boot code, the same way saved-bid-harness.js does) and prints, as one
 * line of JSON:
 *
 *   saved     every saved-bid fixture the ratchet pins (saved-bid-scenarios.js, lifted from it by name):
 *             opened, then saved once by the 600 ms timer and once by `pagehide`, the WHOLE blob each wrote
 *   newBid    a brand new bid, opened over a library full of defaults and over an empty one, with intake's
 *             two SF boxes, with intake's condition cells, and as the beta intake mints it: the model the
 *             page holds after init() and the blob its first save writes
 *
 * test_v2_multi_section.py compares this output with fixtures/save_patch_golden.json, which was captured
 * from the code BEFORE the change (see its `meta`), key order included.
 *
 * Usage: node save-patch-golden-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");

const BASE = path.join(__dirname, "polish-estimate-harness.js");
const norm = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

let code = norm(BASE);
const MARK = "(async function () {\n  // ── A. the takeoff row";
const at = code.indexOf(MARK);
if (at < 0) throw new Error("polish-estimate-harness.js scenario block moved; update the marker");
let head = code.slice(0, at);
head = head.replace(/const EXPORTS = `[\s\S]*?`;\n/,
  "const EXPORTS = `\n  return { init: init, bid: bid, saveSoon: saveSoon, model: function () { return M; }, state: function () { return state; } };\n`;\n");

// The ratchet's own fixtures (everything above its own main), so a fixture added there is covered here.
const SCEN = norm(path.join(__dirname, "saved-bid-scenarios.js"));
const MAIN = "(async function () {\n  const out = { fixtures: {}";
const cut = SCEN.indexOf(MAIN);
if (cut < 0) throw new Error("saved-bid-scenarios.js main moved; update the marker");

const MINE = `
const setAside = (v) => JSON.parse(JSON.stringify(v));

/** One page, opened and saved two ways from the same blob. */
async function savedTwoWays(f, lib) {
  const open = async () => {
    const b = build(Object.assign({ blob: savedBlob(f) }, lib || {}, answerFor(f), f.opts || {}));
    await b.api.init();
    return b;
  };
  const a = await open();
  a.api.saveSoon();
  a.clock.fire();
  const p = await open();
  p.api.saveSoon();
  p.win.fire("pagehide");
  return { autosave: a.rec.saves[a.rec.saves.length - 1] || null,
           pagehide: p.rec.saves[p.rec.saves.length - 1] || null,
           flushed: p.rec.flushed };
}

/** A new bid: the model the page holds once init() has run, and what its first save writes. Its city and state are enough to ask
 *  the distance since 2026-10-22 (Hanz); the lookup does not answer here (UNANSWERED, saved-bid-scenarios.js), because this golden
 *  pins what a save writes, not the distance, whose answer tests/test_polish_distance_approx.py holds. */
async function newBid(over, opts) {
  const nb = blob(over || {});
  delete nb.polish_estimate;
  const b = build(Object.assign({ blob: nb }, opts || {}, { distance: UNANSWERED }));
  await b.api.init();
  for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
  const model = setAside(b.api.model());
  b.api.saveSoon();
  b.clock.fire();
  return { model: model, bid: setAside(b.api.bid()), saved: b.rec.saves[b.rec.saves.length - 1] || null,
           savesBeforeEdit: b.rec.saves.length };
}

(async function () {
  const out = { saved: {}, newBid: {} };
  const ALL = Object.assign({}, FIXTURES, NEWEST);
  for (const name of Object.keys(ALL)) {
    out.saved[name] = await savedTwoWays(ALL[name]);
    out.saved[name + "__library"] = await savedTwoWays(ALL[name], LIBRARY_ON);
  }
  out.newBid.library = await newBid({ polish_sf: 10000 }, LIBRARY_ON);
  out.newBid.empty = await newBid({ polish_sf: 10000 });
  out.newBid.twoSystems = await newBid({ polish_sf: 8250, polish_2_sf: 1000 }, LIBRARY_ON);
  out.newBid.conditionCells = await newBid({ polish_sf: 10000,
    cell_values: { "Polish!B6": "no", "Polish!D5": "Yes", "Polish!B4": "no", "Polish!E29": "No" } }, LIBRARY_ON);
  out.newBid.noSf = await newBid({ polish_sf: "" }, LIBRARY_ON);
  // a SAVED bid (it states labor) whose takeoff is blank: only intake's SF box seeds it, never the library's
  // default takeoff, whatever library is on offer (this is what tells the two gates apart)
  {
    const sv = blob({ polish_sf: 9000, polish_estimate: staged({
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }] }) });
    // A saved bid with no distance asks on open since 2026-10-22; here the lookup does not answer (see newBid above).
    const b = build(Object.assign({ blob: sv }, LIBRARY_ON, { distance: UNANSWERED }));
    await b.api.init();
    for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
    const model = setAside(b.api.model());
    b.api.saveSoon();
    b.clock.fire();
    out.newBid.savedEmptyTakeoff = { model: model, bid: setAside(b.api.bid()),
      saved: b.rec.saves[b.rec.saves.length - 1] || null };
  }
  // the beta intake mints a model with conditions and one blank takeoff row and deletes its labor
  {
    const nb = blob({ polish_sf: 9000,
      polish_estimate: { version: 2, takeoff: [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }],
                         conditions: { local: false, taxable: true, remodel_tax: true, prevailing_wage: true },
                         conditions_shown: { dye: false }, totals: {} } });
    const b = build({ blob: nb, labor: LIBRARY_ON.labor, laborCalc: LIBRARY_ON.laborCalc,
                      markupRules: LIBRARY_ON.markupRules, conditionDefaults: LIBRARY_ON.conditionDefaults,
                      asms: LIBRARY_ON.asms });
    await b.api.init();
    for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
    const model = setAside(b.api.model());
    b.api.saveSoon();
    b.clock.fire();
    out.newBid.mintedByIntake = { model: model, bid: setAside(b.api.bid()),
      saved: b.rec.saves[b.rec.saves.length - 1] || null };
  }
  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
`;

const m = new Module(BASE, module);
m.filename = BASE;
m.paths = Module._nodeModulePaths(path.dirname(BASE));
m._compile(head + SCEN.slice(0, cut) + MINE, BASE);
