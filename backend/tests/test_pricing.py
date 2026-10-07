"""Accuracy lock for the 5.7-recipe pricing engine.

These values were reconciled to the dollar against Kyle's
`estimate sheet - 5.7.xlsx` (via the `formulas` Excel engine). If a recipe
or the math drifts, these break — that's the point. The canonical case is:
2 epoxy systems (MACRO Flake 12,000 sf + Dur-A-Gard 4,000 sf), bulk discount
ON, one $825 extra material, Johnson County remodel (7.975%).
"""
import math

import pytest

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
    """Figures moved on 2026-08-26 with Kyle's labor rate: $32.20 -> $33.00/hr for
    epoxy/polish/sealed. Every number here is downstream of that hour, so all three shifted
    together — and the sales tax did NOT, which is the check that the rate moved and the tax
    treatment did not."""
    fb = _full_bid(0.07975)   # Johnson County: KS 6.5% + county 1.475%
    assert approx(fb["total_base_bid"], 72562, 1)
    assert approx(fb["remodel_tax"], 3030, 1)
    assert approx(fb["sales_tax"], 2730, 1)
    assert fb["gp_pct"] == 0.30


def test_full_bid_matches_sheet_flat_10pct():
    """The sheet hardcodes 10% remodel; engine must reproduce it to the dollar.

    Re-pinned on 2026-08-26 for Kyle's $33.00/hr. What makes this test meaningful is that BOTH
    sides moved and by the same amount: the workbook's own rate cells (Epoxy!C47/C52 and the rest)
    and `pricing.compute_labor`'s default were changed in one commit. If only one had moved, the
    engine and the sheet would disagree — which is exactly what this test exists to catch, and why
    the number could not simply be relaxed to a wider tolerance."""
    fb = _full_bid(0.10)
    assert approx(fb["total_base_bid"], 73332, 1)
    assert approx(fb["remodel_tax"], 3800, 1)


def test_remodel_off_means_no_remodel_tax():
    roll = pricing.roll_up(_two_systems(), patch_sf=16000)
    fb = pricing.compute_full_bid(roll["material_total"], 16000, taxable=True, remodel=False)
    assert fb["remodel_tax"] == 0


def test_non_taxable_means_no_sales_tax():
    roll = pricing.roll_up(_two_systems(), patch_sf=16000)
    fb = pricing.compute_full_bid(roll["material_total"], 16000, taxable=False)
    assert fb["sales_tax"] == 0


# ── the hard-bid discount (D74): REMOVED 2026-10-03 ───────────────────
# Kyle's cell, read off it on 2026-09-04:
#   Epoxy!B74 = IF(B5="yes", IF(D70>=60000, -0.04, IF(B4="yes", IF(D70>=13000, -0.025, 0))))
#   Epoxy!D74 = ROUNDUP(SUM(D70,D73)*B74, 0)
# Hanz, 2026-10-03: "We also need to remove the hard bid discount." The tool now never lets B5 say
# yes (estimate_writer.HARD_BID_FLAG_CELLS), so this engine prices D74 at zero and no longer takes
# a `hard_bid` switch at all. Until today this section pinned the two bands (-4% over $60k for any
# job, -2.5% over $13k for a local one); those are the figures the counterexample below uses to
# prove the switch really is gone rather than merely defaulted off.


def test_the_engine_has_no_hard_bid_switch():
    """Removed, not defaulted. A caller still passing `hard_bid=True` fails loudly rather than
    quietly getting a discount the rest of the tool refuses."""
    import inspect
    assert "hard_bid" not in inspect.signature(pricing.compute_full_bid).parameters
    with pytest.raises(TypeError):
        pricing.compute_full_bid(70000, 16000, hard_bid=True)


def test_a_large_local_bid_gets_no_discount_line():
    """THE COUNTEREXAMPLE. $70k of material puts D70 well over $60k -- the band that used to take
    4% off any hard bid. D74 is now zero and the bid is the sum of the other lines."""
    fb = pricing.compute_full_bid(70000, 16000, local=True, taxable=False, remodel=False)
    assert fb["subtotal_costs"] >= 60000, "this fixture no longer reaches the old -4% band"
    assert fb["hard_bid"] == 0
    assert fb["total_base_bid"] == (fb["subtotal_costs"] + fb["gp_markup"] + fb["superintendent_pto"]
                                    + fb["soft_costs"] + fb["contingency"] + fb["total_taxes"]
                                    + fb["fees_bond"])


