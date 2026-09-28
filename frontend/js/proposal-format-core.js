// Run algebra for the proposal editor's formatting — pure functions, no DOM, no fetch.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT A "RUN" IS HERE.
//
// A block (one Word paragraph) is a list of runs: {text, bold?, italic?, underline?,
// size_pt?, tok?}. A key that is ABSENT means "inherit whatever the template says"; a key
// set to `false` means "explicitly off". Those are genuinely different instructions — an
// absent `bold` must leave Kyle's design alone, while `bold: false` has to un-bold a
// paragraph whose style is bold. The backend's `_set_paragraph_runs` reads them the same way,
// so the distinction has to survive every operation in this file.
//
// WHY THIS IS A SEPARATE FILE.
//
// The editor applies formatting by rebuilding a block from its runs rather than by calling
// execCommand — execCommand emits <b>/<i>/<u> TAGS, and the serialiser reads inline STYLES,
// so an execCommand bold would look right on screen and reach the customer's .docx as
// nothing at all. That makes this arithmetic the load-bearing part: get an offset wrong and
// the wrong words change. Pulling it out of the page's IIFE is what lets the tests exercise
// the code that actually ships instead of a copy of it that can quietly drift.
(function (root, factory) {
  var api = factory();
  root.TWFmt = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var RUN_KEYS = ["bold", "italic", "underline", "size_pt"];

  function runsLength(runs) {
    var n = 0;
    for (var i = 0; i < runs.length; i++) n += String(runs[i].text).length;
    return n;
  }

  /** Merge neighbouring runs that agree on every switch AND their token.
   *
   *  Token equality is part of it because a `.tw-fill` boundary is a real boundary: merging
   *  across it would dissolve the fill span on the next render and turn a live estimate value
   *  into frozen text. */
  function coalesce(runs) {
    var out = [];
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i], p = out[out.length - 1], same = false;
      if (p && (p.tok || null) === (r.tok || null)) {
        same = true;
        for (var k = 0; k < RUN_KEYS.length; k++) {
          if (p[RUN_KEYS[k]] !== r[RUN_KEYS[k]]) { same = false; break; }
        }
      }
      if (same) { p.text += r.text; continue; }
      var copy = {};
      for (var key in r) if (Object.prototype.hasOwnProperty.call(r, key)) copy[key] = r[key];
      out.push(copy);
    }
    return out;
  }

  /** The runs covering [from, to) in character offsets, splitting the runs at the edges. */
  function sliceRuns(runs, from, to) {
    var out = [], pos = 0;
    for (var i = 0; i < runs.length; i++) {
      var r = runs[i], s = pos, text = String(r.text);
      pos += text.length;
      var a = Math.max(0, from - s), b = Math.min(text.length, to - s);
      if (b > a) {
        var copy = {};
        for (var key in r) if (Object.prototype.hasOwnProperty.call(r, key)) copy[key] = r[key];
        copy.text = text.slice(a, b);
        out.push(copy);
      }
    }
    return out;
  }

  /** Apply `patch` to [start, end).
   *
   *  A patch value of `null` DELETES the key, which is what "Reset" and "Template size" mean:
   *  go back to inheriting, rather than pinning an explicit off/size that would then override
   *  the template forever. */
  function patchRuns(runs, start, end, patch) {
    var mid = sliceRuns(runs, start, end);
    for (var i = 0; i < mid.length; i++) {
      for (var key in patch) {
        if (!Object.prototype.hasOwnProperty.call(patch, key)) continue;
        if (patch[key] === null) delete mid[i][key];
        else mid[i][key] = patch[key];
      }
    }
    return coalesce(sliceRuns(runs, 0, start).concat(mid, sliceRuns(runs, end, Infinity)));
  }

  /** Replace [start, end) with `insert`. */
  function spliceRuns(runs, start, end, insert) {
    return coalesce(sliceRuns(runs, 0, start).concat(insert, sliceRuns(runs, end, Infinity)));
  }

  /** What the selection looks like, per switch: a value when every covered run agrees,
   *  `undefined` when they disagree.
   *
   *  The distinction drives the toggle: "some of this is bold" must turn bold ON for the whole
   *  selection, not off, or dragging across a partly-bold line would un-bold the bold part. */
  function summarize(runs, start, end) {
    var seen = {}, out = {};
    for (var k = 0; k < RUN_KEYS.length; k++) seen[RUN_KEYS[k]] = [];
    var pos = 0;
    for (var i = 0; i < runs.length; i++) {
      var s = pos;
      pos += String(runs[i].text).length;
      if (Math.min(pos, end) - Math.max(s, start) <= 0) continue;
      for (var j = 0; j < RUN_KEYS.length; j++) {
        var key = RUN_KEYS[j];
        var v = runs[i][key] === undefined ? null : runs[i][key];
        if (seen[key].indexOf(v) < 0) seen[key].push(v);
      }
    }
    for (var m = 0; m < RUN_KEYS.length; m++) {
      var kk = RUN_KEYS[m];
      out[kk] = seen[kk].length === 1 ? seen[kk][0] : undefined;
    }
    return out;
  }

  /** Bold a selection that is not uniformly bold; un-bold one that is. `undefined` (mixed)
   *  and `null` (inherited) both mean "not uniformly on", so both turn it on. */
  function nextToggle(current) {
    return current === true ? false : true;
  }

  /** A CSS font-size to points, or null.
   *
   *  Word pastes sizes in pt, browsers in px. Anything else (em, %, keywords) is unanswerable
   *  without a computed context, so it inherits rather than guessing. */
  function parseSizePt(v) {
    var m = String(v == null ? "" : v).trim().match(/^([\d.]+)\s*(pt|px)$/);
    if (!m) return null;
    var n = parseFloat(m[1]);
    if (!isFinite(n) || n <= 0) return null;
    var pt = m[2] === "px" ? n * 0.75 : n;
    return Math.max(4, Math.min(72, Math.round(pt * 2) / 2));
  }

  /** The run format implied by one pasted element, over what it inherits.
   *
   *  Tags first, then inline styles, because Word writes both and the style is the more
   *  specific statement. The `font-weight` test has to accept the WORD "bold" as well as a
   *  number: Word emits `font-weight:bold`, and `Number("bold")` is NaN, so a numeric-only
   *  comparison reads Word's own bold as NOT bold. */
  function fmtFromPasted(tag, style, inherited) {
    var f = {};
    for (var key in inherited) {
      if (Object.prototype.hasOwnProperty.call(inherited, key)) f[key] = inherited[key];
    }
    tag = String(tag || "").toUpperCase();
    style = style || {};
    if (tag === "B" || tag === "STRONG") f.bold = true;
    if (tag === "I" || tag === "EM") f.italic = true;
    if (tag === "U") f.underline = true;
    var w = String(style.fontWeight || "");
    if (w) f.bold = (w === "bold" || w === "bolder" || Number(w) >= 600);
    if (style.fontStyle) f.italic = (style.fontStyle === "italic" || style.fontStyle === "oblique");
    var dec = String(style.textDecorationLine || style.textDecoration || "");
    if (dec) f.underline = dec.indexOf("underline") >= 0;
    var size = parseSizePt(style.fontSize);
    if (size) f.size_pt = size;
    return f;
  }

  /** Python's `round()` of a float: the nearest integer, a tie going to the EVEN one.
   *
   *  Decided on the exact double, which is what Python does too, so 10.5 goes to 10 and
   *  10.499999999999998 (what 15 * 0.7 is) goes to 10 as well. `Math.round` sends a tie up and
   *  would print some runs half a point larger on screen than in the document. `x - floor(x)` is
   *  exact for every size this is asked about. */
  function roundHalfEven(x) {
    var f = Math.floor(x), d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return (f % 2 === 0) ? f : f + 1;
  }

  /** The half-point size a run of `hp` half-points PRINTS at in a text box the writer shrank by
   *  `scale` — `proposal_writer._scale_txbx_runs`: `max(8, int(round(hp * scale)))`, the 8 being
   *  its 4pt floor. A box the writer did not shrink (it only scales below 0.999, and then reports
   *  1.0) is left exactly as designed, even a run smaller than 4pt. */
  function fitHp(hp, scale) {
    hp = Number(hp);
    scale = Number(scale);
    if (!(hp > 0)) return hp;
    if (!(scale < 0.999)) return hp;
    return Math.max(8, roundHalfEven(hp * scale));
  }

  return {
    RUN_KEYS: RUN_KEYS,
    runsLength: runsLength, coalesce: coalesce, sliceRuns: sliceRuns,
    patchRuns: patchRuns, spliceRuns: spliceRuns, summarize: summarize,
    nextToggle: nextToggle, parseSizePt: parseSizePt, fmtFromPasted: fmtFromPasted,
    roundHalfEven: roundHalfEven, fitHp: fitHp,
  };
});
