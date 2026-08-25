"use strict";
/* Bold / italic / underline / SIZE have to survive a reload, and a reload must never make the
 * saved draft poorer than it found it.
 *
 * THE BUG THIS HARNESS EXISTS FOR, live on production until 2026-08-21.
 *
 *   `restoreSavedOverrides` replayed a saved override with `el.textContent = o.text` and never
 *   looked at `o.runs`. So after ANY re-init — F5, re-opening the draft, a trip to Done or
 *   Estimate Review and back, a base-bid switch that re-runs initDocumentEditor in place — the
 *   paragraph was one plain text node again. `collectOverrides` then re-serialised THAT:
 *   `runsArePlain` said yes, `tw-fmt` was gone with the spans, and the entry degraded from
 *   {id, text, runs} to {id, text}. The 800ms `schedulePersistOverrides` wrote it back over the
 *   good one. The estimator's formatting was not hidden, it was destroyed.
 *
 * WHY THIS RUNS THE CODE RATHER THAN READING IT. The whole bug is a DISAGREEMENT between two
 * functions that both look correct on their own: one writes a shape, the other reads a
 * different one. No source-text assertion can see that, and the round trip is four functions
 * deep (blockHtml -> toggleFormat/applyFormat -> collectOverrides -> restoreSavedOverrides ->
 * collectOverrides again). The precedent for insisting: on 2026-08-12 `STAGE_CREATED` shipped
 * unbound with every source assertion green and took the production board down.
 *
 * The DOM shim is deliberately partial, exactly as doc-editor-harness.js argues: jsdom would
 * let a missing binding hide behind a stub. What is modelled here is what these functions
 * actually touch — element and text nodes walked by nodeType, `style` parsed out of a real
 * inline style attribute (fmtAt reads the formatting back out of exactly that), class lists,
 * dataset, and bubbling input events (markEdited dispatches one, and the page's own delegated
 * handler is what sets tw-dirty and calls the persist).
 *
 * Two whole PAGES are built over ONE store, so "two tabs open on the same draft" is two real
 * editors racing through the real persist rather than a claim about one.
 *
 * Usage: node doc-editor-fidelity-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
// Normalized to LF: the repo checks the frontend out CRLF on Windows and every lift pattern
// below anchors on "\n  " indentation. A stray CR would make the lifted source subtly different
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

/** A top-level `const` whose VALUE contains a semicolon — a prose string, in practice.
 *  topConst() scans for the first `;` at bracket depth 0 and has no idea it is inside a string
 *  literal, so a message with a semicolon in it would cut the statement in half and produce an
 *  unterminated string. This reads whole LINES until one ends the statement. Same helper
 *  doc-editor-labels-harness.js carries, and for the same reason. */
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

/** One delegated top-level listener body, by the comment that introduces it. The input handler
 *  is what turns a format into `tw-dirty` + a persist, so it is lifted rather than imitated. */
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
const Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
const unesc = (s) => String(s).replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, k) => ENTITIES[k]);

