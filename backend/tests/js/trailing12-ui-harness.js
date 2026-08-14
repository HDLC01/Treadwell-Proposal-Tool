"use strict";
/* Run the REAL Trailing-12 tab and the REAL export payload builder out of analytics.js.
 *
 * WHY EXECUTED. Two of the claims here are about what the code DOESN'T do, and no source assertion
 * can carry those:
 *   - the tab reads ROWS, not filtered() — the org-wide guarantee is literally which variable is
 *     passed, and a grep for "filtered()" in the file finds four legitimate uses;
 *   - the file download carries the bearer — /api/file/* is gated, so forgetting the header 401s
 *     only in production, where tests bypass auth.
 * The numbers come from the real analytics-core.js, so nothing here can agree with a stub instead
 * of the engine.
 *
 * Usage: node trailing12-ui-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

// resolve(): require() needs an absolute path, and the caller passes this relative.
const ROOT = path.resolve(process.argv[2]);
const src = fs.readFileSync(path.join(ROOT, "js", "analytics.js"), "utf8");
const X = require(path.join(ROOT, "js", "analytics-core.js"));

/** Lift a two-space-indented `function name(...) {...}` by brace counting. */
function fn(name) {
  const m = new RegExp("\\n  function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from analytics.js — rewrite this harness");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}
/** render()'s body with comment-only lines removed.
 *
 *  Calling the lifted revealExport() proves the function works and says nothing about whether
 *  anything calls it — which is exactly how the unreachable first version passed. This is the
 *  wiring check, and the comments are stripped so a line MENTIONING revealExport cannot satisfy it.
 */
function renderBody() {
  const NL = String.fromCharCode(10);
  const m = new RegExp(NL + "  function render\\(\\) \\{").exec(src);
  if (!m) throw new Error("render() is gone from analytics.js — rewrite this harness");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) {
      return src.slice(m.index, j + 1).split(NL)
        .filter((l) => !l.trim().startsWith("//")).join(NL);
    }
  }
  throw new Error("unbalanced braces reading render");
}

function grab(re, what) {
  const m = re.exec(src);
  if (!m) throw new Error("could not lift " + what + " — rewrite this harness");
  return m[0];
}

const row = (o) => Object.assign({
  id: "x", name: "Job", stage_id: "s1", estimator_ids: ["e1"], company_ids: [],
  awarded_by_id: "", trades: [], awarded_at: null, submitted_at: null, lost_at: null,
  created_at: null, bid_deadline_at: null, quote: 0, won_amount: 0, pending_amount: 0,
  submitted_amount: 0, lost_amount: 0, archived: false,
}, o);

/** The same fixture the engine tests use: two decided bids, one undecided inside 90 days. */
const FIXTURE = [
  row({ id: "won1", awarded_at: "2025-09-10T15:00:00Z", submitted_at: "2025-08-01T15:00:00Z",
        won_amount: 100000, submitted_amount: 120000, trades: ["Gyp"] }),
  row({ id: "won2", awarded_at: "2026-01-05T15:00:00Z", submitted_at: "2025-12-01T15:00:00Z",
        won_amount: 50000, submitted_amount: 60000, trades: ["Epoxy", "Gyp"] }),
  row({ id: "fresh", submitted_at: "2026-07-01T15:00:00Z", submitted_amount: 400000,
        trades: ["Polish"] }),
];

/** A DOM just big enough for the two renderers, recording what they wrote. */
function dom(ids) {
  const nodes = {};
  ids.forEach((id) => {
    nodes[id] = { id, innerHTML: "", textContent: "", disabled: false, hidden: true,
                  insertAdjacentHTML(pos, html) { this.innerHTML += html; } };
  });
  return nodes;
}

