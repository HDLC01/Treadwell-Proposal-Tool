"use strict";
/* Execute the real pull-window control out of analytics.js, and the real notice branch out of
 * calendar.js.
 *
 * WHY EXECUTED. Both are claims about what a person sees and what request leaves the browser: does
 * the caption read the APPLIED window or the half-typed one, does Save send `from`/`to` the right
 * way round, does the calendar prefer the stale message over the window one. A grep can answer
 * none of that, and on 2026-08-12 an unbound identifier took the board down on prod with every
 * source assertion green.
 *
 * Usage: node pull-window-ui-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[1] === __filename ? process.argv[2] : process.argv[2];
const AN = fs.readFileSync(path.join(ROOT, "js", "analytics.js"), "utf8");
const CAL = fs.readFileSync(path.join(ROOT, "js", "calendar.js"), "utf8");

// ── a DOM small enough to reason about, real enough to render into ───────────
function el(id) {
  return { id, innerHTML: "", textContent: "", value: "", min: "", max: "", disabled: false,
           hidden: false, className: "", classList: { add() {}, remove() {}, toggle() {} },
           insertAdjacentHTML(pos, html) { this.innerHTML += html; },
           querySelector: () => null, querySelectorAll: () => [], focus() {} };
}

function dom(ids) {
  const els = {};
  ids.forEach((i) => { els[i] = el(i); });
  return {
    els,
    getElementById: (i) => els[i] || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener() {},
  };
}

function lift(src, name, deps) {
  const re = new RegExp("^  function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}", "m");
  const m = re.exec(src);
  if (!m) throw new Error("could not lift " + name);
  const keys = Object.keys(deps);
  return new Function(...keys, m[0] + "\nreturn " + name + ";")(...keys.map((k) => deps[k]));
}

const esc = (s) => String(s == null ? "" : s)
  .replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ── the control ──────────────────────────────────────────────────────────────
function analyticsHarness(payload) {
  const document = dom(["pullwindow", "pw-from", "pw-to", "pw-save", "filterbar", "sub"]);
  const requests = [];
  const deps = {
    document,
    $: (id) => document.getElementById(id),
    esc,
    DATA: payload,
    X: { bizDay: (iso) => String(iso).slice(0, 10) },
    C: { fmtInt: (n) => String(n) },
    api: (p, o) => {
      requests.push({ path: p, method: (o && o.method) || "GET", body: o && o.body });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    },
    setTimeout: () => 0,
    render: () => {},
    adopt: () => {},
    pollForWindow: () => {},
  };
  deps.pullWindow = lift(AN, "pullWindow", deps);
  const renderPullWindow = lift(AN, "renderPullWindow", deps);
  deps.renderPullWindow = renderPullWindow;
  const savePullWindow = lift(AN, "savePullWindow", deps);
  return { document, requests, renderPullWindow, savePullWindow };
}

const out = {};

// 1. An unset window says so, and offers empty boxes.
{
  const h = analyticsHarness({ ok: true, pull_window: { from: null, to: null } });
  h.renderPullWindow();
  const html = h.document.els.pullwindow.innerHTML;
  out.unset = {
    saysEverything: /pulling everything BasisBoard has/.test(html),
    hasFrom: /id="pw-from" value=""/.test(html),
    hasTo: /id="pw-to" value=""/.test(html),
    hasSave: /id="pw-save"/.test(html),
  };
}

// 2. A set window is described, with who set it.
{
  const h = analyticsHarness({ ok: true, pull_window: {
    from: "2024-01-01", to: "2026-08-01",
    updated_at: "2026-08-13T15:00:00Z", updated_by: "kyle@wetreadwell.com" } });
  h.renderPullWindow();
  const html = h.document.els.pullwindow.innerHTML;
  out.set = {
    describes: /pulling 2024-01-01 → 2026-08-01/.test(html),
    inputsCarryIt: /id="pw-from" value="2024-01-01"/.test(html) &&
                   /id="pw-to" value="2026-08-01"/.test(html),
    saysWho: /kyle@wetreadwell\.com/.test(html),
    saysWhen: /2026-08-13/.test(html),
    // Cross-bounds, so the picker itself refuses a backwards range.
    crossBounded: /max="2026-08-01"/.test(html) && /min="2024-01-01"/.test(html),
  };
}

// 3. THE CAPTION READS THE APPLIED WINDOW, not what is typed. A half-finished edit must not
//    describe the numbers on screen.
{
  const h = analyticsHarness({ ok: true, pull_window: { from: "2024-01-01", to: null } });
  h.renderPullWindow();
  h.document.els["pw-from"].value = "1999-01-01";      // somebody typing
  h.renderPullWindow();
  out.captionIgnoresTyping = /pulling 2024-01-01/.test(h.document.els.pullwindow.innerHTML) &&
    !/1999/.test(h.document.els.pullwindow.innerHTML.replace(/value="[^"]*"/g, ""));
}

// 4. Save sends a PUT with from/to the right way round.
{
  const h = analyticsHarness({ ok: true, pull_window: { from: null, to: null } });
  h.renderPullWindow();
  h.document.els["pw-from"].value = "2024-01-01";
  h.document.els["pw-to"].value = "2026-08-01";
  h.savePullWindow();
  const r = h.requests[0] || {};
  out.save = { path: r.path, method: r.method, body: r.body ? JSON.parse(r.body) : null };
}

// 5. An empty box clears that side rather than sending "".
{
  const h = analyticsHarness({ ok: true, pull_window: { from: "2024-01-01", to: "2025-01-01" } });
  h.renderPullWindow();
  h.document.els["pw-from"].value = "";
  h.document.els["pw-to"].value = "";
  h.savePullWindow();
  out.cleared = JSON.parse(h.requests[0].body);
}

// 6. A backwards range is refused in the browser, before any request.
{
  const h = analyticsHarness({ ok: true, pull_window: { from: null, to: null } });
  h.renderPullWindow();
  h.document.els["pw-from"].value = "2026-08-01";
  h.document.els["pw-to"].value = "2024-01-01";
  h.savePullWindow();
  out.backwards = { requests: h.requests.length,
                    says: /backwards/i.test(h.document.els.pullwindow.innerHTML),
                    bad: /pw-msg bad/.test(h.document.els.pullwindow.innerHTML) };
}

// 7. A failed save says so and does not claim success.
{
  const document = dom(["pullwindow", "pw-from", "pw-to", "pw-save"]);
  const deps = {
    document, $: (id) => document.getElementById(id), esc,
    DATA: { ok: true, pull_window: {} },
    X: { bizDay: (s) => s }, C: { fmtInt: String },
    api: () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) }),
    setTimeout: () => 0, render: () => {}, adopt: () => {}, pollForWindow: () => {},
  };
  deps.pullWindow = lift(AN, "pullWindow", deps);
  const renderPullWindow = lift(AN, "renderPullWindow", deps);
  deps.renderPullWindow = renderPullWindow;
  const save = lift(AN, "savePullWindow", deps);
  renderPullWindow();
  document.els["pw-from"].value = "2024-01-01";
  const done = save();
  out.failedSave = (done && done.then ? done : Promise.resolve()).then(() => ({
    saysFailed: /Couldn't save/.test(document.els.pullwindow.innerHTML),
    bad: /pw-msg bad/.test(document.els.pullwindow.innerHTML),
  }));
}

// ── the filter-bar warning: a slice we do not hold ───────────────────────────
function warnFacts(payloadWindow, state) {
  const document = dom(["filterbar"]);
  const deps = {
    document, $: (id) => document.getElementById(id), esc,
    DATA: { ok: true, pull_window: payloadWindow },
    STATE: Object.assign({ preset: "custom", from: "", to: "", trades: [], estimators: [],
                           companies: [], stages: [] }, state),
    DIMENSIONS: [],
    X: { PRESETS: [{ id: "custom", label: "Custom" }] },
    win: () => ({ from: state.from || "", to: state.to || "" }),
  };
  deps.pullWindow = lift(AN, "pullWindow", deps);
  lift(AN, "renderFilterBar", deps)();
  return document.els.filterbar.innerHTML;
}
out.warn = {
  before: /we only hold/.test(warnFacts({ from: "2024-01-01", to: null },
                                        { from: "2019-01-01", to: "2026-01-01" })),
  after: /we only hold/.test(warnFacts({ from: null, to: "2025-12-31" },
                                       { from: "2025-01-01", to: "2026-06-01" })),
  inside: /we only hold/.test(warnFacts({ from: "2024-01-01", to: "2026-12-31" },
                                        { from: "2025-01-01", to: "2025-06-01" })),
  noWindow: /we only hold/.test(warnFacts({ from: null, to: null },
                                          { from: "1999-01-01", to: "2026-01-01" })),
  // The filter must NOT be clamped — silently moving somebody's dates is worse than an empty
  // answer, so the typed values survive.
  keepsTypedDates: /id="f-from" value="2019-01-01"/.test(
    warnFacts({ from: "2024-01-01", to: null }, { from: "2019-01-01", to: "2026-01-01" })),
};

// ── the calendar's notice ────────────────────────────────────────────────────
// The alert text is decided inline in `load`, so lift that decision by running the same
// expression against the payloads that matter. showAlert is the real function.
function calendarNotice(payload) {
  const document = dom(["alert"]);
  const showAlert = lift(CAL, "showAlert", { $: (id) => document.getElementById(id), document });
  showAlert(lift(CAL, "bbNotice", {})(payload), true);
  return document.els.alert.textContent;
}
out.calendar = {
  windowed: calendarNotice({ stale: false, pull_window: { from: "2024-01-01", to: "2025-12-31" } }),
  open: calendarNotice({ stale: false, pull_window: { from: null, to: null } }),
  missingKey: calendarNotice({ stale: false }),
  staleWins: calendarNotice({ stale: true, pull_window: { from: "2024-01-01", to: null } }),
};

Promise.resolve(out.failedSave).then((fs2) => {
  out.failedSave = fs2;
  console.log(JSON.stringify(out));
});