/** `font-weight:700;font-size:9pt` -> {fontWeight:"700", fontSize:"9pt"}. fmtAt reads exactly
 *  these camelCase properties, so parsing the real attribute is what keeps the lifted fmtAt
 *  honest instead of handing it a pre-built object. */
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
  constructor(tag, doc) {
    this.nodeType = Node.ELEMENT_NODE;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.style = {};
    this.attrs = {};
    this.title = "";
    this._doc = doc || null;
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
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  get textContent() {
    return this.childNodes.map((n) =>
      n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent).join("");
  }
  /** The OLD reload path, still used for a legacy `{id, text}` entry: the stored plain text
   *  goes straight in and `white-space: pre-wrap` renders its newlines. */
  set textContent(v) {
    this.childNodes = [];
    if (String(v) !== "") this.appendChild(new Text(v));
  }
  /** A real (if small) parser. renderRuns and blockHtml both nest a `.tw-fill` span INSIDE a
   *  style span, so a flat parser would silently dissolve the token boundary the whole token
   *  half of this fix depends on. */
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
        const el = new El(m[2], this._doc);
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
  get innerHTML() {
    return this.childNodes.map((n) => {
      if (n.nodeType === Node.TEXT_NODE) return n.nodeValue;
      const cls = n.className ? ' class="' + n.className + '"' : "";
      const st = Object.keys(n.style).length
        ? ' style="' + Object.keys(n.style).map((k) =>
            k.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase()) + ":" + n.style[k]).join(";") + '"' : "";
      const tok = n.attrs["data-token"] ? ' data-token="' + n.attrs["data-token"] + '"' : "";
      const t = n.tagName.toLowerCase();
      return VOID.has(n.tagName) ? "<" + t + ">"
        : "<" + t + cls + st + tok + ">" + n.innerHTML + "</" + t + ">";
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
  normalize() { /* selectionRange's markers are not used here */ }
  addEventListener(type, f) { (this._listeners[type] = this._listeners[type] || []).push(f); }
  /** markEdited() calls this, and the page's own delegated input handler is what sets tw-dirty
   *  and schedules the persist. Bubbling it for real is what makes the round trip honest. */
  dispatchEvent(e) {
    let cur = this;
    e.target = this;
    while (cur) {
      for (const f of (cur._listeners[e.type] || []).slice()) f(e);
      cur = cur.parentNode;
    }
    return true;
  }
  blur() { if (this._doc && this._doc.activeElement === this) this._doc.activeElement = null; }
  focus() { if (this._doc) this._doc.activeElement = this; }
  getBoundingClientRect() { return { width: 0, height: 0, left: 0, top: 0 }; }
  get offsetHeight() { return 0; }
}

/** `new Event("input", {bubbles:true})` is what markEdited constructs. Node's own global Event
 *  exists but its `target` is getter-only, so the sandbox gets this one instead — the page's
 *  line stays verbatim, which is the point. */
class Ev {
  constructor(type, opts) {
    this.type = String(type);
    this.bubbles = !!(opts && opts.bubbles);
    this.target = null;
  }
}

function makeDoc() {
  const doc = { activeElement: null, querySelectorAll: () => [] };
  doc.createElement = (t) => new El(t, doc);
  doc.body = new El("body", doc);
  return doc;
}

// ── the shared draft: ONE store, exactly as localStorage is shared between tabs ───────────────
const SEED = { work_type: "epoxy", audience: "Direct" };
const STORE = { blob: JSON.parse(JSON.stringify(SEED)) };
// getState hands back a fresh COPY and setState merges into the store without touching the
// caller's snapshot — shared.js's real contract, and the reason `liveKey` exists at all.
const TW = {
  getState: () => JSON.parse(JSON.stringify(STORE.blob)),
  setState: (partial) => {
    STORE.blob = Object.assign(JSON.parse(JSON.stringify(STORE.blob)), partial || {});
    return STORE.blob;
  },
  readForm: () => ({}),
};

const LIFTED = [
  topConst("escHtml"), topConst("DOC_TOKEN_RE"), topConst("sameFmt"),
  topConst("SIZE_CHOICES"), topConst("INDENT_STEP_TW"), topConst("INDENT_MAX_TW"),
  topConst("TWIPS_PER_PT"),
  fn("effectiveWorkType"),
  fn("fillHtml"), fn("fillPlain"), fn("runStyleCss"), fn("blockHtml"),
  fn("singleTokenHint"), fn("setBlockContent"),
  // renderBlock reads `para.marker` to draw a numbered clause as its NUMBER, and the input
  // handler below reaches restoreEmptiedClause, which reaches isNumberedClause and the message
  // const. Every one of them has to be here: a callee left out of this list does not fail at
  // lift time, it throws ReferenceError on the first paragraph that reaches it, which is how a
  // whole module of tests went red on 2026-08-15 for a function nobody remembered to add.
  fn("isNumberedClause"), fn("blanksANumberedClause"),
  stringConst("_CLAUSE_KEPT_MSG"), fn("restoreEmptiedClause"),
  fn("renderBlock"),
  fn("fmtAt"), fn("segmentsOf"), fn("mergeSegs"), fn("serializeRuns"), fn("editRuns"),
  fn("storedRuns"), fn("runEditCss"), fn("renderRuns"), fn("serializeBlock"),
  fn("runsArePlain"), fn("markEdited"),
  fn("selectionFormat"), fn("applyFormat"), fn("toggleFormat"),
  fn("paraBase"), fn("paraNow"), fn("paraPatch"), fn("sanitizeParaPatch"),
  fn("applyParaToEl"), fn("setParaState"),
  topConst("overrideKey"), fn("mergeOverrideEntry"), topConst("liveKey"),
  fn("savedOverridesFor"), fn("restoreSavedOverrides"),
  fn("collectOverrides"), fn("preserveRichOverrides"),
  // The REAL writer. This is the function that overwrote good data with degraded data, so a
  // harness that imitated it would be testing the imitation.
  fn("schedulePersistOverrides"),
  fn("refreshFillsInPlace"), fn("refreshDocumentFills"),
].join("\n\n");

const INPUT_HANDLER = delegated("  // Mark blocks dirty as they're edited (delegated");

/** One whole editor over the shared store: its own document, its own docSurface, its own
 *  template version. Built twice for the two-tabs case. */
function makePage(label) {
  const document = makeDoc();
  // getSelection is what selectionInSurface reads: applyFormat only re-places the document
  // selection when there WAS one in the document, so a ribbon press made from a sidebar field does
  // not paint a highlight the estimator never made. This harness drives formatting through CARET,
  // which IS a document selection, so the honest stub reports one anchored on the surface -- and it
  // is defined as a getter over `docSurface` below rather than a constant, so a future test that
  // clears CARET gets the other branch for free.
  const window = { _listeners: {}, addEventListener(t, f) { (this._listeners[t] = this._listeners[t] || []).push(f); },
                   getSelection: () => ({ rangeCount: 1,
                                          getRangeAt: () => ({ startContainer: docSurface,
                                                               endContainer: docSurface,
                                                               collapsed: false }) }) };
  const docSurface = new El("div", document);
  const persists = [];
  return new Function(
    "document", "window", "docSurface", "F", "Node", "TW", "El", "Event", "persists", "label",
    `const state = TW.getState();
    const RUN_KEYS = F.RUN_KEYS;
    const coalesce = F.coalesce, patchRuns = F.patchRuns, runsLength = F.runsLength;
    const TOKEN_HINTS = {};
    let _fmtBusy = false;
    let flowMode = false;
    let templateVersion = "";
    let templateBlocks = null;
    let _overridesTimer = null, _fillsTimer = null;
    const blockById = new Map();
    const pristineById = new Map();
    const paraById = new Map();
    // Debounces collapsed to "run now": what is under test is what gets WRITTEN, and a real
    // timer would make every assertion below a race. The persist is still the shipped one.
    const setTimeout = (f) => { persists.push(label); f(); return 1; };
    const clearTimeout = () => {};
    // Not lifted, for the reason doc-editor-harness.js gives: selectionRange and placeSelection
    // are Range arithmetic against a live selection, the one thing a shim cannot model
    // honestly. CARET is [start, end] character offsets, i.e. what selectionRange returns.
    let CARET = null;
    const selectionRange = () => CARET;
    const placeSelection = () => {};
    const showFmtBar = () => {};
    ${fn("runsEqual")}
    ${fn("selectionInSurface")}
    // refreshDocumentFills re-renders the ribbon after a re-fill, because the buttons are read off
    // a remembered range that the re-fill may have just invalidated — a lit Bold describing a
    // selection that no longer exists is a button lying about what pressing it will do. The
    // ribbon itself is fmt-ribbon-harness.js's world; a no-op is the truthful answer for a harness
    // that mounts no ribbon, and it still fails loudly if the page ever renames the function.
    const renderFmtBar = () => {};
    // Box geometry belongs to box-drag-harness.js, which builds that world; an empty collector
    // is the truthful answer for a harness that mounts no boxes.
    const collectBoxOverrides = () => ({});
    const renderSystemPreview = () => {};
    const renderNotesPreview = () => {};
    const scheduleRepaginate = () => {};
    const form = null;
    // The token values the sidebar currently resolves to. Settable, because "the estimator
    // changed the square footage" is one of the things under test.
    let TOKENS = {};
    const computeTokenValues = () => TOKENS;
` + LIFTED + `
    docSurface.addEventListener("input", (e) => ${INPUT_HANDLER});

    /** Mount a template through the page's OWN renderBlock, so the fills, the pristine
     *  baselines and the class list are the shipped ones. This is what a page load does. */
    function mount(records, tokens, version) {
      TOKENS = tokens;
      templateVersion = version;
      templateBlocks = records;
      blockById.clear(); pristineById.clear(); paraById.clear();
      docSurface.childNodes = [];
      for (const b of records) {
        blockById.set(b.id, b);
        docSurface.appendChild(renderBlock(b, tokens));
      }
    }
    const blockEl = (id) => docSurface.querySelector('.tw-block[data-id="' + Number(id) + '"]');
    const snapshot = (id) => {
      const el = blockEl(id);
      if (!el) return null;
      return { text: serializeBlock(el), runs: serializeRuns(el),
               html: el.innerHTML,
               fills: el.querySelectorAll(".tw-fill[data-token]").map(s => [s.attrs["data-token"], s.textContent]),
               dirty: el.classList.contains("tw-dirty"), fmt: el.classList.contains("tw-fmt"),
               empty: el.classList.contains("tw-empty") };
    };
    return {
      mount: mount, blockEl: blockEl, snapshot: snapshot,
      setCaret: (r) => { CARET = r; },
      setTokens: (t) => { TOKENS = t; },
      // The B / I / U buttons and the size select, through the toolbar's own entry points.
      bold: (id, range) => { CARET = range; return toggleFormat(blockEl(id), "bold"); },
      italic: (id, range) => { CARET = range; return toggleFormat(blockEl(id), "italic"); },
      size: (id, range, pt) => applyFormat(blockEl(id), { size_pt: pt }, range),
      resetFmt: (id, range) => applyFormat(blockEl(id),
        { bold: null, italic: null, underline: null, size_pt: null }, range),
      type: (id, value) => {
        // What the browser does when somebody edits inside a run: the TEXT NODE changes, no
        // restyling. Then the page's own input handler runs, exactly as it would.
        const el = blockEl(id);
        el.textContent = value;
        el.dispatchEvent({ type: "input" });
      },
      // Typing at the END of a paragraph. Deliberately NOT an el.textContent assignment (and
      // NOTE: no backticks in this comment, or any comment inside this string -- the whole
      // sandbox body is one template literal, so a backtick here ends it early and the file
      // stops compiling with "missing ) after argument list" pointing at a line above), which would
      // dissolve the style and fill spans: what the browser does is add characters to a text
      // node and leave every span in place, and a block that still HAS its fills is the only
      // one where "is this paragraph still the template's words" can matter.
      append: (id, value) => {
        const el = blockEl(id);
        el.appendChild(new (el.constructor)("span"));
        el.childNodes[el.childNodes.length - 1].innerHTML = value;
        el.dispatchEvent({ type: "input" });
      },
      typeInFill: (id, tok, value) => {
        const el = blockEl(id);
        const sp = el.querySelectorAll('.tw-fill[data-token="' + tok + '"]')[0];
        sp.childNodes[0].nodeValue = value;
        el.dispatchEvent({ type: "input" });
      },
      /** What the paragraph LOOKS like: which marker class it carries, the number it shows, and
       *  whether the "clause kept" notice is up. Its own accessor rather than more keys on
       *  snapshot(), which other scenarios compare field by field. */
      look: (id) => {
        const el = blockEl(id);
        if (!el) return null;
        return { li: el.classList.contains("tw-li"), num: el.classList.contains("tw-num"),
                 marker: el.attrs["data-marker"] || "",
                 kept: el.classList.contains("tw-clause-kept"), title: el.title || "",
                 dirty: el.classList.contains("tw-dirty"),
                 empty: el.classList.contains("tw-empty"), text: serializeBlock(el) };
      },
      collect: () => collectOverrides(),
      restore: (wt, audience, tokens) => {
        if (tokens) TOKENS = tokens;
        return restoreSavedOverrides(wt, audience, tokens || TOKENS);
      },
      persist: () => schedulePersistOverrides(),
      refreshFills: (tokens) => { TOKENS = tokens; refreshDocumentFills(); },
      version: () => templateVersion,
    };
    `
  )(document, window, docSurface, F, Node, TW, El, Ev, persists, label);
}

// ── the fixture ──────────────────────────────────────────────────────────────
// Block 115 of the Direct epoxy template, VERBATIM as /api/proposal-template reports it: three
// runs, the label bold and the value explicitly un-bolded, at the template's real 8pt Zetta
// Serif Book. `bold: false` and an ABSENT bold are different instructions to the writer, so the
// friendlier two-run simplification would be testing a payload the page never sends.
// test_doc_editor_ux.py re-derives these runs from the .docx, so they cannot rot into fiction.
const FMT = { italic: null, underline: null, size_pt: 8.0,
              font: "Zetta Serif Book", color: "404040" };
const BLOCK_115 = {
  id: 115,
  text: "Scope:  {{scope_notes}}",
  runs: [
    Object.assign({ text: "Scope:", bold: true }, FMT),
    Object.assign({ text: "  ", bold: false }, FMT),
    Object.assign({ text: "{{scope_notes}}", bold: false }, FMT),
  ],
};
// A WORK row carrying a NUMBER off the estimate. This is the paragraph the token half of the
// fix is about: bold part of it, then correct the square footage on Estimate Review.
const BLOCK_116 = {
  id: 116,
  text: "Area: {{epoxy_sf}} SF",
  runs: [Object.assign({ text: "Area: {{epoxy_sf}} SF", bold: false }, FMT)],
};
const TEMPLATE = [BLOCK_115, BLOCK_116];
const TOKENS_A = { scope_notes: "Grind and coat.", epoxy_sf: "5,200" };
const TOKENS_B = { scope_notes: "Grind and coat.", epoxy_sf: "6,000" };
const VER = "tv-epoxy-1";

const out = {};
out.fixture = { block115: BLOCK_115.runs, tokens: TOKENS_A };

// ═══ 1. THE ROUND TRIP: render, bold a phrase, serialise, restore, re-serialise ══════════════
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("tab-a");
  p.mount(TEMPLATE, TOKENS_A, VER);
  const pristine = p.snapshot(115);

  // Bold "Grind" — characters 8..13 of "Scope:  Grind and coat." Deliberately a PHRASE inside
  // the paragraph, not the whole thing: the failure mode to catch is neighbours picking the
  // bold up, and a whole-paragraph bold could not show that.
  const at = pristine.text.indexOf("Grind");
  p.bold(115, [at, at + 5]);
  const bolded = p.snapshot(115);
  const sent = p.collect();
  p.persist();
  const stored = JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all[
    "epoxy:Direct"].items));

  // THE RELOAD. A fresh page over the same draft: nothing survives in memory, everything has
  // to come back out of the store.
  const q = makePage("tab-a-reloaded");
  q.mount(TEMPLATE, TOKENS_A, VER);
  q.restore("epoxy", "Direct", TOKENS_A);
  const restored = q.snapshot(115);
  const resent = q.collect();
  // …and the persist the next keystroke would fire. THIS is the write that used to destroy it.
  q.persist();
  const afterSecondPersist = JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all[
    "epoxy:Direct"].items));

  out.roundTrip = {
    pristine: pristine, bolded: bolded, sent: sent, stored: stored,
    restored: restored, resent: resent, afterSecondPersist: afterSecondPersist,
    // A third trip, because the degradation was progressive: restore -> serialise -> restore.
    thirdTrip: (() => {
      const r = makePage("tab-a-again");
      r.mount(TEMPLATE, TOKENS_A, VER);
      r.restore("epoxy", "Direct", TOKENS_A);
      r.persist();
      return r.snapshot(115);
    })(),
  };
  // What the .docx has to be built from, handed to the Python half verbatim.
  out.docxRuns = afterSecondPersist.find((o) => o.id === 115).runs;
}

