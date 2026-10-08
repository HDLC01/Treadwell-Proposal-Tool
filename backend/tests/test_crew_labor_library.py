"""Phase LS1 of the v2 estimating program (Hanz, 2026-10-09): every v2 labor line comes from the
Labor list ("Labor is like the Items tab for pulling in data in the estimate sheet").

  1. THE CREW LINES ARE LIBRARY ROWS. Polishing, Mock-up and Joint filler were hard-coded; they are
     rows of public.library_labor with the SAME ids (backend/ops/seed_crew_labor.sql), their starting
     guys / days are `fixed` rows of library_labor_calc, and a NEW bid takes them like any other
     default. bid-model.js SHIPPED_CREW is only the fallback when the library cannot answer, and the
     SQL seed is pinned equal to it below.
  2. A BLANK RATE IS THE LINE'S OWN RATE, not $0; typing 0 is still zero; an off line is still nothing.
  3. NO EMPTY CARDS: a saved draft's rows with no name, no guys and no days are not opened.

EVERYTHING HERE RUNS THE REAL CODE: tests/js/polish-estimate-harness.js drives the real page (block
"LS1"), tests/js/crew-labor-harness.js the real bid-model. Each protection is shown red on a scratch
copy of the source with one line put back (the anchor must be in the file exactly once, so none of
them can pass by applying nowhere).
"""
import json
import pathlib
import re
import shutil

import pytest

from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
FRONTEND = TESTS.parents[1] / "frontend"
OPS = TESTS.parents[1] / "backend" / "ops"
PAGE_HARNESS = TESTS / "js" / "polish-estimate-harness.js"
MODEL_HARNESS = TESTS / "js" / "crew-labor-harness.js"


def _page(frontend):
    p = run_node(PAGE_HARNESS, frontend, timeout=240)
    assert p.returncode == 0, "the harness itself failed:\n" + p.stderr
    return last_json_line(p.stdout)


def _model(frontend):
    p = run_node(MODEL_HARNESS, frontend)
    assert p.returncode == 0, p.stderr
    return last_json_line(p.stdout)


@pytest.fixture(scope="module")
def page():
    require_node()
    return _page(FRONTEND)


@pytest.fixture(scope="module")
def model():
    require_node()
    return _model(FRONTEND)


def mutated(tmp_path, rel, old, new):
    """A scratch copy of the whole frontend with one line of `rel` changed. The anchor must be there
    exactly once."""
    dest = tmp_path / "frontend"
    shutil.copytree(FRONTEND, dest)
    f = dest / rel
    src = f.read_bytes().decode("utf-8")
    assert src.count(old) == 1, "the anchor %r appears %d times in %s" % (old, src.count(old), rel)
    f.write_bytes(src.replace(old, new).encode("utf-8"))
    return dest


# -- 1. the crew lines come from the library ---------------------------------------------------------
def test_a_new_bid_takes_its_crew_lines_from_the_library(page):
    lib = page["ls1Library"]
    # the sheet's order, each line once (the legacy ids are the library ids, so nothing doubles)
    assert lib["ids"] == ["polishing", "mockup", "jointfill", "travel"]
    # Kyle re-rated Polishing to $41 on the Labor tab: that rate is the line's own, over the company $40
    assert lib["polishing"]["rate"] == 41 and lib["polishing"]["calc_default"]["rate"] == 41
    # a name he typed is the card's name; the starting crew comes from the calculator row
    assert lib["mockup"]["label"] == "Mock-up crew"
    assert (lib["polishing"]["guys"], lib["polishing"]["days"]) == (4, "")
    assert (lib["mockup"]["guys"], lib["mockup"]["days"]) == (3, 0.5)
    # a line still on the shipped $33 follows the company rate
    assert lib["mockup"]["rate"] == 40 and lib["jointfill"]["rate"] == 40


def test_when_the_library_cannot_answer_the_shipped_crew_stands_in(page):
    fb = page["ls1Fallback"]
    assert fb["ids"] == ["polishing", "mockup", "jointfill", "travel"]
    assert fb["rows"][:3] == [["polishing", 3, "", 40], ["mockup", 3, 0.5, 40], ["jointfill", 3, "", 40]]


