"use strict";
/* Execute the close-out control on the drawer for a project that was never sent.
 *
 * Hanz, 2026-08-19: "Allow to mark a proposal as lost tho in the Created not sent category."
 * Hanz, 2026-08-20: Kyle's own eight answers, two of which put the bid ON HOLD instead of killing
 * it; a required comment on every one of them; and a prompt naming the destination before a card
 * is brought back.
 *
 * WHY EXECUTED, not grepped. Every claim here is behavioural and invisible to a source read:
 * which endpoint the button posts to (the DRAFT one, because an unsent project has no portal row),
 * that the confirm button will not fire with an empty comment, that "Project on Hold" sends a hold
 * and not a loss, that cancelling the dialog sends NOTHING, that the panel repaints past its own
 * signature guard afterwards, and that a failed save does not leave the rep looking at a bid it
 * claims to have closed. The 2026-08-12 outage was an unbound name in this same file with every
 * source assertion green.
 *
 * Usage: node not-sent-lost-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];
const SRC = fs.readFileSync(path.join(ROOT, "js", "portal.js"), "utf8");
// The real module. Not a copy of its maps typed here: a copy is exactly what let the tool and the
// portal carry two different labels for one reason key for weeks, and here it would let this file
// go on testing a vocabulary the product had already replaced.
const CORE = require(path.join(path.resolve(ROOT), "js", "crm-core.js"));

function source(name) {
  const re = new RegExp("^  function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n  \\}", "m");
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + name);
  return m[0];
}

/** The value of a module-level `const NAME = <number>;`. One use: HOLD_MONTHS. Read out of
 *  portal.js rather than typed here, so this file cannot assert a pause length the page does not
 *  ship. */
function numConst(name) {
  const m = new RegExp("\\n\\s*const " + name + " = (\\d+);").exec(SRC);
  if (!m) throw new Error("const " + name + " is gone from portal.js — rewrite this harness");
  return Number(m[1]);
}
const HOLD_MONTHS = numConst("HOLD_MONTHS");

/** A node whose querySelector hands back one stable stub per selector, so a test can set
 *  `[data-why].value`, type into `[data-note]`, and then fire `[data-go]`'s click the way a person
 *  would. Returning a fresh node per call — the cheaper stub — would silently break that: the
 *  dialog would read a different node from the one the test wrote to, and every "confirm" would
 *  fall through to its `|| "other"` default and still look like it worked. */
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
    + ' const sigHistory = []; const panelCalls = []; const assignCalls = [];'
    + " const HOLD_MONTHS = " + HOLD_MONTHS + ";\n"
    + fact[0] + "\n" + source("drawerHead") + "\n" + source("secTab") + "\n"
    // The dialog is lifted FOR REAL. It is the half of this feature a person actually argues with:
    // its copy changes for an unsent bid, its options are Kyle's list, and its confirm button is
    // the tool's first disabled-until-valid control. A stub returning an answer would assert
    // nothing about any of that.
    + source("closeOutDialog") + "\n"
    // The panel's own markup calls this three times, in the ternary choosing between closed lost,
    // on hold and live, so it is not optional the way an awaited dialog is.
    + source("nsHoldReason")
    // The quoted comment in the closed-lost and on-hold copy. Lifted for the same reason
    // nsHoldReason is: renderNotSent calls it inside a template literal, so a missing bind
    // is a ReferenceError that takes out the whole drawer - which is exactly what it did on
    // the day the function was added and this line was not.
    + source("nsCloseNote") + "\n"
    // The bring-back prompt, and the destination it names. Both real: "the prompt says where the
    // card is going" is the whole of Hanz's ask, and a stub would be the thing under test.
    + source("reopenDestination") + "\n" + source("confirmBringBack") + "\n"
    + source("renderNotSent") + "\n" + source("wireNotSentLost") + "\n"
    // Marking a bid won by hand (2026-08-19). Lifted rather than stubbed because renderNotSent
    // calls BOTH unconditionally: leaving either out is a ReferenceError for the whole panel, which
    // is how this harness found the feature's first bug.
    + source("wonControlHtml") + "\n" + source("wireWon") + "\n"
    // Recorded rather than lifted: applySecPanel reaches for ALL_SEC_CARDS/SEC_ELIGIBLE and two
    // lazy fetches, the estimator picker is another file's subject, and the notify roster is a
    // network read. Recording each means a RENAME in portal.js still fails loudly here.
    + "function applySecPanel() { panelCalls.push(ACTIVE_SEC); }\n"
    + "function wireNotSentAssign(pid) { assignCalls.push(pid); }\n"
    + "function loadNotSentNotify() {}\n"
    + "return { renderNotSent, wireNotSentLost, closeOutDialog, reopenDestination,"
    + "         sig: () => DRAWER_SIG, setSig: (v) => { DRAWER_SIG = v; },"
    + "         panelCalls, assignCalls };";
  return new Function(...keys, body)(...keys.map((k) => deps[k]));
}

