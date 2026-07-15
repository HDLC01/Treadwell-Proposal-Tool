"""PRICE section formatting: NO bullets (flush-left), bold amounts.

Every proposal template authors its PRICE rows (base bid, Material Sales Tax,
Remodel, Total, {{#price_line}} options, {{#room}}, {{#alternate}}) on list
numId=3 — a RED SQUARE bullet (Wingdings filled square, #A71320). Kyle wants the
PRICING to read as clean flush-left lines with NO bullets (confirmed by Hanz
2026-07-16, reversing an earlier "keep the red squares" pass), so
`_flatten_price_bullets` strips numId=3 at generate time. The WORK (numId 4) and
Terms (numId 5) lists keep their bullets, and the amount runs stay bold (already
bold in the templates; token fill preserves run formatting).
"""
import io
import re
import zipfile

from fastapi.testclient import TestClient

import main
import proposal_writer as pw

client = TestClient(main.app)

_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


def _rendered_lines(docx_bytes):
    from docx import Document
    d = Document(io.BytesIO(docx_bytes))
    out = []
    for p in d.element.xpath("//w:p"):
        if any(True for _ in p.iterancestors(f"{_MC}Fallback")):
            continue
        t = "".join(x.text or "" for x in p.xpath(".//w:t")).strip()
        if t:
            out.append(t)
    return out


def _xml(docx_bytes):
    return zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode("utf-8")


def _vals(**over):
    v = {
        "job_name": "Fmt QA", "project_name": "Fmt QA", "city_state": "Olathe, KS",
        "bid_date_formatted": "7/15/26", "system_name": "MACRO", "texture": "OP",
        "epoxy_sf": "12,000", "cove_lf": "250", "disposal": "d", "schedule_notes": "~5d",
        "scope_notes": "scope", "total_formatted": "$63,801.00", "state_name": "Kansas",
        "base_bid_formatted": "$58,523.00", "material_tax_formatted": "$2,639.00",
        "estimator_name": "Kyle", "site_visit_phrase": "per site visit on 7/15",
        "base_tax_phrase": "(material sales tax INCLUDED)", "exclusions": "std",
    }
    v.update(over)
    return v


def test_epoxy_price_rows_flush_no_bullets_bold_amounts():
    vals = _vals()
    systems = main._build_epoxy_systems({}, vals, [{"name": "MACRO Flake", "sf": 12000, "lf": 250}])
    out = pw.fill_proposal(work_type="epoxy", audience="Direct", values=vals, systems=systems,
                           price_lines=[{"amount_formatted": "$2,500", "label": "Add VE"}])
    xml = _xml(out)
    # PRICE rows are FLUSH — every numId=3 list bullet is stripped; the WORK (4)
    # and Terms (5) lists keep theirs.
    assert xml.count('<w:numId w:val="3"') == 0
    assert xml.count('<w:numId w:val="4"') > 0
    assert xml.count('<w:numId w:val="5"') > 0
    # Amounts stay bold (base bid + option line) — flattening only removes numbering.
    for amt in ("58,523", "2,500"):
        para = next(p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.S)
                    if amt in "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))
        run0 = re.search(r"<w:r\b.*?</w:r>", para, re.S).group(0)
        assert re.search(r"<w:b[ />]", run0), f"amount {amt} run not bold"


def test_polish_and_gyp_price_rows_flush_no_bullets():
    # Polish (option/alternate list) + Gyp (underlayment) both drop numId=3
    # (the red-square PRICE list) so the pricing reads flush-left.
    pv = _vals(base_bid_formatted="$14,391.00", total_formatted="$16,707.00")
    pout = pw.fill_proposal(work_type="polish", audience="Direct", values=pv,
                            price_lines=[{"amount_formatted": "$1,100", "label": "Polish Add Dye"}])
    assert _xml(pout).count('<w:numId w:val="3"') == 0

    gv = _vals(gyp_soft_sf="27,825", gyp_hard_sf="11,795", gyp_corridor_sf="5,655",
               gyp_soft_thickness='3/4"', gyp_hard_thickness='1"', gyp_corridor_thickness='3/4"',
               mobilizations_line="1 Mobilization to Site.", work_description="per plans",
               base_bid_formatted="$98,000.00", tax_amount_formatted="$0.00",
               total_formatted="$103,364.00")
    gout = pw.fill_proposal(work_type="gyp", audience="Direct", values=gv)
    assert _xml(gout).count('<w:numId w:val="3"') == 0


def test_double_spacing_before_options_heading():
    # Kyle: double spacing after the base-bid Total. _space_before_options inserts
    # 2 blank paragraphs immediately before each "Options" heading (both the
    # mc:Choice and mc:Fallback copies of the text box).
    pv = _vals(system_name="Polish", base_bid_formatted="$13,614.00",
               total_formatted="$14,973.00")
    out = pw.fill_proposal(work_type="polish", audience="Direct", values=pv, has_options=True,
                           price_lines=[{"amount_formatted": "$1,927", "label": "Polish Add Dye"}])
    from docx import Document
    d = Document(io.BytesIO(out))
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paras = d.element.findall(".//" + W + "txbxContent//" + W + "p")
    txts = ["".join(t.text or "" for t in p.findall(".//" + W + "t")).strip() for p in paras]
    found = False
    for i, t in enumerate(txts):
        if t == "Options":
            assert i >= 2 and txts[i - 1] == "" and txts[i - 2] == "", \
                f"expected 2 blank paragraphs before 'Options' at {i}, got {txts[i-2:i]!r}"
            found = True
    assert found, "no 'Options' heading found to check spacing"


def test_polish_options_heading_precedes_option_lines():
    # Kyle's Polish Direct template authored the "Options" heading at the BOTTOM
    # (after the {{#price_line}} rows + {{#alternate}}); it was moved to render
    # ABOVE the option lines like Epoxy/Combo so a "Polish Add Dye" option reads
    # under its heading. Assert order at the writer level (no /api/generate — the
    # option-line contract there is separate and tested elsewhere).
    pv = _vals(system_name="Polish", base_bid_formatted="$15,257.00",
               total_formatted="$16,707.00")
    out = pw.fill_proposal(work_type="polish", audience="Direct", values=pv,
                           has_options=True,
                           price_lines=[{"amount_formatted": "$1,100",
                                         "label": "Polish Add Dye"}])
    # The price block renders both as separate paragraphs AND as one text-box
    # paragraph with <w:br> breaks (python-docx concatenates the latter), so
    # compare order within the joined text rather than by paragraph index.
    full = "\n".join(_rendered_lines(out))
    opt_at, add_at = full.find("Options"), full.find("Polish Add Dye")
    assert opt_at != -1 and add_at != -1, "Options heading / Add option line missing"
    assert opt_at < add_at, f"Options heading (@{opt_at}) must precede the Add line (@{add_at})"
