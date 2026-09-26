"""Text-box autofit estimate (proposal_writer._estimate_txbx_scale). This is what
keeps a combo's long WORK content (two options + exclusions) from spilling past
its fixed box and getting clipped by the PRICE frame in the LibreOffice PDF —
the estimate is baked as an explicit <a:normAutofit fontScale=…> the renderer
honors (an empty normAutofit is a no-op in LibreOffice)."""
import math

import proposal_writer as pw
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn


def _txbx(paras, sz_halfpt=18):
    ps = "".join(
        f'<w:p><w:r><w:rPr><w:sz w:val="{sz_halfpt}"/></w:rPr><w:t>{t}</w:t></w:r></w:p>'
        for t in paras
    )
    return parse_xml(f'<w:txbxContent {nsdecls("w")}>{ps}</w:txbxContent>')


def test_fits_returns_full_scale():
    txbx = _txbx(["Short line of text"])
    assert pw._estimate_txbx_scale(txbx, {"w_pt": 400, "h_pt": 200}) == 1.0


def test_overflow_shrinks_within_floor():
    long = "x" * 400
    txbx = _txbx([long] * 6)                      # far more content than the box holds
    scale = pw._estimate_txbx_scale(txbx, {"w_pt": 400, "h_pt": 60})
    assert scale < 1.0
    assert scale >= pw._TXBX_SCALE_FLOOR          # never shrinks below the readable floor


def test_unknown_geometry_is_safe_noop():
    txbx = _txbx(["anything"])
    assert pw._estimate_txbx_scale(txbx, None) == 1.0
    assert pw._estimate_txbx_scale(txbx, {"w_pt": None, "h_pt": None}) == 1.0
    assert pw._estimate_txbx_scale(txbx, {"w_pt": 0, "h_pt": 0}) == 1.0


def test_moderate_overflow_is_partial_shrink():
    # ~2x the height it should need → a partial shrink, not the floor.
    line = "y" * 80
    txbx = _txbx([line] * 8)
    scale = pw._estimate_txbx_scale(txbx, {"w_pt": 420, "h_pt": 90})
    assert pw._TXBX_SCALE_FLOOR <= scale < 1.0


def _sizes(txbx):
    return [int(sz.get(qn("w:val"))) for sz in txbx.iter(qn("w:sz"))]


def test_scale_runs_reduces_explicit_sizes():
    # LibreOffice ignores autofit, so we scale the actual run sizes.
    txbx = _txbx(["Line one", "Line two"], sz_halfpt=18)   # 9pt
    pw._scale_txbx_runs(txbx, 0.5)
    sizes = _sizes(txbx)
    assert sizes and all(s == 9 for s in sizes)            # 18 * 0.5 → 9 half-points (4.5pt)


def test_scale_runs_floors_small_text():
    txbx = _txbx(["x"], sz_halfpt=10)                      # 5pt
    pw._scale_txbx_runs(txbx, 0.1)
    assert min(_sizes(txbx)) >= 8                          # never below the 4pt floor


# ── the estimate counts each paragraph's indents (2026-09-26 editor release) ───────────────────
def _txbx_ind(paras):
    """`paras` = [(text, ind attrs, numbered)]: one 9pt run each, the paragraph's own w:ind."""
    ps = []
    for text, ind, numbered in paras:
        attrs = " ".join(f'w:{k}="{v}"' for k, v in (ind or {}).items())
        num = '<w:numPr><w:ilvl w:val="1"/><w:numId w:val="3"/></w:numPr>' if numbered else ""
        ppr = f"<w:pPr>{num}<w:ind {attrs}/></w:pPr>" if (attrs or num) else ""
        ps.append(f'<w:p>{ppr}<w:r><w:rPr><w:sz w:val="18"/></w:rPr><w:t>{text}</w:t></w:r></w:p>')
    return parse_xml(f'<w:txbxContent {nsdecls("w")}>{"".join(ps)}</w:txbxContent>')


# 200pt x 400pt usable inside the default insets (0.1in left and right, 0.05in top and bottom).
_BOX = {"w_pt": 200 + 14.4, "h_pt": 400 + 7.2}


def test_an_indent_narrows_every_line_the_estimate_counts():
    """A line typed under a price line prints its text one inch in (the REBID "o", 1440 twips). The
    estimate used to count it at the box's full width, so its wrapped lines were free and a box of
    them printed past its bottom edge while the shrink said it fit. At 9pt a 200pt line holds 44
    characters; one inch in it holds 28. Mutation: every paragraph measured at the full width."""
    text = "x" * 88                                          # two full lines at 0, four one inch in
    flush = pw._estimate_txbx_fit(_txbx_ind([(text, None, False)]), _BOX)[1]
    inch = pw._estimate_txbx_fit(_txbx_ind([(text, {"left": 1440}, False)]), _BOX)[1]
    right = pw._estimate_txbx_fit(_txbx_ind([(text, {"right": 1440}, False)]), _BOX)[1]
    line = pw._TXBX_LINE_H * 9
    assert (flush, inch, right) == (2 * line, 4 * line, 4 * line), (flush, inch, right)


def test_a_hanging_first_line_is_wider_unless_the_paragraph_is_on_a_list():
    """A plain paragraph's first line starts `hanging` twips left of the rest; a bulleted one puts
    its marker there and its text at the left indent, so its first line is no wider."""
    ind = {"left": 288, "hanging": 288}
    plain = _txbx_ind([("x", ind, False)]).find(qn("w:p"))
    listed = _txbx_ind([("x", ind, True)]).find(qn("w:p"))
    assert pw._fit_line_widths_pt(None, plain, 200.0) == (200.0, 185.6)
    assert pw._fit_line_widths_pt(None, listed, 200.0) == (185.6, 185.6)
    # 84 characters: the plain paragraph's wider first line (44.4 of them at 9pt) leaves 40 for
    # one more line of 41.2; the listed one wraps 41.2 at a time, into three.
    text = "x" * 44 + "y" * 40
    line = pw._TXBX_LINE_H * 9
    assert pw._estimate_txbx_fit(_txbx_ind([(text, ind, False)]), _BOX)[1] == 2 * line
    assert pw._estimate_txbx_fit(_txbx_ind([(text, ind, True)]), _BOX)[1] == 3 * line


def test_a_flush_box_estimates_exactly_as_before():
    """Nothing indented, nothing changed: at 0 indent every paragraph has the box's width, and the
    count is the old ceil(len / chars_per_line), to the float."""
    cpl = max(1.0, 200.0 / (pw._TXBX_GLYPH_W * 9))
    for n in (0, 1, 44, 45, 88, 89, 133, 400, 401):
        got = pw._estimate_txbx_fit(_txbx_ind([("x" * n, None, False)]), _BOX)[1]
        assert got == max(1, math.ceil(n / cpl)) * pw._TXBX_LINE_H * 9, n
