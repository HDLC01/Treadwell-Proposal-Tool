#!/usr/bin/env node
"use strict";
/* THE WORKBOOK ORACLE: Kyle's estimate workbook, evaluated by the engine the Estimate Review page
 * runs, as the answer key every v2 tab is checked against.
 *
 *   node backend/tests/js/workbook-oracle.js            recompute everything and compare it with the
 *                                                       recorded files; exit 1 on any difference
 *   node backend/tests/js/workbook-oracle.js --write    recompute and rewrite
 *                                                       backend/tests/fixtures/oracle/*.json
 *   node backend/tests/js/workbook-oracle.js --only polish     compare one tab only (never with --write)
 *
 * NEEDS hyperformula@2.7.1, which this repository deliberately does not depend on (no package.json):
 *     npm i --no-save --prefix <scratch dir> hyperformula@2.7.1
 *     NODE_PATH=<scratch dir>/node_modules node backend/tests/js/workbook-oracle.js
 * and Python with openpyxl (the backend's own requirements), which reads the template through
 * backend/estimate_writer.py. CI never runs this file: CI COMPARES the recorded answers with the
 * template and the code (backend/tests/test_workbook_oracle.py), so a template edit, or a different
 * HyperFormula on the page, fails there with "re-run the oracle".
 *
 * WHAT IT DOES, in order.
 *   1. Proves it is running the bytes the page ships: the installed hyperformula.full.min.js must hash
 *      to the sha384 estimate-review.html pins, and frontend/js/xl-excel-rounding.js is loaded as it
 *      ships (docs/excel-parity-audit/engine.js).
 *   2. Loads the whole workbook the way the page does: all sixteen tabs, the named expressions with
 *      the page's alias rule, formula text where there is one.
 *   3. SELF-CHECK. With nothing injected, every formula cell must equal the value Excel last saved in the
 *      file. See selfCheck() for the one thing that has to be put back first: the template's labor-rate
 *      cells were edited after its last calculation.
 *   4. For each of the eleven priced tabs, types numbers into the boundary cells named in
 *      frontend/js/bid-profiles.js (material, labor, tooling, travel, fees, contingency, the job
 *      questions, the rates) and records what the chain answers. The cases are fixed lists and sweeps,
 *      no random numbers, so two runs write the same bytes.
 *   5. Runs the probes: a few targeted experiments upstream of the boundary that show the odd rules of
 *      docs/kyle-workbook-odd-rules.md happening in the workbook itself.
 *   6. Writes meta.json, which says what the answers were recorded FROM: the engine, the template (a hash
 *      of the priced tabs' cells AND the workbook's defined names), the self-check, and `integrity`, a
 *      sha256 of every file it wrote and of the cell maps it read (backend/tests/js/oracle-integrity.js).
 *      CI recomputes those hashes, so a recorded answer edited by hand is caught even when it still adds up.
 *
 * A CASE is { id, in, out [, rows] }. `in` names only what differs from the defaults: every input not
 * named is written as 0, every flag and rate not named is left as the template has it. The value
 * "template" for an input restores the template's own formula instead of a 0. `out` is every cell in the
 * map's `outputs`.
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");

const HERE = __dirname;
const REPO = path.resolve(HERE, "..", "..", "..");
const E = require(path.join(REPO, "docs", "excel-parity-audit", "engine.js"));
const P = require(path.join(REPO, "frontend", "js", "bid-profiles.js"));
const I = require("./oracle-integrity.js");
const OUT_DIR = path.join(HERE, "..", "fixtures", "oracle");
const SUPPORT = path.join(HERE, "..", "_oracle_support.py");
const SCHEMA = 1;
const DEFAULT_SF = 10000;

function fail(message) {
  console.error(message);
  process.exit(1);
}

// ── Python: the template, read through the live readers ──────────────────────
function python(args) {
  const exe = process.platform === "win32" ? "python" : "python3";
  const r = cp.spawnSync(exe, [SUPPORT].concat(args), { encoding: "utf8", maxBuffer: 512 * 1024 * 1024 });
  if (r.error || r.status !== 0) {
    fail("could not run " + exe + " " + SUPPORT + "\n" + (r.error ? String(r.error) : r.stderr));
  }
  return r.stdout;
}

function scratchFile(name, text) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-oracle-"));
  const file = path.join(dir, name);
  fs.writeFileSync(file, text);
  return { dir: dir, file: file };
}

function loadSpec() {
  const tmp = scratchFile("spec.json", "");
  try {
    python(["--spec", tmp.file]);
    return JSON.parse(fs.readFileSync(tmp.file, "utf8"));
  } finally {
    fs.rmSync(tmp.dir, { recursive: true, force: true });
  }
}

function templateHash(sheets) {
  const tmp = scratchFile("sheets.json", JSON.stringify(sheets));
  try {
    return JSON.parse(python(["--hash", tmp.file]));
  } finally {
    fs.rmSync(tmp.dir, { recursive: true, force: true });
  }
}

// ── cells: every write goes through here, so a case only touches what changed ─
/** A thin layer over the workbook that remembers what each cell held before the oracle first wrote to
 *  it (`original`) and what it holds now, and skips a write that would change nothing. Re-evaluating
 *  twenty cells that did not move was most of the cost of the first version of this file. */
