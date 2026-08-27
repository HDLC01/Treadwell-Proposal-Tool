"""Ctrl+Z in the Proposal Editor.

Hanz, 2026-08-27:
  "Also in the Proposal Editor, I cant use Keyboard shortcuts. I wanted to control z but didnt
   work. when I deleted all in the textbox."

WHAT WAS ACTUALLY WRONG, because the fix only makes sense against it.

Ctrl+Z was never swallowed. The page's Ctrl handler returns for anything that is not a/b/i/u, so
the browser's own undo really did run — it had nothing to undo. Every edit this editor makes is a
PROGRAMMATIC DOM mutation, and programmatic mutation does not go on a contenteditable's native undo
stack. The gesture Hanz performed is the clearest example of it: Ctrl+A paints the box, Delete is
caught on keydown, `preventDefault()`ed, and answered with `els.forEach(clearBoxLine)` — three
paragraphs rewritten by `renderRuns`, none of it a browser edit. The same is true of Enter
(`insertBreakAt`), Tab (`paraAction`) and Ctrl+B/I/U (`toggleFormat`), and each of them refuses the
browser's version deliberately: `execCommand` emits `<b>`/`<i>`/`<u>` TAGS that `fmtAt` cannot read,
and a browser Enter merges two paragraphs into one, destroying an id the generated document is
filled by POSITION with. On top of all that, a repagination MOVES the nodes, and moving a node
throws the native stack away outright — so even ordinary typing stopped being undoable the moment
the terms flow repaginated.

So the editor keeps its own stack over its own model, and these tests are about that model:

  * WHAT ONE UNDO UNIT IS. A gesture. Enter, Tab, a box-wide delete, a paste and a ribbon press are
    each their own; typing and deleting coalesce until one of four boundaries — an idle gap, the
    caret changing line, the direction changing, or a typed space. An undo that unwound one letter
    at a time would read as broken in a different way; one that unwound a whole paragraph of typing
    would read as broken in a third.
  * THAT THE CARET AND THE SELECTION COME BACK, not just the characters.
  * WHAT IS EXCLUDED, and that it stays excluded: box geometry (it has its own Reset box
    affordance, and this surface is a to-scale preview registered against baked artwork), and the
    paragraph properties of a locked numbered TERMS clause (un-bulleting one renumbers the
    contract, which is why `paraAction` refuses it — an undo must refuse it by the same route).
  * THAT THE STACK IS BOUNDED, so a long editing session cannot grow it without limit.

Everything below is READ OFF A RUN of the shipped code, never off its source text. The precedent is
expensive: on 2026-08-12 `STAGE_CREATED` shipped unbound with every source assertion green and took
the production board down. It matters twice as much here, because a grep for the bug finds nothing
at all — the code that was missing was missing.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "editor-undo-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ═══ the reported gesture ════════════════════════════════════════════════════
def test_ctrl_z_gives_back_a_box_the_estimator_cleared(ran):
    """Hanz's exact sequence: select the whole text box, Delete, Ctrl+Z.

    Every paragraph empty and then every paragraph back, word for word. This is the assertion the
    whole change exists for, and before it there was no stack for Ctrl+Z to pop."""
    assert ran["afterDelete"] == ["\n", "\n", "\n"], "the delete did not clear the box"
    assert ran["afterUndo"] == ran["before"]


def test_the_box_wide_delete_is_one_undo_and_not_three(ran):
    """Three paragraphs cleared by one keystroke is ONE thing that happened.

    `clearBoxLine` runs per paragraph, so a stack that recorded mutations rather than gestures
    would leave three entries here and make the estimator press Ctrl+Z three times to get back to
    where one press of Delete took them."""
    assert ran["stackAfterDelete"] == {"undo": 1, "redo": 0}
    assert ran["stackAfterUndo"] == {"undo": 0, "redo": 1}


def test_the_restore_reaches_the_draft_once_per_box(ran):
    """The undo has to be persisted, and persisted ONCE.

    Nothing about the restored text is in the draft until an `input` event carries it there — the
    dirty flags, the paragraph overrides and the three computed channels all hang off that one
    handler. And every sweep it runs is box-wide, so one event per LINE would re-do the same sweep
    N times on the biggest undo the editor can perform."""
    assert ran["inputsOnUndo"] == 1
    assert ran["persistedOnUndo"] is True


def test_redo_puts_the_delete_back(ran):
    assert ran["afterRedo"] == ["\n", "\n", "\n"]


def test_the_selection_comes_back_as_a_selection(ran):
    """Undoing a Ctrl+A delete leaves the box selected again.

    The text being right is not enough. The estimator pressed Delete while looking at a highlighted
    box; putting the words back without the highlight leaves them looking at a different screen
    from the one they undid, and the next keystroke does something they did not expect."""
    assert ran["boxSelAfterUndo"] == ["110", "111", "112"]


def test_the_formatting_comes_back_with_the_words(ran):
    """A bolded phrase restores as a bolded RUN, not as plain characters.

    An entry stores runs rather than text for exactly this: text-only restore would look correct on
    screen for as long as nobody looked closely, and reach the customer's .docx with the estimator's
    formatting silently dropped."""
    assert ran["fmtAfterUndo"] == ran["fmtBefore"]
    assert any(r.get("bold") for r in ran["fmtBefore"]), "the fixture stopped carrying any bold"


# ═══ what one undo unit is ═══════════════════════════════════════════════════
def test_a_burst_of_typing_is_one_undo(ran):
    """Six characters typed straight through leave ONE entry.

    One entry per keystroke is the other way to get this wrong: Ctrl+Z that gives back a single
    letter is not undo, it is a slow-motion replay, and an estimator correcting a sentence would
    have to hold the key down and watch it crawl."""
    assert ran["unitsForOneBurst"] == 1


def test_a_pause_closes_the_burst(ran):
    """Five seconds later is a different thought, and a different undo."""
    assert ran["unitsAfterAPause"] == ran["unitsForOneBurst"] + 1


def test_a_space_closes_the_word(ran):
    """The space itself belongs to the word being typed; the character after it starts a new unit.

    This is the boundary that makes Ctrl+Z mean "give me back the word I just typed" instead of
    "give me back the paragraph", and it is why the boundary is read off the inserted TEXT on
    `beforeinput` rather than off the spacebar on `keydown` — closing the unit a beat earlier would
    take the pre-image from before the space and undo the space along with the next word."""
    before_word, after_word = ran["unitsAcrossASpace"]
    assert before_word == 2, "the space opened a unit of its own"
    assert after_word == before_word + 1


def test_moving_to_another_line_closes_the_burst(ran):
    before, after = ran["unitsAcrossALine"]
    assert after == before + 1


def test_typing_then_deleting_is_two_units(ran):
    """Deleting is not a continuation of typing.

    Without this an estimator who typed a phrase and then backspaced over part of it would get both
    back on one press, which is never what they meant by either."""
    before, after = ran["unitsAcrossADirectionChange"]
    assert after == before + 1


def test_twelve_keystrokes_leave_a_history_worth_walking(ran):
    """The whole point of coalescing, in one number: neither 12 entries nor 1."""
    assert ran["unitsForTwelveKeystrokes"] == 5


@pytest.mark.parametrize("pressed", ["ArrowLeft", "ArrowRight", "Home", "End", "PageDown",
                                     "Shift", "F5", "Escape", "a+ctrl", "c+ctrl"])
def test_a_key_that_changes_nothing_opens_no_unit(ran, pressed):
    """Navigation, Ctrl+A and Ctrl+C leave the stack alone.

    An entry for a keystroke that moved nothing is a press of Ctrl+Z later that appears to do
    nothing — which is the complaint being fixed, arriving by a different road."""
    assert ran["unitsFromNavigationKeys"][pressed] == 0


# ═══ redo ════════════════════════════════════════════════════════════════════
def test_both_spellings_of_redo_work(ran):
    """Ctrl+Y is Word's redo and Ctrl+Shift+Z is everything else's.

    The estimators here come from both; honouring one of them is refusing half the office. Ctrl+Y
    is asserted here and Ctrl+Shift+Z by `test_redo_puts_the_delete_back` above."""
    assert ran["ctrlY"]["cleared"] == "alpha"
    assert ran["ctrlY"]["afterCtrlY"] == "\n"
    assert ran["ctrlY"]["afterUndoAgain"] == "alpha"


def test_a_fresh_edit_throws_the_redo_away(ran):
    """Typing after an undo forks the history, and the branch that was abandoned goes.

    Keeping it would let a later Ctrl+Y replay an edit from a timeline the estimator deliberately
    left, on top of the one they are in."""
    assert ran["redoBeforeFork"] == 1
    assert ran["redoAfterFork"] == 0


# ═══ the entries that turn out to be no-ops ══════════════════════════════════
def test_a_refused_keystroke_does_not_eat_a_press_of_ctrl_z(ran):
    """Backspace at the very start of a paragraph is refused by the page — it would merge two
    paragraphs and destroy an id — but the pre-image is taken before anyone can know that.

    So an entry exists for it. One press of Ctrl+Z has to see through that entry to the real edit
    behind it, or the estimator presses the key, watches nothing happen, and is back to the bug."""
    assert ran["deadUnits"] == 2, "the refused Backspace stopped leaving an entry; re-aim this test"
    assert ran["afterOnePressPastADeadUnit"] == "alpha"


# ═══ the caret ═══════════════════════════════════════════════════════════════
def test_the_caret_comes_back_where_the_edit_happened(ran):
    """Not just the text: the caret, on the line it was on, at the offset it was at.

    An undo that restores every character and leaves the caret at the top of the box reads as a bug
    even when the words are right — the next thing typed lands somewhere nobody aimed."""
    assert ran["textAfterCaretUndo"] == "alpha bravo"
    assert ran["caretAfterUndo"] == [6, 6]


# ═══ the bounds ══════════════════════════════════════════════════════════════
def test_the_stack_is_bounded(ran):
    """85 separate edits leave the depth limit, not 85 entries.

    Each entry is a pre-image of a whole editing host. An unbounded stack on a long editing session
    is a browser tab that grows all afternoon on the one page an estimator keeps open all
    afternoon."""
    assert ran["depth"]["held"] == ran["depth"]["limit"]


# ═══ what is deliberately excluded ═══════════════════════════════════════════
def test_undo_cannot_renumber_a_locked_terms_clause(ran):
    """A numbered TERMS AND CONDITIONS clause keeps its bullet and its indent through an undo.

    `paraAction` refuses a locked clause, so no keystroke and no ribbon press can un-bullet one. An
    undo writes paragraph state directly, and a route that skipped the refusal would be a way to
    renumber legal boilerplate in a document a customer signs. The restore goes through
    `setParaState`, which is the same refusal reached by a different key.

    The entry recorded indent 0, and the clause is sitting at 576 by the time it is popped, so the
    write really is attempted rather than skipped as already-equal."""
    assert ran["locked"]["before"]["locked"] is True
    assert ran["locked"]["before"]["indent"] == 576
    assert ran["locked"]["after"] == ran["locked"]["before"]
    assert ran["locked"]["text"] == "1. Payment is due on receipt.", (
        "the text half of the undo stopped working, so the para half proves nothing")


def test_undo_cannot_strip_a_locked_clause_back_to_the_template(ran):
    """The other half of the same refusal.

    An entry whose `para` is null means "the estimator had set nothing, the template's own
    properties applied", and putting that back is a DELETE from the override map rather than a
    write. On a numbered clause that delete renumbers the contract just as surely as a write
    would, so the null branch carries the locked check too."""
    assert ran["lockedDelete"]["set"] == {"bullet": True, "indent": 576}
    assert ran["lockedDelete"]["now"]["indent"] == 576


def test_an_ordinary_indent_is_on_the_stack(ran):
    """The other half of the same rule: Tab indents an unlocked paragraph and Ctrl+Z takes it back.

    Excluding paragraph properties altogether would have been the easy answer and the wrong one —
    Tab is a keystroke that changes the document, so it has to be undoable like any other."""
    assert ran["indent"]["after"] == 288
    assert ran["indent"]["afterUndo"] == 0


def test_box_geometry_is_not_on_the_stack(ran):
    """A resized box stays resized when the text inside it is undone.

    Deliberate. Geometry already has its own affordance ("Reset box" in the box tools), and this
    surface is a to-scale preview of a printed page registered against baked artwork: a Ctrl+Z
    aimed at a word that also moved a text box by a few points would be a worse bug than the one it
    fixed."""
    assert ran["geometry"]["height"] == "240pt"
    assert ran["geometry"]["text"] == "alpha", "the text half of the undo stopped working"


def test_a_template_reload_forgets_the_history(ran):
    """`clearDocSurface()` drops both stacks.

    An entry names its lines by the backend walk's paragraph id, and those ids belong to the
    template that was on screen. A work-type or audience switch loads a different one, where the
    same number is a different paragraph — replaying an entry across that boundary would write the
    estimator's words into the wrong clause of a document a customer signs."""
    assert ran["reload"]["before"] == 1
    assert ran["reload"]["after"] == 0


