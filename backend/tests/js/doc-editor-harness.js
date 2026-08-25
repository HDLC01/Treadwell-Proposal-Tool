"use strict";
/* The proposal document editor's two Kyle-reported behaviours, RUN rather than read.
 *
 * Kyle, 2026-08-19, on the Proposal Review document editor:
 *   (b) "when he pressed enter to add spacing it did not generate in the proposal"
 *   (d) "He is confused on how to get out of that Textbox view"
 *
 * WHY THIS RUNS THE CODE. Both are behaviours no source assertion can see.
 *
 *   * The way out of an expanded box is a NEGATIVE: `wireOverflowExpand` must ignore a click
 *     on editable content (you are typing) and must NOT ignore the Collapse button, Escape, or
 *     a click off the box. "Which of four clicks reaches which branch" is delegation and
 *     `closest()` order, and reading the source is exactly how the trap got shipped in the
 *     first place — the exclusion list was correct and left no pixel that could close the box.
 *   * One Enter must become ONE newline in the text that leaves the page, survive being
 *     re-rendered from its own runs, and survive the reload path. That is three different
 *     walkers (segmentsOf, serializeBlock, renderRuns) agreeing on the same character.
 *
 * The precedent for running it is expensive: on 2026-08-12 `STAGE_CREATED` shipped unbound with
 * every source-text assertion green and took the production board down.
 *
 * DELIBERATELY NOT A FULL DOM, for the reason box-drag-harness.js gives: jsdom would let a
 * missing binding hide behind a stub. What is shimmed here is only what these functions touch:
 *   * elements AND text nodes, because serializeBlock/segmentsOf walk childNodes by nodeType;
 *   * `style` as camelCase properties parsed out of a real inline `style="…"`, because fmtAt
 *     reads the run formatting back out of exactly that;
 *   * offsetHeight following the font-size percentage fitTxbx sets and floored by minHeight —
 *     the same honest model box-drag-harness uses, so "this box overflows" is a measurement
 *     rather than a stub returning what the test wants;
 *   * events that bubble to `window`, because Escape and the outside click are bound there.
 *
 * Box geometry is set directly rather than through renderPositioned's loop: box-drag-harness
 * already proves the loop mounts `.tw-box-tools`, and what is under test here is what the
 * tools contain and which click does what.
 *
 * Usage: node doc-editor-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
// Normalized to LF: the repo's frontend is checked out CRLF on Windows and every pattern below
// anchors on "\n  " indentation. A CR left in would make the lifted source subtly different
// from the shipped source, which is the one thing this harness must not allow.
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

/** One delegated listener body out of the page's top level, by the comment that introduces it.
 *  Lifted so the Enter key is exercised through the REAL handler — the guards it puts in front
 *  of insertBreakAt (Ctrl/Meta/Alt, IME composition, "is this even a .tw-block") are most of
 *  what could go wrong. */
function delegated(anchor) {
  const i = SRC.indexOf(anchor);
  if (i < 0) throw new Error("the listener anchored on " + JSON.stringify(anchor) + " is gone");
  const open = SRC.indexOf("{", SRC.indexOf("(e) =>", i));
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(open, j + 1);
  }
  throw new Error("unbalanced braces reading the listener at " + anchor);
}

// ── the smallest DOM these functions touch ───────────────────────────────────
const PX_PER_PT = 96 / 72;
const Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };

const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
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
    this._naturalPx = 0;            // height the content would take at 100% font
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
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  get textContent() {
    return this.childNodes.map((n) =>
      n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent).join("");
  }
  /** The reload path: restoreSavedOverrides writes the saved plain text straight in here and
   *  relies on `white-space: pre-wrap` to render its newlines. */
  set textContent(v) {
    this.childNodes = [];
    if (String(v) !== "") this.appendChild(new Text(v));
  }
  /** A real (if small) parser: renderRuns nests a `.tw-fill` span inside a style span, so a
   *  flat one would silently drop the token boundary this editor depends on. */
  set innerHTML(html) {
    this.childNodes = [];
    const stack = [this];
    const re = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w-]+="[^"]*")*)\s*\/?>|([^<]+)/g;
    let m;
    while ((m = re.exec(html))) {
      const top = stack[stack.length - 1];
      if (m[1]) {                                        // closing tag
        if (stack.length > 1) stack.pop();
      } else if (m[2]) {                                 // opening tag
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
      } else if (m[4] !== undefined) {                    // text
        top.appendChild(new Text(unesc(m[4])));
      }
    }
  }
  get innerHTML() {
    return this.childNodes.map((n) => {
      if (n.nodeType === Node.TEXT_NODE) return n.nodeValue;
      const cls = n.className ? ' class="' + n.className + '"' : "";
      return VOID.has(n.tagName) ? "<" + n.tagName.toLowerCase() + ">"
        : "<" + n.tagName.toLowerCase() + cls + ">" + n.innerHTML + "</" + n.tagName.toLowerCase() + ">";
    }).join("");
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
  blur() { if (document.activeElement === this) document.activeElement = null; }
  focus() { document.activeElement = this; }
  getBoundingClientRect() { return { width: 0, height: 0, left: 0, top: 0 }; }
  get offsetHeight() {
    const pct = /^(\d+)%$/.exec(this.style.fontSize || "");
    const k = pct ? Number(pct[1]) / 100 : 1;
    const floorPt = parseFloat(this.style.minHeight || "0") || 0;
    return Math.max(Math.round(this._naturalPx * k), Math.round(floorPt * PX_PER_PT));
  }
}

const document = {
  createElement: (t) => new El(t),
  activeElement: null,
  body: new El("body"),
  querySelectorAll: () => [],
};
const window = {
  _listeners: {},
  addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
};

/** Bubble an event from `el` up through its ancestors and then to `window`, like the real
 *  thing — Escape and the outside click are bound on window, so an event that stopped at the
 *  surface would prove nothing about them.
 *
 *  `stopPropagation` stops the walk to the NEXT node but not the remaining listeners on the
 *  node it was called on, which is what the DOM does and matters here: proposal-review.js binds
 *  several click listeners to `docSurface` (the overflow toggle, the box Reset), and a harness
 *  that skipped the later ones would hide a control that had stopped working. */
