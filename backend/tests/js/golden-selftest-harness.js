"use strict";
/* Run the golden-master toolkit (_golden.js) against inputs built to fool it.
 *
 * A golden master is only worth having if it cannot be fooled by the things JSON hides. So each
 * block below states the way a comparison goes wrong and what the toolkit must say instead:
 * 0 against -0, NaN against NaN, a field that is `undefined` against a field that is missing,
 * a function that starts (or stops) mutating its argument, a recipe that gained a vector.
 * The last block drives the real command line through a throwaway generator in a temp directory,
 * because the exit codes are what CI reads.
 *
 * Usage: node golden-selftest-harness.js   ->   one line of JSON
 */
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const G = require("./_golden");

const out = {};
const threw = (f) => { try { f(); } catch (e) { return String(e && e.message); } return null; };
const roundTrip = (v) => G.decode(JSON.parse(JSON.stringify(G.encode(v))));

// ── the codec ────────────────────────────────────────────────────────────────
{
  const back = roundTrip([-0, 0, NaN, Infinity, -Infinity, undefined, 1.5e-7, 1e21, "x", null, true,
    { a: undefined, b: [NaN, -0], c: { d: Infinity } }]);
  out.codec = {
    negativeZeroSurvives: Object.is(back[0], -0),
    positiveZeroStaysPositive: Object.is(back[1], 0),
    nan: Number.isNaN(back[2]),
    infinities: back[3] === Infinity && back[4] === -Infinity,
    undefinedInAnArray: back[5] === undefined && 5 in back,
    smallAndHuge: back[6] === 1.5e-7 && back[7] === 1e21,
    plain: back[8] === "x" && back[9] === null && back[10] === true,
    undefinedKeyKept: Object.prototype.hasOwnProperty.call(back[11], "a") && back[11].a === undefined,
    nested: Number.isNaN(back[11].b[0]) && Object.is(back[11].b[1], -0) && back[11].c.d === Infinity,
    // what JSON alone does to the same values: this is the hiding the codec exists to prevent
    jsonAloneHides: JSON.stringify([-0, NaN, Infinity, undefined, { a: undefined }]),
    encodedZero: JSON.stringify(G.encode(-0)),
    reservedKey: threw(function () { G.encode({ "$": 1 }); }),
    aFunction: threw(function () { G.encode({ f: function () {} }); }),
    aClassInstance: threw(function () { G.encode({ d: new Date(0) }); }),
    aNullPrototypeObject: threw(function () { G.encode({ o: Object.create(null) }); }),
    aHole: threw(function () { G.encode([1, , 3]); }),
    unknownTag: threw(function () { G.decode({ "$": "bogus" }); }),
  };
}

// ── deepStrictEqual semantics ────────────────────────────────────────────────
out.same = {
  zeroVsNegativeZero: G.same({ v: 0 }, { v: -0 }),
  nanVsNan: G.same({ v: NaN }, { v: NaN }),
  undefinedVsMissing: G.same({ a: 1, b: undefined }, { a: 1 }),
  arrayLength: G.same([1, 2], [1, 2, 3]),
  keyOrderDoesNotMatter: G.same({ a: 1, b: 2 }, { b: 2, a: 1 }),
  stringVsNumber: G.same({ v: "1" }, { v: 1 }),
  identical: G.same({ v: [1, { w: NaN }] }, { v: [1, { w: NaN }] }),
};

// ── first difference, in words ───────────────────────────────────────────────
function diff(a, b) {
  const d = G.firstDifference(a, b);
  return d ? { path: d.path, want: G.show(d.want), got: G.show(d.got) } : null;   // show() words (absent)
}
out.firstDifference = {
  none: diff({ a: [1, { b: 2 }] }, { a: [1, { b: 2 }] }),
  nested: diff({ out: { gp_pct: 0.45, total: 10 } }, { out: { gp_pct: 0.52, total: 10 } }),
  zero: diff({ out: { cost: 0 } }, { out: { cost: -0 } }),
  nan: diff({ v: NaN }, { v: 0 }),
  nanBothSides: diff({ v: NaN }, { v: NaN }),
  missingKey: diff({ a: 1, b: 2 }, { a: 1 }),
  extraKey: diff({ a: 1 }, { a: 1, z: 9 }),
  shorterArray: diff([1, 2, 3], [1, 2]),
  type: diff({ v: "1" }, { v: 1 }),
  undefinedVsAbsent: diff({ a: undefined }, {}),
  firstOfSeveral: diff({ a: 1, b: 2, c: 3 }, { a: 1, b: 9, c: 8 }),
};

