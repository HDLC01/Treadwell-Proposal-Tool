"""PRICE section formatting: no bullets, bold amounts (Kyle: "prices should be
bold and no bullet points in the pricing").

Every proposal template puts its PRICE rows (base bid, Material Sales Tax,
Remodel, Total, {{#price_line}} options, {{#room}}, {{#alternate}}) on list
numId=3; NOTES (numId 1), the WORK section (numId 4), and Terms (numId 5) keep
their bullets. proposal_writer._flatten_price_bullets strips numId=3 at render
time so the amounts read as clean flush-left lines, and the amount runs stay
bold (already bold in the templates; token fill preserves run formatting).
"""
import io
import re
import zipfile

import main
import proposal_writer as pw


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


def test_epoxy_price_rows_have_no_bullets_and_bold_amounts():
    vals = _vals()
    systems = main._build_epoxy_systems({}, vals, [{"name": "MACRO Flake", "sf": 12000, "lf": 250}])
    out = pw.fill_proposal(work_type="epoxy", audience="Direct", values=vals, systems=systems,
                           price_lines=[{"amount_formatted": "$2,500", "label": "Add VE"}])
    xml = _xml(out)
    # numId=3 (the PRICE list) is fully stripped; WORK (4) + Terms (5) survive.
    assert xml.count('<w:numId w:val="3"') == 0
    assert xml.count('<w:numId w:val="4"') > 0
    assert xml.count('<w:numId w:val="5"') > 0
    # Amounts stay bold (base bid + option line).
    for amt in ("58,523", "2,500"):
        para = next(p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.S)
                    if amt in "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))
        run0 = re.search(r"<w:r\b.*?</w:r>", para, re.S).group(0)
        assert re.search(r"<w:b[ />]", run0), f"amount {amt} run not bold"


def test_polish_and_gyp_price_rows_have_no_bullets():
    # Polish (option/alternate list) + Gyp (underlayment) both strip numId=3.
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
