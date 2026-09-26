"use strict";
/* The PRICE box as the estimator edits it, RUN rather than read.
 *
 * Hanz, 2026-09-25, on the "Hanz Fix" test project on staging: he typed "THis is a test send to
 * Hanz" under the base line and "Test again 123" under an option, and both lines got a warning mark
 * and FROZE the line's amount — the typed text had become part of the price line itself. The fix
 * keeps the estimator's words while the amount and the tax wording stay live, makes the lines he
 * types their own lines, and stops the box-wide sweep from freezing rows he never touched and from
 * deleting a saved Options heading. Every one of those is a claim about what the page's own
 * functions do to a DOM, so this lifts them out of proposal-review.js verbatim and drives them:
 *
 *   * paintLine / lineOverride — a line saved in the old frozen shape is MIGRATED the first time it
 *     is drawn: split into the line and the lines around it, today's amount and tax wording turned
 *     into markers.
 *   * syncPriceLinesIn / captureLineNode — the box sweep after a keystroke: an edit that keeps the
 *     amount stores a marker; an edit that changes the digits stores his figure and marks the line;
 *     a hidden, never-painted row is not an edit.
 *   * the Enter and Backspace/Delete handlers, lifted whole — Enter at the end of a price line makes
 *     a new line of its own below it; Backspace takes an empty one away.
 *   * priceWarnings + TWPrice.confirmOwnFigures — what Send (and Download and To Dropbox) ask.
 *   * the two base-bid pickers (2026-09-26, "the base bid was not updating"): the Estimate step's
 *     wireBidBar change handler and savers, lifted out of estimate-review.js, and the Proposal
 *     step's sidebar radios (drawn and wired by renderProposalExtras) over its real rebuildPricing,
 *     and what they keep of his words (Hanz, 2026-09-26: keep the words).
 *
 * THE DOM IS A SHIM, the same one editor-paste-and-save-harness.js uses (a full DOM lets a missing
 * binding hide behind a stub), extended with the sibling operations the typed lines need.
 *
 * Usage: node price-lines-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8").replace(/\r\n/g, "\n");
const F = require(path.join(FRONTEND, "js", "proposal-format-core.js"));
globalThis.TWPrice = require(path.join(FRONTEND, "js", "price-lines-core.js"));

function fnIn(src, name, where) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from " + where + " — rewrite this harness, don't delete it");
  const open = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}
const fn = (name) => fnIn(SRC, name, "proposal-review.js");
function topConst(name) {
  const m = new RegExp("\\n  const " + name + " =").exec(SRC);
  if (!m) throw new Error("const " + name + " is gone from proposal-review.js");
  let depth = 0;
  for (let j = m.index + m[0].length; j < SRC.length; j++) {
    const ch = SRC[j];
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (ch === ";" && depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unterminated const " + name);
}
/** A one-line string const, read as a whole LINE: topConst's ";" scan does not know it is inside
 *  a string, and _OVERRIDE_TITLE has a semicolon in it. */
function lineConst(name) {
  const m = new RegExp("\n  const " + name + " = .*").exec(SRC);
  if (!m) throw new Error("const " + name + " is gone from proposal-review.js");
  return m[0].slice(1);
}
/** A delegated keydown handler's body, by a line inside it: back to its `(e) => {`, forward to
 *  the matching brace. */
function handlerAround(anchor) {
  const i = SRC.indexOf(anchor);
  if (i < 0) throw new Error("the handler holding " + JSON.stringify(anchor) + " is gone");
  const start = SRC.lastIndexOf("(e) => {", i);
  const open = SRC.indexOf("{", start);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return "(e) => " + SRC.slice(open, j + 1);
  }
  throw new Error("unbalanced braces after " + anchor);
}

// ── the smallest DOM this code touches ───────────────────────────────────────
const Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
const unesc = (s) => String(s).replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, k) => ENTITIES[k]);
function parseStyle(css) {
  const out = {};
  for (const bit of String(css || "").split(";")) {
    const k = bit.indexOf(":");
    if (k < 0) continue;
    const name = bit.slice(0, k).trim().replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    if (name) out[name] = bit.slice(k + 1).trim();
  }
  return out;
}
function matches(el, sel) {
  return String(sel).split(",").some((one) => {
    const part = one.trim();
    if (!part) return false;
    const tag = /^[a-zA-Z][\w-]*/.exec(part);
    if (tag && el.tagName !== tag[0].toUpperCase()) return false;
    for (const m of part.matchAll(/\.([\w-]+)/g)) if (!el.classList.contains(m[1])) return false;
    for (const m of part.matchAll(/\[([\w-]+)(?:=["']?([^\]"']*)["']?)?\]/g)) {
      const have = el.attrs[m[1]];
      if (have === undefined) return false;
      if (m[2] !== undefined && String(have) !== m[2]) return false;
    }
    return true;
  });
}
class Text {
  constructor(v) { this.nodeType = Node.TEXT_NODE; this.nodeValue = String(v); this.parentNode = null; }
  get parentElement() { return this.parentNode; }
  get length() { return this.nodeValue.length; }
}
class El {
  constructor(tag) {
    this.nodeType = Node.ELEMENT_NODE;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.style = {};
    this.attrs = {};
    this.title = "";
    this._classes = new Set();
    this._listeners = {};
    const self = this;
    this.dataset = new Proxy({}, {
      set: (obj, k, v) => {
        obj[k] = v;
        self.attrs["data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())] = v;
        return true;
      },
      get: (obj, k) => obj[k],
      deleteProperty: (obj, k) => { delete obj[k]; return true; },
    });
    this.classList = {
      add: (c) => self._classes.add(c),
      remove: (c) => self._classes.delete(c),
      contains: (c) => self._classes.has(c),
      toggle: (c, on) => {
        const want = on === undefined ? !self._classes.has(c) : !!on;
        if (want) self._classes.add(c); else self._classes.delete(c);
        return want;
      },
    };
  }
  get parentElement() { return this.parentNode; }
  get children() { return this.childNodes.filter((n) => n.nodeType === Node.ELEMENT_NODE); }
  get className() { return Array.from(this._classes).join(" "); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); this.attrs.class = v; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return p.childNodes[i + 1] || null; }
  get nextElementSibling() { const p = this.parentNode; if (!p) return null; const k = p.children; return k[k.indexOf(this) + 1] || null; }
  get previousElementSibling() { const p = this.parentNode; if (!p) return null; const k = p.children; return k[k.indexOf(this) - 1] || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  insertBefore(c, ref) {
    if (!ref) return this.appendChild(c);
    if (c.parentNode) c.parentNode.removeChild(c);
    const i = this.childNodes.indexOf(ref);
    c.parentNode = this;
    this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c);
    return c;
  }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  get textContent() { return this.childNodes.map((n) => n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent).join(""); }
  set textContent(v) { while (this.childNodes.length) this.removeChild(this.childNodes[0]); if (String(v) !== "") this.appendChild(new Text(v)); }
  get innerHTML() { return this._html || ""; }
  set innerHTML(html) {
    this._html = html;
    while (this.childNodes.length) this.removeChild(this.childNodes[0]);
    const stack = [this];
    // Bare attributes too (`checked`, `selected`): the Pricing options panel's radios carry them.
    const re = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/g;
    let m;
    while ((m = re.exec(html))) {
      const top = stack[stack.length - 1];
      if (m[1]) { if (stack.length > 1) stack.pop(); }
      else if (m[2]) {
        const el = new El(m[2]);
        for (const a of m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
          const v = a[2] === undefined ? "" : unesc(a[2]);
          el.attrs[a[1]] = v;
          if (a[1] === "class") el.className = v;
          else if (a[1] === "style") el.style = parseStyle(v);
          else if (a[1] === "title") el.title = v;
          else if (a[1].startsWith("data-")) el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
        }
        // A form control's live properties, as the browser gives them.
        if (el.tagName === "INPUT") { el.value = el.attrs.value || ""; el.checked = "checked" in el.attrs; }
        top.appendChild(el);
        if (el.tagName !== "BR" && el.tagName !== "INPUT") stack.push(el);
      } else if (m[4] !== undefined) top.appendChild(new Text(unesc(m[4])));
    }
  }
  querySelector(sel) { for (const c of this.children) { if (matches(c, sel)) return c; const d = c.querySelector(sel); if (d) return d; } return null; }
  querySelectorAll(sel) { const out = []; for (const c of this.children) { if (matches(c, sel)) out.push(c); out.push(...c.querySelectorAll(sel)); } return out; }
  closest(sel) { let el = this; while (el) { if (el.nodeType === Node.ELEMENT_NODE && matches(el, sel)) return el; el = el.parentNode; } return null; }
  contains(o) { let el = o; while (el) { if (el === this) return true; el = el.parentNode; } return false; }
  addEventListener(type, f) { (this._listeners[type] = this._listeners[type] || []).push(f); }
  dispatchEvent(e) { return fire(this, e.type, e); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "style") this.style = parseStyle(v); }
  removeAttribute(k) { delete this.attrs[k]; if (k === "title") this.title = ""; }
  getAttribute(k) {
    if (k === "style") return Object.entries(this.style).map(([n, v]) => n.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase()) + ":" + v).join(";");
    return this.attrs[k] === undefined ? null : this.attrs[k];
  }
}
const window = { _listeners: {} };
function fire(node, type, props) {
  const e = Object.assign({ type, target: node, preventDefault() { this.defaulted = true; } }, props || {});
  e.type = type; e.target = e.target || node;
  for (let cur = node; cur; cur = cur.parentNode) for (const f of (cur._listeners[type] || []).slice()) f(e);
  return e;
}
class Ev { constructor(type, opts) { this.type = String(type); this.bubbles = !!(opts && opts.bubbles); this.target = null; } }

