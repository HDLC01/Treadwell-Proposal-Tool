"use strict";
/* THE SHEET'S ZOOM, FITTED TO THE SPACE IT REALLY HAS -- run, not read.
 *
 * Audit, 2026-10-02 (staging, Direct epoxy): on most fresh loads at laptop widths the Proposal
 * step drew the sheet too big -- scale(1.577) where scale(1.283) fits at innerWidth 1600 -- with its
 * left ~108px behind the sidebar and its right edge under the floating Pricing options panel, and a
 * 1px window resize put it right. Measured on the bad loads, the sheet was the canvas's clientWidth
 * minus 56 instead of minus 296: 240px too wide, the width of the nav rail auth.js puts on <body>.
 *
 * applyZoom read the canvas once per call, and the only thing that called it again later was the
 * WINDOW's resize event. The space the sheet may take changes without one: the nav rail is a body
 * margin added when the sidebar is drawn, the pricing rail's 272px is padding a :has() rule adds
 * when #options-panel is shown, and below 1400px that panel moves inline.
 *
 * This lifts the SHIPPED syncZoomOuter / zoomFitKey / refitZoomToCanvas / applyZoom out of
 * proposal-review.js and runs them over the smallest layout model that can show the bad state: a
 * canvas whose width follows the body margin, whose padding follows the rail, and whose scrollbar
 * follows how tall the zoomed sheet is -- with a ResizeObserver that reports the way a browser does
 * (once on observe, then only when the observed box changes size).
 *
 * Usage: node doc-zoom-harness.js <frontend-dir>   ->   one line of JSON
 */
const fs = require("fs");
const path = require("path");

// Normalized to LF, like every harness here: the checkout is CRLF and the lifts anchor on "\n  ".
const SRC = fs.readFileSync(path.join(process.argv[2], "js", "proposal-review.js"), "utf8")
  .replace(/\r\n/g, "\n");

function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone from proposal-review.js — rewrite this harness, don't delete it");
  const open = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = open; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

// ── the layout model ─────────────────────────────────────────────────────────────────────────
const PX_PER_PT = 96 / 72;
const NAV_W = 240;          // auth.js --tw-w, the body margin while the rail is open (>= 768px)
const RAIL_PAD = 272;       // proposal-review.html: the canvas's padding-right while the panel shows
const SCROLLBAR = 17;       // a classic (non-overlay) scrollbar
const PAGE_W_PT = 612;
const DOC_H_PT = 792 * 4;   // four sheets of paper, unzoomed

