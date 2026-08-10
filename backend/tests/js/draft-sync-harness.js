/**
 * Runs frontend/shared.js for real, in node, with a fake browser around it.
 *
 * Every other test of this file inspects its SOURCE. That is enough for "is the guard present",
 * and it is not enough here: the blank-form overwrite was live on production for weeks while
 * every string a source test would look for was already in place. The bug was in how three
 * correct-looking conditions combined. Only running it shows that.
 *
 * The fake is deliberately thin — localStorage, sessionStorage, fetch, location, history — so
 * the thing under test is shared.js and not a DOM emulator.
 *
 * Usage: node draft-sync-harness.js '<json scenario>'  →  prints a JSON result.
 */
const fs = require("fs");
const path = require("path");

const SHARED = path.resolve(__dirname, "../../../frontend/shared.js");
const scenario = JSON.parse(process.argv[2] || "{}");

function store(initial) {
  const m = new Map(Object.entries(initial || {}));
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    dump: () => Object.fromEntries(m),
  };
}

const localStorage = store(scenario.local);
const sessionStorage = store(scenario.session);

// What the server holds, PER DRAFT ID, and how it answers. Keyed by id because evicting a
// foreign blob flushes it to ITS OWN id first — with one shared slot that write landed on the
// draft being opened and the test read back the wrong bid. `serverStatus` makes the read fail.
const rows = Object.assign({}, scenario.rows || {});
if (scenario.server) rows[scenario.urlId || ""] = scenario.server;
const server = { rows: rows, status: scenario.serverStatus || 200 };
const idOf = (u) => decodeURIComponent(String(u).split("/api/draft/")[1] || "").split(/[/?]/)[0];
const log = { gets: 0, puts: [], reloads: 0, warns: [] };

let href = scenario.url || "https://proposals.example.com/?d=" + (scenario.urlId || "");

global.window = {
  location: {
    get href() { return href; },
    origin: "https://proposals.example.com",
    reload: () => { log.reloads++; },
    assign: (u) => { href = u; },
  },
  history: { replaceState: (a, b, u) => { if (u) href = String(u); } },
  addEventListener: () => {},
  crypto: { randomUUID: () => "minted-0000-0000-0000-000000000000" },
  TWAuth: { ready: Promise.resolve() },
};
global.location = global.window.location;
global.localStorage = localStorage;
global.sessionStorage = sessionStorage;
global.document = {
  addEventListener: () => {}, removeEventListener: () => {},
  createElement: () => ({ style: {}, appendChild() {}, setAttribute() {}, classList: { add() {} } }),
  createTextNode: () => ({}),
  querySelectorAll: () => [],
  head: { appendChild() {} }, body: { appendChild() {}, removeChild() {} },
  activeElement: null,
};
global.console = Object.assign({}, console, {
  warn: (...a) => log.warns.push(a.join(" ")),
  error: (...a) => log.warns.push(a.join(" ")),
});

global.fetch = (url, opts) => {
  const method = (opts && opts.method) || "GET";
  if (method === "GET") {
    log.gets++;
    if (server.status !== 200) {
      return Promise.resolve({ ok: false, status: server.status, json: () => Promise.resolve({}) });
    }
    const row = server.rows[idOf(url)];
    if (!row) return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ data: row }) });
  }
  if (method === "PUT") {
    const body = JSON.parse(opts.body);
    const id = idOf(url);
    log.puts.push(body.data);
    server.rows[id] = body.data;         // the overwrite, if it happens — under the RIGHT id
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
  }
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
};

// shared.js is an IIFE that starts initDraftSync() on load.
eval(fs.readFileSync(SHARED, "utf8"));
const TW = global.window.TW;

(async () => {
  await TW.draftReady;
  // A keystroke: this is the moment the bug did its damage.
  if (scenario.type) TW.setState(scenario.type);
  // Fire the debounced save (2.5s) without waiting for it.
  if (scenario.type) await new Promise((r) => setTimeout(r, 2700));

  console.log(JSON.stringify({
    gets: log.gets,
    reloads: log.reloads,
    puts: log.puts,
    warns: log.warns,
    serverAfter: server.rows[scenario.urlId || ""] || null,
    serverRows: server.rows,
    localAfter: JSON.parse(localStorage.getItem("treadwell.proposal_tool.state") || "null"),
    unverified: sessionStorage.getItem("treadwell.proposal_tool.unverified"),
  }));
})();