// ── the page, as proposal-review.html + the Direct epoxy template mount it ───
function page() {
  const docSurface = new El("div");
  docSurface.attrs.id = "doc-surface";
  const box = new El("div");
  box.className = "tw-txbx";
  docSurface.appendChild(box);
  const region = new El("div");
  region.className = "tw-priced-region";
  box.appendChild(region);
  const html = fs.readFileSync(path.join(FRONTEND, "proposal-review.html"), "utf8").replace(/\r\n/g, "\n");
  const a = html.indexOf('<div id="price-preview-staging"');
  const staging = html.slice(html.indexOf(">", a) + 1, html.indexOf("\n</div>\n", a));
  const holder = new El("div");
  holder.innerHTML = staging.replace(/<!--[\s\S]*?-->/g, "");
  const ids = {};
  for (const el of holder.children.slice()) { region.appendChild(el); if (el.attrs.id) ids[el.attrs.id] = el; }
  return { docSurface, box, region, ids };
}

const UNITS = [
  topConst("fmtUSD"), topConst("fmtUSDdoc"), topConst("fmtSF"), lineConst("_OVERRIDE_TITLE"),
  topConst("COMPUTED_PRICE_LINE_KEYS"), lineConst("_LIVE_TITLE"), lineConst("_MONEY_TITLE"),
  topConst("_escLine"), topConst("GYP_BASE"), topConst("LINE_SEL"),
  fn("effectiveWorkType"), fn("basePriceSystem"), fn("taxLayout"), fn("taxTreatmentMode"),
  fn("baseTaxRule"), fn("printedTaxRows"), fn("baseBidFigure"),
  fn("lineOverride"), fn("lineValue"), fn("lineCue"), fn("extraLinesHtml"), fn("lineEl"),
  fn("paintExtras"), fn("makeExtraLine"), fn("caretInto"), fn("splitPriceLine"), fn("mergePriceLine"),
  fn("paintLine"), fn("comboSystemLines"), fn("comboLinesForPayload"), fn("baseDescLabel"),
  fn("refreshPriceDisplay"), fn("renderProposalExtras"), fn("computeTokenValues"),
  fn("_ensurePov"), fn("priceRowLive"), fn("captureLineNode"), fn("captureExtrasIn"),
  fn("syncPriceLinesIn"), fn("serializeBlock"), fn("priceWarnings"),
  fn("fmtAt"), fn("segmentsOf"), fn("mergeSegs"), fn("editRuns"),
  fn("lineAt"), fn("lineAtSelection"), fn("lineTarget"), fn("editingBox"),
  // The blank lines above the Options heading and the lines typed on them: the option writer ends
  // by drawing them and the box sweep stores the typed ones, so they are part of this page too
  // (options-gap-harness.js drives their keys).
  "let templateOptionsHeadingIds = [];",
  fn("optionsGapCount"), fn("optionsGapTyped"), fn("isGapTyped"), fn("gapTypedEls"),
  fn("optionsHeadingEl"), fn("aboveOptionsGap"), fn("gapShown"), fn("paintOptionsGap"),
  fn("paintGapTyped"),
  // The pricing the page runs at init and on every base pick in its sidebar (the sidebar's radios
  // are drawn by renderProposalExtras, above, when there is an #options-panel to draw them in).
  topConst("OPTION_ONLY_ROLES"), topConst("COMBINED_BASE_ROLES"), topConst("roleOfTab"),
  topConst("isOptionOnlyTab"), topConst("inCombinedBase"), fn("baseAreaFrom"),
  /\n  const PAYLOAD_PRICING_KEYS = \[[\s\S]*?\];/.exec(SRC)[0],
  fn("pruneComputedPriceLineOverrides"), fn("syncPayloadPricing"), fn("rebuildPricing"),
].join("\n");

