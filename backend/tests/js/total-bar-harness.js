// Runs the Estimate page's REAL updateTotalBarFromHF against a stub engine and reports what the
// sticky Total bar shows.
//
// THE BUG IT COVERS (Hanz, 2026-09-25, on staging): the base bid was a COPIED tab, "Epoxy copy",
// at $14,224, and its own Total Base Bid cell said $14,224, while the bar at the bottom read the
// original Epoxy tab's $7,447. The bar always summed Epoxy and/or Polish; the lump sum the proposal
// and the board use has followed the designated base tab for a long time.
//
// Lifted, never re-typed: TOTAL_CELLS, the role vocabulary, roleFor, totalCellsFor, resolveBaseTab
// and fmtMoney all come out of the shipped file, bound by name.
//
// Usage: node total-bar-harness.js <frontend-dir>   ->  one line of JSON
"use strict";
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(process.argv[2], "js", "estimate-review.js"), "utf8");
const NL = String.fromCharCode(10);

function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + what + " -- rewrite this harness, don't stub it");
  return m[0];
}
function lift(name, deps) {
  const re = new RegExp("^function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name + " -- rewrite this harness, don't stub it");
  const names = Object.keys(deps);
  return new Function(...names, m[0] + NL + "return " + name + ";")(...names.map(k => deps[k]));
}
function liftExpr(re, name, deps) {
  const names = Object.keys(deps);
  return new Function(...names, grab(re, name) + NL + "return " + name + ";")(...names.map(k => deps[k]));
}

const VOCAB = new Function([
  grab(/^const GYP_BASE = .*$/m, "GYP_BASE"),
  grab(/^const GYP_SHEETS = \[[\s\S]*?\];$/m, "GYP_SHEETS"),
  grab(/^const SEAL_SHEETS = \[[\s\S]*?\];$/m, "SEAL_SHEETS"),
  grab(/^const BASE_ROLE = \{[\s\S]*?\};$/m, "BASE_ROLE"),
  grab(/^GYP_SHEETS\.forEach\(\(s\) => \{ BASE_ROLE.*$/m, "the gyp role loop"),
  grab(/^SEAL_SHEETS\.forEach\(\(s\) => \{ BASE_ROLE.*$/m, "the seal role loop"),
  grab(/^const PRICED_ROLES = new Set\(\[[^\]]*\]\);$/m, "PRICED_ROLES"),
  grab(/^const OPTION_ONLY_ROLES = new Set\(\[[^\]]*\]\);$/m, "OPTION_ONLY_ROLES"),
  grab(/^const TOTAL_CELLS = \{[\s\S]*?^\};$/m, "TOTAL_CELLS"),
].join(NL) + NL + "return { GYP_BASE, BASE_ROLE, PRICED_ROLES, OPTION_ONLY_ROLES, TOTAL_CELLS };")();

function bar(opts) {
  const state = Object.assign({ work_type: "epoxy", base_tab_id: null, tab_copies: [], tab_structs: [] },
                              opts.state || {});
  const values = opts.values || {};
  const HF = { ready: true, getValue: (s, a) => (values[s] || {})[a] ?? null };
  const nodes = {};
  for (const id of ["tb-material", "tb-labor", "tb-tooling", "tb-total", "tb-psf"]) nodes[id] = { textContent: "<untouched>" };
  const document = { getElementById: (id) => nodes[id] || null };
  const tabs = [];
  const deps = { state, tabs, HF, document, GYP_BASE: VOCAB.GYP_BASE, BASE_ROLE: VOCAB.BASE_ROLE,
                 PRICED_ROLES: VOCAB.PRICED_ROLES, OPTION_ONLY_ROLES: VOCAB.OPTION_ONLY_ROLES,
                 TOTAL_CELLS: VOCAB.TOTAL_CELLS };
  deps._shiftIdx = lift("_shiftIdx", deps);
  deps.structOpsFor = liftExpr(/^function structOpsFor\(sheetId\) .*$/m, "structOpsFor", { state });
  deps.txAddr = lift("txAddr", deps);
  deps.roleFor = lift("roleFor", deps);
  deps.isPricedRole = liftExpr(/^const isPricedRole = .*$/m, "isPricedRole", { PRICED_ROLES: VOCAB.PRICED_ROLES });
  deps.isOptionOnlyRole = liftExpr(/^const isOptionOnlyRole = .*$/m, "isOptionOnlyRole",
                                   { OPTION_ONLY_ROLES: VOCAB.OPTION_ONLY_ROLES });
  deps.pricedTabs = liftExpr(/^function pricedTabs\(\) .*$/m, "pricedTabs", { tabs, isPricedRole: deps.isPricedRole });
  deps.basePricedTabs = liftExpr(/^const basePricedTabs = .*$/m, "basePricedTabs",
                                 { pricedTabs: deps.pricedTabs, isOptionOnlyRole: deps.isOptionOnlyRole });
  deps.totalCellsFor = lift("totalCellsFor", deps);
  deps.resolveBaseTab = lift("resolveBaseTab", deps);
  deps.fmtMoney = lift("fmtMoney", deps);
  // The page's tab list: the workbook tabs this test needs, plus any copies, with the real roles.
  for (const id of ["Epoxy", "Polish", VOCAB.GYP_BASE, "Seal"]) tabs.push({ id, role: deps.roleFor(id), kind: "base" });
  for (const c of state.tab_copies) tabs.push({ id: c.id, role: c.role || "epoxy", kind: "copy", source: c.source });
  lift("updateTotalBarFromHF", deps)();
  const text = {};
  for (const k of Object.keys(nodes)) text[k] = nodes[k].textContent;
  return text;
}

const E = VOCAB.TOTAL_CELLS.Epoxy, P = VOCAB.TOTAL_CELLS.Polish;
const epoxyVals = { [E.total]: 7447, [E.material]: 1076, [E.labor]: 1584, [E.tooling]: 220, [E.psf]: 75.22 };
const copyVals = { [E.total]: 14224, [E.material]: 2100, [E.labor]: 3000, [E.tooling]: 400, [E.psf]: 17.78 };
const polishVals = { [P.total]: 13585, [P.material]: 900, [P.labor]: 2000, [P.tooling]: 300, [P.psf]: 9.5 };
const copies = [{ id: "Copy1", source: "Epoxy", role: "epoxy" }];

const out = {
  // Hanz's case: the copy is the designated base.
  copyIsBase: bar({ state: { base_tab_id: "Copy1", tab_copies: copies },
                    values: { Epoxy: epoxyVals, Copy1: copyVals, Polish: polishVals } }),
  // An inverted base on an epoxy job: Polish designated.
  polishIsBase: bar({ state: { base_tab_id: "Polish", tab_copies: copies },
                      values: { Epoxy: epoxyVals, Copy1: copyVals, Polish: polishVals } }),
  // Nothing designated: the old behaviour, unchanged.
  noBase: bar({ state: { tab_copies: copies },
                values: { Epoxy: epoxyVals, Copy1: copyVals, Polish: polishVals } }),
  comboNoBase: bar({ state: { work_type: "combo" },
                     values: { Epoxy: epoxyVals, Polish: polishVals } }),
};
console.log(JSON.stringify(out));
