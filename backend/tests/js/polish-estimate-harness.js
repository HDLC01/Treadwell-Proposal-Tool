"use strict";
/* Execute the REAL frontend/js/polish-estimate.js and report what it did.
 *
 * WHY THE WHOLE FILE, EXECUTED.
 *
 * This page went from 7 HyperFormula-driven steps to 3 self-pricing ones on 2026-08-17, and the
 * ways it can now be wrong are all invisible to a source assertion:
 *
 *   * "the takeoff row shows the library's price" is a claim about ARITHMETIC. It fails as a
 *     second opinion drifting from the Items & Assemblies page, and the only honest check is to
 *     price the fixture with the real library-core.js and compare the figure the page put in the
 *     cell.
 *   * "each row's cost lands in its OWN row's cell" is the transposition class. library.js wrote
 *     Quantity and Cost into each other's columns while a test compared `var QTY_TD = 4,
 *     COST_TD = 5` against the rendered columns and agreed with it. That bug shipped. So the cell
 *     graph here is built FROM the render functions' own output and the real repaint is run
 *     against it.
 *   * An unbound identifier in a handler is exactly what a source test cannot see, and that class
 *     of mistake (STAGE_CREATED) took the board down on prod on 2026-08-12.
 *
 * So the page's ENTIRE IIFE body is executed — every line of it, in order, including the three
 * delegated `document.addEventListener` registrations and the parse-time `adopt(TW.getState())` —
 * with only `init();` itself lifted off the bottom so the tests can drive boot. Nothing is lifted
 * out function-by-function, because a function this harness forgot to lift is a function no test
 * would ever have run.
 *
 * Stubbed: fetch, window.TW, window.TWAuth, window.TWPolishSandbox, the DOM, and the clock.
 * REAL: js/bid-model.js (the markup chain, pinned to Kyle's Polish tab) and
 * js/library-core.js (priceAssembly). The arithmetic under test is the shipped arithmetic.
 *
 * Usage: node polish-estimate-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);

// Line endings normalised on read, because this harness matches the page's SOURCE TEXT and git
// hands these files out with CRLF on a Windows checkout. The HEAD anchor below then misses — the
// carriage return sits between the brace and the newline it is looking for — and every test in the
// file reports "the harness crashed" rather than anything about the product. CI checks out LF and
// stays perfectly green while a developer's machine shows 36 errors, which is the worst possible
// split. The fn()-style regex anchors elsewhere in the suite survive CRLF only by luck: they start
// AT the newline, so the stray \r falls outside the match.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const src = read(path.join(ROOT, "js", "polish-estimate.js"));
const pageHtml = read(path.join(ROOT, "polish-estimate.html"));
const B = require(path.join(ROOT, "js", "bid-model.js"));
const L = require(path.join(ROOT, "js", "library-core.js"));
// The one vocabulary (js/work-types.js): the page builds its Takeoff cards off it as it parses.
const W = require(path.join(ROOT, "js", "work-types.js"));
// The one search pop-up both Add buttons open: the REAL module, mounted on this file's stub DOM.
const PICKER = require(path.join(ROOT, "js", "library-picker.js"));

const clone = (v) => JSON.parse(JSON.stringify(v));

// ── the page's own body, with only the boot call lifted off ───────────────────
const HEAD = '(function () {\n  "use strict";\n';
const TAIL = "\n  init();\n})();";
const h = src.indexOf(HEAD);
if (h < 0) {
  throw new Error("polish-estimate.js no longer opens with the standard IIFE — rewrite this " +
                  "harness, don't stub the page");
}
const t = src.lastIndexOf(TAIL);
if (t < 0) {
  throw new Error("polish-estimate.js no longer ends with `init();` at the bottom of its IIFE — " +
                  "rewrite this harness, don't stub the page");
}
const BODY = src.slice(h + HEAD.length, t);

// Everything the tests drive. `at`, `M` and `state` are read through getters so a test sees the
// page's own variables rather than a copy taken at build time.
const EXPORTS = `
  return {
    init: init, adopt: adopt, go: go, changed: changed, saveSoon: saveSoon,
    assemblyByName: assemblyByName, setAssembly: setAssembly,
    itemByName: itemByName, setPick: setPick, rowKind: rowKind,
    rowPrice: rowPrice, materialTotal: materialTotal, bid: bid,
    condLine: condLine, conditionLibrary: conditionLibrary,
    moneyAuto: moneyAuto, measureText: measureText, asmHint: asmHint,
    repaintNumbers: repaintNumbers, renderPanel: renderPanel, stepStatus: stepStatus,
    takeoffPanel: takeoffPanel, laborPanel: laborPanel, reviewPanel: reviewPanel,
    markupTable: markupTable, newLaborRow: newLaborRow,
    STEPS: STEPS, UNITS: UNITS,
    CONDITION_CARDS: CONDITION_CARDS, RESERVED_ITEM_IDS: RESERVED_ITEM_IDS,
    model: function () { return M; },
    state: function () { return state; },
    asms: function () { return ASMS; },
    items: function () { return ITEMS; },
    at: function () { return at; }
  };
`;
const scope = new Function("window", "document", "TW", "fetch", "clock",
  '"use strict";\nvar setTimeout = clock.setTimeout, clearTimeout = clock.clearTimeout;\n' +
  BODY + EXPORTS);

// ── the smallest DOM that can hold what the render functions emit ─────────────
const ENT = [[/&lt;/g, "<"], [/&gt;/g, ">"], [/&quot;/g, '"'], [/&#39;/g, "'"], [/&amp;/g, "&"]];
function dec(s) {
  let out = String(s);
  ENT.forEach(([re, ch]) => { out = out.replace(re, ch); });
  return out;
}
const strip = (html) => dec(String(html).replace(/<[^>]*>/g, ""));

/** `input`, `[data-k="unit"]`, `select[data-tk="0"][data-k="unit"]` — the shapes this page uses. */
function matchesSel(el, sel) {
  const m = /^\s*([a-zA-Z]*)((?:\[[^\]]*\])*)\s*$/.exec(String(sel));
  if (!m) throw new Error("this DOM stub cannot answer the selector " + sel);
  if (m[1] && el.tag !== m[1].toLowerCase()) return false;
  return (m[2].match(/\[[^\]]*\]/g) || []).every((part) => {
    const inner = part.slice(1, -1);
    const eq = inner.indexOf("=");
    if (eq === -1) return Object.prototype.hasOwnProperty.call(el.attrs, inner);
    const k = inner.slice(0, eq);
    const v = inner.slice(eq + 1).replace(/^["']|["']$/g, "");
    return el.attrs[k] === v;
  });
}

function makeDom(log) {
  const nodes = {};

  /** Every element in a node's subtree: the markup it was given, plus anything appended to it. */
  function subtree(node, acc) {
    acc = acc || [];
    (node.children || []).forEach((c) => { acc.push(c); subtree(c, acc); });
    (node.kids || []).forEach((c) => { if (!c.isText) { acc.push(c); subtree(c, acc); } });
    return acc;
  }

  function element(tag, attrs, text, name) {
    const self = { tag: tag, attrs: attrs || {}, name: name || null,
                   children: [], kids: [], listeners: [],
                   htmlWrites: 0, textWrites: 0, classWrites: 0 };
    let _text = text == null ? "" : text;
    let _html = "";
    let _hidden = Object.prototype.hasOwnProperty.call(self.attrs, "hidden");
    let _class = self.attrs["class"] === undefined ? "" : self.attrs["class"];
    self.value = self.attrs.value === undefined ? "" : dec(self.attrs.value);
    Object.defineProperties(self, {
      textContent: {
        get() { return _text; },
        set(v) { _text = String(v); self.textWrites += 1; if (name) log.push("text:" + name); },
      },
      innerHTML: {
        get() { return _html; },
        set(v) {
          _html = String(v);
          self.htmlWrites += 1;
          self.children = parse(String(v));
          self.kids = [];
          _text = strip(v);
          if (name) log.push("html:" + name);
        },
      },
      hidden: {
        get() { return _hidden; },
        set(v) { _hidden = !!v; if (name) log.push((v ? "hide:" : "show:") + name); },
      },
      className: {
        get() { return _class; },
        set(v) { _class = String(v); self.classWrites += 1; },
      },
    });
    self.getAttribute = (k) =>
      (Object.prototype.hasOwnProperty.call(self.attrs, k) ? self.attrs[k] : null);
    self.setAttribute = (k, v) => { self.attrs[k] = String(v); };
    self.matches = (sel) => matchesSel(self, sel);
    // Self-match only: every delegated handler on this page is fired at the button or field it
    // was aimed at, which is also what a browser hands it.
    self.closest = (sel) => (matchesSel(self, sel) ? self : null);
    self.appendChild = (c) => { self.kids.push(c); if (c && c.isText) _text += c.text; return c; };
    self.addEventListener = (type, handler) => { self.listeners.push({ type, handler }); };
    self.querySelectorAll = (sel) => subtree(self).filter((e) => matchesSel(e, sel));
    self.querySelector = (sel) => self.querySelectorAll(sel)[0] || null;
    return self;
  }

  /** Rendered markup → elements, with the attributes and the initial text they were given.
   *
   *  Flat and deliberately dumb: the page addresses its computed cells by data-attribute, never by
   *  position or by walking a tree, so an attribute index is the whole contract. */
  function parse(markup) {
    const out = [];
    const tagRe = /<([a-zA-Z][a-zA-Z0-9]*)((?:[^>"']|"[^"]*"|'[^']*')*)>/g;
    let m;
    while ((m = tagRe.exec(markup))) {
      const attrs = {};
      const attrRe = /([a-zA-Z][a-zA-Z0-9-]*)(?:="([^"]*)")?/g;
      let a;
      while ((a = attrRe.exec(m[2]))) {
        attrs[a[1].toLowerCase()] = a[2] === undefined ? "" : a[2];
      }
      const rest = markup.slice(tagRe.lastIndex);
      const lt = rest.indexOf("<");
      const el = element(m[1].toLowerCase(), attrs,
                         dec(lt === -1 ? rest : rest.slice(0, lt)), null);
      if (el.tag === "select") {
        // A <select>'s value is its selected <option>, which is how the change handler reads it.
        const close = rest.indexOf("</select>");
        const inner = close === -1 ? rest : rest.slice(0, close);
        const picked = /value="([^"]*)"\s+selected/.exec(inner) || /value="([^"]*)"/.exec(inner);
        el.value = picked ? dec(picked[1]) : "";
      }
      out.push(el);
    }
    return out;
  }

  /** Start the document as the page's own shipped markup: #main and #bidbar carry `hidden`, and
   *  #loading carries the message the estimator sees until the library lands. A harness that
   *  invented these as blank-and-visible would make "the page stayed on its loading message" and
   *  "#main was never revealed" true no matter what the page did. */
  function seed(html) {
    parse(html).forEach((el) => {
      const id = el.attrs.id;
      if (!id || nodes[id]) return;
      nodes[id] = element(el.tag, el.attrs, el.textContent, id);
    });
  }

  const get = (id) => (nodes[id] = nodes[id] || element("div", { id: id }, "", id));
  const all = (sel) => {
    const hits = [];
    Object.keys(nodes).forEach((id) => {
      const n = nodes[id];
      if (matchesSel(n, sel)) hits.push(n);
      subtree(n).forEach((e) => { if (matchesSel(e, sel)) hits.push(e); });
    });
    return hits;
  };
  return { nodes, get, all, element, parse, seed };
}

function makeDocument(dom, log) {
  const listeners = [];
  // document.body, for the pop-up to mount on: appendChild keeps it in `kids`, removeChild takes it
  // out, so "the pop-up is on screen" is `body.kids.length`.
  const body = dom.element("body", {}, "", null);
  body.removeChild = (c) => { body.kids = body.kids.filter((k) => k !== c); return c; };
  return {
    listeners,
    body,
    getElementById: dom.get,
    createElement: (tag) => dom.element(String(tag).toLowerCase(), {}, "", null),
    createTextNode: (txt) => ({ isText: true, text: String(txt) }),
    addEventListener(type, handler) {
      listeners.push({ type, handler });
      log.push("listen:" + type);
    },
    removeEventListener(type, handler) {
      const at = listeners.findIndex((l) => l.type === type && l.handler === handler);
      if (at !== -1) listeners.splice(at, 1);
    },
    querySelectorAll: (sel) => dom.all(sel),
    querySelector: (sel) => dom.all(sel)[0] || null,
    fire(type, event) {
      listeners.filter((l) => l.type === type).forEach((l) => l.handler(event));
    },
  };
}

/** A hand-cranked clock, so "the save is debounced" is observable rather than timed.
 *
 *  Handles start at 1, as every browser's do. A 0 handle would make the page's own
 *  `if (saveTimer) clearTimeout(saveTimer)` guard skip a live timer — a condition the real page
 *  never meets, and one a 0-based harness would hide. */
function makeClock() {
  let due = [];
  return {
    setTimeout: (f) => { due.push({ f, live: true }); return due.length; },
    clearTimeout: (id) => { if (due[id - 1]) due[id - 1].live = false; },
    armed: () => due.filter((t) => t.live).length,
    fire: () => { const now = due; due = []; now.forEach((t) => { if (t.live) t.f(); }); },
  };
}

// ── the library this page prices against ─────────────────────────────────────
// Costs and coverages are Kyle's own (OPF at 275 SF/Gal, $85.3827/Gal), plus a five-gallon pail so
// the pack arithmetic has something to be wrong about and a flat $100/1,000 SF line so one row
// lands on a whole dollar — moneyAuto has a branch for each.
const ITEMS = [
  { id: "i1", name: "OPF", unit: "Gal", buy_qty: 1, unit_cost: 85.3827, coverage: 275 },
  { id: "i2", name: "Glaze #4", unit: "Gal", buy_qty: 5, unit_cost: 398.787, coverage: 125 },
  { id: "i3", name: "Armor Top Satin", unit: "Kit", buy_qty: 1, unit_cost: 382.4475,
    coverage: 775 },
  { id: "i4", name: "Densifier", unit: "Pail", buy_qty: 1, unit_cost: 100, coverage: 1000 },
  // ONE NAME, TWO THINGS. Not a hypothetical: "Grout Compound - Test" and "Plastic - Test" each
  // exist as an item AND an assembly in the live library, different ids, identical names. The
  // merged picker has to refuse to guess between them, so the fixture has to be able to trap it.
  { id: "i5", name: "Grout Compound", unit: "Pail", buy_qty: 1, unit_cost: 46.2, coverage: 800 },
];
const ASMS = [
  { id: "a1", name: "Polish 800 Grit", unit: "SF", lines: [
    { item_id: "i1", coverage: 275, waste_pct: 5, roundup: true },
    { item_id: "i3", coverage: 775, waste_pct: 0, roundup: true }] },
  { id: "a2", name: "Cove Base", unit: "LF", lines: [
    { item_id: "i2", coverage: 125, waste_pct: 0, roundup: false }] },
  { id: "a5", name: "Densifier Only", unit: "SF", lines: [
    { item_id: "i4", coverage: 1000, waste_pct: 0, roundup: true }] },
  // Two names differing only by case. A library problem to fix in the library — never something
  // this page resolves by picking one of them.
  { id: "a3", name: "Grind & Seal", unit: "SF", lines: [
    { item_id: "i4", coverage: 1000, waste_pct: 0, roundup: true }] },
  { id: "a4", name: "GRIND & SEAL", unit: "SF", lines: [
    { item_id: "i1", coverage: 275, waste_pct: 0, roundup: true }] },
  // The assembly half of the collision above. Its lines are its own, so picking the wrong one of
  // the two prices the row at something visibly different — which is what makes "resolved to the
  // wrong kind" a thing a test can catch rather than a thing only a reader would notice.
  { id: "a6", name: "Grout Compound", unit: "SF", lines: [
    { item_id: "i2", coverage: 400, waste_pct: 0, roundup: false }] },
  // Its material has been deleted from the library, so it cannot price.
  { id: "a9", name: "Orphaned System", unit: "SF", lines: [
    { item_id: "deleted-material", coverage: 275, waste_pct: 5, roundup: true }] },
];

const MODEL = {
  version: 2,
  takeoff: [
    { assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 12500, unit: "SF" },
    { assembly_id: "a2", assembly_name: "Cove Base", measurement: 200, unit: "LF" },
    { assembly_id: "a5", assembly_name: "Densifier Only", measurement: 5000, unit: "SF" },
  ],
  labor: [
    // Kyle's own screenshot: 3 guys × 5 days × $32.20 = $3,864. That figure pins the ×8 hours.
    { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 32.2 },
    { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 32.2 },
  ],
  conditions: { local: true, prevailing_wage: false, taxable: true,
                remodel_tax: false },
  contingency: 0,
  totals: {},
};

function blob(over) {
  return Object.assign({
    __draft_id: "proj-1",
    project_name: "Nearman Creek",
    city: "Kansas City", state: "KS",
    work_type: "polish",
    polish_estimate: clone(MODEL),
  }, over || {});
}

/** The bid this model SHOULD come to, composed out of the two real engines the documented way.
 *
 *  Independent of the page on purpose: the page must agree with library-core's priceAssembly and
 *  bid-model's markupChain, not merely be self-consistent. */
/** `remodelRate` is the project's county rate off the draft, which the page reads from
 *  `state.county_remodel_rate`. Passing it here too keeps this expectation and the page computing
 *  the same thing; leaving it out would let a page that ignored the county still match. */
/** Dye + Joint Filler's dollar contribution to a model's material total, exactly how the real
 *  page's materialTotal() computes it: off `B.takeoffSf` and the model's OWN conditions,
 *  merged onto freshModel()'s defaults the same way migrateModel merges them (a fixture below
 *  states only the keys it cares about, and joint_filler ships ON -- an omitted key must NOT
 *  silently read as off here, or this expectation would agree with a page that dropped the
 *  seeded condition entirely). Shared by expectedChain and the two raw-material expectations
 *  below that never reach markupChain at all, so the three cannot drift from each other about
 *  what counts as "the area" or "the merged conditions". */
function extraMaterial(model) {
  const cond = Object.assign({}, B.freshModel().conditions, (model || {}).conditions || {});
  const area = B.takeoffSf((model || {}).takeoff);
  return B.dyeCost(area, cond.dye) + B.jointFillerCost(area, cond.joint_filler);
}

function expectedChain(model, asms, items, remodelRate) {
  let material = 0;
  (model.takeoff || []).forEach((r) => {
    const asm = (asms || []).filter((a) => a.id === r.assembly_id)[0];
    if (asm) material += L.priceAssembly(asm, items, B.num(r.measurement)).total;
  });
  material += extraMaterial(model);
  return B.markupChain({
    material: material,
    labor: B.laborTotal(model.labor),
    contingency: model.contingency,
    fees: model.fees,
    conditions: model.conditions,
    sf: B.takeoffSf(model.takeoff),
    // PASSED THROUGH RAW, never through num(). null/undefined means "no county picked" and the
    // engine stands the Kansas state rate up; an explicit 0 means "picked, and exempt" (Missouri).
    // Coercing here collapsed those two into 0 and made this expectation disagree with the page
    // about every job that has no county.
    remodel_rate: remodelRate,
  });
}

function build(opts) {
  opts = opts || {};
  const log = [];
  const rec = { saves: [], fetches: [], flushed: 0 };
  const store = { blob: clone(opts.blob === undefined ? blob() : opts.blob),
                  id: opts.id || "proj-1" };
  const dom = makeDom(log);
  const doc = makeDocument(dom, log);
  const clock = makeClock();
  dom.seed(pageHtml);
  log.length = 0;                 // the seed is the page's own markup, not something it painted

  const TW = {
    getState: () => clone(store.blob),
    setState: (partial) => {
      rec.saves.push(clone(partial));
      store.blob = Object.assign(store.blob, clone(partial));
      return store.blob;
    },
    withDraft: (p) => p + (p.indexOf("?") >= 0 ? "&" : "?") + "d=" + store.id,
    getDraftId: () => store.id,
    draftReady: Promise.resolve(),
    authHeaders: (hs) => Object.assign({}, hs || {}),
    resolveApiBase: () => "",
    // The pagehide flush calls this after pushing the pending save through synchronously --
    // counted separately from rec.saves so it does not masquerade as a second save.
    flushState: () => { rec.flushed++; },
  };

  const S = {
    enterSandbox: async function (adoptFn) {
      log.push("sandbox:in");
      await new Promise((r) => setImmediate(r));      // it settles over two real fetches
      if (opts.copyBlob) {
        store.blob = clone(opts.copyBlob);
        store.id = "proj-1-beta";
        adoptFn(clone(opts.copyBlob));
      }
      log.push("sandbox:out");
      return opts.sandboxOk !== false;
    },
    repointWizardLinks() { log.push("repoint"); },
    markNewProjectAsTest() { log.push("markTest"); },
  };

  const winListeners = [];
  const win = {
    TWBidModel: B, TWWorkTypes: W, TWLib: L, TWPolishSandbox: S, TWLibraryPicker: PICKER,
    TWAuth: { ready: Promise.resolve() },
    scrollTo: () => { log.push("scroll"); },
    location: { href: "https://x/polish-estimate.html?d=proj-1" },
    // The page registers its own `pagehide` flush directly on window (mirrors shared.js's own
    // net at shared.js:513) -- exposed so a test can fire it like a real tab close/switch.
    listeners: winListeners,
    addEventListener(type, handler) {
      winListeners.push({ type, handler });
      log.push("winlisten:" + type);
    },
    fire(type, event) {
      winListeners.filter((l) => l.type === type).forEach((l) => l.handler(event));
    },
  };

  const fetchStub = async function (url, init) {
    rec.fetches.push(url);
    // Every request WITH ITS METHOD, so "never writes to the library" can be asserted on verbs.
    (rec.calls = rec.calls || []).push({ url: String(url), method: ((init || {}).method || "GET").toUpperCase() });
    log.push("fetch:" + url);
    // POST /api/distance -- the server's driving miles from the office. `distance` is the JSON body
    // it answers with; `distanceGate` is a promise the answer waits on (a slow Google);
    // `distanceFails` is the network going away. Its own arm so every older scenario, which has no
    // address, never reaches it -- and one that did would show up in rec.distanceBodies.
    if (/api\/distance/.test(url)) {
      (rec.distanceBodies = rec.distanceBodies || []).push(JSON.parse((init || {}).body || "{}"));
      if (opts.distanceGate) await opts.distanceGate;
      if (opts.distanceFails) throw new Error("the distance service is down");
      return { json: async () => clone(opts.distance === undefined
        ? { ok: false, miles: null, reason: "no_key" } : opts.distance) };
    }
    if (opts.libraryFails) throw new Error("the network went away");
    // GET /api/library/labor -- the estimator's own default labor lines. Answered separately from
    // the two below because the page has to survive it failing: public.library_labor is on staging
    // and NOT on production, so on prod today this endpoint has no table behind it. `laborFails`
    // is that read going down on its own, `laborBody` is it answering with something that is not a
    // list of rows -- a 404's JSON, an { ok: false } -- and neither may cost the page its Labor
    // step. Default [] rather than the fixture list, so a page that fetched this when it had no
    // business to shows up as an empty answer rather than silently seeding.
    // GET /api/condition-defaults -- the company's answers for the three Takeoff
    // conditions. Its own arm for the same reason the labor one has one: the table is
    // applied to NEITHER database yet, so on both of them today this read has nothing
    // behind it, and a page that could not open without it would be unusable. Default []
    // rather than a fixture list, so a page that asked when it had no business to shows
    // up as an empty answer rather than as a silent rewrite of somebody's conditions.
    // GET /api/markup/rules?layout=global -- the company labor rate lives here. Its own arm, and
    // [] by default so every older scenario opens on the shipped $33 exactly as before.
    if (/api\/markup\/rules/.test(url)) {
      if (opts.markupFails) throw new Error("the markup service is down");
      return { json: async () => ({ ok: true,
        rules: clone(opts.markupRules === undefined ? [] : opts.markupRules) }) };
    }
    if (/condition-defaults/.test(url)) {
      if (opts.conditionFetchFails) throw new Error("the defaults table is not there");
      return { json: async () => ({ ok: true,
        conditions: clone(opts.conditionDefaults === undefined
          ? [] : opts.conditionDefaults) }) };
    }
    if (/labor-calc/.test(url)) {
      if (opts.laborCalcFails) throw new Error("the calculator table is not there");
      return { json: async () => ({ ok: true, calc: clone(opts.laborCalc === undefined ? [] : opts.laborCalc) }) };
    }
    if (/\/labor/.test(url)) {
      if (opts.laborFails) throw new Error("the defaults table is not there");
      return { json: async () => (opts.laborBody !== undefined
        ? clone(opts.laborBody)
        : { ok: true, labor: clone(opts.labor === undefined ? [] : opts.labor) }) };
    }
    if (/assemblies/.test(url)) {
      return { json: async () => ({ assemblies: clone(opts.asms === undefined ? ASMS
                                                                             : opts.asms) }) };
    }
    return { json: async () => ({ items: clone(opts.items === undefined ? ITEMS : opts.items) }) };
  };

  const api = scope(win, doc, TW, fetchStub, clock);
  return { api, dom, doc, win, TW, S, clock, log, rec, store };
}

// ── driving the page through its own markup ──────────────────────────────────
function need(built, sel) {
  const el = built.doc.querySelector(sel);
  if (!el) throw new Error("the page rendered nothing matching " + sel);
  return el;
}
const warn = (built, sel) => {
  const el = built.doc.querySelector(sel);
  return el ? { text: el.textContent, hidden: !!el.hidden } : null;
};
const txt = (built, sel) => {
  const el = built.doc.querySelector(sel);
  return el === null ? null : el.textContent;
};
function typeInto(built, sel, value) {
  const el = need(built, sel);
  el.value = String(value);
  built.doc.fire("input", { target: el });
  return el;
}
/** The commit of a typed box (blur or Enter): the value is set, then "change" fires. The clearing
 *  rule lives on this event, not on "input", so a test that only calls typeInto never reaches it. */
function changeTo(built, sel, value) {
  const el = need(built, sel);
  el.value = String(value);
  built.doc.fire("change", { target: el });
  return el;
}
function clickOn(built, sel) {
  return clickEl(built, need(built, sel));
}
function clickEl(built, el) {
  built.doc.fire("click", { target: el, preventDefault: function () {} });
  return el;
}
/** The pop-up on screen (the last thing mounted on body), or null. */
function popup(built) {
  const k = built.doc.body.kids;
  return k.length ? k[k.length - 1] : null;
}
function fireOn(el, type, event) {
  el.listeners.filter((l) => l.type === type).forEach((l) => l.handler(event));
}
/** Tick (or untick) one pop-up row by its key, the way the browser reports it: a change event on the checkbox. */
function tick(built, key) {
  const box = popup(built).querySelectorAll("[data-pk]").filter((e) => e.attrs["data-pk"] === key)[0];
  if (!box) throw new Error("the pop-up has no row " + key);
  fireOn(popup(built), "change", { target: box });
}
function typeInPopup(built, which, value) {
  const el = popup(built).querySelector('[data-pk-el="' + which + '"]');
  el.value = String(value);
  fireOn(popup(built), "input", { target: el });
  return el;
}
function pressIn(built, which, key) {
  const el = popup(built).querySelector('[data-pk-el="' + which + '"]');
  let prevented = false;
  fireOn(popup(built), "keydown", { target: el, key: key, preventDefault() { prevented = true; } });
  return prevented;
}
function pressOneOff(built) {
  fireOn(popup(built), "click", { target: popup(built).querySelector("[data-pk-oneoff]") });
}
function pressAdd(built) {
  fireOn(popup(built), "click", { target: popup(built).querySelector("[data-pk-add]") });
}
const flush = () => new Promise((r) => setImmediate(r));
/** Press "Add a labor line": it reads the Labor list, then the pop-up appears. */
async function openLaborPopup(built) {
  clickOn(built, "[data-add-lab]");
  await flush();
}
/** A row the way a SAVED bid can still hold one: undecided. The add button no longer makes one,
 *  but the row still renders and its own search field still works, and these scenarios are about
 *  that field. */
function addUndecidedRow(built) {
  built.api.model().takeoff.push({ kind: "new", pick_name: "", measurement: "", unit: "SF" });
  built.api.changed(true);
}
function paints(log) {
  return log.filter((e) => /^(html|show|hide|text):/.test(e));
}
/** The class on the <tr> each markup amount sits in, so "this line is switched off" is readable. */
function rowClasses(markup) {
  const out = {};
  String(markup).split("<tr").slice(1).forEach((chunk) => {
    const cls = (/^([^>]*)class="([^"]*)"/.exec(chunk) || [])[2] || "";
    const key = (/data-mk="([^"]*)"/.exec(chunk) || [])[1];
    if (key) out[key] = cls;
  });
  return out;
}
/** Every condition switch the Review step rendered, by key: is it on, and is it a real switch.
 *
 *  Parsed out of the emitted HTML rather than mirrored from a list in this file, so "rendered a
 *  label but no track" and "rendered on when the model says off" are both visible. Same approach
 *  beta-routing-harness.js takes for the intake page's own `.sw`. */
function switches(markup) {
  const out = {};
  String(markup).split('<span class="mw-sw').slice(1).forEach((chunk) => {
    const key = (/data-cond="([^"]*)"/.exec(chunk) || [])[1];
    if (!key) return;
    const head = chunk.slice(0, chunk.indexOf(">"));
    out[key] = {
      on: /^ on"/.test(chunk),
      aria: (/aria-checked="([^"]*)"/.exec(head) || [])[1],
      role: (/role="([^"]*)"/.exec(head) || [])[1],
      hasTrack: /<span class="track"><\/span>/.test(chunk),
      focusable: /tabindex="0"/.test(head),
    };
  });
  return out;
}
/** One switch node the delegated click handler can find, shaped the way the page's own listener
 *  reaches for it: `closest("[data-cond]")` answers itself and `getAttribute` knows its key. */