function makeWorld(opts) {
  const o = Object.assign({ innerWidth: 1600, innerHeight: 900, navOpen: true, railShown: true,
                            docHPt: DOC_H_PT, canvasH: 760 }, opts || {});
  const world = { o: o, observers: [] };

  // `navAt` is the margin mid-transition (auth.js: body{transition:margin-left .2s ease}); when it
  // is not set the margin is wherever the open state says it ends up.
  const navMargin = () => (o.navAt != null ? o.navAt : (o.navOpen && o.innerWidth >= 768 ? NAV_W : 0));
  // Below 1400px the panel is static, above the canvas, and the reservation is dropped.
  const padRight = () => (o.railShown && o.innerWidth > 1400 ? RAIL_PAD : 0);

  const docZoom = { style: {}, getBoundingClientRect() {
    const m = /scale\(([\d.]+)\)/.exec(this.style.transform || "");
    const k = m ? Number(m[1]) : 1;
    return { width: PAGE_W_PT * PX_PER_PT * k, height: o.docHPt * PX_PER_PT * k, left: 0, top: 0 };
  } };
  const docZoomOuter = { style: {} };

  // The canvas scrolls when the zoomed sheet is taller than it, and its scrollbar then eats into
  // clientWidth -- but never into offsetWidth, the border box.
  const scrolls = () => docZoom.getBoundingClientRect().height > o.canvasH;
  const canvas = {
    get offsetWidth() { return o.innerWidth - navMargin(); },
    get clientWidth() { return this.offsetWidth - (scrolls() ? SCROLLBAR : 0); },
  };
  const getComputedStyle = (el) => {
    if (el !== canvas) throw new Error("the fit read the computed style of something other than the canvas");
    return { paddingLeft: "0px", paddingRight: padRight() + "px" };
  };
  const document = { querySelector: (sel) => (sel === ".word-canvas" ? canvas : null) };

  // A ResizeObserver as a browser runs one: every observed element is reported once after
  // observe(), and again only when its CONTENT box changed since its last report. deliver() is one
  // rendering opportunity; the browser keeps delivering in the same frame while reports are due,
  // up to a limit, which is modelled by the caller running deliver() in a bounded loop.
  const contentBox = (el) => {
    if (el === canvas) {
      const cs = getComputedStyle(canvas);
      return [canvas.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight),
              o.canvasH].join("x");
    }
    const r = docZoom.getBoundingClientRect();     // the observer on #doc-zoom
    return [r.width, r.height].join("x");
  };
  class ResizeObserver {
    constructor(cb) { this.cb = cb; this.targets = []; world.observers.push(this); }
    observe(el) { this.targets.push({ el: el, last: null }); }
    disconnect() { this.targets = []; }
  }
  world.deliver = () => {
    let reported = 0;
    for (const ob of world.observers.slice()) {
      const due = ob.targets.filter((t) => contentBox(t.el) !== t.last);
      if (!due.length) continue;
      due.forEach((t) => { t.last = contentBox(t.el); });
      reported += due.length;
      ob.cb(due.map((t) => ({ target: t.el })));
    }
    return reported;
  };
  /** A frame: deliver until nothing is due, or give up the way a browser does after a loop limit. */
  world.settle = (limit) => {
    let rounds = 0;
    while (world.deliver() && ++rounds < (limit || 40)) { /* keep delivering */ }
    return rounds;
  };

  const window = { ResizeObserver: ResizeObserver, addEventListener() {} };
  // The lifted functions, bound to this world. `let` state the shipped file keeps beside them is
  // declared here under the same names, which is all a lift of a function body needs.
  // ResizeObserver as a bare global too: the page reads `window.ResizeObserver` to test for it and
  // constructs the global, which in a browser is the same object.
  const make = new Function("document", "window", "ResizeObserver", "getComputedStyle", "docZoom",
    "docZoomOuter", "pageWpt",
    `let _zoomRO = null; let _canvasRO = null; let _zoomFitKey = "";
     ${fn("syncZoomOuter")}
     ${fn("zoomFitKey")}
     ${fn("refitZoomToCanvas")}
     ${fn("applyZoom")}
     return { applyZoom: applyZoom };`);
  const api = make(document, window, ResizeObserver, getComputedStyle, docZoom, docZoomOuter, PAGE_W_PT);
  world.applyZoom = () => api.applyZoom();
  world.snapshot = () => {
    const r = docZoom.getBoundingClientRect();
    const cs = getComputedStyle(canvas);
    const room = canvas.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const m = /scale\(([\d.]+)\)/.exec(docZoom.style.transform || "");
    return { k: m ? Math.round(Number(m[1]) * 1000) / 1000 : null,
             sheetPx: Math.round(r.width * 10) / 10, roomPx: room,
             fits: r.width <= room + 0.5,
             // The sheet is centred in the canvas's content box (align-items: center), so a sheet
             // wider than the room hangs that much past BOTH edges.
             overhangEachSidePx: Math.max(0, Math.round((r.width - room) / 2 * 10) / 10),
             outerMatches: docZoomOuter.style.width === r.width + "px" };
  };
  // A fit is a write of the transform -- applyZoom is the only writer -- so fits are counted as
  // writes, which includes every fit an observer starts on its own.
  world.countTransforms = () => {
    let n = 0;
    let v = docZoom.style.transform;
    Object.defineProperty(docZoom.style, "transform", {
      configurable: true, enumerable: true,
      get() { return v; }, set(x) { v = x; n++; },
    });
    return () => n;
  };
  return world;
}

const out = {};

