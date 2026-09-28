"""Kyle's four complaints about the Proposal Review document editor, 2026-08-19.

Verbatim:
  (a) "Some of the labels are not editable why not make it like a word document??"
  (b) "when he pressed enter to add spacing it did not generate in the proposal"
  (c) "the textboxes are clunky"
  (d) "He is confused on how to get out of that Textbox view can you improve that as well"

WHAT THE INVESTIGATION FOUND, because the fixes only make sense against it.

(a) is TWO different things wearing one sentence.

    "Epoxy Flooring:", "Scope:", "Schedule:", "Exclusions:" and "Notes:" are real text in real
    editable paragraphs — blocks 109 and 115-118 of the Direct epoxy template, `in_block` None,
    each rendered as a whole contenteditable `.tw-block`. They were ALREADY editable; nothing
    on screen said so, because only the `{{token}}` values carried a cue. That is complaint
    (c), and it is fixed as (c). `test_a_work_label_is_ordinary_editable_text_that_stays_bold`
    proves the label round-trips and keeps its bold;
    `test_an_emptied_label_leaves_no_stray_token_and_no_lone_colon` proves clearing it does not
    expose the token it sat in front of.

    "System:" / "Option N:", "Texture:" and "Area:" are real docx text too (blocks 111-113) —
    NOT baked into the letterhead artwork — but they live inside the `{{#system}}` repeat
    region, which the editor collapses into one read-only `.tw-priced-region` and replaces with
    a preview whose labels are frontend `<strong>` text (proposal-review.js renderSystemPreview).
    `proposal_writer._apply_paragraph_overrides` refuses any id whose `in_block` is not None on
    purpose. So they are genuinely not editable, and making them so is a feature — a new
    override channel through main.py, not a CSS fix.
    `test_the_region_labels_are_real_docx_text_not_artwork` pins the evidence so the next person
    does not have to re-derive it.

(b) had a cause at each end.

    The BROWSER end: what Enter does to a contenteditable is not one thing. Depending on the
    engine and on `white-space` it inserts a `<br>`, a bare "\\n", or a wrapper `<div>` with its
    own placeholder `<br>` — and `serializeBlock` reads that last shape as TWO newlines. So one
    Enter could become a blank line and two could become three.

    The SERVER end, which is where the blank line actually died:
    `_normalize_work_label_formatting` re-bolds a WORK row up to its first colon by splitting
    the run at that character. It measured the run with `"".join(t.text …)`, which is BLIND to
    `<w:br/>`, then handed that string to `_set_direct_run_text`, which clears the run's
    w:t/w:br children and rewrites them from what it was given. Measured before the fix, a
    plain-text override of "Scope:  line one\\n\\nline two" came out of the generator as
    `[t "Scope:", t "  line oneline two"]` — both breaks gone, silently, in a customer document.
    Only the WORK box is affected, and the WORK box is where Scope / Schedule / Exclusions /
    Notes live, which is exactly what Kyle was typing into.

(d) was diagnosed and confirmed: `wireOverflowExpand` toggled on a click on the box and
    deliberately ignored clicks on `.tw-block` / `.tw-line-edit` / `[contenteditable=true]` so a
    click meant for a paragraph puts a caret in it. An OPEN box is nearly all editable content,
    so there was frequently no pixel left that would close it again.

WHY THE FRONTEND HALF RUNS UNDER NODE. Every claim above is a behaviour: which of four clicks
reaches which branch, and whether three walkers agree on one character. A source-text assertion
cannot see either, and this repo has already paid for that lesson — on 2026-08-12 `STAGE_CREATED`
shipped unbound with every source assertion green and took the production board down. So
`js/doc-editor-harness.js` lifts the shipped functions out of proposal-review.js, gives them the
smallest DOM they touch, and fires real events at them.
"""
import io
import json
import pathlib
import re
import shutil
import subprocess

import docx
import pytest
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

import proposal_writer as pw

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "doc-editor-harness.js"
CSS = (FRONTEND / "styles.css").read_text(encoding="utf-8")

_EPOXY_TEMPLATE = "Direct/XX.XX TREADWELL EPOXY PROPOSAL - New Direct.docx"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ═══ shared docx helpers ═════════════════════════════════════════════════════
def _blocks(template_rel_path=_EPOXY_TEMPLATE):
    """The same walk the editor's ids come from, so a paragraph is found by its text rather
    than by a magic number that a template re-annotation would silently invalidate."""
    d = docx.Document(str(pw.TEMPLATES_ROOT / template_rel_path))
    return [{"id": idx, "text": text, "in_block": in_block, "in_txbx": in_txbx}
            for idx, _kind, _p, in_block, text, in_txbx in pw.iter_editable_blocks(d)]


