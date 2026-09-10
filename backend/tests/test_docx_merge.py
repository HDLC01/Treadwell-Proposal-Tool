"""`docx_merge.prepend_cover_letter` — the letter becomes page 1 of the proposal.

WHAT THESE TESTS CAN AND CANNOT SEE. There is no renderer in CI, so nothing here
can assert "page 1 is the letterhead" in the only way that finally counts. What
they assert instead is every property the renderer depends on: the letter's
markup comes first, its section properties stop governing at its last paragraph,
and each of the four id spaces that collide between two packages has been
rewritten. The render itself was checked by hand against Word on 2026-09-09 (5
pages = 1 letter + 4 proposal, every page's text identical to its source
document, the letterhead PNG on page 1 and the proposal's artwork on page 2).
LibreOffice — the renderer production actually uses — is asserted by
`test_libreoffice_renders_the_letter_as_page_one_and_loses_no_pages` at the
bottom of this file. It skips here and RUNS in the container, via the deploy
workflow's LibreOffice step, and it is listed in that step on purpose: a
soffice-gated test missing from the list skips on the dev box, in CI, and in the
image alike, which is coverage that exists only in a docstring.

THE COLLISION TESTS CARRY THEIR OWN COUNTEREXAMPLE. A test that says "the merged
document has no duplicate numbering ids" passes just as well when the two
templates never shared one — it would be green, prove nothing, and go on being
green after somebody deleted the remapping. So each of those tests first asserts
that the inputs DO collide, and fails with a note if they ever stop, because at
that point the guard it is protecting has become untested rather than unneeded.
"""
import io
import shutil
import zipfile

import pytest
from lxml import etree

import cover_letter_writer as clw
import docx_merge
import proposal_writer

W = docx_merge.W
WP = docx_merge.WP

VALUES = {
    "project_name": "Merge Test Job", "job_name": "Merge Test Job",
    "address": "Olathe, KS", "city_state": "Olathe, KS",
    "proposal_date": "September 9, 2026", "bid_date_formatted": "9/9/26",
    "system_name": "Treadwell Epoxy", "texture": "Smooth",
    "epoxy_sf": "5,000", "lump_sum": "$50,000", "estimator_name": "Kyle Nelson",
    "scope_notes": "Scope.", "schedule_notes": "Schedule.",
    "exclusions": "Exclusions.", "work_areas": "Warehouse expansion",
}


def _proposal(work_type="epoxy", audience="Direct"):
    return proposal_writer.fill_proposal(work_type=work_type, audience=audience,
                                         values=VALUES)


def _letter(work_type="epoxy", audience="Direct"):
    return clw.fill_cover_letter(work_type=work_type, audience=audience,
                                 values=VALUES)