// ── the Estimate step's base-bid strip, out of estimate-review.js ────────────
const ER = fs.readFileSync(path.join(FRONTEND, "js", "estimate-review.js"), "utf8").replace(/\r\n/g, "\n");
/** A top-level `function name(...) {...}` of estimate-review.js, bound to `deps` by name. */
function erLift(name, deps) {
  const m = new RegExp("^function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}", "m").exec(ER);
  if (!m) throw new Error(name + "() is gone from estimate-review.js — rewrite this harness, don't stub it");
  const names = Object.keys(deps);
  return new Function(...names, m[0] + "\nreturn " + name + ";")(...names.map((k) => deps[k]));
}

/** A Base-bid pick on the Estimate step, through its REAL change handler (wireBidBar) and its real
 *  savers (persistTabState / persistBidOptions), with the page's own `state` a copy of the draft and
 *  `cellValues` the copy the page edits (`edits`: cells changed this visit). The pricing snapshot
 *  is the one thing counted rather than run: it needs the whole sheet engine, and what the Proposal
 *  step prices from on its way in is its own rebuildPricing over priced_tabs, which runs for real.
 *  `pageTabs` is the page's own tab list (`tabs`: id, role, kind); by default the priced tabs.
 *  Returns the draft as the Proposal step then reads it: the saves merged in order. */
function estimatePick(draft, pick, edits, pageTabs) {
  const state = JSON.parse(JSON.stringify(draft));
  const cellValues = Object.assign({}, state.cell_values || {}, edits || {});
  const sets = [];
  let snapshots = 0;
  const listeners = {};
  const list = { addEventListener: (type, f) => { listeners[type] = f; } };
  const deps = {
    state, cellValues, TWPrice: globalThis.TWPrice, HF: { ready: true },
    tabs: pageTabs || (state.priced_tabs || []).map((t) => ({ id: t.id, role: t.role, kind: t.kind })),
    TW: { setState: (o) => { sets.push(JSON.parse(JSON.stringify(o))); } },
    document: { getElementById: (id) => (id === "bid-options-list" ? list : null) },
    renderBidOptions: () => {}, updateTotalBarFromHF: () => {},
    snapshotLumpSumsToState: () => { snapshots++; },
  };
  deps.ensureOpt = erLift("ensureOpt", deps);
  deps.persistBidOptions = erLift("persistBidOptions", deps);
  deps.persistTabState = erLift("persistTabState", deps);
  erLift("wireBidBar", deps)();
  listeners.change({ target: { checked: true, value: pick, classList: { contains: (c) => c === "bb-base" },
                               closest: () => null } });
  const saved = Object.assign(JSON.parse(JSON.stringify(draft)), ...sets);
  return { saved, sets, snapshots, state };
}
const ENTER = handlerAround("// A PRICE line (or a line typed next to one): a new line of its own");
const BACKSPACE = handlerAround("const back = e.key === \"Backspace\", fwd = e.key === \"Delete\";");

/** One page, one draft. `st` is the draft; the page's own functions run against it. */
function build(st, opts) {
  const o = opts || {};
  const pg = page();
  const saves = [];
  // Every TW.setState the page makes, in order; queuePovSave's debounced save is one of them.
  const sets = [];
  const reloads = [];
  if (o.panel) {
    // The right-hand Pricing options panel (#options-panel): renderProposalExtras draws the
    // Base-bid radios into it and wires their real change handler.
    const panel = new El("div");
    panel.attrs.id = "options-panel";
    pg.ids["options-panel"] = panel;
  }
  const SEL = { el: null, at: [0, 0] };
  const document = {
    querySelector: (sel) => (sel === "#tb-total" ? { textContent: "$" + Number(st.proposal_lump_sum).toFixed(2) } : null),
    getElementById: (id) => pg.ids[id] || null,
    createElement: (t) => new El(t),
    createRange: () => ({ setStart(n, k) { this.n = n; this.k = k; }, collapse() {} }),
    activeElement: null,
  };
  const win = {
    getSelection: () => ({
      rangeCount: SEL.el ? 1 : 0,
      getRangeAt: () => ({ startContainer: SEL.el }),
      removeAllRanges() { SEL.el = null; },
      addRange(r) { SEL.el = r.n; SEL.at = [r.k, r.k]; },
    }),
    TWAuth: null,
  };
  const body = [
    "const RUN_KEYS = F.RUN_KEYS;",
    "const runsLength = F.runsLength;",
    UNITS,
    "const selectionRange = (el) => (SEL.el === el ? SEL.at.slice() : null);",
    "const placeSelection = (el, a, b) => { SEL.el = el; SEL.at = [a, b]; };",
    "const selectionLines = () => [];",
    "const spliceLines = () => { throw new Error('multi-line splice reached'); };",
    "const insertBreakAt = () => { throw new Error('a break was put INSIDE a price line'); };",
    "const markEdited = () => {};",
    "const paraNow = () => null;",
    "const paraAction = () => false;",
    "docSurface.addEventListener('keydown', " + ENTER + ");",
    "docSurface.addEventListener('keydown', " + BACKSPACE + ");",
    // The box sweep, as the page's delegated input handler runs it on the box.
    "docSurface.addEventListener('input', (e) => { const b = editingBox(e.target); if (b) syncPriceLinesIn(b); });",
    "return { refreshPriceDisplay, syncPriceLinesIn, computeTokenValues, priceWarnings, serializeBlock,",
    "         rebuildPricing, effectiveWorkType, renderProposalExtras, baseDescLabel };",
  ].join("\n");
  const clone = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
  const api = new Function("state", "document", "window", "form", "TW", "templateBlocks", "docSurface",
                           "focusInside", "queuePovSave", "F", "Node", "Event", "SEL", "reloadForWorkType",
                           body)(
    st, document, win, { querySelector: () => null },
    { readForm: () => ({}), setState: (x) => { sets.push(clone(x)); } }, o.blocks || null, pg.docSurface,
    () => false,
    // The page's debounced price save, fired at once: what it writes is what a step pill leaves with.
    () => { saves.push(1); sets.push({ price_overrides: clone(st.price_overrides) }); },
    F, Node, Ev, SEL,
    // The template reload a work-type change makes (Phase B). It swaps the .docx on screen; the
    // price lines are drawn by the functions above whatever template is mounted.
    () => { reloads.push(1); });
  api.pg = pg; api.saves = saves; api.SEL = SEL; api.sets = sets; api.reloads = reloads;
  /** The draft as the page leaves it: `from` with every save the page made merged in, in order
   *  (what the pagehide save and a step pill carry). */
  api.saved = (from) => Object.assign(clone(from), ...sets);
  api.key = (el, key, extra) => fire(el, "keydown", Object.assign({ key }, extra || {}));
  api.type = (el, text) => { el.textContent = text; fire(el, "input", { bubbles: true }); };
  api.lines = () => pg.region.querySelectorAll("[data-po-linekey]")
    .filter((n) => !(n.style && n.style.display === "none"))
    .map((n) => ({ key: n.dataset.poLinekey, kind: n.dataset.poKind, text: api.serializeBlock(n),
                   cls: n.className, title: n.title }));
  return api;
}

