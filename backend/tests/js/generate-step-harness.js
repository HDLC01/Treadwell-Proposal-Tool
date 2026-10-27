// 3 · GENERATE FILES (Hanz, 2026-10-28), driven through the real pages.
//
// "Every time we would have a backup or a safety net that it would generate the files every time we
// change something in the estimate." The wizard is 1 Intake, 2 Estimate, 3 Generate Files,
// 4 Proposal, 5 Files, and every arrival at step 3 builds the files of every live proposal of the
// project (js/generate.js).
//
// WHAT THIS PROVES, EXECUTED:
//   * ONE DRAFT, THE ESTIMATE CHANGED: the page walks the tab through the Proposal step's own door
//     (send-all-chain.js, kind "generate"), the door composes the document from the estimate as it
//     stands and comes back, and the page builds the files from THAT document, at the new price. The
//     walk leaves `proposal_auto_built` alone, and a Files page cannot take a generate walk.
//   * REBUILT ON EVERY ARRIVAL: a second visit with nothing changed builds again (no walk).
//   * THREE PROPOSALS, ONE NEVER OPENED: the parent and the opened child are built, each from its own
//     document at its own sheet's price; the never-opened one is not composed unattended and says it is
//     built on the Proposal step. No walk starts.
//   * A FAILED BUILD: the row says the server's sentence, the others are still built, and Continue
//     still leads to the Proposal step. A PDF that cannot be made fails its row the same way.
//   * A PAGE THAT CAME BACK FROM A WALK NEVER WALKS AGAIN (a forged or expired resume).
//   * THE PILLS AND BACK: spreadsheet draft, v2 draft, and a proposal child (its parent's estimate).
//
// THE WORLD: files-door-harness.js's, from its own source (one browser, one stub server, the real
// shared.js per page load, the real continueToDone / composeForFiles). The Generate page is the real
// generate.js over the real shared.js and send-all-chain.js, against a stub server that holds several
// drafts and answers /documents as main.py does (the document's own Total, 422 with no document).
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
  DOOR.slice(0, CUT) + "\nreturn { browser, local, openProposal, openDone, draft, tabs, copy, editElsewhere, lastContinue, load };")(
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

// The step pills, as generate.html marks them up.
const PILLS = (() => {
  const a = HTML.indexOf('<div class="progress">');
  const z = HTML.indexOf("</div>", a);
  if (a < 0 || z < 0) throw new Error("generate.html's step row moved; repoint this harness");
  return [...HTML.slice(a, z).matchAll(/<(a|span)\b([^>]*)>([^<]*)</g)].map((m) => ({
    tag: m[1], step: (/data-step="([^"]+)"/.exec(m[2]) || [])[1] || null,
    href: (/href="([^"]+)"/.exec(m[2]) || [])[1] || null, text: m[3].trim() }));
})();

/** The real Generate page at `href` in browser `b`. Server: d1 is the world's (b.server.d1), every
 *  other draft is b.server.drafts[id]; b.server.view is the project's proposals strip. */
async function openGenerate(b, href) {
  const nav = [];
  const posted = [];
  const loc = { origin: "https://tool" };
  const set = (u) => {
    const x = new URL(String(u), "https://tool");
    loc.href = x.href; loc.pathname = x.pathname; loc.search = x.search; loc.hash = x.hash;
  };
  set(href);
  loc.assign = (u) => { nav.push(["assign", String(u)]); };
  loc.replace = (u) => { nav.push(["replace", String(u)]); };
  loc.reload = () => { nav.push(["reload"]); };
  const history = { state: null, replaceState: (s, t, u) => { if (u != null) set(u); } };
  const json = (status, body) => Promise.resolve({
    ok: status < 400, status, statusText: status < 400 ? "OK" : "ERR",
    json: () => (body === undefined ? Promise.reject(new Error("not json")) : Promise.resolve(body)),
    text: () => Promise.resolve(JSON.stringify(body)) });
  const draftOf = (id) => (id === "d1" ? b.server.d1 : (b.server.drafts || {})[id]);
  const fetch = (url, opts) => {
    const method = (opts && opts.method) || "GET";
    const u = String(url).replace(/^https?:\/\/[^/]+/, "");
    let m = /^\/api\/draft\/([^/]+)\/proposals$/.exec(u);
    if (m) return b.server.view ? json(200, Object.assign({ ok: true }, copy(b.server.view))) : json(404, { ok: false });
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
      (b.server.renders = b.server.renders || []).push({ id, payload: copy(pp) });
      return json(200, { work_type: pp.work_type, audience: pp.audience,
                         docx_download_url: "/api/file/" + id + "-D", pdf_download_url: "/api/file/" + id + "-D/pdf",
                         xlsx_download_url: "/api/file/" + id + "-X", render_id: "K-" + id,
                         document_total: pp.values.total_formatted });
    }
    m = /^\/api\/file\/([^/]+)-D\/pdf$/.exec(u);
    if (m) {
      (b.server.pdfs = b.server.pdfs || []).push(m[1]);
      const fail = (b.server.failPdf || {})[m[1]];
      return fail ? json(500, { detail: fail }) : json(200, undefined);
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
      return d ? json(200, { data: copy(d), updated_at: "2026-10-28T10:00:00Z" }) : json(404, { detail: "Draft not found" });
    }
    return json(200, {});
  };
  const nodes = {};
  const node = (id) => (nodes[id] = nodes[id] || { id, hidden: id === "gen-note" || id === "gen-empty",
    textContent: "", innerHTML: "", attrs: {}, listeners: [],
    setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; },
    addEventListener(ev, h) { this.listeners.push([ev, h]); } });
  ["gen-list", "gen-note", "gen-back", "gen-continue", "gen-empty", "gen-main"].forEach(node);
  nodes["gen-back"].attrs.href = "/estimate-review.html";
  nodes["gen-continue"].attrs.href = "/proposal-review.html";
  const pills = PILLS.filter((p) => p.tag === "a").map((p) => ({
    attrs: { "data-step": p.step, href: p.href }, text: p.text,
    getAttribute(k) { return this.attrs[k] == null ? null : this.attrs[k]; },
    setAttribute(k, v) { this.attrs[k] = String(v); } }));
  const document = {
    addEventListener() {}, removeEventListener() {},
    getElementById: (id) => nodes[id] || null,
    querySelectorAll: (sel) => (sel === ".progress a.step" ? pills : []),
    querySelector: () => null,
    createElement: () => ({ style: {}, appendChild() {}, setAttribute() {}, click() {},
                            classList: { add() {}, remove() {} } }),
    createTextNode: () => ({}), head: { appendChild() {} }, body: { appendChild() {}, removeChild() {} },
  };
  const sandbox = {
    console, JSON, Promise, Math, Date: FixedDate, Object, Array, String, Number, Error, URL,
    URLSearchParams, Map, Set, isFinite, Uint8Array,
    localStorage: b.ls, sessionStorage: b.ss,
    setTimeout: () => 0, clearTimeout: () => {},
    fetch, document,
  };
  sandbox.window = {
    location: loc, history, crypto: webcrypto, sessionStorage: b.ss, localStorage: b.ls, Date: FixedDate,
    addEventListener() {},
    TWAuth: { ready: Promise.resolve(), user: () => ({ name: "Kyle Loseke", email: "kyle@wetreadwell.com" }) },
  };
  sandbox.location = loc;
  sandbox.history = history;
  vm.createContext(sandbox);
  vm.runInContext(SHARED, sandbox);
  vm.runInContext(CHAIN, sandbox);
  vm.runInContext(GENERATE, sandbox);
  await sandbox.window.TWGenerate.done;
  const list = nodes["gen-list"].innerHTML;
  return {
    nav, posted, rows: sandbox.window.TWGenerate.rows(),
    note: nodes["gen-note"].hidden ? "" : nodes["gen-note"].textContent,
    list, emptyShown: !nodes["gen-empty"].hidden,
    back: nodes["gen-back"].attrs.href, next: nodes["gen-continue"].attrs.href,
    nextDisabled: !!nodes["gen-continue"].attrs.disabled || !!nodes["gen-continue"].disabled,
    pills: Object.fromEntries(pills.map((p) => [p.attrs["data-step"], p.attrs.href])),
    url: loc.pathname + loc.search,
    // Every file link the list offers, as "row:key".
    links: [...list.matchAll(/data-row="(\d+)" data-file="([a-z_]+)"/g)].map((x) => x[1] + ":" + x[2]),
    chain: sandbox.window.TWSendAll,
  };
}
const rowsBrief = (g) => g.rows.map((r) => ({ id: r.id, name: r.name, sheet: r.sheet, status: r.status,
                                              total: r.total, message: r.message, current: r.current }));

