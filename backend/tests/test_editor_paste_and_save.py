"""Two keys the Proposal Editor was handing to the browser.

Both were found while fixing Ctrl+Z (see test_editor_undo.py) and reported back rather than
widened into. Hanz, 2026-08-27: "DO you mean to implement? then yes."

1. CTRL+S OPENED CHROMIUM'S SAVE PAGE SHEET.

   A Word user presses it reflexively and got a dialog offering to write an .html copy of the app
   into Downloads. The page autosaves — every `TW.setState` debounces a PUT of the whole draft blob
   2.5s after the last edit — so the key has a real meaning here: finish that save now, and say
   what happened.

   WHAT IT SAYS IS THE RETURN VALUE OF A WRITE, never a claim about one. "Saved" appears only where
   `TW.flushState()` resolved true, and that boolean is the PUT's own `res.ok`. "Saving…" is what is
   on screen while the promise is in the air, because that is all that is known then. And there is
   a third state, which is the one that made this worth care: a save can be REFUSED before it
   leaves the browser — an unverified draft (shared.js holds server saves back after two failed
   reads, deliberately, so a blank form cannot replace a live bid) or a local blob stamped for a
   different project. `flushState` cannot report that: it drops the pending write and then awaits
   `_inFlight`, a promise belonging to an older and possibly successful save, so it answers TRUE
   over a write that never left. `TW.saveBlocked()` was added for exactly that question and is
   asked first. A cheerful "Saved" that is not evidence of a save is worse than no feedback.

2. CTRL+V INTO ANYTHING THAT WAS NOT A TEMPLATE PARAGRAPH FELL THROUGH TO THE BROWSER.

   The handler bailed with `if (!el) return` and no `preventDefault`, so a paste into a price row, a
   WORK system row or a notes bullet inserted the clipboard's own markup — Word's mso-* spans, a
   font tag, a whole table — into a channel that stores a plain string. `serializeBlock` read the
   text back out, so the customer's document did not get the markup, but the page did, and the same
   paste in the same box did two different things depending on which line the caret was in.

   THE MULTI-LINE CASE IS WHERE THE DESIGN IS. A price row and a system row are ONE line, and not
   by convention: `price_overrides.lines[key]` and `system_overrides[i][field]` each hold a single
   string, each is written into a single paragraph, and the red frame around that paragraph is baked
   letterhead artwork this page is registered against. So the newlines collapse to spaces — every
   word the estimator copied arrives, and the row still fits the row it is registered against.
   A notes bullet is NOT one line: its channel is the #notes-text textarea, one line per bullet, so
   five pasted lines become five bullets.

Everything below is READ OFF A RUN of the shipped code. The precedent is expensive: on 2026-08-12
`STAGE_CREATED` shipped unbound with every source assertion green and took the production board
down. Here it matters because both bugs were shaped like working code — an early return that read
as a guard, and a readout whose only value is that its words are a promise's result.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "editor-paste-and-save-harness.js"
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")
PAGE = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ═══ Ctrl+V into the three computed families ═════════════════════════════════
def test_a_paste_into_a_price_row_is_no_longer_the_browsers(ran):
    """The reported hole. The event is consumed, so the clipboard's markup never reaches the row.

    Before this, `preventDefault` was only ever called on the `.tw-block` path — everything else
    returned early and Chromium pasted its own HTML into an element whose channel stores a
    string."""
    assert ran["priceRow"]["refusedTheBrowser"] is True
    assert ran["priceRow"]["text"] == "Quartz broadcast with cove"


def test_a_price_row_takes_the_text_and_refuses_the_formatting(ran):
    """A refusal, not an omission.

    The clipboard offered a bold word and this channel has nowhere to put one: it stores the row as
    a single string. Carrying the bold through would show it on screen and reach the customer's
    document as plain — the formatting silently dropped somewhere between the two. It is the same
    refusal the ribbon already makes for a box-wide format press."""
    assert ran["priceRow"]["runs"] == [{"text": "Quartz broadcast with cove", "tok": None}]


def test_the_paste_reaches_the_rows_own_channel(ran):
    """A silent paste is an override that shows on screen and is gone at the next repaint.

    These families have no dirty flag and no runs channel; the page's own `input` handler is the
    whole of their persistence, and `renderRuns` does not dispatch one. So the handler does, once,
    from the row that changed."""
    assert ran["priceRow"]["dispatched"] == ["option:2"]
    assert ran["sysRow"]["dispatched"] == ["area"]


def test_a_paste_is_one_undo_unit_in_these_families_too(ran):
    """Paste was already named as its own undo unit; this is that being true off the .tw-block path.

    The undo listener is bound here for real (lifted verbatim) rather than assumed, because "the
    pre-image is taken" and "the pre-image is taken for THIS family" are different claims."""
    assert ran["priceRow"]["undoUnits"] == ["paste"]
    assert ran["sysRow"]["undoUnits"] == ["paste"]
    assert ran["notes"]["undoUnits"] == ["paste"]


