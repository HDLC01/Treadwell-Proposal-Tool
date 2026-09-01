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
  addEventListener(type, f) { (this._listeners[type] = this._listeners[type] || []).push(f); }
  dispatchEvent(e) {
    let cur = this;
    e.target = this;
    while (cur) { for (const f of (cur._listeners[e.type] || []).slice()) f(e); cur = cur.parentNode; }
    return true;
  }
}

class Ev {
  constructor(type, opts) { this.type = String(type); this.bubbles = !!(opts && opts.bubbles); this.target = null; }
}

// ── the fixtures ─────────────────────────────────────────────────────────────
/* A cover letter as the endpoint describes it: the DATE anchored in its own text box over the
 * letterhead artwork (block 0, txbx 0), the body flowing beneath (blocks 1..3). This is Kyle's
 * real shape — `docs/Cover Letter/Treadwell Cover Letter - Example1.docx` carries exactly one
 * anchored box and it holds the date. */
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

const PAGE = { w_pt: 612, h_pt: 792, margin: { top: 72, left: 90, right: 90, bottom: 72 } };
const ART = [{ name: "image1.png", para_index: 0, x_pt: 0, y_pt: 0, w_pt: 612, h_pt: 792 }];

const GEO_POSITIONED = { page: PAGE, images: ART, boxes: [{ id: 0, x_pt: 396, y_pt: 158.4, w_pt: 144, h_pt: 18 }] };
// What the endpoint served BEFORE the date box was baked into the templates: a letter with no
// boxes at all. Still a first-class layout, not a failure mode.
const GEO_FLOW = { page: PAGE, images: ART, boxes: [] };

const TOKENS = { proposal_date: "8/26/26", job_name: "Olathe Fire Station 4" };
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

  // The three elements the page provides. Real, and mounted in the body, so `isConnected` and
  // the class toggles mean what they mean in the browser.
  const mk = (id, tag) => { const e = new El(tag || "div", doc); e.attrs.id = id; byId.set(id, e); doc.body.appendChild(e); return e; };
  const docSurface = mk("doc-surface");
  const surface = mk("cl-surface");
  surface.classList.add("cl-offstage");
  const tabs = mk("doc-tabs");
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

  const win = {
    Node, console, JSON, Promise, Map, Set, Array, Object, String, Number, Boolean, Error,
    RegExp, Date, Math, FileReader: null,
    document: doc,
    Event: Ev,
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
    computeTokenValues: opts.noTokens ? undefined : () => JSON.parse(JSON.stringify(TOKENS)),
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
    look(id) {
      const el = surface.querySelector('.tw-block[data-id="' + id + '"]');
      if (!el) return null;
      return { text: el.textContent, cls: el.className, editable: el.contentEditable,
               boxed: !!el.closest(".tw-txbx") };
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

  console.log(JSON.stringify(out));
})().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
