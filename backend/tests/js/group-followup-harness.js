"use strict";
/* EXECUTE the drawer's follow-up task card for a SCOPE GROUP, and the "Decide the other scopes" card.
 *
 * The portal (2026-10-24) chases a project of several scopes as ONE project: its follow-up task lists
 * every scope it covers (`scope_group`, `scopes`), and when one scope is approved it raises a
 * decision task (stage 'decision') asking what to do with the others. This runs the REAL renderers
 * and wiring out of frontend/js/portal.js -- followupTaskHtml, followupDecisionHtml, wireFuDecision,
 * fuDecide, fuSettle -- in one lifted scope holding only what portal.js binds itself,
 * with the page's edges stubbed: the network (`api`), the confirmation dialog
 * (`TW.confirmDanger`) and the repaint the settle triggers (`renderDetail`, `load`, `openDetail`).
 *
 * WHAT IT PRODUCES, for test_group_followup_ui.py:
 *   reminders    a cadence reminder task, ungrouped and grouped, in every shape the pipeline
 *                serves: since 2026-10-28 the worker emails the customer itself, so each draws
 *                NOTHING (no card, no Send);
 *   decision     the decision card: what it renders and what it leaves out, the enable rule as
 *                the controls change, every request each button sends, the dialog it asks
 *                through, and what each refusal and success says;
 *   sentLog      the Follow-ups page's words for the new templates, from followups-core.js.
 *
 * (The SNAPSHOT MODE and group-followup-ungrouped.json went on 2026-10-28: they pinned the remind-
 * only reminder card byte for byte, and that card is gone.)
 *
 * Usage: node group-followup-harness.js <frontend-dir>  ->  one line of JSON
 */
const path = require("path");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);
const C = require(path.join(ROOT, "js", "crm-core.js"));
const src = L.read(path.join(ROOT, "js", "portal.js"));
const IND = { indent: "  ", where: "portal.js" };

