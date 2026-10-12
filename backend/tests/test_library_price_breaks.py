"""Phase 11 of the estimating program: a material can carry price breaks, a bulk cost and a coverage basis.

WHAT THE THREE ARE, and where Kyle's sheet uses them (backend/templates/estimate_sheet_5.7.xlsx, Epoxy):

  * PRICE BREAKS. The flake line is `=IF(O194<240,(O194*$X$146),(O194*MACROFlake))`: O194 is the pounds
    bought (after rounding up to 40 lb bags), X146 is the small-lot price ($2.30 a pound) and MACROFlake
    the bulk price ($2.25). STRICTLY under 240 pays the small price and 240 itself already pays the
    bulk one, so a break applies FROM its quantity, inclusive. The same shape sits behind microFlake.
  * BULK COST. The bid's "Bulk Discount ON" switch (D41) swaps six materials to a bulk price
    (`=IF($D$41=$V$136, W153, ...)`). It is a switch on the BID, not a quantity.
  * COVERAGE BASIS. Rubber cove and striping are priced per linear foot, the floor per square foot.

THE PROMISE THIS FILE KEEPS: a material with none of the three prices exactly as it did before. The
library golden (test_library_pricing_golden.py) holds 874 vectors of that; here it is stated again for
the three columns being null, empty and malformed.

Runs library-core.js under node. The expected flake figures are NOT typed in here: they are the sheet's
own formula, read out of the template and evaluated in Python, so the test follows the workbook.
"""
import json
import math
import pathlib
import re
import shutil
import subprocess

import pytest

