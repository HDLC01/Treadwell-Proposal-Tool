/* This Week, /bd/ (#807: BD's js/week.js, moved in as it works today) - the salesperson's one daily
 * screen. The approved redesign: the apply plan, section 2.1; the artboards Week.dc.html and
 * WeekPhone.dc.html; restyled like the proposal tool by the approved BD mock-up.
 *
 * WHAT CHANGED IN THE MOVE:
 *   - BD's own shell (BDAuth) is gone. The page starts once the tool's shell settles (TWAuth.ready,
 *     which never settles on a page the tool refused, so its refusal card stays) and reads who this
 *     is from TWAuth.bdMe(): the same single /api/bd/me answer the sidebar's BD group reads. A failed
 *     answer (no BD login, a turned-off one, BD off, no network) is said in TWAuth.bdFailure's words,
 *     and the page shows no data.
 *   - ROLE HOME. BD's old shell sent each role to its BD home; that redirect lives here now. A role
 *     whose home is Contacts (the assistant: can.week is false, and the week route refuses her) is
 *     sent to CONTACTS_HOME, which until the Contacts page moves is a plain page saying it is coming.
 *   - LINKS ONLY TO PAGES THAT HAVE MOVED. A person's name, Next up's "Open <name>" and the More
 *     menu's "Open contact" go to their contact page (/bd/contact.html, moved in #808), through
 *     BD.safeHref. Nothing links to the Contacts page until it moves.
 *   - Toasts are BD.toast's; every route is under /api/bd/.
 *
 * The principle (docs/product-brief.md): the system manages the backlog, the salesperson manages
 * only the next 10. So this page shows ONLY this week's list: a greeting, the year's pace and the
 * week's 10 as dots, ONE "Next up" card, the rest of the 10 as compact rows, what is done (and what
 * was taken off), the next steps waiting to be confirmed, and "Give me 10 more". It never shows an
 * overdue count, never lists the backlog, and the list never refills itself.
 *
 * Calling: every Call is a real tel: link whose click also opens the after-a-call sheet
 * (js/call.js, window.BDCall). The sheet saves the outcome and confirms the next step; this page
 * moves the row to Done and refreshes the counts when it hears back (onChange).
 *
 * Maintenance follow-ups (cadence rules, 2026-11-10): a maintenance contact whose follow-up is due
 * is pinned at the TOP of the owner's list (task kind "maintenance"). It is not one of the 10:
 * "N of 10 done", the dots and the bar count the live Friday batch's business-development tasks
 * only, and a separate "Due now: N maintenance follow-up(s)" line counts the open pinned ones
 * (WeekView due_count). The first one is Next up; the rest sit in a "Due now" group above "Rest of
 * your 10". It cannot be taken off by hand: no "Not this week" and no "Done, nothing to log" (the
 * server answers 409 for both), no Undo on a done one; any logged call, meeting, email or text
 * clears it and moves it to Done.
 *
 * Hooks the tests use (the plan's 1.4 hook rules): exactly one node per task carries data-task
 * (the Next up card or a list row), with data-status open | done | snoozed; the tracker dots carry
 * data-dot-task; tray items carry data-contact / data-rec; the menu's choices come back as the
 * "bd-menu" event, never as a click on a .menu node.
 *
 * Routes (all in docs/bd/api-contract.md): GET /api/bd/week (?owner=, ?week_start=),
 * GET /api/bd/users, GET /api/bd/settings, GET /api/bd/contacts/{id},
 * GET /api/bd/contacts/{id}/interactions, POST /api/bd/tasks/{id}/done | snooze | reopen,
 * POST /api/bd/recommendations/{id}/confirm, POST /api/bd/week/ten-more,
 * POST /api/bd/admin/weekly/run. The week is drawn from what GET /api/bd/week answers: the page keeps
 * no list of its own.
 */
