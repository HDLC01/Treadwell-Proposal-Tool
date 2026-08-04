"""Hand-applied formatting has to survive the trip into the .docx.

Hanz asked for the Proposals tab to "act like a microsoft word" — edit text and change its
size. Before this, it couldn't: the pipeline was text-only end to end.

  * `serializeBlock` walked INTO the style spans the preview renders, kept the text and threw
    the styling away — so a bold word never left the browser. And because the TEXT was
    unchanged, the block wasn't marked dirty, so the next `refreshDocumentFills()` rewrote its
    innerHTML and erased the edit on screen too. Lost twice over.
  * `_set_paragraph_text` collapses a paragraph to run[0]'s rPr. Measured on the real GC
    Resinous label row: 20 runs mixing 9pt and 8pt with italic and underline came out as ONE
    run. `_normalize_work_label_formatting` then re-split at the first colon, which is why
    "bold through the colon" LOOKED preserved — it was being reconstructed, not carried.
  * `_shrink_overflowing_text_boxes` rewrites every w:sz in a box it thinks overflows.
    Measured: an edited NOTES line came out at 4.5pt. That silently undoes a deliberate size
    on exactly the boxes somebody resizes BECAUSE they overflow.

The last one is the subtle one and the reason `_user_sized_paragraphs` exists: an automatic
shrink that overrides a human choice is worse than a box that overflows, because the person
who chose has no way to see what happened.
"""
import io
import pathlib

import docx
import pytest
from docx.text.paragraph import Paragraph

import proposal_writer as pw

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "templates"
GC_RESINOUS = TEMPLATES / "GC" / "xx TREADWELL RESINOUS PROPOSAL - xx.docx"


def _label_block(d):
    """The mixed-format GC label row — 20 runs of 9pt/8pt with italic and underline."""
    for idx, _kind, p_elem, in_block, text, _txbx in pw.iter_editable_blocks(d):
        if in_block is None and "Resinous Flooring" in (text or ""):
            return idx, p_elem
    pytest.skip("the GC label row moved; this test needs a mixed-format paragraph")


def _runs(p_elem, d):
    return [(r.text, r.bold, r.italic, r.underline,
             r.font.size.pt if r.font.size else None) for r in Paragraph(p_elem, d).runs]


def test_the_fixture_really_is_mixed_format():
    """If the template ever became uniform, every test below would pass without proving
    anything."""
    d = docx.Document(str(GC_RESINOUS))
    _, p_elem = _label_block(d)
    runs = _runs(p_elem, d)
    assert len(runs) > 5, "expected a many-run paragraph"
    assert len({r[4] for r in runs if r[4]}) > 1, "expected more than one size in the paragraph"


# ── the writer ────────────────────────────────────────────────────────
def test_each_run_keeps_its_own_formatting():
    d = docx.Document(str(GC_RESINOUS))
    idx, p_elem = _label_block(d)
    pw._apply_paragraph_overrides(d, [{"id": idx, "runs": [
        {"text": "Label:", "bold": True, "underline": True, "size_pt": 11.0},
        {"text": " body", "bold": False, "italic": False, "underline": False, "size_pt": 8.0},
        {"text": " aside", "italic": True, "bold": False, "size_pt": 8.0},
    ]}])
    got = _runs(p_elem, d)
    assert len(got) == 3, f"runs were collapsed: {got}"
    assert got[0][1] is True and got[0][3] is True and got[0][4] == 11.0
    assert got[1][1] is False and got[1][4] == 8.0
    assert got[2][2] is True, "the italic aside lost its italic"


def test_an_absent_key_inherits_rather_than_switching_off():
    """`bold: False` and "no bold key" are different instructions. Absent must leave the
    template's own rPr alone, or every unformatted run would strip Kyle's design."""
    d = docx.Document(str(GC_RESINOUS))
    idx, p_elem = _label_block(d)
    base = _runs(p_elem, d)[0]
    pw._apply_paragraph_overrides(d, [{"id": idx, "runs": [{"text": "kept"}]}])
    got = _runs(p_elem, d)[0]
    assert got[1] == base[1], "an absent bold key changed the inherited weight"
    assert got[4] == base[4], "an absent size key changed the inherited size"


def test_an_explicit_false_writes_an_explicit_off():
    d = docx.Document(str(GC_RESINOUS))
    idx, p_elem = _label_block(d)
    pw._apply_paragraph_overrides(d, [{"id": idx, "runs": [{"text": "x", "bold": False}]}])
    assert _runs(p_elem, d)[0][1] is False


def test_a_plain_text_override_still_takes_the_simple_path():
    """Most edits are plain. They must keep working exactly as before — same shape, same
    writer, no behaviour change."""
    d = docx.Document(str(GC_RESINOUS))
    idx, p_elem = _label_block(d)
    n = pw._apply_paragraph_overrides(d, [{"id": idx, "text": "just text"}])
    assert n == 1
    assert Paragraph(p_elem, d).text == "just text"


# ── the 4.5pt bug ─────────────────────────────────────────────────────
def _overflow_the_box(d, p_elem):
    """Make the paragraph's box genuinely overflow, so the shrink actually engages.

    Without this the test is hollow: `_estimate_txbx_scale` returns ~1.0 for a box that fits,
    `_scale_txbx_runs` is never called, and the assertion passes whether or not the exemption
    exists. Verified by removing the exemption and watching the test still pass — which is why
    the padding is here and why the guard below checks the shrink really ran."""
    import copy as _copy
    box = p_elem.getparent()
    for _ in range(30):
        box.append(_copy.deepcopy(p_elem))


