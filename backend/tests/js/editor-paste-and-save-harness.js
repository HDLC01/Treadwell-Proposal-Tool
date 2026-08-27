"use strict";
/* Two keys the Proposal Editor was giving to the browser, RUN rather than read.
 *
 * Hanz, 2026-08-27, on the two gaps found while fixing Ctrl+Z: "DO you mean to implement? then
 * yes."
 *
 *   * CTRL+S opened Chromium's Save Page sheet -- a dialog offering to write an .html copy of the
 *     app into Downloads. The page autosaves, so the key now finishes that save and reports the
 *     outcome.
 *   * CTRL+V into anything that was not a .tw-block fell through to the browser. The paste handler
 *     bailed with an early return and no preventDefault, so the clipboard's own markup landed in a
 *     price row, a WORK system row or a notes bullet -- channels that store a plain string.
 *
 * WHY THIS RUNS THE CODE. Both are claims about what a handler does with an event, and both failed
 * in the direction a source read cannot see: the paste bug was an early return that looked like a
 * guard, and the Ctrl+S readout's whole value is that its three states are the return value of a
 * write rather than a claim about one. "Saved appears only where a PUT resolved ok" is four
 * functions and a promise agreeing.
 *
 * The precedent for running rather than reading is expensive: on 2026-08-12 STAGE_CREATED shipped
 * unbound with every source-text assertion green and took the production board down.
 *
 * WHAT IS MODELLED HERE AND STUBBED ELSEWHERE:
 *
 *   * THE CLIPBOARD, as a real DataTransfer-shaped thing with both flavours -- text/html AND
 *     text/plain -- because "which flavour did this family take, and did the formatting come with
 *     it" is the whole question for the three computed rows.
 *   * THE NOTES PREVIEW AND ITS TEXTAREA, for real, two-way bound by the page's own listener. The
 *     bullets have no store of their own; the textarea IS their channel, and a multi-line paste is
 *     the case that decides how the family behaves.
 *   * THE SAVE PROMISE, resolvable by the test at the moment of its choosing, so "Saving..." can be
 *     read off the screen while the write is still in the air rather than inferred.
 *
 * DELIBERATELY NOT A FULL DOM, for the reason box-drag-harness.js gives: jsdom lets a missing
 * binding hide behind a stub. The shim below is the one editor-undo-harness.js uses, for the same
 * reasons, and the selection is modelled to selectionRange's own contract -- offsets when it is
 * wholly inside the line, null when it is anywhere else.
 *
 * Usage: node editor-paste-and-save-harness.js <frontend-dir>   ->   one line of JSON
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

/** A whole REGION of the page's top-level wiring, verbatim, between two anchor comments.
 *
 *  A region rather than a list of named functions, for the reason fmt-ribbon-harness.js gives: a
 *  harness that lifts only what it thought to name never binds the handler nobody thought of, and
 *  a listener that goes unbound is a listener no scenario can contradict. Here that is the point
 *  twice over -- the paste fix IS a listener, and so is Ctrl+S. */
function region(from, to) {
  const i = SRC.indexOf(from);
  if (i < 0) throw new Error("the block anchored on " + JSON.stringify(from) + " is gone");
  const j = SRC.indexOf(to, i);
  if (j < 0) throw new Error("the block no longer ends at " + JSON.stringify(to));
  return SRC.slice(i, j);
}

/** The paste listener, its two helpers and the whole Ctrl+S section, in one piece: everything the
 *  page wires up between the paste handler and the merge guard below it. */
const PASTE_AND_SAVE = region(
  "  /** PASTE, for every editable family",
  "  /** THE MERGE GUARD");

/** The undo section's own paste listener, verbatim and on its own.
 *
 *  The stack it pushes onto belongs to editor-undo-harness.js, which builds that world and proves
 *  it; what has to be true HERE is only that a paste into a computed row opens exactly one undo
 *  unit, so this listener is bound for real against a recording undoPush. Lifting the line rather
 *  than re-typing it is the difference between testing the page and testing the harness. */
