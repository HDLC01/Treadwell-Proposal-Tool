"use strict";
/* Execute the page's price-block writers over one set of figures and report what the SCREEN shows.
 *
 * THE RULE BEING PROVED (Hanz, 2026-09-25): the estimate sheet decides WHETHER there is tax —
 * Taxable? for material sales tax, Remodel Tax? for remodel tax, per priced tab — and the proposal's
 * TAX control decides the layout, "One line", "Broken out" or (2026-09-28) "Tax exempt". Broken out:
 * the base line is the pre-tax figure with no bracket, a Material Sales Tax row only if taxable, a
 * Remodel Tax row only if remodel, then the Total, and the rows add up ("$6,767 – Epoxy flooring as
 * described above / $72 – Material Sales Tax / $6,839 – Total"). One line: the whole bid, with the
 * wording for the taxes the sheet says are in it. Tax exempt: the pre-tax figure, "(tax exempt)",
 * no row at all. Every option off its own tab, and always on ONE line (Hanz, 2026-09-28) — pre-tax
 * with "(tax exempt)" when the job is exempt, an Add/Deduct off the two pre-tax figures.
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
 * THE TAX CONTROL ITSELF. A case with `pick` also runs the ribbon's wiring — the real wireRibbonTax
 * IIFE, verbatim — against a <select> double holding the options the real proposal-review.html
 * offers (`select_options`; a value it does not offer reads back "", as a browser's does): it paints,
 * picks, repaints, and paints again from what the pick saved, as a reload would.
 *
 * THE PAGE'S OWN PAYLOAD. Each case also reports `payload`, the price half of what Continue hands
 * /api/generate (composeProposalPayload's composition over computeTokenValues' tokens), so a test
 * can render the document from what the page SENDS, not only from figures of its own: the screen
 * could agree with a hand-built payload while the one the page composes prints another price.
 *
 * Usage: node price-block-harness.js <frontend-dir> < cases.json   →  one line of JSON
 *   cases.json: [{ name, work_type, audience, blocks, total, sales_tax, remodel_tax,
 *                  taxable?, remodel_on?, tax_layout?, tax_inclusion?, rooms?, state?,
 *                  pick?, select_options? }]
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

/** The ribbon's wiring: `(function wireRibbonTax() { ... })();` exactly as the page runs it on load. */
function iife(name) {
  const m = new RegExp("\\n  \\(function " + name + "\\s*\\(\\s*\\)\\s*\\{").exec(SRC);
  if (!m) throw new Error(name + " is gone — rewrite this harness, don't stub it");
  const i = SRC.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < SRC.length; j++) {
    if (SRC[j] === "{") depth++;
    else if (SRC[j] === "}" && --depth === 0) {
      const tail = /^\)\(\);/.exec(SRC.slice(j + 1));
      if (!tail) throw new Error(name + " is no longer an IIFE — rewrite this harness, don't stub it");
      return SRC.slice(m.index + 1, j + 1 + tail[0].length);
    }
  }
  throw new Error("unbalanced braces reading " + name);
}
const WIRE_TAX = iife("wireRibbonTax");

/** A <select> double: `value` reads back only an option it offers ("" otherwise, as a browser's
 *  does), and `change` listeners run when the case picks. */
function select(id, options) {
  const listeners = {};
  let v = "";
  return {
    id, options: options.slice(),
    get value() { return v; },
    set value(x) { v = options.indexOf(String(x)) >= 0 ? String(x) : ""; },
    addEventListener(type, f) { (listeners[type] = listeners[type] || []).push(f); },
    fire(type) { (listeners[type] || []).forEach((f) => f({ type, target: this })); },
    listening(type) { return (listeners[type] || []).length; },
  };
}

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
  const inputs = [];
  const form = { querySelector: () => null, dispatchEvent: (e) => { inputs.push(e.type); return true; } };
  if (c.pick !== undefined) rows["tax-treatment-select"] = select("tax-treatment-select", c.select_options || []);
  const sets = [];
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
  const body = UNITS + NL + (c.pick !== undefined ? WIRE_TAX + NL : "") +
    "return { refreshPriceDisplay, computeTokenValues, printedTaxRows, baseBidFigure, taxLayout, priceRowVisibility, comboLinesForPayload,\n" +
    "         effectiveWorkType, fmtUSDdoc };";
  const api = new Function("state", "document", "form", "TW", "window", "templateBlocks",
                           "focusInside", "lineAtSelection", body)(
    state, document, form,
    { readForm: () => ({}), setState: (patch) => { sets.push(JSON.parse(JSON.stringify(patch))); } },
    { TWAuth: null }, c.blocks, () => false, () => null);
  return { api, rows, state, sets, inputs };
}

