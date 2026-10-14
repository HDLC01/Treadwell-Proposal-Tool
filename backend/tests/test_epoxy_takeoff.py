"""Phase 12: js/epoxy-takeoff.js, the part of the Epoxy tab that a library row cannot say.

The contract it follows is the one Dye and Joint Filler follow (docs/v2-architecture.md, rule 3): the FORMULA is code,
the PRICES it reads are editable library rows, and a constant in the code is only the fallback for a database the seed
has not reached. What that makes testable, and what is tested here:

  * ROW = FALLBACK   every constant in PRICE_ROWS equals the row the seed script plans, and the cell it names is the
                     cell the planner reads. Edit one and not the other and this goes red.
  * THE FORMULA IS THE TEMPLATE'S   every divisor of every cove (COVE), the pounds of aggregate, the cap, the quartz
                     systems and the tooling constants are read back out of the template's own cells.
  * THE ROWS ARE READ   a price changed on the library row changes the price; with no row the fallback prices, to the
                     same figure.
  * THE PLAN MATCHES THE CODE   every cove assembly the seed plans has an entry in COVE and the other way round.

How the whole thing prices against the workbook is test_epoxy_v2_proof.py.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import subprocess

import pytest

from _node import require_node
from _seed_support import PLAN, SHEETS, seed

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
MODULE = FRONTEND / "js" / "epoxy-takeoff.js"


def node(code: str):
    node_path = require_node()
    proc = subprocess.run([node_path, "-e", code], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def load_mod(path=MODULE):
    return node("""
      const X = require(%s);
      console.log(JSON.stringify({ PRICE_ROWS: X.PRICE_ROWS, COVE: X.COVE, QUARTZ: X.QUARTZ_SYSTEMS, TOOLING: X.TOOLING,
        CAP: X.CAP_STICK_LF, BAG: X.AGGREGATE_BAG_LB }));
    """ % json.dumps(str(path)))


@pytest.fixture(scope="module")
def mod():
    require_node()
    return load_mod()


def _eval(expr: str) -> float:
    """An arithmetic expression out of a template cell (`30`, `(21/2)`, `35/2`), and nothing else: numbers and the four
    operators, read from the syntax tree, so no text is ever run."""
    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            v = walk(node.operand)
            return v if isinstance(node.op, ast.UAdd) else -v
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            a, b = walk(node.left), walk(node.right)
            return {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b, ast.Div: a / b if b else float("nan")}[type(node.op)]
        raise AssertionError("not plain arithmetic: " + expr)
    return walk(ast.parse(expr.strip(), mode="eval"))


def _formula_arg(sheet, addr: str, pattern: str) -> float:
    f = sheet.formula(addr)
    if not isinstance(f, str):
        return float(sheet.value(addr))
    m = re.fullmatch(pattern, f)
    assert m, "%s holds %r, not the shape the code copies" % (addr, f)
    return _eval(m.group(1))


# ── row = fallback ───────────────────────────────────────────────────────────
def check_fallbacks(mod):
    for key, spec in mod["PRICE_ROWS"].items():
        row = PLAN.items[spec["id"]]
        assert row["unit_cost"] / row["buy_qty"] == pytest.approx(spec["fallback"], abs=1e-9), key
        planned = seed.RESERVED_PRICE_ROWS[spec["id"]]
        assert planned["cell"] == spec["cell"], "%s: the code reads %s and the seed plans %s" % (key, spec["cell"], planned["cell"])
        sheet_value = SHEETS["Epoxy"].value(spec["cell"])
        assert spec["fallback"] == pytest.approx(sheet_value, abs=0.00006), "%s is not the template's figure in %s" % (key, spec["cell"])
    assert set(spec["id"] for spec in mod["PRICE_ROWS"].values()) == set(seed.RESERVED_PRICE_ROWS)


def test_every_fallback_equals_the_row_the_seed_plans_and_reads_the_same_cell(mod):
    check_fallbacks(mod)


def test_a_price_edited_on_the_library_row_reaches_the_price_and_no_row_prices_at_the_fallback(mod):
    got = node("""
      const X = require(%s);
      const rows = %s;
      const price = (items) => X.priceCoveRow("wb-epoxy-cove-epoxy-4in", 300, { items: items, quartz: false }).total;
      const edited = rows.map((r) => r.id === "wb-epoxy-cove-rez" ? Object.assign({}, r, { unit_cost: 100 }) : r);
      console.log(JSON.stringify({ rows: price(rows), none: price([]), edited: price(edited),
        patchRow: X.patchCost(rows, 1000), patchNone: X.patchCost([], 1000),
        unit: X.unitPrice(rows, "silica"), unitNone: X.unitPrice([], "silica") }));
    """ % (json.dumps(str(MODULE)), json.dumps([i for i in PLAN.as_dict()["items"] if i["id"].startswith("wb-epoxy-")])))
    assert got["rows"] == pytest.approx(got["none"], abs=1e-9), "the seeded rows and the fallbacks must price the same"
    assert got["edited"] > got["rows"] + 50, "300 LF of 4 inch cove buys 5 resin units: $100 against $88.83 each"
    assert got["patchRow"] == pytest.approx(got["patchNone"]) == pytest.approx(100.0)
    assert got["unit"] == {"cost": 0.44, "from": "library"} and got["unitNone"] == {"cost": 0.44, "from": "fallback"}


def test_a_cove_priced_by_hand_from_the_sheets_own_formulas(mod):
    """300 LF of 4 inch epoxy cove: gallons = ROUNDUP(300 / 30) = 10; resin units = ROUNDUP(10 / 8) + ROUNDUP(10 / 4) =
    2 + 3 = 5 at $88.8308; aggregate = CEILING(10 * 25, 50) = 250 lb, silica at $0.44 or quartz at $0.47."""
    got = node("""
      const X = require(%s);
      const c = (q) => X.priceCoveRow("wb-epoxy-cove-epoxy-4in", 300, { items: [], quartz: q });
      console.log(JSON.stringify({ silica: c(false), quartz: c(true) }));
    """ % json.dumps(str(MODULE)))
    resin = 5 * 88.8308
    assert got["silica"]["total"] == pytest.approx(resin + 250 * 0.44)
    assert got["quartz"]["total"] == pytest.approx(resin + 250 * 0.47)
    assert [r["role"] for r in got["silica"]["rows"]] == ["Cove liquids", "Aggregate"]
    assert got["silica"]["priced_lines"] == 2 and got["silica"]["broken_lines"] == 0


def test_a_cove_with_no_length_prices_no_lines_not_zero(mod):
    got = node("""
      const X = require(%s);
      console.log(JSON.stringify([0, "", null, undefined, -5].map((lf) => X.priceCoveRow("wb-epoxy-cove-wr-4in", lf, {}))));
    """ % json.dumps(str(MODULE)))
    for r in got:
        assert r["priced_lines"] == 0 and r["per_unit"] is None and r["total"] == 0


def test_a_cove_row_for_an_assembly_that_is_not_a_cove_is_refused():
    got = node("""
      const X = require(%s);
      try { X.priceCoveRow("wb-epoxy-sys-dur-a-gard", 100, {}); console.log(JSON.stringify("no error")); }
      catch (e) { console.log(JSON.stringify(String(e.message))); }
    """ % json.dumps(str(MODULE)))
    assert "not a cove assembly" in got


# ── the formula is the template's ────────────────────────────────────────────
def check_cove_table(mod):
    """The gallons a foot of cove takes, the pounds of aggregate a gallon takes and the cap, for each of the twelve
    cove options, read out of the cells Cove 1 Options (S125 to S136) points at."""
    ws = SHEETS["Epoxy"]
    epoxy = {   # option -> (the cell that divides the length into gallons, the cell of the pounds a gallon takes, cap?)
        "Epoxy 4\"": ("C125", "C126", False), "Epoxy 6\"": ("C130", "C131", False),
        "Epoxy 4\" + Cap": ("C135", "C136", True), "Epoxy 6\" + Cap": ("C141", "C142", True),
        "Epoxy 8\"": ("C147", "C148", False), "Epoxy 8\" + Cap": ("C152", "C153", True)}
    wr = {"WR 4\"": ("M125", False), "WR 6\"": ("M130", False), "WR 4\" + Cap": ("M135", True),
          "WR 6\" + Cap": ("M141", True), "WR 8\"": ("M147", False), "WR 8\" + Cap": ("M152", True)}
    names = {ws.text("S%d" % r) for r in range(125, 137)}
    assert names == set(epoxy) | set(wr), "the template's cove options changed"
    for name, (per_cell, lbs_cell, cap) in epoxy.items():
        entry = mod["COVE"]["wb-epoxy-cove-" + seed._slug(name)]
        # `=ROUNDUP(I123/30,0)`, `=ROUNDUP(I145/(21/2),0)`: what the length is divided by
        per = _formula_arg(ws, per_cell, r"=ROUNDUP\(I\d+/(.+),0\)")
        assert (entry["kind"], entry["per"], entry["lbs"], entry["cap"]) == ("epoxy", per, float(ws.value(lbs_cell)), cap), name
    for name, (per_cell, cap) in wr.items():
        entry = mod["COVE"]["wb-epoxy-cove-" + seed._slug(name)]
        per = float(ws.value(per_cell))
        assert (entry["kind"], entry["per"], entry["cap"]) == ("wr", per, cap), name
    assert set(mod["COVE"]) == {"wb-epoxy-cove-" + seed._slug(n) for n in names}


def test_every_cove_divisor_is_the_templates(mod):
    check_cove_table(mod)


def test_the_resin_units_the_stick_the_bag_and_the_cap_are_the_templates(mod):
    ws = SHEETS["Epoxy"]
    # E125: ROUNDUP(gallons / 8) + ROUNDUP(gallons / 4); C126's "Lbs/LF" label is per gallon (E126 = CEILING(C125*C126, 50))
    for addr in ("E125", "E130", "E135", "E141", "E147", "E152"):
        assert re.fullmatch(r"=ROUNDUP\(C\d+/8,0\)\+ROUNDUP\(C\d+/4,0\)", ws.formula(addr)), addr
    for addr in ("E126", "E131", "E136", "E142", "E148", "E153"):
        assert re.fullmatch(r"=CEILING\(C\d+\*C\d+,%d\)" % mod["BAG"], ws.formula(addr)), addr
    for addr in ("E137", "E143", "E154"):                           # the cap: CEILING(length * 1, 8) at $0.75 a foot
        assert re.fullmatch(r"=CEILING\(I\d+\*C\d+,%d\)" % mod["CAP"], ws.formula(addr)), addr
    for addr in ("O153", "O142", "O136"):
        assert re.fullmatch(r"=CEILING\(I\d+\*M\d+,%d\)" % mod["CAP"], ws.formula(addr)), addr
    for addr in ("O125", "O130", "O135", "O141", "O147", "O152"):   # WR: ROUNDUP(length / coverage, 0) kits
        assert re.fullmatch(r"=ROUNDUP\(I\d+/M\d+,0\)", ws.formula(addr)), addr


def check_quartz(mod):
    """Epoxy!F126 is `IF($A$22=$R$189,Q28_40s,IF($A$22=$R$190,Q28_40s,IF($A$22=$R$191,Q28_40s,Silica)))`."""
    ws = SHEETS["Epoxy"]
    f = ws.formula("F126")
    named = re.findall(r"\$A\$22=\$R\$(\d+)", f)
    assert named == ["189", "190", "191"] and f.endswith(",Silica))))"), f
    ids = ["wb-epoxy-sys-" + seed._slug(ws.text("R%s" % r)) for r in named]
    assert mod["QUARTZ"] == ids
    assert set(ids) <= set(PLAN.assemblies)
    # and the same test in every aggregate cell of both halves: no cell follows System 2's choice ($A$26)
    for addr in ("F126", "F131", "F136", "F142", "F148", "F153", "AF126", "AF131", "AF136", "AF142", "AF148", "AF153"):
        assert "$A$22" in ws.formula(addr) and "$A$26" not in ws.formula(addr), addr


def test_the_quartz_systems_are_the_three_the_cove_aggregate_formula_names(mod):
    check_quartz(mod)


def check_tooling(mod):
    ws = SHEETS["Epoxy"]
    t = mod["TOOLING"]
    assert ws.formula("B58") == "=ROUNDUP(IF(B45>%d,B45/%d,%d),0)" % (t["moistureAfterSf"], t["moistureEverySf"], t["moistureMinTests"])
    assert float(ws.value("C58")) == t["moistureCost"]
    assert ws.formula("D58") == "=ROUNDUP(B58*C58,0)"
    assert ws.formula("D59") == "=ROUNDUP(IF((B59*C59)>%d,(B59*C59),%d),0)" % (t["consumablesMin"], t["consumablesMin"])
    assert float(ws.value("C59")) == t["consumablesPerSf"] and ws.formula("B59") == "=B45"
    assert ws.formula("B45") == "=E20+E24", "the area tooling is judged on is System 1 plus System 2"
    assert ws.formula("D62") == "=SUM(D58:D61)"
    assert float(ws.value("C18")) == 0.1 and ws.formula("B18") == "=E20" and ws.formula("B19") == "=E24" and ws.formula("C19") == "=C18"


def test_the_tooling_constants_are_the_templates(mod):
    check_tooling(mod)


def test_tooling_by_hand_and_for_no_area(mod):
    got = node("""
      const X = require(%s);
      console.log(JSON.stringify([0, -1, 1, 500, 2000, 2001, 6000, 12345].map((sf) => [sf, X.toolingCost(sf)])));
    """ % json.dumps(str(MODULE)))
    # 1 SF: 2 tests ($70) + the $150 floor; 500 SF: $70 + 500 x 0.33 = $165 is past the floor; 2,000 SF is still 2 tests;
    # 2,001 SF: ROUNDUP(2.001) = 3 tests ($105) + $660.33 up to $661; 6,000 SF: 6 tests ($210) + $1,980;
    # 12,345 SF: 13 tests ($455) + $4,073.85 up to $4,074
    assert dict(map(tuple, got)) == {0: 0, -1: 0, 1: 220, 500: 70 + 165, 2000: 70 + 660, 2001: 105 + 661, 6000: 2190,
                                     12345: 13 * 35 + 4074}


# ── the seed and the code agree on the coves ─────────────────────────────────
def test_the_cove_assemblies_the_seed_plans_are_the_ones_the_code_prices(mod):
    planned = {a for a in PLAN.assemblies if a.startswith("wb-epoxy-cove-")}
    assert planned == set(mod["COVE"])
    # every planned cove lists the materials its formula reads, so the Items tab shows what a cove buys
    for aid, entry in mod["COVE"].items():
        asm = PLAN.assemblies[aid]
        ids = [ln["item_id"] for ln in asm["lines"]]
        assert ("wb-epoxy-cove-rez" in ids) == (entry["kind"] == "epoxy")
        assert ("wb-epoxy-cove-wr" in ids) == (entry["kind"] == "wr")
        assert ("wb-epoxy-cove-silica" in ids) == (entry["kind"] == "epoxy")
        assert ("wb-epoxy-cove-zinc-cap" in ids) == entry["cap"]
        assert asm["unit"] == "LF"


def test_the_systems_are_not_confused_with_walls_or_with_a_system_that_is_not_one():
    got = node("""
      const X = require(%s);
      const row = (id, over) => Object.assign({ assembly_id: id, measurement: 100, unit: "SF" }, over || {});
      console.log(JSON.stringify({
        quartzFirst: X.systemOneIsQuartz([row("wb-epoxy-sys-40-s-q28-quartz-double-broadcast")]),
        flakeFirst: X.systemOneIsQuartz([row("wb-epoxy-sys-macro-flake-single-broadcast"), row("wb-epoxy-sys-40-s-q28-quartz-double-broadcast")]),
        wallSkipped: X.systemOneIsQuartz([row("wb-epoxy-sys-walls-troweled-quartz"), row("wb-epoxy-sys-macro-flake-single-broadcast")]),
        primerThenQuartz: X.systemOneIsQuartz([row("wb-epoxy-primer-mvp-12-mils"), row("wb-epoxy-sys-40-s-q28-quartz-double-broadcast")]),
        offSkipped: X.systemOneIsQuartz([row("wb-epoxy-sys-macro-flake-single-broadcast", { enabled: false }), row("wb-epoxy-sys-40-s-q28-quartz-double-broadcast")]),
        kylesOwn: X.systemOneIsQuartz([row("some-assembly-kyle-made")]),
        none: [X.systemOneIsQuartz([]), X.systemOneIsQuartz(null), X.systemOneIsQuartz([{ assembly_id: "" }])],
      }));
    """ % json.dumps(str(MODULE)))
    assert got == {"quartzFirst": True, "flakeFirst": False, "wallSkipped": False, "primerThenQuartz": True,
                   "offSkipped": True, "kylesOwn": False, "none": [False, False, False]}


# ── the layer ────────────────────────────────────────────────────────────────
def test_the_module_names_what_it_needs_and_touches_no_page():
    src = MODULE.read_text(encoding="utf-8")
    assert "needs excel-math.js loaded before it" in src and "needs library-core.js loaded before it" in src
    for forbidden in ("document.", "fetch(", "Date.now", "new Date", "localStorage", "window."):
        assert forbidden not in src, forbidden


# ── red without the code ─────────────────────────────────────────────────────
PIN_BREAKS = {
    "a fallback is not the seeded price": (
        "    coveRez:  { id: \"wb-epoxy-cove-rez\",      cell: \"T152\", fallback: 88.8308 },",
        "    coveRez:  { id: \"wb-epoxy-cove-rez\",      cell: \"T152\", fallback: 88.83 },", check_fallbacks),
    "a fallback reads the wrong cell": (
        "    silica:   { id: \"wb-epoxy-cove-silica\",   cell: \"W145\", fallback: 0.44 },",
        "    silica:   { id: \"wb-epoxy-cove-silica\",   cell: \"W146\", fallback: 0.44 },", check_fallbacks),
    "a cove loses its cap": (
        '    "wb-epoxy-cove-epoxy-4in-plus-cap": { kind: "epoxy", per: 15,   lbs: 25, cap: true },',
        '    "wb-epoxy-cove-epoxy-4in-plus-cap": { kind: "epoxy", per: 15,   lbs: 25, cap: false },', check_cove_table),
    "a WR cove divides by the wrong kit": (
        '    "wb-epoxy-cove-wr-8in":             { kind: "wr", per: 17.5, cap: false },',
        '    "wb-epoxy-cove-wr-8in":             { kind: "wr", per: 18,   cap: false },', check_cove_table),
    "a quartz system is left off": (
        '    "wb-epoxy-sys-hybrid-quartz-double-broadcast-standard-texture",\n', "", check_quartz),
    "the tooling floor moves": (
        "consumablesPerSf: 0.33, consumablesMin: 150 };", "consumablesPerSf: 0.33, consumablesMin: 100 };", check_tooling),
}


@pytest.mark.parametrize("name", sorted(PIN_BREAKS))
def test_the_pins_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    old, new, check = PIN_BREAKS[name]
    src = MODULE.read_bytes().decode("utf-8").replace(chr(13) + chr(10), chr(10))
    assert src.count(old) == 1, "the mutation anchor is in the module %d times, not once" % src.count(old)
    scratch = tmp_path / "frontend" / "js"
    scratch.mkdir(parents=True)
    (scratch / "epoxy-takeoff.js").write_bytes(src.replace(old, new).encode("utf-8"))
    for dep in ("excel-math.js", "library-core.js"):
        (scratch / dep).write_bytes((FRONTEND / "js" / dep).read_bytes())
    broken = load_mod(scratch / "epoxy-takeoff.js")
    check(load_mod())                                   # the real module passes it
    with pytest.raises(AssertionError):
        check(broken)
