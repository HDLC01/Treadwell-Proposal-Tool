"use strict";
/* A FAKE BROWSER WITH A PAGE LIFECYCLE, for harnesses that must run the real pages ACROSS a navigation.
 *
 * WHY THIS EXISTS. X1 (the v2 board's "New estimate", walked on staging 59922bd, 2026-10-21) is a fact about
 * what a browser does when a page is left, and no harness in this folder could say it:
 *
 *   * polish-intake-harness.js lifts functions out of the page and hands them a stub `TW` whose flushState()
 *     is a counter, so a PUT, its reply and the call that is made when the reply arrives are all missing.
 *   * draft-sync-harness.js and publish-race-harness.js run the real shared.js, but with ONE page and a
 *     fetch that answers at once, so nothing is ever in flight when the page goes.
 *
 * The bug lives between those two. Continue called save() and then location.assign() at once, so the
 * draft's first PUT was sent by shared.js's pagehide handler (keepalive), and its reply went to a page that
 * no longer existed: the `.then` that files a new project under Test never ran. A model that cannot lose a
 * reply cannot show that. This one can, and it is deliberately small:
 *
 *   TIME is virtual. One clock (createSim) runs every timer and every request in order, and between two
 *   events it lets every promise settle, so an interleaving is the same on every run and costs no wall time.
 *
 *   A PAGE is a window around the real scripts, run with `new Function` (one realm, so `instanceof` means
 *   what it means in a browser). Its timers die with it. A navigation is TWO steps, as in a browser:
 *   location.assign() asks for the new document, and the old page keeps running (its timers fire, its
 *   replies arrive) until that document commits, `commitMs` later. Then `pagehide` runs on the old page,
 *   the old page is gone, and `bootMs` after that the new page's scripts run.
 *
 *   STORAGE EVENTS. A write to localStorage is announced to every OTHER page that is still running, a task later, as a `storage` event
 *   (world.load gives each page its own view of the one store). { storageEvents: false } is a browser that does not deliver them.
 *
 *   TABS. One browser has ONE localStorage and one clock; each tab has its own sessionStorage and its own page, which a navigation in
 *   that tab replaces (world.openTab, world.load(url, { tab }), world.pageOf(kind, tab)). Two tabs share the one current draft and
 *   the one blob, as two tabs of a browser do.
 *
 *   A REQUEST takes `up` to reach the server, `proc` (per route) to be worked on, and `down` to come back.
 *   Once it has ARRIVED the server finishes it whatever happens to the page, which is what a server does
 *   with a request it has read. What happens to the page decides only three things: a request that has not
 *   arrived when its page goes is dropped unless it was sent with keepalive; a reply that comes back to a
 *   page that has gone is never seen by anyone; and a reply that comes back to a page that is still
 *   running, even one that has asked to leave, is. One more browser rule is modelled, because it is why a
 *   save sent as a page goes cannot be relied on for a big draft: a keepalive request whose body is over
 *   64 KiB, or that would take the keepalive bodies its page already has in flight over 64 KiB between them
 *   (the limit is one budget, not one allowance each), is refused on the spot (TypeError: Failed to fetch)
 *   and nothing is sent. The size is the body's UTF-8 bytes, as the browser counts it, not its `.length`.
 *
 *   THE SERVER is the route contract of backend/main.py, nothing more: GET /api/draft/{id} (200, or 404
 *   when the row does not exist), PUT /api/draft/{id} (an upsert that INSERTS a new row as sent, so a first
 *   save carrying is_test creates the row already filed, and keeps a server-owned key the stored row has, as
 *   drafts.save_draft does with keep_server_owned), POST /api/draft/{id}/test (sets is_test; 200 with
 *   {"ok": true, "existed": false} when there is no row), and GET /api/condition-defaults. Each row remembers
 *   what its first save said (`born`), because "was it ever on the board unfiled" is a fact about its birth. It can be told
 *   to fail a route (`fault`): an HTTP 500, a 200 carrying {"ok": false} (which is how both /test and
 *   the save route answer a caught exception), a network error, no answer at all, a 200 that is not JSON
 *   (a proxy's error page), a 200 that says the row is not there ({"ok": true, "existed": false}) and a request the
 *   server is merely slow over ("slow", `ms` more), so that one request can finish after a later one, and a request that is slow to REACH it
 *   ("slowup", `ms` more on the way up), which a page that goes before it has arrived takes with it, and one whose
 *   answer is slow to come back ("slowdown", `ms` more on the way down: the server has the request, its page has not heard).
 *
 * WHAT IS REAL. The page scripts (shared.js, js/polish-sandbox.js, js/polish-intake.js, and js/index.js, the
 * live intake) and the modules they read (work-types, intake-scope, bid-model, excel-math): every one is read
 * from the frontend directory the harness is given and run unchanged, and so is the body of js/projects.js's
 * "+ New project" click handler (world.pressNewProject lifts it out of the file and runs it), js/portal.js's
 * startNewProposal (world.pressNewProposal) and js/v2-board.js's startNew (world.startNewEstimate). WHAT IS NOT:
 * the DOM (a permissive tree of nodes, enough for these pages), the network, the address lookup index.js
 * mounts (a no-op), and two pages that are only as much of themselves as the facts need. The estimate page is
 * a copy of the first lines of polish-estimate.js's init() (see openEstimate): the real file is 5,000 lines of
 * calculator, and the part that decides a fork is the sandbox call it makes (test_polish_beta_sandbox.py pins
 * that order in the real file). The "review" page (the spreadsheet's Estimate step) is shared.js plus one
 * write when it loads, as estimate-review.js writes the draft as it loads.
 *
 * Usage: const W = require("./_world.js"); const world = W.createWorld({ frontend: "<dir>" });
 */
const fs = require("fs");
const path = require("path");
const L = require("./_lib.js");