function hanzFix(over) {
  return Object.assign({
    work_type: "epoxy", audience: "Direct", project_name: "Hanz Fix",
    proposal_lump_sum: 7447, proposal_sales_tax: 96, proposal_remodel_tax: 0,
    proposal_taxable: true, proposal_remodel_on: false,
    tax_inclusion: "INCLUDED",
    priced_tabs: [], cell_values: {}, sheet_area: { epoxy_sf: 99 },
    rooms: [
      { id: "Epoxy", name: "Epoxy", is_base: true, bid: { total: 7447, sales_tax: 96, remodel: 0 } },
      { id: "Copy1", name: "Epoxy copy", is_base: false, show: true, price_mode: "total",
        system_desc: "Treadwell 3/16\" Urethne Cement With Shop Floor and Armor Top",
        option_desc: "Treadwell 3/16\" Urethne Cement With Shop Floor and Armor Top",
        base_total: 7447, bid: { total: 7696, sales_tax: 99, remodel: 0, taxable: true, remodel_on: false } },
    ],
    price_overrides: { lines: {} },
  }, over || {});
}
const OPT_LINE = "$7,696 – Treadwell 3/16\" Urethne Cement With Shop Floor and Armor Top as described above (material sales tax INCLUDED)";

const out = {};

// 1. HANZ'S OWN PROJECT, as it is saved on staging: the typed lines inside the price lines' frozen
//    overrides. Drawing it migrates both.
{
  const st = hanzFix({ price_overrides: { lines: {
    base: "$7,447 – Epoxy flooring as described above (material sales tax INCLUDED)\n\nTHis is a test send to Hanz",
    "option:Copy1": "\n\n" + OPT_LINE + "\nTest again 123",
  } } });
  const api = build(st);
  api.refreshPriceDisplay();
  out.hanzFix = { lines: api.lines(), pov: JSON.parse(JSON.stringify(st.price_overrides)), saves: api.saves.length };
  // A re-price after the migration: the lines he typed stay, and every amount follows.
  st.proposal_lump_sum = 8000;
  st.rooms[0].bid.total = 8000;
  st.rooms[1].bid.total = 8100;
  api.refreshPriceDisplay();
  out.hanzFixRepriced = api.lines();
}

// 2. AN EDIT THAT KEEPS THE AMOUNT follows the estimate; one that changes the digits keeps his.
{
  const st = hanzFix();
  const api = build(st);
  api.refreshPriceDisplay();
  const base = api.pg.ids["base-bid-row"];
  api.type(base, "$7,447 – Epoxy flooring in the warehouse only as described above (material sales tax INCLUDED)");
  out.keptAmount = { stored: st.price_overrides.lines2.base };
  st.proposal_lump_sum = 9100;
  api.refreshPriceDisplay();
  out.keptAmount.repriced = base.textContent;
  out.keptAmount.cls = base.className;
  // Switch to Broken out: the wording goes, the pre-tax figure comes, his words stay.
  st.tax_layout = "BROKEN_OUT";
  api.refreshPriceDisplay();
  out.keptAmount.broken = base.textContent;
  st.tax_layout = "ONE_LINE";
  api.refreshPriceDisplay();
  api.type(base, "$9,999 – Epoxy flooring in the warehouse only as described above (material sales tax INCLUDED)");
  api.refreshPriceDisplay();
  out.handTyped = { stored: st.price_overrides.lines2.base, shown: base.textContent,
                    cls: base.className, title: base.title,
                    warnings: api.priceWarnings().map((w) => ({ key: w.key, says: w.says, estimate: w.estimate })) };
  // What Send asks, through the one check all three ways out run (TWPrice.confirmOwnFigures),
  // over the document's own list as Continue carries it (proposal_payload.price_warnings).
  TWPrice.confirmOwnFigures({ proposal_payload: { price_warnings: api.priceWarnings() } }, "send",
                            (q) => { out.handTyped.ask = q; return false; });
}

// 3. ONE KEYSTROKE IN THE BOX DOES NOT FREEZE ROWS NOBODY TOUCHED. One line: the tax rows and the
//    Total are hidden and still hold their "$0 – …" staging text.
{
  const st = hanzFix();
  const api = build(st);
  api.refreshPriceDisplay();
  const base = api.pg.ids["base-bid-row"];
  base.textContent = base.textContent + " ";
  fire(base, "input", { bubbles: true });
  out.hiddenRows = { stored: Object.keys(st.price_overrides.lines2 || {}).sort(),
                     legacy: Object.keys(st.price_overrides.lines || {}).sort() };
}

// 4. A SAVED OPTIONS HEADING is painted from the draft and survives a keystroke elsewhere.
{
  const st = hanzFix({ price_overrides: { lines2: { heading_options: "Options & Alternates:" } } });
  const api = build(st);
  api.refreshPriceDisplay();
  const oh = api.pg.ids["options-heading"];
  const shown = oh.textContent;
  const base = api.pg.ids["base-bid-row"];
  base.textContent = base.textContent + " ";
  fire(base, "input", { bubbles: true });
  out.heading = { shown, kept: (st.price_overrides.lines2 || {}).heading_options || null };
}

// 5. ENTER AT THE END OF A PRICE LINE makes a line of its own below it; typing in it is stored
//    beside the price line, which stays untouched; Backspace on an empty one takes it away.
{
  const st = hanzFix();
  const api = build(st);
  api.refreshPriceDisplay();
  const base = api.pg.ids["base-bid-row"];
  const len = api.serializeBlock(base).length;
  api.SEL.el = base; api.SEL.at = [len, len];
  const e = api.key(base, "Enter");
  const added = base.nextElementSibling;
  out.enter = { prevented: !!e.defaulted, addedKind: added && added.dataset.poKind,
                caretInNew: api.SEL.el === added, after: JSON.parse(JSON.stringify(st.price_overrides.after || {})),
                baseStored: (st.price_overrides.lines2 || {}).base || null };
  api.type(added, "THis is a test send to Hanz");
  out.enter.typed = JSON.parse(JSON.stringify(st.price_overrides.after));
  out.enter.baseStillLive = !((st.price_overrides.lines2 || {}).base);
  // A second Enter at the end of the new line: another line below it, blank.
  api.SEL.el = added; api.SEL.at = [added.textContent.length, added.textContent.length];
  api.key(added, "Enter");
  const blank = added.nextElementSibling;
  out.enter.twoLines = JSON.parse(JSON.stringify(st.price_overrides.after));
  // Backspace at the start of the blank line: gone.
  api.SEL.el = blank; api.SEL.at = [0, 0];
  const b = api.key(blank, "Backspace");
  out.enter.backspace = { prevented: !!b.defaulted, after: JSON.parse(JSON.stringify(st.price_overrides.after)) };
  // Repainted from the draft: the typed line comes back as its own line, the base is computed.
  api.refreshPriceDisplay();
  out.enter.repainted = api.lines().filter((l) => l.key === "base");
  // Enter at the very START of an option line: a blank line above it.
  const opt = api.pg.region.querySelector('[data-po-linekey="option:Copy1"][data-po-kind="line"]');
  api.SEL.el = opt; api.SEL.at = [0, 0];
  api.key(opt, "Enter");
  out.enter.above = JSON.parse(JSON.stringify(st.price_overrides.before || {}));
}

