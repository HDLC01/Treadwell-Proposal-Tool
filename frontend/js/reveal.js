"use strict";
// Hold the page-to-page cross-fade on the wizard pages until the new page has something to show.
//
// Hanz, 2026-10-29: "In the files page we should also look into it because when I transfer tabs
// with multiple proposals it flashes white as well." Switching proposals (the Lump sums list on
// Files, the proposal tab strip on Proposal) and every step pill is a REAL page load, on purpose:
// the one localStorage draft slot and each page's one-shot `TW.getState()` snapshot depend on it.
// What changes is how the load LOOKS. /reveal.css opts these pages into a cross-document view
// transition, so the browser cross-fades from the old page to the new one instead of showing the
// new one empty while its scripts fetch the draft.
//
// WHY THE FADE IS HELD. The browser captures the new page at its FIRST frame, and on these pages
// that frame has no content (every card, list and document is drawn after an API call) and no
// sidebar (auth.js puts it up after /api/me). Left alone, the fade would go from the proposal to an
// empty page, and then the content would pop in and the page slide right under the sidebar. So the
// fade's animations are paused at their first frame (the old page, still fully opaque) until:
//   1. the page has DRAWN: it called TWReveal.done() (done.js after its list of proposals,
//      proposal-review.js after its tab strip and document), or an element matching the page's
//      `<html data-tw-drawn="selector">` is on screen (the static pages: the intake form, the grid,
//      the Generate rows); and
//   2. the sidebar is up (#tw-sidebar), so the chrome on both sides of the fade is the same and the
//      fade changes the content and nothing else;
// then played. The new side of the fade is a LIVE image of the page, so it shows what is there when
// it plays, not what was there when it was captured.
//
// Also, while the page boots, `html.tw-booting` turns off the sidebar's slide (reveal.css): the rail
// a desktop user keeps open is drawn open on arrival instead of shoving the page 240px sideways on
// every load. Opening and closing it later still slides.
//
// BOUNDED: released after HOLD_MS whatever happens (an error, a redirect, the sign-in page, a fatal
// card that never draws a sidebar), because the page under a running transition takes no clicks.
// Loaded in <head>, not with the other scripts, because `pagereveal` fires before the first frame
// and a listener added after it never hears it. A browser without cross-document transitions (or
// with reduced motion, see reveal.css) never gets a viewTransition here, and the page simply loads.
// A same-origin file, not an inline <script>: the CSP (nginx) refuses inline script.
(function () {
  var HOLD_MS = 1500;
  var root = document.documentElement;
  var rule = (root && root.getAttribute && root.getAttribute("data-tw-drawn")) || "";
  var drawn = false;
  var released = false;
  var held = [];

  if (root && root.classList) root.classList.add("tw-booting");

  function frame(f) {
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(f); else setTimeout(f, 16);
  }

  /** Is an element matching the page's rule on screen? `hidden`, display:none and a detached node
   *  all have no client rects. */
  function ruleShown() {
    if (!rule) return false;
    var els;
    try { els = document.querySelectorAll(rule); } catch (e) { return false; }
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el && typeof el.getClientRects === "function" && el.getClientRects().length) return true;
    }
    return false;
  }

  function sidebarUp() { return !!document.getElementById("tw-sidebar"); }

  function release() {
    if (released) return;
    released = true;
    if (root && root.classList) root.classList.remove("tw-booting");
    var a = held;
    held = [];
    for (var i = 0; i < a.length; i++) { try { a[i].play(); } catch (e) { /* already finished */ } }
  }

  // Asked once a frame until the page is ready or the cap fires; a frame is when it would show.
  function check() {
    if (released) return;
    if (!drawn && ruleShown()) drawn = true;
    if (drawn && sidebarUp()) { release(); return; }
    frame(check);
  }

  /** The page's own "I have drawn": called once its first content is on screen. Takes any promises
   *  to wait for first (settled either way, so a failed fetch still releases). */
  function done() {
    var waits = Array.prototype.slice.call(arguments);
    if (!waits.length) { drawn = true; return; }
    var left = waits.length;
    var one = function () { if (--left === 0) drawn = true; };
    for (var i = 0; i < waits.length; i++) Promise.resolve(waits[i]).then(one, one);
  }

  window.TWReveal = { done: done, released: function () { return released; } };

  frame(check);
  setTimeout(release, HOLD_MS);

  window.addEventListener("pagereveal", function (e) {
    var vt = e && e.viewTransition;
    if (!vt) return;
    vt.ready.then(function () {
      // Already released: a page that drew before the transition was ready, or a back/forward
      // restore of a page that had finished booting (its first frame IS its content).
      if (released || typeof document.getAnimations !== "function") return;
      held = document.getAnimations().filter(function (a) {
        var pe = a.effect && a.effect.pseudoElement;
        return typeof pe === "string" && pe.indexOf("::view-transition") === 0;
      });
      for (var i = 0; i < held.length; i++) held[i].pause();
    }).catch(function () { /* the transition was skipped: nothing to hold */ });
  });
})();
