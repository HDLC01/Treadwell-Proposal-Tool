"""PRICE section formatting: Kyle's REBID bullets, bold amounts.

Every proposal template authors its PRICE rows (base bid, Material Sales Tax,
Remodel, Total, {{#price_line}} options, {{#room}}, {{#alternate}}) on list
numId=3 — a RED SQUARE bullet (Wingdings filled square, #A71320). From 2026-07-16
to 2026-09-25 the render stripped it (`_flatten_price_bullets`, PR #132: "clean
flush-left lines with NO bullets"). Hanz reversed that on 2026-09-25, with the
rule in front of him: the price box reads like Kyle's hand-made "Nickell RC
Sustainment REBID" proposal, a red square on every money line. So these tests now
pin the OPPOSITE of what they used to — every money row prints on the PRICE list,
placed by its level (not tucked into the margin with `w:ind left=0`, which is how
the Direct files hid the square) — and the WORK (numId 4) and Terms (numId 5)
lists keep theirs. The whole layout, the ribbon's overrides and the screen/paper
parity are test_price_bullets.py. The amount runs stay bold.
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


def _price_rows_by_text(out):
    """{first words: (numId, ilvl, own w:ind)} for every non-empty paragraph, mc:Fallback excluded."""
    from docx import Document
    d = Document(io.BytesIO(out))
    rows = {}
    for p in d.element.xpath("//w:p"):
        if any(True for _ in p.iterancestors(f"{_MC}Fallback")):
            continue
        t = pw._own_text(p).strip()
        if not t:
            continue
        ref = pw._para_num_ref(p)
        ind = p.find(pw.qn("w:pPr") + "/" + pw.qn("w:ind")) if p.find(pw.qn("w:pPr")) is not None else None
        own = {k.split("}")[1]: v for k, v in ind.attrib.items()} if ind is not None else {}
        rows.setdefault(t, (ref, own))
    return rows


def _row(rows, start):
    hit = [v for k, v in rows.items() if k.startswith(start)]
    assert hit, (start, sorted(rows)[:40])
    return hit[0]


def test_epoxy_price_rows_carry_rebid_bullets_bold_amounts():
    vals = _vals()
    systems = main._build_epoxy_systems({}, vals, [{"name": "MACRO Flake", "sf": 12000, "lf": 250}])
    out = pw.fill_proposal(work_type="epoxy", audience="Direct", values=vals, systems=systems,
                           price_lines=[{"amount_formatted": "$2,500", "label": "Add VE"}])
    xml = _xml(out)
    # The PRICE rows are on the PRICE list (numId 3) again; the WORK (4) and Terms (5) lists
    # keep theirs.
    assert xml.count('<w:numId w:val="3"') > 0
    assert xml.count('<w:numId w:val="4"') > 0
    assert xml.count('<w:numId w:val="5"') > 0
    # Every money row: a square on level 0, placed by the level (no tucked `left=0`).
    rows = _price_rows_by_text(out)
    for start in ("$58,523.00 – Epoxy flooring", "$2,500 – Add VE"):
        ref, own = _row(rows, start)
        assert ref == ("3", "0"), (start, ref)
        assert "left" not in own and "start" not in own, (start, own)
    # ...and the headings carry none.
    assert _row(rows, "Base Bid")[0] is None
    # Amounts stay bold (base bid + option line).
    for amt in ("58,523", "2,500"):
        para = next(p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.S)
                    if amt in "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)))
        run0 = re.search(r"<w:r\b.*?</w:r>", para, re.S).group(0)
        assert re.search(r"<w:b[ />]", run0), f"amount {amt} run not bold"


def test_polish_and_gyp_price_rows_carry_rebid_bullets():
    # Polish (its base line is a plain template paragraph, the option a {{#price_line}} row) and
    # Gyp (underlayment: every price row a plain paragraph) print their money rows on the PRICE
    # list, placed by its level.
    pv = _vals(base_bid_formatted="$14,391.00", total_formatted="$16,707.00")
    pout = pw.fill_proposal(work_type="polish", audience="Direct", values=pv,
                            price_lines=[{"amount_formatted": "$1,100", "label": "Polish Add Dye"}])
    prow = _price_rows_by_text(pout)
    for start in ("$14,391.00 – Polished Con", "$1,100 – Polish Add Dye"):
        ref, own = _row(prow, start)
        assert ref == ("3", "0") and "left" not in own, (start, ref, own)

    gv = _vals(gyp_soft_sf="27,825", gyp_hard_sf="11,795", gyp_corridor_sf="5,655",
               gyp_soft_thickness='3/4"', gyp_hard_thickness='1"', gyp_corridor_thickness='3/4"',
               mobilizations_line="1 Mobilization to Site.", work_description="per plans",
               base_bid_formatted="$98,000.00", tax_amount_formatted="$0.00",
               total_formatted="$103,364.00")
    gout = pw.fill_proposal(work_type="gyp", audience="Direct", values=gv)
    grow = _price_rows_by_text(gout)
    for start in ("$98,000.00 – Gypsum Under", "1 Mobilization to Site."):
        assert _row(grow, start)[0] == ("3", "0"), (start, _row(grow, start))


def test_double_spacing_before_options_heading():
    # Kyle: double spacing after the base-bid Total. The writer prints the editor's count
    # (price_overrides.options_gap, default 2) of blank 9pt paragraphs directly above the
    # Options heading, in both text-box copies, on EVERY template -- not only on a heading
    # reading exactly "Options", which is the old helper's rule and why Epoxy and Combo
    # ("Options:") printed none. The cross-template contract is test_options_gap.py; this
    # keeps the Polish case it always covered, now with the size the old bare <w:p/> lacked.
    pv = _vals(system_name="Polish", base_bid_formatted="$13,614.00",
               total_formatted="$14,973.00")
    out = pw.fill_proposal(work_type="polish", audience="Direct", values=pv, has_options=True,
                           price_lines=[{"amount_formatted": "$1,927", "label": "Polish Add Dye"}])
    from docx import Document
    d = Document(io.BytesIO(out))
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paras = d.element.findall(".//" + W + "txbxContent//" + W + "p")
    txts = ["".join(t.text or "" for t in p.findall(".//" + W + "t")).strip() for p in paras]
    found = 0
    for i, t in enumerate(txts):
        if t == "Options":
            assert i >= 3 and txts[i - 1] == "" and txts[i - 2] == "" and txts[i - 3] != "", \
                f"expected exactly 2 blank paragraphs before 'Options' at {i}, got {txts[i-3:i]!r}"
            for blank in paras[i - 2:i]:
                assert blank.find(W + "pPr/" + W + "rPr/" + W + "sz").get(W + "val") == "18"
            found += 1
    assert found == 2, "expected the 'Options' heading in both text-box copies"


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