// ═══ 2. SIZE, the half that "bold looked fine" hid ═══════════════════════════════════════════
// A size is the one switch with no HTML tag behind it, so an execCommand-shaped bug shows up
// here first. It is also what Hanz asked for by name: "spacing, font size, indentation ETC".
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("size");
  p.mount(TEMPLATE, TOKENS_A, VER);
  const text = p.snapshot(115).text;
  const at = text.indexOf("Grind");
  p.size(115, [at, at + 5], 14);
  p.italic(115, [0, 6]);
  p.persist();
  const q = makePage("size-reloaded");
  q.mount(TEMPLATE, TOKENS_A, VER);
  q.restore("epoxy", "Direct", TOKENS_A);
  q.persist();
  out.sizeAndItalic = {
    restored: q.snapshot(115),
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
  };
}

// ═══ 3. THE GUARD, on its own ════════════════════════════════════════════════════════════════
// (b) of the brief: a serialise-after-restore must never replace richer stored data with
// poorer. Asserted with the restore DELIBERATELY SKIPPED, i.e. against a page in exactly the
// state the bug left it in. A guard that only holds while the restore is correct is not a guard.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("guard-writer");
  p.mount(TEMPLATE, TOKENS_A, VER);
  const at = p.snapshot(115).text.indexOf("Grind");
  p.bold(115, [at, at + 5]);
  p.persist();
  const good = JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items));

  const q = makePage("guard-no-restore");
  q.mount(TEMPLATE, TOKENS_A, VER);
  // No restore at all, then a keystroke elsewhere in the document. This is the exact sequence
  // that used to write {id, text} over {id, text, runs}.
  q.type(116, "Area: 5,200 SF and cove");
  const collected = q.collect();
  q.persist();
  out.guard = {
    good: good,
    collected: collected,
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
  };
}

