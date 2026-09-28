"use strict";
/* The PRICE box's bullets and indents, as the editor DRAWS them, run rather than read.
 *
 * Hanz, 2026-09-26: "fix the indents and the bullets now". Before it: "I couldnt add an indendt and
 * bullet" and "also the bullet point and the indent are not working in the pricing box". The ribbon
 * let go of every price line, and the document stripped every PRICE bullet whatever anybody set.
 * Kyle's REBID layout (Hanz, 2026-09-25) is now the default: a red square on every money line, the
 * hollow "o" on a line typed under one, nothing on a heading or a blank line — and the ribbon's
 * Bullet / Indent / Outdent / Reset act on the price line the caret is on.
 *
 * THE CLAIM UNDER TEST IS A COMPARISON: what the editor shows is what the customer's document
 * prints, line for line — text, bullet on or off, which level, where the text starts, and the blank
 * lines between. So this builds the editor's PRICE box through the page's own code, over the real
 * template's blocks (the caller walks /api/proposal-template for them): renderBlockList mounts the
 * template paragraphs and the priced regions exactly as a page load does, refreshPriceDisplay
 * paints the price lines, the options, the gap and the bullets. It then presses the ribbon's buttons
 * through paraAction — the function the ribbon's click handler calls — and reports:
 *
 *   lines    every line the box shows, in order: {text, bullet, level, indent_tw, blank}
 *   payload  what the page hands /api/generate for the box: the token values (computeTokenValues),
 *            price_overrides (the sweep's), paragraph_overrides (paraPatch over every block, as
 *            collectOverrides builds them) and the combo lines
 *   ribbon   for a press made THROUGH THE RIBBON (a `ribbon` action): the ribbon's state when the
 *            caret lands on the line (the page's own focusin handler aims it) and after the click
 *            on the button (the ribbon's own click handler) — which buttons are live, which pressed
 *   reload   the same box drawn again on a NEW page from nothing but the saved draft — the price
 *            lines from price_overrides, the template rows through setParaState, the one line
 *            restoreSavedOverrides uses — so "it survives a reload" is the same comparison again.
 *
 * test_price_bullets.py renders the payload through the real renderer and compares.
 *
 * THE DOM IS THE SHIM price-lines-harness.js uses (a full DOM lets a missing binding hide behind a
 * stub). The one thing it cannot do is apply a stylesheet, so a line's geometry is read off its
 * INLINE style, which is where the page puts it (paintLineParas, applyParaGeom); a shown line with
 * no inline geometry is reported (`unstyled`) rather than guessed at.
 *
 * Usage: node price-bullets-harness.js <frontend-dir> < cases.json   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8").replace(/\r\n/g, "\n");
const HTML = fs.readFileSync(path.join(FRONTEND, "proposal-review.html"), "utf8").replace(/\r\n/g, "\n");
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
/** A one-line string const, read as a whole LINE (a semicolon inside the string would cut
 *  topConst's scan short). */
function lineConst(name) {
  const m = new RegExp("\n  const " + name + " = .*").exec(SRC);
  if (!m) throw new Error("const " + name + " is gone from proposal-review.js");
  return m[0].slice(1);
}
/** A delegated keydown handler's body, by a line inside it. */
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
/** A delegated listener that takes no event (`() => { … }`), by a line inside it. */
function listenerAround(anchor) {
  const i = SRC.indexOf(anchor);
  if (i < 0) throw new Error("the listener holding " + JSON.stringify(anchor) + " is gone");
  const start = SRC.lastIndexOf("() => {", i);
  const open = SRC.indexOf("{", start);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return "() => " + SRC.slice(open, j + 1);
  }
  throw new Error("unbalanced braces after " + anchor);
}

// ── the smallest DOM this code touches (price-lines-harness.js's shim) ──────────────────────────
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
const VOID = new Set(["BR", "IMG", "HR", "INPUT"]);
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
        if (!VOID.has(el.tagName)) stack.push(el);
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
function fire(node, type, props) {
  const e = Object.assign({ type, target: node, preventDefault() { this.defaulted = true; } }, props || {});
  e.type = type; e.target = e.target || node;
  for (let cur = node; cur; cur = cur.parentNode) for (const f of (cur._listeners[type] || []).slice()) f(e);
  return e;
}
class Ev { constructor(type, opts) { this.type = String(type); this.bubbles = !!(opts && opts.bubbles); this.target = null; } }

