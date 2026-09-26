"use strict";
/* Deleting a line removes the line, like Word -- RUN, not read.
 *
 * Hanz, 2026-09-26, deleting a line in the Proposal step's WORK box: "This is also weird when I
 * delete a line." Under the Exclusions paragraph, two empty rows were left behind, each wearing the
 * edit bar and the ribbon's wash, and each printed as a blank line.
 *
 * Executed here: the page's REAL Backspace/Delete boundary handler, its box-wide Delete handler, the
 * whole undo section, spliceLines, the removal family, collectOverrides and restoreSavedOverrides,
 * lifted verbatim out of proposal-review.js. The document half -- the writer honouring
 * `{id, removed: true}` against the pristine template -- is test_line_removal.py's.
 *
 * The DOM model is editor-undo-harness.js's, copied: a real two-phase dispatch (the undo pre-image
 * is a capture listener, the delete a bubble one), a small real innerHTML parser, and a selection
 * modelled to selectionRange's own contract. One thing is added: `defaultPrevented`, because the
 * boundary handler now stands down for a key another handler already took, which is what stops a
 * box-wide Delete from also taking the line out behind the caret.
 *
 * Usage: node line-removal-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");
const F = require(path.join(FRONTEND, "js", "proposal-format-core.js"));

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

// The whole undo section, its listeners included, as editor-undo-harness.js lifts it.
const UNDO = region("  // ══ UNDO AND REDO", "  // ── Wire the formatting ribbon to the focused block ");
// The page's box-selection Delete handler, whole.
const BOX_DELETE = region('  docSurface.addEventListener("keydown", (e) => {\n    if (!boxSel || e.ctrlKey',
                          "  /** TAB INDENTS THE PARAGRAPH.");
// The page's Backspace/Delete boundary handler, whole: the one that now takes an empty line out.
const BOUNDARY = region('  docSurface.addEventListener("keydown", (e) => {\n    const back = e.key === "Backspace"',
                        "  /** PASTE, for every editable family");
// The page's Ctrl+A / B / I / U handler, whole: Ctrl+A is what puts a box selection there.
const CTRL_KEYS = region('  docSurface.addEventListener("keydown", (e) => {\n    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;\n    if (String(e.key).toLowerCase() === "a")',
                         "  // Enter inside a template paragraph = ONE line break");

// Copied from editor-undo-harness.js (see the header); only `defaultPrevented` is new.
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
  constructor(v) {
    this.nodeType = Node.TEXT_NODE;
    this.nodeValue = String(v);
    this.parentNode = null;
  }
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
    this._classes = new Set();
    this._listeners = { capture: {}, bubble: {} };
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
  set className(v) {
    this._classes = new Set(String(v).split(/\s+/).filter(Boolean));
    this.attrs.class = v;
  }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this;
    this.childNodes.push(c);
    return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c);
    if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null;
    return c;
  }
  get textContent() {
    return this.childNodes.map((n) =>
      n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent).join("");
  }
  set textContent(v) {
    while (this.childNodes.length) this.removeChild(this.childNodes[0]);
    if (String(v) !== "") this.appendChild(new Text(v));
  }
  /** A real (if small) parser: renderRuns nests a .tw-fill span inside a style span, so a flat one
   *  would silently drop the token boundary this editor depends on. */
  set innerHTML(html) {
    while (this.childNodes.length) this.removeChild(this.childNodes[0]);
    const stack = [this];
    const re = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w-]+="[^"]*")*)\s*\/?>|([^<]+)/g;
    let m;
    while ((m = re.exec(html))) {
      const top = stack[stack.length - 1];
      if (m[1]) {
        if (stack.length > 1) stack.pop();
      } else if (m[2]) {
        const el = new El(m[2]);
        for (const a of m[3].matchAll(/([\w-]+)="([^"]*)"/g)) {
          const v = unesc(a[2]);
          el.attrs[a[1]] = v;
          if (a[1] === "class") el.className = v;
          else if (a[1] === "style") el.style = parseStyle(v);
          else if (a[1] === "title") el.title = v;
          else if (a[1].startsWith("data-")) {
            el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
          }
        }
        top.appendChild(el);
        if (!VOID.has(el.tagName)) stack.push(el);
      } else if (m[4] !== undefined) {
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
  normalize() { /* the markers selectionRange inserts are modelled away, see readSel */ }
  /** THE CAPTURE FLAG IS REAL. The undo pre-image is taken by a capture listener on #doc-surface
   *  and the delete that destroys the text is a bubble listener on the same element; a shim that
   *  ignored the third argument would run them in registration order and quietly agree with a
   *  version of the page that took its snapshot too late. */
  addEventListener(type, f, capture) {
    const bag = capture ? this._listeners.capture : this._listeners.bubble;
    (bag[type] = bag[type] || []).push(f);
  }
  dispatchEvent(e) { return fire(this, e.type, e); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; }
  blur() { if (document.activeElement === this) document.activeElement = null; }
  focus() { document.activeElement = this; }
  getBoundingClientRect() { return { width: 0, height: 0, left: 0, top: 0, right: 0, bottom: 0 }; }
  get offsetHeight() { return 0; }
  get offsetWidth() { return 0; }
}

