"use strict";
/* RUN the Won tab: the four pools, the four columns, the four pill counts, and every card.
 *
 * WHY THIS EXISTS. Hanz, 2026-08-20: "I marked Trabon Group project as Won but it's still in the
 * Created but Not Sent bucket." The fix moves a won job off the Active board onto its own tab, and
 * every part of that is a behaviour no source read can check: which pool a row lands in depends on
 * three predicates applied in one order, and the columns depend on fields a synthesised not-sent row
 * does not even carry.
 *
 * It also has to catch the OTHER failure this repo has already shipped once. On 2026-08-12 the board
 * went down on production with `ReferenceError: STAGE_CREATED is not defined` — a new constant used
 * inside kanbanHtml that portal.js never imported — while every test was green, because every test
 * asserted the source TEXT of the renderer and none of them ran it. This file adds a whole new column
 * vocabulary to that same function, so it renders all four tabs in both views and reports the throw.
 *
 * WHAT IS REAL AND WHAT IS STUBBED. Real: crm-core (required), and portal.js's own boardPool,
 * kanbanHtml, tableHtml, chipsHtml, cardActions, recipientLine, groupByReason, lostCount, syncTabs
 * and wonControlHtml, lifted out of the IIFE by name, with ONLY the names the page itself binds in
 * scope — so anything portal.js uses without importing is an immediate ReferenceError, which is the
 * point. esc/money/avatar/fu/pausedUntil are lifted from portal.js too rather than reimplemented: a
 * reimplemented esc would prove the harness escapes, not that the page does.
 *
 * Stubbed: `$` and the tab strip's elements, because that IS the DOM boundary — syncTabs writes the
 * counts into it. Deliberately not jsdom, for the same reason the sibling harnesses aren't: a stubbed
 * tree lets a missing import hide behind a global.
 *
 * THE PILL SET COMES OUT OF portal.html, not out of a list typed here, so "TABS grew a tab the markup
 * has no button for" fails instead of passing quietly.
 *
 * Usage: node won-tab-harness.js <crm-core.js> <portal.js> <portal.html>   →  one line of JSON
 */
const fs = require("fs");

const C = require(process.argv[2]);
const src = fs.readFileSync(process.argv[3], "utf8");
const html = fs.readFileSync(process.argv[4], "utf8");

/** The full `function name(...) {...}` text, brace-counted so a template literal in the body
 *  cannot truncate it. */
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

/** A module-level `const NAME = …;`, bracket-counted to its own semicolon — several of these are
 *  multi-line array or arrow literals, and a line-based read silently returned "" for them, which
 *  surfaces as the very ReferenceError this file hunts, thrown by the harness itself. */
