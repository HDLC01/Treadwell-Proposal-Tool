// The Files page's one door, driven end to end: every way into the Files step rebuilds the
// document from the draft as it stands, and a document that is already current is left alone.
//
// Hanz, 2026-09-25: "Clicking to Done should regenerate and make the proposal correctly." Only the
// Proposal step's Continue composed a `proposal_payload`, so a texture picked on the Estimate step,
// a re-price, a note, the tax mode or a base flip reached Files — by a step pill, the Polish beta's
// Files link, View files, a reload — with the document from the LAST Continue. Now:
//   * continueToDone stamps the draft with TW.composeKey (the inputs + the document) as it writes;
//   * the Files page recomputes the key on arrival, and sends a draft whose document is not
//     current through the Proposal step (`?compose=files`), which presses Continue for it and
//     comes straight back (`composed=1`);
//   * the Estimate step's pills save the sheet the way its buttons do.
//
// EXECUTED, NOT READ. The real shared.js runs whole, one fresh vm context PER PAGE LOAD against one
// browser's localStorage and one stub server, so its real setState / flushState / composeKey /
// initDraftSync decide what is stored and PUT. Out of proposal-review.js the real pricing path
// runs — rebuildPricing, the page-init lump block, computeTokenValues, continueToDone and
// composeForFiles — over a form built from the page's own <form> markup and filled by the real
// TW.writeForm. Out of done.js the real filesMode / composedHere lines, the real mode decider and
// the real freshDocuments run. The only seams are the document editor's (a mounted template:
// templateVersion, collectOverrides, collectBoxOverrides, sheetSystems) and the price preview
// repaint, because they need a rendered page; everything that decides the payload is shipped code.
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const FRONT = path.join(ROOT, "frontend");
const read = (p) => fs.readFileSync(path.join(FRONT, p), "utf8").replace(/\r\n/g, "\n");
const SHARED = read("shared.js");
const PROPOSAL = read(path.join("js", "proposal-review.js"));
const DONE = read(path.join("js", "done.js"));
const ESTIMATE = read(path.join("js", "estimate-review.js"));
const HTML = read("proposal-review.html");
const NL = "\n";

function gone(what, where) {
  throw new Error(what + " could not be lifted out of " + where + ". Repoint this harness; do not "
    + "delete the scenarios.");
}
function grab(src, re, what, where) {
  const m = re.exec(src);
  if (!m) gone(what, where);
  return m[0];
}
/** A `function name(...) {...}` (or `async function`) at the page's two-space indent. */
function fn(src, name, where) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) gone(name + "()", where);
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index + 1, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}
/** The body of the first `(async () => {` / `(() => {` after an anchor string. */
function iifeBody(src, anchor, opener, where) {
  const a = src.indexOf(anchor);
  if (a < 0) gone("the block after " + JSON.stringify(anchor), where);
  const k = src.indexOf(opener, a);
  if (k < 0) gone("the IIFE after " + JSON.stringify(anchor), where);
  let depth = 1;
  const start = k + opener.length;
  for (let j = start; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(start, j);
  }
  throw new Error("unbalanced braces after " + anchor);
}

