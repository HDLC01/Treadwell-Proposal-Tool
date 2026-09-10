"""Prepend one .docx in front of another, in the same package.

ONE CALLER, ONE JOB: put the optional Cover Letter on the front of the proposal
so the letter IS page 1 of the document (Hanz, 2026-09-09: "If the Cover letter
is enabled it appends as the first page of the proposal").

WHY A MERGE AND NOT TWO FILES. Until now the letter was a SECOND document: its
own .docx token, its own `/api/admin/cover-letter-pdf`, and a `has_cover_letter`
flag telling the customer portal to show it first. The portal never implemented
any of that -- `grep -ri cover.letter treadwell-portal` returns nothing -- so a
letter an estimator ticked, edited and generated reached no customer at all. One
document cannot have that failure: the letter rides the proposal's own bytes, so
the .docx download, the LibreOffice PDF, the portal's `/api/admin/proposal-pdf`
and the To-Dropbox copy all carry it without any of them knowing it exists.

WHY THE PROPOSAL IS THE BASE PACKAGE AND THE LETTER IS THE GUEST. Whichever
document we keep, the other one's content has to be re-pointed at the host's
parts. Kyle's proposal templates are the fragile half -- a dozen floating text
boxes and two full-page PNGs laid over a fixed form, plus the box overrides the
estimator drags around (`proposal_writer`) -- and the letter is a generated
letterhead with one image and no text boxes (see
`prepare_cover_letter_templates`). So the proposal package survives byte for byte
and the letter is what gets rewritten.

WHAT MAKES THIS SAFE HERE, AND WOULD NOT MAKE IT SAFE IN GENERAL. Checked
against the shipped templates rather than assumed:

  * Identical themes (major Calibri / minor Cambria) and identical
    `docDefaults`, so nothing re-resolves to a different font.
  * The letter's paragraphs reference NO `w:pStyle` at all, and every one of its
    runs names its font explicitly. A guest whose text was styled by name, or
    themed, could change appearance on the way in; this one cannot.
  * The header/footer chain needs no re-pointing, though NOT because there is
    none — that was the original claim here and it is wrong twice over. The Gyp
    proposal template ships a real footer (`word/footer1.xml` with a drawing in
    it), and `python-docx` manufactures an empty `header1.xml`/`footer1.xml` on
    BOTH sides during the fill, so every filled package references one of each.
    It needs no re-pointing because the letter's references are DROPPED and the
    proposal declares its own — see `_drop_header_footer_references`.
  * Same page size (Letter). The margins differ per section and that is fine:
    each section keeps its own `sectPr`.

This is NOT a general docx merger. It handles exactly what these two documents
contain, and raises rather than guessing when it meets something else.

THE SECTION BREAK IS THE PAGE BREAK. A `w:sectPr` that sits as a direct child of
`w:body` describes the LAST section of the document. Moved to the front, the
letter's final section properties would go on governing the proposal's pages, so
they become a paragraph-level `sectPr` on the last letter paragraph -- the
standard way to end a section mid-body. Nothing forces a page break after it:
the proposal's own body-level `sectPr` has no `w:type`, which means `nextPage`,
so the proposal starts on a fresh page by the templates' own setup. (The letter's
final section IS `continuous`, which is exactly why it must not be left
governing anything but the letter.)

IDS ARE REWRITTEN, NOT HOPED OVER. Three id spaces collide across these
packages, and each is a real defect if missed:

  * `r:embed`/`r:id` relationship ids — the letterhead would draw the proposal's
    artwork, or nothing. Load-bearing and tested: both templates ship a
    `word/media/image1.png`.
  * `w:numId`/`w:abstractNumId` — the letter's numbered list would adopt the
    proposal's numbering, which in these templates is the bold Terms clause
    definition, and would continue the contract's clause count.
  * `wp:docPr` drawing ids — a duplicate is what makes Word offer to repair a
    document. Load-bearing and tested (epoxy Direct's own ids include `6`, and so
    does the letter's).

`w:bookmarkStart`/`End` ids are shifted too, DEFENSIVELY and not because anything
reaches it: no filled letter carries a bookmark, and the only proposal that does
(Budget's `_GoBack`) is the host, whose ids are never touched. Kept because a
duplicate bookmark id silently swallows one of the pair, and a test injects one
so the guard is exercised rather than merely present.

NOT an id space, despite an earlier version of this note saying so: `pic:cNvPr`
ids are scoped to their own drawing and are duplicated throughout Kyle's
templates already. `a:cNvPr` does not occur in any of these fifteen files.
"""
from __future__ import annotations

