/* One BD contact, /bd/contact.html?id= (optional &from=week) (#808: BD's js/contact.js, moved in as it
 * works today, restyled like the proposal tool by the approved BD mock-up).
 *
 * The redesign (the apply plan, section 2.3; the Contact artboard): a big avatar header with the
 * Log menu and the Email / Text links, then two columns. Main: the "Next step" card (the confirmed
 * step with Call / Change / Clear, a pending suggestion with Confirm / Change / Dismiss, the
 * missed-call follow-up, or "No next step yet." with the rule-based "Suggest one"), then History
 * (a note composer and the timeline with icons and "Live talk" pills). Side: This year, Follow-up
 * cadence, Details (one "Edit details" drawer), Others at the company, Archive. On a phone: one
 * column, Details folded, and a sticky bar with Call and Log.
 *
 * Every call entry point opens the one call sheet (bd-call.js, window.BDCall, This Week's). The
 * suggestion panel, the step editor and the follow-up block are BDCall.decide / stepEditor / followup,
 * each drawn into a fresh host inside the card; BDCall toasts what it saved and this page re-reads the
 * contact on every onChange.
 *
 * WHAT CHANGED IN THE MOVE:
 *   - BD's own shell (BDAuth) is gone. The page starts once the tool's shell settles (TWAuth.ready,
 *     which never settles on a page the tool refused, so its refusal card stays) and reads who this is
 *     from TWAuth.bdMe(), the one /api/bd/me answer the sidebar's BD group reads too. A failed answer
 *     is said in TWAuth.bdFailure's words, and the page shows no data.
 *   - WHAT A PERSON MAY DO COMES FROM can (bd/auth.py can()), never from a role name: send (log a
 *     call, meeting or email; Change and Clear the step), edit_contact (Edit details, a note, confirm,
 *     archive, "Not the right person"), clear_duplicate, add_contact ("Add someone"), cadence (how
 *     often to follow up; a person with cadence and no edit_contact, the manager, gets only that
 *     sheet) and manage_entries (delete any logged entry, or fix one somebody else logged).
 *   - EDIT AND DELETE AN ENTRY. BD's routes let the person who logged an entry change it and a BD
 *     admin change or delete any, but BD's page had no way to. Each logged entry in History now has
 *     Edit (its words) for the person who logged it and for manage_entries, and Delete for
 *     manage_entries.
 *   - NO LINKS TO PAGES THAT HAVE NOT MOVED. The company name is plain text, and Back goes only to
 *     This Week (from=week): there is no Contacts link until the Contacts page moves. Another
 *     contact and Add contact are /bd/ pages, written through BD.safeHref.
 *   - BD's phone name bar was its own top bar and is gone: the tool's top bar is the only one.
 *     Toasts are BD.toast's; every route is under /api/bd/.
 *
 * Counting rule (api-contract.md): only a live call, a meeting or a hosted event counts. Emails and
 * texts are logged as "Not a live talk". AI and the usual rule only suggest; a person confirms.
 *
 * After every change the page re-reads the contact and its timeline, so what is on screen is what
 * the server holds. Today is /api/bd/me's today (the server's Central date), never the PC clock.
 *
 * Routes (all in docs/bd/api-contract.md): GET /api/bd/contacts/{id} and its /interactions,
 * PATCH /api/bd/contacts/{id}, POST /api/bd/contacts/{id}/confirm | archive | interactions,
 * PATCH | DELETE /api/bd/interactions/{id}, POST /api/bd/tasks/{id}/snooze | reopen,
 * GET /api/bd/companies (the Edit details company list), GET /api/bd/companies/{id} (Others),
 * GET /api/bd/users, GET /api/bd/settings; the call sheet's own (bd-call.js).
 */
