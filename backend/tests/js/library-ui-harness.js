"use strict";
/* Execute the REAL render functions out of frontend/js/library.js and report what they produce.
 *
 * WHY EXECUTED. Batch 6 rebuilt both tables — the Items row went from 7 columns to 8 with a
 * different set, and the assembly line dropped Role and gained two. Every interesting way that
 * can be wrong is invisible to a source assertion:
 *
 *   * `refreshNumbers()` writes the computed cells BY POSITION (tds[4], tds[5]). Those indexes
 *     live in a different function from the row that renderPanel builds, so a column added ahead
 *     of them writes the quantity into the waste box. The only honest check is to render a row
 *     and compare where the qty cell actually landed with the index the updater uses.
 *   * `buy_qty` must be in the numeric-coercion list or the model holds the string "5" and the
 *     next multiplication concatenates. Grepping for the field name would match its own
 *     declaration.
 *   * The Vendors tab renders inputs for an admin and plain text for everybody else. A grep for
 *     "ADMIN" proves the variable is mentioned, not that a non-admin gets no editable field.
 *   * The material picker resolves typed text to an id. "Does it search?" is behaviour.
 *
 * The pricing comes from the REAL library-core.js, so nothing here can pass against a stub that
 * disagrees with the engine.
 *
 * Usage: node library-ui-harness.js <frontend-dir>   →  one line of JSON
 */
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.argv[2]);

// Line endings normalised on read, because this harness matches the page's SOURCE TEXT and git
// hands these files out with CRLF on a Windows checkout. The `grab()` patterns below are
// multiline-anchored (`/^  var DIVISIONS = \[[^\]]*\];$/m`), and on CRLF the character before the
// newline is `\r`, not `;` — so every one of them misses and the whole file reports "the harness
// itself failed" while CI, which checks out LF, stays perfectly green. Found the moment a
// `git checkout --` restored this file mid-session.
const read = (p) => fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");

const src = read(path.join(ROOT, "js", "library.js"));
const html = read(path.join(ROOT, "library.html"));
const L = require(path.join(ROOT, "js", "library-core.js"));

/** Lift a named function out of the page's IIFE (two-space indent), braces balanced.
 *
 *  `async` is optional in the pattern because confirmItemPatch awaits TW.confirmDanger. Without
 *  that the lift throws "confirmItemPatch() is gone", which reads as a deleted function rather
 *  than an unmatched keyword and sends the next reader looking in the wrong file. */
function fn(name) {
  const m = new RegExp("\\n  (?:async )?function " + name + "\\s*\\(").exec(src);
  if (!m) throw new Error(name + "() is gone from library.js — rewrite this harness, don't stub it");
  const i = src.indexOf("{", m.index + m[0].length - 1);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}" && --depth === 0) return src.slice(m.index, j + 1);
  }
  throw new Error("unbalanced braces reading " + name);
}
function grab(re, what) {
  const m = re.exec(src);
  if (!m) throw new Error(what + " is gone from library.js — rewrite this harness");
  return m[0];
}

// ── a DOM stub, only as much as these functions touch ────────────────────────
function makeDom() {
  const nodes = {};
  const el = (id) => (nodes[id] = nodes[id] || {
    id, innerHTML: "", textContent: "", hidden: false, value: "",
    // Filled in on demand by tests that need to walk a rendered table.
    rows: null,
    querySelectorAll(sel) {
      if (sel !== "[data-line]") return [];
      if (!this.rows) this.rows = tableFromHtml(this.innerHTML);
      return this.rows;
    },
  });
  return { el, nodes };
}

/** Turn rendered table HTML into the minimum object graph `refreshNumbers` walks.
 *
 *  Built FROM renderPanel's own output rather than hand-written, which is the whole point: the
 *  updater addresses cells by position on a table that function produced, and a hand-made fixture
 *  could agree with the updater while disagreeing with the page. Recorded per cell index so a
 *  transposition — the exact bug that reached staging — shows up as content in the wrong slot. */
function tableFromHtml(html) {
  const rows = html.split("</tr>").filter((r) => /data-line=/.test(r));
  return rows.map((rowHtml) => {
    const cells = rowHtml.split("<td").slice(1).map((c) => ({
      initial: c, written: null,
      set innerHTML(v) { this.written = v; },
      get innerHTML() { return this.written === null ? this.initial : this.written; },
    }));
    const classes = new Set((/class="([^"]*)"/.exec(rowHtml.split(">")[0]) || ["", ""])[1]
      .split(/\s+/).filter(Boolean));
    return {
      cells,
      classList: {
        add: (c) => classes.add(c), remove: (c) => classes.delete(c),
        toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
        has: (c) => classes.has(c),
      },
      querySelectorAll: (sel) => (sel === "td" ? cells : []),
      getAttribute: (k) => (k === "data-line"
        ? (/data-line="(\d+)"/.exec(rowHtml) || [0, "0"])[1] : null),
    };
  });
}

/** The Division cell, cut out of a rendered row.
 *
 *  Ends at the closing tag of the strip's own div, which is the LAST </div> before the next <td>:
 *  a lazy `[\s\S]*?</div>` would stop at the first one and, if the chip markup ever grows a nested
 *  div, silently report half the chips as missing. */
function divisionCellOf(rowHtml) {
  const i = rowHtml.indexOf('<div class="division-chips"');
  if (i === -1) return "";
  const j = rowHtml.indexOf("<td", i);
  return rowHtml.slice(i, j === -1 ? rowHtml.length : j);
}

/** Turn the REAL rendered division cell into inputs a test can toggle.
 *
 *  Parsed from divisionPick's own output rather than hand-written, for the reason tableFromHtml
 *  gives: the handler queries `input[data-f="divisions"]:checked` off the row, so a renamed
 *  attribute or a lost `checked` has to break this. The row object answers only the two things
 *  onItemEdit asks it for.
 *
 *  Toggling is the browser's job, not the handler's — a label wrapping a checkbox flips it before
 *  `change` fires — so `toggle()` flips the input first and then calls the handler, which is the
 *  order a click produces. */
function chipRowFromHtml(itemId, cellHtml) {
  const tags = cellHtml.match(/<input[^>]*data-f="divisions"[^>]*>/g) || [];
  if (!tags.length) {
    throw new Error("no input[data-f=\"divisions\"] in the division cell — the save contract moved "
      + "and onItemEdit's own selector cannot find the chips either");
  }
  const inputs = tags.map((tag) => ({
    tag,
    div: (/data-div="([^"]*)"/.exec(tag) || ["", ""])[1],
    checked: / checked>/.test(tag) || / checked /.test(tag),
    type: (/type="([^"]*)"/.exec(tag) || ["", ""])[1],
    ariaLabel: (/aria-label="([^"]*)"/.exec(tag) || ["", ""])[1],
    getAttribute(k) { return k === "data-f" ? "divisions" : k === "data-div" ? this.div : null; },
  }));
  const row = {
    inputs,
    getAttribute: (k) => (k === "data-item" ? itemId : null),
    querySelectorAll(sel) {
      if (sel !== 'input[data-f="divisions"]:checked') {
        throw new Error("the handler asked for " + sel + ", which this row does not model");
      }
      return inputs.filter((x) => x.checked);
    },
  };
  inputs.forEach((inp) => { inp.closest = (sel) => (sel === "[data-item]" ? row : null); });
  return row;
}

/** A document stub that records what `paintDates` looked for and what it wrote.
 *
 *  Deliberately NOT a DOM emulator. It answers one question — does the repaint address a selector
 *  the rendered row actually carries, and does it write the dates markup? — and the harness feeds
 *  it the class list taken from the real renderItems output, so a renamed cell breaks the test. */
function makeDocument(presentSelectors) {
  const writes = [];
  return {
    writes,
    querySelector(sel) {
      if (presentSelectors.indexOf(sel) === -1) return null;
      return { set innerHTML(v) { writes.push({ sel, html: v }); } };
    },
  };
}