// ── the Proposal step's composition, lifted in dependency order ──────────────────────────────
const P = "proposal-review.js";
const PROPOSAL_UNITS = [
  grab(PROPOSAL, /^  const GYP_BASE = .*$/m, "GYP_BASE", P),
  grab(PROPOSAL, /^  const fmtUSD = [\s\S]*?;$/m, "fmtUSD", P),
  grab(PROPOSAL, /^  const fmtSF = .*$/m, "fmtSF", P),
  grab(PROPOSAL, /^  const fmtUSDdoc = .*$/m, "fmtUSDdoc", P),
  fn(PROPOSAL, "effectiveWorkType", P),
  grab(PROPOSAL, /^  const OPTION_ONLY_ROLES = [\s\S]*?COMBINED_BASE_ROLES\.has\(roleOfTab\(t\)\);$/m,
       "the base-role helpers", P),
  fn(PROPOSAL, "baseAreaFrom", P),
  fn(PROPOSAL, "rebuildPricing", P),
  fn(PROPOSAL, "taxTreatmentMode", P),
  fn(PROPOSAL, "printedTaxRows", P),
  fn(PROPOSAL, "baseBidFigure", P),
  grab(PROPOSAL, /^  const COMPUTED_PRICE_LINE_KEYS = .*$/m, "COMPUTED_PRICE_LINE_KEYS", P),
  fn(PROPOSAL, "looksLikeComputedPriceLine", P),
  grab(PROPOSAL, /^  let _povTimer = .*$/m, "_povTimer", P),
  fn(PROPOSAL, "queuePovSave", P),
  fn(PROPOSAL, "lineOverride", P),
  fn(PROPOSAL, "comboSystemLines", P),
  fn(PROPOSAL, "comboLinesForPayload", P),
  fn(PROPOSAL, "computeTokenValues", P),
  grab(PROPOSAL, /^  const PAYLOAD_PRICING_KEYS = \[[\s\S]*?\];$/m, "PAYLOAD_PRICING_KEYS", P),
  fn(PROPOSAL, "baseDescLabel", P),
  fn(PROPOSAL, "pruneComputedPriceLineOverrides", P),
  fn(PROPOSAL, "syncPayloadPricing", P),
  grab(PROPOSAL, /^  const overrideKey = .*$/m, "overrideKey", P),
  fn(PROPOSAL, "mergeOverrideEntry", P),
  grab(PROPOSAL, /^  const liveKey = \(name\) => \{[\s\S]*?\n  \};$/m, "liveKey", P),
  fn(PROPOSAL, "repaintNote", P),
  fn(PROPOSAL, "sayTheSaveIsBlocked", P),
  grab(PROPOSAL, /^  let _persistTimer = .*$/m, "_persistTimer", P),
  fn(PROPOSAL, "continueToDone", P),
  fn(PROPOSAL, "composeForFiles", P),
].join(NL);
// The page-init block that creates #tb-total from the snapshotted lump sum, verbatim.
const LUMP = iifeBody(PROPOSAL, "// Lump sum = the estimate sheet's own TOTAL LUMP SUM", "(() => {", P);

const PAGE_BODY = [
  "let templateVersion = __tv0;",
  PROPOSAL_UNITS,
  "function __initLump() {" + LUMP + "}",
  "return { rebuildPricing, continueToDone, composeForFiles, __initLump,",
  "  setTemplateVersion: (v) => { templateVersion = v; },",
  // The form's debounced persist, as the page arms it: it writes a patch of the module snapshot's
  // payload. Armed from here so the scenario can put one in flight when Continue runs.
  "  armPersist: (write, ms) => { _persistTimer = setTimeout(write, ms); } };",
].join(NL);
const makeProposalScope = new Function(
  "state", "form", "document", "TW", "window", "TWAuth", "templateBlocks",
  "collectOverrides", "collectBoxOverrides", "sheetSystems", "refreshPriceDisplay",
  "_firstDocLoad", "_notesReady", "setTimeout", "clearTimeout", "__tv0", PAGE_BODY);

// The page's own <form>: every named field, with the type and default value the markup gives it.
const FORM_HTML = (() => {
  const a = HTML.indexOf('<form id="proposal-form">');
  if (a < 0) gone("the proposal form", "proposal-review.html");
  return HTML.slice(a, HTML.indexOf("</form>", a));
})();
const FIELDS = [...FORM_HTML.matchAll(/<(input|select|textarea)\b([^>]*)>/g)].map((m) => {
  const attr = (n) => ((new RegExp("\\b" + n + '="([^"]*)"').exec(m[2]) || [])[1]);
  return { name: attr("name"), type: m[1] === "input" ? (attr("type") || "text") : m[1],
           value: attr("value") || "" };
}).filter((f) => f.name);

// ── the Files page, lifted ───────────────────────────────────────────────────────────────────
const D = "done.js";
const DONE_BODY = [
  grab(DONE, /^  const filesMode = \(\(\) => \{[\s\S]*?\n  \}\)\(\);$/m, "filesMode", D),
  grab(DONE, /^  const composedHere = \(\(\) => \{[\s\S]*?\n  \}\)\(\);$/m, "composedHere", D),
  fn(DONE, "builtAt", D),
  fn(DONE, "freshDocuments", D),
  "async function __decide() {" + iifeBody(DONE, "─── Decide which mode to show", "(async () => {", D) + "}",
  "return { filesMode, composedHere, __decide, freshDocuments };",
].join(NL);
const makeDoneScope = new Function(
  "TW", "location", "history", "viewFiles", "showPostGenerate", "showPreGenerate", "emptyEl",
  "priceMovedSinceGenerate", DONE_BODY);