def test_a_work_system_row_behaves_the_same_way(ran):
    assert ran["sysRow"]["refusedTheBrowser"] is True
    assert ran["sysRow"]["text"] == "Area:  6,100 SF"
    assert ran["sysRow"]["runs"] == [{"text": "Area:  6,100 SF", "tok": None}]


def test_a_template_paragraph_still_takes_its_formatting(ran):
    """The path that already worked, pinned so the fix cannot have flattened it on the way past.

    A `.tw-block` has a runs channel that reaches the .docx, so `runsFromHtml` still reduces the
    clipboard to the four switches this editor can carry and the bold survives."""
    assert ran["blockKeepsFormatting"] == [
        {"text": "Scope: ", "tok": None},
        {"text": "grind", "tok": None, "bold": True},
        {"text": " and prep", "tok": None},
    ]


# ═══ the multi-line clipboard ════════════════════════════════════════════════
def test_five_lines_into_a_one_line_row_keep_every_word_on_one_line(ran):
    """The case to think hardest about, and the answer is: collapse, do not truncate.

    Keeping the first line and dropping the rest is the alternative that suggests itself first, and
    it silently throws away customer-facing words — the worst of the three failures available.
    Letting the row wrap onto a second line is the other, and it moves text on a to-scale preview of
    a printed page whose frames are baked artwork. Collapsing loses nothing and moves nothing."""
    assert ran["multiline"]["lines"] == 1, "the row was allowed to become two lines"
    assert ran["multiline"]["text"] == "Option 2 Quartz broadcast with integral cove Add $4,500"


def test_the_spaces_the_estimator_copied_are_not_collapsed(ran):
    """Only the newlines move. Kyle, 2026-08-20, on this editor: editing must reflect 1 to 1 in the
    customer's copy — and `syncPriceLinesIn` stores what it is given with no trim and no collapse,
    because he aligns the price rows with runs of spaces. The obvious one-liner for this fix
    (collapse all whitespace) would have quietly undone his columns."""
    assert ran["spacesKept"] == "Quartz broadcast       $41,250"


def test_five_lines_into_a_notes_bullet_are_five_bullets(ran):
    """The other family, and the opposite answer, because its channel is different.

    The bullets are rendered from the #notes-text textarea, one line per bullet, so the newlines are
    what the family is made of — and pasting a list into a bulleted list makes list items
    everywhere else too. The first pasted line joins the bullet the caret was in, which is what
    inserting text at a caret means; the rest become bullets of their own."""
    assert ran["notes"]["before"] == ["Owner supplies the water.", "Two mobilizations."]
    assert ran["notes"]["after"] == [
        "Owner supplies the water.",
        "Two mobilizations.No work above 90 degrees.",
        "Slab must be dry.",
        "Power within 100 ft.",
    ]


def test_the_notes_textarea_holds_what_the_bullets_show(ran):
    """It is their single source of truth, so a paste the bullets show and the textarea does not
    know about is a paste the next repaint erases."""
    assert ran["notes"]["textarea"] == (
        "Owner supplies the water.\nTwo mobilizations.No work above 90 degrees.\n"
        "Slab must be dry.\nPower within 100 ft.")


