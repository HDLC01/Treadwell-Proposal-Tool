"use strict";
/* Execute BOTH of the page's price-block writers over one set of figures and report what each
 * one would put on the base-bid line.
 *
 * THE BUG IT COVERS (Kyle, 2026-09-08). Two reports, one cause:
 *
 *   1. "a proposal printing $6,182 where my estimate said $6,307" — the Direct POLISH template's
 *      base line is a FREE paragraph, so the screen prints {{base_bid_formatted}} straight out of
 *      computeTokenValues, which subtracted the sales tax unconditionally. In that template's
 *      default layout the Material Sales Tax row is inside {{#tax_breakout}} and never prints, so
 *      there was nothing on the page for the base to be net OF: a $125 discount, on screen, on
 *      the only price the document shows.
 *   2. the GC price block printing 6,307 + 125 + 0 under a 6,307 Total — the mirror image. Those
 *      files author their tax rows as plain paragraphs that always print, and the backend was
 *      collapsing the base line to the whole tax-inclusive total anyway.
 *
 * refreshPriceDisplay said `broken ? total - tax : total` and computeTokenValues said
 * `total - tax`, for the same displayed line. THAT disagreement was the defect, so both now go
 * through baseBidFigure and this harness runs BOTH to prove they still agree.
 *
 * WHY EXECUTED, NOT GREPPED. "these two callers agree" is a comparison between two runs of real
 * code. A source assertion that both mention `baseBidFigure` cannot catch a caller that passes
 * its arguments in the wrong order, and `printedTaxRows` reads a module-level `templateBlocks`
 * that a text search cannot evaluate at all.
 *
 * THE SHAPES COME FROM THE REAL .docx FILES. The caller walks each template with
 * proposal_writer.iter_editable_blocks and hands the resulting blocks in on stdin, exactly as
 * /api/proposal-template serves them to the browser. Nothing here hardcodes which templates gate
 * their tax rows, so a template Kyle re-authors with or without a {{#tax_breakout}} wrapper moves
 * this test rather than sneaking past it.
 *
 * Usage: node price-block-harness.js <frontend-dir> < cases.json   →  one line of JSON
 *   cases.json: [{ name, work_type, audience, tax_inclusion, blocks, total, sales_tax, remodel_tax }]
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];
const SRC = fs.readFileSync(path.join(ROOT, "js", "proposal-review.js"), "utf8");
const NL = String.fromCharCode(10);

/** Lift a real unit by name, refusing to invent a stub if the file moved on. */
function grab(re, what) {
  const m = re.exec(SRC);
  if (!m) throw new Error("could not lift " + what + " — rewrite this harness, don't stub it");
  return m[0];
}
/** Lift `function name(...) {...}` by brace counting (bodies contain braces + regexes). */
function fn(name) {
  const m = new RegExp("\\n  function " + name + "\\s*\\(").exec(SRC);
  if (!m) throw new Error(name + "() is gone — rewrite this harness, don't stub it");
  const i = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) return SRC.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}

// The real units, in dependency order. `baseBidFigure` is the subject; `refreshPriceDisplay` and
// `computeTokenValues` are the two callers under comparison. Everything they reach for on the
// pricing path is lifted rather than stubbed, so the harness cannot disagree with the app about
// how a dollar is formatted, which work type is in effect, or what an overridden line shows.
//
// INJECTED, not lifted (see scopeFor): `templateBlocks` — the whole point is to drive it per case;
// `focusInside` and `lineAtSelection` — they read a live Selection; `renderProposalExtras` — it
// renders the options/alternate previews out of the DOM and has nothing to do with the base line.
const UNITS = [
  grab(/^  const fmtUSD = [\s\S]*?;$/m, "fmtUSD"),
  grab(/^  const fmtUSDdoc = .*$/m, "fmtUSDdoc"),
  grab(/^  const fmtSF = .*$/m, "fmtSF"),
  grab(/^  const _OVERRIDE_TITLE = .*$/m, "_OVERRIDE_TITLE"),
  fn("effectiveWorkType"),
  fn("taxTreatmentMode"),
  fn("printedTaxRows"),
  fn("baseBidFigure"),
  fn("lineOverride"),
  fn("lineValue"),
  fn("lineEl"),
  fn("paintLine"),
  fn("comboSystemLines"),
  fn("comboLinesForPayload"),
  fn("baseDescLabel"),
  fn("refreshPriceDisplay"),
  fn("computeTokenValues"),
].join(NL);

