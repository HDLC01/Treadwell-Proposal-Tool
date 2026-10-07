"use strict";
/* Loads frontend scripts the way a BROWSER loads them, and reports what each one did.
 *
 * WHY. A core module has two ways in. Under node (the tests) it is `require`d; in a browser it is a
 * script tag, and a module that depends on another reads the dependency off the global scope
 * (`root.TWExcelMath`). Every other harness in this folder uses the first door. This one uses the
 * second: ONE fresh context, no `module`, no `require`, no `exports`, `self` and `window` both the
 * global object, and the scripts run in exactly the order the caller lists them. A module whose
 * dependency is missing or loaded too late throws here, by name, which is what it would do on the
 * page, where the same mistake shows up as a screen stuck on its loading message.
 *
 * Usage: node core-boot-harness.js <frontend-dir> <script> [<script> ...]
 *   <script>  a path under the frontend dir, e.g. js/excel-math.js
 *
 * The last line printed is JSON:
 *   { scripts: [ { file, threw, published, members } ... ], globals }
 *   threw       null, or the message of what the script threw (the run goes on, as a browser does)
 *   published   the globals this script added, sorted
 *   members     for each published global, the names of its own members that are functions, sorted
 *   globals     every global present when the last script finished, sorted
 */
const path = require("path");
const vm = require("vm");
const { read } = require("./_lib");

const [frontend, ...files] = process.argv.slice(2);
if (!frontend || files.length === 0) {
  console.error("usage: node core-boot-harness.js <frontend-dir> <script> [<script> ...]");
  process.exit(2);
}

const sandbox = {};
sandbox.self = sandbox;
sandbox.window = sandbox;
sandbox.console = console;
vm.createContext(sandbox);

/** The names of the function members of a published global ([] when it is not an object). */
function functionMembers(value) {
  if (!value || (typeof value !== "object" && typeof value !== "function")) return [];
  return Object.keys(value).filter((k) => typeof value[k] === "function").sort();
}

const report = files.map((rel) => {
  const before = new Set(Object.keys(sandbox));
  let threw = null;
  try {
    vm.runInContext(read(path.resolve(frontend, rel)), sandbox, { filename: rel });
  } catch (e) {
    threw = String((e && e.message) || e);
  }
  const published = Object.keys(sandbox).filter((k) => !before.has(k)).sort();
  const members = Object.fromEntries(published.map((k) => [k, functionMembers(sandbox[k])]));
  return { file: rel, threw, published, members };
});

console.log(JSON.stringify({ scripts: report, globals: Object.keys(sandbox).sort() }));