function makeCells(wb) {
  const originals = new Map();
  const current = new Map();
  const key = (tab, addr) => tab + "!" + addr;
  function original(tab, addr) {
    const k = key(tab, addr);
    if (!originals.has(k)) {
      const v = wb.serialized(tab, addr);
      originals.set(k, v === undefined ? null : v);
    }
    return originals.get(k);
  }
  function put(tab, addr, content) {
    const k = key(tab, addr);
    const before = original(tab, addr);
    const now = current.has(k) ? current.get(k) : before;
    if (now === content) return;
    wb.set(tab, addr, content);
    current.set(k, content);
  }
  function restore(tab, addr) { put(tab, addr, original(tab, addr)); }
  return { wb: wb, original: original, put: put, restore: restore };
}

// ── the self-check ───────────────────────────────────────────────────────────
function agrees(cached, engine) {
  if (typeof cached === "number") {
    if (typeof engine === "number") return Math.abs(engine - cached) < 0.005;
    return engine === null && cached === 0;               // a reference to an empty cell: Excel says 0
  }
  if (typeof cached === "boolean") return engine === cached;
  if (typeof cached === "string") return engine === cached; // an error compares as its text, "#DIV/0!"
  return false;
}

function compareAll(wb, spec) {
  const out = new Map();
  for (const tab of spec.order) {
    let compared = 0, matched = 0;
    const misses = [];
    for (const c of spec.sheets[tab].cells) {
      if (!c.isFormula || c.cached === null || c.cached === undefined) continue;
      compared++;
      const got = wb.getPlain(tab, c.addr);
      if (agrees(c.cached, got)) matched++;
      else if (misses.length < 8) misses.push(c.addr + ": saved " + JSON.stringify(c.cached) + ", engine " + JSON.stringify(got));
    }
    out.set(tab, { compared: compared, matched: matched, misses: misses });
  }
  return out;
}

/** The labor rate the cached values were computed with, when it is not the constant the cell holds now.
 *
 *  THE TEMPLATE WAS EDITED AFTER ITS LAST CALCULATION. Polish!C37 holds 33, and the cell right under it,
 *  C38 `=C37`, was saved as 32.2; the same is true of Epoxy, Epoxy blank, Seal (33 against 32.2) and of
 *  Leveling and the Gyp tabs (33.66 against 32.52). Someone changed the rate constants without Excel
 *  recalculating, so every cached figure downstream of a labor rate is a few dollars off what the file
 *  itself computes. The page never shows those cached figures (it computes from the formulas), but they
 *  make "the engine reproduces the file" untrue as it stands.
 *
 *  So the self-check puts back, for the length of the check only, the rate the cache holds: the labor rate
 *  cell and the travel labor rate cell are set to the figure a plain reference to the labor rate cell was
 *  saved with. A tab whose rate cell is itself a formula (Seal (+Jnts) reads Seal's) needs nothing: Seal
 *  is put back first and the formula follows. When the template is saved by Excel after a recalculation
 *  the saved and current rates agree, nothing is put back, and the check is the plain one. */
function cacheRate(spec, tab, map) {
  const ent = map.rates.laborRate;
  if (ent.formula !== undefined) return null;
  const want = "=" + ent.addr;
  for (const c of spec.sheets[tab].cells) {
    if (c.isFormula && c.formula === want && typeof c.cached === "number" && c.cached !== ent.value) return c.cached;
  }
  return null;
}

function selfCheck(cells, spec) {
  const wb = cells.wb;
  const before = compareAll(wb, spec);
  const restored = new Map();                              // tab -> [{cell, template, saved}]
  for (const tab of P.priced) {
    const map = P.sheets[tab];
    const saved = cacheRate(spec, tab, map);
    if (saved === null) continue;
    const list = [{ cell: map.rates.laborRate.addr, template: map.rates.laborRate.value, saved: saved }];
    const travel = map.rates.travelRate;
    if (travel.formula === undefined && travel.value === map.rates.laborRate.value) {
      list.push({ cell: travel.addr, template: travel.value, saved: saved });
    }
    for (const r of list) cells.put(tab, r.cell, r.saved);
    restored.set(tab, list);
  }
  const after = compareAll(wb, spec);
  for (const [tab, list] of restored) for (const r of list) cells.restore(tab, r.cell);
  const rows = [];                                         // [tab, row], in the workbook's order
  const bad = [];
  for (const tab of spec.order) {
    const b = before.get(tab), a = after.get(tab);
    const row = { compared: a.compared, matchedAsSaved: b.matched, matched: a.matched };
    if (restored.has(tab)) {
      row.laborRatesPutBack = restored.get(tab).map((r) => tab + "!" + r.cell + ": " + r.template + " -> " + r.saved);
    }
    rows.push([tab, row]);
    if (a.matched !== a.compared) bad.push(tab + ": " + (a.compared - a.matched) + " of " + a.compared + " differ\n    " + a.misses.join("\n    "));
  }
  const report = {
    sheets: Object.fromEntries(rows),
    rule: "every formula cell with a saved value must equal it (numbers to the cent, an empty reference as 0, " +
      "errors as their text), after the labor-rate cells of the tabs listed are put back to the rate the file was last calculated with",
    compared: spec.order.reduce((n, t) => n + after.get(t).compared, 0),
    matched: spec.order.reduce((n, t) => n + after.get(t).matched, 0),
  };
  return { report: report, bad: bad };
}

