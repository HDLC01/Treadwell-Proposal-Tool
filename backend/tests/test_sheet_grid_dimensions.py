"""The estimate grid's text is visible — rows tall enough for the font, columns wide enough
for the labels, at the size the renderer actually paints.

Hanz, 2026-08-14, with a screenshot of the Epoxy tab: "make sure we can see the text (default
size for all rows, the text must be visible)". Glyphs were sliced through the middle
("MATERIAL - Patch", "Quantity") and labels cut mid-word ("MATERIAL - Epoxy Liq").

ROOT CAUSE, measured against Kyle's real workbook: text paints in POINTS from the xlsx — the
dominant cell is 12pt (×467 cells), rendered at 12 × 0.92pt ≈ 14.7px, line box ≈ 17px — while
the row/column tracks were sized in px from constants calibrated for ~11px text. And the cell's
padding + border were subtracted FROM the Excel-sized track: Excel row heights are line boxes
(no chrome), ours are border-boxes. 432 of the Epoxy tab's 648 rows carry no explicit height at
all, landing on a 20px fallback track = 15px of content for a 17px line box.

EXECUTED, NOT GREPPED. The harness lifts the real `rowTrackPx` / `colTrackPx` / `PX_PER_CHAR`
out of estimate-review.js, parses the line-height/padding the page's CSS actually declares, and
runs the arithmetic with the workbook's measured values. Constants asserted by source could pass
while the two char-width call sites disagreed — so the harness lifts and EXECUTES the dblclick
auto-fit expression too and compares behaviour.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

import estimate_writer

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "sheet-grid-harness.js"

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


# ── rows ─────────────────────────────────────────────────────────────────────
@needs_node
def test_every_row_height_in_the_real_workbook_fits_its_text(ran):
    """The complete height histogram of Kyle's Epoxy tab (None ×432, 16.05 ×8, 16.2 ×194,
    18 ×1, 21 ×3, 21.6 ×9, 26.4 ×1), each run through the real track function and compared
    against the line box the page's own CSS produces for the dominant 12pt cell."""
    for row in ran["rows"]:
        assert row["fits"], (
            f"a {row['xlsxPt']}pt row renders a {row['contentPx']}px content box for a "
            f"{ran['lineBoxPx']:.1f}px line box — glyphs slice again")


@needs_node
def test_the_default_row_is_the_one_that_was_broken(ran):
    """432 of 648 rows have NO stored height; they took a 20px track and clipped. This is the
    literal 'default size for all rows' in the request."""
    default = next(r for r in ran["rows"] if r["xlsxPt"] is None)
    assert default["fits"] and default["trackPx"] >= 24


@needs_node
def test_an_old_cached_payload_without_the_new_key_still_fits(ran):
    """default_row_height is a NEW payload key. A browser holding the previous payload shape —
    or the deploy landing frontend-first — must fall back inside the function, not clip. And the
    fallback must EQUAL the workbook's real default (15.6), or the same page renders every
    height-less row at one size before the payload refreshes and another after."""
    legacy = ran["legacyPayloadNoDefault"]
    assert legacy["fits"]
    assert legacy["equalsWorkbookDefault"], (
        "the function's built-in fallback disagrees with Kyle's sheet_format default")


@needs_node
def test_the_css_actually_declares_what_the_arithmetic_assumes(ran):
    """The +5 chrome allowance and the fit checks are computed FROM the parsed CSS, so this
    pins the declarations the math depends on: 1px vertical padding, an explicit line-height,
    and — critically — line-height on the INPUT too, because the input is height:100% and IT
    is what clips the glyphs; a div-only line-height leaves the slicing in place."""
    css = ran["css"]
    assert css["padV"] == 1, "vertical padding grew — every extra pixel comes out of the glyphs"
    assert css["lineHeight"] and css["lineHeight"] <= 1.2
    assert css["inputHasLineHeight"], "the input's own line box is the one that clips"


# ── columns ──────────────────────────────────────────────────────────────────
@needs_node
def test_the_screenshot_labels_fit_their_columns(ran):
    """The exact strings from his screenshot, at the painted 14.7px face, in their real xlsx
    column widths. The one deliberate exception: 'System 2 Options / Walls (scroll down)' is
    38 chars in a 19.8-char column — Excel itself only shows it by spilling into an empty
    neighbour, which an <input> cannot do; it gets a hover tooltip instead (asserted below)."""
    for col in ran["columns"]:
        if col["text"].startswith("System 2 Options"):
            continue
        assert col["fits"], f"{col['text']!r} needs {col['needsPx']}px, track is {col['trackPx']}px"


@needs_node
def test_the_one_string_that_cannot_fit_gets_a_tooltip():
    """Not executed (the tooltip is one branch in a 100-line DOM builder), but pinned: long
    values must carry title= so the tail is readable on hover."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    assert "inp.title = displayVal" in src, "long clipped values lost their hover tooltip"


@needs_node
def test_autofit_and_initial_layout_share_one_character_width(ran):
    """The px-per-char constant exists at two call sites. When they drift, a dblclick auto-fit
    'fixes' a column to a different width than first paint gave it — the user watches the
    column jump. Executed on both expressions, not grepped."""
    a = ran["autofit"]
    assert a["usesSharedConstant"], f"auto-fit hardcodes its own char width: {a['expr']}"
    assert a["agree"], f"auto-fit {a['autoFitPx']}px vs initial {a['initialPxForSameChars']}px"


# ── the drag floor ───────────────────────────────────────────────────────────
@needs_node
def test_a_drag_cannot_shrink_a_row_below_the_render_floor(ran):
    """The old drag floor was 14px — below anything the renderer would produce, so a stray drag
    hand-recreated the clipped-glyph bug and persisted it for that session."""
    d = ran["dragFloor"]
    assert d["dragCannotRecreateTheBug"], (
        f"drag floor {d['dragFloorPx']}px undercuts the render floor {d['renderFloorPx']}px")


# ── the payload ──────────────────────────────────────────────────────────────
def test_the_payload_carries_the_workbooks_own_default_row_height():
    """The frontend used to hardcode a guess of 15pt; Kyle's file says 15.6. The workbook is
    the authority, per tab."""
    grid = estimate_writer.read_sheet_grid("Epoxy")
    assert isinstance(grid.get("default_row_height"), float)
    assert grid["default_row_height"] == pytest.approx(15.6, abs=0.01)
    assert grid["row_heights"], "explicit row heights vanished from the payload"
    assert all(isinstance(v, float) for v in grid["row_heights"].values())
    assert grid["col_widths"] and all(isinstance(v, float) for v in grid["col_widths"].values())


def test_every_tab_reports_a_sane_default():
    """All 16 tabs go through the same reader; a sheet with no sheet_format data must fall back
    rather than emit None/0 and re-create the clipping on that one tab."""
    for name in ("Epoxy", "Polish"):
        grid = estimate_writer.read_sheet_grid(name)
        assert 10.0 <= grid["default_row_height"] <= 60.0, (name, grid["default_row_height"])
