"use strict";
/* Execute the REAL functions out of frontend/js/polish-intake.js and report what they did.
 *
 * WHY EXECUTED. Every interesting way this page can be wrong is invisible to a source assertion:
 *
 *   * "the save merges into polish_estimate" is a claim about an OBJECT, not about the word
 *     `Object.assign` appearing in the file. The way it fails is a finished takeoff disappearing
 *     when somebody flips a toggle, and the only honest check is to put takeoff rows on the model,
 *     flip a toggle, and look at what was actually queued.
 *   * `paintCondition` finds its switch by `#cond-<key>`, an id `switchHtml` writes in a different
 *     function. A grep proves both mention it; rendering the block and then flipping a toggle
 *     proves the repaint lands on the element that was rendered.
 *   * "nothing renders before the sandbox settles" is an ORDERING. Recorded here as a log of what
 *     the page wrote and when, with the sandbox's own entries in the same log.
 *   * An unbound identifier in a handler is exactly what a source test cannot see, and that class
 *     of mistake took the board down on prod on 2026-08-12.
 *
 * The condition KEYS are compared against the real js/polish-bid-core.js, so this cannot pass
 * against a list that has drifted from the one markupChain() reads. That anchor moved when the
 * beta stopped writing worksheet cells: the keys used to have to match cellWrites() in the old
 * polish-estimate-core.js, and now they have to match the pricing engine that consumes them —
 * a toggle whose key the chain does not read is a toggle that silently does nothing.
 *
 * The COUNTY picker is executed the same way, and for the same reason. "The pick writes
 * county_remodel_rate" is a claim about a draft: it fails as a Kansas job priced at the state
 * fallback, or a Missouri job charged a Kansas rate, with the right-looking sentence on screen
 * either way. So the list is fetched, a search is typed, a row is clicked, and what landed on the
 * draft is priced through the real markupChain.
 *
 * Only the network's stand-in (TW, the sandbox module, fetch) and the clock are stubbed. The
 * renders, the model arithmetic, the handlers and the boot sequence are the page's own code, and
 * the county rows are the server's own reference table.
 *
 * Usage: node polish-intake-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);

// Normalised on read: this harness matches the page's source text, and git hands these files out
// with CRLF on a Windows checkout. See the longer note in polish-estimate-harness.js — an
// exact-substring anchor misses on CRLF, CI stays green on LF, and the developer sees every test
// in the file report "the harness crashed" instead of anything about the product.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const src = read(path.join(ROOT, "js", "polish-intake.js"));
const pageHtml = read(path.join(ROOT, "polish-intake.html"));
const P = require(path.join(ROOT, "js", "polish-bid-core.js"));

// ── the REAL county table, out of the server module that serves it ────────────
//
// backend/reference_tax.py is what GET /api/reference/counties returns, and its rates were pulled
// one by one from the KS DOR Address Tax Rate Locator. Parsed here rather than retyped so that
// 0.07975 is the DOR's number for Johnson County and not one this test invented: a fixture with a
// made-up rate would keep passing after the table it is meant to be pinning had changed.
//
// Each row in that file is one line of double-quoted keys and plain numbers, which is already JSON.
//
// Bounded to the COUNTIES literal itself (bracket-balanced), NOT sliced to end-of-file: a CITIES
// table was added below COUNTIES in reference_tax.py, shaped as the same `{"name": ...}` dicts, and
// an unbounded slice-to-EOF swept those city rows in too — untagged (no `kind`), so the real
// countyRowLabel() then mislabelled a city ("Shawnee" in Johnson Co.) as a county ("Shawnee
// County, KS"). Bracket-balancing is safe here because no row has a nested `[`.
const COUNTIES = (function () {
  const py = read(path.join(ROOT, "..", "backend", "reference_tax.py"));
  const decl = "COUNTIES: list[dict] = [";
  const from = py.indexOf(decl);
  if (from < 0) throw new Error("COUNTIES is gone from backend/reference_tax.py — rewrite this");
  // The declaration's own type annotation ("list[dict]") has a "[" before the list literal's own —
  // start the bracket search at the "[" the decl string ends on, not the first one after `from`.
  const open = from + decl.length - 1;
  let depth = 0, end = -1;
  for (let i = open; i < py.length; i++) {
    if (py[i] === "[") depth++;
    else if (py[i] === "]" && --depth === 0) { end = i; break; }
  }
  if (end < 0) throw new Error("COUNTIES list never closes — rewrite this");
  const body = py.slice(open, end + 1);
  const rows = (body.match(/\{"name":[^}]*\}/g) || []).map((s) => JSON.parse(s));
  if (rows.length < 20) throw new Error("only parsed " + rows.length + " counties — rewrite this");
  if (rows.some((c) => "county" in c && !("fips" in c))) {
    throw new Error("parsed a CITIES-shaped row into COUNTIES — the bracket bound broke, rewrite this");
  }
  return rows;
})();

const JOHNSON_KS = COUNTIES.filter((c) => c.name === "Johnson" && c.state === "KS")[0];
if (!JOHNSON_KS || JOHNSON_KS.remodel_rate == null) {
  throw new Error("Johnson County, KS has no remodel_rate in reference_tax.py");
}

/** Lift a named function out of the page's IIFE (two-space indent), braces balanced. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) {
    throw new Error(name + "() is gone from polish-intake.js — rewrite this harness, don't stub it");
  }
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

function grab(re, what) {
  const m = re.exec(src);
  if (!m) throw new Error(what + " is gone from polish-intake.js — rewrite this harness");
  return m[0];
}

// ── a DOM stub, only as much as this page touches ─────────────────────────────
//
// The child nodes for the switches are created FROM renderConditions' own output, which is the
// whole point: paintCondition addresses `#cond-<key>`, and a hand-written fixture could agree with
// the repaint while disagreeing with what the page rendered.
function makeDom(log, formValues) {
  const nodes = {};
  // Which element last had focus() called on it. repaintCondition puts the caret back after the
  // re-render Joint filler forces, and until this existed the page's own `again.focus &&` guard
  // short-circuited against the stub -- so the restore was unobservable and a regression that
  // dropped it would have gone on passing. Browser walks find keyboard bugs; a stub without a
  // focus() cannot.
  let focused = null;

  function node(id) {
    let html = "", hidden = false, cls = "", text = "";
    const self = {
      id, value: "", attrs: {}, listeners: [],
      get innerHTML() { return html; },
      set innerHTML(v) { html = v; log.push("html:" + id); adoptIds(v); },
      get hidden() { return hidden; },
      set hidden(v) { hidden = !!v; log.push((v ? "hide:" : "show:") + id); },
      get className() { return cls; },
      set className(v) { cls = v; log.push("class:" + id); },
      get textContent() { return text; },
      set textContent(v) { text = String(v); log.push("text:" + id); },
      setAttribute(k, v) { self.attrs[k] = v; },
      getAttribute(k) { return Object.prototype.hasOwnProperty.call(self.attrs, k)
        ? self.attrs[k] : null; },
      addEventListener(type, handler) { self.listeners.push({ type, handler }); },
      focus() { focused = id; log.push("focus:" + id); },
      // Either quote style, because the page uses both: hydrate reaches for [name='bid_date'] and
      // applyVerbal/paintProjLine build [name="…"]. A stub that only understood one silently
      // returned null for half the page's own lookups.
      querySelector(sel) {
        const m = /^\[name=['"]([^'"]+)['"]\]$/.exec(sel);
        if (m) return fields[m[1]] || null;
        return null;
      },
      querySelectorAll() { return []; },
      // What a delegated document click walks up to reach the thing it was aimed at. Attribute and
      // id selectors only, and SELF only — every click fired below is aimed at the element the page
      // rendered, so a real ancestor walk would only be able to invent a match.
      closest(sel) {
        const attr = /^\[([a-z-]+)\]$/.exec(sel);
        if (attr) {
          return Object.prototype.hasOwnProperty.call(self.attrs, attr[1]) ? self : null;
        }
        const byId = /^#([\w-]+)$/.exec(sel);
        if (byId) return self.id === byId[1] ? self : null;
        return null;
      },
    };
    return self;
  }

  // Form fields the page reaches for by name. `bid_date` is the only one it touches directly.
  const fields = {};
  Object.keys(formValues || {}).forEach((k) => { fields[k] = { name: k, value: "" }; });
  if (!fields.bid_date) fields.bid_date = { name: "bid_date", value: "" };

  /** Register a node for every id the rendered markup carries, with the attributes it carries,
   *  so a later lookup finds the element the page actually produced. */
  function adoptIds(markup) {
    String(markup).split("<div").slice(1).forEach((chunk) => {
      const head = chunk.split(">")[0];
      const id = (/id="([^"]+)"/.exec(head) || [])[1];
      if (!id) return;
      const n = node(id);
      let m;
      const attr = /([a-z-]+)="([^"]*)"/g;
      while ((m = attr.exec(head))) n.attrs[m[1]] = m[2];
      n.className = (/class="([^"]*)"/.exec(head) || ["", ""])[1];
      nodes[id] = n;
    });
  }

  const el = (id) => (nodes[id] = nodes[id] || node(id));
  return { el, nodes, fields, focusedId: () => focused };
}

function makeDocument(log) {
  const listeners = [];
  return {
    listeners,
    addEventListener(type, handler) { listeners.push({ type, handler }); log.push("listen:" + type); },
    querySelectorAll() { return []; },
    fire(type, event) {
      listeners.filter((l) => l.type === type).forEach((l) => l.handler(event));
    },
  };
}

/** A hand-cranked clock, so "the save is debounced" is observable rather than timed. */
function makeClock() {
  let due = [];
  return {
    setTimeout: (f) => { due.push({ f, live: true }); return due.length; },
    clearTimeout: (id) => { if (due[id - 1]) due[id - 1].live = false; },
    armed: () => due.filter((t) => t.live).length,
    fire: () => { const now = due; due = []; now.forEach((t) => { if (t.live) t.f(); }); },
  };
}

