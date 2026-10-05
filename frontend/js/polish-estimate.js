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
// percentage and every step of the chain is transcribed in polish-bid-core.js, and
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
//     conditionLibrary and polish-bid-core.js's libraryLineWrites. Otherwise the downloaded
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

  var B = window.TWPolishBid;      // the markup chain, pinned to Kyle's Polish tab
  var L = window.TWLib;            // priceAssembly — the same maths the library page shows
  var S = window.TWPolishSandbox;  // never edit a live bid
  var $ = function (id) { return document.getElementById(id); };

  // The draft this page is working ON, and the model derived from it. Reassigned together by
  // adopt(), because the page can switch drafts mid-boot: opening a real bid here works on a test
  // copy instead, and rendering the copy with the real bid's numbers still in hand would be the
  // same silent mix-up in a different direction.
  var state = {};
  var M = null;

  // The library, loaded once at boot. Prices are recomputed from these on every keystroke rather
  // than stored on the row: an item's cost can move, and a stored line total would then disagree
  // with the same assembly priced on the library page.
  var ASMS = [];
  var ITEMS = [];

  var at = 0;

  function adopt(blob) {
    state = blob || {};
    M = B.migrateModel(state.polish_estimate);
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
    M.conditions = B.conditionsFromCells(M.conditions, state.cell_values);
    // BEFORE THE FIRST PAINT, not on the first edit. `changed()` is what normally keeps a derived
    // Guys figure current, and nothing calls it on load -- so without this a reopened draft shows
    // Travel's Guys box empty until somebody touches an unrelated field, and prices it at nothing
    // in the meantime.
    syncAutoGuys();
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
   *  broken-line warning, the per-unit hint -- keeps working without knowing which kind it got. */
  function rowPrice(row) {
    var r = row || {};
    if (r.item_id) return priceMaterialRow(r);
    var asm = asmById(r.assembly_id);
    if (!asm) return null;
    return priceAssemblyRow(asm, r, B.num(r.measurement));
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
  function priceAssemblyRow(asm, row, area) {
    var lc = (row && row.line_cov && typeof row.line_cov === "object") ? row.line_cov : null;
    var lines = (asm && asm.lines) || [];
    if (!lc) return L.priceAssembly(asm, ITEMS, area);
    var items = ITEMS, any = false;
    var swapped = lines.map(function (ln, j) {
      var cov = B.num(lc[j]);
      var id = ln && (ln.item_id || ln.item);
      if (!(cov > 0) || !id) return ln;
      var real = L.findItem(ITEMS, id);
      if (!real) return ln;
      any = true;
      var tmp = "__cov" + j;
      items = items.concat([Object.assign({}, real, { id: tmp, coverage: cov })]);
      return Object.assign({}, ln, { item_id: tmp, item: undefined });
    });
    if (!any) return L.priceAssembly(asm, ITEMS, area);
    return L.priceAssembly(Object.assign({}, asm, { lines: swapped }), items, area);
  }

  /** One material, priced as priceAssembly would have priced a one-line assembly containing it.
   *
   *  `broken_lines` follows library-core's own rule rather than inventing a second one: an
   *  unfilled row is work not started, not work gone wrong, so `no_item` is not a fault. Getting
   *  that wrong would put "1 line cannot price yet" under every row the moment it is added. */
  function priceMaterialRow(r) {
    var area = B.num(r.measurement);
    // THE OVERRIDE LIVES HERE, not inside priceLine: waste and roundup have no box on this row and
    // come from the material either way. A typed coverage prices against a ONE-ITEM SWAP of the
    // real item -- coverage replaced, everything else (cost, pack size) untouched -- so the item
    // in the library is never mutated. Blank r.coverage leaves `items` as ITEMS, so priceLine
    // falls back to the material's own coverage exactly as it does for every assembly line.
    var items = ITEMS;
    var cov = B.num(r.coverage);
    // TRUTHY, NOT !== null: B.num returns 0 for "", null and undefined alike (see
    // polish-bid-core.js), which is exactly how covHint/covPlaceholder already tell "nothing
    // typed" from a real figure. `!== null` would treat every blank row as coverage 0 and price it
    // as broken (no_coverage) the instant it's added, before anyone touches the box.
    if (cov) items = itemsWithCoverage(ITEMS, r.item_id, cov);
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
   *  reason (library-core.js's per_unit and polish-bid-core.js's per_sf are null rather than 0),
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
   *  coverage 1, waste 0, no roundup, $0.14) price to the cent what polish-bid-core.js's
   *  jointFillerCost/dyeCost did.
   *
   *  THE ROW IS NOT ALWAYS THERE. On a database the seed has not reached, or a row that cannot
   *  price (its cost or coverage blanked), this falls back to jointFillerCost/dyeCost -- the
   *  formulas the tool shipped with, untouched -- rather than pricing the line at $0 or breaking
   *  the page. `library` says which of the two answered.
   *
   *  THE IDS ARE LITERALS HERE, not read off CONDITION_CARDS: adopt() runs at parse time, above
   *  that declaration, and nothing this reaches may depend on a var assigned below it.
   *
   *  `qty` is what the card's Measurement shows: kits for joint filler, the polished area in SF
   *  for dye (the area is what dye is spread across, whatever its row's coverage says). */
  function condLine(key, area) {
    var id = key === "dye" ? "dye" : "joint-filler-kit";
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
   *  lines the bid does (polish-bid-core.js's libraryLineWrites). A key is LEFT OUT when its row
   *  is not in the library -- that writes nothing, so a database the seed has not reached keeps
   *  the template's cells -- and is null when the row is there but cannot price, which is when
   *  condLine falls back to the shipped formula and the cells get the shipped figures. The
   *  library loads after the first paint, so an early save with ITEMS still empty writes nothing
   *  either. */
  function conditionLibrary() {
    var out = {};
    [["dye", "dye"], ["joint_filler", "joint-filler-kit"]].forEach(function (pair) {
      if (!L.findItem(ITEMS, pair[1])) return;
      var ln = condLine(pair[0], 0).line;
      out[pair[0]] = ln ? { unit_price: ln.unit_price, coverage: ln.coverage,
                            waste_pct: ln.waste_pct, roundup: ln.roundup, buy_qty: ln.buy_qty }
                        : null;
    });
    return out;
  }

  function materialTotal() {
    var sum = 0;
    M.takeoff.forEach(function (r) {
      // OFF ROWS ARE SKIPPED HERE, in the raw sum, so the chain rounds only what the bid really
      // buys (D31 is ROUNDUP of the sum -- zeroing a row after that would drift the total).
      if (!B.rowOn(r)) return;
      var p = rowPrice(r);
      if (p) sum += p.total;
    });
    // Dye and Joint Filler are keyed on the polished area (Polish!E25/E29), not on a row's own
    // measurement. `area` is the SAME B.takeoffSf(M.takeoff) that bid() below uses for the
    // sheet's SF, so the Material total and the price-per-SF divisor can never disagree about
    // what "the area" is. Each prices off its reserved library row, or off the shipped formula
    // when that row is not there -- see condLine. Off means nothing, as it always has.
    var area = B.takeoffSf(M.takeoff);
    if (M.conditions.dye) sum += condLine("dye", area).cost;
    if (M.conditions.joint_filler) sum += condLine("joint_filler", area).cost;
    return sum;
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

  /** The whole bid, recomputed from the model. Cheap enough to call on every keystroke. */
  function bid() {
    return B.markupChain({
      material: materialTotal(),
      labor: B.laborTotal(M.labor),
      // Lodging + Per Diem: inside the markups (the sheet's D61), not labor.
      travel: B.travelCosts(M.travel, M.labor).total,
      contingency: M.contingency,
      fees: M.fees,
      conditions: M.conditions,
      sf: B.takeoffSf(M.takeoff),
      remodel_rate: remodelRate(),
    });
  }

  // ── saving ──────────────────────────────────────────────────────────────────
  var saveTimer = null;
  function saveSoon() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      var b = bid();
      M.totals = b;                        // a snapshot for the card and for reading later; the
                                           // page never prices FROM it
      TW.setState(Object.assign({}, TW.getState(), {
        polish_estimate: M,
        // THE FIVE CONDITION CELLS, AND ONLY THOSE. See the file header: this page does not write
        // the takeoff or the pricing cells, because it no longer prices through the workbook. It
        // has to write these, because they are not a rendering of the bid — they are the contract
        // this screen shares with the intake page, which reads them back on load and lets the CELL
        // win over the model (polish-intake.js adoptModel, "THE CELL WINS WHERE THERE IS ONE").
        //
        // That rule's safety condition is that every writer writes both places. This page became a
        // second writer the moment the Review step's switches shipped, and for one commit it wrote
        // only the model: flip Sales tax off here, follow either of this step's own links to
        // Intake — remodelSource()'s "pick a county", or the Labor step's "Change it on the intake
        // step" — and the old answer came back, then intake's next save made the revert permanent.
        //
        // THE DYE AND JOINT FILLER CELLS RIDE THE SAME WRITE: the rate (and, where the library
        // changed it, the quantity formula) the bid priced with -- conditionLibrary above.
        cell_values: B.conditionCellWrites(M.conditions, TW.getState().cell_values,
                                           conditionLibrary()),
        // proposal-review reads this for the SF token, and /api/generate's files-mode rebuild
        // gates on it.
        // b.sf is the area the bid PRICES (an OFF row is out of it). When nothing is on, keep the
        // MEASURED floor on file rather than 0: a 0 here unlocked intake's SF boxes and sent the
        // proposal an empty SF token because somebody flipped the only row's slider (F5).
        polish_sf: b.sf > 0 ? b.sf : B.measuredSf(M.takeoff),
        // polish_sf IS the takeoff total, so intake's System 2 box has nothing left to say: blank
        // it. Left stale it reseeded a deleted row -- empty the takeoff, reopen step 2, and
        // B.seedTakeoffSf read the old polish_2_sf as a fresh measurement.
        polish_2_sf: "",
        // Replaced, not merged — see the file header.
        computed_bid: {
          lump_sum: b.total,
          price_per_sf: b.per_sf,
          polish_sf: b.sf,
          // What the rest of the app reads: _bid_total in backend/drafts.py for the projects card,
          // and proposal-review for the lump sum and the two tax lines it itemizes.
          full_bid: {
            total_base_bid: b.total,
            sales_tax: b.sales_tax,
            remodel_tax: b.remodel_tax,
          },
        },
      }));
    }, 600);
  }

  // Same gap as the intake page's Fault 3: nothing here flushed its own 600ms debounce before
  // navigating away, and shared.js's pagehide net only flushes a timer THIS page armed. A takeoff
  // number typed and then left via the step nav inside that window was silently lost.
  window.addEventListener("pagehide", function () {
    if (!saveTimer) return;
    clearTimeout(saveTimer);
    saveTimer = null;
    var b = bid();
    M.totals = b;
    TW.setState(Object.assign({}, TW.getState(), {
      polish_estimate: M,
      polish_sf: b.sf,
      polish_2_sf: "",                   // see saveSoon: the takeoff total is polish_sf now
      computed_bid: {
        lump_sum: b.total,
        price_per_sf: b.per_sf,
        polish_sf: b.sf,
        full_bid: {
          total_base_bid: b.total,
          sales_tax: b.sales_tax,
          remodel_tax: b.remodel_tax,
        },
      },
    }));
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
    var manDays = B.travelManDays(M.labor);
    for (var i = 0; i < M.labor.length; i++) {
      var r = M.labor[i];
      if (r && r.unit === "hours" && r.guys_auto) r.guys = manDays;
    }
    // Lodging and Per Diem count the same man-days while they are on auto (nights = man-days, the
    // way backend/pricing.py counts them), written into the line for the reason above.
    if (M.travel) {
      B.TRAVEL_LINE_KEYS.forEach(function (k) {
        var l = M.travel[k];
        if (l && l.qty_auto !== false) l.qty = manDays;
      });
    }
  }

  /** Whether an hours-based labor row (Travel) renders dimmed: on a local job, untouched.
   *  `guys_auto` going false is what typing in Guys already does (the `data-k="guys"` handler
   *  below flips it); `filledIn(r.days)` is Hours holding a real number. Either one is the
   *  estimator saying "we need this anyway", so either one lifts the dim -- not just Hours, since
   *  Guys is the box somebody is looking at when they start typing.
   *
   *  ONE FUNCTION, used by both the first paint (laborCard) and the live repaint
   *  (repaintNumbers), so the two cannot disagree about a row that is being typed into right now. */
  function laborInert(r) {
    return !!(r && r.unit === "hours") && !!(M.conditions || {}).local &&
      !!r.guys_auto && !B.filledIn(r.days);
  }

  /** One place every edit funnels through, so nothing can change a value without the bid, the
   *  rail and the draft all catching up.
   *
   *  `rerender` false repaints the computed figures in place instead of rebuilding the panel:
   *  rebuilding mid-keystroke moves the caret out of the field being typed in. */
  function changed(rerender) {
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
    $("bid-total").textContent = b.total ? B.money(b.total) : "—";
    $("bid-psf").textContent = (b.per_sf == null ? "" : B.money2(b.per_sf) + " / SF")
      + (b.sf ? " · " + B.fmtSf(b.sf) + " SF" : "");
    var bits = [];
    if (b.material_total) bits.push("Material " + B.money(b.material_total));
    if (b.labor_total) bits.push("Labor " + B.money(b.labor_total));
    $("maths").innerHTML = bits.map(esc).join(' <i>+</i> ');
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
    M.labor.forEach(function (r) { if (B.laborCost(r) > 0) lab += 1; });
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
    return '<section class="sec"><div class="sec-h"><h2>' + esc(title) + '</h2><p>' +
      esc(blurb) + '</p></div><div class="sec-b">' + body + '</div>' +
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
    return itemById(key === "dye" ? "dye" : "joint-filler-kit");
  }

  /** An assembly row's lines that name a real material, each with the figure it will price with:
   *  [{ j, name, lib, typed }]. `j` is the line's position, the key row.line_cov is stored under. */
  function asmCovLines(row) {
    var asm = asmById((row || {}).assembly_id);
    var out = [];
    if (!asm) return out;
    var lc = (row.line_cov && typeof row.line_cov === "object") ? row.line_cov : {};
    (asm.lines || []).forEach(function (ln, j) {
      var id = ln && (ln.item_id || ln.item);
      var it = id ? itemById(id) : null;
      if (!it) return;
      out.push({ j: j, name: it.name || "Material", lib: B.num(it.coverage), typed: lc[j] });
    });
    return out;
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
   *  Material total through condLine (their reserved library rows, or polish-bid-core.js's
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
  var CONDITION_CARDS = [
    { key: "joint_filler", tag: "JOINT FILLER", label: "In the bid", cell: "Polish!E29",
      // THE RESERVED library_items ROW that prices this line -- see condLine, which falls back to
      // polish-bid-core.js's jointFillerCost when the row is not there.
      item_id: "joint-filler-kit",
      // THE LIVE NAME, not a string typed twice. An admin renaming the row on the Items tab has
      // to show up here too, or the card is a second copy of a fact that can go stale without
      // looking stale.
      material: function () {
        var item = L.findItem(ITEMS, "joint-filler-kit");
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
      cell: "Polish!F29", needs: "joint_filler",
      // ITS RESERVED library_items ROW, 2026-10-01 -- the Defaults tab lists it as a material and
      // the Items tab is where it is edited. NOTHING HERE PRICES OFF IT: the card has no `cost`,
      // so it stays the switch-and-sentence card and its answer still only reaches Polish!F29.
      // It is carried so RESERVED_ITEM_IDS below keeps it out of every takeoff-row picker.
      item_id: "remove-existing-jf",
      why: "Adds a fourth hand to the joint-filler line. Priced on the Labor step, where that " +
           "line is." },
    { key: "dye", tag: "DYE", label: "In the bid", cell: "Polish!E25",
      item_id: "dye",
      material: function () {
        var item = L.findItem(ITEMS, "dye");
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

  /** A row nobody has pointed at anything yet: the shape the add button pushes, and the shape the
   *  delete guard refills an emptied takeoff with. No assembly_id and no item_id, so rowPrice
   *  returns null and the cost box reads as unpriced rather than as free. */
  function newTakeoffRow() {
    return { kind: "new", pick_name: "", measurement: "", unit: "SF" };
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
        (p.broken_lines === 1 ? '' : 's') + ' in this assembly cannot price yet — check the ' +
        'cost and coverage of its items in the library.</p>';
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

      '<div class="f"><label>Unit</label><select data-tk="' + i + '" data-k="unit">' +
      UNITS.map(function (u) {
        return '<option value="' + u + '"' + (r.unit === u ? " selected" : "") + '>' + u +
          '</option>';
      }).join("") + '</select>' +
      '<p class="hint">SF or LF.</p></div>' +

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

      '</div>' + asmCoverageBlock(r, i, kind) + warn;
  }

  /** An ASSEMBLY row's coverage, one box per material line -- an assembly keeps coverage on its
   *  materials, so a row loaded from the defaults (or picked by hand) shows what each of its lines
   *  will price with, and the estimator can change any of them for THIS bid (row.line_cov). The
   *  same covLine text sits under each box. Empty string for every other kind of row. */
  function asmCoverageBlock(r, i, kind) {
    if (kind !== "asm") return "";
    var lines = asmCovLines(r);
    if (!lines.length) return "";
    return '<div class="tk-g asmcov" data-asmcov-for="' + i + '">' + lines.map(function (x) {
      return '<div class="f"><label>' + esc(x.name) + ' coverage</label>' +
        '<input class="n" data-asmcov="' + i + '" data-line="' + x.j + '" value="' +
        esc(nv(x.typed)) + '" placeholder="' + esc(x.lib ? String(x.lib) : "") + '">' +
        dfltWarnHtml('data-asmcovwarn="' + i + ':' + x.j + '"', covWarn(x.typed, x.lib)) +
        '<p class="hint" data-asmcovhint="' + i + ':' + x.j + '">' +
        esc(covLine(x.typed, x.lib)) + '</p></div>';
    }).join("") + '</div>';
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
    var html = '<button class="btn addline" data-add-row="1">' + icon("plus", 16) +
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
    html += CONDITION_CARDS.filter(function (c) {
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

    return shell("Material",
      "One row per assembly. The library prices it against the measurement you give it.", html);
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
    var auto = !!(hours && r.guys_auto);
    // Dimmed, not disabled, and not hidden: `.sw.inert`'s rule, for `.sw.inert`'s reason. A local
    // job that does need drive time must not send somebody back to the intake step to type it,
    // and a row that vanished would take an estimator's typed hours with it. Untouched only --
    // see laborInert -- so typing in either box beside it un-dims the card live.
    var inert = laborInert(r);
    // The way in and out of the derived Guys figure, gated on `hours` -- a crew row must never
    // get this button, because clicking it would run the same handler as Travel's and overwrite
    // that row's own Guys with the man-day sum. A bare <button>, no wrapper, so its own click
    // target is what data-lab-manual/-auto sits on.
    //
    // A SWITCH, NOT A BUTTON WHOSE WORDS FLIP. The old control read "Type my own", and
    // once pressed, "Back to auto" -- the label named the ACTION, so it described the
    // state you were leaving rather than the one you were in. A switch labels the STATE
    // and shows it: on means this row's Guys is typed, off means it is derived. One set of
    // words, always true, and it matches the switches the Review step already uses.
    //
    // STILL A <button>, deliberately. The `.mw-sw` conditions are <span role="switch">
    // with tabindex and no keydown handler, so Space and Enter do nothing on them. This
    // control is a real button today and reaching it by keyboard works; rendering it as a
    // span to match would quietly take that away. A <button role="switch"> looks the same
    // and keeps Space/Enter for free.
    //
    // The two data attributes are UNCHANGED and still point at the two existing handlers,
    // which are not symmetric: going manual also seeds the box with the derived figure and
    // moves the caret into it, while going auto only sets the flag. Only the markup moved.
    var toggle = !hours ? "" : (auto
    //
    // NO aria-label. The visible words ARE the accessible name, and that is the point: an
    // aria-label here would override them, and the old pair ("Type my own Guys figure" /
    // "Back to the automatic Guys figure") flipped with the state. Keeping them would have
    // left a screen-reader user hearing the next ACTION while the screen showed the state,
    // which is the exact confusion this change removes for everybody else. role="switch"
    // plus aria-checked already announces on/off.
      ? '<button type="button" class="mw-sw labsw" role="switch" aria-checked="false"'
        + ' data-lab-manual="' + i + '">'
        + '<span class="track"></span>Type my own</button>'
      : '<button type="button" class="mw-sw labsw on" role="switch" aria-checked="true"'
        + ' data-lab-auto="' + i + '">'
        + '<span class="track"></span>Type my own</button>');
    var on = B.rowOn(r);
    return '<div class="tk lab' + ((inert || !on) ? " inert" : "") + (on ? "" : " off") +
      '" data-lab-card="' + i +
      '"><div class="tk-h">' +
      '<input class="labname" data-lab="' + i + '" data-k="label" value="' + esc(nv(r.label)) +
      '" placeholder="Task" aria-label="Task name">' + toggle +
      B.sliderHtml(on, 'data-on-lab="' + i + '"', "Included", "Off keeps this line here, grayed, " +
        "and adds nothing to the price") +
      '<span class="tk-sub calc" data-lcost-for="' + i + '">' +
      esc(moneyAuto(B.laborCost(r))) + '</span>' +
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
      '<p class="hint">' + (auto ? 'Man-days from the tasks above.'
        : (hours ? 'Man-days on the road.' : 'How many on it.')) + '</p></div>' +

      '<div class="f"><label>' + (hours ? "Hours" : "Days") + '</label>' +
      '<input class="n" data-lab="' + i + '" data-k="days" value="' + esc(nv(r.days)) + '">' +
      dfltWarnHtml('data-calcwarn="' + i + ':days"', calcDefaultText(r, "days")) +
      '<p class="hint">' + (hours ? "Drive time, each way counted." : "How long it takes.") +
      '</p></div>' +

      '<div class="f"><label>Rate</label>' +
      '<span class="mny">$<input class="n" data-lab="' + i + '" data-k="rate" value="' +
      esc(nv(r.rate)) + '"></span>' +
      dfltWarnHtml('data-ratedflt-for="' + i + '"', rateDefaultText(r)) +
      '<p class="hint">Per hour.</p></div>' +

      '<div class="f"><label>Cost</label>' +
      '<div class="costbox' + (B.laborCost(r) > 0 ? "" : " empty") + '">' +
      esc(moneyAuto(B.laborCost(r))) + '</div>' +
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

      '</div>' + (hours
        // Rendered unconditionally on hours rows -- CSS (`.lab:not(.inert) .inertline`) decides
        // whether it shows, so the card's class is the one source of truth for both the dimming
        // and the caption, and the two cannot drift apart on a live repaint.
        ? '<p class="inertline">This job is marked local, so no travel is expected — type here ' +
          'anyway if it needs drive time.</p>' +
          '<p class="hint trvnote">Drive time is expected at 70 miles or more from the office. ' +
          'Under 70 miles this line stays gray.</p>'
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
    var cost = B.travelLineCost(l, M.labor);
    var mode = auto
      ? '<button type="button" class="mw-sw labsw" role="switch" aria-checked="false"' +
        ' data-trv-manual="' + key + '"><span class="track"></span>Type my own</button>'
      : '<button type="button" class="mw-sw labsw on" role="switch" aria-checked="true"' +
        ' data-trv-auto="' + key + '"><span class="track"></span>Type my own</button>';
    return '<div class="tk trv' + ((inert || !on) ? " inert" : "") + (on ? "" : " off") +
      '" data-trv-card="' + key + '"><div class="tk-h">' +
      '<span class="labname static">' + esc(l.label || (isNight ? "Lodging" : "Per Diem")) + '</span>' +
      mode +
      B.sliderHtml(on, 'data-on-trv="' + key + '"', "Included", "Off keeps this line here, " +
        "grayed, and adds nothing to the price") +
      '<span class="tk-sub calc" data-trvcost-for="' + key + '">' + esc(moneyAuto(cost)) + '</span>' +
      '</div><div class="tk-g lab-g trv-g">' +
      '<div class="f"><label>' + unitWord + '</label>' +
      '<input class="n" data-trv="' + key + '" data-k="qty" value="' + esc(nv(l.qty)) + '"' +
      (auto ? ' data-auto="1"' : '') + '>' +
      '<p class="hint">' + (auto ? "Man-days from the tasks above." : "Typed by you.") + '</p></div>' +
      '<div class="f"><label>Rate</label>' +
      '<span class="mny">$<input class="n" data-trv="' + key + '" data-k="rate" value="' +
      esc(nv(l.rate)) + '"></span>' +
      '<p class="hint">' + (isNight ? "Per night." : "Per day.") + ' Set under Items &amp; ' +
      'Assemblies, Labor Calculator.</p></div>' +
      '<div class="f"><label>Cost</label>' +
      '<div class="costbox' + (cost > 0 ? "" : " empty") + '">' + esc(moneyAuto(cost)) + '</div>' +
      '<p class="hint">' + unitWord.toLowerCase() + ' × rate</p></div>' +
      '</div><p class="hint trvnote">' + (isNight
        ? "Overnight stays are expected at 70 miles or more from the office. Under 70 miles " +
          "this line stays gray."
        : "Meals while the guys are away, expected at 70 miles or more from the office. Under " +
          "70 miles this line stays gray.") + '</p></div>';
  }

  // ── distance decides "local" ────────────────────────────────────────────────
  // The intake's "Local job" switch is gone (Kyle 9/18; Hanz, 2026-10-05). The server works the
  // driving miles from the Olathe office to the job address out (POST /api/distance, Google Routes)
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
    var model = M;
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
          ? AbortSignal.timeout(10000) : undefined
      });
      var j = await res.json();
      miles = B.milesOrNull(j && j.miles);
      reason = (j && j.reason) || "error";
    } catch (e) { miles = null; }
    distBusy = false;
    // The page can have moved to another draft, or the estimator can have typed miles while the
    // answer was on its way. Theirs wins; this answer is dropped.
    if (model !== M || (!force && M.distance && M.distance.source === "typed")) { paintDistance(); return; }
    if (miles === null) { distReason = reason; paintDistance(); return; }
    B.applyDistance(M, { miles: miles, source: "google", key: key });
    changed(false);
    paintDistance();
  }

  function laborPanel() {
    // Travel Labor is its own block, below a dividing line, with Lodging and Per Diem. Every other
    // task keeps its place above it. `i` stays the row's real index in M.labor -- the handlers
    // splice and edit by position.
    if (!M.travel) M.travel = B.normalizeTravel(null);
    var html = "";
    var travelRows = "";
    M.labor.forEach(function (r, i) {
      if ((r || {}).id === "travel") travelRows += laborCard(r, i);
      else html += laborCard(r, i);
    });

    // Same control as the takeoff step's, below the list rather than above it: this one adds a
    // row you then name yourself, so there is nothing to search and nothing to scroll back to.
    html += '<button class="btn addline below" data-add-lab="1">' + icon("plus", 16)
      + ' Add a labor line</button>';
    html += '<p class="cap">Labor total <b data-labor-total>' +
      esc(moneyAuto(B.laborTotal(M.labor))) + '</b>.</p>';

    html += '<div class="trvsep" role="separator"><span>Travel</span></div>' +
      '<p class="cap">Travel is expected when the job is 70 miles or more from the office. Under ' +
      '70 miles all three lines below stay gray until you switch one on.</p>';
    html += distanceBlock();
    html += travelRows + travelCard("lodging") + travelCard("per_diem");
    html += '<p class="cap">Lodging and Per Diem total <b data-travel-total>' +
      esc(moneyAuto(B.travelCosts(M.travel, M.labor).total)) + '</b>, added before the markups.</p>';

    var pw = !!(M.conditions || {}).prevailing_wage;
    html += '<p class="cap">Prevailing wage is <b>' + (pw ? "on" : "off") + '</b>' +
      (pw ? ", so a 5% escalation is added on the review step" : "") +
      '. Change it on <a href="' + esc(TW.withDraft("/polish-intake.html")) +
      '">the intake step</a>.</p>';

    return shell("Labor",
      "Guys × days × rate, at " + B.HOURS_PER_DAY + " hours a day. Travel is priced per hour.",
      html);
  }

  // ── review ──────────────────────────────────────────────────────────────────
  function card(title, step, amt, inner) {
    return '<div class="rev"><div class="rev-h">' + esc(title) +
      ' <button data-go="' + step + '">Edit</button>' +
      (amt ? '<span class="amt">' + esc(amt) + '</span>' : '') + '</div>' + inner + '</div>';
  }

  /** rows: [label, middle, money, rowClass]. `money` may be pre-built HTML for a keyed cell.
   *
   *  `label` is escaped by default -- most of it is user data (an assembly name, a labor line's
   *  own typed label) and has to be. The one row that needs to embed a real control (Labor
   *  escalation's prevailing-wage switch) passes `{ raw: "<...>" }` instead of a bare string, so
   *  that one label opts out explicitly rather than this function guessing "looks like HTML" on
   *  a string that could just as easily be a customer's literal `<` in an assembly name. */
  function revTable(rows) {
    return '<table class="rev-t"><tbody>' + rows.map(function (r) {
      var label = (r[0] && typeof r[0] === "object" && "raw" in r[0]) ? r[0].raw : esc(r[0]);
      return '<tr' + (r[3] ? ' class="' + r[3] + '"' : '') + '><td>' + label +
        '</td><td class="r">' + esc(r[1] == null ? "" : r[1]) + '</td><td class="r">' +
        (r[2] == null ? "" : r[2]) + '</td></tr>';
    }).join("") + '</tbody></table>';
  }

  /** An amount the chain computes, keyed so repaintNumbers can refresh it without a rebuild. */
  function mkAmt(b, key) {
    return '<span data-mk="' + key + '">' + esc(moneyAuto(b[key])) + '</span>';
  }

  function reviewPanel() {
    var b = bid();
    var blk = B.blockers(M);
    var html = "";
    if (blk.length) {
      html += '<div class="blockers"><b>Not finished yet.</b><ul>' +
        blk.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + '</ul></div>';
    }

    // Takeoff and material
    var tkRows = [];
    M.takeoff.forEach(function (r) {
      // A MATERIAL ROW HAS A NAME TOO, and it is in a different field. Reading assembly_name only
      // printed a fully priced material row as "(no assembly picked)" beside its own cost, which
      // reads as a fault in a row that has nothing wrong with it.
      if (!r.assembly_id && !r.item_id && !B.num(r.measurement)) return;
      if (!B.rowOn(r)) return;               // switched off: out of the bid, so out of the list
      tkRows.push([r.assembly_name || r.item_name || "(nothing picked yet)", measureText(r),
                   esc(rowCost(r).text)]);
    });
    if (!tkRows.length) tkRows.push(["Nothing measured yet", "", ""]);
    tkRows.push(["Material Subtotal", "", mkAmt(b, "material")]);
    tkRows.push(["Shipping", B.pct(B.RATES.SHIPPING), mkAmt(b, "shipping")]);
    tkRows.push(["Material Total", "", mkAmt(b, "material_total"), "tot"]);
    html += card("Takeoff and Material", 0, moneyAuto(b.material_total), revTable(tkRows));

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
    M.labor.forEach(function (r) {
      if (!B.rowOn(r)) return;               // switched off: out of the bid, so out of the list
      var cost = B.laborCost(r);
      if (!cost && (r || {}).id !== "travel") return;
      labRows.push([r.label || "Labor line",
                    B.num(r.guys) + " × " + B.num(r.days) + " × " + B.money2(r.rate),
                    esc(moneyAuto(cost))]);
    });
    if (!labRows.length) labRows.push(["No labor entered yet", "", ""]);
    labRows.push(["Labor Subtotal", "", mkAmt(b, "labor")]);
    labRows.push([{ raw: condSwitch("prevailing_wage", "Labor escalation") },
      b.escalation ? B.pct(B.RATES.ESCALATION) : "", mkAmt(b, "escalation")]);
    labRows.push(["Labor burden", B.pct(B.RATES.BURDEN), mkAmt(b, "burden")]);
    labRows.push(["Labor Total", "", mkAmt(b, "labor_total"), "tot"]);
    html += card("Labor", 1, moneyAuto(b.labor_total), revTable(labRows));

    // Lodging and Per Diem: listed only while switched on (an off line is out of the bid, so out of
    // the list), and its own card because it is inside the markups but is not labor.
    var trvRows = [];
    B.TRAVEL_LINE_KEYS.forEach(function (k) {
      var tl = (M.travel || {})[k];
      if (!tl || !tl.enabled) return;
      trvRows.push([tl.label, B.num(B.travelQty(tl, M.labor)) + " × " + B.money2(tl.rate),
                    esc(moneyAuto(B.travelLineCost(tl, M.labor)))]);
    });
    if (trvRows.length) {
      trvRows.push(["Travel Subtotal", "", mkAmt(b, "travel"), "tot"]);
      html += card("Lodging and Per Diem", 1, moneyAuto(b.travel), revTable(trvRows));
    }

    html += '<div class="rev">' + markupTable(b) + '</div>';
    return shell("Review the bid",
      "Costs, then the markup Kyle's sheet applies, then the lump sum.", html);
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

  /** Rows 64-82 of the Polish tab, in the same order, so an estimator who knows Kyle's sheet can
   *  read down it and recognise every line. Percentages are the sheet's own and not editable —
   *  the workbook locks these cells in the generated download for the same reason. Contingency is
   *  the one exception, because the sheet leaves D71 open too. */
  function markupTable(b) {
    var r = "";
    var row = function (label, pctHtml, key, cls) {
      return '<tr' + (cls ? ' class="' + cls + '"' : '') + '><td>' + label + '</td>' +
        '<td class="pct">' + pctHtml + '</td>' +
        '<td class="amt" data-mk="' + key + '">' + esc(moneyAuto(b[key])) + '</td></tr>';
    };
    var keyedPct = function (key) {
      return '<span data-mkpct="' + key + '">' + esc(B.pct(b[key])) + '</span>';
    };

    r += '<tr class="sub"><td>Subtotal</td><td class="pct"></td>' +
      '<td class="amt" data-mk="sub_total">' + esc(moneyAuto(b.sub_total)) + '</td></tr>';

    r += '<tr class="band"><td colspan="3">Markup</td></tr>';
    r += row("GP <span class=\"note\">before the lines below</span>", keyedPct("gp_pct"), "gp");
    // NO HARD BID ROW. Hanz, 2026-09-22: "remove all hard bids from the polish intake form. And
    // also on the markups" -- the switch and its row came out with the condition itself; see
    // polish-bid-core.js's note on bid() for where the arithmetic went.
    r += row("Superintendent &amp; PTO", esc(B.pct(B.RATES.SUPER_PTO)), "super_pto");
    r += row("Soft costs", esc(B.pct(B.RATES.SOFT_COSTS)), "soft_costs");
    r += '<tr><td>Contingency <span class="note">yours to set</span></td>' +
      '<td class="pct"></td><td class="amt"><input data-contingency value="' +
      esc(nv(M.contingency)) + '" inputmode="decimal"></td></tr>';

    r += '<tr class="band"><td colspan="3">Taxes &amp; fees</td></tr>';
    r += row(condSwitch("taxable", "Sales tax") + ' <span class="note">on materials</span>',
      keyedPct("sales_tax_pct"), "sales_tax", b.sales_tax_pct ? "" : "off");
    r += row(condSwitch("remodel_tax", "Remodel tax") + remodelSource(),
      keyedPct("remodel_pct"), "remodel_tax", b.remodel_pct ? "" : "off");
    r += row("Total taxes", "", "taxes", "tot");
    // Typed, like Contingency above -- the sheet leaves B77 and C77 open and this is the line
    // an estimator fills them in on. Marked up by everything beneath it, which is D77's own
    // place in Kyle's column rather than a decision made here; see the note in markupChain.
    r += '<tr' + (b.fees ? '' : ' class="off"') + '><td>Fees + Textura ' +
      '<span class="note">yours to set</span></td><td class="pct"></td>' +
      '<td class="amt"><input data-fees value="' + esc(nv(M.fees)) +
      '" inputmode="decimal"></td></tr>';
    r += row(condSwitch("bond", "Bond") +
      ' <span class="note">the sheet ships this at 0% either way</span>',
      keyedPct("bond_pct"), "bond", b.bond ? "" : "off");
    r += row("Total fees + bond", "", "fees_and_bond", "tot");

    r += '<tr class="grand"><td>Total lump sum</td>' +
      '<td class="pct" data-mk-persf>' + esc(perSfText(b)) + '</td>' +
      '<td class="amt" data-mk="total">' + esc(moneyAuto(b.total)) + '</td></tr>';

    return '<table class="mk"><tbody>' + r + '</tbody></table>';
  }

  function perSfText(b) {
    if (!b.sf) return "";
    return B.money2(b.per_sf) + " / SF";
  }

  var PANELS = [takeoffPanel, laborPanel, reviewPanel];

  function renderPanel() { $("panels").innerHTML = PANELS[at](); }

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

  /** Refresh every computed figure in place, without rebuilding the panel.
   *
   *  Keyed by data-attribute, never by column position. The library page addressed its computed
   *  cells by column index and shipped Quantity and Cost written into each other's columns; the
   *  test agreed with the constants and missed it entirely. An attribute cannot be off by one. */
  function repaintNumbers() {
    var b = bid();

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
    document.querySelectorAll("[data-ratedflt-for]").forEach(function (el) {
      var row = M.labor[parseInt(el.getAttribute("data-ratedflt-for"), 10)];
      paintDfltWarn(el, rateDefaultText(row));
    });
    document.querySelectorAll("[data-calcwarn]").forEach(function (el) {
      var parts = el.getAttribute("data-calcwarn").split(":");
      paintDfltWarn(el, calcDefaultText(M.labor[parseInt(parts[0], 10)], parts[1]));
    });
    document.querySelectorAll("[data-lcost-for]").forEach(function (el) {
      el.textContent = moneyAuto(B.laborCost(M.labor[parseInt(
        el.getAttribute("data-lcost-for"), 10)]));
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
    document.querySelectorAll('[data-lab][data-k="guys"][data-auto]').forEach(function (el) {
      var r = M.labor[parseInt(el.getAttribute("data-lab"), 10)];
      if (!r) return;
      var v = r.guys == null ? "" : String(r.guys);
      if (el.value !== v) el.value = v;
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
    if (M.travel) {
      document.querySelectorAll("[data-trvcost-for]").forEach(function (el) {
        el.textContent = moneyAuto(B.travelLineCost(M.travel[el.getAttribute("data-trvcost-for")], M.labor));
      });
      document.querySelectorAll('[data-trv][data-k="qty"][data-auto]').forEach(function (el) {
        var l = M.travel[el.getAttribute("data-trv")];
        if (!l) return;
        var v = l.qty == null ? "" : String(l.qty);
        if (el.value !== v) el.value = v;
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
    document.querySelectorAll("[data-asmcovwarn]").forEach(function (el) {
      var parts = el.getAttribute("data-asmcovwarn").split(":");
      var row = M.takeoff[parseInt(parts[0], 10)];
      var hit = asmCovLines(row).filter(function (x) { return String(x.j) === parts[1]; })[0];
      if (hit) paintDfltWarn(el, covWarn(hit.typed, hit.lib));
    });
    // The Coverage hints under every takeoff box: typing takes `changed(false)`, which repaints in
    // place, so "Library default: N" has to appear here rather than wait for a rebuild.
    document.querySelectorAll("[data-covhint-for]").forEach(function (el) {
      var hi = parseInt(el.getAttribute("data-covhint-for"), 10);
      el.textContent = covHint(M.takeoff[hi]);
    });
    document.querySelectorAll("[data-asmcovhint]").forEach(function (el) {
      var parts = el.getAttribute("data-asmcovhint").split(":");
      var row = M.takeoff[parseInt(parts[0], 10)];
      var hit = asmCovLines(row).filter(function (x) { return String(x.j) === parts[1]; })[0];
      if (hit) el.textContent = covLine(hit.typed, hit.lib);
    });

    var one = function (sel, txt) {
      var el = document.querySelector(sel);
      if (el) el.textContent = txt;
    };
    one("[data-mat-total]", moneyAuto(materialTotal()));
    one("[data-area-total]", B.fmtSf(B.takeoffSf(M.takeoff)) + " SF");
    one("[data-labor-total]", moneyAuto(B.laborTotal(M.labor)));
    one("[data-travel-total]", moneyAuto(B.travelCosts(M.travel, M.labor).total));
    one("[data-mk-persf]", perSfText(b));

    document.querySelectorAll("[data-mk]").forEach(function (el) {
      el.textContent = moneyAuto(b[el.getAttribute("data-mk")]);
    });
    // The GP band and the two tax rates move with the sub-total and the toggles, so the percentage
    // column is as computed as the money column is.
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
  // THE COMPANY LABOR RATE (Markups -> Global). A new line starts from it rather than blank, so the
  // estimator is never typing a rate Treadwell has already decided. The shipped $33 stands until
  // init() has read the real one, and for good if that read fails.
  var LABOR_RATE = B.SHIPPED_LABOR_RATE;
  function newLaborRow() {
    laborSeq += 1;
    return { id: "u_" + Date.now() + "_" + laborSeq, label: "", guys: "", days: "", rate: LABOR_RATE };
  }

  /** The warning under a labor rate box: the shared "Default value: $X.XX" when this row's rate is
   *  not the company rate (a blank one included), "" (hidden) while the two agree. */
  function rateDefaultText(row) {
    // A line the Labor Calculator filled carries its own default rate (the line's, else the
    // company's at the time) -- warn against THAT, so an untouched calculator rate never shows
    // "Default value" and a changed one names the number it started from.
    var d = (row || {}).calc_default;
    var dflt = d ? B.num(d.rate) : LABOR_RATE;
    return dfltWarnText(B.num((row || {}).rate) !== dflt, B.money2(dflt));
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

  // Space and Enter work the on/off slider from the keyboard, as they would a button.
  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (!t || !t.closest || (e.key !== " " && e.key !== "Enter")) return;
    var sw = t.closest("[data-on-tk]") || t.closest("[data-on-lab]") || t.closest("[data-on-trv]");
    if (!sw) return;
    e.preventDefault();
    sw.click();
  });

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;

    var go_ = t.closest("[data-go]");
    if (go_) { e.preventDefault(); go(parseInt(go_.getAttribute("data-go"), 10)); return; }

    // The explicit lookup: replaces a typed figure too, because the estimator asked.
    if (t.closest("[data-dist-lookup]")) { lookupDistance(true); return; }

    // THE CARET GOES WITH THE ROW. The button is at the top of the list and the row lands at the
    // bottom of it, so without this the estimator presses Add and nothing they can see happens.
    // focus() scrolls the box into view as a side effect, which is the whole trick.
    if (t.closest("[data-add-row]")) {
      M.takeoff.push(newTakeoffRow());
      changed(true);
      refocus('[data-tk="' + (M.takeoff.length - 1) + '"][data-k="pick"]');
      return;
    }
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
    var dr = t.closest("[data-del-row]");
    if (dr) {
      M.takeoff.splice(parseInt(dr.getAttribute("data-del-row"), 10), 1);
      if (!M.takeoff.length) M.takeoff.push(newTakeoffRow());
      changed(true);
      return;
    }
    if (t.closest("[data-add-lab]")) {
      M.labor.push(newLaborRow());
      changed(true);
      return;
    }
    // The two ways across the auto/manual line, for somebody who would rather press a thing than
    // discover that typing works. Going back to auto drops the typed figure on purpose -- that is
    // what "back to auto" means, and the crew's man-days are one keystroke from being right again.
    var manual = t.closest("[data-lab-manual]");
    if (manual) {
      var mi = parseInt(manual.getAttribute("data-lab-manual"), 10);
      if (M.labor[mi]) {
        M.labor[mi].guys_auto = false;
        M.labor[mi].guys = B.travelManDays(M.labor);
      }
      changed(true);
      refocus('[data-lab="' + mi + '"][data-k="guys"]');
      return;
    }
    var auto = t.closest("[data-lab-auto]");
    if (auto) {
      var ai = parseInt(auto.getAttribute("data-lab-auto"), 10);
      if (M.labor[ai]) M.labor[ai].guys_auto = true;
      changed(true);
      return;
    }
    var dl = t.closest("[data-del-lab]");
    if (dl) {
      M.labor.splice(parseInt(dl.getAttribute("data-del-lab"), 10), 1);
      if (!M.labor.length) M.labor.push(newLaborRow());
      changed(true);
      return;
    }
    // Review's own toggles -- same idea as polish-intake.js's onClick/toggleCondition, just
    // flipping the one flag in place rather than routing through that page's carry-four/legacy-
    // cell bookkeeping, none of which any of these five keys need.
    // THE ON/OFF SLIDER on a takeoff row and on a labor row (the condition cards' own switch is the
    // `data-cond` one below). Off is an explicit `enabled:false`; back on DELETES the key, so a row
    // that has been flipped back is indistinguishable from one never touched.
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
    // choice the estimator made. The two mode buttons are Travel's "Type my own" switch again:
    // going manual seeds the box with the crew's man-days and puts the caret in it.
    var onTrv = t.closest("[data-on-trv]");
    if (onTrv) {
      var tl = M.travel && M.travel[onTrv.getAttribute("data-on-trv")];
      if (tl) { tl.enabled = !tl.enabled; tl.hand = true; }
      changed(true);
      return;
    }
    var trvManual = t.closest("[data-trv-manual]");
    if (trvManual) {
      var mk = trvManual.getAttribute("data-trv-manual");
      if (M.travel && M.travel[mk]) {
        M.travel[mk].qty_auto = false;
        M.travel[mk].qty = B.travelManDays(M.labor);
      }
      changed(true);
      refocus('[data-trv="' + mk + '"][data-k="qty"]');
      return;
    }
    var trvAuto = t.closest("[data-trv-auto]");
    if (trvAuto) {
      var ak = trvAuto.getAttribute("data-trv-auto");
      if (M.travel && M.travel[ak]) M.travel[ak].qty_auto = true;
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
      changed(true);
      return;
    }
  });

  /** Point a takeoff row at an assembly, by the name that was typed or picked. */
  function setAssembly(i, text) {
    var row = M.takeoff[i];
    if (!row) return false;
    var before = row.assembly_id || "";
    row.assembly_name = text;
    var asm = assemblyByName(text);
    row.assembly_id = asm ? asm.id : "";
    // A DIFFERENT ASSEMBLY IS DIFFERENT LINES: coverage typed against the old one's lines would
    // land on the wrong materials, so it goes with the old pick.
    if (row.assembly_id !== before) delete row.line_cov;
    // Adopt the assembly's own unit only when the pick actually CHANGES. Doing it on every
    // keystroke would snap a row whose unit the estimator switched by hand back to the library's.
    if (asm && row.assembly_id !== before) {
      var u = String(asm.unit == null ? "" : asm.unit).toUpperCase();
      if (u === "SF" || u === "LF") {
        row.unit = u;
        var sel = document.querySelector('select[data-tk="' + i + '"][data-k="unit"]');
        if (sel) sel.value = u;        // in place: a rebuild here would take the caret with it
      }
    }
    return !!asm;
  }

  /** setAssembly's opposite number, and deliberately simpler than it.
   *
   *  NO UNIT ADOPTION. An assembly declares the unit it is measured in, so picking one can
   *  legitimately switch the row to LF. An item's `unit` is the unit it is BOUGHT in -- gallons,
   *  kits, pails -- which has nothing to do with how the floor is measured. Copying it onto the
   *  row would set a 12,000 SF area to "gallons" and price against it.
   *
   *  COVERAGE IS LEFT ALONE on a pick, for the reason covPlaceholder gives: the item's default is
   *  shown as a placeholder and used when the box is empty, so writing it INTO the box would turn
   *  a library default into something indistinguishable from a figure somebody typed for this
   *  job. */
  function setMaterial(i, text) {
    var row = M.takeoff[i];
    if (!row) return false;
    row.item_name = text;
    // Through itemByName, not a loop of its own: that is the one name lookup that refuses Dye and
    // the joint filler kit, so a row typed as "Dye, per coat" cannot become a second dye charge.
    var hit = itemByName(text);
    row.item_id = hit ? hit.id : "";
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

    if (el.matches("[data-contingency]")) {
      M.contingency = el.value;
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
    // once (>= 70 brings the travel lines on, under 70 grays them; a line flipped by hand stays
    // as flipped); clearing the box goes back to "unknown" and asks the server again. The panel is
    // rebuilt so the three cards repaint, with the caret carried (the pattern the Travel boxes
    // below use) -- a half-typed "7" before "70" is an ordinary moment, not an error.
    if (el.matches("[data-dist-miles]")) {
      var rawMiles = String(el.value);
      var typedMiles = B.milesOrNull(el.value);
      if (typedMiles !== null) {
        B.applyDistance(M, { miles: typedMiles, source: "typed", key: addressKey() });
        changed(true);
        refocus("[data-dist-miles]", rawMiles);
      } else if (String(el.value).trim() === "") {
        B.clearDistance(M);
        changed(true);
        refocus("[data-dist-miles]");
        lookupDistance(false);
      }
      return;
    }
    if (!el.matches("input")) return;
    var k = el.getAttribute("data-k");

    // THIS BID'S COVERAGE for Joint Filler / Dye (M.cond_cov) and for one line of an assembly row
    // (row.line_cov). Both take `changed(false)`: reprice and repaint in place, never a rebuild,
    // so the caret stays in the box being typed in.
    var cc = el.getAttribute("data-condcov");
    if (cc !== null) {
      if (!M.cond_cov || typeof M.cond_cov !== "object") M.cond_cov = {};
      M.cond_cov[cc] = el.value;
      changed(false);
      return;
    }
    var ac = el.getAttribute("data-asmcov");
    if (ac !== null) {
      var arow = M.takeoff[parseInt(ac, 10)];
      if (arow) {
        if (!arow.line_cov || typeof arow.line_cov !== "object") arow.line_cov = {};
        arow.line_cov[el.getAttribute("data-line")] = el.value;
      }
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
        // A new assembly brings its own lines, and the coverage boxes under the card are one per
        // line -- so the card is redrawn then too, not only when the kind moved.
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
        // TYPING IN THE AUTO BOX IS HOW YOU LEAVE AUTO. Travel's Guys follows the crew's man-days
        // until somebody disagrees with it, and the disagreement is the keystroke -- asking them
        // to find a control first, to then be allowed to type the number they already have in
        // mind, is a worse trade than the one line it takes to notice. `changed(true)` so the
        // hint under the box repaints from "From the crew above" to the way back.
        if (k === "guys" && M.labor[j].guys_auto) {
          M.labor[j].guys_auto = false;
          M.labor[j][k] = el.value;
          changed(true);
          refocus('[data-lab="' + j + '"][data-k="guys"]');
          return;
        }
        M.labor[j][k] = el.value;
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
    // HOURS A DAY on a calculator-filled labor line is a <select>, which the "input" handler above
    // skips (it only takes <input>); it reprices here, the way the takeoff unit select does.
    var hl = el.getAttribute("data-lab");
    if (hl !== null && el.getAttribute("data-k") === "hours_per_day") {
      if (M.labor[parseInt(hl, 10)]) M.labor[parseInt(hl, 10)].hours_per_day = el.value;
      changed(false);
      return;
    }
    var ti = el.getAttribute("data-tk");
    if (ti === null) return;
    var i = parseInt(ti, 10);
    var k = el.getAttribute("data-k");
    if (k === "unit") {
      if (M.takeoff[i]) M.takeoff[i].unit = el.value;
      changed(false);
      return;
    }
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

  /** The Lodging and Per Diem rates (Markups -> Global), `{lodging, per_diem}` with null for any
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
    var laborDefaults = B.laborUnstated(state.polish_estimate) ? loadLaborDefaults() : null;
    // The company labor rate is read for EVERY bid, a saved one included: it is only APPLIED to a
    // new bid (the laborDefaults gate below), but "Default $X" under a rate needs it on any.
    var laborRate = loadLaborRate();
    // Lodging and Per Diem rates ride the same gate as the labor defaults: a NEW bid copies them
    // from Markups -> Global once; a saved bid keeps the rates it was saved with.
    var travelRates = laborDefaults ? loadTravelRates() : null;
    // The Labor Calculator's per-line modes: same gate again -- a NEW bid fills its default labor
    // from them, a saved bid is never recomputed.
    var laborCalc = laborDefaults ? loadLaborCalc() : null;

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
    var conditionDefaults = B.conditionsUnstated(state.polish_estimate)
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
    if (laborDefaults) {
      // Library rows with no rate of their own and Travel follow the company rate, then the three
      // crew rows are set to it. New bids only: this whole block is behind the laborUnstated gate.
      M.labor = B.applyLaborRate(
        B.seedLibraryLabor(M.labor, await laborDefaults, LABOR_RATE), LABOR_RATE);
      // A default can carry guys_auto, exactly as Travel does. Re-run for the same reason adopt()
      // runs it: before the first paint, not on the first edit.
      syncAutoGuys();
      // The two travel rates, onto the new bid's Lodging / Per Diem lines (both start OFF).
      M.travel = B.applyTravelRates(M.travel, await travelRates);
    }

    // The library's answers for joint filler, remove-existing and dye, written over the shipped
    // ones — on a brand new bid and on nothing else.
    //
    // THE CELL STILL WINS, so conditionsFromCells runs AFTER the seed rather than only in adopt().
    // A project that came through the beta intake has its answers in cell_values and no
    // polish_estimate at all, which is precisely the blob conditionsUnstated calls seedable; if
    // the seed ran last it would write a company-wide default over the answer the estimator gave
    // on intake, and their next save would put that default into Kyle's workbook. Seed first, then
    // let the cell win, which is the order every other reader of these three already uses.
    //
    // Nothing is written to the draft here, exactly as with the labor defaults above: the seeded
    // answers are persisted by the first edit, which is what makes changing a default later leave
    // the bids already holding it alone.
    if (conditionDefaults) {
      var condRows = await conditionDefaults;
      M.conditions = B.conditionsFromCells(
        B.seedConditionDefaults(M.conditions, condRows), state.cell_values);
      // Which cards this new bid shows: the ones still on the Defaults tab (seedConditionsShown).
      M.conditions_shown = B.seedConditionsShown(condRows);
    }

    // Seed the measurement from intake if nothing has been measured here yet, so the page opens
    // with the number the estimator already gave us rather than a blank.
    //
    // BOTH of intake's boxes (Hanz, 2026-10-05): System 1 -> polish_sf, System 2 (optional) ->
    // polish_2_sf, one takeoff row each. Seeding only ever fills an EMPTY takeoff -- see
    // B.seedTakeoffSf for the rules. polish_sf is rewritten as the takeoff total on the first
    // save, and from then on intake shows its boxes locked.
    if (!B.takeoffSf(M.takeoff)) {
      // A NEW BID ALSO LOADS THE DEFAULTS (Hanz, 2026-10-05), on the same gate as the condition
      // defaults above: nothing ever saved. seedDefaultTakeoff owns how they combine with intake's
      // SF boxes (one area-carrying row, the rest marked same_floor); it falls through to
      // seedTakeoffSf when the library has no defaults, and a saved bid takes seedTakeoffSf alone.
      // "New" is the saved blob stating nothing, OR nothing but what the beta intake minted: intake
      // saves a model (conditions, a blank takeoff row) but deletes `labor`, which only this page
      // ever states, so laborUnstated is the signal that the calculator has never saved here.
      M.takeoff = (B.conditionsUnstated(state.polish_estimate) || B.laborUnstated(state.polish_estimate))
        ? B.seedDefaultTakeoff(M.takeoff, ASMS, ITEMS, RESERVED_ITEM_IDS,
                               state.polish_sf, state.polish_2_sf)
        : B.seedTakeoffSf(M.takeoff, state.polish_sf, state.polish_2_sf);
    }
    // THE LABOR CALCULATOR, AFTER THE TAKEOFF SEED because "from SF" lines need the job's SF
    // (B.takeoffSf, the same figure the bid divides by). New bids only (laborCalc is null
    // otherwise). Nothing is written to the draft here; the first edit saves the filled rows, and
    // from then on the rows are the BID's.
    if (laborCalc) {
      M.labor = B.applyLaborCalc(M.labor, await laborCalc, B.takeoffSf(M.takeoff), LABOR_RATE);
      syncAutoGuys();
    }
    // THE TAKEOFF TOTAL IS polish_sf, SO MAKE THE DRAFT SAY SO NOW. Two ways the draft can be
    // behind the model this page just opened with: (1) seeding filled rows in memory only, so
    // polish_sf held System 1 alone and computed_bid held nothing until the first edit; (2) the
    // live intake's beta-continue door saved a polish_sf typed over a takeoff that was already
    // measured. proposal-review reads polish_sf for the SF token. One debounced save, only when
    // the two actually differ, so a plain reopen writes nothing.
    var tkSf = B.takeoffSf(M.takeoff);
    if (tkSf > 0 && tkSf !== B.num(state.polish_sf)) saveSoon();

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
    if (laborDefaults && !M.distance) lookupDistance(false);
  }

  init();
})();