/** Paint, pick, repaint, and paint again from what the pick saved (a reload). */
function pickFlow(c) {
  const first = scopeFor(c);
  const sel = first.rows["tax-treatment-select"];
  const cellsBefore = JSON.stringify(first.state.cell_values);
  const wired = sel.listening("change");
  first.api.refreshPriceDisplay();
  const painted = sel.value;
  sel.value = c.pick;
  sel.fire("change");
  const saved = first.sets.slice();
  // The form's `input` runs the page's own repaint.
  first.api.refreshPriceDisplay();
  const repainted = sel.value;
  const tv = first.api.computeTokenValues(Object.assign({}, first.state));
  // A reload: the draft as the pick left it, drawn by a fresh page.
  const reload = scopeFor(Object.assign({}, c, { tax_layout: Object.assign({}, ...saved).tax_layout }));
  reload.api.refreshPriceDisplay();
  return {
    options: sel.options, wired, painted, picked: sel.value === "" ? "" : c.pick, saved,
    moduleState: first.state.tax_layout, inputs: first.inputs, repainted,
    reloaded: reload.rows["tax-treatment-select"].value,
    base: first.rows["base-bid-row"].textContent,
    rowsShown: ["sales-tax-row", "remodel-tax-row", "total-row"]
      .filter((id) => first.rows[id].style.display !== "none"),
    tokens: { tax_layout: tv.tax_layout, tax_inclusion: tv.tax_inclusion,
              base_bid_formatted: tv.base_bid_formatted, base_tax_phrase: tv.base_tax_phrase },
    cellsUntouched: JSON.stringify(first.state.cell_values) === cellsBefore
      && !saved.some((p) => "cell_values" in p),
  };
}

/** The price half of what composeProposalPayload hands /api/generate, field for field: `values`
 *  is the draft (with the form, empty here) spread UNDER computeTokenValues' tokens, less the keys
 *  it deletes; `combo_options` is comboLinesForPayload's; `remodel` the one conditional row off
 *  the draft's remodel tax; rooms, manual price lines and the line edits as the draft holds them.
 *  The narrative a test adds on top is text, never a figure or a flag. */
function payloadOf(api, state, tv) {
  const values = Object.assign({}, state, tv);
  ["proposal_payload", "proposal_payload_key", "generate_result", "dropbox_result", "priced_tabs"]
    .forEach((k) => { delete values[k]; });
  const remodelTax = Number(state.proposal_remodel_tax || 0);
  return {
    work_type: api.effectiveWorkType(), audience: state.audience || "Direct", values,
    price_lines: Array.isArray(state.price_lines) ? state.price_lines : [],
    combo_options: api.comboLinesForPayload(),
    remodel: remodelTax > 0 ? [{ amount_formatted: api.fmtUSDdoc(remodelTax) }] : [],
    rooms: Array.isArray(state.rooms) ? state.rooms : [],
    price_overrides: (state.price_overrides && typeof state.price_overrides === "object") ? state.price_overrides : {},
  };
}

const CASES = JSON.parse(fs.readFileSync(0, "utf8"));
const out = CASES.map((c) => {
  c.total_text = "$" + Number(c.total).toFixed(2);
  if (c.pick !== undefined) return { name: c.name, pick: pickFlow(c) };
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
    // Combo's Option 1 / Option 2 lines, where the page draws them instead of the base line.
    combo: rows["combo-price-block"].style.display !== "none" ? linesOf(rows["combo-price-block"].innerHTML) : [],
    // WHAT CONTINUE HANDS /api/generate for the price block, so the document can be rendered from
    // the page's OWN output rather than from figures a test writes itself (payloadOf).
    payload: payloadOf(api, state, tv),
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
