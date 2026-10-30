"""An assembly line's OWN coverage per unit, for that assembly only (Hanz, 2026-10-30).

"for v2 items and assemblies: under the Assemblies tab, we should be able to edit the Coverage per
unit in the Assemblies tab." He chose THIS ASSEMBLY ONLY: the same primer covers 300 SF in one
system and 250 in another. Since 2026-09-22 coverage, waste and roundup lived on the material only;
this reverses that for COVERAGE ONLY, on a new line key, `coverage_override`.

WHAT THIS FILE DEFENDS, each executed (node over the real library-core.js, the real library.py,
TestClient over the real route with the fake Supabase):

  * priceLine divides by a positive `coverage_override`, and by the material's coverage otherwise.
    Blank, zero, a negative or nonsense is "use the material's".
  * The legacy `coverage` key old lines still carry is STILL ignored, and the server still drops it.
    Reusing it would quietly bring pre-2026-09-22 numbers back into every price.
  * The server keeps, checks and returns the new key, and stores nothing for a line without one.
  * EXISTING ASSEMBLIES PRICE TO THE CENT AS THEY DID: every assembly the seed plans from Kyle's
    workbook, shaped by the server the way the page receives it (legacy `coverage` on every line
    included), priced at several areas with and without Bulk Discount, by the library-core.js of
    staging 975222e6 (before this change) and by this one. Byte-identical answers.
"""
import json
import pathlib
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import library
import main
import profiles

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "library-core.js"
BASE_COMMIT = "975222e6"          # origin/staging when this branch was cut

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
client = TestClient(main.app)

ITEMS = [
    {"id": "opf", "name": "OPF", "unit": "Gal", "buy_qty": 1, "unit_cost": 85.3827,
     "coverage": 275, "waste_pct": 0, "roundup": True},
    {"id": "bare", "name": "No coverage yet", "unit": "Gal", "buy_qty": 1, "unit_cost": 50, "waste_pct": 0},
]


