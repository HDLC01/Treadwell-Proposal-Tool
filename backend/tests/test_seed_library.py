"""Phase 12: the script that seeds the Items & Assemblies library from Kyle's estimate workbook.

backend/ops/seed_library_from_workbook.py reads backend/templates/estimate_sheet_5.7.xlsx and plans the library rows
that make the Epoxy tab's materials (and the Gyp tab's products) priceable in Estimating Tool v2. It is a one-time
data tool that writes to a database, so what is proven here is the part that matters most: that it can only ADD.

  * DETERMINISTIC   the plan is the same on every run, byte for byte, and every id is made from a name
  * INSERT-ONLY     every statement is `insert ... on conflict (...) do nothing`. Proven by RUNNING the statements:
                    a row somebody edited is still as they left it after the script has run, twice
  * DRY-RUN BY DEFAULT, STAGING ONLY   with no flag nothing is written, `--apply` needs `--target staging`, and
                    nothing that is not staging is accepted (production is not approved)
  * LOUD            a workbook shape the planner has not seen stops the run with the cell named
  * THE RIGHT ROWS  every item and assembly passes the same validation the library's own API applies, every line of
                    every assembly points at a material the plan holds, and the figures are the workbook's

Each mutation at the bottom breaks a scratch copy of the script and the check it belongs to must go red.
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import subprocess
import sys
from fractions import Fraction

import pytest

TESTS = pathlib.Path(__file__).resolve().parent
BACKEND = TESTS.parent
SCRIPT = BACKEND / "ops" / "seed_library_from_workbook.py"

sys.path.insert(0, str(BACKEND))
import library  # noqa: E402  (the library API's own validators)
from _seed_support import PLAN, SHEETS as _SHEETS, edited, load_script, seed  # noqa: E402


def _load(path: pathlib.Path = SCRIPT, name: str = "seed_library_from_workbook"):
    return load_script(path, name)


@pytest.fixture(scope="module")
def plan():
    return PLAN


# ── deterministic ────────────────────────────────────────────────────────────
def test_the_plan_is_the_same_every_time_and_ids_come_from_names(plan):
    again = seed.make_plan(sheets=_SHEETS)
    assert json.dumps(plan.as_dict(), sort_keys=True) == json.dumps(again.as_dict(), sort_keys=True)
    assert seed.statements(plan) == seed.statements(again)
    for it in plan.as_dict()["items"]:
        assert re.fullmatch(r"wb-(epoxy|gyp)-[a-z0-9-]+", it["id"]), it["id"]
    for a in plan.as_dict()["assemblies"]:
        assert re.fullmatch(r"wb-(epoxy-(sys|primer|cove)|gyp-area)-[a-z0-9-]+", a["id"]), a["id"]
    # an id is its name's slug, so renaming a product in the workbook is a NEW row and never an overwrite
    assert plan.items["wb-epoxy-glaze-4-125-sf-gallon"]["name"] == "Glaze #4, 125 SF/Gallon"


def test_the_counts_are_the_workbooks(plan):
    """The Epoxy tab's fifteen floor systems, its six wall systems, six primers and twelve coves; the products they
    buy; and the Gyp tab's products. A change here is a change to the template and wants a look."""
    asm = list(plan.assemblies)
    assert sum(a.startswith("wb-epoxy-sys-") and not a.startswith("wb-epoxy-sys-walls-") for a in asm) == 15
    assert sum(a.startswith("wb-epoxy-sys-walls-") for a in asm) == 6
    assert sum(a.startswith("wb-epoxy-primer-") for a in asm) == 6
    assert sum(a.startswith("wb-epoxy-cove-") for a in asm) == 12
    items = list(plan.items)
    assert sum(i.startswith("wb-epoxy-") for i in items) == 46
    # the Gyp tabs' 20 products: 3 bags (Levelrock 2500 and 3500, Treadstone FR25), 3 primers (USG, wood, Treadstone TP1),
    # 2 ISO strips, tape, sand, and 10 sound mats (the USG and GrassWorx table's 7 and Gyp (FR)'s 3 Treadstone ones)
    assert sum(i.startswith("wb-gyp-") for i in items) == 20
    assert sum(a.startswith("wb-gyp-area-") for a in asm) == 3
    assert set(plan.labor) == {"epoxy-install", "gyp-prepour", "gyp-prep", "gyp-mat", "gyp-pour", "gyp-unload"}
    assert list(plan.labor_calc) == ["epoxy-install"], "the Gyp crew is priced by the hour and has no calculator line"


