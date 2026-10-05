"""The Labor Calculator tab, and the Travel section it opens with (Kyle's notes, B7, 2026-10-05).

Hanz: "create another tab right beside Labor in Items & Assemblies ... where we would have the
calculations for the default containers in the Labor tab in the estimate sheet ... name it Labor
Calculator", and Travel goes in it. Today it holds Travel Labor, Lodging and Per Diem; the rest of
the calculator is a queued follow-up (B7b).

THE LODGING AND PER DIEM RATES ARE NOT STORED HERE. They are the Markup page's Global lines, and the
boxes on this tab are a second door onto the same rows -- so the behaviour is EXECUTED, not read:
labor-calculator-harness.js runs the shipped block out of library.js against a fake DOM and fetch.
(The Defaults tab's own "Markup" inputs carry a data-markup-formula attribute and NO save handler
anywhere in js/, which is the failure a source assertion cannot see.)
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "labor-calculator-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def html():
    return (FRONTEND / "library.html").read_text(encoding="utf-8", errors="replace")


def test_the_tab_sits_right_after_labor_and_before_administration(html):
    """Mutation: move the button after tab-vendors, or drop the pane's `hidden` -- it would open
    showing on top of whichever tab was selected."""
    labor = html.index('id="tab-labor"')
    calc = html.index('id="tab-labcalc"')
    vendors = html.index('id="tab-vendors"')
    assert labor < calc < vendors, "the Labor Calculator tab is not right beside Labor"
    assert re.search(r'id="tab-labcalc"[^>]*aria-controls="pane-labcalc"', html)
    assert re.search(r'<section id="pane-labcalc"[^>]*\shidden', html), "the pane starts visible"
    assert ">Labor Calculator<" in html


def test_the_defaults_tab_points_at_the_calculator_for_travel(html):
    """One line on the Defaults tab: Travel is set in Labor Calculator, with a link that goes there.

    Mutation: delete the data-goto-labcalc anchor -- the pointer becomes plain text."""
    pane = html.split('id="pane-defaults"')[1].split("</section>")[0]
    assert "Travel is set in" in pane and "data-goto-labcalc" in pane


def test_the_new_tab_is_wired_into_the_view_switch():
    """A tab button with no entry in PANES switches nothing, and one with no TAB_OF entry throws on
    the first showView. Both lists carry it, in the page's own order.

    Mutation: drop "labcalc" from PANES in library.js."""
    js = (FRONTEND / "js" / "library.js").read_text(encoding="utf-8", errors="replace")
    assert re.search(r'var PANES = \["items", "asm", "labor", "labcalc", "vendors", "defaults"\];', js)
    assert 'labcalc: "tab-labcalc"' in js
    assert 'if (p === "labcalc") renderLabCalc();' in js, "opening the tab paints nothing"
    assert re.search(r'\$\("pane-labcalc"\)\.addEventListener\("change"', js), (
        "the rate boxes have no save handler")


@needs_node
def test_the_admin_sees_the_stored_rates_and_the_travel_labor_rate_and_the_rule(ran):
    a = ran["admin"]
    assert a["loadingFirst"].startswith('<p class="paneintro">Loading'), (
        "the tab painted before its figures arrived")
    assert a["readOnce"] == 1, "opening the tab made %r reads of the markup rules" % a["readOnce"]
    assert a["lodgingBox"], "the filed $80 lodging figure is not in its box"
    assert a["perDiemBoxEmptyWithShippedPlaceholder"], (
        "an unfiled per diem must show an empty box with Kyle's $45 as the placeholder")
    assert a["travelLaborRow"], "Travel Labor does not show the Labor tab's own rate"
    assert a["seventyMiles"], "the 70-mile rule is not stated on the tab"
    assert a["insideMarkups"], "the tab does not say Lodging and Per Diem price inside the markups"
    assert a["roHidden"] is True


@needs_node
def test_saving_a_rate_files_the_whole_global_row_and_keeps_its_note(ran):
    """A PUT states the whole markup row, so the filed note must ride along or a save from here
    silently clears one written on the Markup page. It files on the GLOBAL layout by line key, a
    `$` typed in front is accepted, and the Defaults tab's copy of the row is kept honest.

    Mutation: drop `notes: rule.notes || ""` from saveTravelRate -- the note comes back empty."""
    s = ran["saved"]
    assert s["puts"][0] == {"layout": "global", "line_key": "travel_per_diem", "applies": True,
                            "notes": "", "formula": "55"}
    assert s["puts"][1] == {"layout": "global", "line_key": "travel_lodging", "applies": True,
                            "notes": "kept note", "formula": "90"}, (
        "the lodging save did not carry the filed note: %r" % s["puts"][1])
    assert "Lodging saved: $90 per night" in s["alert"]
    assert s["cached"] == "55"
    assert s["defaultsTabCopy"] == [["travel_lodging", "90"]]


@needs_node
def test_a_blank_the_same_value_or_a_non_number_sends_nothing(ran):
    """Mutation: drop the `<= 0` / regex guard -- "7e1" or "-5" is filed as a rate."""
    assert ran["noops"]["sent"] == 0
    assert "shipped $45 stands" in ran["noops"]["alert"], ran["noops"]["alert"]
    for r in ran["refused"]:
        assert r["sent"] == 0, "%r was sent to the server" % r["v"]
        assert r["back"] == "90", "%r left the box holding the refused value" % r["v"]
        assert "dollar figure above zero" in r["alert"], r


@needs_node
def test_a_refused_save_puts_the_old_figure_back_and_says_why(ran):
    r = ran["refusedByServer"]
    assert r["back403"] == "80" and "admin-only" in r["alert403"]
    assert r["back400"] == "80" and r["alert400"] == "the server said no"
    assert r["cacheKept"] == "80", "the cached figure moved on a refused save"


@needs_node
def test_a_non_admin_reads_the_figures_but_gets_no_boxes(ran):
    n = ran["nonAdmin"]
    assert n["boxes"] == 0, "a non-admin was handed a box that can only 403"
    assert n["showsLodging"] and n["showsShippedPerDiem"] and n["roShown"]


@needs_node
def test_the_markup_read_failing_is_said_out_loud_and_invents_no_rate(ran):
    assert ran["readFails"]["said"] and ran["readFails"]["boxesEmpty"]
    assert ran["figure"] == ["70", "70.5", "", "", ""], (
        "a switched-off, non-numeric or absent rule must read as not filed: %r" % ran["figure"])
