// Lifts the cover-letter switch AND the payload line that reads it out of
// frontend/js/proposal-review.js, and drives both through a stub DOM and a faithful TW store.
//
// EXECUTED, NOT GREPPED, and this is the case that shows why. The whole cover-letter feature is
// now one boolean, and it travels in opposite directions on the same page: the box is PAINTED
// from the stored draft on load, and the draft is WRITTEN from the box on change. A source read
// sees both `TW.getState()` and `TW.setState` present and cannot tell which way round they are
// wired, cannot tell that `box.checked` is set rather than read, and — the failure this repo has
// actually paid for — cannot see an unbound identifier at all. On 2026-08-12 `STAGE_CREATED`
// shipped unbound with every source assertion green and took the production board down.
//
// AND THE SECOND HALF IS WHY A REGEX WAS NOT ENOUGH EITHER. On 2026-09-09 the payload line in
// `continueToDone` read `!!state.cover_letter_enabled` — a perfectly ordinary-looking line that
// passed every source assertion, including one that checked `cover_letter_enabled` appears inside
// the `proposal_payload` literal. It shipped the wrong VALUE: `state` is the module-top one-shot
// `TW.getState()` and the switch writes a top-level key, which `TW.setState` replaces on a freshly
// parsed object instead of mutating in place. Tick, press Continue, and the payload said `false`.
// So the payload expression is lifted VERBATIM and EVALUATED, in a scope holding the same three
// real bindings the browser gives it: the snapshot, `liveKey`, and the wired checkbox.
//
// WHAT IS AND IS NOT EXECUTED HERE. `continueToDone` is ~180 lines that read the form, the
// pricing rail, the sheet systems and the document overrides; lifting it whole would need most of
// the page. What runs instead is:
//   * the real `const state = TW.getState();` binding, at the real moment (before any tick);
//   * the real `liveKey` helper, verbatim;
//   * the real `wireCoverLetterSwitch` IIFE, verbatim, driven by a real `change` event;
//   * the real `cover_letter_enabled: …` line from `continueToDone`'s `proposal_payload`
//     literal, verbatim, evaluated in that scope.
// What does NOT run: everything else in that literal and everything around it. So this cannot
// catch the key being deleted from the literal or the literal moving out of `proposal_payload` —
// test_the_fields_ride_the_frozen_payload_and_not_merely_the_request is the guard for that, and
// the lift below refuses loudly rather than silently if the line stops being findable.
//
// WHY IT IS SAFE TO LIFT THESE. The rule in this repo is that lifting out of proposal-review.js
// is fragile, because a lifted function whose body grows a call to a NEW free identifier dies
// with a ReferenceError and takes every scenario with it. That risk is the reason these are good
// candidates rather than bad ones: between them they touch `document`, `TW`, `state` and
// `liveKey`, and every one is bound below. If they grow a fifth dependency this harness fails
// with the name of what it could not find, which is the report we want.
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..", "..");
const SRC = fs.readFileSync(
  path.join(ROOT, "frontend", "js", "proposal-review.js"), "utf8");

function gone(what, why) {
  throw new Error(what + " could not be lifted out of proposal-review.js. " + why);
}

/** Brace-balance forward from `startIndex`, returning the text up to the matching close. */
function balanced(startIndex, open, close) {
  let depth = 1;
  for (let j = startIndex; j < SRC.length; j++) {
    if (SRC[j] === open) depth++;
    else if (SRC[j] === close) {
      depth--;
      if (depth === 0) return SRC.slice(startIndex, j);
    }
  }
  return "";
}

/** The body of `(function NAME() { ... })();`. */
function liftIIFE(name) {
  const m = new RegExp("\\(function " + name + "\\s*\\(\\s*\\)\\s*\\{").exec(SRC);
  return m ? balanced(m.index + m[0].length, "{", "}") : "";
}

const SWITCH_BODY = liftIIFE("wireCoverLetterSwitch");
if (!SWITCH_BODY) {
  gone("wireCoverLetterSwitch", "The cover-letter checkbox is the entire feature now — find "
       + "where its wiring moved to and repoint this harness; do not delete the scenarios.");
}

// The module-top snapshot binding. Its being a ONE-SHOT read is the whole mechanism under test,
// so it is taken from the source rather than written out here — a page that switched to a live
// getter would make these scenarios pass for a new reason, and that should be visible.
const SNAPSHOT_M = /\n\s*const state = TW\.getState\(\);/.exec(SRC);
if (!SNAPSHOT_M) {
  gone("the module-top `const state = TW.getState();` binding",
       "If the page no longer keeps a load-time snapshot, the staleness these scenarios are "
       + "about cannot happen and they need rewriting rather than repointing.");
}
const SNAPSHOT_LINE = SNAPSHOT_M[0].trim();