import library
import main
import profiles

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
CORE = FRONTEND / "js" / "library-core.js"
TEMPLATE = BACKEND / "templates" / "estimate_sheet_5.7.xlsx"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run(script: str):
    """Run `script` with `L` bound to library-core.js; returns the JSON it prints."""
    prelude = ("const L = require(%s);\n"
               "const out = (v) => console.log(JSON.stringify(v === undefined ? '<undefined>' : v));\n"
               % json.dumps(str(CORE)))
    proc = subprocess.run(["node", "-e", prelude + script], capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── Kyle's flake, read out of his workbook ────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def sheet():
    """The flake line's own numbers, taken from the template rather than typed in."""
    import warnings

    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        formulas = openpyxl.load_workbook(TEMPLATE)["Epoxy"]
        values = openpyxl.load_workbook(TEMPLATE, data_only=True)["Epoxy"]
    formula = formulas["P194"].value
    # The threshold is read OUT of the formula. The pattern is built from a literal (no user data).
    m = re.match(r"^=IF\(O194<(\d+),\(O194\*\$X\$146\),\(O194\*MACROFlake\)\)$", formula)
    assert m, "the flake line is not the shape this test reads any more: %r" % formula
    # The bag size and lb/SF are on the line above it: CEILING(I192*M194, 40).
    media = formulas["O194"].value
    mm = re.match(r"^=CEILING\(I192\*M194,(\d+)\)$", media)
    assert mm, "the flake quantity is not the shape this test reads any more: %r" % media
    return {"threshold": int(m.group(1)), "bag": int(mm.group(1)),
            "lb_per_sf": float(formulas["M194"].value),
            "small": float(values["X146"].value), "bulk": float(values["W146"].value),
            "formula": formula}


def kyle_flake(sheet, sf):
    """The sheet's own answer for `sf` of MACRO flake: (pounds bought, cost)."""
    lbs = math.ceil(round(sf * sheet["lb_per_sf"] / sheet["bag"], 9)) * sheet["bag"]
    price = sheet["small"] if lbs < sheet["threshold"] else sheet["bulk"]
    return lbs, lbs * price


def flake_item(sheet):
    """Kyle's flake as a library material: 40 lb bags, pack cost = bag x $ per pound, one break."""
    return {"id": "flake", "name": "MACRO Flake", "unit": "Lb", "buy_qty": sheet["bag"],
            "unit_cost": sheet["bag"] * sheet["small"], "coverage": 1 / sheet["lb_per_sf"],
            "waste_pct": 0, "roundup": True,
            "price_breaks": [{"min_qty": sheet["threshold"],
                              "unit_cost": sheet["bag"] * sheet["bulk"]}]}


@needs_node
def test_the_template_still_says_240_pounds_and_the_two_prices(sheet):
    """THE EDGE RULE, pinned to the workbook: 240 lb is the bulk price, 239 is not. If Kyle moves the
    threshold or the two prices this fails and says so, instead of the library drifting from his sheet."""
    assert sheet["threshold"] == 240
    assert (sheet["small"], sheet["bulk"]) == (2.3, 2.25)
    assert sheet["formula"] == "=IF(O194<240,(O194*$X$146),(O194*MACROFlake))"


@needs_node
@pytest.mark.parametrize("sf", [1, 500, 1000, 1199, 1200, 1499, 1500, 1501, 1599, 1600, 1601, 1700,
                                2875, 5000, 12345])
def test_the_flake_prices_as_his_sheet_does_on_either_side_of_the_break(sheet, sf):
    """The library material, priced by priceLine, against the sheet's formula evaluated here. 1,000 SF is
    the $368.00 of media the sheet prints; 1,500 SF is 225 lb needed, 240 lb bought, exactly ON the break."""
    lbs, cost = kyle_flake(sheet, sf)
    got = run("const r = L.priceLine({item_id:'flake'}, [%s], %s); out({units: r.units, cost: r.cost,"
              " pb: r.price_break || null});" % (json.dumps(flake_item(sheet)), sf))
    assert got["units"] == lbs
    assert got["cost"] == pytest.approx(cost, abs=1e-6), (sf, lbs)
    assert (got["pb"] is not None) == (lbs >= sheet["threshold"]), "the break applies from 240 lb, inclusive"


@needs_node
def test_a_thousand_square_feet_of_flake_is_the_368_dollars_the_sheet_prints(sheet):
    got = run("out(L.priceLine({item_id:'flake'}, [%s], 1000).cost)" % json.dumps(flake_item(sheet)))
    assert got == pytest.approx(368.0)


@needs_node
@pytest.mark.parametrize("units,applies", [(239, False), (239.9999, False), (240, True), (240.0001, True),
                                           (10000, True)])
def test_a_break_starts_at_its_quantity_inclusive(units, applies):
    got = run("out(L.breakAt({price_breaks:[{min_qty:240, unit_cost:90}]}, %s))" % units)
    assert (got is not None) == applies


@needs_node
def test_the_float_noise_just_under_a_break_is_not_a_miss():
    """239.99999999999997 pounds is 240: the same twelve-figure guard the pack count uses."""
    assert run("out(L.breakAt({price_breaks:[{min_qty:240, unit_cost:90}]}, 239.99999999999997))")


@needs_node
def test_a_fractional_line_is_priced_by_the_units_it_needs_not_the_packs():
    """Roundup off: the purchase quantity is the units needed, and the break is judged on that."""
    item = {"id": "m", "unit": "Lb", "buy_qty": 40, "unit_cost": 92, "coverage": 1, "waste_pct": 0,
            "roundup": False, "price_breaks": [{"min_qty": 240, "unit_cost": 90}]}
    below = run("const r = L.priceLine({item_id:'m'}, [%s], 239); out({c: r.cost, pb: !!r.price_break})"
                % json.dumps(item))
    on = run("const r = L.priceLine({item_id:'m'}, [%s], 240); out({c: r.cost, pb: !!r.price_break})"
             % json.dumps(item))
    assert below == {"c": pytest.approx(239 * 92 / 40), "pb": False}
    assert on == {"c": pytest.approx(240 * 90 / 40), "pb": True}


@needs_node
def test_the_largest_break_not_above_the_purchase_wins_whatever_order_they_are_stored_in():
    brks = [{"min_qty": 480, "unit_cost": 88}, {"min_qty": 240, "unit_cost": 90}, {"min_qty": 960, "unit_cost": 85}]
    got = run("out([100, 240, 479, 480, 959, 960, 5000].map(u => (L.breakAt({price_breaks: %s}, u) || {}).unit_cost || null))"
              % json.dumps(brks))
    assert got == [None, 90, 90, 88, 88, 85, 85]


@needs_node
def test_a_price_break_reaches_the_working_the_row_shows():
    """The cost working must multiply out to the cost beside it, so it names the PACK COST in force."""
    item = {"id": "m", "unit": "Lb", "buy_qty": 40, "unit_cost": 92, "coverage": 1, "waste_pct": 0,
            "price_breaks": [{"min_qty": 240, "unit_cost": 90}]}
    got = run("const r = L.priceLine({item_id:'m'}, [%s], 240); out({w: L.costWorking(r), c: r.cost,"
              " pack: r.pack_cost, unit: r.unit_price, pb: r.price_break})" % json.dumps(item))
    assert got["pack"] == 90 and got["unit"] == 90 / 40
    assert got["c"] == 6 * 90 and "90" in got["w"] and "92" not in got["w"]
    assert got["pb"] == {"min_qty": 240, "unit_cost": 90}


# ── nothing set means nothing changes ─────────────────────────────────────────────────────────
BASE = {"id": "m", "name": "OPF", "unit": "Gal", "buy_qty": 5, "unit_cost": 426.91, "coverage": 275,
        "waste_pct": 7.5, "roundup": True}


@needs_node
@pytest.mark.parametrize("extra", [
    {}, {"price_breaks": None, "bulk_cost": None, "coverage_basis": None},
    {"price_breaks": [], "bulk_cost": 0, "coverage_basis": ""},
    {"price_breaks": "not a list", "bulk_cost": "abc", "coverage_basis": "yards"},
    {"price_breaks": [None, 5, {}, {"min_qty": 0, "unit_cost": 1}, {"min_qty": 10, "unit_cost": -3},
                      {"min_qty": "x", "unit_cost": 1}]},
])
@pytest.mark.parametrize("area", [0, 275, 2875, 27500, 100000])
def test_a_material_with_none_of_the_three_prices_exactly_as_before(extra, area):
    """Null, empty and malformed values are all 'none': the answer is byte for byte the answer of the
    same material without the keys, with no new field on the row either. (The golden holds the wider
    version of this over 874 vectors.)"""
    plain = run("out(L.priceLine({item_id:'m'}, [%s], %s))" % (json.dumps(BASE), area))
    other = run("out(L.priceLine({item_id:'m'}, [%s], %s, {bulk: true}))"
                % (json.dumps(dict(BASE, **extra)), area))
    # `item` is the material itself, which differs by the keys we added; everything priced is the same.
    plain.pop("item"), other.pop("item")
    assert other == plain
    for key in ("price_break", "bulk", "basis"):
        assert key not in other


# ── the bulk cost ─────────────────────────────────────────────────────────────────────────────
@needs_node
def test_the_bulk_cost_applies_only_when_the_bid_has_bulk_on():
    item = dict(BASE, bulk_cost=380.0)
    off = run("const r = L.priceLine({item_id:'m'}, [%s], 2875); out([r.pack_cost, r.bulk])" % json.dumps(item))
    explicit_off = run("const r = L.priceLine({item_id:'m'}, [%s], 2875, {bulk:false}); out([r.pack_cost, r.bulk])"
                       % json.dumps(item))
    on = run("const r = L.priceLine({item_id:'m'}, [%s], 2875, {bulk:true}); out([r.pack_cost, r.bulk, r.cost])"
             % json.dumps(item))
    assert off == [426.91, None] or off == [426.91]
    assert explicit_off == off
    assert on[0] == 380.0 and on[1] is True
    assert on[2] == pytest.approx(math.ceil(2875 / 275 * 1.075 / 5) * 380.0)


@needs_node
def test_a_bulk_switch_with_no_bulk_cost_on_the_material_changes_nothing():
    got = run("out([L.priceLine({item_id:'m'}, [%s], 2875).cost, L.priceLine({item_id:'m'}, [%s], 2875, {bulk:true}).cost])"
              % (json.dumps(BASE), json.dumps(BASE)))
    assert got[0] == got[1]


@needs_node
def test_a_price_break_beats_the_bulk_cost_because_it_is_the_quantity_actually_bought():
    item = dict(BASE, unit_cost=100, bulk_cost=90, price_breaks=[{"min_qty": 20, "unit_cost": 80}])
    got = run("const a = L.priceLine({item_id:'m'}, [%s], 27500, {bulk:true});"
              "const b = L.priceLine({item_id:'m'}, [%s], 275, {bulk:true});"
              "out([a.pack_cost, !!a.bulk, b.pack_cost, b.bulk === true])" % (json.dumps(item), json.dumps(item)))
    assert got[0] == 80 and got[2] == 90 and got[3] is True


@needs_node
def test_the_assembly_passes_the_bid_switch_to_every_line():
    items = [dict(BASE, id="a", bulk_cost=300.0), dict(BASE, id="b", bulk_cost=200.0)]
    asm = {"lines": [{"item_id": "a"}, {"item_id": "b"}]}
    got = run("const p = (o) => L.priceAssembly(%s, %s, 2750, o).rows.map(r => r.pack_cost);"
              "out([p(), p({bulk:true})])" % (json.dumps(asm), json.dumps(items)))
    assert got == [[426.91, 426.91], [300.0, 200.0]]


# ── the coverage basis ────────────────────────────────────────────────────────────────────────
@needs_node
def test_each_material_takes_the_measure_it_is_quoted_per_from_a_whole_takeoff():
    cove = dict(BASE, id="cove", unit="Gal", coverage=100, buy_qty=1, waste_pct=0, coverage_basis="lf")
    floor = dict(BASE, id="floor", unit="Gal", coverage=100, buy_qty=1, waste_pct=0)          # no basis: SF
    each = dict(BASE, id="each", unit="Each", coverage=1, buy_qty=1, waste_pct=0, coverage_basis="each")
    takeoff = {"sf": 1000, "lf": 250, "each": 7}
    got = run("const t = %s; const items = %s;"
              "out(items.map(i => L.priceLine({item_id: i.id}, items, t).units))"
              % (json.dumps(takeoff), json.dumps([cove, floor, each])))
    assert got == [3, 10, 7]      # ceil(250/100), ceil(1000/100), ceil(7/1)


@needs_node
def test_a_plain_number_is_still_the_measure_whatever_the_basis_says():
    """Every caller today passes a number it has already chosen. A basis must not reinterpret it."""
    lf = dict(BASE, coverage_basis="lf", buy_qty=1, waste_pct=0, coverage=100)
    got = run("out(L.priceLine({item_id:'m'}, [%s], 1000).units)" % json.dumps(lf))
    assert got == 10


@needs_node
def test_a_takeoff_without_the_measure_is_not_priced_yet_rather_than_priced_at_zero():
    lf = dict(BASE, coverage_basis="lf")
    got = run("const r = L.priceLine({item_id:'m'}, [%s], {sf: 1000}); out({ok: r.ok, priced: r.priced, cost: r.cost})"
              % json.dumps(lf))
    assert got == {"ok": True, "priced": False, "cost": 0}


@needs_node
def test_the_basis_is_named_on_the_row_only_when_the_material_has_one():
    got = run("out([L.priceLine({item_id:'m'}, [%s], 100).basis || null,"
              " L.priceLine({item_id:'m'}, [%s], 100).basis || null,"
              " L.coverageBasis({coverage_basis:' LF '}), L.coverageBasis({coverage_basis:'yards'})])"
              % (json.dumps(BASE), json.dumps(dict(BASE, coverage_basis="lf"))))
    assert got == [None, "lf", "lf", None]


# ── the data layer ────────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_items": [], "library_assemblies": [], "library_vendors": []}
    monkeypatch.setattr(library, "get_client", lambda: fake_supabase(st))
    return st


@pytest.fixture()
def as_admin(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "a1", "email": e, "role": "admin"})


