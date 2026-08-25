"""The proposal editor's formatting bar, moved to the top and made static.

Kyle, 2026-08-24:
  "Can we move this editable box on top as well but keep it static like a ribbon in a word
   document."

WHAT THE MOVE ACTUALLY BREAKS, because the fix only makes sense against it.

The bar used to be `position: fixed`, appended to `document.body`, and placed on every focusin
from the focused paragraph's `getBoundingClientRect()`. Moving it into the page chrome is the
easy half — the coordinates simply stop being needed, and a normal-flow row between
`.word-ribbon` and `.word-canvas` is pinned for free because `body.word-app` is a flex column
whose canvas is the scroller.

THE HARD HALF IS THAT A RIBBON DOES NOT KNOW ITS TARGET. A bar placed beside a paragraph knew
which paragraph it was for, and it stopped existing the moment that paragraph lost focus:
`fmtBlock` was assigned in `showFmtBar` and nulled in `hideFmtBar`, so "visible" and "has a
target" were ONE state and the `!fmtBlock` guard on every button never fired in practice. Leave
that wiring alone under a ribbon and you ship a permanently visible row of buttons that silently
does nothing.

AND THE FAILURE WOULD NOT EVEN BE SILENT-INERT — IT WOULD BE SILENT-WRONG. When the live
selection is not inside the block, `selectionRange` returns null and `selectionFormat` widens the
range to the whole paragraph (its collapsed-caret rule: a caret means "this paragraph"). Beside
the caret that path was rare. From a ribbon at the top of the page it is what happens every time
focus went somewhere else first — the Tax select, the pricing rail, the ribbon's own size
dropdown — and the result is a customer-facing paragraph bolded end to end with nothing on screen
saying so. So the ribbon remembers two things: `fmtBlock`, the last paragraph that had focus, and
`fmtRange`, the last selection that was genuinely inside it.

WHAT WAS DECIDED, AND WHY.
  * INERT, NOT GONE, when there is nothing to act on — Word's own behaviour, and the only one
    consistent with the request: a toolbar that disappears is the floating bar again under a
    different name. `disabled` on every control, not merely a dimming class, because a dimmed
    button is still a live button (this repo has already shipped an `opacity: 0` element that went
    on stealing the click underneath it).
  * THE TARGET SURVIVES FOCUSOUT, so the `focusout` listener that hid the bar is deleted outright
    — and the paragraph itself now carries `.tw-fmt-target`, because a ribbon cannot say which
    paragraph it is aimed at by being next to it.
  * THE TARGET IS DROPPED when focus lands on a non-block editable (a `.tw-line-edit` price line
    is a different override channel that run formatting cannot reach) and when the remembered
    block leaves the DOM (`clearDocSurface` destroys every paragraph on a template reload).
  * THE LOCKED TERMS CLAUSE loses its paragraph controls to `visibility: hidden` rather than
    `display: none`. The refusal is unchanged and deliberate — un-bulleting a numbered clause
    renumbers the contract — but a row that reflowed each time the caret crossed from a WORK row
    to a clause would not be static, and Reset would jump out from under the pointer.

WHY THE FRONTEND HALF RUNS UNDER NODE. Every claim above is a behaviour of several functions
agreeing: which of two ranges a press landed on, whether the target survived a blur, whether a
press after a template reload does nothing. A source-text assertion sees none of it, and this repo
has already paid for that lesson — on 2026-08-12 `STAGE_CREATED` shipped unbound with every source
assertion green and took the production board down. `js/fmt-ribbon-harness.js` lifts the shipped
functions and the shipped focusin/selectionchange listeners out of proposal-review.js, gives them
the smallest DOM they touch, and fires real events at them.

THE CSS HALF IS A SOURCE READ, and has to be: the cascade is the thing under test and no stubbed
DOM applies a stylesheet. Both traps this repo keeps hitting are invisible to an assertion about
declaration order — specificity beats source order, and a class `display` rule beats the `hidden`
attribute — so where a rule has to win, the specificity is computed here and compared.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "fmt-ribbon-harness.js"
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")
PAGE = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
JS = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")
# The page's CODE, with comments removed. The comments in this codebase quote the history that made
# each change necessary, so `bar.style.display` and `hideFmtBar` are still written in prose on
# purpose — a probe that could not tell prose from code would report both as still shipping.
# LINE comments first, THEN block comments -- and the order is load-bearing, not tidiness.
#
# Done the other way round, a /* sitting inside a // comment reads as a block-comment OPENER
# and pairs with the next real terminator further down the file, deleting everything between
# them. This file has exactly that: proposal-review.js explains that an <img> "can't carry the
# bearer token through the /api/* gate" -- and that path contains the opener. The moment a new
# block comment was added below it, the stray found a partner and 590 lines of real code
# vanished from JS_CODE, which made an unrelated test claim the zoom transform had been
# deleted. Stripping the line comments first removes the stray before it can pair with
# anything.
JS_CODE = re.sub(r"/\*.*?\*/", "",
                 re.sub(r"(^|[^:\"'`\\])//[^\n]*", r"\1", JS), flags=re.S)


# ══ the ribbon, executed ══════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_ribbon_is_on_screen_before_anything_is_focused(ran):
    """The request in one assertion. The old bar did not exist until the first focusin and was
    `display: none` until it was placed; this one is built at load, in the page chrome, and never
    hidden — so there is nothing for the estimator to make appear."""
    load = ran["onLoad"]
    assert load["placement"]["hostId"] == "fmt-ribbon", (
        "the bar is not mounted in the ribbon row — it fell back to document.body")
    assert load["bar"]["inlineDisplay"] == "", "something still hides the bar with style.display"
    assert load["bar"]["role"] == "toolbar"
    assert load["bar"]["ariaLabel"] == "Text formatting"


def test_with_nothing_selected_the_ribbon_is_inert_rather_than_absent(ran):
    """Word greys its ribbon out; it does not take it away. Every control is REALLY disabled, not
    just dimmed — a dimmed-but-live button is how an element nobody can see goes on stealing the
    click (see test_opacity_zero_is_still_clickable's lesson in this suite)."""
    load = ran["onLoad"]
    assert load["target"] is None
    assert load["bar"]["idle"] is True, "the idle class is missing, so nothing looks greyed out"
    for name in ("bold", "italic", "reset", "size", "bullet", "outdent", "indent"):
        assert load["bar"]["controls"][name]["disabled"] is True, name


def test_focusing_a_paragraph_wakes_the_ribbon_and_marks_that_paragraph(ran):
    """A bar beside the caret answered "which paragraph?" by being there. A ribbon has to say so,
    and exactly one paragraph may say it."""
    f = ran["focused"]
    assert f["bar"]["idle"] is False
    assert f["target"] == "116"
    assert f["marked"] is True, "the paragraph the ribbon is aimed at is unmarked"
    assert f["otherMarked"] is False
    for name in ("bold", "italic", "reset", "size"):
        assert f["bar"]["controls"][name]["disabled"] is False, name
    assert ran["movedTarget"]["target"] == "115"
    assert ran["movedTarget"]["marks"] == [True, False], (
        "the mark did not move, so two paragraphs claim to be the ribbon's target")


def test_the_ribbon_is_never_placed_from_the_block(ran):
    """The deleted half. `getBoundingClientRect` calls are COUNTED because "the positioning is
    gone" is the sort of claim a grep for `style.top` passes while the measurement is still being
    taken — and the measurement is what made the old bar `position: fixed` in the first place."""
    assert ran["focused"]["rectCalls"] == 0
    assert ran["finalRectCalls"] == [], (
        "something still measures an element to place the ribbon: %r" % ran["finalRectCalls"])
    final = ran["finalBar"]
    assert final["inlineTop"] == "" and final["inlineLeft"] == "", (
        "the ribbon is still being positioned with inline coordinates")


def test_focus_leaving_the_paragraph_changes_nothing(ran):
    """The behaviour Kyle asked for, stated as the thing that used to happen instead. A real
    `focusout` is fired at the block with the Tax select as `relatedTarget` — the old handler's
    exact trigger — and the ribbon keeps its target, its mark and its buttons."""
    after = ran["blurThenBold"]["afterBlur"]
    assert after["target"] == "116", "the ribbon forgot its target when focus left"
    assert after["bar"]["idle"] is False, "the ribbon went inert just because focus moved"
    assert after["marked"] is True
    assert after["bar"]["controls"]["bold"]["disabled"] is False
    assert ran["hideFmtBarIsGone"] is True, (
        "hideFmtBar is still reachable from code — the bar can be made to vanish again")


def test_bold_after_focus_left_lands_on_the_remembered_words(ran):
    """THE CRUX. "Schedule" is characters 0-8 of the block. Highlight it, let focus go to the Tax
    select, then press Bold on the ribbon — the gesture a static ribbon invites and a floating bar
    never could. Without the remembered range `selectionFormat` would widen to the whole paragraph
    and bold every word in it, in a customer-facing document, with nothing on screen saying so."""
    got = ran["blurThenBold"]
    assert got["remembered"] == [0, 8], "the selection was never recorded"
    assert got["runs"] == [{"text": "Schedule", "bold": True},
                           {"text": ":  4 days on site"}], (
        "the format did not land on the highlighted words: %r" % (got["runs"],))
    assert got["dirtied"] == [["116", True]], "the edit was not marked as a formatting change"
    assert got["barAfter"]["controls"]["bold"]["on"] is True, (
        "the ribbon does not read back the state it just applied")


def test_the_mousedown_guard_keeps_the_selection_alive(ran):
    """What stops the press itself destroying what it acts on. `preventDefault` on the ribbon's
    mousedown suppresses the browser's focus move, so the block keeps its selection — and that
    matters MORE from a ribbon than from a bar beside the caret, because the ribbon is page chrome
    outside the document and an allowed focus move would take the caret clean out of the editor.
    The `select` is exempt because preventDefault on its mousedown stops it opening at all."""
    assert ran["mousedownGuard"] == {"button": True, "select": False}
    assert ran["blurThenBold"]["pressed"]["prevented"] is True


def test_a_caret_with_no_highlight_still_means_the_whole_paragraph(ran):
    """Not a bug, and not changed: `selectionFormat`'s own rule is that a collapsed caret means
    "this whole paragraph", because the estimator asked for a section to change and a pending
    style that only affects the next keystroke reads as nothing having happened. Asserted here
    because it is what proves the case above was the remembered range doing work, rather than the
    widening happening to agree with it."""
    assert ran["caretOnlyBold"]["runs"] == [
        {"text": "Schedule:  4 days on site", "bold": True}]


def test_the_size_dropdown_no_longer_resizes_the_whole_paragraph(ran):
    """A bug the ribbon inherited rather than caused, fixed on the way past. The mousedown guard
    cannot cover a `<select>` — preventDefault stops it opening — so focus really does leave the
    paragraph before `change` fires, and `selectionFormat` was widening to the whole paragraph.
    The remembered range puts the size on the words that were highlighted."""
    got = ran["sizeAfterBlur"]
    assert got["selectMousedownPrevented"] is False, (
        "the size dropdown's mousedown is being prevented, so it cannot open")
    assert got["runs"] == [{"text": "Schedule", "size_pt": 12},
                           {"text": ":  4 days on site"}]
    assert got["barValue"] == "12", "the ribbon does not show the size it just applied"


def test_reset_also_uses_the_remembered_range(ran):
    """Reset is the other control that writes a range rather than reading one, so it gets the same
    treatment: bold the paragraph from the caret, highlight the first word, walk away, press
    Reset — and only the first word comes back to the template's formatting."""
    assert ran["resetOnRemembered"]["runs"] == [
        {"text": "Schedule"}, {"text": ":  4 days on site", "bold": True}]


def test_switching_paragraphs_drops_the_remembered_range(ran):
    """Character offsets into one paragraph mean nothing in another. Block 115 is 33 characters;
    if [0, 8) had leaked across from 116 only "Scope:  " would be bold."""
    got = ran["rangeDoesNotLeak"]
    assert got["rememberedAfterSwitch"] == [0, 33], (
        "the range from the previous paragraph survived the switch: %r"
        % (got["rememberedAfterSwitch"],))
    assert got["runs"] == [{"text": "Scope:  concrete prep and coating", "bold": True}]


def test_focus_on_a_price_line_makes_the_ribbon_let_go(ran):
    """A `.tw-line-edit` price line is a whole-line display override, a different channel from the
    run formatting the ribbon writes. Staying aimed at the last paragraph is how a press silently
    rewrites something nobody is looking at, so the target is dropped and the ribbon goes inert —
    the one case where "inert" is the right answer even though a paragraph was recently edited."""
    got = ran["priceLineFocus"]
    assert got["idle"]["target"] is None
    assert got["idle"]["bar"]["idle"] is True
    assert got["idle"]["marked"] is False, "the previous paragraph still claims to be the target"
    assert got["idle"]["bar"]["controls"]["bold"]["disabled"] is True
    assert got["runs"] == [{"text": "Schedule:  4 days on site"}], (
        "a press with no target still reformatted the last paragraph")


def test_a_remembered_block_that_left_the_dom_is_dropped(ran):
    """`clearDocSurface` destroys every paragraph on a template reload, a base-bid switch and a
    work-type switch. The floating bar could not hit this — it only existed while its block had
    focus, and a detached node has none. A ribbon holds its target across all of that, so the
    target has to be re-checked against the live document or a press formats an orphan: it lands
    nowhere, and every button still looks like it worked."""
    got = ran["orphanedTarget"]
    assert got["target"] is None and got["remembered"] is None
    assert got["bar"]["idle"] is True, (
        "the ribbon still looks live after the paragraph it was aimed at was destroyed")
    assert got["runs"] == [{"text": "Schedule:  4 days on site"}]


def test_the_paragraph_controls_still_work_after_focus_left(ran):
    """The bullet and the indents act on the whole paragraph regardless of the selection, so they
    need no remembered range — but they do need the remembered BLOCK, which is the half that used
    to die on blur. Kyle's 2026-08-20 complaint ("I cant dletet the bullet points") must not come
    back through the ribbon."""
    got = ran["bulletAfterBlur"]
    assert got["pressed"]["disabled"] is False
    assert got["li"] is False, "the bullet did not come off"
    assert got["now"] == {"bullet": False, "indent": 288, "locked": False}
    assert got["persisted"] is True, "the change was never handed to the override persistence"
    assert got["bar"]["controls"]["bullet"]["on"] is False


def test_a_locked_terms_clause_still_gets_nothing_and_the_ribbon_still_does_not_move(ran):
    """Both halves at once. The refusal is unchanged — a numbered TERMS AND CONDITIONS clause is
    offered no paragraph control, because removing one item from a decimal list renumbers every
    clause after it in legal boilerplate. What changed is HOW: `visibility: hidden` keeps the
    space so a static ribbon stays static, and unlike `opacity: 0` it still takes the button out
    of hit-testing and out of the tab order. `disabled` is set as well, so the refusal survives
    even if that rule ever loses a cascade."""
    got = ran["lockedClause"]
    for name in ("bullet", "outdent", "indent", "sep"):
        c = got["bar"]["controls"][name]
        assert c["visibility"] == "hidden", name
        assert c["display"] == "", (
            "%s is hidden with `display`, so the ribbon reflows and Reset moves" % name)
    for name in ("bullet", "outdent", "indent"):
        assert got["bar"]["controls"][name]["disabled"] is True, name
    # No pressed state left over from the WORK row focused just before it. The ribbon is one
    # memoized element that now lives for the whole session, so a stale "on" would sit on the
    # hidden button waiting for the day the visibility rule loses.
    assert got["bar"]["controls"]["bullet"]["on"] is False
    assert got["bar"]["controls"]["bullet"]["pressed"] == "false"
    assert got["pressed"]["disabled"] is True
    assert got["li"] is True and got["marginLeft"] == "" and got["patch"] is None, (
        "the clause was renumbered by a press on a control it was never offered")
    assert got["boldStillOffered"] is True, (
        "bold on a contract clause is fine — only the renumbering is refused")
    assert got["runsUnchanged"] is True


def test_ctrl_b_still_uses_the_live_selection(ran):
    """The keyboard route is bound in the same wiring block and is the one path that always HAS a
    live selection — the caret is in the paragraph by definition — so it must keep using it. It is
    exercised here because the whole wiring block is lifted: a change that routed Ctrl+B through
    the remembered range instead would look identical in the source."""
    got = ran["ctrlB"]
    assert got["prevented"] is True, (
        "the browser's own execCommand handler still runs, and it emits tags fmtAt cannot read")
    assert got["runs"] == [{"text": "Schedule", "bold": True},
                          {"text": ":  4 days on site"}]
    assert got["target"] == "116"


def test_it_is_one_element_from_load_to_last_press(ran):
    """The bar's DOM identity is load-bearing: the mousedown guard that saves the selection, the
    click handler and the change handler are all bound to that one node by `ensureFmtBar`, which
    memoizes. A path that rebuilt it would keep the ribbon looking right and quietly drop the
    guard that makes it work."""
    assert ran["focused"]["sameNode"] is True
    assert ran["sameNodeThroughout"] is True


def test_a_refill_under_the_ribbon_does_not_leave_the_range_on_other_words(ran):
    """THE BUG THE RIBBON ITSELF CREATED, AND THE ONE THAT REACHES THE CUSTOMER.

    `refreshDocumentFills` re-substitutes the sidebar's live values into every block that does not
    contain `document.activeElement`. That skip WAS the protection the floating bar got for free:
    the bar existed only while its block had focus, so its block was always the skipped one. A
    ribbon REMEMBERS its target past blur, and a remembered block is normally not the focused one
    — so it is re-filled like every other while the ribbon still holds character offsets into the
    text it used to say.

    The sequence is ordinary work, not a corner case: highlight two words in a WORK row, click
    into the pricing rail to correct the square footage, press Bold. "5,200" becomes "12,000", one
    character longer, every offset behind it slides, and the remembered [12, 26) that meant
    "epoxy flooring" now spans " epoxy floorin". Bold lands there — into the runs, into the
    override, into the generated .docx — with the estimator looking at the sidebar and nothing on
    screen saying otherwise.

    FIXED WHERE THE RANGE IS USED, NOT WHERE THE REWRITE HAPPENS. Telling `refreshDocumentFills`
    to notify the ribbon would fix the one path known to do this today and quietly miss the next;
    `setBlockContent` alone already has four call sites. Validating at the point of use covers
    every rewrite from every path by construction, with no call site left to forget.

    The fallback is the whole paragraph. That is not a lesser bug but the rule this editor already
    documents for a caret with no selection, and the estimator watches the whole row change and
    can undo it. Keeping the block OUT of the re-fill to protect the range instead would print
    last week's square footage, which is worse by a distance."""
    got = ran["refilledUnderTheRibbon"]
    assert got["remembered"] == [12, 26], "the harness never recorded the selection under test"
    assert got["pressed"]["disabled"] is False, "the ribbon went inert, so this proves nothing"
    assert got["runs"] == [{"text": "12,000 SF of epoxy flooring", "bold": True}], (
        "Bold landed on characters the estimator never highlighted: %r" % (got["runs"],))
    assert got["rememberedAfter"] != [12, 26], (
        "the stale offsets are still on record, so the next press will use them as well")


def test_the_stale_range_guard_does_not_fire_on_every_refill(ran):
    """The other half of that fix, and without it the fix is a regression wearing a green test.

    `refreshDocumentFills` runs on a 150ms debounce after EVERY sidebar keystroke and walks every
    block on the page. A guard that dropped the remembered range whenever it ran would put the
    ribbon back to formatting whole paragraphs as its NORMAL behaviour — exactly what the
    remembered range was added to stop — and the test above would still pass, because a whole
    paragraph is what that test asserts.

    So: neither a re-fill of a different paragraph, nor a re-fill that writes the same text back
    (the common case, since most keystrokes change no given row), may cost the estimator the
    selection they made."""
    exact = [{"text": "5,200 SF of "}, {"text": "epoxy flooring", "bold": True}]
    assert ran["otherBlockRefilled"]["runs"] == exact, (
        "re-filling a DIFFERENT paragraph threw away this one's remembered selection")
    assert ran["harmlessRefill"]["runs"] == exact, (
        "a re-fill that changed nothing still threw the remembered selection away")


def test_the_idle_ribbon_does_not_keep_the_last_target_lit(ran):
    """The ribbon is ONE memoized element that now lives for the whole session, so anything the
    idle path does not clear is the previous paragraph's state sitting on a dead control.

    `renderFmtBar`'s `if (!el)` branch cleared the run buttons and returned — above both
    `[data-para]` blocks. Bullet therefore stayed lit and went on announcing `aria-pressed="true"`
    on a control that is disabled, which is a claim about a paragraph the ribbon is no longer
    aimed at, read out loud to anyone using a screen reader."""
    got = ran["idleAfterBullet"]
    assert got["lit"]["on"] is True and got["lit"]["pressed"] == "true", (
        "the harness never lit Bullet in the first place, so going idle proves nothing")
    assert got["idle"]["idle"] is True
    c = got["idle"]["controls"]
    assert c["bullet"]["disabled"] is True
    assert c["bullet"]["on"] is False, (
        "Bullet is still lit for a paragraph that is no longer the ribbon's target")
    assert c["bullet"]["pressed"] == "false", (
        'a disabled control still announces aria-pressed="true" about the last target')


def test_the_idle_ribbon_is_the_same_shape_whatever_preceded_it(ran):
    """The locked TERMS clause hides the paragraph group with `visibility: hidden`, which is right
    while it is the target and wrong the moment there is no target at all: the idle ribbon then
    showed a different number of controls depending on which paragraph the estimator happened to
    leave last. Idle is one state and has to look like one state."""
    got = ran["idleAfterLockedClause"]
    names = ("bullet", "outdent", "indent", "sep")
    assert [got["hidden"][n]["visibility"] for n in names] == ["hidden"] * 4, (
        "the harness never hid the paragraph group, so going idle proves nothing")
    c = got["idle"]["controls"]
    for name in names:
        assert c[name]["visibility"] == "", (
            "%s is still hidden from when the target was a locked clause, so the idle ribbon is a "
            "different shape depending on what came before it" % name)


def test_a_selection_that_left_the_paragraph_does_not_leave_a_stale_range_live(ran):
    """THE HOLE THE TEXT STAMP DOES NOT COVER, found in review after the first fix shipped green.

    `selectionRange` returns offsets only when BOTH endpoints are inside the block. So a drag that
    starts in a WORK row and runs past its end — onto the canvas, into the next paragraph — is
    unreadable: nothing re-stamps the range, and the paragraph's TEXT never changed, so the stamp
    still matches. The ribbon lit up for the old [12, 26) while a different span was visibly
    highlighted, and Bold landed on fourteen characters nobody selected.

    Same failure class as the re-fill bug, reached by moving the SELECTION instead of rewriting the
    words — and the whole-paragraph fallback's justification does not cover this one: "the estimator
    sees the entire row change and can undo it" is true of a whole row and false of a stale window
    in the middle of it.

    The first version of the harness could not express this state at all. It modelled the selection
    as "inside `el`" or "not inside `el`", which is exactly the distinction `selectionRange` draws —
    so it agreed with the bug. The model now carries both endpoints."""
    g = ran["selectionEscaped"]
    assert g["remembered"] == [12, 26], "the harness did not set up the selection under test"
    assert g["pressed"]["disabled"] is False, "the ribbon went inert, so this proves nothing"
    assert g["runs"] == [{"text": "5,200 SF of epoxy flooring", "bold": True}], (
        "Bold landed on the stale range instead of falling back to the paragraph: %r" % (g["runs"],))
    assert g["rememberedAfter"] != [12, 26], "the stale offsets are still on record"


def test_dragging_upward_out_of_the_paragraph_is_caught_too(ran):
    """The nastier half of the same gesture, and the reason the guard lives in `fmtRangeFor` rather
    than in the selectionchange listener: when the selection STARTS outside the block, that listener
    returns early on its `startContainer` check and nothing is touched at all. A guard added there
    would have fixed the downward drag and missed this one."""
    assert ran["selectionEscapedUpward"]["runs"] == [
        {"text": "5,200 SF of epoxy flooring", "bold": True}]


def test_a_highlight_in_the_sidebar_leaves_the_remembered_range_alone(ran):
    """The half that makes the fix safe rather than merely strict, and it IS the feature.

    Kyle asked for a bar that stays put and keeps working after focus has gone. Double-clicking a
    word in the Tax field is not a claim about which words in the proposal to format, so the memory
    has to survive it — a guard that dropped the range for any unreadable selection would satisfy
    the two tests above and quietly undo the whole point of the ribbon.

    So the guard fires only for a real, non-collapsed highlight that touches the document surface."""
    assert ran["foreignSelection"]["runs"] == [
        {"text": "5,200 SF of "}, {"text": "epoxy flooring", "bold": True}], (
        "a highlight in a sidebar field threw away the estimator's document selection")


def test_a_press_that_changes_nothing_writes_nothing(ran):
    """`applyFormat` had no did-anything-change test. Reset on a paragraph carrying no formatting
    deletes nothing and Bold on already-bold words adds nothing, but `markEdited` ran regardless —
    which set `tw-fmt`, which the input handler reads as dirty, which persists an override for a
    paragraph nobody touched. `paraPatch`'s own docstring names what that breaks: an untouched
    document ships no overrides, and that is what keeps the generated .docx byte-identical.

    The ribbon is what makes it reachable. `fmtBlock` outlives focus and is cleared only by a
    non-block editable or a template reload, so the row stays aimed at the last paragraph touched
    for the rest of the session, and one stray press writes an override for a paragraph the
    estimator has visually left."""
    g = ran["noOpReset"]
    assert g["dirtiedDelta"] == 0, "a no-op press marked the paragraph edited"
    assert g["persistedDelta"] == 0, "a no-op press persisted an override"
    assert g["runs"] == [{"text": "Schedule:  4 days on site"}]


def test_the_no_op_guard_does_not_swallow_real_edits(ran):
    """The other direction, and the one that would make the guard worse than the bug: a comparison
    that reported "nothing changed" too eagerly would silently drop every format the estimator
    applied, with the button lighting up as though it had worked."""
    g = ran["realEditsStillCount"]
    assert g["boldLanded"], "Bold stopped working"
    assert g["resetCleared"], "Reset stopped working"
    assert g["dirtiedDelta"] == 2, (
        "a real bold and a real reset should be exactly two edits, got %s" % g["dirtiedDelta"])


def test_a_press_from_the_sidebar_does_not_paint_a_selection_in_the_document(ran):
    """`applyFormat` re-placed the document selection unconditionally. Before the bar became a
    ribbon that was unreachable with focus elsewhere — the bar did not exist. Now every press made
    while the caret is in a sidebar field runs it, which paints a highlight the estimator never
    made on top of the target's own background, and in an engine that focuses the editing host on a
    programmatic selection pulls their caret out of the field mid-entry, so the next digits they
    type land in the proposal paragraph.

    The format still has to land — that is the feature — so this asserts both halves."""
    g = ran["noSelectionRepaint"]
    assert g["runs"] == [{"text": "Schedule", "bold": True}, {"text": ":  4 days on site"}], (
        "the format did not land on the remembered range")
    assert g["selectionAfter"] is None, (
        "a selection was written into the document while the caret was in the sidebar")


def test_backspace_at_the_start_of_a_bulleted_line_removes_the_bullet(ran):
    """Hanz, 2026-08-25: "When I back space, it doesnt remove the bullet point."

    It did nothing whatsoever, and not because a branch was missing. Every `.tw-block` is its own
    editing host — `renderBlock` sets contentEditable per block and `#doc-surface` has none — so a
    browser cannot merge or delete across the boundary and Backspace at offset 0 is silently
    dropped. That same structure is what stops two paragraphs ever merging, which is worth
    keeping: a block IS one Word paragraph carrying an id from the backend's walk, and the editor
    cannot invent a second one.

    So the keystroke does what Word does with the room it has — takes the list formatting off,
    one rung at a time — rather than trying to delete backwards into the previous paragraph.

    Routed through `paraAction`, the same call the ribbon's Bullet button makes, so the two cannot
    drift: the persistence, the repagination and the locked-clause refusal are all inherited
    rather than reimplemented."""
    g = ran["backspaceOnBullet"]
    assert g["before"]["bullet"] is True, "the fixture row was not bulleted to begin with"
    assert g["after"]["bullet"] is False, "Backspace left the bullet on"
    assert g["after"]["indent"] == g["before"]["indent"], (
        "removing the bullet also moved the indent; that is the second press, not the first")
    assert g["prevented"], "the keystroke was not consumed, so the browser also acted on it"
    assert g["persisted"], "the change was never scheduled to save"


def test_backspace_again_walks_the_indent_back_to_the_margin(ran):
    """Word's ladder, and the order matters: an estimator pressing Backspace on a bulleted line is
    asking for the bullet, not the indent. Only once the bullet is gone does the indent start to
    give way."""
    g = ran["backspaceAgainOutdents"]
    assert g["after"]["indent"] == 0, "the second press did not outdent to the margin"
    assert g["after"]["bullet"] is False
    assert g["prevented"]


def test_backspace_at_the_margin_gives_the_key_back_to_the_browser(ran):
    """With no bullet and no indent left there is nothing to undo, so the keystroke must NOT be
    swallowed — a Backspace that silently does nothing at the left edge reads as a frozen editor.
    It falls through, and the editing-host boundary makes that a harmless no-op."""
    g = ran["backspaceAtTheMargin"]
    assert g["after"] == {"bullet": False, "indent": 0, "locked": False}
    assert not g["prevented"], "the keystroke was consumed with nothing to show for it"


def test_backspace_anywhere_but_the_start_is_left_alone(ran):
    """A selection means "delete these characters"; a caret mid-line means "delete the character
    before me". Both are the browser's job, and hijacking either would make the bullet vanish
    while somebody was editing a word."""
    g = ran["backspaceElsewhere"]
    assert not g["onSelectionPrevented"], "Backspace over a selection was hijacked"
    assert g["afterSelection"]["bullet"] is True, "a selection delete removed the bullet"
    assert not g["midLinePrevented"], "mid-line Backspace was hijacked"
    assert g["afterMidLine"]["bullet"] is True, "mid-line Backspace removed the bullet"


def test_backspace_cannot_un_number_a_contract_clause(ran):
    """The refusal that has to survive every new route into paragraph formatting: un-bulleting a
    numbered TERMS AND CONDITIONS clause renumbers every clause below it, in the signed contract.
    `paraAction` refuses on `locked`, and this keystroke inherits that instead of checking for
    itself — one guard, not two that can disagree."""
    g = ran["backspaceOnLockedClause"]
    assert g["after"]["locked"] is True
    assert not g["prevented"], "the keystroke was consumed on a clause it must not change"
    assert g["after"]["bullet"] == ran["backspaceOnLockedClause"]["after"]["bullet"]


# ══ where the ribbon sits, and which CSS rules have to win ════════════════════
def _css_rule(selector):
    """The declarations of EVERY top-level rule with exactly this selector, concatenated.

    Scoped to the rule rather than to a slice of the file, for the reason test_box_drag_ui.py
    records: a nearby rule can carry the declaration you are looking for and pass an assertion
    you had already broken."""
    found = [m.group(1) for m in
             re.finditer(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)]
    assert found, "%s has no top-level rule in styles.css" % selector
    return "\n".join(found)


def _rules_matching(needle):
    """[(selector, declarations)] for every rule in styles.css whose selector mentions `needle`,
    with comments and @media wrappers stripped. Used for the negative claims — "nothing anywhere
    sets display:none on this" — which a single-selector lookup cannot make."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    css = re.sub(r"@media[^{]*\{", "", css)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
            if needle in m.group(1)]


def _specificity(selector):
    """(ids, class-level, type-level) for one compound selector.

    Spelled out rather than eyeballed because this is the trap the repo keeps paying for:
    specificity beats source order, so a rule written later can still lose. `:not(X)` and `:is(X)`
    contribute their ARGUMENT's specificity and nothing of their own, which is exactly what lets
    the `.tw-fmt-target` rule outrank the plain hover and focus rules it sits alongside."""
    s = selector.strip()
    args = []
    s = re.sub(r":(?:not|is)\(([^()]*)\)", lambda m: args.append(m.group(1)) or " ", s)
    ids = len(re.findall(r"#[\w-]+", s))
    # Pseudo-ELEMENTS (::after) count as type-level; pseudo-CLASSES (:hover) as class-level.
    types = len(re.findall(r"::[a-z-]+", s))
    s = re.sub(r"::[a-z-]+", " ", s)
    classes = (len(re.findall(r"\.[\w-]+", s))
               + len(re.findall(r"\[[^\]]+\]", s))
               + len(re.findall(r":[a-z-]+(?:\([^()]*\))?", s)))
    types += len(re.findall(r"(?:^|[\s>+~])[a-zA-Z][\w-]*", s))
    for a in args:
        i, c, t = _specificity(a)
        ids, classes, types = ids + i, classes + c, types + t
    return (ids, classes, types)


def test_the_ribbon_row_sits_between_the_toolbar_and_the_canvas():
    """Where it is IS the feature. `body.word-app` is a flex column and `.word-canvas` is
    `flex: 1; overflow-y: auto`, so the canvas is the scroller and everything above it is
    permanently-visible chrome — which is why this needs no `position: sticky` and no `fixed`
    coordinates. The div is empty on purpose: `ensureFmtBar` mounts the bar into it."""
    assert PAGE.count('id="fmt-ribbon"') == 1, (
        "there is more than one ribbon host; getElementById picks one and the rest stay empty")
    i_body = PAGE.index('<body class="word-app">')
    i_tools = PAGE.index('<div class="word-ribbon">')
    i_ribbon = PAGE.index('<div id="fmt-ribbon"')
    i_canvas = PAGE.index('<div class="word-canvas">')
    assert i_body < i_tools < i_ribbon < i_canvas, (
        "the formatting ribbon is not the row between the toolbar and the canvas")
    assert re.search(r'<div id="fmt-ribbon" class="fmt-ribbon">\s*</div>', PAGE), (
        "the ribbon host is not an empty div — the bar is mounted into it by ensureFmtBar")
    # A direct child of <body>, not nested inside the toolbar above it: div depth must be back to
    # zero by the time we reach it, or the flex column does not contain it as its own row.
    between = PAGE[i_body:i_ribbon]
    assert between.count("<div") == between.count("</div>"), (
        "#fmt-ribbon is nested inside another div, so it is not a row of the flex column")


def test_the_ribbon_is_outside_the_document_zoom_transform():
    """The regression the old `position: fixed` existed to avoid, stated the other way round.
    #doc-zoom carries `transform: scale(k)` for the Word-style zoom; anything inside it is scaled
    with the paper. The ribbon must not be, so it is a sibling of `.word-canvas` — which #doc-zoom
    lives inside — and therefore can never enter that subtree."""
    i_ribbon = PAGE.index('<div id="fmt-ribbon"')
    i_zoom = PAGE.index('<div id="doc-zoom"')
    assert i_ribbon < i_zoom
    assert PAGE.index('<div class="word-canvas">') < i_zoom, (
        "#doc-zoom moved out of the canvas — re-derive where the ribbon has to sit")
    assert re.search(r"docZoom\.style\.transform\s*=\s*`scale\(", JS_CODE), (
        "the zoom transform is gone from proposal-review.js — this test's premise needs rewriting")


def _page_style(selector):
    """Declarations of a rule in proposal-review.html's own <style> block. `.word-canvas` and the
    Word chrome are styled there, not in styles.css."""
    found = [m.group(1) for m in
             re.finditer(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", PAGE)]
    assert found, "%s has no rule in proposal-review.html" % selector
    return "\n".join(found)


def test_the_canvas_is_the_scroller_so_the_ribbon_needs_no_sticky():
    """The reason there is no `position: sticky` on the ribbon row: the page body does not scroll.

    THIS WAS REVISITED ON 2026-08-25, exactly as the old version of this docstring said it would
    have to be. Hanz: "Make the ribbon sticky when I scroll down." It was scrolling away — and
    sticky was the wrong fix, because the ribbon is not inside the canvas's scrollport, so sticky
    would have done nothing whenever the canvas WAS the scroller and only masked the real fault
    when it was not.

    The real fault was that nothing bounded the column. `.word-app` was `min-height: 100vh` with
    no `height`, so the canvas could grow to the full height of nine-plus paper pages and let the
    PAGE scroll, carrying the ribbon out of view. Two declarations fix it and both are pinned
    here, because either one alone leaves the bound escapable: `height` bounds the column, and
    `min-height: 0` on the canvas lets a flex item shrink below its own content height, which is
    what actually stops the pages pushing the column taller than the viewport."""
    canvas = _page_style(".word-canvas")
    assert re.search(r"flex\s*:\s*1", canvas)
    assert re.search(r"overflow-y\s*:\s*auto", canvas)
    assert re.search(r"min-height\s*:\s*0", canvas), (
        "the canvas can be floored at its content height, so the page scrolls instead of the "
        "canvas and the ribbon goes with it")
    app = _page_style(".word-app")
    assert "flex-direction: column" in app
    assert re.search(r"height\s*:\s*100(dvh|vh)", app), (
        "the flex column has no upper bound, so nothing keeps the ribbon on screen")
    # The one normal-flow element between the ribbon and the canvas. Unbounded, a long options
    # list grows the body past the viewport and the page scrolls — the same failure by a
    # different route, and the reason `max-height: none` is not acceptable here.
    # `_page_style` catches BOTH the floating base rule and the @media one that drops the panel
    # inline below 1400px -- its leading-whitespace match reaches inside the media block.
    # Comments stripped first. This file explains its own rules in prose, and the phrase being
    # searched for ("max-height: none") is exactly what that prose has to quote to say why it is
    # wrong -- so a raw scan reads the explanation as the offence.
    opts = re.sub(r"/\*.*?\*/", "", _page_style(".options-panel"), flags=re.S)
    assert "max-height" in opts, "no rule bounds the options panel"
    assert not re.search(r"max-height\s*:\s*none", opts), (
        "the inline options panel is unbounded and can push the ribbon off screen")
    assert "flex: 0 0 auto" in _css_rule(".fmt-ribbon"), (
        "the ribbon row can be squeezed by the canvas below it")
    for sel, decls in _rules_matching(".fmt-ribbon") + _rules_matching(".tw-fmtbar"):
        assert not re.search(r"position\s*:\s*(fixed|sticky|absolute)", decls), (
            "%s positions the ribbon; the flex column is what pins it" % sel)


def test_no_rule_can_hide_the_ribbon_and_the_js_never_tries():
    """The bar's old base rule was `display: none`, flipped to `flex` by `showFmtBar`. Both are
    gone: the CSS declares `flex` and nothing anywhere declares `none`, so the ribbon cannot be
    made to vanish by a rule winning a cascade OR by a line of JS."""
    assert re.search(r"display\s*:\s*flex", _css_rule(".tw-fmtbar"))
    for sel, decls in _rules_matching(".tw-fmtbar"):
        assert not re.search(r"display\s*:\s*none", decls), (
            "%s hides the whole ribbon" % sel)
    assert "fmtBar.style.display" not in JS_CODE and "bar.style.display" not in JS_CODE, (
        "proposal-review.js still writes style.display on the ribbon")


def test_the_locked_clause_controls_are_hidden_by_a_rule_nothing_overrides():
    """The runtime half is above: renderFmtBar writes an inline `visibility: hidden`, which is the
    highest-priority origin short of `!important`. So the only thing that could beat it is an
    `!important` visibility rule on those controls, and no stylesheet can be executed by a stubbed
    DOM — hence a source read. There is none, and there is no `opacity` dodge either, which is the
    version of this that leaves the button clickable."""
    para_rules = _rules_matching("data-para")
    assert para_rules, "the paragraph controls have no styling at all — has the markup changed?"
    for sel, decls in para_rules:
        assert not re.search(r"visibility\s*:[^;]*!important", decls), (
            "%s overrides the inline visibility that hides a locked clause's controls" % sel)


def test_the_target_mark_wins_its_cascade_without_moving_the_text():
    """`.tw-block.tw-fmt-target` has to beat the plain hover and dirty rules — otherwise the
    paragraph the ribbon is aimed at loses its mark the moment the pointer crosses it — and it has
    to LOSE to `.tw-clause-kept`, whose amber is a refusal the estimator must be able to read. Both
    are settled by specificity, not by which line comes last."""
    target = [(s, d) for s, d in _rules_matching("tw-fmt-target")]
    assert len(target) == 1, "expected exactly one .tw-fmt-target rule, got %r" % (target,)
    sel, decls = target[0]
    mine = _specificity(sel)
    for other in (".tw-block:hover", ".tw-block:focus", ".tw-block.tw-dirty"):
        assert mine > _specificity(other), (
            "%s (%r) does not outrank %s (%r), so the ribbon's target loses its mark"
            % (sel, mine, other, _specificity(other)))
    assert ":not(.tw-clause-kept)" in sel, (
        "the mark would paint over the emptied-clause warning, which is a refusal to read")
    # Same rule as every other cue on this surface: background or box-shadow only. It is a
    # to-scale preview of a printed page registered against baked artwork, so a mark that reflowed
    # the text by a pixel would be worse than no mark at all.
    #
    # Split on `;` rather than matched line-by-line: this rule is written on ONE line, and the
    # line-anchored version of this check (test_doc_editor_ux.py's, where the rules are multi-line)
    # silently passed a `border` added right next to the background.
    props = {d.split(":")[0].strip() for d in decls.split(";") if ":" in d}
    assert "background" in props
    for banned in ("border", "padding", "margin", "font-size", "letter-spacing", "outline",
                   "width", "height", "line-height"):
        offenders = [p for p in props if p == banned or p.startswith(banned + "-")]
        assert not offenders, (
            "the target mark changes the layout (%s), shifting the text off the artwork"
            % ", ".join(offenders))