function fire(node, type, props) {
  let stopped = false;
  const e = Object.assign({
    target: node,
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

// ── the page's own collaborators, as the page binds them ─────────────────────
const docSurface = new El("div");
const pageBackground = new El("div");        // somewhere on the page that is NOT a text box
const dirtied = [];                          // every markEdited() the lifted code performs

// fitTxbx calls fitOffer, so fitOffer has to be lifted here even though this harness is about
// the collapse/Escape/label behaviour and not about box geometry. Leaving it out does not fail
// at lift time — it throws `ReferenceError: fitOffer is not defined` the first time a box
// overflows, which is every test in this file.
//
// The REAL fitOffer runs, and declines: it looks the box up in boxDesign and returns "" when it
// is not there. This harness registers no box geometry, so that is the honest answer rather
// than a stub pretending to be one — the geometry paths are exercised in
// doc-editor-labels-harness.js, which does build the box world. boxDesign is declared INSIDE the
// sandbox below, not out here: the lifted code runs in a `new Function` scope and cannot see this
// module's own bindings.
const LIFTED = [
  topConst("escHtml"), topConst("DOC_TOKEN_RE"), topConst("sameFmt"),
  fn("fitOffer"),
  fn("fillHtml"), fn("runStyleCss"), fn("blockHtml"),
  fn("fmtAt"), fn("segmentsOf"), fn("mergeSegs"), fn("serializeRuns"), fn("editRuns"),
  fn("runEditCss"), fn("renderRuns"), fn("serializeBlock"), fn("insertBreakAt"), fn("pointAt"),
  fn("addBoxTools"), fn("fitTxbx"), fn("wireOverflowExpand"),
].join("\n\n");

const ENTER_HANDLER = delegated("  // Enter inside a template paragraph = ONE line break");

const api = new Function(
  "document", "window", "docSurface", "F", "Node", "dirtied",
  `const RUN_KEYS = F.RUN_KEYS;
  // Empty on purpose — see the note above LIFTED. fitOffer looks a box up here and returns ""
  // when it is absent, so no box in this harness is ever offered growth, which is the truthful
  // answer for a harness that mounts no page geometry.
  const boxDesign = new Map();
` + LIFTED + `
  // The page's own caret readers are NOT lifted: selectionRange/placeSelection are Range
  // arithmetic against a live selection, which is the one thing a shim cannot model honestly.
  // The handler is lifted verbatim and given a caret it can read, so the guards in front of
  // insertBreakAt — modifier keys, IME composition, "is the target even a block" — are the
  // real ones. CARET is [start, end] character offsets, i.e. what selectionRange returns.
  let CARET = null;
  const selectionRange = () => CARET;
  const placed = [];
  const placeSelection = (el, a, b) => { placed.push([a, b]); };
  const markEdited = (el, formatted) => { dirtied.push([el.dataset.id, !!formatted]); };
  const onEnter = (e) => ${ENTER_HANDLER};
  docSurface.addEventListener("keydown", onEnter);

  wireOverflowExpand();
  return { blockHtml, serializeBlock, serializeRuns, editRuns, renderRuns, insertBreakAt,
           addBoxTools, fitTxbx,
           // Where the caret would actually LAND, as a node kind + offset. placeSelection can
           // only build a Range inside a text node, so "the caret went after the break" is a
           // claim about what pointAt returns, not about what the offset arithmetic says.
           caretLanding: (el, offset) => {
             const p = pointAt(el, offset);
             if (!p) return null;
             return { isText: p.node.nodeType === Node.TEXT_NODE, offset: p.offset,
                      atEndOfNode: p.offset === String(p.node.nodeValue || "").length,
                      after: String(p.node.nodeValue || "").slice(0, p.offset).slice(-1) };
           },
           setCaret: (r) => { CARET = r; }, placed: () => placed };
  `
)(document, window, docSurface, F, Node, dirtied);

const out = {};

// ═══ (d) getting OUT of an expanded text box ═════════════════════════════════
// 183.75pt is box 3 of Kyle's GC Resinous template, measured from the file rather than
// invented; 400pt of content in it is the real complaint (a long WORK scope).
// The clipped height is deliberately NOT computed here — test_doc_editor_ux.py states it
// independently, so a harness that got the arithmetic wrong cannot agree with itself.
const DESIGN_H = 183.75;

function mountBox(naturalPt) {
  docSurface.childNodes = [];
  const box = new El("div");
  box.className = "tw-txbx";
  box.dataset.boxId = "3";
  box.dataset.boxHPt = String(DESIGN_H);
  box.style.minHeight = DESIGN_H + "pt";
  docSurface.appendChild(box);
  // A real editable paragraph inside it — the thing that makes the trap a trap.
  const block = new El("div");
  block.className = "tw-block";
  block.dataset.id = "115";
  block.attrs.contenteditable = "true";
  box.appendChild(block);
  api.addBoxTools(box);
  box._naturalPx = Math.round(naturalPt * PX_PER_PT);
  api.fitTxbx(box);
  return { box, block };
}

const state = (box) => ({
  open: box.classList.contains("tw-notes-open"),
  overflow: box.classList.contains("tw-notes-overflow"),
  maxHeight: box.style.maxHeight,
  overflowStyle: box.style.overflow,
  zIndex: box.style.zIndex,
});

const collapseBtn = (box) => box.querySelector("[data-box-collapse]");

// 1. The box really is over capacity, and the tools carry a labelled way out.
{
  const { box } = mountBox(400);
  out.clipped = state(box);
  const btn = collapseBtn(box);
  out.tools = {
    hasCollapse: !!btn,
    label: btn ? btn.textContent : null,
    title: btn ? btn.title : null,
    inToolsLayer: !!(btn && btn.closest(".tw-box-tools")),
    isNotAGrip: !!(btn && btn.attrs["data-grip"] === undefined),
    // The order the tools are written in, so adding one can be seen not to have displaced the
    // grips box-drag-harness.js asserts the order of.
    order: box.querySelector(".tw-box-tools").children.map((c) => c.className),
  };
}

// 2. A click on the box body opens it (the existing peek), and the Collapse button closes it.
{
  const { box } = mountBox(400);
  fire(box, "click", {});
  const opened = state(box);
  fire(collapseBtn(box), "click", {});
  out.collapseButton = { opened: opened, closed: state(box) };
}

// 3. THE TRAP: a click on the editable content of an OPEN box must not close it — you are
//    typing. This is why the button/Escape/outside click had to exist.
{
  const { box, block } = mountBox(400);
  fire(box, "click", {});
  fire(block, "click", {});
  const afterBlockClick = state(box);
  // The nested case: a click on a `.tw-fill` island inside the paragraph.
  const fill = new El("span");
  fill.className = "tw-fill";
  block.appendChild(fill);
  fire(fill, "click", {});
  out.typingKeepsItOpen = { afterBlockClick: afterBlockClick, afterFillClick: state(box) };
}

// 4. Escape, with the caret inside the box's own paragraph.
{
  const { box, block } = mountBox(400);
  fire(box, "click", {});
  document.activeElement = block;
  const e = fire(block, "keydown", { key: "Escape" });
  out.escape = { closed: state(box), blurred: document.activeElement === null,
                 defaultPrevented: !!e.defaulted };
}

// 5. Escape when nothing is open must not swallow the key — Escape means other things on this
//    page, and a handler that always preventDefaults steals them.
{
  const { box } = mountBox(400);
  const e = fire(box, "keydown", { key: "Escape" });
  out.escapeWhenClosed = { open: box.classList.contains("tw-notes-open"),
                           defaultPrevented: !!e.defaulted };
}

// 6. Escape must not blur a field OUTSIDE the box (the sidebar is full of them).
{
  const { box } = mountBox(400);
  fire(box, "click", {});
  const elsewhere = new El("input");
  pageBackground.appendChild(elsewhere);
  document.activeElement = elsewhere;
  fire(elsewhere, "keydown", { key: "Escape" });
  out.escapeFromElsewhere = { closed: state(box),
                              stillFocused: document.activeElement === elsewhere };
  document.activeElement = null;
}

// 7. A click on the page outside the box collapses it.
{
  const { box } = mountBox(400);
  fire(box, "click", {});
  fire(pageBackground, "click", {});
  out.outsideClick = state(box);
}

// 7b. …but a click on the formatting ribbon does NOT, even though ensureFmtBar mounts it in the
//     page's top chrome (#fmt-ribbon since 2026-08-24, document.body before that) and it is
//     therefore "outside the box" in the DOM either way. It is chrome for the paragraph being
//     edited, and now that it never moves it is the one control that is ALWAYS outside the box.
{
  const { box } = mountBox(400);
  fire(box, "click", {});
  const host = new El("div");
  host.attrs.id = "fmt-ribbon";
  const bar = new El("div");
  bar.className = "tw-fmtbar";
  const boldBtn = new El("button");
  boldBtn.attrs["data-fmt"] = "bold";
  bar.appendChild(boldBtn);
  host.appendChild(bar);
  document.body.appendChild(host);
  fire(boldBtn, "click", {});
  out.formatBarClick = state(box);
}

// 8. …and a click on ANOTHER expanded box does not leave the first one open behind it.
{
  docSurface.childNodes = [];
  const boxes = [];
  for (const id of ["3", "5"]) {
    const box = new El("div");
    box.className = "tw-txbx";
    box.dataset.boxId = id;
    box.dataset.boxHPt = String(DESIGN_H);
    docSurface.appendChild(box);
    api.addBoxTools(box);
    box._naturalPx = Math.round(400 * PX_PER_PT);
    api.fitTxbx(box);
    fire(box, "click", {});
    boxes.push(box);
  }
  const bothOpen = boxes.map((b) => b.classList.contains("tw-notes-open"));
  fire(pageBackground, "click", {});
  out.manyBoxes = { bothOpen: bothOpen, afterOutside: boxes.map((b) => state(b)) };
}

// 9. Re-fitting (what every edit and repagination does) must also put it back, or a box left
//    open would stay open across a render with a stale maxHeight.
{
  const { box } = mountBox(400);
  fire(box, "click", {});
  api.fitTxbx(box);
  out.refitCollapses = state(box);
}

// ═══ (b) a blank line the estimator types must reach the .docx ═══════════════
// Block 115 of the Direct epoxy template, VERBATIM as /api/proposal-template reports it —
// three runs, the label bold and the value explicitly un-bolded, at the template's real 8pt
// Zetta Serif Book. Not a two-run simplification: `bold: false` and `bold` ABSENT are different
// instructions to the writer, and a fixture that used the friendlier shape would be testing a
// payload the page never sends. test_doc_editor_ux.py re-derives these runs from the .docx and
// fails if they have drifted, so this cannot rot into fiction.
const FMT = { italic: null, underline: null, size_pt: 8.0,
              font: "Zetta Serif Book", color: "404040" };
const BLOCK = {
  id: 115,
  text: "Scope:  {{scope_notes}}",
  runs: [
    Object.assign({ text: "Scope:", bold: true }, FMT),
    Object.assign({ text: "  ", bold: false }, FMT),
    Object.assign({ text: "{{scope_notes}}", bold: false }, FMT),
  ],
};
const TOKENS = { scope_notes: "Grind and coat." };
out.fixtureRuns = BLOCK.runs;

function mountBlock() {
  const el = new El("div");
  el.className = "tw-block";
  el.dataset.id = String(BLOCK.id);
  el.attrs.contenteditable = "true";
  docSurface.childNodes = [];
  docSurface.appendChild(el);
  el.innerHTML = api.blockHtml(BLOCK, TOKENS);
  return el;
}

// 10. The pristine rendering, and that the label really arrives bold (the (a) claim: these
//     labels are real editable text, not artwork).
{
  const el = mountBlock();
  out.pristine = {
    text: api.serializeBlock(el),
    runs: api.serializeRuns(el),
    fills: el.querySelectorAll(".tw-fill").map((s) => s.attrs["data-token"]),
  };
}

// 11. ONE Enter at the end of the paragraph = ONE newline. Driven through the page's own
//     keydown handler, with the caret where selectionRange would have reported it.
{
  const el = mountBlock();
  const n = api.serializeBlock(el).length;
  api.setCaret([n, n]);
  const e = fire(el, "keydown", { key: "Enter" });
  const once = api.serializeBlock(el);
  api.setCaret([once.length, once.length]);
  fire(el, "keydown", { key: "Enter" });
  const twice = api.serializeBlock(el);
  out.enter = {
    once: once, twice: twice, defaultPrevented: !!e.defaulted,
    caretsPlaced: api.placed().slice(-2),
    dirtied: dirtied.slice(-2),
    // What the .docx must be built from, and what a re-render of the same content produces.
    runs: api.serializeRuns(el),
  };
  // The caret after the break the estimator just typed — the next character they type has to
  // land AFTER it, not on the line above. placeSelection can only put a caret in a text node.
  out.enter.caretLanding = api.caretLanding(el, twice.length);
  // Stability: re-render from the serialized runs (what applyFormat/paste do) and read back.
  api.renderRuns(el, api.serializeRuns(el));
  out.enter.afterRerender = api.serializeBlock(el);
  out.enter.caretLandingAfterRerender = api.caretLanding(el, twice.length);
  // Stability across the RELOAD path: restoreSavedOverrides writes the stored plain text in
  // as textContent and lets `white-space: pre-wrap` render the newlines.
  const el2 = mountBlock();
  el2.textContent = twice;
  out.enter.afterReload = api.serializeBlock(el2);
}

// 12. The modifier and IME guards: Ctrl+Enter, Alt+Enter and an in-flight IME composition are
//     not "insert a line break", and a plain Enter outside a `.tw-block` is not ours at all.
{
  const el = mountBlock();
  const base = api.serializeBlock(el);
  api.setCaret([base.length, base.length]);
  const results = {};
  for (const [name, props] of [["ctrl", { ctrlKey: true }], ["meta", { metaKey: true }],
                               ["alt", { altKey: true }], ["composing", { isComposing: true }],
                               ["other", { key: "a" }]]) {
    fire(el, "keydown", Object.assign({ key: "Enter" }, props));
    results[name] = api.serializeBlock(el) === base;
  }
  const outside = new El("div");
  outside.className = "tw-line-edit";
  docSurface.appendChild(outside);
  const e = fire(outside, "keydown", { key: "Enter" });
  results.notABlock = !e.defaulted;
  out.enterGuards = results;
}

// 13. Enter with no readable caret leaves Enter to the browser rather than eating the key.
{
  const el = mountBlock();
  api.setCaret(null);
  const e = fire(el, "keydown", { key: "Enter" });
  out.enterNoCaret = { defaultPrevented: !!e.defaulted, text: api.serializeBlock(el) };
  api.setCaret([0, 0]);
}

// 14. A break in the MIDDLE, and inside the token fill — the fill must survive as a fill, or
//     the next render would freeze a live estimate value into hand-typed text.
{
  const el = mountBlock();
  const text = api.serializeBlock(el);
  const at = text.indexOf("coat.");
  api.setCaret([at, at]);
  fire(el, "keydown", { key: "Enter" });
  out.midBreak = {
    text: api.serializeBlock(el),
    fills: el.querySelectorAll(".tw-fill").map((s) => s.attrs["data-token"]),
    runs: api.serializeRuns(el),
  };
}

// 15. WHY the handler intercepts Enter at all: the shape a browser's own Enter leaves behind
//     in a contenteditable — a wrapper div carrying a placeholder <br> — reads as TWO
//     newlines to the serialiser, so one keypress would have become a blank line.
{
  const el = mountBlock();
  const before = api.serializeBlock(el);
  // Appended as NODES rather than through innerHTML: the shape is the point, and a round trip
  // through the shim's innerHTML getter would be measuring the shim.
  const wrapper = new El("div");
  wrapper.appendChild(new El("br"));
  el.appendChild(wrapper);
  out.browserDefaultShape = { before: before, after: api.serializeBlock(el) };
}

// 16. The (a) answer, exercised: the label is ordinary editable text, so retyping it in place
//     keeps its bold, and emptying it leaves neither a stray token nor a lone colon.
{
  const el = mountBlock();
  // Typing inside the bold span is what the browser does — it edits that text node, it does
  // not restyle it. So the model is: change the node's value, then read the runs back.
  const labelNode = el.querySelectorAll("span").map((s) => s.childNodes[0])
    .find((n) => n && n.nodeType === Node.TEXT_NODE && n.nodeValue.indexOf("Scope") === 0);
  labelNode.nodeValue = "Scope of work:";
  out.labelRetyped = { text: api.serializeBlock(el), runs: api.serializeRuns(el) };
  labelNode.nodeValue = "";
  out.labelEmptied = { text: api.serializeBlock(el), runs: api.serializeRuns(el) };
}

console.log(JSON.stringify(out));
