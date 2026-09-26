"use strict";
/* The blank lines above the PRICE "Options" heading, driven through the page's real key handlers.
 *
 * Hanz, 2026-09-25, in the Proposal step's price box: "I cant edit this part" / "I cant back space
 * before options". The gap above "Options:" was a 24pt top margin on the heading, so there was no
 * line to click into and nothing Backspace could take. It is now price_overrides.options_gap real
 * line elements (#options-gap), painted by paintOptionsGap and edited by onOptionsGapKey.
 *
 * WHY THIS RUNS THE CODE. Every claim is an interaction between handlers: the new capture-phase
 * key handler has to act BEFORE the page's own Enter handler, or Enter at the end of the base line
 * would write a line break into the base line's override instead of adding a gap line. A source
 * read cannot see which of two listeners ran. So the whole new section is lifted verbatim
 * (a region, so a listener nobody named is still bound), together with the page's existing Enter
 * and Backspace/Delete handlers, and real keydown events are fired through a capture-then-bubble
 * dispatch.
 *
 * THE STAGING MARKUP IS THE REAL ONE: #price-preview-staging is sliced out of proposal-review.html
 * and mounted the way REGION_MOUNTS (lifted) says, so the heading's own inline style and the order
 * the gap is mounted in are the shipped ones.
 *
 * MODELLED, NOT LIFTED: the live selection. selectionRange / placeSelection / selectionLines are
 * Range arithmetic against a real caret, which is the one thing a shim cannot do honestly (the
 * same call fmt-ribbon-harness.js and doc-editor-harness.js make). The model keeps the contract the
 * code depends on: offsets when the caret is in that line, null when it is anywhere else, and a
 * collapsed element-boundary caret for a blank line (what a click on one gives).
 *
 * Usage: node options-gap-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");
const HTML = fs.readFileSync(path.join(FRONTEND, "proposal-review.html"), "utf8")
  .replace(/\r\n/g, "\n");
const F = require(path.join(FRONTEND, "js", "proposal-format-core.js"));
// The base-bid radio hands the price edits to the ONE base-pick rule (TWPrice.applyBasePick),
// the real one.
const TWPrice = require(path.join(FRONTEND, "js", "price-lines-core.js"));

// ── lifting the real source ──────────────────────────────────────────────────
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone from proposal-review.js — rewrite this harness, don't delete it");
  const open = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}
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
function region(from, to) {
  const i = SRC.indexOf(from);
  if (i < 0) throw new Error("the block anchored on " + JSON.stringify(from) + " is gone");
  const j = SRC.indexOf(to, i);
  if (j < 0) throw new Error("the block no longer ends at " + JSON.stringify(to));
  return SRC.slice(i, j);
}

// The new section, whole: every function and BOTH listener registrations.
const GAP_SECTION = region(
  "  // ── THE BLANK LINES ABOVE THE OPTIONS HEADING",
  "  function _handlePoInput(");
// The page's own Enter handler: the one the new handler has to pre-empt.
const PAGE_ENTER = region(
  "  // Enter inside a template paragraph = ONE line break",
  "  /** Backspace at the very start of a line takes the LIST FORMATTING off");
// The base-bid radio's change handler, whole (renderProposalExtras binds it on every radio): a
// flip clears the old base's price edits, and must leave the gap and what was typed on it alone.
const FLIP_ANCHOR = 'optsPanel.querySelectorAll("input.pr-base").forEach(rb => rb.addEventListener("change", ';
const FLIP_HANDLER = (() => {
  const i = SRC.indexOf(FLIP_ANCHOR);
  if (i < 0) throw new Error("the base-bid radio's change handler is gone -- rewrite this harness, don't delete it");
  const start = i + FLIP_ANCHOR.length;
  const open = SRC.indexOf("{", start);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(start, j + 1);
  }
  throw new Error("unbalanced braces in the base-bid radio's change handler");
})();
// The page's own Backspace/Delete boundary refusal.
const PAGE_BACKSPACE = region(
  '  docSurface.addEventListener("keydown", (e) => {\n    const back = e.key === "Backspace"',
  "  /** PASTE, for every editable family");

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
    const id = /#([\w-]+)/.exec(part);
    if (id && el.attrs.id !== id[1]) return false;
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
const VOID = new Set(["BR", "IMG", "HR", "INPUT"]);

class El {
  constructor(tag) {
    this.nodeType = Node.ELEMENT_NODE;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.style = {};
    this.attrs = {};
    this.title = "";
    this.hidden = false;
    this._classes = new Set();
    this._ls = {};
    const self = this;
    this.dataset = new Proxy({}, {
      set: (obj, k, v) => {
        obj[k] = v;
        self.attrs["data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())] = String(v);
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
  get id() { return this.attrs.id || ""; }
  set id(v) { this.attrs.id = String(v); }
  get parentElement() { return this.parentNode; }
  get children() { return this.childNodes.filter((n) => n.nodeType === Node.ELEMENT_NODE); }
  get previousElementSibling() {
    if (!this.parentNode) return null;
    const sibs = this.parentNode.children;
    const i = sibs.indexOf(this);
    return i > 0 ? sibs[i - 1] : null;
  }
  get nextElementSibling() {
    if (!this.parentNode) return null;
    const sibs = this.parentNode.children;
    const i = sibs.indexOf(this);
    return i >= 0 && i < sibs.length - 1 ? sibs[i + 1] : null;
  }
  get nextSibling() {
    if (!this.parentNode) return null;
    const kids = this.parentNode.childNodes;
    return kids[kids.indexOf(this) + 1] || null;
  }
  get className() { return Array.from(this._classes).join(" "); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); this.attrs.class = v; }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    this.childNodes.push(c);
    return c;
  }
  insertBefore(c, ref) {
    if (!ref) return this.appendChild(c);
    if (c.parentNode) c.parentNode.removeChild(c);
    const i = this.childNodes.indexOf(ref);
    if (i < 0) throw new Error("insertBefore: the reference node is not a child");
    c.parentNode = this;
    this.childNodes.splice(i, 0, c);
    return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c);
    if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null;
    return c;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  get textContent() {
    return this.childNodes.map((n) => (n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent)).join("");
  }
  set textContent(v) {
    while (this.childNodes.length) this.removeChild(this.childNodes[0]);
    if (String(v) !== "") this.appendChild(new Text(v));
  }
  set innerHTML(html) {
    while (this.childNodes.length) this.removeChild(this.childNodes[0]);
    const stack = [this];
    const re = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/g;
    let m;
    while ((m = re.exec(html))) {
      const top = stack[stack.length - 1];
      if (m[1]) {
        if (stack.length > 1) stack.pop();
      } else if (m[2]) {
        const el = new El(m[2]);
        for (const a of m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
          const v = unesc(a[2] == null ? "" : a[2]);
          el.attrs[a[1]] = v;
          if (a[1] === "class") el.className = v;
          else if (a[1] === "style") el.style = parseStyle(v);
          else if (a[1] === "hidden") el.hidden = true;
          else if (a[1].startsWith("data-")) {
            el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
          }
        }
        top.appendChild(el);
        if (!VOID.has(el.tagName)) stack.push(el);
      } else if (m[4] !== undefined) {
        const t = unesc(m[4]);
        if (t.trim() || stack.length > 1) top.appendChild(new Text(t));
      }
    }
  }
  get innerHTML() { return ""; }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === "style") this.style = parseStyle(v);
    else if (k === "class") this.className = String(v);
  }
  getAttribute(k) {
    if (k === "style") {
      return Object.entries(this.style)
        .map(([n, v]) => n.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase()) + ":" + v).join(";");
    }
    return this.attrs[k] === undefined ? null : this.attrs[k];
  }
  removeAttribute(k) { delete this.attrs[k]; if (k === "title") this.title = ""; }
  matches(sel) { return matches(this, sel); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const out = [];
    for (const c of this.children) {
      if (matches(c, sel)) out.push(c);
      out.push(...c.querySelectorAll(sel));
    }
    return out;
  }
  closest(sel) {
    let el = this;
    while (el) {
      if (el.nodeType === Node.ELEMENT_NODE && matches(el, sel)) return el;
      el = el.parentNode;
    }
    return null;
  }
  contains(other) {
    let el = other;
    while (el) { if (el === this) return true; el = el.parentNode; }
    return false;
  }
  normalize() {}
  addEventListener(type, f, capture) {
    (this._ls[type] = this._ls[type] || []).push({ f, capture: !!capture });
  }
  dispatchEvent(e) { return fire(this, e.type, { bubbles: e.bubbles }); }
  getBoundingClientRect() { return { width: 0, height: 0, left: 0, top: 0, right: 0, bottom: 0 }; }
}

/** A DOM dispatch: capture listeners root -> target, then bubble target -> root, honouring
 *  stopPropagation between nodes. That ordering IS the fix under test (see the header). */
