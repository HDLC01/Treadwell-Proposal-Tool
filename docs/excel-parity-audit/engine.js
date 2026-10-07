"use strict";
/* The ONE way this repository builds Kyle's workbook in HyperFormula outside the browser.
 *
 * Two tools stand on it and nothing else does:
 *   - docs/excel-parity-audit/one-config.js   compares the engine with Excel on real estimates
 *   - backend/tests/js/workbook-oracle.js     uses the engine as the answer key for every v2 tab
 *
 * WHAT "THE SAME ENGINE AS THE LIVE PAGE" MEANS HERE, point by point.
 *
 *   1. THE SAME BYTES. The Estimate Review page loads hyperformula@2.7.1/dist/hyperformula.full.min.js
 *      from a CDN with a pinned sha384. This module loads that very file out of an npm install of
 *      hyperformula@2.7.1 and refuses to go on unless its sha384 is the one frontend/estimate-review.html
 *      pins (assertShippedBytes). Nothing from "the node build" (commonjs/) is used: it is a different
 *      file with a different export shape.
 *   2. THE SAME PLUGIN. The page registers frontend/js/xl-excel-rounding.js before it builds an engine,
 *      so that ROUNDUP and CEILING round the way Excel's do. That file is loaded here AS IT SHIPS,
 *      through a two-line shim: a global `HyperFormula` (the bundle's export, which carries
 *      FunctionPlugin and FunctionArgumentType on the class exactly as the browser global does) and a
 *      global `window` for the flag the plugin sets. The audit used to carry its own copy of the plugin
 *      class, which could drift from the one that ships; it no longer does.
 *   3. THE SAME OPTIONS. PAGE_OPTIONS is what estimate-review.js passes to HyperFormula.buildEmpty
 *      (HF.init). backend/tests/test_workbook_oracle.py lifts that object out of the page, runs it
 *      against a fake HyperFormula and requires it to equal PAGE_OPTIONS, so this cannot go stale.
 *   4. THE SAME LOAD ORDER. Every sheet is added first (cross-sheet references need them all),
 *      then the named expressions are registered with the page's alias rule for the names
 *      HyperFormula rejects (Glaze4 becomes Glaze_4, and every formula token is rewritten to match),
 *      then each sheet's cells go in as formula text when there is one and as the value when there is
 *      not (HF.loadSheet).
 *
 * ONE CONFIGURATION PER PROCESS. HyperFormula's function registry is global to the class and
 * unregisterFunction does not reliably undo a registration, so a second configuration measured in
 * the same process silently inherits the first one's plugin. That is how an earlier version of the
 * audit reported 15 wrong cells instead of 98. loadEngine refuses a second, different configuration.
 */
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const REPO = path.resolve(__dirname, "..", "..");
const SHIPPED_PLUGIN = path.join(REPO, "frontend", "js", "xl-excel-rounding.js");
const ESTIMATE_REVIEW_HTML = path.join(REPO, "frontend", "estimate-review.html");
const ESTIMATE_REVIEW_JS = path.join(REPO, "frontend", "js", "estimate-review.js");

/** What estimate-review.js hands HyperFormula.buildEmpty (HF.init). smartRounding is OFF on purpose
 *  and the reason is written at length in that file: ON, it rounded every value read out of the
 *  engine to five significant figures and double-rounded the workbook's own ROUNDUPs upward. */
const PAGE_OPTIONS = Object.freeze({ licenseKey: "gpl-v3", smartRounding: false });

// ── finding and checking the bytes ───────────────────────────────────────────
/** The absolute path of hyperformula.full.min.js, found by node's own lookup: a node_modules next to or
 *  above this file (what `npm install hyperformula@2.7.1` inside docs/excel-parity-audit leaves, gitignored),
 *  or the folders of NODE_PATH. */
