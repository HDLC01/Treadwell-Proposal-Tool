"use strict";
/* Execute the page's price-block writers over one set of figures and report what the SCREEN shows.
 *
 * THE RULE BEING PROVED (Hanz, 2026-09-25): the estimate sheet decides WHETHER there is tax —
 * Taxable? for material sales tax, Remodel Tax? for remodel tax, per priced tab — and the proposal's
 * TAX control decides only the layout, "One line" or "Broken out". Broken out: the base line is the
 * pre-tax figure with no bracket, a Material Sales Tax row only if taxable, a Remodel Tax row only if
 * remodel, then the Total, and the rows add up ("$6,767 – Epoxy flooring as described above / $72 –
 * Material Sales Tax / $6,839 – Total"). One line: the whole bid, with the wording for the taxes the
 * sheet says are in it. Every option the same way, off its own tab.
 *
 * THE PAGE HAS SEVERAL WRITERS FOR ONE PRICE BLOCK — refreshPriceDisplay paints the mounted rows,
 * computeTokenValues fills the {{tokens}} the free-paragraph templates print and the payload carries,
 * renderProposalExtras draws the option lines, setBlockContent / priceRowVisibility show or hide a
 * GC / Gyp tax row — and they all go through one rule (baseBidFigure → TWPrice.taxRule). This runs
 * ALL of them, and test_price_block_reconciles.py compares what they show with what /api/generate
 * prints for the same inputs, on every template shape. Two independent implementations of the rule
 * (price-lines-core.js here, price_rules.py there) have to land on the same rows and the same dollar.
 *
 * WHY EXECUTED, NOT GREPPED. "the screen and the document agree" is a comparison between two runs of
 * real code. A source assertion that both call the rule cannot catch arguments in the wrong order, a
 * phrase built from a stale flag, or a row shown that the render takes out.
 *
 * THE SHAPES COME FROM THE REAL .docx FILES: the caller walks each template with
 * proposal_writer.iter_editable_blocks and hands the blocks in on stdin, exactly as
 * /api/proposal-template serves them to the browser.
 *
 * Usage: node price-block-harness.js <frontend-dir> < cases.json   →  one line of JSON
 *   cases.json: [{ name, work_type, audience, blocks, total, sales_tax, remodel_tax,
 *                  taxable?, remodel_on?, tax_layout?, tax_inclusion?, rooms?, state? }]
 */
const fs = require("fs");
const path = require("path");

const ROOT = process.argv[2];
const SRC = fs.readFileSync(path.join(ROOT, "js", "proposal-review.js"), "utf8").replace(/\r\n/g, "\n");
// The price rule's page half, a script the page loads before proposal-review.js; the lifted code
// reads it as the bare global `TWPrice`, exactly as the page does.
globalThis.TWPrice = require(path.join(ROOT, "js", "price-lines-core.js"));
const NL = "\n";

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