function switchNode(key) {
  const node = {
    getAttribute: (a) => (a === "data-cond" ? key : null),
    closest: function (sel) { return sel === "[data-cond]" ? this : null; },
  };
  return node;
}
function readMk(built) {
  const money = {};
  built.doc.querySelectorAll("[data-mk]").forEach((el) => {
    money[el.getAttribute("data-mk")] = el.textContent;
  });
  const pcts = {};
  built.doc.querySelectorAll("[data-mkpct]").forEach((el) => {
    pcts[el.getAttribute("data-mkpct")] = el.textContent;
  });
  return { money: money, pcts: pcts, persf: txt(built, "[data-mk-persf]") };
}
/** Every "Labour"/"Crew" in a blob of text, with enough around it to find. */
function offenders(text) {
  const hits = [];
  // THE BRITISH SPELLING, deliberately, and it must stay that way: this sweep exists to prove the
  // page never renders "labour" (Hanz asked for "Labor") or "Crew". Rewriting this pattern to
  // /labor/ turns it into an assertion that the page never says the word it is supposed to say
  // everywhere, which is how a blind labour->labor sweep breaks the one test guarding the rename.
  const re = /labour|crew/gi;
  let m;
  while ((m = re.exec(String(text)))) {
    hits.push(String(text).slice(Math.max(0, m.index - 45), m.index + 45).replace(/\s+/g, " "));
  }
  return hits;
}

const out = {};
const rendered = [];      // every string the page put on screen, for the Labour/Crew sweep

