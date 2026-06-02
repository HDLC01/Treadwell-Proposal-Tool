"""Accuracy lock for the 5.7-recipe pricing engine.

These values were reconciled to the dollar against Kyle's
`estimate sheet - 5.7.xlsx` (via the `formulas` Excel engine). If a recipe
or the math drifts, these break — that's the point. The canonical case is:
2 epoxy systems (MACRO Flake 12,000 sf + Dur-A-Gard 4,000 sf), bulk discount
ON, one $825 extra material, Johnson County remodel (7.975%).
"""
import math

import pricing


def approx(a, b, tol=1.0):
    return abs(float(a) - float(b)) <= tol


# ── individual systems (bulk pricing) ─────────────────────────────────
def test_macro_flake_bulk_material():
    r = pricing.compute_system("MACRO Flake Single Broadcast", 12000, bulk_discount=True)
    assert r["found"] is True
    assert approx(r["material"], 18925, 1)


def test_dur_a_gard_bulk_material():
    r = pricing.compute_system("Dur-A-Gard", 4000, bulk_discount=True)
    assert r["found"] is True
    assert approx(r["material"], 5081, 1)


def test_unknown_system_returns_not_found():
    r = pricing.compute_system("No Such System", 1000)
    assert not r.get("found")
    assert r.get("material", 0) in (0, 0.0)


def test_more_sf_costs_more():
    small = pricing.compute_system("MACRO Flake Single Broadcast", 1000)["material"]
    big = pricing.compute_system("MACRO Flake Single Broadcast", 10000)["material"]
    assert big > small


# ── shipping/escalation tiers (sheet B42) ─────────────────────────────
def test_shipping_escalation_tiers():
    assert approx(pricing.shipping_escalation_pct(4000), 0.15, 1e-9)   # <=5000
    assert approx(pricing.shipping_escalation_pct(8000), 0.11, 1e-9)   # <=10000
    assert approx(pricing.shipping_escalation_pct(20000), 0.09, 1e-9)  # else


# ── GP margin tiers (sheet B73) ───────────────────────────────────────
def test_gp_pct_tiers():
    assert pricing._gp_pct(5000) == 0.52
    assert pricing._gp_pct(10000) == 0.45
    assert pricing._gp_pct(20000) == 0.35
    assert pricing._gp_pct(30000) == 0.32
    assert pricing._gp_pct(40000) == 0.30


# ── roll-up (D40 -> D43), incl. extras ────────────────────────────────
def _two_systems():
    s1 = pricing.compute_system("MACRO Flake Single Broadcast", 12000, bulk_discount=True)
    s2 = pricing.compute_system("Dur-A-Gard", 4000, bulk_discount=True)
    return [s1, s2]


def test_rollup_two_systems_bulk_material_total():
    roll = pricing.roll_up(_two_systems(), patch_sf=16000)
    assert approx(roll["material_total"], 27912, 2)


def test_extras_add_exactly_to_material_sub():
    base = pricing.roll_up(_two_systems(), patch_sf=16000)
    withx = pricing.roll_up(_two_systems(), patch_sf=16000, extras_total=825)
    # extras feed D40's SUM(D18:D39) — exact, no rounding surprises at this scale
    assert withx["material_sub"] - base["material_sub"] == 825
    assert approx(withx["material_total"], 28811, 2)


# ── full Total Base Bid (D88) ─────────────────────────────────────────
def _full_bid(remodel_rate):
    roll = pricing.roll_up(_two_systems(), patch_sf=16000, extras_total=825)
    return pricing.compute_full_bid(
        roll["material_total"], 16000,
        taxable=True, remodel=True, remodel_rate=remodel_rate,
    )


def test_full_bid_accurate_county_rate():
    fb = _full_bid(0.07975)   # Johnson County: KS 6.5% + county 1.475%
    assert approx(fb["total_base_bid"], 72369, 1)
    assert approx(fb["remodel_tax"], 3016, 1)
    assert approx(fb["sales_tax"], 2730, 1)
    assert fb["gp_pct"] == 0.30


def test_full_bid_matches_sheet_flat_10pct():
    # The sheet hardcodes 10% remodel; engine must reproduce it to the dollar.
    fb = _full_bid(0.10)
    assert approx(fb["total_base_bid"], 73135, 1)
    assert approx(fb["remodel_tax"], 3782, 1)


def test_remodel_off_means_no_remodel_tax():
    roll = pricing.roll_up(_two_systems(), patch_sf=16000)
    fb = pricing.compute_full_bid(roll["material_total"], 16000, taxable=True, remodel=False)
    assert fb["remodel_tax"] == 0


def test_non_taxable_means_no_sales_tax():
    roll = pricing.roll_up(_two_systems(), patch_sf=16000)
    fb = pricing.compute_full_bid(roll["material_total"], 16000, taxable=False)
    assert fb["sales_tax"] == 0
