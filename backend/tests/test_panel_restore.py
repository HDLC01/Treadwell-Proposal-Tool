"""A moved panel must come back onto the screen it is reopened on — and must not cover the form.

Two bugs, both found by walking a real browser at real widths rather than by any test, in the widget
Hanz asked for: *"Can we transfer the cheat sheet on the right side so that it's not bothering when
they are speaking? And make it look like the floating widget from the proposal tool on number three
proposals."*

**IT STILL COVERED THE FORM.** The first attempt reserved a lane for the rail between 1200px and
1540px and then gave the reservation up above 1540, on the theory that a centred 1000px column
already leaves gutters wider than the rail. It does not: `.wrap`'s containing block is BODY, which
begins after a ~240px left nav, so the right-hand gutter is far narrower than a centred-column
calculation predicts. Measured at 1750px the rail sat at x=1465 while the column still ran to
x=1486 — a 21px overlap, on exactly the text the widget had been moved aside to stop covering. The
fix reserves the lane at *every* floating width, the way the step-3 rail always did, and breaks at
the same 1400px the step-3 rail breaks at.

**IT COULD BE PUT SOMEWHERE UNREACHABLE.** Both panels clamped while dragging and restored with no
clamp. A position saved on a wide monitor came back off the edge of a laptop screen with the drag
handle off screen too: nothing to grab, and no way back short of clearing site data. `TW.clampPanelPos`
now clamps the restore with the same bounds as the drag, in both panels — the reference had the
identical hole, and fixing only the copy would have left the original for someone to find the hard
way.

RUN, NOT READ, for the restore: the guard is a `Math.min` and the bug was that it sat on only one of
two code paths, which no source assertion can distinguish. See
[backend/tests/js/panel-restore-harness.js](js/panel-restore-harness.js).

The CSS is asserted as text because a headless run has no layout engine — but it is asserted as the
*rule the measurement produced*, not as a snapshot of whatever is currently written.
"""

import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "panel-restore-harness.js"

WIN_W, WIN_H = 1750, 1125          # the laptop the harness restores onto
CHEAT_W, OPTS_W = 250, 240         # the two panels' CSS widths


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def intake_css():
    return (FRONTEND / "polish-intake.html").read_text(encoding="utf-8")


# ── the bounds ───────────────────────────────────────────────────────────────
def test_the_clamp_pulls_a_far_away_position_back_to_the_last_legal_pixel(ran):
    """Back onto the screen, and no further than it has to be.

    A clamp that reset the panel to a corner would throw away a placement the estimator chose; this
    keeps the intent (they put it on the right) while making it reachable.
    """
    c = ran["clamp"]
    assert c["farRight"] == {"left": WIN_W - CHEAT_W - 4, "top": 300}
    assert c["farBottom"] == {"left": 300, "top": WIN_H - 40}
    assert c["negative"] == {"left": 4, "top": 4}


def test_a_position_that_already_fits_is_not_touched(ran):
    """The clamp must not become a panel that repositions itself for no reason.

    This is the case that makes the test above mean something: without it, `return {left: 4, top: 4}`
    would pass every other assertion in this file about being on screen.
    """
    assert ran["clamp"]["inBounds"] == {"left": 600, "top": 400}
    assert ran["clamp"]["rightEdge"] == {"left": WIN_W - CHEAT_W - 4, "top": 10}
    # A panel not yet laid out reports offsetWidth 0; the CSS width has to stand in, or the lane
    # would be computed as the full window and the clamp would let it sit past the right edge.
    assert ran["clamp"]["noWidth"]["left"] == WIN_W - CHEAT_W - 4


# ── the cheat sheet ──────────────────────────────────────────────────────────
def test_a_position_saved_on_a_wide_monitor_is_reachable_on_a_laptop(ran):
    """The reported shape of the bug: 3400×2600 restored onto a 1750×1125 window.

    `onScreen` is the whole point — the panel's right edge inside the viewport and its header above
    the bottom. Before the fix this restored at 3400/2600 with the handle nowhere on screen.
    """
    r = ran["cheatRestore"]
    assert r["onScreen"], r["at"]
    assert r["at"] == {"left": WIN_W - CHEAT_W - 4, "top": WIN_H - 40, "right": "auto"}


