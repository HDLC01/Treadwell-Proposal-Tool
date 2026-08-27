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
  for (const key of Object.keys(conditions)) {
    byId["cond-" + key] = {
      className: "", attrs: {},
      setAttribute(k, v) { this.attrs[k] = v; painted.push([key, k, v]); },
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
    events, painted, inputs, byId, captionWrites,
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
    var $ = function (id) { return world.byId[id] || null; };
    var humanConditions = {};
    function renderCountyNote() { notes.push(1); }
    function saveSoon() { saves.push(1); }
    ` + fn("isCondition") + fn("paintCondition") + fn("toggleCondition") + fn("paintProjLine") +
    fn("applyVerbal") + `
    return { applyVerbal: applyVerbal, toggleCondition: toggleCondition, model: M,
             human: humanConditions };`
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
    humanOwned: Object.keys(scope.human).sort(),
    events: world.events,
    inputValues: Object.keys(world.inputs).reduce((acc, k) => {
      if (world.inputs[k].value) acc[k] = world.inputs[k].value;
      return acc;
    }, {}),
    saves: saves.length,
    countyNoteRepaints: notes.length,
    painted: world.painted,
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
