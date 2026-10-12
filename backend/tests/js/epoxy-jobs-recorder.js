#!/usr/bin/env node
"use strict";
/* THE EPOXY JOBS, RECORDED FROM KYLE'S WORKBOOK. The answer key for what the v2 Epoxy takeoff has to price.
 *
 *   node backend/tests/js/epoxy-jobs-recorder.js --plan <plan.json>            compare with the recorded file
 *   node backend/tests/js/epoxy-jobs-recorder.js --plan <plan.json> --write    rewrite it
 *
 * The workbook oracle (workbook-oracle.js) types numbers into the BOUNDARY of each tab's markup chain, so it
 * proves the chain and says nothing about the material that arrives there. This is the other half: it types a
 * JOB into the Epoxy tab (a system for System 1 and one for System 2, a primer, a cove and its length, the
 * square feet, the job questions), lets the workbook price it, and records the cells that matter. The v2 path
 * has to arrive at the same figures from the library rows backend/ops/seed_library_from_workbook.py plans
 * (tests/js/epoxy-v2-proof-harness.js, tests/test_epoxy_v2_proof.py).
 *
 * NEEDS hyperformula@2.7.1 (see workbook-oracle.js) and the plan the seed script prints with --json:
 *     python backend/ops/seed_library_from_workbook.py --json > plan.json
 *     NODE_PATH=<scratch dir>/node_modules node backend/tests/js/epoxy-jobs-recorder.js --plan plan.json --write
 * CI never runs it. CI compares the recorded file with the template (a hash of the Epoxy tab and of every defined
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
const OUT = path.join(HERE, "..", "fixtures", "epoxy_jobs_golden.json");
const SCHEMA = 1;
const TAB = "Epoxy";

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
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-epoxy-jobs-"));
  const file = path.join(dir, "spec.json");
  try {
    python(["--spec", file]);
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function templateHash() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-epoxy-jobs-"));
  const file = path.join(dir, "sheets.json");
  try {
    fs.writeFileSync(file, JSON.stringify([TAB]));
    return JSON.parse(python(["--hash", file]));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// ── the cases ────────────────────────────────────────────────────────────────
/** What a case may say. Every field is optional; a system or cove left out is left blank in the workbook. */
const FIELDS = ["sys1", "primer1", "sf1", "cove1", "lf1", "sys2", "primer2", "sf2", "cove2", "lf2",
  "guys", "days", "taxable", "pw", "remodel"];

