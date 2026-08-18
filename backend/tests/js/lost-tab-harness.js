"use strict";
/* Runs the Lost tab's two pure functions FOR REAL, out of portal.js, against the shipped
 * crm-core predicates.
 *
 * Source assertions can prove `boardPool` mentions the lost tab; only running it proves a lost
 * test project lands somewhere, that the three tabs partition the rows, and that an unrecognised
 * stored reason does not drop a card off the board. portal.js is a browser IIFE that touches the
 * DOM at load, so the functions are lifted out by name rather than the module being required.
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
const TW = { fmtBizDay: (v) => String(v) };
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
];

ALL = ROWS;
const pools = {};
for (const t of ["active", "test", "lost"]) {
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

console.log(JSON.stringify({
  chips: chips,
  pools: pools,
  cols: scope.LOST_COLS,
  reasonLabels: Object.keys(C.LOST_REASON).map((k) => C.LOST_REASON[k]),
  grouped: grouped,
  everyId: ids(ROWS),
}));