function hyperformulaPath() {
  try {
    return require.resolve("hyperformula/dist/hyperformula.full.min.js");
  } catch (e) {
    throw new Error("hyperformula is not installed. It is deliberately NOT a dependency of this repo (there is " +
      "no package.json). Install the version the page ships, outside the repo or into a gitignored " +
      "node_modules, and point node at it:\n" +
      "    npm i --no-save --prefix <scratch dir> hyperformula@2.7.1\n" +
      "    NODE_PATH=<scratch dir>/node_modules node <script>");
  }
}

/** "sha384-<base64>", the form a subresource-integrity attribute takes. */
function sriOf(bytes) {
  return "sha384-" + crypto.createHash("sha384").update(bytes).digest("base64");
}

/** sha256 of a text file with every line ending read as LF, so a Windows checkout (CRLF) and a
 *  Linux one (LF) of the same file give the same answer. */
function textSha256(file) {
  const text = fs.readFileSync(file, "utf8").replace(/^﻿/, "").replace(/\r\n/g, "\n");
  return crypto.createHash("sha256").update(text, "utf8").digest("hex");
}

/** The HyperFormula <script> the page pins: { version, src, sri }. Reads the tag by position, with no
 *  pattern run over markup; throws unless exactly one tag names the package. */
function pinnedSri(html) {
  const needle = "hyperformula@";
  const found = [];
  let from = 0;
  for (;;) {
    const at = html.indexOf(needle, from);
    if (at < 0) break;
    from = at + needle.length;
    const open = html.lastIndexOf("<script", at);
    const close = html.indexOf(">", at);
    if (open < 0 || close < 0) continue;
    const tag = html.slice(open, close + 1);
    const srcAt = tag.indexOf("src=\"");
    const srcEnd = srcAt < 0 ? -1 : tag.indexOf("\"", srcAt + 5);
    const intAt = tag.indexOf("integrity=\"");
    const intEnd = intAt < 0 ? -1 : tag.indexOf("\"", intAt + 11);
    if (srcEnd < 0 || intEnd < 0) continue;
    const src = tag.slice(srcAt + 5, srcEnd);
    const verAt = src.indexOf(needle) + needle.length;
    const verEnd = src.indexOf("/", verAt);
    found.push({ version: src.slice(verAt, verEnd), src: src, sri: tag.slice(intAt + 11, intEnd) });
  }
  if (found.length !== 1) {
    throw new Error("expected exactly one <script> that loads hyperformula with an integrity attribute, found " + found.length);
  }
  return found[0];
}

/** The pinned tag out of frontend/estimate-review.html. */
function pagePin(htmlFile) {
  return pinnedSri(fs.readFileSync(htmlFile || ESTIMATE_REVIEW_HTML, "utf8"));
}

/** Prove the bundle on disk is the one the page ships. Returns { version, sri, bytes, file }.
 *  Throws, naming both hashes, when it is not. */
function assertShippedBytes(file, htmlFile) {
  const bytes = fs.readFileSync(file);
  const sri = sriOf(bytes);
  const pin = pagePin(htmlFile);
  if (sri !== pin.sri) {
    throw new Error("the installed " + file + " is NOT the HyperFormula the page ships.\n" +
      "  installed: " + sri + "\n  pinned in estimate-review.html: " + pin.sri + " (" + pin.src + ")\n" +
      "Install exactly the pinned version (npm i --no-save --prefix <dir> hyperformula@" + pin.version + ").");
  }
  const pkg = JSON.parse(fs.readFileSync(path.join(path.dirname(file), "..", "package.json"), "utf8"));
  if (pkg.version !== pin.version) {
    throw new Error("package.json says hyperformula " + pkg.version + " but the page pins " + pin.version);
  }
  return { version: pin.version, sri: sri, bytes: bytes.length, file: file };
}

// ── installing the engine, once, the way the browser has it ──────────────────
let installed = null;

/** Load HyperFormula the way a page does and return the class.
 *    opts.plugin  false = leave HyperFormula's own ROUNDUP and CEILING (the audit's "before" rows).
 *                 default true = register frontend/js/xl-excel-rounding.js exactly as it ships.
 *    opts.file    the hyperformula.full.min.js to use (default: hyperformulaPath()).
 *  Idempotent for the same configuration; throws for a different one (see the top of this file). */
