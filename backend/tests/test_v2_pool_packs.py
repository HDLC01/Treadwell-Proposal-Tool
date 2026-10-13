"""v2: a material used on several takeoff rows is bought ONCE, in whole packs, for the section.

Hanz, 2026-10-13, "Buy packs for the whole job". Since System 1 and System 2 became two takeoff areas (#660), each area
holds its own copy of the default lines, and each row rounded its material up to whole packs on its own. On the real library
that priced System 1 5,000 + System 2 3,000 at $26,742 against $25,162 for one 8,000 SF floor (+$1,580, 6%), and 1,000 +
1,000 at $9,138 against $7,804 (+17%). Separately Phase 12 (#658) declared that the workbook judges a flake or quartz price
break on a system's two broadcast lines added together while the library judged each line alone, so small flake and quartz
jobs priced $10 to $38 high.

THE RULE (js/library-core.js pricePool, one function; js/polish-estimate.js and js/epoxy-takeoff.js call it, and the save reads
what they priced, so no second formula exists):
  * Within ONE priced section (one tab of a bid) the purchase of the SAME COAT is pooled across every takeoff row that holds it
    (Hanz, 2026-10-13, "Round each coat like Kyle"). A coat is one line of one assembly, so System 1 and System 2 copies of the
    default lines, or the same cove assembly on two areas, are one purchase: the fractional quantity is added first, then waste,
    roundup to whole packs and the price break happen ONCE. TWO DIFFERENT LINES of one assembly that buy the same item (Shop
    Floor Double Broadcast is three lines of Shop Floor) are two coats, each rounded to its own whole packs as Kyle's sheet does,
    so a single-area, single-system job prices to the workbook to the cent. A material row (no assembly) is its own coat by item.
  * The pooled cost goes back to the rows in proportion to what each needed, in whole ten-thousandths of a dollar by the
    LARGEST REMAINDER, so every row still shows a cost and the rows add up to the pooled total exactly.
  * Different materials on one price LADDER (identical price breaks, pack cost, bulk cost, pack size, unit and roundup, which is
    how the sheet reads a system's two flake lines) pool for the BREAK only: each keeps its own packs and the break is judged
    on every pack bought across the ladder (two coats of one item sit on one ladder too). A ladder is derived, not stored: it
    needs no column and no reseed.
  * Dye, Joint Filler and Remove Existing are never pooled. A cove is priced by its own formula, but the same cove on two or more
    rows is one length priced once (epoxy-takeoff poolCoves) and split back by length. An OFF row buys
    nothing. A coverage typed on one bid is the same material.
  * SAVED BIDS DO NOT MOVE. Only a section stamped `pool_packs: true` pools, and the stamp is written when a section is made
    (activateSection) or a new bid's root is seeded (seedNewSections), never on a saved one.

EXECUTED, NOT READ. js/pool-packs-harness.js runs pricePool on hand-worked libraries, the stamp through the real model, and
the real estimate page on Kyle's real library (the seed script's plan). BREAKS at the bottom breaks one line of one file in
a scratch copy, runs the harness on that, and requires the named check to fail. The Epoxy proof against the workbook
(test_epoxy_v2_proof.py) holds the other half: what pooling does to the 440 recorded jobs.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "pool-packs-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js"]


def run(frontend=FRONTEND, tmp=None):
    proc = run_node(HARNESS, frontend, plan_json(tmp))
    assert proc.returncode == 0, "the harness itself failed. Read this before assuming a product bug:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return run(tmp=tmp_path_factory.mktemp("pool"))


def near(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ── 1. the pool, on libraries every figure of which is worked by hand ─────────────────────────────────────────
def check_one_material_on_two_rows_is_bought_once(r):
    o = r["unit"]["once"]
    # 150 SF and 130 SF of a 100 SF/gallon coat: 1.5 + 1.3 = 2.8 gallons. Row by row that is 2 + 2 = 4 gallons.
    assert o["alone"] == [200, 200] and o["aloneTotal"] == 400, o
    assert o["pack"]["needed"] == 2.8 and o["pack"]["packs"] == 3 and o["pack"]["cost"] == 300 and o["pack"]["lines"] == 2, o
    assert o["pooledTotal"] == 300, o
    assert o["aloneUntouched"] == 200, "the rows handed in were edited, not copied"


def check_the_rows_add_up_to_the_pooled_cost_exactly(r):
    o = r["unit"]["once"]
    assert o["pooled"] == [160.7143, 139.2857] and o["sumsExactly"] is True, o
    # by what each needed (1.5 of 2.8 and 1.3 of 2.8), the leftover ten-thousandth to the bigger fraction
    assert near(o["pack"]["share"], 1.5 / 2.8), o["pack"]


def check_a_pooled_row_keeps_its_cost_per_unit(r):
    o = r["unit"]["once"]
    assert near(o["perUnit"] * o["area"], o["pooled"][0], 1e-6), o


def check_the_leftover_goes_to_the_largest_remainder(r):
    assert r["unit"]["biggestFraction"] == [160.7143, 139.2857], r["unit"]["biggestFraction"]
    a = r["unit"]["allocate"]
    assert a["uneven"] == [160.7143, 139.2857] and a["none"] == [] and a["zeroWeights"] == [7, 0], a
    # a tie goes to the earlier part, and the parts still add up
    assert a["thirds"] == [0.3334, 0.3333, 0.3333] and r["unit"]["remainder"]["exact"] is True, (a, r["unit"]["remainder"])
    # a total that is not on a ten-thousandth is split in proportion and still adds up
    assert near(sum(a["offGrain"]), 1 / 3, 1e-12) and near(a["offGrain"][1], 2 * a["offGrain"][0], 1e-12), a["offGrain"]


def check_a_fractional_total_off_the_grain_is_split_exactly_at_any_size(r):
    """A pooled roundup-off purchase whose cost is not on a ten-thousandth ($800.0025846...) was snapped to the grain,
    because the tolerance for "on the grain" grew with the total and passed everything above about $5."""
    a = r["unit"]["allocate"]
    total = 800.0025846153845
    assert near(a["offGrainBig"][0], total / 2, 1e-9) and near(a["offGrainBig"][1], total / 2, 1e-9), a["offGrainBig"]
    assert near(sum(a["offGrainBig"]), total, 1e-9), a["offGrainBig"]
    assert near(a["offGrainUneven"][0], total / 4, 1e-9) and near(a["offGrainUneven"][1], total * 3 / 4, 1e-9), a["offGrainUneven"]
    # ... while an on-the-grain total still splits in whole ten-thousandths (the checks above)


def check_a_row_nothing_pools_with_comes_back_as_it_went_in(r):
    assert r["unit"]["untouched"]["same"] is True
    n = r["unit"]["nulls"]
    assert n["length"] == 3 and n["first"] is None and n["middle"] is True, n


def check_an_off_row_buys_nothing_and_takes_no_share(r):
    o = r["unit"]["off"]
    # 1.5 + 1.2 = 2.7 gallons -> 3 for the two rows that are on; the off one keeps what it priced alone
    assert o["offIsTheSameObject"] is True and o["costs"][1] == 200, o
    assert near(o["onTotal"], 300) and near(sum(o["costs"][i] for i in (0, 2)), 300), o


def check_a_reserved_material_is_never_pooled(r):
    s = r["unit"]["skip"]
    assert s["same"] is True and s["costs"] == [200, 200], s
    p = r["page"]["reserved"]
    assert p["costs"] == p["alone"] and "dye" in p["reservedIds"], p


def check_a_coverage_typed_on_one_bid_is_the_same_material(r):
    p = r["unit"]["poolOf"]
    # 1.5 gallons at the library's coverage and 2 at a coverage of 50: 3.5 gallons, 4 bought. Without `pool_of` the copy
    # is another material and the two rows are bought apart.
    assert p.get("packs") == 4 and near(sum(p["pooled"]), 400) and p["withoutPoolOf"] == [200, 200], p
    t = r["page"]["typedCoverage"]
    assert near(t["rowSum"], t["expected"], 1e-3) and (t["gallons"], t["kits"]) == (29, 11), t


def check_each_coat_of_an_assembly_keeps_its_own_whole_pack_rounding(r):
    """Two lines of one assembly that buy the same item are two coats, rounded one by one like Kyle's sheet, and only the same
    line of the same assembly pools across rows. Three coats of 1.2 gallons are 2 + 2 + 2 = 6 gallons (not 3.6 bought as 4), and
    on two such rows each coat is 2.4 gallons bought as 3, nine gallons (not 7.2 bought as 8, and not 12 row by row)."""
    c = r["unit"]["coats"]
    assert c["one"] == 600 and c["oneUntouched"] is True, "a single area must keep each line's own roundup: %r" % c
    assert c["twoRowsAlone"] == 1200 and c["twoTotal"] == 900 and c["exact"] is True, c
    assert c["packsOfCoat"] == [3, 3, 3] and c["linesPooled"] == [2, 2, 2], c
    assert c["costs"] == [[150, 150, 150], [150, 150, 150]], c
    # a material row (no assembly) pools with another material row of the item, never with an assembly's line; and the
    # same item on two DIFFERENT assemblies is two coats
    assert c["materialRows"] == [160.7143, 139.2857] and c["materialPacks"] == 3, c
    assert c["materialVsAssembly"] == [200, 200] and c["otherAssembly"] == [200, 200], c


def check_two_coats_on_one_price_ladder_still_have_the_break_judged_on_both(r):
    l = r["unit"]["coatLadder"]
    # 4 bags in each coat: neither reaches the break of 6 alone, the two together do, and each coat keeps its own 4 bags
    assert l["alone"] == 800 and l["pooled"] == 720 and l["packs"] == [4, 4], l
    assert l["breakNamed"] == {"min_qty": 6, "unit_cost": 90}, l


def check_a_single_area_system_prices_to_the_workbook_and_the_same_coat_on_two_areas_pools(r):
    """Shop Floor Double Broadcast at 250 SF: three coats of Shop Floor, 100 SF/Gallon, each 2.5 gallons bought as 3. The
    workbook and the library before the pool read $1,270.01 of system; buying the item once for the whole system read
    $1,188.53 (8 gallons), $81.48 under the sheet with no second area involved. The same system in two 125 SF areas is the
    same coats on two rows, one purchase each, and costs what one 250 SF floor costs."""
    c = r["page"]["coats"]
    assert c["shopFloorLines"] == 3 and c["shopFloorPacks"] == [3, 3, 3], c
    assert near(c["sheetSystem"], 1270.009, 1e-3) and near(c["rowCost"], c["sheetSystem"], 1e-6), c
    assert near(c["wholeMaterial"], c["unstampedMaterial"], 1e-6), "a single area must price as a saved bid does: %r" % c
    assert near(c["wholeMaterial"], c["sheetSystem"] + c["patch"], 1e-6), c
    assert c["wholeMaterial"] > 1188.53 + 70, c
    assert near(c["halvesMaterial"], c["wholeMaterial"], 1e-6) and c["rowsAdd"] is True, c
    assert c["halvesAloneMaterial"] > c["halvesMaterial"] + 100, "row by row (a saved bid) must still pay the split: %r" % c


def check_a_fractional_purchase_judges_its_break_on_the_whole(r):
    f = r["unit"]["fractional"]
    assert f["alone"] == 200 and f["exact"] is True and f["breakNamed"] == {"min_qty": 20, "unit_cost": 8}, f
    assert f["pooled"] == [84, 76], f


def check_two_materials_on_one_price_ladder_pool_for_the_break_only(r):
    l = r["unit"]["ladder"]
    # 2 bags and 4 bags: neither reaches the break of 6 alone, together they do. Each keeps its own bags.
    assert l["alone"] == [200, 400] and l["pooled"] == [180, 360] and l["packs"] == [2, 4], l
    assert l["packCost"] == 90 and l["breakNamed"] == {"min_qty": 6, "unit_cost": 90}, l
    o = r["unit"]["ladderInOneRow"]
    assert o["alone"] == 600 and o["pooled"] == 540 and o["priced"] == 2 and o["broken"] == 0, o


def check_a_different_price_is_not_the_same_ladder(r):
    l = r["unit"]["ladder"]
    assert l["otherLadder"] == [200, 404] and l["otherSame"] is True, l


def check_a_line_that_cannot_price_is_left_as_it_is(r):
    b = r["unit"]["brokenLine"]
    assert b["reasons"] == ["missing_item", "ok"] and b["broken"] == 1 and b["costs"] == [160.7143, 139.2857], b


def check_the_pool_buys_at_the_bulk_cost_the_lines_were_priced_at(r):
    b = r["unit"]["bulk"]
    assert b["bulk"] is True and b["alone"] == 320 and b["pooled"] == 240, b


# ── 2. which sections pool ───────────────────────────────────────────────────────────────────────────────────
def check_a_new_bid_is_stamped_to_pool(r):
    m = r["model"]
    assert m["newBid"] == {"root": True, "poolsPacks": True}, m["newBid"]


def check_a_saved_bid_is_never_stamped(r):
    m = r["model"]
    assert m["savedBid"] == {"root": "absent", "poolsPacks": False}, m["savedBid"]
    assert m["savedSection"] == {"stamp": "absent", "poolsPacks": False}, m["savedSection"]


def check_a_section_made_now_is_stamped_to_pool(r):
    assert r["model"]["activated"] == {"stamp": True, "poolsPacks": True}, r["model"]["activated"]


def check_the_stamp_survives_a_save_and_a_reload(r):
    m = r["model"]
    assert m["roundTrip"].get("root") is True and m["roundTripTab"].get("stamp") is True, m


def check_only_exactly_true_pools(r):
    assert r["model"]["strict"] == [True] + [False] * 9, r["model"]["strict"]


# ── 3. the estimate page, on Kyle's real library ─────────────────────────────────────────────────────────────
def check_two_areas_cost_what_one_floor_costs_on_the_real_library(r):
    seen = 0
    for p in r["page"]["pairs"]:
        a, b = p["areas"]
        assert p["sf"] == [a + b, a + b], p
        assert p["twoTotal"] == p["oneTotal"], "%d + %d SF priced %r, one %d SF floor priced %r" % (a, b, p["twoTotal"], a + b, p["oneTotal"])
        assert near(p["twoMaterial"], p["oneMaterial"], 1e-6), p
        assert p["saves"] == 0, "opening a saved bid wrote something: %r" % p
        seen += 1
    assert seen == 5
    d = r["page"]["double"]
    assert d["two"] == d["one"] and near(d["twoMaterial"], d["oneMaterial"], 1e-6), d


def check_row_by_row_is_dearer_so_the_proof_is_not_vacuous(r):
    # the same two areas with no stamp (a saved bid) cost MORE, at every pair: the packs the pool no longer buys twice
    for p in r["page"]["pairs"]:
        assert p["stamped"] == [True, False] and p["rowByRowTotal"] > p["oneTotal"], p
        assert p["rowByRowMaterial"] > p["oneMaterial"] + 100, p


def check_two_different_systems_that_share_a_primer_buy_it_once(r):
    m = r["page"]["mixed"]
    assert m["pooled"] < m["rowByRow"] - 100 and m["rowsSumToMaterial"] is True, m


def check_every_rows_cost_still_shows_and_the_rows_add_up_to_the_sections_material(r):
    o = r["page"]["rows"]
    assert o["everyRowPriced"] is True and any(o["moved"]), o
    assert o["adds"] is True, "the rows and the patch do not add up to the section's material: %r" % o
    assert o["unpooledAdds"] is True, "the check is not vacuous only if a row-by-row section adds up as well: %r" % o


def check_a_saved_section_with_no_stamp_prices_row_by_row_as_it_did(r):
    s = r["page"]["savedSection"]
    assert s["stamped"] is False and near(s["material"], s["byRow"], 1e-6), s


def check_an_off_row_takes_no_share_on_the_page(r):
    o = r["page"]["off"]
    assert near(o["material"], o["alone"], 1e-6) and o["sf"] == [5000, 5000], o


def check_the_same_cove_on_two_areas_is_one_length(r):
    """5,000 + 3,000 SF with 100 LF of cove in each area cost what 8,000 SF with 200 LF cost. Priced one by one the cove
    rounded twice per area: $443 against $354 for 200 LF, and $399 against $222 for 40 + 40 LF."""
    c = r["page"]["cove"]
    assert c["two"] == c["one"] and near(c["twoMaterial"], c["oneMaterial"], 1e-6), c
    assert near(c["odd"], c["oddOne"], 1e-6), c
    assert c["saved"] > c["two"] and c["savedMaterial"] > c["twoMaterial"] + 50, "a saved bid must still pay the split: %r" % c


def check_the_pooled_cove_rows_show_a_cost_and_add_up(r):
    c = r["page"]["cove"]
    assert c["rowsAdd"] is True and len(c["coveCosts"]) == 2 and all(x > 0 for x in c["coveCosts"]), c
    assert near(c["coveCosts"][0], c["coveCosts"][1], 1e-6), "equal lengths take equal shares: %r" % c["coveCosts"]
    assert near(sum(c["coveCosts"]), c["wholeCove"], 1e-6), "the cove rows are the pooled 200 LF cove, every line of it: %r" % c


def check_an_off_cove_takes_no_share_and_two_different_coves_are_two_purchases(r):
    c = r["page"]["cove"]
    assert near(c["offMaterial"], c["firstMaterial"], 1e-6), c
    # an off row still shows what it would cost alone (it is not in the pool, so it is not repriced)
    assert near(c["offRowCost"], c["separate"][0], 1e-6), c
    assert near(c["mixedCoves"][0], c["separate"][0], 1e-6) and near(c["mixedCoves"][1], c["separate"][1], 1e-6), c


def check_the_polish_root_pools_too(r):
    o = r["page"]["root"]
    assert o["two"] == o["one"] and near(o["twoMaterial"], o["oneMaterial"], 1e-6), o
    assert o["rowByRow"] > o["one"] and o["rowsAdd"] is True and o["rowByRowAdds"] is True, o


CHECKS = [
    check_one_material_on_two_rows_is_bought_once,
    check_the_rows_add_up_to_the_pooled_cost_exactly,
    check_a_pooled_row_keeps_its_cost_per_unit,
    check_the_leftover_goes_to_the_largest_remainder,
    check_a_fractional_total_off_the_grain_is_split_exactly_at_any_size,
    check_a_row_nothing_pools_with_comes_back_as_it_went_in,
    check_an_off_row_buys_nothing_and_takes_no_share,
    check_a_reserved_material_is_never_pooled,
    check_a_coverage_typed_on_one_bid_is_the_same_material,
    check_each_coat_of_an_assembly_keeps_its_own_whole_pack_rounding,
    check_two_coats_on_one_price_ladder_still_have_the_break_judged_on_both,
    check_a_single_area_system_prices_to_the_workbook_and_the_same_coat_on_two_areas_pools,
    check_a_fractional_purchase_judges_its_break_on_the_whole,
    check_two_materials_on_one_price_ladder_pool_for_the_break_only,
    check_a_different_price_is_not_the_same_ladder,
    check_a_line_that_cannot_price_is_left_as_it_is,
    check_the_pool_buys_at_the_bulk_cost_the_lines_were_priced_at,
    check_a_new_bid_is_stamped_to_pool,
    check_a_saved_bid_is_never_stamped,
    check_a_section_made_now_is_stamped_to_pool,
    check_the_stamp_survives_a_save_and_a_reload,
    check_only_exactly_true_pools,
    check_two_areas_cost_what_one_floor_costs_on_the_real_library,
    check_row_by_row_is_dearer_so_the_proof_is_not_vacuous,
    check_two_different_systems_that_share_a_primer_buy_it_once,
    check_every_rows_cost_still_shows_and_the_rows_add_up_to_the_sections_material,
    check_a_saved_section_with_no_stamp_prices_row_by_row_as_it_did,
    check_an_off_row_takes_no_share_on_the_page,
    check_the_same_cove_on_two_areas_is_one_length,
    check_the_pooled_cove_rows_show_a_cost_and_add_up,
    check_an_off_cove_takes_no_share_and_two_different_coves_are_two_purchases,
    check_the_polish_root_pools_too,
]


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
def test_a_material_is_bought_once_for_the_section(ran, check):
    check(ran)


# ── RED WITHOUT THE CHANGE ───────────────────────────────────────────────────────────────────────────────────
CORE = "js/library-core.js"
MODEL = "js/bid-model.js"
PAGE = "js/polish-estimate.js"
TAKEOFF = "js/epoxy-takeoff.js"

BREAKS = {
    "an off row is pooled like the others": (
        CORE, "      if (opts.on && opts.on[i] === false) return;", "      if (false) return;",
        [check_an_off_row_buys_nothing_and_takes_no_share, check_an_off_row_takes_no_share_on_the_page]),
    "a reserved material is pooled": (
        CORE, '        if (id === undefined || id === null || id === "" || skip.indexOf(id) >= 0) return;',
        '        if (id === undefined || id === null || id === "") return;',
        [check_a_reserved_material_is_never_pooled]),
    "the leftover goes to the smallest remainder": (
        CORE, "    parts.slice().sort(function (x, y) { return (y.frac - x.frac) || (x.k - y.k); }).forEach(function (p, r) {",
        "    parts.slice().sort(function (x, y) { return (x.frac - y.frac) || (x.k - y.k); }).forEach(function (p, r) {",
        [check_the_leftover_goes_to_the_largest_remainder, check_the_rows_add_up_to_the_pooled_cost_exactly]),
    "a price ladder adds up no packs": (
        CORE, "      lad.units += g.own.units;", "      lad.units += 0;",
        [check_two_materials_on_one_price_ladder_pool_for_the_break_only,
         check_two_coats_on_one_price_ladder_still_have_the_break_judged_on_both]),
    "the ladder ignores the pack cost": (
        CORE, "    return JSON.stringify([brks, num(item.unit_cost), num(item.bulk_cost), buyQty(item),",
        "    return JSON.stringify([brks, 0, num(item.bulk_cost), buyQty(item),",
        [check_a_different_price_is_not_the_same_ladder]),
    "a typed coverage is another material": (
        CORE, '    return (it.pool_of !== undefined && it.pool_of !== null && it.pool_of !== "") ? it.pool_of : it.id;',
        "    return it.id;", [check_a_coverage_typed_on_one_bid_is_the_same_material]),
    "a row's cost per unit is left at what it was alone": (
        CORE, "      if (was.per_unit !== null && was.per_unit !== undefined && was.total > 0) next.per_unit = was.per_unit * (total / was.total);",
        "      void was;", [check_a_pooled_row_keeps_its_cost_per_unit]),
    "a row nothing pools with is rebuilt": (
        CORE, "      if (g.lines.length < 2 && !shared) return;           // nothing pools with it: leave the row alone",
        "      if (false) return;", [check_a_row_nothing_pools_with_comes_back_as_it_went_in]),
    "the needed quantity added is the packs bought": (
        CORE, "        g.needed += r.needed;", "        g.needed += r.units;",
        [check_one_material_on_two_rows_is_bought_once]),
    "a fractional purchase is judged on nothing": (
        CORE, "    var brk2 = breakAt(item, judged === undefined ? needed : judged);", "    var brk2 = breakAt(item, 0);",
        [check_a_fractional_purchase_judges_its_break_on_the_whole]),
    "the pool buys at the unit cost when the bid has Bulk Discount on": (
        CORE, "      var rep = g.rep, bulk = rep.bulk === true;", "      var rep = g.rep, bulk = false;",
        [check_the_pool_buys_at_the_bulk_cost_the_lines_were_priced_at]),
    "the stamp is dropped when a model is read back": (
        MODEL, "      return MODEL_KEYS.indexOf(e[0]) < 0 && !Object.prototype.hasOwnProperty.call(out, e[0]);",
        '      return MODEL_KEYS.indexOf(e[0]) < 0 && e[0] !== "pool_packs" && !Object.prototype.hasOwnProperty.call(out, e[0]);',
        [check_the_stamp_survives_a_save_and_a_reload]),
    "a material is bought once per row, not once per section": (
        CORE, "        var ck = coatKey(res, j, id);", '        var ck = coatKey(res, j, id) + "#" + i;',
        [check_two_different_systems_that_share_a_primer_buy_it_once, check_two_areas_cost_what_one_floor_costs_on_the_real_library]),
    "a coat is the item alone again (every line of the item pools, as #662 did)": (
        CORE, '    return (a === undefined || a === null || a === "") ? JSON.stringify(["m", id]) : JSON.stringify(["a", a, j, id]);',
        '    return JSON.stringify(["m", id]);',
        [check_each_coat_of_an_assembly_keeps_its_own_whole_pack_rounding,
         check_a_single_area_system_prices_to_the_workbook_and_the_same_coat_on_two_areas_pools]),
    "two lines of one assembly are one coat": (
        CORE, '    return (a === undefined || a === null || a === "") ? JSON.stringify(["m", id]) : JSON.stringify(["a", a, j, id]);',
        '    return (a === undefined || a === null || a === "") ? JSON.stringify(["m", id]) : JSON.stringify(["a", a, id]);',
        [check_each_coat_of_an_assembly_keeps_its_own_whole_pack_rounding,
         check_a_single_area_system_prices_to_the_workbook_and_the_same_coat_on_two_areas_pools]),
    "the same line of two assemblies is one coat": (
        CORE, '    return (a === undefined || a === null || a === "") ? JSON.stringify(["m", id]) : JSON.stringify(["a", a, j, id]);',
        '    return (a === undefined || a === null || a === "") ? JSON.stringify(["m", id]) : JSON.stringify(["a", j, id]);',
        [check_each_coat_of_an_assembly_keeps_its_own_whole_pack_rounding]),
    "the pooled cost is not handed back to its rows": (
        CORE, "          cost: share[k], pack_cost: fin.pack_cost,", "          cost: 0, pack_cost: fin.pack_cost,",
        [check_every_rows_cost_still_shows_and_the_rows_add_up_to_the_sections_material]),
    "a pooled row drops the lines that cannot price": (
        CORE, "        if (!copy) { copy = list[l.i].rows.slice(); changed.set(l.i, copy); }",
        "        if (!copy) { copy = []; changed.set(l.i, copy); }",
        [check_a_line_that_cannot_price_is_left_as_it_is]),
    "a break is judged on the pool's own quantity, not the ladder's": (
        CORE, "      var brk = breakAt(item, judged === undefined ? packs * pack : judged);",
        "      var brk = breakAt(item, packs * pack);",
        [check_two_materials_on_one_price_ladder_pool_for_the_break_only, check_two_coats_on_one_price_ladder_still_have_the_break_judged_on_both]),
    "a pooled row keeps the total it priced alone": (
        CORE, "      rows.forEach(function (r) { if (r && r.ok && r.priced) total += r.cost; });",
        "      rows.forEach(function (r) { if (r && r.ok && r.priced) total += 0; });",
        [check_one_material_on_two_rows_is_bought_once]),
    "a section is stamped to pool when it is not": (
        MODEL, "    return isObject(section) && section.pool_packs === true;", "    return isObject(section);",
        [check_a_saved_bid_is_never_stamped, check_only_exactly_true_pools]),
    "a new bid's root is not stamped": (
        MODEL, "out.pool_packs === undefined) out.pool_packs = true;", "out.pool_packs === undefined) void 0;",
        [check_a_new_bid_is_stamped_to_pool]),
    "a section made now is not stamped": (
        MODEL, "      pool_packs: true      // a section made now", "      pool_packs: false     // a section made now",
        [check_a_section_made_now_is_stamped_to_pool]),
    "a saved section pools whether or not it is stamped": (
        PAGE, "    if (i < 0 || !poolsList(list)) return rawRowPrice(row, takeoff);", "    if (i < 0) return rawRowPrice(row, takeoff);",
        [check_a_saved_section_with_no_stamp_prices_row_by_row_as_it_did, check_row_by_row_is_dearer_so_the_proof_is_not_vacuous]),
    "the page prices every row alone": (
        PAGE, "    return pooledRows(list)[i];", "    return rawRowPrice(row, takeoff);",
        [check_two_areas_cost_what_one_floor_costs_on_the_real_library, check_the_polish_root_pools_too]),
    "the page pools its reserved materials": (
        PAGE, "    var pooled = L.pricePool(alone, { on: on, skip: RESERVED_ITEM_IDS });",
        "    var pooled = L.pricePool(alone, { on: on, skip: [] });",
        [check_a_reserved_material_is_never_pooled]),
    "the page pools an off row": (
        PAGE, "    var pooled = L.pricePool(alone, { on: on, skip: RESERVED_ITEM_IDS });",
        "    var pooled = L.pricePool(alone, { skip: RESERVED_ITEM_IDS });",
        [check_an_off_row_takes_no_share_on_the_page]),
    "an off-the-grain total is snapped to the grain at any size": (
        CORE, "    if (Math.abs(scaled - whole) > Math.max(1e-6, 1e-12 * Math.abs(scaled))) {",
        "    if (Math.abs(scaled - whole) > 1e-5 * Math.max(1, Math.abs(scaled))) {",
        [check_a_fractional_total_off_the_grain_is_split_exactly_at_any_size]),
    "the page prices every cove alone": (
        PAGE, "    return E.poolCoves(pooled, list, { items: ITEMS, quartz: E.systemOneIsQuartz(list), on: on });",
        "    return pooled;",
        [check_the_pooled_cove_rows_show_a_cost_and_add_up]),
    "the section's material prices every cove alone": (
        PAGE, "        items: ITEMS, sf: B.takeoffSf(takeoff), poolCoves: B.poolsPacks(entry.section),",
        "        items: ITEMS, sf: B.takeoffSf(takeoff),",
        [check_the_pooled_cove_rows_show_a_cost_and_add_up, check_the_same_cove_on_two_areas_is_one_length]),
    "the page pools an off cove": (
        PAGE, "    return E.poolCoves(pooled, list, { items: ITEMS, quartz: E.systemOneIsQuartz(list), on: on });",
        "    return E.poolCoves(pooled, list, { items: ITEMS, quartz: E.systemOneIsQuartz(list) });",
        [check_an_off_cove_takes_no_share_and_two_different_coves_are_two_purchases]),
    "every cove is one purchase whatever its size": (
        TAKEOFF, "      var key = r.assembly_id;                      // one purchase per cove assembly",
        '      var key = "all";',
        [check_an_off_cove_takes_no_share_and_two_different_coves_are_two_purchases]),
    "a pooled cove row keeps only its first line": (
        TAKEOFF, "          total += split[j][k];",
        "          total += j === 0 ? split[j][k] : 0;",
        [check_the_pooled_cove_rows_show_a_cost_and_add_up]),
    "a typed coverage on an assembly line is another material": (
        PAGE, "      items = items.concat([Object.assign({}, real, { id: tmp, coverage: cov, pool_of: real.id })]);",
        "      items = items.concat([Object.assign({}, real, { id: tmp, coverage: cov })]);",
        [check_a_coverage_typed_on_one_bid_is_the_same_material]),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    """One line of one file is broken in a scratch copy, the harness runs on that, and EVERY named check has to fail on what
    it answers. The harness runs outside the raises block, so a break that merely crashes it is an error and not a pass, and
    break_source refuses an anchor that is not in the file exactly once."""
    require_node()
    rel, old, new, named = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    broken = run(frontend, tmp_path)
    for check in named:
        with pytest.raises(AssertionError):
            check(broken)


def test_every_check_is_named_by_a_break():
    named = {check for *_, checks in BREAKS.values() for check in checks}
    for check in CHECKS:
        assert check in named, "no break turns %s red" % check.__name__
