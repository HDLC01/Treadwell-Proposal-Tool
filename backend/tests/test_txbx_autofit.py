"""Text-box autofit estimate (proposal_writer._estimate_txbx_scale). This is what
keeps a combo's long WORK content (two options + exclusions) from spilling past
its fixed box and getting clipped by the PRICE frame in the LibreOffice PDF —
the estimate is baked as an explicit <a:normAutofit fontScale=…> the renderer
honors (an empty normAutofit is a no-op in LibreOffice)."""
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
