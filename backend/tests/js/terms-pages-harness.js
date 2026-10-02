"use strict";
/* The Proposal step draws the Terms pages and the WORK lines the way the fixed document prints
 * them -- RUN, not read.
 *
 * The audit of 2026-10-02 fixed the DOCUMENT (proposal_writer._rebuild_terms_pages and
 * _omit_bare_lines): the Terms are a section of their own whose header carries the letterhead on
 * every page, Kyle's padding lines and per-page art anchors are gone, his hand-split clauses are
 * joined back, and a WORK "Texture:" / "Notes:" line with nothing after its label is left out.
 * /api/proposal-template hands the editor the writer's own plan as `render_adjustments`. What this
 * harness executes is the page's half: the REAL initDocumentEditor (fetch stubbed with the real
 * /api/proposal-template payload test_terms_pages_editor.py hands it), renderPositioned,
 * repaginateTerms, applyTermsArt, applyTermsPlan, showTermsJoins, applyBareWorkLines,
 * renderSystemPreview, refreshDocumentFills, restoreSavedOverrides and collectOverrides, lifted
 * verbatim out of proposal-review.js. Each scenario reports what the page then shows -- the Terms
 * pages and what each holds, every line the plan hides, the joins, the art each page paints, and
 * the WORK lines -- and the test compares it with the .docx the real fill_proposal writes.
 *
 * THE ONE THING MODELLED BEYOND THE OTHER HARNESSES IS LAYOUT, because the pager measures. A line's
 * height is its paragraph's lines (a greedy word wrap over the advance widths the test reads off the
 * Terms face, argv[3]) times the line height the stylesheet gives it (the rules the test reads out
 * of styles.css, also argv[3]); an element hidden by `display: none` takes no room. It is a model
 * of a browser, not one: it is here so the pager's decisions -- which page a paragraph lands on,
 * how many pages there are -- are made on numbers, not stubs.
 *
 * Usage: node terms-pages-harness.js <frontend-dir> <cases.json>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const CASES = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
// Normalized to LF, like every harness here: the checkout is CRLF and the lifts anchor on "\n  ".
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");
const F = require(path.join(FRONTEND, "js", "proposal-format-core.js"));
globalThis.TWPrice = require(path.join(FRONTEND, "js", "price-lines-core.js"));

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

/** A top-level `const` whose value is a prose string with semicolons in it (topConst would cut it). */
function stringConst(name) {
  const m = new RegExp("\\n  const " + name + " =").exec(SRC);
  if (!m) throw new Error("const " + name + " is gone from proposal-review.js");
  const lines = SRC.slice(m.index + 1).split("\n");
  const kept = [];
  for (const line of lines) {
    kept.push(line);
    if (line.trimEnd().endsWith(";")) return kept.join("\n");
  }
  throw new Error("unterminated const " + name);
}

// ── the layout model (see the header) ─────────────────────────────────────────────────────────
const PX_PER_PT = 96 / 72;
const MODEL = CASES.model;           // {widths: {regular, bold, fallback}, normal_em, css: {...}}
const pt = (v) => parseFloat(String(v == null ? "" : v)) || 0;

function charEm(ch, bold) {
  const t = bold ? MODEL.widths.bold : MODEL.widths.regular;
  const w = t[ch];
  return typeof w === "number" ? w : MODEL.widths.fallback;
}

/** [{ch, bold}] of an element's text, in order, the way the page draws it: bold where a span (or a
 *  STRONG) says so, a "\n" for a BR, and the space the writer puts between two halves of a
 *  rejoined clause where the continuation carries `tw-join-sep`. */
