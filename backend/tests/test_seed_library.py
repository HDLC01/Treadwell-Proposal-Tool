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

The Polish section (three per-SF materials and an assembly for each polish system), the discount-group `vendor` of the Epoxy
rows and the three flagged exceptions to insert-only (vendor fill-in, the Gyp sand price, the beta sample's retirement) are
held the same way: by RUNNING the statements against rows somebody edited.

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
        assert re.fullmatch(r"wb-(epoxy|gyp|seal|polish)-[a-z0-9-]+", it["id"]), it["id"]
    for a in plan.as_dict()["assemblies"]:
        assert re.fullmatch(r"wb-(epoxy-(sys|primer|cove)|gyp-area|seal|polish-sys)-[a-z0-9-]+", a["id"]), a["id"]
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
    # the Seal tabs' 4 materials (the two patch prices, the sealer, the joint filler kit) and 4 assemblies (one coat or two, with
    # and without joint filler); their three crew lines are priced by the day and have a calculator line each
    assert sum(i.startswith("wb-seal-") for i in items) == 4
    assert sum(a.startswith("wb-seal-") for a in asm) == 4
    # the Polish tab's 3 per-SF materials (densifier, sealer, grout compound) and one assembly for each of its 3 systems
    assert sum(i.startswith("wb-polish-") for i in items) == 3
    assert sum(a.startswith("wb-polish-sys-") for a in asm) == 3
    assert set(plan.labor) == {"epoxy-install", "gyp-prepour", "gyp-prep", "gyp-mat", "gyp-pour", "gyp-unload",
                               "seal-install", "seal-mockup", "seal-jointfill"}
    assert list(plan.labor_calc) == ["epoxy-install", "seal-install", "seal-mockup", "seal-jointfill"], (
        "the Gyp crew is priced by the hour and has no calculator line")


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
    price_rows = set(seed.RESERVED_PRICE_ROWS) | {"wb-seal-patch-new", "wb-seal-patch-reno"}
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
    db.execute("create table library_vendors (id primary key, name, notes, deleted_at)")     # the dropdown rows the Epoxy vendors need
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



# ── Polish: the three materials the sheet charges per SF, and one assembly for each polish system ──────────────
POLISH_SYSTEMS = {"wb-polish-sys-salt-and-pepper": "Polish \u2014 Salt & Pepper", "wb-polish-sys-cream": "Polish \u2014 Cream",
                  "wb-polish-sys-full-aggregate": "Polish \u2014 Full aggregate"}


def _lines(plan, asm_id):
    return [ln["item_id"] for ln in plan.assemblies[asm_id]["lines"]]


def test_the_polish_plan_is_three_materials_and_three_systems_and_nothing_else():
    p = seed.make_plan(sheets=_SHEETS, only="polish")
    assert p.counts() == {"items": 3, "assemblies": 3, "labor": 0, "labor_calc": 0}
    assert {k: a["name"] for k, a in p.assemblies.items()} == POLISH_SYSTEMS
    for a in p.assemblies.values():
        assert (a["unit"], a["category"], a["default_work_types"]) == ("SF", "Polished Concrete", ["polish"])
    for it in p.items.values():
        assert (it["unit"], it["buy_qty"], it["coverage"], it["waste_pct"], it["roundup"], it["default_work_types"]) == (
            "SF", 1.0, 1.0, 0, False, ["polish"]), "a per-SF price is the area times the price, never a whole pack"
        assert it["divisions"] == ["Polished Concrete"]
    # the same rows are in the whole plan, so `--only polish` and a full seed agree
    for k in list(p.items) + list(p.assemblies):
        assert (PLAN.items.get(k) or PLAN.assemblies.get(k)) == (p.items.get(k) or p.assemblies.get(k)), k


def test_the_polish_prices_are_read_from_the_sheets_cells_and_never_typed_into_the_script(plan):
    sh = _SHEETS["Polish"]
    assert plan.items["wb-polish-densifier"]["unit_cost"] == sh.value("C20") == 0.07
    assert plan.items["wb-polish-sealer"]["unit_cost"] == sh.value("C21") == 0.1
    assert plan.items["wb-polish-grout-compound"]["unit_cost"] == sh.value("C22") == 0.11
    # change a cell and the plan follows it: the price is not a constant in the script
    with edited("Polish", "v", "C21", 0.125):
        assert seed.make_plan(sheets=_SHEETS, only="polish").items["wb-polish-sealer"]["unit_cost"] == 0.125


def test_the_polish_sealer_is_its_own_row_and_not_the_seal_tabs_sealer(plan):
    assert "wb-seal-sealer" in plan.items and "wb-polish-sealer" in plan.items
    assert plan.items["wb-polish-sealer"]["id"] != plan.items["wb-seal-sealer"]["id"]
    assert plan.items["wb-polish-sealer"]["default_work_types"] == ["polish"]
    assert "wb-seal-sealer" not in {i for a in POLISH_SYSTEMS for i in _lines(plan, a)}, (
        "a Polish assembly that bought the Seal tab's sealer would follow the wrong price when Kyle edits one")


def test_the_three_polish_systems_carry_exactly_the_materials_the_sheet_charges_for_them(plan):
    """The sheet's material lines never read the polish system (B20, B21 are the area, B22 is the area only when the
    Grout box says Yes), so Salt & Pepper and Cream charge the same two lines and only Full aggregate adds the grout.
    Dye, joint filler and the patch are priced by the job, so none of the three lists them."""
    sp, cream, full = (_lines(plan, a) for a in ("wb-polish-sys-salt-and-pepper", "wb-polish-sys-cream", "wb-polish-sys-full-aggregate"))
    assert sp == cream == ["wb-polish-densifier", "wb-polish-sealer"]
    assert full == ["wb-polish-densifier", "wb-polish-sealer", "wb-polish-grout-compound"]
    for a in POLISH_SYSTEMS:
        for item_id in _lines(plan, a):
            assert not re.search(r"dye|joint|patch", item_id), (a, item_id)
    assert "do not depend on the polish system" in " ".join(plan.gaps)


def test_a_polish_job_prices_to_the_cent_through_the_assembly_the_way_the_sheet_does(plan):
    """The sheet: D20 = B20*C20 (area x densifier), D21 = B21*C21, D22 = B22*C22 with B22 the area when grouted. Each
    assembly's lines, priced as a library line is (area / coverage x cost, per-SF so nothing is rounded to a pack), must
    be the same dollars and cents at a spread of areas, for the two-material systems and for the grouted one."""
    from decimal import Decimal
    sh = _SHEETS["Polish"]
    c20, c21, c22 = (Decimal(repr(sh.value(c))) for c in ("C20", "C21", "C22"))

    def priced(asm_id, area):
        total = Decimal(0)
        for item_id in _lines(plan, asm_id):
            it = plan.items[item_id]
            assert it["roundup"] is False and it["buy_qty"] == 1.0
            total += Decimal(area) / Decimal(repr(it["coverage"])) * Decimal(repr(it["unit_cost"]))
        return total

    for area in (1, 640, 999, 2500, 7325, 12345, 40000):
        assert priced("wb-polish-sys-salt-and-pepper", area) == Decimal(area) * (c20 + c21)
        assert priced("wb-polish-sys-cream", area) == Decimal(area) * (c20 + c21)
        assert priced("wb-polish-sys-full-aggregate", area) == Decimal(area) * (c20 + c21 + c22)
    # the grouted system is dearer by exactly the grout, so a plan that dropped the grout line could not pass
    assert priced("wb-polish-sys-full-aggregate", 10000) - priced("wb-polish-sys-cream", 10000) == Decimal(10000) * c22 == Decimal("1100.00")


def test_a_polish_rule_the_planner_has_not_seen_stops_the_run_naming_the_cell():
    with edited("Polish", "f", "B22", "=E18"):
        with pytest.raises(seed.PlanError, match=r"B22.*quantity rule of the grout compound"):
            seed.plan_polish(_SHEETS, seed.Plan())
    with edited("Polish", "f", "B20", '=IF(F36="S&P",E18,0)'):         # a densifier that now depends on the system
        with pytest.raises(seed.PlanError, match=r"B20.*densifier"):
            seed.plan_polish(_SHEETS, seed.Plan())
    with edited("Polish", "v", "P15", "Salt and Pepper"):
        with pytest.raises(seed.PlanError, match=r"P15.*S&P"):
            seed.plan_polish(_SHEETS, seed.Plan())
    with edited("Polish", "v", "C20", None):
        with pytest.raises(seed.PlanError, match=r"C20"):
            seed.plan_polish(_SHEETS, seed.Plan())


def test_the_polish_gaps_name_the_cells_the_library_cannot_say(plan):
    gaps = " ".join(plan.gaps)
    for cell in ("I36", "I35", "B32", "C51", "C52", "B53", "B54", "C17", "C25", "B29", "H17:K22", "I28:I30"):
        assert cell in gaps, cell


# ── the discount group of an Epoxy row: its vendor ───────────────────────────────────────────────────────────────
SW, PC = "Sherwin-Williams", "Poly-Crete"


def test_the_vendor_of_every_epoxy_row_is_its_discount_group(plan):
    """Kyle discounts by price column: a T-column liquid reads T141 (the Epoxy discount) except SL, MD and WR, which read T142
    (Poly-Crete); a W-column material is never discounted."""
    vendor = {i["id"]: i.get("vendor") for i in plan.as_dict()["items"] if i["id"].startswith("wb-epoxy-")}
    assert vendor["wb-epoxy-cove-rez"] == SW                      # T152
    assert vendor["wb-epoxy-cove-wr"] == PC                       # T167
    for none in ("wb-epoxy-cove-silica", "wb-epoxy-cove-q28", "wb-epoxy-cove-zinc-cap", "wb-epoxy-patch"):
        assert vendor[none] is None, none                         # W145, W148, W150, C18
    assert {i for i, v in vendor.items() if v == PC} == {
        "wb-epoxy-cove-wr", "wb-epoxy-poly-crete-md-32-sf-kit", "wb-epoxy-poly-crete-sl-55-sf-kit"}
    # the column of the row's own price cell decides it: T is a discounted liquid, anything else is not
    for i in plan.as_dict()["items"]:
        if i["id"].startswith("wb-epoxy-"):
            col = re.search(r"Epoxy!([A-Z]+)\d+", i["notes"]).group(1)
            assert (i.get("vendor") is not None) == (col == "T"), (i["id"], col, i.get("vendor"))
    # nothing outside the Epoxy tab is tagged
    assert not [i["id"] for i in plan.as_dict()["items"] if i.get("vendor") and not i["id"].startswith("wb-epoxy-")]


def test_the_vendor_is_derived_from_the_price_cell_and_not_from_a_list_of_products():
    """Point the Glaze 4 price at the Poly-Crete discount and the plan moves it: the seed holds no list of who is who."""
    f = _SHEETS["Epoxy"].f["T153"]
    with edited("Epoxy", "f", "T153", f.value.replace("$T$141", "$T$142")):
        p = seed.make_plan(sheets=_SHEETS, only="epoxy")
    assert p.items["wb-epoxy-glaze-4-125-sf-gallon"]["vendor"] == PC
    assert PLAN.items["wb-epoxy-glaze-4-125-sf-gallon"]["vendor"] == SW


def test_a_price_that_reads_two_discounts_or_a_discount_the_planner_has_not_seen_stops_the_run():
    with edited("Epoxy", "f", "T153", "=(U153*$T$141)+(U153*$T$142)"):
        with pytest.raises(seed.PlanError, match=r"T153.*two discounts"):
            seed.plan_epoxy(_SHEETS, seed.Plan())
    with edited("Epoxy", "v", "S142", "Poly-Crete Inc"):
        with pytest.raises(seed.PlanError, match=r"S142.*Poly-Crete"):
            seed.plan_epoxy(_SHEETS, seed.Plan())


# ── the statement groups: the flagged exceptions to insert-only, proven by running them ───────────────────────────
def _library_db(plan, with_plan=True, groups=()):
    """The tables of _sqlite_for plus the soft-delete column and the vendor list, and the plan's statements run on them
    (sqlite stands in for Postgres: now() and chr() are spelled for it, nothing else changes what the statements do)."""
    db = _sqlite_for(plan)
    for table in ("library_items", "library_assemblies"):
        db.execute("alter table %s add column deleted_at" % table)
    return db


def _exec(db, script):
    db.executescript(script.replace("public.", "").replace("::jsonb", "").replace("now()", "'NOW'").replace("chr(", "char("))


def _row(db, table, id_):
    cur = db.execute("select * from %s where id = ?" % table, (id_,))
    cols = [c[0] for c in cur.description]
    return dict(zip(cols, cur.fetchone()))


def test_the_default_script_has_none_of_the_exception_groups(plan):
    script = seed.sql_script(plan)
    assert "EXCEPTION GROUP" not in script
    unquoted = re.sub(r"'(?:[^']|'')*'", "''", script)
    for word in ("update", "delete", "drop", "truncate", "alter", "do update"):
        assert not re.search(r"\b%s\b" % word, unquoted, re.I), word
    # the vendor dropdown rows are inserts too, each one guarded so a vendor already there is not added twice
    stmts = seed.vendor_statements(plan)
    assert len(stmts) == 2 and all(s.startswith("insert into public.library_vendors") and s.endswith("on conflict (id) do nothing;")
                                   and "where not exists" in s for s in stmts)


def test_the_vendor_dropdown_rows_are_added_once_and_never_beside_a_vendor_that_is_already_there(plan):
    db = _library_db(plan)
    db.execute("insert into library_vendors (id, name, notes) values ('v-kyle', ' sherwin-williams ', 'Kyle typed this')")
    db.execute("insert into library_vendors (id, name, deleted_at) values ('v-old', 'Poly-Crete', '2026-01-01')")
    script = seed.sql_script(plan)
    _exec(db, script)
    _exec(db, script)
    names = db.execute("select id, name from library_vendors order by id").fetchall()
    assert ("wb-vendor-sherwin-williams", "Sherwin-Williams") not in names, "a live vendor of that name was already there"
    assert ("v-kyle", " sherwin-williams ") in names
    assert [n for n in names if n[1] == "Poly-Crete"] == [("v-old", "Poly-Crete"), ("wb-vendor-poly-crete", "Poly-Crete")], (
        "a soft-deleted vendor does not block the name, and the second run added nothing")
    assert db.execute("select count(*) from library_vendors").fetchone()[0] == 3


def test_a_fresh_epoxy_row_is_inserted_with_its_vendor(plan):
    db = _library_db(plan)
    _exec(db, seed.sql_script(plan))
    assert db.execute("select vendor from library_items where id = 'wb-epoxy-cove-wr'").fetchone() == (PC,)
    assert db.execute("select vendor from library_items where id = 'wb-epoxy-cove-silica'").fetchone() == (None,)


def test_tag_vendors_fills_a_null_vendor_and_touches_nothing_else_and_never_a_vendor_somebody_set(plan):
    db = _library_db(plan)
    seeded_before = "insert into library_items (id, name, unit, buy_qty, unit_cost, coverage, waste_pct, roundup, notes, vendor) values "
    db.execute(seeded_before + "('wb-epoxy-cove-rez', 'Cove Rez (Kyle renamed)', 'Gallon', 1, 91.5, 1, 7, 1, 'kyle note', NULL)")
    db.execute(seeded_before + "('wb-epoxy-cove-wr', 'WR cove kit', 'Kit', 1, 66.6952, 1, 0, 0, 'n', 'Kyle''s own supplier')")
    db.execute(seeded_before + "('wb-epoxy-cove-silica', 'Silica', 'Bag', 1, 22, 1, 0, 0, 'n', NULL)")
    db.execute(seeded_before + "('not-ours', 'Hand-typed item', 'Each', 1, 3, 1, 0, 0, 'n', NULL)")
    before = {i: _row(db, "library_items", i) for i in ("wb-epoxy-cove-rez", "wb-epoxy-cove-wr", "wb-epoxy-cove-silica", "not-ours")}
    script = seed.sql_script(plan, (seed.GROUP_TAG_VENDORS,))
    _exec(db, script)
    _exec(db, script)
    after = {i: _row(db, "library_items", i) for i in before}
    assert after["wb-epoxy-cove-rez"]["vendor"] == SW, "a NULL vendor is filled"
    assert after["wb-epoxy-cove-wr"]["vendor"] == "Kyle's own supplier", "a vendor somebody set is never changed"
    assert after["wb-epoxy-cove-silica"]["vendor"] is None, "a row with no discount group stays NULL"
    assert after["not-ours"]["vendor"] is None, "a row that is not the seed's is not touched"
    for i, was in before.items():
        assert {k: v for k, v in after[i].items() if k != "vendor"} == {k: v for k, v in was.items() if k != "vendor"}, (
            "the group changes the vendor column and no other: " + i)


def test_the_tag_vendors_statements_are_only_updates_of_vendor_where_it_is_null(plan):
    stmts = seed.exception_statements(plan, (seed.GROUP_TAG_VENDORS,))
    assert stmts[0].startswith("-- EXCEPTION GROUP tag-vendors")
    updates = stmts[1:]
    assert len(updates) == sum(1 for i in plan.items.values() if i.get("vendor")) == 29
    for u in updates:
        assert re.fullmatch(r"update public\.library_items set vendor = '[^']+' where id = '[a-z0-9-]+' and vendor is null;", u), u


def test_the_gyp_sand_moves_from_35_to_40_only_where_it_is_still_35(plan):
    db = _library_db(plan)
    ins = "insert into library_items (id, name, unit, buy_qty, unit_cost, coverage, waste_pct, roundup, notes) values "
    db.execute(ins + "('wb-gyp-sand-per-ton', 'Sand, per ton', 'Ton', 1, 35.0, NULL, 0, 1, 'seeded')")
    db.execute(ins + "('other-sand', 'Sand', 'Ton', 1, 35.0, NULL, 0, 1, 'x')")
    before = _row(db, "library_items", "wb-gyp-sand-per-ton")
    other = _row(db, "library_items", "other-sand")
    script = seed.sql_script(plan, (seed.GROUP_GYP_SAND,))
    _exec(db, script)
    _exec(db, script)
    after = _row(db, "library_items", "wb-gyp-sand-per-ton")
    assert after["unit_cost"] == 40.0
    assert {k: v for k, v in after.items() if k != "unit_cost"} == {k: v for k, v in before.items() if k != "unit_cost"}
    assert _row(db, "library_items", "other-sand") == other, "another row at 35 is not the sand"
    # a price Kyle moved is left exactly as he left it
    kyle = _library_db(plan)
    kyle.execute(ins + "('wb-gyp-sand-per-ton', 'Sand, per ton', 'Ton', 1, 37.5, NULL, 0, 1, 'seeded')")
    _exec(kyle, script)
    assert kyle.execute("select unit_cost from library_items where id = 'wb-gyp-sand-per-ton'").fetchone() == (37.5,)
    # and a row already at 40 is simply still 40
    done = _library_db(plan)
    done.execute(ins + "('wb-gyp-sand-per-ton', 'Sand, per ton', 'Ton', 1, 40.0, NULL, 0, 1, 'seeded')")
    _exec(done, script)
    assert done.execute("select unit_cost from library_items where id = 'wb-gyp-sand-per-ton'").fetchone() == (40.0,)


def test_the_sand_move_is_written_for_the_template_it_was_found_against(plan):
    assert plan.items["wb-gyp-sand-per-ton"]["unit_cost"] == seed.GYP_SAND_FROM == 35.0 and seed.GYP_SAND_TO == 40.0
    with edited("Gyp (USG 1-8\")", "v", "D33", 38), edited("Gyp (FR)", "v", "D33", 38):     # the two tabs share the price
        with pytest.raises(seed.PlanError, match=r"sand is 38"):
            seed.exception_statements(seed.make_plan(sheets=_SHEETS, only="gyp"), (seed.GROUP_GYP_SAND,))
    with pytest.raises(seed.PlanError, match=r"needs the gyp plan"):
        seed.exception_statements(seed.make_plan(sheets=_SHEETS, only="seal"), (seed.GROUP_GYP_SAND,))
    with pytest.raises(seed.PlanError, match=r"needs the epoxy plan"):
        seed.exception_statements(seed.make_plan(sheets=_SHEETS, only="polish"), (seed.GROUP_TAG_VENDORS,))
    with pytest.raises(seed.PlanError, match=r"unknown statement group"):
        seed.exception_statements(plan, ("everything",))


def test_the_beta_sample_is_soft_deleted_by_exact_name_and_only_while_live(plan):
    db = _library_db(plan)
    ia = "insert into library_assemblies (id, name, unit, lines, category) values "
    ii = "insert into library_items (id, name, unit, buy_qty, unit_cost, coverage, waste_pct, roundup, notes) values "
    db.execute(ia + "('a-beta', 'Polish \u2014 Salt & Pepper (beta sample)', 'SF', '[]', 'Polished Concrete')")
    db.execute(ia + "('a-real', 'Polish \u2014 Salt & Pepper', 'SF', '[]', 'Polished Concrete')")
    db.execute(ia + "('a-gone', 'Polish \u2014 Salt & Pepper (beta sample)', 'SF', '[]', 'x')")
    db.execute("update library_assemblies set deleted_at = '2026-10-01' where id = 'a-gone'")
    db.execute(ii + "('i-beta', 'OPF \u2014 5 gal pail (beta sample)', 'Pail', 1, 450, 1, 0, 1, 'Sample row. Safe to delete.')")
    db.execute(ii + "('i-real', 'OPF, 275 SF/Gallon', 'Gallon', 1, 85, 275, 0, 1, 'real')")
    before = {t: {r[0]: r for r in db.execute("select * from %s" % t)} for t in ("library_assemblies", "library_items")}
    script = seed.sql_script(plan, (seed.GROUP_BETA_SAMPLE,))
    assert " ".join(seed.exception_statements(plan, (seed.GROUP_BETA_SAMPLE,))).isascii(), "the em dash is spelled chr(8212), so no console or ssh encoding can change what the name matches"
    _exec(db, script)
    _exec(db, script)
    asm = {r[0]: r for r in db.execute("select * from library_assemblies")}
    itm = {r[0]: r for r in db.execute("select * from library_items")}
    cols = [c[1] for c in db.execute("pragma table_info(library_assemblies)")]
    di = cols.index("deleted_at")
    assert asm["a-beta"][di] == "NOW" and asm["a-real"][di] is None
    assert asm["a-gone"][di] == "2026-10-01", "a row that is already deleted keeps the date it was deleted"
    icols = [c[1] for c in db.execute("pragma table_info(library_items)")]
    ii_ = icols.index("deleted_at")
    assert itm["i-beta"][ii_] == "NOW" and itm["i-real"][ii_] is None
    for t, rows in (("library_assemblies", asm), ("library_items", itm)):
        k = cols.index("deleted_at") if t == "library_assemblies" else ii_
        for id_, was in before[t].items():
            assert [v for j, v in enumerate(rows[id_]) if j != k] == [v for j, v in enumerate(was) if j != k], (
                "only deleted_at changes: " + id_)


def test_the_flags_print_the_groups_and_apply_sends_them_only_when_asked(monkeypatch, capsys, plan):
    monkeypatch.setattr(seed, "load", lambda path=None: _SHEETS)
    assert seed.main(["--sql", "--tag-vendors", "--gyp-sand-40", "--retire-beta-sample"]) == 0
    out = capsys.readouterr().out
    for g in seed.GROUPS:
        assert "-- EXCEPTION GROUP %s" % g in out, g
    assert seed.main(["--sql"]) == 0 and "EXCEPTION GROUP" not in capsys.readouterr().out
    assert seed.main(["--tag-vendors"]) == 2 and "add --sql" in capsys.readouterr().err
    assert seed.main(["--only", "polish", "--sql", "--tag-vendors"]) == 1 and "needs the epoxy plan" in capsys.readouterr().err
    calls = []

    def fake(args, input=None, **kw):
        calls.append(input)
        assert kw.get("encoding") == "utf-8", "the script goes over ssh as utf-8 whatever the console's code page is"
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(seed.subprocess, "run", fake)
    assert seed.main(["--apply", "--target", "staging"]) == 0
    assert seed.main(["--apply", "--target", "staging", "--gyp-sand-40"]) == 0
    assert "EXCEPTION GROUP" not in calls[0] and "-- EXCEPTION GROUP gyp-sand-40" in calls[1]
    assert seed.main(["--apply", "--target", "staging", "--only", "polish", "--tag-vendors"]) == 1
    assert len(calls) == 2, "a group that cannot be built stops the run before anything is sent"


def test_a_kyle_edited_polish_row_survives_the_script(plan):
    db = _library_db(plan)
    db.execute("insert into library_items (id, name, unit_cost, coverage) values ('wb-polish-sealer', 'Polish sealer (Kyle)', 0.13, 1)")
    db.execute("insert into library_assemblies (id, name) values ('wb-polish-sys-cream', 'Cream (Kyle)')")
    _exec(db, seed.sql_script(plan))
    assert db.execute("select name, unit_cost from library_items where id = 'wb-polish-sealer'").fetchall() == [("Polish sealer (Kyle)", 0.13)]
    assert db.execute("select name from library_assemblies where id = 'wb-polish-sys-cream'").fetchall() == [("Cream (Kyle)",)]


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
    db.execute("create table library_vendors (id primary key, name, notes, deleted_at)")
    db.execute("insert into library_items (id, name) values ('wb-epoxy-patch', 'edited')")
    db.executescript(mod.sql_script(plan).replace("public.", "").replace("::jsonb", ""))
    assert db.execute("select name from library_items where id = 'wb-epoxy-patch'").fetchone()[0] != "edited", (
        "the mutated script overwrote the row, and the insert-only test above is what would have said so")


def test_the_checks_notice_a_target_that_is_not_staging(tmp_path, monkeypatch):
    mod = _mutated(tmp_path, 'if args.target != "staging":', 'if args.target not in ("staging", "production"):')
    monkeypatch.setattr(mod.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(args, 0, stdout="", stderr=""))
    monkeypatch.setattr(mod, "load", lambda path=None: _SHEETS)
    assert mod.main(["--apply", "--target", "production"]) == 0, "the mutation lets production through, which the refusal test forbids"


def test_the_checks_notice_a_vendor_fill_that_overwrites(tmp_path):
    mod = _mutated(tmp_path, ' where id = %s and vendor is null;"', ' where id = %s;"')
    p = mod.make_plan(sheets=_SHEETS)
    db = sqlite3.connect(":memory:")
    db.execute("create table library_items (id primary key, vendor)")
    db.execute("insert into library_items values ('wb-epoxy-cove-wr', 'Kyle''s own supplier')")
    db.executescript("\n".join(s for s in mod.exception_statements(p, (mod.GROUP_TAG_VENDORS,)) if s.startswith("update")).replace("public.", ""))
    assert db.execute("select vendor from library_items").fetchone()[0] != "Kyle's own supplier", (
        "the mutated group overwrote a vendor somebody set, which the vendor test above forbids")


def test_the_checks_notice_a_sand_move_that_ignores_the_current_price(tmp_path):
    mod = _mutated(tmp_path, " and unit_cost = %s;\"", " and unit_cost = %s or 1;\"")
    p = mod.make_plan(sheets=_SHEETS)
    db = sqlite3.connect(":memory:")
    db.execute("create table library_items (id primary key, unit_cost)")
    db.execute("insert into library_items values ('wb-gyp-sand-per-ton', 37.5)")
    db.executescript("\n".join(s for s in mod.exception_statements(p, (mod.GROUP_GYP_SAND,)) if s.startswith("update")).replace("public.", ""))
    assert db.execute("select unit_cost from library_items").fetchone()[0] == 40.0, (
        "the mutated move overwrote a price Kyle edited, which the sand test above forbids")


def test_the_checks_notice_a_polish_assembly_that_drops_the_grout(tmp_path):
    mod = _mutated(tmp_path, '("Full", "wb-polish-sys-full-aggregate", "Polish \u2014 Full aggregate", True)',
                   '("Full", "wb-polish-sys-full-aggregate", "Polish \u2014 Full aggregate", False)')
    assert len(mod.make_plan(sheets=_SHEETS, only="polish").assemblies["wb-polish-sys-full-aggregate"]["lines"]) == 2