def _doc(raw):
    """The `w:document` root of a .docx byte string."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return etree.fromstring(z.read("word/document.xml"))


def _part(raw, name):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return z.read(name)


def _names(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        return set(z.namelist())


def _paras(root):
    """Visible text of every paragraph, in document order, blanks dropped."""
    out = []
    for p in root.iter(W + "p"):
        text = "".join(t.text or "" for t in p.iter(W + "t")).strip()
        if text:
            out.append(text)
    return out


def _shape(el):
    """`(tag, sorted attributes, text, children…)` — an element's content with
    nothing serialiser-dependent in it. Namespace DECLARATIONS are deliberately
    not part of this: they are scope bookkeeping, and the merge is entitled to
    move them to the root. Attribute NAMES keep their expanded namespace, so a
    `w:type` that turned into a bare `type` would still show up as a difference.
    """
    return (el.tag,
            tuple(sorted(el.attrib.items())),
            (el.text or "").strip(),
            tuple(_shape(c) for c in el))


def _num_ids(raw):
    root = etree.fromstring(_part(raw, "word/numbering.xml"))
    return [n.get(W + "numId") for n in root.findall(W + "num")]


def _body_num_refs(root):
    return [n.get(W + "val")
            for npr in root.iter(W + "numPr")
            for n in [npr.find(W + "numId")] if n is not None]


@pytest.fixture(scope="module")
def merged():
    return docx_merge.prepend_cover_letter(_proposal(), _letter())


# ══ the letter is in front ════════════════════════════════════════════════════
def test_the_letter_comes_first_and_the_proposal_survives_it(merged):
    """Both documents, whole, in that order. The proposal is the base package, so
    a merge that damaged it would be the expensive failure — this is a signed
    contract with a letter stapled on, not a letter with a contract appended."""
    letter_paras = _paras(_doc(_letter()))
    proposal_paras = _paras(_doc(_proposal()))
    got = _paras(_doc(merged))

    assert got[:len(letter_paras)] == letter_paras, (
        "the letter's paragraphs are not the first thing in the merged document")
    assert got[len(letter_paras):] == proposal_paras, (
        "the proposal's own paragraphs changed on the way through the merge")


def test_the_letters_section_stops_at_the_letters_last_paragraph(merged):
    """A `sectPr` that is a direct child of `w:body` governs the LAST section of
    the document. Prepended as-is, the letter's would own the proposal's pages —
    and it is `continuous`, so the proposal would start mid-page on the
    letterhead's margins instead of on a fresh sheet of its own."""
    root = _doc(merged)
    body = root.find(W + "body")

    final = body.findall(W + "sectPr")
    assert len(final) == 1, "expected exactly one document-level sectPr"
    assert final[0].find(W + "type") is None, (
        "the proposal's section gained a w:type — with anything but the default "
        "nextPage the proposal no longer starts on its own page")
    # Unchanged: this is the section that lays out the contract.
    #
    # COMPARED BY SHAPE, NOT BY SERIALISED TEXT. Two earlier versions of this
    # assertion reported on lxml rather than on the merge. `tostring` of a
    # SUBTREE emits every namespace declaration in scope above it, and
    # `_merged_root` legitimately rebuilds `w:document` with the union of both
    # packages' nsmaps, which reorders them — so the strings differed while the
    # section was identical. `method="c14n2"` then refused outright, because a
    # `w:`-prefixed attribute (`w:rsidR`) on a subtree has no declaration in
    # scope to canonicalise against. The tag/attribute/child tree below is what
    # the claim actually means: no page-setup value changed.
    proposal_sect = _doc(_proposal()).find(W + "body").findall(W + "sectPr")[0]
    # `_shape` has to be able to TELL TWO SECTIONS APART, or the equality below
    # is a comparison of two blanks. The letter's own final section is the
    # counterexample: same element, different page setup.
    letter_sect = _doc(_letter()).find(W + "body").find(W + "sectPr")
    assert _shape(letter_sect) != _shape(proposal_sect), (
        "_shape cannot distinguish the letter's page setup from the proposal's, "
        "so the assertion below proves nothing")

    assert _shape(final[0]) == _shape(proposal_sect), (
        "the proposal's page setup was rewritten by the merge")

    para_level = body.findall("./" + W + "p/" + W + "pPr/" + W + "sectPr")
    assert len(para_level) == 2, (
        "expected the letterhead's two sections to both end on a paragraph, got "
        "%d" % len(para_level))
    # The letter's own margins, not the proposal's 1800-twip ones.
    margins = {s.find(W + "pgMar").get(W + "left") for s in para_level}
    assert margins == {"3420", "990"}, (
        "the letterhead's per-section margins did not survive: %s" % margins)


def test_the_letters_page_setup_is_not_left_governing_the_contract(merged):
    """The specific failure the test above rules out, stated as its own claim:
    nothing `continuous` may be the merged document's final section."""
    body = _doc(merged).find(W + "body")
    final = body.find(W + "sectPr")
    kind = final.find(W + "type")
    assert kind is None or kind.get(W + "val") != "continuous", (
        "the merged document ends on a continuous section, so the proposal runs "
        "onto the letterhead page")


# ══ the four id spaces ════════════════════════════════════════════════════════
def test_the_letterhead_artwork_is_not_overwritten_by_a_name_clash(merged):
    """Both packages ship a `word/media/image1.png`. Copied in under its own
    name, the letterhead would replace the proposal's artwork — or be replaced
    by it, depending on which way the copy went."""
    letter_media = {n for n in _names(_letter()) if n.startswith("word/media/")}
    proposal_media = {n for n in _names(_proposal()) if n.startswith("word/media/")}
    assert letter_media & proposal_media, (
        "the two templates no longer share a media part name, so the rename this "
        "test protects is no longer exercised — check it is still needed")

    got = {n for n in _names(merged) if n.startswith("word/media/")}
    assert proposal_media <= got, "the proposal lost a media part"
    assert len(got) == len(proposal_media) + len(letter_media), (
        "a media part was dropped or overwritten: %s" % sorted(got))


