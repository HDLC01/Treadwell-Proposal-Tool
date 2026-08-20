// Lifts the History page's VERB map out of frontend/js/history.js and prints its keys.
//
// Executed rather than pattern-matched, for the usual reason in this repo: a regex over the
// source counts lines that look like entries, which is not the same as the object the browser
// ends up with. A duplicate key, a stray comma, or an entry commented out mid-block all read
// as present to a grep and are absent at runtime. Evaluating the literal is the only way to
// learn what History can actually label.
//
// Mirrors topConst/topConstValue in board-render-harness.js — same trick, one file over.
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const src = fs.readFileSync(path.join(ROOT, "frontend", "js", "history.js"), "utf8");

/** The text of a top-level `const NAME = <literal>;`, brace-balanced. */
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

const text = topConst("VERB");
if (!text) throw new Error("const VERB is gone from history.js — rewrite this harness");
const lit = text.slice(text.indexOf("=") + 1).replace(/;\s*$/, "");
const VERB = new Function('"use strict"; return (' + lit + ");")();

// The fallback that makes a missing entry user-visible rather than silent. Lifted as a string
// so the Python side can assert the shape it depends on is still there: if History stops
// falling back to the raw action, a missing label becomes "undefined" on screen instead of an
// ugly-but-readable machine word, and the test's premise changes.
const FALLBACK_PRESENT = /VERB\[e\.action\]\s*\|\|\s*e\.action/.test(src);

process.stdout.write(JSON.stringify({
  verbs: Object.keys(VERB),
  labels: VERB,
  fallbackPresent: FALLBACK_PRESENT,
}));
