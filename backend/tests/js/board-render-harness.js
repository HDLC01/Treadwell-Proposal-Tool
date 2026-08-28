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
 * THE TAB LIST IS NOT TYPED HERE. It used to be `["active", "test", "lost"]`, and on 2026-08-20 the
 * product grew a fourth tab (Won) that this file went on not rendering while staying green — the same
 * failure mode as the incident above, one level up: the guard existed and simply did not cover the new
 * code. It now comes out of portal.js's own `const TABS`, cross-checked against the [data-tab] pills
 * in portal.html, so the NEXT tab is rendered the day it is declared and a tab declared without a
 * button (or a button with no tab) fails here.
 *
 * Usage: node board-render-harness.js <crm-core.js> <portal.js> <portal.html>   →  one line of JSON
 */
const fs = require("fs");

const C = require(process.argv[2]);
const src = fs.readFileSync(process.argv[3], "utf8");
const html = fs.readFileSync(process.argv[4], "utf8");

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

/** The VALUE of a module-level `const NAME = <literal>;`, evaluated. Used for TABS: this harness has
 *  to render every tab the product declares, and the only way to know that list is to read the
 *  product's own declaration. A list typed here is what let the Won tab ship unrendered. */
function topConstValue(name) {
  const text = topConst(name);
  if (!text) throw new Error("const " + name + " is gone from portal.js — rewrite this harness");
  const lit = text.slice(text.indexOf("=") + 1).replace(/;\s*$/, "");
  return new Function('"use strict"; return (' + lit + ");")();
}

// The tabs the PAGE declares, in the page's order, and the pills the MARKUP ships, in markup order.
// Asserted equal on the Python side: a tab with no button is unreachable, a button with no tab blanks
// the board, and neither is visible from either file alone.
const TABS = topConstValue("TABS");
// `[a-z_]+`, not `[a-z]+`: the tab ids gained an underscore on 2026-08-28 (`handed_off`) and a
// letters-only class silently dropped that pill, which reads here as "portal.html is missing a
// button" — a false product bug that costs more to chase than the character costs to type.
const PILLS = Array.from(html.matchAll(/data-tab="([a-z_]+)"/g)).map((m) => m[1]);
if (!PILLS.length) throw new Error("portal.html has no [data-tab] pills — rewrite this harness");

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
  // ── the Won tab, which has been its own tab since 2026-08-20 ────────────────
  // Won because THE DEPOSIT ARRIVED — nobody marked it, isWon derives it from approved + the money
  // settled. This row used to sit in the live board's "Contact info" column and now leaves the Active
  // board altogether, which is the behaviour change of 2026-08-20.
  { proposal_id: "received-1", project_name: "Riverside Depot", proposal_status: "approved",
    deposit_status: "received", deposit_received_at: "2026-08-10T12:00:00Z",
    contacts_status: "received", contacts_received_at: "2026-08-10T13:00:00Z" },
  // Won BY HAND on a bid nobody has sent: the card Hanz reported ("I marked Trabon Group project as
  // Won but it's still in the Created but Not Sent bucket"). A synthesised not-sent row carries no
  // deposit or contacts fields AT ALL, so it is also the row that catches a Won column rule that
  // reads them before asking whether the customer has approved.
  { proposal_id: "won-hand-1", project_name: "Trabon Group", not_sent: true,
    won_at: "2026-08-19T15:00:00Z", bid_total: 88000.0, drafted_at: "2026-08-09T12:00:00Z",
    estimator_email: "kyle@wetreadwell.com" },
  // Won by hand with the money genuinely still out. The row the "keep won cards on the live board"
  // argument was protecting: the work on it stays visible, on the Won tab's own outstanding column
  // rather than in the pipeline. Two won rows in two different columns, so a Won board with one
  // column collapsed onto another does not render identically to a correct one.
  { proposal_id: "won-hand-2", project_name: "Northgate Commerce Park", proposal_status: "approved",
    approved_at: "2026-08-16T12:00:00Z", won_at: "2026-08-18T15:00:00Z", deposit_required: true,
    deposit_status: "pending", deposit_requested_at: "2026-08-17T12:00:00Z",
    approved_total: 61000.0, assigned_estimator: "will@wetreadwell.com" },
  // ── the Handed Off tab, which since 2026-08-28 is what winning no longer does ───
  // Handed off with everything settled: the ordinary way a job leaves the board.
  { proposal_id: "handoff-1", project_name: "Galloway Logistics", proposal_status: "approved",
    approved_at: "2026-08-11T12:00:00Z", deposit_status: "received",
    deposit_received_at: "2026-08-12T12:00:00Z", contacts_status: "received",
    contacts_received_at: "2026-08-12T13:00:00Z", won_at: "2026-08-12T14:00:00Z",
    handed_off_at: "2026-08-13T09:00:00Z", assigned_estimator: "kyle@wetreadwell.com",
    approved_total: 47000.0 },
  // Handed off from an UNSENT bid — won on the phone, priced, passed straight to operations. It
  // carries no portal fields at all, so it is the row that catches a Handed Off rule reading them
  // first, and it proves the tab is not merely the far end of the pipeline.
  { proposal_id: "handoff-2", project_name: "Sparrow Point Annex", not_sent: true,
    won_at: "2026-08-14T15:00:00Z", handed_off_at: "2026-08-15T09:00:00Z",
    bid_total: 32500.0, drafted_at: "2026-08-13T12:00:00Z",
    estimator_email: "will@wetreadwell.com" },
  { proposal_id: "paused-1", project_name: "Hillcrest Annex", proposal_status: "viewed",
    followup_state: { enrolled: true, enabled: true, paused_until: "2026-12-01" } },
  { proposal_id: "autooff-1", project_name: "Lakeside Garage", proposal_status: "sent",
    followup_state: { enrolled: true, enabled: false } },
  { proposal_id: "test-1", project_name: "Will 8/10 Test", proposal_status: "sent", is_test: true },
  // Scratch work that was WON. It stays under Test — a test project does not become real work by
  // being marked won, and Test is the one tab its owner looks under — so the Won chip is the only
  // thing on the card that says so. Which is why the chip has to keep drawing there.
  { proposal_id: "won-test-1", project_name: "Will 8/20 Test", is_test: true,
    won_at: "2026-08-19T15:00:00Z", proposal_status: "sent", sent_at: "2026-08-14T12:00:00Z" },
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
     return { pool: pool.length, poolIds: pool.map((p) => p.proposal_id),
              html: view === "table" ? tableHtml(items) : kanbanHtml(items) };
   };`);

const render = make(...VALUES, C, fu, avatar, esc, money, pausedUntil, TW,
                    () => TAB, () => VIEW, () => ALL);

/** Column heading → the card ids drawn under it, read back OUT of the rendered board. Reading the
 *  html rather than re-grouping in the harness is the point: it proves the cards reached the columns,
 *  not that a grouping function agrees with itself.
 *
 *  Splitting on `<div class="col` is safe against the + New button, which is `class="col-add"` on a
 *  <button>, not a <div>; and `[^<]*` stops the heading capture at the `<span>` holding the count. */
