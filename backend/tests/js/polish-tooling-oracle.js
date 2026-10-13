#!/usr/bin/env node
"use strict";
/* THE POLISH TOOLING ORACLE: Kyle's Polish tab, asked what its tooling block (D51 to D55) charges, recorded.
 *
 *   NODE_PATH=<scratch dir>/node_modules node backend/tests/js/polish-tooling-oracle.js           compare
 *   NODE_PATH=<scratch dir>/node_modules node backend/tests/js/polish-tooling-oracle.js --write   record
 *
 * The workbook oracle (workbook-oracle.js) TYPES the tooling dollars into D55, so it cannot say what the tab works
 * out for itself. Phase 17 (Polish rev 2) has the model work it out, so this asks the tab the other question: type
 * a square footage (E18), a linear footage (E19), Dye (E25), New or Reno (B10), the polish system (F36) and the
 * traditional option (G36), and record what D51 (tooling and consumables, $150 minimum), D52 (demo tooling),
 * D53 (slurry hardener) and D54 (plastic) come to, and D55, their total.
 *
 * The recorded answers are backend/tests/fixtures/polish_tooling_oracle.json. CI never runs this file (it needs
 * hyperformula@2.7.1, which this repository does not depend on: npm i --no-save --prefix <dir> hyperformula@2.7.1);
 * CI runs js/polish-tooling-harness.js, which holds the MODEL to what is recorded here, and
 * test_polish_rev2.py, which pins the cells these answers came from to the template.
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");

const HERE = __dirname;
const REPO = path.resolve(HERE, "..", "..", "..");
const E = require(path.join(REPO, "docs", "excel-parity-audit", "engine.js"));
const OUT = path.join(HERE, "..", "fixtures", "polish_tooling_oracle.json");
const SUPPORT = path.join(HERE, "..", "_oracle_support.py");
const TAB = "Polish";

function fail(message) { console.error(message); process.exit(1); }

function loadSpec() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-tooling-oracle-"));
  const file = path.join(dir, "spec.json");
  try {
    const exe = process.platform === "win32" ? "python" : "python3";
    const r = cp.spawnSync(exe, [SUPPORT, "--spec", file], { encoding: "utf8", maxBuffer: 512 * 1024 * 1024 });
    if (r.error || r.status !== 0) fail("could not read the template: " + (r.error ? String(r.error) : r.stderr));
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// What is typed. The square footages walk every edge the tab has: the $150 floor (it binds up to 150 / the rate: 163.4
// SF at the salt and pepper rate for a small job, 231.5 for cream, 92.6 for full aggregate, 132.3 for a traditional salt
// and pepper), the validation tab's size tiers (4,000 and 7,000 SF), the slurry bag per 5,000 SF and the plastic's
// reno leg (B35 > 4999).
const SFS = [0, 1, 92, 93, 132, 133, 163, 164, 231, 232, 500, 2500, 4000, 4001, 4999, 5000, 5001, 6999, 7000, 10000, 25000, 100000];
const LFS = [0, 333];
const DYE = ["No", "Yes"];
const RENO = ["New", "Reno"];
const SYSTEMS = ["cream", "S&P", "full"];
const POLISH_KIND = ["Hybrid", "traditional"];
const READ = ["C51", "B51", "D51", "B52", "D52", "B53", "D53", "B54", "D54", "D55"];

function main() {
  const write = process.argv.includes("--write");
  const shipped = E.assertShippedBytes(E.hyperformulaPath());
  const HF = E.loadEngine({ plugin: true });
  const spec = loadSpec();
  const wb = E.build(HF, spec);
  if (wb.warnings.length) fail("the workbook did not load cleanly:\n  " + wb.warnings.join("\n  "));

  const cases = [];
  for (const system of SYSTEMS) for (const kind of POLISH_KIND) for (const dye of DYE) for (const reno of RENO) {
    for (const lf of LFS) for (const sf of SFS) {
      wb.batch(function () {
        wb.set(TAB, "F36", system);
        wb.set(TAB, "G36", kind);
        wb.set(TAB, "E25", dye);
        wb.set(TAB, "B10", reno);
        wb.set(TAB, "E18", sf);
        wb.set(TAB, "E19", lf);
      });
      const out = Object.fromEntries(READ.map((a) => {
        const v = wb.getPlain(TAB, a);
        return [a, v === null || v === undefined || v === false ? 0 : v];
      }));
      cases.push({ in: { sf: sf, lf: lf, dye: dye === "Yes", reno: reno === "Reno", system: system, traditional: kind === "traditional" }, out: out });
    }
  }
  const doc = {
    schema: 1,
    about: "What Kyle's Polish tab charges for tooling and consumables when it works the figure out itself, recorded from the " +
      "template by backend/tests/js/polish-tooling-oracle.js (hyperformula " + shipped.version + ", the engine the page ships). " +
      "`in` is what was typed: sf (E18), lf (E19), dye (E25), reno (B10), system (F36: cream, S&P or full) and " +
      "traditional (G36). `out` is C51 (the rate per SF), B51 (the area), D51 (tooling and consumables), B52 and D52 " +
      "(demo tooling, a quantity nobody types here), B53 and D53 (slurry hardener), B54 and D54 (plastic) and D55 (the total).",
    cells: READ,
    cases: cases,
  };
  const text = JSON.stringify(doc) + "\n";
  if (write) {
    fs.writeFileSync(OUT, text);
    console.log("wrote " + path.relative(REPO, OUT) + " (" + cases.length + " cases, " + text.length + " bytes)");
    return;
  }
  const have = fs.existsSync(OUT) ? fs.readFileSync(OUT, "utf8").replace(/\r\n/g, "\n") : null;
  if (have !== text) fail("DIFFERS: " + path.relative(REPO, OUT) + ". If the template changed on purpose, re-run with --write.");
  console.log("the tooling oracle reproduces " + cases.length + " recorded cases exactly");
}

main();