def test_the_caret_ends_after_what_was_pasted(ran):
    """The bullets are rebuilt on the spot, which destroys the node the caret was in.

    `.tw-note-edit` carries no `white-space` declaration (`.tw-line-edit` and `.tw-block` are
    pre-wrap; the bullets are not), so five pasted lines would otherwise render run together inside
    one bullet until the caret left the box — five lines shown as one, on a preview of a printed
    page, for as long as somebody kept typing. Rebuilding is the honest answer; putting the caret
    back at the end of the last new bullet is what makes it usable."""
    assert ran["notes"]["caretBullet"] == 3
    assert ran["notes"]["caretAtEnd"] is True


def test_a_one_line_paste_into_a_bullet_leaves_the_bullets_alone(ran):
    """The rebuild is for the multi-line case only.

    A one-line paste has nothing to reflow, and rebuilding anyway would drop the caret out of the
    words just pasted for no reason at all. Pasted mid-bullet on purpose: at the end of one, "the
    caret stayed where the splice left it" and "the bullets were rebuilt and the caret went to the
    end" are the same offset, and the two behaviours could not be told apart."""
    assert ran["notesOneLine"]["bullets"] == ["Owner really supplies the water."]
    assert ran["notesOneLine"]["caret"] == [13, 13], "the caret left the words just pasted"
    assert ran["notesOneLine"]["caretLine"] == 0


def test_a_paste_over_several_selected_rows_lands_in_the_first(ran):
    """Ctrl+A paints the whole box and a paste replaces it.

    The content goes into the first row and the rest are emptied, every element intact — see
    `spliceLines` for why a merge is not an option: a row that stops existing takes its key with it.
    For a price row "emptied" means back to the figure the estimate computed, because that is what
    its channel reads an empty value as, and what `clearBoxLine` already does to one."""
    assert ran["across"]["first"] == "Option 1 - Epoxy, revised second line"
    assert ran["across"]["second"] == "\n", "the second row was not emptied"
    assert ran["across"]["dispatched"] == ["option:1"], "one dispatch, from the row that took it"
    assert ran["across"]["undoUnits"] == ["paste"]


def test_a_paste_that_lands_on_no_line_at_all_is_refused(ran):
    """The caret can sit between two paragraphs of a box.

    Letting the browser paste there drops arbitrary markup into the box itself, where no channel can
    see it and no sweep can persist it — it would show on screen, reach nothing, and vanish at the
    next repaint. Refusing is what Enter already does with an unreadable caret, for the same
    reason."""
    assert ran["noLine"]["refusedTheBrowser"] is True
    assert ran["noLine"]["boxText"] == "Scope.", "something was pasted into the box itself"


# ═══ Ctrl+S ══════════════════════════════════════════════════════════════════
def test_ctrl_s_does_not_open_the_browsers_save_page_sheet(ran):
    assert ran["saveOk"]["refusedTheBrowser"] is True


def test_ctrl_s_finishes_the_pending_autosave(ran):
    """It is not a no-op that only draws a badge. The whole reason the key can honestly say anything
    is that it performs the write it is reporting on."""
    assert ran["saveOk"]["flushed"] == 1


def test_saving_is_what_is_shown_while_the_write_is_in_the_air(ran):
    """Read off the screen while the promise is genuinely unresolved, not inferred from the branch
    that would have set it. "Saving…" is the honest word for the one moment nothing is known yet."""
    assert ran["saveOk"]["inFlight"]["state"] == "saving"
    assert ran["saveOk"]["inFlight"]["text"] == "Saving…"


def test_saved_appears_only_where_the_write_came_back_ok(ran):
    assert ran["saveOk"]["settled"]["state"] == "saved"
    assert ran["saveOk"]["settled"]["text"] == "Saved"