function fire(node, type, props) {
  const e = Object.assign({
    type, target: node, defaultPrevented: false, _stop: false,
    preventDefault() { this.defaultPrevented = true; },
    stopPropagation() { this._stop = true; },
    stopImmediatePropagation() { this._stop = true; },
  }, props || {});
  const up = [];
  for (let n = node; n; n = n.parentNode) up.push(n);
  for (const n of up.slice().reverse()) {
    for (const l of (n._ls[type] || []).filter((x) => x.capture)) l.f.call(n, e);
    if (e._stop) return e;
  }
  for (const n of up) {
    for (const l of (n._ls[type] || []).filter((x) => !x.capture)) l.f.call(n, e);
    if (e._stop) return e;
  }
  return e;
}

class Event {
  constructor(type, init) { this.type = type; this.bubbles = !!(init && init.bubbles); }
}

// ── the modelled selection ───────────────────────────────────────────────────
//   { el, a, b }       — character offsets inside one editable line
//   { node, offset }   — a collapsed caret at an element boundary (a click on a blank line)
let SEL = null;
function firstText(el) {
  for (const c of el.childNodes) {
    if (c.nodeType === Node.TEXT_NODE) return c;
    const t = c.nodeType === Node.ELEMENT_NODE ? firstText(c) : null;
    if (t) return t;
  }
  return null;
}
class Range {
  constructor() { this.startContainer = null; this.startOffset = 0; this.collapsed = false; }
  setStart(node, offset) { this.startContainer = node; this.startOffset = offset; }
  setEnd() {}
  collapse() { this.collapsed = true; }
}
function liveRange() {
  if (!SEL) return null;
  if (SEL.el) {
    const tn = firstText(SEL.el) || SEL.el;
    return { startContainer: tn, startOffset: SEL.a, endContainer: tn, collapsed: SEL.a === SEL.b,
             commonAncestorContainer: SEL.el };
  }
  return { startContainer: SEL.node, startOffset: SEL.offset, endContainer: SEL.node,
           collapsed: true, commonAncestorContainer: SEL.node };
}

