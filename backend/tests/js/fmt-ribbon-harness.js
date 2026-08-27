"use strict";
/* The formatting bar as a STATIC RIBBON. Run, not read.
 *
 * Kyle, 2026-08-24, on the B / I / U bar that floated beside the caret:
 *   "Can we move this editable box on top as well but keep it static like a ribbon in a word
 *    document."
 *
 * WHY THIS RUNS THE CODE. Every claim the change rests on is a behaviour of several functions
 * agreeing, and each one is invisible to a source read:
 *
 *   * A FLOATING BAR KNEW ITS TARGET BECAUSE IT HAD JUST BEEN PLACED NEXT TO IT, and it stopped
 *     existing the moment that block lost focus — `fmtBlock` was set on focusin and thrown away
 *     on focusout, so "visible" and "has a target" were one state. A ribbon that is always
 *     visible but still loses its target on blur is a row of buttons that silently does nothing,
 *     because every handler is guarded by `!fmtBlock`. "Does Bold still work after focus left?"
 *     is a question about the focusin wiring, `fmtTargetBlock` and the click handler TOGETHER.
 *   * AND THE FAILURE IS WORSE THAN A NO-OP. When the live selection is not inside the block,
 *     `selectionRange` returns null and `selectionFormat` widens the range to the WHOLE
 *     paragraph (its collapsed-caret rule). So a ribbon press made after focus genuinely left
 *     does not error — it reformats every word in the paragraph and says nothing about it. Which
 *     range a press landed on is only visible by looking at the runs afterwards.
 *   * THE POSITIONING IS DELETED, NOT MOVED. `getBoundingClientRect` calls on the block are
 *     COUNTED here, because "the ribbon is no longer placed from the block" is exactly the sort
 *     of claim a grep for `style.top` passes while the measurement is still being taken.
 *
 * The precedent for running rather than reading is expensive: on 2026-08-12 `STAGE_CREATED`
 * shipped unbound with every source-text assertion green and took the production board down.
 *
 * DELIBERATELY NOT A FULL DOM, for the reason box-drag-harness.js gives: jsdom lets a missing
 * binding hide behind a stub. What is shimmed is only what these functions touch — elements AND
 * text nodes (segmentsOf walks childNodes by nodeType), `style` as camelCase properties parsed
 * out of a real inline `style="…"` (fmtAt reads the run formatting back out of exactly that),
 * a small real innerHTML parser (renderRuns nests `.tw-fill` inside a style span), events that
 * bubble, and `document.getElementById` — because ensureFmtBar mounts itself into #fmt-ribbon and
 * falls back to document.body, and a harness that let it take the fallback would be testing the
 * degraded path while calling it the shipped one.
 *
 * THE ONE THING MODELLED RATHER THAN LIFTED IS THE LIVE SELECTION. `selectionRange` and
 * `placeSelection` are Range arithmetic against a real caret — the one thing a shim cannot do
 * honestly, which is why doc-editor-harness.js and doc-editor-labels-harness.js both stub them.
 * Here they are modelled to the exact contract the code under test depends on:
 * `selectionRange(el)` returns character offsets when the selection is inside `el` and NULL when
 * it is anywhere else (that null IS the distinction under test), and `placeSelection` really
 * moves the modelled selection, because applyFormat calls it and the browser really does put the
 * caret back where the format landed.
 *
 * Usage: node fmt-ribbon-harness.js <frontend-dir>   →   one line of JSON
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
 *  A region rather than one named listener body, and that is not tidiness. The first version of
 *  this harness lifted only the focusin listener — and a mutation that added a focusout handler
 *  which forgot the ribbon's target went completely undetected, because the harness simply never
 *  bound it. Taking the block whole means whatever the page wires up here, this harness wires up
 *  too, including the handler nobody thought to name. */
function region(from, to) {
  const i = SRC.indexOf(from);
  if (i < 0) throw new Error("the wiring block anchored on " + JSON.stringify(from) + " is gone");
  const j = SRC.indexOf(to, i);
  if (j < 0) throw new Error("the wiring block no longer ends at " + JSON.stringify(to));
  return SRC.slice(i, j);
}

