"use strict";
/* PHASE 7b, ESTIMATING TOOL V2'S INTAKE: a test copy of a split project through the REAL page.
 *
 * js/polish-intake.js's own boot code is reused (everything above polish-intake-harness.js's scenario
 * section: its DOM stub, its fetch stub, its lifted page functions), and the scenarios are in
 * condition-cells-intake-scenarios.js. The same arrangement saved-bid-harness.js has with the Takeoff page.
 *
 * Usage: node condition-cells-intake-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");

const BASE = path.join(__dirname, "polish-intake-harness.js");
const code = fs.readFileSync(BASE, "utf8").replace(/\r\n/g, "\n");
const MARK = "const out = { coreKeys: Object.keys(P.freshModel().conditions) };";
const at = code.indexOf(MARK);
if (at < 0) throw new Error("polish-intake-harness.js scenario section moved; update the marker");
if (code.indexOf(MARK, at + 1) >= 0) throw new Error("polish-intake-harness.js has the marker twice; update it");
const head = code.slice(0, at);

const tail = fs.readFileSync(path.join(__dirname, "condition-cells-intake-scenarios.js"), "utf8");
const m = new Module(BASE, module);
m.filename = BASE;
m.paths = Module._nodeModulePaths(path.dirname(BASE));
m._compile(head + tail, BASE);
