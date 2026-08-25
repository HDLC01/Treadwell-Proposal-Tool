/* Verbal intake for the Polish beta — the estimator talks, the form fills in.
 *
 * Hanz, 2026-08-25: "the estimator talks or types what they have, a cheat sheet tells them what is
 * needed and how to say it, the AI fills what it can and asks ONCE for what is missing; if the
 * estimator does not have it, they carry on." Reaching the normal intake form stays OPTIONAL —
 * this panel sits above it and everything it fills is still editable underneath.
 *
 * DICTATION IS THE BROWSER'S, not a service. Hanz's choice: the Web Speech API needs no key and
 * costs nothing per minute. The trade is that it is Chrome/Brave/Edge only, and in Chrome the
 * audio goes to Google — which is why the panel says so out loud rather than in a tooltip, and
 * why the textarea is the primary control with the microphone as an accelerator. An estimator on
 * Firefox or Safari gets a box to type into and no broken button.
 *
 * THE ONE QUESTION IS A BUDGET, not a style choice. The route is rate-limited to three runs per
 * five minutes per project, the same limiter as every other AI button here — so a first pass plus
 * one re-ask already spends two of the three. That is why the re-ask appends to the same
 * transcript and runs once, rather than opening a conversation.
 *
 * WHAT THIS FILE DOES NOT DO: decide anything about money. The server drops any price flag it
 * cannot find a verbatim quote for (backend/verbal_intake.py), and this panel prints the quote
 * next to every flag it did apply, so the estimator can see what each one rests on. Flags the
 * server refused are listed as still-to-answer rather than quietly left off.
 */
