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

/** Lift a named function out of the page's IIFE (two-space indent), braces balanced. */
function fn(name) {
  const m = new RegExp("\\n  function " + name + "\\s*\\(").exec(src);
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
  ${fn("renderItems")}
  ${fn("adminList")}
  ${fn("usageFor")}
  ${fn("singular")}
  ${fn("renderRefSection")}
  ${fn("renderVendors")}
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
  ${fn("onItemEdit")}
  return { renderItems, renderVendors, renderPanel, renderList, refreshNumbers,
           pickerFor, itemByName, similarNames, pick, datesHtml, adoptSaved,
           onItemEdit, QUEUED, NUMERIC_ITEM_FIELDS, ITEMS, VENDORS,
           itemMatches, itemResultsHtml, lineForSave };
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
    // Present.
    hasDivisionCheckboxes: /class="division-picks"/.test(row) &&
      /data-f="divisions"/.test(row),
    divisionOptions: (row.match(/<div class="division-picks"[\s\S]*?<\/div>/) || [""])[0]
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
  const saveScope = new Function("api", "clock", "hooks", "state", `
    "use strict";
    var timers = {};
    var pendingPatch = {};
    var ASMS = state.ASMS, ITEMS = state.ITEMS, VENDORS = state.VENDORS;
    var setTimeout = clock.setTimeout, clearTimeout = clock.clearTimeout;
    function saving(m) { hooks.saving.push(m); }
    function say(m) { hooks.said.push(m); }
    function renderList() { hooks.renders.push("list"); }
    function renderPanel() { hooks.renders.push("panel"); }
    function paintDates() {}
    function datesHtml() { return ""; }
    ${fn("byId")}
    ${fn("adoptSaved")}
    ${fn("adoptConflict")}
    ${fn("patchSoon")}
    return { patchSoon: patchSoon, adoptConflict: adoptConflict,
             armed: function () { return Object.keys(timers).length; },
             pending: function () { return Object.keys(pendingPatch).length; },
             // Empties the buffer WITHOUT disarming, which is the state the empty-payload guard
             // exists for. adoptConflict no longer produces it — that is the point of the fix —
             // so the guard is defence for the next code path that empties this buffer, and a
             // test of it has to construct the state deliberately rather than pretend otherwise.
             dropBuffer: function () { pendingPatch = {}; } };
  `);

  function run409(fix) {
    const hooks = { saving: [], said: [], renders: [], requests: [], errors: [] };
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
                    ITEMS: [], VENDORS: [] };
    const s = saveScope(api, clock, hooks, state);
    return { hooks, clock, s, release, fire: async () => {
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