function buildCases(plan) {
  const asm = plan.assemblies;
  const floors = asm.filter((a) => a.id.startsWith("wb-epoxy-sys-") && !a.id.startsWith("wb-epoxy-sys-walls-")).map((a) => a.name);
  const walls = asm.filter((a) => a.id.startsWith("wb-epoxy-sys-walls-")).map((a) => a.name);
  const primers = asm.filter((a) => a.id.startsWith("wb-epoxy-primer-")).map((a) => a.name.replace(/^Primer: /, ""));
  const coves = asm.filter((a) => a.id.startsWith("wb-epoxy-cove-")).map((a) => a.name.replace(/^Cove: /, ""));
  const quartz = floors.filter((n) => /Quartz/.test(n));
  const cases = [];
  const add = (id, spec) => cases.push({ id: id, in: spec });
  const slug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

  // every floor system alone, at three sizes (a flake bag is 40 lb: the edges of the CEILINGs are between them)
  floors.forEach((n) => [1000, 4000, 12000].forEach((sf) => add("system/" + slug(n) + "/" + sf, { sys1: n, sf1: sf })));
  // the square feet that sit on or beside a pack edge, for the two flake systems and a quartz one
  [250, 266, 267, 800, 2666, 2667, 8000, 8001, 20000, 33333, 60000, 100000].forEach((sf) => {
    add("edge/macro/" + sf, { sys1: floors.find((n) => n === "MACRO Flake Single Broadcast"), sf1: sf });
    add("edge/quartz/" + sf, { sys1: "40-S (Q28) Quartz Double Broadcast", sf1: sf });
  });
  // every primer, so each primer's coverage and price is on record. System 1's primer list offers the four epoxy
  // primers only (A21 reads B162 to B165); the two wall primers (HP Gripper, HP Block Filler) are System 2's.
  const hp = (p) => /^HP /.test(p);
  primers.filter((p) => !hp(p)).forEach((p) => add("primer/" + slug(p), { sys1: "MACRO Flake Single Broadcast", primer1: p, sf1: 5000 }));
  primers.filter(hp).forEach((p) => add("primer2/" + slug(p), { sys1: "MACRO Flake Single Broadcast", sf1: 5000, sys2: "Walls: Dur-A-Wall HP", primer2: p, sf2: 3000 }));
  // every wall system as System 2 beside a flake floor
  walls.forEach((n) => add("walls/" + slug(n), { sys1: "MACRO Flake Single Broadcast", sf1: 5000, sys2: n, sf2: 3000 }));
  // every floor system as System 2, too: the two halves of the sheet are the same table twice
  floors.forEach((n) => add("system2/" + slug(n), { sys1: "Shop Floor Single Broadcast", sf1: 3000, sys2: n, sf2: 2500 }));
  // every cove, three lengths, under a system that is not quartz and under each quartz system (odd rule 11)
  coves.forEach((c) => [40, 250, 777].forEach((lf) => {
    add("cove/" + slug(c) + "/" + lf, { sys1: "MACRO Flake Single Broadcast", sf1: 6000, cove1: c, lf1: lf });
    quartz.forEach((q) => add("cove/" + slug(c) + "/" + lf + "/under-" + slug(q), { sys1: q, sf1: 6000, cove1: c, lf1: lf }));
  }));
  // a cove under System 2 and a quartz System 2 under a flake System 1: the aggregate follows System 1
  ["Epoxy 4\"", "Epoxy 8\" + Cap"].forEach((c) => {
    add("cove2/" + slug(c) + "/flake-then-quartz", { sys1: "MACRO Flake Single Broadcast", sf1: 4000, sys2: "40-S (Q28) Quartz Double Broadcast", sf2: 4000, cove2: c, lf2: 300 });
    add("cove2/" + slug(c) + "/quartz-then-flake", { sys1: "40-S (Q28) Quartz Double Broadcast", sf1: 4000, sys2: "MACRO Flake Single Broadcast", sf2: 4000, cove2: c, lf2: 300 });
  });
  // whole jobs: a system, a primer, a cove, the job questions
  const jobs = [
    { sys1: "MACRO Flake Single Broadcast", primer1: "MVP (@ 12 mils)", sf1: 8200, cove1: "Epoxy 4\"", lf1: 410, guys: 3, days: 5 },
    { sys1: "micro Flake Double Broadcast", primer1: "WB", sf1: 15750, cove1: "Epoxy 6\" + Cap", lf1: 900, guys: 4, days: 7, taxable: false },
    { sys1: "Hybrid  micro Flake", sf1: 23000, cove1: "WR 4\"", lf1: 600, guys: 5, days: 10, pw: true },
    { sys1: "40-S (Q28) Quartz Double Broadcast", sf1: 5400, cove1: "Epoxy 4\" + Cap", lf1: 380, guys: 3, days: 6, remodel: true },
    { sys1: "Shop Floor Double Broadcast", sf1: 41000, sys2: "Walls: Dur-A-Wall HP", sf2: 6000, guys: 6, days: 14, pw: true, remodel: true },
    { sys1: "Dur-A-Gard", sf1: 1800, guys: 2, days: 3 },
    { sys1: "3/16\" Urethne Cement With Color Fast (SLB)", sf1: 2400, cove1: "WR 8\" + Cap", lf1: 120, guys: 3, days: 4, taxable: false },
    { sys1: "Trowel - Hybrid Quartz Double Broadcast (Orange Peel Texture/Trowel Texture)", sf1: 9100, primer1: "TF+ (Reg. Size)", cove1: "Epoxy 8\"", lf1: 520, guys: 4, days: 8 },
  ];
  jobs.forEach((j, i) => add("job/" + (i + 1), j));
  // nothing measured: the sheet still charges its tooling minimums, the v2 section does not (a declared difference)
  add("empty/none", {});
  return cases;
}

// ── driving the workbook ─────────────────────────────────────────────────────
const norm = (t) => String(t).replace(/\s+/g, " ").trim();

/** The name exactly as the workbook's own lists spell it. The library keeps a name with its spaces collapsed
 *  ("Hybrid MACRO Flake"), and the workbook's dropdown has two spaces in it ("Hybrid  MACRO Flake"), so a cell has to
 *  be given the workbook's spelling. Looked up in the lists the dropdowns offer: System 1 and System 2 options, Cove 1
 *  options and the primer options. */
function exactNamer(wb) {
  const lists = [];
  for (let r = 181; r <= 203; r++) { lists.push("R" + r); lists.push("AR" + r); }
  for (let r = 125; r <= 136; r++) lists.push("S" + r);
  ["B162", "B163", "B164", "B165", "AB166", "AB167", "B166", "B167"].forEach((a) => lists.push(a));
  const byNorm = new Map();
  lists.forEach((a) => {
    const v = wb.getPlain(TAB, a);
    if (typeof v === "string" && v) byNorm.set(norm(v), v);
  });
  return (name) => {
    if (!byNorm.has(norm(name))) fail("the workbook's lists do not offer " + JSON.stringify(name));
    return byNorm.get(norm(name));
  };
}

