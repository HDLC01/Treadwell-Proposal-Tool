"use strict";
/* THE FIXED TOTAL BAR'S HEIGHT REACHES THE PAGE'S PADDING (round 6 audit, U2): js/polish-estimate.js, whole, booted the way polish-estimate-harness.js boots it.
 *
 * #bidbar is position:fixed, so it takes no room in the page, and the page keeps its last row clear of it with the body's padding-bottom, which is the bar's height
 * and a little air (--bid-h, see polish-estimate.html). The height is not a constant: with the staff sidebar open the bar is narrower than the window and wraps its
 * sums onto a second row, so the page script reads it off the bar and writes it onto the html element, as it does the sticky head's (--v2head-h).
 *
 * A headless run lays nothing out, so a bar is given a box here, and its height is what a scenario says (or, where the ORDER of the work matters, a function of the
 * words the page has written into the bar, the way a real bar grows a row as it says more). What is read back is the custom property the page wrote.
 *
 *   observed   a browser WITH a ResizeObserver: the page watches the bar, a repaint of the bar measures nothing, the observer's word is written (rounded up), and a
 *              bar with no height (hidden, or not laid out) leaves the last good figure
 *   plain      a browser WITHOUT one: the bar's first drawing, a repaint through the job bid (a bid of several sheets draws the bar another way) and the window's
 *              resize tell the page; a repaint measures AFTER the bar's words are written; one resize listener of the bar's own; no html element is no error
 *   noLayout   a page with no layout at all (the stand-in DOM, as every other harness has it): nothing is written and nothing throws
 *
 * Usage: node bid-bar-height-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in bid-bar-height-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "clickOn"]);

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 12; i++) await flush(); };

/** What the page last told the browser the bar's height is (--bid-h on the html element), "" when it never has. */
const barProp = (b) => b.doc.documentElement.style.getPropertyValue("--bid-h");
/** Give the bar a box: a number, or a function called each time the page measures (the stand-in DOM has no layout). */
const barBox = (b, height) => { b.dom.get("bidbar").getBoundingClientRect = () => ({ height: typeof height === "function" ? height() : height }); };
const maths = (b) => b.dom.get("maths").textContent;
/** The window's resize listeners that are the bar's own: the page's listeners are named functions. */
const resizeListeners = (b, name) => b.win.listeners.filter((l) => l.type === "resize" && l.handler && l.handler.name === name).length;

/** A ResizeObserver stand-in: it remembers what it was asked to watch, and a scenario says "it changed" by firing it. */
function observerClass() {
  const made = [];
  const cls = class { constructor(cb) { this.cb = cb; this.targets = []; made.push(this); } observe(t) { this.targets.push(t); } disconnect() { this.targets = []; } };
  return { cls: cls, made: made, fire: () => made.forEach((o) => o.cb([], o)) };
}

async function observed() {
  const ro = observerClass();
  const b = P.build({ blob: P.blob({}), resizeObserver: ro.cls });
  barBox(b, 120);
  await b.api.init();
  await settle();
  const watching = ro.made.filter((o) => o.targets.some((t) => t.attrs.id === "bidbar"));
  const watched = { observers: watching.length, targets: watching.map((o) => o.targets.map((t) => t.attrs.id)), resizeListeners: resizeListeners(b, "syncBarHeight") };
  // the page's own drawing of the bar (init) and a repaint (what every keystroke is) measure nothing when there is an observer: it is the one that does
  const idle = barProp(b);
  b.api.changed(false);
  const afterRepaint = barProp(b);
  ro.fire();
  const first = barProp(b);
  barBox(b, 150.2);
  ro.fire();
  const second = barProp(b);
  barBox(b, 0);
  ro.fire();
  const none = barProp(b);
  return { watched: watched, heights: { idle: idle, afterRepaint: afterRepaint, first: first, second: second, none: none } };
}

async function plain() {
  const b = P.build({ blob: P.blob({}) });
  // taller the more the bar says: a stand-in for words wrapping onto another row, and what makes "measured after the words were written" a number
  barBox(b, () => 60 + maths(b).length);
  await b.api.init();
  await settle();
  const single = { painted: barProp(b), mathsLen: maths(b).length };
  // a bid of several sheets draws the bar another way (paintJobBid, and an early return out of paintBid): Copy repaints it that way
  P.clickOn(b, '[data-sh-act="copy"][data-sh-tab="Polish"]');
  await settle();
  const job = { painted: barProp(b), mathsLen: maths(b).length };
  barBox(b, 188.4);
  b.win.fire("resize");
  const resized = barProp(b);
  barBox(b, 0);
  b.win.fire("resize");
  const none = barProp(b);
  const listeners = resizeListeners(b, "syncBarHeight");
  // a document with no html element to write to is no error either (the bar has a height again, so that is what would be written to it)
  barBox(b, 100);
  delete b.doc.documentElement;
  let noRoot = true;
  try { b.win.fire("resize"); } catch (e) { noRoot = false; }
  return { single: single, job: job, resized: resized, none: none, listeners: listeners, noRoot: noRoot };
}

async function noLayout() {
  const b = P.build({ blob: P.blob({}) });
  let threw = false;
  try {
    await b.api.init();
    await settle();
    b.api.changed(false);
    b.win.fire("resize");
  } catch (e) { threw = String(e && e.stack || e); }
  return { value: barProp(b), threw: threw };
}

async function main() {
  const out = {};
  for (const [name, fn] of [["observed", observed], ["plain", plain], ["noLayout", noLayout]]) {
    try { out[name] = await fn(); } catch (e) { out[name] = { error: String(e && e.stack || e) }; }
  }
  process.stdout.write(JSON.stringify(out) + "\n");
}

main().catch((e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