@pytest.fixture()
def as_user(monkeypatch):
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "somebody-else@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "u1", "email": e, "role": "user"})


def _client():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _mk(**kw):
    body = {"name": "MACRO Flake", "unit": "Lb", "unit_cost": 92, "coverage": 6.6667, "buy_qty": 40}
    body.update(kw)
    return library.create_item(body, "hanz@wetreadwell.com")


def test_the_three_fields_are_only_written_when_the_request_carries_them():
    """A database without the columns (production, until its DDL is approved) is never sent one."""
    for partial in (False, True):
        got = library.validate_item({"name": "OPF", "unit_cost": 5}, partial=partial)
        for field in ("price_breaks", "bulk_cost", "coverage_basis"):
            assert field not in got, (field, partial)


def test_price_breaks_are_checked_and_normalised():
    got = library.validate_item({"name": "x", "price_breaks": [
        {"min_qty": "240", "unit_cost": "$90"}, {"min_qty": 480.0, "unit_cost": 88.5, "junk": "dropped"}]})
    assert got["price_breaks"] == [{"min_qty": 240.0, "unit_cost": 90.0}, {"min_qty": 480.0, "unit_cost": 88.5}]


def test_price_breaks_arrive_from_a_json_string_too():
    got = library.validate_item({"name": "x", "price_breaks": '[{"min_qty": 240, "unit_cost": 90}]'})
    assert got["price_breaks"] == [{"min_qty": 240.0, "unit_cost": 90.0}]


