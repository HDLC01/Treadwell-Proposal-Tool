"use strict";
/* RUN the two project boards — Direct Projects and General Contractor — out of the real portal.js.
 *
 * Hanz, 2026-09-29: "we actually have two pipelines now ... We relabel Active projects to Direct
 * Projects and we add a new pipeline named 'General Contractor' as a new sidebar ... it will have the
 * same steps but just on a different webpage." One page and one portal.js draw both; which board a
 * page is comes off `data-pipeline`, and load() hands the board only its own rows. Everything below
 * is EXECUTED, never read as source text: this repo has shipped a board that went down with every
 * source assertion green (2026-08-12, an unbound identifier inside a render callback).
 *
 * FOUR THINGS, each off real code:
 *
 *   rule      crm-core's pipelineOf over the fixture list the Python side runs pipeline_of over, and
 *             boardOf over the pipeline endpoint's REAL payload (produced by main.py in the test and
 *             passed in), so the JavaScript answer can be held equal to the server's `pipeline` stamp
 *             card for card.
 *
 *   boards    portal.js's own load(), renderBoard(), boardPool(), syncTabs(), kanbanHtml() and the
 *             rest of the paint, lifted out of the IIFE with ONLY the names the page binds, run once
 *             per board per tab. Reports which cards each board holds, the four pill counts, the
 *             "N proposals" line and every column's count, read back OUT of what the page wrote.
 *
 *   deeplink  the same load() on a URL carrying ?open=<id>: does a link to the other board's project
 *             go to the other board (query and hash kept, board never painted), and does every other
 *             case still open the drawer here?
 *
 *   newproj   portal.js's startNewProposal() on each board, then shared.js's OWN getState() and
 *             writeForm() over the Audience radios parsed out of index.html — so "the GC board's
 *             + New opens the intake form on GC" is answered by the intake form's own code reading
 *             the key portal.js wrote, not by this file agreeing with itself.
 *
 * STUBBED, AND ONLY THESE: the fetch (`api` returns the payload), `tokenReady`, the DOM elements the
 * paint writes into (a bag of fields, not a tree — deliberately not jsdom, which would let a missing
 * import hide behind a global), `location`, the storage objects and `openDetail`, which is the
 * drawer and has its own harness (drawer-render-harness.js).
 *
 * Usage: node gc-pipeline-harness.js <frontend-dir> <input.json>   →  one line of JSON
 *   input.json: { "fixtures": [...], "payload": {...the /api/portal/pipeline response...} }
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);
const INPUT = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const C = require(path.join(ROOT, "js", "crm-core.js"));
const src = fs.readFileSync(path.join(ROOT, "js", "portal.js"), "utf8");
const sharedSrc = fs.readFileSync(path.join(ROOT, "shared.js"), "utf8");
const portalHtml = fs.readFileSync(path.join(ROOT, "portal.html"), "utf8");
const indexHtml = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");

// ── lifting real code out of an IIFE ─────────────────────────────────────────
function fnFrom(text, name, file) {
  const m = new RegExp("\\n\\s{2,6}(?:async\\s+)?function " + name + "\\s*\\(").exec(text);
  if (!m) throw new Error(name + "() is gone from " + file + " — rewrite this harness, don't delete it");
  const i = text.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < text.length; j++) {
    if (text[j] === "{") depth++;
    else if (text[j] === "}" && --depth === 0) return text.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name + " in " + file);
}
/** A module-level `const NAME = …;`, bracket-counted to its own semicolon. Throws when missing: a
 *  silently empty lift surfaces as a ReferenceError from the harness itself, which reads exactly
 *  like the product bug this file hunts. */
function declFrom(text, name, file) {
  const m = new RegExp("\\n\\s*const " + name.replace(/[$]/g, "\\$&") + " = ").exec(text);
  if (!m) throw new Error("const " + name + " is gone from " + file + " — rewrite this harness");
  let depth = 0;
  for (let j = m.index + m[0].length; j < text.length; j++) {
    const ch = text[j];
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (ch === ";" && depth === 0) return text.slice(m.index, j + 1);
  }
  throw new Error("unterminated declaration reading " + name + " in " + file);
}
const fn = (name) => fnFrom(src, name, "portal.js");
const decl = (name) => declFrom(src, name, "portal.js");

// EXACTLY what portal.js pulls off crm-core, from its own destructuring lines.
const destructured = [];
for (const m of src.matchAll(/const \{([^}]*)\} = C;/g)) {
  for (const part of m[1].split(",")) {
    const t = part.trim();
    if (!t) continue;
    const [from, to] = t.includes(":") ? t.split(":").map((x) => x.trim()) : [t, t];
    if (!(from in C)) throw new Error("portal.js destructures C." + from + ", which crm-core does not export");
    destructured.push([to, C[from]]);
  }
}
const NAMES = destructured.map(([n]) => n);
const VALUES = destructured.map(([, v]) => v);

// The tabs the page declares, and the pills the markup ships.
const TABS = new Function('"use strict"; return (' +
  decl("TABS").replace(/^\s*const TABS = /, "").replace(/;\s*$/, "") + ");")();