(async function () {
  // ── A. the takeoff row shows the LIBRARY's price ───────────────────────────
  {
    const b = build();
    await b.api.init();
    rendered.push(b.dom.get("panels").innerHTML, b.dom.get("maths").innerHTML,
                  b.dom.get("bid-total").textContent, b.dom.get("bid-psf").textContent);
    const rows = MODEL.takeoff.map((r, i) => {
      const asm = ASMS.filter((a) => a.id === r.assembly_id)[0];
      const p = L.priceAssembly(asm, ITEMS, B.num(r.measurement));
      return {
        i: i,
        renderedCost: txt(b, '[data-cost-for="' + i + '"]'),
        renderedPerUnit: txt(b, '[data-perunit-for="' + i + '"]'),
        renderedMeasure: txt(b, '[data-measure-for="' + i + '"]'),
        renderedHint: txt(b, '[data-asmhint-for="' + i + '"]'),
        expectedTotal: p.total,
        expectedPerUnit: p.per_unit,
        lines: (asm.lines || []).length,
      };
    });
    const chain = expectedChain(MODEL, ASMS, ITEMS);
    out.takeoff = {
      rows: rows,
      matTotal: txt(b, "[data-mat-total]"),
      areaTotal: txt(b, "[data-area-total]"),
      expectedMaterial: rows.reduce((s, r) => s + r.expectedTotal, 0) + extraMaterial(MODEL),
      // LF rows are priced but must not count toward the area the price-per-SF divides by.
      expectedArea: B.takeoffSf(MODEL.takeoff),
      bidTotal: b.dom.get("bid-total").textContent,
      expectedChain: chain,
      // Three rows, three cost cells, three per-unit cells — one each, keyed by row.
      costCells: b.doc.querySelectorAll("[data-cost-for]").length,
      railLabels: b.dom.get("rail").kids.map((k) => k.textContent),
    };

    // A row whose material has been deleted from the library says so instead of pricing at zero.
    const broken = build({ blob: blob({ polish_estimate: Object.assign(clone(MODEL), {
      takeoff: [{ assembly_id: "a9", assembly_name: "Orphaned System", measurement: 1000,
                  unit: "SF" }] }) }) });
    await broken.api.init();
    rendered.push(broken.dom.get("panels").innerHTML);
    out.takeoff.brokenWarning = txt(broken, '[data-broken-for="0"]');
    out.takeoff.brokenCost = txt(broken, '[data-cost-for="0"]');
    out.takeoff.brokenClass = broken.doc.querySelector('[data-cost-for="0"]').className;

    // Picked, but not measured yet — the state EVERY row passes through on its way to a price, and
    // therefore the state most likely to be read. priceAssembly returns a perfectly legitimate
    // {total: 0} for it, so the cost box is the thing that has to decide whether that 0 means
    // "free" or means "nobody has said how much of it there is".
    const unmeasured = build({ blob: blob({ polish_estimate: Object.assign(clone(MODEL), {
      takeoff: [{ assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: "",
                  unit: "SF" }] }) }) });
    await unmeasured.api.init();
    const ucell = unmeasured.doc.querySelector('[data-cost-for="0"]');
    out.takeoff.unmeasured = { text: ucell.textContent, className: ucell.className };
    // And it must still be "—" after a repaint, not only on the first render: typing a measurement
    // and clearing it again goes back through repaintNumbers, not through the panel builder.
    const mInput = unmeasured.doc.querySelector('[data-tk="0"][data-k="measurement"]');
    mInput.value = "1000";
    unmeasured.doc.fire("input", { target: mInput });
    out.takeoff.afterTyping = unmeasured.doc.querySelector('[data-cost-for="0"]').textContent;
    mInput.value = "";
    unmeasured.doc.fire("input", { target: mInput });
    const back = unmeasured.doc.querySelector('[data-cost-for="0"]');
    out.takeoff.afterClearing = { text: back.textContent, className: back.className };
  }

  // ── B. the assembly picker resolves by the documented rule and only that ───
  {
    const b = build();
    await b.api.init();
    const id = (x) => (x ? x.id : null);
    out.picker = {
      exact: id(b.api.assemblyByName("Polish 800 Grit")),
      // Exact wins even where a case-insensitive twin exists.
      exactBeatsTheTwin: id(b.api.assemblyByName("Grind & Seal")),
      exactBeatsTheTwinUpper: id(b.api.assemblyByName("GRIND & SEAL")),
      uniqueCaseInsensitive: id(b.api.assemblyByName("cove base")),
      trimmed: id(b.api.assemblyByName("  Cove Base  ")),
      // Two assemblies differing only by case resolve to NOTHING. No arbitrary pick.
      ambiguousCase: id(b.api.assemblyByName("grind & seal")),
      ambiguousCaseMixed: id(b.api.assemblyByName("Grind & seal")),
      partialRefused: id(b.api.assemblyByName("Polish 800")),
      unknownRefused: id(b.api.assemblyByName("Nonsense")),
      blank: id(b.api.assemblyByName("")),
    };

    // Unknown text: the id is cleared but the TYPED NAME is kept, so blockers() can complain
    // about it by name and the estimator can see what they typed.
    const u = build();
    await u.api.init();
    u.api.setAssembly(0, "Terrazzo Polish");
    const row0 = u.api.model().takeoff[0];
    out.picker.unknownKeepsTheText = { id: row0.assembly_id, name: row0.assembly_name,
                                       blockers: B.blockers(u.api.model()) };

    // ── the unit follows the assembly, but only when the PICK changes ────────
    const v = build();
    await v.api.init();
    const before = v.api.model().takeoff[2].unit;                       // "SF"
    v.api.setAssembly(2, "Cove Base");                                  // an LF assembly
    const afterPick = { unit: v.api.model().takeoff[2].unit,
                        select: need(v, 'select[data-tk="2"][data-k="unit"]').value };
    // The estimator overrides it by hand, through the page's own change handler.
    const sel = need(v, 'select[data-tk="2"][data-k="unit"]');
    sel.value = "SF";
    v.doc.fire("change", { target: sel });
    const afterHand = v.api.model().takeoff[2].unit;
    // …and re-types the SAME assembly. The pick has not changed, so the unit must not be
    // re-stamped back to the library's.
    v.api.setAssembly(2, "Cove Base");
    out.unit = {
      before: before,
      afterPick: afterPick,
      afterHand: afterHand,
      afterRetype: v.api.model().takeoff[2].unit,
      // Switching to a different assembly DOES re-stamp it.
      afterDifferentPick: (function () {
        v.api.setAssembly(2, "Polish 800 Grit");
        return v.api.model().takeoff[2].unit;
      })(),
    };
  }

  // ── C. typing repaints the right cell and does NOT rebuild the panel ───────
  {
    const b = build();
    await b.api.init();
    const panels = b.dom.get("panels");
    const rebuilds = panels.htmlWrites;
    const was = [0, 1, 2].map((i) => txt(b, '[data-cost-for="' + i + '"]'));

    typeInto(b, '[data-tk="0"][data-k="measurement"]', "20000");
    const typedModel = Object.assign(clone(MODEL), { takeoff: clone(MODEL.takeoff).map(
      (r, i) => (i === 0 ? Object.assign(r, { measurement: "20000" }) : r)) });
    const chain = expectedChain(typedModel, ASMS, ITEMS);
    const p0 = L.priceAssembly(ASMS[0], ITEMS, 20000);
    out.typing = {
      noRebuild: panels.htmlWrites === rebuilds,
      rebuilds: panels.htmlWrites - rebuilds,
      costWas: was[0],
      costNow: txt(b, '[data-cost-for="0"]'),
      expectedCost: p0.total,
      measureNow: txt(b, '[data-measure-for="0"]'),
      perUnitNow: txt(b, '[data-perunit-for="0"]'),
      matTotalNow: txt(b, "[data-mat-total]"),
      areaTotalNow: txt(b, "[data-area-total]"),
      expectedChain: chain,
      // THE TRANSPOSITION / OFF-BY-ONE CLASS. Rows 1 and 2 were not touched, so their own cells
      // must still hold their own prices — not row 0's, and not each other's.
      othersUnmoved: [1, 2].map((i) => txt(b, '[data-cost-for="' + i + '"]') === was[i]),
      row1Cost: txt(b, '[data-cost-for="1"]'),
      row2Cost: txt(b, '[data-cost-for="2"]'),
      expectedRow1: L.priceAssembly(ASMS[1], ITEMS, 200).total,
      expectedRow2: L.priceAssembly(ASMS[2], ITEMS, 5000).total,
      // The field under the caret is never written to.
      fieldUntouched: need(b, '[data-tk="0"][data-k="measurement"]').textWrites === 0,
    };
    out.typing.expectedMaterialSum =
      L.priceAssembly(ASMS[0], ITEMS, 20000).total +
      L.priceAssembly(ASMS[1], ITEMS, 200).total +
      L.priceAssembly(ASMS[2], ITEMS, 5000).total +
      extraMaterial(typedModel);

    // LEAVING the assembly field must not rebuild the row either. `change` fires when the
    // estimator tabs out of it, and the field they tab INTO is Measurement — so a rebuild here
    // destroys the box under their cursor and the number they type next goes nowhere. Node
    // identity is the assertion: an htmlWrite on #panels replaces every child object.
    {
      const c = build();
      await c.api.init();
      const cPanels = c.dom.get("panels");
      const before = cPanels.htmlWrites;
      const measureBefore = need(c, '[data-tk="0"][data-k="measurement"]');
      const asmField = need(c, '[data-tk="0"][data-k="pick"]');
      asmField.value = ASMS[1].name;                 // retyped by hand, then tabbed away
      c.doc.fire("change", { target: asmField });
      const measureAfter = need(c, '[data-tk="0"][data-k="measurement"]');
      out.leavingTheAssemblyField = {
        rebuilds: cPanels.htmlWrites - before,
        measurementSurvived: measureBefore === measureAfter,
        // The pick still took effect, which is what the rebuild was there for.
        idNow: (c.api.model().takeoff[0] || {}).assembly_id,
        expectedId: ASMS[1].id,
        unitSyncedInPlace: need(c, 'select[data-tk="0"][data-k="unit"]').value,
        expectedUnit: ASMS[1].unit,
        hintNow: txt(c, '[data-asmhint-for="0"]'),
      };
    }

    // The same, on the labor side.
    b.api.go(1);
    rendered.push(panels.innerHTML);
    const labRebuilds = panels.htmlWrites;
    const lwas = [0, 1].map((i) => txt(b, '[data-lcost-for="' + i + '"]'));
    typeInto(b, '[data-lab="0"][data-k="guys"]', "6");
    out.typing.labor = {
      noRebuild: panels.htmlWrites === labRebuilds,
      costWas: lwas[0],
      costNow: txt(b, '[data-lcost-for="0"]'),
      expectedCost: B.laborCost({ guys: "6", days: 5, rate: 32.2 }),
      totalNow: txt(b, "[data-labor-total]"),
      expectedTotal: B.laborTotal([{ guys: "6", days: 5, rate: 32.2 },
                                   { guys: 3, days: 0.5, rate: 32.2 }]),
      otherUnmoved: txt(b, '[data-lcost-for="1"]') === lwas[1],
      row1Cost: txt(b, '[data-lcost-for="1"]'),
    };
  }

  // ── D. labor maths, and the add/remove lines ──────────────────────────────
  {
    const b = build();
    await b.api.init();
    b.api.go(1);
    const panels = b.dom.get("panels");
    rendered.push(panels.innerHTML);
    out.labor = {
      // 3 guys × 5 days × $32.20 × 8 hours = $3,864 — Kyle's own screenshot.
      anchorCell: txt(b, '[data-lcost-for="0"]'),
      anchorExpected: B.laborCost({ guys: 3, days: 5, rate: 32.2 }),
      halfDayCell: txt(b, '[data-lcost-for="1"]'),
      halfDayExpected: B.laborCost({ guys: 3, days: 0.5, rate: 32.2 }),
      totalCell: txt(b, "[data-labor-total]"),
      totalExpected: B.laborTotal(MODEL.labor),
      hoursPerDay: B.HOURS_PER_DAY,
      // A rate is money and wears the sign — outside the input, so the "$" is not parsed as part
      // of the number that was typed.
      rateWearsADollar: /<span class="mny">\$<input class="n" data-lab="0" data-k="rate"/
        .test(panels.innerHTML),
      costCellsWearADollar: [0, 1].every((i) =>
        String(txt(b, '[data-lcost-for="' + i + '"]')).charAt(0) === "$"),
      // The field labels of the FIRST labor card. This read `<th>` text until 2026-09-12, when the
      // step stopped being one table and became a card per task — the sheet heads each task with
      // its own `Guys | Days | Rate`, and Travel's middle column says HOURS rather than Days,
      // which one shared header row cannot express. Scoped to the first card so the list stays the
      // four field names rather than every label on the panel.
      headings: ((panels.innerHTML.split('class="tk lab')[1] || "").split("</div></div>")[0]
        .match(/<label>([^<]*)</g) || []).map((x) => (/>([^<]*)</.exec(x) || ["", ""])[1]),
      // Travel's own labels, to prove the hours row is headed differently from the crew rows.
      travelHeadings: ((panels.innerHTML.split('class="tk lab').slice(-1)[0] || "")
        .split("</div></div>")[0]
        .match(/<label>([^<]*)</g) || []).map((x) => (/>([^<]*)</.exec(x) || ["", ""])[1]),
      // One card per task, not one table: the count is what proves the step was restructured.
      cardCount: (panels.innerHTML.match(/class="tk lab/g) || []).length,
      tableGone: panels.innerHTML.indexOf("<table") === -1,
      // The auto/manual toggle is gated on `hours` -- a crew row (cards 0 and 1 here; card 2 is
      // the auto-appended Travel row) must never get one. Clicking it would run Travel's own
      // handler and overwrite the crew row's Guys with the man-day sum.
      noToggleOnCrewRows: [0, 1].every((i) => {
        var slice = (panels.innerHTML.split('class="tk lab')[i + 1] || "")
          .split("</div></div>")[0];
        return slice.indexOf("data-lab-manual=") === -1 &&
          slice.indexOf("data-lab-auto=") === -1;
      }),
      // THE "TYPE MY OWN" SWITCH IS GONE (Hanz, 2026-10-07), from every card on the step, Travel's
      // included. The "Included" slider on the same header is a different control and stays.
      noTypeMyOwn: {
        words: panels.innerHTML.indexOf("Type my own") === -1,
        labManual: panels.innerHTML.indexOf("data-lab-manual") === -1,
        labAuto: panels.innerHTML.indexOf("data-lab-auto") === -1,
        trvManual: panels.innerHTML.indexOf("data-trv-manual") === -1,
        trvAuto: panels.innerHTML.indexOf("data-trv-auto") === -1,
        noLabsw: panels.innerHTML.indexOf("labsw") === -1,
        includedOnTravelCard: /data-on-lab="2"/.test(
          (panels.innerHTML.split('class="tk lab')[3] || "").split('class="tk-g')[0]),
      },
      linkishGone: panels.innerHTML.indexOf("linkish") === -1,
      // THE HINT SAYS WHICH MODE THE BOX IS IN, in both positions (the fixture boots in auto, so
      // the typed wording has to be entered before it can be read), and the Included slider
      // still toggles a labor row without touching the Guys mode.
      hintsAndIncluded: await (async () => {
        const k = build();
        await k.api.init();
        k.api.go(1);
        const kp = k.dom.get("panels");
        const ti = k.api.model().labor.findIndex((r) => r.id === "travel");
        const hintOf = () => {
          const card = kp.innerHTML.split('class="tk lab')[ti + 1] || "";
          const g = card.split('data-k="guys"')[1] || "";
          // The Guys hint is keyed (data-hint-lab) so the in-place repaint can find it; read THAT one,
          // not the first plain hint after the box (which is the Hours line's).
          return (/<p class="hint" data-hint-lab="[^"]*">([^<]*)<\/p>/.exec(g) || ["", ""])[1];
        };
        const autoHint = hintOf();
        typeInto(k, '[data-lab="' + ti + '"][data-k="guys"]', "7");
        const typedHint = hintOf();
        const onBefore = k.api.model().labor[ti].enabled !== false;
        clickOn(k, '[data-on-lab="' + ti + '"]');
        const offRow = k.api.model().labor[ti];
        const afterOff = { enabled: offRow.enabled, guys_auto: offRow.guys_auto, guys: offRow.guys };
        clickOn(k, '[data-on-lab="' + ti + '"]');
        const onAgain = k.api.model().labor[ti].enabled !== false;
        return { autoHint: autoHint, typedHint: typedHint, onBefore: onBefore,
                 afterOff: afterOff, onAgain: onAgain };
      })(),
    };

    // ── the derived Guys figure, and the two ways across the auto/manual line ──
    {
      const c = build();
      await c.api.init();
      c.api.go(1);
      const cp = c.dom.get("panels");
      const travelIdx = () => c.api.model().labor.findIndex((r) => r.id === "travel");
      const travelRow = () => c.api.model().labor[travelIdx()];
      const before = travelRow().guys;
      // Typing days into a crew row must move Travel's man-days with it.
      typeInto(c, '[data-lab="0"][data-k="days"]', "4");
      const afterCrewEdit = travelRow().guys;
      // Typing in the auto box is how you leave auto — no control to find first.
      typeInto(c, '[data-lab="' + travelIdx() + '"][data-k="guys"]', "7");
      const afterTyping = { guys: travelRow().guys, auto: travelRow().guys_auto };
      // ...and it now IGNORES the crew, which is the whole point of having left auto.
      typeInto(c, '[data-lab="0"][data-k="days"]', "9");
      const stickyAfterCrewMoves = travelRow().guys;
      // The way back is CLEARING THE BOX. First the two halves of "not while typing": an empty
      // box on INPUT (the backspace in "1", backspace, "2") leaves the row typed, and only the
      // change (blur / Enter) hands it back. Whitespace counts as empty.
      typeInto(c, '[data-lab="' + travelIdx() + '"][data-k="days"]', "10");   // hours on the road
      const costTyped = txt(c, '[data-lcost-for="' + travelIdx() + '"]');
      typeInto(c, '[data-lab="' + travelIdx() + '"][data-k="guys"]', "");
      const midBackspace = { guys: travelRow().guys, auto: travelRow().guys_auto };
      typeInto(c, '[data-lab="' + travelIdx() + '"][data-k="guys"]', "2");
      const afterRetype = { guys: travelRow().guys, auto: travelRow().guys_auto };
      const writesBefore = cp.htmlWrites;
      changeTo(c, '[data-lab="' + travelIdx() + '"][data-k="guys"]', "   ");
      const clearRebuilds = cp.htmlWrites - writesBefore;
      const afterBackToAuto = { guys: travelRow().guys, auto: travelRow().guys_auto };
      const clearedBox = String(need(c, '[data-lab="' + travelIdx() + '"][data-k="guys"]').value);
      const clearedHint = need(c, '[data-hint-lab="' + travelIdx() + '"]').textContent
        === "Man-days from the tasks above.";
      const costAuto = txt(c, '[data-lcost-for="' + travelIdx() + '"]');
      // And the cost is the one the same man-days price on a never-touched row.
      const fresh = build();
      await fresh.api.init();
      fresh.api.go(1);
      typeInto(fresh, '[data-lab="0"][data-k="days"]', "9");
      const freshIdx = fresh.api.model().labor.findIndex((r) => r.id === "travel");
      typeInto(fresh, '[data-lab="' + freshIdx + '"][data-k="days"]', "10");
      const costFresh = txt(fresh, '[data-lcost-for="' + freshIdx + '"]');
      // Typing "2" over the man-days priced differently from the man-days.
      out.travelClear = { costTyped: costTyped, midBackspace: midBackspace,
        afterRetype: afterRetype, costAuto: costAuto, costFresh: costFresh,
        clearedBox: clearedBox, clearedHint: clearedHint, clearRebuilds: clearRebuilds };
      out.travelGuys = {
        seeded: before, afterCrewEdit: afterCrewEdit,
        afterTyping: afterTyping, stickyAfterCrewMoves: stickyAfterCrewMoves,
        afterBackToAuto: afterBackToAuto,
        // The box shows the derived figure rather than sitting empty next to a priced row.
        boxShowsIt: String(need(c, '[data-lab="' + travelIdx() + '"][data-k="guys"]').value),
      };
    }

    // ── the derived figure has to reach the SCREEN, not just the model ──
    // A browser pass on staging found Travel's Guys box still reading 1.5 after days went into
    // Polishing, because typing takes the `changed(false)` path: repaintNumbers refreshes the cost
    // cells and the totals, and nothing repainted the derived INPUT. The model was right the whole
    // time, which is exactly why every existing test passed.
    {
      const f = build({ blob: blob({ polish_estimate: null, polish_sf: 9000 }) });
      await f.api.init();
      f.api.go(1);
      const ti = () => f.api.model().labor.findIndex((r) => r.id === "travel");
      const boxVal = () => String(need(f, '[data-lab="' + ti() + '"][data-k="guys"]').value);
      const seededBox = boxVal();
      typeInto(f, '[data-lab="0"][data-k="days"]', "5");
      out.travelLiveRepaint = {
        seededBox: seededBox,
        modelAfterCrewEdit: f.api.model().labor[ti()].guys,
        boxAfterCrewEdit: boxVal(),
        // And the cost that figure drives, which is the half a wrong box actually misprices.
        costAfterCrewEdit: txt(f, '[data-lcost-for="' + ti() + '"]'),
      };
      typeInto(f, '[data-lab="' + ti() + '"][data-k="days"]', "2");
      out.travelLiveRepaint.costWithHours = txt(f, '[data-lcost-for="' + ti() + '"]');
      out.travelLiveRepaint.expectedWithHours = B.laborCost(
        { guys: 16.5, days: 2, rate: 33, unit: "hours" });
      out.travelLiveRepaint.modelWithHours = {
        guys: f.api.model().labor[ti()].guys, days: f.api.model().labor[ti()].days,
        rate: f.api.model().labor[ti()].rate
      };
    }

    // ── dimmed on a local job while UNTOUCHED, and lifts live the moment somebody types ──
    // `guys_auto: true` here (not false, as this fixture read until this change) -- it now has
    // to represent an untouched row to still dim, because touched-vs-untouched is the new half
    // of the rule. See `notDimmedWhenAlreadyManual` below for the guys_auto:false half.
    {
      const loc = build({ blob: blob({ polish_estimate: {
        version: 2,
        takeoff: [{ assembly_id: "a1", assembly_name: "x", measurement: 100, unit: "SF" }],
        labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: 33 },
                { id: "travel", label: "Travel", guys: 6, days: "", rate: 33,
                  unit: "hours", guys_auto: true }],
        conditions: { local: true }, contingency: 0
      } }) });
      await loc.api.init();
      loc.api.go(1);
      const li = loc.api.model().labor.findIndex((r) => r.id === "travel");
      const dimmedHtml = loc.dom.get("panels").innerHTML;
      const costBefore = B.laborTotal(loc.api.model().labor);
      // The card BEFORE typing -- captured as a live node, not a string, because the point of
      // this test is proving the LIVE repaint works. `syncAutoGuys` derives Travel's guys from
      // Polishing (3 x 2 = 6), the same figure the old fixture pinned by hand.
      const cardNode = () => loc.doc.querySelector('[data-lab-card="' + li + '"]');
      const classBeforeTyping = cardNode().className;
      typeInto(loc, '[data-lab="' + li + '"][data-k="days"]', "3");
      out.travelLocal = {
        dimmed: /class="tk lab inert"/.test(dimmedHtml),
        saysWhy: dimmedHtml.indexOf("marked local") !== -1,
        // NOT disabled: the house rule keeps a real `disabled` at .38-.5 and never dims a live
        // control by opacity alone. Typing must still land.
        noDisabledAttr: !/data-lab="[^"]*"[^>]*\sdisabled/.test(dimmedHtml),
        typedAnyway: loc.api.model().labor[li].days,
        costWasZeroWhileUnused: costBefore === B.laborCost(
          { guys: 3, days: 2, rate: 33 }),
        costAfterTyping: B.laborTotal(loc.api.model().labor),
        derivedGuys: loc.api.model().labor[li].guys,
        // THE LIVE LIFT. Typing Hours takes the `changed(false)` repaint path -- no rebuild -- so
        // this is the SAME node before and after, its className mutated in place by
        // repaintNumbers. A test reading `dimmedHtml` (a string snapshot) here would pass even
        // with that repaint block deleted entirely, because the stub's className setter never
        // touches innerHTML -- which is why this reads the live node instead.
        classBeforeTyping: classBeforeTyping,
        classAfterTypingHours: cardNode().className,
      };
      // Backspacing the hours back out re-dims, live, on the same node -- the flicker is
      // deliberate (clearing the one field that means "we're using this" is "we aren't, after
      // all"), not an oversight.
      typeInto(loc, '[data-lab="' + li + '"][data-k="days"]', "");
      out.travelLocal.classAfterClearingHours = cardNode().className;
    }

    // Typing GUYS also lifts it -- the actual reported scenario. A fresh build so it starts
    // untouched again; typing into an auto Guys box takes it off auto and rebuilds (`changed(true)`
    // via the existing auto-flip handler), so this exercises the OTHER path to the same class.
    {
      const locG = build({ blob: blob({ polish_estimate: {
        version: 2,
        takeoff: [{ assembly_id: "a1", assembly_name: "x", measurement: 100, unit: "SF" }],
        labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2, rate: 33 },
                { id: "travel", label: "Travel", guys: 6, days: "", rate: 33,
                  unit: "hours", guys_auto: true }],
        conditions: { local: true }, contingency: 0
      } }) });
      await locG.api.init();
      locG.api.go(1);
      const liG = locG.api.model().labor.findIndex((r) => r.id === "travel");
      typeInto(locG, '[data-lab="' + liG + '"][data-k="guys"]', "9");
      out.travelLocal.classAfterTypingGuys =
        locG.doc.querySelector('[data-lab-card="' + liG + '"]').className;
    }

    // A row already switched to manual (guys typed over, hours still blank) must NOT dim -- the
    // other half of the new rule, distinct from "untouched", and the coverage the fixture change
    // above would otherwise have deleted outright.
    {
      const manual = build({ blob: blob({ polish_estimate: {
        version: 2,
        takeoff: [{ assembly_id: "a1", assembly_name: "x", measurement: 100, unit: "SF" }],
        labor: [{ id: "travel", label: "Travel", guys: 6, days: "", rate: 33,
                  unit: "hours", guys_auto: false }],
        conditions: { local: true }, contingency: 0
      } }) });
      await manual.api.init();
      manual.api.go(1);
      out.travelLocal.notDimmedWhenAlreadyManual =
        !/class="tk lab inert"/.test(manual.dom.get("panels").innerHTML);
    }

    // A non-local job leaves it undimmed.
    {
      const away = build({ blob: blob({ polish_estimate: {
        version: 2,
        takeoff: [{ assembly_id: "a1", assembly_name: "x", measurement: 100, unit: "SF" }],
        labor: [{ id: "travel", label: "Travel", guys: 6, days: 2, rate: 33,
                  unit: "hours", guys_auto: false }],
        conditions: { local: false }, contingency: 0
      } }) });
      await away.api.init();
      away.api.go(1);
      out.travelLocal.undimmedWhenAway =
        !/class="tk lab inert"/.test(away.dom.get("panels").innerHTML);
    }

    // A SAVED bid with guys_auto false still opens as typed (hint says so), prices off the typed
    // number, and is not touched by merely opening and leaving the box alone.
    {
      const sv = build({ blob: blob({ polish_estimate: {
        version: 2,
        takeoff: [{ assembly_id: "a1", assembly_name: "x", measurement: 100, unit: "SF" }],
        labor: [{ id: "travel", label: "Travel", guys: 6, days: 2, rate: 33,
                  unit: "hours", guys_auto: false }],
        conditions: { local: false }, contingency: 0
      } }) });
      await sv.api.init();
      sv.api.go(1);
      const svH = sv.dom.get("panels").innerHTML;
      out.savedTypedRow = {
        typedHint: svH.indexOf("Typed by you. Clear it to use the man-days from the tasks above.") !== -1,
        guys: sv.api.model().labor[0].guys, auto: sv.api.model().labor[0].guys_auto,
        box: String(need(sv, '[data-lab="0"][data-k="guys"]').value),
        cost: txt(sv, '[data-lcost-for="0"]'),
        // 6 guys x 2 hours x $33
        expected: 6 * 2 * 33,
      };
      // A change event carrying the SAME number is not a clear.
      changeTo(sv, '[data-lab="0"][data-k="guys"]', "6");
      out.savedTypedRow.afterSameChange = sv.api.model().labor[0].guys_auto;
    }

    // Add a line: it appears, it is editable, and it prices from ITS OWN values. Travel is
    // backfilled onto MODEL's saved (pre-#491) two rows at boot — see migrateModel's Travel
    // comment — so the model already has three rows [Polishing, Mock-up, Travel] before this
    // click, and the new row lands at index 3, not 2.
    // Through the pop-up's One-off line, the one way a card with no library row behind it is made.
    await openLaborPopup(b);
    typeInPopup(b, "oneoff", "Densify");
    pressOneOff(b);
    out.labor.afterAdd = { count: b.api.model().labor.length,
                           rebuilt: panels.htmlWrites > 0 };
    typeInto(b, '[data-lab="3"][data-k="label"]', "Densify");
    typeInto(b, '[data-lab="3"][data-k="guys"]', "2");
    typeInto(b, '[data-lab="3"][data-k="days"]', "3");
    typeInto(b, '[data-lab="3"][data-k="rate"]', "40");
    out.labor.newRowCost = txt(b, '[data-lcost-for="3"]');
    out.labor.newRowExpected = B.laborCost({ guys: "2", days: "3", rate: "40" });
    out.labor.newRowLabel = b.api.model().labor[3].label;
    // …and the two rows above it are untouched by the new one's arithmetic.
    out.labor.row0StillAnchored = txt(b, '[data-lcost-for="0"]');
    out.labor.totalAfterAdd = txt(b, "[data-labor-total]");
    out.labor.totalAfterAddExpected = B.laborTotal(b.api.model().labor);

    // Delete the RIGHT one: index 1 is the mock-up, and it is the one that goes — not Polishing
    // above it, not the backfilled Travel row (index 2), and not Densify, just added last.
    clickOn(b, '[data-del-lab="1"]');
    out.labor.afterDelete = b.api.model().labor.map((r) => r.label);
    out.labor.afterDeleteCells = b.doc.querySelectorAll("[data-lcost-for]").length;
    // Polishing (0) and Densify — which shifted up past Travel into index 2 — are the two rows
    // either side of the gap; grabbing them (not 0/1) is what proves neither one's cost moved.
    out.labor.afterDeleteCosts = [0, 2].map((i) => txt(b, '[data-lcost-for="' + i + '"]'));

    // Take it down to one line: three rows remain [Polishing, Travel, Densify]. Polishing goes
    // first (an ordinary click, freshly queried), which is what actually reaches one line —
    // deleting Travel next. The ✕ is then not offered at all…
    clickOn(b, '[data-del-lab="0"]');
    const first = need(b, '[data-del-lab="0"]');
    clickEl(b, first);
    out.labor.atOneRow = { count: b.api.model().labor.length,
                           labels: b.api.model().labor.map((r) => r.label),
                           deleteOffered: b.doc.querySelectorAll("[data-del-lab]").length };
    // …and the guard behind it holds. Fired once more, the button the page itself rendered must not
    // leave the estimator with no labor table at all.
    clickEl(b, first);
    out.labor.afterDeletingTheLast = { count: b.api.model().labor.length,
                                       cells: b.doc.querySelectorAll("[data-lcost-for]").length,
                                       labels: b.api.model().labor.map((r) => r.label),
                                       cost: txt(b, '[data-lcost-for="0"]') };

    // Same guard on the takeoff side: three rows, and the first row's ✕ pressed three times.
    const t2 = build();
    await t2.api.init();
    const delRow = need(t2, '[data-del-row="0"]');
    clickEl(t2, delRow);
    clickEl(t2, delRow);
    clickEl(t2, delRow);
    out.labor.takeoffNeverEmpty = { count: t2.api.model().takeoff.length,
                                    cells: t2.doc.querySelectorAll("[data-cost-for]").length,
                                    row: t2.api.model().takeoff[0] };

    // Add a takeoff row: it appears empty, priced at nothing, and says where to search.
    const t3 = build();
    await t3.api.init();
    // Press Add assembly or material: nothing is added until a row is ticked and Add is pressed.
    clickOn(t3, "[data-add-row]");
    const beforePick = t3.api.model().takeoff.length;
    tick(t3, "item:i4");
    pressAdd(t3);
    out.labor.addedTakeoffRow = {
      beforePick: beforePick,
      count: t3.api.model().takeoff.length,
      row: clone(t3.api.model().takeoff[3]),
      // No measurement yet, so the cost box reads unpriced rather than free.
      cost: txt(t3, '[data-cost-for="3"]'),
    };
  }

  // ── E. review: the markup block IS the chain, gated by the conditions ──────
  {
    const live = clone(MODEL);
    live.conditions = { local: true, prevailing_wage: true, taxable: true,
                        remodel_tax: true, bond: true };
    const b = build({ blob: blob({ polish_estimate: clone(live) }) });
    await b.api.init();
    b.api.go(2);
    const panels = b.dom.get("panels");
    rendered.push(panels.innerHTML);
    out.review = {
      rendered: readMk(b),
      rowClasses: rowClasses(panels.innerHTML),
      expected: expectedChain(live, ASMS, ITEMS),
      expectedPct: (function () {
        const c = expectedChain(live, ASMS, ITEMS);
        return { gp_pct: B.pct(c.gp_pct),
                 sales_tax_pct: B.pct(c.sales_tax_pct), remodel_pct: B.pct(c.remodel_pct),
                 bond_pct: B.pct(c.bond_pct) };
      })(),
      switches: switches(panels.innerHTML),
      // Which labor lines the card actually lists, by label, in order.
      laborRowLabels: (function () {
        var m = /<table class="rev-t">[\s\S]*?<\/table>/g;
        var tables = String(panels.innerHTML).match(m) || [];
        var labor = tables[1] || "";
        return labor.split("<tr").slice(1)
          .map(function (c) { return (/<td>([\s\S]*?)<\/td>/.exec(c) || [])[1]; })
          .filter(function (s) { return s != null; });
      })(),
      // The label in the first column of every totalled row, in order.
      totalRowLabels: String(panels.innerHTML).split("<tr").slice(1)
        .filter((c) => /^[^>]*class="tot"/.test(c))
        .map((c) => (/<td>([\s\S]*?)<\/td>/.exec(c) || [])[1]),
      // The subtotal/total pairs in the order they appear down the screen. Order is the claim:
      // the running figure is the SUBTOTAL and the line that closes the card is the TOTAL, and a
      // swap would leave both words present and both wrong.
      labelOrder: String(panels.innerHTML)
        .match(/Material Subtotal|Material Total|Labor Subtotal|Labor Total|<td>Subtotal<\/td>/g)
        || [],
      expectedPerSf: B.money2(expectedChain(live, ASMS, ITEMS).per_sf) + " / SF",
    };

    // ── contingency feeds super/PTO, soft costs and the remodel tax ──────────
    const rebuilds = panels.htmlWrites;
    const beforeC = readMk(b);
    typeInto(b, "[data-contingency]", "5000");
    const withC = Object.assign(clone(live), { contingency: "5000" });
    out.review.contingency = {
      noRebuild: panels.htmlWrites === rebuilds,
      before: { super_pto: beforeC.money.super_pto, soft_costs: beforeC.money.soft_costs,
                remodel_tax: beforeC.money.remodel_tax, total: beforeC.money.total },
      after: readMk(b),
      expected: expectedChain(withC, ASMS, ITEMS),
      model: b.api.model().contingency,
    };

    // -- Travel is listed even at $0; a non-travel row at $0 is not --------------
    // THE COUNTEREXAMPLE IS THE POINT. If travel happened to be priced in the fixture, asserting
    // "travel appears" would prove nothing. Here travel has no hours and costs nothing, and
    // Joint filler is zeroed the same way -- so the two rows differ ONLY in which one is travel.
    const zeroTravel = clone(live);
    zeroTravel.labor = [
      { id: "polishing", label: "Polishing", guys: 3, days: 2, rate: 33 },
      { id: "jointfill", label: "Joint filler", guys: 3, days: "", rate: 33 },
      { id: "travel", label: "Travel", guys: "", days: "", rate: 33,
        unit: "hours", guys_auto: true },
    ];
    const zt = build({ blob: blob({ polish_estimate: clone(zeroTravel) }) });
    await zt.api.init();
    zt.api.go(2);
    out.review.zeroTravel = {
      labels: (function () {
        const tables = String(zt.dom.get("panels").innerHTML)
          .match(/<table class="rev-t">[\s\S]*?<\/table>/g) || [];
        return (tables[1] || "").split("<tr").slice(1)
          .map((c) => (/<td>([\s\S]*?)<\/td>/.exec(c) || [])[1])
          .filter((s) => s != null);
      })(),
      travelCost: B.laborCost(zeroTravel.labor[2]),
      jointFillerCost: B.laborCost(zeroTravel.labor[1]),
    };

    // ── the Fees + Textura line is typed, and marked up the way D77 is ───────
    // Same shape as contingency because it is the same kind of field, but the base it feeds is
    // larger: D77 sits inside GP's own divisor, so a typed fee grows the bid by MORE than itself.
    // That is Kyle's column, not a choice -- and it is the thing most likely to be read as a bug,
    // so it is measured against the real chain rather than asserted to be "about right".
    const feeRebuilds = panels.htmlWrites;
    const beforeF = readMk(b);
    typeInto(b, "[data-fees]", "800");
    const withF = Object.assign(clone(live), { contingency: "5000", fees: "800" });
    out.review.fees = {
      noRebuild: panels.htmlWrites === feeRebuilds,
      before: { gp: beforeF.money.gp, super_pto: beforeF.money.super_pto,
                soft_costs: beforeF.money.soft_costs, remodel_tax: beforeF.money.remodel_tax,
                total: beforeF.money.total },
      after: readMk(b),
      expected: expectedChain(withF, ASMS, ITEMS),
      model: b.api.model().fees,
      inputValue: (/data-fees value="([^"]*)"/.exec(panels.innerHTML) || [])[1],
      freshSeed: B.freshModel().fees,
      backfilled: B.migrateModel({ version: 2, takeoff: [], labor: [],
                                   conditions: {}, contingency: 0 }).fees,
    };

    // ── the GP band is RECOMPUTED, not printed once ──────────────────────────
    // The takeoff's measurement box is not on screen on the review step, so the two functions the
    // input handler calls — setAssembly then changed(false) — are called here in that same order.
    // Everything they touch is the page's own code, and the repaint is the real one.
    const g = build({ blob: blob({ polish_estimate: clone(live) }) });
    await g.api.init();
    g.api.go(2);
    const gpBefore = readMk(g);
    const gpRebuilds = g.dom.get("panels").htmlWrites;
    g.api.setAssembly(0, "Densifier Only");
    g.api.changed(false);
    const cheaper = clone(live);
    cheaper.takeoff[0] = { assembly_id: "a5", assembly_name: "Densifier Only",
                           measurement: 12500, unit: "SF" };
    out.review.gpBand = {
      pctBefore: gpBefore.pcts.gp_pct,
      pctAfter: readMk(g).pcts.gp_pct,
      subBefore: gpBefore.money.sub_total,
      subAfter: readMk(g).money.sub_total,
      expectedBefore: B.pct(expectedChain(live, ASMS, ITEMS).gp_pct),
      expectedAfter: B.pct(expectedChain(cheaper, ASMS, ITEMS).gp_pct),
      noRebuild: g.dom.get("panels").htmlWrites === gpRebuilds,
      gpAfter: readMk(g).money.gp,
      expectedGpAfter: expectedChain(cheaper, ASMS, ITEMS).gp,
    };

    // ── the two taxes switched off in the model ──────────────────────────────
    // hard_bid used to have its own row here too -- ON but still no discount under the $13,000
    // threshold was the one case that read like a bug and got its own note ("under the discount
    // threshold"). B68's gate left with the line on 2026-09-22, and no other condition has a
    // threshold shaped like it, so that note and the fixture built only to reach it are both
    // gone rather than pointed at a different key.
    const off = clone(MODEL);
    off.conditions = { local: true, prevailing_wage: false, taxable: false,
                       remodel_tax: false, bond: false };
    const o = build({ blob: blob({ polish_estimate: clone(off) }) });
    await o.api.init();
    o.api.go(2);
    rendered.push(o.dom.get("panels").innerHTML);
    out.review.off = {
      rendered: readMk(o),
      rowClasses: rowClasses(o.dom.get("panels").innerHTML),
      expected: expectedChain(off, ASMS, ITEMS),
      // The rows that are off carry their own switch, so the state is not just readable, it is
      // reachable -- this used to be an "off · edit in Intake" link back to the other step.
      switches: switches(o.dom.get("panels").innerHTML),
    };
  }

  // ── E2. the Review step's switches are real controls ──────────────────────
  // Every condition Review talks about can be answered HERE, not only back on Intake. Each click
  // goes through the page's own delegated listener, so this exercises the shipped path.
  {
    const start = clone(MODEL);
    start.conditions = { local: true, prevailing_wage: false, taxable: true,
                         remodel_tax: false, bond: false };
    out.review.clicks = {};
    for (const key of ["prevailing_wage", "taxable", "remodel_tax", "bond"]) {
      const c = build({ blob: blob({ polish_estimate: clone(start) }) });
      await c.api.init();
      c.api.go(2);
      const before = readMk(c);
      const wasOn = !!start.conditions[key];
      c.doc.fire("click", { target: switchNode(key) });
      const after = readMk(c);
      out.review.clicks[key] = {
        flipped: c.api.model().conditions[key] === !wasOn,
        // Every other key is left exactly as it was -- one click answers one question.
        othersUntouched: Object.keys(start.conditions).every(
          (k) => k === key || c.api.model().conditions[k] === start.conditions[k]),
        reRendered: switches(c.dom.get("panels").innerHTML)[key],
        expectedOn: !wasOn,
        totalBefore: before.money.total,
        totalAfter: after.money.total,
        expectedAfter: (function () {
          const m = clone(start);
          m.conditions[key] = !wasOn;
          return expectedChain(m, ASMS, ITEMS);
        })(),
        bondMoneyAfter: after.money.bond,
        bondPctAfter: after.pcts.bond_pct,
        // An answer given on Review has to reach the draft, or it is lost on the next load the
        // same way a typed contingency would be.
        queuedASave: c.clock.armed(),
      };
    }
  }

  // ── F. the save contract ──────────────────────────────────────────────────
  {
    const stale = blob({
      // What arrived on the sandbox copy from the project it was copied FROM. Deliberately carries
      // keys the beta never writes at BOTH levels — an epoxy job's phase total and the old
      // tax-handling phrase — because those are the ones a merge would leave behind, and a merge
      // that only overwrote the keys the beta happens to write would look harmless.
      computed_bid: { lump_sum: 999999, price_per_sf: 41.4,
                      epoxy_total: 66666, sales_tax_handling: "added to the bid",
                      full_bid: { total_base_bid: 999999, sales_tax: 88888,
                                  remodel_tax: 77777, epoxy_total: 55555,
                                  phase_prices: [111, 222] } },
      polish_sf: 4321,
    });
    const b = build({ blob: stale });
    await b.api.init();
    const before = b.rec.saves.length;
    typeInto(b, '[data-tk="0"][data-k="measurement"]', "20000");
    const queued = { armed: b.clock.armed(), sent: b.rec.saves.length - before };
    b.clock.fire();
    const save = b.rec.saves[b.rec.saves.length - 1];
    const model = clone(MODEL);
    model.takeoff[0].measurement = "20000";
    const chain = expectedChain(model, ASMS, ITEMS);
    out.save = {
      // Nothing goes out until the timer runs, and it runs once.
      debounced: queued.armed === 1 && queued.sent === 0,
      sentOnce: b.rec.saves.length - before === 1,
      keys: Object.keys(save).sort(),
      hasCellValues: Object.prototype.hasOwnProperty.call(save, "cell_values"),
      // Exactly which worksheet cells this page contributes. Since 2026-09-15 it writes the five
      // conditions' Yes/No literals and NOTHING else -- they are the contract it shares with the
      // intake page, which reads them back and lets the cell win over the model.
      cellValueKeys: Object.keys(save.cell_values || {}).sort(),
      cellValues: save.cell_values || null,
      version: save.polish_estimate.version,
      polishSf: save.polish_sf,
      modelTotals: save.polish_estimate.totals.total,
      computed: save.computed_bid,
      computedKeys: Object.keys(save.computed_bid).sort(),
      fullBidKeys: Object.keys(save.computed_bid.full_bid).sort(),
      expected: chain,
      // REPLACED, not merged, at BOTH levels: the source project's figures must be gone, not
      // sitting underneath a beta price.
      staleTotalGone: JSON.stringify(save.computed_bid).indexOf("999999") === -1,
      staleExtras: ["66666", "55555", "added to the bid", "phase_prices", "88888", "77777"]
        .filter((needle) => JSON.stringify(save.computed_bid).indexOf(needle) !== -1),
      staleSfGone: save.polish_sf !== 4321,
    };

    // Two edits inside one window: one save, carrying both.
    const c = build();
    await c.api.init();
    const n = c.rec.saves.length;
    typeInto(c, '[data-tk="0"][data-k="measurement"]', "18000");
    typeInto(c, '[data-tk="1"][data-k="measurement"]', "300");
    out.save.coalescedArmed = c.clock.armed();
    c.clock.fire();
    const both = clone(MODEL);
    both.takeoff[0].measurement = "18000";
    both.takeoff[1].measurement = "300";
    out.save.coalesced = c.rec.saves.length - n;
    out.save.coalescedTakeoff = c.rec.saves[c.rec.saves.length - 1]
      .polish_estimate.takeoff.map((r) => r.measurement);
    out.save.coalescedTotal = c.rec.saves[c.rec.saves.length - 1]
      .computed_bid.full_bid.total_base_bid;
    out.save.coalescedExpected = expectedChain(both, ASMS, ITEMS).total;

    // A draft that arrived WITH a worksheet map: recorded, not asserted on — the page adds none of
    // its own, and what Object.assign carries through from getState is reported for the record.
  // ── a material row: one product, priced straight off the library ───────────────────────────
  {
    const m = build();
    // BOOT FIRST. Without init() the library fetch never happens, ITEMS stays empty, and a
    // material name resolves to nothing -- which reads exactly like a broken picker. The
    // first version of this probe skipped it and spent its evidence blaming setMaterial.
    await m.api.init();
    m.api.go(0);
    addUndecidedRow(m);
    const idx = m.api.model().takeoff.length - 1;
    const row = () => m.api.model().takeoff[idx];
    // READ THE CARD, NOT THE PANEL. Since 2026-09-23 a row that changes kind is redrawn on its
    // own, precisely so the panel is not rebuilt under the estimator's caret -- which means the
    // panel's innerHTML is still the snapshot from the last full render and shows this row as it
    // was BEFORE the pick. Asking it whether the row says "MATERIAL" would answer about the past.
    const cardEl = () => need(m, '[data-row-card="' + idx + '"]');

    const seeded = clone(row());        // as the button pushes it: undecided, not a material yet
    typeInto(m, '[data-tk="' + idx + '"][data-k="pick"]', "Densifier");
    typeInto(m, '[data-tk="' + idx + '"][data-k="measurement"]', "10000");
    const pickedUnit = row().unit;                    // must stay SF, NOT the item's "Pail"
    const afterPick = clone(row());

    // THE MONEY, against library-core's own engine rather than a number typed into this file.
    // Densifier: $100 a pail, 1,000 SF a pail, 5% waste (its default, since the fixture gives it
    // no waste_pct of its own), roundup on. 10,000 SF needs 10.5 pails, which rounds up to 11.
    const expected = L.priceLine({ item_id: "i4" }, ITEMS, 10000);
    // READ THE NODE, NOT THE MARKUP. `changed(false)` repaints through textContent on the
    // cost element; the panel innerHTML captured at render time never moves, so a regex over
    // it reports the figure from before the keystroke -- em dash forever, which reads as a
    // row that will not price.
    const costCell = () => txt(m, '[data-cost-for="' + idx + '"]');
    const costWithLibraryCoverage = costCell();
    const itemCoverageBeforeOverride = m.api.items().find((it) => it.id === "i4").coverage;

    // A COVERAGE TYPED ON THE ROW WINS over the item's default, which is the whole reason the box
    // is there: the same product goes further in one system than another. priceLine itself no
    // longer reads a line's coverage at all (2026-09-22, coverage moved onto the material), so the
    // independent check here has to swap the ONE item the page is expected to swap, the same way
    // priceMaterialRow does -- comparing against the untouched item would just reproduce
    // costWithLibraryCoverage and prove nothing about the override reaching the engine.
    typeInto(m, '[data-tk="' + idx + '"][data-k="coverage"]', "500");
    const swapped = ITEMS.map((it) => (it.id === "i4" ? Object.assign({}, it, { coverage: 500 })
                                                       : it));
    const expectedTyped = L.priceLine({ item_id: "i4" }, swapped, 10000);
    const costWithTypedCoverage = costCell();
    // THE LIBRARY ITEM ITSELF, re-read after the typed override took effect. If priceMaterialRow
    // swapped the item in place instead of pricing against a copy, this would already read 500.
    const itemCoverageAfterOverride = m.api.items().find((it) => it.id === "i4").coverage;

    // The card, not the model: an assembly row and a material row must not look the same. Read
    // NOW, before the second row below forces a full renderPanel() rebuild -- the DOM stub only
    // fills in a parsed element's own innerHTML/children through a TARGETED repaint (repaintRow),
    // so cardEl() after a fresh full rebuild reads back an empty shell even though the real
    // page's markup (and the model) are both still correct. Reading it late doesn't prove the
    // card is wrong; it proves the stub was asked the wrong way.
    const saysMaterial = /MATERIAL/.test(cardEl().innerHTML);
    const cardClass = cardEl().className;
    const hasCoverageField = !!cardEl().querySelector('[data-k="coverage"]');

    // A SECOND ROW, ON THE SAME MATERIAL, ADDED AFTER THE FIRST ROW'S OVERRIDE AND LEFT BLANK.
    // This is the other half of the proof: a mutated (rather than copied) item would leak the
    // first row's 500 into every other row that points at "Densifier", including one that never
    // touched the coverage box itself.
    addUndecidedRow(m);
    const idx2 = m.api.model().takeoff.length - 1;
    typeInto(m, '[data-tk="' + idx2 + '"][data-k="pick"]', "Densifier");
    typeInto(m, '[data-tk="' + idx2 + '"][data-k="measurement"]', "10000");
    const secondRowBlankCoverageCost = txt(m, '[data-cost-for="' + idx2 + '"]');

    out.materialRow = {
      seeded: seeded,
      // IT BECOMES a material by being pointed at one, rather than being born one. The button
      // that knew the answer in advance is gone; `kind` is still written on the row, and still
      // not inferred from item_id alone, so clearing the name cannot flip it back.
      seededKind: seeded.kind,
      isItemKind: m.api.rowKind(row()) === "item",
      saysMaterial: saysMaterial,
      cardClass: cardClass,
      hasCoverageField: hasCoverageField,
      resolvedId: afterPick.item_id,
      // NO UNIT ADOPTION. An item's unit is what it is BOUGHT in (Pail), not how the floor is
      // measured. Copying it onto the row would price a 10,000 SF area in pails.
      unitStayedSF: pickedUnit === "SF",
      costWithLibraryCoverage: costWithLibraryCoverage,
      expectedLibraryCost: expected.cost,
      costWithTypedCoverage: costWithTypedCoverage,
      expectedTypedCost: expectedTyped.cost,
      // THE OVERRIDE STAYS ON THIS ROW: a per-job fact about this estimate, never written back
      // onto the material -- so the item's own coverage must read the same before and after.
      itemCoverageBeforeOverride: itemCoverageBeforeOverride,
      itemCoverageAfterOverride: itemCoverageAfterOverride,
      // ...and a second row on the same material, added after the first row's override and left
      // blank, still prices at the library's own coverage -- not the first row's 500.
      secondRowBlankCoverageCost: secondRowBlankCoverageCost,
      // An assembly row beside it is untouched and still an assembly row.
      assemblyRowsUnchanged: m.api.model().takeoff.slice(0, idx)
        .every((r) => !r.item_id && r.kind !== "item"),
    };
  }

  // ── the three that moved here, and the two things nothing was pinning ──────────────────────
  {
    // 1. THE SWITCHES ARE ON THE TAKEOFF STEP. Nothing asserted this: wrapping the whole block in
    //    `if (false)` -- deleting all three from the product -- left every test in this file green,
    //    because they all probe the MODEL and the CELLS, which a deleted control still writes
    //    correctly from its defaults. A feature nobody can see is not a feature.
    const s = build();
    s.api.go(0);                                         // the Takeoff step
    // READS THE PANEL FRESH ON EVERY CALL, below. Closing over one innerHTML snapshot is the
    // trap this repo already has a name for: the gate re-renders, and a closed-over string
    // reports the markup from BEFORE it, so a broken gate reads as a working one. Caught by
    // the probe disagreeing with itself -- joint filler off AND remove-existing not dimmed
    // in the same read, which cannot both be true.
    const sw = (key) => {
      const m = new RegExp('<span class="mw-sw([^"]*)" data-cond="' + key + '"').exec(s.dom.get("panels").innerHTML);
      return m ? { there: true, on: / on/.test(m[1]), inert: /inert/.test(m[1]) } : { there: false };
    };
    // 2. THE GATE. remove_existing_jf dims while joint filler is off -- its `needs` rule from the
    //    intake form. Dimmed, NOT hidden and NOT disabled: it adds a fourth hand to a crew that is
    //    not there, so it moves nothing, but its answer still has to reach Polish!F29 either way.
    s.api.model().conditions.joint_filler = false;
    s.api.go(0);
    const gatedOff = sw("remove_existing_jf");
    s.api.model().conditions.joint_filler = true;
    s.api.go(0);
    const gatedOn = (function () {
      const m = /<span class="mw-sw([^"]*)" data-cond="remove_existing_jf"/.exec(
        s.dom.get("panels").innerHTML);
      return m ? { inert: /inert/.test(m[1]) } : { inert: null };
    })();
    out.movedToTakeoff = {
      onTheTakeoffStep: { joint_filler: sw("joint_filler"), dye: sw("dye"),
                          remove_existing_jf: sw("remove_existing_jf") },
      gatedWhenJointFillerOff: gatedOff.inert,
      ungatedWhenJointFillerOn: gatedOn.inert === false,
      // Not on the Labor step, where they would read as priced labor.
      // THE CONTAINER. Hanz: "at least make it a container the same as the assemblie". Three bare
      // switches under a column of cards read as page furniture -- something that configures the
      // list rather than something in it.
      cards: (function () {
        var h = s.dom.get("panels").innerHTML;
        // Each card's own slice of the panel markup, from its own opening tag up to the next
        // card's -- so a check against one card cannot accidentally read markup belonging to a
        // different one. The anchor is `<div class="tk ` WITH THE TRAILING SPACE: it matches
        // `tk mat` and `tk cond` and does NOT match `tk-h` or `tk-g` inside the card, which a
        // bare `<div class="tk` anchor would find first and slice from.
        function cardHtml(tag) {
          var i = h.indexOf(">" + tag + "<");
          if (i < 0) return "";
          var start = h.lastIndexOf('<div class="tk ', i);
          var next = h.indexOf('<div class="tk ', i + 1);
          return h.slice(start, next < 0 ? h.length : next);
        }
        // A `.costbox` addressed by the data-condfig the page repaints it through, with its
        // class, so "$2,500" and "the greyed-out em dash" are told apart.
        function boxOf(block, key, part) {
          var m = new RegExp('<div class="costbox([^"]*)" data-condfig="' + key + '\\.' + part +
                             '">([^<]*)<').exec(block);
          return m ? { cls: m[1], empty: / empty/.test(m[1]), text: m[2] } : null;
        }
        function textOf(block, key, part) {
          var m = new RegExp('data-condfig="' + key + '\\.' + part + '">([^<]*)<').exec(block);
          return m ? m[1] : null;
        }
        // THE SHAPE HANZ ASKED FOR, read off the rendered markup rather than off the model:
        // a material card, four columns, a measurement and a unit and a total cost, and not one
        // box in it that takes typing.
        function probe(tag, key) {
          var block = cardHtml(tag);
          return {
            isMaterialCard: /^<div class="tk mat( inert)?">/.test(block),
            // GRAYED WHILE OFF (Hanz, 2026-10-01), read off the card's own opening tag.
            grayed: /^<div class="tk mat inert">/.test(block),
            usesTheAssemblyGrid: /<div class="tk-g matg">/.test(block),
            name: (/<div class="costbox txt">([^<]*)</.exec(block) || [])[1] || null,
            measurement: boxOf(block, key, "qty"),
            unit: boxOf(block, key, "unit"),
            cost: boxOf(block, key, "cost"),
            rate: textOf(block, key, "rate"),
            measureHint: textOf(block, key, "qtyhint"),
            headerSummary: textOf(block, key, "sub"),
            labels: (block.match(/<label>([^<]*)</g) || []).map(function (m) {
              return m.slice(7, -1);
            }),
            // NOTHING ON THE CARD IS TYPEABLE, which is the honest half of the redesign. A
            // Measurement box that accepted keystrokes and threw them away would be worse than
            // the switch-and-a-sentence card it replaced.
            // THE ONE BOX THAT TAKES TYPING is the Coverage box (data-condcov), this bid's own
            // override; it is stripped before looking for any other input or select.
            nothingTypeable: !/<input|<select/.test(
              block.replace(/<input class="n" data-condcov="[^"]*"[^>]*>/, "")),
            coverageBox: (/<input class="n" data-condcov="([^"]*)" value="([^"]*)" placeholder="([^"]*)">/
              .exec(block) || []).slice(1),
            coverageHint: textOf(block, key, "covhint"),
            // The switch does the row's remove button's job, so it sits where that button sits:
            // after the header's right-hand summary, not bolted on beside the tag.
            switchAfterTheSummary:
              block.indexOf('data-cond="' + key + '"') >
              block.indexOf('data-condfig="' + key + '.sub"'),
          };
        }
        return {
          // ONE switch-shaped card left, Remove Existing's. Joint Filler and Dye are `.tk mat`.
          count: (h.match(/class="tk cond/g) || []).length,
          jointFiller: probe("JOINT FILLER", "joint_filler"),
          dye: probe("DYE", "dye"),
          // REMOVE EXISTING IS THE CARD THIS CHANGE MUST NOT TOUCH -- it is a labor modifier,
          // priced on the Labor step, and Hanz named it out of scope by name.
          removeExisting: (function () {
            var block = cardHtml("REMOVE EXISTING");
            return {
              stillASwitchCard: /^<div class="tk cond/.test(block),
              noCostBox: !/costbox/.test(block),
              noMeasurement: !/data-condfig/.test(block),
              namesItsCell: /Polish!F29/.test(block),
              saysWhereItIsPriced: /Labor step/.test(block),
            };
          })(),
          // Each card names the cell it sets, which is the one thing every one of them does.
          namesItsCell: /Polish!E29/.test(h) && /Polish!F29/.test(h) && /Polish!E25/.test(h),
        };
      })(),
      notOnTheLaborStep: (function () {
        const t = build(); t.api.go(1);
        return !/data-cond="joint_filler"/.test(t.dom.get("panels").innerHTML);
      })(),
    };
  }

  {
    // THE PRICED CARDS FOLLOW THE TAKEOFF, LIVE. Every figure on them is derived from the area,
    // and typing a measurement takes `changed(false)` -- the in-place repaint, never a rebuild --
    // so a card the repaint does not know about goes stale the moment anybody types. It DID:
    // before 2026-09-19 nothing in repaintNumbers touched them, and the dollar figure beside the
    // switch stayed at whatever the last full render worked out.
    //
    // READ THE NODES, NOT THE MARKUP. A regex over the panel's innerHTML reports the string from
    // render time, so it would pass with the whole repaint block deleted.
    const s = build();
    await s.api.init();
    // SWITCHED ON HERE, because all three conditions ship OFF from 2026-09-19 and a card for a
    // line the bid is not buying shows an em dash. The claim under test is that a card which HAS
    // a figure keeps it in step with the area, so it needs a figure.
    s.api.model().conditions.joint_filler = true;
    s.api.model().conditions.dye = true;
    s.api.go(0);
    const fig = (key) => ({
      qty: txt(s, '[data-condfig="' + key + '.qty"]'),
      unit: txt(s, '[data-condfig="' + key + '.unit"]'),
      cost: txt(s, '[data-condfig="' + key + '.cost"]'),
      sub: txt(s, '[data-condfig="' + key + '.sub"]'),
      rate: txt(s, '[data-condfig="' + key + '.rate"]'),
      hint: txt(s, '[data-condfig="' + key + '.qtyhint"]'),
    });
    const panels = s.dom.get("panels");
    const rebuilds = panels.htmlWrites;
    const before = { jf: fig("joint_filler"), dye: fig("dye") };
    // Row 0 is 12,500 SF of the fixture's 17,500. Down to 3,000 the whole area is 8,000, which
    // is 3 kits rather than 5 -- a change the kit count cannot express by accident.
    typeInto(s, '[data-tk="0"][data-k="measurement"]', "3000");
    out.condCardsRepaint = {
      noRebuild: panels.htmlWrites === rebuilds,
      before: before,
      after: { jf: fig("joint_filler"), dye: fig("dye") },
      // What the real engine says about the area that is now on the screen, so the expectation
      // is bid-model's answer rather than a number typed into this file.
      expectedArea: 8000,
      expectedJfCost: B.jointFillerCost(8000, true),
      expectedDyeCost: B.dyeCost(8000, true),
    };
  }

  {
    // TOGGLING MOVES THE MATERIAL TOTAL BY EXACTLY THE FORMULA'S AMOUNT, AND NOTHING ELSE MOVES.
    // The guarantee the old cond-cost tests were really protecting, kept across the markup
    // change: the card is a new shape, the arithmetic behind the switch is not.
    const s = build();
    await s.api.init();
    s.api.go(0);
    const area = B.takeoffSf(s.api.model().takeoff);
    const read = () => ({
      material: s.api.materialTotal(),
      labor: B.laborTotal(s.api.model().labor),
      cost: txt(s, '[data-condfig="dye.cost"]'),
      matTotal: txt(s, "[data-mat-total]"),
    });
    const off = read();                                  // dye ships OFF
    need(s, '[data-cond="dye"]');
    s.doc.fire("click", { target: s.doc.querySelector('[data-cond="dye"]') });
    const on = read();
    out.dyeToggleMovesTheTotal = {
      area: area,
      materialOff: off.material,
      materialOn: on.material,
      expectedDelta: B.dyeCost(area, true),
      laborUnmoved: off.labor === on.labor,
      costBoxOff: off.cost,
      costBoxOn: on.cost,
      matTotalOn: on.matTotal,
    };
  }

  {
    // THE CELL WINS OVER THE MODEL, on this page as on intake. A draft whose blob never stated
    // these keys -- every draft written before they were model keys -- must take the estimator's
    // real answer out of cell_values rather than freshModel's default. Before the shared
    // conditionsFromCells reader, this page read the model alone: it would have shown joint filler
    // ON for a project where somebody turned it off, then written that Yes back over their No.
    const h = build({ blob: blob({
      polish_estimate: (function () { const m = clone(MODEL); delete m.conditions; return m; })(),
      cell_values: { "Polish!E29": "No", "Polish!E25": "Yes", "Polish!F29": "Yes" },
    }) });
    out.hydratedFromCells = {
      joint_filler: h.api.model().conditions.joint_filler,   // No  -> false, NOT freshModel's true
      dye: h.api.model().conditions.dye,                     // Yes -> true
      remove_existing_jf: h.api.model().conditions.remove_existing_jf,
      // A BLANK IS NOT AN ANSWER: an absent cell leaves the model's value alone, because every
      // save writes both literals and a blank therefore means nobody has answered yet.
      //
      // THE SAVED MODEL SAYS `true` ON PURPOSE. joint_filler ships OFF from 2026-09-19, so a
      // fixture that left the model at its default would read `false` whether the blank was
      // ignored (right) or taken as a No (wrong) -- the two answers would be the same
      // observation and this would prove nothing. A stated `true` is the only value that can
      // tell them apart.
      blankLeavesTheDefault: (function () {
        const stated = clone(MODEL);
        stated.conditions = Object.assign({}, MODEL.conditions, { joint_filler: true });
        const k = build({ blob: blob({ polish_estimate: stated,
                                       cell_values: { "Polish!E29": "" } }) });
        return k.api.model().conditions.joint_filler === true;
      })(),
    };
  }

    const legacy = build({ blob: blob({ cell_values: { "Polish!D82": 41000 } }) });
    await legacy.api.init();
    typeInto(legacy, '[data-tk="0"][data-k="measurement"]', "9000");
    legacy.clock.fire();
    out.save.legacyCellValues =
      legacy.rec.saves[legacy.rec.saves.length - 1].cell_values || null;
  }

  // ── G. migration, through the real migrateModel as adopt() calls it ────────
  {
    const V1 = {
      areas: [{ name: "Warehouse", sf: 12500 }, { name: "Dock", sf: 900 }],
      system: "800 Grit Polish",
      tooling: "rental",
      materials: [{ row: 17, name: "Densifier", cost: 1200 }],
      added: [{ row: 28, name: "Extra", cost: 50 }],
      // `labour`, not `labor` — v1 SAVED DATA, which migrateModel reads by that exact key. See the
      // same note on polish-bid-harness.js's V1 fixture.
      labour: { polishing: { crew: 4, days: 3, rate: 34 },
                mockup: { crew: 2, days: 1, rate: 30 },
                joint_filler: { crew: 5, days: 2, rate: 31 } },
      adds: { saw_cut: 1 },
      options: [{ name: "Cove", price: 900 }],
      conditions: { local: false, prevailing_wage: true, taxable: false,
                    remodel_tax: true },
    };
    const b = build({ blob: blob({ polish_estimate: clone(V1), polish_sf: 777 }) });
    await b.api.init();
    const M = b.api.model();
    out.migration = {
      keys: Object.keys(M).sort(),
      version: M.version,
      takeoff: M.takeoff,
      labor: M.labor,
      conditions: M.conditions,
      contingency: M.contingency,
      totals: M.totals,
      dropped: ["areas", "system", "tooling", "materials", "added", "adds", "options", "labour"]
        .filter((k) => k in M),
      // Rendered, not just migrated: the carried SF is on screen in the row's own boxes.
      measureCells: [0, 1].map((i) => txt(b, '[data-measure-for="' + i + '"]')),
      hints: [0, 1].map((i) => txt(b, '[data-asmhint-for="' + i + '"]')),
      blockers: B.blockers(M),
      // The v1 areas already measure something, so intake's polish_sf must not overwrite row 0.
      seededFromIntake: M.takeoff[0].measurement,
    };

    // Nothing measured at all: THEN intake's figure seeds row 0.
    const fresh = build({ blob: blob({ polish_estimate: null, polish_sf: 8250 }) });
    await fresh.api.init();
    out.migration.freshFromIntake = fresh.api.model().takeoff[0].measurement;
    // Hanz, 2026-10-05 ("Add SF, seed the takeoff"): System 2's box seeds a SECOND row, and a
    // system-2-only job seeds one row. Each is read off the model the page actually opened with.
    const rowsOf = (m) => m.takeoff.map((r) => [r.assembly_id, r.measurement, r.unit]);
    const two = build({ blob: blob({ polish_estimate: null, polish_sf: 8250, polish_2_sf: 3100 }) });
    await two.api.init();
    out.migration.seedTwo = rowsOf(two.api.model());
    const only2 = build({ blob: blob({ polish_estimate: null, polish_sf: 0, polish_2_sf: 3100 }) });
    await only2.api.init();
    out.migration.seedOnlyTwo = rowsOf(only2.api.model());
    // A measured takeoff takes NEITHER number, however much intake holds.
    const measured = build({ blob: blob({ polish_estimate: { version: 2,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: 5000, unit: "SF" }],
      labor: [], conditions: {}, contingency: 0, fees: 0, totals: {} },
      polish_sf: 8250, polish_2_sf: 3100 }) });
    await measured.api.init();
    out.migration.seedMeasured = rowsOf(measured.api.model());
    // THE DRAFT IS BROUGHT INTO LINE WITH THE MODEL ON OPEN, with no edit. Seeded rows are in
    // memory only, so without the save polish_sf stays System 1 alone; and a polish_sf typed over
    // a measured takeoff (the live intake's beta-continue door) has to be put back to the total.
    const lastSave = (x) => { x.clock.fire(); return x.rec.saves[x.rec.saves.length - 1] || null; };
    const sTwo = lastSave(two);
    out.migration.savedAfterSeedTwo = sTwo && { sf: sTwo.polish_sf, bidSf: sTwo.computed_bid.polish_sf };
    const clobbered = build({ blob: blob({ polish_estimate: { version: 2,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: 3000, unit: "SF" },
                { assembly_id: "", assembly_name: "", measurement: 2000, unit: "SF" }],
      labor: [], conditions: {}, contingency: 0, fees: 0, totals: {} },
      polish_sf: 3000 }) });
    await clobbered.api.init();
    const sClob = lastSave(clobbered);
    out.migration.savedAfterClobber = sClob && sClob.polish_sf;
    // Already in line: a plain reopen writes nothing.
    const inLine = build({ blob: blob({ polish_estimate: { version: 2,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: 5000, unit: "SF" }],
      labor: [], conditions: {}, contingency: 0, fees: 0, totals: {} },
      polish_sf: 5000 }) });
    await inLine.api.init();
    out.migration.savesWhenInLine = lastSave(inLine) ? 1 : 0;
    // The helper's own guard, which init's !takeoffSf check hides: an LF-only measurement is still
    // a measurement, so neither intake number may be seeded beside it.
    const lfRows = [{ assembly_id: "", assembly_name: "", measurement: 900, unit: "LF" }];
    out.migration.seedOverLf = rowsOf({ takeoff: B.seedTakeoffSf(lfRows, 8250, 3100) });

    // ── B6: THE DEFAULTS LOAD INTO A NEW BID (Hanz, 2026-10-05) ──────────────────────────────
    // Library with favorites: a1 (SF assembly), a2 (LF assembly), i1 (material, coverage 333 --
    // NOT the old 275 so a hard-coded constant shows), i4 (material, switched OFF), plus three that
    // must NOT load: the reserved dye row, an epoxy-only favorite, and a non-favorite.
    const dAsms = clone(ASMS).map((a) => {
      if (a.id === "a1" || a.id === "a2") a.favorite = true;
      if (a.id === "a5") { a.favorite = true; a.default_work_types = ["epoxy"]; }
      return a;
    });
    const dItems = clone(ITEMS).map((it) => {
      if (it.id === "i1") { it.favorite = true; it.coverage = 333; }
      if (it.id === "i4") { it.favorite = true; it.default_on = false; }
      return it;
    });
    dItems.push({ id: "dye", name: "Dye, per coat", unit: "Gal", buy_qty: 1, unit_cost: 10,
                  coverage: 1, favorite: true });
    const shape = (m) => m.takeoff.map((r) => ({ a: r.assembly_id || "", i: r.item_id || "",
      m: r.measurement, u: r.unit, sf: !!r.same_floor, off: r.enabled === false }));
    const loaded = build({ asms: dAsms, items: dItems,
      blob: blob({ polish_estimate: null, polish_sf: 8000, polish_2_sf: 2000 }) });
    await loaded.api.init();
    const lm = loaded.api.model();
    out.defaultsLoad = { rows: shape(lm), area: B.takeoffSf(lm.takeoff),
      i1Price: loaded.api.rowPrice(lm.takeoff[2]).total,
      i1Expected: L.priceLine({ item_id: "i1" }, dItems, 10000).cost,
      i1CoverageBox: lm.takeoff[2].coverage,
      offPrice: B.takeoffSf([lm.takeoff[3]]) };
    loaded.clock.fire();
    const dSave = loaded.rec.saves[loaded.rec.saves.length - 1] || null;
    out.defaultsLoad.savedSf = dSave && dSave.polish_sf;
    out.defaultsLoad.caption = txt(loaded, "[data-area-total]");
    // Nothing enabled to carry the floor: the intake boxes still seed plain area rows.
    const allOff = clone(dAsms).map((a) => { if (a.id === "a1") a.default_on = false;
                                             if (a.id === "a2") a.favorite = false; return a; });
    const offLoad = build({ asms: allOff, items: clone(ITEMS),
      blob: blob({ polish_estimate: null, polish_sf: 5000 }) });
    await offLoad.api.init();
    out.defaultsLoad.allOff = shape(offLoad.api.model());
    out.defaultsLoad.allOffArea = B.takeoffSf(offLoad.api.model().takeoff);
    // A SAVED bid is never touched, whatever the library holds now.
    const savedBlob = { version: 2, takeoff: [{ assembly_id: "", assembly_name: "",
      measurement: "", unit: "SF" }], labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 2,
      rate: 40 }], conditions: { local: true }, contingency: 0,
      fees: 0, totals: {} };
    const savedLoad = build({ asms: dAsms, items: dItems,
      blob: blob({ polish_estimate: savedBlob, polish_sf: 700 }) });
    await savedLoad.api.init();
    out.defaultsLoad.saved = shape(savedLoad.api.model());
    // THE REAL NEW-BID SHAPE: a bid that came through the beta intake. Intake saves migrateModel
    // output (conditions, one blank takeoff row) with `labor` deleted, so conditionsUnstated is
    // FALSE here and the defaults must still load. (Reviewer repro; the cases above all start from null.)
    const minted = B.migrateModel({});
    minted.conditions = Object.assign({}, minted.conditions, { local: true });
    delete minted.labor;
    const mintedLoad = build({ asms: dAsms, items: dItems,
      blob: blob({ polish_estimate: minted, polish_sf: 8000, polish_2_sf: 2000 }) });
    await mintedLoad.api.init();
    out.defaultsLoad.minted = shape(mintedLoad.api.model());
    out.defaultsLoad.mintedGateWasFalse = B.conditionsUnstated(minted);
    // Typing a number into a same_floor row ends the sharing; moving the carrier moves the rest.
    const mm = mintedLoad.api.model();
    typeInto(mintedLoad, '[data-tk="2"][data-k="measurement"]', "2000");
    out.defaultsLoad.ownTyped = { rows: shape(mintedLoad.api.model()),
      area: B.takeoffSf(mintedLoad.api.model().takeoff) };
    typeInto(mintedLoad, '[data-tk="0"][data-k="measurement"]', "6000");
    out.defaultsLoad.carrierMoved = { rows: shape(mintedLoad.api.model()),
      area: B.takeoffSf(mintedLoad.api.model().takeoff) };
    // No defaults in the library: exactly the System 1 / System 2 seeding, unchanged.
    const none = B.seedDefaultTakeoff([{ kind: "new", pick_name: "", measurement: "", unit: "SF" }],
      clone(ASMS), clone(ITEMS), ["dye"], 8250, 3100);
    out.defaultsLoad.none = rowsOf({ takeoff: none });
    // EMPTYING THE TAKEOFF MUST NOT BRING A DELETED ROW BACK (Hanz, 2026-10-05). Open a bid seeded
    // from System 1 + System 2, blank both rows, save, and reopen step 2 from what was saved. The
    // takeoff wrote polish_sf (now 0) but left intake's polish_2_sf at 3100, so the reopen read it
    // as a fresh measurement and put a 3,100 SF row back.
    const emptied = build({ blob: blob({ polish_estimate: null, polish_sf: 8250, polish_2_sf: 3100 }) });
    await emptied.api.init();
    typeInto(emptied, '[data-tk="0"][data-k="measurement"]', "");
    typeInto(emptied, '[data-tk="1"][data-k="measurement"]', "");
    emptied.clock.fire();
    const eSave = emptied.rec.saves[emptied.rec.saves.length - 1];
    const reopened = build({ blob: clone(emptied.store.blob) });
    await reopened.api.init();
    out.migration.emptiedSave = { sf: eSave.polish_sf, sf2: eSave.polish_2_sf };
    out.migration.emptiedDraft2 = emptied.store.blob.polish_2_sf;
    out.migration.emptiedReopen = rowsOf(reopened.api.model());
    out.migration.freshLabor = fresh.api.model().labor.map((r) => [r.id, r.guys, r.rate]);
  }

  // ── H. boot order ─────────────────────────────────────────────────────────
  {
    const b = build();
    await b.api.init();
    const p = paints(b.log);
    out.boot = {
      log: b.log,
      anyPaintBeforeSandbox: b.log.slice(0, b.log.indexOf("sandbox:in"))
        .some((e) => /^(html|show|hide|text):/.test(e)),
      sandboxBeforeFirstPaint: b.log.indexOf("sandbox:out") < b.log.indexOf(p[0]),
      mainShownAfterSandbox: b.log.indexOf("show:main") > b.log.indexOf("sandbox:out"),
      mainShownAfterTheLibrary:
        b.log.indexOf("show:main") > b.log.lastIndexOf("fetch:/api/library/items"),
      loadingHidden: b.dom.get("loading").hidden,
      mainShown: b.dom.get("main").hidden === false,
      bidBarShown: b.dom.get("bidbar").hidden === false,
      fetches: b.rec.fetches,
      projLine: b.dom.get("proj-line").textContent,
      alert: b.dom.get("alert").textContent,
    };

    // The sandbox could not settle: the page stays exactly where it was, and never even asks the
    // server for the library.
    const stopped = build({ sandboxOk: false });
    await stopped.api.init();
    out.boot.stopped = {
      paints: paints(stopped.log),
      fetches: stopped.rec.fetches,
      loadingText: stopped.dom.get("loading").textContent,
      loadingStillShown: stopped.dom.get("loading").hidden === false,
      mainStillHidden: stopped.dom.get("main").hidden !== false,
      saves: stopped.rec.saves.length,
    };

    // The library could not be fetched: an explanation in place of the form, not a blank page.
    const failed = build({ libraryFails: true });
    await failed.api.init();
    out.boot.libraryFailed = {
      loadingText: failed.dom.get("loading").textContent,
      loadingStillShown: failed.dom.get("loading").hidden === false,
      mainStillHidden: failed.dom.get("main").hidden !== false,
      panelsRendered: failed.dom.get("panels").htmlWrites,
    };

    // A library with no assemblies at all: the page opens, and says what is missing.
    const empty = build({ asms: [] });
    await empty.api.init();
    out.boot.emptyLibrary = { alert: empty.dom.get("alert").textContent,
                              mainShown: empty.dom.get("main").hidden === false };
    rendered.push(out.boot.libraryFailed.loadingText, out.boot.emptyLibrary.alert);

    // The sandbox switched drafts mid-boot: the COPY is what gets priced and named.
    const copy = build({ copyBlob: blob({
      __draft_id: "proj-1-beta", project_name: "Nearman Creek (beta test)",
      city: "Bonner Springs", state: "KS", beta_sandbox_of: "proj-1",
      polish_estimate: Object.assign(clone(MODEL), {
        // Remodel tax on with no county picked is what makes remodelSource() render its "pick a
        // county" link -- the one link the Review step still builds at RENDER time, and so the
        // one that proves withDraft was asked for the id the page SETTLED on.
        conditions: { local: true, prevailing_wage: false, taxable: true,
                      remodel_tax: true, bond: false },
        takeoff: [{ assembly_id: "a5", assembly_name: "Densifier Only", measurement: 500,
                    unit: "SF" }] }) }) });
    await copy.api.init();
    const copyCost = txt(copy, '[data-cost-for="0"]');
    copy.api.go(2);                     // the last step is where Continue lives
    out.boot.copyAdopted = {
      projLine: copy.dom.get("proj-line").textContent,
      cost: copyCost,
      expected: L.priceAssembly(ASMS[2], ITEMS, 500).total,
      rows: copy.api.model().takeoff.length,
      // Continue carries the draft the page settled ON, not the one it opened with.
      continueHref: (/href="([^"]*proposal-review[^"]*)"/
        .exec(copy.dom.get("panels").innerHTML) || [])[1],
      intakeHref: (/href="([^"]*polish-intake[^"]*)"/
        .exec(copy.dom.get("panels").innerHTML) || [])[1],
    };
  }

  // ── J. the remodel tax uses the county's REAL rate, never the sheet's 10% ──
  //
  // Kyle's workbook hardcodes 10% at B75. That is not a real rate anywhere: Kansas charges sales
  // tax on commercial remodel LABOR at the state rate plus the county portion only. Hanz,
  // 2026-08-18: "For the Remodel tax please use the real state tax or city tax, DONT USE 10%".
  // The page reads the rate off the draft under `county_remodel_rate`, the same key the live
  // estimate screen's county picker writes, so a project priced on either screen agrees.
  {
    const REMODEL_ON = Object.assign(clone(MODEL), {
      conditions: Object.assign({}, MODEL.conditions, { remodel_tax: true }),
    });

    // Johnson County KS, the figure Kyle and Will both quote.
    const jo = build({ blob: blob({ polish_estimate: clone(REMODEL_ON),
                                    county: "Johnson County, KS", county_remodel_rate: 0.07975 }) });
    await jo.api.init();
    jo.api.go(2);
    const joChain = expectedChain(REMODEL_ON, ASMS, ITEMS, 0.07975);
    out.remodelRate = {
      county: {
        pct: txt(jo, '[data-mkpct="remodel_pct"]'),
        money: txt(jo, '[data-mk="remodel_tax"]'),
        total: txt(jo, '[data-mk="total"]'),
        expectedPct: B.pct(joChain.remodel_pct),
        expectedMoney: joChain.remodel_tax,
        expectedTotal: joChain.total,
        rowNamesTheCounty: /Johnson County, KS/.test(jo.dom.get("panels").innerHTML),
        // The stored value already ends in "County, KS". Appending " County" to it read
        // "Johnson County, KS County" on screen.
        doubledCountyWord: /County,? [A-Z]{2} County|County County/
          .test(jo.dom.get("panels").innerHTML),
      },
    };

    // A rate TYPED on the live estimate screen, with a DIFFERENT county also on the draft.
    // The beta and the workbook it generates have to quote the same number, so the typed
    // one has to win here too -- otherwise picking Johnson County and then typing the
    // figure the state's site actually returned would price two different jobs.
    const typed = build({ blob: blob({ polish_estimate: clone(REMODEL_ON),
                                       county: "Wyandotte County, KS",
                                       county_remodel_rate: 0.0935,
                                       remodel_rate_override: 0.07975 }) });
    await typed.api.init();
    typed.api.go(2);
    const typedChain = expectedChain(REMODEL_ON, ASMS, ITEMS, 0.07975);
    out.remodelRate.typed = {
      pct: txt(typed, '[data-mkpct="remodel_pct"]'),
      money: txt(typed, '[data-mk="remodel_tax"]'),
      expectedPct: B.pct(typedChain.remodel_pct),
      expectedMoney: typedChain.remodel_tax,
      // Formatted through the same helper the page renders with, so the test compares a
      // string to a string instead of pinning a dollar figure by hand.
      expectedMoneyText: B.money(typedChain.remodel_tax),
      // what the COUNTY on the same draft would have charged, so the two cannot be confused
      whatTheCountyWouldBe: expectedChain(REMODEL_ON, ASMS, ITEMS, 0.0935).remodel_tax,
    };

    // No county picked: the Kansas state rate, and the row says to go and pick one.
    const none = build({ blob: blob({ polish_estimate: clone(REMODEL_ON) }) });
    await none.api.init();
    none.api.go(2);
    const noneChain = expectedChain(REMODEL_ON, ASMS, ITEMS, null);
    const noneHtml = none.dom.get("panels").innerHTML;
    out.remodelRate.fallback = {
      pct: txt(none, '[data-mkpct="remodel_pct"]'),
      money: txt(none, '[data-mk="remodel_tax"]'),
      expectedPct: B.pct(noneChain.remodel_pct),
      expectedMoney: noneChain.remodel_tax,
      saysStateRate: /Kansas state rate/i.test(noneHtml),
      offersToPickACounty: /pick a county/i.test(noneHtml),
      // What the sheet's 10% WOULD have charged, so the two can be compared.
      whatTenPercentWouldBe: expectedChain(REMODEL_ON, ASMS, ITEMS, 0.10).remodel_tax,
    };

    // A MISSOURI county: chosen, and carrying no remodel rate on purpose, because Missouri taxes
    // remodel labor as exempt. This must charge NOTHING — not the Kansas state fallback, which is
    // what a null-is-the-same-as-zero reading would have done to every Missouri job.
    const mo = build({ blob: blob({ polish_estimate: clone(REMODEL_ON),
                                    county: "Jackson County, MO", county_remodel_rate: null }) });
    await mo.api.init();
    mo.api.go(2);
    out.remodelRate.exemptCounty = {
      pct: txt(mo, '[data-mkpct="remodel_pct"]'),
      money: txt(mo, '[data-mk="remodel_tax"]'),
      saysExempt: /exempt/i.test(mo.dom.get("panels").innerHTML),
      // The number the Kansas fallback would have invented for this Missouri job.
      whatTheFallbackWouldBe: expectedChain(REMODEL_ON, ASMS, ITEMS, null).remodel_tax,
    };

    // A rate sitting on the draft must never switch the tax on by itself.
    const off = build({ blob: blob({ polish_estimate: clone(MODEL),
                                     county: "Johnson County, KS", county_remodel_rate: 0.07975 }) });
    await off.api.init();
    off.api.go(2);
    out.remodelRate.toggleOff = {
      pct: txt(off, '[data-mkpct="remodel_pct"]'),
      money: txt(off, '[data-mk="remodel_tax"]'),
    };
  }

  // ── I. the one list, filled from BOTH collections ──────────────────────────
  {
    const b = build();
    await b.api.init();
    const dl = b.dom.get("dl-lines");
    const opts = dl.children.filter((c) => c.tag === "option");
    const merged = ASMS.map((a) => a.name).concat(ITEMS.map((i) => i.name));
    out.datalist = {
      options: opts.map((c) => dec(c.attrs.value)),
      labels: opts.map((c) => c.attrs.label),
      expected: merged.filter((n, i) => merged.indexOf(n) === i)
        .sort((x, y) => x.localeCompare(y)),
      // The box is a searchable list input, not a <select>: the library will get long.
      pickerIsAList: /<input list="dl-lines" data-tk="0" data-k="pick"/
        .test(b.dom.get("panels").innerHTML),
      pickerIsNotASelect: !/<select[^>]*data-k="pick"/.test(b.dom.get("panels").innerHTML),
      // The name that is in both collections appears ONCE and says so.
      collision: opts.filter((c) => dec(c.attrs.value) === "Grout Compound")
        .map((c) => c.attrs.label),
      // Two assemblies differing only by case stay two options: collapsing them would hide a
      // library problem this page is not allowed to resolve.
      caseTwins: opts.filter((c) => dec(c.attrs.value).toLowerCase() === "grind & seal").length,
    };
  }

  // ── I2. dye and the joint filler kit: priced off their reserved library rows ─────────
  //
  // Hanz: "joint filler and die should be library items so that we are able to edit them as
  // well." Both are RESERVED library_items rows now (backend/library.py's RESERVED_ITEM_IDS),
  // seeded by the schema files and edited on the Items tab. The page prices its two condition
  // cards off them through library-core's priceLine (condLine), and falls back to
  // bid-model.js's jointFillerCost/dyeCost when a row is not there.
  //
  // RESERVED_SEED IS THE SEED. test_polish_estimate_page.py parses both schema files and requires
  // their inserts to say exactly this, so "the seeded rows price like today" below is a claim about
  // the rows the databases will actually hold, not about a fixture that could drift from them.
  {
    const RESERVED_SEED = [
      { id: "joint-filler-kit", name: "Joint filler, 10 gal kit", unit: "Kit", buy_qty: 1,
        unit_cost: 500, coverage: 3500, waste_pct: 0, roundup: true },
      { id: "dye", name: "Dye, per coat", unit: "SF", buy_qty: 1,
        unit_cost: 0.14, coverage: 1, waste_pct: 0, roundup: false },
      // THE THIRD RESERVED ROW, 2026-10-01 (Hanz: "All 3 exactly like materials"). It BUYS
      // NOTHING -- no cost, no coverage -- and nothing on this page prices off it: remove-existing
      // is a labor modifier, priced on the Labor step. It is in the seed so every identity below
      // runs WITH it present, which is the proof that it changes no price.
      { id: "remove-existing-jf", name: "Remove existing joint filler", unit: "SF", buy_qty: 1,
        unit_cost: null, coverage: null, waste_pct: 0, roundup: false },
    ];
    const seeded = (over) => ITEMS.concat(RESERVED_SEED.map((r) =>
      Object.assign({}, r, (over || {})[r.id] || {})));

    // One SF row with no assembly behind it: it gives the job its area and prices nothing, so the
    // material total is dye + joint filler and nothing else. Both conditions ON unless `off`.
    async function priced(items, sf, off, rem) {
      const model = clone(MODEL);
      model.takeoff = [{ assembly_id: "", assembly_name: "", measurement: sf, unit: "SF" }];
      model.conditions = Object.assign({}, model.conditions,
                                       { dye: !off, joint_filler: !off },
                                       rem ? { remove_existing_jf: true } : {});
      const b = build({ blob: blob({ polish_estimate: model }), items: items });
      await b.api.init();
      b.api.go(0);
      const cards = {};
      b.doc.querySelectorAll("[data-condfig]").forEach(function (el) {
        // The coverage sentence names the library row it read ("Blank uses the library's N"),
        // which is exactly what differs between a seeded and a missing row; the figures are
        // what this identity is about.
        if (/[.]covhint$/.test(el.attrs["data-condfig"])) return;
        cards[el.attrs["data-condfig"]] = el.textContent;
      });
      const html = b.dom.get("panels").innerHTML;
      return { material: b.api.materialTotal(), total: b.api.bid().total, cards: cards,
               renamedCard: /Our kit/.test(html) };
    }

    // THE SHIPPED CONSTANTS, called directly: the prices every bid had before either row existed.
    const constants = (sf) => B.dyeCost(sf, true) + B.jointFillerCost(sf, true);

    const SFS = [0, 1, 3500, 3501, 12000];
    const identity = {};
    for (const sf of SFS) {
      const withRows = await priced(seeded(), sf);
      const withoutRows = await priced(ITEMS, sf);
      identity[sf] = { seeded: withRows, missing: withoutRows, constants: constants(sf) };
    }

    // EDITING THE RATE CHANGES THE BID: $700 a kit and $0.50 a square foot, figures that share
    // nothing with the shipped $500 / $0.14.
    const rated = await priced(seeded({ "joint-filler-kit": { unit_cost: 700 },
                                        dye: { unit_cost: 0.5 } }), 3501);

    // EDITING THE KIT'S COVERAGE CHANGES THE KIT COUNT: 3,500 SF is one kit at the seeded 3,500
    // and four at 1,000 -- the same area, a different answer, because the row said so.
    const oneKit = await priced(seeded(), 3500);
    const fourKits = await priced(seeded({ "joint-filler-kit": { coverage: 1000 } }), 3500);
    // AND ITS WASTE, which the material rule applies before rounding up: 3,500 SF + 10% needs a
    // second kit.
    const wasted = await priced(seeded({ "joint-filler-kit": { waste_pct: 10 } }), 3500);

    // A ROW THAT CANNOT PRICE (cost or coverage blanked) falls back to the shipped formula rather
    // than charging $0 -- the same answer as a row that is not there at all.
    const blanked = await priced(seeded({ "joint-filler-kit": { coverage: null },
                                          dye: { unit_cost: null } }), 3501);

    // OFF IS STILL NOTHING, whatever the row says.
    const offWithRows = await priced(seeded({ "joint-filler-kit": { unit_cost: 700 } }), 3501,
                                     true);

    // THE LIVE NAME: renaming the row on the Items tab renames the card.
    const renamed = await priced(seeded({ "joint-filler-kit": { name: "Our kit" } }), 3500);

    // TYPED INTO A REAL MATERIAL ROW: the path the picker's list does not cover. setPick on a row
    // that is already a material goes through setMaterial, which once had a name loop of its own.
    const typedModel = clone(MODEL);
    typedModel.takeoff = [{ item_id: "i1", item_name: "OPF", measurement: 1000, unit: "SF" }];
    typedModel.conditions = Object.assign({}, typedModel.conditions, { dye: false, joint_filler: false });
    const tp = build({ blob: blob({ polish_estimate: typedModel }), items: seeded() });
    await tp.api.init();
    tp.api.setPick(0, "Dye, per coat");
    const typedDye = tp.api.model().takeoff[0].item_id;
    tp.api.setPick(0, "joint filler, 10 gal kit");
    const typedKit = tp.api.model().takeoff[0].item_id;
    tp.api.setPick(0, "OPF");
    const typedOrdinary = tp.api.model().takeoff[0].item_id;
    tp.api.setPick(0, "Remove existing joint filler");
    const typedRem = tp.api.model().takeoff[0].item_id;
    const typedPick = { dye: typedDye, kit: typedKit, ordinary: typedOrdinary, rem: typedRem };

    // REMOVE-EXISTING ON AS WELL, with its reserved row and without: the row prices nothing, so
    // the bid is the same to the cent either way, and the material total is what it is with
    // remove-existing off -- it is a labor modifier, never a material.
    const remWithRow = await priced(seeded(), 12000, false, true);
    const remWithoutRow = await priced(ITEMS, 12000, false, true);
    const remOff = await priced(seeded(), 12000);

    // NEVER A TAKEOFF ROW: not in the picker's list, and not resolved by typing the name out.
    const p = build({ items: seeded() });
    await p.api.init();
    p.api.go(0);
    const names = p.dom.get("dl-lines").children.filter((c) => c.tag === "option")
      .map((c) => dec(c.attrs.value));

    out.reservedItems = {
      seed: RESERVED_SEED,
      identity: identity,
      rated: { material: rated.material, cards: rated.cards,
               // Two kits at $700, and TWO COATS of 3,501 SF at $0.50 -- Kyle's rows 25 and 26.
               expected: 2 * 700 + 2 * 3501 * 0.5 },
      oneKit: oneKit.cards["joint_filler.qty"], oneKitHint: oneKit.cards["joint_filler.qtyhint"],
      fourKits: fourKits.cards["joint_filler.qty"],
      fourKitsCost: fourKits.material - 3500 * 0.14 * B.DYE_COATS,
      fourKitsHint: fourKits.cards["joint_filler.qtyhint"],
      wastedKits: wasted.cards["joint_filler.qty"],
      wastedHint: wasted.cards["joint_filler.qtyhint"],
      blanked: { material: blanked.material, constants: constants(3501) },
      offMaterial: offWithRows.material,
      renamed: renamed.renamedCard, notRenamedByDefault: oneKit.renamedCard,
      dyeNotInPicker: names.indexOf("Dye, per coat") === -1,
      jointFillerNotInPicker: names.indexOf("Joint filler, 10 gal kit") === -1,
      removeExistingNotInPicker: names.indexOf("Remove existing joint filler") === -1,
      ordinaryItemsStillListed: names.indexOf("OPF") !== -1 && names.indexOf("Densifier") !== -1,
      typedNameResolvesToNothing: p.api.itemByName("Dye, per coat") === null &&
        p.api.itemByName("joint filler, 10 gal kit") === null &&
        p.api.itemByName("Remove existing joint filler") === null,
      ordinaryNameStillResolves: (p.api.itemByName("OPF") || {}).id === "i1",
      typedPick: typedPick,
      removeExisting: { withRow: { material: remWithRow.material, total: remWithRow.total },
                        withoutRow: { material: remWithoutRow.material,
                                      total: remWithoutRow.total },
                        offMaterial: remOff.material },
    };

    // ── WHAT A SAVE HANDS KYLE'S WORKBOOK ──
    // The cell_values the page writes on a real save, per library state, beside the exact Dye /
    // Joint Filler line costs and kit count the bid priced. test_library_rates_reach_the_workbook.py
    // runs these cells through the REAL estimate_writer and evaluates the workbook it writes.
    async function saved(items, sf, cells) {
      const model = clone(MODEL);
      model.takeoff = [{ assembly_id: "", assembly_name: "", measurement: sf, unit: "SF" }];
      model.conditions = Object.assign({}, model.conditions, { dye: true, joint_filler: true });
      const over = { polish_estimate: model };
      if (cells) over.cell_values = cells;
      const b = build({ blob: blob(over), items: items });
      await b.api.init();
      b.api.saveSoon();
      b.clock.fire();
      const save = b.rec.saves[b.rec.saves.length - 1] || {};
      const area = B.takeoffSf(b.api.model().takeoff);
      const dye = b.api.condLine("dye", area);
      const jf = b.api.condLine("joint_filler", area);
      return { cells: save.cell_values || {}, area: area, dyeCost: dye.cost, jfCost: jf.cost,
               jfKits: jf.qty,
               // TODAY'S WRITE, for the same conditions: the two-argument call every save made
               // before the library reached the workbook.
               today: B.conditionCellWrites(b.api.model().conditions, cells || {}) };
    }
    const EDITED = { "joint-filler-kit": { unit_cost: 650, coverage: 2000 },
                     dye: { unit_cost: 0.2 } };
    const STALE_B29 = '=ROUNDUP(IF(E29="yes",(E18/2000),0),0)';
    out.reservedWorkbook = {
      seeded: await saved(seeded(), 3501),
      edited: await saved(seeded(EDITED), 3501),
      // 3,200 SF is ONE kit at 3,500 and TWO once 10% waste is bought -- the area where the
      // waste has to reach the workbook's own kit count or the two disagree.
      wasted: await saved(seeded({ "joint-filler-kit": { waste_pct: 10 } }), 3200),
      missing: await saved(ITEMS, 3501, { "Polish!C25": 0.3 }),
      blanked: await saved(seeded({ "joint-filler-kit": { coverage: null },
                                    dye: { unit_cost: null } }), 3501),
      // An earlier save wrote a 2,000 coverage; the row is back at 3,500 now.
      reset: await saved(seeded(), 3501, { "Polish!B29": STALE_B29, "Polish!C29": 650 }),
      staleB29: STALE_B29,
    };

    // ── G4: WHAT A SAVE WRITES FOR LABOR ── a bid mixing 8- and 10-hour lines, saved through the
    // page's own save. Reports every cell_values key so the test can prove which labor cells (if
    // any) reach the workbook, and the screen's own labor cost for the same lines.
    {
      const model = clone(MODEL);
      model.labor = [
        { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 40, hours_per_day: 10 },
        { id: "mockup", label: "Mock-up", guys: 2, days: 1, rate: 40, hours_per_day: 8 },
      ];
      const b = build({ blob: blob({ polish_estimate: model }) });
      await b.api.init();
      b.api.saveSoon();
      b.clock.fire();
      const save = b.rec.saves[b.rec.saves.length - 1] || {};
      out.laborWrites = { keys: Object.keys(save.cell_values || {}),
                          screenLabor: B.laborTotal(b.api.model().labor) };
    }

    // ── B2: COVERAGE, AS THIS BID'S OWN FIGURE ──
    // Joint Filler / Dye cards, a material row (what a loaded default becomes) and an assembly row
    // (each material line) all carry a Coverage box; a typed number prices the bid, reaches the
    // workbook's cells, and says "Library default: N" when it is not the library's.
    async function typedCov(items, sf, typed) {
      const model = clone(MODEL);
      model.takeoff = [{ assembly_id: "", assembly_name: "", measurement: sf, unit: "SF" }];
      model.conditions = Object.assign({}, model.conditions, { dye: true, joint_filler: true });
      const b = build({ blob: blob({ polish_estimate: model }), items: items });
      await b.api.init();
      b.api.go(0);
      const read = () => {
        const html = b.dom.get("panels").innerHTML;
        const box = (k) => (new RegExp('<input class="n" data-condcov="' + k +
          '" value="([^"]*)" placeholder="([^"]*)"').exec(html) || []).slice(1);
        return { jfBox: box("joint_filler"), dyeBox: box("dye"),
                 jfHint: txt(b, '[data-condfig="joint_filler.covhint"]'),
                 dyeHint: txt(b, '[data-condfig="dye.covhint"]'),
                 jfWarn: warn(b, '[data-condfig="joint_filler.covwarn"]'),
                 dyeWarn: warn(b, '[data-condfig="dye.covwarn"]'),
                 jfCost: txt(b, '[data-condfig="joint_filler.cost"]'),
                 jfQty: txt(b, '[data-condfig="joint_filler.qty"]'),
                 jfQtyHint: txt(b, '[data-condfig="joint_filler.qtyhint"]') };
      };
      const before = read();
      const matBefore = b.api.materialTotal();
      Object.keys(typed || {}).forEach((k) => {
        typeInto(b, '[data-condcov="' + k + '"]', typed[k]);
      });
      const after = read();
      b.api.saveSoon();
      b.clock.fire();
      const save = b.rec.saves[b.rec.saves.length - 1] || {};
      const area = B.takeoffSf(b.api.model().takeoff);
      const dye = b.api.condLine("dye", area), jf = b.api.condLine("joint_filler", area);
      return { before: before, after: after, matBefore: matBefore, matAfter: b.api.materialTotal(),
               cells: save.cell_values || {}, area: area, dyeCost: dye.cost, jfCost: jf.cost,
               jfKits: jf.qty, model: clone(b.api.model()),
               savedModel: clone((save.polish_estimate || {}).cond_cov || null),
               migrated: clone(B.migrateModel(save.polish_estimate).cond_cov || null) };
    }
    out.condCoverage = {
      // library kit at 2,000 -- NOT the old 3,500 constant -- 6,000 SF is 3 kits; typed 3,000 is 2
      libJf: await typedCov(seeded({ "joint-filler-kit": { coverage: 2000 } }), 6000,
                            { joint_filler: "3000" }),
      libDye: await typedCov(seeded({ dye: { coverage: 2, unit_cost: 0.2 } }), 6000,
                             { dye: "4" }),
      untouched: await typedCov(seeded({ "joint-filler-kit": { coverage: 2000 } }), 6000, {}),
      backToLibrary: await typedCov(seeded({ "joint-filler-kit": { coverage: 2000 } }), 6000,
                                    { joint_filler: "2000" }),
    };

    // A MATERIAL ROW and an ASSEMBLY ROW, as a loaded default would arrive: the row carries NO
    // coverage of its own, so the box must show the LIBRARY's figure (275, 775) and price with it.
    {
      const model = clone(MODEL);
      model.takeoff = [
        { kind: "item", item_id: "i1", item_name: "OPF", coverage: "", measurement: 5500, unit: "SF" },
        { assembly_id: "a1", assembly_name: "Polish 800 Grit", measurement: 12500, unit: "SF" },
      ];
      const b = build({ blob: blob({ polish_estimate: model }) });
      await b.api.init();
      b.api.go(0);
      const html = () => b.dom.get("panels").innerHTML;
      const matBox = () => (/data-tk="0" data-k="coverage" value="([^"]*)" placeholder="([^"]*)"/
        .exec(html()) || []).slice(1);
      const asmBoxes = () => (html().match(/data-asmcov="1" data-line="\d+" value="[^"]*" placeholder="[^"]*"/g)
        || []);
      const cost = (i) => txt(b, '[data-cost-for="' + i + '"]');
      const first = { matBox: matBox(), matHint: txt(b, '[data-covhint-for="0"]'),
                      asmBoxes: asmBoxes(), asmHint0: txt(b, '[data-asmcovhint="1:0"]'),
                      asmHint1: txt(b, '[data-asmcovhint="1:1"]'),
                      matCost: cost(0), asmCost: cost(1) };
      // The expected money, from library-core against the SAME library with the figure swapped.
      const swap = (id, cov) => ITEMS.map((it) => it.id === id ? Object.assign({}, it, { coverage: cov }) : it);
      const asmWith = (items) => L.priceAssembly(ASMS[0], items, 12500).total;
      typeInto(b, '[data-tk="0"][data-k="coverage"]', "300");
      const matTyped = { cost: cost(0), hint: txt(b, '[data-covhint-for="0"]'),
                         warn: warn(b, '[data-covwarn-for="0"]'),
                         expected: L.priceLine({ item_id: "i1" }, swap("i1", 300), 5500).cost };
      typeInto(b, '[data-asmcov="1"][data-line="0"]', "300");
      const asmTyped = { cost: cost(1), hint0: txt(b, '[data-asmcovhint="1:0"]'),
                         warn0: warn(b, '[data-asmcovwarn="1:0"]'),
                         warn1: warn(b, '[data-asmcovwarn="1:1"]'),
                         hint1: txt(b, '[data-asmcovhint="1:1"]'),
                         expected: asmWith(swap("i1", 300)),
                         libraryUntouched: ITEMS.find((i) => i.id === "i1").coverage,
                         line_cov: clone(b.api.model().takeoff[1].line_cov),
                         matTotal: b.api.materialTotal() };
      typeInto(b, '[data-tk="0"][data-k="coverage"]', "275");
      const matBackToLib = { hint: txt(b, '[data-covhint-for="0"]'),
                             warn: warn(b, '[data-covwarn-for="0"]') };
      // Switching the row to a different assembly drops the old lines' coverage.
      typeInto(b, '[data-tk="1"][data-k="pick"]', "Cove Base");
      const switched = { line_cov: b.api.model().takeoff[1].line_cov === undefined,
                         boxes: b.doc.querySelector('[data-row-card="1"]').querySelectorAll('[data-asmcov]').length };
      out.rowCoverage = { first: first, matTyped: matTyped, asmTyped: asmTyped,
                          matBackToLib: matBackToLib, switched: switched,
                          expectedFirstAsm: asmWith(ITEMS),
                          expectedFirstMat: L.priceLine({ item_id: "i1" }, ITEMS, 5500).cost };
    }
  }

  // ── J. one add control, and a row that categorises itself ──────────────────
  {
    const a = build();
    await a.api.init();
    a.api.go(0);
    const panels = a.dom.get("panels");
    const opening = panels.innerHTML;
    out.addControl = {
      addButtons: (opening.match(/data-add-row/g) || []).length,
      oldMaterialButton: /data-add-mat/.test(opening),
      dashedGhost: /class="addbtn"/.test(opening),
      isThePrimaryButton: /<button class="btn addline" data-add-row="1"/.test(opening),
      label: ((/data-add-row="1">\s*([^<]*)/.exec(opening) || [])[1] || "").trim(),
      // Above the rows, not under the last one.
      aboveTheRows: opening.indexOf("data-add-row") < opening.indexOf("data-row-card"),
    };

    addUndecidedRow(a);
    const idx = a.api.model().takeoff.length - 1;
    const row = () => a.api.model().takeoff[idx];
    const q = (k) => a.doc.querySelector('[data-tk="' + idx + '"][data-k="' + k + '"]');
    out.pendingRow = {
      seeded: clone(row()),
      kind: a.api.rowKind(row()),
      searchable: !!q("pick"),
      // NO COVERAGE BOX YET. It is a material's field, and nobody has said this is a material.
      hasCoverage: !!q("coverage"),
      cost: txt(a, '[data-cost-for="' + idx + '"]'),
      hint: txt(a, '[data-asmhint-for="' + idx + '"]'),
      mark: txt(a, '[data-mark-for="' + idx + '"]'),
      // It is a row like any other: it can be measured and it can be deleted.
      measurable: !!q("measurement"),
      deletable: !!a.doc.querySelector('[data-del-row="' + idx + '"]'),
    };

    // TYPING A MATERIAL NAME MAKES IT A MATERIAL ROW, coverage box and all — and only that card
    // is redrawn. A panel rebuild here is the focus bug this page already shipped once.
    const panelWrites = panels.htmlWrites;
    const cardBefore = a.doc.querySelector('[data-row-card="' + idx + '"]');
    typeInto(a, '[data-tk="' + idx + '"][data-k="pick"]', "Densifier");
    typeInto(a, '[data-tk="' + idx + '"][data-k="measurement"]', "10000");
    out.autoCategorise = {
      kind: a.api.rowKind(row()),
      row: clone(row()),
      // ASKED OF THE CARD, not of the document: the stub's #panels holds a flat copy of every
      // element the last full render made, and repaintRow replaces the card's children only.
      coverageAppeared: !!cardBefore.querySelector('[data-k="coverage"]'),
      markGone: !cardBefore.querySelector("[data-mark-for]"),
      labelNow: (cardBefore.querySelectorAll("label")[0] || {}).textContent,
      panelRebuilt: panels.htmlWrites !== panelWrites,
      sameCardNode: cardBefore === a.doc.querySelector('[data-row-card="' + idx + '"]'),
      cardRedrawn: cardBefore.htmlWrites,
      // THE MONEY, against library-core rather than a literal: 10,000 SF of a $100 pail that
      // covers 1,000 SF, rounded up, is 10 pails.
      cost: txt(a, '[data-cost-for="' + idx + '"]'),
      expectedCost: L.priceLine({ item_id: "i4" }, ITEMS, 10000).cost,
      unitStayedSF: row().unit,
      hint: txt(a, '[data-asmhint-for="' + idx + '"]'),
    };

    // An ASSEMBLY name in the same box flips it the other way, and the material's own fields go
    // with it — a leftover item_id would decide the row for ever, since rowKind reads it first.
    typeInto(a, '[data-tk="' + idx + '"][data-k="pick"]', "Cove Base");
    out.flipToAssembly = {
      kind: a.api.rowKind(row()),
      row: clone(row()),
      coverageGone: !cardBefore.querySelector('[data-k="coverage"]'),
      unitAdopted: row().unit,
      cost: txt(a, '[data-cost-for="' + idx + '"]'),
    };

    // CLEARING THE NAME DOES NOT TAKE THE KIND BACK, on either side of the line. The row stays
    // what it is, holding the measurement and the coverage somebody typed.
    const mc = build();
    await mc.api.init();
    addUndecidedRow(mc);
    const mi = mc.api.model().takeoff.length - 1;
    typeInto(mc, '[data-tk="' + mi + '"][data-k="pick"]', "Densifier");
    typeInto(mc, '[data-tk="' + mi + '"][data-k="measurement"]', "2000");
    typeInto(mc, '[data-tk="' + mi + '"][data-k="coverage"]', "500");
    typeInto(mc, '[data-tk="' + mi + '"][data-k="pick"]', "");
    out.clearedMaterial = {
      kind: mc.api.rowKind(mc.api.model().takeoff[mi]),
      row: clone(mc.api.model().takeoff[mi]),
      coverageBoxStayed: !!mc.doc.querySelector(
        '[data-tk="' + mi + '"][data-k="coverage"]'),
    };
  }

  // ── K. a name that is two things is never guessed ──────────────────────────
  {
    const q = build();
    await q.api.init();
    addUndecidedRow(q);
    const qi = q.api.model().takeoff.length - 1;
    typeInto(q, '[data-tk="' + qi + '"][data-k="pick"]', "Grout Compound");
    const choices = () => q.doc.querySelectorAll("[data-kind-pick]");
    out.ambiguous = {
      kind: q.api.rowKind(q.api.model().takeoff[qi]),
      row: clone(q.api.model().takeoff[qi]),
      // It prices NOTHING while it is undecided. Picking one of two costs by accident is the
      // failure this whole branch exists to prevent.
      cost: txt(q, '[data-cost-for="' + qi + '"]'),
      asked: txt(q, '[data-asmhint-for="' + qi + '"]'),
      offered: choices().map((e) => e.getAttribute("data-kind-pick")),
      mark: txt(q, '[data-mark-for="' + qi + '"]'),
    };

    clickOn(q, '[data-kind-pick="item"]');
    typeInto(q, '[data-tk="' + qi + '"][data-k="measurement"]', "1000");
    out.ambiguous.afterChoosingMaterial = {
      kind: q.api.rowKind(q.api.model().takeoff[qi]),
      row: clone(q.api.model().takeoff[qi]),
      cost: txt(q, '[data-cost-for="' + qi + '"]'),
      expected: L.priceLine({ item_id: "i5" }, ITEMS, 1000).cost,
      stillAsking: q.doc.querySelectorAll("[data-kind-pick]").length,
    };

    // The other button, on its own build, resolves to the ASSEMBLY of that name — a different
    // id, different lines and a different number, which is what makes the choice real.
    const w = build();
    await w.api.init();
    addUndecidedRow(w);
    const wi = w.api.model().takeoff.length - 1;
    typeInto(w, '[data-tk="' + wi + '"][data-k="pick"]', "Grout Compound");
    clickOn(w, '[data-kind-pick="asm"]');
    typeInto(w, '[data-tk="' + wi + '"][data-k="measurement"]', "1000");
    out.ambiguous.afterChoosingAssembly = {
      kind: w.api.rowKind(w.api.model().takeoff[wi]),
      row: clone(w.api.model().takeoff[wi]),
      cost: txt(w, '[data-cost-for="' + wi + '"]'),
      expected: L.priceAssembly(ASMS[5], ITEMS, 1000).total,
    };

    // A row that already IS something keeps what it is, and is never asked.
    const s = build();
    await s.api.init();
    typeInto(s, '[data-tk="0"][data-k="pick"]', "Grout Compound");
    out.ambiguous.settledRowIsNotAsked = {
      kind: s.api.rowKind(s.api.model().takeoff[0]),
      assemblyId: s.api.model().takeoff[0].assembly_id,
      itemId: s.api.model().takeoff[0].item_id,
      asked: s.doc.querySelectorAll("[data-kind-pick]").length,
    };
  }

  // ── L. a bid made of materials is a finished bid ───────────────────────────
  {
    const mo = build({ blob: blob({ polish_estimate: Object.assign(clone(MODEL), {
      takeoff: [{ kind: "item", item_id: "i4", item_name: "Densifier", measurement: 10000,
                  unit: "SF", coverage: "" }] }) }) });
    await mo.api.init();
    mo.api.go(2);
    const first = (/<table class="rev-t">[\s\S]*?<\/table>/.exec(
      mo.dom.get("panels").innerHTML) || [""])[0];
    out.materialOnly = {
      pip: mo.api.stepStatus().takeoff,
      reviewPip: mo.api.stepStatus().review,
      blockers: B.blockers(mo.api.model()),
      names: (first.match(/<td>[^<]*</g) || []).map((s) => s.slice(4, -1)),
    };
  }

  // ── the shell: three steps, counted from the step list ────────────────────
  {
    const b = build();
    await b.api.init();
    const panels = b.dom.get("panels");
    const seen = [];
    for (let i = 0; i < b.api.STEPS.length; i++) {
      b.api.go(i);
      const rail = b.dom.get("rail").kids;
      seen.push({
        stepOf: (/<span class="step-of">([^<]*)</.exec(panels.innerHTML) || [])[1] || null,
        heading: (/<h2>([^<]*)</.exec(panels.innerHTML) || [])[1] || null,
        navText: (panels.innerHTML.match(/data-go="\d+">([^<]*)</g) || [])
          .map((x) => dec((/>([^<]*)</.exec(x) || ["", ""])[1])),
        railCount: rail.length,
        railLabels: rail.map((k) => k.textContent),
        railPips: rail.map((k) => (k.kids[0] || {}).textContent),
        current: rail.map((k) => k.attrs["aria-current"] || ""),
      });
      rendered.push(panels.innerHTML);
    }
    out.shell = { steps: seen,
                  stepKeys: b.api.STEPS.map((s) => s.key),
                  stepLabels: b.api.STEPS.map((s) => s.label),
                  units: b.api.UNITS };
  }

  // ── the word Hanz asked us to stop using, in RENDERED output only ──────────
  out.words = {
    renderedHits: offenders(rendered.join("\n")),
    markupHits: offenders(pageHtml.replace(/<!--[\s\S]*?-->/g, "")
                                  .replace(/<style[\s\S]*?<\/style>/g, "")),
    renderedChars: rendered.join("\n").length,
  };

  // ── Fault 3 on this page: nothing flushed the 600ms timer before a tab close/switch ──
  //
  // Same gap as the intake page: shared.js's OWN pagehide net (shared.js:513) only flushes a timer
  // THIS page armed, and before the fix nothing here armed one from a takeoff edit soon enough to
  // matter within the 600ms window. The page now pushes the pending save through synchronously and
  // forces the network flush on pagehide, rather than trusting the debounce to survive a tab close.
  {
    const b = build();
    await b.api.init();
    typeInto(b, '[data-tk="0"][data-k="measurement"]', "12000");
    const armedBeforeLeaving = b.clock.armed();
    const before = b.rec.saves.length;
    b.win.fire("pagehide");
    out.pagehideFlush = {
      wired: b.win.listeners.some((l) => l.type === "pagehide"),
      armedBeforeLeaving,
      savedSynchronously: b.rec.saves.length - before,   // save ran inline, not on the timer
      armedAfterLeaving: b.clock.armed(),                // the timer it cleared
      flushedTheNetwork: b.rec.flushed,                  // TW.flushState(), forcing the PUT now
    };

    // Nothing typed, nothing armed: leaving must not manufacture a save out of thin air.
    // (A blob with no SF anywhere: init now saves when it SEEDS rows or finds polish_sf behind the
    // takeoff, so the default fixture's seeded SF would arm a timer legitimately.)
    const d = build({ blob: blob({ polish_estimate: null, polish_sf: 0 }) });
    await d.api.init();
    d.win.fire("pagehide");
    out.pagehideFlush.quietWhenNothingArmed = d.rec.saves.length === 0 && d.rec.flushed === 0;
  }

  // ── J. the library's default labor lines ──────────────────────────────────
  //
  // "+ Add a labor line" on Library -> Default Items & Assemblies shipped wired to nothing,
  // because nothing stored a custom labor line. public.library_labor now does, and this step is
  // what reads it. Every case below is the page BOOTED and its Labor step RENDERED, because the
  // way this feature fails is invisible to a source assertion: a gate that reads the wrong thing
  // still contains the word laborUnstated, and rows that never reach the panel are still on a
  // model somebody could print.
  {
    // Shaped the way GET /api/library/labor returns them: `name` not `label`, a numeric that can
    // arrive as TEXT out of PostgREST, and a `sort` the server has already ordered by.
    //
    // BOTH `favorite: true`, 2026-09-24. The Labor tab lets a labor TYPE exist without being a
    // DEFAULT, so seedLibraryLabor only seeds a favorited row now -- these two are marked the way
    // an admin favorites one on the Defaults tab, which is what every assertion below expects a
    // brand new bid to open holding.
    const LIB = [
      { id: "lab-densify", name: "Densify", rate: "40.00", unit: "days", guys_auto: false,
        sort: 0, notes: null, owner_email: "hanz@wetreadwell.com", favorite: true },
      { id: "lab-night", name: "Night shift premium", rate: 12.5, unit: "hours", guys_auto: true,
        sort: 1, notes: "after 6pm", owner_email: "hanz@wetreadwell.com", favorite: true },
    ];
    /** The names the LABOR STEP actually put on screen, read off the inputs it rendered. */
    const onScreen = (built) => built.doc.querySelectorAll('[data-lab][data-k="label"]')
      .map((el) => el.value);
    const ids = (built) => built.api.model().labor.map((r) => r.id);

    // A brand-new project: no polish_estimate on the draft at all, which is what the sidebar door
    // and a project that reached this page without going through the beta intake both look like.
    const noKey = blob();
    delete noKey.polish_estimate;
    const brandNew = build({ blob: noKey, labor: LIB });
    await brandNew.api.init();
    brandNew.api.go(1);

    // THE NORMAL FLOW, and the case that decides whether any of this is reachable at all. Every
    // beta project starts on polish-intake.html, and its save mints the first polish_estimate --
    // this exact blob: version, takeoff, conditions, and no labor, because labor is not that
    // page's to state. If this one does not seed, the feature only works for people who skipped
    // the intake step.
    const fromIntake = build({ blob: blob({ polish_estimate: {
      version: 2,
      takeoff: [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }],
      conditions: { local: true, prevailing_wage: false, taxable: true,
                    remodel_tax: false, bond: false },
      contingency: 0, fees: 0, totals: {} } }), labor: LIB });
    await fromIntake.api.init();
    fromIntake.api.go(1);

    // AN ESTIMATOR'S OWN WORK. Four rows with their own numbers, Travel already in its current
    // shape and switched to manual (so neither migrateModel nor syncAutoGuys has anything
    // legitimate to change), and a library default they kept and re-rated from $40 to $55.
    const WORKED = {
      version: 2,
      takeoff: clone(MODEL.takeoff),
      labor: [
        { id: "polishing", label: "Polishing", guys: 4, days: 6, rate: 33 },
        { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
        { id: "travel", label: "Travel Labor", guys: 18, days: 2, rate: 33,
          unit: "hours", guys_auto: false },
        { id: "lab-densify", label: "Densify", guys: 2, days: 1, rate: 55, unit: "days",
          guys_auto: false },
      ],
      conditions: clone(MODEL.conditions),
      contingency: 0, fees: 0, totals: {},
    };
    const worked = build({ blob: blob({ polish_estimate: clone(WORKED) }), labor: LIB });
    await worked.api.init();
    worked.api.go(1);

    // The same saved bid, opened on a day when the default has been DELETED from the library.
    const deleted = build({ blob: blob({ polish_estimate: clone(WORKED) }), labor: [] });
    await deleted.api.init();
    deleted.api.go(1);

    // A v1 draft off staging: its crew lives under `labour`, so it has no `labor` key for a
    // reason that has nothing to do with the estimator not having worked on it.
    const v1 = build({ blob: blob({ polish_estimate: {
      areas: [{ name: "Main sales floor", sf: 9000 }],
      labour: { polishing: { crew: 4, days: 6, rate: 32.2 } },
      conditions: { local: false } } }), labor: LIB });
    await v1.api.init();
    v1.api.go(1);

    // PRODUCTION TODAY: the table is not there, so the read cannot answer.
    const down = build({ blob: (() => { const b = blob(); delete b.polish_estimate; return b; })(),
                         labor: LIB, laborFails: true });
    await down.api.init();
    down.api.go(1);

    // …and the same read answering with something that is not a list of rows.
    const notRows = build({ blob: (() => { const b = blob(); delete b.polish_estimate; return b; })(),
                            laborBody: { ok: false, error: "relation library_labor does not exist" } });
    await notRows.api.init();
    notRows.api.go(1);

    out.laborDefaults = {
      brandNew: {
        ids: ids(brandNew),
        onScreen: onScreen(brandNew),
        rates: brandNew.api.model().labor.map((r) => r.rate),
        // Nothing an estimator has to judge is filled in for them.
        guys: brandNew.api.model().labor.map((r) => r.guys),
        days: brandNew.api.model().labor.map((r) => r.days),
        // A default carrying guys_auto is filled from the man-day sum before the first paint,
        // exactly as Travel is -- 4×6 polishing days is not the point, the point is that it is
        // the same figure Travel got rather than a blank.
        autoGuys: brandNew.api.model().labor
          .filter((r) => r.id === "lab-night").map((r) => r.guys),
        travelGuys: brandNew.api.model().labor
          .filter((r) => r.id === "travel").map((r) => r.guys),
        // A default must not quietly put money on the bid.
        laborTotal: B.laborTotal(brandNew.api.model().labor),
        builtInTotal: B.laborTotal(B.freshModel().labor),
        costCells: brandNew.doc.querySelectorAll("[data-lcost-for]").length,
        // What the page says is stopping this bid being priced. A default arrives with its rate
        // and no quantity, so a `days` line has two empty boxes and blockers() reads it the way
        // it reads Polishing and Joint filler off Kyle's own sheet -- named, in words, not
        // silently blocking and not silently priced at nothing.
        blockers: B.blockers(brandNew.api.model()),
        fetches: brandNew.rec.fetches,
        mainShown: brandNew.dom.get("main").hidden === false,
      },
      fromIntake: { ids: ids(fromIntake), onScreen: onScreen(fromIntake),
                    fetched: fromIntake.rec.fetches.some((u) => /\/labor/.test(u)) },
      worked: {
        saved: WORKED.labor,
        after: worked.api.model().labor,
        onScreen: onScreen(worked),
        // THE PROOF THAT THE GATE RAN AT ALL: a saved bid never even asks for the defaults.
        fetches: worked.rec.fetches,
        // …and NOT VACUOUS: those two library rows exist and one of them is missing from this
        // bid, so there was something for the gate to keep out.
        wouldHaveAdded: B.seedLibraryLabor(WORKED.labor, LIB).map((r) => r.id),
      },
      // A default deleted from the library is still on the bid that was holding it.
      deleted: { ids: ids(deleted), onScreen: onScreen(deleted),
                 densifyRate: deleted.api.model().labor
                   .filter((r) => r.id === "lab-densify").map((r) => r.rate) },
      v1: { ids: ids(v1), fetched: v1.rec.fetches.some((u) => /\/labor/.test(u)) },
      // Never a blank Labor step. Travel is there, the page is open, and nothing says anything is
      // wrong -- a default nobody has defined yet is not an error to report to an estimator.
      down: { ids: ids(down), onScreen: onScreen(down),
              mainShown: down.dom.get("main").hidden === false,
              loadingHidden: down.dom.get("loading").hidden,
              alert: down.dom.get("alert").textContent,
              costCells: down.doc.querySelectorAll("[data-lcost-for]").length },
      notRows: { ids: ids(notRows), mainShown: notRows.dom.get("main").hidden === false,
                 alert: notRows.dom.get("alert").textContent },
    };
  }


  // ── the Takeoff condition defaults, at the page level ──────────────────────
  //
  // The three conditions stopped being "built in" on 2026-09-18. What is proved here is the half
  // the shared module cannot prove on its own: which blobs this PAGE decides to seed.
  {
    // Every stored answer disagrees with what the tool ships. All three ship OFF from
    // 2026-09-19, so all three rows say on. A fixture that agreed with freshModel could not tell
    // a seeder that works from one that was never wired up.
    const COND = [{ key: "joint_filler", on: true },
                  { key: "dye", on: true },
                  { key: "remove_existing_jf", on: true }];
    const conds = (built) => built.api.model().conditions;

    // A brand-new project: no polish_estimate on the draft at all. This is the sidebar door and a
    // project that reached this page without going through the beta intake.
    const noKey = blob();
    delete noKey.polish_estimate;
    const brandNew = build({ blob: noKey, conditionDefaults: COND });
    await brandNew.api.init();
    // THE SAME BRAND-NEW PROJECT WITH ALL THREE RESERVED ROWS IN THE LIBRARY. 2026-10-01 made
    // remove-existing a library row beside dye and the kit (Hanz: "All 3 exactly like
    // materials"); the rows are materials an admin edits, and they must change neither which
    // conditions a new estimate opens with nor what it comes to. The seed is the I2 block's own,
    // which test_polish_estimate_page.py pins to both schema files.
    const noKeyRows = blob();
    delete noKeyRows.polish_estimate;
    const brandNewRows = build({ blob: noKeyRows, conditionDefaults: COND,
                                 items: ITEMS.concat(out.reservedItems.seed) });
    await brandNewRows.api.init();

    // AN ESTIMATOR'S OWN ANSWERS, every one of them the opposite of the stored default, so the
    // library has something that COULD have landed here and the gate is the only thing stopping
    // it. joint_filler's direction reversed on 2026-09-19: it now SHIPS off, so the bid at risk
    // is one where somebody deliberately turned it ON, and a careless default would take the
    // $500-a-kit line back out with the workbook saying No in Polish!E29.
    const WORKED = {
      version: 2,
      takeoff: clone(MODEL.takeoff),
      labor: clone(MODEL.labor),
      conditions: Object.assign({}, MODEL.conditions,
        { joint_filler: false, dye: false, remove_existing_jf: false }),
      contingency: 0, fees: 0, totals: {},
    };
    const worked = build({ blob: blob({ polish_estimate: clone(WORKED) }),
                           conditionDefaults: COND });
    await worked.api.init();

    // THE CELL STILL WINS. A project off the live intake has no polish_estimate and its answers
    // sit in cell_values — seeding last would put a company default over the answer the estimator
    // already gave, and the next save would make that permanent in Kyle's workbook.
    //
    // ALL THREE CELLS, not one -- exactly what a real step-1 save on the live intake screen
    // leaves behind, and each one the OPPOSITE of what COND above says. A fixture that answered
    // only one of the three could pass against a page that seeds the other two from the admin
    // default regardless of what their cells said.
    //
    // AND A NARROWED LIST FOR THIS ONE CASE, which is the part that has to be right rather than
    // tidy. Since all three ship OFF, a library row saying "on" against a cell saying "No"
    // leaves false -- and false is ALSO what a page that read neither would show, so that
    // pairing on its own cannot prove the cell was read at all. Two of the three are that
    // pairing (they prove the cell BEATS the default); remove_existing_jf is deliberately left
    // OUT of the list with its cell saying Yes, so `true` there can only have come from the
    // cell. Between them the two shapes pin both halves of "the cell wins".
    const COND_FOR_CELLS = [{ key: "joint_filler", on: true }, { key: "dye", on: true }];
    const fromCells = (() => { const b = blob(); delete b.polish_estimate;
                               b.cell_values = { "Polish!E29": "No", "Polish!E25": "No",
                                                 "Polish!F29": "Yes" };
                               return b; })();
    const celled = build({ blob: fromCells, conditionDefaults: COND_FOR_CELLS });
    await celled.api.init();

    // PRODUCTION TODAY: the table is not there, so the read cannot answer.
    const down = build({ blob: (() => { const b = blob();
                                        delete b.polish_estimate; return b; })(),
                         conditionFetchFails: true });
    await down.api.init();

    out.conditionDefaults = {
      brandNew: { conditions: conds(brandNew),
                  fetched: brandNew.rec.fetches.some((u) => /condition-defaults/.test(u)) },
      brandNewWithRows: { conditions: conds(brandNewRows), total: brandNewRows.api.bid().total,
                          totalWithoutRows: brandNew.api.bid().total },
      // THE PROOF THAT THE GATE RAN AT ALL: a saved bid never even asks for the defaults.
      worked: { saved: WORKED.conditions, after: conds(worked),
                fetched: worked.rec.fetches.some((u) => /condition-defaults/.test(u)),
                // …and NOT VACUOUS: the same rows applied to the same model move all three.
                wouldHaveChanged: B.seedConditionDefaults(conds(worked), COND) },
      celled: { dye: conds(celled).dye, jointFiller: conds(celled).joint_filler,
                removeExistingJf: conds(celled).remove_existing_jf,
                fetched: celled.rec.fetches.some((u) => /condition-defaults/.test(u)) },
      // Never a blank step and never a word about it: a default nobody has defined yet is not an
      // error to report to an estimator.
      down: { conditions: conds(down), shipped: B.freshModel().conditions,
              mainShown: down.dom.get("main").hidden === false,
              alert: down.dom.get("alert").textContent },
    };
  }

  // ── GRAYED UNTIL ON, AND ONLY WHAT THE DEFAULTS TAB LISTS ────────────────────────────────
  // Hanz, 2026-10-01: "Everything that is in the defaults and labor tab in the Items and
  // Assemblies appear as grayed out options that can be enabled or not." Read off the RENDERED
  // Takeoff panel: each card's opening tag, or null when the card is not drawn at all.
  {
    const g = build();
    const panel = () => g.dom.get("panels").innerHTML;
    const opening = (tag) => {
      const h = panel();
      const i = h.indexOf(">" + tag + "<");
      if (i < 0) return null;
      const s0 = h.lastIndexOf('<div class="tk ', i);
      return h.slice(s0, h.indexOf(">", s0) + 1);
    };
    const M = g.api.model();
    M.conditions.joint_filler = false; M.conditions.dye = false;
    M.conditions.remove_existing_jf = false;
    g.api.go(0);
    const allOff = [opening("JOINT FILLER"), opening("DYE"), opening("REMOVE EXISTING")];
    M.conditions.dye = true; g.api.go(0);
    const dyeOn = opening("DYE");
    // REMOVE EXISTING GRAYED FOR ITS OWN REASON: joint filler ON (so `needs` cannot be what dims
    // it), remove-existing off.
    M.conditions.joint_filler = true; M.conditions.remove_existing_jf = false; g.api.go(0);
    const remOffJfOn = opening("REMOVE EXISTING");
    M.conditions.remove_existing_jf = true; g.api.go(0);
    const remOn = opening("REMOVE EXISTING");
    M.conditions.dye = false; M.conditions_shown = { dye: false }; g.api.go(0);
    const dyeHidden = opening("DYE");
    const othersStill = !!opening("JOINT FILLER") && !!opening("REMOVE EXISTING");
    M.conditions.dye = true; g.api.go(0);
    const hiddenButOn = opening("DYE");
    // SWITCHED OFF BY HAND, through the page's own click handler: the card stays.
    g.doc.fire("click", { target: switchNode("dye") });
    const touchedOff = { on: g.api.model().conditions.dye, card: opening("DYE") };
    // JOINT FILLER OFF THE LIST AND OFF: remove-existing (off) is not drawn either.
    M.conditions.joint_filler = false; M.conditions.remove_existing_jf = false;
    M.conditions_shown = { joint_filler: false }; g.api.go(0);
    const needsHidden = { jf: opening("JOINT FILLER"), rem: opening("REMOVE EXISTING") };
    M.conditions.remove_existing_jf = true; g.api.go(0);
    const needsHiddenButOn = opening("REMOVE EXISTING");

    // THE SNAPSHOT, through the real init(): a brand-new bid takes the Defaults tab's answer; a
    // bid somebody already saved does not, whatever the Defaults tab says now.
    const LISTED = [{ key: "dye", on: false, listed: false }];
    const nb = blob(); delete nb.polish_estimate;
    const fresh = build({ blob: nb, conditionDefaults: LISTED });
    await fresh.api.init();
    fresh.api.go(0);
    const savedBid = { version: 2, takeoff: clone(MODEL.takeoff), labor: clone(MODEL.labor),
                       conditions: Object.assign({}, MODEL.conditions, { dye: false }),
                       contingency: 0, fees: 0, totals: {} };
    const old = build({ blob: blob({ polish_estimate: clone(savedBid) }),
                        conditionDefaults: LISTED });
    await old.api.init();
    old.api.go(0);
    const freshPanel = fresh.dom.get("panels").innerHTML;
    const oldPanel = old.dom.get("panels").innerHTML;

    out.grayedUntilOn = {
      allOffGrayed: allOff.every((t) => !!t && / inert"/.test(t)),
      dyeOnNotGrayed: !!dyeOn && !/inert/.test(dyeOn),
      removeExistingOnNotGrayed: !!remOn && !/inert/.test(remOn),
      removeExistingOffGrayedOnItsOwn: !!remOffJfOn && / inert"/.test(remOffJfOn),
      touchedCardStays: touchedOff.on === false && !!touchedOff.card && / inert"/.test(touchedOff.card),
      removeExistingFollowsJointFiller: needsHidden.jf === null && needsHidden.rem === null &&
        !!needsHiddenButOn,
      dyeHiddenWhenOffTheList: dyeHidden === null && othersStill,
      onAlwaysShows: !!hiddenButOn && !/inert/.test(hiddenButOn),
      freshSnapshot: fresh.api.model().conditions_shown || null,
      freshHidesDye: freshPanel.indexOf(">DYE<") === -1 && freshPanel.indexOf(">JOINT FILLER<") !== -1,
      savedBidKeepsAll: oldPanel.indexOf(">DYE<") !== -1 && !old.api.model().conditions_shown,
      migrated: B.migrateModel({ version: 2, takeoff: [], labor: [], conditions: {},
        conditions_shown: { dye: false, joint_filler: true, bogus: false } }).conditions_shown,
      noMapStaysNoMap: !("conditions_shown" in B.migrateModel(clone(savedBid))),
      // THE COMMON STORED ROW IS `{ on: false }` WITH NO `listed` -- what every row written before
      // the column looks like. OFF IS NOT UNLISTED: it must not land in the map.
      seeded: B.seedConditionsShown([{ key: "dye", listed: false }, { key: "joint_filler", listed: true },
        { key: "remove_existing_jf", on: false }, { key: "bogus", listed: false }]),
    };
  }

  // ── M. the company labor rate (Markups -> Global) ───────────────────────────
  {
    const RATE = (formula, extra) => [Object.assign({ id: "mk1", layout: "global",
      line_key: "labor_rate", formula: formula, applies: true }, extra || {})];
    const fresh = () => { const bb = blob(); delete bb.polish_estimate; return bb; };
    const LIBM = [
      { id: "travel", name: "Travel", rate: "33.00", unit: "hours", guys_auto: true, favorite: true },
      { id: "lab-none", name: "No own rate", rate: 0, unit: "hours", guys_auto: false, favorite: true },
      { id: "lab-own", name: "Own rate", rate: "55.00", unit: "days", guys_auto: false, favorite: true },
    ];
    const rates = (built) => {
      const o = {};
      built.api.model().labor.forEach((r) => { o[r.id] = r.rate; });
      return o;
    };
    const flt = (built) => built.doc.querySelectorAll("[data-ratedflt-for]")
      .map((el) => ({ text: el.textContent, hidden: !!el.hidden }));

    const newBid = build({ blob: fresh(), labor: LIBM, markupRules: RATE("40") });
    await newBid.api.init();
    newBid.api.go(1);
    const noRule = build({ blob: fresh(), labor: LIBM });
    await noRule.api.init();
    const down = build({ blob: fresh(), labor: LIBM, markupFails: true });
    await down.api.init();
    const off = build({ blob: fresh(), labor: LIBM, markupRules: RATE("40", { applies: false }) });
    await off.api.init();

    const SAVED = { version: 2, takeoff: clone(MODEL.takeoff),
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
              { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 36 }],
      conditions: clone(MODEL.conditions), contingency: 0, fees: 0, totals: {} };
    const saved = build({ blob: blob({ polish_estimate: clone(SAVED) }), labor: LIBM,
                          markupRules: RATE("40") });
    await saved.api.init();
    saved.api.go(1);

    // Typing the default back hides the line; typing anything else shows it. Driven through the
    // page's own input handler so the in-place repaint is the code under test.
    newBid.api.go(1);
    const before = flt(newBid);
    const newBidRates = rates(newBid);
    typeInto(newBid, '[data-lab="0"][data-k="rate"]', "45");
    const typedOver = flt(newBid)[0];
    typeInto(newBid, '[data-lab="0"][data-k="rate"]', "40");
    const typedBack = flt(newBid)[0];
    const added = newBid.api.newLaborRow();

    // G1: Travel Labor with its OWN library rate ($41) on a $40 company rate -- nothing typed, so
    // no row (Travel included) may warn; typing over it warns against $41, not $40.
    const LIBT = [{ id: "travel", name: "Travel", rate: "41.00", unit: "hours", guys_auto: true,
                    favorite: true }];
    const tb = build({ blob: fresh(), labor: LIBT, markupRules: RATE("40") });
    await tb.api.init();
    tb.api.go(1);
    const ti = tb.api.model().labor.findIndex((r) => r.id === "travel");
    const travelOwn = { rate: tb.api.model().labor[ti].rate, lines: flt(tb) };
    typeInto(tb, '[data-lab="' + ti + '"][data-k="rate"]', "50");
    travelOwn.typedOver = flt(tb)[flt(tb).length - 1];

    out.laborRate = {
      travelOwn: travelOwn,
      newBid: newBidRates, noRule: rates(noRule), down: rates(down), off: rates(off),
      saved: rates(saved), savedDefaultLines: flt(saved),
      newBidLines: before, typedOver: typedOver, typedBack: typedBack,
      addedRate: added.rate,
      fetchedMarkup: newBid.rec.fetches.some((u) => /api\/markup\/rules/.test(u)),
      savedFetchedLaborDefaults: saved.rec.fetches.some((u) => /\/labor/.test(u)),
      parsed: [B.laborRateFromRules(RATE("33.50")), B.laborRateFromRules(RATE("$41")),
               B.laborRateFromRules(RATE("IF(1,2,3)")), B.laborRateFromRules(RATE("0")),
               B.laborRateFromRules([]), B.laborRateFromRules(null),
               B.laborRateFromRules([{ layout: "polish", line_key: "labor_rate", formula: "50",
                                      applies: true }])],
    };
  }

  {
    // THE ON/OFF SLIDER (Kyle, 2026-10-05), EXECUTED THROUGH THE PAGE'S OWN HANDLERS. A switched-off
    // row stays on screen, grayed, and adds $0 -- skipped in the RAW sums, before the chain rounds
    // -- so the proof is that the whole bid equals the bid of a model that never had the row.
    const clickSw = (built, sel) => clickEl(built, need(built, sel));
    const totalOf = (built) => built.api.bid().total;
    const without = (mut) => {
      const m = clone(MODEL); mut(m);
      return build({ blob: blob({ polish_estimate: m }) });
    };

    const base = build();
    await base.api.init();
    base.api.go(0);
    const total0 = totalOf(base), mat0 = base.api.materialTotal();
    const costBoxBefore = txt(base, '[data-cost-for="0"]');
    clickSw(base, '[data-on-tk="0"]');
    const tkOff = base.api.model().takeoff[0];
    const afterTkOff = {
      enabled: tkOff.enabled,
      costBox: txt(base, '[data-cost-for="0"]'),
      cardClass: need(base, '[data-row-card="0"]').className,
      switchOn: need(base, '[data-on-tk="0"]').getAttribute("aria-checked"),
      material: base.api.materialTotal(), total: totalOf(base),
      area: B.takeoffSf(base.api.model().takeoff),
    };
    const tkGone = without((m) => m.takeoff.splice(0, 1));
    await tkGone.api.init();
    const expectTkOff = { material: tkGone.api.materialTotal(), total: totalOf(tkGone),
                          area: B.takeoffSf(tkGone.api.model().takeoff) };
    clickSw(base, '[data-on-tk="0"]');
    const tkBack = { hasEnabledKey: "enabled" in base.api.model().takeoff[0],
                     total: totalOf(base), material: base.api.materialTotal() };

    // LABOR: Polishing off. The bid must equal the bid of a model that never had the row.
    const lab = build();
    await lab.api.init();
    lab.api.go(1);
    const lab0 = totalOf(lab);
    clickSw(lab, '[data-on-lab="0"]');
    const labOff = {
      enabled: lab.api.model().labor[0].enabled,
      cardClass: need(lab, '[data-lab-card="0"]').className,
      cost: txt(lab, '[data-lcost-for="0"]'),
      laborTotalText: txt(lab, "[data-labor-total]"),
      total: totalOf(lab),
    };
    const labGone = without((m) => m.labor.splice(0, 1));
    await labGone.api.init();
    const expectLabOff = { total: totalOf(labGone) };
    clickSw(lab, '[data-on-lab="0"]');
    const labBack = { hasEnabledKey: "enabled" in lab.api.model().labor[0], total: totalOf(lab) };

    // THE REVIEW LIST leaves off rows out, and the step pip / blockers do not count them.
    const rev = build();
    await rev.api.init();
    rev.api.go(0); clickSw(rev, '[data-on-tk="0"]');
    rev.api.go(1); clickSw(rev, '[data-on-lab="0"]');
    rev.api.go(2);
    const revHtml = rev.api.reviewPanel();

    // AN OFF CREW ROW DROPS OUT OF TRAVEL'S GUYS (man-days): polishing 3x5 + mock-up 3x0.5 = 16.5.
    const trv = build({ blob: blob({ polish_estimate: Object.assign(clone(MODEL), {
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
              { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
              { id: "travel", label: "Travel", guys: "", days: 2, rate: 33,
                unit: "hours", guys_auto: true }] }) }) });
    await trv.api.init();
    trv.api.go(1);
    const guysBefore = trv.api.model().labor[2].guys;
    clickSw(trv, '[data-on-lab="0"]');
    const guysAfter = trv.api.model().labor[2].guys;

    // THE KEYBOARD: Space on the slider flips it like a press.
    const kb = build();
    await kb.api.init();
    kb.api.go(0);
    const swEl = need(kb, '[data-on-tk="1"]');
    swEl.click = function () { kb.doc.fire("click", { target: swEl, preventDefault() {} }); };
    let prevented = false;
    kb.doc.fire("keydown", { target: swEl, key: " ", preventDefault() { prevented = true; } });
    const kbOff = kb.api.model().takeoff[1].enabled;
    kb.doc.fire("keydown", { target: swEl, key: "a", preventDefault() {} });
    const kbOtherKey = kb.api.model().takeoff[1].enabled;

    // A CONDITION CARD'S SWITCH is the same component (class, role, aria), not a lookalike.
    const cardSw = need(base, '[data-cond="dye"]');

    out.rowSlider = {
      total0: total0, mat0: mat0, costBoxBefore: costBoxBefore,
      afterTkOff: afterTkOff, expectTkOff: expectTkOff, tkBack: tkBack,
      lab0: lab0, labOff: labOff, expectLabOff: expectLabOff, labBack: labBack,
      reviewHasOffTakeoff: revHtml.indexOf("Polish 800 Grit") !== -1,
      reviewHasOnTakeoff: revHtml.indexOf("Cove Base") !== -1,
      reviewHasOffLabor: revHtml.indexOf("Polishing") !== -1,
      reviewHasOnLabor: revHtml.indexOf("Mock-up") !== -1,
      guysBefore: guysBefore, guysAfter: guysAfter,
      kbOff: kbOff, kbPrevented: prevented, kbOtherKey: kbOtherKey,
      condSwitchClass: cardSw.className, condSwitchRole: cardSw.getAttribute("role"),
      offSwitchSameShape: need(base, '[data-on-tk="1"]').className.indexOf("mw-sw") === 0 &&
        need(base, '[data-on-tk="1"]').getAttribute("role") === "switch",
    };
  }

  // ── N. Lodging and Per Diem, beside Travel Labor (Kyle's notes, B7, 2026-10-05) ─────────────────
  // EXECUTED THROUGH THE PAGE'S OWN HANDLERS: the Labor step draws a dividing line, then Travel
  // Labor, Lodging and Per Diem; each has its own slider and a typeable quantity; they price INSIDE
  // the markups (the bid moves by more than the travel dollars); a switched-off line adds nothing
  // and stays out of Review; a NEW bid copies the two rates from Markups -> Global and a saved bid
  // keeps its own.
  {
    const RULES = [
      { id: "m1", layout: "global", line_key: "travel_lodging", formula: "80", applies: true },
      { id: "m2", layout: "global", line_key: "travel_per_diem", formula: "50", applies: true },
    ];
    // An OLD draft: saved before `travel` existed, with Travel still labelled "Travel".
    const OLD = {
      version: 2, takeoff: clone(MODEL.takeoff),
      labor: [
        { id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
        { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
        { id: "travel", label: "Travel", guys: "", days: "", rate: 33, unit: "hours",
          guys_auto: true },
      ],
      conditions: Object.assign(clone(MODEL.conditions), { local: false }),
      contingency: 0, fees: 0, totals: {},
    };
    const old = build({ blob: blob({ polish_estimate: clone(OLD) }), markupRules: RULES });
    await old.api.init();
    old.api.go(1);
    const html0 = old.dom.get("panels").innerHTML;
    const at = (needle) => html0.indexOf(needle);
    const base = old.api.bid();

    // Lodging ON.
    clickOn(old, '[data-on-trv="lodging"]');
    const lodgingOn = old.api.bid();
    const lodgingModel = clone(old.api.model().travel.lodging);
    const costCellOn = txt(old, '[data-trvcost-for="lodging"]');
    const qtyAuto = need(old, '[data-trv="lodging"][data-k="qty"]').value;

    // Type a quantity of our own: leaves auto, prices on the typed number.
    typeInto(old, '[data-trv="lodging"][data-k="qty"]', "10");
    const typedLodging = clone(old.api.model().travel.lodging);
    const typedBid = old.api.bid();
    const typedCostCell = txt(old, '[data-trvcost-for="lodging"]');
    // And back to auto by CLEARING the box (the "Type my own" switch is gone). An empty box on
    // input stays typed; the change commits it.
    typeInto(old, '[data-trv="lodging"][data-k="qty"]', "");
    const midClearLodging = clone(old.api.model().travel.lodging);
    const lodgeWrites = old.dom.get("panels").htmlWrites;
    changeTo(old, '[data-trv="lodging"][data-k="qty"]', "");
    const lodgeClearRebuilds = old.dom.get("panels").htmlWrites - lodgeWrites;
    const backToAuto = clone(old.api.model().travel.lodging);
    const clearedLodgingBox = need(old, '[data-trv="lodging"][data-k="qty"]').value;
    const clearedLodgingCost = txt(old, '[data-trvcost-for="lodging"]');
    const lodgingHtml = old.dom.get("panels").innerHTML;
    const lodgingHints = {
      auto: need(old, '[data-hint-trv="lodging"]').textContent === "Man-days from the tasks above.",
      noTypeMyOwn: lodgingHtml.indexOf("Type my own") === -1 &&
        lodgingHtml.indexOf("data-trv-manual") === -1 && lodgingHtml.indexOf("data-trv-auto") === -1,
    };
    typeInto(old, '[data-trv="lodging"][data-k="qty"]', "10");
    const typedHintLodging = old.dom.get("panels").innerHTML
      .indexOf("Typed by you. Clear it to use the man-days from the tasks above.") !== -1;
    changeTo(old, '[data-trv="lodging"][data-k="qty"]', "");

    // Per Diem ON as well, rate typed over.
    clickOn(old, '[data-on-trv="per_diem"]');
    typeInto(old, '[data-trv="per_diem"][data-k="rate"]', "60");
    const bothOn = old.api.bid();
    const review = (() => { old.api.go(2); return old.dom.get("panels").innerHTML; })();
    const saved = (() => { old.clock.fire(); return old.rec.saves[old.rec.saves.length - 1]; })();

    // Per Diem OFF again: gone from Review, adds nothing.
    old.api.go(1);
    clickOn(old, '[data-on-trv="per_diem"]');
    const perDiemOff = old.api.bid();
    old.api.go(2);
    const reviewOff = old.dom.get("panels").innerHTML;

    // A NEW bid (no saved estimate at all) copies the two rates; a fresh bid has both OFF.
    const fb = blob(); delete fb.polish_estimate;
    const fresh = build({ blob: fb, markupRules: RULES });
    await fresh.api.init();
    // The markup read failing leaves the shipped 70 / 45.
    const down = build({ blob: (() => { const b2 = blob(); delete b2.polish_estimate; return b2; })(),
                         markupFails: true });
    await down.api.init();

    // A LOCAL job (under 70 miles) leaves the three lines gray until touched.
    const loc = build({ blob: blob({ polish_estimate: Object.assign(clone(OLD), {
      conditions: Object.assign(clone(MODEL.conditions), { local: true }) }) }) });
    await loc.api.init();
    loc.api.go(1);
    const localClass0 = need(loc, '[data-trv-card="lodging"]').className;
    clickOn(loc, '[data-on-trv="lodging"]');
    const localClassOn = need(loc, '[data-trv-card="lodging"]').className;
    const localHand = loc.api.model().travel.lodging.hand === true;

    // HOTEL AND PER DIEM, the Review card (Hanz, 2026-10-06): always there, after Labor, before the
    // markup block. Each state is a fresh page opened on Review.
    const reviewOf = async (travelEdit) => {
      const o = clone(OLD);
      if (travelEdit) {
        const t = clone(old.api.model().travel);
        travelEdit(t);
        o.travel = t;
      }
      const x = build({ blob: blob({ polish_estimate: o }), markupRules: RULES });
      await x.api.init();
      x.api.go(2);
      return { html: x.dom.get("panels").innerHTML, bid: x.api.bid(), x: x };
    };
    const cardBody = (html) => {
      const s = html.indexOf('rev-h">Hotel and Per Diem');
      if (s === -1) return "";
      const e = html.indexOf('class="rev"', s);
      return html.slice(s, e === -1 ? html.length : e);
    };
    const hotelOff = await reviewOf(null);
    const hotelOne = await reviewOf((t) => { t.lodging.enabled = true; });
    const hotelBoth = await reviewOf((t) => { t.lodging.enabled = true; t.per_diem.enabled = true; });
    const hotelRenamed = await reviewOf((t) => { t.lodging.enabled = true; t.lodging.label = "Motel"; });
    const hotelShape = (r) => {
      const h = r.html;
      const body = cardBody(h);
      return {
        count: (h.match(/rev-h">Hotel and Per Diem/g) || []).length,
        body: body,
        header: (body.match(/<span class="amt">([^<]*)<\/span>/) || [])[1] || null,
        total: (body.match(/Hotel and Per Diem Total<\/td><td class="r"><\/td><td class="r"><span data-mk="travel">([^<]*)</) || [])[1] || null,
        travel: r.bid.travel,
        labor: h.indexOf('rev-h">Labor'), card: h.indexOf('rev-h">Hotel and Per Diem'),
        subtotal: h.indexOf("<td>Subtotal</td>"),
      };
    };

    out.hotelCard = {
      off: hotelShape(hotelOff), one: hotelShape(hotelOne),
      both: hotelShape(hotelBoth), renamed: hotelShape(hotelRenamed),
      oldTitleAnywhere: [hotelOff, hotelOne, hotelBoth].some((r) => r.html.indexOf("Lodging and Per Diem") !== -1),
    };

    out.travelCosts = {
      // layout
      order: { sep: at('class="trvsep"'), travelLabor: at('data-lab-card="2"'),
               lodging: at('data-trv-card="lodging"'), perDiem: at('data-trv-card="per_diem"'),
               addLine: at("data-add-lab") },
      travelLaborLabel: old.api.model().labor[2].label,
      cardClassOff: /class="tk trv inert off" data-trv-card="lodging"/.test(html0),
      noteOnEach: (html0.match(/70 miles or more from the office/g) || []).length,
      // money
      baseTravel: base.travel, baseTotal: base.total, baseSub: base.sub_total,
      lodgingOnTravel: lodgingOn.travel, lodgingOnSub: lodgingOn.sub_total,
      lodgingOnTotal: lodgingOn.total, lodgingOnGp: lodgingOn.gp,
      oldRate: lodgingModel.rate, lodgingModel: lodgingModel,
      costCellOn: costCellOn, qtyAuto: qtyAuto,
      typedLodging: typedLodging, typedTravel: typedBid.travel, typedCostCell: typedCostCell,
      backToAuto: backToAuto, midClearLodging: midClearLodging,
      clearedLodgingBox: clearedLodgingBox, lodgeClearRebuilds: lodgeClearRebuilds, clearedLodgingCost: clearedLodgingCost,
      lodgingHints: lodgingHints, typedHintLodging: typedHintLodging,
      bothOnTravel: bothOn.travel, perDiemOffTravel: perDiemOff.travel,
      perDiemOffTotal: perDiemOff.total, lodgingOnlyTotal: null,
      // review
      reviewHasCard: review.indexOf("Hotel and Per Diem") !== -1,
      reviewHasLodging: review.indexOf(">Hotel<") !== -1,
      reviewHasPerDiem: review.indexOf(">Per Diem<") !== -1,
      reviewOffHasPerDiem: reviewOff.indexOf(">Per Diem<") !== -1,
      reviewOffHasLodging: reviewOff.indexOf(">Hotel<") !== -1,
      // saving
      savedTravel: saved && saved.polish_estimate ? saved.polish_estimate.travel : null,
      // rates
      freshRates: { lodging: fresh.api.model().travel.lodging.rate,
                    per_diem: fresh.api.model().travel.per_diem.rate },
      freshEnabled: [fresh.api.model().travel.lodging.enabled, fresh.api.model().travel.per_diem.enabled],
      downRates: { lodging: down.api.model().travel.lodging.rate,
                   per_diem: down.api.model().travel.per_diem.rate },
      oldRates: { lodging: old.api.model().travel.lodging.rate,
                  per_diem: old.api.model().travel.per_diem.rate },
      // local gate
      localClass0: localClass0, localClassOn: localClassOn, localHand: localHand,
    };
  }

  // ── O. DISTANCE DECIDES "LOCAL" (Kyle 9/18; Hanz, 2026-10-05) ─────────────────────────────────
  // EXECUTED THROUGH THE PAGE: init() asks the server for the driving miles AFTER the first paint,
  // and the answer sets the hidden `conditions.local` (still written to Polish!B4), the three
  // travel lines and the "N mi from Olathe office" note. Unknown never guesses; a typed figure
  // always wins; a line flipped by hand is never moved; a slow Google never holds the page.
  {
    const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };
    const ADDRESS = { address: "100 Main St", city: "Wichita", state: "KS", zip: "67202" };
    const newBlob = () => { const b = blob(ADDRESS); delete b.polish_estimate; return b; };
    const snap = (x) => {
      const m = x.api.model();
      const li = m.labor.findIndex((r) => r.id === "travel");
      return {
        distance: m.distance === undefined ? null : clone(m.distance),
        local: m.conditions.local,
        lodging: m.travel.lodging.enabled, perDiem: m.travel.per_diem.enabled,
        lodgingHand: m.travel.lodging.hand === true,
        note: txt(x, "[data-dist-note]"), status: txt(x, "[data-dist-status]"),
        // The "how this is worked out" note, and the figures the bid itself prices these lines at
        // (the same B functions the totals use), so a test can hold the note to them.
        how: txt(x, "[data-trv-how]"),
        cost: { lodging: B.travelLineCost(m.travel.lodging, m.labor),
                per_diem: B.travelLineCost(m.travel.per_diem, m.labor),
                travel: B.laborCost(m.labor[li]) },
        lodgingGray: /inert/.test(need(x, '[data-trv-card="lodging"]').className),
        travelLaborGray: /inert/.test(need(x, '[data-lab-card="' + li + '"]').className),
      };
    };

    // FAR: 120.4 miles. The three lines come on; Polish!B4 is written "No" from the hidden answer.
    const far = build({ blob: newBlob(), distance: { ok: true, miles: 120.4, reason: "" } });
    await far.api.init(); far.api.go(1); await settle();
    const farSnap = snap(far);
    far.clock.fire();
    const farSaved = far.rec.saves[far.rec.saves.length - 1];
    far.api.go(2);
    const farReview = far.dom.get("panels").innerHTML;

    // NEAR: 30 miles. Local; all three stay gray; B4 "Yes".
    const near = build({ blob: newBlob(), distance: { ok: true, miles: 30, reason: "" } });
    await near.api.init(); near.api.go(1); await settle();
    const nearSnap = snap(near);
    near.clock.fire();
    const nearSaved = near.rec.saves[near.rec.saves.length - 1];

    // EXACTLY 70 is far (70 or more).
    const seventy = build({ blob: newBlob(), distance: { ok: true, miles: 70, reason: "" } });
    await seventy.api.init(); await settle();
    const seventySnap = { local: seventy.api.model().conditions.local,
                          lodging: seventy.api.model().travel.lodging.enabled };

    // UNKNOWN (no key): nothing guessed, the page still opens, and typing miles takes over.
    const unk = build({ blob: newBlob(), distance: { ok: false, miles: null, reason: "no_key" } });
    await unk.api.init(); unk.api.go(1); await settle();
    const unkSnap = snap(unk);
    typeInto(unk, "[data-dist-miles]", "85");
    const typed85 = snap(unk);
    // A hand flip on Lodging, then the miles move around: the line the estimator flipped stays.
    clickOn(unk, '[data-on-trv="lodging"]');                 // on -> OFF, by hand
    typeInto(unk, "[data-dist-miles]", "20");
    const typed20 = snap(unk);
    typeInto(unk, "[data-dist-miles]", "90");
    const typed90 = snap(unk);
    // Clearing the box goes back to unknown: Per Diem (never touched) goes gray again.
    typeInto(unk, "[data-dist-miles]", "");
    await settle();
    const cleared = snap(unk);
    // A DECIMAL TYPED KEY BY KEY. The panel rebuilds on every miles keystroke, so the box must come
    // back showing what was typed ("12." stays "12.", not "12"), or "12.5" lands as 125.
    typeInto(unk, "[data-dist-miles]", "12.");
    const dotBox = need(unk, "[data-dist-miles]").value;
    typeInto(unk, "[data-dist-miles]", "12.5");
    const decimal = { dotBox: dotBox, box: need(unk, "[data-dist-miles]").value, snap: snap(unk) };

    // THE NETWORK FAILING is the same answer as unknown, with a reason shown.
    const down = build({ blob: newBlob(), distanceFails: true });
    await down.api.init(); down.api.go(1); await settle();
    const downSnap = snap(down);

    // A SLOW GOOGLE never holds the page: init() resolves while the answer is still pending, the
    // Labor step renders, and a figure typed in the meantime wins when the answer finally lands.
    let release;
    const gate = new Promise((r) => { release = r; });
    const slow = build({ blob: newBlob(), distance: { ok: true, miles: 200, reason: "" },
                         distanceGate: gate });
    await slow.api.init(); slow.api.go(1);
    const slowBusy = snap(slow);
    typeInto(slow, "[data-dist-miles]", "10");
    release(); await settle();
    const slowAfter = snap(slow);

    // NO ADDRESS (or too thin to place): no request leaves, and the estimator is told.
    const blank = build({ blob: (() => { const b = blob(); delete b.polish_estimate; return b; })(),
                          distance: { ok: true, miles: 99, reason: "" } });
    await blank.api.init(); blank.api.go(1); await settle();
    const blankSnap = snap(blank);
    const thin = build({ blob: (() => { const b = blob({ address: "100 Main St", city: "", state: "" });
      delete b.polish_estimate; return b; })(), distance: { ok: true, miles: 99, reason: "" } });
    await thin.api.init(); await settle();

    // A SAVED BID is not repriced behind anybody's back: no automatic request, the line stays as
    // saved, and the button is how the estimator asks. Pressing it applies the answer.
    const savedModel = { version: 2, takeoff: clone(MODEL.takeoff),
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
              { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 },
              { id: "travel", label: "Travel Labor", guys: "", days: "", rate: 33, unit: "hours",
                guys_auto: true }],
      conditions: Object.assign(clone(MODEL.conditions), { local: true }),
      contingency: 0, fees: 0, totals: {} };
    const saved = build({ blob: blob(Object.assign({ polish_estimate: clone(savedModel) }, ADDRESS)),
                          distance: { ok: true, miles: 150, reason: "" } });
    await saved.api.init(); saved.api.go(1); await settle();
    const savedBefore = snap(saved);
    const savedFetches = (saved.rec.distanceBodies || []).length;
    clickOn(saved, "[data-dist-lookup]"); await settle();
    const savedAfter = snap(saved);

    // TYPED NIGHTS on a far job, and a repaint after the miles move (the note must follow).
    const nights = build({ blob: newBlob(), distance: { ok: true, miles: 150, reason: "" } });
    await nights.api.init(); nights.api.go(1); await settle();
    const nightsAuto = snap(nights);
    typeInto(nights, '[data-trv="lodging"][data-k="qty"]', "10");
    const nightsTyped = snap(nights);
    // Miles typed over the looked-up figure: 150 -> 20, in place.
    typeInto(nights, "[data-dist-miles]", "20");
    const nightsLocal = snap(nights);
    // Days typed on a labor line goes through changed(false): the panel is NOT rebuilt, so only the
    // in-place repaint can move the man-days and dollars in the note.
    const nights2 = build({ blob: newBlob(), distance: { ok: true, miles: 150, reason: "" } });
    await nights2.api.init(); nights2.api.go(1); await settle();
    const daysBefore = snap(nights2);
    typeInto(nights2, '[data-lab="0"][data-k="days"]', "20");
    const daysAfter = snap(nights2);

    out.distance = {
      howNights: { auto: nightsAuto, typed: nightsTyped, local: nightsLocal },
      howDays: { before: daysBefore, after: daysAfter },
      requestBody: (far.rec.distanceBodies || [])[0] || null,
      requests: (far.rec.distanceBodies || []).length,
      far: farSnap,
      farKey: farSnap.distance && farSnap.distance.key,
      farCellB4: farSaved.cell_values["Polish!B4"], farModelLocal: farSaved.polish_estimate.conditions.local,
      farSavedDistance: farSaved.polish_estimate.distance,
      farReviewHasLodging: farReview.indexOf(">Hotel<") !== -1,
      near: nearSnap, nearCellB4: nearSaved.cell_values["Polish!B4"],
      seventy: seventySnap,
      unk: unkSnap, typed85: typed85, typed20: typed20, typed90: typed90, cleared: cleared, decimal: decimal,
      down: downSnap,
      slowBusy: slowBusy, slowAfter: slowAfter,
      blank: blankSnap, blankRequests: (blank.rec.distanceBodies || []).length,
      thinRequests: (thin.rec.distanceBodies || []).length,
      savedBefore: savedBefore, savedFetches: savedFetches, savedAfter: savedAfter,
    };
  }

  // ── N. the Labor Calculator fills a NEW bid's default labor (B7b) ──────────────────────────
  {
    const CALC = [
      { line_id: "polishing", mode: "sf", crew: 3, sf_per_day: 2500, hours_per_day: 10,
        guys: null, days: null, rate: null },
      { line_id: "mockup", mode: "fixed", guys: 2, days: 1, hours_per_day: 8, rate: 50,
        crew: null, sf_per_day: null },
    ];
    const RULE40 = [{ id: "mk1", layout: "global", line_key: "labor_rate", formula: "40", applies: true }];
    const rowOf = (built, id) => built.api.model().labor.find((r) => r.id === id);
    const warn = (built, key) => {
      const el = built.doc.querySelector('[data-calcwarn="' + key + '"]');
      return el ? { text: el.textContent, hidden: !!el.hidden } : null;
    };
    const idx = (built, id) => built.api.model().labor.findIndex((r) => r.id === id);

    const nb = build({ blob: blob({ polish_estimate: null, polish_sf: 12000 }),
                       laborCalc: CALC, markupRules: RULE40 });
    await nb.api.init();
    nb.api.go(1);
    const pi = idx(nb, "polishing");
    const first = { polishing: clone(rowOf(nb, "polishing")), mockup: clone(rowOf(nb, "mockup")),
                    jointfill: clone(rowOf(nb, "jointfill")),
                    hoursSelect: !!nb.doc.querySelector('[data-lab="' + pi + '"][data-k="hours_per_day"]'),
                    warnDays: warn(nb, pi + ":days"), warnRate: nb.doc.querySelector(
                      '[data-ratedflt-for="' + pi + '"]').hidden,
                    cost: B.laborCost(rowOf(nb, "polishing")) };
    // typing a different days figure raises the warning; typing the default back clears it
    typeInto(nb, '[data-lab="' + pi + '"][data-k="days"]', "7");
    const over = warn(nb, pi + ":days");
    typeInto(nb, '[data-lab="' + pi + '"][data-k="days"]', "5");
    const back = warn(nb, pi + ":days");
    // hours a day 10 -> 8 reprices and warns
    const hsel = need(nb, '[data-lab="' + pi + '"][data-k="hours_per_day"]');
    hsel.value = "8";
    nb.doc.fire("change", { target: hsel });
    const hrs = { warn: warn(nb, pi + ":hours_per_day"), cost: B.laborCost(rowOf(nb, "polishing")) };
    // a rate typed over the calculator's own shows the default rate
    const mi = idx(nb, "mockup");
    const mockRateBefore = nb.doc.querySelector('[data-ratedflt-for="' + mi + '"]').hidden;
    typeInto(nb, '[data-lab="' + mi + '"][data-k="rate"]', "33");
    const mockRateAfter = nb.doc.querySelector('[data-ratedflt-for="' + mi + '"]').textContent;

    // a SAVED bid is never recomputed, and does not even ask
    const SAVED = { version: 2, takeoff: clone(MODEL.takeoff),
      labor: [{ id: "polishing", label: "Polishing", guys: 4, days: 6, rate: 33 },
              { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 33 }],
      conditions: clone(MODEL.conditions), contingency: 0, fees: 0, totals: {} };
    const sv = build({ blob: blob({ polish_estimate: clone(SAVED) }), laborCalc: CALC });
    await sv.api.init();
    // no SF yet: from-SF days stay BLANK, not 0
    const nosf = build({ blob: blob({ polish_estimate: null, polish_sf: 0 }), laborCalc: CALC });
    await nosf.api.init();
    nosf.api.go(1);
    const noSfRow = clone(rowOf(nosf, "polishing"));
    const nsi = idx(nosf, "polishing");
    typeInto(nosf, '[data-lab="' + nsi + '"][data-k="days"]', "4");
    const noSfWarn = warn(nosf, nsi + ":days");
    // the table is absent: today's blank crew rows
    const gone = build({ blob: blob({ polish_estimate: null, polish_sf: 12000 }), laborCalcFails: true });
    await gone.api.init();
    const plain = build({ blob: blob({ polish_estimate: null, polish_sf: 12000 }) });
    await plain.api.init();

    // G2: days FOLLOW the takeoff while untouched.
    const setSf = (built, v) => {
      built.api.go(0);
      typeInto(built, '[data-tk="0"][data-k="measurement"]', v);
      built.api.go(1);
    };
    const daysOf = (built, id) => rowOf(built, id).days;
    const fol = build({ blob: blob({ polish_estimate: null, polish_sf: 12000 }), laborCalc: CALC,
                        markupRules: RULE40 });
    await fol.api.init();
    fol.api.go(1);
    const fi = idx(fol, "polishing");
    const followed = { start: daysOf(fol, "polishing") };
    setSf(fol, "20000");
    followed.afterUp = daysOf(fol, "polishing");
    followed.boxAfterUp = fol.doc.querySelector('[data-lab="' + fi + '"][data-k="days"]').value;
    followed.warnAfterUp = warn(fol, fi + ":days");
    followed.fixedStays = daysOf(fol, "mockup");
    // an EDITED days keeps the bid's number when the SF moves again
    typeInto(fol, '[data-lab="' + fi + '"][data-k="days"]', "11");
    setSf(fol, "30000");
    followed.editedStays = daysOf(fol, "polishing");
    // a new bid with NO SF fills its days as soon as SF exists
    const fn = build({ blob: blob({ polish_estimate: null, polish_sf: 0 }), laborCalc: CALC });
    await fn.api.init();
    fn.api.go(1);
    followed.noSfBlank = daysOf(fn, "polishing");
    fn.api.go(0);
    typeInto(fn, '[data-tk="0"][data-k="measurement"]', "5000");
    fn.api.go(1);
    followed.noSfFilled = daysOf(fn, "polishing");
    // a SAVED bid: a stale marker row is NOT recomputed on open, nor by an unrelated edit
    const SAVEDM = { version: 2, takeoff: clone(MODEL.takeoff),
      labor: [{ id: "polishing", label: "Polishing", guys: 3, days: 9, rate: 33, hours_per_day: 8,
                calc_default: { guys: 3, days: 9, rate: 33, hours_per_day: 8, sf_per_day: 2500 } }],
      conditions: clone(MODEL.conditions), contingency: 0, fees: 0, totals: {} };
    const sv2 = build({ blob: blob({ polish_estimate: clone(SAVEDM) }), laborCalc: CALC });
    await sv2.api.init();
    sv2.api.go(1);
    followed.savedOnOpen = daysOf(sv2, "polishing");
    typeInto(sv2, '[data-lab="0"][data-k="rate"]', "35");
    followed.savedAfterOtherEdit = daysOf(sv2, "polishing");
    followed.pureMoves = B.followLaborDays(
      [{ id: "x", days: 5, calc_default: { days: 5, sf_per_day: 2500 } },
       { id: "y", days: 5, calc_default: { days: 5 } }], 10000).map((r) => r.days);

    // G3: Lodging / Per Diem rate boxes warn against the Markups -> Global rate they were filled with.
    const TRV = [{ id: "m1", layout: "global", line_key: "travel_lodging", formula: "80", applies: true },
                 { id: "m2", layout: "global", line_key: "travel_per_diem", formula: "50", applies: true }];
    const tr = build({ blob: blob({ polish_estimate: null, polish_sf: 12000 }), markupRules: TRV });
    await tr.api.init();
    tr.api.go(1);
    const trvW = (built, k) => { const el = built.doc.querySelector('[data-trvdflt-for="' + k + '"]');
      return el ? { text: el.textContent, hidden: !!el.hidden } : null; };
    const trvIn = (k) => '[data-trv="' + k + '"][data-k="rate"]';
    const travelWarn = { rates: [tr.api.model().travel.lodging.rate, tr.api.model().travel.per_diem.rate],
                         start: [trvW(tr, "lodging"), trvW(tr, "per_diem")] };
    typeInto(tr, trvIn("lodging"), "90");
    travelWarn.over = trvW(tr, "lodging");
    typeInto(tr, trvIn("lodging"), "80");
    travelWarn.back = trvW(tr, "lodging");
    const trSaved = build({ blob: blob({ polish_estimate: clone(SAVEDM) }), markupRules: TRV });
    await trSaved.api.init();
    trSaved.api.go(1);
    travelWarn.saved = [trvW(trSaved, "lodging"), trvW(trSaved, "per_diem")];

    out.laborCalc = {
      travelWarn: travelWarn,
      followed: followed,
      first: first, over: over, back: back, hrs: hrs, mockRateBefore: mockRateBefore,
      mockRateAfter: mockRateAfter,
      saved: { polishing: clone(rowOf(sv, "polishing")), asked: sv.rec.fetches.some((u) => /labor-calc/.test(u)) },
      noSf: noSfRow, noSfWarn: noSfWarn,
      gone: { polishing: clone(rowOf(gone, "polishing")), same: JSON.stringify(gone.api.model().labor) ===
              JSON.stringify(plain.api.model().labor) },
    };
  }

  // ── O. The Fees + Textura default (Hanz, 2026-10-06) ────────────────────────────────────────────
  // EXECUTED THROUGH THE PAGE'S OWN INIT: a NEW bid's D77 starts at Markups -> Global `fees_textura`;
  // typing over it shows the shared amber warning, typing the default back clears it; the default is
  // saved with the bid so the warning survives a reload; a SAVED bid keeps its own fees and shows no
  // warning; no default (or $0) leaves $0 and no warning.
  {
    const FEES = [{ id: "m9", layout: "global", line_key: "fees_textura", formula: "250", applies: true }];
    const newBlob = () => blob({ polish_estimate: null, polish_sf: 12000 });
    const feesW = (b) => warn(b, '[data-feesdflt]');
    const feesBox = '[data-fees]';
    const withDflt = build({ blob: newBlob(), markupRules: FEES });
    await withDflt.api.init();
    withDflt.api.go(2);
    const startModel = { fees: withDflt.api.model().fees, fees_default: withDflt.api.model().fees_default };
    const startBox = need(withDflt, feesBox).value;
    const startWarn = feesW(withDflt);
    const startTotal = withDflt.api.bid().total;
    typeInto(withDflt, feesBox, "400");
    const overWarn = feesW(withDflt);
    const overTotal = withDflt.api.bid().total;
    typeInto(withDflt, feesBox, "250");
    const backWarn = feesW(withDflt);
    withDflt.clock.fire();
    const savedWith = withDflt.rec.saves[withDflt.rec.saves.length - 1];
    const reloaded = build({ blob: Object.assign(blob(), { polish_estimate: clone(savedWith.polish_estimate) }),
                             markupRules: [] });
    await reloaded.api.init();
    reloaded.api.go(2);
    typeInto(reloaded, feesBox, "10");
    const reloadWarn = feesW(reloaded);
    // The same new bid with NO default filed, and with a $0 one.
    const none = build({ blob: newBlob() });
    await none.api.init();
    none.api.go(2);
    const zero = build({ blob: newBlob(), markupRules: [
      { id: "m9", layout: "global", line_key: "fees_textura", formula: "0", applies: true }] });
    await zero.api.init();
    zero.api.go(2);
    typeInto(zero, feesBox, "75");
    // A SAVED bid (it states a model) with a default filed: its own fees stand.
    const savedBlob = blob({ polish_estimate: Object.assign(clone(MODEL), { fees: 75 }) });
    const sv = build({ blob: savedBlob, markupRules: FEES });
    await sv.api.init();
    sv.api.go(2);
    out.feesDefault = {
      startModel: startModel, startBox: startBox, startWarn: startWarn, overWarn: overWarn,
      backWarn: backWarn, startTotal: startTotal, overTotal: overTotal,
      noneFees: none.api.model().fees, noneDefault: none.api.model().fees_default === undefined,
      noneBox: need(none, feesBox).value, noneWarn: feesW(none),
      zeroFees: zero.api.model().fees, zeroDefault: zero.api.model().fees_default === undefined,
      zeroWarn: feesW(zero),
      noneTotal: none.api.bid().total,
      savedHasDefault: savedWith.polish_estimate.fees_default,
      reloadWarn: reloadWarn,
      savedBidFees: sv.api.model().fees, savedBidDefault: sv.api.model().fees_default === undefined,
      savedBidWarn: feesW(sv),
      rules: (() => {
        const R = (formula, over) => [Object.assign({ layout: "global", line_key: "fees_textura",
                                                      formula: formula, applies: true }, over || {})];
        return { plain: B.feesFromRules(R("250")), dollar: B.feesFromRules(R("$1,250".replace(",", ""))),
                 decimal: B.feesFromRules(R("99.5")), zero: B.feesFromRules(R("0")),
                 off: B.feesFromRules(R("250", { applies: false })),
                 expr: B.feesFromRules(R("=A1*2")), blank: B.feesFromRules(R("")),
                 none: B.feesFromRules([]), notList: B.feesFromRules(null),
                 otherLine: B.feesFromRules([{ layout: "global", line_key: "labor_rate",
                                               formula: "33", applies: true }]),
                 otherLayout: B.feesFromRules([{ layout: "polish", line_key: "fees_textura",
                                                formula: "5", applies: true }]) };
      })(),
    };
  }

  // ── P. EVERY DEFAULT-PULLED ROW'S ESTIMATE TOGGLE MOVES THE LUMP SUM (Hanz, 2026-10-06) ─────────
  // A library with NON-ZERO prices, a NEW bid that pulls in one of each kind of default, and for
  // each row: flip it, read the lump sum off the page's own bid(), compare with an ORACLE built
  // from the model with that one flag set (the two real engines, priced independently of the
  // page's own wiring), flip it back and demand the same total. The flip is a click on the page's
  // own switch, so a row with no switch, or a switch that writes the wrong field, fails here.
  {
    const FAV_ASMS = ASMS.map((a) => (a.id === "a1" ? Object.assign({}, a, { favorite: true }) : a));
    const FAV_ITEMS = ITEMS.map((i) => (i.id === "i4" ? Object.assign({}, i, { favorite: true }) : i))
      .concat([
        { id: "joint-filler-kit", name: "Joint filler, 10 gal kit", unit: "Kit", buy_qty: 1,
          unit_cost: 500, coverage: 3500, waste_pct: 0, roundup: true },
        { id: "dye", name: "Dye, per coat", unit: "SF", buy_qty: 1, unit_cost: 0.14, coverage: 1,
          waste_pct: 0, roundup: false },
        { id: "remove-existing-jf", name: "Remove existing joint filler", unit: "SF", buy_qty: 1,
          unit_cost: null, coverage: null }]);
    const PLABOR = [
      { id: "travel", name: "Travel", rate: 40, unit: "hours", guys_auto: true, favorite: true },
      { id: "c1", name: "Saw cutting", rate: 45, unit: "days", guys_auto: false, favorite: true,
        default_on: true, default_work_types: [] }];
    const PCALC = [
      { line_id: "polishing", mode: "fixed", guys: 3, days: 5, hours_per_day: 8, rate: null },
      { line_id: "mockup", mode: "fixed", guys: 3, days: 1, hours_per_day: 8, rate: null },
      { line_id: "jointfill", mode: "fixed", guys: 3, days: 2, hours_per_day: 8, rate: null },
      { line_id: "c1", mode: "fixed", guys: 2, days: 3, hours_per_day: 8, rate: null }];
    const PRULES = [
      { id: "m1", layout: "global", line_key: "travel_lodging", formula: "80", applies: true },
      { id: "m2", layout: "global", line_key: "travel_per_diem", formula: "50", applies: true }];
    const PCONDS = ["joint_filler", "remove_existing_jf", "dye"]
      .map((k) => ({ key: k, on: k === "joint_filler", listed: true }));  // the fourth hand needs filler ON
    const nb = blob({ polish_estimate: null, polish_sf: 12000 });
    const p = build({ blob: nb, asms: FAV_ASMS, items: FAV_ITEMS, labor: PLABOR, laborCalc: PCALC,
                      markupRules: PRULES, conditionDefaults: PCONDS });
    await p.api.init();
    // Travel's hours, typed by the estimator (it is the one default whose quantity is theirs).
    p.api.go(1);
    const ti = p.api.model().labor.findIndex((r) => r.id === "travel");
    typeInto(p, '[data-lab="' + ti + '"][data-k="days"]', "2");
    const M0 = () => p.api.model();
    const asmIdx = M0().takeoff.findIndex((r) => r.assembly_id === "a1");
    const itemIdx = M0().takeoff.findIndex((r) => r.item_id === "i4");
    const c1i = M0().labor.findIndex((r) => r.id === "c1");

    // THE ORACLE: the two real engines on a copy of the page's own model with one change applied.
    const oracle = (mutate) => {
      const m = clone(M0());
      mutate(m);
      // TRAVEL LABOR'S GUYS ARE DERIVED (guys_auto): the page re-derives them from the crew's
      // man-days whenever a row flips, so the oracle must too or it prices a stale Travel crew.
      m.labor.forEach((r) => { if (r.unit === "hours" && r.guys_auto) r.guys = B.travelManDays(m.labor); });
      let material = 0;
      m.takeoff.forEach((r) => {
        if (!B.rowOn(r)) return;
        if (r.item_id) {
          const it = FAV_ITEMS.filter((x) => x.id === r.item_id)[0];
          const line = { item_id: it.id, coverage: it.coverage, waste_pct: it.waste_pct || 0, roundup: true };
          material += L.priceAssembly({ id: "x", unit: "SF", lines: [line] }, FAV_ITEMS,
                                      B.num(r.measurement)).total;
        } else {
          const asm = FAV_ASMS.filter((a) => a.id === r.assembly_id)[0];
          if (asm) material += L.priceAssembly(asm, FAV_ITEMS, B.num(r.measurement)).total;
        }
      });
      material += extraMaterial(m);
      return B.markupChain({
        material: material, labor: B.laborTotal(m.labor, m.conditions),
        travel: B.travelCosts(m.travel, m.labor).total,
        contingency: m.contingency, fees: m.fees, conditions: m.conditions,
        sf: B.takeoffSf(m.takeoff), remodel_rate: null }).total;
    };
    const total = () => p.api.bid().total;
    const switchOn = (sel) => { const e = p.doc.querySelector(sel); return e ? e.getAttribute("aria-checked") : null; };
    const cardCls = (sel) => { const e = p.doc.querySelector(sel); return e ? e.className : null; };
    const flipRow = (key, i) => (m) => { const r = m[key][i]; if (B.rowOn(r)) r.enabled = false; else delete r.enabled; };

    const rows = [
      { name: "default assembly takeoff row", step: 0, sw: '[data-on-tk="' + asmIdx + '"]',
        card: '[data-row-card="' + asmIdx + '"]', startOn: () => B.rowOn(M0().takeoff[asmIdx]),
        flipped: flipRow("takeoff", asmIdx) },
      { name: "default material takeoff row", step: 0, sw: '[data-on-tk="' + itemIdx + '"]',
        card: '[data-row-card="' + itemIdx + '"]', startOn: () => B.rowOn(M0().takeoff[itemIdx]),
        flipped: flipRow("takeoff", itemIdx) },
      { name: "joint filler condition row", step: 0, sw: '[data-cond="joint_filler"]', card: null,
        startOn: () => !!M0().conditions.joint_filler,
        flipped: (m) => { m.conditions.joint_filler = !m.conditions.joint_filler; } },
      { name: "dye condition row", step: 0, sw: '[data-cond="dye"]', card: null,
        startOn: () => !!M0().conditions.dye,
        flipped: (m) => { m.conditions.dye = !m.conditions.dye; } },
      { name: "remove-existing condition row", step: 0, sw: '[data-cond="remove_existing_jf"]', card: null,
        startOn: () => !!M0().conditions.remove_existing_jf,
        flipped: (m) => { m.conditions.remove_existing_jf = !m.conditions.remove_existing_jf; } },
      { name: "favorited custom labor line", step: 1, sw: '[data-on-lab="' + c1i + '"]',
        card: '[data-lab-card="' + c1i + '"]', startOn: () => B.rowOn(M0().labor[c1i]),
        flipped: flipRow("labor", c1i) },
      { name: "Travel Labor", step: 1, sw: '[data-on-lab="' + ti + '"]', card: '[data-lab-card="' + ti + '"]',
        startOn: () => B.rowOn(M0().labor[ti]), flipped: flipRow("labor", ti) },
      { name: "Lodging", step: 1, sw: '[data-on-trv="lodging"]', card: '[data-trv-card="lodging"]',
        startOn: () => B.rowOn(M0().travel.lodging),
        flipped: (m) => { m.travel.lodging.enabled = !m.travel.lodging.enabled; } },
      { name: "Per Diem", step: 1, sw: '[data-on-trv="per_diem"]', card: '[data-trv-card="per_diem"]',
        startOn: () => B.rowOn(M0().travel.per_diem),
        flipped: (m) => { m.travel.per_diem.enabled = !m.travel.per_diem.enabled; } },
    ];
    const result = {};
    for (const r of rows) {
      p.api.go(r.step);
      const hasSwitch = !!p.doc.querySelector(r.sw);
      const startOn = r.startOn();
      const t0 = total();
      const expectFlip = oracle(r.flipped);
      const swBefore = hasSwitch ? switchOn(r.sw) : null;
      const cardBefore = r.card ? cardCls(r.card) : null;
      if (hasSwitch) clickOn(p, r.sw);
      const t1 = total();
      p.api.go(r.step);
      const swAfter = switchOn(r.sw);
      const cardAfter = r.card ? cardCls(r.card) : null;
      if (hasSwitch) clickOn(p, r.sw);
      const t2 = total();
      p.api.go(r.step);
      result[r.name] = { hasSwitch: hasSwitch, startOn: startOn, before: t0, afterFlip: t1, back: t2,
                         oracleFlip: expectFlip, swBefore: swBefore, swAfter: swAfter,
                         cardBefore: cardBefore, cardAfterFlip: cardAfter };
    }
    out.toggleMovesTotal = result;
    out.toggleMovesTotalBase = { total: total(), takeoff: M0().takeoff.map((r) => r.assembly_id || r.item_id),
                                 labor: M0().labor.map((r) => r.id) };
  }

  // ── Q. THE TWO TOGGLES ARE INDEPENDENT (Hanz, 2026-10-06) ───────────────────────────────────────
  // The library's default_on only sets what a NEW bid STARTS as; the estimate's own switch is the
  // bid's. (1) flipping rows on an estimate never writes to the library; (2) changing a library
  // default_on after a bid is saved never changes that saved bid; (3) a library default_on only
  // sets a new bid's starting state. EXECUTED through the page's own init, handlers and save.
  {
    const lib = (on) => {
      // `on` is the default_on every default-pulled library row carries (undefined = never set).
      const f = (o) => (on === undefined ? o : Object.assign({}, o, { default_on: on }));
      return {
        asms: ASMS.map((a) => (a.id === "a1" ? f(Object.assign({}, a, { favorite: true })) : a)),
        items: ITEMS.map((i) => (i.id === "i4" ? f(Object.assign({}, i, { favorite: true })) : i)),
        labor: [f({ id: "travel", name: "Travel", rate: 40, unit: "hours", guys_auto: true, favorite: true }),
                f({ id: "c1", name: "Saw cutting", rate: 45, unit: "days", guys_auto: false,
                   favorite: true, default_work_types: [] })],
        laborCalc: [
          { line_id: "polishing", mode: "fixed", guys: 3, days: 5, hours_per_day: 8, rate: null },
          { line_id: "c1", mode: "fixed", guys: 2, days: 3, hours_per_day: 8, rate: null }],
        markupRules: [
          { id: "m1", layout: "global", line_key: "travel_lodging", formula: "80", applies: true }],
      };
    };
    const fresh = () => { const b = blob({ polish_estimate: null, polish_sf: 12000 }); return b; };
    const stateOf = (pg) => {
      const m = pg.api.model();
      return { total: pg.api.bid().total,
               takeoff: m.takeoff.map((r) => B.rowOn(r)),
               labor: m.labor.map((r) => r.id + ":" + B.rowOn(r)) };
    };

    // (3) A NEW bid starts as the library says, and only as the library says.
    const startsOn = build(Object.assign({ blob: fresh() }, lib(true)));
    await startsOn.api.init();
    const startsOff = build(Object.assign({ blob: fresh() }, lib(false)));
    await startsOff.api.init();
    const startsUnset = build(Object.assign({ blob: fresh() }, lib(undefined)));
    await startsUnset.api.init();

    // (1) Flip every default-pulled row on a new bid; count what went to the library.
    // THE SAME library object the page is handed, snapshotted before and compared after -- a
    // freshly built lib(true) on both sides would compare equal whatever the page did.
    const lpLib = lib(true);
    const libBefore = JSON.stringify(lpLib);
    const lp = build(Object.assign({ blob: fresh() }, lpLib));
    await lp.api.init();
    const callsBefore = (lp.rec.calls || []).length;
    const m0 = lp.api.model();
    lp.api.go(0);
    m0.takeoff.forEach((r, i) => { clickOn(lp, '[data-on-tk="' + i + '"]'); });
    lp.api.go(1);
    lp.api.model().labor.forEach((r, i) => { clickOn(lp, '[data-on-lab="' + i + '"]'); });
    clickOn(lp, '[data-on-trv="lodging"]');
    lp.api.go(0);
    clickOn(lp, '[data-cond="dye"]');
    lp.clock.fire();
    // Let any request a handler started actually reach the fetch stub before the verbs are read.
    await new Promise((r) => setImmediate(r));
    await new Promise((r) => setImmediate(r));
    const flipped = stateOf(lp);
    const flipCalls = (lp.rec.calls || []).slice(callsBefore);

    // (2) A SAVED bid: flip some rows, save, then reopen it under a library whose default_on is
    // the OPPOSITE of what the bid started with -- and again under one that matches the flipped
    // rows. Neither may change a row state or the total.
    const sv = build(Object.assign({ blob: fresh() }, lib(true)));
    await sv.api.init();
    sv.api.go(0);
    clickOn(sv, '[data-on-tk="0"]');               // the default assembly row: ON -> OFF
    sv.api.go(1);
    const ci = sv.api.model().labor.findIndex((r) => r.id === "c1");
    clickOn(sv, '[data-on-lab="' + ci + '"]');     // the custom labor line: ON -> OFF
    sv.clock.fire();
    const savedModel = clone(sv.rec.saves[sv.rec.saves.length - 1].polish_estimate);
    const savedBlob = Object.assign(blob(), { polish_sf: 12000, polish_estimate: savedModel });
    const reopen = async (libState) => {
      const pg = build(Object.assign({ blob: clone(savedBlob) }, libState));
      await pg.api.init();
      return stateOf(pg);
    };
    const savedHere = await reopen(lib(true));
    const savedLibFlippedOff = await reopen(lib(false));
    const savedLibMatchesFlips = await reopen((() => {
      const l = lib(true);
      l.asms = l.asms.map((a) => (a.id === "a1" ? Object.assign({}, a, { default_on: false }) : a));
      return l;
    })());
    // A bid saved with a row switched OFF while the library says ON, then the library says OFF->ON.
    out.toggleIndependence = {
      startsOn: stateOf(startsOn), startsOff: stateOf(startsOff), startsUnset: stateOf(startsUnset),
      libraryUntouched: JSON.stringify(lpLib) === libBefore,
      flipCalls: flipCalls, flippedDiffers: flipped.total !== stateOf(startsOn).total,
      saved: { here: savedHere, libOff: savedLibFlippedOff, libMatches: savedLibMatchesFlips },
      savedFlips: { takeoff0: savedModel.takeoff[0].enabled, c1: savedModel.labor.filter((r) => r.id === "c1")[0].enabled },
    };
  }

  // ── THE TAKEOFF CARDS ARE THE TABLE'S ROWS, joined with this page's own views ──────────────────────
  // Read off the page's real CONDITION_CARDS after the real parse: which cards there are, in what order, and
  // each one's cell, reserved library row and dependency come from js/work-types.js (the conditions the
  // Takeoff step asks of a polish job). What a card says is the page's, so the harness reports only the
  // table's half, plus whether a card prices (the remove-existing card must not) and what its hint starts
  // with (the cell it names, which is text this page still types).
  {
    const cards = build();
    out.cards = {
      rows: cards.api.CONDITION_CARDS.map((c) => ({
        key: c.key, cell: c.cell, item_id: c.item_id, needs: c.needs === undefined ? null : c.needs,
        prices: typeof c.cost === "function",
        hintNamesItsCell: typeof c.matHint === "string" ? c.matHint.indexOf(c.cell) === 0 : null,
      })),
      reserved: cards.api.RESERVED_ITEM_IDS,
    };
  }


  // ── LS1. THE CREW LINES COME FROM THE LABOR LIST; A BLANK RATE IS THE LINE'S OWN; NO EMPTY CARDS ──
  {
    const RULE40 = [{ id: "mk1", layout: "global", line_key: "labor_rate", formula: "40", applies: true }];
    const TRAVEL = { id: "travel", name: "Travel", rate: 33, unit: "hours", guys_auto: true, favorite: true,
                     default_work_types: [], sort: -1, notes: "" };
    const crewRow = (id, name, sort, extra) => Object.assign({ id: id, name: name, rate: 33, unit: "days",
      guys_auto: false, favorite: true, default_work_types: ["polish"], sort: sort, notes: "" }, extra || {});
    const CALCS = [
      { line_id: "polishing", mode: "fixed", guys: 4, days: null, hours_per_day: 8, rate: null, crew: null, sf_per_day: null },
      { line_id: "mockup", mode: "fixed", guys: 3, days: 0.5, hours_per_day: 8, rate: null, crew: null, sf_per_day: null },
      { line_id: "jointfill", mode: "fixed", guys: 3, days: null, hours_per_day: 8, rate: null, crew: null, sf_per_day: null },
    ];
    const rowOf = (built, id) => built.api.model().labor.find((r) => r.id === id);
    const idx = (built, id) => built.api.model().labor.findIndex((r) => r.id === id);
    const ids = (built) => built.api.model().labor.map((r) => r.id);
    const fresh = (opts) => build(Object.assign({ blob: blob({ polish_estimate: null, polish_sf: 9000 }),
                                                  markupRules: RULE40 }, opts));

    // A. the library's rows (Kyle re-rated Polishing and renamed Mock-up) are what the bid opens with.
    const a = fresh({ labor: [TRAVEL, crewRow("polishing", "Polishing", 1, { rate: 41 }),
                              crewRow("mockup", "Mock-up crew", 2), crewRow("jointfill", "Joint filler", 3)],
                      laborCalc: CALCS });
    await a.api.init();
    out.ls1Library = { ids: ids(a), polishing: clone(rowOf(a, "polishing")), mockup: clone(rowOf(a, "mockup")),
                       jointfill: clone(rowOf(a, "jointfill")) };

    // B. the library cannot answer (read fails): the shipped crew stands in, at the company rate.
    const f = fresh({ laborFails: true, laborCalcFails: true });
    await f.api.init();
    out.ls1Fallback = { ids: ids(f), rows: f.api.model().labor.map((r) => [r.id, r.guys, r.days, r.rate]) };

    // C. a line taken off the defaults (favorite false) is NOT brought back by the fallback.
    const c = fresh({ labor: [TRAVEL, crewRow("polishing", "Polishing", 1, { favorite: false }),
                              crewRow("mockup", "Mock-up", 2), crewRow("jointfill", "Joint filler", 3)],
                      laborCalc: CALCS });
    await c.api.init();
    out.ls1Removed = ids(c);

    // D. a blank Rate box prices at the line's own rate, and repaints in place.
    const d = a;
    d.api.go(1);
    const pi = idx(d, "polishing");
    const rateSel = '[data-lab="' + pi + '"][data-k="rate"]';
    typeInto(d, '[data-lab="' + pi + '"][data-k="days"]', "5");
    const priced = B.laborCost(rowOf(d, "polishing"));
    const cardBefore = d.doc.querySelector('[data-lab-card="' + pi + '"]');
    const costSel = '[data-lcost-for="' + pi + '"]';
    typeInto(d, rateSel, "");                        // the box is empty while typing
    const whileEmpty = { rate: rowOf(d, "polishing").rate, cost: txt(d, costSel), total: B.laborCost(rowOf(d, "polishing")) };
    changeTo(d, rateSel, "");                        // the commit: the box shows the rate again
    const afterChange = { rate: rowOf(d, "polishing").rate, box: need(d, rateSel).value,
                          sameCard: d.doc.querySelector('[data-lab-card="' + pi + '"]') === cardBefore,
                          cost: txt(d, costSel) };
    typeInto(d, rateSel, "0");
    changeTo(d, rateSel, "0");
    const zero = { rate: rowOf(d, "polishing").rate, cost: B.laborCost(rowOf(d, "polishing")) };
    typeInto(d, rateSel, "");
    changeTo(d, rateSel, "");
    const off = clone(rowOf(d, "polishing"));
    off.rate = ""; off.enabled = false;
    out.ls1Blank = { priced: priced, whileEmpty: whileEmpty, afterChange: afterChange, zero: zero,
                     offCost: B.laborCost(off), unstampedBlank: B.laborCost({ guys: 3, days: 5, rate: "" }),
                     stampedBlank: B.laborCost({ guys: 3, days: 5, rate: "", rate_default: 33 }),
                     calcBlank: B.laborCost({ guys: 3, days: 5, rate: "", calc_default: { rate: 50 }, rate_default: 33 }),
                     savedWarn: warn(d, '[data-ratedflt-for="' + pi + '"]') };

    // D2. a SAVED row holding a blank rate beside a stamp priced $0 and still does after loading.
    const savedBlank = B.migrateModel({ version: 2, takeoff: [], labor: [
      { id: "polishing", label: "Polishing", guys: 3, days: 1, rate: "", rate_default: 33 },
      { id: "mockup", label: "Mock-up", guys: 3, days: 1, rate: "", calc_default: { rate: 50 } }] }).labor;
    out.ls1SavedBlank = { a: B.laborCost(savedBlank[0]), b: B.laborCost(savedBlank[1]) };

    // E. a saved draft with five empty cards opens without them, and its total does not move.
    const six = [{ id: "polishing", label: "Polishing", guys: 3, days: 5, rate: 33 },
                 { id: "travel", label: "Travel Labor", guys: 15, days: 2, rate: 33, unit: "hours", guys_auto: true }];
    const empties = [1, 2, 3, 4, 5].map((n) => ({ id: "u_" + n, label: "", guys: "", days: "", rate: 33 }));
    const mk = (labor) => ({ version: 2, takeoff: clone(MODEL.takeoff), labor: labor,
                             conditions: clone(MODEL.conditions), contingency: 0, fees: 0, totals: {} });
    const withE = build({ blob: blob({ polish_estimate: mk(six.concat(empties)) }) });
    const without = build({ blob: blob({ polish_estimate: mk(six) }) });
    await withE.api.init(); await without.api.init();
    out.ls1Empty = { ids: ids(withE), total: B.laborTotal(withE.api.model().labor),
                     totalWithout: B.laborTotal(without.api.model().labor) };
  }

  // ── N. one search pop-up adds Takeoff rows and Labor cards (Hanz, 2026-10-09) ──────────────
  {
    const keysOf = (b) => popup(b).querySelectorAll("[data-pk]").map((e) => e.attrs["data-pk"]);
    const addBtn = (b) => popup(b).querySelector("[data-pk-add]");
    const isIn = (b, key) => popup(b).querySelectorAll("[data-pk]").some((e) => e.attrs["data-pk"] === key);
    const esc = (b) => fireOn(popup(b), "keydown", { target: popup(b), key: "Escape", preventDefault() {} });
    const countText = (b) => popup(b).querySelector('[data-pk-el="count"]').textContent;
    const pop = {};

    // N1. the takeoff button opens the pop-up and adds NOTHING by itself.
    const probe = build();
    const RESERVED = probe.api.RESERVED_ITEM_IDS;
    const items = clone(ITEMS).concat([{ id: RESERVED[0], name: "Reserved Thing", unit: "Kit",
                                         buy_qty: 1, unit_cost: 10, coverage: 100 }]);
    const t = build({ items: items });
    await t.api.init();
    t.api.go(0);
    const opener = need(t, "[data-add-row]");
    let focusedBack = 0;
    opener.focus = () => { focusedBack += 1; };
    const before = t.api.model().takeoff.length;
    clickOn(t, "[data-add-row]");
    pop.takeoffOpen = { before: before, after: t.api.model().takeoff.length,
                        popupOn: !!popup(t), addDisabled: addBtn(t).disabled, keys: keysOf(t),
                        reservedListed: isIn(t, "item:" + RESERVED[0]) };

    // N2. nothing ticked: Add does nothing and the pop-up stays; Enter in the search box adds nothing.
    pressAdd(t);
    const enterPrevented = pressIn(t, "q", "Enter");
    pop.noPick = { rows: t.api.model().takeoff.length, stillOpen: !!popup(t),
                   addDisabled: addBtn(t).disabled, enterPrevented: enterPrevented };

    // N3. the search narrows the list, and a pick survives a narrowing.
    typeInPopup(t, "q", "cove");
    pop.searched = { keys: keysOf(t) };
    tick(t, "asm:a2");
    typeInPopup(t, "q", "zzzz-no-such");
    pop.searchedNone = { keys: keysOf(t), noneHidden: popup(t).querySelector('[data-pk-el="none"]').hidden,
                         count: countText(t) };
    typeInPopup(t, "q", "");

    // N4. Esc closes it, nothing added, and the caret goes back to the button that opened it.
    esc(t);
    pop.esc = { closed: t.doc.body.kids.length === 0, rows: t.api.model().takeoff.length,
                focusedBack: focusedBack };
    // N4b. Esc also closes it when focus is NOT inside it (keydown lands on body), and the
    // document listener is gone afterwards.
    clickOn(t, "[data-add-row]");
    const kdBefore = t.doc.listeners.filter((l) => l.type === "keydown").length;
    t.doc.fire("keydown", { target: t.doc.body, key: "Escape", preventDefault() {} });
    pop.escOutside = { closed: t.doc.body.kids.length === 0, rows: t.api.model().takeoff.length,
                       focusedBack: focusedBack, listenersWhileOpen: kdBefore,
                       listenersAfter: t.doc.listeners.filter((l) => l.type === "keydown").length };
    focusedBack = 1;
    // ...and so does Cancel.
    clickOn(t, "[data-add-row]");
    fireOn(popup(t), "click", { target: popup(t).querySelector("[data-pk-close]") });
    pop.cancel = { closed: t.doc.body.kids.length === 0, rows: t.api.model().takeoff.length,
                   focusedBack: focusedBack };

    // N5. tick an assembly, a material, and the TWO things that share the name "Grout Compound":
    // each becomes one row, resolved to exactly what was ticked.
    clickOn(t, "[data-add-row]");
    tick(t, "asm:a2"); tick(t, "item:i4"); tick(t, "asm:a6"); tick(t, "item:i5");
    pop.ticked = { count: countText(t), addDisabled: addBtn(t).disabled };
    tick(t, "item:i5");                                   // unticking is real
    pop.untickedCount = countText(t);
    pressAdd(t);
    const mt = t.api.model().takeoff;
    pop.added = { before: before, after: mt.length, closed: t.doc.body.kids.length === 0,
                  rows: clone(mt.slice(before)), focusedBack: focusedBack };

    // N6. the SAME row the row's own search field makes: type the names into undecided rows on a
    // second page and compare what each produced.
    const ty = build({ items: items });
    await ty.api.init();
    const typedRows = {};
    [["Cove Base", "a2"], ["Densifier", "i4"]].forEach((pair) => {
      addUndecidedRow(ty);
      const idx = ty.api.model().takeoff.length - 1;
      typeInto(ty, '[data-tk="' + idx + '"][data-k="pick"]', pair[0]);
      typedRows[pair[1]] = clone(ty.api.model().takeoff[idx]);
    });
    pop.typed = typedRows;

    // N7. a picked row prices like any other once measured.
    const di = t.api.model().takeoff.findIndex((r, i) => i >= before && r.item_id === "i4");
    typeInto(t, '[data-tk="' + di + '"][data-k="measurement"]', "10000");
    pop.pickedCost = { cell: txt(t, '[data-cost-for="' + di + '"]'),
                       expected: L.priceLine({ item_id: "i4" }, ITEMS, 10000).cost };

    // N8. a lone untouched starting row is taken over by the first pick instead of sitting under it.
    const lone = clone(MODEL);
    lone.takeoff = [{ assembly_id: "", assembly_name: "", measurement: "", unit: "SF" }];
    const lb = build({ blob: blob({ polish_estimate: lone }) });
    await lb.api.init();
    lb.api.go(0);
    const loneBefore = lb.api.model().takeoff.length;
    clickOn(lb, "[data-add-row]");
    tick(lb, "asm:a1");
    pressAdd(lb);
    pop.lone = { before: loneBefore, after: lb.api.model().takeoff.map((r) => r.assembly_id) };

    // N9. THE LABOR POP-UP. Library rows: one for another work type, one for this bid's, one for
    // any, Travel (never listed).
    const LIB = [
      { id: "L2", name: "Epoxy prep", rate: 61, unit: "days", default_work_types: ["epoxy"], sort: 2 },
      { id: "L1", name: "Densify crew", rate: 40, unit: "days", default_work_types: ["polish"], sort: 3 },
      { id: "L3", name: "Any work", rate: null, unit: "hours", default_work_types: [], sort: 4 },
      { id: "travel", name: "Travel Labor", rate: 33, unit: "hours", default_work_types: [], sort: 5 },
    ];
    const lab = build({ labor: LIB });
    await lab.api.init();
    lab.api.go(1);
    const lopener = need(lab, "[data-add-lab]");
    let lfocus = 0;
    lopener.focus = () => { lfocus += 1; };
    const lBefore = lab.api.model().labor.length;
    const idsBefore = lab.api.model().labor.map((r) => r.id);
    await openLaborPopup(lab);
    pop.laborOpen = { before: lBefore, after: lab.api.model().labor.length, popupOn: !!popup(lab),
                      keys: keysOf(lab), addDisabled: addBtn(lab).disabled,
                      oneOffDisabled: popup(lab).querySelector("[data-pk-oneoff]").disabled };
    // an empty one-off name adds nothing, Enter included
    pressIn(lab, "oneoff", "Enter");
    pop.laborEmptyOneOff = { rows: lab.api.model().labor.length, stillOpen: !!popup(lab) };
    pressAdd(lab);                                         // nothing ticked: Add does nothing
    pop.laborNoPick = { rows: lab.api.model().labor.length, stillOpen: !!popup(lab) };
    esc(lab);
    pop.laborEsc = { closed: lab.doc.body.kids.length === 0, rows: lab.api.model().labor.length,
                     focusedBack: lfocus };

    await openLaborPopup(lab);
    tick(lab, "lab:L1"); tick(lab, "lab:L3");
    pressAdd(lab);
    const picked = lab.api.model().labor.slice(lBefore);
    // The same mapping a new bid's seeding uses, plus the stamp.
    const viaSeed = B.stampRateDefaults(B.seedLibraryLabor([], [
      Object.assign({}, LIB[1], { favorite: true }), Object.assign({}, LIB[2], { favorite: true })],
      B.SHIPPED_LABOR_RATE, "polish"));
    pop.laborPicked = { cards: clone(picked), viaSeed: clone(viaSeed), idsBefore: idsBefore,
                        closed: lab.doc.body.kids.length === 0, focusedBack: lfocus };
    // The card is a real card: the Task name stays editable, the blank-rate fallback and the
    // "Default value" note work (LS1), and the cost prices from what was typed.
    const ci = lBefore + 1;                        // "Any work", no rate of its own
    typeInto(lab, '[data-lab="' + ci + '"][data-k="label"]', "Any work v2");
    typeInto(lab, '[data-lab="' + ci + '"][data-k="guys"]', "2");
    typeInto(lab, '[data-lab="' + ci + '"][data-k="days"]', "3");
    typeInto(lab, '[data-lab="' + ci + '"][data-k="rate"]', "");
    pop.laborCard = { label: lab.api.model().labor[ci].label,
                      rateDefault: lab.api.model().labor[ci].rate_default,
                      costBlankRate: txt(lab, '[data-lcost-for="' + ci + '"]'),
                      expectedBlankRate: B.laborCost({ guys: "2", days: "3", rate: "", rate_default: 33,
                                                       unit: "hours" }),
                      warn: warn(lab, '[data-ratedflt-for="' + ci + '"]') };

    // N10. a library line already on the bid is listed locked and cannot be ticked twice.
    await openLaborPopup(lab);
    const lenNow = lab.api.model().labor.length;
    tick(lab, "lab:L1");
    pressAdd(lab);
    pop.laborLocked = { addedAnother: lab.api.model().labor.length - lenNow,
                        stillOpen: !!popup(lab),
                        lockedRowMarked: /On this bid/.test(
                          popup(lab).querySelector('[data-pk-el="list"]').innerHTML) };

    // N11. the One-off line: name typed (spaces folded), a custom card at the company rate.
    typeInPopup(lab, "oneoff", "  Hand   grind ");
    pop.oneOffEnabled = !popup(lab).querySelector("[data-pk-oneoff]").disabled;
    const oneBefore = lab.api.model().labor.length;
    pressIn(lab, "oneoff", "Enter");
    pop.oneOff = { added: lab.api.model().labor.length - oneBefore,
                   card: clone(lab.api.model().labor[oneBefore] || {}),
                   closed: lab.doc.body.kids.length === 0 };

    // N12. no card anywhere is nameless, however the pop-up was used.
    pop.allNamed = lab.api.model().labor.every((r) => String(r.label || "").trim() !== "");

    // N13. the Labor list cannot be read: the shipped crew stands in, Travel still never listed.
    const bad = build({ laborFails: true });
    await bad.api.init();
    bad.api.go(1);
    await openLaborPopup(bad);
    pop.laborFallback = { keys: keysOf(bad) };

    // N14. two assemblies with ONE name and different units: ticking the second lands on the
    // second's unit, not the first's.
    const dupAsms = clone(ASMS).concat([{ id: "a2b", name: "Cove Base", unit: "SF", lines: [
      { item_id: "i2", coverage: 125, waste_pct: 0, roundup: false }] }]);
    const dp = build({ asms: dupAsms });
    await dp.api.init();
    dp.api.go(0);
    const dBefore = dp.api.model().takeoff.length;
    clickOn(dp, "[data-add-row]");
    tick(dp, "asm:a2b"); tick(dp, "asm:a2");
    pressAdd(dp);
    pop.dupName = dp.api.model().takeoff.slice(dBefore).map((r) => ({ id: r.assembly_id, unit: r.unit }));

    out.addPopup = pop;
  }

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
