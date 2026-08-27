"use strict";
/* Ctrl+Z in the Proposal Editor, RUN rather than read.
 *
 * Hanz, 2026-08-27: "Also in the Proposal Editor, I cant use Keyboard shortcuts. I wanted to
 * control z but didnt work. when I deleted all in the textbox."
 *
 * WHY THIS RUNS THE CODE, and why no source assertion could have caught the bug in the first
 * place. Ctrl+Z was never intercepted: the page's Ctrl handler returns for anything that is not
 * a/b/i/u, so a grep for "preventDefault" near "z" finds nothing and reads as healthy. The undo
 * did run — against an EMPTY native stack, because every edit this editor makes is a programmatic
 * DOM mutation and a contenteditable records only the browser's own. "Pressing this key gives the
 * paragraph its words back" is a claim about a stack, a snapshot, a restore and four event
 * listeners agreeing, and every one of them is invisible to a text search.
 *
 * The precedent for running rather than reading is expensive: on 2026-08-12 `STAGE_CREATED`
 * shipped unbound with every source-text assertion green and took the production board down.
 *
 * TWO THINGS ARE MODELLED HERE THAT THE OTHER EDITOR HARNESSES STUB, because the fix is about
 * them and a stub would test the harness instead of the page:
 *
 *   * THE CAPTURE PHASE. The pre-image has to be taken before the handler that mutates, and both
 *     live on #doc-surface — so `fire()` runs a real capture pass from the ancestors down and then
 *     a bubble pass back up, exactly as the DOM does. A shim that fired listeners in registration
 *     order would let a snapshot taken AFTER the delete pass, which is the whole bug.
 *   * THE CLOCK. Coalescing is "a burst of typing is one undo", and a burst is defined by an idle
 *     gap. `Date.now()` is a controllable counter here so a test can put 20ms or 5s between two
 *     keystrokes and read back how many units that made.
 *
 * DELIBERATELY NOT A FULL DOM, for the reason box-drag-harness.js gives: jsdom lets a missing
 * binding hide behind a stub. What is shimmed is only what the code under test touches — elements
 * and text nodes (segmentsOf walks childNodes by nodeType), `style` as camelCase properties parsed
 * out of a real inline style attribute (fmtAt reads the run formatting back out of exactly that),
 * a small real innerHTML parser (renderRuns nests .tw-fill inside a style span), and a selection
 * modelled to selectionRange's own contract: offsets when it is wholly inside the line, null when
 * it is anywhere else.
 *
 * Usage: node editor-undo-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
// Normalized to LF: the repo's frontend is checked out CRLF on Windows and every pattern below
// anchors on "\n  " indentation. A CR left in would make the lifted source subtly different from
// the shipped source, which is the one thing this harness must not allow.
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");
const F = require(path.join(FRONTEND, "js", "proposal-format-core.js"));

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

/** THE WHOLE UNDO SECTION, verbatim, between two anchor comments — its constants, its functions
 *  AND its four listeners in one piece.
 *
 *  A region rather than a list of named functions, for the reason fmt-ribbon-harness.js gives: a
 *  harness that lifts only what it thought to name never binds the handler nobody thought of, and
 *  a listener that goes unbound is a listener no scenario can contradict. Here it matters twice
 *  over, because "which listener is registered, on what, in which phase" IS the fix. */
function region(from, to) {
  const i = SRC.indexOf(from);
  if (i < 0) throw new Error("the undo section anchored on " + JSON.stringify(from) + " is gone");
  const j = SRC.indexOf(to, i);
  if (j < 0) throw new Error("the undo section no longer ends at " + JSON.stringify(to));
  return SRC.slice(i, j);
}

const UNDO = region(
  "  // ══ UNDO AND REDO",
  "  // ── Wire the formatting ribbon to the focused block ");

/** The page's clearDocSurface body, so "a template reload forgets the history" is read off the
 *  real function rather than off a call to undoForget() a test made itself. */
const CLEAR_DOC_SURFACE = fn("clearDocSurface");

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
    preventDefault() { this.defaulted = true; },
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
const inputs = [];        // every `input` event the surface saw, by the line it came from