function charsOf(el) {
  const out = [];
  const walk = (node, bold) => {
    for (const n of node.childNodes) {
      if (n.nodeType === Node.TEXT_NODE) {
        for (const ch of n.nodeValue) out.push({ ch: ch, bold: bold });
        continue;
      }
      if (n.tagName === "BR") { out.push({ ch: "\n", bold: bold }); continue; }
      if (n.style && n.style.display === "none") continue;
      const b = bold || n.tagName === "STRONG" || n.tagName === "B"
        || String(n.style && n.style.fontWeight) === "700";
      if (n.classList && n.classList.contains("tw-join-sep")) out.push({ ch: " ", bold: false });
      walk(n, b);
    }
  };
  walk(el, false);
  return out;
}

/** Lines a greedy wrap gives `chars` in `widthPt` at `sizePt`: a word goes to the next line when it
 *  does not fit; spaces at a line's end hang (pre-wrap); a "\n" breaks. 0 for no words at all. */
function wrapLines(chars, widthPt, sizePt) {
  if (!chars.some(c => c.ch.trim() || c.ch === "\n")) return 0;
  let lines = 1, x = 0, i = 0;
  const n = chars.length;
  while (i < n) {
    if (chars[i].ch === "\n") { lines++; x = 0; i++; continue; }
    let j = i, ww = 0;
    while (j < n && chars[j].ch !== " " && chars[j].ch !== "\n") { ww += charEm(chars[j].ch, chars[j].bold); j++; }
    let k = j, sw = 0;
    while (k < n && chars[k].ch === " ") { sw += charEm(" ", chars[k].bold); k++; }
    ww *= sizePt; sw *= sizePt;
    if (x > 0 && x + ww > widthPt + 0.01) { lines++; x = 0; }
    x += ww + sw;
    i = k;
  }
  return lines;
}

function pageOf(el) {
  let n = el;
  while (n && !(n.classList && n.classList.contains("tw-page"))) n = n.parentNode;
  return n;
}

/** The value a stylesheet length takes against a font size and a line height, in pt. */
function cssLen(v, fontPt, lhPt) {
  const s = String(v == null ? "" : v).trim();
  if (!s) return 0;
  if (/lh$/.test(s)) return pt(s) * lhPt;
  if (/em$/.test(s)) return pt(s) * fontPt;
  return pt(s);
}

function lineHeightPt(el) {
  const fontPt = MODEL.css.page_font_pt;
  const page = pageOf(el);
  let rule = MODEL.css.page_line_height;
  if (page && page.classList.contains("tw-terms-section") && MODEL.css.terms_line_height) {
    rule = MODEL.css.terms_line_height;
  }
  const own = el.style && el.style.lineHeight;
  const v = own || rule;
  if (v === "normal") return MODEL.normal_em * fontPt;
  if (/pt$/.test(String(v))) return pt(v);
  return Number(v) * fontPt;
}

function padding(el) {
  const p = String((el.style && el.style.padding) || "").trim().split(/\s+/).map(pt);
  const pick = (i) => (p.length === 4 ? p[i] : p.length === 1 ? p[0] : 0);
  return { top: pick(0), right: pick(1), bottom: pick(2), left: pick(3) };
}

/** An element's height in pt, in a page. */
function heightPt(el) {
  if (!el || !el.style || el.style.display === "none") return 0;
  const page = pageOf(el);
  const fontPt = MODEL.css.page_font_pt;
  const lh = lineHeightPt(el);
  const pad = page ? padding(page) : { left: 0, right: 0 };
  const contentW = (page ? pt(page.style.width) : 612) - pad.left - pad.right;
  const terms = !!(page && page.classList.contains("tw-terms-section"));
  if (el.classList.contains("tw-join")) {
    return wrapLines(charsOf(el), contentW - pt(el.style.paddingLeft), fontPt) * lh;
  }
  if (!el.classList.contains("tw-block")) {
    let h = 0;
    for (const c of el.children) h += heightPt(c);
    return h;
  }
  const width = contentW - pt(el.style.marginLeft) - pt(el.style.paddingLeft);
  const lines = wrapLines(charsOf(el), width, fontPt);
  if (!lines) {
    return cssLen(terms ? MODEL.css.terms_empty_min : MODEL.css.empty_min, fontPt, lh);
  }
  const floor = cssLen(terms ? MODEL.css.terms_block_min : MODEL.css.block_min, fontPt, lh);
  return Math.max(lines * lh, floor);
}

