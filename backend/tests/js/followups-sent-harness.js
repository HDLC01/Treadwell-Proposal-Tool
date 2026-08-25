"use strict";
/* The Follow-ups page's SENT HISTORY, executed: the real row() and histRow() out of the real
 * frontend/js/followups.js.
 *
 * WHY EXECUTED AND NOT READ. test_followups_page.py asserts this page by reading its source, which
 * is right for "is it wired to the feed" and useless for the two things that broke here:
 *
 *   1. A row that carries the panel only when OPEN holds its id, and a panel that renders three
 *      different states (loading, error, a log) from HIST. Source text cannot tell you which
 *      branch a given state takes, and an unbound identifier inside a template literal is a
 *      whole-page ReferenceError that every source assertion in the suite passes straight over.
 *      That has taken this app down before (STAGE_CREATED, 2026-08-12).
 *   2. The AUDIENCE WORDING. Half the cadence is written to the estimator and never reaches the
 *      customer, so a line reading "sent to the customer" on a staff-only reminder tells somebody
 *      the customer has been chased when they have not. That claim has to be produced by the real
 *      function from a real worker payload, not matched as a string.
 *
 * WHAT IT LIFTS. row(), histRow() and head() with exactly the module-level names they close over,
 * bracket-counted out of the file rather than retyped, so renaming one here fails loudly instead of
 * testing something the page does not have. crm-core and followups-core are REQUIRED, not stubbed:
 * the wording comes out of followups-core.sentLog and the whole point is that it is the real one.
 *
 * Usage: node followups-sent-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const src = fs.readFileSync(path.join(ROOT, "js", "followups.js"), "utf8").replace(/\r\n/g, "\n");
const C = require(path.join(ROOT, "js", "crm-core.js"));
const B = require(path.join(ROOT, "js", "followups-core.js"));

// ── lifting real code out of the IIFE (same two helpers the drawer harness uses) ──
function fnSrc(name) {
  const m = new RegExp("\\n\\s{2,6}(?:async\\s+)?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from followups.js: rewrite this harness, don't delete it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

function declSrc(kind, name) {
  const m = new RegExp("\\n\\s*" + kind + " " + name.replace(/[$]/g, "\\$&") + " = ").exec(src);
  if (!m) throw new Error(kind + " " + name + " is gone from followups.js: rewrite this harness");
  let depth = 0;
  for (let j = m.index + m[0].length; j < src.length; j++) {
    const ch = src[j];
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (ch === ";" && depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unterminated declaration reading " + name);
}

// Business-timezone dates, the one helper the panel calls that lives in shared.js. Stubbed to a
// FIXED marker rather than a real formatter: what this harness checks is that every date on the
// panel goes through TW, because a viewer-local `new Date().toLocaleDateString()` is a house-rule
// violation the page cannot see for itself (the dev box and Central are usually the same day).
const DATES = [];
const TW = {
  fmtBizDate: (iso) => { DATES.push(iso); return "BIZ(" + iso + ")"; },
  fmtBizDay: (d) => "DAY(" + d + ")",
  bizToday: () => "2026-08-24",
};

const sandbox = {
  console, JSON, Math, Date, Number, String, Boolean, Array, Object, Set, Map, isFinite,
  encodeURIComponent, TW, C, B,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

// Order matters: COLS and the helpers are read while row()/histRow() run, and `fu` reads nothing.
// K / ss / SORTS / NATURAL come with them because SORT and DIR are declared THROUGH them
// (SORTS.includes(ss(K.sort))), and sessionStorage is stubbed empty above so both land on the
// defaults a first visit gets. Lifted rather than retyped for the usual reason: a pinned
// SORT = "score" here would keep passing after the page stopped defaulting to it.
const LIFT = [
  ["const", "esc"], ["const", "money"], ["const", "DAY"], ["const", "days"], ["const", "fu"],
  ["const", "K"], ["const", "ss"], ["const", "SORTS"], ["const", "NATURAL"],
  ["const", "OPEN"], ["const", "HIST"], ["const", "COLS"],
  ["let", "SORT"], ["let", "DIR"],
];
let code = "";
for (const [kind, name] of LIFT) code += declSrc(kind, name) + "\n";
for (const name of ["stateOf", "dueLabel", "head", "histRow", "row"]) code += fnSrc(name) + "\n";
vm.runInContext(code, sandbox, { filename: "followups.js (lifted)" });

const run = (expr) => vm.runInContext(expr, sandbox);

// ── the payloads ─────────────────────────────────────────────────────────────
// A project the cadence has emailed twice, once each way, plus one thing a person logged and one
// piece of bookkeeping. This is the shape followup_worker.reserve_followup writes:
// {audience, template, rule_key} on a row of kind auto_email.
const LOG = [
  { kind: "auto_email", created_at: "2026-08-24T13:00:00Z",
    detail: { audience: "customer", template: "second_nudge", rule_key: "second_nudge" } },
  { kind: "auto_email", created_at: "2026-08-23T13:00:00Z",
    detail: { audience: "staff", template: "staff_personal_followup",
              rule_key: "staff_personal_followup" } },
  { kind: "staff_call", created_at: "2026-08-22T13:00:00Z", by: "kyle@wetreadwell.com",
    detail: { note: "left a voicemail" } },
  { kind: "staff_note", created_at: "2026-08-21T13:00:00Z", detail: { action: "automation_off" } },
];

// The row itself as the feed serves it. last_followup_at is the portal's STAFF-only stamp, so it
// deliberately predates the two automated sends above: that mismatch is the bug this feature is
// about, and the harness would be dishonest without it.
const P = {
  proposal_id: "p-1", project_name: "Test Job", customer_name: "A Customer",
  customer_email: "c@example.test", proposal_status: "sent",
  assigned_estimator: "kyle@wetreadwell.com", estimator_email: "kyle@wetreadwell.com",
  followup_state: { enrolled: true, enabled: true, paused_until: null },
  last_followup_at: "2026-08-22T13:00:00Z", last_activity_at: "2026-08-24T13:00:00Z",
  next_followup_at: "2026-08-27T13:00:00Z", approved_total: 12345, unread: 0,
  reason: "Nobody has chased this in nine days.",
};

function rowFor(state) {
  run("OPEN.clear(); for (const k of Object.keys(HIST)) delete HIST[k];");
  DATES.length = 0;
  if (state) {
    sandbox.__st = state;
    run("OPEN.add('p-1'); HIST['p-1'] = __st;");
  }
  sandbox.__p = P;
  return { html: run("row(__p)"), dates: DATES.slice() };
}

const log = B.sentLog(LOG);

const out = {
  // What the two vocabularies produce, so the python side can compare them against portal.js's.
  templates: B.FU_TEMPLATE_LABEL,
  kinds: B.FU_KIND_LABEL,
  actions: B.FU_ACTION,
  summary: { emails: log.emails, toCustomer: log.toCustomer, toStaff: log.toStaff, last: log.last },
  lines: log.lines,
  head: run("head()"),
  closed: rowFor(null),
  loading: rowFor({ state: "loading" }),
  errored: rowFor({ state: "error", error: "HTTP 502" }),
  open: rowFor({ state: "ok", log: log }),
  empty: rowFor({ state: "ok", log: B.sentLog([]) }),
  // A log the portal could plausibly hand back after a schema change, or on a legacy row written
  // before the worker stored a detail at all. The panel is read-only reporting: it must render
  // something rather than throw, because a throw inside a template literal takes the whole table
  // down, not one line of it.
  junk: (function () {
    var probes = [null, undefined, [], [{}], [{ kind: "auto_email" }],
                  [{ kind: "auto_email", detail: null, created_at: null }],
                  [{ kind: "wat", detail: { note: 7 } }]];
    var got = [];
    for (var i = 0; i < probes.length; i++) {
      try {
        var l = B.sentLog(probes[i]);
        sandbox.__st = { state: "ok", log: l };
        run("OPEN.clear(); OPEN.add('p-1'); HIST['p-1'] = __st;");
        sandbox.__p = P;
        run("row(__p)");                     // the markup path too, not just the numbers
        got.push({ ok: true, emails: l.emails, lines: l.lines.length,
                   what: l.lines.length ? l.lines[0].what : "",
                   side: l.lines.length ? l.lines[0].side : "" });
      } catch (e) {
        got.push({ ok: false, error: String(e && e.message || e) });
      }
    }
    return got;
  })(),
};

process.stdout.write(JSON.stringify(out) + "\n");