def test_the_api_ignores_a_hard_bid_flag_still_sent_by_an_old_caller():
    """/api/price's full_bid read `labor.hard_bid` until today. A client that still sends it gets
    exactly the bid one that does not send it gets."""
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app)
    h = {"Authorization": "Bearer x"}
    body = {"systems": [{"name": "MACRO Flake Single Broadcast", "sf": 16000}], "full_bid": True,
            "taxable": False, "remodel": False}
    plain = c.post("/api/price", json=body, headers=h)
    with_flag = c.post("/api/price", json=dict(body, labor={"hard_bid": True, "local": True}), headers=h)
    without = c.post("/api/price", json=dict(body, labor={"local": True}), headers=h)
    assert plain.status_code == with_flag.status_code == without.status_code == 200, plain.text
    assert with_flag.json()["full_bid"] == without.json()["full_bid"]
    assert with_flag.json()["full_bid"]["hard_bid"] == 0


# -- binary float dust in the ROUNDUP chain ----------------------------------
# Excel keeps 15 significant digits, so a figure that is only a binary artefact above an integer
# IS that integer to Excel. Python's float keeps all 17 and math.ceil believes every one of them.
# The gap costs a dollar, and it compounds: D73 feeds D75 and D76, so one bad dollar of GP comes
# out as two on the bid. bid-model.js has guarded this since it was written; pricing.py had
# not, so the two engines disagreed on 320 of the 22,000 material figures swept on 2026-09-04.
# Every one of those sits in the 0.32 GP band, because 1 - 0.32 is the only band edge that is not
# exact in binary: 0.6799999999999999.


def test_a_bid_is_not_a_dollar_high_because_of_binary_dust():
    """The defect, through the real engine on real inputs. $18,248 of material puts D70 on 27,064,
    and 27064 / (1 - 0.32) is 39800.00000000001 -- 39,800 to Excel and to any human. A bare ceil
    calls it 39,801 and bids the job high for no reason anyone could ever explain to a customer."""
    fb = pricing.compute_full_bid(18248, 12000, taxable=False, remodel=False)
    base = fb["subtotal_costs"]
    assert fb["sales_tax"] == 0 and fb["fees"] == 0, (
        "D73's base is D70+D80+D83; this fixture assumes the latter two are zero")

    quotient = base / (1 - fb["gp_pct"])
    # Self-check: if a rate change ever moves this fixture off the dust, the test below would
    # pass against a bare ceil too and would be proving nothing at all.
    assert math.ceil(quotient) != round(quotient), (
        "this fixture no longer lands on float dust, so it cannot tell the guard from a ceil")
    assert abs(quotient - round(quotient)) < 1e-6, (
        "that is a real fraction, not dust -- it SHOULD round up, and this fixture is wrong")

    assert fb["gp_markup"] == round(quotient) - base, (
        "the GP markup bought a dollar off the back of a rounding error")
    assert fb["gp_markup"] < math.ceil(quotient) - base, "still rounding the dust up"


def test_a_genuine_fraction_still_rounds_all_the_way_up():
    """THE COUNTEREXAMPLE, and the only real risk in this change. The guard has to swallow binary
    dust and NOTHING else. Round to too few digits -- or reach for a plain epsilon -- and a real
    $1,475.40 of cost becomes $1,475 of bid, which is Treadwell quietly under-charging every job
    to fix a problem that costs a dollar. A returned cent is still a billed dollar."""
    assert pricing._roundup(1475.4) == 1476
    assert pricing._roundup(1475.000000000002) == 1475
    assert pricing._roundup(0.0001) == 1
    assert pricing._roundup(9999999.4) == 10000000, "12 digits must not blunt a real seven-figure bid"


def test_the_guard_did_not_cost_the_away_from_zero_rounding():
    """_roundup does two jobs now. The dust guard must not undo the one it was written for -- the
    negative hard-bid discount that PR #449 fixed. Both directions, both properties, one function."""
    assert pricing._roundup(-1475.4) == -1476, "no longer rounding away from zero"
    assert pricing._roundup(-1475.000000000002) == -1475, "dust is not swallowed on the negative side"
    assert pricing._roundup(0) == 0