const dom = makeDom();
const scope = new Function("L", "$", "TW", "state", "document", `
  "use strict";
  var ITEMS = state.ITEMS, ASMS = state.ASMS, VENDORS = state.VENDORS;
  var DIVISION_REFS = state.DIVISION_REFS || [], UNIT_REFS = state.UNIT_REFS || [];
  var VENDOR_USE = state.VENDOR_USE, DIVISION_USE = state.DIVISION_USE || {}, UNIT_USE = state.UNIT_USE || {};
  var ADMIN = state.ADMIN;
  var openId = state.openId;
  // Which line's item picker is showing its results. pickerFor() reads it, so a test can render
  // the closed state (null, the default) or the open one by passing state.pickerOpen.
  var pickerOpen = state.pickerOpen === undefined ? null : state.pickerOpen;
  ${grab(/^  var DIVISIONS = \[[^\]]*\];$/m, "DIVISIONS")}
  ${grab(/^  var UNITS = \[[^\]]*\];$/m, "UNITS")}
  var DEFAULT_DIVISIONS = DIVISIONS.slice();
  // The hardcoded literal above is the FALLBACK. On a loaded page load() replaces it with the
  // Administration tab's list, so a test that wants to prove a curated division reaches the chips
  // passes that list in here — built by the real assignment out of load(), not restated.
  if (state.DIVISIONS) DIVISIONS = state.DIVISIONS;
  ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
  ${fn("current")}
  ${fn("itemOf")}
  ${fn("byId")}
  ${fn("adoptSaved")}
  ${fn("paintDates")}
  ${fn("pick")}
  ${fn("itemDivisions")}
  ${fn("namesWithItemExtras")}
  ${fn("divisionNames")}
  ${fn("unitNames")}
  ${fn("qtyText")}
  ${fn("orderAmount")}
  ${fn("optionsHtml")}
  ${fn("divisionPick")}
  ${fn("vendorNames")}
  ${fn("similarNames")}
  ${fn("dupeHtml")}
  ${fn("datesHtml")}
  // LIFTED, not stubbed, and it has to be lifted BEFORE the three renderers that call it.
  // renderItems, renderRefSection and renderPanel each ask icon() for a glyph now; leaving it
  // out is a ReferenceError that kills every scenario in this file at once.
  ${fn("icon")}
  ${fn("renderItems")}
  ${fn("adminList")}
  ${fn("usageFor")}
  ${fn("singular")}
  ${fn("renderRefSection")}
  ${fn("renderVendors")}
  // The Items tab's own search. itemQuery is settable from state so a test can render the
  // filtered view; on the page it is a plain variable that nothing serialises, which is the whole
  // point of it (the dropdown filters deleted on 2026-08-19 were being saved to the server).
  var itemQuery = state.itemQuery === undefined ? "" : state.itemQuery;
  ${fn("visibleItems")}
  ${fn("nameKey")}
  ${fn("duplicateName")}
  ${fn("itemMatches")}
  ${fn("itemResultsHtml")}
  ${fn("lineForSave")}
  ${fn("pickerFor")}
  ${fn("itemByName")}
  ${fn("renderList")}
  ${fn("renderPanel")}
  ${fn("refreshNumbers")}
  ${grab(/^  var NUMERIC_ITEM_FIELDS = \[[^\]]*\];$/m, "NUMERIC_ITEM_FIELDS")}
  // The real handler, with only the network stubbed. Everything it touches on the way to the
  // model — the coercion list, the duplicate hint, the queued body — is the code the page runs.
  var QUEUED = [];
  function patchSoon(kind, id, body) { QUEUED.push({ kind: kind, id: id, body: body }); }
  // The pre-edit snapshot the confirmation dialog quotes and Cancel restores from. LIFTED, not
  // stubbed: onItemEdit calls rememberItem on every keystroke, so a stub here would be testing a
  // different function from the one that ships. The DIALOG itself is not reachable from this
  // scope — it fires at flush time inside the real patchSoon, which is stubbed here and exercised
  // in saveScope below, and that split is the whole reason the dialog was not put in onItemEdit.
  var itemBefore = {};
  ${fn("snapshotItem")}
  ${fn("rememberItem")}
  ${fn("onItemEdit")}
  return { renderItems, renderVendors, renderPanel, renderList, refreshNumbers,
           pickerFor, itemByName, similarNames, pick, datesHtml, adoptSaved,
           onItemEdit, QUEUED, NUMERIC_ITEM_FIELDS, ITEMS, VENDORS,
           itemMatches, itemResultsHtml, lineForSave, visibleItems, duplicateName, nameKey,
           snapshotOf: function (id) { return itemBefore[id]; } };
`);

// Two materials: a legacy pack-of-one and a five-gallon pail, so the pack column has something to
// be wrong about.
const ITEMS = [
  { id: "i1", name: "OPF", category: "Epoxy", unit: "Gal", buy_qty: 1, unit_cost: 85.3827,
    coverage: 275, vendor: "Sherwin-Williams", notes: "",
    created_at: "2026-08-01T14:30:00Z", cost_updated_at: null },
  { id: "i2", name: "OPF Primer", category: "Polished Concrete", unit: "Gallon", buy_qty: 5,
    unit_cost: 426.91, coverage: 275, vendor: "Gone Supply Co", notes: "",
    created_at: "2026-08-02T09:00:00Z", cost_updated_at: "2026-08-14T21:15:00Z" },
];
const ASMS = [{
  id: "a1", name: "MACRO Flake", unit: "SF",
  lines: [
    { role: "1st BC", item_id: "i1", coverage: 275, waste_pct: 5, roundup: true, note: "" },
    { role: "", item_id: "i2", coverage: 275, waste_pct: 0, roundup: false, note: "" },
  ],
}];
const VENDORS = [{ id: "v1", name: "Sherwin-Williams", notes: "KC branch" },
                 { id: "v2", name: "Sika", notes: "" }];

function build(overrides, docSelectors) {
  const d = makeDom();
  const st = Object.assign({
    ITEMS: JSON.parse(JSON.stringify(ITEMS)),
    ASMS: JSON.parse(JSON.stringify(ASMS)),
    VENDORS: JSON.parse(JSON.stringify(VENDORS)),
    DIVISION_REFS: [{ id: "d1", name: "Polished Concrete", notes: "" },
                    { id: "d2", name: "Epoxy", notes: "" },
                    { id: "d3", name: "Gypsum Underlayment", notes: "" }],
    UNIT_REFS: [{ id: "u1", name: "Gallon", notes: "" },
                { id: "u2", name: "Kit", notes: "" },
                { id: "u3", name: "Bag", notes: "" }],
    VENDOR_USE: { "sherwin-williams": 1, sika: 0 },
    DIVISION_USE: { epoxy: 1, "polished concrete": 1 },
    UNIT_USE: { gal: 1, gallon: 1 },
    ADMIN: false, openId: "a1",
  }, overrides || {});
  const TW = { fmtBizDateTime: (iso) => "BIZ(" + iso + ")" };
  const doc = makeDocument(docSelectors || []);
  const api = scope(L, d.el, TW, st, doc);
  d.el("area").value = "2875";
  return { api, dom: d, st, doc };
}

const out = {};

// ── Items: the columns Hanz asked for, and the ones he asked to lose ─────────
{
  const { api, dom: d } = build();
  api.renderItems();
  const row = d.nodes["items-body"].innerHTML.split("</tr>")[0];
  out.items = {
    // Present. The division cell is now a chip strip (see out.divisions below); the checkbox
    // markup this used to pin was replaced on 2026-08-24 at Hanz's request.
    hasDivisionChips: /class="division-chips"/.test(row) && /data-f="divisions"/.test(row),
    divisionOptions: divisionCellOf(row)
      .split('data-div="').slice(1).map((o) => o.split('"')[0]),
    hasBuyQty: /data-f="buy_qty"/.test(row),
    hasUnitDropdown: /<select data-f="unit"/.test(row),
    unitOptions: (row.match(/<select data-f="unit"[\s\S]*?<\/select>/) || [""])[0]
      .split("<option").slice(1).map((o) => (/>([^<]*)</.exec(o) || ["", ""])[1]),
    hasVendorDropdown: /<select data-f="vendor"/.test(row),
    costWearsADollarSign: /<span class="money"><span>\$<\/span><input data-f="unit_cost"/.test(row),
    // Gone: coverage left the Items tab, and the material name is no longer a bare text box.
    hasCoverage: /data-f="coverage"/.test(d.nodes["items-body"].innerHTML),
    nameOffersAutosuggest: /data-f="name"[^>]*list="dl-materials"/.test(row),
    datalistFilled: /value="OPF"/.test(d.nodes["dl-materials"].innerHTML) &&
      /value="OPF Primer"/.test(d.nodes["dl-materials"].innerHTML),
    count: d.nodes["n-items"].textContent,
  };
  // A legacy unit ("Gal") is not on the offered list and must survive being rendered.
  const legacyUnitSelect = (row.match(/<select data-f="unit"[\s\S]*?<\/select>/) || [""])[0];
  out.items.legacyUnitKept = /<option value="Gal" selected>Gal<\/option>/.test(legacyUnitSelect);
  // Same for a vendor that has left the list: the item still records where it came from.
  const secondRow = d.nodes["items-body"].innerHTML.split("</tr>")[1];
  const vendSel = (secondRow.match(/<select data-f="vendor"[\s\S]*?<\/select>/) || [""])[0];
  out.items.offListVendorKept = /<option value="Gone Supply Co" selected>/.test(vendSel);
  out.items.offListVendorNotDuplicated =
    (vendSel.match(/<option value="Gone Supply Co"/g) || []).length === 1;
}

