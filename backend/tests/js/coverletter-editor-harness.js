"use strict";
/* The optional cover letter's editor, EXECUTED.
 *
 * WHY THIS HARNESS LIFTS ALMOST NOTHING. Every other doc-editor harness in this folder pulls
 * named functions out of proposal-review.js by regex, because that file has no module boundary to
 * get hold of. coverletter-editor.js does: it is one IIFE that publishes `window.TWCoverLetter`,
 * so the honest thing is to run the WHOLE shipped file in a sandbox and drive it through the
 * surface the page itself uses. Nothing here can pass while the file is broken in a way the page
 * would notice, which a lift cannot promise — a lifted function is compiled in isolation, so an
 * unbound identifier three functions away stays invisible. That is the STAGE_CREATED failure of
 * 2026-08-12, and it took the production board down with every source assertion green.
 *
 * ONE THING IS LIFTED, on purpose: `effectiveWorkType` from proposal-review.js. The cover letter
 * DUPLICATES that inference rather than calling it (see the header of coverletter-editor.js — the
 * proposal's copy is regex-lifted by five harnesses, and a lifted function that grows a second
 * caller becomes a dependency any of them can break). A duplicate with nothing watching it is a
 * fork waiting to happen, so both are run over the same table of draft states and asserted to
 * agree. That is the whole point of the lift: it is the anti-drift test, not a shortcut.
 *
 * THE DOM SHIM IS DELIBERATELY PARTIAL, for the reason doc-editor-harness.js states: jsdom would
 * let a missing binding hide behind a stub. What is modelled is what this file actually touches.
 *
 * Usage: node coverletter-editor-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const FRONTEND = process.argv[2];
// Normalized to LF: the repo checks the frontend out CRLF on Windows and the lift below anchors
// on "\n  " indentation. A stray CR would make the lifted source subtly different from the
// shipped source, which is the one thing a harness must never allow.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
const CL_SRC = read(path.join(FRONTEND, "js", "coverletter-editor.js"));
/* The shared run maths. coverletter-editor.js reads it as `window.TWFmt` and, when it is absent,
 * every formatting press becomes a silent no-op -- the ribbon still lights up and nothing happens,
 * which is precisely the bug under test in scenario 13. proposal-review.html loads this first
 * (`:811`, before `:817`), so the harness has to as well or it would "prove" the fix on a page
 * that could not work. */
const FMT_SRC = read(path.join(FRONTEND, "js", "proposal-format-core.js"));
const PR_SRC = read(path.join(FRONTEND, "js", "proposal-review.js"));

function liftFn(src, name, where) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from " + where + " — rewrite this harness, don't delete it");
  const open = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

