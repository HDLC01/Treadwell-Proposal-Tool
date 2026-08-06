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
    not_viewed: "Not opened yet",
    next_steps: "After they open it",
    second_nudge: "Second reminder",
    checkin: "Recurring check-in",
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
      // The server owns what each email is called, because its refusal messages quote those names.
      if (j.labels && typeof j.labels === "object") {
        Object.keys(LABELS).forEach(function (k) {
          if (j.labels[k]) LABELS[k] = j.labels[k];
        });
      }
      $("loading").hidden = true;
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

  function hourOptions() {
    var out = "";
    for (var h = 0; h < 24; h++) {
      var label = h === 0 ? "midnight" : h === 12 ? "noon"
        : (h % 12 === 0 ? 12 : h % 12) + (h < 12 ? "am" : "pm");
      out += '<option value="' + h + '">' + label + "</option>";
    }
    return out;
  }

  function fillNumbers() {
    $("first").value = CFG.first_nudge_hours;
    $("second").value = CFG.second_nudge_hours;
    $("recurring").value = CFG.recurring_hours;
    $("staff").value = CFG.staff_personal_hours;
    $("maxrec").value = CFG.max_recurring;
    if (!$("startH").options.length) {
      $("startH").innerHTML = hourOptions();
      $("endH").innerHTML = hourOptions();
    }
    $("startH").value = String(CFG.send_start_hour);
    $("endH").value = String(CFG.send_end_hour);
  }

  function paintTabs() {
    $("tabs").innerHTML = Object.keys(LABELS).map(function (k) {
      return '<button type="button" role="tab" data-key="' + k + '" aria-selected="' +
             (k === KEY) + '">' + esc(LABELS[k]) + "</button>";
    }).join("");
    $("tokens").innerHTML = TOKENS.map(function (t) {
      var why = t === "{need}"
        ? "your signed approval — and the deposit, when the job has one"
        : t === "{link}" ? "the button back to the proposal (required)"
        : t === "{first_name}" ? "the customer's first name" : "the project name";
      return '<button type="button" class="tok" data-tok="' + esc(t) + '" title="' + esc(why) +
             '">' + esc(t) + "</button>";
    }).join("");
  }

  function fillTemplate() {
    var t = (CFG.templates || {})[KEY] || {};
    $("t-subject").value = t.subject || "";
    $("t-title").value = t.title || "";
    $("t-body").value = t.body || "";
    $("t-cta").value = t.cta || "";
  }

  function collect() {
    var t = (CFG.templates || {})[KEY] || {};
    t.subject = $("t-subject").value;
    t.title = $("t-title").value;
    t.body = $("t-body").value;
    t.cta = $("t-cta").value;
    CFG.templates = CFG.templates || {};
    CFG.templates[KEY] = t;
    return {
      first_nudge_hours: $("first").value,
      second_nudge_hours: $("second").value,
      recurring_hours: $("recurring").value,
      staff_personal_hours: $("staff").value,
      max_recurring: $("maxrec").value,
      send_start_hour: $("startH").value,
      send_end_hour: $("endH").value,
      templates: CFG.templates,
    };
  }

  // ── preview ────────────────────────────────────────────────────────────────
  function renderPreview(pv) {
    if (!pv) return;
    $("pv-subject").textContent = pv.subject || "(no subject)";
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

  $("tokens").addEventListener("click", function (e) {
    var b = e.target.closest("[data-tok]");
    if (!b) return;
    // Insert at the caret rather than appending: somebody clicking {first_name} means "here".
    var ta = $("t-body");
    var tok = b.getAttribute("data-tok");
    var at = ta.selectionStart == null ? ta.value.length : ta.selectionStart;
    var end = ta.selectionEnd == null ? at : ta.selectionEnd;
    ta.value = ta.value.slice(0, at) + tok + ta.value.slice(end);
    ta.focus();
    ta.setSelectionRange(at + tok.length, at + tok.length);
    schedulePreview();
  });

  ["t-subject", "t-title", "t-body", "t-cta"].forEach(function (id) {
    $(id).addEventListener("input", schedulePreview);
  });
  // Typing clears a stale "Saved."/error line — but NOT the read-failed warning, which explains
  // why Save is greyed out. Losing it on the first keystroke would leave a dead button and no
  // reason given.
  var clearUnlessLocked = function () { if (!locked) say(""); };
  ["first", "second", "recurring", "staff", "maxrec"].forEach(function (id) {
    $(id).addEventListener("input", clearUnlessLocked);
  });
  ["startH", "endH"].forEach(function (id) {
    $(id).addEventListener("change", clearUnlessLocked);
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
      title: "Back to the shipped cadence?",
      message: "Every timing and all four emails go back to how they were before anybody edited "
             + "them.",
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
      say("Back to the shipped cadence.", true);
    } catch (err) {
      say("Couldn't reset that: " + (err.message || "try again"));
    }
  });

  load();
})();
