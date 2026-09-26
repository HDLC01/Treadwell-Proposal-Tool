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
 *   * priceWarnings + done.js sendPriceWarning — what Send asks.
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
const DONE = fs.readFileSync(path.join(FRONTEND, "js", "done.js"), "utf8").replace(/\r\n/g, "\n");
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
    const re = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w-]+="[^"]*")*)\s*\/?>|([^<]+)/g;
    let m;
    while ((m = re.exec(html))) {
      const top = stack[stack.length - 1];
      if (m[1]) { if (stack.length > 1) stack.pop(); }
      else if (m[2]) {
        const el = new El(m[2]);
        for (const a of m[3].matchAll(/([\w-]+)="([^"]*)"/g)) {
          const v = unesc(a[2]);
          el.attrs[a[1]] = v;
          if (a[1] === "class") el.className = v;
          else if (a[1] === "style") el.style = parseStyle(v);
          else if (a[1] === "title") el.title = v;
          else if (a[1].startsWith("data-")) el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
        }
        top.appendChild(el);
        if (el.tagName !== "BR") stack.push(el);
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
  // The price box's bullets: every builder above puts a line's override on it (linePropsOf) and
  // refreshPriceDisplay ends by drawing them (paintLineParas).
  fn("linePropsOf"), fn("paintLineParas"), fn("isPriceLine"), fn("priceLineAction"),
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
].join("\n");
const ENTER = handlerAround("// A PRICE line (or a line typed next to one): a new line of its own");
const BACKSPACE = handlerAround("const back = e.key === \"Backspace\", fwd = e.key === \"Delete\";");
const SEND_WARNING = fnIn(DONE, "sendPriceWarning", "done.js");

/** One page, one draft. `st` is the draft; the page's own functions run against it. */
function build(st, opts) {
  const o = opts || {};
  const pg = page();
  const saves = [];
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
    // The Backspace handler's price-line ladder (review of fix 7, finding 6) takes a line's bullet
    // and indent off through the ribbon's own step, and then re-aims the ribbon. The step is real;
    // the ribbon is price-bullets-harness.js's, so a case here that reached it says so.
    "const fitTxbx = () => {};",
    "const showFmtBar = () => { throw new Error('showFmtBar reached: the ribbon is not modelled in price-lines-harness'); };",
    "docSurface.addEventListener('keydown', " + ENTER + ");",
    "docSurface.addEventListener('keydown', " + BACKSPACE + ");",
    // The box sweep, as the page's delegated input handler runs it on the box.
    "docSurface.addEventListener('input', (e) => { const b = editingBox(e.target); if (b) syncPriceLinesIn(b); });",
    SEND_WARNING,
    "return { refreshPriceDisplay, syncPriceLinesIn, computeTokenValues, priceWarnings, sendPriceWarning, serializeBlock };",
  ].join("\n");
  const api = new Function("state", "document", "window", "form", "TW", "templateBlocks", "docSurface",
                           "focusInside", "queuePovSave", "F", "Node", "Event", "SEL", body)(
    st, document, win, { querySelector: () => null },
    { readForm: () => ({}), setState: () => {} }, o.blocks || null, pg.docSurface,
    () => false, () => { saves.push(1); }, F, Node, Ev, SEL);
  api.pg = pg; api.saves = saves; api.SEL = SEL;
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
  out.handTyped.ask = api.sendPriceWarning(api.priceWarnings());
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

console.log(JSON.stringify(out));
