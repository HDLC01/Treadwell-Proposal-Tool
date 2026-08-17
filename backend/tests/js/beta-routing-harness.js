"use strict";
/* Run the REAL intake page script and the REAL projects-page router, and report where they went.
 *
 * WHY EXECUTED, NOT GREPPED. Everything interesting about a second button next to an existing one
 * is invisible to a source assertion:
 *
 *   * Both handlers navigate. A grep proves both strings are present in the file; it cannot tell
 *     you which handler holds which one. Crossing the wires — beta → /estimate-review.html,
 *     submit → /polish-intake.html — leaves every string in place and every grep green, and it is
 *     the single most likely refactor mistake here.
 *   * The beta handler carries its own copy of the state composition. Nothing in the source says
 *     the two copies agree; running both on ONE filled form and comparing the saved blobs does.
 *   * `betaBtn` could be a typo'd id, in which case it is `null` for the life of the page and the
 *     button silently does nothing. This harness only creates a node for an id that really exists
 *     in index.html, so a typo shows up as "no listener was ever wired".
 *   * The visibility rule lives inside syncScopeToWorkType, which also hides quantity fields. A
 *     test that re-implements "polish → show" would agree with itself. This one flips the real
 *     radios, fires the real change listener, and reads the real style off the node.
 *   * `open()` in projects.js branches on a flag; a swapped branch sends every SPREADSHEET bid to
 *     the beta intake. Source text cannot see which way round it is.
 *
 * The form serialiser, the ?d= builder and the form binder are LIFTED OUT OF shared.js rather
 * than faked, so `city_state`, the number coercion and the draft id are the page's own behaviour.
 * Only the network-ish edges are stubs: TW.getState/setState (localStorage + the server) and
 * window.location.
 *
 * Usage: node beta-routing-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
// Normalised on read: these harnesses match the pages' source text, and git hands the files out
// with CRLF on a Windows checkout. See the note in polish-estimate-harness.js.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const indexJs = read(path.join(ROOT, "js", "index.js"));
const indexHtml = read(path.join(ROOT, "index.html"));
const sharedJs = read(path.join(ROOT, "shared.js"));
const projectsJs = read(path.join(ROOT, "js", "projects.js"));

const DRAFT_ID = "d1e2f3a4";

// ── lifting real code out of the page files ──────────────────────────────────
/** Balance braces from `from` and return the source through the matching close. */
function balanced(src, from, what) {
  let depth = 0;
  for (let j = from; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(from, j + 1);
  }
  throw new Error("unbalanced braces reading " + what);
}

/** A named function out of shared.js's IIFE (two-space indent). */
function sharedFn(name) {
  const m = new RegExp("\\n  function " + name + "\\s*\\(").exec(sharedJs);
  if (!m) throw new Error(name + "() is gone from shared.js — rewrite this harness, don't stub it");
  const i = sharedJs.indexOf("{", m.index + m[0].length - 1);
  return sharedJs.slice(m.index, i) + balanced(sharedJs, i, name);
}

/** The `const open = (id) => { … };` router out of projects.js's wireList IIFE. */
function liftOpen() {
  const m = /\n\s*const open = \(id\) => \{/.exec(projectsJs);
  if (!m) {
    throw new Error("projects.js no longer declares `const open = (id) => { … }` — it is what "
      + "every card and row navigates through. Rewrite this harness, do not stub it.");
  }
  const i = m.index + m[0].length - 1;
  return "const open = (id) => " + balanced(projectsJs, i, "open") + ";";
}

// The real serialiser + the real ?d= builder. getDraftId is the one thing stubbed inside the
// lifted scope (it reads localStorage in the browser).
const twScope = new Function("DRAFT_ID", `
  "use strict";
  function getDraftId() { return DRAFT_ID; }
  ${sharedFn("readForm")}
  ${sharedFn("writeForm")}
  ${sharedFn("withDraft")}
  return { readForm: readForm, writeForm: writeForm, withDraft: withDraft };
`)(DRAFT_ID);

// ── a DOM stub, only as much as index.js touches ─────────────────────────────
function parseStyle(attrs) {
  const out = {};
  const m = /style="([^"]*)"/.exec(attrs || "");
  if (!m) return out;
  m[1].split(";").forEach(function (bit) {
    const kv = bit.split(":");
    if (kv.length === 2) out[kv[0].trim()] = kv[1].trim();
  });
  return out;
}