(function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };

  // The names the panel prints. Kept here rather than read off the form's labels because two of
  // them are conditions, which have no <label> to borrow.
  var FIELD_LABELS = {
    project_name: "Project name", address: "Address", city: "City", state: "State",
    zip: "ZIP", contact_name: "Contact", contact_email: "Contact email", bid_date: "Bid date",
    local: "Local job", hard_bid: "Hard bid", prevailing_wage: "Prevailing wage",
    taxable: "Taxable", remodel_tax: "Remodel tax",
  };

  var Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
  var rec = null;
  var listening = false;
  var asked = false;          // the ONE follow-up has been put; see the note at the top

  function label(k) { return FIELD_LABELS[k] || k; }

  function say(msg, kind) {
    var box = $("verbal-msg");
    if (!box) return;
    box.textContent = msg || "";
    box.className = "vmsg" + (kind ? " " + kind : "");
    box.hidden = !msg;
  }

  function busy(on) {
    var go = $("verbal-go");
    if (go) { go.disabled = on; go.textContent = on ? "Reading…" : "Fill the form"; }
  }

  // ── dictation ──────────────────────────────────────────────────────────────
  function startDictation() {
    if (!Rec) return;
    var box = $("verbal-text");
    rec = new Rec();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";
    // Where the committed text ends and the interim guess begins. Without this the interim result
    // is re-appended on every fire and the box fills with the same half-sentence over and over.
    var settled = box.value ? box.value.replace(/\s*$/, "") + " " : "";
    rec.onresult = function (e) {
      var interim = "";
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var chunk = e.results[i][0].transcript;
        if (e.results[i].isFinal) settled += chunk.replace(/^\s+/, "") + " ";
        else interim += chunk;
      }
      box.value = settled + interim;
    };
    rec.onerror = function (e) {
      // "not-allowed" is the estimator declining the microphone, which is a choice rather than a
      // fault — the box still works, so say that instead of reporting an error.
      say(e && e.error === "not-allowed"
        ? "No microphone, no problem — type it in the box instead."
        : "Dictation stopped. You can keep typing.", "warn");
      stopDictation();
    };
    rec.onend = function () { if (listening) stopDictation(); };
    try { rec.start(); } catch (err) { return; }
    listening = true;
    paintMic();
  }

  function stopDictation() {
    listening = false;
    if (rec) { try { rec.stop(); } catch (err) { /* already stopped */ } }
    rec = null;
    paintMic();
  }

  function paintMic() {
    var b = $("verbal-mic");
    if (!b) return;
    b.className = "vmic" + (listening ? " on" : "");
    b.setAttribute("aria-pressed", listening ? "true" : "false");
    b.textContent = listening ? "Stop" : "Speak";
  }

  // ── the result ─────────────────────────────────────────────────────────────
  function renderResult(res, applied) {
    var out = $("verbal-out");
    if (!out) return;
    var html = "";

    if (applied.filled.length) {
      html += '<div class="vgroup"><h3>Filled in</h3><ul>' +
        applied.filled.map(function (k) {
          return "<li>" + esc(label(k)) + ": <b>" + esc(res.fields[k]) + "</b></li>";
        }).join("") + "</ul></div>";
    }

    if (applied.applied.length) {
      // EVERY flag prints the words it rests on. The server has already proved the estimator said
      // them; whether they MEAN what the flag claims is a judgement only a person can make, and
      // they can only make it if the sentence is on screen next to the switch.
      html += '<div class="vgroup"><h3>Switches set</h3><ul>' +
        applied.applied.map(function (k) {
          var c = res.conditions[k];
          return "<li>" + esc(label(k)) + " <b>" + (c.value ? "on" : "off") +
            '</b><span class="vq">because you said: “' + esc(c.quote) + '”</span></li>';
        }).join("") + "</ul></div>";
    }

    if ((res.unsupported || []).length) {
      html += '<div class="vgroup warn"><h3>Not set — you did not say</h3><ul>' +
        res.unsupported.map(function (k) {
          return "<li>" + esc(label(k)) + "</li>";
        }).join("") +
        "</ul><p>These change the price, so nothing was guessed. Set them yourself below.</p></div>";
    }

    var stillMissing = (res.missing || []).filter(function (k) {
      return (res.unsupported || []).indexOf(k) === -1;
    });
    if (stillMissing.length) {
      html += '<div class="vgroup"><h3>Still needed</h3><p>' +
        esc(stillMissing.map(label).join(", ")) + "</p></div>";
    }

    if (res.question && !asked) {
      html += '<div class="vgroup ask"><h3>One question</h3><p>' + esc(res.question) + "</p>" +
        '<textarea id="verbal-answer" rows="2" aria-label="Your answer"></textarea>' +
        '<button type="button" class="btn sm" id="verbal-answer-go">Add this and read again</button>' +
        "</div>";
    }

    out.innerHTML = html || '<div class="vgroup"><h3>Nothing to fill in</h3>' +
      "<p>Nothing in there matched an intake field. Try naming the job, the town and the bid " +
      "date.</p></div>";
    out.hidden = false;

    var answerGo = $("verbal-answer-go");
    if (answerGo) {
      answerGo.addEventListener("click", function () {
        var a = ($("verbal-answer") || {}).value || "";
        if (!a.trim()) return;
        // APPENDED to the same transcript and read once more. The follow-up is not a conversation:
        // three runs per five minutes means the second pass is usually the last one available, so
        // it carries everything rather than only the answer.
        var box = $("verbal-text");
        box.value = box.value.replace(/\s*$/, "") + "\n" + a.trim();
        asked = true;
        run();
      });
    }
  }

  // ── the run ────────────────────────────────────────────────────────────────
  async function run() {
    var box = $("verbal-text");
    var transcript = (box && box.value || "").trim();
    if (transcript.length < 20) {
      say("Say a bit more first — a name, a place, and when it is due.", "warn");
      return;
    }
    if (listening) stopDictation();
    say("");
    busy(true);
    try {
      // Awaited BEFORE the fetch, not alongside it. /api/default-notes shipped without this on
      // 2026-08-something and fired before the auth header existed, so brand-new projects silently
      // missed their boilerplate — a 401 that looked like a missing feature (PR #124).
      if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready;
      var headers = TW.authHeaders();
      headers["Content-Type"] = "application/json";
      var r = await fetch(TW.resolveApiBase() + "/api/polish/verbal-intake", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({ transcript: transcript }),
      });
      var j = await r.json().catch(function () { return {}; });
      if (!j.ok) {
        say(j.error || "That didn't come back. Please try again.", "warn");
        return;
      }
      var applied = (window.TWPolishIntake && window.TWPolishIntake.applyVerbal)
        ? window.TWPolishIntake.applyVerbal(j)
        : { filled: [], applied: [] };
      renderResult(j, applied);
    } catch (err) {
      say("Couldn't reach the server. " + (err && err.message ? err.message : ""), "warn");
    } finally {
      busy(false);
    }
  }

  function mount() {
    var panel = $("verbal");
    if (!panel) return;
    var mic = $("verbal-mic");
    if (Rec && mic) {
      mic.hidden = false;
      mic.addEventListener("click", function () {
        if (listening) stopDictation(); else startDictation();
      });
      paintMic();
    } else if (mic) {
      // Hidden rather than disabled, and the note explains it. A greyed-out microphone reads as
      // something broken; a box to type in with no microphone reads as the feature working.
      mic.hidden = true;
      var note = $("verbal-nomic");
      if (note) note.hidden = false;
    }
    var go = $("verbal-go");
    if (go) go.addEventListener("click", run);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }

  window.TWPolishVerbal = { run: run, renderResult: renderResult, label: label };
})();
