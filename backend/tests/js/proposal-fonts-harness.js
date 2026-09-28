"use strict";
/* The proposal-font loader, EXECUTED: frontend/js/proposal-fonts.js run as the browser runs it, with
 * the refit hook lifted out of proposal-review.js beside it.
 *
 * Hanz, 2026-09-26: "why are the fonts and font sizes still not fixed?" The editor named Zetta
 * Serif and never loaded it, so it drew Georgia. The loader fetches the licensed files from behind
 * the login and registers them with the FontFace API; the page re-fits every box once they are in.
 *
 * WHY THIS RUNS THE CODE. What matters is behaviour across awaits: that nothing is fetched before
 * the token exists, that both faces are constructed from the bytes (not a URL) under the families
 * and descriptors the files really carry, that the refit runs exactly once, and that every failure
 * path ends in one console warning rather than a rejection. None of that is visible in the source.
 *
 * STUBBED, NOT LIFTED: fetch (answers from the font files the test hands it -- synthetic ones, since
 * the licensed files are in neither git nor CI -- by the public name in the URL), FontFace (records
 * its arguments; load() resolves only for bytes that start with an OpenType signature), document.fonts, and the page's two refit collaborators,
 * scheduleRepaginate and fitNotesBox, which have their own harnesses.
 *
 * Usage: node proposal-fonts-harness.js <frontend-dir> <json {publicName: absolutePath}>
 *        -> one line of JSON
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const crypto = require("crypto");

const FRONTEND = process.argv[2];
const FILES = JSON.parse(process.argv[3]);
const LOADER = fs.readFileSync(path.join(FRONTEND, "js", "proposal-fonts.js"), "utf8");
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");

function region(from, to) {
  const i = SRC.indexOf(from);
  if (i < 0) throw new Error("the block anchored on " + JSON.stringify(from) + " is gone");
  const j = SRC.indexOf(to, i);
  if (j < 0) throw new Error("the block no longer ends at " + JSON.stringify(to));
  return SRC.slice(i, j);
}
// The refit and the one line that hands it to the loader, whole.
const HOOK = region("  // THE PROPOSAL'S TYPEFACE ARRIVES AFTER THE FIRST PAINT",
                    "  // The Word-faithful view:");

const unhandled = [];
process.on("unhandledRejection", (r) => unhandled.push(String(r && r.message || r)));

const sha = (buf) => crypto.createHash("sha256").update(Buffer.from(buf)).digest("hex");
const tick = () => new Promise((r) => setImmediate(r));
async function settle(n) { for (let i = 0; i < (n || 8); i++) await tick(); }

function toArrayBuffer(buf) {
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

/** One page load. `answer(name)` -> {status, bytes} | "reject". */
function world(opts) {
  const o = Object.assign({
    answer: (name) => ({ status: 200, bytes: fs.readFileSync(FILES[name]) }),
    faceLoad: (bytes) => bytes.slice(0, 4).toString("latin1") === "OTTO",
    token: "tok-123",
    tokenGate: Promise.resolve(),
    fontFace: true,
  }, opts || {});
  const log = { fetches: [], faces: [], added: [], warns: [], errors: [],
                repaginate: [], fit: 0, directRepaginate: 0 };

  class FontFace {
    constructor(family, source, descriptors) {
      const isAB = Object.prototype.toString.call(source) === "[object ArrayBuffer]";
      const bytes = isAB ? Buffer.from(source) : Buffer.alloc(0);
      this.family = family;
      this.status = "unloaded";
      this._bytes = bytes;
      log.faces.push({ family: family, arrayBuffer: isAB, sha: isAB ? sha(bytes) : null,
                       sourceType: typeof source,
                       descriptors: JSON.parse(JSON.stringify(descriptors || {})) });
    }
    load() {
      if (o.faceLoad(this._bytes)) { this.status = "loaded"; return Promise.resolve(this); }
      this.status = "error";
      return Promise.reject(new Error("A network error occurred."));   // what Chromium says
    }
  }

  const sandbox = {
    console: {
      warn: (...a) => log.warns.push(a.map(String).join(" ")),
      error: (...a) => log.errors.push(a.map(String).join(" ")),
      log: () => {},
    },
    TWAuth: { tokenReady: o.tokenGate, ready: o.tokenGate, token: () => o.token },
    TW: { resolveApiBase: () => "" },
    document: { fonts: { add: (ff) => log.added.push({ family: ff.family, status: ff.status }) } },
    fetch: (url, init) => {
      const m = /^\/api\/proposal-font\/([^?]+)\?v=(.+)$/.exec(url);
      log.fetches.push({ url: url, name: m && m[1], v: m && m[2],
                         auth: init && init.headers && init.headers.Authorization,
                         credentials: init && init.credentials });
      const a = o.answer(m ? m[1] : "");
      if (a === "reject") return Promise.reject(new TypeError("Failed to fetch"));
      return Promise.resolve({
        ok: a.status >= 200 && a.status < 300,
        status: a.status,
        arrayBuffer: () => Promise.resolve(toArrayBuffer(a.bytes)),
      });
    },
    // The page's refit collaborators. repaginateTerms is here only to prove it is NOT called
    // directly: the terms pager has to go through scheduleRepaginate, which waits out a caret.
    scheduleRepaginate: (delay) => log.repaginate.push(delay),
    fitNotesBox: () => { log.fit++; },
    repaginateTerms: () => { log.directRepaginate++; },
    Promise: Promise,
    setTimeout: setTimeout,
  };
  if (o.fontFace) sandbox.FontFace = FontFace;
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(LOADER, sandbox, { filename: "proposal-fonts.js" });
  vm.runInContext(HOOK, sandbox, { filename: "proposal-review.js#refit-hook" });
  return { sandbox: sandbox, log: log };
}

