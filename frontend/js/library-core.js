// Item Library pricing — pure functions, no DOM, no fetch.
// Externalized (CSP: no inline scripts). Do not add inline scripts.
//
// THE MODEL, and where it comes from.
//
// Taken from Kyle's estimate sheet ("Decorative Flake Systems / MACRO Flake Single
// Broadcast"). One measured area drives every line of an assembly:
//
//     qty  = CEIL(area / coverage)      whole gallons and kits get bought
//     line = qty * item unit cost
//     total = sum of the lines
//     price per unit of measure = total / area
//
// Reproduced against his printed sheet at 2,875 SF: OPF at 275 SF/Gal -> 11 Gal / $939.21,
// Glaze #4 at 125 -> 23 Gal / $1,834.42, Armor Top Satin at 775 SF/Kit -> 4 Kit / $1,529.79.
// Every line matches to the cent. Stack's `{MeasuredArea}/200` item formula is the same
// arithmetic, which is why one model serves both mental pictures.
//
// TWO DECISIONS WORTH KNOWING.
//
// 1. CEIL, not round. You cannot buy 3.71 kits, so a 2,875 SF floor takes 4 kits of a 775 SF
//    top coat. Rounding to nearest would under-buy on most jobs, and the estimate would be
//    short of material rather than merely mispriced.
//
// 2. The total sums UNROUNDED line costs, then rounds once for display. Adding the rounded
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

  /** Price one line against an area.
   *
   *  Returns `{ok: false, reason}` rather than throwing or defaulting to zero. A line whose
   *  material was deleted must be VISIBLE and must not contribute — pricing it at zero would
   *  quietly understate the assembly, which is the worst of the three options. */
  function priceLine(line, items, area) {
    line = line || {};
    var item = findItem(items, line.item_id || line.item);
    if (!item) return { ok: false, reason: "missing_item", qty: 0, cost: 0 };

    // Coverage lives on the LINE (Kyle's sheet keeps it there), falling back to the item's
    // default. The same product is used at different coverages in different systems.
    var cov = num(line.coverage);
    if (cov === null) cov = num(item.coverage);
    if (cov === null || cov <= 0) return { ok: false, reason: "no_coverage", qty: 0, cost: 0 };

    var cost = num(item.unit_cost);
    if (cost === null || cost < 0) return { ok: false, reason: "no_cost", qty: 0, cost: 0 };

    var a = num(area);
    if (a === null || a <= 0) {
      // No area yet is not an error — it is the state the screen opens in.
      return { ok: true, priced: false, qty: 0, cost: 0, coverage: cov, item: item };
    }

    var qty = Math.ceil(a / cov);
    return { ok: true, priced: true, qty: qty, cost: qty * cost,
             coverage: cov, unit_cost: cost, item: item };
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

  /** The arithmetic of a line, in words, for the row to show its own working. A wrong coverage
   *  should be visible in the working rather than inferred from a total that looks slightly
   *  off. */
  function explain(row, area) {
    if (!row || !row.ok || !row.priced) return "";
    var a = num(area) || 0;
    // Unit abbreviations don't pluralise — Kyle's sheet writes "SF/Gal" and "SF/Kit", so
    // "11 Gal" is the vocabulary already in use. "11 Gals" would be our invention.
    return a.toLocaleString("en-US") + " ÷ " + row.coverage.toLocaleString("en-US") +
           " → " + row.qty.toLocaleString("en-US") +
           " " + ((row.item && row.item.unit) || "unit");
  }

  return {
    num: num, findItem: findItem, priceLine: priceLine, priceAssembly: priceAssembly,
    money: money, perUnit: perUnit, explain: explain,
  };
});