/** Follow the Generate page through any walk it starts, the way the browser would, until it settles. */
async function arriveAtGenerate(b, href, doorOpts) {
  const stops = [];
  let url = href;
  for (let hop = 0; hop < 6 && url; hop++) {
    if (url.indexOf("/proposal-review.html") === 0) {
      const p = await W.openProposal(b, url, doorOpts);
      p.page.window.TWSendAll = require_chain(b, p.page.loc, p.page.history);
      const said = [];
      const btn = p.nodes["generate-btn"];
      let text = btn.textContent;
      Object.defineProperty(btn, "textContent", { get: () => text, set: (v) => { text = v; said.push(v); } });
      await p.scope.composeForFiles();
      stops.push({ page: "proposal", nav: p.page.nav.slice(), said, note: p.nodes["resync-note-head"].textContent });
      const next = p.page.nav[p.page.nav.length - 1];
      url = next ? next[1].replace(/^https?:\/\/[^/]+/, "") : null;
      continue;
    }
    const g = await openGenerate(b, url);
    stops.push({ page: "generate", nav: g.nav.slice(), url: g.url });
    const next = g.nav[g.nav.length - 1];
    if (!next) return { stops, g };
    url = next[0] === "reload" ? url : next[1].replace(/^https?:\/\/[^/]+/, "");
  }
  return { stops, g: null };
}
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
function childDoc(total, sheet, extra) {
  return Object.assign({ project_name: "Door Test", job_name: "Door Test", work_type: "epoxy", audience: "Direct",
    proposal_of: "d1", scope_group: { id: "G1", label: sheet }, base_tab_id: sheet,
    proposal_lump_sum: total, estimate_digest: "E1",
    proposal_payload: { work_type: "epoxy", audience: "Direct",
                        values: { total_formatted: "$" + total.toLocaleString("en-US") + ".00", sheet } } },
    extra || {});
}
function view(members) {
  return { parent_id: "d1", group_id: "G1", estimate_digest: "E1", members: members.map((m, i) => Object.assign({
    index: i + 1, is_parent: i === 0, stale: false, out_of_step: null, label: m.sheet_label,
    display_label: m.sheet_label }, m)) };
}