// The page tree as proposal-review.html arranges it.
const BODY = new El("body");
const FMT_HOST = new El("div");
FMT_HOST.attrs.id = "fmt-ribbon";
const NOTES_TA = new El("textarea");
NOTES_TA.attrs.id = "notes-text";
NOTES_TA.value = "";
const docSurface = new El("div");
docSurface.attrs.id = "doc-surface";
BODY.appendChild(FMT_HOST);
BODY.appendChild(NOTES_TA);
BODY.appendChild(docSurface);

class Range {
  constructor() { this._a = null; this._b = null; }
  setStartBefore(node) { this._a = node; }
  setEndAfter(node) { this._b = node; }
  setStart(node, offset) { this.startContainer = node; this.startOffset = offset; }
  setEnd(node, offset) { this.endContainer = node; this.endOffset = offset; }
  collapse() { this.collapsed = true; }
}

const document = {
  createElement: (t) => new El(t),
  createRange: () => new Range(),
  createTextNode: (v) => new Text(v),
  activeElement: null,
  body: BODY,
  getElementById: (id) => (id === "fmt-ribbon" ? FMT_HOST : (id === "notes-text" ? NOTES_TA : null)),
  querySelectorAll: (sel) => BODY.querySelectorAll(sel),
  _listeners: { capture: {}, bubble: {} },
  addEventListener(t, f, capture) {
    const bag = capture ? this._listeners.capture : this._listeners.bubble;
    (bag[t] = bag[t] || []).push(f);
  },
};

// THE MODELLED SELECTION: {line, range:[a,b]} for a caret or highlight inside one line, or
// {lines:[...]} for the cross-line range Ctrl+A leaves behind. selectionRange's own contract is
// that it answers with offsets ONLY when both endpoints are inside the element it was handed.
let SEL = null;
let ACROSS = null;
const readSel = (el) => (SEL && SEL.line === el ? SEL.range.slice() : null);
const writeSel = (el, a, b) => { SEL = { line: el, range: [a, b] }; ACROSS = null; };

const window = {
  _listeners: { capture: {}, bubble: {} },
  addEventListener(t, f, capture) {
    const bag = capture ? this._listeners.capture : this._listeners.bubble;
    (bag[t] = bag[t] || []).push(f);
  },
  getSelection: () => ({
    get rangeCount() { return ACROSS || SEL ? 1 : 0; },
    getRangeAt: () => (ACROSS || (SEL ? { startContainer: SEL.line, endContainer: SEL.line } : null)),
    removeAllRanges: () => { ACROSS = null; SEL = null; },
    addRange: (r) => { ACROSS = r; },
  }),
};

/** A real two-phase dispatch: capture from the root down to the target, then bubble back up. */
function fire(node, type, props) {
  let stopped = false;
  const e = Object.assign({
    type: type,
    target: node,
    relatedTarget: null,
    // Both spellings: the boundary handler reads the DOM's own `defaultPrevented`.
    preventDefault() { this.defaulted = true; this.defaultPrevented = true; },
    stopPropagation() { stopped = true; },
  }, props || {});
  e.type = type;
  e.target = e.target || node;
  const chain = [];
  for (let cur = node; cur; cur = cur.parentNode) chain.push(cur);
  chain.push(document);
  for (let i = chain.length - 1; i >= 0; i--) {
    for (const f of ((chain[i]._listeners.capture || {})[type] || []).slice()) f(e);
    if (stopped) return e;
  }
  for (let i = 0; i < chain.length; i++) {
    for (const f of ((chain[i]._listeners.bubble || {})[type] || []).slice()) f(e);
    if (stopped) return e;
  }
  for (const f of ((window._listeners.bubble || {})[type] || []).slice()) f(e);
  return e;
}

/** `new Event("input", {bubbles:true})` is what the restore and markEdited construct. Node's own
 *  Event has a getter-only `target`, so the sandbox gets this one and the page's line stays
 *  verbatim. */
class Ev {
  constructor(type, opts) {
    this.type = String(type);
    this.bubbles = !!(opts && opts.bubbles);
    this.target = null;
  }
}

// THE CLOCK, controllable. Coalescing is defined by an idle gap, so a harness that could not move
// time could only ever test one side of it.
let CLOCK = 1000;
const Clock = { now: () => CLOCK };



// ── the page's own collaborators ─────────────────────────────────────────────
const persisted = [];
const stateWrites = [];
const inputs = [];
const idled = [];
const STORE = { blob: { audience: "Direct" } };
const TAKE = { on: false };

