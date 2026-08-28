"use strict";
/* Execute the real "Created but not sent" drawer out of portal.js: the estimator picker, the
 * assign request it sends, and the repaint afterwards.
 *
 * WHY EXECUTED. On 2026-08-12 an unbound identifier in this very file took the Active Projects
 * board down on prod with every source assertion green. And the claims here are behavioural: which
 * endpoint the button posts to (the DRAFT one, because an unsent project has no portal row), what
 * the select is pre-set to, and whether the drawer shows the new name afterwards — the last of
 * which depends on a signature guard that a grep cannot see.
 *
 * Usage: node not-sent-assign-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

// argv[1] is this script when run as a file; the frontend dir is the first real argument.
const ROOT = process.argv[2];
const SRC = fs.readFileSync(path.join(ROOT, "js", "portal.js"), "utf8");
// The real predicates, for the Won control renderNotSent also paints (2026-08-19) — see the C dep
// below. Stubbing them would choose which branch of that control this panel renders.
const CORE = require(path.join(path.resolve(ROOT), "js", "crm-core.js"));

const ROSTER = [
  { email: "kyle@wetreadwell.com", name: "Kyle Loseke" },
  { email: "rj@wetreadwell.com", name: "RJ Buchanan" },
];

// ── a DOM stub that keeps ids, so $() behaves and innerHTML is readable ──────
function makeDom() {
  const byId = new Map();
  function el(tag) {
    const node = {
      tag, id: "", value: "", disabled: false, textContent: "", title: "",
      className: "", dataset: {}, style: {}, listeners: {},
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
      setAttribute(k, v) { if (k === "id") { this.id = v; byId.set(v, this); } },
      getAttribute: () => null,
      appendChild() {}, remove() {}, focus() {}, closest: () => null,
      get innerHTML() { return this._html || ""; },
      // Registering ids out of the assigned HTML is what makes $("ns-assign") resolve, exactly as
      // the browser would after an innerHTML write.
      set innerHTML(h) {
        this._html = h;
        const re = /id="([^"]+)"/g;
        let m;
        while ((m = re.exec(h))) {
          if (!byId.has(m[1]) || byId.get(m[1])._owner !== this) {
            const child = el("div");
            child.id = m[1];
            child._owner = this;
            // A <select> in the markup has to behave like one for the picker code.
            if (/<select[^>]*id="" ?/.test("") ) { /* no-op: kept simple */ }
            byId.set(m[1], child);
          }
        }
      },
      querySelector(sel) {
        const m = /^\[?([\w-]+)/.exec(sel.replace(/^\./, "").replace(/^\[/, "["));
        void m;
        const node2 = el("div");
        node2._sel = sel;
        return node2;
      },
      querySelectorAll: () => [],
      insertAdjacentHTML() {},
    };
    return node;
  }
  const drawer = el("aside");
  drawer.id = "drawer";
  byId.set("drawer", drawer);
  return {
    byId,
    getElementById: (id) => byId.get(id) || null,
    createElement: el,
    addEventListener() {},
    querySelector: () => null,
    querySelectorAll: () => [],
    body: { appendChild() {} },
    head: { appendChild() {} },
    documentElement: { classList: { add() {}, remove() {}, toggle() {} } },
  };
}

