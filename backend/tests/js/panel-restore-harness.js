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
 * So this lifts BOTH shipped initialisers, TW.clampPanelPos and TW.floatPanel out of the real files,
 * seeds localStorage with a position from a bigger screen, and reads where the panel actually lands.
 *
 * TW.floatPanel (shared.js) is the one copy of the drag / remember / restore logic that the two
 * initialisers above now call, and that the v2 estimate's Sheets panel will too. Sections 2-6 reach
 * it through those initialisers, so they prove each caller passes its own key, classes and width;
 * sections 7-8 call it directly with names nothing else uses, so they prove it is a helper and not
 * a function that only works under its first two callers' names.
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
    // Answers for the element it is asked about, as the browser does, so two panels can share one env.
    getComputedStyle: (el) => ({ position: (el || panel).position }),
    store,
  };
}

// clampPanelPos and floatPanel are lifted from shared.js, so every panel is tested against the
// shipped bounds and the shipped drag rather than against a copy of them that could drift.
// floatPanel is the one copy of the drag/remember/restore logic that the step-3 rail, the cheat
// sheet and the v2 Sheets panel share; the two page initialisers lifted below are now thin calls
// into it, and what they do is only observable by running it.
const CLAMP_SRC = fn(SHARED, "clampPanelPos", "shared.js");
const FLOAT_SRC = fn(SHARED, "floatPanel", "shared.js");

/** The scope a lifted function runs in: only what a page really gives it. The shared helpers are
 *  declared INSIDE it, so their `window` / `localStorage` / `getComputedStyle` are this env's. */
function scopeSrc() {
  return `
    "use strict";
    const window = ENV.window, localStorage = ENV.localStorage, document = ENV.document;
    const getComputedStyle = ENV.getComputedStyle;
    const $ = (id) => document.getElementById(id);
    ${CLAMP_SRC}
    ${FLOAT_SRC}
    const TW = { clampPanelPos, floatPanel };
  `;
}

/** Runs a lifted initialiser inside its own scope with only what the page really gives it. */
function runInit(body, callExpr, env) {
  // eslint-disable-next-line no-new-func
  new Function("ENV", `${scopeSrc()}\n${body}\n${callExpr}`)(env);
}

/** The shipped TW helpers bound to one env, for calling floatPanel directly. */
function loadTW(env) {
  // eslint-disable-next-line no-new-func
  return new Function("ENV", `${scopeSrc()}\nreturn TW;`)(env);
}

const CLAMP = new Function(`${CLAMP_SRC}\nreturn clampPanelPos;`)();

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