const UNDO_PASTE = region(
  "  /** A paste is its own unit and needs its own listener",
  "  /** THE RIBBON'S PRESSES");

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
  removeAttribute(k) { delete this.attrs[k]; if (k === "title") this.title = ""; }
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


/** The readout the Ctrl+S section looks up on load. The shim's getElementById is a fixed lookup, so
 *  the third id is patched in HERE -- before api() is built, because that is when the page reads
 *  it. A harness whose element arrived late would be testing the null-guard, not the readout. */
const SAVE_EL = new El("span");
SAVE_EL.attrs.id = "save-state";
SAVE_EL.hidden = true;
const _byIdBase = document.getElementById;
document.getElementById = (id) => (id === "save-state" ? SAVE_EL : _byIdBase(id));

// ── the page's own collaborators ─────────────────────────────────────────────
const persisted = [];
const stateWrites = [];
const inputs = [];        // every input event the surface saw, by the line it came from
const undoUnits = [];     // every undo unit the page opened, in order

// THE SAVE, held open on purpose. flushState's promise is resolved by the test at the moment of its
// choosing, so "Saving..." can be read off the screen while the write is genuinely in the air.
let saveGate = null;
let saveBlockedAnswer = null;
const flushCalls = [];

const api = new Function(
  "document", "window", "docSurface", "F", "Node", "Event", "TW", "persisted", "stateWrites",
  "inputs", "undoUnits", "readSel", "writeSel", "notesHost",
  `const RUN_KEYS = F.RUN_KEYS;
  const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;
  let _fmtBusy = false;
  let fmtBar = null, fmtBlock = null, fmtRange = null, fmtRangeText = null;
  let boxSel = null;
  const blockById = new Map();
  const paraById  = new Map();
  const pristineById = new Map();
  const schedulePersistOverrides = () => { persisted.push(1); };
  const scheduleRepaginate = () => {};
  // THE UNDO STACK IS NOT LIFTED -- editor-undo-harness.js owns that world and proves it. What
  // matters here is only that a paste OPENS ONE UNIT, whichever family it lands in, so the push is
  // recorded and counted. A stub that swallowed the unit name would let "paste is one undo" pass
  // without being true.
  const undoPush = (unit) => { undoUnits.push(unit); return true; };
  // Modelled, not lifted -- Range arithmetic against a live caret is the one thing a shim cannot do
  // honestly. The CONTRACT is the real function's: offsets when the selection is wholly inside el,
  // null when it is anywhere else.
  const selectionRange = (el) => readSel(el);
  const placeSelection = (el, a, b) => { writeSel(el, a, b); };
  // A CROSS-LINE SELECTION, modelled from boxSel exactly as fmt-ribbon-harness.js models it:
  // readSel/writeSel express one selection inside ONE element and cannot describe a range spanning
  // four lines. boxSel can -- Ctrl+A is what puts one there -- and that is what selectionLines
  // reads off the markers on the real page. A collapsed caret is always one line.
  const selectionLines = () => {
    if (boxSel && boxSel.length > 1) {
      return boxSel.map((el) => ({ el: el, start: 0, end: runsLength(editRuns(el)) }));
    }
    const el = lineAtSelection();
    if (!el) return [];
    const r = readSel(el);
    return r ? [{ el: el, start: r[0], end: r[1] }] : [];
  };
  // The ribbon and the WORK systems preview belong to the other editor harnesses, which build those
  // worlds. Empty stubs are the truthful answer for a harness that mounts neither, and they still
  // fail loudly if the page renames one.
  const showFmtBar = () => {};
  const systemPreviewEl = null;
  // THE NOTES PREVIEW IS REAL. Its bullets have no store of their own -- the #notes-text textarea IS
  // their channel -- so a multi-line paste is the case that decides how the family behaves, and a
  // stub would decide it for the page.
  const notesPreviewEl = notesHost;
  let _notesOvTimer = null;
  const fitNotesBox = () => {};
  const fitTxbx = () => {};
  const setTimeout = () => 0;
  const clearTimeout = () => {};
` + [
    topConst("escHtml"), topConst("sameFmt"), topConst("LINE_SEL"), topConst("focusInside"),
    fn("fmtAt"), fn("segmentsOf"), fn("mergeSegs"), fn("serializeRuns"), fn("editRuns"),
    fn("runStyleCss"), fn("runEditCss"), fn("renderRuns"), fn("serializeBlock"), fn("pointAt"),
    fn("markEdited"), fn("runsFromHtml"), fn("spliceLines"),
    fn("lineAt"), fn("lineAtSelection"), fn("lineTarget"), fn("editingBox"), fn("boxLines"),
    fn("noteLineHtml"), fn("renderNotesPreview"), fn("syncNotesFromDom"),
  ].join("\n") + `
` + UNDO_PASTE + `
` + PASTE_AND_SAVE + `
  // The page's own two-way binding between the bullets and the textarea, verbatim.
  notesPreviewEl.addEventListener("input", syncNotesFromDom);
  // Every input event the surface hears. A paste into a computed row that forgot to dispatch one
  // reaches no channel at all -- it would show on screen and be gone at the next repaint.
  docSurface.addEventListener("input", (e) => {
    const el = e.target && e.target.closest ? e.target.closest(LINE_SEL) : null;
    inputs.push(el ? (el.dataset.id || el.dataset.poLinekey || el.dataset.sysLine
                      || ("note:" + el.dataset.noteIndex)) : "?");
  });

  return {
    serializeBlock, editRuns, renderNotesPreview, pastedTextFor,
    notesBullets: () => Array.prototype.map.call(
      notesPreviewEl.querySelectorAll("[data-note-index]"), (p) => serializeBlock(p)),
    mountNotes: (box) => { box.appendChild(notesPreviewEl); renderNotesPreview(); },
    setBoxSel: (els) => { boxSel = els && els.length ? els : null; },
  };`
);