import io
import logging
import posixpath
import zipfile
from typing import Iterable

from lxml import etree

log = logging.getLogger("proposal_tool.docx_merge")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

_IMAGE_REL = ("http://schemas.openxmlformats.org/officeDocument/2006/"
              "relationships/image")

_DOC = "word/document.xml"
_DOC_RELS = "word/_rels/document.xml.rels"
_NUMBERING = "word/numbering.xml"
_STYLES = "word/styles.xml"
_CONTENT_TYPES = "[Content_Types].xml"

# The `pPr` children that may legally FOLLOW `sectPr` (ECMA-376 CT_PPr order).
# Everything else precedes it, so appending is right unless one of these is
# present -- a revision-tracked paragraph, in practice.
_AFTER_SECTPR = (W + "pPrChange",)

# `[Content_Types].xml` must declare every extension in the package or Word
# refuses to open it. Both templates already declare png; a letterhead re-cut as
# a jpeg would otherwise produce a file that opens nowhere, which is the kind of
# breakage that reaches a customer before it reaches a test.
_MEDIA_CONTENT_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "bmp": "image/bmp", "tif": "image/tiff",
    "tiff": "image/tiff", "emf": "image/x-emf", "wmf": "image/x-wmf",
    "svg": "image/svg+xml",
}

# Relationship-id attributes that appear on document body markup. Read for the
# "what does the guest point at" scan and rewritten afterwards.
_RID_ATTRS = (R + "embed", R + "id", R + "link", R + "pict")


class MergeError(RuntimeError):
    """The two packages cannot be merged safely. Raised instead of producing a
    document that opens wrong -- a proposal with a broken letterhead is worse
    than a refusal the estimator can act on."""


def _max_id(values: Iterable) -> int:
    """The largest integer among `values`, ignoring anything non-numeric."""
    best = 0
    for v in values:
        try:
            best = max(best, int(str(v).strip()))
        except (TypeError, ValueError):
            continue
    return best


def _rel_index(rels_root) -> dict:
    """`{Id: Relationship element}` for one .rels part."""
    return {rel.get("Id"): rel
            for rel in rels_root.findall(PKG_REL + "Relationship")
            if rel.get("Id")}


def _referenced_rids(tree) -> set:
    """Every relationship id the document body actually points at.

    Only these are copied. A guest package's rels also name its styles,
    numbering, theme and settings -- parts we are NOT taking, because the host's
    equivalents already govern the merged document."""
    found = set()
    for el in tree.iter():
        for attr in _RID_ATTRS:
            v = el.get(attr)
            if v:
                found.add(v)
    return found


def _uses_numbering(tree) -> bool:
    return next(tree.iter(W + "numPr"), None) is not None


def _xml_bytes(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                          standalone=True)


def _merged_root(host_doc, guest_doc):
    """A `w:document` root that can hold BOTH documents' markup.

    lxml cannot add a namespace declaration to an element that already exists,
    and a moved subtree needs its prefixes declared somewhere above it. So the
    root is rebuilt with the union of both nsmaps (the host wins a conflict) and
    the host's children are moved across.

    `mc:Ignorable` is unioned for the same reason: it lists the prefixes a
    consumer may skip, and a prefix used by moved content but absent from that
    list is how a document that renders here draws a repair prompt in Word."""
    nsmap = dict(guest_doc.nsmap or {})
    nsmap.update({k: v for k, v in (host_doc.nsmap or {}).items()})
    nsmap = {k: v for k, v in nsmap.items() if k}        # lxml rejects None keys
    root = etree.Element(W + "document", nsmap=nsmap)
    for k, v in host_doc.attrib.items():
        root.set(k, v)
    ignorable = " ".join(dict.fromkeys(
        (host_doc.get(MC + "Ignorable") or "").split()
        + (guest_doc.get(MC + "Ignorable") or "").split()))
    if ignorable:
        root.set(MC + "Ignorable", ignorable)
    for child in list(host_doc):
        root.append(child)
    return root