def _block_id(prefix, blocks=None):
    hits = [b for b in (blocks or _blocks()) if b["text"].startswith(prefix)]
    assert hits, "no template paragraph starts with %r any more" % prefix
    return hits[0]["id"]


def _generate(overrides):
    return pw.fill_proposal(
        work_type="epoxy", audience="Direct",
        values={"job_name": "Cedar Ridge Distribution Center", "scope_notes": "SCOPE"},
        paragraph_overrides=overrides,
    )


def _read_run(run_elem):
    """A run's text with each `<w:br/>` shown as a newline.

    Deliberately its OWN reader rather than `pw._run_text_with_breaks`: that function is half
    the fix under test, and measuring the output with it would make the assertion circular —
    a reader that lost the breaks would agree with a writer that lost them."""
    bits = []
    for el in run_elem.iter():
        if el.tag == qn("w:br"):
            bits.append("\n")
        elif el.tag == qn("w:t"):
            bits.append(el.text or "")
    return "".join(bits)


def _paragraph_with(docx_bytes, needle):
    """The generated paragraph whose OWN text contains `needle`, plus its run structure with
    the line breaks made visible.

    `_own_text` — which is what the editor reports and what the test's `needle` matches — sees
    no breaks at all, which is exactly why a br-blind reading of the paragraph cannot prove the
    break survived."""
    d = docx.Document(io.BytesIO(docx_bytes))
    for _idx, _kind, p_elem, _in_block, text, _txbx in pw.iter_editable_blocks(d):
        if needle in text:
            runs = p_elem.findall(qn("w:r"))
            return {
                "own_text": text,
                "with_breaks": "".join(_read_run(r) for r in runs),
                "breaks": sum(1 for r in runs for _ in r.iter(qn("w:br"))),
                "bold_runs": [_read_run(r) for r in runs if _is_bold(r) and _read_run(r)],
            }
    raise AssertionError("no generated paragraph contains %r" % needle)


def _is_bold(run_elem):
    rpr = run_elem.find(qn("w:rPr"))
    if rpr is None:
        return False
    b = rpr.find(qn("w:b"))
    return b is not None and b.get(qn("w:val")) not in ("0", "false")


# ═══ (b) the blank line, server end ══════════════════════════════════════════
def test_a_typed_blank_line_survives_the_work_label_normalizer():
    """THE bug behind "when he pressed enter to add spacing it did not generate in the
    proposal". A plain-text override arrives as ONE run holding w:t / w:br / w:t / w:br / w:t.
    `_normalize_work_label_formatting` splits that run at the label's colon, and it used to
    measure it with a `<w:br/>`-blind join before handing the result to
    `_set_direct_run_text`, which rewrites the run's children from the string it is given.

    Measured before the fix, this exact input generated `[t "Scope:", t "  line oneline two"]`.
    """
    sent = "Scope:  line one\n\nline two"
    got = _paragraph_with(_generate([{"id": _block_id("Scope:"), "text": sent}]), "line one")
    assert got["with_breaks"] == sent, (
        "the generated paragraph reads back as %r — the estimator's line breaks were joined "
        "away between the override and the file" % got["with_breaks"])
    assert got["breaks"] == 2, (
        "a blank line is TWO line breaks; got %d, so the gap the estimator typed is not in the "
        "document" % got["breaks"])
    # Stated as lines rather than as breaks, because "one blank line" is the thing Kyle asked
    # for: re-parsing must give back exactly one empty line, not two and not none.
    lines = got["with_breaks"].split("\n")
    assert lines == ["Scope:  line one", "", "line two"]
    assert lines.count("") == 1


def test_the_blank_line_is_a_real_break_not_a_literal_newline_in_a_run():
    """A "\\n" left inside a `<w:t>` is not a line break to Word — it is whitespace, and Word
    normalizes it away. The break has to be a real `<w:br/>` element, which is what
    `_write_t_text` emits and what this asserts on the file rather than on the payload."""
    d = docx.Document(io.BytesIO(
        _generate([{"id": _block_id("Schedule:"), "text": "Schedule:  a\n\nb"}])))
    hits = [t for t in d.element.body.iter(qn("w:t")) if "\n" in (t.text or "")]
    assert not hits, (
        "%d <w:t> node(s) still carry a literal newline: %r"
        % (len(hits), [t.text for t in hits[:3]]))