# ── the rows are the library's own kind of row ───────────────────────────────
def test_every_item_and_assembly_passes_the_librarys_own_validation(plan):
    data = plan.as_dict()
    for it in data["items"]:
        out = library.validate_item(dict(it))
        for key in ("name", "unit", "buy_qty", "unit_cost", "waste_pct", "roundup"):
            assert out[key] == it[key], (it["id"], key, out[key], it[key])
        if it["coverage"] is not None:
            assert out["coverage"] == it["coverage"], (it["id"], out["coverage"])
        if it.get("price_breaks"):
            assert out["price_breaks"] == it["price_breaks"]
        if it.get("bulk_cost") is not None:
            assert out["bulk_cost"] == it["bulk_cost"]
        assert out["default_work_types"] == it["default_work_types"]
    for a in data["assemblies"]:
        out = library.validate_assembly(dict(a))
        assert [ln["item_id"] for ln in out["lines"]] == [ln["item_id"] for ln in a["lines"]], a["id"]
        assert out["unit"] == a["unit"]


def test_every_line_points_at_a_material_the_plan_holds_and_every_material_is_used(plan):
    used = {ln["item_id"] for a in plan.as_dict()["assemblies"] for ln in a["lines"]}
    assert used <= set(plan.items), "a line points at a material that is not in the plan: %s" % sorted(used - set(plan.items))
    price_rows = set(seed.RESERVED_PRICE_ROWS)
    gyp = {i for i in plan.items if i.startswith("wb-gyp-")}
    unused = set(plan.items) - used - price_rows - gyp
    # a price row nothing prices through is deliberate; a floor product no assembly buys is a parsing mistake
    assert not unused, "materials no assembly buys: %s" % sorted(unused)


def test_the_figures_are_the_workbooks(plan):
    """Spot checks against cells of the template: Armor Top's price and its bulk price, flake's two prices and the
    pound break, the patch."""
    armor = plan.items["wb-epoxy-armor-top-satin-w-grit-775-sf-kit"]
    assert (armor["unit_cost"], armor["bulk_cost"], armor["coverage"]) == (382.448, 324.837, 775.0)
    flake = plan.items["wb-epoxy-macro-flake-40-lb-bag-0-15-lb-per-sf"]
    assert flake["unit_cost"] == 92.0 and flake["price_breaks"] == [{"min_qty": 6.0, "unit_cost": 90.0}]
    assert flake["coverage"] == 266.667, "40 lb at 0.15 lb a SF is 266.6667 SF, kept to three places and rounded UP"
    assert plan.items["wb-epoxy-patch"]["unit_cost"] == 0.1 and plan.items["wb-epoxy-patch"]["roundup"] is False
    kit = plan.items["wb-epoxy-hp-block-filler-primer-5gal-kit-875-sf-kit"]
    assert kit["coverage"] == 875.0, "the 5 gallon kit covers five times 175 SF"
    crew = plan.labor["epoxy-install"]
    assert (crew["rate"], crew["unit"], crew["default_work_types"]) == (33.0, "days", ["epoxy"])
    assert plan.labor_calc["epoxy-install"]["guys"] == 3.0


def test_the_named_modelling_gaps_are_listed_for_kyle(plan):
    gaps = " ".join(plan.gaps)
    for phrase in ("two broadcast lines added together", "three places", "two ROUNDUPs", "Bulk Discount", "Gyp bags are fractional"):
        assert phrase in gaps, phrase


def test_a_coverage_is_rounded_up_never_down():
    """333.3333 SF a bag stored as 333.333 would make 1,000 SF need 3.000003 bags and buy four; stored as 333.334 it
    needs 2.999997 and buys three, which is what the sheet buys (CEILING(1000 * 0.12, 40) is 120 lb, three bags)."""
    cov = seed._round_up_3(Fraction(40) / Fraction("0.12"))
    assert float(cov) == 333.334
    assert float(seed._round_up_3(Fraction(40) / Fraction("0.15"))) == 266.667
    assert float(seed._round_up_3(Fraction(50) / Fraction("0.8"))) == 62.5, "an exact coverage is left exactly alone"
    import math
    assert math.ceil(1000 / float(cov)) == 3 and math.ceil(1000 / 333.333) == 4


# ── insert-only: proven by running the statements ───────────────────────────────
def _sqlite_for(plan):
    """The statements, run on a database that has the same tables. The statements are Postgres; the only things
    sqlite lacks are the schema prefix and the jsonb cast, and neither changes what `on conflict do nothing` does."""
    db = sqlite3.connect(":memory:")
    for table, columns, key, _ in seed.TABLES:
        db.execute("create table %s (%s, primary key (%s))" % (table, ", ".join(columns), key))
    return db


