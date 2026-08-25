// Follow-ups board logic — pure functions, no DOM, no fetch.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT THE COLUMNS MEAN, and why they changed.
//
// The board used to mix two different questions into one row of columns: Sent / Viewed /
// Approved / Closed lost is where the CUSTOMER stands, while Chasing / Paused is what OUR
// automation is doing. Those are independent — a proposal can be un-opened AND paused for three
// months — so a card could satisfy two columns at once and the old code had to rank them. The
// visible symptom was a proposal reading "Sent" in the table and sitting under "Chasing" on the
// board, which made one of the two views a liar.
//
// Hanz, on seeing it: "What I thought is follow ups would look like a CRM and then it's split
// into categories — Not viewed / Seen / No reply."
//
// So the columns are now ONE axis: how far the customer has got.
//
//     not_opened  ->  seen  ->  talking  ->  approved
//                                       \->  lost
//
// Every proposal is in exactly one, no ranking needed, and "what we are doing about it"
// (chasing, paused, automation off) moves onto the card as a badge — which is where it belongs,
// because it is an attribute of a proposal, not a place a proposal lives.
//
// WHY "SEEN" IS ONE COLUMN AND NOT TWO. A customer who opened the email and one who opened the
// portal are at the same point in the decision: they have the proposal and have not answered.
// Splitting them would double the column count to say something the card can say in a line, so
// `seenHow()` reports it per card instead.
//
// WHAT THIS COSTS. Only one column is ours to set, so only one accepts a drop. Dragging a card
// into "Seen" would assert that somebody opened a proposal they never opened — and that fact
// feeds the digest's ranking and its 6 AM sentence, so the lie would reach a customer's inbox.
// Pause and Resume are therefore buttons on the card, not columns, and `actionPlan()` serves
// both them and the one drag target.
(function (root, factory) {
  var api = factory();
  root.TWFu = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // `ours: true` = we decide it, so it accepts a drop. Everything else is a record of what the
  // customer did, and the board only reports it.
  var COLUMNS = [
    { id: "not_opened", label: "Not opened",  ours: false, dot: "#8a857c",
      sub: "no sign they have seen it" },
    { id: "seen",       label: "Seen",        ours: false, dot: "#4a6b8a",
      sub: "opened it, never answered" },
    { id: "talking",    label: "In conversation", ours: false, dot: "#0f7b34",
      sub: "they have come back to us" },
    { id: "approved",   label: "Approved",    ours: false, dot: "#0f7b34",
      sub: "signed off" },
    { id: "lost",       label: "Closed lost", ours: true,  dot: "#8a857c",
      sub: "reminders stopped" },
  ];

  var BY_ID = {};
  for (var i = 0; i < COLUMNS.length; i++) BY_ID[COLUMNS[i].id] = COLUMNS[i];

  function followup(p) { return (p && p.followup_state) || {}; }

  /** Still paused? String compare against Central's today, like crm-core's pausedUntil —
   *  deliberately no Date parsing, so a lapsed pause simply stops matching. */
  function pausedUntil(p, today) {
    var d = followup(p).paused_until;
    return (d && String(d) >= String(today)) ? String(d) : "";
  }

  function isLost(p) {
    return String((p && p.proposal_status) || "") === "closed_lost" || !!followup(p).closed_at;
  }

  /** Has the customer replied to us at all?
   *
   *  `customer_replied_at` is the portal's customer-only timestamp. `last_message_at` cannot
   *  answer this — it is the newest message from EITHER side, so a thread where we sent the last
   *  note looks identical to one the customer answered. `unread` is also not the question: it
   *  counts messages we have not answered yet, so a customer we already replied to would read
   *  as never having spoken. */
  function hasReplied(p) {
    return !!(p && p.customer_replied_at);
  }

  /** Any evidence the customer has the proposal in front of them.
   *
   *  Portal view is the strong signal; an email link click is the weak one (the landing page
   *  serves before any login, and mail scanners follow links), but for "have they got it at
   *  all" the weak signal is still the difference between a silent customer and a wrong
   *  address. */
  function hasSeen(p) {
    if (!p) return false;
    return !!(p.viewed_at || p.last_viewed_at ||
              String(p.proposal_status || "") === "viewed" ||
              p.link_clicked_at);
  }

  /** How they saw it, for the card to say so. Portal beats email: it is the stronger fact and
   *  it means a person definitely looked. */
  function seenHow(p) {
    if (!p) return "";
    if (p.viewed_at || p.last_viewed_at || String(p.proposal_status || "") === "viewed") {
      return "portal";
    }
    if (p.link_clicked_at) return "email";
    return "";
  }

  /** Which column this proposal belongs in. Exactly one, always.
   *
   *  Order is the journey, with the two terminal states first: a lost proposal is lost however
   *  much of it the customer read, and an approved one is approved even if they never opened the
   *  portal (they can approve from the email link). */
  function column(p) {
    if (isLost(p)) return "lost";
    if (String((p && p.proposal_status) || "") === "approved") return "approved";
    if (hasReplied(p)) return "talking";
    if (hasSeen(p)) return "seen";
    return "not_opened";
  }

  /** What we are doing about it — a badge on the card, not a column.
   *
   *  Returns one of: "chasing" (the cadence is running), "paused" (until a date), "off"
   *  (enrolled but switched off, or never enrolled), or "" for the terminal columns where
   *  chasing is meaningless. */
  function automation(p, today) {
    var col = column(p);
    // "approved" is no longer a blanket stop. Hanz, 2026-08-12: "followups should be automated
    // until a deposit has been received." A won job with the money still out IS being chased, and
    // returning "" here painted no badge at all — staff would read the page as "nothing is going
    // out" while the worker emailed the customer every few days.
    if (col === "lost") return "";
    if (col === "approved" && depositIn(p)) return "";
    if (pausedUntil(p, today)) return "paused";
    var f = followup(p);
    return (f.enrolled && f.enabled) ? "chasing" : "off";
  }

  /** Is the money in, as far as the CUSTOMER's reminders are concerned?
   *
   *  `submitted` counts: once they have recorded ACH details or told us the cheque is posted,
   *  their emails stop. The estimator's continue until `received`, but this function feeds a
   *  page that talks about what the CUSTOMER is being sent. Mirrors
   *  followup_rules.deposit_outstanding(for_customer=True) in the portal; a missing
   *  `deposit_required` is a legacy row, which did collect one. */
  function depositIn(p) {
    if (!p) return true;
    // `deposit_required === false` means none was asked for — UNLESS an invoice was raised anyway,
    // which is staff deciding after the fact that money is due. Omitting that half made this
    // function's own claim to mirror the portal rule false, and left it disagreeing with
    // crm-core.depositSatisfied, which had it right: the card would have read "nothing going out"
    // on a GC job the worker was actively chasing.
    if (p.deposit_required === false && !p.deposit_requested_at) return true;
    var st = String(p.deposit_status || "").toLowerCase();
    return st === "submitted" || st === "received";
  }

  /** Can a person drag this card into that column?
   *
   *  Only Closed lost. The other four are records of what the customer did, and asserting one
   *  by dragging would put a false fact into the digest email. */
  function canMove(p, toId) {
    var col = BY_ID[toId];
    if (!col || !col.ours) return false;
    if (column(p) === toId) return false;                // already there
    // An approved proposal can't be closed-lost: the portal refuses it (already_approved), and
    // offering a move the server will reject is worse than not offering it.
    return column(p) !== "approved";
  }

  /** What an action should actually DO — the cadence change, not a relabel.
   *
   *  Serves the card's buttons AND the one drag target, so the mapping from intent to API call
   *  lives in one tested place. `needs` names the extra input a dialog has to collect first.
   *
   *  Actions are deliberately NOT column ids apart from "lost": pause and resume no longer
   *  correspond to a place on the board, and pretending they do is what made the old columns
   *  ambiguous. */
  function actionPlan(p, action, today) {
    if (action === "lost") {
      if (!canMove(p, "lost")) return null;
      return { status: "closed_lost", needs: "reason",
               confirm: "Stop chasing this proposal for good?" };
    }
    if (action === "pause") {
      if (isLost(p) || column(p) === "approved") return null;
      if (pausedUntil(p, today)) return null;            // already paused
      return { status: "delayed", needs: "months",
               confirm: "Pause reminders for this proposal?" };
    }
    if (action === "resume") {
      if (isLost(p) || column(p) === "approved") return null;
      if (automation(p, today) === "chasing") return null;   // already running
      // Clearing a pause and re-enabling automation are SEPARATE writes on the portal —
      // resume_followups() clears paused_until but not followup_disabled_at — so a card that is
      // both paused and switched off needs both, in this order.
      var f = followup(p);
      var also = (f.enrolled && !f.enabled) || !f.enrolled ? ["enable_automation"] : [];
      return { status: "active", needs: null, then: also,
               confirm: "Resume automatic reminders?" };
    }
    return null;
  }

  /** Which actions to offer on this card, in the order they should appear. */
  function actionsFor(p, today) {
    var out = [];
    if (actionPlan(p, "resume", today)) out.push({ id: "resume", label: "Resume" });
    if (actionPlan(p, "pause", today)) out.push({ id: "pause", label: "Pause" });
    if (actionPlan(p, "lost", today)) out.push({ id: "lost", label: "Closed lost" });
    return out;
  }

  /** How badly this one has been left alone. Drives the card's stripe.
   *
   *  Deliberately NOT the stage — the column already says the stage, so tinting by stage would
   *  say the same thing twice. This says how long it has been ignored, which is the only reason
   *  to look at the board rather than the calendar. */
  var COLD_DAYS = 7;
  var WARM_DAYS = 3;
  function neglect(p, nowMs) {
    if (isLost(p) || String((p && p.proposal_status) || "") === "approved") return "fine";
    var chased = p && p.last_followup_at;
    var acted = p && p.last_activity_at;
    // Never chased at all is the worst case, not a blank — same rule the list sorts by.
    if (!chased) return "cold";
    var days = Math.floor((nowMs - new Date(chased).getTime()) / 86400000);
    if (isNaN(days)) return "fine";
    var quiet = acted ? Math.floor((nowMs - new Date(acted).getTime()) / 86400000) : days;
    var worst = Math.max(days, isNaN(quiet) ? days : quiet);
    if (worst >= COLD_DAYS) return "cold";
    if (worst >= WARM_DAYS) return "warm";
    return "fine";
  }

  /** Group rows into columns, preserving the order they arrive in (the feed is already ranked
   *  by the digest: not-eligible last, then score, then name). */
  function group(rows, today) {
    var out = {};
    for (var i = 0; i < COLUMNS.length; i++) out[COLUMNS[i].id] = [];
    for (var j = 0; j < (rows || []).length; j++) {
      var c = column(rows[j], today);
      (out[c] || out.not_opened).push(rows[j]);
    }
    return out;
  }

  /** Count + total value for a column header. */
  function load(rows) {
    var total = 0, n = (rows || []).length;
    for (var i = 0; i < n; i++) {
      var v = rows[i].approved_total;
      if (typeof v === "number" && isFinite(v)) total += v;
    }
    return { count: n, value: total };
  }

  // ── what actually went out ──────────────────────────────────────────────────
  // WHY THIS IS HERE AT ALL. Hanz, 2026-08-24, the day the cadence started sending on production:
  // "make sure all follow up emails are shown in the Chat box and in the Follow Ups section."
  // The feed this page loads carries next_followup_at (what is COMING) and last_followup_at, and
  // that second one is the portal's `last_staff_followup_at`: its SQL counts only staff_call,
  // staff_email, staff_text and staff_note, so an automated reminder never touches it. A project
  // the cadence emailed three times reads "never" in the Last chased column. Nothing on the page
  // showed a send.
  //
  // The log itself already exists and is not rebuilt here: portal_followups, one row per send,
  // reserved by the worker BEFORE it sends. This turns those rows into lines of text.
  //
  // A SECOND COPY OF THE DRAWER'S VOCABULARY, on purpose and pinned by a test. portal.js has the
  // same three maps for the drawer's History list; they cannot be shared without moving them out
  // of portal.js, which is where backend/tests/js/drawer-render-harness.js lifts them from by name.
  // So test_followups_sent_log.py asserts the two copies are equal, the same way auth.js's
  // NO_SIDEBAR_TABS is asserted equal to nav_access.py's.
  var FU_KIND_LABEL = {
    staff_call: "Call", staff_email: "Email", staff_text: "Text", staff_note: "Note",
    call: "Call", email: "Email", text: "Text", note: "Note",
    auto_email: "Automatic email", customer_status: "Customer update",
  };
  // `template`, not `rule_key`: the worker records what it SENT, and the rule key that deduped it
  // is scheduling bookkeeping. Staff templates read "Told the team" because nothing in them reached
  // the customer, which is the difference between having bothered them and having bothered us.
  var FU_TEMPLATE_LABEL = {
    not_viewed: "Nudge: not opened yet",
    next_steps: "Next steps after viewing",
    second_nudge: "Second nudge",
    checkin: "Check-in",
    deposit_nudge: "Deposit reminder",
    staff_not_viewed: "Told the team: still not opened",
    staff_pause_expired: "Told the team: the pause ended",
    staff_personal_followup: "Told the team: worth a call",
    staff_deposit_outstanding: "Told the team: deposit outstanding",
  };
  // Bookkeeping the portal writes as a staff_note carrying an `action` key. Kept rather than
  // filtered out: "automation off" three weeks ago is the answer to "why has nothing gone out".
  var FU_ACTION = {
    reassigned: "Reassigned", automation_on: "Automation on", automation_off: "Automation off",
    paused: "Paused", closed_lost: "Closed lost", reactivated: "Reactivated",
  };

  /** Was this row an email that LEFT the building, and which way? "customer", "staff" or "".
   *
   *  The audience is the worker's own word for it (followup_worker reserves the row with
   *  {audience, template}), so this reads what sent it rather than guessing from the template
   *  name. A staff-logged email counts as customer outreach: somebody typed it to them. */
  function sentSide(f) {
    var d = (f && f.detail) || {};
    var kind = String((f && f.kind) || "");
    if (kind === "auto_email") return d.audience === "staff" ? "staff" : "customer";
    if (d.action) return "";                       // bookkeeping, not outreach
    if (kind === "staff_email" || kind === "email") return "customer";
    return "";
  }

  /** One log row as the words to print: { what, detail, side, at, by, auto }.
   *
   *  Pure and separate from the markup so it can be asserted under node. The audience wording is
   *  the part that must not drift, because "sent to the customer" on a staff-only note would tell
   *  an estimator the customer has been chased when only the team has. */
  function sentLine(f) {
    var d = (f && f.detail) || {};
    var kind = String((f && f.kind) || "");
    var side = sentSide(f);
    var what = FU_KIND_LABEL[kind] || kind || "Follow-up";
    var detail = d.note || "";
    if (kind === "auto_email") {
      what = FU_TEMPLATE_LABEL[d.template] || "Automatic email";
      detail = side === "staff" ? "sent to the estimator, not the customer"
                                : "sent to the customer";
    } else if (kind === "customer_status") {
      what = "The customer told us where it stands";
    } else if (d.action) {
      what = FU_ACTION[d.action] || "System";
    }
    return { what: what, detail: detail, side: side, at: (f && f.created_at) || "",
             by: (f && f.by) || "", auto: kind === "auto_email" };
  }

  /** The whole log as lines, newest first, plus the counts the summary line needs.
   *
   *  Order is the server's (db.list_followups is created_at desc) and is NOT re-sorted here: two
   *  rows written in the same second by one tick (the customer email and the note about it) would
   *  swap under an unstable sort and read as the reply arriving before the send. */
  function sentLog(followups) {
    var lines = [], emails = 0, toCustomer = 0, toStaff = 0, last = "";
    var rows = followups || [];
    for (var i = 0; i < rows.length; i++) {
      var line = sentLine(rows[i]);
      lines.push(line);
      if (line.side) {
        emails++;
        if (line.side === "customer") toCustomer++; else toStaff++;
        if (!last && line.at) last = line.at;      // newest first, so the first one wins
      }
    }
    return { lines: lines, emails: emails, toCustomer: toCustomer, toStaff: toStaff, last: last };
  }

  return {
    COLUMNS: COLUMNS, COLD_DAYS: COLD_DAYS, WARM_DAYS: WARM_DAYS,
    columnById: function (id) { return BY_ID[id] || null; },
    column: column, canMove: canMove, actionPlan: actionPlan, actionsFor: actionsFor,
    automation: automation, depositIn: depositIn, hasSeen: hasSeen, hasReplied: hasReplied, seenHow: seenHow,
    neglect: neglect, group: group, load: load, pausedUntil: pausedUntil, isLost: isLost,
    FU_KIND_LABEL: FU_KIND_LABEL, FU_TEMPLATE_LABEL: FU_TEMPLATE_LABEL, FU_ACTION: FU_ACTION,
    sentSide: sentSide, sentLine: sentLine, sentLog: sentLog,
  };
});