@pytest.mark.parametrize("label", ["Scope:", "Schedule:", "Exclusions:", "Notes:"])
def test_every_work_row_the_estimator_types_into_keeps_its_breaks(label):
    """All four WORK rows go through the same normalizer, so all four had the same bug.

    The needle is a phrase that occurs nowhere else in the template — "first" also appears in
    the Terms boilerplate, and matching that paragraph made this look like a product failure."""
    sent = label + "  Sawcut control joints\n\nProtect adjacent finishes"
    got = _paragraph_with(_generate([{"id": _block_id(label), "text": sent}]),
                          "Sawcut control joints")
    assert got["with_breaks"] == sent
    assert got["breaks"] == 2


def test_the_label_is_still_bolded_through_its_colon():
    """The normalizer exists to bold the label and un-bold the value; the break fix must not
    cost that. The label half of the split keeps the bold, the value half does not."""
    got = _paragraph_with(
        _generate([{"id": _block_id("Scope:"), "text": "Scope:  line one\n\nline two"}]),
        "line one")
    assert got["bold_runs"], "the WORK label lost its bold"
    assert any(r.startswith("Scope:") for r in got["bold_runs"])
    assert not any("line two" in r for r in got["bold_runs"]), (
        "the value was bolded along with the label")


def test_a_run_that_is_only_a_break_is_left_alone():
    """The visible-text guard: a run with no `<w:t>` text is skipped, exactly as it was before
    the fix, so a bare `<w:br/>` run cannot be rewritten into nothing."""
    assert pw._run_text_with_breaks(_only_break_run()) == "\n"


def _only_break_run():
    from docx.oxml import OxmlElement
    r = OxmlElement("w:r")
    r.append(OxmlElement("w:br"))
    return r


@pytest.mark.parametrize("s,n,expect", [
    ("Scope:  line one\nline two", 7, ("Scope: ", " line one\nline two")),
    ("Scope:", 6, ("Scope:", "")),
    ("a\n\nb", 1, ("a", "\n\nb")),
    ("a\n\nb", 2, ("a\n\nb", "")),
    ("", 0, ("", "")),
    ("abc", 99, ("abc", "")),
])
def test_the_split_counts_visible_characters_only(s, n, expect):
    """The label/colon offsets are measured in the document's TEXT (`_own_text` sees no
    breaks), so converting an index in that coordinate system into a cut in a string that
    carries the breaks is the whole of the fix. Off by one here re-bolds the wrong character."""
    assert pw._split_after_visible(s, n) == expect


# ═══ (b) the blank line, browser end ═════════════════════════════════════════
def test_one_enter_is_one_newline(ran):
    """Driven through the page's real keydown handler with a caret it can read. One press, one
    "\\n"; two presses, one blank line. Not two, not zero."""
    assert ran["enter"]["once"] == "Scope:  Grind and coat.\n"
    assert ran["enter"]["twice"] == "Scope:  Grind and coat.\n\n"
    assert ran["enter"]["defaultPrevented"] is True, (
        "the browser's own Enter still ran alongside ours, so the block gets both")
    # The caret moves past the break it just inserted, and the edit is marked as text (not as
    # formatting — `tw-fmt` would push every Enter onto the richer runs payload).
    assert ran["enter"]["caretsPlaced"] == [[24, 24], [25, 25]]
    assert ran["enter"]["dirtied"] == [["115", False], ["115", False]]


def test_the_caret_ends_up_after_the_break_it_just_typed(ran):
    """The regression that intercepting Enter would otherwise introduce. `placeSelection` can
    only build a Range inside a TEXT node, and `pointAt` has to skip a `<br>` because there is
    no text position in it — so rendering the break as `<br>` left the caret at the end of the
    PREVIOUS line and the next character typed went in above the break. `.tw-block` is
    `white-space: pre-wrap`, so the break is rendered as a real newline character instead,
    which is also what Blink's own editor inserts in this exact CSS context."""
    for key in ("caretLanding", "caretLandingAfterRerender"):
        landing = ran["enter"][key]
        assert landing is not None, "%s: there is no caret position at the end of the block" % key
        assert landing["isText"] is True, "%s: the caret would land on an element, not in text" % key
        assert landing["after"] == "\n", (
            "%s: the character before the caret is %r, so the caret is on the wrong side of the "
            "break" % (key, landing["after"]))


def test_the_blank_line_survives_a_re_render_and_a_reload(ran):
    """Three walkers have to agree on the same character: `serializeBlock` (what is sent),
    `renderRuns` (what applyFormat and paste rebuild the block with) and the reload path, where
    `restoreSavedOverrides` writes the stored text back in as textContent. A disagreement shows
    up as the blank line doubling or vanishing on the next sidebar change."""
    assert ran["enter"]["afterRerender"] == ran["enter"]["twice"]
    assert ran["enter"]["afterReload"] == ran["enter"]["twice"]


