"use strict";
/* RUN the Estimating Tool v2 board (BETA): js/v2-board-core.js and js/v2-board.js, executed.
 *
 * Hanz, 2026-10-13: the v2 pipeline "is still in beta ... so do not merge it to the existing". The
 * board has its own code and its own route; this harness runs that code, never portal.js.
 *
 * Usage: node v2-board-harness.js <frontend-dir> <input.json>   ->   one line of JSON
 *   input.json: { "payload": {...the /api/v2/pipeline response...}, "scenarios": [...] }
 *   scenario:   { "name", "session": {key: value}, "confirm": true|false, "local": {key: value},
 *                 "actions": [ {type: "tab"|"search"|"est"|"open"|"close"|"clear"|"escape"
 *                               |"won"|"handoff"|"lost"|"lost-cancel"|"new"|"new-top", ...} ] }
 *     "won"/"handoff"/"lost" press that card button on the bid `id`. "lost" then answers the close-out
 *     dialog with `reason` and `note` and presses its confirm button; "lost-cancel" presses Cancel.
 *     "confirm" is what the hand-off prompt (TW.confirmDanger) answers; true when absent. "postAnswer"
 *     is the JSON body every write answers with ({ ok: true } when absent). "new" is the
 *     column's "+ New", "new-top" the page's New estimate button. "local" turns localStorage on, as a
 *     recording store seeded with these keys; only "+ New" may touch it.
 *
 * `core`: crm-core's own stage()/boardOf() and the board's own pool()/counts() over the payload.
 * `runs`: the whole v2-board.js in a bare VM with ONLY a stub page (a bag of fields, not jsdom, so a
 *         missing import cannot hide behind a global), reporting what it painted, every sessionStorage
 *         key it READ and WROTE, every address it sent the browser to, and every request it made
 *         (`fetches`: url, method and parsed body). localStorage THROWS if touched unless the scenario
 *         turns it on: only "+ New" has business there.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(process.argv[2]);
const INPUT = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const C = require(path.join(ROOT, "js", "crm-core.js"));
const V = require(path.join(ROOT, "js", "v2-board-core.js"));
const coreSrc = fs.readFileSync(path.join(ROOT, "js", "v2-board-core.js"), "utf8");
const boardSrc = fs.readFileSync(path.join(ROOT, "js", "v2-board.js"), "utf8");

function stub() {
  const listeners = {};
  const classes = new Set();
  const kids = {};
  return {
    innerHTML: "", textContent: "", value: "", className: "", hidden: false, dataset: {},
    disabled: false, removed: false,
    style: {}, listeners: listeners, kids: kids,
    classList: { add(c) { classes.add(c); }, remove(c) { classes.delete(c); },
                 contains(c) { return classes.has(c); } },
    addEventListener(t, fn) { listeners[t] = fn; },
    removeEventListener() {},
    // the close-out dialog finds its parts by selector; each selector is one stub, kept for the test
    querySelector(sel) { return (kids[sel] = kids[sel] || stub()); },
    remove() { this.removed = true; },
    closest() { return null; }, focus() {},
  };
}

const tick = (ms) => new Promise((r) => setTimeout(r, ms || 0));

async function run(payload, scenario) {
  const els = {};
  const el = (id) => (els[id] = els[id] || stub());
  const reads = [], writes = [], opened = [], urls = [], fetches = [], intents = [];
  const session = Object.assign({}, scenario.session || {});
  const local = scenario.local ? Object.assign({}, scenario.local) : null;
  const localWrites = [], confirms = [], dialogs = [], buttons = [], seen = [];
  let keydowns = [];
  const docKeydown = (e) => keydowns.slice().forEach((fn) => fn(e));
  const box = {
    console, setTimeout, clearTimeout, setInterval() { return 0; },
    URLSearchParams,
    document: { hidden: false, getElementById: el,
                querySelector() { return { focus() {} }; },
                createElement() { const d = stub(); dialogs.push(d); return d; },
                body: { appendChild() {} },
                addEventListener(t, fn) { if (t === "keydown") keydowns.push(fn); },
                removeEventListener(t, fn) { keydowns = keydowns.filter((f) => f !== fn); } },
    sessionStorage: {
      getItem(k) { reads.push(k); return Object.prototype.hasOwnProperty.call(session, k) ? session[k] : null; },
      setItem(k, v) { writes.push([k, String(v)]); session[k] = String(v); },
      removeItem(k) { writes.push([k, null]); delete session[k]; },
    },
    get localStorage() {
      if (!local) throw new Error("the v2 board must not touch localStorage");
      return {
        getItem(k) { return Object.prototype.hasOwnProperty.call(local, k) ? local[k] : null; },
        setItem(k, v) { localWrites.push([k, String(v)]); local[k] = String(v); },
        removeItem(k) { localWrites.push([k, null]); delete local[k]; },
      };
    },
    location: { search: scenario.search || "", pathname: "/v2-board.html", hash: "",
                assign(u) { opened.push(String(u)); } },
    history: { replaceState(_a, _b, u) {
      // a real browser moves the address; so does this, or "close" could never be seen to clear ?open
      urls.push(String(u));
      const i = String(u).indexOf("?");
      box.location.search = i < 0 ? "" : String(u).slice(i);
      box.location.pathname = i < 0 ? String(u) : String(u).slice(0, i);
    } },
    TW: { fmtBizDate(iso) { return String(iso || "").slice(0, 10); },
          fmtBizDateTime(iso) { return String(iso || "").slice(0, 16).replace("T", " "); },
          authHeaders() { return {}; }, resolveApiBase() { return ""; },
          // What a "+ New" says the project is started as (shared.js mints its id and keeps the start; the real one runs in
          // tests/js/_world.js, which lifts this file's startNew out and runs it). Recorded here so it is a fact read off the board.
          setNewProjectTestIntent(want) { intents.push(want); },
          confirmDanger(opts) {
            confirms.push(opts);
            return Promise.resolve(scenario.confirm === undefined ? true : !!scenario.confirm);
          } },
    __TW_TOKEN: "t",
    // Every request the page makes is recorded, with its method: a board that "only reads" is held
    // to exactly that by test_v2_board.py. (There is no XMLHttpRequest or sendBeacon in this VM, so
    // using either throws and fails the run instead of slipping past the log.)
    fetch: async (url, init) => {
      const method = String((init && init.method) || "GET").toUpperCase();
      const rec = { url: String(url), method: method };
      if (init && init.body) rec.body = JSON.parse(init.body);
      fetches.push(rec);
      // `postAnswer`: what every write answers (the status route's 200 body), { ok: true } when absent.
      if (method !== "GET") {
        const answer = scenario.postAnswer || { ok: true };
        return { ok: true, status: 200, json: async () => answer };
      }
      return { ok: true, json: async () => payload };
    },
  };
  box.window = box; box.self = box; box.TWCrm = C;
  el("v2-degraded").hidden = true;       // v2-board.html ships it hidden (test_v2_board.py checks)
  vm.createContext(box);
  vm.runInContext(coreSrc, box, { filename: "v2-board-core.js" });
  vm.runInContext(boardSrc, box, { filename: "v2-board.js" });
  await new Promise((r) => setTimeout(r, 60));
  const snap = () => ({
    list: el("list").innerHTML, tabs: el("v2-tabs").innerHTML, est: el("est").innerHTML,
    count: el("count").textContent, toolbarHidden: el("toolbar").hidden,
    clearHidden: el("clear").hidden, ceiling: el("ceiling").textContent,
    panel: el("v2-panel").innerHTML, panelOpen: el("v2-panel").classList.contains("open"),
    degraded: el("v2-degraded").innerHTML, degradedHidden: el("v2-degraded").hidden,
  });
  const first = snap();
  for (const a of scenario.actions || []) {
    if (a.type === "tab") {
      el("v2-tabs").listeners.click({ target: { closest(s) { return s === "[data-tab]" ? { dataset: { tab: a.tab } } : null; } } });
    } else if (a.type === "search") {
      el("q").listeners.input({ target: { value: a.value } });
      await new Promise((r) => setTimeout(r, 200));
    } else if (a.type === "est") {
      el("est").listeners.change({ target: { value: a.value } });
    } else if (a.type === "clear") {
      el("clear").listeners.click();
    } else if (a.type === "open") {
      el("list").listeners.click({ target: { closest(s) { return s === ".deal" ? { dataset: { id: a.id } } : null; } } });
    } else if (a.type === "close") {
      el("v2-panel").listeners.click({ target: { closest(s) { return s === "[data-v2-close]" ? {} : null; } } });
    } else if (a.type === "escape") {
      docKeydown({ key: "Escape" });
    } else if (a.type === "won" || a.type === "handoff" || a.type === "lost" || a.type === "lost-cancel") {
      const kind = a.type === "lost-cancel" ? "lost" : a.type;
      const sel = "[data-" + kind + "]";
      const btn = stub();
      btn.dataset[kind] = encodeURIComponent(a.id);
      btn.textContent = kind;
      buttons.push(btn);
      // the button sits inside its card: a handler that fell through would also find the .deal
      el("list").listeners.click({ target: { closest(s) {
        return s === sel ? btn : s === ".deal" ? { dataset: { id: a.id } } : null; } } });
      await tick(5);
      if (kind === "lost") {
        const dlg = dialogs[dialogs.length - 1];
        const k = dlg.kids;
        if (a.type === "lost-cancel") {
          if (a.escape) docKeydown({ key: "Escape" }); else k["[data-x]"].listeners.click();
        } else {
          k["[data-why]"].value = a.reason || "";
          k["[data-why]"].listeners.change();
          k["[data-note]"].value = a.note || "";
          k["[data-note]"].listeners.input();
          seen.push({ sub: k["[data-sub]"].textContent, go: k["[data-go]"].textContent,
                      goDisabled: k["[data-go]"].disabled });
          k["[data-go]"].listeners.click();
        }
      }
      await tick(60);
    } else if (a.type === "key") {
      // a key on the board: on a card (`on: "card"`) or on a button inside one (`on: "button"`)
      let prevented = false;
      el("list").listeners.keydown({ key: a.key, preventDefault() { prevented = true; },
        target: { closest(s) {
          if (s === "button") return a.on === "button" ? {} : null;
          return s === ".deal" ? { dataset: { id: a.id } } : null; } } });
      seen.push({ key: a.key, on: a.on, prevented: prevented });
    } else if (a.type === "new") {
      el("list").listeners.click({ target: { closest(s) { return s === "[data-new-v2]" ? {} : null; } } });
    } else if (a.type === "new-top") {
      el("new-v2").listeners.click();
    }
  }
  return { name: scenario.name, first: first, last: snap(), reads: reads, writes: writes,
           opened: opened, urls: urls, session: session, fetches: fetches, intents: intents,
           local: local, localWrites: localWrites, confirms: confirms, seen: seen,
           dialogs: dialogs.map((d) => ({ html: d.innerHTML, removed: d.removed })),
           buttons: buttons.map((b) => ({ text: b.textContent, disabled: b.disabled })) };
}

async function main() {
  const rows = (INPUT.payload && INPUT.payload.proposals) || [];
  const core = {
    rows: rows.map((p) => ({ id: p.proposal_id, stage: C.stage(p), board: C.boardOf(p), total: C.cardTotal(p),
                             test: C.isTest(p), lost: C.isLost(p), handed: C.isHandedOff(p) })),
    pools: {}, counts: V.counts(rows), tabs: V.tabsToShow(rows, "direct"),
    columns: { direct: V.columnsFor("direct"), crmStages: C.STAGES },
    cards: {}, panels: {},
  };
  V.TABS.forEach((t) => { core.pools[t] = V.pool(rows, t).map((p) => p.proposal_id); });
  rows.forEach((p) => {
    core.cards[p.proposal_id] = V.cardHtml(p, {});
    core.panels[p.proposal_id] = V.panelHtml(p, {});
  });
  const runs = [];
  for (const s of INPUT.scenarios || []) runs.push(await run(INPUT.payload, s));
  process.stdout.write(JSON.stringify({ core: core, runs: runs }) + "\n");
}
main().catch((e) => { console.error(e && e.stack || String(e)); process.exit(1); });