function harness(row, opts) {
  const o = opts || {};
  const dom = makeDom();
  const requests = [];
  const painted = [];
  const prompts = [];
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
    lostReason: (p) => CORE.LOST_REASON[((p && p.followup_state) || {}).closed_lost_reason] || "",
    // EXACTLY what the lifted functions read off crm-core, by their real names and with the real
    // implementations. closeOutcome decides which outcome the dialog resolves, and stage/wonColumn
    // decide what the bring-back prompt promises — both are the subject here, not scaffolding.
    C: { LOST_REASON: CORE.LOST_REASON, CLOSE_CHOICES: CORE.CLOSE_CHOICES,
         HOLD_REASON: CORE.HOLD_REASON, closeOutcome: CORE.closeOutcome,
         followup: CORE.followup, pausedUntil: CORE.pausedUntil,
         stage: CORE.stage, isWon: CORE.isWon, wonByHand: CORE.wonByHand,
         wonColumn: CORE.wonColumn },
    // The module WRAPPER, not C.pausedUntil: crm-core's own takes Central's today as a second
    // argument and answers "" without one, so binding the bare export would have made the held
    // panel silently dateless — which is how the first version of this test passed while showing
    // nothing. Fixed today rather than read off the clock, so a pause date does not lapse mid-suite.
    pausedUntil: (p) => CORE.pausedUntil(p, "2026-08-21"),
    cardTotal: () => null,
    money: (n) => "$" + n,
    TW: {
      fmtBizDate: (d) => String(d),
      fmtBizDay: (d) => String(d),
      // The confirm helper, recorded and answered. What it was ASKED is the assertion: the prompt
      // has to name the project and the column the card is going back to.
      confirmDanger: (o2) => { prompts.push(o2); return Promise.resolve(o.declineBringBack !== true); },
    },
    api: (p, init) => {
      requests.push({ path: p, method: (init && init.method) || "GET",
                      body: JSON.parse((init && init.body) || "null") });
      return Promise.resolve(o.saveFails
        ? { ok: false, status: 500, json: () => Promise.resolve({ error: "postgrest down" }) }
        : { ok: true, status: 200,
            json: () => Promise.resolve({ ok: true, paused_until: "2026-12-20" }) });
    },
    load: () => painted.push("board"),
    closeDrawer: () => {},
    loadEstimators: () => Promise.resolve([]),
    window: { location: { assign() {} } },
  };
  const m = lift(deps);
  m.renderNotSent("d-1", row);
  return { dom, requests, painted, prompts, m, deps };
}

/** Walk the whole flow: press the control, answer the dialog, let the request settle.
 *
 *  `answer` is a reason key, or one of the three dismissals. `note` is what gets typed into the
 *  required comment — passing "" is how the empty-comment cases are driven, and it is the default
 *  precisely so a case that MEANS to leave it blank reads as deliberate. `only` restricts the
 *  typing to ONE event name, for the two cases that check each listener on its own.
 */
