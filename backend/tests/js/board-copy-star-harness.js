"use strict";
/* Copy and the star on a board card, EXECUTED: rendered, sorted, clicked, followed to the request.
 *
 * Hanz, 2026-10-29: "In the pipeline, both [Direct and GC] we should be able to copy a project ...
 * When we copy a project, the copied project should live under Created but not sent. Also we must
 * have the ability to Star a project and it always gets put up to the top of the pipeline."
 *
 * What runs here is portal.js's own code: kanbanHtml and tableHtml (the buttons and the marks),
 * the page's applySort over the real crm-core sort (the star on top of its column under every sort
 * field and both directions, on both boards), the delegated click listener (a press acts and does
 * not also open the drawer), and toggleCardStar / copyCardProject (which request, what the row
 * becomes, what is asked first). Same scaffolding as card-actions-harness.js.
 *
 * Usage: node board-copy-star-harness.js <frontend-dir>   ->  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];
const SRC = fs.readFileSync(path.join(ROOT, "js", "portal.js"), "utf8");
const C = require(path.join(path.resolve(ROOT), "js", "crm-core.js"));

function fn(name) {
  const m = new RegExp("\\n\\s{2,6}(?:async\\s+)?function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone from portal.js — rewrite this harness, don't delete it");
  const i = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

function topConst(name) {
  const m = new RegExp("\\n\\s*const " + name + " = ").exec(SRC);
  if (!m) throw new Error("const " + name + " is gone from portal.js — rewrite this harness");
  let depth = 0;
  for (let j = m.index + m[0].length; j < SRC.length; j++) {
    const ch = SRC[j];
    if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (ch === ";" && depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unterminated declaration reading " + name);
}

function boardClickStatement() {
  const start = SRC.indexOf('$("board").addEventListener("click"');
  if (start < 0) throw new Error("the board click listener is gone — rewrite this harness");
  let depth = 0;
  for (let j = SRC.indexOf("(", SRC.indexOf(".addEventListener", start)); j < SRC.length; j++) {
    if (SRC[j] === "(") depth++;
    else if (SRC[j] === ")" && --depth === 0) return SRC.slice(start, j + 2);
  }
  throw new Error("unbalanced parens reading the board click listener");
}

// ── the fixtures ─────────────────────────────────────────────────────────────
// Two boards (Direct: audience absent or "Direct"; GC: "GC"), two live columns each (Created but not
// sent, Sent). In every column ONE starred card is the WORST card under every sort: the oldest, the
// smallest, the last estimator by name. A second starred card in the Direct "Created" column proves
// the starred cards keep the sort's order among themselves.
const T = (d) => "2026-10-" + String(d).padStart(2, "0") + "T12:00:00Z";
function unsent(id, aud, day, total, est, star) {
  return { proposal_id: id, project_name: "Proj " + id, not_sent: true, audience: aud,
           drafted_at: T(day), last_activity_at: T(day), bid_total: total,
           estimator_email: est + "@wetreadwell.com", starred_at: star ? T(28) : null };
}
function sent(id, aud, day, total, est, star) {
  return { proposal_id: id, project_name: "Proj " + id, proposal_status: "sent", audience: aud,
           sent_at: T(day), last_activity_at: T(day), bid_total: total,
           assigned_estimator: est + "@wetreadwell.com", starred_at: star ? T(28) : undefined };
}
const ROWS = [
  // Direct, Created but not sent
  unsent("d-c1", null, 20, 50000, "bob"),
  unsent("d-c2", "Direct", 15, 30000, "carl"),
  unsent("d-c3", null, 2, 100, "zed", true),           // worst everywhere, starred
  unsent("d-c4", "Direct", 3, 200, "yuri", true),      // second star
  unsent("d-c5", null, 10, 9000, "amy"),
  // Direct, Sent
  sent("d-s1", "Direct", 22, 70000, "bob"),
  sent("d-s2", null, 1, 50, "zed", true),
  sent("d-s3", "Direct", 12, 8000, "amy"),
  // GC, Created but not sent
  unsent("g-c1", "GC", 21, 40000, "bob"),
  unsent("g-c2", "GC", 1, 10, "zed", true),
  unsent("g-c3", "GC", 11, 900, "amy"),
  // GC, Sent
  sent("g-s1", "GC", 25, 60000, "carl"),
  sent("g-s2", "GC", 2, 20, "zed", true),
  sent("g-s3", "GC", 14, 5000, "amy"),
  // A project of three proposals, for Copy's question
  Object.assign(unsent("m-1", null, 18, 12000, "kyle"),
                { scope_group: "grp", scope_count: 3, scope_index: 1, scope_label: "Polish" }),
];

// ── the lifted module ────────────────────────────────────────────────────────
const confirmed = { answers: [], calls: [] };
const net = { requests: [], fails: false, respond: { ok: true }, addOnLoad: null };
const painted = { board: 0, load: 0 };
const opened = [];

const api = (p, init) => {
  net.requests.push({ path: p, method: (init && init.method) || "GET",
                      body: init && init.body ? JSON.parse(init.body) : null });
  return Promise.resolve(net.fails
    ? { ok: false, status: 500, json: () => Promise.resolve({ ok: false, error: "postgrest down" }) }
    : { ok: true, status: 200, json: () => Promise.resolve(net.respond) });
};

const dsKey = (attr) => attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
function node(attrs, parent) {
  const n = {
    dataset: attrs.dataset || {}, className: attrs.className || "", textContent: attrs.text || "",
    title: "", disabled: false, parent: parent || null,
    closest(sel) {
      for (let el = n; el; el = el.parent) {
        if (sel.startsWith("[") && dsKey(sel.slice(1, -1).replace(/^data-/, "")) in (el.dataset || {})) return el;
        if (sel.startsWith(".") && String(el.className || "").split(" ").includes(sel.slice(1))) return el;
        if (sel.includes(",")) {
          for (const one of sel.split(",").map((s) => s.trim())) {
            if (one.startsWith(".") && String(el.className || "").split(" ").includes(one.slice(1))) return el;
          }
        }
      }
      return null;
    },
  };
  return n;
}

const boardNode = { listeners: {}, className: "", classList: { toggle() {} }, innerHTML: "",
                    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); } };

let page = null;
const deps = {
  C,
  fu: C.followup,
  avatar: C.avatarHtml,
  esc: (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
  money: (n) => "$" + Number(n || 0).toLocaleString(),
  pausedUntil: (p) => C.pausedUntil(p, "2026-10-29"),
  TWIcon: (name) => '<svg data-icon="' + name + '"></svg>',
  TW: { fmtBizDate: (v) => String(v), fmtBizDay: (v) => String(v), bizYM: (v) => String(v).slice(0, 7),
        confirmDanger: (o) => { confirmed.calls.push(o);
                                return Promise.resolve(confirmed.answers.length ? confirmed.answers.shift() : true); } },
  $: (id) => (id === "board" ? boardNode : null),
  api,
  closeOutDialog: () => Promise.resolve(null),
  renderBoard: () => { painted.board++; },
  // load() re-reads the board: a copy made on the server arrives on it (net.addOnLoad).
  load: () => { painted.load++; if (net.addOnLoad) { page.setBoard(page.all().concat([net.addOnLoad])); net.addOnLoad = null; }
                return Promise.resolve(); },
  openDetail: (id) => { opened.push(id); },
  startNewProposal: () => {},
  window: { location: { assign: () => {} } },
  ssSet: () => {},
  syncSortControls: () => {},
  // How the lifted listener's registration is read back out, so the statement itself is untouched.
  getBoardListeners: () => boardNode.listeners.click || [],
};
for (const m of SRC.matchAll(/const \{([^}]*)\} = C;/g)) {
  for (const part of m[1].split(",")) {
    const t = part.trim();
    if (!t) continue;
    const [from, to] = t.includes(":") ? t.split(":").map((x) => x.trim()) : [t, t];
    if (!(from in C)) throw new Error("portal.js destructures C." + from + ", which crm-core does not export");
    deps[to] = C[from];
  }
}

const NAMES = Object.keys(deps);
const body = `"use strict";
  let TAB = "active", VIEW = "board", ALL = [];
  let SORTFIELD = "activity", SORTDIR = "desc";
  ${topConst("LOST_COLS")}
  ${topConst("COLS")}
  ${topConst("HOLD_MONTHS")}
  ${topConst("applySort")}
  ${fn("boardPool")}
  ${fn("groupByReason")}
  ${fn("chipsHtml")}
  ${fn("recipientLine")}
  ${fn("cardActions")}
  ${fn("kanbanHtml")}
  ${fn("tableHtml")}
  ${fn("icon")}
  ${fn("cardRowOf")}
  ${fn("toggleCardStar")}
  ${fn("copyCardProject")}
  ${fn("markCardWon")}
  ${fn("markCardHandoff")}
  ${fn("confirmHandoff")}
  ${fn("closeCardOut")}
  ${boardClickStatement()}
  return {
    paint: (rows, field, dir, view, tab) => { ALL = rows; SORTFIELD = field; SORTDIR = dir; TAB = tab || "active";
      const items = applySort(boardPool());
      return view === "table" ? tableHtml(items) : kanbanHtml(items); },
    setBoard: (rows) => { ALL = rows; },
    all: () => ALL,
    row: (id) => ALL.filter((x) => x.proposal_id === id)[0] || null,
    click: (target) => getBoardListeners()[0]({ target, preventDefault() {} }),
  };`;
page = new Function(...NAMES, body)(...NAMES.map((n) => deps[n]));

// ── load() itself, lifted with a network whose replies arrive in the order a scenario says ──────
// The board re-reads /api/portal/pipeline from a 25s poll, from refreshLive and after every action,
// so two reads can be in flight at once; the scenario answers the NEWER one first.
const loadPage = new Function("C", "esc", "$", `"use strict";
  let ALL = [], BOARD_SIG = "", DEGRADED_SIG = "", LOAD_GEN = 0;
  let CUR_PID = null, REDIRECTED = false, DEEPLINK_USED = false;
  const PIPELINE = C.PIPELINE_DIRECT;
  const location = { search: "", hash: "", replace() {} };
  const tokenReady = async () => {};
  const pending = [];
  const api = () => new Promise((resolve) => { pending.push(resolve); });
  const renderDegraded = () => {};
  const painted = [];
  const renderBoard = () => { painted.push(ALL.map((p) => p.proposal_id + (p.starred_at ? "*" : ""))); };
  const openDetail = () => {};
  ${fn("load")}
  return { load, pending, painted, all: () => ALL };`)(C, deps.esc, () => null);

async function tick() { for (let i = 0; i < 12; i++) await Promise.resolve(); }

/** The cards of each column, in the order the paint drew them. */
function columns(html) {
  const out = {};
  for (const block of html.split('<div class="col').slice(1)) {
    const h = /<h2>([^<]*)</.exec(block);
    out[h ? h[1] : "?"] = [...block.matchAll(/<div class="deal" data-id="([^"]+)"/g)].map((m) => m[1]);
  }
  return out;
}

