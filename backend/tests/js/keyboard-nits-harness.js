"use strict";
/* ROUND 7 POLISH (2026-10-22), K1 AND K2: TWO KEYBOARD NITS FROM THE REAL-BROWSER WALK OF STAGING, run on the REAL estimate page: js/polish-estimate.js, whole, booted the way
 * polish-estimate-harness.js boots it, with the REAL js/bid-model.js beneath it. Every fact below is read off the page after it ran (what it drew, where it put the caret, whether it took the key).
 * test_v2_keyboard_nits.py holds each fact and breaks a COPY of the page one line at a time to prove each can change.
 *
 *   escape  K1: ESCAPE ON THE SHEETS PANEL'S "ADD A SHEET" LIST. Only the rename box took Escape; the list's Close button was a click and nothing else. Escape on a control of the panel while the
 *           list is open closes it, puts the caret back on the "Add sheet" button that opened it (sheetsUi.focus = "add|menu"), and is prevented. It does nothing, and is not prevented, while the
 *           list is shut or when the key was pressed outside the panel, and it never takes a key something else has taken: the rename box's own Escape cancels the rename and leaves the list open.
 *   steps   K2: THE CARET FOLLOWS A STEP THAT WAS PRESSED. Next, Back, a step on the rail and Edit on a Review card rebuild the panel and the rail, so the button that had the caret is gone and
 *           focus fell to <body>: the next Tab started from the top of the page. The new step's heading takes it (tabindex -1, focused with preventScroll so the page does not jump past the
 *           scroll to the top that go() asks for on purpose). Opening the page and a step set by a script (go()) take no caret.
 *
 * The stand-in DOM has no focus(), so, as sheets-panel-harness.js does, a scenario gives focus() to the elements a container hands back and records what it was called with.
 *
 * A section that throws reports `{ error }` instead of crashing, so a tree without the code fails an assertion with a reason.
 *
 * Usage: node keyboard-nits-harness.js <frontend-dir>   ->  one line of JSON
 */
const path = require("path");
const Module = require("module");
const L = require("./_lib.js");

const ROOT = path.resolve(process.argv[2]);

function loadPrelude(file, exportNames) {
  const base = path.join(__dirname, file);
  const code = L.read(base);
  const cut = code.indexOf("\nconst out = ");
  if (cut < 0) throw new Error(file + " no longer holds a top-level `const out = `: update the cut in keyboard-nits-harness.js");
  const m = new Module(base, module);
  m.filename = base;
  m.paths = Module._nodeModulePaths(path.dirname(base));
  m._compile(code.slice(0, cut) + "\nmodule.exports = { " + exportNames.join(", ") + " };\n", base);
  return m.exports;
}

const P = loadPrelude("polish-estimate-harness.js", ["build", "blob", "typeInto", "clickEl", "clickOn", "need", "MODEL"]);

const flush = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await flush(); };

async function open() {
  const b = P.build({});
  await b.api.init();
  await settle();
  return b;
}

const panelHtml = (b, id) => String(b.doc.getElementById(id).innerHTML || "");
const has = (b, sel) => !!b.doc.querySelector(sel);
/** Is the "Add a sheet" list drawn? Its group is the only place the page writes class="sh-pick". */
const listOpen = (b) => /class="sh-pick"/.test(panelHtml(b, "sheets-panel"));
/** Is the button that opens (and, open, closes) the list marked as holding it open? */
const expanded = (b) => { const m = /data-sh-act="add-(?:menu|close)"[^>]*aria-expanded="(true|false)"/.exec(panelHtml(b, "sheets-panel")); return m ? m[1] : null; };

/** A key pressed on `el`, as a browser hands it to the page: an event whose defaultPrevented turns true when a listener calls preventDefault (so a listener that comes after another can see
 *  that the key was taken). Answers whether any listener prevented it, or null when there was no control to press it on (a break that removes one changes a fact, it never crashes the run). */
function press(b, el, key) {
  if (!el) return null;
  const ev = { target: el, key: key, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
  b.doc.fire("keydown", ev);
  return ev.defaultPrevented;
}
const pressOn = (b, sel, key) => press(b, b.doc.querySelector(sel), key);

/** Give focus() to every element a container hands back and record each call: what it was focused for and whether it was told not to scroll. `mark` says what to note of the element. */
function watchFocus(container, mark) {
  const got = [];
  const realAll = container.querySelectorAll;
  container.querySelectorAll = (s) => realAll(s).map((n) => { n.focus = (o) => { got.push(Object.assign(mark(n), { noScroll: !!o && o.preventScroll === true })); }; return n; });
  return got;
}

const out = {};
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out[name] = { error: String((e && e.stack) || e) }; }
}

