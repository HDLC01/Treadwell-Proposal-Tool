"use strict";
/* Run every screen that carries the tool's name, and report what a person would READ.
 *
 * THE NAMES. The Polish beta is "Estimating Tool v2" and its database page is "v2 Estimates"
 * (Phase 1b, 2026-10-07). Only the words changed; hrefs, ids and keys did not. This harness runs
 * the real code that writes those words and hands back the output, so the Python test beside it
 * (test_v2_names.py) is reading what the page produces and not what the file says:
 *
 *   * auth.js, in a bare VM: the sidebar rows for each role, and the label the Admin page's role
 *     matrix draws for them;
 *   * admin.js's own roleMatrixHtml(), handed the REAL capability table (nav_access.py's, passed in
 *     on the command line), so the server's labels and the sidebar's meet in one rendered table
 *     and the paragraph under it, which names the tool, is written for real;
 *   * polish-estimates.js, the whole file, against a stub page and a stubbed /api/drafts: the loaded
 *     table, the empty states, the failure, the footnote at the read ceiling;
 *   * projects.js's own paint(), renderChips() and filter chain, for the "v2 Estimates" tab;
 *   * polish-sandbox.js, the whole file, driven down each of its stop-and-say-so paths.
 *
 * THE SWEEP. The last block reads EVERY string in the frontend's JavaScript through
 * _lib.js's stringLiterals (comments and regular expressions left out: the comments that explain a
 * rename quote the old name, so a search of the file is no answer) and reports the ones that still
 * hold an old name. It is run against planted strings first, so a scanner that stopped seeing
 * strings would fail the test instead of agreeing with it.
 *
 * Usage: node v2-names-harness.js <frontend-dir> <config.json>   ->   one line of JSON
 *   config.json = { capabilityTable: [...], banned: ["polish estimate", ...], exemptPrefixes: [...] }
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const L = require("./_lib");

const FRONTEND = path.resolve(process.argv[2]);
const CONFIG = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const source = function () { return L.read(path.join(FRONTEND, ...arguments)); };

const out = {};

// ── a bare browser, enough for auth.js to load and render its menu ───────────
function bareBrowser() {
  const el = function () {
    return {
      id: "", innerHTML: "", textContent: "", title: "", hidden: false, className: "",
      style: { cssText: "" }, dataset: {},
      classList: { add() {}, remove() {}, toggle() {} },
      appendChild() {}, insertAdjacentHTML() {}, replaceChildren() {}, remove() {},
      addEventListener() {}, setAttribute() {}, getAttribute() { return null; },
      querySelector() { return null; }, querySelectorAll() { return []; },
    };
  };
  const win = {
    document: {
      head: el(), body: el(), documentElement: el(), hidden: false,
      getElementById() { return null; },
      createElement() { return el(); },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
    },
    location: { pathname: "/admin.html", search: "", origin: "https://example.test", replace() {}, assign() {} },
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    fetch() { return Promise.reject(new Error("harness: no network")); },
    matchMedia() { return { matches: true }; },
    getComputedStyle() { return { paddingTop: "0px" }; },
    setTimeout() {}, setInterval() {}, clearInterval() {},
    requestAnimationFrame() {},
    console, JSON, URLSearchParams, Set, Map,
  };
  win.window = win;
  win.self = win;
  win.globalThis = win;
  return win;
}

function loadAuth() {
  const win = bareBrowser();
  vm.createContext(win);
  vm.runInContext(source("js", "icons.js"), win, { filename: "icons.js" });
  vm.runInContext(source("auth.js"), win, { filename: "auth.js" });
  if (!win.TWAuth) throw new Error("auth.js did not publish window.TWAuth");
  return win;
}

/** The text of some markup with its whitespace collapsed to single spaces. */
function plain(html) { return L.stripTags(html).split(/\s+/).filter(Boolean).join(" "); }

