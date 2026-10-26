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


def test_the_column_sits_in_the_middle_of_what_is_left_not_jammed_against_the_rail(intake_css):
    """Reserving the lane and pinning the column to the near edge of it are two different things.

    Hanz, on a screenshot: *"move this intake form a little bit to the left please."* The test above
    only says the rail GETS its 282px, and `margin-left:auto` satisfied that while dumping every
    spare pixel on the LEFT -- so the form pressed against the panel with the whole gutter behind
    it. At a 1400px body the column started at x=238 with 238 empty pixels to its left and 16 to
    its right. This asserts the distribution as geometry, and it asserts the thing that was
    actually wrong: the left edge must be strictly further left than `margin-left:auto` put it, at
    every body width this query covers.
    """
    rule = re.search(r"\.container\{margin-left:([^;]+);margin-right:(\d+)px\}", intake_css)
    assert rule, "the floating .container rule is gone"
    left_expr, rail = rule.group(1), int(rule.group(2))
    assert "auto" not in left_expr, (
        "margin-left:auto is back. It reserves the lane and then pins the column to the near edge "
        "of it, which is the layout Hanz asked to move left.")

    calc = re.search(r"max\(0px,calc\(\(100% - (\d+)px - (\d+)px\) / 2\)\)", left_expr)
    assert calc, f"the centring calc is not recognisable, got: {left_expr}"
    assert int(calc.group(1)) == rail, (
        f"the calc subtracts {calc.group(1)}px but the reservation holds {rail}px -- if these two "
        "drift apart the column is centred against a lane that is not the one the rail uses")
    col = int(calc.group(2))

    # The column figure is not a constant of this page: .container's max-width lives in the shared
    # stylesheet, so hard-coding 880 here would let a change there re-open the overlap silently.
    shared = re.search(r"\.container \{[^}]*?max-width:\s*(\d+)px",
                       (FRONTEND / "styles.css").read_text(encoding="utf-8"), re.S)
    assert shared and int(shared.group(1)) == col, (
        f"the calc centres a {col}px column but .container is "
        f"{shared.group(1) if shared else '?'}px wide in styles.css")

    # BODY is the containing block and the left nav eats into it -- the mistake the 21px paragraph
    # at the top of this file records. So evaluate at body widths that actually occur, not at
    # viewport widths.
    for body in (1160, 1400, 1510, 1750):
        centred = max(0, (body - rail - col) // 2)
        pinned = max(0, body - rail - col)       # what margin-left:auto produced
        width = min(col, body - rail - centred)  # margin-right squeezes it at the narrow end
        assert centred + width <= body - rail, (
            f"at a {body}px body the column runs to x={centred + width}, into the rail's lane "
            f"which starts at x={body - rail}")
        if pinned > 0:
            assert centred < pinned, (
                f"at a {body}px body the column starts at x={centred}, no further left than the "
                f"x={pinned} margin-left:auto already gave it")


def _media_blocks(text, query):
    """The bodies of every `@media (<query>) {` block in `text`."""
    return [_block_at(text, m.end() - 1)
            for m in re.finditer(r"@media \(" + query + r"\)\s*\{", text)]


def test_the_step_three_rail_keeps_its_lane_only_where_there_is_room_for_one():
    """The reference, asserted so "match the step-3 widget" stays a fact and not a memory.

    Since 2026-10-27 the rail floats at EVERY width (it used to drop into the flow below 1400px and
    become permanent chrome above the document, because only .word-canvas scrolls). Its 272px lane
    on `:has(#options-panel:not([hidden]))` is reserved from 1401px up and nowhere else: below that
    the rail sits over the page and collapses instead. 1400 is still the cheat sheet's breakpoint
    above because it is where the rail's lane ends.
    """
    css = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
    lane = r"#options-panel:not\(\[hidden\]\)\) \.word-canvas \{\s*padding-right: 272px"
    wide = _media_blocks(css, r"min-width:\s*1401px")
    assert len(wide) == 1 and re.search(lane, wide[0]), (
        "the step-3 rail must reserve its 272px lane inside one @media (min-width: 1401px) block")
    assert len(re.findall(lane, css)) == 1, "a second, unconditional copy of the lane came back"
    assert not re.search(r"@media \(max-width:\s*1400px\)", css), (
        "the page grew a narrow-screen block again; the rail no longer changes shape below 1400px")


# ══ TW.floatPanel: the one copy of the drag / remember / restore logic ══════════
# The step-3 rail and the cheat sheet each carried their own copy (the cheat sheet was built as a
# copy of the rail, and the restore clamp was missing from both for a release). The v2 estimate's
# Sheets panel is the third panel that moves, so the logic is one helper in shared.js and the two
# initialisers above are thin calls into it. The sections above prove each caller still behaves as
# before; these call the helper directly, under a key and class names nothing else uses.
SHEETS_W = 256                     # the width the v2 Sheets panel will have
PROBE = "tw_probe_pos"


def test_the_helper_restores_a_far_away_position_onto_the_screen(ran):
    """3400x2600 saved on a wide monitor, reopened on a 1750x1125 window: back on screen, against
    THIS panel's own rendered width, and the same `right: auto` the callers always wrote."""
    f = ran["float"]
    assert f["restoreFar"] == {"left": WIN_W - SHEETS_W - 4, "top": WIN_H - 40, "right": "auto"}


def test_the_helper_leaves_a_position_that_fits_alone_and_stands_down_in_the_flow(ran):
    f = ran["float"]
    assert f["restoreLegal"] == {"left": 600, "top": 300, "right": "auto"}
    # Below the breakpoint the CSS returns the panel to the flow: left/top are inert and the width
    # is the whole column, so the restore must not run at all.
    assert f["restoreInFlow"] == {"left": "", "top": "", "right": "16px"}


def test_the_helper_drags_clamps_and_saves_under_its_own_key_only(ran):
    """The whole gesture on a helper that nothing else calls this way: the dragging class is on
    during the drag and off after it, the panel follows the pointer while it fits, stops at the same
    bounds the restore uses when hurled, and what is saved is the clamped spot under the key it was
    given and no other. A fresh page load then opens exactly there."""
    d = ran["float"]["drag"]
    assert d["classDuring"] is True and d["classAfter"] is False
    assert d["followed"] == {"left": 1100, "top": 250, "right": "auto"}      # +100 right, +50 down
    assert d["clamped"] == {"left": WIN_W - SHEETS_W - 4, "top": WIN_H - 40, "right": "auto"}
    assert d["saved"] == {"left": WIN_W - SHEETS_W - 4, "top": WIN_H - 40}
    assert d["keys"] == [PROBE]
    assert ran["float"]["reloaded"] == {
        "left": WIN_W - SHEETS_W - 4, "top": WIN_H - 40, "right": "auto"}


def test_a_press_that_is_not_on_the_header_moves_nothing(ran):
    """The panel is full of inputs and buttons. Only the header drags; pressing anything else must
    not start a drag, add the class, move the panel or write a position."""
    o = ran["float"]["offHandle"]
    assert o["at"] == {"left": 1000, "top": 200, "right": "16px"}
    assert o["classes"] == []
    assert o["keys"] == []


def test_a_cancelled_drag_ends_the_same_way_a_released_one_does(ran):
    c = ran["float"]["cancel"]
    assert c["classAfter"] is False
    assert c["saved"] == {"left": 1050, "top": 220}


def test_without_a_key_the_panel_moves_but_remembers_nothing(ran):
    k = ran["float"]["noKey"]
    assert k["restored"] == {"left": "", "top": "", "right": "16px"}, (
        "a panel with no key read somebody else's saved position")
    assert k["moved"] == {"left": 1100, "top": 250, "right": "auto"}
    assert k["keys"] == [PROBE]
    assert k["stored"] == '{"left":600,"top":300}', "a panel with no key wrote a position"


def test_a_corrupt_or_blocked_store_never_breaks_the_panel(ran):
    """A wiped, corrupt or blocked localStorage means it opens where the CSS put it, and it can
    still be moved. Nothing may throw out of the page's own init."""
    corrupt = ran["float"]["corrupt"]
    assert corrupt == {"threw": False, "left": "", "top": "", "right": "16px"}
    blocked = ran["float"]["blocked"]
    assert blocked["threw"] is False
    assert blocked["moved"] == {"left": 1100, "top": 250, "right": "auto"}
    assert blocked["classAfter"] is False


def test_a_panel_not_laid_out_yet_is_clamped_against_its_declared_width(ran):
    """offsetWidth is 0 until the panel is laid out. The width the caller declared stands in, and
    250 (clampPanelPos's own) when none is, so the lane is never computed from the full window."""
    u = ran["float"]["unlaidOut"]
    assert u["declared"] == WIN_W - 300 - 4
    assert u["byDefault"] == WIN_W - 250 - 4


def test_a_panel_not_laid_out_yet_is_restored_against_its_declared_width_too(ran):
    """The restore is where a panel is most likely not laid out (the rail is hidden at init), and it
    used to ignore `width` and clamp against clampPanelPos's own 250: a 300px panel saved far right
    came back 46px past the edge while its drag clamped it correctly. Same width, both paths."""
    u = ran["float"]["unlaidOutRestore"]
    assert u["declared"] == {"left": WIN_W - 300 - 4, "top": 100, "right": "auto"}
    assert u["byDefault"] == {"left": WIN_W - 250 - 4, "top": 100, "right": "auto"}


def test_two_panels_on_one_page_never_share_a_position(ran):
    """One shared key would teleport each panel to wherever the other was last left. Each restores
    from its own key, and dragging one leaves the other's saved spot untouched."""
    t = ran["float"]["twoPanels"]
    assert t["restored"]["a"] == {"left": 100, "top": 120, "right": "auto"}
    assert t["restored"]["b"] == {"left": 900, "top": 700, "right": "auto"}
    assert t["a"] == {"left": 200, "top": 220}
    assert t["b"] == {"left": 900, "top": 700}


# ── each page caller hands the helper its own key, classes and width ──────────────
def test_the_step_three_rail_drags_with_its_own_key_and_class(ran):
    """Until the helper existed this rail's DRAG was never run by a test, only its restore. Its key
    is tw_opts_pos and its class op-dragging; a caller that sent the cheat sheet's, or dropped one,
    fails here and nowhere above."""
    d = ran["optsDrag"]
    assert d["classDuring"] is True and d["classAfter"] is False
    assert d["clamped"] == {"left": WIN_W - OPTS_W - 4, "top": WIN_H - 40, "right": "auto"}, (
        "the rail's declared width (240) did not reach the clamp")
    assert d["saved"] == {"left": WIN_W - OPTS_W - 4, "top": WIN_H - 40}
    assert d["keys"] == ["tw_opts_pos"]


def test_the_cheat_sheet_keeps_its_own_declared_width(ran):
    """Its width (250) differs from the rail's (240) and only shows before layout."""
    assert ran["cheatUnlaidOut"]["left"] == WIN_W - CHEAT_W - 4


def test_each_callers_restore_uses_its_own_declared_width_before_layout(ran):
    """The rail is hidden until it has content, so its restore runs with offsetWidth 0. It clamps to
    its own 240 (what its drag uses), not the helper's 250: restoring a far-right position puts it
    at the same last legal pixel the drag could have left it on. The cheat sheet declares 250, so
    for it nothing moves."""
    u = ran["unlaidOutRestore"]
    assert u["rail"] == WIN_W - OPTS_W - 4
    assert u["cheat"] == WIN_W - CHEAT_W - 4


# ══ ALWAYS FLOATING: resize re-clamp and collapse (2026-10-27) ══════════════════
# The rail no longer drops into the flow below 1400px, so two things a flowed panel never needed:
# a window narrowed after the page opened must not strand its header off screen, and on a narrow
# screen, where it sits over the page, it must fold to its header.
def test_narrowing_the_window_pulls_a_moved_rail_back_and_widening_returns_it(ran):
    """Through the rail's own initialiser: restored at (1400, 900) on 1750x1125, narrowed to
    1100x700, widened back. The re-clamp starts from where the estimator PUT it, so the second
    resize gives their spot back, and a resize is never saved as a new position."""
    r = ran["resize"]["rail"]
    assert r["listeners"] == 1, "the rail's initialiser bound no resize listener"
    assert r["restored"] == {"left": 1400, "top": 900, "right": "auto"}
    assert r["narrowed"] == {"left": 1100 - OPTS_W - 4, "top": 700 - 40, "right": "auto"}
    assert r["widened"] == {"left": 1400, "top": 900, "right": "auto"}
    assert r["saved"] == {"left": 1400, "top": 900}, "a resize overwrote the remembered position"


def test_a_dragged_panel_re_clamps_from_where_it_was_dropped(ran):
    d = ran["resize"]["dragged"]
    assert d["dropped"] == {"left": 1400, "top": 600, "right": "auto"}
    assert d["narrowed"] == {"left": 1000 - SHEETS_W - 4, "top": 500 - 40, "right": "auto"}
    assert d["widened"] == {"left": 1400, "top": 600, "right": "auto"}
    assert d["saved"] == {"left": 1400, "top": 600}


def test_a_resize_leaves_an_unmoved_or_flowed_panel_to_the_css(ran):
    """Never moved: `right: 16px` keeps it on screen at any width, so the resize writes nothing.
    In the flow (the cheat sheet below its breakpoint): left/top are inert, so it is not touched."""
    r = ran["resize"]
    assert r["neverMoved"] == {"left": "", "top": "", "right": "16px", "keys": []}
    assert r["inFlow"] == {"left": "", "top": "", "right": "16px"}


def test_the_rail_collapses_to_its_header_and_remembers_it(ran):
    c = ran["collapse"]["rail"]
    assert c["start"] is False, "a first visit must open the panel expanded"
    assert c["first"] == {"collapsed": True, "stored": "1", "aria": "false"}
    assert c["second"] == {"collapsed": False, "stored": "0", "aria": "true"}
    assert c["headerClick"] is False, "a click on the header (not the button) must not fold it"
    assert ran["collapse"]["reopened"] is True, "left collapsed, the page must open it collapsed"


def test_a_press_on_the_collapse_button_is_not_a_drag(ran):
    """The button sits inside the drag header. Started as a drag, the pointer capture would take the
    release away from the button and the panel would jump with the cursor."""
    c = ran["collapse"]["rail"]
    assert c["classOnPress"] is False
    assert c["afterPress"] == {"left": 1000, "top": 200, "right": "16px"}
    assert c["posSaved"] is None


def test_collapse_is_opt_in_and_survives_a_blocked_store(ran):
    c = ran["collapse"]
    assert c["noKey"] == {"boundClick": False}, "a panel with no collapseKey grew a collapse"
    assert c["blocked"] == {"threw": False, "collapsed": True}


# ── the rail's CSS moved into the shared stylesheet, rule for rule ────────────────
def _block_at(text, open_at):
    """The text between the brace at `open_at` and its match. Counts braces only, so a comment
    holding a stray one would unbalance it; the media block read here holds none."""
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1:i]
    raise AssertionError("unbalanced braces in styles.css")