// The real units, in dependency order. Everything on the pricing path is lifted rather than
// stubbed, so the harness cannot disagree with the app about how a dollar is formatted, which work
// type is in effect, or what an edited line shows.
//
// INJECTED, not lifted (see scopeFor): `templateBlocks` — driven per case; `focusInside` and
// `lineAtSelection` — they read a live Selection.
const UNITS = [
  grab(/^  const fmtUSD = [\s\S]*?;$/m, "fmtUSD"),
  grab(/^  const fmtUSDdoc = .*$/m, "fmtUSDdoc"),
  grab(/^  const fmtSF = .*$/m, "fmtSF"),
  grab(/^  const _OVERRIDE_TITLE = .*$/m, "_OVERRIDE_TITLE"),
  grab(/^  const COMPUTED_PRICE_LINE_KEYS = .*$/m, "COMPUTED_PRICE_LINE_KEYS"),
  grab(/^  const _LIVE_TITLE = .*$/m, "_LIVE_TITLE"),
  grab(/^  const _MONEY_TITLE = .*$/m, "_MONEY_TITLE"),
  grab(/^  const _escLine = [\s\S]*?\}\[c\]\)\);$/m, "_escLine"),
  grab(/^  const GYP_BASE = .*$/m, "GYP_BASE"),
  fn("effectiveWorkType"),
  fn("basePriceSystem"),
  fn("taxLayout"),
  fn("taxTreatmentMode"),
  fn("baseTaxRule"),
  fn("printedTaxRows"),
  fn("baseBidFigure"),
  fn("lineOverride"),
  fn("lineValue"),
  fn("lineCue"),
  // The price box's bullets: the builders put a line's override on it (linePropsOf) and
  // refreshPriceDisplay ends by drawing them (paintLineParas, a no-op on these element doubles).
  fn("linePropsOf"),
  fn("paintLineParas"),
  fn("extraLinesHtml"),
  fn("lineEl"),
  fn("paintExtras"),
  fn("makeExtraLine"),
  fn("paintLine"),
  fn("comboSystemLines"),
  fn("comboLinesForPayload"),
  fn("baseDescLabel"),
  fn("refreshPriceDisplay"),
  // The option-line writer ends by drawing the blank lines above the Options heading. Lifted, not
  // stubbed: this page double has no #options-gap, so it returns before touching anything, as the
  // real one does on a page without the gap (options-gap-harness.js drives it with one).
  fn("paintOptionsGap"),
  fn("renderProposalExtras"),
  fn("computeTokenValues"),
  fn("priceRowVisibility"),
].join(NL);

/** A <p> double carrying only what paintLine touches: text, the computed baseline, the cue
 *  classes, the tooltip, and a display style refreshPriceDisplay show/hides. */
function el(id) {
  const o = {
    id,
    textContent: "",
    dataset: {},
    style: { display: "" },
    title: "",
    _classes: new Set(),
    removeAttribute() { this.title = ""; },
    appendChild() {},
    get innerHTML() { return this._html || ""; },
    set innerHTML(v) { this._html = v; },
  };
  o.classList = {
    toggle(c, on) { if (on) o._classes.add(c); else o._classes.delete(c); },
    contains(c) { return o._classes.has(c); },
  };
  return o;
}