const PILLS = Array.from(portalHtml.matchAll(/data-tab="([a-z_]+)"/g)).map((m) => m[1]);
if (!PILLS.length) throw new Error("portal.html has no [data-tab] pills — rewrite this harness");

// ── A. the rule ──────────────────────────────────────────────────────────────
// JSON has no `undefined`; {"$missing": true} stands for it, which is what a row with no audience
// key hands pipelineOf through boardOf.
const unwrap = (v) => (v && typeof v === "object" && !Array.isArray(v) && v.$missing ? undefined : v);
const rule = (INPUT.fixtures || []).map((v) => C.pipelineOf(unwrap(v)));
const payloadRows = (INPUT.payload && INPUT.payload.proposals) || [];
const boardOfPayload = payloadRows.map((p) => ({ id: p.proposal_id, js: C.boardOf(p), server: p.pipeline }));

// ── B/C. the boards and the deep link, through the real load() ───────────────
const TW = {
  fmtBizDate: (v) => String(v || ""),
  fmtBizDay: (v) => String(v || ""),
  fmtBizDateTime: (v) => String(v || ""),
  bizYM: (v) => String(v || "").slice(0, 7),
  bizWeekStart: (v) => String(v || "").slice(0, 10),
  bizToday: () => "2026-09-29",
};

/** The page's elements, as a bag of fields. The tab strip is the only one with structure, because
 *  syncTabs writes into a `.n` span inside each pill and that is where the count is read back. */
function makeDom() {
  const counts = {};
  const pills = PILLS.map((tab) => ({
    dataset: { tab: tab },
    setAttribute() {},
    classList: { toggle() {} },
    querySelector(sel) {
      if (sel !== ".n") return null;
      return { set textContent(v) { counts[tab] = v; }, get textContent() { return counts[tab]; } };
    },
  }));
  const el = {
    board: { innerHTML: "", classList: { toggle() {} } },
    count: { textContent: "" },
    search: { value: "" },
    "crm-tabs": { querySelectorAll: (sel) => (sel === "[data-tab]" ? pills : []) },
  };
  return { counts: counts, el: el, $: (id) => (id in el ? el[id] : null) };
}

const LIFT = ["load", "renderDegraded", "renderBoard", "visible", "boardPool", "groupByReason",
              "lostCount", "syncTabs", "kanbanHtml", "tableHtml", "cardActions", "recipientLine",
              "chipsHtml", "wonControlHtml", "icon", "populateEstimators", "populatePeriods"];
const CONSTS = ["esc", "money", "fu", "avatar", "pausedUntil", "LOST_COLS", "COLS", "applySearch",
                "applyEstimator", "applyPeriod", "applySort", "WEEKS_OFFERED"];

const make = new Function(
  ...NAMES, "C", "TW", "PAGE",
  `"use strict";
   // The page's module-level state, declared the way portal.js declares it.
   let ALL = [];
   let TAB = "active", VIEW = "board";
   let EST = "", PERIOD = "", SORTFIELD = "activity", SORTDIR = "desc";
   let BOARD_SIG = "", DEGRADED_SIG = "", DEEPLINK_USED = false;
   // Which board, exactly as portal.js computes it — off <body data-pipeline>.
   const document = PAGE.document;
   ${decl("PIPELINE")}
   const $ = PAGE.$;
   const location = PAGE.location;
   const tokenReady = async () => {};
   const api = async () => ({ ok: true, json: async () => PAGE.payload });
   const openDetail = (id) => { PAGE.opened.push(id); };
   const ssSet = () => {};
   const EST_KEY = "", PERIOD_KEY = "";
   ${CONSTS.map(decl).join("\n")}
   ${LIFT.map(fn).join("\n")}
   return {
     pipeline: () => PIPELINE,
     load: load,
     setTab(t) { TAB = t; BOARD_SIG = ""; renderBoard(); },
     ids: () => ALL.map((p) => p.proposal_id),
     html: () => $("board").innerHTML,
   };`);

/** One page load of one board: a fresh module scope, as a real navigation gives. */
async function page(pipeline, search, hash) {
  const dom = makeDom();
  const replaced = [];
  const PAGE = {
    document: { body: { dataset: pipeline == null ? {} : { pipeline: pipeline } } },
    $: dom.$,
    location: { search: search || "", hash: hash || "", pathname: "/portal.html",
                replace: (u) => { replaced.push(u); } },
    payload: INPUT.payload,
    opened: [],
  };
  const scope = make(...VALUES, C, TW, PAGE);
  await scope.load();
  return { scope: scope, dom: dom, replaced: replaced, opened: PAGE.opened };
}

