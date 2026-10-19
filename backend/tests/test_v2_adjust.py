"""The estimator's overrides on Estimating Tool v2's Review step: every edge (Hanz, 2026-10-16: "all the edge cases").

What Kyle types over his own sheet's rules, one set per section, approved after a scan of 41 real bids made from
2026-08-16 to 10-16 (a discount on 21, Bulk Discount on 11, soft or super % on 4, GP and shipping on 1 each, a supplier
discount on the October job): Discount % or $, Shipping / GP / Superintendent / Soft costs %, and on an Epoxy section
the supplier and Poly-Crete discounts and the Bulk Discount switch.

THE RULES HELD HERE
  * A box is read one way everywhere: "3", "3%", " 3 % ", 3 are 3%; "abc", "3%%", "1e2", "$3" are nothing. A box that
    is typed but unusable is LEFT OUT of the price (the rule stands) and named, never priced as zero, never a crash.
  * The check and the figure the chain is handed are the same number (99.99999999999 is 100%, refused, not a crash).
  * Blank is the rule: a section with nothing typed prices exactly as before, and saves no `adjust` key.
  * A discount is its size, whichever way signed; the $ wins over the %; one bigger than the labor and markup it comes
    off is refused (no negative remodel tax, no negative total); it is inside super, soft, remodel and bond, as in the
    sheet; it replaces the sheet's own hard-bid rule and works on a profile that has none.
  * The supplier discount comes off the LIST price, keeping the library's 6% escalation (Kyle's U140): cost x
    (1.06 - d) / 1.06. It touches only the materials of its vendor (matched on letters, so "sherwin williams " is
    Sherwin-Williams), the Poly-Crete box follows it when blank, and Bulk buys at the bulk cost, dropping only the price
    breaks dearer than it. The library's own rows are never mutated, and nothing typed gives back the same array.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "adjust-harness.js"
SCRATCH = ["js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js", "js/library-core.js", "js/work-types.js",
           "js/markup-core.js", "js/excel-math.js"]


def _run(frontend):
    require_node()
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    return _run(FRONTEND)


# ── 1. what a box reads as ──────────────────────────────────────────────────────────────────────────────────────────
def test_a_box_reads_the_same_way_whatever_was_typed(ran):
    got = dict(ran["pct"][:20])
    assert got["3"] == got["3%"] == got[" 3 % "] == got["+3"] == 0.03
    assert got["-3"] == -0.03 and got["3.5"] == 0.035 and got[".5"] == 0.005
    assert got["0"] == got["0%"] == 0
    for junk in ("", "   ", "abc", "3%%", "1e2", "3,5", "$3"):
        assert got[junk] is None, junk
    assert got["100"] == 1 and got["99.99999999999"] == 1, "the check and the chain read the same rounded figure"
    assert dict(ran["pct"])["NaN"] is None and dict(ran["pct"])["Infinity"] is None
    assert all(v is None for k, v in ran["pct"][24:])  # null, undefined, true, {}, []


def test_the_model_keeps_only_known_keys_as_typed_and_nothing_for_a_blank_set(ran):
    n = ran["normalize"]
    assert n["none"] is None and n["notObject"] is None and n["list"] is None
    assert n["allBlank"] is None, "a section with nothing typed saves no adjust key"
    assert n["junkKeys"] == {"gp_pct": "30"}, "unknown keys and a __proto__ trick are dropped"
    assert n["bulkNotTrue"] is None and n["bulkTrue"] == {"bulk": True}
    assert n["longText"] == 32
    assert n["numbersKept"] == {"gp_pct": 30, "discount_amt": 1500}
    assert n["objectValueDropped"] is None


def test_every_unusable_box_is_named_and_a_usable_one_never_is(ran):
    bad = {p["key"]: p["text"] for p in ran["problems"]["bad"]}
    assert set(bad) == {"gp_pct", "super_pct", "soft_pct", "ship_pct", "discount_pct", "discount_amt",
                        "supplier_pct", "polycrete_pct"}
    assert bad["super_pct"].startswith("not a number") and bad["gp_pct"].startswith("must be from 0 to under 100%")
    assert bad["ship_pct"].startswith("must be"), "99.99999999999% is 100%, named rather than crashing the page"
    assert bad["discount_amt"].startswith("not a dollar figure")
    assert ran["problems"]["fine"] == [] and ran["problems"]["none"] == []


def test_the_chain_is_handed_fractions_and_never_an_unusable_box(ran):
    c = ran["chain"]
    assert c["mixed"] == {"discount_pct": 0.03, "ship_pct": 0.06, "discount_amt": 1254}
    assert c["zeros"] == {"discount_pct": 0, "ship_pct": 0, "gp_pct": 0, "discount_amt": 0}
    assert c["edge"] == {}, "a GP that rounds to 100% is left out, not handed to the chain"
    assert c["materialKeysIgnored"] == {}


def test_the_material_boxes_follow_kyles_two_discount_cells(ran):
    m = ran["material"]
    assert m["supplierOnly"]["discounts"] == {"Sherwin-Williams": 0.2, "Poly-Crete": 0.2}, "C41 = B41 when blank"
    assert m["polycreteZero"]["discounts"] == {"Sherwin-Williams": 0.2}, "a typed 0 is no Poly-Crete discount"
    assert m["polycreteOwn"]["discounts"] == {"Sherwin-Williams": 0.2, "Poly-Crete": 0.1}
    assert m["polycreteBad"]["discounts"] == {"Sherwin-Williams": 0.2}, "an unusable Poly-Crete box is left out"
    assert m["bulk"]["bulk"] is True and m["nothing"] == {"bulk": False, "discounts": {}, "escalation": 0.06}
    assert m["onlyMaterial"] == {"supplier_pct": "20", "bulk": True} and m["onlyMarkup"] is None


# ── 2. the chain ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_nothing_typed_is_the_rule_exactly(ran):
    e = ran["engine"]
    assert e["none"] == e["empty"] == e["pct0"] | {"refused": False} == e["amt0"] | {"hard_bid_pct": 0}


@pytest.mark.parametrize("case,key,want", [
    ("ship6", "ship_pct", 0.06), ("ship0", "shipping", 0), ("gp0", "gp", 0), ("gp30", "gp_pct", 0.30),
    ("super0", "super_pto", 0), ("soft10", "soft_pct", 0.10)])
def test_a_typed_rate_replaces_the_rule_and_moves_the_total(ran, case, key, want):
    e = ran["engine"]
    assert e[case][key] == want
    assert e[case]["total"] != e["none"]["total"]


def test_the_discount_is_its_size_and_the_dollars_win(ran):
    e = ran["engine"]
    assert e["pct3"] == e["pctNeg3"], "3 and -3 are both 3% off"
    assert e["pct3"]["hard_bid"] == -811 and e["pct3"]["hard_bid_pct"] == -0.03
    assert e["amt1500"] == e["amtNeg"] == e["bothAmtWins"]
    assert e["amt1500"]["hard_bid"] == -1500 and e["amt1500"]["hard_bid_pct"] is None
    assert e["amt0"]["hard_bid"] == 0, "a typed $0 is no discount, and never -0"


def test_the_discount_is_inside_super_soft_and_the_remodel_tax(ran):
    e = ran["engine"]
    for k in ("super_pto", "soft_costs", "remodel_tax", "total"):
        assert e["pct3"][k] < e["none"][k], k
    assert e["remodelOff"]["remodel_tax"] == 0
    assert e["negContingency"]["total"] < e["pct3"]["total"]


def test_a_discount_bigger_than_the_labor_and_markup_is_refused_not_priced(ran):
    e = ran["engine"]
    for case in ("amtHuge", "pctNearAll"):
        assert e[case]["refused"] is True, case
        assert e[case]["hard_bid"] == 0 and e[case]["total"] == e["none"]["total"], case
        assert e[case]["remodel_tax"] >= 0 and e[case]["total"] > 0, case


def test_an_override_the_chain_cannot_use_throws_with_its_name(ran):
    t = ran["throws"]
    assert all(x and x.startswith("BidEngineError") for x in t), t
    assert "gp_pct" in t[0] and "ship_pct" in t[2] and "Infinity" in t[4]


def test_the_discount_works_on_every_polish_profile_and_replaces_the_hard_bid_rule(ran):
    for p in ran["polishProfiles"]:
        assert p["hard_bid"] < 0 and p["totalDropped"] > 0 and p["remodelDropped"] > 0, p
    assert ran["hardBidRule"] == {"rule": -0.04, "overridden": -0.1}


# ── 3. the library as the bid buys it ───────────────────────────────────────────────────────────────────────────────
def _by_id(rows):
    return {r["id"]: r for r in rows if r}


def test_nothing_typed_buys_the_library_as_it_is(ran):
    assert ran["items"]["sameArray"] is True and ran["items"]["sameArrayNoAdj"] is True


def test_the_supplier_discount_comes_off_the_list_price_of_its_vendors_only(ran):
    s = _by_id(ran["items"]["supplier20"])
    assert s["sw"]["unit_cost"] == pytest.approx(106 * 0.86 / 1.06) == 86
    assert s["sw2"]["unit_cost"] == 43, "the vendor is matched on its letters"
    assert s["pc"]["unit_cost"] == 172 and s["pc"]["bulk_cost"] == pytest.approx(159 * 0.86 / 1.06)
    assert s["pc"]["breaks"][1]["unit_cost"] == pytest.approx(150 * 0.86 / 1.06)
    assert s["flake"]["unit_cost"] == 90 and s["other"]["unit_cost"] == 10, "no vendor, or another vendor: no discount"
    p = _by_id(ran["items"]["polycrete10"])
    assert p["sw"]["unit_cost"] == 86 and p["pc"]["unit_cost"] == pytest.approx(212 * 0.96 / 1.06)


def test_bulk_buys_at_the_bulk_cost_and_keeps_only_the_cheaper_breaks(ran):
    b = _by_id(ran["items"]["bulk"])
    assert b["pc"]["unit_cost"] == 159 and b["pc"]["bulk_applied"] is True
    assert b["pc"]["breaks"] == [{"min_qty": 50, "unit_cost": 150}], "the $180 break is dearer than bulk and is dropped"
    assert b["flake"]["unit_cost"] == 80, "bulk is not a vendor's: any material with a bulk cost"
    assert b["sw"]["unit_cost"] == 106 and b["sw"]["bulk_applied"] is False
    bd = _by_id(ran["items"]["bulkAndDiscount"])
    assert bd["pc"]["unit_cost"] == pytest.approx(159 * 0.86 / 1.06) and bd["flake"]["unit_cost"] == 80


def test_the_librarys_rows_are_never_changed_and_a_discount_of_everything_is_ignored(ran):
    assert '"unit_cost":212' in ran["items"]["originalUntouched"] and '"price_breaks":[{"min_qty":10' in ran["items"]["originalUntouched"]
    assert ran["items"]["overDiscount"]["unit_cost"] == 106


# ── 4. the facts go red when the code changes ───────────────────────────────────────────────────────────────────────
MUTATIONS = {
    "the discount is not refused when it is too big": (
        "js/bid-engine.js", "      if (hard_bid !== 0 && -hard_bid > labor + escalation + burden + tooling + travel + gp) {",
        "      if (false) {", lambda r: r["engine"]["amtHuge"]["refused"] is False),
    "the dollars do not win": (
        "js/bid-engine.js", '      if (has1("discount_amt")) {', "      if (false) {",
        lambda r: r["engine"]["bothAmtWins"]["hard_bid"] != -1500),
    "the box is checked unrounded": (
        "js/bid-model.js", "    return parseFloat((Number(t) / 100).toPrecision(12));", "    return Number(t) / 100;",
        lambda r: dict(r["pct"])["99.99999999999"] != 1),
    "Poly-Crete does not follow the supplier box": (
        "js/bid-model.js", '    var pc = Object.prototype.hasOwnProperty.call(a, "polycrete_pct") ? off("polycrete_pct") : sw;',
        '    var pc = off("polycrete_pct");', lambda r: "Poly-Crete" not in r["material"]["supplierOnly"]["discounts"]),
    "a dearer break survives bulk": (
        "js/library-core.js", "          .filter(function (b) { return !useBulk || b.unit_cost < bulkCost; })",
        "          .filter(function (b) { return true; })", lambda r: len(_by_id(r["items"]["bulk"])["pc"]["breaks"]) != 1),
    "the vendor is matched exactly": (
        "js/library-core.js", '    var vkey = function (v) { return String(v == null ? "" : v).toLowerCase().replace(/[^a-z]/g, ""); };',
        '    var vkey = function (v) { return String(v); };', lambda r: _by_id(r["items"]["supplier20"])["sw2"]["unit_cost"] != 43),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_facts_go_red_when_the_code_changes(tmp_path, name):
    rel, old, new, noticed = MUTATIONS[name]
    frontend = break_source(tmp_path, rel, old.strip(), new.strip())
    copy_unmodified(frontend, SCRATCH)
    assert noticed(_run(frontend)), "the facts did not notice: " + name