// ── the DOM: a bag of the markup last rendered, answering lookups out of it ────────────────────
const dom = { html: "", els: new Map(), lookups: [] };
function attrsOf(tagRe) {
  const out = [];
  const OPEN = /<([a-zA-Z0-9]+)((?:\s+[-a-zA-Z0-9:_]+(?:="[^"]*")?)*)\s*\/?>/g;
  let m;
  while ((m = OPEN.exec(dom.html))) {
    const attrs = {};
    const ar = /([-a-zA-Z0-9:_]+)(?:="([^"]*)")?/g;
    let a;
    while ((a = ar.exec(m[2] || ""))) attrs[a[1]] = a[2] === undefined ? "" : a[2];
    if (tagRe(attrs)) out.push(attrs);
  }
  return out;
}
function makeEl(key, attrs) {
  const el = {
    key, attrs: attrs || {}, dataset: {}, listeners: {}, textContent: "", value: "",
    disabled: "disabled" in (attrs || {}), checked: false, hidden: false, open: false,
    classes: new Set(String((attrs || {}).class || "").split(/\s+/).filter(Boolean)),
    get classList() {
      const c = this.classes;
      return { add: (x) => c.add(x), remove: (x) => c.delete(x), contains: (x) => c.has(x),
               toggle: (x, on) => { const v = on === undefined ? !c.has(x) : !!on;
                                    if (v) c.add(x); else c.delete(x); return v; } };
    },
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    fire(t) { return Promise.all((this.listeners[t] || []).map((f) => f({ target: this }))); },
    querySelectorAll(sel) {
      const m = /^\[([-a-z]+)\]$/.exec(sel);
      if (!m) throw new Error("the harness DOM only answers [attr] lists, asked for " + sel);
      return attrsOf((a) => m[1] in a).map((a) => dom.el(sel + "=" + a[m[1]], a));
    },
    focus() {},
  };
  for (const k of Object.keys(el.attrs)) {
    if (k.startsWith("data-")) {
      el.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = el.attrs[k];
    }
  }
  if ("value" in el.attrs) el.value = el.attrs.value;
  return el;
}
dom.el = (key, attrs) => {
  if (!dom.els.has(key)) dom.els.set(key, makeEl(key, attrs));
  return dom.els.get(key);
};
dom.paint = (html) => { dom.html = html; dom.els.clear(); dom.lookups.length = 0; };
const document = {
  getElementById(id) {
    const hit = attrsOf((a) => a.id === id)[0];
    dom.lookups.push({ id, present: !!hit });
    return hit ? dom.el("#" + id, hit) : null;
  },
};

// ── the page's edges ─────────────────────────────────────────────────────────────────────────
const net = { requests: [], answers: [], throws: false };
function api(p, init) {
  net.requests.push({ path: p, method: (init && init.method) || "GET",
                      body: init && init.body ? JSON.parse(init.body) : null });
  if (net.throws) return Promise.reject(new Error("offline"));
  const hit = net.answers.find(([re]) => re.test(p));
  const ans = hit ? hit[1] : { status: 200, body: { ok: true } };
  return Promise.resolve({ ok: ans.status < 400, status: ans.status,
                           json: () => Promise.resolve(ans.body) });
}
const danger = { answer: true, calls: [] };
const TW = {
  fmtBizDate: (s) => "D[" + s + "]",
  fmtBizDay: (s) => "Day[" + s + "]",
  bizToday: () => "2026-10-25",
  confirmDanger: (o) => { danger.calls.push(o || {}); return Promise.resolve(danger.answer); },
};
const repaints = { renderDetail: 0, load: 0, openDetail: 0 };
const stubs = {
  renderDetail: () => { repaints.renderDetail++; },
  load: () => { repaints.load++; return Promise.resolve(); },
  openDetail: () => { repaints.openDetail++; },
};

// ── the lifted scope ─────────────────────────────────────────────────────────────────────────
const fns = [
  "followupTaskHtml", "fuScopeNow", "fuScopeOpen", "fuScopeChip", "fuScopeNames",
  "followupDecisionHtml", "fuDecisionReady", "fuDecisionPicked", "fuTaskOf", "fuDecisionErrText",
  "fuDecisionDoneText", "fuDecide", "wireFuDecision", "fuSay", "fuSettle",
];
// `$` by its own pattern: _lib's declaration matcher ends the name on a word boundary, which a
// name that IS `$` never has.
const DOLLAR = L.grab(src, /\n {2}const \$ = \(id\) => document\.getElementById\(id\);/,
                      "portal.js's `const $`").trim();
const body = [
  DOLLAR, L.grabConst(src, "esc", IND), L.grabConst(src, "CHEV", IND),
  L.grabConst(src, "FU_TEMPLATE_LABEL", IND),
  L.grabConst(src, "FU_NOTICE", IND), L.grabConst(src, "DETAIL_CACHE", IND),
  "let ALL = []; let CUR_PID = null; let DRAWER_SIG = \"\";",
  fns.map((n) => L.liftSource(src, n, IND)).join("\n"),
  "return { " + fns.join(", ") + ", FU_NOTICE,",
  "  setAll: (rows) => { ALL = rows; }, setCur: (pid) => { CUR_PID = pid; },",
  "  sig: () => DRAWER_SIG };",
].join("\n");
const deps = { document, TW, C, api, renderDetail: stubs.renderDetail, load: stubs.load,
               openDetail: stubs.openDetail };
const page = new Function(...Object.keys(deps), body)(...Object.values(deps));

const tick = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 8; i++) await tick(); };

// ── cadence reminder tasks draw nothing ──────────────────────────────────────────────────────
// The pipeline's compact summary (_task_summary: no group keys at all on an ordinary task), the
// full task view (_task_view: the group keys present and null/empty), a deposit-stage one, one in
// flight, and a scope group's reminder for the whole project. Every one of these was a card with a
// Send button until 2026-10-28; the worker sends the customer email itself now.
const SUMMARY = { id: "t-1", status: "pending", template: "second_nudge", label: "Second nudge",
                  stage: "pre", due_at: "2026-10-22T12:00:00Z" };
const SCOPES = [{ proposal_id: "s1", label: "Breakroom", status: "sent" },
                { proposal_id: "s2", label: "Lab 1", status: "viewed" }];
function reminders() {
  const row = (t) => ({ proposal_id: "p1", project_name: "Nearman Creek", followup_task: t });
  return {
    summary: page.followupTaskHtml(row(SUMMARY)),
    sending: page.followupTaskHtml(row(Object.assign({}, SUMMARY, { status: "sending" }))),
    deposit: page.followupTaskHtml(
      row({ id: "t-2", status: "pending", template: "deposit_nudge", stage: "deposit" })),
    view: page.followupTaskHtml(row(Object.assign({}, SUMMARY, {
      proposal_id: "p1", scope_group: null, scopes: [], approved_scope: null,
      link_proposal_id: "p1" }))),
    group: page.followupTaskHtml(row(Object.assign({}, SUMMARY, { id: "g-1", label: "Check-in",
      template: "checkin", proposal_id: "s1", scope_group: "grp-1", scopes: SCOPES,
      approved_scope: null, link_proposal_id: "s1" }))),
    none: page.followupTaskHtml(row(null)),
  };
}

