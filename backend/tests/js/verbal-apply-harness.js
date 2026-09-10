"use strict";
/* applyVerbal — the client side of verbal intake, RUN rather than read.
 *
 * This is the function that takes what the server accepted and puts it on the estimator's screen.
 * Four of the things it can get wrong are invisible in a diff and invisible on the page:
 *
 *   * IT COULD FLIP A SWITCH THAT WAS ALREADY RIGHT. `toggleCondition` is a TOGGLE, not a setter.
 *     Calling it for every condition the server returned — rather than only the ones that differ —
 *     turns a correct form wrong, and the only trace is a price that changed. A source read sees a
 *     loop over accepted conditions and a call to a function named for the thing it wants.
 *   * IT COULD FILL THE BOXES AND SAVE NOTHING. There is no `input` listener anywhere on
 *     polish-intake.js — wire() binds a delegated click, a submit and the county box, and that is
 *     the whole list — so dispatching an input event persists nothing. applyVerbal has to call
 *     saveSoon itself. This one WAS the live bug: the panel reported "Filled in" and the fields
 *     survived only when a condition happened to flip in the same run and its save swept them up,
 *     which is why it read as intermittent rather than broken.
 *   * IT COULD ARGUE WITH THE ESTIMATOR. A condition they corrected by hand after the first run
 *     must come back in `respected` on the second, not get flipped again.
 *   * IT COULD LEAVE THE CAPTION STALE. #proj-line names the project and the town — both boxes
 *     this fills — and until now only hydrate() ever wrote it.
 *
 * None of that is reachable from a stub that only records calls, so the REAL toggleCondition,
 * paintCondition, isCondition and paintProjLine are lifted and run: the model, the switch element,
 * the caption and the save hook all move together, which is what makes "already right" observable.
 *
 * Usage: node verbal-apply-harness.js <frontend-dir>   →   one line of JSON
 */
const fs = require("fs");
const path = require("path");

const FRONTEND = process.argv[2];
const SRC = fs.readFileSync(path.join(FRONTEND, "js", "polish-intake.js"), "utf8")
  .replace(/\r\n/g, "\n");

function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone from polish-intake.js — rewrite this harness");
  const open = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

/** The smallest form these functions touch: inputs addressed by name, switches and the caption
 *  by id. */