function mkEl(props) {
  const el = {
    style: {},
    listeners: {},
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    contains() { return false; },
    classList: { add() {}, remove() {} },
    getAttribute() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    innerHTML: "",
    value: "",
  };
  return Object.assign(el, props || {});
}

/** One form field, built from the tag as it appears in the real markup. */
function mkField(attrs, tag) {
  const name = (/name="([^"]*)"/.exec(attrs) || [])[1];
  const type = (/type="([^"]*)"/.exec(attrs) || [])[1]
    || (tag === "textarea" ? "textarea" : tag === "select" ? "select-one" : "text");
  return mkEl({
    name: name,
    type: type,
    id: (/id="([^"]*)"/.exec(attrs) || [])[1] || null,
    value: (/value="([^"]*)"/.exec(attrs) || [])[1] || "",
    checked: /(^|\s)checked(\s|$|=)/.test(attrs),
    required: /(^|\s)required(\s|$|=)/.test(attrs),
    _rendered: false,
  });
}

/** Every named field in index.html, in document order — the browser's form.elements. */
function fieldsFromMarkup(html) {
  const out = [];
  const re = /<(input|select|textarea)\b([^>]*?)\/?>/gi;
  let m;
  while ((m = re.exec(html))) {
    const f = mkField(m[2], m[1].toLowerCase());
    if (f.name) out.push(f);
  }
  return out;
}

/** The tag that carries id="X" in index.html, or null when the page has no such element. */
function attrsOfId(html, id) {
  const at = html.indexOf('id="' + id + '"');
  if (at === -1) return null;
  return html.slice(html.lastIndexOf("<", at), html.indexOf(">", at) + 1);
}

/** Turn renderSystems' output into the object graph syncScopeToWorkType walks. */
function parseSystems(html) {
  const inputs = [], labels = [], rows = [];
  html.split('<div class="row">').slice(1).forEach(function (chunk) {
    const inner = chunk.split("</div>")[0];
    const rowLabels = [];
    const lre = /<label data-scope="([^"]*)">([\s\S]*?)<\/label>/g;
    let lm;
    while ((lm = lre.exec(inner))) {
      const scope = lm[1];
      const lab = mkEl({ getAttribute: (k) => (k === "data-scope" ? scope : null) });
      rowLabels.push(lab);
      labels.push(lab);
      const im = /<input([^>]*)>/.exec(lm[2]);
      if (im) {
        const f = mkField(im[1], "input");
        f._rendered = true;
        inputs.push(f);
      }
    }
    rows.push(mkEl({ querySelectorAll: (sel) => (sel === "[data-scope]" ? rowLabels : []) }));
  });
  return { inputs: inputs, labels: labels, rows: rows };
}