// ── the recorder ─────────────────────────────────────────────────────────────
{
  const r = G.makeRecorder();
  const base = { n: 2 };
  r.add("double", "double", (o) => o.n * 2, [base]);
  r.add("mutates", "mutates", (o) => { o.n = 99; return o.n; }, [base]);
  r.add("throws", "throws", () => { throw new RangeError("a message that differs per node version"); }, []);
  r.add("returnsNegativeZero", "negz", (a, b) => a * b, [3, -0]);
  r.add("returnsUndefined", "undef", () => undefined, []);
  out.recorder = {
    vectors: r.vectors.map((v) => G.show(Object.assign({}, v))),
    argsKeptOriginal: base.n === 2,                       // the call ran on a clone
    mutatedFlagOnlyWhenTrue: r.vectors.map((v) => Object.prototype.hasOwnProperty.call(v, "mut")),
    threwHoldsTheNameOnly: r.vectors[2].threw === "RangeError" && !("out" in r.vectors[2]),
    duplicateId: threw(function () { r.add("double", "double", () => 1, []); }),
    undefinedOutKept: "out" in r.vectors[4] && r.vectors[4].out === undefined,
  };
}

// ── comparing two recordings ─────────────────────────────────────────────────
function recording(rows, version) {
  const r = G.makeRecorder();
  rows.forEach((x) => r.add(x.id, x.fn, x.f, x.args));
  return { meta: { recipe_version: version === undefined ? 1 : version, n: r.vectors.length }, vectors: r.vectors };
}
const A = [
  { id: "t/1", fn: "f", f: (x) => ({ total: x + 1, gp: 0.45 }), args: [1] },
  { id: "t/2", fn: "f", f: (x) => x * 0, args: [5] },
  { id: "t/3", fn: "f", f: (x) => x, args: [NaN] },
  { id: "t/4", fn: "f", f: (o) => o.k, args: [{ k: 1 }] },
];
{
  const golden = recording(A);
  const cases = {
    identical: recording(A),
    moved: recording([{ id: "t/1", fn: "f", f: (x) => ({ total: x + 1, gp: 0.52 }), args: [1] }, A[1], A[2], A[3]]),
    zeroBecameNegativeZero: recording([A[0], { id: "t/2", fn: "f", f: (x) => x * -0, args: [5] }, A[2], A[3]]),
    nanBecameZero: recording([A[0], A[1], { id: "t/3", fn: "f", f: () => 0, args: [NaN] }, A[3]]),
    // same answer as before, but it now writes into its argument: only `mut` says so
    startedMutating: recording([A[0], A[1], A[2],
      { id: "t/4", fn: "f", f: (o) => { const k = o.k; o.k = 2; return k; }, args: [{ k: 1 }] }]),
    lostAVector: recording([A[0], A[1], A[2]]),
    gainedAVector: recording(A.concat([{ id: "t/5", fn: "f", f: () => 1, args: [] }])),
    versionBumped: recording(A, 2),
  };
  // wrap the golden in file form so decode runs on it too
  const file = G.serialize({ meta: Object.assign({ commit: "" }, golden.meta), vectors: golden.vectors });
  const loaded = { meta: JSON.parse(file).meta, vectors: JSON.parse(file).vectors.map(G.decode) };
  out.compare = Object.fromEntries(Object.keys(cases).map((k) => [k, G.compare(loaded, cases[k])]));
  // the limit keeps a wall of failures readable
  const many = recording(Array.from({ length: 12 }, (_v, i) => ({ id: "m/" + i, fn: "f", f: () => i + 1, args: [] })));
  const manyMoved = recording(Array.from({ length: 12 }, (_v, i) => ({ id: "m/" + i, fn: "f", f: () => i + 2, args: [] })));
  out.compare.limited = G.compare({ meta: many.meta, vectors: many.vectors }, manyMoved, { limit: 3 });
  out.serializedShape = file.split("\n").length;          // header + one line per vector + footer
}