// ── the smallest DOM these functions touch ───────────────────────────────────────────────────
const Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
const unesc = (s) => String(s).replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, k) => ENTITIES[k]);

/** An inline style: camelCase properties plus custom properties behind setProperty. */
function makeStyle(css) {
  const st = {};
  const custom = {};
  for (const bit of String(css || "").split(";")) {
    const k = bit.indexOf(":");
    if (k < 0) continue;
    const raw = bit.slice(0, k).trim();
    const v = bit.slice(k + 1).trim();
    if (!raw) continue;
    if (raw.startsWith("--")) custom[raw] = v;
    else st[raw.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
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

function detach(n) {
  const p = n.parentNode;
  if (p) p.childNodes = p.childNodes.filter((c) => c !== n);
  n.parentNode = null;
}

class Text {
  constructor(v) { this.nodeType = Node.TEXT_NODE; this.nodeValue = String(v); this.parentNode = null; }
  get parentElement() { return this.parentNode; }
  get length() { return this.nodeValue.length; }
  remove() { detach(this); }
}

const VOID = new Set(["BR", "IMG", "HR", "INPUT"]);

class El {
  constructor(tag) {
    this.nodeType = Node.ELEMENT_NODE;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.style = makeStyle("");
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
      deleteProperty: (obj, k) => {
        delete obj[k];
        delete self.attrs["data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())];
        return true;
      },
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
  get id() { return this.attrs.id || ""; }
  set id(v) { this.attrs.id = String(v); }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n === ROOT; }
  appendChild(c) { detach(c); c.parentNode = this; this.childNodes.push(c); return c; }
  prepend(c) { detach(c); c.parentNode = this; this.childNodes.unshift(c); return c; }
  insertBefore(c, ref) {
    if (!ref) return this.appendChild(c);
    detach(c);
    const i = this.childNodes.indexOf(ref);
    if (i < 0) throw new Error("insertBefore: the reference node is not a child");
    c.parentNode = this;
    this.childNodes.splice(i, 0, c);
    return c;
  }
  removeChild(c) {
    if (c.parentNode !== this) throw new Error("removeChild: not a child");
    detach(c);
    return c;
  }
  remove() { detach(this); }
  get textContent() {
    return this.childNodes.map((n) => (n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent)).join("");
  }
  set textContent(v) {
    this.childNodes.forEach((n) => { n.parentNode = null; });
    this.childNodes = [];
    if (String(v) !== "") this.appendChild(new Text(v));
  }
  set innerHTML(html) {
    this.childNodes.forEach((n) => { n.parentNode = null; });
    this.childNodes = [];
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
          else if (a[1] === "style") el.style = makeStyle(v);
          else if (a[1] === "title") el.title = v;
          else if (a[1].startsWith("data-")) el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
        }
        top.appendChild(el);
        if (!VOID.has(el.tagName)) stack.push(el);
      } else if (m[4] !== undefined) top.appendChild(new Text(unesc(m[4])));
    }
  }
  get innerHTML() { return ""; }
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
  addEventListener(type, f) { (this._listeners[type] = this._listeners[type] || []).push(f); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; }
  normalize() {}
  // ── layout (see the header) ──
  get offsetHeight() { return Math.round(heightPt(this) * PX_PER_PT * 100) / 100; }
  get offsetTop() {
    const p = this.parentNode;
    if (!p || !(p.classList && p.classList.contains("tw-page"))) return 0;
    let y = padding(p).top;
    for (const c of p.children) {
      if (c === this) break;
      y += heightPt(c);
    }
    return Math.round(y * PX_PER_PT * 100) / 100;
  }
  get clientHeight() {
    const h = String(this.style.height || "");
    if (/pt$/.test(h)) return pt(h) * PX_PER_PT;
    let sum = padding(this).top + padding(this).bottom;
    for (const c of this.children) sum += heightPt(c);
    return Math.max(sum, pt(this.style.minHeight)) * PX_PER_PT;
  }
}

const ROOT = new El("div");
const getComputedStyle = (el) => {
  const p = padding(el);
  return { paddingTop: p.top * PX_PER_PT + "px", paddingBottom: p.bottom * PX_PER_PT + "px",
           paddingLeft: p.left * PX_PER_PT + "px", paddingRight: p.right * PX_PER_PT + "px" };
};

// ── the page under test, one fresh copy per scenario ─────────────────────────────────────────
const LIFTED = [
  topConst("escHtml"), topConst("DOC_TOKEN_RE"), topConst("sameFmt"),
  topConst("TWIPS_PER_PT"), topConst("INDENT_STEP_TW"), topConst("INDENT_MAX_TW"),
  topConst("SINGLE_LINE_EM"), topConst("DOC_DEFAULT_FONT"),
  topConst("LINE_SEL"), topConst("focusInside"),
  stringConst("_OVERRIDE_TITLE"), topConst("_SYS_ROW_LINE_FIELDS"), stringConst("_SYS_LINE_TITLE"),
  topConst("PRICE_TOKENS"), topConst("PRICE_AMOUNT_TOKENS"), stringConst("_MONEY_TITLE"),
  topConst("overrideKey"), topConst("liveKey"), topConst("focusInTerms"),
  fn("effectiveWorkType"), fn("withTokenDefaults"),
  fn("fillHtml"), fn("fillPlain"), fn("runStyleCss"), fn("blockHtml"), fn("singleTokenHint"),
  fn("setBlockContent"), fn("priceRowVisibility"), fn("isNumberedClause"), fn("blanksANumberedClause"),
  fn("renderBlock"), fn("annotateRegions"), fn("mountRegionPreviews"), fn("renderBlockList"),
  fn("applyParaGeom"), fn("paraLineHeight"), fn("applyParaSpacing"),
  fn("takesPriceStep"), fn("isPriceLine"), fn("applyParaToEl"), fn("setParaState"),
  fn("paraBase"), fn("paraNow"), fn("paraPatch"), fn("sanitizeParaPatch"),
  fn("fmtAt"), fn("segmentsOf"), fn("mergeSegs"), fn("serializeRuns"), fn("editRuns"),
  fn("runEditCss"), fn("renderRuns"), fn("serializeBlock"), fn("runsArePlain"),
  fn("storedRuns"), fn("storedText"), fn("isPriceParagraph"), fn("priceParagraphMoneyOff"),
  fn("migratePriceParagraphText"),
  fn("mergeOverrideEntry"), fn("savedOverridesFor"), fn("savedVersionMatches"),
  fn("restoreSavedOverrides"), fn("lineBare"), fn("lineKeptEmpty"), fn("collectOverrides"),
  fn("preserveRichOverrides"), fn("removedBlockIds"), fn("removeLine"), fn("unremoveLine"),
  fn("lineRemovable"), fn("lineIsEmpty"), fn("boxLines"), fn("lineShown"), fn("editingBox"),
  fn("lineAt"), fn("lineAtSelection"),
  fn("effectiveBoxRect"), fn("applyBoxGeom"), fn("resolveTemplateFonts"),
  // The WORK {{#system}} rows: renderSystemPreview builds them and hides a bare Texture row.
  fn("sheetSystems"), fn("sysRowTemplate"), fn("sysRowStyle"), fn("sysRowSizePt"),
  fn("workLabelHtml"), fn("renderSystemPreview"),
  // A sidebar field changed: the real refresh path, which re-fills the untouched lines and asks
  // the WORK lines again.
  fn("refreshFillsInPlace"), fn("refreshPriceFillsInPlace"), fn("refreshDocumentFills"),
  // The render and the pager.
  fn("renderPositioned"), fn("applyTermsArt"), fn("repaginateTerms"), fn("scheduleRepaginate"),
  // The plan, applied.
  fn("readRenderAdjustments"), fn("termsPlanFor"), fn("setRenderHidden"), fn("termsWords"),
  fn("termsLinePrintsNothing"), fn("termsLineIsListed"), fn("joinedTermsText"), fn("termsUnitOf"),
  fn("termsUnitHolds"), fn("applyTermsPlan"), fn("showTermsJoins"), fn("workLineBare"),
  fn("applyBareWorkLines"),
  fn("initDocumentEditor"),
].join("\n\n");

function makePage(sc) {
  const docSurface = new El("div");
  docSurface.id = "doc-surface";
  ROOT.childNodes = [];
  ROOT.appendChild(docSurface);
  const STORE = { blob: JSON.parse(JSON.stringify(sc.state || {})) };
  const FORM = Object.assign({}, sc.form || {});
  const SEL = { node: null };
  const rec = { art: [], band: [], zoom: 0, fit: 0, persist: 0, errors: [] };
  const document = {
    createElement: (t) => new El(t),
    activeElement: null,
    body: new El("body"),
    getElementById: () => null,
    querySelectorAll: (s) => ROOT.querySelectorAll(s),
  };
  const window = {
    addEventListener() {},
    getSelection: () => (SEL.node
      ? { rangeCount: 1, getRangeAt: () => ({ startContainer: SEL.node, endContainer: SEL.node, collapsed: true }) }
      : { rangeCount: 0 }),
  };
  const TW = {
    getState: () => JSON.parse(JSON.stringify(STORE.blob)),
    setState: (o) => { STORE.blob = Object.assign(JSON.parse(JSON.stringify(STORE.blob)), o || {}); return STORE.blob; },
    readForm: () => Object.assign({}, FORM),
    authHeaders: () => ({}),
  };
  const PAYLOAD = sc.payload;
  const BASE_TOKENS = sc.tokens || {};
  const BAND = sc.band == null ? 54 : sc.band;
  const console = { error: (...a) => rec.errors.push(a.map(String).join(" ")), log() {}, warn() {} };
  const api = new Function(
    "document", "window", "docSurface", "TW", "F", "Node", "getComputedStyle", "rec", "console",
    "PAYLOAD", "BASE_TOKENS", "BAND", "El",
    `const state = TW.getState();
    const form = null;
    const RUN_KEYS = F.RUN_KEYS;
    const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;
    const TOKEN_HINTS = {};
    let templateBlocks = null, _lastTokens = null, templateVersion = "", templateLegacyFloorS = 0;
    let templatePredecessors = [], templateTokenDefaults = {}, templateOptionsHeadingIds = [];
    let templateAdjustments = null;
    let templateDefaultFont = "Cambria";
    let pageWpt = 612, flowMode = false, boxLimits = null;
    const blockById = new Map(), pristineById = new Map(), paraById = new Map();
    const boxDesign = new Map();
    let boxOverrides = new Map();
    const boxFitById = new Map();
    let _fitSig = "";
    let _termsUnits = null, _termsGeom = null, _termsArtUrl = null;
    const _termsBandCache = new Map();
    let _repagTimer = null, _repagPending = false, _fillsTimer = null;
    let fmtBlock = null;
    // Debounces collapsed to "run now": what is under test is what the page SHOWS once it settles.
    const setTimeout = (f) => { f(); return 1; };
    const clearTimeout = () => {};
    const fetch = async () => ({ ok: true, json: async () => JSON.parse(JSON.stringify(PAYLOAD)) });
    // The live price islands live in #price-preview-staging, which price-lines-harness.js builds;
    // this page mounts the two WORK/NOTES previews and nothing else.
    const systemPreviewEl = document.createElement("div");
    systemPreviewEl.id = "system-preview-block";
    const notesPreviewEl = document.createElement("div");
    notesPreviewEl.id = "notes-preview-block";
    const REGION_MOUNTS = { system: () => [systemPreviewEl], notes: () => [notesPreviewEl] };
    // What computeTokenValues gives these scenarios: the case's values plus the two WORK fields as
    // the sidebar has them now (the line-under-test inputs).
    const computeTokenValues = (m) => Object.assign({}, BASE_TOKENS,
      { texture: String((m && m.texture) || ""), work_notes: String((m && m.work_notes) || "") });
    // Not this harness's world, each for the reason its own harness gives.
    const clearDocSurface = () => { docSurface.childNodes.forEach(n => { n.parentNode = null; }); docSurface.childNodes = []; };
    const addBoxTools = () => {};
    const applyZoom = () => { rec.zoom += 1; };
    const loadBoxOverrides = () => { boxOverrides = new Map(); };
    const renderFlow = () => { throw new Error("renderFlow reached: these payloads all have boxes"); };
    const renderNotesPreview = () => {};
    const refreshPriceDisplay = () => {};
    // initDocumentEditor's failure path mounts the staging panel; a scenario that reaches it has
    // failed, and says so through console.error (rec.errors).
    const stagingPanel = document.createElement("div");
    const renderFmtBar = () => {};
    const showFmtBar = () => {};
    const idleFmtBar = () => { fmtBlock = null; };
    const markEdited = () => {};
    const selectionRange = () => null;
    const placeSelection = () => {};
    const scheduleFit = () => { rec.fit += 1; };
    const schedulePersistOverrides = () => { rec.persist += 1; };
    const isAutoGrown = () => false;
    // The letterhead art: the real route is /api/proposal-template/media behind the login; what
    // matters here is WHICH media each page asks for, so the answer is a data: URI naming it.
    const artUrl = (name) => { rec.art.push(String(name)); return Promise.resolve("data:" + String(name)); };
    // The old pager's logo band is scanned off the art with a canvas; recorded, and answered with
    // the band the scenario names, so the old page's packing still runs on a real reserve.
    const measureTermsBand = (u, name) => { rec.band.push(String(name)); return Promise.resolve(BAND); };
` + LIFTED + `
    return {
      init: () => initDocumentEditor(),
      repaginate: () => repaginateTerms(),
      bare: () => applyBareWorkLines(),
      refresh: () => refreshDocumentFills(),
      collect: () => collectOverrides(),
      serialize: (el) => serializeBlock(el),
      systemPreviewEl: systemPreviewEl,
      adjustments: () => templateAdjustments,
      termsGeom: () => _termsGeom,
    };`
  )(document, window, docSurface, TW, F, Node, getComputedStyle, rec, console, PAYLOAD, BASE_TOKENS, BAND, El);
  return { api, docSurface, document, SEL, FORM, STORE, rec };
}

const flush = () => new Promise((r) => setImmediate(r));

/** What the page shows, read off the DOM. */
function report(pg) {
  const { api, docSurface, rec } = pg;
  const blockEls = docSurface.querySelectorAll(".tw-block");
  const hidden = blockEls.filter(el => el.style.display === "none").map(el => Number(el.dataset.id));
  const planHidden = blockEls.filter(el => el.dataset.twRenderHidden === "1").map(el => Number(el.dataset.id));
  const unitText = (u) => {
    if (u.classList.contains("tw-join")) {
      return u.children.map(c => (c.classList.contains("tw-join-sep") ? " " : "") + api.serialize(c)).join("");
    }
    return api.serialize(u);
  };
  const unitIds = (u) => (u.classList.contains("tw-join") ? u.children : [u])
    .map(c => (c.dataset && c.dataset.id != null ? Number(c.dataset.id) : null));
  const pages = docSurface.querySelectorAll(".tw-terms-page").map(p => ({
    cls: p.className,
    width: p.style.width, height: p.style.height, padding: p.style.padding, font: p.style.fontFamily || "",
    bg: p.style.backgroundImage || "", bgSize: p.style.backgroundSize || "",
    bgPos: p.style.backgroundPosition || "", bgRepeat: p.style.backgroundRepeat || "",
    imgs: p.querySelectorAll("img").length,
    units: p.children.map(u => ({ ids: unitIds(u), join: u.classList.contains("tw-join"),
                                  shown: u.style.display !== "none", top: u.offsetTop, h: u.offsetHeight })),
    // Each unit's words as the writer's `_own_text` reads a paragraph: a line break is a w:br, not
    // text. (`raw` keeps them.)
    shown: p.children.filter(u => u.style.display !== "none").map(u => unitText(u).replace(/\n/g, "")),
    raw: p.children.filter(u => u.style.display !== "none").map(unitText),
  }));
  const joins = docSurface.querySelectorAll(".tw-join").map(w => ({
    ids: unitIds(w),
    head: w.children[0] && w.children[0].classList.contains("tw-join-head"),
    tails: w.children.slice(1).map(c => c.classList.contains("tw-join-tail")),
    seps: w.children.slice(1).map(c => c.classList.contains("tw-join-sep")),
    padding: w.style.paddingLeft, hang: w.style.getPropertyValue("--tw-join-hang"),
  }));
  const p1 = docSurface.children.find(p => !p.classList.contains("tw-terms-page"));
  const sys = api.systemPreviewEl.querySelectorAll("[data-sys-line]").map(r => ({
    line: r.dataset.sysLine, index: Number(r.dataset.sysIndex), text: api.serialize(r),
    hidden: r.style.display === "none",
  }));
  const geom = api.termsGeom();
  return {
    pages, joins, hidden, planHidden, sys,
    page1Art: p1 ? p1.querySelectorAll("img").map(i => i.src) : [],
    terms: pages.reduce((acc, p) => acc.concat(p.shown), []),
    art: rec.art.slice(), band: rec.band.slice(), errors: rec.errors.slice(),
    plan: !!(geom && geom.plan),
    blockText: Object.fromEntries(blockEls.map(el => [el.dataset.id, api.serialize(el)])),
  };
}

async function run(sc) {
  const pg = makePage(sc);
  const out = { steps: [] };
  const byId = (id) => pg.docSurface.querySelector('.tw-block[data-id="' + Number(id) + '"]');
  for (const st of [{ op: "init" }].concat(sc.steps || [])) {
    if (st.op === "init") { await pg.api.init(); await flush(); await flush(); }
    else if (st.op === "repaginate") pg.api.repaginate();
    else if (st.op === "bare") pg.api.bare();
    else if (st.op === "form") { Object.assign(pg.FORM, st.values || {}); }
    else if (st.op === "refresh") { pg.api.refresh(); await flush(); }
    else if (st.op === "type") { const el = byId(st.id); if (!el) throw new Error("no block " + st.id); el.textContent = st.text; }
    else if (st.op === "caret") {
      // A caret in a template paragraph (`id`), in a WORK {{#system}} row (`sys`), or nowhere.
      pg.SEL.node = st.sys ? pg.api.systemPreviewEl.querySelector('[data-sys-line="' + st.sys + '"]')
        : (st.id == null ? null : byId(st.id));
      if ((st.sys || st.id != null) && !pg.SEL.node) throw new Error("no line for the caret: " + JSON.stringify(st));
    }
    else if (st.op === "collect") out.collect = pg.api.collect();
    else if (st.op === "snap") out.steps.push(Object.assign({ label: st.label || "" }, report(pg)));
    else throw new Error("unknown step " + st.op);
  }
  out.final = report(pg);
  return out;
}

(async () => {
  const res = {};
  for (const sc of CASES.scenarios) {
    try { res[sc.name] = await run(sc); }
    catch (e) { res[sc.name] = { error: String(e && e.stack || e) }; }
  }
  process.stdout.write(JSON.stringify(res));
})();
