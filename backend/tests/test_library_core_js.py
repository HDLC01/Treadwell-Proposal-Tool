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
SHEET_ASM = """{name:'MACRO Flake Single Broadcast', lines:[
  {role:'1st BC',     item_id:'i1', coverage:275},
  {role:'Grout Coat', item_id:'i2', coverage:125},
  {role:'Top Coat',   item_id:'i3', coverage:775}
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
                          capture_output=True, text=True, timeout=60)
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
              "const a={lines:[{item_id:'r1',coverage:100},{item_id:'r1',coverage:100},"
              "{item_id:'r1',coverage:100}]};"
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
    assert run("out(L.priceLine({item_id:'i1', coverage:275}, ITEMS, 2750).qty)") == 10
    assert run("out(L.priceLine({item_id:'i1', coverage:275}, ITEMS, 275).qty)") == 1
    assert run("out(L.priceLine({item_id:'i1', coverage:275}, ITEMS, 276).qty)") == 2


def test_the_smallest_job_still_buys_one_unit():
    assert run("out(L.priceLine({item_id:'i1', coverage:275}, ITEMS, 1).qty)") == 1


# ── coverage comes from the line, then the item ───────────────────────
def test_the_lines_coverage_wins_over_the_items_default():
    """The same product is used at different coverages in different systems, which is why
    Kyle's sheet keeps coverage on the line."""
    got = run("out(L.priceLine({item_id:'i1', coverage:100}, ITEMS, 1000).qty)")
    assert got == 10, "used the item's 275 default instead of the line's 100"


def test_a_line_with_no_coverage_falls_back_to_the_item():
    assert run("out(L.priceLine({item_id:'i1'}, ITEMS, 550).qty)") == 2
    assert run("out(L.priceLine({item_id:'i1', coverage:''}, ITEMS, 550).qty)") == 2


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
    got = run("const p = L.priceAssembly(ASM, ITEMS, 2875);"
              "out(L.explain(p.rows[0], 2875))")
    assert got == "2,875 ÷ 275 → 11 Gal", "unit abbreviations don't pluralise on Kyle's sheet"


def test_an_unpriced_row_explains_nothing():
    assert run("out(L.explain({ok:false}, 2875))") == ""
    assert run("out(L.explain(null, 2875))") == ""
