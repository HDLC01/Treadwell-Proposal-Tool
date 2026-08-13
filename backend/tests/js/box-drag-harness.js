"use strict";
/* DRAG and RESIZE a proposal text box, for real, at a zoom that is not 1.
 *
 * WHY THIS EXISTS. Hanz asked to be able to drag and resize the proposal's text boxes. The whole
 * feature is arithmetic between three coordinate systems — client px, CSS px, document points —
 * with a `transform: scale(k)` in the middle, and the zoom is fitted automatically to the canvas,
 * so k is almost never 1. A source-text assertion cannot tell you whether a 100px drag at 135%
 * zoom makes the box 55.6pt wider or 100pt wider; only running it can. That lesson is expensive
 * here: on 2026-08-12 `STAGE_CREATED` shipped unbound with every source assertion green and took
 * the production board down.
 *
 * So this lifts the SHIPPED functions out of proposal-review.js — including the box loop inside
 * renderPositioned, fitTxbx, and wireOverflowExpand's click handler — binds only what the page
 * really binds, and fires real pointer events at them.
 *
 * DELIBERATELY NOT A FULL DOM, for the reason board-render-harness.js gives: jsdom would let a
 * missing binding hide behind a stub. What is shimmed here is only what the gesture touches, and
 * the two measurements the maths depends on are modelled honestly:
 *
 *   * getBoundingClientRect().width IS scaled by the transform and offsetWidth is NOT — that
 *     ratio is how zoomScale() reads k, so the shim keeps them different.
 *   * offsetHeight follows the font-size percentage fitTxbx sets and is floored by minHeight,
 *     which is what makes "enlarging the box stops the overflow notice" a real measurement rather
 *     than a stub returning whatever the test wants.
 *
 * Usage: node box-drag-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

// Normalized to LF: the repo's frontend is checked out CRLF on Windows, and every pattern below
// anchors on "\n  " indentation. A CR left in would make the lifted source subtly different from
// the shipped source, which is the one thing this harness must not allow.
const SRC = fs.readFileSync(path.join(process.argv[2], "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");

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

/** The box loop out of renderPositioned — the code that actually mounts a box, so the harness
 *  cannot quietly test a hand-built element that has drifted from the shipped one. */
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

// ── the smallest DOM the gesture touches ─────────────────────────────────────
const PX_PER_PT = 96 / 72;

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

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.dataset = new Proxy({}, {
      set: (obj, k, v) => {
        obj[k] = v;
        // Mirror into attributes so `[data-grip]` selectors see what JS wrote.
        this.attrs["data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())] = v;
        return true;
      },
      get: (obj, k) => obj[k],
      deleteProperty: (obj, k) => { delete obj[k]; return true; },
    });
    this.attrs = {};
    this.title = "";
    this.textContent = "";
    this._classes = new Set();
    this._listeners = {};
    this._naturalPx = 0;          // the height the content would take at 100% font
    const self = this;
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
  get className() { return Array.from(this._classes).join(" "); }
  set className(v) {
    this._classes = new Set(String(v).split(/\s+/).filter(Boolean));
    this.attrs.class = v;
  }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  /** Flat markup only — that is all addBoxTools writes, and a real parser here would be a
   *  second implementation of HTML nobody asked for. */
  set innerHTML(html) {
    this.children = [];
    for (const m of String(html).matchAll(/<(\w+)([^>]*)>([\s\S]*?)<\/\1>/g)) {
      const el = new El(m[1]);
      for (const a of m[2].matchAll(/([\w-]+)="([^"]*)"/g)) {
        el.attrs[a[1]] = a[2];
        if (a[1] === "class") el.className = a[2];
        else if (a[1].startsWith("data-")) {
          el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = a[2];
        } else if (a[1] === "title") el.title = a[2];
      }
      el.textContent = m[3];
      this.appendChild(el);
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
      if (matches(el, sel)) return el;
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
  setPointerCapture() {}
  releasePointerCapture() {}
  getBoundingClientRect() {
    // Only #doc-zoom is ever measured this way, and only for its width. K is the harness's
    // stand-in for the CSS transform the page carries.
    return { width: (this.offsetWidth || 0) * K, height: 0, left: 0, top: 0 };
  }
  get offsetWidth() { return this._offsetWidth || 0; }
  set offsetWidth(v) { this._offsetWidth = v; }
  /** Content height in CSS px: scaled by whatever font-size fitTxbx set, floored by minHeight
   *  (a box shorter than its own box still occupies the box). */
  get offsetHeight() {
    const pct = /^(\d+)%$/.exec(this.style.fontSize || "");
    const k = pct ? Number(pct[1]) / 100 : 1;
    const floorPt = parseFloat(this.style.minHeight || "0") || 0;
    return Math.max(Math.round(this._naturalPx * k), Math.round(floorPt * PX_PER_PT));
  }
}

let K = 1;                                   // the live #doc-zoom scale
const document = {
  createElement: (t) => new El(t),
  activeElement: null,
  querySelectorAll: () => [],
};
const window = { _listeners: {}, addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); } };