// ── 1. the sidebar, and the Admin page's matrix of it ────────────────────────
{
  const win = loadAuth();
  out.sidebar = {};
  win.TWAuth.roles().forEach(function (role) {
    out.sidebar[role] = win.TWAuth.navSpec(role).map(function (r) {
      return { section: r.section, href: r.href, label: r.label, tag: r.tag };
    });
  });

  const admin = source("js", "admin.js");
  const indent = { indent: "    " };
  const make = new Function("window", "ME", "TWIcon", "POLICY", [
    '"use strict";',
    "var TWAuth = window.TWAuth;",
    L.grabConst(admin, "ROLE_LABEL", indent),
    L.liftSource(admin, "esc", indent),
    L.liftSource(admin, "icon", indent),
    L.liftSource(admin, "roleLabelOf", indent),
    L.liftSource(admin, "roleDiffSentence", indent),
    L.liftSource(admin, "roleMatrixHtml", indent),
    "return roleMatrixHtml(POLICY);",
  ].join("\n"));
  // The policy the page really receives: the capability table the server serves, nothing denied.
  const html = make(win, { role: "admin", email: "someone@wetreadwell.com" }, win.TWIcon,
    { deny: {}, tabs: CONFIG.capabilityTable, locked_roles: ["super_admin"] });
  const rowLabels = [];
  const rowRe = /<tr data-href="([^"]*)" data-label="([^"]*)"/g;
  let m;
  while ((m = rowRe.exec(html))) rowLabels.push([m[1], m[2]]);
  const note = html.slice(html.indexOf('id="rv-note"'));
  out.admin = {
    rowLabels: rowLabels,
    notes: note.split("</p>").map(plain).filter(Boolean),
  };
}

// ── a stub page element, with the few members these pages touch ──────────────
function stubElement() {
  const listeners = new Map();
  const attrs = new Map();
  return {
    innerHTML: "", textContent: "", value: "", className: "", hidden: false, dataset: {},
    listeners: listeners, attrs: attrs,
    addEventListener(type, fn) { listeners.set(type, fn); },
    setAttribute(k, v) { attrs.set(k, String(v)); },
    querySelectorAll() { return []; },
    closest() { return null; },
  };
}

// ── 2. the v2 Estimates page: polish-estimates.js, all of it, run ────────────
async function runDatabasePage(projects, opts) {
  const o = opts || {};
  const opened = [];                           // every address the page sent the browser to
  const els = new Map();
  const getEl = function (id) {
    if (!els.has(id)) els.set(id, stubElement());
    return els.get(id);
  };
  const session = new Map(Object.entries(o.session || {}));
  // Only what a browser adds. The language's own built-ins already exist inside a VM context, and
  // handing in the outer realm's copies is how an `instanceof` starts lying.
  const box = {
    console, setTimeout, clearTimeout,
    setInterval() { return 0; },
    document: { hidden: false, getElementById: getEl, addEventListener() {} },
    sessionStorage: {
      getItem(k) { return session.has(k) ? session.get(k) : null; },
      setItem(k, v) { session.set(k, String(v)); },
      removeItem(k) { session.delete(k); },
    },
    TW: {
      fmtBizDate(iso) { return String(iso || "").slice(0, 10); },
      bizYM(iso) { return String(iso || "").slice(0, 7); },
      fmtUsd(n) { return "$" + Math.round(n).toLocaleString("en-US"); },
      bizMonthLabel(ym) { return ym; },
      authHeaders() { return {}; },
    },
    TWCrm: { nameOf(e) { return String(e).split("@")[0]; }, avatarHtml() { return ""; } },
    __TW_TOKEN: "token",
    location: { assign(url) { opened.push(String(url)); } },
    fetch: async function () {
      return { json: async function () { return o.answer ? o.answer : { ok: true, projects: projects }; } };
    },
  };
  box.window = box;
  vm.createContext(box);
  vm.runInContext(source("js", "polish-estimates.js"), box, { filename: "polish-estimates.js" });
  await new Promise(function (r) { setTimeout(r, 40); });
  const list = getEl("list");
  const heads = [];
  const headRe = /<th[^>]*>([\s\S]*?)<\/th>/g;
  let h;
  while ((h = headRe.exec(list.innerHTML))) heads.push(plain(h[1]));
  // Press a row, the way the page's own delegated listener is pressed: the event only has to say
  // which row it landed on. Whatever address that sends the browser to is recorded.
  const press = list.listeners.get("click");
  if (press && o.pressRow) {
    press({ target: { closest(sel) { return sel === ".trow" ? { dataset: { id: o.pressRow } } : null; } } });
  }
  return {
    opened: opened,
    listHtml: list.innerHTML,
    listText: plain(list.innerHTML),
    heads: heads,
    count: getEl("count").textContent,
    toolbarHidden: getEl("toolbar").hidden,
    ceilingHidden: getEl("ceiling").hidden,
    ceilingText: getEl("ceiling").textContent,
  };
}

function betaRow(n, extra) {
  return Object.assign({
    id: "p" + n, project_name: "Job " + n, polish_beta: true, is_test: true, total: 10000 + n,
    updated_at: "2026-10-0" + ((n % 9) + 1) + "T12:00:00Z", owner_email: "kyle@wetreadwell.com",
    has_files: false, work_type: "polish", deadline: "2026-11-01",
  }, extra || {});
}

async function databaseScenarios() {
  const s = {};
  s.loaded = await runDatabasePage([betaRow(1), betaRow(2, { total: null, is_test: false }),
    { id: "x", project_name: "Not beta", polish_beta: false }], { pressRow: "p1" });
  s.empty = await runDatabasePage([]);
  s.emptyBecauseNoneMatch = await runDatabasePage([betaRow(1), betaRow(2)],
    { session: { tw_polishdb_q: "zzz-matches-nothing" } });
  s.failed = await runDatabasePage([], { answer: { ok: false, error: "the server could not read the list" } });
  const many = [];
  for (let i = 1; i <= 300; i++) many.push(betaRow(i));
  s.atTheReadCeiling = await runDatabasePage(many);
  return s;
}

// ── 3. the Proposals Database's v2 Estimates tab: projects.js's own code ─────
function projectsPage(filter, rows) {
  const src = source("js", "projects.js");
  const indent = { indent: "    ", where: "projects.js" };
  const names = ["nameLooksLikeTest", "isTest", "realOnly", "isActive", "isInactive", "applyFilter",
    "renderChips", "paint"];
  const painted = { filters: "", list: { className: "", textContent: "", innerHTML: "" } };
  const nodes = new Map();
  const generic = { hidden: false, textContent: "", value: "" };
  nodes.set("filters", {
    get innerHTML() { return painted.filters; },
    set innerHTML(v) { painted.filters = v; },
    hidden: false,
    querySelectorAll() { return []; },
  });
  nodes.set("list", painted.list);
  const body = [
    "var CURRENT_FILTER = FILTER; var ALL_PROJECTS = ROWS; var FILTER_KEY = 'k';",
    "var SEARCH = ''; var MONTH = ''; var SORTFIELD = 'updated'; var SORTDIR = 'desc'; var VIEW = 'cards';",
    "var LAST_SIG = '';",
    "var sessionStorage = { setItem: function () {} };",
    "var document = { getElementById: function (id) { return NODES.get(id) || GENERIC; } };",
    "function populateMonths() {}",
    "function applySort(x) { return x; }",
    "function applyMonth(x) { return x; }",
    "function applySearch(x) { return x; }",
    "function tableHtml() { return 'TABLE'; }",
    "function cardsHtml() { return 'CARDS'; }",
  ].concat(names.map(function (n) { return L.liftSource(src, n, indent); }))
    .concat(["return { applyFilter: applyFilter, renderChips: renderChips, paint: paint };"]).join("\n");
  const api = new Function("FILTER", "ROWS", "NODES", "GENERIC", body)(filter, rows, nodes, generic);
  return { api: api, painted: painted };
}

function projectsScenarios() {
  const rows = [
    { id: "a", project_name: "Niagara Bottling", archived: false, is_test: false, polish_beta: false },
    { id: "c", project_name: "Niagara Bottling (beta test)", archived: false, is_test: true, polish_beta: true },
  ];
  const chips = projectsPage("active", rows);
  chips.api.renderChips();
  const emptyTab = projectsPage("beta", [rows[0]]);       // projects exist, none of them is v2
  emptyTab.api.paint();
  return {
    chips: chips.painted.filters.split("<button").slice(1).map(function (bit) {
      return { key: bit.split('data-filter="')[1].split('"')[0], label: bit.split(">")[1].split("<")[0] };
    }),
    emptyBetaTab: { className: emptyTab.painted.list.className, text: emptyTab.painted.list.textContent },
  };
}

// ── 4. polish-sandbox.js, down each path where it stops and says so ──────────
function domNode() {
  const n = { children: [], own: "", hidden: false, className: "", innerHTML: "" };
  Object.defineProperty(n, "textContent", {
    get() { return flatten(n); },
    set(v) { n.children = []; n.own = String(v); },
  });
  n.appendChild = function (c) { n.children.push(c); return c; };
  n.setAttribute = function () {};
  return n;
}
function flatten(n) { return n.own + n.children.map(flatten).join(""); }

async function runSandbox(route, state) {
  const loading = domNode();
  const note = domNode();
  const ids = new Map([["loading", loading], ["sandbox-note", note]]);
  const box = {
    console: { warn() {}, log() {} }, URL, setTimeout,
    document: {
      getElementById(id) { return ids.has(id) ? ids.get(id) : null; },
      createElement() { return domNode(); },
      createTextNode(t) { const n = domNode(); n.own = String(t); return n; },
      querySelectorAll() { return []; },
    },
    TW: {
      getState() { return state; }, getDraftId() { return "d1"; }, resolveApiBase() { return ""; },
      authHeaders() { return {}; }, clearState() {}, setState() {},
    },
    localStorage: { setItem() {}, getItem() { return null; } },
    location: { origin: "https://app.test", href: "https://app.test/polish-intake.html?d=d1" },
    history: { replaceState() {} },
    fetch: async function (url, opts) { return route(String(url), (opts && opts.method) || "GET"); },
  };
  box.window = box;
  vm.createContext(box);
  vm.runInContext(source("js", "polish-sandbox.js"), box, { filename: "polish-sandbox.js" });
  const api = box.window.TWPolishSandbox;
  const settled = await api.enterSandbox(function () {});
  return { settled: settled, loading: loading.textContent, note: note.textContent, api: api };
}
const reply = function (status, body) {
  return { status: status, ok: status >= 200 && status < 300, json: async function () { return body; } };
};

async function sandboxScenarios() {
  const realJob = { project_name: "Real job" };
  const scenarios = {
    // the first read fails: stop, and say so
    firstReadFails: await runSandbox(function () { throw new Error("network down"); }, {}),
    // a project already filed as a test: edit it directly, and say so
    filedAsTest: await runSandbox(function () {
      return reply(200, { data: { project_name: "Akoya (beta test)", is_test: true } });
    }, {}),
    // a real project, and the check for its test copy fails
    copyReadFails: await runSandbox(function (url) {
      if (url.endsWith("/api/draft/d1")) return reply(200, { data: realJob });
      throw new Error("network down");
    }, {}),
    // a real project, no copy yet, and the copy cannot be saved
    copyCannotBeMade: await runSandbox(function (url, method) {
      if (url.endsWith("/api/draft/d1")) return reply(200, { data: realJob });
      if (method === "GET") return reply(404, null);
      return reply(500, {});
    }, {}),
    // never saved and nothing typed: the "nothing priced yet" note
    nothingPricedYet: await runSandbox(function () { return reply(404, null); }, {}),
  };
  // What a test copy is CALLED is saved data, not a label: the sandbox and the Test tab find a copy
  // by it. Run through the sandbox's own exports so a rename of words cannot reach it unseen.
  const api = scenarios.filedAsTest.api;
  scenarios.naming = {
    copyName: api.betaName("Real job"),
    renamedTwice: api.betaName(api.betaName("Real job")),
    nameless: api.betaName(""),
    copyId: api.sandboxIdFor("d1"),
  };
  Object.keys(scenarios).forEach(function (k) { if (scenarios[k].api) delete scenarios[k].api; });
  return scenarios;
}

// ── 5. the sweep: every string in the frontend's JavaScript ──────────────────
const squash = function (text) { return String(text).split(/\s+/).filter(Boolean).join(" ").toLowerCase(); };

/** The offenders in `src`: strings that hold a banned phrase, minus the log-prefix exemption. */
function offendersIn(src, where) {
  const found = [];
  L.stringLiterals(src).forEach(function (lit) {
    const text = squash(lit.text);
    if (CONFIG.exemptPrefixes.some(function (p) { return text.indexOf(p) === 0; })) return;
    CONFIG.banned.forEach(function (phrase) {
      if (text.indexOf(phrase) !== -1) {
        found.push({ file: where, line: lit.line, phrase: phrase, text: lit.text.slice(0, 140) });
      }
    });
  });
  return found;
}

function frontendScripts() {
  const files = [];
  fs.readdirSync(FRONTEND).forEach(function (e) { if (e.endsWith(".js")) files.push(e); });
  fs.readdirSync(path.join(FRONTEND, "js")).forEach(function (e) { if (e.endsWith(".js")) files.push("js/" + e); });
  return files.sort();
}

function sweep() {
  const files = frontendScripts();
  const offenders = [];
  const failures = [];
  let strings = 0;
  files.forEach(function (rel) {
    try {
      const src = source(...rel.split("/"));
      strings += L.stringLiterals(src).length;
      offendersIn(src, rel).forEach(function (o) { offenders.push(o); });
    } catch (e) {
      failures.push({ file: rel, error: String(e && e.message).slice(0, 160) });
    }
  });
  return {
    files: files.length, strings: strings, offenders: offenders, failures: failures,
    // The scanner, shown planted strings. A sweep that cannot see a string would say "clean" about
    // anything, so these are what stop it agreeing with itself.
    planted: {
      inAString: offendersIn('x = "The Polish Estimate beta is here";', "planted").length,
      inATemplate: offendersIn("x = `<b>Polish Estimate</b>`;", "planted").length,
      wrappedOverTwoLines: offendersIn("x = `the beta\n    calculator`;", "planted").length,
      inACommentOnly: offendersIn('// "Polish Estimate"\n/* beta calculator */ x = 1; // Polish beta', "planted").length,
      aLogPrefix: offendersIn('console.warn("[polish beta] failed", e);', "planted").length,
      theNewName: offendersIn('x = "Estimating Tool v2";', "planted").length,
    },
  };
}

async function main() {
  out.database = await databaseScenarios();
  out.projects = projectsScenarios();
  out.sandbox = await sandboxScenarios();
  out.sweep = sweep();
  process.stdout.write(JSON.stringify(out) + "\n");
}

main().catch(function (e) { console.error(e && e.stack || String(e)); process.exit(1); });
