"""Picking a county must move the workbook's actual remodel-tax number, not just JS state.

Kyle, via a screenshot: "It was brought to my attention that the remodel tax calculator is not
giving correct tax %. I'm not sure how that works but we use the link within the original excel
sheet to go to the website, enter the address, and get the tax % from there."

An earlier fix corrected the REFERENCE data (backend/reference_tax.py — see
test_reference_tax.py) and stopped there. This test file is for the deeper half of the same bug:
the county picker never actually reached the bid. `pickCounty` (frontend/js/estimate-review.js)
only ever set `state.county_remodel_rate` and told the estimator to hand-type the number into
K81/K75/K80 — plain text LABEL cells wired to nothing. The real formula cell that drives the
math — `Epoxy!B81` / `Polish!B75` / `<Gyp variant>!B80` — kept Kyle's own hardcoded
`=IF(D6="yes",0.1,0)` 10% placeholder forever, no matter what the picker said on screen.

The fix writes the corrected formula straight into `cellValues` (the same verbatim
`"<Sheet>!<Addr>"` dict that `/api/generate` already forwards untouched into
`estimate_writer.fill_estimate()`'s cell_values write step — see test_cell_lock.py's
`test_cell_values_write_into_locked_cell_still_lands` for that mechanism) and into the live HF
engine so the on-screen total updates immediately, matching the pattern the AI-autofill feature
already uses for its own cell writes.

Executed, not grepped: the original bug was invisible to source reading — the code that existed
was internally consistent, it just never reached the one cell that mattered. Only running
`pickCounty` for real and inspecting the resulting `cellValues`/HF writes can prove the fix
actually lands.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "remodel-rate-harness.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def result():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_covers_every_sheet_with_a_remodel_tax_line(result):
    """Epoxy + Polish + every Gyp variant = 7 cells. If a 6th Gyp variant is ever added to the
    workbook, this must be the number that moves, not a hand-typed count staying stale."""
    assert result["gypSheetCount"] == 5
    assert result["pickedCity"]["cellCount"] == 7


def test_picking_a_city_writes_the_real_rate_into_every_formula_cell(result):
    p = result["pickedCity"]
    assert p["epoxy"] == '=IF(D6="yes",0.0935,0)'
    assert p["polish"] == '=IF(D6="yes",0.0935,0)'
    for sheet, formula in p["gyp"].items():
        assert formula == '=IF(D8="yes",0.0935,0)', (sheet, formula)


def test_the_write_also_reaches_the_live_hf_engine(result):
    """So the on-screen total is right NOW, not just in the file the estimator downloads later."""
    p = result["pickedCity"]
    assert p["hfCallCount"] == 7
    assert p["hfMatchesCellValues"] is True


def test_the_active_sheets_grid_is_refreshed(result):
    """cellValues alone would be right in the generated file but stale on screen — the estimator
    would see the old total until they clicked away and back."""
    p = result["pickedCity"]
    assert p["activeSheetCacheBusted"] is True
    assert p["showSheetCalledWith"] == ["Epoxy"]


def test_state_still_carries_what_the_proposal_step_reads(result):
    """The {{county}} token and the on-screen state must keep working exactly as before — this
    fix adds a cellValues write, it does not replace the existing state bookkeeping."""
    p = result["pickedCity"]
    assert p["stateCounty"] == "Overland Park, KS"
    assert p["stateCountyTaxRate"] == 0.0935
    assert p["stateCountyRemodelRate"] == 0.0935
    assert p["persistedRemodelRate"] == 0.0935


def test_the_hint_no_longer_tells_the_estimator_to_hand_type_a_dead_cell(result):
    """The old copy said "(enter in K81)" — a legend cell wired to nothing. Following that
    instruction changed zero dollars on the bid; the new copy must not repeat that instruction."""
    pill = result["pickedCity"]["pillHtml"]
    assert "K81" not in pill
    assert "applied automatically" in pill
    assert "9.350%" in pill


def test_a_county_with_no_override_reverts_every_cell_to_kyles_own_placeholder(result):
    """A county-only pick (no `remodel_rate` override, e.g. the KS floor-rate rows) must not
    leave a stale rate from a previous city pick sitting in the formula."""
    p = result["pickedCountyNoOverride"]
    assert p["epoxy"] == '=IF(D6="yes",0.1,0)'
    assert p["polish"] == '=IF(D6="yes",0.1,0)'
    assert p["oneGyp"] == '=IF(D8="yes",0.1,0)'
    assert p["stateCountyRemodelRate"] is None


def test_clearing_the_pill_reverts_the_cell_and_the_state(result):
    c = result["cleared"]
    assert c["epoxy"] == '=IF(D6="yes",0.1,0)'
    assert c["stateHasCounty"] is False
    assert c["stateHasRemodelRate"] is False
    assert c["pillCleared"] is True


def test_a_draft_saved_before_this_fix_self_heals_on_reopen(result):
    """Before this fix shipped, a draft could have `state.county_remodel_rate` set with nothing
    in `cellValues` for these addresses at all — the exact shape a pre-fix save left behind. The
    page-load restore path must replay the override, not just redraw the pill."""
    s = result["staleDraftSelfHeals"]
    assert s["epoxy"] == '=IF(D6="yes",0.0935,0)'
    assert s["polish"] == '=IF(D6="yes",0.0935,0)'


def test_the_toggle_reference_is_local_to_each_sheet(result):
    """Epoxy/Polish read D6, every Gyp variant reads D8 — the same local, unqualified reference
    Kyle's own original placeholder formula used (Polish!D6 and each Gyp D8 are formula mirrors
    of Epoxy!D6, confirmed by direct inspection of the workbook), so no cross-sheet qualifier is
    needed or correct here."""
    t = result["toggleShape"]
    assert t["epoxy"].startswith('=IF(D6=')
    assert t["polish"].startswith('=IF(D6=')
    assert t["gyp"].startswith('=IF(D8=')