def test_the_harness_fixture_is_the_real_template_block(ran):
    """The (b) tests are only worth their assertions if the block they type into is the block
    the editor gets. `/api/proposal-template` reports the WORK rows AFTER running
    `_normalize_work_label_formatting` over the pristine template (main.py does that so the
    preview's metadata matches the generated file), so these are the runs the page renders."""
    d = docx.Document(str(pw.TEMPLATES_ROOT / _EPOXY_TEMPLATE))
    pw._normalize_work_label_formatting(d)
    real = None
    for _idx, _kind, p_elem, _in_block, text, _txbx in pw.iter_editable_blocks(d):
        if text.startswith("Scope:"):
            real = pw._block_runs(p_elem, Paragraph(p_elem, d))
            break
    assert real is not None, "the Scope: row is gone from the template"
    assert ran["fixtureRuns"] == real, (
        "the harness's block fixture has drifted from the template:\nfixture %r\nreal    %r"
        % (ran["fixtureRuns"], real))


def test_the_break_gets_its_own_run_and_leaves_the_label_alone(ran):
    """What actually ships: `serializeRuns`. The label keeps `bold: True`, the value keeps the
    explicit `bold: False` the template carries (absent would mean "inherit", which on a bold
    paragraph style is the opposite instruction), and the break arrives un-styled so the writer
    gives it the template's own base run properties rather than pinning anything."""
    label = {"text": "Scope:", "bold": True, "size_pt": 8}
    value = {"text": "  Grind and coat.", "bold": False, "size_pt": 8}
    assert ran["pristine"]["runs"] == [label, value]
    assert ran["enter"]["runs"] == [label, value, {"text": "\n\n"}]


def test_the_browsers_own_enter_would_have_doubled_it(ran):
    """WHY the handler intercepts Enter at all, stated as a measurement rather than a belief:
    the wrapper-div-plus-placeholder-br shape a contenteditable is left in reads as TWO
    newlines. That is one keypress becoming a blank line."""
    assert ran["browserDefaultShape"]["before"] == "Scope:  Grind and coat."
    assert ran["browserDefaultShape"]["after"] == "Scope:  Grind and coat.\n\n"


@pytest.mark.parametrize("case", ["ctrl", "meta", "alt", "composing", "other"])
def test_enter_is_only_intercepted_when_it_means_a_line_break(ran, case):
    """Ctrl/Cmd/Alt+Enter are other people's shortcuts, an in-flight IME composition is a
    candidate being committed rather than a new line, and any other key is not ours."""
    assert ran["enterGuards"][case] is True, "%s+Enter inserted a line break" % case


def test_enter_is_the_editors_on_every_line_and_refused_when_the_caret_is_unreadable(ran):
    """REVERSED on both counts, 2026-08-26, by the same structural change.

    It used to read: a price line and a notes bullet handle their own Enter, and a caret the page
    cannot read is a caret it must not guess at. Both halves rested on each line being its own
    contenteditable, where the worst a browser Enter could do was leave a stray wrapper element
    inside one line.

    With one editing host per text box, the browser's Enter SPLITS the paragraph into two
    elements. On a computed line that means a second `<p data-sys-line="area">` — a row the writer
    has no channel for, so half of what the estimator typed reaches the customer and half of it
    disappears. On a template paragraph it means a `.tw-block` whose id nothing owns. One break
    inside one element is the only shape this editor can send, so:

      * A computed line's Enter is taken, becomes one break, and the line's own save channel is
        told about it (its channels are delegated `input` listeners — being told is how it saves).
      * A caret the page cannot read means the page will not let ANYTHING happen. Handing the key
        to the browser as a fallback is the one thing that could split the paragraph, so
        "I don't know where the caret is" has to be a refusal, not a delegation. The paragraph is
        left exactly as it was, which is what the estimator sees either way.

    A node that is not an editable line at all — the box's own tools layer, the page behind it —
    still belongs to the browser. That is the guard that stayed."""
    g = ran["enterGuards"]
    assert g["computedLineTaken"] is True, "a computed line's Enter fell through and split its <p>"
    assert g["computedLineText"] == "\n", "the break did not land in the line"
    assert g["computedLineTold"] == 1, "the line's own save channel was never told"
    assert g["notALine"] is True, "Enter on chrome was hijacked"
    assert ran["enterNoCaret"]["defaultPrevented"] is True
    assert ran["enterNoCaret"]["text"] == "Scope:  Grind and coat."


