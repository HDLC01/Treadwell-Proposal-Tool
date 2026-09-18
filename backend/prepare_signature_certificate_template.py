"""One-shot: build `templates/Signature_Certificate.docx` from Treadwell's letterhead.

Run it when the letterhead OR the layout below changes, then commit the .docx it
writes:

    python backend/prepare_signature_certificate_template.py

WHY A GENERATOR AND NOT A HAND-MADE FILE.

Same reason as `prepare_cover_letter_templates.py`, and one more that only
applies here. The certificate is the evidentiary half of a signed contract: its
whole job is to say, in print, exactly which document was signed, by whom, when,
from where, and under which consent wording. Every field on it is a fact a court
would be read. A file somebody edits in Word is a file where a row can be
deleted, a label can drift away from the value it names, and nobody finds out —
`certificate_writer` fills what the template offers and cannot invent a row that
is not there. Generating it means the layout is reviewable as a diff and the
token list is checkable by a test (`test_signed_contract.py`).

THE LETTERHEAD IS COPIED BYTE-FOR-BYTE and then appended to, exactly as the
cover letters are. Its page-one artwork is a full-page transparent PNG anchored
inside a `w:sdt` ("Cover Pages" content control): the bison mark sits top-right
above the 1.625" top margin and the address strip + red bar sit below the 1.375"
bottom margin, so the certificate body has a 7.25" x 8.0" clear column between
them and nothing about the anchor, the two-section page setup or the theme is
touched.

ONE PAGE, BY BUDGET.

`certificate_writer` appends every page the render produces and shouts if there
is more than one (a dropped page of evidence is the worse failure), but the
layout is sized so there is only ever one. Measured against the 8.0" (576pt)
column: title ~22pt, six section headings ~19pt each, thirteen label rows ~12pt
each, the consent statement ~4 lines, two 64-char hashes on one mono line apiece,
and the closing sentence — about 440pt with every free-text field at a realistic
length. The two fields with no upper bound are `options_summary` and
`user_agent`; both are given the full measure and can wrap several lines before
the budget is at risk.

WHY `{{tokens}}` HERE AND SQUARE BRACKETS IN THE COVER LETTERS. Opposite jobs.
A cover letter's "[THICKNESS - pick one: ...]" is copy nobody has approved yet
and must print as itself so a human sees it. A `{{token}}` here is a fill point:
`certificate_writer` refuses to return a document that still contains one, which
is the same discipline `_ensure_value_aliases` enforces on the proposal — a
customer-facing document can never show a literal token.

Source file (kept OUT of the image; reference material, not a runtime input):
    docs/Cover Letter/Treadwell Letterhead.docx
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import docx
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

REPO_ROOT = Path(__file__).resolve().parent.parent
LETTERHEAD = REPO_ROOT / "docs" / "Cover Letter" / "Treadwell Letterhead.docx"
OUT_PATH = Path(__file__).resolve().parent / "templates" / "Signature_Certificate.docx"

# ── House formatting ─────────────────────────────────────────────────────────
# Arial and Courier New because the container substitutes Liberation Sans/Mono
# for them metric-for-metric (see pdf_writer's fidelity note), so what is
# measured here is what LibreOffice lays out in production. Treadwell red is the
# A91120 the letterhead's own headings use.
BODY_FONT = "Arial"
MONO_FONT = "Courier New"
TITLE_PT = Pt(14)
HEAD_PT = Pt(10)
BODY_PT = Pt(9)
MONO_PT = Pt(9)
TREADWELL_RED = RGBColor(0xA9, 0x11, 0x20)
INK = RGBColor(0x26, 0x26, 0x26)
GREY = RGBColor(0x59, 0x59, 0x59)

# A hanging indent, not a table. The label sits at the left margin, the value
# starts at 1.85" and any wrap returns to 1.85" rather than to the margin — so a
# three-line user-agent string stays visually one field. A table would do the
# same and bring borders, a style name and cell margins that LibreOffice and Word
# resolve differently; this is two paragraph properties and a tab stop.
VALUE_COL = Inches(1.85)


def _run(p, text, *, font=BODY_FONT, size=BODY_PT, color=INK, bold=False, italic=False):
    r = p.add_run(text)
    r.font.name = font
    r.font.size = size
    r.font.color.rgb = color
    r.bold = bold
    r.italic = italic
    return r


def _mark(p, font, size):
    """Size the PARAGRAPH MARK too.

    Word gives a line the height of the tallest thing on it and the invisible `¶`
    counts, so a mark left at the theme default (11pt Calibri) makes a 9pt row
    11pt tall — thirteen of those is a quarter inch of the one-page budget spent
    on nothing. `CT_PPr` has no accessor for `w:rPr` (python-docx models the
    properties it edits, not the mark), so it is placed by hand. Same technique,
    same reason, as `prepare_cover_letter_templates._set_mark_size`; duplicated
    rather than imported because that module's import-time constants pull in the
    whole cover-letter copy table."""
    ppr = p._p.get_or_add_pPr()
    rpr = ppr.find(qn("w:rPr"))
    if rpr is None:
        rpr = OxmlElement("w:rPr")
        ppr.append(rpr)                    # after the spacing/indent/tabs group
    rf = OxmlElement("w:rFonts")
    rf.set(qn("w:ascii"), font)
    rf.set(qn("w:hAnsi"), font)
    rpr.append(rf)
    for tag in ("w:sz", "w:szCs"):
        el = OxmlElement(tag)
        el.set(qn("w:val"), str(int(round(size.pt * 2))))     # half-points
        rpr.append(el)


def _para(d, *, space_before=None, space_after=None, font=BODY_FONT, size=BODY_PT,
          left_indent=None, first_line_indent=None, tab_at=None):
    p = d.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = space_before if space_before is not None else Pt(0)
    pf.space_after = space_after if space_after is not None else Pt(0)
    if left_indent is not None:
        pf.left_indent = left_indent
    if first_line_indent is not None:
        pf.first_line_indent = first_line_indent
    if tab_at is not None:
        pf.tab_stops.add_tab_stop(tab_at, WD_TAB_ALIGNMENT.LEFT)
    _mark(p, font, size)
    return p


def _title(d, text):
    p = _para(d, space_after=Pt(2), font=BODY_FONT, size=TITLE_PT)
    _run(p, text, size=TITLE_PT, color=TREADWELL_RED, bold=True)
    return p


def _section(d, text):
    p = _para(d, space_before=Pt(11), space_after=Pt(3), font=BODY_FONT, size=HEAD_PT)
    _run(p, text, size=HEAD_PT, color=TREADWELL_RED, bold=True)
    return p


def _row(d, label, token):
    """`Label<tab>{{token}}` with a hanging indent at the value column."""
    p = _para(d, left_indent=VALUE_COL, first_line_indent=-VALUE_COL, tab_at=VALUE_COL)
    _run(p, label, bold=True, color=GREY)
    _run(p, "\t")
    _run(p, token)
    return p


def _note(d, text, *, italic=False, font=BODY_FONT, size=BODY_PT, space_before=None):
    p = _para(d, space_before=space_before, font=font, size=size)
    _run(p, text, italic=italic, font=font, size=size)
    return p


# ── The page ─────────────────────────────────────────────────────────────────
TITLE = "ELECTRONIC SIGNATURE CERTIFICATE"

# Label -> token, grouped under the heading a reader would look for it beneath.
# The order is the order of the questions: what was signed, who signed it, when,
# from where, under what wording, and how we can prove the document has not
# changed since.
SECTIONS = [
    ("The document signed", [
        ("Project",              "{{project_name}}"),
        ("Proposal ID",          "{{proposal_id}}"),
        ("Revision",             "{{revision_no}}"),
        ("Options accepted",     "{{options_summary}}"),
        ("Contract total",       "{{total}}"),
        ("Deposit due",          "{{deposit_amount}}"),
    ]),
    ("The signer", [
        ("Name",                 "{{signer_name}}"),
        ("Title",                "{{signer_title}}"),
        ("Email",                "{{signer_email}}"),
    ]),
    ("When it was signed", [
        ("Date and time (UTC)",  "{{signed_at_utc}}"),
        ("Date and time (Central)", "{{signed_at_central}}"),
    ]),
    ("Where it was signed from", [
        ("IP address",           "{{ip_address}}"),
        ("Browser",              "{{user_agent}}"),
    ]),
]

CONSENT_HEADING = "Consent to sign electronically"
CONSENT_LEAD = "Statement shown to the signer before signing, and accepted, verbatim:"
INTEGRITY_HEADING = "Document integrity (SHA-256)"
INTEGRITY_LEAD = (
    "These digests identify the exact bytes that were signed. A document that does "
    "not hash to the value below is not the document this certificate covers.")

# Verbatim, as specified. Both statutes are named because the signature is made
# in Kansas and delivered across state lines: ESIGN is the federal Act and
# K.S.A. 16-1601 et seq. is Kansas's enactment of UETA.
CLOSING = ("Signed electronically via portal.wetreadwell.com under "
           "15 U.S.C. § 7001 and K.S.A. 16-1601 et seq.")


def build(out_path: Path = OUT_PATH) -> Path:
    if not LETTERHEAD.is_file():
        raise SystemExit(
            "Missing %s — it is reference material kept out of the image; get it "
            "from the repo's docs/ folder before regenerating." % LETTERHEAD)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(LETTERHEAD, out_path)        # branding, byte-for-byte
    d = docx.Document(str(out_path))

    _title(d, TITLE)
    _note(d, "Treadwell Industries — record of a proposal accepted in the customer portal.",
          size=BODY_PT, italic=True)

    for heading, rows in SECTIONS:
        _section(d, heading)
        for label, token in rows:
            _row(d, label, token)

    _section(d, CONSENT_HEADING)
    _row(d, "Consent version", "{{consent_version}}")
    _note(d, CONSENT_LEAD, space_before=Pt(4))
    # The consent sentence is the customer's own words back at them. Quoted so
    # the boundaries of what they agreed to are unambiguous on the page; the text
    # between the quotes is whatever the portal showed, untouched.
    p = _para(d, left_indent=Inches(0.25), space_before=Pt(2))
    _run(p, "“{{consent_text}}”", italic=True)

    _section(d, INTEGRITY_HEADING)
    _note(d, INTEGRITY_LEAD, size=BODY_PT, italic=True)
    for label, token in (("Proposal PDF as delivered to the signer", "{{proposal_pdf_sha256}}"),
                         ("Proposal revision record", "{{revision_sha256}}")):
        lp = _para(d, space_before=Pt(4))
        _run(lp, label, bold=True, color=GREY)
        hp = _para(d, left_indent=Inches(0.25), font=MONO_FONT, size=MONO_PT)
        # Printed whole, never elided: a truncated digest proves nothing.
        _run(hp, token, font=MONO_FONT, size=MONO_PT)

    _note(d, CLOSING, space_before=Pt(12), size=BODY_PT)

    d.save(str(out_path))
    return out_path


def main() -> int:
    p = build()
    print("wrote %s" % p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