// ═══ 4. …and the guard must not FREEZE formatting the estimator removed ══════════════════════
// Reset sends one plain run rather than no runs (tw-fmt is never taken off), and emptying a
// paragraph sends runs: []. Both are arrays, so both get through the guard.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("reset");
  p.mount(TEMPLATE, TOKENS_A, VER);
  const at = p.snapshot(115).text.indexOf("Grind");
  p.bold(115, [at, at + 5]);
  p.persist();
  const q = makePage("reset-after-reload");
  q.mount(TEMPLATE, TOKENS_A, VER);
  q.restore("epoxy", "Direct", TOKENS_A);
  const len = q.snapshot(115).text.length;
  q.resetFmt(115, [0, len]);
  q.persist();
  out.reset = {
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
    onScreen: q.snapshot(115),
  };

  const r = makePage("emptied");
  r.mount(TEMPLATE, TOKENS_A, VER);
  r.restore("epoxy", "Direct", TOKENS_A);
  r.type(115, "");
  r.persist();
  out.emptied = {
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
    onScreen: r.snapshot(115),
  };
}

// ═══ 5. TOKENS: a value that changed since the format was applied ════════════════════════════
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("token-fresh");
  p.mount(TEMPLATE, TOKENS_A, VER);
  // Bold the label "Area:" only. The number is never touched.
  p.bold(116, [0, 5]);
  p.persist();
  const savedRuns = JSON.parse(JSON.stringify(
    TW.getState().paragraph_overrides_all["epoxy:Direct"].items.find((o) => o.id === 116).runs));

  // The estimator goes back to Estimate Review and corrects the square footage, then returns.
  const q = makePage("token-fresh-reloaded");
  q.mount(TEMPLATE, TOKENS_B, VER);
  q.restore("epoxy", "Direct", TOKENS_B);
  q.persist();
  out.tokenFresh = {
    savedRuns: savedRuns,
    restored: q.snapshot(116),
    stored: JSON.parse(JSON.stringify(
      TW.getState().paragraph_overrides_all["epoxy:Direct"].items.find((o) => o.id === 116))),
  };
}

