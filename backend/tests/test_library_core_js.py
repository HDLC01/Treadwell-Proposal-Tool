"""The Item Library's pricing arithmetic, exercised under node.

Kyle and Will want to build their own assemblies — a system made of materials, priced from one
measured area. The model is lifted from Kyle's own sheet ("Decorative Flake Systems / MACRO
Flake Single Broadcast"), so the first thing these tests do is reproduce that sheet.

Why the maths gets its own file and this much attention: it is the whole feature. Everything
else is CRUD. And every way it can be wrong produces a plausible-looking number:

  * **Round instead of ceil.** You cannot buy 3.71 kits. Rounding to nearest under-buys on most
    jobs, so the estimate is short of MATERIAL, not just mispriced — the job stops halfway.
  * **Off by one at the boundary.** An area that divides exactly must not buy a spare unit.
    2,750 SF at 275 SF/Gal is 10 gallons, not 11. This is the classic ceil() bug and it inflates
    every tidy number an estimator is most likely to sanity-check.
  * **A deleted material pricing at zero.** Items and assemblies are separate rows, so a
    material can be removed while an assembly still points at it. Pricing that line at zero
    understates the bid silently. It has to be visible and excluded.
  * **Divide by zero coverage.** A half-filled item row must not produce Infinity quantities.
  * **Summing rounded lines.** Adding the rounded line costs instead of the unrounded ones
    shifts the total by a cent or two. Excel sums unrounded, so we do too.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "library-core.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")

# Kyle's sheet, exactly. Unit costs back-solve from his printed line costs (939.21/11 etc),
# which is why the real column holds four decimal places and not two.
SHEET_ITEMS = """[
  {id:'i1', name:'OPF',             unit:'Gal', unit_cost:85.3827,  coverage:275},
  {id:'i2', name:'Glaze #4',        unit:'Gal', unit_cost:79.7574,  coverage:125},
  {id:'i3', name:'Armor Top Satin', unit:'Kit', unit_cost:382.4475, coverage:775}
]"""
# waste_pct 0 on every line, deliberately: his sheet has no waste factor, so his printed numbers
# ARE the zero-waste case. Leaving it off would default them to 5% and this file would stop
# reproducing the document it exists to reproduce.
SHEET_ASM = """{name:'MACRO Flake Single Broadcast', lines:[
  {role:'1st BC',     item_id:'i1', coverage:275, waste_pct:0},
  {role:'Grout Coat', item_id:'i2', coverage:125, waste_pct:0},
  {role:'Top Coat',   item_id:'i3', coverage:775, waste_pct:0}
]}"""


def run(script: str):
    """Run `script` with `L` bound to the module; returns its printed JSON."""
    prelude = (
        "const L = require(%s);\n"
        "const ITEMS = %s;\n"
        "const ASM = %s;\n"
        "const out = (v) => console.log(JSON.stringify(v === undefined ? '<undefined>' : v)"
        ".replace(/[\\u0080-\\uffff]/g,"
        " (c) => '\\\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')));\n"
        % (json.dumps(str(CORE)), SHEET_ITEMS, SHEET_ASM)
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_module_loads():
    """A syntax error would make every test below fail with the same opaque message."""
    assert run("out(typeof L.priceAssembly)") == "function"


# ── Kyle's sheet, reproduced ──────────────────────────────────────────
def test_the_quantities_match_kyles_sheet():
    got = run("out(L.priceAssembly(ASM, ITEMS, 2875).rows.map(r => r.qty))")
    assert got == [11, 23, 4], "these are the numbers printed on his sheet"


def test_the_line_costs_match_kyles_sheet_to_the_cent():
    got = run("out(L.priceAssembly(ASM, ITEMS, 2875).rows.map(r => Math.round(r.cost*100)/100))")
    assert got == [939.21, 1834.42, 1529.79]


def test_the_total_and_price_per_sf():
    """The total sums UNROUNDED lines, so it lands a cent above the sum of the printed ones.
    Kyle's sheet prints $4,303.41 and its three printed lines add to $4,303.42; that gap is the
    same distinction, and it is his call which he wants, not ours to paper over."""
    got = run("const p = L.priceAssembly(ASM, ITEMS, 2875);"
              "out({total: Math.round(p.total*100)/100, per: Number(p.per_unit.toFixed(3))})")
    assert got["total"] == 4303.42
    assert got["per"] == 1.497


def test_the_display_helpers_format_those_numbers():
    assert run("out(L.money(4303.4199))") == "$4,303.42"
    assert run("out(L.perUnit(1.4968))") == "$1.497"


def test_the_total_sums_unrounded_lines_not_rounded_ones():
    """Kyle's own figures cannot prove this: both strategies give $4,303.42 there, so the test
    above passes either way — I checked, by making the code sum rounded lines and watching all
    41 tests stay green.

    So this uses a fixture built to separate them. Three lines at $1.114: summing unrounded
    gives $3.34, summing the rounded lines gives $3.33. Excel sums unrounded, and Kyle's sheet
    is Excel, so that is the behaviour to hold."""
    got = run("const items=[{id:'r1',unit:'Ea',unit_cost:1.114,coverage:100}];"
              "const a={lines:[{item_id:'r1',coverage:100,waste_pct:0},"
              "{item_id:'r1',coverage:100,waste_pct:0},{item_id:'r1',coverage:100,waste_pct:0}]};"
              "const p=L.priceAssembly(a,items,100);"
              "out({shown: L.money(p.total),"
              " ifRoundedFirst: L.money(p.rows.reduce((s,r)=>s+Math.round(r.cost*100)/100,0))})")
    assert got["ifRoundedFirst"] == "$3.33", "fixture no longer separates the two strategies"
    assert got["shown"] == "$3.34", "the total is summing rounded line costs"


# ── ceil, and the boundary ────────────────────────────────────────────
def test_quantities_round_up_because_you_buy_whole_units():
    """2,875 / 775 is 3.71 kits. Rounding to nearest would buy 4 as well, so the test that
    actually distinguishes ceil from round is below."""
    assert run("out(L.priceLine({item_id:'i3', coverage:775}, ITEMS, 2875).qty)") == 4
    # 0.2 of a unit: round() gives 3, ceil() gives 4. Only ceil buys enough material.
    assert run("out(L.priceLine({item_id:'i3', coverage:1000}, ITEMS, 2200).qty)") == 3
    assert run("out(L.priceLine({item_id:'i3', coverage:1000}, ITEMS, 2050).qty)") == 3
    assert run("out(L.priceLine({item_id:'i3', coverage:1000}, ITEMS, 2001).qty)") == 3


def test_an_exact_multiple_does_not_buy_a_spare_unit():
    """THE off-by-one. 2,750 at 275 SF/Gal is exactly 10 gallons. An 11th would inflate every
    round number an estimator is most likely to check by hand."""
    q = "out(L.priceLine({item_id:'i1', coverage:275, waste_pct:0}, ITEMS, %d).qty)"
    assert run(q % 2750) == 10
    assert run(q % 275) == 1
    assert run(q % 276) == 2


def test_the_smallest_job_still_buys_one_unit():
    assert run("out(L.priceLine({item_id:'i1', coverage:275}, ITEMS, 1).qty)") == 1


# ── coverage comes from the line, then the item ───────────────────────
def test_the_lines_coverage_wins_over_the_items_default():
    """The same product is used at different coverages in different systems, which is why
    Kyle's sheet keeps coverage on the line."""
    got = run("out(L.priceLine({item_id:'i1', coverage:100, waste_pct:0}, ITEMS, 1000).qty)")
    assert got == 10, "used the item's 275 default instead of the line's 100"


