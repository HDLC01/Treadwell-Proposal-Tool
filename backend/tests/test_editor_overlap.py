"""Editing a text box that overlaps its neighbour, on the real template geometry.

Kyle, 2026-08-20: "There is a problem when the texboxes overlap, its hard to edit."

WHY THESE CSS ASSERTIONS RESOLVE THE CASCADE INSTEAD OF GREPPING. A regex over a
stylesheet finds a declaration; it cannot tell you whether the browser uses it. This
repo has been bitten twice by that: the `hidden` attribute defeated by a class `display`
rule, and the expanded-box badge whose message was overridden by an equal-specificity
rule written later in the file. `pointer-events` on a grip is exactly that shape — two
rules of IDENTICAL specificity (`.tw-box-tools > *` and `.tw-grip`, one class each)
disagree, so source order alone picks the winner. So these tests compute specificity and
order and assert what WINS. Reordering those two rules flips the behaviour, and this
file is the only thing that would notice.
"""
from __future__ import annotations

import pathlib
import re

import docx
import pytest

import proposal_writer as pw

ROOT = pathlib.Path(__file__).resolve().parents[2]
CSS = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "proposal-review.js").read_text(encoding="utf-8")
TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "templates"
DIRECT_EPOXY = TEMPLATES / "Direct" / "XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx"

PT_PER_CSS_PX = 0.75          # the page renders at true point sizes; 96dpi CSS pixels
GRIP_H_PX = 11.0              # .tw-grip-move is 11x11


# ── a small, honest cascade ───────────────────────────────────────────────────
def _rules(css):
    """[(selector, body)] in source order, @media wrappers flattened away."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{", "", css)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def _specificity(sel):
    """(ids, classes+attrs+pseudo-classes, elements). Sufficient for this stylesheet,
    which uses no ids and no !important on the rules under test."""
    ids = len(re.findall(r"#[\w-]+", sel))
    cls = len(re.findall(r"\.[\w-]+|\[[^\]]+\]|:(?!:)[\w-]+(?:\([^)]*\))?", sel))
    els = len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", sel))
    return (ids, cls, els)


def _matches(sel, box_classes, grip_classes, box_states):
    """Does `sel` match the grip inside a box carrying `box_classes` in `box_states`?

    Deliberately narrow: it understands only the selector shapes this stylesheet uses
    for the grips. Anything else it declines, so a new shape shows up as a test that
    stops constraining rather than one that silently passes.
    """
    sel = sel.strip()
    if sel == ".tw-box-tools > *":
        return True                                    # the grip IS a tools child
    parts = [p for p in re.split(r"\s+", sel) if p and p != ">"]
    if not parts:
        return False
    target = parts[-1]
    tclasses = set(re.findall(r"\.([\w-]+)", target))
    tstates = set(re.findall(r":(?!:)([\w-]+)", target))
    if not tclasses or not tclasses <= grip_classes:
        return False
    if tstates and not tstates <= box_states:          # e.g. .tw-grip:hover
        return False
    for anc in parts[:-1]:
        aclasses = set(re.findall(r"\.([\w-]+)", anc))
        astates = set(re.findall(r":(?!:)([\w-]+)", anc))
        if aclasses and not aclasses <= box_classes:
            return False
        if astates and not astates <= box_states:
            return False
    return True


def _resolved(prop, box_classes, grip_classes, box_states):
    """The value the browser would use, by specificity then source order."""
    best, best_key = None, None
    for i, (sel, body) in enumerate(_rules(CSS)):
        for one in (s.strip() for s in sel.split(",")):
            if not _matches(one, box_classes, grip_classes, box_states):
                continue
            m = re.search(r"(?<![-\w])" + re.escape(prop) + r"\s*:\s*([^;]+)", body)
            if not m:
                continue
            key = (_specificity(one), i)
            if best_key is None or key >= best_key:
                best, best_key = m.group(1).strip(), key
    return best


BOX = {"tw-txbx"}
GRIP = {"tw-grip", "tw-grip-move"}


def test_an_invisible_grip_does_not_take_the_click():
    """The bug. At rest a grip is opacity 0, and an element at opacity 0 is still
    hit-tested — so PRICE's move grip silently ate the click meant for WORK's last line,
    with wireBoxDrag's preventDefault ensuring no caret ever arrived."""
    assert _resolved("opacity", BOX, GRIP, set()) == "0", "a grip is visible at rest?"
    assert _resolved("pointer-events", BOX, GRIP, set()) == "none", (
        "an invisible grip is taking clicks again — the overlap bug is back. Note that "
        "`.tw-box-tools > *` grants pointer-events:auto at EQUAL specificity, so check "
        "source order as well as the declaration itself")


def test_a_visible_grip_is_still_grabbable():
    """The other half: inert at rest must not mean undraggable. Kyle still has to be able
    to move and resize a box, which is the only reason the grips exist. HOVER is the state
    that raises them — see the next test for why it is the only one."""
    assert _resolved("opacity", BOX, GRIP, {"hover"}) == ".85"
    assert _resolved("pointer-events", BOX, GRIP, {"hover"}) == "auto", (
        "the grip is visible on hover but cannot be grabbed")


