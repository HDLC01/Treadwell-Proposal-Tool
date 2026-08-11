"use strict";
/* RENDER the Active Projects board, for real, on every tab and in both views.
 *
 * WHY THIS EXISTS. On 2026-08-12 the board went down on production with
 * `ReferenceError: STAGE_CREATED is not defined`: kanbanHtml gained `s === STAGE_CREATED` to decide
 * which column carries the + New button, crm-core exports that constant, and portal.js never
 * destructured it. An unresolved identifier inside a .map() callback throws on the FIRST row, so
 * nothing painted — while the tab counts above the board were correct, because those are written
 * before `board.innerHTML` and the throw happened during it.
 *
 * Every test that touched this code asserted the source TEXT — that `"s === STAGE_CREATED"` appears
 * in the gate — and not one of them ever ran the function. A string being present is not the guard
 * working; here it was not even the identifier existing.
 *
 * So: lift the render functions out of the IIFE, bind ONLY what the page really binds (crm-core's
 * exports by their real names, plus the DOM-ish helpers), and render. Anything portal.js uses
 * without importing is an immediate ReferenceError, which is the whole point.
 *
 * DELIBERATELY NOT A FULL DOM. jsdom would let a missing import hide behind a stubbed global. The
 * value here comes from binding exactly the real names and nothing more.
 *
 * Usage: node board-render-harness.js <crm-core.js> <portal.js>   →  one line of JSON
 */
const fs = require("fs");

const C = require(process.argv[2]);
const src = fs.readFileSync(process.argv[3], "utf8");

