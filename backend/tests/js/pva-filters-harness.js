"use strict";
/* Plan vs Actual's filters, pager and address (#819), run WHOLE: the real js/plan-vs-actual.js and
 * the real js/project-calendar-core.js in a small fake browser.
 *
 * WHY WHOLE AND NOT LIFTED. What #819 can get wrong is wiring: the Status select and the count
 * buttons drifting apart, a filter change that leaves the list on page 3, an address that is not
 * written back, Back from a job's detail losing the page. Each of those lives between functions,
 * so the page runs as the browser runs it: its IIFE, its listeners, its fetch, its paints.
 *
 * THE FAKE BROWSER is only what the page touches: elements by id (text, innerHTML, value, hidden,
 * disabled, listeners, focus), the buttons a paint writes into innerHTML (read back out of the
 * markup, with their data-* and disabled), location and history.replaceState, and a fetch that
 * answers GET /api/project-analytics with the rows below and records every address asked for.
 *
 * The "raken" scenario also loads js/raken-connect.js after it, as project-calendar.html does, so
 * a Connect Raken sign-in coming back to this page is seen with both scripts running.
 *
 * Usage: node pva-filters-harness.js <frontend-dir> <scenario> [search] [hash]  ->  one JSON line
 *
 * PUBLIC REPO: every job and person is made up.
 */
const fs = require("fs");
const path = require("path");

const [ROOT, SCENARIO, SEARCH = "", HASH = ""] = process.argv.slice(2);
const P = require(path.join(ROOT, "js", "project-calendar-core.js"));

// ── sixty made-up jobs ───────────────────────────────────────────────────────────────────────────
// Job i (1-60) is 26.7ii. Work type: Polish when i is even, Epoxy when i % 4 == 1, else none.
// Foreman: Pat when i % 3 == 1, Lee when i % 3 == 0, Sam when i % 3 == 2 up to 30, none after.
// Statuses: Behind and Over budget when i % 6 == 0, Behind when i % 3 == 0, else On plan.
const pad = (n) => String(n).padStart(2, "0");
const PROJECTS = Array.from({ length: 60 }, (_, k) => {
  const i = k + 1;
  return {
    key: "job:26.7" + pad(i), job_number: "26.7" + pad(i), name: "Example Job " + i,
    is_punch: false, label: null,
    work_type: i % 2 === 0 ? "Polish" : (i % 4 === 1 ? "Epoxy" : null), color: null,
    foreman: i % 3 === 1 ? "Pat" : (i % 3 === 0 ? "Lee" : (i <= 30 ? "Sam" : null)),
    start: "2026-11-16", deadline: "2026-11-20", timing: "running", workdays_left: 3,
    workdays_so_far: 2, crew_size: 4, planned_hours: 64, crew_size_missing: false,
    mobilizations: [], punches: [], raken: { state: "not_connected" },
    statuses: i % 6 === 0 ? ["behind", "over_budget"] : (i % 3 === 0 ? ["behind"] : ["on_plan"]),
  };
});
// A Foreman whose name is markup, for the escaping check: job 32 has none otherwise.
const ODD_FOREMAN = "<b>O'Neil & \"Co\"</b>";
if (SCENARIO === "escape") PROJECTS[31].foreman = ODD_FOREMAN;
const COUNTS_KNOWN = SCENARIO !== "unknown-counts";
const DATA = {
  ok: true, connected: true, stale: false, today: "2026-11-18", so_far_through: "2026-11-17",
  hours_per_workday: 8, window_days: 14,
  work_types: [{ name: "Epoxy", color_id: "11", color: "#d50000" },
    { name: "Polish", color_id: "9", color: "#3f51b5" }, { name: "Gyp", color_id: "10", color: "#0b8043" }],
  raken: { state: "not_connected" }, raken_only: [], projects: PROJECTS,
  summary: COUNTS_KNOWN
    ? { jobs: 60, raken_read: true, unflagged: 0,
      counts: { on_plan: 40, behind: 20, over_budget: 10, not_linked: 0 } }
    : { jobs: 60, raken_read: false, counts: null, unflagged: null },
};

