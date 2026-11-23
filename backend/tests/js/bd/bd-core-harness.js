"use strict";
/* Run the rules in frontend/bd/js/bd-core.js against a table of cases.
 *
 * Usage: node bd-core-harness.js <bd-core.js> <cases.json>   ->   one line of JSON
 *
 * HOW THE CODE IS REACHED. Every function in bd-core.js is a declaration at two spaces of indent
 * inside its IIFE, and every constant a `var` at the same indent. Each one is LIFTED by name with
 * _lib.js (liftSource / grabConst), so a case runs the text of the file, not a copy of it. The
 * lifted functions call each other through forwarders, which is what lets a function be lifted
 * before the ones it calls.
 *
 * As a cross-check the whole file is also run in a bare VM (window = {}), and every case is run
 * through that window.BDCore too: `vm_disagrees` lists any case where the two give different
 * answers, which would mean the lifting is not faithful. The VM run also reports which globals
 * the file creates (it must create none but window.BDCore).
 *
 * cases.json is [{ id, fn, args }]. The answer is { results: { id: value | {error} }, ... }.
 */
const fs = require("fs");
const vm = require("vm");
const L = require("./_lib");

const [corePath, casesPath] = process.argv.slice(2);
const src = L.read(corePath);
const cases = JSON.parse(fs.readFileSync(casesPath, "utf8"));
const out = { results: {}, vm_disagrees: [], lifted: [], consts: [] };

// ── lift every function and constant by name ─────────────────────────────────────────────
const fnNames = [];
const constNames = [];
let m;
const fnRe = /^ {2}function (\w+)\(/gm;
while ((m = fnRe.exec(src))) fnNames.push(m[1]);
const constRe = /^ {2}var (\w+) =/gm;
while ((m = constRe.exec(src))) constNames.push(m[1]);
out.lifted = fnNames.slice();
out.consts = constNames.slice();

const deps = {};
constNames.forEach((name) => {
  const text = L.grabConst(src, name, { indent: "  ", where: "bd-core.js" });
  deps[name] = new Function(text + "\nreturn " + name + ";")();
});
const registry = {};
fnNames.forEach((name) => {
  deps[name] = function () { return registry[name].apply(this, arguments); };
});
fnNames.forEach((name) => {
  registry[name] = L.lift(src, name, deps, { indent: "  ", where: "bd-core.js" });
});

// ── the same file, whole, in a bare VM ───────────────────────────────────────────────────
const sandbox = { window: {}, Intl: Intl };
const before = new Set(Object.keys(sandbox));
vm.runInNewContext(src, sandbox, { filename: "bd-core.js" });
out.vm_globals = Object.keys(sandbox).filter((k) => !before.has(k));
out.vm_window_keys = Object.keys(sandbox.window);
const VMCore = sandbox.window.BDCore || {};
out.exports = Object.keys(VMCore).filter((k) => typeof VMCore[k] === "function");

function run(fn, args) {
  try { return { value: fn.apply(null, args) }; } catch (e) { return { error: String(e && e.message) }; }
}
function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

cases.forEach((c) => {
  if (!registry[c.fn]) { out.results[c.id] = { error: "no function " + c.fn + " in bd-core.js" }; return; }
  const lifted = run(registry[c.fn], c.args);
  out.results[c.id] = "error" in lifted ? { error: lifted.error } : lifted.value;
  // vm objects come from another realm; compare by their JSON
  const viaVm = VMCore[c.fn] ? run(VMCore[c.fn], JSON.parse(JSON.stringify(c.args))) : { error: "not exported" };
  if (!same(lifted, JSON.parse(JSON.stringify(viaVm)))) out.vm_disagrees.push(c.id);
});

process.stdout.write(JSON.stringify(out) + "\n");