// ── the smallest DOM this file touches ───────────────────────────────────────
const Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
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
  constructor(v) { this.nodeType = Node.TEXT_NODE; this.nodeValue = String(v); this.parentNode = null; }
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
    this.hidden = false;
    this.spellcheck = true;
    this.contentEditable = "inherit";
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
  /** `isConnected` decides whether the async letterhead fetch is still allowed to paint. Real,
   *  not a constant: a render that replaced the page while the artwork was in flight must not
   *  have the old page's image dropped into it. */
  get isConnected() {
    let el = this;
    while (el.parentNode) el = el.parentNode;
    return el._isRoot === true;
  }
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  prepend(c) { c.parentNode = this; this.childNodes.unshift(c); return c; }
  get textContent() {
    return this.childNodes.map((n) => (n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent)).join("");
  }
  set textContent(v) {
    this.childNodes = [];
    if (String(v) !== "") this.appendChild(new Text(v));
  }
  set innerHTML(html) {
    this.childNodes = [];
    const stack = [this];
    const re = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[\w-]+="[^"]*")*)\s*\/?>|([^<]+)/g;
    let m;
    while ((m = re.exec(html))) {
      const top = stack[stack.length - 1];
      if (m[1]) { if (stack.length > 1) stack.pop(); }
      else if (m[2]) {
        const el = new El(m[2], this._doc);
        for (const a of m[3].matchAll(/([\w-]+)="([^"]*)"/g)) {
          const v = unesc(a[2]);
          el.attrs[a[1]] = v;
          if (a[1] === "class") el.className = v;
          else if (a[1] === "style") el.style = parseStyle(v);
          else if (a[1].startsWith("data-")) {
            el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
          }
        }
        top.appendChild(el);
        if (!VOID.has(el.tagName)) stack.push(el);
      } else if (m[4] !== undefined) top.appendChild(new Text(unesc(m[4])));
    }
  }
  get innerHTML() {
    return this.childNodes.map((n) => {
      if (n.nodeType === Node.TEXT_NODE) return n.nodeValue;
      const cls = n.className ? ' class="' + n.className + '"' : "";
      const tok = n.attrs["data-token"] ? ' data-token="' + n.attrs["data-token"] + '"' : "";
      const t = n.tagName.toLowerCase();
      return VOID.has(n.tagName) ? "<" + t + ">" : "<" + t + cls + tok + ">" + n.innerHTML + "</" + t + ">";
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
    while (el) { if (el.nodeType === Node.ELEMENT_NODE && matches(el, sel)) return el; el = el.parentNode; }
    return null;
  }
  contains(other) { let el = other; while (el) { if (el === this) return true; el = el.parentNode; } return false; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; }
  /* A REAL capture-then-bubble walk, honouring stopPropagation. Both halves are load-bearing:
   * the cover-letter interceptor sits on `#fmt-ribbon`, which is the PARENT of the formatting row
   * AND of the document tabs, and it works by catching a press on the way DOWN, before the
   * proposal's own handlers on the row. A harness that only bubbles runs those handlers first and
   * can never see the difference; a harness whose stopPropagation is a no-op can never see an
   * over-broad interceptor eat the Proposal | Cover letter tab click. Both are real bugs this
   * file exists to catch, so the walk has to be real. */
  addEventListener(type, f, capture) {
    const k = capture === true || (capture && capture.capture === true) ? "!" + type : type;
    (this._listeners[k] = this._listeners[k] || []).push(f);
  }
  dispatchEvent(e) {
    e.target = this;
    const path = [];
    for (let cur = this; cur; cur = cur.parentNode) path.push(cur);
    // Down the tree first, outermost node inward, then back out again. stopPropagation ends the
    // walk after the CURRENT node's listeners have all run, not part-way through them.
    const fire = (node, key) => {
      for (const f of (node._listeners[key] || []).slice()) f(e);
      return !e._stopped;
    };
    for (let i = path.length - 1; i >= 0; i--) if (!fire(path[i], "!" + e.type)) return true;
    for (let i = 0; i < path.length; i++) if (!fire(path[i], e.type)) return true;
    return true;
  }
}

class Ev {
  // `preventDefault` and `stopPropagation` are no-ops that must EXIST: the ribbon interceptor
  // calls both on every press it takes, so an Ev without them throws a TypeError inside the
  // handler and the press looks like it was ignored -- which is the very bug under test.
  constructor(type, opts) {
    this.type = String(type);
    this.bubbles = !!(opts && opts.bubbles);
    this.target = null;
    this.defaultPrevented = false;
    this.key = (opts && opts.key) || undefined;
    this.ctrlKey = !!(opts && opts.ctrlKey);
    this.metaKey = !!(opts && opts.metaKey);
    this.altKey = !!(opts && opts.altKey);
  }
  preventDefault() { this.defaultPrevented = true; }
  // Honoured for real by dispatchEvent above: a handler that calls this ends the walk, so an
  // over-broad interceptor really does swallow the click it should have left alone.
  stopPropagation() { this._stopped = true; }
}

// ── the fixtures ─────────────────────────────────────────────────────────────
/* A letter with the DATE anchored in its own text box over the letterhead artwork (block 0,
 * txbx 0), the body flowing beneath (blocks 1..3).
 *
 * THIS IS NO LONGER A SHAPE THE ENDPOINT SERVES. It was Kyle's — his example letter floats the
 * date in one anchored box — and the seven templates copied it verbatim until 2026-09-04, when
 * Hanz asked for the date off every format. Removing it took the only text box out of the
 * letters, so `describe_template` now returns `boxes: []` for all seven (asserted at the file by
 * `test_cover_letter::test_a_letter_is_pure_flow_with_no_floating_box`).
 *
 * It is kept, and kept as the default, on purpose: the editor's box branch is still live code,
 * and it is the branch a template REGAINS the moment Kyle's letterhead changes or a box is added
 * back. Deleting the fixture would delete the only coverage of it — including the z-order bug
 * below, which only a click found. `GEO_FLOW` + `BODY` is the shape a real letter has today. */
const DATE_BLOCK = { id: 0, text: "{{proposal_date}}", txbx: 0, in_txbx: true, in_block: null,
                     style: { name: null, bold: false }, align: null, list: false, para: null, runs: [] };
const BODY = [
  { id: 1, text: "{{job_name}}", txbx: null, in_txbx: false, in_block: null,
    style: { name: null, bold: true }, align: null, list: false, para: null, runs: [] },
  { id: 2, text: "Thank you for the opportunity to bid {{job_name}}.", txbx: null, in_txbx: false,
    in_block: null, style: { name: null, bold: false }, align: null, list: false, para: null, runs: [] },
  { id: 3, text: "Sincerely,", txbx: null, in_txbx: false, in_block: null,
    style: { name: null, bold: false }, align: null, list: false, para: null, runs: [] },
];

/* THESE ARE OBSERVED PAYLOADS, NOT AN AGREED CONTRACT -- which is the one thing the header of
 * test_cover_letter_ui.py says this file could not offer. Every block below was dumped out of the
 * shipped templates in `backend/templates/CoverLetter/` by running the real
 * `proposal_writer._block_runs` and `para_props` over them, and the weights, slants, point sizes,
 * markers and indents are transcribed from that dump rather than guessed:
 *
 *   Direct/Epoxy.docx  [5] Materials / System:  bold label + plain value, numbered "1.", ind 720/360
 *                      [6] Area:               bold label + plain value, numbered "2."
 *                      [8] Options:            bold label + ITALIC instruction, numbered "4."
 *                      [16] TREADWELL | ...    bold name + plain rest, both 10pt not 11pt, no list
 *   Direct/Combo.docx  [5] Epoxy / Resinous Flooring:  ONE run, wholly bold, no list, no detail
 *   GC/Epoxy.docx      [3] Thanks for the opportunity  three runs, no bold anywhere
 *
 * The segments come with two invariants this editor leans on and `clRunsFor` re-checks:
 * they rejoin to `b.text`, and no {{token}} straddles a boundary.
 *
 * Those four labels are the four Hanz named. TWO CORRECTIONS TO THE BRIEFS this work was written
 * from, both worth recording because both were offered as things to protect:
 *
 *   · "A few things to note:" is NOT bold in any of the seven templates -- it is one plain run in a
 *     plain paragraph. The paragraph that IS wholly bold, and that a careless fix would flatten, is
 *     the Combo system heading ("Epoxy / Resinous Flooring:").
 *   · not one cover-letter paragraph is a BULLET. All seven templates number their labelled lines:
 *     `bullet: false`, `locked: true`, markers "1." upward, restarting per system on Combo. The red
 *     Wingdings square the editor drew was wrong on every letter and every line.
 *
 * `runs: []` is KEPT on the three fixtures above rather than replaced, because the flat path it
 * exercises is still live code for a response cached before the endpoint carried runs, and it is
 * the branch the guards below fall back into.
 *
 * WHY `style.bold` IS COMPUTED HERE AND NEVER TYPED IN. On the server it is
 * `any(r.bold for r in p.runs if r.bold is not None)` -- true the moment ONE run is bold. That is
 * the whole defect: every bullet with a bold label reports itself as a bold PARAGRAPH, and the
 * paragraph-level class then weights the details too. A fixture free to write `bold: false` on a
 * line whose label is bold could hide that by accident, so it is derived by the same rule. */
const R = (text, over) => Object.assign(
  { text: text, bold: null, italic: null, underline: null, size_pt: 11,
    font: "Zetta Serif", color: null }, over || {});
const SPACING = { before: null, after: null, line: null, line_rule: null, contextual: false };
/* A numbered label line, at the templates' real geometry: `w:ind left=720 hanging=360` puts the
 * text 36pt in and the number 18pt to the left of it. `applyGeom` writes both as inline styles,
 * which is what stops `.tw-num`'s own 9pt/18pt -- measured off the PROPOSAL's Terms level -- from
 * standing in for this file's numbers. */
const NUM = (marker) => ({ bullet: false, indent: 720, hanging: 360, first_line: null,
                           locked: true, marker: marker, spacing: SPACING });
const FLOW = { bullet: false, indent: 0, hanging: null, first_line: null, locked: false,
               marker: "", spacing: SPACING };
const P = (id, text, runs, over) => Object.assign(
  { id: id, text: text, txbx: null, in_txbx: false, in_block: null, align: null, list: false,
    para: FLOW, style: { name: null, bold: runs.some((r) => r.bold === true) }, runs: runs },
  over || {});

const LABEL_BODY = [
  // 1 · Direct/Epoxy [5]. THE LINE HE SCREENSHOTTED: the label bold up to and including the colon,
  // the detail plain. The detail is also the whole of a {{token}}, so this one line answers both
  // halves of the question -- is the label the only bold part, and did the yellow fill survive
  // being rendered a run at a time. Numbered "1.", not bulleted.
  P(1, "Materials / System: {{cover_system_line}}",
    [R("Materials / System: ", { bold: true, italic: false }),
     R("{{cover_system_line}}", { bold: false, italic: false })],
    { list: true, para: NUM("1.") }),
  // 2 · Direct/Epoxy [6]. The same line at its shortest, and the one with nothing but the
  // paragraph class standing between its detail half and 700: `bold: false` states no weight of
  // its own, because only what a run turns ON is emitted.
  P(2, "Area: {{work_areas}}",
    [R("Area: ", { bold: true, italic: false }),
     R("{{work_areas}}", { bold: false, italic: false })],
    { list: true, para: NUM("2.") }),
  // 3 · Direct/Epoxy [8]. The Options line, whose detail half is ITALIC in the template -- Kyle
  // italicises the instructions he leaves for the estimator. Real, and the reason italic had to
  // travel across with the weight: this line has rendered upright since the letter shipped.
  P(3, "Options: [OPTIONS - keep the lines that apply]",
    [R("Options: ", { bold: true, italic: false }),
     R("[OPTIONS - keep the lines that apply]", { bold: false, italic: true })],
    { list: true, para: NUM("4.") }),
  // 4 · Direct/Combo [5]. A SYSTEM HEADING: one run, wholly bold, not a list, no detail half and
  // nothing to split. It must stay bold in every character. The change is "prefer what the runs
  // say", not "stop bolding paragraphs" -- a fix that only ever removed weight would read as green
  // on the lines above and quietly flatten this one instead.
  P(4, "Epoxy / Resinous Flooring:",
    [R("Epoxy / Resinous Flooring:", { bold: true, italic: false })]),
  // 5 · the same heading with its run SPLIT IN TWO. Not in the file today; it is what Word leaves
  // behind the first time somebody edits one of these headings, and `_block_runs` reports one
  // segment per `w:r`. Both halves have to stay bold.
  P(5, "Polished Concrete:",
    [R("Polished ", { bold: true, italic: false }), R("Concrete:", { bold: true, italic: false })]),
  // 6 · GC/Epoxy [3]. A plain body sentence in three runs, no bold anywhere, so no class either
  // and nothing for the guard to put back. The fill still has to land. Numbered "3." so that the
  // marker is proven not to depend on the line having a bold label.
  P(6, "Thanks for the opportunity to bid on this {{job_name}} project!",
    [R("Thanks for the opportunity to bid on this ", { bold: false, italic: false }),
     R("{{job_name}}", { bold: false, italic: false }),
     R(" project!", { bold: false, italic: false })],
    { list: true, para: NUM("3.") }),
  // 7 · Direct/Epoxy [16]. The signature footer, and the empirical reason no point size is
  // emitted: the templates really do mix an 11pt body with a 10pt signature block, so restating
  // the runs' own sizes would visibly re-flow this paragraph on a page that is a to-scale preview
  // of a printed sheet. Absent means "inherit the template's own", which is what has always
  // happened here.
  P(7, "TREADWELL | 913.396.6216 | Olathe, KS",
    [R("TREADWELL", { bold: true, italic: false, size_pt: 10 }),
     R(" | 913.396.6216 | Olathe, KS", { bold: false, italic: false, size_pt: 10 })]),
];

/* The three ways run records are refused, each of them a real .docx rather than a defensive
 * edge case. All three keep a bold label in the record, so the paragraph-level class has to come
 * BACK on the two that fall through to flat rendering — a guard that refused the runs and dropped
 * the class as well would leave those paragraphs with no weight at all. */
const GUARD_BODY = [
  // 11 · runs that do not rejoin to the text. `_block_runs` invariant 1, and its own docstring
  // names the cause: hyperlink runs are not direct `w:r` children, so the walk sees less text than
  // the paragraph has.
  P(11, "Terms: see our website for the full conditions.", [R("Terms:", { bold: true })]),
  // 12 · a token STRADDLING a run boundary. Invariant 2 promises this cannot happen. Rendered a run
  // at a time it matches in neither half and prints itself raw at the estimator, which is exactly
  // the "nothing on the letter was substituted" complaint — so the guard sends it flat, where the
  // value lands and only the per-run weights are lost.
  P(12, "Bid for {{job_name}} today.",
    [R("Bid for {{job", { bold: true }), R("_name}} today.")]),
  // 13 · a token INSIDE a longer run: invariant 2 broken without a straddle. Usable, so it takes
  // the run path — and the fill still has to land, which is why each run goes through the same
  // token walk the flat path uses rather than being tested for being a whole token.
  P(13, "Attn: {{job_name}} team", [R("Attn:", { bold: true }), R(" {{job_name}} team")]),
  // 14 · A GENUINE WORD BULLET, which no cover-letter template contains today. The red square
  // branch stays reachable and stays tested: a level whose definition cannot be read reports no
  // marker, and a square is the best guess left for a line we know is a list and cannot number.
  P(14, "A bulleted line, if a template ever grows one", [R("A bulleted line, if a template ever grows one")],
    { list: true, para: Object.assign({}, FLOW, { bullet: true, marker: "" }) }),
];

const PAGE = { w_pt: 612, h_pt: 792, margin: { top: 72, left: 90, right: 90, bottom: 72 } };
const ART = [{ name: "image1.png", para_index: 0, x_pt: 0, y_pt: 0, w_pt: 612, h_pt: 792 }];

const GEO_POSITIONED = { page: PAGE, images: ART, boxes: [{ id: 0, x_pt: 396, y_pt: 158.4, w_pt: 144, h_pt: 18 }] };
// A letter with no boxes at all — which is what every one of the seven templates is since
// 2026-09-04. Still a first-class layout, not a failure mode: see
// `test_a_template_with_no_boxes_is_a_layout_and_not_a_failure`, which is now the scenario that
// matches production rather than a defensive edge case.
const GEO_FLOW = { page: PAGE, images: ART, boxes: [] };

const TOKENS = { proposal_date: "8/26/26", job_name: "Olathe Fire Station 4",
                 cover_system_line: "Epoxy, orange-peel texture",
                 work_areas: "12,000 SF of warehouse" };
const VER_A = "cl-epoxy-1";
const VER_B = "cl-epoxy-2";

// ── one sandboxed page ───────────────────────────────────────────────────────
/** A whole cover-letter editor over one store. `seed` is the draft blob it starts from. */
function makePage(seed, opts) {
  opts = opts || {};
  const STORE = { blob: JSON.parse(JSON.stringify(seed || {})) };
  const fetches = [];
  const idleCalls = [];
  const timers = new Map();
  let nextTimer = 1;

  const doc = { readyState: "complete", hidden: false, _listeners: {} };
  const byId = new Map();
  doc.createElement = (t) => new El(t, doc);
  doc.getElementById = (id) => byId.get(id) || null;
  doc.addEventListener = (t, f) => { (doc._listeners[t] = doc._listeners[t] || []).push(f); };
  doc.body = new El("body", doc);
  doc.body._isRoot = true;
  doc.querySelectorAll = (sel) => doc.body.querySelectorAll(sel);
  doc.querySelector = (sel) => doc.body.querySelector(sel);
  doc.createTextNode = (v) => new Text(v);
  // A Range that can be built and set but NOT cloned, on purpose. `clSelectionRange` measures a
  // real selection by cloning the live range and dropping two marker characters at its ends; a
  // fake DOM cannot honestly do that, so the honest thing is to let it throw inside its own try
  // and come back null. That is the collapsed-caret path -- "the caret is resting in this line,
  // so the press means the whole line" -- which is what an estimator who clicks and presses B
  // actually does, and it is the path a stubbed-out cloneRange would quietly skip.
  doc.createRange = () => ({ setStart: () => {}, setEnd: () => {} });

  // The three elements the page provides. Real, and mounted in the body, so `isConnected` and
  // the class toggles mean what they mean in the browser.
  const mk = (id, tag) => { const e = new El(tag || "div", doc); e.attrs.id = id; byId.set(id, e); doc.body.appendChild(e); return e; };
  const docSurface = mk("doc-surface");
  const surface = mk("cl-surface");
  surface.classList.add("cl-offstage");
  // #fmt-ribbon is the HOST: the formatting row AND the Proposal | Cover letter tabs both live
  // inside it. That containment is the whole reason the letter can intercept presses on the host
  // -- and the whole reason the interceptor has to scope itself to `.tw-fmtbar`, because an
  // unscoped one would swallow the tab clicks and strand the estimator on one document. Both
  // halves are only testable if the tabs really are children of the ribbon here.
  const ribbon = mk("fmt-ribbon");
  const tabs = new El("div", doc);
  tabs.attrs.id = "doc-tabs";
  byId.set("doc-tabs", tabs);
  ribbon.appendChild(tabs);
  tabs.hidden = true;
  const proposalTab = new El("button", doc);
  proposalTab.className = "tab active";
  proposalTab.dataset.doc = "proposal";
  const coverTab = new El("button", doc);
  coverTab.className = "tab";
  coverTab.dataset.doc = "cover";
  tabs.appendChild(proposalTab);
  tabs.appendChild(coverTab);
  const toggle = mk("cl-toggle", "input");
  toggle.type = "checkbox";
  toggle.checked = false;
  // The formatting row itself, in the state the proposal leaves it in the moment it lets go of
  // its paragraph: idle, and every control DISABLED. That disabled flag is not decoration -- a
  // disabled button dispatches no click at all, so interception alone could never have fixed
  // this. Starting them enabled here would hide exactly the half that was missing.
  const fmtBar = new El("div", doc);
  fmtBar.className = "tw-fmtbar tw-fmtbar-idle";
  const fmtButtons = {};
  ["bold", "italic", "underline", "reset"].forEach((k) => {
    const b = new El("button", doc);
    b.dataset.fmt = k;
    b.disabled = true;
    fmtBar.appendChild(b);
    fmtButtons[k] = b;
  });
  const sizeBox = new El("input", doc);
  sizeBox.dataset.fmt = "size";
  sizeBox.disabled = true;
  sizeBox.value = "";
  fmtBar.appendChild(sizeBox);
  // A paragraph control, which a cover-letter block has no equivalent of. It must end up hidden
  // rather than enabled-and-inert.
  const paraBtn = new El("button", doc);
  paraBtn.dataset.para = "bullet";
  fmtBar.appendChild(paraBtn);
  ribbon.appendChild(fmtBar);

  // The caret, as a text node. `null` means "nothing selected anywhere", which is what the page
  // looks like before anyone has clicked into a paragraph.
  let caret = null;

  const win = {
    Node, console, JSON, Promise, Map, Set, Array, Object, String, Number, Boolean, Error,
    RegExp, Date, Math, FileReader: null,
    document: doc,
    Event: Ev,
    // Deliberately WITHOUT cloneRange -- see doc.createRange above.
    getSelection: () => ({
      rangeCount: caret ? 1 : 0,
      getRangeAt: () => ({ startContainer: caret, endContainer: caret }),
      removeAllRanges: () => {},
      addRange: () => {},
    }),
    setTimeout: (f, ms) => { const id = nextTimer++; timers.set(id, f); return id; },
    clearTimeout: (id) => { timers.delete(id); },
    // The draft store. getState hands back a COPY and setState merges into the store without
    // touching the caller's snapshot — shared.js's real contract, and the reason the editor reads
    // every key live instead of off a load-time snapshot.
    TW: {
      getState: () => JSON.parse(JSON.stringify(STORE.blob)),
      setState: (partial) => {
        STORE.blob = Object.assign(JSON.parse(JSON.stringify(STORE.blob)), partial || {});
        return STORE.blob;
      },
      authHeaders: () => ({ Authorization: "Bearer test" }),
    },
    TWAuth: { ready: Promise.resolve() },
    // The proposal editor's token resolver, borrowed by the letter. Present here because it is
    // present on the page; the "absent" case gets its own scenario below.
    //
    // SHAPED LIKE THE REAL ONE ON PURPOSE: `computeTokenValues(mergedValues)` in proposal-review.js
    // dereferences its argument immediately (`mergedValues.polish_sf`, ...), so calling it with
    // none throws. A stub that ignored its argument and always returned TOKENS could not tell a
    // caller that passed the draft's real values apart from one that called it blind — which is
    // exactly the bug that shipped every `{{token}}` raw into the letter (clTokens() swallowed the
    // throw and came back with `{}`). This stub throws the same way and echoes back the job_name
    // it was actually handed, so scenario 12 below can prove which one happened.
    computeTokenValues: opts.noTokens ? undefined : (mergedValues) => {
      void mergedValues.polish_sf; // throws TypeError when called with no argument, like the real one
      return Object.assign({}, TOKENS, mergedValues.job_name ? { job_name: mergedValues.job_name } : {});
    },
    // The formatting ribbon's "aimed at nothing". Spied rather than stubbed away: the whole
    // reason it is called is that the ribbon keeps its target after focus leaves, and a press on
    // Bold while the letter is in front would otherwise format a proposal paragraph off-screen.
    idleFmtBar: () => { idleCalls.push(1); },
    fetch: (url, init) => {
      fetches.push(String(url));
      if (String(url).indexOf("/media") >= 0) {
        return Promise.resolve({ ok: true, status: 200, blob: () => Promise.resolve({ _png: true }) });
      }
      if (opts.templateStatus && opts.templateStatus !== 200) {
        return Promise.resolve({ ok: false, status: opts.templateStatus });
      }
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({
          work_type: "epoxy", template_name: "Epoxy.docx",
          template_version: opts.version || VER_A,
          geometry: opts.geometry || GEO_POSITIONED,
          blocks: opts.blocks || [DATE_BLOCK].concat(BODY),
        }),
      });
    },
  };
  // A FileReader that resolves to a data: URI, because the letterhead MUST be a data: URI — the
  // tool's CSP is an nginx $host map and its img-src does not carry blob: on every host, which is
  // how no attachment photo rendered on production for weeks.
  win.FileReader = function () {
    this.readAsDataURL = () => { this.result = "data:image/png;base64,AAAA"; setTimeout0(() => this.onload && this.onload()); };
  };
  const microtasks = [];
  function setTimeout0(f) { microtasks.push(f); }

  win.window = win;
  win.globalThis = win;
  vm.createContext(win);
  vm.runInContext(FMT_SRC, win, { filename: "proposal-format-core.js" });
  vm.runInContext(CL_SRC, win, { filename: "coverletter-editor.js" });

  const flushMicro = async () => {
    for (let i = 0; i < 40; i++) { while (microtasks.length) microtasks.shift()(); await Promise.resolve(); }
  };

  return {
    win, STORE, fetches, idleCalls, surface, docSurface, tabs, toggle, proposalTab, coverTab,
    CL: () => win.TWCoverLetter,
    /** Every pending debounce, run now. The debounce itself is not what is under test; what is
     *  written is. A real timer would make every assertion below a race. */
    flush: () => { const fs2 = Array.from(timers.values()); timers.clear(); fs2.forEach((f) => f()); },
    settle: flushMicro,
    /** Tick the checkbox the way an estimator does — through the real `change` listener, not by
     *  calling setEnabled, so the wiring is under test too. */
    async tick(on) {
      toggle.checked = !!on;
      toggle.dispatchEvent(new Ev("change", { bubbles: true }));
      await flushMicro();
    },
    /** Type into one paragraph, through the real delegated `input` handler. */
    type(id, text) {
      const el = surface.querySelector('.tw-block[data-id="' + id + '"]');
      if (!el) throw new Error("no block " + id + " on screen");
      el.textContent = text;
      el.dispatchEvent(new Ev("input", { bubbles: true }));
      return el;
    },
    ribbon, fmtBar, fmtButtons, sizeBox, paraBtn,
    /** Put the caret in a paragraph the way a click does, and let the page hear about it. There
     *  is no focus event to lean on here: the editing host is the page, not the paragraph, so
     *  `selectionchange` is the only signal that the ribbon should re-aim. */
    caretIn(id) {
      const el = surface.querySelector('.tw-block[data-id="' + id + '"]');
      if (!el) throw new Error("no block " + id + " on screen");
      const firstText = (n) => {
        for (const c of n.childNodes) {
          if (c.nodeType === Node.TEXT_NODE) return c;
          const deep = firstText(c);
          if (deep) return deep;
        }
        return null;
      };
      caret = firstText(el);
      if (!caret) { caret = new Text(""); el.appendChild(caret); }
      (doc._listeners.selectionchange || []).slice().forEach((f) => f());
      return el;
    },
    /** Press one ribbon button, from the button, so the whole listener chain runs. */
    press(key) {
      fmtButtons[key].dispatchEvent(new Ev("click", { bubbles: true }));
    },
    /** The same request made with the keyboard, from the surface, where the letter listens.
     *  Returns the event so the caller can read whether the default was prevented -- an unhandled
     *  Ctrl+B is not inert in a contenteditable, it is the browser applying its OWN bold. */
    key(k, opts) {
      const e = new Ev("keydown", Object.assign({ bubbles: true, ctrlKey: true, key: k }, opts || {}));
      surface.dispatchEvent(e);
      return e;
    },
    /** Is a block's stored override formatted, and how? Reads what collect() actually emits. */
    override(id) {
      const all = win.TWCoverLetter.collect();
      return all[String(id)] || null;
    },
    look(id) {
      const el = surface.querySelector('.tw-block[data-id="' + id + '"]');
      if (!el) return null;
      return { text: el.textContent, cls: el.className, editable: el.contentEditable,
               boxed: !!el.closest(".tw-txbx") };
    },
    /** The block element itself, for the one thing only identity can answer: whether a press
     *  REPLACED the paragraph or only rewrote its children. */
    el(id) { return surface.querySelector('.tw-block[data-id="' + id + '"]'); },
    /** WHAT THE PARAGRAPH LOOKS LIKE, resolved the way the browser resolves it: every stretch of
     *  text with the weight, slant and underline that would actually paint it, and the token it
     *  sits inside.
     *
     *  The cascade is the point. `styles.css:1253` is `.tw-block.tw-bold { font-weight: 700 }`
     *  with no !important, so an inline weight on an ancestor span outranks it — and text with NO
     *  inline weight above it inherits the class. That second half is where the whole defect
     *  lives: a reading that merely counted `<span>`s, or that checked the spans it found were
     *  right, would call this fixed while every detail half still painted bold off the class. So
     *  `bold: null` from the walk resolves to the CLASS, and the class is reported on its own line
     *  as well, which is what lets the Python side name which of the two halves regressed. */
    painted(id) {
      const el = surface.querySelector('.tw-block[data-id="' + id + '"]');
      if (!el) return null;
      const cls = el.classList.contains("tw-bold");
      const out = [];
      const walk = (n, st) => {
        for (const c of n.childNodes) {
          if (c.nodeType === Node.TEXT_NODE) {
            if (c.nodeValue === "") continue;
            out.push({ text: c.nodeValue, bold: st.bold === null ? cls : st.bold,
                       italic: st.italic === true, underline: st.underline === true,
                       token: st.token });
            continue;
          }
          if (c.nodeType !== Node.ELEMENT_NODE) continue;
          const s = c.style || {};
          const deco = s.textDecorationLine || s.textDecoration || "";
          walk(c, {
            bold: s.fontWeight ? Number(s.fontWeight) >= 600 : st.bold,
            italic: s.fontStyle ? s.fontStyle === "italic" : st.italic,
            underline: deco ? String(deco).indexOf("underline") >= 0 : st.underline,
            token: (c.attrs && c.attrs["data-token"]) || st.token,
          });
        }
      };
      walk(el, { bold: null, italic: null, underline: null, token: null });
      return { cls: cls, runs: out };
    },
    /** Every inline font-size the letter emitted. Must be empty -- see the footer fixture. */
    inlineSizes() {
      return surface.querySelectorAll("span").map((s) => (s.style && s.style.fontSize) || "")
        .filter((v) => !!v);
    },
    /** The list treatment one paragraph actually got: which of the two classes, and what the
     *  marker prints. `.tw-num::before` renders `attr(data-marker)`, so a missing attribute is a
     *  numbered line with no number on it. */
    listLook(id) {
      const el = surface.querySelector('.tw-block[data-id="' + id + '"]');
      if (!el) return null;
      return { num: el.classList.contains("tw-num"), li: el.classList.contains("tw-li"),
               list: el.classList.contains("tw-list"),
               marker: (el.attrs && el.attrs["data-marker"]) || null };
    },
    /** The same reading, boiled down to the question that was asked: which stretches are bold. */
    boldParts(id) {
      const p = this.painted(id);
      return p ? p.runs.filter((r) => r.bold).map((r) => r.text) : null;
    },
    plainParts(id) {
      const p = this.painted(id);
      return p ? p.runs.filter((r) => !r.bold).map((r) => r.text) : null;
    },
  };
}