// ── the Estimate step's pill listener ───────────────────────────────────────────────────────
const PILL = grab(ESTIMATE, /^document\.addEventListener\("click", \(e\) => \{\n  const pill[\s\S]*?\n\}\);$/m,
                  "the step-pill listener", "estimate-review.js");

// ── one browser, one server ─────────────────────────────────────────────────────────────────
const STAMP = (/const STAMP\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const STATE_KEY = (/const STATE_KEY\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const DRAFT_ID_KEY = (/const DRAFT_ID_KEY\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
if (!STAMP || !STATE_KEY || !DRAFT_ID_KEY) throw new Error("shared.js storage keys moved");
const copy = (x) => JSON.parse(JSON.stringify(x));

function storage() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)),
           removeItem: (k) => m.delete(k) };
}

function browser(serverDraft, localDraft) {
  const b = { ls: storage(), ss: storage(), log: [],
              server: { d1: copy(serverDraft), puts: [], rendered: [], failPut: false } };
  b.ls.setItem(STATE_KEY, JSON.stringify(Object.assign(copy(localDraft || serverDraft),
                                                       { [STAMP]: "d1" })));
  b.ls.setItem(DRAFT_ID_KEY, "d1");
  return b;
}
function local(b) { return JSON.parse(b.ls.getItem(STATE_KEY) || "{}"); }

/** One page load at `href`: shared.js runs fresh against the browser's storage. */
async function load(b, href) {
  const nav = [];
  const timers = [];
  const loc = { origin: "https://tool" };
  const set = (u) => {
    const x = new URL(String(u), "https://tool");
    loc.href = x.href; loc.pathname = x.pathname; loc.search = x.search; loc.hash = x.hash;
  };
  set(href);
  loc.assign = (u) => { nav.push(["assign", String(u)]); b.log.push("assign " + u); };
  loc.replace = (u) => { nav.push(["replace", String(u)]); b.log.push("replace " + u); };
  loc.reload = () => { nav.push(["reload"]); };
  const history = { state: null, replaceState: (s, t, u) => { if (u != null) set(u); } };
  const json = (status, body) => Promise.resolve({
    ok: status < 400, status, statusText: status < 400 ? "OK" : "ERR",
    json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) });
  const fetch = (url, opts) => {
    const method = (opts && opts.method) || "GET";
    const u = String(url).replace(/^https?:\/\/[^/]+/, "");
    if (u === "/api/draft/d1" && method === "PUT") {
      b.log.push("PUT");
      if (b.server.failPut) return json(500, { detail: "down" });
      const data = JSON.parse(opts.body).data;
      b.server.puts.push(copy(data));
      b.server.d1 = copy(data);
      return json(200, { ok: true });
    }
    if (u === "/api/draft/d1" && method === "GET") return json(200, { data: copy(b.server.d1) });
    if (u === "/api/draft/d1/documents") {
      const pp = copy(b.server.d1.proposal_payload);
      b.server.rendered.push(pp);
      b.log.push("documents");
      return json(200, { work_type: pp.work_type, audience: pp.audience,
                         docx_download_url: "/api/file/D", pdf_download_url: "/api/file/D/pdf",
                         xlsx_download_url: "/api/file/X", render_id: "K",
                         document_total: pp.values.total_formatted });
    }
    return json(200, {});
  };
  const sandbox = {
    console, JSON, Promise, Math, Date, Object, Array, String, Number, Error, URL,
    URLSearchParams, Map, Set, isFinite,
    localStorage: b.ls, sessionStorage: b.ss,
    setTimeout: (f) => { timers.push(f); return timers.length; },
    clearTimeout: (id) => { if (id) timers[id - 1] = null; },
    fetch,
  };
  sandbox.window = {
    location: loc, history, addEventListener() {}, crypto: { randomUUID: () => "x" },
    TWAuth: { ready: Promise.resolve(),
              user: () => ({ name: "Kyle Loseke", email: "kyle@wetreadwell.com" }) },
  };
  sandbox.location = loc;
  sandbox.history = history;
  sandbox.document = {
    addEventListener() {}, removeEventListener() {}, querySelectorAll: () => [],
    createElement: () => ({ style: {}, appendChild() {}, setAttribute() {}, click() {},
                            classList: { add() {}, remove() {} } }),
    createTextNode: () => ({}), head: { appendChild() {} },
    body: { appendChild() {}, removeChild() {} }, getElementById: () => null,
  };
  vm.createContext(sandbox);
  vm.runInContext(SHARED, sandbox);
  const TW = sandbox.window.TW;
  return { TW, nav, timers, loc, history, window: sandbox.window,
           elapse: () => { const due = timers.splice(0); due.forEach((f) => { if (f) f(); }); } };
}

