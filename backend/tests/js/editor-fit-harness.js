"use strict";
/* The Proposal step shows every text box at the size the document PRINTS it -- RUN, not read.
 *
 * Hanz, 2026-09-26: "please follow the text size of what is written in the proposal PDFs. Its
 * different on the editor and on the output" / "whatever is the font size in the PDF should also be
 * the same as in the Proposal Editor".
 *
 * The size a box prints at is the writer's decision (proposal_writer._shrink_overflowing_text_boxes),
 * which POST /api/proposal-fit reports per box. What this harness executes is the page's half: the
 * REAL renderBlock, notesRowSizePt, renderNotesPreview, applyBoxFit and fitTxbx, lifted verbatim out
 * of proposal-review.js, over the REAL template blocks and the REAL fit report that
 * test_editor_fit_parity.py hands it (argv[3], a JSON file). It reports, element by element, the size
 * each piece of text is given, and the test compares that with the .docx the real _generate writes.
 *
 * NOT A FULL DOM, for the reason box-drag-harness.js gives: jsdom would let a missing binding hide
 * behind a stub. The one thing modelled beyond the other harnesses is `style.setProperty`, because
 * the printed size is a custom property (--tw-fit-pt) that a stylesheet rule turns into the
 * font-size -- so the inline `font-size`, which fmtAt reads back as the estimator's formatting,
 * keeps the design size. Both are reported, so the test can check that neither leaked into the other.
 *
 * Usage: node editor-fit-harness.js <frontend-dir> <cases.json>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const CASES = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
// Normalized to LF, like every harness here: the checkout is CRLF and the lifts anchor on "\n  ".
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

// ── the smallest DOM these functions touch ───────────────────────────────────
const Node = { ELEMENT_NODE: 1, TEXT_NODE: 3 };
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", nbsp: " " };
const unesc = (s) => String(s).replace(/&(#39|amp|lt|gt|quot|nbsp);/g, (_, k) => ENTITIES[k]);

/** An inline style: camelCase properties (what fmtAt and inlineHp read) plus custom properties
 *  behind setProperty / removeProperty / getPropertyValue, which is how applyBoxFit writes. */