/** Build the page scope. `opts.state` overrides STATE, `opts.data` overrides DATA. */
function scope(opts) {
  const o = opts || {};
  const nodes = dom(["filterbar", "active-filters", "cards", "alert",
                     "export-xlsx", "export-note"]);
  const requests = [];
  const downloads = [];

  const DATA = Object.assign({
    ok: true, building: false, generated_at: "2026-08-15T00:00:00Z", truncated: false,
    pull_window: {}, trades: ["Epoxy", "Gyp", "Polish"],
    estimators: [{ id: "e1", name: "Kyle" }], companies: [],
    stages: [{ id: "s1", name: "Bidding", color: "#888" }],
  }, o.data || {});

  const STATE = Object.assign({
    tab: "trailing12", preset: "all", from: "", to: "",
    trades: [], estimators: [], companies: [], stages: [], charts: {},
  }, o.state || {});

  // The charts module, only the formatters these two functions touch.
  const C = {
    esc: (s) => String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
    fmtMoney: (n) => "$" + Number(n).toFixed(2),
    fmtInt: (n) => String(n),
    fmtPct: (r) => (r * 100).toFixed(1) + "%",
  };

  const body = [
    "var esc = C.esc;",                       // analytics.js:29, module-level alias
    fn("revealExport"),                       // the one thing that makes the button usable
    grab(/^  var T12_ROWS = \[[\s\S]*?\];$/m, "T12_ROWS"),
    fn("win"), fn("filtered"), fn("options"), fn("pullWindow"),
    fn("t12Cell"), fn("renderTrailing12"),
    fn("exportTable"), fn("cellMoney"), fn("cellInt"), fn("cellPct"),
    fn("filterSentence"), fn("buildExportPayload"), fn("exportExcel"),
  ].join("\n");

  const api = (p, init) => {
    requests.push({ path: p, method: (init && init.method) || "GET",
                    body: init && init.body ? JSON.parse(init.body) : null,
                    headers: (init && init.headers) || null });
    if (o.apiFails) return Promise.resolve({ ok: false, status: 500,
                                             json: () => Promise.resolve({ detail: "boom" }) });
    return Promise.resolve({ ok: true, status: 200,
      json: () => Promise.resolve({ ok: true, xlsx_download_url: "/api/file/tok123" }) });
  };
  // The SECOND fetch — the actual file. Its headers are the thing under test.
  const fetchStub = (url, init) => {
    downloads.push({ url: String(url), headers: (init && init.headers) || null });
    return Promise.resolve({ ok: true, status: 200, arrayBuffer: () => Promise.resolve(new ArrayBuffer(8)) });
  };

  const api2 = new Function(
    "X", "C", "ROWS", "STATE", "DATA", "STAGES", "NAMES", "TABS", "DIMENSIONS", "$", "api",
    "fetch", "TW", "URL", "Blob", "document", "setTimeout",
    body + "\nreturn { renderTrailing12, buildExportPayload, exportExcel, revealExport };");

  const handles = api2(
    X, C, X.decorate(o.rows || FIXTURE), STATE, DATA, DATA.stages,
    { estimator: { e1: "Kyle" }, company: {}, stage: {}, trade: {} },
    [{ id: "overview", label: "Overview" },
     { id: "trades", label: "Trades", dim: "trade", noun: "Trade" },
     { id: "estimators", label: "Estimators", dim: "estimator", noun: "Estimator" },
     { id: "companies", label: "Companies", dim: "company", noun: "Company" },
     { id: "trailing12", label: "Trailing 12" }],
    [{ key: "trades", label: "Trades" }, { key: "estimators", label: "Estimators" },
     { key: "companies", label: "Companies" }, { key: "stages", label: "Stages" }],
    (id) => nodes[id], api, fetchStub,
    { absoluteUrl: (u) => "https://host" + u, authHeaders: () => ({ Authorization: "Bearer tok" }) },
    { createObjectURL: () => "blob:x", revokeObjectURL: () => {} },
    function Blob() {},
    { createElement: () => ({ click() {}, setAttribute() {} }),
      body: { appendChild() {}, removeChild() {} } },
    (f) => f());

  return { handles, nodes, requests, downloads };
}

const flush = () => new Promise((r) => setImmediate(r));

