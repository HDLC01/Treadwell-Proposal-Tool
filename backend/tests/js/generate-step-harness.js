// 3 · GENERATE FILES (Hanz, 2026-10-28; reworked 2026-10-29), driven through the real pages.
//
// "If we have multiple base bids why does it only generate one file and why does it go back and
// forth from proposal to generate files" / "It should always generate the 3 proposals already" /
// "if we are on the generate files it should stay on that page until I click continue". Step 3
// (js/generate.js) now never leaves: a proposal whose document is older than its draft, or that has
// none, is composed by the Proposal step's own door in a HIDDEN same-origin iframe
// (proposal-review.html?d=<id>&compose=frame&frame=<token>), which shared.js keeps off the one
// localStorage blob every tab shares (FRAME); a stale or out-of-step child is caught up by the
// project's Refresh first.
//
// WHAT THIS PROVES, EXECUTED:
//   * STAGING'S SHAPE: Base Bid 1 with an outdated document, a stale Polish, a never-opened Room 2
//     ends 3 of 3 built, Refresh called once, one frame at a time, the address bar never moves, and
//     Room 2's default-wording backup is marked `proposal_auto_built` and built without the hold.
//   * ONE DRAFT, THE ESTIMATE CHANGED: composed in a frame at the new price, built, no navigation,
//     and this browser's copy takes the new document. Every arrival builds again.
//   * A FRAME TOUCHES NOTHING OF THE TAB'S: the shared localStorage and sessionStorage are byte for
//     byte the same after a frame ran, whether they hold this project or another one.
//   * A FRAME CANNOT SAVE OVER A NEWER SERVER COPY: a colleague's save landing while it works stops it.
//   * A STOPPED FRAME says why on its row and the page stays; a message from another origin is ignored.
//   * NO AUTO-REFRESH FROM A 'kept' COPY, and the tab's unsaved edit survives.
//   * A FAILED BUILD, a sent child Refresh will not move, a lost sibling, the pills and Back.
//   * A Files page never takes a walk record of the old "generate" kind.
//
// THE WORLD: files-door-harness.js's, from its own source (one browser, one stub server, the real
// shared.js per page load, the real continueToDone / composeForFiles). The Generate page is the real
// generate.js over the real shared.js, against a stub server that holds several drafts, answers
// /documents as main.py does and /proposals/refresh as the scenario says. A frame the page appends is
// opened as the real Proposal page in frame mode, and its postMessage reaches the page's listeners.
//
// Usage: node generate-step-harness.js [frontend-dir]  (a dir holding only SOME files: the rest are
// read from the real frontend, which is how test_generate_step.py breaks one file and goes red).
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const REAL_FRONT = path.resolve(__dirname, "..", "..", "..", "frontend");
const FRONT = process.argv[2] ? path.resolve(process.argv[2]) : REAL_FRONT;
const pick = (p) => (fs.existsSync(path.join(FRONT, p)) ? path.join(FRONT, p) : path.join(REAL_FRONT, p));
const read = (p) => fs.readFileSync(pick(p), "utf8").replace(/\r\n/g, "\n");

const RealDate = Date;
const FIXED = RealDate.UTC(2026, 9, 28, 15, 0, 0);
class FixedDate extends RealDate {
  constructor(...a) { if (a.length) super(...a); else super(FIXED); }
  static now() { return FIXED; }
}
global.Date = FixedDate;

const DOOR = fs.readFileSync(path.join(__dirname, "files-door-harness.js"), "utf8").replace(/\r\n/g, "\n");
const CUT = DOOR.indexOf("\n(async function () {");
if (CUT < 0) throw new Error("files-door-harness.js's scenarios moved; repoint this harness");
const W = new Function("require", "__dirname", "process",
  DOOR.slice(0, CUT) + "\nreturn { browser, local, openProposal, openDone, draft, tabs, copy, editElsewhere, lastContinue, load, storage, holdOther };")(
  require, __dirname, { argv: ["node", "files-door-harness.js", process.argv[2]] });