def test_the_letterhead_still_points_at_the_letterhead(merged):
    """The rename is only half the job: the drawing's `r:embed` has to follow it
    to the new relationship, or page 1 draws the proposal's artwork."""
    rels = etree.fromstring(_part(merged, "word/_rels/document.xml.rels"))
    targets = {r.get("Id"): r.get("Target")
               for r in rels.findall(docx_merge.PKG_REL + "Relationship")}
    letterhead = _part(_letter(), "word/media/image1.png")

    root = _doc(merged)
    blips = [b.get(docx_merge.R + "embed")
             for b in root.iter(docx_merge.A + "blip")]
    assert blips, "no images in the merged document at all"
    # The FIRST drawing in document order is the letter's, because the letter is
    # first — and it must resolve to the letterhead's bytes.
    first = targets[blips[0]]
    assert _part(merged, "word/" + first) == letterhead, (
        "the first drawing does not resolve to the letterhead artwork (points at "
        "%s)" % first)


def test_the_letters_list_does_not_adopt_the_proposals_numbering(merged):
    """The letter's numbered lines are `1. 2. 3.`; the proposal's numbering part
    already defines those ids for its Terms clauses. Left un-shifted, the
    letter's list renders with the Terms' definition — which in this template is
    bold, and continues the contract's clause count."""
    letter_ids = set(_num_ids(_letter()))
    proposal_ids = set(_num_ids(_proposal()))
    assert letter_ids & proposal_ids, (
        "the two numbering parts no longer share an id, so the offset this test "
        "protects is no longer exercised — check it is still needed")

    ids = _num_ids(merged)
    assert len(ids) == len(set(ids)), (
        "duplicate w:numId in the merged numbering part: %s" % ids)
    assert len(ids) == len(_num_ids(_proposal())) + len(_num_ids(_letter()))

    # And the body follows the definitions it was given.
    defined = set(ids)
    assert set(_body_num_refs(_doc(merged))) <= defined, (
        "a paragraph references a numbering id the merged part does not define")


def test_the_letters_paragraphs_reference_their_own_new_numbering(merged):
    """The offset has to reach the BODY too. A numbering part that was merged
    correctly while the paragraphs still pointed at the old ids is the same bug
    wearing a clean part."""
    letter_refs = set(_body_num_refs(_doc(_letter())))
    assert letter_refs, "the letter has no numbered paragraphs to check"
    proposal_refs = set(_body_num_refs(_doc(_proposal())))
    merged_refs = _body_num_refs(_doc(merged))

    # The letter's paragraphs come first, so the head of the list is the letter's.
    head = merged_refs[:len(_body_num_refs(_doc(_letter())))]
    assert set(head).isdisjoint(proposal_refs), (
        "the letter's paragraphs point at numbering ids the proposal also uses")
    assert set(head) != letter_refs, (
        "the letter's numbering references were not shifted at all")


def test_word_is_not_asked_to_repair_duplicate_drawing_ids(merged):
    """`wp:docPr/@id` is unique per document; a duplicate is what makes Word
    offer to repair a file. (`pic:cNvPr/@id` is scoped to its own drawing and is
    duplicated throughout Kyle's template already — not this test's business.)"""
    ids = [e.get("id") for e in _doc(merged).iter(WP + "docPr")]
    assert len(ids) == len(set(ids)), "duplicate wp:docPr id: %s" % ids


def test_the_letters_empty_letterhead_chrome_is_not_inherited_by_the_contract(merged):
    """`python-docx` manufactures an empty `header1.xml`/`footer1.xml` while
    filling, and the letter's sections reference them. A section with NO header
    reference inherits the previous section's — so leaving the letter's in place
    would hand its chrome to every page of the proposal behind it."""
    letter_refs = len(list(_doc(_letter()).iter(W + "headerReference")))
    assert letter_refs, (
        "the letter no longer references a header, so the drop this test protects "
        "is no longer exercised — check it is still needed")

    body = _doc(merged).find(W + "body")
    for sect in body.findall("./" + W + "p/" + W + "pPr/" + W + "sectPr"):
        assert sect.find(W + "headerReference") is None
        assert sect.find(W + "footerReference") is None