/** Which cell each field goes to, and what to write. A name (a system, a cove, a primer) is written as the workbook
 *  spells it; a Yes or No and a number are written as they are. */
function writes(spec, exact) {
  const w = [];
  const put = (addr, v) => w.push([addr, v]);
  const named = (addr, v) => w.push([addr, exact(v)]);
  if (spec.sys1) named("A22", spec.sys1);
  if (spec.primer1) named("A21", spec.primer1);
  if (spec.sf1 !== undefined) put("E20", spec.sf1);
  if (spec.cove1) named("A35", spec.cove1);
  if (spec.lf1 !== undefined) put("E34", spec.lf1);
  if (spec.sys2) named("A26", spec.sys2);
  if (spec.primer2) named("A25", spec.primer2);
  if (spec.sf2 !== undefined) put("E24", spec.sf2);
  if (spec.cove2) named("A37", spec.cove2);
  if (spec.lf2 !== undefined) put("E37", spec.lf2);
  if (spec.guys !== undefined) put("A47", spec.guys);
  if (spec.days !== undefined) put("B47", spec.days);
  if (spec.taxable === false) put("B6", "No");
  if (spec.pw === true) put("D5", "Yes");
  if (spec.remodel === true) put("D6", "Yes");
  return w;
}

const PARTS = ["D18", "D19", "D21", "D22", "D23", "D25", "D26", "D27", "D28", "D30", "D31", "D32", "D33",
  "D35", "D36", "D37", "D38", "D39"];
const READ = ["D40", "D42", "D43", "D53", "D62", "D70", "D73", "D80", "D81", "D82", "D88"];

function main() {
  const args = process.argv.slice(2);
  const write = args.includes("--write");
  const planAt = args.indexOf("--plan");
  if (planAt < 0) fail("--plan <the seed script's --json output> is required");
  const plan = JSON.parse(fs.readFileSync(args[planAt + 1], "utf8"));

  const hfFile = E.hyperformulaPath();
  const shipped = E.assertShippedBytes(hfFile);
  const HF = E.loadEngine({ plugin: true });
  const spec = loadSpec();
  const wb = E.build(HF, spec);
  if (wb.warnings.length) fail("the workbook did not load cleanly:\n  " + wb.warnings.join("\n  "));

  const originals = new Map();
  const original = (addr) => {
    if (!originals.has(addr)) { const v = wb.serialized(TAB, addr); originals.set(addr, v === undefined ? null : v); }
    return originals.get(addr);
  };
  const exact = exactNamer(wb);
  const cases = buildCases(plan);
  const seen = new Set();
  cases.forEach((c) => { if (seen.has(c.id)) fail("two cases are called " + c.id); seen.add(c.id); });
  Object.keys(cases.reduce((a, c) => Object.assign(a, c.in), {})).forEach((k) => {
    if (FIELDS.indexOf(k) < 0) fail("a case names a field the recorder does not know: " + k);
  });

  const unknown = [];
  cases.forEach((c) => {
    const touched = writes(c.in, exact);
    touched.forEach(([addr, v]) => { original(addr); wb.set(TAB, addr, v); });
    const parts = {};
    PARTS.forEach((a) => { const v = wb.getPlain(TAB, a); parts[a] = typeof v === "number" ? v : 0; });
    const raw = PARTS.reduce((t, a) => t + parts[a], 0);
    const out = { raw: raw };
    READ.forEach((a) => { out[a] = wb.getPlain(TAB, a); });
    // a system or cove name the workbook did not recognise prices as 0 (its lookup falls through); record that as a
    // mistake in the case, not as a price
    if ((c.in.sys1 && !(parts.D22 > 0 || parts.D30 > 0)) && (c.in.sf1 > 0)) unknown.push(c.id + ": sys1 " + c.in.sys1);
    c.out = out;
    c.parts = parts;
    touched.forEach(([addr]) => wb.set(TAB, addr, original(addr)));
  });
  if (unknown.length) fail("the workbook priced these systems at nothing, so a name is wrong:\n  " + unknown.join("\n  "));

  const doc = {
    schema: SCHEMA, generator: "backend/tests/js/epoxy-jobs-recorder.js", sheet: TAB,
    about: "Epoxy jobs typed into Kyle's workbook (a system, a primer, a cove and its length, the job questions) and what its " +
      "cells answered. Material = the sum of Epoxy!D18:D39 before D40 rounds it. Written by the recorder; CI compares the " +
      "v2 path with it (tests/test_epoxy_v2_proof.py) and checks the template has not moved since (hash).",
    engine: { hyperformula: { version: shipped.version, sri: shipped.sri } },
    template: templateHash(),
    cases: cases,
  };
  const text = "{\n" + ["schema", "generator", "sheet", "about", "engine", "template"].map((k) => JSON.stringify(k) + ": " + JSON.stringify(doc[k])).join(",\n") +
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