// ── the run ──────────────────────────────────────────────────────────────────
const out = {};

(async () => {
  // ══ 1 · OFF by default, and off means off ══════════════════════════════════
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    out.defaultOff = {
      checked: p.toggle.checked,
      tabsHidden: p.tabs.hidden,
      fetched: p.fetches.length,
      surfaceEmpty: p.surface.children.length === 0,
      payload: p.CL().payloadFields(),
      stored: p.STORE.blob.cover_letter_enabled,
    };
  }

  // ══ 2 · ON renders the real template, positioned ═══════════════════════════
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    await p.tick(true);
    await p.settle();
    const page = p.surface.querySelector(".cl-page");
    const box = p.surface.querySelector(".tw-txbx");
    const body = p.surface.querySelector(".cl-body");
    out.positioned = {
      url: p.fetches[0],
      tabsHidden: p.tabs.hidden,
      pageEditable: page ? page.contentEditable : null,
      boxes: p.surface.querySelectorAll(".tw-txbx").length,
      boxGeom: box ? { left: box.style.left, top: box.style.top, width: box.style.width } : null,
      boxEditable: box ? box.contentEditable : null,
      bodyEditable: body ? body.contentEditable : null,
      // THE PR #393 INVARIANT. Not one paragraph may be its own editing host: a browser selection
      // cannot cross a contenteditable boundary, so per-paragraph hosts break select-all,
      // cross-paragraph drag and undo, and draw a box round every line.
      blockHosts: p.surface.querySelectorAll(".tw-block")
        .filter((b) => b.contentEditable === "true").length,
      dateBlock: p.look(0),
      bodyBlock: p.look(2),
      // No drag machinery. The date sits where the letterhead was drawn for it; a handle offering
      // to move it would only offer a way to get it wrong.
      grips: p.surface.querySelectorAll(".tw-grip").length
             + p.surface.querySelectorAll(".tw-box-reset").length,
      // The letterhead, and that it arrived as a data: URI rather than a blob: one.
      art: (() => { const im = p.surface.querySelector(".tw-page-art");
                    return im ? String(im.src).slice(0, 11) : null; })(),
      artBehindText: (() => { const pg = p.surface.querySelector(".cl-page");
                              return pg && pg.children[0] ? pg.children[0].className : null; })(),
      // PAINT ORDER, which is DOM order here. `.cl-body` and `.tw-txbx` both carry `z-index: 1`
      // in styles.css, and with equal z-index the LATER sibling paints on top — so the body,
      // which is a full-page click surface, has to be appended BEFORE the boxes or it covers
      // every one of them and eats the click that should have landed in the date box. Reported
      // from live DOM order rather than asserted here so the Python side can name the failure.
      pageOrder: (() => { const pg = page;
                          return pg ? pg.children.map((c) => String(c.className || "")) : null; })(),
      mediaUrl: p.fetches.find((u) => u.indexOf("/media") >= 0) || null,
    };
  }

  // ══ 3 · a template with NO boxes still renders, and the PAGE is the host ═══
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" },
                       { geometry: GEO_FLOW, blocks: BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    const page = p.surface.querySelector(".cl-page");
    out.flow = {
      pageEditable: page ? page.contentEditable : null,
      boxes: p.surface.querySelectorAll(".tw-txbx").length,
      blocks: p.surface.querySelectorAll(".tw-block").length,
      blockHosts: p.surface.querySelectorAll(".tw-block").filter((b) => b.contentEditable === "true").length,
      padded: page ? page.style.padding : null,
    };
  }

  // ══ 4 · an edit reaches the draft in the backend's own shape ═══════════════
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    await p.tick(true);
    await p.settle();
    const before = JSON.parse(JSON.stringify(p.STORE.blob.cover_letter_paragraph_overrides || {}));
    const el = p.type(2, "Thanks for the chance to bid this one.");
    p.flush();
    out.edit = {
      beforeEmpty: Object.keys(before).length === 0,
      dirty: el.classList.contains("tw-dirty"),
      flat: p.STORE.blob.cover_letter_paragraph_overrides,
      keyed: p.STORE.blob.cover_letter_paragraph_overrides_all,
      meta: p.STORE.blob.cover_letter_paragraph_overrides_meta,
      version: p.STORE.blob.cover_letter_template_version,
      payload: p.CL().payloadFields(),
      // The token was FILLED before it was compared, so an untouched paragraph is not an edit.
      untouchedNotSent: !Object.prototype.hasOwnProperty.call(
        p.STORE.blob.cover_letter_paragraph_overrides, "1"),
    };
  }

  // ══ 4b · what a PASTE leaves behind ════════════════════════════════════════
  /* Nobody types a cover letter from scratch — they paste a sentence out of Word, and what lands
   * in the host is markup: a <b>, a <br> for the line break, an &nbsp; where Word had a space.
   * The backend field is `text`, a plain string that goes straight into a .docx run, so anything
   * that is not plain text here is a literal "<b>" printed in a customer-facing letter. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    await p.tick(true);
    await p.settle();
    const el = p.surface.querySelector('.tw-block[data-id="2"]');
    el.innerHTML = 'We are <b>pleased</b> to bid<br>this&nbsp;project.';
    el.dispatchEvent(new Ev("input", { bubbles: true }));
    p.flush();
    out.paste = { saved: p.STORE.blob.cover_letter_paragraph_overrides["2"] };
  }

  // ══ 5 · the audience dimension: two letters, two entries, neither lost ═════
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.type(2, "Direct wording.");
    p.flush();
    // The estimator switches the proposal's audience. Same work type, DIFFERENT template file.
    p.win.TW.setState({ audience: "GC" });
    await p.CL().load(true);
    await p.settle();
    p.type(2, "GC wording.");
    p.flush();
    out.audience = {
      keys: Object.keys(p.STORE.blob.cover_letter_paragraph_overrides_all).sort(),
      direct: p.STORE.blob.cover_letter_paragraph_overrides_all["epoxy:Direct"],
      gc: p.STORE.blob.cover_letter_paragraph_overrides_all["epoxy:GC"],
      urls: p.fetches.filter((u) => u.indexOf("coverletter-template?") >= 0),
      // Coming back to Direct shows the Direct wording again, not the GC one.
      backToDirect: await (async () => {
        p.win.TW.setState({ audience: "Direct" });
        await p.CL().load(true);
        await p.settle();
        return p.look(2).text;
      })(),
    };
  }

  // ══ 6 · a saved edit belongs to ONE template file ══════════════════════════
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.type(2, "Wording from before the deploy.");
    p.flush();
    const stored = JSON.parse(JSON.stringify(p.STORE.blob.cover_letter_paragraph_overrides_all));
    // Same draft, new .docx on disk: every block id may now point at a different paragraph.
    const q = makePage(p.STORE.blob, { version: VER_B });
    await q.settle();
    await q.tick(true);
    await q.settle();
    // …and the matching-version case, so the gate is shown to be a gate and not a wall.
    const r = makePage(p.STORE.blob, { version: VER_A });
    await r.settle();
    await r.tick(true);
    await r.settle();
    out.versionGate = {
      storedUnder: Object.keys(stored),
      staleReplayed: q.look(2).text,
      staleDirty: q.look(2).cls.indexOf("tw-dirty") >= 0,
      matchingReplayed: r.look(2).text,
      matchingDirty: r.look(2).cls.indexOf("tw-dirty") >= 0,
    };
  }

  // ══ 7 · turning it off keeps the words ═════════════════════════════════════
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.type(2, "Wording worth keeping.");
    p.flush();
    await p.tick(false);
    await p.settle();
    const off = {
      enabled: p.STORE.blob.cover_letter_enabled,
      payload: p.CL().payloadFields(),
      kept: p.STORE.blob.cover_letter_paragraph_overrides_all["epoxy:Direct"],
      tabsHidden: p.tabs.hidden,
      docOffstage: p.docSurface.classList.contains("cl-offstage"),
    };
    await p.tick(true);
    await p.settle();
    out.offKeepsEdits = Object.assign(off, { backOn: p.look(2).text });
  }

  // ══ 8 · the switch, and letting go of the proposal paragraph ═══════════════════════
  const look = (p) => ({ doc: p.docSurface.classList.contains("cl-offstage"),
                         cl: p.surface.classList.contains("cl-offstage"),
                         proposalTab: p.proposalTab.className, coverTab: p.coverTab.className,
                         idled: p.idleCalls.length });
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    const before = look(p);
    // TICKING THE BOX SHOWS THE LETTER. A checkbox whose only visible effect is a tab strip
    // appearing somewhere else in the chrome is a checkbox people press twice and then untick
    // because "nothing happened". `idled` is the other half: the formatting ribbon keeps its
    // target after focus leaves it, and it is scoped to #doc-surface — so unless the switch aims
    // it at nothing, a press on Bold with the letter in front formats an off-screen proposal
    // paragraph. Nothing on screen would show that had happened.
    await p.tick(true);
    await p.settle();
    const onCover = look(p);
    // And the strip itself is wired — clicked, not called.
    p.proposalTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    const backOnProposal = look(p);
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    out.tabs = { before: before, onCover: onCover, backOnProposal: backOnProposal,
                 clickedBack: look(p) };
  }

  // ══ 8b · re-opening a draft that ALREADY has a letter opens on the PROPOSAL ══════
  /* The step is called "3 · Proposal". A draft that happens to carry a letter must not open on
   * the letter — the estimator came back for the bid. The letter warms up off-stage instead. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct", cover_letter_enabled: true });
    await p.settle();
    out.reopen = Object.assign(look(p), { checked: p.toggle.checked, tabsHidden: p.tabs.hidden,
                                          warmed: p.fetches.length > 0 });
  }

  // ══ 9 · the template didn't load ═══════════════════════════════════════════
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" }, { templateStatus: 500 });
    await p.settle();
    await p.tick(true);
    await p.settle();
    const warn = p.surface.querySelector(".cl-warn");
    const btns = p.surface.querySelectorAll(".cl-warn-btn");
    out.failure = {
      warned: !!warn,
      role: warn ? warn.getAttribute("role") : null,
      pages: p.surface.querySelectorAll(".cl-page").length,
      buttons: btns.map((b) => b.textContent),
      // The way out actually works: pressing "Turn the cover letter off" leaves the estimator on
      // a page with no letter and a bid they can still send.
      afterTurnOff: await (async () => {
        const off = btns[btns.length - 1];
        off.dispatchEvent(new Ev("click", { bubbles: true }));
        await p.settle();
        return { enabled: p.STORE.blob.cover_letter_enabled, tabsHidden: p.tabs.hidden,
                 checked: p.toggle.checked };
      })(),
    };
  }

  // ══ 10 · the duplicated inference must not drift from the proposal's ═══════
  /* `effectiveWorkType` is LIFTED from proposal-review.js here and run beside the cover letter's
   * copy over the same draft states. The duplication is deliberate (a lifted function that grows
   * a second caller becomes a dependency five harnesses can break); this is what keeps it a
   * duplicate rather than a fork. */
  {
    const STATES = [
      { name: "plain epoxy", blob: { work_type: "epoxy", audience: "Direct" } },
      { name: "combo wins outright", blob: { work_type: "combo", audience: "GC",
          priced_tabs: [{ id: "t1", role: "polish" }], base_tab_id: "t1" } },
      { name: "base role beats intake", blob: { work_type: "epoxy", audience: "Direct",
          priced_tabs: [{ id: "t1", role: "polish" }], base_tab_id: "t1" } },
      { name: "gyp base", blob: { work_type: "epoxy", audience: "Gyp",
          priced_tabs: [{ id: "t9", role: "gyp" }], base_tab_id: "t9" } },
      { name: "unknown role falls back to intake", blob: { work_type: "polish", audience: "GC",
          priced_tabs: [{ id: "t1", role: "sealer" }], base_tab_id: "t1" } },
      { name: "base id names no tab", blob: { work_type: "epoxy", audience: "Direct",
          priced_tabs: [{ id: "t1", role: "polish" }], base_tab_id: "t7" } },
      { name: "no work type at all", blob: { audience: "Direct" } },
    ];
    const rows = [];
    for (const s of STATES) {
      const p = makePage(s.blob);
      await p.settle();
      // The proposal's own function, compiled against its own `state` snapshot exactly as the
      // page compiles it.
      const theirs = new Function("state", liftFn(PR_SRC, "effectiveWorkType", "proposal-review.js")
        + "\nreturn effectiveWorkType();")(JSON.parse(JSON.stringify(s.blob)));
      rows.push({ name: s.name, ours: p.CL().workType(), theirs: theirs,
                  audience: p.CL().audience(), key: p.CL().key(p.CL().workType(), p.CL().audience()) });
    }
    out.inference = rows;
  }

  // ══ 11 · the payload the two pages agree on ════════════════════════════════
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.type(2, "One line changed.");
    p.flush();
    out.payload = {
      on: p.CL().payloadFields(),
      // A draft whose editor never ran at all — the Files page's "View files" rebuild, which
      // loads this file for `payloadFields` and nothing else.
      coldRead: (() => {
        const q = makePage(p.STORE.blob);
        return q.CL().payloadFields();
      })(),
    };
  }

  // ══ 12 · the resolver is called WITH the draft, not called blind ═══════════
  /* `computeTokenValues` throws when it is not handed a mergedValues object (see the stub above),
   * and `clTokens()` swallows any throw and hands `render()` an empty token map — which looks
   * exactly like "this letter has no tokens", so every `{{token}}` prints literally. That is the
   * bug Hanz reported and the screenshots showed: nothing on the cover letter was substituted.
   *
   * This draft's job_name is one the letterhead default (TOKENS.job_name, "Olathe Fire Station 4")
   * does not know, so the ONLY way it reaches the page is a call that actually passes this draft's
   * state through. If clTokens() regresses to calling the resolver with no argument, the stub
   * throws, the catch swallows it, and this assertion sees the raw "{{job_name}}" text instead. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct", job_name: "Regression Test Job" });
    await p.settle();
    await p.tick(true);
    await p.settle();
    const block = p.look(1);
    out.resolverGetsTheDraft = {
      jobNameBlock: block ? block.text : null,
      stillRaw: block ? block.text.indexOf("{{") >= 0 : null,
    };
  }

  // == 13 - Bold, Italic, Underline actually apply to the LETTER =============
  /* THE BUG HANZ REPORTED, executed: "These options to edit the text to make it bold does not
   * apply." Three independent things had to be true for a press to reach a cover-letter
   * paragraph, and all three are asserted here rather than read out of the source:
   *
   *   1. the ribbon must be AIMED at a letter paragraph -- switching to the letter hands the bar
   *      back to the proposal, which aims it at nothing;
   *   2. the buttons must be RE-ENABLED, because a disabled button dispatches no click at all,
   *      so interception on its own could never have fixed this;
   *   3. collect() must be able to SEE a format-only edit -- bolding a word changes no
   *      character, so a reader that compares text alone finds nothing to save and the press
   *      vanishes on the way out.
   *
   * Block 2 is the one under test on purpose: it carries a {{job_name}} fill in the middle of
   * its sentence, so it also proves a press does not destroy the token highlighting. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" }, { geometry: GEO_FLOW, blocks: BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    const virgin = Object.keys(p.CL().collect()).length;   // an untouched letter ships nothing
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    const disabledBeforeAim = p.fmtButtons.bold.disabled;
    const el = p.caretIn(2);
    const textBefore = el.textContent;
    const disabledAfterAim = p.fmtButtons.bold.disabled;
    /* `disabledAfterAim` is the ONLY assertion that can see the re-enable, and it has to be
     * asserted on its own rather than inferred from the press landing. This fake DOM dispatches a
     * click from a disabled button; a real browser does not. So deleting the re-enable line leaves
     * every other reading here green and breaks the feature completely in the product. */

    p.press("bold");
    const bolded = p.override(2);
    const boldFill = el.querySelector(".tw-fill");
    const pressedAfterBold = p.fmtButtons.bold.getAttribute("aria-pressed");
    const fmtAfterBold = el.classList.contains("tw-fmt");
    const dirtyAfterBold = el.classList.contains("tw-dirty");
    const textAfterBold = el.textContent;

    p.press("bold");                                       // ...and off again
    const unbolded = p.override(2);

    p.press("reset");                                      // back to what the template says
    const afterReset = p.override(2);

    out.boldApplies = {
      virgin: virgin,
      disabledBeforeAim: disabledBeforeAim,
      disabledAfterAim: disabledAfterAim,
      // The tabs live inside #fmt-ribbon, so an unscoped interceptor would have eaten that click
      // and left us on the proposal. Reaching the letter at all is the assertion.
      onCover: p.surface.classList.contains("cl-offstage") === false,
      paraHidden: p.paraBtn.style.visibility,
      pressedAfterBold: pressedAfterBold,
      // ...and back to false once Reset has put the paragraph back to the template's own runs.
      pressedAfterReset: p.fmtButtons.bold.getAttribute("aria-pressed"),
      fmtClass: fmtAfterBold,
      dirty: dirtyAfterBold,
      textUnchanged: textAfterBold === textBefore,
      fillSurvived: !!boldFill,
      fillToken: boldFill ? boldFill.attrs["data-token"] : null,
      boldSaved: bolded ? bolded.runs.map((r) => r.bold) : null,
      boldText: bolded ? bolded.runs.map((r) => r.text).join("") : null,
      // `false` is not the same as absent. Absent means "inherit the template's own run"; false
      // means the estimator turned it off and the .docx has to say so out loud.
      unboldSaved: unbolded ? unbolded.runs.map((r) => r.bold) : null,
      // Reset is the only thing that puts a paragraph back to carrying no override at all, which
      // is what keeps "an untouched letter ships nothing" true after a press-and-undo.
      afterReset: afterReset,
    };
  }

  // == 14 - italic, underline and a typed size, and the guard that scopes them ==========
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" }, { geometry: GEO_FLOW, blocks: BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    p.caretIn(3);
    p.press("italic");
    p.press("underline");
    const both = p.override(3);
    p.sizeBox.value = "14";
    p.sizeBox.dispatchEvent(new Ev("change", { bubbles: true }));
    const sized = p.override(3);

    /* Back to the proposal. TWO separate things have to happen here and each has its own reading
     * below, because the ribbon interceptor sits on `#fmt-ribbon` -- the PARENT of both the
     * formatting row and the document tabs -- and takes presses in the CAPTURE phase.
     *
     * The dangerous click is this one, not the one that opened the letter. Going TO the letter,
     * `activeTab` is still "proposal" and the interceptor returns on its first line. Coming BACK,
     * `activeTab` is "cover", so the interceptor runs -- and if it called stopPropagation before
     * checking that the press was a `button[data-fmt]` inside `.tw-fmtbar`, it would swallow the
     * estimator's own tab click and strand them on the letter with no way out. */
    let proposalHeard = 0;
    p.fmtBar.addEventListener("click", () => { proposalHeard++; });
    p.proposalTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    const backOnProposal = p.surface.classList.contains("cl-offstage");
    p.press("bold");
    const afterSwitchAway = p.override(3);

    out.italicUnderlineSize = {
      italic: both ? both.runs.map((r) => r.italic) : null,
      underline: both ? both.runs.map((r) => r.underline) : null,
      size: sized ? sized.runs.map((r) => r.size_pt) : null,
      boxValue: p.sizeBox.value,
      // Identical to `sized`: the press on the proposal tab must have changed nothing here.
      boldLeakedIn: afterSwitchAway ? afterSwitchAway.runs.some((r) => r.bold === true) : null,
      // The estimator got out of the letter. False means the tab click was eaten on the way down.
      backOnProposal: backOnProposal,
      // ...and the proposal's own bubble-phase handler still hears its own presses. The letter
      // going quiet is only half the requirement; the interceptor also has to stop INTERCEPTING,
      // or bold would be dead on the proposal for the rest of the session.
      proposalHeard: proposalHeard,
    };
  }

  // == 15 - a saved format comes BACK, and survives a reload =================
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" }, { geometry: GEO_FLOW, blocks: BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    p.caretIn(2);
    p.press("bold");
    p.flush();
    const stored = p.STORE.blob.cover_letter_paragraph_overrides;

    // A fresh page over the same draft -- the estimator coming back tomorrow.
    const q = makePage(p.STORE.blob, { geometry: GEO_FLOW, blocks: BODY });
    await q.settle();
    await q.tick(true);
    await q.settle();
    const back = q.surface.querySelector('.tw-block[data-id="2"]');

    out.formatSurvivesReload = {
      storedRuns: stored && stored["2"] ? stored["2"].runs.map((r) => ({ t: r.text, b: r.bold })) : null,
      // The backend prefers `runs` and skips `text` when it has them, so BOTH must be sent --
      // `text` alone is what a paragraph that was merely retyped saves, and a reader that only
      // ever saw text is what made a press vanish in the first place.
      storedHasText: !!(stored && stored["2"] && typeof stored["2"].text === "string"),
      replayedText: back ? back.textContent : null,
      replayedBold: back ? back.querySelectorAll("span").some((s) => String(s.style.fontWeight) === "700") : null,
      replayedFmtClass: back ? back.classList.contains("tw-fmt") : null,
      // ...and it must still be collectable, or the second visit would silently drop the format.
      recollected: q.override(2) ? q.override(2).runs.map((r) => r.bold) : null,
    };
  }

  /* ── 16 · Ctrl+B reaches the letter, and the browser is told to keep its hands off ───────────
   *
   * A second, entirely separate wiring. The ribbon buttons are bound by `clWireRibbon`; the
   * keyboard is bound by `clWireSurface`, and the proposal's own Ctrl+B is scoped to
   * `#doc-surface` so it never fires for the letter at all. Delete the keydown listener and every
   * other scenario in this file stays green while an estimator who reaches for Ctrl+B gets
   * nothing -- or worse, gets the BROWSER's bold, which writes a raw <b> the collector cannot see.
   *
   * Hence two readings, not one: the override has to land, and the default has to be prevented. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" }, { geometry: GEO_FLOW, blocks: BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();

    const el = p.caretIn(2);
    const ev = p.key("b");
    const kbBold = p.override(2);

    p.key("i");
    const kbItalic = p.override(2);

    // A bare "b" with no modifier is a letter being typed, not a command. If this ever comes back
    // formatted, the guard has been dropped and the estimator cannot type the letter b.
    const plain = p.key("b", { ctrlKey: false });

    out.keyboardApplies = {
      bold: kbBold ? kbBold.runs.map((r) => r.bold) : null,
      italic: kbItalic ? kbItalic.runs.map((r) => r.italic) : null,
      // ...and the same paragraph, not a new one, and its text untouched.
      text: el.textContent,
      prevented: ev.defaultPrevented,
      plainPrevented: plain.defaultPrevented,
    };
  }

  /* ── 17 · only the label is bold ────────────────────────────────────────────────────────────
   *
   * Hanz, 2026-09-04, with a screenshot of the Cover letter tab: "Then on the bulleted. Only those
   * words before and including the colon should be default bold. The other details should not be.
   * So, material/system, area, schedule, options should be the only ones bold."
   *
   * The .docx already agrees with him — Kyle's template bolds the label run and leaves the detail
   * run plain — and the editor was throwing that away twice over. It walked `b.text`, so the only
   * weight it could show was the paragraph-level `tw-bold` class, and `b.style.bold` is
   * `any(r.bold ...)` on the server, so every bullet with a bold label asked for that class.
   *
   * READ AS PAINTED TEXT, not as spans: see `painted` above. Both halves of the fix are separately
   * necessary and this scenario is what proves it — drop the per-run pass and every stretch comes
   * back bold; keep the class and the `null`-bold details come back bold. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" },
                       { geometry: GEO_FLOW, blocks: LABEL_BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    out.labelBullets = {
      bulletBold: p.boldParts(1),
      bulletPlain: p.plainParts(1),
      bulletCls: p.painted(1).cls,
      bulletToken: (p.painted(1).runs.find((r) => r.token) || {}).token || null,
      areaBold: p.boldParts(2),
      areaPlain: p.plainParts(2),
      // The Options line: italic travels per run, and does not drag bold along with it.
      optionsBold: p.boldParts(3),
      optionsItalic: p.painted(3).runs.filter((r) => r.italic).map((r) => r.text),
      headingBold: p.boldParts(4),
      headingPlain: p.plainParts(4),
      splitHeadingBold: p.boldParts(5),
      splitHeadingPlain: p.plainParts(5),
      bodyBold: p.boldParts(6),
      bodyToken: (p.painted(6).runs.find((r) => r.token) || {}).token || null,
      footerBold: p.boldParts(7),
      footerPlain: p.plainParts(7),
      // NO POINT SIZE ANYWHERE. The footer's runs state 10pt against an 11pt body, so emitting
      // them would re-flow this letter -- geometry, on a to-scale preview of a printed sheet.
      inlineSizes: p.inlineSizes(),
      // WHICH LIST TREATMENT EACH LINE GOT, and what its marker prints. `.tw-num` shows the
      // document's own number; `.tw-li` is a red Wingdings square. Every labelled line in all
      // seven templates is numbered, so a square anywhere in here is a line the estimator
      // proofreads as a bullet and the customer receives as "1.".
      lists: [1, 2, 3, 4, 6, 7].map((id) => Object.assign({ id: id }, p.listLook(id))),
      // ...and the marker is placed at the level's own geometry, not `.tw-num`'s built-in 9pt/18pt
      // (which was measured off the proposal's Terms level, a different document).
      numGeom: (function () { const e = p.el(1);
                              return { ml: e.style.marginLeft, pl: e.style.paddingLeft }; })(),
      // The words themselves, because a renderer that reflowed the sentence to get the weights
      // right would be a worse bug than the weights.
      bulletText: p.look(1).text,
      // ...and drawing the runs may not make a single paragraph LOOK edited. `pristine` is still
      // the flat fill of `b.text`, so a per-run render that disagreed with it by one character
      // would mark every line dirty and ship the whole letter as overrides on the first keystroke.
      virgin: Object.keys(p.CL().collect()).length,
      dirty: p.surface.querySelectorAll(".tw-block")
        .filter((b) => b.classList.contains("tw-dirty")).length,
    };
  }

  /* ── 18 · the three ways run records are refused ────────────────────────────────────────────
   *
   * Rendering a paragraph one run at a time is only safe while the runs describe the paragraph.
   * Two of these three cases send it back to the flat walk, and the paragraph-level class has to
   * come back WITH it: a guard that refused the runs and dropped the class as well would leave
   * those lines with no weight at all, which is the fix overshooting into a new bug. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" },
                       { geometry: GEO_FLOW, blocks: GUARD_BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    out.runGuards = {
      unjoinableCls: p.painted(11).cls,
      unjoinableBold: p.boldParts(11),
      unjoinableText: p.look(11).text,
      straddledCls: p.painted(12).cls,
      straddledText: p.look(12).text,
      // The one that matters: the token's VALUE reached the screen rather than its braces.
      straddledToken: (p.painted(12).runs.find((r) => r.token) || {}).token || null,
      // A token inside a longer run is still usable, so it keeps its per-run weights AND fills.
      innerBold: p.boldParts(13),
      innerPlain: p.plainParts(13),
      innerCls: p.painted(13).cls,
      innerToken: (p.painted(13).runs.find((r) => r.token) || {}).token || null,
      innerText: p.look(13).text,
      // ...and the red square is still reachable for a line that really is a bullet.
      realBullet: p.listLook(14),
    };
  }

  /* ── 19 · THE COMPOSE PROPERTY, which is the subtle half of this change ─────────────────────
   *
   * The backend grew a label-split of its own for the same complaint: given a PLAIN-TEXT override
   * it bolds the label and leaves the details alone, which is what saves a draft written before
   * this fix and what the portal's server-side replay of a pinned revision goes through. It stands
   * aside the moment an override carries `runs`, because an explicit press by the estimator has to
   * outrank a guess.
   *
   * So the danger in rendering runs is not the rendering, it is what `collect()` then reads back:
   * `clFmtAt` measures inline styles, and the template's own `font-weight:700` is now one of them.
   * If a paragraph nobody touched serialised its runs, every letter in the product would silently
   * become an explicit-runs override and the backend's safety net would be switched off for
   * everybody — a fix for the screen that breaks the print.
   *
   * It does not, and the reason is `collect()`'s existing gate: runs are only read from a block
   * carrying `tw-fmt`, and only `clApplyFormat` (a real press) and `restoreSaved` (replaying an
   * override that already had runs) ever set it. Three readings, because the property is three
   * claims: untouched ships nothing, RETYPED ships text with no runs key, and a PRESS is the one
   * thing that opts that one paragraph into runs. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" },
                       { geometry: GEO_FLOW, blocks: LABEL_BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    const untouched = Object.keys(p.CL().collect()).length;

    p.type(2, "Area: 14,500 SF");
    p.flush();
    const retyped = p.override(2);

    p.caretIn(1);
    // EVERY RUN IN THESE FIXTURES STATES 11pt, and the ribbon must still show an empty size
    // box. This page is a to-scale preview of a printed sheet, so a point size is geometry:
    // emitting the template’s own sizes would reflow the letter, and reading them back would
    // pin 11pt onto every run of the first paragraph anybody pressed a button on. Absent means
    // "inherit the template’s own", which is true, and is what a press stored before this
    // change too.
    const sizeBoxAfterAim = p.sizeBox.value;
    p.press("bold");
    p.flush();
    const pressed = p.override(1);

    out.composeProperty = {
      untouched: untouched,
      // `["text"]` and nothing else. A `runs` key here is the regression: the backend would stand
      // aside and this paragraph would print with no bold label at all.
      retypedKeys: retyped ? Object.keys(retyped).sort() : null,
      retypedText: retyped ? retyped.text : null,
      pressedKeys: pressed ? Object.keys(pressed).sort() : null,
      pressedRuns: pressed ? pressed.runs.map((r) => ({ t: r.text, b: r.bold })) : null,
      sizeBoxAfterAim: sizeBoxAfterAim,
      pressedSizes: pressed ? pressed.runs.map((r) => r.size_pt === undefined ? "absent" : r.size_pt) : null,
      // The press opted ONE paragraph in. The other four are still untouched, so the three
      // paragraphs nobody has been near must still be absent from the store entirely.
      touched: Object.keys(p.STORE.blob.cover_letter_paragraph_overrides).sort(),
      // What a retyped paragraph looks like when it comes BACK: `restoreSaved` replays a text-only
      // entry as textContent, which carries no formatting at all, so the label is not bold on
      // screen while the generated .docx will bold it via the backend split. Recorded rather than
      // asserted-away: it is the one place the two halves of the fix disagree, and re-splitting the
      // label in the browser would be a second copy of the backend's rule.
      retypedOnReload: await (async () => {
        const q = makePage(p.STORE.blob, { geometry: GEO_FLOW, blocks: LABEL_BODY });
        await q.settle();
        await q.tick(true);
        await q.settle();
        return { bold: q.boldParts(2), plain: q.plainParts(2), cls: q.painted(2).cls };
      })(),
    };
  }

  /* ── 20 · Ctrl+B on a label bullet, twice, without touching the caret in between ────────────
   *
   * The keyboard is the second wiring (`clWireSurface`, not `clWireRibbon`) and the one an
   * estimator formatting a letter actually reaches for. On a bullet it is also the first press
   * that has ever had mixed runs underneath it: `summarize` returns `undefined` for a selection
   * that is part bold, and `nextToggle` turns THAT on rather than off, so one press bolds the
   * whole line rather than un-bolding the label.
   *
   * The second press is the interesting one. `clApplyFormat` rewrites the paragraph's innerHTML,
   * which destroys every text node the caret could have been in — the classic "a re-render steals
   * the focus you just tabbed into". What stops that being fatal is that the BLOCK element is
   * never replaced, only its children, so `clFmtBlock` still names a paragraph the surface
   * contains and the second press lands on the same line. Element identity is the only thing that
   * can say so, hence `sameElement`. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" },
                       { geometry: GEO_FLOW, blocks: LABEL_BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    const before = p.caretIn(1);
    const ev = p.key("b");
    const first = p.override(1);
    const paintedAfter = p.painted(1);
    const ev2 = p.key("b");
    const second = p.override(1);
    p.flush();
    out.keyboardOnALabelBullet = {
      prevented: ev.defaultPrevented,
      firstRuns: first ? first.runs.map((r) => ({ t: r.text, b: r.bold })) : null,
      // Bolding the line is an edit to its FORMAT. Not one character of it may move.
      textAfter: p.look(1).text,
      // ...and the estimate's value is still marked as a value.
      fillSurvived: (paintedAfter.runs.find((r) => r.token) || {}).token || null,
      wholeLineBold: paintedAfter.runs.every((r) => r.bold),
      secondPrevented: ev2.defaultPrevented,
      secondRuns: second ? second.runs.map((r) => ({ t: r.text, b: r.bold })) : null,
      sameElement: before === p.el(1),
      ids: Object.keys(p.STORE.blob.cover_letter_paragraph_overrides).sort(),
    };
  }

  /* ── 21 · a saved runs override replays onto a run-rendered paragraph ───────────────────────
   *
   * Scenario 15 proves this for a template with no runs of its own. Now that the template brings
   * its own, `restoreSaved` is putting the estimator's runs over the top of them — and it is the
   * paragraph-level class, dropped in `renderBlock`, that decides whether the replay can be seen
   * for what it is. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" },
                       { geometry: GEO_FLOW, blocks: LABEL_BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    p.caretIn(4);
    p.press("bold");                      // a wholly bold heading, turned OFF on purpose
    p.flush();
    const q = makePage(p.STORE.blob, { geometry: GEO_FLOW, blocks: LABEL_BODY });
    await q.settle();
    await q.tick(true);
    await q.settle();
    out.savedRunsOverRuns = {
      storedRuns: p.STORE.blob.cover_letter_paragraph_overrides["4"].runs
        .map((r) => ({ t: r.text, b: r.bold })),
      replayedBold: q.boldParts(4),
      replayedPlain: q.plainParts(4),
      replayedFmtClass: q.el(4).classList.contains("tw-fmt"),
      // The replay rewrites the paragraph's children. Its list treatment is a CLASS on the
      // paragraph itself, so the number has to still be there afterwards.
      replayedList: q.listLook(4),
      neighbourList: q.listLook(1),
      // The template's own bullets around it are untouched by the replay.
      neighbourBold: q.boldParts(1),
      recollected: q.override(4) ? q.override(4).runs.map((r) => r.bold) : null,
    };
  }

  /* ── 22 · what an EMPTIED numbered line does, and what `locked` is worth here ────────────────
   *
   * `para.locked` is true on every labelled line in all seven templates, and this editor reads it
   * nowhere. That is not an oversight, and the reading below is what says so rather than a comment
   * claiming it: the one thing `locked` exists to refuse in the proposal is a press on the
   * bullet/indent controls, and `clRenderFmtBar` hides the whole `[data-para]` group whenever the
   * letter is on stage — so there is no control here that could drop a line's numbering.
   *
   * What the proposal ALSO does with a numbered paragraph is refuse to let it be emptied
   * (`restoreEmptiedClause`), because Word would print a bare clause number in a signed contract.
   * The letter deliberately does NOT copy that: its Options line says "keep the lines that apply",
   * so deleting one is a thing the estimator is meant to do, and refusing it would be the wrong
   * answer to a different document's problem.
   *
   * The consequence is real and is recorded here rather than hidden: an emptied numbered line
   * keeps its number, on screen AND in the .docx. `.tw-block.tw-empty.tw-li::before` drops the red
   * square for an emptied BULLET, and there is no `.tw-num` equivalent — which, now that these
   * lines render as numbers, means the estimator sees exactly the bare "4." the file prints. Before
   * this change the square vanished and gave a false all-clear. */
  {
    const p = makePage({ work_type: "epoxy", audience: "Direct" },
                       { geometry: GEO_FLOW, blocks: LABEL_BODY });
    await p.settle();
    await p.tick(true);
    await p.settle();
    p.coverTab.dispatchEvent(new Ev("click", { bubbles: true }));
    await p.settle();
    const el = p.type(3, "");
    p.flush();
    out.emptiedNumberedLine = {
      empty: el.classList.contains("tw-empty"),
      dirty: el.classList.contains("tw-dirty"),
      // The number is still there, because the .docx still prints it.
      list: p.listLook(3),
      saved: p.STORE.blob.cover_letter_paragraph_overrides["3"],
      // NOT put back. The proposal restores an emptied numbered clause; the letter must not,
      // because an Options line the job does not need is meant to be deletable.
      text: p.look(3).text,
      // The paragraph controls that `locked` would gate are hidden outright while the letter is
      // in front, which is why nothing here needs to read the flag.
      paraControlsHidden: p.paraBtn.style.visibility,
      paraControlsDisabled: p.paraBtn.disabled,
    };
  }

  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