# ═══ the ordering the fix depends on ═════════════════════════════════════════
def test_the_pre_image_is_taken_before_the_handler_that_deletes(ran):
    """The entry left by the delete is holding the words, not the empty box.

    Both listeners sit on #doc-surface. The snapshot one is registered in the CAPTURE phase
    precisely so that which of them runs first does not depend on where in the file the other
    happens to be written — and the harness registers the mutating handler FIRST, so nothing but
    the phase can put the snapshot ahead of it. A pre-image taken a moment later is a pre-image of
    an empty box: the original bug, wearing a stack.

    Read off the entry rather than off an undo. The right text coming back is a weaker claim — it
    could be reached from a pre-image taken at the wrong moment on some other path."""
    assert ran["preImage"] == ["alpha"]
    capture, bubble = ran["phases"]
    assert capture == "capture:alpha", "the capture pass saw a box that had already been cleared"
    assert bubble == "bubble:\n", "the delete no longer runs in the bubble pass; re-aim this test"


# ═══ the notes box, which is where the complaint came from ═══════════════════
def test_the_notes_bullets_and_their_textarea_both_come_back(ran):
    """NOTES is a text box an estimator clears, and it is the one family with no store of its own.

    Its bullets are rendered from the #notes-text textarea, which is their single source of truth
    and which the delete empties. Both halves have to come back or the next repaint throws the
    restored bullets away again."""
    assert ran["notes"]["afterDelete"]["textarea"] == ""
    assert ran["notes"]["afterUndo"]["bullets"] == ran["notes"]["bullets"]
    assert ran["notes"]["afterUndo"]["textarea"] == ran["notes"]["textarea"]