// ── ladders: the edges of every piecewise rate, read out of the formula text ──
/** The numbers a formula compares against: `D64<6500` gives { op: "<", at: 6500 }. */
function thresholds(formula) {
  const seen = new Map();
  const re = /([<>]=?)\s*(\d+(?:\.\d+)?)/g;
  let m;
  while ((m = re.exec(formula)) !== null) seen.set(m[2], { op: m[1], at: Number(m[2]) });
  return Array.from(seen.values()).sort((a, b) => a.at - b.at);
}

function ladderEdges(map) {
  return map.ladders.map((l) => {
    const ent = map.outputs[l.cell];
    return Object.assign({}, l, { edges: thresholds(ent.formula) });
  });
}

// ── running one case ─────────────────────────────────────────────────────────
function runCase(cells, tab, map, input) {
  const known = new Set([].concat(Object.keys(map.flags), Object.keys(map.inputs), Object.keys(map.rates)));
  for (const name of Object.keys(input)) {
    if (!known.has(name)) throw new Error(tab + ": the case names " + name + ", which is not a flag, input or rate of the map");
  }
  if (input.remodelPct !== undefined && input.remodel !== true) {
    throw new Error(tab + ": a remodel rate is only ever typed with the remodel question answered Yes");
  }
  const words = P.flagWords;
  // Remember what every cell held BEFORE the batch starts: the engine will not read a cell while a
  // batch has evaluation suspended.
  for (const group of [map.flags, map.inputs, map.rates]) {
    for (const name of Object.keys(group)) cells.original(tab, group[name].addr);
  }
  cells.wb.batch(function () {
    for (const name of Object.keys(map.flags)) {
      const v = input[name];
      const addr = map.flags[name].addr;
      if (v === undefined) cells.restore(tab, addr);
      else cells.put(tab, addr, v ? words.on : words.off);
    }
    for (const name of Object.keys(map.inputs)) {
      const v = input[name];
      const addr = map.inputs[name].addr;
      if (v === undefined) cells.put(tab, addr, 0);
      else if (v === "template") cells.restore(tab, addr);
      else cells.put(tab, addr, v);
    }
    for (const name of Object.keys(map.rates)) {
      const v = input[name];
      const addr = map.rates[name].addr;
      if (v === undefined) cells.restore(tab, addr);
      else cells.put(tab, addr, v);
    }
  });
  // Built as a Map and turned into plain data at the end: the keys are names out of the map, and a Map
  // keeps them as data whatever they are called.
  const out = new Map();
  for (const name of Object.keys(map.outputs)) out.set(name, cells.wb.getPlain(tab, map.outputs[name].addr));
  // A rate that is a formula in the template (the remodel rate, `=IF(D6="yes",0.1,0)`) depends on the
  // answers, so what it came to is part of the answer. A constant rate is in the map already.
  for (const name of Object.keys(map.rates)) {
    if (map.rates[name].formula !== undefined) out.set(name, cells.wb.getPlain(tab, map.rates[name].addr));
  }
  for (const name of Object.keys(input)) {
    if (input[name] === "template") out.set(name, cells.wb.getPlain(tab, map.inputs[name].addr));
  }
  // The five answers as the tab holds them after the case, as true and false, so nobody has to guess
  // what a flag the case did not name was (the template's own answer: Local yes, Taxable yes, the rest no).
  const answers = Object.keys(map.flags).map((name) => {
    const v = cells.wb.getPlain(tab, map.flags[name].addr);
    return [name, typeof v === "string" ? v.toLowerCase() === words.on.toLowerCase() : v];
  });
  out.set("answers", Object.fromEntries(answers));
  return Object.fromEntries(out);
}