function fn(name) {
  const m = new RegExp("\\n\\s{2,6}(?:async\\s+)?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from portal.js — rewrite this harness, don't delete it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

/** A module-level `const NAME = …` declaration the renderers close over.
 *
 * Bracket-counted, not line-based: COLS is a multi-line array literal, and a single-line regex
 * silently returned "" for it — which surfaced as `ReferenceError: COLS is not defined` from the
 * harness itself and looked exactly like the product bug this file exists to catch. A test whose
 * own scaffolding throws the error it is hunting is worse than no test. */
function topConst(name) {
  const m = new RegExp("\\n\\s*const " + name + " = ").exec(src);
  if (!m) return "";
  let depth = 0;
  for (let j = m.index + m[0].length; j < src.length; j++) {
    const ch = src[j];
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (ch === ";" && depth === 0) return src.slice(m.index, j + 1);
  }
  return "";
}

// EXACTLY what portal.js pulls off crm-core, taken from portal.js's own destructuring lines so this
// cannot drift into binding something the page does not.
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

// The rest of the page's collaborators. Real where the render depends on them; minimal otherwise.
const fu = C.followup;
const avatar = C.avatarHtml || (() => "");
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => "$" + Number(n || 0).toLocaleString();
const pausedUntil = (p) => fu(p).paused_until || null;
const TW = { fmtBizDate: (v) => String(v), fmtBizDay: (v) => String(v), bizYM: (v) => String(v).slice(0, 7) };

const ROWS = [
  { proposal_id: "not-sent-1", project_name: "Cedar Ridge Distribution Center", not_sent: true,
    drafted_at: "2026-08-09T12:00:00Z", estimator_email: "kyle@wetreadwell.com" },
  { proposal_id: "sent-1", project_name: "Maple Street Warehouse", proposal_status: "sent",
    sent_at: "2026-08-08T12:00:00Z", assigned_estimator: "kyle@wetreadwell.com",
    recipients: ["a@x.com", "b@x.com"], viewed_by: ["a@x.com"], approved_total: 41250.0 },
  { proposal_id: "viewed-1", project_name: "Fairview Clinic", proposal_status: "viewed",
    sent_at: "2026-08-05T12:00:00Z", last_viewed_at: "2026-08-09T12:00:00Z",
    assigned_estimator: "will@wetreadwell.com", unread: 2 },
  { proposal_id: "approved-1", project_name: "Westport Retail Center", proposal_status: "approved",
    approved_at: "2026-08-07T12:00:00Z", deposit_status: "pending", deposit_required: true,
    assigned_estimator: "kyle@wetreadwell.com", approved_total: 88000.0 },
  { proposal_id: "submitted-1", project_name: "Northgate Plaza", proposal_status: "approved",
    deposit_status: "submitted", deposit_submitted_at: "2026-08-10T12:00:00Z" },
  { proposal_id: "received-1", project_name: "Riverside Depot", proposal_status: "approved",
    deposit_status: "received", deposit_received_at: "2026-08-10T12:00:00Z",
    contacts_status: "received", contacts_received_at: "2026-08-10T13:00:00Z" },
  { proposal_id: "paused-1", project_name: "Hillcrest Annex", proposal_status: "viewed",
    followup_state: { enrolled: true, enabled: true, paused_until: "2026-12-01" } },
  { proposal_id: "autooff-1", project_name: "Lakeside Garage", proposal_status: "sent",
    followup_state: { enrolled: true, enabled: false } },
  { proposal_id: "test-1", project_name: "Will 8/10 Test", proposal_status: "sent", is_test: true },
  { proposal_id: "lost-1", project_name: "Brookfield Site", proposal_status: "closed_lost",
    followup_state: { closed_lost_reason: "price", closed_at: "2026-08-01T12:00:00Z" } },
  { proposal_id: "lost-2", project_name: "Old Mill Retrofit", proposal_status: "closed_lost" },
  { proposal_id: "lost-3", project_name: "zz scratch", proposal_status: "closed_lost", is_test: true,
    followup_state: { closed_lost_reason: "aliens" } },
  // Deliberately threadbare: a row with nothing but an id, to catch a template that assumes a field.
  { proposal_id: "bare-1" },
];

let TAB = "active";
let VIEW = "board";
let ALL = ROWS;

const LIFT = ["boardPool", "groupByReason", "kanbanHtml", "tableHtml", "cardActions",
              "recipientLine", "chipsHtml", "cardRow"];
const bodies = [];
const absent = [];
for (const n of LIFT) {
  try { bodies.push(fn(n)); } catch (e) { absent.push(n); }
}

const CONSTS = ["LOST_COLS", "COLS"].map(topConst).filter(Boolean).join("\n");

const make = new Function(
  ...NAMES, "C", "fu", "avatar", "esc", "money", "pausedUntil", "TW", "getTAB", "getVIEW", "getALL",
  `"use strict";
   // The page's module-level view state, declared here for the same reason portal.js declares it
   // there: the renderers read it directly. SORTFIELD/SORTDIR drive the table's sort arrows.
   let TAB, VIEW, ALL;
   let SORTFIELD = "activity", SORTDIR = "desc";
   ${CONSTS}
   ${bodies.join("\n")}
   return function render(tab, view, rows) {
     TAB = tab; VIEW = view; ALL = rows;
     const pool = boardPool();
     const items = pool;
     return { pool: pool.length,
              html: view === "table" ? tableHtml(items) : kanbanHtml(items) };
   };`);

const render = make(...VALUES, C, fu, avatar, esc, money, pausedUntil, TW,
                    () => TAB, () => VIEW, () => ALL);

const out = { imported: NAMES, absent: absent, results: {}, errors: {} };
for (const tab of ["active", "test", "lost"]) {
  for (const view of ["board", "table"]) {
    const key = tab + "/" + view;
    try {
      const r = render(tab, view, ROWS);
      out.results[key] = {
        pool: r.pool,
        chars: r.html.length,
        columns: (r.html.match(/class="col/g) || []).length,
        cards: (r.html.match(/class="deal"/g) || []).length,
        rows: (r.html.match(/<tr/g) || []).length,
        newButton: r.html.includes("data-new-proposal"),
        filesButton: r.html.includes("data-files="),
        testChip: r.html.includes("chip-test"),
        rawToken: /\$\{/.test(r.html),
        undefinedLeak: r.html.includes("undefined"),
      };
    } catch (e) {
      out.errors[key] = e.constructor.name + ": " + e.message;
    }
  }
}
console.log(JSON.stringify(out));