// ── one page ────────────────────────────────────────────────────────────────
const STAGING_HTML = (() => {
  const i = HTML.indexOf('<div id="price-preview-staging"');
  if (i < 0) throw new Error("#price-preview-staging is gone from proposal-review.html");
  return HTML.slice(HTML.indexOf(">", i) + 1, HTML.indexOf("</div>\n\n<script", i))
    .replace(/<!--[\s\S]*?-->/g, "");
})();

const LIFTED = [
  topConst("escHtml"),
  fn("fmtAt"), topConst("sameFmt"), fn("segmentsOf"), fn("mergeSegs"), fn("editRuns"),
  fn("runStyleCss"), fn("runEditCss"), fn("renderRuns"), fn("serializeBlock"), fn("insertBreakAt"),
  topConst("LINE_SEL"), fn("lineAt"), fn("lineAtSelection"), fn("lineTarget"), fn("editingBox"),
  topConst("focusInside"),
  topConst("REGION_MOUNTS"),
  "let _povTimer = null;",
  fn("queuePovSave"),
  // The lines TYPED next to a price line (fix 5): a character typed on a blank gap line makes one
  // (typeOnGapLine -> makeExtraLine), and the page's own Enter and Backspace handlers split and
  // take away typed lines (splitPriceLine / mergePriceLine), so all of them are the real ones.
  fn("_ensurePov"), fn("makeExtraLine"), fn("caretInto"), fn("splitPriceLine"), fn("mergePriceLine"),
].join("\n\n");

