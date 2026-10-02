"""The NOTES box on page 1: where it prints, where the editor draws it, and what size its lines are.

Hanz, 2026-10-02, on staging, a GC epoxy draft: the first note sat above the box's top rule, every
bullet was drawn left of the box with the text running over the rotated "NOTES" label, and one note
("Treadwell is not responsible for wear & tear...") was drawn much larger than the rest. None of it
came from the release under review; all of it was on production. Three causes, each fixed and each
proven here by running the real code:

  1. THE PDF DRIFTED UP A PAGE. Page 1's boxes hang off empty Cambria paragraphs. Word lays each at
     Cambria's 14.07pt; LibreOffice, with Caladea standing in, at 13.8pt -- so every box anchored n
     paragraphs down printed n x 0.27pt higher than Kyle placed it (the GC/Gyp NOTES box, paragraph
     31, by 8.3pt: its first note above the rule). `_pin_anchor_line_heights` gives those paragraphs
     an at-least line Word already exceeds, and the editor's estimate is that same line.
  2. THE EDITOR IGNORED A WRAP. The GC and Gyp NOTES paragraph runs beside the REGARDS box (square
     wrap), so both renderers start its column after that box: 36.3pt (GC) / 39pt (Gyp) right of
     the margin arithmetic the editor used (`_wrap_column_shift`).
  3. A PLAIN EDIT LOOKED LIKE A CHOSEN SIZE. The editor sends every run's size back as it reads it
     off the page, so editing a NOTES line's words arrived with Kyle's own 7.5pt, and the shrink
     left that line at 7.5pt among 4.5pt neighbours. A size equal to the template's is not a choice.

The positions below were measured on 2026-10-03 from real PDFs: the production LibreOffice image
(backend/ops/terms_render_proof.py's container) rendering these templates filled by this code, each
text box given a visible outline. Word's own PDF export of the same files agrees within 0.55pt, and
Word's output did not change by a point with the line pin in place.
"""
import io

import docx
import pytest
from docx import Document
from docx.oxml.ns import qn

import main
import proposal_writer as pw
from test_editor_fit_parity import _V, _fit, _docx, _box_runs, _harness, _template, needs_node

# {(work_type, audience): {box id: (x_pt, y_pt) LibreOffice prints the box at}}
PRINTED = {
    ("epoxy", "Direct"): {0: (125.2, 36.0), 1: (18.35, 36.0), 2: (162.35, 152.9), 3: (162.25, 495.0),
                          4: (162.25, 321.35), 5: (23.3, 503.45)},
    ("polish", "Direct"): {0: (125.2, 36.0), 1: (18.35, 36.0), 2: (27.35, 504.0), 3: (162.0, 152.9),
                           4: (162.25, 321.35), 5: (162.3, 491.15)},
    ("combo", "Direct"): {0: (125.2, 36.0), 1: (18.35, 36.0), 2: (27.35, 504.0), 3: (162.0, 152.9),
                          4: (162.3, 492.95), 5: (162.25, 321.35)},
    ("polish", "GC"): {0: (125.2, 36.0), 1: (18.35, 36.0), 2: (27.35, 504.0), 3: (160.7, 153.85),
                       4: (161.15, 332.25), 5: (161.3, 509.1)},
    ("epoxy", "GC"): {0: (125.2, 36.0), 1: (18.35, 36.0), 2: (27.35, 504.0), 3: (161.8, 153.4),
                      4: (161.75, 332.8), 5: (161.95, 508.95)},
    ("sealer", "GC"): {0: (125.2, 36.0), 1: (18.35, 36.0), 2: (27.35, 504.0), 3: (160.7, 155.6),
                       4: (160.65, 329.85), 5: (160.65, 508.15)},
    ("gyp", "Direct"): {0: (125.2, 36.0), 1: (18.35, 36.0), 2: (161.35, 153.2), 3: (161.95, 361.1),
                        4: (27.0, 503.45), 5: (161.5, 511.2)},
}
# Where the artwork's NOTES rule ends (its lower edge), and the right edge of the label strip.
NOTES_RULE_BOTTOM = {("epoxy", "Direct"): 488.05, ("polish", "Direct"): 489.45, ("combo", "Direct"): 489.45,
                     ("polish", "GC"): 509.6, ("epoxy", "GC"): 509.6, ("sealer", "GC"): 509.6,
                     ("gyp", "Direct"): 509.6}
LABEL_STRIP_RIGHT = 156.0


def _geometry(wt, aud):
    return pw.template_geometry(docx.Document(str(pw.pick_template(wt, aud))))["boxes"]