def test_a_line_taken_off_the_defaults_is_not_brought_back_by_the_fallback(page):
    assert page["ls1Removed"] == ["mockup", "jointfill", "travel"]


def test_the_shipped_fallback_is_pinned_equal_to_the_sql_seed(model):
    """The dye / joint filler reserved-row contract: the library is the source, the constant only the
    fallback, and a test holds them equal."""
    sql = (OPS / "seed_crew_labor.sql").read_text(encoding="utf-8")
    labor_sql, calc_sql = sql.split("insert into public.library_labor_calc")
    rows = {}
    for m in re.finditer(r"\('(\w+)',\s*'([^']+)',\s*([\d.]+),\s*'(\w+)',\s*(true|false),\s*(-?\d+),\s*"
                         r"(true|false),\s*'(\[[^']*\])'::jsonb\)", labor_sql):
        rows[m.group(1)] = {"id": m.group(1), "name": m.group(2), "rate": float(m.group(3)),
                            "unit": m.group(4), "guys_auto": m.group(5) == "true", "sort": int(m.group(6)),
                            "favorite": m.group(7) == "true", "default_work_types": json.loads(m.group(8))}
    assert sorted(rows) == ["jointfill", "mockup", "polishing"]
    assert [r["id"] for r in model["rows"]] == ["polishing", "mockup", "jointfill"]
    for shipped in model["rows"]:
        r = rows[shipped["id"]]
        for k in ("name", "rate", "unit", "guys_auto", "sort", "favorite", "default_work_types"):
            assert r[k] == shipped[k], (shipped["id"], k, r[k], shipped[k])
    calcs = {}
    for m in re.finditer(r"\('(\w+)',\s*'(\w+)',\s*null,\s*null,\s*(\d+),\s*(\d+),\s*(null|[\d.]+),\s*null\)",
                         calc_sql):
        calcs[m.group(1)] = {"mode": m.group(2), "hours_per_day": int(m.group(3)), "guys": float(m.group(4)),
                             "days": None if m.group(5) == "null" else float(m.group(5))}
    assert sorted(calcs) == ["jointfill", "mockup", "polishing"]
    assert [c["line_id"] for c in model["calc"]] == ["polishing", "mockup", "jointfill"]
    for shipped in model["calc"]:
        c = calcs[shipped["line_id"]]
        assert c["mode"] == shipped["mode"] and c["hours_per_day"] == shipped["hours_per_day"]
        assert c["guys"] == shipped["guys"] and c["days"] == shipped["days"]
        assert shipped["crew"] is None and shipped["sf_per_day"] is None and shipped["rate"] is None


def test_the_seed_script_is_idempotent_and_changes_no_schema():
    sql = (OPS / "seed_crew_labor.sql").read_text(encoding="utf-8").lower()
    code = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    assert code.count("on conflict (id) do nothing") == 1
    assert code.count("on conflict (line_id) do nothing") == 1
    for ddl in ("create table", "alter table", "drop ", "delete from", "update public"):
        assert ddl not in code, ddl


def test_the_fallback_rule_and_the_old_four_rows_are_one_list(model):
    # freshModel / a model that states no rows still reads the shipped four (the golden pins it),
    # built from the one SHIPPED_CREW list
    assert model["legacy"] == [["polishing", "Polishing", 3, "", 33], ["mockup", "Mock-up", 3, 0.5, 33],
                               ["jointfill", "Joint filler", 3, "", 33], ["travel", "Travel Labor", "", "", 33]]
    assert model["fresh"] == model["legacy"]
    assert model["fallbackWhenNoneListed"] == ["travel", "polishing", "mockup", "jointfill"]
    assert model["fallbackWhenOneListed"] == ["travel", "polishing"]
    assert model["crewFirst"] == ["polishing", "mockup", "jointfill", "travel", "c1"]


