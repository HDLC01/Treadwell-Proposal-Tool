"use strict";
/* The two buttons on a board card, EXECUTED: rendered, clicked, and followed to the request.
 *
 * Hanz, 2026-08-20: "the board card's two buttons become Mark as closed and Lost", and "Closed"
 * means WON. Files and Info sheet came off the card the same day, having moved into both drawers'
 * Proposal tab.
 *
 * WHY EXECUTED. Four claims here, none of them settled by a source read:
 *   · the buttons reach the RIGHT project — cardRowOf looks the row up out of ALL by id, and a
 *     board that repainted between the render and the click must not act on a neighbour;
 *   · "Mark as closed" posts the existing won mark rather than inventing a state;
 *   · "Lost" picks its endpoint off `not_sent`, because an unsent project has no portal row;
 *   · a click on either one does NOT also open the drawer. That last one is a returns-from-a-branch
 *     property of a delegated listener, so the listener itself is lifted and fired.
 *
 * The 2026-08-12 outage was an unbound identifier inside kanbanHtml's own .map() with every source
 * assertion in the suite green, which is why cardActions is rendered through kanbanHtml here rather
 * than called on its own.
 *
 * Usage: node card-actions-harness.js <frontend-dir>   →  one line of JSON
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

/** A module-level `const NAME = …;`, bracket-counted to its own semicolon. */
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

/** The delegated click listener on #board, verbatim, as a STATEMENT.
 *
 *  Lifted rather than re-implemented because the claim under test is about its shape: every button
 *  branch has to run before the row branch AND return, or a click both acts and opens the drawer,
 *  and the drawer wins the repaint. A hand-written stand-in would be asserting my own code. */
function boardClickStatement() {
  const start = SRC.indexOf('$("board").addEventListener("click"');
  if (start < 0) throw new Error("the board click listener is gone — rewrite this harness");
  // Count from addEventListener's OWN paren. Counting from the first "(" after `start` finds the
  // one inside `$("board")` and closes a statement early, which surfaces as a SyntaxError from
  // this file rather than as anything about the product.
  let depth = 0;
  for (let j = SRC.indexOf("(", SRC.indexOf(".addEventListener", start)); j < SRC.length; j++) {
    if (SRC[j] === "(") depth++;
    else if (SRC[j] === ")" && --depth === 0) return SRC.slice(start, j + 2);   // include the ;
  }
  throw new Error("unbalanced parens reading the board click listener");
}

// ── the fixtures ─────────────────────────────────────────────────────────────
// One of each shape the two buttons have to tell apart. Deliberately including the two that must
// get NO buttons: a lost card offering "Lost" and a won card offering "Mark as closed" are both
// controls that save and change nothing visible, which reads as broken.
const ROWS = [
  { proposal_id: "ns-1", project_name: "Cedar Ridge", not_sent: true,
    drafted_at: "2026-08-09T12:00:00Z", estimator_email: "kyle@wetreadwell.com" },
  { proposal_id: "sent-1", project_name: "Maple Street Warehouse", proposal_status: "sent",
    sent_at: "2026-08-08T12:00:00Z", assigned_estimator: "kyle@wetreadwell.com" },
  { proposal_id: "approved-1", project_name: "Westport Retail", proposal_status: "approved",
    approved_at: "2026-08-07T12:00:00Z", deposit_status: "pending", deposit_required: true },
  { proposal_id: "won-1", project_name: "Trabon Group", not_sent: true,
    won_at: "2026-08-19T15:00:00Z", drafted_at: "2026-08-09T12:00:00Z" },
  { proposal_id: "lost-1", project_name: "Brookfield Site", proposal_status: "closed_lost",
    followup_state: { closed_lost_reason: "not_low_bid", closed_at: "2026-08-01T12:00:00Z" } },
  // An id that does not survive a round trip through the attribute unless both halves happen. Its
  // only job is the lookup assertion above, so it is a plain live not-sent row otherwise.
  { proposal_id: "odd 1/2+3", project_name: "Odd Id Test", not_sent: true,
    drafted_at: "2026-08-09T12:00:00Z" },
];

let TAB = "active";
let VIEW = "board";

// ── the lifted module ────────────────────────────────────────────────────────
const answer = { value: null, calls: [] };
const net = { requests: [], fails: false, respond: { ok: true } };
const painted = { board: 0, load: 0 };
const opened = [];
const navigated = [];

const api = (p, init) => {
  net.requests.push({ path: p, method: (init && init.method) || "GET",
                      body: init && init.body ? JSON.parse(init.body) : null });
  return Promise.resolve(net.fails
    ? { ok: false, status: 500, json: () => Promise.resolve({ error: "postgrest down" }) }
    : { ok: true, status: 200, json: () => Promise.resolve(net.respond) });
};

