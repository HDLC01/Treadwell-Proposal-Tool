"""Dragging and resizing a proposal text box, in the browser half.

Hanz, 2026-08-13: "Allow me to drag and resize the text box for the proposal please."

The backend could already resize a box (test_box_resize.py) and the frontend never asked it to.
Moving did not exist at either end. This file covers the browser half of both: the grips, the
pointer arithmetic, the clamping, the persistence, and the two existing behaviours a new gesture
could quietly break.

WHY IT RUNS THE CODE RATHER THAN READING IT. The whole feature is arithmetic across three
coordinate systems — client px, CSS px, document points — with `transform: scale(k)` in the
middle. #doc-zoom's k is FITTED to the canvas (applyZoom clamps it to 0.45-1.7), so k is almost
never 1 and a missing division shows up as the box drifting away from the cursor. No source
assertion can see that. The precedent is expensive: on 2026-08-12 an unbound identifier shipped
with every source-text assertion green and took the production board down.

So `js/box-drag-harness.js` lifts the SHIPPED functions out of proposal-review.js — including the
box loop inside renderPositioned, fitTxbx, and wireOverflowExpand's click handler — gives them the
smallest DOM the gesture touches, and fires real pointer events at four zoom levels.

THE TWO NUMBERS. 1pt = 96/72 CSS px, and the transform makes 1 layout px into k screen px, so a
client-px delta is `px * (72/96) / k` points. 100px is 166.67pt at 45% zoom and 44.12pt at 170%.
Both are asserted below, because getting either factor wrong still "works" at one zoom.

THE TWO CEILINGS, which are different rectangles on purpose and match proposal_writer exactly:
  * how BIG a box may be made — the printable area (432 x 648 on Kyle's sheet), because a box
    taller than that cannot fit from any position.
  * how far it may be MOVED — the SHEET, because every box in every template already sits outside
    the printable area (the DATE/JOB NAME header at y=36pt against a 72pt margin, the logo at
    x=27pt against a 90pt one). Bounding position by the printable area would refuse to move any
    box in any template, and a refused drag reads as a broken drag.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "box-drag-harness.js"
JS = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

DESIGN_H = 183.75
DESIGN_W = 423.0
DESIGN_X = 161.8
DESIGN_Y = 153.2


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the zoom conversion: the bug this feature would otherwise ship with ──────
def test_a_pointer_delta_becomes_points_through_the_zoom(ran):
    """100 client px is 75pt of document at 100% zoom, and k divides that again. Miss the 72/96
    and every drag is 33% too big; miss the k and the box runs away from the cursor at every zoom
    the estimator actually gets."""
    got = {row["k"]: row["hundredPx"] for row in ran["ptPerPx"]}
    assert got[1] == pytest.approx(75.0)
    assert got[0.45] == pytest.approx(100 * 72 / 96 / 0.45, abs=0.01)
    assert got[1.35] == pytest.approx(100 * 72 / 96 / 1.35, abs=0.01)
    assert got[1.7] == pytest.approx(100 * 72 / 96 / 1.7, abs=0.01)


def test_a_nonsense_zoom_degrades_to_no_zoom(ran):
    """A zero or missing k must not divide the delta into infinity and fling the box off the
    page. 0, null and undefined all read as 100%; a NaN delta reads as no movement."""
    assert ran["ptPerPxJunk"] == [75.0, 75.0, 75.0, 0.0]


def test_the_zoom_factor_is_measured_not_remembered(ran):
    """applyZoom can run between the pointerdown and the pointerup — a window resize, the terms
    repaginating, a font swap — so a k captured at the start would describe the previous zoom.
    zoomScale reads it off the element: getBoundingClientRect is scaled by the transform,
    offsetWidth is not, and the ratio is the live factor."""
    assert ran["zoomScaleMeasured"] == pytest.approx(1.35, abs=1e-3)
    assert ran["zoomScaleAtOne"] == pytest.approx(1.0, abs=1e-3)
    assert ran["zoomScaleUnlaidOut"] == 1, "an unmeasured element must read as 100%, not 0 or NaN"


@pytest.mark.parametrize("k", [0.45, 1, 1.35, 1.7])
def test_a_real_drag_resizes_by_the_zoom_corrected_amount(ran, k):
    """The end-to-end version of the same thing: a real pointerdown/move/up on the bottom grip,
    100 client px down, at each end of applyZoom's clamp."""
    row = next(r for r in ran["heightByZoom"] if r["k"] == k)
    want = DESIGN_H + 100 * 72 / 96 / k
    assert row["h"] == pytest.approx(want, abs=0.02), (
        "a 100px drag at %g zoom changed the height by %.2fpt, expected %.2f"
        % (k, row["h"] - DESIGN_H, want - DESIGN_H))
    # And the same number reaches the payload and the metadata fitTxbx reads.
    assert row["payload"]["h_pt"] == pytest.approx(want, abs=0.02)
    assert row["boxHPt"] == pytest.approx(want, abs=0.02)


