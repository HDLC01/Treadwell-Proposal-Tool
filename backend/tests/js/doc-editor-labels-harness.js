"use strict";
/* The last locked labels on the proposal page, a text box that grows instead of clipping, and
 * the paragraph controls (part 3) — the bullet toggle and the two indent steps.
 * RUN, not read.
 *
 * Kyle, 2026-08-19, on the proposal document editor:
 *   "Some of the labels are not editable why not make it like a word document??"
 *   "Everything on that page must be editable like a word doc"
 *   "instead of it being a textbox why not make it editable like a word document?"
 * and 2026-08-20:
 *   "I cant dletet the bullet points"
 *   "There is indentation in this but I cant remove tat if I want to to be aligned on the
 *    polished concrete?"
 *
 * Part 3's own reason for running rather than reading: whether the bullet button reads ON,
 * whether a numbered contract clause is offered anything at all, and whether the state survives
 * a reload are properties of several functions agreeing — the block record from the endpoint,
 * paraNow/paraPatch, the toolbar's render, the collector and the restorer. No line of source
 * says any of that.
 *
 * Two behaviours from the earlier pass, neither visible to a source assertion:
 *
 *   * THE LABELS. renderSystemPreview builds the WORK rows as a string of HTML, and whether a
 *     label came out as an editable island or as escaped dead text is a property of the string it
 *     produced — plus what the delegated `input` handler then writes into state.system_overrides,
 *     plus what a RE-RENDER shows afterwards. "Option 2:" surviving on the rows the estimator did
 *     not rename is three functions agreeing, not one line of source.
 *   * THE GROWTH. Whether a box may get taller is arithmetic against the OTHER boxes' rects on a
 *     612x792 sheet. Kyle's shapes already overlap each other (Direct epoxy's WORK ends at
 *     323.65pt and PRICE starts at 320.95pt), so the obvious "is it below my bottom edge" test
 *     silently classifies the one box you must not grow into as "not below me". Only running it
 *     with the real geometry catches that.
 *
 * The precedent for running it is expensive: on 2026-08-12 `STAGE_CREATED` shipped unbound with
 * every source-text assertion green and took the production board down.
 *
 * DELIBERATELY NOT A FULL DOM, for the reason box-drag-harness.js gives: jsdom lets a missing
 * binding hide behind a stub. What is shimmed is what these functions touch — elements AND text
 * nodes (serializeBlock walks childNodes by nodeType), a small real innerHTML parser (the preview
 * nests islands inside <strong> and <p>), and an offsetHeight that follows the font-size fitTxbx
 * sets and is floored by minHeight, so "this box overflows" is a measurement rather than a stub
 * returning whatever the test wants.
 *
 * Usage: node doc-editor-labels-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
// Normalized to LF: the repo's frontend is checked out CRLF on Windows and every pattern below
// anchors on "\n  " indentation. A CR left in would make the lifted source subtly different from
// the shipped source, which is the one thing this harness must not allow.
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");
// The run algebra, the real module the page loads — collectOverrides reads runs off the DOM and
// the format bar's own state summary comes out of it.
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

/** A top-level `const` whose VALUE contains a semicolon — a prose string, in practice.
 *  topConst() scans for the first `;` at bracket depth 0 and has no idea it is inside a string
 *  literal, so "…the computed estimate; the estimate sheet…" cut the statement in half and
 *  produced an unterminated string. This reads whole LINES until one ends the statement, which is
 *  how these constants are actually written. */
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

/** One delegated listener body out of the page's top level, by the comment that introduces it.
 *  Lifted so an edit to a label island goes through the REAL handler — its revert rule ("empty
 *  or back to computed means delete the override") is the whole reason an emptied label cannot
 *  leave a bare token or a lone colon in a customer's document. */
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

/** The box loop out of renderPositioned — the code that actually mounts a box, so this cannot
 *  quietly test a hand-built element that has drifted from the shipped one. */
function renderBoxLoop() {
  const start = SRC.indexOf("    boxDesign.clear();\n    for (const box of (geo.boxes || [])) {");
  if (start < 0) throw new Error("renderPositioned's box loop moved — rewrite this harness");
  const open = SRC.indexOf("{", SRC.indexOf("for (const box of", start));
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(start, j + 1);
  }
  throw new Error("unbalanced braces reading the box loop");
}

// ── the smallest DOM these functions touch ───────────────────────────────────
const PX_PER_PT = 96 / 72;
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
  remove() {
    const p = this.parentNode;
    if (!p) return;
    p.childNodes = p.childNodes.filter((n) => n !== this);
    this.parentNode = null;
  }
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
  set textContent(v) {
    this.childNodes = [];
    if (String(v) !== "") this.appendChild(new Text(v));
  }
  /** A real (if small) parser: renderSystemPreview nests a `.tw-fill` island inside a <strong>
   *  inside a <p>, so a flat one would lose exactly the nesting under test. */
  set innerHTML(html) {
    this.childNodes = [];
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
  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  // The format bar builds itself with setAttribute (role/aria-label) and keeps aria-pressed in
  // step with the buttons' pressed state, so these are part of the surface under test.
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; }
  normalize() {}
  setPointerCapture() {}
  releasePointerCapture() {}
  blur() { if (document.activeElement === this) document.activeElement = null; }
  focus() { document.activeElement = this; }
  getBoundingClientRect() { return { width: 0, height: 0, left: 0, top: 0 }; }
  get offsetWidth() { return this._offsetWidth || 0; }
  set offsetWidth(v) { this._offsetWidth = v; }
  /** Content height in CSS px: scaled by whatever font-size fitTxbx set, floored by minHeight
   *  (a box shorter than its own shape still occupies the shape). This is the one measurement
   *  the whole growth decision rests on, so it is modelled rather than stubbed. */
  get offsetHeight() {
    const pct = /^(\d+)%$/.exec(this.style.fontSize || "");
    const k = pct ? Number(pct[1]) / 100 : 1;
    const floorPt = parseFloat(this.style.minHeight || "0") || 0;
    return Math.max(Math.round(this._naturalPx * k), Math.round(floorPt * PX_PER_PT));
  }
}

