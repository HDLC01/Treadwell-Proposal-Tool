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
  // Lifted because renderPanel calls it. A lifted function that reaches for a helper this scope
  // does not have dies with a ReferenceError, which takes every test in test_library_ui.py red at
  // once with no hint of the real cause — so a new helper and its lift belong in one commit.
  ${fn("asmUnit")}
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
  // The facets. The DECLARATION is lifted out of library.js rather than restated, so a fourth
  // facet added there without a default here cannot pass as an empty object.
  ${grab(/^  var FILTERS = \{[^}]*\};$/m, "the FILTERS declaration")}
  if (state.FILTERS) FILTERS = Object.assign(FILTERS, state.FILTERS);
  var filterBarSig = "";
  // EVERY ONE OF THESE IS CALLED BY SOMETHING ALREADY LIFTED. renderItems asks anyFilterActive
  // and filterSummary; visibleItems asks matchesFilters; itemMatches asks parseQuery and
  // termHits. Miss one and the whole file dies on a ReferenceError rather than failing a test.
  ${fn("anyFilterActive")}
  ${fn("parseQuery")}
  ${fn("termHits")}
  ${fn("numberHits")}
  ${fn("conditionHits")}
  ${fn("conditionPhrase")}
  ${fn("matchesFilters")}
  ${fn("filterSummary")}
  ${fn("renderFilterBar")}
  ${fn("visibleItems")}
  ${fn("nameKey")}
  ${fn("duplicateName")}
  // The name a BRAND NEW row is created under. Separate from duplicateName because the first
  // candidate differs: a copy of "Densifier" must never be called "Densifier", and a new material
  // wants the bare "New material" whenever it is free.
  ${fn("nameTaken")}
  ${fn("newMaterialName")}
  ${fn("newRefName")}
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
  // LIFTED, not restated: onItemEdit's first line reads the first of these and its snapshot line
  // writes the second, so a rename in library.js has to break this file rather than quietly
  // leave the guard untested.
  ${grab(/^  var itemConfirmOpen = null;$/m, "the itemConfirmOpen declaration")}
  ${grab(/^  var itemLastField = \{\};$/m, "the itemLastField declaration")}
  ${fn("snapshotItem")}
  ${fn("rememberItem")}
  ${fn("onItemEdit")}
  // Test glue, and the only piece in this file: load() replaces DIVISIONS with the Administration
  // tab list, and a test of "an added division reaches the filter chips" has to be able to do the
  // same thing to a scope that is ALREADY built, or renderFilterBar has nothing to notice.
  return { setDivisions: function (list) { DIVISIONS = list; }, renderFilterBar, parseQuery, matchesFilters, anyFilterActive, filterSummary,
           numberHits, FILTERS,
           renderItems, renderVendors, renderPanel, renderList, refreshNumbers,
           pickerFor, itemByName, similarNames, pick, datesHtml, adoptSaved,
           onItemEdit, QUEUED, NUMERIC_ITEM_FIELDS, ITEMS, VENDORS,
           itemMatches, itemResultsHtml, lineForSave, visibleItems, duplicateName, nameKey,
           newMaterialName, newRefName,
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

  // THE ASSEMBLY'S UNIT REACHES ALL THREE LABELS, and the arithmetic is untouched by it.
  //
  // The field was persisted and read by the Polish beta long before it had an editor, so every
  // assembly said SF and the rail's "$1.497/SF" was a guess that happened to be right. These two
  // scenarios are the same fixture and the same numbers with only `unit` changed — so a divergence
  // in `total`/`perUnit` between them would mean the relabel had started changing prices.
  {
    const lf = build({ ASMS: [{ id: "a1", name: "Cove Base", unit: "LF", lines: [
      { item_id: "i1", coverage: 275, waste_pct: 5, roundup: true }] }] });
    lf.api.renderPanel();
    const sf = build({ ASMS: [{ id: "a1", name: "Floor", unit: "SF", lines: [
      { item_id: "i1", coverage: 275, waste_pct: 5, roundup: true }] }] });
    sf.api.renderPanel();
    const bare = build({ ASMS: [{ id: "a1", name: "Legacy", unit: "sqft", lines: [
      { item_id: "i1", coverage: 275, waste_pct: 5, roundup: true }] }] });
    bare.api.renderPanel();
    out.assemblyUnit = {
      lfPerUnitLabel: lf.dom.nodes["t-unit-k"].textContent,
      lfAreaLabel: lf.dom.nodes["area-k"].textContent,
      lfAreaSuffix: lf.dom.nodes["area-u"].textContent,
      lfSelectSynced: lf.dom.nodes["asm-unit"].value,
      sfPerUnitLabel: sf.dom.nodes["t-unit-k"].textContent,
      sfAreaLabel: sf.dom.nodes["area-k"].textContent,
      sfAreaSuffix: sf.dom.nodes["area-u"].textContent,
      // An off-list legacy value reads as SF rather than being echoed into the label, so the words
      // still describe the arithmetic that actually ran.
      legacyReadsAsSf: bare.dom.nodes["area-u"].textContent,
      legacySelectSynced: bare.dom.nodes["asm-unit"].value,
      // Identical money on both, which is the point: this is a label, not a calculation.
      lfTotal: lf.dom.nodes["t-total"].textContent,
      sfTotal: sf.dom.nodes["t-total"].textContent,
      lfPerUnit: lf.dom.nodes["t-unit"].textContent,
      sfPerUnit: sf.dom.nodes["t-unit"].textContent,
    };
  }

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
  const saveScope = new Function("api", "clock", "hooks", "state", "TW", "L", "document", `
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
    ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
    // The item-change confirmation, REAL, because this is the scope that has the real patchSoon —
    // and the dialog fires from inside the flush, after the payload has been coalesced.
    // TW is a parameter so a test can answer Yes or No and read back what it was asked.
    var itemBefore = {};
    // WHICH ROW'S DIALOG IS ON SCREEN, and where the caret was when it opened. Both are lifted
    // rather than restated: the guard at the top of onItemEdit reads the first, and the whole
    // bypass this file now probes for is a re-entry that happens while it is set.
    ${grab(/^  var itemConfirmOpen = null;$/m, "the itemConfirmOpen declaration")}
    ${grab(/^  var itemLastField = \{\};$/m, "the itemLastField declaration")}
    ${grab(/^  var SERVER_OWNED_ITEM_FIELDS = \[[^\]]*\];$/m, "SERVER_OWNED_ITEM_FIELDS")}
    ${grab(/^  var NUMERIC_ITEM_FIELDS = \[[^\]]*\];$/m, "NUMERIC_ITEM_FIELDS")}
    ${grab(/^  var ITEM_FIELD_LABELS = \{[\s\S]*?\n  \};$/m, "ITEM_FIELD_LABELS")}
    ${fn("itemOf")}
    ${fn("snapshotItem")}
    ${fn("rememberItem")}
    ${fn("shownValue")}
    ${fn("rowHasFocus")}
    ${fn("refocusItemField")}
    // CALLED BY BOTH confirmItemPatch AND forgetItem, so leaving it out is a ReferenceError that
    // kills every scenario in this file at once rather than failing one assertion.
    ${fn("endItemRound")}
    ${fn("confirmItemPatch")}
    ${fn("byId")}
    ${fn("adoptSaved")}
    ${fn("adoptConflict")}
    ${fn("arm")}
    ${fn("flush")}
    ${fn("forgetItem")}
    ${fn("flushItemRow")}
    ${fn("onItemRowFocusOut")}
    ${fn("patchSoon")}
    // THE REAL onItemEdit, in THIS scope, on top of the REAL patchSoon. The first scope in this
    // file runs it against a stubbed patchSoon, which is what made the bypass invisible: the
    // re-entrant keystroke the dialog's own focus move produces has to reach the real queue and
    // the real timer for the probe below to mean anything. similarNames/dupeHtml come with it
    // because the name branch calls them.
    ${fn("similarNames")}
    ${fn("dupeHtml")}
    ${fn("onItemEdit")}
    return { patchSoon: patchSoon, adoptConflict: adoptConflict,
             rememberItem: rememberItem, onItemEdit: onItemEdit,
             onItemRowFocusOut: onItemRowFocusOut, flushItemRow: flushItemRow,
             forgetItem: forgetItem,
             confirmOpen: function () { return itemConfirmOpen; },
             snapshotOf: function (id) { return itemBefore[id]; },
             armed: function () { return Object.keys(timers).length; },
             pending: function () { return Object.keys(pendingPatch).length; },
             // Empties the buffer WITHOUT disarming, which is the state the empty-payload guard
             // exists for. adoptConflict no longer produces it — that is the point of the fix —
             // so the guard is defence for the next code path that empties this buffer, and a
             // test of it has to construct the state deliberately rather than pretend otherwise.
             dropBuffer: function () { pendingPatch = {}; } };
  `);

  /** Just enough DOM for the row-leave rules: one item row per id, one focusable control per
   *  field, and an activeElement a test can move.
   *
   *  Purpose-built rather than a DOM emulator, and it THROWS on a selector it does not model —
   *  the two questions the page asks it ("does this row hold the focus", "where do I put the
   *  caret back") are asked through selectors renderItems' own output has to carry, so a renamed
   *  attribute must break this file loudly rather than quietly answer null. */
  function makeRowDom(itemIds, fields) {
    const rows = {};
    const doc = {
      activeElement: null,
      rows,
      querySelector(sel) {
        let m = /^\[data-item="([^"]+)"\]$/.exec(sel);
        if (m) return rows[m[1]] || null;
        m = /^\[data-item="([^"]+)"\] \[data-f="([^"]+)"\]$/.exec(sel);
        if (m) return (rows[m[1]] || { cells: {} }).cells[m[2]] || null;
        throw new Error("the page asked document for " + sel + ", which this stub does not model "
          + "— the row/field selector moved and rowHasFocus cannot find anything either");
      },
    };
    itemIds.forEach((id) => {
      const cells = {};
      const row = {
        id, cells,
        getAttribute: (k) => (k === "data-item" ? id : null),
        contains: (el) => !!el && Object.keys(cells).some((f) => cells[f] === el),
      };
      fields.forEach((f) => {
        cells[f] = {
          field: f, value: "", focused: 0,
          getAttribute: (k) => (k === "data-f" ? f : null),
          closest: (sel) => (sel === "[data-item]" ? row : null),
          // A cell has no parentNode/querySelector: the name branch of onItemEdit is not exercised
          // here, and a stub that silently answered it would hide that.
          focus() { doc.activeElement = this; this.focused++; },
        };
      });
      rows[id] = row;
    });
    return doc;
  }

  function run409(fix, answer) {
    const hooks = { saving: [], said: [], renders: [], requests: [], bodies: [], errors: [],
                    asked: [], dialogs: [], onDialogOpen: null, autoReply: null };
    // THE DIALOG IS A DEFERRED, NOT A RESOLVED PROMISE, and that is the whole point of this
    // rework. The old stub was `async (opts) => answer !== false`, which settles on the next
    // microtask — so no test could ever run code in the window while the dialog is OPEN, which is
    // exactly the window the focus-steal bypass lived in. `onDialogOpen` fires SYNCHRONOUSLY at
    // the moment the real helper appends its overlay and moves the focus, which is the moment the
    // page used to re-enter onItemEdit.
    //
    // `answer`: undefined/true = Yes, false = Cancel, "throw" = the dialog itself blew up,
    // "manual" = the test resolves it by hand off hooks.dialogs.
    // Whether SOME OTHER dialog is on screen — the delete confirmation a row's own Remove button
    // opens. Answerable from a test, because the hazard is that dialog's focus move firing the
    // focusout this page saves on.
    let othersOpen = 0;
    const TW = {
      modalOpen: () => othersOpen > 0,
      openAnotherDialog: () => { othersOpen += 1; },
      closeAnotherDialog: () => { othersOpen -= 1; },
      confirmDanger: (opts) => {
        hooks.asked.push(opts);
        return new Promise((resolve, reject) => {
          const d = { opts, resolve, reject };
          hooks.dialogs.push(d);
          if (hooks.onDialogOpen) hooks.onDialogOpen(d);
          if (answer === "throw") Promise.resolve().then(() => reject(new Error("dialog blew up")));
          else if (answer !== "manual") Promise.resolve().then(() => resolve(answer !== false));
        });
      },
    };
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
      // A SCENARIO THAT DOES NOT CARE ABOUT THE RACE answers immediately. Held requests are the
      // point of the 409 scenarios and a deadlock in every other one: a mutation that opens one
      // more dialog than expected leaves a flush awaiting a reply the test was never going to
      // release, node's event loop empties, and the harness exits 0 having printed nothing — which
      // reads as "the harness itself failed" instead of naming the assertion that broke.
      if (hooks.autoReply) {
        hooks.bodies.push(String((opts || {}).body || ""));
        return Promise.resolve(hooks.autoReply);
      }
      // EVERY BODY, kept separately from the request line so the bypass probe can assert on what
      // was actually SENT rather than on how many times we sent something. "Cancel stopped the
      // dialog" and "the rejected number never left the browser" are different claims.
      hooks.bodies.push(String((opts || {}).body || ""));
      return inflight;
    };
    const state = { ASMS: [{ id: "a1", name: "MACRO", unit: "SF", lines: [], updated_at: "T1" }],
                    ITEMS: [{ id: "i1", name: "Densifier", unit: "Gallon", unit_cost: 42,
                              buy_qty: 5, vendor: "Sika", divisions: ["Polished Concrete"],
                              updated_at: "T1", cost_updated_at: "STAMP-1" },
                            { id: "i2", name: "Hardener", unit: "Gallon", unit_cost: 10,
                              buy_qty: 1, vendor: "Sika", divisions: [],
                              updated_at: "T1", cost_updated_at: "STAMP-1" }],
                    VENDORS: [] };
    const doc = makeRowDom(["i1", "i2"], ["name", "unit_cost", "vendor", "buy_qty", "unit"]);
    const s = saveScope(api, clock, hooks, state, TW, L, doc);
    return { hooks, clock, s, state, release, doc, TW, fire: async () => {
      const now = due; due = [];
      for (const t of now) {
        if (!t.live) continue;
        try {
          // BOUNDED. The timer callback hands its promise back, and a flush can legitimately sit
          // on a request this scenario has not released — but it can also sit on a DIALOG nobody
          // is going to answer, which is what a change that asks one more time than expected
          // produces. Unbounded, that stops the whole harness and it prints nothing; bounded, it
          // becomes a line in hooks.errors that the scenario's own `errors == []` catches.
          let stuck = false;
          await Promise.race([
            Promise.resolve(t.fn()),
            new Promise((r) => global.setTimeout(() => { stuck = true; r(); }, 250)),
          ]);
          if (stuck) hooks.errors.push("a flush never settled — an unanswered dialog or a reply "
            + "this scenario never released");
        } catch (e) { hooks.errors.push(String(e)); }
      }
    }, cancelledCount: () => due.filter((t) => !t.live).length,
      // The methods the page's own paths are driven through, so no scenario below hand-rolls an
      // event shape the real handlers do not receive.
      type: (id, field, value) => {
        const cell = doc.rows[id].cells[field];
        cell.value = value;
        doc.activeElement = cell;
        s.onItemEdit({ target: cell });
      },
      // …and the browser's own blur→change, which is what a .focus() elsewhere provokes: the
      // input reports `change` with the value it still holds.
      synthChange: (id, field) => s.onItemEdit({ target: doc.rows[id].cells[field] }),
      // Returns the flush's promise so a scenario can await it. The rejection has to be reachable:
      // a dialog that throws rejects this chain, and an unawaited rejection kills node with an
      // unhandled-rejection exit instead of failing the assertion that cares.
      leaveRow: (id, field, to) => {
        doc.activeElement = to || null;
        return Promise.resolve(
          s.onItemRowFocusOut({ target: doc.rows[id].cells[field], relatedTarget: to || null })
        ).catch((e) => { hooks.errors.push(String(e)); });
      },
      // Every value that reached the wire, flattened, so "58 was never sent" is one assertion
      // rather than a walk over request bodies.
      sentValues: () => hooks.bodies.map((b) => {
        try { return JSON.parse(b); } catch (e) { return b; }
      }) };
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

  // ══ THE BYPASS PROBE ═══════════════════════════════════════════════════════
  // The defect this whole block exists for, EXECUTED rather than reasoned about.
  //
  // The dialog's own focus move blurs the input the estimator was typing in. A blurred input with
  // an uncommitted value fires `change`, `change` is bound to #items-body, so the page re-entered
  // onItemEdit WHILE ITS OWN DIALOG WAS OPEN — took a fresh snapshot of the already-edited model,
  // queued a second patch, and 600ms later found before == after and sent the rejected number
  // with no dialog at all. Cancel put 42 back on screen; 58 was in the database.
  //
  // Everything below is driven through the REAL onItemEdit on the REAL patchSoon, and the
  // re-entrant keystroke is fired from inside the dialog-open hook — which is the only ordering
  // that can catch this and the reason the old resolved-promise stub could not.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    const it = c.state.ITEMS[0];
    const reentries = [];
    c.hooks.onDialogOpen = (d) => {
      // What .focus() on anything else provokes: the cost input reports `change`, still holding
      // "58", and it bubbles to the tbody listener.
      c.synthChange("i1", "unit_cost");
      reentries.push({ armed: c.s.armed(), pending: c.s.pending(),
                       // The SNAPSHOT still has to hold 42. Before the fix the re-entry found it
                       // already deleted, took a fresh one off the edited model, and every later
                       // comparison then agreed that 58 was where the row had started.
                       snapshotCost: (c.s.snapshotOf("i1") || {}).unit_cost,
                       open: c.s.confirmOpen() });
      d.resolve(false);
    };
    c.type("i1", "unit_cost", "58");            // 42 → 58, model updated live as the page does
    const modelMidEdit = it.unit_cost;
    c.leaveRow("i1", "unit_cost", null);        // focus leaves the row → flush + ask
    await settle(); await settle();
    // Anything the re-entry managed to arm gets its turn, twice, so a deferred timer cannot hide.
    await c.fire(); await settle();
    await c.fire(); await settle();
    out.itemBypass = {
      modelMidEdit,
      asked: c.hooks.asked.length,
      // THE ONE THAT MATTERS: no request body ever carried the rejected number.
      sent: c.sentValues(),
      requests: c.hooks.requests,
      costAfter: it.unit_cost,
      // The re-entrant event must be DISCARDED, not merged: no fresh snapshot, nothing queued,
      // no timer re-armed behind the dialog.
      reentries,
      confirmOpenAfter: c.s.confirmOpen(),
      pendingAfter: c.s.pending(),
      errors: c.hooks.errors,
    };
  }

  // A SECOND ROW'S FLUSH WAITS FOR THE OPEN DIALOG rather than stacking a second one on top of it.
  // Two of these modals at once is one trapping the focus the other one needs, over a question
  // that names neither row clearly.
  //
  // DRIVEN THROUGH patchSoon, NOT THROUGH A KEYSTROKE, and that is not a shortcut: with the guard
  // in place, typing into a second row while a dialog is open is unreachable — the overlay traps
  // the input on the page and onItemEdit discards anything that gets past it. The reachable state
  // is an ARMED TIMER left over from a previous round, which is exactly what a deferred flush
  // leaves behind, so that is what this constructs.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "x" } }) };
    // Every dialog after the first answers itself, so the queue really drains.
    c.hooks.onDialogOpen = (d) => { if (c.hooks.dialogs.length > 1) d.resolve(true); };
    const first = c.state.ITEMS[0], second = c.state.ITEMS[1];
    c.s.rememberItem(second);
    second.unit_cost = 77;
    c.s.patchSoon("items", "i2", { unit_cost: "77" });
    // …and now row one is left, which opens row one's dialog.
    c.type("i1", "unit_cost", "58");
    c.leaveRow("i1", "unit_cost", null);
    await settle();
    const whileOpen = { asked: c.hooks.asked.length, forRow: (c.hooks.asked[0] || {}).name };
    // Row two's timer comes due WITH that dialog still on screen.
    await c.fire(); await settle();
    const secondAsked = c.hooks.asked.length;
    const secondDeferred = c.s.pending();
    const secondRearmed = c.s.armed();
    // Row one is answered; row two's re-armed timer then gets its turn.
    c.hooks.dialogs[0].resolve(true);
    await settle(); await settle();
    await c.fire(); await settle(); await settle();
    out.itemDialogQueue = {
      whileOpen,
      // Still ONE dialog while the first was open…
      askedWhileOpen: secondAsked,
      secondStillQueued: secondDeferred >= 1,
      secondRearmed: secondRearmed >= 1,
      // …and the second row's question does get asked once the first is answered.
      askedInTheEnd: c.hooks.asked.length,
      secondAskedAbout: (c.hooks.asked[1] || {}).name,
      firstCost: first.unit_cost,
      secondCost: second.unit_cost,
      errors: c.hooks.errors,
    };
  }

  // A THROWN DIALOG IS A CANCEL, NOT A DROPPED WRITE. Without the try/catch the rejection escapes
  // the flush: the payload has already been taken out of pendingPatch, the snapshot has been
  // consumed, itemConfirmOpen is left set — so onItemEdit's guard silently swallows every
  // subsequent keystroke on the page and nothing is ever saved again, with no error on screen.
  {
    const c = run409(undefined, "throw");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    const it = c.state.ITEMS[0];
    c.type("i1", "unit_cost", "58");
    // AWAITED, so a rejection that escapes confirmItemPatch lands in hooks.errors instead of
    // killing node with an unhandled rejection and taking every other scenario with it.
    await c.leaveRow("i1", "unit_cost", null);
    await settle(); await settle();
    await c.fire(); await settle();
    out.itemDialogThrew = {
      asked: c.hooks.asked.length,
      requests: c.hooks.requests,
      sent: c.sentValues(),
      costAfter: it.unit_cost,
      // The page is still usable: the flag is down and a later edit is still asked about.
      confirmOpenAfter: c.s.confirmOpen(),
      // The rejection was HANDLED, not left to become an unhandled rejection.
      errors: c.hooks.errors,
    };
  }

  // CANCEL DOES NOT RESTORE THE SERVER'S OWN STAMPS. `updated_at` and `cost_updated_at` are the
  // server's to decide — adoptSaved takes them off a successful write — so putting the snapshot's
  // copy back discards what the server just told us and the Dates cell goes on quoting a price
  // date the database has already moved past.
  {
    const c = run409(undefined, "manual");
    const it = c.state.ITEMS[0];
    c.type("i1", "unit_cost", "58");
    // The server's answer to an EARLIER write lands while the snapshot is held, exactly as it
    // does on the page: adoptSaved is what moves these two, and it can land at any point during
    // the round the snapshot spans.
    it.updated_at = "T9";
    it.cost_updated_at = "STAMP-9";
    const stampsBefore = { updated_at: it.updated_at, cost_updated_at: it.cost_updated_at };
    c.hooks.onDialogOpen = (d) => d.resolve(false);
    c.leaveRow("i1", "unit_cost", null);
    await settle(); await settle();
    out.itemCancelStamps = {
      asked: c.hooks.asked.length,
      costAfter: it.unit_cost,
      stampsBefore,
      stampsAfter: { updated_at: it.updated_at, cost_updated_at: it.cost_updated_at },
      errors: c.hooks.errors,
      // AND THE CARET GOES BACK to the field the refused edit was typed into. The row was rebuilt
      // by the repaint above, so this is the NEW input being focused, not the one they left.
      refocused: c.doc.rows.i1.cells.unit_cost.focused,
      focusedElsewhere: Object.keys(c.doc.rows.i1.cells)
        .filter((f) => f !== "unit_cost" && c.doc.rows.i1.cells[f].focused > 0),
    };
  }

  // ROW-LEAVE TIMING. Hanz, 2026-08-27: the dialog fires when focus leaves the row, not on a
  // typing pause. While the row is being worked in, the flush re-defers; the moment focus lands
  // outside it, the row's edits go in one question.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    c.hooks.onDialogOpen = (d) => d.resolve(true);
    c.type("i1", "unit_cost", "58");
    // The 600ms timer comes due with the focus still in the row.
    await c.fire(); await settle();
    const duringTyping = { asked: c.hooks.asked.length, requests: c.hooks.requests.length,
                           stillQueued: c.s.pending(), rearmed: c.s.armed() };
    await c.fire(); await settle();               // and again: it keeps deferring, it does not fire
    const afterASecondPause = { asked: c.hooks.asked.length, requests: c.hooks.requests.length };
    // Tabbing to another cell IN THE SAME ROW is not leaving it — edits accumulate.
    c.type("i1", "vendor", "Euclid");
    c.leaveRow("i1", "vendor", c.doc.rows.i1.cells.name);
    await settle();
    const insideTheRow = { asked: c.hooks.asked.length };
    // …and now out of the row altogether.
    c.leaveRow("i1", "name", c.doc.rows.i2.cells.unit_cost);
    await settle(); await settle(); await settle();
    out.itemRowLeave = {
      duringTyping,
      afterASecondPause,
      insideTheRow,
      askedOnLeaving: c.hooks.asked.length,
      // ONE question, listing BOTH fields — which is the interruption this design removes.
      detail: (c.hooks.asked[0] || {}).detail,
      sent: c.sentValues(),
      errors: c.hooks.errors,
    };
  }

  // A DIALOG SOMEBODY ELSE PUT UP holds the save back too. The route in is the row's own Remove
  // button: clicking it leaves the focus inside the row, so nothing flushes — and then the delete
  // confirmation focuses ITS Cancel button, which blurs that button and fires the focusout this
  // page saves on. Without asking shared.js whether a modal is up, "Remove this material?" gets
  // "Save this change?" stacked on top of it.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    c.hooks.onDialogOpen = (d) => d.resolve(true);
    c.type("i1", "unit_cost", "58");
    // Reaching for that row's Remove button: still inside the row, so nothing has flushed yet.
    c.TW.openAnotherDialog();
    // …and the delete dialog's own .focus() blurs the button, out of the row.
    await c.leaveRow("i1", "unit_cost", null);
    await settle(); await settle();
    const whileTheOtherIsOpen = { asked: c.hooks.asked.length, queued: c.s.pending(),
                                  rearmed: c.s.armed() };
    // The estimator cancels the delete; the save question is asked then, on its own.
    c.TW.closeAnotherDialog();
    await c.fire(); await settle(); await settle();
    out.itemOtherModal = {
      whileTheOtherIsOpen,
      askedAfterItClosed: c.hooks.asked.length,
      sent: c.sentValues(),
      errors: c.hooks.errors,
    };
  }

  // A DELETED ROW'S QUEUE DIES WITH IT. Far more likely now the save waits for the row to be
  // left: typing a cost and then reaching for that row's Remove button never leaves the row, so
  // the edit is still queued when the material stops existing.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    c.hooks.onDialogOpen = (d) => d.resolve(true);
    c.type("i1", "unit_cost", "58");
    const queuedBefore = c.s.pending();
    c.s.forgetItem("i1");
    const queuedAfter = c.s.pending();
    const snapshotAfter = c.s.snapshotOf("i1");
    await c.fire(); await settle(); await settle();
    out.itemForgotten = {
      queuedBefore, queuedAfter,
      snapshotDropped: snapshotAfter === undefined,
      // Nothing asked and nothing sent: there is no row left to ask about.
      asked: c.hooks.asked.length,
      requests: c.hooks.requests,
      errors: c.hooks.errors,
      // …and the delete path really calls it. The handler it lives in is a 200-line click
      // listener this harness cannot lift, so the call site is checked in the source — weaker than
      // the assertions above, and paired with them rather than standing alone.
      calledOnDelete: /await del\("items", di\);\s*\n\s*\/\/[^\n]*\n\s*forgetItem\(di\);/.test(src),
    };
  }

  // WHAT THE DIALOG IS ASKED FOR. Two opt-ins that exist only for this caller, and both are about
  // the bypass rather than about looks: focusing the dialog itself means a stray SPACE cannot
  // press Cancel, and requiring an explicit answer means clicking the next cell cannot silently
  // revert a deliberate edit.
  {
    const c = run409(undefined, "manual");
    c.hooks.autoReply = { status: 200, ok: true, json: async () => ({ item: { id: "i1" } }) };
    c.hooks.onDialogOpen = (d) => d.resolve(true);
    c.type("i1", "unit_cost", "58");
    c.leaveRow("i1", "unit_cost", null);
    await settle(); await settle();
    out.itemAskedOpts = c.hooks.asked[0] || {};
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

  // ── and the name a NEW row is created under ────────────────────────────────
  // "+ Add material" posted the literal "New material". `create_item` refuses a duplicate name
  // with a 400, so the second press of that button was dead: "Couldn't add that material. "New
  // material" is already in the library." — with nothing on screen explaining that the fix is to
  // go and rename the first one.
  const free = build({ ITEMS: [{ id: "y1", name: "OPF", unit: "Gallon", divisions: [] }] }).api;
  const taken = build({ ITEMS: [
    { id: "y1", name: "New material", unit: "Gallon", divisions: [] },
  ] }).api;
  const takenTwice = build({ ITEMS: [
    { id: "y1", name: "New material", unit: "Gallon", divisions: [] },
    { id: "y2", name: "new  material (2)", unit: "Gallon", divisions: [] },
  ] }).api;
  out.newMaterialName = {
    // Bare stem while it is free: "New material (2)" as the FIRST material would be absurd.
    whenFree: free.newMaterialName("New material"),
    whenTaken: taken.newMaterialName("New material"),
    // Taken in another spelling counts, because the server's own block strips punctuation and
    // spacing the same way — otherwise the button offers a name the save then refuses.
    whenTwoTaken: takenTwice.newMaterialName("New material"),
    blank: free.newMaterialName(""),
    // The Administration tab has the identical literal default, checked against ITS OWN list.
    refWhenFree: free.newRefName("vendors"),
    refWhenTaken: build({ VENDORS: [{ id: "v9", name: "New vendor", notes: "" }] })
      .api.newRefName("vendors"),
    refDivision: build({ DIVISION_REFS: [{ id: "d9", name: "New division", notes: "" }] })
      .api.newRefName("divisions"),
    // A material named "New vendor" must not stop the Vendors tab adding one: the two lists are
    // unique within themselves, not against each other.
    refIgnoresItems: build({
      ITEMS: [{ id: "y1", name: "New vendor", unit: "Gallon", divisions: [] }],
      VENDORS: [],
    }).api.newRefName("vendors"),
  };
}

