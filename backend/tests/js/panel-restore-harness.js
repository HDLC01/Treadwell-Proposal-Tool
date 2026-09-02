"use strict";
/* RESTORE a moved panel onto a screen SMALLER than the one it was moved on.
 *
 * WHY THIS EXISTS. Two panels float and remember where they were dragged: the Pricing options rail
 * on step 3 (proposal-review.js) and the polish-intake cheat sheet (polish-verbal.js), which was
 * built to match it. Both clamped the position while dragging and then reapplied it on load with no
 * clamp at all — safe only while the window never gets smaller. Drag either to the far side of a
 * wide monitor, reopen the page on a laptop, and it is restored past the edge with its drag handle
 * off screen: nothing to grab it by, and no way back short of clearing site data. That is a panel
 * the estimator cannot recover, sitting on the page they are trying to read.
 *
 * The overlap this widget was moved aside to fix was found by walking a browser, not by a test, and
 * so was this. The lesson is the one STAGE_CREATED taught on 2026-08-12: run the shipped function.
 * A source assertion can see a Math.min in the drag handler and conclude the geometry is guarded,
 * because it cannot tell which of the two code paths that Math.min is on.
 *
 * So this lifts BOTH shipped initialisers and TW.clampPanelPos out of the real files, seeds
 * localStorage with a position from a bigger screen, and reads where the panel actually lands.
 *
 * DELIBERATELY NOT A FULL DOM, for the reason board-render-harness.js gives: jsdom would let a
 * missing binding hide behind a stub. What is shimmed is only what the gesture touches, and the two
 * things the arithmetic depends on are modelled honestly:
 *
 *   * getComputedStyle().position is the harness's own answer, because both restores are supposed
 *     to stand down when the CSS has put the panel back in the flow. A shim that always said
 *     "fixed" would make the narrow-screen case untestable.
 *   * offsetWidth is the panel's real rendered width in each mode — 250/240 floating, the whole
 *     ~1000px column in the flow — which is what makes "clamping in the flow would compute a lane
 *     for a panel four times too wide" a measurement rather than an assertion about a comment.
 *
 * Usage: node panel-restore-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const DIR = process.argv[2];
// Normalized to LF: the frontend is checked out CRLF here and every pattern below anchors on
// "\n  " indentation. A stray CR would make the lifted source differ from the shipped source,
// which is the one thing this harness must not allow.
const read = (...p) => fs.readFileSync(path.join(DIR, ...p), "utf8").replace(/\r\n/g, "\n");
const SHARED = read("shared.js");
const VERBAL = read("js", "polish-verbal.js");
const REVIEW = read("js", "proposal-review.js");

// ── lifting the real source ──────────────────────────────────────────────────
function braceMatch(src, open) {
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return j;
  }
  throw new Error("unbalanced braces");
}

function fn(src, name, where) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from " + where + " — rewrite this harness, don't delete it");
  return src.slice(m.index, braceMatch(src, src.indexOf("{", m.index + m[0].length - 1)) + 1);
}

/** initOptionsPanelDrag is a named IIFE, not a declaration — `(function name() { … })();` — so it
 *  is lifted as the function EXPRESSION it is and assigned, rather than matched as a declaration.
 *  Lifting it at all is the point: the reference panel had the identical hole, and a harness that
 *  only covered the copy would have left the original for a user to find. */