(async function () {
  const out = {};

  // ── ONE DRAFT, THE ESTIMATE CHANGED ────────────────────────────────────────────────────────
  {
    const b = await continued();
    const builtBefore = b.server.d1.proposal_payload.values.total_formatted;
    await W.editElsewhere(b, { texture: "Orange Peel", priced_tabs: W.tabs(12500, 400),
                               proposal_lump_sum: 12500, proposal_sales_tax: 400 });
    const walk = await arriveAtGenerate(b, "/generate.html?d=d1");
    const g = walk.g;
    const rendered = (b.server.renders || []).map((r) => ({ id: r.id, texture: r.payload.values.texture,
                                                            total: r.payload.values.total_formatted }));
    // A Files page (Send all's kind) asked for the same finished walk gets nothing.
    out.oneDraft = {
      builtBefore, stops: walk.stops.map((s) => ({ page: s.page, nav: s.nav, said: s.said || null })),
      rows: g && rowsBrief(g), rendered, links: g && g.links, note: g && g.note,
      mark: b.server.d1.proposal_auto_built === undefined ? null : b.server.d1.proposal_auto_built,
      chainLeft: b.ss.getItem(KEY), url: g && g.url, next: g && g.next,
    };
    // REBUILT ON EVERY ARRIVAL: nothing changed since, so no walk, and the files are built again.
    const before = (b.server.renders || []).length;
    const again = await openGenerate(b, "/generate.html?d=d1");
    out.again = { nav: again.nav, rows: rowsBrief(again), posted: again.posted.map((p) => p.id),
                  newRenders: (b.server.renders || []).length - before,
                  pdfs: (b.server.pdfs || []).length };
  }

  // ── A FILES PAGE NEVER TAKES A GENERATE WALK ───────────────────────────────────────────────
  {
    const b = await continued();
    await W.editElsewhere(b, { texture: "Knockdown" });
    const g = await openGenerate(b, "/generate.html?d=d1");
    const door = (g.nav[0] || [])[1] || "";
    const tok = (/sendall=([0-9a-f]+)/.exec(door) || [])[1] || "";
    const p = await W.openProposal(b, door.replace(/^https?:\/\/[^/]+/, ""));
    p.page.window.TWSendAll = require_chain(b, p.page.loc, p.page.history);
    await p.scope.composeForFiles();
    const params = new URLSearchParams("?d=d1&sendall_resume=" + tok);
    const files = require_chain(b, { pathname: "/done.html", search: "?d=d1&sendall_resume=" + tok }, { replaceState() {} });
    out.kinds = { door: door.replace(/sendall=[0-9a-f]+/, "sendall=TOK"), doorNav: p.page.nav.slice(),
                  filesTook: files.take(params, "d1") };
  }

  // ── A PAGE THAT CAME BACK NEVER WALKS AGAIN ────────────────────────────────────────────────
  {
    const b = await continued();
    await W.editElsewhere(b, { texture: "Knockdown" });
    const g = await openGenerate(b, "/generate.html?d=d1&sendall_resume=feedface");
    out.forgedResume = { nav: g.nav, rows: rowsBrief(g), posted: g.posted.map((p) => p.id) };
  }

  // ── THREE PROPOSALS, ONE NEVER OPENED ──────────────────────────────────────────────────────
  {
    const b = await continued();
    b.server.drafts = {
      c2: await keyed(childDoc(14000, "Polish")),
      c3: Object.assign(childDoc(9000, "Seal"), { proposal_payload: undefined }),
    };
    delete b.server.drafts.c3.proposal_payload;
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish" },
                          { id: "c3", sheet_label: "Seal" }]);
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.three = { nav: g.nav, rows: rowsBrief(g), posted: g.posted.map((p) => p.id), links: g.links,
                  holdAsked: g.posted.every((p) => p.body.hold_placeholders === true),
                  renders: (b.server.renders || []).map((r) => [r.id, r.payload.values.total_formatted]),
                  note: g.note, next: g.next, nextDisabled: g.nextDisabled };
    // The same project opened from the CHILD's step 3: the same list, built the same way.
    b.ls.setItem(STATE_KEY, JSON.stringify(Object.assign(copy(b.server.drafts.c2), { [STAMP]: "c2" })));
    b.ls.setItem(DRAFT_ID_KEY, "c2");
    const fromChild = await openGenerate(b, "/generate.html?d=c2");
    out.fromChild = { nav: fromChild.nav, rows: rowsBrief(fromChild), back: fromChild.back,
                      pills: fromChild.pills, next: fromChild.next };
  }

  // ── A FAILED BUILD, AND A PDF THAT COULD NOT BE MADE ───────────────────────────────────────
  {
    const b = await continued();
    b.server.drafts = { c2: await keyed(childDoc(14000, "Polish")), c4: await keyed(childDoc(6000, "Gyp")) };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish" },
                          { id: "c4", sheet_label: "Gyp" }]);
    b.server.failDocs = { c2: [500, "Could not build the proposal document."] };
    b.server.failPdf = { c4: "Failed to render the PDF. Please try again." };
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.failed = { nav: g.nav, rows: rowsBrief(g), links: g.links, note: g.note, next: g.next,
                   nextDisabled: g.nextDisabled };
  }

  // ── A STALE OR OUT-OF-STEP CHILD, AND A LOST SIBLING ───────────────────────────────────────
  {
    const b = await continued();
    b.server.drafts = { c2: await keyed(childDoc(14000, "Polish")), c3: await keyed(childDoc(9000, "Seal")),
                        c5: await keyed(childDoc(7000, "Sealer", { closed_lost: true })) };
    b.server.view = view([{ id: "d1", sheet_label: "Epoxy" }, { id: "c2", sheet_label: "Polish", stale: true },
                          { id: "c3", sheet_label: "Seal", out_of_step: "same_as_base" },
                          { id: "c5", sheet_label: "Sealer" }]);
    const g = await openGenerate(b, "/generate.html?d=d1");
    out.held = { nav: g.nav, rows: rowsBrief(g), posted: g.posted.map((p) => p.id) };
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

  // ── NO PROJECT ─────────────────────────────────────────────────────────────────────────────
  {
    const b = W.browser({});
    const g = await openGenerate(b, "/generate.html");
    out.empty = { emptyShown: g.emptyShown, posted: g.posted.length, nav: g.nav };
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