async function press(which, id) {
  net.requests.length = 0;
  confirmed.calls.length = 0;
  opened.length = 0;
  const before = { board: painted.board, load: painted.load };
  const deal = node({ className: "deal", dataset: { id } });
  const btn = node({ dataset: { [which]: encodeURIComponent(id) }, className: "deal-tool" }, deal);
  page.click(btn);
  await tick();
  return { requests: net.requests.slice(), prompts: confirmed.calls.map((c) => ({ title: c.title, message: c.message })),
           openedDrawer: opened.slice(), rendered: painted.board - before.board,
           reloaded: painted.load - before.load, disabled: btn.disabled, title: btn.title };
}

(async () => {
  const out = { errors: {} };
  try {
    const clone = () => JSON.parse(JSON.stringify(ROWS));
    const unstar = (rows) => rows.map((r) => Object.assign({}, r, { starred_at: null }));
    // ── the order, under every sort, on both boards ──
    out.orders = [];
    for (const pipeline of [C.PIPELINE_DIRECT, C.PIPELINE_GC]) {
      for (const field of C.SORT_FIELDS) {
        for (const dir of ["asc", "desc"]) {
          const rows = C.onBoard(clone(), pipeline);
          out.orders.push({ pipeline, field, dir,
                            starred: rows.filter((r) => r.starred_at).map((r) => r.proposal_id),
                            withStars: columns(page.paint(rows, field, dir, "board")),
                            without: columns(page.paint(unstar(rows), field, dir, "board")) });
        }
      }
    }
    // ── what the card and the row draw ──
    const board = page.paint(C.onBoard(clone(), C.PIPELINE_DIRECT), "activity", "desc", "board");
    out.cards = Object.fromEntries(board.split('<div class="deal"').slice(1).map((b) => {
      const id = /data-id="([^"]+)"/.exec(b)[1];
      return [id, { copy: b.includes('data-copy="' + encodeURIComponent(id) + '"'),
                    star: b.includes('data-star="' + encodeURIComponent(id) + '"'),
                    pressed: /data-star="[^"]*" aria-pressed="true"/.test(b),
                    on: b.includes("deal-star is-on"), starIcon: b.includes('data-icon="star"'),
                    copyIcon: b.includes('data-icon="copy"') }];
    }));
    const table = page.paint(C.onBoard(clone(), C.PIPELINE_DIRECT), "activity", "desc", "table");
    out.tableStars = [...table.matchAll(/<tr class="trow" data-id="([^"]+)"[^>]*>\s*<td class="t-name">(<span class="t-star")?/g)]
      .map((m) => [m[1], !!m[2]]);
    // A lost card has no outcome buttons, but Copy and the star are still there.
    const lostRows = clone().concat([{ proposal_id: "lost-1", project_name: "Gone", proposal_status: "closed_lost",
      followup_state: { closed_lost_reason: "not_low_bid" }, starred_at: T(5) }]);
    const lostHtml = page.paint(lostRows, "activity", "desc", "board", "lost");
    out.lostCard = { copy: lostHtml.includes('data-copy="lost-1"'), star: lostHtml.includes('data-star="lost-1"'),
                     won: lostHtml.includes("data-won=") };

    // ── the star, pressed ──
    page.setBoard(clone());
    out.starOn = await press("star", "d-c1");
    out.starOnRow = page.row("d-c1").starred_at;
    out.starOff = await press("star", "d-c3");
    out.starOffRow = page.row("d-c3").starred_at;
    net.fails = true;
    out.starFailed = await press("star", "d-c2");
    out.starFailedRow = page.row("d-c2").starred_at;
    net.fails = false;

    // ── Copy, pressed ──
    confirmed.answers = [false];
    out.copyRefused = await press("copy", "d-c2");
    net.respond = { ok: true, id: "new-copy", ids: ["new-copy"], project_name: "Proj d-c2 (copy)" };
    net.addOnLoad = { proposal_id: "new-copy", project_name: "Proj d-c2 (copy)", not_sent: true, files_pending: true };
    out.copyDone = await press("copy", "d-c2");
    out.copyLanded = page.row("new-copy");
    // The re-read has not brought this copy (yet): the drawer is not opened on a card that is not there.
    net.respond = { ok: true, id: "copy-many", ids: ["copy-many", "c2", "c3"], project_name: "Proj m-1 (copy)" };
    out.copyMany = await press("copy", "m-1");
    // A project of three whose other two proposals are closed lost and on hold: the copy leaves
    // them behind (drafts.copy_project), and the question says so before anything is made.
    const grp = (id, extra) => Object.assign(unsent(id, null, 17, 5000, "kyle"),
      { scope_group: "grp", scope_count: 3, scope_label: id }, extra);
    page.setBoard(clone().concat([
      grp("m-2", { proposal_status: "closed_lost", followup_state: { closed_lost_reason: "not_low_bid" } }),
      grp("m-3", { followup_state: { on_hold_reason: "on_hold", paused_until: "" } })]));
    confirmed.answers = [false];
    out.copyBehind = await press("copy", "m-1");
    page.setBoard(clone().concat([grp("m-2", { proposal_status: "closed_lost" })]));
    confirmed.answers = [false];
    out.copyBehindOne = await press("copy", "m-1");
    page.setBoard(clone());
    net.fails = true;
    out.copyFailed = await press("copy", "d-c5");
    net.fails = false;
    // ── two board reads in flight, the newer answered first ──
    const reply = (rows) => ({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, proposals: rows }) });
    const poll = loadPage.load();              // the 25s poll: read the board before the star
    const fresh = loadPage.load();             // toggleCardStar's re-read, after the star was saved
    await tick();
    out.loadInFlight = loadPage.pending.length;
    loadPage.pending[1](reply([Object.assign(unsent("r-1", null, 5, 10, "amy"), { starred_at: T(29) })]));
    await fresh;
    loadPage.pending[0](reply([unsent("r-1", null, 5, 10, "amy")]));
    await poll;
    out.loadRace = { all: loadPage.all().map((p) => p.proposal_id + (p.starred_at ? "*" : "")),
                     painted: loadPage.painted.slice() };
  } catch (e) {
    out.errors.run = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }
  process.stdout.write(JSON.stringify(out));
})().catch((e) => {
  process.stdout.write(JSON.stringify({ error: e.constructor.name + ": " + e.message, stack: String(e.stack || "") }));
});