const ORIGIN = "https://proposals.test";
const KEYS = {
  state: "treadwell.proposal_tool.state",
  draftId: "treadwell.proposal_tool.draft_id",
  guard: "treadwell.proposal_tool.hydrated_once",
  // The PREFIX of a project's start: each project's own key is `<intent>:<id>` (world.startOf, world.setStart, world.starts). The bare
  // key is the one slot of an earlier version, which nothing reads now; the model still reports it (report().intent).
  intent: "treadwell.proposal_tool.new_is_test",
  synced: "treadwell.proposal_tool.synced",
};
// Mirror of drafts._SERVER_OWNED_KEYS. test_v2_new_estimate_test_flag.py compares the two.
const SERVER_OWNED = ["is_test", "archived", "assigned_estimator", "scope_group",
  "proposal_of", "estimate_digest", "estimate_synced_at"];
const KEEPALIVE_CAP = 64 * 1024;

const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));
const flush = () => new Promise((resolve) => setImmediate(resolve));
const read = (file) => fs.readFileSync(file, "utf8").replace(/^\uFEFF/, "");

// ── time ─────────────────────────────────────────────────────────────────────────────────────────────────
function createSim() {
  let seq = 0;
  let queue = [];
  const sim = {
    now: 0,
    /** Run `fn` `delay` virtual ms from now. Returns a handle for cancel(). */
    at(delay, fn) {
      const ev = { t: sim.now + Math.max(0, delay), n: seq++, fn: fn, live: true };
      queue.push(ev);
      queue.sort((a, b) => a.t - b.t || a.n - b.n);
      return ev;
    },
    cancel(ev) { if (ev) ev.live = false; },
    idle() { return !queue.some((e) => e.live); },
    /** Move the clock forward `ms`, running every event on the way in order, and letting every promise
     *  settle after each one (a page's `await` continues before the next event happens). */
    async advance(ms) {
      const until = sim.now + ms;
      await flush();
      for (;;) {
        queue = queue.filter((e) => e.live);
        const next = queue[0];
        if (!next || next.t > until) break;
        queue.shift();
        next.live = false;
        sim.now = next.t;
        next.fn();
        await flush();
      }
      sim.now = until;
    },
    /** Run until nothing is left to happen, or `capMs` have passed (a page that re-arms a timer for ever). */
    async settle(capMs) {
      const stop = sim.now + (capMs || 120000);
      await flush();                  // a page that has just loaded has not asked for anything yet
      for (;;) {
        queue = queue.filter((e) => e.live);
        if (!queue.length || queue[0].t > stop) break;
        await sim.advance(Math.max(0, queue[0].t - sim.now));
      }
    },
  };
  return sim;
}

// ── storage ──────────────────────────────────────────────────────────────────────────────────────────────
function createStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(String(k), String(v)); },
    removeItem: (k) => { m.delete(k); },
    clear: () => m.clear(),
    dump: () => Object.fromEntries(m),
  };
}

// ── the DOM: only as much as these pages touch ───────────────────────────────────────────────────────────
function textNode(text) { return { isText: true, textContent: String(text) }; }

function makeNode(tag) {
  const listeners = {};
  let own = "";
  let markup = "";
  const n = {
    tagName: String(tag || "div").toUpperCase(),
    id: "", name: "", type: "", value: "", checked: false, hidden: false, className: "",
    style: {}, dataset: {}, children: [], elements: [], attrs: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    removeEventListener(type, fn) { listeners[type] = (listeners[type] || []).filter((f) => f !== fn); },
    /** Not a DOM method: deliver an event to this node's listeners, as the browser does. */
    fire(type, evt) {
      const e = Object.assign({ type: type, target: n, preventDefault() {}, stopPropagation() {} }, evt || {});
      (listeners[type] || []).slice().forEach((fn) => fn.call(n, e));
      return e;
    },
    appendChild(c) { n.children.push(c); return c; },
    append() { Array.prototype.forEach.call(arguments, (c) => n.children.push(typeof c === "string" ? textNode(c) : c)); },
    replaceChildren() { n.children = []; },
    remove() {},
    insertAdjacentHTML() {},
    setAttribute(k, v) { n.attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(n.attrs, k) ? n.attrs[k] : null; },
    hasAttribute(k) { return Object.prototype.hasOwnProperty.call(n.attrs, k); },
    removeAttribute(k) { delete n.attrs[k]; },
    // `[name='x']` / `[name="x"]` over the form's controls, which is the one selector the intake asks a form.
    querySelector(sel) {
      const m = /^\[name=['"]([^'"]+)['"]\]$/.exec(sel);
      return m ? (n.elements.filter((e) => e.name === m[1])[0] || null) : null;
    },
    querySelectorAll() { return []; },
    closest() { return null; },
    focus() {}, blur() {}, select() {},
  };
  // As in a DOM: setting the text replaces whatever markup the node held, and setting the markup replaces the text; the text of a node
  // that holds only markup is that markup without its tags (so a button given back its markup reads as its words again).
  Object.defineProperty(n, "innerHTML", {
    get() { return markup; },
    set(v) { markup = String(v); own = ""; n.children = []; },
  });
  Object.defineProperty(n, "textContent", {
    get() {
      if (!(markup && !own && !n.children.length)) return own + n.children.map((c) => c.textContent).join("");
      let t = markup, prev;
      do { prev = t; t = t.replace(/<[^>]*>/g, ""); } while (t !== prev);
      return t;
    },
    set(v) { n.children = []; own = String(v); markup = ""; },
  });
  return n;
}

/** The form's controls, read out of the REAL polish-intake.html (or index.html, the live intake), so the names a
 *  save reads are the page's own. */