// ── the fake browser ─────────────────────────────────────────────────────────────────────────────
const focused = [];
const fetched = [];
const calls = [];                      // every request: [method, url, body]
const scrolls = [];                    // every scrollIntoView, by element id

/** The start tags a paint wrote, as fake elements: their attributes, data-*, disabled, focus. */
function children(html, focusName) {
  const out = [];
  const re = /<([a-z]+)((?:\s+[a-z-]+(?:="[^"]*")?)*)\s*>/g;
  let m;
  while ((m = re.exec(String(html || "")))) {
    const attrs = {};
    m[2].replace(/([a-z-]+)(?:="([^"]*)")?/g, (_, k, v) => { attrs[k] = v == null ? "" : v; });
    const dataset = {};
    Object.keys(attrs).forEach((k) => {
      if (k.indexOf("data-") === 0) {
        dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] =
          attrs[k].replace(/&quot;/g, '"').replace(/&#39;/g, "'")
            .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");  // &amp; last: decoded once
      }
    });
    const cls = (attrs.class || "").split(/\s+/).filter(Boolean);
    const node = {
      tag: m[1], attrs, dataset, classList: cls, disabled: "disabled" in attrs,
      getAttribute: (k) => (k in attrs ? attrs[k] : null),
      focus() { focused.push(focusName(node)); },
      closest(sel) { return matches(node, sel, true) ? node : null; },
    };
    out.push(node);
  }
  return out;
}

/** A selector as simple as the page's: "tag", ".cls", "[attr]", ".cls[attr]", "tr[attr]". In
 *  closest(), the tag is ignored when the selector also names an attribute: the button inside a
 *  row stands for the row. */
function matches(node, sel, forClosest) {
  const m = /^([a-z]+)?((?:\.[a-z0-9_-]+)*)(?:\[([a-z-]+)\])?$/.exec(sel.trim().split(/\s+/).pop());
  if (!m) return false;
  const [, tag, classes, attr] = m;
  if (tag && !(forClosest && attr) && node.tag !== tag) return false;
  if (classes && !classes.split(".").filter(Boolean).every((c) => node.classList.includes(c))) {
    return false;
  }
  return !attr || attr in node.attrs;
}

const focusNameOf = (n) => (n.dataset.page ? "page:" + n.dataset.page
  : n.dataset.key ? "row:" + n.dataset.key : n.dataset.st ? "tile:" + n.dataset.st : n.tag);

const els = {};
function el(id) {
  if (els[id]) return els[id];
  const node = {
    id, hidden: false, disabled: false, value: "", textContent: "", innerHTML: "", tabIndex: 0,
    open: false, dataset: {}, style: {}, listeners: {}, scrollLeft: 0, clientWidth: 0,
    scrollWidth: 0, offsetLeft: 0,
    parentElement: null,
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    setAttribute(k, v) { this["attr:" + k] = String(v); },
    getAttribute(k) { return this["attr:" + k] == null ? null : this["attr:" + k]; },
    removeAttribute(k) { delete this["attr:" + k]; },
    focus() { focused.push(id); },
    scrollIntoView() { scrolls.push(id); },
    rectTop: 0,                        // < 0: the element's top has scrolled out of view
    getBoundingClientRect() { return { top: this.rectTop }; },
    querySelectorAll(sel) { return children(this.innerHTML, focusNameOf).filter((n) => matches(n, sel)); },
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
  };
  node.parentElement = { scrollLeft: 0, clientWidth: 0, scrollWidth: 0 };
  els[id] = node;
  return node;
}

const location = { pathname: "/project-calendar.html", search: SEARCH, hash: HASH };
const history = {
  replaceState(_s, _t, url) {
    const u = new URL(url, "https://example.test");
    location.pathname = u.pathname;
    location.search = u.search;
    location.hash = u.hash;
  },
};
const tablist = el("tablist");
const document = {
  hidden: false,
  getElementById: el,
  querySelector: (sel) => (sel === '[role="tablist"]' ? tablist : null),
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: (tag) => ({ tag, className: "", textContent: "", children: [],
    appendChild(c) { this.children.push(c); return c; }, addEventListener() {}, click() {},
    remove() {} }),
  body: { firstChild: null, appendChild() {}, insertBefore() {} },
};
const window = { TWProjCal: P, addEventListener() {} };
const TW = { resolveApiBase: () => "", authHeaders: () => ({}) };
async function fetch(url, init) {
  fetched.push(url);
  calls.push([(init && init.method) || "GET", url, init && init.body ? JSON.parse(init.body) : null]);
  if (url === "/api/project-analytics") {
    return { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(DATA)) };
  }
  return { ok: true, status: 200, headers: { get: () => "" },
    arrayBuffer: async () => new ArrayBuffer(4), json: async () => ({}) };
}
const URL_ = { createObjectURL: () => "blob:x", revokeObjectURL() {} };

// The page itself, unchanged.
const src = fs.readFileSync(path.join(ROOT, "js", "plan-vs-actual.js"), "utf8");
new Function("window", "document", "location", "history", "TW", "fetch", "setInterval",
  "setTimeout", "clearTimeout", "URL", "Blob", src)(
  window, document, location, history, TW, fetch, () => 0, () => 0, () => {},
  Object.assign(function () {}, URL_), Blob);

// Connect Raken, loaded after the page as project-calendar.html loads it, signed in as an admin.
if (SCENARIO === "raken") {
  Object.assign(window, { document, location, history, fetch, TW,
    TWAuth: { ready: Promise.resolve(), user: () => ({ role: "admin" }) } });
  new Function("window", fs.readFileSync(path.join(ROOT, "js", "raken-connect.js"), "utf8"))(window);
}

// ── driving it ───────────────────────────────────────────────────────────────────────────────────
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r)); };
// `extra` adds to the event: {detail: 1} is a pointer click, a keyboard press has detail 0.
function fire(id, type, target, extra) {
  (el(id).listeners[type] || []).forEach((fn) => fn(Object.assign({ target: target || el(id),
    key: "", detail: 0, preventDefault() {}, stopPropagation() {} }, extra || {})));
}
function choose(id, value) { el(id).value = value; fire(id, "change"); }
function press(containerId, sel, pick, extra) {
  const node = el(containerId).querySelectorAll(sel).find(pick);
  if (!node) throw new Error("nothing to press in " + containerId + " for " + sel);
  fire(containerId, "click", node, extra);
}
const pressPage = (v, extra) => press("pva-pages", "[data-page]",
  (n) => n.dataset.page === String(v), extra);
