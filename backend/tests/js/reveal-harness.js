"use strict";
/* THE WIZARD PAGES' CROSS-FADE HOLD (Hanz, 2026-10-29), RUN rather than read.
 *
 * "In the files page we should also look into it because when I transfer tabs with multiple
 * proposals it flashes white as well." Every switch of proposal and every step pill is a real page
 * load; reveal.css cross-fades it and js/reveal.js holds the fade on the old page until the new one
 * has drawn its content AND its sidebar, capped at 1.5 s.
 *
 * What runs here:
 *   * frontend/js/reveal.js, whole, in a fresh vm context per scenario, over a fake document whose
 *     clock, animation frames, animations, sidebar and on-screen elements each scenario drives;
 *   * the pages' own "drawn" calls, lifted from the shipped files and run in that same context on
 *     top of the real reveal.js: done.js refreshFilesProposals (the Files page's list of proposals)
 *     and its readyProposals block (the pre-generate card's list), and proposal-review.js's boot
 *     statements from `const _tabsMounted = ` through its TWReveal line.
 *
 * Usage: node reveal-harness.js [frontend-dir]   ->  one line of JSON
 * The optional directory may hold only SOME files (js/reveal.js, js/done.js, js/proposal-review.js);
 * the rest come from the real frontend. test_wizard_page_fade.py breaks one there and requires a
 * scenario to go red.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const L = require("./_lib.js");

const REAL = path.resolve(__dirname, "..", "..", "..", "frontend");
const FRONT = process.argv[2] ? path.resolve(process.argv[2]) : REAL;
const pick = (p) => (fs.existsSync(path.join(FRONT, p)) ? path.join(FRONT, p) : path.join(REAL, p));
const REVEAL = L.read(pick(path.join("js", "reveal.js")));
const DONE = L.read(pick(path.join("js", "done.js")));
const PROPOSAL = L.read(pick(path.join("js", "proposal-review.js")));
const NL = "\n";

/** One page load: the real reveal.js over a fake document. */
function page(opts) {
  const o = opts || {};
  const classes = new Set();
  const frames = [];
  const timers = [];
  const listeners = {};
  const present = new Set(o.present || []);     // selectors (one '#id' each) that match an element
  const shown = new Set(o.shown || []);         // ...and of those, the ones with a box on screen
  const anims = [];
  let now = 0;
  let sidebar = !!o.sidebar;
  const document = {
    documentElement: {
      getAttribute: (n) => (n === "data-tw-drawn" ? (o.rule || null) : null),
      classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
    },
    querySelectorAll: (sel) => String(sel).split(",").map((s) => s.trim()).filter((s) => present.has(s))
      .map((s) => ({ getClientRects: () => (shown.has(s) ? [{}] : []) })),
    getElementById: (id) => (id === "tw-sidebar" && sidebar ? {} : null),
    getAnimations: () => anims.slice(),
  };
  const ctx = vm.createContext({
    document, console, Promise,
    requestAnimationFrame: (f) => { frames.push(f); },
    setTimeout: (f, ms) => { timers.push({ at: now + (ms || 0), f }); },
    addEventListener: (t, h) => { (listeners[t] = listeners[t] || []).push(h); },
  });
  ctx.window = ctx;
  vm.runInContext(REVEAL, ctx, { filename: "reveal.js" });
  const api = {
    ctx,
    booting: () => classes.has("tw-booting"),
    /** A cross-document transition reaching this page: its pseudo-element animations, running. */
    transition(ready) {
      const mk = (pe) => ({ effect: { pseudoElement: pe }, state: "running",
                            pause() { this.state = "paused"; }, play() { this.state = "running"; } });
      anims.push(mk("::view-transition-old(root)"), mk("::view-transition-new(root)"), mk(null));
      (listeners.pagereveal || []).forEach((h) => h({ viewTransition: { ready } }));
    },
    vtStates: () => anims.filter((a) => a.effect.pseudoElement).map((a) => a.state),
    otherState: () => anims.filter((a) => !a.effect.pseudoElement).map((a) => a.state)[0],
    frame() { frames.splice(0).forEach((f) => f()); },
    advance(ms) {
      now += ms;
      timers.filter((t) => t.at <= now && !t.ran).forEach((t) => { t.ran = true; t.f(); });
    },
    sidebarUp() { sidebar = true; },
    show(sel) { present.add(sel); shown.add(sel); },
    add(sel) { present.add(sel); },
    released: () => ctx.TWReveal.released(),
  };
  return api;
}

