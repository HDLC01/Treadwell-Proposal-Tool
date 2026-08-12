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
  const body = 'let DRAWER_SIG = "";\n' + source("renderNotSent") + "\n" +
    source("wireNotSentAssign") + "\nreturn { renderNotSent, wireNotSentAssign, sig: () => DRAWER_SIG };";
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
    estimatorOf: (p) => String(p.assigned_estimator || p.estimator_email || ""),
    cardTotal: () => null,
    money: (n) => "$" + n,
    TW: { fmtBizDate: (d) => String(d) },
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
  return { document, requests, painted, render: pair.renderNotSent, sig: pair.sig, deps };
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