def _run(db, script):
    db.executescript(script.replace("public.", "").replace("::jsonb", ""))


def test_a_row_somebody_edited_is_still_as_they_left_it_after_the_script_runs_twice(plan):
    db = _sqlite_for(plan)
    db.execute("insert into library_items (id, name, unit_cost, coverage) values ('wb-epoxy-patch', 'Patch (edited by Kyle)', 9.99, 7)")
    db.execute("insert into library_labor (id, name, rate) values ('epoxy-install', 'Epoxy crew (edited)', 41)")
    script = seed.sql_script(plan)
    _run(db, script)
    _run(db, script)
    assert db.execute("select name, unit_cost, coverage from library_items where id = 'wb-epoxy-patch'").fetchall() == [
        ("Patch (edited by Kyle)", 9.99, 7)]
    assert db.execute("select name, rate from library_labor where id = 'epoxy-install'").fetchall() == [("Epoxy crew (edited)", 41)]
    # idempotent: the second run added nothing, and everything else of the plan is there once
    counts = plan.counts()
    assert db.execute("select count(*) from library_items").fetchone()[0] == counts["items"]
    assert db.execute("select count(*) from library_assemblies").fetchone()[0] == counts["assemblies"]
    assert db.execute("select count(*) from library_labor").fetchone()[0] == counts["labor"]
    assert db.execute("select count(*) from library_labor_calc").fetchone()[0] == counts["labor_calc"]


def test_the_statements_can_only_add(plan):
    statements = seed.statements(plan)
    assert len(statements) == sum(plan.counts().values())
    for s in statements:
        assert s.startswith("insert into public.") and re.search(r" on conflict \((id|line_id)\) do nothing;$", s), s[:90]
    # nothing that changes or removes anything is in the script, not even in a name (a name is quoted text, so the
    # words are looked for outside quotes)
    unquoted = re.sub(r"'(?:[^']|'')*'", "''", seed.sql_script(plan))
    for word in ("update", "delete", "drop", "truncate", "alter", "do update"):
        assert not re.search(r"\b%s\b" % word, unquoted, re.I), word


def test_a_name_with_a_quote_in_it_survives_the_statement(plan):
    p = seed.Plan()
    p.add_item(seed._item("wb-epoxy-test", "Kyle's 4\" cove, 'quoted'", "Gallon", 1, 1.5, 2.0, "Epoxy", "epoxy", "it's a note"))
    db = _sqlite_for(p)
    _run(db, seed.sql_script(p))
    assert db.execute("select name, notes from library_items").fetchall() == [("Kyle's 4\" cove, 'quoted'", "it's a note")]


