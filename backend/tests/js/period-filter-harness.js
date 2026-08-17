"use strict";
/* Exercise the board's period filter FOR REAL: the week helpers out of shared.js and applyPeriod +
 * populatePeriods out of portal.js.
 *
 * Executed rather than grepped, for the reason the STAGE_CREATED outage taught: a source assertion
 * cannot tell you whether the code runs, let alone whether it buckets a Sunday evening in Kansas
 * into the right week.
 *
 * Usage: node period-filter-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];

// shared.js is a browser IIFE that hangs TW off window. Give it the smallest shim that lets it
// finish loading; everything under test is pure date arithmetic.
const win = { addEventListener() {}, location: { reload() {}, href: "http://x/" } };
const store = { getItem: () => null, setItem() {}, removeItem() {} };
new Function("window", "document", "localStorage", "sessionStorage",
             fs.readFileSync(path.join(ROOT, "shared.js"), "utf8"))(
  win, { addEventListener() {}, readyState: "complete" }, store, store);
const TW = win.TW;

const portal = fs.readFileSync(path.join(ROOT, "js", "portal.js"), "utf8");

function lift(re, what) {
  const m = re.exec(portal);
  if (!m) throw new Error(what + " not found in portal.js — rewrite this harness, don't delete it");
  return m[0];
}

const applyPeriodSrc = lift(/const applyPeriod = \(list\) => \{[\s\S]*?\n  \};/, "applyPeriod");
const populateSrc = lift(/\n  function populatePeriods\(\) \{[\s\S]*?\n  \}/, "populatePeriods");
const weeksOffered = Number((/const WEEKS_OFFERED = (\d+);/.exec(portal) || [])[1]);

// ── applyPeriod ──────────────────────────────────────────────────────────────
const runFilter = new Function("TW", "activityTs",
  "let PERIOD;" + applyPeriodSrc.replace("const applyPeriod =", "const f =") +
  "return (rows, per) => { PERIOD = per; return f(rows); };")(TW, (p) => p.ts);

// Central is UTC-5 in August, so 05:00Z is Monday 00:00 and 04:59Z is still Sunday.
const ROWS = [
  { id: "wed", ts: "2026-08-12T18:00:00Z" },
  { id: "mon-first-minute", ts: "2026-08-10T05:00:00Z" },
  { id: "sun-last-minute-prev", ts: "2026-08-10T04:59:00Z" },
  { id: "prev-week", ts: "2026-08-05T14:00:00Z" },
  { id: "july", ts: "2026-07-15T14:00:00Z" },
  { id: "dst-spring", ts: "2026-03-11T12:00:00Z" },
  { id: "no-activity", ts: null },
];
const ids = (l) => l.map((r) => r.id);

// ── populatePeriods ──────────────────────────────────────────────────────────
// A <select> stub that records what was written, plus the module state the function closes over.
function populate(rows, period) {
  const sel = { innerHTML: "", value: "" };
  const state = { PERIOD: period, stored: undefined };
  const fnBody =
    "let PERIOD = state.PERIOD;" +
    "const $ = () => sel;" +
    "const esc = (v) => String(v == null ? '' : v);" +
    "const boardPool = () => rows;" +
    "const activityTs = (p) => p.ts;" +
    "const ssSet = (k, v) => { state.stored = v; };" +
    "const WEEKS_OFFERED = " + weeksOffered + ";" +
    "const PERIOD_KEY = 'tw_crm_month';" +
    populateSrc +
    ";populatePeriods(); state.PERIOD = PERIOD; return { html: sel.innerHTML, value: sel.value };";
  const out = new Function("TW", "rows", "sel", "state", fnBody)(TW, rows, sel, state);
  return { ...out, period: state.PERIOD, cleared: state.stored === "" };
}

const groups = (html) => (html.match(/<optgroup label="([^"]+)"/g) || [])
  .map((g) => g.replace(/.*label="([^"]+)".*/, "$1"));
const options = (html) => (html.match(/<option value="([^"]*)">([^<]*)</g) || [])
  .map((o) => {
    const m = /value="([^"]*)">([^<]*)</.exec(o);
    return { value: m[1], label: m[2] };
  });

// Six weeks of activity plus a seventh, to prove the cap and that the cap is the NEWEST weeks.
const MANY = [];
for (let i = 0; i < 8; i++) {
  MANY.push({ id: "w" + i, ts: new Date(Date.UTC(2026, 7, 12) - i * 7 * 86400000).toISOString() });
}

const thisWeek = TW.bizWeekStart(new Date().toISOString());
const lastWeek = TW.bizWeekStart(new Date(Date.now() - 7 * 86400000).toISOString());