def test_a_line_with_no_coverage_falls_back_to_the_item():
    assert run("out(L.priceLine({item_id:'i1', waste_pct:0}, ITEMS, 550).qty)") == 2
    assert run("out(L.priceLine({item_id:'i1', coverage:'', waste_pct:0}, ITEMS, 550).qty)") == 2


# ── the ways a line can be un-priceable ───────────────────────────────
def test_a_deleted_material_is_reported_not_priced_at_zero():
    """Items and assemblies are separate rows, so this WILL happen. Pricing it at zero would
    silently understate the assembly — the worst of the three possible behaviours."""
    got = run("out(L.priceLine({item_id:'gone', coverage:275}, ITEMS, 2875))")
    assert got["ok"] is False and got["reason"] == "missing_item"
    assert got["cost"] == 0


def test_a_broken_line_is_excluded_from_the_total_and_counted():
    got = run("const a = {lines:[{role:'a',item_id:'i1',coverage:275},"
              "{role:'b',item_id:'gone',coverage:100}]};"
              "const p = L.priceAssembly(a, ITEMS, 2875);"
              "out({total: Math.round(p.total*100)/100, priced: p.priced_lines, broken: p.broken_lines})")
    assert got == {"total": 939.21, "priced": 1, "broken": 1}


@pytest.mark.parametrize("cov", ["0", "-5", "'abc'", "''", "null"])
def test_a_bad_coverage_never_divides_by_zero(cov):
    got = run("out(L.priceLine({item_id:'i3', coverage:%s}, [{id:'i3',unit_cost:10}], 2875))" % cov)
    assert got["ok"] is False and got["reason"] == "no_coverage"
    assert got["qty"] == 0