/** A <p> double carrying only what paintLine touches: text, the computed baseline, the ⚠ class,
 *  the tooltip, and a display style refreshPriceDisplay show/hides. */
function el(id) {
  return {
    id,
    textContent: "",
    dataset: {},
    style: { display: "" },
    title: "",
    _classes: new Set(),
    classList: {
      toggle(c, on) { if (on) this._o._classes.add(c); else this._o._classes.delete(c); },
      contains(c) { return this._o._classes.has(c); },
    },
    removeAttribute() { this.title = ""; },
    appendChild() {},
    get innerHTML() { return this._html || ""; },
    set innerHTML(v) { this._html = v; },
  };
}

/** Build a page scope for one case and return handles into the real functions. */
function scopeFor(c) {
  const rows = {};
  for (const id of ["base-bid-heading", "combo-price-block", "base-bid-row", "sales-tax-row",
                    "remodel-tax-row", "total-row", "options-heading", "rooms-block",
                    "options-panel", "price-lines-block", "alternate-block"]) {
    rows[id] = el(id);
    rows[id].classList._o = rows[id];
  }
  const document = {
    // #tb-total is where BOTH writers read the lump sum from; the page renders it before calling.
    querySelector: (sel) => (sel === "#tb-total" ? { textContent: c.total_text } : null),
    getElementById: (id) => rows[id] || null,
  };
  const form = {
    querySelector: (sel) => {
      const m = /\[name='([^']+)'\]/.exec(sel);
      const vals = { tax_inclusion: c.tax_inclusion };
      return m && vals[m[1]] !== undefined ? { value: vals[m[1]] } : null;
    },
  };
  const state = {
    work_type: c.work_type, audience: c.audience,
    project_name: "Viracor", priced_tabs: [], rooms: [],
    proposal_lump_sum: c.total, proposal_sales_tax: c.sales_tax,
    proposal_remodel_tax: c.remodel_tax,
    sheet_area: { epoxy_sf: 3000, polish_sf: 3000, cove_lf: 0 },
    price_overrides: { lines: {} },
    cell_values: {},
  };
  const body = UNITS + NL +
    "return { refreshPriceDisplay, computeTokenValues, printedTaxRows, baseBidFigure };";
  const api = new Function("state", "document", "form", "TW", "window", "templateBlocks",
                           "focusInside", "lineAtSelection", "renderProposalExtras", body)(
    state, document, form, { readForm: () => ({}) }, { TWAuth: null },
    c.blocks, () => false, () => null, () => {});
  return { api, rows, state };
}

const CASES = JSON.parse(fs.readFileSync(0, "utf8"));
const out = CASES.map((c) => {
  c.total_text = "$" + Number(c.total).toFixed(2);
  const { api, rows, state } = scopeFor(c);

  // THE SCREEN. refreshPriceDisplay paints the mounted rows (the layout the Direct templates get,
  // where the base line is inside {{#single_bid}} / next to a {{#tax_breakout}} region).
  api.refreshPriceDisplay();

  // THE DOCUMENT. computeTokenValues fills the token the templates whose base line is a FREE
  // paragraph print directly, and is also the payload /api/generate is handed.
  const tv = api.computeTokenValues(Object.assign({}, state));

  return {
    name: c.name,
    printedTaxRows: api.printedTaxRows(),
    // What the estimator reads off the painted rows.
    painted: {
      base: rows["base-bid-row"].textContent,
      sales_tax: rows["sales-tax-row"].textContent,
      remodel: rows["remodel-tax-row"].textContent,
      total: rows["total-row"].textContent,
      salesRowShown: rows["sales-tax-row"].style.display !== "none",
      remodelRowShown: rows["remodel-tax-row"].style.display !== "none",
      totalRowShown: rows["total-row"].style.display !== "none",
    },
    // What the document is filled from.
    tokens: {
      base_bid_formatted: tv.base_bid_formatted,
      material_tax_formatted: tv.material_tax_formatted,
      tax_amount_formatted: tv.tax_amount_formatted,
      total_formatted: tv.total_formatted,
      base_tax_phrase: tv.base_tax_phrase,
    },
  };
});
console.log(JSON.stringify(out));