def _norm(decls):
    return " ".join(decls.split())


# ── reading selectors out of a page, for the "no second copy" guard ───────────────
# Walks by position. A single-pass regex over markup or comments is the shape CodeQL calls
# incomplete sanitisation, and a hand-rolled walk reads no worse for a sheet this plain.
def _drop_css_comments(css):
    out, at = [], 0
    while True:
        start = css.find("/*", at)
        if start == -1:
            out.append(css[at:])
            return "".join(out)
        out.append(css[at:start])
        end = css.find("*/", start + 2)
        if end == -1:
            return "".join(out)
        at = end + 2


def _style_text(html):
    """The text of every <style> element in the page, joined."""
    parts, at = [], 0
    while True:
        start = html.find("<style", at)
        if start == -1:
            return "\n".join(parts)
        after = html[start + len("<style"):start + len("<style") + 1]
        if after and not (after == ">" or after.isspace()):
            at = start + 1                      # <styles...>, not a style element
            continue
        gt = html.find(">", start)
        end = html.find("</style>", gt)
        if gt == -1 or end == -1:
            return "\n".join(parts)
        parts.append(html[gt + 1:end])
        at = end + len("</style>")


def _split_top_level_commas(text):
    parts, depth, buf = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _selector_entries(css):
    """Every selector in a sheet, one per comma-separated entry, at any @media depth. A prelude is
    the text since the last `{`, `}` or `;`; at-rule preludes are not selectors and are skipped, but
    the rules inside them are read as the preludes they are."""
    out, buf = [], []
    for ch in _drop_css_comments(css):
        if ch == "{":
            prelude = "".join(buf).strip()
            if prelude and not prelude.startswith("@"):
                out.extend(_split_top_level_commas(prelude))
            buf = []
        elif ch in "};":
            buf = []
        else:
            buf.append(ch)
    return out