const unesc = (s) => String(s).replace(/&(#39|amp|lt|gt|quot);/g,
  (_, k) => ({ "#39": "'", amp: "&", lt: "<", gt: ">", quot: '"' }[k]));
/** The lines lineEl drew into a container, in order: {key, kind, text, classes}. */
function linesOf(html) {
  const out = [];
  const re = /<p class="([^"]*)"[^>]*?data-po-kind="(line|extra)" data-po-linekey="([^"]*)"[^>]*>([\s\S]*?)<\/p>/g;
  let m;
  while ((m = re.exec(String(html || "")))) out.push({ classes: m[1], kind: m[2], key: unesc(m[3]), text: unesc(m[4]) });
  return out;
}

/** Build a page scope for one case and return handles into the real functions. */
function scopeFor(c) {
  const rows = {};
  for (const id of ["base-bid-heading", "combo-price-block", "base-bid-row", "sales-tax-row",
                    "remodel-tax-row", "total-row", "options-heading", "rooms-block",
                    "price-lines-block", "alternate-block"]) {
    rows[id] = el(id);
  }
  const document = {
    // #tb-total is where the writers read the lump sum from; the page renders it before calling.
    querySelector: (sel) => (sel === "#tb-total" ? { textContent: c.total_text } : null),
    getElementById: (id) => rows[id] || null,
  };
  const form = { querySelector: () => null };
  const state = {
    work_type: c.work_type, audience: c.audience,
    project_name: "Viracor", priced_tabs: [], rooms: c.rooms || [],
    proposal_lump_sum: c.total, proposal_sales_tax: c.sales_tax,
    proposal_remodel_tax: c.remodel_tax,
    sheet_area: { epoxy_sf: 3000, polish_sf: 3000, cove_lf: 0 },
    price_overrides: c.price_overrides || { lines: {} },
    cell_values: {},
  };
  if (c.taxable !== undefined) state.proposal_taxable = c.taxable;
  if (c.remodel_on !== undefined) state.proposal_remodel_on = c.remodel_on;
  if (c.tax_layout !== undefined) state.tax_layout = c.tax_layout;
  if (c.tax_inclusion !== undefined) state.tax_inclusion = c.tax_inclusion;
  // Narrative fields a case wants set (or explicitly blank) — the price cases never pass any.
  Object.assign(state, c.state || {});
  const body = UNITS + NL +
    "return { refreshPriceDisplay, computeTokenValues, printedTaxRows, baseBidFigure, taxLayout, priceRowVisibility, comboLinesForPayload };";
  const api = new Function("state", "document", "form", "TW", "window", "templateBlocks",
                           "focusInside", "lineAtSelection", body)(
    state, document, form, { readForm: () => ({}), setState: () => {} }, { TWAuth: null },
    c.blocks, () => false, () => null);
  return { api, rows, state };
}

const CASES = JSON.parse(fs.readFileSync(0, "utf8"));
const out = CASES.map((c) => {
  c.total_text = "$" + Number(c.total).toFixed(2);
  const { api, rows, state } = scopeFor(c);

  // THE SCREEN. refreshPriceDisplay paints the mounted rows and renders the option lines.
  api.refreshPriceDisplay();

  // THE DOCUMENT'S INPUTS. computeTokenValues fills the tokens the free-paragraph templates print,
  // and is also the payload /api/generate is handed.
  const tv = api.computeTokenValues(Object.assign({}, state));

  // The GC / Gyp tax rows are FREE paragraphs: which of them the editor shows, block by block.
  const freeRows = {};
  for (const b of (c.blocks || [])) {
    if (b.in_block != null) continue;
    const fake = el("b" + b.id);
    const hide = api.priceRowVisibility(fake, b, tv);
    if (hide !== null) freeRows[b.id] = !hide;
  }

  return {
    name: c.name,
    layout: api.taxLayout(),
    printedTaxRows: api.printedTaxRows(),
    painted: {
      base: rows["base-bid-row"].textContent,
      sales_tax: rows["sales-tax-row"].textContent,
      remodel: rows["remodel-tax-row"].textContent,
      total: rows["total-row"].textContent,
      salesRowShown: rows["sales-tax-row"].style.display !== "none",
      remodelRowShown: rows["remodel-tax-row"].style.display !== "none",
      totalRowShown: rows["total-row"].style.display !== "none",
      optionsHeadingShown: rows["options-heading"].style.display !== "none",
      baseClasses: Array.from(rows["base-bid-row"]._classes),
    },
    options: linesOf(rows["price-lines-block"].innerHTML),
    freeRows,
    tokens: {
      base_bid_formatted: tv.base_bid_formatted,
      material_tax_formatted: tv.material_tax_formatted,
      tax_amount_formatted: tv.tax_amount_formatted,
      total_formatted: tv.total_formatted,
      base_tax_phrase: tv.base_tax_phrase,
      tax_layout: tv.tax_layout,
      tax_inclusion: tv.tax_inclusion,
      price_taxable: tv.price_taxable,
      price_remodel_on: tv.price_remodel_on,
      price_rows_material: tv.price_rows_material,
      price_rows_remodel: tv.price_rows_remodel,
      price_rows_total: tv.price_rows_total,
    },
    price_overrides: state.price_overrides,
    // The narrative tokens a blank field used to turn into a printed "0".
    narrative: {
      texture: tv.texture, system_name: tv.system_name, system_name_epoxy: tv.system_name_epoxy,
      system_name_polish: tv.system_name_polish, city_state: tv.city_state, address: tv.address,
      work_description: tv.work_description, scope_notes: tv.scope_notes,
      schedule_notes: tv.schedule_notes, exclusions: tv.exclusions, bid_date: tv.bid_date,
      site_visit_date: tv.site_visit_date, work_type: tv.work_type,
      site_visit_phrase: tv.site_visit_phrase, no_site_visit: tv.no_site_visit,
      bid_date_formatted: tv.bid_date_formatted,
    },
  };
});
console.log(JSON.stringify(out));