def test_a_missing_cost_is_refused_rather_than_priced_free():
    got = run("out(L.priceLine({item_id:'x', coverage:100},"
              "[{id:'x', coverage:100}], 1000))")
    assert got["ok"] is False and got["reason"] == "no_cost"


# ── no area yet is the opening state, not an error ────────────────────
@pytest.mark.parametrize("area", ["0", "''", "null", "undefined", "'abc'", "-100"])
def test_no_area_is_not_an_error(area):
    got = run("out(L.priceLine({item_id:'i1', coverage:275}, ITEMS, %s))" % area)
    assert got["ok"] is True, "the screen opens with no area typed; that is not a failure"
    assert got["priced"] is False and got["qty"] == 0 and got["cost"] == 0


def test_price_per_unit_is_null_without_an_area_rather_than_zero():
    """Zero would read as "free". Null reads as "not yet known", which is the truth."""
    assert run("out(L.priceAssembly(ASM, ITEMS, 0).per_unit)") is None
    assert run("out(L.priceAssembly({lines:[]}, ITEMS, 2875).per_unit)") is None


# ── pasted values ─────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expect", [
    ("'2875'", 2875), ("'2,875'", 2875), ("' 2875 '", 2875), ("'$2875'", 2875),
    ("'$1,200.50'", 1200.5), ("2875", 2875),
    ("''", None), ("'abc'", None), ("null", None), ("true", None), ("'1.2.3'", None),
])
def test_numbers_survive_being_pasted_from_a_spreadsheet(raw, expect):
    """These values come out of Excel, so commas and dollar signs arrive with them."""
    assert run("out(L.num(%s))" % raw) == expect


def test_a_pasted_area_prices_the_same_as_a_typed_one():
    a = run("out(L.priceAssembly(ASM, ITEMS, '2,875').rows.map(r => r.qty))")
    assert a == [11, 23, 4]


# ── rows line up with lines ───────────────────────────────────────────
def test_every_line_gets_exactly_one_row_in_order():
    """The page renders lines and rows side by side. A filtered-out broken line would silently
    shift every row after it onto the wrong line."""
    got = run("const a = {lines:[{item_id:'gone'},{item_id:'i1',coverage:275},{item_id:'gone'}]};"
              "const p = L.priceAssembly(a, ITEMS, 2875);"
              "out({n: p.rows.length, ok: p.rows.map(r => r.ok)})")
    assert got == {"n": 3, "ok": [False, True, False]}


def test_an_empty_assembly_prices_to_nothing_without_throwing():
    for asm in ("{}", "{lines:[]}", "{lines:null}", "null"):
        got = run("const p = L.priceAssembly(%s, ITEMS, 2875);"
                  "out({total: p.total, rows: p.rows.length})" % asm)
        assert got == {"total": 0, "rows": 0}


# ── the working shown on each row ─────────────────────────────────────
def test_a_row_can_explain_its_own_arithmetic():
    """Both halves of the sum are shown: what the area needs, and what that rounds up to. 10.45
    gallons becoming 11 is the single most-questioned number on this screen, and an estimator
    should be able to see where the extra gallon came from without doing the division."""
    got = run("const p = L.priceAssembly(ASM, ITEMS, 2875);"
              "out(L.explain(p.rows[0], 2875))")
    assert got == "2,875 ÷ 275 = 10.4545 → 11 Gal", \
        "unit abbreviations don't pluralise on Kyle's sheet"