// ── the real units ───────────────────────────────────────────────────────────────────────────────
const UNITS = [
  topConst("fmtUSD"), topConst("fmtUSDdoc"), topConst("fmtSF"), lineConst("_OVERRIDE_TITLE"),
  topConst("COMPUTED_PRICE_LINE_KEYS"), lineConst("_LIVE_TITLE"), lineConst("_MONEY_TITLE"),
  topConst("_escLine"), topConst("GYP_BASE"), topConst("LINE_SEL"),
  topConst("escHtml"), topConst("DOC_TOKEN_RE"),
  topConst("INDENT_STEP_TW"), topConst("INDENT_MAX_TW"), topConst("TWIPS_PER_PT"),
  topConst("PRICE_TOKENS"), topConst("PRICE_AMOUNT_TOKENS"),
  // The price rule's page half, and the price lines the page composes.
  fn("effectiveWorkType"), fn("basePriceSystem"), fn("taxLayout"), fn("taxTreatmentMode"),
  fn("baseTaxRule"), fn("printedTaxRows"), fn("baseBidFigure"),
  fn("lineOverride"), fn("lineValue"), fn("lineCue"),
  fn("linePropsOf"), fn("paintLineParas"), fn("extraLinesHtml"), fn("lineEl"),
  fn("paintExtras"), fn("makeExtraLine"), fn("caretInto"), fn("splitPriceLine"), fn("mergePriceLine"),
  fn("paintLine"), fn("comboSystemLines"), fn("comboLinesForPayload"), fn("baseDescLabel"),
  fn("refreshPriceDisplay"), fn("renderProposalExtras"), fn("computeTokenValues"),
  fn("_ensurePov"), fn("priceRowLive"), fn("captureLineNode"), fn("captureExtrasIn"),
  fn("syncPriceLinesIn"), fn("serializeBlock"),
  // editRuns is what the keydown handlers measure a line by (Backspace's ladder, Delete at its end).
  fn("fmtAt"), topConst("sameFmt"), fn("segmentsOf"), fn("mergeSegs"), fn("editRuns"),
  fn("lineAt"), fn("lineAtSelection"), fn("lineTarget"), fn("editingBox"),
  // The blank lines above the Options heading (drawn by the option writer).
  fn("optionsGapCount"), fn("optionsGapTyped"), fn("isGapTyped"), fn("gapTypedEls"),
  fn("optionsHeadingEl"), fn("aboveOptionsGap"), fn("gapShown"), fn("paintOptionsGap"),
  fn("paintGapTyped"),
  // The gap takes in a blank template line above the heading, never one he emptied and KEPT
  // (the editor-parity branch).
  fn("lineBare"), fn("lineKeptEmpty"),
  // The template's own paragraphs, mounted the way a page load mounts them: the free paragraphs
  // through renderBlock, the priced regions through their staging islands.
  topConst("REGION_MOUNTS"),
  fn("annotateRegions"), fn("mountRegionPreviews"), fn("renderBlockList"),
  fn("fillHtml"), fn("fillPlain"), fn("runStyleCss"), fn("blockHtml"), fn("singleTokenHint"),
  fn("setBlockContent"), fn("priceRowVisibility"), fn("renderBlock"),
  // The paragraph controls, and the ribbon's one entry point into them.
  fn("paraBase"), fn("paraNow"), fn("paraPatch"), fn("sanitizeParaPatch"),
  fn("applyParaGeom"), fn("applyParaToEl"), fn("setParaState"),
  fn("isPriceLine"), fn("takesPriceStep"), fn("priceLineAction"), fn("paraAction"),
  // The ribbon: built, aimed and pressed by the page's own code. A price line takes the early branch
  // of renderFmtBar, so the run-formatting half (selectionFormat and friends) is never reached here.
  topConst("SIZE_CHOICES"), fn("icon"), fn("ensureFmtBar"), fn("fmtTargetBlock"), fn("markFmtTarget"),
  fn("renderFmtBar"), fn("showFmtBar"), fn("idleFmtBar"),
  // The Backspace / Delete handler asks the editor-parity branch's line-removal family first: a
  // caret in a hidden line moves to one shown (lineShown / caretToLine), and an EMPTY line may be
  // taken out (lineRemovable reads the block's `fit.removable`, removeLineAt does it). Lifted,
  // not stubbed, so a price-box Backspace here meets the rule the page applies.
  fn("boxLines"), fn("lineShown"), fn("pointAt"), fn("lineIsEmpty"), fn("lineRemovable"), fn("removeLine"),
  fn("adjacentLine"), fn("caretToLine"), fn("removeLineAt"),
].join("\n\n");
const ENTER = handlerAround("// A PRICE line (or a line typed next to one): a new line of its own");
// The ribbon's aim: focus landing on a line is what points it there.
const FOCUSIN = handlerAround("const el = line && (line.classList.contains(\"tw-block\") || isPriceLine(line)) ? line : null;");
// ...and the caret moving within a box that already has focus (no focusin fires then).
const SELCHANGE = listenerAround("MOVING THE CARET BETWEEN PARAGRAPHS IS NOW A SELECTION CHANGE");
// Tab / Shift+Tab, and Backspace / Delete at a line's edge: the page's own keydown handlers.
const TAB = handlerAround("const rung = e.shiftKey ? \"outdent\" : \"indent\";");
const BACKSPACE = handlerAround("const back = e.key === \"Backspace\", fwd = e.key === \"Delete\";");

