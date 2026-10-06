"""Library pricing, recorded before the v2 program gives materials new columns.

backend/tests/fixtures/library_pricing_golden.json holds what js/library-core.js (TWLib) answers for
874 deliberately awkward inputs: priceLine and priceAssembly over one baseline material varied one
field at a time (waste, roundup, pack size, coverage, unit cost) and across the combinations that
interact; every area an estimator or a pasted spreadsheet might hand it; lines and catalogs of every
shape; legacy rows written before waste_pct, buy_qty and roundup existed; and whole assemblies,
Kyle's printed flake system among them. It was cut ONCE from a clean `git archive` of origin/staging
(meta.commit says which) by tests/js/gen-library-golden.js, whose recipe lists inputs only.

Every material in the product prices through this file, and so does every bid already saved. Phase
11 adds price_breaks, bulk_cost and coverage_basis to materials; Phase 12 prices Epoxy off them. A
row WITHOUT the new columns must keep pricing exactly as it does now, and where a change is meant it
shows up as a diff of lines somebody can read. The comparison is assert.deepStrictEqual in node, so
a -0 or a NaN cannot turn into 0 or null unseen (see test_polish_chain_golden.py for why).

Run under node; a missing node FAILS under CI (tests/_node.py).
"""
import json
import re

import pytest

from _golden_support import FIXTURES, break_source, compare, generate, load
from _node import require_node

GOLDEN = FIXTURES / "library_pricing_golden.json"
GENERATOR = "gen-library-golden.js"
MODULE = "js/library-core.js"


@pytest.fixture(scope="module")
def node():
    return require_node()


@pytest.fixture(scope="module")
def golden():
    return load(GOLDEN)


@pytest.fixture(scope="module")
def vectors(golden):
    return {v["id"]: v for v in golden["vectors"]}


# ── the comparison itself ────────────────────────────────────────────────────
def test_this_trees_library_pricing_answers_exactly_as_the_golden_says(node):
    """Red here means a price moved: read the first difference and decide whether it is the change
    you meant. If it is, regenerate (the message says how) and review the fixture diff."""
    proc = compare(GENERATOR, GOLDEN)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"ok": True, "n": load(GOLDEN)["meta"]["n"]}


def test_the_recipe_is_deterministic(node):
    assert generate(GENERATOR) == generate(GENERATOR)


def test_the_golden_says_where_it_came_from(golden):
    meta = golden["meta"]
    assert re.fullmatch(r"[0-9a-f]{40}", meta["commit"])
    assert meta["recipe_version"] == 1
    assert meta["n"] == len(golden["vectors"]) == len({v["id"] for v in golden["vectors"]})
    assert meta["generator"] == "backend/tests/js/gen-library-golden.js"


# ── the golden is anchored to things that are true outside it ────────────────
@pytest.mark.parametrize("vector_id, packs, cost", [
    ("line/kyle/opf/area-2875", 11, 939.21),
    ("line/kyle/glaze/area-2875", 23, 1834.42),
    ("line/kyle/armor/area-2875", 4, 1529.79),
])
def test_kyles_printed_sheet_is_reproduced(vectors, vector_id, packs, cost):
    """The model is lifted from Kyle's flake system at 2,875 SF: OPF 11 Gal / $939.21, Glaze #4
    23 Gal / $1,834.42, Armor Top Satin 4 Kit / $1,529.79. The golden holds those numbers, so it is
    a record of the SHEET and not just of whatever the code happens to say."""
    out = vectors[vector_id]["out"]
    assert out["packs"] == packs and round(out["cost"], 2) == cost


def test_the_assembly_sums_unrounded_lines(vectors):
    """Kyle's sheet prints $4,303.41 for the system while its three lines add to $4,303.42: the sheet
    sums the UNROUNDED values, and so does this."""
    out = vectors["asm/kyleFlake/area-2875"]["out"]
    assert round(out["total"], 2) == 4303.42 and out["priced_lines"] == 3 and out["broken_lines"] == 0


def test_an_area_that_divides_exactly_does_not_buy_a_spare_pack(vectors):
    """27,500 / 250 * (1 + 0) is 110 exactly; with waste it is 110.00000000000001 in floating point
    and a bare ceil() buys a 111th pack. The float guard is what keeps the round numbers an
    estimator checks by hand right."""
    out = vectors["line/baseline/area-27500"]["out"]
    assert out["needed"] == 110 and out["packs"] == 110 and out["cost"] == 11000
    guarded = vectors["line/waste/4/5/area-27500"]["out"]            # 5% waste on the same floor
    assert guarded["needed"] == 115.5 and guarded["packs"] == 116