def test_a_break_inside_a_token_value_keeps_the_value_a_token(ran):
    """A `.tw-fill` span is a live estimate value. Splitting it must leave two fills, not
    dissolve it into hand-typed text — that is how a computed figure gets frozen."""
    assert ran["midBreak"]["text"] == "Scope:  Grind and \ncoat."
    assert ran["midBreak"]["fills"] == ["scope_notes", "scope_notes"]
    # And the two halves of the split value keep the template's own formatting, so the .docx
    # does not come back with half a line at a different weight or size.
    assert ran["midBreak"]["runs"] == [
        {"text": "Scope:", "bold": True, "size_pt": 8},
        {"text": "  Grind and ", "bold": False, "size_pt": 8},
        {"text": "\n"},
        {"text": "coat.", "bold": False, "size_pt": 8}]


def test_the_whole_frontend_to_docx_round_trip(ran):
    """The two halves joined: the text the harness's real serializer produced, sent through the
    real writer, read back out of the real file. Exactly one blank line, end to end."""
    sent = ran["enter"]["twice"]
    got = _paragraph_with(_generate([{"id": _block_id("Scope:"), "text": sent}]),
                          "Grind and coat.")
    assert got["with_breaks"] == sent
    assert got["breaks"] == 2
    assert got["with_breaks"].split("\n") == ["Scope:  Grind and coat.", "", ""], (
        "two Enters at the end of the paragraph did not come back as one blank line")
    # And through the richer `runs` shape, which is what a formatted paragraph sends.
    got_runs = _paragraph_with(
        _generate([{"id": _block_id("Scope:"), "runs": ran["enter"]["runs"]}]),
        "Grind and coat.")
    assert got_runs["with_breaks"] == sent
    assert got_runs["breaks"] == 2


# ═══ (d) a box too long for its template height is NOT CLIPPED ═══════════════
# Hanz, 2026-09-26: "whatever is the font size in the PDF should also be the same as in the Proposal
# Editor". The writer prints an over-long box at its shrink floor and lets the lines that still do
# not fit run past the box's bottom edge; it never cuts one. fitTxbx used to clip the box at its
# design height and hide those lines behind "Show all", so the page showed LESS than the PDF. The
# Show all / Collapse / Escape / outside-click machinery existed only to get past that clip, and it
# went with it.
UNCLIPPED = {"open": False, "overflow": True, "maxHeight": "", "overflowStyle": "", "zIndex": ""}


def test_an_overflowing_box_is_marked_and_not_clipped(ran):
    """400pt of content in Kyle's 183.75pt GC Resinous box is the real complaint (a long WORK
    scope). The box says it is over, and every line of it stays on the page."""
    assert ran["overflowing"] == UNCLIPPED


def test_there_is_nothing_to_open_and_nothing_to_collapse(ran):
    """No hidden text, so no way in and no way out: a Show all button on a box that hides nothing
    would be a control that does nothing."""
    t = ran["tools"]
    assert t["hasPeek"] is False, "the Show all button is back on a box that is not clipped"
    assert t["hasCollapse"] is False, "the Collapse button is back on a box that is not clipped"
    # Removing two controls from the tools layer must not reorder the grips — test_box_drag_ui.py
    # asserts they come out as move / e / s / se, in that order.
    grips = [c.split()[-1] for c in t["order"] if c.startswith("tw-grip ")]
    assert grips == ["tw-grip-move", "tw-grip-e", "tw-grip-s", "tw-grip-se"]
    assert "past the bottom of the box" in t["title"], (
        "the tooltip no longer says where the rest of the text prints: %r" % t["title"])


def test_a_box_whose_text_fits_says_nothing(ran):
    assert ran["fits"] == {"open": False, "overflow": False, "maxHeight": "",
                           "overflowStyle": "", "zIndex": "", "title": ""}


def test_escape_with_nothing_open_is_not_swallowed(ran):
    """Escape means other things on this page. A handler that always preventDefaults steals
    them from whatever else is listening."""
    assert ran["escapeWhenClosed"] == {"open": False, "defaultPrevented": False}


def test_a_click_outside_the_box_changes_nothing_about_it(ran):
    assert ran["outsideClick"] == UNCLIPPED


def test_a_refit_leaves_the_box_unclipped(ran):
    """fitTxbx re-runs after every edit and every repagination; none of those may put a clip
    back."""
    assert ran["refit"] == UNCLIPPED


