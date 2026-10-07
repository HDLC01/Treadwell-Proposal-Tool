"use strict";
/* PHASE 7b, THE TAKEOFF STEP: a test copy of a split project through the REAL page.
 *
 * The page under test is executed whole (js/polish-estimate.js, through polish-estimate-harness.js's own boot
 * code: everything above its `(async function () {` scenario block is reused, so there is one DOM stub and
 * one fetch stub, not two). The scenarios are in condition-cells-takeoff-scenarios.js and are the harness
 * saved-bid-harness.js uses, for the same reason: what the page does with a draft it is handed.
 *
 * Usage: node condition-cells-takeoff-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");

const BASE = path.join(__dirname, "polish-estimate-harness.js");
let code = fs.readFileSync(BASE, "utf8").replace(/\r\n/g, "\n");
const MARK = "(async function () {\n  // ── A. the takeoff row";
const at = code.indexOf(MARK);
if (at < 0) throw new Error("polish-estimate-harness.js scenario block moved; update the marker");
let head = code.slice(0, at);
// Export only what these scenarios drive, so the same harness can boot a tree whose page lacks the rest.
const EXPORTS_RE = /const EXPORTS = `[\s\S]*?`;\n/;
if (!EXPORTS_RE.test(head)) throw new Error("polish-estimate-harness.js no longer declares EXPORTS; update this file");
head = head.replace(EXPORTS_RE, "const EXPORTS = `\n  return { init: init, adopt: adopt, saveSoon: saveSoon, bid: bid, model: function () { return M; }, state: function () { return state; } };\n`;\n");

const tail = fs.readFileSync(path.join(__dirname, "condition-cells-takeoff-scenarios.js"), "utf8");
const m = new Module(BASE, module);
m.filename = BASE;
m.paths = Module._nodeModulePaths(path.dirname(BASE));
m._compile(head + tail, BASE);
