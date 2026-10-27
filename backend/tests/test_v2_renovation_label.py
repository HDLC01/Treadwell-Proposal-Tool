"""THE RENOVATION LABEL: a job is said to be a renovation, and the Polish patch is charged the way Kyle's sheet charges it.

Hanz, 2026-10-21: "So we have a solution for the renovation 0.10 cents per sf difference. Will said that it should just be an item but I
suggest there must be a label that we could just identify if its a renovation job to fix the lump sum difference we had for polish."

WHAT WAS WRONG. Kyle's Polish tab prices the patch at C17 = IF(B10="New",0.05,0.15). On the recorded Jayhawk Polish job (tests/fixtures/
recorded_job_2026_10.json) B10 was blank, so the sheet charged the renovation rate and came to $32,864. The v2 estimate had no way to say
"renovation" (the intake's toggle came off on 2026-09-23), so it charged the new-concrete rate and came to $31,840: $407 of patch, $1,024
after the markups and the taxes.

WHAT IT IS NOW (Hanz's picks, 2026-10-21: the label on the estimate with a tag, an unlabelled job is new concrete):
  * A "Renovation" switch on the Material step of a Polish sheet and of a Seal option, the two whose patch line it prices. An Epoxy sheet
    has none: its patch is one rate.
  * The answer is Kyle's own New or Reno cells on the draft (Polish!B10, Epoxy!B10, Seal!B10), the cells the live intake and the AI
    autofill already write and the save already carries to the downloaded workbook. It is not put on the model, so a bid nobody labels
    prices exactly as before.
  * The open sheet's bar says "Renovation" on every step. The patch itself stays the itemised line on the Review step (quantity, rate and
    total), which is Will's "it should just be an item".

Everything runs code: tests/js/renovation-label-harness.js boots the real js/polish-estimate.js on the library the seed plans, the way
test_recorded_job_parity.py prices the same job through the engines, and reads every fact off the page after it ran. The last test breaks
a scratch copy of the code and requires each fact to notice.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "renovation-label-harness.js"
JOB = TESTS / "fixtures" / "recorded_job_2026_10.json"
RECORDED = json.loads(JOB.read_text(encoding="utf-8"))
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]
SECTIONS = ["jayhawk", "arrived", "sheets"]
RENO = {"Epoxy!B10": "Reno", "Polish!B10": "Reno", "Seal!B10": "Reno"}
NEW = {"Epoxy!B10": "New", "Polish!B10": "New", "Seal!B10": "New"}


def _run(frontend, tmp_path):
    require_node()
    plan = plan_json(tmp_path)
    proc = run_node(HARNESS, frontend, plan, JOB)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    return _run(FRONTEND, tmp_path_factory.mktemp("reno"))


@pytest.mark.parametrize("section", SECTIONS)
def test_no_section_of_the_harness_failed(ran, section):
    assert "error" not in ran[section], ran[section].get("error")


def test_the_jayhawk_polish_job_comes_to_kyles_figure_once_it_is_labelled_a_renovation(ran):
    """The finding, on the real page: unlabelled it is the $31,840 the email to Will quoted; labelled it is the sheet's own $32,864."""
    j = ran["jayhawk"]
    assert j["recorded"] == RECORDED["polish"]["sheet"]["total"] == 32864
    assert j["off"]["total"] == 31840, "unlabelled, the job is new concrete, as v2 always priced it"
    assert j["on"]["total"] == j["recorded"], "labelled a renovation, the job is what Kyle's sheet priced it at"


def test_the_label_is_kyles_new_or_reno_cells_and_survives_a_reload(ran):
    j = ran["jayhawk"]
    # Every cell of the condition: the switch writes all three, and the save's conditionCellWrites would carry one to the rest anyway.
    assert j["savedCells"] == RENO, "the label is saved in Kyle's New or Reno cells"
    assert j["reopened"] == {"total": j["recorded"], "card": True, "on": True, "tag": True, "cells": RENO}
    assert j["back"]["total"] == 31840 and j["backCells"] == NEW, "switched back, it is new concrete again, said in the same cells"


def test_the_switch_is_a_switch_space_presses_it_and_the_caret_stays_on_it(ran):
    j = ran["jayhawk"]
    assert j["off"]["card"] is True and j["off"]["on"] is False and j["on"]["on"] is True
    assert j["back"]["prevented"] is True and j["back"]["on"] is False, "Space presses it, as every switch on the page"
    assert j["on"]["refocused"] == ["[data-reno-sw]"], "the panel is rebuilt under it, and the caret goes back to it"


