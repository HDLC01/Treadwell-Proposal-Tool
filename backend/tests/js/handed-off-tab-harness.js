"use strict";
/* RUN the board's four tabs: the four pools, every column, the four pill counts, and every card.
 *
 * WHY THIS EXISTS, AND WHY THE FILE IS NAMED FOR A TAB THAT ONCE SAID "WON". Hanz, 2026-08-20:
 * "I marked Trabon Group project as Won but it's still in the Created but Not Sent bucket." The fix
 * that day moved a won job off the Active board onto a Won tab of its own — and on 2026-08-28 he
 * reversed the second half of it: "the mark as won button would move the project the Won/Approved
 * not into a separate pipeline", "the Won category would be relabeled as 'Handed Off'".
 *
 * So winning is a COLUMN on the live board now, and what takes a card off it is a human pressing
 * Hand it off. Both halves are behaviour no source read can check: which pool a row lands in depends
 * on three predicates applied in one order, which column depends on seven more applied in another,
 * and a synthesised not-sent row does not carry most of the fields either rule asks about.
 *
 * It also has to catch the OTHER failure this repo has already shipped once. On 2026-08-12 the board
 * went down on production with `ReferenceError: STAGE_CREATED is not defined` — a new constant used
 * inside kanbanHtml that portal.js never imported — while every test was green, because every test
 * asserted the source TEXT of the renderer and none of them ran it. This change swaps a whole column
 * vocabulary inside that same function, so it renders all four tabs in both views and reports the
 * throw.
 *
 * WHAT IS REAL AND WHAT IS STUBBED. Real: crm-core (required), and portal.js's own boardPool,
 * kanbanHtml, tableHtml, chipsHtml, cardActions, recipientLine, groupByReason, lostCount, syncTabs
 * and wonControlHtml, lifted out of the IIFE by name, with ONLY the names the page itself binds in
 * scope — so anything portal.js uses without importing is an immediate ReferenceError, which is the
 * point. esc/money/avatar/fu/pausedUntil are lifted from portal.js too rather than reimplemented: a
 * reimplemented esc would prove the harness escapes, not that the page does.
 *
 * Stubbed: `$` and the tab strip's elements, because that IS the DOM boundary — syncTabs writes the
 * counts into it — and `sessionStorage`, so the per-tab view default runs against real storage
 * precedence instead of a grep. Deliberately not jsdom, for the same reason the sibling harnesses
 * aren't: a stubbed tree lets a missing import hide behind a global.
 *
 * THE PILL SET COMES OUT OF portal.html, not out of a list typed here, so "TABS grew a tab the markup
 * has no button for" fails instead of passing quietly.
 *
 * Usage: node handed-off-tab-harness.js <crm-core.js> <portal.js> <portal.html>  →  one line of JSON
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
const PILLS = Array.from(html.matchAll(/data-tab="([a-z_]+)"/g)).map((m) => m[1]);
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

// The session store the per-tab view preference lives in. A plain object rather than a mock with
// assertions: what is being tested is which view a tab OPENS in, not how many times the page reads
// its own storage.
const STORE = {};
const sessionStorage = {
  getItem: (k) => (k in STORE ? STORE[k] : null),
  setItem: (k, v) => { STORE[k] = String(v); },
  removeItem: (k) => { delete STORE[k]; },
};

const TW = {
  fmtBizDate: (v) => String(v || ""),
  fmtBizDay: (v) => String(v || ""),
  bizYM: (v) => String(v || "").slice(0, 7),
  bizToday: () => "2026-08-29",
};

const LIFT = ["boardPool", "groupByReason", "lostCount", "syncTabs", "kanbanHtml", "tableHtml",
              "cardActions", "recipientLine", "chipsHtml", "wonControlHtml"];

const make = new Function(
  ...NAMES, "C", "TW", "getDollar", "sessionStorage",
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
   // The per-tab view preference, lifted rather than reimplemented. Hanz, 2026-08-28: "After the
   // Handed Off Pipeline would just be one list. Default View should be a list." Which view a tab
   // OPENS in is a three-way precedence (stored, valid, default-by-tab) and a source read of the
   // ternary cannot tell you which branch a real stored value takes.
   ${decl("ss")}
   ${decl("viewKey")}
   ${decl("defaultView")}
   ${decl("readView")}
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
     // stored === null means "this rep has never toggled the view on this tab", which is the state
     // every rep is in the first time they open it and the only one the default governs.
     viewFor(tab, stored) {
       if (stored == null) sessionStorage.removeItem(viewKey(tab));
       else sessionStorage.setItem(viewKey(tab), stored);
       return readView(tab);
     },
   };`);

let TABS_EL = makeTabs();
const scope = make(...VALUES, C, TW, (id) => (id === "crm-tabs" ? TABS_EL.wrap : null), sessionStorage);

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
// drafted_at, estimator_email, won_at and handed_off_at and NOTHING else (api_portal_pipeline in
// main.py).
const ROWS = [
  // THE REPORTED BUG. Marked won by hand on a bid nobody has sent. It has no deposit or contacts
  // fields at all, so any column rule that reads them first files it under an invoice that does not
  // exist. Since 2026-08-28 it stays on the ACTIVE board, in Won/Approved.
  { proposal_id: "won-unsent", project_name: "Trabon Group", not_sent: true, won_at: "2026-08-19T15:00:00Z",
    bid_total: 88000.0, drafted_at: "2026-08-09T12:00:00Z", estimator_email: "kyle@wetreadwell.com" },
  // The same card unmarked: still in Created but not sent. The control case for the bug.
  { proposal_id: "unsent-plain", project_name: "Cedar Ridge Distribution Center", not_sent: true,
    bid_total: 41250.0, drafted_at: "2026-08-10T12:00:00Z", estimator_email: "kyle@wetreadwell.com" },
  // MARKED WON ON THE PHONE, ON A PROPOSAL THAT IS OUT. Sent, not approved, no deposit, no invoice —
  // neither half of the derived rule is true of it, which is the whole point of drafts.set_won ("days
  // before the customer clicks Approve"). lost-tab-harness.js fixtures the same shape as `won-marked`.
  { proposal_id: "won-marked-sent", project_name: "Elmwood Cold Storage", proposal_status: "sent",
    won_at: "2026-08-19T15:00:00Z", sent_at: "2026-08-15T12:00:00Z", bid_total: 54000.0,
    assigned_estimator: "kyle@wetreadwell.com" },
  // Won by hand with the money genuinely out. The row the whole reversal was for: it is won AND it
  // still owes a deposit, so it belongs in front of the sales meeting, not on a tab of finished work.
  { proposal_id: "won-deposit-out", project_name: "Northgate Plaza", proposal_status: "approved",
    won_at: "2026-08-18T15:00:00Z", deposit_required: true, deposit_status: "pending",
    deposit_requested_at: "2026-08-18T16:00:00Z", approved_total: 61000.0,
    assigned_estimator: "will@wetreadwell.com" },
  // Marked won on the phone on a job that collects NO deposit, still unapproved. depositSatisfied is
  // TRUE of it (nothing to collect, nothing invoiced) while the customer has agreed to nothing.
  { proposal_id: "won-marked-nodeposit", project_name: "Barton Trade Center", proposal_status: "sent",
    won_at: "2026-08-19T15:00:00Z", sent_at: "2026-08-13T12:00:00Z", deposit_required: false,
    bid_total: 33000.0 },
  // Deposit in, contacts not. Derived won, nobody marked it, nobody has handed it off — so it reads
  // as Deposit received on the live board, which is the column that names the work left on it.
  { proposal_id: "won-contacts-out", project_name: "Riverside Logistics", proposal_status: "approved",
    deposit_status: "received", deposit_received_at: "2026-08-14T12:00:00Z",
    contacts_status: "pending", approved_total: 22000.0 },
  // A job that collects no deposit and was never invoiced for one: satisfied, so the next question is
  // the contacts, and approval puts it in Won/Approved until they arrive.
  { proposal_id: "won-nodeposit", project_name: "Brookfield GC Tenant Fit-out", proposal_status: "sent",
    approved_at: "2026-08-01T12:00:00Z", deposit_required: false },
  // Nothing outstanding and STILL ON THE BOARD, because nobody has pressed Hand it off. This is the
  // card the 2026-08-20 design removed automatically and Hanz asked for back: the numbers being
  // finished is not the same fact as operations having it.
  { proposal_id: "won-complete", project_name: "Westport Retail Center", proposal_status: "approved",
    deposit_status: "received", contacts_status: "received",
    deposit_received_at: "2026-08-12T12:00:00Z", contacts_received_at: "2026-08-13T12:00:00Z" },
  // Approved with the deposit still out and NOBODY has marked it won. Won/Approved is wider than
  // isWon on purpose: the column is "the customer said yes", the button is "we may hand this over".
  { proposal_id: "approved-unpaid", project_name: "Halstead Medical", proposal_status: "approved",
    deposit_status: "pending", deposit_required: true, deposit_requested_at: "2026-08-15T12:00:00Z" },
  { proposal_id: "sent-plain", project_name: "Maple Street Warehouse", proposal_status: "sent",
    sent_at: "2026-08-08T12:00:00Z", recipients: ["a@x.com", "b@x.com"], viewed_by: ["a@x.com"] },
  // ── the two Active columns an adversarial review called structurally empty ─────────────────────
  // It reasoned that "Deposit received" and "Contact info" both imply depositSatisfied, which with
  // approval means isWon, which meant the Won tab. The missing premise is APPROVAL, and the portal
  // takes it back: db.reset_for_revision drops proposal_status to 'sent' and NULLS approved_at when a
  // new revision is published, and deliberately leaves the deposit and contacts columns alone —
  // "Money that has already been invoiced or paid is a fact about the project, not about which
  // revision is current". These rows keep their own reason to exist after the reversal: they are the
  // shapes that reach those columns WITHOUT being won at all.
  { proposal_id: "revised-deposit-in", project_name: "Sedgwick Distribution", proposal_status: "sent",
    sent_at: "2026-08-16T12:00:00Z", current_revision_no: 2, deposit_required: true,
    deposit_status: "received", deposit_received_at: "2026-08-05T12:00:00Z",
    contacts_status: "pending", bid_total: 96500.0, assigned_estimator: "will@wetreadwell.com" },
  { proposal_id: "revised-contacts-in", project_name: "Olathe Pointe Phase 2", proposal_status: "sent",
    sent_at: "2026-08-16T12:00:00Z", current_revision_no: 3, deposit_required: true,
    deposit_status: "received", deposit_received_at: "2026-08-04T12:00:00Z",
    contacts_status: "received", contacts_received_at: "2026-08-06T12:00:00Z", bid_total: 130000.0 },
  // Money in and unconfirmed: the one column kanbanHtml flags for attention.
  { proposal_id: "deposit-submitted", project_name: "Gardner Freight Terminal",
    proposal_status: "approved", approved_at: "2026-08-11T12:00:00Z", deposit_required: true,
    deposit_status: "submitted", deposit_submitted_at: "2026-08-18T12:00:00Z",
    approved_total: 47500.0 },
  { proposal_id: "viewed-plain", project_name: "Fairview Clinic", proposal_status: "viewed",
    last_viewed_at: "2026-08-17T12:00:00Z", unread: 2 },
  // ── handed off: the only thing that takes a card off the live board ───────────────────────────
  // Everything settled AND somebody pressed the button. The card operations owns now.
  { proposal_id: "handoff-complete", project_name: "Lenexa Cold Chain", proposal_status: "approved",
    deposit_status: "received", contacts_status: "received",
    deposit_received_at: "2026-08-12T12:00:00Z", contacts_received_at: "2026-08-13T12:00:00Z",
    handed_off_at: "2026-08-25T14:00:00Z", approved_total: 74000.0,
    assigned_estimator: "will@wetreadwell.com" },
  // HANDED OFF WITH THE CONTACTS STILL OUT, which is reachable because confirmHandoff warns and does
  // not block. It has to land on the tab on the strength of the stamp alone — a routing rule that
  // also asked for contacts would strand this card on a board nobody is still selling from.
  { proposal_id: "handoff-contacts-out", project_name: "Shawnee Mission Bakery",
    proposal_status: "approved", deposit_status: "received", contacts_status: "pending",
    deposit_received_at: "2026-08-15T12:00:00Z", handed_off_at: "2026-08-26T14:00:00Z",
    approved_total: 39000.0 },
  // Never sent, won on the phone, handed straight to operations. Rare and real, and the reason
  // _not_sent_rows carries handed_off_at unconditionally: a synthesised row has no portal field to
  // fall back on, so if the stamp does not ride along the card simply never leaves Active.
  { proposal_id: "handoff-unsent", project_name: "Gardner Sitework", not_sent: true,
    won_at: "2026-08-21T15:00:00Z", handed_off_at: "2026-08-27T14:00:00Z", bid_total: 15500.0,
    drafted_at: "2026-08-20T12:00:00Z", estimator_email: "kyle@wetreadwell.com" },
  // Handed off and THEN closed lost — a job cancelled after operations had it. Lost wins everywhere,
  // because boardPool asks isLost first, and this is the row that proves the new predicate did not
  // jump that queue.
  { proposal_id: "lost-after-handoff", project_name: "Prairie Village Dental",
    proposal_status: "closed_lost", handed_off_at: "2026-08-24T14:00:00Z",
    followup_state: { closed_lost_reason: "canceled" } },
  // Scratch work that was won. Stays under Test: a test project does not become real work by being
  // marked won, and Test is the one tab its owner looks under.
  { proposal_id: "won-test", project_name: "Will 8/20 Test", is_test: true, proposal_status: "approved",
    deposit_status: "received", contacts_status: "received", won_at: "2026-08-19T15:00:00Z" },
  // And scratch work that was handed off. Test beats Handed Off for the same reason it beats Won:
  // somebody's demo must not inflate a number a human reads as finished jobs.
  { proposal_id: "handoff-test", project_name: "Kyle scratch handoff", is_test: true,
    proposal_status: "approved", deposit_status: "received", contacts_status: "received",
    handed_off_at: "2026-08-23T14:00:00Z" },
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
              pools: {}, boards: {}, tables: {}, errors: {}, handoffCols: C.HANDOFF_COLS,
              stages: C.STAGES, stageWon: C.STAGE_WON };

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

// A Handed Off tab with nothing on it. One empty column reads worse than four did — a lone heading
// over nothing looks like a board that failed to load — so it has to say which kind of empty it is,
// and there are TWO kinds. Both branches are rendered here, because the difference between them is
// one ternary reading boardPool(), and a test that reads that call out of the source cannot tell
// whether the branch it names is ever taken.
//
//   emptyHandoff          nothing handed off at all: news, and nothing to clear.
//   emptyHandoffFiltered  hand-offs exist and the toolbar has hidden every one: clear the filter.
//                         The pool is the full set and the drawn list is empty, which only
//                         renderFiltered can do.
try {
  out.emptyHandoff = scope.render("handed_off", "board",
                                  ROWS.filter((p) => !out.pools.handed_off.includes(p.proposal_id))).html;
} catch (e) {
  out.errors["emptyHandoff"] = e.constructor.name + ": " + e.message;
}
try {
  const r = scope.renderFiltered("handed_off", "board", ROWS, []);
  out.emptyHandoffFiltered = { html: r.html, pool: r.pool.length, shown: r.shown.length };
} catch (e) {
  out.errors["emptyHandoffFiltered"] = e.constructor.name + ": " + e.message;
}

// The pills, WRITTEN BY syncTabs into the stub, once per tab so the pressed state is exercised too.
TABS_EL = makeTabs();
try {
  scope.pills("handed_off", ROWS);
  out.counts = Object.assign({}, TABS_EL.counts);
  out.pressed = Object.assign({}, TABS_EL.pressed);
} catch (e) {
  out.errors["syncTabs"] = e.constructor.name + ": " + e.message;
}

// ── which view each tab OPENS in ─────────────────────────────────────────────
// Executed through the real readView, with a real store behind it, on all three inputs that reach
// it: never toggled, toggled to each view. "Default View should be a list" is a claim about the
// first of those and says nothing about the other two, which is exactly the distinction a source
// read of the ternary loses.
out.views = {};
try {
  for (const tab of PILLS) {
    out.views[tab] = { fresh: scope.viewFor(tab, null),
                       storedTable: scope.viewFor(tab, "table"),
                       storedBoard: scope.viewFor(tab, "board"),
                       storedJunk: scope.viewFor(tab, "kanban") };
  }
} catch (e) {
  out.errors["views"] = e.constructor.name + ": " + e.message;
}

// ── the whole routing table, executed ────────────────────────────────────────
// The board fixtures above only cover the shapes that happen to be in ROWS. These are the states a
// won job can distinguishably be in, run through the real stage(), so the table anybody reasons from
// is GENERATED rather than argued. Every one of these is a shape a producer really makes: not_sent
// comes off api_portal_pipeline, the two `won_at` sent rows are drafts.set_won's whole purpose, and
// the approved ones are the portal's own deposit sequence.
//
// It runs stage() rather than the retired wonColumn because that is where the question moved. Until
// 2026-08-28 a won job's column came from a second vocabulary that only the Won tab spoke; now it
// comes from the same seven columns every other card is filed under, which is the entire point of
// the reversal and the one thing most worth pinning.
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
  "deposit submitted": { proposal_status: "approved", deposit_required: true,
                         deposit_status: "submitted" },
  "deposit received + contacts missing": { proposal_status: "approved", deposit_status: "received",
                                           contacts_status: "pending" },
  "everything settled": { proposal_status: "approved", deposit_status: "received",
                          contacts_status: "received" },
  // Not won at all: the three columns that exist for cards nobody has agreed to yet.
  "not_sent, unmarked": { not_sent: true },
  "sent, unmarked": { proposal_status: "sent" },
  "viewed, unmarked": { proposal_status: "viewed" },
};
out.stageRouting = {};
out.routingIsWon = {};
// The SAME shapes with the hand-off stamp on them. Handing a job off changes which TAB it is on and
// must change nothing about which column it would draw in — the two are separate facts, and a
// hand-off that quietly re-columned a card would make the Handed Off tab's single list disagree
// with the board it came off.
out.stageRoutingHandedOff = {};
for (const [name, row] of Object.entries(ROUTING)) {
  out.routingIsWon[name] = C.isWon(row);
  out.stageRouting[name] = C.stage(row);
  out.stageRoutingHandedOff[name] = C.stage(Object.assign({}, row, { handed_off_at: "2026-08-27T14:00:00Z" }));
}

// isHandedOff on its own, on the shapes that could plausibly fool a predicate that derived it rather
// than reading the one field. Nothing here is won-by-numbers enough to be handed off automatically,
// which is the assertion: there is no second half.
out.handoffPredicate = {
  "stamped": C.isHandedOff({ handed_off_at: "2026-08-27T14:00:00Z" }),
  "everything settled, unstamped": C.isHandedOff({ proposal_status: "approved",
                                                   deposit_status: "received",
                                                   contacts_status: "received" }),
  "won by hand, unstamped": C.isHandedOff({ won_at: W }),
  "empty": C.isHandedOff({}),
  "null": C.isHandedOff(null),
};

// BY ID, not by index: this list read [ROWS[0], ROWS[1], ROWS[11]] and inserting a fixture above
// silently repointed the third one at a different project, which is a green test about the wrong row.
out.wonControl = {};
// `won-complete` is the DERIVED win: approved, deposit in, contacts in, and nobody marked it. It
// is the one state with nothing to undo, and the panel has to say so out loud rather than leaving a
// gap where every other state has a control. `handoff-complete` is the state past it — the job
// operations has — which needs its own answer again, because "Hand it off" on a card already handed
// off is a button that does nothing.
//
// `approved-unpaid` is the state that had no drawer here at all until 2026-08-29, and its absence is
// why the bug shipped. Every other won-ish fixture carries `won_at`, so every one of them reaches
// the panel through `wonByHand` and would have rendered correctly no matter what the approved-only
// branch did. This row is approved with nobody having marked it: the ONLY fixture whose drawer
// depends on the branch that was missing.
const WON_CONTROL_ROWS = ["won-unsent", "unsent-plain", "won-marked-sent", "lost-after-won",
                          "won-complete", "handoff-complete", "handoff-unsent",
                          "won-deposit-out", "approved-unpaid"];
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
