"use strict";
/* The Proposal step's page 1, laid out -- RUN, not read.
 *
 * Audit, 2026-10-02 (staging, Direct epoxy "Release check 9-26"), the editor-only items this covers:
 *   #9  the REGARDS name drew in Zetta Serif; Word prints a run with no font of its own in the
 *       document default (docDefaults -> theme minor latin: Cambria in every template).
 *   #10 the Options heading sat ~16pt lower than the PDF prints it: the PRICE lines the page composes
 *       carried margins nobody prints and the page's 1.32 line height.
 *   #11 "Longer than this box" and Fit to text on a PRICE box whose last words were two thirds of the
 *       way down it: the test counted the blank spacer paragraphs every box ends with.
 *   #12 a second red rule under the PRICE/NOTES boundary: the over-long marker drawn at the element's
 *       bottom, which is where the TEXT stops, not where the printed box ends.
 *
 * WHAT IS LIFTED: the shipped functions themselves, verbatim, out of proposal-review.js --
 * resolveTemplateFonts, renderBlock and everything it draws through, renderBlockList and the
 * REGION_MOUNTS that put the real #price-preview-staging rows (sliced out of proposal-review.html)
 * into the PRICE box, lineEl, paintLineParas, paintOptionsGap and its section, and the fit family
 * (boxInkPx, boxContentPx, fitTxbx, fitOffer, growBoxToFit, applyBoxGeom ...).
 *
 * WHAT IS MODELLED: the browser's block layout, because the bug in #10 and #11 IS layout. Every
 * line box is `line-height x font-size` (CSS: a unitless line height multiplies the element's own
 * size, a length is that length, and `.tw-page` gives 1.32 to anything that states none), each line
 * with words or a <br> is ONE line (every row here is shorter than the box is wide), an empty
 * element has no line box, and the stylesheet's min-heights apply: `.tw-block` 1.3em,
 * `.tw-block.tw-empty` 1.05em at its paragraph-mark size, `.tw-gap-line` 1em, an empty
 * `.tw-line-edit` 1.1em. Vertical margins between consecutive lines collapse to the larger, through
 * the plain wrapper divs (regions, the gap) that have no border or padding of their own. A
 * baseline sits half the leading below the line box's top plus Zetta Serif's ascender:
 * (L - 1.0em)/2 + 0.76em, the face's hhea ascender 760 and descender 240 on a 1000-unit em. That
 * is the model that reproduces the audited editor's Options heading (96.7pt below the box top
 * modelled, 97.5pt measured off the screenshot) from the code before this fix.
 *
 * Usage: node editor-layout-harness.js <frontend-dir> <payloads.json>   ->   one line of JSON
 *   payloads.json: { "epoxy:Direct": <GET /api/proposal-template body>, ... }
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const PAYLOADS = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
// Normalized to LF, like every harness here: the checkout is CRLF and the lifts anchor on "\n  ".
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");
const HTML = fs.readFileSync(path.join(FRONTEND, "proposal-review.html"), "utf8")
  .replace(/\r\n/g, "\n");
const F = require(path.join(FRONTEND, "js", "proposal-format-core.js"));
const TWPrice = require(path.join(FRONTEND, "js", "price-lines-core.js"));

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
/** A `const NAME = "..."` that is one line (the tooltip strings lineEl hands its lines). */
function lineConst(name) {
  const m = new RegExp("\\n  const " + name + " = [^\\n]*;").exec(SRC);
  if (!m) throw new Error("const " + name + " is gone from proposal-review.js");
  return m[0];
}

// ── the smallest DOM these functions touch ─────────────────────────────────────────────────────
const Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
const unesc = (s) => String(s).replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, k) => ENTITIES[k]);

