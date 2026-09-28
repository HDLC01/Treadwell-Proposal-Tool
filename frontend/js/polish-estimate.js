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
//     answer back on the next visit to Intake. The downloaded .xlsx therefore shows the
//     template's own Polish tab, not what was priced here. That is survivable only because the
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
   *  COVERAGE IS TYPED ON THE ROW, falling back to the item's own default -- priceLine's existing
   *  rule, not a new one. It has to be per-row rather than per-item because the same product is
   *  used at different coverages in different systems, which is exactly why Kyle's sheet keeps
   *  coverage on the line. Storing the row's figure back onto the item would make it wrong for
   *  every other place that item is used.
   *
   *  The return is shaped like priceAssembly's so every caller -- rowCost, materialTotal, the
   *  broken-line warning, the per-unit hint -- keeps working without knowing which kind it got. */
  function rowPrice(row) {
    var r = row || {};
    if (r.item_id) return priceMaterialRow(r);
    var asm = asmById(r.assembly_id);
    if (!asm) return null;
    return L.priceAssembly(asm, ITEMS, B.num(r.measurement));
  }

  /** One material, priced as priceAssembly would have priced a one-line assembly containing it.
   *
   *  `broken_lines` follows library-core's own rule rather than inventing a second one: an
   *  unfilled row is work not started, not work gone wrong, so `no_item` is not a fault. Getting
   *  that wrong would put "1 line cannot price yet" under every row the moment it is added. */
  function priceMaterialRow(r) {
    var area = B.num(r.measurement);
    var one = L.priceLine({ item_id: r.item_id, coverage: r.coverage,
                            waste_pct: r.waste_pct, roundup: r.roundup }, ITEMS, area);
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
    var p = rowPrice(row);
    if (!p || !p.priced_lines) return { text: "—", empty: true, price: p };
    return { text: moneyAuto(p.total), empty: false, price: p };
  }

  function materialTotal() {
    var sum = 0;
    M.takeoff.forEach(function (r) {
      var p = rowPrice(r);
      if (p) sum += p.total;
    });
    // Dye and Joint Filler are fixed formulas keyed on the polished area (Polish!E25/E29),
    // not library items -- see polish-bid-core.js's dyeCost/jointFillerCost for why they
    // are not a priceLine call. `area` is the SAME B.takeoffSf(M.takeoff) that bid() below
    // uses for the sheet's SF, so the Material total and the price-per-SF divisor can never
    // disagree about what "the area" is.
    var area = B.takeoffSf(M.takeoff);
    sum += B.dyeCost(area, M.conditions.dye);
    sum += B.jointFillerCost(area, M.conditions.joint_filler);
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
        cell_values: B.conditionCellWrites(M.conditions, TW.getState().cell_values),
        // proposal-review reads this for the SF token, and /api/generate's files-mode rebuild
        // gates on it.
        polish_sf: b.sf,
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

  function covHint(row) {
    var it = itemById((row || {}).item_id);
    var cov = it && B.num(it.coverage);
    if (B.num((row || {}).coverage)) return "How far one goes, for this job.";
    if (cov) return "Blank uses the library's " + B.num(cov) + ".";
    return "How far one goes. The library has no default for it.";
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
   *  Material total through polish-bid-core.js's jointFillerCost/dyeCost. Since 2026-09-19 they
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
   *  `qty` READS THE PRICE BACK rather than restating the formula. "One kit per 3,500 sq ft" lives
   *  in polish-bid-core.js and nowhere else; dividing the cost by the kit rate cannot drift from
   *  it, and a second copy of 3500 on this page could. */
  var CONDITION_CARDS = [
    { key: "joint_filler", tag: "JOINT FILLER", label: "In the bid", cell: "Polish!E29",
      material: "Joint filler, 10 gal kit",
      matHint: "Polish!E29 · a fixed kit price, not a library item.",
      cost: function (area) { return B.jointFillerCost(area, true); },
      qty: function (area) {
        return B.jointFillerCost(area, true) / B.RATES.JOINT_FILLER_KIT_COST;
      },
      unit: function (n) { return n === 1 ? "kit" : "kits"; },
      qtyHint: function (area) {
        return B.fmtSf(area) + " sq ft, at one kit per 3,500, rounded up.";
      },
      unitHint: "Kits are what the job buys." },
    { key: "remove_existing_jf", tag: "REMOVE EXISTING", label: "Taking the old filler out",
      cell: "Polish!F29", needs: "joint_filler",
      why: "Adds a fourth hand to the joint-filler line. Priced on the Labor step, where that " +
           "line is." },
    { key: "dye", tag: "DYE", label: "In the bid", cell: "Polish!E25",
      material: "Dye, two coats",
      matHint: "Polish!E25 · a flat rate, not a library item.",
      cost: function (area) { return B.dyeCost(area, true); },
      qty: function (area) { return B.num(area); },
      unit: function () { return "SF"; },
      qtyHint: function () { return "The polished area from the rows above."; },
      unitHint: "Priced across the area, not by the pack." }
  ];

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
      rate: qty > 0 ? B.money2(cost / qty) + " / " + c.unit(1) : "",
      qtyHint: c.qtyHint(area)
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
   *  FOUR COLUMNS, `.tk-g` UNCHANGED -- the assembly row's template, not `.matg`'s five. There is
   *  no Coverage, because neither of these is bought by the pack. Sharing the template is what
   *  puts the Measurement, Unit and Total cost of these lines in the same place down the page as
   *  every row above them, which is the whole point of them being rows. */
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
    return '<div class="tk mat">' +
      '<div class="tk-h">' +
      '<span class="tag">' + esc(c.tag) + "</span>" +
      '<span class="tk-sub" data-condfig="' + esc(c.key) + '.sub">' + esc(f.sub) + "</span>" +
      condSwitch(c.key, c.label) +
      "</div>" +
      '<div class="tk-g">' +

      '<div class="f"><label>Material</label>' +
      '<div class="costbox txt">' + esc(c.material) + "</div>" +
      '<p class="hint">' + esc(c.matHint) + "</p></div>" +

      '<div class="f"><label>Measurement</label>' +
      box("qty", f.qtyEmpty, f.qty) +
      hint("qtyhint", f.qtyHint) + "</div>" +

      '<div class="f"><label>Unit</label>' +
      '<div class="costbox txt" data-condfig="' + esc(c.key) + '.unit">' + esc(f.unit) +
      "</div>" +
      '<p class="hint">' + esc(c.unitHint) + "</p></div>" +

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
    return '<div class="tk cond' + (inert ? " inert" : "") + '">' +
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

  function rowCardClass(r) { return "tk" + (rowKind(r) === "item" ? " mat" : ""); }

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
          '<p class="hint">' + esc(covHint(r)) + '</p></div>'
        : "") +

      '<div class="f"><label>Total cost</label>' +
      '<div class="costbox' + (rc.empty ? " empty" : "") + '" data-cost-for="' + i + '">' +
      esc(rc.text) + '</div>' +
      '<p class="hint" data-perunit-for="' + i + '">' +
      esc(p && p.per_unit != null ? B.money2(p.per_unit) + " / " + (r.unit || "SF") : "") +
      '</p></div>' +

      '</div>' + warn;
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
    html += CONDITION_CARDS.map(function (c) {
      return c.cost ? condMaterialCard(c) : condSwitchCard(c);
    }).join("");

    html += '<p class="cap">Material total <b data-mat-total>' +
      esc(moneyAuto(materialTotal())) + '</b> · measured area <b data-area-total>' +
      esc(B.fmtSf(B.takeoffSf(M.takeoff))) + ' SF</b>. LF rows are priced like any other but do ' +
      'not count toward the square footage the price-per-SF is divided by.</p>';

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
    return '<div class="tk lab' + (inert ? " inert" : "") + '" data-lab-card="' + i +
      '"><div class="tk-h">' +
      '<input class="labname" data-lab="' + i + '" data-k="label" value="' + esc(nv(r.label)) +
      '" placeholder="Task" aria-label="Task name">' + toggle +
      '<span class="tk-sub calc" data-lcost-for="' + i + '">' +
      esc(moneyAuto(B.laborCost(r))) + '</span>' +
      (M.labor.length > 1
        ? '<button class="x" data-del-lab="' + i + '" title="Remove this line">' + icon("x", 12) + '</button>'
        : '') +
      '</div><div class="tk-g lab-g">' +

      '<div class="f"><label>Guys</label>' +
      '<input class="n" data-lab="' + i + '" data-k="guys" value="' +
      esc(nv(r.guys)) + '"' + (auto ? ' data-auto="1"' : '') + '>' +
      // "Guys", never "Crew" -- Hanz renamed that column and
      // test_nothing_on_screen_says_labour_or_crew holds the page to it.
      '<p class="hint">' + (auto ? 'Man-days from the tasks above.'
        : (hours ? 'Man-days on the road.' : 'How many on it.')) + '</p></div>' +

      '<div class="f"><label>' + (hours ? "Hours" : "Days") + '</label>' +
      '<input class="n" data-lab="' + i + '" data-k="days" value="' + esc(nv(r.days)) + '">' +
      '<p class="hint">' + (hours ? "Drive time, each way counted." : "How long it takes.") +
      '</p></div>' +

      '<div class="f"><label>Rate</label>' +
      '<span class="mny">$<input class="n" data-lab="' + i + '" data-k="rate" value="' +
      esc(nv(r.rate)) + '"></span>' +
      '<p class="hint">Per hour.</p></div>' +

      '<div class="f"><label>Cost</label>' +
      '<div class="costbox' + (B.laborCost(r) > 0 ? "" : " empty") + '">' +
      esc(moneyAuto(B.laborCost(r))) + '</div>' +
      '<p class="hint">' + (hours ? "guys × hours × rate" :
        "guys × days × rate × " + B.HOURS_PER_DAY) + '</p></div>' +

      '</div>' + (hours
        // Rendered unconditionally on hours rows -- CSS (`.lab:not(.inert) .inertline`) decides
        // whether it shows, so the card's class is the one source of truth for both the dimming
        // and the caption, and the two cannot drift apart on a live repaint.
        ? '<p class="inertline">This job is marked local, so no travel is expected — type here ' +
          'anyway if it needs drive time.</p>'
        : "") + '</div>';
  }

  function laborPanel() {
    var html = M.labor.map(laborCard).join("");

    // Same control as the takeoff step's, below the list rather than above it: this one adds a
    // row you then name yourself, so there is nothing to search and nothing to scroll back to.
    html += '<button class="btn addline below" data-add-lab="1">' + icon("plus", 16)
      + ' Add a labor line</button>';
    html += '<p class="cap">Labor total <b data-labor-total>' +
      esc(moneyAuto(B.laborTotal(M.labor))) + '</b>.</p>';

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
    return '<span class="mw-sw' + (on ? " on" : "") + (inert ? " inert" : "") +
      '" data-cond="' + esc(key) +
      '" role="switch" tabindex="0" aria-checked="' + (on ? "true" : "false") + '">' +
      '<span class="track"></span>' + esc(label) + '</span>';
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
    ITEMS.forEach(function (it) { add(it.name, "item"); });
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
      el.className = "tk lab" + (laborInert(r) ? " inert" : "");
    });
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
    });

    var one = function (sel, txt) {
      var el = document.querySelector(sel);
      if (el) el.textContent = txt;
    };
    one("[data-mat-total]", moneyAuto(materialTotal()));
    one("[data-area-total]", B.fmtSf(B.takeoffSf(M.takeoff)) + " SF");
    one("[data-labor-total]", moneyAuto(B.laborTotal(M.labor)));
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
  function newLaborRow() {
    laborSeq += 1;
    return { id: "u_" + Date.now() + "_" + laborSeq, label: "", guys: "", days: "", rate: "" };
  }

  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;

    var go_ = t.closest("[data-go]");
    if (go_) { e.preventDefault(); go(parseInt(go_.getAttribute("data-go"), 10)); return; }

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
    var cond = t.closest("[data-cond]");
    if (cond) {
      var ck = cond.getAttribute("data-cond");
      M.conditions[ck] = !M.conditions[ck];
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
    var want = String(text || "").trim().toLowerCase();
    var hit = null;
    for (var n = 0; n < ITEMS.length; n++) {
      if (String(ITEMS[n].name || "").trim().toLowerCase() === want) { hit = ITEMS[n]; break; }
    }
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
      delete row.assembly_id; delete row.assembly_name;
      return;
    }
    if (kind === "asm") {
      row.kind = "asm";
      row.assembly_id = ""; row.assembly_name = "";
      delete row.item_id; delete row.item_name; delete row.coverage;
      return;
    }
    row.kind = "new"; row.pick_name = "";
    delete row.assembly_id; delete row.assembly_name;
    delete row.item_id; delete row.item_name; delete row.coverage;
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
    if (!el.matches("input")) return;
    var k = el.getAttribute("data-k");

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
        var flipped = setPick(i, el.value);
        changed(false);
        if (flipped) {
          repaintRow(i);
          refocus('[data-tk="' + i + '"][data-k="pick"]');
        }
        return;
      }
      if (M.takeoff[i]) M.takeoff[i][k] = el.value;
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
  function refocus(sel) {
    var el = document.querySelector(sel);
    if (!el || !el.focus) return;
    el.focus();
    try { el.setSelectionRange(el.value.length, el.value.length); } catch (err) {}
  }

  document.addEventListener("change", function (e) {
    var el = e.target;
    if (!el || !el.getAttribute) return;
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
    if (laborDefaults) {
      M.labor = B.seedLibraryLabor(M.labor, await laborDefaults);
      // A default can carry guys_auto, exactly as Travel does. Re-run for the same reason adopt()
      // runs it: before the first paint, not on the first edit.
      syncAutoGuys();
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
      M.conditions = B.conditionsFromCells(
        B.seedConditionDefaults(M.conditions, await conditionDefaults), state.cell_values);
    }

    // Seed the measurement from intake if nothing has been measured here yet, so the page opens
    // with the number the estimator already gave us rather than a blank.
    if (!B.takeoffSf(M.takeoff) && B.num(state.polish_sf) > 0) {
      M.takeoff[0].measurement = B.num(state.polish_sf);
    }

    renderDatalist();
    $("loading").hidden = true;
    $("main").hidden = false;
    paintBid();
    // The step the URL names, decided BEFORE the first paint so the rail and the panel come up
    // agreeing. Setting `at` after paintRail would light one step and render another.
    at = openingStep(at);
    paintRail();
    renderPanel();
  }

  init();
})();
