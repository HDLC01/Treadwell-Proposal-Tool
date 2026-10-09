"use strict";
/* Execute the REAL frontend/js/library-picker.js's pure half: filter, work-type ordering,
 * multi-select, locked rows, the one-off name. The DOM half is run end to end by
 * polish-estimate-harness.js (section N), which mounts this same module on that page.
 * Usage: node library-picker-harness.js <frontend-dir>  ->  one line of JSON */
const path = require("path");
const P = require(path.join(path.resolve(process.argv[2]), "js", "library-picker.js"));

const E = [
  { key: "a", name: "Polish 800 Grit", sub: "Assembly, per SF" },
  { key: "b", name: "Cove Base", sub: "Assembly, per LF", first: true },
  { key: "c", name: "Densifier", sub: "Material, Pail" },
  { key: "d", name: "Epoxy prep", sub: "Days", first: true },
  { key: "e", name: "Grout Compound", sub: "Material, Pail", on: true },
];
const names = (l) => l.map((e) => e.key);
const out = {};

out.all = names(P.shown(E, ""));                     // first rows above the rest, each group stable
out.oneWord = names(P.shown(E, "cove"));
out.twoWordsNarrow = names(P.shown(E, "material pail"));
out.matchesTheSmallLine = names(P.shown(E, "per lf"));
out.caseAndSpaces = names(P.shown(E, "  DENSI  "));
out.none = names(P.shown(E, "zzz"));
out.notArray = P.shown(null, "x");
const before = JSON.stringify(E);
P.shown(E, "cove");
out.inputUntouched = JSON.stringify(E) === before;

let keys = [];
keys = P.toggle(keys, "c");
keys = P.toggle(keys, "a");
out.afterTwo = keys.slice();
const keys2 = P.toggle(keys, "c");
out.afterUntick = keys2.slice();
out.toggleIsNew = keys.length === 2 && keys !== keys2;
// keys that look like property names are only compared, never used as names
out.protoKey = P.toggle(P.toggle([], "__proto__"), "constructor");
// picked: list order (not tick order), locked rows never come back, a stale key is dropped
out.picked = names(P.picked(E, ["c", "a", "e", "gone"]));

out.clean = [P.cleanName("  Hand   grind "), P.cleanName("   "), P.cleanName(null), P.cleanName("x")];
console.log(JSON.stringify(out));