def test_the_job_says_renovation_on_every_step_and_every_sheet(ran):
    j, s = ran["jayhawk"], ran["sheets"]
    assert j["off"]["tag"] is False and j["on"]["tag"] is True and j["back"]["tag"] is False
    assert s["sealOn"]["tag"] is True and s["epoxy"]["tag"] is True, "on the bar of whichever sheet is open"
    assert s["labor"]["tag"] is True and s["review"]["tag"] is True, "on the Labor and Review steps too"
    assert s["review"]["renoRate"] is True and s["review"]["newRate"] is False, "the Review's patch line says which rate it charged"


def test_a_draft_that_arrives_labelled_opens_labelled_and_an_unlabelled_one_as_new_concrete(ran):
    """The live intake and the AI autofill write the cells; the first cell holding an answer decides, as conditionCellWrites carries it."""
    a = ran["arrived"]
    for name in ("reno", "renoOnEpoxyOnly"):
        assert a[name]["total"] == 32864 and a[name]["on"] is True and a[name]["tag"] is True, name
    for name in ("fresh", "none"):
        assert a[name]["total"] == 31840 and a[name]["on"] is False and a[name]["tag"] is False, name
    assert a["none"]["savedCells"] == {}, "opening a bid writes nothing"


def test_a_seal_option_prices_its_patch_by_the_label_and_shows_the_switch_and_an_epoxy_sheet_has_none(ran):
    s = ran["sheets"]
    assert s["sealTab"] == "Seal" and s["sealOff"]["card"] is True and s["sealOn"]["card"] is True
    assert s["sealOn"]["total"] > s["sealOff"]["total"] > 0, "the Seal option's own patch moves to the renovation rate"
    assert s["epoxy"]["card"] is False, "an Epoxy sheet's patch is one rate: it has no switch"


BREAKS = {
    "the switch writes nothing to the draft": (
        "js/polish-estimate.js", "    TW.setState({ cell_values: cells });", "    void cells;",
        lambda r: r["jayhawk"]["savedCells"] != RENO or r["jayhawk"]["reopened"]["total"] != 32864),
    "the page's copy of the draft is not told": (
        "js/polish-estimate.js",
        "    state = Object.assign({}, state, { cell_values: Object.assign({}, state && state.cell_values || {}, mine) });",
        "    void mine;",
        lambda r: r["jayhawk"]["on"]["total"] != 32864),
    "the click is not heard": (
        "js/polish-estimate.js", "    if (renoSw) { setReno(!jobIsReno()); return; }", "    if (false) { setReno(!jobIsReno()); return; }",
        lambda r: r["jayhawk"]["on"]["total"] != 32864),
    "Space does not press it": (
        "js/polish-estimate.js", '      t.closest("[data-cond]") || t.closest("[data-reno-sw]");',
        '      t.closest("[data-cond]");',
        lambda r: r["jayhawk"]["back"]["total"] != 31840 or r["jayhawk"]["back"]["prevented"] is not True),
    "the caret is not put back": (
        "js/polish-estimate.js", '    refocus("[data-reno-sw]");', "    void 0;",
        lambda r: r["jayhawk"]["on"]["refocused"] != ["[data-reno-sw]"]),
    "the card is not drawn": (
        "js/polish-estimate.js", '    if (floorRole === "polish" || floorRole === "seal") html += renoCard();', "    if (false) html += renoCard();",
        lambda r: r["jayhawk"]["off"]["card"] is not True),
    "a Seal option has no switch": (
        "js/polish-estimate.js", '    if (floorRole === "polish" || floorRole === "seal") html += renoCard();',
        '    if (floorRole === "polish") html += renoCard();',
        lambda r: r["sheets"]["sealOff"]["card"] is not True),
    "an Epoxy sheet shows the switch": (
        "js/polish-estimate.js", '    if (floorRole === "polish" || floorRole === "seal") html += renoCard();', "    html += renoCard();",
        lambda r: r["sheets"]["epoxy"]["card"] is not False),
    "the sheet bar is not told": (
        "js/polish-estimate.js", "      reno: jobIsReno()", "      reno: false",
        lambda r: r["jayhawk"]["on"]["tag"] is not True),
    "the bar draws no tag": (
        "js/bid-model.js",
        "      if (v.reno === true) s += '<span class=\"pill reno\" title=\"A renovation: the patch is charged at the renovation rate\">Renovation</span>';",
        "      if (false) s += '';",
        lambda r: r["jayhawk"]["on"]["tag"] is not True or r["sheets"]["labor"]["tag"] is not True),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend, plan_json(tmp_path), JOB)
    # A BREAK IS NOTICED BY A FACT THAT CHANGED, never by a crash: a section that throws has no facts to compare.
    assert proc.returncode == 0, "the break stopped the page outright, so no fact noticed it: " + name
    got = last_json_line(proc.stdout)
    crashed = sorted(k for k, v in got.items() if isinstance(v, dict) and "error" in v)
    assert not crashed, "the break crashed %s instead of changing a fact: %s" % (", ".join(crashed), name)
    assert noticed(got), "the checks did not notice: " + name