const SHARED = read("shared.js");
const CHAIN = read(path.join("js", "send-all-chain.js"));
const GENERATE = read(path.join("js", "generate.js"));
const HTML = read("generate.html");
const STATE_KEY = (/const STATE_KEY\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const DRAFT_ID_KEY = (/const DRAFT_ID_KEY\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const STAMP = (/const STAMP\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const copy = (x) => JSON.parse(JSON.stringify(x));
const webcrypto = require("crypto").webcrypto;
const KEY = "treadwell.sendall.chain";
const ORIGIN = "https://tool";
const settle = () => new Promise((r) => setImmediate(r));
const VERSION = "2026-10-28T10:00:00Z";            // every draft's updated_at, unless b.server.version
/** A document's identity as main._canonical_sha256 reads it: canonical JSON (sorted keys). */
const canon = (x) => JSON.stringify(x, (k, v) => (v && typeof v === "object" && !Array.isArray(v)
  ? Object.keys(v).sort().reduce((o, key) => { o[key] = v[key]; return o; }, {}) : v));

// The step pills, as generate.html marks them up.
const PILLS = (() => {
  const a = HTML.indexOf('<div class="progress">');
  const z = HTML.indexOf("</div>", a);
  if (a < 0 || z < 0) throw new Error("generate.html's step row moved; repoint this harness");
  return [...HTML.slice(a, z).matchAll(/<(a|span)\b([^>]*)>([^<]*)</g)].map((m) => ({
    tag: m[1], step: (/data-step="([^"]+)"/.exec(m[2]) || [])[1] || null,
    href: (/href="([^"]+)"/.exec(m[2]) || [])[1] || null, text: m[3].trim() }));
})();

/** A window `parent` for a frame page: the Generate page's own TWComposeFrames, its origin, and a
 *  postMessage that reaches `deliver` the way a browser delivers one (later, with the frame's origin
 *  and the frame's window as its source). */
function frameParent(getHost, deliver, getSource, log) {
  return {
    location: { origin: ORIGIN },
    get TWComposeFrames() { return getHost().TWComposeFrames; },
    postMessage: (msg, target) => {
      log.push({ msg: copy(msg), target });
      if (target !== ORIGIN) return;
      const ev = { data: copy(msg), origin: ORIGIN, source: getSource() };
      setImmediate(() => deliver(ev));
    },
  };
}

/** The real Generate page at `href` in browser `b`. Server: d1 is the world's (b.server.d1), every
 *  other draft is b.server.drafts[id]; b.server.view is the project's proposals strip. A frame it
 *  appends is opened as the real Proposal page (b.frameOpts[id]: openProposal's options, plus
 *  `forge`: a message from another origin delivered first). */
async function openGenerate(b, href) {
  const nav = [];
  const posted = [];
  const loc = { origin: ORIGIN };
  const set = (u) => {
    const x = new URL(String(u), ORIGIN);
    loc.href = x.href; loc.pathname = x.pathname; loc.search = x.search; loc.hash = x.hash;
  };
  set(href);
  const urls = [loc.pathname + loc.search];
  loc.assign = (u) => { nav.push(["assign", String(u)]); };
  loc.replace = (u) => { nav.push(["replace", String(u)]); };
  loc.reload = () => { nav.push(["reload"]); };
  const history = { state: null, replaceState: (s, t, u) => { if (u != null) { set(u); urls.push(loc.pathname + loc.search); } } };
  const json = (status, body) => Promise.resolve({
    ok: status < 400, status, statusText: status < 400 ? "OK" : "ERR",
    json: () => (body === undefined ? Promise.reject(new Error("not json")) : Promise.resolve(body)),
    text: () => Promise.resolve(JSON.stringify(body)) });
  const draftOf = (id) => (id === "d1" ? b.server.d1 : (b.server.drafts || {})[id]);
  const fetch = (url, opts) => {
    const method = (opts && opts.method) || "GET";
    const u = String(url).replace(/^https?:\/\/[^/]+/, "");
    let m = /^\/api\/draft\/([^/]+)\/proposals\/refresh$/.exec(u);
    if (m && method === "POST") {
      const body = JSON.parse((opts && opts.body) || "{}");
      (b.server.refreshes = b.server.refreshes || []).push({ id: decodeURIComponent(m[1]), body });
      if (!body.draft_version) return json(409, { ok: false, code: "document_changed", error: "no version" });
      const r = b.server.onRefresh ? b.server.onRefresh() : { refreshed: [], skipped: [] };
      if (r.error) return json(r.status || 409, { ok: false, error: r.error });
      return json(200, Object.assign({ ok: true, parent_id: "d1", estimate_digest: "E2", moved: [] }, r,
                                     { proposals: Object.assign({ ok: true }, copy(b.server.view)) }));
    }
    m = /^\/api\/draft\/([^/]+)\/proposals$/.exec(u);
    if (m) return b.server.view ? json(200, Object.assign({ ok: true }, copy(b.server.view))) : json(404, { ok: false });
    // main.py's render cache, as _render_documents keeps it: one render per document (its payload,
    // canonical), reused by every later build of the same document unless `rebuild` asks for a new
    // one; `pdf` once that render's PDF was made (_entry_pdf). Every build and every "held" answer
    // mints fresh download tokens (_documents_out); a token minted at or before `b.server.expireBefore`
    // has expired (a restart, an hour) and its file answers 404.
    const cache = b.server.cache = b.server.cache || {};
    const lastKey = b.server.lastKey = b.server.lastKey || {};
    const filesOf = (id, pp) => {
      const g = b.server.gen = (b.server.gen || 0) + 1;
      return { work_type: pp.work_type, audience: pp.audience,
               docx_download_url: "/api/file/" + id + "-D" + g, pdf_download_url: "/api/file/" + id + "-D" + g + "/pdf",
               xlsx_download_url: "/api/file/" + id + "-X" + g, render_id: "K-" + id,
               document_total: pp.values.total_formatted };
    };
    m = /^\/api\/draft\/([^/]+)\/documents\/held$/.exec(u);
    if (m && method === "POST") {
      // main.py api_draft_documents_held: the very saved copy, a document, its render cached with
      // all three files made; else not held.
      const id = decodeURIComponent(m[1]);
      const body = JSON.parse((opts && opts.body) || "{}");
      (b.server.checks = b.server.checks || []).push({ id, body });
      const d = draftOf(id);
      if (!d) return json(404, { detail: "Draft not found" });
      const no = json(200, { ok: true, held: false });
      if (!body.draft_version || body.draft_version !== (b.server.version || VERSION)) return no;
      const pp = d.proposal_payload;
      if (!(pp && pp.values)) return no;
      const c = cache[canon(pp)];
      if (!c || !c.pdf) return no;
      if (!d.generate_result) d.generate_result = { recorded: true };
      lastKey[id] = canon(pp);
      return json(200, { ok: true, held: true, files: filesOf(id, pp) });
    }
    m = /^\/api\/draft\/([^/]+)\/documents$/.exec(u);
    if (m && method === "POST") {
      const id = decodeURIComponent(m[1]);
      const body = JSON.parse((opts && opts.body) || "{}");
      posted.push({ id, body });
      const d = draftOf(id);
      if (!d) return json(404, { detail: "Draft not found" });
      const fail = (b.server.failDocs || {})[id];
      if (fail) return json(fail[0], { detail: fail[1] });
      const pp = d.proposal_payload;
      if (!(pp && pp.values)) {
        return json(422, { detail: "This proposal hasn't been built yet — open the Proposal step and press Continue." });
      }
      // main.py api_draft_documents: the generate_result is recorded only the first time.
      if (!d.generate_result) d.generate_result = { recorded: true };
      const key = canon(pp);
      if (body.rebuild || !cache[key]) {
        cache[key] = { pdf: false };
        (b.server.renders = b.server.renders || []).push({ id, payload: copy(pp), rebuild: !!body.rebuild });
      }
      lastKey[id] = key;
      return json(200, filesOf(id, pp));
    }
    m = /^\/api\/file\/([^/]+)-D(\d+)\/pdf$/.exec(u);
    if (m) {
      if (Number(m[2]) <= (b.server.expireBefore || 0)) return json(404, { detail: "File expired or already downloaded" });
      (b.server.pdfs = b.server.pdfs || []).push(m[1]);
      const fail = (b.server.failPdf || {})[m[1]];
      if (fail) return json(500, { detail: fail });
      if (cache[lastKey[m[1]]]) cache[lastKey[m[1]]].pdf = true;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new Error("not json")),
                               arrayBuffer: () => Promise.resolve(new TextEncoder().encode("%PDF " + m[1]).buffer) });
    }
    m = /^\/api\/file\/([^/]+)-(X|D)(\d+)$/.exec(u);
    if (m) {
      if (Number(m[3]) <= (b.server.expireBefore || 0)) return json(404, { detail: "File expired or already downloaded" });
      (b.server.fileGets = b.server.fileGets || []).push(m[1] + ":" + m[2]);
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.reject(new Error("not json")),
                               arrayBuffer: () => Promise.resolve(new TextEncoder().encode(m[2] + " " + m[1]).buffer) });
    }
    m = /^\/api\/draft\/([^/]+)$/.exec(u);
    if (m) {
      const id = decodeURIComponent(m[1]);
      if (method === "PUT") {
        const data = JSON.parse(opts.body).data;
        if (id === "d1") { b.server.puts.push(copy(data)); b.server.d1 = copy(data); }
        else b.server.drafts[id] = copy(data);
        return json(200, { ok: true });
      }
      const d = draftOf(id);
      return d ? json(200, { data: copy(d), updated_at: b.server.version || VERSION }) : json(404, { detail: "Draft not found" });
    }
    return json(200, {});
  };
  const nodes = {};
  const node = (id) => (nodes[id] = nodes[id] || { id, hidden: id === "gen-note" || id === "gen-empty",
    textContent: "", innerHTML: "", attrs: {}, listeners: [],
    setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; },
    addEventListener(ev, h) { this.listeners.push([ev, h]); } });
  ["gen-list", "gen-note", "gen-back", "gen-continue", "gen-empty", "gen-main", "gen-rebuild"].forEach(node);
  nodes["gen-rebuild"].hidden = true;
  nodes["gen-back"].attrs.href = "/estimate-review.html";
  nodes["gen-continue"].attrs.href = "/proposal-review.html";
  // Every line the progress note showed, in order.
  const notes = [];
  let noteText = "";
  Object.defineProperty(nodes["gen-note"], "textContent", { get: () => noteText, set: (v) => { noteText = v; notes.push(v); } });
  const pills = PILLS.filter((p) => p.tag === "a").map((p) => ({
    attrs: { "data-step": p.step, href: p.href }, text: p.text,
    getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; },
    setAttribute(k, v) { this.attrs[k] = String(v); } }));

  // ── the frames ──
  const winListeners = [];
  const frames = { opened: [], live: 0, maxLive: 0, nav: [], posts: [], errors: [], frameUrls: [], together: [] };
  const liveIds = new Set();
  const deliver = (ev) => winListeners.filter(([t]) => t === "message").forEach(([, h]) => h(ev));
  let sandbox = null;
  const body = {
    appendChild(el) {
      if (!el || el.tag !== "iframe") return;
      el.parentNode = body;
      frames.live++;
      frames.maxLive = Math.max(frames.maxLive, frames.live);
      const src = el.attrs.src;
      const id = new URL(src, ORIGIN).searchParams.get("d");
      frames.opened.push({ id, src, attrs: copy(el.attrs), className: el.className });
      // Which frames were on the page together, each time one opened.
      liveIds.add(id);
      el.__id = id;
      frames.together.push([...liveIds].sort());
      const parent = frameParent(() => sandbox.window, deliver, () => el.contentWindow, frames.posts);
      (async () => {
        const o = Object.assign({}, (b.frameOpts || {})[id] || {});
        const forge = o.forge;
        delete o.forge;
        const p = await W.openProposal(b, src, Object.assign(o, { frameParent: parent }));
        el.contentWindow = p.page.window;
        el.listeners.filter(([t]) => t === "load").forEach(([, h]) => h());
        if (forge) {
          // Another origin's page posting what a finished frame would say, as the frame's own window.
          const tok = new URL(src, ORIGIN).searchParams.get("frame");
          deliver({ data: { tw_compose_frame: tok, id, phase: "saved" }, origin: "https://evil.example",
                    source: el.contentWindow });
          await settle();
        }
        await p.scope.composeForFiles();
        frames.nav.push(...p.page.nav);
        // A page that navigated loads another page into the frame: its load event fires again.
        if (p.page.nav.length) el.listeners.filter(([t]) => t === "load").forEach(([, h]) => h());
        frames.frameUrls.push(p.page.loc.pathname + p.page.loc.search);
      })().catch((e) => frames.errors.push(String((e && e.stack) || e)));
    },
    removeChild(el) {
      if (el && el.tag === "iframe" && el.parentNode) { el.parentNode = null; frames.live--; liveIds.delete(el.__id); }
    },
  };
  // What the page saved through its download links: the file name and the bytes.
  const saved = [];
  const blobs = {};
  const document = {
    addEventListener() {}, removeEventListener() {},
    getElementById: (id) => nodes[id] || null,
    querySelectorAll: (sel) => (sel === ".progress a.step" ? pills : []),
    querySelector: () => null,
    createElement: (tag) => (tag === "iframe"
      ? { tag: "iframe", attrs: {}, listeners: [], parentNode: null, contentWindow: null, className: "",
          setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; },
          addEventListener(ev, h) { this.listeners.push([ev, h]); } }
      : { style: {}, appendChild() {}, setAttribute() {}, classList: { add() {}, remove() {} },
          click() { if (tag === "a") saved.push({ name: this.download, bytes: blobs[this.href] || null }); } }),
    createTextNode: () => ({}), head: { appendChild() {} }, body,
  };
  // A download saves a Blob through an object URL, as the page's download() does.
  class HBlob { constructor(parts) { this.text = parts.map((x) => Buffer.from(x).toString()).join(""); } }
  class HURL extends URL {
    static createObjectURL(bl) { const u = "blob:" + Object.keys(blobs).length; blobs[u] = bl.text; return u; }
    static revokeObjectURL() {}
  }
  sandbox = {
    console, JSON, Promise, Math, Date: FixedDate, Object, Array, String, Number, Error, URL: HURL,
    URLSearchParams, Map, Set, isFinite, Uint8Array, Blob: HBlob,
    localStorage: b.ls, sessionStorage: b.ss,
    // A timer gets an id, as a browser gives one, and never fires (a save is sent by flushState).
    setTimeout: (() => { let n = 0; return () => ++n; })(), clearTimeout: () => {},
    fetch, document,
  };
  sandbox.window = {
    location: loc, history, crypto: webcrypto, sessionStorage: b.ss, localStorage: b.ls, Date: FixedDate,
    addEventListener(ev, h) { winListeners.push([ev, h]); },
    removeEventListener(ev, h) { const i = winListeners.findIndex((x) => x[0] === ev && x[1] === h); if (i >= 0) winListeners.splice(i, 1); },
    TWAuth: { ready: Promise.resolve(), user: () => ({ name: "Kyle Loseke", email: "kyle@wetreadwell.com" }) },
  };
  sandbox.location = loc;
  sandbox.history = history;
  vm.createContext(sandbox);
  vm.runInContext(SHARED, sandbox);
  vm.runInContext(GENERATE, sandbox);
  await sandbox.window.TWGenerate.done;
  for (let i = 0; i < 5; i++) await settle();               // a frame's tail after it reported
  return snap();
  function snap() {
  const list = nodes["gen-list"].innerHTML;
  return {
    nav, posted, rows: sandbox.window.TWGenerate.rows(), notes,
    note: nodes["gen-note"].hidden ? "" : nodes["gen-note"].textContent,
    list, emptyShown: !nodes["gen-empty"].hidden,
    back: nodes["gen-back"].attrs.href, next: nodes["gen-continue"].attrs.href,
    nextDisabled: !!nodes["gen-continue"].attrs.disabled || !!nodes["gen-continue"].disabled,
    pills: Object.fromEntries(pills.map((p) => [p.attrs["data-step"], p.attrs.href])),
    url: loc.pathname + loc.search, urls,
    // Every file link the list offers, as "row:key".
    links: [...list.matchAll(/data-row="(\d+)" data-file="([a-z_]+)"/g)].map((x) => x[1] + ":" + x[2]),
    frames, refreshCalls: sandbox.window.TWGenerate.refreshCalls(),
    listening: winListeners.filter(([t]) => t === "message").length,
    rebuildShown: !nodes["gen-rebuild"].hidden, rebuildDisabled: !!nodes["gen-rebuild"].disabled,
    /** Press row `i`'s `key` file link, as a person clicks it in the list; resolves with what was
     *  saved (null when nothing) and the button's own text after. */
    download: async (i, key) => {
      const btn = { attrs: { "data-row": String(i), "data-file": key }, innerHTML: "link", textContent: "link",
                    disabled: false, getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; } };
      const before = saved.length;
      const click = nodes["gen-list"].listeners.find(([t]) => t === "click")[1];
      click({ target: { closest: (sel) => (sel === "button.gen-dl" ? btn : null) } });
      for (let k = 0; k < 40; k++) await settle();
      return { saved: saved.length > before ? saved[saved.length - 1] : null, text: btn.textContent };
    },
    /** Press "Rebuild all" and wait for the run it starts; resolves with the page as it is then. */
    rebuildAll: async () => {
      const click = nodes["gen-rebuild"].listeners.find(([t]) => t === "click")[1];
      click({});
      await sandbox.window.TWGenerate.running();
      for (let k = 0; k < 5; k++) await settle();
      return snap();
    },
  };
  }
}
const rowsBrief = (g) => g.rows.map((r) => ({ id: r.id, name: r.name, sheet: r.sheet, status: r.status,
                                              total: r.total, message: r.message, current: r.current }));
