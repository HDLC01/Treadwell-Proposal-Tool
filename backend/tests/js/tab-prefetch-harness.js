"use strict";
/* A PROPOSAL TAB OPENS ON ITS DRAFT READ AHEAD (Hanz, 2026-10-27: "can we make the switching of the proposals tabs more
 * efficient? like pre loading"). shared.js, RUN WHOLE, over a thin fake browser: one localStorage and one sessionStorage
 * shared by every page load of the tab, a server holding rows with their `updated_at`, and a page load that is a fresh run
 * of the script over those storages (a reload is one more).
 *
 * What it shows: prefetchDraft reads a draft once per page and never this page's own; the next page runs on the kept read
 * with no reload, holding its saves until the server says the read is still its copy; a read that went stale is replaced
 * by the server's copy and nothing is saved over it; a blocked sessionStorage, an expired read, or a blob with unsaved work
 * leaves the ordinary open (read, write, reload) as it was. `timing` measures one tab switch both ways against a server
 * whose every round trip takes RT ms.
 *
 * Usage: node tab-prefetch-harness.js <frontend-dir>  ->  one line of JSON
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2] || path.join(__dirname, "..", "..", "..", "frontend"));
const SHARED = L.read(path.join(ROOT, "shared.js"));
const quoted = (re, what) => /"([^"]+)"/.exec(L.grab(SHARED, re, what))[1];
const STAMP = quoted(/const STAMP\s*=\s*"[^"]+"/, "STAMP");
const STATE_KEY = quoted(/const STATE_KEY\s*=\s*"[^"]+"/, "STATE_KEY");
const UNVERIFIED = "treadwell.proposal_tool.unverified";
const KEPT = "treadwell.proposal_tool.prefetched";
const clone = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const ticks = async (n) => { for (let i = 0; i < (n || 8); i++) await sleep(0); };

function store(blocked) {
  const m = new Map();
  const no = () => { throw new Error("SecurityError: storage is blocked"); };
  return blocked ? { getItem: no, setItem: no, removeItem: no, m }
    : { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k), m };
}

/** One browser tab against one server. `o.rt`: ms per round trip (0: answered at once). `o.blockedSession`. */
function tab(o) {
  o = o || {};
  const local = store(false);
  const session = store(!!o.blockedSession);
  const rows = {};
  let n = 0;
  const stamp = () => "2026-10-28T10:00:" + String(++n).padStart(2, "0") + "+00:00";
  const log = { gets: [], puts: [], reloads: 0, warns: [], loads: 0 };
  const holds = {};      // id -> a promise its GET waits for
  let failGets = false;
  const rt = o.rt || 0;
  const wire = () => (rt ? sleep(rt) : Promise.resolve());
  const fetchFn = async (url, init) => {
    const method = (init && init.method) || "GET";
    const id = decodeURIComponent(String(url).split("/api/draft/")[1] || "").split(/[/?]/)[0];
    await wire();
    if (method === "GET") {
      log.gets.push(id);
      if (holds[id]) await holds[id].p;
      if (failGets) return { ok: false, status: 500, json: async () => ({}) };
      const row = rows[id];
      if (!row) return { ok: false, status: 404, json: async () => ({ ok: false }) };
      return { ok: true, status: 200, json: async () => ({ ok: true, id, data: clone(row.data), updated_at: row.updated_at }) };
    }
    const body = JSON.parse(init.body);
    log.puts.push([id, body.data]);
    rows[id] = { data: body.data, updated_at: stamp() };
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  };

  /** One page load of /proposal-review.html?d=<id>. `auth`: ms to the token and to the profile. */
  function load(id) {
    log.loads++;
    let href = "https://proposals.example.com/proposal-review.html?d=" + id;
    const page = { reloaded: false };
    const loc = {
      get href() { return href; }, set href(v) { href = String(v); },
      origin: "https://proposals.example.com", pathname: "/proposal-review.html",
      get search() { return "?" + href.split("?")[1]; },
      reload() { log.reloads++; page.reloaded = true; }, assign(h) { href = String(h); }, replace(h) { href = String(h); },
    };
    const token = rt ? sleep(rt) : Promise.resolve();              // /api/public-config, then the session
    const ready = token.then(() => (rt ? sleep(rt) : null));        // ... then /api/me
    const win = {
      location: loc, history: { replaceState(a, b, u) { if (u) href = String(u); } },
      addEventListener() {}, removeEventListener() {}, crypto: { randomUUID: () => "minted-0000" },
      TWAuth: { tokenReady: token, ready }, setTimeout, clearTimeout,
    };
    const doc = { addEventListener() {}, removeEventListener() {}, readyState: "complete", querySelectorAll: () => [],
                  querySelector: () => null, getElementById: () => null,
                  createElement: () => ({ setAttribute() {}, appendChild() {}, style: {}, classList: { add() {}, remove() {} } }),
                  head: { appendChild() {} }, body: { appendChild() {}, removeChild() {} }, cookie: "" };
    const con = { log() {}, info() {}, warn: (...a) => log.warns.push(a.join(" ")), error: (...a) => log.warns.push(a.join(" ")) };
    new Function("window", "document", "localStorage", "sessionStorage", "fetch", "location", "console", SHARED)(
      win, doc, local, session, fetchFn, loc, con);
    // What a page script's module-top snapshot reads, in the same synchronous run (`const state = TW.getState()`).
    page.TW = win.TW;
    page.snapshot = clone(win.TW.getState());
    page.ready = ready;
    return page;
  }

  /** Open draft `id` the way the browser does: a load, and the reload it asks for, until a page stays. */
  async function open(id) {
    let p = load(id);
    await p.TW.draftReady;
    while (p.reloaded) { p = load(id); await p.TW.draftReady; }
    return p;
  }

  function hold(id) {
    let release;
    const p = new Promise((r) => { release = r; });
    holds[id] = { p, release: () => { delete holds[id]; release(); } };
    return holds[id].release;
  }

  const blob = () => { try { return JSON.parse(local.getItem(STATE_KEY) || "null"); } catch (e) { return null; } };
  const kept = (id) => (session.m.has(KEPT + ":" + id) ? JSON.parse(session.m.get(KEPT + ":" + id)) : null);
  return { local, session, rows, log, load, open, hold, blob, kept, stamp, setFail: (v) => { failGets = v; } };
}