# ══ it refuses rather than guessing ══════════════════════════════════════════
def test_a_letterhead_header_with_content_is_refused_not_dropped():
    """Dropping an EMPTY header loses nothing. Dropping one somebody put a
    footer bar in loses a customer-facing page element silently — so that case
    raises, and the message says why it needs a decision."""
    raw = _letter()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    hdr = etree.fromstring(parts["word/header1.xml"])
    body = hdr.find(W + "body") if hdr.find(W + "body") is not None else hdr
    p = etree.SubElement(body, W + "p")
    r = etree.SubElement(p, W + "r")
    etree.SubElement(r, W + "t").text = "TREADWELL FLOORING SYSTEMS"
    parts["word/header1.xml"] = etree.tostring(hdr, xml_declaration=True,
                                               encoding="UTF-8", standalone=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zo:
        for name, data in parts.items():
            zo.writestr(name, data)

    with pytest.raises(docx_merge.MergeError) as exc:
        docx_merge.prepend_cover_letter(_proposal(), buf.getvalue())
    assert "header" in str(exc.value).lower()


def test_a_letter_with_no_page_setup_is_refused():
    """Without its own `sectPr` the letter would silently inherit the proposal's
    margins, which is not the letterhead."""
    raw = _letter()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = etree.fromstring(parts["word/document.xml"])
    body = root.find(W + "body")
    body.remove(body.find(W + "sectPr"))
    parts["word/document.xml"] = etree.tostring(root, xml_declaration=True,
                                                encoding="UTF-8", standalone=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zo:
        for name, data in parts.items():
            zo.writestr(name, data)

    with pytest.raises(docx_merge.MergeError):
        docx_merge.prepend_cover_letter(_proposal(), buf.getvalue())


def test_something_that_is_not_a_docx_is_refused_by_name():
    with pytest.raises(docx_merge.MergeError):
        docx_merge.prepend_cover_letter(_proposal(), b"this is not a zip")
    with pytest.raises(docx_merge.MergeError):
        docx_merge.prepend_cover_letter(b"this is not a zip", _letter())


# ══ every shipped variant ════════════════════════════════════════════════════
@pytest.mark.parametrize("work_type,audience", [
    ("epoxy", "Direct"), ("polish", "Direct"), ("combo", "Direct"),
    ("epoxy", "GC"), ("polish", "GC"), ("combo", "GC"), ("gyp", None),
])
def test_every_variant_that_has_a_letter_can_be_merged(work_type, audience):
    """Seven letters, eight proposal templates, and a picker that is
    deliberately not a clean grid. A variant that merged nowhere would be a
    refusal an estimator meets for the first time on a live bid."""
    if not clw.has_template(work_type, audience):
        pytest.skip("no cover letter for %s/%s" % (work_type, audience))
    letter = _letter(work_type, audience)
    merged = docx_merge.prepend_cover_letter(_proposal(work_type, audience), letter)

    got = _paras(_doc(merged))
    assert got[:len(_paras(_doc(letter)))] == _paras(_doc(letter))
    ids = _num_ids(merged)
    assert len(ids) == len(set(ids))
    docpr = [e.get("id") for e in _doc(merged).iter(WP + "docPr")]
    assert len(docpr) == len(set(docpr))
    # The package still opens as a document.
    import docx
    assert len(docx.Document(io.BytesIO(merged)).sections) >= 2


# ══ the guard that nothing shipped reaches ═══════════════════════════════════
def test_a_bookmark_the_letter_brings_cannot_collide_with_the_proposals():
    """The bookmark remap, exercised with a bookmark that actually collides.

    NOTHING SHIPPED REACHES THIS. No filled cover letter carries a
    `w:bookmarkStart`, and the only proposal that does is Budget (Word's own
    `_GoBack`, id 1) — which is the HOST, whose ids are never rewritten. An audit
    proved the point by setting the offset to zero and watching the whole suite
    stay green: a guard nothing exercises is a guard nobody can trust.

    So the letter is given one, at the exact id Budget already uses. Word does
    not refuse a duplicate bookmark id the way it refuses a duplicate drawing id
    — it silently keeps one of the pair, which would swallow a real bookmark (a
    cross-reference, a form field, a table-of-contents anchor) in whichever
    document lost the toss."""
    proposal = proposal_writer.fill_proposal(
        work_type="budget", audience="Direct", values=VALUES)
    host_ids = [e.get(W + "id")
                for e in _doc(proposal).iter(W + "bookmarkStart")]
    assert host_ids, (
        "the Budget proposal no longer carries a bookmark, so this test's "
        "collision is imaginary — pick another host or drop the remap")

    # Give the letter a bookmark wrapping its first paragraph, at a colliding id.
    raw = _letter()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    root = etree.fromstring(parts["word/document.xml"])
    body = root.find(W + "body")
    first_p = body.find(W + "p")
    clash = host_ids[0]
    start = etree.Element(W + "bookmarkStart")
    start.set(W + "id", clash)
    start.set(W + "name", "letter_top")
    end = etree.Element(W + "bookmarkEnd")
    end.set(W + "id", clash)
    first_p.insert(0, start)
    first_p.append(end)
    parts["word/document.xml"] = etree.tostring(root, xml_declaration=True,
                                                encoding="UTF-8", standalone=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zo:
        for name, data in parts.items():
            zo.writestr(name, data)

    merged_root = _doc(docx_merge.prepend_cover_letter(proposal, buf.getvalue()))
    starts = {e.get(W + "name"): e.get(W + "id")
              for e in merged_root.iter(W + "bookmarkStart")}
    assert "letter_top" in starts, "the letter's bookmark did not survive the merge"
    assert starts["letter_top"] != clash, (
        "the letter's bookmark kept the id the proposal already uses (%s)" % clash)
    # A bookmark is a PAIR. Shifting only the start orphans it, which is its own
    # flavour of corruption.
    ends = [e.get(W + "id") for e in merged_root.iter(W + "bookmarkEnd")]
    assert starts["letter_top"] in ends, (
        "bookmarkStart was shifted but its bookmarkEnd was not — the bookmark is "
        "now unclosed")
    all_starts = [e.get(W + "id") for e in merged_root.iter(W + "bookmarkStart")]
    assert len(all_starts) == len(set(all_starts)), (
        "duplicate bookmarkStart id after the merge: %s" % all_starts)


# ══ the renderer production actually uses ════════════════════════════════════
@pytest.mark.skipif(shutil.which("soffice") is None
                    and shutil.which("libreoffice") is None,
                    reason="LibreOffice renders production's PDF; not installed "
                           "on this box (it is in the Docker image)")
def test_libreoffice_renders_the_letter_as_page_one_and_loses_no_pages():
    """THE ARTEFACT THE CUSTOMER READS, through the renderer that builds it.

    Everything else in this module asserts on markup, and a merged document was
    checked by hand in Word — but Word is not what serves the customer.
    LibreOffice is (`pdf_writer.docx_to_pdf`, baked into the image), and it is
    known to diverge from Word in this repo: it ignores docx text-box autofit,
    which is why `_shrink_to_fit` exists at all.

    The divergence risk here is specific and worth naming. The merge takes the
    proposal from ONE section to THREE, and the middle one is the letterhead's
    own `continuous` section — a shape that had never been rendered in
    production, because the standalone letter was only ever offered as a .docx
    and the portal never called its PDF route. If LibreOffice collapses that
    boundary, or resolves footer inheritance the other way, the visible result is
    the letter's body shifted by 1.7 inches or Kyle's footer bar printed across
    the letterhead. Neither shows up in the XML.

    Page COUNT catches all of it: letter pages + proposal pages, with the
    letter's text on page 1 and the proposal's pages immediately after. A
    collapsed section break loses a page; a leaked footer or a mis-set margin
    reflows one into two.
    """
    import fitz                                  # noqa: PLC0415 — optional, dev-only
    import pdf_writer

    letter, proposal = _letter(), _proposal()
    merged = docx_merge.prepend_cover_letter(proposal, letter)

    def pages(raw):
        with fitz.open(stream=pdf_writer.docx_to_pdf(raw), filetype="pdf") as d:
            return [" ".join(p.get_text().split()) for p in d]

    letter_pages, proposal_pages = pages(letter), pages(proposal)
    merged_pages = pages(merged)
    assert len(merged_pages) == len(letter_pages) + len(proposal_pages), (
        "LibreOffice rendered %d pages for the merged document, but %d for the "
        "letter and %d for the proposal — a section break was collapsed or an "
        "extra page appeared" % (len(merged_pages), len(letter_pages),
                                 len(proposal_pages)))
    assert merged_pages[:len(letter_pages)] == letter_pages, (
        "page 1 of the merged document is not the letter as LibreOffice renders "
        "it on its own")
    assert merged_pages[len(letter_pages):] == proposal_pages, (
        "the proposal's pages changed when the letter was put in front of them")
