// Follow-up cadence editor — the chase schedule and the four customer emails.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHY THE PREVIEW IS THE POINT OF THIS PAGE.
//
// Everything edited here ends up in a CUSTOMER's inbox, and it repeats every few days until
// somebody notices. A form full of text boxes gives no feedback at all: an unfilled placeholder,
// a deleted button or a sentence that reads oddly in the letterhead are all invisible until a
// customer has it. So the right-hand side renders what they will actually receive, live, and the
// server does the rendering — the same code path the worker uses, so the preview cannot flatter
// the real thing.
//
// The validation rules live on the server too (followup_settings.py). This page deliberately does
// not re-implement them: two copies of "is this template usable" would drift, and the one that
// matters is the one that runs when the email goes out.
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var CFG = null;                 // the settings as last loaded or saved
  var KEY = "not_viewed";         // which email is open
  // Names to fall back on if the server does not send them. It does (`labels` on the GET), and its
  // copy is the one the refusal messages quote, so the two can never name the same email
  // differently — these are only here so the tabs are never blank.
  var LABELS = {
    sent: "Proposal sent",
    not_viewed: "Not opened yet",
    next_steps: "After they open it",
    second_nudge: "Second reminder",
    checkin: "Recurring check-in",
    deposit_nudge: "Deposit reminder",
  };
  // Fallback only — the portal serves these (editor_titles). Present so a failed or older GET
  // still shows which email is open rather than an empty heading.
  var EDITOR_TITLES = {
    sent: "Proposal sent — the first email, when you publish it",
    not_viewed: "First reminder — after not opening",
    next_steps: "Next steps — after they open it",
    second_nudge: "Second reminder — opened, still no decision",
    checkin: "Recurring check-in — repeats until they decide",
    deposit_nudge: "Deposit reminder — approved, deposit not yet in",
  };
  var TOKENS = ["{first_name}", "{project}", "{need}", "{link}"];

  // Every request waits for the bearer token in ONE place — the Bid Calendar shipped a 401 that
  // hid data because one fetch waited and its sibling did not.
  var api = async function (path, opts) {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    return fetch(TW.resolveApiBase() + path,
      Object.assign({}, opts || {}, { headers: TW.authHeaders((opts || {}).headers) }));
  };

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  };

  function say(msg, ok) {
    var el = $("alert");
    el.textContent = msg || "";
    el.className = "alert" + (ok ? " ok" : "");
  }

  // Who last changed this, and when. ONE function, because there are three ways the answer
  // changes — first load, a save, and a reset — and for a while only the first of them updated
  // the line. Saving then left "Never changed — this is the cadence as shipped" on screen
  // underneath the edit that had just been stored, which is precisely the question this line
  // exists to answer. Every response that can change it carries the same three fields.
  function showWhoChanged(j) {
    $("meta").textContent = j && j.read_failed
      ? "Can't read the saved cadence right now"
      : j && j.saved
        ? "Last changed " + (j.updated_at ? TW.fmtBizDate(j.updated_at) : "just now")
          + (j.updated_by ? " by " + j.updated_by : "")
        : "Never changed — this is the cadence as shipped";
  }

  // A read that FAILED must not be shown as a read that came back empty.
  //
  // Saving replaces the whole row — all five intervals, the send window and the wording of all
  // four emails. So if the page shows the shipped defaults after a failed read, says "never
  // changed", and lets somebody press Save, it overwrites wording that may have been written by
  // hand months ago, with no history to recover it from and that estimator's name on the change.
  // The only safe posture when we cannot see the current values is to refuse to write them.
  var locked = false;             // read failed: the form is editable but must not be saved

  function lockForFailedRead(failed) {
    locked = !!failed;
    $("save").disabled = failed;
    $("reset").disabled = failed;
    if (failed) {
      say("Couldn't read the saved cadence, so this shows the shipped defaults — which may not be "
        + "what is in use. Saving is off until it can be read, because it would replace the real "
        + "settings and all four email drafts. Try reloading in a minute.");
    }
  }

  // ── load ───────────────────────────────────────────────────────────────────
  async function load() {
    try {
      var r = await api("/api/followup-settings");
      var j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.detail || j.error || ("HTTP " + r.status));
      CFG = j.settings;
      if (Array.isArray(j.tokens) && j.tokens.length) TOKENS = j.tokens;
      // The server owns WHICH emails exist, what each is called, and the order they appear in.
      //
      // This used to walk the LOCAL keys and copy any label the server also had, which meant a
      // template the server knew about and this file did not could never grow a tab. That is not
      // hypothetical: it is exactly what happened to the "Proposal sent" email — the portal served
      // it, this list did not contain it, and the whole feature was unreachable on the page. Taking
      // the server's key set wholesale is what stops the next one repeating it.
      //
      // Safe because the portal asserts its LABELS cover exactly the editable templates, so every
      // tab this paints has a template behind it. The local map above is the fallback for a failed
      // or older GET, and nothing more.
      if (j.labels && typeof j.labels === "object") {
        var served = {};
        Object.keys(j.labels).forEach(function (k) {
          if (j.labels[k]) served[k] = j.labels[k];
        });
        if (Object.keys(served).length) LABELS = served;
      }
      // The open tab has to be one that exists. Otherwise a server that stopped serving
      // `not_viewed` would leave KEY pointing at nothing: no tab selected, and fillTemplate
      // writing into a template nobody can see.
      if (!LABELS[KEY]) KEY = Object.keys(LABELS)[0];

      // Longer when-it-fires wording for the heading under the tabs, same server-owns-it rule.
      if (j.editor_titles && typeof j.editor_titles === "object") {
        Object.keys(j.editor_titles).forEach(function (k) {
          if (j.editor_titles[k]) EDITOR_TITLES[k] = j.editor_titles[k];
        });
      }      $("loading").hidden = true;
      $("main").hidden = false;
      showWhoChanged(j);
      lockForFailedRead(!!j.read_failed);
      paintTabs();
      fillNumbers();
      fillTemplate();
      renderPreview(j.previews && j.previews[KEY]);
    } catch (err) {
      $("loading").textContent = "Couldn't load the cadence. " + (err.message || "");
    }
  }

  // ── days on screen, hours in the database ────────────────────────────────
  // Hanz, 2026-08-12: "Change the timing to Days instead of Hours". Hours is what the WORKER
  // reads (followup_rules compares against *_hours, and the bounds in followup_settings.py are
  // in hours), so converting the stored unit would mean touching the rules engine, the bounds,
  // the digest and every existing row. The unit people read is a presentation concern, so it is
  // converted here and nowhere else.
  //
  // Rounded, not floored: a stored 36 hours from before this change shows as 2 days rather than
  // 1, which is the nearer truth. Floor 1 day, because 0 would mean "chase instantly, for ever".
  function toDays(hours) { return Math.max(1, Math.round(Number(hours || 0) / 24)); }
  function toHours(days) { return Math.max(1, Math.round(Number(days || 0))) * 24; }

  function fillNumbers() {
    // The project-level subject lives here rather than in fillTemplate: it belongs to the
    // whole cadence, so switching tabs must not reload or clear it.
    $("thread-subject").value = CFG.thread_subject || "";
    $("first").value = toDays(CFG.first_nudge_hours);
    $("second").value = toDays(CFG.second_nudge_hours);
    $("recurring").value = toDays(CFG.recurring_hours);
    $("staff").value = toDays(CFG.staff_personal_hours);
    // NOT a duration — a count of reminders. It was always unitless and stays unitless.
    $("maxrec").value = CFG.max_recurring;
  }

  function paintTabs() {
    // In paintTabs rather than in the tab click handler: this runs on load AND on every switch,
    // so the heading cannot get out of step with the form under it.
    $("which-email").textContent = EDITOR_TITLES[KEY] || LABELS[KEY] || "";
    $("tabs").innerHTML = Object.keys(LABELS).map(function (k) {
      return '<button type="button" role="tab" data-key="' + k + '" aria-selected="' +
             (k === KEY) + '">' + esc(LABELS[k]) + "</button>";
    }).join("");
    $("tokens").innerHTML = TOKENS.map(function (t) {
      var why = t === "{need}"
        ? "your signed approval — and the deposit, when the job has one"
        : t === "{link}" ? "the button back to the proposal (required)"
        : t === "{first_name}" ? "the customer's first name" : "the project name";
      // draggable="true" because a <button> is not draggable by default. It has to be set HERE
      // rather than once on the container: paintTabs rebuilds this strip on every tab switch, so
      // anything hung on the chips themselves is gone by the second email you edit. The listeners
      // avoid the same trap by being delegated on #tokens, which survives.
      // The tooltip carries the HOW as well as the what. The sentence above the editor used to
      // say "Drag a placeholder into the message, or click one to drop it where the cursor is";
      // Hanz deleted it on 2026-08-12, and draggable="true" is invisible — so without this the
      // drag-and-drop is a feature nobody would find. Costs no page copy.
      return '<button type="button" class="tok" draggable="true" data-tok="' + esc(t) +
             '" title="' + esc(why) + ' — drag it in, or click to insert at the cursor' +
             '">' + esc(t) + "</button>";
    }).join("");
  }

  function fillTemplate() {
    var t = (CFG.templates || {})[KEY] || {};
    $("t-title").value = t.title || "";
    $("t-body").value = t.body || "";
    $("t-cta").value = t.cta || "";
  }

  function collect() {
    var t = (CFG.templates || {})[KEY] || {};
    t.title = $("t-title").value;
    t.body = $("t-body").value;
    t.cta = $("t-cta").value;
    CFG.templates = CFG.templates || {};
    CFG.templates[KEY] = t;
    return {
      first_nudge_hours: toHours($("first").value),
      second_nudge_hours: toHours($("second").value),
      recurring_hours: toHours($("recurring").value),
      staff_personal_hours: toHours($("staff").value),
      max_recurring: $("maxrec").value,
      // THE SEND WINDOW IS ROUND-TRIPPED, NOT OMITTED, and that is not a style choice.
      //
      // Hanz took the two hour selects off this page on 2026-08-10, but the window is still stored
      // and the sender still enforces it. Leaving these keys out of the payload would quietly
      // reset it. The PUT lands on the portal's /api/admin/settings/followups, which runs
      // followup_settings.validate() (portal main.py:1764), and validate() does
      // `_clamp_int(raw.get(field), field)` for EVERY field in DEFAULTS, where a missing key means
      // raw.get() is None and _clamp_int returns the DEFAULT. So a window somebody had set to
      // 9-17 would silently snap back to the shipped 8-18 the first time anybody edited an email.
      //
      // The near miss: followup_settings.merge() DOES skip absent keys (`if field in stored`), so
      // reading that function alone says omitting is safe. merge() is the read path. It never sees
      // this payload.
      //
      // CFG is whatever the GET returned, and it is replaced by the response on every save, so
      // these are the live stored values rather than a copy that can drift. A failed read cannot
      // send stale hours either: lockForFailedRead disables Save outright.
      send_start_hour: CFG.send_start_hour,
      send_end_hour: CFG.send_end_hour,
      // SENT EVERY TIME, for exactly the reason the send window above is. validate() runs
      // validate_thread_subject(raw.get("thread_subject")), and an absent key is None, which
      // that function treats as "cleared" and answers with the shipped wording. Omitting this
      // would silently reset a customised subject the first time anybody edited an email.
      thread_subject: $("thread-subject").value,
      templates: CFG.templates,
    };
  }

  // ── preview ────────────────────────────────────────────────────────────────
  function renderPreview(pv) {
    if (!pv) return;
    // The server no longer renders a per-template subject, because there is not one. Show the
    // project subject with the sample project filled in, which is what the customer will see.
    $("pv-subject").textContent =
      ($("thread-subject").value || "Your Treadwell proposal — {project}")
        .replace("{project}", "Westport Retail Center");
    // The server hands back the body with the CTA already rendered as "[ Label ]" — turn the
    // paragraphs into markup here and the button into a real one, so the preview reads like an
    // email rather than like a template.
    var html = String(pv.body || "").split(/\n{2,}/).map(function (block) {
      var b = block.trim();
      if (!b) return "";
      var m = b.match(/^\[\s*(.+?)\s*\]$/);
      if (m) return '<p><span class="pv-cta">' + esc(m[1]) + "</span></p>";
      return "<p>" + esc(b).replace(/\n/g, "<br>") + "</p>";
    }).join("");
    $("pv-body").innerHTML = html;
    $("pv").hidden = false;
    $("pv-bad").hidden = true;
  }

  function previewFailed(msg) {
    // A template that will not send has to say so HERE, next to the wording, not as a surprise
    // when Save is pressed.
    $("pv-bad").textContent = msg;
    $("pv-bad").hidden = false;
    $("pv").hidden = true;
  }

  var pvTimer = null;
  function schedulePreview() {
    if (pvTimer) clearTimeout(pvTimer);
    pvTimer = setTimeout(async function () {
      try {
        var r = await api("/api/followup-settings/preview", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ settings: collect() }) });
        var j = await r.json();
        if (!r.ok || j.ok === false) {
          previewFailed(j.detail || j.error || "This wording will not send.");
          return;
        }
        renderPreview(j.previews && j.previews[KEY]);
      } catch (err) {
        // A network blip must not make the wording look broken.
        say("Couldn't refresh the preview. " + (err.message || ""));
      }
    }, 450);
  }

  // ── events ─────────────────────────────────────────────────────────────────
  $("tabs").addEventListener("click", function (e) {
    var b = e.target.closest("[data-key]");
    if (!b) return;
    collect();                       // keep what was typed before switching away
    KEY = b.getAttribute("data-key");
    paintTabs();
    fillTemplate();
    schedulePreview();
  });

  // ── the token chips: drag one in, or click one ─────────────────────────────
  //
  // Hanz, 2026-08-10: "also make this a drag and drop bar instead of a brace". Dragging is the new
  // way in and it lands the token where you let go of it.
  //
  // CLICK STAYS, and not out of caution. A drag needs a pointer, so drag-only would put all four
  // placeholders out of reach of a keyboard and awkward on a touch screen. And {link} is not
  // optional decoration: the server refuses to save a body without it (followup_settings
  // validate_template), so an estimator who cannot insert a token cannot save the email at all.
  $("tokens").addEventListener("click", function (e) {
    var b = e.target.closest("[data-tok]");
    if (!b) return;
    // The caret, not the end of the box: clicking {first_name} means "here".
    var ta = $("t-body");
    insertToken(b.getAttribute("data-tok"), ta.selectionStart, ta.selectionEnd);
  });

  // Both ways in end here: a click hands over the caret, a drop hands over the point it
  // landed on.
  function insertToken(tok, at, end) {
    var ta = $("t-body");
    var lim = ta.value.length;
    var from = Math.max(0, Math.min(lim, at == null ? lim : at));
    var to = Math.max(from, Math.min(lim, end == null ? from : end));
    ta.value = ta.value.slice(0, from) + tok + ta.value.slice(to);
    ta.focus();
    ta.setSelectionRange(from + tok.length, from + tok.length);
    schedulePreview();
  }

  // Our own drag type. It is what lets the textarea tell one of these chips from every other thing
  // that can be dropped into it, which the drop handler below depends on completely.
  var TOK_MIME = "application/x-treadwell-token";

  var isTokenDrag = function (e) {
    var types = e.dataTransfer && e.dataTransfer.types;
    if (!types) return false;
    // types is a DOMStringList on older engines, so indexOf/includes are not safe to assume.
    for (var i = 0; i < types.length; i++) {
      if (String(types[i]).toLowerCase() === TOK_MIME) return true;
    }
    return false;
  };

  var carriesText = function (e) {
    var types = e.dataTransfer && e.dataTransfer.types;
    if (!types) return false;
    for (var i = 0; i < types.length; i++) {
      var t = String(types[i]).toLowerCase();
      if (t === "text/plain" || t === "text" || t === TOK_MIME) return true;
    }
    return false;
  };

  $("tokens").addEventListener("dragstart", function (e) {
    var b = e.target.closest("[data-tok]");
    if (!b || !e.dataTransfer) return;
    var tok = b.getAttribute("data-tok");
    // text/plain too, so a chip dragged into the subject line, the heading box, or out into any
    // other text field entirely, still deposits the token instead of nothing.
    e.dataTransfer.setData("text/plain", tok);
    e.dataTransfer.setData(TOK_MIME, tok);
    e.dataTransfer.effectAllowed = "copy";
  });

  // Where a drop landed, as an index into the textarea's value, or null if that cannot be worked
  // out honestly.
  //
  // A textarea is NOT a contenteditable, and the two APIs disagree about it badly enough that this
  // has to be checked rather than trusted. Measured in Chrome 151 against a known body of text:
  //
  //   document.caretPositionFromPoint  ->  offsetNode is the TEXTAREA itself (an element node) and
  //                                       offset is a real index into .value: 7, 17, 97, 103, 122
  //                                       and 140-of-140 all landed on the right character.
  //   document.caretRangeFromPoint     ->  startContainer is BODY, startOffset is 1. It does not
  //                                       resolve into the control at all.
  //
  // So the WebKit fallback, taken at face value, would have inserted every dragged token at
  // character 1 of the message, six words into "Hi {first_name}," and blamed on the drag. The
  // ownership test below is what catches that, and it is the reason this function returns null
  // instead of a number it cannot stand behind. A token one character out is a typo anybody can
  // fix; a token spliced into the middle of an unrelated sentence reads as the tool being broken.
  function dropOffset(ta, x, y) {
    var node = null, off = null;
    if (document.caretPositionFromPoint) {
      var pos = document.caretPositionFromPoint(x, y);
      if (pos) { node = pos.offsetNode; off = pos.offset; }
    } else if (document.caretRangeFromPoint) {
      var rng = document.caretRangeFromPoint(x, y);
      if (rng) { node = rng.startContainer; off = rng.startOffset; }
    }
    if (!node || typeof off !== "number" || off < 0) return null;
    if (!ownedBy(node, ta)) return null;                 // BODY/1, and anything else foreign
    // Two shapes are safe to read as a value index. The control itself, which is what the spec now
    // says a text control returns and what Chrome does. Or a text node holding the WHOLE value,
    // which is how an engine with anonymous content inside the control answers. The length test
    // is the point of it: an offset into one line of a value split across nodes is not an offset
    // into the value, and there is no way to add up the ones in front of it from here.
    if (node !== ta && !(node.nodeType === 3 && node.nodeValue != null
                         && node.nodeValue.length === ta.value.length)) return null;
    return off > ta.value.length ? null : off;
  }

  // ta.contains() answers false for the anonymous content inside a text control, so walk out by
  // hand. A ShadowRoot has no parentNode; it has a host.
  function ownedBy(node, ta) {
    for (var n = node; n; n = n.parentNode || n.host || null) {
      if (n === ta) return true;
    }
    return false;
  }

  var msg = $("t-body");
  var overDepth = 0;                  // see the dragleave handler

  msg.addEventListener("dragover", function (e) {
    // No preventDefault here and the drop event never fires at all, which is the single easiest way
    // to ship this looking finished and doing nothing.
    if (!carriesText(e)) return;      // a file dragged onto the page is not ours to accept
    e.preventDefault();
    if (e.dataTransfer && isTokenDrag(e)) e.dataTransfer.dropEffect = "copy";
  });

  msg.addEventListener("dragenter", function (e) {
    if (!isTokenDrag(e)) return;
    overDepth++;
    msg.classList.add("dropping");
  });

  msg.addEventListener("dragleave", function () {
    // Counted, not just removed. Dragging across a textarea sends leave/enter pairs as the pointer
    // crosses its own inner content, and a bare remove flickered the highlight off and on while
    // the pointer never left the box.
    if (--overDepth <= 0) { overDepth = 0; msg.classList.remove("dropping"); }
  });

  // Let go outside the textarea and the drop never fires, so the highlight would sit there lit up
  // over a box that received nothing.
  $("tokens").addEventListener("dragend", function () {
    overDepth = 0;
    msg.classList.remove("dropping");
  });

  msg.addEventListener("drop", function (e) {
    overDepth = 0;
    msg.classList.remove("dropping");
    // EVERY OTHER DROP IS LEFT TO THE BROWSER, on purpose. A textarea already inserts dropped text
    // at the drop point, and it knows two things this handler does not: a selection dragged from
    // inside this same box is a MOVE, so handling it here would leave the original behind and
    // paste a second copy, and text arriving from another application may carry a flavour we never
    // asked for. Not calling preventDefault is also what stops a token landing twice: the default
    // insert and ours both firing is the duplicate this guard exists to avoid.
    if (!isTokenDrag(e)) return;
    e.preventDefault();
    var tok = e.dataTransfer.getData(TOK_MIME) || e.dataTransfer.getData("text/plain") || "";
    if (!tok) return;
    var at = dropOffset(msg, e.clientX, e.clientY);
    // Nothing resolvable under the pointer: the caret is a wrong-but-predictable answer, and the
    // estimator can see where it is.
    if (at == null) at = msg.selectionStart == null ? msg.value.length : msg.selectionStart;
    insertToken(tok, at, at);
  });

  ["thread-subject", "t-title", "t-body", "t-cta"].forEach(function (id) {
    $(id).addEventListener("input", schedulePreview);
  });
  // Typing clears a stale "Saved."/error line — but NOT the read-failed warning, which explains
  // why Save is greyed out. Losing it on the first keystroke would leave a dead button and no
  // reason given.
  var clearUnlessLocked = function () { if (!locked) say(""); };
  ["first", "second", "recurring", "staff", "maxrec"].forEach(function (id) {
    $(id).addEventListener("input", clearUnlessLocked);
  });

  $("save").addEventListener("click", async function () {
    var btn = this;
    btn.disabled = true;
    say("");
    try {
      var payload = collect();
      var r = await api("/api/followup-settings", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: payload }) });
      var j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.detail || j.error || ("HTTP " + r.status));
      // Numbers get pulled into range on the way in, so the SAVED values are re-read into the
      // form. Somebody who typed 2 hours needs to see they got 4 rather than believe it stuck.
      var before = JSON.stringify([payload.first_nudge_hours, payload.second_nudge_hours,
                                   payload.recurring_hours, payload.staff_personal_hours,
                                   payload.max_recurring].map(Number));
      CFG = j.settings;
      fillNumbers();
      fillTemplate();
      renderPreview(j.previews && j.previews[KEY]);
      showWhoChanged(j);
      var after = JSON.stringify([CFG.first_nudge_hours, CFG.second_nudge_hours,
                                  CFG.recurring_hours, CFG.staff_personal_hours,
                                  CFG.max_recurring].map(Number));
      say(before === after ? "Saved."
        : "Saved — some numbers were outside the allowed range and have been adjusted.", true);
    } catch (err) {
      say("Couldn't save that: " + (err.message || "try again"));
    } finally {
      btn.disabled = false;
    }
  });

  $("reset").addEventListener("click", async function () {
    var ok = await TW.confirmDanger({
      title: "Reset to Default?",
      // The send window is named HERE because this dialog is now the only place it can be. A reset
      // PUTs an empty payload, so the server refills every field including send_start_hour and
      // send_end_hour, which has always been true. What changed on 2026-08-10 is that the card
      // showing those hours is gone, so a window somebody had set to 9-17 snaps back to 8-18 with
      // nothing on screen before or after to say it happened.
      message: "Every timing, the hours those emails may go out, and all four emails go back to "
             + "how they were before anybody edited them.",
      detail: "Proposals already being chased carry on — nothing is re-sent.",
      confirmText: "Reset cadence",
      tone: "warn",
    });
    if (!ok) return;
    // Saving an empty payload is how a reset is expressed: the server fills every field from the
    // shipped defaults, so there is no second definition of "default" on this side to drift.
    try {
      var r = await api("/api/followup-settings", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ settings: {} }) });
      var j = await r.json();
      if (!r.ok || j.ok === false) throw new Error(j.detail || j.error || ("HTTP " + r.status));
      CFG = j.settings;
      fillNumbers();
      fillTemplate();
      renderPreview(j.previews && j.previews[KEY]);
      showWhoChanged(j);      // a reset IS a change, and it is the newest one
      say("Reset to the default cadence.", true);
    } catch (err) {
      say("Couldn't reset that: " + (err.message || "try again"));
    }
  });

  load();
})();