const api = new Function(
  "document", "window", "docSurface", "F", "Node", "Event", "Date", "persisted", "stateWrites",
  "inputs", "idled", "readSel", "writeSel", "getAcross", "STORE", "TAKE",
  `const RUN_KEYS = F.RUN_KEYS;
  const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;
  let _fmtBusy = false;
  let fmtBar = null, fmtBlock = null, fmtRange = null, fmtRangeText = null;
  let boxSel = null;
  const blockById = new Map();
  const paraById  = new Map();
  const pristineById = new Map();
  let templateBlocks = null;
  let templateVersion = "tv-1";
  let templateLegacyFloorS = 0;
  const TWIPS_PER_PT = 20;
  const INDENT_STEP_TW = 288;
  const INDENT_MAX_TW = 2880;
  // The page's state store, the way shared.js behaves: getState parses a FRESH copy every call and
  // setState merges onto a fresh one, never touching the caller's snapshot.
  const TW = {
    getState: () => JSON.parse(JSON.stringify(STORE.blob)),
    setState: (o) => { stateWrites.push(o); STORE.blob = Object.assign(JSON.parse(JSON.stringify(STORE.blob)), o); return STORE.blob; },
  };
  const state = TW.getState();
  // The ribbon belongs to fmt-ribbon-harness.js; what matters here is that a removal lets go of it.
  const idleFmtBar = () => { idled.push(fmtBlock ? fmtBlock.dataset.id : null); fmtBlock = null; };
  const fmtTargetBlock = () => fmtBlock;
  const showFmtBar = () => {};
  // The persist is recorded rather than debounced: collectOverrides is read back directly below.
  const schedulePersistOverrides = () => { persisted.push(1); };
  const scheduleRepaginate = () => {};
  const effectiveWorkType = () => "epoxy";
  // Modelled, not lifted, exactly as in editor-undo-harness.js.
  const selectionRange = (el) => readSel(el);
  const placeSelection = (el, a, b) => { writeSel(el, a, b); };
  // A cross-line selection, modelled as the paste harness models it: from the box selection.
  const selectionLines = () => {
    if (boxSel && boxSel.length > 1) return boxSel.map((el) => ({ el: el, start: 0, end: runsLength(editRuns(el)) }));
    const el = lineAtSelection();
    if (!el) return [];
    const r = readSel(el);
    return r ? [{ el: el, start: r[0], end: r[1] }] : [];
  };
  const systemPreviewEl = null;
  const notesPreviewEl = document.createElement("div");
  let _notesOvTimer = null;
  const fitNotesBox = () => {};
  const fitTxbx = () => {};
  const setTimeout = () => 0;
  const clearTimeout = () => {};
  const ISLAND_IDS = [];
  const stagingPanel = null, stagingHome = null;
  // The values the document was last drawn with (refreshDocumentFills sets them): unremoveLine asks
  // the tax rule again with them. B / I / U belong to fmt-ribbon-harness.js.
  let _lastTokens = null;
  const toggleFormat = () => {};
  const priceLineAction = () => { throw new Error("priceLineAction reached: the price box's bullets are price-bullets-harness.js's"); };
  // #569's typed price lines ride the undo entry too (snap.po). Redrawing the price block from the
  // restored maps is price-lines-harness.js's; here the redraw and the save are recorded.
  const povRedraws = [];
  const refreshPriceDisplay = () => { povRedraws.push("redraw"); };
  const queuePovSave = () => { povRedraws.push("save"); };
` + [
    topConst("escHtml"), topConst("sameFmt"), topConst("LINE_SEL"), topConst("focusInside"),
    fn("fmtAt"), fn("segmentsOf"), fn("mergeSegs"), fn("serializeRuns"), fn("editRuns"),
    fn("runStyleCss"), fn("runEditCss"), fn("renderRuns"), fn("serializeBlock"),
    fn("runsEqual"), fn("pointAt"), fn("markEdited"),
    fn("lineAt"), fn("lineAtSelection"), fn("lineTarget"), fn("editingBox"), fn("boxLines"), fn("lineShown"),
    fn("paraBase"), fn("paraNow"), fn("paraPatch"), fn("sanitizeParaPatch"), fn("applyParaGeom"),
    fn("applyParaToEl"), fn("setParaState"), fn("paraAction"),
    fn("paintBoxSel"), fn("clearBoxSel"), fn("clearBoxLine"), fn("selectRangeAcross"),
    fn("insertBreakAt"), fn("spliceLines"),
    fn("noteLineHtml"), fn("notesRowSizePt"), fn("renderNotesPreview"), fn("syncNotesFromDom"),
    fn("lineIsEmpty"), fn("lineRemovable"), fn("removeLine"), fn("unremoveLine"),
    fn("removedBlockIds"), fn("adjacentLine"), fn("caretToLine"), fn("removeLineAt"),
    fn("isNumberedClause"), fn("blanksANumberedClause"), fn("runsArePlain"), fn("storedRuns"),
    // collectOverrides keeps an untouched PRICE figure of a free price paragraph as its token.
    topConst("PRICE_TOKENS"), fn("storedText"), fn("isPriceParagraph"),
    // The Backspace handler hands a typed price line to mergePriceLine first.
    fn("makeExtraLine"), fn("caretInto"), fn("mergePriceLine"),
    // ...after the bullets branch's ladder on a price line with words (isPriceLine asks). Its
    // step (priceLineAction) is price-bullets-harness.js's: no case here reaches it, and one that
    // did would say so.
    fn("isPriceLine"),
    topConst("overrideKey"), topConst("liveKey"), fn("savedVersionMatches"),
    fn("savedOverridesFor"), fn("preserveRichOverrides"), fn("lineBare"), fn("lineKeptEmpty"), fn("collectOverrides"),
    fn("restoreSavedOverrides"), fn("priceRowVisibility"),
  ].join("\n") + `
` + BOX_DELETE + `
` + UNDO + `
` + BOUNDARY + `
` + CTRL_KEYS + `
  notesPreviewEl.addEventListener("input", syncNotesFromDom);
  // Another handler that takes Backspace first, the way the Options gap's capture listener does.
  docSurface.addEventListener("keydown", (e) => { if (TAKE.on && e.key === "Backspace") e.preventDefault(); }, true);
  docSurface.addEventListener("input", (e) => {
    const el = e.target && e.target.closest ? e.target.closest(LINE_SEL) : null;
    inputs.push(el ? (el.dataset.id || ("note:" + el.dataset.noteIndex)) : "?");
  });
  return {
    collectOverrides, restoreSavedOverrides, spliceLines, removedBlockIds, serializeBlock, editRuns,
    renderNotesPreview,
    records: (list) => { blockById.clear(); (list || []).forEach((b) => blockById.set(b.id, b)); templateBlocks = list; },
    pristine: (id, text) => { pristineById.set(Number(id), text); },
    setBoxSel: (els) => { boxSel = els && els.length ? els : null; paintBoxSel(); },
    setFmtBlock: (el) => { fmtBlock = el; },
    forget: () => undoForget(),
    setTokens: (t) => { _lastTokens = t; },
    setPov: (o) => { state.price_overrides = o; },
    pov: () => state.price_overrides,
    povRedraws,
    lineShown, lineKeptEmpty,
    notesPreviewEl,
  };`
)(document, window, docSurface, F, Node, Ev, Clock, persisted, stateWrites, inputs, idled, readSel,
  writeSel, () => ACROSS, STORE, TAKE);

