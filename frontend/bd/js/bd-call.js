/* The BD CRM's after-a-call sheet, as window.BDCall (#807: BD's js/call.js, moved in with This Week).
 * /bd/ loads it after the BD shell (bd-api.js, bd-shared.js, bd-core.js) and before bd-week.js; the
 * contact page loads it too once that page moves. The apply plan, section 2.6; the artboard
 * CallPhone.dc.html.
 *
 * WHAT CHANGED IN THE MOVE. BD's own shell (BDAuth) is gone: the page hands this file what it read
 * from /api/bd/me with BDCall.setMe(me) (today, the BD role, whether it may send follow-ups), toasts
 * are BD.toast's, and every route is under /api/bd/. The recommendation and follow-up routes are not
 * built yet: they answer 503 "This part is not built yet (Phase 5).", and the sheet says that
 * sentence where BD's sheet says it today. Changing a call's outcome saves the outcome first; a 503
 * from the step that follows it is said without taking the saved outcome back.
 *
 * ONE sheet (div.sheet#call-sheet on <body>, opened with BD.sheet): a bottom sheet on a phone, a
 * 440px right drawer from 768px. "How did it go?" with four outcome tiles (Talked, Voicemail, No
 * answer, Wrong person; "It was a meeting" swaps in Meeting and Hosted event). A tile saves at
 * once; then the sheet shows the saved line, the note, the suggested next step (Usual rule / AI
 * suggestion / Your step: Change, Dismiss) and, after a voicemail or no answer, "Send a
 * follow-up?" Email | Text | Nothing with the draft shown and editable. Nothing is decided for the
 * person: the pinned red button confirms the step and sends the follow-up they picked.
 *
 *   BDCall.open({contact, task, mode, focusOutcome, startedAt, recommendation, missed, interaction,
 *                aiEnabled, canSend, onChange, logPast, returnFocus})
 *       logPast (the contact page's Log menu): a "Day" field (today or earlier) and, for a call,
 *       "Minutes (optional)" above the tiles, sent as occurred_at (noon Central for an earlier
 *       day) and duration_s, so a call or meeting can be logged after the fact.
 *       returnFocus(): where focus goes on close when a save redrew the opener away.
 *       mode "call" (default) | "meeting" | "nrp" (Wrong person picked) | "decide" (straight to
 *       the saved state for a recommendation and/or a missed call; `interaction` {kind, outcome,
 *       occurred_at} is optional and only names the call: "Voicemail on Mon, Nov 2").
 *       onChange({type: "saved" | "confirmed" | "closed", result}).
 *   BDCall.close(); BDCall.isOpen();
 *   BDCall.decide(el, {contact, recommendation, missed, interaction, aiEnabled, canSend, onChange,
 *                      size})
 *       the same decision in place (desktop tray, contact page) with its own Confirm and Send;
 *       size "lg" (the contact page's Next step card) draws the step at 22/700 with "(in a week)".
 *   BDCall.stepEditor(el, {action, date, promised, promisedLabel, today, onSave, onCancel,
 *                          actionLabel, dateLabel})   (the labels default to "Next step", "When")
 *       the one inline next-step editor; renders, never sends; returns {save()}.
 *   BDCall.followup(el, {interactionId, contact, canSend, onDone})
 *       Email | Text | Nothing with the draft and its own Send.
 *
 * Every node it draws inside a page carries data-call-root on its host, so a page's delegated
 * click handler can step aside (`if (e.target.closest("[data-call-root]")) return;`). No node in
 * it carries data-task. Routes (all in docs/api-contract.md): POST /api/bd/contacts/{id}/interactions,
 * GET /api/bd/contacts/{id}, PATCH /api/bd/interactions/{id}, PATCH /api/bd/contacts/{id},
 * POST /api/bd/interactions/{id}/recommend, POST /api/bd/recommendations/{id}/confirm | dismiss,
 * POST /api/bd/interactions/{id}/draft-followup | send-followup, POST /api/bd/tasks/{id}/not-right-person,
 * POST /api/bd/contacts/{id}/confirm.
 */
