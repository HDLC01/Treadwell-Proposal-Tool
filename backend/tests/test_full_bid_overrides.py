"""compute_full_bid overrides: the estimator's grid edits (hard-bid %, GP %,
crew/days, demo SF) must flow into the bid, while an un-edited job is unchanged.

These guard the fix that lets the tool's Computed Bid (and the proposal) match
Kyle's sheet when he hand-types a competitive hard-bid discount / fewer days /
demo SF, instead of being stuck on the template defaults.
"""
import pricing

MAT, SF = 10000, 10000


def test_no_override_matches_default_behavior():
    # No hard_bid flag, no hard_bid_pct -> no discount (unchanged).
    b = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)])
    assert b["hard_bid"] == 0


def test_hard_bid_pct_override_applies_and_lowers_bid():
    base = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)])
    disc = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)], hard_bid_pct=-0.17)
    assert disc["hard_bid"] < 0
    assert disc["total_base_bid"] < base["total_base_bid"]


def test_explicit_pct_beats_tiered_flag():
    # Big job: tier would be -0.04; an explicit -0.17 override must win.
    tier = pricing.compute_full_bid(200000, 50000, crews=[(6, 10)], hard_bid=True)
    over = pricing.compute_full_bid(200000, 50000, crews=[(6, 10)], hard_bid=True,
                                    hard_bid_pct=-0.17)
    assert over["hard_bid"] < tier["hard_bid"] <= 0


def test_gp_pct_override():
    lo = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)], gp_pct=0.30)
    hi = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)], gp_pct=0.52)
    assert hi["gp_markup"] > lo["gp_markup"]


def test_crews_and_demo_change_costs():
    fewer_days = pricing.compute_full_bid(MAT, SF, crews=[(3, 4)])
    more_days = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)])
    assert fewer_days["install_labor"] < more_days["install_labor"]
    no_demo = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)], demo_sf=0)
    demo = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)], demo_sf=10000)
    assert demo["tooling"] > no_demo["tooling"]


def test_soft_pct_override():
    a = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)], soft_pct=0.10)
    b = pricing.compute_full_bid(MAT, SF, crews=[(3, 5)], soft_pct=0.13)
    assert b["soft_costs"] > a["soft_costs"]