const api = new Function(
  "document", "window", "docSurface", "F", "Node", "Event", "Date", "persisted", "stateWrites",
  "inputs", "readSel", "writeSel",
  `const RUN_KEYS = F.RUN_KEYS;
  const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;
  let _fmtBusy = false;
  let fmtBar = null, fmtBlock = null, fmtRange = null, fmtRangeText = null;
  // The whole-box selection, the page's own binding verbatim: the box-wide delete and the undo
  // entry both read it, and a stub would let the branch go untested.
  let boxSel = null;
  const blockById = new Map();      // id -> the template's block record
  const paraById  = new Map();      // id -> {bullet, indent} the estimator set
  const pristineById = new Map();
  const TWIPS_PER_PT = 20;
  const INDENT_STEP_TW = 288;
  const INDENT_MAX_TW = 2880;
  const ISLAND_IDS = [];
  const stagingPanel = null, stagingHome = null;
  const idleFmtBar = () => {};
  const fmtTargetBlock = () => fmtBlock;
  const schedulePersistOverrides = () => { persisted.push(1); };
  const scheduleRepaginate = () => {};
  const TW = { setState: (o) => { stateWrites.push(o); } };
  // Modelled, not lifted — Range arithmetic against a live caret is the one thing a shim cannot do
  // honestly. The CONTRACT is what matters and it is the real function's: offsets when the
  // selection is wholly inside el, null when it is anywhere else.
  const selectionRange = (el) => readSel(el);
  const placeSelection = (el, a, b) => { writeSel(el, a, b); };
  // The WORK systems preview belongs to doc-editor-labels-harness.js, which builds that world. An
  // empty stub is the truthful answer for a harness that does not mount it, and it still fails
  // loudly if the page renames it.
  const systemPreviewEl = null;
  // THE NOTES PREVIEW IS REAL HERE, and it is the one preview that has to be. Its bullets are not
  // stored anywhere -- they are rendered from the #notes-text textarea, which is their single
  // source of truth -- so restoring a DELETED bullet by element is impossible and the entry has to
  // carry the text. Stubbing it would leave the only family whose restore works differently
  // completely untested, and NOTES is a text box an estimator clears.
  const notesPreviewEl = document.createElement("div");
  let _notesOvTimer = null;
  const fitNotesBox = () => {};
  const fitTxbx = () => {};
  // The debounces: every one of them is a save this harness has already stubbed at the far end.
  const setTimeout = () => 0;
  const clearTimeout = () => {};
` + [
    topConst("escHtml"), topConst("sameFmt"), topConst("LINE_SEL"),
    fn("fmtAt"), fn("segmentsOf"), fn("mergeSegs"), fn("serializeRuns"), fn("editRuns"),
    fn("runStyleCss"), fn("runEditCss"), fn("renderRuns"), fn("serializeBlock"),
    fn("runsEqual"), fn("pointAt"), fn("markEdited"),
    fn("lineAt"), fn("lineAtSelection"), fn("editingBox"), fn("boxLines"),
    fn("paraBase"), fn("paraNow"), fn("sanitizeParaPatch"), fn("applyParaGeom"),
    fn("applyParaToEl"), fn("setParaState"), fn("paraAction"),
    fn("paintBoxSel"), fn("clearBoxSel"), fn("clearBoxLine"), fn("selectRangeAcross"),
    fn("insertBreakAt"),
    topConst("focusInside"), fn("noteLineHtml"), fn("renderNotesPreview"), fn("syncNotesFromDom"),
    CLEAR_DOC_SURFACE,
  ].join("\n") + `

  // ── the page's own delete-with-a-box-selection handler, verbatim ───────────
  // The gesture Hanz performed, and registered BEFORE the undo section below on purpose. In the
  // shipped file the undo listeners happen to come first, which would make a bubble-phase snapshot
  // work by accident and go on working right up until somebody moved a block of code. Here the
  // mutating handler is first, so the only thing that can still put the pre-image ahead of the
  // delete is the capture flag — which is the claim.
  docSurface.addEventListener("keydown", (e) => {
    if (!boxSel || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    if (e.key !== "Backspace" && e.key !== "Delete") return;
    e.preventDefault();
    const els = boxSel.slice();
    clearBoxSel();
    els.forEach(clearBoxLine);
  });
` + UNDO + `
  // The page's own two-way binding between the bullets and the textarea, verbatim.
  notesPreviewEl.addEventListener("input", syncNotesFromDom);
  // Every input event the surface hears, so a restore that forgot to dispatch one — and therefore
  // persisted nothing — is a failure rather than a silent pass.
  docSurface.addEventListener("input", (e) => {
    const el = e.target && e.target.closest ? e.target.closest(LINE_SEL) : null;
    inputs.push(el ? (el.dataset.id || el.dataset.poLinekey || el.dataset.sysLine || "?") : "?");
  });

  return {
    editRuns, renderRuns, serializeBlock, runsEqual, undoLineKey, undoSnapshot,
    mountNotes: (box) => { box.appendChild(notesPreviewEl); renderNotesPreview(); },
    renderNotes: () => renderNotesPreview(),
    notesBullets: () => Array.prototype.map.call(
      notesPreviewEl.querySelectorAll("[data-note-index]"), (p) => serializeBlock(p)),
    clearDocSurface, paraAction, insertBreakAt,
    depth: () => UNDO_DEPTH,
    stacks: () => ({ undo: _undoStack.length, redo: _redoStack.length }),
    setBoxSel: (els) => { boxSel = els && els.length ? els : null; paintBoxSel(); },
    getBoxSel: () => (boxSel || []).map((el) => el.dataset.id || el.dataset.poLinekey || "?"),
    block: (id, rec) => { blockById.set(Number(id), rec); },
    paraOf: (id) => { const p = paraNow(Number(id)); return p ? { bullet: p.bullet, indent: p.indent, locked: p.locked } : null; },
    paraSetFor: (id) => (paraById.has(Number(id)) ? paraById.get(Number(id)) : null),
    forget: () => undoForget(),
    /** What restoreSavedOverrides does on load: write a saved paragraph override into paraById.
     *  It writes from the DRAFT, while the locked flag comes from the template on screen now, so
     *  a set value and a locked clause genuinely coexist -- which is the only way the para half of
     *  a restore ever reaches its refusal. */
    seedPara: (id, st) => { paraById.set(Number(id), st); },
    /** What a template load does to the override map before it renders: empties it. */
    resetPara: () => { paraById.clear(); blockById.clear(); },
    /** What the pending entries record about the caret and the box selection. The restore's own
     *  claim, read off the stack rather than inferred from where the caret ended up. */
    peek: () => _undoStack.map((s) => ({ caret: s.caret, boxSel: s.boxSel, lines: s.lines.length })),
    /** The TEXT the pending entry is holding, line by line. The pre-image's own claim, read off
     *  the stack rather than inferred from what an undo happened to produce. */
    peekText: () => {
      const top = _undoStack[_undoStack.length - 1];
      if (!top) return null;
      return top.lines.map((l) => (l.runs ? l.runs.map((r) => r.text).join("") : l.text));
    },
  };`
)(document, window, docSurface, F, Node, Ev, Clock, persisted, stateWrites, inputs, readSel, writeSel);