def _move_final_sectpr_onto_last_paragraph(guest_body) -> None:
    """Turn the guest's document-level `sectPr` into a paragraph-level one.

    See the module docstring: a body-level `sectPr` claims the last section of
    the whole document, which after a prepend would be the proposal's pages."""
    final = guest_body.find(W + "sectPr")
    if final is None:
        # Nothing to carry: the letter's pages would inherit the proposal's
        # section, which for a letterhead means the wrong margins. Loud.
        raise MergeError("The cover letter has no document-level sectPr; its "
                         "page setup would be lost.")
    guest_body.remove(final)

    last_p = None
    for child in guest_body:
        if child.tag == W + "p":
            last_p = child
    if last_p is None:
        last_p = etree.SubElement(guest_body, W + "p")
    if last_p.find(W + "pPr") is None:
        last_p.insert(0, etree.Element(W + "pPr"))
    ppr = last_p.find(W + "pPr")
    if ppr.find(W + "sectPr") is not None:
        # Two sectPr on one paragraph is invalid markup.
        raise MergeError("The cover letter's last paragraph already ends a "
                         "section; cannot attach its page setup.")
    anchor = next((c for c in ppr if c.tag in _AFTER_SECTPR), None)
    if anchor is None:
        ppr.append(final)
    else:
        anchor.addprevious(final)


def _remap_attr(tree, attr: str, mapping: dict) -> None:
    if not mapping:
        return
    for el in tree.iter():
        v = el.get(attr)
        if v is not None and v in mapping:
            el.set(attr, mapping[v])


def _shift_int_attr(tree, tags: Iterable[str], attr: str, offset: int) -> None:
    """Add `offset` to an integer attribute wherever it appears on `tags`."""
    wanted = set(tags)
    for el in tree.iter():
        if el.tag not in wanted:
            continue
        v = el.get(attr)
        if v is None:
            continue
        try:
            el.set(attr, str(int(str(v).strip()) + offset))
        except (TypeError, ValueError):
            continue


def _ensure_content_type(pz, pnames: set, new_parts: dict, parser,
                         ext: str) -> None:
    """Declare `ext` in `[Content_Types].xml` if the host package doesn't."""
    if _CONTENT_TYPES not in pnames:
        return
    raw = new_parts.get(_CONTENT_TYPES)
    root = etree.fromstring(
        raw if raw is not None else pz.read(_CONTENT_TYPES), parser)
    for d in root.findall(CT + "Default"):
        if (d.get("Extension") or "").lower() == ext:
            return
    ctype = _MEDIA_CONTENT_TYPES.get(ext)
    if not ctype:
        raise MergeError(f"The cover letter carries a .{ext} part and the "
                         f"proposal package does not declare that type.")
    el = etree.Element(CT + "Default")
    el.set("Extension", ext)
    el.set("ContentType", ctype)
    root.insert(0, el)
    new_parts[_CONTENT_TYPES] = _xml_bytes(root)


def _drop_header_footer_references(ldoc, lz, lrels, lnames: set) -> int:
    """Remove the letter's header/footer references, or refuse if they matter.

    NOT laziness, and not only because these parts are empty. A `sectPr` with no
    `headerReference` INHERITS the previous section's, so prepending a letter
    section that defines one would hand its chrome to the proposal's section --
    which is no longer the document's first -- and put letterhead furniture on
    every page of a signed contract.

    The proposal does in fact declare its own header and footer references (
    `python-docx` manufactures the parts during the fill, and the Gyp template
    ships a footer with real content), so today that inheritance would not
    actually reach it. Dropping the letter's references is the belt to that
    braces: it removes the thing to be inherited rather than relying on every
    proposal template, present and future, to keep shadowing it.

    Nothing is lost today: `python-docx` MANUFACTURES `header1.xml`/`footer1.xml`
    as a side effect of the fill, and both come out with no text, no drawing and
    no VML. If one ever carries content -- somebody adds a footer bar to the
    letterhead master -- this raises instead, so the loss is a refusal an
    estimator reports rather than a page that quietly went missing."""
    dropped = 0
    lindex = _rel_index(lrels) if lrels is not None else {}
    for el in list(ldoc.iter(W + "headerReference", W + "footerReference")):
        rid = el.get(R + "id")
        rel = lindex.get(rid or "")
        target = (rel.get("Target") if rel is not None else "") or ""
        part = posixpath.normpath(posixpath.join("word", target)) if target else ""
        if part and part in lnames and _part_has_content(lz.read(part)):
            raise MergeError(
                f"The cover letter's {etree.QName(el).localname} points at "
                f"{part}, which has content. Merging it would also put it on "
                f"every proposal page (an absent reference inherits the "
                f"previous section's), so this needs deciding by hand.")
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
            dropped += 1
    if dropped:
        log.debug("docx_merge: dropped %d empty header/footer reference(s) "
                  "from the cover letter's sections", dropped)
    return dropped


