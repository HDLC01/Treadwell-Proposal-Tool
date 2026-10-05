"""The Proposal step's sheet is zoomed to the space it really has, on the first paint and after.

Audit, 2026-10-02 (staging, Direct epoxy "Release check 9-26"): on most fresh loads at laptop widths
the sheet came up too big -- scale(1.577) where scale(1.283) fits at innerWidth 1600 -- so its left
~108px sat behind the sidebar and its right edge ran under the floating Pricing options panel. A 1px
window resize put it right. On the bad loads the sheet measured the canvas's clientWidth minus 56
instead of minus 296: 240px too wide, which is the nav rail auth.js puts on <body> as a margin.

applyZoom read the canvas once per call and only the WINDOW's resize event called it again. The
space the sheet may take changes without one: auth.js ANIMATES <body>'s margin-left from 0 to the
rail's 240px when it draws the sidebar (`body{transition:margin-left .2s ease}`), so a first fit
inside those 200ms measured a canvas up to 240px too wide -- exactly the audited error; the 272px
reservation is padding a :has() rule adds when #options-panel is shown; and below 1400px the panel
moves inline. The fix observes the canvas's own box and fits again when it changes.

RUN, NOT READ. `js/doc-zoom-harness.js` lifts the shipped functions and runs them over a canvas whose
width follows the body margin, whose padding follows the rail and whose scrollbar follows how tall the
zoomed sheet is, with a ResizeObserver that reports the way a browser does. What it cannot show is a
real browser's paint; the first fresh load at 1440 and 1600 wide still wants a look on staging.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "doc-zoom-harness.js"
JS = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _run(frontend=FRONTEND):
    proc = subprocess.run(["node", str(HARNESS), str(frontend)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed; read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran():
    return _run()


def test_the_audited_load_is_fitted_again_when_the_sidebar_arrives(ran):
    """The first fit sees the canvas the full window wide -- the audited scale(1.577) at 1600 --
    and the sidebar's 240px margin then arrives with no window resize. The sheet has to come back
    to the audited good zoom on its own."""
    got = ran["navArrivesLate"]
    assert got["firstFit"]["k"] == pytest.approx(1.577, abs=0.001), (
        "the harness no longer reproduces the audited bad fit; re-derive the scenario")
    assert got["afterRail"]["k"] == pytest.approx(1.283, abs=0.001)
    assert got["afterRail"]["fits"] and got["afterRail"]["overhangEachSidePx"] == 0, got
    assert got["afterRail"]["outerMatches"], "the scroll reservation was not re-sized with the zoom"
    assert ran["navArrivesLate1440"]["k"] == pytest.approx(1.087, abs=0.001)
    assert ran["navArrivesLate1440"]["fits"]


def test_every_frame_of_the_rails_slide_in_refits_and_the_last_one_is_right(ran):
    """The cause, frame by frame: the sidebar's margin animates in after the first fit. Each frame
    that narrows the canvas fits again, once, and the frame it ends on gives the audited good zoom."""
    got = ran["navTransition"]
    assert got["firstFit"]["k"] == pytest.approx(1.577, abs=0.001)
    assert got["end"]["k"] == pytest.approx(1.283, abs=0.001) and got["end"]["fits"], got
    assert got["writes"] <= got["frames"] + 1, got


def test_the_pricing_rails_reservation_arriving_late_refits_the_sheet(ran):
    got = ran["railArrivesLate"]
    assert got["firstFit"]["k"] > 1.5, got
    assert got["afterRail"]["k"] == pytest.approx(1.283, abs=0.001)
    assert got["afterRail"]["fits"], got


def test_space_given_back_is_taken_up_again(ran):
    """Every later change, not only the first: the panel going away and the rail being collapsed
    each widen the sheet, up to the existing 170% cap."""
    got = ran["spaceGrows"]
    assert got["noRail"]["k"] == pytest.approx(1.616, abs=0.001) and got["noRail"]["fits"]
    assert got["noRailNoNav"]["k"] == pytest.approx(1.7) and got["noRailNoNav"]["fits"]


def test_the_scrollbar_cannot_start_a_refit_loop(ran):
    """At the canvas height where the sheet only overflows at the wider zoom, a fit that followed
    clientWidth would bring its own scrollbar in, fit narrower, lose the scrollbar, fit wider, and
    so on until the browser's loop limit. It must settle in one write, and still fit."""
    got = ran["scrollbarThreshold"]
    assert got["writes"] <= 2, got
    assert got["rounds"] <= 3, got
    assert got["after"]["fits"], got


def test_the_clamp_and_the_narrow_layouts_are_unchanged(ran):
    got = ran["clamp"]
    assert got["huge"]["k"] == pytest.approx(1.7), "the 170% cap moved"
    # Below 1400px the panel is inline and the 272px reservation is dropped.
    assert got["inlineRail1300"]["k"] == pytest.approx((1300 - 240 - 17 - 24) / 816, abs=0.001)
    assert got["phone380"]["k"] == pytest.approx(0.45), "the 45% floor moved"


def test_a_steady_page_is_not_refitted(ran):
    """The observer's first report, and reports about the canvas's HEIGHT, change nothing the fit
    depends on, so they write no transform: a refit costs a reflow of four pages of paper."""
    assert ran["steady"]["writes"] == 0, ran["steady"]
    assert ran["steady"]["after"]["k"] == pytest.approx(1.283, abs=0.001)


def test_the_page_observes_the_canvas_and_keys_the_fit_off_its_border_box():
    """The two facts the behaviour rests on, stated where a refactor will trip over them."""
    body = re.search(r"\n  function applyZoom\(\) \{.*?\n  \}\n", JS, re.S).group(0)
    assert "_canvasRO.observe(canvas)" in body
    key = re.search(r"\n  function zoomFitKey\(canvas, cs\) \{.*?\n  \}\n", JS, re.S).group(0)
    assert "offsetWidth" in key and "clientWidth" not in key.split("{", 1)[1], (
        "the fit key follows the scrollbar; see test_the_scrollbar_cannot_start_a_refit_loop")