const out = { errors: {} };
async function run() {
  out.reminders = reminders();

  // ── the decision card ──────────────────────────────────────────────────────────────────────
  const DEC_SCOPES = [{ proposal_id: "s2", label: "Lab 1", status: "sent" },
                      { proposal_id: "s3", label: "Lab 2", status: "viewed" },
                      // Approved since the task was raised: shown, never tickable.
                      { proposal_id: "s4", label: "Office", status: "sent" }];
  const DEC = { id: "d-1", status: "pending", template: "scope_decision",
                label: "Decide the other scopes", stage: "decision", proposal_id: "s1",
                due_at: "2026-10-24T12:00:00Z", scope_group: "grp-1", scopes: DEC_SCOPES,
                approved_scope: { proposal_id: "s1", label: "Breakroom" },
                link_proposal_id: "s1" };
  const decRows = () => [
    { proposal_id: "s1", project_name: "Acme Labs", proposal_status: "approved",
      followup_task: Object.assign({}, DEC) },
    { proposal_id: "s2", project_name: "Acme Labs", proposal_status: "sent" },
    { proposal_id: "s3", project_name: "Acme Labs", proposal_status: "viewed" },
    { proposal_id: "s4", project_name: "Acme Labs", proposal_status: "approved" },
  ];
  const el = (id) => document.getElementById(id);
  const box = (sid) => dom.el("[data-fu-scope]=" + sid,
                              attrsOf((a) => a["data-fu-scope"] === sid)[0]);
  const alertText = () => { const a = el("fu-task-alert");
                            return a ? { text: a.textContent, err: a.classList.contains("is-err") } : null; };
  let rows;
  function openDecision() {
    rows = decRows();
    page.setAll(rows);
    page.setCur("s1");
    page.FU_NOTICE.clear();
    dom.paint(page.followupTaskHtml(rows[0]));
    page.wireFuDecision("s1", "d-1");
    net.requests.length = 0;
    net.answers = [];
    net.throws = false;
    danger.calls.length = 0;
    danger.answer = true;
    repaints.load = 0;
  }
  async function readyToClose() {
    box("s2").checked = true;
    await box("s2").fire("change");
    el("fu-dec-reason").value = "not_low_bid";
    await el("fu-dec-reason").fire("change");
    el("fu-dec-note").value = "They went with the lab floors only";
    await el("fu-dec-note").fire("input");
  }
  const reqs = () => net.requests.filter((r) => /scope-decision$/.test(r.path))
    .map((r) => ({ path: r.path, method: r.method, body: r.body }));
  try {
    out.decision = {};
    openDecision();
    out.decision.html = dom.html;
    // Every id the wiring reached for, and whether this paint rendered it.
    out.decision.lookups = dom.lookups.slice();
    out.decision.boxes = attrsOf((a) => "data-fu-scope" in a)
      .map((a) => ({ id: a["data-fu-scope"], disabled: "disabled" in a }));
    out.decision.reasons = attrsOf((a) => "value" in a && !("id" in a) && !("type" in a))
      .map((a) => a.value);
    // Painting the decision card asks the portal for nothing: it has no email to draft.
    out.decision.draftRequests = net.requests.map((r) => r.path);

    // THE ENABLE RULE, step by step.
    const closeOff = () => !!el("fu-dec-close").disabled;
    const steps = { start: closeOff() };
    box("s2").checked = true; await box("s2").fire("change"); steps.ticked = closeOff();
    el("fu-dec-reason").value = "not_low_bid"; await el("fu-dec-reason").fire("change");
    steps.reason = closeOff();
    el("fu-dec-note").value = "   "; await el("fu-dec-note").fire("input"); steps.blankNote = closeOff();
    el("fu-dec-note").value = "They went with the lab floors only";
    await el("fu-dec-note").fire("input"); steps.all = closeOff();
    box("s2").checked = false; await box("s2").fire("change"); steps.unticked = closeOff();
    // A box for a scope approved since cannot count, even if something ticks it.
    box("s4").checked = true; await box("s4").fire("change"); steps.onlyApprovedTicked = closeOff();
    box("s4").checked = false;
    el("fu-dec-reason").value = ""; box("s2").checked = true; await box("s2").fire("change");
    steps.noReason = closeOff();
    out.decision.steps = steps;
    // Pressed while not ready (a stale enable): refused on the page, nothing sent, nothing asked.
    el("fu-dec-close").disabled = false;
    await el("fu-dec-close").fire("click");
    await settle();
    out.decision.pressedNotReady = { requests: reqs(), asked: danger.calls.length, alert: alertText() };

    // CLOSE, the dialog says no: nothing sent.
    openDecision();
    await readyToClose();
    danger.answer = false;
    await el("fu-dec-close").fire("click");
    await settle();
    out.decision.closeDeclined = { requests: reqs(), asked: danger.calls.slice() };

    // CLOSE, confirmed: the ticked scope, the reason, the note. The portal skipped one.
    openDecision();
    await readyToClose();
    box("s3").checked = true; await box("s3").fire("change");
    net.answers = [[/scope-decision$/, { status: 200, body: { ok: true, outcome: "close",
      closed: ["s2"], failed: [], skipped: ["s3"], task: { id: "d-1", status: "decided" } } }]];
    await el("fu-dec-close").fire("click");
    await settle();
    out.decision.close = { requests: reqs(), asked: danger.calls.slice(),
                           notice: page.FU_NOTICE.get("s1") || null,
                           rowTask: rows[0].followup_task, reloaded: repaints.load };

    // LEAVE and KEEP: no dialog, an explicit empty list.
    for (const action of ["leave", "keep"]) {
      openDecision();
      net.answers = [[/scope-decision$/, { status: 200, body: { ok: true, outcome: action,
        task: { id: "d-1", status: "decided" },
        warnings: action === "keep" ? ["resume_not_recorded"] : undefined } }]];
      await el("fu-dec-" + action).fire("click");
      await settle();
      out.decision[action] = { requests: reqs(), asked: danger.calls.length,
                               notice: page.FU_NOTICE.get("s1") || null,
                               rowTask: rows[0].followup_task };
    }

    // THE PORTAL'S REFUSALS: said in words, the card stays.
    const refusals = {
      scopeNotOpen: [409, { ok: false, error: "scope_not_open", scope_ids: ["s3"] }],
      scopesNotOpen: [409, { ok: false, error: "scope_not_open", scope_ids: ["s2", "s3"] }],
      invalidReason: [400, { ok: false, error: "invalid_reason" }],
      noteRequired: [400, { ok: false, error: "note_required" }],
      noScopes: [400, { ok: false, error: "no_scopes" }],
      unknownScope: [400, { ok: false, error: "unknown_scope" }],
      portalDown: [502, { ok: false, error: "Could not reach the customer portal." }],
    };
    out.decision.refusals = {};
    for (const [name, [status, bodyOut]] of Object.entries(refusals)) {
      openDecision();
      await readyToClose();
      net.answers = [[/scope-decision$/, { status, body: bodyOut }]];
      await el("fu-dec-close").fire("click");
      await settle();
      out.decision.refusals[name] = { alert: alertText(), stillThere: !!rows[0].followup_task,
                                      buttonBack: !el("fu-dec-close").disabled,
                                      reloaded: repaints.load };
    }
    // Somebody else answered first: the card goes, with a sentence.
    openDecision();
    net.answers = [[/scope-decision$/, { status: 409, body: { ok: false, error: "already_decided",
                                                              status: "decided" } }]];
    await el("fu-dec-leave").fire("click");
    await settle();
    out.decision.alreadyDecided = { notice: page.FU_NOTICE.get("s1") || null,
                                    rowTask: rows[0].followup_task };
    // The network itself failed.
    openDecision();
    net.throws = true;
    await el("fu-dec-leave").fire("click");
    await settle();
    out.decision.offline = { alert: alertText(), stillThere: !!rows[0].followup_task };
    net.throws = false;
  } catch (e) {
    out.errors.decision = e.constructor.name + ": " + e.message + "\n" + e.stack;
  }

  // ── the Follow-ups page's words for what the portal can now write ──────────────────────────
  try {
    const F = require(path.join(ROOT, "js", "followups-core.js"));
    const line = (template, audience) =>
      F.sentLine({ kind: "auto_email", detail: { template, audience } }).what;
    out.sentLog = {
      staff_followup_due: line("staff_followup_due", "staff"),
      staff_scope_decision: line("staff_scope_decision", "staff"),
      scope_decision: F.FU_TEMPLATE_LABEL.scope_decision || null,
      resume: F.sentLine({ kind: "staff_note", detail: { action: "scope_group_resume" } }).what,
    };
  } catch (e) {
    out.errors.sentLog = e.constructor.name + ": " + e.message;
  }
}

run().then(() => process.stdout.write(JSON.stringify(out) + "\n"),
           (e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