def test_the_page_carries_no_clip_code():
    """The clip is gone from the one function that set it, and from the stylesheet. Asserted on
    the source because an unused `maxHeight` write is exactly what a later change would revive."""
    JS = (FRONTEND / "js" / "proposal-review.js").read_text(encoding="utf-8")
    body = JS[JS.index("  function fitTxbx(box) {"):]
    body = body[:body.index("\n  }\n") + 4]
    assert 'box.style.overflow = "hidden"' not in body
    assert "box.style.maxHeight = Math.round" not in body
    assert "data-box-peek" not in JS and "data-box-collapse" not in JS
    for gone in (".tw-box-peek", ".tw-box-collapse", ".tw-notes-open"):
        assert not _rules_matching(gone), "%s is styled again" % gone


def test_a_click_on_the_boxs_own_padding_places_a_caret_and_does_not_expand_it(ran):
    """Hanz, 2026-08-26: "Editing from one text box to another is a bit clunky, it doesnt
    automatically transfer to the next text box when I click to edit a section."

    THE MECHANISM. `wireOverflowExpand` toggled the box on any click it did not recognise as
    belonging to a line — and after the box became the single editing host, its exclusion had to be
    narrowed to `lineAt(e.target)`, because the old `[contenteditable=true]` test matched the box
    itself and would have made a clipped box impossible to open. The consequence was that
    everything which is NOT a line — the box's padding, the gap between two paragraphs, the strip
    under the last one, a `.tw-priced-region`'s padding — expanded the box instead of putting a
    caret in it. That is where a Word user clicks to start typing, and the box was `cursor:
    zoom-in` there, so the page was advertising it.

    Executed rather than read, because "the click landed a caret" is a claim about a Range, and
    about a chain of three handlers not fighting each other. It is also asserted that nothing
    preventDefaults: where the browser is already right, this must not overrule it."""
    got = ran["padClick"]
    assert got["open"] is False, "the click expanded the box instead of placing a caret"
    assert got["caretIn"] is True, "the click left no caret in the box at all"
    assert got["caretLine"] == got["lineIds"][-1], (
        "the caret went to the wrong line: %r of %r" % (got["caretLine"], got["lineIds"]))
    assert got["collapsed"] is True, "a click placed a SELECTION rather than a caret"
    assert got["prevented"] is False, "the handler cancelled the click it only had to complete"


def test_a_caret_the_browser_already_placed_is_left_alone(ran):
    """The other half, and the one that would be a regression rather than a bug: a click that
    lands on the text is placed by the browser, exactly where the pointer was. Re-placing it from
    the nearest line would move the caret off the character the estimator aimed at, which is worse
    than the padding click ever was."""
    assert ran["padClickKeepsCaret"]["same"] is True, (
        "the handler moved a caret the browser had already placed")
    assert ran["padClickKeepsCaret"]["offset"] == 4, "the caret's own offset was rewritten"


def test_a_resolvable_point_is_used_as_the_browser_resolved_it(ran):
    """The nearest-line walk is a FALLBACK for a point that resolves to no text position, not the
    mechanism. When `caretRangeFromPoint` answers, that answer is used — otherwise a click in the
    middle of a wrapped line would jump to the start of it."""
    got = ran["padClickUsesThePoint"]
    assert (got["line"], got["offset"]) == ("116", 7), (
        "the resolved point was thrown away for the nearest line: %r" % (got,))


def test_releasing_a_resize_grip_does_not_move_the_caret(ran):
    """A grip release fires a click on the box too. Somebody who has just dragged the box's edge
    did not ask to start typing in it — and the grips are the one part of this layer that
    `preventDefault`s the pointer, so a caret placed here would be a caret nobody asked for."""
    assert ran["gripClickPlacesNoCaret"]["caret"] is None, (
        "resizing the box moved the caret into it")
    assert ran["gripClickPlacesNoCaret"]["open"] is False, (
        "releasing a grip expanded the box — the peek is the opposite of what a resize wanted")


# ═══ (c) clunky: what is editable, and what is being edited ═══════════════════
def _css_rule(selector):
    """The declarations of EVERY top-level rule with exactly this selector, concatenated.

    Scoped to the rule rather than to a slice of the file, for the reason test_box_drag_ui.py
    records: a nearby rule can carry the declaration you are looking for and pass an assertion
    you had already broken. All of them rather than the first, because styles.css legitimately
    declares `.tw-txbx.tw-notes-overflow` twice — once for the clipped box's fade and once for
    its cursor — and reading only the first is how a real declaration reads as missing."""
    found = [m.group(1) for m in
             re.finditer(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)]
    assert found, "%s has no top-level rule in styles.css" % selector
    return "\n".join(found)