// ── EXECUTED: the division chips ─────────────────────────────────────────────
// Hanz, 2026-08-24: "For the [divisions] can we have it in just one row? Also instead of a
// checkbox please pick a better UI that allows a material to have multiple divisions but they show
// up in one row." Three stacked checkbox labels made every row three lines tall.
//
// EXECUTED, because every interesting failure here is invisible to a grep:
//   * "two divisions render as on" is about which inputs carry `checked`, which depends on
//     itemDivisions, the case-folding, and the legacy `category` fallback all agreeing.
//   * "toggling one leaves the other alone" runs the REAL onItemEdit against a row parsed from the
//     REAL rendered markup, so a renamed attribute breaks the selector rather than the assertion.
//   * "one line for three" is a width fact. The old control was `flex-wrap:wrap` too — it stacked
//     because the box was 170px. Asserting `display:flex` alone would have passed on the bug.
{
  const twoDivs = build({ ITEMS: [{ id: "i1", name: "OPF", divisions: ["Epoxy", "polished concrete"],
    unit: "Gallon", buy_qty: 5, unit_cost: 100, coverage: 275, vendor: "Sika",
    created_at: "2026-08-01T14:30:00Z", cost_updated_at: null }] });
  twoDivs.api.renderItems();
  const cell = divisionCellOf(twoDivs.dom.nodes["items-body"].innerHTML.split("</tr>")[0]);
  const chips = (cell.match(/<label class="dchip"[\s\S]*?<\/label>/g) || []);
  const inputTags = cell.match(/<input[^>]*data-f="divisions"[^>]*>/g) || [];

  out.divisions = {
    // MULTI-SELECT, AND IT LOOKS IT: two chips on at once, each an independent checkbox inside a
    // group. Nothing here is a radio, and nothing here is a select.
    group: /<div class="division-chips" role="group" aria-label="Divisions">/.test(cell),
    chipCount: chips.length,
    onOff: inputTags.map((t) => [(/data-div="([^"]*)"/.exec(t) || ["", ""])[1], / checked>/.test(t)]),
    noRadios: !/type="radio"/.test(cell),
    // KEYBOARD AND SCREEN READER: a real checkbox, so Tab and Space and the announced state come
    // for free. Each carries its own accessible name, so "checked, Epoxy" is what gets read out
    // rather than "checked" on an unnamed box.
    everyChipIsACheckbox: inputTags.length > 0 && inputTags.every((t) => /type="checkbox"/.test(t)),
    everyChipHasAnAccessibleName: inputTags.length > 0 && inputTags.every((t) => {
      const div = (/data-div="([^"]*)"/.exec(t) || ["", ""])[1];
      return (/aria-label="([^"]*)"/.exec(t) || ["", ""])[1] === div;
    }),
    // The state mark must not end up in that name, which is why it is hidden from the tree.
    markIsHiddenFromTheTree: /<span class="dchip-mark" aria-hidden="true">/.test(cell),
    // The full name is always available even when the visible text is clipped.
    everyChipCarriesItsFullNameInATitle: chips.length > 0 && chips.every((c) => {
      const t = (/<label class="dchip" title="([^"]*)"/.exec(c) || ["", ""])[1];
      return t === (/data-div="([^"]*)"/.exec(c) || ["", "x"])[1];
    }),
    // THE SAVE CONTRACT IS UNCHANGED: still data-f="divisions" + data-div="NAME" on the input.
    // The length guard matters — `every` on an empty list is true, so a renamed attribute would
    // pass this while onItemEdit's own selector found nothing.
    contractUnchanged: inputTags.length === 3 &&
      inputTags.every((t) => /data-f="divisions"/.test(t) && /data-div="/.test(t)),
  };

  // A DIVISION ADDED ON THE ADMINISTRATION TAB reaches the chips. The step that turns the fetched
  // refs into the offered list is LIFTED OUT OF load() rather than restated here, so deleting it
  // there breaks this instead of leaving a test that agrees with itself.
  const REFS = [{ id: "d1", name: "Polished Concrete", notes: "" },
                { id: "d2", name: "Epoxy", notes: "" },
                { id: "d3", name: "Gypsum Underlayment", notes: "" },
                { id: "d4", name: "Sealer & Traffic Coatings", notes: "" }];
  const offeredList = new Function("DIVISION_REFS", "DEFAULT_DIVISIONS", `
    "use strict";
    var DIVISIONS;
    ${grab(/^\s*DIVISIONS = \(DIVISION_REFS\.length \?[^\n]*$/m, "the DIVISIONS assignment in load()")}
    return DIVISIONS;
  `);
  const custom = build({
    DIVISION_REFS: REFS,
    DIVISIONS: offeredList(REFS, ["Polished Concrete", "Epoxy", "Gypsum Underlayment"]),
    ITEMS: [{ id: "i1", name: "OPF", divisions: ["Sealer & Traffic Coatings"], unit: "Gallon",
              buy_qty: 1, unit_cost: 1, coverage: 275, vendor: "", created_at: null,
              cost_updated_at: null }],
  });
  custom.api.renderItems();
  const customCell = divisionCellOf(custom.dom.nodes["items-body"].innerHTML.split("</tr>")[0]);
  out.divisions.customIsOffered =
    (customCell.match(/data-div="([^"]*)"/g) || []).map((m) => m.slice(10, -1));
  // Escaped, not injected — a division name is free text somebody typed on the Administration tab.
  out.divisions.customIsEscaped = /data-div="Sealer &amp; Traffic Coatings"/.test(customCell) &&
    !/data-div="Sealer & Traffic/.test(customCell);
  out.divisions.customRendersAsOn = / checked>/.test(
    (customCell.match(/<input[^>]*data-div="Sealer &amp; Traffic Coatings"[^>]*>/) || [""])[0]);
  // And a name only an OLD ITEM holds, which is not on any list at all: still offered, still
  // correctable. A division can be deleted from the Administration tab without rewriting items.
  const orphan = build({
    ITEMS: [{ id: "i1", name: "OPF", divisions: ["Terrazzo Restoration Systems"], unit: "Gallon",
              buy_qty: 1, unit_cost: 1, coverage: 275, vendor: "", created_at: null,
              cost_updated_at: null }],
  });
  orphan.api.renderItems();
  const orphanCell = divisionCellOf(orphan.dom.nodes["items-body"].innerHTML.split("</tr>")[0]);
  out.divisions.offListItemValueStillOffered =
    (orphanCell.match(/data-div="([^"]*)"/g) || []).map((m) => m.slice(10, -1));

  // TOGGLING ONE LEAVES THE OTHERS ALONE. The browser flips the box, then the handler reads the
  // row — the same order a click on the label produces.
  const row = chipRowFromHtml("i1", cell);
  const target = row.inputs.filter((x) => x.div === "Epoxy")[0];
  target.checked = false;
  twoDivs.api.onItemEdit({ target: target });
  out.divisions.afterTurningEpoxyOff = {
    model: twoDivs.api.ITEMS[0].divisions.slice(),
    category: twoDivs.api.ITEMS[0].category,
    queued: twoDivs.api.QUEUED.map((q) => q.kind + " " + JSON.stringify(q.body)),
  };
  // And back on, plus a third: two selected at once is legal and stays legal.
  target.checked = true;
  row.inputs.filter((x) => x.div === "Gypsum Underlayment")[0].checked = true;
  twoDivs.api.onItemEdit({ target: target });
  out.divisions.afterTurningTwoMoreOn = twoDivs.api.ITEMS[0].divisions.slice();
  // Emptying it is allowed: a material can be waiting to be filed.
  row.inputs.forEach((x) => { x.checked = false; });
  twoDivs.api.onItemEdit({ target: row.inputs[0] });
  out.divisions.canBeEmptied = twoDivs.api.ITEMS[0].divisions.length === 0 &&
    twoDivs.api.QUEUED[twoDivs.api.QUEUED.length - 1].body.divisions.length === 0;

  // ── ONE ROW. The width facts, read off the real stylesheet ─────────────────
  const rule = (sel) => (new RegExp(sel.replace(/[.>*+?^${}()|[\]\\]/g, "\\$&") +
    "\\s*\\{[^}]*\\}").exec(html) || [""])[0];
  const strip = rule(".division-chips");
  const face = rule(".dchip-f");
  const px = (re, s) => Number((re.exec(s) || [0, 0])[1]);
  const stripMin = px(/min-width:(\d+)px/, strip);
  const stripMax = px(/max-width:(\d+)px/, strip);
  const fontPx = px(/font:\s*\d+\s+([\d.]+)px/, face);
  const padParts = ((/padding:([^;]+);/.exec(face) || ["", "0"])[1]).trim().split(/\s+/)
    .map((v) => parseFloat(v));
  const padX = padParts.length >= 4 ? padParts[1] + padParts[3]
             : padParts.length === 2 ? padParts[1] * 2 : padParts[0] * 2;
  const innerGap = px(/gap:(\d+)px/, face);
  const markW = px(/width:(\d+)px/, rule(".dchip-mark"));
  const stripGap = px(/gap:(\d+)px/, strip);
  // 0.55em per character. A UI sans at this size averages nearer 0.52em over mixed-case text, so
  // this over-estimates slightly on purpose: the question is whether the column has room to spare,
  // and a floor-value estimate would let a too-narrow column pass and wrap in the browser.
  const chipWidth = (name) => name.length * fontPx * 0.55 + padX + innerGap + markW + 2;
  const three = ["Polished Concrete", "Epoxy", "Gypsum Underlayment"];
  const needFor = (names) => names.reduce((s, n) => s + chipWidth(n), 0) +
    stripGap * Math.max(0, names.length - 1);
  out.divisions.width = {
    fontPx: fontPx, stripMin: stripMin, stripMax: stripMax,
    // Side by side, not stacked, and a name never breaks across two lines.
    stripIsAFlexRow: /display:flex/.test(strip) && /flex-wrap:wrap/.test(strip),
    chipIsInline: /display:inline-flex/.test(face) && /white-space:nowrap/.test(face),
    // The three real divisions fit on ONE line.
    neededForThree: Math.round(needFor(three)),
    threeFitOnOneLine: needFor(three) <= stripMin,
    // Six and ten WRAP rather than widen the table: the column is capped, so the strip grows
    // downwards. Two lines at six, four at ten.
    neededForSix: Math.round(needFor(three.concat(three))),
    sixWraps: needFor(three.concat(three)) > stripMax,
    tenWraps: needFor(three.concat(three, three, ["Sealer"])) > stripMax,
    cappedSoTheTableCannotStretch: stripMax > 0 && stripMax < needFor(three.concat(three)),
    // A long custom name keeps enough of itself to stay distinct from the next one along.
    textClampChars: px(/max-width:(\d+)ch/, rule(".dchip-t")),
    textClampEllipsises: /text-overflow:ellipsis/.test(rule(".dchip-t")),
  };

  // ── the state is not colour alone, and the input is still operable ─────────
  const onFace = rule(".dchip > input:checked + .dchip-f");
  const hiddenInput = rule(".dchip > input");
  out.divisions.state = {
    // The pill fills in when it is on, the way the CRM drawer's notification chips do.
    onHasItsOwnFill: /background:/.test(onFace) && /border-color:/.test(onFace),
    // SHAPE, not just hue: the mark differs between the two states, so the on chips can be counted
    // by somebody who cannot separate the green from the grey.
    offMark: (/content:"([^"]*)"/.exec(rule(".dchip-mark::before")) || ["", ""])[1],
    onMark: (/content:"([^"]*)"/.exec(
      rule(".dchip > input:checked + .dchip-f .dchip-mark::before")) || ["", ""])[1],
    // Hidden from sight, NOT from the keyboard. display:none or visibility:hidden would take the
    // control out of the tab order and leave Space nothing to press.
    inputIsClippedNotRemoved: /clip-path:inset\(50%\)/.test(hiddenInput) &&
      !/display:none|visibility:hidden/.test(hiddenInput),
    focusRingOnTheFace: /outline:/.test(rule(".dchip > input:focus-visible + .dchip-f")),
    // The control the old markup used is gone, along with its stacking box.
    oldCheckboxStyleGone: !/\.division-picks/.test(html) && !/class="division-picks"/.test(src),
  };
}