// 6. OPTIONS FOLLOW THEIR OWN TAB, and an edited option keeps following it.
{
  const st = hanzFix({ tax_layout: "BROKEN_OUT" });
  const api = build(st);
  api.refreshPriceDisplay();
  out.brokenOptions = api.lines().filter((l) => l.key.startsWith("option:"));
  const opt = api.pg.region.querySelector('[data-po-linekey="option:Copy1"][data-po-kind="line"]');
  api.type(opt, opt.textContent.replace("as described above", "as described above, shop floor"));
  st.rooms[1].bid.total = 8696;
  api.refreshPriceDisplay();
  out.editedOption = { stored: st.price_overrides.lines2["option:Copy1"],
                       lines: api.lines().filter((l) => l.key.startsWith("option:")) };
}

// 7. A LINE BREAK THAT LANDS INSIDE A PRICE LINE by a route other than Enter at a caret (Enter over
//    a selection that spans lines, say): the text after the break is a line of its own below the
//    price line, and it survives the same keystroke's re-read of the typed lines -- which used to
//    read the page, find no such line there yet, and wipe it.
{
  const st = hanzFix();
  const api = build(st);
  api.refreshPriceDisplay();
  const base = api.pg.ids["base-bid-row"];
  api.type(base, base.textContent + "\nTyped under it");
  out.breakInside = { after: JSON.parse(JSON.stringify(st.price_overrides.after || {})),
                      base: (st.price_overrides.lines2 || {}).base || null };
  api.refreshPriceDisplay();
  out.breakInside.repainted = api.lines().filter((l) => l.key === "base").map((l) => [l.kind, l.text]);
  // The next keystroke, on the repainted page, edits it as the line it now is.
  api.type(base.nextElementSibling, "Typed under it!");
  out.breakInside.next = JSON.parse(JSON.stringify(st.price_overrides.after || {}));
}

// ═══ PICKING A DIFFERENT BASE BID ════════════════════════════════════════════════════════════
// Hanz, 2026-09-26, on staging: "I had an error in the proposal tool where the base bid was not
// updating". He picked another base tab and the proposal kept the old tab's price. Hanz Fix: Epoxy
// $7,447, its copy "Epoxy copy" $15,149, and a Polish tab -- the figures below are the sheet's own
// kind (tax-inclusive totals, each tab's own tax cells and Taxable? / Remodel Tax? answers).
const HF_TABS = [
  { id: "Epoxy", name: "Epoxy", role: "epoxy", kind: "base", total: 7447, sales_tax: 96, remodel: 0,
    taxable: true, remodel_on: false, system_desc: "Treadwell 3/16\" Urethne Cement", notes_auto: [] },
  { id: "Copy1", name: "Epoxy copy", role: "epoxy", kind: "copy", total: 15149, sales_tax: 195, remodel: 0,
    taxable: true, remodel_on: false, system_desc: "Treadwell 3/16\" Urethne Cement With Shop Floor", notes_auto: [] },
  { id: "Polish", name: "Polish", role: "polish", kind: "base", total: 9860, sales_tax: 110, remodel: 745,
    taxable: true, remodel_on: true, system_desc: "Polished Concrete, 800 grit", notes_auto: [] },
];
const clone = (x) => JSON.parse(JSON.stringify(x));
const markOf = (cls) => (/tw-money-off/.test(cls) ? "money" : /tw-po-live/.test(cls) ? "live" : "");
const priceRows = (api) => api.lines().filter((l) => ["base", "sales_tax", "remodel", "total"].includes(l.key))
  .map((l) => ({ key: l.key, kind: l.kind, text: l.text, cue: /tw-overridden/.test(l.cls), mark: markOf(l.cls) }));
/** What Continue hands /api/generate for the price box: the page's own token values, its rooms, the
 *  draft's price edits (proposal-review.js's composer builds it the same way). */
function docPayload(st, api) {
  const values = api.computeTokenValues(Object.assign({}, st));
  const remodel = Number(st.proposal_remodel_tax) || 0;
  return { work_type: api.effectiveWorkType(), audience: st.audience || "Direct", values,
           rooms: clone(st.rooms || []), price_lines: clone(st.price_lines || []),
           remodel: remodel > 0 ? [{ amount_formatted: "$" + remodel.toLocaleString("en-US") }] : [],
           price_overrides: clone(st.price_overrides || {}) };
}
/** The Proposal step opening a draft: its pricing runs, then the price box paints. */
function openProposal(draft) {
  const st = clone(draft);
  const api = build(st, { panel: true });
  api.rebuildPricing();
  api.refreshPriceDisplay();
  return { st, api, draft };
}
/** A Base-bid pick in the Proposal step's own sidebar, through its real radio handler. */
function sidebarPick(p, id) {
  const panel = p.api.pg.ids["options-panel"];
  const radio = panel.querySelectorAll("input.pr-base").find((r) => r.attrs.value === id);
  if (!radio) throw new Error("no Base-bid radio for " + id + " in the sidebar");
  radio.checked = true;
  fire(radio, "change");
  return p.api.saved(p.draft);
}
const snap = (p) => ({ base_tab_id: p.st.base_tab_id, lump: p.st.proposal_lump_sum, rows: priceRows(p.api),
                       pov: clone(p.st.price_overrides || {}), doc: docPayload(p.st, p.api),
                       warnings: p.api.priceWarnings().map((w) => ({ key: w.key, says: w.says, estimate: w.estimate })) });