function source(name) {
  const re = new RegExp("^  function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name);
  return m[0];
}

/** Both functions inside ONE closure, because in portal.js they share module scope: renderNotSent
 *  calls wireNotSentAssign, the handler calls renderNotSent back, and both read and write the same
 *  `DRAWER_SIG`. Lifting them separately would give each its own copy of the guard and the test
 *  would prove nothing about the repaint. */
function liftPair(deps) {
  const keys = Object.keys(deps);
  // The REAL head and fact helpers too, not stubs. The 2026-08-13 drawer redesign moved
  // renderNotSent onto both of them, and this harness reported it as `drawerHead is not defined`
  // — which is precisely the class of failure (a name used but not bound) that took the board
  // down on prod once. Stubbing them would have hidden the coupling instead of proving it.
  const fact = /^  const fact = [\s\S]*?;$/m.exec(SRC);
  if (!fact) throw new Error("could not lift fact");
  const body = 'let DRAWER_SIG = ""; let ACTIVE_SEC = null; const SEC_TABS = { proposal: 1 };'
    + ' const notifyCalls = []; const panelCalls = []; const lostCalls = [];'
    + ' const wonCalls = []; const delCalls = [];\n'
    + fact[0] + "\n" + source("drawerHead") + "\n" +
    // renderNotSent now builds the same five-tab strip a sent project gets. `secTab` is lifted for
    // real — it is pure markup and cheap — but `applySecPanel` is recorded as a no-op here.
    //
    // That is a division of labour, not a gap: applySecPanel reaches for SEC_TABS, ALL_SEC_CARDS,
    // SEC_ELIGIBLE, the chat scroll and two lazy fetches, none of which this file has any business
    // standing up. THIS harness tests the estimator picker. The strip itself is executed for real in
    // drawer-render-harness.js, which asserts all five tabs, their panels and their placeholder
    // copy. Recording the call rather than deleting it means a rename still fails loudly here.
    source("secTab") +
    "\nfunction applySecPanel() { panelCalls.push(ACTIVE_SEC); }" + "\n" +
    source("renderNotSent") + "\n" + source("wireNotSentAssign") +
    // renderNotSent also kicks off the notification picker, which is a network read this file has
    // no business making — it tests the ESTIMATOR control. Recorded as a call rather than lifted,
    // so a rename in portal.js still fails loudly here instead of being silently absent.
    "\nfunction loadNotSentNotify(pid) { notifyCalls.push(pid); }" +
    // Same division of labour for the close-lost control (2026-08-19). It has its own executed
    // tests in not-sent-lost-harness.js, where the dialog and the request are the subject; here it
    // is recorded so a rename still fails loudly rather than going quiet.
    "\nfunction wireNotSentLost(pid, row) { lostCalls.push(pid); }" +
    // nsHoldReason is lifted FOR REAL, unlike the wiring beside it, because renderNotSent's own
    // MARKUP calls it — three times, in the ternary that chooses between closed lost, on hold and
    // live. A stub would be choosing which of the three panels this file renders, which is the one
    // thing a stub must never decide. (2026-08-20: two of Kyle's eight close-out answers put a bid
    // on hold instead of closing it.)
    "\n" + source("nsHoldReason") +
    // Same again for the quoted comment: it is called from the closed-lost and on-hold
    // arms of the same ternary, so it is markup rather than wiring.
    "\n" + source("nsCloseNote") +
    // The by-hand Won control (2026-08-19). Its MARKUP is lifted for real — renderNotSent embeds it,
    // it is pure string-building, and a stub would decide what this panel contains — while its
    // WIRING is recorded, on the same division of labour as wireNotSentLost above: the request and
    // the repaint are drawer-render-harness.js's subject.
    "\n" + source("wonControlHtml") +
    "\nfunction wireWon(pid, row, repaint) { wonCalls.push(pid); }" +
    // Deleting a project (2026-08-24). The MARKUP is lifted for real, on the same division of
    // labour as wonControlHtml above: renderNotSent embeds it, and a stub would decide what this
    // panel contains. Note this file's `window` carries NO TWAuth, so the real function takes its
    // non-admin branch and renders "" -- which is the useful half here, because it proves the
    // section is absent for anybody who is not an admin rather than merely gated at the endpoint.
    // The WIRING is recorded: the dialog and the request are not-sent-lost-harness.js's subject.
    "\n" + source("deleteProjectHtml") +
    "\nfunction wireDeleteProject(pid, row) { delCalls.push(pid); }" +
    "\nreturn { renderNotSent, wireNotSentAssign, sig: () => DRAWER_SIG," +
    "         notifyCalls, panelCalls, lostCalls, wonCalls, delCalls };";
  return new Function(...keys, body)(...keys.map((k) => deps[k]));
}

function harness(row, opts) {
  const o = opts || {};
  const document = makeDom();
  const requests = [];
  const painted = [];
  const deps = {
    document,
    $: (id) => document.getElementById(id),
    esc: (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
    avatar: (e) => '<span class="av">' + String(e)[0] + "</span>",
    nameOf: (e) => (ROSTER.find((x) => x.email === e) || {}).name || e,
    isAssigned: (p) => !!p.assigned_estimator,
    // crm-core's own definitions, not stubs returning false: the panel branches on them for the
    // close-lost control, and a stub that always says "live" would leave the reactivate half of
    // this drawer unrendered and unexercised in every case below.
    isLost: (p) => String((p && p.proposal_status) || "") === "closed_lost",
    // crm-core's REAL maps, not a copy typed here. A copy is what let the tool and the portal
    // carry two labels for one key for weeks, and here it would let this file keep testing a
    // vocabulary the product had replaced (which is what happened on 2026-08-20).
    lostReason: (p) => CORE.LOST_REASON[((p && p.followup_state) || {}).closed_lost_reason] || "",
    estimatorOf: (p) => String(p.assigned_estimator || p.estimator_email || ""),
    cardTotal: () => null,
    // The WHOLE module, not a named subset, since 2026-08-28 — matching not-sent-lost-harness.
    //
    // It used to list exactly what the panel read (isWon, wonByHand, HOLD_REASON, followup,
    // pausedUntil), on the reasoning that a hand-copy could disagree with the page. That reasoning
    // was right and the list was still a trap: an allowlist has to be edited every time the lifted
    // code reaches for one more thing, and it fails LOUDLY AND ELSEWHERE when nobody does. Adding
    // the Hand it off control put `C.isHandedOff` inside wonControlHtml, which this file lifts for
    // real (see liftPair), and every test in it died on `C.isHandedOff is not a function` — a
    // failure about the estimator picker that had nothing to do with the estimator picker.
    //
    // Passing CORE keeps the property the list was protecting (these are the page's real
    // predicates, never re-implemented here) and drops the maintenance the list was charging for.
    C: CORE,
    // The module wrapper, which supplies Central's today. See the note in not-sent-lost-harness.
    pausedUntil: (p) => CORE.pausedUntil(p, "2026-08-21"),
    money: (n) => "$" + n,
    TW: { fmtBizDate: (d) => String(d), fmtBizDay: (d) => String(d) },
    loadEstimators: () => Promise.resolve(o.rosterFails ? [] : ROSTER),
    api: (p, init) => {
      requests.push({ path: p, method: (init && init.method) || "GET",
                      body: init && init.body });
      return Promise.resolve(o.saveFails
        ? { ok: false, status: 500, json: () => Promise.resolve({ error: "nope" }) }
        : { ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    },
    load: () => painted.push("board"),
    closeDrawer: () => {},
    openDetail: () => Promise.resolve(),
    window: { location: { assign() {} } },
  };
  const pair = liftPair(deps);
  return { document, requests, painted, render: pair.renderNotSent, sig: pair.sig, deps,
           delCalls: pair.delCalls };
}

const out = {};

// ── 1. the control is offered, and says what it is ───────────────────────────
{
  const h = harness({ project_name: "Nearman Creek", estimator_email: "kyle@wetreadwell.com" });
  h.render("d-1", { project_name: "Nearman Creek", estimator_email: "kyle@wetreadwell.com" });
  const html = h.document.getElementById("drawer").innerHTML;
  out.offered = {
    hasSelect: /id="ns-assign"/.test(html),
    hasButton: /id="ns-assign-btn"/.test(html),
    startsDisabled: /id="ns-assign"[^>]*disabled/.test(html),
    // The guess is still shown, with its question mark — the picker settles it, it does not
    // replace the fact that nobody has.
    stillShowsTheGuess: /Kyle Loseke\?/.test(html),
    unchangedActions: /data-go-files/.test(html) && /data-go-edit/.test(html),
    // The two invariants the 2026-08-13 redesign merge had to preserve, both of which a
    // mutation walked straight through until they were asserted:
    //   the control is actually VISIBLE (a `hidden` wrapper renders the ids and reaches nobody)
    pickerHidden: /class="ns-assign"[^>]*hidden/.test(html) ||
                  /<div class="sec"[^>]*hidden[^>]*>\s*<div class="lbl">Assign/.test(html),
    //   and the estimator is named ONCE — the merge's whole job was collapsing two renderers of
    //   that line into the facts grid, and nothing noticed when both came back.
    estimatorCells: (html.match(/fact-k">Estimator</g) || []).length,
  };
}

// ── 2. an unassigned project does not pre-select the guess ───────────────────
async function selectionCases() {
  {
    const h = harness({});
    h.render("d-1", { estimator_email: "kyle@wetreadwell.com" });   // author only, no assignment
    await new Promise((r) => setImmediate(r));
    const sel = h.document.getElementById("ns-assign");
    out.unassigned = { value: sel.value, enabled: !sel.disabled,
                       offersChoose: /Choose an estimator/.test(sel.innerHTML) };
  }
  {
    const h = harness({});
    h.render("d-1", { assigned_estimator: "rj@wetreadwell.com" });
    await new Promise((r) => setImmediate(r));
    const sel = h.document.getElementById("ns-assign");
    out.assigned = { value: sel.value,
                     noChoosePrompt: !/Choose an estimator/.test(sel.innerHTML) };
  }
  {
    // Somebody assigned who has since left the roster must stay listed, or the control reads as
    // "unassigned" and the truth is lost.
    const h = harness({});
    h.render("d-1", { assigned_estimator: "gone@wetreadwell.com" });
    await new Promise((r) => setImmediate(r));
    const sel = h.document.getElementById("ns-assign");
    out.departed = { value: sel.value, listed: /no longer listed/.test(sel.innerHTML) };
  }
  {
    const h = harness({}, { rosterFails: true });
    h.render("d-1", {});
    await new Promise((r) => setImmediate(r));
    out.rosterDown = {
      says: h.document.getElementById("ns-assign").innerHTML,
      note: h.document.getElementById("ns-assign-note").textContent,
      requests: h.requests.length,
    };
  }
}

// ── 3. the request: the DRAFT endpoint, with the chosen address ──────────────
async function saveCases() {
  {
    const h = harness({});
    h.render("d-77", { assigned_estimator: "" });
    await new Promise((r) => setImmediate(r));
    const sel = h.document.getElementById("ns-assign");
    const btn = h.document.getElementById("ns-assign-btn");
    sel.value = "rj@wetreadwell.com";
    (btn.listeners.click || []).forEach((fn) => fn({ target: btn }));
    for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r));
    const req = h.requests[0] || {};
    out.save = {
      path: req.path, method: req.method,
      body: req.body ? JSON.parse(req.body) : null,
      refreshedBoard: h.painted.includes("board"),
      // The drawer must show the name it just saved. renderNotSent is signature-guarded against
      // the 12s poll, so this only works if the handler clears the guard.
      showsNewName: /RJ Buchanan/.test(h.document.getElementById("drawer").innerHTML),
    };
  }
  {
    const h = harness({});
    h.render("d-77", {});
    await new Promise((r) => setImmediate(r));
    const btn = h.document.getElementById("ns-assign-btn");
    // Nothing chosen → no request at all.
    (btn.listeners.click || []).forEach((fn) => fn({ target: btn }));
    await new Promise((r) => setImmediate(r));
    out.noChoice = { requests: h.requests.length };
  }
  {
    const h = harness({}, { saveFails: true });
    h.render("d-77", {});
    await new Promise((r) => setImmediate(r));
    const sel = h.document.getElementById("ns-assign");
    const btn = h.document.getElementById("ns-assign-btn");
    sel.value = "kyle@wetreadwell.com";
    (btn.listeners.click || []).forEach((fn) => fn({ target: btn }));
    for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r));
    out.failed = {
      note: h.document.getElementById("ns-assign-note").textContent,
      buttonUsableAgain: h.document.getElementById("ns-assign-btn").disabled === false,
      // A failed save must not paint a name nobody stored.
      claimsSuccess: /RJ Buchanan/.test(h.document.getElementById("drawer").innerHTML),
    };
  }
}

selectionCases().then(saveCases).then(() => console.log(JSON.stringify(out)));