// ── the page under test ──────────────────────────────────────────────────────
/** One text box with N template paragraphs in it, the way renderPositioned builds one: the BOX is
 *  the editing host, the paragraphs are plain `.tw-block` children carrying the backend walk's id.
 *  Mounting the old one-host-per-paragraph shape would be worse than no harness at all — it would
 *  keep passing after the page stopped working that way. */
function mountBox(texts, opts) {
  docSurface.childNodes.slice().forEach((n) => docSurface.removeChild(n));
  SEL = null; ACROSS = null;
  persisted.length = 0; stateWrites.length = 0; inputs.length = 0;
  // The box selection is the page's own binding and it outlives a scenario the way it outlives a
  // template reload -- clearBoxSel is only ever called by a gesture. Dropped here so one scenario
  // cannot hand the next one a selection it never made.
  api.setBoxSel(null);
  api.resetPara();
  api.forget();
  const page = new El("div");
  page.className = "tw-page";
  docSurface.appendChild(page);
  const box = new El("div");
  box.className = "tw-txbx";
  box.attrs.contenteditable = "true";
  page.appendChild(box);
  const blocks = texts.map((t, i) => {
    const b = new El("div");
    b.className = "tw-block";
    b.dataset.id = String(110 + i);
    b.innerHTML = String(t);
    box.appendChild(b);
    api.block(110 + i, { id: 110 + i, para: Object.assign(
      { bullet: false, indent: 0, locked: false }, (opts && opts.para && opts.para[i]) || {}) });
    return b;
  });
  return { page: page, box: box, blocks: blocks };
}