async function clickLost(h, answer, note, only) {
  const btn = h.dom.byId.get("ns-lost");
  if (!btn) return { opened: false };
  // The DOM stub registers ids out of the markup but does not parse text nodes, so the button
  // arrives with an empty label. Seed it, or "the label goes back to what it said" is unfalsifiable:
  // the handler restores `orig`, and an empty orig restores to empty whether or not it tried.
  btn.textContent = "Close this bid out";
  fire(btn, "click");
  await Promise.resolve();                  // let the handler reach `await closeOutDialog`
  const dlg = h.dom.appended[h.dom.appended.length - 1];
  if (!dlg) return { opened: false, btn };
  const out = { opened: true, btn, dlg, html: dlg.innerHTML };
  // The sentence under the heading is written with textContent, so it does not appear in
  // innerHTML. Read off the node instead — which is also the string a person actually sees, and
  // the thing that changes between the sent and the unsent wording.
  out.sub = dlg.querySelector("[data-sub]").textContent;
  const noteEl = dlg.querySelector("[data-note]");
  const goEl = dlg.querySelector("[data-go]");
  out.goDisabledOnOpen = goEl.disabled;
  out.errOnOpen = dlg.querySelector("[data-err]").textContent;
  if (answer === "cancel") fire(dlg.querySelector("[data-x]"), "click");
  else if (answer === "escape") h.dom.keyHandlers.forEach((fn) => fn({ key: "Escape" }));
  else if (answer === "backdrop") fire(dlg, "click", { target: dlg });
  else {
    dlg.querySelector("[data-why]").value = answer;
    fire(dlg.querySelector("[data-why]"), "change");
    out.goLabelForReason = goEl.textContent;
    out.subForReason = dlg.querySelector("[data-sub]").textContent;
    noteEl.value = note === undefined ? "" : note;
    // BOTH events by default, because the page listens for both and a test that fires only one
    // cannot tell a handler bound to the other from a handler that is missing.
    //
    // `only` NARROWS IT TO ONE, which is the opposite need and the reason it exists: firing both
    // means removing either listener survives. `input` alone is a person mid-typing, who must not
    // be looking at a dead button; `change` alone is a paste from the context menu followed by a
    // blur, which some browsers report only as `change`.
    for (const evt of (only ? [only] : ["input", "change"])) fire(noteEl, evt);
    out.goDisabledAfterTyping = goEl.disabled;
    out.errAfterTyping = dlg.querySelector("[data-err]").textContent;
    fire(goEl, "click");
  }
  // The dialog's resolve, the api() promise and its .json() each need a turn.
  for (let i = 0; i < 10; i++) await Promise.resolve();
  out.removed = h.dom.removed.length;
  out.stillOnScreen = h.dom.removed.indexOf(dlg) < 0;
  return out;
}

async function clickReopen(h) {
  const btn = h.dom.byId.get("ns-reopen");
  if (!btn) return { present: false };
  btn.textContent = "Bring this bid back";
  fire(btn, "click");
  for (let i = 0; i < 10; i++) await Promise.resolve();
  return { present: true, btn };
}

/** The OTHER way back: taking a by-hand won mark off, which is wireWon's own control rather than
 *  the lost panel's. Its own presser because it lives in a different section of the drawer and
 *  posts a different status - `not_won`, the narrow undo, because a card showing this button is
 *  never also lost, so there is no second mark for a combined clear to catch. */
async function clickWonUndo(h) {
  const btn = h.dom.byId.get("won-undo");
  if (!btn) return { present: false };
  btn.textContent = "Undo";
  fire(btn, "click");
  for (let i = 0; i < 10; i++) await Promise.resolve();
  return { present: true, btn };
}

const LIVE = { project_name: "Nearman Creek", not_sent: true,
               estimator_email: "kyle@wetreadwell.com", drafted_at: "2026-08-10" };
const LOST = Object.assign({}, LIVE, { proposal_status: "closed_lost",
                                       followup_state: { closed_lost_reason: "different_gc",
                                                         closed_lost_note: "12% over Wilson <b>." } });
const HELD = Object.assign({}, LIVE, { followup_state: { paused_until: "2026-12-20",
                                                         on_hold_reason: "on_hold",
                                                         on_hold_note: "GC has gone quiet." } });
// The same two states with NO comment on them, which is every bid closed before 2026-08-20. The
// panel has to read as a finished sentence without one rather than showing an empty quote.
const LOST_NO_NOTE = Object.assign({}, LIVE, {
  proposal_status: "closed_lost", followup_state: { closed_lost_reason: "different_gc" } });
// Marked won by hand and THEN closed lost. It reads as Lost only (every reader asks isLost first),
// so this is the row whose bring-back has to clear BOTH marks.
const WON_THEN_LOST = Object.assign({}, LOST, { won_at: "2026-08-18T15:00:00Z" });
// Marked won by hand and NOT lost: the row that renders the won mark's own undo.
//
// A FUNCTION, not a shared object, and that is not fussiness. wireWon's repaint does
// `Object.assign(row, patch)` on the row it was handed - it is the page's one copy of the mark, on
// purpose - so a successful undo blanks `won_at` on the fixture itself. Sharing one object between
// the two cases below left the second one rendering an unwon bid, with no undo button, and its
// assertions read as "the prompt was never shown".
const wonByHand = () => Object.assign({}, LIVE, { won_at: "2026-08-18T15:00:00Z" });

