"""Phase 14: js/gyp-takeoff.js, the part of the Gyp tabs that a library row cannot say.

The contract it follows is the one Dye, Joint Filler and the Epoxy cove follow (docs/v2-architecture.md, rule 3): the
FORMULA is code, the PRICES it reads are editable library rows, and a number in the code is only the fallback for a
database the seed has not reached. What that makes testable, and what is tested here:

  * ROW = FALLBACK = TEMPLATE   every price a preset reads (bag, primer, ISO strip, tape, sand, every sound mat's
                     roll price and roll size) equals the row the seed script plans AND the cell of that Gyp tab it
                     came from, on all five tabs.
  * THE FORMULA IS THE TEMPLATE'S   the yield of a bag, the hard-surface extra, the 3000 psi factor, the waste, the
                     sand a bag takes, what a gallon of primer and a roll of tape cover, the tooling, the crews and
                     hours are read back out of the template's own cells.
  * THE PRESETS ARE THE TABS'   the sound mat each tab opens on, its truckload (H36), its default thicknesses, its
                     catalogue, its ISO strip, and the label the proposal calls it, on every one of the five.
  * THE ARITHMETIC   bags are fractional and never rounded up (odd rule 7), sand follows them, the sound mat's rolls
                     decide whether it ships free (odd rule 6), a thickness that cannot be worked out is no price.
  * THE ROWS ARE READ   a price changed on the library row changes the price; with no row the fallback prices.

How the whole thing prices against the workbook is test_gyp_v2_proof.py.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest

from _node import require_node
from _oracle_support import profiles
from _seed_support import PLAN, SHEETS, seed

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
MODULE = FRONTEND / "js" / "gyp-takeoff.js"
FIRST = 'Gyp (USG 1-8")'
FR = "Gyp (FR)"
TABS = [FIRST, "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", FR]


def node(code: str):
    node_path = require_node()
    proc = subprocess.run([node_path, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def load_mod(path=MODULE):
    return node("""
      const G = require(%s);
      console.log(JSON.stringify({ PRESETS: G.PRESETS, AREAS: G.AREA_ASSEMBLIES, MIXES: G.MIXES, YIELD: G.YIELD_PER_EIGHTH,
        HARD: G.HARD_EXTRA, STRONG: G.STRONG_MIX_FACTOR, WASTE: G.WASTE, PRIMER: G.PRIMER_SF, TAPE: G.TAPE_SF,
        TON: G.POUNDS_A_TON, TOOLING: G.TOOLING, CREWS: G.CREWS, HOURS: G.HOURS, TABS: G.tabs() }));
    """ % json.dumps(str(MODULE if path is None else path)))


@pytest.fixture(scope="module")
def mod():
    require_node()
    return load_mod()


def _text(sheet, addr):
    return re.sub(r"\s+", " ", str(SHEETS[sheet].value(addr))).strip()


def _f(sheet, addr):
    return SHEETS[sheet].formula(addr)


def _v(sheet, addr):
    return SHEETS[sheet].value(addr)


# The cells of each tab. The area table and the lookup tables sit one column further left on Gyp (FR).
def _cells(tab):
    fr = tab == FR
    return {"mats": ([37, 38, 39, 42, 43, 44] if fr else [37, 38, 39, 40, 42, 43, 44]),
            "name": "N" if fr else "O", "price": "O" if fr else "P", "sf": "P" if fr else "Q"}


# ── the presets are the tabs' ────────────────────────────────────────────────
def check_presets(mod):
    assert mod["TABS"] == TABS, "the presets are the five Gyp tabs of the workbook, in its order"
    tabs = profiles()["tabs"]
    for tab in TABS:
        p = mod["PRESETS"][tab]
        c = _cells(tab)
        # the sound mat the tab opens on (A36) is the library row of that product, with H36's truckload
        a36 = _text(tab, "A36")
        want = "wb-gyp-" + seed._slug("Sound mat %s, roll" % a36)
        assert p["defaultMat"] == want, (tab, p["defaultMat"], want)
        mats = {m["id"]: m for m in p["mats"]}
        assert mats[want]["truckload"] == float(_v(tab, "H36")) == tabs[tab]["truckload"], tab
        # H36 is a lookup of the truckload by product on the four USG and GrassWorx tabs (`IF(A36=O37,280,IF(A36=O38,208,
        # ...)))`), so EVERY mat of the catalogue carries its own; Gyp (FR) types one number for all of them
        h36 = _f(tab, "H36")
        if tab == FR:
            assert h36 == 448 and {m["truckload"] for m in p["mats"]} == {448.0}
        else:
            lookup = {int(r): float(n) for r, n in re.findall(r"A36=O(\d+),(\d+)", h36)}
            assert sorted(lookup) == c["mats"], (tab, h36)
            assert [m["truckload"] for m in p["mats"]] == [lookup[r] for r in c["mats"]], tab
        # the catalogue is the tab's own table, each at the sheet's price a roll and SF a roll, in the sheet's order
        assert [m["id"] for m in p["mats"]] == [
            "wb-gyp-" + seed._slug("Sound mat %s, roll" % _text(tab, "%s%d" % (c["name"], r))) for r in c["mats"]], tab
        for m, r in zip(p["mats"], c["mats"]):
            assert m["price"] == pytest.approx(float(_v(tab, "%s%d" % (c["price"], r))), abs=1e-9), (tab, r)
            assert m["sf"] == float(_v(tab, "%s%d" % (c["sf"], r))), (tab, r)
            assert m["id"] in PLAN.items, m["id"]
            row = PLAN.items[m["id"]]
            assert row["unit_cost"] == pytest.approx(m["price"], abs=5e-5) and row["coverage"] == m["sf"], m["id"]
        # the default thickness of each area: G10 (soft), I10 (hard), K10 (corridor)
        assert p["thickness"] == {"soft": float(_v(tab, "G10")), "hard": float(_v(tab, "I10")),
                                  "corridor": float(_v(tab, "K10"))}, tab
        # the two tabs that type K10 are the two that do not follow G10 (here only Gyp (FR)); the rest read `=G10`
        assert (_f(tab, "K10") == "=G10") == (tab != FR), tab
        # ... and the preset says so, because a blank corridor box follows the soft thickness exactly there
        assert p["corridorFollowsSoft"] == (_f(tab, "K10") == "=G10"), tab
        # the label the proposal prints is the tab's own A1, `=B16` + C16 (Gyp (FR) has none and reads its mat)
        label = tabs[tab].get("label")
        assert label, tab


def test_every_preset_is_the_tabs_it_names(mod):
    check_presets(mod)


def test_the_labels_the_proposal_prints_are_the_sheets_own_titles(mod):
    tabs = profiles()["tabs"]
    for tab in TABS:
        if tab == FR:
            assert tabs[tab]["label"] == "Treadstone FR25 + R1 mat"        # A1 is blank on Gyp (FR)
            continue
        assert tabs[tab]["label"] == "%s + %s" % (_text(tab, "B16"), _text(tab, "C16").lstrip("+ ").strip()), tab


# ── row = fallback = template ────────────────────────────────────────────────
def check_prices(mod):
    for tab in TABS:
        p = mod["PRESETS"][tab]
        for key, cell_fallback in (("bag", "D23"), ("primer", "D27"), ("iso", "D28"), ("tape", "D29"), ("sand", "D33")):
            spec = p[key]
            assert spec["cell"] == cell_fallback, (tab, key)
            assert spec["fallback"] == pytest.approx(float(_v(tab, spec["cell"])), abs=1e-9), (tab, key)
            row = PLAN.items[spec["id"]]
            assert row["unit_cost"] / row["buy_qty"] == pytest.approx(spec["fallback"], abs=1e-9), (tab, key, spec["id"])


def test_every_fallback_equals_the_template_cell_of_its_tab_and_the_row_the_seed_plans(mod):
    check_prices(mod)


def test_the_primer_is_bought_by_the_drum_so_a_gallon_is_exactly_what_the_sheet_says():
    """USG!D27 is `=891/53`: stored as a pack of 53 gallons at $891 the gallon is the sheet's own float, and the
    four-place price a plain per-gallon row would have held ($16.8113) is not what the workbook charges."""
    row = PLAN.items["wb-gyp-usg-primer-53-gallon-drum"]
    assert (row["buy_qty"], row["unit_cost"]) == (53.0, 891.0)
    assert row["unit_cost"] / row["buy_qty"] == float(_v(FIRST, "D27"))
    assert "wb-gyp-usg-primer-53-gallon-drum-per-gallon" not in PLAN.items
    tp1 = PLAN.items["wb-gyp-treadstone-primer-tp1-gallon"]
    assert tp1["unit_cost"] / tp1["buy_qty"] == float(_v(FR, "D27"))


# ── the formula is the template's ────────────────────────────────────────────
def check_constants(mod):
    first = FIRST
    # a bag covers `G14 * 6` SF an eighth (G14 = 40 SF at 3/4"); a hard surface gets 12 more (S52 and S54)
    assert _f(first, "G15") == "=G14*6" and float(_v(first, "G14")) * 6 == mod["YIELD"]
    assert _f(first, "S52") == "=(G15+%d)/I24" % mod["HARD"]
    assert _f(first, "R52") == "=G15/I23" and _f(first, "T52") == "=G15/I25"
    assert "1.1764705915999" in _f(first, "R54") and mod["STRONG"] == 1.1764705915999
    for addr, base in (("R54", "G15/(I23*"), ("S54", "(G15+%d)/(I24*" % mod["HARD"]), ("T54", "G15/(I25*")):
        assert _f(first, addr) == "=ROUND(%s%s),0)" % (base, mod["STRONG"]), addr
    # the eighths of an inch at a thickness are the thickness times eight (I23:I25)
    for addr, t in (("I23", "H23"), ("I24", "H24"), ("I25", "H25")):
        assert _f(first, addr) == "=%s*8" % t
    # waste: gypsum, sand, sound mat
    assert (float(_v(first, "G18")), float(_v(first, "G19")), float(_v(first, "G20"))) == (
        mod["WASTE"]["gyp"], mod["WASTE"]["sand"], mod["WASTE"]["soundMat"])
    # bags are the area over the yield plus waste, NEVER rounded up (odd rule 7)
    for addr, area, y in (("B23", "F23", "J23"), ("B24", "F24", "J24"), ("B25", "F25", "J25")):
        assert _f(first, addr) == "=(%s/%s)*(1+G18)" % (area, y), addr
    assert _f(first, "H33") == "=B23+B24+B25"
    # the mixes and the sand a bag takes: 1.8 is 2500 psi at 180 lb, 1.4 is 3000+ psi at 140 lb
    assert [(m["mix"], m["sandLb"]) for m in mod["MIXES"]] == [
        (float(_v(first, "P52")), float(_v(first, "Q52"))), (float(_v(first, "P54")), float(_v(first, "Q54")))]
    assert _f(first, "B33") == "=((IF(G11=P52,Q52,IF(G11=P54,Q54))*H33)/%d)*(1+G19)" % mod["TON"]
    # the extras: primer on soft + corridor, ISO on hard (or every area), tape on hard
    assert _f(first, "B27") == "=(F23+F25)/%d" % mod["PRIMER"]
    assert _f(first, "B29") == "=F24/%d" % mod["TAPE"]
    assert _f(first, "B28") == "=IF(B14=\"Yes\",((F23+F24+F25)/(1200*1.8)),(F24/(1200*1.8)))"
    assert _f(FR, "B28") == "=IF(B14=\"Yes\",((F23+F24+F25)/1200),(F24/1200))"
    assert mod["PRESETS"][FIRST]["isoSf"] == pytest.approx(1200 * 1.8) and mod["PRESETS"][FR]["isoSf"] == 1200
    for tab in TABS:
        assert mod["PRESETS"][tab]["isoSf"] == (1200 if tab == FR else pytest.approx(2160))
    # the sound mat: ROUNDUP(hard SF / SF a roll * (1 + waste), 0)
    assert re.fullmatch(r"=ROUNDUP\(IF\(A36=O37,\(F24/Q37\).*\)\*\(1\+G20\),0\)", _f(first, "B36"))
    assert re.fullmatch(r"=ROUNDUP\(IF\(A36=N37,\(F24/P37\).*\)\*\(1\+G20\),0\)", _f(FR, "B36"))
    assert _f(first, "E36") == "=B36*D36" and _f(first, "E27") == "=B27*D27"
    # tooling: a moisture test ($35 each, the count typed) and consumables a square foot of every area
    assert float(_v(first, "C57")) == mod["TOOLING"]["moistureTest"] and float(_v(first, "C58")) == mod["TOOLING"]["consumablesPerSf"]
    assert _f(first, "E57") == "=ROUNDUP(B57*C57,0)" and _f(first, "E58") == "=ROUNDUP(B58*C58,0)"
    assert _f(first, "B58") == "=B43" and _f(first, "B43") == "=F22" and _f(first, "F22") == "=SUM(F23:F25)"
    assert _f(first, "E61") == "=SUM(E57:E60)"
    # the area boxes are the soft, hard and corridor SF of the area table
    assert (_f(first, "F23"), _f(first, "F24"), _f(first, "F25")) == ("=G9", "=I9", "=K9")
    assert (_f(first, "G9"), _f(first, "I9"), _f(first, "K9")) == ("=P28", "=Q28", "=R28")
    for name, cell in (("soft", "F23"), ("hard", "F24"), ("corridor", "F25")):
        assert mod["AREAS"][name]["cell"] == cell


def test_the_constants_are_the_templates(mod):
    check_constants(mod)


def check_hours(mod):
    """The crews and the hours the sheet works the labor out of (A45:A49, G46:G49, B46:B51)."""
    first = FIRST
    crews = mod["CREWS"]
    assert (float(_v(first, "A45")), float(_v(first, "A46")), float(_v(first, "A47")), float(_v(first, "A48")),
            float(_v(first, "A49")), float(_v(first, "A51"))) == (
        crews["prePour"], crews["prep"], crews["mat"], crews["pour"], crews["unload"], crews["travel"])
    h = mod["HOURS"]
    assert float(_v(first, "G46")) == h["prepPerMob"] and _f(first, "B46") == "=T28*G46"
    assert _f(first, "G47") == "=85*A47" and 85 * crews["mat"] == h["matSfPerHour"] and _f(first, "B47") == "=F24/G47"
    assert float(_v(first, "G48")) == h["poursPerHour"] and _f(first, "B48") == "=H33/G48"
    assert float(_v(first, "G49")) == h["unloadPerMob"] and _f(first, "B49") == "=G49*H49" and _f(first, "H49") == "=G55"
    assert _f(first, "G55") == "=T28" and _f(first, "B51") == "=((B6*2)/%d)*T28" % h["mph"]


def test_the_crews_and_the_hours_the_sheet_works_out_are_the_templates(mod):
    check_hours(mod)


def test_the_seed_lists_the_three_areas_and_the_five_crew_lines_the_code_names(mod):
    assert {a["id"]: a["name"] for a in PLAN.as_dict()["assemblies"] if a["id"].startswith("wb-gyp-")} == {
        v["id"]: v["name"] for v in mod["AREAS"].values()}
    for a in PLAN.as_dict()["assemblies"]:
        if a["id"].startswith("wb-gyp-"):
            assert a["unit"] == "SF" and a["default_work_types"] == ["gyp"]
            assert [ln["item_id"] for ln in a["lines"]] == ["wb-gyp-levelrock-2500-bag"]
    crew = PLAN.as_dict()["labor"]
    assert [r["id"] for r in crew if r["id"].startswith("gyp-")] == [
        "gyp-mat", "gyp-pour", "gyp-prep", "gyp-prepour", "gyp-unload"]
    for r in crew:
        if r["id"].startswith("gyp-"):
            assert r["unit"] == "hours" and r["rate"] == float(_v(FIRST, "C45")) and r["favorite"] is True
            assert r["default_work_types"] == ["gyp"]


# ── the arithmetic, by hand ──────────────────────────────────────────────────
def test_bags_are_fractional_and_the_sand_is_worked_out_from_them(mod):
    """Odd rule 7. 1,000 SF of soft surface at 3/4" is 1000 / 40 * 1.03 = 25.75 bags, not 26. With 1,000, 2,000 and 500 SF
    in the three areas the bags are 25.75 + 49.05 + 12.875 and the sand 180 lb a bag x 87.68 bags / 2000 x 1.1 = 8.68 tons."""
    got = node("""
      const G = require(%s);
      const row = (b, sf) => ({ assembly_id: G.AREA_ASSEMBLIES[b].id, measurement: sf, unit: "SF", bucket: b });
      const one = G.figures([row("soft", 1000)], {}, %s, []);
      const three = G.figures([row("soft", 1000), row("hard", 2000), row("corridor", 500)], {}, %s, []);
      console.log(JSON.stringify({ one: one.bags, three: three.bags, tons: three.tons }));
    """ % (json.dumps(str(MODULE)), json.dumps(FIRST), json.dumps(FIRST)))
    assert got["one"]["soft"] == pytest.approx(25.75) and got["one"]["total"] == pytest.approx(25.75)
    assert got["three"]["hard"] == pytest.approx(2000 / 42 * 1.03) and got["three"]["corridor"] == pytest.approx(12.875)
    assert got["three"]["total"] == pytest.approx(25.75 + 2000 / 42 * 1.03 + 12.875)
    assert got["tons"] == pytest.approx(180 * got["three"]["total"] / 2000 * 1.1)
    assert got["tons"] == pytest.approx(8.68, abs=0.005)


def test_a_bag_covers_what_the_sheet_says_at_each_thickness_and_mix(mod):
    got = node("""
      const G = require(%s);
      const y = (b, t, m) => G.yieldPerBag(b, t, m);
      console.log(JSON.stringify({
        at18: [y("soft", 0.75, 1.8), y("hard", 0.75, 1.8), y("corridor", 0.75, 1.8)],
        at14: [y("soft", 0.75, 1.4), y("hard", 0.75, 1.4), y("corridor", 0.75, 1.4)],
        eighth: [y("soft", 0.125, 1.8), y("hard", 0.125, 1.8)], strong: [y("soft", 0.125, 1.4), y("hard", 1.25, 1.4)],
        bad: [y("soft", 0, 1.8), y("soft", -1, 1.8), y("soft", "", 1.8), y("soft", "x", 1.4), y("soft", null, 1.8)],
        round: G.xlRound(34.5), roundDown: G.xlRound(34.4999999),
      }));
    """ % json.dumps(str(MODULE)))
    assert got["at18"] == [40, 42, 40]                       # 240 / 6, 252 / 6, 240 / 6
    assert got["at14"] == [34, 36, 34]                       # ROUND(240 / (6 * 1.1764705916)), ROUND(252 / ...)
    assert got["eighth"] == [240, 252]                       # 240 / 1, 252 / 1
    assert got["strong"] == [round(240 / (1 * 1.1764705915999)), round(252 / (10 * 1.1764705915999))]
    assert got["bad"] == [None] * 5, "a thickness that is not above zero has no yield; the sheet divides by zero"
    assert got["round"] == 35 and got["roundDown"] == 34


def test_a_blank_thickness_is_the_presets_and_a_typed_one_wins(mod):
    got = node("""
      const G = require(%s);
      const area = [{ assembly_id: G.AREA_ASSEMBLIES.soft.id, measurement: 4000, unit: "SF" }];
      const bags = (tab, set) => G.figures(area, set, tab, []).bags.soft;
      console.log(JSON.stringify({
        n25: [G.thicknessOf(%s, {}, "soft"), G.thicknessOf(%s, {}, "hard"), G.thicknessOf(%s, {}, "corridor")],
        typed: G.thicknessOf(%s, { thickness: { soft: "0.5" } }, "soft"), blank: G.thicknessOf(%s, { thickness: { soft: "" } }, "soft"),
        zero: G.thicknessOf(%s, { thickness: { soft: 0 } }, "soft"),
        defaults: bags(%s, {}), explicit: bags(%s, { thickness: { soft: 0.75 } }), thin: bags(%s, { thickness: { soft: 0.375 } }),
      }));
    """ % ((json.dumps(str(MODULE)),) + (json.dumps('Gyp (USG N25 1-4")'),) * 3 + (json.dumps(FIRST),) * 6))
    assert got["n25"] == [1.25, 1, 1.25]
    assert got["typed"] == 0.5 and got["blank"] == 0.75 and got["zero"] is None
    assert got["defaults"] == pytest.approx(4000 / 40 * 1.03) == got["explicit"]
    assert got["thin"] == pytest.approx(4000 / (240 / 3) * 1.03), "3/8 inch is 3 eighths, so a bag covers 80 SF"


def test_a_blank_corridor_thickness_follows_the_soft_surface_where_the_sheet_says_k10_is_g10(mod):
    # Gyp (USG 1-8")!K10 is `=G10`: type 1.25 for the soft surface, leave the corridor blank, and the workbook pours
    # the corridor at 1.25 too. Gyp (FR)!K10 is a typed 0.75, so there a blank corridor stays 0.75.
    got = node("""
      const G = require(%s);
      const corridor = [{ assembly_id: G.AREA_ASSEMBLIES.corridor.id, measurement: 1000, unit: "SF" }];
      const bags = (tab, set) => G.figures(corridor, set, tab, []).bags.corridor;
      const soft = { thickness: { soft: 1.25 } };
      console.log(JSON.stringify({
        usg: G.thicknessOf(%s, soft, "corridor"), fr: G.thicknessOf(%s, soft, "corridor"),
        n25: G.thicknessOf(%s, { thickness: { soft: 0.5 } }, "corridor"),
        typed: G.thicknessOf(%s, { thickness: { soft: 1.25, corridor: 0.5 } }, "corridor"),
        blankSoft: G.thicknessOf(%s, { thickness: { soft: "", corridor: "" } }, "corridor"),
        zeroSoft: G.thicknessOf(%s, { thickness: { soft: 0 } }, "corridor"),
        usgBags: bags(%s, soft), frBags: bags(%s, soft),
      }));
    """ % ((json.dumps(str(MODULE)),) + (json.dumps(FIRST), json.dumps("Gyp (FR)"), json.dumps('Gyp (USG N25 1-4")'),
                                          json.dumps(FIRST), json.dumps(FIRST), json.dumps(FIRST), json.dumps(FIRST),
                                          json.dumps("Gyp (FR)"))))
    assert got["usg"] == 1.25 and got["fr"] == 0.75
    assert got["n25"] == 0.5, "the corridor follows what is typed for the soft surface, not the tab's 1.25"
    assert got["typed"] == 0.5, "a typed corridor thickness still wins"
    assert got["blankSoft"] == 0.75 and got["zeroSoft"] is None
    assert got["usgBags"] == pytest.approx(1000 / (240 / 10) * 1.03), "1 1/4 inch is 10 eighths: 42.92 bags, not 25.75"
    assert got["frBags"] == pytest.approx(1000 / (240 / 6) * 1.03)


def test_an_area_with_no_usable_thickness_is_no_price_and_says_why(mod):
    got = node("""
      const G = require(%s);
      const rows = [{ assembly_id: G.AREA_ASSEMBLIES.hard.id, measurement: 1000, unit: "SF" }];
      const m = G.sectionMaterial(rows, { thickness: { hard: 0 } }, %s, { items: [] });
      const row = G.priceAreaRow(G.AREA_ASSEMBLIES.hard.id, 1000, { items: [], tab: %s, settings: { thickness: { hard: -2 } } });
      const empty = G.sectionMaterial([], {}, %s, { items: [] });
      console.log(JSON.stringify({ unpriceable: m.unpriceable, gyp: m.gyp, row: [row.priced_lines, row.broken_lines, row.total],
        empty: [empty.unpriceable === undefined, empty.gyp, empty.soundMatRolls, empty.tooling] }));
    """ % ((json.dumps(str(MODULE)),) + (json.dumps(FIRST),) * 3))
    assert "hard surface" in got["unpriceable"] and "thickness" in got["unpriceable"]
    assert got["gyp"] == 0 and got["row"] == [0, 1, 0]
    assert got["empty"] == [True, 0, 0, 0], "a bid with nothing measured prices nothing and is not an error"


def test_the_sound_mat_is_the_hard_area_in_whole_rolls_with_four_percent_over_at_the_tabs_price(mod):
    """ROUNDUP(hard / SF a roll * 1.04): 52,000 SF over a 494 SF roll is 109.5 rolls, so 110, at $237.12."""
    got = node("""
      const G = require(%s);
      const hard = (sf, set, tab) => G.figures([{ assembly_id: G.AREA_ASSEMBLIES.hard.id, measurement: sf, unit: "SF" }], set, tab || %s, []);
      const a = hard(52000, {});
      const exact = hard(494 * 100 / 1.04, {});          // exactly 100 rolls' worth, so 100 and not 101
      const none = hard(0, {});
      const fr = hard(37000, {}, %s);
      console.log(JSON.stringify({ rolls: a.rolls, mat: a.parts.soundMat, exact: exact.rolls, none: none.rolls,
        frRolls: fr.rolls, frPrice: fr.mat.price, frTruck: fr.truckload, truck: a.truckload }));
    """ % (json.dumps(str(MODULE)), json.dumps(FIRST), json.dumps(FR)))
    assert got["rolls"] == 110 and got["mat"] == pytest.approx(110 * 237.12)
    assert got["exact"] == 100 and got["none"] == 0
    assert got["frRolls"] == 104 and got["frPrice"] == 199.8 and got["frTruck"] == 448 and got["truck"] == 280


def test_the_truckload_follows_the_mat_on_the_first_four_tabs_and_is_a_typed_448_on_gyp_fr(mod):
    got = node("""
      const G = require(%s);
      const rows = [{ assembly_id: G.AREA_ASSEMBLIES.hard.id, measurement: 10000, unit: "SF" }];
      const t = (tab, mat) => G.figures(rows, { sound_mat: mat }, tab, []).truckload;
      const ids = (tab) => G.matList(tab).map((m) => m.id);
      console.log(JSON.stringify({
        usg: ids(%s).map((id) => t(%s, id)),
        fr: ids(%s).map((id) => t(%s, id)),
        foreign: [t(%s, "wb-gyp-sound-mat-elite-1-4in-roll"), t(%s, "no-such-mat"), t(%s, null)],
      }));
    """ % ((json.dumps(str(MODULE)),) + (json.dumps(FIRST),) * 2 + (json.dumps(FR),) * 2 + (json.dumps(FIRST),) * 3))
    assert got["usg"] == [280, 208, 208, 260, 384, 384, 384]
    assert got["fr"] == [448] * 6
    assert got["foreign"] == [280, 280, 280], "a mat this tab does not offer is not used: the tab's own opens"


def test_every_other_row_of_a_gyp_takeoff_is_an_extra_and_off_rows_add_nothing(mod):
    got = node("""
      const G = require(%s);
      const area = { assembly_id: G.AREA_ASSEMBLIES.soft.id, measurement: 1000, unit: "SF" };
      const other = { assembly_id: "something-kyle-made", measurement: 10, unit: "SF" };
      const off = Object.assign({}, other, { enabled: false });
      const price = (r) => r.assembly_id === "something-kyle-made" ? { total: 77 } : null;
      const m = (rows) => G.sectionMaterial(rows, {}, %s, { items: [], rowPrice: price });
      const slip = { assembly_id: G.AREA_ASSEMBLIES.hard.id, measurement: -500, unit: "SF" };
      console.log(JSON.stringify({ base: m([area]).extras, withOther: m([area, other]).extras, withOff: m([area, off]).extras,
        gyp: [m([area]).gyp, m([area, other]).gyp],
        slip: [m([area, slip]).gyp === m([area]).gyp, m([area, slip]).tooling === m([area]).tooling, m([slip]).soundMatRolls] }));
    """ % (json.dumps(str(MODULE)), json.dumps(FIRST)))
    assert got["withOther"] == pytest.approx(got["base"] + 77) and got["withOff"] == pytest.approx(got["base"])
    assert got["gyp"][0] == got["gyp"][1], "a row that is not an area adds no gypsum"
    assert got["slip"] == [True, True, 0], "a negative area is a slip and is not counted"


def test_the_tooling_by_hand(mod):
    """E57 + E58: ROUNDUP(tests x 35) + ROUNDUP(SF x 0.04), each its own ROUNDUP, over every area."""
    got = node("""
      const G = require(%s);
      console.log(JSON.stringify([[0, 0], [1, 0], [1000, 0], [1001, 0], [12345, 3], [0, 2], ["", ""]].map((a) => G.toolingCost(a[0], a[1]))));
    """ % json.dumps(str(MODULE)))
    assert got == [0, 1, 40, 41, 494 + 105, 70, 0]


def test_a_price_edited_on_the_library_row_reaches_the_price_and_no_row_prices_at_the_fallback(mod):
    got = node("""
      const G = require(%s);
      const rows = %s;
      const area = [{ assembly_id: G.AREA_ASSEMBLIES.soft.id, measurement: 4000, unit: "SF" }];
      const gyp = (items) => G.sectionMaterial(area, {}, %s, { items: items }).gyp;
      const edited = rows.map((r) => r.id === "wb-gyp-levelrock-2500-bag" ? Object.assign({}, r, { unit_cost: 20 }) : r);
      const primer = (items) => G.sectionMaterial(area, {}, %s, { items: items }).extras;
      const fr = (items) => G.sectionMaterial(area, {}, %s, { items: items }).gyp;
      console.log(JSON.stringify({ rows: gyp(rows), none: gyp([]), edited: gyp(edited), primerRows: primer(rows), primerNone: primer([]),
        frRows: fr(rows), frNone: fr([]), unit: G.unitPrice(rows, G.PRESETS[%s].primer), unitNone: G.unitPrice([], G.PRESETS[%s].primer) }));
    """ % (json.dumps(str(MODULE)), json.dumps(PLAN.as_dict()["items"]), json.dumps(FIRST), json.dumps(FIRST),
           json.dumps(FR), json.dumps(FIRST), json.dumps(FIRST)))
    assert got["rows"] == pytest.approx(got["none"], abs=1e-9), "the seeded rows and the fallbacks must price the same"
    assert got["edited"] == pytest.approx(got["rows"] * 20 / 14.08)
    assert got["primerRows"] == pytest.approx(got["primerNone"], abs=1e-9)
    assert got["frRows"] == pytest.approx(got["frNone"]) and got["frRows"] == pytest.approx(4000 / 40 * 1.03 * 14.65)
    assert got["unit"]["from"] == "library" and got["unitNone"]["from"] == "fallback"
    assert got["unit"]["cost"] == got["unitNone"]["cost"] == 891 / 53


def test_an_area_row_is_priced_in_the_shape_a_library_row_is_and_a_row_that_is_not_an_area_is_refused(mod):
    got = node("""
      const G = require(%s);
      const r = G.priceAreaRow(G.AREA_ASSEMBLIES.soft.id, 1000, { items: [], tab: %s, settings: {} });
      const none = G.priceAreaRow(G.AREA_ASSEMBLIES.soft.id, "", { items: [], tab: %s, settings: {} });
      let err = null;
      try { G.priceAreaRow("wb-epoxy-sys-dur-a-gard", 100, { items: [], tab: %s }); } catch (e) { err = String(e.message); }
      console.log(JSON.stringify({ total: r.total, perUnit: r.per_unit, lines: [r.priced_lines, r.broken_lines], role: r.rows[0].role,
        none: [none.priced_lines, none.total, none.per_unit], err: err,
        bucket: [G.bucketOfAssembly(G.AREA_ASSEMBLIES.hard.id), G.bucketOfAssembly("x"), G.bucketOfRow({ bucket: "corridor" }),
                 G.bucketOfRow({ assembly_id: G.AREA_ASSEMBLIES.soft.id }), G.bucketOfRow({ bucket: "nonsense" }), G.bucketOfRow(null)] }));
    """ % ((json.dumps(str(MODULE)),) + (json.dumps(FIRST),) * 3))
    assert got["total"] == pytest.approx(25.75 * 14.08) and got["perUnit"] == pytest.approx(25.75 * 14.08 / 1000)
    assert got["lines"] == [1, 0] and got["role"] == "Gypsum bags" and got["none"] == [0, 0, None]
    assert "not a Gyp area assembly" in got["err"]
    assert got["bucket"] == ["hard", None, "corridor", "soft", None, None]


def test_a_new_gyp_takeoff_is_one_row_for_each_area_the_intake_measured():
    got = node("""
      const G = require(%s);
      const asms = %s;
      console.log(JSON.stringify({ all: G.seedTakeoff(asms, 1000, 500, "250"), some: G.seedTakeoff(asms, 0, 800, ""), none: G.seedTakeoff(asms, "", "", ""),
        missing: G.seedTakeoff([], 1000, 0, 0), junk: G.seedTakeoff(null, 5, 5, 5) }));
    """ % (json.dumps(str(MODULE)), json.dumps(PLAN.as_dict()["assemblies"])))
    assert [(r["bucket"], r["measurement"], r["unit"]) for r in got["all"]] == [("soft", 1000, "SF"), ("hard", 500, "SF"), ("corridor", 250, "SF")]
    assert [r["bucket"] for r in got["some"]] == ["hard"] and got["none"] == [] and got["missing"] == [] and got["junk"] == []
    assert got["all"][0]["assembly_name"] == "Gypsum: soft surfaces"


def test_the_hours_the_sheet_suggests_are_its_own_arithmetic(mod):
    got = node("""
      const G = require(%s);
      const rows = [{ assembly_id: G.AREA_ASSEMBLIES.hard.id, measurement: 5950, unit: "SF" }, { assembly_id: G.AREA_ASSEMBLIES.soft.id, measurement: 12000, unit: "SF" }];
      const f = G.figures(rows, {}, %s, []);
      console.log(JSON.stringify({ h: G.sheetHours(f, 3, 90), bags: f.bags.total }));
    """ % (json.dumps(str(MODULE)), json.dumps(FIRST)))
    h = got["h"]
    assert h["prep"] == 12 and h["unload"] == 6 and h["mat"] == 10 and h["prePour"] is None
    assert h["pour"] == pytest.approx(got["bags"] / 75) and h["travel"] == pytest.approx(90 * 2 / 60 * 3)


# ── the layer ────────────────────────────────────────────────────────────────
def test_the_module_names_what_it_needs_and_touches_no_page():
    src = MODULE.read_text(encoding="utf-8")
    assert "needs excel-math.js loaded before it" in src and "needs library-core.js loaded before it" in src
    for forbidden in ("document.", "fetch(", "Date.now", "new Date", "localStorage", "window."):
        assert forbidden not in src, forbidden


# ── red without the code ─────────────────────────────────────────────────────
PIN_BREAKS = {
    "a bag covers a different amount an eighth": ("var YIELD_PER_EIGHTH = 240;", "var YIELD_PER_EIGHTH = 250;", check_constants),
    "a hard surface gets no extra yield": ("var HARD_EXTRA = 12;", "var HARD_EXTRA = 0;", check_constants),
    "the strong mix factor drifts": ("var STRONG_MIX_FACTOR = 1.1764705915999;", "var STRONG_MIX_FACTOR = 1.17647;", check_constants),
    "gypsum waste moves": ("var WASTE = { gyp: 0.03,", "var WASTE = { gyp: 0.04,", check_constants),
    "a gallon of primer covers more": ("var PRIMER_SF = 1200;", "var PRIMER_SF = 1500;", check_constants),
    "a moisture test costs more": ("var TOOLING = { moistureTest: 35,", "var TOOLING = { moistureTest: 40,", check_constants),
    "a mix takes another pound of sand": ('{ mix: 1.4, label: "3000+ psi (1.4)", sandLb: 140 }', '{ mix: 1.4, label: "3000+ psi (1.4)", sandLb: 150 }', check_constants),
    "the crew on the pour changes": ("var CREWS = { prePour: 8, prep: 8, mat: 7, pour: 8,", "var CREWS = { prePour: 8, prep: 8, mat: 7, pour: 9,", check_hours),
    "a fallback is not the template's price": (
        'var USG_BAG = row("wb-gyp-levelrock-2500-bag", 14.08, "D23");', 'var USG_BAG = row("wb-gyp-levelrock-2500-bag", 14.5, "D23");', check_prices),
    "the FR bag reads the wrong cell": (
        'bag: row("wb-gyp-treadstone-fr25-bag", 14.65, "D23"),', 'bag: row("wb-gyp-treadstone-fr25-bag", 14.65, "D24"),', check_prices),
    "the N25 tab opens on a thinner soft area": (
        "thickness: { soft: 1.25, hard: 1, corridor: 1.25 } }),", "thickness: { soft: 1, hard: 1, corridor: 1.25 } }),", check_presets),
    "a blank corridor stops following the soft surface": (
        "corridorFollowsSoft: true", "corridorFollowsSoft: false", check_presets),
    "the ULTRA tab opens on the wrong mat": (
        'defaultMat: "wb-gyp-sound-mat-sam-n12-ultra-3-16in-roll" }),', 'defaultMat: "wb-gyp-sound-mat-sam-n25-1-4in-roll" }),', check_presets),
    "a truckload is wrong": (
        'mat("wb-gyp-sound-mat-sam-n40-3-8in-roll",        214.5,  330, 208, "39"),', 'mat("wb-gyp-sound-mat-sam-n40-3-8in-roll",        214.5,  330, 209, "39"),', check_presets),
    "a roll covers another area": (
        'mat("wb-gyp-sound-mat-sam-n12-1-8in-roll",        237.12, 494, 280, "37"),', 'mat("wb-gyp-sound-mat-sam-n12-1-8in-roll",        237.12, 490, 280, "37"),', check_presets),
    "Gyp (FR) ISO strip goes as far as the USG roll": ("iso: row(\"wb-gyp-iso-strip-roll\", 27, \"D28\"), isoSf: 1200,", "iso: row(\"wb-gyp-iso-strip-roll\", 27, \"D28\"), isoSf: 2160,", check_constants),
}


@pytest.mark.parametrize("name", sorted(PIN_BREAKS))
def test_the_pins_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    old, new, check = PIN_BREAKS[name]
    src = MODULE.read_bytes().decode("utf-8").replace(chr(13) + chr(10), chr(10))
    assert src.count(old) == 1, "the mutation anchor is in the module %d times, not once" % src.count(old)
    scratch = tmp_path / "frontend" / "js"
    scratch.mkdir(parents=True)
    (scratch / "gyp-takeoff.js").write_bytes(src.replace(old, new).encode("utf-8"))
    for dep in ("excel-math.js", "library-core.js"):
        (scratch / dep).write_bytes((FRONTEND / "js" / dep).read_bytes())
    broken = load_mod(scratch / "gyp-takeoff.js")
    check(load_mod())                                   # the real module passes it
    with pytest.raises(AssertionError):
        check(broken)
