"use strict";
/* Runs the Lost tab's two pure functions FOR REAL, out of portal.js, against the shipped
 * crm-core predicates.
 *
 * Source assertions can prove `boardPool` mentions the lost tab; only running it proves a lost
 * test project lands somewhere, that the tabs partition the rows, and that an unrecognised stored
 * reason does not drop a card off the board. portal.js is a browser IIFE that touches the DOM at
 * load, so the functions are lifted out by name rather than the module being required.
 *
 * It also runs the TAB LIST and the line that resolves a stored tab, which replaced a source-text
 * pin on `const TABS = [...]` in test_active_projects_board.py on 2026-08-20 — see resolveTab.
 *
 * Usage: node lost-tab-harness.js <crm-core.js> <portal.js>   →   one line of JSON
 */
const fs = require("fs");

const C = require(process.argv[2]);
const src = fs.readFileSync(process.argv[3], "utf8");

/** The full `function name(...) {...}` text, brace-counted so a template literal or an object
 *  literal inside the body cannot truncate it. */
function fn(name) {
  const m = new RegExp("\\n\\s{2,6}function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from portal.js — rewrite this harness, don't delete it");
  let i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name + "()");
}

const colsLine = /const LOST_COLS = .*;/.exec(src);
if (!colsLine) throw new Error("LOST_COLS is gone from portal.js");

// THE TAB LIST, AND THE LINE THAT RESOLVES IT, both lifted out and RUN rather than matched.
// test_active_projects_board.py used to pin `const TABS = ["active", "test", "lost"]` as a literal
// string, which is worth almost nothing here: it cannot see that a tab in the list has no pill in
// the markup, and it cannot see that boardPool sends nothing to it. It also had to be edited by hand
// on 2026-08-20 when the Won tab arrived, which is the tell. On 2026-08-28 the same habit cost more
// than an edit: a hand-typed `data-tab="([a-z]+)"` elsewhere silently dropped `handed_off` and
// reported the markup as missing a pill it ships. Read TABS, don't retype it. Both declarations are
// single-line and semicolon-terminated, so a bracket count is not needed.
const tabsLine = /const TABS = \[[^\]]*\];/.exec(src);
if (!tabsLine) throw new Error("const TABS is gone from portal.js — rewrite this harness, don't delete it");
const tabDecl = /\n\s*let TAB = [^;]*;/.exec(src);
if (!tabDecl) throw new Error("the `let TAB = …` resolution is gone from portal.js — rewrite this harness");

const TABS = new Function('"use strict";\n' + tabsLine[0] + "\nreturn TABS;")();

/** Which tab the page LANDS on for a stored sessionStorage value, out of portal.js's own
 *  expression. `null` stands for "nothing stored". The fallback matters on its own: a stale session
 *  holding a tab that no longer exists must land on Active rather than paint no pressed pill over an
 *  empty board. */
function resolveTab(stored) {
  const f = new Function("ss", "TAB_KEY",
                         '"use strict";\n' + tabsLine[0] + tabDecl[0] + "\nreturn TAB;");
  return f((k, d) => (stored === null ? d : stored), "tw_crm_tab");
}

// Everything the two functions close over, supplied exactly as portal.js supplies it: the
// predicates come from crm-core, so a change there is felt here rather than being stubbed away.
const { isLost, isTest, lostReason } = C;
let TAB = "active";
let ALL = [];
// chipsHtml's other collaborators, stubbed to the shape it expects. isTest/isLost/lostReason stay
// real, because they are what the chip's correctness depends on.
const esc = (v) => String(v == null ? "" : v);
const pausedUntil = () => null;
const followupOff = () => false;
// BOTH date formatters chipsHtml reaches for. fmtBizDate is the Handed off chip's, added with the
// handed-off fixture below: a stub missing one formatter throws a TypeError inside the chip and
// takes the whole harness down, which is the same failure the real page would have.
const TW = { fmtBizDay: (v) => String(v), fmtBizDate: (v) => String(v) };
const scope = eval(
  "(() => {\n" + colsLine[0] + "\n" + fn("boardPool") + "\n" + fn("groupByReason") + "\n" + fn("chipsHtml") +
  "\nreturn { boardPool, groupByReason, chipsHtml, LOST_COLS };\n})()");

const ids = (list) => list.map((p) => p.proposal_id);