(function () {
  "use strict";

  var BD = window.BD, BDApi = window.BDApi;
  var esc = BD.esc;
  var icon = BD.icon;
  // What the page read from /api/bd/me (BDCall.setMe): {today, user: {role}, can: {send}}.
  var ME = null;
  function today() { return (ME && ME.today) || ""; }
  function role() { return ME && ME.user ? ME.user.role : null; }
  function canSendDefault() { return !!(ME && ME.can && ME.can.send === true); }
  function toast(msg, o) { return typeof BD.toast === "function" ? BD.toast(msg, o || {}) : null; }
  var seq = 0;
  function uid(p) { seq += 1; return "call-" + p + "-" + seq; }

  // ── words ────────────────────────────────────────────────────────────────────────────────
  var TILES = {
    answered: { label: "Talked", glyph: "phone", tone: "ok" },
    voicemail: { label: "Voicemail", glyph: "voicemail", tone: "info" },
    no_answer: { label: "No answer", glyph: "phone-missed", tone: "neutral" },
    wrong: { label: "Wrong person", glyph: "user-x", tone: "warn" },
    meeting: { label: "Meeting", glyph: "users", tone: "ok" },
    hosted: { label: "Hosted event", glyph: "flag", tone: "info" },
  };
  var CALL_TILES = ["answered", "voicemail", "no_answer", "wrong"];
  var MEETING_TILES = ["meeting", "hosted"];
  var TOUCH = { answered: true, meeting_set: true, meeting: true, hosted: true };
  var SAVED_WORD = { answered: "Talked", meeting_set: "Talked", voicemail: "Voicemail", no_answer: "No answer",
    meeting: "Meeting", hosted: "Hosted event" };
  var AFTER_WORD = { answered: "a live talk", meeting_set: "a live talk", voicemail: "a voicemail",
    no_answer: "no answer", meeting: "a meeting", hosted: "a hosted event" };

  function isMissed(o) { return o === "voicemail" || o === "no_answer"; }

  /** The tile key an Interaction stands for. */
  function outcomeOf(i) {
    if (!i) return null;
    if (i.kind === "voicemail") return "voicemail";
    if (i.kind === "meeting" || i.kind === "hosted") return i.kind;
    if (i.kind === "call") return i.outcome || null;
    return null;
  }

  function first(contact) { return BD.firstName(contact) || "They"; }
  function phoneText(c) { return c && c.phone ? BD.fmtPhone(c.phone) : ""; }
  function canText(c) { return !!(c && (c.phone_e164 || BD.e164(c.phone))); }

  /** "Wed, Nov 11 (in a week)"; the parenthesis only for a date still to come. */
  function dayWithRel(iso, t) {
    var d = BD.fmtDay(iso, t);
    var rel = BD.fmtRel(iso, t);
    return rel ? d + " (" + rel + ")" : d;
  }

  // ── the next-step editor (BDCall.stepEditor) ─────────────────────────────────────────────
  var CHIPS = [["week", "In a week"], ["month", "In a month"], ["3months", "In 3 months"], ["pick", "Pick a date"]];

  /** The one inline editor for a next step: "Next step", When (In a week / In a month / In 3
   *  months / Pick a date), "<Name> asked for this date", Save and Cancel. It renders into `el`
   *  and calls onSave({action, date, promised}) or onCancel(); it never sends anything itself.
   *  Returns {save()} (true when it saved) so a pinned button can save an open editor first. */
  function stepEditor(el, opts) {
    var o = opts || {};
    if (!el) return { save: function () { return true; } };
    var t = o.today || today();
    var st = { action: String(o.action || ""), date: String(o.date || ""), promised: !!o.promised, chip: null, err: "" };
    var ids = { a: uid("step"), w: uid("when"), d: uid("date") };
    el.setAttribute("data-call-root", "");

    function preview() {
      if (st.chip === "pick") return st.date && st.date !== o.date ? "New date: " + dayWithRel(st.date, t) : "Pick the day above.";
      if (st.chip) return "New date: " + BD.fmtDay(st.date, t);
      return st.date ? "Now: " + BD.fmtDay(st.date, t) : "Pick when.";
    }
    function draw() {
      var chips = CHIPS.map(function (c) {
        return '<button type="button" class="chip-filter" data-chip="' + c[0] + '" aria-pressed="' + (st.chip === c[0]) + '">' +
          esc(c[1]) + "</button>";
      }).join("");
      var min = /^\d{4}-\d{2}-\d{2}$/.test(t) ? ' min="' + esc(t) + '"' : "";
      el.innerHTML = '<div class="call-editor" data-editor>' +
        '<div class="field"><label for="' + ids.a + '">' + esc(o.actionLabel || "Next step") + "</label>" +
        '<input class="input" type="text" id="' + ids.a + '" data-field="recaction" maxlength="200" value="' + esc(st.action) + '" /></div>' +
        '<div class="field"><span class="label" id="' + ids.w + '">' + esc(o.dateLabel || "When") + "</span>" +
        '<div class="date-chips" role="group" aria-labelledby="' + ids.w + '">' + chips + "</div></div>" +
        '<div class="field"' + (st.chip === "pick" ? "" : " hidden") + '><label for="' + ids.d + '">Date</label>' +
        '<input class="input" type="date" id="' + ids.d + '" data-field="recdate" value="' + esc(st.chip === "pick" ? (st.date !== o.date ? st.date : "") : "") + '"' + min + " /></div>" +
        '<p class="call-editor-preview">' + esc(preview()) + "</p>" +
        '<label class="check"><input type="checkbox" data-field="recpromised"' + (st.promised ? " checked" : "") + " /> " +
        esc(o.promisedLabel || "They asked for this date") + "</label>" +
        (st.err ? '<p class="field-error" role="alert">' + esc(st.err) + "</p>" : "") +
        '<div class="wrap-row call-editor-acts"><button type="button" class="btn" data-act="rec-save">Save</button>' +
        '<button type="button" class="btn-link" data-act="rec-cancel">Cancel</button></div></div>';
    }
    function save() {
      var action = st.action.trim();
      if (!action) { st.err = "Say what to do next."; draw(); focus('[data-field="recaction"]'); return false; }
      if (!/^\d{4}-\d{2}-\d{2}$/.test(st.date)) { st.err = "Pick a date."; draw(); focus('[data-chip="pick"]'); return false; }
      if (t && st.date < t) { st.err = "Pick today or a later day."; draw(); focus('[data-field="recdate"]'); return false; }
      if (typeof o.onSave === "function") o.onSave({ action: action, date: st.date, promised: st.promised });
      return true;
    }
    function focus(sel) {
      var n = el.querySelector(sel);
      if (n) n.focus();
    }
    var onClick = function (e) {
      var chip = e.target.closest ? e.target.closest("[data-chip]") : null;
      if (chip && el.contains(chip)) {
        var k = chip.getAttribute("data-chip");
        st.chip = k; st.err = "";
        if (k === "pick") st.date = o.date && st.date === o.date ? "" : st.date;
        else st.date = BD.chipDate(k, t);
        if (k === "pick" && !st.date) st.date = "";
        draw();
        focus(k === "pick" ? '[data-field="recdate"]' : '[data-chip="' + k + '"]');
        // The redraw made the preview line anew, and a live region drawn with its words is often
        // not read out: the words go to BD's one live region instead.
        BD.announce(preview());
        return;
      }
      var b = e.target.closest ? e.target.closest("[data-act]") : null;
      if (!b || !el.contains(b)) return;
      var act = b.getAttribute("data-act");
      if (act === "rec-save") save();
      else if (act === "rec-cancel" && typeof o.onCancel === "function") o.onCancel();
    };
    var onInput = function (e) {
      var f = e.target.getAttribute && e.target.getAttribute("data-field");
      if (f === "recaction") st.action = e.target.value;
      else if (f === "recpromised") st.promised = !!e.target.checked;
      else if (f === "recdate") {
        st.date = e.target.value; st.err = "";
        var p = el.querySelector(".call-editor-preview");
        if (p) p.textContent = preview();
        BD.announce(preview());
      }
    };
    // One editor per element at a time: a redraw replaces the old one's listeners.
    if (el._bdEditorOff) el._bdEditorOff();
    el.addEventListener("click", onClick);
    el.addEventListener("input", onInput);
    el.addEventListener("change", onInput);
    el._bdEditorOff = function () {
      el.removeEventListener("click", onClick);
      el.removeEventListener("input", onInput);
      el.removeEventListener("change", onInput);
      el._bdEditorOff = null;
    };
    draw();
    focus('[data-field="recaction"]');
    return { save: save };
  }

  // ── one flow: the sheet, or a decision in place ──────────────────────────────────────────
  /** All the state of one after-a-call flow. `inline` = drawn into a page element (decide /
   *  followup): no tiles, no pinned bar, its own Confirm and Send buttons. */
  function Flow(o, inline) {
    this.o = o || {};
    this.inline = !!inline;
    this.contact = this.o.contact || {};
    this.task = this.o.task || null;
    this.today = today();
    this.ai = !!this.o.aiEnabled;
    this.canSend = this.o.canSend != null ? !!this.o.canSend : canSendDefault();
    this.mode = this.o.mode || "call";
    this.fuOnly = !!this.o.fuOnly;
    this.phase = "pick";               // pick (the tiles) | saved
    this.meetingMode = this.mode === "meeting";
    this.wrong = this.mode === "nrp";  // Wrong person picked (sent by the bar, or on close)
    this.busy = null;                  // the tile being saved
    this.err = "";                     // the tiles' failure line
    this.regrid = false;               // the tiles again, after "Change"
    this.iid = null;                   // the saved interaction's id
    this.at = null;                    // ...and when
    this.outcome = null;               // its tile key
    this.taskClosed = false;
    this.kept = null;                  // the contact's step before the first save (S15)
    this.note = ""; this.noteSaved = ""; this.noteOpen = false;
    this.nrpNote = "";
    this.meetingSet = false; this.meetingSetSaved = false; this.meetingDate = "";
    this.rec = null; this.recState = "none"; this.custom = null; this.aiBusy = false; this.aiMsg = "";
    this.fuOn = false; this.channel = null; this.drafts = {}; this.fuBusy = false; this.fuDone = null;
    this.fuErr = "";
    this.barBusy = false; this.barErr = ""; this.keepDraft = false;
    this.done = { rec: false, fu: false, nrp: false };
    this.sentWhat = null;              // "email" | "sms" after a send
    this.savedStep = null;             // {action, date} once confirmed
    this.editor = null;
    this.last = null;                  // the last API answer
    this.finished = false;             // the bar closed the sheet
    this.focusSel = null;
    this.logPast = !!this.o.logPast;   // Day and Minutes above the tiles (logged after the fact)
    this.logDay = this.today;
    this.logMin = "";
    this.whenErr = null;               // {field: "day" | "min", text}

    if (this.mode === "decide" || this.fuOnly) {
      var rec = this.o.recommendation || null;
      var missed = this.o.missed || null;
      var inter = this.o.interaction || null;
      this.phase = "saved";
      this.rec = rec;
      this.recState = rec ? "pending" : "none";
      this.iid = (missed && missed.interaction_id) || (rec && rec.interaction_id) || (inter && inter.id) || this.o.interactionId || null;
      this.at = (missed && missed.occurred_at) || (inter && inter.occurred_at) || null;
      this.outcome = outcomeOf(inter) || (missed ? "voicemail" : null);
      this.fuOn = !!(missed || this.fuOnly) && this.canSend;
    }
  }

  Flow.prototype.req = function (method, path, body) {
    var self = this;
    var p = method === "GET" ? BDApi.get(path) : (method === "PATCH" ? BDApi.patch(path, body) : BDApi.post(path, body));
    return p.then(function (r) { self.last = r; return r; });
  };

  /** The contact's step as it was before the first save, for S15 (a touch that becomes a
   *  non-touch gives it back). Asked for once, fresh, when the sheet opens (what the page holds
   *  may be older than the server's). */
  Flow.prototype.loadKept = function () {
    var c = this.contact, self = this;
    if (this.keptReady) return this.keptReady;
    if (c && c.id != null) {
      this.keptReady = BDApi.get(BDApi.path("contacts", c.id)).then(function (r) {
        var x = (r && r.contact) || {};
        self.kept = { next_step: x.next_step || null, next_step_date: x.next_step_date || null, promised_date: x.promised_date || null };
        ["email", "phone", "phone_e164", "title", "city"].forEach(function (k) { if (!self.contact[k] && x[k]) self.contact[k] = x[k]; });
      }, function () {
        self.kept = "next_step" in c ? { next_step: c.next_step || null, next_step_date: c.next_step_date || null,
          promised_date: c.promised_date || null } : null;
      });
    } else {
      this.keptReady = Promise.resolve();
    }
    return this.keptReady;
  };

  Flow.prototype.emit = function (type) {
    if (typeof this.o.onChange === "function") {
      try { this.o.onChange({ type: type, result: this.last }); } catch (e) { if (window.console) console.error(e); }
    }
  };

  // ── markup ───────────────────────────────────────────────────────────────────────────────
  Flow.prototype.tilesHTML = function () {
    var self = this;
    var keys = this.meetingMode ? MEETING_TILES : CALL_TILES;
    var current = this.wrong ? "wrong" : this.outcome === "meeting_set" ? "answered" : this.outcome;
    var tiles = keys.map(function (k) {
      var d = TILES[k];
      var pressed = self.phase === "saved" || self.wrong ? current === k : false;
      return '<button type="button" class="choice-tile call-tile' + (self.busy === k ? " is-busy" : "") + '" data-outcome="' + k + '"' +
        ' aria-pressed="' + pressed + '"' + (self.busy === k ? ' aria-busy="true"' : "") + ">" +
        '<span class="choice-ico" data-tone="' + d.tone + '">' + icon(d.glyph, 20) + "</span>" +
        '<span class="call-tile-label">' + esc(d.label) + "</span></button>";
    }).join("");
    return '<div class="choice-grid call-tiles" role="group" aria-label="Call outcome">' + tiles + "</div>" +
      (this.err ? '<p class="field-error call-err" role="alert">' + esc(this.err) + "</p>" : "");
  };

  Flow.prototype.headHTML = function () {
    var c = this.contact;
    var meta;
    if (this.mode === "decide" && this.at) {
      meta = (SAVED_WORD[this.outcome] || "Call") + " on " + BD.fmtDay(this.at, this.today);
    } else {
      var bits = [];
      if (phoneText(c)) bits.push(phoneText(c));
      if (this.o.startedAt && !this.logPast) bits.push(BD.fmtBizTime(this.o.startedAt));
      meta = bits.join(" · ");
    }
    var titled = this.phase === "saved" || this.wrong;
    var name = titled
      ? '<h2 class="who-name call-name" id="call-title">' + esc(c.name || "") + "</h2>"
      : '<span class="who-name call-name">' + esc(c.name || "") + "</span>";
    return '<div class="sheet-grab" aria-hidden="true"></div>' +
      '<div class="sheet-head call-head">' + BD.avatarHTML(c.name || "", "") +
      '<div class="who">' + name + (meta ? '<span class="who-sub call-meta">' + esc(meta) + "</span>" : "") + "</div>" +
      '<button type="button" class="btn btn-icon" data-act="close" aria-label="Close">' + icon("x", 20) + "</button></div>";
  };

  Flow.prototype.savedLineHTML = function () {
    if (this.wrong) {
      return '<div class="panel-warn call-saved" data-saved role="status">' + icon("user-x", 18) +
        '<span class="call-saved-text">Marked as needs confirming.</span>' +
        '<button type="button" class="btn-link" data-act="change-outcome" aria-label="Change the call outcome">Change</button></div>';
    }
    var word = SAVED_WORD[this.outcome] || "Saved";
    var text = "Saved as " + word + "." + (this.meetingSetSaved || this.outcome === "meeting_set" ? " Meeting set." : "") +
      (this.taskClosed ? " This one is done." : "");
    if (!this.task && !this.taskClosed) text = "Saved as " + word + ".";
    return '<div class="panel-ok call-saved" data-saved role="status">' + icon("check-circle", 18) +
      '<span class="call-saved-text">' + esc(text) + "</span>" +
      '<button type="button" class="btn-link" data-act="change-outcome" aria-label="Change the call outcome">Change</button></div>';
  };

  Flow.prototype.noteHTML = function () {
    var live = TOUCH[this.outcome];
    var id = uid("note");
    if (!live && !this.noteOpen) {
      return '<div class="call-block"><button type="button" class="btn-link" data-act="add-note">' + icon("plus", 16) + " Add a note</button></div>";
    }
    var ai = "";
    if (this.ai) {
      var has = !!this.note.trim();
      ai = '<div class="wrap-row call-ai">' +
        '<button type="button" class="btn-link" data-act="suggest-ai"' + (has && !this.aiBusy ? "" : " disabled") + ">" +
        icon("lightbulb", 16) + " Suggest from my note</button>" +
        '<span class="call-hint" data-ai-hint>' + esc(this.aiBusy ? "Getting a suggestion..." : (has ? this.aiMsg : "Write a note first.")) + "</span></div>";
    }
    var meeting = "";
    if (this.outcome === "answered" || this.outcome === "meeting_set") {
      var did = uid("mdate");
      meeting = '<label class="check call-check"><input type="checkbox" data-field="meeting-set"' + (this.meetingSet ? " checked" : "") + " /> We set a meeting</label>" +
        (this.meetingSet ? '<div class="field"><label for="' + did + '">Meeting date</label>' +
          '<input class="input" type="date" id="' + did + '" data-field="meeting-date" value="' + esc(this.meetingDate) + '"' +
          (this.today ? ' min="' + esc(this.today) + '"' : "") + " /></div>" : "");
    }
    return '<div class="call-block call-note">' +
      '<div class="field"><label for="' + id + '">What did you talk about? <span class="opt">(optional)</span></label>' +
      '<textarea class="textarea" id="' + id + '" data-field="note" rows="3" placeholder="A line or two. It helps the next suggestion.">' +
      esc(this.note) + "</textarea></div>" + ai + meeting + "</div>";
  };

  Flow.prototype.recHTML = function () {
    var r = this.rec, c = this.contact;
    var hid = uid("rec");
    if (this.recState === "none") return "";
    if (this.recState === "dismissed") {
      return '<section class="panel call-rec" data-rec aria-label="Next step">' +
        '<p class="call-rec-title">No next step for now.</p>' +
        '<p class="call-rec-why">' + esc(first(c) + " can come up again on a later Friday.") + "</p>" +
        '<div class="wrap-row call-rec-acts"><button type="button" class="btn-link" data-act="rec-undo">Undo</button></div></section>';
    }
    if (this.recState === "confirmed") {
      var s = this.savedStep || { action: r.action, date: r.due_date };
      return '<section class="panel-ok call-rec-done" data-rec role="status">' + icon("check-circle", 18) +
        "<span>" + esc("Next step saved: " + s.action + ", " + BD.fmtDay(s.date, this.today) + ".") + "</span></section>";
    }
    var tag, why = "";
    if (this.custom) { tag = BD.esc("Your step"); why = this.custom.promised ? first(c) + " asked for this date." : ""; }
    else if (r.source === "ai") { tag = null; why = this.inline && r.reason ? r.reason : "From your note."; }
    else { tag = BD.esc("Usual rule"); why = this.inline && r.reason ? r.reason : ""; }
    var pill = tag === null
      ? '<span class="pill pill-ai">' + icon("lightbulb", 14) + "AI suggestion</span>"
      : '<span class="pill pill-neutral">' + tag + "</span>";
    var action = this.custom ? this.custom.action : r.action;
    var date = this.custom ? this.custom.date : r.due_date;
    var head;
    if (this.inline) {
      var when = this.at ? "After " + (AFTER_WORD[this.outcome] || "a call") + " on " + BD.fmtDay(this.at, this.today) : "";
      head = '<div class="call-rec-head">' + pill + (when ? '<span class="call-rec-when">' + esc(when) + "</span>" : "") + "</div>";
    } else {
      head = '<div class="call-rec-head"><h3 class="call-rec-h" id="' + hid + '">Suggested next step</h3>' + pill + "</div>";
    }
    var body;
    if (this.recState === "editing") {
      body = '<div class="call-editor-slot" data-editor-slot></div>';
    } else {
      var acts = this.inline
        ? '<div class="wrap-row call-rec-acts">' +
          '<button type="button" class="btn" data-act="rec-confirm"' + (this.barBusy ? " disabled" : "") + ">" + icon("check", 18) + " Confirm</button>" +
          '<button type="button" class="btn btn-tertiary" data-act="rec-change">Change</button>' +
          '<button type="button" class="btn btn-tertiary" data-act="rec-dismiss">Dismiss</button></div>'
        : '<div class="wrap-row call-rec-acts"><button type="button" class="btn-link" data-act="rec-change">Change</button>' +
          '<button type="button" class="btn-link" data-act="rec-dismiss">Dismiss</button></div>';
      body = '<p class="call-rec-title">' + esc(action) + "</p>" +
        '<p class="call-rec-date">' + icon("calendar", 16) + "<span>" + esc(this.inline && this.o.size !== "lg" ? BD.fmtDay(date, this.today) : dayWithRel(date, this.today)) + "</span></p>" +
        (why ? '<p class="call-rec-why">' + esc(why) + "</p>" : "") +
        (this.inline && this.barErr ? '<p class="field-error" role="alert">' + esc(this.barErr) + "</p>" : "") + acts;
    }
    var cls = this.inline ? "call-decide-rec" : "panel call-rec";
    return '<section class="' + cls + '" data-rec' + (this.inline ? ' aria-label="Next step"' : ' aria-labelledby="' + hid + '"') + ">" + head + body + "</section>";
  };

  Flow.prototype.fuHTML = function () {
    if (!this.fuOn) return "";
    var c = this.contact, hid = uid("fu");
    var h = '<section class="call-fu" data-fu aria-labelledby="' + hid + '">' +
      '<h3 class="call-fu-title" id="' + hid + '">Send a follow-up? <span class="opt">(optional)</span></h3>';
    if (this.fuDone === "sent") {
      return h + '<p class="call-fu-done text-ok">' + icon("check-circle", 16) + " " + (this.sentWhat === "sms" ? "Text sent." : "Email sent.") + "</p></section>";
    }
    if (this.fuDone === "none") return h + '<p class="call-fu-none">No follow-up for this call.</p></section>';
    var ch = this.channel;
    var seg = '<div class="seg call-seg" role="group" aria-labelledby="' + hid + '">' +
      '<button type="button" data-act="fu-pick" data-ch="email" aria-pressed="' + (ch === "email") + '"' + (c.email ? "" : ' disabled title="No email on file"') + ">Email</button>" +
      '<button type="button" data-act="fu-pick" data-ch="sms" aria-pressed="' + (ch === "sms") + '"' + (canText(c) ? "" : ' disabled title="No phone number on file"') + ">Text</button>" +
      '<button type="button" data-act="fu-pick" data-ch="none" aria-pressed="' + (ch === "none") + '">Nothing</button></div>';
    h += seg;
    if (this.fuBusy) h += '<p class="call-hint" role="status">Getting the draft...</p>';
    if (this.fuErr) h += '<p class="field-error" role="alert">' + esc(this.fuErr) + "</p>";
    if (ch === "none") {
      h += '<p class="call-fu-none">No follow-up for this call.</p>';
    } else if (ch && this.drafts[ch]) {
      var d = this.drafts[ch];
      var sid = uid("subj"), bid = uid("body");
      var to = ch === "sms" ? (phoneText(c) || d.to) : d.to;
      h += '<div class="call-draft" data-draft>' +
        '<div class="wrap-row call-draft-tag">' +
        (d.source === "ai" ? '<span class="pill pill-ai">' + icon("lightbulb", 14) + "AI draft</span>" : '<span class="pill pill-neutral">Standard text</span>') +
        '<span class="call-hint">Read it before you send.</span></div>' +
        '<p class="call-draft-to"><span class="call-draft-to-k">To</span> <span class="call-draft-to-v">' + esc(to || "") + "</span></p>" +
        (ch === "email" ? '<div class="field"><label for="' + sid + '">Subject</label>' +
          '<input class="input" type="text" id="' + sid + '" data-field="fu-subject" value="' + esc(d.subject || "") + '" /></div>' : "") +
        '<div class="field"><label for="' + bid + '">Message</label>' +
        '<textarea class="textarea" id="' + bid + '" data-field="fu-body" rows="' + (ch === "email" ? 6 : 4) + '">' + esc(d.body || "") + "</textarea></div>" +
        '<p class="call-foot">' + esc("Logged on " + first(c) + "'s history. Does not count as a touch.") + "</p>" +
        (this.inline ? '<div class="wrap-row"><button type="button" class="btn" data-act="fu-send">' + icon(ch === "email" ? "mail" : "message", 18) +
          (ch === "email" ? " Send email" : " Send text") + "</button></div>" : "") +
        "</div>";
    }
    return h + "</section>";
  };

  Flow.prototype.nrpHTML = function () {
    var id = uid("nrp");
    var check = role() === "assistant" ? "" : "An assistant will check. ";
    var line = this.task ? check + "This counts as done this week." : (check || "It stays marked as needs confirming.");
    return '<div class="call-block call-nrp"><div class="field"><label for="' + id + '">Who is the right person? <span class="opt">(optional)</span></label>' +
      '<textarea class="textarea" id="' + id + '" data-field="nrp" rows="3" placeholder="A name, a title or a phone number">' + esc(this.nrpNote) + "</textarea></div>" +
      '<p class="call-nrp-note">' + esc(line.trim()) + "</p></div>";
  };

  Flow.prototype.barLabel = function () {
    if (this.wrong) return "Save";
    if (this.keepDraft) return "Close and keep the draft";
    var ch = this.fuOn && !this.done.fu ? this.channel : null;
    var send = ch === "email" ? "Send email" : (ch === "sms" ? "Send text" : null);
    var stepOpen = this.rec && !this.done.rec && (this.recState === "pending" || this.recState === "editing");
    if (stepOpen) return ch === "email" ? "Confirm and send email" : (ch === "sms" ? "Confirm and send text" : "Confirm next step");
    if (this.recState === "dismissed") return send || "Save without a next step";
    return send || (this.done.rec ? "Close" : "Save");
  };

  /** Day and Minutes, for a call or meeting logged after the fact (logPast only). */
  Flow.prototype.whenHTML = function () {
    if (!this.logPast) return "";
    var e = this.whenErr || {};
    var max = /^\d{4}-\d{2}-\d{2}$/.test(this.today) ? ' max="' + esc(this.today) + '"' : "";
    var err = function (f) {
      return e.field === f ? ' aria-invalid="true" aria-describedby="call-' + f + '-err"' : "";
    };
    var msg = function (f) {
      return e.field === f ? '<p class="field-error" id="call-' + f + '-err" role="alert">' + esc(e.text) + "</p>" : "";
    };
    return '<div class="call-when">' +
      '<div class="field"><label for="call-day">Day</label>' +
      '<input class="input" type="date" id="call-day" data-field="log-day" value="' + esc(this.logDay) + '"' + max + err("day") + " />" +
      msg("day") + "</div>" +
      (this.meetingMode ? "" : '<div class="field"><label for="call-min">Minutes (optional)</label>' +
        '<input class="input" type="number" id="call-min" data-field="log-min" min="0" max="600" step="1" inputmode="numeric" value="' +
        esc(this.logMin) + '"' + err("min") + " />" + msg("min") + "</div>") +
      "</div>";
  };

  /** occurred_at and duration_s for a logged call or meeting, or null (and whenErr set) when a
   *  field is wrong. Nothing extra when the sheet is not logging after the fact. */
  Flow.prototype.whenBody = function () {
    this.whenErr = null;
    if (!this.logPast || !this.today) return {};
    var out = {};
    var day = (this.logDay || "").trim() || this.today;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) { this.whenErr = { field: "day", text: "Pick a day." }; return null; }
    if (day > this.today) { this.whenErr = { field: "day", text: "Pick a day that has already happened." }; return null; }
    out.occurred_at = stampFor(day, this.today);
    var mins = String(this.logMin || "").trim();
    if (!this.meetingMode && mins !== "") {
      var n = Number(mins);
      if (!(n >= 0) || n > 600) { this.whenErr = { field: "min", text: "Use a number of minutes, 0 to 600." }; return null; }
      out.duration_s = Math.round(n * 60);
    }
    return out;
  };

  /** The whole sheet (the page-element variants are drawn by drawInline). */
  Flow.prototype.sheetHTML = function () {
    var showSaved = this.phase === "saved" || this.wrong;
    var body = "";
    if (!showSaved) {
      body = this.whenHTML() + '<h2 class="call-q" id="call-title">How did it go?</h2>' + this.tilesHTML() +
        '<div class="call-links"><button type="button" class="btn-link" data-act="meeting-mode">' +
        (this.meetingMode ? "Back to call outcomes" : "It was a meeting") + "</button>" +
        '<button type="button" class="btn btn-tertiary" data-act="not-now">Not now</button></div>';
      return this.headHTML() + '<div class="sheet-body call-body">' + body + "</div>";
    }
    if (this.mode !== "decide") {
      if (this.regrid) {
        body += '<div class="call-regrid">' + this.tilesHTML() +
          '<div class="call-links"><button type="button" class="btn-link" data-act="meeting-mode">' +
          (this.meetingMode ? "Back to call outcomes" : "It was a meeting") + "</button></div></div>";
      } else {
        body += this.savedLineHTML();
      }
    }
    if (this.wrong) {
      body += this.nrpHTML();
    } else {
      if (this.mode !== "decide") body += this.noteHTML();
      body += this.recHTML();
      body += this.fuHTML();
    }
    var bar = '<div class="sheet-bar call-bar">' +
      (this.barErr ? '<p class="field-error call-bar-err" role="alert">' + esc(this.barErr) + "</p>" : "") +
      '<button type="button" class="btn btn-primary btn-block' + (this.barBusy ? " is-busy" : "") + '" data-act="rec-confirm"' +
      (this.barBusy ? ' aria-busy="true"' : "") + ">" + esc(this.barLabel()) + "</button></div>";
    return this.headHTML() + '<div class="sheet-body call-body">' + body + "</div>" + bar;
  };

  // ── the sheet element ────────────────────────────────────────────────────────────────────
  var sheetEl = null;
  var flow = null;

  function ensureSheet() {
    if (sheetEl) return sheetEl;
    sheetEl = document.createElement("div");
    sheetEl.className = "sheet call-sheet";
    sheetEl.id = "call-sheet";
    sheetEl.setAttribute("role", "dialog");
    sheetEl.setAttribute("aria-modal", "true");
    sheetEl.setAttribute("aria-labelledby", "call-title");
    sheetEl.hidden = true;
    document.body.appendChild(sheetEl);
    sheetEl.addEventListener("click", function (e) { if (flow && !flow.inline) onClick(flow, sheetEl, e); });
    sheetEl.addEventListener("input", function (e) { if (flow && !flow.inline) onInput(flow, sheetEl, e); });
    sheetEl.addEventListener("change", function (e) { if (flow && !flow.inline) onInput(flow, sheetEl, e); });
    return sheetEl;
  }

  function render(f, host) {
    if (f.inline) return drawInline(f, host);
    host.innerHTML = f.sheetHTML();
    host.classList.toggle("is-tall", f.phase === "saved" || f.wrong);
    mountEditor(f, host);
    placeFocus(f, host);
  }

  function placeFocus(f, host) {
    var sel = f.focusSel;
    f.focusSel = null;
    if (!sel) return;
    var n = host.querySelector(sel);
    if (n) { try { n.focus({ preventScroll: false }); } catch (e) { n.focus(); } }
  }

  function mountEditor(f, host) {
    var slot = host.querySelector("[data-editor-slot]");
    if (!slot) { f.editor = null; return; }
    var c = f.contact;
    var cur = f.custom || { action: f.rec.action, date: f.rec.due_date, promised: false };
    f.editor = stepEditor(slot, {
      action: cur.action, date: cur.date, promised: cur.promised,
      promisedLabel: first(c) + " asked for this date", today: f.today,
      onSave: function (v) {
        f.custom = v; f.recState = "pending"; f.editor = null;
        f.focusSel = '[data-act="rec-change"]';
        render(f, host);
      },
      onCancel: function () {
        f.recState = "pending"; f.editor = null;
        f.focusSel = '[data-act="rec-change"]';
        render(f, host);
      },
    });
  }

  // ── actions ──────────────────────────────────────────────────────────────────────────────
  function bodyFor(key, extra) {
    var b;
    if (key === "meeting" || key === "hosted") b = { kind: key };
    else if (key === "voicemail") b = { kind: "call", outcome: "voicemail" };
    else b = { kind: "call", outcome: key };
    Object.keys(extra || {}).forEach(function (k) { b[k] = extra[k]; });
    if ("duration_s" in b && b.kind !== "call") delete b.duration_s;
    return b;
  }

  /** An ISO timestamp with the Central offset: now for today, noon Central for an earlier day. */
  function stampFor(day, todayStr) {
    if (!day || day === todayStr) return BD.bizNowISO(todayStr);
    return BD.bizNowISO(day).replace(/T\d{2}:\d{2}:\d{2}/, "T12:00:00");
  }
  function patchFor(key) {
    if (key === "meeting" || key === "hosted") return { kind: key };
    if (key === "voicemail") return { kind: "voicemail", outcome: "voicemail" };
    return { kind: "call", outcome: key };
  }

  function pickTile(f, host, key) {
    if (f.busy) return;
    if (key === "wrong") {
      f.wrong = true; f.regrid = false; f.err = "";
      f.focusSel = '[data-field="nrp"]';
      render(f, host);
      return;
    }
    if (f.phase === "pick") {
      f.wrong = false;
      saveTile(f, host, key);
      return;
    }
    if (key === f.outcome && !f.wrong) { f.regrid = false; f.focusSel = '[data-act="change-outcome"]'; render(f, host); return; }
    f.wrong = false;
    changeTile(f, host, key);
  }

  function saveTile(f, host, key) {
    var c = f.contact;
    var when = f.whenBody();
    if (!when) {
      f.focusSel = f.whenErr.field === "day" ? "#call-day" : "#call-min";
      render(f, host);
      return;
    }
    f.busy = key; f.err = "";
    f.focusSel = '[data-outcome="' + key + '"]';
    render(f, host);
    f.loadKept().then(function () {
      return f.req("POST", BDApi.path("contacts", c.id, "interactions"), bodyFor(key, when));
    }).then(function (r) {
      var i = (r && r.interaction) || {};
      f.busy = null; f.regrid = false;
      f.phase = "saved";
      f.iid = i.id; f.at = i.occurred_at || null;
      f.outcome = outcomeOf(i) || key;
      f.taskClosed = !!(r && r.task);
      f.rec = (r && r.recommendation) || null;
      f.recState = f.rec ? "pending" : "none";
      f.fuOn = !!(r && r.missed_call) && f.canSend;
      f.focusSel = TOUCH[f.outcome] ? '[data-field="note"]' : '[data-act="change-outcome"]';
      render(f, host);
      f.emit("saved");
    }, function () {
      f.busy = null;
      f.err = "Not saved. No signal? Tap again.";
      f.focusSel = '[data-outcome="' + key + '"]';
      render(f, host);
    });
  }

  function changeTile(f, host, key) {
    var c = f.contact;
    var wasTouch = !!TOUCH[f.outcome], nowTouch = !!TOUCH[key];
    var hadRec = f.rec && (f.recState === "pending" || f.recState === "editing");
    f.busy = key; f.err = "";
    f.focusSel = '[data-outcome="' + key + '"]';
    render(f, host);
    var saved = function (r) {
      f.busy = null; f.regrid = false;
      f.outcome = key;
      f.meetingSet = false; f.meetingSetSaved = false;
      if (r && r.recommendation) { f.rec = r.recommendation; f.recState = "pending"; f.custom = null; }
      f.fuOn = isMissed(key) && f.canSend;
      if (!f.fuOn) { f.channel = null; }
      f.focusSel = '[data-act="change-outcome"]';
      render(f, host);
      f.emit("saved");
    };
    f.req("PATCH", BDApi.path("interactions", f.iid), patchFor(key)).then(function () {
      var k = f.kept;
      if (wasTouch && !nowTouch && k && (k.next_step || k.next_step_date || k.promised_date)) {
        return f.req("PATCH", BDApi.path("contacts", c.id), k);
      }
    }).then(function () {
      if (!hadRec) { saved(null); return; }
      // The outcome is saved. Swapping the suggested step is a second step, and its routes answer
      // 503 until they are built (#807): say so under the step, and keep the saved outcome.
      f.req("POST", BDApi.path("recommendations", f.rec.id, "dismiss"), {}).then(function () {
        return f.req("POST", BDApi.path("interactions", f.iid, "recommend"), {});
      }).then(saved, function (e) {
        f.barErr = (e && e.message) || "The next step was not changed. Try again.";
        saved(null);
      });
    }, function (e) {
      f.busy = null;
      f.err = (e && e.message) || "Not saved. No signal? Tap again.";
      render(f, host);
    });
  }

  function suggestAI(f, host) {
    var note = f.note.trim();
    if (!note || f.aiBusy) return;
    f.aiBusy = true; f.aiMsg = "";
    render(f, host);
    f.req("PATCH", BDApi.path("interactions", f.iid), { summary: note }).then(function () {
      f.noteSaved = note;
      return f.req("POST", BDApi.path("interactions", f.iid, "recommend"), {});
    }).then(function (r) {
      f.aiBusy = false;
      var rec = r && r.recommendation;
      if (rec) { f.rec = rec; f.recState = "pending"; f.custom = null; }
      f.aiMsg = rec && rec.source === "ai" ? "" : "No AI suggestion right now. The usual rule is shown.";
      f.focusSel = '[data-act="suggest-ai"]';
      render(f, host);
    }, function () {
      f.aiBusy = false;
      f.aiMsg = "No AI suggestion right now. The usual rule is shown.";
      render(f, host);
    });
  }

  function dismissRec(f, host, btn) {
    if (!f.rec || btn.disabled) return;
    btn.disabled = true;
    f.req("POST", BDApi.path("recommendations", f.rec.id, "dismiss"), {}).then(function () {
      f.recState = "dismissed"; f.custom = null;
      f.focusSel = '[data-act="rec-undo"]';
      render(f, host);
      if (f.inline) f.emit("confirmed");
    }, function (e) {
      btn.disabled = false;
      toast((e && e.message) || "Not saved. Try again.", { kind: "error" });
    });
  }

  function undoDismiss(f, host, btn) {
    if (!f.iid || btn.disabled) return;
    btn.disabled = true;
    f.req("POST", BDApi.path("interactions", f.iid, "recommend"), {}).then(function (r) {
      f.rec = (r && r.recommendation) || f.rec;
      f.recState = "pending"; f.custom = null;
      f.focusSel = '[data-act="rec-change"]';
      render(f, host);
    }, function (e) {
      btn.disabled = false;
      toast((e && e.message) || "Not saved. Try again.", { kind: "error" });
    });
  }

  function pickChannel(f, host, ch) {
    if (f.fuBusy) return;
    f.fuErr = "";
    if (f.channel === ch) { f.channel = null; f.focusSel = '[data-ch="' + ch + '"]'; render(f, host); return; }
    if (ch === "none" && f.inline) {
      f.fuBusy = true;
      f.req("POST", BDApi.path("interactions", f.iid, "send-followup"), { channel: "none" }).then(function () {
        f.fuBusy = false; f.fuDone = "none"; f.done.fu = true;
        render(f, host);
        f.emit("confirmed");
      }, function (e) {
        f.fuBusy = false; f.fuErr = (e && e.message) || "Not saved. Try again.";
        render(f, host);
      });
      return;
    }
    f.channel = ch;
    if (ch === "none" || f.drafts[ch]) {
      f.focusSel = ch === "none" ? '[data-ch="none"]' : '[data-field="fu-body"]';
      render(f, host);
      return;
    }
    f.fuBusy = true;
    render(f, host);
    f.req("POST", BDApi.path("interactions", f.iid, "draft-followup"), { channel: ch }).then(function (r) {
      f.fuBusy = false;
      var d = (r && r.draft) || {};
      f.drafts[ch] = { id: d.id, to: d.to, subject: d.subject || "", body: d.body || "", source: d.source };
      f.focusSel = '[data-ch="' + ch + '"]';
      render(f, host);
    }, function (e) {
      f.fuBusy = false; f.channel = null;
      f.fuErr = (e && e.message) || "No draft right now. Try again.";
      render(f, host);
    });
  }

  /** The send-followup body for the picked channel, or an error sentence. */
  function sendBody(f) {
    var ch = f.channel, d = f.drafts[ch];
    if (ch === "none") return { body: { channel: "none" } };
    if (!d) return { err: "Pick Email or Text again to load the draft." };
    if (!String(d.body || "").trim()) return { err: "The message is empty. Write something to send." };
    if (ch === "email" && !String(d.subject || "").trim()) return { err: "The email needs a subject." };
    var b = { draft_id: d.id, channel: ch, body: d.body };
    if (ch === "email") b.subject = d.subject;
    return { body: b };
  }

  /** The inline Send (decide / followup on a page). */
  function sendInline(f, host, btn) {
    var s = sendBody(f);
    if (s.err) { f.fuErr = s.err; render(f, host); return; }
    btn.classList.add("is-busy"); btn.setAttribute("aria-busy", "true");
    f.req("POST", BDApi.path("interactions", f.iid, "send-followup"), s.body).then(function () {
      f.sentWhat = f.channel; f.fuDone = "sent"; f.done.fu = true;
      render(f, host);
      toast(f.channel === "sms" ? "Text sent." : "Email sent.", { kind: "ok" });
      f.emit("confirmed");
    }, function (e) {
      f.fuErr = (e && e.message) || "Not sent. Try again.";
      render(f, host);
    });
  }

  /** The inline Confirm (decide on a page). */
  function confirmInline(f, host, btn) {
    if (!f.rec) return;
    if (f.recState === "editing" && f.editor && !f.editor.save()) return;
    var body = f.custom ? { action: f.custom.action, due_date: f.custom.date } : {};
    if (f.custom && f.custom.promised) body.promised = true;
    f.barBusy = true; f.barErr = "";
    if (btn) { btn.classList.add("is-busy"); btn.setAttribute("aria-busy", "true"); }
    f.req("POST", BDApi.path("recommendations", f.rec.id, "confirm"), body).then(function (r) {
      var saved = (r && r.recommendation) || {};
      f.barBusy = false; f.done.rec = true; f.recState = "confirmed";
      f.savedStep = { action: saved.action || body.action || f.rec.action, date: saved.due_date || body.due_date || f.rec.due_date };
      render(f, host);
      toast("Next step saved: " + f.savedStep.action + ", " + BD.fmtDay(f.savedStep.date, f.today) + ".", { kind: "ok" });
      f.emit("confirmed");
    }, function (e) {
      f.barBusy = false;
      f.barErr = (e && e.message) || "Not saved. Try again.";
      render(f, host);
    });
  }

  /** The pinned bar: note, meeting set, the step, the follow-up, Wrong person, in that order.
   *  Each step that worked is not repeated when the bar is pressed again after a failure. */
  function finish(f, host) {
    if (f.barBusy) return;
    if (f.keepDraft) { closeSheet("kept"); return; }
    if (!f.wrong && f.recState === "editing" && f.editor && !f.editor.save()) return;
    var c = f.contact;
    var fuPick = f.fuOn && !f.done.fu ? f.channel : null;
    var send = fuPick ? sendBody(f) : null;
    if (send && send.err) { f.barErr = send.err; render(f, host); return; }
    f.barBusy = true; f.barErr = "";
    render(f, host);
    var chain = Promise.resolve();
    var note = f.note.trim();
    if (f.iid && f.phase === "saved" && note !== f.noteSaved) {
      chain = chain.then(function () {
        return f.req("PATCH", BDApi.path("interactions", f.iid), { summary: note }).then(function () { f.noteSaved = note; });
      });
    }
    if (!f.wrong && f.iid && (f.outcome === "answered" || f.outcome === "meeting_set") && f.meetingSet !== f.meetingSetSaved) {
      chain = chain.then(function () {
        return f.req("PATCH", BDApi.path("interactions", f.iid), { kind: "call", outcome: f.meetingSet ? "meeting_set" : "answered" }).then(function () {
          f.meetingSetSaved = f.meetingSet;
          f.outcome = f.meetingSet ? "meeting_set" : "answered";
          if (f.meetingSet && f.meetingDate && !f.custom) {
            f.custom = { action: "Meeting with " + first(c), date: f.meetingDate, promised: false };
          }
        });
      });
    }
    if (!f.wrong && f.rec && !f.done.rec && (f.recState === "pending" || f.recState === "editing")) {
      chain = chain.then(function () {
        var body = f.custom ? { action: f.custom.action, due_date: f.custom.date } : {};
        if (f.custom && f.custom.promised) body.promised = true;
        return f.req("POST", BDApi.path("recommendations", f.rec.id, "confirm"), body).then(function (r) {
          var saved = (r && r.recommendation) || {};
          f.done.rec = true;
          f.savedStep = { action: saved.action || body.action || f.rec.action, date: saved.due_date || body.due_date || f.rec.due_date };
        });
      });
    }
    if (!f.wrong && fuPick) {
      chain = chain.then(function () {
        return f.req("POST", BDApi.path("interactions", f.iid, "send-followup"), send.body).then(function () {
          f.done.fu = true;
          f.fuDone = fuPick === "none" ? "none" : "sent";
          if (fuPick !== "none") f.sentWhat = fuPick;
        }, function (e) {
          if (e && e.status === 409 && fuPick !== "none") f.keepDraft = true;
          throw e;
        });
      });
    }
    if (f.wrong && !f.done.nrp) chain = chain.then(function () { return sendNotRight(f, f.nrpNote.trim()); });
    chain.then(function () {
      f.barBusy = false;
      f.finished = true;
      var msg;
      if (f.wrong) msg = "Marked as needs confirming.";
      else {
        var sent = f.sentWhat === "email" ? "Email sent." : (f.sentWhat === "sms" ? "Text sent." : "");
        if (f.done.rec && f.savedStep) {
          msg = sent ? "Next step saved. " + sent : "Next step saved: " + f.savedStep.action + ", " + BD.fmtDay(f.savedStep.date, f.today) + ".";
        } else {
          msg = sent ? "Saved. " + sent : (f.recState === "dismissed" ? "Saved. No next step." : "Saved.");
        }
      }
      closeSheet("done");
      toast(msg, { kind: "ok" });
      f.emit(f.wrong ? "saved" : "confirmed");
    }, function (e) {
      f.barBusy = false;
      f.barErr = (e && e.message) || "Not saved. No signal? Try again.";
      f.focusSel = '[data-act="rec-confirm"]';
      render(f, host);
    });
  }

  /** Wrong person: the task's not-right-person (closes it as done), or for someone not on this
   *  week's list the contact's confirm {confirmed: false} and the note as a note. */
  function sendNotRight(f, note) {
    var c = f.contact;
    var p;
    if (f.task && f.task.id != null) {
      p = f.req("POST", BDApi.path("tasks", f.task.id, "not-right-person"), note ? { note: note } : {});
    } else {
      p = f.req("POST", BDApi.path("contacts", c.id, "confirm"), { confirmed: false }).then(function (r) {
        if (!note) return r;
        return f.req("POST", BDApi.path("contacts", c.id, "interactions"), { kind: "note", summary: note });
      });
    }
    return p.then(function (r) { f.done.nrp = true; return r; });
  }

  // ── events (one set per host) ────────────────────────────────────────────────────────────
  function onClick(f, host, e) {
    var tile = e.target.closest ? e.target.closest("[data-outcome]") : null;
    if (tile && host.contains(tile)) { pickTile(f, host, tile.getAttribute("data-outcome")); return; }
    var b = e.target.closest ? e.target.closest("[data-act]") : null;
    if (!b || !host.contains(b)) return;
    if (b.closest("[data-editor]")) return;       // the step editor handles its own buttons
    var act = b.getAttribute("data-act");
    if (act === "close" || act === "not-now") { closeSheet(act); return; }
    if (act === "meeting-mode") {
      f.meetingMode = !f.meetingMode;
      f.focusSel = '[data-act="meeting-mode"]';
      render(f, host);
      return;
    }
    if (act === "change-outcome") {
      f.regrid = true;
      f.meetingMode = f.outcome === "meeting" || f.outcome === "hosted";
      f.focusSel = '[data-outcome]';
      render(f, host);
      return;
    }
    if (act === "add-note") { f.noteOpen = true; f.focusSel = '[data-field="note"]'; render(f, host); return; }
    if (act === "suggest-ai") { suggestAI(f, host); return; }
    if (act === "rec-change") { f.recState = "editing"; render(f, host); return; }
    if (act === "rec-dismiss") { dismissRec(f, host, b); return; }
    if (act === "rec-undo") { undoDismiss(f, host, b); return; }
    if (act === "fu-pick") { pickChannel(f, host, b.getAttribute("data-ch")); return; }
    if (act === "fu-send") { sendInline(f, host, b); return; }
    if (act === "rec-confirm") {
      if (f.inline) confirmInline(f, host, b);
      else finish(f, host);
    }
  }

  function onInput(f, host, e) {
    var el = e.target;
    var field = el.getAttribute ? el.getAttribute("data-field") : null;
    if (!field) return;
    if (field === "note") {
      f.note = el.value;
      var btn = host.querySelector('[data-act="suggest-ai"]');
      var hint = host.querySelector("[data-ai-hint]");
      var has = !!f.note.trim();
      if (btn) btn.disabled = !has || f.aiBusy;
      if (hint) hint.textContent = f.aiBusy ? "Getting a suggestion..." : (has ? f.aiMsg : "Write a note first.");
    } else if (field === "nrp") f.nrpNote = el.value;
    else if (field === "log-day") f.logDay = el.value;
    else if (field === "log-min") f.logMin = el.value;
    else if (field === "meeting-set" && e.type === "change") {
      f.meetingSet = !!el.checked;
      f.focusSel = '[data-field="' + (f.meetingSet ? "meeting-date" : "meeting-set") + '"]';
      render(f, host);
    } else if (field === "meeting-date") f.meetingDate = el.value;
    else if (field === "fu-subject" && f.drafts[f.channel]) f.drafts[f.channel].subject = el.value;
    else if (field === "fu-body" && f.drafts[f.channel]) f.drafts[f.channel].body = el.value;
  }

  // ── open / close ─────────────────────────────────────────────────────────────────────────
  var closingQuietly = false;

  function closeSheet(reason) {
    if (sheetEl && sheetEl._bdSheet) BD.sheet.close(sheetEl, reason || "close");
  }

  /** What closing the sheet means, by where the person was (the plan's D10, D16, S3a). */
  function onSheetClosed(f, reason) {
    if (closingQuietly || f.finished) return;
    if (f.mode === "decide") { f.emit("closed"); return; }
    if (f.phase === "pick" && !f.wrong) {
      toast("Nothing saved.");
      f.emit("closed");
      return;
    }
    if (f.wrong && !f.done.nrp) {
      sendNotRight(f, f.nrpNote.trim()).then(function () {
        toast("Marked as needs confirming.", { kind: "ok" });
        f.emit("saved");
      }, function (e) {
        toast((e && e.message) || "Not saved. Try again.", { kind: "error" });
        f.emit("closed");
      });
      return;
    }
    var note = f.note.trim();
    if (f.iid && note !== f.noteSaved) {
      f.req("PATCH", BDApi.path("interactions", f.iid), { summary: note }).then(function () { f.noteSaved = note; }, function () {});
    }
    var stepWaits = f.rec && !f.done.rec && (f.recState === "pending" || f.recState === "editing");
    var fuWaits = f.fuOn && !f.done.fu;
    if (stepWaits || fuWaits) {
      toast("Call saved. The next step waits in Next steps to confirm.", {
        ms: 8000,
        action: { label: "Show the sheet", onClick: function () { reopenDecide(f); } },
      });
    } else {
      toast("Call saved.", { kind: "ok" });
    }
    f.emit("closed");
    void reason;
  }

  function reopenDecide(f) {
    var stepWaits = f.rec && !f.done.rec && f.recState !== "dismissed" && f.recState !== "confirmed";
    var fuWaits = f.fuOn && !f.done.fu;
    open({
      contact: f.contact, task: f.task, mode: "decide",
      recommendation: stepWaits ? f.rec : null,
      missed: fuWaits ? { interaction_id: f.iid, occurred_at: f.at } : null,
      interaction: { id: f.iid, kind: f.outcome === "voicemail" ? "voicemail" : (f.outcome === "meeting" || f.outcome === "hosted" ? f.outcome : "call"),
        outcome: f.outcome, occurred_at: f.at },
      aiEnabled: f.ai, canSend: f.canSend, onChange: f.o.onChange,
    });
  }

  function open(opts) {
    var o = opts || {};
    if (!o.contact || o.contact.id == null) return;
    var el = ensureSheet();
    if (el._bdSheet) { closingQuietly = true; BD.sheet.close(el, "replace"); closingQuietly = false; }
    var f = new Flow(o, false);
    flow = f;
    if (f.mode !== "decide") f.loadKept();
    render(f, el);
    var firstFocus = f.phase === "pick" && !f.wrong
      ? el.querySelector(o.focusOutcome ? '[data-outcome="' + o.focusOutcome + '"]' : "[data-outcome]")
      : el.querySelector(f.wrong ? '[data-field="nrp"]' : '[data-act="close"]');
    BD.sheet.open(el, {
      initialFocus: firstFocus || null,
      returnFocus: typeof o.returnFocus === "function" ? o.returnFocus : null,
      onClose: function (reason) { if (flow === f) onSheetClosed(f, reason); },
    });
  }

  // ── in place: decide and followup ────────────────────────────────────────────────────────
  function drawInline(f, host) {
    var html = f.fuOnly ? f.fuHTML() : f.recHTML() + f.fuHTML();
    host.innerHTML = '<div class="call-decide' + (f.o.size === "lg" ? " call-decide-lg" : "") + '">' + (html || '<p class="call-hint">Nothing to decide here.</p>') + "</div>";
    mountEditor(f, host);
    placeFocus(f, host);
  }

  function attachInline(el, f) {
    el.setAttribute("data-call-root", "");
    el._bdCallFlow = f;
    if (el._bdCallWired) return;
    el._bdCallWired = true;
    el.addEventListener("click", function (e) { if (el._bdCallFlow) onClick(el._bdCallFlow, el, e); });
    el.addEventListener("input", function (e) { if (el._bdCallFlow) onInput(el._bdCallFlow, el, e); });
    el.addEventListener("change", function (e) { if (el._bdCallFlow) onInput(el._bdCallFlow, el, e); });
  }

  function decide(el, opts) {
    if (!el) return;
    var o = Object.assign({}, opts || {}, { mode: "decide" });
    var f = new Flow(o, true);
    attachInline(el, f);
    render(f, el);
  }

  function followup(el, opts) {
    if (!el) return;
    var o = opts || {};
    var f = new Flow({
      contact: o.contact, mode: "decide", fuOnly: true, interactionId: o.interactionId,
      missed: { interaction_id: o.interactionId, occurred_at: o.occurredAt || null },
      canSend: o.canSend,
      onChange: function (ev) { if (typeof o.onDone === "function") o.onDone(ev.result); },
    }, true);
    attachInline(el, f);
    render(f, el);
  }

  window.BDCall = {
    /** The page's /api/bd/me answer (its body): today, the BD role and the can() map. */
    setMe: function (me) { ME = me || null; },
    open: open,
    close: function () { closeSheet("close"); },
    isOpen: function () { return !!(sheetEl && sheetEl._bdSheet); },
    decide: decide,
    stepEditor: stepEditor,
    followup: followup,
  };
})();