// 1. THE AUDITED LOAD: the first fit happens before the sidebar's margin is on <body> (the canvas
//    is the full window wide), then the rail goes up. No window resize follows.
{
  const w = makeWorld({ innerWidth: 1600, navOpen: false, railShown: true });
  w.applyZoom(); w.settle();
  const before = w.snapshot();
  w.o.navOpen = true; w.settle();
  out.navArrivesLate = { firstFit: before, afterRail: w.snapshot() };
}
// THE CAUSE, frame by frame: auth.js draws the sidebar and ANIMATES <body>'s margin-left from 0 to
// 240px over 200ms. The first fit lands early in it; each later frame reports a narrower canvas.
{
  const w = makeWorld({ innerWidth: 1600, navAt: 0, railShown: true });
  const writes = w.countTransforms();
  w.applyZoom(); w.settle();
  const first = w.snapshot();
  const frames = [24, 70, 130, 190, 228, 240];         // an ease curve, sampled once a frame
  for (const m of frames) { w.o.navAt = m; w.settle(); }
  out.navTransition = { firstFit: first, end: w.snapshot(), writes: writes(), frames: frames.length };
}
// The same at innerWidth 1440, the other width the audit measured.
{
  const w = makeWorld({ innerWidth: 1440, navOpen: false, railShown: true });
  w.applyZoom(); w.settle();
  w.o.navOpen = true; w.settle();
  out.navArrivesLate1440 = w.snapshot();
}

// 2. THE PRICING RAIL'S RESERVATION ARRIVES LATE: the first fit runs while #options-panel is still
//    hidden (no 272px padding), then renderProposalExtras shows it.
{
  const w = makeWorld({ innerWidth: 1600, navOpen: true, railShown: false });
  w.applyZoom(); w.settle();
  const before = w.snapshot();
  w.o.railShown = true; w.settle();
  out.railArrivesLate = { firstFit: before, afterRail: w.snapshot() };
}

// 3. AND GOES AGAIN: hiding the panel (no priced tabs) gives the sheet its width back, and the
//    collapse button on the nav rail does the same.
{
  const w = makeWorld({ innerWidth: 1600, navOpen: true, railShown: true });
  w.applyZoom(); w.settle();
  w.o.railShown = false; w.settle();
  const noRail = w.snapshot();
  w.o.navOpen = false; w.settle();
  out.spaceGrows = { noRail: noRail, noRailNoNav: w.snapshot() };
}

// 4. THE SCROLLBAR CANNOT START A LOOP. The canvas is exactly as tall as the sheet is at one of the
//    two zooms, so a fit that followed clientWidth would bring the scrollbar in, fit narrower, take
//    it away, fit wider... The browser gives up on such a loop after a limit and leaves whichever
//    zoom it stopped on; the fit must instead settle in one or two writes.
{
  // Height where the sheet at the no-scrollbar zoom overflows and at the scrollbar zoom does not.
  const W = 1600, avail = W - NAV_W - RAIL_PAD - 24;
  const kWide = avail / (PAGE_W_PT * PX_PER_PT), kNarrow = (avail - SCROLLBAR) / (PAGE_W_PT * PX_PER_PT);
  const canvasH = DOC_H_PT * PX_PER_PT * (kWide + kNarrow) / 2;
  const w = makeWorld({ innerWidth: W, navOpen: true, railShown: true, canvasH: canvasH });
  const writes = w.countTransforms();
  w.applyZoom();
  const rounds = w.settle(40);
  out.scrollbarThreshold = { writes: writes(), rounds: rounds, after: w.snapshot() };
}

// 5. THE CLAMP AND THE NARROW LAYOUTS ARE UNCHANGED.
{
  const huge = makeWorld({ innerWidth: 3840 }); huge.applyZoom(); huge.settle();
  const inlineRail = makeWorld({ innerWidth: 1300 }); inlineRail.applyZoom(); inlineRail.settle();
  const phone = makeWorld({ innerWidth: 380 }); phone.applyZoom(); phone.settle();
  out.clamp = { huge: huge.snapshot(), inlineRail1300: inlineRail.snapshot(), phone380: phone.snapshot() };
}

// 6. A STEADY PAGE IS NOT RE-FITTED. Reports that change nothing the fit depends on -- the
//    observer's first report, a height change of the canvas -- write no new transform.
{
  const w = makeWorld({ innerWidth: 1600 });
  w.applyZoom(); w.settle();
  const writes = w.countTransforms();
  w.o.canvasH = 500; w.settle();          // a taller ribbon row: height only
  w.o.canvasH = 900; w.settle();
  out.steady = { writes: writes(), after: w.snapshot() };
}

process.stdout.write(JSON.stringify(out) + "\n");