def test_the_corner_grip_moves_both_axes(ran):
    r = ran["corner"]["res"]["rect"]
    assert r["width"] == "432pt", "the width stopped short of the printable-area ceiling"
    assert float(r["minHeight"].replace("pt", "")) == pytest.approx(
        DESIGN_H + 100 * 72 / 96 / 1.35, abs=0.02)


def test_a_multi_step_drag_lands_where_a_single_step_one_does(ran):
    """Deltas are measured from the pointerdown, not accumulated between moves. Accumulating is
    how a slow drag ends up going twice as far as a fast one."""
    assert ran["moveStepped"]["payload"] == ran["moveOneStep"]["payload"]


# ── the two ceilings ─────────────────────────────────────────────────────────
def test_a_resize_stops_at_the_printable_area(ran):
    """The same 432 x 648 the server's sanitiser refuses past. If the handle went further, the
    estimator would drag to a size that is then silently dropped, which reads as a broken drag."""
    assert ran["pure"]["tooWide"]["w"] == pytest.approx(432.0)
    assert ran["pure"]["tooTall"]["h"] == pytest.approx(648.0)


def test_a_resize_also_stops_at_the_paper_for_a_box_near_an_edge(ran):
    """A box starting at x=200 cannot be 432 wide on a 612 sheet, whatever the printable area
    says. Both bounds apply, and the tighter one wins."""
    assert ran["pure"]["tooWideNearEdge"]["w"] == pytest.approx(412.0)   # 612 - 200
    assert ran["pure"]["tooTallNearEdge"]["h"] == pytest.approx(192.0)   # 792 - 600


def test_a_resize_stops_at_the_twelve_point_floor(ran):
    """Below 12pt is not a box. The server refuses it, so the handle must not offer it."""
    assert ran["pure"]["tooSmall"] == {"x": 100, "y": 100, "w": 12, "h": 12}


def test_the_floor_wins_when_the_paper_and_the_floor_disagree(ran):
    """A box wedged against the right edge has less than 12pt of paper left. Clamping toward the
    paper would send a 7pt width the sanitiser refuses; clamping toward the floor sends something
    it accepts."""
    assert ran["pure"]["wedged"]["w"] == pytest.approx(12.0)


def test_a_box_cannot_be_dragged_off_the_paper(ran):
    """The failure this bound exists for: LibreOffice CLIPS a box that hangs off the sheet, so
    nothing errors and the customer's proposal is simply missing a paragraph."""
    p = ran["pure"]
    assert p["offRight"]["x"] == pytest.approx(612 - DESIGN_W)
    assert p["offBottom"]["y"] == pytest.approx(792 - DESIGN_H)
    assert p["offTopLeft"]["x"] == 0 and p["offTopLeft"]["y"] == 0


def test_a_box_that_lives_in_the_margins_is_still_movable(ran):
    """Every box in every one of Kyle's templates sits outside the printable area — this is the
    DATE/JOB NAME header, at y=36pt against a 72pt top margin. Bounding position by the printable
    area (the obvious mistake, since that IS the size bound) would refuse to move any of them."""
    assert ran["pure"]["headerBox"] == {"x": pytest.approx(8.35), "y": pytest.approx(16.0),
                                        "w": 72, "h": 18}