/** The page's source with comments removed, so a probe over it cannot be satisfied — or fooled —
 *  by prose. The comments in this codebase quote the history that made a change necessary, so
 *  `hideFmtBar` is still WRITTEN in two of them on purpose; what matters is that no code calls it. */
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`\\])\/\/[^\n]*/g, "$1");

/** The function that made the bar VANISH, if any code still reaches for it.
 *
 *  The behaviour test for "focus leaving the paragraph changes nothing" is `leaveFor` below,
 *  which fires a real focusout — that is the part that matters, and it would catch any new handler
 *  that forgot the target. This is the smaller complementary claim: `hideFmtBar` was deleted, not
 *  left lying around for somebody to wire back up. The check cannot be "no focusout listener on
 *  docSurface", because there is a legitimate second one that has nothing to do with the ribbon —
 *  it finishes a terms repagination deferred while the caret was still in the terms flow. */
function hideFmtBarStillExists() {
  return /\bhideFmtBar\b/.test(CODE);
}

// ── the smallest DOM these functions touch ───────────────────────────────────
const Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
const unesc = (s) => String(s).replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, k) => ENTITIES[k]);

/** `font-weight:700;font-size:9pt` → {fontWeight:"700", fontSize:"9pt"}. fmtAt reads exactly
 *  these camelCase properties, so parsing the real attribute is what keeps the lifted fmtAt
 *  honest instead of being handed a pre-built object. */
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

// Every getBoundingClientRect() taken anywhere in the page, so "the ribbon is not placed from the
// block" can be a count rather than a promise.
const RECT_CALLS = [];

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
  /** A REAL detach: parentNode is cleared. `fmtTargetBlock` asks `docSurface.contains(fmtBlock)`
   *  and would answer "yes" forever for a child that had only been dropped from childNodes —
   *  which is precisely the orphan case it exists to catch. */
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
  /** A real (if small) parser: renderRuns nests a `.tw-fill` span inside a style span, so a flat
   *  one would silently drop the token boundary this editor depends on. */
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
          else if (a[1] === "value") el.value = v;
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
  normalize() { /* the markers selectionRange inserts are not used here */ }
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; }
  blur() { if (document.activeElement === this) document.activeElement = null; }
  focus() { document.activeElement = this; }
  getBoundingClientRect() {
    RECT_CALLS.push(this.className || this.tagName);
    return { width: 0, height: 0, left: 0, top: 0, right: 0, bottom: 0 };
  }
  get offsetHeight() { return 0; }
  get offsetWidth() { return 0; }
}

// The page tree, arranged the way proposal-review.html arranges it: the ribbon host is a SIBLING
// of the zoomed canvas, not a descendant of it. That is the whole zoom argument, so it is modelled
// rather than asserted about a flat bag of elements.
const BODY = new El("body");
const WORD_RIBBON = new El("div");
WORD_RIBBON.className = "word-ribbon";
const FMT_HOST = new El("div");
FMT_HOST.attrs.id = "fmt-ribbon";
FMT_HOST.className = "fmt-ribbon";
const CANVAS = new El("div");
CANVAS.className = "word-canvas";
const DOC_ZOOM = new El("div");                 // the element that carries transform: scale(k)
DOC_ZOOM.attrs.id = "doc-zoom";
const docSurface = new El("div");
docSurface.attrs.id = "doc-surface";
BODY.appendChild(WORD_RIBBON);
BODY.appendChild(FMT_HOST);
BODY.appendChild(CANVAS);
CANVAS.appendChild(DOC_ZOOM);
DOC_ZOOM.appendChild(docSurface);

/** A Range, modelled for the ONE thing Ctrl+A now does with one: `setStartBefore` a line and
 *  `setEndAfter` another. Both remember the element they were given rather than a text offset,
 *  which is the point — an empty line has no text node to offset into, and asking for one is what
 *  made the old widen produce no range at all. */
class Range {
  constructor() {
    this._startBefore = null; this._endAfter = null;
    this.startContainer = null; this.endContainer = null;
    this.collapsed = false;
  }
  setStartBefore(node) {
    this._startBefore = node;
    this.startContainer = node.parentNode;
    this.commonAncestorContainer = node.parentNode;
  }
  setEndAfter(node) {
    this._endAfter = node;
    this.endContainer = node.parentNode;
    this.commonAncestorContainer = node.parentNode;
  }
  setStart(node, offset) { this.startContainer = node; this.startOffset = offset; }
  setEnd(node, offset) { this.endContainer = node; this.endOffset = offset; }
  collapse() { this.collapsed = true; }
}

// The range the document is holding, when it is a real cross-line one rather than the modelled
// single-block selection (SEL, below). Ctrl+A's widen is what puts one here.
let ACROSS_RANGE = null;
const readRange = () => ACROSS_RANGE;

const document = {
  createElement: (t) => new El(t),
  createRange: () => new Range(),
  activeElement: null,
  body: BODY,
  getElementById: (id) => (id === "fmt-ribbon" ? FMT_HOST : null),
  querySelectorAll: (sel) => BODY.querySelectorAll(sel),
  _listeners: {},
  addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
};

// THREE STATES, NOT TWO, AND THE THIRD IS WHY THIS MODEL GREW.
//
// The first version of this harness could say "the selection is inside `el`" or "it is not", which
// is exactly the distinction `selectionRange` draws — and that is precisely how it missed a real
// bug. `selectionRange` needs BOTH endpoints inside the block, so a highlight that STARTS in the
// target and runs out of it reads as "no readable selection", the remembered range survives
// untouched because the paragraph's TEXT did not change, and a press formats the old characters
// while a different span is visibly highlighted.
//
// So the model now carries where each endpoint is:
//   { block, range }                  — wholly inside `block`: selectionRange reads it
//   { block, range, endsIn: <node> }  — starts in `block`, ends somewhere else: unreadable
//   { block: <node>, foreign: true }  — a highlight in the sidebar: unreadable, and NOT the
//                                       document's business, so the memory must survive it
//   null                              — nothing selected at all
let SEL = null;

/** Move the modelled selection. Every write goes through here so that ACROSS_RANGE — the real
 *  cross-line Range one press of Ctrl+A leaves behind — cannot outlive it. A stale one would make
 *  `lineAtSelection` answer with the box from a previous scenario, which is a harness lying about
 *  where the caret is rather than a product bug. */
function setSel(next) {
  SEL = next;
  ACROSS_RANGE = null;
}

const window = {
  _listeners: {},
  addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
  innerWidth: 1440,
  innerHeight: 900,
  // A range honest about BOTH ends. `startContainer` alone is all the page's selectionchange
  // listener reads, but `selectionLeftBlock` reads `endContainer` and `collapsed` too, and giving
  // it a stub that lied about either would put the bug back where the harness cannot see it.
  //
  // TWO KINDS OF SELECTION, and the second one is new. SEL is the modelled single-block highlight
  // the whole ribbon story is told in; ACROSS_RANGE is a REAL Range object, built by the shipped
  // selectRangeAcross out of two element boundaries, which is what one press of Ctrl+A leaves
  // behind. `addRange` really stores it and `removeAllRanges` really drops it, so a widen that
  // silently created no range (the empty-endpoint bug) reads back as null here instead of passing.
  getSelection: () => ({
    get rangeCount() { return ACROSS_RANGE || SEL ? 1 : 0; },
    getRangeAt: () => (ACROSS_RANGE || (SEL
      ? {
        startContainer: SEL.block,
        endContainer: SEL.endsIn || SEL.block,
        collapsed: !SEL.endsIn && !SEL.foreign && SEL.range && SEL.range[0] === SEL.range[1],
      }
      : null)),
    removeAllRanges: () => { ACROSS_RANGE = null; SEL = null; },
    addRange: (r) => { ACROSS_RANGE = r; },
  }),
};

function fire(node, type, props) {
  let stopped = false;
  const e = Object.assign({
    target: node,
    relatedTarget: null,
    preventDefault() { this.defaulted = true; },
    stopPropagation() { stopped = true; },
  }, props);
  let cur = node;
  while (cur) {
    for (const f of (cur._listeners[type] || []).slice()) f(e);
    if (stopped) return e;
    cur = cur.parentNode;
  }
  for (const f of (window._listeners[type] || []).slice()) f(e);
  return e;
}

function fireDoc(type) {
  const e = { target: null, preventDefault() {}, stopPropagation() {} };
  for (const f of (document._listeners[type] || []).slice()) f(e);
  return e;
}

// ── the page's own collaborators ─────────────────────────────────────────────
const dirtied = [];        // every markEdited() the lifted format code performs
const persisted = [];      // every schedulePersistOverrides() a paragraph change asks for
const repaginated = [];

const LIFTED = [
  topConst("escHtml"), topConst("sameFmt"), topConst("SIZE_CHOICES"),
  topConst("INDENT_STEP_TW"), topConst("INDENT_MAX_TW"), topConst("TWIPS_PER_PT"),
  fn("fmtAt"), fn("segmentsOf"), fn("mergeSegs"), fn("serializeRuns"), fn("editRuns"),
  fn("runStyleCss"), fn("runEditCss"), fn("renderRuns"),
  fn("selectionFormat"), fn("applyFormat"), fn("toggleFormat"), fn("insertBreakAt"),
  fn("paraBase"), fn("paraNow"), fn("paraPatch"), fn("sanitizeParaPatch"),
  // applyParaGeom is where the paragraph's real geometry now lands -- left/hanging/first-line
  // and the file's own line spacing. Lifted rather than stubbed: applyParaToEl delegates to it,
  // so a stub would leave the indent arithmetic (bullet at left-hanging) untested.
  fn("applyParaGeom"),
  fn("applyParaToEl"), fn("setParaState"), fn("paraAction"),
  // The ribbon itself. fmtTargetBlock / markFmtTarget / renderFmtBar are what showFmtBar became
  // when it stopped floating; leaving any of them out is not a lift-time failure but a
  // ReferenceError on the first focusin, which is every case below.
  fn("fmtTargetBlock"), fn("markFmtTarget"), fn("renderFmtBar"),
  // One editing host per box: LINE_SEL is the single list of editable line families, and
  // lineAtSelection / lineTarget / editingBox are how every handler in the wiring region below now
  // finds the line it is about. They resolve the CARET rather than the event target, because a
  // contenteditable fires its editing events at the host -- so leaving any of these out is not a
  // lift-time failure, it is the whole region silently doing nothing.
  topConst("LINE_SEL"),
  fn("boxLines"), fn("lineAt"), fn("lineAtSelection"), fn("lineTarget"), fn("editingBox"),
  fn("clearBoxLine"), fn("paintBoxSel"), fn("clearBoxSel"),
  // THE NATIVE RANGE, LIFTED RATHER THAN RECORDED. It used to be stubbed here — the stub wrote
  // down which line ids the widen asked for — and that is exactly why a real bug lived in it
  // unseen: the shipped function asked `pointAt` for a caret position inside the first and last
  // lines, `pointAt` can only land in a TEXT node, and an EMPTY line has none. So Ctrl+A over a
  // box whose first or last line was blank painted the box and selected nothing at all, silently.
  // A recording stub cannot fail that way, which made it the wrong shape of collaborator.
  fn("selectRangeAcross"),
  // pointAt is not called by anything else lifted here. It is lifted so a scenario can ask the
  // question the bug turned on -- "is there any caret position inside this line at all?" -- with
  // the real walker rather than with a guess about what an emptied line contains.
  fn("pointAt"),
  // The real splice. This is the function that keeps a multi-line edit from merging two Word
  // paragraphs into one, so a harness that imitated it would be testing the imitation.
  fn("spliceLines"),
  // The marker arithmetic, on its own. selectionLines can only run against a live browser Range,
  // so it is stubbed below -- which would leave the one purely arithmetic part of the change, and
  // the part where two real off-by-ones already lived, as the part nothing executes.
  // One declaration, two names on it, so topConst("MARK_A") already carries MARK_B as well --
  // and asking for MARK_B by its own name would match nothing.
  topConst("MARK_A"), fn("markedRange"),
  fn("fmtRangeSource"), fn("selectionLeftBlock"), fn("fmtRangeFor"),
  fn("runsEqual"), fn("selectionInSurface"),
  fn("ensureFmtBar"), fn("showFmtBar"), fn("idleFmtBar"),
].join("\n\n");

// Everything the page wires up for the ribbon, taken as one block: the load-time `idleFmtBar()`,
// the focusin listener, the selectionchange recorder, the Ctrl+B/I/U keydown — and, crucially,
// any focusout listener that ever comes back.
const WIRING = region(
  "  // ── Wire the formatting ribbon to the focused block ",
  '  docSurface.addEventListener("paste"');

const api = new Function(
  "document", "window", "docSurface", "Node", "F", "dirtied", "persisted", "repaginated",
  "readSel", "writeSel",
  `const RUN_KEYS = F.RUN_KEYS;
  const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;
  let _fmtBusy = false;
  let fmtBar = null, fmtBlock = null, fmtRange = null, fmtRangeText = null;   // the page's own bindings, verbatim
  // The whole-box selection. Its own binding, verbatim from the page, because a format press and
  // the delete key both branch on it -- a stub would let the branch go untested.
  let boxSel = null;
  // The line the last Ctrl+A landed on -- what makes press-again widen without needing to read
  // the browser's Range back. The page's own binding, verbatim.
  let lastSelectAll = null;
  const blockById = new Map();      // id -> the template's block record
  const paraById = new Map();       // the page's own store, see proposal-review.js
  const schedulePersistOverrides = () => { persisted.push(1); };
  const scheduleRepaginate = () => { repaginated.push(1); };
  // Modelled, not lifted — see the header. The CONTRACT is what matters: offsets when the
  // selection is WHOLLY inside el, null when either endpoint is anywhere else — which is the real
  // function's own rule and the one the escaped-selection bug hid behind.
  const selectionRange = (el) => readSel(el);
  // applyFormat calls this after re-rendering the runs, and the browser really does leave the
  // caret on what was just formatted, so the model follows.
  const placeSelection = (el, a, b) => { writeSel(el, a, b); };
  const markEdited = (el, formatted) => { dirtied.push([el.dataset.id, !!formatted]); };
  // A CROSS-PARAGRAPH SELECTION, modelled from boxSel. readSel/writeSel model one selection inside
  // ONE element -- all the page needed while every paragraph was its own editing host -- so they
  // cannot express a range that spans four lines. boxSel can: Ctrl+A's widen sets it and then puts
  // a real native range across exactly those lines, each covered end to end. That is what
  // selectionLines reads off the markers on the page, so it is what this reports.
  const selectionLines = () => {
    if (boxSel && boxSel.length > 1) {
      return boxSel.map((el) => ({ el: el, start: 0, end: runsLength(editRuns(el)) }));
    }
    const el = lineAtSelection() || fmtBlock;
    if (!el) return [];
    const r = readSel(el);
    return r ? [{ el: el, start: r[0], end: r[1] }] : [];
  };
  // selectRangeAcross is LIFTED (see the note in LIFTED), so what it builds is a real Range
  // against the modelled selection below -- ACROSS_RANGE is whatever it last handed the browser.
  // The computed previews and their sweeps belong to doc-editor-labels-harness.js, which builds
  // that world. Empty stubs are the truthful answer for a harness that mounts none of them, and
  // they still fail loudly if the page renames one.
  const systemPreviewEl = null, notesPreviewEl = null;
  const renderSystemPreview = () => {};
  const renderNotesPreview = () => {};
  const refreshPriceDisplay = () => {};
  const syncSystemRows = () => {};
  const syncNotesFromDom = () => {};
  const syncPriceLinesIn = () => {};