// 8. A LINE FROZEN AT THE OLD BASE'S FIGURE, as Hanz Fix held it the moment the base moved: the base
//    is Epoxy copy at $15,149, the base line saved (before the live shape) with Epoxy's $7,447 and
//    the note he typed under it inside it, while Epoxy still prices at $7,447. The figure is one a
//    tab prices today, so it is the tool's: drawn once, it is live again and his note is a line of
//    its own. Broken out, the tax rows a sweep froze at Epoxy's figures follow the same way. (By
//    revision 2 Epoxy had been re-priced to $7,696; that state is block 11.)
{
  const st = hanzFix({ base_tab_id: "Copy1", proposal_lump_sum: 15149, proposal_sales_tax: 195,
    priced_tabs: clone(HF_TABS), rooms: [],
    price_overrides: { lines: {
      base: "$7,447 – Epoxy flooring as described above (material sales tax INCLUDED)\n\nTHis is a test send to Hanz",
    } } });
  const api = build(st);
  api.refreshPriceDisplay();
  out.frozenAtOldBase = { rows: priceRows(api), pov: clone(st.price_overrides),
                          warnings: api.priceWarnings().map((w) => ({ key: w.key, says: w.says })) };
  const br = hanzFix({ base_tab_id: "Copy1", proposal_lump_sum: 15149, proposal_sales_tax: 195,
    tax_layout: "BROKEN_OUT", priced_tabs: clone(HF_TABS), rooms: [],
    price_overrides: { lines: {
      base: "$7,351 – Epoxy flooring as described above\nnoted",
      sales_tax: "$96 – Material Sales Tax", total: "$7,447 – Total",
    } } });
  const bapi = build(br);
  bapi.refreshPriceDisplay();
  out.frozenAtOldBaseBroken = { rows: priceRows(bapi), pov: clone(br.price_overrides) };
  // A figure NO tab ever priced is his: kept, marked, and Send asks (Hanz: warn, then let him send).
  const own = hanzFix({ base_tab_id: "Copy1", proposal_lump_sum: 15149, proposal_sales_tax: 195,
    priced_tabs: clone(HF_TABS), rooms: [],
    price_overrides: { lines: {
      base: "$9,999 – Epoxy flooring as described above (material sales tax INCLUDED)\n\nas agreed",
    } } });
  const oapi = build(own);
  oapi.refreshPriceDisplay();
  out.frozenOwnFigure = { rows: priceRows(oapi), pov: clone(own.price_overrides),
                          cls: oapi.pg.ids["base-bid-row"].className,
                          warnings: oapi.priceWarnings().map((w) => ({ key: w.key, says: w.says, estimate: w.estimate })) };
}

// 9. BASE PICKS BOTH WAYS, on both pickers, the Proposal step reading what the Estimate step saved
//    and the other way round. Hanz, 2026-09-26: KEEP THE WORDS -- a base line he re-worded keeps
//    his words through a pick; its amount, its words for the tab's system and its tax wording are
//    the new base's. The draft starts on base Epoxy with the base line re-worded ("…, warehouse
//    only", its amount and tax wording live) and the Total re-worded ("Total, all in"), the sweep's
//    Material Sales Tax row frozen at Epoxy's figure and a phantom "$0 – Remodel Tax", both in the
//    old shape, an option line saved with lines typed inside it -- and the things no base pick
//    touches: a manual price line he re-worded, a line typed on the gap above "Options:", a
//    total-priced option he re-worded, the note he typed under the base line.
const OPT_COPY1_LEGACY = "\n\n$15,149 – Treadwell 3/16\" Urethne Cement With Shop Floor as described above (material sales tax INCLUDED)\nTest again 123";
function basePickFlow(layout) {
  const broken = layout === "BROKEN_OUT";
  const draft = hanzFix({
    base_tab_id: "Epoxy", proposal_lump_sum: 7447, proposal_sales_tax: 96, proposal_remodel_tax: 0,
    priced_tabs: clone(HF_TABS), rooms: [],
    tab_opts: { Copy1: { is_option: true, show: true, price_mode: "total" },
                Polish: { is_option: true, show: true, price_mode: "total" } },
    price_lines: [{ label: "Joint filler", amount: 1500 }],
    cell_values: { "Epoxy!E20": 2000 },
    price_overrides: {
      lines: {
        sales_tax: "$96 – Material Sales Tax", remodel: "$0 – Remodel Tax",
        "option:Copy1": OPT_COPY1_LEGACY,
      },
      lines2: {
        base: TWPrice.AMOUNT + " – Epoxy flooring as described above, warehouse only " + TWPrice.TAX,
        total: TWPrice.AMOUNT + " – Total, all in",
        "manual:0": TWPrice.AMOUNT + " – Joint filler, per plan",
        "option:Polish": TWPrice.AMOUNT + " – Polished Concrete, 800 grit, warehouse only " + TWPrice.TAX,
      },
      after: { base: ["", "THis is a test send to Hanz"] },
      before: { heading_options: ["TEST123"] },
    },
  }, {});
  if (broken) draft.tax_layout = "BROKEN_OUT";
  const flow = {};
  // (1) ESTIMATE STEP: Epoxy -> Epoxy copy, with a cell edited this visit.
  const e1 = estimatePick(draft, "Copy1", { "Epoxy!E20": 2400 });
  flow.estimate1 = { base: e1.saved.base_tab_id, snapshots: e1.snapshots,
                     cellValues: e1.saved.cell_values, pov: clone(e1.saved.price_overrides) };
  // (2) the Proposal step opens it; he types a figure of his own over the base line's amount.
  const p2 = openProposal(e1.saved);
  flow.proposal2 = snap(p2);
  const base = p2.api.pg.ids["base-bid-row"];
  p2.api.type(base, base.textContent.replace(/^\$[\d,]+/, "$15,000"));
  flow.proposal2.typed = clone(p2.st.price_overrides.lines2 || {}).base || null;
  // (3) PROPOSAL SIDEBAR: Epoxy copy -> Polish, another work type (the words for the system change
  //     too), and he leaves by a step pill: what the page saved is what the next visit reads.
  const left3 = sidebarPick(p2, "Polish");
  flow.sidebar3 = Object.assign(snap(p2), { reloads: p2.api.reloads.length,
    savedPov: clone(left3.price_overrides || {}) });
  const p3 = openProposal(left3);
  flow.revisit3 = snap(p3);
  // (4) PROPOSAL SIDEBAR again: Polish -> Epoxy. Then he types the COPY's own figure into the base
  //     line: under Epoxy it is a figure of his own.
  sidebarPick(p3, "Epoxy");
  flow.sidebar4 = snap(p3);
  const b4 = p3.api.pg.ids["base-bid-row"];
  p3.api.type(b4, b4.textContent.replace(/^\$[\d,]+/, broken ? "$14,954" : "$15,149"));
  flow.typed4 = snap(p3);
  const left4 = p3.api.saved(p3.draft);
  // (5) ESTIMATE STEP again, on what the Proposal step saved: Epoxy -> Epoxy copy. His figure is
  //     now the one a tab prices the line at, so it is the tool's again: the live amount.
  const e5 = estimatePick(left4, "Copy1");
  flow.estimate5pov = clone(e5.saved.price_overrides.lines2 || {});
  const p5 = openProposal(e5.saved);
  flow.estimate5 = snap(p5);
  return flow;
}
out.basePick = { ONE_LINE: basePickFlow("ONE_LINE"), BROKEN_OUT: basePickFlow("BROKEN_OUT") };

