"use strict";
/* WHAT POSTGRES DOES TO A DRAFT'S KEYS, FOR A HARNESS THAT REOPENS ONE.
 *
 * `drafts.data` is a jsonb column (backend/supabase_schema.sql for production, backend/staging/schema_pg.sql for staging), and jsonb does not
 * keep an object's keys in the order they were written. It stores them sorted by the key's LENGTH IN BYTES first and by the bytes themselves
 * (memcmp, unsigned) second (PostgreSQL's lengthCompareJsonbStringValue), at every depth, and that is the order GET /api/draft/{id} hands the
 * browser (FastAPI and Python's json keep a dict's order). PostgreSQL's own documentation shows it: '{"bar": "baz", "balance": 7.77, "active":
 * false}'::jsonb comes back as {"bar": "baz", "active": false, "balance": 7.77}.
 *
 * So a bid the estimator saves and reopens from the server is a DIFFERENT OBJECT from the one in the session: same values, other key order. Every
 * harness that models "save, then reload" with a plain JSON copy keeps the session's order and so cannot see anything that depends on it
 * (2026-10-20: a bid's `tabs` came back as [Polish 2, Gyp (base)] after a reload, and "Copy1" sorts before 'Gyp (USG 1-8")'). `reloaded(blob)`
 * is what a reopen of a saved blob must go through; `jsonbOrder(value)` is the re-keying alone.
 *
 * Built by inserting keys in the sorted order, which is what JSON.parse of the server's text does too, so the one reading JavaScript adds of
 * its own (a key that is an array index, like "1", comes first whatever order it was inserted in) happens here exactly as it does in a browser.
 * A key is defined as an OWN property (a key spelled __proto__ is data, as JSON.parse makes it, and never the object's prototype).
 *
 * Used by travel-sequence-harness.js, travel-round5-harness.js, polish-estimate-harness.js (its reopens) and sheet-order-harness.js.
 */

/** Postgres's order for two jsonb keys: shorter (in UTF-8 bytes) first, equal lengths by their bytes. -1, 0 or 1. */
function compareKeys(a, b) {
  const x = Buffer.from(String(a), "utf8");
  const y = Buffer.from(String(b), "utf8");
  if (x.length !== y.length) return x.length < y.length ? -1 : 1;
  return Buffer.compare(x, y);
}

/** `value` with the keys of every object, at every depth, in jsonb's order. A NEW value: nothing handed in is changed. Arrays keep their order
 *  (jsonb arrays do), and everything that is not an object or an array comes back as it is. */
function jsonbOrder(value) {
  if (Array.isArray(value)) return value.map(jsonbOrder);
  if (value && typeof value === "object") {
    const out = {};
    Object.keys(value).sort(compareKeys).forEach((k) => {
      Object.defineProperty(out, k, { value: jsonbOrder(value[k]), enumerable: true, writable: true, configurable: true });
    });
    return out;
  }
  return value;
}

/** A saved blob as the server hands it back on a reopen: the JSON that was PUT (a plain clone: what the page saved and nothing else), with every
 *  object's keys in jsonb's order. */
function reloaded(blob) {
  return jsonbOrder(JSON.parse(JSON.stringify(blob)));
}

module.exports = { compareKeys, jsonbOrder, reloaded };
