#!/usr/bin/env node
"use strict";
/* THE SEAL JOBS, RECORDED FROM KYLE'S WORKBOOK. The answer key for what the v2 Seal option has to price.
 *
 *   node backend/tests/js/seal-jobs-recorder.js            compare with the recorded file
 *   node backend/tests/js/seal-jobs-recorder.js --write    rewrite it
 *
 * The workbook oracle (workbook-oracle.js) types numbers into the BOUNDARY of each tab's markup chain (material,
 * labor, tooling), so it proves the chain and says nothing about how a takeoff arrives at those figures. This is the
 * other half, for the two Seal tabs: it types a JOB into Seal and Seal (+Jnts) (the area, New or Reno, one coat of
 * sealer or two, joint filler on or off, the days of the crew), lets the workbook price it, and records the cells that
 * matter. The v2 path has to arrive at the same figures from the library rows backend/ops/seed_library_from_workbook.py
 * plans and the formulas of js/seal-takeoff.js (tests/js/seal-v2-proof-harness.js, tests/test_seal_v2_proof.py).
 *
 * NEEDS hyperformula@2.7.1 (see workbook-oracle.js):
 *     npm i --no-save --prefix <scratch dir> hyperformula@2.7.1
 *     NODE_PATH=<scratch dir>/node_modules node backend/tests/js/seal-jobs-recorder.js --write
 * CI never runs it. CI compares the recorded file with the template (a hash of the two Seal tabs and of every defined
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
const OUT = path.join(HERE, "..", "fixtures", "seal_jobs_golden.json");
const SCHEMA = 1;

const TABS = ["Seal", "Seal (+Jnts)"];

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-seal-jobs-"));
  const file = path.join(dir, "spec.json");
  try {
    python(["--spec", file]);
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function templateHash() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-seal-jobs-"));
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
 *    sf       the area (Seal!E18; Seal (+Jnts) reads it from there)
 *    reno     true types "Reno" into Seal!B10; anything else types "New" (the cell is always typed, see below)
 *    coats    1 zeroes the second sealer line (B21) of the tab that is read; 2 is the sheet as it ships
 *    jf       true or false types Yes or No into E29 of the tab that is read (Seal ships No, Seal (+Jnts) Yes)
 *    days     the days of the first crew line (Seal!B37) */
const FIELDS = ["sf", "reno", "coats", "jf", "days"];

function buildCases() {
  const cases = [];
  const add = (tab, id, spec) => cases.push({ id: tab + "/" + id, tab: tab, in: spec });
  const SFS = [500, 1000, 2500, 3499, 3500, 3501, 7000, 12345, 20000, 45000, 90000, 250000];
  TABS.forEach((tab) => {
    // the ordinary job, at sizes either side of the joint filler's 3,500 SF and the tooling's $150 floor
    SFS.forEach((sf) => [false, true].forEach((reno) => add(tab, "sf/" + sf + (reno ? "/reno" : "/new"), { sf: sf, reno: reno })));
    // one coat of sealer instead of two (Clean + Seal)
    [1000, 3501, 12345, 90000].forEach((sf) => [false, true].forEach((reno) =>
      add(tab, "coats1/" + sf + (reno ? "/reno" : "/new"), { sf: sf, reno: reno, coats: 1 })));
    // the joint filler switched the other way from how the tab ships
    const flip = tab === "Seal" ? true : false;
    [1000, 3500, 3501, 12345, 45000].forEach((sf) => add(tab, "jf/" + (flip ? "on" : "off") + "/" + sf, { sf: sf, jf: flip }));
    // days typed on the crew line
    [2, 5.5, 12].forEach((d) => add(tab, "days/" + d, { sf: 12345, days: d }));
  });
  return cases;
}

// ── driving the workbook ─────────────────────────────────────────────────────
function main() {
  const args = process.argv.slice(2);
  const write = args.includes("--write");
  const hfFile = E.hyperformulaPath();
  const shipped = E.assertShippedBytes(hfFile);
  const HF = E.loadEngine({ plugin: true });
  const spec = loadSpec();
  const wb = E.build(HF, spec);
  if (wb.warnings.length) fail("the workbook did not load cleanly:\n  " + wb.warnings.join("\n  "));

  const cases = buildCases();
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

  cases.forEach((c) => {
    const tab = c.tab;
    const s = c.in;
    const touched = [];
    const put = (sheet, addr, v) => { original(sheet, addr); wb.set(sheet, addr, v); touched.push([sheet, addr]); };
    // what is shared lives on Seal (Seal (+Jnts) reads it from there)
    if (s.sf !== undefined) put("Seal", "E18", s.sf);
    // New / Reno is ALWAYS typed: the template ships B10 blank, and a blank answers the Reno branch of the patch (Polish!C17
    // and Seal!C17 are IF(B10="New", ...)), where the v2 intake writes "New" for a job that never said
    put("Seal", "B10", s.reno === true ? "Reno" : "New");
    if (s.days !== undefined) put("Seal", "B37", s.days);
    // what each tab owns is typed on the tab that is read
    if (s.coats === 1) put(tab, "B21", 0);
    if (s.jf !== undefined) put(tab, "E29", s.jf ? "Yes" : "No");

    const out = {
      D17: plain(tab, "D17"), D20: plain(tab, "D20"), D21: plain(tab, "D21"), B29: plain(tab, "B29"), D29: plain(tab, "D29"),
      D31: plain(tab, "D31"), D32: plain(tab, "D32"), D33: plain(tab, "D33"),
      D51: plain(tab, "D51"), D55: plain(tab, "D55"),
      D45: plain(tab, "D45"), D64: plain(tab, "D64"), D74: plain(tab, "D74"), D75: plain(tab, "D75"),
      D76: plain(tab, "D76"), D82: plain(tab, "D82"), C82: plain(tab, "C82"), B67: plain(tab, "B67"),
    };
    // the sums the sheet rounds up, unrounded: material before D31, and the labor lines before D45
    out.material = ["D17", "D18", "D19", "D20", "D21", "D22", "D23", "D25", "D26", "D27", "D29", "D30"].reduce((t, a) => t + plain(tab, a), 0);
    out.labor = ["D37", "D38", "D40", "D42", "D44"].reduce((t, a) => t + plain(tab, a), 0);
    c.out = out;
    touched.forEach(([sheet, addr]) => wb.set(sheet, addr, original(sheet, addr)));
  });

  const doc = {
    schema: SCHEMA, generator: "backend/tests/js/seal-jobs-recorder.js", tabs: TABS,
    about: "Seal jobs typed into Kyle's Seal and Seal (+Jnts) tabs (the area, New or Reno, one coat of sealer or two, joint " +
      "filler on or off, the days of the crew) and what the workbook answered. `material` is the sum of D17:D30 before D31 " +
      "rounds it, `labor` the sum of the labor lines before D45 rounds it. Written by the recorder; CI compares the v2 path " +
      "with it (tests/test_seal_v2_proof.py) and checks the template has not moved since (hash).",
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