const scope = new Function("$", "TW", "SB", "document", "window", "clock", "fetch", `
  "use strict";
  var setTimeout = clock.setTimeout, clearTimeout = clock.clearTimeout;
  ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
  ${grab(/^  var B = window\.TWPolishBid;[^\n]*$/m, "the window.TWPolishBid binding")}
  ${grab(/^  var CONDITIONS = \[[\s\S]*?\n  \];$/m, "CONDITIONS")}
  ${grab(/^  var DEFAULT_CONDITIONS = [^\n]*;$/m, "DEFAULT_CONDITIONS")}
  // Added 2026-09-03 with the cell map. adoptModel() and save() both reach for it now,
  // and a const the lifted function cannot see is a ReferenceError at boot, not a
  // product bug -- which is the whole reason grab() names what it is looking for.
  //
  // Repointed 2026-09-15: the map moved into polish-bid-core.js, because the Review step became a
  // second writer of these same five cells and two copies is how the two screens drift. This line
  // is now an alias, and it resolves through the window.TWPolishBid binding lifted above --
  // which is why that grab has to stay ahead of this one.
  ${grab(/^  var CONDITION_CELLS = B\.CONDITION_CELLS;$/m, "CONDITION_CELLS")}
  // Added 2026-09-11 with the four carry-through toggles, and down to ONE of them since
  // 2026-09-16 -- dye, joint filler and remove-existing moved onto the Takeoff step and into the
  // model, leaving reno, which still cannot live there. NO BACKTICKS IN THIS COMMENT, and none in
  // any of its neighbours: every line from here to the return below is inside the template literal
  // that builds the page's scope, so a quoted identifier ends the string and node reports a
  // SyntaxError pointing at a line nobody touched. Same rule as the cell map above: the
  // list, the helpers over it AND the carry binding all have to be in this scope, because
  // adoptModel/conditionCells/switchHtml every one of them reaches for it and a name the lifted
  // function cannot see is a ReferenceError at boot -- which is what happened first try.
  ${grab(/^  var CARRY_CONDITIONS = \[[\s\S]*?\n  \];$/m, "CARRY_CONDITIONS")}
  ${grab(/^  var COUNTY_LIMIT = [^\n]*$/m, "COUNTY_LIMIT")}
  var state = {};
  var M = null;
  var form = null;
  // Who settled each of the five. A real binding rather than a stub: a click through onClick has
  // to land in humanConditions, which is what stops a second verbal run overriding it.
  var humanConditions = {};
  // The carried conditions' on/off -- Renovation alone since 2026-09-16. A real binding, not a
  // stub, for the same reason humanConditions is: a click has to land in it and adoptModel has to
  // reassign it, and a probe that read a stub would agree with itself instead of with the page.
  var carry = {};
  var saveTimer = null;
  var counties = [];
  var countyMatches = [];
  var countyHighlight = -1;
  var countyPick = null;
  ${fn("allConditions")}
  ${fn("carrySpec")}
  ${fn("condOn")}
  ${fn("hasDependents")}
  ${fn("adoptModel")}
  ${fn("conditionCells")}
  ${fn("isCondition")}
  ${fn("switchHtml")}
  ${fn("renderConditions")}
  ${fn("paintCondition")}
  ${fn("repaintCondition")}
  ${fn("toggleCondition")}
  ${fn("loadCounties")}
  ${fn("countyStateOf")}
  ${fn("countyRowRate")}
  ${fn("countyRowLabel")}
  ${fn("filterCounties")}
  ${fn("closeCountyResults")}
  ${fn("renderCountyResults")}
  ${fn("paintCountyHighlight")}
  ${fn("countyKeys")}
  ${fn("pickCounty")}
  ${fn("clearCounty")}
  ${fn("countyNoteText")}
  ${fn("renderCountyNote")}
  ${fn("hydrateCounty")}
  ${fn("paintProjLine")}
  ${fn("onCountyInput")}
  ${fn("onCountyKeydown")}
  ${fn("saveSoon")}
  ${fn("save")}
  ${fn("paintSaveBlocked")}
  ${fn("hydrate")}
  ${fn("onClick")}
  ${fn("onSubmit")}
  ${fn("wire")}
  ${fn("boot")}
  return { boot: boot, save: save, saveSoon: saveSoon, toggleCondition: toggleCondition,
           renderConditions: renderConditions, adoptModel: adoptModel, hydrate: hydrate,
           onClick: onClick, onSubmit: onSubmit, CONDITIONS: CONDITIONS,
           DEFAULT_CONDITIONS: DEFAULT_CONDITIONS, COUNTY_LIMIT: COUNTY_LIMIT,
           CONDITION_CELLS: CONDITION_CELLS, conditionCells: conditionCells,
           CARRY_CONDITIONS: CARRY_CONDITIONS, carry: function () { return carry; },
           loadCounties: loadCounties, countyKeys: countyKeys,
           model: function () { return M; }, state: function () { return state; },
           countyPick: function () { return countyPick; } };
`);

// ── a project, with the calculator's own work already on it ───────────────────
// The calculator's own v2 shapes, not an approximation of them. A model that says version 2 while
// carrying v1-shaped rows is not a model the calculator would ever write, and testing against one
// hides the normalisation migrateModel actually performs: it replaces a non-array `labor` with the
// seeded rows, so an object here would look like "the save deleted my crew" for the wrong reason.
const TAKEOFF = [
  { assembly_id: "asm-sp", assembly_name: "Salt & Pepper polish", measurement: 12500, unit: "SF" },
  { assembly_id: "asm-edge", assembly_name: "Edge grind", measurement: 900, unit: "LF" },
];
const LABOR = [
  { id: "polishing", label: "Polishing", guys: 4, days: 3, rate: 32.2 },
  { id: "mockup", label: "Mock-up", guys: 3, days: 0.5, rate: 32.2 },
];

function blob(over) {
  return Object.assign({
    __draft_id: "proj-1",
    project_name: "Nearman Creek",
    address: "1 Water Works Dr",
    city: "Kansas City", state: "KS", zip: "66101",
    bid_date: "2026-09-01",
    contact_name: "Kyle", contact_email: "kyle@example.com",
    polish_estimate: {
      version: 2,
      takeoff: JSON.parse(JSON.stringify(TAKEOFF)),
      labor: JSON.parse(JSON.stringify(LABOR)),
      conditions: { local: true, hard_bid: false, prevailing_wage: false,
                    taxable: true, remodel_tax: false },
    },
  }, over || {});
}

const FORM_VALUES = {
  project_name: "Nearman Creek", address: "1 Water Works Dr",
  city: "Kansas City", state: "ks", zip: "66101", bid_date: "2026-09-01",
  contact_name: "Kyle", contact_email: "kyle@example.com",
};

function build(opts) {
  opts = opts || {};
  const log = [];
  const rec = { saves: [], written: [], navigated: [], fetched: [], flushed: 0 };
  const store = { blob: JSON.parse(JSON.stringify(opts.blob === undefined ? blob() : opts.blob)),
                  id: opts.id || "proj-1" };
  const dom = makeDom(log, opts.formValues || FORM_VALUES);
  const doc = makeDocument(log);

  const TW = {
    getState: () => JSON.parse(JSON.stringify(store.blob)),
    setState: (partial) => {
      rec.saves.push(JSON.parse(JSON.stringify(partial)));
      store.blob = Object.assign(store.blob, JSON.parse(JSON.stringify(partial)));
      return store.blob;
    },
    readForm: () => Object.assign({}, opts.formValues || FORM_VALUES),
    writeForm: (f, values) => { rec.written.push({ isForm: f === dom.nodes["intake-form"],
                                                   values: values }); },
    withDraft: (p) => p + (p.indexOf("?") >= 0 ? "&" : "?") + "d=" + store.id,
    getDraftId: () => store.id,
    draftReady: Promise.resolve(),
    authHeaders: () => ({}),
    resolveApiBase: () => "",
    // The pagehide flush in wire() calls both of these. saveBlocked defaults to "answered" (null)
    // so every existing test keeps seeing a hidden #save-note unless a test opts into the
    // foreign-blob case via opts.saveBlockedReason -- mirrors the real shared.js contract.
    flushState: () => { rec.flushed++; },
    saveBlocked: () => (opts.saveBlockedReason || null),
  };

  const SB = {
    enterSandbox: async function (adoptFn) {
      log.push("sandbox:in");
      await new Promise((r) => setImmediate(r));      // it settles over two real fetches
      if (opts.copyBlob) {
        store.blob = JSON.parse(JSON.stringify(opts.copyBlob));
        store.id = "proj-1-beta";
        adoptFn(JSON.parse(JSON.stringify(opts.copyBlob)));
      }
      log.push("sandbox:out");
      return opts.sandboxOk !== false;
    },
    repointWizardLinks: function () { log.push("repoint"); },
    markNewProjectAsTest: function () { log.push("markTest"); },
  };

  const clock = makeClock();
  const winListeners = [];
  const win = {
    TWAuth: { ready: Promise.resolve() },
    // The REAL pricing core, under the real global name. The page's own
    // `var B = window.TWPolishBid` line is lifted below, so renaming the global breaks this
    // harness instead of quietly leaving B undefined at runtime.
    TWPolishBid: P,
    location: { href: "https://x/polish-intake.html?d=proj-1",
                assign: (u) => rec.navigated.push(u) },
    // wire() registers its own pagehide flush directly on window (mirrors shared.js's own net
    // at shared.js:513) -- exposed so a test can fire it like a real tab close/switch.
    listeners: winListeners,
    addEventListener(type, handler) { winListeners.push({ type, handler }); },
    fire(type, event) { winListeners.filter((l) => l.type === type).forEach((l) => l.handler(event)); },
  };
  // The ONLY source of the county list. Nothing is seeded into the page, so a hardcoded table in
  // polish-intake.js would show up here as a search that works with the fetch never called.
  const fetchStub = async function (url, init) {
    rec.fetched.push({ url: String(url), headers: (init || {}).headers || null });
    // Reference data is a READ. A method or a body here would mean this page had started writing
    // through a path that bypasses the sandbox's draft check entirely.
    if (init && init.method) throw new Error("the intake page must not " + init.method + " " + url);
    if (init && init.body) throw new Error("the intake page must not send a body to " + url);
    return { ok: true, json: async () => ({ counties: JSON.parse(JSON.stringify(COUNTIES)) }) };
  };

  const api = scope(dom.el, TW, SB, doc, win, clock, opts.countyFetchFails
    ? async function (url) { rec.fetched.push({ url: String(url), failed: true });
                             throw new Error("reference data is down"); }
    : fetchStub);
  return { api, dom, doc, win, TW, SB, clock, log, rec, store };
}

