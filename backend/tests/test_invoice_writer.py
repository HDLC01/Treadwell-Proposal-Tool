"""Deposit invoice built from Kyle's real Invoice_Deposit.docx.

The template hides two traps and both are pinned here:
  * every string exists TWICE (Word's mc:Choice + the legacy VML mc:Fallback),
    so a fill that stops at the first match leaves LibreOffice free to render
    the stale copy;
  * values are split across runs ("23.150-01" is "23" + ".150-01"), so matching
    must happen on the paragraph's concatenated text.
"""
import io
import re
import zipfile

import pytest

import invoice_writer as iw
import proposal_writer

TEMPLATE = proposal_writer.TEMPLATES_ROOT / iw.TEMPLATE_NAME

SRC = {
    "customer_name": "Westport Retail Center LLC",
    "customer_address": "4600 Madison Ave, Suite 200",
    "city_state": "Kansas City, MO 64112",
    "contract_value": 32985.00,
    "deposit_amount": 8246.25,
    "total_due": 8246.25,
    "invoice_no": "26.114-01",
    "job_number": "26.114",
    "job_name": "Westport Retail Center",
    "invoice_date": "2026-07-28",
}


def _xml(docx_bytes: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode("utf8")


def test_template_is_committed():
    assert TEMPLATE.is_file(), "Invoice_Deposit.docx must ship in backend/templates/"


# ── field shaping (pure) ─────────────────────────────────────────────────────
def test_fields_derive_the_deposit_line_from_the_contract_value():
    f = iw.invoice_fields(SRC)
    assert f["deposit_line"] == "Deposit (25% of $32,985.00 contract value)"
    assert f["deposit_amount"] == "$8,246.25"
    assert f["total_due"] == "$8,246.25"


def test_fields_format_the_date_like_the_template():
    assert iw.invoice_fields(SRC)["invoice_date"] == "7/28/2026"      # M/D/YYYY, as 12/6/2023


def test_staff_edits_win_over_derived_values():
    """The whole point of the review step: a human can correct the document."""
    f = iw.invoice_fields({**SRC, "deposit_line": "Deposit — agreed at kickoff",
                           "deposit_amount_text": "$1.00", "invoice_date_text": "1/2/2027"})
    assert f["deposit_line"] == "Deposit — agreed at kickoff"
    assert f["deposit_amount"] == "$1.00"
    assert f["invoice_date"] == "1/2/2027"


def test_fields_tolerate_an_empty_source():
    f = iw.invoice_fields({})
    assert f["customer_name"] == "Customer Name"    # template's own placeholder, never blank
    assert f["invoice_date"]                        # defaults to today


# ── the fill ─────────────────────────────────────────────────────────────────
def test_fill_rewrites_both_the_choice_and_fallback_copies():
    x = _xml(iw.build_invoice_docx(SRC, TEMPLATE))
    # Word stores each shape twice; a value must land in BOTH or LibreOffice can
    # render the stale one.
    for value in ("Westport Retail Center LLC", "26.114-01", "7/28/2026"):
        assert len(re.findall(re.escape(value), x)) == 2, value


def test_fill_leaves_no_placeholder_behind():
    x = _xml(iw.build_invoice_docx(SRC, TEMPLATE))
    for stale in ("Customer Name", "Customer Address", "City State",
                  "23.150-01", "12/6/2023", "$650.00", "xxxx"):
        assert stale not in x, stale


def test_fill_keeps_the_static_boilerplate():
    x = _xml(iw.build_invoice_docx(SRC, TEMPLATE))
    assert "Payment " in x and "upon receipt" in x
    assert "ccounting@WeTreadwell.com" in x          # split run in the template
    assert "Material cannot be ordered until deposit is received" in x


def test_values_split_across_runs_are_matched_whole():
    """job number 23.150 and invoice 23.150-01 are distinct paragraphs even
    though the runs overlap — neither may bleed into the other."""
    x = _xml(iw.build_invoice_docx(SRC, TEMPLATE))
    assert len(re.findall(r"26\.114-01", x)) == 2
    # the bare job number also appears twice, and never as part of the invoice no.
    assert len(re.findall(r">26\.114<", x)) == 2


def test_template_on_disk_is_never_modified():
    before = TEMPLATE.read_bytes()
    iw.build_invoice_docx(SRC, TEMPLATE)
    assert TEMPLATE.read_bytes() == before


def test_unrecognised_template_raises_rather_than_shipping_a_blank():
    """If Kyle rewords the template, fail loudly instead of emailing a document
    still showing 'Customer Name'."""
    import docx
    blank = io.BytesIO()
    docx.Document().save(blank)
    blank.seek(0)
    tmp = TEMPLATE.parent / "_test_blank.docx"
    tmp.write_bytes(blank.read())
    try:
        with pytest.raises(RuntimeError, match="no placeholders matched"):
            iw.build_invoice_docx(SRC, tmp)
    finally:
        tmp.unlink(missing_ok=True)


# ── shrink-to-fit ────────────────────────────────────────────────────────────
# LibreOffice ignores docx text-box autofit, so a value longer than the
# placeholder clips or wraps out of its box. The first real render showed
# "TW-INV-01001" printing as "TW-" and "$19,767.50" breaking across two lines.
def test_fit_scale_only_ever_shrinks():
    assert iw._fit_scale("23.150-01", "26.114-01") == 1.0        # same length → untouched
    assert iw._fit_scale("23.150-01", "26.1") == 1.0             # shorter → never grows
    assert iw._fit_scale("23.150-01", "TW-INV-01001") < 1.0


def test_fit_scale_has_a_readability_floor():
    """Past ~65% the field is genuinely too long and should be shortened
    upstream — shrinking further just produces unreadable print."""
    assert iw._fit_scale("xxxxxx", "x" * 200) == 0.65


def test_long_values_get_smaller_runs_so_they_do_not_clip():
    """Compare like for like: every field short except the one under test, so the
    only difference in run sizes is the shrink applied to the long value."""
    short = {k: "1" for k in ("customer_name", "customer_address", "city_state",
                              "job_name", "job_number", "invoice_no")}
    short.update(deposit_line="D", deposit_amount_text="$1", total_due_text="$1",
                 invoice_date_text="1/1/26")
    sizes = lambda src: [int(m) for m in re.findall(r'<w:sz w:val="(\d+)"/>',
                                                    _xml(iw.build_invoice_docx(src, TEMPLATE)))]
    base = sizes(short)
    long_no = sizes({**short, "invoice_no": "TW-INV-01001-EXTRA-LONG-NUMBER"})
    assert min(long_no) < min(base), "an overflowing value must shrink its runs"


def test_shrinking_never_produces_a_vanishing_font():
    x = _xml(iw.build_invoice_docx({**SRC, "job_name": "J" * 300}, TEMPLATE))
    import re
    for hp in (int(m) for m in re.findall(r'<w:sz w:val="(\d+)"/>', x)):
        assert hp >= 10, "half-points floor keeps text legible"