/** `[data-new-proposal]` as the browser spells it on the element: dataset keys are camelCase.
 *  Getting this wrong is silent — every attribute selector simply misses, the row branch catches
 *  the click instead, and the harness reports that every button opens the drawer. Which is a real
 *  bug shape, so it looked like a finding rather than like scaffolding. */
const dsKey = (attr) => attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

/** A node stub good enough for a delegated listener: `closest` walks a declared parent chain, so
 *  a click on a button inside a .deal reaches BOTH selectors and the ordering claim is real. */
function node(attrs, parent) {
  const n = {
    dataset: attrs.dataset || {}, className: attrs.className || "", textContent: attrs.text || "",
    disabled: false, parent: parent || null,
    closest(sel) {
      for (let el = n; el; el = el.parent) {
        if (sel.startsWith("[") && dsKey(sel.slice(1, -1).replace(/^data-/, "")) in (el.dataset || {})) return el;
        if (sel.startsWith(".") && String(el.className || "").split(" ").includes(sel.slice(1))) return el;
        // ".deal, .trow" — the row branch's own selector, comma-separated.
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

const deps = {
  C,
  fu: C.followup,
  avatar: C.avatarHtml,
  esc: (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
  money: (n) => "$" + Number(n || 0).toLocaleString(),
  pausedUntil: (p) => C.pausedUntil(p, "2026-08-21"),
  TW: { fmtBizDate: (v) => String(v), fmtBizDay: (v) => String(v), bizYM: (v) => String(v).slice(0, 7) },
  $: (id) => (id === "board" ? boardNode : null),
  api,
  // The dialog, ANSWERABLE. Its own markup and its required comment are not-sent-lost-harness's
  // subject; what this file drives is which request an answer turns into.
  closeOutDialog: (p, opts) => { answer.calls.push({ name: p && p.project_name, opts: opts || null });
                                 return Promise.resolve(answer.value); },
  renderBoard: () => { painted.board++; },
  load: () => { painted.load++; },
  openDetail: (id) => { opened.push(id); },
  startNewProposal: () => { navigated.push("new"); },
  window: { location: { assign: (u) => navigated.push(u) } },
  ssSet: () => {},
  syncSortControls: () => {},
};

// EXACTLY what portal.js pulls off crm-core, taken from its own destructuring lines so this cannot
// drift into binding something the page does not have — and so a name the page uses without
// importing is an immediate ReferenceError, which is the whole point of running this at all.
const destructured = [];
for (const m of SRC.matchAll(/const \{([^}]*)\} = C;/g)) {
  for (const part of m[1].split(",")) {
    const t = part.trim();
    if (!t) continue;
    const [from, to] = t.includes(":") ? t.split(":").map((x) => x.trim()) : [t, t];
    if (!(from in C)) throw new Error("portal.js destructures C." + from + ", which crm-core does not export");
    destructured.push([to, C[from]]);
  }
}
for (const [name, value] of destructured) deps[name] = value;

const NAMES = Object.keys(deps);
const body = `"use strict";
  let TAB = getTAB(), VIEW = getVIEW(), ALL = getALL();
  let SORTFIELD = "activity", SORTDIR = "desc";
  ${topConst("LOST_COLS")}
  ${topConst("COLS")}
  ${topConst("HOLD_MONTHS")}
  ${fn("boardPool")}
  ${fn("groupByReason")}
  ${fn("chipsHtml")}
  ${fn("recipientLine")}
  ${fn("cardActions")}
  ${fn("kanbanHtml")}
  ${fn("tableHtml")}
  ${fn("cardRowOf")}
  ${fn("markCardWon")}
  ${fn("closeCardOut")}
  ${boardClickStatement()}
  return {
    render: (tab, view, rows) => { TAB = tab; VIEW = view; ALL = rows;
      return view === "table" ? tableHtml(boardPool()) : kanbanHtml(boardPool()); },
    setBoard: (rows) => { ALL = rows; },
    row: (id) => ALL.filter((x) => x.proposal_id === id)[0] || null,
    // The listener the page registered, so a click goes through the REAL delegation.
    click: (target) => boardListeners()[0]({ target, preventDefault() {} }),
    cardRowOf,
  };`;

// `boardListeners` is how the lifted statement's registration is read back out. Declared as a dep
// so the statement itself is untouched: rewriting `$("board").addEventListener(...)` into something
// capturable is exactly the kind of edit that would stop this file testing the shipped code.
deps.boardListeners = () => boardNode.listeners.click || [];
NAMES.push("boardListeners");
NAMES.push("getTAB", "getVIEW", "getALL");
const page = new Function(...NAMES, body)(
  ...NAMES.slice(0, NAMES.length - 3).map((n) => deps[n]),
  () => TAB, () => VIEW, () => ROWS);

async function tick() { for (let i = 0; i < 8; i++) await Promise.resolve(); }

/** Click one card button, through the real delegated listener, and report everything it did. */
async function press(which, id, className) {
  net.requests.length = 0;
  answer.calls.length = 0;
  opened.length = 0;
  navigated.length = 0;
  const before = { board: painted.board, load: painted.load };
  const deal = node({ className: className || "deal", dataset: { id } });
  const btn = node({ dataset: { [which]: encodeURIComponent(id) }, className: "deal-act",
                     text: which === "won" ? "Mark as closed" : "Lost" }, deal);
  page.click(btn);
  await tick();
  return { requests: net.requests.slice(), asked: answer.calls.slice(),
           openedDrawer: opened.slice(), navigated: navigated.slice(),
           rendered: painted.board - before.board, reloaded: painted.load - before.load,
           label: btn.textContent, disabled: btn.disabled };
}

(async () => {
  const out = { errors: {} };
  try {
    // ── what the card draws ──
    const board = page.render("active", "board", ROWS);
    const table = page.render("active", "table", ROWS);
    const wonBoard = page.render("won", "board", ROWS);
    const lostBoard = page.render("lost", "board", ROWS);
    page.render("active", "board", ROWS);
    out.rendered = {
      board, table, wonBoard, lostBoard,
      // Per card, read back OUT of the html: which buttons its own .deal block carries.
      byCard: Object.fromEntries(board.split('<div class="deal"').slice(1).map((block) => {
        const id = /data-id="([^"]+)"/.exec(block);
        return [id ? id[1] : "?", { won: block.includes("data-won="),
                                    lost: block.includes("data-lost="),
                                    files: block.includes("data-files="),
                                    info: block.includes("data-info=") }];
      })),
    };

    // ── the row lookup ──
    out.lookup = {
      found: !!page.cardRowOf({ dataset: { won: "sent-1" } }),
      // The id is encoded on the way into the attribute, so it has to be decoded on the way out or
      // any project id needing an escape would silently resolve to nothing.
      //
      // ESCAPED ON PURPOSE. This read `encodeURIComponent("ns-1")` and proved nothing: "ns-1"
      // encodes to itself, so dropping the decode left the assertion green. `odd-1` is the fixture
      // whose id needs escaping, and it is why there is a fixture with an odd id at all - today's
      // ids are uuids, but the id on this attribute comes off whatever the pipeline served, and one
      // decode is cheaper than finding out.
      encoded: !!page.cardRowOf({ dataset: { lost: encodeURIComponent("odd 1/2+3") } }),
      // The self-check that makes the line above load-bearing: this fixture's id really does change
      // shape under encodeURIComponent, so a handler that skipped the decode would compare
      // "odd%201%2F2%2B3" against "odd 1/2+3" and find nothing.
      encodedDiffers: encodeURIComponent("odd 1/2+3") !== "odd 1/2+3",
      missing: page.cardRowOf({ dataset: { won: "no-such-project" } }),
    };

    // ── Mark as closed ──
    out.markWon = await press("won", "sent-1");
    out.markWonRow = { wonAt: (page.row("sent-1") || {}).won_at };
    // …and it must not have opened the drawer over its own navigation.
    net.fails = true;
    out.markWonFailed = await press("won", "approved-1");
    net.fails = false;

    // ── Lost, dismissed ──
    answer.value = null;
    out.lostDismissed = await press("lost", "sent-1");

    // ── Lost on a SENT card: the portal route ──
    answer.value = { reason: "not_low_bid", note: "12% over Wilson.", outcome: "lost" };
    out.lostSent = await press("lost", "sent-1");

    // ── Lost on an UNSENT card: the draft route ──
    out.lostUnsent = await press("lost", "ns-1");
    out.lostUnsentOpts = out.lostUnsent.asked[0];

    // ── a hold from the card, both ways round ──
    answer.value = { reason: "on_hold", note: "GC pushed it to spring.", outcome: "hold" };
    out.holdSent = await press("lost", "approved-1");
    out.holdUnsent = await press("lost", "ns-1");
    answer.value = null;

    // ── the drawer must not open over any of it ──
    // A plain click on the card body still opens the drawer, which is what makes the four
    // assertions above about NOT opening it mean something.
    opened.length = 0;
    page.click(node({ className: "deal", dataset: { id: "sent-1" } }));
    out.plainCardClick = { openedDrawer: opened.slice() };
  } catch (e) {
    out.errors.run = e.constructor.name + ": " + e.message + "\n" + (e.stack || "");
  }
  process.stdout.write(JSON.stringify(out));
})().catch((e) => {
  process.stdout.write(JSON.stringify({ error: e.constructor.name + ": " + e.message,
                                        stack: String(e.stack || "") }));
});