// ── the price date lands on screen without a reload ──────────────────────────
{
  // The selector list is taken from what renderItems ACTUALLY emits, so renaming the cell's class
  // breaks this rather than quietly making the repaint a no-op.
  const rendered = build();
  rendered.api.renderItems();
  const cellClass = /<td class="([a-z]+)">\s*<div class="dates"/.exec(
    rendered.dom.nodes["items-body"].innerHTML);
  const sel = '[data-item="i1"] .' + (cellClass ? cellClass[1] : "MISSING");

  const b = build({}, [sel]);
  // The server replies to a cost PATCH with the row it stored: same updated_at bump, plus a
  // cost_updated_at that only it can decide.
  b.api.adoptSaved("items", { id: "i1", updated_at: "2026-08-15T00:00:01Z",
                              cost_updated_at: "2026-08-15T00:00:01Z" });
  const wrote = b.doc.writes;
  out.priceDate = {
    cellClass: cellClass ? cellClass[1] : null,
    modelAdopted: b.api.ITEMS[0].cost_updated_at,
    repainted: wrote.length === 1,
    repaintedSelector: wrote.length ? wrote[0].sel : null,
    repaintShowsTheNewDate: wrote.length
      ? /BIZ\(2026-08-15T00:00:01Z\)/.test(wrote[0].html) : false,
    repaintDroppedTheNeverLine: wrote.length
      ? !/not since we started tracking/.test(wrote[0].html) : false,
  };

  // A patch that did NOT change the cost must not repaint — and must not invent a date.
  const quiet = build({}, [sel]);
  quiet.api.adoptSaved("items", { id: "i1", updated_at: "2026-08-15T00:00:02Z",
                                  cost_updated_at: null });
  out.priceDate.quietPatchNoRepaint = quiet.doc.writes.length === 0;
  out.priceDate.quietPatchStillBumpedVersion =
    quiet.api.ITEMS[0].updated_at === "2026-08-15T00:00:02Z";

  // An assembly save must never reach into the items table.
  const asm = build({}, [sel]);
  asm.api.adoptSaved("assemblies", { id: "a1", updated_at: "2026-08-15T00:00:03Z" });
  out.priceDate.assemblySaveDoesNotRepaintItems = asm.doc.writes.length === 0;
}

// ── the vendor dropdown offers more than the curated list ────────────────────
{
  // No curated vendors at all — a fresh install, or before an admin has got to it. The estimator
  // must still be able to record where a material came from, or a dropdown replaces a text box
  // with nothing in it and only two people in the company can fix that.
  const bare = build({ VENDORS: [] });
  bare.api.renderItems();
  const rows = bare.dom.nodes["items-body"].innerHTML;
  const sel = (i) =>
    (rows.split("</tr>")[i].match(/<select data-f="vendor"[\s\S]*?<\/select>/) || [""])[0];
  // Same supplier, two spellings on two items: the curated one wins and the other is not offered
  // back, or the list would re-create the duplication it exists to end.
  const messy = build({
    VENDORS: [{ id: "v1", name: "Sherwin-Williams", notes: "" }],
    ITEMS: JSON.parse(JSON.stringify(ITEMS)).map((it, i) =>
      Object.assign(it, { vendor: i === 0 ? "sherwin-williams" : "Gone Supply Co" })),
  });
  messy.api.renderItems();
  const messyOpts = (messy.dom.nodes["items-body"].innerHTML
    .match(/<select data-f="vendor"[\s\S]*?<\/select>/) || [""])[0]
    .split("<option").slice(1).map((o) => (/value="([^"]*)"/.exec(o) || ["", ""])[1]);
  out.vendorOptions = {
    withNoCuratedList: [0, 1].map((i) => /<option value="Sherwin-Williams"/.test(sel(i)) ||
      /<option value="Gone Supply Co"/.test(sel(i))),
    messyOpts,
    curatedSpellingWins: messyOpts.indexOf("Sherwin-Williams") !== -1 &&
      messyOpts.indexOf("sherwin-williams") === -1,
    uncuratedStillOffered: messyOpts.indexOf("Gone Supply Co") !== -1,
  };
}

// ── the duplicate hint ───────────────────────────────────────────────────────
{
  const { api } = build();
  out.dupes = {
    // "OPF" is a prefix of "OPF Primer" — the exact way one product gets entered twice.
    onSimilar: api.similarNames("OPF Prim", "i1"),
    // Never itself, or every row would accuse itself of being a duplicate the moment it was typed.
    notItself: api.similarNames("OPF", "i1").indexOf("OPF") === -1,
    // Two characters is not yet a name.
    quietWhileTyping: api.similarNames("OP", "zz"),
    unrelated: api.similarNames("Sika Level 125", "zz"),
  };
}