// -- 7. TW.floatPanel directly, under a key and class names nothing else uses ----
// A helper that only worked under "op-drag" / "vc-drag" would pass sections 2-6 and fail the first
// time a third panel reached for it. Everything here uses the names a new panel would bring.
const WIN = { w: 1750, h: 1125 };
const OPTS = { handle: "sh-drag", draggingClass: "sh-dragging", key: "tw_probe_pos" };
const keysOf = (env) => Object.keys(env.store).sort();
out.float = {};
{
  // restored from a bigger screen: back on screen, against THIS panel's rendered width (256)
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  const env = makeEnv(panel, "tw_probe_pos", { left: 3400, top: 2600 }, WIN);
  loadTW(env).floatPanel(panel, OPTS);
  out.float.restoreFar = panel.at();
}
{
  // a legal saved position is left exactly where the estimator put it
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  const env = makeEnv(panel, "tw_probe_pos", { left: 600, top: 300 }, WIN);
  loadTW(env).floatPanel(panel, OPTS);
  out.float.restoreLegal = panel.at();
}
{
  // in the flow the restore stands down: left/top are inert and offsetWidth is the whole column
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  panel.position = "static";
  const env = makeEnv(panel, "tw_probe_pos", { left: 600, top: 300 }, { w: 1100, h: 900 });
  loadTW(env).floatPanel(panel, OPTS);
  out.float.restoreInFlow = { left: panel.style.left, top: panel.style.top, right: panel.style.right };
}
{
  // a full drag: follows the pointer, clamps at the bounds, ends clean, saves under ITS key only
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  const env = makeEnv(panel, "tw_probe_pos", undefined, WIN);
  loadTW(env).floatPanel(panel, OPTS);
  panel.style.left = "1000"; panel.style.top = "200";
  panel.fire("pointerdown", { clientX: 1010, clientY: 210 });
  const classDuring = panel.classList.contains("sh-dragging");
  panel.fire("pointermove", { clientX: 1110, clientY: 260 });       // 100 right, 50 down, in bounds
  const followed = panel.at();
  panel.fire("pointermove", { clientX: 9000, clientY: 9000 });      // hurled off the bottom-right
  const clamped = panel.at();
  panel.fire("pointerup", {});
  out.float.drag = {
    classDuring,
    classAfter: panel.classList.contains("sh-dragging"),
    followed,
    clamped,
    saved: JSON.parse(env.store["tw_probe_pos"] || "null"),
    keys: keysOf(env),
  };
  // and what was saved is what a fresh page load restores
  const again = makePanel("sheets", 256, 1000, "sh-drag");
  const env2 = makeEnv(again, "tw_probe_pos", out.float.drag.saved, WIN);
  loadTW(env2).floatPanel(again, OPTS);
  out.float.reloaded = again.at();
}
{
  // pointerdown anywhere but the header does not start a drag, so nothing moves and nothing saves
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  const env = makeEnv(panel, "tw_probe_pos", undefined, WIN);
  loadTW(env).floatPanel(panel, OPTS);
  panel.style.left = "1000"; panel.style.top = "200";
  panel.fire("pointerdown", { clientX: 1010, clientY: 210, target: { closest: () => null } });
  panel.fire("pointermove", { clientX: 1500, clientY: 800 });
  panel.fire("pointerup", {});
  out.float.offHandle = {
    at: panel.at(),
    classes: [...panel.classes],
    keys: keysOf(env),
  };
}
{
  // pointercancel (a touch interrupted, the window lost the pointer) ends the drag exactly as up does
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  const env = makeEnv(panel, "tw_probe_pos", undefined, WIN);
  loadTW(env).floatPanel(panel, OPTS);
  panel.style.left = "1000"; panel.style.top = "200";
  panel.fire("pointerdown", { clientX: 1010, clientY: 210 });
  panel.fire("pointermove", { clientX: 1060, clientY: 230 });
  panel.fire("pointercancel", {});
  out.float.cancel = {
    classAfter: panel.classList.contains("sh-dragging"),
    saved: JSON.parse(env.store["tw_probe_pos"] || "null"),
  };
}
{
  // no key: it still drags, but it neither reads a stored position nor writes one
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  const env = makeEnv(panel, "tw_probe_pos", { left: 600, top: 300 }, WIN);
  loadTW(env).floatPanel(panel, { handle: "sh-drag", draggingClass: "sh-dragging" });
  const restored = { left: panel.style.left, top: panel.style.top, right: panel.style.right };
  panel.style.left = "1000"; panel.style.top = "200";
  panel.fire("pointerdown", { clientX: 1010, clientY: 210 });
  panel.fire("pointermove", { clientX: 1110, clientY: 260 });
  panel.fire("pointerup", {});
  // the position seeded under the key is still the only thing in storage, and still the seeded one
  out.float.noKey = { restored, moved: panel.at(), keys: keysOf(env), stored: env.store["tw_probe_pos"] };
}
{
  // a wiped or corrupt stored value just means it opens where the CSS put it
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  const env = makeEnv(panel, "tw_probe_pos", undefined, WIN);
  env.store["tw_probe_pos"] = "{not json";
  let threw = false;
  try { loadTW(env).floatPanel(panel, OPTS); } catch (err) { threw = true; }
  out.float.corrupt = { threw, left: panel.style.left, top: panel.style.top, right: panel.style.right };
}
{
  // storage that throws (private mode, blocked site data) must not stop the panel being movable
  const panel = makePanel("sheets", 256, 1000, "sh-drag");
  const env = makeEnv(panel, "tw_probe_pos", undefined, WIN);
  env.localStorage = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
  };
  let threw = false;
  try {
    loadTW(env).floatPanel(panel, OPTS);
    panel.style.left = "1000"; panel.style.top = "200";
    panel.fire("pointerdown", { clientX: 1010, clientY: 210 });
    panel.fire("pointermove", { clientX: 1110, clientY: 260 });
    panel.fire("pointerup", {});
  } catch (err) { threw = true; }
  out.float.blocked = { threw, moved: panel.at(), classAfter: panel.classList.contains("sh-dragging") };
}
{
  // not laid out yet (offsetWidth 0): the declared width stands in, and 250 when none is declared
  const panelA = makePanel("sheets", 0, 0, "sh-drag");
  const envA = makeEnv(panelA, "tw_probe_pos", undefined, WIN);
  loadTW(envA).floatPanel(panelA, Object.assign({ width: 300 }, OPTS));
  panelA.style.left = "1000"; panelA.style.top = "200";
  panelA.fire("pointerdown", { clientX: 1010, clientY: 210 });
  panelA.fire("pointermove", { clientX: 9000, clientY: 200 });
  const declared = panelA.at().left;
  panelA.fire("pointerup", {});
  const panelB = makePanel("sheets", 0, 0, "sh-drag");
  const envB = makeEnv(panelB, "tw_probe_pos", undefined, WIN);
  loadTW(envB).floatPanel(panelB, OPTS);
  panelB.style.left = "1000"; panelB.style.top = "200";
  panelB.fire("pointerdown", { clientX: 1010, clientY: 210 });
  panelB.fire("pointermove", { clientX: 9000, clientY: 200 });
  out.float.unlaidOut = { declared, byDefault: panelB.at().left };
}
{
  // The RESTORE is where a panel is most likely not laid out: the rail is hidden at init, so it
  // reports offsetWidth 0 exactly when the saved position is read back. The declared width has to
  // stand in there as well, or the restore and the drag clamp the same panel to different edges.
  const restoreUnlaidOut = (opts) => {
    const panel = makePanel("sheets", 0, 0, "sh-drag");
    const env = makeEnv(panel, "tw_probe_pos", { left: 5000, top: 100 }, WIN);
    loadTW(env).floatPanel(panel, Object.assign({}, OPTS, opts));
    return panel.at();
  };
  out.float.unlaidOutRestore = {
    declared: restoreUnlaidOut({ width: 300 }),
    byDefault: restoreUnlaidOut({}),
  };
}
{
  // two panels on one page, one storage: each restores from and saves to its OWN key
  const a = makePanel("a", 256, 1000, "sh-drag");
  const b = makePanel("b", 256, 1000, "sh-drag");
  const env = makeEnv(a, "tw_a_pos", { left: 100, top: 120 }, WIN);
  env.store["tw_b_pos"] = JSON.stringify({ left: 900, top: 700 });
  const TWx = loadTW(env);
  TWx.floatPanel(a, { handle: "sh-drag", draggingClass: "sh-dragging", key: "tw_a_pos" });
  TWx.floatPanel(b, { handle: "sh-drag", draggingClass: "sh-dragging", key: "tw_b_pos" });
  const restored = { a: a.at(), b: b.at() };
  a.fire("pointerdown", { clientX: 110, clientY: 130 });
  a.fire("pointermove", { clientX: 210, clientY: 230 });
  a.fire("pointerup", {});
  out.float.twoPanels = {
    restored,
    a: JSON.parse(env.store["tw_a_pos"]),
    b: JSON.parse(env.store["tw_b_pos"]),
  };
}