function makePage(layout, stateIn) {
  const BODY = new El("body");
  const docSurface = new El("div");
  docSurface.id = "doc-surface";
  const staging = new El("div");
  staging.id = "price-preview-staging";
  staging.hidden = true;
  staging.innerHTML = STAGING_HTML;
  BODY.appendChild(docSurface);
  BODY.appendChild(staging);
  const byId = (id) => {
    const walk = (n) => {
      if (n.attrs && n.attrs.id === id) return n;
      for (const c of n.children || []) { const hit = walk(c); if (hit) return hit; }
      return null;
    };
    return walk(BODY);
  };
  const document = {
    body: BODY,
    getElementById: byId,
    createElement: (t) => new El(t),
    createRange: () => new Range(),
    querySelector: (s) => BODY.querySelector(s),
    querySelectorAll: (s) => BODY.querySelectorAll(s),
    activeElement: null,
  };
  const window = {
    getSelection: () => ({
      get rangeCount() { return SEL ? 1 : 0; },
      getRangeAt: () => liveRange(),
      removeAllRanges: () => { SEL = null; },
      addRange: (r) => {
        SEL = r.startContainer && r.startContainer.nodeType === Node.TEXT_NODE
          ? { el: r.startContainer.parentNode, a: r.startOffset, b: r.startOffset }
          : { node: r.startContainer, offset: r.startOffset };
      },
    }),
  };
  const saves = [];
  const TW = { setState: (o) => { saves.push(JSON.parse(JSON.stringify(o))); } };
  const timers = [];
  const setTimeout = (f) => { timers.push(f); return timers.length; };
  const clearTimeout = (id) => { if (id) timers[id - 1] = null; };
  const fits = [];
  const fitTxbx = (box) => { fits.push(box ? box.className : null); };
  const state = JSON.parse(JSON.stringify(stateIn || {}));
  const api = new Function(
    "document", "window", "docSurface", "Node", "F", "state", "TW", "setTimeout", "clearTimeout",
    "fitTxbx", "Event", "selectionRange", "placeSelection", "selectionLines", "TWPrice",
    `const RUN_KEYS = F.RUN_KEYS;
    const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;
    let templateOptionsHeadingIds = [];
    const systemPreviewEl = null, notesPreviewEl = null;
    // The page's paragraph-record store is not part of this: a price row and the Options heading
    // have no para record, and the GC paragraphs here carry no bullet to take off.
    const paraNow = () => null;
    const paraAction = () => false;
    const markEdited = (el) => { el.dispatchEvent(new Event("input", { bubbles: true })); };
    const spliceLines = () => { throw new Error("no multi-line selection is modelled here"); };
` + LIFTED + "\n\n" + PAGE_ENTER + "\n\n" + PAGE_BACKSPACE + "\n\n" + GAP_SECTION + `
    // The radio the estimator ticks, and what the panel around the handler supplies: the tab
    // options it edits, and the repaint it ends with (here, the gap's own painter).
    function flipBaseTo(value) {
      const rb = { checked: true, value: value };
      const opts = state.tab_opts && typeof state.tab_opts === "object" ? state.tab_opts : (state.tab_opts = {});
      const applyAndRefresh = () => { paintOptionsGap(); };
      const reloadForWorkType = () => {};
      // The tax wording the base line printed before the pick: it only matters to a base line
      // still in the old shape, which this gap fixture never has, so the tax rule (another
      // harness's world: price-lines-harness lifts it) is stood in for by "no wording".
      const baseTaxRule = () => ({ phrase: "" });
      (` + FLIP_HANDLER + `)();
    }
    return {
      flipBaseTo,
      paintOptionsGap, optionsGapCount, onOptionsGapKey, serializeBlock,
      setHeadingIds: (ids) => { templateOptionsHeadingIds = ids; },
      REGION_MOUNTS,
    };`)(document, window, docSurface, Node, F, state, TW, setTimeout, clearTimeout, fitTxbx,
         Event,
         // selectionRange, modelled: offsets when the caret is in `el`, else null.
         (el) => {
           if (!SEL) return null;
           if (SEL.el) return el === SEL.el || el.contains(SEL.el) ? [SEL.a, SEL.b] : null;
           return el === SEL.node || el.contains(SEL.node) ? [0, 0] : null;
         },
         (el, a, b) => { SEL = { el, a, b }; },
         () => (SEL && SEL.el ? [{ el: SEL.el, start: SEL.a, end: SEL.b }] : []),
         TWPrice);

  const box = new El("div");
  box.className = "tw-txbx";
  box.attrs.contenteditable = "true";
  docSurface.appendChild(box);
  const block = (id, text) => {
    const el = new El("div");
    el.className = "tw-block";
    el.dataset.id = String(id);
    el.textContent = text;
    return el;
  };
  const els = {};
  if (layout === "direct" || layout === "gyp") {
    if (layout === "gyp") {
      els.mobil = box.appendChild(block(10, "1 Mobilization to Site."));
      els.spacer = box.appendChild(block(11, ""));
    }
    const wrap = new El("div");
    wrap.className = "tw-priced-region";
    box.appendChild(wrap);
    // Mounted the way the page mounts them: the REAL mount list, in its order.
    const mounted = layout === "direct" ? api.REGION_MOUNTS.single_bid() : api.REGION_MOUNTS.has_options();
    mounted.forEach((el) => { if (el) wrap.appendChild(el); });
    els.wrap = wrap;
  } else if (layout === "gc") {
    els.total = box.appendChild(block(5, "$36,763 – Total"));
    els.spacer = box.appendChild(block(6, ""));
    els.heading = box.appendChild(block(7, "Options & Unit Prices"));
    box.appendChild(block(8, ""));
    api.setHeadingIds([7]);
  }
  const g = byId;
  if (layout !== "gc") els.heading = g("options-heading");
  // What refreshPriceDisplay leaves on screen for an INCLUDED-tax epoxy bid: the one base line.
  if (layout === "direct") {
    els.base = g("base-bid-row");
    els.base.textContent = "$36,763 – Epoxy flooring as described above (material sales tax INCLUDED)";
    for (const id of ["sales-tax-row", "remodel-tax-row", "total-row", "combo-price-block"]) {
      g(id).style.display = "none";
    }
  }
  // ...and what renderOptionLinesPreview does when the bid has options: the heading shows.
  if (layout !== "gc" && !(stateIn && stateIn.__noOptions)) els.heading.style.display = "";
  SEL = null;
  return { api, state, saves, timers, fits, box, els, g, docSurface };
}