@pytest.mark.parametrize("blank", [None, "", [], "[]"])
def test_no_breaks_is_stored_as_null_never_as_an_empty_list(blank):
    assert library.validate_item({"name": "x", "price_breaks": blank})["price_breaks"] is None


@pytest.mark.parametrize("bad,words", [
    ([{"min_qty": 240, "unit_cost": 90}, {"min_qty": 240, "unit_cost": 88}], "go up"),
    ([{"min_qty": 480, "unit_cost": 90}, {"min_qty": 240, "unit_cost": 88}], "go up"),
    ([{"min_qty": 0, "unit_cost": 90}], "quantity above zero"),
    ([{"min_qty": 240, "unit_cost": 0}], "cost above zero"),
    ([{"min_qty": 240}], "cost above zero"),
    ([{"unit_cost": 90}], "quantity above zero"),
    ([{"min_qty": -5, "unit_cost": 90}], "negative"),
    ([{"min_qty": "lots", "unit_cost": 90}], "number"),
    (["240"], "quantity and a cost"),
    ({"min_qty": 240, "unit_cost": 90}, "list"),
    ("not json", "could not be read"),
    ([{"min_qty": 1, "unit_cost": 1}] * 13, "at most"),
])
def test_a_bad_price_break_list_is_refused_with_a_plain_message(bad, words):
    with pytest.raises(library.ValidationError) as e:
        library.validate_item({"name": "x", "price_breaks": bad})
    assert words in str(e.value), str(e.value)
    assert "—" not in str(e.value), "house rule: no em dashes in user copy"


