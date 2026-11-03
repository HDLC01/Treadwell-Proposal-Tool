"""Every material priced per single unit (Hanz, 2026-11-04): the data conversion, proved.

"So what we want to do now is remove the order quantity. Then round up would be to just the nearest single
unit." The Items tab lost its Order Quantity column and the server stores buy_qty = 1 on every write, so a
row that held a PACK price (a 5 gallon pail at $139.50) has to become the price of ONE unit ($27.90 a
gallon) or every bid that reads it prices five times too high.

WHAT THIS FILE PROVES:

  * library.per_unit_conversion is the arithmetic, and backend/ops/library_per_unit_cost.sql is the SAME
    arithmetic: the SQL is read and its expressions pinned to what the function does.
  * On the four pack-priced rows staging holds today (copied below from a live read of the staging
    library on 2026-11-04, and checked against that read when it is on this machine), plus two rows that
    are already single units:
      - Roundup OFF, the price of a line is IDENTICAL before and after, at every area, through
        library-core's own priceLine (the function every bid prices with).
      - Roundup ON may differ, and only by rounding: before, the line bought whole PACKS
        (CEIL(needed / pack) packs); after, whole UNITS (CEIL(needed) units). That is the change Hanz
        asked for, and the test states it as an equation rather than as "close".
      - epoxy-takeoff.js and gyp-takeoff.js unitPrice (the cove and Gyp formulas' price of one unit)
        answer the same before and after.
    THE ONE INEXACT ROW: the USG primer drum, $891 for 53 gallons. 891 / 53 = 16.81132... and unit_cost is
    numeric(12,4), so it becomes $16.8113: two thousandths of a cent a gallon under. Its checks allow
    exactly that (5e-5 a unit) and every other row is held to 1e-9.
  * The conversion is idempotent: run twice, the second run changes nothing.
  * The seed (backend/ops/seed_library_from_workbook.py) plans every row at buy_qty 1 with its unit price,
    so a re-seed never brings a pack back, and the cove aggregates are pounds.

Each test here was run against the code before the change and failed (no per_unit_conversion, no SQL file,
a seed still planning 50 lb bags and 53 gallon drums).
"""
from __future__ import annotations

import json
import math
import pathlib
import re
import subprocess

import pytest

import library
from _node import require_node
from _seed_support import PLAN

ROOT = pathlib.Path(__file__).resolve().parents[2]
SQL = ROOT / "backend" / "ops" / "library_per_unit_cost.sql"
CORE = ROOT / "frontend" / "js" / "library-core.js"
EPOXY = ROOT / "frontend" / "js" / "epoxy-takeoff.js"
GYP = ROOT / "frontend" / "js" / "gyp-takeoff.js"
# The live read this file's rows were copied from (a session scratchpad; absent on CI, where the
# embedded copies below stand on their own).
LIVE_READ = pathlib.Path(
    r"C:/Users/Hanz/AppData/Local/Temp/claude/16964296ed04ecb0/1446a2c2-96d6-4f9c-90c6-76f3a965f66c"
    r"/scratchpad/libdata.clean.json")

_PRICED = ("id", "name", "unit", "buy_qty", "unit_cost", "coverage", "waste_pct", "roundup",
           "price_breaks", "bulk_cost", "coverage_basis")