def test_a_chosen_size_survives_the_overflow_shrink():
    """THE regression. The shrink rewrites every w:sz in a box it thinks overflows; measured
    turning an edited NOTES line into 4.5pt. A size the estimator chose has to be exempt."""
    d = docx.Document(str(GC_RESINOUS))
    idx, p_elem = _label_block(d)
    pw._apply_paragraph_overrides(d, [{"id": idx, "runs": [
        {"text": "Deliberately eleven point", "size_pt": 11.0}]}])
    assert _runs(p_elem, d)[0][4] == 11.0
    _overflow_the_box(d, p_elem)

    # Prove the shrink ENGAGED, or the assertion below means nothing.
    box = p_elem.getparent()
    sizes_before = [sz.get(pw.qn("w:val")) for sz in box.iter(pw.qn("w:sz"))]
    pw._shrink_overflowing_text_boxes(d)
    sizes_after = [sz.get(pw.qn("w:val")) for sz in box.iter(pw.qn("w:sz"))]
    assert sizes_before != sizes_after, (
        "the shrink did not run on this box, so this test proves nothing about the exemption")

    assert _runs(p_elem, d)[0][4] == 11.0, (
        "the automatic shrink overrode a size the estimator chose")


def test_the_shrink_still_shrinks_everything_else():
    """The exemption must be surgical. If it accidentally exempted the whole box, long content
    would start overlapping the next section again — the bug the shrink exists to prevent."""
    d = docx.Document(str(GC_RESINOUS))
    idx, p_elem = _label_block(d)
    # Stuff a box so it definitely overflows, and size only ONE paragraph.
    pw._apply_paragraph_overrides(d, [{"id": idx, "runs": [
        {"text": "sized " * 40, "size_pt": 11.0}]}])
    before = {}
    for i, txbx in enumerate(pw._iter_txbx(d)):
        before[i] = [sz.get(pw.qn("w:val")) for sz in txbx.iter(pw.qn("w:sz"))]
    pw._shrink_overflowing_text_boxes(d)
    after = {}
    for i, txbx in enumerate(pw._iter_txbx(d)):
        after[i] = [sz.get(pw.qn("w:val")) for sz in txbx.iter(pw.qn("w:sz"))]
    assert any(before[i] != after[i] for i in before), (
        "nothing shrank at all — the exemption is too broad")


# ── through the whole pipeline ─────────────────────────────────────────
def test_formatting_survives_a_full_generate():
    """Piece-by-piece passing is not enough: `_normalize_work_label_formatting` runs AFTER
    overrides and re-splits label rows at the first colon, and the shrink runs after that."""
    d0 = docx.Document(str(GC_RESINOUS))
    idx, _ = _label_block(d0)
    blob = pw.fill_proposal(
        work_type="polish", audience="GC",
        values={"job_name": "Test", "city_state": "Lenexa, KS"},
        paragraph_overrides=[{"id": idx, "runs": [
            {"text": "Label:", "bold": True, "underline": True, "size_pt": 11.0},
            {"text": " body at eleven", "bold": False, "italic": False,
             "underline": False, "size_pt": 11.0},
        ]}],
    )
    out = docx.Document(io.BytesIO(blob))
    for _i, _k, p_elem, _ib, text, _t in pw.iter_editable_blocks(out):
        if "Label:" in (text or ""):
            got = _runs(p_elem, out)
            assert got[0][1] is True and got[0][4] == 11.0, got
            assert any(r[1] is False for r in got[1:]), (
                "the body run was re-bolded — normalize_work_label_formatting clobbered it")
            return
    pytest.fail("the overridden paragraph is not in the generated document")


# ── never 500 on bad input ────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    {"id": 0, "runs": "nope"},
    {"id": 0, "runs": []},
    {"id": 0, "runs": [{"nope": 1}]},
    {"id": 0, "runs": [{"text": 5}]},
    {"id": 0, "runs": [{"text": "x", "size_pt": "big"}]},
    {"id": 0, "runs": [{"text": "x", "size_pt": 0}]},
    {"id": 0, "runs": [{"text": "x", "size_pt": 9999}]},
    {"id": 0, "runs": [{"text": "x", "bold": "yes"}]},
    {"id": 0, "runs": [None]},
])
def test_malformed_runs_never_raise(bad):
    """A stale draft or a hand-built request must not 500 /api/generate — the house rule for
    every sanitiser in this codebase."""
    d = docx.Document(str(GC_RESINOUS))
    pw._apply_paragraph_overrides(d, [bad])          # must not raise


def test_a_bad_size_falls_back_rather_than_writing_nonsense():
    d = docx.Document(str(GC_RESINOUS))
    idx, p_elem = _label_block(d)
    base_size = _runs(p_elem, d)[0][4]
    pw._apply_paragraph_overrides(d, [{"id": idx, "runs": [
        {"text": "x", "size_pt": 9999}]}])
    got = _runs(p_elem, d)[0][4]
    assert got != 9999, "an absurd size was written straight through"
    assert got == base_size, "a rejected size should leave the inherited one"


def test_media_runs_are_never_removed():
    """Kyle's templates anchor the letterhead AND every floating text box in runs of otherwise
    blank paragraphs. Dropping those would delete the letterhead from a customer document."""
    d = docx.Document(str(GC_RESINOUS))
    before = len(list(d.element.body.iter(pw.qn("w:drawing"))))
    assert before, "no drawings in the fixture — this test would prove nothing"
    for idx, _k, p_elem, in_block, _t, _tx in pw.iter_editable_blocks(d):
        if in_block is None and next(p_elem.iter(pw.qn("w:drawing")), None) is not None:
            pw._apply_paragraph_overrides(d, [{"id": idx, "runs": [{"text": "replaced"}]}])
            break
    assert len(list(d.element.body.iter(pw.qn("w:drawing")))) == before