def test_a_notes_bullet_comes_back_after_its_element_is_gone(ran):
    """The case that decides the design.

    Leaving the box re-renders the preview from the emptied textarea, so three bullet ELEMENTS
    collapse into one — and there is no element left for an entry keyed by `data-note-index` to
    write bullets two and three into. Only the text can bring them back, which is why an entry for
    a notes box carries the textarea and not just the lines. A key-only restore passes every other
    test in this file and fails this one."""
    assert ran["notesRebuilt"]["bulletsLeft"] == 1
    assert ran["notesRebuilt"]["afterUndo"] == [
        "Owner supplies the water.", "No work above 90 degrees.", "Two mobilizations."]


# ═══ the computed families ═══════════════════════════════════════════════════
def test_a_computed_line_comes_back_through_its_own_channel(ran):
    """A hand-worded PRICE row restores its wording AND dispatches the event that persists it.

    The computed families store text, not runs, and clearing one resets it to the figure the
    estimate computed rather than voiding it. So the undo has to write the estimator's wording back
    and let the page's own `input` handler carry it into `price_overrides` — a silent restore is an
    override that shows on screen and reaches the customer's document as the computed line."""
    assert ran["priceLine"]["afterDelete"] == ""
    assert ran["priceLine"]["afterUndo"] == "Option 2 - Quartz broadcast (includes cove)   $41,250"
    assert ran["priceLine"]["dispatched"] == ["option:2"]


def test_an_undo_always_leaves_a_caret_somewhere(ran):
    """Even when the entry never recorded one.

    The restore drops the selection on the way in — the notes preview refuses to rebuild its
    bullets while the caret is inside them, and an undo of a deleted bullet is exactly the case
    that has to rebuild them. So an entry with no caret of its own (an edit that arrived before any
    selectionchange, a drag-and-drop, a context-menu paste) would end with no caret at all, and the
    estimator would have to click back into the box before they could carry on typing."""
    assert ran["caretless"]["recorded"] is None, "the fixture stopped being a caretless entry"
    assert ran["caretless"]["text"] == "alpha bravo"
    assert ran["caretless"]["after"] == [0, 0]