function build() {
  const NAV = [];
  const SAVES = [];
  const STATE = {};
  const nodes = {};
  const flags = { valid: true, reportValidityCalls: 0 };

  const fields = fieldsFromMarkup(indexHtml);
  const radios = fields.filter((f) => f.name === "work_type");
  const byName = (n) => form.elements.filter((f) => f.name === n)[0];

  const form = mkEl({ id: "intake-form" });
  form.elements = fields;
  form.reportValidity = function () {
    flags.reportValidityCalls++;
    return flags.valid;
  };
  form.querySelector = function (sel) {
    if (sel === "[name='work_type']:checked") return radios.filter((r) => r.checked)[0] || null;
    if (sel === "[name='bid_date']") return byName("bid_date");
    throw new Error("form.querySelector: unexpected selector " + sel + " — teach the harness");
  };
  form.querySelectorAll = function (sel) {
    if (sel === "[name='work_type']") return radios;
    throw new Error("form.querySelectorAll: unexpected selector " + sel + " — teach the harness");
  };
  nodes["intake-form"] = form;

  // #systems-container: renderSystems writes it, syncScopeToWorkType reads it back. The inputs it
  // renders join form.elements, exactly as they would in a real form.
  const systems = mkEl({ id: "systems-container" });
  let parsed = { inputs: [], labels: [], rows: [] };
  let systemsHtml = "";
  Object.defineProperty(systems, "innerHTML", {
    get() { return systemsHtml; },
    set(v) {
      systemsHtml = v;
      parsed = parseSystems(v);
      form.elements = form.elements.filter((f) => !f._rendered).concat(parsed.inputs);
    },
  });
  systems.querySelectorAll = function (sel) {
    if (sel === "input[name]") return parsed.inputs;
    if (sel === "[data-scope]") return parsed.labels;
    if (sel === ".row") return parsed.rows;
    throw new Error("systems-container: unexpected selector " + sel + " — teach the harness");
  };
  nodes["systems-container"] = systems;

  const documentStub = {
    listeners: {},
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    getElementById(id) {
      if (nodes[id]) return nodes[id];
      const attrs = attrsOfId(indexHtml, id);
      // NOT invented. An id the page does not carry has to come back null here, or a typo'd
      // getElementById would look wired in the harness and be dead in the browser.
      if (attrs === null) return null;
      nodes[id] = mkEl({ id: id, style: parseStyle(attrs), _attrs: attrs });
      return nodes[id];
    },
  };
  const windowStub = { location: { assign: (url) => NAV.push(url) } };
  const TW = {
    readForm: twScope.readForm,
    writeForm: twScope.writeForm,
    withDraft: twScope.withDraft,
    getState: () => STATE,
    setState: (partial) => { SAVES.push(JSON.parse(JSON.stringify(partial))); Object.assign(STATE, partial); },
  };

  // THE REAL PAGE SCRIPT, top to bottom. An unbound identifier anywhere in it throws here.
  new Function("document", "window", "TW", indexJs)(documentStub, windowStub, TW);

  function fire(el, type, ev) {
    const fns = (el.listeners || {})[type] || [];
    fns.forEach((fn) => fn(ev || { preventDefault() {}, target: el }));
    return fns.length;
  }
  function setWorkType(wt) {
    const target = radios.filter((r) => r.value === wt)[0];
    if (!target) throw new Error("no work_type radio with value " + wt);
    radios.forEach((r) => { r.checked = r === target; });
    fire(target, "change");            // only the clicked radio fires change in a browser
  }
  function fill(vals) {
    Object.keys(vals).forEach(function (k) {
      const f = byName(k);
      if (!f) throw new Error("index.html has no field named " + k);
      f.value = vals[k];
    });
  }

  return { NAV, SAVES, STATE, nodes, flags, form, radios, systems, documentStub,
           fire, setWorkType, fill, byName };
}

const out = {};

// ── boot: is there a button at all, and is it wired? ─────────────────────────
{
  const b = build();
  const beta = b.nodes["beta-continue"];
  out.boot = {
    buttonIsInTheMarkup: !!beta,
    // Straight off the markup's style attribute: the button must not flash on an epoxy job
    // before any script runs.
    shipsHidden: !!beta && beta.style.display === "none",
    typeIsButton: /type="button"/.test((beta && beta._attrs) || ""),
    // Secondary, not a second primary — and the class has to be one styles.css defines.
    className: /class="([^"]*)"/.exec((beta && beta._attrs) || "") ?
      /class="([^"]*)"/.exec(beta._attrs)[1] : null,
    clickListeners: ((beta && beta.listeners.click) || []).length,
    submitListeners: ((b.form.listeners || {}).submit || []).length,
    label: (function () {
      if (!beta) return null;
      const at = indexHtml.indexOf('id="beta-continue"');
      const open = indexHtml.indexOf(">", at);
      const close = indexHtml.indexOf("</button>", open);
      return indexHtml.slice(open + 1, close);
    })(),
  };
}

