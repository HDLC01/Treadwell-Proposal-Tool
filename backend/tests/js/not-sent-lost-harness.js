"use strict";
/* Execute the "close this bid lost" control on the drawer for a project that was never sent.
 *
 * Hanz, 2026-08-19: "Allow to mark a proposal as lost tho in the Created not sent category."
 *
 * WHY EXECUTED, not grepped. Every claim here is behavioural and invisible to a source read:
 * which endpoint the button posts to (the DRAFT one, because an unsent project has no portal row),
 * that cancelling the dialog sends NOTHING, that the panel repaints past its own signature guard
 * afterwards, and that a failed save does not leave the rep looking at a bid it claims to have
 * closed. The 2026-08-12 outage was an unbound name in this same file with every source assertion
 * green.
 *
 * Usage: node not-sent-lost-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];
const SRC = fs.readFileSync(path.join(ROOT, "js", "portal.js"), "utf8");

const REASONS = {
  price: "Price", another_contractor: "Another contractor", canceled: "Project canceled",
  scope_changed: "Scope changed", timing: "Timing", other: "Other",
};

function source(name) {
  const re = new RegExp("^  function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name);
  return m[0];
}

/** A node whose querySelector hands back one stable stub per selector, so a test can set
 *  `[data-why].value` and then fire `[data-go]`'s click the way a person would. Returning a fresh
 *  node per call — the cheaper stub — would silently break that: the dialog would read a different
 *  node from the one the test wrote to, and every "confirm" would fall through to its `|| "other"`
 *  default and still look like it worked. */
function makeNode(tag, dom) {
  const node = {
    tag, id: "", className: "", value: "", textContent: "", disabled: false,
    dataset: {}, style: {}, listeners: {}, _sels: new Map(), _html: "",
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    removeEventListener(t, fn) {
      this.listeners[t] = (this.listeners[t] || []).filter((f) => f !== fn);
    },
    setAttribute() {}, getAttribute: () => null, appendChild() {}, focus() {},
    remove() { dom.removed.push(this); },
    closest: () => null,
    querySelectorAll: () => [],
    get innerHTML() { return this._html; },
    set innerHTML(h) {
      this._html = h;
      // Register ids out of the markup exactly as the browser would after an innerHTML write —
      // this is what makes $("ns-lost") resolve to something clickable.
      const re = /id="([^"]+)"/g;
      let m;
      while ((m = re.exec(h))) {
        if (!dom.byId.has(m[1]) || dom.byId.get(m[1])._owner !== this) {
          const child = makeNode("div", dom);
          child.id = m[1];
          child._owner = this;
          dom.byId.set(m[1], child);
        }
      }
      dom.ids = new Set([...dom.byId.keys()]);
    },
    querySelector(sel) {
      if (!this._sels.has(sel)) this._sels.set(sel, makeNode("div", dom));
      return this._sels.get(sel);
    },
  };
  return node;
}

function fire(node, type, ev) {
  const fns = (node && node.listeners && node.listeners[type]) || [];
  fns.forEach((fn) => fn(ev || { target: node, preventDefault() {} }));
  return fns.length;
}