def test_a_row_older_than_the_columns_still_reads_as_it_always_did(vectors):
    """No waste_pct reads as 5%, no roundup reads as yes, no buy_qty reads as a pack of one."""
    for vid in ("line/legacy/area-2875", "line/legacyBare/area-2875"):
        out = vectors[vid]["out"]
        assert (out["waste_pct"], out["roundup"], out["buy_qty"]) == (5, True, 1), vid
    assert vectors["line/legacy/area-2875"]["out"]["packs"] == 11


def test_waste_and_pack_size_are_clamped_and_defaulted(vectors):
    assert vectors["waste/2"]["out"] == 5            # no waste_pct at all
    assert vectors["waste/8"]["out"] == 100          # 150 is clamped to 100
    assert vectors["waste/9"]["out"] == 5            # negative reads as the default
    assert vectors["buy/0"]["out"] == 1 and vectors["buy/3"]["out"] == 1      # absent and 0 are a pack of one


def test_the_material_owns_the_numbers_not_the_line(vectors):
    """Hanz, 2026-09-22: coverage, waste and roundup come from the MATERIAL. Numbers typed on a line
    are ignored."""
    out = vectors["line/shape/numbersOnTheLineAreIgnored"]["out"]
    assert (out["coverage"], out["waste_pct"], out["roundup"], out["buy_qty"], out["packs"]) == (250, 0, True, 1, 12)


def test_roundup_off_buys_exactly_what_is_needed(vectors):
    on = vectors["line/cross/w10/rtrue/b7/c125/area-2875"]["out"]
    off = vectors["line/cross/w10/rfalse/b7/c125/area-2875"]["out"]
    assert on["packs"] == 4 and on["units"] == 28
    assert off["packs"] is None and off["units"] == off["needed"] == 25.3


def test_every_kind_of_answer_is_in_the_file(vectors):
    kinds = set()
    for v in vectors.values():
        if v["fn"] != "priceLine" or not isinstance(v.get("out"), dict):
            continue
        o = v["out"]
        kinds.add(("priced" if o.get("priced") else "unpriced") if o.get("ok") else o.get("reason"))
    assert kinds == {"priced", "unpriced", "no_item", "missing_item", "no_coverage", "no_cost"}


def test_a_broken_line_is_counted_but_an_unfilled_one_is_not(vectors):
    mixed = vectors["asm/brokenMixed/area-2875"]["out"]
    assert mixed["priced_lines"] == 2 and mixed["broken_lines"] == 3
    unfilled = vectors["asm/onlyUnfilled/area-2875"]["out"]
    assert unfilled["priced_lines"] == 0 and unfilled["broken_lines"] == 0 and unfilled["total"] == 0


def test_what_json_would_hide_is_in_the_file():
    raw = GOLDEN.read_text(encoding="utf-8")
    for tag in ('{"$":"-0"}', '{"$":"NaN"}', '{"$":"undefined"}', '{"$":"Infinity"}'):
        assert tag in raw, tag


def test_both_helper_families_and_the_export_surface_are_covered(vectors):
    assert {"priceLine", "priceAssembly", "wastePct", "buyQty", "findItem", "num"} <= {v["fn"] for v in vectors.values()}
    assert "exports" in vectors


# ── red without the code: break a COPY of the module and watch the comparison fail ────────────────
MUTATIONS = {
    "the float guard on CEIL is removed": (
        "var packs = Math.ceil(parseFloat((needed / pack).toPrecision(12)));",
        "var packs = Math.ceil(needed / pack);",
        ["line/", "golden 110, now 111"]),
    "an absent waste_pct reads as 0, not 5": (
        "if (v === null || v < 0) return 5;",
        "if (v === null || v < 0) return 0;",
        ["line/legacy/", "golden 5, now 0"]),
    "an absent roundup reads as no": (
        "var roundup = (item.roundup === undefined || item.roundup === null) ? true : !!item.roundup;",
        "var roundup = (item.roundup === undefined || item.roundup === null) ? false : !!item.roundup;",
        ["line/legacy/", "golden true, now false"]),
    "negative zero becomes zero": (
        "return Math.min(v, 100);",
        "return Math.min(v, 100) + 0;",
        ["waste/18", "golden -0, now 0"]),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_the_golden_goes_red_when_the_code_changes(node, tmp_path, name):
    """The proof the golden is not decoration: each change below is the kind a refactor makes by
    accident, applied to a scratch copy, and each must fail the comparison BY NAME."""
    old, new, expected = MUTATIONS[name]
    frontend = break_source(tmp_path, MODULE, old, new)
    proc = compare(GENERATOR, GOLDEN, frontend, "--limit", "100000")
    assert proc.returncode == 1, "the golden did not notice: " + name + "\n" + proc.stdout
    assert "GOLDEN MASTER MISMATCH" in proc.stdout
    for fragment in expected:
        assert fragment in proc.stdout, (fragment, proc.stdout[:1500])