// ── the visibility rule, driven through the real syncScopeToWorkType ─────────
{
  const b = build();
  const beta = b.nodes["beta-continue"];
  const gyp = b.nodes["gyp-sf-container"];
  out.visibility = {};
  out.liveIntakeUnchanged = {};
  ["epoxy", "polish", "combo", "gyp"].forEach(function (wt) {
    b.setWorkType(wt);
    out.visibility[wt] = beta.style.display;
    // Evidence that the same function still does its old job for the live path: gyp's buckets
    // and the per-work-type quantity scopes.
    out.liveIntakeUnchanged[wt] = {
      gypBuckets: gyp.style.display,
      systems: b.systems.style.display,
      shownScopes: b.systems.querySelectorAll("[data-scope]")
        .filter((l) => l.style.display !== "none")
        .map((l) => l.getAttribute("data-scope"))
        .filter((s, i, a) => a.indexOf(s) === i),
    };
  });
  // Hidden, never removed: the same fields (and the same button) come back on switching back.
  b.setWorkType("polish");
  out.visibility.polishAgainAfterEpoxy = beta.style.display;
  out.visibility.buttonStillWired = (beta.listeners.click || []).length;
}

// ── where each handler goes, and what each one saves ────────────────────────
const PROJECT = {
  project_name: "Nearman Creek Polish",
  address: "1200 Kaw Dr",
  city: "Overland Park",
  state: "ks",                 // lower case on purpose: city_state must upper it
  zip: "66210",
  architect: "",
  contact_name: "Dave",
  contact_email: "dave@example.com",
  polish_sf: "2875",
};

function runHandler(which) {
  const b = build();
  b.setWorkType("polish");
  b.fill(PROJECT);
  if (which === "beta") b.fire(b.nodes["beta-continue"], "click");
  else b.fire(b.form, "submit");
  return b;
}

{
  const beta = runHandler("beta");
  const submit = runHandler("submit");
  out.nav = {
    beta: beta.NAV,
    submit: submit.NAV,
  };
  out.saves = {
    betaCount: beta.SAVES.length,
    submitCount: submit.SAVES.length,
    beta: beta.SAVES[0] || null,
    submit: submit.SAVES[0] || null,
  };
  // Two copies of one composition. Compared key for key so a change to either one that is not
  // made to the other fails here rather than in production.
  const norm = (o) => JSON.stringify(Object.keys(o || {}).sort().map((k) => [k, o[k]]));
  out.saves.identical = norm(beta.SAVES[0]) === norm(submit.SAVES[0]);
  out.saves.betaOnlyKeys = Object.keys(beta.SAVES[0] || {})
    .filter((k) => !(k in (submit.SAVES[0] || {})));
  out.saves.submitOnlyKeys = Object.keys(submit.SAVES[0] || {})
    .filter((k) => !(k in (beta.SAVES[0] || {})));
}

// ── the beta button is not a way around the required fields ─────────────────
{
  const b = build();
  b.setWorkType("polish");
  b.fill(PROJECT);
  b.flags.valid = false;                 // as if bid_date / project_name were empty
  b.fire(b.nodes["beta-continue"], "click");
  out.validation = {
    asked: b.flags.reportValidityCalls,
    navigated: b.NAV.length,
    saved: b.SAVES.length,
  };
}

// ── EXECUTED: the projects-page router ──────────────────────────────────────
{
  const navs = [];
  const list = [
    { id: "beta-1", polish_beta: true },
    { id: "sheet-1", polish_beta: false },
    { id: "legacy-1" },                                  // no flag at all (older rows)
    { id: "beta 2", polish_beta: true },                 // an id that needs encoding
  ];
  const open = new Function("ALL_PROJECTS", "window", liftOpen() + "\nreturn open;")(
    list, { location: { assign: (u) => navs.push(u) } });
  // Ids reach open() already encodeURIComponent'd — that is what the card/row markup carries.
  open(encodeURIComponent("beta-1"));
  open(encodeURIComponent("sheet-1"));
  open(encodeURIComponent("legacy-1"));
  open(encodeURIComponent("beta 2"));
  open(encodeURIComponent("never-heard-of-it"));
  out.projectsOpen = {
    beta: navs[0], sheet: navs[1], legacy: navs[2], encodedBeta: navs[3], unknown: navs[4],
    count: navs.length,
  };
}

console.log(JSON.stringify(out));