function makeStyle(css) {
  const st = {};
  const custom = {};
  const assign = (raw, v) => {
    if (raw.startsWith("--")) { custom[raw] = v; return; }
    st[raw.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
  };
  for (const bit of String(css || "").split(";")) {
    const k = bit.indexOf(":");
    if (k < 0) continue;
    const raw = bit.slice(0, k).trim();
    if (raw) assign(raw, bit.slice(k + 1).trim());
  }
  Object.defineProperties(st, {
    setProperty: { value: (k, v) => { custom[k] = String(v); }, enumerable: false },
    removeProperty: { value: (k) => { delete custom[k]; }, enumerable: false },
    getPropertyValue: { value: (k) => (custom[k] === undefined ? "" : custom[k]), enumerable: false },
  });
  return st;
}

function matches(el, sel) {
  return String(sel).split(",").some((one) => {
    const part = one.trim();
    if (!part) return false;
    if (/\s/.test(part)) throw new Error("descendant selector not modelled: " + part);
    const id = /#([\w-]+)/.exec(part);
    if (id && el.attrs.id !== id[1]) return false;
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
  get textContent() { return this.nodeValue; }
}

const VOID = new Set(["BR", "IMG", "HR", "INPUT"]);
let LAYOUT = null;                      // set by layoutBox(): el -> {top, h} in pt, box-relative

class El {
  constructor(tag) {
    this.nodeType = Node.ELEMENT_NODE;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.style = makeStyle("");
    this.attrs = {};
    this.title = "";
    this.hidden = false;
    this._classes = new Set();
    const self = this;
    this.dataset = new Proxy({}, {
      set: (obj, k, v) => {
        obj[k] = v;
        self.attrs["data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())] = String(v);
        return true;
      },
      get: (obj, k) => obj[k],
      deleteProperty: (obj, k) => {
        delete obj[k];
        delete self.attrs["data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())];
        return true;
      },
    });
    this.classList = {
      add: (...cs) => cs.forEach((c) => self._classes.add(c)),
      remove: (...cs) => cs.forEach((c) => self._classes.delete(c)),
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
  get className() { return Array.from(this._classes).join(" "); }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); this.attrs.class = v; }
  get previousElementSibling() {
    if (!this.parentNode) return null;
    const sib = this.parentNode.children;
    const i = sib.indexOf(this);
    return i > 0 ? sib[i - 1] : null;
  }
  get nextElementSibling() {
    if (!this.parentNode) return null;
    const sib = this.parentNode.children;
    const i = sib.indexOf(this);
    return i >= 0 && i < sib.length - 1 ? sib[i + 1] : null;
  }
  appendChild(c) {
    if (c.parentNode) c.parentNode.childNodes = c.parentNode.childNodes.filter((n) => n !== c);
    c.parentNode = this; this.childNodes.push(c); return c;
  }
  insertBefore(c, ref) {
    if (!ref) return this.appendChild(c);
    if (c.parentNode) c.parentNode.childNodes = c.parentNode.childNodes.filter((n) => n !== c);
    const i = this.childNodes.indexOf(ref);
    c.parentNode = this;
    this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c);
    return c;
  }
  remove() { if (this.parentNode) this.parentNode.childNodes = this.parentNode.childNodes.filter((n) => n !== this); this.parentNode = null; }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
    if (k === "style") this.style = makeStyle(v);
    if (k === "class") this.className = v;
  }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; }
  get textContent() {
    return this.childNodes.map((n) => (n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent)).join("");
  }
  set textContent(v) { this.childNodes = []; if (String(v) !== "") this.appendChild(new Text(v)); }
  set innerHTML(html) {
    this.childNodes = [];
    const stack = [this];
    const re = /<!--[\s\S]*?-->|<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:="[^"]*")?)*)\s*\/?>|([^<]+)/g;
    let m;
    while ((m = re.exec(String(html)))) {
      if (m[0].startsWith("<!--")) continue;
      const top = stack[stack.length - 1];
      if (m[1]) { if (stack.length > 1) stack.pop(); }
      else if (m[2]) {
        const el = new El(m[2]);
        for (const a of m[3].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
          const v = unesc(a[2] === undefined ? "" : a[2]);
          el.attrs[a[1]] = v;
          if (a[1] === "class") el.className = v;
          else if (a[1] === "style") el.style = makeStyle(v);
          else if (a[1] === "title") el.title = v;
          else if (a[1] === "hidden") el.hidden = true;
          else if (a[1].startsWith("data-")) el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
        }
        top.appendChild(el);
        if (!VOID.has(el.tagName)) stack.push(el);
      } else if (m[4] !== undefined && m[4].trim() !== "" ) top.appendChild(new Text(unesc(m[4])));
      else if (m[4] !== undefined && stack.length > 1 && stack[stack.length - 1].tagName !== "DIV") {
        top.appendChild(new Text(unesc(m[4])));
      }
    }
  }
  querySelector(sel) {
    for (const c of this.children) {
      if (matches(c, sel)) return c;
      const deep = c.querySelector(sel);
      if (deep) return deep;
    }
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    for (const c of this.children) { if (matches(c, sel)) out.push(c); out.push(...c.querySelectorAll(sel)); }
    return out;
  }
  closest(sel) {
    let el = this;
    while (el) { if (el.nodeType === Node.ELEMENT_NODE && matches(el, sel)) return el; el = el.parentNode; }
    return null;
  }
  contains(other) { let el = other; while (el) { if (el === this) return true; el = el.parentNode; } return false; }
  addEventListener() {}
  // Layout, read the way the page reads it: offsetTop against offsetParent, offsetHeight, in CSS px.
  get offsetParent() {
    if (!LAYOUT || !LAYOUT.has(this)) return null;
    for (let n = this.parentNode; n; n = n.parentNode) {
      if (n === LAYOUT.box) return n;
      if (n.classList && ["tw-priced-region", "tw-li", "tw-num"].some((c) => n.classList.contains(c))) return n;
    }
    return null;
  }
  get offsetTop() {
    if (!LAYOUT || !LAYOUT.has(this)) return undefined;
    const p = this.offsetParent;
    const base = !p || p === LAYOUT.box ? 0 : LAYOUT.get(p).top;
    return (LAYOUT.get(this).top - base) * PX_PER_PT;
  }
  get offsetHeight() {
    if (LAYOUT && this === LAYOUT.box) return LAYOUT.boxH * PX_PER_PT;
    if (!LAYOUT || !LAYOUT.has(this)) return 0;
    return LAYOUT.get(this).h * PX_PER_PT;
  }
}

// ── the layout model (see the header) ──────────────────────────────────────────────────────────
const PX_PER_PT = 96 / 72;
const PAGE_LH = 1.32, PAGE_FS = 9;
const ASC = 0.76;                          // Zetta Serif hhea ascender, per em

const isShown = (el) => !el.hidden && el.style.display !== "none"
  && !el.classList.contains("tw-block-removed") && !el.classList.contains("tw-gap-absorbed");
const isBlock = (el) => el.nodeType === Node.ELEMENT_NODE && /^(DIV|P)$/.test(el.tagName);

/** The font size an element is drawn at, in pt: the stylesheet's two !important rules first (an
 *  empty paragraph at its mark size, a printed size from applyBoxFit), then its own inline size,
 *  then its parent's. */
function fontPt(el) {
  if (!el || el.nodeType !== Node.ELEMENT_NODE) return PAGE_FS;
  if (el.classList.contains("tw-block") && el.classList.contains("tw-empty") && el.dataset.markPt) {
    return Number(el.dataset.markPt);
  }
  if (el.dataset.twFit === "1" && el.style.getPropertyValue("--tw-fit-pt")) {
    return parseFloat(el.style.getPropertyValue("--tw-fit-pt"));
  }
  if (/pt$/.test(el.style.fontSize || "")) return parseFloat(el.style.fontSize);
  return el.parentNode ? fontPt(el.parentNode) : PAGE_FS;
}
/** Its line box height, in pt. */
function lineBoxPt(el) {
  const fsz = fontPt(el);
  for (let n = el; n && n.nodeType === Node.ELEMENT_NODE; n = n.parentNode) {
    const v = String(n.style.lineHeight || "");
    if (!v) continue;
    if (/pt$/.test(v)) return parseFloat(v);
    if (/^[\d.]+$/.test(v)) return Number(v) * fsz;
  }
  return PAGE_LH * fsz;
}
function marginsPt(el) {
  const parse = (v) => (v == null || v === "" ? null : /pt$/.test(v) ? parseFloat(v) : Number(v) === 0 ? 0 : null);
  let top = null, bottom = null;
  const sh = String(el.style.margin || "").trim().split(/\s+/).filter(Boolean);
  if (sh.length) {
    top = parse(sh[0]);
    bottom = parse(sh.length >= 3 ? sh[2] : sh[0]);
  }
  if (el.style.marginTop !== undefined && el.style.marginTop !== "") top = parse(el.style.marginTop);
  if (el.style.marginBottom !== undefined && el.style.marginBottom !== "") bottom = parse(el.style.marginBottom);
  // The stylesheet's own: `.tw-gap-line` states its margin; a <p> with none gets the UA's 1em.
  if (el.classList.contains("tw-gap-line")) {
    const css = GAP_LINE_MARGIN;
    if (top === null) top = css;
    if (bottom === null) bottom = css;
  }
  if (el.tagName === "P") { if (top === null) top = fontPt(el); if (bottom === null) bottom = fontPt(el); }
  return { top: top || 0, bottom: bottom || 0 };
}
const hasInk = (el) => el.childNodes.some((n) => (n.nodeType === Node.TEXT_NODE ? n.nodeValue !== ""
  : n.tagName === "BR" || (!isBlock(n) && hasInk(n))));
function minHeightPt(el) {
  const em = fontPt(el);
  let h = 0;
  if (el.classList.contains("tw-block")) h = el.classList.contains("tw-empty") ? 1.05 * em : 1.3 * em;
  if (el.classList.contains("tw-gap-line")) h = Math.max(h, 1 * em);
  if (el.classList.contains("tw-line-edit") && !el.childNodes.length) h = Math.max(h, 1.1 * em);
  if (/pt$/.test(el.style.minHeight || "")) h = Math.max(h, parseFloat(el.style.minHeight));
  return h;
}

/** Lay one text box out: every shown block element gets {top, h} in pt from the box's top. */
function layoutBox(box) {
  const map = new Map();
  let y = 0;                     // the running bottom edge of the last line, before its margin
  let pendingMargin = 0;         // the last line's bottom margin, waiting to collapse
  const visit = (el) => {
    if (!isShown(el)) return;
    const blockKids = el.children.filter(isBlock);
    const m = marginsPt(el);
    if (blockKids.length && !hasInk(el)) {
      // A wrapper: its margins collapse with its first and last child's (no border, no padding).
      pendingMargin = Math.max(pendingMargin, m.top);
      const start = y + pendingMargin;
      const rec = { top: start, h: 0 };
      map.set(el, rec);
      blockKids.forEach(visit);
      rec.top = Math.min(rec.top, ...blockKids.filter((k) => map.has(k)).map((k) => map.get(k).top));
      rec.h = Math.max(minHeightPt(el), y - rec.top);
      pendingMargin = Math.max(pendingMargin, m.bottom);
      return;
    }
    y += Math.max(pendingMargin, m.top);
    const content = hasInk(el) ? lineBoxPt(el) : 0;
    const h = Math.max(content, minHeightPt(el));
    map.set(el, { top: y, h: h, lineBox: content ? lineBoxPt(el) : 0, fs: fontPt(el) });
    y += h;
    pendingMargin = m.bottom;
  };
  box.children.filter(isBlock).forEach(visit);
  map.box = box;
  map.boxH = Math.max(y + pendingMargin, minHeightPt(box));
  LAYOUT = map;
  return map;
}
/** A line's first baseline, in pt from the box's top (see the header for the model). */
function baselinePt(map, el) {
  const r = map.get(el);
  return r.top + (r.lineBox - r.fs) / 2 + ASC * r.fs;
}

// The stylesheet's `.tw-gap-line { margin: ... }`, read out of styles.css so the model cannot drift.
const STYLES = fs.readFileSync(path.join(FRONTEND, "styles.css"), "utf8").replace(/\r\n/g, "\n");
const GAP_LINE_MARGIN = (() => {
  const m = /\n\.tw-gap-line \{([^}]*)\}/.exec(STYLES);
  if (!m) throw new Error(".tw-gap-line has no rule in styles.css");
  const mm = /margin:\s*([^;]+);/.exec(m[1]);
  const first = mm ? mm[1].trim().split(/\s+/) : ["0"];
  // top and bottom, as the shorthand says them
  const v = (s) => (/pt$/.test(s) ? parseFloat(s) : 0);
  return Math.max(v(first[0]), v(first.length >= 3 ? first[2] : first[0]));
})();