/** A tab on Base Bid 1 (A), with Base Bid 2 (B) on the server: A opened (read, reload) and in step with the server. */
async function onA(o) {
  const t = tab(o);
  t.rows.A = { data: { project_name: "Gym", work_type: "epoxy", scope_notes: "A's words" }, updated_at: t.stamp() };
  t.rows.B = { data: { project_name: "Gym", work_type: "polish", scope_notes: "B's words", proposal_of: "A" }, updated_at: t.stamp() };
  const a = await t.open("A");
  return { t, a };
}

const out = {};

async function main() {
  // 1. ONCE PER DRAFT, NEVER THIS ONE: a second ask is the first one's read; this page's own draft is not read.
  {
    const { t, a } = await onA();
    const g0 = t.log.gets.length;
    const p1 = a.TW.prefetchDraft("B");
    const p2 = a.TW.prefetchDraft("B");
    const self = await a.TW.prefetchDraft("A");
    const first = await p1;
    await p2;
    out.once = { kept: first, samePromise: p1 === p2, self, gets: t.log.gets.slice(g0),
                 keptVersion: (t.kept("B") || {}).version || null, rowVersion: t.rows.B.updated_at };
  }

  // 2. THE KEPT READ OPENS THE PAGE: no reload, the page's snapshot is B's, saves held until the server says the read is
  //    still its copy, then what was typed meanwhile is saved.
  {
    const { t, a } = await onA();
    await a.TW.prefetchDraft("B");
    const r0 = t.log.reloads, g0 = t.log.gets.length, l0 = t.log.loads;
    const release = t.hold("B");
    const b = t.load("B");
    const atLoad = { snapshot: b.snapshot, blocked: b.TW.saveBlocked(), keptLeft: t.kept("B") !== null };
    b.TW.setState({ scope_notes: "typed while it was asked" });
    await ticks();
    const flushedEarly = await b.TW.flushState();
    const putsWhileAsked = t.log.puts.filter((p) => p[0] === "B").length;
    release();
    await b.TW.draftReady;
    const after = { blocked: b.TW.saveBlocked(), unverified: t.session.m.get(UNVERIFIED) || null };
    const flushed = await b.TW.flushState();
    out.hit = { atLoad, flushedEarly, putsWhileAsked, after, flushed,
                puts: t.log.puts.filter((p) => p[0] === "B").map((p) => p[1].scope_notes),
                reloads: t.log.reloads - r0, loads: t.log.loads - l0, gets: t.log.gets.slice(g0),
                server: t.rows.B.data.scope_notes };
  }

  // 3. A READ THAT WENT STALE: somebody saved B after it was read ahead. The page opened on the old read, but nothing it
  //    wrote reaches the server; the server's copy replaces it and the page reloads onto that.
  {
    const { t, a } = await onA();
    await a.TW.prefetchDraft("B");
    t.rows.B = { data: Object.assign({}, t.rows.B.data, { scope_notes: "Kyle's newer words" }), updated_at: t.stamp() };
    const r0 = t.log.reloads;
    const release = t.hold("B");
    const b = t.load("B");
    b.TW.setState({ scope_notes: "typed on the old read" });
    release();
    await b.TW.draftReady;
    await b.TW.flushState();
    out.stale = { snapshot: b.snapshot.scope_notes, reloads: t.log.reloads - r0,
                  puts: t.log.puts.filter((p) => p[0] === "B").length, server: t.rows.B.data.scope_notes,
                  local: (t.blob() || {}).scope_notes, stamp: (t.blob() || {})[STAMP] };
    const again = await t.open("B");
    out.stale.reopened = { snapshot: again.snapshot.scope_notes, reloads: t.log.reloads - r0, blocked: again.TW.saveBlocked() };
  }

  // 4. A BLOCKED sessionStorage: nothing is kept, nothing throws, and the tab opens the ordinary way.
  {
    const { t, a } = await onA({ blockedSession: true });
    let threw = false, kept = null;
    try { kept = await a.TW.prefetchDraft("B"); } catch (e) { threw = true; }
    const r0 = t.log.reloads;
    const b = await t.open("B");
    out.blocked = { threw, kept, reloads: t.log.reloads - r0, snapshot: b.snapshot.scope_notes, blocked: b.TW.saveBlocked() };
  }

  // 5. UNSAVED WORK IN THE BLOB: the kept read is not used, the ordinary open (which saves that work first) runs.
  {
    const { t, a } = await onA();
    await a.TW.prefetchDraft("B");
    t.local.setItem(STATE_KEY, JSON.stringify(Object.assign(t.blob(), { scope_notes: "A, typed and not yet saved" })));
    const r0 = t.log.reloads;
    const b1 = t.load("B");
    const first = { snapshot: b1.snapshot[STAMP], keptLeft: t.kept("B") !== null };
    await b1.TW.draftReady;
    const b = b1.reloaded ? await t.open("B") : b1;
    out.unsaved = Object.assign(first, { reloads: t.log.reloads - r0, aSaved: t.rows.A.data.scope_notes,
                                         snapshotAfter: b.snapshot.scope_notes });
  }

  // 6. AN OLD READ (over ten minutes): not used.
  {
    const { t, a } = await onA();
    await a.TW.prefetchDraft("B");
    const k = t.kept("B");
    k.at -= 11 * 60 * 1000;
    t.session.m.set(KEPT + ":B", JSON.stringify(k));
    const r0 = t.log.reloads;
    const b1 = t.load("B");
    out.expired = { snapshot: b1.snapshot[STAMP] || null };
    await b1.TW.draftReady;
    out.expired.reloads = t.log.reloads - r0;
  }

  // 7. THE SERVER CANNOT BE ASKED: the page stays on the read, its saves stay refused, nothing reloads.
  {
    const { t, a } = await onA();
    await a.TW.prefetchDraft("B");
    t.setFail(true);
    const r0 = t.log.reloads;
    const b = t.load("B");
    b.TW.setState({ scope_notes: "typed, unconfirmed" });
    await b.TW.draftReady;
    await b.TW.flushState();
    out.unreachable = { reloads: t.log.reloads - r0, blocked: b.TW.saveBlocked(), puts: t.log.puts.filter((p) => p[0] === "B").length,
                        snapshot: b.snapshot.scope_notes };
  }

  // 8. TIMING: one tab switch, A -> B, at RT ms a round trip (the sign-in token is one, the profile one more, a draft one).
  //    "The page is ready" = the page that stays has its draft settled and its sign-in done, which is when the proposal
  //    page starts its own template, notes and strip requests.
  {
    const RT = 40;
    const time = async (prefetch) => {
      const { t, a } = await onA({ rt: RT });
      if (prefetch) await a.TW.prefetchDraft("B");
      const g0 = t.log.gets.length, l0 = t.log.loads;
      const t0 = Date.now();
      let p = t.load("B");
      await p.TW.draftReady;
      while (p.reloaded) { p = t.load("B"); await p.TW.draftReady; }
      await p.ready;
      const ms = Date.now() - t0;
      return { ms, rts: Math.round(ms / RT), loads: t.log.loads - l0, gets: t.log.gets.length - g0, on: p.snapshot.scope_notes };
    };
    out.timing = { rt: RT, before: await time(false), after: await time(true) };
  }

  console.log(JSON.stringify(out));
}

main().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
