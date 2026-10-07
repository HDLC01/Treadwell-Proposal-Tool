// ONE config, in its own process. Nothing can leak between measurements.
//
// The previous harness ran all four configs in a single process, and `unregisterFunctionPlugin`
// silently failed to remove the custom ROUNDUP (it was handed a freshly-built class that did not
// match the registered one). Every config measured after the plugin config therefore ran WITH the
// plugin, which made `smartRounding:false` look like it achieved parity on its own. It does not.
//
// The engine itself (the shipped HyperFormula bytes, the shipped rounding plugin, the page's load
// order) lives in ./engine.js, shared with backend/tests/js/workbook-oracle.js. This file is only
// the comparison against Excel's own answers.
//
// Usage: node one-config.js <was|nosmart|precision|roundup>
//   `roundup` is the configuration that ships: frontend/js/xl-excel-rounding.js, loaded as it is.
//   The other three leave HyperFormula's own ROUNDUP in place, with the options named below.
const fs = require("fs");
const path = require("path");
const E = require("./engine.js");

const HERE = __dirname;
const CENT = 0.005;
const WHICH = process.argv[2];

const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8").replace(/^﻿/, ""));

const OPTS = {
  was:       { smartRounding: true,  precisionRounding: 4 },
  nosmart:   { smartRounding: false },
  precision: { smartRounding: true,  precisionRounding: 10 },
  roundup:   { smartRounding: false },      // + the shipped plugin, loaded by engine.js
};
if (!OPTS[WHICH]) { console.error("unknown config " + WHICH); process.exit(2); }

// The bytes under test must be the bytes the page ships: a result measured on some other
// HyperFormula says nothing about the screen.
E.assertShippedBytes(E.hyperformulaPath());
const HyperFormula = E.loadEngine({ plugin: WHICH === "roundup" });

let numeric = 0, match = 0;
const misses = [];
for (const f of fs.readdirSync(HERE).filter((x) => /^job\d+\.json$/.test(x)).sort()) {
  const stem = f.replace(/\.json$/, "");
  const ep = path.join(HERE, stem + ".excel.json");
  if (!fs.existsSync(ep)) continue;
  const spec = readJson(path.join(HERE, f));
  const excel = readJson(ep);
  const wb = E.build(HyperFormula, spec, { options: Object.assign({ licenseKey: "gpl-v3" }, OPTS[WHICH]) });
  if (wb.warnings.length) console.error(stem + ": " + wb.warnings.join("; "));
  for (const c of spec.compare) {
    const key = c.sheet + "!" + c.addr;
    const e = excel[key];
    if (typeof e !== "number" || e < -1e9) continue;
    numeric++;
    let h = null;
    if (wb.sheetNames.indexOf(c.sheet) >= 0 && /^[A-Z]{1,3}\d+$/.test(c.addr)) {
      try { h = wb.get(c.sheet, c.addr); } catch (x) { /* a cell the engine cannot read counts as a miss */ }
    }
    const hn = typeof h === "number" ? h : NaN;
    if (isFinite(hn) && Math.abs(hn - e) < CENT) match++;
    else misses.push({ job: stem, cell: key, excel: e, hf: hn, diff: isFinite(hn) ? +(hn - e).toFixed(4) : null });
  }
  wb.destroy();
}
console.log(JSON.stringify({ config: WHICH, numeric, match, wrong: misses.length,
                             pct: +(100 * match / numeric).toFixed(3),
                             worst: misses.sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff)).slice(0, 5) }));
