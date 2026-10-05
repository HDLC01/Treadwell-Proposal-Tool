"use strict";
/* F5: opening a bid that was SAVED BEFORE Kyle's B1-B8 batches must not move its total.
 *
 * The page under test is executed whole (polish-estimate.js, via polish-estimate-harness.js's own
 * boot code -- everything above its `(async function () {` scenario block is reused, so there is
 * one DOM stub and one fetch stub, not two). The fixtures below are the SHAPES a draft has on
 * staging today, written by the pre-B1 code: a v2 model with a "Travel" labor row and no `travel`
 * block, no `distance`, no `hours_per_day`, no `enabled`, no `same_floor`; a v1 {areas} model; and
 * an intake-only blob with no polish_estimate at all.
 *
 * Usage: node saved-bid-harness.js <frontend-dir>   ->  one line of JSON
 * Run it against `git archive origin/staging frontend` to get the BEFORE totals, and against the
 * branch's frontend for the AFTER ones. test_polish_saved_bid_safety.py pins the totals.
 */
const fs = require("fs");
const path = require("path");
const Module = require("module");

const BASE = path.join(__dirname, "polish-estimate-harness.js");
let code = fs.readFileSync(BASE, "utf8");
const MARK = "(async function () {\n  // ── A. the takeoff row";
code = code.replace(/\r\n/g, "\n");
const at = code.indexOf(MARK);
if (at < 0) throw new Error("polish-estimate-harness.js scenario block moved; update the marker");
let head = code.slice(0, at);
// The older page does not define every function the current harness exports; export only what this
// file drives so the SAME harness can boot both trees.
head = head.replace(/const EXPORTS = `[\s\S]*?`;\n/, "const EXPORTS = `\n  return { init: init, bid: bid, model: function () { return M; }, state: function () { return state; } };\n`;\n");

const tail = fs.readFileSync(path.join(__dirname, "saved-bid-scenarios.js"), "utf8");
const m = new Module(BASE, module);
m.filename = BASE;
m.paths = Module._nodeModulePaths(path.dirname(BASE));
m._compile(head + tail, BASE);