// ── a function that writes into its argument and returns nothing ─────────────
// setMeasurement is one: its whole effect is the rows it edits. `mut` says THAT it wrote and only
// `after` says WHAT, so a golden without `after` stays green when it starts writing something else.
{
  const writes = (m) => (rows) => { rows[0].m = m; };
  const one = (f) => recording([{ id: "w/1", fn: "write", f: f, args: [[{ m: 1 }]] }]);
  const golden = one(writes(5));
  const inFile = (rec) => {
    const text = G.serialize({ meta: Object.assign({ commit: "" }, rec.meta), vectors: rec.vectors });
    return { meta: JSON.parse(text).meta, vectors: JSON.parse(text).vectors.map(G.decode) };
  };
  const reads = G.makeRecorder();
  reads.add("reads", "read", (rows) => rows[0].m, [[{ m: 1 }]]);
  const kept = inFile(one(writes(-0))).vectors[0];
  out.inPlace = {
    recorded: G.show(golden.vectors[0]),
    afterOnlyWhenWritten: [golden.vectors[0], reads.vectors[0]].map((v) => Object.prototype.hasOwnProperty.call(v, "after")),
    sameWrite: G.compare(golden, one(writes(5))),
    wroteAnotherNumber: G.compare(golden, one(writes(6))),
    stoppedWriting: G.compare(golden, one(() => undefined)),
    negativeZeroWritten: G.compare(inFile(one(writes(-0))), one(writes(0))),
    negativeZeroSurvivesTheFile: Boolean(kept.after) && Object.is(kept.after[0][0].m, -0),
  };
}

// ── the command line, through a throwaway generator ──────────────────────────
{
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tw-golden-"));
  try {
    const gen = path.join(dir, "gen-demo.js");
    fs.writeFileSync(gen, [
      'const G = require(' + JSON.stringify(path.join(__dirname, "_golden.js")) + ');',
      'G.main({ script: "gen-demo.js", generator: "demo", recipeVersion: 1, build(frontend, add) {',
      '  const bump = require("fs").readFileSync(frontend + "/bump.txt", "utf8").trim();',
      '  add("a", "f", (x) => x * 2 + Number(bump), [3]);',
      '  add("b", "f", (x) => x * -0, [4]);',
      '} }, process.argv);',
    ].join("\n"));
    const front = path.join(dir, "frontend");
    fs.mkdirSync(front);
    fs.writeFileSync(path.join(front, "bump.txt"), "0");
    const run = (...a) => cp.spawnSync(process.execPath, [gen, front, ...a], { encoding: "utf8" });
    const file = path.join(dir, "demo.json");
    const sha = "0123456789abcdef0123456789abcdef01234567";
    const noCommit = run("--write", file);
    const wrote = run("--write", file, "--commit", sha);
    const okRun = run("--compare", file);
    fs.writeFileSync(path.join(front, "bump.txt"), "1");
    const badRun = run("--compare", file);
    const usage = cp.spawnSync(process.execPath, [gen], { encoding: "utf8" });
    out.cli = {
      writeNeedsACommit: noCommit.status,
      wroteStatus: wrote.status,
      fileStartsWith: fs.readFileSync(file, "utf8").slice(0, 12),
      fileMeta: JSON.parse(fs.readFileSync(file, "utf8")).meta,
      negativeZeroOnDisk: fs.readFileSync(file, "utf8").indexOf('{"$":"-0"}') >= 0,
      compareOkStatus: okRun.status,
      compareOkLine: okRun.stdout.trim(),
      compareBadStatus: badRun.status,
      compareBadMentionsId: badRun.stdout.indexOf("a   f(3)") >= 0,
      compareBadFirstLines: badRun.stdout.split("\n").slice(0, 4),
      compareBadMentionsPath: badRun.stdout.indexOf("at .out: golden 6, now 7") >= 0,
      compareBadSaysHowToRegenerate: badRun.stdout.indexOf("--write") >= 0,
      usageStatus: usage.status,
    };
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

console.log(JSON.stringify(out));