// ═══ 6. …but a token the estimator TYPED OVER keeps their characters ═════════════════════════
// {{scope_notes}} renders as an editable fill and rewording the scope in the document is a
// first-class use of this editor. Their text must not be replaced by the sidebar's value.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("token-typed");
  p.mount(TEMPLATE, TOKENS_A, VER);
  p.typeInFill(115, "scope_notes", "Grind, patch and coat.");
  const at = p.snapshot(115).text.indexOf("patch");
  p.bold(115, [at, at + 5]);
  p.persist();
  const typedRuns = JSON.parse(JSON.stringify(
    TW.getState().paragraph_overrides_all["epoxy:Direct"].items.find((o) => o.id === 115).runs));

  // Reload with a DIFFERENT scope in the sidebar, which is the hostile case.
  const q = makePage("token-typed-reloaded");
  const hostile = { scope_notes: "Something else entirely.", epoxy_sf: "6,000" };
  q.mount(TEMPLATE, hostile, VER);
  q.restore("epoxy", "Direct", hostile);
  out.tokenTyped = { savedRuns: typedRuns, restored: q.snapshot(115) };
}

// ═══ 6b. …and the typing rule has to hold ON ITS OWN ══════════════════════════════════════════
// Case 6 formats INSIDE the fill, which splits it — so the duplicate-token rule would have
// dropped the tag even if the typing rule were missing, and 6 therefore proves nothing about
// the typing rule. Here the estimator types in the fill and then bolds the LABEL, well outside
// it. The fill stays one run, so only "the words changed, so they are the estimator's" can
// stop the sidebar overwriting them.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("token-typed-format-outside");
  p.mount(TEMPLATE, TOKENS_A, VER);
  p.typeInFill(115, "scope_notes", "Grind, patch and coat.");
  // ITALIC, not bold: the label is already bold, so pressing B on it would turn bold OFF and
  // coalesce the paragraph back to one plain run - which would quietly stop this case isolating
  // anything. Italic is a switch the label does not already carry.
  p.italic(115, [0, 6]);            // "Scope:", nowhere near the fill
  // The fill is still ONE span, which is what makes the duplicate-token rule irrelevant here.
  const fillsAtSave = p.snapshot(115).fills;
  p.persist();
  const savedRuns = JSON.parse(JSON.stringify(
    TW.getState().paragraph_overrides_all["epoxy:Direct"].items.find((o) => o.id === 115).runs));
  const q = makePage("token-typed-format-outside-reloaded");
  const hostile = { scope_notes: "Something else entirely.", epoxy_sf: "6,000" };
  q.mount(TEMPLATE, hostile, VER);
  q.restore("epoxy", "Direct", hostile);
  out.tokenTypedFormatOutside = {
    savedRuns: savedRuns, fillsAtSave: fillsAtSave, restored: q.snapshot(115),
  };
}