function ev(target, props) {
  let stopped = false;
  return Object.assign({
    target: target,
    pointerId: 1,
    preventDefault() { this.defaulted = true; },
    stopPropagation() { stopped = true; },
    get _stopped() { return stopped; },
  }, props);
}

/** Bubble an event from `el` up through its ancestors, like the delegated listeners expect. */
function fire(el, type, props) {
  const e = ev(el, props);
  let node = el;
  while (node) {
    for (const fn of node._listeners[type] || []) {
      fn(e);
      if (e._stopped) return e;
    }
    node = node.parentNode;
  }
  return e;
}

function fireWindow(type, props) {
  const e = ev(props && props.target, props);
  for (const fn of window._listeners[type] || []) fn(e);
  return e;
}

// ── the page's own collaborators, as the page binds them ─────────────────────
const docSurface = new El("div");
const docZoom = new El("div");
docZoom.offsetWidth = 612 * PX_PER_PT;       // the page laid out at true point size

const templateBlocks = [{ id: 1, txbx: 0 }];   // truthy: the editor loaded
const boxDesign = new Map();
const persisted = { calls: 0 };

const overrideKey = (wt, audience) => String(wt || "") + ":" + String(audience || "Direct");
function mergeOverrideEntry(all, wt, audience, tv, items) {
  const next = Object.assign({}, (all && typeof all === "object") ? all : null);
  next[overrideKey(wt, audience)] = { template_version: tv, items: items };
  return next;
}

// `state`, `boxOverrides`, `boxLimits` and `templateVersion` are all REASSIGNED by the lifted
// code, so they have to live inside it and be reached through the returned handle. A shadow copy
// out here would drift, and the drift would look like a product bug.
let API = null;

// Which template the page thinks it is showing, so a base-bid switch can be simulated.
const PERSIST_AS = { wt: "epoxy", audience: "Direct" };

// Exactly what schedulePersistOverrides does AROUND the shipped collector + merge, so the store
// this harness reads back is written by the real functions.
function schedulePersistOverrides() {
  persisted.calls += 1;
  const boxes = API.collectBoxOverrides();
  const tv = API.getVersion();
  const { wt, audience } = PERSIST_AS;
  API.setState(Object.assign({}, API.getState(), {
    box_overrides_all: mergeOverrideEntry(API.getState().box_overrides_all, wt, audience, tv, boxes),
    box_overrides: boxes,
    box_overrides_meta: { template_version: tv, work_type: wt, audience: audience },
  }));
}

const LIFTED = [
  topConst("PT_PER_CSS_PX"), topConst("BOX_DRAG_SLOP_PT"), topConst("BOX_EPS_PT"),
  fn("zoomScale"), fn("ptFromClientPx"), fn("clampPt"), fn("dragBoxRect"),
  fn("boxOverrideEntry"), fn("boxReadout"), fn("effectiveBoxRect"), fn("applyBoxGeom"),
  fn("addBoxTools"), fn("showBoxReadout"), fn("setBoxOverride"), fn("wireBoxDrag"),
  fn("savedBoxOverridesFor"), fn("loadBoxOverrides"), fn("collectBoxOverrides"),
  fn("fitTxbx"), fn("wireOverflowExpand"),
].join("\n\n");