// The page root, so `document.querySelectorAll(".tw-txbx")` (fitNotesBox) really finds the boxes.
const ROOT = new El("div");
// #fmt-ribbon: the row of page chrome the formatting ribbon mounts itself into since 2026-08-24
// ("keep it static like a ribbon in a word document"). Modelled rather than shimmed away, because
// ensureFmtBar falls back to document.body when it is missing — a harness that let it take the
// fallback would be testing the degraded path and calling it the shipped one.
const FMT_HOST = new El("div");
FMT_HOST.attrs.id = "fmt-ribbon";
const document = {
  createElement: (t) => new El(t),
  activeElement: null,
  body: new El("body"),
  getElementById: (id) => (id === "fmt-ribbon" ? FMT_HOST : null),
  querySelectorAll: (sel) => ROOT.querySelectorAll(sel),
};
const window = {
  _listeners: {},
  addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
  innerWidth: 1440,
  innerHeight: 900,
};

function fire(node, type, props) {
  let stopped = false;
  const e = Object.assign({
    target: node,
    pointerId: 1,
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

function fireWindow(type, props) {
  const e = Object.assign({
    target: (props && props.target) || null,
    pointerId: 1,
    preventDefault() { this.defaulted = true; },
    stopPropagation() {},
  }, props);
  for (const f of (window._listeners[type] || []).slice()) f(e);
  return e;
}

// ── the page's own collaborators, as the page binds them ─────────────────────
const docSurface = new El("div");
ROOT.appendChild(docSurface);
const systemPreviewEl = new El("div");
ROOT.appendChild(systemPreviewEl);
const form = new El("form");
const boxDesign = new Map();
const persisted = { calls: 0 };

// THE PAGE'S OWN BINDING, not a friendlier one: proposal-review.js line 2 is
// `const state = TW.getState()`, a one-shot snapshot, and TW.setState re-reads storage into a NEW
// object. Everything the code under test does works only because it mutates NESTED objects in
// place (state.system_overrides) — a harness with a reassignable `state` would be kinder than the
// page and would hide exactly that class of bug (see box-drag-harness.js for what it cost).
const SEED = {
  work_type: "epoxy",
  audience: "Direct",
  base_tab_id: "t1",
  cell_values: {},
  system_overrides: [],
  texture: "Light Broadcast",
};
const STORE = { blob: JSON.parse(JSON.stringify(SEED)) };
const TWStub = {
  getState: () => JSON.parse(JSON.stringify(STORE.blob)),
  setState: (partial) => {
    STORE.blob = Object.assign(JSON.parse(JSON.stringify(STORE.blob)), partial || {});
    return STORE.blob;
  },
  readForm: () => ({ texture: "Light Broadcast", cove_height: "6" }),
};

let API = null;

const dirtied = [];        // every markEdited() the lifted format code performs
const repaginated = [];    // every scheduleRepaginate() a paragraph change asks for

// Exactly what schedulePersistOverrides does AROUND the shipped collectors, so the store this
// harness reads back is written by the real collectBoxOverrides / collectOverrides /
// mergeOverrideEntry. The paragraph half matters for the round trip: a bullet the toolbar
// forgets after a reload is worse than no toolbar, and the only way to prove it does not is to
// persist through the real collector and restore through the real restorer.
function schedulePersistOverrides() {
  persisted.calls += 1;
  const items = API.collectOverrides();
  const ver = API.templateVersion();
  TWStub.setState({
    box_overrides: API.collectBoxOverrides(),
    paragraph_overrides_all: API.mergeOverrideEntry(
      TWStub.getState().paragraph_overrides_all, "epoxy", "Direct", ver, items),
    paragraph_overrides: items,
    paragraph_overrides_meta: { template_version: ver, work_type: "epoxy", audience: "Direct" },
  });
}

const LIFTED = [
  // focusInside asks TWO questions now, and the second one is the caret's own line. It has to:
  // the box is the editing host, so document.activeElement is an ANCESTOR of the paragraph being
  // typed in and `el.contains(activeElement)` is false exactly when the guard matters. These
  // three are what the second question is made of -- leaving them out is a ReferenceError the
  // first time renderSystemPreview asks whether it may repaint.
  topConst("LINE_SEL"), fn("lineAt"), fn("lineAtSelection"),
  topConst("focusInside"), topConst("escHtml"), stringConst("_OVERRIDE_TITLE"),
  topConst("_SYS_ROW_LINE_FIELDS"), stringConst("_SYS_LINE_TITLE"),
  // workLabelHtml is called from inside renderSystemPreview, so leaving it out does not fail
  // at lift time - it fails as `ReferenceError: workLabelHtml is not defined` the first time a
  // WORK row renders, which is every test in part 1. Any function renderSystemPreview reaches
  // has to be here (see the fitOffer note below for what that already cost once).
  // sysRowStyle / sysRowTemplate / sysRowSizePt put the synthesized {{#system}} rows where their
  // TEMPLATE paragraphs go, instead of the hand-written inline margins that produced a sub-group
  // the document does not have. Lifted, not stubbed: this harness owns those rows, and a stub
  // returning "" would test the old geometry while calling it the new one.
  fn("sysRowTemplate"), fn("sysRowStyle"), fn("sysRowSizePt"),
  fn("workLabelHtml"),
  fn("effectiveWorkType"), fn("sheetSystems"), fn("renderSystemPreview"), fn("serializeBlock"),
  topConst("PT_PER_CSS_PX"), topConst("BOX_DRAG_SLOP_PT"), topConst("BOX_EPS_PT"),
  topConst("isAutoGrown"),
  fn("zoomScale"), fn("ptFromClientPx"), fn("clampPt"), fn("dragBoxRect"),
  fn("boxOverrideEntry"), fn("boxReadout"), fn("effectiveBoxRect"), fn("applyBoxGeom"),
  fn("addBoxTools"), fn("showBoxReadout"), fn("setBoxOverride"),
  // boxCeilingPt answers "is there a real box under this one?", and growRoomPt returns 0 when
  // the answer is no — that null is what stops a box growing over the baked letterhead art.
  fn("boxCeilingPt"),
  fn("dropAutoGrownHeight"), fn("releaseAutoGrownHeight"), fn("growRoomPt"), fn("otherBoxRects"), fn("growBoxToFit"),
  fn("wireBoxDrag"), fn("collectBoxOverrides"),
  // fitOffer is called from inside fitTxbx, so leaving it out does not fail at lift time —
  // it fails as `ReferenceError: fitOffer is not defined` the first time a box overflows,
  // which took out all 86 tests in this module. Any function fitTxbx reaches has to be here.
  fn("fitOffer"),
  fn("fitTxbx"), fn("fitNotesBox"), fn("wireOverflowExpand"),
  // ── the paragraph controls (bullet / indent) and everything they touch ──
  // The toolbar's own click handler reaches toggleFormat and applyFormat on the B/I/U buttons,
  // and showFmtBar reads selectionFormat, so those are lifted too rather than stubbed: a stub
  // here is exactly how `fitOffer` hid until the first overflowing box (see the note above).
  topConst("DOC_TOKEN_RE"), topConst("sameFmt"), topConst("SIZE_CHOICES"),
  topConst("INDENT_STEP_TW"), topConst("INDENT_MAX_TW"), topConst("TWIPS_PER_PT"),
  fn("fillHtml"), fn("runStyleCss"), fn("blockHtml"), fn("fmtAt"), fn("segmentsOf"),
  fn("mergeSegs"), fn("serializeRuns"), fn("editRuns"), fn("runEditCss"), fn("renderRuns"),
  fn("runsArePlain"), fn("selectionFormat"), fn("applyFormat"), fn("toggleFormat"),
  fn("paraBase"), fn("paraNow"), fn("paraPatch"), fn("sanitizeParaPatch"),
  // applyParaGeom is where the paragraph's real geometry now lands -- left/hanging/first-line
  // and the file's own line spacing. Lifted rather than stubbed: applyParaToEl delegates to it,
  // so a stub would leave the indent arithmetic (bullet at left-hanging) untested.
  fn("applyParaGeom"),
  fn("applyParaToEl"), fn("setParaState"), fn("paraAction"),
  // fmtTargetBlock / markFmtTarget / renderFmtBar are what showFmtBar became when the bar
  // stopped floating: it no longer positions anything, it re-checks its REMEMBERED block against
  // the live document and re-renders. Leaving any of them out is not a lift-time failure — it is
  // a ReferenceError on the first focusin, i.e. in every test below (see the fitOffer note).
  //
  // fmtRangeFor / fmtRangeSource joined them for the same reason and cost the same 30 tests when
  // they were first left out. renderFmtBar reads the remembered range THROUGH fmtRangeFor now,
  // because a range is character offsets and offsets mean nothing once the paragraph underneath
  // has been re-filled — which, since the ribbon holds its target past blur, is something
  // refreshDocumentFills does to it routinely.
  fn("fmtTargetBlock"), fn("markFmtTarget"), fn("renderFmtBar"),
  fn("fmtRangeSource"), fn("selectionLeftBlock"), fn("fmtRangeFor"),
  // applyFormat gained two guards in review: runsEqual (a press that changes nothing must not mark
  // the paragraph edited and ship an override) and selectionInSurface (do not re-place the document
  // selection when the caret is in a sidebar field). Both must be lifted, not stubbed -- a stub
  // that always said "changed" would put the spurious-override bug straight back.
  fn("runsEqual"), fn("selectionInSurface"),
  fn("ensureFmtBar"), fn("showFmtBar"), fn("idleFmtBar"),
  topConst("overrideKey"), fn("mergeOverrideEntry"), topConst("liveKey"),
  fn("savedOverridesFor"), fn("restoreSavedOverrides"), fn("collectOverrides"),
  // BOTH of those reach isNumberedClause: neither will ship or replay an override that empties a
  // numbered TERMS clause. Left out, it is not a lift-time failure — it is a ReferenceError in
  // the middle of a persist, which is the failure mode the note above fitOffer describes.
  fn("isNumberedClause"), fn("blanksANumberedClause"),
  // collectOverrides calls both of these. Leaving either out does not fail at lift time — it
  // throws `ReferenceError` on the first formatted paragraph, i.e. in the middle of a persist,
  // which is the failure mode the note above fitOffer describes.
  fn("storedRuns"), fn("preserveRichOverrides"),
  // The {{#system}} row channel is a whole-container SWEEP now, not a single-row write: the box is
  // one editing host, so a Delete across three rows arrives as one input event and a handler that
  // only read the caret's row would leave the other two edited on screen and unedited in the
  // draft. syncSystemRow is the per-row half the sweep and the per-row listener share.
  fn("syncSystemRows"), fn("queueSysOvSave"), fn("syncSystemRow"),
].join("\n\n");

const BOX_LOOP = renderBoxLoop();
const SYS_INPUT = delegated("  // ── Editable estimate-sourced fills: WORK systems ──");

const api = new Function(
  "document", "window", "docSurface", "systemPreviewEl", "form", "boxDesign", "Node",
  "schedulePersistOverrides", "TW", "F", "dirtied", "repaginated",
  `const state = TW.getState();
  let boxOverrides = new Map(); let boxLimits = null; let docZoom = null;
  let templateBlocks = [{ id: 1, txbx: 0 }];
  // Debounces are collapsed to "run now": what is under test is what gets WRITTEN, and a real
  // timer would make every assertion below a race.
  const setTimeout = (f) => { f(); return 1; };
  const clearTimeout = () => {};
  let _sysOvTimer = null;
  const renderNotesPreview = () => {};
  const RUN_KEYS = F.RUN_KEYS;
  const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;
  const TOKEN_HINTS = {};
  let _fmtBusy = false;
  let flowMode = false;
  let fmtBar = null, fmtBlock = null, fmtRange = null, fmtRangeText = null;   // the page's own bindings, verbatim
  let templateVersion = "tv-1";
  const blockById = new Map();      // id -> the template's block record
  const pristineById = new Map();   // id -> the block's pristine plain text
  const paraById = new Map();       // the page's own store, see proposal-review.js
  const scheduleRepaginate = () => { repaginated.push(1); };
  // NOT lifted, for the reason doc-editor-harness.js gives: selectionRange and placeSelection
  // are Range arithmetic against a live selection, the one thing a shim cannot model honestly.
  // Returning null is what a real collapsed-caret-less block gives selectionFormat, which then
  // treats the whole paragraph as the range — and a paragraph property applies to the whole
  // paragraph anyway, so nothing under test here depends on the caret.
  const selectionRange = () => null;
  const placeSelection = () => {};
  const markEdited = (el, formatted) => { dirtied.push([el.dataset.id, !!formatted]); };
` + LIFTED + `
  systemPreviewEl.addEventListener("input", (e) => ${SYS_INPUT});
  wireBoxDrag();
  wireOverflowExpand();
  function mountBoxes(geo, byBox, p1, tokens) {
    const renderBlockList = () => {};
${BOX_LOOP}
  }
  return { mountBoxes, renderSystemPreview, fitTxbx, fitNotesBox, growBoxToFit, growRoomPt,
           effectiveBoxRect, collectBoxOverrides, dragBoxRect,
           setLimits: (l) => { boxLimits = l; },
           clearOverrides: () => { boxOverrides = new Map(); },
           readOverrides: () => Array.from(boxOverrides.entries()),
           isAutoGrown: isAutoGrown,
           liveState: () => state,
           // ── the paragraph controls ──
           showFmtBar, idleFmtBar, paraAction, paraNow, paraPatch, collectOverrides,
           restoreSavedOverrides, mergeOverrideEntry,
           fmtBarEl: () => ensureFmtBar(),
           templateVersion: () => templateVersion,
           /** Mount blocks the way renderBlock does — class from the record, no inline para
            *  styling — so an untouched paragraph starts out exactly as it does today. */
           mountBlocks: (records) => {
             docSurface.childNodes = [];
             blockById.clear(); pristineById.clear(); paraById.clear();
             templateBlocks = records;
             const els = new Map();
             for (const b of records) {
               blockById.set(b.id, b);
               const el = document.createElement("div");
               el.className = "tw-block";
               el.dataset.id = String(b.id);
               el.attrs.contenteditable = "true";
               if (b.list) el.classList.add("tw-li");
               el.textContent = b.text || "";
               pristineById.set(b.id, b.text || "");
               docSurface.appendChild(el);
               els.set(b.id, el);
             }
             return els;
           },
           forgetParaState: () => { paraById.clear(); },
           paraStore: () => Array.from(paraById.entries()) };
  `
)(document, window, docSurface, systemPreviewEl, form, boxDesign, Node,
  schedulePersistOverrides, TWStub, F, dirtied, repaginated);
API = api;

const out = {};

// ═══ part 1 — the WORK rows, edited as WHOLE LINES ═══════════════════
// The picks come from the BASE tab's sheet cells, which is the live path (sheetSystems). Two
// systems is the most that path can resolve — it reads two fixed cell pairs — so the 3-system
// numbering rule is asserted on the Python side, in the code that actually writes the document.
//
// WHAT CHANGED, and why these cases were rewritten rather than deleted. Until 2026-08-24 each
// row was a string of escaped template words with two contenteditable islands dropped into it,
// so the words themselves — "~", " SF of epoxy flooring", the whole cove clause — had no
// element to put a caret in. Kyle asked three times for one editable line per row. The
// assertions below therefore stop counting islands and start proving that the whole line takes
// a caret, that every word in it can be replaced or deleted, that an untouched line still
// follows the estimate, and that an edited one stops.
function seedSystems(names) {
  const sf = { epoxy_sf: 5000, cove_lf: 240, epoxy_sf_2: 1800, cove_lf_2: 0 };
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const st = api.liveState();
  st.system_overrides = [];
  st.priced_tabs = [{ id: "t1", role: "epoxy", kind: "base", sf: sf, sys_names: names }];
  st.base_tab_id = "t1";
  TWStub.setState({ priced_tabs: st.priced_tabs, system_overrides: st.system_overrides });
  api.renderSystemPreview();
}

/** Every WORK row in the preview, in document order — and, for each, whether the WHOLE row is
 *  the editable element. `islands` counts anything editable strictly INSIDE the row: it has to
 *  be zero, because a nested editable span is the model Kyle rejected three times. */
function rows() {
  return systemPreviewEl.querySelectorAll("[data-sys-line]").map((p) => ({
    i: Number(p.dataset.sysIndex),
    field: p.dataset.sysLine,
    text: p.textContent,
    computed: p.dataset.computed,
    editable: p.attrs.contenteditable === "true",
    wholeLine: p.classList.contains("tw-line-edit"),
    islands: p.querySelectorAll("[contenteditable]").length,
    bold: p.querySelectorAll("strong").map((b) => b.textContent),
    warned: p.classList.contains("tw-overridden"),
    title: p.title || null,
    // THE GEOMETRY, as the row is actually rendered. These three rows are DISPLAY stand-ins for
    // real template paragraphs, and they used to be positioned by hand-written inline margins
    // with no relationship to those paragraphs -- which is where the phantom "sub group" came
    // from: `margin:0 0 1pt` zeroes margin-left, silently overriding .tw-li's own indent, so the
    // synthesized rows sat further left AND (carrying no font-size) rendered a size larger than
    // every real block beside them.
    style: p.attrs.style || "",
  }));
}

/** The preview as the estimator reads it: one string per rendered paragraph. */
const lines = () => systemPreviewEl.children.map((p) => p.textContent);

/** Rewrite one whole row through the page's own delegated `input` handler — which is what a
 *  person does when they select the line and type over it. */
function typeLine(i, field, text) {
  const p = systemPreviewEl.querySelectorAll("[data-sys-line]")
    .find((el) => Number(el.dataset.sysIndex) === i && el.dataset.sysLine === field);
  if (!p) throw new Error("no editable row for " + i + "/" + field);
  p.textContent = text;
  fire(p, "input", {});
  return p;
}

// The epoxy WORK box's three {{#system}} paragraphs, as the TEMPLATE states them. Every number
// here is the file's own, and test_doc_editor_labels asserts these same numbers against the .docx
// itself -- so the fixture cannot drift away from what Kyle's template says while still passing.
//
// This is what the synthesized preview rows are stand-ins FOR. Without the template records
// mounted, sysRowStyle has nothing to look up and falls back to a bare margin, which is exactly
// the state that let the hand-written inline margins go unnoticed.
const SYS_TEMPLATE = [
  { id: 301, text: "{{system.prefix}}   {{system.name}}", list: true, txbx: 0,
    para: { bullet: true, indent: 288, hanging: 288, first_line: null, locked: false, marker: "",
            spacing: { before: null, after: null, line: 276, line_rule: "auto",
                       contextual: false } },
    runs: [{ text: "System:", bold: true, size_pt: 8 }] },
  { id: 302, text: "Texture:  {{system.texture}}", list: false, txbx: 0,
    para: { bullet: false, indent: 1008, hanging: null, first_line: 72, locked: false, marker: "",
            spacing: { before: null, after: null, line: 276, line_rule: "auto",
                       contextual: false } },
    runs: [{ text: "Texture:", bold: false, size_pt: 8 }] },
  { id: 303, text: "Area: ~{{system.sqft}} SF of epoxy flooring", list: true, txbx: 0,
    para: { bullet: true, indent: 288, hanging: 288, first_line: null, locked: false, marker: "",
            spacing: { before: null, after: null, line: 300, line_rule: "auto",
                       contextual: false } },
    runs: [{ text: "Area:", bold: true, size_pt: 8 }] },
];

// 0. THE GEOMETRY. Mount the template paragraphs first, then render the preview, and record where
// each synthesized row actually landed.
api.mountBlocks(SYS_TEMPLATE);
seedSystems(["Broadcast Quartz"]);
out.workGeometry = { rows: rows() };

// 1. One system: three rows, each ONE editable line, with nothing editable nested inside.
seedSystems(["Broadcast Quartz"]);
out.oneSystem = { rows: rows(), lines: lines() };

// 2. Two systems: the rows number themselves.
seedSystems(["Broadcast Quartz", "Decorative Flake"]);
out.twoSystems = { rows: rows(), lines: lines() };

// 3. Rewrite row 1's SYSTEM line, label and all. Row 2 must keep ITS number — the rule is per
//    row, and a row nobody touched must not be rewritten in a document a customer receives.
typeLine(0, "name_line", "Base System:   Broadcast Quartz");
out.renamedRow1 = {
  stored: JSON.parse(JSON.stringify(api.liveState().system_overrides)),
  persisted: JSON.parse(JSON.stringify(TWStub.getState().system_overrides)),
};
api.renderSystemPreview();
out.renamedRow1.lines = lines();
out.renamedRow1.rows = rows();

// 4. Empty it again. The revert rule has to give the computed line back — not a bare token, not
//    a lone colon, which is what a customer would otherwise read.
typeLine(0, "name_line", "");
api.renderSystemPreview();
out.emptiedLine = {
  stored: JSON.parse(JSON.stringify(api.liveState().system_overrides)),
  lines: lines(),
};

// 5. THE COMPLAINT, executed. Delete the static words " SF of epoxy flooring" and the cove
//    clause out of the Area line — the exact text that had no element to put a caret in — and
//    reword the Texture row's label in the same pass.
seedSystems(["Broadcast Quartz", "Decorative Flake"]);
typeLine(0, "texture_line", "Surface texture:  Light Broadcast");
typeLine(0, "area_line", "Coverage: 5,000");
api.renderSystemPreview();
out.staticWordsDeleted = {
  stored: JSON.parse(JSON.stringify(api.liveState().system_overrides)),
  lines: lines(),
  rows: rows(),
};

// 6. A line whose NUMBERS moved off the estimate is a pricing-review risk and says so; a line
//    that was only reworded is not, and says that instead. One visual state either way.
seedSystems(["Broadcast Quartz"]);
typeLine(0, "name_line", "Base System:   Broadcast Quartz");
typeLine(0, "area_line", "Area: ~9,999 SF of epoxy flooring and 240 LF of 6\" epoxy cove base");
api.renderSystemPreview();
out.warnings = rows().map((p) => ({ field: p.field, warned: p.warned, title: p.title }));

// 7. UNTOUCHED TRACKS, TOUCHED FREEZES. Edit row 1's Area line, then move the estimate's square
//    footage underneath it. The edited line keeps the estimator's words; row 2's untouched line
//    picks the new figure up. This is the whole of constraint 2, and no source assertion can
//    reach it — it is renderSystemPreview, the input handler and the store agreeing.
seedSystems(["Broadcast Quartz", "Decorative Flake"]);
typeLine(0, "area_line", "Coverage: 5,000 SF, cove included");
{
  const st = api.liveState();
  st.priced_tabs = [{ id: "t1", role: "epoxy", kind: "base",
                      sf: { epoxy_sf: 7777, cove_lf: 240, epoxy_sf_2: 2222, cove_lf_2: 0 },
                      sys_names: ["Broadcast Quartz", "Decorative Flake"] }];
  TWStub.setState({ priced_tabs: st.priced_tabs });
}
api.renderSystemPreview();
out.estimateMoved = { lines: lines(), rows: rows() };

// 9. Delete the colon and the label rule has nothing to find. The page then has to show the
//    row's TEMPLATE weight, which is bold for System and Area and normal for Texture — that is
//    what proposal_writer writes into the row's first run. Asserted here and against the real
//    .docx in test_a_line_with_no_colon_keeps_the_row_weight_the_page_shows.
seedSystems(["Broadcast Quartz"]);
typeLine(0, "name_line", "Base build no colon");
typeLine(0, "texture_line", "Finish matte no colon");
typeLine(0, "area_line", "Coverage 5000 sq ft");
api.renderSystemPreview();
out.noColon = rows().map((p) => ({ field: p.field, text: p.text, bold: p.bold }));

// 8. Spaces reach the store untouched. The estimator now types at both ends of a whole line, so
//    a trim anywhere on this channel is a 1:1 violation on the line he is most likely to space
//    out. main._sanitize_system_overrides is asserted on the Python side.
seedSystems(["Broadcast Quartz"]);
typeLine(0, "area_line", "  Area:  ~5,000 SF  ");
out.spacesKept = JSON.parse(JSON.stringify(api.liveState().system_overrides));

// ═══ part 2 — a box that grows instead of clipping ═══════════════════════════
// Kyle's Direct epoxy template, every box, read out of the .docx with template_geometry — not
// invented, because the whole question is whether the page has room and the answer depends on
// where the OTHER boxes are. test_doc_editor_labels.py restates the room arithmetic
// independently, so a harness that got it wrong cannot agree with itself.
const DIRECT_EPOXY = [
  { id: 0, x_pt: 125.20, y_pt: 36.00, w_pt: 324.80, h_pt: 99.00 },   // JOB NAME header
  { id: 1, x_pt: 18.35, y_pt: 36.00, w_pt: 72.00, h_pt: 18.00 },     // DATE
  { id: 2, x_pt: 162.35, y_pt: 152.65, w_pt: 423.00, h_pt: 171.00 }, // WORK
  { id: 3, x_pt: 162.30, y_pt: 494.60, w_pt: 422.65, h_pt: 162.00 }, // NOTES (last on the page)
  { id: 4, x_pt: 162.30, y_pt: 320.95, w_pt: 422.65, h_pt: 164.50 }, // PRICE
  { id: 5, x_pt: 23.31, y_pt: 501.95, w_pt: 90.00, h_pt: 90.00 },    // logo, beside NOTES
];
const LIM = { pageW: 612, pageH: 792, maxW: 432, maxH: 648, minPt: 12, printBottom: 720 };
api.setLimits(LIM);

/** Mount the whole page, then give each box `naturalPt` of content. Boxes not named in
 *  `contentByBox` get 10pt — comfortably inside the shortest box on the sheet (the 18pt DATE
 *  field), so the only box that overflows in a scenario is the one that scenario is about. */
function mountPage(contentByBox) {
  api.clearOverrides();
  docSurface.childNodes = [];
  const p1 = new El("div");
  docSurface.appendChild(p1);
  const byBox = new Map(DIRECT_EPOXY.map((b) => [b.id, [{ id: b.id }]]));
  api.mountBoxes({ boxes: DIRECT_EPOXY }, byBox, p1, {});
  const boxes = new Map();
  for (const el of p1.children) {
    const id = Number(el.dataset.boxId);
    boxes.set(id, el);
    el._naturalPx = Math.round((contentByBox[id] || 10) * PX_PER_PT);
  }
  return boxes;
}

const geomOf = (el) => ({
  left: el.style.left, top: el.style.top, width: el.style.width,
  minHeight: el.style.minHeight, boxHPt: el.dataset.boxHPt,
  moved: el.classList.contains("tw-box-moved"),
  grown: el.classList.contains("tw-box-grown"),
  blocked: el.classList.contains("tw-grow-blocked"),
  overflow: el.classList.contains("tw-notes-overflow"),
  fontSize: el.style.fontSize || "",
  title: el.title || "",
});

// 7. The room each box actually has, straight out of the shipped growRoomPt.
{
  const boxes = mountPage({});
  out.room = {};
  for (const b of DIRECT_EPOXY) {
    out.room[b.id] = Number(api.growRoomPt(
      { x: b.x_pt, y: b.y_pt, w: b.w_pt, h: b.h_pt },
      DIRECT_EPOXY.filter((o) => o.id !== b.id)
        .map((o) => ({ x: o.x_pt, y: o.y_pt, w: o.w_pt, h: o.h_pt })),
      LIM).toFixed(2));
  }
  out.roomBoxCount = boxes.size;
}

// 8. A box that FITS is not touched. Byte-identical geometry and an empty payload: the generated
//    .docx has to be the same file it was before this feature existed.
{
  const boxes = mountPage({ 3: 100 });
  const before = geomOf(boxes.get(3));
  api.fitNotesBox();
  out.fitsUntouched = { before: before, after: geomOf(boxes.get(3)),
                        payload: api.collectBoxOverrides(), persisted: persisted.calls };
}

/** Press "Fit to text" on one box, the way the estimator does.
 *
 *  GROWTH IS A GESTURE, NOT A SIDE EFFECT (2026-08-20). It used to happen inside fitNotesBox, so
 *  a box changed the geometry of the generated .docx on first paint and on every keystroke, off
 *  a browser measurement the comment above fitTxbx documents as overstating overflow. These
 *  scenarios therefore lay the page out, then CLICK, which is the only path that may resize now.
 *  Calling api.growBoxToFit directly would skip the handler and prove less. */
function pressFit(box) {
  const btn = box.querySelector("[data-box-fit]");
  if (!btn) throw new Error("no Fit to text button on this box — is fitOffer offering it?");
  fire(btn, "click", {});
}

// 9. A box with ROOM grows to fit, and the height reaches the payload the writer reads.
//    PRICE, not NOTES: PRICE has NOTES below it, so its room is bounded by a real box (173.65pt
//    from its top) and growing it is provably safe. NOTES is the last box on the page and its
//    room is bounded by nothing we can see — scenario 9b covers that case.
{
  const boxes = mountPage({ 4: 170 });
  const persistedBefore = persisted.calls;
  api.fitNotesBox();
  pressFit(boxes.get(4));
  out.grows = {
    geom: geomOf(boxes.get(4)),
    payload: api.collectBoxOverrides(),
    persistCalls: persisted.calls - persistedBefore,
    stored: TWStub.getState().box_overrides,
    autoGrown: api.isAutoGrown(boxes.get(4)),
  };
}

// 9b. THE ARTWORK CASE. NOTES is the last box on the page: 162pt of box at y=494.6, 225.4pt of
//     clear space to the bottom margin, and the ACCEPTANCE + signature frame printed across most
//     of it in the letterhead PNG. There is no element to measure, so the only honest answer is
//     that there is no room. Growing here used to move its bottom edge to 714.35pt — 57.75pt down
//     over that frame — and because a grown box disarms the server-side shrink, the customer got
//     the terms printed over the artwork. The button must not even be offered.
{
  const boxes = mountPage({ 3: 220 });
  api.fitNotesBox();
  const box = boxes.get(3);
  out.artBlocked = {
    geom: geomOf(box),
    offered: !!box.querySelector("[data-box-fit]") && box.classList.contains("tw-can-grow"),
    payload: api.collectBoxOverrides(),
  };
}

// 10. A box whose room a real box takes keeps the clip-and-warn — and says a DIFFERENT thing,
//     because "the next box starts here" and "we cannot see what is under you" are not the same
//     excuse. WORK is 171pt tall and PRICE starts 168.3pt below its top.
{
  const boxes = mountPage({ 2: 300 });
  api.fitNotesBox();
  out.blocked = { geom: geomOf(boxes.get(2)), payload: api.collectBoxOverrides() };
}

// 11. Trimming the text gives the space back: the height WE added is recomputed, not accumulated.
{
  const boxes = mountPage({ 4: 170 });
  api.fitNotesBox();
  pressFit(boxes.get(4));
  const grown = geomOf(boxes.get(4));
  boxes.get(4)._naturalPx = Math.round(100 * PX_PER_PT);
  api.fitNotesBox();
  out.trimGivesItBack = { grown: grown, after: geomOf(boxes.get(4)),
                          payload: api.collectBoxOverrides() };
}

// 12. A height the ESTIMATOR dragged is theirs. Pressing Fit to text must not undo a deliberate
//     resize, even when the text still does not fit — and the button should not be offered on a
//     box they have sized themselves, so pressFit is not used here.
{
  const boxes = mountPage({ 3: 220 });
  const box = boxes.get(3);
  const g = box.querySelector('[data-grip="s"]');
  fire(g, "pointerdown", { clientX: 0, clientY: 0 });
  fireWindow("pointermove", { clientX: 0, clientY: -40 * PX_PER_PT });  // drag it SHORTER
  fireWindow("pointerup", {});
  const dragged = geomOf(box);
  api.fitNotesBox();
  api.growBoxToFit(box);            // the gesture's own effect, forced past the missing button
  out.manualHeightWins = { dragged: dragged, after: geomOf(box),
                           offered: box.classList.contains("tw-can-grow"),
                           payload: api.collectBoxOverrides() };
}

// 13. "Reset box" means the template's geometry, and it has to STAY. A re-grow on the next
//     repaint would make the button look broken.
{
  const boxes = mountPage({ 4: 170 });
  api.fitNotesBox();
  pressFit(boxes.get(4));
  const grown = geomOf(boxes.get(4));
  fire(boxes.get(4).querySelector("[data-box-reset]"), "click", {});
  const reset = geomOf(boxes.get(4));
  api.fitNotesBox();
  out.resetSticks = { grown: grown, reset: reset, afterRefit: geomOf(boxes.get(4)),
                      payload: api.collectBoxOverrides() };
}

// 14. The tools layer carries the "Grown to fit" note, and adding it did not displace the grips.
//     On box 4, which is the one that can actually be grown (see scenario 9).
{
  const boxes = mountPage({ 4: 170 });
  api.fitNotesBox();
  pressFit(boxes.get(4));
  const tools = boxes.get(4).querySelector(".tw-box-tools");
  const note = tools.querySelector(".tw-box-grown-note");
  out.grownNote = {
    present: !!note,
    label: note ? note.textContent : null,
    title: note ? note.title : null,
    isNotAGrip: !!(note && note.attrs["data-grip"] === undefined),
    order: tools.children.map((c) => c.className),
  };
}

// ═══ part 3 — the bullet and the indent ══════════════════════════════════════
// Kyle, 2026-08-20: "I cant dletet the bullet points" / "There is indentation in this but I cant
// remove tat if I want to to be aligned on the polished concrete?"
//
// The records are the Direct epoxy template's own, read out of the .docx by /api/proposal-template
// (test_paragraph_controls.py re-derives them from the file, so a harness that invented them
// cannot agree with itself): four WORK rows on numId 4 (bullet, 288tw), one numbered TERMS clause
// on numId 5 (decimal, 540tw, locked), and one record with NO `para` at all — a browser replaying
// a pre-v5 cached response.
const BLOCK_RECORDS = [
  { id: 115, text: "Scope:  concrete prep",  list: true,  para: { bullet: true,  indent: 288, locked: false } },
  { id: 116, text: "Schedule:  4 days",      list: true,  para: { bullet: true,  indent: 288, locked: false } },
  { id: 117, text: "Exclusions:  none",      list: true,  para: { bullet: true,  indent: 288, locked: false } },
  { id: 52,  text: "Price and Payment...",   list: true,  para: { bullet: false, indent: 540, locked: true } },
  { id: 48,  text: "TREADWELL, LLC",         list: false, para: { bullet: false, indent: 270, locked: false } },
  { id: 999, text: "no para metadata",       list: true },
];

const barState = () => {
  const bar = api.fmtBarEl();
  const read = (sel) => {
    const n = bar.querySelector(sel);
    return n ? { display: n.style.display === undefined ? "" : n.style.display,
                 visibility: n.style.visibility === undefined ? "" : n.style.visibility,
                 on: n.classList.contains("on"), pressed: n.getAttribute("aria-pressed"),
                 disabled: !!n.disabled, label: n.attrs["aria-label"] || null,
                 title: n.title || null, text: n.textContent } : null;
  };
  return { bullet: read("button[data-para='bullet']"),
           outdent: read("button[data-para='outdent']"),
           indent: read("button[data-para='indent']"),
           sep: read("[data-para='sep']"),
           bold: read("button[data-fmt='bold']") };
};

const elState = (el) => ({ li: el.classList.contains("tw-li"),
                           marginLeft: el.style.marginLeft || "",
                           paddingLeft: el.style.paddingLeft === undefined ? "" : el.style.paddingLeft,
                           dirty: el.classList.contains("tw-dirty") });

// 15. The toolbar on an ordinary bulleted WORK row: all three controls offered, the bullet
//     button reading ON because the paragraph really is bulleted, and outdent live because the
//     row really is indented.
{
  const els = api.mountBlocks(BLOCK_RECORDS);
  api.showFmtBar(els.get(116));
  out.paraBarWork = barState();
  out.paraBarWorkNow = api.paraNow(116);
}

// 16. THE CONTRACT. A numbered TERMS AND CONDITIONS clause is offered NOTHING — not a disabled
//     button, which still invites the click, but no control at all. Removing one item from a
//     decimal list renumbers every clause after it, silently, in legal boilerplate.
{
  const els = api.mountBlocks(BLOCK_RECORDS);
  api.showFmtBar(els.get(52));
  out.paraBarLocked = barState();
  out.paraLockedAction = {
    bulletPressed: api.paraAction(els.get(52), "bullet"),
    outdentPressed: api.paraAction(els.get(52), "outdent"),
    el: elState(els.get(52)),
    patch: api.paraPatch(52),
  };
}

// 16b. A block with NO `para` metadata (a stale pre-v5 cached template response). We cannot tell
//      a WORK row from a contract clause, so nothing is offered — the schema bump exists so this
//      never happens, and this is what it degrades to if it ever does.
{
  const els = api.mountBlocks(BLOCK_RECORDS);
  api.showFmtBar(els.get(999));
  out.paraBarNoMeta = barState();
  out.paraNoMetaAction = api.paraAction(els.get(999), "bullet");
}

// 17. THE FIRST COMPLAINT. Switch the bullet off on ONE row: that row loses its square, its
//     neighbours keep theirs, and the payload carries `para` with NO text — the words were not
//     touched, and sending text would flatten the template's own bold lead-in.
{
  const els = api.mountBlocks(BLOCK_RECORDS);
  api.paraAction(els.get(116), "bullet");
  out.bulletOff = {
    target: elState(els.get(116)),
    before: elState(els.get(115)),
    after: elState(els.get(117)),
    now: api.paraNow(116),
    payload: api.collectOverrides(),
    repaginated: repaginated.length,
  };
}

// 18. THE SECOND COMPLAINT. Outdent reaches ZERO, so the row aligns with its neighbours, and
//     indent puts it back. Asserted as the twips that travel, not as pixels.
{
  const els = api.mountBlocks(BLOCK_RECORDS);
  const el = els.get(116);
  api.paraAction(el, "outdent");
  const zero = { now: api.paraNow(116), el: elState(el), payload: api.collectOverrides() };
  const again = api.paraAction(el, "outdent");   // already at the margin
  api.showFmtBar(el);
  const floored = { now: api.paraNow(116), pressed: again, bar: barState() };
  api.paraAction(el, "indent");
  out.indentSteps = { zero: zero, floored: floored,
                      back: { now: api.paraNow(116), el: elState(el),
                              payload: api.collectOverrides() } };
}

// 19. A row nobody touched ships NOTHING. The generated .docx has to be the file it was before
//     this feature existed, and `paraPatch` comparing against the template's own state is what
//     guarantees that.
{
  const els = api.mountBlocks(BLOCK_RECORDS);
  api.showFmtBar(els.get(115));
  api.showFmtBar(els.get(116));   // look at two of them, change neither
  out.untouched = { payload: api.collectOverrides(),
                    patches: [api.paraPatch(115), api.paraPatch(116), api.paraPatch(48)],
                    el: elState(els.get(116)) };
}

// 20. THE ROUND TRIP. Set it, persist through the real schedulePersistOverrides, forget the live
//     state the way a page reload does, re-mount, and restore. A control that forgets what you
//     set is worse than no control.
{
  const els = api.mountBlocks(BLOCK_RECORDS);
  api.paraAction(els.get(116), "bullet");
  api.paraAction(els.get(116), "outdent");
  const sent = api.collectOverrides();
  const stored = TWStub.getState().paragraph_overrides;
  // A reload: new elements, empty paraById, the saved blob is all there is.
  const els2 = api.mountBlocks(BLOCK_RECORDS);
  api.restoreSavedOverrides("epoxy", "Direct");
  api.showFmtBar(els2.get(116));
  out.roundTrip = { sent: sent, stored: stored, now: api.paraNow(116),
                    el: elState(els2.get(116)), bar: barState(),
                    resent: api.collectOverrides() };
}

// 21. AN OVERRIDE SAVED BEFORE THIS FEATURE EXISTED. {id, text} with no `para`: the text comes
//     back, the paragraph properties stay the template's, and nothing throws on the missing key.
{
  api.mountBlocks(BLOCK_RECORDS);
  TWStub.setState({
    paragraph_overrides_all: null,
    paragraph_overrides: [{ id: 116, text: "Schedule:  legacy text" }],
    paragraph_overrides_meta: { template_version: api.templateVersion(),
                                work_type: "epoxy", audience: "Direct" },
  });
  api.restoreSavedOverrides("epoxy", "Direct");
  const el = docSurface.querySelector('.tw-block[data-id="116"]');
  out.legacyOverride = { text: el.textContent, el: elState(el),
                         now: api.paraNow(116), patch: api.paraPatch(116) };
}

// 22. A TEXT edit and a bullet change on the SAME paragraph travel together, in one entry, with
//     the text present this time — because this time the estimator did type.
{
  const els = api.mountBlocks(BLOCK_RECORDS);
  const el = els.get(117);
  el.textContent = "Exclusions:  striping";
  api.paraAction(el, "bullet");
  out.textAndPara = { payload: api.collectOverrides() };
}

console.log(JSON.stringify(out));