def _part_has_content(raw: bytes) -> bool:
    """True if a header/footer part would print anything."""
    try:
        root = etree.fromstring(raw)
    except etree.XMLSyntaxError:
        return True                      # unreadable: treat as significant
    if any((t.text or "").strip() for t in root.iter(W + "t")):
        return True
    return (next(root.iter(W + "drawing"), None) is not None
            or next(root.iter(W + "pict"), None) is not None)


def _copy_letter_media(pz, lz, ldoc, prels, lrels, pnames: set,
                       lnames: set, new_parts: dict, parser) -> None:
    """Copy the media the letter body points at, and re-id its relationships."""
    if lrels is None:
        return
    lindex = _rel_index(lrels)
    rid_map: dict = {}
    # New ids continue past the HOST's highest, so they cannot collide with a
    # relationship the proposal already declares.
    next_rid = _max_id((k or "")[3:] for k in _rel_index(prels)) + 1
    for rid in sorted(_referenced_rids(ldoc)):
        rel = lindex.get(rid)
        if rel is None:
            raise MergeError(f"The cover letter points at relationship {rid}, "
                             f"which its own package does not declare.")
        new_rid = f"rId{next_rid}"
        next_rid += 1
        rtype = rel.get("Type") or ""
        target = rel.get("Target") or ""
        mode = rel.get("TargetMode")
        if mode == "External":
            new_target = target                  # a hyperlink: only the id moves
        elif rtype == _IMAGE_REL:
            src = posixpath.normpath(posixpath.join("word", target))
            if src not in lnames:
                raise MergeError(f"Cover letter media {src} is missing from its "
                                 f"package.")
            base = posixpath.basename(target)
            # Renamed on the way in: both templates ship a
            # `word/media/image1.png`, and the host's must not be overwritten
            # by the guest's letterhead.
            n, name = 0, f"cl_{base}"
            while (f"word/media/{name}" in pnames
                   or f"word/media/{name}" in new_parts):
                n += 1
                name = f"cl{n}_{base}"
            new_parts[f"word/media/{name}"] = lz.read(src)
            new_target = f"media/{name}"
            ext = base.rpartition(".")[2].lower()
            if ext:
                _ensure_content_type(pz, pnames, new_parts, parser, ext)
        else:
            raise MergeError(f"The cover letter body references an unsupported "
                             f"relationship type: {rtype}")
        new_rel = etree.SubElement(prels, PKG_REL + "Relationship")
        new_rel.set("Id", new_rid)
        new_rel.set("Type", rtype)
        new_rel.set("Target", new_target)
        if mode:
            new_rel.set("TargetMode", mode)
        rid_map[rid] = new_rid
    for attr in _RID_ATTRS:
        _remap_attr(ldoc, attr, rid_map)


def _merge_numbering(pnum, lnum, ldoc) -> None:
    """Fold the letter's list definitions into the proposal's numbering part."""
    abs_offset = _max_id(el.get(W + "abstractNumId")
                         for el in pnum.findall(W + "abstractNum")) + 1
    num_offset = _max_id(el.get(W + "numId")
                         for el in pnum.findall(W + "num")) + 1
    guest_abs = list(lnum.findall(W + "abstractNum"))
    guest_num = list(lnum.findall(W + "num"))
    for el in guest_abs:
        _shift_int_attr(el, [el.tag], W + "abstractNumId", abs_offset)
    for el in guest_num:
        _shift_int_attr(el, [el.tag], W + "numId", num_offset)
        ref = el.find(W + "abstractNumId")
        if ref is not None:
            _shift_int_attr(ref, [ref.tag], W + "val", abs_offset)
    # Schema order: every abstractNum precedes every num.
    first_num = pnum.find(W + "num")
    for el in guest_abs:
        if first_num is None:
            pnum.append(el)
        else:
            first_num.addprevious(el)
    for el in guest_num:
        pnum.append(el)
    # And the body's references follow the same offset.
    for numpr in ldoc.iter(W + "numPr"):
        nid = numpr.find(W + "numId")
        if nid is not None:
            _shift_int_attr(nid, [nid.tag], W + "val", num_offset)


