#!/usr/bin/env node
"use strict";
/* THE GYP JOBS, RECORDED FROM KYLE'S WORKBOOK. The answer key for what the v2 Gyp takeoff has to price.
 *
 *   node backend/tests/js/gyp-jobs-recorder.js            compare with the recorded file
 *   node backend/tests/js/gyp-jobs-recorder.js --write    rewrite it
 *
 * The workbook oracle (workbook-oracle.js) types numbers into the BOUNDARY of each tab's markup chain (gypsum,
 * extras, sand, sound mat, its rolls), so it proves the chain and says nothing about how a takeoff arrives at those
 * figures. This is the other half: it types a JOB into each of the five Gyp tabs (the three areas, a thickness for
 * each, the mix, ISO strip at all areas, the sound mat, moisture tests), lets the workbook price it, and records the
 * cells that matter. The v2 path has to arrive at the same figures from the library rows backend/ops/
 * seed_library_from_workbook.py plans (tests/js/gyp-v2-proof-harness.js, tests/test_gyp_v2_proof.py).
 *
 * NEEDS hyperformula@2.7.1 (see workbook-oracle.js):
 *     npm i --no-save --prefix <scratch dir> hyperformula@2.7.1
 *     NODE_PATH=<scratch dir>/node_modules node backend/tests/js/gyp-jobs-recorder.js --write
 * CI never runs it. CI compares the recorded file with the template (a hash of the five Gyp tabs and of every defined
 * name) and with the code, so a template edit says "re-run the recorder".
 *
 * The cases are lists, never random, so two runs write the same bytes.
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");

const HERE = __dirname;
const REPO = path.resolve(HERE, "..", "..", "..");
const E = require(path.join(REPO, "docs", "excel-parity-audit", "engine.js"));
const SUPPORT = path.join(HERE, "..", "_oracle_support.py");
const OUT = path.join(HERE, "..", "fixtures", "gyp_jobs_golden.json");
const SCHEMA = 1;

const FIRST = 'Gyp (USG 1-8")';
const TABS = [FIRST, "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", "Gyp (FR)"];

// Where each tab keeps what a job types. The area table is P3:R27 on four tabs and O3:Q27 on Gyp (FR), which is built
// one column further left; the sound-mat table follows (O37:O44 against N37:N44). Thickness, mix and ISO are in the
// same cells on all five.
const LAYOUT = {
  usg: { soft: "P3", hard: "Q3", corridor: "R3", matNames: ["O37", "O38", "O39", "O40", "O42", "O43", "O44"] },
  fr: { soft: "O3", hard: "P3", corridor: "Q3", matNames: ["N37", "N38", "N39", "N42", "N43", "N44"] },
};
const layoutOf = (tab) => (tab === "Gyp (FR)" ? LAYOUT.fr : LAYOUT.usg);

function fail(message) {
  console.error(message);
  process.exit(1);
}

function python(args) {
  const exe = process.platform === "win32" ? "python" : "python3";
  const r = cp.spawnSync(exe, [SUPPORT].concat(args), { encoding: "utf8", maxBuffer: 512 * 1024 * 1024 });
  if (r.error || r.status !== 0) fail("could not run " + exe + " " + SUPPORT + "\n" + (r.error ? String(r.error) : r.stderr));
  return r.stdout;
}

function loadSpec() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-gyp-jobs-"));
  const file = path.join(dir, "spec.json");
  try {
    python(["--spec", file]);
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function templateHash() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-gyp-jobs-"));
  const file = path.join(dir, "sheets.json");
  try {
    fs.writeFileSync(file, JSON.stringify(TABS));
    return JSON.parse(python(["--hash", file]));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// ── the cases ────────────────────────────────────────────────────────────────
/** What a case may say. Every field is optional; what a case leaves out stays as the template ships it.
 *    soft, hard, corr   the three areas, in SF           thick   {soft, hard, corridor} inches (blank: the tab's own)
 *    mix                1.8 or 1.4                       isoAll  true for "ISO Strip at All Areas: Yes"
 *    mat                the index of the sound mat in the tab's table      moisture   moisture tests typed */
const FIELDS = ["soft", "hard", "corr", "thick", "mix", "isoAll", "mat", "moisture"];

