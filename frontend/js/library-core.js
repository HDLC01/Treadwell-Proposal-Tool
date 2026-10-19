// Item Library pricing — pure functions, no DOM, no fetch.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// THE MODEL, and where it comes from.
//
// Taken from Kyle's estimate sheet ("Decorative Flake Systems / MACRO Flake Single
// Broadcast"). One measured area drives every line of an assembly:
//
//     needed = area / coverage * (1 + waste/100)      units, fractional
//     bought = CEIL(needed / buy_qty) packs           when the line rounds up
//              needed units                           when it doesn't
//     line   = packs * pack price   or   needed * (pack price / buy_qty)
//     total  = sum of the lines
//     price per unit of measure = total / area
//
// Reproduced against his printed sheet at 2,875 SF with waste 0 and single-unit packs: OPF at
// 275 SF/Gal -> 11 Gal / $939.21, Glaze #4 at 125 -> 23 Gal / $1,834.42, Armor Top Satin at
// 775 SF/Kit -> 4 Kit / $1,529.79. Every line matches to the cent. Stack's `{MeasuredArea}/200`
// item formula is the same arithmetic, which is why one model serves both mental pictures.
//
// FOUR DECISIONS WORTH KNOWING.
//
// 1. CEIL, not round — when the line asks for it. You cannot buy 3.71 kits, so a 2,875 SF floor
//    takes 4 kits of a 775 SF top coat. Rounding to nearest would under-buy on most jobs, and
//    the estimate would be short of material rather than merely mispriced. The Roundup? checkbox
//    exists because not everything is bought that way: bulk gypsum is weighed out, and forcing
//    whole bags onto it overstates a large pour.
//
// 2. Waste INFLATES. 5% means buy 5% more than the area strictly needs — the offcuts, the
//    over-rolled edge, the half-kit that skins over. It is not 5% off the price.
//
// 3. Coverage is per SINGLE unit and `unit_cost` is what the PACK costs (Hanz, 2026-08-15: Cost
//    is "the cost of that Qty+Unit purchase"). So a 5-gallon pail covering 275 SF/Gal covers
//    1,375 SF, and the two numbers can no longer be divided into each other directly.
//
// 4. The total sums UNROUNDED line costs, then rounds once for display. Adding the rounded
//    lines instead shifts the total by a cent or two, and Excel (Kyle's sheet) sums the
//    unrounded values. Worth knowing that his sheet PRINTS $4,303.41 while its three printed
//    lines add to $4,303.42 — that one cent is this exact distinction, and it is flagged for
//    Kyle rather than quietly resolved here.
//
// Costs carry four decimal places on purpose: his per-gallon prices back-solve to
// $85.3827 and $79.7574, and holding them at two would drift over a large floor.
(function (root, factory) {
  var api = factory();
  root.TWLib = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;   // node, for tests
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  /** A number from anything a person might type or paste. Null when it isn't one.
   *
   *  Tolerates "$1,200" and " 275 " because these values get pasted out of spreadsheets. */
  function num(raw) {
    if (raw === null || raw === undefined || raw === "") return null;
    if (typeof raw === "number") return isFinite(raw) ? raw : null;
    if (typeof raw === "boolean") return null;
    var s = String(raw).replace(/[$,\s]/g, "");
    if (s === "" || !/^-?\d*\.?\d+$/.test(s)) return null;
    var n = parseFloat(s);
    return isFinite(n) ? n : null;
  }

  /** The item a line points at, or null when it has been removed from the library. */
  function findItem(items, id) {
    if (!id) return null;
    for (var i = 0; i < (items || []).length; i++) {
      if (items[i] && items[i].id === id) return items[i];
    }
    return null;
  }

  /** A line's waste factor as a percentage. 5 when it hasn't got one.
   *
   *  Matches library.py's read-shaping deliberately: a line stored before the column existed must
   *  price the same on both sides, and a row showing 5% that was priced at 0% is a lie. */
  function wastePct(row) {
    var v = num((row || {}).waste_pct);
    if (v === null || v < 0) return 5;
    return Math.min(v, 100);
  }

  /** How many units come in one purchase — the "5" of "5 Gal". 1 when unset, which is what every
   *  row written before that column existed genuinely is. Never 0: a pack of nothing would divide
   *  the cost by zero. */
  function buyQty(item) {
    var v = num((item || {}).buy_qty);
    return (v === null || v <= 0) ? 1 : v;
  }

  /** The kinds of measure a coverage can be quoted against: floor area, length, or a count. */
  var BASES = ["sf", "lf", "each"];

  /** What a material's coverage is measured per: "sf", "lf" or "each". Null when the material has
   *  not said, which is every row written before the column and means "use the area you were given". */
  function coverageBasis(item) {
    var b = (item || {}).coverage_basis;
    if (typeof b !== "string") return null;
    b = b.trim().toLowerCase();
    return BASES.indexOf(b) === -1 ? null : b;
  }

  /** The measured quantity this material is priced against.
   *
   *  A plain number is returned untouched, which is how every caller works today: the caller has
   *  already decided which measure drives the line. An OBJECT, `{sf, lf, each}`, is a whole takeoff,
   *  and each material picks its own: a cove material takes the LF, a floor material the SF (also
   *  what a material with no basis gets). A takeoff without the measure asked for answers undefined,
   *  which prices as "no area yet" rather than as zero. */
  function areaFor(item, area) {
    if (area === null || typeof area !== "object" || Array.isArray(area)) return area;
    var basis = coverageBasis(item);
    if (basis === "lf") return area.lf;
    if (basis === "each") return area.each;
    return area.sf;
  }

  /** A material's price breaks as clean numbers: `[{min_qty, unit_cost}]`. Anything malformed is
   *  left out instead of guessed at, so a half-typed break can never price a line. Order does not
   *  matter here; the break chosen is decided by the quantity alone. */
  function priceBreaks(item) {
    var raw = (item || {}).price_breaks;
    if (!Array.isArray(raw)) return [];
    var out = [];
    for (var i = 0; i < raw.length; i++) {
      var b = raw[i];
      if (!b || typeof b !== "object") continue;
      var q = num(b.min_qty), c = num(b.unit_cost);
      if (q === null || q <= 0 || c === null || c < 0) continue;
      out.push({ min_qty: q, unit_cost: c });
    }
    return out;
  }

  /** The price break a purchase falls in, or null when it is below every one.
   *
   *  THE EDGE RULE, taken from Kyle's sheet. His flake line is
   *  `=IF(O194<240, O194*small-lot price, O194*MACROFlake)`: strictly under 240 lb pays the small-lot
   *  price, and 240 lb exactly already pays the bulk price. So a break applies FROM its quantity,
   *  inclusive, and the one with the largest quantity not above the purchase wins. Quantity is the
   *  units BOUGHT, in the material's own unit (pounds for flake), after rounding up to whole packs.
   *
   *  The same twelve-figure guard as the pack count: 239.99999999999997 pounds is 240. */
  function breakAt(item, units) {
    var u = num(units);
    if (u === null) return null;
    u = parseFloat(u.toPrecision(12));
    var list = priceBreaks(item), hit = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].min_qty <= u && (hit === null || list[i].min_qty > hit.min_qty)) hit = list[i];
    }
    return hit;
  }

  /** THE LIBRARY AS ONE SECTION OF ONE BID BUYS IT (Hanz, 2026-10-16): `items` with that section's supplier discounts
   *  and Bulk Discount switch applied, as a COPY. Every price on the estimate goes through priceLine / pricePool over a
   *  list of items, so pricing them over this list is the whole change: no second pricing path exists to drift.
   *
   *    adj.discounts   { vendor: fraction off }   a material whose `vendor` is named is priced at
   *                    cost x (1 + E - d) / (1 + E), E = adj.escalation: the library cost is the list price with the
   *                    escalation in it (Kyle's U140), and his sheet takes the discount off the LIST, so the
   *                    escalation stands. Its pack cost, bulk cost and every price break move alike.
   *    adj.bulk        true: a material with a bulk cost is bought at it. A price break dearer than the bulk cost is
   *                    dropped, because switching a discount on must never raise a price (priceLine's breakHelps,
   *                    which this keeps), and the cheaper break still wins.
   *
   *  The SAME ARRAY comes back when there is nothing to change, so a bid that never used the boxes prices off the
   *  library exactly as it always did. Rows are never mutated. A discount that would leave a price at or below zero is
   *  refused by the caller's range check (bid-model.js pctInRange); one that arrives anyway is ignored. */
  function itemsForBid(items, adj) {
    if (!(items instanceof Array) || !adj) return items;
    var disc = adj.discounts || {};
    var esc = num(adj.escalation) || 0;
    // A vendor is matched on its letters alone, so "Sherwin Williams", "sherwin-williams" and "Sherwin-Williams " typed
    // on the Items tab are one vendor, and a hand-made row gets the same discount the seeded ones do.
    var vkey = function (v) { return String(v == null ? "" : v).toLowerCase().replace(/[^a-z]/g, ""); };
    var offOf = new Map();
    Object.keys(disc).forEach(function (v) {
      var d = num(disc[v]);
      if (d !== null && d > 0 && (1 + esc - d) > 0) offOf.set(vkey(v), d);
    });
    var vendors = Array.from(offOf.keys());
    if (!adj.bulk && !vendors.length) return items;
    return items.map(function (it) {
      if (!it || typeof it !== "object") return it;
      var factor = 1;
      if (offOf.has(vkey(it.vendor))) factor = (1 + esc - offOf.get(vkey(it.vendor))) / (1 + esc);
      var bulkCost = num(it.bulk_cost);
      var useBulk = !!adj.bulk && bulkCost !== null && bulkCost > 0;
      if (factor === 1 && !useBulk) return it;
      var scale = function (c) { var n = num(c); return n === null ? c : n * factor; };
      var out = Object.assign({}, it, { unit_cost: scale(useBulk ? bulkCost : it.unit_cost) });
      if (bulkCost !== null) out.bulk_cost = scale(bulkCost);
      var brks = priceBreaks(it);
      if (brks.length) {
        out.price_breaks = brks
          .filter(function (b) { return !useBulk || b.unit_cost < bulkCost; })
          .map(function (b) { return { min_qty: b.min_qty, unit_cost: b.unit_cost * factor }; });
      }
      if (useBulk) out.bulk_applied = true;
      if (factor !== 1) out.discount_factor = factor;
      return out;
    });
  }

  /** Price one line against an area.
   *
   *  THREE OPTIONAL COLUMNS ON THE MATERIAL (Phase 11), and a row without them prices exactly as it
   *  always did. `price_breaks` swaps the pack cost for a cheaper one once the purchase is big
   *  enough (see breakAt). `bulk_cost` is the pack cost when the bid has the Bulk Discount switched
   *  on (Kyle's D41): pass `{bulk: true}` as `opts`, otherwise it is ignored. `coverage_basis` says
   *  which measure the coverage is quoted per (see areaFor). When a price break and the bulk cost
   *  both apply, the price break wins: it is the more specific price, the quantity actually bought.
   *  The one exception is a break dearer than the bulk cost: then the bulk cost stands, because
   *  turning a discount on must never raise the price (see breakHelps).
   *
   *  Returns `{ok: false, reason}` rather than throwing or defaulting to zero. A line whose
   *  material was deleted must be VISIBLE and must not contribute — pricing it at zero would
   *  quietly understate the assembly, which is the worst of the three options.
   *
   *  THE ARITHMETIC (Hanz, 2026-08-15). Coverage is now per SINGLE unit, and `unit_cost` is what
   *  the PACK costs, so the two are no longer the same division:
   *
   *      needed = area / coverage * (1 + waste/100)      units, fractional
   *      roundup ✓  packs = CEIL(needed / buy_qty)       cost = packs * pack price
   *      roundup ✗  cost  = needed * (pack price / buy_qty)
   *
   *  Waste INFLATES — 5% means buy 5% more than the area needs, not price 5% of it away.
   *  With buy_qty 1, roundup on and waste 0 this is exactly the old CEIL(area/coverage) model,
   *  which is how every line written before today keeps its number. */
  function priceLine(line, items, area, opts) {
    line = line || {};
    // A LINE NOBODY HAS FILLED IN IS NOT A BROKEN LINE, and this is the only place that
    // distinction can be drawn once. `findItem` returns null for an empty id and for a deleted
    // one alike, so "the estimator just clicked + line" and "the material this line used was
    // removed from the library" both arrived as missing_item -- and every consumer then reported
    // a fresh, empty row as a fault: amber "Item removed" in the quantity cell, a "Pick a
    // replacement item" note, a red-tinted row, "1 to fix" in the sidebar, and a warning on the
    // Polish beta page. Five surfaces, one wrong answer, because they all trusted this reason.
    if (!(line.item_id || line.item)) return { ok: false, reason: "no_item", qty: 0, cost: 0 };
    var item = findItem(items, line.item_id || line.item);
    if (!item) return { ok: false, reason: "missing_item", qty: 0, cost: 0 };

    // COVERAGE, WASTE AND ROUNDUP COME FROM THE MATERIAL, and from nowhere else.
    //
    // Hanz, 2026-09-22: "we must have coverage per unit, waste factor, roundup, and materials
    // tab. And then it gets pulled in to assemblies instead of it being in assemblies." Offered
    // per-line overrides, he chose "Material only, no overrides" -- so a line names a material
    // and a role and carries no numbers of its own.
    //
    // THIS IS A PRECEDENCE INVERSION, NOT NEW ARITHMETIC. The fallback already ran the other
    // way: line first, item as the default. The paragraph that stood here said coverage lives on
    // the line "(Kyle's sheet keeps it there)" because "the same product is used at different
    // coverages in different systems". That case has not gone away -- it is now served by TWO
    // MATERIALS rather than by one material at two coverages, which is what the owner chose and
    // what the migration that precedes this change does to the two rows it applied to.
    //
    // NO FALLBACK TO THE LINE. A reader that took the line's value when the material had none
    // would be two sources for one number, which is the shape of defect this repo keeps paying
    // for. The migration copies every line's values onto its material BEFORE this lands, so
    // there is nothing to fall back to and nothing that silently reprices.
    var cov = num(item.coverage);
    if (cov === null || cov <= 0) return { ok: false, reason: "no_coverage", qty: 0, cost: 0 };

    var packCost = num(item.unit_cost);
    if (packCost === null || packCost < 0) return { ok: false, reason: "no_cost", qty: 0, cost: 0 };

    var pack = buyQty(item);
    var waste = wastePct(item);
    // Absent means yes: CEIL is what these lines were priced with, and the page has promised
    // "you cannot buy 3.7 kits" since it shipped. Read off the MATERIAL now -- see above.
    var roundup = (item.roundup === undefined || item.roundup === null) ? true : !!item.roundup;

    // The Bulk Discount switch swaps the pack cost for the material's bulk cost, but only when
    // the caller says the bid has it on AND the material has a bulk cost worth using.
    var bulkCost = (opts && opts.bulk) ? num(item.bulk_cost) : null;
    var bulk = bulkCost !== null && bulkCost > 0;
    if (bulk) packCost = bulkCost;

    var base = { ok: true, coverage: cov, waste_pct: waste, roundup: roundup,
                 buy_qty: pack, pack_cost: packCost, unit_price: packCost / pack, item: item };
    // Only named when the material has said so: a row without the columns answers as it always did.
    if (bulk) base.bulk = true;
    var basis = coverageBasis(item);
    if (basis) base.basis = basis;

    var a = num(areaFor(item, area));
    if (a === null || a <= 0) {
      // No area yet is not an error — it is the state the screen opens in.
      return Object.assign(base, { priced: false, qty: 0, cost: 0, needed: 0, units: 0,
                                   packs: null });
    }

    var needed = (a / cov) * (1 + waste / 100);
    return purchase(base, needed, roundup, bulk, packCost);
  }

  /** WHAT BUYING `needed` UNITS OF ONE MATERIAL COSTS. The one place a fractional quantity becomes packs
   *  and a price, shared by a single line (priceLine) and by a purchase that several lines make together
   *  (pricePool), so the two cannot disagree about a rounding or a break.
   *
   *  `base` is the line being answered (`item`, `buy_qty`, and the pack cost and unit price a price break
   *  rewrites); `packCost` is the pack cost BEFORE any break; `bulk` says the bulk cost is what that is.
   *  `judged`, when given, is the quantity the price break is judged on instead of this purchase's own: it
   *  is how a pool of lines on one price ladder is read together (see pricePool). Mutates and returns `base`. */
  function purchase(base, needed, roundup, bulk, packCost, judged) {
    var pack = base.buy_qty, item = base.item;
    if (roundup) {
      // CEIL, but not on a float's rounding error. 27,500 ÷ 275 × 1.10 is 110.00000000000001 in
      // IEEE-754, and a bare ceil() there buys a 111th gallon nobody needs — on exactly the round
      // numbers an estimator checks by hand. Twelve significant figures is far finer than any
      // coverage anybody types and coarser than the error.
      var packs = Math.ceil(parseFloat((needed / pack).toPrecision(12)));
      var brk = breakAt(item, judged === undefined ? packs * pack : judged);
      if (brk && breakHelps(bulk, packCost, brk)) packCost = withBreak(base, brk);
      return Object.assign(base, { priced: true, needed: needed, packs: packs,
                                   units: packs * pack, qty: packs, cost: packs * packCost });
    }
    // Fractional: buy exactly what is needed, at the price of one unit rather than one pack.
    var brk2 = breakAt(item, judged === undefined ? needed : judged);
    if (brk2 && breakHelps(bulk, packCost, brk2)) packCost = withBreak(base, brk2);
    return Object.assign(base, { priced: true, needed: needed, packs: null,
                                 units: needed, qty: needed,
                                 cost: needed * (packCost / pack) });
  }

  /** Does a price break change the price? Always, EXCEPT when the bid has Bulk Discount on and the
   *  break costs no less than the bulk cost already in use: switching a discount on must never
   *  raise the price, so the cheaper of the two stands. With bulk off the break always applies,
   *  as it always did. */
  function breakHelps(bulk, packCost, brk) {
    return !(bulk && brk.unit_cost >= packCost);
  }

  /** Put a price break's cost on a priced row and say which break it was. Returns the pack cost. */
  function withBreak(base, brk) {
    base.pack_cost = brk.unit_cost;
    base.unit_price = brk.unit_cost / base.buy_qty;
    base.price_break = { min_qty: brk.min_qty, unit_cost: brk.unit_cost };
    return brk.unit_cost;
  }

  /** Price a whole assembly. `lines[i]` in, `rows[i]` out — same order, same length, so the
   *  caller can render them side by side without matching anything up. */
  function priceAssembly(assembly, items, area, opts) {
    var lines = (assembly && assembly.lines) || [];
    var rows = [], total = 0, priced = 0, broken = 0;
    for (var i = 0; i < lines.length; i++) {
      var r = priceLine(lines[i], items, area, opts);
      rows.push(r);
      // `broken_lines` means "faults to fix" -- what the sidebar badge and the Polish page's
      // warning both count. An unfilled line is work not started, not work gone wrong, so it is
      // deliberately not counted here; that is what fixes both of those readouts without either
      // of them knowing about this change.
      if (!r.ok) { if (r.reason !== "no_item") broken += 1; continue; }
      if (r.priced) { total += r.cost; priced += 1; }
    }
    var a = num(area);
    var answer = {
      rows: rows,
      total: total,
      // Only meaningful with an area. Reporting 0 would read as "free" rather than "unknown".
      per_unit: (a !== null && a > 0 && priced > 0) ? total / a : null,
      priced_lines: priced,
      broken_lines: broken,
    };
    // WHICH ASSEMBLY these rows are the lines of: pricePool tells one coat from another by it (the same line of the
    // same assembly on two takeoff rows is one coat; two lines of one assembly are two). Only an assembly that has an
    // id says so, so an answer for an unnamed assembly keeps exactly the shape it always had.
    if (assembly && assembly.id !== undefined && assembly.id !== null) answer.assembly_id = assembly.id;
    return answer;
  }

  // ── ONE PURCHASE FOR THE WHOLE JOB (Hanz, 2026-10-13, "Buy packs for the whole job") ────────────────
  //
  // A coat used on several takeoff rows is bought ONCE. Priced row by row, each row rounded its own
  // fractional quantity up to whole packs, so System 1 5,000 SF plus System 2 3,000 SF bought up to one
  // more pack per material than one 8,000 SF floor does (+$1,580, 6%, on the real library; 1,000 + 1,000
  // is +17%). The pool sums the FRACTIONAL quantity of the same material across every row and line that
  // buys it, applies the roundup and the price break ONCE, and hands the pooled cost back to the rows in
  // proportion to what each needed, so a row still shows a cost and the rows add up to the pooled total.
  //
  // TWO LEVELS, because Kyle's sheet does two different things.
  //   1. THE SAME COAT (Hanz, 2026-10-13, "Round each coat like Kyle"): one line of one assembly, which is the
  //      same library item on the same line index of the same assembly (a coverage typed on a bid is the same
  //      item, see `pool_of`). The coat's fractional quantities on every row and area that holds that assembly are
  //      added first, then waste, roundup and the break happen once. TWO DIFFERENT LINES of one assembly that buy
  //      the same item are TWO coats, each rounded up to its own whole packs, exactly as Kyle's sheet rounds each
  //      line (Shop Floor Double Broadcast is three lines of Shop Floor and buys three roundups, not one). A
  //      single-area, single-system job therefore prices to the workbook to the cent. A material row (no
  //      assembly) is its own coat, keyed by the item, so two rows of the same item still pool.
  //   2. A PRICE LADDER SHARED BY DIFFERENT MATERIALS. The sheet judges a flake or quartz break on a system's
  //      two broadcast lines ADDED TOGETHER (`IF((O201+O202)<240, ...)`), and each line still rounds to its own
  //      bags. The library holds those two lines as two items (the name carries the pounds per SF), so they
  //      are pooled for the BREAK ONLY: each keeps its own packs, and the break is judged on every pack
  //      bought across the ladder. A ladder is DERIVED, not stored: identical price breaks, pack cost, bulk
  //      cost, pack size, unit and roundup. That is exactly the sheet's reading (both lines point at the same
  //      two price cells), it needs no new column and no reseed, and it holds for rows already in the library.

  /** The item a priced line belongs to for pooling: the real one when a bid typed its own coverage on a
   *  throwaway copy (`pool_of`), else the item itself. */
  function poolId(item) {
    var it = item || {};
    return (it.pool_of !== undefined && it.pool_of !== null && it.pool_of !== "") ? it.pool_of : it.id;
  }

  /** The coat a priced line belongs to: the line of its assembly (assembly id and line index) plus the item, or
   *  just the item for a line that is not a line of an assembly (a material row). One string, a Map key. */
  function coatKey(res, j, id) {
    var a = res ? res.assembly_id : undefined;
    return (a === undefined || a === null || a === "") ? JSON.stringify(["m", id]) : JSON.stringify(["a", a, j, id]);
  }

  /** A price ladder as one string, or null for a material with no price breaks (those pool at level 1 only). */
  function ladderKey(item, roundup) {
    var brks = priceBreaks(item);
    if (!brks.length) return null;
    brks.sort(function (x, y) { return x.min_qty - y.min_qty; });
    return JSON.stringify([brks, num(item.unit_cost), num(item.bulk_cost), buyQty(item),
                           String((item || {}).unit || ""), !!roundup]);
  }

  /** `total` split in proportion to `weights` so the parts add up to `total` exactly. A library cost has four
   *  decimals, so a pooled cost lands on a ten-thousandth of a dollar and is split in whole ten-thousandths by
   *  the LARGEST REMAINDER (each part is rounded down, and the leftover ten-thousandths go to the parts with
   *  the biggest fractions, the earlier one first on a tie). A total that is not on a ten-thousandth (a
   *  fractional purchase at an odd unit price) is split exactly in proportion and the last part takes what is
   *  left, so the parts still add up. */
  function allocate(total, weights) {
    var n = weights.length, sum = 0, i;
    for (i = 0; i < n; i++) sum += weights[i];
    if (n === 0) return [];
    if (!(sum > 0)) return weights.map(function (w, k) { return k === 0 ? total : 0; });
    var grain = 1e4, scaled = total * grain, whole = Math.round(scaled);
    var out = [];
    // "On a ten-thousandth" is judged against float noise only (a few ulps of the scaled figure). A looser, size-
    // relative tolerance read every total above about $5 as on the grain and snapped a fractional purchase to it.
    if (Math.abs(scaled - whole) > Math.max(1e-6, 1e-12 * Math.abs(scaled))) {
      var rest = total;
      for (i = 0; i < n - 1; i++) { out.push(total * weights[i] / sum); rest -= out[i]; }
      out.push(rest);
      return out;
    }
    var parts = weights.map(function (w, k) {
      var q = whole * w / sum, f = Math.floor(q);
      return { k: k, f: f, frac: q - f };
    });
    var left = whole - parts.reduce(function (t, p) { return t + p.f; }, 0);
    parts.slice().sort(function (x, y) { return (y.frac - x.frac) || (x.k - y.k); }).forEach(function (p, r) {
      if (r < left) p.f += 1;
    });
    return parts.map(function (p) { return p.f / grain; });
  }

  /** PRICE SEVERAL PRICED TAKEOFF ROWS AS ONE PURCHASE. `results[i]` is what a row priced to (the shape
   *  priceAssembly answers: `rows` of priceLine answers, `total`, `per_unit`, ...) or null; the answer is a new
   *  array of the same length, where every row that buys a coat (one line of one assembly, see coatKey) another
   *  row also buys has that coat's cost replaced by its share of the pooled purchase. Two lines of ONE assembly
   *  that buy the same item are two coats and are not pooled with each other. A row nothing pools with
   *  comes back as the very object it went in as, so a bid with nothing to pool prices to the cent as it did.
   *
   *  `opts.on[i] === false` leaves row i out (an OFF row buys nothing). `opts.skip` is a list of item ids that
   *  are never pooled (Dye, Joint Filler: each is owned by its own condition card and priced as it always was).
   *  A line that cannot price (no material, no coverage) is left exactly as it is. Whether the bid has Bulk
   *  Discount on is read off the priced lines themselves (`bulk`), so the pool buys at the same cost they did.
   *
   *  EVERY ROW HANDED IN IS ONE PURCHASE: the caller decides what "the section" is by what it passes. The
   *  estimate page passes the whole takeoff of one section (one priced tab of a bid).
   *
   *  The pooled line says so: `line.pooled = { lines, needed, packs, units, cost, share }` (the whole
   *  purchase and this line's share of it), and its `packs`, `units` and `qty` are that share. */
  function pricePool(results, opts) {
    opts = opts || {};
    var list = Array.isArray(results) ? results : [];
    var skip = Array.isArray(opts.skip) ? opts.skip : [];
    var groups = new Map();                 // level 1: coat -> every line that buys it
    list.forEach(function (res, i) {
      if (!res || !Array.isArray(res.rows)) return;
      if (opts.on && opts.on[i] === false) return;
      res.rows.forEach(function (r, j) {
        if (!r || !r.ok || !r.priced || !r.item) return;
        var id = poolId(r.item);
        if (id === undefined || id === null || id === "" || skip.indexOf(id) >= 0) return;
        var ck = coatKey(res, j, id);
        var g = groups.get(ck);
        if (!g) { g = { rep: r, lines: [], needed: 0 }; groups.set(ck, g); }
        g.lines.push({ i: i, j: j, r: r });
        g.needed += r.needed;
      });
    });
    // what each material's own purchase comes to, and which price ladders more than one of them sit on
    var ladders = new Map();
    groups.forEach(function (g) {
      var rep = g.rep, bulk = rep.bulk === true;
      g.bulk = bulk;
      g.cost0 = num(bulk ? rep.item.bulk_cost : rep.item.unit_cost);
      g.own = purchase({ item: rep.item, buy_qty: rep.buy_qty, pack_cost: g.cost0, unit_price: g.cost0 / rep.buy_qty },
                       g.needed, rep.roundup, bulk, g.cost0);
      var lk = ladderKey(rep.item, rep.roundup);
      if (lk === null) return;
      var lad = ladders.get(lk);
      if (!lad) { lad = { groups: [], units: 0 }; ladders.set(lk, lad); }
      lad.groups.push(g);
      lad.units += g.own.units;
      g.ladder = lad;
    });
    var out = list.slice(), changed = new Map();         // row index -> its lines, copied
    groups.forEach(function (g) {
      var shared = g.ladder && g.ladder.groups.length > 1;
      if (g.lines.length < 2 && !shared) return;           // nothing pools with it: leave the row alone
      var rep = g.rep, fin = g.own;
      if (shared) {
        fin = purchase({ item: rep.item, buy_qty: rep.buy_qty, pack_cost: g.cost0, unit_price: g.cost0 / rep.buy_qty },
                       g.needed, rep.roundup, g.bulk, g.cost0, g.ladder.units);
      }
      var share = allocate(fin.cost, g.lines.map(function (l) { return l.r.needed; }));
      var wsum = g.needed;
      g.lines.forEach(function (l, k) {
        var f = wsum > 0 ? l.r.needed / wsum : 0;
        var line = Object.assign({}, l.r, {
          cost: share[k], pack_cost: fin.pack_cost, unit_price: fin.unit_price,
          packs: rep.roundup ? fin.packs * f : null, units: fin.units * f, qty: (rep.roundup ? fin.packs : fin.qty) * f,
          pooled: { lines: g.lines.length, needed: g.needed, packs: fin.packs, units: fin.units, cost: fin.cost, share: f }
        });
        if (fin.price_break) line.price_break = fin.price_break; else delete line.price_break;
        var copy = changed.get(l.i);
        if (!copy) { copy = list[l.i].rows.slice(); changed.set(l.i, copy); }
        copy[l.j] = line;
      });
    });
    changed.forEach(function (rows, i) {
      var was = list[i], total = 0;
      rows.forEach(function (r) { if (r && r.ok && r.priced) total += r.cost; });
      var next = Object.assign({}, was, { rows: rows, total: total });
      // per unit is the total over the area the row was measured at, which the row no longer carries: recover it
      if (was.per_unit !== null && was.per_unit !== undefined && was.total > 0) next.per_unit = was.per_unit * (total / was.total);
      out[i] = next;
    });
    return out;
  }

  /** Money for display: two decimals, thousands separated. */
  function money(n) {
    var v = num(n);
    if (v === null) return "—";
    return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  /** A price per unit of measure. Three decimals, because $1.497/SF and $1.50/SF are
   *  different bids on a 40,000 SF floor. */
  function perUnit(n) {
    var v = num(n);
    if (v === null) return "—";
    return "$" + v.toFixed(3);
  }

  /** A quantity for reading: whole numbers plain, fractions to two places, no trailing zeros.
   *  "16.8 Gallon" and "3" rather than "16.80" and "3.00". */
  function qtyText(n) {
    var v = num(n);
    if (v === null) return "—";
    var r = Math.round(v * 100) / 100;
    return r.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  /** A quantity for ARITHMETIC that is shown: four places, trailing zeros trimmed.
   *
   *  Two places is right for reading a quantity and wrong for showing a multiplication. 10.98 ×
   *  $85.38 does not reach the $937.26 printed above it, and an estimator who checks the row by
   *  hand concludes the total is wrong. Four places is what the costs themselves are held to. */
  function qty4(n) {
    var v = num(n);
    if (v === null) return "—";
    return (Math.round(v * 1e4) / 1e4).toLocaleString("en-US", { maximumFractionDigits: 4 });
  }

  /** A price for arithmetic that is shown: up to four places, trailing zeros trimmed.
   *
   *  Kyle's per-gallon prices are $85.3827 and $79.7574. Rounding them to the cent inside the
   *  working makes "4 × $382.45" print $1,529.80 under a cost cell that says $1,529.79. */
  function price4(n) {
    var v = num(n);
    if (v === null) return "—";
    return "$" + (Math.round(v * 1e4) / 1e4).toLocaleString("en-US",
      { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }

  /** What to buy, in the vocabulary of the purchase.
   *
   *  Rounded up it names the PACKS, because "3 × 5 Gallon" is what goes on an order and "15
   *  Gallon" is not — the pack size is the thing that made it three. Not rounded it names single
   *  units, because that is the point of the checkbox being off. */
  function qtyLabel(row) {
    if (!row || !row.ok || !row.priced) return "—";
    // Unit abbreviations don't pluralise — Kyle's sheet writes "SF/Gal" and "SF/Kit", so
    // "11 Gal" is the vocabulary already in use. "11 Gals" would be our invention.
    var unit = (row.item && row.item.unit) || "unit";
    if (!row.roundup) return qtyText(row.needed) + " " + unit;
    if (row.buy_qty === 1) return qtyText(row.packs) + " " + unit;
    return qtyText(row.packs) + " × " + qtyText(row.buy_qty) + " " + unit;
  }

  /** The arithmetic of a line, in words, for the row to show its own working. A wrong coverage or
   *  a waste factor somebody fat-fingered should be visible in the working rather than inferred
   *  from a total that looks slightly off. */
  function explain(row, area) {
    if (!row || !row.ok || !row.priced) return "";
    var a = num(area) || 0;
    var s = a.toLocaleString("en-US") + " ÷ " + row.coverage.toLocaleString("en-US");
    if (row.waste_pct) s += " +" + qtyText(row.waste_pct) + "%";
    // Four places, matching the cost working below it — the two lines describe the same quantity
    // and disagreeing with each other is worse than either being long.
    s += " = " + qty4(row.needed);
    // Only worth saying when rounding actually moved the number.
    if (row.roundup && Math.abs(row.units - row.needed) > 1e-9) {
      s += " → " + qtyText(row.units);
    }
    return s + " " + ((row.item && row.item.unit) || "unit");
  }

  /** How the cost was reached, stated so that it MULTIPLIES OUT to the cost shown beside it.
   *
   *  Two different sums, and which one ran is exactly what the Roundup? checkbox decides:
   *
   *      rounded up   packs × pack price
   *      fractional   units ÷ pack size × pack price
   *
   *  The fractional branch deliberately divides by the pack size rather than showing a per-unit
   *  price, because a pack price divided by its size is usually a repeating decimal: $89.99 for
   *  seven bags is $12.855714…/bag, and "1,680 × $12.86" prints $21,604.80 under a cost cell
   *  reading $21,597.60. Naming the pack price keeps every figure on the line exact. */
  function costWorking(row) {
    if (!row || !row.ok || !row.priced) return "";
    if (row.roundup) return qtyText(row.packs) + " × " + price4(row.pack_cost);
    if (row.buy_qty === 1) return qty4(row.needed) + " × " + price4(row.pack_cost);
    return qty4(row.needed) + " ÷ " + qtyText(row.buy_qty) + " × " + price4(row.pack_cost);
  }

  /** The POST body for a copy of a material. Every priced field comes across, so the copy does not
   *  price differently from the original. The three Phase 11 columns ride along ONLY for an admin
   *  (the server refuses them from anybody else) and ONLY when the source has them, so a database
   *  without those columns is never sent one. `divisions` is passed in already normalised. */
  function itemCopyBody(src, name, divisions, isAdmin) {
    src = src || {};
    var body = {
      name: name,
      unit: src.unit || "",
      buy_qty: src.buy_qty,
      unit_cost: src.unit_cost,
      coverage: src.coverage,
      waste_pct: src.waste_pct,
      roundup: src.roundup,
      vendor: src.vendor || "",
      divisions: divisions,
    };
    if (isAdmin) {
      if (Array.isArray(src.price_breaks) && src.price_breaks.length) {
        body.price_breaks = src.price_breaks.map(function (b) {
          return { min_qty: b.min_qty, unit_cost: b.unit_cost };
        });
      }
      if (num(src.bulk_cost) !== null && num(src.bulk_cost) > 0) body.bulk_cost = src.bulk_cost;
      if (src.coverage_basis) body.coverage_basis = src.coverage_basis;
    }
    return body;
  }

  /** WHAT A SEARCH POP-UP SAYS A MATERIAL COSTS (Hanz, 2026-10-12): the cost the Items tab shows,
   *  in words, per what it is bought in. `unit_cost` is what ONE PURCHASE costs, so a 5 Gallon pail
   *  reads "$120.00 per 5 Gallon" and a single-unit material "$1,200.00 per Gallon". No cost in the
   *  library (blank, or 0, which the Items tab files under "no cost") is "No price set", never $0. */
  function materialPriceText(item) {
    var cost = num((item || {}).unit_cost);
    if (cost === null || cost <= 0) return "No price set";
    var unit = String((item || {}).unit || "").trim() || "unit";
    var pack = buyQty(item);
    return money(cost) + " per " + (pack === 1 ? "" : qtyText(pack) + " ") + unit;
  }

  /** The area an assembly is priced at when it has to be shown as "per SF" with no job to measure:
   *  the Items & Assemblies page's own default for its area box, so the pop-up and that page quote
   *  the same figure. Roundup moves the answer with the area, which is why it is stated once. */
  var REFERENCE_AREA = 1000;

  /** What a search pop-up says an ASSEMBLY costs: priceAssembly's own per-unit answer at the
   *  reference area, per the assembly's unit (SF unless it is LF, the library's own reading).
   *  Not a second formula: the number is `priceAssembly(...).per_unit`. An assembly nothing can
   *  price (no lines, a line with no cost or coverage) is "No price set", never $0.
   *
   *  THREE WAYS A QUOTED FIGURE COULD MISLEAD, each closed here:
   *   - ONE LINE CANNOT PRICE (deleted material, no coverage, or a line not filled in): the other
   *     lines' sum is an understated figure that looks clean, so the whole assembly is "No price
   *     set". `per_unit` alone cannot say this; it only goes null when NO line prices.
   *   - EVERYTHING PRICES AT $0: free is not a price. A $0 material already reads "No price set"
   *     (materialPriceText), so the assembly built from it must agree.
   *   - ROUNDUP MAKES THE FIGURE DEPEND ON THE AREA: a kit bought whole is $1.20/SF at 1,000 SF and
   *     $0.72/SF at 10,000. When a second area gives a different answer the text names the area it
   *     was worked at, instead of quoting a number that matches no real bid. */
  function assemblyPriceText(asm, items) {
    var priced = priceAssembly(asm, items, REFERENCE_AREA);
    var per = priced.per_unit;
    if (per === null || per === undefined || !(per > 0)) return "No price set";
    for (var i = 0; i < priced.rows.length; i++) {
      if (!priced.rows[i].priced) return "No price set";
    }
    var unit = String((asm || {}).unit || "").trim().toUpperCase() === "LF" ? "LF" : "SF";
    var text = money(per) + " per " + unit;
    var other = priceAssembly(asm, items, REFERENCE_AREA * 10).per_unit;
    // A few percent is ordinary rounding noise every assembly has; only a real swing earns the words.
    if (other === null || other === undefined || Math.abs(other - per) > per * 0.05) {
      text += " at " + qtyText(REFERENCE_AREA) + " " + unit;
    }
    return text;
  }

  return {
    itemCopyBody: itemCopyBody,
    num: num, findItem: findItem, priceLine: priceLine, priceAssembly: priceAssembly,
    money: money, perUnit: perUnit, explain: explain,
    wastePct: wastePct, buyQty: buyQty, qtyText: qtyText, qty4: qty4, price4: price4,
    qtyLabel: qtyLabel, costWorking: costWorking,
    coverageBasis: coverageBasis, areaFor: areaFor, priceBreaks: priceBreaks, breakAt: breakAt,
    pricePool: pricePool, poolId: poolId, allocate: allocate, itemsForBid: itemsForBid,
    materialPriceText: materialPriceText, assemblyPriceText: assemblyPriceText,
    REFERENCE_AREA: REFERENCE_AREA,
  };
});