/** The switches as they were rendered: key, label, why, whether the track is on, and whether it
 *  is greyed out. */
function readSwitches(markup) {
  return String(markup).split('<div class="sw').slice(1).map((chunk) => {
    // The rest of the class attribute, tokenised rather than prefix-matched. A dependent switch
    // greys itself with `inert`, so "sw on inert" has to keep reading as ON; the old prefix test
    // matched the first word and would have called that switch off -- a harness bug that would
    // have looked exactly like a page bug.
    //
    // NO SWITCH ON THIS FORM IS INERT TODAY: Remove existing joint filler was the only one, and it
    // moved to the Takeoff step on 2026-09-16. The tokeniser stays because it is the correct way
    // to read a class list whatever is in it, and because CARRY_CONDITIONS is a list somebody will
    // add a `needs` to again -- at which point this reading has to already be right, not be
    // rediscovered by watching a green test describe an off switch that is on.
    const rest = (/^([^"]*)"/.exec(chunk) || ["", ""])[1];
    const words = rest.split(/\s+/).filter(Boolean);
    return {
      key: (/data-cond="([^"]*)"/.exec(chunk) || [])[1] || null,
      id: (/id="([^"]*)"/.exec(chunk) || [])[1] || null,
      on: words.indexOf("on") >= 0,
      inert: words.indexOf("inert") >= 0,
      cls: ["sw"].concat(words).join(" "),
      ariaChecked: (/aria-checked="([^"]*)"/.exec(chunk) || [])[1] || null,
      label: (/<span class="t">([^<]*)</.exec(chunk) || [])[1] || null,
      why: (/<span class="c">([^<]*)</.exec(chunk) || [])[1] || null,
      hasTrack: /<span class="track">/.test(chunk),
      // The cell chips came off with the step. B4/B5/D5/B6/D6 must not be back.
      namesACell: /class="cell"/.test(chunk),
    };
  });
}

/** Fire the page's own delegated click listener at one switch. */
function clickSwitch(built, key) {
  const el = built.dom.nodes["cond-" + key];
  if (!el) throw new Error("nothing was rendered with id cond-" + key);
  built.doc.fire("click", { target: el });
  return el;
}

/** Fire the page's own delegated click listener at any element it rendered, by id. */
function clickId(built, id) {
  const el = built.dom.nodes[id];
  if (!el) throw new Error("nothing was rendered with id " + id);
  built.doc.fire("click", { target: el });
  return el;
}

/** Fire a listener the page attached to one of its own elements. */
function fireOn(built, id, type, event) {
  const el = built.dom.nodes[id];
  if (!el) throw new Error("the page never reached for #" + id);
  const hits = el.listeners.filter((l) => l.type === type);
  if (!hits.length) throw new Error("#" + id + " has no " + type + " listener — wire() forgot it");
  hits.forEach((l) => l.handler(event || {}));
}

/** Type into the search box the way an estimator does: set the value, then let the page's own
 *  `input` handler see it. */
function typeCounty(built, text) {
  built.dom.nodes["county-input"].value = text;
  fireOn(built, "county-input", "input");
  return readCountyRows(built);
}

/** The county rows as they were rendered: id, index, name and the rate line. */
function readCountyRows(built) {
  const box = built.dom.nodes["county-results"];
  return String((box && box.innerHTML) || "").split('<div class="c-row').slice(1).map((chunk) => ({
    id: (/id="([^"]*)"/.exec(chunk) || [])[1] || null,
    idx: (/data-county="([^"]*)"/.exec(chunk) || [])[1] || null,
    name: (/<span class="c-name">([^<]*)</.exec(chunk) || [])[1] || null,
    rate: (/<span class="c-rate">([^<]*)</.exec(chunk) || [])[1] || null,
  }));
}

/** Which rendered row currently carries the keyboard cursor, by index. */
function highlightedRow(built) {
  const rows = readCountyRows(built);
  for (let i = 0; i < rows.length; i++) {
    const el = built.dom.nodes["county-row-" + i];
    if (el && / on$/.test(el.className)) return i;
  }
  return -1;
}

/** What the county field is showing, all of it, in one object. */
function readCountyField(built) {
  const n = built.dom.nodes;
  return {
    input: n["county-input"] ? n["county-input"].value : null,
    note: n["county-note"] ? n["county-note"].textContent : null,
    resultsHidden: n["county-results"] ? n["county-results"].hidden : null,
    clearShown: !!n["county-clear"] && n["county-clear"].hidden === false,
  };
}

/** What markupChain charges for the remodel tax, given a save this page wrote.
 *
 *  TWO calls on purpose, and the pair is the point. The engine documents `null` ("nobody has said
 *  which county" → stand the Kansas state rate up) and an explicit `0` ("we know, and it is
 *  nothing" → Missouri exempts remodel labor) as DIFFERENT inputs. js/polish-estimate.js hands it
 *  `B.num(state.county_remodel_rate)`, which flattens both to 0. So `raw` is the engine's contract
 *  and `asWired` is what a beta bid is actually charged today; where they disagree, the disagreement
 *  belongs in the open rather than inside one number.
 */
function enginePcts(save) {
  const call = (rate) => P.markupChain({
    material: 10000, labor: 20000, sf: 10000,
    conditions: save.polish_estimate.conditions, remodel_rate: rate,
  }).remodel_pct;
  return { raw: call(save.county_remodel_rate), asWired: call(P.num(save.county_remodel_rate)) };
}

/** The four draft keys off a recorded save. */
function countyOf(save) {
  return { county: save.county, county_tax_rate: save.county_tax_rate,
           county_remodel_rate: save.county_remodel_rate, county_notes: save.county_notes };
}

// Everything the page ever painted, across every scenario below. The remodel rate the workbook
// hardcodes must not appear in any of it — see the note on out.rendered.
const RENDERED = [];
function snap(built) {
  ["conditions", "county-results", "county-note", "proj-line"].forEach((id) => {
    const n = built.dom.nodes[id];
    if (!n) return;
    RENDERED.push(String(n.innerHTML || "") + " " + String(n.textContent || ""));
  });
}

// The keys the PRICING engine reads. freshModel() is where markupChain's conditions come from, so
// a toggle the page renders under any other name is a toggle that moves no money.
const out = { coreKeys: Object.keys(P.freshModel().conditions) };