// ── the page ─────────────────────────────────────────────────────────────────
const NOTES_HOST = new El("div");
NOTES_HOST.attrs.id = "notes-preview-block";

window.TW = null;   // replaced below; declared first so the sandbox sees the same object
const TWStub = {
  saveBlocked: () => saveBlockedAnswer,
  flushState: () => {
    flushCalls.push(1);
    return new Promise((resolve) => { saveGate = resolve; });
  },
  setState: (o) => { stateWrites.push(o); },
};

window.TW = TWStub;
const page = api(document, window, docSurface, F, Node, Ev, TWStub, persisted, stateWrites,
                 inputs, undoUnits, readSel, writeSel, NOTES_HOST);

// THE READOUT, CHECKED THE INSTANT THE PAGE IS BUILT. mountBox empties the surface between
// scenarios, so a readout that HAD been mounted into the document would have been swept out
// again by the last scenario -- and a check taken only at the end would pass while the page
// was wrong. Both moments are reported.
const surfaceCleanAtLoad = !docSurface.contains(SAVE_EL);

/** One text box with N template paragraphs, the way renderPositioned builds one: the BOX is the
 *  editing host and the paragraphs are plain .tw-block children carrying the backend walk's id. */
function mountBox(texts) {
  docSurface.childNodes.slice().forEach((n) => docSurface.removeChild(n));
  SEL = null; ACROSS = null;
  persisted.length = 0; stateWrites.length = 0; inputs.length = 0; undoUnits.length = 0;
  page.setBoxSel(null);
  const pg = new El("div");
  pg.className = "tw-page";
  docSurface.appendChild(pg);
  const box = new El("div");
  box.className = "tw-txbx";
  box.attrs.contenteditable = "true";
  pg.appendChild(box);
  const blocks = (texts || []).map((t, i) => {
    const b = new El("div");
    b.className = "tw-block";
    b.dataset.id = String(110 + i);
    b.innerHTML = String(t);
    box.appendChild(b);
    return b;
  });
  return { page: pg, box: box, blocks: blocks };
}

/** A whole-line computed PRICE row: persists by data-po-linekey, and its channel reads an empty
 *  value as "no override" rather than as a blank line. */
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

