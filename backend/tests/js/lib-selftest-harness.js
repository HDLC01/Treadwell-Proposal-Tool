"use strict";
/* Run the helpers in _lib.js against inputs built to break them, and against the REAL page files.
 *
 * Every later harness in the v2 program lifts functions out of pages that are about to be
 * refactored, so a helper that lifts the wrong text, or quietly stops at a brace inside a string,
 * would make every one of those harnesses green for the wrong reason. These are the cases the
 * hand-written copies in the older harnesses get wrong, each stated with the answer it must give.
 *
 * The last block is the one that matters most: it takes EVERY `function name(` declaration out
 * of seven real frontend files, lifts it with liftSource, and compiles the result. A matcher that
 * miscounts a brace, a template literal or a regex literal anywhere in thousands of real lines
 * produces text that does not parse, and shows up here by name.
 *
 * Usage: node lib-selftest-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const os = require("os");
const path = require("path");
const vm = require("vm");
const L = require("./_lib");

const FRONTEND = process.argv[2];
const out = {};

/** The message of whatever `f` throws, or null when it does not throw. */
function threw(f) {
  try { f(); } catch (e) { return String(e && e.message); }
  return null;
}

// ── read ────────────────────────────────────────────────────────────────────
{
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-lib-"));
  try {
    const p = path.join(dir, "crlf.txt");
    fs.writeFileSync(p, "﻿one\r\ntwo\r\n\r\nthree\n");
    out.read = L.read(p);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// ── balanced ────────────────────────────────────────────────────────────────
/** The slice from the first `{` to the bracket `balanced` says closes it. */
function braced(src) {
  const open = src.indexOf("{");
  return src.slice(open, L.balanced(src, open) + 1);
}
out.balanced = {
  plain: braced("x { a { b } c } tail"),
  inDoubleQuote: braced('x { s = "}"; } tail'),
  inSingleQuote: braced("x { s = '}{'; } tail"),
  escapedQuote: braced('x { s = "a\\"}"; } tail'),
  inTemplate: braced("x { s = `}`; } tail"),
  templateSubstitution: braced("x { s = `a${ {k: 1}.k }b}`; } tail"),
  nestedTemplate: braced("x { s = `a${ `b${ 1 }}` }c`; } tail"),
  inLineComment: braced("x { // }\n a } tail"),
  inBlockComment: braced("x { /* } */ a } tail"),
  inRegexLiteral: braced("x { r = /[}]/g; } tail"),
  slashInRegexClass: braced("x { r = /[/}]/; } tail"),
  afterReturn: braced("x { return /}/.test(s); } tail"),
  division: braced("x { n = (a + b) / 2 / 3; } tail"),
  divisionAfterNumber: braced("x { n = 4 / 2; /* } */ } tail"),
  parens: (function () { const s = "f(a, (b), [c]) tail"; return s.slice(1, L.balanced(s, 1) + 1); })(),
  brackets: (function () { const s = "[1, [2, 3], {a: 4}] tail"; return s.slice(0, L.balanced(s, 0) + 1); })(),
  mismatched: threw(function () { L.balanced("{ ( }", 0); }),
  notAnOpener: threw(function () { L.balanced("abc", 0); }),
  runsOff: threw(function () { L.balanced("{ a { b }", 0); }),
};

// ── liftSource, lift, grabConst ─────────────────────────────────────────────
const SRC = [
  "(function () {",
  '  "use strict";',
  "  var K = 3;",
  "  function add(a, b) { return a + b + K; }",
  "  function outer() {",
  "    function add(a, b) { return 'nested'; }",
  "    return add(1, 2);",
  "  }",
  "  async function load(x = { y: 1 }) { return x.y; }",
  "  function brace() { return '}' + `{${K}}` + /}/.source; }",
  "  function usesDep() { return helper(2); }",
  "  const ROLES = new Set([\"a\", \"b;\"]);",
  "  const TABLE = { one: function () { return 1; }, two: 2 };",
  "  var LONG = [",
  "    1, 2,",
  "  ];",
  "})();",
].join("\n");

const lifted = {};
{
  const add = L.lift(SRC, "add", { K: 10 }, { indent: "  ", where: "synthetic.js" });
  lifted.addWithDep = add(1, 2);
  lifted.sourceOfAdd = L.liftSource(SRC, "add", { indent: "  " });
  lifted.nestedPicked = L.liftSource(SRC, "add", { indent: "    " });
  lifted.ambiguous = threw(function () { L.liftSource(SRC, "add", { where: "synthetic.js" }); });
  lifted.gone = threw(function () { L.liftSource(SRC, "nothing", { where: "synthetic.js" }); });
  lifted.asyncDefault = L.liftSource(SRC, "load");
  lifted.braceInside = L.liftSource(SRC, "brace");
  // a callee the harness did not hand over is unbound in the copy, and says so when it runs
  const bad = L.lift(SRC, "usesDep", {});
  lifted.unbound = threw(function () { bad(); });
  const good = L.lift(SRC, "usesDep", { helper: function (n) { return n * 21; } });
  lifted.bound = good();
  lifted.constSet = L.grabConst(SRC, "ROLES");
  lifted.constObject = L.grabConst(SRC, "TABLE");
  lifted.constArray = L.grabConst(SRC, "LONG");
  lifted.constGone = threw(function () { L.grabConst(SRC, "NOPE"); });
  lifted.prefixIsNotAMatch = L.liftSource("function addAll() { return 1; }\nfunction add() { return 2; }", "add");
  lifted.grab = L.grab("alpha beta", /b\w+/, "beta");
  lifted.grabMissing = threw(function () { L.grab("alpha", /zzz/, "zzz"); });
}
out.lift = lifted;

// ── stripTags ───────────────────────────────────────────────────────────────
out.stripTags = {
  plain: L.stripTags("<p>One <b>two</b></p>"),
  comment: L.stripTags("a<!-- <b>hidden</b> -->b"),
  quotedGreaterThan: L.stripTags('<a title="x > y">link</a>'),
  singleQuoted: L.stripTags("<a title='x > y'>link</a>"),
  // The reason the loop exists: one pass over this leaves a live <script>.
  buildsATag: L.stripTags("<<b>script>alert(1)<</b>/script>"),
  buildsAComment: L.stripTags("<<b>!-- x -->y"),
  nestedDeep: L.stripTags("<<<b>b>b>script>x"),
  loneLessThan: L.stripTags("1 < 2 and 3 > 2"),
  unterminatedTag: L.stripTags("keep <div class='open"),
  unterminatedComment: L.stripTags("keep <!-- never closed"),
  empty: L.stripTags(""),
  nullish: L.stripTags(null),
  noTagSurvives: (function () {
    const hostile = ["<<b>script>", "<scr<b>ipt>", "<<<b>b>b>img src=x>", "<!<b>-- a -->"];
    return hostile.map(function (h) { const s = L.stripTags(h); return s.indexOf("<") < 0 || !/<[a-zA-Z!/?]/.test(s); });
  })(),
};

// ── escapeRegExp, reOf ──────────────────────────────────────────────────────
{
  const meta = ".*+?^${}()|[]\\/-";
  out.escape = {
    escaped: L.escapeRegExp(meta),
    everyMetaMatchesItself: Array.from(meta).map(function (c) { return L.reOf(c).test(c); }),
    wholeStringMatchesItself: L.reOf(meta).test(meta),
    doesNotMatchTheWildcardMeaning: L.reOf("a.c").test("abc"),
    matchesTheLiteral: L.reOf("a.c").test("a.c"),
    flags: L.reOf("A+", "i").test("a+"),
    number: L.escapeRegExp(12.5),
  };
}

// ── the real page files: lift every function, compile every one ─────────────
const FILES = ["js/polish-estimate.js", "js/estimate-review.js", "js/proposal-review.js", "js/library.js",
  "js/polish-bid-core.js", "js/index.js", "js/portal.js"];
const DECL = /(^|\n)([ \t]*)(?:async[ \t]+)?function[ \t]*\*?[ \t]*([A-Za-z_$][\w$]*)[ \t]*\(/g;
out.sweep = FILES.map(function (rel) {
  const src = L.read(path.join(FRONTEND, rel));
  const seen = new Map();
  let m;
  DECL.lastIndex = 0;
  while ((m = DECL.exec(src))) {
    const key = m[2] + "\u0000" + m[3];
    seen.set(key, (seen.get(key) || 0) + 1);
  }
  let lifted = 0;
  const failures = [];
  seen.forEach(function (count, key) {
    if (count !== 1) return;                    // two at one indent needs a human, not a sweep
    const parts = key.split("\u0000");
    try {
      const code = L.liftSource(src, parts[1], { indent: parts[0], where: rel });
      new vm.Script("(" + code + ")", { filename: rel + "#" + parts[1] });
      lifted++;
    } catch (e) {
      failures.push({ name: parts[1], error: String(e && e.message).slice(0, 160) });
    }
  });
  return { file: rel, declared: seen.size, lifted: lifted, failures: failures };
});

// Constants lifted by name out of a real page, and evaluated: the shapes later phases read.
{
  const est = L.read(path.join(FRONTEND, "js", "estimate-review.js"));
  const roles = new Function(L.grabConst(est, "PRICED_ROLES") + "\nreturn PRICED_ROLES;")();
  const baseRole = new Function(L.grabConst(est, "BASE_ROLE") + "\nreturn BASE_ROLE;")();
  out.realConsts = { pricedRoles: Array.from(roles).sort(), baseRoleIsObject: typeof baseRole === "object" && baseRole !== null };
}

console.log(JSON.stringify(out));