const frameBrief = (g) => ({ opened: g.frames.opened.map((f) => f.id), maxLive: g.frames.maxLive,
                             together: g.frames.together,
                             live: g.frames.live, nav: g.frames.nav, errors: g.frames.errors,
                             phases: g.frames.posts.map((p) => p.msg.id + ":" + p.msg.phase),
                             targets: [...new Set(g.frames.posts.map((p) => p.target))] });
function require_chain(b, loc, history) {
  const mod = { exports: {} };
  new Function("module", "window", CHAIN)(mod, undefined);
  return mod.exports.create({ sessionStorage: b.ss, location: loc, history: history || { replaceState() {} },
                              crypto: webcrypto, Date: FixedDate });
}

/** A browser whose d1 has been through a real Continue (its document holds). */
async function continued(make) {
  const b = W.browser(make ? make() : W.draft());
  await W.lastContinue(b);
  return b;
}

/** `blob` stamped as a Continue would have left it: its document's key over its own inputs. */
async function keyed(blob) {
  const p = await W.load(W.browser(blob), "/x.html?d=d1");
  const out = copy(blob);
  out.proposal_payload_key = p.TW.composeKey(copy(blob));
  return out;
}
/** A proposal of d1's estimate as Create Multiple Proposals makes it: the estimate copied, its own
 *  sheet as its base, no document (nobody opened it) unless `extra` gives one. */
