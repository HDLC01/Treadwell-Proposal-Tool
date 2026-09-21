"""Sign INTO the proposal's own acceptance block, rather than behind it.

WHAT CHANGED AND WHY. The first cut of e-signature appended an Electronic
Signature Certificate page carrying the signer, the timestamp, the IP address,
the browser string, the consent paragraph and two SHA-256 digests. Hanz read one
and said three things: "we dont need another page for the signatory", "I think
the signature goes here?" — pointing at the ACCEPTANCE / SIGNATURE / DATE /
PRINTED NAME / TOTAL row Kyle already prints on the proposal form — and "this is
too much information... Just the basic information is what we need". So the page
is gone and four values are written onto the row that was always there. The
evidence the certificate used to PRINT is not lost: it is still validated on the
way in (`certificate_writer.field_problems`) and still stored on the portal's
approval row. It is simply not on the paper any more.

WHY THIS IS AN OVERLAY AND NOT A TOKEN FILL. Every one of Kyle's proposal
templates paints its form as a single full-page raster — 1275x1649 px at 150
DPI, laid under a dozen floating text boxes. "ACCEPTANCE", "SIGNATURE",
"PRINTED NAME" and the rules beside them appear in NO text run in any template;
they are pixels. There is nothing to substitute, so the four values are drawn
onto the already-rendered PDF in the artwork's own coordinates.

THE PAGE IS NOT THE LAST PAGE, AND THAT IS THE BUG THIS MODULE EXISTS TO AVOID.
A Direct Epoxy proposal renders as four pages: the FORM is page 1 and pages 2-4
are Terms & Conditions on blank letterhead. Drawing on "the last page" would put
the customer's signature on the back of the Terms, on blank paper, and every
naive test would still pass. Worse, the index is not fixed either: the optional
cover letter is prepended into the proposal's own bytes (`docx_merge`), so the
form is page index 0 or 1 depending on `cover_letter_enabled`. The caller
therefore derives the index from the draft the PDF was rendered from, and
`verify_acceptance_page` re-checks it against the document itself before a single
glyph is written.

THE CHECK THAT MAKES A WRONG INDEX LOUD. The acceptance block is on exactly ONE
page of a proposal, by construction — Kyle's form artwork is drawn once and every
other page carries the blank letterhead. So the page we are about to sign must
draw a full-page image that appears on NO other page of the document. A cover
letter that ran to two pages, a template that grew a page, a caller that passed
the wrong revision: each of them lands on a page whose artwork is shared with its
neighbours, and each is refused by name instead of producing a signature in the
wrong place. That is the whole point — a signature on blank letterhead is not a
document with a cosmetic fault, it is a contract that does not say what it
appears to say.

THE FONT IS A PDF BASE-14 FACE, DELIBERATELY. There is no script font in the
container: the Dockerfile installs Carlito, Liberation and Treadwell's Zetta
Serif and nothing else, so naming a cursive face would silently substitute and
render one way here and another way in production. Times-Italic and Times-Roman
are two of the fourteen faces every PDF consumer is required to provide, so they
need no font file on the box at all, no embedding step, and no second code path
between the test suite and the container. A typed name in italic serif is also
what ESIGN contemplates — the glyph was never the point, the record of intent is.

NOTHING IS RE-ENCODED. The page's own content stream object is left exactly as
it arrived: the overlay is appended as ADDITIONAL entries in the page's
`/Contents` array, with a `q` before the original and a `Q` after it so the
overlay cannot inherit a graphics state the proposal left set. PDF concatenates a
content array into one stream, and a split is legal at any token boundary, so
this is a standard construction — and it means the bytes of the pages we were
handed are the bytes we hand back. Every other page is copied object-for-object.
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import Optional

import pypdf
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

log = logging.getLogger("treadwell.acceptance_signature")


class AcceptanceError(RuntimeError):
    """This document cannot be signed in place, and the message says why.

    Always a sentence the portal can put in front of a person: the customer is on
    an "approving..." spinner when this fires and "500" tells whoever is paged
    exactly nothing."""


# ── Kyle's form, in the artwork's own pixels ──────────────────────────────────
# The artwork is 1275x1649 px — US Letter at 150 DPI — in every template that
# carries the block. Measured off the real render at
# `sample-epoxy-proposal.pdf`; `y` is the rule's own line and `x0..x1` is the
# span of that rule, so a value drawn at `x0 + INSET` with its baseline `LIFT`
# above `y` sits ON the rule the way a pen would.
ARTWORK_PX = (1275, 1649)

RULE_Y_SIGNATURE = 1431
RULE_Y_PRINTED = 1496

# (rule_y_px, rule_x0_px, rule_x1_px)
RULES = {
    "signature":    (RULE_Y_SIGNATURE, 470, 883),
    "date":         (RULE_Y_SIGNATURE, 966, 1191),
    "printed_name": (RULE_Y_PRINTED, 506, 883),
    "total":        (RULE_Y_PRINTED, 976, 1189),
}

# The signature is the only field in italic; the other three are ordinary type,
# because they are recorded facts rather than the mark itself.
ITALIC_FIELDS = frozenset({"signature"})

NOMINAL_SIZE = {"signature": 14.0, "date": 11.0, "printed_name": 11.0, "total": 11.0}

# Never smaller than this. Below ~6pt a name stops being legible on paper, and a
# contract nobody can read is not a contract that was signed — so a value that
# still will not fit at the floor is REFUSED rather than shrunk into a smudge.
MIN_SIZE = 6.0

# How far in from the rule's left end the ink starts, and how far the baseline
# sits above the rule. Both in points, both chosen so the glyphs clear the line
# instead of striking through it.
INSET_PT = 4.0
LIFT_PT = 3.0

# The rule's right end is a hard edge: past it sits the next label ("DATE",
# "TOTAL") or the page margin. Leave a little air so a descender or an italic
# overhang cannot touch it.
TAIL_PT = 3.0


# ── Adobe Core-14 advance widths, ASCII 32..126, in 1/1000 em ─────────────────
# Taken from the Times-Roman / Times-Italic AFMs (codes 39 and 96 are the
# WinAnsiEncoding glyphs `quotesingle` and `grave`, not StandardEncoding's
# curly quotes, because that is the encoding this module declares). Needed for
# one reason only: to know whether a value fits between the ends of its rule
# before it is drawn. Guessing an average width is how a long name comes to
# overprint the DATE label on a signed contract.
_W_TIMES_ROMAN = (
    250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333, 250, 278,
    500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 278, 278, 564, 564, 564, 444,
    921, 722, 667, 667, 722, 611, 556, 722, 722, 333, 389, 722, 611, 889, 722, 722,
    556, 722, 667, 556, 611, 722, 722, 944, 722, 722, 611, 333, 278, 333, 469, 500,
    333, 444, 500, 444, 500, 444, 333, 500, 500, 278, 278, 500, 278, 778, 500, 500,
    500, 500, 333, 389, 278, 500, 500, 722, 500, 500, 444, 480, 200, 480, 541,
)
_W_TIMES_ITALIC = (
    250, 333, 420, 500, 500, 833, 778, 214, 333, 333, 500, 675, 250, 333, 250, 278,
    500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 333, 333, 675, 675, 675, 500,
    920, 611, 611, 667, 722, 611, 611, 722, 722, 333, 444, 667, 556, 833, 667, 722,
    611, 722, 611, 500, 556, 722, 611, 833, 611, 556, 556, 389, 278, 389, 422, 500,
    333, 500, 500, 444, 500, 444, 278, 500, 500, 278, 278, 444, 278, 722, 500, 500,
    500, 500, 389, 389, 278, 500, 444, 667, 444, 444, 389, 400, 275, 400, 541,
)
# Anything outside ASCII (an accented name, a currency mark) still encodes in
# WinAnsi and still prints; only its advance is approximated, by the width of a
# lower-case `o`. The error is a fraction of a point per character and it can
# only make the fit check slightly pessimistic, never optimistic enough to
# overrun the rule.
_W_DEFAULT = 500


def text_width(text: str, size: float, italic: bool) -> float:
    """Advance width of `text` at `size` points, in points."""
    table = _W_TIMES_ITALIC if italic else _W_TIMES_ROMAN
    total = 0
    for ch in text:
        code = ord(ch)
        total += table[code - 32] if 32 <= code <= 126 else _W_DEFAULT
    return total * size / 1000.0


def fit_size(text: str, available_pt: float, nominal: float, italic: bool) -> Optional[float]:
    """The largest size at or below `nominal` at which `text` fits, or None.

    Steps down in half points rather than solving for the size so the result is a
    value a person would choose, and stops at MIN_SIZE. None means "this will not
    go on this rule at a legible size" and the caller refuses — see the module
    header on why a smudge is not an acceptable alternative.
    """
    if not text:
        return nominal
    size = float(nominal)
    while size >= MIN_SIZE:
        if text_width(text, size, italic) <= available_pt:
            return size
        size -= 0.5
    return None


# ── which templates even have a block ─────────────────────────────────────────
# ONLY THE DIRECT FORM CARRIES ONE. Verified by artwork hash across the shipped
# templates: Direct Epoxy / Polish / Combo / Budget all paint the same form,
# which has the ACCEPTANCE row; the three GC templates share a different form
# that has none, and Gyp has its own, also without. Kyle has not added the row to
# the GC or Gyp forms, so those proposals approve exactly as they always did and
# no signed contract is produced for them — the same treatment Budget Pricing
# already gets in the portal for having no Terms and Conditions.
#
# Resolved through `proposal_writer.TEMPLATE_PICKER` rather than a second list of
# work types, because the picker is what actually decides which .docx is filled.
# A duplicate list would go stale the first time a template moves.
ACCEPTANCE_TEMPLATE_DIR = "Direct/"


def template_has_acceptance_block(work_type: str, audience: Optional[str]) -> bool:
    """Does the template for this (work_type, audience) print an acceptance row?

    Raises rather than guessing on a pair the picker does not know.
    `proposal_writer.pick_template` falls back to (epoxy, Direct) for an unmapped
    pair so a proposal always renders; inheriting that fallback HERE would answer
    "yes, it has a block" for a combination nobody has ever seen, and then draw a
    signature onto whatever page came back. A refusal is the only safe answer.
    """
    import proposal_writer

    wt = str(work_type or "").strip().lower()
    aud = str(audience or "").strip() or None
    key = (wt, aud)
    picker = proposal_writer.TEMPLATE_PICKER
    if key not in picker:
        if (wt, None) in picker:
            key = (wt, None)
        else:
            raise AcceptanceError(
                "no proposal template is mapped for work type " + repr(wt)
                + " and audience " + repr(aud) + ", so we cannot tell whether it "
                "carries an acceptance block to sign")
    return picker[key].replace("\\", "/").startswith(ACCEPTANCE_TEMPLATE_DIR)


# ── reading the page ──────────────────────────────────────────────────────────
def _mul(m, n):
    """m x n, PDF row-vector convention: applying m then n."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D,
            c * A + d * C, c * B + d * D,
            e * A + f * C + E, e * B + f * D + F)