/** Column heading → [count printed in the heading, card ids drawn under it]. */
function columnsOf(board) {
  const by = {};
  for (const block of board.split('<div class="col').slice(1)) {
    const m = /<h2>([^<]*)<span>(\d+)<\/span>/.exec(block);
    if (!m) continue;
    by[m[1]] = { n: Number(m[2]), ids: Array.from(block.matchAll(/data-id="([^"]+)"/g)).map((x) => x[1]) };
  }
  return by;
}

// ── D. + New, then the intake form's own code ────────────────────────────────
const getStateSrc = fnFrom(sharedSrc, "getState", "shared.js");
const writeFormSrc = fnFrom(sharedSrc, "writeForm", "shared.js");
const STATE_KEY_SRC = declFrom(sharedSrc, "STATE_KEY", "shared.js");

// The Audience radios exactly as index.html ships them, `checked` and all.
const RADIOS = Array.from(indexHtml.matchAll(/<input\b[^>]*\bname="audience"[^>]*>/g)).map((m) => ({
  name: "audience", type: "radio",
  value: (/\bvalue="([^"]*)"/.exec(m[0]) || [])[1],
  checked: /\bchecked\b/.test(m[0]),
}));
if (RADIOS.length < 2) throw new Error("index.html has no Audience radios — rewrite this harness");

function newProject(pipeline, tab) {
  const local = new Map([["treadwell.proposal_tool.state", JSON.stringify({ project_name: "Yesterday's bid" })],
                         ["treadwell.proposal_tool.draft_id", "old-draft"]]);
  const store = (m) => ({ getItem: (k) => (m.has(k) ? m.get(k) : null),
                          setItem: (k, v) => { m.set(k, String(v)); },
                          removeItem: (k) => { m.delete(k); } });
  const localStorage = store(local);
  const sessionStorage = store(new Map([["treadwell.proposal_tool.hydrated_once", "1"]]));
  const intents = [], went = [];
  const TWn = { setNewProjectTestIntent: (v) => { intents.push(v); } };
  const window = { location: { assign: (u) => { went.push(u); } } };
  const document = { body: { dataset: pipeline == null ? {} : { pipeline: pipeline } } };
  const run = new Function("localStorage", "sessionStorage", "TW", "window", "document", "TAB",
    `"use strict";
     ${decl("PIPELINE")}
     ${fn("startNewProposal")}
     startNewProposal();`);
  run(localStorage, sessionStorage, TWn, window, document, tab);
  // The intake page, reading what was left behind — with shared.js's own reader and form writer.
  const form = { elements: RADIOS.map((r) => Object.assign({}, r)) };
  const intake = new Function("localStorage",
    `"use strict";
     ${STATE_KEY_SRC}
     ${getStateSrc}
     ${writeFormSrc}
     return function (form) { writeForm(form, getState()); return getState(); };`)(localStorage);
  const state = intake(form);
  const checked = form.elements.filter((e) => e.checked).map((e) => e.value);
  return { state: state, checked: checked, intents: intents, went: went,
           draftIdLeft: local.has("treadwell.proposal_tool.draft_id") };
}

(async () => {
  const out = { tabs: TABS, pills: PILLS, rule: rule, boardOfPayload: boardOfPayload, radios: RADIOS,
                boards: {}, deeplink: {}, newproj: {}, errors: {} };
  // B. every board, every tab
  for (const pl of ["direct", "gc", null]) {
    const key = pl == null ? "none" : pl;
    try {
      const p = await page(pl, "", "");
      const res = { pipeline: p.scope.pipeline(), ids: p.scope.ids(), pills: {}, tabs: {} };
      for (const tab of TABS) {
        p.scope.setTab(tab);
        res.tabs[tab] = { count: p.dom.el.count.textContent, columns: columnsOf(p.scope.html()),
                          newButton: p.scope.html().includes("data-new-proposal"),
                          undefinedLeak: p.scope.html().includes("undefined") };
      }
      res.pills = Object.assign({}, p.dom.counts);
      out.boards[key] = res;
    } catch (e) { out.errors["boards/" + key] = e.constructor.name + ": " + e.message; }
  }
  // C. deep links
  for (const [label, pl, id] of INPUT.deeplinks || []) {
    try {
      const p = await page(pl, "?open=" + encodeURIComponent(id) + "&sec=followup", "#here");
      const first = { replaced: p.replaced.slice(), opened: p.opened.slice(),
                      painted: p.dom.el.board.innerHTML !== "" };
      // A second load on the same page scope, as the 25s poll gives if the navigation is slow: the
      // latch must stop it redirecting (or opening a drawer) a second time.
      await p.scope.load();
      out.deeplink[label] = { first: first, replaced: p.replaced, opened: p.opened };
    } catch (e) { out.errors["deeplink/" + label] = e.constructor.name + ": " + e.message; }
  }
  // D. + New
  for (const [label, pl, tab] of [["direct", "direct", "active"], ["gc", "gc", "active"],
                                  ["gcTest", "gc", "test"], ["directTest", "direct", "test"]]) {
    try { out.newproj[label] = newProject(pl, tab); }
    catch (e) { out.errors["newproj/" + label] = e.constructor.name + ": " + e.message; }
  }
  console.log(JSON.stringify(out));
})().catch((e) => { console.log(JSON.stringify({ fatal: e.constructor.name + ": " + e.message })); });