async function main() {
  // ═══ K1. ESCAPE ON THE "ADD A SHEET" LIST ═══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("escape", async () => {
    const b = await open();
    const focused = watchFocus(b.doc.getElementById("sheets-panel"), (n) => ({ key: n.attrs["data-sh-key"] }));
    const at = () => ({ open: listOpen(b), expanded: expanded(b) });
    // Every step starts from the list SHUT, whatever the one before did (a page that ignores Escape leaves it open): the Close button shuts it, the caret record is cleared, and the list is opened
    // again by the button that opens it. Each answers what the press of the button left the caret on.
    const shut = () => { if (has(b, '[data-sh-act="add-close"]')) P.clickOn(b, '[data-sh-act="add-close"]'); focused.splice(0); };
    const openList = () => { shut(); if (has(b, '[data-sh-act="add-menu"]')) P.clickOn(b, '[data-sh-act="add-menu"]'); return focused.splice(0); };
    const res = { shut: at() };

    // (a) open it with the mouse or Enter: the caret goes to its Close button; Escape on that button closes it, puts the caret back on "Add sheet", and the key is taken
    const onOpen = openList();
    res.opened = { state: at(), focus: onOpen };
    const prevented = pressOn(b, '[data-sh-act="add-close"]', "Escape");
    res.closed = { state: at(), focus: focused.splice(0), prevented: prevented };

    // (b) Escape with the list shut does nothing, and is not taken (it is not the page's to swallow)
    shut();
    const idle = pressOn(b, '[data-sh-act="add-menu"]', "Escape");
    res.shut2 = { state: at(), focus: focused.splice(0), prevented: idle };

    // (c) Escape on one of the list's own rows does the same as on its Close button
    openList();
    const row = pressOn(b, '[data-sh-act="add"]', "Escape");
    res.fromRow = { state: at(), focus: focused.splice(0), prevented: row };

    // (d) another key does not close it
    openList();
    const other = pressOn(b, '[data-sh-act="add-close"]', "Tab");
    res.otherKey = { state: at(), focus: focused.splice(0), prevented: other };

    // (e) Escape pressed OUTSIDE the panel (a button of the step) leaves the list as it is and is not taken
    openList();
    const outside = pressOn(b, '[data-go="1"]', "Escape");
    res.outside = { state: at(), focus: focused.splice(0), prevented: outside };

    // (f) the rename box's own Escape cancels the rename and the key is taken: the list stays open for a second Escape, which closes it
    openList();
    if (has(b, '[data-sh-act="rename"]')) P.clickOn(b, '[data-sh-act="rename"]');
    focused.splice(0);
    const renamingBefore = has(b, "[data-sh-name]");
    const first = pressOn(b, "[data-sh-name]", "Escape");
    const afterRename = { renamingBefore: renamingBefore, renaming: has(b, "[data-sh-name]"), state: at(), focus: focused.splice(0), prevented: first };
    const second = pressOn(b, '[data-sh-act="add-close"]', "Escape");
    res.renameFirst = { first: afterRename, second: { state: at(), focus: focused.splice(0), prevented: second } };
    return res;
  });

  // ═══ K2. THE CARET FOLLOWS A STEP THAT WAS PRESSED ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
  await section("steps", async () => {
    const b = await open();
    const focused = watchFocus(b.doc.getElementById("panels"), (n) => ({ tag: n.tag, text: n.textContent, tabindex: n.getAttribute("tabindex") }));
    const res = { onOpen: focused.splice(0) };
    // a step set by a script (go) takes no caret
    b.api.go(1);
    res.byScript = { at: b.api.at(), focus: focused.splice(0) };
    b.api.go(0);
    focused.splice(0);

    const pressed = (what, doIt) => { doIt(); return { what: what, at: b.api.at(), focus: focused.splice(0) }; };
    // Next on the Material step, then Back on the Labor step
    res.next = pressed("next", () => P.clickOn(b, '[data-go="1"]'));
    res.back = pressed("back", () => P.clickOn(b, '[data-go="0"]'));
    // a step on the rail: its buttons are drawn by paintRail, each with its own click listener
    const rail = b.dom.get("rail").kids;
    res.rail = pressed("rail", () => rail[2] && rail[2].listeners.filter((l) => l.type === "click").forEach((l) => l.handler({})));
    // Edit on a card of the Review goes back to the step the card is about
    res.edit = pressed("edit", () => P.clickOn(b, '[data-go="0"]'));
    // ...and the rail again, now the other way
    const rail2 = b.dom.get("rail").kids;
    res.railBack = pressed("railBack", () => rail2[0] && rail2[0].listeners.filter((l) => l.type === "click").forEach((l) => l.handler({})));
    return res;
  });

  return out;
}

main().then((o) => console.log(JSON.stringify(o))).catch((e) => { console.error(e && e.stack || e); process.exit(1); });