// ── the page under test ──────────────────────────────────────────────────────
/** One text box of template paragraphs, the way renderPositioned builds one: the BOX is the editing
 *  host, the paragraphs are `.tw-block`s carrying the backend walk's id, and each has a template
 *  record whose `fit.removable` is the writer's own answer (served by /api/proposal-template). */
function mountBox(lines, opts) {
  docSurface.childNodes.slice().forEach((n) => docSurface.removeChild(n));
  SEL = null; ACROSS = null;
  persisted.length = 0; stateWrites.length = 0; inputs.length = 0; idled.length = 0;
  api.setBoxSel(null);
  api.forget();
  const page = new El("div");
  page.className = "tw-page";
  docSurface.appendChild(page);
  const box = new El("div");
  box.className = (opts && opts.terms) ? "tw-terms-page" : "tw-txbx";
  box.attrs.contenteditable = "true";
  page.appendChild(box);
  const recs = [];
  const els = lines.map((ln, i) => {
    if (ln.priceRow) {
      const p = new El("p");
      p.className = "tw-line-edit";
      p.dataset.poLinekey = ln.key || "base";
      if (ln.kind) p.dataset.poKind = ln.kind;
      if (ln.hidden) p.style.display = "none";
      p.textContent = ln.text;
      box.appendChild(p);
      return p;
    }
    const id = 200 + i;
    const el = new El("div");
    el.className = "tw-block";
    el.dataset.id = String(id);
    if (ln.hidden) el.style.display = "none";
    el.innerHTML = ln.text ? '<span style="font-size:8pt">' + ln.text + "</span>" : "<br>";
    // Inside something hidden, the way #options-gap hides the lines it holds.
    if (ln.inHidden) {
      const wrap = new El("div");
      wrap.style.display = "none";
      wrap.appendChild(el);
      box.appendChild(wrap);
    } else {
      box.appendChild(el);
    }
    api.pristine(id, ln.pristine == null ? ln.text : ln.pristine);
    recs.push({ id: id, text: ln.tpl != null ? ln.tpl : ln.text, txbx: 2, in_block: null,
                para: ln.marker ? { marker: "1." } : null,
                fit: { hp: 18, typed_hp: 16, typed_sized: true, removable: ln.removable !== false } });
    return el;
  });
  api.records(recs);
  return { box, els };
}

const caret = (el, a) => { SEL = { line: el, range: [a, a] }; ACROSS = null; };
const key = (el, k, extra) => fire(el, "keydown", Object.assign({ key: k, ctrlKey: false, metaKey: false,
                                                                  altKey: false, shiftKey: false }, extra || {}));