function iife(src, name, where) {
  const m = new RegExp("\\n  \\(function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + " is gone from " + where + " — rewrite this harness, don't delete it");
  const start = src.indexOf("(function", m.index);
  return src.slice(start, braceMatch(src, src.indexOf("{", m.index + m[0].length - 1)) + 1) + ")";
}

// ── the shims ────────────────────────────────────────────────────────────────
/** A panel with the two measurements that matter and nothing invented. `position` is settable so a
 *  single element can play both the floating and the in-the-flow case. */
function makePanel(id, floatWidth, flowWidth, handleClass) {
  const handle = {
    className: handleClass,
    closest(sel) { return sel === "." + handleClass ? handle : null; },
    setPointerCapture() {},
  };
  const el = {
    id,
    handle,
    position: "fixed",
    style: { left: "", top: "", right: "16px" },
    classes: new Set(),
    listeners: {},
    get offsetWidth() { return el.position === "fixed" ? floatWidth : flowWidth; },
    classList: {
      add: (c) => el.classes.add(c),
      remove: (c) => el.classes.delete(c),
      contains: (c) => el.classes.has(c),
    },
    contains: (n) => n === handle,
    addEventListener: (t, h) => { el.listeners[t] = h; },
    getBoundingClientRect() {
      return {
        left: parseFloat(el.style.left) || 0,
        top: parseFloat(el.style.top) || 0,
        width: el.offsetWidth,
      };
    },
    fire(type, props) {
      const h = el.listeners[type];
      if (!h) throw new Error(id + " never bound " + type);
      h(Object.assign({ target: handle, preventDefault() {}, pointerId: 1 }, props));
    },
    at() {
      return { left: parseFloat(el.style.left), top: parseFloat(el.style.top), right: el.style.right };
    },
  };
  return el;
}

function makeEnv(panel, key, saved, win) {
  const store = {};
  if (saved !== undefined) store[key] = JSON.stringify(saved);
  return {
    window: { innerWidth: win.w, innerHeight: win.h },
    localStorage: {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
    },
    document: { getElementById: (id) => (id === panel.id ? panel : null) },
    getComputedStyle: () => ({ position: panel.position }),
    store,
  };
}

/** Runs a lifted initialiser inside its own scope with only what the page really gives it. */
function runInit(body, callExpr, env) {
  const src = `
    "use strict";
    const window = ENV.window, localStorage = ENV.localStorage, document = ENV.document;
    const getComputedStyle = ENV.getComputedStyle;
    const $ = (id) => document.getElementById(id);
    const TW = { clampPanelPos: CLAMP };
    ${body}
    ${callExpr}
  `;
  // eslint-disable-next-line no-new-func
  new Function("ENV", "CLAMP", src)(env, CLAMP);
}

// clampPanelPos is itself lifted, so the two panels are tested against the shipped bounds rather
// than against a copy of them that could drift.
const CLAMP = new Function(
  `${fn(SHARED, "clampPanelPos", "shared.js")}\nreturn clampPanelPos;`)();

const out = {};

// -- 1. the bounds themselves --------------------------------------------------
{
  const w = { innerWidth: 1750, innerHeight: 1125 };
  global.window = w;
  out.clamp = {
    farRight: CLAMP(3400, 300, 250),      // saved on a wide monitor, restored on a laptop
    farBottom: CLAMP(300, 2600, 250),
    negative: CLAMP(-500, -80, 250),
    inBounds: CLAMP(600, 400, 250),       // already legal: must pass through untouched
    rightEdge: CLAMP(1496, 10, 250),      // exactly the last legal x
    noWidth: CLAMP(3400, 10, 0),          // falsy width falls back to the CSS 250
  };
}

// -- 2. the cheat sheet restores onto the smaller screen -----------------------
// The reported shape: dragged to the right on a wide monitor, reopened on a laptop.
{
  const panel = makePanel("verbal-cheat", 250, 1000, "vc-drag");
  const env = makeEnv(panel, "tw_vcheat_pos", { left: 3400, top: 2600 }, { w: 1750, h: 1125 });
  global.window = env.window;
  runInit(fn(VERBAL, "initCheatDrag", "polish-verbal.js"), "initCheatDrag();", env);
  out.cheatRestore = {
    at: panel.at(),
    onScreen: parseFloat(panel.style.left) + 250 <= 1750 && parseFloat(panel.style.top) <= 1125 - 40,
  };
}

// -- 3. a legal saved position is left exactly alone ---------------------------
// The clamp must not become a "helpfully" repositioning panel: if the estimator put it somewhere
// that fits, it opens there.
{
  const panel = makePanel("verbal-cheat", 250, 1000, "vc-drag");
  const env = makeEnv(panel, "tw_vcheat_pos", { left: 1265, top: 264 }, { w: 1750, h: 1125 });
  global.window = env.window;
  runInit(fn(VERBAL, "initCheatDrag", "polish-verbal.js"), "initCheatDrag();", env);
  out.cheatLegal = panel.at();
}

// -- 4. in the flow, the restore stands down ----------------------------------
// Below the breakpoint the CSS returns the panel to the document flow, where left/top are inert and
// offsetWidth is the whole column. Clamping against THAT width would compute a lane for a panel
// four times too wide, so the restore must not run at all.
{
  const panel = makePanel("verbal-cheat", 250, 1000, "vc-drag");
  panel.position = "static";
  const env = makeEnv(panel, "tw_vcheat_pos", { left: 1265, top: 264 }, { w: 1100, h: 900 });
  global.window = env.window;
  runInit(fn(VERBAL, "initCheatDrag", "polish-verbal.js"), "initCheatDrag();", env);
  out.cheatInFlow = { left: panel.style.left, top: panel.style.top, right: panel.style.right };
}

// -- 5. dragging still clamps, and still persists ------------------------------
// The drag was verified in a real browser but had no test. Both halves are asserted here so a
// future change cannot fix one path by breaking the other.
{
  const panel = makePanel("verbal-cheat", 250, 1000, "vc-drag");
  const env = makeEnv(panel, "tw_vcheat_pos", undefined, { w: 1750, h: 1125 });
  global.window = env.window;
  runInit(fn(VERBAL, "initCheatDrag", "polish-verbal.js"), "initCheatDrag();", env);
  panel.style.left = "1484"; panel.style.top = "104";
  panel.fire("pointerdown", { clientX: 1500, clientY: 120 });
  const midDrag = panel.classList.contains("vc-dragging");
  panel.fire("pointermove", { clientX: 9000, clientY: 9000 });   // hurled off the bottom-right
  const clamped = panel.at();
  panel.fire("pointerup", {});
  out.cheatDrag = {
    midDrag,
    stillDragging: panel.classList.contains("vc-dragging"),
    clamped,
    saved: JSON.parse(env.store["tw_vcheat_pos"] || "null"),
  };
}

// -- 6. the reference panel had the same hole -----------------------------------
// polish-intake copied this panel, and copied the bug with it. Fixing only the copy would have left
// the original for whoever it happened to.
{
  const panel = makePanel("options-panel", 240, 1000, "op-drag");
  const env = makeEnv(panel, "tw_opts_pos", { left: 3400, top: 2600 }, { w: 1750, h: 1125 });
  global.window = env.window;
  runInit("const RAW = " + iife(REVIEW, "initOptionsPanelDrag", "proposal-review.js") + ";",
    "RAW();", env);
  out.optsRestore = {
    at: panel.at(),
    onScreen: parseFloat(panel.style.left) + 240 <= 1750 && parseFloat(panel.style.top) <= 1125 - 40,
  };
}

process.stdout.write(JSON.stringify(out) + "\n");
