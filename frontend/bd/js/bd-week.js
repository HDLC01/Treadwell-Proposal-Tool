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
 *     sent to CONTACTS_HOME, the Contacts page (#810).
 *   - A person's name, Next up's "Open <name>" and the More menu's "Open contact" go to their contact
 *     page (/bd/contact.html, moved in #808), through BD.safeHref.
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
 * ONE ROW PER COMPANY (#828). The page draws the WeekView's `rows` (WeekRow: one company's tasks on
 * one list), never one row per task. A row closed shows the company, the person to call first, the
 * reason chip and the company's misses; opened (its toggle: a button, so click, Enter or Space, with
 * aria-expanded) it shows every person on the row with their title, phone, Call, last live talk,
 * tries and any promised call or next step. Calling someone opens the call sheet on THAT person (it
 * logs on them; logging with anyone there closes the row). "Not the right person" is per person (its
 * contact_id goes to the row's task); Done, Not this week and Reopen act on the whole row (any task id
 * of a row does). Next up is the first open row, drawn as a card, with the others there under it.
 * "N of 10 done", the dots and the bar count the live Friday batch's rows (section "ten").
 *
 * Maintenance follow-ups (cadence rules, 2026-11-10): a maintenance contact whose follow-up is due
 * is pinned at the TOP of the owner's list (task kind "maintenance"), one row per company (section
 * "due"). It is not one of the 10: a separate "Due now: N maintenance account(s)" line counts the
 * open "Due now" rows, companies (WeekView due_count). The first one is Next up; the rest sit in a
 * "Due now" group above "Rest of your 10". It cannot be taken off by hand: no "Not this week" and no
 * "Done, nothing to log" (the server answers 409 for both), no Undo on a done one; a logged call,
 * meeting, email or text for each person due there clears it and moves it to Done.
 *
 * The maintenance banner (#wk-due-banner, under the page header, above the progress card): while the
 * list being looked at has open "Due now" rows it says "N maintenance account(s) due this week" (the
 * same count as the "Due now" line, dueNow()) and offers Show, which only moves focus (and scrolls)
 * to the first due row: Next up, which parts() always makes the first open "Due now" row (the "Due
 * now" heading is only a fallback in case that ever changes). It follows
 * the count at once (applyRow), is redrawn for the list "Whose list" switches to, and is absent at 0,
 * while loading, on a load error and before a list is chosen. A count change after the list's first
 * paint is said in #live; a redraw with the same count says nothing.
 *
 * Hooks the tests use (the plan's 1.4 hook rules): exactly one node per ROW carries data-task, the
 * row's id (its first task; the Next up card or a list row), with data-status open | done | snoozed;
 * a person inside a row carries data-person (their contact id); the tracker dots carry
 * data-dot-task; tray items carry data-contact / data-rec; the menu's choices come back as the
 * "bd-menu" event, never as a click on a .menu node (heard on the document: a refresh that redrew
 * the row while its menu was open must not lose the choice).
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
  // The Contacts page (#810): the BD home of a role without a weekly list.
  var CONTACTS_HOME = "/bd/contacts.html";
  var esc = BD.esc;

  var CALL_KEY = "bd_call_started";
  var CALL_KEEP_MS = 2 * 60 * 60 * 1000;     // a dialled call reopens its sheet for 2 hours

  var S = {
    me: null,          // /api/bd/me's answer (TWAuth.bdMe())
    today: null,       // Central "today" from /api/bd/me
    week: null,        // the WeekView
    byId: {},          // row id AND every task id of a row -> its WeekRow
    taskById: {},      // task id -> Task (a row's first task carries the contact's pills)
    open: {},          // row ids opened in this page view
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
    offNow: {},        // row ids taken off in this page view (their Undo is shown)
    dueSaid: null,     // the "Due now" count the banner last drew for this list (null: not drawn yet)
    bannerLostFocus: false, // the banner went (or lost Show) while it held focus: renderAll re-homes it
    doneSaid: null,    // the "N of 10 done" words last put in #live for this list
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
  var bannerEl = document.getElementById("wk-due-banner");

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
    S.taskById = {};
    (w.tasks || []).forEach(function (t) { S.taskById[t.id] = t; });
    rowsOf(w).forEach(function (r) {
      S.byId[r.id] = r;
      (r.task_ids || []).forEach(function (id) { if (!S.byId[id]) S.byId[id] = r; });
    });
  }

  /** The week's company rows (WeekView rows, #828), in the server's order. */
  function rowsOf(w) { return (w && w.rows) || []; }

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

  /** The live Friday batch's rows (section "ten": the latest Friday batch, without its "Due now"
   *  rows; a batch a forced re-run replaced is still listed, not counted). The "did I do my 10?"
   *  headline counts only these, companies (WeekView done_count/total). */
  function fridayRows() {
    return rowsOf(S.week).filter(function (r) { return r.section === "ten"; });
  }

  /** The "N more (to get ahead)" lists: Give Me 10 More's lists, each holding a BD row. A list the
   *  server made only to pin a maintenance follow-up (a company made a maintenance account, #810) is
   *  not one: its pin is under "Due now", and it would read "0 more". */
  function extraBatches() {
    var rows = rowsOf(S.week);
    return batches().filter(function (b) {
      return b.kind === "ten_more" && rows.some(function (r) { return r.batch_id === b.id && r.section === "more"; });
    });
  }

  function isOpen(r) { return r.status === "open"; }
  /** A "Due now" row: maintenance follow-ups, pinned above the 10. */
  function isMaint(r) { return r.section === "due" || r.kind === "maintenance"; }

  /** "Due now": the open "Due now" rows, companies. The server's WeekView due_count when it sent
   *  one (applyRow keeps it current), else counted here. */
  function dueNow() {
    var w = S.week;
    if (w && typeof w.due_count === "number") return w.due_count;
    return rowsOf(w).filter(function (r) { return isMaint(r) && isOpen(r); }).length;
  }

  /** Everything the page draws, worked out once per paint. */
  function parts() {
    var rows = rowsOf(S.week);
    var fri = fridayRows();
    var openFri = fri.filter(isOpen);
    var extras = extraBatches();
    var openExtra = rows.filter(function (r) { return r.section === "more" && isOpen(r); });
    // The open "Due now" rows (the server's order: they head every list) come first.
    var maint = rows.filter(function (r) { return isMaint(r) && isOpen(r); });
    var next = maint[0] || openFri[0] || openExtra[0] || null;
    var order = {};
    rows.forEach(function (r, i) { order[r.id] = i; });
    var done = rows.filter(function (r) { return r.status === "done"; }).sort(function (a, b) {
      var x = String(a.done_at || ""), y = String(b.done_at || "");
      return x < y ? -1 : (x > y ? 1 : order[a.id] - order[b.id]);
    });
    var off = rows.filter(function (r) { return r.status === "snoozed"; });
    var friDone = fri.filter(function (r) { return r.status === "done"; }).length;
    var friOff = fri.filter(function (r) { return r.status === "snoozed"; }).length;
    return {
      rows: rows, fri: fri, openFri: openFri, openExtra: openExtra, extras: extras, next: next,
      maint: maint, due: maint.filter(function (r) { return r !== next; }),
      rest: openFri.filter(function (r) { return r !== next; }),
      done: done, off: off, friDone: friDone, friOff: friOff,
    };
  }

  /** normal (something to call) | alldone | nothingleft | finished | empty. "finished" comes from
   *  data, never the clock: nothing open, something not done, and next week's Friday list already
   *  made (the Friday run closed what was left as snoozed). */
  function weekState(p) {
    if (!p.rows.length) return "empty";
    if (p.next) return "normal";
    if (p.fri.length && p.friDone === p.fri.length) return "alldone";
    var nw = S.nextWeek;
    if (nw && rowsOf(nw).length) return "finished";
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

  /** The person to call first on a row: its first person (the server puts them on top). */
  function firstOf(r) { return ((r && r.people) || [])[0] || null; }

  /** A person on a row as a contact: the person, their company, and what their own task's contact
   *  adds (category, importance, a duplicate flag: what the pills read). `tasks`: task id -> Task
   *  (next week's, for its preview), else this week's. */
  function asContact(r, p, tasks) {
    var out = {};
    var t = (tasks || S.taskById)[p.task_id];
    var tc = t && t.contact && t.contact.id === p.id ? t.contact : {};
    Object.keys(tc).forEach(function (k) { out[k] = tc[k]; });
    Object.keys(p).forEach(function (k) { if (p[k] != null || out[k] == null) out[k] = p[k]; });
    out.company = r.company || out.company;
    return out;
  }

  /** The person a control belongs to: the data-person around it, else the row's first person. */
  function personOf(el, r) {
    var host = el && el.closest ? el.closest("[data-person]") : null;
    var id = host ? Number(host.getAttribute("data-person")) : null;
    var ps = (r && r.people) || [];
    for (var i = 0; i < ps.length; i++) if (ps[i].id === id) return ps[i];
    return firstOf(r);
  }

  /** The row's first person as a contact, with what GET /api/contacts/{id} added once it has landed. */
  function contactFor(r) {
    var c = asContact(r, firstOf(r) || {});
    var d = S.details[c.id];
    if (!d || !d.contact) return c;
    var out = {};
    Object.keys(d.contact).forEach(function (k) { out[k] = d.contact[k]; });
    Object.keys(c).forEach(function (k) { if (out[k] == null) out[k] = c[k]; });
    return out;
  }

  /** The contacts whose details the page needs: Next up's first person (city, last live talk) and
   *  everyone on a closed row (the done line's outcome, and the tray). */
  function wantedIds() {
    var p = parts();
    var ids = [];
    var add = function (id) { if (id != null && ids.indexOf(id) === -1) ids.push(id); };
    if (p.next && firstOf(p.next)) add(firstOf(p.next).id);
    p.done.concat(p.off).forEach(function (r) { (r.people || []).forEach(function (x) { add(x.id); }); });
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
    if (!p.rows.length || p.next || !p.fri.length || p.friDone === p.fri.length) return;
    S.nextWeek = null;
    var monday = nextMonday();
    if (!monday) return;
    BDApi.get(weekPath(monday)).then(function (r) {
      var w = r && r.week;
      S.nextWeek = w && rowsOf(w).length ? w : null;
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

  /** "Talked · Mon, Nov 2" for a done row: the newest call, voicemail, meeting or hosted event (or
   *  "Not the right person"; for a maintenance follow-up also "Emailed" or "Texted") with anyone on
   *  it since the week began, the person's name first when the row has more than one ("Sue Marlow:
   *  Voicemail · Mon, Nov 30"); "Done" when nothing was logged. Null while a timeline is still on
   *  its way. */
  function doneLine(r) {
    var ws = S.week.week_start;
    var people = r.people || [];
    var best = null;
    for (var j = 0; j < people.length; j++) {
      var d = S.details[people[j].id];
      if (!d) return null;
      var items = d.timeline || [];
      for (var i = 0; i < items.length; i++) {
        var x = items[i], word = null, at = x.at;
        if (BD.bizDateOf(x.at) < ws) break;
        if (x.type === "event" && x.event && x.event.action === "unconfirmed") word = "Not the right person";
        else if (x.type === "interaction" && x.interaction) {
          word = interactionWord(x.interaction, isMaint(r));
          at = x.interaction.occurred_at || x.at;
        }
        if (!word) continue;
        if (!best || String(at) > String(best.at)) best = { word: word, at: at, who: people[j] };
        break;
      }
    }
    if (!best) return "Done" + (r.done_at ? " · " + BD.fmtDay(r.done_at, S.today) : "");
    return (people.length > 1 ? best.who.name + ": " : "") + best.word + " · " + BD.fmtDay(best.at, S.today);
  }

  /** The company's misses (#828: voicemails and calls nobody answered, with anyone there, since the
   *  last live talk with anyone there): "Never reached after 2 tries", "2 tries since the last live
   *  talk"; "" with none. */
  function missesWords(r) {
    var n = Number(r && r.misses) || 0;
    if (!n) return "";
    return r.last_live_at ? plural(n, "try", "tries") + " since the last live talk" : "Never reached after " + plural(n, "try", "tries");
  }

  /** Where one person stands: their own last live talk and tries, then any promised call or next
   *  step, each a short line. */
  function personFacts(p) {
    var n = Number(p.attempts_since_live) || 0;
    var live = p.last_live_at ? "Last live talk " + BD.fmtDay(p.last_live_at, S.today) : "No live talk yet";
    var lines = [live + (n ? " · " + plural(n, "try", "tries") + (p.last_live_at ? " since" : "") : "")];
    var promisedIsStep = p.promised_date && p.promised_date === p.next_step_date;
    if (p.promised_date && !promisedIsStep) lines.push("Promised a call by " + BD.fmtDay(p.promised_date, S.today));
    if (p.next_step || p.next_step_date) {
      lines.push("Next step: " + [p.next_step || "Get in touch", p.next_step_date ? BD.fmtDay(p.next_step_date, S.today) : ""]
        .filter(Boolean).join(", ") + (promisedIsStep ? " (promised)" : ""));
    }
    return lines;
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
   *  missed call this week with no follow-up yet, one item per person on a closed row, soonest step
   *  first. */
  function trayItems() {
    if (!S.canSend || !S.week) return [];
    var ws = S.week.week_start;
    var seen = {}, items = [];
    rowsOf(S.week).forEach(function (r) {
      if (r.status === "open") return;
      (r.people || []).forEach(function (p) {
        var cid = p.id;
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
        items.push({ cid: cid, row: r, contact: d.contact || asContact(r, p), rec: rec, missed: missed, interaction: inter });
      });
    });
    items.sort(function (a, b) {
      var x = a.rec ? a.rec.due_date : "9999", y = b.rec ? b.rec.due_date : "9999";
      return x < y ? -1 : (x > y ? 1 : String(a.contact.name).localeCompare(String(b.contact.name)));
    });
    return items;
  }

  /** The tray has its data: the details of everyone on a closed row have landed. */
  function trayReady() {
    return rowsOf(S.week).every(function (r) {
      return r.status === "open" || (r.people || []).every(function (p) { return !!S.details[p.id]; });
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
        plural(p.maint.length, "maintenance account") + " still due.";
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
    var fri = fridayRows();
    var total = fri.length;
    var done = fri.filter(function (r) { return r.status === "done"; }).length;
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

    // Under the headline: the "Due now" companies still open. Absent at 0.
    var due = dueNow();
    var dueLine = due > 0
      ? '<p class="wk-due-line" id="wk-due-line">' + esc("Due now: " + plural(due, "maintenance account")) + "</p>" : "";
    var weekZone;
    if (!total) {
      weekZone = '<div class="wk-week"><p class="wk-zone-label hide-phone">This week</p>' +
        '<p class="wk-count" id="week-count">No list yet</p>' + dueLine + "</div>";
    } else {
      var news = fri.filter(function (r) { return r.kind === "new"; });
      var follows = fri.filter(function (r) { return r.kind !== "new"; });
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
          return '<span class="dot' + cls + '" data-dot-task="' + esc(t.id) + '" title="' + esc((t.company && t.company.name) + ", " + word) + '"></span>';
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
    // Said when it changes, not on every redraw (a redraw would also talk over the banner's words).
    var doneWords = done + " of " + total + " done";
    if (liveEl && total && doneWords !== S.doneSaid) { S.doneSaid = doneWords; liveEl.textContent = doneWords; }
  }

  // ── drawing: the maintenance banner ──────────────────────────────────────────────────────

  function dueWords(n) { return plural(n, "maintenance account") + " due this week"; }

  /** The id of the first due row on show, for Show. Next up is always the first open "Due now" row
   *  (parts()), so this is wk-next; wk-due-h is a fallback in case parts() ever stops putting due
   *  rows first. null when neither is drawn. */
  function dueTarget() {
    var p = parts();
    if (p.next && isMaint(p.next)) return "wk-next";
    return p.due.length ? "wk-due-h" : null;
  }

  function hideBanner() {
    if (!bannerEl) return;
    bannerEl.hidden = true;
    bannerEl.innerHTML = "";
  }

  /** The banner, from dueNow(): there while the count is above 0. A count different from the one
   *  last drawn for this list is said in #live (the list's first paint says nothing). */
  function renderBanner() {
    if (!bannerEl) return;
    var n = dueNow(), was = S.dueSaid;
    S.dueSaid = n;
    if (liveEl && was != null && was !== n) {
      liveEl.textContent = n > 0 ? dueWords(n) + "." : "No maintenance accounts due this week.";
    }
    // A redraw replaces Show: focus on it goes back to the new one, never to <body>. When Show goes,
    // the fallback waits for renderAll: picked now, it would be a node of the lists about to be
    // repainted (often Next up's Call on the very due row that has just closed).
    var hadFocus = bannerEl.contains(document.activeElement);
    if (!(n > 0)) { hideBanner(); if (hadFocus) S.bannerLostFocus = true; return; }
    var target = dueTarget();
    bannerEl.innerHTML = '<span class="wk-due-banner-ico">' + icon("bell", 20) + "</span>" +
      '<div class="wk-due-banner-text"><h2 class="wk-due-banner-title" id="wk-due-banner-h">' + esc(dueWords(n)) + "</h2>" +
      '<p class="wk-due-banner-sub">They stay on the list until you log a call, meeting, email or text.</p></div>' +
      (target ? '<button type="button" class="btn wk-due-banner-show" data-act="show-due" data-target="' + target +
        '" aria-describedby="wk-due-banner-h">Show</button>' : "");
    bannerEl.hidden = false;
    if (hadFocus) {
      var show = bannerEl.querySelector('[data-act="show-due"]');
      if (show) { try { show.focus({ preventScroll: true }); } catch (e) { show.focus(); } } else S.bannerLostFocus = true;
    }
  }

  /** Show: focus (and scroll to) the first due row. It changes no data. */
  function showDue() {
    var id = dueTarget();
    var n = id ? document.getElementById(id) : null;
    if (!n) return;                                 // focus stays on Show, never on <body>
    var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (n.scrollIntoView) n.scrollIntoView({ block: "start", behavior: calm ? "auto" : "smooth" });
    try { n.focus({ preventScroll: true }); } catch (e) { n.focus(); }
  }

  // ── drawing: the lists ───────────────────────────────────────────────────────────────────

  function moreBtnHTML(label, extraCls) {
    return '<button type="button" class="btn btn-icon wk-more' + (extraCls ? " " + extraCls : "") + '" data-act="more" aria-label="' +
      esc(label) + '" aria-haspopup="menu" aria-expanded="false">' + icon("more", 20) + "</button>";
  }

  function callBtnHTML(c) {
    var href = BD.telHref(c);
    if (!href) return '<span class="wk-nophone">No phone</span>';
    return '<a class="btn-call" href="' + esc(href) + '" data-act="call" aria-label="' + esc("Call " + c.name + ", " + phoneOf(c)) + '">' +
      icon("phone", 20) + "</a>";
  }

  function companyName(r) { return (r && r.company && r.company.name) || ""; }

  /** One person on a company row (opened, or under Next up): name (to their contact page), title
   *  and phone, their own last live talk and tries, any promised call or next step, and Call. */
  function personHTML(r, p, tasks) {
    var c = asContact(r, p, tasks);
    var href = contactHref(c);
    var sub = [c.title, phoneOf(c)].filter(Boolean).join(" · ");
    var flag = p.not_right_person ? BD.pill("warn", "Not the right person") :
      (p.confirmed === false ? BD.pill("warn", "Needs confirming") : "");
    var acts = S.canAct ? '<div class="wk-p-acts">' + callBtnHTML(c) + moreBtnHTML("More for " + c.name, "wk-p-more") + "</div>" : "";
    return '<div class="wk-person" role="listitem" data-person="' + esc(p.id) + '">' + BD.avatarHTML(c.name || "", "sm") +
      '<div class="wk-p-who">' + (href ? '<a class="wk-p-name" href="' + esc(href) + '">' + esc(c.name) + "</a>" :
        '<span class="wk-p-name">' + esc(c.name) + "</span>") +
      (sub ? '<span class="wk-p-sub">' + esc(sub) + "</span>" : "") + "</div>" +
      '<div class="wk-p-facts">' + personFacts(p).map(function (l) { return "<span>" + esc(l) + "</span>"; }).join("") +
      (flag ? '<span class="wk-p-flag">' + flag + "</span>" : "") + "</div>" + acts + "</div>";
  }

  /** An opened row: everyone on it, then the row's own buttons (a "Due now" row says what clears it). */
  function bodyHTML(r) {
    var foot = "";
    if (S.canAct && !isMaint(r) && isOpen(r)) {
      foot = '<div class="wk-co-foot"><button type="button" class="btn btn-sm" data-act="snooze">' + icon("clock", 16) + "Not this week</button>" +
        '<button type="button" class="btn btn-sm" data-act="done">' + icon("check", 16) + "Done, nothing to log</button></div>";
    } else if (isMaint(r) && isOpen(r)) {
      foot = '<p class="wk-co-note">Stays on your list until you log a call, meeting, email or text with each person due here.</p>';
    }
    return '<div class="wk-co-body" id="wk-p-' + esc(r.id) + '"' + (S.open[r.id] ? "" : " hidden") + ">" +
      '<div class="wk-people" role="list" aria-label="' + esc("People at " + companyName(r)) + '">' +
      (r.people || []).map(function (p) { return personHTML(r, p); }).join("") + "</div>" + foot + "</div>";
  }

  /** One company row (Due now, Rest of the 10, an extra 10, next week's preview). Closed: the
   *  company, the person to call first, the reason chip and the company's misses, with Call for that
   *  person; its toggle opens everyone there. A preview row has no toggle and no buttons. */
  function rowHTML(r, opts) {
    var o = opts || {};
    var first = firstOf(r) || {};
    var c = asContact(r, first, o.tasks);
    var maint = isMaint(r);
    var hook = o.preview ? ' data-preview-task="' + esc(r.id) + '"'
      : ' data-task="' + esc(r.id) + '" data-status="' + esc(r.status) + '" data-company="' + esc(r.company && r.company.id) + '"';
    var reason = reasonOf(r);
    // A pinned maintenance follow-up says "Maintenance · due" (the neutral "Maintenance" pill would repeat it,
    // but a warning or Key account pill still shows beside it).
    var status = BD.statusPill(c, r.reasons, maint);
    var pill = (maint ? BD.kindPill(r) : "") + status;
    var two = maint && status !== "";   // two pills: the middle column gives the pill cell more room
    // Admin acts AND picks: the manager's "Priority N" caption goes under the pill.
    if (!o.preview && S.canAct && S.canPick && r.score != null && !maint) pill += '<span class="wk-score">' + esc("Priority " + r.score) + "</span>";
    var acts;
    // No phone number: More stays on a phone too, where it takes the call column (bd.css
    // .wk-row-nophone), or a phone user could not take the row off, mark it done or flag the person.
    var noPhone = !o.preview && S.canAct && !BD.telHref(c);
    if (o.preview) {
      acts = '<span class="wk-row-meta">' + esc(phoneOf(c)) + "</span>";
    } else if (S.canAct) {
      acts = '<span class="wk-row-call">' + callBtnHTML(c) + "</span>" +
        moreBtnHTML("More for " + companyName(r), (noPhone ? "" : "hide-phone ") + "wk-row-more");
    } else {
      acts = '<span class="wk-row-meta"><span>' + esc(phoneOf(c)) + "</span>" +
        (S.canPick && r.score != null && !maint ? '<span class="wk-score">' + esc("Priority " + r.score) + "</span>" : "") + "</span>";
    }
    var n = (r.people || []).length;
    var firstLine = [first.name, first.title].filter(Boolean).join(" · ") + (n > 1 ? " · +" + (n - 1) + " more" : "");
    var misses = missesWords(r);
    var main = BD.coIconHTML() +
      '<span class="wk-co-main"><span class="wk-co-name bd-co-name">' + esc(companyName(r)) + "</span>" +
      '<span class="wk-co-first">' + esc(firstLine) + "</span>" +
      (misses ? '<span class="wk-co-misses">' + esc(misses) + "</span>" : "") + "</span>";
    var opened = !o.preview && !!S.open[r.id];
    var toggle = o.preview ? '<span class="wk-co-toggle is-static">' + main + "</span>"
      : '<button type="button" class="wk-co-toggle" data-act="toggle" id="wk-t-' + esc(r.id) + '" aria-expanded="' + opened +
        '" aria-controls="wk-p-' + esc(r.id) + '">' + main + BD.coChevHTML() + "</button>";
    return '<li class="list-row wk-row wk-co' + (opened ? " is-open" : "") + (two ? " wk-row-two" : "") + (noPhone ? " wk-row-nophone" : "") +
      (S.canAct && !o.preview ? "" : " is-readonly") + '"' + hook + ">" +
      '<div class="wk-co-head">' + toggle +
      '<span class="wk-reason">' + reasonHTML(reason) + "</span>" +
      '<span class="wk-pill">' + pill + "</span>" + acts + "</div>" +
      (o.preview ? "" : bodyHTML(r)) + "</li>";
  }

  function nextHTML(r) {
    var c = contactFor(r);
    var first = firstOf(r) || {};
    var d = S.details[c.id];
    var reason = reasonOf(r);
    var kind = BD.kindPill(r);
    var maint = isMaint(r);
    var metaWide = [c.title, companyName(r), c.city].filter(Boolean).join(" · ");
    var acts = "";
    if (S.canAct) {
      var href = BD.telHref(c);
      acts = '<div class="wk-next-acts">' +
        (href
          ? '<a class="btn btn-primary wk-call" href="' + esc(href) + '" data-act="call">' + icon("phone", 18) + esc("Call " + phoneOf(c)) + "</a>"
          : '<button type="button" class="btn" disabled>No phone number</button>') +
        // A pinned maintenance follow-up cannot be taken off by hand: no "Not this week".
        (maint ? "" : '<button type="button" class="btn hide-phone" data-act="snooze">' + icon("clock", 18) + "Not this week</button>") +
        moreBtnHTML("More for " + c.name, "wk-next-more") + "</div>" +
        (maint ? '<p class="wk-next-stays">Stays on your list until you log a call, meeting, email or text.</p>' : "") +
        (S.canPick && r.score != null && !maint ? '<p class="wk-score wk-next-score">' + esc("Priority " + r.score) + "</p>" : "");
    } else {
      acts = '<p class="wk-next-phone">' + esc([phoneOf(c), S.canPick && r.score != null && !maint ? "Priority " + r.score : ""].filter(Boolean).join(" · ")) + "</p>";
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
    // The company's misses, and the person's promised call or next step (their last live talk is beside).
    var more = [missesWords(r)].concat(personFacts(first).slice(1)).filter(Boolean);
    var others = (r.people || []).slice(1);
    var also = others.length
      ? '<div class="wk-next-also"><p class="wk-next-label2" id="wk-next-also-h">' + esc("Also at " + companyName(r)) + "</p>" +
        '<div class="wk-people" role="list" aria-labelledby="wk-next-also-h">' +
        others.map(function (p) { return personHTML(r, p); }).join("") + "</div></div>" : "";
    // tabindex -1: the banner's Show can move focus here (and a redraw puts it back by its id).
    return '<section class="wk-next-sec" id="wk-next" tabindex="-1" aria-labelledby="wk-next-name">' +
      '<article class="card wk-next" data-task="' + esc(r.id) + '" data-status="open" data-company="' + esc(r.company && r.company.id) + '">' +
      '<div class="wk-next-main">' +
      '<div class="wk-next-top"><p class="wk-next-label">Next up</p><span class="wk-next-kind-top">' + kind + "</span></div>" +
      '<div class="wk-next-who">' + BD.avatarHTML(c.name || "", "lg") +
      '<div class="wk-next-id"><div class="wk-next-namerow"><h2 class="wk-next-name" id="wk-next-name">' +
      (contactHref(c) ? '<a href="' + esc(contactHref(c)) + '">' + esc(c.name) + "</a>" : esc(c.name)) + "</h2>" +
      '<span class="wk-next-kind">' + kind + "</span></div>" +
      '<p class="wk-next-meta wk-meta-wide">' + esc(metaWide) + "</p>" +
      '<p class="wk-next-meta wk-meta-narrow"><span>' + esc(companyName(r)) + "</span>" +
      (c.title ? "<span>" + esc(c.title) + "</span>" : "") + "</p></div></div>" +
      (reason ? '<p class="wk-next-reason">' + icon("calendar", 18) + "<span>" + esc(reason) + "</span></p>" : "") +
      '<p class="wk-next-line">' + line + "</p>" +
      more.map(function (l) { return '<p class="wk-next-fact">' + esc(l) + "</p>"; }).join("") +
      acts + "</div>" +
      '<div class="wk-next-side"><p class="wk-next-label2">Last live talk</p>' + side +
      (contactHref(c) ? '<a class="btn-link wk-next-open" href="' + esc(contactHref(c)) + '">' + esc("Open " + c.name) + icon("arrow-right", 16) + "</a>" : "") +
      "</div>" + also +
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

  /** "Due now": the other open maintenance companies, from any batch of the week, above the 10. */
  function dueHTML(p) {
    if (!p.due.length) return "";
    return '<section class="section wk-due" id="wk-due" aria-labelledby="wk-due-h">' +
      '<div class="section-head"><h2 class="section-title" id="wk-due-h" tabindex="-1">Due now</h2>' +
      '<span class="section-meta">' + esc(p.due.length + " to go") + "</span></div>" +
      '<div class="card card-flush"><ul class="list wk-list wk-due-list">' + p.due.map(function (r) { return rowHTML(r); }).join("") + "</ul></div></section>";
  }

  function restHTML(p) {
    if (!p.rest.length) return "";
    return '<section class="section wk-rest" id="wk-rest" aria-labelledby="wk-rest-h">' +
      '<div class="section-head"><h2 class="section-title" id="wk-rest-h">' + (own() ? "Rest of your 10" : "Rest of the 10") + "</h2>" +
      '<span class="section-meta">' + esc(p.rest.length + " to go") + "</span></div>" +
      '<div class="card card-flush"><ul class="list wk-list">' + p.rest.map(function (r) { return rowHTML(r); }).join("") + "</ul></div></section>";
  }

  function extrasHTML(p) {
    var list = p.extras;
    return list.map(function (b, i) {
      var mine = p.rows.filter(function (r) { return r.batch_id === b.id && r.section === "more"; });
      var d = mine.filter(function (r) { return r.status === "done"; }).length;
      var open = mine.filter(function (r) { return isOpen(r) && r !== p.next; });
      var title = mine.length + " more (to get ahead)" + (list.length > 1 ? " (" + (i + 1) + ")" : "");
      return '<section class="section wk-extra" data-batch="' + esc(b.id) + '" aria-labelledby="wk-g' + esc(b.id) + '">' +
        '<div class="section-head"><h2 class="section-title" id="wk-g' + esc(b.id) + '" tabindex="-1">' + esc(title) + "</h2>" +
        '<span class="section-meta">' + esc(d + " of " + mine.length + " extra done") + "</span></div>" +
        (open.length ? '<div class="card card-flush"><ul class="list wk-list">' + open.map(function (r) { return rowHTML(r); }).join("") + "</ul></div>" : "") +
        "</section>";
    }).join("");
  }

  function trayBannerHTML() {
    if (!S.canSend || !S.week || !rowsOf(S.week).length) return "";
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

  /** A closed row's company and its people, each name a link to their contact page. */
  function coWhoHTML(r) {
    var ps = r.people || [];
    var names = ps.slice(0, 2).map(function (p) {
      var href = contactHref(p);
      return href ? '<a href="' + esc(href) + '">' + esc(p.name) + "</a>" : esc(p.name);
    }).join(", ") + (ps.length > 2 ? esc(" +" + (ps.length - 2) + " more") : "");
    return '<span class="who wk-who"><span class="who-name">' + esc(companyName(r)) + "</span>" +
      '<span class="who-sub">' + names + "</span></span>";
  }

  function doneRowHTML(r) {
    var line = doneLine(r);
    // No Undo on a done maintenance follow-up: reopening it would leave a pin nobody can clear.
    var undo = S.canAct && !isMaint(r) && BD.bizDateOf(r.done_at) === S.today
      ? '<button type="button" class="btn-link wk-undo" data-act="reopen" aria-label="' + esc("Undo for " + companyName(r)) + '">Undo</button>' : "";
    return '<li class="list-row wk-row wk-done-row is-done" data-task="' + esc(r.id) + '" data-status="done">' +
      BD.avatarHTML(companyName(r), "", "done") +
      coWhoHTML(r) +
      '<span class="wk-outcome">' + (line == null ? '<span class="skeleton wk-skel-short"></span>' : esc(line)) + "</span>" + undo + "</li>";
  }

  function offRowHTML(r) {
    var undo = S.canAct && S.offNow[r.id]
      ? '<button type="button" class="btn-link wk-undo" data-act="reopen" aria-label="' + esc("Undo for " + companyName(r)) + '">Undo</button>' : "";
    return '<li class="list-row wk-row wk-done-row is-off" data-task="' + esc(r.id) + '" data-status="snoozed">' +
      BD.avatarHTML(companyName(r), "", "off") +
      coWhoHTML(r) +
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
        (S.showNames ? '<ul class="wk-names">' + notReached.map(function (r) {
          return '<li data-task="' + esc(r.id) + '" data-status="snoozed">' + esc(companyName(r)) + "</li>";
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
    var tasks = {};
    (nw.tasks || []).forEach(function (t) { tasks[t.id] = t; });
    return '<section class="section wk-preview" id="wk-preview" aria-labelledby="wk-preview-h">' +
      '<div class="section-head"><h2 class="section-title" id="wk-preview-h" tabindex="-1">Next week\'s 10</h2>' +
      '<span class="section-meta">Calls open on Monday.</span></div>' +
      '<div class="card card-flush"><ul class="list wk-list">' + rowsOf(nw).map(function (r) { return rowHTML(r, { preview: true, tasks: tasks }); }).join("") +
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
   *  (a row's button by its row and person, or an id). */
  function focusKey() {
    var a = document.activeElement;
    if (!a || !main.contains(a) || a === main) return null;
    var host = a.closest("[data-task]"), act = a.getAttribute("data-act"), who = a.closest("[data-person]");
    if (host && act) {
      return '[data-task="' + host.getAttribute("data-task") + '"] ' +
        (who ? '[data-person="' + who.getAttribute("data-person") + '"] ' : "") + '[data-act="' + act + '"]';
    }
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
    var show = S.canSend && rowsOf(S.week).length > 0;
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
    renderBanner();
    renderMain();
    renderTray();
    if (S.bannerLostFocus) {
      S.bannerLostFocus = false;
      var a = document.activeElement;
      if (!a || a === document.body || !document.contains(a)) focusShown([]);
    }
    maybeNextWeek();
  }

  // ── actions ──────────────────────────────────────────────────────────────────────────────

  /** What a task button answered (the row's first task: done, snooze and reopen act on the whole
   *  row), on the row. */
  function applyRow(r, x) {
    if (!r || !x) return;
    if (x.status) r.status = x.status;
    if ("done_at" in x) r.done_at = x.done_at;
    if ("snoozed_until" in x) r.snoozed_until = x.snoozed_until;
    // "Due now" follows the change at once (the next refresh brings the server's own number).
    if (S.week && typeof S.week.due_count === "number" && isMaint(r)) {
      S.week.due_count = rowsOf(S.week).filter(function (y) { return isMaint(y) && isOpen(y); }).length;
    }
  }

  function rowOf(el) {
    var host = el && el.closest ? el.closest("[data-task]") : null;
    return host ? S.byId[Number(host.getAttribute("data-task"))] || null : null;
  }

  function idsOf(r) { return (r.people || []).map(function (p) { return p.id; }); }

  function focusLater(sel) {
    var n = sel ? $(sel) : null;
    if (n) { try { n.focus({ preventScroll: true }); } catch (e) { n.focus(); } }
  }

  /** Open or close a row in place: the same toggle keeps focus and says open or closed
   *  (aria-expanded), and the people are shown or hidden. */
  function toggleRow(btn) {
    var r = rowOf(btn);
    if (!r) return;
    var on = !S.open[r.id];
    if (on) S.open[r.id] = true; else delete S.open[r.id];
    btn.setAttribute("aria-expanded", String(on));
    var li = btn.closest("[data-task]");
    if (li) li.classList.toggle("is-open", on);
    var body = document.getElementById("wk-p-" + r.id);
    if (body) body.hidden = !on;
  }

  /** Open the after-a-call sheet for a person on a row: "call" (from a Call link), "meeting" or
   *  "nrp". It logs on THAT person; the row's task goes with it (not the right person names them). */
  function openCall(r, p, mode) {
    if (!S.canAct || !window.BDCall || !p) return;
    var c = p === firstOf(r) ? contactFor(r) : asContact(r, p);
    var t = S.taskById[r.id] || { id: r.id };
    if (mode === "call") BD.store.set(CALL_KEY, { contact_id: c.id, task_id: r.id, at: Date.now() }, { session: true });
    window.BDCall.open({
      contact: c, task: t, mode: mode, startedAt: mode === "call" ? BD.bizNowISO() : null,
      aiEnabled: S.ai, canSend: S.canSend,
      returnFocus: function () { return callFocusTarget(r); },
      onChange: function (ev) { onCallChange(r, c, ev); },
    });
  }

  /** The first of `sels` that is on show (a hidden Undo in the closed Done section on a phone is
   *  not), else the next thing on show: Next up's Call, any Call, the Done toggle, the heading. */
  function shownTarget(sels) {
    var shown = function (sel) {
      return Array.prototype.filter.call(document.querySelectorAll(sel), function (n) { return n.getClientRects().length > 0; })[0] || null;
    };
    var all = sels.concat(['#wk-next [data-act="call"]', '#lists [data-act="call"]', ".wk-done-toggle"]);
    for (var i = 0; i < all.length; i++) {
      var n = shown(all[i]);
      if (n) return n;
    }
    return $("main h1");
  }

  /** Focus the first of `sels` on show (shownTarget), so focus never drops to <body> after a redraw. */
  function focusShown(sels) {
    var n = shownTarget(sels);
    if (!n) return;
    if (n.tagName === "H1" && !n.hasAttribute("tabindex")) n.setAttribute("tabindex", "-1");
    try { n.focus({ preventScroll: true }); } catch (e) { n.focus(); }
  }

  /** Where focus goes when the call sheet closes after a save redrew the row it was opened from:
   *  the row's Undo, else its Call, else shownTarget's next thing on show. */
  function callFocusTarget(r) {
    return shownTarget(['[data-task="' + r.id + '"] [data-act="reopen"]', '[data-task="' + r.id + '"] [data-act="call"]']);
  }

  function onCallChange(r, c, ev) {
    BD.store.del(CALL_KEY, { session: true });
    var res = ev && ev.result;
    if (!res) return;                                 // closed with nothing sent: nothing changed
    // A logged call closes a business-development row whole; on a "Due now" row with someone else
    // still due it closes only that person's follow-up, so the refresh says what the row is now.
    if (res.task && S.byId[res.task.id] === r && (!isMaint(r) || (r.task_ids || []).length < 2)) applyRow(r, res.task);
    refreshAll([c.id]).then(function () {
      // The redraw replaced the focused element: put focus back on the row, not on <body>.
      var a = document.activeElement;
      if (window.BDCall.isOpen() || (a && a !== document.body && document.contains(a))) return;
      var n = callFocusTarget(r);
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
    var r = S.byId[rec.task_id];
    var p = r ? (r.people || []).filter(function (x) { return x.id === rec.contact_id; })[0] : null;
    if (!r || !p || r.status !== "open" || !(Date.now() - Number(rec.at) < CALL_KEEP_MS)) {
      BD.store.del(CALL_KEY, { session: true });
      return;
    }
    openCall(r, p, "call");
  }

  function doDone(r, btn) {
    run(btn, function () { return BDApi.post(BDApi.path("tasks", r.id, "done")); }).then(function (res) {
      if (!res) return;
      applyRow(r, res.task);
      renderAll();
      focusShown(['[data-task="' + r.id + '"] [data-act="reopen"]']);
      toast("Done. Nothing logged.", { action: { label: "Undo", onClick: function () { doReopen(r, null); } } });
      refreshAll(idsOf(r));
    });
  }

  function doSnooze(r, btn) {
    run(btn, function () { return BDApi.post(BDApi.path("tasks", r.id, "snooze"), {}); }).then(function (res) {
      if (!res) return;
      applyRow(r, res.task);
      S.offNow[r.id] = true;
      renderAll();
      focusShown([]);                               // Next up's Call, else the next thing on show
      toast("Taken off this week.", { action: { label: "Undo", onClick: function () { doReopen(r, null); } } });
      refreshAll(idsOf(r));
    });
  }

  function doReopen(r, btn) {
    run(btn, function () { return BDApi.post(BDApi.path("tasks", r.id, "reopen")); }).then(function (res) {
      if (!res) return;
      applyRow(r, res.task);
      delete S.offNow[r.id];
      renderAll();
      focusShown(['[data-task="' + r.id + '"] [data-act="call"]', '[data-task="' + r.id + '"] [data-act="toggle"]']);
      BD.announce(companyName(r) + " is back on the list.");
      refreshAll([]);
    });
  }

  function tenMore(btn) {
    var w = S.week;
    var body = w.owner && w.owner.id != null ? { owner: w.owner.id } : {};
    var before = rowsOf(w).length;
    if (btn.classList.contains("is-busy")) return;
    btn.classList.add("is-busy"); btn.setAttribute("aria-busy", "true");
    BDApi.post("/api/bd/week/ten-more", body).then(function (r) {
      S.moreMsg = "";
      setWeek(r.week);
      S.nextWeek = undefined;
      renderAll();
      var added = rowsOf(r.week).length - before;
      toast(added > 0 ? plural(added, "more company", "more companies") + " added below." : "Nothing new to add.", { kind: "ok" });
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
          contact: it.contact, task: S.taskById[it.row.id] || { id: it.row.id }, mode: "decide", recommendation: it.rec, missed: it.missed,
          interaction: it.interaction, aiEnabled: S.ai, canSend: S.canSend,
          onChange: function () { afterTrayChange(it.cid); },
        });
      },
    });
  }

  /** The More menu. A row's (or Next up's): Not this week and Done, nothing to log for the whole
   *  row, and the person to call first's own choices (named when the row has more than one person).
   *  A person's, inside an opened row: their own choices only. */
  function menuItems(r, where, p) {
    var items = [];
    var maint = isMaint(r);     // a pinned follow-up cannot be taken off by hand (the server says 409)
    var who = where === "person" ? p : firstOf(r);
    var named = where !== "person" && (r.people || []).length > 1 ? BD.firstName(who) : "";
    if (where !== "person" && !maint && (where === "row" || isPhone())) items.push({ act: "snooze", label: "Not this week", icon: "clock" });
    if (who) {
      items.push({ act: "log-meeting", label: named ? "Log a meeting with " + named : "Log a meeting", icon: "users" });
      if (!who.not_right_person) items.push({ act: "nrp", label: named ? named + " is not the right person" : "Not the right person", icon: "user-x" });
    }
    if (where !== "person" && !maint) items.push({ act: "done", label: "Done, nothing to log", icon: "check" });
    if (who && contactHref(who)) {
      items.push({ act: "open", label: named ? "Open " + named + "'s contact" : "Open contact", icon: "arrow-right", href: contactHref(who) });
    }
    return items;
  }

  // ── events (one set, on the page) ────────────────────────────────────────────────────────

  main.addEventListener("click", function (e) {
    var target = e.target;
    if (!target.closest) return;
    if (target.closest("[data-call-root]") || target.closest(".menu")) return;   // BDCall's own, and the menu's
    var btn = target.closest("[data-act]");
    if (!btn || !main.contains(btn)) {
      // A click anywhere else on a row's head (its reason, its pills) opens or closes it too.
      var head = target.closest(".wk-co-head");
      var tg = head && !target.closest("a, button") ? head.querySelector('[data-act="toggle"]') : null;
      if (tg) toggleRow(tg);
      return;
    }
    var act = btn.getAttribute("data-act");
    var r = rowOf(btn);

    if (act === "toggle") return toggleRow(btn);
    if (act === "show-due") return showDue();         // focus only: every viewer of a list has it
    if (act === "call") { if (r) openCall(r, personOf(btn, r), "call"); return; }   // a real tel: link: no preventDefault
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
    if (!r || !S.canAct) return;
    if (act === "more") {
      var inPerson = btn.closest("[data-person]");
      BD.menu(btn, menuItems(r, inPerson ? "person" : (btn.closest("#wk-next") ? "next" : "row"), personOf(btn, r)));
      return;
    }
    if (act === "snooze") return doSnooze(r, btn);
    if (act === "done") return doDone(r, btn);
    if (act === "reopen") return doReopen(r, btn);
  });

  // The menu's choices, from BD.menu (dispatched on its anchor: a row, Next up, or a person in one).
  // Heard on the document: when a background refresh redrew the anchor away while the menu was open,
  // BD.menu sends the choice there, and the old anchor still names its row and person.
  document.addEventListener("bd-menu", function (e) {
    var d = e.detail || {};
    var r = rowOf(d.anchor);
    if (!r || !S.canAct) return;
    if (d.act === "snooze") doSnooze(r, null);
    else if (d.act === "done") doDone(r, null);
    else if (d.act === "log-meeting") openCall(r, personOf(d.anchor, r), "meeting");
    else if (d.act === "nrp") openCall(r, personOf(d.anchor, r), "nrp");
  });

  // Hovering or focusing a company's row rings its dot in the tracker.
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
    hideBanner();
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
    hideBanner();
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
    hideBanner();                     // the list being loaded draws its own
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
      S.dueSaid = null; S.doneSaid = null;   // another list: its first paint is not a change
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
    hideBanner();
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
