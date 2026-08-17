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
 * Only the network's stand-in (TW + the sandbox module) and the clock are stubbed. The renders,
 * the model arithmetic, the handlers and the boot sequence are the page's own code.
 *
 * Usage: node polish-intake-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const src = fs.readFileSync(path.join(ROOT, "js", "polish-intake.js"), "utf8");
const pageHtml = fs.readFileSync(path.join(ROOT, "polish-intake.html"), "utf8");
const P = require(path.join(ROOT, "js", "polish-bid-core.js"));

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
      querySelector(sel) {
        const m = /^\[name='([^']+)'\]$/.exec(sel);
        if (m) return fields[m[1]] || null;
        return null;
      },
      querySelectorAll() { return []; },
      // What a delegated document click walks up to reach the switch it was aimed at.
      closest(sel) { return sel === "[data-cond]" && self.attrs["data-cond"] ? self : null; },
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
  return { el, nodes, fields };
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

const scope = new Function("$", "TW", "SB", "document", "window", "clock", `
  "use strict";
  var setTimeout = clock.setTimeout, clearTimeout = clock.clearTimeout;
  ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
  ${grab(/^  var B = window\.TWPolishBid;[^\n]*$/m, "the window.TWPolishBid binding")}
  ${grab(/^  var CONDITIONS = \[[\s\S]*?\n  \];$/m, "CONDITIONS")}
  ${grab(/^  var DEFAULT_CONDITIONS = [^\n]*;$/m, "DEFAULT_CONDITIONS")}
  var state = {};
  var M = null;
  var form = null;
  var saveTimer = null;
  ${fn("adoptModel")}
  ${fn("isCondition")}
  ${fn("switchHtml")}
  ${fn("renderConditions")}
  ${fn("paintCondition")}
  ${fn("toggleCondition")}
  ${fn("saveSoon")}
  ${fn("save")}
  ${fn("hydrate")}
  ${fn("onClick")}
  ${fn("onSubmit")}
  ${fn("wire")}
  ${fn("boot")}
  return { boot: boot, save: save, saveSoon: saveSoon, toggleCondition: toggleCondition,
           renderConditions: renderConditions, adoptModel: adoptModel, hydrate: hydrate,
           onClick: onClick, onSubmit: onSubmit, CONDITIONS: CONDITIONS,
           DEFAULT_CONDITIONS: DEFAULT_CONDITIONS,
           model: function () { return M; }, state: function () { return state; } };
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
  const rec = { saves: [], written: [], navigated: [] };
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
  const win = {
    TWAuth: { ready: Promise.resolve() },
    // The REAL pricing core, under the real global name. The page's own
    // `var B = window.TWPolishBid` line is lifted below, so renaming the global breaks this
    // harness instead of quietly leaving B undefined at runtime.
    TWPolishBid: P,
    location: { href: "https://x/polish-intake.html?d=proj-1",
                assign: (u) => rec.navigated.push(u) },
  };
  const api = scope(dom.el, TW, SB, doc, win, clock);
  return { api, dom, doc, TW, SB, clock, log, rec, store };
}

/** The switches as they were rendered: key, label, why, and whether the track is on. */
function readSwitches(markup) {
  return String(markup).split('<div class="sw').slice(1).map((chunk) => ({
    key: (/data-cond="([^"]*)"/.exec(chunk) || [])[1] || null,
    id: (/id="([^"]*)"/.exec(chunk) || [])[1] || null,
    on: /^ on"/.test(chunk),
    ariaChecked: (/aria-checked="([^"]*)"/.exec(chunk) || [])[1] || null,
    label: (/<span class="t">([^<]*)</.exec(chunk) || [])[1] || null,
    why: (/<span class="c">([^<]*)</.exec(chunk) || [])[1] || null,
    hasTrack: /<span class="track">/.test(chunk),
    // The cell chips came off with the step. B4/B5/D5/B6/D6 must not be back.
    namesACell: /class="cell"/.test(chunk),
  }));
}

/** Fire the page's own delegated click listener at one switch. */
function clickSwitch(built, key) {
  const el = built.dom.nodes["cond-" + key];
  if (!el) throw new Error("nothing was rendered with id cond-" + key);
  built.doc.fire("click", { target: el });
  return el;
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

  // ── EXECUTED: the real sandbox module, on this page's real pill links ───────
  //
  // Not the stub used above — frontend/js/polish-sandbox.js itself, run over the anchors parsed out
  // of polish-intake.html, after shared.js's OWN rule (read out of shared.js, so it cannot drift)
  // has had its turn. That is the whole situation in one: shared.js stamps the three wizard pages
  // with the id the page opened on, skips both beta pages entirely, and the sandbox then has to
  // move all of them onto the draft it settled on.
  {
    const sbSrc = fs.readFileSync(path.join(ROOT, "js", "polish-sandbox.js"), "utf8");
    const sharedSrc = fs.readFileSync(path.join(ROOT, "shared.js"), "utf8");
    const wizardSrc = (/const _WIZARD_PATH = \/(.*)\/;/.exec(sharedSrc) || [])[1];
    if (!wizardSrc) throw new Error("_WIZARD_PATH is gone from shared.js — rewrite this block");
    const wizard = new RegExp(wizardSrc);

    const nav = pageHtml.slice(pageHtml.indexOf('<nav class="steps">'), pageHtml.indexOf("</nav>"));
    const raw = (nav.match(/href="([^"]+)"/g) || []).map((h) => h.slice(6, -1));

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

  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err); process.exit(1); });
