"use strict";
/* The cover-letter switch with BOTH scripts the Proposal step loads: proposal-review.js's
 * coverLetterOn (the one answer: the estimator's choice, else ON for a GC project) and the whole of
 * coverletter-editor.js, run as the page runs it.
 *
 * Why this exists. cover-letter-switch-harness runs proposal-review's wiring alone, and it was
 * green while the page shipped the GC default dead: coverletter-editor.js loads AFTER it, read the
 * absent flag as false and WROTE that false on load (walk of 2026-10-02). Only the two together can
 * show that, so this loads them together.
 *
 * Usage: node cover-letter-default-harness.js <frontend-dir>  ->  one line of JSON */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const FRONTEND = path.resolve(process.argv[2]);
const PR = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8");
const CE = fs.readFileSync(path.join(FRONTEND, "js", "coverletter-editor.js"), "utf8");
const CRM = require(path.join(FRONTEND, "js", "crm-core.js"));

function balanced(src, start) {
  let depth = 1;
  for (let j = start; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(start, j); }
  }
  return "";
}
const m = /\n  function coverLetterOn\(\) \{/.exec(PR);
if (!m) throw new Error("coverLetterOn is not in proposal-review.js -- repoint this harness");
const RESOLVER = "function coverLetterOn() {" + balanced(PR, m.index + m[0].length) + "}";

function anyNode() {
  const store = { style: {}, dataset: {}, children: [], childNodes: [], textContent: "",
                  innerHTML: "", value: "",
                  classList: { add() {}, remove() {}, toggle() {}, contains: () => false } };
  return new Proxy(function () {}, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => "";
      if (k === Symbol.iterator) return function* () {};
      if (k === "then") return undefined;
      if (k === "length") return 0;
      if (k in store) return store[k];
      if (k === "querySelectorAll" || k === "getElementsByClassName"
          || k === "getElementsByTagName") return () => [];
      if (k === "closest" || k === "querySelector") return () => null;
      return anyNode();
    },
    set(t, k, v) { store[k] = v; return true; },
    apply() { return anyNode(); },
  });
}

function run(stored, opts) {
  const o = opts || {};
  let raw = JSON.stringify(stored);
  const writes = [];
  const TW = {
    getState: () => JSON.parse(raw),
    setState: (p) => { writes.push(p); raw = JSON.stringify(Object.assign(JSON.parse(raw), p)); },
    readForm: () => ({}), authHeaders: (h) => Object.assign({}, h || {}), resolveApiBase: () => "",
    getDraftId: () => "d1",
  };
  const listeners = {};
  const box = { checked: undefined,
                addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); } };
  // The letter's surface: a node that takes listeners like any other, with `hidden` readable.
  const surface = anyNode();
  surface.hidden = true;
  const body = anyNode();
  const sandbox = {
    console, setTimeout: () => 0, clearTimeout() {}, Promise, JSON, Object, Array, String,
    Number, Boolean, Math, Date, RegExp, Error, Map, Set, Symbol, Proxy, encodeURIComponent,
    fetch: () => new Promise(() => {}),           // the letter template never arrives here
  };
  sandbox.window = sandbox;
  sandbox.self = sandbox;
  sandbox.TW = TW;
  sandbox.TWAuth = { ready: Promise.resolve() };
  if (!o.noCrm) sandbox.TWCrm = CRM;
  sandbox.document = new Proxy({
    readyState: "complete", body,
    getElementById: (id) => (id === "cl-toggle" ? box : id === "cl-surface" ? surface : null),
    addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [], createElement: () => anyNode(),
    createTextNode: () => anyNode(), createRange: () => anyNode(),
  }, { get(t, k) { return k in t ? t[k] : anyNode(); } });
  sandbox.getSelection = () => anyNode();
  sandbox.addEventListener = () => {};
  vm.createContext(sandbox);
  if (!o.noResolver) vm.runInContext(RESOLVER, sandbox);   // proposal-review.js, loaded first
  let threw = null;
  try { vm.runInContext(CE, sandbox); } catch (e) { threw = String(e && e.message || e); }
  const onLoad = { checked: box.checked, writes: writes.slice(), surfaceHidden: surface.hidden };
  if (o.press !== undefined) {
    box.checked = o.press;
    (listeners.change || []).forEach((fn) => fn({ type: "change" }));
  }
  return { onLoad, after: writes, threw };
}

const out = {
  gcFresh: run({ audience: "GC", project_name: "x" }),
  gcPadded: run({ audience: " gc ", project_name: "x" }),
  gcUntickedBefore: run({ audience: "GC", cover_letter_enabled: false, project_name: "x" }),
  gcTickedBefore: run({ audience: "GC", cover_letter_enabled: true, project_name: "x" }),
  directFresh: run({ audience: "Direct", project_name: "x" }),
  gcFreshThenUntick: run({ audience: "GC", project_name: "x" }, { press: false }),
  gcNoResolver: run({ audience: "GC", project_name: "x" }, { noResolver: true }),
};
process.stdout.write(JSON.stringify(out));