@pytest.mark.parametrize("raw,expect", [("$58.1846", 58.1846), (88, 88.0), ("", None), (None, None), (0, None)])
def test_a_bulk_cost_is_a_pasted_money_figure_and_zero_means_not_set(raw, expect):
    assert library.validate_item({"name": "x", "bulk_cost": raw})["bulk_cost"] == expect


@pytest.mark.parametrize("bad", [-1, "abc", True])
def test_a_bad_bulk_cost_is_refused(bad):
    with pytest.raises(library.ValidationError):
        library.validate_item({"name": "x", "bulk_cost": bad})


@pytest.mark.parametrize("raw,expect", [("sf", "sf"), (" LF ", "lf"), ("Each", "each"), ("", None), (None, None)])
def test_a_coverage_basis_is_one_of_three_words_or_blank(raw, expect):
    assert library.validate_item({"name": "x", "coverage_basis": raw})["coverage_basis"] == expect


@pytest.mark.parametrize("bad", ["yards", "square feet", 5, True])
def test_an_unknown_coverage_basis_is_refused(bad):
    with pytest.raises(library.ValidationError) as e:
        library.validate_item({"name": "x", "coverage_basis": bad})
    assert "SF, LF or Each" in str(e.value)


def test_a_row_without_the_columns_reads_back_with_all_three_empty(store):
    """list_items on a database that does not have the columns: present, and None."""
    store["library_items"].append({"id": "old", "name": "Old OPF", "unit": "Gal", "unit_cost": 85.38,
                                   "coverage": 275, "deleted_at": None})
    got = library.list_items()[0]
    assert (got["price_breaks"], got["bulk_cost"], got["coverage_basis"]) == (None, None, None)