const BOX_LOOP = renderBoxLoop();

// THE PAGE'S OWN BINDING, not a friendlier one.
//
// This harness used to declare `let state = {}` with a `setState` that REBOUND it, and to merge
// against a fresh `API.getState()`. Both are kinder than reality, and they hid a real bug:
// proposal-review.js line 2 is `const state = TW.getState()` — a one-shot snapshot — while
// TW.setState re-reads localStorage into a NEW object and never writes back onto it. So a
// top-level key replaced by setState is frozen at page load for the whole visit, and an
// adversarial review showed the consequence: drag a box on an epoxy job, switch the base bid to a
// polish tab (the editor reloads in place, with no page load), come back, and the layout was gone
// AND the sibling template's entry had been dropped from the draft.
//
// So: `STORE` stands in for localStorage, `TW.getState()` returns a fresh copy of it exactly as
// shared.js does, `TW.setState` merges into STORE and leaves the snapshot alone, and the page's
// `state` is bound ONCE from it with const. A test that passes here now passes for the same reason
// the page works.
const STORE = { blob: {} };
const TWStub = {
  getState: () => JSON.parse(JSON.stringify(STORE.blob)),
  setState: (partial) => {
    STORE.blob = Object.assign(JSON.parse(JSON.stringify(STORE.blob)), partial || {});
    return STORE.blob;
  },
};

const api = new Function(
  "document", "window", "docSurface", "docZoom", "boxDesign", "templateBlocks",
  "overrideKey", "mergeOverrideEntry", "schedulePersistOverrides", "TW", "STORE",
  `const state = TW.getState();
  const liveKey = (name) => { try { return (TW.getState() || {})[name]; } catch { return undefined; } };
  let templateVersion = "TV1"; let boxOverrides = new Map(); let boxLimits = null;
` + LIFTED + `
  wireBoxDrag();
  wireOverflowExpand();
  function mountBoxes(geo, byBox, p1, tokens) {
    const renderBlockList = () => {};
${BOX_LOOP}
  }
  return { mountBoxes, dragBoxRect, ptFromClientPx, clampPt, boxOverrideEntry, boxReadout,
           effectiveBoxRect, applyBoxGeom, collectBoxOverrides, loadBoxOverrides,
           savedBoxOverridesFor, fitTxbx, zoomScale,
           setLimits: (l) => { boxLimits = l; },
           // The STORE, i.e. what a reload would read — never the frozen snapshot.
           getState: () => TW.getState(),
           setState: (s) => TW.setState(s),
           // The snapshot itself, so a test can prove it really is stale rather than assuming it.
           snapshotKeys: () => Object.keys(state),
           getVersion: () => templateVersion,
           setVersion: (v) => { templateVersion = v; },
           setBlocks: (b) => { templateBlocks = b; },
           clearOverrides: () => { boxOverrides = new Map(); },
           readOverrides: () => Array.from(boxOverrides.entries()) };
  `
)(document, window, docSurface, docZoom, boxDesign, templateBlocks,
  overrideKey, mergeOverrideEntry, schedulePersistOverrides, TWStub, STORE);
API = api;

const st = () => api.getState();

// ── the fixture: one box, at Kyle's real GC Resinous geometry ────────────────
// Measured from the template, not invented: box 3 of `GC/xx TREADWELL RESINOUS PROPOSAL - xx.docx`
// is 423 x 183.75pt at (161.8, 153.2) on a 612 x 792 sheet whose printable area is 432 x 648.
const DESIGN = { id: 3, x_pt: 161.8, y_pt: 153.2, w_pt: 423, h_pt: 183.75 };
const LIM = { pageW: 612, pageH: 792, maxW: 432, maxH: 648, minPt: 12 };
api.setLimits(LIM);

/** A fresh box on a fresh page, with `naturalPt` of content in it. Clears the override map: a
 *  scenario that inherited the previous one's layout would measure the wrong thing, and did. */