// ── the page ────────────────────────────────────────────────────────────────────────────────────
const STAGING = (() => {
  const i = HTML.indexOf('<div id="price-preview-staging"');
  if (i < 0) throw new Error("#price-preview-staging is gone from proposal-review.html");
  return HTML.slice(HTML.indexOf(">", i) + 1, HTML.indexOf("</div>\n\n<script", i));
})();

const GAP_SECTION = region("  // ── THE BLANK LINES ABOVE THE OPTIONS HEADING", "  function _handlePoInput(");

const LIFTED = [
  topConst("escHtml"), topConst("DOC_TOKEN_RE"), topConst("TWIPS_PER_PT"), topConst("LINE_SEL"),
  topConst("DOC_DEFAULT_FONT"), fn("resolveTemplateFonts"),
  fn("fillHtml"), fn("fillPlain"), fn("runStyleCss"), fn("blockHtml"), fn("singleTokenHint"),
  fn("setBlockContent"), fn("priceRowVisibility"),
  topConst("SINGLE_LINE_EM"), fn("paraLineHeight"), fn("applyParaSpacing"), fn("applyParaGeom"),
  fn("renderBlock"), fn("annotateRegions"), fn("mountRegionPreviews"), fn("renderBlockList"),
  topConst("REGION_MOUNTS"),
  fn("serializeBlock"), fn("segmentsOf"), fn("fmtAt"), fn("lineAt"), fn("lineBare"), fn("lineKeptEmpty"),
  topConst("_escLine"), lineConst("_OVERRIDE_TITLE"), lineConst("_LIVE_TITLE"), lineConst("_MONEY_TITLE"),
  fn("lineOverride"), fn("lineValue"), fn("lineCue"),
  fn("linePropsOf"), fn("extraLinesHtml"), fn("lineEl"), fn("makeExtraLine"),
  fn("paintLineParas"), fn("priceLineRecord"),
  GAP_SECTION,
  // the fit family
  topConst("boxFitById"), topConst("PAGE_HP"), fn("inlineHp"), fn("clearBoxFit"), fn("applyBoxFit"),
  fn("boxInkPx"), fn("boxContentPx"), fn("fitTxbx"),
  topConst("PT_PER_CSS_PX"), topConst("BOX_EPS_PT"), topConst("isAutoGrown"),
  fn("effectiveBoxRect"), fn("applyBoxGeom"), fn("boxOverrideEntry"), fn("setBoxOverride"),
  fn("clampPt"), fn("dragBoxRect"), fn("dropAutoGrownHeight"), fn("boxCeilingPt"), fn("growRoomPt"),
  fn("otherBoxRects"), fn("fitOffer"), fn("growBoxToFit"),
].join("\n\n");