def test_a_stored_row_is_shaped_leniently():
    got = library._shape_item({"id": "x", "name": "n", "bulk_cost": "58.1846", "coverage_basis": "lf",
                               "price_breaks": [{"min_qty": "240", "unit_cost": "90"}, {"min_qty": 0}, "junk"]})
    assert got["bulk_cost"] == 58.1846 and got["coverage_basis"] == "lf"
    assert got["price_breaks"] == [{"min_qty": 240.0, "unit_cost": 90.0}]
    assert library._shape_item({"id": "x", "name": "n", "coverage_basis": "yards"})["coverage_basis"] is None
    assert library._shape_item({"id": "x", "name": "n", "price_breaks": '[{"min_qty":240,"unit_cost":90}]'}
                               )["price_breaks"] == [{"min_qty": 240.0, "unit_cost": 90.0}]


def test_the_api_saves_and_returns_all_three(store, as_admin):
    row = _mk()
    r = _client().patch("/api/library/items/%s" % row["id"], json={
        "price_breaks": [{"min_qty": 240, "unit_cost": 90}], "bulk_cost": "88", "coverage_basis": "lf"})
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["price_breaks"] == [{"min_qty": 240.0, "unit_cost": 90.0}]
    assert (item["bulk_cost"], item["coverage_basis"]) == (88.0, "lf")
    again = [i for i in _client().get("/api/library/items").json()["items"] if i["id"] == row["id"]][0]
    assert again["price_breaks"] == item["price_breaks"]
    stored = store["library_items"][0]
    assert stored["price_breaks"] == [{"min_qty": 240.0, "unit_cost": 90.0}]


def test_the_api_answers_400_with_a_plain_message_for_bad_breaks(store, as_admin):
    row = _mk()
    r = _client().patch("/api/library/items/%s" % row["id"], json={
        "price_breaks": [{"min_qty": 480, "unit_cost": 90}, {"min_qty": 240, "unit_cost": 88}]})
    assert r.status_code == 400
    assert "go up" in r.json()["detail"]
    assert store["library_items"][0].get("price_breaks") is None, "a refused save wrote nothing"


def test_clearing_the_breaks_sets_them_back_to_null(store, as_admin):
    row = _mk(price_breaks=[{"min_qty": 240, "unit_cost": 90}])
    r = _client().patch("/api/library/items/%s" % row["id"], json={"price_breaks": []})
    assert r.status_code == 200 and r.json()["item"]["price_breaks"] is None