(async function () {
  // ── the five toggles, from the data the page ships ──────────────────────────
  {
    const b = build();
    await b.api.boot();
    const rendered = readSwitches(b.dom.nodes["conditions"].innerHTML);
    out.conditions = {
      pageKeys: b.api.CONDITIONS.map((c) => c.key),
      defaults: b.api.DEFAULT_CONDITIONS,
      rendered,
      // Every switch keeps its plain-English line, and none of them names a worksheet cell.
      allHaveWhy: rendered.every((s) => s.why && s.why.length > 12),
      allAreSwitches: rendered.every((s) => s.hasTrack),
      noCellChips: rendered.every((s) => !s.namesACell),
    };

    // A brand-new project has no model at all: the documented defaults have to come from
    // somewhere, and "somewhere" is not the estimate page.
    const fresh = build({ blob: { __draft_id: "new-1" } });
    await fresh.api.boot();
    out.conditions.freshRender = readSwitches(fresh.dom.nodes["conditions"].innerHTML)
      .map((s) => [s.key, s.on]);

    // A v1 model — {areas: […]} with no `version` — carries conditions in the same shape.
    const v1 = build({ blob: { __draft_id: "v1", polish_estimate: {
      areas: [{ name: "Bay", sf: 1000 }],
      conditions: { local: false, prevailing_wage: true } } } });
    await v1.api.boot();
    out.conditions.v1Render = readSwitches(v1.dom.nodes["conditions"].innerHTML)
      .map((s) => [s.key, s.on]);
  }

  // ── renovation, the one condition this page still carries ───────────────────
  //
  // THREE OF THE FOUR LEFT THIS BLOCK ON 2026-09-16. Dye, joint filler and remove-existing moved
  // onto the Takeoff step, and into freshModel().conditions with it, so their probe is about the
  // MODEL now and lives in the next block. What is left is `reno` on its own, and it is still
  // here for the reason the other three no longer are: migrateModel() whitelists condition keys
  // against freshModel().conditions and drops the rest, and `reno` is not one of them. So it
  // cannot live on the model, cell_values is its one home, and the only way to see what lands in
  // it is to run the writer.
  {
    const b = build();
    await b.api.boot();
    // A save this page makes for an UNRELATED reason, BEFORE Renovation is ever touched. Both its
    // cells still have to come out of it, carrying the word "New" rather than a blank.
    clickSwitch(b, "prevailing_wage");
    b.clock.fire();
    const untouched = b.rec.saves[b.rec.saves.length - 1];
    const before = b.rec.saves.length;
    clickSwitch(b, "reno");
    b.clock.fire();
    const afterReno = b.rec.saves[b.rec.saves.length - 1];
    out.carry = {
      keys: b.api.CARRY_CONDITIONS.map((c) => c.key),
      flippedInCarry: b.api.carry().reno,
      notInTheModel: !("reno" in b.api.model().conditions),
      savedOnce: b.rec.saves.length - before === 1,
      // BOTH literals, and BOTH cells, on EVERY save -- not only the save that touched it. A page
      // that wrote Renovation only when Renovation was clicked would leave Kyle's
      // IF(B10="New",0.05,0.15) reading a blank on a brand-new project, which takes the Reno
      // branch and triples the patch material rate with nothing on screen to say so.
      offCells: {
        "Epoxy!B10": untouched.cell_values["Epoxy!B10"],
        "Polish!B10": untouched.cell_values["Polish!B10"],
      },
      onCells: {
        "Epoxy!B10": afterReno.cell_values["Epoxy!B10"],
        "Polish!B10": afterReno.cell_values["Polish!B10"],
      },
      // The engine five still land in both homes, unchanged by any of this.
      engineCells: {
        "Epoxy!B4": afterReno.cell_values["Epoxy!B4"],
        "Polish!B4": afterReno.cell_values["Polish!B4"],
        "Epoxy!B6": afterReno.cell_values["Epoxy!B6"],
      },
      savedConditionKeys: Object.keys(afterReno.polish_estimate.conditions),
      takeoffKept: (afterReno.polish_estimate.takeoff || []).length,
      // What the calculator gets handed back on the next load. `reno` must be absent from it --
      // that is migrateModel's whitelist doing its job, and the reason cell_values is its home.
      readBackConditionKeys: Object.keys(
        P.migrateModel(JSON.parse(JSON.stringify(afterReno.polish_estimate))).conditions),
    };

    // MOVES NO MONEY -- ASKED OF THE ENGINE, NOT OF THE TWO SAVES. Comparing the model this page
    // wrote before the flip with the one it wrote after would be vacuous by construction: `reno`
    // is not a model key, so those two objects are equal whatever happens on screen, and the
    // comparison would stay green after somebody taught markupChain to read it. So the probe adds
    // the key to the saved conditions and prices both. In the workbook B10 really does move a
    // price -- Polish!C17 reads it -- but the beta prices from the Items & Assemblies library, and
    // polish-bid-core.js has no notion of renovation at all.
    const priced = (conds) => P.markupChain({ sf: 12500, material: 8000, labor: 30000,
                                              conditions: conds, remodel_rate: null });
    // ONE CONDITION VECTOR IS A HIDING PLACE, so the pair is priced twice. The save above has
    // Prevailing wage ON, because flipping it is what triggered the save -- and a branch written
    // as `prevailing_wage || reno` moves no money at all while prevailing wage is on. Pricing the
    // same pair again with the engine six turned the other way takes that hiding place away:
    // whichever half a masked read is hiding behind, one of the two runs has it the other way.
    const ENGINE = ["local", "hard_bid", "prevailing_wage", "taxable", "remodel_tax", "bond"];
    const invert = (conds) => ENGINE.reduce(
      (acc, k) => { acc[k] = !acc[k]; return acc; }, Object.assign({}, conds));
    const withReno = (conds) => Object.assign({}, conds, { reno: true });
    const same = (conds) =>
      JSON.stringify(priced(conds)) === JSON.stringify(priced(withReno(conds)));
    out.carry.priceIdentical = same(afterReno.polish_estimate.conditions);
    out.carry.priceIdenticalInverted = same(invert(afterReno.polish_estimate.conditions));
    out.carry.priceTotal = priced(afterReno.polish_estimate.conditions).total;

    // And it comes back off its cell on the next load, because it has nowhere else to come back
    // from. "Reno" rather than "New", so a hydrate that quietly fell through to the documented
    // default cannot produce the same screen.
    const h = build({ blob: { __draft_id: "reno-from-cells", cell_values: {
      "Epoxy!B10": "Reno", "Polish!B10": "Reno" } } });
    await h.api.boot();
    out.carry.hydrated = readSwitches(h.dom.nodes["conditions"].innerHTML)
      .map((sw) => [sw.key, sw.on]);
  }

  // ── THE THREE THAT MOVED STILL REACH THE WORKBOOK FROM HERE ─────────────────
  //
  // THIS IS THE RISK THE 2026-09-16 MOVE CARRIES, and this block is the only place a test can see
  // it. Dye, joint filler and remove-existing used to be written into cell_values by this page's
  // own `carry` loop, from this page alone. That loop is gone. Nothing on screen would notice if
  // nothing had replaced it: the questions would still be ASKED (on Takeoff), still be SAVED (on
  // the model) and still be shown back there -- and Polish!E25/E29/F29 would quietly go blank in
  // every workbook a save from THIS page touched. A blank Yes/No cell is not "No" to Kyle's
  // formulas, it is whatever his IF() falls through to, so the bid would come back wrong with the
  // screen still right.
  //
  // What replaced the loop is B.conditionCellWrites -- the one writer both screens call, driven by
  // M.conditions. So the probe has to be a round trip through the product: answer them on the
  // OTHER screen, arrive here, save for an unrelated reason, and read the cells that came out.
  {
    /** One visit to this page by a project whose three moved answers were settled on Takeoff.
     *
     *  Saved by touching a DIFFERENT switch, which is both the realistic visit and the only one
     *  that proves anything: the estimator came back to fix the address or to set Prevailing wage,
     *  not to re-answer these. A page that wrote a condition cell only when that condition was
     *  clicked would sail through a test that clicked it. */
    const visitAfterTakeoff = async (id, answers) => {
      const pg = build({ blob: { __draft_id: id, polish_estimate: {
        version: 2, takeoff: [], labor: [],
        conditions: Object.assign({ local: true, hard_bid: false, prevailing_wage: false,
                                    taxable: true, remodel_tax: false, bond: false },
                                  answers) } } });
      await pg.api.boot();
      clickSwitch(pg, "prevailing_wage");
      pg.clock.fire();
      return { page: pg, wrote: pg.rec.saves[pg.rec.saves.length - 1] };
    };

    // As Kyle's sheet ships: joint filler on, the other two off.
    const shipped = await visitAfterTakeoff("takeoff-as-shipped",
      { dye: false, joint_filler: true, remove_existing_jf: false });
    // All three the other way. Remove-existing is YES while joint filler is OFF, which is exactly
    // the combination the Takeoff step dims -- and a dimmed switch's answer still has to reach the
    // workbook, because dimming says "this moves no money here", not "nobody answered".
    const flipped = await visitAfterTakeoff("takeoff-all-flipped",
      { dye: true, joint_filler: false, remove_existing_jf: true });
    // Nothing to remove, and nothing to do the removing. F29's "No" here is the write a tidy-up
    // deletes on the grounds that it changes nothing; it is the one that must not go missing.
    const nothing = await visitAfterTakeoff("takeoff-nothing-to-remove",
      { dye: false, joint_filler: false, remove_existing_jf: false });

    const CELLS = ["Polish!E25", "Polish!E29", "Polish!F29"];
    const KEYS = ["dye", "joint_filler", "remove_existing_jf"];
    // PRESENT, not merely equal to "No". Once a key stops being written, `undefined` is what every
    // downstream reader sees, and it is falsy in exactly the places "No" is -- so the way this
    // fails is invisible to a check that only compares values.
    const written = (save) => CELLS.filter(
      (c) => Object.prototype.hasOwnProperty.call(save.cell_values, c));
    const literals = (save) => CELLS.reduce(
      (acc, c) => { acc[c] = save.cell_values[c]; return acc; }, {});

    out.moved = {
      shippedCells: literals(shipped.wrote),
      flippedCells: literals(flipped.wrote),
      nothingCells: literals(nothing.wrote),
      shippedWritten: written(shipped.wrote),
      flippedWritten: written(flipped.wrote),
      nothingWritten: written(nothing.wrote),
      // ON THE MODEL NOW, which is the inversion this change made. They were deliberately kept OFF
      // it before -- migrateModel would have dropped them -- and the whole move was into it.
      inTheModel: KEYS.filter((k) => k in shipped.page.api.model().conditions),
      savedConditions: shipped.wrote.polish_estimate.conditions,
      // AND THEY SURVIVE THE READ-BACK. migrateModel whitelists against freshModel().conditions,
      // which is the exact mechanism that used to drop them. Run over the blob the page just
      // saved rather than a hand-built one, so this is the trip the estimator's next visit takes.
      readBack: KEYS.map((k) => [k, P.migrateModel(
        JSON.parse(JSON.stringify(flipped.wrote.polish_estimate))).conditions[k]]),
      // The intake form no longer renders any of the three. Asked rather than assumed, because
      // "they moved" is only true if they left.
      stillOnScreen: readSwitches(shipped.page.dom.nodes["conditions"].innerHTML)
        .map((sw) => sw.key).filter((k) => KEYS.indexOf(k) >= 0),
    };

    // MOVES NO MONEY, AND THAT IS A NEW RISK RATHER THAN AN OLD REASSURANCE. Until today these
    // three were physically incapable of changing the beta price: they were not on the model, and
    // the model is what markupChain() is handed. They are on it now, so "they price nothing" has
    // stopped being a fact about the data shape and become a claim about the engine -- proven here
    // over two saves this page really wrote, which differ in nothing but these three keys.
    const priced = (conds) => P.markupChain({ sf: 12500, material: 8000, labor: 30000,
                                              conditions: conds, remodel_rate: null });
    out.moved.priceIdentical =
      JSON.stringify(priced(shipped.wrote.polish_estimate.conditions)) ===
      JSON.stringify(priced(flipped.wrote.polish_estimate.conditions));
    out.moved.priceTotal = priced(shipped.wrote.polish_estimate.conditions).total;
    // ONE CONDITION VECTOR IS A HIDING PLACE, so the pair is priced twice. Both saves have
    // Prevailing wage ON, because flipping it is what triggered them -- and a branch written as
    // `prevailing_wage || joint_filler` moves no money at all while prevailing wage is on.
    // Pricing the same pair again with the engine six turned the other way takes that hiding place
    // away: whichever half a masked read is hiding behind, one of the two runs has it the other
    // way round. Found by mutation: the first version of this probe stayed green with the engine
    // reading joint_filler.
    const ENGINE = ["local", "hard_bid", "prevailing_wage", "taxable", "remodel_tax", "bond"];
    const invert = (conds) => ENGINE.reduce(
      (acc, k) => { acc[k] = !acc[k]; return acc; }, Object.assign({}, conds));
    out.moved.priceIdenticalInverted =
      JSON.stringify(priced(invert(shipped.wrote.polish_estimate.conditions))) ===
      JSON.stringify(priced(invert(flipped.wrote.polish_estimate.conditions)));
    // NOT A VACUOUS PAIR. The two saved condition sets have to really disagree about these three,
    // or "the price did not move" is a statement about two identical inputs.
    out.moved.pricedInputsDiffer = KEYS.filter(
      (k) => shipped.wrote.polish_estimate.conditions[k] !==
             flipped.wrote.polish_estimate.conditions[k]);

    // ── and they come back off their cells, through the SAME loop the engine five use ──
    // Their read-back used to be a second loop, over CARRY_CONDITIONS, sitting next to the engine
    // five's. It is one loop over CONDITION_CELLS now, which is what makes "the cell wins where
    // there is one" true of all eight rather than of five. A draft with cells and no model at all
    // is the case that proves the loop runs: every answer here is the opposite of freshModel's.
    const fromCells = build({ blob: { __draft_id: "moved-from-cells", cell_values: {
      "Polish!E25": "Yes", "Polish!E29": "No", "Polish!F29": "Yes" } } });
    await fromCells.api.boot();
    out.moved.hydrated = KEYS.map((k) => [k, fromCells.api.model().conditions[k]]);
  }

  // ── the caret, which a browser walk found once already ──────────────────────
  //
  // repaintCondition has two paths: repaint ONE element's class, or re-render the whole block and
  // put the caret back afterwards. The block path exists because Joint filler changed the SENTENCE
  // inside Remove existing joint filler, and greying is a class on a sibling rather than on the
  // switch that was clicked -- and both of those left this form on 2026-09-16, taking the only
  // `needs` rule in CARRY_CONDITIONS with them.
  //
  // WHAT THAT LEAVES WORTH PINNING is the cheap path, which is now the only one this form can
  // take: a switch flipped here must not throw away a caret the estimator tabbed somewhere else.
  // The block branch is kept rather than deleted because the rule it implements is generic and
  // CARRY_CONDITIONS is a list somebody will add to again; what is recorded here is that no entry
  // currently asks for it.
  {
    const b = build();
    await b.api.boot();
    // The estimator has tabbed to Local job and is reading it. The click below lands somewhere
    // else entirely, the way a mouse does.
    b.dom.nodes["cond-local"].focus();
    const beforeFlip = b.dom.nodes["conditions"].innerHTML;
    clickSwitch(b, "taxable");
    b.clock.fire();
    out.caret = {
      // Nothing on this form greys itself out because of another switch, so nothing takes the
      // re-render path. Read off the real list rather than asserted in a comment.
      dependsOn: b.api.CARRY_CONDITIONS.map((c) => c.needs || null).filter(Boolean),
      focusUnmoved: b.dom.focusedId(),
      // The container is deliberately NOT re-rendered, so its string still carries the pre-click
      // markup while the element itself has had its class repainted in place.
      containerUntouched: beforeFlip === b.dom.nodes["conditions"].innerHTML,
      elementRepainted: b.dom.nodes["cond-taxable"].className,
    };
  }

  {
    // ── AN ANSWER GIVEN ON THE REVIEW STEP SURVIVES ARRIVING HERE ────────────
    // The exact blob the Estimate page writes when its Sales tax switch is turned off: the model
    // says taxable=false AND the cell says "No", because that page writes both. Before it wrote
    // the cell, the model said false, Epoxy!B6 still said "Yes", and this page's cell-wins rule
    // handed the estimator their old answer straight back -- then save() rewrote the model from
    // it, making the revert permanent.
    const fromReview = build({ blob: { __draft_id: "review-said-no",
      polish_estimate: { version: 2, takeoff: [], labor: [],
        conditions: { local: true, hard_bid: false, prevailing_wage: false,
                      taxable: false, remodel_tax: false, bond: false } },
      cell_values: { "Epoxy!B4": "Yes", "Polish!B4": "Yes", "Epoxy!B5": "No", "Polish!B5": "No",
                     "Epoxy!D5": "No", "Epoxy!B6": "No", "Epoxy!D6": "No" } } });
    await fromReview.api.boot();
    const rt = readSwitches(fromReview.dom.nodes["conditions"].innerHTML);
    out.roundTrip = {
      taxableOnScreen: (rt.filter((sw) => sw.key === "taxable")[0] || {}).on,
      model: fromReview.api.model().conditions.taxable,
    };

    // And the half that made the revert PERMANENT: this page's own save must not put the old
    // answer back. Driven by touching a DIFFERENT switch, which is the realistic visit -- the
    // estimator came here to set Prevailing wage, not to re-answer Sales tax.
    clickSwitch(fromReview, "prevailing_wage");
    fromReview.clock.fire();
    const wrote = fromReview.rec.saves[fromReview.rec.saves.length - 1] || {};
    out.roundTrip.savedModel = ((wrote.polish_estimate || {}).conditions || {}).taxable;
    out.roundTrip.savedCell = (wrote.cell_values || {})["Epoxy!B6"];
    out.roundTrip.theOtherOneLanded =
      ((wrote.polish_estimate || {}).conditions || {}).prevailing_wage;

    // THE COUNTERFACTUAL, so this pair cannot pass vacuously. The same visit with the cell still
    // saying "Yes" -- which is exactly what a Review step that wrote only the model would leave
    // behind -- must show the revert. If this does not disagree with the case above, the cell-wins
    // rule is not actually running and the assertions prove nothing.
    const stale = build({ blob: { __draft_id: "review-said-no-cell-stale",
      polish_estimate: { version: 2, takeoff: [], labor: [],
        conditions: { local: true, hard_bid: false, prevailing_wage: false,
                      taxable: false, remodel_tax: false, bond: false } },
      cell_values: { "Epoxy!B6": "Yes" } } });
    await stale.api.boot();
    out.roundTrip.revertsWhenCellNotWritten =
      stale.api.model().conditions.taxable === true;
  }

  // ── clicking one flips the model, queues a save, and keeps the siblings ─────
  {
    const b = build();
    await b.api.boot();
    const before = b.rec.saves.length;
    const el = clickSwitch(b, "prevailing_wage");
    const queued = { model: b.api.model().conditions.prevailing_wage,
                     armed: b.clock.armed(), savedYet: b.rec.saves.length - before };
    b.clock.fire();
    const save = b.rec.saves[b.rec.saves.length - 1];
    out.toggle = {
      flippedInTheModel: queued.model,
      // Debounced, like the calculator's: armed, not sent, until the timer runs.
      debounced: queued.armed === 1 && queued.savedYet === 0,
      savedOnce: b.rec.saves.length - before === 1,
      savedValue: save.polish_estimate.conditions.prevailing_wage,
      // THE REGRESSION. takeoff and labor live under the same key; a save that replaced the
      // object instead of merging into it would delete a finished takeoff to record one toggle.
      takeoffKept: JSON.stringify(save.polish_estimate.takeoff),
      laborKept: JSON.stringify(save.polish_estimate.labor),
      versionKept: save.polish_estimate.version,
      // The other four are untouched by flipping the third.
      siblingConditions: [["local", save.polish_estimate.conditions.local],
                          ["hard_bid", save.polish_estimate.conditions.hard_bid],
                          ["taxable", save.polish_estimate.conditions.taxable],
                          ["remodel_tax", save.polish_estimate.conditions.remodel_tax]],
      workType: save.work_type,
      cityState: save.city_state,
      // The switch that was clicked shows it, on the element renderConditions produced.
      repaintedOn: el.className,
      repaintedAria: el.getAttribute("aria-checked"),
    };

    // Off again, and the model + the class go back.
    clickSwitch(b, "prevailing_wage");
    b.clock.fire();
    out.toggle.flipsBack = b.rec.saves[b.rec.saves.length - 1]
      .polish_estimate.conditions.prevailing_wage;
    out.toggle.repaintedOff = b.dom.nodes["cond-prevailing_wage"].className;

    // Two flips inside one debounce window send ONE save carrying both.
    const c = build();
    await c.api.boot();
    const n = c.rec.saves.length;
    clickSwitch(c, "hard_bid");
    clickSwitch(c, "remodel_tax");
    c.clock.fire();
    out.toggle.coalesced = c.rec.saves.length - n;
    const last = c.rec.saves[c.rec.saves.length - 1].polish_estimate.conditions;
    out.toggle.coalescedBoth = last.hard_bid === true && last.remodel_tax === true;
  }

  // ── a model whose only content is a takeoff ─────────────────────────────────
  // Deliberately WITHOUT a conditions object: the defaults have to be filled in without
  // disturbing what is already there.
  {
    const b = build({ blob: { __draft_id: "t1", project_name: "Takeoff only",
      polish_estimate: { takeoff: JSON.parse(JSON.stringify(TAKEOFF)),
                         labor: JSON.parse(JSON.stringify(LABOR)) } } });
    await b.api.boot();
    clickSwitch(b, "taxable");
    b.clock.fire();
    const save = b.rec.saves[b.rec.saves.length - 1];
    out.takeoffOnly = {
      takeoff: JSON.stringify(save.polish_estimate.takeoff),
      labor: JSON.stringify(save.polish_estimate.labor),
      taxable: save.polish_estimate.conditions.taxable,
      local: save.polish_estimate.conditions.local,
    };
  }

  // ── THE SEAM: a brand-new project, handed to the calculator ─────────────────
  //
  // This is the one case neither page can test on its own, and it was broken. A new beta project
  // has NO polish_estimate at all, so this page writes the first one. If that blob goes out
  // without a version, two silent failures follow on the very next click: the calculator's
  // migrateModel reads it as unrecognised and replaces the estimator's toggles with defaults, and
  // backend/drafts.py — which decides "resume this project on the beta intake" by reading
  // polish_estimate.version — sends the project back to the spreadsheet intake instead.
  //
  // So the assertion is a ROUND TRIP: what this page saved, read back through the real
  // polish-bid-core the calculator prices with.
  {
    const b = build({ blob: { __draft_id: "brand-new", project_name: "Fresh beta job" } });
    await b.api.boot();
    clickSwitch(b, "prevailing_wage");
    clickSwitch(b, "taxable");
    b.clock.fire();
    const saved = b.rec.saves[b.rec.saves.length - 1].polish_estimate;
    const readBack = P.migrateModel(JSON.parse(JSON.stringify(saved)));
    out.seam = {
      savedVersion: saved.version,
      savedConditions: saved.conditions,
      readBackConditions: readBack.conditions,
      // What backend/drafts.py._polish_beta() is handed. PostgREST gives it back as text.
      routingFlagSees: saved.version === undefined ? null : String(saved.version),
    };
  }

  // ── Continue ───────────────────────────────────────────────────────────────
  {
    const b = build();
    await b.api.boot();
    const n = b.rec.saves.length;
    let prevented = false;
    b.dom.nodes["intake-form"].listeners
      .filter((l) => l.type === "submit")
      .forEach((l) => l.handler({ preventDefault: () => { prevented = true; } }));
    out.continue_ = {
      wired: b.dom.nodes["intake-form"].listeners.some((l) => l.type === "submit"),
      prevented,
      navigated: b.rec.navigated,
      // Saved on the way out, not left on the 600ms timer that a navigation would kill.
      savedBeforeLeaving: b.rec.saves.length - n === 1,
      savedConditions: b.rec.saves.length > n
        ? !!b.rec.saves[b.rec.saves.length - 1].polish_estimate.conditions : false,
    };
  }

  // ── Fault 1, the actual bug: typing must arm the debounce ──────────────────────
  //
  // wire() had no `input` listener at all -- see wire()'s own comment. NAMED fields only: the
  // county box has no `name`, and its keystrokes are a search (onCountyInput), not a draft
  // edit -- a listener that could not tell them apart would save on every character typed while
  // searching for a county, which is not what the county note is supposed to govern.
  {
    const b = build();
    await b.api.boot();
    b.dom.nodes["intake-form"].listeners
      .filter((l) => l.type === "input")
      .forEach((l) => l.handler({ target: { name: "project_name" } }));
    const armedOnNamedField = b.clock.armed();
    b.clock.fire();

    const c = build();
    await c.api.boot();
    c.dom.nodes["intake-form"].listeners
      .filter((l) => l.type === "input")
      .forEach((l) => l.handler({ target: c.dom.nodes["county-input"] }));  // the real element,
                                                                             // no `name` attribute
    out.typing = {
      wired: b.dom.nodes["intake-form"].listeners.some((l) => l.type === "input"),
      armedOnNamedField,
      savedFromTyping: b.rec.saves.length,
      quietOnCountyInput: c.clock.armed(),
    };
  }

  // ── Fault 3: nothing flushed the 600ms timer before a tab close/switch ─────────────
  //
  // shared.js's OWN pagehide net only flushes a timer THIS page armed -- see shared.js:513 -- and
  // before the fix nothing here ever armed one from typing at all. wire() now pushes a save
  // through synchronously and forces the network flush, rather than trusting the 600ms window.
  {
    const b = build();
    await b.api.boot();
    b.dom.nodes["intake-form"].listeners
      .filter((l) => l.type === "input")
      .forEach((l) => l.handler({ target: { name: "project_name" } }));
    const armedBeforeLeaving = b.clock.armed();
    b.win.fire("pagehide");
    out.pagehideFlush = {
      wired: b.win.listeners.some((l) => l.type === "pagehide"),
      armedBeforeLeaving,
      savedSynchronously: b.rec.saves.length,       // save() ran inline, not on the timer
      armedAfterLeaving: b.clock.armed(),            // the timer it cleared
      flushedTheNetwork: b.rec.flushed,              // TW.flushState(), forcing the PUT now
    };

    // Nothing typed, nothing armed: leaving must not manufacture a save out of thin air.
    const d = build();
    await d.api.boot();
    d.win.fire("pagehide");
    out.pagehideFlush.quietWhenNothingArmed = d.rec.saves.length === 0 && d.rec.flushed === 0;
  }

  // ── Fault 2 made visible: a refused cross-tab write now says so ──────────────────
  //
  // shared.js silently refuses a write when another tab has re-stamped the shared blob onto a
  // different draft -- a console.warn only, nothing an estimator can see. TW.saveBlocked() names
  // the reason; paintSaveBlocked() is what now puts it on screen, in a note separate from
  // #sandbox-note (the test-copy identity banner, which must never be clobbered by this).
  {
    const b = build({ saveBlockedReason: "foreign-blob" });
    await b.api.boot();
    clickSwitch(b, "taxable");
    b.clock.fire();
    const blocked = b.dom.nodes["save-note"];

    const c = build();
    await c.api.boot();
    clickSwitch(c, "taxable");
    c.clock.fire();
    const clear = c.dom.nodes["save-note"];

    out.saveBlockedNote = {
      shownWhenBlocked: blocked.hidden === false,
      textMentionsAnotherTab: /another tab/i.test(blocked.textContent),
      hiddenWhenNotBlocked: clear.hidden === true,
    };
  }

  // ── nothing renders before the sandbox settles ──────────────────────────────
  {
    const b = build();
    await b.api.boot();
    const paints = b.log.filter((e) => /^(html|show|text|class|listen):/.test(e));
    out.bootOrder = {
      log: b.log,
      sandboxFirst: b.log.indexOf("sandbox:out") < b.log.indexOf(paints[0]),
      anyPaintBeforeSandbox: b.log.slice(0, b.log.indexOf("sandbox:in"))
        .some((e) => /^(html|show|text|class|listen):/.test(e)),
      repointedAfterSandbox: b.log.indexOf("repoint") > b.log.indexOf("sandbox:out"),
      loadingHidden: b.dom.nodes["loading"].hidden,
      mainShown: b.dom.nodes["main"].hidden === false,
    };

    // The sandbox could not settle safely: the page stays where it is. Rendering the form anyway
    // would offer an estimator a box to type a real customer's job into.
    const stopped = build({ sandboxOk: false });
    await stopped.api.boot();
    out.bootOrder.stopped = {
      renders: stopped.log.filter((e) => /^(html|show|text|class|listen):/.test(e)),
      // Never even asked for: an element the page never reached for was never un-hidden.
      mainStillHidden: !stopped.dom.nodes["main"] || stopped.dom.nodes["main"].hidden !== false,
      noListeners: stopped.doc.listeners.length === 0,
      formNeverRead: stopped.rec.written.length === 0,
      nothingSaved: stopped.rec.saves.length,
    };
  }

  // ── the sandbox switched drafts: the COPY is what gets rendered ─────────────
  {
    const b = build({ copyBlob: { __draft_id: "proj-1-beta",
      project_name: "Nearman Creek (beta test)", city: "Bonner Springs", state: "KS",
      beta_sandbox_of: "proj-1",
      // The cell-borne answers, in the only place the copy states them. Both are the OPPOSITE of
      // the documented default, so "the page read the copy" and "the page read nothing" cannot
      // produce the same screen.
      //
      // THE TWO NOW LAND IN DIFFERENT PLACES, which is why the probe below reads both. Renovation
      // comes back into the `carry` binding and shows as a switch; joint filler came off this form
      // on 2026-09-16 and comes back onto M.conditions instead, where it is invisible to the
      // rendered block. adoptModel reassigns BOTH bindings, and a page that switched drafts mid-
      // boot and only re-read one of them would carry the source project's answer into the copy's
      // workbook with nothing on screen to show for it.
      cell_values: { "Epoxy!B10": "Reno", "Polish!B10": "Reno", "Polish!E29": "No" },
      polish_estimate: { takeoff: [{ area: "Copy bay", sf: 500 }],
                         conditions: { local: false, hard_bid: true, prevailing_wage: false,
                                       taxable: true, remodel_tax: false } } } });
    await b.api.boot();
    out.copyAdopted = {
      // The form is hydrated from the copy, not from the project that was clicked.
      hydratedFrom: b.rec.written.length ? b.rec.written[0].values.project_name : null,
      hydratedIntoTheForm: b.rec.written.length ? b.rec.written[0].isForm : false,
      projLine: b.dom.nodes["proj-line"].textContent,
      rendered: readSwitches(b.dom.nodes["conditions"].innerHTML).map((s) => [s.key, s.on]),
      // The half of the re-read that no longer shows on this screen. Polish!E29 says "No" on the
      // copy and joint filler ships ON, so a model still carrying the source project's answer is
      // the visible failure -- visible here, that is, and nowhere on the page.
      //
      // COPIED, NOT REFERENCED. api.model() hands back the page's LIVE M, and the remodel_tax
      // click below mutates it in place -- so a bare reference here is serialised at the end of
      // the run, after the click, and reports a condition this line never saw. Everything else in
      // this file reads out of rec.saves, which build() already deep-copies; this is the one probe
      // that reaches into the page's own object.
      modelConds: JSON.parse(JSON.stringify(b.api.model().conditions)),
    };
    // And a save lands on the copy's model, with the copy's takeoff intact.
    clickSwitch(b, "remodel_tax");
    b.clock.fire();
    const save = b.rec.saves[b.rec.saves.length - 1];
    out.copyAdopted.savedTakeoff = JSON.stringify(save.polish_estimate.takeoff);
    out.copyAdopted.savedRemodel = save.polish_estimate.conditions.remodel_tax;
    out.copyAdopted.savedHardBid = save.polish_estimate.conditions.hard_bid;
  }

  // ── the bid date defaults to today, and a stated one is left alone ──────────
  {
    const b = build({ formValues: Object.assign({}, FORM_VALUES, { bid_date: "" }) });
    await b.api.boot();
    out.bidDate = { defaulted: b.dom.fields.bid_date.value };

    const kept = build();
    kept.dom.fields.bid_date.value = "2026-12-24";
    await kept.api.boot();
    out.bidDate.keptWhatWasThere = kept.dom.fields.bid_date.value;
  }

  // ── a stray data-cond invents nothing ──────────────────────────────────────
  {
    const b = build();
    await b.api.boot();
    const before = JSON.stringify(b.api.model().conditions);
    b.doc.fire("click", { target: { attrs: { "data-cond": "made_up" },
      getAttribute: (k) => (k === "data-cond" ? "made_up" : null),
      closest: function (sel) { return sel === "[data-cond]" ? this : null; } } });
    out.strayKey = { unchanged: JSON.stringify(b.api.model().conditions) === before,
                     armed: b.clock.armed() };
    // A click on something that is not a switch at all must be a quiet no-op.
    b.doc.fire("click", { target: { closest: () => null } });
    out.strayKey.plainClickIsQuiet = b.clock.armed() === 0;
  }

  // ── the county, and the real remodel-tax rate ───────────────────────────────
  //
  // Kyle's workbook hardcodes the remodel tax at 10%. That is not a real rate anywhere: Kansas
  // charges sales tax on commercial remodel LABOR at the state rate plus the county portion, which
  // is 7.975% in Johnson County. Hanz, 2026-08-18: "For the Remodel tax please use the real state
  // tax or city tax, DONT USE 10%". markupChain() takes `remodel_rate` as an input, and this field
  // is where it comes from — so what is executed here is: the list arrives from the API, a search
  // narrows it, a click writes the four keys the live estimate screen also writes, and the note on
  // screen says what that does to the price.
  out.ksStateRate = P.RATES.KS_STATE;
  out.johnsonKs = JOHNSON_KS;

  {
    const b = build();
    await b.api.boot();
    // The list is not on the page. It arrives from GET /api/reference/counties, and until it does
    // there is nothing to match — a hardcoded copy in the page would search fine right here.
    const beforeLoad = typeCounty(b, "johnson");
    await b.api.loadCounties();

    const rows = typeCounty(b, "johnson");
    const ksIdx = rows.map((r) => r.name).indexOf("Johnson County, KS");
    if (ksIdx < 0) throw new Error("the picker never offered Johnson County, KS for 'johnson'");

    const before = b.rec.saves.length;
    clickId(b, "county-row-" + ksIdx);
    const queued = { armed: b.clock.armed(), savedYet: b.rec.saves.length - before };
    b.clock.fire();
    const save = b.rec.saves[b.rec.saves.length - 1];

    out.county = {
      // Where the rows came from, and what the page sent to get them.
      fetched: b.rec.fetched,
      searchedBeforeTheListArrived: beforeLoad.length,
      // Both Johnsons are real and they charge different rates, so the picker has to offer both.
      offeredForJohnson: rows.map((r) => [r.name, r.rate]),
      clicked: rows[ksIdx].name,
      // THE FOUR KEYS.
      keys: countyOf(save),
      // Through the page's own debounced save, like every other write on this form.
      debounced: queued.armed === 1 && queued.savedYet === 0,
      savedOnce: b.rec.saves.length - before === 1,
      // THE MERGE REGRESSION, from the county's direction this time: the pick shares one save with
      // the calculator's model, and that model must arrive intact.
      takeoffKept: JSON.stringify(save.polish_estimate.takeoff),
      laborKept: JSON.stringify(save.polish_estimate.labor),
      versionKept: save.polish_estimate.version,
      conditionsKept: save.polish_estimate.conditions,
      field: readCountyField(b),
    };

    // The consequence, with the toggle off and then on. Same county, two different sentences,
    // because with Remodel tax off the county is not moving any money yet.
    clickSwitch(b, "remodel_tax");
    b.clock.fire();
    out.county.noteWithRemodelOn = readCountyField(b).note;
    out.county.remodelRateReachedTheDraft =
      b.rec.saves[b.rec.saves.length - 1].county_remodel_rate;
    // The whole point of the field, priced through the real engine: 7.975% on the bid, not 10%.
    out.county.enginePct = enginePcts(b.rec.saves[b.rec.saves.length - 1]);

    // The cap: "county" matches every row in the table, and the box offers a typed-down list
    // rather than a scrollable copy of the whole thing.
    out.county.cappedRows = typeCounty(b, "county").length;
    out.county.cap = b.api.COUNTY_LIMIT;
    snap(b);
  }

  // ── a Missouri county ───────────────────────────────────────────────────────
  // MO rows carry no `remodel_rate` and that is CORRECT, not missing data: Missouri remodel labor
  // is generally exempt. The note has to say so, and the key has to stay null rather than being
  // filled in with a Kansas number.
  {
    const b = build();
    await b.api.boot();
    await b.api.loadCounties();
    // Searched by TOWN, which is what is on the drawing set. Warrensburg is in Johnson County, MO.
    const rows = typeCounty(b, "warrensburg");
    if (!rows.length) throw new Error("searching the notes for a town found nothing");
    clickId(b, "county-row-0");
    b.clock.fire();
    out.countyMo = {
      offered: rows.map((r) => [r.name, r.rate]),
      keys: countyOf(b.rec.saves[b.rec.saves.length - 1]),
      noteWithRemodelOff: readCountyField(b).note,
    };
    clickSwitch(b, "remodel_tax");
    b.clock.fire();
    out.countyMo.noteWithRemodelOn = readCountyField(b).note;
    // What the ENGINE charges on this bid, priced through the real module the calculator prices
    // with, off the keys this page just wrote. A Missouri job must not be charged a Kansas rate.
    out.countyMo.enginePct = enginePcts(b.rec.saves[b.rec.saves.length - 1]);
    snap(b);
  }

  // ── Remodel tax on, no county ───────────────────────────────────────────────
  // The engine falls back to the Kansas state rate. The page has to say which rate that is, and
  // must never offer the workbook's 10% as an alternative.
  {
    const b = build();
    await b.api.boot();
    out.countyFallback = { noteWithRemodelOff: readCountyField(b).note };
    clickSwitch(b, "remodel_tax");
    b.clock.fire();
    const save = b.rec.saves[b.rec.saves.length - 1];
    out.countyFallback.note = readCountyField(b).note;
    out.countyFallback.field = readCountyField(b);
    // Nothing invented on the draft: no county was picked, so no rate was written.
    out.countyFallback.keys = countyOf(save);
    // And the rate the engine stands up for that draft — the number the note on screen promises.
    out.countyFallback.enginePct = enginePcts(save);
    snap(b);
  }

  // ── hydration: the county was picked on the LIVE estimate screen ────────────
  // The four keys are that screen's own. A project that chose its county there has to show it here,
  // or the estimator picks it a second time — and an unrelated toggle on this page must not wipe it.
  {
    const picked = { county: "Wyandotte County, KS", county_tax_rate: 0.01,
                     county_remodel_rate: 0.075, county_notes: "KCK, Bonner Springs." };
    const b = build({ blob: blob(Object.assign({}, picked, { polish_estimate: {
      version: 2, takeoff: JSON.parse(JSON.stringify(TAKEOFF)),
      labor: JSON.parse(JSON.stringify(LABOR)),
      conditions: { local: true, hard_bid: false, prevailing_wage: false,
                    taxable: true, remodel_tax: true } } })) });
    await b.api.boot();
    out.countyHydrated = { field: readCountyField(b) };
    // An unrelated toggle, whose save rewrites the whole blob.
    clickSwitch(b, "hard_bid");
    b.clock.fire();
    out.countyHydrated.keysAfterAnUnrelatedToggle = countyOf(b.rec.saves[b.rec.saves.length - 1]);

    // Hydration reads the DRAFT, not the API: with reference data down the field still shows the
    // county this project chose. Anything else would look like the county had been lost.
    const down = build({ countyFetchFails: true, blob: blob(picked) });
    await down.api.boot();
    await down.api.loadCounties();
    out.countyHydrated.withReferenceDataDown = readCountyField(down).input;
    out.countyHydrated.searchWithReferenceDataDown = typeCounty(down, "johnson").length;
    snap(b);
  }

  // ── the keyboard, and Clear ─────────────────────────────────────────────────
  {
    const b = build();
    await b.api.boot();
    await b.api.loadCounties();
    typeCounty(b, "johnson");
    const openedOnTyping = b.dom.nodes["county-results"].hidden === false;
    let prevented = 0;
    const steps = [];
    const press = (key) => {
      fireOn(b, "county-input", "keydown", { key, preventDefault: () => { prevented++; } });
      steps.push(highlightedRow(b));
    };
    press("ArrowDown"); press("ArrowDown"); press("ArrowUp"); press("ArrowDown");
    const before = b.rec.saves.length;
    press("Enter");
    b.clock.fire();
    out.countyKeyboard = {
      openedOnTyping,
      highlightSteps: steps,
      preventedDefaults: prevented,
      picked: countyOf(b.rec.saves[b.rec.saves.length - 1]).county,
      savedOnce: b.rec.saves.length - before === 1,
      closedAfterPick: b.dom.nodes["county-results"].hidden,
      // Enter inside the form must NEVER reach the submit handler while the list is open: that
      // handler navigates to the estimate, and the estimator was choosing a row.
      navigated: b.rec.navigated,
    };

    // Escape closes without choosing anything.
    typeCounty(b, "wyandotte");
    const savesBeforeEscape = b.rec.saves.length;
    fireOn(b, "county-input", "keydown", { key: "Escape", preventDefault: () => {} });
    b.clock.fire();
    out.countyKeyboard.escapeClosed = b.dom.nodes["county-results"].hidden;
    out.countyKeyboard.escapeSaved = b.rec.saves.length - savesBeforeEscape;
    // The abandoned search is put back to the county that is actually saved, rather than left
    // showing "wyandotte" on a draft that says Johnson.
    out.countyKeyboard.escapeRestoredTheField = readCountyField(b).input;

    // Clear puts the four keys back to empty — the same shape a project that never picked one has.
    typeCounty(b, "johnson");
    clickId(b, "county-clear");
    b.clock.fire();
    out.countyClear = {
      keys: countyOf(b.rec.saves[b.rec.saves.length - 1]),
      field: readCountyField(b),
    };
    snap(b);
  }

  // ── the list closes when you click away, and not when you click into it ─────
  {
    const b = build();
    await b.api.boot();
    await b.api.loadCounties();
    typeCounty(b, "johnson");
    // The page's own markup puts data-county-keep on the input; test_..._page.py pins that, so this
    // stand-in is not making the attribute up.
    b.dom.nodes["county-input"].attrs["data-county-keep"] = "";
    b.doc.fire("click", { target: b.dom.nodes["county-input"] });
    out.countyOutside = { openAfterClickingTheBox: b.dom.nodes["county-results"].hidden === false };
    b.doc.fire("click", { target: { closest: () => null } });
    out.countyOutside.closedAfterClickingAway = b.dom.nodes["county-results"].hidden;
    // Nothing was ever chosen, so the abandoned search text does not stay in the box pretending to
    // be a county.
    out.countyOutside.inputAfterClickingAway = readCountyField(b).input;
    out.countyOutside.savedNothing = b.clock.armed();
    snap(b);
  }

  // Every string the page painted, in every scenario above. The workbook's flat 10% must not be in
  // any of it — not as a rate, not as an "or", not as a leftover from the sheet's own wording.
  out.rendered = RENDERED;

  // ── EXECUTED: the real sandbox module, on this page's real pill links ───────
  //
  // Not the stub used above — frontend/js/polish-sandbox.js itself, run over the anchors parsed out
  // of polish-intake.html, after shared.js's OWN rule (read out of shared.js, so it cannot drift)
  // has had its turn. That is the whole situation in one: shared.js stamps the three wizard pages
  // with the id the page opened on, skips both beta pages entirely, and the sandbox then has to
  // move all of them onto the draft it settled on.
  {
    const sbSrc = read(path.join(ROOT, "js", "polish-sandbox.js"));
    const sharedSrc = read(path.join(ROOT, "shared.js"));
    const wizardSrc = (/const _WIZARD_PATH = \/(.*)\/;/.exec(sharedSrc) || [])[1];
    if (!wizardSrc) throw new Error("_WIZARD_PATH is gone from shared.js — rewrite this block");
    const wizard = new RegExp(wizardSrc);

    // THE STEP ROW, out of the page. `<div class="progress">` … `</header>` since 2026-09-10, when
    // this page dropped its private `<nav class="steps">` for the live intake's shared shell —
    // auth.js finds the pills by that exact class and folds them into its one-line header.
    //
    // GUARDED, and that is the point of the guard rather than politeness: the old slice was
    // `indexOf(open) … indexOf(close)`, and when a markup change made both miss it returned -1 and
    // -1, `slice(-1, -1)` gave "", and `raw` came back as an empty array. The harness did not
    // crash. Every assertion downstream that compares two derived lists would then have compared
    // [] to [] and PASSED — a test that proves nothing while reporting green is worse than a red
    // one. So a slice that cannot find its ends, or that finds no pills, is a harness fault and
    // says so, in the same voice as fn() and grab() above.
    const navFrom = pageHtml.indexOf('<div class="progress">');
    const navTo = pageHtml.indexOf("</header>", navFrom);
    if (navFrom < 0 || navTo < 0) {
      throw new Error('the step row is no longer `<div class="progress">` inside <header> in ' +
        "polish-intake.html — retarget this slice, don't let it return an empty list");
    }
    const nav = pageHtml.slice(navFrom, navTo);
    const raw = (nav.match(/href="([^"]+)"/g) || []).map((h) => h.slice(6, -1));
    if (raw.length !== 3) {
      throw new Error("parsed " + raw.length + " step links out of polish-intake.html, expected 3 " +
        "— rewrite this block rather than testing an empty list");
    }

    function run(draftId, hrefs) {
      const anchors = hrefs.map((h) => {
        const a = { href: h, getAttribute: (k) => (k === "href" ? a.href : null),
                    setAttribute: (k, v) => { if (k === "href") a.href = v; } };
        return a;
      });
      const win = { location: { href: "https://x/polish-intake.html" }, history: {} };
      const doc = { querySelectorAll: (sel) => (sel === "a[href]" ? anchors : []),
                    getElementById: () => null };
      const make = new Function("window", "document", "TW", "location", "localStorage", "fetch",
        sbSrc + "\nreturn window.TWPolishSandbox;");
      const SBreal = make(win, doc, { getDraftId: () => draftId }, { origin: "https://x" },
                          { setItem() {}, getItem() { return null; } }, () => {});
      SBreal.repointWizardLinks();
      return anchors.map((a) => a.href);
    }

    // What shared.js would have left behind on this page, by its own rule.
    const stamped = raw.map((h) => (wizard.test(h.split("?")[0]) ? h + "?d=proj-1" : h));
    out.pills = {
      raw,
      stampedBySharedJs: stamped,
      afterSandbox: run("proj-1-beta", stamped),
      // No draft at all: nothing to stamp, and nothing invented.
      withNoDraft: run(null, stamped),
    };
  }

  // -- labor is not this page's to state -------------------------------------
  //
  // This page has no labor UI at all, and its save() says out loud that only `conditions` is its
  // own. It stated labor anyway until 2026-09-17, by accident: migrateModel fills a missing
  // `labor` in from freshModel() before it hands the model back, so the first save on a brand-new
  // project persisted four crew rows nobody had been shown.
  //
  // Harmless on its own, and not harmless at all in the seam: js/polish-estimate.js adds the
  // library's default labor lines to a bid whose labor has never been stated (B.laborUnstated),
  // and a model minted here had already stated it -- so "+ Add a labor line" on the library page
  // could never reach a project that started where every project starts.
  {
    // A brand-new beta project, saved by flipping a toggle, exactly as the seam probe above does.
    const fresh = build({ blob: { __draft_id: "brand-new-labor", project_name: "Fresh beta job" } });
    await fresh.api.boot();
    clickSwitch(fresh, "prevailing_wage");
    fresh.clock.fire();
    const minted = fresh.rec.saves[fresh.rec.saves.length - 1].polish_estimate;

    // Saved again, because this page saves on every keystroke and the guard reads what is ALREADY
    // SAVED. A second save that re-stated labor would close the door just as firmly as the first.
    clickSwitch(fresh, "local");
    fresh.clock.fire();
    const mintedAgain = fresh.rec.saves[fresh.rec.saves.length - 1].polish_estimate;

    // An estimator's own rows, arriving here from the calculator. Flipping a toggle on this page
    // must not touch them -- this is the guard's other direction, and the expensive one.
    const worked = build({ blob: { __draft_id: "worked-on", project_name: "Worked on",
      polish_estimate: { version: 2, takeoff: JSON.parse(JSON.stringify(TAKEOFF)),
        labor: [{ id: "polishing", label: "Polishing", guys: 4, days: 6, rate: 33 },
                { id: "lab-densify", label: "Densify", guys: 2, days: 1, rate: 55,
                  unit: "days", guys_auto: false }],
        conditions: { local: true } } } });
    await worked.api.boot();
    clickSwitch(worked, "taxable");
    worked.clock.fire();
    const kept = worked.rec.saves[worked.rec.saves.length - 1].polish_estimate;

    out.laborNotStated = {
      // The key is absent, not empty: absent is what B.laborUnstated reads as "never stated".
      mintedHasLaborKey: Object.prototype.hasOwnProperty.call(minted, "labor"),
      mintedStillHasConditions: !!minted.conditions,
      mintedVersion: minted.version,
      mintedHasTakeoff: minted.takeoff instanceof Array,
      secondSaveHasLaborKey: Object.prototype.hasOwnProperty.call(mintedAgain, "labor"),
      // THE SEAM, asked of the real core the calculator gates on.
      calculatorWouldSeed: P.laborUnstated(JSON.parse(JSON.stringify(minted))),
      calculatorWouldSeedAfterTwoSaves: P.laborUnstated(JSON.parse(JSON.stringify(mintedAgain))),
      // NOTHING IS LOST ON SCREEN: the calculator fills the display copy in from freshModel(),
      // which is what it did with the rows this page used to persist.
      readBackLabor: P.migrateModel(JSON.parse(JSON.stringify(minted))).labor
        .map((r) => [r.id, r.guys, r.rate]),
      // …and a bid that HAS been worked on is left strictly alone.
      keptHasLaborKey: Object.prototype.hasOwnProperty.call(kept, "labor"),
      keptLabor: kept.labor,
      keptCalculatorWouldSeed: P.laborUnstated(JSON.parse(JSON.stringify(kept))),
      keptTaxable: kept.conditions.taxable,
    };
  }

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err); process.exit(1); });