function makePage(payload, stateIn) {
  const docSurface = new El("div");
  const staging = new El("div");
  staging.innerHTML = STAGING;
  const byId = (id, root) => {
    for (const r of root ? [root] : [docSurface, staging]) {
      if (r.attrs && r.attrs.id === id) return r;
      const hit = r.querySelector("#" + id);
      if (hit) return hit;
    }
    return null;
  };
  const document = {
    createElement: (t) => new El(t),
    activeElement: null,
    getElementById: (id) => byId(id),
    querySelectorAll: (sel) => docSurface.querySelectorAll(sel),
  };
  const window = { getSelection: () => ({ rangeCount: 0 }) };
  const state = JSON.parse(JSON.stringify(stateIn || {}));
  const api = new Function(
    "document", "window", "Node", "F", "TWPrice", "state", "docSurface", "templateBlocksIn",
    `const focusInside = () => false;
    const lineAtSelection = () => null;
    const systemPreviewEl = document.createElement("div");
    const notesPreviewEl = document.createElement("div");
    const blockById = new Map();
    const pristineById = new Map();
    const boxDesign = new Map();
    let boxOverrides = new Map();
    let boxLimits = { pageW: 612, pageH: 792, maxW: 432, maxH: 648, minPt: 12, printBottom: 720 };
    let templateBlocks = templateBlocksIn;
    let templateOptionsHeadingIds = [];
    let flowMode = false;
    const TOKEN_HINTS = {};
    const PERSISTS = [];
    const schedulePersistOverrides = () => { PERSISTS.push(1); };
    const caretInto = () => {};
    const queuePovSave = () => {};
    const scheduleFit = () => {};
` + LIFTED + `
    return { resolveTemplateFonts, renderBlock, renderBlockList, annotateRegions, lineEl,
             paintLineParas, paintOptionsGap, priceLineRecord, fitTxbx, growBoxToFit, applyBoxGeom,
             boxInkPx, boxContentPx, blockById, boxDesign, PERSISTS,
             setOptionsHeadingIds: (ids) => { templateOptionsHeadingIds = ids; } };`
  )(document, window, Node, F, TWPrice, state, docSurface, payload.blocks);
  payload.blocks.forEach((b) => api.blockById.set(b.id, b));
  (payload.geometry.boxes || []).forEach((b) => api.boxDesign.set(b.id,
    { x_pt: b.x_pt, y_pt: b.y_pt, w_pt: b.w_pt, h_pt: b.h_pt }));
  api.setOptionsHeadingIds(payload.options_heading_ids || []);
  return { api, docSurface, document, staging };
}