const tick = (ms) => { CLOCK += ms == null ? 5000 : ms; };
const lineState = (el) => ({
  id: el.dataset.id || null,
  block: el.classList.contains("tw-block"),
  removed: el.classList.contains("tw-block-removed"),
  display: el.style.display || "",
  text: api.serializeBlock(el),
});
const caretAt = () => {
  if (SEL) return { line: SEL.line.dataset.id || null, at: SEL.range[0] };
  if (ACROSS && ACROSS.startContainer) return { line: ACROSS.startContainer.dataset ? ACROSS.startContainer.dataset.id : null, at: ACROSS.startOffset };
  return null;
};
/** Where the caret is, whichever family its line is, and whether that line is on screen. */
const caretWhere = () => {
  const el = SEL ? SEL.line : (ACROSS && ACROSS.startContainer ? ACROSS.startContainer : null);
  if (!el || !el.dataset) return null;
  return { line: el.dataset.id || el.dataset.poLinekey || null,
           at: SEL ? SEL.range[0] : ACROSS.startOffset, shown: api.lineShown(el) };
};
const out = {};

// 1. Backspace on an EMPTY line takes it out; the caret lands at the end of the line above.
{
  const { box, els } = mountBox([{ text: "Scope: x" }, { text: "", pristine: "Exclusions: y" }, { text: "Notes: z" }]);
  caret(els[1], 0);
  const e = key(els[1], "Backspace");
  out.backspaceEmpty = { prevented: !!e.defaultPrevented, lines: els.map(lineState), caret: caretAt(),
                         overrides: api.collectOverrides(), inputs: inputs.slice(),
                         boxLines: box.querySelectorAll(".tw-block").length };
  // 1b. Ctrl+Z puts it back, and Ctrl+Y takes it out again.
  tick();
  key(els[0], "z", { ctrlKey: true });
  out.undoRemoval = { lines: els.map(lineState), overrides: api.collectOverrides() };
  tick();
  key(els[0], "y", { ctrlKey: true });
  out.redoRemoval = { lines: els.map(lineState), overrides: api.collectOverrides() };
}

// 2. Delete on an empty line takes it out; the caret lands at the start of the line below.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "" }, { text: "Notes: z" }]);
  caret(els[1], 0);
  const e = key(els[1], "Delete");
  out.deleteEmpty = { prevented: !!e.defaultPrevented, lines: els.map(lineState), caret: caretAt() };
}

// 3. Backspace at the START of a line whose line above is empty: the empty line goes, the caret stays.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "" }, { text: "Notes: z" }]);
  caret(els[2], 0);
  const e = key(els[2], "Backspace");
  out.backspaceIntoEmpty = { prevented: !!e.defaultPrevented, lines: els.map(lineState), caret: caretAt() };
}

// 4. Delete at the END of a line whose line below is empty: the empty line goes.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "" }, { text: "Notes: z" }]);
  caret(els[0], 8);
  const e = key(els[0], "Delete");
  out.deleteIntoEmpty = { prevented: !!e.defaultPrevented, lines: els.map(lineState), caret: caretAt() };
}

// 5. A line the template will not let go (a numbered clause, a region row): kept, and the key still
//    refused, exactly as before -- no merge, ever.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "", removable: false, marker: true }, { text: "Notes: z" }]);
  caret(els[1], 0);
  const e = key(els[1], "Backspace");
  out.notRemovable = { prevented: !!e.defaultPrevented, lines: els.map(lineState), overrides: api.collectOverrides() };
}

// 6. The only line in a box stays, whichever key.
{
  const { els } = mountBox([{ text: "" }]);
  caret(els[0], 0);
  key(els[0], "Backspace");
  key(els[0], "Delete");
  out.onlyLine = { lines: els.map(lineState) };
}

// 7. The last TEMPLATE line of a box stays even beside a priced row: the writer keeps one free
//    paragraph per box, because a region's rows can all be stripped at print time.
{
  const { els } = mountBox([{ priceRow: true, text: "$36,763 – Total" }, { text: "" }]);
  caret(els[1], 0);
  key(els[1], "Backspace");
  out.lastTemplateLine = { lines: els.map(lineState) };
}

// 8. ...and a hidden line (the free Remodel row on a job with no remodel tax, which the writer takes
//    out itself) does not count as the one that keeps the box alive.
{
  const { els } = mountBox([{ priceRow: true, text: "$36,763 – Total" }, { text: "" },
                            { text: "$0 – Remodel Tax", hidden: true }]);
  caret(els[1], 0);
  key(els[1], "Backspace");
  out.hiddenDoesNotCount = { lines: els.map(lineState) };
}

// 9. Ctrl+A, Delete: every line goes but the first, which stays empty for the caret.
{
  const { box, els } = mountBox([{ text: "Scope: x" }, { text: "Schedule: y" }, { text: "Notes: z" }]);
  api.setBoxSel(els.slice());
  const e = key(els[0], "Delete");
  out.boxWideDelete = { prevented: !!e.defaultPrevented, lines: els.map(lineState),
                        overrides: api.collectOverrides(),
                        // The boundary handler must not ALSO act on the same keystroke.
                        removedCount: api.removedBlockIds().length };
  tick();
  key(els[0], "z", { ctrlKey: true });
  out.undoBoxWide = { lines: els.map(lineState) };
}