/** The staging islands, as proposal-review.html declares them. */
function stagingIslands() {
  const a = HTML.indexOf('<div id="price-preview-staging"');
  const staging = HTML.slice(HTML.indexOf(">", a) + 1, HTML.indexOf("\n</div>\n", a));
  const holder = new El("div");
  holder.innerHTML = staging.replace(/<!--[\s\S]*?-->/g, "");
  holder.attrs.id = "price-preview-staging";
  return holder;
}

/** One page over one draft. The box is the PRICE text box; the case's blocks are its paragraphs. */
function build(c, st) {
  const docSurface = new El("div");
  docSurface.attrs.id = "doc-surface";
  const box = new El("div");
  box.className = "tw-txbx";
  docSurface.appendChild(box);
  const staging = stagingIslands();
  const byId = (root, id) => {
    if (root.attrs && root.attrs.id === id) return root;
    for (const ch of root.children) { const hit = byId(ch, id); if (hit) return hit; }
    return null;
  };
  const SEL = { el: null, at: [0, 0] };
  const persists = [];
  const document = {
    querySelector: (sel) => (sel === "#tb-total" ? { textContent: "$" + Number(st.proposal_lump_sum).toFixed(2) } : null),
    getElementById: (id) => byId(docSurface, id) || byId(staging, id),
    createElement: (t) => new El(t),
    createRange: () => ({ setStart(n, k) { this.n = n; this.k = k; }, collapse() {} }),
    activeElement: null,
    body: new El("body"),
    _listeners: {},
    addEventListener(type, f) { (this._listeners[type] = this._listeners[type] || []).push(f); },
  };
  const win = {
    getSelection: () => ({
      rangeCount: SEL.el ? 1 : 0,
      getRangeAt: () => ({ startContainer: SEL.el, collapsed: SEL.at[0] === SEL.at[1] }),
      removeAllRanges() { SEL.el = null; },
      addRange(r) { SEL.el = r.n; SEL.at = [r.k, r.k]; },
    }),
    TWAuth: null,
  };
  const body = [
    "const RUN_KEYS = F.RUN_KEYS;",
    "const runsLength = F.runsLength;",
    "let templateOptionsHeadingIds = OPTIONS_HEADING_IDS;",
    "const TOKEN_HINTS = {};",
    "let flowMode = false;",
    "const blockById = new Map();",
    "const pristineById = new Map();",
    "const paraById = new Map();",
    // Detached, as they are on a page whose WORK / NOTES previews live in another box.
    "const systemPreviewEl = document.createElement('div');",
    "const notesPreviewEl = document.createElement('div');",
    // Box fitting is the editor-parity workflow's, and the page wraps this call in try/catch.
    "const fitTxbx = () => {};",
    "const scheduleRepaginate = () => {};",
    "const schedulePersistOverrides = () => { persists.push('para'); };",
    "const selectionRange = (el) => (SEL.el === el ? SEL.at.slice() : null);",
    "const placeSelection = (el, a, b) => { SEL.el = el; SEL.at = [a, b]; };",
    "const selectionLines = () => [];",
    "const spliceLines = () => { throw new Error('multi-line splice reached'); };",
    "const insertBreakAt = () => { throw new Error('a break was put INSIDE a price line'); };",
    "const markEdited = () => {};",
    "let fmtBar = null, fmtBlock = null, fmtRange = null, fmtRangeText = null;",
    "let boxSel = null;",
    "let _fmtBusy = false;",
    // The undo stack is editor-undo-harness.js's; a removal here records nothing.
    "const undoPush = () => false;",
    UNITS,
    "docSurface.addEventListener('keydown', " + ENTER + ");",
    "docSurface.addEventListener('keydown', " + TAB + ");",
    "docSurface.addEventListener('keydown', " + BACKSPACE + ");",
    "docSurface.addEventListener('focusin', " + FOCUSIN + ");",
    "document.addEventListener('selectionchange', " + SELCHANGE + ");",
    // The box sweep and the bullets' repaint, as the page's delegated input handler runs them.
    "docSurface.addEventListener('input', (e) => { const b = editingBox(e.target); if (b) { syncPriceLinesIn(b); paintLineParas(b); } });",
    "return { refreshPriceDisplay, computeTokenValues, comboLinesForPayload, annotateRegions,",
    "         renderBlockList, serializeBlock, paraAction, paraPatch, setParaState, paintLineParas,",
    "         blockById, paraById, bar: () => ensureFmtBar(), aimedAt: () => fmtBlock };",
  ].join("\n");
  const api = new Function("state", "document", "window", "form", "TW", "templateBlocks", "docSurface",
                           "focusInside", "queuePovSave", "F", "Node", "Event", "SEL", "persists",
                           "OPTIONS_HEADING_IDS", body)(
    st, document, win, { querySelector: () => null },
    { readForm: () => ({}), setState: () => {} }, c.blocks, docSurface,
    () => false, () => {}, F, Node, Ev, SEL, persists, c.options_heading_ids || []);
  // A page load: the blocks registered, the box rendered, the prices painted.
  const blocks = c.blocks.map((b) => Object.assign({}, b));
  api.annotateRegions(blocks);
  for (const b of blocks) api.blockById.set(b.id, b);
  const tokens = api.computeTokenValues(Object.assign({}, st));
  api.renderBlockList(box, blocks, tokens);
  api.refreshPriceDisplay();
  // A draft saved earlier (before this change, say): its template rows' `para` go back through
  // setParaState, the call restoreSavedOverrides makes for every saved entry.
  for (const o of (c.saved_paragraph_overrides || [])) {
    const el = box.querySelector('.tw-block[data-id="' + o.id + '"]');
    if (el) api.setParaState(o.id, o.para, el);
  }
  return { api, box, docSurface, SEL, tokens, persists, document };
}