const dayName = (ymd) => new Date(ymd + "T12:00:00Z")
  .toLocaleDateString("en-US", { timeZone: "America/Chicago", weekday: "short" });

const out = {
  weeksOffered: weeksOffered,
  // Every bucket must be a Monday in Central, including across both DST changes.
  mondays: ["2026-08-12T18:00:00Z", "2026-03-11T12:00:00Z", "2026-11-04T12:00:00Z",
            "2026-01-01T12:00:00Z"].map((iso) => {
    const w = TW.bizWeekStart(iso);
    return { iso: iso, week: w, day: dayName(w), label: TW.bizWeekLabel(w) };
  }),
  boundary: {
    mondayFirstMinute: TW.bizWeekStart("2026-08-10T05:00:00Z"),
    oneMinuteEarlier: TW.bizWeekStart("2026-08-10T04:59:00Z"),
    sundayLastMinute: TW.bizWeekStart("2026-08-17T04:59:00Z"),
  },
  empties: {
    nullIn: TW.bizWeekStart(null),
    emptyIn: TW.bizWeekStart(""),
    junkIn: TW.bizWeekStart("not a date"),
    ymNull: TW.bizYM(null),
  },
  labels: {
    sameMonth: TW.bizWeekLabel("2026-08-10"),
    acrossMonths: TW.bizWeekLabel("2026-08-31"),
    acrossYears: TW.bizWeekLabel("2025-12-29"),
  },
  filter: {
    none: ids(runFilter(ROWS, "")),
    thisWeek: ids(runFilter(ROWS, "w:2026-08-10")),
    prevWeek: ids(runFilter(ROWS, "w:2026-08-03")),
    august: ids(runFilter(ROWS, "2026-08")),
    july: ids(runFilter(ROWS, "2026-07")),
    unknownWeek: ids(runFilter(ROWS, "w:1999-01-04")),
  },
  dropdown: (() => {
    // "This week" and "Last week" are named RELATIVE TO TODAY, and a period with no rows is never
    // offered — so proving those two labels needs rows in those two weeks, whenever the suite runs.
    // ROWS is pinned to August 2026 because its other job is the Central-midnight and DST
    // boundaries, which only mean anything at fixed instants. It stopped being "this week" on
    // 2026-08-17 and the label test went red on a calendar roll, having tested nothing about the
    // code. These two rows are the fix: derived from now, so the labels stay checkable forever.
    const NOW = Date.now();
    const named = ROWS.concat([
      { id: "in-this-week", ts: new Date(NOW).toISOString() },
      { id: "in-last-week", ts: new Date(NOW - 7 * 86400000).toISOString() },
    ]);
    const r = populate(named, "");
    return { groups: groups(r.html), options: options(r.html), value: r.value };
  })(),
  capped: (() => {
    const r = populate(MANY, "");
    const opts = options(r.html).filter((o) => o.value.slice(0, 2) === "w:");
    return { weekCount: opts.length, values: opts.map((o) => o.value) };
  })(),
  staleSelection: (() => {
    // A week with no rows any more (e.g. after switching tab) must be dropped, not left selected.
    const r = populate(ROWS, "w:1999-01-04");
    return { period: r.period, cleared: r.cleared, value: r.value };
  })(),
  beyondTheCap: (() => {
    // A week that DOES have rows but fell past WEEKS_OFFERED. It is unreachable in the dropdown, so
    // leaving it selected strands the board with no way back but Clear. MANY has 8 weeks; take the
    // oldest, which the cap of 6 excludes.
    const all = [...new Set(MANY.map((r) => TW.bizWeekStart(r.ts)))].sort();
    const oldest = "w:" + all[0];
    const r = populate(MANY, oldest);
    return { picked: oldest, period: r.period, cleared: r.cleared,
             offeredCount: options(r.html).filter((o) => o.value.slice(0, 2) === "w:").length };
  })(),
  namedFromToday: (() => {
    // Rows whose newest week is NOT the current one. "This week" must not slide onto whatever
    // happens to be first in the list — that would label an old week as the live one.
    const old = [30, 37, 44].map((d, i) => ({
      id: "o" + i, ts: new Date(Date.now() - d * 86400000).toISOString() }));
    const r = populate(old, "");
    const labels = options(r.html).filter((o) => o.value.slice(0, 2) === "w:").map((o) => o.label);
    return { labels: labels,
             saysThisWeek: labels.some((l) => l.startsWith("This week")),
             saysLastWeek: labels.some((l) => l.startsWith("Last week")) };
  })(),
  legacyMonthKept: (() => {
    const r = populate(ROWS, "2026-07");
    return { period: r.period, value: r.value, cleared: r.cleared };
  })(),
  namedWeeks: { thisWeek: thisWeek, lastWeek: lastWeek },
};

console.log(JSON.stringify(out));