// ═══ 7. A fill split in half by formatting is never rebuilt from the token ═══════════════════
// Bold HALF the number and the fill becomes two spans. Writing the whole value into each would
// print it twice, on screen and in the customer's document.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("split-fill");
  p.mount(TEMPLATE, TOKENS_A, VER);
  const at = p.snapshot(116).text.indexOf("5,200");
  p.bold(116, [at, at + 2]);        // "5," only
  p.persist();
  const q = makePage("split-fill-reloaded");
  q.mount(TEMPLATE, TOKENS_B, VER);
  q.restore("epoxy", "Direct", TOKENS_B);
  out.splitFill = {
    stored: JSON.parse(JSON.stringify(
      TW.getState().paragraph_overrides_all["epoxy:Direct"].items.find((o) => o.id === 116))),
    restored: q.snapshot(116),
  };
}

// ═══ 8. A LIVE sidebar change, no reload, on a block that was only formatted ══════════════════
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("live-fill");
  p.mount(TEMPLATE, TOKENS_A, VER);
  p.bold(116, [0, 5]);
  const before = p.snapshot(116);
  p.refreshFills(TOKENS_B);
  out.liveFill = {
    before: before, after: p.snapshot(116),
    stored: JSON.parse(JSON.stringify(
      TW.getState().paragraph_overrides_all["epoxy:Direct"].items.find((o) => o.id === 116))),
  };
  // …and a block somebody TYPED in is still left alone by the same pass.
  const q = makePage("live-fill-typed");
  q.mount(TEMPLATE, TOKENS_A, VER);
  q.type(116, "Area: 5,200 SF plus cove");
  q.refreshFills(TOKENS_B);
  out.liveFillTyped = q.snapshot(116);

  // The case that needs the pristine check INSIDE refreshFillsInPlace, not the tw-fmt gate
  // outside it: formatted AND typed in, with the fill spans still THERE. The gate lets this one
  // through, so the baseline comparison is the only thing standing between the estimator's
  // words and the sidebar. Two shapes of it, because they fail differently: words added after
  // the fill, and the highlighted number itself overtyped.
  const r = makePage("live-fill-formatted-then-typed");
  r.mount(TEMPLATE, TOKENS_A, VER);
  r.bold(116, [0, 5]);
  r.append(116, " plus 60 LF cove");
  r.refreshFills(TOKENS_B);
  out.liveFillFormattedThenTyped = r.snapshot(116);

  const t = makePage("live-fill-overtyped-number");
  t.mount(TEMPLATE, TOKENS_A, VER);
  t.bold(116, [0, 5]);
  t.typeInFill(116, "epoxy_sf", "5,250");
  t.refreshFills(TOKENS_B);
  out.liveFillOvertypedNumber = t.snapshot(116);

  // TWICE, because the first re-fill has to leave the block able to take a second one. Without
  // the pristine baseline moving with the value it just wrote, the next serialise reads the
  // fresh number as a hand edit: the token tag is dropped from the stored runs and the fill
  // stops tracking the estimate from then on — a slower version of the same frozen number.
  const s = makePage("live-fill-twice");
  s.mount(TEMPLATE, TOKENS_A, VER);
  s.bold(116, [0, 5]);
  s.refreshFills(TOKENS_B);
  const mid = JSON.parse(JSON.stringify(
    TW.getState().paragraph_overrides_all["epoxy:Direct"].items.find((o) => o.id === 116)));
  s.refreshFills({ scope_notes: "Grind and coat.", epoxy_sf: "7,500" });
  out.liveFillTwice = {
    mid: mid, after: s.snapshot(116),
    stored: JSON.parse(JSON.stringify(
      TW.getState().paragraph_overrides_all["epoxy:Direct"].items.find((o) => o.id === 116))),
  };
}

// ═══ 9. TWO TABS on the same draft ═══════════════════════════════════════════════════════════
// Both editors are real, both share the one store. The second tab loaded BEFORE the first one
// formatted anything, which is what makes it dangerous: its DOM knows nothing about the runs.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const a = makePage("two-tabs-a");
  const b = makePage("two-tabs-b");
  a.mount(TEMPLATE, TOKENS_A, VER);
  b.mount(TEMPLATE, TOKENS_A, VER);
  const at = a.snapshot(115).text.indexOf("Grind");
  a.bold(115, [at, at + 5]);
  a.persist();
  // Tab B now edits an UNRELATED paragraph and persists. Its own document never had tab A's
  // formatting, so its collector cannot see it.
  b.type(116, "Area: 5,200 SF and cove");
  b.persist();
  const afterB = JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items));
  // Tab B then reloads and must show tab A's formatting.
  const b2 = makePage("two-tabs-b-reloaded");
  b2.mount(TEMPLATE, TOKENS_A, VER);
  b2.restore("epoxy", "Direct", TOKENS_A);
  out.twoTabs = { afterB: afterB, tabBSees: b2.snapshot(115) };
}

