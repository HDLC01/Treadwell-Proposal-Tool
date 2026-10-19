// Polish estimating, step 2 for polish jobs — three steps, priced from the item library.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// WHAT CHANGED, AND WHY THE WORKBOOK IS GONE FROM THIS PAGE.
//
// The first version of this page was a form over the Polish worksheet: every field wrote a cell,
// HyperFormula recalculated the sheet's own formulas, and the bid was read back out of D82. That
// held as long as the beta only re-arranged inputs the worksheet already had.
//
// Will's 2026-08-17 pass asked for things the worksheet cannot represent — a takeoff whose rows are
// ASSEMBLIES out of the Items & Assemblies library, labor lines an estimator can add, and the
// markup chain shown as its own reviewable block. There is no cell to write an assembly into. So
// the beta now prices itself, and the connection to Kyle's file is kept a different way: every
// percentage and every step of the chain is transcribed in bid-model.js, and
// backend/tests/test_polish_markup_parity.py fails if his workbook and that transcription ever
// disagree. The pin replaces the engine.
//
// Two consequences worth stating plainly:
//
//   * This page NO LONGER writes the takeoff or pricing cells into state.cell_values — with ONE
//     exception, added 2026-09-15 when the Review step's condition switches shipped: the five
//     Yes/No condition cells, through B.conditionCellWrites. Those are not a rendering of the bid,
//     they are the contract this screen shares with the intake page, which reads them back and
//     lets the cell win over the model. A writer that skips them hands the estimator their old
//     answer back on the next visit to Intake. AND, since 2026-09-30, the Dye and Joint Filler
//     rate/quantity cells (Polish!C25, C29, and B25/B29 when they differ from the template), so
//     the workbook prices those two lines off the same library rows this page does -- see
//     conditionLibrary and bid-model.js's libraryLineWrites. Otherwise the downloaded
//     .xlsx shows the template's own Polish tab, not what was priced here. That is survivable only because the
//     beta works on test projects by construction (see polish-sandbox.js) — it must be revisited
//     before any of this prices a real bid.
//   * computed_bid is REPLACED on every save, not merged. On a sandbox copy the source project's
//     computed_bid arrived with the blob, and merging would leave a real project's total sitting
//     underneath a beta price.
(function () {
  "use strict";

  /** One drawn glyph out of js/icons.js, which every page loads before this file.
   *
   *  NEVER an emoji — an emoji is drawn by whatever font the machine has, cannot take the
   *  row's colour, and ignores every size token on the page. `typeof TWIcon` rather than
   *  `window.TWIcon` because the test harnesses lift these renderers into a bare Function
   *  scope with no `window`; an icons.js that failed to load then costs a page its pictures
   *  rather than its render.
   */
  function icon(name, size) {
    return typeof TWIcon === "function" ? TWIcon(name, size) : "";
  }

  var B = window.TWBidModel;      // the markup chain, pinned to Kyle's Polish tab
  // The one vocabulary and job-conditions table (js/work-types.js). Bound ABOVE adopt() on purpose:
  // adopt() runs at parse time, and condLine reads the reserved library ids off it.
  var T = window.TWWorkTypes;
  var L = window.TWLib;            // priceAssembly — the same maths the library page shows
  // The Epoxy tab's patch, cove and tooling: what the sheet does before its markup chain and a library row
  // cannot say (js/epoxy-takeoff.js). Bound ABOVE adopt() like T, because pricing a section reads it.
  var E = window.TWEpoxyTakeoff;
  // The Gyp tabs' areas, bags, extras, sand and sound mat (js/gyp-takeoff.js). Bound here for the same reason; a page
  // that does not load it prices no Gyp section (priceSection says so) and every other section is untouched.
  var G = window.TWGypTakeoff;
  // The Seal tabs' patch, tooling and starting takeoff (js/seal-takeoff.js): what a Seal option adds to its rows.
  var SL = window.TWSealTakeoff;
  var S = window.TWPolishSandbox;  // never edit a live bid
  var P = window.TWLibraryPicker;  // the one search pop-up both "Add" buttons open (js/library-picker.js)
  // The base-pick rule for the lines typed on the Proposal step (js/price-lines-core.js): the Sheets panel applies it when the
  // estimator changes the base bid, as the live estimate and the proposal's own base picker do. A page that lacks it
  // changes the base and leaves those lines as they were, which is what the page did before the panel could.
  var PR = window.TWPrice;
  var $ = function (id) { return document.getElementById(id); };

  // The draft this page is working ON, and the model derived from it. Reassigned together by
  // adopt(), because the page can switch drafts mid-boot: opening a real bid here works on a test
  // copy instead, and rendering the copy with the real bid's numbers still in hand would be the
  // same silent mix-up in a different direction.
  var state = {};
  // ROOT IS THE WHOLE MODEL and M IS THE MODEL THE PANELS EDIT (Phase 12). They are the same object for every
  // bid with one section, which is every Polish bid. When a bid has several and the estimator opens one that is
  // not the root, M is a view of that section (B.sectionView): `M.takeoff`, `M.labor`, `M.contingency` and
  // `M.fees` are that section's and every other key is the model's, so the Material, Labor and Review panels are
  // the same code for every section and nothing is copied. Anything that is about the WHOLE bid (saving, pricing
  // every section, the strip) reads ROOT, never M. See show().
  var ROOT = null;
  var M = null;
  // The takeoff SF the labor days last followed (null until the page has opened). See changed().
  var followSf = null;

  // The library, loaded once at boot. Prices are recomputed from these on every keystroke rather
  // than stored on the row: an item's cost can move, and a stored line total would then disagree
  // with the same assembly priced on the library page.
  var ASMS = [];
  var ITEMS = [];

  var at = 0;
  // The section on show (a workbook tab id). The root, Polish, unless the bid has more than one section and
  // the estimator picked another (paintSections). Every bid today has one section, so this never moves.
  var activeTab = B.ROOT_TAB;

  /** The model a panel edits while `tab` is on show: the root itself, or a view of that section. A bid whose
   *  sections cannot be read has only its root to show. */
  function viewOf(tab) {
    if (tab === B.ROOT_TAB || !ROOT.tabs) return ROOT;
    try { return B.sectionView(ROOT, tab); } catch (err) { activeTab = B.ROOT_TAB; return ROOT; }
  }

  /** Put a section on show: the panels from here on edit it. */
  function show(tab) {
    activeTab = tab;
    M = viewOf(tab);
  }

  /** The section a bid opens on: the first one that is part of it (an Epoxy job's Polish root is off, so it
   *  opens on Epoxy). The root when the sections cannot be read. */
  function openingTab() {
    try { return B.travelCarrier(ROOT); } catch (err) { return B.ROOT_TAB; }
  }

  /** Is the section on show the one that carries the job's travel? ONE section does (B.travelCarrier), so a combo
   *  bid charges Hotel and Per Diem once and not once for each of its two sections. A bid with one section is
   *  always its own carrier. */
  function carriesTravel() {
    if (!ROOT || !ROOT.tabs) return true;
    try { return B.travelCarrier(ROOT) === activeTab; } catch (err) { return true; }
  }

  /** Is the section on show an option? An option is priced apart and carries its own Hotel and Per Diem (B.optionTravelCosts). */
  function activeIsOption() {
    try { return B.sectionOf(ROOT, activeTab).kind === "option"; } catch (err) { return false; }
  }

  /** Is the section on show a BASE of the bid that does not carry the job's travel? The job's one drive is charged on the carrier, so a
   *  Travel Labor row sitting here is a leftover of a carrier move (B.followDistance): empty, or typed and left as typed. Its card
   *  says the drive is charged elsewhere (B.strayTravelNote). An option is not this: it is priced apart and its Travel Labor is its own. */
  function holdsStrayTravel() {
    if (!ROOT || !ROOT.tabs) return false;
    try { return B.sectionOf(ROOT, activeTab).kind === "base" && B.travelCarrier(ROOT) !== activeTab; } catch (err) { return false; }
  }

  /** What the notes call the section that carries the job's travel: its name on screen (a sheet the estimator renamed is called that),
   *  else its tab id. */
  function carrierName() {
    try {
      var tab = B.travelCarrier(ROOT);
      return B.sectionOf(ROOT, tab).label || tab;
    } catch (err) { return B.ROOT_TAB; }
  }

  /** The words on the Labor and Review steps of a section that does not carry the job's travel. */
  function travelNote() {
    var tab = B.ROOT_TAB;
    try { tab = B.travelCarrier(ROOT); } catch (err) { tab = B.ROOT_TAB; }
    if (activeIsOption()) {
      return "This option is priced apart, so it carries its own Hotel and Per Diem for its own crew when the job is on the road, " +
        "at the rates set on the " + tab + " section. Open it to change them.";
    }
    return "Travel, Hotel and Per Diem are charged once for the whole job, on the " + tab +
      " section. Open it to change them.";
  }

  function adopt(blob) {
    state = blob || {};
    ROOT = B.migrateModel(state.polish_estimate);
    M = ROOT;
    // THE CELL WINS WHERE THERE IS ONE, the same rule polish-intake.js has always applied, through
    // the same shared reader so the two screens cannot disagree about one answer.
    //
    // THIS WAS A LIVE BUG UNTIL THE THREE MOVED HERE. migrateModel alone hands back freshModel's
    // defaults for any key a saved blob never stated, so a draft written before dye, joint filler
    // and remove-existing were model keys would have shown this step the DEFAULTS rather than what
    // the estimator answered on intake -- and the next save would have written those defaults over
    // the real answers in Polish!E25/E29/F29. joint_filler is the one that bites: it ships ON, so a
    // project where somebody deliberately turned it off would have had it quietly turned back on
    // and the downloaded workbook would have said Yes.
    //
    // Safe only because every writer writes both places: saveSoon puts all eight cells back through
    // conditionCellWrites on every save, so the cell can never be the staler of the two.
    //
    // `T.isSplit(state)`: on a draft the estimate screen has split per sheet, the two tax answers are the
    // base sheet's own cell, and the save below (B.buildSavePatch) writes the same one.
    ROOT.conditions = B.conditionsFromCells(ROOT.conditions, state.cell_values, T.isSplit(state));
    // BEFORE THE FIRST PAINT, not on the first edit. `changed()` is what normally keeps a derived
    // Guys figure current, and nothing calls it on load -- so without this a reopened draft shows
    // Travel's Guys box empty until somebody touches an unrelated field, and prices it at nothing
    // in the meantime.
    syncAutoGuys();
    show(openingTab());
  }

  adopt(TW.getState());

  var STEPS = [
    { key: "takeoff", label: "Material" },
    { key: "labor",   label: "Labor" },
    { key: "review",  label: "Review" },
  ];

  var UNITS = ["SF", "LF"];

  function say(msg, ok) {
    var el = $("alert");
    el.textContent = msg || "";
    el.className = "alert" + (ok ? " ok" : "");
  }

  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  };

  /** A form value: the estimator's own text, or empty. Never "0" for a field they left alone. */
  function nv(v) { return v == null ? "" : String(v); }

  /** Money with cents only when there are cents.
   *
   *  Kyle's sheet shows whole dollars, and a column of "$3,864.00" reads heavy. But hiding cents
   *  under a total that sums the exact figures is how "11 × $85.38" ended up printed under
   *  $939.21 on the library page. So: round figures stay round, and a fraction says so. */
  function moneyAuto(n) {
    var v = B.num(n);
    return Math.abs(v - Math.round(v)) < 0.005 ? B.money(v) : B.money2(v);
  }

  var api = async function (path, opts) {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    return fetch(TW.resolveApiBase() + path,
      Object.assign({}, opts || {}, { headers: TW.authHeaders((opts || {}).headers) }));
  };

  // ── pricing ─────────────────────────────────────────────────────────────────
  function asmById(id) {
    if (!id) return null;
    for (var i = 0; i < ASMS.length; i++) { if (ASMS[i].id === id) return ASMS[i]; }
    return null;
  }

  /** Resolve typed text to an assembly: exact name first, then a UNIQUE case-insensitive match.
   *
   *  Never a fuzzy guess — the same rule as the material picker on the library page. Two
   *  assemblies whose names differ only by case is a library problem to fix in the library, not
   *  something to resolve by picking one of them here. */
  function assemblyByName(text) {
    var want = String(text == null ? "" : text).trim();
    if (!want) return null;
    var i;
    for (i = 0; i < ASMS.length; i++) {
      if (String(ASMS[i].name == null ? "" : ASMS[i].name) === want) return ASMS[i];
    }
    var lc = want.toLowerCase();
    var hits = [];
    for (i = 0; i < ASMS.length; i++) {
      if (String(ASMS[i].name == null ? "" : ASMS[i].name).toLowerCase() === lc) hits.push(ASMS[i]);
    }
    return hits.length === 1 ? hits[0] : null;
  }

  /** setMaterial's own rule, lifted out so the merged picker can ask the question without
   *  writing to a row: an exact, case-insensitive name match against the library's items.
   *
   *  Deliberately NOT assemblyByName's two-pass rule. An assembly resolves on an exact hit first
   *  and only then on a unique case-insensitive one, because two assemblies differing by case is
   *  a library problem this page must not resolve by choosing. Items never had that rule and
   *  inventing it here would change what setMaterial does. */
  function itemByName(text) {
    var want = String(text == null ? "" : text).trim().toLowerCase();
    if (!want) return null;
    for (var i = 0; i < ITEMS.length; i++) {
      // DYE, THE JOINT FILLER KIT AND REMOVE-EXISTING ARE NEVER A TAKEOFF ROW. Each is already
      // owned by its own condition card (CONDITION_CARDS below); a row resolved to one of them by
      // its exact name would charge the same line twice. renderDatalist leaves them out of the list, and
      // this is the half that also holds when somebody types the name out in full.
      if (RESERVED_ITEM_IDS.indexOf(ITEMS[i].id) !== -1) continue;
      if (String(ITEMS[i].name == null ? "" : ITEMS[i].name).trim().toLowerCase() === want) {
        return ITEMS[i];
      }
    }
    return null;
  }

  /** What the library has under this name: an assembly, an item, both, or neither.
   *
   *  BOTH IS REAL, not a hypothetical. "Grout Compound - Test" and "Plastic - Test" each exist as
   *  an item AND an assembly on production today, with different ids and the same name. Whoever
   *  asks this question has to handle that answer; nothing here picks one. */
  function lineMatches(text) {
    return { asm: assemblyByName(text), item: itemByName(text) };
  }

  /** What one takeoff row costs: the library's own price for that assembly at that measurement.
   *  null when the row has no assembly picked yet — which is not an error, just unfinished. */
  /** A takeoff row is EITHER an assembly or a single material, and this is where that forks.
   *
   *  Hanz asked for material rows because not everything an estimate buys is a system. A pallet of
   *  patch, a box of blades, one drum of densifier: making somebody build a one-line assembly to
   *  put a single product on a bid is ceremony, and the assembly it produces is a system that does
   *  not exist.
   *
   *  A MATERIAL ROW IS ONE `priceLine` CALL, not a new engine. That is the whole reason this fits:
   *  library-core already prices one line against an area, applying coverage, waste and roundup,
   *  and an assembly is nothing more than a list of those. So a material row takes the same path a
   *  line inside an assembly takes, and cannot drift from it.
   *
   *  COVERAGE IS TYPED ON THE ROW as THIS ESTIMATE'S OWN OVERRIDE, applied here in the page, not
   *  inside priceLine -- the library rule (2026-09-22) moved coverage onto the material, so
   *  priceLine itself no longer reads a line's coverage at all. Hanz, 2026-09-30: keep the box,
   *  because the same product is used at different coverages on different jobs, but the override
   *  is a per-job fact about THIS estimate, not a second source of truth for the material -- it is
   *  never written back onto the item (see priceMaterialRow). Blank still falls back to the
   *  item's own default, same as before.
   *
   *  The return is shaped like priceAssembly's so every caller -- rowCost, materialTotal, the
   *  broken-line warning, the per-unit hint -- keeps working without knowing which kind it got.
   *
   *  THE ROW AS THE SECTION BUYS IT. A section that pools (B.poolsPacks) buys each coat once for the
   *  whole section, so the cost of one row is its share of the pooled purchase (rawRowPrice below prices the
   *  row alone, which is what the pool starts from). `takeoff` is the list the row sits in; any other list,
   *  or a row that is not in it, prices alone as it always did. EVERY reader of a row's price goes through
   *  here -- the cost box, the section's material sum and the save -- so none of them can disagree. */
  function rowPrice(row, takeoff) {
    var list = takeoff || (M && M.takeoff);
    var i = (list instanceof Array && row) ? list.indexOf(row) : -1;
    if (i < 0 || !poolsList(list)) return rawRowPrice(row, takeoff);
    return pooledRows(list)[i];
  }

  /** Does the section that owns this takeoff list pool? Found by identity: the root's own list, or one of the
   *  sections' under `tabs`. A list no section owns does not. */
  function poolsList(list) {
    if (!ROOT) return false;
    if (ROOT.takeoff === list) return B.poolsPacks(ROOT);
    var tabs = ROOT.tabs;
    if (!tabs || typeof tabs !== "object") return false;
    return Object.keys(tabs).some(function (k) { return !!tabs[k] && tabs[k].takeoff === list && B.poolsPacks(tabs[k]); });
  }

  /** THE SECTION THAT OWNS A TAKEOFF LIST, found by identity as poolsList finds it: the root for the root's own list,
   *  one of the sections under `tabs` for theirs, or null for a list no section owns. */
  function sectionOfList(list) {
    if (!ROOT || !(list instanceof Array)) return null;
    if (ROOT.takeoff === list) return ROOT;
    var tabs = ROOT.tabs;
    if (!tabs || typeof tabs !== "object") return null;
    var keys = Object.keys(tabs);
    for (var i = 0; i < keys.length; i++) if (tabs[keys[i]] && tabs[keys[i]].takeoff === list) return tabs[keys[i]];
    return null;
  }

  /** THE LIBRARY AS THE SECTION THAT OWNS `takeoff` BUYS IT (Hanz, 2026-10-16): ITEMS with that section's supplier
   *  discounts applied (library-core's itemsForBid; the boxes are on the Review step). Every
   *  material price on this page is read off the list this returns, so a discount reaches the row cost boxes, the
   *  pooled coats, the cove, the Gyp area rows and the section's material sum alike. ITEMS itself when the section
   *  typed nothing, which is every bid saved before the boxes existed. Kept until ITEMS or the boxes change. */
  var itemsForCache = { items: null, key: "", out: null };
  function itemsFor(takeoff) {
    var sec = sectionOfList(takeoff || (M && M.takeoff));
    var adj = sec ? B.materialAdjust(sec.adjust) : null;
    if (!adj || !Object.keys(adj.discounts).length) return ITEMS;
    var key = JSON.stringify(adj);
    if (itemsForCache.items !== ITEMS || itemsForCache.key !== key) {
      itemsForCache = { items: ITEMS, key: key, out: L.itemsForBid(ITEMS, adj) };
    }
    return itemsForCache.out;
  }

  /** Every row of a pooling takeoff priced as one purchase: library-core's pricePool over each row priced
   *  alone. An OFF row buys nothing and takes no share; Dye and Joint Filler are never pooled. Index for
   *  index with `list`. */
  function pooledRows(list) {
    var alone = list.map(function (r) { return rawRowPrice(r, list); });
    var on = list.map(function (r) { return B.rowOn(r); });
    var pooled = L.pricePool(alone, { on: on, skip: RESERVED_ITEM_IDS });
    // a cove on two areas is one length, priced once (the library's pool has no item to add up for it)
    return E.poolCoves(pooled, list, { items: itemsFor(list), quartz: E.systemOneIsQuartz(list), on: on });
  }

  function rawRowPrice(row, takeoff) {
    var r = row || {};
    var items = itemsFor(takeoff);
    if (r.item_id) return priceMaterialRow(r, items);
    var asm = asmById(r.assembly_id);
    if (!asm) return null;
    // A COVE IS PRICED BY THE SHEET'S OWN FORMULA, NOT BY A LIBRARY LINE (js/epoxy-takeoff.js): it rounds twice,
    // and its aggregate follows System 1, the first system of the takeoff this row sits in. `takeoff` is that
    // list, and it is the one on show unless a caller prices another section's.
    if (E.coveVariant(asm.id)) {
      return E.priceCoveRow(asm.id, B.num(r.measurement),
        { items: items, quartz: E.systemOneIsQuartz(takeoff || M.takeoff) });
    }
    // A GYP AREA ROW IS THE GYPSUM OF THAT AREA at the section's thickness and mix (js/gyp-takeoff.js), not a library
    // line: a bag's yield depends on the thickness, which the library cannot say. A takeoff that is not a Gyp
    // section's (an area assembly picked into a Polish bid) is priced as any assembly is.
    if (G && G.bucketOfAssembly(asm.id)) {
      var gyp = gypEntryOf(takeoff || M.takeoff);
      if (gyp) return G.priceAreaRow(asm.id, B.num(r.measurement),
        { items: items, tab: gyp.sheet, settings: gyp.section.gyp });
    }
    return priceAssemblyRow(asm, r, B.num(r.measurement), items);
  }

  /** `items` with ONE item's coverage replaced, as a copy. The library's own rows are never
   *  mutated: a coverage typed on a bid is that bid's fact, not a second source for the material.
   *  Anything that is not a positive number leaves `items` as it came, so a blank box falls back
   *  to the library value exactly as before. */
  function itemsWithCoverage(items, itemId, cov) {
    if (!(cov > 0)) return items;
    return items.map(function (it) {
      return it && it.id === itemId ? Object.assign({}, it, { coverage: cov }) : it;
    });
  }

  /** An assembly row priced with THIS BID'S coverage for any of its lines (`row.line_cov`, keyed
   *  by the line's position because one material can sit on two lines at two coverages).
   *
   *  The override rides on a one-line SWAP of the real item under a throwaway id, so the same
   *  priceLine / priceAssembly that every other number on the page goes through does the
   *  arithmetic; there is no second pricing path to drift. With nothing typed this is exactly
   *  L.priceAssembly(asm, ITEMS, area), which is what every row saved before this existed gets. */
  function priceAssemblyRow(asm, row, area, base) {
    // `base` is the library as this row's section buys it (itemsFor); a caller that has none prices off ITEMS.
    var lib = base || ITEMS;
    var lc = (row && row.line_cov && typeof row.line_cov === "object") ? row.line_cov : null;
    var lines = (asm && asm.lines) || [];
    if (!lc) return L.priceAssembly(asm, lib, area);
    var items = lib, any = false;
    var swapped = lines.map(function (ln, j) {
      var cov = B.num(lc[j]);
      var id = ln && (ln.item_id || ln.item);
      if (!(cov > 0) || !id) return ln;
      var real = L.findItem(lib, id);
      if (!real) return ln;
      any = true;
      var tmp = "__cov" + j;
      // `pool_of` keeps the typed-over copy the same material for the section's pool (library-core pricePool)
      items = items.concat([Object.assign({}, real, { id: tmp, coverage: cov, pool_of: real.id })]);
      return Object.assign({}, ln, { item_id: tmp, item: undefined });
    });
    if (!any) return L.priceAssembly(asm, lib, area);
    return L.priceAssembly(Object.assign({}, asm, { lines: swapped }), items, area);
  }

  /** One material, priced as priceAssembly would have priced a one-line assembly containing it.
   *
   *  `broken_lines` follows library-core's own rule rather than inventing a second one: an
   *  unfilled row is work not started, not work gone wrong, so `no_item` is not a fault. Getting
   *  that wrong would put "1 line cannot price yet" under every row the moment it is added. */
  function priceMaterialRow(r, base) {
    var area = B.num(r.measurement);
    // THE OVERRIDE LIVES HERE, not inside priceLine: waste and roundup have no box on this row and
    // come from the material either way. A typed coverage prices against a ONE-ITEM SWAP of the
    // real item -- coverage replaced, everything else (cost, pack size) untouched -- so the item
    // in the library is never mutated. Blank r.coverage leaves `items` as ITEMS, so priceLine
    // falls back to the material's own coverage exactly as it does for every assembly line.
    // `base` is the library as this row's section buys it (itemsFor); a caller that has none prices off ITEMS.
    var lib = base || ITEMS;
    var items = lib;
    var cov = B.num(r.coverage);
    // TRUTHY, NOT !== null: B.num returns 0 for "", null and undefined alike (see
    // bid-model.js), which is exactly how covHint/covPlaceholder already tell "nothing
    // typed" from a real figure. `!== null` would treat every blank row as coverage 0 and price it
    // as broken (no_coverage) the instant it's added, before anyone touches the box.
    if (cov) items = itemsWithCoverage(lib, r.item_id, cov);
    var one = L.priceLine({ item_id: r.item_id }, items, area);
    var priced = one.ok && one.priced ? 1 : 0;
    var broken = (!one.ok && one.reason !== "no_item") ? 1 : 0;
    var total = priced ? one.cost : 0;
    return {
      rows: [one], total: total, priced_lines: priced, broken_lines: broken,
      per_unit: (area !== null && area > 0 && priced) ? total / area : null
    };
  }

  /** The row's cost as it should READ: a figure only when something was actually priced.
   *
   *  An assembly picked with no measurement yet prices to a perfectly legitimate 0 —
   *  priceAssembly returns {total: 0, priced_lines: 0} — and printing "$0" there tells the
   *  estimator the row is FREE, when the truth is that nobody has said how much of it there is.
   *  That is the state every row sits in for the whole time between picking an assembly and typing
   *  a number, so it is the state most likely to be read.
   *
   *  Both engines already refuse to do this with their own per-unit figures for exactly this
   *  reason (library-core.js's per_unit and bid-model.js's per_sf are null rather than 0),
   *  and the cost box has to agree with them. Same for an assembly whose items cannot price: the
   *  warning line beneath it says why, and "—" is what invites reading it. */
  function rowCost(row) {
    // A row switched OFF shows $0 and prices nothing (the on/off slider): the card stays, grayed.
    if (!B.rowOn(row)) return { text: "$0", empty: true, price: null };
    var p = rowPrice(row);
    if (!p || !p.priced_lines) return { text: "—", empty: true, price: p };
    return { text: moneyAuto(p.total), empty: false, price: p };
  }

  /** What Joint Filler (`key` "joint_filler") or Dye ("dye") comes to over `area`, as if on.
   *
   *  PRICED BY THE MATERIAL RULE, OFF A LIBRARY ROW (2026-09-30). Hanz: "joint filler and die
   *  should be library items so that we are able to edit them as well." Both are reserved
   *  library_items rows now -- `joint-filler-kit` and `dye`, backend/library.py's
   *  RESERVED_ITEM_IDS -- edited on the Items tab like any other material, and priced by the
   *  one priceLine every material row and assembly line already goes through. Coverage, waste
   *  and roundup come off the row, so an admin who changes the kit's coverage changes how many
   *  kits a job buys. The seeded rows (JF: coverage 3500, waste 0, roundup on, $500; dye:
   *  coverage 1, waste 0, no roundup, $0.14) price to the cent what bid-model.js's
   *  jointFillerCost/dyeCost did.
   *
   *  THE ROW IS NOT ALWAYS THERE. On a database the seed has not reached, or a row that cannot
   *  price (its cost or coverage blanked), this falls back to jointFillerCost/dyeCost -- the
   *  formulas the tool shipped with, untouched -- rather than pricing the line at $0 or breaking
   *  the page. `library` says which of the two answered.
   *
   *  THE IDS ARE THE TABLE'S (T.itemIdOf: js/work-types.js), not read off CONDITION_CARDS: adopt() runs
   *  at parse time, above that declaration, and nothing this reaches may depend on a var assigned
   *  below it. T is bound at the top of this file for that reason.
   *
   *  `qty` is what the card's Measurement shows: kits for joint filler, the polished area in SF
   *  for dye (the area is what dye is spread across, whatever its row's coverage says). */
  function condLine(key, area) {
    var id = T.itemIdOf(key);
    // THIS BID'S COVERAGE for the line, if one was typed (M.cond_cov, set from the card's Coverage
    // box). Blank leaves ITEMS alone, so the library's own figure -- and every bid saved before the
    // box existed -- prices exactly as it did.
    var p = L.priceLine({ item_id: id }, itemsWithCoverage(ITEMS, id, condCovTyped(key)), area);
    if (p.ok) {
      // DYE IS TWO COATS, Kyle's rows 25 and 26 (B.DYE_COATS); the row prices ONE of them. The
      // fallback's dyeCost already charges both.
      var cost = (p.priced ? p.cost : 0) * (key === "dye" ? B.DYE_COATS : 1);
      return { library: true, line: p, cost: cost,
               qty: key === "dye" ? B.num(area) : (p.priced ? p.qty : 0) };
    }
    if (key === "dye") {
      return { library: false, line: null, cost: B.dyeCost(area, true), qty: B.num(area) };
    }
    var jf = B.jointFillerCost(area, true);
    return { library: false, line: null, cost: jf, qty: jf / B.RATES.JOINT_FILLER_KIT_COST };
  }

  /** What this page priced Dye and Joint Filler with, for Kyle's workbook.
   *
   *  Handed to B.conditionCellWrites on every save so the downloaded .xlsx quotes the same two
   *  lines the bid does (bid-model.js's libraryLineWrites). A key is LEFT OUT when its row
   *  is not in the library -- that writes nothing, so a database the seed has not reached keeps
   *  the template's cells -- and is null when the row is there but cannot price, which is when
   *  condLine falls back to the shipped formula and the cells get the shipped figures. The
   *  library loads after the first paint, so an early save with ITEMS still empty writes nothing
   *  either. */
  function conditionLibrary() {
    var out = {};
    ["dye", "joint_filler"].forEach(function (key) {
      if (!L.findItem(ITEMS, T.itemIdOf(key))) return;
      var ln = condLine(key, 0).line;
      out[key] = ln ? { unit_price: ln.unit_price, coverage: ln.coverage,
                        waste_pct: ln.waste_pct, roundup: ln.roundup, buy_qty: ln.buy_qty }
                    : null;
    });
    return out;
  }

  /** The raw material of the section on show: the root's (rootMaterial) or another section's. */
  function materialTotal() {
    if (activeTab === B.ROOT_TAB) return rootMaterial();
    var e = openEntry();
    if (!e) return 0;
    var m = sectionMaterial(e);
    // A section that cannot be priced (a Seal option whose takeoff did not load) shows no material, not NaN.
    if (m && typeof m === "object" && m.material === undefined && typeof m.unpriceable === "string" && m.gyp === undefined) return 0;
    // A Gyp section's material comes as the engine's four figures (gypsum, extras, sand, sound mat), not a sum.
    if (m && typeof m === "object" && m.material === undefined) return m.gyp + m.extras + m.sand + m.soundMat;
    return m.material;
  }

  /** The raw material of the ROOT (Polish) section, which is what bid() prices. */
  function rootMaterial() {
    return polishMaterial(ROOT.takeoff);
  }

  /** The raw material of ONE Polish section's takeoff, the root's or a copy's or a sheet added to the bid: what rootMaterial
   *  has always answered for the root, so every Polish section is bought the same way (B.polishBid prices them alike). */
  function polishMaterial(takeoff) {
    var sum = 0;
    takeoff.forEach(function (r) {
      // OFF ROWS ARE SKIPPED HERE, in the raw sum, so the chain rounds only what the bid really
      // buys (D31 is ROUNDUP of the sum -- zeroing a row after that would drift the total).
      if (!B.rowOn(r)) return;
      var p = rowPrice(r, takeoff);
      if (p) sum += p.total;
    });
    // Dye and Joint Filler are keyed on the polished area (Polish!E25/E29), not on a row's own
    // measurement. `area` is the SAME B.takeoffSf(takeoff) that the section's bid uses for the
    // sheet's SF, so the Material total and the price-per-SF divisor can never disagree about
    // what "the area" is. Each prices off its reserved library row, or off the shipped formula
    // when that row is not there -- see condLine. Off means nothing, as it always has. The two
    // are the JOB's conditions, so they are charged on every Polish section.
    var area = B.takeoffSf(takeoff);
    if (ROOT.conditions.dye) sum += condLine("dye", area).cost;
    if (ROOT.conditions.joint_filler) sum += condLine("joint_filler", area).cost;
    // The patch line (Polish!D17) is NOT in this sum: it goes to the chain on its own (polishMaterialIn), and the
    // engine adds it inside D31's round-up only on a profile that carries it (the `polishPatch` quirk).
    return sum;
  }

  /** What a Polish section's chain is handed: the raw material and, separately, the patch line (Polish!D17). The
   *  engine takes the patch into the material only on a profile that carries it (polish-rev3 on), so a section saved
   *  before 2026-10-16 prices exactly as it did whatever is passed here. */
  function polishMaterialIn(takeoff) {
    return { material: polishMaterial(takeoff), patch: polishPatchCost(takeoff) };
  }

  /** What the patch line comes to for the Polish section that owns `takeoff`, or 0 when its profile has no patch line
   *  or the Seal module (which prices it) did not load. */
  function polishPatchCost(takeoff) {
    if (!SL || !polishPatchOnList(takeoff)) return 0;
    return SL.patchCost(ITEMS, B.takeoffSf(takeoff), jobIsReno());
  }

  /** Does the Polish section that owns `takeoff` carry the patch line? Found by identity, as sectionOfList finds it. */
  function polishPatchOnList(takeoff) {
    if (!ROOT || !(takeoff instanceof Array)) return false;
    if (ROOT.takeoff === takeoff) return B.polishPatchOn(ROOT, B.ROOT_TAB);
    var tabs = ROOT.tabs;
    if (!tabs || typeof tabs !== "object") return false;
    var keys = Object.keys(tabs);
    for (var i = 0; i < keys.length; i++) {
      if (tabs[keys[i]] && tabs[keys[i]].takeoff === takeoff) return B.polishPatchOn(ROOT, keys[i]);
    }
    return false;
  }

  /** This project's REAL remodel-tax rate, or 0 when nobody has picked a county.
   *
   *  Read off the draft under the same two keys the live estimate screen writes:
   *  `remodel_rate_override` (the % an estimator typed off the state's site for this address)
   *  first, then `county_remodel_rate` (its county picker, and the beta intake's). Both, in
   *  that order, so a project prices the same whichever screen answered the question. Kyle's
   *  sheet hardcodes 10% here; that is not a real rate anywhere, and Hanz's instruction on
   *  2026-08-18 was to use the actual one. When this returns 0 the engine falls back to the
   *  Kansas state rate rather than to 10%. */
  function remodelRate() {
    // A rate TYPED on the live estimate screen wins over the county table, for the same
    // reason it does there: the estimator read it off the state's own site for this
    // address, and a county is coarser than an address. Without this the beta would show
    // one rate while the workbook it generates carried another -- two sources of truth for
    // one number, which is the defect the duplicate city tables already taught us to
    // refuse. An explicit 0 is a real answer here (no remodel tax at this address) and is
    // deliberately allowed through rather than treated as unset.
    var r = state.remodel_rate_override;
    if (r === null || r === undefined || r === "") r = state.county_remodel_rate;
    if (r !== null && r !== undefined && r !== "") return B.num(r);
    // A county IS chosen but carries no remodel rate — that is Missouri, where remodel labor is
    // generally exempt. Return a definite 0, not null: null would stand the Kansas state rate up
    // and charge a Missouri job a Kansas tax.
    if (state.county) return 0;
    return null;                        // nobody has picked a county yet
  }

  /** Is this job a renovation? Only a Seal option reads it (the sheet's patch price is one figure for New and another for Reno). The
   *  v2 estimate model does not carry Renovation (js/work-types.js: `model: false`), so it is read off the draft the
   *  way the intake leaves it: the cells the condition writes (T.condition("reno").cells), the first one that holds
   *  an answer deciding. A draft that never answered it is a new floor, the condition's own default. */
  function jobIsReno() {
    var cells = (state && state.cell_values && typeof state.cell_values === "object") ? state.cell_values : {};
    var list = T.condition("reno").cells;
    for (var i = 0; i < list.length; i++) {
      var v = Object.prototype.hasOwnProperty.call(cells, list[i]) ? cells[list[i]] : undefined;
      if (v === "Reno" || v === "New") return v === "Reno";
    }
    return false;
  }

  /** The ROOT (Polish) section's bid, recomputed from the model. Cheap enough to call on every keystroke.
   *  It reads ROOT, never M: M is whichever section is on show. */
  function bid() {
    // B.polishBid prices every Polish section the same way, the root and a copy under `tabs` alike (the model's own
    // markupChain call with the section's rows, travel by its role, and tooling on a rev 2 profile). The page hands it the
    // library's raw material, which is the one thing the model cannot know.
    return B.polishBid(ROOT, B.ROOT_TAB, { material: function () { return polishMaterialIn(ROOT.takeoff); },
                                           remodel_rate: remodelRate() });
  }

  /** The raw material of a section that is not the root: its takeoff rows priced from the library, the rows
   *  that are on. Dye and Joint Filler are Polish's conditions and stay with the root (rootMaterial).
   *
   *  AN EPOXY SECTION ADDS WHAT THE SHEET DOES BEFORE ITS CHAIN (js/epoxy-takeoff.js): the patch, the cove (a
   *  cove row is priced by the sheet's own formula, not by a library line) and the tooling, which the chain takes
   *  as its own input. It answers { material, tooling }, the engine's material inputs. */
  function sectionMaterial(entry) {
    var takeoff = entry.section.takeoff || [];
    // A POLISH SECTION UNDER `tabs` (a copy of the Polish sheet, or a Polish sheet added to the bid) is bought like the root.
    if (entry.role === "polish") return polishMaterialIn(takeoff);
    if (entry.role === "epoxy") {
      var r = E.sectionMaterial(takeoff, {
        items: itemsFor(takeoff), sf: B.takeoffSf(takeoff), poolCoves: B.poolsPacks(entry.section),
        rowPrice: function (row) { return rowPrice(row, takeoff); }
      });
      return { material: r.material, tooling: r.tooling };
    }
    // A SEAL OPTION ADDS WHAT THE SEAL SHEET DOES BEFORE ITS CHAIN (js/seal-takeoff.js): the patch (a price a square
    // foot of the whole area, the renovation price when the job is a renovation) and the tooling, which the chain
    // takes as its own input. Without the module no Seal option is priced, and it says so: a plain sum would leave
    // out the patch and the tooling and still call the option priceable.
    if (entry.role === "seal") {
      if (!SL) return { unpriceable: "the Seal takeoff did not load, so this option cannot be priced. Reload the page." };
      var sr = SL.sectionMaterial(takeoff, {
        items: itemsFor(takeoff), sf: B.takeoffSf(takeoff), reno: jobIsReno(),
        rowPrice: function (row) { return rowPrice(row, takeoff); }
      });
      return { material: sr.material, tooling: sr.tooling };
    }
    // A GYP SECTION'S MATERIAL IS SPLIT FOUR WAYS AND ITS ROLLS COUNTED (js/gyp-takeoff.js): the gypsum bags by
    // thickness, the extras (primer, ISO strip, tape, and any other row), the sand worked out from the fractional
    // bags, and the sound mat with its rolls, which decide whether the mat ships free. Without the module no Gyp
    // section is priced: a plain sum is refused by priceSection, never charged as the gypsum alone.
    if (entry.role === "gyp" && G) {
      var g = G.sectionMaterial(takeoff, entry.section.gyp, entry.sheet, {
        items: itemsFor(takeoff), rowPrice: function (row) { return rowPrice(row, takeoff); }
      });
      var figures = { gyp: g.gyp, extras: g.extras, sand: g.sand, soundMat: g.soundMat,
                      soundMatRolls: g.soundMatRolls, truckload: g.truckload, tooling: g.tooling };
      if (g.unpriceable) figures.unpriceable = g.unpriceable;
      return figures;
    }
    var sum = 0;
    takeoff.forEach(function (r) {
      if (!B.rowOn(r)) return;
      var p = rowPrice(r, takeoff);
      if (p) sum += p.total;
    });
    return sum;
  }

  /** The entry of the section on show (never the root's: materialTotal answers that one itself). */
  function openEntry() {
    try { return B.sectionOf(ROOT, activeTab); } catch (err) { return null; }
  }

  /** The Gyp section whose takeoff is this very list, as B.sectionsOf's entry, or null. A row is priced against the
   *  list it sits in, and that list belongs to one section, which holds the thickness, the mix and the preset. */
  function gypEntryOf(takeoff) {
    try {
      var list = B.sectionsOf(ROOT);
      for (var i = 0; i < list.length; i++) {
        if (list[i].role === "gyp" && list[i].section.takeoff === takeoff) return list[i];
      }
    } catch (err) { /* a bid whose sections cannot be read has no Gyp section to price against */ }
    return null;
  }

  /** The Gyp section on show, or null. */
  function gypOpen() {
    if (!G || activeTab === B.ROOT_TAB) return null;
    var e = openEntry();
    return e && e.role === "gyp" ? e : null;
  }

  /** The workbook tab a Gyp bid's section is filed under (its preset), or null when the bid has none. */
  function gypTab() {
    try { return B.sheetHeld(ROOT, T.tab("gyp")); } catch (err) { return null; }
  }

  /** The bids of every section but the root, { tabId: bid } (B.priceTabs). {} for a bid with one section,
   *  which reads nothing and costs nothing. */
  function sectionBids() {
    return B.priceTabs(ROOT, { material: sectionMaterial, remodel_rate: remodelRate() });
  }

  /** The bid of the section on show, whichever it is: the root's chain, or the engine's answer for the section.
   *  The Review panel and the repaint read this, so they show the section they are about. */
  function activeBid() {
    if (activeTab === B.ROOT_TAB) return bid();
    var all = sectionBids();
    return Object.prototype.hasOwnProperty.call(all, activeTab) ? all[activeTab] : bid();
  }

  /** What a save is composed from (B.buildSavePatch): the root's bid, the other sections' and the library's
   *  figures for Dye and Joint Filler. */
  function priceCtx() {
    return { bid: bid(), bids: sectionBids(), library: conditionLibrary() };
  }

  /** The patch a save lays over the draft. A bid whose sections cannot be read (a saved `tabs` that is not well
   *  formed) must still SAVE what was typed, so the root is composed on its own and the sections go back as they
   *  were saved, untouched, with the reason on screen; a save that threw would lose the edit. */
  function savePatch(now) {
    try {
      return B.buildSavePatch(ROOT, now, priceCtx());
    } catch (err) {
      say("This bid's other sections cannot be read, so they were saved as they were: " + (err && err.message));
      var rootOnly = Object.assign({}, ROOT);
      delete rootOnly.tabs;
      var patch = B.buildSavePatch(rootOnly, now, { bid: bid(), library: conditionLibrary() });
      if (ROOT.tabs !== undefined) patch.polish_estimate = Object.assign({}, patch.polish_estimate, { tabs: ROOT.tabs });
      return patch;
    }
  }

  // ── saving ──────────────────────────────────────────────────────────────────
  var saveTimer = null;
  // WHAT IS WRITTEN, AND WHY EACH KEY IS THERE, IS B.buildSavePatch'S BUSINESS (bid-model.js).
  // This page and its pagehide flush used to compose the blob by hand in two places, and the two
  // drifted: the flush skipped the condition cells and the measured-floor fallback. Both call it
  // now, so a key can only be added or fixed once. `bid` is the price this page computes (the
  // library lives here), `library` is what it priced Dye and Joint Filler with.
  function saveSoon() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      // DISARMED ONCE IT HAS RUN (2026-10-19, "When I go back from proposal to estimate it doesnt save my values"). The
      // pagehide save below runs only while this timer is pending, and a fired timer left `saveTimer` set, so every exit
      // after the first autosave rewrote the blob from this page's model. An older estimate page leaving (a second tab,
      // or one restored by the browser's Back and reloaded) wrote its old values over the newer ones. polish-intake.js
      // has always cleared it here.
      saveTimer = null;
      var now = TW.getState();
      TW.setState(Object.assign({}, now, savePatch(now)));
    }, 600);
  }

  // Same gap as the intake page's Fault 3: nothing here flushed its own 600ms debounce before
  // navigating away, and shared.js's pagehide net only flushes a timer THIS page armed. A takeoff
  // number typed and then left via the step nav inside that window was silently lost.
  window.addEventListener("pagehide", function () {
    if (!saveTimer) return;
    clearTimeout(saveTimer);
    saveTimer = null;
    var cur = TW.getState();
    TW.setState(Object.assign({}, cur, savePatch(cur)));
    TW.flushState();
  });

  /** Write the derived Guys figure INTO any auto travel row, so the model holds what the screen
   *  shows.
   *
   *  The alternative was leaving `guys` blank and deriving it only at render time, and it splits
   *  the row in two: the box would read 18 while `laborCost` multiplied by an empty string, so
   *  Travel would price at $0 with a number sitting right there in it, `blockers` would read the
   *  row as emptier than it looks, and the draft would save a figure nobody could see. One
   *  assignment on the way through `changed()` keeps the screen, the price, the validation and
   *  the saved blob describing the same row. */
  function syncAutoGuys() {
    // The rule moved into the model (B.syncAutoGuys) so the new-bid seeding can run it between its steps:
    // Lodging and Per Diem count the same man-days while they are on auto (nights = man-days, the way
    // backend/pricing.py counts them), and a Travel row on auto follows the job's crew SIZE (the most guys on any labor
    // line of the base sections), or its own section's lines when the section is an option; an older row follows the man-days.
    B.syncAutoGuys(ROOT);
  }

  /** Is this labor row drive time? Every hours row is, except in a Gyp section, where the crew is priced by the hour
   *  and only the row called travel is the drive. Travel's guys follow the crew's size on a far job (the most guys on any labor
   *  line; a bid saved before 2026-10-12 still on auto follows the man-days instead), it dims on a local job, and its second
   *  box is drive time; a Gyp pour is none of those. */
  function travelLike(r) {
    return !!(r && r.unit === "hours") && (r.id === "travel" || !gypOpen());
  }

  /** Whether an hours-based labor row (Travel) renders dimmed: on a local job, untouched.
   *  Untouched is Guys not typed (blank on a new bid, or still on auto: a bid saved before
   *  2026-10-12, or one the distance sent far and then back under 70 miles) and Hours blank. A
   *  typed Guys or a typed Hours is the estimator saying "we need
   *  this anyway", so either one lifts the dim -- not just Hours, since Guys is the box somebody
   *  is looking at when they start typing.
   *
   *  ONE FUNCTION, used by both the first paint (laborCard) and the live repaint
   *  (repaintNumbers), so the two cannot disagree about a row that is being typed into right now. */
  function laborInert(r) {
    return travelLike(r) && !!(M.conditions || {}).local &&
      (!!r.guys_auto || !B.filledIn(r.guys)) && !B.filledIn(r.days);
  }

  /** One place every edit funnels through, so nothing can change a value without the bid, the
   *  rail and the draft all catching up.
   *
   *  `rerender` false repaints the computed figures in place instead of rebuilding the panel:
   *  rebuilding mid-keystroke moves the caret out of the field being typed in. */
  function changed(rerender) {
    // G2: a "From SF" labor line's untouched Days follow the takeoff -- only when the SF moved in
    // THIS session (followSf is set once the page has opened), so reopening a saved bid moves nothing.
    var sfNow = B.takeoffSf(M.takeoff);
    if (followSf !== null && sfNow !== followSf) {
      followSf = sfNow;
      M.labor = B.followLaborDays(M.labor, sfNow);
    }
    syncAutoGuys();
    paintBid();
    paintRail();
    saveSoon();
    if (rerender) renderPanel(); else repaintNumbers();
  }

  // ── the bid bar ─────────────────────────────────────────────────────────────
  function paintBid() {
    var b = bid();
    $("bidbar").hidden = false;
    paintSections();
    if (sectionList().length > 1) { paintJobBid(); return; }
    $("bid-total").textContent = b.total ? B.money(b.total) : "—";
    $("bid-psf").textContent = (b.per_sf == null ? "" : B.money2(b.per_sf) + " / SF")
      + (b.sf ? " · " + B.fmtSf(b.sf) + " SF" : "");
    var bits = [];
    if (b.material_total) bits.push("Material " + B.money(b.material_total));
    if (b.labor_total) bits.push("Labor " + B.money(b.labor_total));
    $("maths").innerHTML = bits.map(esc).join(' <i>+</i> ');
  }

  // ── more than one section ───────────────────────────────────────────────────
  /** The model's sections, or [] when it has only the root (every bid today, which is why nothing below shows).
   *  A saved `tabs` that is not well formed answers [] and says so; saving still works (savePatch). */
  function sectionList() {
    if (!ROOT.tabs) return [];
    try { return B.sectionsOf(ROOT); } catch (err) {
      say("This bid's other sections cannot be read: " + (err && err.message));
      return [];
    }
  }

  /** Every section's bid, the root's under its own tab id. */
  function allBids() {
    return Object.assign({}, sectionBids(), Object.fromEntries([[B.ROOT_TAB, bid()]]));
  }

  /** Keep the sheet on show one that is part of the bid (an Epoxy job's Polish root is not), then draw the Sheets panel.
   *  The name is the strip's, which this replaced: the strip hid itself for one section, the panel is there on every bid. */
  function paintSections() {
    var live = sectionList().filter(function (e) { return e.kind !== "off"; });
    if (live.length < 2) {
      if (!live.length || live[0].tab !== activeTab) show(live.length ? live[0].tab : B.ROOT_TAB);
    } else if (!live.some(function (e) { return e.tab === activeTab; })) show(live[0].tab);
    paintSheets();
  }

  /** The bar for a bid priced on several sections: the combined base bid (the same figure a save writes as the
   *  lump sum) and each section's own price. No price when a section cannot be priced, never a wrong one. */
  function paintJobBid() {
    var c = null;
    try { c = B.composePricingSnapshot(ROOT, priceCtx()).computed_bid; } catch (err) { c = null; }
    $("bid-total").textContent = c && c.lump_sum ? B.money(c.lump_sum) : "no price";
    $("bid-psf").textContent = (c && c.price_per_sf != null ? B.money2(c.price_per_sf) + " / SF" : "");
    var bids = allBids();
    var live = sectionList().filter(function (e) { return e.kind !== "off"; });
    var say1 = function (e) {
      var b = bids[e.tab];
      return esc(e.label + " " + (b && b.priceable !== false && b.total ? B.money(b.total) : "no price"));
    };
    // The base sections add up to the lump sum; an option is priced beside them and is never part of it.
    var line = live.filter(function (e) { return e.kind !== "option"; }).map(say1).join(' <i>+</i> ');
    var opts = live.filter(function (e) { return e.kind === "option"; }).map(function (e) { return say1(e) + " option"; });
    if (opts.length) line += ' <i>·</i> ' + opts.join(' <i>·</i> ') + ' (not in the lump sum)';
    $("maths").innerHTML = line;
  }

  // ── the Sheets panel (Sheets phase 3) ───────────────────────────────────────
  // Every sheet of the bid, the base bid marked, and what each option does on the proposal, as ONE strip of tabs and the open sheet's
  // bar under it (section#sheets-panel). It took the place of the strip of section buttons and the "+ Add option" bar. The markup is
  // B.sheetsPanelHtml's (js/bid-model.js, pure); this is the page's side of it: the state the panel is in (a base change
  // waiting for its yes, a Delete pressed once, a name being typed), what each control writes, and the repaint.
  //
  // WHAT EACH CONTROL WRITES. The model is the sheets, their kinds and their names (B.copySection, B.addSheet,
  // B.renameSection, B.deleteSection, B.pickBase). The DRAFT is what the proposal reads around it: tab_opts (on the
  // proposal, Total or Add / Deduct, the words), and on a base change work_type and base_tab_id with the Proposal step's own
  // edited lines moved to the new base (TWPrice.applyBasePick). The model functions answer the draft's side as a `patch`.
  var sheetsUi = {
    confirm: null,      // { row, ids }: a base change the estimator has asked for and not yet confirmed
    armed: null,        // the sheet whose Delete has been pressed once
    renaming: null,     // the sheet being renamed, with what is typed so far and the reason it was refused
    draft: "", error: "",
    notice: null,       // { at, text }: why Copy or Add sheet was refused, drawn beside the control (at: the sheet, or "add")
    descOpen: {},       // the sheets whose description box is open
    pick: false,        // the "Add a sheet" choices are showing
    busy: false,        // a sheet is being added (the library is being read)
    focus: null         // the control to put the caret back on after the next repaint (data-sh-key)
  };
  var lastSheets = null;     // the bar markup last drawn, so a keystroke elsewhere redraws nothing that did not change

  /** The area a new sheet starts on: what the job's base section measures (the section that carries the job's travel
   *  is the first base), 0 when nothing is measured yet. */
  function optionStartSf() {
    try { return B.takeoffSf(B.sectionOf(ROOT, B.travelCarrier(ROOT)).section.takeoff); } catch (err) { return 0; }
  }

  /** What the option prints now, for the grey text in an open description box: the system's own words, off the priced
   *  tabs of a save. "" when they cannot be worked out, which leaves the box with no grey text. */
  function sysDescOf(tab) {
    try {
      var tabs = B.composePricingSnapshot(ROOT, priceCtx()).priced_tabs || [];
      for (var i = 0; i < tabs.length; i++) if (tabs[i].id === tab) return String(tabs[i].system_desc || "");
    } catch (err) { /* nothing to show */ }
    return "";
  }

  /** Everything the panel is drawn from. The draft's tab_opts are read only when the bid has more than one sheet: they
   *  are what the option controls show, a bid with one sheet has none, and a read parses the whole draft. */
  function sheetsView() {
    var multi = !!ROOT.tabs;
    // A bid whose other sheets cannot be read still prices its first sheet (the panel says so and offers nothing else).
    var bids;
    try { bids = allBids(); } catch (err) { bids = Object.fromEntries([[B.ROOT_TAB, bid()]]); }
    return {
      open: activeTab, bids: bids, opts: multi ? TW.getState().tab_opts : undefined, sf: optionStartSf(), icon: icon,
      confirm: sheetsUi.confirm, armed: sheetsUi.armed, renaming: sheetsUi.renaming, draft: sheetsUi.draft,
      error: sheetsUi.error, notice: sheetsUi.notice, descOpen: sheetsUi.descOpen, pick: sheetsUi.pick, busy: sheetsUi.busy, sysDesc: sysDescOf
    };
  }

  /** The control the caret is on, by its data-sh-key, when it is inside the panel; null otherwise. */
  function sheetsFocusKey(el) {
    var ae = document.activeElement;
    if (!ae || !ae.getAttribute || typeof el.contains !== "function" || !el.contains(ae)) return null;
    return ae.getAttribute("data-sh-key");
  }

  /** Put the caret on the control with this data-sh-key. A repaint rebuilds every control, and a rebuilt control has no
   *  caret: without this a keyboard user who presses a switch is dropped back to the top of the page. */
  function focusSheetsKey(key) {
    var el = $("sheets-panel");
    if (!el || !key) return;
    var all = el.querySelectorAll("[data-sh-key]");
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute("data-sh-key") !== key) continue;
      // preventScroll: the bar is in the sticky head and html's scroll-padding-top is the head's height, so a plain focus() on a control IN the head
      // scrolls the page up to put it below the head (a click on Add sheet, Rename or a tab threw a scrolled page back to the top). The control the
      // caret goes back to is on screen already: it is the one that was pressed.
      if (all[i].focus) all[i].focus({ preventScroll: true });
      // A box gets the caret at the end of what is in it, never the start.
      try { if (all[i].setSelectionRange && all[i].value) all[i].setSelectionRange(all[i].value.length, all[i].value.length); } catch (err) { /* a switch has none */ }
      return;
    }
  }

  // ── the sticky head's height ────────────────────────────────────────────────
  // THE TOP BAR AND THE SHEET BAR ARE ONE STICKY BLOCK (#v2head in polish-estimate.html), and a field that is focused or scrolled to must
  // not stop behind it. The page's CSS gives the html element a scroll-padding-top of the block's height (--v2head-h) and puts it back to
  // nothing where the block is static. The height is not a constant (a long bid wraps the steps, and the Add menu and the description box
  // open inside it), so it is read off the block: a ResizeObserver says when it changes, and a browser without one is told by the two
  // things that change it, a repaint of the bar (paintSheets) and a resize of the window. A page run without a layout (the harnesses'
  // stand-in DOM) has no box to measure, and nothing happens.
  var headObserver = null;
  function syncHeadHeight() {
    var head = $("v2head"), root = document.documentElement;
    if (!head || !root || !root.style || typeof root.style.setProperty !== "function" || typeof head.getBoundingClientRect !== "function") return;
    var box = head.getBoundingClientRect();
    var h = box && typeof box.height === "number" ? Math.ceil(box.height) : 0;
    if (h > 0) root.style.setProperty("--v2head-h", h + "px");
  }
  function watchHead() {
    var head = $("v2head"), RO = window.ResizeObserver;
    if (head && typeof RO === "function") {
      try { headObserver = new RO(syncHeadHeight); headObserver.observe(head); } catch (err) { headObserver = null; }
    }
    if (!headObserver) window.addEventListener("resize", syncHeadHeight);
    syncHeadHeight();
  }
  watchHead();

  /** Draw the sheet bar (the tabs and the open sheet's controls). Redrawn only when what it says changed.
   *
   *  THE STRIP KEEPS ITS PLACE. A repaint rebuilds the strip, and a rebuilt strip starts scrolled to the far left: on a phone,
   *  or a bid with many tabs, every price change would have thrown the open tab out of view. So the strip's scrollLeft is
   *  read before the rebuild and put back after it, and only a CHANGE of the open tab scrolls to it (stripReveal). */
  var lastOpenSheet = null;
  function paintSheets() {
    var el = $("sheets-panel");
    if (!el) return;
    var view = sheetsView();
    var html = B.sheetsPanelHtml(ROOT, view);
    var want = sheetsUi.focus;
    sheetsUi.focus = null;
    var openChanged = view.open !== lastOpenSheet;
    lastOpenSheet = view.open;
    var drew = html !== lastSheets;
    if (drew) {
      var keep = want || sheetsFocusKey(el);
      var oldStrip = el.querySelector("[data-sh-strip]");
      var left = oldStrip && typeof oldStrip.scrollLeft === "number" ? oldStrip.scrollLeft : 0;
      el.innerHTML = html;
      lastSheets = html;
      want = keep;
      var newStrip = el.querySelector("[data-sh-strip]");
      if (newStrip && left) newStrip.scrollLeft = left;
    }
    // HIDDEN UNTIL DRAWN. The bar sits in the sticky head, above the page heading, while the page keeps everything behind "Loading the item
    // library" until init has what it needs (#main is hidden the same way). So it is shown the first time it has been drawn, never as an
    // empty bar that then jumps open and pushes the page down. Before the strip is scrolled to the open tab below: a hidden strip has no layout.
    var shown = el.hidden;
    if (shown) el.hidden = false;
    if (openChanged) stripReveal(el.querySelector("[data-sh-strip]"), el.querySelector("[data-sh-cur]"));
    if (want) focusSheetsKey(want);
    if (!headObserver && (drew || shown)) syncHeadHeight();
  }

  /** Scroll the strip, and only the strip, just far enough to show `tab` (inline: nearest, with no page jump: scrollIntoView
   *  can move the page too). A tab already in view leaves the strip where it is. Needs layout, so it does nothing when
   *  either node cannot say where it is. */
  function stripReveal(strip, tab) {
    if (!strip || !tab || typeof tab.offsetLeft !== "number" || typeof strip.clientWidth !== "number") return;
    var start = tab.offsetLeft - (strip.offsetLeft || 0), end = start + (tab.offsetWidth || 0), pad = 8;
    var from = strip.scrollLeft || 0;
    if (start < from) strip.scrollLeft = Math.max(0, start - pad);
    else if (end > from + strip.clientWidth) strip.scrollLeft = end - strip.clientWidth + pad;
  }

  // The strip's tabs by keyboard: Left and Right move the caret to the neighbouring tab (Home and End to the first and the
  // last), and Enter or Space opens the one it is on, as a button does. The tabs are real <button>s, so that part is free.
  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (!t || !t.closest || !t.getAttribute || t.getAttribute("data-section-tab") === null) return;
    var k = e.key;
    if (k !== "ArrowLeft" && k !== "ArrowRight" && k !== "Home" && k !== "End") return;
    var panel = $("sheets-panel");
    var tabs = panel ? Array.prototype.slice.call(panel.querySelectorAll("[data-section-tab]")) : [];
    var at = tabs.indexOf(t);
    if (at < 0 || tabs.length < 2) return;
    var to = k === "Home" ? 0 : k === "End" ? tabs.length - 1
      : (at + (k === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    e.preventDefault();
    if (tabs[to] && tabs[to].focus) {
      // preventScroll for the reason focusSheetsKey gives. The strip is scrolled to the tab by hand, which moves the strip and nothing else.
      tabs[to].focus({ preventScroll: true });
      stripReveal(panel.querySelector("[data-sh-strip]"), typeof tabs[to].closest === "function" ? tabs[to].closest("li") : null);
    }
  });

  /** Kept under its old name: the harnesses (and anything else that asked the page to redraw "the option bar") still do. */
  function paintOptionBar() { paintSheets(); }

  /** Back to the panel's resting state: nothing waiting to be confirmed, armed or being renamed. */
  function resetSheetsUi() {
    sheetsUi.confirm = null; sheetsUi.armed = null; sheetsUi.renaming = null; sheetsUi.error = ""; sheetsUi.notice = null;
  }

  /** The model was replaced (a copy, an added sheet, a rename, a base change, a delete): the panels' view of it is made
   *  again, and the bid, the rail and the draft catch up. */
  function sheetsChanged(tab, focusKey) {
    show(tab);
    syncAutoGuys();
    sheetsUi.focus = focusKey || null;
    saveSoon();
    paintBid();
    paintRail();
    renderPanel();
  }

  /** ADD A SHEET: any type the tool prices (B.sheetsToAdd), as an option that starts ON the proposal. The library is read first
   *  (the labor lines filed under the sheet's work type and the calculator's modes) and the model is read AFTER it answers, so
   *  a figure typed while it was loading is kept. Only the new sheet is added; nothing typed on any other is touched. */
  async function addSheetPress(sheet) {
    if (sheetsUi.busy) return;
    sheetsUi.busy = true;
    paintSheets();
    try {
      var rules = await loadMarkupRules();
      var laborRows = B.withCrewFallback(await loadLaborDefaults());
      var calcRows = B.withCrewCalcFallback(await loadLaborCalc());
      var sf = optionStartSf();
      var made = B.addSheet(ROOT, sheet, {
        rules: rules, laborRows: laborRows, laborRate: LABOR_RATE, calcRows: calcRows,
        asms: ASMS, items: ITEMS, reserved: RESERVED_ITEM_IDS,
        cellValues: state.cell_values, split: T.isSplit(state), state: TW.getState(),
        sf: Object.fromEntries([[sheet, [sf, "", ""]]]), lf: {},
        takeoffRows: function (entry, sfs) {
          if (entry.role === "seal" && SL) return SL.seedTakeoff(entry.sheet, ASMS, sfs[0]);
          if (entry.role === "gyp" && G) return G.seedTakeoff(ASMS, sfs[0], sfs[1], sfs[2]);
          return null;
        }
      });
      ROOT = made.model;
      if (Object.keys(made.patch).length) TW.setState(made.patch);
      resetSheetsUi();
      sheetsUi.pick = false;
      show(made.id);
      followSf = B.takeoffSf(B.sectionOf(ROOT, made.id).section.takeoff);
      sheetsChanged(made.id, made.id + "|open");
    } catch (err) {
      // In the panel, under the Add sheet button: the page's own alert is at the top of the page, out of sight once it has scrolled.
      sheetsUi.notice = { at: "add", text: "The sheet could not be added: " + (err && err.message) };
    } finally {
      sheetsUi.busy = false;
      paintSheets();
    }
  }

  /** Kept under its old name for the harnesses: the "+ Add option" button is "Add sheet" now, and every sheet it adds is
   *  an option that starts on the proposal, as the options it used to add did. */
  function addOption(tab) { return addSheetPress(tab); }

  /** COPY A SHEET: a copy of everything on it, prices exactly as it does, filed as an option that starts OFF the proposal. */
  function copySheet(tab) {
    try {
      var made = B.copySection(ROOT, tab, { state: TW.getState() });
      ROOT = made.model;
      if (Object.keys(made.patch).length) TW.setState(made.patch);
      resetSheetsUi();
      show(made.id);
      followSf = B.takeoffSf(B.sectionOf(ROOT, made.id).section.takeoff);
      sheetsChanged(made.id, made.id + "|open");
    } catch (err) {
      // In the panel, under the sheet's own buttons (see addSheetPress): the 13th copy is refused where the estimator is looking.
      sheetsUi.notice = { at: tab, text: "The sheet could not be copied: " + (err && err.message) };
      sheetsUi.focus = tab + "|copy";
      paintSheets();
    }
  }

  /** DELETE A SHEET: the first press arms the button ("Click again to delete"), the second removes it, rows included. What the
   *  draft kept for it goes too (B.deleteSection's patch), because a Copy id is handed out again. The base bid and the
   *  sheet a bid starts on are refused by the model and their button is disabled with the reason beside it. */
  function deletePress(tab) {
    var held;
    try { held = B.sectionOf(ROOT, tab); } catch (err) { return; }
    // The base bid and the sheet a bid starts on are refused in the model's own words, never armed.
    if (held.root || held.kind === "base") {
      try { B.deleteSection(ROOT, tab, { state: TW.getState() }); } catch (err) { say("That sheet could not be deleted: " + (err && err.message)); }
      return;
    }
    if (sheetsUi.armed !== tab) { sheetsUi.armed = tab; paintSheets(); return; }
    sheetsUi.armed = null;
    var gone;
    try {
      gone = B.deleteSection(ROOT, tab, { state: TW.getState() });
    } catch (err) {
      say("That sheet could not be deleted: " + (err && err.message));
      paintSheets();
      return;
    }
    ROOT = gone.model;
    if (Object.keys(gone.patch).length) TW.setState(gone.patch);
    sheetsUi.confirm = null; sheetsUi.renaming = null; sheetsUi.error = ""; sheetsUi.notice = null; sheetsUi.descOpen = {};
    var next = activeTab === tab ? openingTab() : activeTab;
    sheetsChanged(next, next + "|open");
  }

  /** Kept under its old name for the harnesses: the first press arms, the second deletes. */
  function removeOptionPress(tab) { deletePress(tab); }

  /** RENAME: what the sheet is called on screen and on the proposal. Checked when the name is committed (Save name or Enter),
   *  never while it is being typed; the reason it was refused (B.validateLabel) is shown under the box and the box keeps what
   *  was typed. The key of the sheet never changes, so nothing the draft keeps for it moves. */
  function commitRename(tab) {
    var why = null;
    try { why = B.validateLabel(ROOT, sheetsUi.draft, tab); } catch (err) { why = (err && err.message) || "That name will not do."; }
    if (why) {
      sheetsUi.error = why;
      sheetsUi.focus = tab + "|name";
      paintSheets();
      return;
    }
    try { ROOT = B.renameSection(ROOT, tab, sheetsUi.draft); } catch (err) {
      sheetsUi.error = (err && err.message) || "That name will not do.";
      sheetsUi.focus = tab + "|name";
      paintSheets();
      return;
    }
    sheetsUi.renaming = null; sheetsUi.error = "";
    sheetsChanged(activeTab, tab + "|rename");
  }

  function cancelRename(tab) {
    sheetsUi.renaming = null; sheetsUi.error = "";
    sheetsUi.focus = tab + "|rename";
    paintSheets();
  }

  /** The base bid was asked for: one sheet, or the combined Epoxy and Polish pair. Nothing changes until the estimator says
   *  yes, because it moves the lump sum, the job type and what the proposal prints. */
  function askBase(row) {
    var ids = row === "combined" ? B.combinedPair(ROOT) : [row];
    var now = null;
    try { now = B.baseOf(ROOT).ids; } catch (err) { now = null; }
    if (!ids || (now && now.length === ids.length && ids.every(function (id) { return now.indexOf(id) >= 0; }))) {
      sheetsUi.confirm = null;
      paintSheets();
      return;
    }
    sheetsUi.confirm = { row: row, ids: ids };
    sheetsUi.armed = null;
    paintSheets();
  }

  /** MAKE THE ASKED-FOR SHEET(S) THE BASE BID. Everything follows the base: B.pickBase moves the kinds (the old base goes ON
   *  the proposal as an option, priced as a total) and answers the draft's side, work_type (a combined base is "combo") and
   *  base_tab_id (null for the pair) with the old base's tab_opts; the lines the estimator typed on the Proposal step follow the
   *  new base by the rule the other two base pickers run (TWPrice.applyBasePick); and the save that comes next stamps the lump
   *  sum, the priced tabs and the proposal's figures from the new base. */
  function makeBase() {
    var asked = sheetsUi.confirm;
    sheetsUi.confirm = null;
    if (!asked) { paintSheets(); return; }
    var st = TW.getState();
    var made, before, carrierBefore;
    try {
      before = B.baseOf(ROOT);
      carrierBefore = B.travelCarrier(ROOT);
      made = B.pickBase(ROOT, asked.ids, { state: st });
    } catch (err) {
      say("The base bid could not be changed: " + (err && err.message));
      paintSheets();
      return;
    }
    var patch = Object.assign({}, made.patch);
    var from = before.ids.length === 1 ? before.ids[0] : null;
    var to = made.patch.base_tab_id === undefined ? null : made.patch.base_tab_id;
    if (PR && from !== to && st.price_overrides && typeof st.price_overrides === "object") {
      var pov = JSON.parse(JSON.stringify(st.price_overrides));
      var roles = {};
      try { B.sectionsOf(made.model).forEach(function (e) { roles = Object.assign({}, roles, Object.fromEntries([[e.tab, e.role]])); }); } catch (err) { roles = {}; }
      var moved = PR.applyBasePick(pov, from, to, st.priced_tabs, {
        workType: made.patch.work_type, roles: roles, basePhrase: PR.draftBasePhrase(st)
      });
      if (moved) patch.price_overrides = pov;
    }
    ROOT = made.model;
    // A BASE CHANGE IS A JOB TYPE SWITCHED IN THE SESSION TOO (2026-10-20 audit): when it moves the job's travel to another sheet, the
    // Travel Labor row moves with it (B.pickBase), and a row that was left blank under a far distance on file is filled by the same
    // rule an answer follows (B.followDistance), which also takes back the drive an old carrier that is still a base had filled, so one
    // Travel Labor row is priced for the job's one drive. It is given the WHOLE model (ROOT): M is the section on show, of the model
    // from before the change. A base change that keeps the carrier fills nothing.
    if (B.travelCarrier(ROOT) !== carrierBefore) B.followDistance(ROOT, carrierBefore);
    TW.setState(patch);
    sheetsChanged(activeTab, (asked.row === "combined" ? "combined" : asked.row) + "|base");
  }

  /** The "On the proposal as an option" switch. Off keeps the sheet on the bid and priced, and takes it off the proposal. */
  function toggleOnProposal(tab) {
    var st = TW.getState();
    var on = B.optionIsOn(st.tab_opts, tab);
    TW.setState(B.tabOptPatch(st, tab, on ? { is_option: false } : { is_option: true, show: true }));
    paintSheets();
  }

  /** Total, or Add / Deduct. A Seal sheet is priced as a total only, so the page refuses the other even if it is asked. */
  function setPriceMode(tab, mode) {
    var e = null;
    try { e = B.sectionOf(ROOT, tab); } catch (err) { return; }
    var want = mode === "deduct" && e.role !== "seal" ? "deduct" : "total";
    TW.setState(B.tabOptPatch(TW.getState(), tab, { price_mode: want }));
    paintSheets();
  }

  /** The words an option prints as its line. Saved as they are typed, never repainted under the caret. */
  function setOptionDesc(tab, text) {
    TW.setState(B.tabOptPatch(TW.getState(), tab, { desc: String(text || "").slice(0, 400) }));
  }

  /** What each button in the panel does. `tab` is the sheet it is on, `sheet` the type chosen in the Add menu. */
  function sheetsAct(act, tab, sheet) {
    if (act === "on") { toggleOnProposal(tab); return; }
    if (act === "desc") {
      var wasOpen = sheetsUi.descOpen[tab] === true;
      sheetsUi.descOpen = Object.assign({}, sheetsUi.descOpen, Object.fromEntries([[tab, !wasOpen]]));
      sheetsUi.focus = tab + (wasOpen ? "|desc" : "|desc-box");
      paintSheets();
      return;
    }
    if (act === "copy") { copySheet(tab); return; }
    if (act === "rename") {
      var label = "";
      try { label = B.sectionOf(ROOT, tab).label; } catch (err) { return; }
      sheetsUi.renaming = tab; sheetsUi.draft = label; sheetsUi.error = ""; sheetsUi.armed = null; sheetsUi.confirm = null;
      sheetsUi.focus = tab + "|name";
      paintSheets();
      return;
    }
    if (act === "rename-save") { commitRename(tab); return; }
    if (act === "rename-cancel") { cancelRename(tab); return; }
    if (act === "delete") { deletePress(tab); return; }
    if (act === "base-yes") { makeBase(); return; }
    if (act === "base-no") {
      var row = sheetsUi.confirm ? sheetsUi.confirm.row : null;
      sheetsUi.confirm = null;
      sheetsUi.focus = row ? row + "|base" : null;
      paintSheets();
      return;
    }
    if (act === "add-menu") { sheetsUi.pick = true; sheetsUi.armed = null; sheetsUi.focus = "add|close"; paintSheets(); return; }
    if (act === "add-close") { sheetsUi.pick = false; sheetsUi.focus = "add|menu"; paintSheets(); return; }
    if (act === "add") { addSheetPress(sheet); return; }
  }

  /** Is the section on show edited on the page's own panels? Polish, Epoxy and Gyp are (their work types are `ready`
   *  in Estimating Tool v2). The others, until their phases, show the summary below, so nothing is hidden. */
  function openSectionEditable() {
    if (activeTab === B.ROOT_TAB) return true;
    var e = openEntry();
    return !!e && (e.role === "polish" || e.role === "epoxy" || e.role === "gyp" || e.role === "seal");
  }

  /** What the panel shows while a section that is not edited here yet is open: what it holds and how it was
   *  priced. */
  function otherSectionPanel() {
    var e;
    try { e = B.sectionOf(ROOT, activeTab); } catch (err) { show(B.ROOT_TAB); return PANELS[at](); }
    var b = allBids()[e.tab] || {};
    var s = e.section;
    var rates = (s.rates && s.rates.notes) || [];
    var priced = b.priceable === false
      ? "It cannot be priced: " + (b.reason || "the reason was not given") + "."
      : "Priced at " + (b.total ? B.money(b.total) : "nothing yet") + ".";
    var body = '<p>' + esc(priced) + '</p>' +
      '<p>' + esc((s.takeoff || []).length + " takeoff row(s), " + (s.labor || []).length + " labor row(s). " +
        "Priced with " + e.profile + ".") + '</p>' +
      (rates.length ? '<p>Markups rules that were not used when this section was added:</p><ul>' +
        rates.map(function (n) { return '<li>' + esc(n) + '</li>'; }).join("") + '</ul>' : "");
    return '<section class="sec"><div class="sec-h"><h2>' + esc(e.label) + '</h2><p>' +
      esc(e.kind === "option" ? "An option on this bid." : e.kind === "off" ? "Not part of this bid." : "Part of the base bid.") +
      '</p></div><div class="sec-b">' + body + '</div></section>';
  }

  // ── the rail ────────────────────────────────────────────────────────────────
  /** Untouched, done, or needs attention. Untouched is deliberately blank rather than a warning:
   *  a page that opens shouting at the estimator has said nothing. */
  function stepStatus() {
    var priced = 0, half = 0;
    M.takeoff.forEach(function (r) {
      if (!B.rowOn(r)) return;                         // an off row is not part of the bid
      var measured = B.num(r.measurement) > 0;
      // EITHER ID COUNTS. A picked, measured material row is a finished row by every definition
      // this page uses -- it prices, it reaches the Material total, it prints on Review -- and
      // reading `assembly_id` alone left the takeoff pip blank on a bid made entirely of
      // materials, which has been possible since 2026-09-19.
      var picked = !!(r.assembly_id || r.item_id);
      if (picked && measured) priced += 1;
      else if (picked || measured) half += 1;
    });
    var lab = 0;
    // The Labor step is done when a line prices, and a line the prevailing wage prices counts (the same rate the
    // totals and the blockers use), so a blank-rate line the card is pricing does not leave the pips grey.
    var pwStep = B.prevailingApplied(M);
    M.labor.forEach(function (r) { if (B.laborCost(r, pwStep) > 0) lab += 1; });
    return {
      takeoff: half ? "att" : (priced ? "ok" : ""),
      labor: lab ? "ok" : "",
      review: (priced && lab && !B.blockers(M).length) ? "ok" : "",
    };
  }

  function paintRail() {
    var st = stepStatus();
    var rail = $("rail");
    rail.innerHTML = "";
    STEPS.forEach(function (s, i) {
      var b = document.createElement("button");
      b.type = "button";
      if (i === at) b.setAttribute("aria-current", "true");
      var pip = document.createElement("span");
      var status = st[s.key] || "";
      pip.className = "pip" + (i === at ? "" : (status ? " " + status : ""));
      if (status === "ok" && i !== at) pip.innerHTML = icon("check", 12);
      else pip.textContent = String(i + 1);
      b.appendChild(pip);
      b.appendChild(document.createTextNode(s.label));
      b.addEventListener("click", function () { go(i); });
      rail.appendChild(b);
    });
  }

  /** The step keys, in rail order — what the URL is allowed to name. */
  function stepKeys() {
    return STEPS.map(function (s) { return s.key; });
  }

  /** Which step this estimate opens on, as an index.
   *
   *  BY KEY, NEVER BY NUMBER. "Step 2" would mean Labor today and something else the day a step
   *  is added or reordered, and a link somebody sent last week would then open the wrong screen.
   *  `pick` also makes a removed step fall back rather than leaving `at` pointing past the end of
   *  PANELS, which renders nothing at all.
   *
   *  Without the module this answers the caller's own default. See library.js's showView on why
   *  the guard is a `typeof`. */
  function openingStep(fallbackIndex) {
    if (typeof window === "undefined" || !window.TWTabMemo) return fallbackIndex;
    var keys = stepKeys();
    var want = window.TWTabMemo.pick(window.TWTabMemo.read(window, "step"), keys,
                                     keys[fallbackIndex]);
    var i = keys.indexOf(want);
    return i < 0 ? fallbackIndex : i;
  }

  function go(i) {
    at = Math.max(0, Math.min(STEPS.length - 1, i));
    // So a reload comes back to the step you were on. Written after the clamp, so what the URL
    // records is the step actually shown rather than the number that was asked for.
    if (typeof window !== "undefined" && window.TWTabMemo) {
      window.TWTabMemo.write(window, { step: STEPS[at].key });
    }
    paintRail();
    renderPanel();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ── panels ──────────────────────────────────────────────────────────────────
  function shell(title, blurb, body) {
    var prev = at > 0
      ? '<button class="btn ghost" data-go="' + (at - 1) + '">← Back</button>' : "";
    var next = at < STEPS.length - 1
      ? '<button class="btn" data-go="' + (at + 1) + '">Next · ' +
        esc(STEPS[at + 1].label) + ' →</button>'
      // withDraft, not a bare path: this panel is rendered long after shared.js has finished
      // stamping ?d= onto the static links, and on a test copy the id it would have stamped is
      // the REAL project's. Continue has to carry the draft the page is actually editing.
      : '<a class="btn" href="' + esc(TW.withDraft("/proposal-review.html")) +
        '">Continue to proposal →</a>';
    return '<section class="sec"><div class="sec-h"><h2>' + esc(title) + '</h2>' +
      (blurb ? '<p>' + esc(blurb) + '</p>' : '') + '</div><div class="sec-b">' + body + '</div>' +
      '<div class="nav"><span class="step-of">Step ' + (at + 1) + ' of ' + STEPS.length +
      '</span>' + prev + next + '</div></section>';
  }

  /** The hint under an assembly picker: what was matched, or that nothing was. */
  function asmHint(row) {
    var asm = asmById((row || {}).assembly_id);
    if (asm) {
      var n = (asm.lines || []).length;
      return n + " item line" + (n === 1 ? "" : "s") + " · priced per " + (asm.unit || "SF");
    }
    if (String((row || {}).assembly_name || "").trim()) {
      return "No assembly by that name — pick one from the list.";
    }
    return "From the Items &amp; Assemblies library.";
  }

  /** The material row's three helpers. Separate from asmHint rather than a branch inside it,
   *  because they answer different questions: an assembly's hint is about its LINES, a material's
   *  is about the pack you buy. */
  function itemById(id) {
    for (var i = 0; i < ITEMS.length; i++) if (ITEMS[i].id === id) return ITEMS[i];
    return null;
  }

  /** The library row a takeoff row points at, with the kind that tells takeoffUnit which field is
   *  its unit: an assembly's own `unit`, a material's `coverage_basis` (never `item.unit`, which is
   *  the pack it is bought in). Null for a row nothing is picked on. */
  function libraryRowOf(row) {
    var r = row || {};
    if (rowKind(r) === "item") {
      var it = itemById(r.item_id);
      return it ? { kind: "item", lib: it } : null;
    }
    var asm = asmById(r.assembly_id);
    return asm ? { kind: "asm", lib: asm } : null;
  }

  /** What the row's Unit box shows: {text, hint, note}. See B.takeoffUnitView. */
  function unitView(row) {
    var ref = libraryRowOf(row);
    return B.takeoffUnitView(row, ref ? ref.kind : "asm", ref ? ref.lib : null);
  }

  /** The line under the Unit box. A link to Items & Assemblies, where the unit is set, so a row
   *  that says "Not set" is one click from the place that fixes it. */
  function unitHintHtml(v, i) {
    return '<a class="hint unithint' + (v.note ? ' note' : '') + '" href="/library.html" ' +
      'target="_blank" rel="noopener" data-unithint-for="' + i + '">' + esc(v.hint) + '</a>';
  }

  /** Redraw every takeoff row's Unit box and the line under it, in place. A pick that changes the
   *  unit does not rebuild the card (a rebuild mid-keystroke takes the caret with it), so this is
   *  how the screen catches up. */
  function paintUnits() {
    document.querySelectorAll("[data-unit-for]").forEach(function (el) {
      el.textContent = unitView(M.takeoff[parseInt(el.getAttribute("data-unit-for"), 10)]).text;
    });
    document.querySelectorAll("[data-unithint-for]").forEach(function (el) {
      var v = unitView(M.takeoff[parseInt(el.getAttribute("data-unithint-for"), 10)]);
      el.textContent = v.hint;
      el.className = "hint unithint" + (v.note ? " note" : "");
    });
    // A pick that changes the unit clears the row's measurement (B.adoptTakeoffUnit), and the card
    // is not rebuilt, so the box has to be told. A box somebody is typing in is never touched.
    document.querySelectorAll('[data-tk][data-k="measurement"]').forEach(function (box) {
      if (box === document.activeElement) return;
      var row = M.takeoff[parseInt(box.getAttribute("data-tk"), 10)];
      if (!row) return;
      var want = row.measurement == null ? "" : String(row.measurement);
      if (String(box.value) !== want) box.value = want;
    });
  }

  function matHint(row) {
    var it = itemById((row || {}).item_id);
    if (it) {
      var pack = B.num(it.buy_qty) || 1;
      return esc(B.num(it.unit_cost) != null
        ? B.money2(it.unit_cost) + " per " + (pack === 1 ? "" : B.num(pack) + " ") +
          (it.unit || "unit")
        : "This material has no cost in the library yet.");
    }
    if (String((row || {}).item_name || "").trim()) {
      return "No material by that name — pick one from the list.";
    }
    return "A single product, priced straight off the library.";
  }

  /** A name that is two things at once, on a row that has not decided yet. */
  function ambiguous(row) {
    var r = row || {};
    if (rowKind(r) !== "new") return false;
    var hit = lineMatches(r.pick_name);
    return !!(hit.asm && hit.item);
  }

  /** Enough of each candidate to tell them apart on a button. Shorter than asmHint/matHint on
   *  purpose -- these sit two-to-a-line inside a hint, not under a field of their own. */
  function asmPickLabel(a) {
    var n = ((a || {}).lines || []).length;
    return n + " item line" + (n === 1 ? "" : "s");
  }

  function matPickLabel(it) {
    var c = B.num((it || {}).unit_cost);
    return c != null
      ? B.money2(c) + " per " + esc((it || {}).unit || "unit")
      : "no cost in the library yet";
  }

  /** The line under the one picker, which has four things to say instead of two.
   *
   *  A ROW THAT HAS RESOLVED reads exactly as it did before -- asmHint or matHint, untouched --
   *  because what an estimator wants from a finished row did not change.
   *
   *  A NAME THAT IS TWO THINGS IS THE ONE QUESTION THIS PAGE ASKS. It would be easy to resolve it
   *  by order (items first, say) and never mention it; that is precisely the silent wrong answer
   *  the merged list makes possible, and the whole reason the old two-list split existed. So the
   *  row holds what was typed, prices nothing, and offers the two candidates with enough of each
   *  to choose by. It is the only place a takeoff row asks the estimator anything. */
  function pickHint(row, i) {
    var r = row || {};
    var k = rowKind(r);
    if (k === "item") return matHint(r);
    if (k === "asm") return asmHint(r);
    var hit = lineMatches(r.pick_name);
    if (hit.asm && hit.item) {
      return "Two things in the library are called that. " +
        '<button class="kindpick" data-kind-pick="item" data-kind-row="' + i + '">Material · ' +
        matPickLabel(hit.item) + "</button>" +
        '<button class="kindpick" data-kind-pick="asm" data-kind-row="' + i + '">Assembly · ' +
        asmPickLabel(hit.asm) + "</button>";
    }
    if (String(r.pick_name || "").trim()) {
      return "Nothing in the library goes by that name — pick one from the list.";
    }
    return "Search the Items &amp; Assemblies library. Picking a material adds a coverage box.";
  }

  /** WHAT THE BOX WILL USE IF IT IS LEFT EMPTY, shown as the placeholder rather than typed into
   *  the field. Filling the box with the item's default would look like an answer somebody gave
   *  for THIS row, and the estimator would have no way to tell it apart from one they typed --
   *  which matters the day the item's default changes in the library and this row does not. */
  function covPlaceholder(row) {
    var it = itemById((row || {}).item_id);
    var cov = it && B.num(it.coverage);
    return cov ? String(cov) : "";
  }

  /** The line under EVERY coverage box, whichever kind of row owns it.
   *
   *  `typed` is what this bid says, `lib` the material's own figure. A typed number that differs
   *  from the library's is the one case worth a sentence of its own: the estimator is looking at
   *  a figure that is not the library's and needs the way back to it ("Library default: N").
   *  Typing the library's own number back reads as the plain line, because nothing differs. */
  function covLine(typed, lib) {
    typed = B.num(typed); lib = B.num(lib);
    if (typed > 0) return "How far one goes, for this job.";
    if (lib > 0) return "Blank uses the library's " + lib + ".";
    return "How far one goes. The library has no default for it.";
  }

  /** THE ONE "Default value: N" WARNING, shared by every box whose default the estimator may
   *  override (coverage on every row kind, the labor rate). It sits directly under the box in the
   *  page's amber `.warnline`, is empty/hidden while the box agrees with the default, and goes
   *  away again when the default is typed back. `text` is "" when there is nothing to warn about. */
  function dfltWarnText(differs, shown) {
    return differs ? "Default value: " + shown : "";
  }
  function dfltWarnHtml(attrs, text) {
    return '<p class="warnline dflt-warn" ' + attrs + (text ? "" : " hidden") + '>' +
      esc(text) + '</p>';
  }
  function paintDfltWarn(el, text) {
    el.textContent = text;
    el.hidden = !text;
  }
  /** Coverage: warns only when a typed figure differs from a library figure that exists. */
  function covWarn(typed, lib) {
    typed = B.num(typed); lib = B.num(lib);
    return dfltWarnText(typed > 0 && lib > 0 && typed !== lib, lib);
  }

  function covHint(row) {
    var it = itemById((row || {}).item_id);
    return covLine((row || {}).coverage, it && it.coverage);
  }
  function covRowWarn(row) {
    var it = itemById((row || {}).item_id);
    return covWarn((row || {}).coverage, it && it.coverage);
  }

  /** What THIS BID types for a condition card's coverage (Joint Filler, Dye). 0 when blank. */
  function condCovTyped(key) {
    var cc = (M && M.cond_cov) || {};
    return B.num(cc[key]);
  }

  function condCovItem(key) {
    return itemById(T.itemIdOf(key));
  }

  function measureText(row) {
    var r = row || {};
    return B.num(r.measurement) ? B.fmtSf(r.measurement) + " " + (r.unit || "SF") : "";
  }

  /** The three that came off the intake form, as cards rather than as bare switches.
   *
   *  A SPEC RATHER THAN THREE COPIES OF THE SAME MARKUP, and the `cell` is on it deliberately:
   *  the main thing every one of these does is set that cell, so naming it on screen is the
   *  difference between a control whose effect you can see and one you have to be told about.
   *  The star this page's library replaced got that wrong for two years.
   *
   *  TWO SHAPES NOW, DECIDED BY `cost`. Joint Filler and Dye BUY something: they move the
   *  Material total through condLine (their reserved library rows, or bid-model.js's
   *  jointFillerCost/dyeCost when a row is not there). Since 2026-09-19 they
   *  render as material rows -- the same `.tk.mat` card, the same Material / Measurement / Unit /
   *  Total cost columns, the same `.costbox` -- as the rows above them. Hanz, on staging: "joint
   *  filler and die should have a measurement a unit in a total cost and they should be a
   *  material not an assembly." One dollar figure beside a switch is not a material row; a line
   *  that says what is bought, how much of it, and what it comes to, is.
   *
   *  REMOVE EXISTING HAS NO `cost` and keeps the old switch-and-sentence card, untouched. It buys
   *  nothing: it adds a fourth hand to the joint-filler crew and is priced on the Labor step, so
   *  giving it a Measurement and a Total cost would invent a purchase that does not exist.
   *
   *  `needs` is the gate remove_existing_jf carried on the intake form. With no joint filler there
   *  is no crew for it to be the fourth hand of -- dimmed, never hidden, and its answer still
   *  reaches Polish!F29 either way.
   *
   *  WHY NOTHING ON THESE TWO CARDS IS TYPEABLE. A real material row's measurement is the
   *  estimator's own number. These have none of their own: the area is always
   *  `B.takeoffSf(M.takeoff)`, the same figure materialTotal() prices and divides by, and the kit
   *  count is recomputed from it on every render. A box that accepted typing and then threw it
   *  away would be a lie, so all four columns are `.costbox` -- this page's own "a field's
   *  answer, never an input" box, which is exactly what the Total cost column beside them has
   *  always been. The tell an estimator already reads is the hover: `.f input` takes a red border
   *  under the cursor and a `.costbox` does not.
   *
   *  `qty` READS THE PRICE BACK rather than restating the formula. Since 2026-09-30 the kit's
   *  coverage is the reserved row's own (condLine), so the kit count and the "one kit per ..."
   *  sentence both come off the line priceLine priced; a second copy of 3500 on this page would
   *  go stale the day an admin changed it. */
  //
  //  WHICH CARDS THERE ARE IS THE TABLE'S, AND WHAT EACH ONE SAYS IS THIS PAGE'S (Phase 7). CARD_VIEWS
  //  below is everything about a card that is this screen's own: its tag, its sentences, how it prices.
  //  The conditions the Takeoff step asks of a polish job, in its order, and each one's workbook cell, its
  //  reserved library row (`item_id`: see condLine, which falls back to bid-model.js's jointFillerCost when
  //  the row is not there) and what it `needs` come from js/work-types.js, and CONDITION_CARDS joins the
  //  two. A condition added there with no view here is refused by name rather than drawn half-finished.
  var CARD_VIEWS = [
    { key: "joint_filler", tag: "JOINT FILLER", label: "In the bid",
      // THE LIVE NAME, not a string typed twice. An admin renaming the row on the Items tab has
      // to show up here too, or the card is a second copy of a fact that can go stale without
      // looking stale.
      material: function () {
        var item = L.findItem(ITEMS, T.itemIdOf("joint_filler"));
        return (item && item.name) ? item.name : "Joint filler, 10 gal kit";
      },
      matHint: "Polish!E29 · priced from the Item Library.",
      cost: function (area) { return condLine("joint_filler", area).cost; },
      qty: function (area) { return condLine("joint_filler", area).qty; },
      unit: function (n) { return n === 1 ? "kit" : "kits"; },
      // THE ROW'S OWN COVERAGE, WASTE AND ROUNDUP, read back off the priced line rather than
      // restated: the sentence says what the arithmetic did. With the seeded row -- and with no
      // row at all -- it reads exactly as it always has.
      qtyHint: function (area) {
        var ln = condLine("joint_filler", area).line;
        if (!ln) return B.fmtSf(area) + " sq ft, at one kit per 3,500, rounded up.";
        return B.fmtSf(area) + " sq ft, at one kit per " + B.fmtSf(ln.coverage) +
          (ln.waste_pct > 0 ? " plus " + B.fmtSf(ln.waste_pct) + "% waste" : "") +
          (ln.roundup ? ", rounded up." : ".");
      },
      unitHint: "Kits are what the job buys." },
    { key: "remove_existing_jf", tag: "REMOVE EXISTING", label: "Taking the old filler out",
      // ITS RESERVED library_items ROW, 2026-10-01 -- the Defaults tab lists it as a material and
      // the Items tab is where it is edited. NOTHING HERE PRICES OFF IT: the card has no `cost`,
      // so it stays the switch-and-sentence card and its answer still only reaches Polish!F29.
      // It is carried so RESERVED_ITEM_IDS below keeps it out of every takeoff-row picker.
      why: "Adds a fourth hand to the joint-filler line. Priced on the Labor step, where that " +
           "line is." },
    { key: "dye", tag: "DYE", label: "In the bid",
      material: function () {
        var item = L.findItem(ITEMS, T.itemIdOf("dye"));
        return (item && item.name) ? item.name : "Dye, per coat";
      },
      matHint: "Polish!E25 · two coats, rows 25 and 26 · priced from the Item Library.",
      cost: function (area) { return condLine("dye", area).cost; },
      qty: function (area) { return condLine("dye", area).qty; },
      unit: function () { return "SF"; },
      // TWO COATS, SAID WHERE THE RATE IS: "2 coats x $0.14 / SF" rather than a $0.28 nobody can
      // find in the library, whose row is one coat.
      rateHint: function (cost, qty) {
        return B.DYE_COATS + " coats \u00d7 " + B.money2(cost / qty / B.DYE_COATS) + " / SF";
      },
      qtyHint: function () { return "The polished area from the rows above."; },
      unitHint: "Priced across the area, not by the pack." }
  ];

  /** The cards, as the page draws them: each condition the Takeoff step asks of a polish job (the table's
   *  rows, in its order) with its own view laid over { key, cell, item_id, needs }. `cell` is the first
   *  workbook cell the answer is written to, `item_id` the reserved library row that prices it, and
   *  `needs` is set only on the card that depends on another. */
  var CONDITION_CARDS = (function () {
    var views = new Map(CARD_VIEWS.map(function (v) { return [v.key, v]; }));
    return T.conditionsFor("polish", "v2Takeoff").map(function (c) {
      if (!views.has(c.key)) {
        throw new Error("polish-estimate.js has no card for the Takeoff condition " + c.key);
      }
      var data = { key: c.key, cell: c.cells[0], item_id: c.item_id };
      if (c.needs) data.needs = c.needs;
      return Object.assign(data, views.get(c.key));
    });
  })();

  // The three ids CONDITION_CARDS above owns -- the two it prices by a fixed formula rather than
  // by search, and remove-existing's, which prices nothing -- read off it rather than retyped, so
  // an id excluded here can never drift from the card that owns it. renderDatalist() below is the
  // reason this exists: none may be picked into a takeoff row as an ordinary second material,
  // because the card above already owns that line and prices it (or does not) its own way.
  var RESERVED_ITEM_IDS = CONDITION_CARDS.filter(function (c) { return c.item_id; })
    .map(function (c) { return c.item_id; });

  /** Everything a priced condition card SHOWS, worked out once.
   *
   *  ONE FUNCTION FOR BOTH PAINTS, which is the lesson the Travel card's Guys box already taught
   *  this file: if the first render and repaintNumbers each work a figure out their own way, the
   *  screen ends up disagreeing with itself about a number the estimator is looking at.
   *
   *  AND IT WAS DISAGREEING. Until now the condition cards' dollar figure was rendered once and
   *  never repainted. Typing into a takeoff row takes `changed(false)`, which refreshes the row
   *  costs and the Material total in place, and nothing in that path knew about these cards --
   *  so the Joint Filler line sat there quoting an area that was no longer on the screen.
   *
   *  AN UNMEASURED JOB GETS THE EM DASH a takeoff row with no measurement gets, in the same
   *  `.costbox.empty`. Never "0 SF" and never "$0": both read as a computed answer of nothing,
   *  when the truth is that nobody has measured anything yet. rowCost()'s own rule.
   *
   *  THE RATE SHOWS EITHER WAY. It is Kyle's C25/C29 and is true whether the line is in the bid
   *  or not, unlike a takeoff row's per-unit, which has no value until somebody types a
   *  measurement. `cost` here is always what the line WOULD come to; `on` decides only whether
   *  the Total cost box says it. */
  function condFigures(c) {
    var area = B.takeoffSf(M.takeoff);
    var qty = B.num(c.qty(area));
    var unit = c.unit(qty);
    var cost = B.num(c.cost(area));
    var on = !!(M.conditions || {})[c.key];
    return {
      on: on, unit: unit,
      qty: qty > 0 ? B.fmtSf(qty) : "\u2014",
      qtyEmpty: !(qty > 0),
      sub: qty > 0 ? B.fmtSf(qty) + " " + unit : "",
      cost: (on && cost > 0) ? moneyAuto(cost) : "\u2014",
      costEmpty: !(on && cost > 0),
      // SINGULAR, always: "$500.00 / kit" is the price of one, which is what a per-unit line
      // says. `unit` beside the Measurement is plural because five of them is what the job buys.
      rate: qty > 0 ? (c.rateHint ? c.rateHint(cost, qty)
                                  : B.money2(cost / qty) + " / " + c.unit(1)) : "",
      qtyHint: c.qtyHint(area),
      // The Coverage box's own text, here so the first paint and repaintNumbers share one source.
      covPlaceholder: (function () {
        var it = condCovItem(c.key);
        var v = it && B.num(it.coverage);
        return v ? String(v) : "";
      })(),
      covHint: (function () {
        var it = condCovItem(c.key);
        return covLine(((M && M.cond_cov) || {})[c.key], it && it.coverage);
      })(),
      covWarn: (function () {
        var it = condCovItem(c.key);
        return covWarn(((M && M.cond_cov) || {})[c.key], it && it.coverage);
      })()
    };
  }

  /** A condition that buys something, drawn as the material row it is.
   *
   *  THE SWITCH SITS WHERE THE ROW'S REMOVE BUTTON SITS -- top right of the header -- because it
   *  does that button's job: it is what decides whether this line is in the takeoff at all.
   *  Hanging it off the card as a fifth thing that is not one of the four columns is the failure
   *  this shape exists to avoid.
   *
   *  ITS LABEL NAMES THE STATE, not the action, which is `.labsw`'s rule and for `.labsw`'s
   *  reason: "In the bid" reads true against both switch positions, where "Include" would
   *  describe the state you are leaving.
   *
   *  FIVE COLUMNS, `.matg` -- a material row's template, Coverage included. (An earlier note here
   *  said these had no Coverage because neither is bought by the pack. That was wrong: Joint
   *  Filler is bought by the KIT, one per 3,500 SF, and Dye is a library material with its own
   *  coverage like any other.) The box is this bid's own override (M.cond_cov): blank prices with
   *  the library row's figure, and a typed one says "Library default: N". It prices through
   *  condLine and reaches Kyle's workbook through conditionLibrary, so the download matches. */
  function condMaterialCard(c) {
    var f = condFigures(c);
    var box = function (part, empty, text) {
      return '<div class="costbox' + (empty ? " empty" : "") + '" data-condfig="' +
        esc(c.key) + "." + part + '">' + esc(text) + "</div>";
    };
    var hint = function (part, text) {
      return '<p class="hint" data-condfig="' + esc(c.key) + "." + part + '">' + esc(text) +
        "</p>";
    };
    // GRAYED WHILE OFF, like Travel on a local job: `.tk.inert` dims the card, nothing is disabled,
    // and the switch in its header is how the estimator enables it.
    return '<div class="tk mat' + ((M.conditions || {})[c.key] ? "" : " inert") + '">' +
      '<div class="tk-h">' +
      '<span class="tag">' + esc(c.tag) + "</span>" +
      '<span class="tk-sub" data-condfig="' + esc(c.key) + '.sub">' + esc(f.sub) + "</span>" +
      condSwitch(c.key, c.label) +
      "</div>" +
      '<div class="tk-g matg">' +

      '<div class="f"><label>Material</label>' +
      '<div class="costbox txt">' + esc(c.material()) + "</div>" +
      '<p class="hint">' + esc(c.matHint) + "</p></div>" +

      '<div class="f"><label>Measurement</label>' +
      box("qty", f.qtyEmpty, f.qty) +
      hint("qtyhint", f.qtyHint) + "</div>" +

      '<div class="f"><label>Unit</label>' +
      '<div class="costbox txt" data-condfig="' + esc(c.key) + '.unit">' + esc(f.unit) +
      "</div>" +
      '<p class="hint">' + esc(c.unitHint) + "</p></div>" +

      // THE SAME COVERAGE BOX A MATERIAL ROW CARRIES, for this bid only (M.cond_cov). Blank prices
      // with the library row's coverage, shown as the placeholder; a typed figure that differs
      // says "Library default: N" underneath.
      '<div class="f"><label>Coverage</label>' +
      '<input class="n" data-condcov="' + esc(c.key) + '" value="' +
      esc(nv(((M && M.cond_cov) || {})[c.key])) + '" placeholder="' + esc(f.covPlaceholder) + '">' +
      dfltWarnHtml('data-condfig="' + esc(c.key) + '.covwarn"', f.covWarn) +
      hint("covhint", f.covHint) + "</div>" +

      '<div class="f"><label>Total cost</label>' +
      box("cost", f.costEmpty, f.cost) +
      hint("rate", f.rate) + "</div>" +

      "</div></div>";
  }

  /** A condition that buys nothing: Remove Existing, and only Remove Existing.
   *
   *  It must never grow a Measurement or a Total cost, because it has neither. An assembly row
   *  carries a measurement and comes to a number; this carries a Yes or a No and comes to nothing
   *  on THIS screen, since the fourth hand it adds is priced on the Labor step. A "$0" here would
   *  be a figure, and it would be wrong. */
  function condSwitchCard(c) {
    var inert = c.needs && !M.conditions[c.needs];
    // The CARD is grayed while this condition is off, as the material cards are; the SWITCH is
    // dimmed only for the `needs` reason, so an off card is not dimmed twice.
    var off = !M.conditions[c.key];
    return '<div class="tk cond' + (inert || off ? " inert" : "") + '">' +
      '<div class="tk-h">' +
      '<span class="tag">' + esc(c.tag) + "</span>" +
      condSwitch(c.key, c.label, inert) +
      '<span class="tk-sub">' + esc(c.cell) + "</span>" +
      "</div>" +
      '<p class="hint">' + esc(c.why) + "</p>" +
      "</div>";
  }

  /** WHICH OF THE THREE KINDS a takeoff row is, in one place.
   *
   *  `item` first, and off `item_id` OR `kind` -- the old two-part test kept whole, for the reason
   *  it was written: a material row that has not been pointed at anything yet has an empty
   *  item_id, and inferring from that alone would redraw it as an assembly row the moment somebody
   *  cleared the field, taking their measurement and coverage with it.
   *
   *  `new` is the third kind, added 2026-09-23 with the single add button. A row nobody has
   *  searched on yet is not an assembly and not a material, and it no longer has to pretend to be
   *  one before the estimator has typed anything. A row saved before that date carries no `kind`
   *  at all and comes back an assembly, which is what it was. */
  function rowKind(row) {
    var r = row || {};
    if (r.item_id || r.kind === "item") return "item";
    if (r.kind === "new") return "new";
    return "asm";
  }

  /** The name the row's one search box shows, out of whichever field its kind owns. */
  function rowName(row) {
    var r = row || {};
    var k = rowKind(r);
    return k === "item" ? r.item_name : (k === "new" ? r.pick_name : r.assembly_name);
  }

  /** What the takeoff pop-up lists: every assembly and every material the row's own search field
   *  offers (renderDatalist), by name, minus the three reserved materials that already have a
   *  condition card of their own. Pure over ASMS and ITEMS. */
  function takeoffPickEntries() {
    var out = [];
    // IN A SECTION OTHER THAN THE ROOT, THE WORK TYPE'S OWN ROWS COME FIRST (Phase 12): an Epoxy section offers the
    // assemblies and materials filed for epoxy above the rest. `first` is the pop-up's own mark for that (js/
    // library-picker.js lists those rows on top, each group still in the order given), and it is set only here, so
    // the root's entries are the ones they always were. A row filed for no work type is everyone's and is not moved.
    var layout = null;
    if (activeTab !== B.ROOT_TAB) { var oe = openEntry(); layout = oe ? oe.layout : null; }
    var mark = function (entry, row) {
      if (layout !== null && (row.default_work_types || []).indexOf(layout) >= 0) entry.first = true;
      return entry;
    };
    ASMS.forEach(function (a) {
      out.push(mark({ key: "asm:" + a.id, kind: "asm", id: a.id, name: String(a.name == null ? "" : a.name),
                 sub: "Assembly" + (a.unit ? ", per " + String(a.unit).toUpperCase() : ""),
                 tag: L.assemblyPriceText(a, ITEMS) }, a));
    });
    ITEMS.forEach(function (it) {
      if (RESERVED_ITEM_IDS.indexOf(it.id) !== -1) return;
      out.push(mark({ key: "item:" + it.id, kind: "item", id: it.id,
                 name: String(it.name == null ? "" : it.name),
                 sub: "Material" + (it.unit ? ", " + it.unit : ""), tag: L.materialPriceText(it) }, it));
    });
    out.sort(function (x, y) { return x.name.localeCompare(y.name) || (x.kind < y.kind ? -1 : 1); });
    return out;
  }

  /** Add one takeoff row already pointed at the assembly or material that was ticked. It is built
   *  the way the row's own search field builds one: an undecided row, then becomeKind and the same
   *  setAssembly / setMaterial the field uses (unit adoption and all). The id is then pinned
   *  explicitly, because those two resolve by NAME and the pop-up knows exactly which row was
   *  ticked (two materials that differ only by case would otherwise land on the first). Returns
   *  the new row's index. */
  function addPickedTakeoffRow(p) {
    M.takeoff.push({ kind: "new", pick_name: "", measurement: "", unit: "SF" });
    var i = M.takeoff.length - 1;
    var row = M.takeoff[i];
    becomeKind(row, p.kind);
    if (p.kind === "item") {
      setMaterial(i, p.name);
      row.item_id = p.id;
      // The same pin for the unit: two materials of one name must not hand the row the first one's.
      var tickedItem = itemById(p.id);
      if (tickedItem) { row.unit = B.takeoffUnit("item", tickedItem).unit; paintUnits(); }
    } else {
      setAssembly(i, p.name);
      row.assembly_id = p.id;
      stampArea(row);
      // setAssembly found the assembly by NAME, so with two assemblies of one name the unit it
      // adopted is the first one's. Take the unit of the one that was actually ticked, through
      // the same resolve the row's own search uses.
      var ticked = ASMS.filter(function (a) { return a.id === p.id; })[0];
      if (ticked) row.unit = B.takeoffUnit("asm", ticked).unit;
    }
    // A SYSTEM IS SEVERAL ROWS ON ONE FLOOR (a primer, a body coat, a topcoat), so in a section other than the
    // root a square-foot row added beside a measured one starts as the same floor: it carries that number and is
    // not added to the area again (the `same_floor` mark takeoffSf skips). Typing its own number stops sharing.
    // The root keeps what it always did, a new row empty.
    if (activeTab !== B.ROOT_TAB && row.unit === "SF") {
      var carriers = M.takeoff.filter(function (q) {
        return q && q !== row && q.unit === "SF" && B.rowOn(q) && !q.same_floor && B.num(q.measurement) > 0;
      });
      var carrier = carriers[0];
      if (carrier) { row.measurement = carrier.measurement; row.same_floor = true; }
      // A carrier of a separate area (seedDefaultTakeoff marks it) is followed as that area's row.
      if (carrier && carrier.floor_area) {
        row.same_floor_of = carrier.floor_area;
        // A bid with two areas has two floors: the row covers each, one copy per area, so a primer added
        // beside System 1 and System 2 is bought for both floors and not for the first alone.
        var covered = [carrier.floor_area];
        carriers.forEach(function (c) {
          if (!c.floor_area || covered.indexOf(c.floor_area) !== -1) return;
          covered.push(c.floor_area);
          var copy = JSON.parse(JSON.stringify(row));
          copy.measurement = c.measurement;
          copy.same_floor_of = c.floor_area;
          M.takeoff.push(copy);
        });
      }
    }
    return i;
  }

  /** A lone takeoff row nobody has touched (no pick, no measurement) is the empty starting row of
   *  a new bid; the first pick takes its place rather than sitting under an empty one. */
  function isUntouchedTakeoffRow(r) {
    return !!r && !r.item_id && !r.assembly_id && !r.pick_name &&
      (r.measurement === "" || r.measurement == null);
  }

  var pickerOpen = false;
  function openTakeoffPicker(btn) {
    if (!P || pickerOpen) return;
    if (TW.modalOpen && TW.modalOpen()) return;
    if (TW.injectModalCss) TW.injectModalCss();
    pickerOpen = true;
    P.open(document, {
      onClose: function () { pickerOpen = false; },
      title: "Add assemblies or materials",
      sub: "Tick what this bid uses. Each one becomes a takeoff row.",
      placeholder: "Search assemblies and materials",
      emptyText: "The library has no assemblies or materials yet. Add some in Items & Assemblies first.",
      entries: takeoffPickEntries(),
      opener: btn,
      onAdd: function (chosen) {
        if (M.takeoff.length === 1 && isUntouchedTakeoffRow(M.takeoff[0])) M.takeoff = [];
        var first = -1;
        chosen.forEach(function (p) {
          var i = addPickedTakeoffRow(p);
          if (first === -1) first = i;
        });
        changed(true);
        // The caret goes with the new rows: Measurement of the first one is the next thing to fill.
        refocus('[data-tk="' + first + '"][data-k="measurement"]');
      }
    });
  }

  /** One takeoff row, as its own card -- a named function beside laborCard, and for the same
   *  reason that one is: a row now has to be redrawn on its own.
   *
   *  Since 2026-09-23 the picker decides the row's KIND, and a material's card is not an
   *  assembly's -- it carries a Coverage field and a fifth column. Showing that the moment a name
   *  resolves means redrawing the card mid-keystroke, and rebuilding the whole PANEL to do it
   *  would take the caret out of the box being typed in, which is the bug
   *  test_leaving_the_assembly_field_does_not_destroy_the_box_you_tabbed_into pins. `data-row-card`
   *  is what repaintRow addresses, and `i` is the row's real index in M.takeoff, which is what the
   *  delete splices by. */
  function takeoffRowCard(r, i) {
    return '<div class="' + rowCardClass(r) + '" data-row-card="' + i + '">' +
      rowCardInner(r, i) + '</div>';
  }

  function rowCardClass(r) {
    return "tk" + (rowKind(r) === "item" ? " mat" : "") + (B.rowOn(r) ? "" : " inert");
  }

  function rowCardInner(r, i) {
    var rc = rowCost(r);
    var p = rc.price;
    var warn = "";
    if (p && p.broken_lines) {
      warn = '<p class="warnline" data-broken-for="' + i + '">' + p.broken_lines + ' line' +
        (p.broken_lines === 1 ? '' : 's') + ' in this assembly cannot price yet. Check their ' +
        'cost and coverage in the Items &amp; Assemblies library.</p>';
    }
    // A MATERIAL ROW IS THE SAME CARD with a different first field and one extra, not a second
    // kind of card. An estimator reading the takeoff should see one list of things the job
    // buys; which of them happen to be systems and which are single products is a detail of how
    // the library stores them, not a distinction worth two layouts.
    //
    // AND A ROW THAT HAS NOT BEEN SEARCHED ON YET IS NEITHER -- the third state the single add
    // button brought with it. It draws as the assembly card minus Coverage, because Coverage is
    // the one field that would be a lie before anybody knows what is being bought.
    var kind = rowKind(r);
    var mat = kind === "item";
    var pending = kind === "new";
    return '<div class="tk-h">' +
      '<span class="tag">' + (mat ? "MATERIAL " : "ROW ") + (i + 1) + '</span>' +
      // Amber, and only while the row is undecided: the app's own mark for "this one is waiting on
      // a person". It leaves as soon as a name resolves, so a finished takeoff carries none.
      (pending ? '<span class="tk-mark" data-mark-for="' + i + '">' +
        (ambiguous(r) ? "pick one" : "new") + '</span>' : '') +
      '<span class="tk-sub" data-measure-for="' + i + '">' + esc(measureText(r)) + '</span>' +
      B.sliderHtml(B.rowOn(r), 'data-on-tk="' + i + '"', "Included", "Off keeps this row here, grayed, " +
        "and adds nothing to the price") +
      (M.takeoff.length > 1
        ? '<button class="x" data-del-row="' + i + '" title="Remove this row">' + icon("x", 12) + '</button>'
        : '') +
      '</div><div class="tk-g' + (mat ? " matg" : "") + '">' +

      // ONE FIELD AND ONE LIST, whichever kind the row turns out to be. Hanz, 2026-09-23: "These
      // two buttons should be combined to one and then it should just auto categorize based off
      // the item or assemblie we want to add." The label names what the field is holding NOW, so
      // it reads as an answer once there is one and as a question while there is not.
      '<div class="f"><label>' +
      (mat ? "Material" : (pending ? "Assembly or material" : "Assembly")) + '</label>' +
      '<input list="dl-lines" data-tk="' + i + '" data-k="pick" ' +
      'placeholder="Search assemblies and materials…" value="' + esc(nv(rowName(r))) + '">' +
      '<p class="hint" data-asmhint-for="' + i + '">' + pickHint(r, i) + '</p></div>' +

      '<div class="f"><label>Measurement</label>' +
      '<input class="n" data-tk="' + i + '" data-k="measurement" value="' +
      esc(nv(r.measurement)) + '">' +
      '<p class="hint">How much of it there is.</p></div>' +

      // THE UNIT IS ITEMS & ASSEMBLIES' ANSWER, NOT A CHOICE (Hanz, 2026-10-12: "Unit should be
      // pulled from the items and assemblies tab"). A read-only box in the same chrome as the
      // other facts on this page, and a line under it that says where the word came from, linking
      // to the page where it is set. unitView says what to show; paintUnits keeps it in step.
      '<div class="f"><label>Unit</label>' +
      '<div class="costbox txt" data-unit-for="' + i + '">' + esc(unitView(r).text) + '</div>' +
      unitHintHtml(unitView(r), i) + '</div>' +

      (mat
        ? '<div class="f"><label>Coverage</label>' +
          '<input class="n" data-tk="' + i + '" data-k="coverage" value="' +
          esc(nv(r.coverage)) + '" placeholder="' + esc(covPlaceholder(r)) + '">' +
          dfltWarnHtml('data-covwarn-for="' + i + '"', covRowWarn(r)) +
          '<p class="hint" data-covhint-for="' + i + '">' + esc(covHint(r)) + '</p></div>'
        : "") +

      '<div class="f"><label>Total cost</label>' +
      '<div class="costbox' + (rc.empty ? " empty" : "") + '" data-cost-for="' + i + '">' +
      esc(rc.text) + '</div>' +
      '<p class="hint" data-perunit-for="' + i + '">' +
      esc(p && p.per_unit != null ? B.money2(p.per_unit) + " / " + (r.unit || "SF") : "") +
      '</p></div>' +

      '</div>' + asmSavedCovNote(r, i, kind) + warn;
  }

  /** True when the row carries a coverage that actually changes its price: the same test
   *  priceAssemblyRow applies (a positive figure on a line of THIS assembly whose item the library
   *  still has), so the note and the arithmetic cannot disagree. A figure keyed to a line the
   *  assembly does not have, or to a line with no real item, prices nothing and earns no note. */
  function rowHasLineCov(r, asm) {
    var lc = r && r.line_cov;
    if (!lc || typeof lc !== "object") return false;
    var lines = (asm && asm.lines) || [];
    return lines.some(function (ln, j) {
      var id = ln && (ln.item_id || ln.item);
      return B.num(lc[j]) > 0 && !!id && !!L.findItem(ITEMS, id);
    });
  }

  /** An ASSEMBLY row has no coverage boxes (Hanz, 2026-10-12: "Remove these coverage for
   *  assemblies in the estimating tool. Just leave the Assembly name, measurement, unit and total
   *  cost."). A new row prices every line at the library's coverage, which is what a blank box did.
   *
   *  A row SAVED before that carries `line_cov`, and its total was made with those figures, so it
   *  keeps pricing with them: silently dropping them would move a bid someone already sent. With
   *  the boxes gone, the one honest thing to do is say so and offer the way back, which is a click
   *  that deletes `line_cov`. Nothing here ever deletes it by itself.
   *
   *  Empty string for every other kind of row, and for a line_cov that holds no positive figure
   *  (it prices exactly like none, so a note about it would be a lie). */
  function asmSavedCovNote(r, i, kind) {
    if (kind !== "asm" || !rowHasLineCov(r, asmById(r.assembly_id))) return "";
    return '<div class="asmcov-note" data-asmcov-note="' + i + '">' +
      '<p class="hint">This row uses coverage typed on this bid before.</p>' +
      '<button class="btn ghost sm" data-asmcov-reset="' + i + '">Use the library coverage</button></div>';
  }

  /** Redraw ONE row card, in place, class and inside.
   *
   *  THE PANEL IS WHAT MUST NOT BE REBUILT -- see the `change` handler's note, and the test it
   *  names. One card can be, and has to be: a kind change adds or removes a whole field, which no
   *  amount of repainting text can do. Addressed by `data-row-card`, never by position.
   *
   *  innerHTML plus className rather than outerHTML, because the node has to survive: everything
   *  keyed inside it is queried again by repaintNumbers straight afterwards. */
  function repaintRow(i) {
    var card = document.querySelector('[data-row-card="' + i + '"]');
    if (!card) return;
    card.className = rowCardClass(M.takeoff[i]);
    card.innerHTML = rowCardInner(M.takeoff[i], i);
  }

  // ── the Gyp section's own boxes (js/gyp-takeoff.js) ─────────────────────────────────────────
  var GYP_AREA_LABELS = { soft: "Soft surfaces", hard: "Hard surfaces", corridor: "Corridors" };

  /** What the Gyp sheet works out from the section on show, for the card, the caption and the Review step. */
  function gypFigures(entry) {
    return G.figures(entry.section.takeoff || [], entry.section.gyp, entry.sheet, itemsFor(entry.section.takeoff || []));
  }

  /** Text for a quantity of a thing the sheet buys in fractions: two places, no trailing zeros. */
  function gypQty(n) {
    return String(Math.round(B.num(n) * 100) / 100);
  }

  /** The Gyp card: the sheet to price on, the mix, the thickness of each area, the sound mat, ISO strip and the
   *  mobilizations. A blank thickness is the sheet's own (the placeholder says what it is), as a blank coverage
   *  is the library's. The boxes are keyed `data-gyp` and handled in the delegated listeners below. */
  function gypCard(entry) {
    var set = entry.section.gyp || {};
    var preset = G.presetOf(entry.sheet);
    var opt = function (value, label, on) {
      return '<option value="' + esc(value) + '"' + (on ? " selected" : "") + '>' + esc(label) + '</option>';
    };
    var sheets = G.tabs().map(function (tab) {
      return opt(tab, B.sheetLabel(tab), tab === entry.sheet);
    }).join("");
    var mixes = G.MIXES.map(function (m) { return opt(String(m.mix), m.label, m.mix === G.mixOf(set)); }).join("");
    var matId = G.matIdOf(entry.sheet, set);
    var mats = G.matList(entry.sheet).map(function (m) {
      var item = itemById(m.id);
      return opt(m.id, item ? item.name : m.id, m.id === matId);
    }).join("");
    var thick = G.BUCKETS.map(function (b) {
      var typed = set.thickness ? set.thickness[b] : "";
      var follows = b === "corridor" && preset.corridorFollowsSoft;
      var shown = follows ? G.thicknessOf(entry.sheet, set, "soft") : preset.thickness[b];
      return '<div class="f"><label>' + esc(GYP_AREA_LABELS[b]) + ' thickness</label>' +
        '<input class="n" data-gyp="thickness.' + b + '" inputmode="decimal" value="' + esc(nv(typed)) +
        '" placeholder="' + esc(String(shown === null ? preset.thickness[b] : shown)) + '">' +
        '<p class="hint">' + (follows ? 'Inches. Blank is the soft surface thickness, as the sheet has it.'
          : 'Inches. Blank is the sheet\'s ' + esc(String(preset.thickness[b])) + '.') + '</p></div>';
    }).join("");
    return '<div class="tk gyp" data-gyp-card>' +
      '<div class="tk-h"><span class="tag">GYPSUM</span>' +
      '<span class="tk-sub">What the sheet works the bags, sand and sound mat out of</span></div>' +
      '<div class="tk-g">' +
      '<div class="f"><label>Gyp sheet</label><select data-gyp="preset" aria-label="Gyp sheet">' + sheets + '</select>' +
      '<p class="hint">Sets the bag, primer, ISO strip, sound mat and thickness the sheet starts from.</p></div>' +
      '<div class="f"><label>Mix design</label><select data-gyp="mix" aria-label="Mix design">' + mixes + '</select>' +
      '<p class="hint">A stronger mix covers less from a bag.</p></div>' +
      thick +
      '<div class="f"><label>Sound mat</label><select data-gyp="sound_mat" aria-label="Sound mat">' + mats + '</select>' +
      '<p class="hint" data-gyp-truck>' + esc(gypTruckText(entry)) + '</p></div>' +
      '<div class="f"><label>ISO strip at all areas</label>' +
      B.sliderHtml(!!set.iso_all, 'data-gyp-iso="1"', set.iso_all ? "Yes" : "No",
        "Off puts ISO strip on the hard surfaces only") +
      '<p class="hint">Off is hard surfaces only.</p></div>' +
      '<div class="f"><label>Moisture tests</label>' +
      '<input class="n" data-gyp="moisture_tests" inputmode="decimal" value="' + esc(nv(set.moisture_tests)) + '">' +
      '<p class="hint">$' + esc(String(G.TOOLING.moistureTest)) + ' a test. Tooling and consumables are added for you.</p></div>' +
      '<div class="f"><label>Mobilizations</label>' +
      '<input class="n" data-gyp="mobs" inputmode="decimal" value="' + esc(nv(set.mobs)) + '">' +
      '<p class="hint">How many times the crew comes out. It sets the hours the sheet suggests on the Labor step.</p></div>' +
      '</div></div>';
  }

  /** The lines of a Gyp section's material that are not a takeoff row: what the sheet buys from the areas. Each is
   *  { label, qty, cost }. Rows are the page's own (the takeoff rows above them are priced as rows). */
  function gypLines(entry) {
    var f = gypFigures(entry);
    var p = f.parts;
    var lines = [];
    // `n`, `unit` and `one` are the same quantity as `qty` says it, apart: the number, its unit and the unit of one (the Review
    // step's Quantity, Unit and Rate columns).
    var add = function (label, qty, cost, n, unit, one) { lines.push({ label: label, qty: qty, cost: cost, n: n, unit: unit, one: one }); };
    if (f.primerGal > 0) add("Primer", gypQty(f.primerGal) + " gallons", p.primer, f.primerGal, "gallons", "gallon");
    if (f.isoRolls > 0) add("ISO strip", gypQty(f.isoRolls) + " rolls", p.iso, f.isoRolls, "rolls", "roll");
    if (f.tapeRolls > 0) add("Joint tape", gypQty(f.tapeRolls) + " rolls", p.tape, f.tapeRolls, "rolls", "roll");
    if (f.tons > 0) add("Sand", gypQty(f.tons) + " tons", p.sand, f.tons, "tons", "ton");
    if (f.rolls > 0) add("Sound mat", f.rolls + " rolls", p.soundMat, f.rolls, "rolls", "roll");
    return lines;
  }

  /** What the sound mat box says under it: the truckload, and where this job stands against it. */
  function gypTruckText(entry) {
    var f = gypFigures(entry);
    return "A truckload is " + f.truckload + " rolls" + (f.rolls ? "; this job has " + f.rolls : "") + ".";
  }

  /** The words under the Gyp rows (the inside of the caption): what is added for them, and the sound mat's
   *  truckload. */
  function gypCaptionText(entry) {
    var f = gypFigures(entry);
    if (f.problem) return 'Cannot be priced yet: ' + esc(f.problem) + '.';
    var lines = gypLines(entry);
    var bits = lines.map(function (l) {
      return esc(l.label) + ' ' + esc(l.qty) + ' <b>' + esc(moneyAuto(l.cost)) + '</b>';
    });
    var truck = f.rolls > 0
      ? ' The sound mat ships free from ' + f.truckload + ' rolls on this sheet (this job has ' + f.rolls + ').'
      : '';
    return 'Added for you from the areas above: ' + (bits.length ? bits.join(", ") : "nothing yet") + '.' + esc(truck) +
      ' Bags are not rounded up: ' + esc(gypQty(f.bags.total)) + ' in all.';
  }

  function gypCaption(entry) {
    return '<p class="cap" data-gyp-cap>' + gypCaptionText(entry) + '</p>';
  }

  function takeoffPanel() {
    // ONE BUTTON, AT THE TOP, IN THE PAGE'S OWN PRIMARY STYLE. It was two dashed buttons under
    // the last row until 2026-09-23 -- "+ Add another assembly" and "+ Add a material" -- on the
    // argument that which kind you want is known before you reach for either, so a menu would add
    // a click to both paths to save a button. Hanz: "These two buttons should be combined to one
    // and then it should just auto categorize based off the item or assemblie we want to add.
    // Also that button should be at the top and make it more visible." The argument was wrong in
    // the way that matters: you cannot know which kind you want before you have searched, and
    // guessing wrong quietly halved the library you were allowed to search.
    //
    // The row it adds still lands at the BOTTOM of the list, so the list keeps the order it was
    // built in and ROW n keeps meaning what it says. The caret goes with it -- see the handler --
    // which is what makes a button at the top and a row at the bottom read as one action.
    var gypSec = gypOpen();
    var html = gypSec ? gypCard(gypSec) : "";
    html += '<button class="btn addline" data-add-row="1">' + icon("plus", 16) +
      ' Add assembly or material</button>';
    html += M.takeoff.map(takeoffRowCard).join("");

    // ── the three that came off the intake form, 2026-09-16 ─────────────────────────────────
    // They are questions about the WORK, and the work is described here. On intake they sat among
    // questions about the building and the bid, where an estimator answered them before opening a
    // takeoff at all.
    //
    // NOT ONE SHAPE BUT TWO, and which one a card gets is decided by whether it BUYS anything --
    // see CONDITION_CARDS above. Joint Filler and Dye are material rows, columns and all, because
    // that is what they are: Hanz, 2026-09-19, "joint filler and die should have a measurement a
    // unit in a total cost and they should be a material not an assembly." Remove Existing is a
    // switch and a sentence, because it buys nothing on this screen.
    //
    // remove_existing_jf IS GATED ON joint_filler, which is the `needs` rule it carried on intake.
    // It adds a fourth hand to the joint-filler crew, so with no joint filler there is no crew for
    // it to be the fourth hand of. Gated, still written: a blank cell is not "No" to Kyle. DIMMED,
    // NOT HIDDEN AND NOT DISABLED -- `.mw-sw.inert`'s rule, and Travel's -- because the answer
    // still has to reach the downloaded .xlsx whichever way it points.
    //
    // ONLY THE ONES ON THE DEFAULTS TAB, and grayed until switched on -- Hanz, 2026-10-01:
    // "Everything that is in the defaults and labor tab in the Items and Assemblies appear as
    // grayed out options that can be enabled or not." One taken off the Defaults tab is not drawn
    // on a bid created after that; one that is switched on is always drawn (B.conditionShown).
    // A card not drawn still writes its "No" to Kyle's workbook through conditionCellWrites.
    //
    // REMOVE EXISTING FOLLOWS JOINT FILLER: its `needs` card hidden means there is no switch on this
    // page that could ever un-gray it, so it is not drawn either -- unless it is itself switched on.
    // These three are Polish's questions (dye, joint filler, remove existing), so another section has none.
    html += (activeTab === B.ROOT_TAB ? CONDITION_CARDS : []).filter(function (c) {
      if (!B.conditionShown(M, c.key)) return false;
      return !c.needs || B.conditionShown(M, c.needs) || !!(M.conditions || {})[c.key];
    }).map(function (c) {
      return c.cost ? condMaterialCard(c) : condSwitchCard(c);
    }).join("");

    html += '<p class="cap">Material total <b data-mat-total>' +
      esc(moneyAuto(materialTotal())) + '</b> · measured area <b data-area-total>' +
      esc(B.fmtSf(B.takeoffSf(M.takeoff))) + ' SF</b>. LF rows are priced like any other but do ' +
      'not count toward the square footage the price-per-SF is divided by.' +
      (M.takeoff.some(function (r) { return r && r.same_floor; })
        ? ' Default rows that share the floor carry the same square feet but are not added to ' +
          'it again.' : '') + '</p>';
    html += epoxyCaption();
    html += sealCaption();
    html += gypSec ? gypCaption(gypSec) : "";

    return shell("Material",
      "One row per assembly. The library prices it against the measurement you give it.", html);
  }

  /** What an Epoxy section charges that is not one of its rows, in words: the patch (a flat price on the whole
   *  area, always charged) and where the cove rows and the tooling are. "" for any other section. */
  function epoxyCaption() {
    var e = activeTab === B.ROOT_TAB ? null : openEntry();
    if (!e || e.role !== "epoxy") return "";
    var takeoff = e.section.takeoff || [];
    var r = E.sectionMaterial(takeoff, {
      items: itemsFor(takeoff), sf: B.takeoffSf(takeoff), rowPrice: function (row) { return rowPrice(row, takeoff); }
    });
    return '<p class="cap">Patch <b data-epoxy-patch>' + esc(moneyAuto(r.patch)) + '</b> is added for you: ' +
      esc(B.money2(E.unitPrice(ITEMS, "patch").cost)) + ' a square foot of the whole area, whatever the system. ' +
      'A cove row is priced the way the estimate sheet prices it, from its length. Tooling and consumables, ' +
      esc(moneyAuto(r.tooling)) + ', are added on the Review step.</p>';
  }

  /** What a Seal option charges that is not one of its rows, in words: the patch (a price a square foot of the whole
   *  area, always charged, at the renovation price when the job is a renovation) and where the tooling is. "" for any
   *  other section. */
  function sealCaption() {
    var e = activeTab === B.ROOT_TAB ? null : openEntry();
    if (!e || e.role !== "seal" || !SL) return "";
    var sf = B.takeoffSf(e.section.takeoff || []);
    var reno = jobIsReno();
    return '<p class="cap">Patch <b data-seal-patch>' + esc(moneyAuto(SL.patchCost(ITEMS, sf, reno))) + '</b> is added for you: ' +
      esc(B.money2(SL.unitPrice(ITEMS, reno ? "patchReno" : "patchNew").cost)) + ' a square foot of the whole area (' +
      (reno ? "a renovation" : "new concrete") + '), whatever the rows say. Tooling and consumables, ' +
      esc(moneyAuto(SL.toolingCost(sf))) + ', are added on the Review step.</p>';
  }

  /** THE PREVAILING WAGE CALCULATOR, as a card at the bottom of the Labor step (Hanz, 2026-10-15).
   *
   *  Kyle's workbook has this calculator on every priced tab (Polish!I47:L54): a Rate box, a Fringes box,
   *  the Prevailing Wage Rate they add up to (J48) and the 1:1 "Entry" Half Wage (J53, half the rate and
   *  never under $23, for the Missouri state wage only, not Davis-Bacon). Nothing in the sheet reads it,
   *  so the estimator worked the rate out there and typed it into every labor line. Here the card sets
   *  the labor lines itself: while its switch is on and a rate is set, every labor line prices at the
   *  prevailing rate except Travel Labor and a line where somebody typed a rate (B.laborRateOf).
   *
   *  The switch is the JOB's prevailing wage answer (conditions.prevailing_wage), the same flag the
   *  intake and the Review step use, so there is one source. Every trade has its own box (Cement Mason and
   *  Painter always, plus any the estimator adds and names, Hanz 2026-10-15), and the one marked "Labor lines
   *  use this rate" is the rate the lines follow. Rate and fringes start EMPTY on a new bid, like every quantity.
   *  The figures are the job's, so the card reads the same on every section of the bid.
   *
   *  OFF IS ONE LINE (Hanz, 2026-10-15): the title, the switch and the words "Off. Labor lines keep their own rates."
   *  Switching it on opens the trade boxes and + Add a trade. What was typed is kept while it is closed
   *  (the boxes are still there, only hidden), and the switch repaints the card IN PLACE (repaintNumbers), never a
   *  rebuild of the panel, so the focus stays on the switch and the keyboard can press it again. */
  function pwNote(total) {
    var on = !!(M.conditions || {}).prevailing_wage;
    if (!on) return "";
    // NAMES THE TRADE the lines use: "no rate yet" with figures typed on ANOTHER trade would be a sentence that
    // reads as false, and the bid would go out at the lines' own rates.
    if (!(total > 0)) return pwTradeLabel(M.prevailing) + " has no rate yet. Type its rate and fringes, or pick another " +
      "trade with Labor lines use this rate.";
    return "Labor lines price at " + B.money2(total) + " an hour. Travel Labor, and any rate you type on a line, keep their own." +
      (gypOpen() ? "" : " The 5% labor escalation is added on the review step.");
  }

  /** A trade's name as the card says it: the sheet's two by their names, one of the estimator's own by the
   *  name typed for it, or "Other trade" while it has none. */
  function pwTradeName(t) {
    var name = String((t && t.label) || "").trim();
    return name || "Other trade";
  }

  /** The name of the trade the crew is paid at. */
  function pwTradeLabel(p) {
    var t = B.prevailingCrewTrade(p || {});
    return t ? pwTradeName(t) : "";
  }

  function pwOwnTrade(t) {
    for (var i = 0; i < B.PREVAILING_TRADES.length; i++) if (B.PREVAILING_TRADES[i].key === t.key) return false;
    return true;
  }

  function pwSubText(p, total) {
    if (!(M.conditions || {}).prevailing_wage) return "Off. Labor lines keep their own rates.";
    return pwTradeLabel(p) + (total > 0 ? ", " + B.money2(total) + " an hour" : "");
  }

  /** ONE TRADE'S BOX on the card: its name, rate, fringes, the two figures the sheet works out, and the choice
   *  that makes it the rate the crew is paid. `i` is the trade's place in the block's `trades`, which every
   *  input carries (data-pw-i) so the handlers write the right one. The sheet's two trades are named by the
   *  card; a trade the estimator added has a name box and a Remove button. */
  function pwTradeBox(t, i, crewKey) {
    var total = B.prevailingTotal(t);
    var crew = t.key === crewKey;
    var own = pwOwnTrade(t);
    var name = pwTradeName(t);
    var money = function (field, label) {
      return '<div class="f"><label>' + label + '</label>' +
        '<span class="mny">$<input class="n" inputmode="decimal" data-pw="' + field + '" data-pw-i="' + i + '" value="' +
        esc(nv(t[field])) + '" aria-label="' + esc(name) + ' ' + label.toLowerCase() + ' per hour"></span></div>';
    };
    return '<div class="pwtrade' + (crew ? " paid" : "") + '" data-pw-trade="' + i + '"><div class="pwtrade-h">' +
      (own
        ? '<input class="pwname" data-pw="label" data-pw-i="' + i + '" value="' + esc(t.label) + '" maxlength="' +
          B.PREVAILING_LABEL_MAX + '" placeholder="Trade name" aria-label="Trade name">' +
          '<button class="x" data-pw-del="' + i + '" title="Remove this trade" aria-label="Remove ' + esc(name) + '">' +
          icon("x", 12) + '</button>'
        : '<span class="pwname static">' + esc(name) + '</span>') +
      '</div><div class="pwtrade-g">' + money("rate", "Rate") + money("fringes", "Fringes") +
      '<div class="f"><label>Prevailing wage rate</label>' +
      '<div class="costbox' + (total > 0 ? "" : " empty") + '" data-pw-total data-pw-i="' + i + '">' +
      esc(total > 0 ? B.money2(total) : "") + '</div></div>' +
      '<div class="f"><label>Entry half wage</label>' +
      '<div class="costbox' + (total > 0 ? "" : " empty") + '" data-pw-entry data-pw-i="' + i + '">' +
      esc(total > 0 ? B.money2(B.entryHalfWage(total)) : "") + '</div></div></div>' +
      '<label class="pwpay"><input type="radio" name="pw-pay" data-pw-pick="' + i + '" value="' + esc(t.key) + '"' +
      (crew ? " checked" : "") + '> Labor lines use this rate</label></div>';
  }

  function prevailingCard() {
    var p = B.normalizePrevailing(M.prevailing) || B.normalizePrevailing({});
    var on = !!(M.conditions || {}).prevailing_wage;
    var total = B.prevailingTotal(p);
    return '<div class="tk pwcard' + (on ? "" : " inert off") + '" data-pw-card><div class="tk-h">' +
      '<span class="labname static">Prevailing wage</span>' +
      B.sliderHtml(on, 'data-cond="prevailing_wage" data-pw-sw="1"', "On", "The job's prevailing wage switch, the same one " +
        "as on the intake and Review steps. On sets the labor lines to this rate and adds the 5% labor escalation") +
      '<span class="tk-sub calc" data-pw-sub>' + esc(pwSubText(p, total)) + '</span>' +
      // THE BODY, hidden while the switch is off. A wrapper with nothing but the attribute on it: the page's own
      // `[hidden]{display:none!important}` hides it, and the grid inside keeps its own `display` untouched.
      '</div><div data-pw-body' + (on ? "" : " hidden") + '><div class="pwtrades">' +
      p.trades.map(function (t, i) { return pwTradeBox(t, i, p.trade); }).join("") +
      '</div><button class="btn addline below" data-pw-add="1">' + icon("plus", 16) + ' Add a trade</button>' +
      '<p class="hint trvnote">Rate plus fringes is the prevailing wage rate. Entry half wage is the 1:1 entry ' +
      'laborer, Missouri state wage only, not Davis-Bacon. Foreman min. ' + esc(B.money(B.PREVAILING.FOREMAN_MIN)) +
      ', entry min. ' + esc(B.money(B.PREVAILING.ENTRY_MIN)) + '.</p>' +
      '<p class="hint trvnote" data-pw-note>' + esc(pwNote(total)) + '</p></div></div>';
  }

  /** Write one box of the Prevailing wage card into the job (`M.prevailing`, kept at the root with the
   *  other job-level answers). `i` is the trade's place on the card. `field` is read off an attribute, so it
   *  is matched against the names below and written to a named property, never used as a key. "pick" makes
   *  that trade the one the crew is paid; "label" names one of the estimator's own trades (the sheet's two
   *  keep their names). The first write on a bid creates the block. */
  function setPrevailing(field, value, i) {
    var cur = B.normalizePrevailing(M.prevailing) || B.normalizePrevailing({});
    var t = cur.trades[i];
    if (!t) return;
    if (field === "pick") cur.trade = t.key;
    else if (field === "rate") t.rate = value;
    else if (field === "fringes") t.fringes = value;
    else if (field === "label" && pwOwnTrade(t)) t.label = value;
    else return;
    // THE FIRST FIGURES TYPED PICK THEIR TRADE. While the trade the lines use has no rate, typing a rate or fringes on
    // another one makes that one the trade the lines use: an estimator on a painting job who types the Painter box and
    // never looks at the radio must not send the bid out at the lines' own rates. Once the picked trade has a rate,
    // typing another trade's figures moves nothing; picking is then the radio's job.
    if ((field === "rate" || field === "fringes") && t.key !== cur.trade && B.prevailingTotal(t) > 0 &&
        !(B.prevailingTotal(B.prevailingCrewTrade(cur)) > 0)) cur.trade = t.key;
    M.prevailing = B.normalizePrevailing(cur);
  }

  /** + Add a trade: a new box with no name and no figures, after the others. Returns its place. */
  function addPrevailingTrade() {
    var cur = B.normalizePrevailing(M.prevailing) || B.normalizePrevailing({});
    cur.trades.push({ key: B.newPrevailingTradeKey(cur), label: "", rate: "", fringes: "" });
    M.prevailing = B.normalizePrevailing(cur);
    return M.prevailing.trades.length - 1;
  }

  /** Remove one of the estimator's own trades (the sheet's two stay). When it was the one the crew was paid,
   *  the crew goes back to the first trade, Cement Mason. */
  function removePrevailingTrade(i) {
    var cur = B.normalizePrevailing(M.prevailing);
    if (!cur || !cur.trades[i] || !pwOwnTrade(cur.trades[i])) return false;
    var gone = cur.trades.splice(i, 1)[0];
    if (cur.trade === gone.key) cur.trade = cur.trades[0].key;
    M.prevailing = B.normalizePrevailing(cur);
    return true;
  }

  /** One labor task, as its own card.
   *
   *  ONE CARD PER TASK BECAUSE THAT IS HOW THE SHEET READS. Kyle's Polish tab heads each task
   *  separately -- `Labor: Guys | Days | Rate`, then `Mock-Up:`, then `Joint Filler:`, then
   *  `Travel: Guys | HOURS` -- rather than running them as one table under one header. A single
   *  table cannot say that Travel's middle column means something different from the three above
   *  it, which is exactly the thing an estimator has to notice.
   *
   *  Same `.tk` vocabulary as takeoffPanel's rows, deliberately: it is the card pattern this page
   *  already uses one step earlier, so Takeoff and Labor read as the same screen.
   *
   *  Every data- attribute the delegated handlers and the harness rely on is unchanged --
   *  `data-lab` + `data-k` on the inputs, `data-lcost-for` on the cost box, `data-del-lab` -- and
   *  `i` is still the row's real index in M.labor, which is what the delete splices by. */
  function laborCard(r, i) {
    var hours = r && r.unit === "hours";
    // Travel is the one hours row with a driving meaning: on a far job its guys follow the crew's size (the most guys on any labor
    // line; a bid saved before 2026-10-12 still on auto follows the man-days) and it dims on a local job. A crew line priced by
    // the hour (a Gyp pour) is an ordinary line whose second box is hours.
    var travelRow = travelLike(r);
    var auto = !!(hours && r.guys_auto);
    // A Travel Labor row on an option follows its OWN section's lines, and one on a base that does not carry the job's travel is a
    // leftover of a carrier move that says so (B.strayTravelNote).
    var ownCrew = activeIsOption();
    var stray = travelRow && r.id === "travel" && holdsStrayTravel();
    // WHERE THE HOURS CAME FROM, when the distance wrote them (Hanz, 2026-10-20): said full width under the card, and "" (the line
    // hidden) while the hours are typed or empty. repaintNumbers keeps it current as the miles, the crew and the boxes move.
    var srcNote = travelRow ? B.driveHoursNote(M, r, M.labor, ownCrew) : "";
    // Dimmed, not disabled, and not hidden: `.sw.inert`'s rule, for `.sw.inert`'s reason. A local
    // job that does need drive time must not send somebody back to the intake step to type it,
    // and a row that vanished would take an estimator's typed hours with it. Untouched only --
    // see laborInert -- so typing in either box beside it un-dims the card live.
    var inert = laborInert(r);
    // NO "TYPE MY OWN" SWITCH (Hanz, 2026-10-07). The Guys box is editable, so a control to ask
    // for permission to type was a second way to do what the box already does. A NEW bid's box opens
    // EMPTY and stays the estimator's (2026-10-12); only a bid saved before then (its guys are the
    // man-days), or Travel Labor on a job the distance sent far (its guys are the crew's size,
    // 2026-10-20), can be on auto, and typing a number makes it the estimator's own (guys_auto
    // false, and the row is marked so no answer writes into it again). The "Included"
    // slider is a different thing and stays.
    var on = B.rowOn(r);
    // THE PREVAILING RATE IN FORCE (0 when the card is off or empty): a line that follows its default
    // prices at it, and its Rate box says so. One figure for the box, the cost and the warning.
    var pw = B.prevailingApplied(M);
    return '<div class="tk lab' + ((inert || !on) ? " inert" : "") + (on ? "" : " off") +
      '" data-lab-card="' + i +
      '"><div class="tk-h">' +
      '<input class="labname" data-lab="' + i + '" data-k="label" value="' + esc(nv(r.label)) +
      '" placeholder="Task" aria-label="Task name">' +
      B.sliderHtml(on, 'data-on-lab="' + i + '"', "Included", "Off keeps this line here, grayed, " +
        "and adds nothing to the price") +
      '<span class="tk-sub calc" data-lcost-for="' + i + '">' +
      esc(moneyAuto(B.laborCost(r, pw))) + '</span>' +
      (M.labor.length > 1
        ? '<button class="x" data-del-lab="' + i + '" title="Remove this line">' + icon("x", 12) + '</button>'
        : '') +
      '</div><div class="tk-g lab-g">' +

      '<div class="f"><label>Guys</label>' +
      '<input class="n" data-lab="' + i + '" data-k="guys" value="' +
      esc(nv(r.guys)) + '"' + (auto ? ' data-auto="1"' : '') + '>' +
      dfltWarnHtml('data-calcwarn="' + i + ':guys"', calcDefaultText(r, "guys")) +
      // "Guys", never "Crew" -- Hanz renamed that column and
      // test_nothing_on_screen_says_labour_or_crew holds the page to it.
      '<p class="hint" data-hint-lab="' + i + '">' + (travelRow ? B.travelGuysHint(M, r, M.labor, ownCrew)
        : 'How many on it.') + '</p></div>' +

      '<div class="f"><label>' + (hours ? "Hours" : "Days") + '</label>' +
      '<input class="n" data-lab="' + i + '" data-k="days" value="' + esc(nv(r.days)) + '">' +
      dfltWarnHtml('data-calcwarn="' + i + ':days"', calcDefaultText(r, "days")) +
      '<p class="hint">' + (travelRow ? "Drive time, each way counted." : (hours ? "Hours on the job." : "How long it takes.")) +
      '</p></div>' +

      '<div class="f"><label>Rate</label>' +
      '<span class="mny">$<input class="n" data-lab="' + i + '" data-k="rate" value="' +
      esc(nv(B.laborRateBox(r, pw))) + '"></span>' +
      dfltWarnHtml('data-ratedflt-for="' + i + '"', rateDefaultText(r, pw)) +
      '<p class="hint">Per hour.</p></div>' +

      '<div class="f"><label>Cost</label>' +
      '<div class="costbox' + (B.laborCost(r, pw) > 0 ? "" : " empty") + '" data-lcostbox-for="' + i + '">' +
      esc(moneyAuto(B.laborCost(r, pw))) + '</div>' +
      '<p class="hint">' + (hours ? "guys × hours × rate" :
        "guys × days × rate × " + B.dayHours(r)) + '</p></div>' +
      // HOURS A DAY, only on a line the Labor Calculator filled (it carries calc_default): 8 or 10.
      (r.calc_default && !hours
        ? '<div class="f"><label>Hours a day</label><select data-lab="' + i +
          '" data-k="hours_per_day" aria-label="Hours a day">' +
          [8, 10].map(function (h) {
            return '<option value="' + h + '"' + (B.dayHours(r) === h ? " selected" : "") + '>' + h +
              '</option>';
          }).join("") + '</select>' +
          dfltWarnHtml('data-calcwarn="' + i + ':hours_per_day"', calcDefaultText(r, "hours_per_day")) +
          '</div>'
        : "") +

      '</div>' + (travelRow
        // The note on where the hours came from (B.driveHoursNote). Always drawn on the travel card, hidden while there is
        // nothing to say, so the live repaint can bring it in and out without a rebuild. `hidden` holds on this page
        // (`[hidden]{display:none!important}`).
        ? '<p class="hint trvnote" data-trv-src="' + i + '"' + (srcNote ? '' : ' hidden') + '>' + esc(srcNote) + '</p>' +
        // Rendered unconditionally on hours rows -- CSS (`.lab:not(.inert) .inertline`) decides
        // whether it shows, so the card's class is the one source of truth for both the dimming
        // and the caption, and the two cannot drift apart on a live repaint.
        '<p class="inertline">This job is marked local, so no travel is expected — type here ' +
          'anyway if it needs drive time.</p>' +
          // A TRAVEL LABOR ROW ON A BASE THAT DOES NOT CARRY THE JOB'S TRAVEL is a leftover of a carrier move: the job's one drive is
          // charged on the carrier, so this card says so (typed figures were left as typed) instead of promising a fill it will not get.
          (stray
            ? '<p class="hint trvnote" data-trv-stray="' + i + '">' + esc(B.strayTravelNote(carrierName(), r)) + '</p>'
            // WHAT THE LINE PROMISES IS WHAT IT DOES. A job on any sheet but Gyp fills the hours from the miles and the guys
            // with the crew's size (B.followDistanceHours); a Gyp bid fills nothing here (the Gyp sheet works its own drive
            // time), so its card must not say the hours "fill in".
            : '<p class="hint trvnote">Drive time is expected at 70 miles or more from the office. ' +
              (r.id !== "travel" ? ''
                : gypOpen()
                  ? 'A Gyp bid does not fill this line in from the miles: type its guys and its hours. '
                  : 'There the hours fill in from the miles, one round trip, and the guys are the most on any labor line. ') +
              'Under 70 miles this line stays gray.</p>')
        : "") + '</div>';
  }

  /** Is a Lodging / Per Diem card dimmed? Off is gray, and so is a LOCAL job (under 70 miles) the
   *  estimator has not touched -- the rule Travel Labor's card already follows (laborInert). A line
   *  somebody flipped by hand (`hand`) is theirs, so it lifts the dim. ONE FUNCTION for the first
   *  paint and the live repaint, like laborInert. */
  function travelInert(l) {
    return !!(M.conditions || {}).local && !(l && l.hand);
  }

  /** One of the two travel cost lines (Lodging, Per Diem) as a card, in the `.tk lab` vocabulary
   *  the labor cards use so the three travel lines read as one family. `key` is "lodging" or
   *  "per_diem". Quantity is nights / days; while it is auto it is the crew's man-days (the way
   *  backend/pricing.py counts them) and the box says so; typing flips it to the estimator's own. */
  function travelCard(key) {
    var l = (M.travel || {})[key] || {};
    var on = !!l.enabled;
    var auto = l.qty_auto !== false;
    var isNight = key === "lodging";
    var inert = travelInert(l);
    var unitWord = isNight ? "Nights" : "Days";
    var cost = B.travelLineCost(l, M.labor, B.travelOpts(ROOT, activeTab));
    return '<div class="tk trv' + ((inert || !on) ? " inert" : "") + (on ? "" : " off") +
      '" data-trv-card="' + key + '"><div class="tk-h">' +
      '<span class="labname static">' + esc(l.label || (isNight ? "Lodging" : "Per Diem")) + '</span>' +
      B.sliderHtml(on, 'data-on-trv="' + key + '"', "Included", "Off keeps this line here, " +
        "grayed, and adds nothing to the price") +
      '<span class="tk-sub calc" data-trvcost-for="' + key + '">' + esc(moneyAuto(cost)) + '</span>' +
      '</div><div class="tk-g lab-g trv-g">' +
      '<div class="f"><label>' + unitWord + '</label>' +
      '<input class="n" data-trv="' + key + '" data-k="qty" value="' + esc(nv(l.qty)) + '"' +
      (auto ? ' data-auto="1"' : '') + '>' +
      '<p class="hint" data-hint-trv="' + key + '">' + B.lodgingHint(ROOT, activeTab, auto, M.labor) + '</p></div>' +
      '<div class="f"><label>Rate</label>' +
      '<span class="mny">$<input class="n" data-trv="' + key + '" data-k="rate" value="' +
      esc(nv(l.rate)) + '"></span>' +
      dfltWarnHtml('data-trvdflt-for="' + key + '"', travelRateDefaultText(l)) +
      '<p class="hint">' + (isNight ? "Per night." : "Per day.") + ' Set under Items &amp; ' +
      'Assemblies, Labor tab.</p></div>' +
      '<div class="f"><label>Cost</label>' +
      '<div class="costbox' + (cost > 0 ? "" : " empty") + '" data-trvcostbox-for="' + key + '">' +
      esc(moneyAuto(cost)) + '</div>' +
      '<p class="hint">' + unitWord.toLowerCase() + ' × rate</p></div>' +
      '</div><p class="hint trvnote">' + (isNight
        ? "Overnight stays are expected at 70 miles or more from the office. Under 70 miles " +
          "this line stays gray."
        : "Meals while the guys are away, expected at 70 miles or more from the office. Under " +
          "70 miles this line stays gray.") + '</p></div>';
  }

  // ── distance decides "local" ────────────────────────────────────────────────
  // The intake's "Local job" switch is gone (Kyle 9/18; Hanz, 2026-10-05). The server works the
  // driving miles from the Olathe office to the job address out (POST /api/distance, free Census geocoder + OSRM)
  // and B.applyDistance turns them into the hidden `conditions.local` answer, which is still what
  // Polish!B4 is written from. >= 70 miles: the three travel lines come on. < 70: they gray.
  //
  // THE LOOKUP NEVER BLOCKS ANYTHING. It starts after the first paint, has its own timeout, and
  // any failure leaves the page exactly as it was with "Distance unknown -- enter miles" and a
  // box to type the number in. Nothing is guessed. A typed figure always wins, and a Lodging /
  // Per Diem line the estimator flipped by hand is never moved by an answer (B.applyDistance).
  //
  // ONLY A NEW BID LOOKS IT UP BY ITSELF. A saved bid opened later does not reprice behind
  // anybody's back: it shows what it was saved with and offers the button.
  //
  // A FAR ANSWER ALSO FILLS TRAVEL LABOR, KYLE'S WAY (Hanz, 2026-10-20): its hours from the miles (one round trip), its
  // guys the crew's size, so each guy is charged one trip as on his own sheets. A figure the estimator typed in a box, or
  // cleared, always wins, and a switched-off row is left as it is (B.applyDistance, B.clearDistance, B.followDistanceHours).
  // It is given the WHOLE model (ROOT), not the section on show: the Travel Labor row is the carrier section's.
  var distBusy = false;
  var distReason = "";
  var DIST_REASONS = {
    incomplete: "Add the street, city and state on the intake step, or type the miles.",
    no_key: "The distance service is not set up yet. Type the miles.",
    not_found: "That address could not be found. Check it on the intake step, or type the miles.",
    busy: "Too many lookups just now. Type the miles, or try again in a few minutes.",
    error: "The distance lookup did not answer. Type the miles, or try again."
  };

  function addressKey() {
    var s = TW.getState() || {};
    return B.distanceKey(s.address, s.city, s.state, s.zip);
  }

  function distanceStatus() {
    if (distBusy) return "Looking up the driving distance…";
    var d = M.distance;
    if (d && d.source === "google" && addressKey() && d.key !== addressKey()) {
      return "The address changed since this was measured. Look it up again, or type the miles.";
    }
    if (!d && distReason) return DIST_REASONS[distReason] || DIST_REASONS.error;
    if (!d) return "Type the miles from the office, or look it up from the job address.";
    return "";
  }

  function distanceBlock() {
    var d = M.distance;
    return '<div class="trvdist" data-dist>' +
      '<p class="cap"><b data-dist-note>' + esc(B.distanceNote(M)) + '</b> ' +
      '<span class="hint" data-dist-status>' + esc(distanceStatus()) + '</span></p>' +
      '<div class="distrow"><label>Miles from the office</label>' +
      '<input class="n" inputmode="decimal" data-dist-miles value="' +
      esc(d && d.miles != null ? d.miles : "") + '">' +
      '<button type="button" class="btn" data-dist-lookup>Look it up from the address</button></div>' +
      '</div>';
  }

  /** Repaint the distance note and the three travel lines in place: no rebuild, so a caret
   *  somewhere else on the page is not stolen when the server's answer lands. */
  function paintDistance() {
    var note = document.querySelector("[data-dist-note]");
    if (note) note.textContent = B.distanceNote(M);
    var how = document.querySelector("[data-trv-how]");
    if (how) how.textContent = B.travelHow(M).text;
    var st = document.querySelector("[data-dist-status]");
    if (st) st.textContent = distanceStatus();
    var box = document.querySelector("[data-dist-miles]");
    if (box && document.activeElement !== box) {
      var v = M.distance && M.distance.miles != null ? String(M.distance.miles) : "";
      if (box.value !== v) box.value = v;
    }
    document.querySelectorAll("[data-on-trv]").forEach(function (el) {
      var l = M.travel && M.travel[el.getAttribute("data-on-trv")];
      if (!l) return;
      el.className = "mw-sw" + (l.enabled ? " on" : "");
      el.setAttribute("aria-checked", l.enabled ? "true" : "false");
    });
  }

  /** Ask the server for the miles and apply them. `force` is the estimator pressing the button:
   *  it replaces a typed figure too, because they asked. Without it a typed figure, or a figure
   *  already measured for this exact address, is left alone. Never throws. */
  async function lookupDistance(force) {
    var s = TW.getState() || {};
    var key = B.distanceKey(s.address, s.city, s.state, s.zip);
    if (!key) { distReason = "incomplete"; paintDistance(); return; }
    if (!force && M.distance && (M.distance.source === "typed" || M.distance.key === key)) return;
    var model = M, whole = ROOT;
    distBusy = true; distReason = "";
    paintDistance();
    var miles = null, reason = "error";
    try {
      var res = await api("/api/distance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: s.address || "", city: s.city || "", state: s.state || "",
                               zip: s.zip || "" }),
        signal: (typeof AbortSignal !== "undefined" && AbortSignal.timeout)
          ? AbortSignal.timeout(14000) : undefined
      });
      var j = await res.json();
      miles = B.milesOrNull(j && j.miles);
      reason = (j && j.reason) || "error";
    } catch (e) { miles = null; }
    distBusy = false;
    // The page can have moved to another draft, or the estimator can have typed miles while the
    // answer was on its way. Theirs wins; this answer is dropped.
    if (model !== M || whole !== ROOT || (!force && M.distance && M.distance.source === "typed")) { paintDistance(); return; }
    if (miles === null) { distReason = reason; paintDistance(); return; }
    B.applyDistance(ROOT, { miles: miles, source: "google", key: key });
    changed(false);
    paintDistance();
  }

  /** What the Gyp sheet works the labor hours out to, quoted beside the boxes: the figure the workbook would have,
   *  with the crew it uses. The hours are the estimator's to type; this is the sheet's own answer to check them by. */
  function gypHoursCaption(entry) {
    var f = gypFigures(entry);
    var mobs = B.num((entry.section.gyp || {}).mobs);
    var h = G.sheetHours(f, mobs, M.distance && M.distance.miles);
    var hrs = function (n) { return gypQty(n) + " hours"; };
    var bits = [
      "Prep, prime and seal " + hrs(h.prep) + " (" + G.HOURS.prepPerMob + " hours a mobilization)",
      "Mat time " + hrs(h.mat) + " (the hard surfaces at " + G.HOURS.matSfPerHour + " SF an hour)",
      "Pour " + hrs(h.pour) + " (" + gypQty(f.bags.total) + " bags at " + G.HOURS.poursPerHour + " an hour)",
      "Semi delivery unload " + hrs(h.unload) + " (" + G.HOURS.unloadPerMob + " hours a mobilization)"
    ];
    return '<p class="cap" data-gyp-hours>The sheet works these out for ' + (mobs > 0 ? mobs : "no") +
      ' mobilizations: ' + esc(bits.join("; ")) + '. Pre-pour hours are typed on the sheet. The sheet\'s crews are ' +
      G.CREWS.prePour + ', ' + G.CREWS.prep + ', ' + G.CREWS.mat + ', ' + G.CREWS.pour + ' and ' + G.CREWS.unload +
      ' guys.</p>';
  }

  function laborPanel() {
    // Travel Labor is its own block, below a dividing line, with Lodging and Per Diem. Every other
    // task keeps its place above it. `i` stays the row's real index in M.labor -- the handlers
    // splice and edit by position.
    if (!M.travel) M.travel = B.normalizeTravel(null);
    // THE PREVAILING WAGE CARD is drawn LAST, at the bottom of every section's Labor step (Hanz, 2026-10-15:
    // "prevailing wage should be at the bottom not at the top"), after the crew lines and the travel block.
    var html = "";
    var travelRows = "";
    // The job's travel is charged ONCE, on the section that carries it (B.travelCarrier). Any other section of a
    // combo bid has no Travel block to draw: its crew is priced as labor and nothing else (see travelNote).
    var carries = carriesTravel();
    M.labor.forEach(function (r, i) {
      if ((r || {}).id === "travel" && carries) travelRows += laborCard(r, i);
      else html += laborCard(r, i);
    });

    // Same control as the takeoff step's, below the list rather than above it: this one adds a
    // row you then name yourself, so there is nothing to search and nothing to scroll back to.
    html += '<button class="btn addline below" data-add-lab="1">' + icon("plus", 16)
      + ' Add a labor line</button>';
    html += '<p class="cap">Labor total <b data-labor-total>' +
      esc(moneyAuto(B.laborTotal(M.labor, M.conditions, B.prevailingApplied(M)))) + '</b>.</p>';

    if (!carries) {
      html += '<div class="trvsep" role="separator"><span>Travel</span></div>' +
        '<p class="cap" data-travel-note>' + esc(travelNote()) + '</p>';
    } else {
      html += '<div class="trvsep" role="separator"><span>Travel</span></div>' +
        '<p class="cap">Travel is expected when the job is 70 miles or more from the office. Under ' +
        '70 miles all three lines below stay gray until you switch one on.</p>';
      html += distanceBlock();
      // HOW IT IS WORKED OUT: the local-or-not call and the sums, in words. Text only (one element,
      // pre-line), so the live repaint can replace it without touching anything the estimator is in.
      html += '<p class="cap trvhow" data-trv-how>' + esc(B.travelHow(M).text) + '</p>';
      html += travelRows + travelCard("lodging") + travelCard("per_diem");
      html += '<p class="cap">Lodging and Per Diem total <b data-travel-total>' +
        esc(moneyAuto(B.travelCosts(M.travel, M.labor, B.travelOpts(ROOT, activeTab)).total)) + '</b>, added before the markups.</p>';
    }

    var pw = !!(M.conditions || {}).prevailing_wage;
    var gypLab = gypOpen();
    html += gypLab
      ? '<p class="cap">A Gyp bid adds the 5% labor escalation whatever prevailing wage says (the sheet types it in).</p>'
      : '<p class="cap">Prevailing wage is <b data-pw-state>' + (pw ? "on" : "off") + '</b>' +
        '<span data-pw-esc>' + (pw ? ", so a 5% escalation is added on the review step" : "") + '</span>' +
        '. Change it with the switch on the Prevailing wage card, or on <a href="' + esc(TW.withDraft("/polish-intake.html")) +
        '">the intake step</a>.</p>';
    if (gypLab) html += gypHoursCaption(gypLab);
    html += prevailingCard();

    return shell("Labor",
      gypLab ? "Guys × hours × rate. A Gyp crew is priced by the hour, in 10 hour days. Travel is priced per hour."
        : "Guys × days × rate, at " + B.HOURS_PER_DAY + " hours a day. Travel is priced per hour.",
      html);
  }

  // ── review ──────────────────────────────────────────────────────────────────
  /** A Review card. `key` is its colour (data-rev, see the --rev-* tokens in polish-estimate.html).
   *
   *  THE HEADER CARRIES NO FIGURE (Hanz, 2026-10-12): the total sits once, on the card's own last
   *  row, where it is also keyed for repaintNumbers. The header used to repeat it at the far right
   *  and had no repaint hook, so it could go stale while the row below it moved. The attribute is
   *  written BEFORE class on purpose: tests cut the review html at 'class="rev"'. */
  function card(title, step, key, inner) {
    return '<div data-rev="' + key + '" class="rev"><div class="rev-h">' + esc(title) +
      ' <button data-go="' + step + '">Edit</button></div>' + inner + '</div>';
  }

  /** THE REVIEW TABLES SHOW HOW EVERY FIGURE WAS WORKED OUT (Hanz, 2026-10-19: "show the break down of any thing that has a
   *  total ... how its solved or how it got to that price. Make sure to label the columns as price/sf, SF or LF etc.").
   *  Every card is a table with a header row and five columns: Item | Quantity | Unit | Rate | Total. A row that has a total
   *  shows the working in front of it, and every figure in the working is the figure the chain priced with, read from the
   *  same code that priced it (the row's own price, the module's own patch rate, the chain's own bases), never retyped.
   *
   *  rows: [label, quantity, unit, rate, total, rowClass]. Each of the first four may be text (escaped) or `{ raw: "<...>" }`;
   *  `total` is HTML (an amount the chain computes, built by mkAmt or rv).
   *
   *  `label` is escaped by default -- most of it is user data (an assembly name, a labor line's own typed label) and has to
   *  be. A label that needs a real control (Labor escalation's prevailing-wage switch) passes `{ raw }` instead of a bare
   *  string, so that one label opts out explicitly rather than this function guessing "looks like HTML" on a string that
   *  could just as easily be a customer's literal `<` in an assembly name.
   *
   *  The table sits in a box that scrolls on its own, so a narrow phone scrolls the table and never the page. */
  function revTable(rows) {
    return '<div class="tscroll"><table class="rev-t"><thead>' + REV_HEAD + '</thead><tbody>' + rows.map(function (r) {
      return '<tr' + (r[5] ? ' class="' + r[5] + '"' : '') + '><td>' + revCell(r[0]) + '</td><td class="q r">' + revCell(r[1]) +
        '</td><td class="u">' + revCell(r[2]) + '</td><td class="rt r">' + revCell(r[3]) + '</td><td class="r">' +
        (r[4] == null ? "" : r[4]) + '</td></tr>';
    }).join("") + '</tbody></table></div>';
  }

  var REV_HEAD = '<tr><th>Item</th><th class="r">Quantity</th><th>Unit</th><th class="r">Rate</th><th class="r">Total</th></tr>';

  function revCell(v) {
    return (v && typeof v === "object" && "raw" in v) ? v.raw : esc(v == null ? "" : v);
  }

  /** A figure of the working that moves with a keystroke on the Review step, keyed `data-rv`. Writing the Review also fills
   *  FIGS (key -> text), and repaintNumbers writes the Review again into FIGS and copies each text onto the cell with its key:
   *  the first paint and the repaint are one code path, so they cannot disagree, and no box being typed in is ever rebuilt. */
  var FIGS = null;
  function rv(key, text) {
    var t = text == null ? "" : String(text);
    if (FIGS) FIGS[key] = t;
    return '<span data-rv="' + esc(key) + '">' + esc(t) + '</span>';
  }
  /** rv for a Quantity, Unit or Rate cell, whose strings revTable escapes: the keyed span goes in as markup. */
  function rvc(key, text) { return { raw: rv(key, text) }; }

  /** An amount the chain computes, keyed so repaintNumbers can refresh it without a rebuild. */
  function mkAmt(b, key) {
    return '<span data-mk="' + key + '">' + esc(moneyAuto(b[key])) + '</span>';
  }

  /** A rate per unit as the Material step's hint says it: "$1.57 / SF". Nothing when it cannot be said. */
  function perUnitText(per, unit) {
    return (per === null || per === undefined || !isFinite(per)) ? "" : B.money2(per) + " / " + unit;
  }

  /** A Review rate that quantity x rate has to come back to: exactRate's places, not the cent the Material step's hint
   *  rounds to (5,482 SF at "$1.85 / SF" read $25 short of a $10,166.55 row). A pack-priced row's rate is its cost over
   *  its measurement, so it is said to four places; the row's own total stays the figure the chain priced. */
  /** An hourly or nightly rate as typed: whole dollars or cents as typed, and a third place only when the rate has one (a prevailing rate). */
  function rateMoney(n) {
    var v = B.num(n);
    return Math.abs(v * 100 - Math.round(v * 100)) < 1e-6 ? moneyAuto(v) : exactRate(v);
  }

  function reviewPerUnit(per, unit) {
    return (per === null || per === undefined || !isFinite(per)) ? "" : exactRate(per) + " / " + unit;
  }

  /** A price per unit worked to the figure it has: two places, and more only when the rate has them ($0.0987), so
   *  quantity x rate is the total the module charged. */
  function exactRate(n) {
    var v = parseFloat(Number(n).toFixed(4));
    var two = v.toFixed(2);
    return Math.abs(v - parseFloat(two)) < 1e-9 ? "$" + two : "$" + String(v);
  }

  /** The bases of the markup lines, each taken from the chain's own arithmetic (bid-engine.js priceChain) out of the bid's
   *  own figures. A base that is not a plain sum, or that the figures cannot say (a bid with no such line), is null and the
   *  row shows its % and its total only: the REMODEL base depends on the profile (the sheet's profiles add the tooling and
   *  the travel), and is the one of the two sums whose rate gives the tax the chain charged.
   *  GP is not here on purpose: it is a gross-up (price = cost / (1 - GP)), not a % of anything. */
  function markupBases(b) {
    var n = B.num;
    var hb = n(b.hard_bid), sales = n(b.sales_tax), fees = n(b.fees), cont = n(b.contingency), gp = n(b.gp);
    var sub = n(b.sub_total);
    var out = { disc: sub + gp, sales: n(b.material_total) };
    out.super = sub + gp + hb + cont + sales + fees;
    out.soft = out.super + n(b.super_pto);
    // The tax or bond the chain charged is ROUNDUP(base x rate): the base whose product rounds up to it is the base it used.
    var gives = function (base, p, amt) { p = n(p); return p > 0 && base * p <= n(amt) + 1e-4 && base * p > n(amt) - 1 - 1e-4; };
    var rem = n(b.labor) + n(b.escalation) + n(b.burden) + gp + hb + n(b.super_pto) + n(b.soft_costs) + cont + fees;
    var remSheet = rem + n(b.tooling) + n(b.travel);
    out.remodel = gives(remSheet, b.remodel_pct, b.remodel_tax) ? remSheet : (gives(rem, b.remodel_pct, b.remodel_tax) ? rem : null);
    // The bond counts both taxes twice (the sheet's odd rule 1).
    var bondBase = sub + gp + hb + n(b.super_pto) + n(b.soft_costs) + cont + sales + n(b.remodel_tax) + n(b.taxes) + fees;
    out.bond = gives(bondBase, b.bond_pct, b.bond) ? bondBase : null;
    return out;
  }

  /** The takeoff-card line the sheet charges by the square foot of the whole area: the patch. `label` is the row's words
   *  (HTML), `rate` the module's own price of one SF (the rate its patchCost multiplied by), `cost` what the module charged. */
  function patchRow(label, sf, rate, cost) {
    return [{ raw: label }, B.fmtSf(sf), "SF", rvc("patch.rate", exactRate(rate) + " / SF"), rv("patch.tot", moneyAuto(cost))];
  }

  /** What the tooling card is made of, line by line, when the section's tooling module can say: [label, quantity, unit, rate,
   *  total] rows whose totals add up to the chain's own tooling figure. null when they do not (a section the page cannot break
   *  down, or a saved bid whose chain priced it another way): the card then shows the one total, as it always did. */
  function toolingParts(onShow, b) {
    var role = onShow ? onShow.role : "polish";
    var sf = B.takeoffSf(M.takeoff);
    var parts = null;
    if (role === "polish") {
      var kind = B.polishSystemOf(M.takeoff);
      var T = B.POLISH_TOOLING;
      var t = B.polishTooling(sf, B.takeoffLf(M.takeoff), { dye: !!(ROOT.conditions || {}).dye, system: kind.system, traditional: kind.traditional });
      parts = [["Tooling and consumables (minimum $" + T.min + ")", B.fmtSf(sf), "SF", exactRate(t.rate) + " / SF", t.consumables]];
      if (t.slurry > 0) parts.push(["Slurry hardener", B.fmtSf(B.roundUp(sf / T.slurryEverySf)), "bags", B.money(T.slurryBag) + " / bag", t.slurry]);
      if (t.plastic > 0) parts.push(["Plastic", B.fmtSf(B.takeoffLf(M.takeoff)), "LF", exactRate(T.plasticPerLf) + " / LF", t.plastic]);
    } else if (role === "epoxy" && E && E.TOOLING) {
      var X = E.TOOLING;
      var tests = B.roundUp(sf > X.moistureAfterSf ? sf / X.moistureEverySf : X.moistureMinTests);
      var perSf = sf * X.consumablesPerSf;
      parts = [["Moisture test", B.fmtSf(tests), "tests", B.money(X.moistureCost) + " / test", B.roundUp(tests * X.moistureCost)],
               ["Consumables (minimum $" + X.consumablesMin + ")", B.fmtSf(sf), "SF", exactRate(X.consumablesPerSf) + " / SF",
                B.roundUp(perSf > X.consumablesMin ? perSf : X.consumablesMin)]];
    } else if (role === "seal" && SL && SL.TOOLING) {
      parts = [["Tooling and consumables (minimum $" + SL.TOOLING.min + ")", B.fmtSf(sf), "SF", exactRate(SL.TOOLING.perSf) + " / SF",
                SL.toolingCost(sf)]];
    }
    if (!parts) return null;
    var sum = parts.reduce(function (s, p) { return s + p[4]; }, 0);
    return Math.abs(sum - B.num(b.tooling)) < 0.005 ? parts : null;
  }

  var OPTION_NOT_IN_SUM = "Option, not in the lump sum";

  function reviewPanel() {
    // No blurb on Review: the figures speak for themselves, and shell() leaves out the grey
    // line entirely when the blurb is empty, so no gap is left behind.
    return shell("Review the bid", "", reviewBody());
  }

  /** The Review step's whole body as HTML. Pure apart from FIGS, which it refills (see rv), so repaintNumbers can call it
   *  to learn the live figures of the working without touching the page. */
  function reviewBody() {
    FIGS = {};
    // The bid of the section on show: the root's chain, or the engine's answer for another section.
    var b = activeBid();
    var blk = B.blockers(M);
    var html = "";
    if (blk.length) {
      html += '<div class="blockers"><b>Not finished yet.</b><ul>' +
        blk.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + '</ul></div>';
    }
    // A section that is an OPTION says so first: its figure is quoted on its own and is never in the lump sum.
    var onShow = activeTab === B.ROOT_TAB ? null : openEntry();
    if (onShow && onShow.kind === "option") {
      html += '<p class="cap" data-option-note><b>' + esc(OPTION_NOT_IN_SUM) + '.</b> ' + esc(onShow.label || onShow.tab) +
        ' is priced on its own and printed under Options &amp; Unit Prices. The lump sum is the base bid alone.</p>';
    }
    // Takeoff and material
    var tkRows = [];
    M.takeoff.forEach(function (r, i) {
      // A MATERIAL ROW HAS A NAME TOO, and it is in a different field. Reading assembly_name only
      // printed a fully priced material row as "(no assembly picked)" beside its own cost, which
      // reads as a fault in a row that has nothing wrong with it.
      if (!r.assembly_id && !r.item_id && !B.num(r.measurement)) return;
      if (!B.rowOn(r)) return;               // switched off: out of the bid, so out of the list
      // HOW THE ROW'S COST WAS REACHED: its measurement, its unit, and the rate per unit the Material step shows beside it
      // ("$1.57 / SF"), which is the row's cost over its measurement (rowPrice's own per_unit).
      var rc = rowCost(r), p = rc.price, meas = B.num(r.measurement), unit = r.unit || "SF";
      var per = (p && p.priced_lines && meas > 0) ? (p.per_unit != null ? p.per_unit : p.total / meas) : null;
      tkRows.push([r.assembly_name || r.item_name || "(nothing picked yet)", meas ? B.fmtSf(meas) : "", meas ? unit : "",
                   rvc("tk." + i + ".rate", reviewPerUnit(per, unit)), rv("tk." + i + ".tot", rc.text)]);
    });
    if (!tkRows.length) tkRows.push(["Nothing measured yet", "", "", "", ""]);
    // THE PATCH LINE, said where its money is: a price a square foot of the whole area, from the same module that charged it
    // (the Polish and Seal rate is the New one or the Renovation one; the Epoxy rate is its own).
    var areaSf = B.takeoffSf(M.takeoff), roleNow = onShow ? onShow.role : "polish";
    var patchNow = polishPatchCost(M.takeoff);
    if (patchNow > 0) {
      var polishReno = jobIsReno();
      tkRows.push(patchRow('Patch <span class="note">' + (polishReno ? "renovation" : "new concrete") + ' rate</span>', areaSf,
        SL.unitPrice(ITEMS, polishReno ? "patchReno" : "patchNew").cost, patchNow));
    } else if (roleNow === "epoxy" && E && E.patchCost) {
      var epItems = itemsFor(M.takeoff), epPatch = E.patchCost(epItems, areaSf);
      if (epPatch > 0) tkRows.push(patchRow('Patch <span class="note">epoxy rate</span>', areaSf, E.unitPrice(epItems, "patch").cost, epPatch));
    } else if (roleNow === "seal" && SL) {
      var slItems = itemsFor(M.takeoff), slReno = jobIsReno(), slPatch = SL.patchCost(slItems, areaSf, slReno);
      if (slPatch > 0) {
        tkRows.push(patchRow('Patch <span class="note">' + (slReno ? "renovation" : "new concrete") + ' rate</span>', areaSf,
          SL.unitPrice(slItems, slReno ? "patchReno" : "patchNew").cost, slPatch));
      }
    }
    // DYE AND JOINT FILLER, which the Polish material buys beside its takeoff rows (the job's conditions, charged on every Polish
    // section): their own quantity, unit and rate, as the cards on the Takeoff step say them, so the rows add up to the subtotal.
    if (roleNow === "polish") {
      CONDITION_CARDS.forEach(function (c) {
        if (!c.cost || !(ROOT.conditions || {})[c.key]) return;
        var cost = B.num(condLine(c.key, areaSf).cost);
        if (!(cost > 0)) return;
        var f = condFigures(c), cq = B.num(c.qty(areaSf));
        // Dye is bought in two coats (the row prices one and the line charges both), so its rate is the cost of the line over
        // its area; the name says so.
        tkRows.push([c.material() + (c.key === "dye" ? " (" + B.DYE_COATS + " coats)" : ""), f.qty, f.unit,
                     rvc("cond." + c.key + ".rate", cq > 0 ? exactRate(cost / cq) + " / " + c.unit(1) : ""),
                     rv("cond." + c.key + ".tot", moneyAuto(cost))]);
      });
    }
    // A Gyp section's other lines: the primer, ISO strip, tape, sand and sound mat the sheet buys from the areas.
    var gypRev = gypOpen();
    if (gypRev) {
      gypLines(gypRev).forEach(function (l, i) {
        tkRows.push([l.label, gypQty(l.n), l.unit, rvc("gyp." + i + ".rate", l.n > 0 ? exactRate(l.cost / l.n) + " / " + l.one : ""),
                     rv("gyp." + i + ".tot", moneyAuto(l.cost))]);
      });
    }
    // AN EPOXY SECTION'S OWN MATERIAL BOXES (Hanz, 2026-10-16): Kyle's supplier discounts (B41 on the Sherwin-Williams
    // liquids, C41 on the Poly-Crete ones). They price the materials above, so they sit with them. Only an Epoxy section has
    // those cells; a Polish, Seal or Gyp tab has no discount groups. NO BULK DISCOUNT SWITCH (Hanz, 2026-10-20: "Remove all
    // bulk discount toggle in the V2 estimates"): a v2 material is bought at its own price; no saved bid had it on.
    // The boxes are rates, so they sit in the Rate column.
    var rb = ruleBid();
    if (onShow && onShow.layout === "epoxy") {
      tkRows.push([{ raw: 'Supplier discount <span class="note">Sherwin-Williams liquids</span>' }, "", "",
                   { raw: adjBox("supplier_pct", "0") }, ""]);
      tkRows.push([{ raw: 'Poly-Crete discount <span class="note">SL, MD and WR; blank is the supplier discount</span>' }, "", "",
                   { raw: adjBox("polycrete_pct", adjTyped("supplier_pct") || "0") }, ""]);
    }
    tkRows.push(["Material Subtotal", "", "", "", mkAmt(b, "material")]);
    // A rate the engine reports for the section on show is the one printed (an Epoxy section ships at its tier);
    // the root's chain reports none of these, so it prints the Polish figures it always did.
    var rateOf = function (key, fallback) { return b[key] != null ? b[key] : fallback; };
    if (b.ship_pct === null) {
      // A Gyp chain has no one shipping rate: 8% escalation on gypsum, extras and mat, and shipping of 20% on the
      // gypsum and 10% on the rest, the sound mat free from a truckload on. So no one base or rate is shown for them.
      tkRows.push(["Material escalation", "", "", "", mkAmt(b, "material_escalation")]);
      tkRows.push(["Shipping", "", "", "", mkAmt(b, "shipping")]);
    } else {
      // Typed over the sheet's own rate (Kyle's B42 / B32); blank is the rule, which the box shows greyed. The base is the
      // material subtotal the % is taken of.
      tkRows.push(["Shipping", rvc("ship.q", moneyAuto(b.material)), "of material",
                   { raw: rateSpan(b, "ship_pct") + adjBox("ship_pct", pctNum(rb.ship_pct != null ? rb.ship_pct : B.RATES.SHIPPING)) },
                   mkAmt(b, "shipping")]);
    }
    tkRows.push(["Material Total", "", "", "", mkAmt(b, "material_total"), "tot"]);
    html += card("Takeoff and Material", 0, "takeoff", revTable(tkRows));

    // Labor
    var labRows = [];
    // A row that prices at nothing is left off -- EXCEPT TRAVEL, which is always listed.
    //
    // The difference is what a zero MEANS on each. An empty Polishing or Joint filler row is
    // unfinished work, and the blockers panel at the top of this step already names it; repeating
    // it here would say the same thing twice and put a $0 beside a line that is going to cost
    // thousands. An empty Travel row is a legitimate answer -- a local job has no travel -- so its
    // zero is a DECISION, and a decision is exactly what a review step is for. Leaving it off meant
    // the one labor line an estimator is most likely to have forgotten was also the only one they
    // could not see.
    var pwRev = B.prevailingApplied(M);       // the Labor step's prevailing rate, the one the totals use
    M.labor.forEach(function (r, i) {
      if (!B.rowOn(r)) return;               // switched off: out of the bid, so out of the list
      var cost = B.laborCost(r, pwRev);
      if (!cost && (r || {}).id !== "travel") return;
      // HOURS: guys x days x the hours of a day (guys x hours on an hours row, travel), then x the line's hourly rate.
      var perDay = r.unit === "hours" ? 1 : B.dayHours(r);
      var hrs = B.num(r.guys) * B.num(r.days) * perDay;
      var work = B.fmtSf(B.num(r.guys)) + " × " + B.fmtSf(B.num(r.days)) + (r.unit === "hours" ? "" : " × " + perDay);
      // Hours the distance wrote say the trip they were worked from, and who it is charged to (Hanz, 2026-10-20), under the
      // line's name: "6.5 hrs: one 380 mile round trip at 60 mph from the Olathe office, for each of the 4 guys on the labor
      // lines above". The Quantity column is too narrow to hold it (it would run into the Unit column), so it sits in the
      // wide one, and the working beside it stays "4 × 6.5".
      var drive = B.driveHoursSentence(M, r, activeIsOption());
      var lineName = r.label || "Labor line";
      // THE TRIP SENTENCE IS A KEYED FIGURE LIKE THE OTHERS (2026-10-20 audit): a late distance answer lands through repaintNumbers,
      // which never rebuilds the Review, so on Travel Labor's row the sentence sits in a keyed cell even while it is empty, and the
      // repaint writes it in place. An empty block-level note has no height, so a row with no trip looks as it always did.
      var nameCell = B.isTravelRow(r)
        ? { raw: esc(lineName) + '<span class="note work">' + rv("lab." + i + ".drive", drive) + '</span>' } : lineName;
      labRows.push([nameCell,
                    { raw: rv("lab." + i + ".q", B.fmtSf(hrs)) + '<span class="note work">' + rv("lab." + i + ".w", work) + '</span>' },
                    "hrs", rvc("lab." + i + ".rate", rateMoney(B.laborRateOf(r, pwRev)) + " / hr"),
                    rv("lab." + i + ".tot", moneyAuto(cost))]);
    });
    // The fourth hand on the joint-filler line (Remove existing joint filler) is labor too, and is in the subtotal.
    var handCost = B.removeExistingHand(M.labor, M.conditions, pwRev);
    if (handCost > 0) {
      var jf = M.labor.filter(function (r) { return (r || {}).id === "jointfill"; })[0] || {};
      var jfPer = jf.unit === "hours" ? 1 : B.dayHours(jf);
      labRows.push(["Remove existing joint filler (one more hand)",
                    { raw: rv("hand.q", B.fmtSf(B.num(jf.days) * jfPer)) + '<span class="note work">' + rv("hand.w", "1 × " +
                      B.fmtSf(B.num(jf.days)) + (jf.unit === "hours" ? "" : " × " + jfPer)) + '</span>' },
                    "hrs", rvc("hand.rate", rateMoney(B.laborRateOf(jf, pwRev)) + " / hr"), rv("hand.tot", moneyAuto(handCost))]);
    }
    if (!labRows.length) labRows.push(["No labor entered yet", "", "", "", ""]);
    labRows.push(["Labor Subtotal", "", "", "", mkAmt(b, "labor")]);
    // The escalation and the burden are % of the labor above: the base, then the %, then what it comes to.
    labRows.push([gypRev ? "Labor escalation (always on for Gyp)" : { raw: condSwitch("prevailing_wage", "Labor escalation") },
      rvc("esc.q", b.escalation ? moneyAuto(b.labor) : ""), "of labor",
      rvc("esc.rate", b.escalation ? B.pct(rateOf("esc_pct", B.RATES.ESCALATION)) : ""), mkAmt(b, "escalation")]);
    labRows.push(["Labor burden", rvc("burden.q", moneyAuto(B.num(b.labor) + B.num(b.escalation))),
                  b.escalation ? "of labor + escalation" : "of labor",
                  rvc("burden.rate", B.pct(rateOf("burden_pct", B.RATES.BURDEN))), mkAmt(b, "burden")]);
    labRows.push(["Labor Total", "", "", "", mkAmt(b, "labor_total"), "tot"]);
    html += card("Labor", 1, "labor", revTable(labRows));

    // Hotel and Per Diem (Hanz, 2026-10-06): ALWAYS drawn, straight after Labor, because it is
    // inside the markups but is not labor and he wants to see the container whether or not it is
    // used. A line is listed only while switched on (an off line is out of the bid, so out of the
    // list); with both off the card says so in one row and shows $0. The title is this card's
    // alone -- every other screen still calls the line "Lodging". The lodging line shows "Hotel"
    // here unless the estimator typed a label of their own over the default.
    var trvRows = [];
    // A section that does not carry the job's travel (the second section of a combo bid) prices none: the job's
    // Hotel and Per Diem are charged once, on the carrier, and this card says where instead of listing lines
    // that belong to another section's crew.
    var carries = carriesTravel();
    var ownTravel = !carries && activeIsOption();   // an option lists its own lines, for its own crew's man-days
    B.TRAVEL_LINE_KEYS.forEach(function (k) {
      var tl = (M.travel || {})[k];
      if ((!carries && !ownTravel) || !tl || !tl.enabled) return;
      var name = (k === "lodging" && (!tl.label || tl.label === "Lodging")) ? "Hotel" : tl.label;
      // Nights (lodging) or days (per diem) at the line's own rate: the quantity the chain charged, times the rate.
      var qty = ownTravel ? B.travelManDays(M.labor) : B.travelQty(tl, M.labor, B.travelOpts(ROOT, activeTab));
      var cost = ownTravel ? B.optionTravelCosts(M.travel, M.labor)[k]
                           : B.travelLineCost(tl, M.labor, B.travelOpts(ROOT, activeTab));
      var per = k === "lodging" ? "night" : "day";
      trvRows.push([name, rvc("trv." + k + ".q", B.fmtSf(B.num(qty))), per + "s", rvc("trv." + k + ".rate", rateMoney(tl.rate) + " / " + per),
                    rv("trv." + k + ".tot", moneyAuto(cost))]);
    });
    if (!carries) {
      trvRows.push([travelNote(), "", "", "", ""]);
    } else if (!trvRows.length) {
      trvRows.push(["Not included. Switch Lodging or Per Diem on in the Labor step.", "", "", "", ""]);
    }
    trvRows.push(["Hotel and Per Diem Total", "", "", "", mkAmt(b, "travel"), "tot"]);
    html += card("Hotel and Per Diem", 1, "travel", revTable(trvRows));

    // TOOLING AND CONSUMABLES, for a section whose chain has the line (Epoxy: the moisture test, and $0.33 a
    // square foot with a $150 floor; a Polish bid made after Phase 17: tooling with its $150 minimum, slurry hardener
    // and plastic). A saved Polish bid's chain has none, so it draws nothing here.
    // The card header carries no figure now; the total is the card's own last row. It takes the takeoff colour.
    // Where the section's tooling module can break the line down, each part shows its quantity, unit and rate above the total.
    if (b.tooling > 0) {
      var toolingWords = activeTab === B.ROOT_TAB ? "Tooling, slurry hardener and plastic" : "Moisture test, tooling and consumables";
      var toolRows = (toolingParts(onShow, b) || []).map(function (p, i) {
        return [p[0], p[1], p[2], p[3], rv("tool." + i + ".tot", moneyAuto(p[4]))];
      });
      toolRows.push([toolingWords, "", "", "", mkAmt(b, "tooling"), "tot"]);
      html += card("Tooling and consumables", 0, "takeoff", revTable(toolRows));
    }

    html += '<div data-rev="markup" class="rev">' + markupTable(b) + '</div>';
    return html;
  }

  /** Any condition Intake has a toggle for and Review already talks about gets a real, clickable
   *  toggle here too -- not just a read-only echo of Intake's own answer. Same track-and-knob
   *  language as Intake's `.sw` (styles.css), sized to sit inside a table cell instead of its own
   *  full padded row: `polish-estimate.html` does not link styles.css (standalone, like every
   *  other page carrying its own tokens), so this is `.mw-sw`, not `.sw`.
   *
   *  Returns the switch + label only -- callers compose it with whatever extra context that
   *  SPECIFIC row still needs (remodelSource()'s county note, ...),
   *  so nothing those already said gets lost by routing through here. */
  function condSwitch(key, label, inert) {
    var on = !!(M.conditions || {})[key];
    // `inert` DIMS, it does not disable and it does not hide -- `.sw.inert`'s convention and its
    // reason. A switch whose answer changes no price still has an answer, and that answer still
    // reaches the downloaded workbook, so taking it away would lose a cell rather than tidy a
    // screen. It stays clickable; it just stops claiming to matter to the figure above it.
    return B.sliderHtml(on, 'data-cond="' + esc(key) + '"', label, null, inert ? " inert" : "");
  }

  /** Where the remodel rate came from, said out loud beside the row.
   *
   *  Worth the words: Kyle's sheet charges a flat 10% here, so an estimator who knows the workbook
   *  will read this line expecting that number. Naming the county, or naming the state fallback,
   *  is what stops the difference looking like a bug.
   *
   *  Off has nothing left to say now that the switch beside it shows the state directly -- the
   *  old "off · edit in Intake" text was only ever standing in for a control that did not exist
   *  here yet. */
  function remodelSource() {
    if (!(M.conditions || {}).remodel_tax) return "";
    var rate = remodelRate();
    // `county` already reads "Johnson County, KS" — the shape the live estimate screen's picker
    // writes and the beta intake matches, so both screens store one thing. Printing it as-is:
    // appending " County" to it produced "Johnson County, KS County".
    if (rate > 0) {
      return ' <span class="note">' + esc(state.county || "county rate") + '</span>';
    }
    if (rate === 0 && state.county) {
      return ' <span class="note">' + esc(state.county) +
        ' — remodel labor is exempt there</span>';
    }
    return ' <span class="note">Kansas state rate · <a href="' +
      esc(TW.withDraft("/polish-intake.html")) + '">pick a county</a> for the real one</span>';
  }

  // ── THE ESTIMATOR'S OVERRIDES (Hanz, 2026-10-16) ───────────────────────────────────────────────────────────
  // Boxes over the sheet's own rules, one set per section (`M.adjust`, which B.sectionView answers from the section on
  // show). bid-model.js checks and converts them (normalizeAdjust, chainAdjust, materialAdjust, adjustProblems).

  /** What was typed in one box, as text, or "" for nothing. */
  function adjTyped(key) {
    var a = B.normalizeAdjust(M.adjust);
    if (!a) return "";
    switch (key) {
      case "discount_pct": return a.discount_pct == null ? "" : String(a.discount_pct);
      case "discount_amt": return a.discount_amt == null ? "" : String(a.discount_amt);
      case "ship_pct": return a.ship_pct == null ? "" : String(a.ship_pct);
      case "gp_pct": return a.gp_pct == null ? "" : String(a.gp_pct);
      case "super_pct": return a.super_pct == null ? "" : String(a.super_pct);
      case "soft_pct": return a.soft_pct == null ? "" : String(a.soft_pct);
      case "supplier_pct": return a.supplier_pct == null ? "" : String(a.supplier_pct);
      case "polycrete_pct": return a.polycrete_pct == null ? "" : String(a.polycrete_pct);
      default: return "";
    }
  }
  function adjOn(key) {
    var a = B.normalizeAdjust(M.adjust);
    if (!a) return false;
    if (key === "hard_bid") return a.hard_bid === true;
    return false;
  }

  /** Write one box into the section on show. The keys are named one by one (never `obj[key] = value` with a key off
   *  an attribute), and the whole set goes back through normalizeAdjust, so a cleared box takes its key away and a
   *  section left with nothing typed saves no `adjust` at all. */
  function setAdjust(key, value) {
    var a = Object.assign({}, B.normalizeAdjust(M.adjust) || {});
    switch (key) {
      case "discount_pct": a.discount_pct = value; break;
      case "discount_amt": a.discount_amt = value; break;
      case "ship_pct": a.ship_pct = value; break;
      case "gp_pct": a.gp_pct = value; break;
      case "super_pct": a.super_pct = value; break;
      case "soft_pct": a.soft_pct = value; break;
      case "supplier_pct": a.supplier_pct = value; break;
      case "polycrete_pct": a.polycrete_pct = value; break;
      case "hard_bid": a.hard_bid = value === true; break;
      default: return;
    }
    var next = B.normalizeAdjust(a);
    M.adjust = next || undefined;
  }

  /** The bid of the section on show with its boxes set aside: what the sheet's own rules give, which is what each box
   *  shows greyed until something is typed in it. Nothing is changed: the section's boxes are put back. */
  function ruleBid() {
    var saved = M.adjust;
    // The material boxes stay: the rule a markup box is greyed with is the rule for the material this section buys.
    try { M.adjust = B.materialOnlyAdjust(saved) || undefined; return activeBid(); } finally { M.adjust = saved; }
  }

  /** A fraction as the figure a % box holds: nine percent reads "9", two point seven percent "2.7". "" for none. */
  function pctNum(f) {
    var n = B.num(f);
    return (f === null || f === undefined || !isFinite(n)) ? "" : String(parseFloat((n * 100).toPrecision(6)));
  }

  /** The words beside a box that is typed but cannot be used (B.adjustProblems), hidden when there are none. */
  function adjWarnText(key) {
    var probs = B.adjustProblems(M.adjust);
    for (var i = 0; i < probs.length; i++) if (probs[i].key === key) return probs[i].text;
    // The chain refuses a discount that gives back the whole bid (bid-engine.js): said under whichever box is in force,
    // the dollars when they are typed (they win), else the percentage.
    if (key === "discount_amt" || key === "discount_pct") {
      var typedAmt = adjTyped("discount_amt") !== "";
      if ((key === "discount_amt") === typedAmt && activeBid().discount_refused) {
        return "more than the labor and markup it comes off, so it is not used";
      }
    }
    return "";
  }
  function adjWarnHtml(key) {
    var t = adjWarnText(key);
    return '<span class="adjwarn" data-adjwarn="' + key + '"' + (t ? '' : ' hidden') + '>' + esc(t) + '</span>';
  }

  /** THE RATE A LINE WAS PRICED WITH, override or rule, as the chain reports it (falling back to the pinned rate where
   *  the Polish chain reports none). Keyed `data-mkrate` so the repaint refreshes it beside its box. */
  function rateUsed(b, key) {
    switch (key) {
      case "ship_pct": return b.ship_pct != null ? b.ship_pct : B.RATES.SHIPPING;
      case "super_pct": return b.super_pct != null ? b.super_pct : B.RATES.SUPER_PTO;
      case "soft_pct": return b.soft_pct != null ? b.soft_pct : B.RATES.SOFT_COSTS;
      case "discount_pct": return b.hard_bid_pct ? -b.hard_bid_pct : null;
      default: return null;
    }
  }
  function rateSpan(b, key) {
    var f = rateUsed(b, key);
    // NOT DRAWN (Hanz, 2026-10-17: "why do we have double values here its confusing"). It sits beside a box that already
    // shows the same rate, greyed when it is the sheet's rule and in the box's own ink when typed; the span stays so the
    // repaint and the checks still read the rate the chain priced with.
    return '<span class="mkused" aria-hidden="true" data-mkrate="' + key + '">' + esc(f == null ? "" : B.pct(f)) + '</span>';
  }

  /** The Discount box's greyed figure: what Kyle's hard bid rule gives (the switch on), else 0. */
  function discountRule(rb) {
    return rb && rb.hard_bid_pct ? pctNum(-rb.hard_bid_pct) : "0";
  }

  /** The words beside the Hard bid switch: the rule while it is off, what it gives while it is on. */
  function hardBidNote(rb) {
    if (!adjOn("hard_bid")) return "4% off from $60,000, 2.5% on a local job from $13,000";
    if (rb && rb.hard_bid_pct) return "the rule takes " + pctNum(-rb.hard_bid_pct) + "% off; a figure you type wins";
    return "the rule gives nothing here: under $13,000, or not local and under $60,000";
  }

  /** One % box over a rule. `rule` is the figure the sheet's rule gives, shown greyed as the placeholder. */
  function adjBox(key, rule) {
    var label = { ship_pct: "Shipping", gp_pct: "GP", super_pct: "Superintendent and PTO", soft_pct: "Soft costs",
                  discount_pct: "Discount", supplier_pct: "Supplier discount", polycrete_pct: "Poly-Crete discount" }[key] || key;
    return '<span class="adjbox"><input data-adj="' + key + '" value="' + esc(adjTyped(key)) + '" placeholder="' +
      esc(rule) + '" inputmode="decimal" aria-label="' + esc(label) + ' in percent; blank uses the sheet\'s rule">%' +
      adjWarnHtml(key) + '</span>';
  }

  /** Rows 64-82 of the Polish tab, in the same order, so an estimator who knows Kyle's sheet can
   *  read down it and recognise every line. Percentages are the sheet's own and not editable —
   *  the workbook locks these cells in the generated download for the same reason. Contingency is
   *  the one exception, because the sheet leaves D71 open too.
   *
   *  THE SAME FIVE COLUMNS AS THE CARDS ABOVE (Item | Quantity | Unit | Rate | Total): a line that is a % of something shows
   *  that something (markupBases, taken from the chain's own arithmetic) in Quantity, what it is of in Unit, and the % in Rate,
   *  where the override boxes still sit. A line with no plain base (GP is a gross-up, Fees and Contingency are typed dollars)
   *  shows its % or its box and its total only. */
  function markupTable(b) {
    var r = "";
    var bases = markupBases(b);
    // The base and what it is of, as two keyed cells that show only while the line has a rate to apply (a line at 0% has no
    // base worth reading). Keyed so the repaint moves them with every keystroke.
    var baseCells = function (key, base, unitWords, pctNow) {
      var on = base !== null && base !== undefined && B.num(pctNow) !== 0;
      return [rv("mk." + key + ".q", on ? moneyAuto(base) : ""), rv("mk." + key + ".u", on ? unitWords : "")];
    };
    var rowOf = function (labelHtml, qty, unit, rate, total, cls) {
      return '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + labelHtml + '</td><td class="q r">' + qty + '</td><td class="u">' +
        unit + '</td><td class="rt r">' + rate + '</td>' + total + '</tr>';
    };
    var amtCell = function (key) { return '<td class="amt" data-mk="' + key + '">' + esc(moneyAuto(b[key])) + '</td>'; };
    var row = function (label, qty, unit, pctHtml, key, cls) { return rowOf(label, qty, unit, pctHtml, amtCell(key), cls); };
    var keyedPct = function (key, beside) {
      // `beside`: a box shows this rate already, so the text is kept for the repaint and not drawn (see rateSpan).
      return '<span' + (beside ? ' class="mkused" aria-hidden="true"' : '') + ' data-mkpct="' + key + '">' +
        esc(B.pct(b[key])) + '</span>';
    };

    r += rowOf("Subtotal", "", "", "", amtCell("sub_total"), "sub");

    r += '<tr class="band"><td colspan="5">Markup <span class="bandnote">grey is the sheet\'s own figure; ' +
      'type over it to change it, clear the box to go back</span></td></tr>';
    // THE RATES ARE BOXES OVER THE RULE (Hanz, 2026-10-16): blank is the sheet's own figure, shown greyed in the box,
    // and a number typed is the rate (Kyle types over B73/B67, B75/B69 and B76/B70 on a share of his bids).
    var rb = ruleBid();
    // GP is a margin, not a % of anything: the sheet divides the cost by (1 - GP) and takes the cost back off, so no base is shown.
    r += row("GP <span class=\"note\">before the lines below</span>", "", "margin on cost",
      keyedPct("gp_pct", true) + adjBox("gp_pct", pctNum(rb.gp_pct)), "gp");
    // THE DISCOUNT LINE IS BACK (Hanz, 2026-10-16), reversing 2026-09-22: Kyle's "Hard Bid Discount" was his
    // price-landing line on 21 of 41 bids in the two months before, mostly on jobs that were not hard bids. It is
    // a plain discount now, a % or a $ (the $ wins), blank is none, and nothing turns it on by itself.
    // The discount's amount is keyed `data-mkdisc`, not `data-mk`: a bid with nothing typed has no such line in its
    // chain, and the review's every-money-cell-is-the-chain check stays exactly as strict as it was.
    // HARD BID (Hanz, 2026-10-17): the job's switch sits on this line, because the line is what it moves. On, the box shows
    // Kyle's rule greyed (4% from $60,000, 2.5% local from $13,000) and the rule prices; a figure typed in either box
    // still wins. Shown only where the section's chain has the rule.
    // A DISCOUNT TYPED IN DOLLARS has no % (the chain reports none), so it has no base either.
    var hb = B.hardBidRuleOn(ROOT, activeTab);
    var disc = baseCells("disc", b.hard_bid_pct === null ? null : bases.disc, "of subtotal + GP", b.hard_bid_pct);
    r += '<tr data-disc-row' + (b.hard_bid ? '' : ' class="off"') + '><td>Discount <span class="note">% or $, yours to set</span>' +
      (hb ? '<div class="hbline">' + B.sliderHtml(adjOn("hard_bid"), 'data-adj-hb="1"', "Hard bid",
              "Kyle's Hard bid answer for this sheet: his rule fills the discount until you type one") +
            ' <span class="note" data-hbnote>' + esc(hardBidNote(rb)) + '</span></div>' : '') + '</td>' +
      '<td class="q r">' + disc[0] + '</td><td class="u">' + disc[1] + '</td>' +
      '<td class="rt r">' + rateSpan(b, "discount_pct") + adjBox("discount_pct", discountRule(rb)) + '</td>' +
      '<td class="amt"><span class="adjbox adjamt">$<input data-adj="discount_amt" value="' + esc(adjTyped("discount_amt")) +
      '" placeholder="0" inputmode="decimal" aria-label="Discount in dollars; it wins over the percentage">' +
      adjWarnHtml("discount_amt") + '</span> <span data-mkdisc>' + esc(moneyAuto(b.hard_bid || 0)) + '</span></td></tr>';
    var sup = baseCells("super", bases.super, "of subtotal + markups", rateUsed(b, "super_pct"));
    r += row("Superintendent &amp; PTO", sup[0], sup[1], rateSpan(b, "super_pct") +
      adjBox("super_pct", pctNum(rb.super_pct != null ? rb.super_pct : B.RATES.SUPER_PTO)), "super_pto");
    var soft = baseCells("soft", bases.soft, "of subtotal + markups", rateUsed(b, "soft_pct"));
    r += row("Soft costs", soft[0], soft[1], rateSpan(b, "soft_pct") +
      adjBox("soft_pct", pctNum(rb.soft_pct != null ? rb.soft_pct : B.RATES.SOFT_COSTS)), "soft_costs");
    r += '<tr><td>Contingency <span class="note">yours to set</span></td>' +
      '<td class="q r"></td><td class="u"></td><td class="rt r"></td><td class="amt"><input data-contingency value="' +
      esc(nv(M.contingency)) + '" inputmode="decimal"></td></tr>';

    r += '<tr class="band"><td colspan="5">Taxes &amp; fees</td></tr>';
    var st = baseCells("sales", bases.sales, "of materials", b.sales_tax_pct);
    r += row(condSwitch("taxable", "Sales tax") + ' <span class="note">on materials</span>', st[0], st[1],
      keyedPct("sales_tax_pct"), "sales_tax", b.sales_tax_pct ? "" : "off");
    var rt = baseCells("remodel", bases.remodel, "of labor + markups", b.remodel_pct);
    r += row(condSwitch("remodel_tax", "Remodel tax") + remodelSource(), rt[0], rt[1],
      keyedPct("remodel_pct"), "remodel_tax", b.remodel_pct ? "" : "off");
    r += row("Total taxes", "", "", "", "taxes", "tot");
    // Typed, like Contingency above -- the sheet leaves B77 and C77 open and this is the line
    // an estimator fills them in on. Marked up by everything beneath it, which is D77's own
    // place in Kyle's column rather than a decision made here; see the note in markupChain.
    r += '<tr' + (b.fees ? '' : ' class="off"') + '><td>Fees + Textura ' +
      '<span class="note">yours to set</span></td><td class="q r"></td><td class="u"></td><td class="rt r"></td>' +
      '<td class="amt"><input data-fees value="' + esc(nv(M.fees)) +
      '" inputmode="decimal">' +
      dfltWarnHtml('data-feesdflt="1"', feesDefaultText()) + '</td></tr>';
    var bd = baseCells("bond", bases.bond, "of the bid so far", b.bond_pct);
    r += row(condSwitch("bond", "Bond") +
      ' <span class="note">the sheet ships this at 0% either way</span>', bd[0], bd[1],
      keyedPct("bond_pct"), "bond", b.bond ? "" : "off");
    r += row("Total fees + bond", "", "", "", "fees_and_bond", "tot");

    // THE LUMP SUM, over the area it is priced on: the area in Quantity and the price a square foot in Rate.
    r += '<tr class="grand"><td>Total lump sum</td><td class="q r">' + rv("mk.total.q", b.sf ? B.fmtSf(b.sf) : "") +
      '</td><td class="u">' + rv("mk.total.u", b.sf ? "SF" : "") + '</td>' +
      '<td class="rt r" data-mk-persf>' + esc(perSfText(b)) + '</td>' +
      '<td class="amt" data-mk="total">' + esc(moneyAuto(b.total)) + '</td></tr>';

    return '<div class="tscroll"><table class="mk"><thead>' + REV_HEAD + '</thead><tbody>' + r + '</tbody></table></div>';
  }

  function perSfText(b) {
    if (!b.sf) return "";
    return B.money2(b.per_sf) + " / SF";
  }

  var PANELS = [takeoffPanel, laborPanel, reviewPanel];

  function renderPanel() {
    $("panels").innerHTML = openSectionEditable() ? PANELS[at]() : otherSectionPanel();
  }

  /** ONE LIST, BOTH COLLECTIONS, sorted by name.
   *
   *  THE DECISION CHANGED ON 2026-09-23. This was two lists, and the note here said so: "Kept
   *  apart from the assemblies rather than merged: a row is one or the other, and a merged list
   *  would let somebody pick a system into the field that prices a single product." What it did
   *  in practice was decide, at the moment the row was created, which half of the library the
   *  estimator was allowed to search -- and the half they did not pick was simply missing, which
   *  is what "the dropdown search only pulls assemblies" was describing. The row picks its own
   *  kind now, so the list does not have to be picked first.
   *
   *  The guard the old note was right about is kept, one step later: a name that is BOTH an item
   *  and an assembly is never resolved by guessing. See pickHint.
   *
   *  `label` is the browser's own second column on a datalist option, which is how each name can
   *  say which collection it came from without this page drawing a listbox of its own -- keyboard
   *  handling, filtering and all. Deduped by EXACT name: two entries differing only by case stay
   *  two options, because collapsing them would hide a library problem this page must not
   *  resolve, and the same string in both collections is the one real collision. */
  function renderDatalist() {
    var dl = $("dl-lines");
    if (!dl) return;
    var seen = {};
    var names = [];
    function add(name, kind) {
      var n = String(name == null ? "" : name);
      if (!n) return;
      if (!seen[n]) { seen[n] = {}; names.push(n); }
      seen[n][kind] = true;
    }
    ASMS.forEach(function (a) { add(a.name, "asm"); });
    ITEMS.forEach(function (it) {
      // DYE, THE JOINT FILLER KIT AND REMOVE-EXISTING NEVER APPEAR HERE. All three are already on
      // the takeoff as their own condition rows (see CONDITION_CARDS), priced by a fixed formula
      // (or, for remove-existing, on the Labor step) rather than by the pack — picking either one into an ordinary row a second time would double the
      // charge and give an estimator no way to tell the two apart on screen.
      if (RESERVED_ITEM_IDS.indexOf(it.id) !== -1) return;
      add(it.name, "item");
    });
    names.sort(function (x, y) { return x.localeCompare(y); });
    dl.innerHTML = names.map(function (n) {
      var k = seen[n];
      var label = (k.asm && k.item) ? "Material or assembly" : (k.item ? "Material" : "Assembly");
      return '<option value="' + esc(n) + '" label="' + label + '"></option>';
    }).join("");
  }

  /** The figure the model holds for one Labor box the PAGE owns: a Guys box while it is on auto (the crew's size or the
   *  man-days, whichever the row follows), and Travel Labor's Hours box (the distance writes it). null for every other box,
   *  which is the estimator's own and is never written from the model. */
  function ownedBoxFigure(el) {
    var r = M.labor[parseInt(el.getAttribute("data-lab"), 10)];
    if (!r) return null;
    var k = el.getAttribute("data-k");
    if (k === "guys" && r.unit === "hours" && r.guys_auto) return r.guys == null ? "" : String(r.guys);
    if (k === "days" && r.id === "travel") return r.days == null ? "" : String(r.days);
    return null;
  }

  /** Put the model's figures into the Labor boxes the page owns (see ownedBoxFigure), in place, SKIPPING THE BOX THE ESTIMATOR IS
   *  IN: a late distance answer used to write the crew's size into a Guys box somebody was already typing in, and the
   *  next character went on the end of it (a 3 after the 48 read 483). The focusout handler below settles the skipped box
   *  when they leave it. */
  function paintTravelBoxes() {
    document.querySelectorAll('[data-lab][data-k="guys"]').forEach(function (el) {
      var v = ownedBoxFigure(el);
      if (v === null) return;
      el.setAttribute("data-auto", "1");               // cleared back to auto: the page owns it again
      if (document.activeElement === el) return;       // the Guys box under the estimator's cursor is left alone
      if (el.value !== v) el.value = v;
    });
    // A far answer fills Travel Labor's Hours box, and the lookup landing takes the `changed(false)` path that
    // never rebuilds the card, so the box is repainted here. Hours somebody typed are never changed by an answer, so
    // this only ever writes what the model holds.
    document.querySelectorAll('[data-lab][data-k="days"]').forEach(function (el) {
      var v = ownedBoxFigure(el);
      if (v === null || document.activeElement === el) return;
      if (el.value !== v) el.value = v;
    });
  }

  /** Refresh every computed figure in place, without rebuilding the panel.
   *
   *  Keyed by data-attribute, never by column position. The library page addressed its computed
   *  cells by column index and shipped Quantity and Cost written into each other's columns; the
   *  test agreed with the constants and missed it entirely. An attribute cannot be off by one. */
  function repaintNumbers() {
    var b = activeBid();

    document.querySelectorAll("[data-cost-for]").forEach(function (el) {
      var rc = rowCost(M.takeoff[parseInt(el.getAttribute("data-cost-for"), 10)]);
      el.textContent = rc.text;
      el.className = "costbox" + (rc.empty ? " empty" : "");
    });
    document.querySelectorAll("[data-perunit-for]").forEach(function (el) {
      var i = parseInt(el.getAttribute("data-perunit-for"), 10);
      var p = rowPrice(M.takeoff[i]);
      var r = M.takeoff[i] || {};
      el.textContent = (p && p.per_unit != null)
        ? B.money2(p.per_unit) + " / " + (r.unit || "SF") : "";
    });
    document.querySelectorAll("[data-measure-for]").forEach(function (el) {
      el.textContent = measureText(M.takeoff[parseInt(el.getAttribute("data-measure-for"), 10)]);
    });
    paintUnits();
    // The undecided row's mark, which changes the moment a typed name turns out to be two
    // things. It exists only while the row is undecided; the pick that ends that redraws the card
    // and takes the mark with it.
    document.querySelectorAll("[data-mark-for]").forEach(function (el) {
      el.textContent = ambiguous(M.takeoff[parseInt(el.getAttribute("data-mark-for"), 10)])
        ? "pick one" : "new";
    });
    document.querySelectorAll("[data-asmhint-for]").forEach(function (el) {
      var hi = parseInt(el.getAttribute("data-asmhint-for"), 10);
      el.innerHTML = pickHint(M.takeoff[hi], hi);
    });
    // THE PREVAILING RATE IN FORCE (0 when off or empty), read once for every labor figure below.
    var pwNow = B.prevailingApplied(M);
    document.querySelectorAll("[data-ratedflt-for]").forEach(function (el) {
      var row = M.labor[parseInt(el.getAttribute("data-ratedflt-for"), 10)];
      paintDfltWarn(el, rateDefaultText(row, pwNow));
    });
    // A Rate box on a line that follows the prevailing wage is a derived number: it moves when the card's
    // rate does, and goes back to the line's own rate when the card is switched off. A box somebody is typing
    // in is never touched, and a typed rate is left as typed (laborRateBox gives the stored one back).
    document.querySelectorAll('[data-lab][data-k="rate"]').forEach(function (el) {
      if (document.activeElement === el) return;
      var r = M.labor[parseInt(el.getAttribute("data-lab"), 10)];
      if (!r) return;
      var v = nv(B.laborRateBox(r, pwNow));
      if (el.value !== v) el.value = v;
    });
    // The Prevailing wage card's own figures, live: each trade's sum and entry half wage, which trade the crew
    // is paid, the header and the note.
    var pwBlock = B.normalizePrevailing(M.prevailing) || B.normalizePrevailing({});
    var pwSum = B.prevailingTotal(pwBlock);
    var pwOn = !!(M.conditions || {}).prevailing_wage;
    var pwOf = function (el) { return pwBlock.trades[parseInt(el.getAttribute("data-pw-i"), 10)]; };
    document.querySelectorAll("[data-pw-total]").forEach(function (el) {
      var sum = B.prevailingTotal(pwOf(el));
      el.textContent = sum > 0 ? B.money2(sum) : "";
      el.className = "costbox" + (sum > 0 ? "" : " empty");
    });
    document.querySelectorAll("[data-pw-entry]").forEach(function (el) {
      var sum = B.prevailingTotal(pwOf(el));
      el.textContent = sum > 0 ? B.money2(B.entryHalfWage(sum)) : "";
      el.className = "costbox" + (sum > 0 ? "" : " empty");
    });
    document.querySelectorAll("[data-pw-trade]").forEach(function (el) {
      var t = pwBlock.trades[parseInt(el.getAttribute("data-pw-trade"), 10)];
      el.className = "pwtrade" + (t && t.key === pwBlock.trade ? " paid" : "");
    });
    document.querySelectorAll("[data-pw-pick]").forEach(function (el) {
      var t = pwBlock.trades[parseInt(el.getAttribute("data-pw-pick"), 10)];
      el.checked = !!t && t.key === pwBlock.trade;
    });
    document.querySelectorAll("[data-pw-sub]").forEach(function (el) { el.textContent = pwSubText(pwBlock, pwSum); });
    document.querySelectorAll("[data-pw-note]").forEach(function (el) { el.textContent = pwNote(pwSum); });
    document.querySelectorAll("[data-pw-card]").forEach(function (el) {
      el.className = "tk pwcard" + (pwOn ? "" : " inert off");
    });
    // OPEN AND CLOSED, IN PLACE: the card's own switch is repainted here (its track and aria-checked) and its body
    // shown or hidden, so pressing it never rebuilds the panel and the focus stays on the switch. The boxes inside
    // keep what was typed while the body is hidden.
    document.querySelectorAll("[data-pw-sw]").forEach(function (el) {
      el.className = "mw-sw" + (pwOn ? " on" : "");
      el.setAttribute("aria-checked", pwOn ? "true" : "false");
    });
    document.querySelectorAll("[data-pw-body]").forEach(function (el) { el.hidden = !pwOn; });
    document.querySelectorAll("[data-pw-state]").forEach(function (el) { el.textContent = pwOn ? "on" : "off"; });
    document.querySelectorAll("[data-pw-esc]").forEach(function (el) {
      el.textContent = pwOn ? ", so a 5% escalation is added on the review step" : "";
    });
    document.querySelectorAll("[data-calcwarn]").forEach(function (el) {
      var parts = el.getAttribute("data-calcwarn").split(":");
      paintDfltWarn(el, calcDefaultText(M.labor[parseInt(parts[0], 10)], parts[1]));
    });
    // A followed Days box (G2) is a derived number too: show what changed() moved it to, unless the
    // estimator is typing in it.
    document.querySelectorAll('[data-lab][data-k="days"]').forEach(function (el) {
      var r = M.labor[parseInt(el.getAttribute("data-lab"), 10)];
      if (!r || !r.calc_default || !(B.num(r.calc_default.sf_per_day) > 0)) return;
      if (document.activeElement === el) return;
      var v = r.days == null ? "" : String(r.days);
      if (el.value !== v) el.value = v;
    });
    document.querySelectorAll("[data-lcost-for]").forEach(function (el) {
      el.textContent = moneyAuto(B.laborCost(M.labor[parseInt(
        el.getAttribute("data-lcost-for"), 10)], pwNow));
    });
    // The Cost box in the card body shows the same figure as the header above it, so it repaints in
    // the same pass. Until it had its own hook only the header moved while the box kept the value
    // it was rendered with ($594 up top, $0 below). Class and text only: no rebuild, no lost focus.
    document.querySelectorAll("[data-lcostbox-for]").forEach(function (el) {
      var c = B.laborCost(M.labor[parseInt(el.getAttribute("data-lcostbox-for"), 10)], pwNow);
      el.textContent = moneyAuto(c);
      el.className = "costbox" + (c > 0 ? "" : " empty");
    });
    // A DERIVED BOX IS A NUMBER ON SCREEN, so it repaints here with the costs. Everything else in
    // this function is text the estimator cannot type into, which is why nothing repainted an
    // INPUT before — and it is exactly what made this go wrong: typing days into a task takes the
    // `changed(false)` path, `syncAutoGuys` moved Travel's man-days to 16.5 in the model, the cost
    // cell repainted off 16.5, and the Guys box went on showing the 1.5 it was rendered with. The
    // screen then disagreed with itself — a box reading 1.5 beside a cost worked out from 16.5 —
    // and a browser pass read that as the guys figure being dropped from the formula. It never
    // was; only the box was stale.
    //
    // `data-auto` marks the ones the page owns. A box the estimator has taken over is not in this
    // list (typing flips it to manual and rebuilds the card), so this cannot overwrite typing.
    //
    // A BOX THE ESTIMATOR IS IN IS NEVER REPAINTED (2026-10-20 audit). A late distance answer put the crew's size into a Guys box
    // somebody was already standing in, and the next character they typed went on the end of it (a 3 after the 48 was 483).
    // paintTravelBoxes skips the focused box; the focusout handler below puts the model's figure in when they leave it.
    paintTravelBoxes();
    var ownCrew = activeIsOption();       // a Travel row on an option follows its own section's lines (B.ownCrewSize)
    document.querySelectorAll("[data-hint-lab]").forEach(function (el) {
      var r = M.labor[parseInt(el.getAttribute("data-hint-lab"), 10)];
      if (travelLike(r)) el.textContent = B.travelGuysHint(M, r, M.labor, ownCrew);
    });
    // The note under the Travel Labor card that says where its hours came from (B.driveHoursNote), shown while there is one.
    document.querySelectorAll("[data-trv-src]").forEach(function (el) {
      var r = M.labor[parseInt(el.getAttribute("data-trv-src"), 10)];
      var note = r ? B.driveHoursNote(M, r, M.labor, ownCrew) : "";
      el.textContent = note;
      el.hidden = !note;
    });
    // The words on a leftover Travel Labor row (a base that does not carry the job's travel) say whether it holds typed figures,
    // and typing in it changes that.
    document.querySelectorAll("[data-trv-stray]").forEach(function (el) {
      var r = M.labor[parseInt(el.getAttribute("data-trv-stray"), 10)];
      if (r) el.textContent = B.strayTravelNote(carrierName(), r);
    });
    // The Travel card's own dim state, live: typing in Guys or Hours takes this path
    // (`changed(false)`), never a rebuild, so nothing else repaints the card's class. Keyed
    // attribute + whole-className assignment -- laborCard is the only other writer of this
    // string, and laborInert is the only source either one reads.
    document.querySelectorAll("[data-lab-card]").forEach(function (el) {
      var r = M.labor[parseInt(el.getAttribute("data-lab-card"), 10)];
      if (!r) return;
      var rOn = B.rowOn(r);
      el.className = "tk lab" + ((laborInert(r) || !rOn) ? " inert" : "") + (rOn ? "" : " off");
    });
    // Lodging and Per Diem, live: cost, the auto quantity box, and the card's gray state. Keyed by
    // attribute like everything above, and the class string is written by travelCard and here only.
    document.querySelectorAll("[data-feesdflt]").forEach(function (el) {
      paintDfltWarn(el, feesDefaultText());
    });
    if (M.travel) {
      document.querySelectorAll("[data-trvdflt-for]").forEach(function (el) {
        paintDfltWarn(el, travelRateDefaultText(M.travel[el.getAttribute("data-trvdflt-for")]));
      });
      document.querySelectorAll("[data-trvcost-for]").forEach(function (el) {
        el.textContent = moneyAuto(B.travelLineCost(M.travel[el.getAttribute("data-trvcost-for")], M.labor, B.travelOpts(ROOT, activeTab)));
      });
      document.querySelectorAll("[data-trvcostbox-for]").forEach(function (el) {
        var c = B.travelLineCost(M.travel[el.getAttribute("data-trvcostbox-for")], M.labor, B.travelOpts(ROOT, activeTab));
        el.textContent = moneyAuto(c);
        el.className = "costbox" + (c > 0 ? "" : " empty");
      });
      document.querySelectorAll('[data-trv][data-k="qty"]').forEach(function (el) {
        var l = M.travel[el.getAttribute("data-trv")];
        if (!l || l.qty_auto === false) return;
        el.setAttribute("data-auto", "1");
        var v = l.qty == null ? "" : String(l.qty);
        if (el.value !== v) el.value = v;
      });
      document.querySelectorAll("[data-hint-trv]").forEach(function (el) {
        var l = M.travel[el.getAttribute("data-hint-trv")];
        if (l) el.textContent = B.lodgingHint(ROOT, activeTab, l.qty_auto !== false, M.labor);
      });
      document.querySelectorAll("[data-trv-card]").forEach(function (el) {
        var l = M.travel[el.getAttribute("data-trv-card")];
        if (!l) return;
        el.className = "tk trv" + ((travelInert(l) || !l.enabled) ? " inert" : "") +
          (l.enabled ? "" : " off");
      });
    }
    // The two condition cards that price. Every figure on them is derived from the takeoff area,
    // which is exactly what a keystroke in a takeoff row changes -- and a keystroke takes
    // `changed(false)`, which repaints in place and never rebuilds the panel. Before 2026-09-19
    // nothing in this function knew they existed, so typing 9,000 into row 1 moved the Material
    // total while the Joint Filler line went on quoting the kits and the dollars of an area that
    // had left the screen. A stale figure on a priced line is worse than no figure.
    //
    // condFigures() is the SAME function condMaterialCard uses for the first paint, so the two
    // cannot work the same number out two ways.
    CONDITION_CARDS.forEach(function (c) {
      if (!c.cost) return;
      var f = condFigures(c);
      var put = function (part, txt, cls) {
        var el = document.querySelector('[data-condfig="' + c.key + "." + part + '"]');
        if (!el) return;
        el.textContent = txt;
        // Whole-className assignment, and condMaterialCard is the only other writer of this
        // string -- the same discipline the labor card's dim state is repainted with.
        if (cls != null) el.className = cls;
      };
      put("sub", f.sub);
      put("qty", f.qty, "costbox" + (f.qtyEmpty ? " empty" : ""));
      put("unit", f.unit);
      put("qtyhint", f.qtyHint);
      put("cost", f.cost, "costbox" + (f.costEmpty ? " empty" : ""));
      put("rate", f.rate);
      put("covhint", f.covHint);
      var cw = document.querySelector('[data-condfig="' + c.key + '.covwarn"]');
      if (cw) paintDfltWarn(cw, f.covWarn);
    });
    document.querySelectorAll("[data-covwarn-for]").forEach(function (el) {
      paintDfltWarn(el, covRowWarn(M.takeoff[parseInt(el.getAttribute("data-covwarn-for"), 10)]));
    });
    // The Coverage hints under every takeoff box: typing takes `changed(false)`, which repaints in
    // place, so "Library default: N" has to appear here rather than wait for a rebuild.
    document.querySelectorAll("[data-covhint-for]").forEach(function (el) {
      var hi = parseInt(el.getAttribute("data-covhint-for"), 10);
      el.textContent = covHint(M.takeoff[hi]);
    });

    var one = function (sel, txt) {
      var el = document.querySelector(sel);
      if (el) el.textContent = txt;
    };
    one("[data-mat-total]", moneyAuto(materialTotal()));
    var gypNow = gypOpen();
    if (gypNow) {
      var capEl = document.querySelector("[data-gyp-cap]");
      if (capEl) capEl.innerHTML = gypCaptionText(gypNow);
      var truckEl = document.querySelector("[data-gyp-truck]");
      if (truckEl) truckEl.textContent = gypTruckText(gypNow);
    }
    one("[data-area-total]", B.fmtSf(B.takeoffSf(M.takeoff)) + " SF");
    one("[data-labor-total]", moneyAuto(B.laborTotal(M.labor, M.conditions, pwNow)));
    one("[data-travel-total]", moneyAuto(B.travelCosts(M.travel, M.labor, B.travelOpts(ROOT, activeTab)).total));
    one("[data-trv-how]", B.travelHow(M).text);
    one("[data-mk-persf]", perSfText(b));

    document.querySelectorAll("[data-mk]").forEach(function (el) {
      el.textContent = moneyAuto(b[el.getAttribute("data-mk")]);
    });
    // The GP band and the two tax rates move with the sub-total and the toggles, so the percentage
    // column is as computed as the money column is.
    // The override boxes: each one's greyed rule (the rule moves with the job: GP steps down as the sub-total grows),
    // and the warning beside a box that is typed but cannot be used. A box being typed in keeps its own text.
    var adjEls = document.querySelectorAll("[data-adj]");
    if (adjEls.length) {
      var rb = ruleBid();
      var ruleOf = {
        ship_pct: pctNum(rb.ship_pct != null ? rb.ship_pct : B.RATES.SHIPPING), gp_pct: pctNum(rb.gp_pct),
        super_pct: pctNum(rb.super_pct != null ? rb.super_pct : B.RATES.SUPER_PTO),
        soft_pct: pctNum(rb.soft_pct != null ? rb.soft_pct : B.RATES.SOFT_COSTS),
        polycrete_pct: adjTyped("supplier_pct") || "0",
        discount_pct: discountRule(rb)
      };
      document.querySelectorAll("[data-hbnote]").forEach(function (el) { el.textContent = hardBidNote(rb); });
      adjEls.forEach(function (el) {
        var k = el.getAttribute("data-adj");
        if (Object.prototype.hasOwnProperty.call(ruleOf, k) && el.placeholder !== ruleOf[k]) el.placeholder = ruleOf[k];
      });
      document.querySelectorAll("[data-adjwarn]").forEach(function (el) {
        var t = adjWarnText(el.getAttribute("data-adjwarn"));
        el.textContent = t;
        el.hidden = !t;
      });
    }
    document.querySelectorAll("[data-mkrate]").forEach(function (el) {
      var f = rateUsed(b, el.getAttribute("data-mkrate"));
      el.textContent = f == null ? "" : B.pct(f);
    });
    // THE WORKING IN FRONT OF EVERY REVIEW TOTAL (Quantity, Unit and Rate): the Review is written again, only to learn each
    // keyed figure's text (reviewBody refills FIGS), and the text is put on the cell that has the key. Nothing is rebuilt, so
    // the box being typed in keeps its caret. The Takeoff and Labor steps carry no such cell and skip it.
    if (document.querySelector("[data-rv]")) {
      reviewBody();
      var figs = FIGS || {};
      document.querySelectorAll("[data-rv]").forEach(function (el) {
        var k = el.getAttribute("data-rv");
        if (Object.prototype.hasOwnProperty.call(figs, k)) el.textContent = figs[k];
      });
    }
    document.querySelectorAll("[data-mkdisc]").forEach(function (el) { el.textContent = moneyAuto(b.hard_bid || 0); });
    document.querySelectorAll("[data-disc-row]").forEach(function (el) { el.className = b.hard_bid ? "" : "off"; });
    document.querySelectorAll("[data-mkpct]").forEach(function (el) {
      el.textContent = B.pct(b[el.getAttribute("data-mkpct")]);
    });
  }

  // ── events ──────────────────────────────────────────────────────────────────
  // Delegated, because every panel is re-rendered from state rather than mutated in place.
  // Monotonic, not derived from the row count: add-delete-add inside one millisecond used to
  // regenerate an id that had already been used. Nothing indexes labor rows by id today (the page
  // works by array position), so this is closing a door rather than fixing a symptom.
  var laborSeq = 0;
  // THE COMPANY LABOR RATE (Items & Assemblies -> Labor). A new line starts from it rather than blank, so the
  // estimator is never typing a rate Treadwell has already decided. The shipped $33 stands until
  // init() has read the real one, and for good if that read fails.
  var LABOR_RATE = B.SHIPPED_LABOR_RATE;
  /** A one-off labor card at the company rate. ONLY the pop-up's "One-off line" calls this, and only
   *  with a name somebody typed: an unnamed "Task" card can no longer be made. */
  function newLaborRow(name) {
    laborSeq += 1;
    // rate_default is the rate a cleared Rate box falls back to (B.laborRateOf).
    return { id: "u_" + Date.now() + "_" + laborSeq, label: name == null ? "" : String(name),
             guys: "", days: "", rate: LABOR_RATE, rate_default: LABOR_RATE };
  }

  /** What the labor pop-up lists: the live Labor rows of Items & Assemblies, Travel left out (it has
   *  its own block below). Rows that apply to this bid's work type, or name none, are listed first;
   *  a row already on the bid shows locked, so one library line is never two cards with one id.
   *  `rows` is GET /api/library/labor's list, with the shipped crew standing in when the library
   *  cannot answer (the same fallback a new bid is seeded with). */
  function laborPickEntries(rows) {
    var onBid = {};
    M.labor.forEach(function (r) { if (r && r.id != null) onBid[String(r.id)] = true; });
    var out = [];
    B.withCrewFallback(rows).forEach(function (r) {
      if (!r || r.id == null || String(r.id) === "travel") return;
      out.push({ key: "lab:" + r.id, id: r.id, row: r, name: String(r.name == null ? "" : r.name),
                 sub: (r.unit === "hours" ? "Hours" : "Days") + (r.notes ? ", " + r.notes : ""),
                 tag: B.laborPriceText(r, LABOR_RATE),
                 first: B.workTypeApplies(r, "polish"),
                 on: !!onBid[String(r.id)], onText: "On this bid" });
    });
    return out;
  }

  function openLaborPicker(btn) {
    if (!P || pickerOpen) return;
    if (TW.modalOpen && TW.modalOpen()) return;
    pickerOpen = true;          // held across the fetch so a double click opens one pop-up
    loadLaborDefaults().then(function (rows) {
      if (TW.injectModalCss) TW.injectModalCss();
      P.open(document, {
        onClose: function () { pickerOpen = false; },
        title: "Add labor lines",
        sub: "Tick the lines this bid needs, or type a one-off at the bottom.",
        placeholder: "Search labor lines",
        emptyText: "The Labor list in Items & Assemblies is empty. Type a one-off line below.",
        entries: laborPickEntries(rows),
        opener: btn,
        onAdd: function (chosen) {
          var first = M.labor.length;
          chosen.forEach(function (p) { M.labor.push(B.laborRowFromLibrary(p.row, LABOR_RATE)); });
          changed(true);
          refocus('[data-lab="' + first + '"][data-k="guys"]');
        },
        oneOff: {
          label: "One-off line", placeholder: "Name this line", button: "Add line",
          note: B.oneOffRateText(LABOR_RATE),
          onAdd: function (name) {
            var first = M.labor.length;
            M.labor.push(newLaborRow(name));
            changed(true);
            refocus('[data-lab="' + first + '"][data-k="guys"]');
          }
        }
      });
    });
  }

  /** The warning under a labor rate box: the shared "Default value: $X.XX" when this row's rate is
   *  not the company rate (a blank one included), "" (hidden) while the two agree. */
  function rateDefaultText(row, pw) {
    // WHILE A PREVAILING WAGE IS IN FORCE it is every crew line's default (Travel Labor keeps its own):
    // a line that follows it reads the same as the default and says nothing, and a rate typed over it
    // says "Default value: <the prevailing rate>" -- the way back is to retype it or clear the box.
    if (B.num(pw) > 0 && !B.isTravelRow(row)) {
      return dfltWarnText(B.num(B.laborRateOf(row, pw)) !== B.num(pw), B.money2(pw));
    }
    // A line the Labor Calculator filled carries its own default rate (the line's, else the
    // company's at the time) -- warn against THAT, so an untouched calculator rate never shows
    // "Default value" and a changed one names the number it started from.
    // Otherwise the rate the row was filled with (rate_default, stamped on a new bid after seeding:
    // the library row's own rate, else the company rate); a saved bid has no stamp and compares
    // to the company rate as it always did.
    var d = (row || {}).calc_default;
    var dflt = d ? B.num(d.rate)
      : (row && row.rate_default !== undefined && row.rate_default !== null && row.rate_default !== ""
          ? B.num(row.rate_default) : LABOR_RATE);
    return dfltWarnText(B.num((row || {}).rate) !== dflt, B.money2(dflt));
  }

  /** The warning under the Fees + Textura box: the shared "Default value: $N" while the typed
   *  fee differs from the default this bid started from (Defaults tab). "" on a bid with no
   *  `fees_default` -- a saved bid, or a new one whose default was nothing. */
  function feesDefaultText() {
    if (!M || M.fees_default === undefined || M.fees_default === null) return "";
    return dfltWarnText(B.num(M.fees) !== B.num(M.fees_default), B.money2(B.num(M.fees_default)));
  }

  /** The warning under a Lodging / Per Diem rate box (G3): the shared "Default value: $N" while the
   *  rate differs from the one the line was filled with (Items & Assemblies -> Labor), "" while they agree and
   *  on a line with no stamp (a saved bid, which was never filled from anything). */
  function travelRateDefaultText(l) {
    if (!l || l.rate_default === undefined || l.rate_default === null) return "";
    return dfltWarnText(B.num(l.rate) !== B.num(l.rate_default), B.money2(B.num(l.rate_default)));
  }

  /** The warning under a calculator-filled labor box ("guys", "days" or "hours_per_day"): the
   *  shared "Default value: N" while the box differs from what the Labor Calculator filled, "" on a
   *  row it never filled (every saved bid) and while the two agree. */
  function calcDefaultText(row, field) {
    var d = (row || {}).calc_default;
    if (!d || B.laborCalcDiffers(row).indexOf(field) < 0) return "";
    // The calculator had nothing to fill (a from-SF line on a bid with no SF yet): there is no
    // default to name, so say nothing rather than "Default value: blank".
    if (d[field] === "" || d[field] == null) return "";
    var v = field === "hours_per_day" ? B.dayHours(d) : d[field];
    return dfltWarnText(true, field === "hours_per_day" ? v + " hours" : (v === "" ? "blank" : v));
  }

  // Enter saves a sheet's new name and Esc drops it (the Sheets panel's rename box). The panel's own buttons are real
  // <button>s, so Space and Enter already work them; only this box needed a key.
  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (!t || !t.getAttribute) return;
    var name = t.getAttribute("data-sh-name");
    if (name === null) return;
    if (e.key === "Enter") { e.preventDefault(); commitRename(name); }
    else if (e.key === "Escape") { e.preventDefault(); cancelRename(name); }
  });

  // Space and Enter work the on/off slider from the keyboard, as they would a button.
  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (!t || !t.closest || (e.key !== " " && e.key !== "Enter")) return;
    // data-cond is the job's condition switch, the Prevailing wage card's among them.
    var sw = t.closest("[data-on-tk]") || t.closest("[data-on-lab]") || t.closest("[data-on-trv]") ||
      t.closest("[data-cond]") || t.closest("[data-adj-hb]");
    if (!sw) return;
    e.preventDefault();
    sw.click();
  });

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;

    var go_ = t.closest("[data-go]");
    if (go_) { e.preventDefault(); go(parseInt(go_.getAttribute("data-go"), 10)); return; }

    // THE SHEETS PANEL's buttons (see sheetsAct). Any other click puts an armed Delete back to what it was, so a single
    // press never deletes a sheet that a later click has nothing to do with.
    var shAct = t.closest("[data-sh-act]");
    var shWhat = shAct ? shAct.getAttribute("data-sh-act") : null;
    if (sheetsUi.armed && shWhat !== "delete") { sheetsUi.armed = null; paintSheets(); }
    // A refusal is said once: the next click, on anything but another press of Copy or Add, takes it down.
    if (sheetsUi.notice && shWhat !== "copy" && shWhat !== "add") { sheetsUi.notice = null; paintSheets(); }
    if (shAct) {
      sheetsAct(shWhat, shAct.getAttribute("data-sh-tab"), shAct.getAttribute("data-sh-sheet"));
      return;
    }

    // A sheet's name in the panel (and the Open button on an option's Review card): put that sheet on show.
    var secTab = t.closest("[data-section-tab]");
    if (secTab) {
      resetSheetsUi();
      show(secTab.getAttribute("data-section-tab"));
      sheetsUi.focus = secTab.getAttribute("data-sh-key");
      paintSections();
      renderPanel();
      return;
    }

    // The explicit lookup: replaces a typed figure too, because the estimator asked.
    if (t.closest("[data-dist-lookup]")) { lookupDistance(true); return; }

    // THE CARET GOES WITH THE ROW. The button is at the top of the list and the row lands at the
    // bottom of it, so without this the estimator presses Add and nothing they can see happens.
    // focus() scrolls the box into view as a side effect, which is the whole trick.
    // NOTHING IS ADDED BY THE CLICK ITSELF (Hanz, 2026-10-09): it opens the search pop-up, and a
    // row exists only once something was ticked there and Add was pressed.
    var addRow = t.closest("[data-add-row]");
    if (addRow) { openTakeoffPicker(addRow); return; }
    // The answer to the only question a takeoff row asks -- see pickHint. The typed name is read
    // off the row BEFORE becomeKind clears it, then replayed through the setter for the kind that
    // was chosen, so the id lands exactly the way typing the name would have landed it.
    //
    // The caret moves to Measurement rather than nowhere: this button is about to be removed from
    // the page by its own click, and focus left on a destroyed node falls to <body>.
    var kp = t.closest("[data-kind-pick]");
    if (kp) {
      var ki = parseInt(kp.getAttribute("data-kind-row"), 10);
      var krow = M.takeoff[ki];
      if (krow) {
        var kname = krow.pick_name;
        becomeKind(krow, kp.getAttribute("data-kind-pick"));
        if (rowKind(krow) === "item") setMaterial(ki, kname); else setAssembly(ki, kname);
      }
      changed(true);
      refocus('[data-tk="' + ki + '"][data-k="measurement"]');
      return;
    }
    // The way back from a saved row's own coverage to the library's. Only ever on a click: the
    // figures priced a bid that may already have gone out, so nothing else removes them.
    var acr = t.closest("[data-asmcov-reset]");
    if (acr) {
      var ari = parseInt(acr.getAttribute("data-asmcov-reset"), 10);
      if (M.takeoff[ari]) {
        delete M.takeoff[ari].line_cov;
        repaintRow(ari);
        changed(false);
        // This button was removed from the page by its own click; focus left on it falls to
        // <body>. Put the caret on Measurement, as the kind pick above does.
        refocus('[data-tk="' + ari + '"][data-k="measurement"]');
      }
      return;
    }
    var dr = t.closest("[data-del-row]");
    if (dr) {
      // The last row stays: the x is not drawn on it, and a stale button must not empty the step.
      if (M.takeoff.length <= 1) return;
      M.takeoff.splice(parseInt(dr.getAttribute("data-del-row"), 10), 1);
      changed(true);
      return;
    }
    var addLab = t.closest("[data-add-lab]");
    if (addLab) { openLaborPicker(addLab); return; }
    // + Add a trade, and the x on a trade the estimator added. The panel is redrawn (a box comes or goes), and a
    // new trade's name box takes the focus, since naming it is the first thing it needs.
    if (t.closest("[data-pw-add]")) {
      var at = addPrevailingTrade();
      changed(true);
      var nameBox = document.querySelector('[data-pw="label"][data-pw-i="' + at + '"]');
      if (nameBox && nameBox.focus) nameBox.focus();
      return;
    }
    var pwDel = t.closest("[data-pw-del]");
    if (pwDel) {
      if (removePrevailingTrade(parseInt(pwDel.getAttribute("data-pw-del"), 10))) changed(true);
      return;
    }
    var dl = t.closest("[data-del-lab]");
    if (dl) {
      if (M.labor.length <= 1) return;
      M.labor.splice(parseInt(dl.getAttribute("data-del-lab"), 10), 1);
      changed(true);
      return;
    }
    // Review's own toggles -- same idea as polish-intake.js's onClick/toggleCondition, just
    // flipping the one flag in place rather than routing through that page's carry-four/legacy-
    // cell bookkeeping, none of which any of these five keys need.
    // THE ON/OFF SLIDER on a takeoff row and on a labor row (the condition cards' own switch is the
    // `data-cond` one below). Off is an explicit `enabled:false`; back on DELETES the key, so a row
    // that has been flipped back is indistinguishable from one never touched.
    // THE HARD BID SWITCH on the Discount line: the rule's figure goes into the box (greyed) and the price, and the
    // words beside the switch say what it gives. In place: the repaint moves the note, the box's
    // grey figure and the line, and the focus stays on the switch.
    var hbSw = t.closest("[data-adj-hb]");
    if (hbSw) {
      setAdjust("hard_bid", !adjOn("hard_bid"));
      var hbNow = adjOn("hard_bid");
      hbSw.className = "mw-sw" + (hbNow ? " on" : "");
      hbSw.setAttribute("aria-checked", hbNow ? "true" : "false");
      changed(false);
      return;
    }
    var gypIso = t.closest("[data-gyp-iso]");
    if (gypIso) {
      var isoSec = gypOpen();
      if (isoSec) {
        isoSec.section.gyp = Object.assign({}, isoSec.section.gyp, { iso_all: !(isoSec.section.gyp || {}).iso_all });
      }
      changed(true);
      return;
    }
    var onTk = t.closest("[data-on-tk]");
    if (onTk) {
      var oi = parseInt(onTk.getAttribute("data-on-tk"), 10);
      if (M.takeoff[oi]) {
        if (B.rowOn(M.takeoff[oi])) M.takeoff[oi].enabled = false; else delete M.takeoff[oi].enabled;
      }
      changed(true);
      return;
    }
    // LODGING AND PER DIEM. The slider writes an explicit true/false (this block's convention, see
    // normalizeTravel) and marks the line `hand`, so a later distance answer cannot override a
    // choice the estimator made. (The "Type my own" switch is gone: typing leaves auto, clearing
    // the box returns to it -- see the change handler.)
    var onTrv = t.closest("[data-on-trv]");
    if (onTrv) {
      var tl = M.travel && M.travel[onTrv.getAttribute("data-on-trv")];
      if (tl) { tl.enabled = !tl.enabled; tl.hand = true; }
      changed(true);
      return;
    }
    var onLab = t.closest("[data-on-lab]");
    if (onLab) {
      var ol = parseInt(onLab.getAttribute("data-on-lab"), 10);
      if (M.labor[ol]) {
        if (B.rowOn(M.labor[ol])) M.labor[ol].enabled = false; else delete M.labor[ol].enabled;
      }
      changed(true);
      return;
    }
    var cond = t.closest("[data-cond]");
    if (cond) {
      var ck = cond.getAttribute("data-cond");
      M.conditions[ck] = !M.conditions[ck];
      // TOUCHED, SO IT STAYS. A card drawn only because it arrived switched ON (conditionShown)
      // would vanish under the cursor the moment it was switched off, and could not be switched
      // back on. Once the estimator has pressed it, this bid draws it whatever the snapshot said.
      if (M.conditions_shown && Object.prototype.hasOwnProperty.call(M.conditions_shown, ck)) {
        delete M.conditions_shown[ck];
      }
      // THE PREVAILING WAGE CARD's own switch repaints in place (repaintNumbers): opening or closing the card must
      // not rebuild the panel and drop the focus off the switch. Every other condition switch rebuilds as it did.
      changed(cond.getAttribute("data-pw-sw") === null);
      return;
    }
  });

  /** Write one box of the Gyp card into the section on show. `key` is "preset", "mix", "sound_mat", "mobs",
   *  "moisture_tests" or
   *  "thickness.<area>"; any other key is ignored (the keys come off an attribute). The preset renames the section's
   *  workbook tab, so the model and the tab on show are both replaced. */
  function setGyp(key, value) {
    var e = gypOpen();
    if (!e) return;
    var held = e.section.gyp || {};
    if (key === "preset") {
      if (G.tabs().indexOf(value) < 0 || value === e.sheet) return;
      ROOT = B.moveSectionSheet(ROOT, e.tab, value);
      // What the draft kept under the old key (the sheet's proposal settings, its notes, its own price override and its lines)
      // follows it, or the sheet comes back with fresh settings and an option the estimator switched off prints. A copy keeps its key.
      if (e.tab === e.sheet) {
        var carried = B.moveSheetDraftPatch(TW.getState(), e.tab, value);
        if (Object.keys(carried).length) TW.setState(carried);
      }
      // A section filed under its sheet's name is re-filed under the new one; a copy keeps its Copy<N> key.
      show(e.tab === e.sheet ? value : e.tab);
      return;
    }
    var next = null;
    if (key === "mix") next = { mix: G.mixOf({ mix: value }) };
    else if (key === "sound_mat") next = { sound_mat: value };
    else if (key === "mobs") next = { mobs: value };
    else if (key === "moisture_tests") next = { moisture_tests: value };
    else if (key.indexOf("thickness.") === 0) {
      var area = key.slice("thickness.".length);
      if (G.BUCKETS.indexOf(area) < 0) return;
      next = { thickness: Object.assign({}, held.thickness, Object.fromEntries([[area, value]])) };
    }
    if (next) e.section.gyp = Object.assign({}, held, next);
  }

  /** A Gyp area row says which area it is (soft, hard or corridor) with a `bucket` mark, which the model reads to
   *  split the proposal's area line. A row pointed at any other assembly carries none. */
  function stampArea(row) {
    var area = G ? G.bucketOfAssembly(row.assembly_id) : null;
    if (area) row.bucket = area; else delete row.bucket;
  }

  /** Point a takeoff row at an assembly, by the name that was typed or picked. */
  function setAssembly(i, text) {
    var row = M.takeoff[i];
    if (!row) return false;
    var before = row.assembly_id || "";
    row.assembly_name = text;
    var asm = assemblyByName(text);
    // A ROW ALREADY POINTED AT AN ASSEMBLY OF THIS NAME KEEPS IT. Two assemblies can share a name
    // (the add-line pop-up pins the one that was ticked); resolving by name again on a later blur
    // would hand the row the first twin and its unit.
    var cur = asmById(before);
    if (asm && cur && cur.id !== asm.id && String(cur.name == null ? "" : cur.name) === String(asm.name == null ? "" : asm.name)) {
      asm = cur;
    }
    row.assembly_id = asm ? asm.id : "";
    stampArea(row);
    // A DIFFERENT ASSEMBLY IS DIFFERENT LINES: coverage typed against the old one's lines would
    // land on the wrong materials, so it goes with the old pick.
    if (row.assembly_id !== before) delete row.line_cov;
    // The row's unit is the assembly's own, taken when the pick actually CHANGES. Doing it on
    // every keystroke would re-stamp a SAVED row whose unit differs from the library's, which is
    // the one case that must keep what it was saved with (and say so; see unitView). An assembly
    // with no unit set is SF, today's default. Painted in place: a rebuild here would take the
    // caret with it.
    //
    // Also taken when the saved unit is not SF or LF (a row the totals count nowhere): retyping the
    // name is the way out, as the row's note says. A measurement already on the row is cleared when
    // the unit really changes (B.adoptTakeoffUnit): the digits belong to the old unit.
    if (asm && (row.assembly_id !== before || !B.validTakeoffUnit(row.unit))) {
      B.adoptTakeoffUnit(M.takeoff, i, B.takeoffUnit("asm", asm).unit);
      paintUnits();
    }
    return !!asm;
  }

  /** setAssembly's opposite number, and deliberately simpler than it.
   *
   *  NEVER ADOPTS `item.unit`. An assembly declares the unit it is measured in, so picking one can
   *  legitimately switch the row to LF. An item's `unit` is the unit it is BOUGHT in -- gallons,
   *  kits, pails -- which has nothing to do with how the floor is measured. Copying it onto the
   *  row would set a 12,000 SF area to "gallons" and price against it. What a material CAN say
   *  about measurement is its coverage basis (SF or LF), and that is what the row takes.
   *
   *  COVERAGE IS LEFT ALONE on a pick, for the reason covPlaceholder gives: the item's default is
   *  shown as a placeholder and used when the box is empty, so writing it INTO the box would turn
   *  a library default into something indistinguishable from a figure somebody typed for this
   *  job. */
  function setMaterial(i, text) {
    var row = M.takeoff[i];
    if (!row) return false;
    var before = row.item_id || "";
    row.item_name = text;
    // Through itemByName, not a loop of its own: that is the one name lookup that refuses Dye and
    // the joint filler kit, so a row typed as "Dye, per coat" cannot become a second dye charge.
    var hit = itemByName(text);
    // A ROW ALREADY POINTED AT A MATERIAL OF THIS NAME KEEPS IT. Two materials can share a name (the
    // add-line pop-up pins the one that was ticked); resolving by name again on a later blur would
    // hand the row the first twin and re-stamp its unit.
    var cur = itemById(before);
    if (hit && cur && cur.id !== hit.id &&
        String(cur.name == null ? "" : cur.name).trim().toLowerCase() ===
        String(hit.name == null ? "" : hit.name).trim().toLowerCase()) {
      hit = cur;
    }
    row.item_id = hit ? hit.id : "";
    // THE UNIT IS THE MATERIAL'S COVERAGE BASIS (Items & Assemblies: "Coverage is per SF / LF"),
    // taken when the pick CHANGES, like an assembly's. Never `hit.unit`: see the paragraph above.
    // Also when the saved unit is not SF or LF (see setAssembly). A measurement already on the row
    // is cleared if the unit really changes: the digits belong to the old unit (B.adoptTakeoffUnit).
    if (hit && (row.item_id !== before || !B.validTakeoffUnit(row.unit))) {
      B.adoptTakeoffUnit(M.takeoff, i, B.takeoffUnit("item", hit).unit);
      paintUnits();
    }
    return !!hit;
  }

  /** Move a row across the line between the kinds, clearing what it is leaving behind.
   *
   *  A LEFTOVER item_id WOULD DECIDE THE ROW, because rowKind reads it first: an assembly row
   *  still carrying the id of the material it used to be would draw as a material for ever. So
   *  the crossing is explicit rather than additive. Coverage goes with the item fields because
   *  coverage is a material's field -- an assembly keeps coverage on its own lines in the
   *  library, and a stale one on the row would be read by nothing and believed by everybody. */
  function becomeKind(row, kind) {
    if (!row) return;
    delete row.pick_name;
    if (kind === "item") {
      row.kind = "item";
      row.item_id = ""; row.item_name = "";
      if (row.coverage == null) row.coverage = "";
      delete row.assembly_id; delete row.assembly_name; delete row.line_cov;
      return;
    }
    if (kind === "asm") {
      row.kind = "asm";
      row.assembly_id = ""; row.assembly_name = "";
      delete row.item_id; delete row.item_name; delete row.coverage; delete row.line_cov;
      return;
    }
    row.kind = "new"; row.pick_name = "";
    delete row.assembly_id; delete row.assembly_name;
    delete row.item_id; delete row.item_name; delete row.coverage; delete row.line_cov;
  }

  /** Point a takeoff row at whatever was typed or picked, and let the pick decide what kind of
   *  row it is. The auto-categorising half of Hanz's one button.
   *
   *  IT DELEGATES rather than reimplements: once the kind is settled, setAssembly and setMaterial
   *  do exactly what they did before, including setAssembly adopting the assembly's SF/LF and
   *  setMaterial pointedly not adopting the item's Gal/Pail. Their rules are tested; a second
   *  copy of them here would be a second opinion.
   *
   *  THE KIND CHANGES ONLY ON A RESOLVED PICK. Clearing the box leaves the row exactly the kind it
   *  already was -- the rule the two-button version carried, for its reason: a material row whose
   *  name is cleared must not silently become an assembly row and lose its measurement and
   *  coverage.
   *
   *  A NAME THAT IS BOTH IS NOT GUESSED. A row that already has a kind keeps it and is not asked;
   *  a row that does not stays undecided and pickHint asks. Returns true when the kind actually
   *  moved, which is the only case a caller has to redraw the card for. */
  function setPick(i, text) {
    var row = M.takeoff[i];
    if (!row) return false;
    var was = rowKind(row);
    var hit = lineMatches(text);
    var want = was;
    // BOTH IS A REFUSAL, not a choice: `want` stays whatever the row already was. On a row that
    // has a kind that means it keeps it; on an undecided row it means it stays undecided, and
    // pickHint puts the question on screen. It is written out rather than left implicit because
    // the silent alternative -- falling through to one of the two branches below -- is the bug.
    if (hit.asm && hit.item) want = was;
    else if (hit.asm) want = "asm";
    else if (hit.item) want = "item";
    if (want !== was) becomeKind(row, want);
    if (want === "item") setMaterial(i, text);
    else if (want === "asm") setAssembly(i, text);
    else row.pick_name = text;        // still undecided: hold what was typed, price nothing
    return want !== was;
  }

  document.addEventListener("input", function (e) {
    var el = e.target;
    if (!el || !el.matches) return;

    // THE SHEETS PANEL's two boxes. A name being typed is held and checked when it is committed, never mid-word; the
    // reason shown under it from an earlier refusal is taken down as soon as typing starts again. The words an option
    // prints are saved as they are typed and the panel is NOT redrawn, which would take the caret out of the box.
    var shName = el.getAttribute("data-sh-name");
    if (shName !== null) {
      sheetsUi.draft = el.value;
      if (sheetsUi.error) {
        sheetsUi.error = "";
        var shErr = document.querySelector("[data-sh-error]");
        if (shErr) shErr.hidden = true;
        lastSheets = null;
      }
      return;
    }
    var shDesc = el.getAttribute("data-sh-desc");
    if (shDesc !== null) { setOptionDesc(shDesc, el.value); return; }

    if (el.matches("[data-contingency]")) {
      M.contingency = el.value;
      changed(false);
      return;
    }
    // AN OVERRIDE BOX. `changed(false)`: the chain reprices and repaintNumbers refreshes the amounts, the other boxes'
    // greyed rules and the warnings in place, so the caret stays in the box being typed in.
    var adjKey = el.getAttribute("data-adj");
    if (adjKey !== null) {
      setAdjust(adjKey, el.value);
      changed(false);
      return;
    }
    // `changed(false)` like contingency: the chain reprices and repaintNumbers refreshes every
    // keyed cell, without the full rebuild that would take the caret out of the box.
    if (el.matches("[data-fees]")) {
      M.fees = el.value;
      changed(false);
      return;
    }
    // THE ESTIMATOR'S OWN MILES. They always win over the server's figure. A number applies at
    // once (>= 70 brings the travel lines on and fills Travel Labor's hours and guys, under 70 grays
    // them and takes the hours the tool wrote back; a line flipped by hand stays as flipped, and so
    // do hours typed); clearing the box goes back to "unknown" and asks the server again. The panel is
    // rebuilt so the three cards repaint, with the caret carried (the pattern the Travel boxes
    // below use) -- a half-typed "7" before "70" is an ordinary moment, not an error.
    if (el.matches("[data-dist-miles]")) {
      var rawMiles = String(el.value);
      var typedMiles = B.milesOrNull(el.value);
      if (typedMiles !== null) {
        B.applyDistance(ROOT, { miles: typedMiles, source: "typed", key: addressKey() });
        changed(true);
        refocus("[data-dist-miles]", rawMiles);
      } else if (String(el.value).trim() === "") {
        B.clearDistance(ROOT);
        changed(true);
        refocus("[data-dist-miles]");
        lookupDistance(false);
      }
      return;
    }
    if (!el.matches("input")) return;
    // The Gyp card's text boxes: a thickness for an area, and the mobilizations. Repriced in place, never rebuilt.
    var gypKey = el.getAttribute("data-gyp");
    if (gypKey !== null) {
      setGyp(gypKey, el.value);
      changed(false);
      return;
    }
    var k = el.getAttribute("data-k");

    // THIS BID'S COVERAGE for Joint Filler / Dye (M.cond_cov). It takes `changed(false)`: reprice
    // and repaint in place, never a rebuild, so the caret stays in the box being typed in.
    var cc = el.getAttribute("data-condcov");
    if (cc !== null) {
      if (!M.cond_cov || typeof M.cond_cov !== "object") M.cond_cov = {};
      M.cond_cov[cc] = el.value;
      changed(false);
      return;
    }

    // THE PREVAILING WAGE CARD's Rate and Fringes. `changed(false)`: the sum, the entry half wage and every
    // labor line that follows the rate repaint in place, so the caret stays in the box being typed in.
    var pwField = el.getAttribute("data-pw");
    if (pwField !== null) {
      setPrevailing(pwField, el.value, parseInt(el.getAttribute("data-pw-i"), 10));
      changed(false);
      return;
    }

    var ti = el.getAttribute("data-tk");
    if (ti !== null && k) {
      var i = parseInt(ti, 10);
      // THE CARD IS REBUILT HERE AND NOWHERE ELSE. A pick that changes the row's kind adds or
      // removes the Coverage field, which repainting text cannot do -- so the one card is redrawn
      // and the caret put back at the end of the name being typed. Same trade as the Guys switch
      // above: one rebuild, mid-keystroke, with the caret carried, because the alternative is a
      // field that appears only after the next unrelated render.
      //
      // It is deliberately NOT done in `change`: by the time that fires the estimator has tabbed
      // into Measurement, and rebuilding then destroys the box they are standing in.
      if (k === "pick") {
        var asmBefore = M.takeoff[i] ? (M.takeoff[i].assembly_id || "") : "";
        var flipped = setPick(i, el.value);
        // A new assembly drops the old one's saved coverage (setAssembly), and the note about it
        // lives in the card -- so the card is redrawn then too, not only when the kind moved.
        if (!flipped && M.takeoff[i] && (M.takeoff[i].assembly_id || "") !== asmBefore) flipped = true;
        changed(false);
        if (flipped) {
          repaintRow(i);
          refocus('[data-tk="' + i + '"][data-k="pick"]');
        }
        return;
      }
      if (M.takeoff[i]) {
        if (k === "measurement") B.setMeasurement(M.takeoff, i, el.value);
        else M.takeoff[i][k] = el.value;
      }
      changed(false);
      // A carrier edit moves the same-floor rows' numbers too: write them into their boxes in
      // place (a rebuild would take the caret out of the box being typed in).
      if (k === "measurement") {
        M.takeoff.forEach(function (row, n) {
          if (n === i) return;
          var box = document.querySelector('[data-tk="' + n + '"][data-k="measurement"]');
          if (box && row && String(box.value) !== String(row.measurement == null ? "" : row.measurement)) {
            box.value = row.measurement;
          }
        });
      }
      return;
    }

    // Lodging / Per Diem boxes. Typing in the auto quantity is how you leave auto (the same trade
    // Travel's Guys box makes): one rebuild so the hint and the switch say so, caret carried.
    var trvKey = el.getAttribute("data-trv");
    if (trvKey !== null && k) {
      var tline = M.travel && M.travel[trvKey];
      if (tline) {
        if (k === "qty" && tline.qty_auto !== false) {
          tline.qty_auto = false;
          tline.qty = el.value;
          changed(true);
          refocus('[data-trv="' + trvKey + '"][data-k="qty"]');
          return;
        }
        tline[k] = el.value;
      }
      changed(false);
      return;
    }

    var li = el.getAttribute("data-lab");
    if (li !== null && k) {
      var j = parseInt(li, 10);
      if (M.labor[j]) {
        // A KEYSTROKE IN A TRAVEL LABOR GUYS OR HOURS BOX MAKES THAT BOX THE ESTIMATOR'S, clearing it included (2026-10-20 audit):
        // the row is marked (B.markTypedByHand), and no later distance answer writes into a box that is marked.
        if (k === "guys" || k === "days") B.markTypedByHand(M.labor[j], k);
        // TYPING IN THE AUTO BOX IS HOW YOU LEAVE AUTO. Travel's Guys follows the crew (its size, or the
        // man-days on a bid saved before 2026-10-12) until somebody disagrees with it, and the disagreement is the keystroke -- asking them
        // to find a control first, to then be allowed to type the number they already have in
        // mind, is a worse trade than the one line it takes to notice. `changed(true)` so the
        // hint under the box repaints from "Most guys on one labor line above" to the way back.
        if (k === "guys" && M.labor[j].guys_auto) {
          M.labor[j].guys_auto = false;
          M.labor[j][k] = el.value;
          changed(true);
          refocus('[data-lab="' + j + '"][data-k="guys"]');
          return;
        }
        // A typed RATE goes in through B.setLaborRate: a rate typed to the line's own default is marked as typed,
        // so a prevailing wage in force does not take it back (the number alone cannot say it was typed).
        if (k === "rate") B.setLaborRate(M.labor[j], el.value);
        else M.labor[j][k] = el.value;
      }
      changed(false);
      return;
    }
  });

  /** Put the caret back in a box a full repaint just replaced, at the end of what is in it.
   *
   *  Only the auto-to-manual switch needs this: it is the one edit on this panel that has to
   *  rebuild the card mid-keystroke (the hint under the box changes), and a rebuild that drops
   *  the caret would make the first character somebody types the last one that lands. */
  function refocus(sel, typed) {
    var el = document.querySelector(sel);
    if (!el) return;
    // The rebuilt box was drawn from the stored number, so a half-typed "12." came back as "12".
    // Put back exactly what was typed.
    if (typed !== undefined && el.value !== typed) el.value = typed;
    if (!el.focus) return;
    el.focus();
    try { el.setSelectionRange(el.value.length, el.value.length); } catch (err) {}
  }

  document.addEventListener("change", function (e) {
    var el = e.target;
    if (!el || !el.getAttribute) return;
    // THE SHEETS PANEL's two radio groups: which sheet is the base bid (asked, then confirmed), and Total or Add / Deduct.
    var shBase = el.getAttribute("data-sh-base");
    if (shBase !== null) { askBase(shBase); return; }
    var shMode = el.getAttribute("data-sh-mode");
    if (shMode !== null) { setPriceMode(shMode, el.value); return; }
    // The Gyp card's three selects (sheet, mix, sound mat). The sheet moves the section to another workbook tab, so
    // the whole page is repainted; the other two reprice and repaint the panel.
    var gypSel = el.getAttribute("data-gyp");
    if (gypSel === "preset" || gypSel === "mix" || gypSel === "sound_mat") {
      setGyp(gypSel, el.value);
      changed(true);
      return;
    }
    // THE PREVAILING WAGE CARD's "Labor lines use this rate": the trade whose rate the labor lines follow. Every
    // figure that moves with it (the lines, the header, the note) repaints in place, so the radio keeps focus.
    var pwPick = el.getAttribute("data-pw-pick");
    if (pwPick !== null) {
      if (el.checked) setPrevailing("pick", el.value, parseInt(pwPick, 10));
      changed(false);
      return;
    }
    // HOURS A DAY on a calculator-filled labor line is a <select>, which the "input" handler above
    // skips (it only takes <input>); it reprices here, the way the takeoff unit select does.
    var hl = el.getAttribute("data-lab");
    if (hl !== null && el.getAttribute("data-k") === "hours_per_day") {
      if (M.labor[parseInt(hl, 10)]) M.labor[parseInt(hl, 10)].hours_per_day = el.value;
      changed(false);
      return;
    }
    // A CLEARED GUYS / NIGHTS / DAYS / HOURS BOX STAYS EMPTY (Hanz, 2026-10-12: "nights, days, guys and hours
    // should have nothing when it starts"). From 2026-10-07 clearing the box handed the figure back
    // to the man-days; that is gone, because the man-days are no longer a value the box can hold.
    // Empty is the estimator's own answer and prices $0. The hint under the box says what the
    // man-days are, as text.
    //
    // Nothing has to run here for the Travel Labor boxes: the clearing already happened on `input`, which is
    // where a keystroke in a Travel Labor Guys or Hours box leaves its mark on the row (B.markTypedByHand: guys_typed and
    // hours_typed). That mark, saved with the row, is what stops a distance answer from refilling a box that was
    // cleared. (Until 2026-10-20 an empty Travel box read as nobody's yet, and the next answer wrote into it.)
    var blankKey = el.getAttribute("data-k");
    // A CLEARED RATE BOX GOES BACK TO THE LINE'S OWN RATE (Hanz, 2026-10-09), on change, so typing
    // "3", backspace, "4" never snaps. The row was already priced at that rate while
    // the box was empty (B.laborRateOf); this writes it back into the model and the box so the screen,
    // the total and the saved blob agree. In place, never a rebuild: a rebuild eats the next click.
    // Typing 0 is not blank and stays zero. A row with no default to fall back to stays blank.
    if (blankKey === "rate" && el.getAttribute("data-lab") !== null && String(el.value).trim() === "") {
      var rateRow = M.labor[parseInt(el.getAttribute("data-lab"), 10)];
      if (rateRow && B.laborRateOf(rateRow) > 0) {
        // The line's OWN rate goes back into the row (what turning the prevailing wage off restores), and
        // the box shows what the line prices at now: the prevailing rate while the card has one in force.
        var back = B.laborRateOf(rateRow);
        rateRow.rate = back;
        delete rateRow.rate_typed;     // the line follows its default again (the prevailing rate, while one is in force)
        el.value = String(B.laborRateBox(rateRow, B.prevailingApplied(M)));
        changed(false);
        return;
      }
    }

    var ti = el.getAttribute("data-tk");
    if (ti === null) return;
    var i = parseInt(ti, 10);
    var k = el.getAttribute("data-k");
    if (k === "measurement") { askMeasure(i); return; }
    // No `unit` branch: a takeoff row's unit is read-only now (it comes from Items & Assemblies),
    // so nothing on the page fires a change for it.
    if (k === "pick") {
      // Committed — blurred, or picked off the list. A TARGETED repaint, not a re-render.
      //
      // `change` on this field fires when the estimator leaves it, and the ordinary way to leave it
      // is Tab into Measurement. A full re-render at that moment rebuilds the row, destroys the
      // field they have just tabbed into, and drops focus onto <body> — so the number they type
      // next goes nowhere at all. Found by tabbing between the two fields on staging; every unit
      // test passed, because a test never has to reach for the keyboard.
      //
      // Nothing is lost by repainting instead: the hint, the per-unit line, the measurement label
      // and the cost are all keyed and refreshed by repaintNumbers, and setAssembly already syncs
      // the unit select in place.
      // NO REBUILD, not even when the kind moved. Typing or picking already fired `input`, which
      // redrew the card and kept the caret; the only way here without that is a value set by
      // something other than a person, and a Coverage box that waits for the next render beats a
      // caret thrown on the floor.
      setPick(i, el.value);
      changed(false);
    }
  });

  // LEAVING A BOX THE PAGE OWNS SETTLES IT. repaintNumbers never writes into the box the estimator is in (paintTravelBoxes), so a
  // distance answer that landed while they stood in a Travel Labor box left the model ahead of the screen. When they leave it
  // without typing, the box shows what the model holds. A box they typed in already holds what they typed, so this writes nothing there.
  document.addEventListener("focusout", function (e) {
    var el = e.target;
    if (!el || !el.getAttribute || el.getAttribute("data-lab") === null) return;
    var v = ownedBoxFigure(el);
    if (v !== null && el.value !== v) el.value = v;
  });

  // A MEASUREMENT CHANGED BY ACCIDENT IS ASKED ABOUT (Hanz, 2026-10-17: "add a pop up when we accidentally edit the
  // measurement"). The takeoff as it stood when the box was entered is kept; leaving the box (Tab, a click away or
  // Enter) with a different number over one that was already there asks whether to keep it. "Put back" restores that
  // takeoff whole, because the keystrokes moved more than the one number: a floor's coats follow the floor. A first
  // number typed into an empty box is never asked about, and neither is retyping the same number.
  var measureStart = null;
  document.addEventListener("focusin", function (e) {
    var el = e.target;
    if (!el || !el.getAttribute || el.getAttribute("data-k") !== "measurement") return;
    var ti = el.getAttribute("data-tk");
    if (ti === null) return;
    measureStart = { i: parseInt(ti, 10), rows: JSON.parse(JSON.stringify(M.takeoff || [])) };
  });

  function measureWords(v, unit) {
    return v > 0 ? B.fmtSf(v) + (unit ? " " + unit : "") : "nothing";
  }

  function askMeasure(i) {
    var start = measureStart;
    measureStart = null;
    if (!start || start.i !== i || !start.rows[i] || !M.takeoff[i]) return;
    var was = B.num(start.rows[i].measurement);
    var now = B.num(M.takeoff[i].measurement);
    if (!(was > 0) || was === now) return;
    if (!TW.confirmDanger || (TW.modalOpen && TW.modalOpen())) return;
    var unit = M.takeoff[i].unit || "";
    var rows = start.rows;
    // After the focus has finished moving, so it goes back to wherever the estimator was going.
    setTimeout(function () {
      var back = document.activeElement;
      TW.confirmDanger({
        tone: "warn", icon: "pencil", title: "Change this measurement?",
        name: rowName(M.takeoff[i]) || "this row", before: "Row " + (i + 1) + ", ",
        after: ", goes from " + measureWords(was, unit) + " to " + measureWords(now, unit) + ".",
        detail: "Every price on the bid follows it.",
        cancelText: "Put back " + measureWords(was, unit), confirmText: "Keep " + measureWords(now, unit),
        focus: "container", dismiss: "explicit"
      }).then(function (keep) {
        if (!keep) {
          Array.prototype.splice.apply(M.takeoff, [0, M.takeoff.length].concat(rows));
          document.querySelectorAll('[data-tk][data-k="measurement"]').forEach(function (box) {
            var row = M.takeoff[parseInt(box.getAttribute("data-tk"), 10)];
            if (row) box.value = row.measurement == null ? "" : row.measurement;
          });
          changed(false);
        }
        try { if (back && back !== document.body && document.contains(back)) back.focus(); } catch (err) { /* gone */ }
      });
    }, 0);
  }

  // ── boot ────────────────────────────────────────────────────────────────────
  /** The estimator's own default labor lines, out of Library -> Default Items & Assemblies.
   *  [] when there are none, and [] when the read did not work.
   *
   *  IT CANNOT FAIL THE PAGE, and that is the entire point of it being its own function rather
   *  than a third entry in the Promise.all below. `public.library_labor` is on staging and NOT on
   *  production, by Hanz's decision -- so on prod today this endpoint has no table behind it, and
   *  a missing table has to read as "no custom labor lines", never as a broken screen. A new bid
   *  that opened with no Labor step at all would be a far worse outcome than one that opened
   *  without a default nobody has defined yet.
   *
   *  The assemblies/items pair below is genuinely unrecoverable -- with no assemblies a takeoff
   *  row has nothing to point at, so the page stops and says so -- which is why this read is kept
   *  out of the same all(): one rejection there takes the whole screen down, and this read must
   *  never be able to do that. */
  async function loadLaborDefaults() {
    try {
      var res = await api("/api/library/labor");
      var j = await res.json();
      return (j && j.labor instanceof Array) ? j.labor : [];
    } catch (e) {
      return [];
    }
  }

  /** The Labor Calculator's saved modes, or [] when there are none or the read cannot answer.
   *  NEVER THROWS, like loadLaborDefaults: `library_labor_calc` may not exist on a database yet
   *  (backend/ops/labor_calc.sql), and a missing table has to mean "no line has a mode" -- the
   *  estimate opens with today's blank crew rows -- never a broken screen. */
  async function loadLaborCalc() {
    try {
      var res = await api("/api/library/labor-calc");
      var j = await res.json();
      return (j && j.calc instanceof Array) ? j.calc : [];
    } catch (e) {
      return [];
    }
  }

  /** The library's answers for the three Takeoff conditions, or [] when the read cannot answer.
   *  NEVER THROWS.
   *
   *  The same posture as loadLaborDefaults directly above, and for a sharper reason:
   *  `condition_defaults` is applied to NEITHER database as of 2026-09-18 — it is written into
   *  both schema files and waiting on Hanz — so today this request has no table behind it
   *  anywhere. An estimate that refused to open over a table nobody has promoted would be a far
   *  worse outcome than one that opens with the answers the tool ships, which is exactly what []
   *  produces: seedConditionDefaults writes nothing and freshModel's literals stand. */
  async function loadConditionDefaults() {
    try {
      var res = await api("/api/condition-defaults");
      var j = await res.json();
      return (j && j.conditions instanceof Array) ? j.conditions : [];
    } catch (e) {
      return [];
    }
  }

  /** The company labor rate, or the shipped $33 when nothing is filed or the read cannot answer.
   *  NEVER THROWS: a rate service being down must not stop an estimate opening. GET
   *  /api/markup/rules needs no admin, so every estimator can read it. */
  async function loadLaborRate() {
    try {
      var res = await api("/api/markup/rules?layout=global");
      var j = await res.json();
      return B.laborRateOrShipped(B.laborRateFromRules(j && j.rules));
    } catch (e) {
      return B.SHIPPED_LABOR_RATE;
    }
  }

  /** Every filed Markups rule, for the rates a NEW section keeps (B.activateSection). NEVER THROWS: a rate service
   *  that is down means the section is priced at the built-ins, which is what it is given when nothing is filed. */
  async function loadMarkupRules() {
    try {
      var res = await api("/api/markup/rules");
      var j = await res.json();
      return (j && j.rules instanceof Array) ? j.rules : [];
    } catch (e) {
      return [];
    }
  }

  /** The Fees + Textura default (Markups -> Global), a number or null. Read for a NEW bid only and
   *  NEVER THROWS: a rate service being down must not stop an estimate opening. */
  async function loadFeesDefault() {
    try {
      var res = await api("/api/markup/rules?layout=global");
      var j = await res.json();
      return B.feesFromRules(j && j.rules);
    } catch (e) {
      return null;
    }
  }

  /** The Lodging and Per Diem rates (Items & Assemblies -> Labor, Hotel and Per Diem), `{lodging, per_diem}` with null for any
   *  that is not filed. Read for a NEW bid only (see init) and NEVER THROWS, like loadLaborRate:
   *  a rate service being down must not stop an estimate opening, and null means the shipped
   *  $70 / $45 stand. */
  async function loadTravelRates() {
    try {
      var res = await api("/api/markup/rules?layout=global");
      var j = await res.json();
      return B.travelRatesFromRules(j && j.rules);
    } catch (e) {
      return { lodging: null, per_diem: null };
    }
  }

  async function init() {
    try { if (window.TWAuth && window.TWAuth.ready) await window.TWAuth.ready; } catch (e) {}
    // shared.js is still deciding which draft this page is on (it can even hydrate and reload),
    // and every decision below turns on that id.
    try { await TW.draftReady; } catch (e) {}
    adopt(TW.getState());

    // Before the library, before the form, before anything can be typed: whatever happens after
    // this line writes to a test project. A save timer started against the real bid and fired
    // after the switch would be the bug with extra steps.
    if (!(await S.enterSandbox(adopt))) return;

    // THE DEFAULTS ARE FOR A NEW BID AND NOTHING ELSE. Decided HERE, on the saved blob, the moment
    // the sandbox has settled which draft this page is on and before a single row can be typed --
    // and never again. B.laborUnstated is what it turns on: true only when nothing has ever stated
    // a labor row for this estimate, so there is no saved work for a default to land on.
    //
    // Read the blob, not M: adopt() has already run it through migrateModel, which fills a missing
    // `labor` in from freshModel(), so M cannot be asked this question -- every model has four
    // rows whether or not anybody chose them.
    //
    // The read is only STARTED when the answer could be used, so a saved bid does not pay for a
    // request whose result it would have to throw away; starting it here rather than after the
    // library means the two overlap instead of queueing. It is awaited below, once the library has
    // landed. Null, not an empty array, for "not asked": an empty array is a real answer (the
    // table exists and holds nothing) and the two must not be confused.
    var savedEstimate = state.polish_estimate;
    var newBid = B.laborUnstated(savedEstimate);
    // A SAVED BID WHOSE JOB TYPE MOVED (Polish to Combo) is given a new section, and a new section is crewed
    // from the library like any other, so the library's labor lines and the calculator's modes are asked for
    // it too. Nothing else the defaults carry (travel rates, the fees default, the distance) is asked: those
    // belong to a new bid, and the root keeps the rows it was saved with.
    var jobType = state.work_type;
    var jobSections = T.isJobType(jobType) && T.jobType(jobType).ready === true &&
      (jobType !== "polish" || B.sectionsLeaving(ROOT, jobType).length > 0);
    var addsSection = jobSections && B.sectionsToAdd(ROOT, jobType).length > 0;
    var laborDefaults = (newBid || addsSection) ? loadLaborDefaults() : null;
    // The company labor rate is read for EVERY bid, a saved one included: it is only APPLIED to a
    // new bid (the laborDefaults gate below), but "Default $X" under a rate needs it on any.
    var laborRate = loadLaborRate();
    // Lodging and Per Diem rates ride the same gate as the labor defaults: a NEW bid copies them
    // from Items & Assemblies -> Labor once; a saved bid keeps the rates it was saved with.
    var travelRates = newBid ? loadTravelRates() : null;
    // The Labor Calculator's per-line modes: same gate again -- a NEW bid fills its default labor
    // from them, a saved bid is never recomputed.
    var laborCalc = laborDefaults ? loadLaborCalc() : null;
    // The Fees + Textura default: same gate, a NEW bid's D77 starts at it.
    var feesDefault = newBid ? loadFeesDefault() : null;

    // THE CONDITION DEFAULTS, ON THE SAME TERMS AND WITH A STRICTER GATE. B.conditionsUnstated is
    // true only when NOTHING has ever been saved for this estimate, because Hanz's rule for this
    // feature is that changing a default must not change any estimate that already exists — an
    // estimator's saved answers are their work. Decided here, on the saved blob, for the reason
    // the labor block above gives: adopt() has already run migrateModel, which answers every
    // condition from freshModel, so M cannot be asked the question.
    //
    // Started here so it overlaps the library read instead of queueing behind it, and awaited
    // below. Null, not [], for "not asked" — [] is a real answer (nobody has overridden anything)
    // and the two must not be confused.
    var conditionDefaults = B.conditionsUnstated(savedEstimate)
      ? loadConditionDefaults() : null;

    $("proj-line").textContent = [state.project_name, state.city && state.state
      ? state.city + ", " + state.state : ""].filter(Boolean).join(" · ") || "Untitled project";

    try {
      var res = await Promise.all([
        api("/api/library/assemblies"),
        api("/api/library/items"),
      ]);
      var aj = await res[0].json();
      var ij = await res[1].json();
      ASMS = (aj && aj.assemblies) || [];
      ITEMS = (ij && ij.items) || [];
    } catch (err) {
      $("loading").textContent = "Couldn't load the item library, so there is nothing to price " +
        "against. " + (err.message || "") + " Reload to try again.";
      return;
    }

    if (!ASMS.length) {
      say("The item library has no assemblies yet, so a takeoff row has nothing to point at. " +
          "Add one under Items & Assemblies first.");
    }

    // The library's default labor lines, added BESIDE the four the model ships with, so a brand
    // new bid opens holding Travel and every line the estimator set up under Items & Assemblies.
    // Travel is built in and stays built in -- seedLibraryLabor adds, it never replaces.
    //
    // Nothing is written to the draft here. The seeded rows are persisted by the first edit like
    // every other part of this model, which is what makes removing a default from the library
    // later leave the bids already holding it alone: once saved, the rows are the BID's, and
    // laborUnstated has answered false ever since.
    LABOR_RATE = await laborRate;

    // EVERYTHING A NEW BID IS GIVEN, IN ONE CALL (bid-model.js seedNewSections; it was written out here until
    // Phase 10 and is the same steps in the same order). The library's answers are collected first and each is
    // null when it was not asked, which is the gate: a saved bid never asked, so nothing lands on it.
    //
    //   labor     the library's default labor lines beside Travel, which is built in and stays built in; the
    //             crew rows come from the Labor list like any other default, with the shipped set standing in
    //             only when the library cannot answer. Library rows with no rate of their own and Travel follow
    //             the company rate. Travel is a default like any other: if the library says this bid does not
    //             get it, the model says so, so a reload does not append the "missing" row back.
    //   travel    the two rates onto Lodging / Per Diem (both start OFF), and Fees + Textura at the Defaults
    //             tab's amount (nothing when none is set)
    //   conditions  the library's answers for joint filler, remove-existing and dye, and which cards the bid
    //             shows. THE CELL STILL WINS, so the seed lets a cell the intake wrote override it: a project
    //             that came through the beta intake has its answers in cell_values and no polish_estimate, and a
    //             company-wide default written over one would reach Kyle's workbook on the next save.
    //   takeoff   intake's SF boxes (System 1 -> polish_sf, System 2 -> polish_2_sf), one row each, and the
    //             library's default takeoff when the bid is new
    //   calculator  the Labor Calculator's per-line modes, AFTER the takeoff because a "from SF" line needs the
    //             job's SF
    // Nothing is written to the draft here: the first edit saves what was seeded, and from then on the rows are
    // the BID's, which is what makes a later library change leave the bids already holding them alone.
    var libraryLaborRows = laborDefaults ? B.withCrewFallback(await laborDefaults) : null;
    // A bid whose sections cannot be read is opened as it is, unseeded, with the reason on screen: refusing to
    // open it would lose the estimator's work.
    try {
      // AN EPOXY JOB'S BID IS AN EPOXY SECTION, with the Polish root marked off (B.sectionsForJob). Added before
      // the seeding below, so the new section is given the library's defaults like any other new one. The Markups
      // rules filed today are kept on it as text (B.activateSection), and no later edit to them moves this bid.
      // A job type that is Polish, or that Estimating Tool v2 cannot price yet, adds nothing.
      // A saved bid whose job type moved is brought to the new one here too (Epoxy to Combo turns the Polish root
      // back on, Combo to Polish marks the Epoxy section off, its rows kept), and is saved once because what the
      // draft holds is behind what the page shows. A Polish bid with no other sections adds and changes nothing.
      var sectionsBefore = JSON.stringify(ROOT);
      var carrierBefore = openingTab();
      if (jobSections) ROOT = B.sectionsForJob(ROOT, jobType, { rules: await loadMarkupRules() });
      var restructured = !newBid && JSON.stringify(ROOT) !== sectionsBefore;
      var carrierMoved = restructured && openingTab() !== carrierBefore;
      ROOT = B.seedNewSections(ROOT, {
      saved: savedEstimate,
      laborRows: libraryLaborRows,
      laborRate: LABOR_RATE,
      travelRates: travelRates ? await travelRates : null,
      feesDefault: feesDefault ? await feesDefault : null,
      conditionRows: conditionDefaults ? await conditionDefaults : null,
      cellValues: state.cell_values,
      split: T.isSplit(state),
      asms: ASMS, items: ITEMS, reserved: RESERVED_ITEM_IDS,
      sf: Object.fromEntries([[B.ROOT_TAB, [state.polish_sf, state.polish_2_sf]]].concat(
        jobSections && jobType !== "gyp" ? [["Epoxy", [state.system_1_sf, state.system_2_sf]]] : [],
        jobSections && jobType === "gyp" && gypTab() ? [[gypTab(), [state.gyp_soft_sf, state.gyp_hard_sf, state.gyp_corridor_sf]]] : [])),
      lf: Object.fromEntries(jobSections && jobType !== "gyp" ? [["Epoxy", [state.cove_1_lf, state.cove_2_lf]]] : []),
      // A Gyp section's takeoff is its three areas, one row each, the library's area assemblies.
      takeoffRows: function (entry, sfs) {
        return entry.role === "gyp" && G ? G.seedTakeoff(ASMS, sfs[0], sfs[1], sfs[2]) : null;
      },
      calcRows: laborCalc ? B.withCrewCalcFallback(await laborCalc) : null
      });
    } catch (err) {
      say("This bid's other sections cannot be read, so the library's defaults were not added: " + (err && err.message));
    }
    // A JOB TYPE SWITCHED IN THE SESSION CAN GIVE THE BID A NEW CARRIER (2026-10-20 audit): Polish saved at 190 miles and switched to
    // Epoxy on the intake step opens with the Epoxy section carrying the job's travel, and the seeding above gave that section a
    // blank Travel Labor row while the distance on file still says far and Lodging and Per Diem are on. The switch is the
    // estimator's own action, so the distance on file fills the new carrier's row by the same rule an answer does
    // (B.followDistance). A plain reopen is not a switch (sectionsForJob hands back the model it was given, so nothing
    // restructured and the carrier is the same) and fills nothing, and neither does a switch that keeps the carrier.
    // THE JOB'S ONE DRIVE IS PRICED ONCE, so the switch also settles the row that held it (B.followDistance, given the carrier the
    // job had): a new carrier with no row of its own takes the old one's (a Combo switched to Epoxy left the filled row on the Polish
    // root, which is off), the new carrier's row is filled on the crew's size (an Epoxy job switched to Polish holds the root's older
    // row), and a row the old carrier had filled and is still a base of the bid (Epoxy to Combo) is taken back. Given the WHOLE model.
    if (carrierMoved) B.followDistance(ROOT, carrierBefore);
    // The model was replaced above (the seeding hands back a new one), so the panels' view of it is made again.
    show(openingTab());
    followSf = B.takeoffSf(M.takeoff);
    if (restructured) saveSoon();
    // THE TAKEOFF TOTAL IS polish_sf, SO MAKE THE DRAFT SAY SO NOW. Two ways the draft can be
    // behind the model this page just opened with: (1) seeding filled rows in memory only, so
    // polish_sf held System 1 alone and computed_bid held nothing until the first edit; (2) the
    // live intake's beta-continue door saved a polish_sf typed over a takeoff that was already
    // measured. proposal-review reads polish_sf for the SF token. One debounced save, only when
    // the two actually differ, so a plain reopen writes nothing.
    //
    // (3) THE PRICE SNAPSHOT: intake's SF boxes stay editable on a measured takeoff, and a figure
    // typed there moves the takeoff rows and polish_sf together but cannot reprice (the library
    // lives on this page). So polish_sf agrees with the takeoff while computed_bid, which holds
    // the SF it was priced on, still says the old figure. A snapshot priced on another floor is
    // stale: save once so computed_bid and the stamped totals come from the model as it is.
    // Only when a snapshot exists and names an SF, so a draft that never had one still writes nothing.
    // EVERY SECTION THAT IS PART OF THE BID IS ASKED (B.snapshotBehind): the intake's boxes edit the takeoff of the
    // section that owns each quantity, so an Epoxy job's System 1 moves the Epoxy section and a Combo bid's Polish box
    // moves the root, and the snapshot of whichever it was is the one that is behind. The root's is polish_sf and
    // computed_bid.polish_sf; another section's is its priced_tabs entry.
    if (B.snapshotBehind(ROOT, state)) saveSoon();
    // A SEAL OPTION IS A TOTAL (B.optionOnlyTotalPatch): the Proposal step can leave one on Add / Deduct, which the panel has no
    // way to show or change. Put back here, before the first paint, so the panel and the proposal say the same. Writes nothing
    // for a bid that has no such sheet, so a plain reopen still writes nothing.
    var sealTotals = B.optionOnlyTotalPatch(ROOT, TW.getState());
    if (Object.keys(sealTotals).length) TW.setState(sealTotals);

    renderDatalist();
    $("loading").hidden = true;
    $("main").hidden = false;
    paintBid();
    // The step the URL names, decided BEFORE the first paint so the rail and the panel come up
    // agreeing. Setting `at` after paintRail would light one step and render another.
    at = openingStep(at);
    paintRail();
    renderPanel();

    // DISTANCE, AFTER THE PAINT AND NEVER AWAITED: a slow or dead map service costs the page
    // nothing. Only a NEW bid asks by itself (the same gate as the defaults above); a saved bid
    // keeps what it was saved with and offers the button. See lookupDistance.
    if (newBid && laborDefaults && !M.distance) lookupDistance(false);
  }

  init();
})();