/** One text box of `payload`, mounted the way renderPositioned mounts it, with the staging rows
 *  painted the way refreshPriceDisplay paints them for the audited job. */
function priceBox(payload, opts) {
  const o = Object.assign({ options: 1, breakout: true, pov: {} }, opts || {});
  const pg = makePage(payload, { price_overrides: o.pov });
  const { api, docSurface } = pg;
  api.resolveTemplateFonts(payload.blocks, payload.default_font);
  api.annotateRegions(payload.blocks);
  const priceId = payload.blocks.find((b) => /^\s*Base Bid\s*$/.test(String(b.text || ""))).txbx;
  const page = new El("div");
  page.className = "tw-page";
  docSurface.appendChild(page);
  const box = new El("div");
  box.className = "tw-txbx";
  box.dataset.boxId = String(priceId);
  page.appendChild(box);
  api.applyBoxGeom(box);
  api.renderBlockList(box, payload.blocks.filter((b) => b.txbx === priceId), {});
  const $ = (id) => pg.document.getElementById(id);
  const set = (id, text, show) => { const el = $(id); if (!el) return; el.textContent = text; el.style.display = show ? "" : "none"; };
  set("base-bid-row", "$5,569 – Epoxy flooring as described above", true);
  set("sales-tax-row", "$11 – Material Sales Tax", o.breakout);
  set("remodel-tax-row", "$0 – Remodel Tax", false);
  set("total-row", "$5,580 – Total", o.breakout);
  const lines = $("price-lines-block");
  let html = "";
  for (let i = 0; i < o.options; i++) {
    html += api.lineEl("option:r" + i, "$5,283 – Epoxy copy as described above (material sales tax INCLUDED)",
                       { parts: { amount: "$5,283" } });
  }
  if (lines) lines.innerHTML = html;
  const oh = $("options-heading");
  if (oh) { oh.style.display = o.options ? "" : "none"; oh.textContent = "Options:"; }
  api.paintOptionsGap();
  api.paintLineParas(box);
  return { pg, box, $ };
}

