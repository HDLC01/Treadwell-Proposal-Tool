"use strict";
/* THE RENOVATION LABEL ON THE REAL ESTIMATE PAGE: js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it, on
 * the library backend/ops/seed_library_from_workbook.py plans, with the REAL js/bid-model.js, library-core.js and seal-takeoff.js beneath it.
 *
 * Hanz, 2026-10-21: "there must be a label that we could just identify if its a renovation job to fix the lump sum difference we had for
 * polish". Kyle's sheet prices the patch at C17 = IF(B10="New",0.05,0.15); v2 had no way to say Reno, so the recorded Jayhawk Polish job
 * (B10 blank, so Reno on the sheet) came to $31,840 against the sheet's $32,864. Every fact below is read off the page after it ran.
 *
 * Usage: node renovation-label-harness.js <frontend-dir> <plan.json> <recorded_job.json>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const plan = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const job = JSON.parse(fs.readFileSync(process.argv[4], "utf8"));
const B = require(path.join(ROOT, "js", "bid-model.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in renovation-label-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}
const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "clickEl", "need"]);

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 12; i++) await flush(); };
const panel = (b) => b.doc.getElementById("sheets-panel").innerHTML;
const panels = (b) => b.doc.getElementById("panels").innerHTML;
const RENO_CELLS = ["Epoxy!B10", "Polish!B10", "Seal!B10"];
const cellsOf = (blob) => Object.fromEntries(RENO_CELLS.map((c) => [c, ((blob && blob.cell_values) || {})[c]]));

const norm = (t) => String(t).replace(/\s+/g, " ").trim();
const byName = new Map(plan.assemblies.map((a) => [norm(a.name), a]));
function asmNamed(name) {
  const hit = byName.get(norm(name));
  if (!hit) throw new Error("the library has no assembly called " + name);
  return hit;
}

/** The recorded Polish job as v2 holds it: the inputs recorded-job-parity-harness.js prices through the engines, as a page draft. */
function jayhawkDraft(extra) {
  const spec = job.polish.in;
  const m = B.freshModel();
  m.profile = "polish-rev3@1";
  m.conditions = Object.assign({}, m.conditions, { taxable: true, remodel_tax: true, prevailing_wage: false, local: true,
    dye: !!spec.dye, joint_filler: !!spec.joint_filler });
  const asm = asmNamed(spec.system);
  m.takeoff = [{ assembly_id: asm.id, assembly_name: asm.name, measurement: spec.sf, unit: "SF" }];
  m.labor = spec.labor.map((l) => ({ id: l.id, label: l.label, guys: l.guys, days: l.days, rate: spec.rate, unit: "days" }));
  return P.blob(Object.assign({ work_type: "polish", polish_sf: spec.sf, polish_estimate: m, remodel_rate_override: spec.remodel_rate }, extra || {}));
}

async function open(blob) {
  const b = P.build({ blob: blob, items: clone(plan.items), asms: clone(plan.assemblies) });
  await b.api.init();
  await settle();
  return b;
}

/** Every element the page focuses through document.querySelector from now on (refocus), as the selector it asked for. */
function watchRefocus(b) {
  const got = [];
  const real = b.doc.querySelector.bind(b.doc);
  b.doc.querySelector = (s) => { const el = real(s); if (el) el.focus = () => { got.push(s); }; return el; };
  return got;
}

const swOf = (b) => b.doc.querySelector("[data-reno-sw]");
const facts = (b) => {
  const sw = swOf(b);
  return {
    total: b.api.bid().total,
    patch: b.api.bid().patch,
    card: panels(b).indexOf('data-reno-card="1"') >= 0,
    on: sw ? sw.getAttribute("aria-checked") === "true" : null,
    tag: /<span class="pill reno"[^>]*>Renovation<\/span>/.test(panel(b)),
  };
};