(async () => {
  const out = {};

  // ── the tab ────────────────────────────────────────────────────────────────
  {
    const s = scope({});
    // SEED both regions with what another tab left behind. Starting them empty made
    // "was it cleared?" unfalsifiable — it passed whether or not the code cleared anything, which
    // a mutation proved by deleting the clear and staying green.
    s.nodes.filterbar.innerHTML = "<span>STALE FILTER BAR</span>";
    s.nodes["active-filters"].innerHTML = '<span class="fchip">STALE CHIP</span>';
    s.handles.renderTrailing12();
    out.tab = {
      filterbar: s.nodes.filterbar.innerHTML,
      staleBarReplaced: s.nodes.filterbar.innerHTML.indexOf("STALE FILTER BAR") === -1,
      activeFiltersCleared: s.nodes["active-filters"].innerHTML === "",
      cards: s.nodes.cards.innerHTML,
    };
  }

  // THE ORG-WIDE GUARANTEE. Filters that exclude every row must not change one number: the tab
  // reads ROWS, and if it ever reads filtered() these two renders diverge.
  {
    const open = scope({});
    open.handles.renderTrailing12();
    const hostile = scope({ state: { estimators: ["nobody"], trades: ["Nonexistent"],
                                     preset: "custom", from: "2099-01-01", to: "2099-12-31" } });
    hostile.handles.renderTrailing12();
    out.orgWide = {
      identical: open.nodes.cards.innerHTML === hostile.nodes.cards.innerHTML,
      sample: hostile.nodes.cards.innerHTML.indexOf("$150000.00") !== -1,
    };
  }

  // ── the pull-window warnings ───────────────────────────────────────────────
  {
    const late = scope({ data: { pull_window: { from: "2026-01-01" } } });
    late.handles.renderTrailing12();
    const early = scope({ data: { pull_window: { to: "2026-01-01" } } });
    early.handles.renderTrailing12();
    const open = scope({});
    open.handles.renderTrailing12();
    const capped = scope({ data: { truncated: true } });
    capped.handles.renderTrailing12();
    out.warnings = {
      lateFrom: late.nodes.cards.innerHTML.indexOf("Under-reported") !== -1,
      earlyTo: early.nodes.cards.innerHTML.indexOf("Under-reported") !== -1,
      openWindowSilent: open.nodes.cards.innerHTML.indexOf("Under-reported") === -1,
      cappedWarns: capped.nodes.cards.innerHTML.indexOf("Capped") !== -1,
    };
  }

  // ── the export payload ─────────────────────────────────────────────────────
  {
    const s = scope({});
    const p = s.handles.buildExportPayload();
    out.payload = {
      tabNames: p.tabs.map((t) => t.name),
      t12Labels: p.trailing12.columns.map((c) => c.label),
      t12AllBids: p.trailing12.columns[0],
      carriesNoRatios: JSON.stringify(p.trailing12).indexOf("ratio") === -1,
      generatedAt: p.generated_at,
      filters: p.filters,
      firstOverviewRow: p.tabs[0].tables[0].rows[0],
    };
  }

  // A filtered export names the slice, while the trailing block stays org-wide.
  {
    const s = scope({ state: { trades: ["Epoxy"] } });
    const p = s.handles.buildExportPayload();
    out.filteredPayload = {
      filters: p.filters,
      t12Unchanged: p.trailing12.columns[0].won_amount,
    };
  }

  // The button ships hidden — a render has to reveal it, or the whole export is unreachable.
  // It shipped to staging that way once: the markup and the handler were both there and nothing
  // ever set hidden=false.
  {
    const s = scope({});
    const before = s.nodes["export-xlsx"].hidden;
    s.handles.revealExport();
    out.exportButton = {
      hiddenBeforeRender: before,
      hiddenAfterRender: s.nodes["export-xlsx"].hidden,
      // The sentence beside it explains what lands in the file; revealing one without the other
      // gives a bare button whose scope nobody can guess.
      noteRevealed: s.nodes["export-note"].hidden === false,
      // WIRED, not just present: lifting revealExport and calling it proves the function works and
      // nothing about whether render() ever calls it. Deleting the call left every executed
      // assertion green, which is how the unreachable version passed in the first place.
      calledByRender: /revealExport\(\);/.test(renderBody()),
      calledBeforeTheEarlyReturn:
        renderBody().indexOf("revealExport()") < renderBody().indexOf('if (tab().id === "trailing12")'),
    };
  }

  // ── the download ───────────────────────────────────────────────────────────
  {
    const s = scope({});
    s.nodes["export-xlsx"].textContent = "Download Excel";
    s.handles.exportExcel();
    const disabledDuring = s.nodes["export-xlsx"].disabled;
    const labelDuring = s.nodes["export-xlsx"].textContent;
    await flush(); await flush(); await flush(); await flush();
    out.download = {
      disabledDuring: disabledDuring, labelDuring: labelDuring,
      restored: s.nodes["export-xlsx"].disabled === false &&
                s.nodes["export-xlsx"].textContent === "Download Excel",
      posted: s.requests.map((r) => r.method + " " + r.path),
      fileUrl: s.downloads.length ? s.downloads[0].url : null,
      // /api/file/* is bearer-gated: without this header the download 401s in production only.
      fileCarriedAuth: !!(s.downloads.length && s.downloads[0].headers &&
                          s.downloads[0].headers.Authorization),
    };
  }

  // A failure says so and gives the button back.
  {
    const s = scope({ apiFails: true });
    s.nodes["export-xlsx"].textContent = "Download Excel";
    s.handles.exportExcel();
    await flush(); await flush(); await flush(); await flush();
    out.failure = {
      alerted: s.nodes.alert.innerHTML.indexOf("Could not build") !== -1,
      restored: s.nodes["export-xlsx"].disabled === false,
      noDownload: s.downloads.length === 0,
    };
  }

  // Mid-build there is nothing to export yet.
  {
    const s = scope({ data: { building: true } });
    s.handles.exportExcel();
    await flush();
    out.refusesWhileBuilding = { requests: s.requests.length };
  }

  console.log(JSON.stringify(out));
})();