/** A WORK {{#system}} row: persists by index + field into system_overrides. */
function addSysRow(box, i, field, text) {
  const p = new El("p");
  p.className = "tw-sysline tw-line-edit";
  p.dataset.sysIndex = String(i);
  p.dataset.sysLine = field;
  p.dataset.computed = text;
  p.textContent = text;
  box.appendChild(p);
  return p;
}

const caretIn = (el, a, b) => { SEL = { line: el, range: [a, b === undefined ? a : b] }; ACROSS = null; };

/** A paste, with a real two-flavour clipboard. Both flavours are offered unless the test says
 *  otherwise, because "which one did this family take" is the question. */
function paste(target, plain, html) {
  const data = {};
  if (plain != null) data["text/plain"] = plain;
  if (html != null) data["text/html"] = html;
  return fire(target, "paste", { clipboardData: { getData: (t) => data[t] || "" } });
}

const key = (target, k, props) =>
  fire(target, "keydown", Object.assign({ key: k, ctrlKey: false, metaKey: false, altKey: false,
                                          shiftKey: false, isComposing: false }, props || {}));
const saveKey = (target, props) => key(target || docSurface, "s", Object.assign({ ctrlKey: true }, props || {}));
const readout = () => ({ text: SAVE_EL.textContent, state: SAVE_EL.dataset.state,
                         hidden: !!SAVE_EL.hidden, title: SAVE_EL.title || "" });

const out = {};

// ═══ 1. A PRICE ROW TAKES TEXT, NOT MARKUP ═══════════════════════════════════
// The reported hole. Word's clipboard offers both flavours; the row's channel stores a string, so
// the HTML flavour must not reach it and the browser must not be handed the event.
{
  const { box } = mountBox(["Scope: grind and prep."]);
  const line = addPriceLine(box, "option:2", "Option 2 - Quartz broadcast   $41,250");
  line.textContent = "";
  caretIn(line, 0, 0);
  const e = paste(box, "Quartz broadcast with cove",
                  '<span style="font-weight:700; mso-fareast-font-family:Calibri">Quartz</span>'
                  + '<b> broadcast</b> with cove');
  out.priceRow = {
    refusedTheBrowser: !!e.defaulted,
    text: page.serializeBlock(line),
    // NO FORMATTING, and that is a refusal rather than an omission: this channel stores a string,
    // so a bold word would show here and reach the customer's document as plain.
    runs: page.editRuns(line),
    dispatched: inputs.slice(),
    undoUnits: undoUnits.slice(),
  };
}

// ═══ 2. FIVE LINES INTO A ONE-LINE ROW ═══════════════════════════════════════
// price_overrides.lines[key] holds ONE string and the red frame around the row is baked artwork.
// Every word arrives; the newlines become spaces. Losing the tail would lose customer-facing words
// and wrapping onto a second line would move text on a to-scale preview of a printed page.
{
  const { box } = mountBox(["Scope: grind and prep."]);
  const line = addPriceLine(box, "option:2", "computed");
  line.textContent = "";
  caretIn(line, 0, 0);
  paste(box, "Option 2\r\nQuartz broadcast\n\n  with integral cove\nAdd $4,500\n");
  out.multiline = { text: page.serializeBlock(line), lines: page.serializeBlock(line).split("\n").length };
}

// ═══ 3. THE SPACES KYLE TYPED ARE NOT COLLAPSED ══════════════════════════════
// syncPriceLinesIn stores what it is given with no trim and no collapse, because he aligns the
// price rows with runs of spaces. Only the newlines -- which the row cannot carry at all -- move.
{
  const { box } = mountBox(["Scope."]);
  const line = addPriceLine(box, "base", "computed");
  line.textContent = "";
  caretIn(line, 0, 0);
  paste(box, "Quartz broadcast       $41,250");
  out.spacesKept = page.serializeBlock(line);
}