const pt = (v) => {
  const m = /^(-?[\d.]+)pt$/.exec(String(v == null ? "" : v).trim());
  return m ? Number(m[1]) : (String(v || "").trim() === "0" ? 0 : null);
};
function hiddenEl(el) {
  return (el.style && el.style.display === "none") || el.attrs.hidden !== undefined
    || el.classList.contains("tw-gap-absorbed");
}
function isLine(el) {
  const d = el.dataset || {};
  return el.classList.contains("tw-block") || el.classList.contains("tw-gap-line")
    || ((d.poKind === "line" || d.poKind === "extra") && !!d.poLinekey);
}
/** Every line the box shows, in order. */
function linesOf(pg) {
  const out = [];
  const walk = (n) => {
    for (const ch of n.children) {
      if (hiddenEl(ch)) continue;
      if (isLine(ch)) out.push(describe(pg, ch));
      else walk(ch);
    }
  };
  walk(pg.box);
  return out;
}
function describe(pg, el) {
  const text = el.classList.contains("tw-gap-line") ? "" : pg.api.serializeBlock(el).replace(/\n+$/, "");
  const blank = !text.trim();
  // The square / "o" is `.tw-li::before`; an emptied template row draws none
  // (`.tw-block.tw-empty.tw-li::before { content: none }`).
  const drawn = el.classList.contains("tw-li")
    && !(el.classList.contains("tw-block") && el.classList.contains("tw-empty"));
  const ml = pt(el.style.marginLeft), pl = pt(el.style.paddingLeft), ti = pt(el.style.textIndent);
  const d = el.dataset || {};
  return {
    text, blank,
    bullet: drawn && !blank,
    // What the page DREW, blank line or not: the square / "o" of a price line that is not a
    // template block shows on an empty line too, so a blank line with tw-li would show one.
    drawn,
    level: drawn && !blank ? (el.classList.contains("tw-lvl-o") ? 1 : 0) : null,
    // Where the words start (margin + the padding the square sits in), and how far the FIRST line
    // starts from there (text-indent: a first-line indent, or a hanging one when negative).
    indent_tw: (ml == null && pl == null) ? null : Math.round(((ml || 0) + (pl || 0)) * 20),
    first_tw: Math.round((ti || 0) * 20),
    unstyled: !blank && ml == null && pl == null,
    key: d.poLinekey || null, kind: d.poKind || (el.classList.contains("tw-block") ? "block" : "gap"),
    id: el.classList.contains("tw-block") ? Number(d.id) : null,
  };
}

