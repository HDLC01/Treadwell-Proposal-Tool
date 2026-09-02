"use strict";
/* The Beta Polish tab, RUN rather than grepped.
 *
 * WHY EXECUTED. Every interesting claim here is about ORDER, and order is what source text cannot
 * show you:
 *
 *   * The sandbox files every beta copy with is_test true, so if the beta branch is placed BELOW
 *     realOnly() the tab renders empty -- every string still present, every grep still green, and
 *     the feature completely dead. That is the single most likely way to break this.
 *   * The chip count and the grid are two separate expressions over two different lists. A count
 *     taken off the real-bids list instead of ALL_PROJECTS shows "Beta Polish 0" above a tab full
 *     of rows -- which is the exact class of bug realOnly() was introduced to end.
 *   * A chip can render and bind nothing, in which case clicking it does nothing forever.
 *
 * The filter chain is LIFTED from frontend/js/projects.js -- nameLooksLikeTest, isTest, realOnly,
 * isActive, isInactive, applyFilter and renderChips are the page's own code. Only CURRENT_FILTER,
 * ALL_PROJECTS, the #filters node and paint() are stubs, because those are the edges.
 *
 * Deliberately NO regex and NO backslashes anywhere in this file: the lifts are line scans. This
 * toolchain strips a backslash level out of heredocs, which has silently broken harnesses here
 * before.
 *
 * Usage: node projects-beta-tab-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const LF = String.fromCharCode(10);
const DQ = String.fromCharCode(34);
const SRC = fs.readFileSync(path.join(process.argv[2], "js", "projects.js"), "utf8")
  .split(String.fromCharCode(13) + LF).join(LF);
const LINES = SRC.split(LF);

/** Lift a named function out of the projects.js IIFE (four-space indent) by line scan. */
function fn(name) {
  const head = "    function " + name + "(";
  const at = LINES.findIndex((l) => l.startsWith(head));
  if (at < 0) {
    throw new Error(name + "() is gone from projects.js -- rewrite this harness, do not stub it. "
      + "It is the page's real filter chain, and faking it would make this file agree with itself.");
  }
  const from = LINES.slice(0, at).join(LF).length + (at ? 1 : 0);
  let depth = 0;
  for (let j = SRC.indexOf("{", from); j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(from, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

// -- the fixtures ------------------------------------------------------------
// Shaped like real /api/drafts rows: polish_beta is projected on EVERY row (drafts.py:620, 684),
// never absent, and the sandbox stamps is_test true plus a " (beta test)" suffix onto the copy.
const ROWS = [
  { id: "a", project_name: "Niagara Bottling",             archived: false, is_test: false, polish_beta: false },
  { id: "b", project_name: "Blue Valley West",             archived: true,  is_test: false, polish_beta: false },
  { id: "c", project_name: "Niagara Bottling (beta test)", archived: false, is_test: true,  polish_beta: true  },
  { id: "d", project_name: "Olathe North (beta test)",     archived: true,  is_test: true,  polish_beta: true  },
  { id: "e", project_name: "delete me",                    archived: false, is_test: true,  polish_beta: false },
  // No is_test at all (a legacy row) and a name the heuristic catches. It must NOT reach the beta
  // tab -- polish_beta is the only thing that decides that, never the name.
  { id: "f", project_name: "QA sample",                    archived: false, polish_beta: false },
];

function scope(filter, rows) {
  const painted = { html: null, hidden: null, bound: [] };
  const node = {
    get innerHTML() { return painted.html; },
    set innerHTML(v) { painted.html = v; },
    set hidden(v) { painted.hidden = v; },
    get hidden() { return painted.hidden; },
    // One stub per chip the page actually rendered, so "it renders but binds nothing" is visible.
    querySelectorAll() {
      return (painted.html || "").split("data-filter=" + DQ).slice(1)
        .map((bit) => bit.split(DQ)[0])
        .map((key) => ({
          dataset: { filter: key },
          addEventListener(t) { painted.bound.push(key + ":" + t); },
        }));
    },
  };
  const body = [
    "var CURRENT_FILTER = FILTER;",
    "var ALL_PROJECTS = ROWS;",
    "var FILTER_KEY = 'beta-tab-harness';",
    "var sessionStorage = { setItem: function () {} };",
    "var document = { getElementById: function () { return NODE; } };",
    "function paint() {}",
    fn("nameLooksLikeTest"),
    fn("isTest"),
    fn("realOnly"),
    fn("isActive"),
    fn("isInactive"),
    fn("applyFilter"),
    fn("renderChips"),
    "return { applyFilter: applyFilter, renderChips: renderChips };",
  ].join(LF);
  return { s: new Function("FILTER", "ROWS", "NODE", body)(filter, rows, node), painted: painted };
}

const out = { shown: {} };

// Which rows each tab shows. ids only -- the point is membership, not row shape.
["active", "inactive", "all", "test", "beta"].forEach((f) => {
  out.shown[f] = scope(f, ROWS).s.applyFilter(ROWS).map((p) => p.id);
});

// The chip row: keys, labels and counts, DERIVED from what renderChips emitted rather than
// hard-coded here. test_active_projects_board.py records that a hard-coded tab list broke every
// time a tab was added; that lesson is why this is parsed and not asserted as a fixed five.
{
  const r = scope("beta", ROWS);
  r.s.renderChips();
  const html = r.painted.html || "";
  out.chips = html.split("<button").slice(1).map((bit) => ({
    key: bit.split("data-filter=" + DQ)[1].split(DQ)[0],
    label: bit.split(">")[1].split("<")[0],
    n: Number(bit.split("class=" + DQ + "n" + DQ + ">")[1].split("<")[0]),
    selected: bit.split("data-filter=")[0].indexOf("sel") >= 0,
  }));
  out.bound = r.painted.bound;
  out.filtersHidden = r.painted.hidden;
}

// No rows at all: the chip row hides itself, and nothing may throw on an empty list.
{
  const r = scope("beta", []);
  r.s.renderChips();
  out.chipsEmpty = { hidden: r.painted.hidden };
  out.shownEmpty = r.s.applyFilter([]);
}

process.stdout.write(JSON.stringify(out) + LF);