// ── the sizes of job each family is tried at ─────────────────────────────────
const SIZES = {
  polish: {
    small: { material: 800, labor: 900, tooling: 150, travel: 0 },
    mid: { material: 12000, labor: 6000, tooling: 300, travel: 400 },
    big: { material: 90000, labor: 40000, tooling: 1500, travel: 3000 },
  },
  epoxy: {
    small: { material: 800, labor: 900, tooling: 220, travel: 0 },
    mid: { material: 7000, labor: 6000, tooling: 220, travel: 400 },
    big: { material: 40000, labor: 25000, tooling: 800, travel: 2500 },
  },
  "epoxy-blank": {
    small: { material: 800, overage: 48, labor: 900, tooling: 220, travel: 0 },
    mid: { material: 7000, overage: 420, labor: 6000, tooling: 220, travel: 400 },
    big: { material: 40000, overage: 2400, labor: 25000, tooling: 800, travel: 2500 },
  },
  leveling: {
    small: { material: 800, labor: 900, tooling: 220, travel: 0 },
    mid: { material: 7000, labor: 6000, tooling: 220, travel: 400 },
    big: { material: 40000, labor: 25000, tooling: 800, travel: 2500 },
  },
  gyp: {
    small: { gyp: 5000, extras: 400, sand: 300, soundMat: 900, soundMatRolls: 20, labor: 3500, tooling: 100, travel: 0 },
    mid: { gyp: 40000, extras: 3000, sand: 2000, soundMat: 8000, soundMatRolls: 100, labor: 15000, tooling: 400, travel: 800 },
    big: { gyp: 400000, extras: 30000, sand: 20000, soundMat: 60000, soundMatRolls: 300, labor: 120000, tooling: 3000, travel: 8000 },
  },
};
// The inputs a family scales with the size of the job (everything in SIZES but these stays as typed).
const MATERIAL_INPUTS = {
  polish: ["material"], epoxy: ["material"], "epoxy-blank": ["material"], leveling: ["material"],
  gyp: ["gyp", "extras", "sand", "soundMat"],
};
const REMODEL_RATES = [0, 0.065, 0.07975, 0.08475, 0.0975, 0.1];
const FLAG_ORDER = [["local", "L"], ["taxable", "T"], ["prevailingWage", "P"], ["remodel", "R"], ["hardBid", "H"]];

function sized(family, size) {
  return Object.assign({ sf: DEFAULT_SF }, SIZES[family][size]);
}

function scaled(family, k) {
  const base = sized(family, "mid");
  return Object.fromEntries(Object.keys(base).map((name) => [name, name === "sf" ? base[name] : Math.round(base[name] * k)]));
}

/** Inputs that put the sub-total on exactly `target`: the labor input is searched for the largest
 *  figure that does not pass it (the sub-total never falls as labor rises), and the travel input, which
 *  is added in whole dollars, fills the rest. Material is NOT the lever: the Epoxy-style shipping tiers
 *  make the material total FALL when material crosses 5,000 or 10,000. */
function landSubTotal(run, target, base) {
  const at = (labor, travel) => run(Object.assign({}, base, { labor: labor, travel: travel })).subTotal;
  if (typeof at(0, 0) !== "number" || at(0, 0) > target) {
    throw new Error("the seed alone already passes a sub-total of " + target);
  }
  let lo = 0, hi = target;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (at(mid, 0) <= target) lo = mid; else hi = mid - 1;
  }
  const filler = target - at(lo, 0);
  const input = Object.assign({}, base, { labor: lo, travel: filler });
  const got = run(input).subTotal;
  if (got !== target) throw new Error("could not land the sub-total on " + target + " (got " + got + ")");
  return input;
}

function seedOf(family) {
  const s = sized(family, "small");
  const entries = [["sf", DEFAULT_SF]];
  for (const name of MATERIAL_INPUTS[family]) entries.push([name, s[name]]);
  if (s.overage !== undefined) entries.push(["overage", s.overage]);
  if (s.soundMatRolls !== undefined) entries.push(["soundMatRolls", s.soundMatRolls]);
  return Object.fromEntries(entries);
}