// ── the dates ────────────────────────────────────────────────────────────────
{
  const { api } = build();
  const withPrice = api.datesHtml(
    { created_at: "2026-08-02T09:00:00Z", cost_updated_at: "2026-08-14T21:15:00Z" });
  const never = api.datesHtml({ created_at: "2026-08-01T14:30:00Z", cost_updated_at: null });
  out.dates = {
    // Through TW.fmtBizDateTime, so the stamps read in Central and carry a time.
    usesBusinessTime: /BIZ\(2026-08-02T09:00:00Z\)/.test(withPrice) &&
      /BIZ\(2026-08-14T21:15:00Z\)/.test(withPrice),
    saysAddedAndPrice: /Added/.test(withPrice) && /Price/.test(withPrice),
    // Not "—" and not today's date: a material whose price has never moved must not look
    // freshly priced.
    neverPricedSaysSo: /not since we started tracking/.test(never),
    neverPricedShowsNoDate: !/BIZ\(2026-08-14/.test(never),
  };
}

// ── Vendors: admin edits, everybody else reads ───────────────────────────────
{
  const plain = build({ ADMIN: false });
  plain.api.renderVendors();
  const asUser = plain.dom.nodes["divisions-body"].innerHTML +
    plain.dom.nodes["units-body"].innerHTML + plain.dom.nodes["vendors-body"].innerHTML;
  const admin = build({ ADMIN: true });
  admin.api.renderVendors();
  const asAdmin = admin.dom.nodes["divisions-body"].innerHTML +
    admin.dom.nodes["units-body"].innerHTML + admin.dom.nodes["vendors-body"].innerHTML;
  out.vendors = {
    userGetsNoInputs: !/<input/.test(asUser),
    userGetsNoDeleteButton: !/data-del-ref/.test(asUser),
    userStillSeesTheNames: /Polished Concrete/.test(asUser) && /Gallon/.test(asUser) &&
      /Sherwin-Williams/.test(asUser) && /Sika/.test(asUser),
    userToldWhoToAsk: plain.dom.nodes["vendors-ro"].hidden === false,
    userNotOfferedAddButtons: !/data-add-ref/.test(asUser),
    adminGetsInputs: /<input data-rf="name"/.test(asAdmin) && /<input data-rf="notes"/.test(asAdmin),
    adminGetsDelete: /data-del-ref="vendors"/.test(asAdmin) &&
      /data-del-ref="divisions"/.test(asAdmin) && /data-del-ref="units"/.test(asAdmin),
    adminNotShownTheReadOnlyNote: admin.dom.nodes["vendors-ro"].hidden === true,
    adminOfferedAdd: true,
    // How many materials name each vendor, so a delete can say what it affects.
    usageShown: /<td class="n">1<\/td>/.test(asAdmin),
    sectionOrder: ["divisions-body", "units-body", "vendors-body"].every((id) => !!admin.dom.nodes[id]),
  };
}

// ── the assembly line: Role gone, waste and roundup in, picker searchable ────
{
  const { api, dom: d } = build();
  api.renderPanel();
  const body = d.nodes["lines-body"].innerHTML;
  const firstRow = body.split("</tr>")[0];
  const tds = firstRow.split("<td").slice(1);
  const qtyIdx = tds.findIndex((t) => /class="qty"/.test(t));
  const costIdx = tds.findIndex((t, i) => i > qtyIdx && /class="qty"/.test(t));
  out.lines = {
    roleColumnGone: !/data-lf="role"/.test(body),
    hasWaste: /data-lf="waste_pct"/.test(firstRow),
    hasRoundupCheckbox: /type="checkbox" data-lf="roundup"/.test(firstRow),
    roundupTicksFromTheData: /data-lf="roundup" checked/.test(firstRow) &&
      !/data-lf="roundup" checked/.test(body.split("</tr>")[1]),
    // A search box with autofill, not a <select>: the list is going to get long.
    pickerIsSearchable: /<div class="item-picker">/.test(firstRow) &&
      /data-lf="item_search"/.test(firstRow),
    // ONE LINE ITEM, ONE ROW. No filter dropdowns and no "Divisions" label inside the row — those
    // belong to the header, and having them in the cell made one line item a tall block.
    pickerHasNoInRowFilters: !/item_division_filter|item_vendor_filter/.test(body) &&
      !/<span>Divisions<\/span>/.test(body),
    // Closed, the box shows the chosen item rather than an open list of candidates.
    pickerShowsTheCurrentMaterial: /data-lf="item_search" value="OPF"/.test(firstRow),
    pickerStartsClosed: !/class="item-results"/.test(body),
    rowCount: (body.match(/<tr/g) || []).length,
    pickerIsNotASelect: !/<select data-lf="item_id"/.test(body),
    rowCellsTopAligned: /\.lines td \{ vertical-align:top; \}/.test(html),
    primaryLineCount: (firstRow.match(/class="line-primary/g) || []).length,
    deleteControlAligned: /\.lines td > \.icon \{[^}]*min-height:32px/.test(html),
    tdCount: tds.length,
    qtyIdx, costIdx,
    // The two modes, rendered: whole packs vs the fraction.
    firstQtyLabel: (/<span class="qty">([^<]*)</.exec(tds[qtyIdx]) || ["", ""])[1],
    secondQtyLabel: (/<span class="qty">([^<]*)</
      .exec(body.split("</tr>")[1].split("<td").slice(1)[qtyIdx]) || ["", ""])[1],
  };

  // THE POSITIONAL CONTRACT. refreshNumbers writes tds[QTY_TD] / tds[COST_TD] on a table
  // renderPanel built, and the two functions never see each other. Lifted from the source and
  // compared with where the cells actually landed.
  const rn = fn("refreshNumbers");
  const qm = /var QTY_TD = (\d+), COST_TD = (\d+);/.exec(rn);
  out.lines.updaterIndexes = qm ? [Number(qm[1]), Number(qm[2])] : null;
  out.lines.indexesAgree = !!qm && Number(qm[1]) === qtyIdx && Number(qm[2]) === costIdx;
  // The empty-state placeholder has to span the columns that now exist.
  const empty = build({ ASMS: [{ id: "a1", name: "Bare", unit: "SF", lines: [] }] });
  empty.api.renderPanel();
  out.lines.placeholderColspan = Number(
    (/colspan="(\d+)"/.exec(empty.dom.nodes["lines-body"].innerHTML) || [0, 0])[1]);
}

// ── EXECUTED: one row per line item, and a search that looks at three fields ─
// Hanz, 2026-08-19: "divisions should be a label up top like before not on the row. Make one line
// item, one row." The previous picker rendered an always-open panel — search box, a Divisions
// label, two filter selects, twelve results — inside every ITEMS cell, so one line was a tall
// block. These run the real matcher and the real renderer rather than reading the source.
{
  const { api } = build();
  // The fixtures differ in BOTH fields the search now reaches: i1 is Epoxy / Sherwin-Williams,
  // i2 is Polished Concrete / Gone Supply Co. A matcher that only read `name` would answer these
  // identically, since both names begin "OPF".
  const names = (q) => api.ITEMS.filter((it) => api.itemMatches(it, q)).map((it) => it.name);
  out.itemSearch = {
    byName: names("primer"),
    byDivision: names("polished"),
    byVendor: names("sherwin"),
    // "combination of those" — a division word AND a name word, which must narrow rather than
    // find nothing. This is the case a single-field matcher gets wrong.
    byCombination: names("polished primer"),
    caseInsensitive: names("SHERWIN"),
    blankFindsEverything: names("").length,
    nonsenseFindsNothing: names("zzz not a material"),
  };

  // The results markup, from the real builder: every row names its division and vendor, so a match
  // on something other than the name is never a mystery.
  const openLine = { item_id: "i1", _item_search: "polished" };
  const resultsHtml = api.itemResultsHtml(openLine);
  out.itemSearch.resultNamesDivisionAndVendor =
    /Polished Concrete &middot; Gone Supply Co/.test(resultsHtml);
  out.itemSearch.resultsAreButtonsKeyedByItemId = /data-pick-item="i2"/.test(resultsHtml);
  out.itemSearch.emptySearchSaysSo =
    /No items match that search/.test(api.itemResultsHtml({ _item_search: "zzzz" }));

  // CLOSED: the box shows the chosen item and emits no list, so the row is one row high.
  const closed = api.pickerFor({ item_id: "i1", _item_search: "polished" }, 0);
  // OPEN: the same line, with its picker open, gains the floating list — and nothing else.
  const openApi = build({ pickerOpen: 0 }).api;
  const opened = openApi.pickerFor({ item_id: "i1", _item_search: "polished" }, 0);
  out.itemSearch.closedShowsTheItem = /value="OPF"/.test(closed);
  out.itemSearch.closedHasNoResults = !/item-results/.test(closed);
  out.itemSearch.openShowsResults = /class="item-results"/.test(opened);
  // Open, the box holds the QUERY, not the item name — otherwise 30 characters must be deleted
  // before three can be typed.
  out.itemSearch.openShowsTheQuery = /value="polished"/.test(opened);
  // A different line's picker being open must not open this one's.
  out.itemSearch.onlyTheOpenLineExpands =
    !/item-results/.test(openApi.pickerFor({ item_id: "i2" }, 1));

  // The transient query rides on the line while typing; the SAVE must not carry it.
  out.itemSearch.savePayloadIsClean = Object.keys(
    api.lineForSave({ item_id: "i1", coverage: 275, waste_pct: 5, roundup: true,
                      _item_search: "polished", _division_filter: "Epoxy" })).sort();
}

// ── EXECUTED: the live updater, on the table renderPanel actually built ──────
// The earlier version of this check regex-scraped `var QTY_TD = 4, COST_TD = 5;` out of the source
// and compared the numbers with the rendered column positions. Both agreed — and the two writes
// were transposed, so the constants were right and the content went into the wrong cells. That
// version reached staging. This one runs the function.
{
  const { api, dom: d } = build();
  api.renderPanel();
  const rows = d.nodes["lines-body"].querySelectorAll("[data-line]");
  // Nothing has been written yet: refreshNumbers is what fires on a keystroke.
  const before = rows.map((r) => r.cells.map((c) => c.written));
  api.refreshNumbers();
  const first = rows[0].cells.map((c) => c.written);
  const second = rows[1].cells.map((c) => c.written);
  out.liveUpdate = {
    untouchedBefore: before.every((r) => r.every((c) => c === null)),
    // Cell 4 is Quantity, cell 5 is Cost — per the <thead> the page ships.
    qtyCellGotTheQuantity: /class="qty">11 Gal</.test(first[5] || ""),
    costCellGotTheMoney: /class="qty">\$939/.test(first[6] || ""),
    // …and neither got the other's content, which is the transposition, stated directly.
    qtyCellHasNoDollarAmount: !/\$[\d,]+\.\d\d</.test(first[5] || ""),
    costCellHasNoUnitLabel: !/>1?1 Gal</.test(first[6] || ""),
    // The columns a user types in must not be written at all, or the input under the caret dies.
    inputCellsUntouched: [0, 1, 2, 3, 4].every((i) => first[i] === null),
    deleteCellUntouched: first[7] === null,
    // The fractional row shows its own working, not the rounded one's.
    secondRowQty: (/class="qty">([^<]*)</.exec(second[5] || "") || ["", ""])[1],
    secondRowWorking: (/class="calc mono">([^<]*)</.exec(second[6] || "") || ["", ""])[1],
    totalWritten: d.nodes["t-total"].textContent,
    perUnitWritten: d.nodes["t-unit"].textContent,
  };

  // A broken line must be reported in the Quantity cell and cleared out of the Cost cell.
  const broken = build({ ASMS: [{ id: "a1", name: "Broken", unit: "SF", lines: [
    { item_id: "deleted-material", coverage: 275, waste_pct: 5, roundup: true }] }] });
  broken.api.renderPanel();
  const brows = broken.dom.nodes["lines-body"].querySelectorAll("[data-line]");
  broken.api.refreshNumbers();
  const bcells = brows[0].cells.map((c) => c.written);
  out.liveUpdate.brokenSaysSoInTheQtyCell = /Item removed/.test(bcells[5] || "");
  out.liveUpdate.brokenCostCellCleared = bcells[6] === "—";
  out.liveUpdate.brokenCostCellClearedInsideAlignment = /line-primary/.test(bcells[6] || "") &&
    !/\$|Item removed|Needs/.test(bcells[6] || "");
  out.liveUpdate.brokenRowFlagged = brows[0].classList.has("broken");
}

// ── EXECUTED: the item edit handler, not just its field list ─────────────────
// The earlier check read the NUMERIC_ITEM_FIELDS array literal. Deleting the ternary that CONSULTS
// it left the array intact, so the test passed while every typed number went into the model as a
// string. That also reached staging.
{
  // `keep` lets two consecutive edits share one cell — required to observe the hint being REMOVED.
  // A fresh cell per call made "the hint went away" true no matter what the handler did.
  function edit(api, dom, itemId, field, raw, keep) {
    const cell = keep || { hint: null,
      querySelector: (sel) => (sel === ".dupe" ? cell.hint : null),
      insertAdjacentHTML: (_where, html) => { cell.hint = { textContent: html, remove() { cell.hint = null; } }; } };
    api.onItemEdit({ target: {
      getAttribute: (k) => (k === "data-f" ? field : null),
      value: raw,
      parentNode: cell,
      closest: (sel) => (sel === "[data-item]"
        ? { getAttribute: () => itemId } : null),
    } });
    return cell;
  }
  const { api, dom: d } = build();
  api.renderItems();
  edit(api, d, "i1", "buy_qty", "5");
  edit(api, d, "i1", "unit_cost", "$1,200.50");
  edit(api, d, "i1", "coverage", " 275 ");
  edit(api, d, "i1", "vendor", "Sika");
  const it = api.ITEMS[0];
  out.itemEdit = {
    // Numbers, not strings: "5" divides by luck and concatenates the first time anything multiplies.
    buyQtyType: typeof it.buy_qty, buyQty: it.buy_qty,
    costType: typeof it.unit_cost, cost: it.unit_cost,
    coverageType: typeof it.coverage, coverage: it.coverage,
    // Text stays text.
    vendorType: typeof it.vendor, vendor: it.vendor,
    // Every edit is queued for the server as typed, in field-level bodies.
    queued: api.QUEUED.map((q) => q.kind + ":" + Object.keys(q.body).join(",")),
    queuedRaw: api.QUEUED.map((q) => Object.values(q.body)[0]),
  };
  // The duplicate hint appears and disappears through the same handler, in ONE cell — the same
  // field being typed in, which is the only way "it was removed" can fail.
  const cell = edit(api, d, "i1", "name", "OPF Primer II");
  out.itemEdit.hintShown = !!cell.hint && /Already in the list/.test(cell.hint.textContent);
  edit(api, d, "i1", "name", "Totally Different Product", cell);
  out.itemEdit.hintRemovedWhenNoLongerSimilar = !cell.hint;
  edit(api, d, "i1", "name", "OPF Primer III", cell);
  out.itemEdit.hintNotDuplicatedOnRetype =
    !!cell.hint && (String(cell.hint.textContent).match(/Already in the list/g) || []).length === 1;
}

// ── EXECUTED: the debounced save, and what a 409 does to a queued edit ───────
// Its own scope, because this needs the REAL patchSoon while the block above needs it stubbed.
// Driven by a hand-cranked clock so the race is deterministic: type → PATCH in flight → keep
// typing (re-arming the timer) → 409 lands → the repaint empties the buffer.
async function conflictChecks() {
  const saveScope = new Function("api", "clock", "hooks", "state", "TW", "L", `
    "use strict";
    var timers = {};
    var pendingPatch = {};
    var ASMS = state.ASMS, ITEMS = state.ITEMS, VENDORS = state.VENDORS;
    var setTimeout = clock.setTimeout, clearTimeout = clock.clearTimeout;
    function saving(m) { hooks.saving.push(m); }
    function say(m) { hooks.said.push(m); }
    function renderList() { hooks.renders.push("list"); }
    function renderPanel() { hooks.renders.push("panel"); }
    function renderItems() { hooks.renders.push("items"); }
    function paintDates() {}
    function datesHtml() { return ""; }
    // The item-change confirmation, REAL, because this is the scope that has the real patchSoon —
    // and the dialog fires from inside its timer callback, after the payload has been coalesced.
    // TW is a parameter so a test can answer Yes or No and read back what it was asked.
    var itemBefore = {};
    ${grab(/^  var ITEM_FIELD_LABELS = \{[\s\S]*?\n  \};$/m, "ITEM_FIELD_LABELS")}
    ${fn("itemOf")}
    ${fn("snapshotItem")}
    ${fn("rememberItem")}
    ${fn("shownValue")}
    ${fn("confirmItemPatch")}
    ${fn("byId")}
    ${fn("adoptSaved")}
    ${fn("adoptConflict")}
    ${fn("patchSoon")}
    return { patchSoon: patchSoon, adoptConflict: adoptConflict,
             rememberItem: rememberItem,
             armed: function () { return Object.keys(timers).length; },
             pending: function () { return Object.keys(pendingPatch).length; },
             // Empties the buffer WITHOUT disarming, which is the state the empty-payload guard
             // exists for. adoptConflict no longer produces it — that is the point of the fix —
             // so the guard is defence for the next code path that empties this buffer, and a
             // test of it has to construct the state deliberately rather than pretend otherwise.
             dropBuffer: function () { pendingPatch = {}; } };
  `);

  function run409(fix, answer) {
    const hooks = { saving: [], said: [], renders: [], requests: [], errors: [], asked: [] };
    // The confirmation the real patchSoon now puts in front of an ITEM save. `answer` is what the
    // estimator presses; the default is Yes so every assembly-side scenario below is unaffected,
    // which is the point — the dialog is scoped to items and must not appear anywhere else.
    const TW = { confirmDanger: async (opts) => { hooks.asked.push(opts); return answer !== false; } };
    let due = [];
    // Handles start at 1, as every browser's do — a 0 handle would make `if (timers[key])` skip,
    // which is a condition the real page never meets and would fake a pass here.
    const clock = {
      setTimeout: (fn2) => { due.push({ fn: fn2, live: true }); return due.length; },
      clearTimeout: (id) => { if (due[id - 1]) due[id - 1].live = false; },
    };
    let release;
    const inflight = new Promise((r) => { release = r; });
    const api = (path, opts) => {
      hooks.requests.push(((opts || {}).method || "GET") + " " + path);
      return inflight;
    };
    const state = { ASMS: [{ id: "a1", name: "MACRO", unit: "SF", lines: [], updated_at: "T1" }],
                    ITEMS: [{ id: "i1", name: "Densifier", unit: "Gallon", unit_cost: 42,
                              buy_qty: 5, vendor: "Sika", divisions: ["Polished Concrete"] }],
                    VENDORS: [] };
    const s = saveScope(api, clock, hooks, state, TW, L);
    return { hooks, clock, s, state, release, fire: async () => {
      const now = due; due = [];
      for (const t of now) if (t.live) { try { await t.fn(); } catch (e) { hooks.errors.push(String(e)); } }
    }, cancelledCount: () => due.filter((t) => !t.live).length };
  }

  // Scenario: the 409 arrives while a newer keystroke is already queued.
  const c = run409();
  c.s.patchSoon("assemblies", "a1", { name: "A" });
  const firing = c.fire();                       // the timer callback starts and awaits api()
  await new Promise((r) => setTimeout(r, 0));
  c.s.patchSoon("assemblies", "a1", { name: "AB" });   // …the user keeps typing: timer re-armed
  const armedBeforeConflict = c.s.armed();
  c.release({ status: 409, json: async () => ({ error: "changed", assembly:
    { id: "a1", name: "B's version", unit: "SF", lines: [], updated_at: "T2" } }) });
  await firing;
  const afterConflict = { pending: c.s.pending(), cancelled: c.cancelledCount() };
  await c.fire();                                 // whatever is still armed gets its turn
  out.conflict = {
    armedBeforeConflict,
    bufferEmptied: afterConflict.pending === 0,
    // THE FIX: the re-armed timer is disarmed too. Leaving it armed meant it fired 600ms later on
    // an empty buffer and threw before the try block — a dropped write with nothing on screen.
    timerDisarmed: afterConflict.cancelled === 1,
    noSecondRequest: c.hooks.requests.length === 1,
    noUnhandledError: c.hooks.errors.length === 0,
    screenRepainted: c.hooks.renders.join(",") === "list,panel",
    toldTheUser: c.hooks.said.some((m) => /changed/i.test(String(m))),
  };

  // And the belt to that brace: a timer that fires with nothing queued must be a quiet no-op,
  // not a TypeError thrown outside the try.
  const d2 = run409();
  d2.s.patchSoon("assemblies", "a1", { name: "A" });
  d2.s.dropBuffer();          // armed, with nothing left to send
  await d2.fire();
  out.conflict.emptyTimerIsQuiet = d2.hooks.errors.length === 0;
  out.conflict.emptyTimerSendsNothing = d2.hooks.requests.length === 0;
  // An ASSEMBLY save is never confirmed. Read off the run above rather than asserted in its own
  // scenario, because that run is a realistic assembly edit — two keystrokes, a conflict, a
  // repaint — and if the dialog had leaked out of the items branch it would have fired in it.
  out.conflict.neverAskedAboutAnAssembly = c.hooks.asked.length === 0
    && d2.hooks.asked.length === 0;

  // ── the confirmation in front of an ITEM save ──────────────────────────────
  // Hanz, 2026-08-25: items "will be connected to many assemblies and an accidental change could
  // alter the pricing." Driven through the REAL patchSoon, because the design decision under test
  // is WHERE the question is asked — at flush time, on the payload after 600ms of coalescing, not
  // on the keystroke. A test that called confirmItemPatch directly would pass with the call site
  // deleted.
  const settle = () => new Promise((r) => setTimeout(r, 0));

  async function itemRun(answer, edit, payload) {
    const c = run409(undefined, answer);
    const it = c.state.ITEMS[0];
    c.s.rememberItem(it);            // what onItemEdit does on the first keystroke of a round
    edit(it);                        // …and the model really is updated live, before the save
    c.s.patchSoon("items", "i1", payload);
    const firing = c.fire();
    await settle();
    c.release({ status: 200, ok: true,
                json: async () => ({ item: { id: "i1", name: it.name, updated_at: "T2" } }) });
    await firing;
    return { c, it };
  }

  // YES: it asks once, quotes the field that moved, and the payload goes.
  {
    const { c, it } = await itemRun(true, (x) => { x.unit_cost = 58; }, { unit_cost: "58" });
    out.itemConfirm = {
      asked: c.hooks.asked.length,
      title: (c.hooks.asked[0] || {}).title,
      name: (c.hooks.asked[0] || {}).name,
      detail: (c.hooks.asked[0] || {}).detail,
      confirmText: (c.hooks.asked[0] || {}).confirmText,
      tone: (c.hooks.asked[0] || {}).tone,
      requests: c.hooks.requests,
      costAfter: it.unit_cost,
      errors: c.hooks.errors,
    };
  }

  // TWO FIELDS IN ONE PAUSE: still one dialog, and it lists both. This is the whole reason the
  // question is asked at flush time rather than in onItemEdit.
  {
    const { c } = await itemRun(true, (x) => { x.unit_cost = 58; x.vendor = "Euclid"; },
                                { unit_cost: "58", vendor: "Euclid" });
    out.itemConfirmTwoFields = {
      asked: c.hooks.asked.length,
      title: (c.hooks.asked[0] || {}).title,
      detail: (c.hooks.asked[0] || {}).detail,
    };
  }

  // NO: nothing is sent, and the model goes back to what it said. Leaving the edit on screen with
  // the server never told is worse than the accidental change this dialog exists to catch.
  {
    const c = run409(undefined, false);
    const it = c.state.ITEMS[0];
    c.s.rememberItem(it);
    it.unit_cost = 999;
    it.vendor = "Wrong Co";
    c.s.patchSoon("items", "i1", { unit_cost: "999", vendor: "Wrong Co" });
    // Resolved BEFORE the flush, deliberately. A Cancel is supposed to send nothing, so nothing
    // should ever await this — but if the dialog stops appearing (which is what a broken snapshot
    // does: "before" mutates with the edit, the fields compare equal, and no question is asked)
    // the save proceeds and awaits a promise that would otherwise never settle. That turns a
    // detectable bug into a hung harness and 56 tests failing with no reason attached.
    c.release({ status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) });
    await c.fire();
    await settle();
    out.itemCancel = {
      asked: c.hooks.asked.length,
      requests: c.hooks.requests,
      costAfter: it.unit_cost,
      vendorAfter: it.vendor,
      repainted: c.hooks.renders.join(","),
      neverSaidSaving: c.hooks.saving.every((m) => !/Saving/.test(String(m))),
      errors: c.hooks.errors,
    };
  }

  // A DIVISION toggle is an ARRAY field, and the snapshot has to have copied it rather than
  // referenced it — otherwise "before" mutated along with the edit and Cancel would restore the
  // very value it was meant to undo, silently and with the dialog still saying it worked.
  {
    const c = run409(undefined, false);
    const it = c.state.ITEMS[0];
    c.s.rememberItem(it);
    it.divisions.push("Epoxy");                 // toggled on, in place, as onItemEdit does
    c.s.patchSoon("items", "i1", { divisions: ["Polished Concrete", "Epoxy"] });
    // Resolved BEFORE the flush, deliberately. A Cancel is supposed to send nothing, so nothing
    // should ever await this — but if the dialog stops appearing (which is what a broken snapshot
    // does: "before" mutates with the edit, the fields compare equal, and no question is asked)
    // the save proceeds and awaits a promise that would otherwise never settle. That turns a
    // detectable bug into a hung harness and 56 tests failing with no reason attached.
    c.release({ status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) });
    await c.fire();
    await settle();
    out.itemCancelArray = {
      asked: c.hooks.asked.length,
      detail: (c.hooks.asked[0] || {}).detail,
      divisionsAfter: it.divisions.slice(),
    };
  }

  // TYPED AND TYPED BACK: no dialog. patchSoon MERGES a row's fields across the quiet period, so a
  // value changed and then restored arrives identical to where it started. Asking about that is
  // how an estimator learns to dismiss the dialog without reading it, which costs more than it
  // ever saves.
  {
    const { c } = await itemRun(true, (x) => { x.unit_cost = 42; }, { unit_cost: "42" });
    out.itemNoChange = { asked: c.hooks.asked.length, requests: c.hooks.requests };
  }
}

// ── B. the Items tab's own search box ───────────────────────────────────────
// One box, no dropdowns: the division/vendor dropdowns that used to sit in the assembly picker
// were deleted on 2026-08-19 partly because their state was being persisted to the server. This
// one reuses itemMatches, the SAME matcher the picker searches with, so the two boxes on this page
// cannot disagree about what a query finds.
{
  const all = build();
  all.api.renderItems();
  const hit = build({ itemQuery: "opf primer" });
  hit.api.renderItems();
  const miss = build({ itemQuery: "nothing like this" });
  miss.api.renderItems();
  const rowsIn = (d) => (d.nodes["items-body"].innerHTML.match(/data-item=/g) || []).length;
  out.itemsSearch = {
    unfiltered: rowsIn(all.dom),
    filtered: rowsIn(hit.dom),
    missed: rowsIn(miss.dom),
    // The tab badge counts what Treadwell HAS, not what is on screen. A badge that fell as
    // somebody typed would read as materials being deleted.
    badgeWhileFiltering: all.dom.nodes["n-items"].textContent === hit.dom.nodes["n-items"].textContent,
    hits: hit.dom.nodes["item-hits"].textContent,
    hitsHiddenWhenNotFiltering: all.dom.nodes["item-hits"].hidden,
    noMatchShown: miss.dom.nodes["items-nomatch"].hidden === false,
    noMatchHiddenOnAHit: hit.dom.nodes["items-nomatch"].hidden,
    // "No materials yet" offers an Add button. It must not stand in for a bad search, or the
    // answer to a typo is an invitation to create a duplicate.
    emptyPanelStaysHidden: miss.dom.nodes["items-empty"].hidden,
    sameMatcherAsThePicker:
      JSON.stringify(hit.api.visibleItems().map((x) => x.id))
      === JSON.stringify(all.api.ITEMS.filter((x) => all.api.itemMatches(x, "opf primer")).map((x) => x.id)),
  };
}

// ── D. the name a copy gets ─────────────────────────────────────────────────
{
  const plain = build().api;
  const crowded = build({ ITEMS: [
    { id: "x1", name: "Densifier", unit: "Gallon", divisions: [] },
    { id: "x2", name: "Densifier (2)", unit: "Gallon", divisions: [] },
    { id: "x3", name: "densifier(3)", unit: "Gallon", divisions: [] },
  ] }).api;
  out.duplicateName = {
    first: plain.duplicateName("Densifier"),
    // The "(n)" comes off the stem first, or a copy of a copy is "Densifier (2) (2)".
    ofACopy: plain.duplicateName("Densifier (2)"),
    // Skips both taken numbers — and the third is taken in a DIFFERENT spelling, which only
    // counts because the comparison goes through nameKey. The server strips punctuation the same
    // way, so a counter matching exact strings would hand back a name the save then refuses.
    skipsTaken: crowded.duplicateName("Densifier"),
    blank: plain.duplicateName(""),
  };
}

// ── E. a line nobody has filled in is not a broken line ─────────────────────
// "Item removed" is what a line says when its material was DELETED. A line added ten seconds ago
// says the same thing today, in the same amber, on a row flagged broken — which is a fault report
// about the estimator not having finished typing yet.
{
  const blank = build({
    ASMS: [{ id: "b1", name: "Test", unit: "SF", updated_at: "T1",
             lines: [{ role: "", item_id: "", coverage: null, waste_pct: 5, roundup: true }] }],
    openId: "b1",
  });
  blank.api.renderPanel();
  blank.api.refreshNumbers();
  const row = blank.dom.nodes["lines-body"].rows[0];
  out.blankLine = {
    qtyCell: row.cells[5].innerHTML,
    saysPick: /Pick a material/.test(row.cells[5].innerHTML),
    saysRemoved: /Item removed/.test(row.cells[5].innerHTML),
    flaggedBroken: row.classList.has("broken"),
  };
  // …while a line pointing at a material that really is gone still says so, and still is.
  const gone = build({
    ASMS: [{ id: "b2", name: "Test", unit: "SF", updated_at: "T1",
             lines: [{ role: "", item_id: "deleted-one", coverage: 275, waste_pct: 5, roundup: true }] }],
    openId: "b2",
  });
  gone.api.renderPanel();
  gone.api.refreshNumbers();
  const grow = gone.dom.nodes["lines-body"].rows[0];
  out.removedLine = {
    saysRemoved: /Item removed/.test(grow.cells[5].innerHTML),
    flaggedBroken: grow.classList.has("broken"),
  };
}

// ── the picker resolves typed text to a material ─────────────────────────────
{
  const { api } = build();
  out.picker = {
    exact: (api.itemByName("OPF Primer") || {}).id,
    caseInsensitive: (api.itemByName("opf primer") || {}).id,
    trimmed: (api.itemByName("  OPF  ") || {}).id,
    // Never a "closest" guess: silently picking the wrong primer is worse than saying no.
    partialRefused: api.itemByName("OPF Pri"),
    unknownRefused: api.itemByName("Nonsense"),
    blank: api.itemByName(""),
  };
}

// ── the numeric coercion list ────────────────────────────────────────────────
out.numericFields = build().api.NUMERIC_ITEM_FIELDS;

// ── EXECUTED: where the create controls live ────────────────────────────────
// Hanz, 2026-08-27: "I dont like the New assembly button up top." It sat in a .tabaction wrapper
// at the right-hand end of the tab strip, beside Administration and about 1300px from the rail it
// appends a row to. The rule now is one rule in four places: a create control sits at the foot of
// the list it adds to, inside the same container.
//
// Read off the real markup and driven through the real renderList, because "it moved" is a
// structural fact a source grep for the id would answer identically before and after.
{
  const between = (open, close, from) => {
    const i = html.indexOf(open, from || 0);
    if (i === -1) return "";
    const j = html.indexOf(close, i);
    return html.slice(i, j === -1 ? html.length : j);
  };
  const tabStrip = between('<div class="views"', "</div>");
  const rail = between('id="asm-rail"', "</section>");

  out.createAction = {
    // GONE FROM THE HEADER. The id itself is retired, so a later edit cannot quietly put it back
    // by re-using the wrapper.
    // Every button left in the strip is a tab. A create control here is exactly what was
    // removed, so anything that is not role="tab" fails this.
    // The class and its rule, not the word: the comment left where the button used to sit names
    // the old wrapper on purpose, so the next reader knows what moved and why.
    goneFromTheTabStrip: !/asm-new-top/.test(html) && !/class="tabaction"/.test(html) &&
      !/\.tabaction\s*\{/.test(html) &&
      (tabStrip.match(/<button/g) || []).length ===
      (tabStrip.match(/role="tab"/g) || []).length,
    // AT THE FOOT OF THE RAIL, and after the list rather than before it: the control has to read
    // as the next row, not as a header above the ones that exist.
    inTheRail: /id="asm-new-2"/.test(rail) &&
      rail.indexOf('id="asm-list"') < rail.indexOf('id="asm-new-2"'),
    // The same shape in all four places, so the page has ONE way of saying "add another".
    addRowCount: (html.match(/class="addrow"/g) || []).length,
    addBtnCount: (html.match(/class="addbtn"/g) || []).length,
    // Materials and each of the three administration lists put theirs inside the table's own card.
    materialsAddRowInTheCard: /id="items-addrow"/.test(html) &&
      html.indexOf('<tbody id="items-body">') < html.indexOf('id="items-addrow"'),
    adminAddRows: ["divisions", "units", "vendors"].every((k) =>
      new RegExp('class="addrow" data-addrow-ref="' + k + '"').test(html)),
    // renderRefSection hides those three for a non-admin by that same attribute, so moving the
    // wrapper must not have dropped the hook the permission check hangs on.
    adminAddRowsStillHideable: ["divisions", "units", "vendors"].every((k) =>
      new RegExp('data-addrow-ref="' + k + '"').test(html)),
    // The old below-the-grid wrapper is gone rather than left hidden.
    oldNewRowWrapperGone: !/asm-newrow/.test(html),
  };

  // THE RAIL IS WHAT HIDES, not the list inside it. Hiding only #asm-list would leave the create
  // button alone in an empty card while the "No assemblies yet" panel offered a second one.
  const some = build();
  some.api.renderList();
  const none = build({ ASMS: [] });
  none.api.renderList();
  out.createAction.railShownWithAssemblies = some.dom.nodes["asm-rail"].hidden === false;
  out.createAction.railHiddenWithNone = none.dom.nodes["asm-rail"].hidden === true;
  out.createAction.countStillPainted = some.dom.nodes["n-asm"].textContent;

  // AND THE MATERIALS ADD ROW follows its table. Under "No materials yet" it would be the second
  // Add button in one card; under "Nothing matches that" it would answer a typo with an
  // invitation to create the duplicate the search just failed to find.
  const rows = build();
  rows.api.renderItems();
  const bare = build({ ITEMS: [] });
  bare.api.renderItems();
  const nohits = build({ itemQuery: "nothing like this" });
  nohits.api.renderItems();
  out.createAction.itemsAddRowWithRows = rows.dom.nodes["items-addrow"].hidden === false;
  out.createAction.itemsAddRowWhenEmpty = bare.dom.nodes["items-addrow"].hidden === true;
  out.createAction.itemsAddRowOnNoMatch = nohits.dom.nodes["items-addrow"].hidden === true;
}

// ── EXECUTED: the glyphs are drawn, not typed ───────────────────────────────
// House rule, and not a matter of taste: an emoji is rendered by whatever font the machine has, so
// the delete control is a different picture on Kyle's Windows box than on a phone, it cannot take
// the row's colour on hover, and it ignores every size and stroke token on the page. This page
// shipped with 🗑 in three renderers and ⧉ in a fourth.
//
// The SECOND half is the part a grep would miss. An <svg> inside a <button> becomes the click
// target, and every one of these handlers reads its data- attribute off the element that was
// pressed — so the button goes dead over most of its own area unless something stops that.
{
  const b = build({ ADMIN: true });
  b.api.renderItems();
  b.api.renderVendors();
  b.api.renderPanel();
  const itemRow = b.dom.nodes["items-body"].innerHTML.split("</tr>")[0];
  const refRow = b.dom.nodes["divisions-body"].innerHTML.split("</tr>")[0];
  const lineRow = b.dom.nodes["lines-body"].innerHTML.split("</tr>")[0];
  const everywhere = itemRow + refRow + lineRow + html;
  const glyphs = (itemRow + refRow + lineRow).match(/<svg[^>]*class="ic"[^>]*>/g) || [];

  const rule = (sel) => (new RegExp(sel.replace(/[.>*+?^${}()|[\]\\]/g, "\\$&") +
    "\\s*\\{[^}]*\\}").exec(html) || [""])[0];

  out.icons = {
    // No emoji left anywhere the estimator looks: the three renderers, and the page's own markup.
    // Ranges are the pictographs and the dingbats; the tick inside a division chip is CSS content
    // keyed off :checked and is a typographic mark, not a picture, so it is excluded by range.
    noEmojiInRenderedRows: !/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]/u
      .test(itemRow + refRow + lineRow),
    // The two specific characters this page used.
    oldGlyphsGone: !/🗑/.test(everywhere) && !/⧉/.test(everywhere),
    // Every control that had one now has a real vector in its place.
    glyphCount: glyphs.length,
    // Lucide's geometry, so these sit beside the sidebar's and the drawer's without arguing.
    allAreLucideShaped: glyphs.length > 0 && glyphs.every((g) =>
      /viewBox="0 0 24 24"/.test(g) && /fill="none"/.test(g) &&
      /stroke="currentColor"/.test(g) && /stroke-width="2"/.test(g) &&
      /stroke-linecap="round"/.test(g)),
    // Decorative: the button already carries the accessible name, so the glyph must not add a
    // second one for a screen reader to read out after it.
    allHiddenFromTheTree: glyphs.length > 0 && glyphs.every((g) => /aria-hidden="true"/.test(g)),
    // The buttons kept their names and their save contract.
    deleteStillNamed: /aria-label="Remove OPF"/.test(itemRow),
    duplicateStillNamed: /aria-label="Duplicate OPF"/.test(itemRow),
    contractUnchanged: /data-dupe-item="i1"/.test(itemRow) && /data-del-item="i1"/.test(itemRow) &&
      /data-del-ref="divisions"/.test(refRow) && /data-del-line="0"/.test(lineRow),
    // THE PRESS STILL LANDS ON THE BUTTON. Two independent answers, because either alone is one
    // tidy-up away from a control that looks fine and does nothing.
    glyphIsNotAClickTarget: /pointer-events:none/.test(rule(".icon svg, .addbtn svg")),
    handlersResolveByClosest: ["data-dupe-item", "data-del-item", "data-del-ref", "data-del-line"]
      .every((a) => src.indexOf('t.closest("[' + a + ']")') !== -1),
  };
}

// ── the page wears the app's own warm palette ───────────────────────────────
// Settled 2026-08-25 after three rejected attempts, and this page was the one screen still
// disagreeing: --surf:#f4f4f5 and --red:#c8102e are a cool grey and a brighter red than the brand
// uses anywhere else, so beside any other Treadwell screen it read as somebody else's product.
{
  const root = (/:root \{ color-scheme: only light;[\s\S]*?\n\s*--r-lg[^}]*\}/.exec(html) ||
                /:root \{ color-scheme: only light;[^}]*\}/.exec(html) || [""])[0];
  const val = (name) => ((new RegExp("--" + name + ":\\s*([^;]+);").exec(root)) || ["", ""])[1].trim();
  out.palette = {
    red: val("red"), redDark: val("red-dark"), redTint: val("red-tint"),
    surf: val("surf"), surfLow: val("surf-low"), ink: val("ink"), inkV: val("ink-v"),
    // ONE type stack. Headings, buttons and totals were set in system-ui while the prose beside
    // them was Inter, so a number and the sentence explaining it were different faces.
    uiStack: val("ui"),
    systemUiLeftInAFontShorthand: /font:[^;]*system-ui/.test(html.replace(/--ui:[^;]+;/, "")),
    // ONE radius scale. There were five, assigned by whichever value the last person typed.
    radiiDeclared: ["r-lg", "r-md", "r-sm"].map(val),
    hardcodedRadii: (html.match(/border-radius:\s*\d+px/g) || [])
      .filter((r) => !/999px/.test(r)),
  };

  // THE CLIPPING TRAP, guarded. The card clips so a full-bleed table head and the add row keep
  // the rounded corners — and any overflow other than `visible` is a clipping context, so the
  // panel holding the item picker has to opt back out or the results list is cut off at the card
  // edge. That bug shipped once already; .tw-nolimit exists because of it.
  const rule2 = (sel) => (new RegExp(sel.replace(/[.>*+?^${}()|[\]\\]/g, "\\$&") +
    "\\s*\\{[^}]*\\}").exec(html) || [""])[0];
  const cardRule = rule2(".card");
  out.palette.cardClips = /overflow:hidden/.test(cardRule);
  out.palette.panelOptsOutOfClipping = /overflow:visible/.test(rule2(".card.apanel"));
  // …and the picker still lives inside that panel, so the opt-out is protecting the right box.
  out.palette.pickerIsInsideThePanel =
    html.indexOf('id="asm-panel"') < html.indexOf('class="tw-nolimit"');
}