// 9b. THE SIDEBAR'S PICK IS SAVED. The only thing it changes here is the base line's words for the
//     system (Epoxy copy -> Polish), and rebuildPricing's save carries the base and the money, not
//     the price edits: without its own save, leaving by a step pill put the Epoxy words back under
//     the Polish base.
{
  const draft = hanzFix({ base_tab_id: "Copy1", proposal_lump_sum: 15149, proposal_sales_tax: 195,
    priced_tabs: clone(HF_TABS), rooms: [], tab_opts: {},
    price_overrides: { lines2: {
      base: TWPrice.AMOUNT + " – Epoxy flooring as described above, warehouse only " + TWPrice.TAX } } });
  const p = openProposal(draft);
  const left = sidebarPick(p, "Polish");
  const again = openProposal(left);
  out.sidebarSave = { saved: clone((left.price_overrides || {}).lines2 || {}), rows: priceRows(again.api) };
}

// 9c. A COPY MADE A MOMENT AGO AND PICKED AT ONCE on the Estimate step: priced_tabs does not hold it
//     yet (this pick is what prices it), so its role comes from the page's own tab list. A Polish
//     copy on an epoxy job: the base line's words for the system become the Polish ones.
{
  const draft = hanzFix({ base_tab_id: "Epoxy", priced_tabs: clone(HF_TABS), rooms: [], tab_opts: {},
    price_overrides: { lines2: {
      base: TWPrice.AMOUNT + " – Epoxy flooring as described above, warehouse only " + TWPrice.TAX } } });
  const pageTabs = HF_TABS.map((t) => ({ id: t.id, role: t.role, kind: t.kind }))
    .concat([{ id: "Copy2", role: "polish", kind: "copy" }]);
  const e = estimatePick(draft, "Copy2", null, pageTabs);
  out.newCopyPick = { base: e.saved.base_tab_id, lines2: clone(e.saved.price_overrides.lines2 || {}) };
}

/** The base line as the Proposal step draws it: every row keyed "base", in order, with its cue. */
const baseRows = (api) => api.lines().filter((l) => l.key === "base")
  .map((l) => ({ kind: l.kind, text: l.text, money: /tw-money-off/.test(l.cls) }));
const warned = (api) => api.priceWarnings().map((w) => ({ key: w.key, says: w.says, estimate: w.estimate }));
/** A draft picked away from its base on the Estimate step, then opened on the Proposal step. */
function pickedThenOpened(draft, pick) {
  const e = estimatePick(draft, pick);
  const p = openProposal(e.saved);
  return { pov: clone(e.saved.price_overrides), rows: baseRows(p.api), warnings: warned(p.api),
           doc: docPayload(p.st, p.api) };
}

// 10. A LINE SAVED IN THE OLD SHAPE WITH A NOTE ABOVE ITS PRICE LINE that quotes a figure. Which of
//     its lines is the price line decides what the customer reads: the note taken for it was
//     printed with the base bid's amount, and the real price line kept as a typed line frozen at
//     the old figure -- never re-priced, never forgotten on a later pick, never warned about.
{
  const PRICE = "$7,447 – Epoxy flooring as described above (material sales tax INCLUDED)";
  const legacy = (text) => hanzFix({ base_tab_id: "Epoxy", proposal_lump_sum: 7447, proposal_sales_tax: 96,
    priced_tabs: clone(HF_TABS), rooms: [], tab_opts: {}, price_overrides: { lines: { base: text } } });
  out.oldShape = {
    // (a) The Estimate step's pick, on a note carrying any figure ("Includes $500 cove allowance").
    noteAbove: pickedThenOpened(legacy("Includes $500 cove allowance\n" + PRICE), "Copy1"),
    // (b) ...and on a note that reads like a price line itself: only the tabs' figures tell them apart.
    shapedNote: pickedThenOpened(legacy("$500 – cove allowance, included in the price below\n" + PRICE), "Copy1"),
  };
  // (c) A note quoting ANOTHER TAB's own figure (Polish's $9,860), drawn on the Proposal step, then
  //     the base picked away on the Estimate step.
  const quoted = legacy("Polish alternative quoted separately at $9,860\n" + PRICE);
  const qa = build(quoted);
  qa.refreshPriceDisplay();
  out.oldShape.quotedTab = { rows: baseRows(qa), warnings: warned(qa), pov: clone(quoted.price_overrides),
                             picked: pickedThenOpened(qa.saved(quoted), "Copy1") };
  // (d) The same figure in the line's own WORDS, on a line frozen at a figure no tab prices: it is
  //     his line and his figure (marked, Send asks), and the $9,860 in his words stays $9,860.
  const inWords = hanzFix({ base_tab_id: "Copy1", proposal_lump_sum: 15149, proposal_sales_tax: 195,
    priced_tabs: clone(HF_TABS), rooms: [],
    price_overrides: { lines: {
      base: "$7,000 – Epoxy flooring, Polish alternative $9,860 (material sales tax INCLUDED)" } } });
  const wa = build(inWords);
  wa.refreshPriceDisplay();
  out.oldShape.inWords = { rows: baseRows(wa), warnings: warned(wa), pov: clone(inWords.price_overrides) };
}

// 11. HANZ FIX REVISION 5, as staging holds it (draft_revisions, 2026-09-26; product wording only):
//     the base is Epoxy copy at $15,149, and the base line was frozen at Epoxy's $7,447 in revision
//     1 -- but Epoxy had been re-priced to $7,696 by revision 2, so no tab prices $7,447 any more.
//     Nothing on the page remembers a tab's old price: the line is his, marked, and Send asks. A
//     base pick (away and back, on the Estimate step) forgets it.
{
  const REV5_TABS = [
    { id: "Epoxy", name: "Epoxy", role: "epoxy", kind: "base", total: 7696, sales_tax: 102, remodel: 0, notes_auto: [] },
    { id: "Copy1", name: "Epoxy copy", role: "epoxy", kind: "copy", total: 15149, sales_tax: 437, remodel: 0, notes_auto: [] },
    { id: "Polish", name: "Polish", role: "polish", kind: "base", total: 13585, sales_tax: 0, remodel: 0, notes_auto: [] },
    { id: "Seal", name: "Seal", role: "seal", kind: "base", total: 1476, sales_tax: 0, remodel: 0, notes_auto: [] },
    { id: "Seal (+Jnts)", name: "Seal (+Jnts)", role: "seal", kind: "base", total: 2942, sales_tax: 0, remodel: 0, notes_auto: [] },
  ];
  const rev5 = hanzFix({ base_tab_id: "Copy1", proposal_lump_sum: 15149, proposal_sales_tax: 437,
    priced_tabs: REV5_TABS, rooms: [],
    tab_opts: { Epoxy: { show: true, is_option: true, show_diff: false, price_mode: "total", show_system: true },
                Seal: { show: true, is_option: false, show_diff: false, price_mode: "total", show_system: true } },
    price_overrides: { rows: {}, combo: {}, single_bid: {}, options_gap: 1, lines: {
      base: "$7,447 – Epoxy flooring as described above (material sales tax INCLUDED)\n\nTHis is a test send to Hanz\n\n12312312312312a",
      total: "$0 – Total", remodel: "$0 – Remodel Tax", sales_tax: "$0 – Material Sales Tax",
    } } });
  const p = openProposal(rev5);
  const there = estimatePick(p.api.saved(rev5), "Epoxy").saved;
  const back = pickedThenOpened(there, "Copy1");
  out.rev5 = { rows: baseRows(p.api), warnings: warned(p.api), lines2: clone(p.st.price_overrides.lines2 || {}),
               afterPicks: { rows: back.rows, warnings: back.warnings, lines2: back.pov.lines2 || {} } };
}