def test_a_resize_never_moves_the_box_and_a_move_never_resizes_it(ran):
    p = ran["pure"]
    assert (p["resizeKeepsCorner"]["x"], p["resizeKeepsCorner"]["y"]) == (
        pytest.approx(DESIGN_X), pytest.approx(DESIGN_Y))
    assert (p["moveKeepsSize"]["w"], p["moveKeepsSize"]["h"]) == (
        pytest.approx(DESIGN_W), pytest.approx(DESIGN_H))


def test_missing_limits_do_not_throw(ran):
    """boxLimits is null until the first positioned render. A gesture that somehow arrives first
    must fall back to a Letter sheet rather than crash the editor."""
    assert ran["pure"]["noLimits"] == {"x": 15, "y": 15, "w": 50, "h": 50}


# ── what the estimator actually sees ─────────────────────────────────────────
def test_every_box_gets_a_move_grip_three_resize_grips_and_a_reset(ran):
    """Built by renderPositioned's own loop, not by the harness — so this cannot pass against a
    hand-made element that has drifted from the shipped one."""
    m = ran["mounted"]
    assert m["grips"] == ["move", "e", "s", "se"]
    assert m["hasTools"] and m["hasReset"]
    assert m["boxId"] == "3", "the box element carries no id, so a drag cannot be attributed"


def test_the_box_mounts_at_the_templates_own_geometry(ran):
    m = ran["mounted"]["rect"]
    assert (m["left"], m["top"], m["width"], m["minHeight"]) == (
        "161.8pt", "153.2pt", "423pt", "183.75pt")
    assert m["boxHPt"] == "183.75", "fitTxbx reads the height from here"
    assert m["moved"] is False


def test_the_size_is_shown_while_dragging_and_put_away_afterwards(ran):
    """"Bigger" is not a size. The estimator is laying out a customer document, so they get the
    actual numbers, and only while they are changing them."""
    assert ran["corner"]["res"]["readout"] == "432 × 239 pt"
    assert ran["corner"]["res"]["readoutAfter"] == ""
    assert ran["moveOneStep"]["res"]["readout"] == "x 128 · y 203 pt"
    assert ran["corner"]["res"]["draggingMidGesture"] is True
    assert ran["corner"]["res"]["draggingAfter"] is False


def test_the_readout_says_width_by_height_and_x_by_y(ran):
    assert ran["readout"] == {"size": "423 × 184 pt", "move": "x 162 · y 153 pt"}


def test_the_reset_control_says_what_it_does(ran):
    """An estimator who has nudged three boxes needs a way back that is not "reload the page and
    lose the text you typed"."""
    assert ran["mounted"]["resetLabel"] == "Reset box"
    assert ran["mounted"]["resetTitle"] == "Put this box back where the template has it"
    assert all(t.startswith("Drag to ") for t in ran["mounted"]["gripTitles"])


def test_reset_puts_the_box_back_and_clears_the_saved_layout(ran):
    r = ran["reset"]
    assert r["before"], "the fixture never resized the box, so this proves nothing"
    assert r["after"] == {}
    assert (r["rect"]["left"], r["rect"]["width"], r["rect"]["minHeight"]) == (
        "161.8pt", "423pt", "183.75pt")
    assert r["rect"]["boxHPt"] == "183.75"
    assert r["rect"]["moved"] is False
    assert r["stored"] == {}, "reset never reached the draft, so a reload would undo the reset"


def test_a_grab_with_no_travel_is_not_a_drag(ran):
    """Otherwise a Reset button appears on every box somebody brushed past, and every brush
    writes a draft."""
    assert ran["slop"] == {"payload": {}, "moved": False, "persisted": 0}


def test_dragging_a_box_back_to_the_template_removes_the_override(ran):
    """Overrides are stored as differences, which makes this an undo for free — and keeps
    generation byte-identical for a box that ended up where it started."""
    assert ran["backToDesign"]["afterFirst"], "the fixture never moved the box"
    assert ran["backToDesign"]["afterBack"] == {}
    assert ran["backToDesign"]["rect"]["moved"] is False