def _without_has(selector):
    """The selector with its `:has( ... )` groups taken out. `:has(#options-panel) .word-canvas`
    styles the CANVAS and merely reads the panel; it is not a rule about the panel."""
    out, at = [], 0
    while True:
        start = selector.find(":has(", at)
        if start == -1:
            out.append(selector[at:])
            return "".join(out)
        out.append(selector[at:start])
        depth, i = 0, start + len(":has")
        while i < len(selector):
            if selector[i] == "(":
                depth += 1
            elif selector[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        at = i + 1


def _mentions(selector, name):
    """`name` as a whole word in the selector: `.op-row`, `#options-panel`, `[id=options-panel]`
    match, `.my-op-row` does not."""
    at = 0
    while True:
        i = selector.find(name, at)
        if i == -1:
            return False
        before = selector[i - 1] if i else " "
        end = i + len(name)
        after = selector[end] if end < len(selector) else " "
        if not (before.isalnum() or before in "_-") and not (after.isalnum() or after in "_-"):
            return True
        at = i + 1


def _panel_owned_names():
    """The class and id names that belong to the floating panel: every one that styles.css only ever
    uses in a selector that also names `.options-panel`. Read from the stylesheet rather than listed
    here, so a class added to the panel's rules is covered without anyone remembering this file."""
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    inside, outside = set(), set()
    for entry in _selector_entries(css):
        names = set(re.findall(r"[.#]([A-Za-z_][\w-]*)", _without_has(entry)))
        (inside if "options-panel" in names else outside).update(names)
    return (inside - outside) | {"options-panel"}


def _panel_forks_in(page):
    """Every selector in the page's own <style> that is a rule about the panel, however it is
    spelled: `#options-panel`, `body .options-panel`, `aside.options-panel`, a bare `.op-drag`."""
    owned = _panel_owned_names()
    forks = []
    for entry in _selector_entries(_style_text(page)):
        bare = _without_has(entry)
        hit = sorted(n for n in owned if _mentions(bare, n))
        if hit:
            forks.append((entry, hit))
    return forks


def test_the_options_panel_rules_live_in_the_shared_stylesheet():
    """The v2 estimate's Sheets panel is `.options-panel` too, so the look moved to styles.css.
    Asserted as the declarations that make it a floating, bounded, draggable widget rather than as a
    snapshot of the file: a headless run has no layout engine, so the rules are read as text."""
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")

    base = re.search(r"(?m)^\.options-panel \{([^}]*)\}", css)
    assert base, "the floating base rule is not in styles.css"
    for decl in ("position: fixed", "right: 16px", "top: 150px", "width: 240px",
                 "max-height: calc(100vh - 170px)", "overflow-y: auto", "z-index: 40"):
        assert decl in _norm(base.group(1)), f".options-panel lost `{decl}`"

    drag = re.search(r"(?m)^\.options-panel \.op-drag \{([^}]*)\}", css)
    assert drag, "the drag header rule is not in styles.css"
    for decl in ("cursor: move", "user-select: none", "position: sticky", "top: -12px"):
        assert decl in _norm(drag.group(1)), f".op-drag lost `{decl}`"
    assert re.search(r"(?m)^\.options-panel\.op-dragging \{", css), "the dragging look is gone"

    # The rest of the rail's own rules came with it.
    for sel in (".options-panel h3", ".options-panel .op-hint", ".options-panel .pr-inert-warn",
                ".options-panel .op-row", ".options-panel .op-name", ".options-panel .op-price",
                ".options-panel label", ".options-panel .op-notes", ".options-panel select",
                ".options-panel .pr-baserow", ".options-panel .pr-optsub",
                ".options-panel .pr-addsys-btn"):
        assert re.search(r"(?m)^" + re.escape(sel) + r"\s*\{", css), f"{sel} is not in styles.css"


def test_the_panel_is_floating_at_every_width():
    """THE OLD BREAKPOINT IS GONE (2026-10-27). Below 1400px the panel used to drop into the flow
    with `position: static`, and because only .word-canvas scrolls on step 3 it became permanent
    chrome at the top of the page, pushing the proposal down. No rule about the panel, at any
    @media depth, may take it out of `position: fixed` again. The fields panel keeps its own 1400px
    block in the same file, which is why this reads every selector rather than one block."""
    css = _drop_css_comments((FRONTEND / "styles.css").read_text(encoding="utf-8"))

    def styles_the_panel_itself(selector):
        # The SUBJECT of the selector (its last compound) is the panel: `.options-panel.collapsed`
        # is, `.options-panel .op-drag` (the sticky header) is not.
        bare = re.sub(r":not\([^)]*\)", "", _without_has(selector)).strip()
        return _mentions(re.split(r"[\s>+~]+", bare)[-1], "options-panel")

    seen = 0
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, decls = m.group(1).strip(), _norm(m.group(2))
        if not any(styles_the_panel_itself(s) for s in _split_top_level_commas(selectors)):
            continue
        pos = re.search(r"(?<![-\w])position:\s*([\w-]+)", decls)
        if pos:
            seen += 1
            assert pos.group(1) == "fixed", (
                f"`{selectors}` sets position: {pos.group(1)} on the panel; it must float")
    assert seen >= 1, "found no rule positioning the panel at all -- the scan is reading nothing"
    for block in _media_blocks(css, r"max-width:\s*\d+px"):
        assert not re.search(r"(?m)^\s*\.options-panel\s*\{", block), (
            "a narrow-screen block restyles .options-panel again; the panel no longer changes shape")


def test_the_collapsed_panel_is_its_header_pill_alone():
    """On a narrow screen the floating rail sits over the page, so it folds to its header. The CSS
    half of that (TW.floatPanel toggles the class, run in the harness): the button is styled in the
    shared sheet, and `.collapsed` hides every child but the header and drops the scroll bound."""
    css = (FRONTEND / "styles.css").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\.options-panel \.op-collapse \{", css), "the collapse button has no rule"
    hide = re.search(r"(?m)^\.options-panel\.collapsed > :not\(\.op-drag\) \{([^}]*)\}", css)
    assert hide and "display: none" in _norm(hide.group(1)), (
        "a collapsed panel must hide everything but its header")
    pill = re.search(r"(?m)^\.options-panel\.collapsed \{([^}]*)\}", css)
    assert pill, "the collapsed panel has no rule"
    for decl in ("width: auto", "max-height: none", "padding: 0"):
        assert decl in _norm(pill.group(1)), f"the collapsed pill lost `{decl}`"
    # the glyph flips, so the button says which way it will go
    assert re.search(r"(?m)^\.options-panel \.op-collapse::before \{", css)
    assert re.search(r"(?m)^\.options-panel\.collapsed \.op-collapse::before \{", css)


def test_the_proposal_page_no_longer_carries_a_second_copy_of_the_panel_rules():
    """A copy left behind in the page would quietly fork the look the day someone edits one."""
    page = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
    # Not "no selector that STARTS with .options-panel": a fork spelled `#options-panel`,
    # `body .options-panel` or a bare `.op-drag` loads after styles.css and wins a tie just the same.
    forks = _panel_forks_in(page)
    assert forks == [], (
        "proposal-review.html's own <style> still has rules about the floating panel; they belong "
        f"in styles.css: {forks}")
    # What stays is the part that is the page's own: the canvas padding that keeps the document
    # clear of the rail, because .word-canvas is this page's. Reserved from 1401px up only (see
    # test_the_step_three_rail_keeps_its_lane_only_where_there_is_room_for_one), so no
    # `padding-right: 0` undo rule is needed any more and none should come back.
    assert re.search(r"#options-panel:not\(\[hidden\]\)\) \.word-canvas \{\s*padding-right: 272px",
                     page)
    assert not re.search(r"#options-panel:not\(\[hidden\]\)\) \.word-canvas \{\s*padding-right: 0",
                         page), "an undo rule for the lane came back; the lane is media-gated now"


# A guard that finds nothing proves nothing until something it must catch has been put in front of
# it: each of these is a way to fork the panel's look that the old, start-of-selector check missed.
FORKED_PANEL_RULES = [
    "#options-panel { top: 0; width: 300px; }",
    "body .options-panel { position: absolute; }",
    "aside.options-panel { width: 300px; }",
    "[id=options-panel] { width: 300px; }",
    ".op-drag { cursor: pointer; }",
    ".options-panel .op-row, .elsewhere { padding: 0; }",
    ".elsewhere, .options-panel { top: 0; }",
    "@media (max-width: 1400px) { .options-panel { position: absolute; } }",
    "body:has(.x) .op-row { padding: 0; }",           # a :has() elsewhere does not excuse it
]


@pytest.mark.parametrize("fork", FORKED_PANEL_RULES)
def test_the_second_copy_guard_catches_a_fork_under_any_selector(fork):
    page = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
    assert _panel_forks_in(page) == []                # the page as shipped is clean
    forked = page.replace("</style>", fork + "\n</style>", 1)
    assert forked != page
    assert _panel_forks_in(forked), f"the guard let this fork through: {fork}"


@pytest.mark.parametrize("rule", [
    # reads the panel, styles the canvas: exactly what the page keeps
    ".word-canvas:has(#options-panel:not([hidden])) { padding-right: 9px; }",
    # a comment is not a rule
    "/* .options-panel { width: 1px } and #options-panel { top: 0 } */",
    # a different element that merely shares a prefix
    ".my-op-row { padding: 0; }",
])
def test_the_second_copy_guard_leaves_the_pages_own_rules_alone(rule):
    page = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
    forked = page.replace("</style>", rule + "\n</style>", 1)
    assert forked != page
    assert _panel_forks_in(forked) == [], rule


def test_the_panels_own_names_are_read_from_the_stylesheet_not_guessed():
    """If this came back empty the guard above would pass on every page for ever."""
    owned = _panel_owned_names()
    assert {"options-panel", "op-drag", "op-dragging", "op-row", "op-name"} <= owned
    # `.op-hint` is also the fields panel's class, so it is not the floating panel's to own: a page
    # that styles it for the fields panel must not be accused of forking this one.
    assert "op-hint" not in owned


@pytest.mark.parametrize("name", ["proposal-review.html", "estimate-review.html"])
def test_each_page_that_floats_the_panel_loads_the_shared_stylesheet_first(name):
    """The panel's look is only in styles.css now. The step-3 page uses it today and the v2
    estimate page will, so both must load it, and before their own <style> so a page rule still
    wins a tie as it always has."""
    page = (FRONTEND / name).read_text(encoding="utf-8")
    link = page.find('<link rel="stylesheet" href="/styles.css"')
    inline = page.find("<style")
    assert link != -1, f"{name} does not load /styles.css"
    assert inline == -1 or link < inline, f"{name} loads /styles.css after its own <style>"


def test_the_shared_helper_is_exported_for_every_page():
    """Pages reach it as TW.floatPanel; the page initialisers keep their own names."""
    shared = (FRONTEND / "shared.js").read_text(encoding="utf-8")
    assert re.search(r"window\.TW = \{[^}]*\bfloatPanel,", shared, re.S)
    assert "function initCheatDrag()" in (FRONTEND / "js" / "polish-verbal.js").read_text(
        encoding="utf-8")
    assert "(function initOptionsPanelDrag()" in (
        FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")