// ── the cases ────────────────────────────────────────────────────────────────
function buildCases(tab, map, family, cells) {
  const run = (input) => runCase(cells, tab, map, input);
  const cases = [];
  const ids = new Set();
  const add = (id, input, extra) => {
    if (ids.has(id)) throw new Error(tab + ": two cases are called " + id);
    ids.add(id);
    cases.push(Object.assign({ id: id, in: input }, extra || {}));
  };

  add("base/zero", { sf: DEFAULT_SF });
  for (const size of ["small", "mid", "big"]) add("size/" + size, sized(family, size));
  for (const k of [0.01, 0.05, 0.25, 0.5, 2, 5, 25, 100]) add("scale/x" + k, scaled(family, k));
  for (const sf of [1, 1000, 12500, 99999, 250000]) add("sf/" + sf, Object.assign(sized(family, "mid"), { sf: sf }));

  // the five job questions, every combination, at three sizes
  for (const size of ["small", "mid", "big"]) {
    for (let n = 0; n < 32; n++) {
      const settings = FLAG_ORDER.map(([name], i) => [name, Boolean((n >> i) & 1)]);
      const label = FLAG_ORDER.map(([, letter], i) => letter + (settings[i][1] ? 1 : 0)).join("");
      add("flags/" + size + "/" + label, Object.assign(sized(family, size), Object.fromEntries(settings)));
    }
  }

  // the remodel tax at the rates the counties charge, and at the rate the sheet types in itself
  const withExtras = Object.assign(sized(family, "mid"), { fees: 250, contingency: 500, remodel: true });
  add("remodel/sheet-own-rate", withExtras);
  for (const rate of REMODEL_RATES) add("remodel/" + rate, Object.assign({}, withExtras, { remodelPct: rate }));

  // fees and contingency
  for (const fees of [0, 1, 250, 1200, 5000]) {
    for (const contingency of [0, 500, 2500]) {
      add("money/fees" + fees + "/cont" + contingency, Object.assign(sized(family, "mid"), { fees: fees, contingency: contingency }));
    }
  }

  // the bond: the template ships it at 0, so the rate is typed
  for (const bondPct of [0.01, 0.0125, 0.02]) {
    for (const taxable of [true, false]) {
      for (const remodel of [false, true]) {
        const input = Object.assign(sized(family, "mid"), { bondPct: bondPct, taxable: taxable, fees: 500, contingency: 250 });
        if (remodel) { input.remodel = true; input.remodelPct = 0.07975; }
        add("bond/" + bondPct + "/T" + (taxable ? 1 : 0) + "/R" + (remodel ? 1 : 0), input);
      }
    }
  }

  // every edge of every ladder: one dollar below, on it, one dollar above
  const seed = seedOf(family);
  for (const ladder of ladderEdges(map)) {
    for (const edge of ladder.edges) {
      for (const off of [-1, 0, 1]) {
        const at = edge.at + off;
        const tag = "edge/" + ladder.cell + "/" + edge.at + "/" + (off > 0 ? "+" + off : String(off));
        if (ladder.on === "material") {
          const input = Object.assign({}, seed, { material: at, labor: 1500 });
          if (family === "epoxy-blank") input.overage = Math.ceil(at * 0.06);
          add(tag, input);
        } else if (ladder.needs) {
          for (const local of [true, false]) {
            const base = Object.assign({}, seed, { [ladder.needs]: true, local: local });
            add(tag + "/local" + (local ? 1 : 0), landSubTotal(run, at, base));
          }
        } else {
          add(tag, landSubTotal(run, at, Object.assign({}, seed)));
        }
      }
    }
  }
  return { cases: cases, run: run };
}

/** The travel sub-chain: nights of lodging and days of per diem worked out of the labor dollars.
 *  The sheet's quantity is `((labor - travel labor) / labor rate) / 8` (or / 10 on Gyp) and the case
 *  keeps the crew rows that made the labor, so a model that counts man-days can be set beside it. */
function lodgingCases(tab, map, family, cells) {
  const rate = cells.wb.getPlain(tab, map.rates.laborRate.addr);
  const hoursText = cells.wb.getPlain(tab, map.fixed.dayHours.addr);
  const hours = Number(/^(\d+) hour days$/.exec(hoursText)[1]);
  const crews = {
    one: [{ guys: 3, days: 5, rate: rate }],
    template: [{ guys: 3, days: 5, rate: rate }, { guys: 3, days: 0.5, rate: rate }, { guys: 3, days: 0.5, rate: rate }],
    mixedRates: [{ guys: 3, days: 5, rate: rate }, { guys: 2, days: 2, rate: 48 }],
    withTravel: [{ guys: 3, days: 5, rate: rate }],
  };
  const cases = [];
  for (const local of [false, true]) {
    for (const name of Object.keys(crews)) {
      const rows = crews[name];
      const crewDollars = rows.reduce((t, r) => t + r.guys * r.days * r.rate * hours, 0);
      const travelLabor = name === "withTravel" ? 18 * 1 * rate : 0;
      const input = {
        sf: DEFAULT_SF, local: local, labor: Math.ceil(crewDollars + travelLabor), travelLabor: travelLabor, travel: "template",
      };
      cases.push({ id: "lodging/" + name + "/local" + (local ? 1 : 0), in: input, rows: rows, hoursPerDay: hours });
    }
  }
  return cases;
}

// ── the probes: experiments upstream of the boundary ─────────────────────────
// The chain cases above all start AFTER the boundary, so they cannot show a rule that lives before it
// (a bag count, a shipping waiver, which system a price is keyed on). A probe starts from the template
// exactly as it stands, sets a few cells by address, reads a few cells, and puts everything back. Each
// one belongs to a rule of docs/kyle-workbook-odd-rules.md (`rule` is its id in
// backend/tests/fixtures/oracle/odd_rules.json), and backend/tests/test_kyle_odd_rules.py reads the
// recorded readings to decide whether the rule holds.
const LEVELING = "Leveling";
const GYP_TABS = P.priced.filter((t) => P.sheets[t].family === "gyp");

/** builders: tab -> [function (tab, ctx) -> probe]. ctx.read(addr) reads a cell as the template has it. */
const PROBE_BUILDERS = new Map();
function probeFor(tabs, builder) {
  for (const tab of tabs) {
    if (!PROBE_BUILDERS.has(tab)) PROBE_BUILDERS.set(tab, []);
    PROBE_BUILDERS.get(tab).push(builder);
  }
}

probeFor([LEVELING], () => ({
  id: "lodging-divisor", rule: "leveling-lodging-eight",
  note: "Lodging nights on Leveling: ((labor - travel labor) / labor rate) / 8. The tab's days are ten hours.",
  steps: [
    { label: "ten hour days, as the tab ships", set: { B4: "No", D48: 0, D49: 5049 }, read: ["E42", "C44", "B61", "D61"] },
    { label: "the day-length cell changed to 8 hour days", set: { B4: "No", D48: 0, D49: 5049, E42: "8 hour days" }, read: ["E42", "C44", "B61", "D61"] },
  ],
}));