// ── driving it the way a person does ────────────────────────────────────────
const gapLines = (p) => {
  const gap = p.g("options-gap");
  return gap ? gap.querySelectorAll(".tw-gap-line") : [];
};
const gapIndexOfCaret = (p) => {
  if (!SEL || !SEL.node) return null;
  return gapLines(p).indexOf(SEL.node.closest ? SEL.node.closest(".tw-gap-line") : null);
};
/** A keystroke as the browser delivers it: at the editing HOST, with the caret wherever it is. */
const key = (p, k) => fire(p.box, "keydown", { key: k, ctrlKey: false, metaKey: false, altKey: false });
/** A click on blank line `i`: the browser puts a collapsed caret before its placeholder break. */
const clickGapLine = (p, i) => { SEL = { node: gapLines(p)[i], offset: 0 }; };
const caretAt = (el, off) => { SEL = { el, a: off, b: off }; };
const flushSaves = (p) => { p.timers.forEach((f) => { if (f) f(); }); p.timers.length = 0; };
const snapshot = (p) => ({
  lines: gapLines(p).length,
  stored: (p.state.price_overrides || {}).options_gap,
  gapDirectlyAboveHeading: p.g("options-gap").nextElementSibling === p.els.heading,
  gapShown: p.g("options-gap").style.display !== "none",
  headingText: p.api.serializeBlock(p.els.heading),
  caretOnGapLine: gapIndexOfCaret(p),
  caretLine: SEL && SEL.el ? (SEL.el.id || SEL.el.dataset.id || null) : null,
  caretOffset: SEL && SEL.el ? SEL.a : null,
});

const out = {};

// ═══ the markup: no margin standing in for the gap ═══════════════════════════
{
  const p = makePage("direct", {});
  const st = p.els.heading.style;
  out.headingMargin = st.margin || "";
  out.headingMarginTop = st.marginTop || "";
  // The gap is mounted directly above the heading by the page's own mount list.
  const kids = p.els.wrap.children.map((c) => c.id);
  out.mountOrder = kids;
}

// ═══ Epoxy Direct, a draft saved before the key existed ══════════════════════
{
  const p = makePage("direct", {});
  p.api.paintOptionsGap();
  out.legacyDraft = snapshot(p);
  // Each blank line is a real element INSIDE the box's editing host and declares no host of its
  // own, so a click lands a caret on it and the arrow keys walk through it.
  const line = gapLines(p)[0];
  out.lineInHost = line ? { host: (line.closest("[contenteditable]") || {}).className || null,
                            ownHost: line.attrs.contenteditable || null,
                            isParagraph: line.tagName, placeholder: line.children.map((c) => c.tagName) } : null;

  // CLICK onto blank line 1, then an ARROW KEY: the handler leaves both to the browser.
  clickGapLine(p, 1);
  out.clickLandsOnLine = gapIndexOfCaret(p);
  out.arrowDown = key(p, "ArrowDown").defaultPrevented;
  out.arrowUp = key(p, "ArrowUp").defaultPrevented;

  // (Typing ON a blank line is its own page below: it changes the count.)

  // BACKSPACE ON BLANK LINE 1: one fewer, caret up onto line 0.
  clickGapLine(p, 1);
  const bs = key(p, "Backspace");
  out.backspaceOnGap = Object.assign(snapshot(p), { defaulted: bs.defaultPrevented });

  // BACKSPACE ON THE LAST BLANK LINE: refused -- the floor is one line (Hanz, 2026-09-26: "Base
  // bid and options should always have atleast 1 or 2 spaces from each other"). The line stays,
  // and the caret goes where it would have landed: the END of the base line above.
  const bs2 = key(p, "Backspace");
  out.backspaceLastGap = Object.assign(snapshot(p), { defaulted: bs2.defaultPrevented,
    baseLen: p.api.serializeBlock(p.els.base).length });

  // DELETE ON THE LAST BLANK LINE: refused the same way; the caret goes to the heading's start.
  clickGapLine(p, 0);
  const dl = key(p, "Delete");
  out.deleteLastGap = Object.assign(snapshot(p), { defaulted: dl.defaultPrevented });

  // BACKSPACE AT THE HEADING'S START with one line left: refused, the caret goes up onto it. The
  // page's own refusal still stands behind it (no merge into the line above), and nothing is
  // taken.
  caretAt(p.els.heading, 0);
  const bs3 = key(p, "Backspace");
  out.backspaceHeadingAtFloor = Object.assign(snapshot(p), { defaulted: bs3.defaultPrevented });

  // DELETE AT THE END OF THE BASE LINE with one line left: refused, the caret goes down onto it.
  const endBase = p.api.serializeBlock(p.els.base).length;
  caretAt(p.els.base, endBase);
  const dl2 = key(p, "Delete");
  out.deleteAboveAtFloor = Object.assign(snapshot(p), { defaulted: dl2.defaultPrevented,
    baseUnchanged: p.api.serializeBlock(p.els.base).length === endBase });

  // ENTER AT THE END OF THE BASE LINE: one more blank line, caret onto it -- and the base line
  // itself is untouched (the page's own Enter handler would have written "\n" into it).
  const before = p.api.serializeBlock(p.els.base);
  caretAt(p.els.base, before.length);
  const en = key(p, "Enter");
  out.enterAtEndOfBase = Object.assign(snapshot(p), { defaulted: en.defaultPrevented,
    baseUnchanged: p.api.serializeBlock(p.els.base) === before,
    baseAfter: p.api.serializeBlock(p.els.base) });

  // ENTER ON A BLANK LINE: one more, caret onto the new line below.
  const en2 = key(p, "Enter");
  out.enterOnGap = Object.assign(snapshot(p), { defaulted: en2.defaultPrevented });

  // ENTER IN THE MIDDLE OF THE BASE LINE is the page's own Enter: the text after the caret moves
  // to a line of its own under the base line (splitPriceLine), never a break inside the line. The
  // gap is untouched.
  caretAt(p.els.base, 5);
  const mid = key(p, "Enter");
  const under = p.els.base.nextElementSibling;
  out.enterMidBase = { lines: gapLines(p).length, defaulted: mid.defaultPrevented,
                       baseHead: p.api.serializeBlock(p.els.base),
                       under: under ? { kind: under.dataset.poKind, pos: under.dataset.poPos,
                                        text: p.api.serializeBlock(under) } : null,
                       headWas: before.slice(0, 5), tailWas: before.slice(5) };
  if (under && under.dataset.poKind === "extra") under.remove();
  p.els.base.textContent = before;

  // BACKSPACE AT THE HEADING'S START: one fewer, caret stays at the heading's start, and the
  // heading's own text (the heading_options override channel) is untouched.
  caretAt(p.els.heading, 0);
  const bs4 = key(p, "Backspace");
  out.backspaceHeadingStart = Object.assign(snapshot(p), { defaulted: bs4.defaultPrevented });

  // Backspace in the MIDDLE of the heading is ordinary editing, not a gap change.
  caretAt(p.els.heading, 3);
  const bs5 = key(p, "Backspace");
  out.backspaceMidHeading = { lines: gapLines(p).length, defaulted: bs5.defaultPrevented };

  // DELETE ON A BLANK LINE: one fewer, caret stays on that line when one is still there.
  p.state.price_overrides.options_gap = 3;
  p.api.paintOptionsGap();
  clickGapLine(p, 0);
  const del = key(p, "Delete");
  out.deleteOnGap = Object.assign(snapshot(p), { defaulted: del.defaultPrevented });

  // What was persisted: the count, through the page's own debounced price_overrides save.
  flushSaves(p);
  out.persisted = p.saves.length ? p.saves[p.saves.length - 1] : null;
  out.refitted = p.fits.length;
}