(async () => {
  const out = { holdMonths: HOLD_MONTHS, closeChoices: CORE.CLOSE_CHOICES,
                lostReasons: CORE.LOST_REASON, holdReasons: CORE.HOLD_REASON };

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
    out.dialog = { html: r.html, sub: r.sub, goDisabledOnOpen: r.goDisabledOnOpen,
                   errOnOpen: r.errOnOpen };
  }
  {
    // …and the sent wording, so the branch is proven to differ rather than assumed to. The dialog
    // builds its markup synchronously and only its RESOLUTION is deferred, so read the markup
    // first and dismiss it after — awaiting the promise before anything clicks leaves node with
    // nothing to run and it exits silently with no output at all.
    const h = harness(LIVE);
    const pending = h.m.closeOutDialog(LIVE);            // no opts → the sent wording
    const d = h.dom.appended[h.dom.appended.length - 1];
    out.dialogSent = { html: d ? d.innerHTML : "",
                       sub: d ? d.querySelector("[data-sub]").textContent : "" };
    if (d) fire(d.querySelector("[data-x]"), "click");
    await pending;
  }

  // 4. THE REQUIRED COMMENT. Confirming with an empty box must send nothing and say why.
  {
    const h = harness(LIVE);
    const r = await clickLost(h, "not_low_bid", "");
    out.emptyNote = {
      opened: r.opened,
      requests: h.requests.length,
      painted: h.painted.length,
      goDisabledOnOpen: r.goDisabledOnOpen,
      goDisabledAfterTyping: r.goDisabledAfterTyping,
      errOnOpen: r.errOnOpen,
      errAfterTyping: r.errAfterTyping,
      stillOnScreen: r.stillOnScreen,
    };
  }
  // …and a box holding nothing but whitespace is the same as an empty one.
  {
    const h = harness(LIVE);
    const r = await clickLost(h, "not_low_bid", "   \n  ");
    out.blankNote = { requests: h.requests.length, goDisabled: r.goDisabledAfterTyping,
                      err: r.errAfterTyping, stillOnScreen: r.stillOnScreen };
  }
  // …and each of the two events that re-check it, ON ITS OWN. Firing both together means dropping
  // either listener still passes, which is exactly what happened: removing the `input` binding left
  // every assertion in this file green while leaving the button dead until the box lost focus.
  out.byTypingEvent = {};
  for (const evt of ["input", "change"]) {
    const h = harness(LIVE);
    const r = await clickLost(h, "not_low_bid", "GC went with Wilson.", evt);
    out.byTypingEvent[evt] = { goDisabled: r.goDisabledAfterTyping, err: r.errAfterTyping,
                               requests: h.requests.length,
                               body: h.requests.length ? h.requests[0].body : null };
  }

  // 5. every one of Kyle's answers, one at a time, through the real dialog
  out.byReason = {};
  for (const choice of CORE.CLOSE_CHOICES) {
    const h = harness(LIVE);
    const r = await clickLost(h, choice.key, "Said so on the phone.");
    out.byReason[choice.key] = {
      outcome: choice.outcome,
      requests: h.requests,
      painted: h.painted,
      goLabel: r.goLabelForReason,
      sub: r.subForReason,
      goDisabledAfterTyping: r.goDisabledAfterTyping,
      // What the panel says about itself afterwards. A held bid must NOT read as closed lost.
      html: h.dom.byId.get("drawer").innerHTML,
      sigAfter: h.m.sig(),
    };
  }

  // 6. a reason left at the default still sends a real one
  {
    const h = harness(LIVE);
    const r = await clickLost(h, "", "Nothing else fitted.");
    out.defaultReason = { requests: h.requests, opened: r.opened };
  }

  // 7. an already-closed bid offers the bring-back, and it asks first
  {
    const h = harness(LOST);
    out.lostPanel = {
      html: h.dom.byId.get("drawer").innerHTML,
      hasReopen: h.dom.ids.has("ns-reopen"),
      hasLost: h.dom.ids.has("ns-lost"),
    };
    const r = await clickReopen(h);
    out.reopened = { present: r.present, requests: h.requests, painted: h.painted,
                     prompts: h.prompts,
                     html: h.dom.byId.get("drawer").innerHTML,
                     appended: h.dom.appended.length };
  }

  // 8. …and answering "no" to that prompt changes nothing
  {
    const h = harness(LOST, { declineBringBack: true });
    await clickReopen(h);
    out.reopenDeclined = { requests: h.requests, painted: h.painted, prompts: h.prompts };
  }

  // 9. a HELD bid: on the board, in the Created column, with a way back
  {
    const h = harness(HELD);
    out.heldPanel = {
      html: h.dom.byId.get("drawer").innerHTML,
      hasReopen: h.dom.ids.has("ns-reopen"),
      hasLost: h.dom.ids.has("ns-lost"),
      stage: CORE.stage(HELD),
      // Central's today passed explicitly. crm-core's pausedUntil answers "" without it (the
      // string compare is against `undefined`), which is exactly the mistake the panel itself made
      // for one revision of this file.
      pausedUntil: CORE.pausedUntil(HELD, "2026-08-21"),
      isLost: CORE.isLost(HELD),
    };
    const r = await clickReopen(h);
    out.heldReopened = { present: r.present, requests: h.requests, prompts: h.prompts };
  }

  // 10. won and THEN lost: one press has to clear both marks, and the prompt has to name the
  //     column the timestamps earn rather than "Won".
  {
    const h = harness(WON_THEN_LOST);
    out.wonThenLost = {
      readsAsLost: CORE.isLost(WON_THEN_LOST),
      readsAsWon: CORE.isWon(WON_THEN_LOST),
      stage: CORE.stage(WON_THEN_LOST),
      destination: h.m.reopenDestination(WON_THEN_LOST),
      hasReopen: h.dom.ids.has("ns-reopen"),
    };
    const r = await clickReopen(h);
    out.wonThenLostReopened = { present: r.present, requests: h.requests, prompts: h.prompts };
  }

  // 10b. the won mark's OWN undo. Same prompt helper, because the card moves either way - to
  //      whichever Active column its own timestamps earn - and the day the Won tab took won jobs
  //      off the Active board is the day this stopped being the no-consequence click its comment
  //      used to claim it was.
  {
    const row = wonByHand();
    const h = harness(row);
    out.wonByHandPanel = {
      hasUndo: h.dom.ids.has("won-undo"),
      hasMark: h.dom.ids.has("won-mark"),
      destination: h.m.reopenDestination(row),
    };
    const r = await clickWonUndo(h);
    out.wonUndone = { present: r.present, requests: h.requests, prompts: h.prompts };
  }
  {
    const h = harness(wonByHand(), { declineBringBack: true });
    await clickWonUndo(h);
    out.wonUndoDeclined = { requests: h.requests, prompts: h.prompts };
  }

  // 10c. the comment, printed back. Requiring a sentence and never showing it anywhere would cost
  //      the estimator the sentence and give the next reader nothing, which is the opposite of why
  //      it is required.
  {
    out.notePrinted = {
      lost: harness(LOST).dom.byId.get("drawer").innerHTML,
      held: harness(HELD).dom.byId.get("drawer").innerHTML,
      lostNoNote: harness(LOST_NO_NOTE).dom.byId.get("drawer").innerHTML,
    };
  }

  // 11. where the prompt says a SENT card is going, over the stages that can produce it
  {
    const h = harness(LIVE);
    const sentLost = (extra) => Object.assign(
      { project_name: "Maple Street", proposal_status: "closed_lost",
        sent_at: "2026-08-01T12:00:00Z",
        followup_state: { closed_lost_reason: "no_response" } }, extra);
    out.destinations = {
      unsent: h.m.reopenDestination(LIVE),
      sent: h.m.reopenDestination(sentLost({})),
      viewed: h.m.reopenDestination(sentLost({ last_viewed_at: "2026-08-05T12:00:00Z" })),
      approved: h.m.reopenDestination(sentLost({ approved_at: "2026-08-06T12:00:00Z" })),
      depositIn: h.m.reopenDestination(sentLost({ approved_at: "2026-08-06T12:00:00Z",
                                                 deposit_status: "received",
                                                 deposit_received_at: "2026-08-07T12:00:00Z" })),
      contactsIn: h.m.reopenDestination(sentLost({ approved_at: "2026-08-06T12:00:00Z",
                                                   deposit_status: "received",
                                                   contacts_status: "received" })),
    };
  }

  // 12. a failed save must not claim the bid is closed
  {
    const h = harness(LIVE, { saveFails: true });
    const r = await clickLost(h, "not_low_bid", "GC never called back.");
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