def test_a_write_the_server_refused_says_where_the_work_actually_is(ran):
    """The PUT was made and came back not-ok — offline, backend down, a 500.

    The estimator's sentence is the consequence, not the mechanism: the work is in this browser and
    nowhere else. The mechanism rides the title, for whoever they show it to."""
    assert ran["saveFailed"]["settled"]["state"] == "failed"
    assert ran["saveFailed"]["settled"]["text"] == (
        "Not saved — your work is still on this computer")
    assert ran["saveFailed"]["settled"]["title"] == "the server did not take the write"


def test_a_save_refused_before_it_left_the_browser_is_not_called_saved(ran):
    """THE case that made a decision necessary.

    shared.js holds server saves back for an unverified draft — after two failed reads it adopts an
    empty blob, and pushing that would replace a live bid with a blank form. `flushState` cannot
    report it: it clears the debounce, skips the PUT, and then resolves from an older in-flight
    promise, so it answers TRUE. The harness makes it answer true here on purpose, and the readout
    still says "not saved", because `saveBlocked` is asked first and no PUT is even attempted."""
    assert ran["saveBlocked"]["flushed"] == 0, "a write was attempted through a closed gate"
    assert ran["saveBlocked"]["settled"]["state"] == "failed"
    assert ran["saveBlocked"]["settled"]["title"] == "unverified"


def test_ctrl_shift_s_is_left_to_the_browser(ran):
    """Taking a key away is only justified where the thing being taken away is wrong.
    Ctrl+Shift+S is somebody else's screenshot tool."""
    assert ran["shiftS"]["refusedTheBrowser"] is False
    assert ran["shiftS"]["flushed"] == 0


def test_ctrl_s_works_from_the_notes_textarea_too(ran):
    """Deliberately the opposite of where Ctrl+Z is bound, and the difference is what the key would
    otherwise do. Ctrl+Z in a plain input has a correct native behaviour worth protecting, so the
    undo listener is scoped to the document surface. Ctrl+S has none — the Save Page sheet is wrong
    everywhere on this page — and the notes textarea is document content anyway: it is the bullets'
    single source of truth."""
    assert ran["saveFromTextarea"]["refusedTheBrowser"] is True
    assert ran["saveFromTextarea"]["flushed"] == 1
    assert ran["saveFromTextarea"]["settled"]["state"] == "saved"


def test_the_readout_is_never_inside_the_document_surface(ran):
    """This surface is a to-scale preview of a printed page registered against baked artwork, and it
    is also what the generate payload is read from. Anything mounted in it could move the text and
    could reach the .docx; the readout is page chrome and stays there."""
    assert ran["notInTheDocument"] is True


# ═══ the readout, as markup and CSS ══════════════════════════════════════════
def test_the_readout_lives_in_the_row_that_already_reports_this_pages_state(ran):
    """`.word-ribbon` carries which step is active, the tax treatment and whether Continue is busy.
    It is also outside `#doc-zoom`, so it is not under the preview's scale transform."""
    assert 'id="save-state"' in PAGE
    ribbon = PAGE.split('<div class="word-ribbon">', 1)[1].split("</div>\n\n", 1)[0]
    assert 'id="save-state"' in ribbon, "the readout is not in the ribbon row"
    assert 'id="doc-zoom"' not in ribbon


def test_the_readout_announces_itself(ran):
    """It changes without the focus moving, which is exactly what `role="status"` and a polite live
    region are for. A visual-only readout is invisible to the estimator using a screen reader, and
    "did my work save" is not a decorative question."""
    row = [ln for ln in PAGE.splitlines() if 'id="save-state"' in ln][0]
    assert 'role="status"' in row
    assert 'aria-live="polite"' in row


def test_the_readout_can_actually_be_hidden(ran):
    """`hidden` loses to a class `display` rule — author beats UA — and this repo has shipped four
    elements that were "hidden" and still on screen for exactly that reason. So `.save-state`
    declares no `display` at all. It is a flex child of `.word-ribbon`, which blockifies it, so the
    padding behaves without one."""
    rules = [ln for ln in PAGE.splitlines() if ln.strip().startswith(".save-state")]
    assert rules, ".save-state has no rule at all any more"
    assert not any("display" in r for r in rules), (
        "a display declaration on .save-state defeats the hidden attribute: " + str(rules))
