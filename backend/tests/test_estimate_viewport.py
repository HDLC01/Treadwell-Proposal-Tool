"""Estimate Review is the spreadsheet, so the spreadsheet gets the window.

Two complaints, one screen. Hanz, 2026-08-07:

    "remove this please I can barely see the sheet. The Estimate sheet is supposed to be the
     majority viewport."
    "Is there a way to grab and expand the estimate sheets viewport?"

The first was a beta banner I had put above the grid — gone, and guarded in
test_polish_estimate_page.py so the next launch cannot take that space back.

The second is this file. The bid bar sits ABOVE the worksheet, capped at 30vh, which on a laptop
is a third of the window; the only escape was hiding it outright. A splitter now trades height
between the two.

WHAT IS EASY TO GET WRONG HERE, WHICH IS WHAT THESE TESTS ARE FOR.

  * **Resizing the viewport instead of the bid bar.** The viewport is `flex: 1 1 auto` and fills
    whatever is left. Give it an explicit height and it stops adapting — the sheet no longer
    grows when the window does, and a saved height on a big monitor leaves a laptop with a
    sliver of grid and dead space beneath it.
  * **Listening on the grip.** A drag moves faster than a 9px target. Bind the move/up to the
    grip and the page sticks in resize mode the moment the pointer outruns it.
  * **No floor under the grid.** Dragging the bar to full height would leave two rows of
    spreadsheet on the screen the spreadsheet is the point of.
  * **Trusting the saved height.** A height stored on a 27" monitor buries the sheet on a
    13" laptop, so it has to be clamped on read and on window resize, not just on drag.
  * **Mouse only.** The grip is a focusable separator; without key handling it is decoration to
    anyone not using a mouse.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HTML = FRONTEND / "estimate-review.html"
JS = FRONTEND / "js" / "estimate-review.js"


def _code(path):
    """Source with // comments stripped — the comments describe the failure modes, so a raw
    grep matches its own prose."""
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                     if not l.strip().startswith("//"))


@pytest.fixture(scope="module")
def html():
    return HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js():
    return _code(JS)


@pytest.fixture(scope="module")
def resizer(js):
    i = js.index("function wireBidResizer")
    return js[i:js.index("\n})();", i)]


# ── it exists, and it is a real control ───────────────────────────────────────
def test_the_splitter_exists_between_the_bid_bar_and_the_grid(html):
    body = html[html.index("<main>"):]
    bar = body.index('id="bid-bar"')
    grip = body.index('id="bid-resizer"')
    view = body.index('class="xl-viewport"')
    assert bar < grip < view, "the splitter is not between the bid bar and the worksheet"


def test_it_is_a_separator_not_a_decorative_div(html):
    i = html.index('id="bid-resizer"')
    tag = html[i - 200:i + 400]
    assert 'role="separator"' in tag
    assert 'aria-orientation="horizontal"' in tag
    assert 'tabindex="0"' in tag, "not focusable, so the keyboard path is unreachable"
    assert "aria-label" in tag


def test_it_disappears_when_the_bar_is_collapsed(html):
    """There is nothing to trade when the bar is folded away, and a live grip there would look
    broken."""
    assert ".bid-bar.collapsed + .bid-resizer" in html


# ── the thing it must not do ──────────────────────────────────────────────────
def test_it_resizes_the_bid_bar_and_never_the_viewport(resizer):
    """The viewport is flex:1 and fills what is left. An explicit height stops it adapting to
    the window, which is worse than the problem being solved."""
    assert "bar.style.height" in resizer
    assert not re.search(r'view\.style\.(height|flex|maxHeight)', resizer), (
        "the splitter sets a height on the viewport; it must only resize the bid bar")


def test_the_thirty_vh_cap_is_lifted_when_a_height_is_set(resizer):
    """The stylesheet caps the bar at 30vh. Without clearing it, dragging downward stops dead
    at the cap and the control feels broken."""
    assert 'maxHeight = "none"' in resizer


def test_the_grid_keeps_a_floor(resizer):
    assert "GRID_FLOOR" in resizer
    m = re.search(r'GRID_FLOOR\s*=\s*(\d+)', resizer)
    assert m and int(m.group(1)) >= 100, "the floor is too low to be worth having"
    assert "maxH" in resizer, "nothing stops the bar from taking the whole window"


def test_the_bar_keeps_a_floor_too(resizer):
    """Dragging to zero would hide the header row and its Hide button, stranding the control."""
    assert re.search(r'MIN\s*=\s*\d+', resizer)
    assert "Math.max(MIN" in resizer


# ── the drag itself ───────────────────────────────────────────────────────────
def test_move_and_release_are_bound_to_the_window_not_the_grip(resizer):
    """A drag outruns a 9px target. Bound to the grip, the page sticks in resize mode the moment
    the pointer leaves it."""
    for ev in ("mousemove", "mouseup"):
        assert re.search(r'window\.addEventListener\("%s"' % ev, resizer), ev
    assert re.search(r'window\.removeEventListener\("mousemove"', resizer), (
        "the move listener is never removed, so every drag leaves one behind")


def test_the_drag_is_persisted_once_on_release_not_every_frame(resizer):
    up = resizer[resizer.index("function onUp"):resizer.index("function onDown")]
    assert "setH(" in up and "true" in up, "the settled height is never saved"
    move = resizer[resizer.index("function onMove"):resizer.index("function onUp")]
    assert "false" in move, "every mousemove writes to localStorage"


def test_touch_is_handled_too(resizer):
    assert "touchstart" in resizer and "touchmove" in resizer and "touchend" in resizer
    assert "e.touches" in resizer, "touch events are bound but the Y is read as a mouse event"


# ── restoring it ──────────────────────────────────────────────────────────────
def test_the_height_is_remembered(resizer):
    assert "tw_bidbar_h" in resizer
    assert "localStorage" in resizer


def test_the_saved_height_is_clamped_on_read(resizer):
    """A height saved on a 27-inch monitor buries the sheet on a 13-inch laptop.

    Asserts the saved value itself flows through setH, which is where the clamp lives. An
    earlier version looked for "setH(" anywhere in the 300 characters after the read — and
    passed while the restore assigned bar.style.height directly, because onMove's setH fell
    inside the window.
    """
    assert re.search(r'setH\(\s*saved\b', resizer), (
        "the saved height is applied without going through setH, so it is never clamped")


def test_a_window_resize_reclamps(resizer):
    assert re.search(r'window\.addEventListener\("resize"', resizer), (
        "a saved height that fitted one window can bury the sheet on a smaller one")


def test_there_is_a_way_back_to_the_default(resizer):
    assert "function reset" in resizer
    assert "dblclick" in resizer
    assert "removeItem" in resizer, "reset leaves the old height in storage to come back later"


# ── keyboard ──────────────────────────────────────────────────────────────────
def test_the_keyboard_can_drive_it(resizer):
    assert "keydown" in resizer
    for key in ("ArrowUp", "ArrowDown"):
        assert key in resizer, key


def test_the_keyboard_has_a_reset_and_the_two_extremes(resizer):
    for key in ("Home", "End", "Escape"):
        assert key in resizer, key


def test_the_key_handler_does_not_swallow_other_keys(resizer):
    """preventDefault on everything would break Tab off the grip."""
    kd = resizer[resizer.index('addEventListener("keydown"'):]
    assert "else return;" in kd, "unhandled keys are not passed through"