def test_only_an_admin_may_set_the_three_fields(store, as_user):
    row = _mk()
    c = _client()
    for body in ({"price_breaks": [{"min_qty": 240, "unit_cost": 90}]}, {"bulk_cost": 5},
                 {"coverage_basis": "lf"}):
        assert c.patch("/api/library/items/%s" % row["id"], json=body).status_code == 403, body
    assert c.post("/api/library/items", json={"name": "Other", "bulk_cost": 5}).status_code == 403
    # An ordinary edit by the same person is still open, as it always was.
    assert c.patch("/api/library/items/%s" % row["id"], json={"unit_cost": 93}).status_code == 200
    assert store["library_items"][0].get("bulk_cost") is None


def test_a_bulk_cost_or_a_price_break_change_is_a_price_revision(store, as_admin):
    """'Date modified should only trigger when cost is modified': a bulk price is a price."""
    row = _mk()
    before = store["library_items"][0].get("cost_updated_at")
    r = _client().patch("/api/library/items/%s" % row["id"], json={"bulk_cost": 88})
    stamp = r.json()["item"]["cost_updated_at"]
    assert stamp and stamp != before
    same = _client().patch("/api/library/items/%s" % row["id"], json={"bulk_cost": 88})
    assert same.json()["item"]["cost_updated_at"] == stamp, "saving the same figure is not a revision"
    brk = _client().patch("/api/library/items/%s" % row["id"],
                          json={"price_breaks": [{"min_qty": 240, "unit_cost": 90}]})
    assert brk.json()["item"]["cost_updated_at"] >= stamp
    assert store["library_items"][0]["price_breaks"] == [{"min_qty": 240.0, "unit_cost": 90.0}]


def test_a_name_edit_does_not_touch_the_price_stamp(store, as_admin):
    row = _mk()
    r = _client().patch("/api/library/items/%s" % row["id"], json={"name": "MACRO Flake II"})
    assert r.json()["item"]["cost_updated_at"] in (None, row.get("cost_updated_at"))


# ── the DDL, in lock step across the three places a database comes from ───────────────────────
DDL_FILES = [BACKEND / "supabase_schema.sql", BACKEND / "staging" / "schema_pg.sql",
             BACKEND / "ops" / "library_price_breaks.sql"]
COLUMN_LINES = [
    re.compile(r"alter table public\.library_items add column if not exists price_breaks\s+jsonb;"),
    re.compile(r"alter table public\.library_items add column if not exists bulk_cost\s+numeric\(12,4\);"),
    re.compile(r"alter table public\.library_items add column if not exists coverage_basis\s+text\s+"
               r"check \(coverage_basis in \('sf', 'lf', 'each'\)\);"),
]


@pytest.mark.parametrize("path", DDL_FILES, ids=lambda p: p.name)
def test_every_database_source_adds_the_same_three_nullable_columns(path):
    text = path.read_text(encoding="utf-8")
    for pattern in COLUMN_LINES:
        assert pattern.search(text), "%s is missing %s" % (path.name, pattern.pattern)
    # NULLABLE, NO DEFAULT: no existing row changes.
    for name in ("price_breaks", "bulk_cost", "coverage_basis"):
        line = [l for l in text.splitlines() if "add column if not exists %s " % name in l][0]
        assert "default" not in line.lower() and "not null" not in line.lower(), line


def test_the_ops_script_reloads_the_schema_cache_and_touches_nothing_else():
    text = (BACKEND / "ops" / "library_price_breaks.sql").read_text(encoding="utf-8")
    assert "notify pgrst, 'reload schema';" in text
    statements = [l for l in text.splitlines() if re.match(r"^\s*(alter|update|insert|delete|drop|create)\b", l, re.I)]
    assert all(l.lower().startswith("alter table public.library_items add column if not exists") for l in statements)
    assert not re.search(r"\b(update|insert|delete|drop)\b\s", "\n".join(l for l in text.splitlines()
                                                                        if not l.lstrip().startswith("--")), re.I)


