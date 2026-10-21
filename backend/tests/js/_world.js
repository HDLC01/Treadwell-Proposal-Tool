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
 *   A REQUEST takes `up` to reach the server, `proc` (per route) to be worked on, and `down` to come back.
 *   Once it has ARRIVED the server finishes it whatever happens to the page, which is what a server does
 *   with a request it has read. What happens to the page decides only three things: a request that has not
 *   arrived when its page goes is dropped unless it was sent with keepalive; a reply that comes back to a
 *   page that has gone is never seen by anyone; and a reply that comes back to a page that is still
 *   running, even one that has asked to leave, is.
 *
 *   THE SERVER is the route contract of backend/main.py, nothing more: GET /api/draft/{id} (200, or 404
 *   when the row does not exist), PUT /api/draft/{id} (an upsert that keeps the server-owned keys, as
 *   drafts.save_draft does with keep_server_owned), POST /api/draft/{id}/test (sets is_test; 200 with
 *   {"ok": true, "existed": false} when there is no row), and GET /api/condition-defaults. It can be told
 *   to fail a route (`fault`): an HTTP 500, a 200 carrying {"ok": false} (which is how both /test and
 *   the save route answer a caught exception), a network error, no answer at all, a 200 that is not JSON
 *   (a proxy's error page) and a 200 that says the row is not there ({"ok": true, "existed": false}).
 *
 * WHAT IS REAL. The page scripts (shared.js, js/polish-sandbox.js, js/polish-intake.js) and the modules they
 * read (work-types, intake-scope, bid-model, excel-math): every one is read from the frontend directory the
 * harness is given and run unchanged. WHAT IS NOT: the DOM (a permissive tree of nodes, enough for these
 * pages), the network, and the estimate page, which is a copy of the first lines of polish-estimate.js's
 * init() (see openEstimate): the real file is 5,000 lines of calculator, and the part that decides a fork
 * is the sandbox call it makes. test_polish_beta_sandbox.py pins that order in the real file.
 *
 * Usage: const W = require("./_world.js"); const world = W.createWorld({ frontend: "<dir>" });
 */
const fs = require("fs");
const path = require("path");

const ORIGIN = "https://proposals.test";
const KEYS = {
  state: "treadwell.proposal_tool.state",
  draftId: "treadwell.proposal_tool.draft_id",
  guard: "treadwell.proposal_tool.hydrated_once",
  intent: "treadwell.proposal_tool.new_is_test",
};
// Mirror of drafts._SERVER_OWNED_KEYS. test_v2_new_estimate_test_flag.py compares the two.
const SERVER_OWNED = ["is_test", "archived", "assigned_estimator"];

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
  const n = {
    tagName: String(tag || "div").toUpperCase(),
    id: "", name: "", type: "", value: "", checked: false, hidden: false, className: "", innerHTML: "",
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
  Object.defineProperty(n, "textContent", {
    get() { return own + n.children.map((c) => c.textContent).join(""); },
    set(v) { n.children = []; own = String(v); },
  });
  return n;
}

/** The form's controls, read out of the REAL polish-intake.html, so the names a save reads are the page's own. */
function formControls(html) {
  const from = html.indexOf('<form id="intake-form">');
  const to = html.indexOf("</form>", from);
  if (from < 0 || to < 0) throw new Error("#intake-form is gone from polish-intake.html: retarget _world.js");
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
  if (controls.length < 15) throw new Error("only " + controls.length + " named controls in #intake-form: retarget _world.js");
  return controls;
}

// ── the world ────────────────────────────────────────────────────────────────────────────────────────────
function createWorld(cfg) {
  const o = Object.assign({}, cfg || {});
  if (!o.frontend) throw new Error("createWorld needs { frontend }");
  const frontend = path.resolve(o.frontend);
  const net = Object.assign({ up: 20, down: 20, commitMs: 150, bootMs: 120 }, o.net);
  const procMs = Object.assign({ GET: 10, PUT: 40, TEST: 40, COND: 10 }, o.proc);
  const sim = createSim();
  const local = createStorage();
  const session = createStorage();

  const world = {
    sim, local, session, net, procMs, frontend,
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
        world.rows.set(req.id, { data: data, created_at: stamp(), updated_at: stamp() });
      }
      return { status: 200, body: { ok: true, id: req.id, updated_at: stamp() } };
    }
    if (req.route === "TEST") {
      const want = req.body ? JSON.parse(req.body).is_test !== false : true;
      if (row) row.data.is_test = want;
      return { status: 200, body: { ok: true, existed: !!row, is_test: want } };
    }
    if (req.route === "COND") return { status: 200, body: { ok: true, conditions: [] } };
    world.unmocked.push(req.method + " " + req.url);
    return { status: 404, body: { detail: "the harness has no route for this" } };
  }

  /** Put a row on the server without going through a page (a project that already exists). */
  world.seed = (id, data) => {
    world.rows.set(id, { data: clone(data), created_at: stamp(), updated_at: stamp() });
  };
  /** Fail a route. { route: "PUT"|"GET"|"TEST", mode: "http500"|"okfalse"|"network"|"hang"|"html"|"gone", id?, times? } */
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
      return new Promise((resolve, reject) => {
        const fault = faultFor(req);
        sim.at(net.up, () => {
          // Not there yet when its page went: a plain request dies with the page, a keepalive one does not.
          if (page.dead && !req.keepalive) { req.outcome = "aborted"; return; }
          if (fault && fault.mode === "network") {
            req.outcome = "network error";
            if (!page.dead) reject(new TypeError("Failed to fetch"));
            return;
          }
          req.arrivedAt = sim.now;
          if (fault && fault.mode === "hang") { req.outcome = "hung"; return; }
          sim.at(procMs[req.route] === undefined ? 10 : procMs[req.route], () => {
            let res;
            if (fault && fault.mode === "http500") res = { status: 500, body: { detail: "boom" } };
            else if (fault && fault.mode === "okfalse") res = { status: 200, body: { ok: false, error: "Couldn't do that. Please try again." } };
            else if (fault && fault.mode === "html") res = { status: 200, body: undefined };
            else if (fault && fault.mode === "gone") res = { status: 200, body: { ok: true, existed: false, is_test: true } };
            else res = handle(req);
            req.doneAt = sim.now;
            req.status = res.status;
            sim.at(net.down, () => {
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
    const win = {
      document: doc, location, history, localStorage: local, sessionStorage: session,
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

  world.load = (urlString) => {
    const u = new URL(urlString, ORIGIN);
    const page = { n: ++pageCount, url: u.href, kind: kindOf(u.pathname), dead: false, leaving: false, bornAt: sim.now,
                   diedAt: null, settled: null, settledAt: null };
    page.label = page.kind + "#" + page.n;
    page.win = makeWindow(page);
    world.pages.push(page);
    world.current = page;
    const win = page.win;

    // A blank page runs no scripts: it is a window to put requests and timers on, for the model's own checks.
    if (page.kind !== "blank") {
      runScript(page, "shared.js");
      win.TWWorkTypes = mod("js/work-types.js");
      if (page.kind === "intake") {
        win.TWBidModel = mod("js/bid-model.js");
        win.TWIntakeScope = mod("js/intake-scope.js");
      }
      runScript(page, "js/polish-sandbox.js");
    }

    if (page.kind === "intake") {
      const html = read(path.join(frontend, "polish-intake.html"));
      const form = makeNode("form");
      form.id = "intake-form";
      form.elements = formControls(html);
      page.nodes["intake-form"] = form;
      runScript(page, "js/polish-intake.js");
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
    /** Press Continue (or Enter in a box): the form's own submit handlers. */
    page.pressContinue = () => { page.form.fire("submit", {}); };
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
    page.leaving = true;
    const target = new URL(String(href), page.url).href;
    world.navs.push({ from: page.label, to: target, askedAt: sim.now });
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
      sim.at(net.bootMs, () => { world.load(target); });
    });
  };

  // ── what a test does ───────────────────────────────────────────────────────────────────────────────────
  world.advance = (ms) => sim.advance(ms);
  world.settle = (capMs) => sim.settle(capMs);
  world.now = () => sim.now;
  world.localKey = (k) => local.getItem(KEYS[k] || k);

  /** The board's "+ New estimate": the same keys js/v2-board.js startNew() clears so shared.js mints a new
   *  draft id, then the intake page opens with no ?d=. From the GC tab the bid starts as a GC one, which startNew
   *  does by leaving { audience: "GC" } behind (`opts.gc`). Resolves once the page has booted. */
  world.startNewEstimate = async (opts) => {
    local.removeItem(KEYS.state);
    local.removeItem(KEYS.draftId);
    session.removeItem(KEYS.guard);
    if (opts && opts.gc) local.setItem(KEYS.state, JSON.stringify({ audience: "GC" }));
    const page = world.load("/polish-intake.html");
    await world.settle();
    return page;
  };

  /** This browser has been working on a project: its blob is stored, stamped for the project, and is the
   *  draft the browser resumes. (What opening a project from the board looks like after the first visit.) */
  world.holdLocally = (id, data) => {
    local.setItem(KEYS.state, JSON.stringify(Object.assign({}, clone(data), { __draft_id: id })));
    local.setItem(KEYS.draftId, id);
  };

  world.pageOf = (kind) => world.pages.filter((p) => p.kind === kind).pop() || null;

  /** A row as the Projects page would read it: is_test is true, false, or null for "nobody has said". */
  world.row = (id) => {
    const r = world.rows.get(id);
    if (!r) return null;
    const d = r.data;
    return {
      is_test: Object.prototype.hasOwnProperty.call(d, "is_test") && d.is_test !== undefined ? d.is_test : null,
      beta_sandbox_of: d.beta_sandbox_of || null,
      project_name: d.project_name === undefined ? null : d.project_name,
    };
  };

  world.requestsLog = () => world.requests.map((r) => ({
    n: r.n, at: r.sentAt, page: r.page.label, route: r.route, method: r.method, id: r.id || null,
    keepalive: r.keepalive, outcome: r.outcome, status: r.status,
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
