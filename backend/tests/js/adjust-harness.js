"use strict";
/* THE ESTIMATOR'S OVERRIDES, every edge (Hanz, 2026-10-16: "all the edge cases").
 *
 *   node adjust-harness.js <frontend dir>
 *
 * Runs js/bid-model.js's box readers (pctFraction, normalizeAdjust, adjustProblems, chainAdjust, materialAdjust,
 * materialOnlyAdjust), js/bid-engine.js priceChain with `adjust`, and js/library-core.js itemsForBid over a table of
 * inputs, and prints every answer as one JSON line. test_v2_adjust.py holds each one.
 */
const path = require("path");
const FRONTEND = path.resolve(process.argv[2]);
const B = require(path.join(FRONTEND, "js", "bid-model.js"));
const E = require(path.join(FRONTEND, "js", "bid-engine.js"));
const L = require(path.join(FRONTEND, "js", "library-core.js"));

const out = {};

// ── what a box reads as ────────────────────────────────────────────────────────────────────────────────────────────
const BOXES = ["3", "3%", " 3 % ", "-3", "+3", "3.5", ".5", "0", "0%", "", "   ", "abc", "3%%", "1e2", "3,5", "$3",
  "100", "99.99999999999", "99.999", 3, 0, -3, NaN, Infinity, null, undefined, true, {}, []];
out.pct = BOXES.map((v) => [String(v), B.pctFraction(v)]);

// ── what the model keeps ───────────────────────────────────────────────────────────────────────────────────────────
out.normalize = {
  none: B.normalizeAdjust(undefined), notObject: B.normalizeAdjust("3"), list: B.normalizeAdjust([1]),
  allBlank: B.normalizeAdjust({ gp_pct: "", ship_pct: "  ", bulk: false }),
  junkKeys: B.normalizeAdjust({ junk: "1", __proto__: { gp_pct: "50" }, constructor: "x", gp_pct: "30" }),
  bulkNotTrue: B.normalizeAdjust({ bulk: "true" }), bulkTrue: B.normalizeAdjust({ bulk: true }),
  longText: B.normalizeAdjust({ gp_pct: "1".repeat(50) }).gp_pct.length,
  numbersKept: B.normalizeAdjust({ gp_pct: 30, discount_amt: 1500 }),
  objectValueDropped: B.normalizeAdjust({ gp_pct: { a: 1 } }),
};
out.problems = {
  bad: B.adjustProblems({ gp_pct: "100", super_pct: "abc", soft_pct: "-1", ship_pct: "99.99999999999",
                          discount_pct: "-150", discount_amt: "lots", supplier_pct: "120", polycrete_pct: "x" }),
  fine: B.adjustProblems({ gp_pct: "0", super_pct: "3", soft_pct: "13", ship_pct: "6", discount_pct: "-25",
                           discount_amt: "$1,500", supplier_pct: "20", polycrete_pct: "0" }),
  none: B.adjustProblems(undefined),
};
out.chain = {
  mixed: B.chainAdjust({ discount_pct: "-3", ship_pct: "6", gp_pct: "100", super_pct: "x", discount_amt: "$1,254" }),
  zeros: B.chainAdjust({ gp_pct: "0", ship_pct: "0", discount_pct: "0", discount_amt: "0" }),
  edge: B.chainAdjust({ gp_pct: "99.99999999999" }),
  materialKeysIgnored: B.chainAdjust({ supplier_pct: "20", bulk: true }),
};
out.material = {
  supplierOnly: B.materialAdjust({ supplier_pct: "20" }),
  polycreteZero: B.materialAdjust({ supplier_pct: "20", polycrete_pct: "0" }),
  polycreteOwn: B.materialAdjust({ supplier_pct: "20", polycrete_pct: "10" }),
  polycreteBad: B.materialAdjust({ supplier_pct: "20", polycrete_pct: "x" }),
  bulk: B.materialAdjust({ bulk: true }),
  nothing: B.materialAdjust(undefined),
  onlyMaterial: B.materialOnlyAdjust({ gp_pct: "30", supplier_pct: "20", bulk: true }),
  onlyMarkup: B.materialOnlyAdjust({ gp_pct: "30" }),
};

// ── the chain ──────────────────────────────────────────────────────────────────────────────────────────────────────
const JOB = { material: 10000, labor: 5000, tooling: 500, travel: 0, sf: 5000, contingency: 0, fees: 0, remodel_rate: 0.075,
  conditions: { local: true, taxable: true, remodel_tax: true, prevailing_wage: false } };
const price = (adjust, extra) => E.priceChain("epoxy", Object.assign({}, JOB, extra || {}, adjust === undefined ? {} : { adjust: adjust }));
const keep = (r) => ({ ship_pct: r.ship_pct, shipping: r.shipping, gp_pct: r.gp_pct, gp: r.gp, hard_bid: r.hard_bid,
  hard_bid_pct: r.hard_bid_pct, super_pct: r.super_pct, super_pto: r.super_pto, soft_pct: r.soft_pct,
  soft_costs: r.soft_costs, remodel_tax: r.remodel_tax, bond: r.bond, total: r.total, refused: r.discount_refused });
