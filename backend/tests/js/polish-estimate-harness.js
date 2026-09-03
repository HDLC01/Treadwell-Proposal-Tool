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

    // The same, on the labour side.
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

  // ── D. labour maths, and the add/remove lines ──────────────────────────────
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
      headings: (panels.innerHTML.match(/<th(?:\s[^>]*)?>([^<]*)</g) || [])
        .map((x) => (/>([^<]*)</.exec(x) || ["", ""])[1]),
    };

    // Add a line: it appears, it is editable, and it prices from ITS OWN values.
    clickOn(b, "[data-add-lab]");
    out.labor.afterAdd = { count: b.api.model().labor.length,
                           rebuilt: panels.htmlWrites > 0 };
    typeInto(b, '[data-lab="2"][data-k="label"]', "Densify");
    typeInto(b, '[data-lab="2"][data-k="guys"]', "2");
    typeInto(b, '[data-lab="2"][data-k="days"]', "3");
    typeInto(b, '[data-lab="2"][data-k="rate"]', "40");
    out.labor.newRowCost = txt(b, '[data-lcost-for="2"]');
    out.labor.newRowExpected = B.laborCost({ guys: "2", days: "3", rate: "40" });
    out.labor.newRowLabel = b.api.model().labor[2].label;
    // …and the two rows above it are untouched by the new one's arithmetic.
    out.labor.row0StillAnchored = txt(b, '[data-lcost-for="0"]');
    out.labor.totalAfterAdd = txt(b, "[data-labor-total]");
    out.labor.totalAfterAddExpected = B.laborTotal(b.api.model().labor);

    // Delete the RIGHT one: index 1 is the mock-up, and it is the one that goes — not the row
    // above it and not the one that was added last.
    clickOn(b, '[data-del-lab="1"]');
    out.labor.afterDelete = b.api.model().labor.map((r) => r.label);
    out.labor.afterDeleteCells = b.doc.querySelectorAll("[data-lcost-for]").length;
    out.labor.afterDeleteCosts = [0, 1].map((i) => txt(b, '[data-lcost-for="' + i + '"]'));

    // Take it down to one line. The ✕ is then not offered at all…
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
                        remodel_tax: true };
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
                 sales_tax_pct: B.pct(c.sales_tax_pct), remodel_pct: B.pct(c.remodel_pct) };
      })(),
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
                       remodel_tax: false };
    const o = build({ blob: blob({ polish_estimate: clone(off) }) });
    await o.api.init();
    o.api.go(2);
    rendered.push(o.dom.get("panels").innerHTML);
    out.review.off = {
      rendered: readMk(o),
      rowClasses: rowClasses(o.dom.get("panels").innerHTML),
      expected: expectedChain(off, ASMS, ITEMS),
      // The rows that are off point at the step that can turn them on.
      salesTaxRowSaysWhere: /Sales tax[\s\S]{0,220}?edit in Intake/.test(
        o.dom.get("panels").innerHTML),
      remodelRowSaysWhere: /remodel tax[\s\S]{0,220}?edit in Intake/i.test(
        o.dom.get("panels").innerHTML),
      hardBidReason: /hard bid off/.test(o.dom.get("panels").innerHTML),
    };
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
      // No cell_values key at all: this page stopped writing worksheet cells.
      hasCellValues: Object.prototype.hasOwnProperty.call(save, "cell_values"),
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
  // tax on commercial remodel LABOUR at the state rate plus the county portion only. Hanz,
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
    // remodel labour as exempt. This must charge NOTHING — not the Kansas state fallback, which is
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

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