function summary(w) {
  const L = w.log;
  return {
    fetches: L.fetches, faces: L.faces, added: L.added, warns: L.warns, errors: L.errors,
    repaginate: L.repaginate, fit: L.fit, directRepaginate: L.directRepaginate,
    api: Object.keys(w.sandbox.TWProposalFonts || {}).sort(),
    version: w.sandbox.TWProposalFonts && w.sandbox.TWProposalFonts.VERSION,
  };
}

/** The page's own hook starts the load, and nothing else awaits it -- exactly as in the browser,
 *  where a rejection from the loader would be an unhandled one. Only after it has settled does the
 *  harness ask start() for its value (the same promise, so no second load). */
async function outcome(w) {
  try { return await w.sandbox.TWProposalFonts.start(); }
  catch (err) { return "rejected: " + String(err && err.message || err); }
}

async function scenario(opts, after) {
  const w = world(opts);
  await settle();
  const out = summary(w);
  out.ok = await outcome(w);
  if (after) Object.assign(out, await after(w));
  return out;
}

(async () => {
  const out = {};
  const bookName = Object.keys(FILES).find((n) => /book/.test(n));

  out.ok = await scenario({}, async (w) => {
    // A second registrant AFTER the load: runs once, from the fonts already in, with no reload.
    let late = 0;
    w.sandbox.TWProposalFonts.whenLoaded(() => { late++; });
    await settle();
    const again = await outcome(w);
    await settle();
    return { late: late, fetchesAfterLate: w.log.fetches.length, fitAfterLate: w.log.fit,
             startAgain: again };
  });

  // Nothing is fetched before the token exists (the /api/default-notes 401 race, #124).
  {
    let open;
    const gate = new Promise((r) => { open = r; });
    const w = world({ tokenGate: gate });
    await settle();
    const before = w.log.fetches.length;
    open();
    await settle();
    out.gated = { before: before, after: w.log.fetches.length, fit: w.log.fit };
  }

  out.unauthorized = await scenario({ answer: () => ({ status: 401, bytes: Buffer.from('{"ok":false}') }) });
  out.offline = await scenario({ answer: () => "reject" });
  out.badBytes = await scenario({ faceLoad: () => false });
  out.partial = await scenario({
    answer: (name) => name === bookName
      ? { status: 401, bytes: Buffer.from("{}") }
      : { status: 200, bytes: fs.readFileSync(FILES[name]) },
  });
  out.noFontFace = await scenario({ fontFace: false });
  out.noToken = await scenario({ token: null });

  await settle();
  out.unhandled = unhandled;
  process.stdout.write(JSON.stringify(out) + "\n");
})().catch((err) => {
  process.stderr.write(String(err && err.stack || err) + "\n");
  process.exit(1);
});