probeFor([LEVELING], () => ({
  id: "travel-hour-when-local", rule: "leveling-travel-hour",
  note: "Travel labor on Leveling with the template's own hours, Local answered Yes and then No.",
  steps: [
    { label: "Local = Yes, as the tab ships", set: {}, read: ["B4", "A48", "B48", "C48", "D48"] },
    { label: "Local = No", set: { B4: "No" }, read: ["B4", "A48", "B48", "C48", "D48"] },
  ],
}));
probeFor([LEVELING], () => ({
  id: "travel-person-days", rule: "leveling-travel-hour",
  note: "The quantity on the travel line (A48) is PERSON-DAYS: the guys times the days of every crew row of the labor " +
    "table (A44:B46), added up. It is not a head count. Travel labor is that quantity x the travel hours (B48) x the " +
    "travel rate (C48). Local stays Yes, as the tab ships.",
  steps: [
    { label: "one crew row: 6 guys for 5 days", set: { A44: 6, B44: 5 }, read: ["B4", "A44", "B44", "A48", "B48", "C48", "D48"] },
    { label: "two crew rows: 3 guys for 4 days and 2 guys for 3 days", set: { A44: 3, B44: 4, A45: 2, B45: 3 },
      read: ["B4", "A44", "B44", "A45", "B45", "A48", "B48", "C48", "D48"] },
  ],
}));
probeFor(["Epoxy"], () => ({
  id: "travel-hours-when-local", rule: "leveling-travel-hour",
  note: "The same reading on Epoxy, for contrast: its travel hours are typed and ship as 0.",
  steps: [{ label: "Local = Yes, as the tab ships", set: {}, read: ["B4", "A52", "B52", "C52", "D52"] }],
}));
probeFor(["Polish"], () => ({
  id: "travel-hours-when-local", rule: "leveling-travel-hour",
  note: "The same reading on Polish, for contrast.",
  steps: [{ label: "Local = Yes, as the tab ships", set: {}, read: ["B4", "A44", "B44", "C44", "D44"] }],
}));

probeFor([LEVELING], () => ({
  id: "overage-powders-only", rule: "leveling-overage-powders",
  note: "Discount / Overage on Leveling is B38 times the powder rows D21:D27 only. A sand row is not touched by it.",
  steps: [
    { label: "10% overage, nothing in a powder row", set: { B38: 0.1 }, read: ["D37", "D38", "D40"] },
    { label: "10% overage, 1,000 in a powder row", set: { B38: 0.1, D22: 1000 }, read: ["D37", "D38", "D40"] },
    { label: "10% overage, 1,000 in a sand row", set: { B38: 0.1, D30: 1000 }, read: ["D37", "D38", "D40"] },
  ],
}));
probeFor(["Epoxy blank"], () => ({
  id: "overage-all-rows", rule: "leveling-overage-powders",
  note: "The same line on Epoxy blank, for contrast: its overage is taken on every material row.",
  steps: [
    { label: "6% overage, nothing typed", set: {}, read: ["B38", "D37", "D38"] },
    { label: "1,000 in a liquids row", set: { D22: 1000 }, read: ["B38", "D37", "D38"] },
    { label: "1,000 in a cove row", set: { D33: 1000 }, read: ["B38", "D37", "D38"] },
  ],
}));

probeFor(["Epoxy"], (tab, ctx) => {
  const quartz = ctx.read("R189");
  const SET = { AE126: 100, W148: 3, W145: 1 };
  return {
    id: "cove-aggregate-system-1", rule: "cove-aggregate-system-1",
    note: "System 2's cove aggregate (AF126) prices the sand as a quartz or a silica by asking whether SYSTEM 1's " +
      "option (A22) is one of three quartz systems. Quartz is priced at 3 and silica at 1 here, 100 lbs of aggregate.",
    steps: [
      { label: "System 1 is the quartz system, System 2 is something else",
        set: Object.assign({ A22: quartz, A26: "something else" }, SET), read: ["A22", "A26", "AE126", "AF126"] },
      { label: "System 1 is something else, System 2 is the quartz system",
        set: Object.assign({ A22: "something else", A26: quartz }, SET), read: ["A22", "A26", "AE126", "AF126"] },
      { label: "both are the quartz system",
        set: Object.assign({ A22: quartz, A26: quartz }, SET), read: ["A22", "A26", "AE126", "AF126"] },
    ],
  };
});

probeFor(GYP_TABS, (tab, ctx) => {
  const truck = ctx.fixed.truckload;
  const SET = (rolls) => ({ E36: 10000, B36: rolls });
  return {
    id: "sound-mat-truckload", rule: "gyp-mat-shipping-truckload",
    note: "Shipping on the sound mat (10% of its $10,000 here) is charged only while the roll count B36 is BELOW a truckload H36.",
    steps: [truck - 1, truck, truck + 1].map((rolls) => ({
      label: rolls + " rolls (a truckload is " + truck + ")", set: SET(rolls), read: ["B36", "H36", "E36", "E40"],
    })),
  };
});