def _notes_box_id(wt, aud):
    """The box holding the NOTES text: the one lowest-down 400pt-wide box."""
    return max((b for b in _geometry(wt, aud) if b["w_pt"] > 400), key=lambda b: b["y_pt"])["id"]


@pytest.mark.parametrize("wt,aud", sorted(PRINTED))
def test_the_editor_draws_every_page_one_box_where_the_pdf_prints_it(wt, aud):
    """Every box the editor places (what /api/proposal-template serves it) within 0.2pt of the
    rectangle the PDF prints, both axes. Before: the GC/Gyp NOTES box 36-39pt left, and every box
    hung off a deep paragraph up to 8pt off, in one direction or the other."""
    for b in _geometry(wt, aud):
        x, y = PRINTED[(wt, aud)][b["id"]]
        assert b["x_pt"] == pytest.approx(x, abs=0.2), (wt, aud, b["id"], "x", b["x_pt"], x)
        assert b["y_pt"] == pytest.approx(y, abs=0.2), (wt, aud, b["id"], "y", b["y_pt"], y)


@pytest.mark.parametrize("wt,aud", sorted(PRINTED))
def test_the_notes_box_starts_inside_its_frame(wt, aud):
    """Right of the label strip, and its top not above the artwork's rule by more than the rule is
    thick (the GC/Gyp box top meets the rule; Kyle placed it there in Word)."""
    b = next(g for g in _geometry(wt, aud) if g["id"] == _notes_box_id(wt, aud))
    assert b["x_pt"] > LABEL_STRIP_RIGHT, (wt, aud, b)
    assert b["y_pt"] >= NOTES_RULE_BOTTOM[(wt, aud)] - 1.5, (wt, aud, b)


def _filled(wt, aud):
    return Document(io.BytesIO(pw.fill_proposal(work_type=wt, audience=aud, values=dict(_V),
                                                notes=main._notes_for(wt, []))))


def _deepest_box_paragraph(d):
    body = d.element.body
    tops = [c for c in body if c.tag == qn("w:p")]
    deepest = -1
    for tx in pw._iter_txbx(d):
        a = pw._txbx_anchor(tx)
        if a is None or pw._anchor_offset(a, "positionV")[1] != "paragraph":
            continue
        deepest = max(deepest, tops.index(pw._top_level_of(body, a)))
    return tops, deepest


@pytest.mark.parametrize("wt,aud", sorted(PRINTED))
def test_the_paragraphs_page_one_hangs_off_print_at_the_editors_line(wt, aud):
    """In the generated document, every paragraph above the deepest box carries an AT-LEAST line of
    exactly the editor's estimate (`_ANCHOR_LINE_H_PT`), and nothing from that box down is touched,
    so the Terms pages are not. At-least: Word's taller Cambria line wins there, unchanged."""
    d = _filled(wt, aud)
    tops, deepest = _deepest_box_paragraph(d)
    assert deepest >= 5, "no page-1 box found"
    assert pw._ANCHOR_LINE_TW / 20.0 == pw._ANCHOR_LINE_H_PT
    for i, p in enumerate(tops):
        sp = p.find(qn("w:pPr") + "/" + qn("w:spacing"))
        line = sp.get(qn("w:line")) if sp is not None else None
        if i < deepest:
            assert (line, sp.get(qn("w:lineRule"))) == (str(pw._ANCHOR_LINE_TW), "atLeast"), (wt, aud, i)
    def pinned(p):
        sp = p.find(qn("w:pPr") + "/" + qn("w:spacing"))
        return (sp is not None and sp.get(qn("w:line")) == str(pw._ANCHOR_LINE_TW)
                and sp.get(qn("w:lineRule")) == "atLeast")
    assert not [p for p in tops[deepest:] if pinned(p)], (wt, aud)


# ── 3. a plain edit on a NOTES line shrinks with the lines around it ────────────────────────────
WEAR = "Treadwell is not responsible for wear"


def _gc_body(overrides):
    tpl = _template("epoxy", "GC")
    return {"work_type": "epoxy", "audience": "GC", "template_version": tpl["template_version"],
            "values": dict(_V), "paragraph_overrides": overrides}


def _wear_block():
    return next(b for b in _template("epoxy", "GC")["blocks"] if str(b["text"]).startswith(WEAR))


