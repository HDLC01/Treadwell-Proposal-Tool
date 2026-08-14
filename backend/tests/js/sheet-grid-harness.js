"use strict";
/* Execute the REAL track-sizing functions out of estimate-review.js against measured values from
 * Kyle's actual workbook, and report the pixel tracks they produce.
 *
 * THE BUG THEY FIX (Hanz, 2026-08-14, screenshot): grid text sliced through the middle
 * ("MATERIAL - Patch", "Quantity") and cut mid-word ("MATERIAL - Epoxy Liq"). Root cause was a
 * unit mismatch — text paints at 12pt → ~14.7px while the tracks were sized for ~11px text, and
 * the cell's padding+border were taken OUT of the Excel-sized track instead of added to it.
 *
 * Executed rather than grepped: the claim is "the track a given xlsx height produces is tall
 * enough for the line box the CSS actually declares", which is arithmetic over two files. A
 * source assertion on the constants would pass while the two call sites of the char-width
 * disagreed — the exact drift this module-scoping exists to prevent, so the harness also lifts
 * BOTH column expressions and compares their behaviour.
 *
 * Usage: node sheet-grid-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];
const src = fs.readFileSync(path.join(ROOT, "js", "estimate-review.js"), "utf8");
const html = fs.readFileSync(path.join(ROOT, "estimate-review.html"), "utf8");

function grab(re, what) {
  const m = re.exec(src);
  if (!m) throw new Error(what + " is gone from estimate-review.js — rewrite this harness");
  return m[0];
}
function fn(name) {
  const m = new RegExp("\\nfunction " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone — rewrite this harness, don't stub it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

const api = new Function(
  grab(/^const PX_PER_CHAR = .*$/m, "PX_PER_CHAR") + "\n" +
  fn("colTrackPx") + "\n" + fn("rowTrackPx") + "\n" +
  "return { PX_PER_CHAR, colTrackPx, rowTrackPx };")();

// ── the CSS the tracks must satisfy ──────────────────────────────────────────
// Parse the grid cell's declared geometry out of the page, because the "does it fit" arithmetic
// is only honest against what the CSS actually says today.
const cellBlock = (/\.xl-grid \.gridcell \{[\s\S]*?\}/.exec(html) || [""])[0];
const padM = /padding:\s*(\d+(?:\.\d+)?)px\s+\d+/.exec(cellBlock);
const lhM = /line-height:\s*([\d.]+)/.exec(cellBlock);
const inputBlock = (/\.xl-grid \.gridcell input,[\s\S]*?\{[\s\S]*?\}/.exec(html) || [""])[0];
const css = {
  padV: padM ? Number(padM[1]) : null,          // vertical padding per side
  lineHeight: lhM ? Number(lhM[1]) : null,       // unitless
  borderBottomPx: /border-bottom:\s*1px/.test(cellBlock) ? 1 : 0,
  inputHasLineHeight: /line-height:\s*[\d.]+/.test(inputBlock),
};

// ── measured from Kyle's estimate_sheet_5.7.xlsx (Epoxy tab) ─────────────────
// Dominant cell font 12pt ×467; renderer paints fontSize*0.92 in pt → px at 96/72.
const FONT_PT = 12;
const paintedPx = FONT_PT * 0.92 * (96 / 72);                  // ≈ 14.72px
const lineBoxPx = paintedPx * (css.lineHeight || 1.2);         // what a row must contain
const chromePx = (css.padV == null ? 99 : css.padV * 2) + css.borderBottomPx;

// Row-height histogram from the real file: None ×432, 16.2 ×194, 16.05 ×8, 21.6 ×9, 21.0 ×3,
// 18.0 ×1, 26.4 ×1; sheet_format.defaultRowHeight = 15.6.
const DEFAULT_H = 15.6;
// 10.0 is not in Kyle's file — it models a row a user drag-shrinks or another workbook ships;
// it is the case that exercises the FLOOR rather than the pt→px arithmetic.
const ROW_HEIGHTS = [null, 10.0, 16.05, 16.2, 18.0, 21.0, 21.6, 26.4];

// NOTE ON AN EQUIVALENT MUTANT: dropping rowTrackPx's +5 chrome allowance is NOT detectable by
// these cases — the 24px floor absorbs it for every font/height shape in Kyle's workbook. The +5
// stays because it is the correct MODEL (Excel heights are line boxes, ours are border-boxes) and
// it is what keeps larger fonts safe if the floor or the CSS ever loosens; the floor and the CSS
// assertions are the load-bearing guards.
// "Fits" demands 1.5px of headroom, not a bare >=. The pre-fix geometry FAILED by 2px and a
// naive fix could pass by 0.07px — which inverts the moment the browser zooms to 90% and rounds
// the track down a pixel. Real margin or it does not count.
const HEADROOM = 1.5;

const out = { css, paintedPx, lineBoxPx, chromePx };

out.rows = ROW_HEIGHTS.map((h) => {
  const track = api.rowTrackPx(h, DEFAULT_H);
  return { xlsxPt: h, trackPx: track, contentPx: track - chromePx,
           fits: track - chromePx >= lineBoxPx + HEADROOM };
});

// An old cached payload without default_row_height: the function's own fallback must hold —
// and must agree with the workbook's real default, or a frontend-first deploy renders every
// height-less row at a different size than the same page will a minute later.
out.legacyPayloadNoDefault = (() => {
  const track = api.rowTrackPx(undefined, undefined);
  return { trackPx: track, fits: track - chromePx >= lineBoxPx + HEADROOM,
           equalsWorkbookDefault: track === api.rowTrackPx(undefined, DEFAULT_H) };
})();

// ── columns: the exact clipped strings from the screenshot ───────────────────
// Col A is 19.797 chars in the xlsx. The strings must fit at the painted font; Calibri averages
// ≈ 0.5em per char for mixed-case text → paintedPx/2 per character, + the 17px of horizontal
// chrome (cell 4+4, input 4+4, border 1) that comes out of the track.
const H_CHROME = 17;
const perCharPx = paintedPx / 2;
out.columns = [
  { col: "A", w: 19.797, text: "MATERIAL - Epoxy Liquids" },
  { col: "A", w: 19.797, text: "System 2 Options / Walls (scroll down)" },
  { col: "B", w: 13.797, text: "Quantity" },
  { col: "I", w: 13.0, text: "Cost / Unit" },
].map((c) => {
  const track = api.colTrackPx(c.w);
  const needs = Math.ceil(c.text.length * perCharPx) + H_CHROME;
  return { ...c, trackPx: track, needsPx: needs, fits: track >= needs };
});

// ── the two char-width call sites cannot disagree ────────────────────────────
// Lift the auto-fit expression and EXECUTE it: for a text of length L, auto-fit must produce at
// least what the initial layout gives a column sized exactly for L characters.
out.autofit = (() => {
  const m = /colPx\[idx - 1\] = (Math\.max\([^;]+\));/.exec(src);
  if (!m) throw new Error("the dblclick auto-fit expression moved — rewrite this harness");
  const autoFit = new Function("maxLen", "PX_PER_CHAR",
                               "return " + m[1].replace(/maxLen/g, "maxLen") + ";");
  const L = 24;                                   // "MATERIAL - Epoxy Liquids"
  return {
    expr: m[1],
    usesSharedConstant: /PX_PER_CHAR/.test(m[1]),
    autoFitPx: autoFit(L, api.PX_PER_CHAR),
    initialPxForSameChars: api.colTrackPx(L),
    agree: autoFit(L, api.PX_PER_CHAR) >= api.colTrackPx(L) - 12,
  };
})();

// ── the drag floor cannot undercut the render floor ─────────────────────────
out.dragFloor = (() => {
  const m = /rowPx\[index - 1\] = Math\.max\((\d+), startSize \+ delta\);/.exec(src);
  if (!m) throw new Error("the row drag-resize commit moved — rewrite this harness");
  return { dragFloorPx: Number(m[1]), renderFloorPx: api.rowTrackPx(0.0001, 0.0001),
           dragCannotRecreateTheBug: Number(m[1]) >= api.rowTrackPx(0.0001, 0.0001) };
})();

console.log(JSON.stringify(out));
