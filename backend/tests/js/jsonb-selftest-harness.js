"use strict";
/* js/_jsonb.js, the helper every "reopen a saved draft" in the harnesses goes through, run over keys whose order is KNOWN.
 *
 * The order is PostgreSQL's, not an invention of ours: a jsonb object is stored with its keys sorted by length in BYTES and then by the bytes
 * (lengthCompareJsonbStringValue). The vectors below are the cases that tell that rule from the ones it is easily mistaken for: sorting by
 * character count or by UTF-16 code units, sorting alphabetically, or keeping the order the keys came in.
 *
 * Usage: node jsonb-selftest-harness.js [path to _jsonb.js]   ->  one line of JSON
 */
const path = require("path");
const J = require(path.resolve(process.argv[2] || path.join(__dirname, "_jsonb.js")));

const keysOf = (o) => Object.keys(o);
const obj = (keys) => Object.fromEntries(keys.map((k, i) => [k, i]));
const order = (keys) => keysOf(J.jsonbOrder(obj(keys)));

const out = {};
// PostgreSQL's documentation (8.14.1, json vs jsonb): '{"bar": "baz", "balance": 7.77, "active": false}'::jsonb is {"bar": "baz", "active": false, "balance": 7.77}.
out.documented = order(["bar", "balance", "active"]);
// shorter first, whatever the letters
out.length = order(["bb", "a", "ccc", "aa", ""]);
// equal lengths: by the bytes
out.bytes = order(["b", "a", "B", "A", "_"]);
// LENGTH IS IN BYTES: "é" is one character and two bytes, so it is not shorter than "zz", and it is longer than "b"; "€" is three bytes
out.multibyte = order(["é", "zz", "b", "€", "ab", "abc"]);
// the sheets of a bid: what the staging walk saw, and the ids that sort across each other
out.sheets = order(['Gyp (USG 1-8")', "Epoxy", "Copy1", "Copy2", "Copy10", "Polish 2", "Gyp (base)", "Seal"]);
// an array index key leads in JavaScript whatever order it was inserted in, exactly as JSON.parse does it in a browser
out.indexKeys = order(["b", "10", "a", "2"]);
// every depth, arrays keep their order and their objects' keys are sorted, scalars are untouched
const nested = { zz: [{ b: 1, a: { yy: 1, x: 2 } }, 3, null, "s"], a: { ccc: 1, bb: 2, a: 3 }, n: null, t: true };
const nestedOut = J.jsonbOrder(nested);
out.nested = { top: keysOf(nestedOut), list: nestedOut.zz.map((v) => (v && typeof v === "object" ? keysOf(v) : v)), deep: keysOf(nestedOut.zz[0].a), inner: keysOf(nestedOut.a), same: JSON.stringify(nestedOut.zz[0].a.yy) };
// nothing handed in is changed, and the result shares nothing with it
const before = JSON.stringify(nested);
const copy = J.jsonbOrder(nested);
copy.a.ccc = 99;
out.pure = { inputIntact: JSON.stringify(nested) === before, independent: nested.a.ccc === 1 };
// reloaded() is a JSON clone first: what the page saved and nothing else
const live = { b: 1, a: undefined, f: function () {}, d: new Date(0) };
const back = J.reloaded(live);
out.reloaded = { keys: keysOf(back), date: back.d };
// a key spelled __proto__ is data, as JSON.parse makes it, and never the object's prototype
const hostile = JSON.parse('{"zzzz": 1, "__proto__": {"polluted": true}, "a": 2}');
const hostileOut = J.jsonbOrder(hostile);
out.proto = { keys: keysOf(hostileOut), own: Object.prototype.hasOwnProperty.call(hostileOut, "__proto__"), polluted: ({}).polluted === true, prototypeKept: Object.getPrototypeOf(hostileOut) === Object.prototype };
// compareKeys is the order, as a comparator
out.compare = [J.compareKeys("a", "b"), J.compareKeys("b", "a"), J.compareKeys("a", "a"), J.compareKeys("zz", "é"), J.compareKeys("é", "b"), J.compareKeys("b", "é")];
console.log(JSON.stringify(out));