def prepend_cover_letter(proposal_docx: bytes, letter_docx: bytes) -> bytes:
    """Return proposal bytes whose first page(s) are `letter_docx`.

    Both arguments are FILLED documents -- tokens already substituted by
    `proposal_writer.fill_proposal` and `cover_letter_writer.fill_cover_letter`.
    Merging after the fill rather than before is deliberate: each writer resolves
    its overrides against block ids that are positions in a walk over its OWN
    template, and one merged template would renumber both walks.

    Raises `MergeError` for anything it cannot do faithfully."""
    try:
        pz = zipfile.ZipFile(io.BytesIO(proposal_docx))
        lz = zipfile.ZipFile(io.BytesIO(letter_docx))
    except zipfile.BadZipFile as exc:
        raise MergeError(f"Not a readable .docx package: {exc}") from exc

    with pz, lz:
        pnames, lnames = set(pz.namelist()), set(lz.namelist())
        if _DOC not in pnames:
            raise MergeError(f"The proposal package is missing {_DOC}.")
        if _DOC not in lnames:
            raise MergeError(f"The cover letter package is missing {_DOC}.")
        if _DOC_RELS not in pnames:
            raise MergeError(f"The proposal package is missing {_DOC_RELS}.")

        parser = etree.XMLParser(remove_blank_text=False)
        pdoc = etree.fromstring(pz.read(_DOC), parser)
        ldoc = etree.fromstring(lz.read(_DOC), parser)
        pbody, lbody = pdoc.find(W + "body"), ldoc.find(W + "body")
        if pbody is None or lbody is None:
            raise MergeError("A package has no w:body.")

        prels = etree.fromstring(pz.read(_DOC_RELS), parser)
        lrels = (etree.fromstring(lz.read(_DOC_RELS), parser)
                 if _DOC_RELS in lnames else None)

        new_parts: dict = {}
        # Before the rid scan: these references are removed, not carried, so the
        # scan below must not try to copy the parts behind them.
        _drop_header_footer_references(ldoc, lz, lrels, lnames)
        _copy_letter_media(pz, lz, ldoc, prels, lrels, pnames, lnames,
                           new_parts, parser)

        pnum = (etree.fromstring(pz.read(_NUMBERING), parser)
                if _NUMBERING in pnames else None)
        lnum = (etree.fromstring(lz.read(_NUMBERING), parser)
                if _NUMBERING in lnames else None)
        if lnum is not None and _uses_numbering(ldoc):
            if pnum is None:
                raise MergeError("The cover letter is numbered but the proposal "
                                 "package has no numbering part to merge into.")
            _merge_numbering(pnum, lnum, ldoc)

        pstyles = (etree.fromstring(pz.read(_STYLES), parser)
                   if _STYLES in pnames else None)
        lstyles = (etree.fromstring(lz.read(_STYLES), parser)
                   if _STYLES in lnames else None)
        if pstyles is not None and lstyles is not None:
            have = {s.get(W + "styleId") for s in pstyles.findall(W + "style")}
            for s in lstyles.findall(W + "style"):
                sid = s.get(W + "styleId")
                if sid and sid not in have:
                    pstyles.append(s)
                    have.add(sid)

        # Word treats a duplicate drawing id as corruption; a duplicate bookmark
        # id silently swallows one of the two.
        # `wp:docPr` ONLY. `pic:cNvPr` is scoped to its own drawing, so shifting
        # it would be meaningless at best; `a:cNvPr` (which an earlier version of
        # this line also named) occurs in none of these files, so it silently
        # matched nothing and read as coverage it never had.
        drawing_offset = _max_id(el.get("id")
                                 for el in pdoc.iter(WP + "docPr")) + 1
        _shift_int_attr(ldoc, (WP + "docPr",), "id", drawing_offset)
        bookmark_offset = _max_id(
            el.get(W + "id") for el in pdoc.iter()
            if el.tag in (W + "bookmarkStart", W + "bookmarkEnd")) + 1
        _shift_int_attr(ldoc, (W + "bookmarkStart", W + "bookmarkEnd"),
                        W + "id", bookmark_offset)

        _move_final_sectpr_onto_last_paragraph(lbody)
        merged_root = _merged_root(pdoc, ldoc)
        merged_body = merged_root.find(W + "body")
        for i, child in enumerate(list(lbody)):
            merged_body.insert(i, child)

        rewritten = {_DOC: _xml_bytes(merged_root),
                     _DOC_RELS: _xml_bytes(prels)}
        if pnum is not None:
            rewritten[_NUMBERING] = _xml_bytes(pnum)
        if pstyles is not None:
            rewritten[_STYLES] = _xml_bytes(pstyles)
        for name, data in new_parts.items():
            rewritten.setdefault(name, data)

        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
            for item in pz.infolist():
                replacement = rewritten.pop(item.filename, None)
                zo.writestr(item, pz.read(item.filename)
                            if replacement is None else replacement)
            for name, data in rewritten.items():
                zo.writestr(name, data)
        return out.getvalue()