(function () {
  "use strict";

  var BD = window.BD, Api = window.BDApi;
  var esc = BD.esc;
  var TIMELINE_STEP = 20;
  var WIDE = "(min-width: 768px)";

  var FALLBACK = {
    lead_sources: ["Current Account", "DSBC Sales", "Website Lead", "Other/Misc"],
    industries: ["Manufacturing", "Other", "Food Processing", "GC", "Life Science", "Restaurant", "Education", "Warehouse", "Retail", "Healthcare"],
    stages: ["Meeting Set", "Met", "Proposal", "Won"],
    account_types: ["Utility", "Manufacturing", "Pharma", "GC"],
  };
  var IMPORTANCE = [[1, "Normal"], [2, "Important"], [3, "Key account"]];
  /** The value an owner select uses for a workbook person with no login yet (id null). */
  var KEEP = "keep";

  var S = {
    me: null, role: "", today: "", settings: null, users: null, companies: null,
    id: "", c: null, task: null, rec: null, missed: null, items: [], others: null,
    shown: TIMELINE_STEP, stepEdit: false, suggest: false, composing: false, asking: null,
    // From /api/bd/me's can (bd/auth.py can()), never worked out from a role name.
    canSend: false, canEdit: false, canNote: false, canNrp: false,
    canClearDup: false, canAdd: false, canFreq: false,
    cadenceOnly: false,   // cadence and not edit_contact (the manager): only the cadence sheet
    seeScore: false,      // pick_owner and not edit_contact (the manager): the week's priority score
    canManage: false,     // manage_entries: delete any logged entry, or fix one somebody else logged
    canWeek: false,       // week: Back to This Week
    editing: null,        // the id of the logged entry being edited in History, or null
  };
  var root;

  function $(id) { return document.getElementById(id); }
  function ico(name, size) { return BD.icon(name, size || 18); }
  function first() { return BD.firstName(S.c && S.c.name) || "them"; }
  function setting(key) {
    var s = S.settings || {};
    return s[key] && s[key].length ? s[key] : FALLBACK[key];
  }
  function archived() { return !!(S.c && S.c.archived_at); }
  function taskOpen() { return !!(S.task && S.task.status === "open"); }
  function wide() { return !!(window.matchMedia && window.matchMedia(WIDE).matches); }
  function fromWeek() { return BD.qs("from") === "week"; }
  // This Week, for a person who came from it. There is no Contacts link until that page moves.
  function back() { return fromWeek() && S.canWeek ? { href: "/bd/", label: "This Week" } : null; }
  /** A /bd/ page's address ending in one id ("/bd/contact.html?id=" and 21), through BD.safeHref. */
  function bdHref(start, id) { return BD.safeHref(start + encodeURIComponent(id)); }

  /** "6 min" (whole minutes from a minute up), "40 s" under a minute, "" for none. */
  function minutes(s) {
    var n = Number(s);
    if (!(n > 0)) return "";
    return n < 60 ? Math.round(n) + " s" : Math.round(n / 60) + " min";
  }
  /** "Today", or "Tue, Sep 15" ("Mon, Jan 11, 2027" in another year). */
  function dayWord(at) {
    var day = BD.bizDateOf(at);
    if (!day) return "";
    return day === S.today ? "Today" : BD.fmtDay(day, S.today);
  }

  function focusOn() {
    for (var i = 0; i < arguments.length; i++) {
      var el = typeof arguments[i] === "string" ? root.querySelector(arguments[i]) : arguments[i];
      if (!el || el.disabled) continue;
      if (!el.matches("a[href], button, input, select, textarea, [tabindex]")) el.setAttribute("tabindex", "-1");
      try { el.focus({ preventScroll: false }); } catch (e) { el.focus(); }
      return;
    }
  }
  function setBusy(btn, on) {
    if (!btn) return;
    btn.disabled = on;
    btn.classList.toggle("is-busy", on);
    if (on) btn.setAttribute("aria-busy", "true"); else btn.removeAttribute("aria-busy");
  }
  function errText(e) {
    var f = e && e.fields;
    if (f) { var k = Object.keys(f)[0]; if (k && f[k]) return f[k]; }
    return (e && e.message) || "Something went wrong.";
  }
  function fail(e) { BD.toast(errText(e), { kind: "error" }); }

  // ── loading ────────────────────────────────────────────────────────────────────────────────
  function fetchContact() {
    return Promise.all([
      Api.get(Api.path("contacts", S.id)),
      Api.get(Api.path("contacts", S.id, "interactions")),
    ]).then(function (r) {
      var d = r[0];
      S.c = d.contact;
      S.task = d.open_task || null;
      S.rec = d.pending_recommendation || null;
      S.missed = d.missed_call || null;
      S.items = r[1].items || [];
    });
  }

  function reload() {
    S.stepEdit = false;
    S.suggest = false;
    S.editing = null;
    return fetchContact().then(render);
  }

  function fetchAll(path) {
    var out = [];
    function next() {
      return Api.get(path + (path.indexOf("?") === -1 ? "?" : "&") + "limit=500&offset=" + out.length).then(function (r) {
        var items = r.items || [];
        out = out.concat(items);
        return (items.length && out.length < (r.total || 0)) ? next() : out;
      });
    }
    return next();
  }

  /** The others at this contact's company (optional: a failure just says so). */
  function loadOthers() {
    var co = S.c && S.c.company;
    if (!co || co.id == null) { S.others = []; return Promise.resolve(); }
    return Api.get(Api.path("companies", co.id)).then(function (r) {
      S.others = (r.contacts || []).filter(function (x) { return String(x.id) !== String(S.c.id); });
    }, function () { S.others = "failed"; });
  }

  // ── header ─────────────────────────────────────────────────────────────────────────────────
  function backHtml() {
    var b = back();
    if (!b) return "";
    return '<a class="back-link cd-back" href="' + esc(b.href) + '">' + ico("arrow-left", 18) + esc(b.label) + "</a>";
  }

  function pillsHtml(c) {
    var out = "";
    var t = S.task;
    if (t && !c.archived_at) {
      if (t.status === "open") out += BD.kindPill(t) + '<span class="pill pill-info">On this week\'s list</span>';
      else if (t.status === "done") out += '<span class="pill pill-ok">' + ico("check", 14) + "Done this week</span>";
    }
    // "Maintenance · due" already says it: only the neutral "Maintenance" status pill is dropped (it would
    // repeat it); a warning or Key account pill still shows.
    var pinned = t && t.status === "open" && t.kind === "maintenance" && !c.archived_at;
    out += BD.statusPill(c, t && t.reasons, !!pinned);
    return out;
  }

  function subHtml(c) {
    // Plain text until the Contacts page (where a company opens) has moved.
    var company = c.company ? '<span class="cd-company">' + esc(c.company.name) + "</span>" : "";
    var who = c.title ? esc(c.title) + (company ? " at " + company : "") : company;
    var parts = [];
    if (who) parts.push(who);
    if (c.city) parts.push(esc(c.city));
    return parts.join(" · ") || "No title or company yet";
  }

  /** The Log menu's items, filtered by role (the plan's role matrix). */
  function logItems() {
    var out = [];
    if (archived()) return S.canNote ? [{ act: "log-note", label: "Add a note", icon: "file" }] : [];
    if (S.canSend) {
      out.push({ act: "log-call", label: "Log a call", icon: "phone" });
      out.push({ act: "log-meeting", label: "Log a meeting", icon: "users" });
      out.push({ act: "log-hosted", label: "Log a hosted event", icon: "flag" });
    }
    if (S.canNote) out.push({ act: "log-note", label: "Add a note", icon: "file" });
    // A due maintenance follow-up cannot be taken off by hand (the server says 409).
    if (S.canSend && taskOpen() && S.task.kind !== "maintenance") out.push({ act: "snooze", label: "Not this week", icon: "clock" });
    if (S.canNrp) out.push({ act: "nrp", label: "Not the right person", icon: "user-x" });
    return out;
  }

  function logButton(extra) {
    return '<button type="button" class="btn cd-log' + (extra || "") + '" data-act="log-menu" aria-label="Log for ' + esc(S.c.name) + '">' +
      ico("pencil", 18) + "<span>Log</span>" + ico("chev-down", 16) + "</button>";
  }

  function headHtml(c) {
    var score = S.seeScore && S.task && S.task.score != null && S.task.kind !== "maintenance" && !c.archived_at
      ? '<p class="cd-score">Priority ' + esc(S.task.score) + " this week</p>" : "";
    var actions = "";
    if (logItems().length) actions += logButton(" hide-phone");
    if (c.email) {
      actions += '<a class="btn btn-icon cd-iconbtn" data-act="mail-out" href="mailto:' + esc(c.email) + '" aria-label="Email ' + esc(c.name) + '">' + ico("mail", 20) + "</a>";
    }
    var sms = BD.telHref(c).replace(/^tel:/, "");
    if (sms) {
      actions += '<a class="btn btn-icon cd-iconbtn" data-act="sms-out" href="sms:' + esc(sms) + '" aria-label="Text ' + esc(c.name) + '">' + ico("message", 20) + "</a>";
    }
    return '<header class="cd-head">' +
      '<div class="cd-who">' + BD.avatarHTML(c.name, "xl") +
      '<div class="cd-id"><div class="cd-name-row"><h1 class="page-title cd-name" id="cd-title" tabindex="-1">' + esc(c.name) + "</h1>" +
      pillsHtml(c) + "</div>" +
      '<p class="cd-sub">' + subHtml(c) + "</p>" + score + "</div></div>" +
      (actions ? '<div class="cd-head-actions">' + actions + "</div>" : "") +
      "</header>";
  }

  /** "Did you send something?" after the Email or Text link (salesperson, admin). */
  function askHtml() {
    if (!S.asking || !S.canSend) return "";
    return '<div class="cd-ask" role="status"><span class="cd-ask-text">Did you send something?</span>' +
      '<button type="button" class="btn" data-act="log-sent">Log it</button>' +
      '<button type="button" class="btn btn-tertiary" data-act="log-sent-no">No</button></div>';
  }

  /** Taken off this week ("Not this week"), with Undo while the week lasts. */
  function snoozedHtml() {
    if (!S.task || S.task.status !== "snoozed" || !S.canSend || archived()) return "";
    return '<div class="cd-off" role="status"><span class="cd-off-text"><span class="cd-off-ring" aria-hidden="true"></span>Taken off this week.</span>' +
      '<button type="button" class="btn btn-tertiary cd-undo" data-act="snooze-undo">Undo</button></div>';
  }

  function noticesHtml(c) {
    var out = "";
    if (c.archived_at) {
      out += '<div class="panel-info cd-notice">' + ico("archive", 18) + '<span class="cd-notice-text">Archived on ' + esc(BD.fmtBizDate(c.archived_at)) + ".</span>" +
        (S.canEdit ? '<button type="button" class="btn" data-act="restore">' + ico("undo", 18) + "Restore</button>" : "") + "</div>";
    }
    if (c.duplicate_of) {
      var d = c.duplicate_of;
      out += '<div class="panel-warn cd-notice cd-dupe">' + ico("copy", 18) + '<span class="cd-notice-text">Possible duplicate of ' + esc(d.name) +
        (d.reason ? " (" + esc(d.reason) + ")" : "") + ".</span>" +
        '<span class="cd-notice-acts"><a class="btn-link" href="' + esc(bdHref("/bd/contact.html?id=", d.contact_id)) + '">Open ' + esc(d.name) + ico("arrow-right", 16) + "</a>" +
        (S.canClearDup ? '<button type="button" class="btn" data-act="dup-clear">Not a duplicate</button>' : "") + "</span></div>";
    }
    return out;
  }

  // ── the Next step card ─────────────────────────────────────────────────────────────────────
  function callLink(cls) {
    var c = S.c;
    var href = BD.telHref(c);
    if (!S.canSend || archived() || !href) return "";
    var num = BD.fmtPhone(c.phone || c.phone_e164);
    return '<a class="btn btn-primary cd-call' + (cls || "") + '" data-act="call" href="' + esc(href) + '">' + ico("phone", 18) + "Call " + esc(num) + "</a>";
  }

  /** The date line: a calendar pill, then why ("Marcus asked for this date") or how far off. */
  function whenHtml(date, why) {
    if (!date) return why ? '<p class="cd-when"><span class="cd-why">' + esc(why) + "</span></p>" : "";
    var rel = BD.fmtRel(date, S.today);
    var tail = why || rel;
    return '<p class="cd-when"><span class="pill pill-neutral cd-date">' + ico("calendar", 16) + esc(BD.fmtDay(date, S.today)) + "</span>" +
      (tail ? '<span class="cd-why">' + esc(tail) + "</span>" : "") + "</p>";
  }

  /** D13: the rule-based suggestion for a reached contact with no step ("Call Marcus again" on
   *  the cadence's next due date, never before today). Null when it does not apply. */
  function cadenceSuggestion() {
    var c = S.c;
    if (!S.canSend || archived() || S.rec || !c.next_due_date || !c.last_live_at) return null;
    var date = c.next_due_date < S.today ? S.today : c.next_due_date;
    var freq = Number(c.frequency_per_year) || 0;
    return { action: "Call " + first() + " again", date: date, why: freq ? "Suggested: " + BD.plural(freq, "live talk") + " a year" : "" };
  }

  function hasStep() { return !!(S.c.next_step || S.c.next_step_date); }

  /** The card's shell; its body is filled by mountNext() (some states are BDCall's to draw). */
  function nextHtml() {
    return '<section id="cd-next" class="card cd-next" aria-labelledby="cd-next-h">' +
      '<h2 class="cd-label" id="cd-next-h">' + ico("flag", 18) + "Next step</h2>" +
      '<div class="cd-next-body" id="cd-next-body"></div>' +
      '<div class="cd-fu-slot" id="cd-fu-slot" hidden></div></section>';
  }

  function stepState() {
    if (S.stepEdit) return "edit";
    if (S.rec && S.canSend && !archived()) return "pending";
    if (hasStep()) return "set";
    return "none";
  }

  function mountNext() {
    var body = $("cd-next-body");
    if (!body) return;
    var c = S.c, state = stepState();
    if (state === "edit") {
      var e = S.stepEdit;
      drawEditor(callHost(body, "editor"), {
        action: e.action, date: e.date, promised: e.promised,
        promisedLabel: first() + " asked for this date", today: S.today,
        actionLabel: "What's next", dateLabel: "When",
        onSave: e.onSave,
        onCancel: function () { S.stepEdit = false; mountNext(); focusOn(e.returnTo || '[data-act="step-change"]', "#cd-next-h"); },
      });
    } else if (state === "pending") {
      // The follow-up for a missed call is drawn once, by mountFollowup() under the card's actions,
      // so decide gets no `missed`; the call itself still words "After a voicemail on Mon, Nov 2".
      drawDecide(callHost(body, "decide"), {
        contact: c, recommendation: S.rec, missed: null, interaction: interactionOf(S.missed ? S.missed.interaction_id : S.rec.interaction_id),
        aiEnabled: aiEnabled(), canSend: S.canSend, onChange: onCallChange, size: "lg",
      });
      // Call keeps the red, on its own row under BDCall's Confirm / Change / Dismiss (outside
      // BDCall's host, so a redraw of the suggestion never takes it away).
      var call = callLink(" hide-phone");
      if (call) body.insertAdjacentHTML("beforeend", '<div class="cd-actions hide-phone">' + call + "</div>");
    } else if (state === "set") {
      var promised = c.promised_date && c.promised_date === c.next_step_date;
      var acts = callLink(" hide-phone");
      if (S.canSend && !archived()) {
        acts += '<button type="button" class="btn btn-tertiary" data-act="step-change">Change</button>' +
          '<button type="button" class="btn btn-tertiary" data-act="step-clear">Clear</button>';
      }
      body.innerHTML = '<p class="cd-step-title">' + esc(c.next_step || "Get in touch with " + first()) + "</p>" +
        whenHtml(c.next_step_date, promised ? first() + " asked for this date" : "") +
        (acts ? '<div class="cd-actions">' + acts + "</div>" : "");
    } else {
      var sug = cadenceSuggestion();
      var html, actsNone = callLink(" hide-phone");
      if (S.suggest && sug) {
        html = '<div class="panel cd-suggest" data-suggest>' +
          '<p class="cd-step-title">' + esc(sug.action) + "</p>" + whenHtml(sug.date, "") +
          (sug.why ? '<p class="cd-reason">' + esc(sug.why) + "</p>" : "") +
          '<div class="cd-actions"><button type="button" class="btn" data-act="suggest-confirm">' + ico("check", 18) + "Confirm</button>" +
          '<button type="button" class="btn btn-tertiary" data-act="suggest-change">Change</button>' +
          '<button type="button" class="btn btn-tertiary" data-act="suggest-cancel">Not now</button></div></div>';
      } else {
        html = '<p class="cd-none">No next step yet.</p>';
        if (sug) actsNone += '<button type="button" class="btn" data-act="suggest">' + ico("lightbulb", 18) + "Suggest one</button>";
      }
      body.innerHTML = html + (actsNone ? '<div class="cd-actions">' + actsNone + "</div>" : "");
    }
    mountFollowup();
  }

  /** The timeline's interaction with this id ({id, kind, outcome, occurred_at}), or null. */
  function interactionOf(id) {
    var hit = null;
    S.items.forEach(function (it) { if (it.type === "interaction" && it.interaction && it.interaction.id === id) hit = it.interaction; });
    return hit;
  }

  /** The missed-call follow-up under the step (salesperson, admin; one per call). */
  function mountFollowup() {
    var slot = $("cd-fu-slot");
    if (!slot) return;
    var m = S.missed;
    if (!m || m.followup_sent || !S.canSend || archived() || S.stepEdit) { slot.hidden = true; slot.innerHTML = ""; return; }
    slot.hidden = false;
    drawFollowup(callHost(slot, "followup"), {
      interactionId: m.interaction_id, contact: S.c, canSend: S.canSend, onDone: onFollowupDone,
    });
  }

  function aiEnabled() { return !!(S.settings && S.settings.ai_enabled); }

  /** A fresh element for one of BDCall's pieces: BDCall wires its own listeners on its host, so
   *  each redraw gets a new host and the old one (with its listeners) goes with the old markup.
   *  The page's delegated click handler steps aside inside [data-bdcall]. */
  function callHost(parent, kind) {
    parent.innerHTML = '<div class="cd-call-host" data-bdcall="' + kind + '"></div>';
    return parent.firstChild;
  }
  /** BDCall's pieces (js/call.js): the suggestion, the step editor and the follow-up. */
  function drawDecide(el, o) { window.BDCall.decide(el, o); }
  function drawEditor(el, o) { window.BDCall.stepEditor(el, o); }
  function drawFollowup(el, o) { window.BDCall.followup(el, o); }

  /** Change: the step editor in place, then one PATCH with all three fields. */
  function editStep(seed, returnTo) {
    S.stepEdit = {
      action: seed.action, date: seed.date, promised: !!seed.promised, returnTo: returnTo,
      onSave: function (v) {
        var body = { next_step: v.action, next_step_date: v.date || null, promised_date: v.promised && v.date ? v.date : null };
        return Api.patch(Api.path("contacts", S.id), body).then(function () {
          return reload().then(function () {
            focusOn('[data-act="step-change"]', "#cd-next-h");
            BD.toast("Next step saved: " + v.action + (v.date ? ", " + BD.fmtDay(v.date, S.today) : "") + ".", { kind: "ok" });
          });
        });
      },
    };
    mountNext();
    var f = root.querySelector('#cd-next-body [data-field="recaction"]');
    if (f) f.focus();
  }

  function clearStep(btn) {
    var c = S.c;
    var was = { next_step: c.next_step, next_step_date: c.next_step_date, promised_date: c.promised_date };
    setBusy(btn, true);
    Api.patch(Api.path("contacts", S.id), { next_step: null, next_step_date: null, promised_date: null }).then(function () {
      return reload().then(function () {
        focusOn('[data-act="suggest"]', "#cd-next-h");
        BD.toast("Next step cleared.", {
          kind: "ok", ms: 8000,
          action: { label: "Undo", onClick: function () {
            Api.patch(Api.path("contacts", S.id), was).then(function () { return reload(); }).then(function () {
              focusOn('[data-act="step-change"]', "#cd-next-h");
            }, fail);
          } },
        });
      });
    }, function (e) { setBusy(btn, false); fail(e); });
  }

  function confirmSuggestion(btn) {
    var sug = cadenceSuggestion();
    if (!sug) return;
    setBusy(btn, true);
    Api.patch(Api.path("contacts", S.id), { next_step: sug.action, next_step_date: sug.date }).then(function () {
      return reload().then(function () {
        focusOn('[data-act="step-change"]', "#cd-next-h");
        BD.toast("Next step saved: " + sug.action + ", " + BD.fmtDay(sug.date, S.today) + ".", { kind: "ok" });
      });
    }, function (e) { setBusy(btn, false); fail(e); });
  }

  /** Any change from BDCall (a saved call, a confirmed or dismissed suggestion, a closed sheet):
   *  read the contact again. BDCall says what it saved in its own toast; this page only moves
   *  the focus to what is there now. */
  function onCallChange(ev) {
    var type = ev && ev.type;
    return reload().then(function () {
      if (type === "confirmed") focusOn(hasStep() ? '[data-act="step-change"]' : '[data-act="suggest"]', "#cd-next-h");
      // The redraw replaced the focused element (the Call button the sheet came from): put focus
      // back on the page, never on <body>.
      var a = document.activeElement;
      if (window.BDCall && window.BDCall.isOpen()) return;
      if (!a || a === document.body || !document.contains(a)) focusOn(callFocusTarget());
    }, fail);
  }

  /** A visible Call (or Log) button on the page, else the contact's name. */
  function callFocusTarget() {
    var pick = function (sel) {
      return Array.prototype.filter.call(document.querySelectorAll(sel), function (n) { return n.getClientRects().length > 0; })[0] || null;
    };
    return pick('[data-act="call"]') || pick('[data-act="log-menu"]') || $("cd-title");
  }

  /** The follow-up was sent (or "Nothing" picked): BDCall toasted it; read the contact again. */
  function onFollowupDone() {
    return reload().then(function () { focusOn("#cd-next-h"); }, fail);
  }

  // ── History ────────────────────────────────────────────────────────────────────────────────
  function composerHtml() {
    if (!S.canNote) return "";
    if (!S.composing) {
      return '<div class="cd-compose"><label class="sr-only" for="cd-note">Add a note</label>' +
        '<input class="input" id="cd-note" type="text" placeholder="Add a note" autocomplete="off" /></div>';
    }
    return '<div class="cd-compose is-open"><label class="sr-only" for="cd-note-text">Note</label>' +
      '<textarea class="textarea" id="cd-note-text" rows="3" placeholder="A line or two about ' + esc(first()) + '"></textarea>' +
      '<p class="field-error" id="cd-note-err" role="alert" hidden></p>' +
      '<div class="cd-actions"><button type="button" class="btn" data-act="note-save">Save note</button>' +
      '<button type="button" class="btn btn-tertiary" data-act="note-cancel">Cancel</button></div></div>';
  }

  function kindIcon(i) {
    if (i.kind === "call") return i.outcome === "no_answer" ? "phone-missed" : (i.direction === "in" ? "phone-incoming" : "phone");
    return { voicemail: "voicemail", meeting: "users", hosted: "flag", email: "mail", sms: "message", note: "pencil" }[i.kind] || "pencil";
  }

  function kindWord(i) {
    var inn = i.direction === "in";
    switch (i.kind) {
      case "call":
        if (i.outcome === "no_answer") return "No answer";
        if (i.outcome === "meeting_set") return "Meeting set";
        return inn ? "Incoming call" : "Call";
      case "voicemail": return inn ? "Voicemail received" : "Voicemail";
      case "email": return inn ? "Email received" : "Email";
      case "sms": return inn ? "Text received" : "Text";
      default: return BD.LABELS.kind[i.kind] || i.kind;
    }
  }

  var EVENT = {
    created: ["Added", "user-plus"], added_from_quote: ["Added from a quote", "user-plus"],
    confirmed: ["Confirmed", "check-circle"], unconfirmed: ["Needs confirming", "help-circle"],
    duplicate_cleared: ["Not a duplicate", "copy"], owner_changed: ["Owner changed", "user"],
    frequency_changed: ["Cadence changed", "clock"], merged: ["Merged", "layers"],
    archived: ["Archived", "archive"], restored: ["Restored", "undo"],
  };

  function interactionItem(i, n) {
    var when = [dayWord(i.occurred_at)];
    var dur = minutes(i.duration_s);
    if (dur) when.push(dur);
    var sent = (i.kind === "email" || i.kind === "sms") && i.direction !== "in";
    var pill = i.counts_as_touch ? '<span class="pill pill-ok">Live talk</span>'
      : ((i.kind === "email" || i.kind === "sms") ? '<span class="pill pill-neutral">Not a live talk</span>' : "");
    var links = "";
    if (i.recording_url && /^https?:\/\//i.test(i.recording_url)) {
      links += '<a href="' + esc(i.recording_url) + '" target="_blank" rel="noopener">Recording</a>';
    }
    if (i.transcript) {
      links += '<button type="button" class="btn-link cd-tl-tx" data-act="transcript" aria-expanded="false" aria-controls="cd-tx-' + i.id + '">Transcript</button>';
    }
    var editing = S.editing != null && S.editing === i.id;
    var words = kindWord(i) + ", " + when.join(", ");
    return '<li class="tl-item cd-tl-item" data-row="' + n + '" data-interaction="' + esc(i.id) + '">' +
      '<span class="cd-tl-ico' + (i.counts_as_touch ? " is-touch" : "") + '" aria-hidden="true">' + ico(kindIcon(i), 20) + "</span>" +
      '<div class="cd-tl-main"><div class="cd-tl-top"><span class="cd-tl-kind"><span class="cd-tl-word">' + esc(kindWord(i)) + "</span>" + pill + "</span>" +
      '<span class="cd-tl-when">' + esc(when.join(" · ")) + "</span></div>" +
      (editing ? entryEditorHtml(i) : (i.summary ? '<p class="cd-tl-text">' + esc(i.summary) + "</p>" : "")) +
      (sent && i.user && i.user.name ? '<p class="cd-tl-by">Logged by ' + esc(i.user.name) + ".</p>" : "") +
      (links ? '<p class="cd-tl-links">' + links + "</p>" : "") +
      (i.transcript ? '<div class="cd-tl-transcript" id="cd-tx-' + i.id + '" hidden>' + esc(i.transcript) + "</div>" : "") +
      (editing ? "" : entryActsHtml(i, words)) +
      "</div></li>";
  }

  /** May this person change this logged entry? The one who logged it, or manage_entries (BD's rule on
   *  PATCH /api/bd/interactions/{id}). An entry nobody logged (a phone system's) is manage_entries'. */
  function mayEditEntry(i) {
    var me = S.me && S.me.user;
    var mine = !!(i.user && i.user.id != null && me && me.id != null && i.user.id === me.id);
    return mine || S.canManage;
  }

  /** Edit (the person who logged it, manage_entries) and Delete (manage_entries) under an entry. */
  function entryActsHtml(i, words) {
    var acts = "";
    if (mayEditEntry(i)) {
      acts += '<button type="button" class="btn-link cd-tl-act" data-act="entry-edit" data-entry="' + esc(i.id) +
        '" aria-label="' + esc("Edit: " + words) + '">' + ico("pencil", 16) + "Edit</button>";
    }
    if (S.canManage) {
      acts += '<button type="button" class="btn-link cd-tl-act cd-tl-del" data-act="entry-delete" data-entry="' + esc(i.id) +
        '" aria-label="' + esc("Delete: " + words) + '">' + ico("trash", 16) + "Delete</button>";
    }
    return acts ? '<p class="cd-tl-acts">' + acts + "</p>" : "";
  }

  /** The entry's words in place, with Save and Cancel (Escape cancels too). */
  function entryEditorHtml(i) {
    return '<div class="field cd-tl-edit"><label for="cd-entry-text">What happened</label>' +
      '<textarea class="textarea" id="cd-entry-text" rows="3">' + esc(i.summary || "") + "</textarea>" +
      '<p class="field-error" id="cd-entry-err" role="alert" hidden></p>' +
      '<div class="cd-actions"><button type="button" class="btn" data-act="entry-save" data-entry="' + esc(i.id) + '">Save</button>' +
      '<button type="button" class="btn btn-tertiary" data-act="entry-cancel" data-entry="' + esc(i.id) + '">Cancel</button></div></div>';
  }

  function eventItem(it, n) {
    var e = it.event || {};
    var m = EVENT[e.action] || [String(e.action || "").replace(/_/g, " "), "history"];
    var by = e.by && e.by.name;
    var text = e.detail ? e.detail + (by ? " by " + by : "") + "." : (by ? by + " " + (BD.VERB[e.action] || "changed this contact") + "." : "");
    return '<li class="tl-item cd-tl-item is-event" data-row="' + n + '">' +
      '<span class="cd-tl-ico" aria-hidden="true">' + ico(m[1], 20) + "</span>" +
      '<div class="cd-tl-main"><div class="cd-tl-top"><span class="cd-tl-kind"><span class="cd-tl-word">' + esc(m[0].charAt(0).toUpperCase() + m[0].slice(1)) + "</span></span>" +
      '<span class="cd-tl-when">' + esc(dayWord(it.at)) + "</span></div>" +
      (text ? '<p class="cd-tl-note">' + esc(text) + "</p>" : "") + "</div></li>";
  }

  function historyHtml() {
    var items = S.items.slice().sort(function (a, b) { return (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0); });
    var rows = items.slice(0, S.shown).map(function (it, n) {
      return it.type === "event" ? eventItem(it, n) : interactionItem(it.interaction, n);
    }).join("");
    var left = items.length - S.shown;
    return '<section id="cd-history" class="card cd-history" aria-labelledby="cd-hist-h">' +
      '<h2 class="cd-card-title" id="cd-hist-h">History</h2>' +
      '<div id="cd-compose-slot">' + composerHtml() + "</div>" +
      (items.length ? '<ol class="timeline cd-tl">' + rows + "</ol>" : '<p class="cd-empty-line">Nothing logged yet.</p>') +
      (left > 0 ? '<div class="cd-more"><button type="button" class="btn" data-act="more-history">Show ' + Math.min(TIMELINE_STEP, left) + " more</button></div>" : "") +
      "</section>";
  }

  function redrawHistory() {
    var hist = $("cd-history");
    if (hist) hist.outerHTML = historyHtml();
  }

  function editEntry(id) {
    S.editing = id;
    redrawHistory();
    var ta = $("cd-entry-text");
    if (ta) { ta.focus(); try { ta.setSelectionRange(ta.value.length, ta.value.length); } catch (e) { /* not a text box */ } }
  }

  function cancelEntry(id) {
    S.editing = null;
    redrawHistory();
    focusOn('[data-act="entry-edit"][data-entry="' + id + '"]', "#cd-hist-h");
  }

  /** One PATCH with the entry's new words; a note needs some. Unchanged words save nothing. */
  function saveEntry(btn, id) {
    var it = interactionOf(id);
    var ta = $("cd-entry-text"), err = $("cd-entry-err");
    if (!it || !ta) return;
    var text = ta.value.trim();
    err.hidden = true;
    if (text === String(it.summary || "").trim()) { cancelEntry(id); return; }
    if (!text && it.kind === "note") { err.textContent = "Type the note first."; err.hidden = false; ta.focus(); return; }
    setBusy(btn, true);
    Api.patch(Api.path("interactions", id), { summary: text }).then(function () {
      return reload().then(function () {
        focusOn('[data-act="entry-edit"][data-entry="' + id + '"]', "#cd-hist-h");
        BD.toast("Entry saved.", { kind: "ok" });
      });
    }, function (e) { setBusy(btn, false); err.textContent = errText(e); err.hidden = false; ta.focus(); });
  }

  /** A BD admin takes a wrong entry off the history, after asking. */
  function deleteEntry(id) {
    var it = interactionOf(id);
    if (!it) return;
    BD.dialog({ title: "Delete this " + kindWord(it).toLowerCase() + "?",
      text: "It comes off " + first() + "'s history for good. This can't be undone.",
      yes: "Delete", no: "Cancel", danger: true })
      .then(function (yes) {
        if (!yes) { focusOn('[data-act="entry-delete"][data-entry="' + id + '"]', "#cd-hist-h"); return null; }
        return Api.del(Api.path("interactions", id)).then(function () {
          return reload().then(function () { focusOn("#cd-hist-h"); BD.toast("Entry deleted.", { kind: "ok" }); });
        }, fail);
      });
  }

  function redrawComposer(focusSel) {
    var slot = $("cd-compose-slot");
    if (!slot) return;
    slot.innerHTML = composerHtml();
    if (focusSel) { var f = $(focusSel); if (f) f.focus(); }
  }

  function saveNote(btn) {
    var ta = $("cd-note-text"), err = $("cd-note-err");
    var text = ta.value.trim();
    err.hidden = true;
    if (!text) { err.textContent = "Type the note first."; err.hidden = false; ta.focus(); return; }
    setBusy(btn, true);
    Api.post(Api.path("contacts", S.id, "interactions"), { kind: "note", summary: text, occurred_at: BD.bizNowISO(S.today) }).then(function () {
      S.composing = false;
      return reload().then(function () { focusOn("#cd-note"); BD.toast("Note saved.", { kind: "ok" }); });
    }, function (e) { setBusy(btn, false); err.textContent = errText(e); err.hidden = false; });
  }

  // ── side: This year, Details, Others, Archive ──────────────────────────────────────────────
  var YEAR_PILL = {
    on_track: ["ok", "On track", "check"], behind: ["warn", "Behind", null],
    never: ["info", "Never reached", null], complete: ["ok", "Done for the year", "check"],
  };

  function yearHtml(c) {
    var freq = Number(c.frequency_per_year) || 0, t = Number(c.touches_this_year) || 0;
    var p = YEAR_PILL[c.cadence_status] || ["neutral", c.cadence_status, null];
    var bar;
    if (freq > 0 && freq <= 12) {
      var segs = "";
      for (var i = 0; i < freq; i++) segs += "<span" + (i < t ? ' class="is-done"' : "") + "></span>";
      bar = '<div class="seg-bar cd-year-bar" role="img" aria-label="' + esc(t + " of " + freq) + ' live talks this year">' + segs + "</div>";
    } else {
      bar = '<div class="progress cd-year-bar" role="img" aria-label="' + esc(t + " of " + freq) + ' live talks this year">' +
        '<div class="progress-fill" data-w="' + (freq > 0 ? Math.min(100, Math.round(100 * t / freq)) : 0) + '"></div></div>';
    }
    var due;
    if (c.cadence_status === "behind") due = "Due for a live talk";
    else if (c.cadence_status === "never" || !c.next_due_date) due = "No live talk yet.";
    else due = "Next one due by <strong>" + esc(BD.fmtDay(c.next_due_date, S.today)) + "</strong>";
    return '<section id="cd-year" class="card cd-year" aria-labelledby="cd-year-h">' +
      '<div class="cd-card-head"><h2 class="cd-card-title" id="cd-year-h">This year</h2>' +
      '<span class="pill pill-' + p[0] + '">' + (p[2] ? ico(p[2], 14) : "") + esc(p[1]) + "</span></div>" +
      '<p class="cd-year-num"><span class="cd-big">' + esc(t + " of " + freq) + '</span><span class="cd-year-unit">live talks</span></p>' +
      bar + '<p class="cd-year-due">' + due + "</p></section>";
  }

  // ── side: Follow-up cadence ────────────────────────────────────────────────────────────────
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  /** "2027-01-31" -> "Jan 31" (the date as written: no clock, no time zone). */
  function monDay(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    // The year only when the day is not in this (Central) year, like BD.fmtDay: "Jan 31, 2027".
    return m ? MONTHS[+m[2] - 1] + " " + (+m[3]) + (S.today && m[1] !== String(S.today).slice(0, 4) ? ", " + m[1] : "") : "";
  }
  /** The BD cadence everyone follows unless a contact has an override: weekly, monthly or quarterly. */
  function globalCadence() {
    var w = S.settings && S.settings.bd_cadence;
    return w === "weekly" || w === "monthly" || w === "quarterly" ? w : "";
  }
  function overrideActive(c) { return c.category !== "maintenance" && c.cadence_source === "override" && !!c.cadence_override_until; }
  /** The cadence the contact follows now: the active override, else the global one. */
  function cadenceWord(c) { return (overrideActive(c) ? c.cadence_override : c.cadence) || globalCadence(); }
  function capital(w) { return w ? w.charAt(0).toUpperCase() + w.slice(1) : ""; }
  var MAINT_RULE = "A follow-up comes due 120 days after the last call, meeting, email or text.";

  function cadenceHtml(c) {
    var line, sub = "", pill = "";
    if (c.category === "maintenance") {
      sub = MAINT_RULE;
      if (c.maintenance_due) {
        line = "Follow-up due now.";
        pill = '<span class="pill pill-warn">Due now</span>';
        if (!c.last_followup_at) sub = "No follow-up logged yet. " + sub;
      } else if (c.maintenance_due_date) line = "Next follow-up due " + monDay(c.maintenance_due_date) + ".";
      else line = "No follow-up logged yet.";
    } else if (overrideActive(c)) {
      var back = globalCadence();
      line = "Follow up " + cadenceWord(c) + " until " + monDay(c.cadence_override_until) + ", then back to " + (back || "the BD cadence") + ".";
      pill = '<span class="pill pill-info">Override</span>';
    } else {
      var w = cadenceWord(c);
      line = w ? "Follow up " + w + "." : "Follows the BD cadence.";
    }
    var edit = S.canFreq && !archived()
      ? '<button type="button" class="btn cd-edit-btn" data-act="cadence">' + ico("pencil", 18) +
        (c.category === "maintenance" ? "Change live talks a year" : "Change cadence") + "</button>" : "";
    return '<section id="cd-cadence" class="card cd-cadence" aria-labelledby="cd-cad-h">' +
      '<div class="cd-card-head"><h2 class="cd-card-title" id="cd-cad-h">Follow-up cadence</h2>' + pill + "</div>" +
      '<p class="cd-cad-line">' + esc(line) + "</p>" +
      (sub ? '<p class="cd-cad-sub">' + esc(sub) + "</p>" : "") + edit + "</section>";
  }

  function pair(label, value, cls) {
    return '<div class="cd-kv-item' + (cls ? " " + cls : "") + '"><dt>' + esc(label) + "</dt><dd>" + value + "</dd></div>";
  }
  function plain(v) { return v == null || v === "" ? '<span class="cd-none-val">None</span>' : esc(v); }

  function detailsHtml(c) {
    var phone = c.phone || c.phone_e164;
    var href = BD.telHref(c);
    var num = BD.fmtPhone(phone);
    var phoneVal = phone && href
      ? '<a class="cd-tel" href="' + esc(href) + '" aria-label="Call ' + esc(c.name) + ", " + esc(num) + '">' + esc(num) + "</a>" : plain(phone);
    var imp = IMPORTANCE.filter(function (x) { return x[0] === Number(c.importance); })[0];
    var sw = S.canEdit
      ? '<span class="cd-switch"><button type="button" class="switch" role="switch" id="cd-confirm" data-act="confirm-toggle" aria-checked="' + (c.confirmed ? "true" : "false") +
        '" aria-labelledby="cd-confirm-label"></button><span class="cd-switch-word" aria-hidden="true">' + (c.confirmed ? "Yes" : "No") + "</span></span>"
      : (c.confirmed ? "Yes" : "No");
    var rows = pair("Phone", phoneVal) + pair("City", plain(c.city)) +
      pair("Email", c.email ? '<a href="mailto:' + esc(c.email) + '">' + esc(c.email) + "</a>" : plain(""), "cd-kv-full") +
      '<div class="cd-kv-rule" aria-hidden="true"></div>' +
      pair("Industry", plain(c.industry)) + pair("Lead source", plain(c.lead_source)) +
      pair("Stage", plain(c.stage)) + pair("Importance", plain(imp ? imp[1] : "")) +
      pair("Owner", plain(c.owner && c.owner.name)) + pair("Co-owner", plain(c.co_owner && c.co_owner.name)) +
      (c.category === "maintenance" ? pair("Category", "Maintenance") + pair("Account type", plain(c.account_type)) : "") +
      (c.category === "maintenance" ? pair("Live talks a year", plain(c.frequency_per_year))
        : pair("Follow-up cadence", plain(capital(cadenceWord(c)) + (overrideActive(c) ? " until " + monDay(c.cadence_override_until) : "")),
          overrideActive(c) ? "cd-kv-full" : "")) +
      '<div class="cd-kv-item"><dt id="cd-confirm-label">Still the right person?</dt><dd>' + sw + "</dd></div>" +
      ((c.tags || []).length ? pair("Tags", '<span class="wrap-row cd-tags">' + c.tags.map(function (t) { return '<span class="pill pill-neutral">' + esc(t) + "</span>"; }).join("") + "</span>", "cd-kv-full") : "") +
      (c.notes ? pair("Notes", '<span class="cd-pre">' + esc(c.notes) + "</span>", "cd-kv-full") : "");
    // A manager gets the cadence sheet only (never the full form): the same one the cadence card opens.
    var edit = S.canEdit ? "Edit details" : (S.cadenceOnly && !archived() ? "Edit follow-up cadence" : "");
    return '<section id="cd-details" class="card cd-details" aria-labelledby="cd-det-h">' +
      '<details class="cd-fold" id="cd-details-fold"><summary class="cd-fold-sum"><h2 class="cd-card-title" id="cd-det-h">Details</h2>' +
      '<span class="cd-fold-chev" aria-hidden="true">' + ico("chev-down", 20) + "</span></summary>" +
      '<dl class="cd-kv">' + rows + "</dl>" +
      (edit ? '<button type="button" class="btn cd-edit-btn" data-act="edit">' + ico("pencil", 18) + esc(edit) + "</button>" : "") +
      "</details></section>";
  }

  function othersHtml(c) {
    var name = c.company ? c.company.name : "this company";
    var body;
    if (S.others === null) body = '<div class="skeleton cd-skel-line"></div>';
    else if (S.others === "failed") body = '<p class="cd-empty-line">Could not load them.</p>';
    else if (!S.others.length) {
      body = '<p class="cd-empty-line">No one else here yet.</p>' +
        (S.canAdd && c.company ? '<a class="btn cd-add-someone" href="' + esc(bdHref("/bd/add.html?company=", c.company.id)) + '">' + ico("plus", 18) + "Add someone</a>" : "");
    } else {
      body = '<ul class="cd-others">' + S.others.map(function (o) {
        return '<li class="cd-other">' + BD.avatarHTML(o.name, "sm") + '<span class="who"><a class="who-name" href="' + esc(bdHref("/bd/contact.html?id=", o.id)) + '">' +
          esc(o.name) + "</a>" + (o.title ? '<span class="who-sub">' + esc(o.title) + "</span>" : "") + "</span></li>";
      }).join("") + "</ul>";
    }
    return '<section id="cd-others" class="card cd-others-card" aria-labelledby="cd-oth-h">' +
      '<h2 class="cd-card-title" id="cd-oth-h">Others at ' + esc(name) + "</h2>" + body + "</section>";
  }

  function archiveHtml() {
    if (!S.canEdit || archived()) return "";
    return '<button type="button" class="btn btn-tertiary cd-archive" data-act="archive">' + ico("archive", 18) + "Archive " + esc(first()) + "</button>";
  }

  function callbarHtml() {
    var call = callLink();
    var log = logItems().length ? logButton(" cd-callbar-log") : "";
    if (!call && !log) return "";
    return '<div class="cd-callbar show-phone' + (call ? "" : " is-log-only") + '">' + call + log + "</div>";
  }

  // ── the whole page ─────────────────────────────────────────────────────────────────────────
  function render() {
    var c = S.c;
    document.title = c.name + " · BD CRM · Treadwell";
    var bar = callbarHtml();
    document.body.classList.toggle("cd-has-callbar", !!bar);
    root.removeAttribute("aria-busy");
    root.innerHTML = backHtml() + headHtml(c) +
      '<div id="cd-ask-slot">' + askHtml() + "</div>" + snoozedHtml() + noticesHtml(c) +
      '<div class="layout-2 cd-layout"><div class="cd-main">' + nextHtml() + historyHtml() + "</div>" +
      '<aside class="cd-side" aria-label="About ' + esc(c.name) + '">' + yearHtml(c) + cadenceHtml(c) + detailsHtml(c) + othersHtml(c) + archiveHtml() + "</aside></div>" +
      bar;
    Array.prototype.forEach.call(root.querySelectorAll("[data-w]"), function (el) { el.style.width = el.getAttribute("data-w") + "%"; });
    mountNext();
    syncFold();
  }

  function redrawOthers() {
    var el = $("cd-others");
    if (el) el.outerHTML = othersHtml(S.c);
  }

  /** Details is open at 768px and up, folded under its heading on a phone. */
  function syncFold() {
    var f = $("cd-details-fold");
    if (!f) return;
    var w = wide();
    if (w) f.open = true;
    var sum = f.querySelector("summary");
    if (sum) sum.tabIndex = w ? -1 : 0;
  }

  function renderNotFound() {
    document.title = "Contact not found · BD CRM · Treadwell";
    root.removeAttribute("aria-busy");
    root.innerHTML = '<div class="empty empty-page"><div class="empty-ico">' + ico("user-x", 24) + "</div>" +
      '<h1 class="empty-title">That contact isn\'t here</h1>' +
      '<p class="empty-text">It may have been merged into another contact, or the link may be wrong.</p>' +
      '<a class="btn btn-primary" href="/bd/">Back to the BD CRM</a></div>';
  }

  function renderError(e) {
    root.removeAttribute("aria-busy");
    root.innerHTML = '<div class="error-box" role="alert"><p>' + esc(errText(e)) + "</p>" +
      '<button type="button" class="btn" data-act="retry">Try again</button></div>';
  }

  // ── actions ────────────────────────────────────────────────────────────────────────────────
  function openCall(mode, extra) {
    if (!window.BDCall || typeof window.BDCall.open !== "function") return;
    var o = {
      contact: S.c, task: taskOpen() ? S.task : null, mode: mode, startedAt: BD.bizNowISO(S.today),
      recommendation: S.rec, missed: S.missed, aiEnabled: aiEnabled(), canSend: S.canSend, onChange: onCallChange,
      returnFocus: callFocusTarget,
    };
    if (extra) Object.keys(extra).forEach(function (k) { o[k] = extra[k]; });
    window.BDCall.open(o);
  }

  function openLogMenu(btn) {
    BD.menu(btn, logItems());
  }

  function onMenu(e) {
    var act = e.detail && e.detail.act;
    switch (act) {
      case "log-call": openCall("call", { logPast: true }); break;
      case "log-meeting": openCall("meeting", { logPast: true }); break;
      case "log-hosted": openCall("meeting", { focusOutcome: "hosted", logPast: true }); break;
      case "nrp": openCall("nrp"); break;
      case "log-note": startNote(); break;
      case "snooze": snooze(); break;
      default: break;
    }
  }

  function startNote() {
    S.composing = true;
    redrawComposer("cd-note-text");
    var ta = $("cd-note-text");
    if (ta && ta.scrollIntoView) ta.scrollIntoView({ block: "center" });
  }

  function snooze() {
    var t = S.task;
    if (!t) return;
    Api.post(Api.path("tasks", t.id, "snooze"), {}).then(function () {
      return reload().then(function () { focusOn('[data-act="snooze-undo"]', "#cd-title"); });
    }, fail);
  }

  function unsnooze(btn) {
    var t = S.task;
    if (!t) return;
    setBusy(btn, true);
    Api.post(Api.path("tasks", t.id, "reopen"), {}).then(function () {
      return reload().then(function () { focusOn("#cd-title"); BD.toast("Back on this week's list.", { kind: "ok" }); });
    }, function (e) { setBusy(btn, false); fail(e); });
  }

  function logSent(btn) {
    var kind = S.asking;
    setBusy(btn, true);
    Api.post(Api.path("contacts", S.id, "interactions"), { kind: kind, occurred_at: BD.bizNowISO(S.today) }).then(function () {
      S.asking = null;
      return reload().then(function () {
        focusOn("#cd-hist-h");
        BD.toast((kind === "email" ? "Email" : "Text") + " logged. It is not a live talk.", { kind: "ok" });
      });
    }, function (e) { setBusy(btn, false); fail(e); });
  }

  function toggleConfirm(btn) {
    var next = !S.c.confirmed;
    setBusy(btn, true);
    Api.post(Api.path("contacts", S.id, "confirm"), { confirmed: next }).then(function () {
      return reload().then(function () {
        focusOn("#cd-confirm");
        BD.toast(next ? "Marked as still the right person." : "Marked as needs confirming.", { kind: "ok" });
      });
    }, function (e) { setBusy(btn, false); fail(e); });
  }

  function archive() {
    var c = S.c;
    BD.dialog({ title: "Archive " + c.name + "?", text: "They leave every list. Their history is kept.", yes: "Archive", no: "Cancel", danger: true,
      field: { label: "Why? (optional)", placeholder: "For example: left the company", maxlength: 200 } })
      .then(function (yes) {
        if (!yes) return null;
        var body = { archived: true };
        var reason = typeof yes === "string" ? yes.trim() : "";
        if (reason) body.reason = reason;
        return Api.post(Api.path("contacts", S.id, "archive"), body).then(function () {
          return reload().then(function () {
            focusOn('[data-act="restore"]', "#cd-title");
            BD.toast("Archived. " + first() + " is off every list.", {
              kind: "ok", ms: 8000, action: { label: "Undo", onClick: function () { restore(null); } },
            });
          });
        }, fail);
      });
  }

  function restore(btn) {
    setBusy(btn, true);
    Api.post(Api.path("contacts", S.id, "archive"), { archived: false }).then(function () {
      return reload().then(function () {
        focusOn('[data-act="archive"]', "#cd-title");
        BD.toast("Restored. " + first() + " can come back on a weekly list.", { kind: "ok" });
      });
    }, function (e) { setBusy(btn, false); fail(e); });
  }

  function clearDuplicate(btn) {
    setBusy(btn, true);
    Api.patch(Api.path("contacts", S.id), { duplicate_of: null }).then(function () {
      return reload().then(function () { focusOn("#cd-title"); BD.toast("Marked as not a duplicate.", { kind: "ok" }); });
    }, function (e) { setBusy(btn, false); fail(e); });
  }

  function showMore() {
    var from = S.shown;
    S.shown += TIMELINE_STEP;
    redrawHistory();
    focusOn('[data-row="' + from + '"]', "#cd-hist-h");
  }

  function toggleTranscript(btn) {
    var box = $(btn.getAttribute("aria-controls"));
    if (!box) return;
    var open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", open ? "false" : "true");
    box.hidden = open;
  }

  // ── the Edit details drawer ────────────────────────────────────────────────────────────────
  /** The select value for an owner ref: its id, KEEP for a workbook name with no login, "" for none. */
  function refValue(u) { return u ? (u.id != null ? String(u.id) : KEEP) : ""; }

  function ownerChoices(key) {
    var c = S.c;
    var current = key === "owner" ? c.owner : c.co_owner;
    var roles = key === "owner" ? ["salesperson"] : ["salesperson", "manager"];
    var skip = key === "co_owner" && c.owner && c.owner.id != null ? String(c.owner.id) : null;
    var seen = {}, out = [];
    function add(u) {
      var v = refValue(u);
      if (!v || seen[v] || v === skip) return;
      seen[v] = true;
      out.push([v, u.name]);
    }
    (S.users || []).forEach(function (u) { if (roles.indexOf(u.role) !== -1) add(u); });
    add(current);
    out.sort(function (a, b) { return String(a[1]).localeCompare(String(b[1])); });
    return out;
  }

  function same(list) { return list.map(function (v) { return [v, v]; }); }

  function fieldDefs() {
    var c = S.c;
    var all = [
      { key: "name", label: "Name", type: "text", required: true, get: function () { return c.name; } },
      { key: "title", label: "Title", type: "text", get: function () { return c.title; } },
      { key: "company", label: "Company", type: "company", required: true, get: function () { return c.company ? c.company.name : ""; } },
      { key: "phone", label: "Phone", type: "tel", get: function () { return c.phone; } },
      { key: "email", label: "Email", type: "email", get: function () { return c.email; } },
      { key: "city", label: "City", type: "text", get: function () { return c.city; } },
      { key: "industry", label: "Industry", type: "select", pairs: same(setting("industries")), blank: "Not set", get: function () { return c.industry; } },
      { key: "lead_source", label: "Lead source", type: "select", pairs: same(setting("lead_sources")), get: function () { return c.lead_source; } },
      { key: "stage", label: "Stage", type: "select", pairs: same(setting("stages")), blank: "None", get: function () { return c.stage; } },
      { key: "category", label: "Category", type: "select", pairs: [["bd", "BD"], ["maintenance", "Maintenance"]], get: function () { return c.category; } },
      { key: "account_type", label: "Account type", type: "select", pairs: same(setting("account_types")), blank: "Not set", optional: true, get: function () { return c.account_type; } },
      { key: "owner", label: "Owner", type: "select", pairs: ownerChoices("owner"), blank: "Nobody", get: function () { return refValue(c.owner); },
        patch: function (v) { return idPatch("owner_id", v); } },
      { key: "co_owner", label: "Co-owner", type: "select", pairs: ownerChoices("co_owner"), blank: "Nobody", optional: true, get: function () { return refValue(c.co_owner); },
        patch: function (v) { return idPatch("co_owner_id", v); } },
      { key: "frequency_per_year", label: "Live talks a year", type: "number", get: function () { return c.frequency_per_year; },
        hint: "Answered calls, meetings and hosted events count." },
      { key: "importance", label: "Importance", type: "select", pairs: IMPORTANCE.map(function (p) { return [String(p[0]), p[1]]; }), get: function () { return String(c.importance || 1); },
        patch: function (v) { return { importance: Number(v) }; } },
      { key: "next_step", label: "Next step", type: "text", optional: true, get: function () { return c.next_step; } },
      { key: "next_step_date", label: "Next step date", type: "date", optional: true, future: true, get: function () { return c.next_step_date; } },
      { key: "promised_date", label: "Date we promised", type: "date", optional: true, future: true, get: function () { return c.promised_date; } },
      { key: "tags", label: "Tags", type: "text", optional: true, get: function () { return (c.tags || []).join(", "); },
        patch: function (v) { return { tags: v ? v.split(",").map(function (t) { return t.trim(); }).filter(Boolean) : [] }; },
        hint: "Separate with commas." },
      { key: "notes", label: "Notes", type: "textarea", optional: true, get: function () { return c.notes; } },
    ];
    // A BD contact's number is derived (override, else the BD cadence) and the server refuses it: only a
    // maintenance contact has it here. A BD contact's cadence is the cadence sheet's override fields.
    if (c.category !== "maintenance") all = all.filter(function (d) { return d.key !== "frequency_per_year"; });
    return all;
  }

  /** The cadence sheet's fields: the override (BD) or the number (maintenance). Never the full form. */
  function cadenceDefs() {
    var c = S.c;
    if (c.category === "maintenance") {
      return fieldDefs().filter(function (d) { return d.key === "frequency_per_year"; });
    }
    var on = overrideActive(c);
    return [
      { key: "cadence_override", label: "Follow up", type: "select", blank: "Use the BD cadence",
        pairs: [["weekly", "Weekly"], ["monthly", "Monthly"], ["quarterly", "Quarterly"]], get: function () { return on ? c.cadence_override : ""; } },
      { key: "cadence_override_until", label: "Until (last day)", type: "date", min: S.today, get: function () { return on ? c.cadence_override_until : ""; },
        hint: "After this day it goes back to the BD cadence" + (globalCadence() ? " (" + globalCadence() + ")" : "") + "." },
    ];
  }

  /** {owner_id: 3} or {owner_id: null}; a KEEP (a workbook name with no login) is never sent. */
  function idPatch(field, v) {
    var body = {};
    if (v === "") body[field] = null;
    else if (/^\d+$/.test(v)) body[field] = Number(v);
    else return null;
    return body;
  }

  function fieldHtml(d) {
    var id = "cd-f-" + d.key;
    var v = d.get();
    v = v == null ? "" : String(v);
    var control;
    if (d.type === "select") {
      var pairs = d.pairs.slice();
      if (v && !pairs.some(function (p) { return String(p[0]) === v; })) pairs.push([v, v]);
      control = '<select class="select" id="' + id + '" name="' + d.key + '">' +
        (d.blank ? '<option value="">' + esc(d.blank) + "</option>" : "") +
        pairs.map(function (p) {
          return '<option value="' + esc(p[0]) + '"' + (String(p[0]) === v ? " selected" : "") + ">" + esc(p[1]) + "</option>";
        }).join("") + "</select>";
    } else if (d.type === "textarea") {
      control = '<textarea class="textarea" id="' + id + '" name="' + d.key + '" rows="4">' + esc(v) + "</textarea>";
    } else {
      var type = { tel: "tel", email: "email", number: "number", date: "date" }[d.type] || "text";
      control = '<input class="input" id="' + id + '" name="' + d.key + '" type="' + type + '" value="' + esc(v) + '"' +
        (d.type === "tel" ? ' inputmode="tel" autocomplete="off"' : "") +
        (d.type === "number" ? ' inputmode="numeric" min="1" max="52" step="1"' : "") +
        (d.type === "date" && d.min ? ' min="' + esc(d.min) + '"' : "") +
        (d.type === "company" ? ' list="cd-companies" autocomplete="off"' : "") + " />" +
        (d.type === "company" ? '<datalist id="cd-companies">' + (S.companies || []).map(function (co) {
          return '<option value="' + esc(String(co.name).trim()) + '"></option>';
        }).join("") + "</datalist>" : "");
    }
    return '<div class="field" data-field="' + d.key + '"><label for="' + id + '">' + esc(d.label) +
      (d.optional ? ' <span class="opt">(optional)</span>' : "") + "</label>" + control +
      (d.hint ? '<p class="field-hint">' + esc(d.hint) + "</p>" : "") +
      '<p class="field-error" id="' + id + '-err" hidden></p></div>';
  }

  /** mode "details": the full form (salesperson, assistant, admin). mode "cadence": only how often to
   *  follow up. A manager is always in cadence mode, whatever opened it. */
  function openEdit(opener, mode) {
    if ($("cd-edit-sheet")) return;
    if (!S.canEdit) mode = "cadence";
    setBusy(opener, true);
    var needs = [];
    if (mode === "details" && S.users === null) {
      needs.push(Api.get("/api/bd/users").then(function (r) {
        S.users = (r.items || []).filter(function (u) { return u.active !== false; });
      }, function () { S.users = []; }));
    }
    if (mode === "details" && S.companies === null) {
      needs.push(fetchAll("/api/bd/companies").then(function (r) { S.companies = r; }, function () { S.companies = []; }));
    }
    Promise.all(needs).then(function () {
      setBusy(opener, false);
      drawEdit(opener, mode);
    });
  }

  function drawEdit(opener, mode) {
    var cad = mode === "cadence";
    var defs = cad ? cadenceDefs() : fieldDefs();
    var back = opener && opener.getAttribute && opener.getAttribute("data-act") || "edit";
    var sheet = document.createElement("div");
    sheet.className = "sheet cd-edit-sheet";
    sheet.id = "cd-edit-sheet";
    sheet.setAttribute("aria-labelledby", "cd-edit-title");
    sheet.hidden = true;
    var bd = S.c.category !== "maintenance";
    var title = !cad ? "Edit details" : (bd ? "Change cadence" : "Change live talks a year");
    var clear = cad && bd && S.c.cadence_override != null
      ? '<div class="cd-cad-clear"><button type="button" class="btn" data-act="clear-override">Use the BD cadence</button></div>' : "";
    sheet.innerHTML = '<div class="sheet-grab" aria-hidden="true"></div>' +
      '<div class="sheet-head"><h2 class="sheet-title" id="cd-edit-title">' + esc(title) + "</h2>" +
      '<button type="button" class="btn btn-icon" data-act="edit-close" aria-label="Close">' + ico("x", 20) + "</button></div>" +
      '<div class="sheet-body"><form id="cd-edit" class="cd-edit-form" novalidate>' + defs.map(fieldHtml).join("") + clear +
      '<p class="field-error" id="cd-edit-err" role="alert" hidden></p></form></div>' +
      '<div class="sheet-bar"><button type="button" class="btn btn-tertiary" data-act="edit-close">Cancel</button>' +
      '<button type="submit" form="cd-edit" class="btn btn-primary" data-act="edit-save">Save</button></div>';
    document.body.appendChild(sheet);
    sheet.addEventListener("click", function (e) {
      var b = e.target.closest && e.target.closest('[data-act="edit-close"]');
      if (b) { BD.sheet.close(sheet, "close"); return; }
      var cl = e.target.closest && e.target.closest('[data-act="clear-override"]');
      if (cl) sendPatch(sheet, cl, { cadence_override: null }, back);
    });
    // A contact being switched to BD has no number of its own (the server refuses one): hide it and send none.
    // The last day only means something with a cadence picked: while "Use the BD cadence" is chosen it is locked.
    var syncUntil = function () {
      var pick = $("cd-f-cadence_override"), until = $("cd-f-cadence_override_until");
      if (pick && until) until.disabled = !pick.value;
    };
    var syncNumber = function () {
      var catCtl = $("cd-f-category"), numWrap = sheet.querySelector('.field[data-field="frequency_per_year"]');
      if (catCtl && numWrap) numWrap.hidden = catCtl.value === "bd";
    };
    syncNumber();
    sheet.addEventListener("change", function (e) {
      if (e.target && e.target.id === "cd-f-category") syncNumber();
      // "Use the BD cadence" has no last day: clear it so the form never says two things.
      if (e.target && e.target.id === "cd-f-cadence_override") {
        var until = $("cd-f-cadence_override_until");
        if (until && !e.target.value) until.value = "";
        syncUntil();
      }
    });
    syncUntil();
    sheet.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      if (cad && bd) saveCadence(sheet, back); else saveEdit(sheet, defs, back);
    });
    var firstField = sheet.querySelector(!cad ? "#cd-f-name" : (bd ? "#cd-f-cadence_override" : "#cd-f-frequency_per_year"));
    BD.sheet.open(sheet, {
      initialFocus: firstField,
      onClose: function () {
        setTimeout(function () { if (sheet.parentNode) sheet.parentNode.removeChild(sheet); }, 220);
        if (opener && document.contains(opener)) opener.focus();
        else focusOn('[data-act="' + back + '"]', '[data-act="edit"]', '[data-act="cadence"]');
      },
    });
  }

  function showFieldErrors(sheet, errs) {
    Array.prototype.forEach.call(sheet.querySelectorAll(".field"), function (f) {
      f.classList.remove("has-error");
      var e = f.querySelector(".field-error");
      if (e) { e.hidden = true; e.textContent = ""; }
      var inp = f.querySelector("input, select, textarea");
      if (inp) { inp.removeAttribute("aria-invalid"); inp.removeAttribute("aria-describedby"); }
    });
    var firstBad = null;
    Object.keys(errs).forEach(function (k) {
      var key = k === "owner_id" ? "owner" : (k === "co_owner_id" ? "co_owner" : k);
      var wrap = sheet.querySelector('.field[data-field="' + key + '"]');
      if (!wrap) {
        var all = $("cd-edit-err");
        if (all) { all.textContent = errs[k]; all.hidden = false; }
        return;
      }
      wrap.classList.add("has-error");
      var e = wrap.querySelector(".field-error");
      e.textContent = errs[k]; e.hidden = false;
      var inp = wrap.querySelector("input, select, textarea");
      if (inp) { inp.setAttribute("aria-invalid", "true"); inp.setAttribute("aria-describedby", e.id); if (!firstBad) firstBad = inp; }
    });
    if (firstBad) firstBad.focus();
  }

  function saveEdit(sheet, defs, back) {
    var save = sheet.querySelector('[data-act="edit-save"]');
    var body = {}, errs = {};
    defs.forEach(function (d) {
      var ctl = $("cd-f-" + d.key);
      if (!ctl) return;
      var v = String(ctl.value || "").trim();
      var was = d.get() == null ? "" : String(d.get()).trim();
      if (v === was) return;
      if (d.required && !v) { errs[d.key] = d.label + " can't be empty."; return; }
      if (d.key === "email" && v && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)) { errs.email = "That doesn't look like an email address."; return; }
      if (d.future && v && !/^\d{4}-\d{2}-\d{2}$/.test(v)) { errs[d.key] = "Pick a date."; return; }
      if (d.future && v && S.today && v < S.today) { errs[d.key] = "Pick today or a later day."; return; }
      if (d.key === "phone" && v && !BD.e164(v)) { errs.phone = "Enter a 10-digit phone number, like 816-555-0142."; return; }
      if (d.key === "frequency_per_year") {
        var catNow = $("cd-f-category");
        if (catNow && catNow.value === "bd") return;
        var n = Number(v);
        if (!(v !== "" && n >= 1 && n <= 52 && Math.floor(n) === n)) { errs.frequency_per_year = "Use a whole number from 1 to 52."; return; }
        body.frequency_per_year = n;
        return;
      }
      if (d.patch) {
        var p = d.patch(v);
        if (p) Object.keys(p).forEach(function (k) { body[k] = p[k]; });
        return;
      }
      if (d.key === "company") {
        var exact = (S.companies || []).filter(function (co) { return String(co.name).trim().toLowerCase() === v.toLowerCase(); })[0];
        body.company = exact ? { id: exact.id } : { name: v };
        return;
      }
      body[d.key] = v === "" ? null : v;
    });
    showFieldErrors(sheet, errs);
    if (Object.keys(errs).length) return;
    if (!Object.keys(body).length) { BD.sheet.close(sheet, "close"); BD.toast("Nothing changed.", { kind: "info" }); return; }
    sendPatch(sheet, save, body, back);
  }

  /** One PATCH from the edit sheet: close and reload on success, the server's words under the field on a 400. */
  function sendPatch(sheet, btn, body, back) {
    // One request at a time: while it is out, Save and "Use the BD cadence" are both off, so a second
    // patch can never race the first and leave the opposite of what the sheet shows.
    if (sheet.getAttribute("data-sending")) return;
    sheet.setAttribute("data-sending", "true");
    var acts = Array.prototype.slice.call(sheet.querySelectorAll('[data-act="edit-save"], [data-act="clear-override"]'));
    acts.forEach(function (b) { if (b !== btn) b.disabled = true; });
    setBusy(btn, true);
    Api.patch(Api.path("contacts", S.id), body).then(function (r) {
      var dup = (r && r.possible_duplicates || [])[0];
      BD.sheet.close(sheet, "saved");
      return reload().then(function () {
        focusOn('[data-act="' + (back || "edit") + '"]', '[data-act="edit"]', '[data-act="cadence"]');
        if (dup) {
          BD.toast("Saved. This may be the same person as " + dup.name + " at " + dup.company + ".", { kind: "info", ms: 8000 });
        } else BD.toast("Saved.", { kind: "ok" });
      });
    }, function (e) {
      sheet.removeAttribute("data-sending");
      acts.forEach(function (b) { b.disabled = false; });
      setBusy(btn, false);
      if (e && e.fields) showFieldErrors(sheet, e.fields);
      else { var all = $("cd-edit-err"); all.textContent = errText(e); all.hidden = false; }
    });
  }

  /** A BD contact's cadence sheet: the override word and its last day go together in ONE patch; "Use the
   *  BD cadence" sends null. The sentences are the server's, so a pre-check and the server read alike. */
  function saveCadence(sheet, back) {
    var c = S.c;
    var word = String($("cd-f-cadence_override").value || "").trim();
    var until = String($("cd-f-cadence_override_until").value || "").trim();
    var errs = {}, body = {};
    if (!word) {
      if (until && until !== c.cadence_override_until) errs.cadence_override = "Pick how often first.";
      else if (c.cadence_override != null) body.cadence_override = null;
    } else if (!until) errs.cadence_override_until = "Pick the last day of the override.";
    else if (!/^\d{4}-\d{2}-\d{2}$/.test(until)) errs.cadence_override_until = "Use a date (YYYY-MM-DD).";
    else if (overrideActive(c) && word === c.cadence_override && until === c.cadence_override_until) body = {};
    else if (S.today && until < S.today) errs.cadence_override_until = "Pick a day from today on.";
    else { body.cadence_override = word; body.cadence_override_until = until; }
    showFieldErrors(sheet, errs);
    if (Object.keys(errs).length) return;
    if (!Object.keys(body).length) { BD.sheet.close(sheet, "close"); BD.toast("Nothing changed.", { kind: "info" }); return; }
    sendPatch(sheet, sheet.querySelector('[data-act="edit-save"]'), body, back);
  }

  // ── events ─────────────────────────────────────────────────────────────────────────────────
  function onClick(e) {
    var t = e.target;
    if (!t.closest) return;
    if (t.closest(".menu")) return;
    var btn = t.closest("[data-act]");
    if (!btn || !root.contains(btn)) return;
    var act = btn.getAttribute("data-act");
    // BDCall's pieces (every host it draws into carries data-call-root) handle their own buttons.
    if (btn.closest("[data-call-root]")) return;
    switch (act) {
      case "call": openCall("call"); break;            // a tel: link: the dialer opens too (D14)
      case "log-menu": openLogMenu(btn); break;
      case "mail-out": S.asking = "email"; redrawAsk(); break;
      case "sms-out": S.asking = "sms"; redrawAsk(); break;
      case "log-sent": logSent(btn); break;
      case "log-sent-no": S.asking = null; redrawAsk(); focusOn("#cd-title"); break;
      case "snooze-undo": unsnooze(btn); break;
      case "step-change":
        editStep({ action: S.c.next_step || "", date: S.c.next_step_date || "", promised: !!(S.c.promised_date && S.c.promised_date === S.c.next_step_date) },
          '[data-act="step-change"]');
        break;
      case "step-clear": clearStep(btn); break;
      case "suggest": S.suggest = true; mountNext(); focusOn('[data-act="suggest-confirm"]'); break;
      case "suggest-cancel": S.suggest = false; mountNext(); focusOn('[data-act="suggest"]', "#cd-next-h"); break;
      case "suggest-confirm": confirmSuggestion(btn); break;
      case "suggest-change": {
        var sug = cadenceSuggestion();
        if (sug) editStep({ action: sug.action, date: sug.date, promised: false }, '[data-act="suggest"]');
        break;
      }
      case "note-save": saveNote(btn); break;
      case "note-cancel": S.composing = false; redrawComposer("cd-note"); break;
      case "more-history": showMore(); break;
      case "transcript": toggleTranscript(btn); break;
      case "confirm-toggle": toggleConfirm(btn); break;
      case "edit": openEdit(btn, "details"); break;
      case "cadence": openEdit(btn, "cadence"); break;
      case "archive": archive(); break;
      case "restore": restore(btn); break;
      case "dup-clear": clearDuplicate(btn); break;
      case "entry-edit": editEntry(Number(btn.getAttribute("data-entry"))); break;
      case "entry-cancel": cancelEntry(Number(btn.getAttribute("data-entry"))); break;
      case "entry-save": saveEntry(btn, Number(btn.getAttribute("data-entry"))); break;
      case "entry-delete": deleteEntry(Number(btn.getAttribute("data-entry"))); break;
      case "retry": location.reload(); break;
      default: break;
    }
  }

  function redrawAsk() {
    var slot = $("cd-ask-slot");
    if (slot) slot.innerHTML = askHtml();
  }

  function wire() {
    root.addEventListener("click", onClick);
    root.addEventListener("bd-menu", onMenu);
    root.addEventListener("focusin", function (e) {
      if (e.target && e.target.id === "cd-note" && !S.composing) {
        var typed = e.target.value;
        S.composing = true;
        redrawComposer("cd-note-text");
        if (typed) $("cd-note-text").value = typed;
      }
    });
    root.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && e.target && e.target.id === "cd-entry-text" && S.editing != null) {
        e.preventDefault();
        cancelEntry(S.editing);
        return;
      }
      if (e.key === "Escape" && e.target && e.target.id === "cd-note-text" && !e.target.value.trim()) {
        S.composing = false;
        redrawComposer("cd-note");
      }
    });
    if (window.matchMedia) {
      var mq = window.matchMedia(WIDE);
      var on = function () { syncFold(); };
      if (mq.addEventListener) mq.addEventListener("change", on); else if (mq.addListener) mq.addListener(on);
    }
  }

  // ── start ──────────────────────────────────────────────────────────────────────────────────
  /** /api/bd/me did not answer ok (no BD login, a turned-off one, BD off, no network): the server's
   *  own sentence, in TWAuth.bdFailure's words, and no data. */
  function renderRefused(res) {
    document.title = "Contact · BD CRM · Treadwell";
    root.removeAttribute("aria-busy");
    root.innerHTML = '<div class="error-box" role="alert"><p>' +
      esc(window.TWAuth.bdFailure(res && res.status, res && res.body).message) + "</p></div>";
  }

  /** What this person may do, from /api/bd/me's can (bd/auth.py can()). */
  function readCan(can) {
    var c = can || {};
    S.canSend = c.send === true;
    S.canEdit = c.edit_contact === true;
    S.canNote = S.canEdit;
    S.canNrp = S.canEdit;
    S.canClearDup = c.clear_duplicate === true;
    S.canAdd = c.add_contact === true;
    S.canFreq = c.cadence === true;
    S.cadenceOnly = S.canFreq && !S.canEdit;
    S.seeScore = c.pick_owner === true && !S.canEdit;
    S.canManage = c.manage_entries === true;
    S.canWeek = c.week === true;
  }

  root = $("cd-root");
  var auth = window.TWAuth;
  if (!root || !auth || !auth.ready || typeof auth.bdMe !== "function" || typeof auth.bdFailure !== "function") return;
  auth.ready.then(function () { return auth.bdMe(); }).then(function (res) {
    var ok = res && res.status >= 200 && res.status < 300 && res.body && res.body.ok;
    if (!ok) { renderRefused(res); return null; }
    var me = res.body;
    S.me = me;
    S.today = me.today || BD.bizToday();
    if (window.BDCall && typeof window.BDCall.setMe === "function") window.BDCall.setMe(me);
    readCan(me.can);
    wire();
    S.id = String(BD.qs("id") || "");
    if (!/^\d+$/.test(S.id)) { renderNotFound(); return null; }
    return Promise.all([
      Api.get("/api/bd/settings").then(function (r) { return r.settings; }, function () { return null; }),
      fetchContact(),
    ]).then(function (r) {
      S.settings = r[0];
      render();
      return loadOthers().then(redrawOthers);
    }, function (e) {
      if (e && e.status === 404) renderNotFound(); else renderError(e);
    });
  }).catch(renderError);
})();