function mount(naturalPt) {
  api.clearOverrides();
  docSurface.children = [];
  const p1 = new El("div");
  docSurface.appendChild(p1);
  api.mountBoxes({ boxes: [DESIGN] }, new Map([[3, [{ id: 1 }]]]), p1, {});
  const box = p1.children[0];
  box._naturalPx = Math.round((naturalPt === undefined ? 60 : naturalPt) * PX_PER_PT);
  return box;
}

const grip = (box, mode) => box.querySelector('[data-grip="' + mode + '"]');
const rectOf = (box) => ({
  left: box.style.left, top: box.style.top, width: box.style.width,
  minHeight: box.style.minHeight, boxHPt: box.dataset.boxHPt,
  moved: box.classList.contains("tw-box-moved"),
});
const num = (v) => Math.round(parseFloat(v) * 100) / 100;

/** One complete gesture: down on a grip, one or more moves, an up. */
function gesture(box, mode, dxPx, dyPx, opts) {
  const g = grip(box, mode);
  fire(g, "pointerdown", { clientX: 0, clientY: 0 });
  const steps = (opts && opts.steps) || 1;
  for (let i = 1; i <= steps; i++) {
    fireWindow("pointermove", { clientX: dxPx * i / steps, clientY: dyPx * i / steps });
  }
  const readout = box.querySelector(".tw-box-size").textContent;
  const dragging = box.classList.contains("tw-box-dragging");
  const persistsBefore = persisted.calls;
  fireWindow("pointerup", {});
  return { rect: rectOf(box), readout: readout, draggingMidGesture: dragging,
           readoutAfter: box.querySelector(".tw-box-size").textContent,
           draggingAfter: box.classList.contains("tw-box-dragging"),
           persisted: persisted.calls - persistsBefore };
}

const out = {};
let box = null;

// 1. The conversion itself, at the zooms applyZoom actually produces (it clamps k to 0.45-1.7).
out.ptPerPx = [1, 0.45, 1.35, 1.7].map((k) => ({
  k: k, hundredPx: Number(api.ptFromClientPx(100, k).toFixed(3)) }));
// Junk k must degrade to "no zoom" rather than to Infinity/NaN, which would fling the box.
out.ptPerPxJunk = [api.ptFromClientPx(100, 0), api.ptFromClientPx(100, null),
                   api.ptFromClientPx(100, undefined), api.ptFromClientPx(NaN, 1)]
  .map((v) => Number(Number(v).toFixed(3)));

// 2. zoomScale MEASURES the transform off the element instead of remembering it.
K = 1.35;
out.zoomScaleMeasured = Number(api.zoomScale().toFixed(4));
K = 1;
out.zoomScaleAtOne = Number(api.zoomScale().toFixed(4));
docZoom.offsetWidth = 0;
out.zoomScaleUnlaidOut = api.zoomScale();          // before layout: no zoom, not a divide by zero
docZoom.offsetWidth = 612 * PX_PER_PT;

