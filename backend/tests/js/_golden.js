"use strict";
/* The golden-master toolkit: record what today's code answers, keep it in a file, compare later.
 *
 * WHAT A GOLDEN MASTER IS FOR. The v2 estimating program rewrites the engine behind the Polish
 * bid in a dozen steps. Each step must leave every price exactly where it was, or move it on
 * purpose and in view. So before anything moves, this records what the code gives for a few
 * thousand deliberately awkward inputs (a vector is a function name, its arguments, and its full
 * answer), cut from a clean export of origin/staging. After that, every change either leaves the
 * file alone (nothing moved) or shows up as a diff of lines somebody can read.
 *
 * NO COPIED CODE. A recipe never re-implements what it records. It lists INPUTS; the answers come
 * from running the real functions. A golden that held a second copy of the formulas would be a
 * second opinion that drifts, which is the defect this program exists to remove.
 *
 * THE COMPARISON IS assert.deepStrictEqual, and so is the file. JSON cannot say -0, NaN, Infinity
 * or `undefined`, and a comparison that goes through JSON.stringify hides exactly those: a refactor
 * that turns `-0` into `0`, or an `undefined` field into a missing one, would pass. The codec below
 * stores each of them as a tagged object ({"$":"-0"}), the compare decodes the file back into real
 * values, and Node's own strict deep equality (which tells 0 from -0 and treats NaN as equal to
 * itself) is the judge. A readable "first difference" is worked out separately, for the message
 * only; the verdict is never its.
 *
 * A VECTOR is {id, fn, args, out}. `out` is the function's answer; `threw` (the error's NAME, never
 * its message, which differs between node versions) replaces it when the call threw; `mut: true` is
 * written only when the call changed its own arguments, so a refactor that starts mutating (or
 * stops) shows as one line.
 *
 * Usage, from a generator script built on main() below:
 *   node gen-x-golden.js <frontend-dir>                              print the golden
 *   node gen-x-golden.js <frontend-dir> --write <file> --commit <sha>  write it
 *   node gen-x-golden.js <frontend-dir> --compare <file>             exit 1 and say why if it differs
 *   ... --compare <file> --limit 100000                              list every differing vector, not five
 */
const assert = require("assert");
const fs = require("fs");
const util = require("util");

const TAG = "$";

// ── the codec: JSON that can say -0, NaN, Infinity and undefined ─────────────
function tagged(name) { return { [TAG]: name }; }

/** A value as plain JSON-safe data. Throws on anything a recipe has no business holding. */
function encode(v, where) {
  const at = where || "value";
  if (v === undefined) return tagged("undefined");
  if (v === null || typeof v === "string" || typeof v === "boolean") return v;
  if (typeof v === "number") {
    if (Number.isNaN(v)) return tagged("NaN");
    if (v === Infinity) return tagged("Infinity");
    if (v === -Infinity) return tagged("-Infinity");
    if (Object.is(v, -0)) return tagged("-0");
    return v;
  }
  if (Array.isArray(v)) {
    const out = [];
    for (let i = 0; i < v.length; i++) {
      if (!(i in v)) throw new Error(at + "[" + i + "] is a hole in a sparse array");
      out.push(encode(v[i], at + "[" + i + "]"));
    }
    return out;
  }
  if (typeof v === "object") {
    // Only ordinary objects. A null-prototype object would come back from the file as a normal one,
    // and deepStrictEqual (rightly) tells those apart, so it is refused here rather than lost.
    const proto = Object.getPrototypeOf(v);
    if (proto !== Object.prototype) {
      throw new Error(at + " is " + (proto === null ? "an object with no prototype" : "a " + (proto.constructor && proto.constructor.name)) +
        ", not plain data");
    }
    const keys = Object.keys(v);
    if (keys.includes(TAG)) throw new Error(at + " has a key named " + TAG + ", which the codec reserves");
    return Object.fromEntries(keys.map((k) => [k, encode(v[k], at + "." + k)]));
  }
  throw new Error(at + " is a " + typeof v + ", which a golden cannot hold");
}