/** The Proposal step at `href`, initialised the way the page initialises, with the document
 *  editor's template "loading" (`tpl`: the version it reports, or "" when the load failed;
 *  `never`: it does not finish). */
async function openProposal(b, href, opts) {
  const o = opts || {};
  const page = await load(b, href);
  const TW = page.TW;
  const state = TW.getState();                         // the page's one-shot snapshot (line 14)
  const form = { elements: FIELDS.map((f) => ({ name: f.name, type: f.type, value: f.value,
                                                  checked: false })) };
  form.querySelector = (sel) => {
    const m = /\[name=['"]([^'"]+)['"]\]/.exec(sel);
    return m ? form.elements.find((e) => e.name === m[1]) || null : null;
  };
  TW.writeForm(form, state);                          // the page's own line 27
  const nodes = {};
  ["generate-btn", "resync-note", "resync-note-head", "resync-note-what", "resync-note-do"]
    .forEach((id) => { nodes[id] = { id, hidden: true, textContent: "", disabled: false,
                                     style: {}, scrollIntoView() {}, focus() {} }; });
  nodes["generate-btn"].textContent = "Continue to Done →";
  let tb = null;
  const doc = {
    getElementById: (id) => nodes[id] || null,
    querySelector: (sel) => (sel === "#tb-total" ? tb : null),
    createElement: () => ({ style: {}, textContent: "" }),
    body: { appendChild: (el) => { if (el.id === "tb-total") tb = el; } },
  };
  const pageTimers = [];
  let scope = null;
  const firstDocLoad = o.never ? new Promise(() => {})
    : Promise.resolve().then(() => { if (o.tpl !== "") scope.setTemplateVersion(o.tpl || "tpl-epoxy-direct"); });
  scope = makeProposalScope(
    state, form, doc, TW, page.window, page.window.TWAuth,
    // A Direct template's PRICE rows, as /api/proposal-template serves them (see payload-sync).
    [{ id: 124, in_block: null, text: "{{base_bid_formatted}} – Epoxy flooring as described above {{base_tax_phrase}}" },
     { id: 126, in_block: "tax_breakout", text: "{{material_tax_formatted}} – Material Sales Tax" },
     { id: 129, in_block: "remodel", text: "{{remodel.amount_formatted}} – Remodel Tax" },
     { id: 132, in_block: "tax_breakout", text: "{{total_label}}" }],
    () => [], () => ({}),
    () => [{ name: (state.system_name || "System"), sf: 1000, lf: 0 }],
    () => {},
    firstDocLoad, Promise.resolve(),
    (f) => { pageTimers.push(f); return pageTimers.length; },
    (id) => { if (id) pageTimers[id - 1] = null; },
    "");
  await TW.draftReady;
  scope.rebuildPricing();                              // page init, in the page's order
  scope.__initLump();
  return { page, TW, state, form, nodes, scope, firstDocLoad,
           firePageTimers: () => { const due = pageTimers.splice(0); due.forEach((f) => { if (f) f(); }); } };
}

/** The Files page at `href`: its real opening lines and its real mode decider. */
async function openDone(b, href) {
  const page = await load(b, href);
  const calls = [];
  const emptyEl = { style: { display: "none" } };
  const scope = makeDoneScope(page.TW, page.loc, page.history,
    () => calls.push("viewFiles"), () => calls.push("showPostGenerate"),
    () => calls.push("showPreGenerate"), emptyEl, () => false);
  await scope.__decide();
  return { page, TW: page.TW, calls, scope, url: page.loc.pathname + page.loc.search,
           nav: page.nav, emptyShown: emptyEl.style.display === "" };
}