// 3. The pure rect maths, including both ceilings and both floors.
const START = { x: 161.8, y: 153.2, w: 423, h: 183.75 };
out.pure = {
  widen: api.dragBoxRect("e", START, { x: 5, y: 0 }, LIM),
  taller: api.dragBoxRect("s", START, { x: 0, y: 40 }, LIM),
  corner: api.dragBoxRect("se", START, { x: 5, y: 20 }, LIM),
  move: api.dragBoxRect("move", START, { x: -41.8, y: 46.8 }, LIM),
  // A resize grip must not move the box, and the move grip must not resize it.
  resizeKeepsCorner: api.dragBoxRect("se", START, { x: 30, y: 30 }, LIM),
  moveKeepsSize: api.dragBoxRect("move", START, { x: 30, y: 30 }, LIM),
  // SIZE is capped by the printable area…
  tooWide: api.dragBoxRect("e", { x: 100, y: 100, w: 423, h: 183.75 }, { x: 900, y: 0 }, LIM),
  tooTall: api.dragBoxRect("s", { x: 100, y: 20, w: 423, h: 183.75 }, { x: 0, y: 5000 }, LIM),
  // …and additionally by the paper, for a box that starts near an edge.
  tooWideNearEdge: api.dragBoxRect("e", { x: 200, y: 100, w: 400, h: 100 }, { x: 900, y: 0 }, LIM),
  tooTallNearEdge: api.dragBoxRect("s", { x: 100, y: 600, w: 400, h: 100 }, { x: 0, y: 5000 }, LIM),
  tooSmall: api.dragBoxRect("se", { x: 100, y: 100, w: 423, h: 183.75 }, { x: -9000, y: -9000 }, LIM),
  // POSITION is capped by the SHEET, so a box can never be dragged off the paper.
  offRight: api.dragBoxRect("move", START, { x: 9000, y: 0 }, LIM),
  offBottom: api.dragBoxRect("move", START, { x: 0, y: 9000 }, LIM),
  offTopLeft: api.dragBoxRect("move", START, { x: -9000, y: -9000 }, LIM),
  // But NOT by the printable area: every box in every template already sits in the margins, and
  // this is the one Kyle put at y=36 against a 72pt top margin. It has to stay movable.
  headerBox: api.dragBoxRect("move", { x: 18.35, y: 36, w: 72, h: 18 }, { x: -10, y: -20 }, LIM),
  // A box wedged against the right edge: the 12pt floor wins over an inverted window.
  wedged: api.dragBoxRect("e", { x: 605, y: 100, w: 7, h: 100 }, { x: -50, y: 0 }, LIM),
  noLimits: api.dragBoxRect("move", { x: 10, y: 10, w: 50, h: 50 }, { x: 5, y: 5 }, null),
};

// 4. What renderPositioned's OWN loop mounted.
box = mount();
out.mounted = {
  rect: rectOf(box),
  boxId: box.dataset.boxId,
  grips: box.querySelectorAll("[data-grip]").map((g) => g.attrs["data-grip"]),
  hasReset: !!box.querySelector("[data-box-reset]"),
  hasTools: !!box.querySelector(".tw-box-tools"),
  resetLabel: (box.querySelector("[data-box-reset]") || {}).textContent,
  resetTitle: (box.querySelector("[data-box-reset]") || {}).title,
  gripTitles: box.querySelectorAll("[data-grip]").map((g) => g.title),
};

// 5. THE bug this file exists for. 100 client px down the "s" grip must add 100·(72/96)/k points
//    of height — 166.67 at 45% zoom, 44.12 at 170% — and NOT a flat 100 or a flat 75.
out.heightByZoom = [0.45, 1, 1.35, 1.7].map((k) => {
  K = k;
  const b = mount();
  const res = gesture(b, "s", 0, 100);
  return { k: k, h: num(res.rect.minHeight), boxHPt: num(b.dataset.boxHPt),
           payload: api.collectBoxOverrides()["3"], readout: res.readout };
});

// 6. The corner grip at a zoom: both axes, and the width hitting the printable-area ceiling.
K = 1.35;
box = mount();
out.corner = { res: gesture(box, "se", 100, 100), payload: api.collectBoxOverrides() };

// 7. Moving, at a zoom, in several steps (the deltas are absolute from pointerdown, so a
//    multi-step drag must land in the same place a single-step one does).
K = 1.35;
box = mount();
out.moveStepped = { res: gesture(box, "move", -60, 90, { steps: 4 }),
                    payload: api.collectBoxOverrides() };
box = mount();
out.moveOneStep = { res: gesture(box, "move", -60, 90), payload: api.collectBoxOverrides() };

// 8. Dragged back to where the template has it = no override at all (the natural undo).
//    Deliberately AWAY from the right edge: a drag that clamps cannot be undone by an equal and
//    opposite one, and an earlier version of this scenario clamped and then blamed the product.
K = 1;
box = mount();
gesture(box, "move", -40, 40);
const afterFirst = api.collectBoxOverrides();
fire(grip(box, "move"), "pointerdown", { clientX: 0, clientY: 0 });
fireWindow("pointermove", { clientX: 40, clientY: -40 });
fireWindow("pointerup", {});
out.backToDesign = { afterFirst: afterFirst, afterBack: api.collectBoxOverrides(),
                     rect: rectOf(box) };