def node(script: str, core: pathlib.Path = CORE):
    prelude = "const L = require(%s);\nconst out = (v) => console.log(JSON.stringify(v));\n" % json.dumps(str(core))
    proc = subprocess.run(["node", "-e", prelude + script], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def price(line, area=2750):
    return node("out(L.priceLine(%s, %s, %s))" % (json.dumps(line), json.dumps(ITEMS), area))


# ── the pricer ────────────────────────────────────────────────────────────────────────────────
@needs_node
def test_a_line_with_its_own_coverage_divides_by_it():
    """2,750 SF: OPF at its own 275 is 10 gallons; this assembly's 250 is 11. The priced row says
    which coverage it used and what the material says, for the page's "Material: 275" line."""
    own = price({"item_id": "opf", "coverage_override": 250})
    assert (own["coverage"], own["qty"], own["coverage_own"], own["material_coverage"]) == (250, 11, True, 275)
    assert round(own["cost"], 4) == round(11 * 85.3827, 4)
    assert price({"item_id": "opf", "coverage_override": "250"})["qty"] == 11, "a typed string is a number"


@needs_node
@pytest.mark.parametrize("raw", [None, "", 0, "0", -250, "abc"])
def test_a_line_without_a_positive_coverage_of_its_own_uses_the_materials(raw):
    """And answers in exactly the shape it always did: no coverage_own, no material_coverage."""
    got = price({"item_id": "opf", "coverage_override": raw})
    assert got == price({"item_id": "opf"}), got
    assert got["coverage"] == 275 and "coverage_own" not in got and "material_coverage" not in got


@needs_node
def test_the_legacy_line_coverage_key_is_still_ignored():
    """Lines saved before 2026-09-22 still carry `coverage`. It must not price, alone or beside the
    new key (the new key wins, the legacy one never does)."""
    assert price({"item_id": "opf", "coverage": 999})["coverage"] == 275
    assert price({"item_id": "opf", "coverage": 999, "coverage_override": 250})["coverage"] == 250


@needs_node
def test_a_line_can_price_a_material_that_has_no_coverage_yet():
    """The override is a coverage like any other: a material with none of its own is "Needs a
    coverage" on its own and prices once this assembly gives it one. A deleted material stays
    "Item removed" whatever the line says."""
    assert price({"item_id": "bare"})["reason"] == "no_coverage"
    got = price({"item_id": "bare", "coverage_override": 275})
    assert got["ok"] and got["qty"] == 10 and got["material_coverage"] is None, got
    assert price({"item_id": "gone", "coverage_override": 275})["reason"] == "missing_item"


@needs_node
def test_two_takeoff_rows_of_one_assembly_pool_its_overridden_coat_as_one_purchase():
    """The section pool (pricePool) buys one coat once across rows. Two 1,375 SF rows at this
    assembly's 250 need 5.5 gallons each: alone that is 6 + 6, pooled it is 11."""
    got = node("const asm = {id:'a', lines:[{item_id:'opf', coverage_override:250}]};"
               "const items = %s;"
               "const rows = [L.priceAssembly(asm, items, 1375), L.priceAssembly(asm, items, 1375)];"
               "const pooled = L.pricePool(rows);"
               "out([rows[0].rows[0].qty + rows[1].rows[0].qty, pooled[0].rows[0].pooled.packs])"
               % json.dumps(ITEMS))
    assert got == [12, 11], got


# ── the server ────────────────────────────────────────────────────────────────────────────────
def test_the_server_keeps_checks_and_never_invents_a_line_coverage():
    lines = library.validate_assembly({"name": "x", "lines": [
        {"item_id": "a", "coverage_override": 300},
        {"item_id": "b", "coverage_override": "$1,250"},
        {"item_id": "c", "coverage_override": ""},
        {"item_id": "d", "coverage_override": 0},
        {"item_id": "e", "coverage_override": None},
        {"item_id": "f", "coverage": 999},
    ]})["lines"]
    assert [ln.get("coverage_override") for ln in lines] == [300.0, 1250.0, None, None, None, None]
    # not set is NOT stored: a line nobody typed one on saves exactly as it did before this change
    assert [("coverage_override" in ln) for ln in lines] == [True, True, False, False, False, False]
    assert all("coverage" not in ln for ln in lines), "the legacy key came back: %r" % lines


@pytest.mark.parametrize("bad, word", [(-5, "negative"), ("abc", "number"), (2e6, "large"), (True, "number")])
def test_an_impossible_line_coverage_is_refused_with_a_readable_message(bad, word):
    """The same rule and the same ceiling the material's own coverage has (validate_item)."""
    with pytest.raises(library.ValidationError) as e:
        library.validate_assembly({"name": "x", "lines": [{"item_id": "a", "coverage_override": bad}]})
    assert word in str(e.value) and "Coverage" in str(e.value)


def test_a_stored_line_coverage_reads_back_and_garbage_reads_as_not_set():
    shaped = library._shape_assembly({"id": "a", "name": "x", "lines": [
        {"item_id": "a", "coverage_override": 300}, {"item_id": "b"},
        {"item_id": "c", "coverage_override": "nan"}, {"item_id": "d", "coverage_override": -1},
        {"item_id": "e", "coverage_override": 5e9}]})
    assert [ln["coverage_override"] for ln in shaped["lines"]] == [300.0, None, None, None, None]


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_items": [], "library_assemblies": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(library, "get_client", lambda: fake)
    return st


@pytest.fixture()
def as_user(monkeypatch):
    """An ordinary estimator: editing an assembly's lines has never needed admin, and setting a
    line's own coverage is a line edit through the same route, so it needs no more than that."""
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "somebody-else@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"id": "u1", "email": e, "role": "user"})


def test_a_line_coverage_round_trips_through_the_assembly_route_with_its_version_check(store, as_user):
    """The page's own save: PATCH the whole lines array, declaring the version it is editing. The
    override sticks, comes back on GET, and clearing it (null) takes it off the stored line."""
    asm = library.create_assembly({"name": "MACRO Flake", "lines": [{"item_id": "opf"}]}, None)
    r = client.patch("/api/library/assemblies/%s" % asm["id"], json={
        "expected_updated_at": asm["updated_at"],
        "lines": [{"item_id": "opf", "coverage": 999, "coverage_override": 300}]})
    assert r.status_code == 200, r.text
    assert r.json()["assembly"]["lines"][0]["coverage_override"] == 300.0
    assert store["library_assemblies"][0]["lines"][0] == {
        "role": "", "item_id": "opf", "note": None, "coverage_override": 300.0}
    got = client.get("/api/library/assemblies").json()["assemblies"][0]["lines"][0]
    assert got["coverage_override"] == 300.0
    r2 = client.patch("/api/library/assemblies/%s" % asm["id"], json={
        "expected_updated_at": r.json()["assembly"]["updated_at"],
        "lines": [{"item_id": "opf", "coverage_override": None}]})
    assert r2.status_code == 200, r2.text
    assert "coverage_override" not in store["library_assemblies"][0]["lines"][0]
    assert r2.json()["assembly"]["lines"][0]["coverage_override"] is None


def test_a_bad_line_coverage_is_a_readable_400_and_writes_nothing(store, as_user):
    asm = library.create_assembly({"name": "MACRO Flake", "lines": [{"item_id": "opf"}]}, None)
    r = client.patch("/api/library/assemblies/%s" % asm["id"], json={
        "lines": [{"item_id": "opf", "coverage_override": -5}]})
    assert r.status_code == 400 and "negative" in r.text
    assert store["library_assemblies"][0]["lines"][0] == {"role": "", "item_id": "opf", "note": None}


# ── existing assemblies price to the cent as they did ─────────────────────────────────────────
@needs_node
def test_every_seeded_assembly_prices_exactly_as_before_this_change(tmp_path):
    """THE TO-THE-CENT PROOF. Every assembly and item the seed plans from Kyle's workbook, each line
    given a legacy `coverage` of 999 the way a pre-2026-09-22 row still carries one, put through the
    server's create + read-shape (the exact JSON GET /api/library/assemblies hands the page, with
    `coverage_override: null` on every line), then priced at five areas, bulk off and on, by
    library-core.js as it stood at 975222e6 and as it stands now. The two answers must be identical,
    field for field, not merely close.

    Mutation: make priceLine read `line.coverage`, or treat a null override as 0, or add a key to an
    unchanged answer: the comparison fails."""
    old = subprocess.run(["git", "show", BASE_COMMIT + ":frontend/js/library-core.js"],
                         cwd=str(FRONTEND.parent), capture_output=True, encoding="utf-8")
    if old.returncode != 0:
        pytest.skip("%s is not readable in this checkout: %s" % (BASE_COMMIT, old.stderr.strip()))
    old_core = tmp_path / "library-core-before.js"
    old_core.write_text(old.stdout, encoding="utf-8")
    assert "coverage_override" not in old.stdout, "the base commit already has the change"

    import _seed_support
    plan = _seed_support.PLAN.as_dict()
    items, asms = plan["items"], plan["assemblies"]
    assert len(asms) >= 40 and len(items) >= 60, (len(asms), len(items))
    shaped = []
    for a in asms:
        row = dict(a, lines=[dict(ln, coverage=999) for ln in a.get("lines") or []])
        shaped.append(library._shape_assembly(row))
    assert all(ln["coverage_override"] is None and ln["coverage"] == 999.0
               for a in shaped for ln in a["lines"])
    data = tmp_path / "lib.json"
    data.write_text(json.dumps({"items": items, "asms": shaped}), encoding="utf-8")
    script = ("const D = JSON.parse(require('fs').readFileSync(%s, 'utf8'));"
              "const res = [];"
              "for (const a of D.asms) for (const area of [1, 275, 2875, 12500, 40000])"
              "  for (const bulk of [false, true])"
              "    res.push([a.id, area, bulk, L.priceAssembly(a, D.items, area, {bulk: bulk})]);"
              "out(res);" % json.dumps(str(data)))
    before, after = node(script, old_core), node(script)
    assert len(before) == len(shaped) * 10
    priced = sum(1 for _, _, _, p in after if p["priced_lines"] > 0)
    assert priced > len(shaped) * 5, "too few seeded assemblies priced for this to prove anything"
    diff = [(b[0], b[1], b[2]) for b, a in zip(before, after) if json.dumps(b) != json.dumps(a)]
    assert diff == [], "these assemblies price differently than before: %r" % diff[:10]