def test_the_writable_list_and_the_request_model_know_the_three_fields():
    for field in ("price_breaks", "bulk_cost", "coverage_basis"):
        assert field in library.ITEM_WRITABLE
        assert field in main.LibraryItemIn.model_fields, "the API would drop %s without a word" % field
        assert field in library.ITEM_ADMIN_ONLY


# ── review findings: a dearer break never beats bulk; Duplicate carries the columns ─────────────
@needs_node
def test_switching_bulk_on_never_raises_the_price_when_a_break_costs_more_than_bulk():
    """Bulk 70 against a 240+ break of 90: with bulk on the cheaper bulk price stands. A break that is
    cheaper than the bulk cost still wins, and with bulk off the break applies as it always did."""
    dear = dict(BASE, unit_cost=100, buy_qty=1, waste_pct=0, bulk_cost=70,
                price_breaks=[{"min_qty": 240, "unit_cost": 90}])
    cheap = dict(dear, price_breaks=[{"min_qty": 240, "unit_cost": 60}])
    got = run("const area = 275 * 240;"
              "const f = (it, o) => L.priceLine({item_id:'m'}, [it], area, o);"
              "const d = f(%s, {bulk:true}), c = f(%s, {bulk:true}), off = f(%s);"
              "out([d.pack_cost, !!d.price_break, d.cost, c.pack_cost, !!c.price_break, off.pack_cost])"
              % (json.dumps(dear), json.dumps(cheap), json.dumps(dear)))
    assert got == [70, False, 70 * 240, 60, True, 90]


@needs_node
def test_the_fractional_path_also_keeps_bulk_when_the_break_is_dearer():
    dear = dict(BASE, unit_cost=100, buy_qty=1, waste_pct=0, roundup=False, bulk_cost=70,
                price_breaks=[{"min_qty": 240, "unit_cost": 90}])
    got = run("const r = L.priceLine({item_id:'m'}, [%s], 275 * 240, {bulk:true}); out([r.pack_cost, r.cost])"
              % json.dumps(dear))
    assert got == [70, 70 * 240]


FULL = dict(BASE, unit="Lb", buy_qty=40, unit_cost=90, vendor="V", coverage=12, waste_pct=3, roundup=False,
            price_breaks=[{"min_qty": 240, "unit_cost": 80}], bulk_cost=70, coverage_basis="lf")


@needs_node
def test_duplicate_carries_every_priced_field_for_an_admin():
    got = run("out(L.itemCopyBody(%s, 'OPF (2)', ['Epoxy'], true))" % json.dumps(FULL))
    assert got["price_breaks"] == [{"min_qty": 240, "unit_cost": 80}]
    assert (got["bulk_cost"], got["coverage_basis"]) == (70, "lf")
    assert (got["coverage"], got["waste_pct"], got["roundup"]) == (12, 3, False)
    assert (got["name"], got["buy_qty"], got["unit_cost"], got["divisions"]) == ("OPF (2)", 40, 90, ["Epoxy"])


@needs_node
def test_duplicate_sends_the_admin_only_columns_to_nobody_else_and_only_when_present():
    non_admin = run("out(L.itemCopyBody(%s, 'x', [], false))" % json.dumps(FULL))
    assert not set(non_admin) & set(library.ITEM_ADMIN_ONLY), "a 403 on every non-admin Duplicate"
    bare = run("out(L.itemCopyBody(%s, 'x', [], true))" % json.dumps(BASE))
    assert not set(bare) & set(library.ITEM_ADMIN_ONLY), "a column production does not have yet"


def test_the_items_tab_builds_the_duplicate_body_with_the_shared_helper():
    src = (FRONTEND / "js" / "library.js").read_text(encoding="utf-8")
    assert "L.itemCopyBody(src, duplicateName(src.name), itemDivisions(src), ADMIN)" in src