function decl(name, optional) {
  const m = new RegExp("\\n\\s*const " + name + " = ").exec(src);
  if (!m) {
    if (optional) return "";
    throw new Error("const " + name + " is gone from portal.js — rewrite this harness");
  }
  let depth = 0;
  for (let j = m.index + m[0].length; j < src.length; j++) {
    const ch = src[j];
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (ch === ";" && depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unterminated declaration reading " + name);
}

// EXACTLY what portal.js pulls off crm-core, read from its own destructuring lines so this cannot
// drift into binding something the page does not have.
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

// The tabs the MARKUP ships, in markup order. syncTabs is driven through these, so a tab in TABS with
// no button (or a button with no tab) shows up as a missing count rather than as nothing at all.
const PILLS = Array.from(html.matchAll(/data-tab="([a-z]+)"/g)).map((m) => m[1]);
if (!PILLS.length) throw new Error("portal.html has no [data-tab] pills — rewrite this harness");

// ── the tab strip, stubbed ───────────────────────────────────────────────────
// The only DOM syncTabs touches: one wrapper, one button per pill, one .n span inside each. The
// counts and the pressed state are read back out of it exactly as the page writes them.
function makeTabs() {
  const counts = {};
  const pressed = {};
  const buttons = PILLS.map((tab) => ({
    dataset: { tab: tab },
    setAttribute(k, v) { if (k === "aria-pressed") pressed[tab] = v; },
    classList: { toggle() {} },
    querySelector(sel) {
      if (sel !== ".n") return null;
      return { set textContent(v) { counts[tab] = v; }, get textContent() { return counts[tab]; } };
    },
  }));
  return {
    counts: counts,
    pressed: pressed,
    wrap: { querySelectorAll: (sel) => (sel === "[data-tab]" ? buttons : []) },
  };
}

const TW = {
  fmtBizDate: (v) => String(v || ""),
  fmtBizDay: (v) => String(v || ""),
  bizYM: (v) => String(v || "").slice(0, 7),
  bizToday: () => "2026-08-20",
};

const LIFT = ["boardPool", "groupByReason", "lostCount", "syncTabs", "kanbanHtml", "tableHtml",
              "cardActions", "recipientLine", "chipsHtml", "wonControlHtml"];

const make = new Function(
  ...NAMES, "C", "TW", "getDollar",
  `"use strict";
   // The page's module-level view state, declared here for the same reason portal.js declares it
   // there: the renderers read it directly, and SORTFIELD/SORTDIR drive the table's sort arrows.
   let TAB, VIEW, ALL;
   let SORTFIELD = "activity", SORTDIR = "desc";
   const $ = (id) => getDollar(id);
   ${decl("esc")}
   ${decl("money")}
   ${decl("fu")}
   ${decl("avatar")}
   ${decl("pausedUntil")}
   ${decl("LOST_COLS")}
   ${decl("COLS")}
   ${LIFT.map(fn).join("\n")}
   return {
     render(tab, view, rows) {
       TAB = tab; VIEW = view; ALL = rows;
       const pool = boardPool();
       return { pool: pool.map((p) => p.proposal_id),
                html: view === "table" ? tableHtml(pool) : kanbanHtml(pool) };
     },
     // The pool and what is DRAWN, deliberately allowed to differ, which is the one thing render()
     // above cannot express: visible() hands kanbanHtml a filtered subset of boardPool(), so the
     // empty state's "does the unfiltered tab have anything on it" branch is only reachable when
     // those two disagree. Passing the ids to keep rather than a predicate keeps the toolbar's
     // filters out of it — WHICH filter emptied the board is not what that branch asks.
     renderFiltered(tab, view, rows, keepIds) {
       TAB = tab; VIEW = view; ALL = rows;
       const pool = boardPool();
       const items = pool.filter((p) => keepIds.indexOf(p.proposal_id) >= 0);
       return { pool: pool.map((p) => p.proposal_id), shown: items.map((p) => p.proposal_id),
                html: view === "table" ? tableHtml(items) : kanbanHtml(items) };
     },
     pills(tab, rows) { TAB = tab; ALL = rows; syncTabs(); },
     wonControl(row) { return wonControlHtml(row); },
   };`);

let TABS_EL = makeTabs();
const scope = make(...VALUES, C, TW, (id) => (id === "crm-tabs" ? TABS_EL.wrap : null));

/** Column name → the card ids under it, out of the RENDERED board. Reading the html rather than
 *  re-grouping in the harness is the whole point: it proves the cards reached the columns, not that
 *  a grouping function agrees with itself. */
function columnsOf(board) {
  const out = {};
  const order = [];
  for (const block of board.split('<div class="col').slice(1)) {
    const name = /<h2>([^<]*)</.exec(block);
    if (!name) continue;
    const col = name[1];
    order.push(col);
    out[col] = Array.from(block.matchAll(/data-id="([^"]+)"/g)).map((m) => m[1]);
  }
  return { cols: order, by: out };
}

// ── the fixtures ─────────────────────────────────────────────────────────────
// Shaped as the two producers really shape them: a portal row carries proposal_status / deposit_* /
// contacts_status, and a synthesised "Created but not sent" row carries not_sent, bid_total,
// drafted_at, estimator_email and won_at and NOTHING else (api_portal_pipeline in main.py).
const ROWS = [
  // THE REPORTED BUG. Marked won by hand on a bid nobody has sent. It has no deposit or contacts
  // fields at all, so any column rule that reads them first files it under an invoice that does not
  // exist.
  { proposal_id: "won-unsent", project_name: "Trabon Group", not_sent: true, won_at: "2026-08-19T15:00:00Z",
    bid_total: 88000.0, drafted_at: "2026-08-09T12:00:00Z", estimator_email: "kyle@wetreadwell.com" },
  // The same card unmarked: still Active, still in Created but not sent. The control case for the bug.
  { proposal_id: "unsent-plain", project_name: "Cedar Ridge Distribution Center", not_sent: true,
    bid_total: 41250.0, drafted_at: "2026-08-10T12:00:00Z", estimator_email: "kyle@wetreadwell.com" },
  // MARKED WON ON THE PHONE, ON A PROPOSAL THAT IS OUT. Sent, not approved, no deposit, no invoice —
  // neither half of the derived rule is true of it, which is the whole point of drafts.set_won ("days
  // before the customer clicks Approve"). lost-tab-harness.js fixtures the same shape as `won-marked`.
  // It filed under "Deposit outstanding" for a few hours on 2026-08-20, which claimed money was owed
  // on a proposal nobody has invoiced.
  { proposal_id: "won-marked-sent", project_name: "Elmwood Cold Storage", proposal_status: "sent",
    won_at: "2026-08-19T15:00:00Z", sent_at: "2026-08-15T12:00:00Z", bid_total: 54000.0,
    assigned_estimator: "kyle@wetreadwell.com" },
  // Won by hand with the money genuinely out. The row the old reasoning was protecting: it must stay
  // visible as outstanding work, which is what the Won tab's own column is for.
  { proposal_id: "won-deposit-out", project_name: "Northgate Plaza", proposal_status: "approved",
    won_at: "2026-08-18T15:00:00Z", deposit_required: true, deposit_status: "pending",
    deposit_requested_at: "2026-08-18T16:00:00Z", approved_total: 61000.0,
    assigned_estimator: "will@wetreadwell.com" },
  // Marked won on the phone on a job that collects NO deposit, still unapproved. depositSatisfied is
  // TRUE of it (nothing to collect, nothing invoiced) while the customer has agreed to nothing, so
  // this is the row that separates "gate the columns on approval" from "gate them on the money": a
  // money-only rule files it under "Contacts outstanding", which asks the customer for contacts the
  // portal will not collect until they approve.
  { proposal_id: "won-marked-nodeposit", project_name: "Barton Trade Center", proposal_status: "sent",
    won_at: "2026-08-19T15:00:00Z", sent_at: "2026-08-13T12:00:00Z", deposit_required: false,
    bid_total: 33000.0 },
  // Deposit in, contacts not. Derived won, nobody marked it.
  { proposal_id: "won-contacts-out", project_name: "Riverside Logistics", proposal_status: "approved",
    deposit_status: "received", deposit_received_at: "2026-08-14T12:00:00Z",
    contacts_status: "pending", approved_total: 22000.0 },
  // A job that collects no deposit and was never invoiced for one: satisfied, so the next question is
  // the contacts.
  { proposal_id: "won-nodeposit", project_name: "Brookfield GC Tenant Fit-out", proposal_status: "sent",
    approved_at: "2026-08-01T12:00:00Z", deposit_required: false },
  // Nothing outstanding.
  { proposal_id: "won-complete", project_name: "Westport Retail Center", proposal_status: "approved",
    deposit_status: "received", contacts_status: "received",
    deposit_received_at: "2026-08-12T12:00:00Z", contacts_received_at: "2026-08-13T12:00:00Z" },
  // Approved with the deposit still out and NOBODY has marked it won. The most worth-chasing row on
  // the board: it has to stay on Active, or the strictness of isWon's derived half is decoration.
  { proposal_id: "approved-unpaid", project_name: "Halstead Medical", proposal_status: "approved",
    deposit_status: "pending", deposit_required: true, deposit_requested_at: "2026-08-15T12:00:00Z" },
  { proposal_id: "sent-plain", project_name: "Maple Street Warehouse", proposal_status: "sent",
    sent_at: "2026-08-08T12:00:00Z", recipients: ["a@x.com", "b@x.com"], viewed_by: ["a@x.com"] },
  // ── the three Active columns an adversarial review called structurally empty ───────────────────
  // It reasoned that "Deposit received" and "Contact info" both imply depositSatisfied, which with
  // approval means isWon, which means the Won tab. The missing premise is APPROVAL, and the portal
  // takes it back: db.reset_for_revision drops proposal_status to 'sent' and NULLS approved_at when a
  // new revision is published, and deliberately leaves the deposit and contacts columns alone —
  // "Money that has already been invoiced or paid is a fact about the project, not about which
  // revision is current". So a job whose deposit is in, and whose contacts are in, can be waiting on
  // an approval again. That card is live work, it is not won, and losing it off the board would lose
  // the most valuable row on it: money already collected against a price nobody has agreed to yet.
  { proposal_id: "revised-deposit-in", project_name: "Sedgwick Distribution", proposal_status: "sent",
    sent_at: "2026-08-16T12:00:00Z", current_revision_no: 2, deposit_required: true,
    deposit_status: "received", deposit_received_at: "2026-08-05T12:00:00Z",
    contacts_status: "pending", bid_total: 96500.0, assigned_estimator: "will@wetreadwell.com" },
  { proposal_id: "revised-contacts-in", project_name: "Olathe Pointe Phase 2", proposal_status: "sent",
    sent_at: "2026-08-16T12:00:00Z", current_revision_no: 3, deposit_required: true,
    deposit_status: "received", deposit_received_at: "2026-08-04T12:00:00Z",
    contacts_status: "received", contacts_received_at: "2026-08-06T12:00:00Z", bid_total: 130000.0 },
  // Money in and unconfirmed: the one column kanbanHtml flags for attention. Reachable with nothing
  // exotic at all — approved, the deposit submitted, nobody has confirmed it — and empty here only
  // because the fixture set had no such row, which is what made the review's third claim look like
  // the other two.
  { proposal_id: "deposit-submitted", project_name: "Gardner Freight Terminal",
    proposal_status: "approved", approved_at: "2026-08-11T12:00:00Z", deposit_required: true,
    deposit_status: "submitted", deposit_submitted_at: "2026-08-18T12:00:00Z",
    approved_total: 47500.0 },
  { proposal_id: "viewed-plain", project_name: "Fairview Clinic", proposal_status: "viewed",
    last_viewed_at: "2026-08-17T12:00:00Z", unread: 2 },
  // Scratch work that was won. Stays under Test: a test project does not become real work by being
  // marked won, and Test is the one tab its owner looks under.
  { proposal_id: "won-test", project_name: "Will 8/20 Test", is_test: true, proposal_status: "approved",
    deposit_status: "received", contacts_status: "received", won_at: "2026-08-19T15:00:00Z" },
  { proposal_id: "test-plain", project_name: "zz scratch", is_test: true, proposal_status: "sent" },
  // Won and then cancelled. Lost only, in both directions of the mark.
  { proposal_id: "lost-after-won", project_name: "Kellogg Self Storage", proposal_status: "closed_lost",
    approved_at: "2026-08-01T12:00:00Z", deposit_status: "received",
    followup_state: { closed_lost_reason: "canceled" } },
  { proposal_id: "lost-after-marked-won", project_name: "Grandview Terminal", proposal_status: "closed_lost",
    won_at: "2026-08-19T15:00:00Z", followup_state: { closed_lost_reason: "price" } },
  { proposal_id: "lost-plain", project_name: "Old Mill Retrofit", proposal_status: "closed_lost" },
  // Deliberately threadbare: an id and nothing else, to catch a template that assumes a field.
  { proposal_id: "bare" },
];

const out = { imported: NAMES, pills: PILLS, everyId: ROWS.map((p) => p.proposal_id),
              pools: {}, boards: {}, tables: {}, errors: {}, wonCols: C.WON_COLS };

for (const tab of PILLS) {
  for (const view of ["board", "table"]) {
    try {
      const r = scope.render(tab, view, ROWS);
      if (view === "board") {
        out.pools[tab] = r.pool;
        const cols = columnsOf(r.html);
        out.boards[tab] = {
          cols: cols.cols,
          by: cols.by,
          cards: (r.html.match(/class="deal"/g) || []).length,
          newButton: r.html.includes("data-new-proposal"),
          rawToken: /\$\{/.test(r.html),
          undefinedLeak: r.html.includes("undefined"),
          html: r.html,
        };
      } else {
        out.tables[tab] = { rows: (r.html.match(/<tr/g) || []).length,
                            rawToken: /\$\{/.test(r.html),
                            undefinedLeak: r.html.includes("undefined") };
      }
    } catch (e) {
      out.errors[tab + "/" + view] = e.constructor.name + ": " + e.message;
    }
  }
}

// A Won tab with nothing on it: four empty columns is a page that reads as broken, so it has to say
// which kind of empty it is, and there are TWO kinds. Both branches are rendered here, because the
// difference between them is one ternary reading boardPool() — and a test that reads that call out of
// the source cannot tell whether the branch it names is ever taken.
//
//   emptyWon          nothing has been won at all: news, and nothing to clear.
//   emptyWonFiltered  won jobs exist and the toolbar has hidden every one: clear the filter. The pool
//                     is the full set and the drawn list is empty, which only renderFiltered can do.
try {
  out.emptyWon = scope.render("won", "board",
                              ROWS.filter((p) => !out.pools.won.includes(p.proposal_id))).html;
} catch (e) {
  out.errors["emptyWon"] = e.constructor.name + ": " + e.message;
}
try {
  const r = scope.renderFiltered("won", "board", ROWS, []);
  out.emptyWonFiltered = { html: r.html, pool: r.pool.length, shown: r.shown.length };
} catch (e) {
  out.errors["emptyWonFiltered"] = e.constructor.name + ": " + e.message;
}

// The pills, WRITTEN BY syncTabs into the stub, once per tab so the pressed state is exercised too.
TABS_EL = makeTabs();
try {
  scope.pills("won", ROWS);
  out.counts = Object.assign({}, TABS_EL.counts);
  out.pressed = Object.assign({}, TABS_EL.pressed);
} catch (e) {
  out.errors["syncTabs"] = e.constructor.name + ": " + e.message;
}

// The drawer's two outcome controls on the card Hanz marked: rendered, not grepped. wonControlHtml is
// pure, so it runs here; the Mark closed lost half lives in renderNotSent and is exercised by
// test_drawer_renders.py, which stubs the DOM the panel needs.
// ── the whole routing table, executed ────────────────────────────────────────
// The board fixtures above only cover the shapes that happen to be in ROWS. These are the states a
// won job can distinguishably be in, run through the real wonColumn, so the table anybody reasons
// from is GENERATED rather than argued. Every one of these is a shape a producer really makes:
// not_sent comes off api_portal_pipeline, the two `won_at` sent rows are drafts.set_won's whole
// purpose, and the approved ones are the portal's own deposit sequence.
const W = "2026-08-19T15:00:00Z";
const ROUTING = {
  "not_sent + won_at": { not_sent: true, won_at: W },
  "sent + won_at": { proposal_status: "sent", won_at: W },
  "sent + won_at + deposit_required false": { proposal_status: "sent", won_at: W,
                                             deposit_required: false },
  "viewed + won_at": { proposal_status: "viewed", won_at: W },
  "approved + deposit requested": { proposal_status: "approved", deposit_required: true,
                                    deposit_status: "pending",
                                    deposit_requested_at: "2026-08-18T16:00:00Z" },
  "approved + deposit_required false": { proposal_status: "approved", deposit_required: false },
  "deposit received + contacts missing": { proposal_status: "approved", deposit_status: "received",
                                           contacts_status: "pending" },
  "everything settled": { proposal_status: "approved", deposit_status: "received",
                          contacts_status: "received" },
};
out.wonRouting = {};
out.wonRoutingIsWon = {};
for (const [name, row] of Object.entries(ROUTING)) {
  out.wonRoutingIsWon[name] = C.isWon(row);
  out.wonRouting[name] = C.wonColumn(row);
}

// BY ID, not by index: this list read [ROWS[0], ROWS[1], ROWS[11]] and inserting a fixture above
// silently repointed the third one at a different project, which is a green test about the wrong row.
out.wonControl = {};
// `won-complete` is the DERIVED win: approved, deposit in, contacts in, and nobody marked it. It
// is the one state with nothing to undo, and since 2026-08-20 the panel has to say so out loud
// rather than leaving a gap where every other state has a control.
const WON_CONTROL_ROWS = ["won-unsent", "unsent-plain", "won-marked-sent", "lost-after-won",
                          "won-complete"];
for (const row of WON_CONTROL_ROWS.map((id) => {
  const hit = ROWS.find((p) => p.proposal_id === id);
  if (!hit) throw new Error("no fixture called " + id + " — rewrite this harness, don't delete it");
  return hit;
})) {
  try {
    out.wonControl[row.proposal_id] = scope.wonControl(row);
  } catch (e) {
    out.errors["wonControl/" + row.proposal_id] = e.constructor.name + ": " + e.message;
  }
}

console.log(JSON.stringify(out));