def test_only_the_axes_that_changed_are_sent(ran):
    """A width-only drag must not pin the height, or Kyle editing the template would stop moving
    that box's height for anybody with a saved draft."""
    assert ran["entry"]["nothing"] is None
    assert ran["entry"]["widthOnly"] == {"w_pt": 430}
    assert ran["entry"]["rounded"] == {"w_pt": 430.12}, "not rounded to the template's precision"
    assert ran["entry"]["hairline"] is None, "a 0.02pt difference is float noise, not an edit"
    assert ran["entry"]["nan"] is None
    assert ran["moveOneStep"]["payload"]["3"].keys() == {"x_pt", "y_pt"}
    assert ran["heightByZoom"][0]["payload"].keys() == {"h_pt"}


# ── the two existing behaviours a new gesture could break ────────────────────
def test_enlarging_a_box_stands_the_overflow_notice_down(ran):
    """THE point of the feature. Today a long WORK scope shrinks its own font and then gets
    clipped with a "Too long for this box" badge; the estimator's actual fix is a taller box, and
    the badge has to notice. fitTxbx reads the height out of dataset.boxHPt, which applyBoxGeom
    writes, so the notice follows the drag without either knowing about the other."""
    assert ran["overflow"]["atDesign"]["marked"] is True, (
        "the fixture's content already fits the design box, so this proves nothing")
    assert ran["overflow"]["atDesign"]["clipped"], "fitTxbx did not clip at the design height"
    assert ran["overflow"]["afterGrow"]["marked"] is False, (
        "the box was made taller than its content and still claims the text is cut off")
    assert ran["overflow"]["afterGrow"]["clipped"] == "", "the clip survived the resize"
    assert ran["overflow"]["afterGrow"]["boxHPt"] == pytest.approx(459.75, abs=0.02)


def test_releasing_a_grip_does_not_open_the_overflow_peek(ran):
    """A pointerup on a grip fires a click on the box, and wireOverflowExpand toggles on exactly
    that. Peeking at hidden text is the opposite of what somebody who just made the box bigger
    asked for."""
    assert ran["peek"]["gripClickOpened"] is False
    assert ran["peek"]["resetClickOpened"] is False


def test_the_overflow_peek_still_works(ran):
    """The guard above must skip the grips, not disable the feature."""
    assert ran["peek"]["bodyClickOpened"] is True


def _css_rule(selector):
    """The declarations of one exact top-level rule. Scoped to the rule rather than to a slice of
    the file: an earlier draft of this test read a 60-line window, and `.tw-notes-overflow::before`
    inside it carries `pointer-events: none` — so the assertion passed with the declaration it was
    checking for deleted."""
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, "%s has no top-level rule in styles.css" % selector
    return m.group(1)


@pytest.mark.parametrize("selector", [".tw-box-tools", ".tw-grip", ".tw-box-size", ".tw-box-reset"])
def test_the_handles_add_no_height_to_the_box(selector):
    """fitTxbx decides what overflows from the box's offsetHeight. A grip in the normal flow
    would make every box measure taller than its text, i.e. would break the overflow notice for
    the sake of a handle — so every part of the tools layer is absolutely positioned."""
    assert "position: absolute" in _css_rule(selector), (
        "%s is not absolutely positioned, so it adds height to the box" % selector)


def test_the_tools_layer_does_not_swallow_clicks_meant_for_the_text():
    """It covers the whole box so the grips can sit on its edges. Without pointer-events:none on
    the container, every click aimed at a paragraph would land on the overlay instead and the
    document would stop being editable.

    THE SECOND HALF NO LONGER MEANS WHAT IT USED TO SAY, so it does not claim it any more.
    `.tw-box-tools > *` still grants the pointer back, but as of 2026-08-20 `.tw-grip` takes it
    away again at rest and regains it on hover/focus — because an invisible grip was still being
    hit-tested, and PRICE's move grip sits over WORK's last line on Kyle's template. So the
    presence of this declaration is NOT what makes a grip draggable, and asserting that it is
    would be a lying test. What actually decides it is specificity plus source order between
    these two rules, resolved and asserted in tests/test_editor_overlap.py — including a
    mutation that reorders them without editing a single declaration."""
    assert "pointer-events: none" in _css_rule(".tw-box-tools")
    assert "pointer-events: auto" in _css_rule(".tw-box-tools > *"), (
        "the non-grip tools (Reset, Collapse, Fit to text) would stop being clickable")