// ═══ 4. A WORK SYSTEM ROW, THE SAME WAY ══════════════════════════════════════
{
  const { box } = mountBox(["Scope."]);
  const row = addSysRow(box, 0, "area", "Area:   5,200 SF");
  row.textContent = "";
  caretIn(row, 0, 0);
  const e = paste(box, "Area:  6,100 SF", '<p class=MsoNormal><b>Area:</b>  6,100 SF</p>');
  out.sysRow = {
    refusedTheBrowser: !!e.defaulted,
    text: page.serializeBlock(row),
    runs: page.editRuns(row),
    dispatched: inputs.slice(),
    undoUnits: undoUnits.slice(),
  };
}

// ═══ 5. A TEMPLATE PARAGRAPH STILL TAKES ITS FORMATTING ══════════════════════
// The path that already worked, asserted so the fix cannot have flattened it on the way past.
{
  const { blocks, box } = mountBox(["Scope: "]);
  caretIn(blocks[0], 7, 7);
  paste(box, "grind and prep", '<span style="font-weight:700">grind</span> and prep');
  out.blockKeepsFormatting = page.editRuns(blocks[0]);
}

// ═══ 6. A PASTE THAT LANDS ON NO LINE IS REFUSED ═════════════════════════════
// The caret can sit between two paragraphs of a box. Letting the browser paste there drops markup
// into the box itself, where no channel can see it and no sweep can persist it.
{
  const { box } = mountBox(["Scope."]);
  SEL = null;
  const e = paste(box, "loose text", "<b>loose text</b>");
  out.noLine = { refusedTheBrowser: !!e.defaulted, boxText: page.serializeBlock(box) };
}

// ═══ 7. FIVE LINES INTO A NOTES BULLET ARE FIVE BULLETS ══════════════════════
// The bullets' channel IS the textarea, one line per bullet, so this family keeps the newlines --
// which is also what pasting a list into a bulleted list does everywhere else. And the preview is
// rebuilt on the spot: .tw-note-edit is not pre-wrap, so five lines would otherwise render run
// together inside one bullet until the caret left the box.
{
  const { box } = mountBox(["Notes:"]);
  NOTES_TA.value = "Owner supplies the water.\nTwo mobilizations.";
  page.mountNotes(box);
  const bullets = box.querySelectorAll(".tw-note-edit");
  out.notes = { before: page.notesBullets() };
  caretIn(bullets[1], page.serializeBlock(bullets[1]).length);
  paste(box, "No work above 90 degrees.\nSlab must be dry.\nPower within 100 ft.");
  out.notes.after = page.notesBullets();
  out.notes.textarea = NOTES_TA.value;
  out.notes.undoUnits = undoUnits.slice();
  out.notes.caretBullet = SEL ? Number(SEL.line.dataset.noteIndex) : null;
  out.notes.caretAtEnd = SEL ? (SEL.range[0] === page.serializeBlock(SEL.line).length) : null;
}

// ═══ 8. ONE LINE INTO A NOTES BULLET STAYS ONE BULLET ════════════════════════
// The rebuild is for the multi-line case only: a one-line paste has nothing to reflow, and
// rebuilding anyway would take the caret away from the words just pasted for no reason.
{
  const { box } = mountBox(["Notes:"]);
  NOTES_TA.value = "Owner supplies the water.";
  page.mountNotes(box);
  const bullets = box.querySelectorAll(".tw-note-edit");
  // IN THE MIDDLE OF THE BULLET, deliberately. At the end, "the caret stayed where the splice left
  // it" and "the bullets were rebuilt and the caret went to the end" are the same offset, so the
  // scenario could not tell the two apart. Here they cannot agree.
  caretIn(bullets[0], 6, 6);                // Owner |supplies the water.
  paste(box, "really ");
  out.notesOneLine = { bullets: page.notesBullets(), caret: SEL ? SEL.range.slice() : null,
                       caretLine: SEL ? Number(SEL.line.dataset.noteIndex) : null };
}