function loadEngine(opts) {
  const withPlugin = !(opts && opts.plugin === false);
  if (installed) {
    if (installed.withPlugin !== withPlugin) {
      throw new Error("this process already loaded the engine " + (installed.withPlugin ? "WITH" : "WITHOUT") +
        " the Excel rounding plugin; HyperFormula's registry is global, so measure each configuration in its own process");
    }
    return installed.HyperFormula;
  }
  const file = (opts && opts.file) || hyperformulaPath();
  // The shim. `require` of the full bundle returns the class itself with FunctionPlugin,
  // FunctionArgumentType and the rest hung on it, which is what `window.HyperFormula` is in a page.
  const HyperFormula = require(file);
  if (typeof HyperFormula !== "function" || !HyperFormula.FunctionPlugin || !HyperFormula.FunctionArgumentType) {
    throw new Error(file + " did not export the HyperFormula class with FunctionPlugin on it; is it the full UMD bundle?");
  }
  globalThis.HyperFormula = HyperFormula;
  if (typeof globalThis.window === "undefined") globalThis.window = {};
  if (withPlugin) {
    require(SHIPPED_PLUGIN);                       // an IIFE: registers on load, sets window.TW_EXCEL_ROUNDING
    if (globalThis.window.TW_EXCEL_ROUNDING !== true) {
      throw new Error("frontend/js/xl-excel-rounding.js ran but did not register (window.TW_EXCEL_ROUNDING is not true)");
    }
  }
  installed = { HyperFormula: HyperFormula, withPlugin: withPlugin, file: file };
  return HyperFormula;
}

// ── addresses and values ─────────────────────────────────────────────────────
/** "AB12" -> { col: 27, row: 11 } (zero based, as HyperFormula wants). */
function colRow(addr) {
  const m = /^([A-Z]{1,3})(\d+)$/.exec(addr);
  if (!m) throw new Error("not a cell address: " + addr);
  let col = 0;
  for (const ch of m[1]) col = col * 26 + (ch.charCodeAt(0) - 64);
  return { col: col - 1, row: parseInt(m[2], 10) - 1 };
}

/** A value read out of the engine as plain data: numbers, text and booleans as they are, an empty
 *  cell as null, an error (HyperFormula hands back an object) as its text, "#DIV/0!". */
function plain(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "object") return v.value !== undefined ? String(v.value) : "#ERROR!";
  return v;
}

/** The page's rule for a name HyperFormula will not take: letters then only digits look like a cell
 *  reference ("Glaze4"), so the name is registered as Glaze_4; a name with no trailing digits gets "_n". */
function aliasFor(name) {
  const a = name.replace(/(\d+)$/, "_$1");
  return a === name ? name + "_n" : a;
}

function escapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** estimate-review.js HF.rewriteNames, as a function of the alias table (a Map of name to alias):
 *  every whole-token use of an aliased name inside a formula is rewritten, never a name that merely
 *  contains it. A value that is not a formula is returned as it is. */
function makeRewriter(aliases) {
  const patterns = [];
  for (const [orig, alias] of aliases) {
    patterns.push([new RegExp("(?<![A-Za-z0-9_.])" + escapeRegExp(orig) + "(?![A-Za-z0-9_.])", "g"), alias]);
  }
  return function rewrite(formula) {
    if (typeof formula !== "string" || formula.charAt(0) !== "=") return formula;
    let out = formula;
    for (const [re, alias] of patterns) out = out.replace(re, alias);
    return out;
  };
}