// An attribute value as the browser hands it back: the markup's entities undone.
const unescape = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");

const optionsOf = (id) => {
  const out = [];
  String(el(id).innerHTML).replace(/<option value="([^"]*)">([^<]*)<\/option>/g,
    (_, v, l) => { out.push([v, l]); });
  return out;
};
function snap() {
  const pages = el("pva-pages").querySelectorAll("[data-page]");
  const nums = pages.filter((n) => /^\d+$/.test(n.dataset.page));
  const end = (v) => { const b = pages.find((n) => n.dataset.page === v); return !b || b.disabled; };
  const rows = (String(el("pva-body").innerHTML).match(/<tr data-key=/g) || []).length;
  const jn = /class="jn">([^<]*)</.exec(el("pva-body").innerHTML);
  return {
    rows, first: jn ? jn[1] : null, range: el("pva-range").textContent,
    count: el("pva-count").textContent,
    pages: nums.map((n) => n.dataset.page),
    current: (nums.find((n) => n.getAttribute("aria-current") === "page") || { dataset: {} }).dataset.page || null,
    prev_disabled: end("prev"), next_disabled: end("next"),
    url: location.pathname + location.search + location.hash,
    clear_hidden: el("pva-clear").hidden, pager_hidden: el("pva-pager").hidden,
    wt_options: optionsOf("pva-wt"), fm_options: optionsOf("pva-fm"), st_options: optionsOf("pva-st"),
    st_disabled: el("pva-st").disabled, select: el("pva-st").value,
    st_described: el("pva-st").getAttribute("aria-describedby"),
    note_id: (/<p id="([^"]*)" class="sum-note">/.exec(el("pva-sum").innerHTML) || [])[1] || null,
    range_live: el("pva-range").getAttribute("aria-live"),
    values: { q: el("pva-q").value, wt: el("pva-wt").value, fm: el("pva-fm").value,
      st: el("pva-st").value, per: el("pva-per").value },
    pressed: el("pva-sum").querySelectorAll("[data-st]")
      .filter((n) => n.getAttribute("aria-pressed") === "true").map((n) => n.dataset.st),
    empty: el("pva-empty").hidden ? "" : el("pva-empty").textContent,
    tab: el("panel-schedule").hidden ? "pva" : "schedule",
    detail_open: !el("pva-detail").hidden,
    focus: focused[focused.length - 1] || null,
  };
}
const pick = (s, keys) => Object.fromEntries(keys.map((k) => [k, s[k]]));