(function () {
  "use strict";

  var BD = window.BD, BDApi = window.BDApi;
  // The Contacts page: the BD home of a role without a weekly list. Until Contacts moves it is a
  // plain page saying the page is coming, with a link to Add contact (#808).
  var CONTACTS_HOME = "/bd/contacts.html";
  var esc = BD.esc;

  var CALL_KEY = "bd_call_started";
  var CALL_KEEP_MS = 2 * 60 * 60 * 1000;     // a dialled call reopens its sheet for 2 hours

  var S = {
    me: null,          // /api/bd/me's answer (TWAuth.bdMe())
    today: null,       // Central "today" from /api/bd/me
    week: null,        // the WeekView
    byId: {},          // task id -> task
    details: {},       // contact id -> {contact, timeline, pending, missed}
    // What this person may do: /api/bd/me's can (bd/auth.py can()), never worked out from a role name.
    canAct: false,     // can.send: may call, take off, mark done, ask for more
    canSend: false,    // can.send: may decide next steps and send follow-ups (the tray)
    canRun: false,     // can.run_batch: may build the Friday list
    canPick: false,    // can.pick_owner: may look at any salesperson's week (sees the score)
    owner: null,       // the owner asked for (?owner= or the picker); null = none yet (a manager or admin is asked)
    chooser: false,    // manager or admin with no ?owner=: greeted and asked whose week to look at
    ai: false,         // settings.ai_enabled
    settings: null,    // GET /api/bd/settings (null until it answers; the empty week reads its run day and hour)
    loadToken: 0,
    nextWeek: undefined,   // undefined: not asked; null: none; else next week's WeekView
    preview: false,    // "See next week's 10" open
    showNames: false,  // the not-reached names shown
    doneOpen: null,    // null = the default for the width (open on desktop, closed on a phone)
    trayOpen: null,    // the contact id whose tray item is open (desktop)
    trayAll: false,    // "Show 2 more" pressed
    moreMsg: "",       // the 409 sentence under Give me 10 more
    offNow: {},        // task ids taken off in this page view (their Undo is shown)
  };

  var main = document.getElementById("main");
  var listsEl = document.getElementById("lists");
  var finishEl = document.getElementById("finish");
  var summaryEl = document.getElementById("summary");
  var subEl = document.getElementById("week-sub");
  var greetEl = document.getElementById("wk-greeting");
  var eyebrowEl = document.getElementById("wk-eyebrow");
  var liveEl = document.getElementById("live");
  var ownerField = document.getElementById("owner-field");
  var ownerPick = document.getElementById("owner-pick");
  var trayEl = document.getElementById("wk-tray");
  var layoutEl = document.getElementById("wk-layout");

  var icon = BD.icon;
  function $(sel, root) { return (root || document).querySelector(sel); }
  function toast(msg, o) { return BD.toast(msg, o || {}); }
  function fail(e) { toast((e && e.message) || "Something went wrong. Try again.", { kind: "error" }); }
  function clamp(n) { n = Number(n) || 0; return n < 0 ? 0 : (n > 100 ? 100 : n); }
  function isPhone() { return !!(window.matchMedia && window.matchMedia("(max-width: 767px)").matches); }
  function plural(n, one, many) { return BD.plural(n, one, many); }

  /** Run one request with the clicked button shown as busy. Resolves to the response, or to
   *  undefined after showing the error (so callers just `if (!r) return;`). */
  function run(btn, work) {
    if (btn && btn.classList.contains("is-busy")) return Promise.resolve();
    if (btn) { btn.classList.add("is-busy"); btn.setAttribute("aria-busy", "true"); }
    var clear = function () {
      if (btn) { btn.classList.remove("is-busy"); btn.removeAttribute("aria-busy"); }
    };
    return work().then(function (r) { clear(); return r; }, function (e) { clear(); fail(e); });
  }

  // ── data ─────────────────────────────────────────────────────────────────────────────────

  function setWeek(w) {
    S.week = w;
    S.byId = {};
    (w.tasks || []).forEach(function (t) { S.byId[t.id] = t; });
  }

  function weekPath(weekStart) {
    var q = [];
    if (S.canPick && S.owner != null) q.push("owner=" + encodeURIComponent(S.owner));
    if (weekStart) q.push("week_start=" + encodeURIComponent(weekStart));
    if (!q.length) return "/api/bd/week";
    return "/api/bd/week?" + q.join("&");
  }

  function loadWeek() {
    return BDApi.get(weekPath()).then(function (r) { setWeek(r.week); return r.week; });
  }

  function batches() {
    var w = S.week;
    var b = (w.batches || []).slice();
    if (!b.length && w.batch) b = [w.batch];
    return b;
  }

  /** The live Friday batch's business-development tasks (the latest Friday batch: one a forced
   *  re-run replaced is still listed, not counted; the pinned maintenance tasks are not one of the
   *  10). Without a batch list, every task that is not an extra. The "did I do my 10?" headline
   *  counts only these (WeekView done_count/total). */
  function fridayTasks() {
    var w = S.week;
    var tasks = (w.tasks || []).filter(function (t) { return t.kind !== "maintenance"; });
    var fri = batches().filter(function (b) { return b.kind === "friday"; }).map(function (b) { return b.id; });
    if (!fri.length) {
      var extra = batches().filter(function (b) { return b.kind === "ten_more"; }).map(function (b) { return b.id; });
      return tasks.filter(function (t) { return extra.indexOf(t.batch_id) === -1; });
    }
    var live = fri[fri.length - 1];
    return tasks.filter(function (t) { return t.batch_id === live; });
  }

  function extraBatches() { return batches().filter(function (b) { return b.kind === "ten_more"; }); }

  function isOpen(t) { return t.status === "open"; }
  function isMaint(t) { return t.kind === "maintenance"; }

  /** "Due now": the open maintenance follow-ups on this week's lists (any batch). The server's
   *  WeekView due_count when it sent one (applyTask keeps it current), else counted here. */
  function dueNow() {
    var w = S.week;
    if (w && typeof w.due_count === "number") return w.due_count;
    return ((w && w.tasks) || []).filter(function (t) { return isMaint(t) && isOpen(t); }).length;
  }

  /** Everything the page draws, worked out once per paint. */
  function parts() {
    var tasks = S.week.tasks || [];
    var fri = fridayTasks();
    var openFri = fri.filter(isOpen);
    var extras = extraBatches();
    var openExtra = [];
    extras.forEach(function (b) {
      tasks.forEach(function (t) { if (t.batch_id === b.id && isOpen(t) && !isMaint(t)) openExtra.push(t); });
    });
    // The open pinned follow-ups (any batch, the server's order: they head every list) come first.
    var maint = tasks.filter(function (t) { return isMaint(t) && isOpen(t); });
    var next = maint[0] || openFri[0] || openExtra[0] || null;
    var order = {};
    tasks.forEach(function (t, i) { order[t.id] = i; });
    var done = tasks.filter(function (t) { return t.status === "done"; }).sort(function (a, b) {
      var x = String(a.done_at || ""), y = String(b.done_at || "");
      return x < y ? -1 : (x > y ? 1 : order[a.id] - order[b.id]);
    });
    var off = tasks.filter(function (t) { return t.status === "snoozed"; });
    var friDone = fri.filter(function (t) { return t.status === "done"; }).length;
    var friOff = fri.filter(function (t) { return t.status === "snoozed"; }).length;
    return {
      tasks: tasks, fri: fri, openFri: openFri, openExtra: openExtra, extras: extras, next: next,
      maint: maint, due: maint.filter(function (t) { return t !== next; }),
      rest: openFri.filter(function (t) { return t !== next; }),
      done: done, off: off, friDone: friDone, friOff: friOff,
    };
  }

  /** normal (something to call) | alldone | nothingleft | finished | empty. "finished" comes from
   *  data, never the clock: nothing open, something not done, and next week's Friday list already
   *  made (the Friday run closed what was left as snoozed). */
  function weekState(p) {
    if (!p.tasks.length) return "empty";
    if (p.next) return "normal";
    if (p.fri.length && p.friDone === p.fri.length) return "alldone";
    var nw = S.nextWeek;
    if (nw && (nw.tasks || []).length) return "finished";
    return "nothingleft";
  }

  function own() {
    var w = S.week, meId = S.me && S.me.user && S.me.user.id;
    return !w.owner || w.owner.id === meId;
  }

  /** The contact page, back to This Week ("" for a contact with no id: then the name is plain text). */
  function contactHref(c) {
    return c && c.id != null ? BD.pageHref("/bd/contact.html?id=", c.id, "&from=week") : "";
  }

  /** A row's name and company: a link to the contact page. */
  function whoHTML(c) {
    var inner = '<span class="who-name">' + esc(c.name) + "</span>" +
      '<span class="who-sub">' + esc(c.company ? c.company.name : "") + "</span>";
    var href = contactHref(c);
    return href ? '<a class="who wk-who" href="' + esc(href) + '">' + inner + "</a>" : '<span class="who wk-who">' + inner + "</span>";
  }

  /** The task's contact, with what GET /api/contacts/{id} added once it has landed. */
  function contactFor(t) {
    var c = t.contact || {};
    var d = S.details[c.id];
    if (!d || !d.contact) return c;
    var out = {};
    Object.keys(d.contact).forEach(function (k) { out[k] = d.contact[k]; });
    Object.keys(c).forEach(function (k) { if (out[k] == null) out[k] = c[k]; });
    return out;
  }

  /** The contacts whose details the page needs: Next up's (city, last live talk) and every closed
   *  task's (the done line's outcome, and the tray). */
  function wantedIds() {
    var p = parts();
    var ids = [];
    if (p.next && p.next.contact) ids.push(p.next.contact.id);
    p.done.concat(p.off).forEach(function (t) {
      if (t.contact && ids.indexOf(t.contact.id) === -1) ids.push(t.contact.id);
    });
    return ids;
  }

  /** GET /api/contacts/{id} and its timeline for each id (all in parallel). A failure leaves
   *  that contact empty (no outcome, no tray item): these are extras, never an error on screen. */
  function loadDetails(ids, force) {
    var need = ids.filter(function (id) { return id != null && (force || !S.details[id]); });
    return Promise.all(need.map(function (id) {
      return Promise.all([
        BDApi.get(BDApi.path("contacts", id)),
        BDApi.get(BDApi.path("contacts", id, "interactions")),
      ]).then(function (rs) {
        var a = rs[0] || {}, b = rs[1] || {};
        S.details[id] = { contact: a.contact || null, pending: a.pending_recommendation || null,
          missed: a.missed_call || null, timeline: b.items || [] };
      }, function () {
        S.details[id] = { contact: null, pending: null, missed: null, timeline: [], failed: true };
      });
    }));
  }

  /** Quietly pull fresh numbers after a change (and the details of `ids` again), then repaint.
   *  Only the newest answer is used. */
  function refreshAll(ids) {
    var token = ++S.loadToken;
    return Promise.all([
      BDApi.get(weekPath()).then(function (r) { return r.week; }),
      loadDetails(ids || [], true),
    ]).then(function (rs) {
      if (token !== S.loadToken) return;
      setWeek(rs[0]);
      S.nextWeek = undefined;
      renderAll();
      return loadDetails(wantedIds()).then(function () {
        if (token === S.loadToken) { renderMain(); renderTray(); }
      });
    }, function () {
      if (token === S.loadToken) renderAll();   // the page keeps what the action returned
    });
  }

  /** "Nothing left" or "week finished"? Asked once, only when nothing is open and not all is
   *  done: is next week's Friday list already made? */
  function maybeNextWeek() {
    if (S.nextWeek !== undefined) return;
    var p = parts();
    if (!p.tasks.length || p.next || !p.fri.length || p.friDone === p.fri.length) return;
    S.nextWeek = null;
    var monday = nextMonday();
    if (!monday) return;
    BDApi.get(weekPath(monday)).then(function (r) {
      var w = r && r.week;
      S.nextWeek = w && (w.tasks || []).length ? w : null;
      if (S.nextWeek) renderAll();
    }, function () { /* no next week to show */ });
  }

  function nextMonday() {
    var ws = S.week && S.week.week_start;
    if (!ws) return "";
    var d = new Date(ws + "T12:00:00Z");
    d.setUTCDate(d.getUTCDate() + 7);
    return d.toISOString().slice(0, 10);
  }

  // ── words ────────────────────────────────────────────────────────────────────────────────

  function phoneOf(c) { return c && c.phone ? BD.fmtPhone(c.phone) : ""; }

  /** The reason to show on a row: the first one the status pill does not already say, up to its
   *  first ";" ("Last live talk 7 months ago; needs 3 a year" -> "Last live talk 7 months ago"). */
  function reasonOf(t) {
    var r = BD.firstReason(t);
    return r ? r.split(";")[0].trim() : "";
  }

  /** A reason as HTML with each "Fri, Oct 23" date kept on one line (a row's reason column is narrow, and
   *  a date split across two lines reads untidy). The text itself is unchanged. */
  var DATE_IN_REASON = /\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), [A-Z][a-z]{2} \d{1,2}\b/g;
  function reasonHTML(reason) {
    var out = "", last = 0, m;
    DATE_IN_REASON.lastIndex = 0;
    while ((m = DATE_IN_REASON.exec(reason))) {
      out += esc(reason.slice(last, m.index)) + '<span class="wk-nowrap">' + esc(m[0]) + "</span>";
      last = m.index + m[0].length;
    }
    return out + esc(reason.slice(last));
  }

  /** "Sep 15" from a date (fmtDay without the weekday). */
  function monthDay(iso) { return BD.fmtDay(iso, S.today).replace(/^[A-Za-z]+,\s*/, ""); }


  var KIND_WORD = { call: "call", meeting: "meeting", hosted: "hosted event", voicemail: "voicemail" };

  /** The newest live talk (a touch) on a contact's timeline, or null. */
  function lastLive(d) {
    var items = (d && d.timeline) || [];
    for (var i = 0; i < items.length; i++) {
      var x = items[i];
      if (x.type === "interaction" && x.interaction && x.interaction.counts_as_touch) return x.interaction;
    }
    return null;
  }

  var OUTCOME_WORD = { answered: "Talked", meeting_set: "Meeting set", voicemail: "Voicemail", no_answer: "No answer" };

  /** The words for one logged interaction. A maintenance follow-up is also cleared by an email or
   *  a text ("Emailed", "Texted"); a kind the page does not know says "Followed up". A note never
   *  clears one, and is no follow-up for a business-development task either: null. */
  function interactionWord(it, maint) {
    var k = it.kind;
    if (k === "call") return OUTCOME_WORD[it.outcome] || (maint ? "Followed up" : null);
    if (k === "voicemail") return "Voicemail";
    if (k === "meeting") return "Meeting";
    if (k === "hosted") return "Hosted event";
    if (!maint || k === "note") return null;
    if (k === "email") return "Emailed";
    if (k === "sms") return "Texted";
    return "Followed up";
  }

  /** "Talked · Mon, Nov 2" for a done task: the newest call, voicemail, meeting or hosted event
   *  (or "Not the right person"; for a maintenance follow-up also "Emailed" or "Texted") since
   *  the week began; "Done" when nothing was logged. Null while the contact's timeline is still
   *  on its way. */
  function doneLine(t) {
    var d = S.details[t.contact && t.contact.id];
    if (!d) return null;
    var ws = S.week.week_start;
    var items = d.timeline || [];
    for (var i = 0; i < items.length; i++) {
      var x = items[i];
      if (BD.bizDateOf(x.at) < ws) break;
      if (x.type === "event" && x.event && x.event.action === "unconfirmed") return "Not the right person · " + BD.fmtDay(x.at, S.today);
      if (x.type !== "interaction" || !x.interaction) continue;
      var it = x.interaction;
      var word = interactionWord(it, isMaint(t));
      if (word) return word + " · " + BD.fmtDay(it.occurred_at || x.at, S.today);
    }
    return "Done" + (t.done_at ? " · " + BD.fmtDay(t.done_at, S.today) : "");
  }

  /** "Try again" from "Try Ray again": the action without the person's first name. */
  function shortAction(action, c) {
    var f = BD.firstName(c);
    var s = String(action || "");
    if (!f) return s;
    var re = new RegExp("\\s+" + f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "(?=\\s|$)");
    return s.replace(re, "");
  }

  // ── the tray: next steps to confirm ──────────────────────────────────────────────────────

  /** Every decision left from this week's calls: a pending suggestion made this week and/or a
   *  missed call this week with no follow-up yet, one item per person, soonest step first. */
  function trayItems() {
    if (!S.canSend || !S.week) return [];
    var ws = S.week.week_start;
    var seen = {}, items = [];
    (S.week.tasks || []).forEach(function (t) {
      if (t.status === "open" || !t.contact) return;
      var cid = t.contact.id;
      if (seen[cid]) return;
      seen[cid] = true;
      var d = S.details[cid];
      if (!d) return;
      var rec = d.pending && BD.bizDateOf(d.pending.created_at) >= ws ? d.pending : null;
      var missed = d.missed && BD.bizDateOf(d.missed.occurred_at) >= ws ? d.missed : null;
      if (!rec && !missed) return;
      var iid = missed ? missed.interaction_id : rec.interaction_id;
      var inter = null;
      (d.timeline || []).some(function (x) {
        if (x.type === "interaction" && x.interaction && x.interaction.id === iid) { inter = x.interaction; return true; }
        return false;
      });
      items.push({ cid: cid, task: t, contact: d.contact || t.contact, rec: rec, missed: missed, interaction: inter });
    });
    items.sort(function (a, b) {
      var x = a.rec ? a.rec.due_date : "9999", y = b.rec ? b.rec.due_date : "9999";
      return x < y ? -1 : (x > y ? 1 : String(a.contact.name).localeCompare(String(b.contact.name)));
    });
    return items;
  }

  /** The tray has its data: every closed task's details have landed. */
  function trayReady() {
    return (S.week.tasks || []).every(function (t) {
      return t.status === "open" || !t.contact || !!S.details[t.contact.id];
    });
  }

  function traySub(it) {
    if (!it.rec) return "Send a follow-up?";
    return shortAction(it.rec.action, it.contact) + " " + BD.fmtDay(it.rec.due_date, S.today);
  }

  // ── drawing: header and progress ─────────────────────────────────────────────────────────

  function renderHead() {
    var w = S.week;
    var a = BD.fmtDay(w.week_start, S.today), b = BD.fmtDay(w.week_end, S.today);
    var sa = monthDay(w.week_start), sb = monthDay(w.week_end);
    var sameMonth = sa.split(" ")[0] === sb.split(" ")[0];
    eyebrowEl.innerHTML = '<span class="hide-phone">' + esc("This Week · " + a + " - " + b) + "</span>" +
      '<span class="show-phone">' + esc("This Week · " + sa + " - " + (sameMonth ? sb.split(" ")[1] : sb)) + "</span>";
    if (own()) {
      greetEl.textContent = BD.greeting(BD.bizNowISO()) + ", " + BD.firstName(S.me && S.me.user);
    } else {
      greetEl.textContent = BD.firstName(w.owner) + "'s week";
    }
    var p = parts(), st = weekState(p);
    var sub;
    if (st === "empty") sub = "Nothing on the list this week.";
    else if (p.openFri.length) sub = plural(p.openFri.length, "call") + " to go this week.";
    else if (p.maint.length) {
      sub = (p.fri.length && p.friDone === p.fri.length ? "All " + p.fri.length + " done. " : "") +
        plural(p.maint.length, "maintenance follow-up") + " still due.";
    }
    else if (p.fri.length && p.friDone === p.fri.length) sub = "All " + p.fri.length + " done. Nice work.";
    else if (st === "finished") sub = "This week is finished.";
    else if (p.openExtra.length) sub = plural(p.openExtra.length, "extra call") + " to go.";
    else sub = "Nothing left this week.";
    subEl.textContent = sub;
  }

  function renderSummary() {
    var w = S.week;
    var pw = BD.paceWords(w.pace || {}, S.today);
    var year = (w.pace && w.pace.year) || String(S.today || "").slice(0, 4);
    var fri = fridayTasks();
    var total = fri.length;
    var done = fri.filter(function (t) { return t.status === "done"; }).length;
    var mark = pw.target > 0 ? clamp(100 * pw.dueToday / pw.target) : 0;
    var pillKind = pw.state === "behind" ? "warn" : "ok";

    var words;
    if (pw.sentence.indexOf(pw.short + ".") === 0) {
      words = '<span class="wk-delta is-' + pw.state + '">' + esc(pw.short + ".") + "</span>" + esc(pw.sentence.slice(pw.short.length + 1));
    } else {
      words = '<span class="wk-delta is-' + pw.state + '">' + esc(pw.sentence) + "</span>";
    }
    var pace = '<div class="wk-pace">' +
      '<p class="wk-zone-label hide-phone">' + esc(year + " pace") + "</p>" +
      '<div class="wk-pace-line"><p class="wk-pace-big"><span class="wk-pace-num">' + esc(pw.pct + "%") + "</span> " +
      '<span class="wk-pace-of">' + esc("of the way to " + BD.fmtCount(pw.target)) + "</span></p>" +
      '<span class="show-phone"><span class="pill pill-' + pillKind + '">' + esc(pw.short) + "</span></span></div>" +
      '<div class="progress wk-bar" role="img" aria-label="' + esc(pw.pct + "% of the way to " + pw.target + ": " + pw.done +
        " done. Where you should be today: " + pw.dueToday + ".") + '">' +
      '<div class="progress-fill" data-w="' + clamp(pw.pct) + '"></div>' +
      (pw.target > 0 ? '<div class="progress-mark" data-l="' + mark + '"></div>' +
        '<span class="progress-mark-label' + (mark < 30 ? " is-start" : "") + '" data-l="' + mark + '">' + esc("Today's pace: " + pw.dueToday) + "</span>" : "") +
      "</div>" +
      '<p class="wk-pace-words hide-phone" id="pace-words">' + words + "</p>" +
      '<p class="wk-pace-caption hide-phone" id="pace-caption">' + esc(pw.caption) + "</p></div>";

    // Under the headline: the pinned maintenance follow-ups still open. Absent at 0.
    var due = dueNow();
    var dueLine = due > 0
      ? '<p class="wk-due-line" id="wk-due-line">' + esc("Due now: " + plural(due, "maintenance follow-up")) + "</p>" : "";
    var weekZone;
    if (!total) {
      weekZone = '<div class="wk-week"><p class="wk-zone-label hide-phone">This week</p>' +
        '<p class="wk-count" id="week-count">No list yet</p>' + dueLine + "</div>";
    } else {
      var news = fri.filter(function (t) { return t.kind === "new"; });
      var follows = fri.filter(function (t) { return t.kind !== "new"; });
      var group = function (list, label) {
        if (!list.length) return "";
        var d = list.filter(function (t) { return t.status === "done"; }).length;
        // Filled from the left: done, then to do, then taken off (the artboards' order).
        var rank = function (t) { return t.status === "done" ? 0 : (t.status === "snoozed" ? 2 : 1); };
        var sorted = list.map(function (t, i) { return { t: t, i: i }; }).sort(function (a, b) {
          return rank(a.t) - rank(b.t) || a.i - b.i;
        }).map(function (x) { return x.t; });
        return '<div class="dots-group"><div class="dots-row">' + sorted.map(function (t) {
          var cls = t.status === "done" ? " is-done" : (t.status === "snoozed" ? " is-off" : "");
          var word = t.status === "done" ? "done" : (t.status === "snoozed" ? "taken off" : "to do");
          return '<span class="dot' + cls + '" data-dot-task="' + esc(t.id) + '" title="' + esc((t.contact && t.contact.name) + ", " + word) + '"></span>';
        }).join("") + '</div><span class="dots-legend hide-phone">' + esc(label + ": " + d + " of " + list.length) + "</span></div>";
      };
      var all = done === total;
      var count = all
        ? '<p class="wk-count is-all" id="week-count">' + esc("All " + total + " done") + "</p>"
        : '<p class="wk-count" id="week-count"><span class="wk-count-n">' + done + '</span> <span class="wk-count-of">of ' + total + "</span> done</p>";
      var nd = news.filter(function (t) { return t.status === "done"; }).length;
      var fd = follows.filter(function (t) { return t.status === "done"; }).length;
      var m = w.weekly_meetings || {};
      weekZone = '<div class="wk-week"><p class="wk-zone-label hide-phone">This week</p>' +
        '<div class="wk-week-line">' + count +
        '<div class="dots wk-dots" role="img" aria-label="' + esc(done + " of " + total + " done: " + nd + " of " + news.length +
          " new, " + fd + " of " + follows.length + " follow-ups") + '">' +
        group(news, "New") + group(follows, "Follow-ups") + "</div></div>" + dueLine +
        // The goal is the weekly meetings goal, so the count beside it is meetings (weekly_meetings.count).
        (m.goal ? '<p class="wk-live hide-phone">' + esc("Meetings this week: " + (Number(m.count) || 0) + " of " + m.goal) + "</p>" : "") +
        "</div>";
    }
    summaryEl.innerHTML = '<div class="wk-progress-in">' + pace + weekZone + "</div>";
    // Widths and lefts through the DOM (not style="" in markup) so a strict CSP cannot block them.
    Array.prototype.forEach.call(summaryEl.querySelectorAll("[data-w]"), function (el) { el.style.width = el.getAttribute("data-w") + "%"; });
    Array.prototype.forEach.call(summaryEl.querySelectorAll("[data-l]"), function (el) { el.style.left = el.getAttribute("data-l") + "%"; });
    if (liveEl && total) liveEl.textContent = done + " of " + total + " done";
  }

  // ── drawing: the lists ───────────────────────────────────────────────────────────────────

  function moreBtnHTML(t, extraCls) {
    var c = t.contact || {};
    return '<button type="button" class="btn btn-icon wk-more' + (extraCls ? " " + extraCls : "") + '" data-act="more" aria-label="' +
      esc("More for " + c.name) + '" aria-haspopup="menu" aria-expanded="false">' + icon("more", 20) + "</button>";
  }

  function callBtnHTML(c) {
    var href = BD.telHref(c);
    if (!href) return '<span class="wk-nophone">No phone</span>';
    return '<a class="btn-call" href="' + esc(href) + '" data-act="call" aria-label="' + esc("Call " + c.name + ", " + phoneOf(c)) + '">' +
      icon("phone", 20) + "</a>";
  }

  /** One row of the 10 (Rest, an extra group, next week's preview). */
  function rowHTML(t, opts) {
    var o = opts || {};
    var c = t.contact || {};
    var hook = o.preview ? ' data-preview-task="' + esc(t.id) + '"' : ' data-task="' + esc(t.id) + '" data-status="' + esc(t.status) + '"';
    var reason = reasonOf(t);
    // A pinned maintenance follow-up says "Maintenance · due" (the neutral "Maintenance" pill would repeat it,
    // but a warning or Key account pill still shows beside it).
    var status = BD.statusPill(c, t.reasons, isMaint(t));
    var pill = (isMaint(t) ? BD.kindPill(t) : "") + status;
    var two = isMaint(t) && status !== "";   // two pills: the middle column gives the pill cell more room
    // Admin acts AND picks: the manager's "Priority N" caption goes under the pill.
    if (!o.preview && S.canAct && S.canPick && t.score != null && !isMaint(t)) pill += '<span class="wk-score">' + esc("Priority " + t.score) + "</span>";
    var acts;
    // No phone number: More stays on a phone too, where it takes the call column (bd.css
    // .wk-row-nophone), or a phone user could not take the task off, mark it done or flag the person.
    var noPhone = !o.preview && S.canAct && !BD.telHref(c);
    if (o.preview) {
      acts = '<span class="wk-row-meta">' + esc(phoneOf(c)) + "</span>";
    } else if (S.canAct) {
      acts = '<span class="wk-row-call">' + callBtnHTML(c) + "</span>" + moreBtnHTML(t, (noPhone ? "" : "hide-phone ") + "wk-row-more");
    } else {
      acts = '<span class="wk-row-meta"><span>' + esc(phoneOf(c)) + "</span>" +
        (S.canPick && t.score != null && !isMaint(t) ? '<span class="wk-score">' + esc("Priority " + t.score) + "</span>" : "") + "</span>";
    }
    return '<li class="list-row wk-row' + (two ? " wk-row-two" : "") + (noPhone ? " wk-row-nophone" : "") +
      (S.canAct && !o.preview ? "" : " is-readonly") + '"' + hook + ">" +
      BD.avatarHTML(c.name || "", "") +
      whoHTML(c) +
      '<span class="wk-reason">' + reasonHTML(reason) + "</span>" +
      '<span class="wk-pill">' + pill + "</span>" + acts + "</li>";
  }

  function nextHTML(t) {
    var c = contactFor(t);
    var d = S.details[c.id];
    var reason = reasonOf(t);
    var kind = BD.kindPill(t);
    var metaWide = [c.title, c.company && c.company.name, c.city].filter(Boolean).join(" · ");
    var acts = "";
    if (S.canAct) {
      var href = BD.telHref(c);
      acts = '<div class="wk-next-acts">' +
        (href
          ? '<a class="btn btn-primary wk-call" href="' + esc(href) + '" data-act="call">' + icon("phone", 18) + esc("Call " + phoneOf(c)) + "</a>"
          : '<button type="button" class="btn" disabled>No phone number</button>') +
        // A pinned maintenance follow-up cannot be taken off by hand: no "Not this week".
        (isMaint(t) ? "" : '<button type="button" class="btn hide-phone" data-act="snooze">' + icon("clock", 18) + "Not this week</button>") +
        moreBtnHTML(t, "wk-next-more") + "</div>" +
        (isMaint(t) ? '<p class="wk-next-stays">Stays on your list until you log a call, meeting, email or text.</p>' : "") +
        (S.canPick && t.score != null && !isMaint(t) ? '<p class="wk-score wk-next-score">' + esc("Priority " + t.score) + "</p>" : "");
    } else {
      acts = '<p class="wk-next-phone">' + esc([phoneOf(c), S.canPick && t.score != null && !isMaint(t) ? "Priority " + t.score : ""].filter(Boolean).join(" · ")) + "</p>";
    }
    var live = d ? lastLive(d) : null;
    var side, line;
    if (!d) {
      side = '<div class="skeleton wk-skel-line"></div><div class="skeleton wk-skel-line"></div>';
      line = '<span class="skeleton wk-skel-line"></span>';
    } else if (!live) {
      side = '<p class="wk-next-when">No live talk yet.</p>';
      line = "No live talk yet.";
    } else {
      var bits = [KIND_WORD[live.kind] || live.kind];
      if (BD.fmtMinutes(live.duration_s)) bits.push(BD.fmtMinutes(live.duration_s));
      side = '<p class="wk-next-when">' + esc(BD.fmtDay(live.occurred_at, S.today) + " · " + bits.join(", ")) + "</p>" +
        (live.summary ? '<p class="wk-next-sum">' + esc(live.summary) + "</p>" : "");
      line = esc("Last talk " + monthDay(live.occurred_at) + (live.summary ? ": " + String(live.summary).replace(/\.+$/, "") : ""));
    }
    return '<section class="wk-next-sec" id="wk-next" aria-labelledby="wk-next-name">' +
      '<article class="card wk-next" data-task="' + esc(t.id) + '" data-status="open">' +
      '<div class="wk-next-main">' +
      '<div class="wk-next-top"><p class="wk-next-label">Next up</p><span class="wk-next-kind-top">' + kind + "</span></div>" +
      '<div class="wk-next-who">' + BD.avatarHTML(c.name || "", "lg") +
      '<div class="wk-next-id"><div class="wk-next-namerow"><h2 class="wk-next-name" id="wk-next-name">' +
      (contactHref(c) ? '<a href="' + esc(contactHref(c)) + '">' + esc(c.name) + "</a>" : esc(c.name)) + "</h2>" +
      '<span class="wk-next-kind">' + kind + "</span></div>" +
      '<p class="wk-next-meta wk-meta-wide">' + esc(metaWide) + "</p>" +
      '<p class="wk-next-meta wk-meta-narrow"><span>' + esc(c.company ? c.company.name : "") + "</span>" +
      (c.title ? "<span>" + esc(c.title) + "</span>" : "") + "</p></div></div>" +
      (reason ? '<p class="wk-next-reason">' + icon("calendar", 18) + "<span>" + esc(reason) + "</span></p>" : "") +
      '<p class="wk-next-line">' + line + "</p>" +
      acts + "</div>" +
      '<div class="wk-next-side"><p class="wk-next-label2">Last live talk</p>' + side +
      (contactHref(c) ? '<a class="btn-link wk-next-open" href="' + esc(contactHref(c)) + '">' + esc("Open " + c.name) + icon("arrow-right", 16) + "</a>" : "") +
      "</div>" +
      "</article></section>";
  }

  function tenMoreHTML(note) {
    if (!S.canAct) return "";
    return '<div class="wk-ten"><button type="button" class="btn" id="ten-more-btn" data-act="ten-more">' + icon("plus", 18) + "Give me 10 more</button>" +
      '<span class="wk-ten-note">' + esc(note) + "</span></div>" +
      (S.moreMsg ? '<p class="wk-ten-msg" role="status">' + esc(S.moreMsg) + "</p>" : "");
  }

  function endHTML(st, p) {
    var h;
    if (st === "finished") {
      var nw = S.nextWeek || {};
      h = '<p class="wk-end-title">' + esc("This week is finished: " + p.friDone + " of " + p.fri.length + " done.") + "</p>" +
        '<p class="wk-end-text">' + esc("Your next 10 are ready for " + BD.fmtDay(nw.week_start, S.today) + ".") + "</p>" +
        '<div class="wrap-row"><button type="button" class="btn" data-act="next-week" aria-expanded="' + S.preview + '" aria-controls="wk-preview">' +
        esc(S.preview ? "Hide next week's 10" : "See next week's 10") + "</button></div>";
    } else if (st === "alldone") {
      h = '<p class="wk-end-title">' + icon("check-circle", 20) + esc("All " + p.fri.length + " done this week.") + "</p>" + tenMoreHTML("Optional.");
    } else {
      // A week of only maintenance follow-ups has no 10: count everything closed.
      var nDone = p.fri.length ? p.friDone : p.done.length, nOff = p.fri.length ? p.friOff : p.off.length;
      h = '<p class="wk-end-title">' + esc("Nothing left this week. " + nDone + " done, " + nOff + " taken off.") + "</p>" + tenMoreHTML("Optional.");
    }
    return '<section class="wk-next-sec" id="wk-next" aria-label="This week"><div class="card wk-end' + (st === "alldone" ? " is-all" : "") + '">' + h + "</div></section>";
  }

  /** "Due now": the other open maintenance follow-ups, from any batch of the week, above the 10. */
  function dueHTML(p) {
    if (!p.due.length) return "";
    return '<section class="section wk-due" id="wk-due" aria-labelledby="wk-due-h">' +
      '<div class="section-head"><h2 class="section-title" id="wk-due-h">Due now</h2>' +
      '<span class="section-meta">' + esc(p.due.length + " to go") + "</span></div>" +
      '<div class="card card-flush"><ul class="list wk-list wk-due-list">' + p.due.map(function (t) { return rowHTML(t); }).join("") + "</ul></div></section>";
  }

  function restHTML(p) {
    if (!p.rest.length) return "";
    return '<section class="section wk-rest" id="wk-rest" aria-labelledby="wk-rest-h">' +
      '<div class="section-head"><h2 class="section-title" id="wk-rest-h">' + (own() ? "Rest of your 10" : "Rest of the 10") + "</h2>" +
      '<span class="section-meta">' + esc(p.rest.length + " to go") + "</span></div>" +
      '<div class="card card-flush"><ul class="list wk-list">' + p.rest.map(function (t) { return rowHTML(t); }).join("") + "</ul></div></section>";
  }

  function extrasHTML(p) {
    var tasks = p.tasks;
    var list = p.extras;
    return list.map(function (b, i) {
      var mine = tasks.filter(function (t) { return t.batch_id === b.id && !isMaint(t); });
      var d = mine.filter(function (t) { return t.status === "done"; }).length;
      var open = mine.filter(function (t) { return isOpen(t) && t !== p.next; });
      var title = mine.length + " more (to get ahead)" + (list.length > 1 ? " (" + (i + 1) + ")" : "");
      return '<section class="section wk-extra" data-batch="' + esc(b.id) + '" aria-labelledby="wk-g' + esc(b.id) + '">' +
        '<div class="section-head"><h2 class="section-title" id="wk-g' + esc(b.id) + '" tabindex="-1">' + esc(title) + "</h2>" +
        '<span class="section-meta">' + esc(d + " of " + mine.length + " extra done") + "</span></div>" +
        (open.length ? '<div class="card card-flush"><ul class="list wk-list">' + open.map(function (t) { return rowHTML(t); }).join("") + "</ul></div>" : "") +
        "</section>";
    }).join("");
  }

  function trayBannerHTML() {
    if (!S.canSend || !S.week || !(S.week.tasks || []).length) return "";
    if (!trayReady()) return '<div class="section show-phone"><div class="skeleton wk-skel-banner"></div></div>';
    var items = trayItems();
    if (!items.length) return "";
    var it = items[0];
    var sub = it.contact.name + ": " + traySub(it).charAt(0).toLowerCase() + traySub(it).slice(1);
    return '<div class="section show-phone"><button type="button" class="card wk-tray-banner" id="wk-tray-banner" data-act="tray-sheet" aria-haspopup="dialog">' +
      '<span class="wk-tray-bulb">' + icon("lightbulb", 20) + "</span>" +
      '<span class="who"><span class="who-name">' + esc(plural(items.length, "next step") + " to confirm") + "</span>" +
      '<span class="who-sub">' + esc(sub) + "</span></span>" + icon("chev-right", 20) + "</button></div>";
  }

  function doneRowHTML(t) {
    var c = t.contact || {};
    var line = doneLine(t);
    // No Undo on a done maintenance follow-up: reopening it would leave a pin nobody can clear.
    var undo = S.canAct && !isMaint(t) && BD.bizDateOf(t.done_at) === S.today
      ? '<button type="button" class="btn-link wk-undo" data-act="reopen" aria-label="' + esc("Undo for " + c.name) + '">Undo</button>' : "";
    return '<li class="list-row wk-row wk-done-row is-done" data-task="' + esc(t.id) + '" data-status="done">' +
      BD.avatarHTML(c.name || "", "", "done") +
      whoHTML(c) +
      '<span class="wk-outcome">' + (line == null ? '<span class="skeleton wk-skel-short"></span>' : esc(line)) + "</span>" + undo + "</li>";
  }

  function offRowHTML(t) {
    var c = t.contact || {};
    var undo = S.canAct && S.offNow[t.id]
      ? '<button type="button" class="btn-link wk-undo" data-act="reopen" aria-label="' + esc("Undo for " + c.name) + '">Undo</button>' : "";
    return '<li class="list-row wk-row wk-done-row is-off" data-task="' + esc(t.id) + '" data-status="snoozed">' +
      BD.avatarHTML(c.name || "", "", "off") +
      whoHTML(c) +
      '<span class="wk-outcome">Not this week</span>' + undo + "</li>";
  }

  function doneHTML(p, st) {
    var finished = st === "finished";
    var off = finished ? [] : p.off;
    var notReached = finished ? p.off : [];
    if (!p.done.length && !off.length && !notReached.length) return "";
    var openNow = S.doneOpen == null ? !isPhone() : S.doneOpen;
    var cheer = p.done.length ? "Nice. " + p.done.length + " done." : "";
    var body = "";
    if (p.done.length || off.length) {
      body = '<div class="card card-flush">' +
        (p.done.length ? '<ul class="list wk-list">' + p.done.map(doneRowHTML).join("") + "</ul>" : "") +
        (off.length ? '<p class="wk-sublabel">Taken off this week</p><ul class="list wk-list">' + off.map(offRowHTML).join("") + "</ul>" : "") +
        "</div>";
    }
    var reached = "";
    if (notReached.length) {
      reached = '<p class="wk-notreached">' + esc(notReached.length + " not reached this week. They go back on the list and can come up again.") +
        ' <button type="button" class="btn-link" data-act="show-names" aria-expanded="' + S.showNames + '">' + (S.showNames ? "Hide names" : "Show names") + "</button></p>" +
        (S.showNames ? '<ul class="wk-names">' + notReached.map(function (t) {
          return '<li data-task="' + esc(t.id) + '" data-status="snoozed">' + esc(t.contact && t.contact.name) + "</li>";
        }).join("") + "</ul>" : "");
    }
    return '<section class="section wk-done" id="wk-done" aria-labelledby="wk-done-h">' +
      '<div class="section-head wk-done-head"><h2 class="section-title" id="wk-done-h">Done this week</h2>' +
      (cheer ? '<span class="wk-cheer">' + icon("check-circle", 18) + esc(cheer) + "</span>" : "") +
      (body ? '<button type="button" class="btn-link wk-done-hide" data-act="toggle-done" aria-expanded="' + openNow + '" aria-controls="wk-done-body">' +
        (openNow ? "Hide" : "Show") + "</button>" : "") + "</div>" +
      (body ? '<button type="button" class="card wk-done-toggle" data-act="toggle-done" aria-expanded="' + openNow + '" aria-controls="wk-done-body">' +
        '<span class="wk-done-ico">' + icon("check", 18) + "</span>" +
        '<span class="who"><span class="who-name wk-done-cheer">' + esc(cheer || "Done this week") + "</span>" +
        (cheer ? '<span class="who-sub">Done this week</span>' : "") + "</span>" + icon(openNow ? "chev-up" : "chev-down", 20) + "</button>" : "") +
      (body ? '<div class="wk-done-body" id="wk-done-body"' + (openNow ? "" : " hidden") + ">" + body + "</div>" : "") +
      reached + "</section>";
  }

  function previewHTML() {
    var nw = S.nextWeek;
    if (!S.preview || !nw) return "";
    return '<section class="section wk-preview" id="wk-preview" aria-labelledby="wk-preview-h">' +
      '<div class="section-head"><h2 class="section-title" id="wk-preview-h" tabindex="-1">Next week\'s 10</h2>' +
      '<span class="section-meta">Calls open on Monday.</span></div>' +
      '<div class="card card-flush"><ul class="list wk-list">' + (nw.tasks || []).map(function (t) { return rowHTML(t, { preview: true }); }).join("") +
      "</ul></div></section>";
  }

  var DAY_WORD = { monday: "Monday", tuesday: "Tuesday", wednesday: "Wednesday", thursday: "Thursday",
                   friday: "Friday", saturday: "Saturday", sunday: "Sunday" };

  /** When the Friday worker makes the next list: settings.weekly.run_day and run_hour, the ones it
   *  runs on (bd/weekly_worker.py). Friday at 4 PM, the default, until the settings answer. */
  function nextListWords() {
    var w = (S.settings && S.settings.weekly) || {};
    var day = DAY_WORD[String(w.run_day || "").toLowerCase()] || "Friday";
    var hour = Number(w.run_hour);
    if (w.run_hour == null || w.run_hour === "" || !(hour >= 0 && hour <= 23) || Math.floor(hour) !== hour) hour = 16;
    return "The next list arrives " + day + " at " + (hour % 12 === 0 ? 12 : hour % 12) + (hour < 12 ? " AM." : " PM.");
  }

  function emptyHTML() {
    var run = S.canRun ? '<button type="button" class="btn" data-act="run-weekly">' + icon("refresh", 18) + "Make this week's list now</button>" : "";
    var more = S.canAct ? '<button type="button" class="btn" id="ten-more-btn" data-act="ten-more">' + icon("plus", 18) + "Give me 10 more</button>" : "";
    return '<div class="card empty wk-empty"><div class="empty-ico">' + icon("calendar", 22) + "</div>" +
      '<p class="empty-title">Nothing on the list this week.</p>' +
      '<p class="empty-text">' + esc(nextListWords()) + "</p>" +
      (more || run ? '<div class="wrap-row wk-empty-acts">' + more + run + "</div>" : "") +
      (S.moreMsg ? '<p class="wk-ten-msg" role="status">' + esc(S.moreMsg) + "</p>" : "") + "</div>";
  }

  /** Where focus is inside the lists, as a selector that finds the same control after a repaint
   *  (a row's button by its task, or an id). */
  function focusKey() {
    var a = document.activeElement;
    if (!a || !main.contains(a) || a === main) return null;
    var host = a.closest("[data-task]"), act = a.getAttribute("data-act");
    if (host && act) return '[data-task="' + host.getAttribute("data-task") + '"] [data-act="' + act + '"]';
    if (a.id) return "#" + a.id;
    if (act) return '[data-act="' + act + '"]';
    return null;
  }

  function renderMain() {
    if (!S.week) return;
    var key = focusKey();
    paintMain();
    if (key && !main.contains(document.activeElement)) focusLater(key);
  }

  function paintMain() {
    var p = parts(), st = weekState(p);
    var h = "";
    if (st === "empty") {
      h = emptyHTML();
    } else {
      h += st === "normal" ? nextHTML(p.next) : endHTML(st, p);
      h += dueHTML(p);
      h += restHTML(p);
      h += extrasHTML(p);
      h += trayBannerHTML();
      h += doneHTML(p, st);
      h += previewHTML();
    }
    listsEl.innerHTML = h;
    finishEl.innerHTML = st === "normal" ? '<div class="section wk-finish">' + tenMoreHTML("Your 10 stay as they are.") + "</div>" : "";
  }

  function renderTray() {
    if (!S.week) return;
    var show = S.canSend && (S.week.tasks || []).length > 0;
    trayEl.hidden = !show;
    layoutEl.classList.toggle("wk-solo", !show);
    if (!show) { trayEl.innerHTML = ""; return; }
    var head = function (n) {
      return '<div class="section-head wk-tray-head"><h2 class="section-title" id="wk-tray-h">Next steps to confirm</h2>' +
        (n ? '<span class="count count-warn">' + n + '<span class="sr-only"> to confirm</span></span>' : "") + "</div>";
    };
    if (!trayReady()) {
      trayEl.innerHTML = head(0) + '<div class="card wk-tray-wait"><div class="skeleton wk-skel-line"></div><div class="skeleton wk-skel-line"></div></div>';
      return;
    }
    var items = trayItems();
    if (!items.length) {
      S.trayOpen = null;
      trayEl.innerHTML = head(0) + '<p class="wk-tray-empty" role="status">' + icon("check-circle", 18) + "All next steps are confirmed.</p>";
      return;
    }
    if (S.trayOpen != null && !items.some(function (it) { return it.cid === S.trayOpen; })) S.trayOpen = null;
    var shown = S.trayAll ? items : items.slice(0, 3);
    var li = shown.map(function (it) {
      var c = it.contact;
      var openIt = S.trayOpen === it.cid;
      var bodyId = "wk-tray-b-" + it.cid;
      var confirm = it.rec && !openIt
        ? '<button type="button" class="btn wk-tray-confirm" data-act="tray-confirm" data-rec="' + esc(it.rec.id) + '" data-contact="' + esc(it.cid) + '"' +
          ' aria-label="' + esc("Confirm: " + it.rec.action + ", " + BD.fmtDay(it.rec.due_date, S.today)) + '">Confirm</button>' : "";
      return '<li class="wk-tray-item' + (openIt ? " is-open" : "") + '" data-contact="' + esc(it.cid) + '">' +
        '<div class="wk-tray-row"><button type="button" class="wk-tray-line" data-act="tray-open" data-contact="' + esc(it.cid) + '"' +
        ' aria-expanded="' + openIt + '" aria-controls="' + bodyId + '">' + BD.avatarHTML(c.name || "", "sm") +
        '<span class="who"><span class="who-name">' + esc(c.name) + "</span>" +
        '<span class="who-sub">' + esc(traySub(it)) + "</span></span>" + icon(openIt ? "chev-up" : "chev-down", 18) + "</button>" +
        confirm + "</div>" + (openIt ? '<div class="wk-tray-body" id="' + bodyId + '"></div>' : "") + "</li>";
    }).join("");
    var more = !S.trayAll && items.length > 3
      ? '<button type="button" class="btn-link wk-tray-more" data-act="tray-more">' + esc("Show " + (items.length - 3) + " more") + "</button>" : "";
    trayEl.innerHTML = head(items.length) + '<div class="card card-flush"><ul class="wk-tray-list">' + li + "</ul></div>" + more;
    if (S.trayOpen != null) {
      var it = items.filter(function (x) { return x.cid === S.trayOpen; })[0];
      var body = trayEl.querySelector("#wk-tray-b-" + it.cid);
      if (body) window.BDCall.decide(body, decideOpts(it));
    }
  }

  function decideOpts(it) {
    return {
      contact: it.contact, recommendation: it.rec, missed: it.missed, interaction: it.interaction,
      aiEnabled: S.ai, canSend: S.canSend,
      onChange: function () { afterTrayChange(it.cid); },
    };
  }

  function afterTrayChange(cid) {
    var token = S.loadToken;
    loadDetails([cid], true).then(function () {
      if (token !== S.loadToken) return;
      renderMain();
      renderTray();
    });
  }

  function renderAll() {
    renderHead();
    renderSummary();
    renderMain();
    renderTray();
    maybeNextWeek();
  }

  // ── actions ──────────────────────────────────────────────────────────────────────────────

  function applyTask(t, x) {
    if (!t || !x) return;
    if (x.status) t.status = x.status;
    if ("done_at" in x) t.done_at = x.done_at;
    if ("snoozed_until" in x) t.snoozed_until = x.snoozed_until;
    // "Due now" follows the change at once (the next refresh brings the server's own number).
    if (S.week && typeof S.week.due_count === "number" && isMaint(t)) {
      S.week.due_count = (S.week.tasks || []).filter(function (y) { return isMaint(y) && isOpen(y); }).length;
    }
  }

  function taskOf(el) {
    var host = el && el.closest ? el.closest("[data-task]") : null;
    return host ? S.byId[Number(host.getAttribute("data-task"))] || null : null;
  }

  function focusLater(sel) {
    var n = sel ? $(sel) : null;
    if (n) { try { n.focus({ preventScroll: true }); } catch (e) { n.focus(); } }
  }

  /** Open the after-a-call sheet for a task: "call" (from a Call link), "meeting" or "nrp". */
  function openCall(t, mode) {
    if (!S.canAct || !window.BDCall) return;
    var c = contactFor(t);
    if (mode === "call") BD.store.set(CALL_KEY, { contact_id: c.id, task_id: t.id, at: Date.now() }, { session: true });
    window.BDCall.open({
      contact: c, task: t, mode: mode, startedAt: mode === "call" ? BD.bizNowISO() : null,
      aiEnabled: S.ai, canSend: S.canSend,
      returnFocus: function () { return callFocusTarget(t); },
      onChange: function (ev) { onCallChange(t, c, ev); },
    });
  }

  /** Where focus goes when the call sheet closes after a save redrew the row it was opened from:
   *  the row's Undo, else the next Call, else the first Call on the page, else the heading. */
  function callFocusTarget(t) {
    var shown = function (sel) {
      return Array.prototype.filter.call(document.querySelectorAll(sel), function (n) { return n.getClientRects().length > 0; })[0] || null;
    };
    return shown('[data-task="' + t.id + '"] [data-act="reopen"]') || shown('[data-task="' + t.id + '"] [data-act="call"]') ||
      shown('#wk-next [data-act="call"]') || shown('#lists [data-act="call"]') || shown(".wk-done-toggle") || $("main h1");
  }

  function onCallChange(t, c, ev) {
    BD.store.del(CALL_KEY, { session: true });
    var r = ev && ev.result;
    if (!r) return;                                   // closed with nothing sent: nothing changed
    if (r.task && r.task.id === t.id) applyTask(t, r.task);
    refreshAll([c.id]).then(function () {
      // The redraw replaced the focused element: put focus back on the row, not on <body>.
      var a = document.activeElement;
      if (window.BDCall.isOpen() || (a && a !== document.body && document.contains(a))) return;
      var n = callFocusTarget(t);
      if (n) {
        if (n.tagName === "H1" && !n.hasAttribute("tabindex")) n.setAttribute("tabindex", "-1");
        try { n.focus({ preventScroll: true }); } catch (e) { n.focus(); }
      }
    });
  }

  /** Back from the phone app (or a reload) with a dialled call not saved: the sheet again. */
  function maybeReopenCall() {
    if (!S.canAct || !window.BDCall || window.BDCall.isOpen()) return;
    var rec = BD.store.get(CALL_KEY, { session: true });
    if (!rec) return;
    var t = S.byId[rec.task_id];
    if (!t || t.status !== "open" || !(Date.now() - Number(rec.at) < CALL_KEEP_MS)) {
      BD.store.del(CALL_KEY, { session: true });
      return;
    }
    openCall(t, "call");
  }

  function doDone(t, btn) {
    run(btn, function () { return BDApi.post(BDApi.path("tasks", t.id, "done")); }).then(function (r) {
      if (!r) return;
      applyTask(t, r.task);
      renderAll();
      focusLater('[data-task="' + t.id + '"] [data-act="reopen"]');
      toast("Done. Nothing logged.", { action: { label: "Undo", onClick: function () { doReopen(t, null); } } });
      refreshAll([t.contact.id]);
    });
  }

  function doSnooze(t, btn) {
    run(btn, function () { return BDApi.post(BDApi.path("tasks", t.id, "snooze"), {}); }).then(function (r) {
      if (!r) return;
      applyTask(t, r.task);
      S.offNow[t.id] = true;
      renderAll();
      focusLater("#wk-next [data-act=\"call\"]");
      toast("Taken off this week.", { action: { label: "Undo", onClick: function () { doReopen(t, null); } } });
      refreshAll([t.contact.id]);
    });
  }

  function doReopen(t, btn) {
    run(btn, function () { return BDApi.post(BDApi.path("tasks", t.id, "reopen")); }).then(function (r) {
      if (!r) return;
      applyTask(t, r.task);
      delete S.offNow[t.id];
      renderAll();
      focusLater('[data-task="' + t.id + '"] [data-act="call"]');
      refreshAll([]);
    });
  }

  function tenMore(btn) {
    var w = S.week;
    var body = w.owner && w.owner.id != null ? { owner: w.owner.id } : {};
    var before = (w.tasks || []).length;
    if (btn.classList.contains("is-busy")) return;
    btn.classList.add("is-busy"); btn.setAttribute("aria-busy", "true");
    BDApi.post("/api/bd/week/ten-more", body).then(function (r) {
      S.moreMsg = "";
      setWeek(r.week);
      S.nextWeek = undefined;
      renderAll();
      var added = (r.week.tasks || []).length - before;
      toast(added > 0 ? plural(added, "more name") + " added below." : "Nothing new to add.", { kind: "ok" });
      var ex = extraBatches();
      var last = ex[ex.length - 1];
      var head = last ? document.getElementById("wk-g" + last.id) : null;
      if (head) {
        var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        head.scrollIntoView({ block: "start", behavior: calm ? "auto" : "smooth" });
        head.focus({ preventScroll: true });
      }
    }, function (e) {
      btn.classList.remove("is-busy"); btn.removeAttribute("aria-busy");
      if (e && e.status === 409) {
        S.moreMsg = e.message || "Everyone on your list is already covered this week.";
        renderMain();
        focusLater("#ten-more-btn");
        return;
      }
      fail(e);
    });
  }

  function runWeekly(btn) {
    var w = S.week;
    var body = { week_start: w.week_start };
    if (w.owner && w.owner.id != null) body.owner = w.owner.id;
    run(btn, function () { return BDApi.post("/api/bd/admin/weekly/run", body); }).then(function (r) {
      if (!r) return;
      return loadWeek().then(function () {
        renderAll();
        toast("This week's list is ready.", { kind: "ok" });
        return loadDetails(wantedIds()).then(function () { renderMain(); renderTray(); });
      });
    });
  }

  function trayConfirm(btn) {
    var rid = Number(btn.getAttribute("data-rec"));
    var cid = Number(btn.getAttribute("data-contact"));
    var d = S.details[cid] || {};
    var rec = d.pending && d.pending.id === rid ? d.pending : null;
    run(btn, function () { return BDApi.post(BDApi.path("recommendations", rid, "confirm"), {}); }).then(function (r) {
      if (!r) return;
      var saved = (r && r.recommendation) || rec || {};
      toast("Next step saved: " + (saved.action || (rec && rec.action) || "") + ", " + BD.fmtDay(saved.due_date || (rec && rec.due_date), S.today) + ".", { kind: "ok" });
      if (S.details[cid]) S.details[cid].pending = null;
      renderMain();
      renderTray();
      focusLater("#wk-tray-h");
      afterTrayChange(cid);
    });
  }

  /** The phone's "N next steps to confirm" banner opens a sheet of the items; one opens the call
   *  sheet in decide mode. */
  function openTraySheet() {
    var items = trayItems();
    if (!items.length) return;
    var el = document.createElement("div");
    el.className = "sheet wk-traysheet";
    el.setAttribute("aria-labelledby", "wk-traysheet-h");
    el.innerHTML = '<div class="sheet-grab" aria-hidden="true"></div>' +
      '<div class="sheet-head"><h2 class="sheet-title" id="wk-traysheet-h">Next steps to confirm</h2>' +
      '<button type="button" class="btn btn-icon" data-act="close" aria-label="Close">' + icon("x", 20) + "</button></div>" +
      '<div class="sheet-body"><ul class="wk-traysheet-list">' + items.map(function (it) {
        return '<li><button type="button" class="wk-tray-line wk-traysheet-item" data-pick="' + esc(it.cid) + '">' +
          BD.avatarHTML(it.contact.name || "", "sm") +
          '<span class="who"><span class="who-name">' + esc(it.contact.name) + "</span>" +
          '<span class="who-sub">' + esc(traySub(it)) + "</span></span>" + icon("chev-right", 18) + "</button></li>";
      }).join("") + "</ul></div>";
    var picked = null;
    el.addEventListener("click", function (e) {
      var b = e.target.closest ? e.target.closest("[data-pick], [data-act]") : null;
      if (!b) return;
      if (b.hasAttribute("data-pick")) {
        picked = Number(b.getAttribute("data-pick"));
        BD.sheet.close(el, "pick");
      } else if (b.getAttribute("data-act") === "close") BD.sheet.close(el, "close");
    });
    document.body.appendChild(el);
    BD.sheet.open(el, {
      onClose: function () {
        setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 240);
        if (picked == null) return;
        var it = items.filter(function (x) { return x.cid === picked; })[0];
        if (!it) return;
        window.BDCall.open({
          contact: it.contact, task: it.task, mode: "decide", recommendation: it.rec, missed: it.missed,
          interaction: it.interaction, aiEnabled: S.ai, canSend: S.canSend,
          onChange: function () { afterTrayChange(it.cid); },
        });
      },
    });
  }

  function menuItems(t, where) {
    var items = [];
    var maint = isMaint(t);     // a pinned follow-up cannot be taken off by hand (the server says 409)
    if (!maint && (where === "row" || isPhone())) items.push({ act: "snooze", label: "Not this week", icon: "clock" });
    items.push({ act: "log-meeting", label: "Log a meeting", icon: "users" });
    items.push({ act: "nrp", label: "Not the right person", icon: "user-x" });
    if (!maint) items.push({ act: "done", label: "Done, nothing to log", icon: "check" });
    if (contactHref(t.contact)) items.push({ act: "open", label: "Open contact", icon: "arrow-right", href: contactHref(t.contact) });
    return items;
  }

  // ── events (one set, on the page) ────────────────────────────────────────────────────────

  main.addEventListener("click", function (e) {
    var target = e.target;
    if (!target.closest) return;
    if (target.closest("[data-call-root]") || target.closest(".menu")) return;   // BDCall's own, and the menu's
    var btn = target.closest("[data-act]");
    if (!btn || !main.contains(btn)) return;
    var act = btn.getAttribute("data-act");
    var t = taskOf(btn);

    if (act === "call") { if (t) openCall(t, "call"); return; }   // a real tel: link: no preventDefault
    if (act === "ten-more") return tenMore(btn);
    if (act === "run-weekly") return runWeekly(btn);
    if (act === "toggle-done") {
      var openNow = S.doneOpen == null ? !isPhone() : S.doneOpen;
      S.doneOpen = !openNow;
      renderMain();
      focusLater(isPhone() ? ".wk-done-toggle" : ".wk-done-hide");
      return;
    }
    if (act === "next-week") {
      S.preview = !S.preview;
      renderMain();
      focusLater(S.preview ? "#wk-preview-h" : '[data-act="next-week"]');
      return;
    }
    if (act === "show-names") { S.showNames = !S.showNames; renderMain(); focusLater('[data-act="show-names"]'); return; }
    if (act === "tray-open") {
      var cid = Number(btn.getAttribute("data-contact"));
      S.trayOpen = S.trayOpen === cid ? null : cid;
      renderTray();
      focusLater('.wk-tray-line[data-contact="' + cid + '"]');
      return;
    }
    if (act === "tray-confirm") return trayConfirm(btn);
    if (act === "tray-more") { S.trayAll = true; renderTray(); focusLater(".wk-tray-item:nth-child(4) .wk-tray-line"); return; }
    if (act === "tray-sheet") return openTraySheet();
    if (!t || !S.canAct) return;
    if (act === "more") { BD.menu(btn, menuItems(t, btn.closest("#wk-next") ? "next" : "row")); return; }
    if (act === "snooze") return doSnooze(t, btn);
    if (act === "reopen") return doReopen(t, btn);
  });

  // The menu's choices, from BD.menu (dispatched on its anchor, inside a row or Next up).
  main.addEventListener("bd-menu", function (e) {
    var d = e.detail || {};
    var t = taskOf(d.anchor);
    if (!t || !S.canAct) return;
    if (d.act === "snooze") doSnooze(t, null);
    else if (d.act === "done") doDone(t, null);
    else if (d.act === "log-meeting") openCall(t, "meeting");
    else if (d.act === "nrp") openCall(t, "nrp");
  });

  // Hovering or focusing a person's row rings their dot in the tracker.
  function hot(id) {
    Array.prototype.forEach.call(summaryEl.querySelectorAll(".dot.is-hot"), function (d) { d.classList.remove("is-hot"); });
    if (id == null) return;
    var dot = summaryEl.querySelector('[data-dot-task="' + id + '"]');
    if (dot) dot.classList.add("is-hot");
  }
  function hotFrom(e) {
    var host = e.target.closest ? e.target.closest("[data-task]") : null;
    hot(host ? host.getAttribute("data-task") : null);
  }
  listsEl.addEventListener("mouseover", hotFrom);
  listsEl.addEventListener("focusin", hotFrom);
  listsEl.addEventListener("mouseleave", function () { hot(null); });
  listsEl.addEventListener("focusout", function (e) { if (!listsEl.contains(e.relatedTarget)) hot(null); });

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && S.week) maybeReopenCall();
  });

  // ── start ────────────────────────────────────────────────────────────────────────────────

  function showError(e) {
    summaryEl.innerHTML = "";
    finishEl.innerHTML = "";
    trayEl.hidden = true;
    layoutEl.classList.add("wk-solo");
    if (e && e.status === 403) {
      // The week route refused this role (the assistant is sent home before this runs; this is the
      // net). Trying again can't help: she goes to her own BD home.
      goHome();
      return;
    }
    listsEl.innerHTML = '<div class="error-box" role="alert"><p>' + esc((e && e.message) || "Could not load your week.") + "</p>" +
      '<button type="button" class="btn" id="retry">Try again</button></div>';
    var retry = document.getElementById("retry");
    if (retry) retry.addEventListener("click", start);
  }

  // ── owner picker (manager and admin: "Whose list") ───────────────────────────────────────

  /** Fill the picker with the salespeople (GET /api/users), plus whoever this week belongs to
   *  if that is someone else (an ?owner= link). Shown only to a manager or admin. */
  function fillOwners() {
    if (!S.canPick || !ownerPick) return Promise.resolve();
    return BDApi.get("/api/bd/users").then(function (r) {
      var all = r.items || [];
      var people = BD.withRole(all, ["salesperson"]);
      var cur = S.week && S.week.owner;
      if (cur && !all.some(function (u) { return u.id === cur.id; })) people.push(cur);
      ownerPick.innerHTML = (cur ? "" : '<option value="" disabled selected>Choose someone</option>') +
        people.map(function (u) {
          return '<option value="' + esc(u.id) + '"' + (cur && u.id === cur.id ? " selected" : "") + ">" + esc(u.name) + "</option>";
        }).join("");
      ownerField.hidden = !people.length;
    }, function () { ownerField.hidden = true; });
  }

  /** Keep ?owner= in the address so the view can be shared or reloaded. */
  function rememberOwner() {
    try {
      var q = new URLSearchParams(location.search);
      if (S.owner != null) q.set("owner", S.owner); else q.delete("owner");
      var s = q.toString();
      history.replaceState(null, "", location.pathname + (s ? "?" + s : "") + location.hash);
    } catch (e) { /* the view still changes; only the address does not */ }
  }

  /** A manager or admin has no weekly list of their own, and the page no longer opens on
   *  somebody else's: it greets whoever is signed in and asks whose week to look at. Opening a
   *  link with ?owner= still goes straight to that list. */
  function renderChooser() {
    eyebrowEl.textContent = "This Week";
    greetEl.textContent = BD.greeting(BD.bizNowISO()) + ", " + BD.firstName(S.me && S.me.user);
    subEl.textContent = "Choose whose week to look at.";
    summaryEl.innerHTML = "";
    summaryEl.hidden = true;          // no pace card until there is a week to show
    finishEl.innerHTML = "";
    trayEl.hidden = true;
    layoutEl.classList.add("wk-solo");
    return BDApi.get("/api/bd/users").then(function (r) {
      var people = (r.items || []).filter(function (u) { return u.role === "salesperson" && u.active !== false; });
      listsEl.innerHTML = people.length
        ? '<div class="section"><h2 class="section-title">Whose week?</h2><div class="wk-choices">' + people.map(function (u) {
            return '<button type="button" class="btn btn-secondary" data-pick="' + esc(u.id) + '">' + esc(u.name) + "</button>";
          }).join("") + "</div></div>"
        : '<div class="panel-info" role="status">' + icon("info", 18) +
          "<span>Nobody has a weekly list yet.</span></div>";
      return fillOwners();
    }, function (e) { listsEl.innerHTML = ""; fail(e); });
  }

  listsEl.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-pick]");
    if (b) pickOwner(Number(b.getAttribute("data-pick")));
  });

  function showLoading() {
    listsEl.innerHTML = '<div class="section" id="loading" aria-hidden="true"><div class="stack-lg">' +
      '<div class="skeleton skeleton-card"></div><div class="skeleton skeleton-card"></div></div></div>';
    finishEl.innerHTML = "";
  }

  /** Show one salesperson's week (the picker and the "Whose week?" buttons both come here). */
  function pickOwner(v) {
    if (!v) return;
    S.owner = v;
    S.chooser = false;
    summaryEl.hidden = false;
    rememberOwner();
    var token = ++S.loadToken;
    showLoading();
    BDApi.get(weekPath()).then(function (r) {
      if (token !== S.loadToken) return;   // a newer pick is on its way
      setWeek(r.week);
      S.nextWeek = undefined; S.preview = false; S.trayOpen = null; S.moreMsg = "";
      if (ownerPick && ownerPick.querySelector('option[value="' + v + '"]')) ownerPick.value = String(v);
      renderAll();
      if (liveEl) liveEl.textContent = "Showing " + ((S.week.owner && S.week.owner.name) || "this") + "'s list.";
      return loadDetails(wantedIds()).then(function () {
        if (token === S.loadToken) { renderMain(); renderTray(); }
      });
    }).catch(showError);
  }

  if (ownerPick) {
    ownerPick.addEventListener("change", function () { pickOwner(Number(ownerPick.value)); });
  }

  /** A role whose BD home is Contacts: sent there, and this page is left out of the history. */
  function goHome() {
    try { window.location.replace(CONTACTS_HOME); } catch (e) { window.location.href = CONTACTS_HOME; }
  }

  /** /api/bd/me did not answer ok (no BD login, a turned-off one, BD off, no network): the
   *  server's own sentence, in TWAuth.bdFailure's words, and no data. */
  function showRefused(res) {
    eyebrowEl.textContent = "This Week";
    greetEl.textContent = "BD CRM";
    subEl.textContent = window.TWAuth.bdFailure(res && res.status, res && res.body).message;
    summaryEl.innerHTML = "";
    summaryEl.hidden = true;
    listsEl.innerHTML = "";
    finishEl.innerHTML = "";
    trayEl.hidden = true;
    layoutEl.classList.add("wk-solo");
  }

  var STOP = {};     // start() went no further: refused, or sent to the role's home

  function start() {
    var auth = window.TWAuth;
    if (!auth || !auth.ready || typeof auth.bdMe !== "function" || typeof auth.bdFailure !== "function") return;
    auth.ready.then(function () { return auth.bdMe(); }).then(function (res) {
      var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
      if (!ok) { showRefused(res); return STOP; }
      var me = res.body;
      if (!(me.can && me.can.week === true)) { goHome(); return STOP; }
      S.me = me;
      S.today = me.today || BD.bizToday();
      if (window.BDCall && typeof window.BDCall.setMe === "function") window.BDCall.setMe(me);
      S.canAct = S.canSend = me.can.send === true;
      S.canRun = me.can.run_batch === true;
      S.canPick = me.can.pick_owner === true;
      // ai_enabled only shows or hides "Suggest from my note", and the run day and hour only word the
      // empty week: a failure is just "off" and the default. A week drawn before they answer is
      // drawn again.
      BDApi.get("/api/bd/settings").then(function (r) {
        S.settings = (r && r.settings) || null;
        S.ai = !!(S.settings && S.settings.ai_enabled);
        if (S.week) renderMain();
      }, function () {});
      var asked = Number(BD.qs("owner"));
      S.owner = S.canPick && asked > 0 ? asked : null;
      S.chooser = S.canPick && S.owner == null;
      if (S.chooser) return null;
      return loadWeek().catch(function (e) {
        // An ?owner= link to someone who is not there any more, or who has no weekly list (only a
        // salesperson has one): say so and show the default list instead.
        if (!(e && e.status === 404 && S.owner != null)) throw e;
        S.owner = null;
        rememberOwner();
        return loadWeek().then(function (w) {
          toast(((e && e.message) || "That list was not found.") + " Showing " + ((w.owner && w.owner.name) || "the default") + "'s list.");
          return w;
        });
      });
    }).then(function (r) {
      if (r === STOP) return;
      if (S.chooser) return renderChooser();
      renderAll();
      fillOwners();
      var token = S.loadToken;
      return loadDetails(wantedIds()).then(function () {
        if (token !== S.loadToken) return;
        renderMain();
        renderTray();
        maybeReopenCall();
      });
    }).catch(showError);
  }

  start();
})();
