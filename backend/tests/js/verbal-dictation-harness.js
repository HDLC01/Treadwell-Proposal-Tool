"use strict";
/* startDictation — RUN against a microphone that refuses, rather than read.
 *
 * WHY EXECUTED. The bug being pinned here was a silent `return`. There is no assertion a
 * source-text test can make about silence: the old code parsed, linted and shipped, and the only
 * way to see the failure is to call the function with a recognizer that throws and look at whether
 * anything reached the screen.
 *
 * THE FAILURE. `rec.start()` can throw SYNCHRONOUSLY instead of firing the async `onerror` — which
 * is precisely what a Permissions-Policy of `microphone=()` does. The browser refuses to attempt
 * dictation at all, so no permission prompt appears and there is nothing for the estimator to
 * decline. The old `catch (err) { return; }` swallowed it, leaving a mic button that does nothing:
 * no prompt, no message, no text in the box, and no way to tell a blocked policy from a dead
 * feature. They reported it as "verbal intake not working", which is the only thing it could look
 * like from the outside.
 *
 * Note the two paths are DIFFERENT sentences on purpose, and case 3 holds that line. `onerror` with
 * "not-allowed" is a person choosing to decline, and gets the light "no microphone, no problem".
 * A synchronous throw is nobody's choice, so telling them to grant permission would send them
 * hunting a prompt that will never appear.
 *
 * Usage: node verbal-dictation-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "polish-verbal.js"), "utf8")
  .replace(/\r\n/g, "\n");

/** Lift a named function out of the panel's IIFE (two-space indent), braces balanced. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone from polish-verbal.js — rewrite this harness");
  const open = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

/** The two nodes these functions touch, by the ids frontend/polish-intake.html ships. */
function makeDom() {
  const nodes = {};
  return (id) => (nodes[id] = nodes[id] || {
    id, value: "", hidden: true, disabled: false, textContent: "", className: "",
  });
}

/** One run of startDictation against a recognizer of our choosing.
 *
 *  `behaviour` decides what the fake `.start()` does: "ok" resolves, "throw" raises the
 *  DOMException a blocking Permissions-Policy produces, and "none" removes the constructor
 *  altogether (an old browser). `say` and `paintMic` are the only leaves stubbed — startDictation
 *  and stopDictation are LIFTED and run for real, because the swallowed error lived in one of them.
 */
function run(behaviour, opts) {
  const $ = makeDom();
  $("verbal-text").value = (opts && opts.typed) || "";
  const said = [];
  const paints = [];
  const started = [];

  function FakeRec() {
    this.continuous = false; this.interimResults = false; this.lang = "";
    this.start = function () {
      started.push(1);
      if (behaviour === "throw") {
        const e = new Error("start failed");
        e.name = "NotAllowedError";       // what Chrome raises when the policy forbids the mic
        throw e;
      }
    };
    this.stop = function () { };
  }

  const scope = new Function("$", "Rec", "said", "paints", `
    "use strict";
    var rec = null;
    var listening = false;
    function paintMic() { paints.push(listening); }
    function say(msg, kind) { said.push({ msg: msg, kind: kind }); }
    ${fn("startDictation")}
    ${fn("stopDictation")}
    return {
      startDictation: startDictation,
      // Read AFTER the call, so a claim about "listening" is about the closure the page uses and
      // not about a copy taken before it ran.
      state: function () { return { listening: listening, recHeld: rec !== null }; },
      fireError: function (code) { if (rec && rec.onerror) rec.onerror({ error: code }); },
      fireResult: function (e) { if (rec && rec.onresult) rec.onresult(e); },
    };
  `)($, behaviour === "none" ? undefined : FakeRec, said, paints);

  scope.startDictation();
  return { scope, $, said, paints, started };
}

const out = {};

// ── 1. the mic is blocked outright: .start() throws ──────────────────────────
// The reported bug. Everything below the throw must NOT happen (no "listening", no held
// recognizer), and — the whole point — the estimator must be told, in words they can act on.
{
  const r = run("throw");
  out.blocked = {
    startAttempted: r.started.length,
    said: r.said,
    state: r.scope.state(),
    micPainted: r.paints.length,
  };
}

// ── 2. a working microphone is untouched by the new branch ──────────────────
// The catch must not cost the happy path anything: still listening, still painted, still silent.
{
  const r = run("ok", { typed: "twelve hundred square feet" });
  out.working = {
    said: r.said,
    state: r.scope.state(),
    micPainted: r.paints,
  };
}

// ── 3. declining a prompt keeps its own, gentler sentence ───────────────────
// A person choosing Block is not the same event as the browser refusing to ask, and the two must
// not collapse into one message — the advice differs (grant it vs. it will never be offered).
{
  const r = run("ok");
  r.scope.fireError("not-allowed");
  out.declined = {
    said: r.said,
    state: r.scope.state(),
  };
}

// ── 4. an old browser with no SpeechRecognition at all ──────────────────────
// Guards the guard: `if (!Rec) return` runs before any of this, so nothing is said and nothing
// throws. (The button is hidden in that case, which is why silence is right here and wrong in 1.)
{
  const r = run("none");
  out.noSupport = { said: r.said, startAttempted: r.started.length, state: r.scope.state() };
}

process.stdout.write(JSON.stringify(out) + "\n");
