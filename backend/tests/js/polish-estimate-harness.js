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
 * REAL: js/polish-bid-core.js (the markup chain, pinned to Kyle's Polish tab) and
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
const B = require(path.join(ROOT, "js", "polish-bid-core.js"));
const L = require(path.join(ROOT, "js", "library-core.js"));

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
    rowPrice: rowPrice, materialTotal: materialTotal, bid: bid,
    moneyAuto: moneyAuto, measureText: measureText, asmHint: asmHint,
    repaintNumbers: repaintNumbers, renderPanel: renderPanel, stepStatus: stepStatus,
    takeoffPanel: takeoffPanel, laborPanel: laborPanel, reviewPanel: reviewPanel,
    markupTable: markupTable, newLaborRow: newLaborRow,
    STEPS: STEPS, UNITS: UNITS,
    model: function () { return M; },
    state: function () { return state; },
    asms: function () { return ASMS; },
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
  return {
    listeners,
    getElementById: dom.get,
    createElement: (tag) => dom.element(String(tag).toLowerCase(), {}, "", null),
    createTextNode: (txt) => ({ isText: true, text: String(txt) }),
    addEventListener(type, handler) {
      listeners.push({ type, handler });
      log.push("listen:" + type);
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
  conditions: { local: true, hard_bid: false, prevailing_wage: false, taxable: true,
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
 *  polish-bid-core's markupChain, not merely be self-consistent. */
/** `remodelRate` is the project's county rate off the draft, which the page reads from
 *  `state.county_remodel_rate`. Passing it here too keeps this expectation and the page computing
 *  the same thing; leaving it out would let a page that ignored the county still match. */
function expectedChain(model, asms, items, remodelRate) {
  let material = 0;
  (model.takeoff || []).forEach((r) => {
    const asm = (asms || []).filter((a) => a.id === r.assembly_id)[0];
    if (asm) material += L.priceAssembly(asm, items, B.num(r.measurement)).total;
  });
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
    TWPolishBid: B, TWLib: L, TWPolishSandbox: S,
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

  const fetchStub = async function (url) {
    rec.fetches.push(url);
    log.push("fetch:" + url);
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
    if (/condition-defaults/.test(url)) {
      if (opts.conditionFetchFails) throw new Error("the defaults table is not there");
      return { json: async () => ({ ok: true,
        conditions: clone(opts.conditionDefaults === undefined
          ? [] : opts.conditionDefaults) }) };
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
function clickOn(built, sel) {
  return clickEl(built, need(built, sel));
}
function clickEl(built, el) {
  built.doc.fire("click", { target: el, preventDefault: function () {} });
  return el;
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
      expectedMaterial: rows.reduce((s, r) => s + r.expectedTotal, 0),
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
    const chain = expectedChain(
      Object.assign(clone(MODEL), { takeoff: clone(MODEL.takeoff).map(
        (r, i) => (i === 0 ? Object.assign(r, { measurement: "20000" }) : r)) }), ASMS, ITEMS);
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
      L.priceAssembly(ASMS[2], ITEMS, 5000).total;

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
      const asmField = need(c, '[data-tk="0"][data-k="assembly_name"]');
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
      // The toggle lives in the header (before the fields grid starts), on Travel's own card
      // (card index 2, the auto-appended row) -- not the old inline hint link.
      toggleInHeader: /class="mw-sw labsw" role="switch"[^>]*data-lab-manual="2"/.test(
        (panels.innerHTML.split('class="tk lab')[3] || "").split('class="tk-g')[0]),
      linkishGone: panels.innerHTML.indexOf("linkish") === -1,
      // A SWITCH REPORTS ITS STATE, which is the whole reason this stopped being a button
      // whose words flipped. Off while the figure is derived, on once it is typed --
      // and the label stays the same sentence in both, so it describes what IS rather
      // than what clicking would do.
      // BOTH POSITIONS, because the fixture only ever renders one. Travel boots in AUTO, so
      // a check that reads the page as-built inspects a single branch of the ternary --
      // flipping the OTHER branch back to "Back to auto" then changes nothing any
      // assertion can see. The manual state has to be entered before it can be asserted.
      toggleSaysItsState: await (async () => {
        const k = build();
        await k.api.init();
        k.api.go(1);
        const kp = k.dom.get("panels");
        const ti = k.api.model().labor.findIndex((r) => r.id === "travel");
        const headOf = () => (kp.innerHTML.split('class="tk lab')[ti + 1] || "")
          .split('class="tk-g')[0];
        const offHead = headOf();                 // derived: switch off
        clickOn(k, '[data-lab-manual="' + ti + '"]');
        const onHead = headOf();                  // typed: switch on
        const read = (h, want) => ({
          checked: h.indexOf('aria-checked="' + want + '"') !== -1,
          labelOnce: (h.match(/Type my own/g) || []).length,
          backToAutoGone: h.indexOf("Back to auto") === -1,
          hasTrack: h.indexOf('<span class="track">') !== -1,
        });
        return { off: read(offHead, "false"), on: read(onHead, "true") };
      })(),
      // Still a <button>: the `.mw-sw` conditions are spans with no keydown handler, so
      // matching them visually must not cost this control its keyboard.
      toggleIsAButton: /<button[^>]*class="mw-sw labsw"/.test(panels.innerHTML),
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
      // The way back.
      clickOn(c, '[data-lab-auto="' + travelIdx() + '"]');
      const afterBackToAuto = { guys: travelRow().guys, auto: travelRow().guys_auto };
      out.travelGuys = {
        seeded: before, afterCrewEdit: afterCrewEdit,
        afterTyping: afterTyping, stickyAfterCrewMoves: stickyAfterCrewMoves,
        afterBackToAuto: afterBackToAuto,
        // The box shows the derived figure rather than sitting empty next to a priced row.
        boxShowsIt: String(need(c, '[data-lab="' + travelIdx() + '"][data-k="guys"]').value),
        manualLinkOffered: cp.innerHTML.indexOf("data-lab-manual=") !== -1,
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

    // Add a line: it appears, it is editable, and it prices from ITS OWN values. Travel is
    // backfilled onto MODEL's saved (pre-#491) two rows at boot — see migrateModel's Travel
    // comment — so the model already has three rows [Polishing, Mock-up, Travel] before this
    // click, and the new row lands at index 3, not 2.
    clickOn(b, "[data-add-lab]");
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

    // Add a takeoff row: it appears empty, priced at nothing, and says why.
    const t3 = build();
    await t3.api.init();
    clickOn(t3, "[data-add-row]");
    out.labor.addedTakeoffRow = {
      count: t3.api.model().takeoff.length,
      cost: txt(t3, '[data-cost-for="3"]'),
      hint: txt(t3, '[data-asmhint-for="3"]'),
    };
  }

  // ── E. review: the markup block IS the chain, gated by the conditions ──────
  {
    const live = clone(MODEL);
    live.conditions = { local: true, hard_bid: true, prevailing_wage: true, taxable: true,
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
        return { gp_pct: B.pct(c.gp_pct), hard_bid_pct: B.pct(c.hard_bid_pct),
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
    const off = clone(MODEL);
    off.conditions = { local: true, hard_bid: false, prevailing_wage: false, taxable: false,
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
      // Hard bid ON but still no discount is the case that reads like a bug, so it is the case
      // that gets words. Off says nothing, because the switch beside it already did.
      thresholdNoteWhenOff: /under the discount threshold/.test(o.dom.get("panels").innerHTML),
    };
    {
      // Hard bid ON, and the bid still under the threshold: the one row that must explain itself.
      // hardBidPct() gives a local job nothing under a $13,000 sub-total, so the takeoff and labor
      // are cut right down -- the point is a priced job whose discount is legitimately zero, not
      // an empty model.
      const ht = clone(off);
      ht.conditions.hard_bid = true;
      ht.takeoff = [{ assembly_id: "a5", assembly_name: "Densifier Only", measurement: 200,
                      unit: "SF" }];
      ht.labor = [{ id: "polishing", label: "Polishing", guys: 1, days: 1, rate: 33 }];
      const h = build({ blob: blob({ polish_estimate: clone(ht) }) });
      await h.api.init();
      h.api.go(2);
      const hc = expectedChain(ht, ASMS, ITEMS);
      out.review.off.thresholdNoteWhenOnButZero =
        /under the discount threshold/.test(h.dom.get("panels").innerHTML) &&
        hc.hard_bid_pct === 0 && hc.sub_total > 0 && hc.sub_total < 13000;
    }
  }

  // ── E2. the Review step's switches are real controls ──────────────────────
  // Every condition Review talks about can be answered HERE, not only back on Intake. Each click
  // goes through the page's own delegated listener, so this exercises the shipped path.
  {
    const start = clone(MODEL);
    start.conditions = { local: true, hard_bid: false, prevailing_wage: false, taxable: true,
                         remodel_tax: false, bond: false };
    out.review.clicks = {};
    for (const key of ["hard_bid", "prevailing_wage", "taxable", "remodel_tax", "bond"]) {
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
    clickOn(m, "[data-add-mat]");
    const idx = m.api.model().takeoff.length - 1;
    const row = () => m.api.model().takeoff[idx];
    const card = () => (m.dom.get("panels").innerHTML.split('class="tk mat"')[1] || "")
      .split("</div></div>")[0];

    const seeded = clone(row());
    typeInto(m, '[data-tk="' + idx + '"][data-k="item_name"]', "Densifier");
    typeInto(m, '[data-tk="' + idx + '"][data-k="measurement"]', "10000");
    const pickedUnit = row().unit;                    // must stay SF, NOT the item's "Pail"
    const afterPick = clone(row());

    // THE MONEY, against library-core's own engine rather than a number typed into this file.
    // Densifier: $100 a pail, 1,000 SF a pail, no waste, roundup on. 10,000 SF is 10 pails.
    const expected = L.priceLine({ item_id: "i4" }, ITEMS, 10000);
    // READ THE NODE, NOT THE MARKUP. `changed(false)` repaints through textContent on the
    // cost element; the panel innerHTML captured at render time never moves, so a regex over
    // it reports the figure from before the keystroke -- em dash forever, which reads as a
    // row that will not price.
    const costCell = () => txt(m, '[data-cost-for="' + idx + '"]');
    const costWithLibraryCoverage = costCell();

    // A COVERAGE TYPED ON THE ROW WINS over the item's default, which is the whole reason the box
    // is there: the same product goes further in one system than another.
    typeInto(m, '[data-tk="' + idx + '"][data-k="coverage"]', "500");
    const expectedTyped = L.priceLine({ item_id: "i4", coverage: 500 }, ITEMS, 10000);
    const costWithTypedCoverage = costCell();

    out.materialRow = {
      seeded: seeded,
      isItemKind: seeded.kind === "item",
      // The card, not the model: an assembly row and a material row must not look the same.
      saysMaterial: /MATERIAL/.test(m.dom.get("panels").innerHTML),
      hasCoverageField: /data-k="coverage"/.test(m.dom.get("panels").innerHTML),
      resolvedId: afterPick.item_id,
      // NO UNIT ADOPTION. An item's unit is what it is BOUGHT in (Pail), not how the floor is
      // measured. Copying it onto the row would price a 10,000 SF area in pails.
      unitStayedSF: pickedUnit === "SF",
      costWithLibraryCoverage: costWithLibraryCoverage,
      expectedLibraryCost: expected.cost,
      costWithTypedCoverage: costWithTypedCoverage,
      expectedTypedCost: expectedTyped.cost,
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
        return {
          count: (h.match(/class="tk cond/g) || []).length,
          // The card must NOT claim a cost. An assembly row comes to a number; these come to a
          // Yes/No that only Kyle's workbook reads, and printing "$0" beside one would be a
          // figure, and would be wrong.
          noCostBox: !/class="tk cond[^"]*"[\s\S]{0,600}?costbox/.test(h),
          // It names the cell it sets, which is the only thing it actually does.
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
      blankLeavesTheDefault: (function () {
        const k = build({ blob: blob({ cell_values: { "Polish!E29": "" } }) });
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
      conditions: { local: false, hard_bid: true, prevailing_wage: true, taxable: false,
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
        conditions: { local: true, hard_bid: false, prevailing_wage: false, taxable: true,
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

  // ── I. the datalist, filled from the assemblies ────────────────────────────
  {
    const b = build();
    await b.api.init();
    const dl = b.dom.get("dl-assemblies");
    out.datalist = {
      options: dl.children.filter((c) => c.tag === "option").map((c) => dec(c.attrs.value)),
      expected: ASMS.map((a) => a.name),
      // The assembly box is a searchable list input, not a <select>: the library will get long.
      pickerIsAList: /<input list="dl-assemblies" data-tk="0" data-k="assembly_name"/
        .test(b.dom.get("panels").innerHTML),
      pickerIsNotASelect: !/<select[^>]*data-k="assembly_name"/.test(
        b.dom.get("panels").innerHTML),
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
    const d = build();
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
    const LIB = [
      { id: "lab-densify", name: "Densify", rate: "40.00", unit: "days", guys_auto: false,
        sort: 0, notes: null, owner_email: "hanz@wetreadwell.com" },
      { id: "lab-night", name: "Night shift premium", rate: 12.5, unit: "hours", guys_auto: true,
        sort: 1, notes: "after 6pm", owner_email: "hanz@wetreadwell.com" },
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
      conditions: { local: true, hard_bid: false, prevailing_wage: false, taxable: true,
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
        { id: "travel", label: "Travel", guys: 18, days: 2, rate: 33,
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
    // Every stored answer disagrees with what the tool ships — joint filler ships ON and this says
    // off; dye and remove-existing ship off and this says on. A fixture that agreed with
    // freshModel could not tell a seeder that works from one that was never wired up.
    const COND = [{ key: "joint_filler", on: false },
                  { key: "dye", on: true },
                  { key: "remove_existing_jf", on: true }];
    const conds = (built) => built.api.model().conditions;

    // A brand-new project: no polish_estimate on the draft at all. This is the sidebar door and a
    // project that reached this page without going through the beta intake.
    const noKey = blob();
    delete noKey.polish_estimate;
    const brandNew = build({ blob: noKey, conditionDefaults: COND });
    await brandNew.api.init();

    // AN ESTIMATOR'S OWN ANSWERS, every one of them the opposite of the stored default. joint
    // filler is the one that bites: it SHIPS on, so a bid where somebody deliberately turned it
    // off is exactly the bid a careless default would quietly turn back on — and the downloaded
    // workbook would then say Yes in Polish!E29.
    const WORKED = {
      version: 2,
      takeoff: clone(MODEL.takeoff),
      labor: clone(MODEL.labor),
      conditions: Object.assign({}, MODEL.conditions,
        { joint_filler: true, dye: false, remove_existing_jf: false }),
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
    const fromCells = (() => { const b = blob(); delete b.polish_estimate;
                               b.cell_values = { "Polish!E29": "Yes", "Polish!E25": "No",
                                                 "Polish!F29": "No" };
                               return b; })();
    const celled = build({ blob: fromCells, conditionDefaults: COND });
    await celled.api.init();

    // PRODUCTION TODAY: the table is not there, so the read cannot answer.
    const down = build({ blob: (() => { const b = blob();
                                        delete b.polish_estimate; return b; })(),
                         conditionFetchFails: true });
    await down.api.init();

    out.conditionDefaults = {
      brandNew: { conditions: conds(brandNew),
                  fetched: brandNew.rec.fetches.some((u) => /condition-defaults/.test(u)) },
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

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
