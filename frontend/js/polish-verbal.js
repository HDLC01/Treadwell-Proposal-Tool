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
 * cannot find a verbatim quote for (backend/verbal_intake.py), and this panel prints THE
 * TRANSCRIPT'S OWN WORDS AROUND that quote next to every flag it applied, so the estimator can see
 * what each one rests on. Flags the server refused are listed as still-to-answer rather than
 * quietly left off.
 *
 * WHY THE SURROUNDING WORDS AND NOT THE QUOTE. The quote was the MODEL'S crop, and a crop can say
 * the opposite of the sentence it came out of: a transcript reading "it is not a hard bid" contains
 * the words "a hard bid", which is a verbatim quote the server is right to accept as evidence that
 * those words were said. Printed alone beside "Hard bid on", it made the screen assert the reverse
 * of what the estimator told it. The server now sends `context` INSTEAD OF `quote` — up to eight
 * words either side of the match, raw out of the transcript — so the "not" is on screen next to the
 * switch and the human check actually works. Nothing here reads `quote` any more; it is gone.
 *
 * AND IT DOES NOT ARGUE WITH THE ESTIMATOR. A condition they corrected by hand comes back from
 * applyVerbal in `respected`, and is printed as left alone rather than flipped a second time.
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

  // The resting labels of the two buttons that run an extraction. Named once because busy() puts
  // them back, and a busy() that restored the wrong words would relabel a button mid-session.
  var GO_LABEL = "Fill the form";
  var ASK_LABEL = "Add this and read again";

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

  /** Both buttons that can start a run, not just the first one.
   *
   *  The follow-up button is rendered INTO #verbal-out and it is the button in front of the
   *  estimator when the second run is in flight, so leaving it live meant the one control they were
   *  looking at could spend the third of three rate-limited runs on a double click. */
  function busy(on) {
    var go = $("verbal-go");
    if (go) { go.disabled = on; go.textContent = on ? "Reading…" : GO_LABEL; }
    var askGo = $("verbal-answer-go");
    if (askGo) { askGo.disabled = on; askGo.textContent = on ? "Reading…" : ASK_LABEL; }
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
    try {
      rec.start();
    } catch (err) {
      // A DOMException here — as opposed to the async onerror above — means the browser refused
      // to even ATTEMPT dictation: no permission prompt ever appears, because there was nothing
      // to ask. The one seen in the wild is a Permissions-Policy that disallows `microphone` for
      // the page (nginx sets that header on this app, not this file — see CSP/headers ops notes),
      // which throws synchronously from .start() rather than firing onerror. Silently returning
      // here, as this used to, left the estimator staring at a mic button that does nothing: no
      // prompt, no message, no filled box, and no way to tell a policy block from a broken feature.
      say("This browser or site setting is blocking the microphone outright — no permission " +
        "prompt will appear. Type into the box instead, or try a different browser.", "warn");
      rec = null;
      return;
    }
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

  /** Where one sentence of the transcript ends and the next begins.
   *
   *  Crude on purpose — a full stop, bang or question mark, then whitespace, then a real character.
   *  It will break "Ridgeview Rd. Overland Park" in two, and that costs a line break in an excerpt
   *  nobody is quoting back. Missing a break costs the thing described in evidenceHtml.
   *
   *  The newline is safe as a marker: the server collapses every whitespace run in `context`, so
   *  one cannot already be in there. */
  function sentencesOf(text) {
    return String(text).replace(/([.!?])\s+(?=\S)/g, "$1\n").split("\n");
  }

  /** The words a price flag rests on, as the transcript said them.
   *
   *  `context` is the contract with backend/verbal_intake.py: a raw slice of the transcript — the
   *  matched words plus up to eight either side, starting and ending on a word, with only
   *  whitespace runs collapsed. It is the estimator's own capitals and punctuation, so it is
   *  ESCAPED. It is also what makes the flag checkable — see the note at the top of this file for
   *  the "not a hard bid" case that made the panel assert the opposite of what was said.
   *
   *  THE SENTENCE BREAK IS THE OTHER HALF OF THAT SAFEGUARD, and it is deliberately the display's
   *  job. The server's matcher requires consecutive tokens, which kills the mid-word match, but it
   *  cannot tell that "It is not local. Hard bid though." makes "not local hard bid" a legitimately
   *  consecutive run across a full stop — the words really are in that order. The backend leaves
   *  that to be judged by a person (their `_find_span` and
   *  test_a_quote_cannot_be_stitched_across_a_full_stop say so out loud), which only works if the
   *  boundary is impossible to skim past. So a multi-sentence excerpt is broken onto its own lines
   *  AND counted in words, rather than run together into one grey line where the full stop
   *  disappears.
   *
   *  There is NO `quote` fallback: the backend stopped sending one, on purpose. The last branch is
   *  for a malformed response only, and it says so in words rather than printing a pair of empty
   *  quote marks — which would read as "the estimator said nothing", the one thing the server has
   *  already proved false. */
  function evidenceHtml(c) {
    var ctx = String((c && c.context) || "").trim();
    if (!ctx) {
      return '<span class="vq">nothing came back to show for this one. Check it yourself.</span>';
    }
    var parts = sentencesOf(ctx);
    if (parts.length < 2) {
      return '<span class="vq">the transcript says: “…' + esc(ctx) + '…”</span>';
    }
    // Counted, not just broken: "2 sentences, so read both" is the instruction, and the line break
    // is what makes it followable. .vq is display:block, so the <br> costs no new CSS.
    return '<span class="vq">the transcript says — ' + parts.length + " sentences, so read " +
      (parts.length === 2 ? "both" : "them all") + ': “…' +
      parts.map(esc).join("<br>") + '…”</span>';
  }

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
      // they can only make it if the SENTENCE — not the model's crop of it — is on screen next to
      // the switch. There is no "because" here on purpose: this panel reports what was said, and
      // the estimator decides whether it is a reason.
      html += '<div class="vgroup"><h3>Switches set</h3><ul>' +
        applied.applied.map(function (k) {
          var c = (res.conditions || {})[k] || {};
          return "<li>" + esc(label(k)) + " <b>" + (c.value ? "on" : "off") +
            "</b>" + evidenceHtml(c) + "</li>";
        }).join("") + "</ul></div>";
    }

    if ((applied.respected || []).length) {
      // THE ESTIMATOR'S OWN FLIPS, LEFT ALONE. Reported rather than silently skipped: the words
      // still go on screen, because the point is to let them change their own mind on the evidence,
      // not to hide that the transcript disagrees with the switch.
      html += '<div class="vgroup"><h3>You set these yourself</h3><ul>' +
        applied.respected.map(function (k) {
          var c = (res.conditions || {})[k] || {};
          return "<li>" + esc(label(k)) + " — left as you set it. What you said reads as <b>" +
            (c.value ? "on" : "off") + "</b>." + evidenceHtml(c) + "</li>";
        }).join("") +
        "</ul><p>Yours wins. Change it below if those words change your mind.</p></div>";
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
        '<button type="button" class="btn sm" id="verbal-answer-go">' + esc(ASK_LABEL) +
        "</button></div>";
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
        : { filled: [], applied: [], respected: [] };
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