const out = {};

// ═══ #9: the face a run with no font of its own prints in ════════════════════════════════════════
{
  const p = JSON.parse(JSON.stringify(PAYLOADS["epoxy:Direct"]));
  const pg = makePage(p, {});
  const face = pg.api.resolveTemplateFonts(p.blocks, p.default_font);
  const estimator = p.blocks.find((b) => /\{\{\s*estimator_name\s*\}\}/.test(String(b.text || "")));
  const zetta = p.blocks.find((b) => /^Epoxy Flooring:/.test(String(b.text || "")));
  const runless = p.blocks.find((b) => b.txbx != null && !(b.runs || []).length);
  const termsRunless = p.blocks.find((b) => b.txbx == null && !(b.runs || []).length);
  const terms = p.blocks.find((b) => b.txbx == null && (b.runs || []).some((r) => /\w/.test(r.text)));
  const fontsIn = (el) => el.querySelectorAll("span").map((s) => s.style.fontFamily || "").filter(Boolean);
  const draw = (b) => pg.api.renderBlock(b, { estimator_name: "Hanz de la Cruz", site_visit_phrase: "per site visit" });
  const est = draw(estimator), z = draw(zetta), rl = draw(runless), trl = draw(termsRunless), t = draw(terms);
  // A server that names the face: what it says is used.
  const p2 = JSON.parse(JSON.stringify(PAYLOADS["epoxy:Direct"]));
  p2.default_font = "Caladea";
  const pg2 = makePage(p2, {});
  pg2.api.resolveTemplateFonts(p2.blocks, p2.default_font);
  const est2 = pg2.api.renderBlock(p2.blocks.find((b) => b.id === estimator.id), { estimator_name: "X" });
  out.fonts = {
    face: face,
    estimator: { fonts: fontsIn(est), text: est.textContent, blockFont: est.style.fontFamily || "" },
    zetta: { fonts: fontsIn(z) },
    runless: { id: runless.id, blockFont: rl.style.fontFamily || "", typed: runless.typed_font || null },
    termsRunless: { id: termsRunless.id, blockFont: trl.style.fontFamily || "" },
    terms: { fonts: fontsIn(t) },
    named: { fonts: fontsIn(est2) },
    // The run the server left null is the one that changed; every run it named kept its font.
    nullRunsLeft: p.blocks.reduce((n, b) => n + (b.runs || []).filter((r) => !r.font).length, 0),
  };
}

