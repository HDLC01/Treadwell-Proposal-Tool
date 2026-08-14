"""The Trailing-12 tab and the Excel download, executed out of the real analytics.js.

Hanz, 2026-08-14: "IS there a way to show this in another tab like a new tab beside Companies" —
and the tab has to answer the whole company's question, not the filtered view's, because the whole
point is comparing the same number week to week.

EXECUTED, NOT GREPPED. Two of the guarantees here are about what the code DOESN'T do:
  - the tab reads ROWS rather than filtered(). That is one variable name, and the file has four
    legitimate uses of filtered(), so a grep proves nothing; feeding it filters that exclude every
    row and checking the numbers don't move does.
  - the file download carries the bearer. /api/file/* is gated like every other route, so a missing
    header 401s in PRODUCTION ONLY — the suite bypasses auth, and no server-side test can see it.
The figures come from the real analytics-core.js, so nothing here can pass against a stub that
disagrees with the engine.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "trailing12-ui-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the tab ──────────────────────────────────────────────────────────────────
@needs_node
def test_the_tab_says_the_filters_do_not_apply_to_it(ran):
    """Leaving the date range and chips sitting above numbers they don't affect would be a lie told
    by omission. One sentence, rather than disabled controls that still look clickable."""
    bar = ran["tab"]["filterbar"]
    assert "whole company" in bar and "don’t apply here" in bar
    # The harness seeds both regions with another tab's leftovers first, so these two assertions
    # can actually fail. Checking a region that started empty proves nothing about clearing it.
    assert ran["tab"]["staleBarReplaced"], "the previous tab's filter bar is still on screen"
    assert ran["tab"]["activeFiltersCleared"], "stale filter chips left above the trailing numbers"


@needs_node
def test_the_numbers_ignore_the_filters_entirely(ran):
    """THE ORG-WIDE GUARANTEE. Rendered once with no filters and once with filters that match
    nothing — an estimator who doesn't exist, a trade that doesn't exist, a date range in 2099. If
    the tab ever reads filtered() instead of ROWS, these two renders stop being identical."""
    assert ran["orgWide"]["identical"], "the trailing numbers moved when filters were applied"
    assert ran["orgWide"]["sample"], "the fixture's won amount is missing — the table rendered empty"


@needs_node
def test_it_warns_when_the_pull_window_hides_part_of_the_span(ran):
    """The org pull window drops rows server-side before the browser sees them, so a window that
    starts inside the 15 months makes every figure quietly too low. Silence there would be the
    worst outcome: a wrong number that looks like a right one."""
    w = ran["warnings"]
    assert w["lateFrom"], "a pull window starting inside the 15 months went unmentioned"
    assert w["earlyTo"], "a pull window ending before today went unmentioned"
    assert w["openWindowSilent"], "an open window cried wolf"


@needs_node
def test_it_warns_when_the_dataset_was_capped(ran):
    """Over the cap, the bids dropped are chosen by BasisBoard's paging order, not by date — so a
    trailing window can lose rows with nothing to show it happened."""
    assert ran["warnings"]["cappedWarns"]


# ── the export payload ───────────────────────────────────────────────────────
@needs_node
def test_the_payload_carries_every_tab(ran):
    assert ran["payload"]["tabNames"] == ["Overview", "Trades", "Estimators", "Companies"]


@needs_node
def test_the_trailing_block_is_kyles_four_columns(ran):
    assert ran["payload"]["t12Labels"] == ["All Bids", "Gyp", "Epoxy", "Polish"]


@needs_node
def test_the_trailing_block_ships_raw_sums_and_no_ratios(ran):
    """Every derived cell in Kyle's sheet is a live formula. Sending our percentages too would put
    two answers in one workbook, and they would part company the first time he edited a number."""
    assert ran["payload"]["carriesNoRatios"], "a computed ratio leaked into the export payload"
    assert ran["payload"]["t12AllBids"] == {
        "label": "All Bids", "won_amount": 150000, "submitted_amount": 580000,
        "sub90_amount": 400000, "n_awarded": 2, "n_submitted": 3, "n_sub90": 1}


@needs_node
def test_the_file_records_which_filters_produced_it(ran):
    """"based on the filters that are on" — so the file has to say which ones, or a saved workbook
    is a number with no question attached."""
    assert "Dates: All time" in ran["payload"]["filters"]
    assert "3 of 3 projects" in ran["payload"]["filters"]
    assert ran["payload"]["generatedAt"] == "2026-08-15T00:00:00Z"


@needs_node
def test_a_filtered_export_names_the_slice_but_not_in_the_trailing_sheet(ran):
    """The dashboard sheets follow the filters; the trailing sheet stays org-wide. Both facts in one
    file, which is why the header sentence matters."""
    f = ran["filteredPayload"]
    assert "Trades: Epoxy" in f["filters"] and "1 of 3 projects" in f["filters"]
    assert f["t12Unchanged"] == 150000, "the trailing sheet followed the filters"


@needs_node
def test_typed_cells_travel_rather_than_formatted_strings(ran):
    """A number formatted in the browser arrives as text and Excel cannot sum it."""
    label, cell = ran["payload"]["firstOverviewRow"]
    assert label == "Won amount"
    assert cell == {"v": 150000, "t": "money"}


# ── the download ─────────────────────────────────────────────────────────────
@needs_node
def test_a_render_reveals_the_export_button(ran):
    """It ships hidden in the static markup — static so that #filterbar's constant re-rendering
    (including the 4-second build poll) cannot resurrect it enabled mid-download. Which leaves one
    thing to remember, and the first version of this feature forgot it: the markup was there, the
    handler was there, and nothing ever set hidden=false. It reached staging complete and
    unreachable, and no test noticed because none of them looked at `hidden`."""
    b = ran["exportButton"]
    assert b["hiddenBeforeRender"] is True, "the button no longer ships hidden"
    assert b["hiddenAfterRender"] is False, "revealExport does not reveal the export button"
    assert b["noteRevealed"], "the button appeared without the sentence explaining what it exports"
    # Calling the lifted function proves it works, not that anything calls it — the two mutations
    # "delete the call from render()" and "reveal only the button" both survived until these.
    assert b["calledByRender"], "render() never calls revealExport, so the button stays hidden"
    assert b["calledBeforeTheEarlyReturn"], (
        "revealExport is called after the trailing-12 early return, so that tab has no button")



@needs_node
def test_the_download_asks_the_server_to_build_then_fetches_the_file(ran):
    d = ran["download"]
    assert d["posted"] == ["POST /api/analytics/export"]
    assert d["fileUrl"].endswith("/api/file/tok123")


@needs_node
def test_the_file_fetch_carries_the_bearer(ran):
    """/api/file/* is bearer-gated, and this is the one assertion that can catch a missing header:
    the test suite bypasses auth, so without it the omission surfaces only on production."""
    assert ran["download"]["fileCarriedAuth"], "the workbook download went out unauthenticated"


@needs_node
def test_the_button_says_it_is_working_and_comes_back(ran):
    d = ran["download"]
    assert d["disabledDuring"] and d["labelDuring"] == "Building…"
    assert d["restored"], "the button stayed disabled after the download finished"


@needs_node
def test_a_failure_is_reported_and_the_button_is_returned(ran):
    """A dead end with a spinner is worse than an error: the estimator cannot tell whether to wait."""
    f = ran["failure"]
    assert f["alerted"] and f["restored"] and f["noDownload"]


@needs_node
def test_it_refuses_while_the_dataset_is_still_building(ran):
    """The page polls for up to five minutes on a cold build. Exporting mid-build would write a
    workbook of zeros and look like a finished answer."""
    assert ran["refusesWhileBuilding"]["requests"] == 0