def _as_the_editor_sends(block, edit=None):
    """The block's runs as the page serializes them after a text edit: every run carries the size
    it is drawn at, which is the template's own (fmtAt reads the span's inline size)."""
    runs = [{"text": r["text"], "size_pt": r["size_pt"]} for r in block["runs"]]
    if edit:
        runs[0]["text"] = runs[0]["text"].replace("Treadwell", edit, 1)
    return {"id": block["id"], "text": "".join(r["text"] for r in runs), "runs": runs}


def test_a_plain_edit_on_a_notes_line_shrinks_with_its_neighbours():
    blk = _wear_block()
    box = blk["txbx"]
    plain = _gc_body([])
    edited = _gc_body([_as_the_editor_sends(blk, edit="TREADWELL")])
    f = next(b for b in _fit(edited) if b["id"] == box)
    assert f["scale"] < 0.999, "the GC NOTES box no longer shrinks, so this proves nothing"
    assert f["exempt"] == [], "a size equal to the template's was taken for the estimator's choice"
    # The document prints the edited line at the same scaled sizes as the unedited one.
    want = [hp for hp, t in _box_runs(_docx(plain))[box] if t and t.startswith(("Treadwell is not", "&", " tear",
                                                                                "ng from", "See Terms"))]
    got = [hp for hp, t in _box_runs(_docx(edited))[box] if t and t.startswith(("TREADWELL is not", "&", " tear",
                                                                                 "ng from", "See Terms"))]
    assert got and got == want and max(got) < 14, (got, want)


def test_a_size_the_estimator_did_choose_on_a_notes_line_is_still_left_alone():
    blk = _wear_block()
    ov = _as_the_editor_sends(blk)
    ov["runs"][0]["size_pt"] = 9                       # not the template's 7.5pt: a real choice
    f = next(b for b in _fit(_gc_body([ov])) if b["id"] == blk["txbx"])
    assert f["exempt"] == [blk["id"]]
    runs = _box_runs(_docx(_gc_body([ov])))[blk["txbx"]]
    assert [hp for hp, t in runs if t.startswith("Treadwell is not")] == [18]


@needs_node
def test_the_editor_draws_the_plainly_edited_notes_line_at_its_neighbours_size():
    """The route's real answer for that payload, handed to the page's real applyBoxFit: the edited
    line's spans get the same printed size as the line above it. Before: none (exempt), so the
    page showed it at 7.5pt among 4.5pt lines."""
    tpl = _template("epoxy", "GC")
    blk = _wear_block()
    body = _gc_body([_as_the_editor_sends(blk, edit="TREADWELL")])
    rep = {b["id"]: b for b in _fit(body)}
    case = _harness([{"name": "wear", "blocks": tpl["blocks"],
                      "fit": {str(k): v for k, v in rep.items()}, "tokens": body["values"]}])[0]
    got = {b["id"]: b for b in case["blocks"]}
    prev = max(i for i in got if i < blk["id"] and got[i]["txbx"] == blk["txbx"] and got[i]["spans"])
    mine = {s["printed"] for s in got[blk["id"]]["spans"] if s["printed"]}
    theirs = {s["printed"] for s in got[prev]["spans"] if s["printed"]}
    assert mine and mine <= theirs | {"4pt", "4.5pt"}, (mine, theirs)


@needs_node
def test_a_shrunk_notes_line_keeps_its_paragraph_mark_on_screen():
    """The writer scales runs, never the paragraph mark, and the mark (with the list bullet drawn at
    its size) sets how tall the line prints: 8.7pt apart for the GC's 4.5pt notes in the PDF. The
    page marks every shrunk paragraph that states its line spacing (`data-tw-mark`), which
    styles.css turns into a mark-sized strut; an unshrunk box and an exempt line get none."""
    tpl = _template("epoxy", "GC")
    body = _gc_body([])
    rep = {b["id"]: b for b in _fit(body)}
    blk = _wear_block()
    case = _harness([{"name": "marks", "blocks": tpl["blocks"],
                      "fit": {str(k): v for k, v in rep.items()}, "tokens": body["values"]}])[0]
    notes = [b for b in case["blocks"] if b["txbx"] == blk["txbx"]]
    stated = {b["id"] for b in tpl["blocks"] if b["txbx"] == blk["txbx"]
              and (b.get("para") or {}).get("spacing", {}).get("line")}
    assert stated, "no NOTES paragraph states its line spacing"
    assert {b["id"] for b in notes if b.get("twMark")} == {b["id"] for b in notes if b["id"] in stated and b["printed"]}
    assert all(not b.get("twMark") for b in case["blocks"] if rep[b["txbx"]]["scale"] >= 0.999)
