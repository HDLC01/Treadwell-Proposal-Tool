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
  function wastePct(line) {
    var v = num((line || {}).waste_pct);
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

  /** Price one line against an area.
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
  function priceLine(line, items, area) {
    line = line || {};
    var item = findItem(items, line.item_id || line.item);
    if (!item) return { ok: false, reason: "missing_item", qty: 0, cost: 0 };

    // Coverage lives on the LINE (Kyle's sheet keeps it there), falling back to the item's
    // default. The same product is used at different coverages in different systems.
    var cov = num(line.coverage);
    if (cov === null) cov = num(item.coverage);
    if (cov === null || cov <= 0) return { ok: false, reason: "no_coverage", qty: 0, cost: 0 };

    var packCost = num(item.unit_cost);
    if (packCost === null || packCost < 0) return { ok: false, reason: "no_cost", qty: 0, cost: 0 };

    var pack = buyQty(item);
    var waste = wastePct(line);
    // Absent means yes: CEIL is what these lines were priced with, and the page has promised
    // "you cannot buy 3.7 kits" since it shipped.
    var roundup = (line.roundup === undefined || line.roundup === null) ? true : !!line.roundup;

    var base = { ok: true, coverage: cov, waste_pct: waste, roundup: roundup,
                 buy_qty: pack, pack_cost: packCost, unit_price: packCost / pack, item: item };

    var a = num(area);
    if (a === null || a <= 0) {
      // No area yet is not an error — it is the state the screen opens in.
      return Object.assign(base, { priced: false, qty: 0, cost: 0, needed: 0, units: 0,
                                   packs: null });
    }

    var needed = (a / cov) * (1 + waste / 100);
    if (roundup) {
      // CEIL, but not on a float's rounding error. 27,500 ÷ 275 × 1.10 is 110.00000000000001 in
      // IEEE-754, and a bare ceil() there buys a 111th gallon nobody needs — on exactly the round
      // numbers an estimator checks by hand. Twelve significant figures is far finer than any
      // coverage anybody types and coarser than the error.
      var packs = Math.ceil(parseFloat((needed / pack).toPrecision(12)));
      return Object.assign(base, { priced: true, needed: needed, packs: packs,
                                   units: packs * pack, qty: packs, cost: packs * packCost });
    }
    // Fractional: buy exactly what is needed, at the price of one unit rather than one pack.
    return Object.assign(base, { priced: true, needed: needed, packs: null,
                                 units: needed, qty: needed,
                                 cost: needed * (packCost / pack) });
  }

  /** Price a whole assembly. `lines[i]` in, `rows[i]` out — same order, same length, so the
   *  caller can render them side by side without matching anything up. */
  function priceAssembly(assembly, items, area) {
    var lines = (assembly && assembly.lines) || [];
    var rows = [], total = 0, priced = 0, broken = 0;
    for (var i = 0; i < lines.length; i++) {
      var r = priceLine(lines[i], items, area);
      rows.push(r);
      if (!r.ok) { broken += 1; continue; }
      if (r.priced) { total += r.cost; priced += 1; }
    }
    var a = num(area);
    return {
      rows: rows,
      total: total,
      // Only meaningful with an area. Reporting 0 would read as "free" rather than "unknown".
      per_unit: (a !== null && a > 0 && priced > 0) ? total / a : null,
      priced_lines: priced,
      broken_lines: broken,
    };
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
    s += " = " + qtyText(row.needed);
    // Only worth saying when rounding actually moved the number.
    if (row.roundup && Math.abs(row.units - row.needed) > 1e-9) {
      s += " → " + qtyText(row.units);
    }
    return s + " " + ((row.item && row.item.unit) || "unit");
  }

  /** How the cost was reached: packs at the pack price, or units at the unit price. Two different
   *  multiplications, and which one ran is exactly what the Roundup? checkbox decides. */
  function costWorking(row) {
    if (!row || !row.ok || !row.priced) return "";
    if (row.roundup) return qtyText(row.packs) + " × " + money(row.pack_cost);
    return qtyText(row.needed) + " × " + money(row.unit_price);
  }

  return {
    num: num, findItem: findItem, priceLine: priceLine, priceAssembly: priceAssembly,
    money: money, perUnit: perUnit, explain: explain,
    wastePct: wastePct, buyQty: buyQty, qtyText: qtyText, qtyLabel: qtyLabel,
    costWorking: costWorking,
  };
});