// ═══ #10: the PRICE box's lines, as tall as they print ════════════════════════════════════════════
for (const key of Object.keys(PAYLOADS)) {
  const p = JSON.parse(JSON.stringify(PAYLOADS[key]));
  if (!p.blocks.some((b) => b.in_block === "single_bid")) continue;   // the staging rows' templates
  const { box, $ } = priceBox(p, { options: 1 });
  const map = layoutBox(box);
  const at = (el) => (el && map.has(el) ? Math.round(baselinePt(map, el) * 100) / 100 : null);
  const optLine = $("price-lines-block") && $("price-lines-block").children[0];
  const gapLines = $("options-gap") ? $("options-gap").children : [];
  const st = (el) => (el ? { mt: el.style.marginTop || "", mb: el.style.marginBottom || "",
                             margin: el.style.margin || "", lh: el.style.lineHeight || "" } : null);
  out["price:" + key] = {
    baselines: { heading_base: at($("base-bid-heading")), base: at($("base-bid-row")),
                 sales_tax: at($("sales-tax-row")), total: at($("total-row")),
                 options: at($("options-heading")), option: at(optLine) },
    styles: { heading_base: st($("base-bid-heading")), base: st($("base-bid-row")), total: st($("total-row")),
              options: st($("options-heading")), option: st(optLine), gap: gapLines.map(st) },
    gapLines: gapLines.length,
  };
}

