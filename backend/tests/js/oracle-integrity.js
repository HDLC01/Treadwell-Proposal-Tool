"use strict";
/* WHAT MAKES THE RECORDED ANSWERS TAMPER-EVIDENT: the one definition of what is hashed and how.
 *
 *   node backend/tests/js/oracle-integrity.js [<bid-profiles.js>]     prints {"profiles":"<sha256>"}
 *
 * THE GAP THIS CLOSES. The recorded answers (backend/tests/fixtures/oracle/<tab>.json) are only worth
 * something while they are what the oracle computed. Every other check CI runs on them is arithmetic: the
 * total is the sum of its parts, each edge straddles its rung, every question is answered both ways. A
 * value edited by hand together with the figure that has to add up to it (gp and total both raised by
 * 1,000) satisfies all of them. Nothing but a hash of the file sees it, so the oracle records one, in
 * meta.json, for every file it writes and for the cell maps it read, and backend/tests/test_workbook_oracle.py
 * recomputes them in CI, where HyperFormula is not installed, and says "re-run the oracle".
 *
 * WHO USES IT
 *   - workbook-oracle.js requires it and writes `integrity` into meta.json when it regenerates.
 *   - backend/tests/_oracle_support.py runs it as a script (profiles_sha256) to recompute the cell-map hash,
 *     so the value that is written and the value that is checked come out of the same code. The file hashes
 *     are computed twice, once here and once in Python (text_sha256), and CI requires them to agree.
 *
 * WHAT THE CELL-MAP HASH COVERS: exactly what workbook-oracle.js reads out of frontend/js/bid-profiles.js.
 * For each priced tab SHEET_FIELDS (its file name, its layout family, and the groups flags, inputs, rates,
 * fixed, outputs, ladders), plus the list of priced tabs and flagWords. Not `families`, which only
 * test_workbook_formula_pins.py reads, and not `version`, and not a comment: a note rewritten there does not
 * make the answers stale, so it must not ask anybody to run the oracle. Text is hashed as canonical JSON
 * (keys sorted, no spaces), so the order a module happens to build its objects in does not matter either.
 */
const crypto = require("crypto");
const path = require("path");

/** The fields of one tab's map that workbook-oracle.js reads. A field the oracle starts to read has to be
 *  added here in the same change, or a change to it would leave the hash where it was. */
const SHEET_FIELDS = ["slug", "family", "flags", "inputs", "rates", "fixed", "outputs", "ladders"];

/** sha256 of some text with every "\r\n" read as "\n" (a Windows checkout of an LF file). Nothing else is
 *  folded: not a lone "\r", not a byte-order mark. */
function textSha256(text) {
  return crypto.createHash("sha256").update(String(text).replace(/\r\n/g, "\n"), "utf8").digest("hex");
}

/** Plain data as JSON text with every object's keys sorted and nothing between tokens. Refuses what JSON
 *  would quietly change (undefined, a function, NaN, Infinity), naming where it was. */
function canonicalJson(value, where) {
  const at = where || "value";
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error(at + " is " + value + ", which JSON cannot hold");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return "[" + value.map((v, i) => canonicalJson(v, at + "[" + i + "]")).join(",") + "]";
  if (value !== null && typeof value === "object") {
    return "{" + Object.keys(value).sort().map((k) => JSON.stringify(k) + ":" + canonicalJson(value[k], at + "." + k)).join(",") + "}";
  }
  throw new Error(at + " is a " + typeof value + ", not data");
}

/** The cell-map data the oracle read, as one plain object (see the top of this file). */
function profileData(P) {
  const tabs = P.priced.map((tab) => [tab, Object.fromEntries(SHEET_FIELDS.map((f) => [f, P.sheets[tab][f]]))]);
  return { flagWords: P.flagWords, priced: P.priced, sheets: Object.fromEntries(tabs) };
}

/** sha256 of profileData(P) as canonical JSON. */
function profilesSha256(P) {
  return textSha256(canonicalJson(profileData(P), "profiles"));
}

module.exports = { SHEET_FIELDS, textSha256, canonicalJson, profileData, profilesSha256 };

if (require.main === module) {
  const file = process.argv[2] || path.join(__dirname, "..", "..", "..", "frontend", "js", "bid-profiles.js");
  process.stdout.write(JSON.stringify({ profiles: profilesSha256(require(path.resolve(file))) }) + "\n");
}