// ═══ A PASTE OVER SEVERAL SELECTED ROWS ══════════════════════════════════════
// Ctrl+A paints the whole box and a paste replaces it. The content lands in the first row and the
// rest are emptied, every element intact -- see spliceLines for why a merge is not an option. For a
// price row "emptied" means back to the figure the estimate computed, which is what its channel
// reads an empty value as, and what clearBoxLine already does to one.
{
  const { box } = mountBox([]);
  const a = addPriceLine(box, "option:1", "Option 1 - Epoxy   $28,000");
  const c = addPriceLine(box, "option:2", "Option 2 - Quartz   $41,250");
  caretIn(a, 0, 0);
  page.setBoxSel([a, c]);
  paste(box, "Option 1 - Epoxy, revised\nsecond line");
  out.across = { first: page.serializeBlock(a), second: page.serializeBlock(c),
                 dispatched: inputs.slice(), undoUnits: undoUnits.slice() };
}


// ═══ CTRL+S ══════════════════════════════════════════════════════════════════
// The readout's three states, each read off the screen at the moment it is true. The save promise
// is held open by the harness, so "Saving..." is observed while the write is genuinely in the air
// rather than inferred from the code path that would have set it.
(async () => {
  const pressAndSettle = async (answer, resolveWith) => {
    mountBox(["Scope."]);
    SAVE_EL.hidden = true;
    SAVE_EL.textContent = "";
    delete SAVE_EL.dataset.state;
    SAVE_EL.title = "";
    saveBlockedAnswer = answer;
    saveGate = null;
    flushCalls.length = 0;
    const e = saveKey(docSurface);
    const inFlight = readout();
    if (saveGate) saveGate(resolveWith);
    await Promise.resolve(); await Promise.resolve();   // let the .then run
    return { refusedTheBrowser: !!e.defaulted, flushed: flushCalls.length,
             inFlight: inFlight, settled: readout() };
  };

  // 9. The write came back ok. This is the ONLY path that may say "Saved".
  out.saveOk = await pressAndSettle(null, true);

  // 10. The PUT was made and the server did not take it. The work is in the browser and nowhere
  //     else, and the readout has to say so rather than fall back to silence.
  out.saveFailed = await pressAndSettle(null, false);

  // 11. THE CASE flushState CANNOT SPEAK FOR. An unverified draft: shared.js holds server saves
  //     back, flushState drops the pending write and then answers `true` from an older in-flight
  //     promise. saveBlocked is asked FIRST, so no PUT is even attempted and nothing claims a save.
  out.saveBlocked = await pressAndSettle("unverified", true);

  // 12. Ctrl+Shift+S is left to the browser: taking a key away is only justified where the thing
  //     being taken away is wrong, and that combination is somebody else's screenshot tool.
  {
    mountBox(["Scope."]);
    flushCalls.length = 0;
    saveBlockedAnswer = null;
    const e = saveKey(docSurface, { shiftKey: true });
    out.shiftS = { refusedTheBrowser: !!e.defaulted, flushed: flushCalls.length };
  }

  // 13. FROM THE NOTES TEXTAREA TOO, which is the opposite of where Ctrl+Z is bound. The undo key
  //     leaves a plain input alone because the browser's undo there is correct; the Save Page sheet
  //     is wrong everywhere on this page, and the notes textarea is document content -- it is the
  //     bullets' single source of truth.
  {
    mountBox(["Scope."]);
    flushCalls.length = 0;
    saveBlockedAnswer = null;
    saveGate = null;
    const e = saveKey(NOTES_TA);
    if (saveGate) saveGate(true);
    await Promise.resolve(); await Promise.resolve();
    out.saveFromTextarea = { refusedTheBrowser: !!e.defaulted, flushed: flushCalls.length,
                             settled: readout() };
  }

  // 14. Nothing is added to the document. The readout lives in the page chrome, so the surface the
  //     generate payload is read from must not contain it at any point.
  //
  //     Checked AT LOAD as well as now: mountBox empties the surface between scenarios, so a
  //     readout that had been mounted into it on load would have been swept out again by the time
  //     the last scenario finished, and this would pass while the page was wrong.
  out.notInTheDocument = !docSurface.contains(SAVE_EL) && surfaceCleanAtLoad;

  process.stdout.write(JSON.stringify(out) + "\n");
})();