// ── the draft ────────────────────────────────────────────────────────────────────────────────
function tabs(epoxyTotal, epoxyTax) {
  return [
    { id: "Epoxy", name: "Epoxy", role: "epoxy", kind: "base", total: epoxyTotal,
      sales_tax: epoxyTax, remodel: 0, system_desc: "Treadwell MACRO Flake", notes_auto: [],
      sf: { epoxy_sf: 1000, cove_lf: 0 } },
    { id: "Polish", name: "Polish", role: "polish", kind: "base", total: 8000, sales_tax: 250,
      remodel: 0, system_desc: "Treadwell Polished Concrete", notes_auto: [],
      sf: { polish_sf: 1000 } },
  ];
}
function draft() {
  return {
    project_name: "Door Test", job_name: "Door Test", work_type: "epoxy", audience: "Direct",
    city_state: "Lenexa, KS", address: "100 Main St", bid_date: "2026-09-20",
    base_tab_id: "Epoxy", priced_tabs: tabs(10000, 320), tab_opts: {},
    proposal_lump_sum: 10000, proposal_sales_tax: 320, proposal_remodel_tax: 0,
    system_name: "Treadwell MACRO Flake", texture: "Smooth",
    scope_notes: "Grind and coat.", schedule_notes: "One week.", exclusions: "Moving furniture.",
    notes_text: "Old note", tax_inclusion: "INCLUDED", estimator_name: "Kyle Loseke",
    price_overrides: { lines: {} },
    // A document from long ago, nesting ITS predecessor and a build result, as real drafts do.
    proposal_payload: { work_type: "polish", audience: "Direct",
                        values: { work_type: "polish", texture: "ancient",
                                  proposal_payload: { values: { texture: "older still" } },
                                  generate_result: { docx_download_url: "/api/file/ANCIENT" } } },
    generate_result: { docx_download_url: "/api/file/OLD" },
    dropbox_result: { folder: "/Estimating/old" },
  };
}

/** The last Continue: the Proposal step composes the old draft and leaves for Files. */
async function lastContinue(b) {
  const p = await openProposal(b, "/proposal-review.html?d=d1");
  await p.scope.continueToDone(null);
  return p;
}

/** What the Estimate step and a Proposal-step visit left without pressing Continue. */
async function editElsewhere(b, patch) {
  const e = await load(b, "/estimate-review.html?d=d1");
  e.TW.setState(patch);
  await e.TW.flushState();
}

const NESTED = ["proposal_payload", "proposal_payload_key", "generate_result", "dropbox_result",
                "priced_tabs"];
function summary(pp) {
  const v = (pp && pp.values) || {};
  return {
    workType: pp && pp.work_type, valuesWorkType: v.work_type,
    texture: v.texture, total: v.total_formatted, taxInclusion: v.tax_inclusion,
    baseTaxPhrase: v.base_tax_phrase, baseBid: v.base_bid_formatted,
    materialTax: v.material_tax_formatted, notes: pp && pp.notes,
    nested: NESTED.filter((k) => Object.prototype.hasOwnProperty.call(v, k)),
    mentionsAncient: /ancient|older still|ANCIENT|\/api\/file\/OLD|Estimating\/old/.test(JSON.stringify(v)),
  };
}