/** A whole-line computed row — the PRICE family, which persists by data-po-linekey and whose
 *  channel reads an empty value as "no override". */
function addPriceLine(box, key, text) {
  const p = new El("p");
  p.className = "tw-priceline tw-line-edit";
  p.dataset.poKind = "line";
  p.dataset.poLinekey = key;
  p.dataset.computed = text;
  p.textContent = text;
  box.appendChild(p);
  return p;
}

/** Put the caret in a line. Nothing has to be fired afterwards: the page reads the caret LIVE,
 *  through lineAtSelection and selectionRange, at the moment a unit opens -- there is no
 *  selectionchange memo to keep in step, which is the point of reading it there. */
const caretIn = (el, a, b) => { SEL = { line: el, range: [a, b === undefined ? a : b] }; ACROSS = null; };
const tick = (ms) => { CLOCK += ms; };
const key = (target, k, props) =>
  fire(target, "keydown", Object.assign({ key: k, ctrlKey: false, metaKey: false, altKey: false,
                                          shiftKey: false, isComposing: false }, props || {}));
const beforeinput = (target, inputType, data) =>
  fire(target, "beforeinput", { inputType: inputType, data: data === undefined ? null : data });
const undoKey = (target, props) => key(target, "z", Object.assign({ ctrlKey: true }, props || {}));
const texts = (blocks) => blocks.map((b) => api.serializeBlock(b));

const out = {};

// ═══ 1. THE REPORTED GESTURE: select the whole box, delete, Ctrl+Z ═══════════
{
  const { box, blocks } = mountBox([
    "Scope: grind and prep the slab.",
    "Schedule: two mobilizations.",
    "Exclusions: no moisture mitigation.",
  ]);
  caretIn(blocks[0], 0, 0);
  api.setBoxSel(blocks);
  out.before = texts(blocks);
  key(box, "Delete");
  out.afterDelete = texts(blocks);
  out.stackAfterDelete = api.stacks();
  inputs.length = 0;
  persisted.length = 0;
  undoKey(box);
  out.afterUndo = texts(blocks);
  out.stackAfterUndo = api.stacks();
  // The selection is a selection again, not just text on a page: undoing a Ctrl+A delete leaves
  // the estimator looking at what they were looking at when they pressed the key.
  out.boxSelAfterUndo = api.getBoxSel();
  // And the restore reached the draft — ONE dispatch per editing host, not one per line (every
  // persistence sweep hanging off `input` is box-wide, so N events would each re-do the same
  // sweep) and not none (a silent restore is an override the draft never hears about).
  out.inputsOnUndo = inputs.length;
  out.persistedOnUndo = persisted.length > 0;
  // Redo puts the delete back.
  key(box, "z", { ctrlKey: true, shiftKey: true });
  out.afterRedo = texts(blocks);
}

// ═══ 2. FORMATTING SURVIVES THE ROUND TRIP ═══════════════════════════════════
// The pre-image stores RUNS, not text: a bolded phrase that came back as plain characters would
// look restored and reach the customer's .docx with the formatting silently dropped.
{
  const { box, blocks } = mountBox(
    ['Scope: <span style="font-weight:700">grind</span> and prep.']);
  caretIn(blocks[0], 0, 0);
  out.fmtBefore = api.editRuns(blocks[0]);
  api.setBoxSel(blocks);
  key(box, "Delete");
  undoKey(box);
  out.fmtAfterUndo = api.editRuns(blocks[0]);
}