function buildCases(matsOf) {
  const cases = [];
  const add = (tab, id, spec) => cases.push({ id: tab + "/" + id, tab: tab, in: spec });
  TABS.forEach((tab) => {
    const mats = matsOf(tab);
    // each area alone, then together, at sizes either side of the CEILINGs the bags and rolls do not have
    [1000, 2500, 12345, 60000, 250000].forEach((sf) => {
      add(tab, "soft/" + sf, { soft: sf });
      add(tab, "hard/" + sf, { hard: sf });
      add(tab, "corridor/" + sf, { corr: sf });
      add(tab, "all/" + sf, { soft: sf, hard: Math.round(sf * 0.6), corr: Math.round(sf * 0.25) });
    });
    // every thickness a job pours, on each area, at a 2500 psi mix and at a 3000 psi one
    [0.125, 0.25, 0.375, 0.5, 0.75, 1, 1.25, 1.5, 2, 3].forEach((t) => {
      [1.8, 1.4].forEach((mix) => {
        add(tab, "thick/" + t + "/mix" + mix, { soft: 5000, hard: 4000, corr: 1500, thick: { soft: t, hard: t, corridor: t }, mix: mix });
      });
    });
    // a different thickness in each area
    add(tab, "thick/mixed-a", { soft: 8000, hard: 6000, corr: 2000, thick: { soft: 1.5, hard: 0.5, corridor: 0.25 } });
    add(tab, "thick/mixed-b", { soft: 8000, hard: 6000, corr: 2000, thick: { soft: 0.375, hard: 2, corridor: 1.25 }, mix: 1.4 });
    // ISO strip at every area, and the default (hard surfaces only)
    add(tab, "iso/all", { soft: 9000, hard: 7000, corr: 2000, isoAll: true });
    add(tab, "iso/hard", { soft: 9000, hard: 7000, corr: 2000 });
    // moisture tests typed
    [0, 1, 3, 12].forEach((n) => add(tab, "moisture/" + n, { soft: 4000, hard: 2000, moisture: n }));
    // every sound mat the tab offers, over a hard area big enough to need several rolls
    mats.forEach((m, i) => {
      add(tab, "mat/" + i, { soft: 6000, hard: 52000, corr: 1000, mat: i });
      // the roll count either side of a truckload (odd rule 6): the SF that makes exactly truckload - 1, truckload and
      // truckload + 1 rolls, worked out below once the workbook has said what a roll covers and a truckload is
      [-1, 0, 1].forEach((d) => add(tab, "truck/" + i + "/" + (d < 0 ? "below" : d === 0 ? "at" : "above"),
        { soft: 3000, hard: { rollsFor: d, mat: i }, corr: 500, mat: i }));
    });
    // whole jobs
    add(tab, "job/1", { soft: 18400, hard: 9200, corr: 3100, thick: { soft: 0.75, hard: 0.75, corridor: 0.75 } });
    add(tab, "job/2", { soft: 31000, hard: 14000, corr: 6200, thick: { soft: 1, hard: 0.5, corridor: 1 }, mix: 1.4, isoAll: true, moisture: 4 });
    add(tab, "job/3", { soft: 700, hard: 450, corr: 120 });
    add(tab, "job/4", { soft: 123456, hard: 76543, corr: 21098, mat: Math.min(3, mats.length - 1) });
    // nothing measured
    add(tab, "empty/none", {});
  });
  return cases;
}

// ── driving the workbook ─────────────────────────────────────────────────────
const norm = (t) => String(t).replace(/\s+/g, " ").trim();