// ── the inline style attributes the renderers used to emit ──────────────────
// The house rule is classes, not style attributes, and this page was the worst offender: eight on
// the assembly header row alone, plus a width on every field the three renderers produced.
{
  const b = build({ ADMIN: true });
  b.api.renderItems();
  b.api.renderVendors();
  b.api.renderPanel();
  const rendered = b.dom.nodes["items-body"].innerHTML + b.dom.nodes["divisions-body"].innerHTML +
    b.dom.nodes["units-body"].innerHTML + b.dom.nodes["vendors-body"].innerHTML +
    b.dom.nodes["lines-body"].innerHTML;
  out.inlineStyles = {
    inRenderedMarkup: (rendered.match(/style="[^"]*"/g) || []),
    inThePage: (html.match(/style="[^"]*"/g) || []),
    // The fields still have their widths, they are just wearing them as classes now.
    nameFieldStillSized: /class="cell-name"/.test(rendered),
    costFieldStillSized: /cell-cost/.test(rendered),
  };
}

// ── the page's own copy ──────────────────────────────────────────────────────
out.page = {
  title: /<title>([^<]*)</.exec(html)[1],
  h1: /<h1>([^<]*)</.exec(html)[1],
  materialHeaderNamesTheManufacturer:
    /Materials <span[^>]*>\(how the manufacturer names it\)<\/span>/.test(html),
  itemsIntro: /Items are entered as we buy them/.test(html),
  assembliesIntro: /Assemblies are how we estimate them/.test(html),
  coveragePerUnitHeader: /Coverage per Unit/.test(html),
  wasteHeader: /Waste Factor/.test(html),
  roundupHeader: /Roundup\?/.test(html),
  vendorsTab: /id="tab-vendors"/.test(html),
  noCoverageSfHeader: !/Coverage \(SF\)/.test(html),
  noRoleHeader: !/<th[^>]*>Role<\/th>/.test(html),
};

conflictChecks().then(
  () => console.log(JSON.stringify(out)),
  (err) => { console.error(err); process.exit(1); });