# ── dry run by default, staging only ─────────────────────────────────────────
def test_with_no_flag_nothing_is_written(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("a dry run reached for ssh")
    monkeypatch.setattr(seed.subprocess, "run", boom)
    monkeypatch.setattr(seed, "load", lambda path=None: _SHEETS)
    assert seed.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith("PLAN (a dry run writes nothing)") and "library_items" in out and "NAMED MODELLING GAPS" in out
    assert seed.main(["--sql"]) == 0 and capsys.readouterr().out.startswith("begin;")
    assert seed.main(["--json"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {"items", "assemblies", "labor", "labor_calc", "gaps"}


@pytest.mark.parametrize("argv", [["--apply"], ["--apply", "--target", "production"], ["--apply", "--target", "prod"],
                                  ["--apply", "--target", ""], ["--target", "staging"]])
def test_apply_is_refused_without_the_staging_target_and_never_reaches_a_network(monkeypatch, capsys, argv):
    def boom(*a, **k):
        raise AssertionError("a refused run reached for ssh")
    monkeypatch.setattr(seed.subprocess, "run", boom)
    assert seed.main(argv) == 2
    assert "refused" in capsys.readouterr().err


def test_apply_to_staging_runs_the_script_inside_the_staging_database_container_and_nowhere_else(monkeypatch, plan):
    calls = []

    def fake(args, input=None, **kw):
        calls.append((args, input))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(seed.subprocess, "run", fake)
    monkeypatch.setattr(seed, "load", lambda path=None: _SHEETS)
    assert seed.main(["--apply", "--target", "staging"]) == 0
    assert len(calls) == 1
    args, script = calls[0]
    assert args[:2] == ["ssh", seed.STAGING_SSH_HOST] and "treadwell-staging-db" in args and "ON_ERROR_STOP=1" in args
    assert script == seed.sql_script(plan)
    assert "treadwell-db" not in " ".join(args).replace("treadwell-staging-db", ""), "only the staging container is named"


def test_a_failed_psql_stops_the_run(monkeypatch):
    monkeypatch.setattr(seed.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 3, stdout="", stderr="no route"))
    monkeypatch.setattr(seed, "load", lambda path=None: _SHEETS)
    assert seed.main(["--apply", "--target", "staging"]) == 1


# ── loud ─────────────────────────────────────────────────────────────────────
def test_a_quantity_formula_the_planner_has_not_seen_stops_the_run_naming_the_cell():
    with edited("Epoxy", "f", "E173", "=ROUNDUP(I171/C173,1)"):
        with pytest.raises(seed.PlanError, match=r"E173.*not one this planner reads"):
            seed.plan_epoxy(_SHEETS, seed.Plan())


def test_a_price_cell_with_no_saved_value_stops_the_run():
    with edited("Epoxy", "v", "T153", None):
        with pytest.raises(seed.PlanError, match=r"T153.*not a saved number"):
            seed.plan_epoxy(_SHEETS, seed.Plan())


def test_a_cost_formula_that_is_not_quantity_times_a_price_stops_the_run():
    with edited("Epoxy", "f", "F173", "=E173*SL+5"):
        with pytest.raises(seed.PlanError, match=r"F173"):
            seed.plan_epoxy(_SHEETS, seed.Plan())


def test_two_different_materials_that_would_share_an_id_stop_the_run():
    p = seed.Plan()
    p.add_item(seed._item("wb-epoxy-x", "X", "Gallon", 1, 1.0, 1.0, "Epoxy", "epoxy", ""))
    with pytest.raises(seed.PlanError, match="both be"):
        p.add_item(seed._item("wb-epoxy-x", "Y", "Gallon", 1, 2.0, 1.0, "Epoxy", "epoxy", ""))


def test_a_system_written_twice_with_two_different_bodies_stops_the_run():
    with edited("Epoxy", "v", "AC194", 300):      # System 2's flake single broadcast: a different OPF coverage
        with pytest.raises(seed.PlanError, match="two copies differ"):
            seed.plan_epoxy(_SHEETS, seed.Plan())


# ── red without the code ─────────────────────────────────────────────────────
def _mutated(tmp_path, old, new):
    src = SCRIPT.read_bytes().decode("utf-8")
    assert src.count(old) == 1, "the mutation anchor %r is in the script %d times, not once" % (old, src.count(old))
    path = tmp_path / "seed_mutated.py"
    path.write_bytes(src.replace(old, new).encode("utf-8"))
    return _load(path, "seed_mutated")


def test_the_checks_notice_a_coverage_rounded_down(tmp_path):
    mod = _mutated(tmp_path, ".to_integral_value(ROUND_CEILING)", ".to_integral_value(rounding='ROUND_FLOOR')")
    flake = mod.make_plan(sheets=_SHEETS).items["wb-epoxy-macro-flake-40-lb-bag-0-12-lb-per-sf"]
    assert flake["coverage"] == 333.333 != 333.334


def test_the_checks_notice_an_insert_that_overwrites(tmp_path):
    mod = _mutated(tmp_path, '"insert into public.%s (%s) values (%s) on conflict (%s) do nothing;" % (',
                   '"insert or replace into public.%s (%s) values (%s);%.0s" % (')
    plan = mod.make_plan(sheets=_SHEETS)
    db = sqlite3.connect(":memory:")
    for table, columns, key, _ in mod.TABLES:
        db.execute("create table %s (%s, primary key (%s))" % (table, ", ".join(columns), key))
    db.execute("insert into library_items (id, name) values ('wb-epoxy-patch', 'edited')")
    db.executescript(mod.sql_script(plan).replace("public.", "").replace("::jsonb", ""))
    assert db.execute("select name from library_items where id = 'wb-epoxy-patch'").fetchone()[0] != "edited", (
        "the mutated script overwrote the row, and the insert-only test above is what would have said so")


def test_the_checks_notice_a_target_that_is_not_staging(tmp_path, monkeypatch):
    mod = _mutated(tmp_path, 'if args.target != "staging":', 'if args.target not in ("staging", "production"):')
    monkeypatch.setattr(mod.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 0, stdout="", stderr=""))
    monkeypatch.setattr(mod, "load", lambda path=None: _SHEETS)
    assert mod.main(["--apply", "--target", "production"]) == 0, "the mutation lets production through, which the refusal test forbids"