# -- 2. a blank rate is the line's own rate ------------------------------------------------------------
def test_a_cleared_rate_box_prices_at_the_lines_own_rate_and_the_box_shows_it_again(page):
    b = page["ls1Blank"]
    assert b["priced"] == 6560                                      # 4 guys x 5 days x $41 x 8
    assert b["whileEmpty"]["rate"] == "" and b["whileEmpty"]["total"] == 6560, "an empty box priced at $0"
    assert b["whileEmpty"]["cost"] == "$6,560"
    # on change the model and the box agree again, in place (the same card node: no rebuild)
    assert b["afterChange"]["rate"] == 41 and b["afterChange"]["box"] == "41"
    assert b["afterChange"]["sameCard"] is True and b["afterChange"]["cost"] == "$6,560"
    assert b["savedWarn"]["hidden"] is True                         # back at the default: no warning


def test_typing_zero_is_still_zero_and_an_off_line_is_still_nothing(page):
    b = page["ls1Blank"]
    assert b["zero"]["cost"] == 0
    assert b["offCost"] == 0


def test_the_fallback_reads_the_calculator_rate_then_the_stamp_and_a_saved_row_stays_as_it_was(page):
    b = page["ls1Blank"]
    assert b["calcBlank"] == 6000                                    # 3 x 5 x $50 x 8: calc rate wins
    assert b["stampedBlank"] == 3960                                 # 3 x 5 x $33 x 8
    assert b["unstampedBlank"] == 0, "a saved row with no stamp must not move"


# -- 4. no empty cards ----------------------------------------------------------------------------------
def test_a_saved_draft_with_five_empty_cards_opens_without_them_and_its_total_is_unchanged(page):
    e = page["ls1Empty"]
    assert e["ids"] == ["polishing", "travel"]
    assert e["total"] == e["totalWithout"] == 4950


# -- the proofs: each protection goes red when its line is put back ------------------------------------
MUTATIONS = {
    "a blank rate prices at $0 again": (
        "js/bid-model.js",
        "return num(row.guys) * num(row.days) * laborRateOf(row) * perDay;",
        "return num(row.guys) * num(row.days) * num(row.rate) * perDay;",
        lambda r: r["ls1Blank"]["whileEmpty"]["total"] == 0),
    "the empty cards open again": (
        "js/bid-model.js",
        "laborIn = dropEmptyLaborRows(laborIn);",
        "laborIn = laborIn;",
        lambda r: len(r["ls1Empty"]["ids"]) == 7),
    "no fallback when the library cannot answer": (
        "js/polish-estimate.js",
        "var laborRows = B.withCrewFallback(await laborDefaults);",
        "var laborRows = await laborDefaults;",
        lambda r: r["ls1Fallback"]["ids"] == ["travel"]),
    "the model's own crew rows win over the library's": (
        "js/polish-estimate.js",
        'M.labor = M.labor.filter(function (r) { return r && r.id === "travel"; });',
        "M.labor = M.labor;",
        lambda r: r["ls1Library"]["mockup"]["label"] == "Mock-up"),
    "a Labor-tab rate loses to the company rate": (
        "js/polish-estimate.js",
        "M.labor = B.keepLibraryRates(M.labor, libraryLaborRows, calcRows);",
        "M.labor = M.labor;",
        lambda r: r["ls1Library"]["polishing"]["rate"] == 40),
    "the box is not written back on change": (
        "js/polish-estimate.js",
        "rateRow.rate = back;",
        "rateRow.rate = rateRow.rate;",
        lambda r: r["ls1Blank"]["afterChange"]["rate"] == ""),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_each_protection_goes_red_without_its_line(tmp_path, name):
    rel, old, new, noticed = MUTATIONS[name]
    require_node()
    p = run_node(PAGE_HARNESS, mutated(tmp_path, rel, old, new), timeout=240)
    if p.returncode != 0:
        return          # an older scenario in the same harness crashed on the missing row: red, as wanted
    assert noticed(last_json_line(p.stdout)), "the harness did not notice: " + name