// 10. A selection across lines: the lines it covers end to end go, a line it only touches stays.
{
  const { els } = mountBox([{ text: "Scope: xyz" }, { text: "Schedule: y" }, { text: "Notes: z" }]);
  caret(els[0], 3);
  api.spliceLines([{ el: els[0], start: 3, end: 10 }, { el: els[1], start: 0, end: 11 },
                   { el: els[2], start: 0, end: 2 }], []);
  out.splice = { lines: els.map(lineState) };
}

// 10b. A selection that starts at the very beginning of a line and runs into the next -- a
//      triple-click, Shift+Down from a line's start -- covers that line's paragraph mark too, and
//      Word deletes the paragraph whole. The line below keeps every word and takes the caret.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "Schedule: y" }, { text: "Notes: z" }]);
  caret(els[1], 0);
  inputs.length = 0;
  api.spliceLines([{ el: els[1], start: 0, end: 11 }, { el: els[2], start: 0, end: 0 }], []);
  out.tripleClick = { lines: els.map(lineState), caret: caretAt(), inputs: inputs.slice(),
                      overrides: api.collectOverrides() };
}

// 10c. The same selection TYPED over keeps the first line: the typed text has to land somewhere.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "Schedule: y" }, { text: "Notes: z" }]);
  caret(els[1], 0);
  api.spliceLines([{ el: els[1], start: 0, end: 11 }, { el: els[2], start: 0, end: 0 }],
                  [{ text: "Q", tok: null }]);
  out.tripleClickTyped = { lines: els.map(lineState) };
}

// 10d. ...and a first line the template will not let go stays, emptied, as it always did.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "Clause", removable: false }, { text: "Notes: z" }]);
  caret(els[1], 0);
  api.spliceLines([{ el: els[1], start: 0, end: 6 }, { el: els[2], start: 0, end: 0 }], []);
  out.tripleClickKept = { lines: els.map(lineState) };
}

// 10e. Covering every line of the selection end to end leaves the first one, empty, for the caret:
//      there is no later line of the selection left to move onto.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "Schedule: y" }, { text: "Notes: z" }]);
  caret(els[0], 0);
  api.spliceLines([{ el: els[0], start: 0, end: 8 }, { el: els[1], start: 0, end: 11 },
                   { el: els[2], start: 0, end: 8 }], []);
  out.coverAll = { lines: els.map(lineState) };
}

// 16. A line EMPTIED on the page is saved as an empty paragraph, not as a line break: it holds the
//     placeholder `<br>`, which serializeBlock reads as "\n" and the writer would print two lines
//     tall. A formatted line emptied sends `runs: []`. A "\n" that is real text -- what a draft
//     saved before this change replays as `textContent` -- is sent exactly as it was.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "", pristine: "Exclusions: y" },
                            { text: "", pristine: "Notes: z" }]);
  els[2].classList.add("tw-fmt");
  const placeholder = els.map((el) => el.childNodes.map((n) => n.tagName || "#text"));
  const emptied = api.collectOverrides();
  els[1].textContent = "\n";
  const legacy = api.collectOverrides();
  out.emptiedIsEmpty = { placeholder: placeholder, emptied: emptied, legacy: legacy,
                         texts: els.map((el) => api.serializeBlock(el)) };
}

// 11. A reload: the saved removal hides the line again, and the next save sends it again.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "Exclusions: y" }, { text: "Notes: z" }]);
  STORE.blob = { audience: "Direct", paragraph_overrides_all: {
    "epoxy:Direct": { template_version: "tv-1", items: [{ id: 201, removed: true }] } } };
  api.restoreSavedOverrides("epoxy", "Direct", {});
  out.reload = { lines: els.map(lineState), overrides: api.collectOverrides() };
  // A saved removal for a line this template will NOT let go is ignored, not drawn empty.
  const again = mountBox([{ text: "Scope: x" }, { text: "Clause", removable: false }, { text: "Notes: z" }]);
  STORE.blob = { audience: "Direct", paragraph_overrides_all: {
    "epoxy:Direct": { template_version: "tv-1", items: [{ id: 201, removed: true }] } } };
  api.restoreSavedOverrides("epoxy", "Direct", {});
  out.reloadRefused = { lines: again.els.map(lineState) };
  STORE.blob = { audience: "Direct" };
}

// 12. The ribbon lets go of a line that is taken out.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "" }, { text: "Notes: z" }]);
  els[1].classList.add("tw-fmt-target");
  api.setFmtBlock(els[1]);
  caret(els[1], 0);
  key(els[1], "Backspace");
  out.ribbon = { idled: idled.slice(), stillMarked: els[1].classList.contains("tw-fmt-target") };
}