(async function () {
  const out = {};

  // A. THE CASE. The last Continue built "Smooth / $10,000 / included / Old note". Then the
  //    Estimate step re-priced to $12,500 and picked Orange Peel, and a Proposal-step visit left
  //    the tax Broken out and a new note, without Continue. The estimator clicks 4 · Files.
  {
    const b = browser(draft());
    const first = await lastContinue(b);
    const composedNav = first.page.nav.slice();
    const afterContinue = await openDone(b, "/done.html?composed=1&d=d1");
    const reload = await openDone(b, "/done.html?d=d1");
    const putsBeforeEdits = b.server.puts.length;

    await editElsewhere(b, { texture: "Orange Peel", priced_tabs: tabs(12500, 400),
                             proposal_lump_sum: 12500, proposal_sales_tax: 400,
                             tax_inclusion: "BROKEN_OUT", notes_text: "New note line" });
    const putsAfterEdits = b.server.puts.length;
    const arrive = await openDone(b, "/done.html?d=d1");        // the Files pill, unmarked
    const putsByArrival = b.server.puts.length - putsAfterEdits;

    b.log.length = 0;
    const door = await openProposal(b, "/proposal-review.html?compose=files&d=d1");
    await door.scope.composeForFiles();
    const doorLog = b.log.slice();
    const composed = local(b);

    const back = await openDone(b, "/done.html?composed=1&d=d1");
    const keyNow = back.TW.composeKey(back.TW.getState());
    await back.scope.freshDocuments();
    const rendered = b.server.rendered[b.server.rendered.length - 1];
    const again = await openDone(b, "/done.html?d=d1");

    out.e2e = {
      firstNav: composedNav,
      firstPayload: summary(b.server.puts[0] && b.server.puts[0].proposal_payload),
      afterContinue: { calls: afterContinue.calls, nav: afterContinue.nav, url: afterContinue.url },
      reload: { calls: reload.calls, nav: reload.nav },
      putsBeforeEdits, putsByArrival,
      arrive: { calls: arrive.calls, nav: arrive.nav },
      doorLog, doorNav: door.page.nav, doorNote: door.nodes["resync-note-head"].textContent,
      composed: summary(composed.proposal_payload),
      keyStored: composed.proposal_payload_key, keyNow,
      back: { calls: back.calls, nav: back.nav, url: back.url, composedHere: back.scope.composedHere },
      rendered: summary(rendered),
      again: { calls: again.calls, nav: again.nav },
      serverBlob: b.server.d1,
    };
  }

  // B. View files off the board, after the same edits: files mode survives the round trip, and so
  //    does the cover letter ticked since the last Continue (it is page 1 of the document).
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { texture: "Orange Peel", cover_letter_enabled: true });
    const arrive = await openDone(b, "/done.html?d=d1&files=1");
    const doorUrl = (arrive.nav[0] || [])[1] || "";
    const door = await openProposal(b, doorUrl.replace(/^https?:\/\/[^/]+/, ""));
    await door.scope.composeForFiles();
    const backUrl = (door.page.nav[0] || [])[1] || "";
    const back = await openDone(b, backUrl);
    out.viewFiles = { arriveNav: arrive.nav, doorNav: door.page.nav, backCalls: back.calls,
                      backFilesMode: back.scope.filesMode,
                      texture: local(b).proposal_payload.values.texture,
                      letter: local(b).proposal_payload.cover_letter_enabled };
  }

  // C. A base flip on the Proposal step, left by Back: the document follows the base's ROLE.
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { base_tab_id: "Polish" });
    const arrive = await openDone(b, "/done.html?d=d1");
    const door = await openProposal(b, "/proposal-review.html?compose=files&d=d1");
    await door.scope.composeForFiles();
    out.flip = { arriveNav: arrive.nav, payload: summary(local(b).proposal_payload) };
  }

  // D. THE SAFETY PROPERTY. Kyle's browser holds a CURRENT copy (keyed), and RJ has since sent a
  //    revision from another machine. View files on Kyle's machine must neither rebuild nor write:
  //    his copy is older than the server's, and writing it would put it back over RJ's work.
  {
    const b = browser(draft());
    await lastContinue(b);
    const rj = copy(b.server.d1);
    rj.texture = "RJ's texture";
    rj.proposal_payload.values.texture = "RJ's texture";
    b.server.d1 = rj;                                           // RJ's Continue, elsewhere
    const puts = b.server.puts.length;
    const d = await openDone(b, "/done.html?d=d1&files=1");
    await d.scope.freshDocuments();
    out.staleLocal = { nav: d.nav, calls: d.calls, putsFromThisBrowser: b.server.puts.length - puts,
                       rendered: b.server.rendered[b.server.rendered.length - 1].values.texture,
                       serverTexture: b.server.d1.proposal_payload.values.texture };
  }

  // E. The door never builds unattended when the template did not load, or the page never settles.
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { texture: "Orange Peel" });
    const puts = b.server.puts.length;
    const noTpl = await openProposal(b, "/proposal-review.html?compose=files&d=d1", { tpl: "" });
    await noTpl.scope.composeForFiles();
    const slow = await openProposal(b, "/proposal-review.html?compose=files&d=d1", { never: true });
    const pending = slow.scope.composeForFiles();
    await Promise.resolve();
    slow.firePageTimers();                                      // the 20 s timeout
    await pending;
    out.unattended = {
      noTemplate: { nav: noTpl.page.nav, note: noTpl.nodes["resync-note-head"].textContent,
                    shown: !noTpl.nodes["resync-note"].hidden,
                    button: noTpl.nodes["generate-btn"].textContent,
                    disabled: noTpl.nodes["generate-btn"].disabled },
      neverSettles: { nav: slow.page.nav, note: slow.nodes["resync-note-head"].textContent },
      putsFromEither: b.server.puts.length - puts,
    };
  }

  // F. A save the door cannot make goes nowhere: another tab took this browser's copy, or the
  //    server is down. Either way the Files page must not open on the old document.
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { texture: "Orange Peel" });
    const foreign = await openProposal(b, "/proposal-review.html?compose=files&d=d1");
    const taken = local(b); taken[STAMP] = "d2";
    b.ls.setItem(STATE_KEY, JSON.stringify(taken));           // another tab, after this page loaded
    await foreign.scope.composeForFiles();
    const fNav = foreign.page.nav.slice();

    const b2 = browser(draft());
    await lastContinue(b2);
    await editElsewhere(b2, { texture: "Orange Peel" });
    b2.server.failPut = true;
    const down = await openProposal(b2, "/proposal-review.html?compose=files&d=d1");
    await down.scope.composeForFiles();
    out.refusedSave = {
      foreign: { nav: fNav, note: foreign.nodes["resync-note-head"].textContent },
      serverDown: { nav: down.page.nav, note: down.nodes["resync-note-head"].textContent,
                    button: down.nodes["generate-btn"].textContent },
    };
  }

  // G. A debounced form persist still pending when Continue runs must not put the old document
  //    back: it writes a patch of the page snapshot's OLD payload.
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { texture: "Orange Peel" });
    const p = await openProposal(b, "/proposal-review.html?d=d1");
    p.scope.armPersist(() => p.TW.setState({ proposal_payload: p.state.proposal_payload }), 300);
    await p.scope.continueToDone(null);
    p.firePageTimers();                                         // what was pending, if anything
    p.page.elapse();
    await p.TW.flushState();
    const st = local(b);
    out.latePersist = { texture: st.proposal_payload.values.texture,
                        keyHolds: st.proposal_payload_key === p.TW.composeKey(st),
                        serverTexture: b.server.d1.proposal_payload.values.texture };
  }

  // I. The DOCUMENT half of the key: a write that put an older document back while leaving every
  //    input alone (the shape of a debounced save landing after Continue) still goes through the
  //    door, because the key covers the document as well as what it was built from.
  {
    const b = browser(draft());
    const p0 = await lastContinue(b);
    const older = copy(p0.state.proposal_payload);            // what this page loaded with
    const e = await load(b, "/proposal-review.html?d=d1");
    e.TW.setState({ proposal_payload: older });
    const arrive = await openDone(b, "/done.html?d=d1");
    out.documentOnly = { nav: arrive.nav, calls: arrive.calls };
  }

  // J. The loop guard: a page that has just come back from the door is never sent round again,
  //    even if its key does not hold; the same draft arriving unmarked is.
  {
    const b = browser(draft());
    await lastContinue(b);
    const st = local(b); st.proposal_payload_key = "not-this-document";
    b.ls.setItem(STATE_KEY, JSON.stringify(st));
    const marked = await openDone(b, "/done.html?composed=1&d=d1");
    const unmarked = await openDone(b, "/done.html?d=d1");
    out.loopGuard = { marked: marked.nav, unmarked: unmarked.nav };
  }

  // K. No project in this browser at all: the Proposal step would only say "No project started",
  //    so the Files page shows its own empty state instead of sending anybody there.
  {
    const b = browser({ notes_text: "" });
    const d = await openDone(b, "/done.html?d=d1");
    out.noProject = { nav: d.nav, calls: d.calls, emptyShown: d.emptyShown };
  }

  // H. The Estimate step's pills save the sheet on the way out, as its buttons do.
  {
    const listeners = [];
    const doc = { addEventListener: (ev, h) => listeners.push([ev, h]) };
    let persisted = 0;
    new Function("document", "persistTabState", PILL)(doc, () => { persisted++; });
    const click = (target) => listeners.filter(([ev]) => ev === "click").forEach(([, h]) => h({ target }));
    const pill = { closest: (sel) => (sel === ".progress a.step[href]" ? pill : null) };
    const cell = { closest: () => null };
    click(pill);
    const afterPill = persisted;
    click(cell);
    out.estimatePill = { events: listeners.map(([ev]) => ev), afterPill, afterCell: persisted };
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