def test_where_the_estimator_actually_left_it_is_where_it_opens(ran):
    """The position from the real browser walk (1265/264) survives a reload untouched."""
    assert ran["cheatLegal"] == {"left": 1265, "top": 264, "right": "auto"}


def test_below_the_breakpoint_the_restore_stands_down(ran):
    """In the flow, left/top are inert and offsetWidth is the whole column.

    Clamping against that width would compute a lane for a panel four times too wide, so the restore
    must not run at all — the panel opens where the CSS put it.
    """
    assert ran["cheatInFlow"] == {"left": "", "top": "", "right": "16px"}


def test_dragging_still_clamps_and_still_remembers(ran):
    """The drag was verified in a browser and had no test; now neither path can be fixed by
    breaking the other. Hurled at 9000/9000 it stops at the same bounds the restore uses, the
    dragging class goes on and comes back off, and what is stored is the clamped position.
    """
    d = ran["cheatDrag"]
    assert d["midDrag"] is True
    assert d["stillDragging"] is False
    assert d["clamped"]["left"] == WIN_W - CHEAT_W - 4
    assert d["clamped"]["top"] == WIN_H - 40
    assert d["saved"] == {"left": WIN_W - CHEAT_W - 4, "top": WIN_H - 40}


# ── the panel this one was copied from ───────────────────────────────────────
def test_the_step_three_rail_is_recoverable_too(ran):
    """polish-intake copied this panel, and inherited its bug.

    Reported nowhere, because nobody had dragged the Pricing rail off a big monitor yet. Fixing only
    the copy would have left this one for a user to find.
    """
    r = ran["optsRestore"]
    assert r["onScreen"], r["at"]
    assert r["at"]["left"] == WIN_W - OPTS_W - 4


# ── the lane, which is what "not bothering" actually means ───────────────────
def test_the_rail_gets_its_own_lane_at_every_width_it_floats_at(intake_css):
    """The 21px overlap, stated as the rule the measurement produced.

    Two claims: the lane is reserved inside the floating media query, and there is NO wider
    breakpoint that gives it back. The second is the bug — the reservation was dropped at 1540px
    because the gutter was assumed to be `(1000 + 2x266)/2`, and a ~240px left nav means it is not.
    """
    floating = re.search(r"@media \(min-width:(\d+)px\)\{(.+?)\n    \}", intake_css, re.S)
    assert floating, "the floating block is gone — has the widget been reverted?"
    assert floating.group(1) == "1400", (
        "the cheat sheet must break at the same width the step-3 rail breaks at")
    assert "margin-right:282px" in floating.group(2), (
        "the column must leave a lane for the rail while it is floating")
    # padding-right would reserve the lane by SHRINKING the column to 718px, making the textarea
    # they dictate into smaller. margin-right moves the column and keeps its full 1000px.
    assert "padding-right:282px" not in intake_css

    for width in re.findall(r"@media \(min-width:(\d+)px\)", intake_css):
        assert int(width) <= 1400, (
            f"a min-width:{width}px block reappeared. If it hands the rail's lane back, the panel "
            "overlaps the form again — that was the 21px bug, measured at 1750px.")


def test_the_step_three_rail_keeps_the_lane_it_always_kept():
    """The reference, asserted so "match the step-3 widget" stays a fact and not a memory.

    Its reservation is on `:has(#options-panel:not([hidden]))` at every width above its breakpoint,
    and its breakpoint is 1400 — which is where the 1400 above comes from.
    """
    css = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
    assert re.search(r"#options-panel:not\(\[hidden\]\)\) \.word-canvas \{\s*padding-right: 272px",
                     css), "the step-3 rail stopped reserving its lane"
    assert re.search(r"@media \(max-width:\s*1400px\)", css), (
        "the step-3 rail's breakpoint moved — the 1400 asserted above came from matching it")