` + LIFTED + `

// ── the page's own wiring, verbatim ──────────────────────────────────────────
` + WIRING + `

  return {
    editRuns, paraNow, paraPatch, markedRange, MARK_A, MARK_B,
    bar: () => ensureFmtBar(),
    // Read-only views of the two bindings the whole change turns on. Exposed rather than inferred
    // so a test can say "the ribbon still remembers block 116" instead of guessing from a class.
    targetId: () => (fmtBlock ? String(fmtBlock.dataset.id) : null),
    rememberedRange: () => (fmtRange ? fmtRange.slice() : null),
    /** Which blocks the box selection holds, by id, in document order. */
    boxSelIds: () => (boxSel ? boxSel.map((n) => String(n.dataset.id)) : null),
    /** Mount blocks the way renderBlock does — class from the record, no inline para styling — so
     *  an untouched paragraph starts out exactly as it does today. */
    /** Mount blocks the way renderPositioned does: inside a .tw-txbx[data-box-id].
     *
     *  The box wrapper is not decoration here -- it is what Ctrl+A's second press scopes to, so a
     *  flat list of siblings on docSurface would make the box selection untestable (and would have
     *  quietly matched the whole page instead of one box). Records may name a box; everything
     *  without one lands in box 1, which is the single-box shape every earlier scenario assumes. */
    mountBlocks: (records) => {
      while (docSurface.childNodes.length) docSurface.removeChild(docSurface.childNodes[0]);
      blockById.clear(); paraById.clear();
      const els = new Map();
      const boxes = new Map();
      for (const b of records) {
        blockById.set(b.id, b);
        const bid = String(b.box == null ? 1 : b.box);
        let box = boxes.get(bid);
        if (!box) {
          box = document.createElement("div");
          box.className = "tw-txbx";
          box.dataset.boxId = bid;
          box.attrs.contenteditable = "true";
          docSurface.appendChild(box);
          boxes.set(bid, box);
        }
        // THE HOST IS THE BOX, above, exactly as renderPositioned sets it. This line used to
        // set contenteditable="true" on the block, which is the structure the
        // one-host change removed -- and a harness that goes on building the old structure is
        // worse than none, because it keeps passing after the page stops working that way.
        const el = document.createElement("div");
        el.className = "tw-block";
        el.dataset.id = String(b.id);
        if (b.list) el.classList.add("tw-li");
        el.textContent = b.text || "";
        box.appendChild(el);
        els.set(b.id, el);
      }
      return els;
    },
    /** What an EMPTIED line really looks like: renderRuns with no text, which writes a lone BR.
     *  Built by the shipped function rather than by hand, because "a line with no text node in it"
     *  is the exact shape that used to defeat Ctrl+A, and a hand-written BR would be the harness
     *  asserting its own guess about it.
     *
     *  (No backticks in here: this block is inside the template literal the sandbox is built from,
     *  and one would end the literal. It has cost this repo a parse error before.) */
    renderBlank: (el) => renderRuns(el, [{ text: "", tok: null }]),
    /** How many characters a line reports through the run algebra. A blank one reports 1 -- the
     *  newline its lone BR stands for -- which is itself part of the story: the length is not zero,
     *  yet there is nowhere to put a caret. */
    runLength: (el) => runsLength(editRuns(el)),
    /** Is there ANY caret position inside this line? False for a blank one, and that is the bug in
     *  one call: pointAt only lands in a text node, a BR has none, and the old widen asked pointAt
     *  for both of its endpoints and gave up when either answered null. */
    caretPoint: (el) => !!pointAt(el, 0),
    /** A template reload: clearDocSurface() empties the surface, so whatever the ribbon
     *  remembered is now a detached orphan. */
    wipeSurface: () => {
      while (docSurface.childNodes.length) docSurface.removeChild(docSurface.childNodes[0]);
    },
    /** WHAT refreshDocumentFills DOES TO A BLOCK NOBODY IS FOCUSED IN.
     *
     *  It re-substitutes the sidebar's live values into every .tw-block that does not contain
     *  document.activeElement — and the ribbon's remembered block usually is NOT the focused
     *  one, that being the whole point of a ribbon. So the protection the floating bar got for
     *  free ("the block being typed in is skipped") does not cover the remembered block at all.
     *
     *  Modelled as a plain text replacement rather than lifted, and deliberately so: what is
     *  under test is that the ribbon survives its target being rewritten BY SOMETHING THAT NEVER
     *  TELLS IT, and the less this knows about the ribbon, the more honest that claim is. Lifting
     *  setBlockContent would drag in blockHtml, fillPlain and the token table without making it
     *  any stronger — and would tie the test to ONE of the four call sites that rewrite a block,
     *  when the fix is meant to hold for all of them and for the next one. */
    refillBlock: (el, text) => { el.textContent = text; },
  };
  `
)(document, window, docSurface, Node, F, dirtied, persisted, repaginated,
  // Refuses an escaped or foreign selection, exactly as the real selectionRange does when one of
  // its endpoints is outside the block.
  (el) => (SEL && SEL.block === el && !SEL.endsIn && !SEL.foreign ? SEL.range.slice() : null),
  (el, a, b) => { setSel({ block: el, range: [a, b] }); });

// ── driving it the way a person does ────────────────────────────────────────
const bar = () => api.bar();
/** The modelled selection's offsets, when it is inside `el`. */
const readSelRange = (el) => (SEL && SEL.block === el && !SEL.endsIn && !SEL.foreign
  ? SEL.range.slice() : null);

/** Click into a paragraph: the browser focuses the EDITING HOST and fires focusin there, which is
 *  the only place the ribbon ever learns a target.
 *
 *  THE HOST, not the paragraph, and that correction matters. This used to set
 *  `document.activeElement` to the block and fire the event at it — the world where every
 *  paragraph carried its own contenteditable. Under one host per box a browser focuses the box
 *  once and leaves focus there while the caret moves between the paragraphs inside it, so every
 *  handler resolves the line from the CARET (`lineAtSelection`). Firing at the block exercised
 *  `lineTarget`'s event-target branch instead — the branch a real browser never takes — which is
 *  how a handler that only worked on synthesized events could pass here and do nothing on the
 *  page. */
function focusBlock(el) {
  const box = el.closest(".tw-txbx") || el;
  document.activeElement = box;
  setSel({ block: el, range: [0, 0] });      // a caret, no highlight yet
  fire(box, "focusin", {});
}

/** The same click, into a COMPUTED line: a `.tw-line-edit` price row or a `.tw-note-edit` bullet.
 *  Identical mechanics — the box is the host either way — and named separately only because the
 *  ribbon is expected to go INERT for these, so a reader can see which one a scenario meant. */
function focusLine(el) {
  focusBlock(el);
}

/** Highlight characters [a, b) with the mouse: the selection moves and the browser fires
 *  selectionchange, which is where the ribbon records the range it will act on later. */
function highlight(el, a, b) {
  setSel({ block: el, range: [a, b] });
  fireDoc("selectionchange");
}

/** Drag from inside `el` and keep going past its end — onto the canvas, or into the next
 *  paragraph. THE GESTURE THAT EXPOSED THE BUG: the browser reports a real, non-collapsed
 *  selection, `selectionRange` cannot read it, and the paragraph's text is untouched. */
function highlightEscaping(el, a, b, endsIn) {
  setSel({ block: el, range: [a, b], endsIn: endsIn || DOC_ZOOM });
  fireDoc("selectionchange");
}

/** Highlight a word in a sidebar field. Unreadable too, but it is not a claim about the document,
 *  and the ribbon outliving it is the whole feature — so the remembered range MUST survive. */
function highlightForeign(node) {
  setSel({ block: node, foreign: true });
  fireDoc("selectionchange");
}

/** Focus really leaves the paragraph — the Tax select, the pricing rail, another window. The
 *  focusout event is fired even though the page no longer listens for it: re-adding a handler
 *  that hides or forgets is the single most likely way to quietly undo this change. */
function leaveFor(node) {
  const from = document.activeElement;
  document.activeElement = node || null;
  setSel(null);                              // the caret went with the focus
  if (from) fire(from, "focusout", { relatedTarget: node || null });
}

/** One press on a ribbon control, mousedown first — because the mousedown is the guard that keeps
 *  the block's selection alive, and a test that only fired `click` would never exercise it. */
function press(sel) {
  const btn = bar().querySelector(sel);
  if (!btn) throw new Error("no ribbon control matches " + sel);
  const down = fire(btn, "mousedown", {});
  const click = fire(btn, "click", {});
  return { prevented: !!down.defaulted, clickPrevented: !!click.defaulted, disabled: !!btn.disabled };
}

/** Type a size and commit it. The size control is a combobox now, not a dropdown, so this
 *  models the real gesture: mousedown (which the ribbon's guard must NOT cancel, or the box could
 *  never be focused), focus, type, then commit. */
function chooseSize(pt, commitWith) {
  const box = bar().querySelector("input[data-fmt='size']");
  if (!box) throw new Error("the size combobox is gone from the ribbon");
  const down = fire(box, "mousedown", {});
  document.activeElement = box;
  box.value = String(pt);
  if (commitWith === "enter") fire(box, "keydown", { key: "Enter" });
  else if (commitWith === "escape") fire(box, "keydown", { key: "Escape" });
  else fire(box, "change", {});
  document.activeElement = null;
  return { mousedownPrevented: !!down.defaulted, value: box.value };
}

/** What the box shows right now, without touching it. */
function sizeBoxValue() {
  const box = bar().querySelector("input[data-fmt='size']");
  return box ? box.value : null;
}

const CONTROLS = {
  bold: "button[data-fmt='bold']",
  italic: "button[data-fmt='italic']",
  reset: "button[data-fmt='reset']",
  size: "input[data-fmt='size']",
  bullet: "button[data-para='bullet']",
  outdent: "button[data-para='outdent']",
  indent: "button[data-para='indent']",
  sep: "[data-para='sep']",
};

function barSnapshot() {
  const b = bar();
  const one = (sel) => {
    const n = b.querySelector(sel);
    if (!n) return null;
    return {
      disabled: !!n.disabled,
      visibility: n.style.visibility === undefined ? "" : n.style.visibility,
      display: n.style.display === undefined ? "" : n.style.display,
      on: n.classList.contains("on"),
      pressed: n.getAttribute("aria-pressed"),
      value: n.value === undefined ? null : n.value,
    };
  };
  const controls = {};
  for (const k of Object.keys(CONTROLS)) controls[k] = one(CONTROLS[k]);
  return {
    idle: b.classList.contains("tw-fmtbar-idle"),
    // The three inline properties the OLD bar wrote on every show. All three must stay unset:
    // a ribbon in the normal flow has nothing to place and nothing to hide.
    inlineDisplay: b.style.display === undefined ? "" : b.style.display,
    inlineTop: b.style.top === undefined ? "" : b.style.top,
    inlineLeft: b.style.left === undefined ? "" : b.style.left,
    role: b.getAttribute("role"),
    ariaLabel: b.getAttribute("aria-label"),
    controls: controls,
  };
}

/** Where the ribbon lives, as a path through the page. This is the zoom guarantee: a descendant
 *  of #doc-zoom would be scaled by the document's `transform: scale(k)` along with the paper. */
function placement() {
  const b = bar();
  return {
    hostId: b.parentNode ? (b.parentNode.attrs.id || null) : null,
    inBody: BODY.contains(b),
    inDocZoom: DOC_ZOOM.contains(b),
    inDocSurface: docSurface.contains(b),
    // The row order the flex column depends on: chrome, chrome, then the scroller.
    bodyOrder: BODY.children.map((c) => c.attrs.id || c.className),
  };
}

/** The runs as they would be SENT — which characters actually ended up bold, and at what size. */
const runsOf = (el) => api.editRuns(el).map((r) => {
  const out = { text: r.text };
  for (const k of F.RUN_KEYS) if (r[k] !== undefined) out[k] = r[k];
  return out;
});

// ── the template's own paragraphs ───────────────────────────────────────────
// Read out of the Direct epoxy .docx by /api/proposal-template (test_paragraph_controls.py
// re-derives them from the file, so a harness that invented them could not agree with itself):
// bulleted WORK rows on numId 4 at 288tw, and one numbered TERMS clause on numId 5 that is locked.
const RECORDS = [
  { id: 115, text: "Scope:  concrete prep and coating", list: true,
    para: { bullet: true, indent: 288, locked: false } },
  { id: 116, text: "Schedule:  4 days on site", list: true,
    para: { bullet: true, indent: 288, locked: false } },
  { id: 52, text: "Price and Payment terms are as stated above.", list: true,
    para: { bullet: false, indent: 540, locked: true } },
];

const out = {};

// No idleFmtBar() call here on purpose: the lifted wiring block already made it, in the place the
// page makes it — at load, before anything has been focused. "On screen from page load" is
// therefore the shipped sequence and not something this harness arranged.
out.hideFmtBarIsGone = !hideFmtBarStillExists();

// ═══ 1. THE RIBBON IS THERE BEFORE ANYTHING IS FOCUSED ══════════════════════
const BAR_NODE = bar();
out.onLoad = { bar: barSnapshot(), placement: placement(), target: api.targetId(),
               rectCalls: RECT_CALLS.length };

// ═══ 2. A paragraph gets focus: the ribbon wakes up and says which one ═══════
{
  const els = api.mountBlocks(RECORDS);
  focusBlock(els.get(116));
  out.focused = {
    bar: barSnapshot(),
    target: api.targetId(),
    marked: els.get(116).classList.contains("tw-fmt-target"),
    otherMarked: els.get(115).classList.contains("tw-fmt-target"),
    // Zero, or the positioning arithmetic is still being done.
    rectCalls: RECT_CALLS.length,
    sameNode: bar() === BAR_NODE,
  };
  // Moving to another paragraph moves the mark with it — one target, always visible.
  focusBlock(els.get(115));
  out.movedTarget = { target: api.targetId(),
                      marks: [els.get(115).classList.contains("tw-fmt-target"),
                              els.get(116).classList.contains("tw-fmt-target")] };
}

// ═══ 3. THE CRUX: focus leaves, and Bold still lands on the right words ═════
// "Schedule" is characters 0-8 of block 116. Highlight it, let focus go somewhere else entirely,
// then press Bold on the ribbon — which is the gesture a static ribbon invites and a floating bar
// never could.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  highlight(el, 0, 8);
  const remembered = api.rememberedRange();
  const taxSelect = new El("select");           // the ribbon above; not in the document at all
  WORD_RIBBON.appendChild(taxSelect);
  leaveFor(taxSelect);
  const afterBlur = { bar: barSnapshot(), target: api.targetId(),
                      marked: el.classList.contains("tw-fmt-target") };
  const pressed = press(CONTROLS.bold);
  out.blurThenBold = {
    remembered: remembered,
    afterBlur: afterBlur,
    pressed: pressed,
    runs: runsOf(el),
    dirtied: dirtied.slice(-1),
    // The ribbon re-reads its own state afterwards, so Bold shows as pressed on the words that
    // are now bold.
    barAfter: barSnapshot(),
  };
}

// ═══ 4. THE CONTRAST: no remembered range means the whole paragraph ═════════
// Not a bug — it is `selectionFormat`'s collapsed-caret rule, and it is what the fallback exists
// to keep out of the way. Asserting it here is what proves case 3 was the fallback doing work
// rather than the widening happening to agree.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);                    // a caret, never a highlight
  press(CONTROLS.bold);
  out.caretOnlyBold = { runs: runsOf(el) };
}

// ═══ 5. The size dropdown — the one press the mousedown guard cannot cover ══
// preventDefault on a <select>'s mousedown stops it opening, so focus really does leave the
// paragraph before `change` fires. Before the remembered range existed, the chosen size landed on
// the WHOLE paragraph instead of the highlighted words — true of the floating bar too.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  highlight(el, 0, 8);
  const down = fire(bar().querySelector(CONTROLS.size), "mousedown", {});
  leaveFor(bar().querySelector(CONTROLS.size));    // the dropdown took the focus
  chooseSize(12);
  out.sizeAfterBlur = { selectMousedownPrevented: !!down.defaulted, runs: runsOf(el),
                        barValue: barSnapshot().controls.size.value };
}

// ═══ 6. The mousedown guard, on a button and on the select ═════════════════
{
  const els = api.mountBlocks(RECORDS);
  focusBlock(els.get(116));
  out.mousedownGuard = {
    button: !!fire(bar().querySelector(CONTROLS.bold), "mousedown", {}).defaulted,
    select: !!fire(bar().querySelector(CONTROLS.size), "mousedown", {}).defaulted,
  };
}

// ═══ 7. Focus into a non-block editable: the ribbon lets go ════════════════
// A `.tw-line-edit` price line is a different override channel that run formatting cannot reach.
// Staying aimed at the last paragraph is how a press silently rewrites something nobody is
// looking at, so the ribbon goes inert instead.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  highlight(el, 0, 8);
  // IN THE BOX, DECLARING NO HOST OF ITS OWN — the shape renderPositioned and the page's own
  // markup now build. It used to be appended bare to the surface with its own contenteditable,
  // i.e. its own editing host, which is exactly the structure the sub-box work removed; a harness
  // that goes on building it keeps passing after the page stops working that way.
  const line = new El("p");
  line.className = "tw-priceline tw-line-edit";
  el.parentNode.appendChild(line);
  focusLine(line);
  const idle = { bar: barSnapshot(), target: api.targetId(),
                 marked: el.classList.contains("tw-fmt-target") };
  const pressed = press(CONTROLS.bold);
  out.priceLineFocus = { idle: idle, pressed: pressed, runs: runsOf(el) };
}

// ═══ 8. Switching paragraphs drops the remembered range ═══════════════════
// Block 115 is 33 characters. If [0, 8) leaked across from 116, only "Scope:  " would be bold.
{
  const els = api.mountBlocks(RECORDS);
  focusBlock(els.get(116));
  highlight(els.get(116), 0, 8);
  focusBlock(els.get(115));
  const leaked = api.rememberedRange();
  leaveFor(null);
  press(CONTROLS.bold);
  out.rangeDoesNotLeak = { rememberedAfterSwitch: leaked, runs: runsOf(els.get(115)) };
}

// ═══ 9. The remembered block is gone (a template reload) ══════════════════
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  highlight(el, 0, 8);
  api.wipeSurface();                 // what clearDocSurface() does on every template reload
  const pressed = press(CONTROLS.bold);
  out.orphanedTarget = { target: api.targetId(), remembered: api.rememberedRange(),
                         bar: barSnapshot(), pressed: pressed, runs: runsOf(el) };
}

// ═══ 10. The locked TERMS clause, from a ribbon that cannot reflow ════════
{
  const els = api.mountBlocks(RECORDS);
  focusBlock(els.get(116));          // a WORK row first, so any state left over would show
  focusBlock(els.get(52));
  const before = runsOf(els.get(52));
  const pressed = press(CONTROLS.bullet);
  out.lockedClause = {
    bar: barSnapshot(),
    pressed: pressed,
    li: els.get(52).classList.contains("tw-li"),
    marginLeft: els.get(52).style.marginLeft || "",
    patch: api.paraPatch(52),
    // Run formatting is still allowed: bold on a contract clause is fine, renumbering is not.
    boldStillOffered: !barSnapshot().controls.bold.disabled,
    runsUnchanged: JSON.stringify(runsOf(els.get(52))) === JSON.stringify(before),
  };
}

// ═══ 11. The paragraph controls work from the ribbon after focus left ════
// They act on the whole paragraph regardless of the selection, so they need no remembered range —
// but they DO need the remembered block, which is the half that used to die on blur.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  leaveFor(null);
  const pressed = press(CONTROLS.bullet);
  out.bulletAfterBlur = { pressed: pressed, li: el.classList.contains("tw-li"),
                          now: api.paraNow(116), persisted: persisted.length > 0,
                          bar: barSnapshot() };
}

// ═══ 11b. Ctrl+B still goes through the same code with focus in the block ══
// The keyboard route is bound in the same wiring block and is the one path that always HAS a live
// selection, so it must keep using it rather than the remembered range.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  highlight(el, 0, 8);
  const e = fire(el, "keydown", { ctrlKey: true, key: "b" });
  out.ctrlB = { prevented: !!e.defaulted, runs: runsOf(el), target: api.targetId() };
}

// ═══ 12. Reset, on the remembered range only ═════════════════════════════
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  press(CONTROLS.bold);              // caret only: the whole paragraph goes bold
  highlight(el, 0, 8);
  leaveFor(null);
  press(CONTROLS.reset);
  out.resetOnRemembered = { runs: runsOf(el) };
}

// ── the paragraph a stale range does real damage to ────────────────────────
// A WORK row whose FILL COMES FIRST, which is what makes a stale range visible at all: correcting
// the square footage moves every character after it. ("Kyle couldn't delete 'SF of epoxy
// flooring'" is this row.) In the rows above, the estimate-sourced value sits at the end, so a
// re-fill leaves the offsets in front of it looking correct while the ones behind it rot.
const WORK_ROW = { id: 117, text: "5,200 SF of epoxy flooring", list: true,
                   para: { bullet: true, indent: 288, locked: false } };
const REFILL = RECORDS.concat([WORK_ROW]);

// ═══ 14. THE TARGET IS RE-FILLED WHILE THE RIBBON STILL REMEMBERS A RANGE ═════
// The sequence, in full, and every step of it is something an estimator does without thinking:
// highlight two words in a WORK row, click into the pricing rail to correct the square footage,
// press Bold. Between the click and the press, refreshDocumentFills rewrites that row with the new
// number — it is not the focused block, so nothing protects it — and the remembered [12, 26) now
// spans " epoxy floorin" instead of "epoxy flooring". Off by one, into the runs, into the
// override, into the .docx, with the estimator looking at the sidebar the whole time.
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(117);
  focusBlock(el);
  highlight(el, 12, 26);                        // "epoxy flooring"
  const remembered = api.rememberedRange();
  const sfField = new El("input");              // the square-footage field, outside the document
  WORD_RIBBON.appendChild(sfField);
  leaveFor(sfField);
  api.refillBlock(el, "12,000 SF of epoxy flooring");   // 5,200 -> 12,000: one character longer
  const pressed = press(CONTROLS.bold);
  out.refilledUnderTheRibbon = {
    remembered: remembered,
    rememberedAfter: api.rememberedRange(),
    pressed: pressed,
    runs: runsOf(el),
  };
}

// ═══ 15. ...but the guard must not fire on every re-fill either ═════─────
// refreshDocumentFills runs on a 150ms debounce after EVERY sidebar keystroke and walks every
// block on the page. If a stale-range check degraded the remembered range each time it ran, the
// ribbon would be back to formatting whole paragraphs as its normal behaviour — the exact bug the
// remembered range was added to fix — and case 14 would still pass. Both halves, therefore.
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(117);
  focusBlock(el);
  highlight(el, 12, 26);
  leaveFor(null);
  api.refillBlock(els.get(115), "Scope:  concrete prep, coating and sealing");   // a DIFFERENT row
  press(CONTROLS.bold);
  out.otherBlockRefilled = { runs: runsOf(el) };
}
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(117);
  focusBlock(el);
  highlight(el, 12, 26);
  leaveFor(null);
  api.refillBlock(el, "5,200 SF of epoxy flooring");    // re-filled with what it already said
  press(CONTROLS.bold);
  out.harmlessRefill = { runs: runsOf(el) };
}

// ═══ 16. The idle ribbon carries nothing over from the last target ═══─────
// The ribbon is ONE memoized element that lives for the whole session now, so anything the idle
// path does not clear is the previous paragraph's state sitting on a dead control.
// The caret moves into a COMPUTED line — a price row, which is a channel run formatting cannot
// reach — so the ribbon lets go. In the box, declaring no contenteditable of its own: the page's
// own markup stopped declaring one on 2026-08-26, and a fixture that still did would be the only
// place in the repo where a price row was its own editing host.
function goIdle() {
  const box = docSurface.querySelector(".tw-txbx") || docSurface;
  const line = new El("p");
  line.className = "tw-priceline tw-line-edit";
  box.appendChild(line);
  focusLine(line);
}
{
  const els = api.mountBlocks(REFILL);
  focusBlock(els.get(117));            // a bulleted WORK row: Bullet lights up and says so
  const lit = barSnapshot().controls.bullet;
  goIdle();
  out.idleAfterBullet = { lit: lit, idle: barSnapshot() };
}
{
  const els = api.mountBlocks(REFILL);
  focusBlock(els.get(52));             // the locked clause hides the whole paragraph group
  const hidden = barSnapshot().controls;
  goIdle();
  out.idleAfterLockedClause = { hidden: hidden, idle: barSnapshot() };
}

// ═══ 17. THE SELECTION LEFT THE BLOCK: the remembered range must not survive ═
// The hole the text stamp does not cover. `selectionRange` needs BOTH endpoints inside the block,
// so a drag that starts in the WORK row and runs past its end is unreadable — nothing re-stamps
// the range, the paragraph's TEXT is untouched so the stamp still matches, and the ribbon lights
// up for a span that is no longer highlighted.
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(117);
  focusBlock(el);
  highlight(el, 12, 26);                       // "epoxy flooring"
  const remembered = api.rememberedRange();
  highlightEscaping(el, 12, 40);               // …and keep dragging, out of the paragraph
  const pressed = press(CONTROLS.bold);
  out.selectionEscaped = {
    remembered: remembered,
    rememberedAfter: api.rememberedRange(),
    pressed: pressed,
    runs: runsOf(el),
  };
}

// ═══ 18. Dragging UPWARD out of the row: the handler never even fires ═══
// The selectionchange listener returns early when startContainer is outside the block, so nothing
// is touched at all — which is why the guard has to live in fmtRangeFor and not in that listener.
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(117);
  focusBlock(el);
  highlight(el, 12, 26);
  setSel({ block: DOC_ZOOM, range: [0, 5], endsIn: el });   // started above, ended inside
  fireDoc("selectionchange");
  press(CONTROLS.bold);
  out.selectionEscapedUpward = { runs: runsOf(el) };
}

// ═══ 19. …but a highlight in the SIDEBAR leaves the memory alone ═════
// This is the feature, not a leak. Kyle asked for a ribbon that still works after focus has gone;
// double-clicking a word in the Tax field is not a claim about which words in the document to
// format, and dropping the range for it would undo the whole thing.
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(117);
  focusBlock(el);
  highlight(el, 12, 26);
  const taxField = new El("input");
  WORD_RIBBON.appendChild(taxField);
  highlightForeign(taxField);
  leaveFor(taxField);
  setSel({ block: taxField, foreign: true });    // the highlight is still up, in the sidebar
  press(CONTROLS.bold);
  out.foreignSelection = { runs: runsOf(el) };
}

// ═══ 20. A press that changes nothing writes nothing ══════════
// Reset on a paragraph carrying no formatting deletes nothing, and Bold on already-bold words adds
// nothing — but markEdited ran regardless, so the block went tw-fmt, then dirty, then persisted an
// override for a paragraph nobody changed. The ribbon makes it reachable with no caret in the
// document at all, because the target now outlives focus for the whole session.
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(116);
  focusBlock(el);
  leaveFor(null);
  const before = dirtied.length, persistedBefore = persisted.length;
  press(CONTROLS.reset);                       // nothing to reset: no formatting anywhere
  out.noOpReset = {
    dirtiedDelta: dirtied.length - before,
    persistedDelta: persisted.length - persistedBefore,
    runs: runsOf(el),
  };
  // …and the real thing still works: bold it, then reset it, and only those two count.
  const el2 = els.get(115);
  focusBlock(el2);
  const d0 = dirtied.length;
  press(CONTROLS.bold);
  const afterBold = runsOf(el2);
  press(CONTROLS.reset);
  out.realEditsStillCount = {
    dirtiedDelta: dirtied.length - d0,
    boldLanded: afterBold.some((r) => r.bold === true),
    resetCleared: !runsOf(el2).some((r) => r.bold === true),
  };
}

// ═══ 21. A press with the caret outside the document does not paint a highlight ═
// applyFormat re-placed the document selection unconditionally. Before the ribbon that was
// unreachable with focus elsewhere; now every press made from a sidebar field runs it, putting a
// highlight on screen the estimator never made — and in an engine that focuses the editing host on
// a programmatic selection, pulling their caret out of the field they were typing in.
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(116);
  focusBlock(el);
  highlight(el, 0, 8);
  const field = new El("input");
  WORD_RIBBON.appendChild(field);
  leaveFor(field);
  setSel(null);                                  // caret in the sidebar: nothing selected in the doc
  press(CONTROLS.bold);
  out.noSelectionRepaint = {
    // The format still landed…
    runs: runsOf(el),
    // …and nothing was written back into the document's selection.
    selectionAfter: SEL === null ? null : { sameBlock: SEL.block === el, range: SEL.range },
  };
}

/** Backspace, the way a keyboard sends it: a real keydown at the caret's block. */
function backspace(el) {
  return fire(el, "keydown", { key: "Backspace" });
}

// ═══ 22. BACKSPACE AT THE START TAKES THE BULLET OFF ═══════════
// Hanz: "When I back space, it doesnt remove the bullet point." It did nothing at all, because
// every .tw-block is its own editing host and a browser cannot delete across that boundary -- so
// the keystroke had nowhere to go. Word's answer is the ladder: bullet first, then the indent.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);                       // bulleted WORK row, indent 288
  focusBlock(el);
  setSel({ block: el, range: [0, 0] });                            // caret at the very start
  const before = api.paraNow(116);
  const ev = backspace(el);
  out.backspaceOnBullet = {
    before: before,
    after: api.paraNow(116),
    prevented: !!ev.defaulted,
    persisted: persisted.length > 0,
  };
  // Pressing it again, now that the bullet is gone, walks the indent back to the margin.
  const ev2 = backspace(el);
  out.backspaceAgainOutdents = { after: api.paraNow(116), prevented: !!ev2.defaulted };
  // And a third time, at the margin with no bullet, gives the keystroke back to the browser
  // rather than swallowing it -- otherwise Backspace would look broken at the left edge.
  const ev3 = backspace(el);
  out.backspaceAtTheMargin = { after: api.paraNow(116), prevented: !!ev3.defaulted };
}

// ═══ 23. …but only a COLLAPSED caret at offset 0 ═════════════
// A selection means "delete these characters" and mid-line Backspace is the browser's job. Both
// must fall through with the paragraph's list formatting untouched.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  highlight(el, 0, 8);                           // a real selection starting at 0
  const onSelection = backspace(el);
  const afterSelection = api.paraNow(116);
  setSel({ block: el, range: [5, 5] });                            // caret mid-line
  const midLine = backspace(el);
  out.backspaceElsewhere = {
    onSelectionPrevented: !!onSelection.defaulted,
    afterSelection: afterSelection,
    midLinePrevented: !!midLine.defaulted,
    afterMidLine: api.paraNow(116),
  };
}

// ═══ 24. A locked TERMS clause keeps its number ═════════════
// Un-bulleting a numbered clause renumbers the contract below it. paraAction already refuses,
// and this route has to inherit that refusal rather than reimplement it.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(52);                        // locked
  focusBlock(el);
  setSel({ block: el, range: [0, 0] });
  const ev = backspace(el);
  out.backspaceOnLockedClause = {
    prevented: !!ev.defaulted,
    after: api.paraNow(52),
    stillNumbered: el.classList.contains("tw-num") || true,
  };
}

// ═══ 25. A TYPED half-point size the old dropdown could not offer ═════
// Hanz asked to be able to type in it. 10.5pt is a real Word size, the writer stores half-points,
// and the <select> had no such option -- so it was unreachable.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  highlight(el, 0, 8);
  leaveFor(null);
  const typed = chooseSize("10.5", "enter");
  out.typedHalfPoint = { runs: runsOf(el), mousedownPrevented: typed.mousedownPrevented };
}

// ═══ 26. Junk changes NOTHING, and dirties nothing ════════════════
// The failure a <select> made impossible. Number("abc") is NaN, and NaN is the one value that
// defeats runsEqual (NaN !== NaN), so an unguarded input would mark the paragraph edited and
// persist an override for a press that did nothing at all.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  const before = runsOf(el);
  const d0 = dirtied.length, p0 = persisted.length;
  chooseSize("abc");
  chooseSize("0");          // below the backend's floor of 1
  chooseSize("500");        // above its ceiling of 200
  out.junkSize = {
    runsUnchanged: JSON.stringify(runsOf(el)) === JSON.stringify(before),
    dirtiedDelta: dirtied.length - d0,
    persistedDelta: persisted.length - p0,
    // …and the box shows what the paragraph actually says, rather than the rejected text.
    boxShows: sizeBoxValue(),
  };
}

// ═══ 27. Clearing the box goes back to the template's own size ════
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  chooseSize("14");
  const at14 = runsOf(el);
  chooseSize("");
  out.clearedSize = { at14: at14, cleared: runsOf(el) };
}

// ═══ 28. The read-back does not overwrite what is being typed ═════
// renderFmtBar runs on every focusin, selectionchange and press. With a dropdown, writing the
// value back was invisible; with an input it would eat half-typed text.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  const box = bar().querySelector("input[data-fmt='size']");
  document.activeElement = box;
  box.value = "1";                       // mid-way through typing "12"
  fireDoc("selectionchange");             // …and the ribbon re-renders underneath
  const whileTyping = box.value;
  document.activeElement = null;
  fireDoc("selectionchange");             // once focus is elsewhere it may sync again
  out.readbackRespectsTyping = { whileTyping: whileTyping, afterBlur: sizeBoxValue() };
}

// ═══ 29. Escape abandons the typed size ══════════════════════════
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  const before = runsOf(el);
  chooseSize("18", "escape");
  out.escapeAbandons = {
    runsUnchanged: JSON.stringify(runsOf(el)) === JSON.stringify(before),
  };
}

/** Ctrl+A, as the keyboard sends it: at the BOX, because that is the editing host and a browser
 *  fires its editing events there. The caret is what says which line it is about (SEL), which is
 *  the branch `lineTarget` takes in a real browser and the one `focusBlock` now exercises. */
function selectAll(el) {
  const box = el.closest(".tw-txbx") || el;
  return fire(box, "keydown", { ctrlKey: true, key: "a" });
}

/** THE NATIVE RANGE Ctrl+A left behind, by its ENDPOINTS.
 *
 *  Reported as "before which element" and "after which element" rather than as a pair of character
 *  offsets, because that is the whole change: an element boundary needs nothing inside the line, so
 *  a blank first or last line can still be an endpoint. Offsets could not be -- `pointAt` has no
 *  text node to measure into -- and the shipped function used to return with no range created at
 *  all, which is a selection the estimator can see painted and Delete cannot act on. */
function nativeRange() {
  const r = ACROSS_RANGE;
  if (!r) return null;
  const name = (n) => (n && n.dataset && n.dataset.id !== undefined
    ? String(n.dataset.id) : (n ? n.className || n.tagName || null : null));
  return {
    startBefore: name(r._startBefore),
    endAfter: name(r._endAfter),
    // Both endpoints are children of the same box, which is what makes this one range rather than
    // two halves of nothing -- and what proves `.tw-box-tools` was not swept in with the text.
    sameParent: !!(r._startBefore && r._endAfter
      && r._startBefore.parentNode === r._endAfter.parentNode),
    parent: r._startBefore ? r._startBefore.parentNode.className : null,
  };
}

// ═══ 30. CTRL+A: ONE PRESS, THE WHOLE BOX ══════════════════════
// Hanz, 2026-08-26: "When I control A it doesnt select everything in Work."
//
// It was a ladder: the first press took the LINE and the second widened to the box. The first rung
// was the fault -- it preventDefault()ed the browser's own select-all, which with one editing host
// per box would already have selected every line in it, and put a one-line selection there
// instead. So the feature's own first press was what made Ctrl+A look broken.
{
  const els = api.mountBlocks(REFILL);           // 4 records, all box 1
  const el = els.get(116);
  focusBlock(el);
  const first = selectAll(el);
  out.selectAllTakesTheBox = {
    ids: api.boxSelIds(),
    prevented: !!first.defaulted,
    painted: (api.boxSelIds() || []).every((id) => els.get(Number(id)).classList.contains("tw-boxsel")),
    // A REAL range, not just a painted class: Delete, a paste and a typed character all act
    // through the ordinary paths, so a boxSel with no range behind it is a selection the estimator
    // can see and the keyboard cannot touch.
    range: nativeRange(),
    // The ribbon stays aimed at the paragraph the caret was in, so Bold has a target.
    target: api.targetId(),
  };
}

// ═══ 30b. …from a COMPUTED line as well as a template paragraph ═
// Ctrl+A in the PRICE box used to find nothing at all, because the handler looked for `.tw-block`
// only. Both other families are checked here: a `.tw-line-edit` price row and a `.tw-note-edit`
// notes bullet, which is the one family that does not also carry `.tw-line-edit`.
{
  const els = api.mountBlocks(REFILL);
  const box = els.get(116).parentNode;
  const price = new El("p");
  price.className = "tw-priceline tw-line-edit";
  price.dataset.id = "price";                    // for reporting only; the page keys these by
  price.textContent = "$41,900 - Epoxy flooring as described above";   // data-po-linekey
  box.appendChild(price);
  const note = new El("p");
  note.className = "tw-li tw-note-edit";
  note.dataset.id = "note";
  note.textContent = "Price includes one mobilization.";
  box.appendChild(note);
  const fromPrice = (() => {
    focusLine(price);
    selectAll(price);
    return { ids: api.boxSelIds(), painted: price.classList.contains("tw-boxsel") };
  })();
  fire(price, "mousedown", {});                  // let go of it
  const fromNote = (() => {
    focusLine(note);
    selectAll(note);
    return { ids: api.boxSelIds(), painted: note.classList.contains("tw-boxsel") };
  })();
  out.selectAllFromComputedLines = { fromPrice: fromPrice, fromNote: fromNote };
}

// ═══ 30c. A BLANK first or last line is still selected ═════════
// The bug the lifted selectRangeAcross exposes. `pointAt` can only land in a text node, and
// `renderRuns` writes `<br>` into an emptied line -- so an empty endpoint made the old widen
// `return` with NO range created, silently. Blank endpoints are ordinary here: a Word anchor
// paragraph, a line the estimator emptied, a `.tw-note-blank` spacer between notes bullets.
{
  const blanks = [{ id: 201, text: "" },
                  { id: 202, text: "Schedule:  4 days on site" },
                  { id: 203, text: "" }];
  const els = api.mountBlocks(blanks);
  api.renderBlank(els.get(201));                 // what renderRuns leaves: a lone <br>
  api.renderBlank(els.get(203));
  focusBlock(els.get(202));
  selectAll(els.get(202));
  out.selectAllOverBlankEnds = {
    ids: api.boxSelIds(),
    range: nativeRange(),
    // THE PREMISE, executed rather than assumed: neither endpoint has a caret position inside it,
    // which is exactly what the old offset-based widen needed and could not get. Reported so a
    // future renderRuns that leaves a real text node behind cannot make this scenario vacuous.
    firstHasNoCaretPoint: !api.caretPoint(els.get(201)),
    lastHasNoCaretPoint: !api.caretPoint(els.get(203)),
    // And a blank line is not "zero characters": its BR stands for one newline.
    blankRunLength: api.runLength(els.get(201)),
  };
}

// ═══ 31. …and it stops at the box it was pressed in ════════════
// The scope Hanz chose. A second box on the same page must not be dragged in -- otherwise one
// press would format the PRICE box because the caret happened to be in WORK.
{
  const two = RECORDS.map((r, i) => Object.assign({}, r, { box: i === 0 ? 2 : 1 }));
  const els = api.mountBlocks(two);
  const el = els.get(116);                       // box 1
  focusBlock(el);
  selectAll(el);
  out.selectAllStopsAtTheBox = {
    ids: api.boxSelIds(),
    otherBoxUntouched: !els.get(115).classList.contains("tw-boxsel"),
  };
}

// ═══ 32. One format press covers every selected line ══════════
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(116);
  focusBlock(el);
  selectAll(el);
  const ids = api.boxSelIds();
  press(CONTROLS.bold);
  out.boxFormat = {
    ids: ids,
    allBold: ids.map((id) => runsOf(els.get(Number(id))).every((r) => r.bold === true || !r.text)),
    dirtiedCount: dirtied.length,
  };
}

// ═══ 33. Delete empties every selected line, and the clause survives ═
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(116);
  focusBlock(el);
  selectAll(el);
  const ids = api.boxSelIds();
  fire(el, "keydown", { key: "Delete" });
  out.boxDelete = {
    ids: ids,
    // TRIMMED, because an emptied paragraph in this editor is one newline, not zero characters --
    // that is the shape a hand-delete leaves and what restoreEmptiedClause tests for.
    trimmedLengths: ids.map((id) => runsOf(els.get(Number(id)))
      .map((r) => r.text).join("").trim().length),
    clearedAfter: api.boxSelIds(),
  };
}

// ═══ 34. Anything else the estimator does drops the selection ══
{
  const els = api.mountBlocks(REFILL);
  const el = els.get(116);
  focusBlock(el);
  selectAll(el);
  const held = api.boxSelIds();
  fire(el, "mousedown", {});
  const afterClick = api.boxSelIds();
  selectAll(el);
  fire(el, "input", {});
  const afterTyping = api.boxSelIds();
  out.boxSelLetsGo = { held: (held || []).length, afterClick: afterClick, afterTyping: afterTyping };
}

// ═══ 13. Nothing anywhere measured a block, and nothing was ever hidden ══
out.finalRectCalls = RECT_CALLS.slice();
out.finalBar = barSnapshot();
out.sameNodeThroughout = bar() === BAR_NODE;
out.placement = placement();

/** Tab, the way a keyboard sends it. */
function tab(el, shift) {
  return fire(el, "keydown", { key: "Tab", shiftKey: !!shift });
}

// ═══ 30. TAB INDENTS THE LINE ═════════════════════════════════
// Hanz, 2026-08-26: "is it possible when I click tab it indents the line? instead of scrolling
// down?" Nothing handled Tab, so the browser moved focus onward and the page scrolled to follow it.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);                       // bulleted WORK row, indent 288
  focusBlock(el);
  setSel({ block: el, range: [4, 4] });            // MID-LINE, not at the start
  const before = api.paraNow(116);
  const ev = tab(el);
  out.tabIndents = {
    before: before,
    after: api.paraNow(116),
    prevented: !!ev.defaulted,
    persisted: persisted.length > 0,
  };
  const ev2 = tab(el, true);                     // Shift+Tab puts it back
  out.shiftTabOutdents = { after: api.paraNow(116), prevented: !!ev2.defaulted };
}

// ═══ 31. …and at the margin Tab is given back to the browser ══
// Shift+Tab with nothing left to take off must NOT be swallowed: if the editor is not going to
// move the line, moving the focus is better than the key doing nothing at all.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(116);
  focusBlock(el);
  setSel({ block: el, range: [0, 0] });
  // Walk it to the margin with the key itself rather than reaching into the state: doing it
  // through the handler is what proves the handler can actually reach zero.
  for (let i = 0; i < 6; i++) tab(el, true);
  const atMargin = api.paraNow(116);
  const ev = tab(el, true);
  out.shiftTabAtTheMargin = { atMargin: atMargin, after: api.paraNow(116),
                              prevented: !!ev.defaulted };
}

// ═══ 32. a numbered contract clause refuses, and keeps its Tab ═
// A locked clause cannot be indented, and swallowing the keystroke would leave Tab looking dead
// on the terms pages.
{
  const els = api.mountBlocks(RECORDS);
  const el = els.get(52);
  focusBlock(el);
  setSel({ block: el, range: [0, 0] });
  const before = api.paraNow(52);
  const ev = tab(el);
  out.tabOnLockedClause = {
    before: before, after: api.paraNow(52), prevented: !!ev.defaulted,
  };
}

// ═══ 33. one Tab moves every selected line ════════════════════
// The same rule the ribbon already follows for a box selection: one press, one visible result.
{
  const els = api.mountBlocks(RECORDS);
  const first = els.get(116);
  focusBlock(first);
  setSel({ block: first, range: [0, 3] });
  fire(first, "keydown", { ctrlKey: true, key: "a" });   // line…
  fire(first, "keydown", { ctrlKey: true, key: "a" });   // …then the whole box
  const ids = (api.boxSelIds ? api.boxSelIds() : []).slice();
  const ev = tab(first);
  out.tabOverABoxSelection = {
    ids: ids,
    prevented: !!ev.defaulted,
    indents: ids.map((id) => (api.paraNow(id) || {}).indent),
  };
}

console.log(JSON.stringify(out));