def _rules_matching(needle):
    """[(selector, declarations)] for every rule whose SELECTOR mentions `needle`, with comments
    and @media wrappers stripped. Same helper as test_fmt_ribbon.py's, and here for the same
    reason: the negative claims — "no rule anywhere paints one line on hover" — cannot be made by
    looking one selector up, and the comments in this stylesheet quote the rules they explain."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    css = re.sub(r"@media[^{]*\{", "", css)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
            if needle in m.group(1)]


def test_an_editable_paragraph_says_so_with_the_pointer():
    """Kyle read the un-highlighted half of a paragraph as not editable, and the pointer was
    agreeing with him: `.tw-block` set no cursor, and `cursor` is inherited — so inside a
    clipped box the caret pointer over the text was the box's `zoom-in` magnifier.

    THE MAGNIFIER IS GONE FROM THE BOX ENTIRELY (2026-08-26), which is why the third assertion
    inverted. It advertised a gesture that no longer exists: a click on a clipped box used to
    expand it, and now it lands a caret like a click anywhere else in a text box. The two controls
    that carried the zoom cursors afterwards, Show all and Collapse, went with the clip on
    2026-09-26."""
    assert "cursor: text" in _css_rule(".tw-block")
    assert "cursor: text" in _css_rule(".tw-block .tw-fill"), (
        "a token value inside an editable paragraph still claims to be read-only")
    assert "cursor: text" in _css_rule(".tw-txbx"), (
        "the box does not say 'text', so its padding still reads as something else to click")
    for sel, _decls in _rules_matching(".tw-txbx"):
        assert "zoom" not in _decls, (
            "%s puts a zoom cursor back on the box itself, which advertises a click gesture the "
            "box no longer has" % sel)


def test_the_per_line_hover_and_focus_rules_are_gone():
    """Hanz, 2026-08-26: "why do we still have subboxes for the main text box?" / "Also remove the
    sub textboxes the subsections."

    `.tw-block:hover` drew a 1px inset ring around whichever paragraph the pointer was over — a
    sub-box per line, following the mouse — and that is what he was looking at. This test used to
    assert those rules were geometry-free; the rules themselves are now the thing that had to go,
    so it asserts their absence instead, and that the ONE region cue left is on the text box.

    The two `:focus` rules could not have painted anything either way: a `.tw-block` carries no
    contenteditable since the box became the single editing host, so focus never lands on one."""
    for gone in (".tw-block:hover", ".tw-block:focus", ".tw-block.tw-dirty:focus"):
        assert not [s for s, _ in _rules_matching(gone) if s.strip() == gone], (
            "%s is back: that is the per-line sub-box, one per paragraph, following the pointer"
            % gone)
    # And nothing replaced them with the same thing under another name: no rule anywhere paints a
    # single line on hover or focus.
    for sel, decls in _rules_matching("tw-block") + _rules_matching("tw-line-edit") \
            + _rules_matching("tw-note-edit"):
        if ":hover" not in sel and ":focus" not in sel:
            continue
        assert not re.search(r"(?m)^\s*(background|box-shadow|outline)\s*:", decls), (
            "%s paints one line on hover/focus again: %r" % (sel, decls))
    # The region cue that replaced them, on the editing host itself.
    assert "outline" in _css_rule(".tw-txbx:focus-within"), (
        "the box being typed in has no cue at all now, which is worse than a per-line one")


def test_the_dirty_bar_survives_on_its_own():
    """`.tw-block.tw-dirty:focus` existed to stop the dirty bar losing a cascade fight with
    `.tw-block:focus`. With both focus rules gone there is nothing to fight, and the bar has to
    still be there: it is the mark that says "this paragraph was hand-edited", which is
    provenance rather than chrome and was never part of the sub-box complaint."""
    assert "inset 2px 0 0" in _css_rule(".tw-block.tw-dirty"), (
        "the hand-edited paragraph no longer says so")


def test_the_overflow_badge_sits_above_the_box_and_hides_no_text():
    """The lines that run past the box are the point of showing them, so nothing may sit on top of
    them: the old fade (`::before`, a white gradient over the last lines) is gone, and the badge
    is drawn ABOVE the box, not under its bottom edge where those lines are. Absolutely
    positioned, so fitTxbx's offsetHeight measurement is unaffected."""
    badge = _css_rule(".tw-txbx.tw-notes-overflow::after")
    assert "position: absolute" in badge
    assert re.search(r"top:\s*-\d", badge), "the badge is not above the box: %r" % badge
    assert "bottom:" not in badge, "the badge sits over the lines that run past the box"
    assert "pointer-events: none" in badge
    assert not _rules_matching(".tw-txbx.tw-notes-overflow::before"), (
        "the fade that hid the last lines of an over-long box is back")