def test_the_working_names_the_waste_factor_when_there_is_one():
    got = run("out(L.explain(L.priceLine({item_id:'i1', coverage:275, waste_pct:5},"
              " ITEMS, 2875), 2875))")
    assert got == "2,875 ÷ 275 +5% = 10.9773 → 11 Gal"


def test_the_working_does_not_claim_rounding_that_did_not_happen():
    """A line that lands exactly on a whole unit must not show "→ 10" after "= 10" — a redundant
    arrow reads as a rounding step and invites somebody to go looking for it."""
    got = run("out(L.explain(L.priceLine({item_id:'i1', coverage:275, waste_pct:0},"
              " ITEMS, 2750), 2750))")
    assert got == "2,750 ÷ 275 = 10 Gal"


def test_an_unpriced_row_explains_nothing():
    assert run("out(L.explain({ok:false}, 2875))") == ""
    assert run("out(L.explain(null, 2875))") == ""


# ── waste factor, pack sizes and the Roundup? checkbox (Hanz, 2026-08-15) ─────
# Three changes that all move money, and every one of them can be wrong in a way that still looks
# like a price:
#
#   * waste applied the WRONG WAY (×0.95) buys 10% less than intended and reads as a discount;
#   * `unit_cost` treated as a per-unit price when it is now a PACK price divides the bid by five;
#   * a legacy line quietly repriced, so an assembly somebody checked last week has moved.
def test_the_legacy_line_prices_exactly_as_it_did_before_any_of_this():
    """THE COMPATIBILITY GUARANTEE. Pack of one, rounding up, no waste — the old model was
    CEIL(area/coverage) × cost, and Kyle's sheet above is reproduced through the same code path.
    If this drifts, every assembly built during the beta has silently changed price."""
    got = run("const p = L.priceAssembly(ASM, ITEMS, 2875);"
              "out({qty: p.rows.map(r => r.qty),"
              " cost: p.rows.map(r => Math.round(r.cost*100)/100)})")
    assert got == {"qty": [11, 23, 4], "cost": [939.21, 1834.42, 1529.79]}


def test_waste_buys_more_material_not_less():
    """5% means buy 5% MORE than the area needs. The inverted version (×0.95) would under-buy on
    every job while looking like a sensible number, which is the failure this test exists for."""
    got = run("const line = (w) => L.priceLine({item_id:'i1', coverage:275, waste_pct:w},"
              " ITEMS, 27500);"
              "out({none: line(0).qty, five: line(5).qty, ten: line(10).qty})")
    # 100 gallons at the area, so the percentages read directly. The 10% case is also the
    # float-precision trap: 100 × 1.10 is 110.00000000000001, and a bare ceil() buys a 111th
    # gallon on exactly the round number somebody would check by hand.
    assert got == {"none": 100, "five": 105, "ten": 110}


def test_waste_can_push_an_exact_multiple_onto_another_unit():
    """The flip side of the boundary test above: with waste on, 2,750 SF at 275 SF/Gal is 10.5
    gallons and takes 11. That is the point of the column, not an off-by-one."""
    assert run("out(L.priceLine({item_id:'i1', coverage:275, waste_pct:5}, ITEMS, 2750).qty)") == 11


@pytest.mark.parametrize("waste,expect", [
    ("undefined", 5), ("null", 5), ("''", 5), ("'abc'", 5), ("-3", 5),
    ("0", 0), ("'5'", 5), ("2.5", 2.5), ("500", 100),
])
def test_a_missing_or_impossible_waste_factor_reads_as_the_default(waste, expect):
    """5% when absent, matching library.py's read-shaping exactly — a line stored before the column
    existed must price the same on both sides, and a row displaying 5% that was priced at 0% is a
    row lying about its own arithmetic. Over 100% is clamped rather than refused: it is a fat
    finger, and refusing the whole save would lose the rest of the line."""
    assert run("out(L.wastePct({waste_pct:%s}))" % waste) == expect