function makeWorld(conditions) {
  const events = [];
  const painted = [];
  const inputs = {};
  for (const name of ["project_name", "address", "city", "state", "zip",
                      "contact_name", "contact_email", "bid_date"]) {
    inputs[name] = {
      name, value: "",
      dispatchEvent(e) { events.push({ name, type: e.type, bubbles: !!e.bubbles }); return true; },
    };
  }
  const byId = {};
  // Which switches had focus() called on them, and how many times the whole block was re-rendered.
  // Only a key something DEPENDS ON forces a re-render; the rest take the cheap one-node repaint.
  // Both are recorded because "it repainted" and "it repainted the expensive way" are different
  // claims, and the verbal panel touching five keys should never pay for the expensive one.
  const focuses = [];
  const rerenders = [];
  // The engine five come from the fixture; the carried four are always on this page, so they are
  // always in the DOM. A world with only five switches cannot see the caret being put back.
  const keys = Object.keys(conditions)
    .concat(["reno", "dye", "joint_filler", "remove_existing_jf"]);
  for (const key of keys) {
    byId["cond-" + key] = {
      className: "", attrs: {},
      setAttribute(k, v) { this.attrs[k] = v; painted.push([key, k, v]); },
      focus() { focuses.push(key); },
    };
  }
  // The caption above the form. Counted as well as read: "it was repainted" and "it says the right
  // thing" are different claims, and a fill that never touched it would satisfy neither.
  const captionWrites = [];
  byId["proj-line"] = {
    _text: "Loading…",
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); captionWrites.push(String(v)); },
  };
  return {
    events, painted, inputs, byId, captionWrites, focuses, rerenders,
    form: { querySelector: (sel) => inputs[(/\[name="([^"]+)"\]/.exec(sel) || [])[1]] || null },
  };
}

/** One page visit. `runs` is a LIST of extractions plus the clicks between them, because the whole
 *  point of `respected` is what the SECOND run does about the first one. */
function visit(conditions, steps, blob) {
  const world = makeWorld(conditions);
  const saves = [];
  const notes = [];
  const M = { conditions: Object.assign({}, conditions) };
  const scope = new Function(
    "M", "form", "world", "saves", "notes", "Event", "state",
    `"use strict";
    var CONDITIONS = [{ key: "local" }, { key: "hard_bid" }, { key: "prevailing_wage" },
                      { key: "taxable" }, { key: "remodel_tax" }];
    // The four the polish page carries through from the live intake. They are NOT the engine's --
    // they move no money and they are not on the model -- but the toggle path reads them, so a
    // scope without them is a ReferenceError the moment anything is clicked. Same shape as the
    // page's own list, including the one dependency, because hasDependents reads "needs".
    var CARRY_CONDITIONS = [{ key: "reno", def: false }, { key: "dye", def: false },
                            { key: "joint_filler", def: true },
                            { key: "remove_existing_jf", def: false, needs: "joint_filler" }];
    // SEEDED, NOT EMPTY, AND THIS IS WHAT MAKES THE COMPARISON TESTABLE. hydrate() fills carry
    // from cell_values and falls back to cc.def, so a fresh project starts with Joint filler ON --
    // one kit per 3,500 sq ft is how the sheet ships. An empty object would leave every carried
    // key undefined, where reading the model and calling condOn agree on false, and a comparison
    // pointed at the wrong binding could not be caught: a transcript saying no joint filler would
    // look correctly handled either way. With the default seeded, the model read says "already
    // off, nothing to do" and leaves the switch ON.
    // (No backticks in this comment. It is inside a new Function template literal, where one
    // would end the literal and Node would blame the line the literal opened on.)
    var carry = {};
    CARRY_CONDITIONS.forEach(function (cc) { carry[cc.key] = cc.def; });
    var $ = function (id) { return world.byId[id] || null; };
    var humanConditions = {};
    function renderCountyNote() { notes.push(1); }
    function saveSoon() { saves.push(1); }
    // The page rewrites the whole block's innerHTML; what matters to this harness is the EFFECT --
    // every switch repainted and the caret gone -- so the stub reproduces that and counts itself.
    function renderConditions() {
      world.rerenders.push(1);
      Object.keys(world.byId).forEach(function (id) {
        if (id.indexOf("cond-") === 0) paintCondition(id.slice(5));
      });
    }
    ` + fn("isCondition") + fn("carrySpec") + fn("condOn") + fn("hasDependents") +
    fn("paintCondition") + fn("repaintCondition") + fn("toggleCondition") + fn("paintProjLine") +
    fn("applyVerbal") + `
    return { applyVerbal: applyVerbal, toggleCondition: toggleCondition, model: M,
             carry: carry, human: humanConditions };`
  )(M, world.form, world, saves, notes, function (type, opts) {
    return { type, bubbles: !!(opts && opts.bubbles) };
  }, blob || {});

  const results = [];
  for (const step of steps) {
    if (step.click) {
      // Through toggleCondition with NO second argument, which is exactly what the page's
      // delegated click handler does. That absence is what marks the key as the estimator's.
      scope.toggleCondition(step.click);
      results.push({ clicked: step.click });
      continue;
    }
    results.push({ applied: scope.applyVerbal(step.read) });
  }

  return {
    results,
    applied: results.length === 1 ? results[0].applied : undefined,
    conditionsAfter: Object.assign({}, M.conditions),
    // Whatever the run left on the carried-four binding, which is the only place those four
    // live: migrateModel whitelists condition keys against freshModel().conditions, so a carried
    // key written to the model would be dropped on the next load. It starts at the page's
    // defaults, so an untouched run reads them back rather than reading {}.
    carryAfter: Object.assign({}, scope.carry),
    humanOwned: Object.keys(scope.human).sort(),
    events: world.events,
    inputValues: Object.keys(world.inputs).reduce((acc, k) => {
      if (world.inputs[k].value) acc[k] = world.inputs[k].value;
      return acc;
    }, {}),
    saves: saves.length,
    countyNoteRepaints: notes.length,
    painted: world.painted,
    focuses: world.focuses,
    rerenders: world.rerenders.length,
    // Every switch's final class, keyed. aria-checked already rides `painted`, but the class is
    // where "on" and "greyed" are, and it is the level a wrong comparison is visible at: a
    // transcript that says no joint filler, mishandled, leaves this reading "sw on" while the
    // estimator's own screen says the crew is filling joints.
    classesAfter: Object.keys(world.byId).reduce((acc, id) => {
      if (id.indexOf("cond-") === 0) acc[id.slice(5)] = world.byId[id].className;
      return acc;
    }, {}),
    captionWrites: world.captionWrites,
    caption: world.byId["proj-line"].textContent,
  };
}

function run(conditions, res, blob) {
  return visit(conditions, [{ read: res }], blob);
}

const BASE = { local: true, hard_bid: false, prevailing_wage: false,
               taxable: true, remodel_tax: false };
const out = {};

// ═══ 1. a flag that DIFFERS is set ═══════════════════════════════════════════
out.flips = run(BASE, {
  conditions: { prevailing_wage: {
    value: true, context: "the district says they said prevailing wage on this" } },
});

// ═══ 2. THE ONE THAT MATTERS: a flag already right is not toggled ════════════
// toggleCondition is a TOGGLE. Calling it for every accepted condition — the obvious loop — turns
// a correct form wrong, silently, and the only evidence is a price that moved.
out.alreadyRight = run(BASE, {
  conditions: {
    local: { value: true, context: "it is local" },
    taxable: { value: true, context: "it is taxable" },
  },
});

// ═══ 3. text fields are filled AND the draft is scheduled to save ════════════
// Nothing on the page listens for `input`, so the event alone persists none of it. The save call is
// the fix; the event stays because a programmatic fill should still look like a keystroke.
out.fields = run(BASE, {
  fields: { project_name: "Blue Valley West", city: "Overland Park", bid_date: "2026-09-03" },
});

// ═══ 3b. the caption over the form follows the boxes ════════════════════════
// project_name and city are both in it. A fill that left it reading "Untitled project" over a
// named form is the panel disagreeing with itself on screen.
out.caption = run(BASE, {
  fields: { project_name: "Blue Valley West", city: "Overland Park", state: "KS" },
});
out.captionNoState = run(BASE, { fields: { project_name: "Blue Valley West" } });
// The draft still names the project when the transcript only gave the town: the boxes are read
// first, the blob second, and neither is thrown away for the other.
out.captionFromBlob = run(BASE, { fields: { city: "Bonner Springs", state: "KS" } },
                          { project_name: "Nearman Creek", city: "Kansas City", state: "KS" });

// ═══ 4. a condition name nobody wired up sets nothing ═══════════════════════
out.unknownCondition = run(BASE, {
  conditions: { union_job: { value: true, context: "x" },
                county_remodel_rate: { value: true, context: "x" } },
});

// ═══ 4b. a CARRIED-THROUGH key handed back by the extraction ═══════════════
// The nine switches this page renders, not the five the pricing engine reads. Both halves of the
// widening are exercised here at once, because they are not separable:
//
//   * THE GATE. `!carrySpec(key) && !isCondition(key)` -- toggleCondition has taken a carried key
//     since the nine shipped, and applyVerbal had not.
//   * THE COMPARISON. condOn, not M.conditions. joint_filler is the fixture that tells them
//     apart: it ships ON, it is not on the model, and `!!undefined !== false` is false -- so the
//     old read would call "no joint filler on this one" a no-op and leave the switch on.
//
// NOT REACHABLE END-TO-END YET. verbal_intake.py builds its conditions by looping over
// MONEY_CONDITIONS -- five literals -- so the server cannot hand this shape back today; that is
// pinned in test_verbal_intake.py rather than left to this file's green run to imply. The
// seven-flag list that includes B10 New/Reno is /api/autofill's, a different route.
out.carryFromVerbal = run(BASE, {
  conditions: { reno: { value: true, context: "the notes say it is a remodel" },
                joint_filler: { value: false, context: "no joint filler on this one" } },
});

// ═══ 4c. a click on a carried-through key still works ══════════════════════
// Straight through toggleCondition with no second argument, exactly as the delegated click
// handler calls it. This is the path that threw ReferenceError while the scope had no carry
// bindings -- every test in this file errored, and none of them was about the carried four.
out.carryClicked = visit(BASE, [{ click: "joint_filler" }, { click: "dye" }]);

// ═══ 4d. a carried key that is ALREADY RIGHT is left alone ═════════════════
// The whole reason the comparison exists, now aimed at the four. toggleCondition is a TOGGLE:
// looping over everything the server accepted and calling it would flip Joint filler OFF here,
// on a transcript that agreed with the screen. Both keys are given at their default, so a page
// that toggles unconditionally fails and a page that reads the wrong binding fails too -- reading
// `!!M.conditions.joint_filler` here is false against a true value and would toggle.
out.carryAlreadyRight = run(BASE, {
  conditions: { dye: { value: false, context: "no dye on this one" },
                joint_filler: { value: true, context: "joints get filled" } },
});

// ═══ 5. a non-boolean is not a decision ════════════════════════════════════
out.nonBoolean = run(BASE, {
  conditions: { hard_bid: { value: "true", context: "x" } },
});

// ═══ 6. an empty extraction changes nothing at all ═════════════════════════
out.empty = run(BASE, {});

// ═══ 7. THE HUMAN WINS. Read, corrected by hand, read again ════════════════
// The re-ask is the common second run: three runs per five minutes means the estimator usually
// gets one correction and one re-read. If the re-read undoes the correction, the feature is worse
// than no feature — they watched themselves fix it and it came back.
out.humanWins = visit(BASE, [
  { read: { conditions: { hard_bid: {
      value: true, context: "through the district it is a hard bid I think" } } } },
  { click: "hard_bid" },
  { read: { conditions: { hard_bid: {
      value: true, context: "through the district it is a hard bid I think" } } } },
]);

// ═══ 8. a key the PANEL set is still the panel's to correct ════════════════
// The mirror of 7, and the reason `respected` is keyed on the click rather than on "has been set
// before": a first run that got prevailing_wage wrong must be fixable by a second run.
out.verbalMayCorrectItself = visit(BASE, [
  { read: { conditions: { prevailing_wage: { value: true, context: "prevailing wage job" } } } },
  { read: { conditions: { prevailing_wage: { value: false, context: "not prevailing wage" } } } },
]);

// ═══ 9. a human flip does not freeze the OTHER four ════════════════════════
out.humanFlipIsPerKey = visit(BASE, [
  { click: "hard_bid" },
  { read: { conditions: {
      hard_bid: { value: true, context: "it is a hard bid" },
      prevailing_wage: { value: true, context: "prevailing wage job" },
    } } },
]);

// ═══ 10. fields and a flip in one run land on ONE debounced timer ══════════
out.fieldsAndFlip = run(BASE, {
  fields: { project_name: "Blue Valley West" },
  conditions: { prevailing_wage: { value: true, context: "prevailing wage job" } },
});

console.log(JSON.stringify(out));