// ═══ 10. A TEMPLATE SWITCH mid-session ═══════════════════════════════════════════════════════
// Same page object, re-mounted for another template (what reloadForWorkType does in place).
// Epoxy's formatting must be untouched by the polish visit, and polish must not inherit it —
// the ids belong to one file.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("switch");
  p.mount(TEMPLATE, TOKENS_A, VER);
  const at = p.snapshot(115).text.indexOf("Grind");
  p.bold(115, [at, at + 5]);
  p.persist();
  const epoxyStored = JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items));

  // The polish template: same ids, different file, different version.
  const POLISH = [{ id: 115, text: "Polish scope:  {{scope_notes}}",
                    runs: [Object.assign({ text: "Polish scope:  {{scope_notes}}", bold: false }, FMT)] }];
  STORE.blob = Object.assign(TW.getState(), { work_type: "polish" });
  const q = makePage("switch-polish");
  q.mount(POLISH, TOKENS_A, "tv-polish-1");
  q.restore("polish", "Direct", TOKENS_A);
  const polishAfterRestore = q.snapshot(115);
  q.type(115, "Polish scope:  Diamond grind.");
  q.persist();
  const storeAfterPolish = JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all));

  // …and back to epoxy.
  STORE.blob = Object.assign(TW.getState(), { work_type: "epoxy" });
  const r = makePage("switch-back");
  r.mount(TEMPLATE, TOKENS_A, VER);
  r.restore("epoxy", "Direct", TOKENS_A);
  r.persist();
  out.templateSwitch = {
    epoxyStored: epoxyStored,
    polishAfterRestore: polishAfterRestore,
    keys: Object.keys(storeAfterPolish).sort(),
    polishItems: storeAfterPolish["polish:Direct"].items,
    backToEpoxy: r.snapshot(115),
    epoxyStillStored: JSON.parse(JSON.stringify(
      TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
  };
}

// ═══ 11. A draft saved BEFORE this feature existed ═══════════════════════════════════════════
// Entries with no `runs` key at all must restore exactly as they do today: the text comes back,
// the block goes dirty, and nothing gains formatting it never had.
{
  STORE.blob = Object.assign(JSON.parse(JSON.stringify(SEED)), {
    paragraph_overrides_all: {
      "epoxy:Direct": { template_version: VER, items: [{ id: 115, text: "Scope:  legacy text" }] },
    },
  });
  const p = makePage("legacy");
  p.mount(TEMPLATE, TOKENS_A, VER);
  p.restore("epoxy", "Direct", TOKENS_A);
  const restored = p.snapshot(115);
  const collected = p.collect();
  p.persist();
  out.legacy = {
    restored: restored, collected: collected,
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
  };
  // The legacy SINGLE-SLOT shape too (paragraph_overrides + _meta), which is what a draft in
  // flight right now actually looks like.
  STORE.blob = Object.assign(JSON.parse(JSON.stringify(SEED)), {
    paragraph_overrides: [{ id: 115, text: "Scope:  older still" }],
    paragraph_overrides_meta: { template_version: VER, work_type: "epoxy", audience: "Direct" },
  });
  const q = makePage("legacy-flat");
  q.mount(TEMPLATE, TOKENS_A, VER);
  q.restore("epoxy", "Direct", TOKENS_A);
  out.legacyFlat = { restored: q.snapshot(115), collected: q.collect() };
}

// ═══ 12. An entry from ANOTHER version of the same template is still refused ══════════════════
{
  STORE.blob = Object.assign(JSON.parse(JSON.stringify(SEED)), {
    paragraph_overrides_all: {
      "epoxy:Direct": { template_version: "tv-OLD", items: [
        { id: 115, text: "Scope:  stale", runs: [{ text: "Scope:  stale", bold: true }] }] },
    },
  });
  const p = makePage("stale-version");
  p.mount(TEMPLATE, TOKENS_A, VER);
  p.restore("epoxy", "Direct", TOKENS_A);
  const restored = p.snapshot(115);
  p.type(116, "Area: 5,200 SF and cove");
  p.persist();
  out.staleVersion = {
    restored: restored,
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
  };
}

// ═══ 13. An untouched document still ships NOTHING ═══════════════════════════════════════════
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("untouched");
  p.mount(TEMPLATE, TOKENS_A, VER);
  out.untouched = p.collect();
}

// ═══ 14. THE NUMBERED TERMS CLAUSES ══════════════════════════════════════════════════════════
// Two halves of one misunderstanding about ordered lists, and neither is visible to a source
// assertion: whether a clause is drawn as its NUMBER is renderBlock reading the block record,
// and whether a clause can be emptied is the delegated input handler, restoreEmptiedClause,
// setBlockContent and collectOverrides agreeing.
//
// CLAUSE_51 / CLAUSE_52 are the shape /api/proposal-template really returns for blocks 51 and 52
// of the Direct epoxy template — `list: true` (they carry w:numPr), `para.bullet: false`,
// `para.locked: true`, `para.marker` "1." / "2." — with the clause text shortened. The Python
// half re-derives the same fields off the live endpoint, so this fixture cannot rot into fiction.
const CLAUSE_FMT = { italic: null, underline: null, size_pt: 9.0, font: "Cambria", color: null };
const clause = (id, marker, lead, body) => ({
  id: id, text: lead + body, align: "justify", list: true,
  style: { name: "Normal", bold: true },
  para: { bullet: false, indent: 540, locked: true, marker: marker },
  runs: [Object.assign({ text: lead, bold: true }, CLAUSE_FMT),
         Object.assign({ text: body, bold: null }, CLAUSE_FMT)],
});
const CLAUSE_51 = clause(51, "1.", "Agreement.", " The Proposal of Treadwell, LLC.");
const CLAUSE_52 = clause(52, "2.", "Price and Payment Terms.", "  Customer shall pay Treadwell.");
// A clause record as a PRE-v6 browser holds it: same paragraph, `para` with no `marker` at all.
const CLAUSE_53_V5 = (() => {
  const c = clause(53, "3.", "Taxes.", "  Customer shall pay all taxes.");
  delete c.para.marker;
  return c;
})();
// Block 115 as the endpoint really reports it — `list: true` with a BULLET level under it. The
// earlier scenarios use it without those fields (they predate them); here the bullet row has to
// be the real shape, because "the clause stopped being a square and the WORK row still is one" is
// half of what this scenario claims.
const BULLET_115 = Object.assign({}, BLOCK_115,
  { list: true, para: { bullet: true, indent: 288, locked: false, marker: "" } });
