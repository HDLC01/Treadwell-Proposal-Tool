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
  // "Scheduled" was the last column until 2026-08-11. Hanz: "We need to remove the schedule
  // status on the CRM and on the Customer portal Status." It was a step with nothing behind it:
  // Treadwell books the date by phone, so the customer's own Schedule tile had nowhere to
  // navigate to and the column only ever restated what a call had already settled.
  //
  // The stage() branch that returned it went at the same moment, and that pairing is not
  // optional: group() below drops any card whose stage is not a live column, so leaving the
  // branch would have made every scheduled project disappear off the board rather than fall
  // back to Contact info.
  //
  // schedule_status and scheduled_at are untouched in the database. Nothing is deleted, so
  // reinstating the column is putting these two lines back.
  //
  // The first column is not a portal state at all. Hanz, 2026-08-11: "Under the Active Proposals
  // we need to create a new category before sent 'Created but not Sent'."
  //
  // Everything to its right comes from portal_proposals, which only has a row once a proposal has
  // been emailed to a customer. A finished estimate sitting on somebody's desk therefore has no
  // portal row and was invisible on this board, which is exactly the work most worth chasing.
  // api_portal_pipeline synthesises those rows out of our own drafts and marks them `not_sent`;
  // see the note there for what counts as one.
  var STAGE_CREATED = "Created but not sent";
  var STAGES = [STAGE_CREATED, "Sent", "Viewed", "Approved", STAGE_SUBMITTED,
                "Deposit received", "Contact info"];

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
    ["last_message_at", "Message"],
    ["last_followup_at", "Followed up"],
    // Only a synthesised "Created but not sent" row carries this; the portal never stores it.
    // LAST, because lastActivity keeps the first entry on a strictly-greater comparison — so a
    // real portal event sharing the timestamp wins the card's activity line, which is right:
    // being created is the earliest thing that can happen to a project.
    ["drafted_at", "Created"],
  ];

  // The date a card EARNED its current column.
  var STAGE_DATE_KEY = {
    "Created but not sent": "drafted_at",
    "Sent": "sent_at",
    "Viewed": "last_viewed_at",
    "Approved": "approved_at",
    "Deposit submitted": "deposit_submitted_at",
    "Deposit received": "deposit_received_at",
    "Contact info": "contacts_received_at",
    "Closed lost": "closed_at",
  };

  function followup(p) { return (p && p.followup_state) || {}; }
  function isLost(p) { return String((p && p.proposal_status) || "") === "closed_lost"; }

  // ── test / demo projects ───────────────────────────────────────────────────
  // Somebody's scratch work, as opposed to a customer's bid. The Proposals Database has kept
  // these in their own tab since 2026-08-07; the Active Projects board grew the same
  // Active/Test split on 2026-08-10. It has to be ONE rule: a project filed as test on that
  // page must appear under Test here, or the two screens disagree about what a test project is.
  //
  // THE FLAG WINS, IN BOTH DIRECTIONS. `is_test` is a tri-state on purpose (see `_tribool` in
  // backend/drafts.py): true = filed as test, false = somebody looked and said "real bid",
  // absent = nobody has said. False has to BEAT the name, or un-filing a project genuinely
  // called "Test Treadwell" bounces it straight back into the Test tab with no way out.
  //
  // Absent falls back to the NAME, and that regex stays narrow deliberately: "demo" lives
  // inside "demolition", which is a live hazard in a construction tool, and a misfiled real bid
  // is worse than a visible test one. The names it misses ("Testing", "test1", "(untitled)")
  // are what the Test? button on the card is for.
  //
  // projects.js still carries its own copy of this pair. It predates this module, and it was
  // being edited by somebody else the day this moved here. test_active_projects_board.py
  // compares the two heuristics character for character so they cannot drift apart unnoticed.
  function nameLooksLikeTest(p) {
    var n = String((p && p.project_name) || "");
    return /\b(sample|test|verify|demo|qa|bugtest)\b/i.test(n)
        || /delete me/i.test(n)
        || /^\s*zz/i.test(n);
  }
  function isTest(p) {
    if (p && typeof p.is_test === "boolean") return p.is_test;   // filed by hand, either way
    return nameLooksLikeTest(p);
  }

  /** No deposit stage stands between approval and contacts when this job doesn't
   *  collect one — otherwise a GC project would sit in "Approved" forever, unable
   *  to reach Contact info. An issued invoice means a deposit is genuinely
   *  outstanding, flag or not, so it still gates. */
  function depositSatisfied(p) {
    return p.deposit_status === "received" ||
      (p.deposit_required === false && !p.deposit_requested_at);
  }

  /** WON: the customer said yes AND the money question is settled.
   *
   *  Hanz, 2026-08-19: "CRM lost and won should also tie up to the notification sending okay?"
   *  It lived in notifications.js, which is the one page that had a Won tab, and that is exactly
   *  how two screens end up disagreeing about a word Troy reads as a number. It sits here beside
   *  isLost now, so the board and the Notification Sending page cannot drift.
   *
   *  Deliberately NOT depositSatisfied on its own. That predicate is true of any job which collects
   *  no deposit — including a proposal emailed this morning nobody has opened. It answers "is money
   *  outstanding", not "did we win".
   *
   *  And not approval on its own, which is too generous the other way: an approved job with the
   *  deposit still outstanding is the single most worth-chasing project there is, and filing it
   *  under Won would hide it from the person whose job is the chasing. followups.js draws the same
   *  line from the other side — its bucket is internally called `won` and LABELLED "Approved",
   *  because approval alone does not earn the word.
   *
   *  `approved_at` as well as the status, because the portal moves a row forward past approval —
   *  stage() below reads deposit state before proposal_status for that very reason — and the stamp
   *  never unsets. Without it a job falls back out of Won the moment contacts arrive.
   *
   *  A BY-HAND MARK WINS OUTRIGHT, and needs neither half of the derived rule. Hanz, 2026-08-19:
   *  "Is there any way to also mark as won for now other than after the deposit has been received".
   *  The derived rule describes a FINISHED job, and the commonest way we learn we won one is a
   *  verbal yes on the phone — days before the customer clicks Approve, weeks before the money
   *  lands. Until somebody marked it, that job read as Active, which is the same "nobody has said"
   *  the estimator is trying to correct. So the mark is not another input to the rule, it is a
   *  person overriding it: `won_at` is set only by a human pressing the button (drafts.set_won), and
   *  the two paths deliberately do not gate each other — requiring approval as well would refuse
   *  exactly the case this exists for.
   *
   *  Nothing here checks isLost, and that is on purpose: every reader asks isLost FIRST (stage(),
   *  ppCategory(), chipsHtml()), so a job marked won and then cancelled reads as Lost only. Folding
   *  it in here would put the same rule in two places, and a SENT project's closed_lost belongs to
   *  the portal, which the mark cannot see or clear. */
  function isWon(p) {
    if (p && p.won_at) return true;
    var approved = String((p && p.proposal_status) || "") === "approved" || !!(p && p.approved_at);
    return approved && depositSatisfied(p);
  }

  /** Won because a HUMAN said so, as opposed to won because the deposit landed. The drawer's control
   *  needs the difference: there is nothing to undo about a deposit that arrived, and offering
   *  "Undo won" on a paid job would be a button that appears to do nothing. */
  function wonByHand(p) { return !!(p && p.won_at); }

  function stage(p) {
    if (isLost(p)) return STAGE_LOST;
    // Checked before every portal state, because a synthesised row has none of them: it is a
    // draft of ours, not a proposal the customer has. The flag is set server-side rather than
    // inferred from missing fields, so a portal row that arrives without a status cannot fall
    // into this column by accident.
    if (p.not_sent) return STAGE_CREATED;
    // No schedule branch. A scheduled job now reads as Contact info, the furthest stage that
    // still exists, rather than vanishing: group() only keeps cards whose stage is a live
    // column. See the note on STAGES.
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

  /** The money on a card, or null when there is none to show.
   *
   *  Two sources because a card has two possible lives. A sent proposal carries the portal's
   *  `approved_total`, which is the figure the customer was actually given. A "Created but not
   *  sent" card has no portal row at all, so it carries `bid_total` off the draft — the same
   *  number the Proposals Database shows. Deliberately NOT one field: calling an unsent
   *  draft's working figure "approved" would put a word on it that nobody has earned. */
  function cardTotal(p) {
    if (typeof p.approved_total === "number") return p.approved_total;
    if (typeof p.bid_total === "number") return p.bid_total;
    return null;
  }
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

  // ── estimator avatars ──────────────────────────────────────────────────────
  // A coloured circle of initials, the way BasisBoard shows an assignee. The point
  // is scanning: "whose are these?" answered down a column without reading a single
  // name, because one person is always the same colour.

  /** "kyle.loseke@…" → "KL"; "Kyle Loseke" → "KL"; "troy@…" → "T"; "" → "".
   *
   *  Takes an address OR a display name, because half the app has one and half has the
   *  other. First and LAST word, not first and second: "Marisoll Monserrat Ontiveros"
   *  reads as MO to the person who owns it, not MM. Two letters at most — a third stops
   *  fitting a 20px circle at a legible weight.
   *
   *  KNOWN SEAM. Initials follow whatever string the page has, so a one-word address
   *  yields one letter: Troy is `T` on the CRM board (which knows only
   *  troy@wetreadwell.com) and `TH` on the Bid Pipeline (where BasisBoard supplies "Troy
   *  Holmes"). His COLOUR is identical on both, because that keys on the first name — and
   *  colour is what makes a column scannable. Making the initials agree too would mean
   *  every page fetching the roster before it could draw a chip, trading a correct-but-
   *  terse label for a flash of the wrong one. */
  function initialsOf(who) {
    var words = nameOf(who).split(/\s+/).filter(Boolean);
    if (!words.length) return "";
    var first = words[0].charAt(0);
    return (words.length > 1 ? first + words[words.length - 1].charAt(0) : first).toUpperCase();
  }

  // Every one of these clears 4.5:1 against white text (worst is 4.92:1), and none is
  // near the unread badge's red — an avatar must never read as an alert.
  //
  // WHY FOURTEEN. Hashing cannot promise two people different colours, and no hash we
  // tried separates a ten-person roster at any palette size. Fourteen is about the limit
  // at which a human still tells 20px circles apart, so a wider palette would trade hash
  // collisions for perceptual ones and gain nothing. A clash is therefore possible and
  // harmless: the NAME is rendered beside the chip everywhere, so two people sharing a
  // colour costs a little scanning speed and never shows anybody the wrong owner.
  // No near-greys: an earlier slate entry sat two hex digits from AVATAR_NONE, so a real
  // person could look like the "unassigned" chip beside them.
  var AVATAR_COLORS = [
    "#0F766E", "#4F46E5", "#7C3AED", "#BE185D", "#C2410C", "#15803D", "#1D4ED8",
    "#9F1239", "#92400E", "#86198F", "#0E7490", "#6D28D9", "#A16207", "#166534",
  ];

  // "Nobody", and deliberately NOT a palette member, so no real person can ever wear
  // the colour that means unassigned. (Carving a colour OUT of the palette to free this
  // one cost three roster separations — a modulo over a shorter list reshuffles
  // everybody — so it lives outside the list instead.)
  var AVATAR_NONE = "#4B5563";

  /** What we hash: the person's FIRST NAME, lowercased and stripped to letters.
   *
   *  Different pages know the same person by different strings. Our own screens have
   *  `kyle.loseke@wetreadwell.com`; the Bid Pipeline and Analytics read BasisBoard,
   *  which only ever says `Kyle Loseke`. Hashing either string whole gives that person
   *  TWO colours across the app, which defeats the point of colour-coding them at all.
   *  Reducing both to `kyle` makes them agree, and a first name is the only key the two
   *  sources actually share.
   *
   *  The cost, stated plainly: two people with the same first name always draw the same
   *  colour. Nobody on the roster collides today, and the NAME is rendered beside every
   *  chip, so if it ever happens it costs a little scanning speed and never misattributes
   *  a project. Better trade than one person being purple here and teal there. */
  function identityKey(who) {
    var s = String(who || "").split("@")[0].toLowerCase();
    return s.split(/[^a-z0-9]+/).filter(Boolean)[0] || "";
  }

  /** A stable colour for one person, from their address OR their display name.
   *
   *  Derived, never stored, never assigned by position in a list: the same person is the
   *  same colour on every page, in every session, on everyone's machine, and a new hire
   *  needs no setup and repaints nobody. (Roster position would guarantee distinctness,
   *  but the roster is a lazy fetch and a chip has to render at once.)
   *
   *  sdbm, not djb2, and measured rather than assumed: the keys here are SHORT first
   *  names, where djb2 clusters badly. Across the roster plus a dozen common first names
   *  sdbm separated 12 where djb2 managed 10 — and djb2 put Kyle and a demo account on
   *  the same colour on the same board, which is what sent me looking. `|0` keeps the
   *  arithmetic in int32 so it can't drift into floats. */
  function colorOf(who) {
    var s = identityKey(who);
    if (!s) return AVATAR_NONE;
    var h = 0;
    for (var i = 0; i < s.length; i++) h = (s.charCodeAt(i) + (h << 6) + (h << 16) - h) | 0;
    return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
  }

  /** The chip, ready to interpolate. Takes an address or a display name.
   *
   *  Safe without escaping by construction: the initials are letters pulled out by regex
   *  and the colour is one of our constants, so a hostile value can't reach the output.
   *  `dim` marks an inherited owner nobody actually chose. aria-hidden because the name
   *  is always rendered right beside it — a reader announcing "K L Kyle Loseke" is noise. */
  function avatarHtml(who, dim) {
    var ini = initialsOf(who);
    return '<span class="tw-av' + (dim ? " tw-av-dim" : "") + '" aria-hidden="true"'
      + ' style="background:' + colorOf(who) + '">' + (ini || "—") + "</span>";
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
        var tx = cardTotal(x), ty = cardTotal(y);
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
    STAGE_CREATED: STAGE_CREATED,
    LOST_REASON: LOST_REASON, MILESTONES: MILESTONES, STAGE_DATE_KEY: STAGE_DATE_KEY,
    SORT_FIELDS: SORT_FIELDS, NATURAL_DIR: NATURAL_DIR, COMPARE: COMPARE,
    followup: followup, isLost: isLost, isWon: isWon, wonByHand: wonByHand,
    depositSatisfied: depositSatisfied,
    isTest: isTest, nameLooksLikeTest: nameLooksLikeTest,
    stage: stage, lastActivity: lastActivity, activityTs: activityTs, stageTs: stageTs,
    estimatorOf: estimatorOf, isAssigned: isAssigned, cardTotal: cardTotal,
    pausedUntil: pausedUntil,
    lostReason: lostReason, followupOff: followupOff, nameOf: nameOf,
    initialsOf: initialsOf, colorOf: colorOf, avatarHtml: avatarHtml, identityKey: identityKey,
    AVATAR_COLORS: AVATAR_COLORS, AVATAR_NONE: AVATAR_NONE,
    sort: sort, group: group,
  };
});
