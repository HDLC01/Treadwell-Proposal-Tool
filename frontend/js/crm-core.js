// CRM board logic — pure functions, no DOM, no fetch.
// Externalized from portal.js so it can be tested under node (CSP: no inline
// scripts). Do not add DOM access here; portal.js owns rendering.
//
// The board answers three questions about every proposal, and each one has a
// wrong-looking obvious answer:
//
//   WHICH COLUMN?  `stage()`. Closed-lost wins over everything: a customer who
//   said they aren't moving forward must not keep sitting halfway down the board
//   as live work. A deposit gates progress past it, so an unpaid deal can never
//   read as further along than a paid one.
//
//   WHAT DATE?  `stageTs()` for "how long has it been HERE", `activityTs()` for
//   "when did anything last happen". Sorting a kanban column by last activity
//   mixes the two — a deal viewed weeks ago whose customer wrote yesterday jumps
//   above one that only just arrived in the column.
//
//   WHOSE IS IT?  `estimatorOf()`. The portal already coalesces the assignment
//   over the draft's owner, so that field is the effective answer; `assigned` is
//   what says whether a human actually chose.
//
// DATES. Timestamps arrive as UTC ISO strings and are only ever compared as
// strings — same instant ordering, no parsing. Plain "YYYY-MM-DD" values (a
// follow-up pause) are compared against Central's today, never the viewer's.
(function (root, factory) {
  var api = factory();
  root.TWCrm = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var STAGE_SUBMITTED = "Deposit submitted";
  var STAGE_LOST = "Closed lost";
  var STAGES = ["Sent", "Viewed", "Approved", STAGE_SUBMITTED,
                "Deposit received", "Contact info", "Scheduled"];

  var LOST_REASON = {
    price: "Price", another_contractor: "Another contractor",
    canceled: "Project canceled", scope_changed: "Scope changed",
    timing: "Timing", other: "Other",
  };

  // The newest thing that actually happened, NAMED. `sent_at` is never null (a
  // proposal row can't exist before the email goes out), so every card dates.
  // "First viewed" is exactly that — the portal coalesces viewed_at and never
  // moves it; last_viewed_at is the one that tracks re-reads.
  var MILESTONES = [
    ["sent_at", "Sent"],
    ["viewed_at", "First viewed"],
    ["last_viewed_at", "Viewed"],
    ["approved_at", "Approved"],
    ["deposit_requested_at", "Invoiced"],
    ["deposit_submitted_at", "Deposit sent"],
    ["deposit_received_at", "Deposit in"],
    ["contacts_received_at", "Contacts in"],
    ["scheduled_at", "Scheduled"],
    ["last_message_at", "Message"],
    ["last_followup_at", "Followed up"],
  ];

  // The date a card EARNED its current column.
  var STAGE_DATE_KEY = {
    "Sent": "sent_at",
    "Viewed": "last_viewed_at",
    "Approved": "approved_at",
    "Deposit submitted": "deposit_submitted_at",
    "Deposit received": "deposit_received_at",
    "Contact info": "contacts_received_at",
    "Scheduled": "scheduled_at",
    "Closed lost": "closed_at",
  };

  function followup(p) { return (p && p.followup_state) || {}; }
  function isLost(p) { return String((p && p.proposal_status) || "") === "closed_lost"; }

  /** No deposit stage stands between approval and contacts when this job doesn't
   *  collect one — otherwise a GC project would sit in "Approved" forever, unable
   *  to reach Contact info or Scheduled. An issued invoice means a deposit is
   *  genuinely outstanding, flag or not, so it still gates. */
  function depositSatisfied(p) {
    return p.deposit_status === "received" ||
      (p.deposit_required === false && !p.deposit_requested_at);
  }

  function stage(p) {
    if (isLost(p)) return STAGE_LOST;
    if (p.schedule_status === "scheduled") return "Scheduled";
    // A customer may submit contacts right after approval (the portal allows it),
    // but an unpaid deal must NOT read as further along than a paid one.
    if (depositSatisfied(p) && p.contacts_status === "received") return "Contact info";
    if (p.deposit_status === "received") return "Deposit received";
    // Checked AFTER "received" so a confirmed deposit can never fall back into the
    // submitted column if the portal ever sends both signals.
    if (p.deposit_status === "submitted") return STAGE_SUBMITTED;
    if (p.proposal_status === "approved") return "Approved";
    if (p.proposal_status === "viewed") return "Viewed";
    return "Sent";
  }

  function lastActivity(p) {
    var best = null;
    for (var i = 0; i < MILESTONES.length; i++) {
      var ts = p[MILESTONES[i][0]];
      if (ts && (!best || String(ts) > String(best.ts))) best = { ts: ts, label: MILESTONES[i][1] };
    }
    // The server's own figure spans things we have no named stamp for. Trust it for
    // the DATE whenever it's ahead, and say only that something happened — a wrong
    // label is worse than a vague one.
    var srv = p.last_activity_at;
    if (srv && (!best || String(srv) > String(best.ts))) return { ts: srv, label: "Activity" };
    return best;
  }

  function activityTs(p) {
    if (p.last_activity_at) return p.last_activity_at;
    var a = lastActivity(p);
    return a ? a.ts : "";
  }

  function stageTs(p) {
    var key = STAGE_DATE_KEY[stage(p)];
    // Fall back rather than blank: the stage stamps were added later than the rows
    // they describe, so a proposal that reached its stage before the column existed
    // has no date for it. Its last activity is the honest approximation.
    var direct = key && p[key];
    if (!direct && key === "closed_at") direct = followup(p).closed_at;
    return direct || activityTs(p) || "";
  }

  function estimatorOf(p) { return String(p.assigned_estimator || p.estimator_email || ""); }
  function isAssigned(p) { return !!p.assigned_estimator; }

  /** A pause the customer asked for, still in the future — "" once it lapses.
   *  `today` is Central's date as "YYYY-MM-DD"; the caller supplies it so this
   *  stays pure and testable across a date boundary. */
  function pausedUntil(p, today) {
    var d = followup(p).paused_until;
    return (d && String(d) >= String(today)) ? String(d) : "";
  }

  function lostReason(p) { return LOST_REASON[followup(p).closed_lost_reason] || ""; }

  /** Automation exists for this proposal but somebody switched it off. Worth a
   *  chip; automation being ON is the norm and would say nothing on every card. */
  function followupOff(p) {
    var f = followup(p);
    return !!f.enrolled && !f.enabled;
  }

  // ── ordering ───────────────────────────────────────────────────────────────
  // Blanks stay last in BOTH directions: the dir multiplier never touches the null
  // branches, so flipping a sort must not surface empty cards first.
  function byTs(get) {
    return function (dir) {
      return function (x, y) {
        var tx = get(x), ty = get(y);
        if (!tx && !ty) return 0;
        if (!tx) return 1;
        if (!ty) return -1;
        return dir * String(tx).localeCompare(String(ty));
      };
    };
  }

  /** "hanz@wetreadwell.com" → "Hanz". Sorting by the raw address orders by the
   *  local-part's punctuation, which is not what a person reading names expects. */
  function nameOf(email) {
    var s = String(email || "");
    var parts = s.split("@")[0].split(/[._-]+/).filter(Boolean).map(function (w) {
      return w.charAt(0).toUpperCase() + w.slice(1);
    });
    return parts.join(" ") || s;
  }

  var COMPARE = {
    stage: byTs(stageTs),
    activity: byTs(activityTs),
    estimator: function (dir) {
      return function (x, y) {
        var nx = nameOf(estimatorOf(x)).toLowerCase(), ny = nameOf(estimatorOf(y)).toLowerCase();
        if (!nx && !ny) return 0;
        if (!nx) return 1;
        if (!ny) return -1;
        return dir * nx.localeCompare(ny);
      };
    },
    total: function (dir) {
      return function (x, y) {
        var tx = typeof x.approved_total === "number" ? x.approved_total : null;
        var ty = typeof y.approved_total === "number" ? y.approved_total : null;
        if (tx === null && ty === null) return 0;
        if (tx === null) return 1;
        if (ty === null) return -1;
        return dir * (tx - ty);
      };
    },
  };

  var SORT_FIELDS = ["stage", "activity", "estimator", "total"];
  // Each field opens the way you'd want to read it first.
  var NATURAL_DIR = { stage: "desc", activity: "desc", estimator: "asc", total: "desc" };

  function sort(list, field, dirWord) {
    var make = COMPARE[field] || COMPARE.activity;
    return list.slice().sort(make(dirWord === "asc" ? 1 : -1));
  }

  /** Group into kanban columns. Unknown stages are dropped rather than thrown —
   *  a portal that grows a new status must not blank the board. */
  function group(items, columns) {
    var by = {};
    columns.forEach(function (c) { by[c] = []; });
    items.forEach(function (p) { var s = stage(p); if (by[s]) by[s].push(p); });
    return by;
  }

  return {
    STAGES: STAGES, STAGE_SUBMITTED: STAGE_SUBMITTED, STAGE_LOST: STAGE_LOST,
    LOST_REASON: LOST_REASON, MILESTONES: MILESTONES, STAGE_DATE_KEY: STAGE_DATE_KEY,
    SORT_FIELDS: SORT_FIELDS, NATURAL_DIR: NATURAL_DIR, COMPARE: COMPARE,
    followup: followup, isLost: isLost, depositSatisfied: depositSatisfied,
    stage: stage, lastActivity: lastActivity, activityTs: activityTs, stageTs: stageTs,
    estimatorOf: estimatorOf, isAssigned: isAssigned, pausedUntil: pausedUntil,
    lostReason: lostReason, followupOff: followupOff, nameOf: nameOf,
    sort: sort, group: group,
  };
});
