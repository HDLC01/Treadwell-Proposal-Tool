"""The Estimate page's bottom Total bar shows the bid the proposal is built from.

Hanz, 2026-09-25, on staging: the base bid was a COPIED tab, "Epoxy copy", at $14,224. Its own
Total Base Bid cell said $14,224, and the proposal, the board card and the downloaded file all used
$14,224, while the sticky bar at the bottom of the Estimate page read the ORIGINAL Epoxy tab's
$7,447. `updateTotalBarFromHF` always summed Epoxy and/or Polish; the pricing snapshot that sets
proposal_lump_sum has followed the designated base tab (`state.base_tab_id`) for a long time.

RUN, not read: tests/js/total-bar-harness.js lifts the shipped function and its helpers.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "total-bar-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_a_copied_tab_as_the_base_bid_drives_the_bar(ran):
    """Mutation: remove the designated-base branch. The bar goes back to the Epoxy tab's $7,447."""
    b = ran["copyIsBase"]
    assert b["tb-total"] == "$14,224.00", b
    assert b["tb-material"] == "$2,100.00" and b["tb-psf"] == "$17.78", b


def test_an_inverted_base_drives_the_bar(ran):
    assert ran["polishIsBase"]["tb-total"] == "$13,585.00", ran["polishIsBase"]


def test_picking_a_base_bid_repaints_the_bar_at_once(ran):
    """Hanz's second report: base put back to Epoxy $7,696 and the bar still read the copy's
    $15,149, because the base-bid radio's handler never repainted it. Driven through the real
    wireBidBar change listener.

    Mutation: drop the updateTotalBarFromHF call from the radio branch. `after` stays `before`."""
    back = ran["radioBackToEpoxy"]
    assert back["base"] == "Epoxy"
    assert back["before"] == "$14,224.00" and back["after"] == "$7,447.00", back
    to = ran["radioToCopy"]
    assert to["before"] == "$7,447.00" and to["after"] == "$14,224.00", to


def test_with_no_designated_base_the_bar_is_unchanged(ran):
    assert ran["noBase"]["tb-total"] == "$7,447.00", ran["noBase"]
    assert ran["comboNoBase"]["tb-total"] == "$21,032.00", ran["comboNoBase"]