probeFor(GYP_TABS, (tab, ctx) => {
  // The sand lookup is `IF(G11=<key>,<value>,...)`; its address differs on the Gyp (FR) tab.
  const m = /IF\(G11=([A-Z]+\d+),([A-Z]+\d+),/.exec(ctx.formula("B33"));
  if (!m) throw new Error(tab + ": B33 no longer reads IF(G11=<key>,<value>,...)");
  return {
    id: "bags-fractional-sand-follows", rule: "gyp-bags-fractional",
    note: "Bags of gypsum are (SF / yield per bag) x (1 + waste), never rounded; sand in tons comes off the SUM of those " +
      "fractional bags: (pounds of sand per bag x bags / 2000) x (1 + sand waste).",
    steps: [{
      label: "1,000, 2,000 and 500 SF in the three areas",
      set: { F23: 1000, F24: 2000, F25: 500 },
      read: ["F23", "F24", "F25", "J23", "J24", "J25", "G18", "G19", "B23", "B24", "B25", "H33", m[2], "B33"],
    }],
  };
});

/** Put the tab back to the template for the probes: the cases leave the boundary cells set. */
function restoreTemplate(cells, tab, map) {
  for (const group of [map.flags, map.inputs, map.rates]) {
    for (const name of Object.keys(group)) cells.restore(tab, group[name].addr);
  }
}

function runProbe(cells, tab, probe) {
  const steps = probe.steps.map((step) => {
    const touched = Object.keys(step.set);
    for (const addr of touched) cells.put(tab, addr, step.set[addr]);
    const got = step.read.map((addr) => [addr, cells.wb.getPlain(tab, addr)]);
    for (const addr of touched) cells.restore(tab, addr);
    return { label: step.label, set: step.set, got: Object.fromEntries(got) };
  });
  return { id: probe.id, rule: probe.rule, note: probe.note, steps: steps };
}

// ── putting a tab together ───────────────────────────────────────────────────
function buildSheet(tab, cells) {
  const map = P.sheets[tab];
  const family = map.family;
  const built = buildCases(tab, map, family, cells);
  const vectors = built.cases.concat(lodgingCases(tab, map, family, cells));
  for (const v of vectors) v.out = runCase(cells, tab, map, v.in);
  restoreTemplate(cells, tab, map);
  const fixed = Object.fromEntries(Object.keys(map.fixed).map((name) => [name, cells.wb.getPlain(tab, map.fixed[name].addr)]));
  const ctx = {
    fixed: fixed,
    read: (addr) => cells.wb.getPlain(tab, addr),
    formula: (addr) => String(cells.wb.serialized(tab, addr)),
  };
  const probes = (PROBE_BUILDERS.get(tab) || []).map((build) => runProbe(cells, tab, build(tab, ctx)));
  return { schema: SCHEMA, sheet: tab, slug: map.slug, family: family, fixed: fixed, vectors: vectors, probes: probes };
}

/** One case per line, so a changed answer is a one-line diff somebody can read. */
function sheetText(doc) {
  const head = ["schema", "sheet", "slug", "family", "fixed"].map((k) => JSON.stringify(k) + ": " + JSON.stringify(doc[k]));
  const lines = (list) => list.map((x) => JSON.stringify(x)).join(",\n");
  return "{\n" + head.join(",\n") + ",\n\"vectors\": [\n" + lines(doc.vectors) + "\n],\n\"probes\": [\n" + lines(doc.probes) + "\n]\n}\n";
}

function main() {
  const args = process.argv.slice(2);
  const write = args.includes("--write");
  const onlyAt = args.indexOf("--only");
  const only = onlyAt >= 0 ? args[onlyAt + 1] : null;
  if (write && only) fail("--only compares one tab; --write rewrites them all (meta.json has to describe the whole set)");

  const hfFile = E.hyperformulaPath();
  const shipped = E.assertShippedBytes(hfFile);
  const HF = E.loadEngine({ plugin: true });
  const spec = loadSpec();
  const wb = E.build(HF, spec);
  if (wb.warnings.length) fail("the workbook did not load cleanly:\n  " + wb.warnings.join("\n  "));
  const cells = makeCells(wb);

  const check = selfCheck(cells, spec);
  if (check.bad.length) fail("SELF-CHECK FAILED: the engine does not reproduce the values saved in the template:\n  " + check.bad.join("\n  "));

  const tabs = only ? P.priced.filter((t) => P.sheets[t].slug === only) : P.priced;
  if (!tabs.length) fail("no priced tab has the slug " + only);
  const files = new Map();
  const counts = [];
  for (const tab of tabs) {
    const doc = buildSheet(tab, cells);
    if (args.includes("--print-probes")) {
      for (const p of doc.probes) console.log(JSON.stringify(p, null, 1));
    }
    files.set(doc.slug + ".json", sheetText(doc));
    counts.push([tab, { slug: doc.slug, family: doc.family, vectors: doc.vectors.length, probes: doc.probes.length }]);
  }

  if (!only) {
    const tmpl = templateHash(P.priced);
    const ladders = P.priced.map((tab) => [tab, ladderEdges(P.sheets[tab]).map((l) => ({
      cell: l.cell, on: l.on, needs: l.needs, edges: l.edges,
    }))]);
    const aliases = Object.fromEntries(wb.aliases);
    // `files` holds only the recorded sheet files at this point (meta.json is added to it below), and a
    // hash goes in for every one of them. The cell maps are hashed as the data this run just read.
    const integrity = {
      about: "sha256 of each recorded sheet file (its text with every CRLF read as LF) and of the cell-map data in " +
        "frontend/js/bid-profiles.js that this run read, hashed by backend/tests/js/oracle-integrity.js. Written only " +
        "when the oracle regenerates; backend/tests/test_workbook_oracle.py recomputes them in CI, so a recorded " +
        "answer edited by hand, even one that still adds up, fails there with 're-run the oracle'",
      files: Object.fromEntries(Array.from(files).map(([name, text]) => [name, I.textSha256(text)])),
      profiles: { file: "frontend/js/bid-profiles.js", sheetFields: I.SHEET_FIELDS, sha256: I.profilesSha256(P) },
    };
    const meta = {
      schema: SCHEMA,
      generator: "backend/tests/js/workbook-oracle.js",
      engine: {
        hyperformula: { version: shipped.version, sri: shipped.sri, bytes: shipped.bytes },
        plugin: { file: "frontend/js/xl-excel-rounding.js", sha256: E.textSha256(E.SHIPPED_PLUGIN) },
        options: E.PAGE_OPTIONS,
        namesRegistered: wb.namesRegistered,
        aliases: aliases,
      },
      template: {
        file: "backend/templates/estimate_sheet_5.7.xlsx",
        sheets: P.priced,
        hash: tmpl.hash,
        cells: tmpl.cells,
        names: tmpl.names,
        about: "sha256 over the sorted (sheet, address, formula or constant) lines of the priced sheets, then the " +
          "sorted (scope, name, expression) lines of every defined name the page registers, from " +
          "backend/tests/_oracle_support.py normalised_cells() and normalised_names(); it ignores cached values and " +
          "how the file was saved",
      },
      integrity: integrity,
      selfCheck: check.report,
      ladders: Object.fromEntries(ladders),
      sheets: Object.fromEntries(counts),
    };
    files.set("meta.json", JSON.stringify(meta, null, 1) + "\n");
  }

  let differing = 0;
  for (const [name, text] of files) {
    const file = path.join(OUT_DIR, name);
    if (write) {
      fs.mkdirSync(OUT_DIR, { recursive: true });
      fs.writeFileSync(file, text);
      console.log("wrote " + path.relative(REPO, file) + "  (" + text.length + " bytes)");
      continue;
    }
    const have = fs.existsSync(file) ? fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n") : null;
    if (have === text) continue;
    differing++;
    console.error("DIFFERS: " + path.relative(REPO, file) + (have === null ? " (missing)" : ""));
    if (have !== null) reportDifference(have, text);
  }
  if (differing) fail(differing + " recorded file(s) differ from what the oracle computes now. If that is the change you meant, re-run with --write and review the diff.");
  if (!write) console.log("the oracle reproduces " + files.size + " recorded file(s) exactly");
}

/** Name the first few cases that differ between the recorded file and the new one. */
function reportDifference(haveText, wantText) {
  let have, want;
  try { have = JSON.parse(haveText); want = JSON.parse(wantText); } catch (e) { console.error("  (a file is not valid JSON)"); return; }
  if (!Array.isArray(have.vectors)) {
    // meta.json: name the top-level parts that moved (template, integrity, selfCheck, ...)
    const keys = Array.from(new Set(Object.keys(have).concat(Object.keys(want))));
    console.error("  (meta.json differs in: " + keys.filter((k) => JSON.stringify(have[k]) !== JSON.stringify(want[k])).join(", ") + ")");
    return;
  }
  const was = new Map(have.vectors.map((v) => [v.id, JSON.stringify(v)]));
  let shown = 0;
  for (const v of want.vectors) {
    const now = JSON.stringify(v);
    if (was.get(v.id) !== now && shown++ < 5) console.error("  case " + v.id + "\n    recorded: " + was.get(v.id) + "\n    now:      " + now);
  }
  if (JSON.stringify(have.probes) !== JSON.stringify(want.probes)) console.error("  the probes differ");
}

try {
  main();
} catch (e) {
  // HyperFormula's minified bundle prints itself into a stack trace; keep the lines that are ours.
  const lines = String(e && e.stack ? e.stack : e).split("\n").map((l) => l.slice(0, 240));
  console.error(lines.filter((l) => !/hyperformula\.full\.min\.js/.test(l)).slice(0, 14).join("\n"));
  process.exit(1);
}