# THE FOUR PACK-PRICED ROWS ON STAGING, 2026-11-04, and two single-unit rows beside them.
PACK_ROWS = [
    {"id": "wb-epoxy-cove-q28", "name": "Q28 / 40-S quartz for cove, 50 lb bag", "unit": "Bag", "buy_qty": 50,
     "unit_cost": 23.5, "coverage": 1, "waste_pct": 0, "roundup": False, "price_breaks": None,
     "bulk_cost": None, "coverage_basis": None},
    {"id": "wb-epoxy-cove-silica", "name": "Silica for cove, 50 lb bag", "unit": "Bag", "buy_qty": 50,
     "unit_cost": 22, "coverage": 1, "waste_pct": 0, "roundup": False, "price_breaks": None,
     "bulk_cost": None, "coverage_basis": None},
    {"id": "wb-gyp-treadstone-primer-tp1-gallon", "name": "Treadstone primer TP1, 5 gallon", "unit": "Gallon",
     "buy_qty": 5, "unit_cost": 139.5, "coverage": None, "waste_pct": 0, "roundup": True, "price_breaks": None,
     "bulk_cost": None, "coverage_basis": None},
    {"id": "wb-gyp-usg-primer-53-gallon-drum", "name": "USG primer, 53 gallon drum", "unit": "Gallon",
     "buy_qty": 53, "unit_cost": 891, "coverage": None, "waste_pct": 0, "roundup": True, "price_breaks": None,
     "bulk_cost": None, "coverage_basis": None},
]
UNIT_ROWS = [
    {"id": "wb-epoxy-cove-rez", "name": "Cove Rez, per gallon", "unit": "Gallon", "buy_qty": 1,
     "unit_cost": 88.8308, "coverage": 1, "waste_pct": 0, "roundup": False, "price_breaks": None,
     "bulk_cost": None, "coverage_basis": None},
    {"id": "wb-epoxy-cove-zinc-cap", "name": "Zinc cove cap, per LF", "unit": "LF", "buy_qty": 1,
     "unit_cost": 0.75, "coverage": 1, "waste_pct": 0, "roundup": False, "price_breaks": None,
     "bulk_cost": None, "coverage_basis": None},
]
EXPECTED = {
    "wb-epoxy-cove-q28": {"unit_cost": 0.47, "buy_qty": 1.0, "unit": "lb",
                          "name": "Q28 / 40-S quartz for cove, per lb"},
    "wb-epoxy-cove-silica": {"unit_cost": 0.44, "buy_qty": 1.0, "unit": "lb",
                             "name": "Silica for cove, per lb"},
    "wb-gyp-treadstone-primer-tp1-gallon": {"unit_cost": 27.9, "buy_qty": 1.0},
    "wb-gyp-usg-primer-53-gallon-drum": {"unit_cost": 16.8113, "buy_qty": 1.0},
}
# A pack with a price break and a bulk cost, which no staging row has today but the SQL must still get right:
# a 40 lb bag at $92, $90 a bag from 240 lb, $85 a bag in bulk.
LADDER = {"id": "flake", "name": "Flake, 40 lb bag", "unit": "lb", "buy_qty": 40, "unit_cost": 92,
          "coverage": 6.6667, "waste_pct": 3, "roundup": False, "bulk_cost": 85,
          "price_breaks": [{"min_qty": 240, "unit_cost": 90}], "coverage_basis": None}


def _apply(row, patch):
    out = dict(row)
    out.update(patch)
    return out