function columnsOf(board) {
  const by = {};
  const order = [];
  for (const block of board.split('<div class="col').slice(1)) {
    const m = /<h2>([^<]*)</.exec(block);
    if (!m) continue;
    order.push(m[1]);
    by[m[1]] = Array.from(block.matchAll(/data-id="([^"]+)"/g)).map((x) => x[1]);
  }
  return { order: order, by: by };
}

const out = { imported: NAMES, absent: absent, tabs: TABS, pills: PILLS,
              handoffCols: C.HANDOFF_COLS, stages: C.STAGES,
              // The Lost tab's own vocabulary, read the way portal.js builds it (LOST_COLS):
              // every label in the derived LOST_REASON map, then the catch-all. Exported so the
              // Lost-tab test can assert column NAMES rather than a bare count, which is the only
              // way to tell one column set from another.
              lostCols: Object.keys(C.LOST_REASON).map((k) => C.LOST_REASON[k])
                              .concat(["Not recorded"]),
              everyId: ROWS.map((p) => p.proposal_id), results: {}, errors: {} };
for (const tab of TABS) {
  for (const view of ["board", "table"]) {
    const key = tab + "/" + view;
    try {
      const r = render(tab, view, ROWS);
      const cols = view === "board" ? columnsOf(r.html) : { order: [], by: {} };
      out.results[key] = {
        pool: r.pool,
        poolIds: r.poolIds,
        chars: r.html.length,
        // NOTE ON `columns`: this counts the string `class="col`, which the + New BUTTON
        // (`class="col-add"`) also matches — so on a tab that draws that button the number is one
        // higher than the column count. `colNames`/`byCol` come from the <h2> headings and are the
        // honest column set; which column vocabulary a tab drew is a fact about the html, and a bare
        // count cannot tell two 4-column vocabularies apart.
        columns: (r.html.match(/class="col/g) || []).length,
        colNames: cols.order,
        byCol: cols.by,
        cards: (r.html.match(/class="deal"/g) || []).length,
        rows: (r.html.match(/<tr/g) || []).length,
        newButton: r.html.includes("data-new-proposal"),
        // The card's two outcome buttons, which replaced Files and Info sheet on 2026-08-20.
        // Both names are reported so a board that grew the old pair back is visible here too.
        wonButton: r.html.includes("data-won="),
        lostButton: r.html.includes("data-lost="),
        filesButton: r.html.includes("data-files="),
        testChip: r.html.includes("chip-test"),
        wonChip: r.html.includes("chip-won"),
        rawToken: /\$\{/.test(r.html),
        undefinedLeak: r.html.includes("undefined"),
      };
    } catch (e) {
      out.errors[key] = e.constructor.name + ": " + e.message;
    }
  }
}
console.log(JSON.stringify(out));
