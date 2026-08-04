// Follow-ups board logic — pure functions, no DOM, no fetch.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHICH COLUMN A PROPOSAL SITS IN, and who is allowed to move it.
//
// The board draws the SAME rows the list draws, so its column order has to agree with the
// list's `stateOf()` precedence exactly — a proposal that reads "Paused to 12 Oct" in the
// table and sits under Chasing on the board would make one of the two a liar. The order
// below is that same rank: closed lost > approved > paused > chasing > viewed/sent.
//
// A row really can satisfy two columns at once. `proposal_status` is what the CUSTOMER has
// done (sent → viewed → approved / closed_lost) while `followup_state` is what WE have
// decided (enrolled, paused until a date, automation off). A proposal can be "sent, not
// viewed" AND "paused for three months" simultaneously. Our decision wins, because that is
// the one that answers "do I need to do anything today".
//
// THREE COLUMNS ARE NOT DROP TARGETS. Sent, Viewed and Approved are records of what the
// customer did. Dragging a card into Viewed would assert that somebody opened a proposal
// they never opened — and that fact feeds the digest's ranking and its 6 AM sentence, so the
// lie would propagate into an email. Only Chasing, Paused and Closed lost are ours to set.
(function (root, factory) {
  var api = factory();
  root.TWFu = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // `ours: true` = we decide it, so it accepts a drop and a keyboard move.
  // `ours: false` = the customer decides it; the board only reports it.
  var COLUMNS = [
    { id: "sent",     label: "Sent",        ours: false, dot: "#4a6b8a",
      sub: "not opened yet" },
    { id: "viewed",   label: "Viewed",      ours: false, dot: "#4a6b8a",
      sub: "read, not decided" },
    { id: "chasing",  label: "Chasing",     ours: true,  dot: "#0f7b34",
      sub: "reminders going out" },
    { id: "paused",   label: "Paused",      ours: true,  dot: "#7a5c00",
      sub: "customer asked us to wait" },
    { id: "approved", label: "Approved",    ours: false, dot: "#0f7b34",
      sub: "signed off" },
    { id: "lost",     label: "Closed lost", ours: true,  dot: "#8a857c",
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

  /** Which column this proposal belongs in. Precedence mirrors the list's stateOf(). */
  function column(p, today) {
    if (isLost(p)) return "lost";
    var st = String((p && p.proposal_status) || "");
    if (st === "approved") return "approved";
    if (pausedUntil(p, today)) return "paused";
    // "Chasing" means the cadence is actually running. Enrolled-but-disabled, or never
    // enrolled, is NOT chasing — it sits in the customer column it came from, because
    // nothing is going out and the board shouldn't imply otherwise.
    var f = followup(p);
    if (f.enrolled && f.enabled) return "chasing";
    return st === "viewed" ? "viewed" : "sent";
  }

  /** Can a person move this card into that column? */
  function canMove(p, toId, today) {
    var col = BY_ID[toId];
    if (!col || !col.ours) return false;                 // customer-owned
    var from = column(p, today);
    if (from === toId) return false;                     // already there
    // An approved proposal can't be closed-lost: the portal refuses it (already_approved),
    // and offering a move the server will reject is worse than not offering it.
    if (from === "approved") return false;
    return true;
  }

  /** What a drop should actually DO — the cadence change, not a relabel.
   *
   *  Returns a small plan the page executes, so the mapping from column to API call lives
   *  in one tested place instead of inside a drop handler. `needs` names the extra input a
   *  dialog has to collect first. */
  function movePlan(p, toId, today) {
    if (!canMove(p, toId, today)) return null;
    if (toId === "paused") {
      return { status: "delayed", needs: "months",
               confirm: "Pause reminders for this proposal?" };
    }
    if (toId === "lost") {
      return { status: "closed_lost", needs: "reason",
               confirm: "Stop chasing this proposal for good?" };
    }
    // Back to chasing. Clearing a pause and re-enabling automation are SEPARATE writes on
    // the portal — resume_followups() clears paused_until but not followup_disabled_at — so
    // a card that is both paused and switched off needs both, in this order.
    var f = followup(p);
    var also = (f.enrolled && !f.enabled) || !f.enrolled ? ["enable_automation"] : [];
    return { status: "active", needs: null, then: also,
             confirm: "Resume automatic reminders?" };
  }

  /** How badly this one has been left alone. Drives the card's stripe.
   *
   *  Deliberately NOT the stage — the column already says the stage, so tinting by stage
   *  would say the same thing twice. This says how long it has been ignored, which is the
   *  only reason to look at the board rather than the calendar. */
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

  /** Group rows into columns, preserving the order they arrive in (the feed is already
   *  ranked by the digest: not-eligible last, then score, then name). */
  function group(rows, today) {
    var out = {};
    for (var i = 0; i < COLUMNS.length; i++) out[COLUMNS[i].id] = [];
    for (var j = 0; j < (rows || []).length; j++) {
      var c = column(rows[j], today);
      (out[c] || out.sent).push(rows[j]);
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

  return {
    COLUMNS: COLUMNS, COLD_DAYS: COLD_DAYS, WARM_DAYS: WARM_DAYS,
    columnById: function (id) { return BY_ID[id] || null; },
    column: column, canMove: canMove, movePlan: movePlan, neglect: neglect,
    group: group, load: load, pausedUntil: pausedUntil, isLost: isLost,
  };
});