function main() {
  const args = process.argv.slice(2);
  const write = args.includes("--write");
  const hfFile = E.hyperformulaPath();
  const shipped = E.assertShippedBytes(hfFile);
  const HF = E.loadEngine({ plugin: true });
  const spec = loadSpec();
  const wb = E.build(HF, spec);
  if (wb.warnings.length) fail("the workbook did not load cleanly:\n  " + wb.warnings.join("\n  "));

  const matLabels = (tab) => layoutOf(tab).matNames.map((a) => {
    const v = wb.getPlain(tab, a);
    if (typeof v !== "string" || !v) fail(tab + "!" + a + " should name a sound mat, found " + JSON.stringify(v));
    return v;
  });
  const cases = buildCases((tab) => matLabels(tab));
  const seen = new Set();
  cases.forEach((c) => { if (seen.has(c.id)) fail("two cases are called " + c.id); seen.add(c.id); });
  Object.keys(cases.reduce((a, c) => Object.assign(a, c.in), {})).forEach((k) => {
    if (FIELDS.indexOf(k) < 0) fail("a case names a field the recorder does not know: " + k);
  });

  const originals = new Map();
  const original = (tab, addr) => {
    const key = tab + "!" + addr;
    if (!originals.has(key)) { const v = wb.serialized(tab, addr); originals.set(key, v === undefined ? null : v); }
    return originals.get(key);
  };
  const plain = (tab, addr) => { const v = wb.getPlain(tab, addr); return typeof v === "number" ? v : 0; };

  // what a roll covers and a truckload is, per tab and mat, read from the workbook before any case changes it
  const sfPerRoll = (tab, i) => {
    const row = [37, 38, 39, 40, 42, 43, 44];
    const frRow = [37, 38, 39, 42, 43, 44];
    return tab === "Gyp (FR)" ? wb.getPlain(tab, "P" + frRow[i]) : wb.getPlain(tab, "Q" + row[i]);
  };

  cases.forEach((c) => {
    const tab = c.tab;
    const L = layoutOf(tab);
    const spec1 = c.in;
    const touched = [];
    const put = (addr, v) => { original(tab, addr); wb.set(tab, addr, v); touched.push(addr); };
    const mats = matLabels(tab);
    const mat = spec1.mat === undefined ? null : spec1.mat;
    if (mat !== null) put("A36", mats[mat]);
    // the hard area that makes a given number of rolls: the smallest SF whose roll count is truckload + d
    let hard = spec1.hard;
    if (hard && typeof hard === "object") {
      put("A36", mats[hard.mat]);
      const truck = wb.getPlain(tab, "H36");
      const per = sfPerRoll(tab, hard.mat);
      const want = truck + hard.rollsFor;
      hard = Math.ceil(((want - 1) * per) / 1.04) + 1;           // just past the edge of want - 1 rolls
      while (Math.ceil((hard / per) * 1.04 - 1e-12) < want) hard += 1;
      while (Math.ceil(((hard - 1) / per) * 1.04 - 1e-12) >= want) hard -= 1;
      c.in = Object.assign({}, spec1, { hard: hard });
    }
    if (spec1.soft !== undefined) put(L.soft, spec1.soft);
    if (hard !== undefined) put(L.hard, hard);
    if (spec1.corr !== undefined) put(L.corridor, spec1.corr);
    if (spec1.thick) {
      if (spec1.thick.soft !== undefined) put("G10", spec1.thick.soft);
      if (spec1.thick.hard !== undefined) put("I10", spec1.thick.hard);
      if (spec1.thick.corridor !== undefined) put("K10", spec1.thick.corridor);
    }
    if (spec1.mix !== undefined) put("G11", spec1.mix);
    if (spec1.isoAll) put("B14", "Yes");
    if (spec1.moisture !== undefined) put("B57", spec1.moisture);

    const out = {
      D36: wb.getPlain(tab, "D36"), B36: plain(tab, "B36"), H36: wb.getPlain(tab, "H36"),
      E36: plain(tab, "E36"), H33: plain(tab, "H33"), B33: plain(tab, "B33"), E33: plain(tab, "E33"),
      E38: plain(tab, "E38"), E39: plain(tab, "E39"), E40: plain(tab, "E40"), E41: plain(tab, "E41"),
      E52: plain(tab, "E52"), E61: plain(tab, "E61"), E69: plain(tab, "E69"), E72: plain(tab, "E72"),
      E81: plain(tab, "E81"), E87: plain(tab, "E87"),
    };
    // the cells the sheet sums into the chain's figures, unrounded
    out.gyp = [20, 21, 22, 23, 24, 25, 26].reduce((t, r) => t + plain(tab, "E" + r), 0);
    out.extras = [27, 28, 29, 30, 31].reduce((t, r) => t + plain(tab, "E" + r), 0);
    out.bags = { soft: plain(tab, "B23"), hard: plain(tab, "B24"), corridor: plain(tab, "B25") };
    out.hours = { prePour: plain(tab, "B45"), prep: plain(tab, "B46"), mat: plain(tab, "B47"), pour: plain(tab, "B48"),
      unload: plain(tab, "B49"), travel: plain(tab, "B51") };
    out.areas = { soft: plain(tab, "F23"), hard: plain(tab, "F24"), corridor: plain(tab, "F25") };
    c.out = out;
    touched.forEach((addr) => wb.set(tab, addr, original(tab, addr)));
  });

  const doc = {
    schema: SCHEMA, generator: "backend/tests/js/gyp-jobs-recorder.js", tabs: TABS,
    about: "Gyp jobs typed into each of Kyle's five Gyp tabs (three areas, a thickness for each, the mix, ISO strip at all " +
      "areas, the sound mat, moisture tests) and what the workbook answered. `gyp` is the sum of E20:E26, `extras` of " +
      "E27:E31, before E38 rounds the material. Written by the recorder; CI compares the v2 path with it " +
      "(tests/test_gyp_v2_proof.py) and checks the template has not moved since (hash).",
    engine: { hyperformula: { version: shipped.version, sri: shipped.sri } },
    template: templateHash(),
    cases: cases,
  };
  const text = "{\n" + ["schema", "generator", "tabs", "about", "engine", "template"].map((k) => JSON.stringify(k) + ": " + JSON.stringify(doc[k])).join(",\n") +
    ",\n\"cases\": [\n" + cases.map((c) => JSON.stringify(c)).join(",\n") + "\n]\n}\n";
  if (write) {
    fs.writeFileSync(OUT, text);
    console.log("wrote " + path.relative(REPO, OUT) + ": " + cases.length + " cases");
  } else {
    const have = fs.existsSync(OUT) ? fs.readFileSync(OUT, "utf8").replace(/\r\n/g, "\n") : "";
    if (have === text) console.log("the recorded file is current: " + cases.length + " cases");
    else { console.error("the recorded file differs from what the workbook answers now: re-run with --write and read the diff"); process.exit(1); }
  }
}

main();