def test_rounding_up_buys_whole_packs_and_pays_the_pack_price():
    """A five-gallon pail is one purchase. 2,875 SF at 275 SF/Gal needs 10.98 gallons, which is
    three pails — not eleven, and not 2.196 pails."""
    got = run("const items=[{id:'p', name:'OPF', unit:'Gallon', buy_qty:5, unit_cost:426.91,"
              " coverage:275}];"
              "const r = L.priceLine({item_id:'p', waste_pct:5, roundup:true}, items, 2875);"
              "out({packs: r.packs, units: r.units, qty: r.qty,"
              " needed: Number(r.needed.toFixed(2)), cost: Math.round(r.cost*100)/100,"
              " label: L.qtyLabel(r), working: L.costWorking(r)})")
    assert got == {"packs": 3, "units": 15, "qty": 3, "needed": 10.98,
                   "cost": 1280.73, "label": "3 × 5 Gallon", "working": "3 × $426.91"}


def test_not_rounding_up_buys_the_fraction_at_the_single_unit_price():
    """Unticked, the line prices what is actually used — 10.98 gallons out of the pail, at a fifth
    of the pail's price. Charging the PACK price per gallon here would be five times the bid."""
    got = run("const items=[{id:'p', name:'OPF', unit:'Gallon', buy_qty:5, unit_cost:426.91,"
              " coverage:275}];"
              "const r = L.priceLine({item_id:'p', waste_pct:5, roundup:false}, items, 2875);"
              "out({packs: r.packs, unit_price: Number(r.unit_price.toFixed(4)),"
              " cost: Math.round(r.cost*100)/100, label: L.qtyLabel(r),"
              " working: L.costWorking(r)})")
    assert got["packs"] is None, "an unrounded line does not buy packs"
    assert got["unit_price"] == 85.382
    assert got["cost"] == 937.26         # 10.9773 gal × $85.382, vs $939.21 for 11 whole gallons
    assert got["label"] == "10.98 Gallon", "the QUANTITY still reads at two places"
    # The working names the PACK price and divides by the pack, so every figure in it is exact —
    # $426.91/5 is $85.382 here but $89.99/7 repeats, and a repeating per-unit price cannot be
    # printed in a way that multiplies back to the cost.
    assert got["working"] == "10.9773 ÷ 5 × $426.91"


def test_the_two_modes_differ_by_exactly_the_unused_material():
    """Rounded up pays for 15 gallons and uses 10.98 of them. The gap is real money, and it is the
    reason the checkbox exists rather than being a display preference."""
    got = run("const items=[{id:'p', unit:'Gallon', buy_qty:5, unit_cost:500, coverage:275}];"
              "const L2 = (ru) => L.priceLine({item_id:'p', waste_pct:0, roundup:ru}, items, 2875);"
              "out({up: Math.round(L2(true).cost*100)/100, frac: Math.round(L2(false).cost*100)/100})")
    # 2,875/275 = 10.4545 gal → 3 pails ($1,500) rounded up, or 10.4545 × $100 fractional.
    assert got == {"up": 1500.0, "frac": 1045.45}


def test_an_absent_roundup_flag_still_rounds_up():
    """Legacy lines have no flag, and the page has promised "you cannot buy 3.7 kits" since it
    shipped. Reading absent as false would reprice every one of them downwards."""
    got = run("out([undefined, null, true].map(ru =>"
              " L.priceLine({item_id:'i3', coverage:775, waste_pct:0, roundup:ru}, ITEMS, 2875).qty))")
    assert got == [4, 4, 4]
    assert run("out(Number(L.priceLine({item_id:'i3', coverage:775, waste_pct:0, roundup:false},"
               " ITEMS, 2875).qty.toFixed(3)))") == 3.71


# ── the working under each row must multiply out to the cost beside it ────────
# Found by an adversarial review, not by the tests above: every figure in the working line was run
# through a DISPLAY formatter (2dp) while the Cost cell beside it renders the full-precision
# product. So "11 × $85.38" sat under $939.21 (it multiplies to $939.18), and the three working
# lines of Kyle's own sheet added to $4,303.46 under a $4,303.42 total. An estimator checking a row
# by hand concludes the tool is wrong — which is the opposite of what showing the working is for.
#
# The fixtures below are chosen to BREAK naive formatting: 4-decimal unit costs, and a pack price
# that divides into a repeating decimal ($89.99 for 7 bags = $12.855714…/bag).
_TIE_OUT_CASES = [
    # (label, buy_qty, unit_cost, coverage, waste, roundup, area)
    ("Kyle's OPF, whole gallons", 1, 85.3827, 275, 0, "true", 2875),
    ("Kyle's Armor Top, 4-dp kit price", 1, 382.4475, 775, 0, "true", 2875),
    ("five-gallon pail, rounded up", 5, 426.91, 275, 5, "true", 2875),
    ("five-gallon pail, fractional", 5, 426.91, 275, 5, "false", 2875),
    ("$89.99 per 7 bags, fractional", 7, 89.99, 25, 0, "false", 40000),
    ("repeating unit price, big floor", 3, 100.00, 40, 5, "false", 12000),
    ("4-dp price and a 50-unit pack", 50, 1234.5678, 40, 5, "false", 12000),
]