// ═══ 3. WHAT ONE UNDO UNIT IS ════════════════════════════════════════════════
// A burst of typing is one; a pause, a space and a move to another line each open the next.
{
  const { box, blocks } = mountBox(["one", "two"]);
  /** ONE CHARACTER, the whole way the browser delivers it: keydown, then beforeinput, then the
   *  mutation. Both events reach the undo listeners for the same keystroke, which is exactly the
   *  double-arrival the signature check has to absorb, and the text really changes, which is what
   *  stops the NEXT push being dropped as a no-op. */
  const type = (el, gapMs, k) => {
    tick(gapMs);
    caretIn(el, 0, 0);
      key(box, k || "x");
    beforeinput(box, "insertText", k || "x");
    el.textContent = (k || "x") + el.textContent;
  };
  // Six characters typed straight through: one unit.
  for (let i = 0; i < 6; i++) type(blocks[0], 20);
  out.unitsForOneBurst = api.stacks().undo;
  // A pause longer than the coalescing window: the next character opens the next unit.
  type(blocks[0], 5000);
  out.unitsAfterAPause = api.stacks().undo;
  // A SPACE closes the word, so the character after it is a new unit even with no pause at all.
  type(blocks[0], 20, " ");
  const beforeWord = api.stacks().undo;
  type(blocks[0], 20);
  out.unitsAcrossASpace = [beforeWord, api.stacks().undo];
  // The caret moving to another line closes the run too.
  const beforeMove = api.stacks().undo;
  type(blocks[1], 20);
  out.unitsAcrossALine = [beforeMove, api.stacks().undo];
  // Typing then deleting is two units, not one run of "editing".
  const beforeDelete = api.stacks().undo;
  tick(20);
  caretIn(blocks[1], 1, 1);
  key(box, "Backspace");
  beforeinput(box, "deleteContentBackward");
  blocks[1].textContent = blocks[1].textContent.slice(1);
  out.unitsAcrossADirectionChange = [beforeDelete, api.stacks().undo];
  // Twelve keystrokes in, and the estimator can still walk every one of those units back rather
  // than one giant one — this is the number that says the coalescing did not swallow the history.
  out.unitsForTwelveKeystrokes = api.stacks().undo;
}

// ═══ 4. THE KEYS THAT MUST NOT OPEN A UNIT ═══════════════════════════════════
{
  const { box, blocks } = mountBox(["one"]);
  caretIn(blocks[0], 0, 0);
  const quiet = {};
  for (const spec of [["ArrowLeft", {}], ["ArrowRight", {}], ["Home", {}], ["End", {}],
                      ["PageDown", {}], ["Shift", {}], ["F5", {}], ["Escape", {}],
                      ["a", { ctrlKey: true }], ["c", { ctrlKey: true }]]) {
    tick(5000);
    const was = api.stacks().undo;
    key(box, spec[0], spec[1]);
    quiet[spec[0] + (spec[1].ctrlKey ? "+ctrl" : "")] = api.stacks().undo - was;
  }
  out.unitsFromNavigationKeys = quiet;
}

// ═══ 5. BOTH SPELLINGS OF REDO, AND A NEW EDIT FORKS THE HISTORY ═════════════
{
  const { box, blocks } = mountBox(["alpha"]);
  caretIn(blocks[0], 0, 0);
  api.setBoxSel(blocks);
  key(box, "Delete");
  undoKey(box);
  out.ctrlY = { cleared: api.serializeBlock(blocks[0]) };
  key(box, "y", { ctrlKey: true });
  out.ctrlY.afterCtrlY = api.serializeBlock(blocks[0]);
  undoKey(box);
  out.ctrlY.afterUndoAgain = api.serializeBlock(blocks[0]);
  // A fresh edit while a redo is pending throws the redo away — there is nothing to go forward to
  // any more, and offering one would replay a branch the estimator left.
  out.redoBeforeFork = api.stacks().redo;
  tick(5000);
  caretIn(blocks[0], 0, 0);
  key(box, "q");
  beforeinput(box, "insertText", "q");
  out.redoAfterFork = api.stacks().redo;
}