const flush = () => new Promise((r) => setImmediate(r));
function deferred() {
  let resolve, reject;
  const p = new Promise((a, b) => { resolve = a; reject = b; });
  return { p, resolve, reject };
}
const allPaused = (s) => s.length > 0 && s.every((x) => x === "paused");
const allRunning = (s) => s.length > 0 && s.every((x) => x === "running");

const out = {};

async function scenarios() {
  // 1. The fade waits for BOTH the page's content and the sidebar, then plays.
  {
    const w = page();
    w.transition(Promise.resolve());
    await flush();
    w.frame();
    const pausedAtStart = allPaused(w.vtStates());
    const bootingAtStart = w.booting();
    w.ctx.TWReveal.done();
    w.frame(); w.frame();
    const stillHeldWithoutSidebar = allPaused(w.vtStates()) && !w.released();
    w.sidebarUp();
    w.frame();
    out.hold = { pausedAtStart, bootingAtStart, stillHeldWithoutSidebar,
                 playedOnceReady: allRunning(w.vtStates()) && w.released(), unbooted: !w.booting() };
  }
  // 2. Only the view-transition's own animations are held, never the page's.
  {
    const w = page();
    w.transition(Promise.resolve());
    await flush();
    out.onlyVt = { vtPaused: allPaused(w.vtStates()), otherRunning: w.otherState() === "running" };
  }
  // 3. The cap: a page that never draws (an error, a redirect, a fatal card) is released at 1.5 s.
  {
    const w = page();
    w.transition(Promise.resolve());
    await flush();
    w.advance(1499); w.frame();
    const heldAt1499 = allPaused(w.vtStates()) && w.booting();
    w.advance(1);
    out.cap = { heldAt1499, releasedAt1500: allRunning(w.vtStates()) && !w.booting() && w.released() };
  }
  // 4. The page's rule: an element matching it must be ON SCREEN, not merely in the markup.
  {
    const w = page({ rule: "#gen-list > li, #gen-empty", sidebar: true });
    w.transition(Promise.resolve());
    await flush();
    w.add("#gen-empty");                  // in the markup, `hidden`
    w.frame(); w.frame();
    const heldWhileHidden = allPaused(w.vtStates());
    w.show("#gen-list > li");
    w.frame();
    out.rule = { heldWhileHidden, releasedOnceShown: allRunning(w.vtStates()) };
  }
  // 5. done(a, b) waits for both to settle, and a failed one still counts.
  {
    const w = page({ sidebar: true });
    w.transition(Promise.resolve());
    await flush();
    const a = deferred(); const b = deferred();
    w.ctx.TWReveal.done(a.p, b.p);
    a.resolve(); await flush(); w.frame();
    const heldOnOne = allPaused(w.vtStates());
    b.reject(new Error("template fetch failed")); await flush(); w.frame();
    out.waits = { heldOnOne, releasedOnBoth: allRunning(w.vtStates()) };
  }
  // 6. No transition (an old browser, reduced motion, a first visit): nothing to hold, and the
  //    sidebar's slide is still off only until the page has drawn.
  {
    const w = page({ sidebar: true });
    const booting = w.booting();
    w.ctx.TWReveal.done();
    w.frame();
    out.noVt = { booting, unbootedOnDraw: !w.booting() && w.released() };
  }
  // 7. A page that drew before the transition was ready: nothing is paused afterwards.
  {
    const w = page({ sidebar: true });
    const ready = deferred();
    w.transition(ready.p);
    w.ctx.TWReveal.done();
    w.frame();
    ready.resolve(); await flush();
    out.early = { notPaused: allRunning(w.vtStates()) };
  }
  // 8. A skipped transition (its ready rejects) throws nothing.
  {
    const w = page();
    const ready = deferred();
    w.transition(ready.p);
    ready.reject(new Error("skipped"));
    await flush();
    out.skipped = { ok: true };
  }

  // ── the pages' own "drawn" calls, run on the real reveal.js ─────────────────────────────────
  // 9. Files page: the list of proposals is drawn after its read, and only then is the page drawn.
  {
    const w = page({ sidebar: true });
    w.transition(Promise.resolve());
    await flush();
    const read = deferred();
    const log = [];
    const src = L.grabConst(DONE, "filesProposals", { indent: "  ", where: "done.js" }) + NL
      + L.liftSource(DONE, "refreshFilesProposals", { indent: "  ", where: "done.js" }) + NL
      + "refreshFilesProposals();";
    w.ctx.TW = { getDraftId: () => "d1", readProposals: () => read.p };
    w.ctx.document.getElementById = ((orig) => (id) => (id === "lump-row" || id === "lump-sum" ? null : orig(id)))(w.ctx.document.getElementById);
    w.ctx.paintFilesProposals = () => { log.push("paint:" + w.released()); };
    vm.runInContext("(function () {" + src + "})()", w.ctx, { filename: "done.js#refreshFilesProposals" });
    await flush(); w.frame();
    const heldWhileReading = allPaused(w.vtStates());
    read.resolve({ members: [{ id: "d1" }, { id: "d2" }] });
    await flush(); w.frame();
    out.filesList = { heldWhileReading, paintedBeforeRelease: log[0] === "paint:false",
                      releasedAfterPaint: allRunning(w.vtStates()) };
  }
  // 10. Files page, pre-generate card: the same after its list of proposals.
  {
    const w = page({ sidebar: true });
    w.transition(Promise.resolve());
    await flush();
    const read = deferred();
    const at = DONE.indexOf("(async function readyProposals()");
    if (at < 0) throw new Error("the readyProposals block is gone from done.js -- repoint this harness");
    const body = L.balanced(DONE, DONE.indexOf("{", at));
    const block = DONE.slice(at, DONE.indexOf(";", body) + 1);
    let painted = false;
    w.ctx.TW = { getDraftId: () => "d1", readProposals: () => read.p };
    w.ctx.paintReadyProposals = () => { painted = true; };
    vm.runInContext(block, w.ctx, { filename: "done.js#readyProposals" });
    await flush(); w.frame();
    const heldWhileReading = allPaused(w.vtStates());
    read.resolve(null);
    await flush(); w.frame();
    out.readyList = { heldWhileReading, painted, released: allRunning(w.vtStates()) };
  }
  // 11. Proposal page: drawn once the tab strip AND the document are both on screen.
  {
    const w = page({ sidebar: true });
    w.transition(Promise.resolve());
    await flush();
    const start = PROPOSAL.indexOf("const _tabsMounted = ");
    const call = start < 0 ? -1 : PROPOSAL.indexOf("TWReveal.done(", start);
    if (start < 0 || call < 0) throw new Error("proposal-review.js's boot statements are gone -- repoint this harness");
    const end = PROPOSAL.indexOf(";", call) + 1;
    const tabs = deferred(); const doc = deferred();
    w.ctx.mountProposalTabs = () => tabs.p;
    w.ctx.initDocumentEditor = () => doc.p;
    vm.runInContext("(function () {" + PROPOSAL.slice(start, end) + "})()", w.ctx,
                    { filename: "proposal-review.js#boot" });
    tabs.resolve({}); await flush(); w.frame();
    const heldOnTabsAlone = allPaused(w.vtStates());
    doc.resolve(); await flush(); w.frame();
    out.proposal = { heldOnTabsAlone, releasedOnBoth: allRunning(w.vtStates()) };
  }
}

scenarios().then(
  () => { console.log(JSON.stringify(out)); },
  (e) => { console.log(JSON.stringify({ error: String((e && e.stack) || e) })); process.exitCode = 1; });