// 13. A NOTES bullet emptied and Backspaced goes from the textarea, which is the notes' only store.
{
  const { box } = mountBox([{ text: "Scope: x" }]);
  box.appendChild(api.notesPreviewEl);
  NOTES_TA.value = "One\n\nThree";
  api.renderNotesPreview();
  const bullets = api.notesPreviewEl.querySelectorAll("[data-note-index]");
  caret(bullets[1], 0);
  key(bullets[1], "Backspace");
  out.notes = { textarea: NOTES_TA.value,
                bullets: api.notesPreviewEl.querySelectorAll("[data-note-index]").map((p) => [p.dataset.noteIndex, api.serializeBlock(p)]) };
  tick();
  key(bullets[0], "z", { ctrlKey: true });
  out.notesUndo = { textarea: NOTES_TA.value };
}

// 15. A key another handler already took (the Options gap's, a box-wide Delete) is not also a
//     removal: the boundary handler stands down on `defaultPrevented`.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "" }, { text: "Notes: z" }]);
  TAKE.on = true;
  caret(els[1], 0);
  key(els[1], "Backspace");
  TAKE.on = false;
  out.alreadyTaken = { lines: els.map(lineState) };
}

// 14. The terms flow is not a text box: an empty terms line is never taken out.
{
  const { els } = mountBox([{ text: "1. Clause" }, { text: "" }, { text: "2. Clause" }], { terms: true });
  caret(els[1], 0);
  key(els[1], "Backspace");
  out.terms = { lines: els.map(lineState) };
}

// ═══ lines nobody can see: never landed on, never selected, never taken out ═══════════════════
// 17. A Direct PRICE box on a bid with no options: under the base line, the "Options:" heading is
//     there but hidden, then the blank lines. Backspace on the first blank line takes it out and the
//     caret goes to the END OF THE BASE LINE -- the line above that is on screen -- not into the
//     hidden heading. A second Backspace is then the browser's own, in a visible line.
{
  const { els } = mountBox([{ priceRow: true, text: "$6,767 – Epoxy flooring as described above" },
                            { priceRow: true, key: "heading_options", text: "Options:", hidden: true },
                            { text: "" }, { text: "" }, { text: "" }]);
  caret(els[2], 0);
  const e1 = key(els[2], "Backspace");
  const first = { prevented: !!e1.defaultPrevented, caret: caretWhere(), removed: api.removedBlockIds() };
  const e2 = key(els[0], "Backspace");
  out.hiddenAbove = { first: first, secondPrevented: !!e2.defaultPrevented, caretAfter: caretWhere(),
                      removedAfter: api.removedBlockIds(),
                      heading: { text: api.serializeBlock(els[1]), display: els[1].style.display || "" } };
}

// 18. ...and a caret that is in a hidden line anyway does nothing there: the key is refused and
//     the caret moves to the nearest line shown (Backspace looks up, Delete down).
{
  const { els } = mountBox([{ priceRow: true, text: "$6,767 – Epoxy flooring as described above" },
                            { priceRow: true, key: "heading_options", text: "Options:", hidden: true },
                            { text: "" }, { text: "Notes" }]);
  caret(els[1], 8);
  const back = key(els[1], "Backspace");
  const afterBack = { prevented: !!back.defaultPrevented, caret: caretWhere() };
  caret(els[1], 0);
  const del = key(els[1], "Delete");
  out.caretInHidden = { back: afterBack, del: { prevented: !!del.defaultPrevented, caret: caretWhere() },
                        heading: api.serializeBlock(els[1]), removed: api.removedBlockIds() };
}

// 19. GC, no remodel tax: the free "$0 – Remodel Tax" row is hidden between the Material Sales Tax
//     row and the Total. The Total emptied and Backspaced goes; the caret goes to the end of the
//     Material Sales Tax row, and the hidden row is neither landed on nor touched.
{
  const { els } = mountBox([{ text: "$1,200 – Material Sales Tax" },
                            { text: "$0 – Remodel Tax", hidden: true },
                            { text: "", pristine: "$1,300 – Total" },
                            { text: "Options & Unit Prices" }, { text: "" }]);
  caret(els[2], 0);
  const e = key(els[2], "Backspace");
  out.gcHiddenRemodel = { prevented: !!e.defaultPrevented, caret: caretWhere(), lines: els.map(lineState) };
}

// 20. Delete on an empty line whose next line is inside a hidden container: the caret skips it.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "" }, { text: "Gap", inHidden: true },
                            { text: "Notes: z" }]);
  caret(els[1], 0);
  const e = key(els[1], "Delete");
  out.hiddenBelow = { prevented: !!e.defaultPrevented, caret: caretWhere(), lines: els.map(lineState) };
}