// ═══ 6. A KEYSTROKE THAT CHANGED NOTHING DOES NOT EAT A PRESS OF CTRL+Z ══════
// Backspace at offset 0 is refused by the page (it would merge two paragraphs and destroy an id).
// The pre-image is taken before anyone knows that, so the entry it leaves has to be recognised as
// a no-op at the pop — otherwise the estimator presses Ctrl+Z, watches nothing happen, and is back
// to the bug this fixes.
{
  const { box, blocks } = mountBox(["alpha"]);
  caretIn(blocks[0], 0, 0);
  api.setBoxSel(blocks);
  key(box, "Delete");                       // the real edit
  tick(5000);
  caretIn(blocks[0], 0, 0);
  key(box, "Backspace");                    // refused: nothing changes
  beforeinput(box, "deleteContentBackward");
  out.deadUnits = api.stacks().undo;
  undoKey(box);
  out.afterOnePressPastADeadUnit = api.serializeBlock(blocks[0]);
}

// ═══ 7. THE CARET COMES BACK ═════════════════════════════════════════════════
// An undo that restores every character and drops the caret at the top of the box reads as a bug
// even when the text is right. The pre-image records where the caret was; the restore puts it
// back there, on the line it was on.
{
  const { box, blocks } = mountBox(["alpha bravo"]);
  caretIn(blocks[0], 6, 6);                 // between the two words
  key(box, "x");
  beforeinput(box, "insertText", "x");
  blocks[0].textContent = "alpha xbravo";
  caretIn(blocks[0], 0, 0);                 // the caret wanders off, as it does while editing
  undoKey(box);
  out.caretAfterUndo = SEL && SEL.line === blocks[0] ? SEL.range : null;
  out.textAfterCaretUndo = api.serializeBlock(blocks[0]);
}

// ═══ 8. THE DEPTH LIMIT ══════════════════════════════════════════════════════
{
  const { box, blocks } = mountBox(["seed"]);
  const want = api.depth();
  for (let i = 0; i < want + 25; i++) {
    tick(5000);
    caretIn(blocks[0], 0, 0);
      key(box, "x");
    beforeinput(box, "insertText", "x");
    blocks[0].textContent = "seed" + i;     // a real change, so no entry is dropped as a no-op
  }
  out.depth = { limit: want, held: api.stacks().undo };
}

// ═══ 9. A NUMBERED TERMS CLAUSE CANNOT BE RENUMBERED BY AN UNDO ═════════════
// paraAction refuses a locked clause, so no keystroke and no ribbon press can un-bullet one — but
// an UNDO writes paragraph state, and a route that skipped the refusal would be a way to renumber
// legal boilerplate in a document a customer signs.
//
// Both halves of the restore are reached. The entry records the clause's properties as they were
// when the snapshot was taken; a saved override then moves them (restoreSavedOverrides writes
// paraById from the DRAFT while `locked` comes from the template on screen, so the two really can
// disagree); and the undo tries to put the recorded pair back.
{
  const { box, blocks } = mountBox(["1. Payment is due on receipt."],
                                   { para: [{ bullet: true, indent: 288, locked: true }] });
  api.seedPara(110, { bullet: false, indent: 0 });        // what the entry will record
  caretIn(blocks[0], 0, 0);
  api.setBoxSel(blocks);
  key(box, "Delete");                                     // the pre-image, para included
  api.seedPara(110, { bullet: true, indent: 576 });        // the properties move underneath it
  out.locked = { before: api.paraOf(110) };
  undoKey(box);
  // The WRITE half: the recorded pair disagrees with what is there now, and setParaState refuses.
  out.locked.after = api.paraOf(110);
  out.locked.text = api.serializeBlock(blocks[0]);
}