# -- the same dust, in the MATERIAL functions ---------------------------------
# The guard went into _roundup for the markup chain. It was not reaching the material figures that
# FEED that chain, which turned out to be the worse half: a sweep on 2026-09-04 found the guard
# changing compute_polish's material on 1008 of 22,572 (sf, dye, joint-filler) combinations -- 4.5%,
# four times the rate in compute_full_bid -- and roll_up's on 272 of 59,999. compute_system (81,300
# cases) and compute_cove (23,928) showed none, so only two functions were actually paying.
#
# It is the dye. Kyle's sheet prices it as TWO rows of sf x $0.14 (Polish D25 and D26), and 0.14 is
# not exact in binary, so the material subtotal lands a hair above an integer and a bare ceil buys a
# dollar. Every site touched here was read off the workbook first rather than trusted to the code's
# own comments: Polish D31/D32, Epoxy D40/D42, Polish B29, the liquids tables' ROUNDUP(sf/coverage),
# and the cove pair ROUNDUP(C/8)+ROUNDUP(C/4). All of them say ROUNDUP.


def test_polish_material_is_not_a_dollar_high_because_of_the_dye():
    """The defect through the real engine. 724 sq ft with dye puts the material subtotal on
    362.00000000000006 -- 362 to Excel, to Kyle, and to anyone reading the sheet. A bare ceil calls
    it 363, and that dollar then gets marked up on the way to the bid."""
    r = pricing.compute_polish(724, dye=True)

    # The raw sum the engine rounds. ORDER AND ROUNDING BOTH MATTER, and both are easy to get
    # wrong here: r["detail"] cannot be used because `line()` rounds each cost to 2dp for display
    # (summing those gives a clean 362.0), and folding the rates together first -- sf * (a+b+c+d)
    # -- also gives 362.0. The dust exists only in the engine's own shape: four separate products
    # accumulated one at a time, where 36.2 + 50.68 + 72.4 is already 159.28000000000003.
    P = pricing._POLISH
    raw = 0.0
    raw += 724 * P["patch_new"]
    raw += 724 * P["densifier"]
    raw += 724 * P["sealer"]
    raw += 724 * P["dye_per_coat"] * P["dye_coats"]
    # Self-check: if a rate ever moves this fixture off the dust, the assertion below would pass
    # against a bare ceil too and would be defending nothing.
    assert math.ceil(raw) != round(raw), "this fixture no longer lands on dust"
    assert abs(raw - round(raw)) < 1e-6, "that is a real fraction, not dust"

    assert r["subtotal"] == 362, "the material subtotal bought a dollar off a rounding error"
    assert r["material"] == 370


def test_the_material_roll_up_does_not_round_dust_either():
    """Epoxy D40 = ROUNDUP(SUM(D18:D39),0). The polish total arriving here is itself a sum of
    products, so it carries the same dust -- and D40 feeds D42's shipping, so one bad dollar
    arrives twice."""
    r = pricing.roll_up([], polish_total=300 * 1.37)   # 411.00000000000006
    assert r["material_sub"] == 411, "the material subtotal rounded binary dust up"


@pytest.mark.parametrize("fn,kw,want", [
    (pricing.compute_polish, {"sf": 1001}, 221),        # raw 220.22000000000003
    (pricing.compute_polish, {"sf": 1006}, 222),        # raw 221.32
])
def test_a_real_fraction_of_material_still_rounds_all_the_way_up(fn, kw, want):
    """THE COUNTEREXAMPLE, and the only real risk in this change. Guard too hard and a genuine
    $220.22 of material becomes $220 -- Treadwell under-buying on every job to fix a problem worth
    a dollar. Both fractions sit well above the integer, and both deliberately BELOW .5, so
    nearest-rounding would take them DOWN and this test would name it. sf=1007 was tried first and
    dropped: its raw is 221.54, which rounds up anyway, so it would have stayed green against a
    guard that had gone too far -- a passing test proving nothing."""
    assert fn(**kw)["subtotal"] == want


def test_roll_up_rounds_a_genuine_fraction_up_as_well():
    """The same counterexample on the other function. 410.40 is real money, not dust."""
    assert pricing.roll_up([], polish_total=410.4)["material_sub"] == 411