/** The line the ribbon is aimed at, as {key, kind, text, id}, or null when it is idle. */
function aimOf(pg) {
  const el = pg.api.aimedAt();
  if (!el) return null;
  const d = el.dataset || {};
  return { key: d.poLinekey || null, kind: d.poKind || (el.classList.contains("tw-block") ? "block" : null),
           text: pg.api.serializeBlock(el), id: el.classList.contains("tw-block") ? Number(d.id) : null };
}

/** The ribbon, as the estimator sees it: each control live or not, pressed or not. */
function barState(pg) {
  const bar = pg.api.bar();
  const out = {};
  for (const b of bar.querySelectorAll("button")) {
    const k = b.dataset.para || b.dataset.fmt;
    out[k] = { disabled: !!b.disabled, pressed: b.getAttribute("aria-pressed") || null,
               on: b.classList.contains("on"), visibility: (b.style && b.style.visibility) || "" };
  }
  const size = bar.querySelector("input[data-fmt='size']");
  out.size = { disabled: !!(size && size.disabled) };
  return out;
}

/** The line an action is aimed at. */
function target(pg, on) {
  if (on.gap != null) {
    const gap = pg.box.querySelectorAll(".tw-gap-line")[on.gap];
    if (!gap) throw new Error("no blank line " + on.gap + " in the Options gap");
    return gap;
  }
  const all = [];
  const walk = (n) => { for (const ch of n.children) { if (isLine(ch)) all.push(ch); walk(ch); } };
  walk(pg.box);
  const hit = all.find((el) => {
    const d = el.dataset || {};
    if (on.key != null) {
      if (d.poLinekey !== on.key) return false;
      if ((on.kind || "line") !== d.poKind) return false;
      if (on.kind === "extra") {
        const same = all.filter((x) => x.dataset.poLinekey === on.key && x.dataset.poKind === "extra"
                                       && (x.dataset.poPos || "after") === (on.pos || "after"));
        return same[on.idx || 0] === el;
      }
      return true;
    }
    if (on.starts != null) return el.classList.contains("tw-block") && pg.api.serializeBlock(el).startsWith(on.starts);
    return false;
  });
  if (!hit) throw new Error("no line for " + JSON.stringify(on));
  return hit;
}

function payloadOf(pg, st) {
  const paragraph_overrides = [];
  for (const id of pg.api.blockById.keys()) {
    const para = pg.api.paraPatch(id);
    if (para) paragraph_overrides.push({ id, para });
  }
  return {
    values: pg.api.computeTokenValues(Object.assign({}, st)),
    price_overrides: JSON.parse(JSON.stringify(st.price_overrides || {})),
    paragraph_overrides,
    combo_options: pg.api.comboLinesForPayload(),
  };
}

