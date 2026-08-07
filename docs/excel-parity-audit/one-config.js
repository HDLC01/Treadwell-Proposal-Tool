// ONE config, in its own process. Nothing can leak between measurements.
//
// The previous harness ran all four configs in a single process, and `unregisterFunctionPlugin`
// silently failed to remove the custom ROUNDUP (it was handed a freshly-built class that did not
// match the registered one). Every config measured after the plugin config therefore ran WITH the
// plugin, which made `smartRounding:false` look like it achieved parity on its own. It does not.
//
// Usage: node one-config.js <was|nosmart|precision|roundup>
const { HyperFormula, FunctionPlugin, FunctionArgumentType } = require("hyperformula");
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const CENT = 0.005;
const WHICH = process.argv[2];

const readJson = (p) => JSON.parse(fs.readFileSync(p, "utf8").replace(/^﻿/, ""));
const snap = (x) => { const n = Number(x); return isFinite(n) ? Number(n.toPrecision(12)) : n; };

const OPTS = {
  was:       { smartRounding: true,  precisionRounding: 4 },
  nosmart:   { smartRounding: false },
  precision: { smartRounding: true,  precisionRounding: 10 },
  roundup:   { smartRounding: false },      // + the plugin below
};
if (!OPTS[WHICH]) { console.error("unknown config " + WHICH); process.exit(2); }

if (WHICH === "roundup") {
  class ExcelRounding extends FunctionPlugin {
    roundup(ast, state) {
      return this.runFunction(ast.args, state, this.metadata("ROUNDUP"), (value, places) => {
        const p = Math.trunc(places || 0), f = Math.pow(10, p);
        const s = snap(snap(value) * f);
        return (s >= 0 ? Math.ceil(s) : Math.floor(s)) / f;
      });
    }
    ceilingFn(ast, state) {
      return this.runFunction(ast.args, state, this.metadata("CEILING"), (value, sig) => {
        const s = (sig === undefined || sig === null) ? 1 : Number(sig);
        if (s === 0) return 0;
        return Math.ceil(snap(snap(value) / s)) * s;
      });
    }
  }
  ExcelRounding.implementedFunctions = {
    ROUNDUP: { method: "roundup", parameters: [
      { argumentType: FunctionArgumentType.NUMBER },
      { argumentType: FunctionArgumentType.NUMBER, defaultValue: 0 }] },
    CEILING: { method: "ceilingFn", parameters: [
      { argumentType: FunctionArgumentType.NUMBER },
      { argumentType: FunctionArgumentType.NUMBER, defaultValue: 1 }] },
  };
  HyperFormula.unregisterFunction("ROUNDUP");
  HyperFormula.unregisterFunction("CEILING");
  HyperFormula.registerFunctionPlugin(ExcelRounding,
    { enGB: { ROUNDUP: "ROUNDUP", CEILING: "CEILING" } });
}

function build(spec) {
  const hf = HyperFormula.buildEmpty(Object.assign({ licenseKey: "gpl-v3" }, OPTS[WHICH]));
  const idBy = {};
  for (const n of spec.order) { hf.addSheet(n); idBy[n] = hf.getSheetId(n); }
  const aliases = {};
  for (const n of spec.names || []) {
    let reg = n.name;
    try {
      if (!hf.isItPossibleToAddNamedExpression(reg, n.expression)) {
        reg = n.name.replace(/(\d+)$/, "_$1");
        if (reg === n.name) reg = n.name + "_n";
        aliases[n.name] = reg;
      }
      hf.addNamedExpression(reg, n.expression);
    } catch (e) { delete aliases[n.name]; }
  }
  const rewrite = (f) => {
    let o = f;
    for (const k in aliases) {
      const esc = k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      o = o.replace(new RegExp("(?<![A-Za-z0-9_.])" + esc + "(?![A-Za-z0-9_.])", "g"), aliases[k]);
    }
    return o;
  };
  for (const name of spec.order) {
    const cells = spec.sheets[name].cells;
    let mr = 0, mc = 0;
    for (const c of cells) { if (c.row > mr) mr = c.row; if (c.col > mc) mc = c.col; }
    const data = [];
    for (let r = 0; r < mr; r++) data.push(new Array(mc).fill(null));
    for (const c of cells) {
      data[c.row - 1][c.col - 1] = c.isFormula && c.formula != null ? rewrite(c.formula)
        : (c.value === "" || c.value === undefined ? null : c.value);
    }
    try { hf.setSheetContent(idBy[name], data); } catch (e) {}
  }
  return { hf, idBy };
}

let numeric = 0, match = 0;
const misses = [];
for (const f of fs.readdirSync(HERE).filter((x) => /^job\d+\.json$/.test(x)).sort()) {
  const stem = f.replace(/\.json$/, "");
  const ep = path.join(HERE, stem + ".excel.json");
  if (!fs.existsSync(ep)) continue;
  const spec = readJson(path.join(HERE, f));
  const excel = readJson(ep);
  const eng = build(spec);
  for (const c of spec.compare) {
    const key = c.sheet + "!" + c.addr;
    const e = excel[key];
    if (typeof e !== "number" || e < -1e9) continue;
    numeric++;
    const id = eng.idBy[c.sheet];
    let h = null;
    if (id !== undefined) {
      const m = /^([A-Z]{1,3})(\d+)$/.exec(c.addr);
      if (m) {
        let col = 0;
        for (const ch of m[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
        try { h = eng.hf.getCellValue({ sheet: id, col: col - 1, row: +m[2] - 1 }); } catch (x) {}
      }
    }
    const hn = typeof h === "number" ? h : NaN;
    if (isFinite(hn) && Math.abs(hn - e) < CENT) match++;
    else misses.push({ job: stem, cell: key, excel: e, hf: hn, diff: isFinite(hn) ? +(hn - e).toFixed(4) : null });
  }
  eng.hf.destroy();
}
console.log(JSON.stringify({ config: WHICH, numeric, match, wrong: misses.length,
                             pct: +(100 * match / numeric).toFixed(3),
                             worst: misses.sort((a, b) => Math.abs(b.diff) - Math.abs(a.diff)).slice(0, 5) }));
