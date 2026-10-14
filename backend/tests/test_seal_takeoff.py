"""Phase 15: js/seal-takeoff.js, the part of the Seal tabs that a library row cannot say, and the seed rows around it.

The contract it follows is the one Dye, Joint Filler and the Epoxy patch follow (docs/v2-architecture.md, rule 3): the FORMULA
is code, the PRICES it reads are editable library rows, and a constant in the code is only the fallback for a database the
seed has not reached. What is tested here:

  * ROW = FALLBACK   every constant in PRICE_ROWS equals the row the seed script plans, and both are the template's own cell.
  * THE FORMULA IS THE TEMPLATE'S   the patch is IF(B10="New", new, reno), the tooling is $0.27 a square foot with a $150
                     floor, rounded up, and the joint filler kit is one for every 3,500 square feet, all read back out of the
                     template's cells.
  * THE ROWS ARE READ   a price changed on the library row changes the price; with no row the fallback prices.
  * THE PLAN IS LOUD   a Seal tab that Kyle changes stops the seed with the cell named, and never seeds a price for a rule the
                     code no longer matches.
  * THE PLAN MATCHES THE CODE   the assemblies a new option opens with are in the plan.

How the whole thing prices against the workbook is test_seal_v2_proof.py.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

import pytest

from _node import require_node
from _seed_support import PLAN, SHEETS, edited, seed

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
MODULE = FRONTEND / "js" / "seal-takeoff.js"


def node(code: str):
    node_path = require_node()
    proc = subprocess.run([node_path, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def mod():
    return node("""
      const S = require(%s);
      console.log(JSON.stringify({ PRICE_ROWS: S.PRICE_ROWS, TOOLING: S.TOOLING, DEFAULT: S.DEFAULT_ASSEMBLY }));
    """ % json.dumps(str(MODULE)))


def _item(id_):
    return next(i for i in PLAN.as_dict()["items"] if i["id"] == id_)


def _asm(id_):
    return next(a for a in PLAN.as_dict()["assemblies"] if a["id"] == id_)


# ── row = fallback = the template's cell ─────────────────────────────────────────────────────────
def test_every_price_row_constant_is_the_seeded_row_and_the_templates_cell(mod):
    seal = SHEETS["Seal"]
    f = seal.formula("C17")
    m = re.fullmatch(r'=IF\(B10="New",(\d*\.?\d+),(\d*\.?\d+)\)', f)
    assert m, "Seal!C17 is not the patch rule the code copies: %r" % f
    new, reno = float(m.group(1)), float(m.group(2))
    rows = mod["PRICE_ROWS"]
    assert (rows["patchNew"]["fallback"], rows["patchReno"]["fallback"]) == (new, reno) == (0.05, 0.15)
    for key in ("patchNew", "patchReno"):
        assert rows[key]["cell"] == "C17"
        row = _item(rows[key]["id"])
        assert row["unit_cost"] == rows[key]["fallback"] and row["unit"] == "SF" and row["coverage"] == 1.0
        assert row["roundup"] is False and row["default_work_types"] == ["seal"], "a price source, read per square foot"


def test_the_tooling_constants_are_the_templates(mod):
    seal = SHEETS["Seal"]
    assert seal.formula("D51") == "=ROUNDUP(IF((B51*C51)>150,(B51*C51),150),0)"
    assert seal.value("C51") == mod["TOOLING"]["perSf"] == 0.27 and mod["TOOLING"]["min"] == 150
    assert seal.formula("B51") == "=B35", "the tooling is charged on the whole area"
    assert SHEETS["Seal (+Jnts)"].formula("C51") == "=Seal!C51", "Seal (+Jnts) reads its tooling rate from Seal"


def test_the_sealer_and_the_joint_filler_are_the_templates_prices_and_coverage():
    seal, jnts = SHEETS["Seal"], SHEETS["Seal (+Jnts)"]
    assert seal.value("C20") == seal.value("C21") == _item("wb-seal-sealer")["unit_cost"] == 0.15
    kit = _item("wb-seal-joint-filler-kit")
    assert kit["unit_cost"] == jnts.value("C29") == 500 and kit["coverage"] == 3500.0 and kit["roundup"] is True
    assert jnts.formula("B29") == '=ROUNDUP(IF(E29="yes",(E18/3500),0),0)'
    assert seal.formula("D20") == "=B20*C20" and seal.formula("B20") == "=E18", "a sealer line is the area at its price"


# ── the plan matches the code ────────────────────────────────────────────────────────────────────
def test_the_assemblies_a_new_option_opens_with_are_in_the_plan_and_say_what_the_sheet_ships(mod):
    assert mod["DEFAULT"] == {"Seal": "wb-seal-2-coats", "Seal (+Jnts)": "wb-seal-jnts-2-coats"}
    for tab, id_ in mod["DEFAULT"].items():
        assert _asm(id_)["default_work_types"] == ["seal"] and _asm(id_)["unit"] == "SF", tab
    two = _asm("wb-seal-2-coats")["lines"]
    assert [l["item_id"] for l in two] == ["wb-seal-sealer", "wb-seal-sealer"], "the sheet ships with both sealer lines filled in"
    assert [l["item_id"] for l in _asm("wb-seal-1-coat")["lines"]] == ["wb-seal-sealer"]
    assert [l["item_id"] for l in _asm("wb-seal-jnts-2-coats")["lines"]] == ["wb-seal-sealer", "wb-seal-sealer", "wb-seal-joint-filler-kit"]
    assert [l["item_id"] for l in _asm("wb-seal-jnts-1-coat")["lines"]] == ["wb-seal-sealer", "wb-seal-joint-filler-kit"]


def test_the_seal_crew_is_three_lines_by_the_day_at_the_sheets_rate_for_the_seal_tab_only():
    labor = {r["id"]: r for r in PLAN.as_dict()["labor"] if r["id"].startswith("seal-")}
    assert sorted(labor) == ["seal-install", "seal-jointfill", "seal-mockup"]
    for r in labor.values():
        assert r["rate"] == SHEETS["Seal"].value("C37") == 33 and r["unit"] == "days" and r["default_work_types"] == ["seal"]
        assert r["favorite"] is True and r["guys_auto"] is False
    calc = {c["line_id"]: c for c in PLAN.as_dict()["labor_calc"] if c["line_id"].startswith("seal-")}
    assert calc["seal-install"]["guys"] == SHEETS["Seal"].value("A37") == 3
    assert calc["seal-mockup"]["guys"] == SHEETS["Seal"].value("A40") == 3
    assert calc["seal-jointfill"]["guys"] == 2 and all(c["mode"] == "fixed" and c["hours_per_day"] == 8 for c in calc.values())


def test_the_seal_rows_are_only_ever_inserted_and_never_replace_a_row_somebody_edited():
    stmts = [s for s in seed.statements(PLAN) if "wb-seal" in s or "'seal-" in s]
    assert len(stmts) == 4 + 4 + 3 + 3
    assert all(s.startswith("insert into public.") and s.endswith("on conflict (id) do nothing;") or s.endswith("on conflict (line_id) do nothing;")
               for s in stmts)
    assert not [s for s in stmts if re.search(r"\b(update|delete|drop|truncate)\b", s, re.I)]


def test_the_plan_names_what_v2_does_not_carry_for_kyle():
    gaps = " ".join(PLAN.as_dict()["gaps"])
    for must in ("Exclude Patching", "demo tooling, slurry hardener and plastic", "joint filler crew's days", "OWN lodging, per diem and travel labor"):
        assert must in gaps, must


# ── the plan is loud ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind,sheet,addr,value,words", [
    ("f", "Seal", "C17", "=IF(B10=\"New\",0.05)", "Seal!C17"),
    ("f", "Seal", "C17", "=0.05", "Seal!C17"),
    ("v", "Seal", "C21", 0.2, "the two sealer lines no longer cost the same"),
    ("v", "Seal", "A21", "Primer", "Seal!A20 and A21 should both name the sealer"),
    ("f", "Seal (+Jnts)", "B29", "=ROUNDUP(IF(E29=\"yes\",(E18/4000),0),0)", "Seal (+Jnts)!B29"),
    ("f", "Seal (+Jnts)", "A42", "=2", "Seal (+Jnts)!A42"),
])
def test_a_seal_tab_that_kyle_changes_stops_the_seed_with_the_cell_named(kind, sheet, addr, value, words):
    with edited(sheet, kind, addr, value):       # "f" edits the formula sheet's cell, "v" the saved values'
        with pytest.raises(seed.PlanError) as e:
            seed.make_plan(sheets=SHEETS, only="seal")
    assert words in str(e.value), str(e.value)
    assert seed.make_plan(sheets=SHEETS, only="seal").counts() == {"items": 4, "assemblies": 4, "labor": 3, "labor_calc": 3}


# ── what the module does, run ─────────────────────────────────────────────────────────────────────
def test_the_tooling_the_patch_and_the_material_are_the_sheets_run_in_node():
    got = node("""
      const S = require(%s);
      const items = [{ id: "wb-seal-patch-new", unit_cost: 0.05, buy_qty: 1 }, { id: "wb-seal-patch-reno", unit_cost: 0.15, buy_qty: 1 }];
      const price = (row) => ({ total: Number(row.measurement) * 0.3 });
      console.log(JSON.stringify({
        tooling: [0, 100, 555, 556, 1000, 12345].map((sf) => [sf, S.toolingCost(sf)]),
        patch: { none: S.patchCost(items, 0, false), new: S.patchCost(items, 1000, false), reno: S.patchCost(items, 1000, true),
                 fallback: S.patchCost([], 1000, true), repriced: S.patchCost([{ id: "wb-seal-patch-new", unit_cost: 0.5, buy_qty: 1 }], 1000, false) },
        from: [S.unitPrice(items, "patchNew").from, S.unitPrice([], "patchNew").from],
        material: S.sectionMaterial([{ measurement: 1000 }, { measurement: 500, enabled: false }, null],
                                    { items: items, sf: 1000, reno: false, rowPrice: price }),
        seed: [S.seedTakeoff("Seal", [{ id: "wb-seal-2-coats", name: "Two" }], 4000), S.seedTakeoff("Seal", [], 4000),
               S.seedTakeoff("Polish", [{ id: "wb-seal-2-coats", name: "Two" }], 4000), S.seedTakeoff("Seal (+Jnts)", [{ id: "wb-seal-jnts-2-coats", name: "J" }], 0)],
        priceRowThrows: (() => { try { S.unitPrice(items, "nothing"); return null; } catch (e) { return String(e.message); } })(),
      }));
    """ % json.dumps(str(MODULE)))
    # 555 SF is $149.85, under the floor; 556 SF is $150.12, rounded up to $151; 12,345 SF is $3,333.15, rounded up to $3,334
    assert got["tooling"] == [[0, 0], [100, 150], [555, 150], [556, 151], [1000, 270], [12345, 3334]]
    assert got["patch"] == {"none": 0, "new": 50, "reno": 150, "fallback": 150, "repriced": 500}
    assert got["from"] == ["library", "fallback"]
    assert got["material"] == {"material": 300 + 50, "tooling": 270, "patch": 50}, "an off row buys nothing and a blank row is skipped"
    assert got["seed"] == [[{"assembly_id": "wb-seal-2-coats", "assembly_name": "Two", "measurement": 4000, "unit": "SF"}], None, None,
                           [{"assembly_id": "wb-seal-jnts-2-coats", "assembly_name": "J", "measurement": "", "unit": "SF"}]]
    assert "not a price row" in got["priceRowThrows"]