async function jayhawk() {
  const b = await open(jayhawkDraft());
  b.api.go(0);
  await settle();
  const off = facts(b);
  const focused = watchRefocus(b);
  P.clickEl(b, swOf(b));
  await settle();
  const on = Object.assign(facts(b), { refocused: focused.splice(0) });
  b.clock.fire();
  const saved = clone(b.store.blob);
  // a reload of what was saved: the label is the draft's, so it comes back
  const r = await open(saved);
  r.api.go(0);
  await settle();
  const reopened = Object.assign(facts(r), { cells: cellsOf(r.store.blob) });
  // Space presses it, as every switch on the page
  const sw = swOf(r);
  // the stand-in DOM's elements have no click(); a browser's dispatches a click on the element, and so does this one
  if (sw) sw.click = () => P.clickEl(r, sw);
  let prevented = false;
  r.doc.fire("keydown", { target: sw, key: " ", preventDefault() { prevented = true; } });
  await settle();
  const back = Object.assign(facts(r), { prevented: prevented });
  r.clock.fire();
  const savedBack = clone(r.store.blob);
  return {
    off: off, on: on, savedCells: cellsOf(saved), reopened: reopened, back: back, backCells: cellsOf(savedBack),
    recorded: job.polish.sheet.total,
  };
}

/** Drafts as the live intake and the AI autofill leave them: the answer is already in the cells, and the page reads it as it always did. */
async function arrived() {
  const one = async (cells) => {
    const b = await open(jayhawkDraft(cells === null ? {} : { cell_values: cells }));
    b.api.go(0);
    await settle();
    const f = facts(b);
    b.clock.fire();
    return Object.assign(f, { savedCells: cellsOf(b.store.blob) });
  };
  return { reno: await one({ "Polish!B10": "Reno" }), renoOnEpoxyOnly: await one({ "Epoxy!B10": "Reno" }), fresh: await one({ "Polish!B10": "New" }),
           none: await one(null) };
}

/** The other sheets: a Seal option prices its own patch by the label, and shows the switch; an Epoxy sheet has no patch it moves and no
 *  switch. The tag is the job's, so it is on every sheet's bar and on every step. */
async function sheets() {
  const b = await open(jayhawkDraft());
  const addSheet = async (sheet) => {
    const menu = b.doc.querySelector('[data-sh-act="add-menu"]');
    if (menu) P.clickEl(b, menu);
    const pickEl = b.doc.querySelector('[data-sh-act="add"][data-sh-sheet="' + sheet + '"]');
    if (pickEl) P.clickEl(b, pickEl);
    await settle();
  };
  await addSheet("Seal");
  const sealTab = Object.keys(b.api.root().tabs || {}).filter((k) => /^Seal/.test(k) || ((b.api.root().tabs[k] || {}).sheet || "").indexOf("Seal") === 0)[0] || null;
  b.api.go(0);
  await settle();
  const sealBids = () => (sealTab ? (b.api.sectionBids()[sealTab] || {}).total : null);
  const sealOff = { card: panels(b).indexOf('data-reno-card="1"') >= 0, total: sealBids() };
  const sw = swOf(b);
  if (sw) P.clickEl(b, sw);
  await settle();
  const sealOn = { card: panels(b).indexOf('data-reno-card="1"') >= 0, total: sealBids(), tag: /<span class="pill reno"/.test(panel(b)) };
  await addSheet("Epoxy");
  b.api.go(0);
  await settle();
  const epoxy = { card: panels(b).indexOf('data-reno-card="1"') >= 0, tag: /<span class="pill reno"/.test(panel(b)) };
  b.api.go(1);
  await settle();
  const labor = { tag: /<span class="pill reno"/.test(panel(b)) };
  b.api.show(B.ROOT_TAB);
  b.api.go(2);
  await settle();
  const review = { tag: /<span class="pill reno"/.test(panel(b)), renoRate: panels(b).indexOf("renovation rate") >= 0, newRate: panels(b).indexOf("new concrete rate") >= 0 };
  return { sealTab: sealTab, sealOff: sealOff, sealOn: sealOn, epoxy: epoxy, labor: labor, review: review };
}

async function main() {
  const out = {};
  for (const [name, fn] of [["jayhawk", jayhawk], ["arrived", arrived], ["sheets", sheets]]) {
    try { out[name] = await fn(); } catch (e) { out[name] = { error: String(e && e.stack || e) }; }
  }
  return out;
}

main().then((o) => { process.stdout.write(JSON.stringify(o) + "\n"); }).catch((e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
