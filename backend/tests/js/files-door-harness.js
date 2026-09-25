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
//   * both ask the SERVER's copy (TW.reconcileWithServer, TW.bootDigest, TW.bootSynced): an older
//     copy in this browser is replaced by the server's rather than built from and PUT back, one
//     that is the server's plus unsaved edits is built and saved, one where both sides moved stops
//     at the Files page, and a page initDraftSync is reloading onto another project writes nothing
//     (the review of the door, 2026-09-25: scenarios D to D10; the review of fix 4: R1 to R6);
//   * the Estimate step's pills save an edit still waiting on the grid's debounce, and only that.
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
// The page-init block that puts a name on the signature line, verbatim.
const PREFILL = iifeBody(PROPOSAL, "(function prefillEstimator() {", "(function prefillEstimator() {", P);

const PAGE_BODY = [
  "let templateVersion = __tv0;",
  PROPOSAL_UNITS,
  "function __initLump() {" + LUMP + "}",
  "function __prefillEstimator() {" + PREFILL + "}",
  "return { rebuildPricing, continueToDone, composeForFiles, __initLump, __prefillEstimator,",
  "  setTemplateVersion: (v) => { templateVersion = v; },",
  // The form's debounced persist, as the page arms it: it writes a patch of the module snapshot's
  // payload. Armed from here so the scenario can put one in flight when Continue runs.
  "  armPersist: (write, ms) => { _persistTimer = setTimeout(write, ms); } };",
].join(NL);
const makeProposalScope = new Function(
  "state", "form", "document", "TW", "window", "TWAuth", "templateBlocks",
  "collectOverrides", "collectBoxOverrides", "sheetSystems", "refreshPriceDisplay",
  "_firstDocLoad", "_notesReady", "setTimeout", "clearTimeout", "__tv0", "TWCoverLetter",
  PAGE_BODY);
// The cover letter's editor, loaded whole into the page when a scenario asks for it (its DOM is
// absent, so init() returns before rendering; its store and payloadFields() are the real ones).
const COVER_LETTER = read(path.join("js", "coverletter-editor.js"));

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
  fn(DONE, "showDoorStop", D),
  "async function __decide() {" + iifeBody(DONE, "─── Decide which mode to show", "(async () => {", D) + "}",
  "return { filesMode, composedHere, __decide, freshDocuments };",
].join(NL);
const makeDoneScope = new Function(
  "TW", "location", "history", "viewFiles", "showPostGenerate", "showPreGenerate", "emptyEl",
  "priceMovedSinceGenerate", DONE_BODY);

// ── the Estimate step's pill listener, and the grid listener that arms its pending save ───────
const PILL = grab(ESTIMATE, /^document\.addEventListener\("click", \(e\) => \{\n  const pill[\s\S]*?\n\}\);$/m,
                  "the step-pill listener", "estimate-review.js");
const GRID_CHANGE = grab(ESTIMATE,
  /^document\.getElementById\("sheet-grid"\)\.addEventListener\("change", \(\) => \{[\s\S]*?\n\}\);$/m,
  "the grid's change listener", "estimate-review.js");
/** Both listeners in one scope that shares the page's `_cbTimer`, with its collaborators stubbed
 *  and counted. Timers are captured, so "the debounce fired" is a step the scenario takes. */
function estimatePage() {
  const listeners = [];
  const timers = [];
  const rec = { persisted: 0, rendered: 0 };
  const grid = { addEventListener: (ev, h) => listeners.push(["grid:" + ev, h]) };
  const doc = { addEventListener: (ev, h) => listeners.push([ev, h]),
                getElementById: (id) => (id === "sheet-grid" ? grid : null) };
  const scope = new Function(
    "document", "persistTabState", "renderBidOptions", "refreshSystemName", "setTimeout",
    "clearTimeout",
    "let _cbTimer = null; let _bulkWrite = false;\n" + PILL + "\n" + GRID_CHANGE
      + "\nreturn { pending: () => _cbTimer };")(
    doc, () => { rec.persisted++; }, () => { rec.rendered++; }, () => {},
    (f) => { timers.push(f); return timers.length; },
    (id) => { if (id) timers[id - 1] = null; });
  const fire = (name, arg) => listeners.filter(([ev]) => ev === name).forEach(([, h]) => h(arg));
  const pill = { closest: (sel) => (sel === ".progress a.step[href]" ? pill : null) };
  const cell = { closest: () => null };
  return {
    rec, scope, events: listeners.map(([ev]) => ev),
    edit: () => fire("grid:change"),
    clickPill: () => fire("click", { target: pill }),
    clickCell: () => fire("click", { target: cell }),
    debounce: () => { const due = timers.splice(0); due.forEach((f) => { if (f) f(); }); },
  };
}