# ── persistence, and the guard that keeps a stale id from moving a live box ──
def test_a_dragged_layout_is_saved_for_this_template(ran):
    p = ran["persist"]
    assert p["stored"] == {"3": {"w_pt": 432, "h_pt": 228.75}}
    assert p["keyed"] == ["epoxy:Direct"]
    assert p["meta"] == {"template_version": "TV1", "work_type": "epoxy", "audience": "Direct"}


def test_reopening_the_same_template_restores_the_layout(ran):
    assert ran["restoreSameVersion"] == [[3, {"w_pt": 432, "h_pt": 228.75}]]


def test_a_restored_box_mounts_at_its_saved_size(ran):
    """Loaded BEFORE the render, so the box does not appear at the template's geometry and jump a
    frame later."""
    m = ran["mountedRestored"]
    assert (m["left"], m["minHeight"], m["boxHPt"], m["moved"]) == ("100pt", "300pt", "300", True)


def test_a_stale_template_version_drops_the_saved_layout(ran):
    """A box id is a position in the backend's walk over one specific .docx. Re-annotate the
    template and the same id is a different box, so replaying it would resize a box the estimator
    never touched — in a customer-facing document, with nothing on screen to show it."""
    assert ran["restoreStaleVersion"] == []


def test_another_templates_layout_is_never_replayed(ran):
    """Work type and audience are what pick the FILE, so both belong in the key."""
    assert ran["restoreOtherTemplate"] == []
    assert ran["restoreOtherAudience"] == []


def test_switching_the_base_bid_and_coming_back_keeps_both_layouts(ran):
    """The bug the per-template store exists for, in its box form: an epoxy → polish → epoxy round
    trip used to throw the first template's edits away with no warning and no undo."""
    assert sorted(ran["roundTrip"]["keyed"]) == ["epoxy:Direct", "polish:Direct"]
    assert ran["roundTrip"]["epoxyBack"] == [[3, {"w_pt": 432, "h_pt": 228.75}]]


@pytest.mark.parametrize("case,expect", [
    ("restoreGarbage", []),
    ("restorePartlyGarbage", [[3, {"h_pt": 200}]]),
    ("restoreArrayStore", []),
    # The nastiest shape, and the reason the loader checks `typeof` rather than coercing:
    # Number(null) and Number("") are both 0, and 0 is a LEGAL position (the corner of the
    # sheet), so a coercing loader would read corruption as "this box belongs in the top-left"
    # and put it there — a wrong document that looks deliberate.
    ("restoreCoercibleGarbage", [[3, {"h_pt": 200}]]),
])
def test_a_garbled_store_reads_as_nothing_saved(ran, case, expect):
    """State is user data round-tripped through the draft store. A garbled entry must read as
    absent rather than break Proposal Review on load — and a partly garbled one must keep the
    fields that are usable rather than throw the whole box away."""
    assert ran[case] == expect


def test_a_saved_layout_still_ships_when_the_editor_never_loaded(ran):
    """The degraded path: the template fetch failed, so there is no live map to read. An earlier
    drag still has to reach the .docx, exactly as collectOverrides does for paragraph edits."""
    assert ran["fallbackNoEditor"] == {"3": {"h_pt": 300}}
    assert ran["fallbackFlatMeta"]["items"] == {"3": {"h_pt": 300}}
    assert ran["fallbackFlatWrongTemplate"] is None, (
        "the flat slot was offered to a different template, whose box ids do not match")
    assert ran["fallbackJunk"] == {}


# ── the wiring the harness cannot reach ──────────────────────────────────────
def test_the_payload_carries_box_overrides(ran):
    """Everything above is worthless if the dict never leaves the page. Done posts
    state.proposal_payload verbatim, so the key has to be in the object Continue builds.

    Matched as a LIVE line, not as a substring: `// box_overrides: boxOverridesOut,` contains the
    substring too, and commenting the line out is exactly how this would get broken."""
    i = JS.index("proposal_payload: {")
    block = JS[i:i + 6000]
    assert re.search(r"(?m)^\s*box_overrides: boxOverridesOut,\s*$", block), (
        "the generate payload does not carry box_overrides — the drag reaches the draft and never "
        "the document")