// -- 8. each page caller hands the helper its OWN key, classes and width ---------------------
// Sections 2-6 cover the cheat sheet's restore and drag. These close the other gaps: the step-3
// rail's drag (it was only ever restored here), and both callers' fallback widths, which differ
// (240 and 250) and only show when the panel has not been laid out. A caller that dropped its
// `width`, or sent the other panel's key, would pass every restore test above and fail here.
{
  const panel = makePanel("options-panel", 0, 0, "op-drag");
  const env = makeEnv(panel, "tw_opts_pos", undefined, WIN);
  global.window = env.window;
  runInit("const RAW = " + iife(REVIEW, "initOptionsPanelDrag", "proposal-review.js") + ";",
    "RAW();", env);
  panel.style.left = "1000"; panel.style.top = "200";
  panel.fire("pointerdown", { clientX: 1010, clientY: 210 });
  const classDuring = panel.classList.contains("op-dragging");
  panel.fire("pointermove", { clientX: 9000, clientY: 9000 });
  const clamped = panel.at();
  panel.fire("pointerup", {});
  out.optsDrag = {
    classDuring,
    classAfter: panel.classList.contains("op-dragging"),
    clamped,
    saved: JSON.parse(env.store["tw_opts_pos"] || "null"),
    keys: keysOf(env),
  };
}
{
  const panel = makePanel("verbal-cheat", 0, 0, "vc-drag");
  const env = makeEnv(panel, "tw_vcheat_pos", undefined, WIN);
  global.window = env.window;
  runInit(fn(VERBAL, "initCheatDrag", "polish-verbal.js"), "initCheatDrag();", env);
  panel.style.left = "1000"; panel.style.top = "200";
  panel.fire("pointerdown", { clientX: 1010, clientY: 210 });
  panel.fire("pointermove", { clientX: 9000, clientY: 200 });
  out.cheatUnlaidOut = { left: panel.at().left };
}
{
  // The same two callers, but RESTORING a far-right saved position into a panel that is not laid
  // out yet (the rail is hidden at init). Each must clamp to its own declared width, the one its
  // drag already uses, so a position the drag could leave is a position the restore gives back.
  const restoreFar = (id, handle, key, init) => {
    const panel = makePanel(id, 0, 0, handle);
    const env = makeEnv(panel, key, { left: 5000, top: 100 }, WIN);
    global.window = env.window;
    runInit(init.body, init.call, env);
    return panel.at().left;
  };
  out.unlaidOutRestore = {
    rail: restoreFar("options-panel", "op-drag", "tw_opts_pos", {
      body: "const RAW = " + iife(REVIEW, "initOptionsPanelDrag", "proposal-review.js") + ";",
      call: "RAW();" }),
    cheat: restoreFar("verbal-cheat", "vc-drag", "tw_vcheat_pos", {
      body: fn(VERBAL, "initCheatDrag", "polish-verbal.js"), call: "initCheatDrag();" }),
  };
}

process.stdout.write(JSON.stringify(out) + "\n");