// ── F. the shared dialog's two opt-ins, EXECUTED out of shared.js ───────────
// Nothing in this repo has ever executed confirmDanger, and that is the second half of why the
// bypass survived review: `noBtn.focus()` is one line inside a requestAnimationFrame and reads as
// an accessibility nicety rather than as the thing that fires a `change` event on whatever the
// estimator was typing in.
//
// Both opt-ins default OFF, so the other callers on this page and the twenty elsewhere in the
// frontend get byte-identical behaviour — which is asserted here rather than assumed, by running
// the SAME function with no options and reading back what it focused and what it listened for.
async function dialogChecks() {
  const sharedSrc = read(path.join(ROOT, "shared.js"));
  const m = /\n  function confirmDanger\s*\(/.exec(sharedSrc);
  if (!m) throw new Error("confirmDanger() is gone from shared.js — rewrite this harness");
  const start = sharedSrc.indexOf("{", m.index + m[0].length - 1);
  let depth = 0, end = -1;
  for (let j = start; j < sharedSrc.length; j++) {
    if (sharedSrc[j] === "{") depth++;
    else if (sharedSrc[j] === "}" && --depth === 0) { end = j + 1; break; }
  }
  const confirmSrc = sharedSrc.slice(m.index, end);

  /** The narrowest DOM the real dialog touches: createElement, one appendChild, querySelector
   *  over the markup it just wrote, and a focus() that records who got it.
   *
   *  Elements are objects rather than parsed HTML because the only questions asked here are "what
   *  did it focus" and "what did it listen for" — but `innerHTML` is really assigned and really
   *  queried, so a renamed internal class breaks the lift rather than passing. */
  function fakeDialogDom() {
    const focused = [];
    const mk = (tag) => {
      const node = {
        tag, className: "", innerHTML: "", textContent: "", children: [], attrs: {},
        listeners: {},
        setAttribute(k, v) { this.attrs[k] = v; },
        getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
        appendChild(c) { this.children.push(c); return c; },
        append(...cs) { this.children.push(...cs); },
        remove() { this.removed = true; },
        addEventListener(ev, fn2) { (this.listeners[ev] = this.listeners[ev] || []).push(fn2); },
        removeEventListener() {},
        focus() { focused.push(this); doc.activeElement = this; },
        classList: { add() {}, remove() {} },
        querySelector(sel) {
          // The dialog writes its own markup and then reads it back by class. Modelled by class
          // name so a rename in that template is a null here and a loud failure, not a pass.
          const known = {
            ".tw-dlg-ic": "ic", ".tw-dlg-h": "h", ".tw-dlg-m": "m", ".tw-dlg-d": "d",
            ".tw-dlg-no": "no", ".tw-dlg-go": "go",
          };
          if (!(sel in known)) {
            throw new Error("the dialog asked for " + sel + ", which this stub does not model");
          }
          this._parts = this._parts || {};
          if (!this._parts[sel]) {
            const part = mk("div");
            part.role = known[sel];
            this._parts[sel] = part;
          }
          return this._parts[sel];
        },
      };
      return node;
    };
    const body = mk("body");
    const doc = {
      activeElement: null,
      body,
      focused,
      docListeners: {},
      createElement: (t) => mk(t),
      createTextNode: (t) => ({ text: t }),
      addEventListener(ev, fn2) {
        (this.docListeners[ev] = this.docListeners[ev] || []).push(fn2);
      },
      removeEventListener() {},
    };
    return doc;
  }

  function sharedGrab(re, what) {
    const m = re.exec(sharedSrc);
    if (!m) throw new Error(what + " is gone from shared.js — rewrite this harness");
    return m[0];
  }

  const runDialog = new Function("document", "requestAnimationFrame", "setTimeout",
    "injectModalCss", "opts", `
    "use strict";
    // The dialog keeps a count of how many of itself are on screen, for callers that must not put
    // a second question on top of one being asked. LIFTED, not restated: it lives outside
    // confirmDanger, and without it every call in here throws a ReferenceError inside the promise
    // executor — which surfaces as a rejected promise and an empty overlay rather than as an error.
    ${sharedGrab(/^  let openModals = 0;$/m, "the openModals counter")}
    ${sharedGrab(/^  function modalOpen\(\) \{[^\n]*$/m, "modalOpen()")}
    ${confirmSrc}
    // A FACTORY, not one call, so a scenario can put two dialogs up in ONE scope and watch the
    // counter. That is the whole reason it is a count and not a boolean: with a flag, the first of
    // two overlapping dialogs closing would report the second one gone.
    return { open: confirmDanger, modalOpen: modalOpen, first: opts && confirmDanger(opts) };
  `);

  function askWith(opts) {
    const doc = fakeDialogDom();
    // The control the page's focus is really on when the dialog goes up. It records who focused
    // it, so "the dialog handed the focus back to a stale element" is a fact rather than a guess.
    const prev = { role: "prev", focused: 0,
                   focus() { this.focused++; doc.activeElement = this; } };
    doc.activeElement = prev;
    const frames = [];
    const later = [];
    const built = runDialog(doc, (fn2) => frames.push(fn2),
      (fn2) => { later.push(fn2); return 1; }, () => {}, opts);
    const promise = built.first;
    frames.forEach((f) => f());                     // the rAF the real helper focuses inside
    // NO SILENT FALLBACK. An empty body means the helper threw inside its own promise executor —
    // a lifted identifier it needs that this scope does not have — and a stub object standing in
    // for the dialog would report that as "it stopped setting tabindex".
    if (!doc.body.children.length) {
      throw new Error("confirmDanger appended no overlay: it threw inside its promise executor, "
        + "most likely on an identifier declared outside the function and not lifted here");
    }
    const ov = doc.body.children[0];
    const dlg = ov.children[0];
    const focusedRole = doc.focused[0] === dlg ? "dialog" : ((doc.focused[0] || {}).role || null);
    return { doc, ov, dlg, promise, focusedRole, prev, modalOpen: built.modalOpen,
             openAnother: (o) => built.open(o),
             // The teardown timer, run on demand: this is where the helper restores the focus it
             // took, which is the piece the row-leave design has to be able to opt out of.
             settle: () => later.forEach((f) => f()),
             icon: () => (dlg._parts || {})[".tw-dlg-ic"],
             fire: (ev, e) => (ov.listeners[ev] || []).forEach((h) => h(e)),
             backdropListens: Object.keys(ov.listeners || {}) };
  }

  /** What the dialog answered, or the fact that it never did.
   *
   *  A promise that never settles is a HANG, and a hung harness prints nothing at all — which
   *  reports as "the harness itself failed" and sends the next reader to this file instead of to
   *  the assertion that broke. A real answer resolves on a microtask, so it always wins the race
   *  against a sentinel scheduled on the next turn of the loop. */
  const answered = (p) =>
    Promise.race([p, new Promise((r) => setImmediate(() => r("never answered")))]);

  const plainAsk = askWith({ title: "Remove this material?", name: "OPF" });
  const optedIn = askWith({ tone: "warn", title: "Save this change?", name: "Densifier",
                            focus: "container", dismiss: "explicit" });
  out.confirmFocus = {
    // DEFAULT, unchanged for every other caller: the No button takes the focus, and a mousedown
    // on the backdrop cancels.
    defaultFocusesCancel: plainAsk.focusedRole === "no",
    defaultHasBackdropCancel: plainAsk.backdropListens.indexOf("mousedown") !== -1,
    // OPTED IN: the dialog element itself takes the focus, so SPACE cannot press a button that
    // was never focused…
    optedInFocusesTheDialog: optedIn.focusedRole === "dialog",
    optedInDialogIsFocusable: optedIn.dlg.getAttribute("tabindex") === "-1",
    // …and the backdrop is inert, so clicking the next cell cannot answer the question.
    optedInHasNoBackdropCancel: optedIn.backdropListens.indexOf("mousedown") === -1,
    // Escape still works in BOTH — an inert backdrop must not mean an unclosable dialog.
    bothTrapTheKeyboard: (plainAsk.doc.docListeners.keydown || []).length === 1 &&
      (optedIn.doc.docListeners.keydown || []).length === 1,
    // The default caller's own defaults are untouched by the new options existing.
    defaultTabindexAbsent: plainAsk.dlg.getAttribute("tabindex") === null,
  };
  // A BACKDROP MOUSEDOWN on the default dialog still cancels it, and on the opted-in one does
  // nothing at all. Both proved by what the promise resolves to, not by a listener count.
  const backdropDefault = askWith({ title: "x", name: "y" });
  backdropDefault.fire("mousedown", { target: backdropDefault.ov });
  out.confirmFocus.defaultBackdropCancels = (await answered(backdropDefault.promise)) === false;

  // ESCAPE CANCELS the opted-in dialog too — an inert backdrop must not mean a trapped estimator.
  const escaped = askWith({ focus: "container", dismiss: "explicit", title: "x", name: "y" });
  (escaped.doc.docListeners.keydown || []).forEach((h) =>
    h({ key: "Escape", preventDefault() {} }));
  out.confirmFocus.escapeStillCancels = (await answered(escaped.promise)) === false;

  // FOCUS RESTORATION. The default caller wants the focus put back where it was — its dialog went
  // up over a live element. The row-leave caller does NOT: focus had already left the row before
  // the question was asked, so `prevFocus` is whatever the browser parked on mid-transition, and
  // handing the focus back to it 170ms later would yank the caret out of wherever the estimator
  // actually went and out of the field confirmItemPatch just restored.
  const restoreDefault = askWith({ title: "x", name: "y" });
  (restoreDefault.doc.docListeners.keydown || []).forEach((h) =>
    h({ key: "Escape", preventDefault() {} }));
  restoreDefault.settle();
  out.confirmFocus.defaultRestoresTheFocus = restoreDefault.prev.focused === 1;

  const restoreOpted = askWith({ focus: "container", dismiss: "explicit", title: "x", name: "y" });
  (restoreOpted.doc.docListeners.keydown || []).forEach((h) =>
    h({ key: "Escape", preventDefault() {} }));
  restoreOpted.settle();
  out.confirmFocus.optedInLeavesTheFocusAlone = restoreOpted.prev.focused === 0;

  // THE MODAL COUNTER, which the Items page reads to avoid stacking a save question on top of a
  // delete confirmation. Two dialogs in ONE scope, because a boolean would report the second one
  // gone the moment the first closed — and that is the case the Items page is exposed to, since
  // the delete dialog's own focus move is what triggers the save it must not ask about yet.
  {
    const counter = askWith({ title: "Remove this material?", name: "OPF" });
    const afterOne = counter.modalOpen();
    const second = counter.openAnother({ title: "And another", name: "OPF" });
    const afterTwo = counter.modalOpen();
    // Close the FIRST one only — through its own Cancel BUTTON, not Escape. Both dialogs listen
    // for Escape on `document`, so an Escape here would close both and this would be measuring
    // nothing. (That both answer one Escape is the shared helper's own long-standing behaviour and
    // not something this change touches.)
    const noBtn = counter.dlg.querySelector(".tw-dlg-no");
    (noBtn.listeners.click || []).forEach((h) => h({}));
    const afterClosingOne = counter.modalOpen();
    // Read BEFORE the second one is closed, or "the other dialog is still waiting" measures
    // nothing: one of them really was answered and the other really was not.
    const firstAnswered = (await answered(counter.promise)) === false;
    const secondStillWaiting = (await answered(second)) === "never answered";
    // …and then the other one, which has to bring the count back to nothing. Without the
    // decrement the Items page would never save again: every flush from here on would defer
    // against a modal that is not on screen.
    const secondDlg = counter.doc.body.children[1].children[0];
    (secondDlg.querySelector(".tw-dlg-no").listeners.click || []).forEach((h) => h({}));
    out.confirmModalCount = {
      beforeAny: false,          // no dialog has been opened in this scope before askWith
      afterOne, afterTwo, afterClosingOne,
      afterClosingBoth: counter.modalOpen(),
      firstAnswered, secondStillWaiting,
    };
  }

  // THE ICON. The slot is filled with textContent, so an SVG cannot go through `icon` — and the
  // warn tone's own default is a WASTEBASKET, which is the wrong glyph over "Save this change?".
  // `iconSvg` is markup this page writes itself (never a project name), and every caller that
  // does not pass it keeps the exact glyph it draws today.
  const svgAsk = askWith({ tone: "warn", title: "Save this change?", name: "Densifier",
                           focus: "container", dismiss: "explicit",
                           iconSvg: '<svg class="ic"><path d="M1 1"></path></svg>' });
  const warnDefault = askWith({ tone: "warn", title: "Remove this vendor?", name: "Sika" });
  const glyphAsk = askWith({ tone: "warn", title: "x", name: "y", icon: "✎" });
  out.confirmIcon = {
    svgReachesTheSlot: /<svg class="ic">/.test((svgAsk.icon() || {}).innerHTML || ""),
    // …and it is not ALSO written as text, which would draw the markup as a literal string.
    svgNotWrittenAsText: !/svg/.test((svgAsk.icon() || {}).textContent || ""),
    // UNCHANGED for everybody else: the warn default is still the wastebasket glyph and a caller
    // passing `icon` still gets it as text.
    warnDefaultUnchanged: (warnDefault.icon() || {}).textContent === "\u{1F5D1}",
    dangerDefaultUnchanged: (plainAsk.icon() || {}).textContent === "⚠️",
    plainIconStillText: (glyphAsk.icon() || {}).textContent === "✎",
    plainIconNotInjected: ((glyphAsk.icon() || {}).innerHTML || "") === "",
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
    // Materials moved to the TOP of its card (Hanz, 2026-08-28) — it was getting lost below the
    // horizontal scrollbar and a full table of rows. Still inside the same card as the table;
    // just above it instead of after it. The three administration lists are unchanged, at the
    // foot of theirs.
    materialsAddRowInTheCard: /id="items-addrow"/.test(html) &&
      html.indexOf('id="items-addrow"') < html.indexOf('<tbody id="items-body">'),
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

// ── EXECUTED: the advanced search grammar ───────────────────────────────────
// Hanz, 2026-08-27: "For the Items and Assemblies under the Items Tab, we must have filters and an
// advanced search." The matcher was a substring test over one haystack; a bare word still behaves
// exactly that way, which is what keeps the assembly picker working, and everything below is new
// on top of it.
//
// EXECUTED against the REAL parser and the REAL fixture materials, because every interesting
// failure is a parsing fact. A grep for "vendor:" would match the regex that reads it.
{
  const { api } = build();
  const names = (q) => api.ITEMS.filter((it) => api.itemMatches(it, q)).map((it) => it.name);

  out.advSearch = {
    // The old behaviour, unchanged. i1 is OPF / Epoxy / Sherwin-Williams, i2 is OPF Primer /
    // Polished Concrete / Gone Supply Co, so a matcher reading only `name` answers these the same.
    bareWordStillSearchesEverything: names("sherwin"),
    bareWordsStillNarrow: names("polished primer"),

    // FIELD SCOPING. "opf" is in both names, so scoping is the only way to tell these apart by
    // vendor, and a scoped term must NOT fall back to the whole haystack when it misses.
    scopedToVendor: names("vendor:sherwin"),
    scopedToName: names("name:primer"),
    scopedToDivision: names("division:epoxy"),
    scopedToUnit: names("unit:gal"),
    // The scope really is a scope: "epoxy" is a DIVISION on i1, so asking for it as a NAME finds
    // nothing. This is the assertion that fails if a scoped term quietly searches everything.
    scopeIsNotAFallback: names("name:epoxy"),
    aliasesAgree: [names("div:epoxy"), names("supplier:sherwin"), names("material:primer")],

    // NUMBERS. i1 costs 85.3827, i2 costs 426.91; packs are 1 and 5.
    costGreaterThan: names("cost:>100"),
    costLessThan: names("cost:<100"),
    costAtLeast: names("cost:>=426.91"),
    costExactly: names("cost:426.91"),
    packExactly: names("pack:5"),
    priceIsAnAliasOfCost: names("price:>100"),
    // Written the way it is written on the invoice.
    toleratesDollarAndComma: names("cost:<$1,000"),

    // NEGATION.
    negatedBareWord: names("-sherwin"),
    negatedScoped: names("-division:epoxy"),
    negationCombinesWithTheRest: names("opf -epoxy"),

    // PHRASES. Two bare words narrow independently, so "opf primer" as separate terms matches a
    // material called "Primer OPF" too; quoted, it is one string in one order.
    phraseIsOneString: names('"opf primer"'),
    phraseInAScope: names('vendor:"gone supply"'),

    // HONEST ABOUT NOTHING. A term the parser cannot make sense of must match NOTHING, never
    // everything: a dropped term hands the full list back and reads as the search being ignored,
    // which is worse than a blank table because it looks like it worked.
    nonsenseNumberFindsNothing: names("cost:abc"),
    unknownFieldIsSearchedLiterally: names("colour:red"),
    // …and a material with NO cost is not a material costing nothing, so it fails every
    // comparison rather than sorting under cost:<1.
    absentCostIsNotZero: api.numberHits(null, "<1"),
    absentCostFailsGreaterThan: api.numberHits(null, ">1"),
    blankIsNotZero: api.numberHits("", "=0"),

    // Still kind while somebody is typing: a scope with nothing after the colon is not yet a term.
    halfTypedScopeShowsEverything: names("vendor:").length,
    blankStillFindsEverything: names("").length,
    // The parse itself, so a change of shape is visible rather than inferred from a match count.
    parsed: api.parseQuery('vendor:"gone supply" cost:>100 -epoxy loose'),
  };
}

// ── EXECUTED: the facets ────────────────────────────────────────────────────
// Three, and each earns its place off a column that already exists. Division and vendor narrow
// what somebody could already find by typing; CONDITION answers the question no search can, which
// is what in this list is not safe to price a bid from.
//
// There is no waste-factor or Roundup? facet because neither is a property of a material: both
// live on an assembly LINE (_clean_lines in backend/library.py). This block proves the fixture
// items carry no such field, so a later reader does not spend an afternoon looking for one.
{
  const FIXTURES = [
    { id: "p1", name: "Priced", divisions: ["Epoxy"], unit: "Gallon", buy_qty: 5,
      unit_cost: 100, coverage: 275, vendor: "Sika", created_at: null,
      cost_updated_at: "2026-08-14T21:15:00Z" },
    { id: "p2", name: "No cost", divisions: ["Epoxy"], unit: "Gallon", buy_qty: 1,
      unit_cost: null, coverage: 275, vendor: "Sika", created_at: null, cost_updated_at: null },
    { id: "p3", name: "Unfiled", divisions: [], unit: "Gallon", buy_qty: 1, unit_cost: 12,
      coverage: 275, vendor: "", created_at: null, cost_updated_at: null },
    { id: "p4", name: "Gyp bag", divisions: ["Gypsum Underlayment"], unit: "Bag", buy_qty: 1,
      unit_cost: 30, coverage: 100, vendor: "Sherwin-Williams", created_at: null,
      cost_updated_at: "2026-08-01T00:00:00Z" },
  ];
  const shown = (filters, q) => {
    const b = build(Object.assign({ ITEMS: JSON.parse(JSON.stringify(FIXTURES)) },
      { FILTERS: Object.assign({ divisions: [], vendor: "", condition: "" }, filters || {}) },
      q === undefined ? {} : { itemQuery: q }));
    return b.api.visibleItems().map((x) => x.name);
  };

  out.facets = {
    // No facet, no query: the list is handed back untouched, not a copy through the filter.
    nothingOnShowsEverything: shown({}).length,

    // DIVISION: ORs within itself, because "epoxy or gypsum" is the question actually asked.
    oneDivision: shown({ divisions: ["Epoxy"] }),
    twoDivisionsOr: shown({ divisions: ["Epoxy", "Gypsum Underlayment"] }),
    divisionIsCaseInsensitive: shown({ divisions: ["ePoXy"] }),

    // VENDOR: an exact match on the value the dropdown offered, not a substring, or picking
    // "Sika" would also pull in a "Sika Distribution Co" that is a different account.
    oneVendor: shown({ vendor: "Sika" }),
    vendorIsCaseInsensitive: shown({ vendor: "sika" }),

    // CONDITION.
    missingACost: shown({ condition: "no_cost" }),
    notInAnyDivision: shown({ condition: "no_division" }),
    noVendor: shown({ condition: "no_vendor" }),
    priceNeverRecorded: shown({ condition: "no_price_date" }),

    // ACROSS facets it is AND, so two of them narrow rather than widen.
    facetsAnd: shown({ divisions: ["Epoxy"], condition: "no_cost" }),
    // …and the text box ANDs with them too.
    textAndsWithFacets: shown({ divisions: ["Epoxy"] }, "cost:>50"),
    // A combination nothing satisfies gives nothing, rather than falling back to a wider answer.
    impossibleCombination: shown({ divisions: ["Gypsum Underlayment"], vendor: "Sika" }),
  };

  // The facets are the ITEMS TAB'S, not the matcher's. The assembly line picker searches with
  // itemMatches and must NOT inherit a bar it cannot see — a line quietly unable to find a
  // material because of a filter set on another tab would be unexplainable from where it happens.
  const filtered = build({
    ITEMS: JSON.parse(JSON.stringify(FIXTURES)),
    FILTERS: { divisions: ["Epoxy"], vendor: "", condition: "" },
  });
  out.facets.pickerIgnoresTheFacets =
    /data-pick-item="p4"/.test(filtered.api.itemResultsHtml({ _item_search: "gyp" }));
  out.facets.tabStillObeysThem = filtered.api.visibleItems().map((x) => x.name);

  // No item carries a waste factor or a roundup flag, so neither could be a facet here.
  out.facets.itemsHaveNoWasteOrRoundup = FIXTURES.every(
    (f) => f.waste_pct === undefined && f.roundup === undefined);
}

// ── EXECUTED: the filter survives what re-renders the list ──────────────────
// "The filter state must survive the things that re-render the list - an edit, a save, a tab
// switch back - or it will read as the filter randomly clearing itself."
//
// Two mechanisms, and both are tested because either alone is not enough. The STATE lives in
// plain variables rather than in the DOM, and the CONTROLS live outside the tbody renderItems
// replaces. The third hazard is renderFilterBar itself, which paint() calls on every edit: if it
// rewrote its markup each time it would drop the focus of anybody tabbing the chips, so it only
// writes when the offered values have actually changed.
{
  const b = build({ FILTERS: { divisions: ["Epoxy"], vendor: "Sika", condition: "no_cost" } });

  b.api.renderFilterBar();
  const firstChips = b.dom.nodes["f-divisions"].innerHTML;

  /** Count WRITES to innerHTML, not the value that ends up there.
   *
   *  The first version of this compared the markup before and after and passed against a
   *  renderFilterBar that rebuilt unconditionally - because rebuilding from the same FILTERS
   *  produces a byte-identical string. In a browser that write still destroys every node in the
   *  strip and takes the focus with it, which is the entire bug being guarded against. So the
   *  question is whether the assignment happened, and only a spy can answer it. */
  function countWrites(node) {
    var held = node.innerHTML, n = 0;
    Object.defineProperty(node, "innerHTML", {
      configurable: true,
      get: function () { return held; },
      set: function (v) { n++; held = v; },
    });
    return function () { return n; };
  }
  const chipWrites = countWrites(b.dom.nodes["f-divisions"]);
  const vendorWrites = countWrites(b.dom.nodes["f-vendor"]);

  // An edit and a save both go through renderItems, and paint() calls renderFilterBar after it.
  b.api.renderItems();
  b.api.renderFilterBar();
  b.api.renderItems();
  b.api.renderFilterBar();

  out.filterState = {
    // The chips came back with the active division still on.
    rebuiltFromTheModel: /data-fdiv="Epoxy"[^>]*checked/.test(firstChips),
    // …and were NOT written again on the repeat passes, which is what would cost the focus.
    chipWritesOnRepaint: chipWrites(),
    vendorWritesOnRepaint: vendorWrites(),
    // The selects still say what the model says.
    vendorHeld: b.dom.nodes["f-vendor"].value,
    conditionHeld: b.dom.nodes["f-condition"].value,
    clearOffered: b.dom.nodes["f-clear"].hidden === false,
    // The state is not read back off the DOM at all, so nothing renderItems does can lose it.
    modelHeld: JSON.stringify(b.api.FILTERS),
  };

  // …but an admin ADDING a division must rebuild the strip, or the new value is unfilterable
  // until somebody reloads. Same spy, and here it has to fire exactly once.
  const grown = build({ FILTERS: { divisions: ["Epoxy"], vendor: "", condition: "" } });
  grown.api.renderFilterBar();
  const grownWrites = countWrites(grown.dom.nodes["f-divisions"]);
  grown.api.renderFilterBar();
  out.filterState.quietWhenNothingChanged = grownWrites();
  grown.api.setDivisions(["Polished Concrete", "Epoxy", "Gypsum Underlayment",
                          "Sealer & Traffic Coatings"]);
  grown.api.renderFilterBar();
  const after = grown.dom.nodes["f-divisions"].innerHTML;
  out.filterState.writesAfterANewDivision = grownWrites();
  out.filterState.newDivisionAppears = /data-fdiv="Sealer &amp; Traffic Coatings"/.test(after);
  out.filterState.rebuildKeptTheActiveOne = /data-fdiv="Epoxy"[^>]*checked/.test(after);
  // Free text somebody typed on the Administration tab, escaped rather than injected.
  out.filterState.customIsEscaped = !/data-fdiv="Sealer & Traffic/.test(after);

  // With nothing on, the Clear button is not offered.
  const idle = build();
  idle.api.renderFilterBar();
  out.filterState.clearHiddenWhenIdle = idle.dom.nodes["f-clear"].hidden === true;
}

// ── EXECUTED: the empty state says what it left out ─────────────────────────
// "Empty state: say what was filtered out and offer the way back, do not show a blank rail."
{
  const gone = build({
    FILTERS: { divisions: ["Gypsum Underlayment"], vendor: "Sika", condition: "no_cost" },
    itemQuery: "primer",
  });
  gone.api.renderItems();
  const hit = build({ itemQuery: "primer" });
  hit.api.renderItems();
  // A FACET with an empty search box still counts as filtering. The line this replaced read only
  // itemQuery, so narrowing to a division nothing is filed under produced a blank table with the
  // add row gone and no panel at all.
  const facetOnly = build({ FILTERS: { divisions: ["Nothing Is In Here"], vendor: "", condition: "" } });
  facetOnly.api.renderItems();

  out.filterEmpty = {
    panelShown: gone.dom.nodes["items-nomatch"].hidden === false,
    why: gone.dom.nodes["items-nomatch-why"].textContent,
    // Every active constraint is named, not just the text.
    namesTheQuery: /"primer"/.test(gone.dom.nodes["items-nomatch-why"].textContent),
    namesTheDivision: /Gypsum Underlayment/.test(gone.dom.nodes["items-nomatch-why"].textContent),
    namesTheVendor: /Sika/.test(gone.dom.nodes["items-nomatch-why"].textContent),
    namesTheCondition: /no cost recorded/.test(gone.dom.nodes["items-nomatch-why"].textContent),
    // The way back is offered in the panel as well as the bar, and both press the same handler.
    clearOfferedInThePanel:
      (html.match(/data-clear-filters/g) || []).length === 2 &&
      /id="items-nomatch"[\s\S]*?data-clear-filters/.test(html),
    // A facet alone opens the panel.
    facetAloneOpensThePanel: facetOnly.dom.nodes["items-nomatch"].hidden === false,
    facetAloneExplainsItself: facetOnly.dom.nodes["items-nomatch-why"].textContent,
    // A hit shows the count, not the panel.
    hitHidesThePanel: hit.dom.nodes["items-nomatch"].hidden === true,
    hits: hit.dom.nodes["item-hits"].textContent,
    // The blank rail this replaces: no rows AND no add row, so the panel is the only thing left
    // to explain the screen.
    addRowGoneWhenNothingMatches: gone.dom.nodes["items-addrow"].hidden === true,
    // The tab badge still counts what Treadwell HAS.
    badgeIsStillTheTotal: gone.dom.nodes["n-items"].textContent,
  };
}

// ── the keyboard, and where the controls sit in the markup ──────────────────
{
  const between = (open, close) => {
    const i = html.indexOf(open);
    const j = html.indexOf(close, i);
    return i === -1 ? "" : html.slice(i, j === -1 ? html.length : j);
  };
  out.filterKeyboard = {
    // Escape clears the box. type="search" has a native clear affordance in Chromium but it is a
    // mouse target, and Escape is not wired to it the same way everywhere.
    escapeClears: /if \(e\.key !== "Escape" \|\| !String\(itemQuery\)\.trim\(\)\) return;/.test(src),
    // Every facet control is a real focusable control rather than a div with a click handler.
    divisionsAreCheckboxes: /<input type="checkbox" data-fdiv=/.test(
      (() => { const b = build(); b.api.renderFilterBar(); return b.dom.nodes["f-divisions"].innerHTML; })()),
    vendorIsASelect: /<select id="f-vendor">/.test(html),
    conditionIsASelect: /<select id="f-condition">/.test(html),
    // Named for a screen reader: the chip strip is a group with a label, and the two selects have
    // real <label for> rather than a placeholder standing in for one.
    chipStripIsALabelledGroup:
      /<span class="fchips" id="f-divisions" role="group"\s+aria-labelledby="f-div-label">/
        .test(html.replace(/\r\n/g, "\n")),
    selectsHaveLabels: /<label class="flabel" for="f-vendor">/.test(html) &&
      /<label class="flabel" for="f-condition">/.test(html),
    // THE SYNTAX HINT IS GONE, at Hanz's request on 2026-08-27, and these probes now guard its
    // ABSENCE rather than its presence. He is the person who uses this page every day; a line of
    // grammar help under the box was explaining his own tool to him.
    //
    // The GRAMMAR is untouched - see out.advSearch, which parses all five forms the deleted line
    // used to advertise. Only the on-screen sentence went.
    tipsGone: !/id="search-tips"/.test(html) && !/class="searchtips"/.test(html) &&
      !/Narrow it:/.test(html),
    // NOTHING ORPHANED. The input pointed aria-describedby at that paragraph's id; left behind it
    // is a reference to an element that does not exist, which a screen reader reads as nothing at
    // all rather than as a fault anybody would notice.
    noOrphanedDescribedBy: !/aria-describedby/.test(html),
    searchFieldStillNamed: /<input id="item-q"[\s\S]{0,240}?aria-label="Search materials"/.test(html),
    // The rules and the only <code> on the page went with it, rather than being left as dead
    // stylesheet for the next reader to wonder about.
    searchtipsCssGone: !/\.searchtips/.test(html) && !/<code/.test(html),
    // …and the row closed up. The bar spaces itself with `gap` on the grid, so deleting a child
    // removes its space too - there is no empty container left holding a margin open.
    barClosedUp: /\.filterbar \{[^}]*display:grid[^}]*\}/.test(html) &&
      !/<p class="searchtips"/.test(html) && !/class="filterbar"[^>]*>\s*<\/div>/.test(html),
    // THE COMPOSITION AFTER THE DELETION. The sentence was doing the separating between the search
    // box and the facets; without it the bar's row gap equalled a facet's own label-to-control
    // gap and the two rows read as one block. Each step has to be bigger than the one it
    // contains, so the ORDERING is what is asserted rather than three magic numbers.
    spacingHierarchy: (() => {
      const px = (re) => Number((re.exec(html) || [0, 0])[1]);
      const inFacet = px(/\.facet \{[^}]*gap:(\d+)px/);
      const betweenRows = px(/\.filterbar \{[^}]*gap:(\d+)px/);
      const toTheTable = px(/\.filterbar \{ margin:0 0 (\d+)px/);
      return { inFacet, betweenRows, toTheTable,
               ordered: inFacet > 0 && inFacet < betweenRows && betweenRows < toTheTable };
    })(),
    // THE CONTROLS ARE OUTSIDE THE TBODY renderItems replaces. This is the structural half of the
    // survives-a-re-render answer, and it is a fact about the markup rather than about a variable.
    controlsOutsideTheRenderedBody:
      html.indexOf('id="f-divisions"') < html.indexOf('<tbody id="items-body">') &&
      html.indexOf('id="item-q"') < html.indexOf('<tbody id="items-body">'),
    // And the bar is not a fifth card.
    barIsNotACard: !/class="card[^"]*"[^>]*>\s*<div class="filterbar"/.test(html) &&
      !/class="filterbar card"/.test(html),
  };
}

// ── the page's own copy ──────────────────────────────────────────────────────
out.page = {
  title: /<title>([^<]*)</.exec(html)[1],
  h1: /<h1>([^<]*)</.exec(html)[1],
  materialHeaderNamesTheManufacturer:
    /Materials <span[^>]*>\(how the manufacturer names it\)<\/span>/.test(html),
  // REMOVED 2026-08-27 at Hanz's request, and this probe is kept pointing at the deleted
  // sentence on purpose: it must stay false. He uses this tab daily and did not need the pack
  // convention explained to him in a paragraph above it.
  itemsIntro: /Items are entered as we buy them/.test(html),
  // The other two panes keep theirs. They were asked for by name, they were not what he
  // screenshotted, and neither is a tab anybody lives in.
  assembliesIntro: /Assemblies are how we estimate them/.test(html),
  adminIntro: /Administration lists\./.test(html),
  // The class survives the deletion because two panes still use it. A stylesheet rule with no
  // remaining caller is the thing to delete; this is not one.
  paneintroStillUsed: (html.match(/class="paneintro"/g) || []).length,
  coveragePerUnitHeader: /Coverage per Unit/.test(html),
  wasteHeader: /Waste Factor/.test(html),
  roundupHeader: /Roundup\?/.test(html),
  vendorsTab: /id="tab-vendors"/.test(html),
  noCoverageSfHeader: !/Coverage \(SF\)/.test(html),
  noRoleHeader: !/<th[^>]*>Role<\/th>/.test(html),
};

// A WATCHDOG, because the alternative failure mode is silence. These scenarios await dialogs and
// held requests, so a change that opens one more dialog than a test answers leaves a flush waiting
// forever: node's loop empties, the process exits 0, and nothing is printed — which the fixture
// reports as "the harness itself failed" with no line number and no clue. A pending timer keeps
// the loop alive long enough to say what actually happened.
const watchdog = setTimeout(() => {
  console.error("A SCENARIO NEVER SETTLED. Something is awaiting a dialog nobody answered or a "
    + "request nobody released — most likely a change that asks one MORE time than the scenario "
    + "expects. Look at the scenario you touched, not at this file.");
  process.exit(1);
}, 30000);

Promise.all([conflictChecks(), dialogChecks()]).then(
  () => { clearTimeout(watchdog); console.log(JSON.stringify(out)); },
  (err) => { clearTimeout(watchdog); console.error(err); process.exit(1); });