// The real `liveKey` helper — the fix for that staleness, and 13 keys on this page depend on it.
const LIVEKEY_M = /\n(\s*)const liveKey = \(name\) => \{/.exec(SRC);
if (!LIVEKEY_M) {
  gone("the `liveKey` helper",
       "It is what reads a top-level key out of the CURRENT blob rather than the page's snapshot.");
}
const LIVEKEY_SRC = "const liveKey = (name) => {"
  + balanced(LIVEKEY_M.index + LIVEKEY_M[0].length, "{", "}") + "};";

// The payload line, from inside continueToDone's `proposal_payload` literal. Anchored on the
// literal first, so a `cover_letter_enabled:` written somewhere else on the page (there is one,
// in the switch's own setState call) cannot be picked up instead.
const LITERAL_M = /proposal_payload:\s*\{/.exec(SRC);
if (!LITERAL_M) gone("the `proposal_payload` literal", "It is what a sent revision freezes.");
const LITERAL = balanced(LITERAL_M.index + LITERAL_M[0].length, "{", "}");
const FIELD_M = /^[ \t]*cover_letter_enabled:.*$/m.exec(LITERAL);
if (!FIELD_M) {
  gone("the `cover_letter_enabled` field of the proposal_payload literal",
       "Without it a ticked box reaches no document at all, and the frozen revision a customer "
       + "re-opens has no way to know the proposal had a letterhead page.");
}
const PAYLOAD_FIELD = FIELD_M[0].trim().replace(/,\s*$/, "");

// ── the smallest DOM it touches ──────────────────────────────────────────────
function makeBox() {
  const listeners = {};
  return {
    checked: undefined,          // undefined so "was it painted at all" is answerable
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    fire(type) { (listeners[type] || []).forEach((fn) => fn({ type })); },
    listenerCount(type) { return (listeners[type] || []).length; },
  };
}

/** `undefined` as a value the Python side can read and print.
 *
 *  JSON.stringify DELETES an undefined property, so a wiring that never touched `box.checked`
 *  would arrive on the other side as a missing key — a KeyError with no message instead of the
 *  assertion "a saved project with a cover letter opens with the box unticked". Which is the
 *  reported-failure equivalent of the bug this whole harness exists to avoid: the report has to
 *  say what went wrong, not merely that something did. */
function reported(v) { return v === undefined ? "<never set>" : v; }

/** shared.js's state store, with the one property that makes this bug possible.
 *
 *  `getState` PARSES localStorage and hands back a NEW object every call; `setState` merges the
 *  partial onto a fresh parse and writes that back. So a caller holding an earlier `getState()`
 *  result holds an object nothing will ever update — which is precisely why the payload line has
 *  to go through `liveKey`. A stub that returned the same object from every `getState` would make
 *  the broken version of that line pass, and this harness would certify the bug.
 *
 *  Not modelled, because none of it bears on this read: the draft-id STAMP guard that refuses a
 *  write belonging to another draft, and the debounced server PUT. */
function makeStore(stored, opts) {
  const options = opts || {};
  let raw = JSON.stringify(stored === undefined ? {} : stored);
  const writes = [];
  return {
    writes,
    getState() {
      try { return raw ? JSON.parse(raw) : {}; } catch (e) { return {}; }
    },
    setState(partial) {
      writes.push(partial);
      if (options.throws) throw new Error("QuotaExceededError");
      const merged = Object.assign(this.getState(), partial || {});
      raw = JSON.stringify(merged);
      return merged;
    },
  };
}

/** The real wiring alone, against one stored draft blob. */
function scenario(cfg) {
  const present = cfg.present === undefined ? true : cfg.present;
  const box = present ? makeBox() : null;
  const doc = { getElementById: (id) => (id === "cl-toggle" ? box : null) };
  const store = makeStore(cfg.stored, { throws: cfg.setStateThrows });
  const TW = { getState: () => store.getState(), setState: (p) => store.setState(p) };
  const wire = new Function("document", "TW", '"use strict";\n' + SWITCH_BODY);
  let threw = null;
  try { wire(doc, TW); } catch (e) { threw = String((e && e.message) || e); }
  return { box, store, writes: store.writes, threw };
}

/** The wiring AND the payload line, in one scope, in the page's own order.
 *
 *  The snapshot is taken first (page load), then `liveKey` is defined, then the switch is wired
 *  — exactly the sequence in the file. `buildPayload` is what `continueToDone` evaluates. */
function payloadScenario(cfg) {
  const box = makeBox();
  const doc = { getElementById: (id) => (id === "cl-toggle" ? box : null) };
  const store = makeStore(cfg.stored);
  const TW = { getState: () => store.getState(), setState: (p) => store.setState(p) };
  const build = new Function("document", "TW", '"use strict";\n'
    + SNAPSHOT_LINE + "\n"
    + LIVEKEY_SRC + "\n"
    + "(function () {\n" + SWITCH_BODY + "\n})();\n"
    + "return function () { return { " + PAYLOAD_FIELD + " }; };");
  const buildPayload = build(doc, TW);
  return { box, store, buildPayload };
}

/** Tick or untick, then read what Continue would freeze into the revision. */
function press(cfg, checked) {
  const s = payloadScenario(cfg);
  const paintedOnLoad = reported(s.box.checked);
  s.box.checked = checked;
  s.box.fire("change");
  return {
    paintedOnLoad: paintedOnLoad,
    payload: s.buildPayload().cover_letter_enabled,
    // What actually reached the draft. Read separately so a failure says WHICH half broke: the
    // write, or the read that goes looking for it.
    stored: !!s.store.getState().cover_letter_enabled,
  };
}

const out = {};
out.liftedPayloadField = PAYLOAD_FIELD;

// 1. A reopened draft shows the box as the estimator left it.
{
  const r = scenario({ stored: { cover_letter_enabled: true } });
  out.paintedFromTrueDraft = reported(r.box.checked);
  out.paintedThrew = r.threw;
  out.changeListeners = r.box.listenerCount("change");
}
// 2. A draft that never asked for one, and a brand-new draft with no key at all.
out.paintedFromFalseDraft =
  reported(scenario({ stored: { cover_letter_enabled: false } }).box.checked);
out.paintedFromEmptyDraft = reported(scenario({ stored: {} }).box.checked);
// 3. TW.getState() can legitimately hand back nothing (private mode / parse failure); the page
//    must still finish wiring rather than throw on the way past.
{
  const r = scenario({ stored: null });
  out.paintedFromNoState = reported(r.box.checked);
  out.noStateThrew = r.threw;
}
// 4. A truthy non-boolean must reach the DOM as a real boolean — `checked = "1"` is how a
//    checkbox ends up un-round-trippable through JSON.
out.paintedFromTruthyString =
  reported(scenario({ stored: { cover_letter_enabled: "1" } }).box.checked);

// 5. Ticking writes the flag onto the draft; unticking writes it back off (not deletes it —
//    the backend defaults a missing key to False, but a draft that once had a letter has to be
//    able to say so).
{
  const r = scenario({ stored: {} });
  r.box.checked = true;
  r.box.fire("change");
  r.box.checked = false;
  r.box.fire("change");
  out.writes = r.writes;
}
// 6. A write that fails must not throw out of the handler and kill the rest of the page's
//    listeners — the same `try {} catch {}` every other choice on this page uses.
{
  const r = scenario({ stored: {}, setStateThrows: true });
  r.box.checked = true;
  let handlerThrew = null;
  try { r.box.fire("change"); } catch (e) { handlerThrew = String((e && e.message) || e); }
  out.handlerThrewOnFailedWrite = handlerThrew;
  out.attemptedWriteAnyway = r.writes.length;
}
// 7. Inert where the checkbox does not exist. The same script tag is not on every page, but a
//    guard that returned on a missing element is what keeps this from being a console error the
//    day the ribbon is restructured.
{
  const r = scenario({ stored: { cover_letter_enabled: true }, present: false });
  out.absentBoxThrew = r.threw;
  out.absentBoxWrote = r.writes.length;
}

// 8. THE PAYLOAD, in the same visit as the press. The two directions of the bug that shipped.
out.tickThenContinue = press({ stored: {} }, true);
out.untickThenContinue = press({ stored: { cover_letter_enabled: true } }, false);
// 9. And Continue WITHOUT touching the box, both ways round — the control that stops the two
//    above from passing on a line that ignores the draft and answers `!box`, or a constant.
{
  const s = payloadScenario({ stored: { cover_letter_enabled: true } });
  out.untouchedFromTrueDraft = s.buildPayload().cover_letter_enabled;
}
{
  const s = payloadScenario({ stored: {} });
  out.untouchedFromEmptyDraft = s.buildPayload().cover_letter_enabled;
}

process.stdout.write(JSON.stringify(out));