function child(sheet, extra) {
  const d = W.draft();
  delete d.proposal_payload; delete d.generate_result; delete d.dropbox_result;
  d.priced_tabs = W.tabs(10000, 320).concat([{ id: "Room 2", name: "Room 2", role: "epoxy", kind: "base",
    total: 6000, sales_tax: 190, remodel: 0, system_desc: "Treadwell MACRO Flake", notes_auto: [],
    sf: { epoxy_sf: 600, cove_lf: 0 } }]);
  return Object.assign(d, { proposal_of: "d1", scope_group: { id: "G1", label: sheet }, base_tab_id: sheet,
                            estimate_digest: "E1" }, extra || {});
}
/** A document of `total` (as a Continue long ago left it), so a child's draft can hold one. */
function oldDoc(total, texture) {
  return { work_type: "epoxy", audience: "Direct", values: { total_formatted: total, texture: texture || "old" } };
}
function view(members) {
  return { parent_id: "d1", group_id: "G1", estimate_digest: "E1", members: members.map((m, i) => Object.assign({
    index: i + 1, is_parent: i === 0, stale: false, out_of_step: null, label: m.sheet_label,
    display_label: m.sheet_label }, m)) };
}
/** Staging's project (2026-10-29): Base Bid 1 Epoxy whose document is older than the estimate, a
 *  Polish whose copy of the estimate is stale, and a Room 2 nobody has opened (a GC scope with its
 *  words left blank, so its defaults are Kyle's placeholders). */