@pytest.mark.parametrize("label,pack,cost,cov,waste,ru,area", _TIE_OUT_CASES)
def test_the_working_multiplies_out_to_the_cost_it_explains(label, pack, cost, cov, waste, ru, area):
    """Parses what the row LITERALLY SAYS and multiplies it, then compares with the cost cell."""
    got = run(
        "const items=[{id:'t', name:'X', unit:'Gallon', buy_qty:%s, unit_cost:%s, coverage:%s}];"
        "const r=L.priceLine({item_id:'t', waste_pct:%s, roundup:%s}, items, %s);"
        "out({working: L.costWorking(r), cost: L.money(r.cost)})"
        % (pack, cost, cov, waste, ru, area))
    # Read the sentence back the way a person would: "a × $b", or "a ÷ n × $b".
    import re as _re
    nums = [float(x.replace(",", "").replace("$", ""))
            for x in _re.findall(r"[\d,]+\.?\d*", got["working"].replace("$", "$ ").replace("$ ", "$"))]
    if " ÷ " in got["working"]:
        stated = nums[0] / nums[1] * nums[2]
    else:
        stated = nums[0] * nums[1]
    shown = float(got["cost"].replace("$", "").replace(",", ""))
    assert abs(stated - shown) <= 0.011, (
        "%s: the row says %s (= %.4f) under a cost of %s"
        % (label, got["working"], stated, got["cost"]))


def test_the_quantity_line_and_the_cost_line_agree_with_each_other(ran=None):
    """Both describe the same needed quantity, so both show it to the same precision. One saying
    10.98 while the other says 10.9773 invites somebody to work out which is lying."""
    got = run("const items=[{id:'t', unit:'Gallon', buy_qty:5, unit_cost:426.91, coverage:275}];"
              "const r=L.priceLine({item_id:'t', waste_pct:5, roundup:false}, items, 2875);"
              "out({q: L.explain(r, 2875), c: L.costWorking(r)})")
    assert "10.9773" in got["q"] and "10.9773" in got["c"], got


def test_a_price_held_to_four_places_is_shown_to_four_in_the_working():
    """Not in the Cost cell — money stays money — but inside the multiplication, where two
    decimals is the difference between explaining a number and contradicting it."""
    assert run("out(L.price4(382.4475))") == "$382.4475"
    assert run("out(L.price4(426.91))") == "$426.91", "trailing zeros are noise"
    assert run("out(L.price4(1200))") == "$1,200.00"
    assert run("out(L.qty4(10.977272727))") == "10.9773"
    assert run("out(L.qty4(15))") == "15"


@pytest.mark.parametrize("qty,expect", [
    ("undefined", 1), ("null", 1), ("0", 1), ("''", 1), ("'abc'", 1), ("-5", 1),
    ("5", 5), ("'5'", 5), ("2.5", 2.5),
])
def test_a_missing_or_impossible_pack_size_is_one_not_zero(qty, expect):
    """A pack of nothing would divide the cost by zero and price the job at Infinity. Every row
    written before this column existed is genuinely a pack of one."""
    assert run("out(L.buyQty({buy_qty:%s}))" % qty) == expect


def test_a_single_unit_pack_does_not_say_times_one():
    """"11 × 1 Gallon" is noise. The pack size is only worth naming when it is what made the
    quantity what it is."""
    got = run("const r = L.priceLine({item_id:'i1', coverage:275, waste_pct:0}, ITEMS, 2875);"
              "out(L.qtyLabel(r))")
    assert got == "11 Gal"


def test_quantities_read_without_trailing_zeros():
    assert run("out(L.qtyText(3))") == "3"
    assert run("out(L.qtyText(10.9773))") == "10.98"
    assert run("out(L.qtyText(1250.5))") == "1,250.5"
    assert run("out(L.qtyText('abc'))") == "—"