def test_the_view_files_rebuild_also_carries_the_layout():
    """done.js rebuilds a payload from raw state when `proposal_payload` is missing — the path
    "View files" re-generates an already-generated project through. Without the layout there, the
    second download would put the boxes back at the template's size and disagree with the first
    one the estimator already checked.

    The template_version rides along on purpose: an empty one means "legacy caller, apply
    unchanged", which is the wrong answer for box ids that may have shifted."""
    done = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")
    i = done.index("const payload = (pp && pp.values) ? pp : {")
    block = done[i:done.index("};", i)]
    assert re.search(r"(?m)^\s*box_overrides: ", block), (
        "the View-files rebuild drops the dragged box layout")
    assert "template_version:" in block, (
        "the rebuild sends a layout with no version, so a stale one cannot be dropped")


def test_both_writers_file_the_layout_under_this_template(ran):
    """The debounced save and Continue. Both must merge into the store AS IT IS NOW, not as it was
    when the page loaded, or the sibling template's layout disappears — the bug the keyed store was
    added for and did not actually prevent.

    This asserted `mergeOverrideEntry(state.box_overrides_all, …)` until 2026-08-13, i.e. it
    asserted the defect. `state` is a one-shot snapshot taken on line 2; `TW.setState` merges into a
    fresh read of localStorage and never writes back onto it, so a top-level key it replaces is
    frozen for the whole visit. Merging onto the frozen value REPLACED the store with a single-key
    object and dropped the other template's entry. `liveKey()` re-reads the stored blob, and
    `test_a_template_round_trip_keeps_each_layout` is the behavioural half of this claim — it now
    runs against the page's real binding, where it used to run against a friendlier one."""
    for anchor in ("function schedulePersistOverrides()",
                   "const boxOverridesOut = collectBoxOverrides();"):
        i = JS.index(anchor)
        block = JS[i:i + 2500]
        assert "box_overrides_all" in block, "%s does not file the box layout" % anchor
        assert re.search(r'mergeOverrideEntry\(\s*liveKey\("box_overrides_all"\),', block), (
            "%s merges onto the page's load-time snapshot instead of the live store" % anchor)
    # And the same for the paragraph edits, which had the identical flaw and cost typed text.
    i = JS.index("function schedulePersistOverrides()")
    assert re.search(r'mergeOverrideEntry\(\s*liveKey\("paragraph_overrides_all"\),',
                     JS[i:i + 2500]), "the paragraph store is still merged onto the snapshot"
    assert not re.search(r"state\.(box|paragraph)_overrides", JS), (
        "an override store is read off the load-time snapshot again: %s"
        % re.findall(r"state\.(?:box|paragraph)_overrides\w*", JS))


def test_the_layout_is_loaded_before_the_render(ran):
    """Order matters twice: after templateVersion (the guard reads it) and before
    renderPositioned (so the box is created at its saved size)."""
    i_ver = JS.index('templateVersion = String(j.template_version || "")')
    # Searched FROM the version assignment, so this finds the call inside initDocumentEditor and
    # not the function's own definition further up the file.
    i_load = JS.index("loadBoxOverrides(wt, audience);", i_ver)
    i_render = JS.index("if (hasBoxes) renderPositioned(geo, tokens)")
    assert i_ver < i_load < i_render


def test_the_limits_come_from_the_server_rather_than_being_re_derived(ran):
    """Two independent subtractions of the same margins is how a handle ends up offering a size
    the server refuses. max_box is stated in the payload for exactly this reason; re-deriving it
    is only the fallback for a browser holding a pre-v4 cached response."""
    i = JS.index("boxLimits = {")
    block = JS[i - 600:i + 500]
    assert "page.max_box" in block
    assert "Number(maxBox.w_pt) ||" in block, "max_box is not preferred over the derivation"