// 9. A grab with no travel must not mark the box as moved, or a Reset button appears on every box
//    somebody brushed past.
box = mount();
fire(grip(box, "se"), "pointerdown", { clientX: 10, clientY: 10 });
fireWindow("pointermove", { clientX: 10, clientY: 10 });
const persistsBefore = persisted.calls;
fireWindow("pointerup", {});
out.slop = { payload: api.collectBoxOverrides(), moved: rectOf(box).moved,
             persisted: persisted.calls - persistsBefore };

// 10. Reset: the click path, and that it reaches the store.
box = mount();
gesture(box, "se", 100, 100);
const beforeReset = api.collectBoxOverrides();
fire(box.querySelector("[data-box-reset]"), "click", {});
out.reset = { before: beforeReset, after: api.collectBoxOverrides(), rect: rectOf(box),
              stored: st().box_overrides };

// 11. THE POINT OF THE FEATURE: the overflow notice must stand down once the box is big enough.
box = mount(400);                       // 400pt of content in a 183.75pt box
api.fitTxbx(box);
const atDesign = { marked: box.classList.contains("tw-notes-overflow"),
                   clipped: box.style.maxHeight, fontSize: box.style.fontSize };
K = 1;
gesture(box, "s", 0, Math.round((460 - 183.75) * PX_PER_PT));   // grow past the content
out.overflow = {
  atDesign: atDesign,
  afterGrow: { marked: box.classList.contains("tw-notes-overflow"),
               clipped: box.style.maxHeight, fontSize: box.style.fontSize,
               minHeight: num(box.style.minHeight), boxHPt: num(box.dataset.boxHPt) },
};

// 12. wireOverflowExpand must not treat a grip release as "peek at the hidden text"…
box = mount(400);
api.fitTxbx(box);
fire(grip(box, "se"), "click", {});
const gripClickOpened = box.classList.contains("tw-notes-open");
fire(box.querySelector("[data-box-reset]"), "click", {});
const resetClickOpened = box.classList.contains("tw-notes-open");
// …while a click on the box itself still peeks, so the guard did not disable the feature.
fire(box, "click", {});
out.peek = { gripClickOpened: gripClickOpened, resetClickOpened: resetClickOpened,
             bodyClickOpened: box.classList.contains("tw-notes-open") };

// 13. Persistence, the version guard, and the sibling-template store.
api.setState({});
PERSIST_AS.wt = "epoxy";
box = mount();
K = 1;
gesture(box, "se", 60, 60);
const savedState = st();
out.persist = { stored: savedState.box_overrides,
                keyed: Object.keys(savedState.box_overrides_all || {}),
                meta: savedState.box_overrides_meta };
// Reloading the same template brings the layout back.
api.setVersion("TV1");
api.loadBoxOverrides("epoxy", "Direct");
out.restoreSameVersion = api.readOverrides();
// After the .docx is re-annotated the ids mean different boxes, so they must be dropped.
api.setVersion("TV-NEW");
api.loadBoxOverrides("epoxy", "Direct");
out.restoreStaleVersion = api.readOverrides();
api.setVersion("TV1");
// Another template's layout is not this one's.
api.loadBoxOverrides("polish", "Direct");
out.restoreOtherTemplate = api.readOverrides();
api.loadBoxOverrides("epoxy", "GC");
out.restoreOtherAudience = api.readOverrides();
// The reported bug this store exists for: switch the base bid to polish, drag there, switch back.
PERSIST_AS.wt = "polish";
box = mount();
gesture(box, "move", 20, 20);
PERSIST_AS.wt = "epoxy";
api.loadBoxOverrides("epoxy", "Direct");
out.roundTrip = { keyed: Object.keys(st().box_overrides_all || {}),
                  epoxyBack: api.readOverrides() };