// ── building the workbook ────────────────────────────────────────────────────
/** Build the whole workbook in an engine.
 *
 *  `spec` is { order: [sheet names], sheets: { name: { cells: [...] } }, names: [...] } where a cell is
 *  { addr, row, col, formula?, value? } with row and col one-based (the shape GET /api/sheet serves and
 *  extract.py writes) and a name is { name, expression, scope? }.
 *
 *  Returns a Workbook: { hf, sheetNames, aliases (Map), warnings, sheetId, get, getPlain, serialized,
 *  set, batch, destroy }. A failure the page would only log (a sheet that will not load, a name that
 *  will not register even under its alias) is collected in `warnings` for the caller to refuse. */
function build(HyperFormula, spec, opts) {
  const options = Object.assign({}, (opts && opts.options) || PAGE_OPTIONS);
  const hf = HyperFormula.buildEmpty(options);
  const ids = new Map();
  for (const name of spec.order) {
    hf.addSheet(name);
    ids.set(name, hf.getSheetId(name));
  }
  const warnings = [];
  const aliases = new Map();
  let registered = 0;
  for (const n of spec.names || []) {
    const scopeId = (n.scope && ids.has(n.scope)) ? ids.get(n.scope) : undefined;
    let regName = n.name;
    try {
      if (!hf.isItPossibleToAddNamedExpression(regName, n.expression, scopeId)) {
        regName = aliasFor(n.name);
        aliases.set(n.name, regName);
      }
      if (scopeId !== undefined) hf.addNamedExpression(regName, n.expression, scopeId);
      else hf.addNamedExpression(regName, n.expression);
      registered++;
    } catch (e) {
      aliases.delete(n.name);
      warnings.push("named expression " + n.name + " would not register: " + (e && e.message));
    }
  }
  const rewrite = makeRewriter(aliases);
  for (const name of spec.order) {
    const cells = spec.sheets[name].cells;
    let maxRow = 0, maxCol = 0;
    for (const c of cells) { if (c.row > maxRow) maxRow = c.row; if (c.col > maxCol) maxCol = c.col; }
    const data = [];
    for (let r = 0; r < maxRow; r++) data.push(new Array(maxCol).fill(null));
    for (const c of cells) {
      // HF.loadSheet: the FORMULA TEXT when there is one, otherwise the value.
      data[c.row - 1][c.col - 1] = c.formula != null ? rewrite(c.formula) : (c.value === undefined ? null : c.value);
    }
    try {
      hf.setSheetContent(ids.get(name), data);
    } catch (e) {
      warnings.push("setSheetContent failed for " + name + ": " + (e && e.message));
    }
  }

  function address(sheet, addr) {
    if (!ids.has(sheet)) throw new Error("no sheet named " + sheet);
    const rc = colRow(addr);
    return { sheet: ids.get(sheet), col: rc.col, row: rc.row };
  }
  return {
    hf: hf,
    sheetNames: spec.order.slice(),
    aliases: aliases,
    namesRegistered: registered,
    warnings: warnings,
    sheetId: function (name) { return ids.get(name); },
    /** the raw engine value (an error is an object) */
    get: function (sheet, addr) { return hf.getCellValue(address(sheet, addr)); },
    /** the value as plain data: errors as "#DIV/0!", an empty cell as null */
    getPlain: function (sheet, addr) { return plain(hf.getCellValue(address(sheet, addr))); },
    /** what the cell holds: its formula text ("=...") or its constant */
    serialized: function (sheet, addr) { return hf.getCellSerialized(address(sheet, addr)); },
    /** put a constant, or a formula text, into a cell; formulas get the page's name aliases */
    set: function (sheet, addr, content) {
      return hf.setCellContents(address(sheet, addr), rewrite(content));
    },
    batch: function (fn) { return hf.batch(fn); },
    destroy: function () { hf.destroy(); },
  };
}

module.exports = {
  REPO, SHIPPED_PLUGIN, ESTIMATE_REVIEW_HTML, ESTIMATE_REVIEW_JS, PAGE_OPTIONS,
  hyperformulaPath, sriOf, textSha256, pinnedSri, pagePin, assertShippedBytes,
  loadEngine, build, colRow, plain, aliasFor, makeRewriter, escapeRegExp,
};