function makeDom() {
  const dom = { byId: new Map(), ids: new Set(), appended: [], removed: [], keyHandlers: [] };
  const drawer = makeNode("aside", dom);
  drawer.id = "drawer";
  dom.byId.set("drawer", drawer);
  dom.document = {
    getElementById: (id) => dom.byId.get(id) || null,
    createElement: (t) => makeNode(t, dom),
    body: { appendChild(n) { dom.appended.push(n); } },
    addEventListener(t, fn) { if (t === "keydown") dom.keyHandlers.push(fn); },
    removeEventListener(t, fn) {
      if (t === "keydown") dom.keyHandlers = dom.keyHandlers.filter((f) => f !== fn);
    },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
  return dom;
}

/** renderNotSent, wireNotSentLost and the dialog in ONE closure, because in portal.js they share
 *  module scope: the handler calls renderNotSent back and both read and write DRAWER_SIG. Lifting
 *  them separately would give each its own guard and the repaint assertions would prove nothing. */
function lift(deps) {
  const keys = Object.keys(deps);
  const fact = /^  const fact = [\s\S]*?;$/m.exec(SRC);
  if (!fact) throw new Error("could not lift fact");
  const body =
    'let DRAWER_SIG = ""; let ACTIVE_SEC = null; const SEC_TABS = { proposal: 1 };'
    + ' const sigHistory = []; const panelCalls = []; const assignCalls = [];\n'
    + fact[0] + "\n" + source("drawerHead") + "\n" + source("secTab") + "\n"
    // The dialog is lifted FOR REAL. It is the half of this feature a person actually argues with,
    // and its copy changes for an unsent bid — a stub returning a reason would assert nothing about
    // either.
    + source("lostReasonDialog") + "\n"
    + source("renderNotSent") + "\n" + source("wireNotSentLost") + "\n"
    // Recorded rather than lifted: applySecPanel reaches for ALL_SEC_CARDS/SEC_ELIGIBLE and two
    // lazy fetches, the estimator picker is another file's subject, and the notify roster is a
    // network read. Recording each means a RENAME in portal.js still fails loudly here.
    + "function applySecPanel() { panelCalls.push(ACTIVE_SEC); }\n"
    + "function wireNotSentAssign(pid) { assignCalls.push(pid); }\n"
    + "function loadNotSentNotify() {}\n"
    + "return { renderNotSent, wireNotSentLost, lostReasonDialog,"
    + "         sig: () => DRAWER_SIG, setSig: (v) => { DRAWER_SIG = v; },"
    + "         panelCalls, assignCalls };";
  return new Function(...keys, body)(...keys.map((k) => deps[k]));
}

function harness(row, opts) {
  const o = opts || {};
  const dom = makeDom();
  const requests = [];
  const painted = [];
  const deps = {
    document: dom.document,
    $: (id) => dom.document.getElementById(id),
    esc: (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
    avatar: (e) => '<span class="av">' + String(e)[0] + "</span>",
    nameOf: (e) => e,
    isAssigned: (p) => !!p.assigned_estimator,
    estimatorOf: (p) => String(p.assigned_estimator || p.estimator_email || ""),
    // crm-core's real pair. A stub returning false would leave the reactivate branch of this panel
    // unrendered in every case, including the ones about reopening.
    isLost: (p) => String((p && p.proposal_status) || "") === "closed_lost",
    lostReason: (p) => REASONS[((p && p.followup_state) || {}).closed_lost_reason] || "",
    C: { LOST_REASON: REASONS },
    cardTotal: () => null,
    money: (n) => "$" + n,
    TW: { fmtBizDate: (d) => String(d) },
    api: (p, init) => {
      requests.push({ path: p, method: (init && init.method) || "GET",
                      body: JSON.parse((init && init.body) || "null") });
      return Promise.resolve(o.saveFails
        ? { ok: false, status: 500, json: () => Promise.resolve({ error: "postgrest down" }) }
        : { ok: true, status: 200, json: () => Promise.resolve({ ok: true }) });
    },
    load: () => painted.push("board"),
    closeDrawer: () => {},
    loadEstimators: () => Promise.resolve([]),
    window: { location: { assign() {} } },
  };
  const m = lift(deps);
  m.renderNotSent("d-1", row);
  return { dom, requests, painted, m, deps };
}

/** Walk the whole flow: press the control, answer the dialog, let the request settle. */
async function clickLost(h, answer) {
  const btn = h.dom.byId.get("ns-lost");
  if (!btn) return { opened: false };
  // The DOM stub registers ids out of the markup but does not parse text nodes, so the button
  // arrives with an empty label. Seed it, or "the label goes back to what it said" is unfalsifiable:
  // the handler restores `orig`, and an empty orig restores to empty whether or not it tried.
  btn.textContent = "Mark closed lost";
  fire(btn, "click");
  await Promise.resolve();                  // let the handler reach `await lostReasonDialog`
  const dlg = h.dom.appended[h.dom.appended.length - 1];
  if (!dlg) return { opened: false, btn };
  const out = { opened: true, btn, dlg, html: dlg.innerHTML };
  if (answer === "cancel") fire(dlg.querySelector("[data-x]"), "click");
  else if (answer === "escape") h.dom.keyHandlers.forEach((fn) => fn({ key: "Escape" }));
  else if (answer === "backdrop") fire(dlg, "click", { target: dlg });
  else {
    dlg.querySelector("[data-why]").value = answer;
    fire(dlg.querySelector("[data-go]"), "click");
  }
  // The dialog's resolve, the api() promise and its .json() each need a turn.
  for (let i = 0; i < 8; i++) await Promise.resolve();
  out.removed = h.dom.removed.length;
  return out;
}

const LIVE = { project_name: "Nearman Creek", not_sent: true,
               estimator_email: "kyle@wetreadwell.com", drafted_at: "2026-08-10" };
const LOST = Object.assign({}, LIVE, { proposal_status: "closed_lost",
                                       followup_state: { closed_lost_reason: "another_contractor" } });

(async () => {
  const out = {};

  // 1. the control is offered on a live bid, and the reactivate half is not
  {
    const h = harness(LIVE);
    out.live = {
      html: h.dom.byId.get("drawer").innerHTML,
      hasLost: h.dom.ids.has("ns-lost"),
      hasReopen: h.dom.ids.has("ns-reopen"),
    };
  }

  // 2. cancelling, escaping and clicking the backdrop each send NOTHING
  for (const how of ["cancel", "escape", "backdrop"]) {
    const h = harness(LIVE);
    const r = await clickLost(h, how);
    out["dismiss_" + how] = { opened: r.opened, requests: h.requests.length,
                              removed: r.removed, disabled: r.btn && r.btn.disabled };
  }

  // 3. the dialog's own copy, on a bid nobody ever sent
  {
    const h = harness(LIVE);
    const r = await clickLost(h, "cancel");
    out.dialog = { html: r.html };
  }
  {
    // …and the sent wording, so the branch is proven to differ rather than assumed to. The dialog
    // builds its markup synchronously and only its RESOLUTION is deferred, so read the markup
    // first and dismiss it after — awaiting the promise before anything clicks leaves node with
    // nothing to run and it exits silently with no output at all.
    const h = harness(LIVE);
    const pending = h.m.lostReasonDialog(LIVE);            // no opts → the sent wording
    const d = h.dom.appended[h.dom.appended.length - 1];
    out.dialogSent = { html: d ? d.innerHTML : "" };
    if (d) fire(d.querySelector("[data-x]"), "click");
    await pending;
  }

  // 4. confirming: the request, the repaint, the board reload
  {
    const h = harness(LIVE);
    h.m.setSig("guard-me");
    const r = await clickLost(h, "timing");
    const html = h.dom.byId.get("drawer").innerHTML;
    out.confirmed = {
      requests: h.requests,
      painted: h.painted,
      // The signature the guard now holds. It has to be the NEW state's, not "guard-me" and not
      // the old row's, or the panel the rep is looking at still says "Mark closed lost".
      sigAfter: h.m.sig(),
      html,
      hasLost: html.indexOf('id="ns-lost"') >= 0,
      hasReopen: html.indexOf('id="ns-reopen"') >= 0,
      opened: r.opened,
    };
  }

  // 5. a reason left at the default still sends a real one
  {
    const h = harness(LIVE);
    const r = await clickLost(h, "");
    out.defaultReason = { requests: h.requests, opened: r.opened };
  }

  // 6. an already-closed bid offers reactivate, and it posts no reason
  {
    const h = harness(LOST);
    const reopen = h.dom.byId.get("ns-reopen");
    out.lostPanel = {
      html: h.dom.byId.get("drawer").innerHTML,
      hasReopen: h.dom.ids.has("ns-reopen"),
      hasLost: h.dom.ids.has("ns-lost"),
    };
    if (reopen) {
      fire(reopen, "click");
      for (let i = 0; i < 8; i++) await Promise.resolve();
    }
    out.reopened = { requests: h.requests, painted: h.painted,
                     html: h.dom.byId.get("drawer").innerHTML,
                     appended: h.dom.appended.length };
  }

  // 7. a failed save must not claim the bid is closed
  {
    const h = harness(LIVE, { saveFails: true });
    const r = await clickLost(h, "price");
    const note = h.dom.byId.get("ns-lost-note");
    out.failed = {
      requests: h.requests.length,
      painted: h.painted.length,
      note: note ? note.textContent : null,
      btnDisabled: r.btn ? r.btn.disabled : null,
      btnLabel: r.btn ? r.btn.textContent : null,
      html: h.dom.byId.get("drawer").innerHTML,
    };
  }

  process.stdout.write(JSON.stringify(out));
})().catch((e) => {
  process.stdout.write(JSON.stringify({ error: e.constructor.name + ": " + e.message,
                                        stack: String(e.stack || "") }));
});