// ═══ 9b. AND THE DELETE HALF OF THE SAME REFUSAL ═════════════════════════════
// An entry whose para is null means "the estimator had set nothing, the template's own properties
// applied", and putting that back is a DELETE from paraById rather than a write. On a locked
// clause that delete is the same renumbering by another name.
{
  const { box, blocks } = mountBox(["1. Payment is due on receipt."],
                                   { para: [{ bullet: true, indent: 288, locked: true }] });
  caretIn(blocks[0], 0, 0);
  api.setBoxSel(blocks);
  key(box, "Delete");                                     // recorded with no override set
  api.seedPara(110, { bullet: true, indent: 576 });        // a saved override arrives afterwards
  undoKey(box);
  out.lockedDelete = { set: api.paraSetFor(110), now: api.paraOf(110) };
}

// ═══ 10. AN UNLOCKED INDENT IS ON THE STACK ══════════════════════════════════
// The other half of 9: Tab really does indent an ordinary paragraph, and Ctrl+Z really does take
// the indent back. Both go through paraAction / setParaState, the ribbon's own channel.
{
  const { box, blocks } = mountBox(["Grind and prep."], { para: [{ bullet: false, indent: 0 }] });
  caretIn(blocks[0], 0, 0);
  key(box, "Tab");                          // the pre-image
  api.paraAction(blocks[0], "indent");      // what the page's Tab handler then calls
  out.indent = { after: api.paraOf(110).indent };
  undoKey(box);
  out.indent.afterUndo = api.paraOf(110).indent;
}

// ═══ 11. A COMPUTED LINE COMES BACK THROUGH ITS OWN CHANNEL ══════════════════
// The PRICE family stores TEXT, and clearing one resets it to the computed figure rather than
// voiding it. An undo has to put the estimator's wording back and dispatch the input event that
// carries it into price_overrides — a silent restore is an override that never persists.
{
  const { box, blocks } = mountBox(["Scope: grind."]);
  const line = addPriceLine(box, "option:2", "Option 2 - Quartz broadcast   $41,250");
  line.textContent = "Option 2 - Quartz broadcast (includes cove)   $41,250";
  caretIn(line, 0, 0);
  api.setBoxSel([line]);
  inputs.length = 0;
  key(box, "Delete");
  out.priceLine = { afterDelete: line.textContent };
  inputs.length = 0;
  undoKey(box);
  out.priceLine.afterUndo = line.textContent;
  out.priceLine.dispatched = inputs.slice();
}

// ═══ 12. A TEMPLATE RELOAD FORGETS THE HISTORY ═══════════════════════════════
// The ids an entry names belong to the template that was on screen. clearDocSurface() is what runs
// on a work-type or audience switch, and replaying an entry across one would write the estimator's
// words into a different paragraph of a document a customer signs.
{
  const { box, blocks } = mountBox(["alpha"]);
  caretIn(blocks[0], 0, 0);
  api.setBoxSel(blocks);
  key(box, "Delete");
  out.reload = { before: api.stacks().undo };
  api.clearDocSurface();
  out.reload.after = api.stacks().undo;
}

// ═══ 13. BOX GEOMETRY IS NOT ON THE STACK ════════════════════════════════════
// Deliberately excluded: a resize has its own Reset box affordance, and this surface is a to-scale
// preview of a printed page registered against baked artwork. A Ctrl+Z aimed at a word that also
// moved a box by a few points would be a worse bug than the one it fixed.
{
  const { box, blocks } = mountBox(["alpha"]);
  caretIn(blocks[0], 0, 0);
  api.setBoxSel(blocks);
  key(box, "Delete");
  box.style.height = "240pt";               // what a drag-resize leaves behind
  undoKey(box);
  out.geometry = { height: box.style.height, text: api.serializeBlock(blocks[0]) };
}