const CASES = JSON.parse(fs.readFileSync(0, "utf8"));
const out = CASES.map((c) => {
  const st = JSON.parse(JSON.stringify(c.state));
  const pg = build(c, st);
  const pressed = [];
  const ribbon = [];
  for (const a of (c.actions || [])) {
    if (a.ribbon) {
      // Through the ribbon, the way a person does it: the caret lands on the line, the ribbon aims
      // at it, the button is clicked.
      const el = target(pg, a.ribbon);
      fire(el, "focusin", { bubbles: true });
      const aimed = barState(pg);
      const btn = pg.api.bar().querySelector(a.click === "reset" ? "button[data-fmt='reset']"
                                                                 : "button[data-para='" + a.click + "']");
      if (!btn) throw new Error("no ribbon button " + a.click);
      const before = el.dataset.pl || null;
      fire(btn, "click", { target: btn });
      ribbon.push({ on: a.ribbon, click: a.click, aimed, after: barState(pg), before,
                    pl: el.dataset.pl || null });
      continue;
    }
    if (a.key) {
      // A key at the caret, through the page's own keydown handlers (Enter, Tab, Backspace): the
      // caret is put on the line at `at` (its start when omitted, "end" for its end).
      const el = target(pg, a.on);
      const len = pg.api.serializeBlock(el).length;
      const at = a.at == null ? 0 : (a.at === "end" ? len : a.at);
      pg.SEL.el = el; pg.SEL.at = [at, at];
      const e = fire(el, "keydown", { key: a.key, shiftKey: !!a.shift });
      pressed.push({ key: a.key, shift: !!a.shift, on: a.on, prevented: !!e.defaulted,
                     pl: el.dataset.pl || null, text: pg.api.serializeBlock(el),
                     attached: pg.box.contains(el), aimedAt: aimOf(pg), bar: barState(pg) });
      continue;
    }
    if (a.select) {
      // The caret moved onto a line WITHOUT a focus event -- an arrow key inside a box that already
      // has focus -- so only the page's selectionchange listener runs.
      const el = target(pg, a.select);
      pg.SEL.el = el; pg.SEL.at = [0, 0];
      fire(pg.document, "selectionchange");
      ribbon.push({ select: a.select, aimedAt: aimOf(pg), bar: barState(pg) });
      continue;
    }
    if (a.press_ribbon) {
      // A ribbon button pressed on whatever the ribbon is aimed at NOW, with no new aim first. A
      // disabled button does not fire a click, so it is not pressed.
      const btn = pg.api.bar().querySelector(a.press_ribbon === "reset" ? "button[data-fmt='reset']"
                                                                         : "button[data-para='" + a.press_ribbon + "']");
      if (!btn) throw new Error("no ribbon button " + a.press_ribbon);
      const aimed = aimOf(pg);
      if (!btn.disabled) fire(btn, "click", { target: btn });
      ribbon.push({ press_ribbon: a.press_ribbon, aimedAt: aimed, disabled: !!btn.disabled });
      continue;
    }
    if (a.input_on || a.settext) {
      // A keystroke in the box: the line's words (unchanged for `input_on`, replaced for
      // `settext`), then the input event the page's delegated handler sweeps the box on.
      const el = target(pg, a.input_on || a.settext);
      if (a.settext) el.textContent = a.text;
      fire(el, "input", { bubbles: true });
      pressed.push({ input: true, on: a.input_on || a.settext });
      continue;
    }
    if (a.enter_after) {
      // Enter at the end of a line, through the page's own keydown handler, then the words typed
      // into the new line through an input event — the sweep stores them.
      const el = target(pg, a.enter_after);
      const len = pg.api.serializeBlock(el).length;
      pg.SEL.el = el; pg.SEL.at = [len, len];
      fire(el, "keydown", { key: "Enter" });
      const added = el.nextElementSibling;
      added.textContent = a.type || "";
      fire(added, "input", { bubbles: true });
      pressed.push({ enter: true, kind: added.dataset.poKind });
      continue;
    }
    const el = target(pg, a.on);
    pressed.push({ on: a.on, press: a.press, done: pg.api.paraAction(el, a.press) });
  }
  const lines = linesOf(pg);
  const payload = payloadOf(pg, st);
  // RELOAD: a new page, the saved draft only. The template rows' saved `para` goes back through
  // setParaState, the call restoreSavedOverrides makes for every saved entry.
  const st2 = JSON.parse(JSON.stringify(st));
  const pg2 = build(c, st2);
  for (const o of payload.paragraph_overrides) {
    const el = pg2.box.querySelector('.tw-block[data-id="' + o.id + '"]');
    if (el) pg2.api.setParaState(o.id, o.para, el);
  }
  return { name: c.name, lines, payload, pressed, ribbon, reload: linesOf(pg2),
           reloadPayload: payloadOf(pg2, st2) };
});
console.log(JSON.stringify(out));