def node(code: str):
    proc = subprocess.run([require_node(), "-e", code], capture_output=True, text=True, encoding="utf-8",
                          timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ── the embedded rows ARE the live ones ───────────────────────────────────────
@pytest.mark.skipif(not LIVE_READ.exists(), reason="the 2026-11-04 staging read is not on this machine")
def test_the_embedded_rows_are_the_staging_rows_they_say_they_are():
    live = {r["id"]: r for r in json.loads(LIVE_READ.read_text(encoding="utf-8"))["items"]["items"]}
    for row in PACK_ROWS + UNIT_ROWS:
        assert {k: live[row["id"]].get(k) for k in _PRICED} == row, row["id"]
    # ...and they are ALL of the pack-priced rows there are.
    assert sorted(i for i, r in live.items() if (r.get("buy_qty") or 1) != 1) == sorted(r["id"] for r in PACK_ROWS)


# ── the function ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("row", PACK_ROWS, ids=lambda r: r["id"])
def test_a_pack_row_becomes_the_price_of_one_unit(row):
    assert library.per_unit_conversion(row) == EXPECTED[row["id"]]


@pytest.mark.parametrize("row", PACK_ROWS + UNIT_ROWS + [LADDER], ids=lambda r: r["id"])
def test_a_second_run_changes_nothing(row):
    once = _apply(row, library.per_unit_conversion(row))
    assert library.per_unit_conversion(once) == {}


@pytest.mark.parametrize("row", UNIT_ROWS, ids=lambda r: r["id"])
def test_a_single_unit_row_is_left_alone(row):
    assert library.per_unit_conversion(row) == {}


def test_a_deleted_row_is_left_alone():
    assert library.per_unit_conversion(dict(PACK_ROWS[2], deleted_at="2026-10-01T00:00:00Z")) == {}


def test_a_break_and_a_bulk_cost_are_pack_prices_too_and_the_break_quantity_stays_in_units():
    """A break's quantity is already counted in UNITS bought (library-core breakAt judges packs * buy_qty),
    so it is not touched. Its cost, and the bulk cost, were pack prices (priceLine swaps them in for
    unit_cost), so they divide like unit_cost does."""
    assert library.per_unit_conversion(LADDER) == {
        "unit_cost": 2.3, "bulk_cost": 2.125, "buy_qty": 1.0,
        "price_breaks": [{"min_qty": 240, "unit_cost": 2.25}]}


def test_rounding_is_postgres_numeric_rounding_half_away_from_zero():
    """round(numeric, 4) in Postgres rounds a half away from zero on the decimal value; a float round()
    would not always agree. 0.00005 a unit is exactly the case."""
    assert library.per_unit_conversion({"id": "x", "buy_qty": 2, "unit_cost": "0.0001"})["unit_cost"] == 0.0001
    assert library.per_unit_conversion({"id": "x", "buy_qty": 4, "unit_cost": "0.0002"})["unit_cost"] == 0.0001
    assert library.per_unit_conversion({"id": "x", "buy_qty": 3, "unit_cost": 1})["unit_cost"] == 0.3333


# ── the SQL is the function ───────────────────────────────────────────────────
def _sql_code():
    return "\n".join(line.split("--", 1)[0] for line in SQL.read_text(encoding="utf-8").splitlines())


def test_the_sql_does_the_functions_arithmetic():
    code = re.sub(r"\s+", " ", _sql_code())
    for expr in ("unit_cost = case when li.unit_cost is null then null else round(li.unit_cost / li.buy_qty, 4) end",
                 "bulk_cost = case when li.bulk_cost is null then null else round(li.bulk_cost / li.buy_qty, 4) end",
                 "to_jsonb(round((e->>'unit_cost')::numeric / li.buy_qty, 4))",
                 "jsonb_set(e, '{unit_cost}',",
                 "buy_qty = 1 where li.deleted_at is null and coalesce(li.buy_qty, 1) <> 1 and li.buy_qty > 0",
                 "order by ord"):
        assert expr in code, expr
    # The break's quantity is never rewritten, and the same numeric test picks which costs are divided.
    assert "min_qty" not in code
    assert "'^\\s*-?[0-9]*\\.?[0-9]+\\s*$'" in code
    assert library._NUMERIC_TEXT.pattern == r"^\s*-?[0-9]*\.?[0-9]+\s*$"


def test_the_sql_moves_the_same_two_rows_to_pounds():
    code = re.sub(r"\s+", " ", _sql_code())
    ids = re.search(r"set unit = 'lb' where id in \(([^)]*)\)", code)
    assert ids, "the per-pound update is missing"
    assert tuple(re.findall(r"'([^']+)'", ids.group(1))) == library.PER_POUND_ITEM_IDS
    assert "and unit is distinct from 'lb'" in code


def test_the_sql_renames_only_the_seeded_cove_names_the_way_the_function_does():
    """A "50 lb bag" priced at $0.44 a pound invites a "correction" to $22. Only the seeded name moves."""
    code = re.sub(r"\s+", " ", _sql_code())
    for row_id, (old, new) in library.PER_POUND_RENAMES.items():
        assert ("update public.library_items set name = '%s' where id = '%s' and deleted_at is null "
                "and name = '%s';" % (new, row_id, old)) in code, row_id
        assert library.per_unit_conversion({"id": row_id, "name": "Somebody's own name", "unit": "lb"}) == {}


def test_the_sql_adds_the_price_break_columns_it_reads_before_it_reads_them():
    """A database that missed library_price_breaks.sql must not fail the conversion on a missing column."""
    code = re.sub(r"\s+", " ", _sql_code())
    for col, typ in (("price_breaks", "jsonb"), ("bulk_cost", "numeric(12,4)")):
        ddl = "alter table public.library_items add column if not exists %s %s;" % (col, typ)
        assert ddl in code, ddl
        assert code.index("begin;") < code.index(ddl) < code.index("update public.library_items li"), col


def test_the_sql_is_one_transaction_and_leaves_the_history_alone():
    code = _sql_code()
    assert re.search(r"^begin;$", code, re.M) and re.search(r"^commit;$", code, re.M)
    assert code.index("begin;") < code.index("update public.library_items") < code.index("commit;")
    assert code.rstrip().endswith("notify pgrst, 'reload schema';")
    for stamp in ("updated_at", "cost_updated_at", "updated_by"):
        assert stamp not in code, "%s is a record of an edit, and nobody edited the row" % stamp
    assert "BOTH" in SQL.read_text(encoding="utf-8"), "the header must say it runs on both databases"


# ── the proof: what a bid pays, before and after ──────────────────────────────
# 1521 SF puts LADDER's need at 235 lb (1521 / 6.6667 + 3%): six whole 40 lb bags = 240 lb reach its break
# from 240 lb, 235 whole pounds do not. The one place whole-unit rounding costs MORE than whole-pack did.
LADDER_BREAK_LOST_AREA = 1521
AREAS = [1, 7.5, 137, 1000, LADDER_BREAK_LOST_AREA, 2875, 12345]
# The primers have no coverage on staging (the Gyp formula decides how many gallons). priceLine needs one to
# price a line at all, so the proof lends them the formula's own 1,200 SF a gallon (gyp-takeoff.js PRIMER_SF).
PRIMER_SF = 1200


def _proof():
    pairs = []
    for row in PACK_ROWS + UNIT_ROWS + [LADDER]:
        before = dict(row)
        if before.get("coverage") is None:
            before["coverage"] = PRIMER_SF
        after = _apply(before, library.per_unit_conversion(row))
        pairs.append({"id": row["id"], "before": before, "after": after})
    return node("""
      const L = require(%s), E = require(%s), G = require(%s);
      const pairs = %s, areas = %s;
      const line = (it, area, roundup, opts) => {
        const row = Object.assign({}, it, { roundup: roundup });
        const r = L.priceLine({ item_id: it.id }, [row], area, opts);
        return { ok: r.ok, cost: r.cost, needed: r.needed, units: r.units, unit_price: r.unit_price, pack_cost: r.pack_cost };
      };
      const out = pairs.map((p) => ({
        id: p.id, pack: p.before.buy_qty,
        off: areas.map((a) => [line(p.before, a, false), line(p.after, a, false)]),
        offBulk: areas.map((a) => [line(p.before, a, false, { bulk: true }), line(p.after, a, false, { bulk: true })]),
        on: areas.map((a) => [line(p.before, a, true), line(p.after, a, true)]),
      }));
      const epoxy = ["q28", "silica"].map((k) => {
        const id = { q28: "wb-epoxy-cove-q28", silica: "wb-epoxy-cove-silica" }[k];
        const p = pairs.find((x) => x.id === id);
        return { key: k, before: E.unitPrice([p.before], k), after: E.unitPrice([p.after], k) };
      });
      const gyp = Object.keys(G.PRESETS).map((tab) => {
        const spec = G.PRESETS[tab].primer;
        const p = pairs.find((x) => x.id === spec.id);
        return { tab: tab, id: spec.id, before: G.unitPrice([p.before], spec), after: G.unitPrice([p.after], spec) };
      });
      console.log(JSON.stringify({ lines: out, epoxy: epoxy, gyp: gyp }));
    """ % (json.dumps(str(CORE)), json.dumps(str(EPOXY)), json.dumps(str(GYP)), json.dumps(pairs), json.dumps(AREAS)))


@pytest.fixture(scope="module")
def proof():
    return _proof()


def _tol(row_id, needed):
    # The USG drum's four-place unit price (see the module docstring); exact everywhere else.
    return needed * 5e-5 + 1e-9 if row_id == "wb-gyp-usg-primer-53-gallon-drum" else 1e-9


def test_roundup_off_prices_identically_before_and_after(proof):
    for r in proof["lines"]:
        for (b, a), (bb, ab) in zip(r["off"], r["offBulk"]):
            assert b["ok"] and a["ok"], r["id"]
            assert a["cost"] == pytest.approx(b["cost"], abs=_tol(r["id"], b["needed"])), (r["id"], b, a)
            assert ab["cost"] == pytest.approx(bb["cost"], abs=_tol(r["id"], bb["needed"])), (r["id"], "bulk", bb, ab)


def test_roundup_on_now_buys_whole_units_instead_of_whole_packs(proof):
    """The one place a price moves, and by exactly this: before, CEIL(needed / pack) packs at the pack price;
    after, CEIL(needed) units at the unit price. Without a price break, never more than before (a whole unit
    is never more than a whole pack), and the same whenever the need lands on a whole pack.

    WITH A PRICE BREAK IT CAN COST MORE: whole-pack rounding could overshoot into the break where whole-unit
    rounding stops short of it. LADDER at 1521 SF needs 235 lb; before, six 40 lb bags = 240 lb at the $90
    break = $540.00; after, 235 lb at $2.30 = $540.50. The test pins that case rather than avoid it."""
    lost = None
    for r in proof["lines"]:
        pack = r["pack"]
        has_breaks = r["id"] == LADDER["id"]
        for area, (b, a) in zip(AREAS, r["on"]):
            need = b["needed"]
            assert b["cost"] == pytest.approx(math.ceil(round(need / pack, 9)) * b["pack_cost"]), (r["id"], b)
            assert a["cost"] == pytest.approx(math.ceil(round(need, 9)) * a["unit_price"]), (r["id"], a)
            assert a["units"] == math.ceil(round(need, 9)) and a["units"] == int(a["units"]), "whole units only"
            if not has_breaks:
                assert a["cost"] <= b["cost"] + _tol(r["id"], need), (r["id"], b, a)
            elif area == LADDER_BREAK_LOST_AREA:
                lost = (b, a)
            if pack == 1:
                assert a["cost"] == b["cost"], r["id"]
    b, a = lost
    assert 234 < b["needed"] <= 235 and b["units"] == 240 and a["units"] == 235
    assert (round(b["cost"], 2), round(a["cost"], 2)) == (540.00, 540.50), "the break-lost case moved"


def test_the_cove_and_gyp_formulas_read_the_same_price_of_one_unit(proof):
    for e in proof["epoxy"]:
        assert e["before"]["from"] == e["after"]["from"] == "library"
        assert e["after"]["cost"] == pytest.approx(e["before"]["cost"], abs=1e-12), e
    assert {e["key"]: e["after"]["cost"] for e in proof["epoxy"]} == {"q28": 0.47, "silica": 0.44}
    for g in proof["gyp"]:
        assert g["before"]["from"] == g["after"]["from"] == "library"
        tol = 5e-5 if g["id"] == "wb-gyp-usg-primer-53-gallon-drum" else 1e-12
        assert g["after"]["cost"] == pytest.approx(g["before"]["cost"], abs=tol), g


# ── the seed never brings a pack back ─────────────────────────────────────────
def test_the_seed_plans_every_material_at_one_unit():
    items = PLAN.as_dict()["items"]
    assert items and all(i["buy_qty"] == 1 for i in items), [i["id"] for i in items if i["buy_qty"] != 1]
    for i in items:
        assert library.per_unit_conversion(i) == {}, i["id"]


def test_the_seed_plans_the_four_converted_rows_at_their_converted_prices():
    for row_id, want in EXPECTED.items():
        got = PLAN.items[row_id]
        assert {k: got[k] for k in want} == want, row_id
