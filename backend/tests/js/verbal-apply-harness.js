"use strict";
/* applyVerbal — the client side of verbal intake, RUN rather than read.
 *
 * This is the function that takes what the server accepted and puts it on the estimator's screen.
 * Two of the things it can get wrong are invisible in a diff and invisible on the page:
 *
 *   * IT COULD FLIP A SWITCH THAT WAS ALREADY RIGHT. `toggleCondition` is a TOGGLE, not a setter.
 *     Calling it for every condition the server returned — rather than only the ones that differ —
 *     turns a correct form wrong, and the only trace is a price that changed. A source read sees a
 *     loop over accepted conditions and a call to a function named for the thing it wants.
 *   * IT COULD SET .value WITHOUT AN EVENT. The draft saves off the form's own input handling, so
 *     assigning .value alone fills the boxes on screen and saves none of it. The estimator sees a
 *     complete form, reloads, and it is empty.
 *
 * Neither is reachable from a stub that only records calls, so the REAL toggleCondition,
 * paintCondition and isCondition are lifted and run: the model, the switch element and the save
 * hook all move together, which is what makes "already right" observable.
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

/** The smallest form these functions touch: inputs addressed by name, switches by id. */
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
  const switches = {};
  for (const key of Object.keys(conditions)) {
    switches["cond-" + key] = {
      className: "", attrs: {},
      setAttribute(k, v) { this.attrs[k] = v; painted.push([key, k, v]); },
    };
  }
  return {
    events, painted, inputs, switches,
    form: { querySelector: (sel) => inputs[(/\[name="([^"]+)"\]/.exec(sel) || [])[1]] || null },
  };
}

function run(conditions, res) {
  const world = makeWorld(conditions);
  const saves = [];
  const notes = [];
  const M = { conditions: Object.assign({}, conditions) };
  const scope = new Function(
    "M", "form", "world", "saves", "notes", "Event",
    `"use strict";
    var CONDITIONS = [{ key: "local" }, { key: "hard_bid" }, { key: "prevailing_wage" },
                      { key: "taxable" }, { key: "remodel_tax" }];
    var $ = function (id) { return world.switches[id] || null; };
    function renderCountyNote() { notes.push(1); }
    function saveSoon() { saves.push(1); }
    ` + fn("isCondition") + fn("paintCondition") + fn("toggleCondition") + fn("applyVerbal") + `
    return { applyVerbal: applyVerbal, model: M };`
  )(M, world.form, world, saves, notes, function (type, opts) {
    return { type, bubbles: !!(opts && opts.bubbles) };
  });

  const applied = scope.applyVerbal(res);
  return {
    applied,
    conditionsAfter: Object.assign({}, M.conditions),
    events: world.events,
    inputValues: Object.keys(world.inputs).reduce((acc, k) => {
      if (world.inputs[k].value) acc[k] = world.inputs[k].value;
      return acc;
    }, {}),
    saves: saves.length,
    countyNoteRepaints: notes.length,
    painted: world.painted,
  };
}

const BASE = { local: true, hard_bid: false, prevailing_wage: false,
               taxable: true, remodel_tax: false };
const out = {};

// ═══ 1. a flag that DIFFERS is set ═══════════════════════════════════════════
out.flips = run(BASE, {
  conditions: { prevailing_wage: { value: true, quote: "they said prevailing wage" } },
});

// ═══ 2. THE ONE THAT MATTERS: a flag already right is not toggled ════════════
// toggleCondition is a TOGGLE. Calling it for every accepted condition — the obvious loop — turns
// a correct form wrong, silently, and the only evidence is a price that moved.
out.alreadyRight = run(BASE, {
  conditions: {
    local: { value: true, quote: "it is local" },
    taxable: { value: true, quote: "it is taxable" },
  },
});

// ═══ 3. text fields go in THROUGH a real input event ════════════════════════
// The draft saves off the form's own input handling. Assigning .value alone fills the boxes and
// saves none of it: a complete-looking form that is empty after a reload.
out.fields = run(BASE, {
  fields: { project_name: "Blue Valley West", city: "Overland Park", bid_date: "2026-09-03" },
});

// ═══ 4. a condition name nobody wired up sets nothing ═══════════════════════
out.unknownCondition = run(BASE, {
  conditions: { union_job: { value: true, quote: "x" },
                county_remodel_rate: { value: true, quote: "x" } },
});

// ═══ 5. a non-boolean is not a decision ════════════════════════════════════
out.nonBoolean = run(BASE, {
  conditions: { hard_bid: { value: "true", quote: "x" } },
});

// ═══ 6. an empty extraction changes nothing at all ═════════════════════════
out.empty = run(BASE, {});

console.log(JSON.stringify(out));