function formControls(html, file) {
  const from = html.indexOf('<form id="intake-form">');
  const to = html.indexOf("</form>", from);
  if (from < 0 || to < 0) throw new Error("#intake-form is gone from " + file + ": retarget _world.js");
  const attr = (tag, k) => {
    const m = new RegExp("\\s" + k + '="([^"]*)"').exec(tag);
    return m ? m[1] : null;
  };
  const controls = (html.slice(from, to).match(/<(?:input|select|textarea)\b[^>]*>/g) || []).map((tag) => {
    const c = makeNode(/^<(\w+)/.exec(tag)[1]);
    c.name = attr(tag, "name") || "";
    c.type = attr(tag, "type") || (/^<select/.test(tag) ? "select-one" : "text");
    c.value = attr(tag, "value") || "";
    c.checked = /\schecked\b/.test(tag);
    return c;
  }).filter((c) => c.name);
  if (controls.length < 15) throw new Error("only " + controls.length + " named controls in #intake-form of " + file + ": retarget _world.js");
  return controls;
}

/** What the server holds of a draft's `is_test`, as the Projects page reads it: true, false, or null for "nobody has said". */
const flagOf = (data) => (Object.prototype.hasOwnProperty.call(data, "is_test") && data.is_test !== undefined ? data.is_test : null);