def test_focusing_a_box_does_not_arm_its_grips():
    """`:focus-within` used to raise the grips too, and that is the same click-theft bug from the
    other end. The move grip sits ABOVE its own box (`top: -13px`), i.e. inside the box above it —
    so while the estimator typed in PRICE, PRICE's grip was a live target sitting on WORK's last
    line, and `wireBoxDrag`'s pointerdown `preventDefault()`s: the click that should have put a
    caret in WORK produced nothing at all, with nothing on screen explaining why. Hanz,
    2026-08-26, on the editor being clunky between sections; you clicked slightly to one side and
    it worked.

    Visible and grabbable still move together — the box you hover is the box whose grips arm —
    which is what stops the other failure mode, a grip you can see but cannot drag."""
    assert _resolved("opacity", BOX, GRIP, {"focus-within"}) == "0", (
        "a merely-focused box shows its grips again, over its neighbour's text")
    assert _resolved("pointer-events", BOX, GRIP, {"focus-within"}) == "none", (
        "a focused box's grips are hit-testable again — that is PRICE's move grip eating the "
        "click meant for WORK's last line")


def test_a_dragging_box_keeps_its_grips_live():
    """Mid-drag the pointer has capture, but the grip must not go inert underneath it."""
    assert _resolved("pointer-events", BOX | {"tw-box-dragging"}, GRIP, set()) == "auto"


# ── the arithmetic that makes the fix load-bearing ────────────────────────────
def _boxes():
    return pw.template_geometry(docx.Document(str(DIRECT_EPOXY)))["boxes"]


def _grip_top_offset_px():
    """The grip's own `top`, read out of the stylesheet rather than typed here — if
    somebody moves the grip, this test follows them instead of going stale."""
    for sel, body in _rules(CSS):
        if ".tw-grip-move" in sel:
            m = re.search(r"top\s*:\s*(-?[\d.]+)px", body)
            if m:
                return float(m.group(1))
    raise AssertionError(".tw-grip-move has no top offset — rewrite this test")


def test_the_boxes_really_do_overlap_on_kyles_template():
    """Not hypothetical: WORK ends BELOW where PRICE begins, in Kyle's own file."""
    by_id = {b["id"]: b for b in _boxes()}
    work, price = by_id[2], by_id[4]
    work_bottom = work["y_pt"] + work["h_pt"]
    assert price["y_pt"] < work_bottom, "the overlap this file exists for is gone"
    overlap = work_bottom - price["y_pt"]
    assert 2.0 < overlap < 4.0, "overlap is now %.2fpt — re-read this file" % overlap


def test_the_lower_boxs_move_grip_sits_on_the_upper_boxs_text():
    """Why pointer-events at rest mattered, in points on the page. PRICE's grip is
    positioned above PRICE's own top edge, which puts it inside WORK — over WORK's last
    line, not over empty page."""
    by_id = {b["id"]: b for b in _boxes()}
    work, price = by_id[2], by_id[4]
    grip_top_pt = price["y_pt"] + _grip_top_offset_px() * PT_PER_CSS_PX
    grip_bottom_pt = grip_top_pt + GRIP_H_PX * PT_PER_CSS_PX
    work_bottom = work["y_pt"] + work["h_pt"]
    assert grip_top_pt > work["y_pt"], "the grip is above WORK entirely"
    assert grip_bottom_pt < work_bottom, "the grip clears WORK's bottom edge"
    assert work_bottom - grip_top_pt > 9.0, (
        "the grip only clips WORK's bottom margin, so the click theft would be harmless "
        "and this fix would not be load-bearing")


# ── the z-order the fix introduces ────────────────────────────────────────────
def test_the_focused_box_outranks_neighbours_but_not_open_or_dragging():
    """Ordering is the point: the box you are typing in must beat a plain neighbour, and
    must NOT beat one expanded to read past its clip, or one being dragged across the
    page. The latter two are set from JS, so this reads both sides and compares them."""
    plain = int(re.search(r"\.tw-txbx\s*\{[^}]*z-index\s*:\s*(\d+)", CSS).group(1))
    m = re.search(r"\.tw-txbx:focus-within\s*\{[^}]*z-index\s*:\s*(\d+)", CSS)
    assert m, "the focused box no longer gets a z-index — the overlap fix is gone"
    focused = int(m.group(1))
    opened = int(re.search(r'zIndex\s*=\s*open\s*\?\s*"(\d+)"', JS).group(1))
    dragged = int(re.search(r'zIndex\s*=\s*"(\d+)"', JS).group(1))
    assert plain < focused < opened <= dragged, (
        "z-order broken: plain=%d focused=%d open=%d drag=%d"
        % (plain, focused, opened, dragged))


def test_the_focus_raise_is_css_not_inline():
    """fitTxbx clears box.style.zIndex on every pass, and it runs on every keystroke and
    every repagination. An inline raise would be wiped mid-typing, and would also break
    the tests asserting a closed box carries no inline zIndex. So it must be a rule."""
    assert re.search(r"\.tw-txbx:focus-within\s*\{[^}]*z-index", CSS), "not in the CSS"
    assert not re.search(r"focus.{0,40}style\.zIndex\s*=", JS, re.S), (
        "something now sets zIndex inline on focus — fitTxbx will erase it")


def test_the_cascade_helper_is_actually_looking_at_something():
    """A guard on the guard. If _matches stopped matching anything, every assertion above
    would pass vacuously on None == None."""
    assert _resolved("position", BOX, GRIP, set()) == "absolute"
    assert _resolved("no-such-property", BOX, GRIP, set()) is None