out.engine = {
  none: keep(price(undefined)), empty: keep(price({})),
  ship6: keep(price({ ship_pct: 0.06 })), ship0: keep(price({ ship_pct: 0 })),
  gp0: keep(price({ gp_pct: 0 })), gp30: keep(price({ gp_pct: 0.30 })),
  super0: keep(price({ super_pct: 0 })), soft10: keep(price({ soft_pct: 0.10 })),
  pct3: keep(price({ discount_pct: 0.03 })), pctNeg3: keep(price({ discount_pct: -0.03 })),
  pct0: keep(price({ discount_pct: 0 })), amt1500: keep(price({ discount_amt: 1500 })), amtNeg: keep(price({ discount_amt: -1500 })),
  amt0: keep(price({ discount_amt: 0 })), bothAmtWins: keep(price({ discount_pct: 0.03, discount_amt: 1500 })),
  amtHuge: keep(price({ discount_amt: 1000000 })), pctNearAll: keep(price({ discount_pct: 0.99 })),
  negContingency: keep(price({ discount_pct: 0.03 }, { contingency: -2000 })),
  remodelOff: keep(price({ discount_pct: 0.03 }, { conditions: { local: true, taxable: true, remodel_tax: false } })),
};
out.throws = [{ gp_pct: 1 }, { gp_pct: -0.1 }, { ship_pct: "abc" }, { discount_pct: 1.2 }, { super_pct: Infinity }, "3"]
  .map((a) => { try { price(a); return null; } catch (e) { return e.name + ": " + e.message; } });
// a profile with no hard-bid rule (the v2 Polish chain) and one with it
out.polishProfiles = ["polish-legacy", "polish-rev2", "polish-rev3"].map((id) => {
  const r = E.priceChain(id, Object.assign({}, JOB, { adjust: { discount_pct: 0.03 } }));
  const base = E.priceChain(id, JOB);
  return { id: id, hard_bid: r.hard_bid, totalDropped: base.total - r.total, remodelDropped: base.remodel_tax - r.remodel_tax };
});
// the sheet's own hard-bid rule still fires with no override, and an override replaces it
out.hardBidRule = {
  rule: E.priceChain("epoxy", Object.assign({}, JOB, { material: 40000, labor: 30000,
    conditions: Object.assign({}, JOB.conditions, { hard_bid: true }) })).hard_bid_pct,
  overridden: E.priceChain("epoxy", Object.assign({}, JOB, { material: 40000, labor: 30000, adjust: { discount_pct: 0.10 },
    conditions: Object.assign({}, JOB.conditions, { hard_bid: true }) })).hard_bid_pct,
};

// ── the library as a bid buys it ───────────────────────────────────────────────────────────────────────────────────
const ITEMS = [
  { id: "sw", vendor: "Sherwin-Williams", unit_cost: 106, coverage: 100 },
  { id: "sw2", vendor: "sherwin williams ", unit_cost: 53, coverage: 100 },
  { id: "pc", vendor: "Poly-Crete", unit_cost: 212, bulk_cost: 159, coverage: 55,
    price_breaks: [{ min_qty: 10, unit_cost: 180 }, { min_qty: 50, unit_cost: 150 }] },
  { id: "flake", vendor: null, unit_cost: 90, bulk_cost: 80, coverage: 266.667 },
  { id: "other", vendor: "Torginol", unit_cost: 10, coverage: 1 },
  null,
];
const view = (items) => items.map((i) => i && { id: i.id, unit_cost: +Number(i.unit_cost).toFixed(6),
  bulk_cost: i.bulk_cost === undefined ? null : +Number(i.bulk_cost).toFixed(6), breaks: i.price_breaks || null,
  bulk_applied: !!i.bulk_applied });
out.items = {
  sameArray: L.itemsForBid(ITEMS, B.materialAdjust({})) === ITEMS,
  sameArrayNoAdj: L.itemsForBid(ITEMS, null) === ITEMS,
  supplier20: view(L.itemsForBid(ITEMS, B.materialAdjust({ supplier_pct: "20" }))),
  polycrete10: view(L.itemsForBid(ITEMS, B.materialAdjust({ supplier_pct: "20", polycrete_pct: "10" }))),
  // library-core keeps its bulk pricing for the library's own use; v2 no longer asks for it (materialAdjust's bulk is
  // always false since 2026-10-20), so these hand it the switch directly
  bulk: view(L.itemsForBid(ITEMS, Object.assign(B.materialAdjust({}), { bulk: true }))),
  bulkAndDiscount: view(L.itemsForBid(ITEMS, Object.assign(B.materialAdjust({ supplier_pct: "20" }), { bulk: true }))),
  originalUntouched: JSON.stringify(ITEMS[2]),
  overDiscount: view(L.itemsForBid(ITEMS, { discounts: { "Sherwin-Williams": 1.06 }, escalation: 0.06 }))[0],
};
console.log(JSON.stringify(out));