// ═══ a reload restores N ═════════════════════════════════════════════════════
{
  const counts = {};
  for (const [name, v] of [["three", 3], ["zero", 0], ["string", "4"], ["garbage", "lots"],
                           ["negative", -2], ["huge", 99], ["fraction", 2.5]]) {
    const p = makePage("direct", { price_overrides: { options_gap: v } });
    p.api.paintOptionsGap();
    counts[name] = { lines: gapLines(p).length, shown: p.g("options-gap").style.display !== "none",
                     counted: p.api.optionsGapCount() };
  }
  out.reload = counts;
}

// ═══ no options: no heading, no gap ══════════════════════════════════════════
{
  const p = makePage("direct", { __noOptions: true, price_overrides: { options_gap: 3 } });
  p.api.paintOptionsGap();
  out.noOptions = { lines: gapLines(p).length, shown: p.g("options-gap").style.display !== "none" };
  // ...and Enter at the end of the base line is the page's own Enter again: a new line of its own
  // under the base line, the base line itself untouched.
  const t = p.api.serializeBlock(p.els.base);
  caretAt(p.els.base, t.length);
  key(p, "Enter");
  const under = p.els.base.nextElementSibling;
  out.noOptionsEnter = { lines: gapLines(p).length,
                         newLineUnderBase: !!under && under.dataset.poKind === "extra"
                           && under.dataset.poPos === "after" && p.api.serializeBlock(under) === "",
                         baseUnchanged: p.api.serializeBlock(p.els.base) === t };
}

// ═══ GC: the heading is a free paragraph; the template's spacer is absorbed ═══
{
  const p = makePage("gc", {});
  p.api.paintOptionsGap();
  const gap = p.g("options-gap");
  out.gc = {
    lines: gapLines(p).length,
    gapDirectlyAboveHeading: gap.nextElementSibling === p.els.heading,
    gapInBox: p.box.contains(gap),
    spacerHidden: p.els.spacer.classList.contains("tw-gap-absorbed"),
    trailingBlankKept: !p.box.children[p.box.children.length - 1].classList.contains("tw-gap-absorbed"),
  };
  caretAt(p.els.heading, 0);
  const bs = key(p, "Backspace");
  out.gcBackspaceHeading = Object.assign(snapshot(p), { defaulted: bs.defaultPrevented });
  const tot = p.api.serializeBlock(p.els.total);
  caretAt(p.els.total, tot.length);
  const en = key(p, "Enter");
  out.gcEnterAtTotal = Object.assign(snapshot(p), { defaulted: en.defaultPrevented,
    totalUnchanged: p.api.serializeBlock(p.els.total) === tot });
  // Text typed into the spacer makes it a line of its own: it is shown again, like the writer
  // keeping a spacer that is no longer blank.
  p.els.spacer.textContent = "see below";
  p.api.paintOptionsGap();
  out.gcTypedSpacer = { spacerHidden: p.els.spacer.classList.contains("tw-gap-absorbed") };
}