def test_the_badge_says_where_the_rest_prints():
    """It says what the document does with the text, which is the thing to know: the rest prints
    below the box, as on screen. Both badges, the ordinary one and the cannot-grow one."""
    assert "prints below it" in _css_rule(".tw-txbx.tw-notes-overflow::after")
    blocked = _css_rule(".tw-txbx.tw-notes-overflow.tw-grow-blocked::after")
    assert "prints below it" in blocked and "cannot grow" in blocked


# ═══ (a) the labels: what is real text, and what is locked ════════════════════
def test_a_work_label_is_ordinary_editable_text_that_stays_bold(ran):
    """Retyping "Scope:" as "Scope of work:" in place — which is what typing inside the bold
    span does; the browser edits that text node, it does not restyle it — keeps the run bold and
    at the template's own size, all the way into the file."""
    assert ran["labelRetyped"]["text"] == "Scope of work:  Grind and coat."
    assert ran["labelRetyped"]["runs"] == [
        {"text": "Scope of work:", "bold": True, "size_pt": 8},
        {"text": "  Grind and coat.", "bold": False, "size_pt": 8}]
    got = _paragraph_with(
        _generate([{"id": _block_id("Scope:"), "runs": ran["labelRetyped"]["runs"]}]),
        "Scope of work:")
    assert any(r.startswith("Scope of work:") for r in got["bold_runs"]), (
        "the retyped label reached the document un-bolded")


def test_an_emptied_label_leaves_no_stray_token_and_no_lone_colon(ran):
    """Emptying the label must not expose the `{{scope_notes}}` token it sat in front of, and
    must not leave a colon on its own. The value is what is left, and nothing else."""
    assert ran["labelEmptied"]["text"] == "  Grind and coat."
    assert ran["labelEmptied"]["runs"] == [
        {"text": "  Grind and coat.", "bold": False, "size_pt": 8}]
    got = _paragraph_with(
        _generate([{"id": _block_id("Scope:"), "text": ran["labelEmptied"]["text"]}]),
        "Grind and coat.")
    assert "{{" not in got["own_text"], "an emptied label re-exposed a raw token"
    assert ":" not in got["own_text"], "an emptied label left a colon behind"
    assert got["own_text"].strip() == "Grind and coat."


def test_the_region_labels_are_real_docx_text_not_artwork():
    """The evidence behind the honest answer to "why not make it like a word document":
    "System:" / "Texture:" / "Area:" are ordinary paragraph text in the template — the reason
    they cannot be edited is that they sit inside the `{{#system}}` repeat region, which the
    editor collapses into a read-only preview and which `_apply_paragraph_overrides` refuses by
    design. Nothing here is baked into a PNG, so this is a missing feature and not a limit of
    the template artwork; whoever adds it needs a new override channel, not a CSS change."""
    blocks = _blocks()
    labelled = {b["text"].split(":")[0]: b for b in blocks if ":" in b["text"]}
    for name in ("Texture", "Area"):
        assert name in labelled, "%s: is gone from the template" % name
        assert labelled[name]["in_block"] == "system", (
            "%s: is no longer inside the {{#system}} region — if it became a free paragraph it "
            "is now editable and this test should become the round-trip one" % name)
    # And the paragraphs Kyle can already edit are free paragraphs in the same text box.
    for prefix in ("Scope:", "Schedule:", "Exclusions:", "Notes:", "Epoxy Flooring:"):
        b = [x for x in blocks if x["text"].startswith(prefix)][0]
        assert b["in_block"] is None, "%s moved into a region and stopped being editable" % prefix
        assert b["in_txbx"] == labelled["Texture"]["in_txbx"], (
            "%s is no longer in the WORK text box, so the label normalizer no longer covers it"
            % prefix)


def test_a_region_paragraph_override_is_still_refused():
    """The refusal is what makes the region labels un-editable, so it is stated here rather than
    left as a comment: a client that sends one anyway must be ignored, not obeyed."""
    system_id = [b["id"] for b in _blocks() if b["in_block"] == "system"][1]
    d = docx.Document(str(pw.TEMPLATES_ROOT / _EPOXY_TEMPLATE))
    assert pw._apply_paragraph_overrides(d, [{"id": system_id, "text": "Widget:  x"}]) == 0