const TERMS = [BULLET_115, CLAUSE_51, CLAUSE_52, CLAUSE_53_V5];

// 14a — how they are DRAWN. A red square in front of a clause that prints "1." is the bug.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("clause-render");
  p.mount(TERMS, TOKENS_A, VER);
  out.clauseRender = {
    clause: p.look(51), second: p.look(52), noMarker: p.look(53), workRow: p.look(115),
  };
}

// 14b — EMPTYING one. The estimator selects the clause and presses delete.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("clause-emptied");
  p.mount(TERMS, TOKENS_A, VER);
  p.type(51, "");
  const kept = p.look(51);
  const collected = p.collect();
  p.persist();
  const stored = TW.getState().paragraph_overrides_all["epoxy:Direct"].items;
  // …and then they carry on typing in the same clause, which is when the notice has stopped
  // being true. A real edit to the words is still a real edit.
  p.type(51, "Agreement.  The Proposal of Treadwell, LLC, as amended.");
  out.clauseEmptied = {
    kept: kept, collected: collected, stored: JSON.parse(JSON.stringify(stored)),
    neighbour: p.look(52),
    afterTyping: p.look(51), afterTypingCollected: p.collect(),
  };
}

// 14c — a lone newline, which is what a browser leaves behind when the last character goes.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("clause-newline");
  p.mount(TERMS, TOKENS_A, VER);
  p.type(51, "\n");
  out.clauseNewline = { kept: p.look(51), collected: p.collect() };
}

// 14d — a BULLETED WORK row can still be emptied. The rule is about clause numbers, not about
// making the editor read-only, and this is the behaviour that must not be caught by the guard.
{
  STORE.blob = JSON.parse(JSON.stringify(SEED));
  const p = makePage("work-row-emptied");
  p.mount(TERMS, TOKENS_A, VER);
  p.type(115, "");
  out.workRowEmptied = { look: p.look(115), collected: p.collect() };
}

// 14e — a draft SAVED while emptying a clause was possible. It restores through the real
// restorer, so a blank clause must not come back on screen while the .docx (which refuses it)
// prints the wording.
{
  STORE.blob = Object.assign(JSON.parse(JSON.stringify(SEED)), {
    paragraph_overrides_all: {
      "epoxy:Direct": { template_version: VER, items: [
        { id: 51, text: "", runs: [] },
        { id: 115, text: "Scope:  kept from the same draft" }] },
    },
  });
  const p = makePage("clause-legacy-blank");
  p.mount(TERMS, TOKENS_A, VER);
  p.restore("epoxy", "Direct", TOKENS_A);
  const restored = p.look(51);
  const collected = p.collect();
  p.persist();
  out.clauseLegacyBlank = {
    restored: restored, collected: collected, workRow: p.look(115),
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
  };
}

// 14f — the same stale draft, but stored as `runs: [{text: ""}]`. THE SHAPE THAT DOES NOT HEAL
// ITSELF: a non-empty array of nothing. The restore skips it, so the DOM never reports the id at
// all — and preserveRichOverrides then treats the array as formatting worth rescuing and pushes
// the whole entry back. Left alone, that entry is re-sent on every persist for the life of the
// project and only the writer's refusal keeps it out of the document.
{
  STORE.blob = Object.assign(JSON.parse(JSON.stringify(SEED)), {
    paragraph_overrides_all: {
      "epoxy:Direct": { template_version: VER, items: [
        { id: 51, text: "", runs: [{ text: "", bold: true }] }] },
    },
  });
  const p = makePage("clause-blank-runs");
  p.mount(TERMS, TOKENS_A, VER);
  p.restore("epoxy", "Direct", TOKENS_A);
  const collected = p.collect();
  p.persist();
  out.clauseBlankRuns = {
    restored: p.look(51), collected: collected,
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
  };
}

// 14g — blank RUNS beside non-blank `text`. The two halves of an entry disagree, and the restore
// renders the RUNS, so the runs are what decide whether the clause ends up empty. An entry judged
// on its `text` alone reads as harmless here and blanks the clause on screen.
{
  STORE.blob = Object.assign(JSON.parse(JSON.stringify(SEED)), {
    paragraph_overrides_all: {
      "epoxy:Direct": { template_version: VER, items: [
        { id: 51, text: "Agreement. The Proposal of Treadwell, LLC.", runs: [{ text: "" }] }] },
    },
  });
  const p = makePage("clause-blank-runs-live-text");
  p.mount(TERMS, TOKENS_A, VER);
  p.restore("epoxy", "Direct", TOKENS_A);
  const restored = p.look(51);
  p.persist();
  out.clauseRunsDisagree = {
    restored: restored,
    stored: JSON.parse(JSON.stringify(TW.getState().paragraph_overrides_all["epoxy:Direct"].items)),
  };
}

console.log(JSON.stringify(out));