def _resources(page) -> dict:
    res = page.get("/Resources")
    if res is None:
        res = page.get_inherited("/Resources")
    return res.get_object() if res is not None else {}


def _image_draws(page) -> list:
    """Every image XObject actually DRAWN on this page: (ctm, width_px, height_px, digest).

    The content stream, not the resource dictionary. LibreOffice lists BOTH
    full-page artworks in the resources of every page of a proposal — only one of
    them is ever painted, and it is the painted one that decides what the page
    shows.
    """
    from pypdf.generic import ContentStream

    xobjects = _resources(page).get("/XObject")
    xobjects = xobjects.get_object() if xobjects is not None else {}
    contents = page.get_contents()
    if contents is None:
        return []
    stream = ContentStream(contents, page.pdf)

    ctm = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    stack: list = []
    found: list = []
    for operands, operator in stream.operations:
        if operator == b"q":
            stack.append(ctm)
        elif operator == b"Q":
            ctm = stack.pop() if stack else (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        elif operator == b"cm":
            try:
                ctm = _mul(tuple(float(v) for v in operands), ctm)
            except (TypeError, ValueError):
                continue
        elif operator == b"Do" and operands:
            obj = xobjects.get(operands[0])
            if obj is None:
                continue
            obj = obj.get_object()
            if obj.get("/Subtype") != "/Image":
                continue
            try:
                raw = bytes(obj.get_data())
            except Exception:  # noqa: BLE001 — an undecodable image is still an image
                raw = bytes(getattr(obj, "_data", b"") or b"")
            found.append((ctm, int(obj.get("/Width") or 0), int(obj.get("/Height") or 0),
                          hashlib.sha256(raw).hexdigest()))
    return found


def full_page_artwork(page) -> Optional[tuple]:
    """(ctm, pixel_size, digest) of the one full-page raster on this page, or None.

    "Full page" means the placement covers at least 95% of the MediaBox in both
    directions — the real artwork is placed at 612 x 791 on a 612 x 792 page and
    hangs a point off one edge or the other depending on the page, so an exact
    comparison would find nothing.
    """
    box = page.mediabox
    page_w = float(box.width)
    page_h = float(box.height)
    if page_w <= 0 or page_h <= 0:
        return None
    for ctm, w_px, h_px, digest in _image_draws(page):
        a, b, c, d, _e, _f = ctm
        if b or c:                      # rotated or skewed — not our flat artwork
            continue
        if abs(a) >= 0.95 * page_w and abs(d) >= 0.95 * page_h:
            return (ctm, (w_px, h_px), digest)
    return None


def verify_acceptance_page(reader, page_index: int) -> tuple:
    """The artwork placement for the page we are about to sign, or raise.

    THE INDEX CAME FROM THE DRAFT; THIS IS THE DOCUMENT'S OWN OPINION. Kyle's
    form is painted on exactly one page and every other page carries the blank
    letterhead, so the acceptance page's artwork is the one that appears nowhere
    else. If the page at `page_index` shares its artwork with another page, the
    index is wrong — a cover letter that ran long, a stale revision, a template
    that grew — and signing it would put the customer's name on blank paper at
    the back of the Terms.
    """
    pages = list(reader.pages)
    if not 0 <= page_index < len(pages):
        raise AcceptanceError(
            "the acceptance page was worked out to be page " + str(page_index + 1)
            + " but the proposal has " + str(len(pages)) + " page(s)")

    art = full_page_artwork(pages[page_index])
    if art is None:
        raise AcceptanceError(
            "page " + str(page_index + 1) + " of the proposal does not carry the "
            "full-page Treadwell form, so there is no acceptance block to sign on it")

    ctm, size_px, digest = art
    # THE COORDINATES ARE MEASURED IN THIS ARTWORK'S OWN PIXELS. Re-export the
    # form at another resolution and every number in RULES points somewhere else;
    # a signature half an inch below the line is not a typo, it is a contract
    # that looks unsigned. Checked rather than assumed.
    if size_px != ARTWORK_PX:
        raise AcceptanceError(
            "the form on page " + str(page_index + 1) + " is " + str(size_px[0]) + "x"
            + str(size_px[1]) + " pixels, not the " + str(ARTWORK_PX[0]) + "x"
            + str(ARTWORK_PX[1]) + " artwork the acceptance block was measured on — "
            "nothing was signed")

    for other, page in enumerate(pages):
        if other == page_index:
            continue
        seen = full_page_artwork(page)
        if seen is not None and seen[2] == digest:
            raise AcceptanceError(
                "page " + str(page_index + 1) + " carries the same artwork as page "
                + str(other + 1) + ", so it is not the acceptance page — the proposal's "
                "page order is not what we expected and nothing was signed")
    return ctm


# ── drawing ───────────────────────────────────────────────────────────────────
def artwork_point(ctm: tuple, px_x: float, px_y: float) -> tuple:
    """An artwork pixel (origin top-left) as a PDF user-space point.

    A PDF image fills the unit square with its FIRST row of samples along the
    square's top edge, so the pixel row maps to `1 - y/H` before the CTM is
    applied. Getting that inversion wrong puts the signature the same distance
    below the block as it should have been above it, which is precisely the kind
    of mistake a "did it render?" test does not catch.
    """
    a, _b, _c, d, e, f = ctm
    w_px, h_px = ARTWORK_PX
    return (e + a * (float(px_x) / w_px),
            f + d * (1.0 - float(px_y) / h_px))


def _pdf_string(text: str) -> bytes:
    """A PDF literal string in WinAnsiEncoding, escaped."""
    raw = text.encode("cp1252", "replace")
    out = bytearray(b"(")
    for byte in raw:
        if byte in (0x28, 0x29, 0x5C):          # ( ) \
            out.append(0x5C)
        out.append(byte)
    out.append(0x29)
    return bytes(out)


def _num(value: float) -> bytes:
    return ("%.3f" % float(value)).rstrip("0").rstrip(".").encode("ascii") or b"0"


def build_overlay(ctm: tuple, values: dict, roman_name: str, italic_name: str) -> bytes:
    """The content stream that writes the four values onto the block.

    `values` is {field: text}; a field left out or blank draws nothing, because a
    blank on a rule reads as a rule nobody filled in — which is exactly what it
    is — rather than as a failed fill.
    """
    body = bytearray(b"q\n0 0 0 rg\n0 0 0 RG\nBT\n")
    for field in ("signature", "date", "printed_name", "total"):
        text = str(values.get(field) or "").strip()
        if not text:
            continue
        rule_y, rule_x0, rule_x1 = RULES[field]
        italic = field in ITALIC_FIELDS
        left = artwork_point(ctm, rule_x0, rule_y)
        right = artwork_point(ctm, rule_x1, rule_y)
        available = (right[0] - left[0]) - INSET_PT - TAIL_PT
        size = fit_size(text, available, NOMINAL_SIZE[field], italic)
        if size is None:
            raise AcceptanceError(
                "the " + field.replace("_", " ") + " (" + str(len(text))
                + " characters) will not fit on its line of the acceptance block "
                "at a legible size, so nothing was signed")
        body += b"/" + (italic_name if italic else roman_name).encode("ascii") + b" "
        body += _num(size) + b" Tf\n"
        body += b"1 0 0 1 " + _num(left[0] + INSET_PT) + b" " + _num(left[1] + LIFT_PT) + b" Tm\n"
        body += _pdf_string(text) + b" Tj\n"
    body += b"ET\nQ\n"
    return bytes(body)


def _free_name(existing, stem: str) -> str:
    """A resource name `stem` that does not collide with one already on the page."""
    name = stem
    n = 0
    while NameObject("/" + name) in existing:
        n += 1
        name = stem + str(n)
    return name


def _base14(writer, base_font: str) -> DictionaryObject:
    font = DictionaryObject()
    font[NameObject("/Type")] = NameObject("/Font")
    font[NameObject("/Subtype")] = NameObject("/Type1")
    font[NameObject("/BaseFont")] = NameObject("/" + base_font)
    font[NameObject("/Encoding")] = NameObject("/WinAnsiEncoding")
    return writer._add_object(font)


def sign_acceptance_page(pdf_bytes: bytes, page_index: int, *,
                         signer_name: str = "", date_text: str = "",
                         total_text: str = "", printed_name: Optional[str] = None) -> bytes:
    """The proposal with its acceptance block filled in. Same page count, in and out.

    `printed_name` defaults to `signer_name` — the block asks for the signature
    and the printed name, and for a typed electronic signature they are the same
    string by definition. It is a parameter rather than a constant so a future
    signature image can be drawn on the top line without the printed line
    following it into illegibility.
    """
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    ctm = verify_acceptance_page(reader, page_index)

    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    page = writer.pages[page_index]

    resources = page.get(NameObject("/Resources"))
    if resources is None:
        inherited = page.get_inherited("/Resources")
        resources = DictionaryObject() if inherited is None else inherited.get_object()
        page[NameObject("/Resources")] = resources
    resources = resources.get_object()
    fonts = resources.get(NameObject("/Font"))
    if fonts is None:
        fonts = DictionaryObject()
        resources[NameObject("/Font")] = fonts
    fonts = fonts.get_object()

    roman_name = _free_name(fonts, "TWAcceptRoman")
    italic_name = _free_name(fonts, "TWAcceptItalic")

    overlay = build_overlay(
        ctm,
        {"signature": signer_name, "date": date_text,
         "printed_name": signer_name if printed_name is None else printed_name,
         "total": total_text},
        roman_name, italic_name)

    fonts[NameObject("/" + roman_name)] = _base14(writer, "Times-Roman")
    fonts[NameObject("/" + italic_name)] = _base14(writer, "Times-Italic")

    # THE ORIGINAL STREAM OBJECT IS NEVER TOUCHED. `q` and `Q` go in as their own
    # tiny entries around it so the proposal's own drawing bytes, and their
    # filter, come out of this function exactly as they went in — see the module
    # header. A content array is concatenated into one stream by every consumer,
    # and a split at a token boundary is explicitly legal.
    existing = page.get(NameObject("/Contents"))
    parts = ArrayObject()
    if isinstance(existing, ArrayObject):
        parts.extend(existing)
    elif existing is not None:
        parts.append(page.raw_get(NameObject("/Contents")))
    parts.insert(0, writer._add_object(_stream(b"q\n")))
    parts.append(writer._add_object(_stream(b"\nQ\n")))
    parts.append(writer._add_object(_stream(overlay)))
    page[NameObject("/Contents")] = parts

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _stream(data: bytes) -> DecodedStreamObject:
    obj = DecodedStreamObject()
    obj.set_data(data)
    obj[NameObject("/Length")] = NumberObject(len(data))
    return obj


# ── the date that goes on the DATE rule ───────────────────────────────────────
# The rule is ~108pt wide. The portal's Central stamp is the whole sentence
# "September 18, 2026 at 10:42 AM CDT", which is half as wide again as the line
# it would have to sit on. The DATE on a contract is a date, so the time is
# dropped for PRINTING only — it is still validated on the way in and still on
# the portal's approval row, which is where a dispute would read it from.
#
# NO TIMEZONE MATHS, ANYWHERE. `signed_at_central` arrives pre-formatted from the
# portal, the one process that knows when the click happened; this box's clock
# runs ~13 hours off Central and converting here would let two systems disagree
# about what day a contract was signed.
_AT = " at "


def acceptance_date(signed_at_central: str) -> str:
    """The date half of the portal's Central-time stamp, for the DATE rule.

    Falls back to the whole string if the format ever changes — it still prints
    something true, and `fit_size` shrinks it to fit rather than letting it run
    into the TOTAL column.
    """
    text = str(signed_at_central or "").strip()
    head = text.split(_AT, 1)[0].strip()
    return head or text