// ── the world ────────────────────────────────────────────────────────────────────────────────────────────
function createWorld(cfg) {
  const o = Object.assign({}, cfg || {});
  if (!o.frontend) throw new Error("createWorld needs { frontend }");
  const frontend = path.resolve(o.frontend);
  const net = Object.assign({ up: 20, down: 20, commitMs: 150, bootMs: 120 }, o.net);
  const procMs = Object.assign({ GET: 10, PUT: 40, TEST: 40, COND: 10 }, o.proc);
  const sim = createSim();
  const local = createStorage();
  // TABS. One browser has ONE localStorage and one clock, and each tab has its own sessionStorage (shared.js keeps its reload
  // guard and its "this draft was adopted blind" mark there) and its own page, which a navigation in that tab replaces. A world
  // starts with one tab; world.openTab() adds another, and world.load(url, { tab }) puts a page in it.
  const tabs = [];
  const openTab = () => { const t = { n: tabs.length + 1, session: createStorage(), page: null }; tabs.push(t); return t; };
  const mainTab = openTab();
  const session = mainTab.session;

  const world = {
    sim, local, session, net, procMs, frontend, tabs, mainTab, openTab,
    rows: new Map(), faults: [], requests: [], pages: [], navs: [], console: [], unmocked: [],
    current: null,
  };
  let uuids = 0;
  let pageCount = 0;
  let reqCount = 0;
  const stamp = () => new Date(Date.UTC(2026, 9, 21, 15, 0, 0) + sim.now).toISOString();

  // ── the server ─────────────────────────────────────────────────────────────────────────────────────────
  function routeOf(req) {
    const path = String(req.url).split("?")[0];
    let m = /^\/api\/draft\/([^/]+)\/test$/.exec(path);
    if (m && req.method === "POST") return { route: "TEST", id: decodeURIComponent(m[1]) };
    m = /^\/api\/draft\/([^/]+)$/.exec(path);
    if (m && req.method === "GET") return { route: "GET", id: decodeURIComponent(m[1]) };
    if (m && (req.method === "PUT" || req.method === "POST")) return { route: "PUT", id: decodeURIComponent(m[1]) };
    if (path === "/api/condition-defaults" && req.method === "GET") return { route: "COND" };
    return { route: "OTHER" };
  }

  /** The fault that applies to this request, if any, used up as it is handed out. A fault names a route ("GET",
   *  "PUT" or "TEST"), optionally one draft id, and how many requests it spoils (all of them when it says nothing). */
  function faultFor(req) {
    for (const f of world.faults) {
      if (f.used >= f.times) continue;
      if (f.route !== req.route) continue;
      if (f.id && f.id !== req.id) continue;
      f.used++;
      return f;
    }
    return null;
  }

  /** The work a route does, at the moment the server finishes it. Returns { status, body }. */
  function handle(req) {
    const row = world.rows.get(req.id);
    if (req.route === "GET") {
      if (!row) return { status: 404, body: { detail: "Draft not found" } };
      return { status: 200, body: { ok: true, id: req.id, data: clone(row.data), created_at: row.created_at, updated_at: row.updated_at } };
    }
    if (req.route === "PUT") {
      const data = clone(JSON.parse(req.body).data);
      if (row) {
        // drafts.save_draft(keep_server_owned=True): the stored value of a server-owned key wins.
        SERVER_OWNED.forEach((k) => { if (Object.prototype.hasOwnProperty.call(row.data, k)) data[k] = row.data[k]; });
        row.data = data;
        row.updated_at = stamp();
      } else {
        // INSERTED AS SENT (drafts.save_draft's else branch): a row is born with whatever is_test its first save
        // carries. `born` is the fact the fix is about: a project that is ever on the board unfiled was born unfiled.
        world.rows.set(req.id, { data: data, created_at: stamp(), updated_at: stamp(),
                                 born: { at: sim.now, is_test: flagOf(data) }, flips: [] });
      }
      return { status: 200, body: { ok: true, id: req.id, updated_at: stamp() } };
    }
    if (req.route === "TEST") {
      const want = req.body ? JSON.parse(req.body).is_test !== false : true;
      // A flip is a CHANGE: a filing that finds the row already filed that way changes nothing.
      if (row) { if (flagOf(row.data) !== want) row.flips.push({ at: sim.now, from: flagOf(row.data), to: want }); row.data.is_test = want; }
      return { status: 200, body: { ok: true, existed: !!row, is_test: want } };
    }
    if (req.route === "COND") return { status: 200, body: { ok: true, conditions: [] } };
    world.unmocked.push(req.method + " " + req.url);
    return { status: 404, body: { detail: "the harness has no route for this" } };
  }

  /** Put a row on the server without going through a page (a project that already exists). */
  world.seed = (id, data) => {
    world.rows.set(id, { data: clone(data), created_at: stamp(), updated_at: stamp(),
                         born: { at: sim.now, is_test: flagOf(data) }, flips: [] });
  };
  /** Fail a route. { route: "PUT"|"GET"|"TEST", mode: "http500"|"okfalse"|"network"|"hang"|"html"|"gone"|"slow"|"slowup"|"slowdown", id?, times?, ms? }
   *  ("slow" does not fail it: the server takes `ms` longer over the requests it is handed to, and answers them as usual). */
  world.fault = (spec) => { world.faults.push(Object.assign({ times: Infinity, used: 0 }, spec)); };

  // ── fetch, per page ────────────────────────────────────────────────────────────────────────────────────
  function makeFetch(page) {
    return function fetch(url, init) {
      const opts = init || {};
      const req = Object.assign(routeOf({ url: String(url), method: String(opts.method || "GET").toUpperCase() }), {
        n: ++reqCount, page: page, url: String(url), method: String(opts.method || "GET").toUpperCase(),
        body: opts.body === undefined ? null : String(opts.body), keepalive: opts.keepalive === true,
        sentAt: sim.now, outcome: "sent", status: null,
      });
      world.requests.push(req);
      // A keepalive request is refused on the spot, with "TypeError: Failed to fetch" and nothing sent, when its body is over
      // 64 KiB, and ALSO when it and the keepalive bodies its page already has in flight add up to more than that: the limit is
      // one budget shared by every keepalive request in flight (the fetch spec's inflightKeepaliveBytes), not one allowance each.
      // The first is the case the real drafts hit (shared.js putDraft measured a real bid at about 89 KB); the second is what two
      // saves sent as a page goes do to a draft of half that size. It is why a save sent as a page goes cannot be relied on for a
      // big draft, and why one page must send ONE.
      if (req.keepalive && req.body !== null) {
        const size = Buffer.byteLength(req.body, "utf8");
        if (size > KEEPALIVE_CAP) {
          req.outcome = "refused (keepalive body over 64 KiB)";
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        if (page.keepaliveBytes + size > KEEPALIVE_CAP) {
          req.outcome = "refused (keepalive bodies in flight over 64 KiB)";
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        page.keepaliveBytes += size;
        req.heldBytes = size;
      }
      // The budget comes back when the request is over (answered, or lost to the network), not before: a request that never
      // answers holds its share.
      const release = () => { if (req.heldBytes) { page.keepaliveBytes -= req.heldBytes; req.heldBytes = 0; } };
      return new Promise((resolve, reject) => {
        const fault = faultFor(req);
        // "slowup": the request is slow to REACH the server (a poor uplink), `ms` more than usual: a page that goes before it has
        // arrived takes a plain request with it.
        sim.at(net.up + (fault && fault.mode === "slowup" ? fault.ms : 0), () => {
          // Not there yet when its page went: a plain request dies with the page, a keepalive one does not.
          if (page.dead && !req.keepalive) { req.outcome = "aborted"; return; }
          if (fault && fault.mode === "network") {
            req.outcome = "network error";
            release();
            if (!page.dead) reject(new TypeError("Failed to fetch"));
            return;
          }
          req.arrivedAt = sim.now;
          if (fault && fault.mode === "hang") { req.outcome = "hung"; return; }
          // "slow": the server takes `ms` longer over THIS request, so a later one can finish first (a request that is handed a
          // fault says which: `times`, `id`).
          sim.at((procMs[req.route] === undefined ? 10 : procMs[req.route]) + (fault && fault.mode === "slow" ? fault.ms : 0), () => {
            let res;
            if (fault && fault.mode === "http500") res = { status: 500, body: { detail: "boom" } };
            else if (fault && fault.mode === "okfalse") res = { status: 200, body: { ok: false, error: "Couldn't do that. Please try again." } };
            else if (fault && fault.mode === "html") res = { status: 200, body: undefined };
            else if (fault && fault.mode === "gone") res = { status: 200, body: { ok: true, existed: false, is_test: true } };
            else res = handle(req);
            req.doneAt = sim.now;
            req.status = res.status;
            // "slowdown": the answer is slow to come BACK, `ms` more (the server has stored the request; its page has not heard yet).
            sim.at(net.down + (fault && fault.mode === "slowdown" ? fault.ms : 0), () => {
              release();
              if (page.dead) { req.outcome = "reply dropped"; return; }
              req.outcome = "replied";
              req.repliedAt = sim.now;
              resolve({
                ok: res.status >= 200 && res.status < 300, status: res.status, statusText: String(res.status),
                json: async () => {
                  if (res.body === undefined) throw new SyntaxError("Unexpected token '<', \"<html>\" is not valid JSON");
                  return clone(res.body);
                },
                text: async () => (res.body === undefined ? "<html>bad gateway</html>" : JSON.stringify(res.body)),
              });
            });
          });
        });
      });
    };
  }

  // ── a page ─────────────────────────────────────────────────────────────────────────────────────────────
  function kindOf(pathname) {
    if (pathname === "/polish-intake.html") return "intake";
    if (pathname === "/polish-estimate.html") return "estimate";
    // The LIVE intake (index.html + js/index.js), where "+ New project" on the Projects page lands.
    if (pathname === "/" || pathname === "/index.html") return "v1intake";
    // The spreadsheet's Estimate step. It writes the draft as it loads, so it is shared.js plus one write.
    if (pathname === "/estimate-review.html") return "review";
    // A page that runs shared.js and nothing else (the Projects page, which has not saved anything).
    if (pathname === "/projects.html") return "plain";
    if (pathname === "/blank.html") return "blank";
    throw new Error("the harness has no page for " + pathname);
  }

  function makeWindow(page) {
    const winListeners = {};
    const docListeners = {};
    const nodes = {};
    const doc = {
      head: makeNode("head"), body: makeNode("body"), documentElement: makeNode("html"),
      readyState: "complete", cookie: "", activeElement: null, hidden: false,
      getElementById(id) { return nodes[id] || (nodes[id] = Object.assign(makeNode("div"), { id: id })); },
      createElement: (tag) => makeNode(tag),
      createTextNode: (t) => textNode(t),
      querySelector: () => null, querySelectorAll: () => [],
      addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
      removeEventListener() {},
    };
    page.nodes = nodes;
    const location = {
      get href() { return page.url; },
      get origin() { return ORIGIN; },
      get pathname() { return new URL(page.url).pathname; },
      get search() { return new URL(page.url).search; },
      get hash() { return new URL(page.url).hash; },
      assign(u) { world.navigate(page, u); },
      replace(u) { world.navigate(page, u); },
      reload() { world.navigate(page, page.url); },
    };
    const history = { replaceState(_s, _t, u) { if (u) page.url = new URL(String(u), page.url).href; }, pushState() {} };
    const timers = new Map();
    let timerSeq = 0;
    // THIS PAGE'S VIEW OF THE BROWSER'S ONE localStorage. A write through it is announced to every OTHER page that is still running, as a
    // `storage` event (never to the page that wrote it, and only when the value changed, as the browser does it), a task later. A page that
    // has gone hears nothing. A world made with { storageEvents: false } is a browser that does not deliver them (a tab the browser has
    // frozen, a page restored from the back/forward cache), which is the case the server's word has to cover.
    const announce = (key, oldValue, newValue) => {
      if (o.storageEvents === false || oldValue === newValue) return;
      world.pages.forEach((p) => {
        if (p === page || p.dead) return;
        sim.at(0, () => {
          if (p.dead) return;
          (p.winListeners.storage || []).slice().forEach((fn) => {
            try { fn({ type: "storage", key: key, oldValue: oldValue, newValue: newValue, storageArea: p.win.localStorage }); }
            catch (e) { world.console.push({ page: p.label, level: "error", text: "storage handler threw: " + e }); }
          });
        });
      });
    };
    const pageLocal = {
      getItem: (k) => local.getItem(k),
      setItem(k, v) { const old = local.getItem(k); local.setItem(k, v); announce(String(k), old, String(v)); },
      removeItem(k) { const old = local.getItem(k); local.removeItem(k); announce(String(k), old, null); },
      clear() { Object.keys(local.dump()).forEach((k) => pageLocal.removeItem(k)); },
      dump: () => local.dump(),
    };
    const win = {
      document: doc, location, history, localStorage: pageLocal, sessionStorage: page.tab.session,
      crypto: { randomUUID: () => "est-" + (++uuids) },
      fetch: makeFetch(page),
      setTimeout(fn, ms) {
        const id = ++timerSeq;
        timers.set(id, sim.at(ms || 0, () => { timers.delete(id); if (!page.dead) fn(); }));
        return id;
      },
      clearTimeout(id) { sim.cancel(timers.get(id)); timers.delete(id); },
      addEventListener(type, fn) { (winListeners[type] = winListeners[type] || []).push(fn); },
      removeEventListener() {},
      console: {
        log() {}, info() {}, debug() {},
        warn() { world.console.push({ page: page.label, level: "warn", text: Array.prototype.map.call(arguments, String).join(" ") }); },
        error() { world.console.push({ page: page.label, level: "error", text: Array.prototype.map.call(arguments, String).join(" ") }); },
      },
    };
    win.window = win;
    win.self = win;
    page.winListeners = winListeners;
    page.docListeners = docListeners;
    return win;
  }

  const PARAMS = ["window", "document", "localStorage", "sessionStorage", "fetch", "location", "history",
    "setTimeout", "clearTimeout", "console", "crypto", "TW"];

  /** Run a script of the frontend as a browser would: a classic script, with the page's own globals. */
  function runScript(page, rel) {
    const src = read(path.join(frontend, rel));
    const win = page.win;
    const fn = new Function(...PARAMS, src + "\n//# sourceURL=" + rel);
    fn(win, win.document, win.localStorage, win.sessionStorage, win.fetch, win.location, win.history,
       win.setTimeout, win.clearTimeout, win.console, win.crypto, win.TW);
  }
  const mod = (rel) => require(path.join(frontend, rel));

  /** Load a page: a new document in `opts.tab` (the first tab when none is named). `opts.standIn` marks a page that only stands for one
   *  the model does not run (the board that starts a project): its leaving is not a fact about the flow under test, so it is not
   *  recorded in `navs`. */
  world.load = (urlString, opts) => {
    const u = new URL(urlString, ORIGIN);
    const tab = (opts && opts.tab) || mainTab;
    const page = { n: ++pageCount, url: u.href, kind: kindOf(u.pathname), dead: false, leaving: false, bornAt: sim.now,
                   diedAt: null, settled: null, settledAt: null, tab: tab, keepaliveBytes: 0, standIn: !!(opts && opts.standIn) };
    page.label = page.kind + "#" + page.n;
    tab.page = page;
    page.win = makeWindow(page);
    world.pages.push(page);
    world.current = page;
    const win = page.win;

    // A blank page runs no scripts: it is a window to put requests and timers on, for the model's own checks.
    const sandboxed = page.kind === "intake" || page.kind === "estimate";
    if (page.kind !== "blank") {
      runScript(page, "shared.js");
      if (sandboxed || page.kind === "v1intake") win.TWWorkTypes = mod("js/work-types.js");
      if (page.kind === "intake") win.TWBidModel = mod("js/bid-model.js");
      if (page.kind === "intake" || page.kind === "v1intake") win.TWIntakeScope = mod("js/intake-scope.js");
      // The address lookup (js/address-lookup.js) is a convenience that needs a real DOM, and index.js calls it unasked.
      if (page.kind === "v1intake") win.TWAddress = { mount() {} };
      if (sandboxed) runScript(page, "js/polish-sandbox.js");
    }

    if (page.kind === "intake") {
      const html = read(path.join(frontend, "polish-intake.html"));
      const form = makeNode("form");
      form.id = "intake-form";
      form.elements = formControls(html, "polish-intake.html");
      page.nodes["intake-form"] = form;
      // The Continue button as the page ships it (its label is what a disabled-and-relabelled button must give back).
      const btn = /<button\b[^>]*\bid="continue-btn"[^>]*>([^<]*)<\/button>/.exec(html);
      if (btn) { const b = makeNode("button"); b.id = "continue-btn"; b.textContent = btn[1]; page.nodes["continue-btn"] = b; }
      runScript(page, "js/polish-intake.js");
    }
    if (page.kind === "v1intake") {
      const html = read(path.join(frontend, "index.html"));
      const form = makeNode("form");
      form.id = "intake-form";
      form.elements = formControls(html, "index.html");
      page.nodes["intake-form"] = form;
      // The beta door ("Continue with Estimating Tool v2") as the page ships it: its markup is what it must give back.
      const door = /<button\b[^>]*\bid="beta-continue"[^>]*>([\s\S]*?)<\/button>/.exec(html);
      if (door) { const b = makeNode("button"); b.id = "beta-continue"; b.innerHTML = door[1].trim(); page.nodes["beta-continue"] = b; }
      runScript(page, "js/index.js");
    }
    if (page.kind === "review") {
      // estimate-review.js writes the draft as it loads (a county, a tab order, the price lines); one write stands for them.
      (async () => {
        try { await win.TW.draftReady; } catch (e) { /* the page carries on */ }
        win.TW.setState({ review_opened: true });
      })();
    }
    if (page.kind === "estimate") openEstimate(page);

    // The page as a person drives it.
    page.el = (id) => win.document.getElementById(id);
    page.form = page.nodes["intake-form"] || null;
    page.control = (name) => {
      const c = page.form && page.form.elements.filter((e) => e.name === name)[0];
      if (!c) throw new Error("no control named " + name + " on " + page.label);
      return c;
    };
    /** Type into a named box: the value changes, then `input` reaches the form, as it does in a browser. */
    page.type = (name, value) => {
      const c = page.control(name);
      c.value = String(value);
      page.form.fire("input", { target: c });
    };
    /** Press Continue (or Enter in a box): the form's own submit handlers. A disabled Continue does nothing, and neither
     *  does Enter in a box while it is disabled (a form whose default button is disabled is not submitted implicitly), so
     *  a press that finds it disabled answers false and the page is never asked. */
    page.pressContinue = () => {
      const btn = page.nodes["continue-btn"];
      if (btn && btn.disabled) return false;
      page.form.fire("submit", {});
      return true;
    };
    /** Press the live intake's "Continue with Estimating Tool v2" (the beta door): its own click handler. A disabled button does
     *  nothing, and a press that finds it disabled answers false. */
    page.pressBetaDoor = () => {
      const b = page.nodes["beta-continue"];
      if (!b) throw new Error("no beta door on " + page.label);
      if (b.disabled) return false;
      b.fire("click");
      return true;
    };
    /** The beta door as a person sees it right now: disabled or not, what it says while it works (textContent), and its markup. */
    page.betaDoor = () => {
      const b = page.nodes["beta-continue"];
      return b ? { disabled: !!b.disabled, saying: b.textContent, html: b.innerHTML } : null;
    };
    /** Click a link: the browser is sent to `href`. */
    page.follow = (href) => world.navigate(page, href);
    page.text = (id) => page.el(id).textContent;
    page.draftId = () => win.TW.getDraftId();
    return page;
  };

  /** The first lines of polish-estimate.js init(): wait for shared.js to settle the draft, adopt what is
   *  stored, and let the sandbox decide which draft this page may write to, BEFORE anything else. That
   *  decision is the whole of what this harness needs the estimate page for (see the header). */
  function openEstimate(page) {
    const win = page.win;
    const adopt = () => {};                         // the real page rebuilds its model here; this one has none
    (async () => {
      try { if (win.TWAuth && win.TWAuth.ready) await win.TWAuth.ready; } catch (e) { /* none here */ }
      try { await win.TW.draftReady; } catch (e) { /* the page carries on */ }
      adopt(win.TW.getState());
      page.settled = await win.TWPolishSandbox.enterSandbox(adopt);
      page.settledAt = sim.now;
    })().catch((e) => { page.crashed = String(e && e.stack || e); });
  }

  // ── navigation ─────────────────────────────────────────────────────────────────────────────────────────
  /** location.assign() / a link: ask for the new document. The old page keeps running until it commits. */
  world.navigate = (page, href) => {
    if (page.dead || page.leaving) return;
    const target = new URL(String(href), page.url).href;
    // A browser that does not go (the load was stopped, a prompt was answered no): the page is still there, as it was.
    if (world.navigationBlocked) {
      if (!page.standIn) world.navs.push({ from: page.label, to: target, askedAt: sim.now, blocked: true, syncedAtAsk: local.getItem(KEYS.synced) });
      return;
    }
    page.leaving = true;
    // `syncedAtAsk`: the browser's record of what the server holds (SYNCED_KEY) at the moment the page asked to leave.
    if (!page.standIn) world.navs.push({ from: page.label, to: target, askedAt: sim.now, syncedAtAsk: local.getItem(KEYS.synced) });
    sim.at(net.commitMs, () => {
      if (page.dead) return;
      // pagehide runs on a page that still exists, and what it sends goes out as it goes.
      (page.winListeners.pagehide || []).slice().forEach((fn) => {
        try { fn({ type: "pagehide", persisted: false }); }
        catch (e) { world.console.push({ page: page.label, level: "error", text: "pagehide threw: " + e }); }
      });
      page.dead = true;
      page.diedAt = sim.now;
      if (world.current === page) world.current = null;
      // A page that keeps asking for itself (shared.js's hydrate-and-reload, with something else claiming the
      // slot each time) must show up in the report as a fact, not as a run that never ends.
      if (pageCount >= (o.maxPages || 30)) { world.runaway = true; return; }
      sim.at(net.bootMs, () => { world.load(target, { tab: page.tab }); });
    });
  };

  // ── what a test does ───────────────────────────────────────────────────────────────────────────────────
  world.advance = (ms) => sim.advance(ms);
  world.settle = (capMs) => sim.settle(capMs);
  world.now = () => sim.now;
  world.localKey = (k) => local.getItem(KEYS[k] || k);

  /** The v2 board's "+ New estimate", executed: the REAL startNew of js/v2-board.js, lifted out of the file and run on a page that has
   *  shared.js loaded (the board's own page is not modelled), with `opts.gc` as the board's TAB (the GC tab leaves { audience: "GC" }
   *  in the fresh draft; the Direct tab leaves nothing). It clears what makes shared.js mint a new draft id, records what the project is
   *  started as, and sends the browser to the v2 intake with no ?d=. `opts.tab` is the browser tab it is pressed in (the first by
   *  default). Resolves with the intake page once it has booted, with the clock run on to the end, unless `opts.hold` (ms) says to
   *  step it that much past the intake's boot instead: another tab's timers (a queued save) are then left where they are, which is what
   *  a person's second click does. (It used to copy what startNew did, so a line added to startNew was never run here.) */
  world.startNewEstimate = async (opts) => {
    const tab = (opts && opts.tab) || mainTab;
    const src = L.read(path.join(frontend, "js", "v2-board.js"));
    const fn = L.liftSource(src, "startNew", { where: "js/v2-board.js" });
    const page = world.load("/projects.html", { tab, standIn: true });
    await world.advance(0);                                     // shared.js settles which draft the page is on
    const win = page.win;
    new Function("window", "TW", "localStorage", "sessionStorage", "TAB", fn + "\nstartNew();")(
      win, win.TW, win.localStorage, win.sessionStorage, opts && opts.gc ? "gc" : "direct");
    const blobAtStart = world.blob();                           // as the press leaves it, before any time passes
    await (opts && opts.hold ? world.advance(net.commitMs + net.bootMs + opts.hold) : world.settle());
    const intake = world.pageOf("intake", tab);
    if (intake) intake.blobAtStart = blobAtStart;
    return intake;
  };

  /** The v2 intake opened by a BARE link (a bookmark, or the address typed) on a project nobody started: the browser's current draft is whatever
   *  shared.js mints, and nothing says what it is started as (the board's New estimate leaves a start; this leaves none). It is the flow in which
   *  the v2 page's OWN word ("this page created the project": TW.startsAsTest) is the only thing that can say a project is a test. `opts.gc`
   *  leaves { audience: "GC" } in the draft, `opts.tab` is the browser tab, `opts.hold` as for startNewEstimate. */
  world.openBareV2Intake = async (opts) => {
    const tab = (opts && opts.tab) || mainTab;
    local.removeItem(KEYS.state);
    local.removeItem(KEYS.draftId);
    tab.session.removeItem(KEYS.guard);
    if (opts && opts.gc) local.setItem(KEYS.state, JSON.stringify({ audience: "GC" }));
    const page = world.load("/polish-intake.html", { tab });
    await (opts && opts.hold ? world.advance(opts.hold) : world.settle());
    return page;
  };

  /** This browser has been working on a project: its blob is stored, stamped for the project, and is the
   *  draft the browser resumes. (What opening a project from the board looks like after the first visit.) */
  world.holdLocally = (id, data) => {
    local.setItem(KEYS.state, JSON.stringify(Object.assign({}, clone(data), { __draft_id: id })));
    local.setItem(KEYS.draftId, id);
  };

  /** Projects' "+ New project", executed: the REAL click handler of js/projects.js, lifted out of the file and run on a
   *  page that has shared.js loaded, with `tab` as the Projects page's CURRENT_FILTER ("test", "active", "all" or
   *  "inactive"). It clears the browser's own copy of the project, records which tab the click came from and sends the
   *  browser to the live intake ("/?new=1"). Resolves with the intake page once it has booted. */
  world.pressNewProject = async (opts) => {
    const tab = (opts && opts.tab) || "test";
    const browserTab = (opts && opts.browserTab) || mainTab;
    const src = read(path.join(frontend, "js", "projects.js"));
    const head = 'document.getElementById("new-project").addEventListener("click", (e) => {';
    const at = src.indexOf(head);
    if (at < 0) throw new Error("projects.js no longer starts a new project with a click handler on #new-project: retarget _world.js");
    const open = at + head.length - 1;
    const body = src.slice(open + 1, L.balanced(src, open));
    const step = () => (opts && opts.hold ? world.advance(opts.hold) : world.settle());
    const page = world.load("/projects.html", { tab: browserTab });
    await step();
    const win = page.win;
    new Function("CURRENT_FILTER", "window", "TW", "localStorage", "sessionStorage", "e", body)(
      tab, win, win.TW, win.localStorage, win.sessionStorage, { preventDefault() {} });
    await step();
    return world.pageOf("v1intake", browserTab);
  };

  /** The Direct and GC boards' "+ New proposal", executed: the REAL startNewProposal of js/portal.js, lifted out of the file and
   *  run on a page that has shared.js loaded, with `opts.tab` as the board's TAB ("test" or "active": the only two that draw the
   *  button) and `opts.pipeline` as its PIPELINE ("gc" or "direct"). From the GC board it leaves { audience: "GC" } in the fresh
   *  draft; either way it records which tab the click came from and sends the browser to the live intake ("/?new=1").
   *  `opts.browserTab` is the browser tab it is pressed in. Resolves with the intake page once it has booted. */
  world.pressNewProposal = async (opts) => {
    const board = (opts && opts.tab) || "test";
    const pipeline = (opts && opts.pipeline) || "direct";
    const browserTab = (opts && opts.browserTab) || mainTab;
    const src = L.read(path.join(frontend, "js", "portal.js"));
    const fn = L.liftSource(src, "startNewProposal", { where: "js/portal.js" });
    const page = world.load("/projects.html", { tab: browserTab });
    await world.settle();
    const win = page.win;
    new Function("window", "TW", "localStorage", "sessionStorage", "PIPELINE", "TAB", fn + "\nstartNewProposal();")(
      win, win.TW, win.localStorage, win.sessionStorage, pipeline, board);
    await world.settle();
    return world.pageOf("v1intake", browserTab);
  };

  /** The blob this browser holds for the project it is on, as stored. */
  world.blob = () => { try { return JSON.parse(local.getItem(KEYS.state) || "{}"); } catch (e) { return null; } };

  /** The most recent page of a kind (in `tab`, when one is named). */
  world.pageOf = (kind, tab) => world.pages.filter((p) => p.kind === kind && (!tab || p.tab === tab)).pop() || null;

  /** What this browser holds of how a project was STARTED: the value under its own key ("1" a test, "0" a real bid, null when
   *  nothing is pending for it). Every project has its own key, so no other project's start can touch it. */
  world.startOf = (id) => local.getItem(KEYS.intent + ":" + id);
  /** Put a start under a project's own key, as the Projects page or a board leaves one ("1" a test, "0" a real bid). */
  world.setStart = (id, value) => { local.setItem(KEYS.intent + ":" + id, value); };
  /** Every start this browser holds, { id: "1" | "0" }. */
  world.starts = () => {
    const out = {};
    const dump = local.dump();
    Object.keys(dump).forEach((k) => { if (k.indexOf(KEYS.intent + ":") === 0) out[k.slice(KEYS.intent.length + 1)] = dump[k]; });
    return out;
  };

  /** A row as the Projects page would read it: is_test is true, false, or null for "nobody has said". `bornIsTest` is what
   *  the row's FIRST save said (a project that is ever on the board unfiled was born unfiled), `flips` how many times a
   *  filing request changed it afterwards. */
  world.row = (id) => {
    const r = world.rows.get(id);
    if (!r) return null;
    const d = r.data;
    return {
      is_test: flagOf(d),
      bornIsTest: r.born.is_test,
      flips: r.flips.length,
      beta_sandbox_of: d.beta_sandbox_of || null,
      project_name: d.project_name === undefined ? null : d.project_name,
    };
  };

  /** What a save said about the project's filing: the is_test its body carried (true, false, or null for "nothing"). */
  const sentFlag = (r) => {
    if (r.route !== "PUT" || !r.body) return undefined;
    try { return flagOf(JSON.parse(r.body).data || {}); } catch (e) { return undefined; }
  };

  /** One field of the draft a save carried (undefined when the request was not a save, or did not say it). */
  const sentField = (r, key) => {
    if (r.route !== "PUT" || !r.body) return undefined;
    try { return (JSON.parse(r.body).data || {})[key]; } catch (e) { return undefined; }
  };

  world.requestsLog = () => world.requests.map((r) => ({
    n: r.n, at: r.sentAt, page: r.page.label, route: r.route, method: r.method, id: r.id || null,
    keepalive: r.keepalive, outcome: r.outcome, status: r.status, sentIsTest: sentFlag(r),
    // The size of the body, as characters (what `.length` says) and as UTF-8 bytes (what the browser counts against its limit).
    chars: r.body === null ? 0 : r.body.length, bytes: r.body === null ? 0 : Buffer.byteLength(r.body, "utf8"),
    // What the save said the project's name and address were: the data a stale page can empty (PUTs only).
    sentName: sentField(r, "project_name"), sentAddress: sentField(r, "address"),
    arrivedAt: r.arrivedAt === undefined ? null : r.arrivedAt, doneAt: r.doneAt === undefined ? null : r.doneAt,
    repliedAt: r.repliedAt === undefined ? null : r.repliedAt,
  }));

  world.pageReport = (page) => page && {
    label: page.label, url: page.url, bornAt: page.bornAt, diedAt: page.diedAt, settled: page.settled,
    settledAt: page.settledAt, crashed: page.crashed || null,
    draftId: page.win.TW ? page.win.TW.getDraftId() : null,
    note: page.nodes["sandbox-note"] ? page.nodes["sandbox-note"].textContent : "",
    noteHidden: page.nodes["sandbox-note"] ? page.nodes["sandbox-note"].hidden : true,
    loading: page.nodes["loading"] ? page.nodes["loading"].textContent : "",
  };

  world.report = () => ({
    now: sim.now,
    rows: Object.fromEntries(Array.from(world.rows.keys()).sort().map((id) => [id, world.row(id)])),
    requests: world.requestsLog(),
    intent: local.getItem(KEYS.intent),
    starts: world.starts(),
    synced: local.getItem(KEYS.synced),
    blob: world.blob(),
    storedDraftId: local.getItem(KEYS.draftId),
    navs: world.navs.slice(),
    pages: world.pages.map(world.pageReport),
    console: world.console.slice(),
    unmocked: world.unmocked.slice(),
    runaway: !!world.runaway,
  });

  return world;
}

module.exports = { createWorld, KEYS, SERVER_OWNED, ORIGIN };