// 21. CTRL+A THEN DELETE, AND UNDO, in a GC PRICE box with no remodel tax. Ctrl+A takes the lines
//     on screen: the hidden Remodel row is not selected, not emptied, not taken out -- the
//     document leaves it out on its own -- and Ctrl+Z does not bring it onto the screen.
{
  const { box, els } = mountBox([{ text: "Base Bid" }, { text: "$1,200 – Material Sales Tax" },
                                 { text: "$0 – Remodel Tax", hidden: true }, { text: "$1,300 – Total" },
                                 { text: "" }]);
  caret(els[0], 2);
  const a = key(els[0], "a", { ctrlKey: true });
  const selected = els.map((el) => el.classList.contains("tw-boxsel"));
  const d = key(els[0], "Delete");
  const afterDelete = { lines: els.map(lineState), overrides: api.collectOverrides() };
  tick();
  key(els[0], "z", { ctrlKey: true });
  out.ctrlAHidden = { ctrlAPrevented: !!a.defaultPrevented, selected: selected,
                      deletePrevented: !!d.defaultPrevented, afterDelete: afterDelete,
                      afterUndo: els.map(lineState), boxLines: box.querySelectorAll(".tw-block").length };
}

// 22. A tax row taken out while it showed, and the rule moved while it was out (the remodel tax
//     switched off in the sidebar): Ctrl+Z brings it back HIDDEN, as the document prints it.
{
  const { els } = mountBox([{ text: "$1,200 – Material Sales Tax" },
                            { text: "", tpl: "{{tax_amount_formatted}} – Remodel Tax",
                              pristine: "$120 – Remodel Tax" },
                            { text: "$1,320 – Total" }]);
  api.setTokens({ price_rows_remodel: true, tax_amount_formatted: "$120" });
  caret(els[1], 0);
  key(els[1], "Backspace");
  const gone = lineState(els[1]);
  api.setTokens({ price_rows_remodel: false, tax_amount_formatted: "$0" });
  tick();
  key(els[0], "z", { ctrlKey: true });
  const back = lineState(els[1]);
  // ...and one whose rule still says it prints comes back shown.
  api.setTokens({ price_rows_remodel: true, tax_amount_formatted: "$120" });
  tick();
  key(els[0], "y", { ctrlKey: true });
  tick();
  key(els[0], "z", { ctrlKey: true });
  out.unremoveAsksTheRule = { gone: gone, backHidden: back, backShown: lineState(els[1]) };
  api.setTokens(null);
}

// 23. A LINE EMPTIED AND KEPT, saved and reloaded: it is drawn as it was left (the placeholder
//     break), so it is still his kept line and the next save says so again. A `text: ""` saved
//     before the flag existed is restored as it always was (an empty line, no break), and saves
//     back without the flag.
{
  const { els } = mountBox([{ text: "Scope: x" }, { text: "Exclusions: y" }, { text: "Notes: z" }]);
  STORE.blob = { audience: "Direct", paragraph_overrides_all: {
    "epoxy:Direct": { template_version: "tv-1", items: [{ id: 201, text: "", kept: true }] } } };
  api.restoreSavedOverrides("epoxy", "Direct", {});
  const kept = { children: els[1].childNodes.map((c) => c.tagName || "#text"),
                 keptEmpty: api.lineKeptEmpty(els[1]), overrides: api.collectOverrides() };
  const again = mountBox([{ text: "Scope: x" }, { text: "Exclusions: y" }, { text: "Notes: z" }]);
  STORE.blob = { audience: "Direct", paragraph_overrides_all: {
    "epoxy:Direct": { template_version: "tv-1", items: [{ id: 201, text: "" }] } } };
  api.restoreSavedOverrides("epoxy", "Direct", {});
  out.keptReload = { kept: kept,
                     legacy: { children: again.els[1].childNodes.map((c) => c.tagName || "#text"),
                               keptEmpty: api.lineKeptEmpty(again.els[1]),
                               overrides: api.collectOverrides() } };
  STORE.blob = { audience: "Direct" };
}

// 24. ONE UNDO HISTORY FOR BOTH: a line taken out, then the blank lines above "Options:" changed
//     (price_overrides, #569). The first Ctrl+Z puts the count back and leaves the line out; the
//     second brings the line back and leaves the count alone.
{
  const { els } = mountBox([{ priceRow: true, kind: "line", key: "base",
                              text: "$6,767 – Epoxy flooring as described above" },
                            { text: "" }, { text: "Notes: z" }]);
  api.setPov({ options_gap: 2 });
  caret(els[1], 0);
  key(els[1], "Backspace");                       // the empty line goes (one undo entry)
  const afterRemove = { removed: api.removedBlockIds(), gap: api.pov().options_gap };
  tick();
  key(els[2], "Enter");                           // the pre-image of the next edit (one entry)...
  api.pov().options_gap = 3;                      // ...which is the gap's Enter: one line more
  tick();
  api.povRedraws.length = 0;
  key(els[2], "z", { ctrlKey: true });
  const first = { removed: api.removedBlockIds(), gap: api.pov().options_gap,
                  redraws: api.povRedraws.slice() };
  tick();
  key(els[2], "z", { ctrlKey: true });
  out.undoBoth = { afterRemove: afterRemove, first: first,
                   second: { removed: api.removedBlockIds(), gap: api.pov().options_gap } };
  api.setPov(undefined);
}

process.stdout.write(JSON.stringify(out));