/** The inverse of encode: tagged objects back into -0, NaN, Infinity and undefined. */
function decode(j) {
  if (Array.isArray(j)) return j.map(decode);
  if (j !== null && typeof j === "object") {
    const keys = Object.keys(j);
    if (keys.length === 1 && keys[0] === TAG) {
      switch (j[TAG]) {
        case "undefined": return undefined;
        case "NaN": return NaN;
        case "Infinity": return Infinity;
        case "-Infinity": return -Infinity;
        case "-0": return -0;
        default: throw new Error("unknown codec tag " + JSON.stringify(j[TAG]));
      }
    }
    return Object.fromEntries(keys.map((k) => [k, decode(j[k])]));
  }
  return j;
}

// ── saying what differs ──────────────────────────────────────────────────────
const ABSENT = Symbol("absent");

/** A value for a message: node's own inspect, which prints -0 as -0 and NaN as NaN. */
function show(v) {
  if (v === ABSENT) return "(absent)";
  return util.inspect(v, { depth: 4, breakLength: Infinity, compact: true, maxArrayLength: 10, maxStringLength: 140 });
}

/** A call's arguments for a message: `3, -0` for f(3, -0), cut short when there are many. */
function showArgs(args) {
  const text = (Array.isArray(args) ? args : [args]).map(show).join(", ");
  return text.length > 220 ? text.slice(0, 217) + "..." : text;
}
function isPlain(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

/** The first place `want` and `got` part, as {path, want, got}, or null when they do not.
 *  Uses Object.is for leaves, so 0 against -0 and NaN against NaN are told apart correctly.
 *  This only words the message: the verdict is assert.deepStrictEqual's. */
function firstDifference(want, got, path) {
  const here = path || "";
  if (Object.is(want, got)) return null;
  if (Array.isArray(want) && Array.isArray(got)) {
    const n = Math.max(want.length, got.length);
    for (let i = 0; i < n; i++) {
      const d = firstDifference(i < want.length ? want[i] : ABSENT, i < got.length ? got[i] : ABSENT,
        here + "[" + i + "]");
      if (d) return d;
    }
    return null;
  }
  if (isPlain(want) && isPlain(got)) {
    const keys = Object.keys(want).concat(Object.keys(got).filter((k) => !Object.prototype.hasOwnProperty.call(want, k)));
    for (const k of keys) {
      const w = Object.prototype.hasOwnProperty.call(want, k) ? want[k] : ABSENT;
      const g = Object.prototype.hasOwnProperty.call(got, k) ? got[k] : ABSENT;
      const d = firstDifference(w, g, here + "." + k);
      if (d) return d;
    }
    return null;
  }
  return { path: here || "(root)", want: want, got: got };
}

/** Do two decoded vectors agree, by assert.deepStrictEqual? */
function same(a, b) {
  try { assert.deepStrictEqual(a, b); return true; } catch (e) { return false; }
}

// ── recording ────────────────────────────────────────────────────────────────
/** A recorder that calls functions on a CLONE of the arguments and notes what happened.
 *  `add(id, fnName, fn, args)`: `fn` is called with a structured clone of `args`, so a function that
 *  mutates its input cannot spoil the next vector, and `mut` records that it did. */
function makeRecorder() {
  const vectors = [];
  const ids = new Set();
  function add(id, fnName, fn, args) {
    if (ids.has(id)) throw new Error("duplicate vector id " + id);
    ids.add(id);
    const before = JSON.stringify(encode(args, id + ".args"));
    const live = structuredClone(args);
    const v = { id: id, fn: fnName, args: args };
    try {
      v.out = fn.apply(null, live);
    } catch (e) {
      v.threw = (e && e.name) || "Error";
    }
    if (JSON.stringify(encode(live, id + ".args")) !== before) v.mut = true;
    vectors.push(v);
    return v;
  }
  return { vectors: vectors, add: add };
}

/** The golden as text: one vector per line, so a changed answer is a changed line in the diff. */
function serialize(doc) {
  const lines = doc.vectors.map((v) => JSON.stringify(encode(v, v.id)));
  return '{"meta":' + JSON.stringify(doc.meta) + ',"vectors":[\n' + lines.join(",\n") + "\n]}\n";
}

/** A golden read back from its file, vectors decoded into real values. */
function load(file) {
  const raw = JSON.parse(fs.readFileSync(file, "utf8"));
  return { meta: raw.meta, vectors: raw.vectors.map(decode) };
}

// ── comparing ────────────────────────────────────────────────────────────────
/** What differs between a golden and a fresh recording, as a list of problems (empty = none).
 *  Vectors are matched by id, so a recipe that gained or lost one is told apart from an answer
 *  that moved. */
function compare(golden, live, opts) {
  const limit = (opts && opts.limit) || 5;
  const problems = [];
  if (golden.meta.recipe_version !== live.meta.recipe_version) {
    problems.push("recipe_version is " + golden.meta.recipe_version + " in the golden but " +
      live.meta.recipe_version + " in the generator: the INPUTS changed, so regenerate the golden.");
  }
  const byId = new Map(golden.vectors.map((v) => [v.id, v]));
  const liveIds = new Set(live.vectors.map((v) => v.id));
  const gone = golden.vectors.filter((v) => !liveIds.has(v.id)).map((v) => v.id);
  const fresh = live.vectors.filter((v) => !byId.has(v.id)).map((v) => v.id);
  if (gone.length) problems.push(gone.length + " vector(s) in the golden are no longer made, first: " + gone[0]);
  if (fresh.length) problems.push(fresh.length + " vector(s) are made now that the golden does not hold, first: " + fresh[0]);
  if (golden.meta.n !== golden.vectors.length) {
    problems.push("the golden says n=" + golden.meta.n + " but holds " + golden.vectors.length + " vectors");
  }

  const differing = [];
  for (const l of live.vectors) {
    const g = byId.get(l.id);
    if (!g) continue;
    if (!same(g, l)) differing.push({ g: g, l: l });
  }
  if (differing.length) {
    problems.push(differing.length + " of " + live.vectors.length + " vectors answer differently now:");
    for (const d of differing.slice(0, limit)) {
      const diff = firstDifference(d.g, d.l) || { path: "(root)", want: d.g, got: d.l };
      problems.push("  " + d.l.id + "   " + d.l.fn + "(" + showArgs(d.l.args) + ")\n" +
        "      at " + diff.path + ": golden " + show(diff.want) + ", now " + show(diff.got));
    }
    if (differing.length > limit) problems.push("  ... and " + (differing.length - limit) + " more");
  }
  return problems;
}

// ── a generator's main() ─────────────────────────────────────────────────────
/** The command line every generator shares.
 *  spec: {script, generator, recipeVersion, build(frontendDir, add)} where build calls
 *  add(id, fnName, fn, args) once per vector. */
function main(spec, argv) {
  const args = argv.slice(2);
  const frontend = args[0];
  if (!frontend || frontend.startsWith("--")) {
    console.error("usage: node " + spec.script + " <frontend-dir> [--write <file> --commit <sha> | --compare <file>]");
    process.exit(2);
  }
  const flag = (name) => { const i = args.indexOf(name); return i < 0 ? null : args[i + 1]; };

  const rec = makeRecorder();
  spec.build(frontend, rec.add);
  const live = { meta: { recipe_version: spec.recipeVersion, n: rec.vectors.length }, vectors: rec.vectors };

  const compareTo = flag("--compare");
  if (compareTo) {
    const golden = load(compareTo);
    const limit = flag("--limit") === null ? undefined : Number(flag("--limit"));
    const problems = compare(golden, live, { limit: limit });
    if (problems.length) {
      console.log("GOLDEN MASTER MISMATCH against " + spec.generator + " (" + frontend + ")");
      problems.forEach((p) => console.log(p));
      console.log("If this change is intended, regenerate with:\n  node " + spec.script + " <frontend-dir> --write " +
        compareTo + " --commit <sha>\nand review the fixture diff line by line.");
      process.exit(1);
    }
    console.log(JSON.stringify({ ok: true, n: live.vectors.length }));
    return;
  }

  const meta = { commit: flag("--commit") || "", recipe_version: spec.recipeVersion, n: rec.vectors.length,
                 generator: spec.generator };
  const text = serialize({ meta: meta, vectors: rec.vectors });
  const writeTo = flag("--write");
  if (writeTo) {
    if (!/^[0-9a-f]{40}$/.test(meta.commit)) {
      console.error("--write needs --commit <the 40-character sha of the origin/staging export it was cut from>");
      process.exit(2);
    }
    fs.writeFileSync(writeTo, text);
    console.log(JSON.stringify({ wrote: writeTo, n: rec.vectors.length }));
    return;
  }
  process.stdout.write(text);
}

module.exports = {
  encode, decode, firstDifference, same, makeRecorder, serialize, load, compare, main, show, showArgs,
};