const ROWS = [
  { proposal_id: "live-active", project_name: "Cedar Ridge Distribution Center",
    proposal_status: "sent" },
  { proposal_id: "live-test", project_name: "Cedar Ridge Distribution Center", is_test: true,
    proposal_status: "sent" },
  { proposal_id: "lost-price", project_name: "Westport Retail Center",
    proposal_status: "closed_lost", followup_state: { closed_lost_reason: "price" } },
  { proposal_id: "lost-test", project_name: "Test Will 7/29", is_test: true,
    proposal_status: "closed_lost", followup_state: { closed_lost_reason: "timing" } },
  { proposal_id: "lost-noreason", project_name: "Maple Street Warehouse",
    proposal_status: "closed_lost" },
  { proposal_id: "lost-unknown", project_name: "Fairview Clinic", proposal_status: "closed_lost",
    followup_state: { closed_lost_reason: "aliens" } },
  // WON, both ways a job can get there (2026-08-19). The chip exists so this board and the
  // Notification Sending page agree about the word out loud, not only in crm-core.
  { proposal_id: "won-paid", project_name: "Riverside Logistics", proposal_status: "approved",
    deposit_status: "received" },
  { proposal_id: "won-nodeposit", project_name: "Brookfield GC Tenant Fit-out",
    approved_at: "2026-08-01T12:00:00Z", proposal_status: "sent", deposit_required: false },
  // Approved with the money still out. NOT won — this is the most worth-chasing row there is, and
  // a Won chip on it would tell the estimator the job is done.
  { proposal_id: "approved-unpaid", project_name: "Halstead Medical",
    proposal_status: "approved", deposit_status: "pending" },
  // Won and then lost anyway (a cancelled job). Lost has to win the chip, or the card claims both.
  { proposal_id: "lost-after-won", project_name: "Kellogg Self Storage",
    proposal_status: "closed_lost", approved_at: "2026-08-01T12:00:00Z",
    deposit_status: "received", followup_state: { closed_lost_reason: "canceled" } },
  // MARKED WON BY HAND (2026-08-19), with neither half of the derived rule true of it: sent,
  // unapproved, no deposit. The chip is how the board says out loud what a colleague recorded on the
  // phone — without it the card reads as untouched work.
  { proposal_id: "won-marked", project_name: "Elmwood Cold Storage", proposal_status: "sent",
    won_at: "2026-08-19T15:00:00Z" },
  // Marked won by hand and closed lost afterwards. Lost still takes the chip.
  { proposal_id: "lost-after-marked-won", project_name: "Grandview Terminal",
    proposal_status: "closed_lost", won_at: "2026-08-19T15:00:00Z",
    followup_state: { closed_lost_reason: "canceled" } },
  // HANDED OFF (2026-08-28): the same shape as won-paid, one press of the button later. The pools
  // stopped turning on isWon that day — a won job still owes a deposit and a set of contacts, so it
  // stays on the Active board — and a hand-off is what takes a card off it now. Without a row
  // carrying the stamp, "won-paid is on Active" would be equally true of a board nothing ever leaves,
  // so this fixture is what makes that assertion mean anything.
  //
  // `handed_off_at` and nothing else, because isHandedOff derives nothing: a person pressing the
  // button is the only thing that can know operations has the job.
  { proposal_id: "handoff-done", project_name: "Northgate Cold Storage",
    proposal_status: "approved", deposit_status: "received", contacts_status: "received",
    handed_off_at: "2026-08-28T14:00:00Z" },
  // Somebody's scratch work, won. The pools are decided by isLost, then is_test, then isHandedOff
  // (isWon held that third place from 2026-08-20 until 2026-08-28), so this is the row a restored
  // won-leaves-the-board rule would move: it is a test project AND a won one, and it has to stay
  // under Test either way. Which pool it belongs in — Test, because scratch work does not become
  // real work by being marked won — is asserted by name in test_handed_off_tab.py, not here.
  { proposal_id: "won-test", project_name: "Will 8/20 Test", is_test: true,
    proposal_status: "approved", deposit_status: "received", contacts_status: "received" },
];

ALL = ROWS;
// EVERY tab portal.js names, not a list typed here: the partition assertion is only worth anything
// if a tab added to TABS is a tab this loop visits. It was a hardcoded triple until 2026-08-20,
// when the Won tab arrived and the sum stopped covering the rows.
const pools = {};
for (const t of TABS) {
  TAB = t;
  pools[t] = ids(scope.boardPool());
}

TAB = "lost";
const grouped = {};
const by = scope.groupByReason(scope.boardPool());
for (const col of Object.keys(by)) grouped[col] = ids(by[col]);

// The Test chip, RENDERED. Four rows: lost+test must say Test, lost+real must not, and neither
// live row may carry it — on the live tabs the tab itself is the label.
const chips = {};
for (const r of ROWS) chips[r.proposal_id] = scope.chipsHtml(r);

// Which tab a stored value resolves to, run through portal.js's own expression. "haggis" stands for
// a tab a past deploy had and this one does not.
const resolved = { stored: {}, nothingStored: resolveTab(null), unknown: resolveTab("haggis") };
for (const t of TABS) resolved.stored[t] = resolveTab(t);

console.log(JSON.stringify({
  chips: chips,
  pools: pools,
  tabs: TABS,
  resolved: resolved,
  cols: scope.LOST_COLS,
  reasonLabels: Object.keys(C.LOST_REASON).map((k) => C.LOST_REASON[k]),
  grouped: grouped,
  everyId: ids(ROWS),
}));