// 14. Garbage in the store reads as nothing saved, rather than breaking the page on load.
api.setState({ box_overrides_all: { "epoxy:Direct": { template_version: "TV1", items: "nope" } } });
api.loadBoxOverrides("epoxy", "Direct");
out.restoreGarbage = api.readOverrides();
api.setState({ box_overrides_all: { "epoxy:Direct": { template_version: "TV1",
  items: { "3": { w_pt: "wide", h_pt: 200 }, bad: { h_pt: 100 }, "4": null, "5": 7 } } } });
api.loadBoxOverrides("epoxy", "Direct");
out.restorePartlyGarbage = api.readOverrides();
// The nastiest shape: values that COERCE to a legal number. 0 is a legal position (the top-left
// corner of the sheet), so a null read through Number() would silently pin the box there.
api.setState({ box_overrides_all: { "epoxy:Direct": { template_version: "TV1",
  items: { "3": { x_pt: null, y_pt: "", w_pt: true, h_pt: 200 } } } } });
api.loadBoxOverrides("epoxy", "Direct");
out.restoreCoercibleGarbage = api.readOverrides();
api.setState({ box_overrides_all: [1, 2, 3], box_overrides: "nope" });
api.loadBoxOverrides("epoxy", "Direct");
out.restoreArrayStore = api.readOverrides();

// 15. A saved layout is restored BEFORE the render, so the box mounts at its saved size.
api.setState({ box_overrides_all: { "epoxy:Direct":
  { template_version: "TV1", items: { "3": { h_pt: 300, x_pt: 100 } } } } });
api.loadBoxOverrides("epoxy", "Direct");
docSurface.children = [];
const p1 = new El("div");
docSurface.appendChild(p1);
api.mountBoxes({ boxes: [DESIGN] }, new Map([[3, [{ id: 1 }]]]), p1, {});
out.mountedRestored = rectOf(p1.children[0]);

// 16. The legacy/no-editor fallback: a saved layout still reaches the payload when the template
//     fetch failed and there is no live map to read.
// `box_overrides_all: {}` is stated, not assumed. setState now MERGES into the store, exactly as
// shared.js does, so the keyed entries cases 14-15 filed are still there — and savedBoxOverridesFor
// checks the keyed store BEFORE the flat slot, so without clearing it this case would silently
// exercise the keyed path and prove nothing about the fallback. The old stub replaced the whole
// blob on every setState, which handed each case a clean slate the page never gets.
api.setState({ box_overrides_all: {},
               box_overrides: { "3": { h_pt: 300 } },
               box_overrides_meta: { template_version: "TV1", work_type: "epoxy", audience: "Direct" } });
api.setBlocks(null);
out.fallbackNoEditor = api.collectBoxOverrides();
out.fallbackFlatMeta = api.savedBoxOverridesFor("epoxy", "Direct");
out.fallbackFlatWrongTemplate = api.savedBoxOverridesFor("gyp", "Direct");
api.setState({ box_overrides: "nope" });
out.fallbackJunk = api.collectBoxOverrides();
api.setBlocks([{ id: 1, txbx: 0 }]);

// 17. The strings the estimator reads while dragging.
out.readout = {
  size: api.boxReadout("se", { x: 1, y: 2, w: 423.4, h: 183.75 }),
  move: api.boxReadout("move", { x: 161.8, y: 153.2, w: 1, h: 2 }),
};

// 18. boxOverrideEntry keeps only what changed, at the template's own precision.
out.entry = {
  nothing: api.boxOverrideEntry(DESIGN, { x: 161.8, y: 153.2, w: 423, h: 183.75 }),
  widthOnly: api.boxOverrideEntry(DESIGN, { x: 161.8, y: 153.2, w: 430, h: 183.75 }),
  rounded: api.boxOverrideEntry(DESIGN, { x: 161.8, y: 153.2, w: 430.123456, h: 183.75 }),
  hairline: api.boxOverrideEntry(DESIGN, { x: 161.82, y: 153.2, w: 423, h: 183.75 }),
  nan: api.boxOverrideEntry(DESIGN, { x: NaN, y: 153.2, w: 423, h: 183.75 }),
  noDesign: api.boxOverrideEntry(null, { x: 5, y: 5, w: 5, h: 5 }),
};

console.log(JSON.stringify(out));