// ═══ Gyp: the gap opens its region; the spacer sits just above the region ═══
{
  const p = makePage("gyp", {});
  p.api.paintOptionsGap();
  out.gyp = {
    lines: gapLines(p).length,
    gapDirectlyAboveHeading: p.g("options-gap").nextElementSibling === p.els.heading,
    spacerHidden: p.els.spacer.classList.contains("tw-gap-absorbed"),
    mobilShown: !p.els.mobil.classList.contains("tw-gap-absorbed"),
  };
  const m = p.api.serializeBlock(p.els.mobil);
  caretAt(p.els.mobil, m.length);
  key(p, "Enter");
  out.gypEnterAtMobil = snapshot(p);
}

// ═══ THE BLANK LINES TAKE TEXT (Hanz, 2026-09-26: "I cant write texts on this white space lines") ═
const typedEls = (p) => p.docSurface.querySelectorAll(
  '[data-po-kind="extra"][data-po-linekey="heading_options"][data-po-pos="before"]');
const typedState = (p) => {
  const pov = p.state.price_overrides || {};
  return pov.before && Array.isArray(pov.before.heading_options) ? pov.before.heading_options : null;
};
const typedSnap = (p) => {
  const els = typedEls(p);
  return Object.assign(snapshot(p), {
    typed: typedState(p),
    drawn: els.map((n) => p.api.serializeBlock(n)),
    // Top to bottom: the typed lines, then the blank lines, then the heading.
    typedDirectlyAboveGap: els.length ? els[els.length - 1].nextElementSibling === p.g("options-gap") : null,
    caretText: SEL && SEL.el ? p.api.serializeBlock(SEL.el) : null,
    caretIsTyped: !!(SEL && (SEL.el || SEL.node) && ((SEL.el || SEL.node).dataset || {}).poKind === "extra"),
  });
};
const typeKey = (p, ch) => fire(p.box, "keydown", { key: ch, ctrlKey: false, metaKey: false, altKey: false });
{
  // A character typed on blank line 1 of 2: that line becomes a typed line; the blank line above
  // it becomes a typed blank line so it stays where it was typed; and, it having been the last
  // blank line, a fresh one is kept under it (the floor).
  const p = makePage("direct", {});
  p.api.paintOptionsGap();
  clickGapLine(p, 1);
  const e = typeKey(p, "x");
  out.typeOnGap = Object.assign(typedSnap(p), { defaulted: e.defaultPrevented });
  flushSaves(p);
  out.typeOnGapSaved = p.saves.length ? (p.saves[p.saves.length - 1].price_overrides || {}) : null;
}
{
  // On blank line 0 of 2: the typed line, then one blank line, then the heading.
  const p = makePage("direct", {});
  p.api.paintOptionsGap();
  clickGapLine(p, 0);
  typeKey(p, "a");
  out.typeOnFirstGap = typedSnap(p);
  const a = typedEls(p)[0];
  // ENTER at the end of the typed line: one more BLANK line under it (the count), caret onto it.
  caretAt(a, 1);
  const en = key(p, "Enter");
  out.enterAtEndOfTyped = Object.assign(typedSnap(p), { defaulted: en.defaultPrevented });
  // DELETE at the end of the typed line: the blank line under it goes.
  caretAt(a, 1);
  const del = key(p, "Delete");
  out.deleteAtEndOfTyped = Object.assign(typedSnap(p), { defaulted: del.defaultPrevented });
  // BACKSPACE on the last blank line: refused (the floor), the caret at the end of the typed line
  // above.
  clickGapLine(p, 0);
  const bs = key(p, "Backspace");
  out.backspaceOntoTyped = Object.assign(typedSnap(p), { defaulted: bs.defaultPrevented });
  // BACKSPACE AT THE START OF "Options:" with one blank line left and words above it: the line
  // stays, the words stay, the caret goes up onto the blank line.
  caretAt(p.els.heading, 0);
  const bh = key(p, "Backspace");
  out.backspaceHeadingUnderTyped = Object.assign(typedSnap(p), { defaulted: bh.defaultPrevented });
}
{
  // TYPED ON THE LAST REMAINING BLANK LINE: it becomes a typed line and a fresh blank line is kept
  // under it, so "Options:" still has one above it.
  const p = makePage("direct", { price_overrides: { options_gap: 1 } });
  p.api.paintOptionsGap();
  clickGapLine(p, 0);
  const e = typeKey(p, "z");
  out.typeOnLastGap = Object.assign(typedSnap(p), { defaulted: e.defaultPrevented });
  flushSaves(p);
  out.typeOnLastGapSaved = p.saves.length ? (p.saves[p.saves.length - 1].price_overrides || {}) : null;
}
{
  // A draft saved with NO blank line left (options_gap 0, an empty typed line right above the
  // heading, from before the floor): it is drawn with the one blank line the floor keeps, and the
  // empty typed line is still Backspace's to take -- from the heading, up onto the blank line,
  // up to the end of the empty typed line (the floor refuses the blank line), and then the page's
  // own Backspace takes the empty line away.
  const p = makePage("direct", { price_overrides: { options_gap: 0, before: { heading_options: ["kept", ""] } } });
  p.api.paintOptionsGap();
  out.reloadTyped = typedSnap(p);
  caretAt(p.els.heading, 0);
  const bh = key(p, "Backspace");
  out.backspaceHeadingOverTyped = Object.assign(typedSnap(p), { defaulted: bh.defaultPrevented });
  const bf = key(p, "Backspace");
  out.backspaceFloorOntoEmptyTyped = Object.assign(typedSnap(p), { defaulted: bf.defaultPrevented,
    caretOnEmptyTyped: !!(SEL && SEL.el && SEL.el === typedEls(p)[1]) });
  const empty = typedEls(p)[1];
  if (empty) { caretAt(empty, 0); SEL = { node: empty, offset: 0 }; }
  const bt = key(p, "Backspace");
  out.backspaceTakesEmptyTyped = Object.assign(typedSnap(p), { defaulted: bt.defaultPrevented });
}
{
  // An empty typed line with a price row above it: Backspace takes it away and puts the caret at
  // the end of the line SHOWN above -- the base line, not the hidden tax rows between them.
  const p = makePage("direct", { price_overrides: { options_gap: 0, before: { heading_options: ["", "x"] } } });
  p.api.paintOptionsGap();
  const first = typedEls(p)[0];
  caretAt(first, 0);
  SEL = { node: first, offset: 0 };
  const bs = key(p, "Backspace");
  out.backspaceEmptyFirstTyped = Object.assign(typedSnap(p), { defaulted: bs.defaultPrevented,
    baseLen: p.api.serializeBlock(p.els.base).length });
}
{
  // A PASTE on a blank line: one typed line per line of the clipboard.
  const p = makePage("direct", {});
  p.api.paintOptionsGap();
  clickGapLine(p, 0);
  const e = fire(p.box, "paste", { clipboardData: { getData: (t) => (t === "text/plain" ? "first\r\nsecond\n" : "") } });
  out.pasteOnGap = Object.assign(typedSnap(p), { defaulted: e.defaultPrevented });
  // Text that arrives without a keystroke (an IME commit): lands the same way.
  const q = makePage("direct", {});
  q.api.paintOptionsGap();
  clickGapLine(q, 1);
  const bi = fire(q.box, "beforeinput", { inputType: "insertText", data: "q" });
  out.beforeInputOnGap = Object.assign(typedSnap(q), { defaulted: bi.defaultPrevented });
  // ...and a deletion by a route the keys do not cover is still refused, changing nothing.
  const r = makePage("direct", {});
  r.api.paintOptionsGap();
  clickGapLine(r, 0);
  const bd = fire(r.box, "beforeinput", { inputType: "deleteContentBackward" });
  out.beforeInputDelete = Object.assign(typedSnap(r), { defaulted: bd.defaultPrevented });
}
{
  // GC: the typed line sits between the template's spacer (still absorbed) and the blank lines.
  const p = makePage("gc", {});
  p.api.paintOptionsGap();
  clickGapLine(p, 0);
  typeKey(p, "G");
  p.api.paintOptionsGap();
  const els = typedEls(p);
  out.gcTyped = Object.assign(typedSnap(p), {
    spacerHidden: p.els.spacer.classList.contains("tw-gap-absorbed"),
    spacerAboveTyped: els.length ? els[0].previousElementSibling === p.els.spacer : null,
  });
}

