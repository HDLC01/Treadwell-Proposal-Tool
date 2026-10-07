"""Kyle's on/off slider (2026-10-05), proved by EXECUTING the code.

Hanz's rule: a default has a slider. On the Defaults tab it is the row's STARTING state in a new bid;
on the estimate, every labor row, takeoff row and condition card carries the same slider. A row
switched OFF is shown grayed, adds $0, drops out of the totals BEFORE they are rounded, drops out of
Travel's man-days, and is left out of the Review list.

Three harnesses run the real files:
  * js/row-slider-core-harness.js    -- bid-model.js's arithmetic, against "the bid of a model
                                        that never had the row" (the only honest oracle).
  * js/polish-estimate-harness.js    -- the whole estimate page, its click and keydown handlers.
  * js/library-ui-harness.js         -- the Defaults tab: what is drawn, what a press writes, and the
                                        put-back when the server refuses.
Backend: library.py reads an absent column as ON and writes default_on ONLY when the request carries
it, so a database without backend/ops/default_on.sql is never written a column it lacks.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import library

HERE = pathlib.Path(__file__).resolve().parent
FRONTEND = HERE.parents[1] / "frontend"
JS = HERE / "js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _run(harness):
    proc = subprocess.run(["node", str(JS / harness), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def core():
    return _run("row-slider-core-harness.js")


@pytest.fixture(scope="module")
def page():
    return _run("polish-estimate-harness.js")["rowSlider"]


@pytest.fixture(scope="module")
def defaults():
    return _run("library-ui-harness.js")["defaultSlider"]


# ── the arithmetic ────────────────────────────────────────────────────────────
def test_an_off_row_costs_nothing_and_absent_or_true_means_on(core):
    assert core["costOff"] == 0
    assert core["costAbsentIsOn"] == core["costTrueIsOn"] == 3960
    assert core["rowOn"] == [True, True, False, True]


def test_the_whole_bid_equals_the_bid_of_a_model_that_never_had_the_row(core):
    # Skipped in the raw sum, so the chain's own ROUNDUP sees only what the bid buys.
    assert core["chainOff"] == core["chainGone"]
    assert core["chainWith"] == core["chainWithout0"]
    # ...and the vacuity guard: switching a row off really moved the bid.
    assert core["chainOff"]["total"] != core["chainOnAllRows"]["total"]


def test_zeroing_after_rounding_would_have_been_a_different_number(core):
    # Why the skip lives in laborCost: round(sum) - row is NOT round(sum - row) for this fixture.
    assert core["roundedAfterWouldBe"] != core["roundedBefore"]
    assert core["chainOff"]["labor"] == core["roundedBefore"]


def test_an_off_takeoff_row_leaves_the_area(core):
    assert core["areaOff"] == core["areaGone"] == 1000


def test_an_off_crew_row_drops_out_of_travels_man_days(core):
    assert core["manDays"] == 16.5
    assert core["manDaysOff"] == core["manDaysGone"] == 1.5


def test_an_off_row_never_blocks_review(core):
    assert core["blockedOn"], "the fixture's half-filled row must block when it is ON"
    assert core["blockedOff"] == []
    assert any("takeoff" in b.lower() for b in core["blockedTakeoffOff"]), (
        "every takeoff row off means nothing is being priced")


def test_a_default_saved_off_seeds_the_row_off_and_nothing_else_changes(core):
    assert core["seedTravelOff"] is False
    assert core["seedL1Off"] is False
    assert core["seedL2HasKey"] is False and core["seedL3HasKey"] is False


def test_the_shared_slider_markup_is_one_escaped_switch(core):
    s = core["slider"]
    assert s.startswith('<span class="mw-sw on" data-x="1" role="switch" tabindex="0" '
                        'aria-checked="true"')
    assert "Hi &lt;b&gt;" in s and 'title="T&quot;t"' in s
    assert 'aria-checked="false"' in core["sliderOff"] and " on" not in core["sliderOff"][:20]


# ── the estimate page, through its own handlers ───────────────────────────────
def test_a_takeoff_row_switched_off_is_grayed_costs_zero_and_the_bid_matches_a_model_without_it(page):
    a = page["afterTkOff"]
    assert a["enabled"] is False and a["switchOn"] == "false"
    assert a["costBox"] == "$0" and page["costBoxBefore"] != "$0"
    assert "inert" in a["cardClass"]
    for k in ("material", "total", "area"):
        assert a[k] == page["expectTkOff"][k], k
    assert a["total"] != page["total0"], "vacuity guard: the row was in the bid before"


def test_switching_it_back_on_restores_the_exact_bid_and_leaves_no_key_behind(page):
    assert page["tkBack"] == {"hasEnabledKey": False, "total": page["total0"],
                              "material": page["mat0"]}
    assert page["labBack"] == {"hasEnabledKey": False, "total": page["lab0"]}


def test_a_labor_row_switched_off_is_grayed_costs_zero_and_the_bid_matches(page):
    a = page["labOff"]
    assert a["enabled"] is False and a["cost"] == "$0"
    assert "inert" in a["cardClass"] and "off" in a["cardClass"].split()
    assert a["total"] == page["expectLabOff"]["total"] != page["lab0"]


def test_review_leaves_the_off_rows_out_and_keeps_the_others(page):
    assert not page["reviewHasOffTakeoff"] and page["reviewHasOnTakeoff"]
    assert not page["reviewHasOffLabor"] and page["reviewHasOnLabor"]


def test_an_off_crew_row_drops_out_of_the_travel_row_on_screen(page):
    assert page["guysBefore"] == 16.5 and page["guysAfter"] == 1.5


def test_space_flips_the_slider_and_other_keys_do_not(page):
    assert page["kbOff"] is False and page["kbPrevented"] is True
    assert page["kbOtherKey"] is False, "a second, unrelated key must not have flipped it back"


def test_the_condition_cards_and_the_row_sliders_are_one_component(page):
    assert page["condSwitchRole"] == "switch" and page["condSwitchClass"].startswith("mw-sw")
    assert page["offSwitchSameShape"] is True


# ── the Defaults tab ──────────────────────────────────────────────────────────
def test_defaults_draw_absent_as_on_and_false_as_off_on_every_kind(defaults):
    d = defaults["drawn"]
    assert d["asmAbsentIsOn"] == "true" and d["asmFalseIsOff"] == "false"
    assert d["itemAbsentIsOn"] == "true"
    assert d["travelOn"] == "true" and d["laborOff"] == "false"
    assert d["dyeOff"] == "false"


def test_pressing_a_default_slider_writes_default_on_not_favorite(defaults):
    assert defaults["afterAsm"] == "false"
    assert json.loads(defaults["asmCalls"]) == [
        {"op": "PATCH_DEFAULT_ON", "kind": "assemblies", "id": "a1", "on": False}]
    assert defaults["afterLabor"] == "true"


def test_a_refused_save_puts_the_slider_back(defaults):
    assert defaults["afterRefused"] == "true"
    assert defaults["dyeRefused"] == "false"


def test_a_condition_materials_slider_is_the_condition_default(defaults):
    assert json.loads(defaults["condCalls"]) == [{"key": "dye", "on": True}]
    assert defaults["dyeAfter"] == "true" and defaults["noItemWrite"] is True


def test_a_non_admin_reads_labor_and_condition_state_as_words(defaults):
    v = defaults["viewer"]
    assert v["noLaborSwitches"] and v["noConditionSwitch"]
    assert v["laborSaysOff"] and v["dyeSaysOff"]
    assert v["asmStillSwitch"], "items and assemblies match their Remove button: not admin-gated"


def test_the_tab_is_titled_with_labor():
    html = (FRONTEND / "library.html").read_text(encoding="utf-8")
    assert "Default Items, Assemblies &amp; Labor</button>" in html
    assert html.count('<th class="w-on">Starts</th>') == 2, "both Defaults tables get the column"


# ── the backend ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("validate,base", [
    (library.validate_item, {"name": "X", "unit": "Gallon"}),
    (library.validate_assembly, {"name": "X", "unit": "SF", "lines": []}),
    (library.validate_labor, {"name": "X", "unit": "days", "rate": 33}),
])
def test_default_on_is_written_only_when_the_request_carries_it(validate, base):
    assert "default_on" not in validate(dict(base))
    assert "default_on" not in validate({"favorite": True}, partial=True)
    assert validate({"default_on": False}, partial=True)["default_on"] is False
    assert validate({"default_on": True}, partial=True)["default_on"] is True


@pytest.mark.parametrize("shape", [library._shape_item, library._shape_assembly,
                                   library._shape_labor])
def test_an_absent_or_null_column_reads_on_only_an_explicit_false_reads_off(shape):
    assert shape({"id": "1"})["default_on"] is True
    assert shape({"id": "1", "default_on": None})["default_on"] is True
    assert shape({"id": "1", "default_on": True})["default_on"] is True
    assert shape({"id": "1", "default_on": False})["default_on"] is False


def test_the_ddl_is_idempotent_covers_all_three_tables_and_reloads_the_schema_cache():
    sql = (HERE.parent / "ops" / "default_on.sql").read_text(encoding="utf-8")
    for t in ("library_items", "library_assemblies", "library_labor"):
        assert re.search(r"alter table public\.%s\s+add column if not exists default_on boolean;" % t,
                         sql), t
    assert sql.strip().endswith("notify pgrst, 'reload schema';")
    for schema in (HERE.parent / "supabase_schema.sql", HERE.parent / "staging" / "schema_pg.sql"):
        text = schema.read_text(encoding="utf-8")
        assert text.count("add column if not exists default_on boolean") == 3, schema.name
