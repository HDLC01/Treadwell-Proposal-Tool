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
const src = fs.readFileSync(path.join(ROOT, "js", "library.js"), "utf8");
const html = fs.readFileSync(path.join(ROOT, "library.html"), "utf8");
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
  });
  return { el, nodes };
}

const dom = makeDom();
const scope = new Function("L", "$", "TW", "state", `
  "use strict";
  var ITEMS = state.ITEMS, ASMS = state.ASMS, VENDORS = state.VENDORS;
  var VENDOR_USE = state.VENDOR_USE, ADMIN = state.ADMIN;
  var openId = state.openId;
  ${grab(/^  var DIVISIONS = \[[^\]]*\];$/m, "DIVISIONS")}
  ${grab(/^  var UNITS = \[[^\]]*\];$/m, "UNITS")}
  ${grab(/^  var esc = function[\s\S]*?\n  \};$/m, "esc")}
  ${fn("current")}
  ${fn("itemOf")}
  ${fn("pick")}
  ${fn("vendorNames")}
  ${fn("similarNames")}
  ${fn("dupeHtml")}
  ${fn("datesHtml")}
  ${fn("renderItems")}
  ${fn("renderVendors")}
  ${fn("pickerFor")}
  ${fn("itemByName")}
  ${fn("renderList")}
  ${fn("renderPanel")}
  ${fn("refreshNumbers")}
  ${grab(/^  var NUMERIC_ITEM_FIELDS = \[[^\]]*\];$/m, "NUMERIC_ITEM_FIELDS")}
  return { renderItems, renderVendors, renderPanel, renderList, refreshNumbers,
           pickerFor, itemByName, similarNames, pick, datesHtml,
           NUMERIC_ITEM_FIELDS, ITEMS, VENDORS };
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

function build(overrides) {
  const d = makeDom();
  const st = Object.assign({
    ITEMS: JSON.parse(JSON.stringify(ITEMS)),
    ASMS: JSON.parse(JSON.stringify(ASMS)),
    VENDORS: JSON.parse(JSON.stringify(VENDORS)),
    VENDOR_USE: { "sherwin-williams": 1, sika: 0 },
    ADMIN: false, openId: "a1",
  }, overrides || {});
  const TW = { fmtBizDateTime: (iso) => "BIZ(" + iso + ")" };
  const api = scope(L, d.el, TW, st);
  d.el("area").value = "2875";
  return { api, dom: d, st };
}

const out = {};

// ── Items: the columns Hanz asked for, and the ones he asked to lose ─────────
{
  const { api, dom: d } = build();
  api.renderItems();
  const row = d.nodes["items-body"].innerHTML.split("</tr>")[0];
  out.items = {
    // Present.
    hasDivisionDropdown: /<select data-f="category"[\s\S]*?Gypsum Underlayment/.test(row),
    divisionOptions: (row.match(/<select data-f="category"[\s\S]*?<\/select>/) || [""])[0]
      .split("<option").slice(1).map((o) => (/>([^<]*)</.exec(o) || ["", ""])[1]),
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
  const asUser = plain.dom.nodes["vendors-body"].innerHTML;
  const admin = build({ ADMIN: true });
  admin.api.renderVendors();
  const asAdmin = admin.dom.nodes["vendors-body"].innerHTML;
  out.vendors = {
    userGetsNoInputs: !/<input/.test(asUser),
    userGetsNoDeleteButton: !/data-del-vendor/.test(asUser),
    userStillSeesTheNames: /Sherwin-Williams/.test(asUser) && /Sika/.test(asUser),
    userToldWhoToAsk: plain.dom.nodes["vendors-ro"].hidden === false,
    userNotOfferedAddButtons: plain.dom.nodes["vendor-addrow"].hidden === true &&
      plain.dom.nodes["vendor-add-first"].hidden === true,
    adminGetsInputs: /<input data-vf="name"/.test(asAdmin) && /<input data-vf="notes"/.test(asAdmin),
    adminGetsDelete: /data-del-vendor="v1"/.test(asAdmin),
    adminNotShownTheReadOnlyNote: admin.dom.nodes["vendors-ro"].hidden === true,
    adminOfferedAdd: admin.dom.nodes["vendor-addrow"].hidden === false,
    // How many materials name each vendor, so a delete can say what it affects.
    usageShown: /<td class="n">1<\/td>/.test(asAdmin),
    count: admin.dom.nodes["n-vendors"].textContent,
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
    pickerIsSearchable: /<input data-lf="item_name" list="dl-materials"/.test(firstRow),
    pickerShowsTheCurrentMaterial: /value="OPF"/.test(firstRow),
    pickerIsNotASelect: !/<select data-lf="item_id"/.test(body),
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
    /Material <span[^>]*>\(how the manufacturer names it\)<\/span>/.test(html),
  itemsIntro: /Items are entered as we buy them/.test(html),
  assembliesIntro: /Assemblies are how we estimate them/.test(html),
  coveragePerUnitHeader: /Coverage per Unit/.test(html),
  wasteHeader: /Waste Factor/.test(html),
  roundupHeader: /Roundup\?/.test(html),
  vendorsTab: /id="tab-vendors"/.test(html),
  noCoverageSfHeader: !/Coverage \(SF\)/.test(html),
  noRoleHeader: !/<th[^>]*>Role<\/th>/.test(html),
};

console.log(JSON.stringify(out));