{
  // A BASE-BID FLIP (review, 2026-09-26). Typing on blank line 1 of 2 moves both lines out of the
  // count into the typed lines (options_gap 0). The flip used to clear those typed lines with the
  // old base's edits and keep the count: the note was lost and the gap came back as 0 lines.
  // Since the base-pick fix (Hanz, 2026-09-26: keep the words) the base line's own words and the
  // lines typed round it are kept too, by the one rule both pickers share (TWPrice.applyBasePick).
  const p = makePage("direct", { base_tab_id: "Epoxy", price_overrides: {
    lines2: { base: "\u27e6amount\u27e7 – for the old base" }, after: { base: ["typed under the old base"] } } });
  p.api.paintOptionsGap();
  clickGapLine(p, 1);
  typeKey(p, "N");
  const typed = typedSnap(p);
  p.api.flipBaseTo("Copy1");
  const pov = p.state.price_overrides;
  out.flipKeepsGap = Object.assign(typedSnap(p), {
    typedBefore: { typed: typed.typed, lines: typed.lines, stored: typed.stored },
    base: p.state.base_tab_id,
    oldBaseLine: (pov.lines2 || {}).base || null,
    oldBaseTyped: (pov.after || {}).base || null,
  });
}

console.log(JSON.stringify(out));