function makeStyle(css) {
  const st = {};
  const custom = {};
  for (const bit of String(css || "").split(";")) {
    const k = bit.indexOf(":");
    if (k < 0) continue;
    const raw = bit.slice(0, k).trim();
    const v = bit.slice(k + 1).trim();
    if (!raw) continue;
    if (raw.startsWith("--")) custom[raw] = v;
    else st[raw.replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
  }
  Object.defineProperties(st, {
    setProperty: { value: (k, v) => { custom[k] = String(v); }, enumerable: false },
    removeProperty: { value: (k) => { delete custom[k]; }, enumerable: false },
    getPropertyValue: { value: (k) => (custom[k] === undefined ? "" : custom[k]), enumerable: false },
  });
  return st;
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
}

const VOID = new Set(["BR", "IMG", "HR", "INPUT"]);

class El {
  constructor(tag) {
    this.nodeType = Node.ELEMENT_NODE;
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.style = makeStyle("");
    this.attrs = {};
    this.title = "";
    this._classes = new Set();
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
  appendChild(c) { c.parentNode = this; this.childNodes.push(c); return c; }
  get textContent() {
    return this.childNodes.map((n) => (n.nodeType === Node.TEXT_NODE ? n.nodeValue : n.textContent)).join("");
  }
  set textContent(v) { this.childNodes = []; if (String(v) !== "") this.appendChild(new Text(v)); }
  set innerHTML(html) {
    this.childNodes = [];
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
          else if (a[1] === "style") el.style = makeStyle(v);
          else if (a[1] === "title") el.title = v;
          else if (a[1].startsWith("data-")) el.dataset[a[1].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v;
        }
        top.appendChild(el);
        if (!VOID.has(el.tagName)) stack.push(el);
      } else if (m[4] !== undefined) top.appendChild(new Text(unesc(m[4])));
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
    for (const c of this.children) { if (matches(c, sel)) out.push(c); out.push(...c.querySelectorAll(sel)); }
    return out;
  }
  closest(sel) {
    let el = this;
    while (el) { if (el.nodeType === Node.ELEMENT_NODE && matches(el, sel)) return el; el = el.parentNode; }
    return null;
  }
  contains(other) { let el = other; while (el) { if (el === this) return true; el = el.parentNode; } return false; }
  /** A box that fits: this harness is about SIZES, and fitTxbx's overflow notice is measured in
   *  doc-editor-harness.js and box-drag-harness.js, which model heights. */
  get offsetHeight() { return 0; }
}

const NOTES_TA = new El("textarea");
NOTES_TA.value = "";
const document = {
  createElement: (t) => new El(t),
  activeElement: null,
  getElementById: (id) => (id === "notes-text" ? NOTES_TA : null),
};
const window = { getSelection: () => ({ rangeCount: 0 }) };

const LIFTED = [
  topConst("escHtml"), topConst("DOC_TOKEN_RE"), topConst("TWIPS_PER_PT"), topConst("focusInside"),
  // focusInside asks where the caret is; there is none here, and the real resolvers say so.
  topConst("LINE_SEL"), fn("lineAt"), fn("lineAtSelection"),
  topConst("boxFitById"), topConst("PAGE_HP"),
  fn("fillHtml"), fn("fillPlain"), fn("runStyleCss"), fn("blockHtml"), fn("singleTokenHint"),
  fn("setBlockContent"), fn("isNumberedClause"), fn("applyParaGeom"), fn("renderBlock"),
  fn("inlineHp"), fn("clearBoxFit"), fn("applyBoxFit"), fn("fitOffer"), fn("fitTxbx"),
  fn("notesRowSizePt"), fn("noteLineHtml"), fn("renderNotesPreview"),
  // THE PAGE'S OWN QUESTION-AND-ANSWER LOOP: the three bookkeeping lets, verbatim, and requestFit,
  // which parses the route's answer, drops one for another template or one a newer question
  // overtook, and hands the rest to fitTxbx. setFit below is the harness's shortcut for the render
  // cases; the `answers` scenario goes through this instead, so the parsing is the page's.
  (() => {
    const i = SRC.indexOf("\n  let _fitTimer = null;");
    const j = SRC.indexOf("\n  /** Ask again, soon.", i);
    if (i < 0 || j < 0) throw new Error("the fit request's bookkeeping lets are gone");
    return SRC.slice(i, j);
  })(),
  fn("requestFit"),
].join("\n\n");

// `fetch` is the one collaborator faked: each call is recorded and answered by whatever the
// scenario put in FETCH.reply. `fitPayload` -- the Continue composer, which builds the question --
// is stubbed to a question the scenario sets, because what is under test is the answer's handling.
const FETCH = { calls: [], reply: null };
const fetchStub = (url, opts) => {
  FETCH.calls.push({ url: url, method: opts && opts.method, body: opts && opts.body,
                     contentType: opts && opts.headers && opts.headers["Content-Type"],
                     auth: opts && opts.headers && opts.headers.Authorization });
  return FETCH.reply(opts && opts.body);
};
const QUESTION = { q: "" };
const DOC = new El("div");
const TW = { authHeaders: () => ({ Authorization: "Bearer harness" }) };

const api = new Function(
  "document", "window", "F", "Node", "fetch", "TW", "docSurface", "QUESTION",
  `let templateVersion = "tv-A";
  const fitPayload = () => ({ q: QUESTION.q });
  const blockById = new Map();
  const pristineById = new Map();
  const boxDesign = new Map();         // fitOffer's: no geometry here, so no box is offered growth
  const TOKEN_HINTS = {};
  let flowMode = false;
  let templateBlocks = null;
  const notesPreviewEl = document.createElement("div");
  // The notes preview re-fits every box after a rebuild; the fit itself is exercised directly below.
  const fitNotesBox = () => {};
` + LIFTED + `
  return {
    renderBlock, applyBoxFit, clearBoxFit, fitTxbx, notesRowSizePt, renderNotesPreview, requestFit,
    load: (blocks) => {
      templateBlocks = blocks;
      blockById.clear();
      blocks.forEach((b) => blockById.set(b.id, b));
    },
    setFit: (fit) => {
      boxFitById.clear();
      for (const k of Object.keys(fit || {})) {
        const f = fit[k];
        boxFitById.set(Number(k), { scale: f.scale, default_hp: f.default_hp,
                                    exempt: new Set((f.exempt || []).map(Number)), at_floor: !!f.at_floor });
      }
    },
    notesPreviewEl,
  };`
)(document, window, F, Node, fetchStub, TW, DOC, QUESTION);

/** Every element under `root` that states a size inline, and the root itself: design size (the
 *  inline font-size, which is what fmtAt reads) and printed size (the custom property). */
function sizes(root) {
  const out = [];
  const walk = (el) => {
    for (const c of el.children) {
      if (c.style.fontSize || c.style.getPropertyValue("--tw-fit-pt")) {
        out.push({ text: c.textContent, design: c.style.fontSize || null,
                   printed: c.style.getPropertyValue("--tw-fit-pt") || null,
                   marked: c.dataset.twFit === "1" });
      }
      walk(c);
    }
  };
  walk(root);
  return out;
}

const out = { cases: [] };
for (const kase of CASES.cases) {
  api.load(kase.blocks);
  api.setFit(kase.fit);
  const boxes = new Map();
  for (const b of kase.blocks) {
    if (b.txbx == null || b.in_block) continue;
    if (!boxes.has(b.txbx)) {
      const box = new El("div");
      box.className = "tw-txbx";
      box.dataset.boxId = String(b.txbx);
      box.dataset.boxHPt = "1000";
      boxes.set(b.txbx, box);
    }
    boxes.get(b.txbx).appendChild(api.renderBlock(b, kase.tokens || {}));
  }
  // THE PAGE'S PATH: fitTxbx, the function every render, edit and fit answer runs, is what applies
  // the printed size -- not a direct call a test could make and the page never does.
  boxes.forEach((box) => api.fitTxbx(box));
  const rec = { name: kase.name, boxes: [], blocks: [] };
  boxes.forEach((box, id) => {
    rec.boxes.push({ id: id, printed: box.style.getPropertyValue("--tw-fit-pt") || null,
                     marked: box.dataset.twFit === "1" });
    for (const el of box.children) {
      rec.blocks.push({
        id: Number(el.dataset.id), txbx: id,
        base: el.style.fontSize || null,
        markPt: el.dataset.markPt || null,
        markVar: el.style.getPropertyValue("--tw-mark-pt") || null,
        printed: el.style.getPropertyValue("--tw-fit-pt") || null,
        spans: sizes(el),
      });
    }
  });
  // And back: with no answer for any box (a template switch clears them), every mark comes off.
  api.setFit({});
  boxes.forEach((box) => api.fitTxbx(box));
  let left = 0;
  boxes.forEach((box) => {
    if (box.dataset.twFit || box.style.getPropertyValue("--tw-fit-pt")) left++;
    for (const s of sizes(box)) if (s.printed || s.marked) left++;
  });
  rec.marksLeftAfterClear = left;
  // The NOTES bullets, rendered the page's way from the template's own {{#notes}} row.
  NOTES_TA.value = "First note.\n\nThird note, after a blank one.";
  api.renderNotesPreview();
  rec.notesRowPt = api.notesRowSizePt();
  rec.notes = api.notesPreviewEl.children.map((p) => ({ cls: p.className, fontSize: p.style.fontSize || null }));
  out.cases.push(rec);
}

/** The route's answer, handled by the page's real requestFit (see LIFTED). `a` is one template's
 *  blocks and the REAL /api/proposal-fit report for a payload; the boxes are mounted in the
 *  surface requestFit re-fits, and each step reports every box's printed size. */
async function runAnswers(a) {
  api.load(a.blocks);
  api.setFit({});
  DOC.childNodes = [];
  const boxes = new Map();
  for (const b of a.blocks) {
    if (b.txbx == null || b.in_block) continue;
    if (!boxes.has(b.txbx)) {
      const box = new El("div");
      box.className = "tw-txbx";
      box.dataset.boxId = String(b.txbx);
      box.dataset.boxHPt = "1000";
      DOC.appendChild(box);
      boxes.set(b.txbx, box);
    }
    boxes.get(b.txbx).appendChild(api.renderBlock(b, a.tokens || {}));
  }
  boxes.forEach((box) => api.fitTxbx(box));
  const snap = () => {
    const o = {};
    boxes.forEach((box, id) => { o[id] = box.style.getPropertyValue("--tw-fit-pt") || null; });
    return o;
  };
  const answer = (tv, list) => () => Promise.resolve({ ok: true, json: () => Promise.resolve(
    { template_version: tv, boxes: list }) });
  const unshrunk = a.report.map((b) => Object.assign({}, b, { scale: 1.0 }));
  const res = {};
  FETCH.calls.length = 0;
  // 1. An answer for the template on screen is applied.
  QUESTION.q = "q1";
  FETCH.reply = answer("tv-A", a.report);
  await api.requestFit();
  res.applied = snap();
  res.request = FETCH.calls[0] || null;
  res.calls = FETCH.calls.length;
  // 2. The same question again asks nothing.
  await api.requestFit();
  res.callsAfterRepeat = FETCH.calls.length;
  // 3. An answer computed for ANOTHER template (a base flip in between) is dropped.
  api.setFit({});
  boxes.forEach((box) => api.fitTxbx(box));
  QUESTION.q = "q2";
  FETCH.reply = answer("tv-B", a.report);
  await api.requestFit();
  res.stale = snap();
  // 4. An older answer arriving after a newer one is dropped: the newer says "shrunk", the older,
  //    released last, says "nothing shrinks" -- and must not undo it.
  let release1 = null, release2 = null;
  QUESTION.q = "q3";
  FETCH.reply = () => new Promise((r) => { release1 = r; });
  const p1 = api.requestFit();
  QUESTION.q = "q4";
  FETCH.reply = () => new Promise((r) => { release2 = r; });
  const p2 = api.requestFit();
  release2({ ok: true, json: () => Promise.resolve({ template_version: "tv-A", boxes: a.report }) });
  await p2;
  release1({ ok: true, json: () => Promise.resolve({ template_version: "tv-A", boxes: unshrunk }) });
  await p1;
  res.outOfOrder = snap();
  // 5. A failed request leaves the last good answer on the page.
  QUESTION.q = "q5";
  FETCH.reply = () => Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  await api.requestFit();
  res.afterFailure = snap();
  // 6. A newer answer that shrinks nothing takes every printed size off again.
  QUESTION.q = "q6";
  FETCH.reply = answer("tv-A", unshrunk);
  await api.requestFit();
  res.unshrunk = snap();
  return res;
}

(async () => {
  if (CASES.answers) out.answers = await runAnswers(CASES.answers);
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