// ── one browser, one server ─────────────────────────────────────────────────────────────────
const STAMP = (/const STAMP\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const STATE_KEY = (/const STATE_KEY\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
const DRAFT_ID_KEY = (/const DRAFT_ID_KEY\s*=\s*"([^"]+)"/.exec(SHARED) || [])[1];
if (!STAMP || !STATE_KEY || !DRAFT_ID_KEY) throw new Error("shared.js storage keys moved");
const copy = (x) => JSON.parse(JSON.stringify(x));
const KYLE = { name: "Kyle Loseke", email: "kyle@wetreadwell.com" };
const TROY = { name: "Troy Holmes", email: "troy@wetreadwell.com" };

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
    if (u === "/api/draft/d2" && method === "PUT") {          // another project, saved as it leaves
      b.server.d2Puts = (b.server.d2Puts || []).concat([JSON.parse(opts.body).data]);
      return json(200, { ok: true });
    }
    if (u === "/api/draft/d1" && method === "GET") {
      if (b.server.failGet) return json(503, { detail: "down" });
      return json(200, { data: copy(b.server.d1) });
    }
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
    // Whoever is signed in on this browser: Kyle, unless the scenario says otherwise.
    TWAuth: { ready: Promise.resolve(), user: () => copy(b.user || KYLE) },
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
  return { TW, nav, timers, loc, history, window: sandbox.window, sandbox,
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
  nodes["estimator-name"] = form.elements.find((e) => e.name === "estimator_name");
  if (o.letter) {                                     // coverletter-editor.js, as the page loads it
    page.sandbox.document.readyState = "complete";
    page.sandbox.TW = TW;
    vm.runInContext(COVER_LETTER, page.sandbox);
  }
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
    "", page.window.TWCoverLetter);
  scope.__prefillEstimator();                          // page init: the signature line
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
  // The empty-state card as done.html marks it up: a heading, a lede, and one link-button.
  const h1 = { textContent: "Nothing to generate yet" };
  const lede = { textContent: "" };
  const presses = [];
  const link = { textContent: "← Go to Proposal Review",
                 addEventListener: (ev, h) => { if (ev === "click") presses.push(h); } };
  const emptyEl = { style: { display: "none" },
                    querySelector: (sel) => ({ h1, ".lede": lede, ".actions a": link }[sel] || null) };
  const scope = makeDoneScope(page.TW, page.loc, page.history,
    () => calls.push("viewFiles"), () => calls.push("showPostGenerate"),
    () => calls.push("showPreGenerate"), emptyEl, () => false);
  await scope.__decide();
  return { page, TW: page.TW, calls, scope, url: page.loc.pathname + page.loc.search,
           nav: page.nav, emptyShown: emptyEl.style.display === "",
           card: { title: h1.textContent, lede: lede.textContent, button: link.textContent },
           ledeNow: () => lede.textContent,
           /** The card's button, pressed; resolves once everything it started has settled. */
           press: () => { presses.forEach((h) => h({ preventDefault() {} }));
                          return new Promise((r) => setImmediate(r)); } };
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

/** The key a Continue on ANOTHER machine would have stamped on `blob` (the real TW.composeKey). */
async function keyOf(blob) {
  const p = await load(browser(blob), "/x.html?d=d1");
  return p.TW.composeKey(copy(blob));
}

/** Follow the Files page wherever it sends the estimator, the way the browser would, until it
 *  settles on a page: through the Proposal step's door (which composes, or stops and says why)
 *  and back, and through a reload. Returns every stop, and the settled Files page if there is one. */
async function arriveAtFiles(b, href, proposalOpts) {
  const stops = [];
  let url = href;
  for (let hop = 0; hop < 6 && url; hop++) {
    if (url.indexOf("/proposal-review.html") === 0) {
      const door = await openProposal(b, url, proposalOpts);
      await door.scope.composeForFiles();
      stops.push({ page: "proposal", nav: door.page.nav,
                   note: door.nodes["resync-note-head"].textContent });
      const next = door.page.nav[door.page.nav.length - 1];
      url = next && next[0] === "reload" ? url : (next ? next[1] : null);
      continue;
    }
    const done = await openDone(b, url);
    stops.push({ page: "done", nav: done.nav, calls: done.calls });
    const next = done.nav[done.nav.length - 1];
    if (!next) return { stops, done };
    url = next[0] === "reload" ? done.url : next[1];
  }
  return { stops, done: null };
}

/** Another project this browser opened in some other tab: its copy, stamped for ITS id. */
function otherProject() {
  return { project_name: "Other Project Y", job_name: "Other Project Y", texture: "Y texture",
           scope_notes: "Y scope", notes_text: "Y note", work_type: "epoxy", audience: "Direct",
           proposal_lump_sum: 777, priced_tabs: tabs(777, 7), base_tab_id: "Epoxy",
           [STAMP]: "d2" };
}
function holdOther(b) {
  b.ls.setItem(STATE_KEY, JSON.stringify(otherProject()));
  b.ls.setItem(DRAFT_ID_KEY, "d2");
}
const mentionsY = (x) => /Other Project Y|Y texture|Y scope|Y note/.test(JSON.stringify(x));

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

  // D. THE SAFETY PROPERTY. Kyle's browser holds a copy that is current by its own key, and RJ has
  //    since revised the project and pressed Continue on another machine (so RJ's copy is keyed
  //    too). View files on Kyle's machine must neither rebuild nor write: it takes the server's copy
  //    in place of Kyle's older one, reloads onto it, and renders RJ's document.
  {
    const b = browser(draft());
    await lastContinue(b);
    const rj = copy(b.server.d1);
    rj.texture = "RJ's texture";
    rj.proposal_payload.values.texture = "RJ's texture";
    rj.proposal_payload_key = await keyOf(rj);                 // RJ's Continue, elsewhere
    b.server.d1 = rj;
    const puts = b.server.puts.length;
    const d = await openDone(b, "/done.html?d=d1&files=1");
    const again = await openDone(b, "/done.html?d=d1&files=1");   // the reload it asked for
    await again.scope.freshDocuments();
    out.staleLocal = { nav: d.nav, calls: d.calls, againNav: again.nav, againCalls: again.calls,
                       putsFromThisBrowser: b.server.puts.length - puts,
                       rendered: b.server.rendered[b.server.rendered.length - 1].values.texture,
                       serverTexture: b.server.d1.proposal_payload.values.texture,
                       localTexture: local(b).texture };
  }

  // D2. THE REVIEW'S CASE (findings 2 and 5). Kyle's copy was current, then Kyle edited a note on
  //     the Estimate step and left (saved, no Continue), so his key no longer holds. RJ then
  //     re-priced to $15,000 and picked a texture on his own machine without pressing Continue,
  //     and Troy marked the job Won off the board. Kyle clicks View files. The door must build from
  //     the SERVER's copy — RJ's price and texture, Troy's Won — and never from Kyle's.
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { notes_text: "Kyle's later note" });     // Kyle, Estimate step, saved
    const rj = copy(b.server.d1);
    rj.texture = "RJ Orange Peel";
    rj.priced_tabs = tabs(15000, 480);
    rj.proposal_lump_sum = 15000;
    rj.proposal_sales_tax = 480;
    rj.won = { at: "2026-09-24", by: "troy@wetreadwell.com" };       // the board, server-side
    rj.handed_off = false;
    b.server.d1 = rj;
    const putsBefore = b.server.puts.length;
    const trip = await arriveAtFiles(b, "/done.html?d=d1&files=1");
    const puts = b.server.puts.slice(putsBefore);
    if (trip.done) await trip.done.scope.freshDocuments();
    out.staleEdited = {
      stops: trip.stops.map((s) => s.page + " " + JSON.stringify(s.nav)),
      finalCalls: trip.done ? trip.done.calls : null,
      puts: puts.length,
      everyPutIsRJs: puts.every((p) => p.texture === "RJ Orange Peel" && p.proposal_lump_sum === 15000
                                       && !!p.won && p.notes_text === "Kyle's later note"),
      server: { texture: b.server.d1.texture, lump: b.server.d1.proposal_lump_sum,
                won: b.server.d1.won || null, handedOff: b.server.d1.handed_off },
      document: summary(b.server.d1.proposal_payload),
      rendered: summary(trip.done ? b.server.rendered[b.server.rendered.length - 1] : null),
    };
  }

  // D3. A copy saved BEFORE this deploy: a document, no key, and no record of when it last matched
  //     the server. RJ has since revised the project elsewhere. Same answer: the server's copy wins,
  //     and Kyle's is never written.
  {
    const b = browser(draft());
    const rj = copy(draft());
    rj.texture = "RJ Orange Peel";
    rj.proposal_payload.values.texture = "RJ Orange Peel";
    rj.proposal_payload_key = "stamped-by-rj-elsewhere";
    b.server.d1 = rj;
    const trip = await arriveAtFiles(b, "/done.html?d=d1&files=1");
    out.legacyStale = {
      stops: trip.stops.map((s) => s.page),
      puts: b.server.puts.length,
      everyPutIsRJs: b.server.puts.every((p) => p.texture === "RJ Orange Peel"),
      serverTexture: b.server.d1.texture,
      documentTexture: b.server.d1.proposal_payload.values.texture,
      settled: !!trip.done,
    };
  }

  // D4. Finding 3. Kyle's copy is current by its own key; RJ picked Knockdown on the Estimate step
  //     on his machine and left without Continue, so the SERVER's draft says Knockdown under a
  //     document that says Smooth. Kyle's key holds; the server's does not. The door asks the
  //     server's, so View files builds Knockdown and Download renders it.
  {
    const b = browser(draft());
    await lastContinue(b);
    const rj = copy(b.server.d1);
    rj.texture = "Knockdown";
    b.server.d1 = rj;
    const trip = await arriveAtFiles(b, "/done.html?d=d1&files=1");
    if (trip.done) await trip.done.scope.freshDocuments();
    const last = b.server.rendered[b.server.rendered.length - 1];
    out.serverMoved = {
      stops: trip.stops.map((s) => s.page),
      documentTexture: b.server.d1.proposal_payload.values.texture,
      renderedTexture: last ? last.values.texture : null,
      keyHolds: b.server.d1.proposal_payload_key === (await keyOf(b.server.d1)),
    };
  }

  // D5. This browser's copy has an edit the server never got (its save failed), and nobody has saved
  //     the server's copy since ("ahead"). The Files page does not replace that copy, and the door
  //     builds it and saves it: the edit reaches the server and the document, and nothing of
  //     anyone else's is lost.
  {
    const b = browser(draft());
    await lastContinue(b);
    b.server.failPut = true;
    await editElsewhere(b, { texture: "Unsaved Knockdown" });
    b.server.failPut = false;
    const putsBefore = b.server.puts.length;
    const trip = await arriveAtFiles(b, "/done.html?d=d1");
    out.unconfirmed = {
      stops: trip.stops.map((s) => s.page),
      note: (trip.stops[trip.stops.length - 1] || {}).note,
      puts: b.server.puts.length - putsBefore,
      localTexture: local(b).texture,
      serverTexture: b.server.d1.texture,
    };
  }

  // D6. The same edit, whose save is merely still in flight when the Files page asks (a pill click
  //     sends it as the page goes). The Files page cannot see it yet, so it sends the estimator
  //     through the door on this browser's own copy; by the time the Proposal step asks, the save
  //     has landed, the two copies agree, and the document is built.
  {
    const b = browser(draft());
    await lastContinue(b);
    const e = await load(b, "/estimate-review.html?d=d1");
    e.TW.setState({ texture: "Knockdown" });                    // queued; the page goes
    const d = await openDone(b, "/done.html?d=d1");            // the server has not got it yet
    b.server.d1 = copy(local(b));                               // …and now it has (keepalive)
    const trip = await arriveAtFiles(b, (d.nav[0] || [])[1] || "");
    out.inFlight = {
      firstNav: d.nav,
      stops: trip.stops.map((s) => s.page),
      documentTexture: b.server.d1.proposal_payload.values.texture,
    };
  }

  // D7. Finding 1. The door page is open on this project (X) when another tab opens project Y, so
  //     this browser's copy becomes Y's. The door refuses ("open in another tab") and the estimator
  //     reloads as it says. On that load the page's snapshot is Y's; initDraftSync adopts X and
  //     reloads. Nothing may build from Y's snapshot on the way: X must never be written with Y.
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { texture: "Orange Peel" });
    const door = await openProposal(b, "/proposal-review.html?compose=files&d=d1");
    holdOther(b);                                               // the other tab, after this loaded
    await door.scope.composeForFiles();
    const said = door.nodes["resync-note-head"].textContent;
    const putsBefore = b.server.puts.length;
    const reload1 = await openProposal(b, "/proposal-review.html?compose=files&d=d1");
    await reload1.scope.composeForFiles();
    const putsAfterFirst = b.server.puts.length - putsBefore;
    const localAfterFirst = local(b);
    const reload2 = await openProposal(b, "/proposal-review.html?compose=files&d=d1");
    await reload2.scope.composeForFiles();
    out.foreignReload = {
      said, reload1Nav: reload1.page.nav, reload2Nav: reload2.page.nav, putsAfterFirst,
      localAfterFirst: { project: localAfterFirst.project_name, texture: localAfterFirst.texture,
                         lump: localAfterFirst.proposal_lump_sum },
      serverMentionsY: mentionsY(b.server.d1),
      putsMentioningY: b.server.puts.filter(mentionsY).length,
      server: { project: b.server.d1.project_name, scope: b.server.d1.scope_notes,
                docProject: b.server.d1.proposal_payload.values.project_name,
                docTexture: b.server.d1.proposal_payload.values.texture },
    };
  }

  // D8. The same thing from a plain load: this browser last held project Y, and the door's address
  //     for X is opened (a restored tab, a pasted link, Back to a door that had stopped).
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { texture: "Orange Peel" });
    holdOther(b);
    const putsBefore = b.server.puts.length;
    const first = await openProposal(b, "/proposal-review.html?compose=files&d=d1");
    await first.scope.composeForFiles();
    const putsFromFirst = b.server.puts.length - putsBefore;
    const second = await openProposal(b, "/proposal-review.html?compose=files&d=d1");
    await second.scope.composeForFiles();
    out.crossDraft = {
      firstNav: first.page.nav, putsFromFirst, secondNav: second.page.nav,
      serverMentionsY: mentionsY(b.server.d1),
      putsMentioningY: b.server.puts.filter(mentionsY).length,
      docTexture: b.server.d1.proposal_payload.values.texture,
    };
  }

  // D10. A fresh hydrate records what it read. This browser last held another project, so opening X
  //      reads the server's copy; then an edit here fails to save. The Files page must know that
  //      copy has changes the server never got (and not replace it), which it can only tell from
  //      the record the hydrate left of what the server held.
  {
    const b = browser(draft());
    await lastContinue(b);
    holdOther(b);
    b.ls.removeItem("treadwell.proposal_tool.synced");        // only the hydrate may record it
    const hydrate = await load(b, "/estimate-review.html?d=d1");       // reads X, reloads
    await hydrate.TW.draftReady;
    b.server.failPut = true;
    await editElsewhere(b, { texture: "Unsaved Knockdown" });
    b.server.failPut = false;
    const putsBefore = b.server.puts.length;
    const trip = await arriveAtFiles(b, "/done.html?d=d1");
    out.hydratedThenUnsaved = {
      hydrateNav: hydrate.nav,
      stops: trip.stops.map((s) => s.page),
      puts: b.server.puts.length - putsBefore,
      localTexture: local(b).texture,
      serverTexture: b.server.d1.texture,
    };
  }

  // D9. Finding 6. The draft already says cover_letter_enabled:false at the top level (the box was
  //     unticked once). The estimator ticks it and presses Continue — the switch writes that one
  //     key with setState, which the page's snapshot never sees — then later changes a note on the
  //     Estimate step and clicks Files. The rebuilt document must still carry page 1.
  {
    const start = Object.assign(draft(), { cover_letter_enabled: false });
    const b = browser(start);
    const p = await openProposal(b, "/proposal-review.html?d=d1");
    p.TW.setState({ cover_letter_enabled: true });              // wireCoverLetterSwitch's write
    await p.scope.continueToDone(null);
    const afterTick = local(b);
    await editElsewhere(b, { notes_text: "A later note" });
    await arriveAtFiles(b, "/done.html?d=d1");
    out.coverLetter = {
      afterTick: { topLevel: afterTick.cover_letter_enabled,
                   payload: afterTick.proposal_payload.cover_letter_enabled },
      afterDoor: { topLevel: b.server.d1.cover_letter_enabled,
                   payload: b.server.d1.proposal_payload.cover_letter_enabled,
                   notes: b.server.d1.proposal_payload.notes },
    };
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

  // H. The Estimate step's pills save the sheet on the way out WHEN AN EDIT IS STILL WAITING on the
  //    grid's 300ms debounce — and only then. persistTabState writes the page's whole load-time
  //    snapshot, so a pill click on a page with nothing waiting (a stale page opened before a
  //    colleague's revision, merely walked through) must write nothing.
  {
    const edited = estimatePage();
    edited.edit();                                              // a cell edit: the debounce armed
    const armed = !!edited.scope.pending();
    edited.clickPill();
    const afterPill = edited.rec.persisted;
    const clearedByPill = edited.scope.pending() === null;
    edited.debounce();                                          // the cancelled timer is gone
    const afterDebounce = edited.rec.persisted;

    const idle = estimatePage();
    idle.clickPill();                                           // nothing edited on this page

    const settled = estimatePage();
    settled.edit();
    settled.debounce();                                         // the debounce saved the edit itself
    const settledSaves = settled.rec.persisted;
    settled.clickPill();                                        // …so the pill has nothing to add

    const elsewhere = estimatePage();
    elsewhere.edit();
    elsewhere.clickCell();                                      // not a pill

    out.estimatePill = {
      events: edited.events, armed, afterPill, clearedByPill, afterDebounce,
      idle: idle.rec.persisted,
      settledSaves, settledAfterPill: settled.rec.persisted,
      settledPending: settled.scope.pending(),
      elsewhere: elsewhere.rec.persisted,
    };
  }

  // ── The review of fix 4 (2026-09-25) ────────────────────────────────────────────────────────
  const settle = () => new Promise((r) => setImmediate(r));

  /** Finding 1's world. Kyle's Continue keyed his copy and recorded it as the server's. He then
   *  typed a note on the Proposal step and closed the tab inside the 2.5 s: the pagehide keepalive
   *  PUT landed, but its .then never ran, so the record is one edit behind. RJ then re-priced to
   *  $15,000, picked a texture and pressed Continue on his own machine, and Troy marked it Won. */
  async function bothMoved() {
    const b = browser(draft());
    await lastContinue(b);
    const p = await load(b, "/proposal-review.html?d=d1");
    p.TW.setState({ notes_text: "Kyle's note, sent as the tab closed" });
    b.server.d1 = copy(local(b));                       // the keepalive landed; nothing recorded it
    const rj = copy(b.server.d1);
    rj.texture = "RJ Orange Peel"; rj.priced_tabs = tabs(15000, 480);
    rj.proposal_lump_sum = 15000; rj.proposal_sales_tax = 480;
    rj.proposal_payload.values.texture = "RJ Orange Peel";
    rj.proposal_payload.values.total_formatted = "$15,480.00";
    rj.proposal_payload_key = await keyOf(rj);          // RJ's Continue, elsewhere
    rj.won = { at: "2026-09-25", by: "troy@wetreadwell.com" };   // the board, server-side
    b.server.d1 = rj;
    return b;
  }
  const rjStands = (b) => ({ texture: b.server.d1.texture, lump: b.server.d1.proposal_lump_sum,
                             won: !!b.server.d1.won, notes: b.server.d1.notes_text,
                             docTotal: b.server.d1.proposal_payload.values.total_formatted });

  // R1. Both copies moved. The Files page stops and says so, writes nothing, and never sends the
  //     copy to the Proposal step (whose load saves it). Its one button loads the saved copy.
  {
    const b = await bothMoved();
    const putsBefore = b.server.puts.length;
    const d = await openDone(b, "/done.html?d=d1&files=1");
    d.page.elapse(); await d.TW.flushState();
    const kept = local(b);
    const r = { nav: d.nav.slice(), calls: d.calls, emptyShown: d.emptyShown, card: d.card,
                putsByArrival: b.server.puts.length - putsBefore,
                keptKyles: { texture: kept.texture, notes: kept.notes_text } };
    await d.press();
    r.pressNav = d.nav.slice(r.nav.length);
    const adopted = local(b);
    r.localAfterPress = { texture: adopted.texture, lump: adopted.proposal_lump_sum, won: !!adopted.won };
    const trip = await arriveAtFiles(b, "/done.html?d=d1&files=1");   // the reload it asked for
    if (trip.done) { trip.done.page.elapse(); await trip.done.TW.flushState(); }
    r.afterReload = { stops: trip.stops.map((s) => s.page + " " + JSON.stringify(s.nav)),
                      calls: trip.done ? trip.done.calls : null };
    r.putsFromKyle = b.server.puts.length - putsBefore;
    r.server = rjStands(b);
    out.bothMoved = r;
  }

  // R1b. The card is up, and before the estimator presses it another tab of this browser opens
  //      project Y. Loading X's saved copy must not drop Y's: it is saved under Y's own id first,
  //      exactly as opening a project does (initDraftSync's eviction).
  {
    const b = await bothMoved();
    const d = await openDone(b, "/done.html?d=d1&files=1");
    holdOther(b);
    await d.press();
    const mine = local(b);
    out.pressWhileAnotherTabHeldY = {
      pressNav: d.nav.slice(),
      yPuts: (b.server.d2Puts || []).map((p) => p.project_name),
      local: { project: mine.project_name, texture: mine.texture, stamp: mine[STAMP] },
    };
  }

  // R1c. The server cannot be read when the button is pressed: nothing changes, and the card says
  //      so rather than sitting there as a button that does nothing.
  {
    const b = await bothMoved();
    const d = await openDone(b, "/done.html?d=d1&files=1");
    b.server.failGet = true;
    await d.press();
    out.pressWhileServerDown = { nav: d.nav.slice(), lede: d.ledeNow(), texture: local(b).texture,
                                 puts: b.server.puts.length };
  }

  // R2. The Proposal step opened as the door on that copy all the same (a tab left open on the
  //     door's address, the old routing): it asks the server at once, drops its own load save
  //     unsent, and goes back to the Files page. Whether the template is quick or slow.
  {
    const r = {};
    for (const slow of [false, true]) {
      const b = await bothMoved();
      const putsBefore = b.server.puts.length;
      const door = await openProposal(b, "/proposal-review.html?compose=files&d=d1",
                                      slow ? { never: true } : {});
      const pending = door.scope.composeForFiles();
      await settle();                                   // the server has answered
      door.page.elapse();                               // 2.5 s: the page's own load save was due
      if (slow) door.firePageTimers();                  // 20 s: the template never came
      await pending;
      door.page.elapse(); await door.TW.flushState();
      r[slow ? "slowTemplate" : "quickTemplate"] = {
        nav: door.page.nav, note: door.nodes["resync-note-head"].textContent,
        puts: b.server.puts.length - putsBefore, server: rjStands(b) };
    }
    out.doorOnBothMoved = r;
  }

  // R3. The server cannot be read at the Files page, and the document is out of date: stop and say
  //     so. Not the door: a page that saves as it loads is not sent a copy nobody could check.
  {
    const b = browser(draft());
    await lastContinue(b);
    await editElsewhere(b, { texture: "Orange Peel" });
    b.server.failGet = true;
    const putsBefore = b.server.puts.length;
    const d = await openDone(b, "/done.html?d=d1&files=1");
    d.page.elapse(); await d.TW.flushState();
    const r = { nav: d.nav.slice(), calls: d.calls, card: d.card,
                puts: b.server.puts.length - putsBefore };
    await d.press();
    r.pressNav = d.nav.slice(r.nav.length);
    out.unreachable = r;
  }

  // R4. Finding 3. The draft carries the letter wording from an earlier visit (X0). Kyle rewrites
  //     it (X1, the editor's own persistNow write) and presses Continue; later he changes a note on
  //     the Estimate step and opens View files, and the door rebuilds with nobody looking.
  {
    const X0 = { "3": { text: "Dear Sam — first wording." } };
    const X1 = { "3": { text: "Dear Sam — the wording Kyle settled on." } };
    const store = (items) => ({
      cover_letter_paragraph_overrides_all: { "epoxy:Direct": { template_version: "clv", items } },
      cover_letter_paragraph_overrides: items,
      cover_letter_paragraph_overrides_meta: { template_version: "clv", work_type: "epoxy",
                                               audience: "Direct" },
      cover_letter_template_version: "clv" });
    const b = browser(Object.assign(draft(), { cover_letter_enabled: true }, store(X0)));
    const p = await openProposal(b, "/proposal-review.html?d=d1", { letter: true });
    p.TW.setState(store(X1));
    await p.scope.continueToDone(null);
    const after = local(b);
    await editElsewhere(b, { notes_text: "A later note" });
    const trip = await arriveAtFiles(b, "/done.html?d=d1&files=1", { letter: true });
    out.letterWording = {
      afterContinue: {
        payload: after.proposal_payload.cover_letter_paragraph_overrides,
        topLevel: after.cover_letter_paragraph_overrides,
        store: (after.cover_letter_paragraph_overrides_all["epoxy:Direct"] || {}).items,
        keyHolds: after.proposal_payload_key === p.TW.composeKey(after) },
      stops: trip.stops.map((s) => s.page),
      afterDoor: { payload: b.server.d1.proposal_payload.cover_letter_paragraph_overrides,
                   topLevel: b.server.d1.cover_letter_paragraph_overrides,
                   notes: b.server.d1.proposal_payload.notes },
    };
  }

  // R5. Finding 5, the board's marks. Kyle composed the project. Then, from the CRM, somebody
  //     changed who is told about a send and Troy marked it Won — both written by the server. Troy
  //     opens View files on his own machine: nothing the proposal prints has changed, so nothing is
  //     rebuilt, nothing is saved, and the letter is still signed with Kyle's address.
  {
    const b = browser(draft());
    await lastContinue(b);
    const kyles = copy(b.server.d1);
    const marked = Object.assign(copy(kyles), {
      notify_picks: { add: ["rj@wetreadwell.com"], mute: [] },
      won: { at: "2026-09-25", by: "troy@wetreadwell.com" } });
    const t = browser(marked, kyles);
    t.user = TROY;
    const trip = await arriveAtFiles(t, "/done.html?d=d1&files=1");
    out.boardMarks = { stops: trip.stops.map((s) => s.page + " " + JSON.stringify(s.nav)),
                       finalCalls: trip.done ? trip.done.calls : null, puts: t.server.puts.length,
                       won: !!t.server.d1.won,
                       email: t.server.d1.proposal_payload.values.estimator_email };
  }

  // R6. Finding 5, a real rebuild on a colleague's machine: Kyle picked a new texture on the
  //     Estimate step (saved, no Continue), and Troy opens View files. The document is rebuilt on
  //     Troy's machine — and is still signed by Kyle, at Kyle's address.
  {
    const r = {};
    const signing = (t) => { const v = t.server.d1.proposal_payload.values;
                             return { name: v.estimator_name, email: v.estimator_email,
                                      texture: v.texture, puts: t.server.puts.length }; };
    {
      const b = browser(draft());
      await lastContinue(b);
      await editElsewhere(b, { texture: "Orange Peel" });
      const t = browser(b.server.d1); t.user = TROY;
      await arriveAtFiles(t, "/done.html?d=d1&files=1");
      r.rebuiltByTroy = signing(t);
    }
    // A document saved before it carried an address (2026-09-09): signed Kyle, no address.
    // Rebuilt by Troy it prints none (never Troy's); rebuilt by Kyle it gets his.
    for (const who of [TROY, KYLE]) {
      const legacy = draft();
      legacy.proposal_payload.values.estimator_name = "Kyle Loseke";
      const t = browser(legacy); t.user = who;
      await arriveAtFiles(t, "/done.html?d=d1&files=1");
      r[who === TROY ? "legacyByTroy" : "legacyByKyle"] = signing(t);
    }
    // The project's own signature field was never filled in; its saved document says Kyle.
    {
      const blank = Object.assign(draft(), { estimator_name: "" });
      blank.proposal_payload.values.estimator_name = "Kyle Loseke";
      blank.proposal_payload.values.estimator_email = "kyle@wetreadwell.com";
      const t = browser(blank); t.user = TROY;
      await arriveAtFiles(t, "/done.html?d=d1&files=1");
      r.blankFieldByTroy = signing(t);
    }
    // Troy types his own name on the signature line and presses Continue: he signs, at his address.
    {
      const b = browser(draft());
      await lastContinue(b);
      b.user = TROY;
      const p = await openProposal(b, "/proposal-review.html?d=d1");
      p.form.elements.find((e) => e.name === "estimator_name").value = "Troy Holmes";
      await p.scope.continueToDone(null);
      r.troySigns = signing(b);
    }
    out.signing = r;
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stderr.write(String((e && e.stack) || e)); process.exit(1); });