// The gap's lines are copies of the ROW ABOVE the heading, never of a line typed on the gap. On the
// Polish file the two differ: its Total row is 1.15-spaced and its Options heading 1.25.
{
  const p = JSON.parse(JSON.stringify(PAYLOADS["polish:Direct"]));
  const { $ } = priceBox(p, { options: 1, pov: { before: { heading_options: ["A line typed on the gap"] } } });
  const gap = $("options-gap");
  const typed = gap && gap.parentNode ? gap.parentNode.children.filter((n) =>
    n.dataset.poKind === "extra" && n.dataset.poLinekey === "heading_options") : [];
  out.polishGap = {
    gap: (gap ? gap.children : []).map((n) => n.style.lineHeight || ""),
    typed: typed.map((n) => ({ text: n.textContent, lh: n.style.lineHeight || "",
                               mt: n.style.marginTop || "", mb: n.style.marginBottom || "" })),
    total: $("total-row") ? $("total-row").style.lineHeight || "" : null,
    heading: $("options-heading") ? $("options-heading").style.lineHeight || "" : null,
  };
}

// ═══ #11 / #12: what counts as running past the box ═══════════════════════════════════════════════
{
  const p = JSON.parse(JSON.stringify(PAYLOADS["epoxy:Direct"]));
  const run = (options) => {
    const { pg, box } = priceBox(JSON.parse(JSON.stringify(p)), { options: options });
    layoutBox(box);
    pg.api.fitTxbx(box);
    const map = layoutBox(box);
    return {
      options: options,
      designPx: Math.round(parseFloat(box.dataset.boxHPt) * PX_PER_PT * 10) / 10,
      contentPx: Math.round(map.boxH * PX_PER_PT * 10) / 10,     // what the old test measured
      inkPx: Math.round(pg.api.boxInkPx(box) * 10) / 10,
      overflow: box.classList.contains("tw-notes-overflow"),
      canGrow: box.classList.contains("tw-can-grow"),
      blocked: box.classList.contains("tw-grow-blocked"),
      boxEnd: box.style.getPropertyValue("--tw-box-end"),
      pg: pg, box: box,
    };
  };
  const strip = (r) => { const c = Object.assign({}, r); delete c.pg; delete c.box; return c; };
  // The audited job, and one with three more options: neither prints a word past the box.
  const audited = run(1), longer = run(4);
  // Twelve options do: the last ones print past the bottom edge.
  const over = run(12);
  // "Fit to text", pressed on the box that really runs over: it grows to the words, not past them
  // to the blank spacers under them.
  const fitted = run(7);
  const grew = fitted.pg.api.growBoxToFit(fitted.box);
  layoutBox(fitted.box);
  out.overflow = {
    audited: strip(audited), longer: strip(longer), over: strip(over),
    fit: Object.assign(strip(fitted), {
      grew: grew,
      grownHPt: Number(fitted.box.dataset.boxHPt),
      inkPt: Math.round(fitted.pg.api.boxInkPx(fitted.box) / PX_PER_PT * 100) / 100,
      boxEndAfter: fitted.box.style.getPropertyValue("--tw-box-end"),
    }),
    // No line laid out (the other harnesses' boxes): the box's own height decides, as before.
    unmeasured: (() => {
      LAYOUT = null;
      const pg = makePage(JSON.parse(JSON.stringify(p)), {});
      const b = new El("div"); b.className = "tw-txbx";
      const line = new El("p"); line.className = "tw-line-edit"; line.textContent = "words";
      b.appendChild(line);
      Object.defineProperty(b, "offsetHeight", { value: 321 });
      return { ink: pg.api.boxInkPx(b), content: pg.api.boxContentPx(b) };
    })(),
  };
}

process.stdout.write(JSON.stringify(out) + "\n");