// 12. DELETING THE BASE COPY changes the base too, to the one the sheet derives: the Estimate step's
//     real deleteTab (and the real resolveBaseTab it asks), then the Proposal step opens the draft.
function deleteBaseCopy(baseLine, legacyBase) {
  const draft = hanzFix({ base_tab_id: "Copy1", proposal_lump_sum: 15149, proposal_sales_tax: 195,
    priced_tabs: clone(HF_TABS), rooms: [], tab_copies: [{ id: "Copy1", role: "epoxy", source: "Epoxy" }],
    tab_labels: { Copy1: "Epoxy copy" }, tab_notes: {}, lock_overrides: {},
    tab_opts: { Copy1: {}, Polish: { is_option: true, show: true, price_mode: "total" } },
    price_lines: [{ label: "Joint filler", amount: 1500 }],
    price_overrides: Object.assign({
      lines2: Object.assign(baseLine ? { base: baseLine } : {}, {
                "manual:0": TWPrice.AMOUNT + " – Joint filler, per plan",
                "option:Polish": TWPrice.AMOUNT + " – Polished Concrete, 800 grit, warehouse only " + TWPrice.TAX,
                "option:Epoxy": TWPrice.AMOUNT + " – Epoxy as an option " + TWPrice.TAX }),
    }, legacyBase ? { lines: { base: legacyBase } } : { after: { base: NOTE_UNDER_BASE.slice() } }) });
  const state = clone(draft);
  const sets = [];
  const src = (re, what) => { const m = re.exec(ER); if (!m) throw new Error(what + " is gone from estimate-review.js"); return m[0]; };
  const deleteTab = new Function("state", "HF", "TW", "TWPrice", [
    "const BASE_ROLE = { Epoxy: 'epoxy', Polish: 'polish' }; const sheets = ['Epoxy', 'Polish'];",
    "const cellValues = {}; const sheetCache = {}; let activeSheet = 'Epoxy';",
    "const labelFor = (id) => id; const renderTabs = () => {}; const showSheet = () => {};",
    "const defaultBaseSheet = () => 'Epoxy';",
    // The tab list the page rebuilds from the draft (buildTabs), as the real one shapes it.
    "let tabs = [];",
    "function buildTabs() { tabs = sheets.map((id) => ({ id, role: BASE_ROLE[id], kind: 'base' }))",
    "  .concat(state.tab_copies.map((c) => ({ id: c.id, role: c.role || 'epoxy', kind: 'copy' }))); }",
    "buildTabs();",
    src(/^const GYP_BASE = .*$/m, "GYP_BASE"), src(/^const PRICED_ROLES = .*$/m, "PRICED_ROLES"),
    src(/^const OPTION_ONLY_ROLES = .*$/m, "OPTION_ONLY_ROLES"),
    src(/^const isOptionOnlyRole = .*$/m, "isOptionOnlyRole"), src(/^const basePricedTabs = .*$/m, "basePricedTabs"),
    src(/^const isPricedRole = .*$/m, "isPricedRole"), src(/^function pricedTabs\(\) .*$/m, "pricedTabs"),
    src(/^function resolveBaseTab\(\) \{[\s\S]*?\n\}/m, "resolveBaseTab"),
    src(/^function reKeyPriceLineOverrides\(rename\) \{[\s\S]*?\n\}/m, "reKeyPriceLineOverrides"),
    src(/^async function deleteTab\(id\) \{[\s\S]*?\n\}/m, "deleteTab"),
    "return deleteTab;",
  ].join("\n"))(state, { removeSheet() {} },
    { confirmDanger: async () => true, setState: (o) => { sets.push(clone(o)); } }, globalThis.TWPrice);
  return deleteTab("Copy1").then(() => {
    const saved = Object.assign(clone(draft), ...sets);
    // What the Estimate step's next pricing snapshot holds: the copy is gone.
    saved.priced_tabs = clone(HF_TABS).filter((t) => t.id !== "Copy1");
    const p = openProposal(saved);
    return { savedBase: saved.base_tab_id, pov: clone(saved.price_overrides), base: p.st.base_tab_id,
             rows: baseRows(p.api), warnings: warned(p.api), doc: docPayload(p.st, p.api) };
  });
}
const NOTE_UNDER_BASE = ["", "THis is a test send to Hanz"];

// 13. THE WORDS FOR THE TAB'S SYSTEM, both halves: the page's baseDescLabel (through its own
//     effectiveWorkType) and TWPrice.baseDesc, which the base-pick rule applies on either page.
{
  const rows = [];
  for (const wt of ["epoxy", "polish", "combo", "gyp", "sealer"]) {
    for (const role of ["epoxy", "polish", "gyp", "seal", ""]) {
      const st = hanzFix({ work_type: wt, base_tab_id: role ? "T" : null,
                           priced_tabs: role ? [{ id: "T", role }] : [] });
      rows.push({ wt, role, page: build(st).baseDescLabel(), core: TWPrice.baseDesc(wt, role) });
    }
  }
  out.baseDesc = rows;
}

Promise.all([
  deleteBaseCopy("$15,000 – Epoxy flooring as described above " + TWPrice.TAX),
  deleteBaseCopy(TWPrice.AMOUNT + " – Epoxy flooring, whole building incl. mezzanine " + TWPrice.TAX),
  // In the old shape, frozen at the COPY's figure, the note typed under it inside it.
  deleteBaseCopy(null, "$15,149 – Epoxy flooring as described above (material sales tax INCLUDED)\n\nTHis is a test send to Hanz"),
]).then(([money, words, frozen]) => {
  out.deleteBase = { money, words, frozen };
  console.log(JSON.stringify(out));
});