(async () => {
  await settle();
  let out;
  if (SCENARIO === "open" || SCENARIO === "unknown-counts") {
    out = snap();
  } else if (SCENARIO === "polish") {
    pressPage("next");
    const b = snap();
    choose("pva-wt", "Polish");
    out = Object.assign(snap(), { before: { page: b.current, url: b.url } });
  } else if (SCENARIO === "status") {
    const look = () => pick(snap(), ["pressed", "select", "url", "rows"]);
    choose("pva-st", "behind");
    const a = look();
    press("pva-sum", "[data-st]", (n) => n.dataset.st === "over_budget");
    const b = look();
    fire("pva-showall", "click");
    out = { after_select: a, after_tile: b, after_showall: look() };
  } else if (SCENARIO === "clear") {
    const before = snap();
    fire("pva-clear", "click");
    out = Object.assign(snap(), { before });
  } else if (SCENARIO === "pager") {
    const step = () => { const s = snap();
      return [s.current, s.range, s.prev_disabled, s.next_disabled, s.url]; };
    const steps = [];
    const focus = [];
    pressPage(3); steps.push(step()); focus.push(snap().focus);
    pressPage("prev"); steps.push(step()); focus.push(snap().focus);
    pressPage("next"); steps.push(step()); focus.push(snap().focus);
    choose("pva-per", "100"); steps.push(step());
    out = { steps, focus };
  } else if (SCENARIO === "detail") {
    press("pva-body", ".jlink", () => true);
    const open = snap();
    fire("pd-back", "click");
    out = Object.assign(snap(), { detail_open: open.detail_open, url_in_detail: open.url });
  } else if (SCENARIO === "escape") {
    const html = el("pva-fm").innerHTML;
    const odd = optionsOf("pva-fm").find((o) => o[1].indexOf("Neil") >= 0);
    choose("pva-fm", unescape(odd[0]));
    out = Object.assign(snap(), { fm_html: html, odd_option: odd, odd: ODD_FOREMAN });
  } else if (SCENARIO === "pager-scroll") {
    // The list's top has scrolled away (the pager sits under 25 rows).
    el("pva-main").rectTop = -400;
    const step = (label) => { const s = snap();
      return { label, current: s.current, focus: s.focus, scrolls: scrolls.length,
        range_live: s.range_live }; };
    pressPage(2);                      // the keyboard: Enter on the page 2 button
    const key = step("keyboard");
    pressPage(3, { detail: 1 });       // a pointer click
    const click = step("pointer");
    choose("pva-wt", "Polish");        // a filter: the count line says it, not the range
    out = { key, click, filter: step("filter") };
  } else if (SCENARIO === "raken") {
    out = Object.assign(pick(snap(), ["url", "rows", "values"]), {
      posts: calls.filter((c) => c[0] === "POST") });
  } else if (SCENARIO === "download") {
    fetched.length = 0;
    fire("pva-download", "click");
    await settle();
    out = { fetched: fetched[0] || null };
  } else {
    throw new Error("unknown scenario " + SCENARIO);
  }
  console.log(JSON.stringify(out));
})().catch((err) => { console.error(err && err.stack || err); process.exit(1); });