// ═══ 14. THE PRE-IMAGE IS TAKEN BEFORE THE HANDLER THAT MUTATES ═════════════
// Both listeners sit on #doc-surface. The undo one is registered in the CAPTURE phase precisely so
// its ordering does not depend on where in the file the other one happens to be written — and in
// this harness the mutating handler really is registered first, so nothing but the phase can put
// the snapshot ahead of it.
//
// Read off the ENTRY, not off the undo. What the entry is holding the instant after the delete is
// the only direct evidence; an undo that produced the right text could still have got there from
// a pre-image taken at the wrong moment on some other path.
{
  const seen = [];
  const { box, blocks } = mountBox(["alpha"]);
  caretIn(blocks[0], 0, 0);
  docSurface.addEventListener("keydown", () => { seen.push("bubble:" + api.serializeBlock(blocks[0])); });
  docSurface.addEventListener("keydown", () => { seen.push("capture:" + api.serializeBlock(blocks[0])); }, true);
  api.setBoxSel(blocks);
  key(box, "Delete");
  out.preImage = api.peekText();
  // A COPY. `seen` goes on collecting from the probes for the rest of the run -- they stay bound to
  // the surface, as listeners do -- and reporting the live array would hand the test every later
  // scenario's keystrokes as well.
  out.phases = seen.slice();
}

// ═══ 15. THE NOTES BOX, WHICH IS WHERE THE COMPLAINT CAME FROM ═══════════════
// The bullets are not stored anywhere: they are rendered from the #notes-text textarea, which is
// their single source of truth, and clearing them empties it. So an entry carries the TEXT and the
// restore rebuilds the bullets from it — restoring by element would put back only the bullets that
// still exist, which after a box-wide delete is a partial undo wearing the look of a complete one.
{
  const { box, blocks } = mountBox(["Notes:"]);
  NOTES_TA.value = "Owner supplies the water.\nNo work above 90 degrees.\nTwo mobilizations.";
  api.mountNotes(box);
  out.notes = { bullets: api.notesBullets(), textarea: NOTES_TA.value };
  const bullets = box.querySelectorAll(".tw-note-edit");
  caretIn(bullets[0], 0, 0);
  api.setBoxSel(bullets);
  key(box, "Delete");
  out.notes.afterDelete = { bullets: api.notesBullets(), textarea: NOTES_TA.value };
  undoKey(box);
  out.notes.afterUndo = { bullets: api.notesBullets(), textarea: NOTES_TA.value };
}

// ═══ 16. THE NOTES BULLETS AFTER THEY HAVE BEEN REBUILT ══════════════════════
// The case that decides the design. Leaving the box re-renders the preview from the emptied
// textarea, so three bullet ELEMENTS collapse into one — and there is now no element left for an
// entry keyed by data-note-index to write bullet two and three into. Only the text can bring them
// back, which is why an entry for a notes box carries the textarea and not just the lines.
{
  const { box } = mountBox(["Notes:"]);
  NOTES_TA.value = "Owner supplies the water.\nNo work above 90 degrees.\nTwo mobilizations.";
  api.mountNotes(box);
  const bullets = box.querySelectorAll(".tw-note-edit");
  caretIn(bullets[0], 0, 0);
  api.setBoxSel(bullets);
  key(box, "Delete");
  SEL = null;                               // the caret leaves the box ...
  api.renderNotes();                        // ... which is what re-renders the preview
  out.notesRebuilt = { bulletsLeft: api.notesBullets().length };
  undoKey(box);
  out.notesRebuilt.afterUndo = api.notesBullets();
}

// ═══ 17. AN UNDO ALWAYS LEAVES A CARET SOMEWHERE ════════════════════════════
// The restore drops the selection on the way in, because the notes preview refuses to rebuild its
// bullets while the caret is inside them. An entry that never recorded a caret -- an edit that
// arrived before any selectionchange, a drag-and-drop, a context-menu paste -- would then end with
// no caret at all, and the estimator has to click back into the box to carry on typing.
{
  const { box, blocks } = mountBox(["alpha bravo"]);
  // NO selectionchange: nothing has told the page where the caret is.
  beforeinput(box, "insertText", "x");
  blocks[0].textContent = "xalpha bravo";
  out.caretless = { recorded: (api.peek()[0] || {}).caret };
  undoKey(box);
  out.caretless.after = SEL && SEL.line === blocks[0] ? SEL.range : null;
  out.caretless.text = api.serializeBlock(blocks[0]);
}

process.stdout.write(JSON.stringify(out) + "\n");