async function stagingProject() {
  const b = await continued();
  await W.editElsewhere(b, { texture: "Orange Peel", priced_tabs: W.tabs(12500, 400),
                             proposal_lump_sum: 12500, proposal_sales_tax: 400 });
  b.server.drafts = {
    c2: await keyed(child("Polish", { proposal_payload: oldDoc("$8,000.00", "before the change") })),
    c3: child("Room 2", { audience: "GC", scope_notes: "", schedule_notes: "", exclusions: "", architect: "" }),
  };
  b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish", stale: true },
                        { id: "c3", sheet_label: "Room 2" }]);
  // Refresh, as drafts.refresh_proposals does it: Polish re-copies the estimate and keeps its words.
  b.server.onRefresh = () => {
    b.server.drafts.c2 = Object.assign(copy(b.server.drafts.c2), { estimate_digest: "E2",
      priced_tabs: W.tabs(12500, 400).concat(b.server.drafts.c2.priced_tabs.slice(2)) });
    b.server.drafts.c3 = Object.assign(copy(b.server.drafts.c3), { estimate_digest: "E2" });
    b.server.view.members.forEach((m) => { m.stale = false; });
    return { refreshed: ["c2", "c3"], skipped: [] };
  };
  return b;
}

(async function () {
  const out = {};

  // ── ONE NAME (Hanz, 2026-10-29): GEN_NAMES_VIEW is the strip the SERVER answered (drafts.proposals_view, run by
  //    test_proposal_names.py on staging's shape and re-keyed to d1 / c2 / c3). Step 3 names each row by it, with no
  //    "(sheet)" after it. Only this scenario runs.
  if (process.env.GEN_NAMES_VIEW) {
    const b = await stagingProject();
    b.server.view = JSON.parse(process.env.GEN_NAMES_VIEW);
    b.server.onRefresh = () => ({ refreshed: [], skipped: [] });
    const g = await openGenerate(b, "/generate.html?d=d1");
    const text = g.list.replace(/<[^>]*>/g, "|").split("|").map((s) => s.trim()).filter(Boolean);
    process.stdout.write(JSON.stringify({ names: { rows: rowsBrief(g).map((r) => r.name), list: g.list, text } }));
    return;
  }

  // ── STAGING'S SHAPE: 3 OF 3, REFRESH ONCE, NEVER LEAVING ────────────────────────────────────
  {
    const b = await stagingProject();
    const putsBefore = b.server.puts.length;
    const g = await openGenerate(b, "/generate.html?d=d1");
    const c3 = b.server.drafts.c3;
    const total = (d) => ((d && d.proposal_payload && d.proposal_payload.values) || {}).total_formatted || null;
    out.staging = {
      // TWO FRAMES AT ONCE, EACH ON ITS OWN DRAFT: every save a frame made, as [draft, its sheet, the
      // total of the document it saved]; and this project's own saves made while the frames ran.
      framePuts: (b.server.otherPuts || []).map((p) => [p.id, (p.data.scope_group || {}).label || null, total(p.data)]),
      d1Puts: b.server.puts.slice(putsBefore).map((p) => [p.proposal_of || null, p.scope_group ? p.scope_group.label : null, total(p)]),
      rows: rowsBrief(g), nav: g.nav, url: g.url, urls: g.urls, frames: frameBrief(g),
      frameAttrs: g.frames.opened.map((f) => ({ className: f.className, inert: f.attrs.inert,
        hidden: f.attrs["aria-hidden"], tab: f.attrs.tabindex,
        src: f.src.replace(/frame=[0-9a-f]+/, "frame=TOK") })),
      refreshes: (b.server.refreshes || []).map((r) => ({ id: r.id, versioned: !!r.body.draft_version })),
      refreshCalls: g.refreshCalls,
      holds: Object.fromEntries(g.posted.map((p) => [p.id, p.body.hold_placeholders])),
      renders: (b.server.renders || []).map((r) => [r.id, r.payload.values.total_formatted]),
      note: g.note, notes: g.notes, links: g.links, next: g.next, listening: g.listening,
      c3: { mark: c3.proposal_auto_built === undefined ? null : c3.proposal_auto_built,
            payload: c3.proposal_payload, audience: c3.audience },
      c2Mark: b.server.drafts.c2.proposal_auto_built === undefined ? null : b.server.drafts.c2.proposal_auto_built,
      d1Mark: b.server.d1.proposal_auto_built === undefined ? null : b.server.d1.proposal_auto_built,
      // This browser's copy, after: the open project's, holding the document its frame composed.
      slotOwner: W.local(b)[STAMP], slotTotal: ((W.local(b).proposal_payload || {}).values || {}).total_formatted,
      slotIsServer: JSON.stringify(Object.assign(copy(b.server.d1), { [STAMP]: "d1" })) === b.ls.getItem(STATE_KEY)
        || (() => { const l = W.local(b); delete l[STAMP]; return JSON.stringify(Object.keys(l).sort()) === JSON.stringify(Object.keys(b.server.d1).sort()) && l.proposal_payload_key === b.server.d1.proposal_payload_key; })(),
    };
  }

  // ── ONE DRAFT, THE ESTIMATE CHANGED ────────────────────────────────────────────────────────
  {
    const b = await continued();
    const builtBefore = b.server.d1.proposal_payload.values.total_formatted;
    await W.editElsewhere(b, { texture: "Orange Peel", priced_tabs: W.tabs(12500, 400),
                               proposal_lump_sum: 12500, proposal_sales_tax: 400 });
    const g = await openGenerate(b, "/generate.html?d=d1");
    const rendered = (b.server.renders || []).map((r) => ({ id: r.id, texture: r.payload.values.texture,
                                                            total: r.payload.values.total_formatted }));
    out.oneDraft = {
      builtBefore, nav: g.nav, url: g.url, frames: frameBrief(g),
      rows: rowsBrief(g), rendered, links: g.links, note: g.note, next: g.next,
      mark: b.server.d1.proposal_auto_built === undefined ? null : b.server.d1.proposal_auto_built,
      slotTotal: ((W.local(b).proposal_payload || {}).values || {}).total_formatted,
      chainLeft: b.ss.getItem(KEY),
    };
    // REBUILT ON EVERY ARRIVAL: nothing changed since, so no frame, and the files are built again.
    const before = (b.server.renders || []).length;
    const again = await openGenerate(b, "/generate.html?d=d1");
    out.again = { nav: again.nav, rows: rowsBrief(again), posted: again.posted.map((p) => p.id),
                  newRenders: (b.server.renders || []).length - before, frames: again.frames.opened.length,
                  pdfs: (b.server.pdfs || []).length };
  }

  // ── A FRAME TOUCHES NOTHING OF THE TAB'S ───────────────────────────────────────────────────
  // The frame for Room 2 is the real Proposal page in frame mode, run directly, with this browser's
  // storage holding (a) this project, (b) another project another tab has open. Both stores are the
  // same, byte for byte, after it composed and saved Room 2.
  for (const which of ["thisProject", "otherProject"]) {
    const b = await continued();
    if (which === "otherProject") W.holdOther(b);
    b.ls.setItem("tw_nav_open", "1");
    b.ss.setItem("treadwell.proposal_tool.unverified", "d2");
    b.server.drafts = { c3: child("Room 2") };
    const lsBefore = b.ls.dump();
    const ssBefore = b.ss.dump();
    const posts = [];
    const seedFor = copy(b.server.drafts.c3);
    let seedTaken = 0;
    const host = { TWComposeFrames: { seed: (t) => (t === "a1b2c3d4e5f60718293a4b5c6d7e8f90" && !seedTaken++
      ? { id: "c3", data: seedFor } : null) } };
    let frameWin = null;
    const parent = frameParent(() => host, () => {}, () => frameWin, posts);
    const p = await W.openProposal(b, "/proposal-review.html?d=c3&compose=frame&frame=a1b2c3d4e5f60718293a4b5c6d7e8f90",
                                   { frameParent: parent });
    frameWin = p.page.window;
    await p.scope.composeForFiles();
    await settle();
    out["isolated_" + which] = {
      lsSame: b.ls.dump() === lsBefore, ssSame: b.ss.dump() === ssBefore,
      phases: posts.map((x) => x.msg.phase), targets: posts.map((x) => x.target), nav: p.page.nav,
      saved: !!(b.server.drafts.c3.proposal_payload && b.server.drafts.c3.proposal_payload.values),
      mark: b.server.drafts.c3.proposal_auto_built === undefined ? null : b.server.drafts.c3.proposal_auto_built,
      putsTo: (b.server.otherPuts || []).map((x) => x.id), d1Puts: b.server.puts.length,
      seedTaken,
    };
  }

  // ── A FRAME CANNOT SAVE OVER A NEWER SERVER COPY ───────────────────────────────────────────
  // Polish's document is older than its draft, so its frame composes it. The moment the frame has
  // first read Polish from the server, RJ saves Polish elsewhere: the frame's save asks again,
  // finds RJ's copy, and writes nothing.
  {
    const b = await continued();
    b.server.drafts = { c2: await keyed(child("Polish", { proposal_payload: oldDoc("$8,000.00") })) };
    b.server.drafts.c2.texture = "changed since its document";
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish" }]);
    let reads = 0;
    b.server.onGet = (oid) => {
      if (oid !== "c2" || ++reads !== 1) return;
      b.server.drafts.c2 = Object.assign(copy(b.server.drafts.c2), { scope_notes: "RJ's scope, saved elsewhere" });
    };
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.newer = { rows: rowsBrief(g), nav: g.nav, url: g.url, frames: frameBrief(g),
                  c2Scope: b.server.drafts.c2.scope_notes,
                  c2Doc: (b.server.drafts.c2.proposal_payload.values || {}).total_formatted,
                  putsTo: (b.server.otherPuts || []).map((x) => x.id),
                  posted: g.posted.map((p) => p.id), note: g.note };
  }

  // ── A STOPPED FRAME, AND A MESSAGE FROM ANOTHER ORIGIN ─────────────────────────────────────
  // Polish's template does not load, so its frame stops and says so. Before it does, a page of
  // another origin posts "saved" with Polish's token as the frame's own window: it is not listened to.
  {
    const b = await continued();
    b.server.drafts = { c2: child("Polish", { proposal_payload: oldDoc("$8,000.00") }) };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish" }]);
    b.frameOpts = { c2: { tpl: "", forge: true } };
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.stopped = { rows: rowsBrief(g), nav: g.nav, url: g.url, frames: frameBrief(g),
                    posted: g.posted.map((p) => p.id), note: g.note, next: g.next,
                    nextDisabled: g.nextDisabled, putsTo: (b.server.otherPuts || []).map((x) => x.id) };
  }

  // ── THIS BROWSER'S COPY IS NOT THE SAVED ONE: NO AUTO-REFRESH, AND NOTHING OF IT IS LOST ───
  // Kyle's tab holds an edit whose save never landed, and a colleague has saved the project since
  // ("kept"). Polish is stale: Refresh is not run. Gyp's document holds: built. Sealer's document is
  // older than its draft: its frame composes it without touching Kyle's copy.
  {
    const b = await continued();
    const mine = Object.assign(W.local(b), { notes_text: "Kyle's note, never saved" });
    b.ls.setItem(STATE_KEY, JSON.stringify(mine));
    b.server.d1 = Object.assign(copy(b.server.d1), { texture: "Saved by RJ" });
    b.server.drafts = { c2: await keyed(child("Polish", { proposal_payload: oldDoc("$8,000.00") })),
                        c4: await keyed(child("Gyp", { proposal_payload: oldDoc("$6,000.00") })),
                        c5: child("Room 2", { proposal_payload: oldDoc("$5,000.00") }) };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish", stale: true },
                          { id: "c4", sheet_label: "Gyp" }, { id: "c5", sheet_label: "Room 2" }]);
    b.server.onRefresh = () => ({ refreshed: ["c2"], skipped: [] });
    const slotBefore = b.ls.dump();
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.kept = { nav: g.nav, rows: rowsBrief(g), posted: g.posted.map((p) => p.id),
                 refreshes: (b.server.refreshes || []).length, refreshCalls: g.refreshCalls,
                 frames: frameBrief(g), localNote: W.local(b).notes_text, slotSame: b.ls.dump() === slotBefore };
  }

  // ── THIS BROWSER IS AHEAD: ITS LATE CHANGE IS SAVED FIRST, THEN BUILT ────────────────────────
  // Kyle typed a note whose save never landed, and nobody has saved the project since ("ahead").
  {
    const b = await continued();
    b.ls.setItem(STATE_KEY, JSON.stringify(Object.assign(W.local(b), { notes_text: "Kyle's note, saved late" })));
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.ahead = { rows: rowsBrief(g), nav: g.nav, serverNote: b.server.d1.notes_text,
                  docNote: (b.server.d1.proposal_payload.notes || []).join(" "),
                  frames: frameBrief(g), localNote: W.local(b).notes_text };
  }

  // ── A SENT CHILD REFRESH WILL NOT MOVE, A LOST SIBLING, A FAILED BUILD, A PDF ──────────────
  {
    const b = await continued();
    b.server.drafts = {
      c2: await keyed(child("Polish", { proposal_payload: oldDoc("$8,000.00") })),
      c3: await keyed(child("Seal", { proposal_payload: oldDoc("$9,000.00") })),
      c4: await keyed(child("Gyp", { proposal_payload: oldDoc("$6,000.00") })),
      c5: await keyed(child("Sealer", { proposal_payload: oldDoc("$7,000.00"), closed_lost: true })),
    };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish" },
                          { id: "c3", sheet_label: "Seal", out_of_step: "same_as_base" },
                          { id: "c4", sheet_label: "Gyp" }, { id: "c5", sheet_label: "Sealer" }]);
    b.server.onRefresh = () => ({ refreshed: [], skipped: [{ id: "c3", label: "Seal", code: "sent",
      message: "Seal: the customer already has this proposal, so it was not moved." }] });
    b.server.failDocs = { c2: [500, "Could not build the proposal document."] };
    b.server.failPdf = { c4: "Failed to render the PDF. Please try again." };
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.held = { nav: g.nav, rows: rowsBrief(g), posted: g.posted.map((p) => p.id), links: g.links,
                 refreshes: (b.server.refreshes || []).length, note: g.note, next: g.next,
                 nextDisabled: g.nextDisabled };
  }

  // ── A REFRESH THE SERVER REFUSES ───────────────────────────────────────────────────────────
  {
    const b = await continued();
    b.server.drafts = { c2: await keyed(child("Polish", { proposal_payload: oldDoc("$8,000.00") })) };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish", stale: true }]);
    b.server.onRefresh = () => ({ error: "Nothing changed. This project was saved again after this page read it.", status: 409 });
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.refused = { rows: rowsBrief(g), nav: g.nav, posted: g.posted.map((p) => p.id) };
  }

  // ── FROM THE CHILD'S STEP 3 ────────────────────────────────────────────────────────────────
  {
    const b = await continued();
    b.server.drafts = { c2: await keyed(child("Polish", { proposal_payload: oldDoc("$8,000.00") })),
                        c3: child("Room 2") };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish" },
                          { id: "c3", sheet_label: "Room 2" }]);
    b.ls.setItem(STATE_KEY, JSON.stringify(Object.assign(copy(b.server.drafts.c2), { [STAMP]: "c2" })));
    b.ls.setItem(DRAFT_ID_KEY, "c2");
    const g = await openGenerate(b, "/generate.html?d=c2");
    out.fromChild = { nav: g.nav, rows: rowsBrief(g), back: g.back, pills: g.pills, next: g.next,
                      url: g.url, slotOwner: W.local(b)[STAMP] };
  }

  // ── A WALK RECORD OF THE OLD "generate" KIND IS NOBODY'S ───────────────────────────────────
  {
    const b = W.browser(W.draft());
    b.ss.setItem(KEY, JSON.stringify({ token: "feedface", group: "d1", queue: [], built: ["d1"], labels: {},
      returnUrl: "/generate.html?d=d1", stash: null, expires: FIXED + 60000, done: true, kind: "generate" }));
    const files = require_chain(b, { pathname: "/done.html", search: "?d=d1&sendall_resume=feedface" }, { replaceState() {} });
    const took = files.take(new URLSearchParams("?d=d1&sendall_resume=feedface"), "d1");
    b.ss.setItem(KEY, JSON.stringify({ token: "beefcafe", group: "d1", queue: ["d1"], built: [], labels: {},
      returnUrl: "/generate.html?d=d1", stash: null, expires: FIXED + 60000, done: false, kind: "generate" }));
    const door = require_chain(b, { pathname: "/proposal-review.html", search: "?d=d1&compose=files&sendall=beefcafe" });
    out.oldKind = { took, progress: door.progress(new URLSearchParams("?d=d1&compose=files&sendall=beefcafe")),
                    next: door.nextHop(new URLSearchParams("?d=d1&compose=files&sendall=beefcafe")) };
  }

  // ── THE PILLS AND BACK ─────────────────────────────────────────────────────────────────────
  {
    const b = await continued();
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.pillsV1 = { pills: g.pills, back: g.back, next: g.next };
    const v2 = await continued(() => Object.assign(W.draft(), { polish_estimate: { version: 2 } }));
    const g2 = await openGenerate(v2, "/generate.html?d=d1");
    out.pillsV2 = { pills: g2.pills, back: g2.back, next: g2.next };
  }

  // ── ONLY WHAT CHANGED IS REBUILT (Hanz, 2026-10-29) ────────────────────────────────────────
  // Three proposals, all built on the first visit. RJ then rewrites Polish's scope and nothing else.
  // The next visit composes and builds Polish only; Epoxy and Room 2 are "Up to date", with working
  // links. A restart then expires every token: a link still downloads (it builds again first).
  // Then "Rebuild all" builds all three again, the cached renders notwithstanding.
  {
    const b = await continued();
    b.server.drafts = { c2: await keyed(child("Polish", { proposal_payload: oldDoc("$8,000.00") })),
                        c3: await keyed(child("Room 2", { proposal_payload: oldDoc("$6,000.00") })) };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish" },
                          { id: "c3", sheet_label: "Room 2" }]);
    const first = await openGenerate(b, "/generate.html?d=d1");
    b.server.drafts.c2 = Object.assign(copy(b.server.drafts.c2), { scope_notes: "RJ's new scope for the polish" });
    const rendersBefore = (b.server.renders || []).length;
    const pdfsBefore = (b.server.pdfs || []).length;
    const checksBefore = (b.server.checks || []).length;
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.onlyChanged = {
      first: { rows: rowsBrief(first), note: first.note, posted: first.posted.map((p) => p.id) },
      rows: rowsBrief(g), note: g.note, notes: g.notes.slice(), links: g.links, nav: g.nav,
      posted: g.posted.map((p) => p.id), frames: frameBrief(g).opened,
      rendered: (b.server.renders || []).slice(rendersBefore).map((r) => r.id),
      pdfs: (b.server.pdfs || []).slice(pdfsBefore),
      checked: (b.server.checks || []).slice(checksBefore).map((c) => [c.id, !!c.body.draft_version, c.body.hold_placeholders]),
      c2Scope: ((b.server.drafts.c2.proposal_payload || {}).values || {}).scope_notes || null,
      rebuildShown: g.rebuildShown, rebuildDisabled: g.rebuildDisabled,
      statusText: [...g.list.matchAll(/<span class="gen-status">([^<]*)<\/span>/g)].map((x) => x[1]),
    };
    // Its links work: Epoxy's .xlsx and Room 2's PDF, off the "Up to date" rows.
    const xlsx = await g.download(0, "xlsx_download_url");
    const pdf = await g.download(2, "pdf_download_url");
    const postedBefore = g.posted.length;
    // A RESTART: every token minted so far has expired.
    b.server.expireBefore = b.server.gen;
    const rendersMid = (b.server.renders || []).length;
    const healed = await g.download(0, "pdf_download_url");
    out.expired = { xlsx: xlsx.saved, pdf: pdf.saved, healed: healed.saved, healedText: healed.text,
                    posted: g.posted.slice(postedBefore).map((p) => [p.id, p.body.hold_placeholders, !!p.body.rebuild]),
                    rendered: (b.server.renders || []).length - rendersMid };
    // "REBUILD ALL".
    const rb = { renders: (b.server.renders || []).length, pdfs: (b.server.pdfs || []).length,
                 checks: (b.server.checks || []).length, posted: g.posted.length, frames: g.frames.opened.length };
    const r = await g.rebuildAll();
    out.rebuild = {
      rows: rowsBrief(r), note: r.note, nav: r.nav, links: r.links,
      posted: r.posted.slice(rb.posted).map((p) => [p.id, !!p.body.rebuild]),
      rendered: (b.server.renders || []).slice(rb.renders).map((x) => [x.id, x.rebuild]),
      pdfs: (b.server.pdfs || []).length - rb.pdfs, checks: (b.server.checks || []).length - rb.checks,
      frames: r.frames.opened.length - rb.frames, rebuildShown: r.rebuildShown, rebuildDisabled: r.rebuildDisabled,
    };
  }

  // ── AN ESTIMATE-ONLY CHANGE IS REBUILT ─────────────────────────────────────────────────────
  // Both built and cached. Then the Polish sheet is re-priced on the estimate ($8,000 -> $9,500): no
  // word of either proposal changed, and the server still holds each one's OLD document, rendered,
  // with its PDF. Polish's copy of the estimate is behind; Refresh re-copies it. Both are rebuilt;
  // neither may be called up to date off the old document.
  {
    const polishAt = (t) => W.tabs(10000, 320).map((x) => (x.id === "Polish" ? Object.assign(x, { total: t }) : x));
    const b = await continued();
    b.server.drafts = { c2: await keyed(child("Polish", { proposal_payload: oldDoc("$8,000.00") })) };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish" }]);
    const first = await openGenerate(b, "/generate.html?d=d1");
    await W.editElsewhere(b, { priced_tabs: polishAt(9500) });
    b.server.view.members[1].stale = true;
    b.server.onRefresh = () => {
      b.server.drafts.c2 = Object.assign(copy(b.server.drafts.c2), { estimate_digest: "E2",
        priced_tabs: polishAt(9500).concat(b.server.drafts.c2.priced_tabs.slice(2)) });
      b.server.view.members.forEach((m) => { m.stale = false; });
      return { refreshed: ["c2"], skipped: [] };
    };
    const rendersBefore = (b.server.renders || []).length;
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.estimateOnly = {
      first: rowsBrief(first).map((x) => [x.id, x.status, x.total]),
      rows: rowsBrief(g).map((x) => [x.id, x.status, x.total]), note: g.note,
      posted: g.posted.map((p) => p.id), frames: frameBrief(g).opened, refreshCalls: g.refreshCalls,
      rendered: (b.server.renders || []).slice(rendersBefore).map((x) => [x.id, x.payload.values.total_formatted]),
    };
  }

  // ── NO PROJECT ─────────────────────────────────────────────────────────────────────────────
  {
    const b = W.browser({});
    const g = await openGenerate(b, "/generate.html");
    out.empty = { emptyShown: g.emptyShown, posted: g.posted.length, nav: g.nav };
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
