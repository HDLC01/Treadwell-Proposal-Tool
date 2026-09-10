"""The optional Cover Letter — Treadwell's letterhead page, PREPENDED as page 1 of the proposal.

It is not a second document and never was one that reached anybody. From 2026-08-28 it had its
own editor tab, its own `/api/coverletter-template` block model, its own paragraph-override
channel, its own `/api/admin/cover-letter-pdf` render and a `has_cover_letter` flag telling the
customer portal to show it first — and the portal implemented none of that, so every letter an
estimator ticked, edited and generated reached no customer at all. On 2026-09-09 Hanz replaced the
lot with one checkbox: `docx_merge.prepend_cover_letter` puts the filled letter on the front of the
filled proposal, so the .docx download, the LibreOffice PDF, the portal's /api/admin/proposal-pdf
and the To-Dropbox copy all carry it without any of them knowing it exists.

One letterhead template per (work type, audience), filled from the same intake/estimate values the
proposal uses, riding inside the same `proposal_payload` so a sent revision pins the letter exactly
as it pins the prices.

Everything here EXECUTES the real writer and the real templates. A source-text assertion cannot
catch a token nothing fills, a numbering definition Word would reject, or a template that quietly
lost its letterhead — and those are the three ways a first-draft document set goes wrong.

Covers:
  (a) the templates themselves — one per (work type, audience), real letterhead, the dates, no raw
      token left behind, the numbering that has to restart for a second system;
  (b) the generate path — off by default, and ON means the letter's words are IN the proposal
      .docx, ahead of the proposal's own, with no second file anywhere;
  (b2) the label bullets, bold to the colon and normal after, unedited AND overridden. The writer
      still accepts `paragraph_overrides` and nothing in production passes any; these tests are
      what keeps that parameter honest, because the split it performs is the reason it exists;
  (c) PortalPublishIn.has_cover_letter — the omitted-means-nothing-forwarded contract. It no
      longer tells the portal to DO anything (the letter is inside the document), and it is kept
      because it is a true statement about the paperwork and because a portal row that already has
      it must not silently lose it.

The merge itself — id collisions, section properties, the letterhead artwork — is
`test_docx_merge.py`. This file asserts that the letter and the proposal come out of `_generate`
as one document; that file asserts the document is well-formed.
"""
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import zipfile
from unittest import mock

import docx
import pytest
from fastapi.testclient import TestClient

import cover_letter_writer as clw
import docx_merge
import main
import prepare_cover_letter_templates as prep
import proposal_writer as pw

client = TestClient(main.app)

# The (work_type, audience) pairs that have a letter of their own.
VARIANTS = sorted(clw.TEMPLATE_PICKER, key=lambda k: (k[0], k[1] or ""))

BASE = {
    "work_type": "epoxy",
    "audience": "Direct",
    "values": {
        "job_name": "Cover Letter QA", "project_name": "Cover Letter QA",
        "city_state": "Olathe, KS", "bid_date_formatted": "8/26/26",
        "system_name": "Treadwell MACRO Flake", "texture": "Orange Peel",
        "epoxy_sf": "18,000", "cove_lf": "420", "polish_sf": "0",
        "schedule_notes": "~5 working days.", "estimator_name": "Kyle Loseke",
        "lump_sum": "$61,162.00",
    },
}

FULL_VALUES = dict(BASE["values"], **{
    "epoxy_system_name": "Treadwell MACRO Flake",
    "gyp_soft_thickness": '3/4"', "gyp_soft_sf": "9,000",
    "gyp_hard_thickness": '1"', "gyp_hard_sf": "2,500",
})


def _rendered(docx_bytes: bytes) -> str:
    """Every paragraph, TEXT BOXES INCLUDED. `d.paragraphs` alone would miss the floating date on
    the letter and essentially the whole front page of a proposal."""
    d = docx.Document(io.BytesIO(docx_bytes))
    return "\n".join(p.text for p in pw._iter_all_paragraphs(d) if p.text.strip())


def _generate(**extra):
    r = client.post("/api/generate", json={**BASE, **extra})
    assert r.status_code == 200, r.text
    return r.json()


# Which letters print the job name in their own body copy.
#
# Until 2026-09-04 every variant did, because every variant opened with the red heading
# "<System> Proposal - {{job_name}}". Hanz took that heading off all seven, and the two copy sets
# behind them do not agree about what is left: the SHARED copy (GC and Gyp) still opens "Thanks
# for the opportunity to bid on this {{job_name}} project!", while Will's DIRECT copy says "Thank
# you for the opportunity to provide a quote for this project." and names nobody. So a Direct
# letter now identifies the job nowhere on its own page — the greeting names the PERSON — and the
# proposal stapled behind it is what carries the job name.
#
# That is a copy decision, not a bug, and it is recorded here rather than papered over: the
# assertion below is two-sided, so restoring the job name to Will's wording (or losing it from
# GC's on a copy pass) goes red here and has to be a deliberate edit.
_NAMES_THE_JOB = {"Direct": False, "GC": True, None: True}


# ── (a) the templates ────────────────────────────────────────────────────────
def test_the_picker_mirrors_the_proposal_s_shape():
    """Keyed on (work_type, audience) with audience-first folders, like
    `proposal_writer.TEMPLATE_PICKER` — including its asymmetry: gyp's audience is None there and
    here, because a gypsum bid reads the same to an owner and to a GC."""
    assert all(isinstance(k, tuple) and len(k) == 2 for k in clw.TEMPLATE_PICKER)
    assert clw.TEMPLATE_PICKER[("gyp", None)]
    assert ("gyp", "Direct") not in clw.TEMPLATE_PICKER
    assert {a for _, a in clw.TEMPLATE_PICKER} == {"Direct", "GC", None}
    for (_wt, aud), rel in clw.TEMPLATE_PICKER.items():
        assert rel.split("/")[1] == (aud or "Gyp"), rel


@pytest.mark.parametrize("key", VARIANTS)
def test_every_mapped_template_exists_on_disk(key):
    """`pick_template` falls back to Direct/Epoxy on purpose (an unmapped combination still gets a
    letter), which means a MISSING gyp file would send a gyp customer an epoxy letter and log a
    warning nobody reads. This is the assertion that turns that into a red test."""
    assert clw.has_template(*key), (
        str(key) + " has no cover-letter template on disk; pick_template would serve Direct/Epoxy")
    assert clw.pick_template(*key).is_file()


def test_the_generator_and_the_writer_name_the_same_files():
    """Two tables, one set of files. A generator that stops writing a variant the writer still
    picks is a 500 on a real send, and nothing else would notice."""
    assert {"CoverLetter/" + rel for _wt, _aud, rel in prep.VARIANTS} == set(clw.TEMPLATE_PICKER.values())
    assert {(wt, aud) for wt, aud, _ in prep.VARIANTS} == set(clw.TEMPLATE_PICKER)


def test_gc_combo_has_its_own_letter_unlike_the_proposal():
    """The proposal reuses the GC resinous DOCUMENT for a GC combo bid because Kyle never made a
    GC combo file. A letter that did the same would tell a combo customer, in prose, that the
    pages behind it are an epoxy proposal — half the scope missing from the one page written to
    describe the job."""
    assert clw.pick_template("combo", "GC") != clw.pick_template("epoxy", "GC")
    text = _rendered(clw.fill_cover_letter(work_type="combo", audience="GC", values=FULL_VALUES))
    assert "Polished Concrete" in text and "Epoxy" in text


def test_an_unmapped_work_type_still_produces_a_letter():
    """sealer/budget have no letter of their own. Falling back beats 500-ing a generate."""
    assert clw.pick_template("sealer", "GC").name == "Epoxy.docx"
    assert clw.pick_template("sealer", "GC").parent.name == "Direct"
    assert clw.has_template("sealer", "GC") is False


def test_gyp_reaches_its_one_file_from_either_audience():
    """The audience-agnostic rung of the ladder, the same one `proposal_writer.pick_template`
    uses for (gyp, None)."""
    one = clw.pick_template("gyp", None)
    assert clw.pick_template("gyp", "Direct") == one
    assert clw.pick_template("gyp", "GC") == one
    assert clw.has_template("gyp", "GC") is True


@pytest.mark.parametrize("key", VARIANTS)
def test_a_filled_letter_leaves_no_raw_token(key):
    """The rule the proposal already lives by: a customer-facing document never shows a literal
    {{token}}. Executed against the REAL template, so a token added to the copy without a value
    behind it fails here rather than on a customer's screen."""
    work_type, audience = key
    blob = clw.fill_cover_letter(work_type=work_type, audience=audience, values=FULL_VALUES)
    assert clw.unfilled_tokens(docx.Document(io.BytesIO(blob))) == set()
    text = _rendered(blob)
    assert "Kyle Loseke" in text              # {{estimator_name}} signed it
    assert ("Cover Letter QA" in text) is _NAMES_THE_JOB[audience]


@pytest.mark.parametrize("key", VARIANTS)
def test_the_letterhead_survives(key):
    """The branding is the whole point of the document. It is a full-page PNG anchored on page
    one; a template rebuilt without it is a blank sheet with three bullets on it."""
    path = clw.pick_template(*key)
    with zipfile.ZipFile(str(path)) as z:
        assert [n for n in z.namelist() if n.startswith("word/media/")], \
            path.name + " has no letterhead artwork"
    _, _, geometry = clw.describe_template(*key)
    assert geometry["images"], path.name + " draws no image on the page"


@pytest.mark.parametrize("key", VARIANTS)
def test_a_letter_is_pure_flow_with_no_floating_box(key):
    """Kyle's example letter floats the date over the artwork in a small anchored box, and these
    templates copied that box verbatim until 2026-09-04, when Hanz asked for the date off every
    format. Removing it took the ONLY text box out of these documents, so a letter is now nothing
    but flowing body paragraphs. Two things the editor reads off this response:

      * `in_block` is None everywhere — a letter has no priced/repeatable region, so every
        paragraph is freely editable and nothing is engine-owned;
      * NOTHING is positioned. That mattered for the document editor, which had a no-box layout
        branch to fall into (a template with no boxes was a layout, not a failure); the editor is
        gone since 2026-09-09 and the claim outlived it, because `_halves` and
        `_body_paragraphs` in section (b) both rely on the letter being pure flow to tell the two
        documents apart in the merged .docx. A stray box re-appearing on a copy pass would put
        one letter line after the whole proposal in those walks — so it goes red here rather
        than on a customer's screen.
    """
    _, blocks, geometry = clw.describe_template(*key)
    assert len(blocks) > 5
    assert all(b["in_block"] is None for b in blocks)
    assert [b["text"] for b in blocks if b["in_txbx"]] == []
    assert geometry["boxes"] == []
    # The letterhead artwork is still drawn — it is an image, not a box.
    assert geometry["images"]


@pytest.mark.parametrize("key", VARIANTS)
def test_no_variant_prints_a_date_or_the_old_heading(key):
    """The two things Hanz took off, asserted at the FILE, for every format at once.

    Read from the raw XML rather than the paragraph text because the date lived inside
    `mc:AlternateContent` — stored twice, once as the modern `wps` shape and once as a VML
    fallback — and `d.paragraphs` sees neither copy. A half-removal that left the fallback behind
    would print the date on any consumer that reads VML, and every paragraph-level assertion in
    this file would stay green.
    """
    xml = zipfile.ZipFile(str(clw.pick_template(*key))).read("word/document.xml").decode("utf8")
    assert "{{proposal_date_short}}" not in xml, "the date box survived in this variant"
    assert "txbxContent" not in xml, "a text box survived in this variant"
    # The heading was "<System> Proposal - {{job_name}}". Match on the connective rather than one
    # variant's system name, so Polish and Combo are covered by the same line.
    assert "Proposal - " not in xml, "the red title line survived in this variant"


@pytest.mark.parametrize("key", VARIANTS)
def test_the_letterhead_artwork_is_the_only_drawing_left(key):
    """Two `wp:docPr` sharing an id is a file Word 'repairs' on open by dropping a shape — and the
    shape it drops is silent. There used to be two (the artwork and the date box); with the box
    gone there is exactly one, which is also a second, independent check that the box is really
    out of the file rather than merely emptied of its text."""
    d = docx.Document(str(clw.pick_template(*key)))
    ids = [e.get("id") for e in d.element.body.iter(pw.qn("wp:docPr"))]
    assert len(ids) == len(set(ids)) == 1, ids


def test_combo_numbering_restarts_for_the_second_system():
    """Combo carries two system sections and Hanz's Template 3 numbers each of them 1/2/3.

    This assertion is the EDITOR's view, and on its own it is not enough — it was green on
    2026-08-29 over a Word render that printed the Polished Concrete items as 4/5/6.
    `_ordered_markers` runs one counter per `(numId, ilvl)`, which is right for a list whose
    instance owns its count and blind to the case below. Kept because it is what the editor draws;
    paired with `test_the_second_system_s_numbering_really_restarts_in_word` because it is not
    what Word obeys."""
    _, blocks, _ = clw.describe_template("combo", "Direct")
    markers = [b["para"]["marker"] for b in blocks if b["para"]["marker"]]
    # DERIVED, not restated. Direct's first section gained an "Area:" item on 2026-09-03 (Will's
    # wording), so the two sections are no longer the same length and a hard-coded 3+3 was
    # asserting the copy rather than the numbering. The claim is that the count RESTARTS: two
    # runs, each beginning at 1 and counting up by one.
    runs, cur = [], []
    for m in markers:
        if m == "1." and cur:
            runs.append(cur)
            cur = []
        cur.append(m)
    if cur:
        runs.append(cur)
    assert len(runs) == 2, markers
    for run in runs:
        assert len(run) >= 3, markers        # an empty second run would satisfy "restarts"
        assert run == ["%d." % (i + 1) for i in range(len(run))], markers


@pytest.mark.parametrize("key", VARIANTS)
def test_the_second_system_s_numbering_really_restarts_in_word(key):
    """The rule Word actually applies, asserted on the real numbering part.

    A list's counter belongs to the `w:abstractNum`, NOT to the `w:num` that points at it. The
    generator gives the two Combo sections two `w:num` ids over one shared abstract definition and
    its comment claimed that was enough to restart the count; it is not, and Word rendered
    "4. Schedule:" under "Polished Concrete:". The only reset in OOXML is an explicit
    `w:lvlOverride`/`w:startOverride`.

    So: any two numbering instances this document uses that share an abstract must each carry a
    startOverride at the level they print. Checked on every variant, not just Combo — a
    single-section letter shares the same numbering part and would drift the same way if a second
    instance ever appeared."""
    d = docx.Document(str(clw.pick_template(*key)))
    numbering = d.part.numbering_part.element

    used = set()
    for p in d.element.body.iter(pw.qn("w:p")):
        for num in p.iter(pw.qn("w:numId")):
            used.add(num.get(pw.qn("w:val")))
    assert used, clw.pick_template(*key).name + " has no numbered list at all"

    by_abstract: dict = {}
    for num in numbering.findall(pw.qn("w:num")):
        if num.get(pw.qn("w:numId")) not in used:
            continue
        ref = num.find(pw.qn("w:abstractNumId"))
        by_abstract.setdefault(ref.get(pw.qn("w:val")), []).append(num)

    for abstract_id, instances in by_abstract.items():
        if len(instances) < 2:
            continue
        for num in instances:
            starts = [ov.find(pw.qn("w:startOverride"))
                      for ov in num.findall(pw.qn("w:lvlOverride"))
                      if ov.get(pw.qn("w:ilvl")) == "0"]
            starts = [s for s in starts if s is not None]
            assert starts and starts[0].get(pw.qn("w:val")) == "1", (
                "numId %s shares abstractNum %s with %d other instance(s) and has no "
                "startOverride, so Word continues the count instead of restarting it"
                % (num.get(pw.qn("w:numId")), abstract_id, len(instances) - 1))


# ── (a3) the letter is one page, and these are the four reasons it is ────────
# Combo stranded its entire sign-off on a second, LETTERHEAD-LESS page: the artwork is anchored
# to page one, so page two came out as five grey lines on blank paper. Rendered with Word COM and
# measured with PyMuPDF on 2026-08-29 — before, page one ended at 691.59pt against a 693.0pt
# text-area bottom with the tagline pushed over; after, at 677.55pt with 15.45pt to spare, and
# all seven variants are one page.
#
# The PAGE COUNT itself cannot be asserted here: there is no renderer in the test environment
# (no LibreOffice, no Word), and an estimator accurate to ±20pt cannot tell a 15pt margin from an
# overflow — it would be a green light with nothing behind it. What is asserted instead is each
# of the four measured causes, every one of them read off the real generated file.
_BODY_HALF_PT = int(round(prep.BODY_PT.pt * 2))
_SIG_HALF_PT = int(round(prep.SIG_PT.pt * 2))


def _generated_paragraphs(d):
    """The paragraphs this generator wrote: the direct `w:p` children of the body that follow the
    letterhead's `w:sdt`. Excludes Kyle's own two — the section-break paragraph before the `sdt`
    and the artwork host inside it — which are copied byte-for-byte and are not ours to size."""
    out, seen_sdt = [], False
    for child in d.element.body:
        if child.tag == pw.qn("w:sdt"):
            seen_sdt = True
        elif seen_sdt and child.tag == pw.qn("w:p"):
            out.append(child)
    assert out, "found no generated paragraphs after the letterhead sdt"
    return out


def _mark_half_pt(p):
    ppr = p.find(pw.qn("w:pPr"))
    rpr = ppr.find(pw.qn("w:rPr")) if ppr is not None else None
    sz = rpr.find(pw.qn("w:sz")) if rpr is not None else None
    return int(sz.get(pw.qn("w:val"))) if sz is not None else None


def _run_half_pts(p):
    out = []
    for r in p.findall(pw.qn("w:r")):
        sz = r.find(pw.qn("w:rPr") + "/" + pw.qn("w:sz"))
        if sz is not None:
            out.append(int(sz.get(pw.qn("w:val"))))
    return out


@pytest.mark.parametrize("key", VARIANTS)
def test_every_paragraph_mark_is_the_size_of_its_own_text(key):
    """Cause 1, and the one nothing on screen shows you.

    Word gives a line the height of the tallest thing on it and the invisible `¶` counts.
    `add_paragraph()` leaves that mark at the style default — 12pt here — so in an 11pt letter
    every paragraph's LAST line was 14.06pt tall against 12.94pt for its wrapped ones, and the
    blank line inside a 10pt signature was a 12pt blank line. Worth ~22pt on Combo. It is
    invisible in Word, invisible in the block model, and it is why the mark is set explicitly."""
    d = docx.Document(str(clw.pick_template(*key)))
    for p in _generated_paragraphs(d):
        mark = _mark_half_pt(p)
        text = "".join(t.text or "" for t in p.iter(pw.qn("w:t")))
        assert mark in (_BODY_HALF_PT, _SIG_HALF_PT), (
            "paragraph %r carries no explicit mark size, so its last line is the style's 12pt"
            % text[:40])
        runs = _run_half_pts(p)
        if runs:
            assert mark == max(runs), (
                "paragraph %r prints at %.1fpt but its mark is %.1fpt"
                % (text[:40], max(runs) / 2.0, mark / 2.0))


@pytest.mark.parametrize("key", VARIANTS)
def test_the_thank_you_runs_straight_into_the_line_that_introduces_the_proposal(key):
    """Cause 2. Example1 sets those two lines adjacent (measured at a 0.02pt gap in his render);
    the blank paragraph between them was this generator's invention and cost ~15pt."""
    d = docx.Document(str(clw.pick_template(*key)))
    texts = ["".join(t.text or "" for t in p.iter(pw.qn("w:t"))).strip()
             for p in _generated_paragraphs(d)]
    # Two wordings per line since Direct took Will's text on 2026-09-03. The claim under test
    # is ADJACENCY, not the copy -- so match either and assert nothing sits between them.
    thanks = ("Thanks for the opportunity", "Thank you for the opportunity")
    opens_the_list = ("The pages that follow", "A few things to note")
    i = next(i for i, t in enumerate(texts) if t.startswith(thanks))
    assert texts[i + 1].startswith(opens_the_list), texts[i:i + 3]


@pytest.mark.parametrize("key", VARIANTS)
def test_the_numbered_items_run_together_with_air_only_around_the_list(key):
    """Cause 3. Kyle's three items are contiguous — his `beforeAutospacing` puts ~14pt above the
    list and collapses to nothing between its rows. A `space_after` on every item spread the six
    Combo rows by ~36pt for no gain, and this asserts both halves of his shape: no space BETWEEN
    the rows, and real air ABOVE the row that opens a group."""
    d = docx.Document(str(clw.pick_template(*key)))
    numbered = [p for p in _generated_paragraphs(d)
                if p.find(pw.qn("w:pPr") + "/" + pw.qn("w:numPr")) is not None]
    assert len(numbered) >= 3, len(numbered)

    opens_a_group = []
    for p in numbered:
        spacing = p.find(pw.qn("w:pPr") + "/" + pw.qn("w:spacing"))
        after = spacing.get(pw.qn("w:after")) if spacing is not None else None
        assert after in (None, "0"), (
            "a numbered item carries %s twips of space_after; Kyle's run together" % after)
        before = spacing.get(pw.qn("w:before")) if spacing is not None else None
        opens_a_group.append(before not in (None, "0"))

    # Combo's second group opens on its heading, not on an item, so the count is 0 or 1 per
    # variant — what must not happen is that EVERY row is spaced, or that a group opens flush.
    heads = [p for p in _generated_paragraphs(d)
             if "".join(t.text or "" for t in p.iter(pw.qn("w:t"))).strip().endswith(":")
             and p.find(pw.qn("w:pPr") + "/" + pw.qn("w:spacing")) is not None]
    assert sum(opens_a_group) + len(heads) >= 1, "the numbered list opens flush against the intro"
    assert sum(opens_a_group) <= 1, "more than one numbered row is spaced off the one above it"


@pytest.mark.parametrize("key", VARIANTS)
def test_there_is_no_title_line_and_the_body_keeps_kyles_right_indent(key):
    """Every letter used to open with a red underlined heading — "Epoxy / Resinous Flooring
    Proposal - {{job_name}}" and its siblings. Hanz took it off every format on 2026-09-04: the
    proposal stapled behind the letter names the system and the job on its own front page, and a
    heading that repeats it is a second place for the job name to go stale. The greeting is now
    the first line on the page.

    The second half is the part that is easy to lose while deleting the first. Kyle's example
    carries `w:ind w:right="2340"` (117pt) on its BODY paragraphs — that is what keeps the text
    off the letterhead's right-hand artwork — and it was the TITLE that was the exception. Delete
    the title carelessly and the indent goes with it, which no reader of the diff would notice
    and every printed letter would show.
    """
    d = docx.Document(str(clw.pick_template(*key)))
    paras = _generated_paragraphs(d)
    first = "".join(t.text or "" for t in paras[0].iter(pw.qn("w:t")))
    assert "Proposal - " not in first, "the title line is still the first thing on the page"
    assert first.strip() in ("{{greeting}}", "Hello,"), first

    def right_tw(p):
        ind = p.find(pw.qn("w:pPr") + "/" + pw.qn("w:ind"))
        return ind.get(pw.qn("w:right")) if ind is not None else None

    assert all(right_tw(p) == "2340" for p in paras),         "the body lost Kyle's 117pt right indent"


def test_the_letter_does_not_read_like_an_email():
    """The PDF these templates came from was written as outbound email. Hanz confirmed this is a
    portal document page, so the email framing had to go — and this is the assertion that stops it
    creeping back in on a copy pass."""
    text = _rendered(clw.fill_cover_letter(work_type="epoxy", audience="Direct",
                                           values=FULL_VALUES)).lower()
    assert "subject line" not in text
    assert "to this email" not in text
    assert "attached" not in text


def test_the_date_is_backfilled_from_the_bid_date_not_a_clock():
    """No letter PRINTS a date any more (the letterhead box came off on 2026-09-04), but
    `_ensure_cover_letter_values` still resolves `{{proposal_date_short}}` because the same values
    dict fills the PROPOSAL in the same request. This box runs ~13 hours ahead of Central, so a
    date taken off `datetime.now()` would be a day out; a replayed payload that predates the field
    must still resolve to a real date rather than to today."""
    values = {k: v for k, v in FULL_VALUES.items() if k != "proposal_date"}
    values["bid_date_formatted"] = "8/26/26"
    assert clw._ensure_cover_letter_values(values)["proposal_date_short"] == "8/26/26"


# ── (a2) the short date still has to PARSE, even though no letter prints it ──
# Kyle drew a 63pt date box on his letterhead and Word clips rather than grows, so a long-form
# date once printed as the single word "August" on all seven letters. The box is gone (2026-09-04)
# and with it the clipping, but `{{proposal_date_short}}` is still resolved from the same values
# dict — the PROPOSAL uses it — so the parsing ladder below still has to hold.


def test_the_long_date_is_not_narrowed_for_the_proposal_too():
    """`{{proposal_date}}` and `{{proposal_date_short}}` are two tokens on purpose. The same values
    dict fills the PROPOSAL in the same request and its header prints long form; narrowing the one
    token would silently re-date every proposal document to M/D/YY."""
    out = clw._ensure_cover_letter_values(dict(FULL_VALUES, proposal_date="August 27, 2026"))
    assert out["proposal_date"] == "August 27, 2026"
    # NOT "8/27/26": `bid_date_formatted` ("8/26/26" in FULL_VALUES) outranks `proposal_date`
    # for the letterhead box, because it is what the proposal's own header prints. `proposal_date`
    # is stamped fresh to "today" on every generate and would otherwise date the letterhead the
    # day someone clicked Generate rather than the day the bid was actually dated.
    assert out["proposal_date_short"] == "8/26/26"


def test_the_short_date_prefers_the_bid_date_over_todays_stamped_proposal_date():
    """The bug this guards: `proposal_date` is recomputed to `new Date()` on every Proposal Review
    load (`proposal-review.js`), so a bid entered 2026-08-20 and finalized/sent 2026-08-27 must
    still letterhead itself 8/20/26 — the same date the proposal's own header prints — not the day
    someone happened to click Generate."""
    out = clw._ensure_cover_letter_values(dict(
        FULL_VALUES,
        bid_date_formatted="8/20/26",
        proposal_date="August 27, 2026",
    ))
    assert out["proposal_date_short"] == "8/20/26"


@pytest.mark.parametrize("raw, expect", [
    ("8/26/26", "8/26/26"),            # Kyle's own spelling, and what the payload already carries
    ("08/26/2026", "8/26/26"),         # four-digit year
    ("2026-08-26", "8/26/26"),         # the ISO bid_date column
    ("August 26, 2026", "8/26/26"),    # what the Proposal Review screen stamps
    ("Aug 26, 2026", "8/26/26"),
    ("", None),
    (None, None),
    ("TBD", None),                     # not a date; the caller must not print it in a 63pt box
    ("next Tuesday", None),
])
def test_the_short_date_reads_every_shape_the_payload_arrives_in(raw, expect):
    """`_short_date` PARSES, it never clocks — this box runs ~13 hours ahead of Central and a
    `now()` here would date a letter sent Tuesday evening as Wednesday. `%y` is tried before `%Y`
    so "8/26/26" is 2026 and not the year 26."""
    assert clw._short_date(raw) == expect


def test_an_undatable_payload_resolves_to_blank_rather_than_to_garbage():
    """Empty beats a half-parsed date. The refusal is logged naming the value that failed to parse
    — see `_ensure_cover_letter_values` — and nothing else moves. Asserted at the values pass
    because the letter no longer prints this token; a caller that DOES print it must be handed a
    blank string rather than the literal "TBD"."""
    values = {k: v for k, v in FULL_VALUES.items()
              if k not in ("proposal_date", "bid_date_formatted", "bid_date", "site_visit_date")}
    values["proposal_date"] = "TBD"
    assert clw._ensure_cover_letter_values(values)["proposal_date_short"] == ""
    # And the letter itself is still clean — blank, never a raw {{token}}.
    d = docx.Document(io.BytesIO(
        clw.fill_cover_letter(work_type="epoxy", audience="Direct", values=values)))
    assert clw.unfilled_tokens(d) == set()


def test_filling_the_letter_does_not_mutate_the_caller_s_values():
    """The SAME dict is handed to fill_proposal in the same request. A writer that grows keys on
    its caller's data is how the proposal starts printing something nobody typed."""
    values = dict(FULL_VALUES)
    before = dict(values)
    clw.fill_cover_letter(work_type="epoxy", audience="Direct", values=values)
    assert values == before


# ── (b) the generate path: the letter IS the proposal's first page ───────────
# THE MARKERS, and why they are these. `_LETTER_*` are two lines the shipped Direct letter prints
# and the Direct proposal template does not; `_PROPOSAL_ONLY` is a heading the proposal prints and
# the letter does not. Every test below is a claim about which of two documents a piece of text
# came from, so a marker that turned out to be in BOTH — or in neither — would make those claims
# unfalsifiable. `test_the_markers_really_do_tell_the_two_documents_apart` is the counterexample
# that keeps them honest: read it first when anything in this section goes red, because a marker
# that has drifted out of a template fails several tests at once and none of them by name.
_LETTER_OPENING = "Thank you for the opportunity to provide a quote for this project."
_LETTER_SIGNOFF = "Looking forward to working with you!"
_PROPOSAL_ONLY = "TERMS AND CONDITIONS"


def _body_paragraphs(docx_bytes: bytes):
    """`d.paragraphs` — the BODY, in real document order, blanks included.

    Deliberately not `_rendered`, which walks the text boxes after the body and so reports a
    proposal's own front page LAST. Document order is the whole question here ("is the letter page
    1?"), and the letter is pure flow with no floating box of its own
    (test_a_letter_is_pure_flow_with_no_floating_box), so every one of its paragraphs is a body
    paragraph and this walk sees all of them in the order Word will lay them out."""
    return [p.text for p in docx.Document(io.BytesIO(docx_bytes)).paragraphs]


def _body_index(paragraphs, needle):
    """The index of the first body paragraph containing `needle`, or None."""
    return next((i for i, t in enumerate(paragraphs) if needle in t), None)


def _halves(docx_bytes: bytes):
    """`(letter_text, proposal_text)` for a merged document, split at the Terms heading.

    `_PROPOSAL_ONLY` is the first thing the proposal itself prints in this walk — the letter is
    pure flow and comes first, and the proposal's own front page lives in text boxes that
    `_iter_all_paragraphs` visits after the body. Verified rather than assumed: for both audiences
    the lines before the Terms heading are EXACTLY the standalone letter, which is what
    test_the_two_halves_are_really_the_two_documents asserts.

    A split is needed because the two documents are one file now. "The letter says X and the
    proposal says X" used to be two `client.get`s; asserting it against the merged text would
    instead be satisfied by either half alone, which is how a merge that dropped the proposal
    entirely would keep a green test."""
    lines = [t for t in _rendered(docx_bytes).split("\n")]
    cut = next((i for i, t in enumerate(lines) if _PROPOSAL_ONLY in t), None)
    assert cut is not None, (
        "the proposal's %r heading is not in the merged document, so the letter and the proposal "
        "cannot be told apart" % _PROPOSAL_ONLY)
    return "\n".join(lines[:cut]), "\n".join(lines[cut:])


def test_the_two_halves_are_really_the_two_documents():
    """THE PREMISE OF `_halves`, checked for both audiences rather than trusted. It splits the
    merged text at the Terms heading and calls everything before it "the letter" — true only
    while the proposal prints nothing ahead of that heading in this walk. Kyle's templates put
    the front page in text boxes, which are walked last, so it holds today; a template edit that
    moved one line of the proposal into the flowing body would silently reassign it to the letter
    and every content assertion below would be reading the wrong half.

    So: the lines before the cut must be, exactly, the standalone letter."""
    for audience in ("Direct", "GC"):
        values = dict(BASE["values"])
        letter = _rendered(clw.fill_cover_letter(work_type="epoxy", audience=audience,
                                                 values=values))
        merged = docx_merge.prepend_cover_letter(
            pw.fill_proposal(work_type="epoxy", audience=audience, values=dict(values)),
            clw.fill_cover_letter(work_type="epoxy", audience=audience, values=dict(values)))
        letter_half, proposal_half = _halves(merged)
        assert letter_half == letter, (
            "the %s split does not land between the two documents. Before the Terms heading the "
            "merged document has:\n%r\nand the standalone letter is:\n%r"
            % (audience, letter_half[-400:], letter[-400:]))
        assert proposal_half, "the proposal's half of the %s document is empty" % audience


def test_the_markers_really_do_tell_the_two_documents_apart():
    """THE COUNTEREXAMPLE FOR EVERY TEST BELOW. Each of them says "this text is the letter's" or
    "this text is the proposal's", and a marker string that had drifted out of one template — a
    copy pass, a re-generated letterhead — would turn those into assertions about nothing that go
    on passing. So both documents are built standalone here and each marker is checked against
    both: present in the one it belongs to, absent from the other.

    If this goes red, the markers are wrong, not the merge. Fix them here first."""
    letter = _rendered(clw.fill_cover_letter(work_type="epoxy", audience="Direct",
                                             values=dict(BASE["values"])))
    proposal = _rendered(pw.fill_proposal(work_type="epoxy", audience="Direct",
                                          values=dict(BASE["values"])))
    for marker in (_LETTER_OPENING, _LETTER_SIGNOFF):
        assert marker in letter, (
            "the Direct letter no longer says %r — update the marker, do not loosen the tests "
            "that use it" % marker)
        assert marker not in proposal, (
            "%r is in the PROPOSAL template too, so 'the letter's text is in the .docx' stops "
            "being a claim about the letter" % marker)
    assert _PROPOSAL_ONLY in proposal, (
        "the proposal no longer prints %r — the 'both documents are in there' assertions would "
        "then only be checking the letter" % _PROPOSAL_ONLY)
    assert _PROPOSAL_ONLY not in letter, (
        "%r is in the LETTER now, so it cannot stand for the proposal's own content"
        % _PROPOSAL_ONLY)


def test_the_cover_letter_is_off_by_default_and_a_legacy_payload_still_replays():
    """Off by default: every draft saved before this feature carries none of these keys, and
    `GenerateIn(**proposal_payload)` is how the portal PDF, the revision replay and the To-Dropbox
    re-upload rebuild those payloads.

    AND THE TWO REMOVED KEYS MUST BE IGNORED, NOT REFUSED. Between 2026-08-28 and 2026-09-09 a
    generate payload could also carry `cover_letter_paragraph_overrides` and
    `cover_letter_template_version`, and drafts saved in that window still have them frozen inside
    `proposal_payload`. Those payloads are replayed months later, by a customer opening a portal
    link. Pydantic ignores unknown keys by default, so they keep working and simply stop honouring
    edits nothing can make any more — but "by default" is a config away from being false, and
    `extra="forbid"` on this model would turn every one of those drafts into a 422 on the
    customer's side. Asserted, because nothing else would notice until it happened."""
    gi = main.GenerateIn(**{"work_type": "epoxy", "values": {}})
    assert gi.cover_letter_enabled is False
    legacy = main.GenerateIn(**{
        "work_type": "epoxy", "values": {}, "cover_letter_enabled": True,
        "cover_letter_paragraph_overrides": {"3": {"text": "an edit nothing can make now"}},
        "cover_letter_template_version": "epoxy:Direct@1756000000000000000"})
    assert legacy.cover_letter_enabled is True, (
        "a payload frozen while the editor existed no longer replays — a customer's pinned "
        "revision would 422 instead of rendering")
    for dead in ("cover_letter_paragraph_overrides", "cover_letter_template_version"):
        assert not hasattr(legacy, dead), (
            dead + " is back on GenerateIn; there is no editor to produce it and no sanitizer to "
            "validate it")


def test_disabled_means_the_proposal_alone_and_no_second_download():
    """Not an empty string, not a url that 404s: the key does not exist. `GenerateOut` used to
    carry `cover_letter_download_url` and the Done page branched on it; both are gone, and a key
    that came back as `null` would let a caller start branching on it again.

    And the proposal is the proposal. A merge that ran unconditionally would put Treadwell's
    letterhead on the front of every bid, most of which do not want one, and the estimator would
    only find out from the customer."""
    out = _generate()
    # Asserted on the MODEL as well as on the payload, and the pair is deliberate. FastAPI
    # serializes exactly `GenerateOut`'s declared fields, so the response can only regrow this key
    # by the field being re-declared — which means the payload check alone cannot be made to fail
    # by any amount of runtime misbehaviour, only by that source change. The model check names the
    # source change directly; the payload check is what proves the route really is filtered
    # through the model (`out["docx_download_url"]` below is the positive control for that).
    assert "cover_letter_download_url" not in main.GenerateOut.model_fields, (
        "GenerateOut declares a cover-letter download again; the letter is page 1 of the "
        "proposal, so a second file either 404s or duplicates it")
    assert "cover_letter_download_url" not in out, (
        "GenerateOut is advertising a separate cover-letter download again")
    assert out["docx_download_url"]
    paragraphs = _body_paragraphs(client.get(out["docx_download_url"]).content)
    joined = "\n".join(paragraphs)
    for marker in (_LETTER_OPENING, _LETTER_SIGNOFF):
        assert marker not in joined, (
            "a bid that did not ask for a cover letter got one: %r is in the proposal .docx"
            % marker)
    assert _PROPOSAL_ONLY in joined, "the proposal itself came out empty"


def test_enabled_puts_the_letter_in_front_of_the_proposal_in_one_document():
    """THE FEATURE. One .docx, letter first, proposal whole and behind it — which is what makes
    every downstream consumer carry the letter without knowing it exists.

    Both documents' text, and the ORDER. Either half alone would pass a broken merge: a document
    that dropped the proposal still contains the letter's words, and a document that appended the
    letter to the END still contains both. There is still no second download, because there is no
    second file."""
    out = _generate(cover_letter_enabled=True)
    assert "cover_letter_download_url" not in out
    paragraphs = _body_paragraphs(client.get(out["docx_download_url"]).content)
    i_letter = _body_index(paragraphs, _LETTER_OPENING)
    i_signoff = _body_index(paragraphs, _LETTER_SIGNOFF)
    i_proposal = _body_index(paragraphs, _PROPOSAL_ONLY)
    assert i_letter is not None, (
        "the letter's opening line is not in the proposal .docx — the estimator ticked the box "
        "and got the proposal alone, with nothing on screen saying so")
    assert i_proposal is not None, (
        "the PROPOSAL's own text is missing from the merged document; the letter replaced the "
        "contract instead of being stapled in front of it")
    assert i_letter < i_signoff < i_proposal, (
        "the letter is not page 1: opening at %r, sign-off at %r, the proposal's Terms at %r"
        % (i_letter, i_signoff, i_proposal))
    # And it is one document, not the proposal twice: the letter's page is not a copy of the bid.
    text = _rendered(client.get(out["docx_download_url"]).content)
    assert text.count(_PROPOSAL_ONLY) == 1, "the proposal's Terms appear twice"


def test_a_broken_letter_fails_the_live_generate_loudly(monkeypatch):
    """An estimator who ticked the box must not be handed a silent proposal-only send. They would
    read "generated", press Send, and the customer would receive a document with its first page
    missing — the same shape of failure as the publish that wrote the proposal row, refused the
    attachment, logged it and returned 200."""
    def boom(*a, **k):
        raise RuntimeError("template is corrupt")
    monkeypatch.setattr(clw, "fill_cover_letter", boom)
    r = client.post("/api/generate", json=dict(BASE, cover_letter_enabled=True))
    assert r.status_code >= 400, "a failed letter was swallowed on the live generate path"
    assert "cover letter" in r.json()["detail"].lower(), (
        "the refusal does not name the cover letter, so the estimator cannot tell what failed: %r"
        % (r.json(),))


def _pinned(monkeypatch, payload, live=None):
    """SERVICE_TOKEN plus a draft whose revision and live copy are both `payload`."""
    monkeypatch.setitem(os.environ, "SERVICE_TOKEN", "svc-test")
    monkeypatch.setattr(main.drafts, "get_revision",
                        lambda did, no: {"data": {"proposal_payload": payload}})
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda did: {"data": {"proposal_payload":
                                              live if live is not None else payload}})


def test_a_broken_letter_now_fails_the_customers_pdf_too(monkeypatch):
    """THE REVERSAL, STATED OUT LOUD. Until 2026-09-09 this route passed `want_cover_letter=False`
    and the test here asserted the opposite of this one: a cover-letter fault must not 500 the
    proposal PDF the portal is waiting on, because the letter was a separate document this route
    never served.

    It serves it now — the letter is page 1 of this very PDF. So the trade has flipped with it, and
    it is a deliberate trade rather than an oversight: a refusal is reportable, and a customer PDF
    that silently arrives without the page the estimator approved is not. The blast radius really
    is wider than it was (the letter templates are re-generated from Kyle's master by hand, per
    CoverLetter/README.md, so they can break while the estimate sheet and the proposal templates
    are fine) and that is the accepted cost.

    Executed through the route, not read off the source: the refusal has to survive the handler's
    own error handling, which is where a 500 turns back into a 200 with something missing."""
    monkeypatch.setattr(clw, "fill_cover_letter",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("template is corrupt")))
    _pinned(monkeypatch, dict(BASE, cover_letter_enabled=True))
    r = client.get("/api/admin/proposal-pdf?draft_id=d1",
                   headers={"X-Service-Token": "svc-test"})
    assert r.status_code == 500, (
        "the customer's PDF rendered anyway, so it is missing the cover-letter page 1 the "
        "estimator approved and nothing says so: %s %s" % (r.status_code, r.text[:200]))
    assert "cover letter" in r.json()["detail"].lower(), (
        "the refusal does not name the cover letter: %r" % (r.json(),))


def test_the_customers_pdf_still_renders_when_the_letter_is_fine(monkeypatch):
    """The other half, and the reason the test above is not merely "this route 500s". Without this
    one, a route that had come to refuse EVERY render — a letter-enabled draft it could no longer
    handle at all — would pass it, and the pair would look like a working refusal.

    LibreOffice is stubbed: it is what production renders with and it is not on every dev box, and
    the claim here is about the route reaching a 200 with the box ticked, not about soffice. The
    document that reaches it is the REAL merged .docx — `_generate` is untouched — and
    test_enabled_puts_the_letter_in_front_of_the_proposal_in_one_document is what checks its
    contents."""
    _pinned(monkeypatch, dict(BASE, cover_letter_enabled=True))
    rendered_from = {}

    def fake_pdf(blob):
        rendered_from["bytes"] = blob
        return b"%PDF-1.4"

    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", fake_pdf)
    r = client.get("/api/admin/proposal-pdf?draft_id=d1",
                   headers={"X-Service-Token": "svc-test"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    # The bytes handed to the renderer are the merged document, not the bare proposal.
    joined = "\n".join(_body_paragraphs(rendered_from["bytes"]))
    assert _LETTER_OPENING in joined and _PROPOSAL_ONLY in joined, (
        "the customer's PDF was rendered from a document that is missing one of the two halves")


@pytest.mark.parametrize("audience", ["Direct", "GC"])
def test_the_audience_on_the_generate_body_picks_the_letter(monkeypatch, audience):
    """`audience` already rides every generate for the proposal. The letter reads it from that
    same field rather than adding a second one that could disagree with it.

    Asserted at the seam, with the REAL writer still doing the work, because Direct/Epoxy.docx and
    GC/Epoxy.docx are byte-identical today (the source PDF has no GC copy — see the CoverLetter
    README). Comparing the produced documents would therefore pass with the audience hard-wired to
    None, and go on passing right up until the copy pass diverges them and a GC customer gets the
    owner's letter.

    Read out of the ONE .docx now, which changes what the second assertion can say: the merged
    document always contains the job name, because the proposal prints it. So the check runs on
    the LETTER's half — see `_halves`."""
    seen = {}
    real = clw.fill_cover_letter

    def spy(**kw):
        seen["audience"] = kw.get("audience")
        seen["path"] = clw.pick_template(kw["work_type"], kw.get("audience"))
        return real(**kw)

    monkeypatch.setattr(main.cover_letter_writer, "fill_cover_letter", spy)
    out = _generate(audience=audience, cover_letter_enabled=True)
    assert seen["audience"] == audience
    assert seen["path"].parent.name == audience
    letter_half, _proposal_half = _halves(client.get(out["docx_download_url"]).content)
    assert "Kyle Loseke" in letter_half
    assert ("Cover Letter QA" in letter_half) is _NAMES_THE_JOB[audience], (
        "the %s letter %s the job name, against _NAMES_THE_JOB" %
        (audience, "names" if "Cover Letter QA" in letter_half else "does not name"))


def test_the_letter_and_the_proposal_agree_on_the_job():
    """Built from the same `values` dict, after the same alias/backfill pass. Two halves of one
    document that disagree about the job is what a second values path would produce — and it is
    one document now, so the disagreement would be consecutive pages contradicting each other,
    which is worse to read and no easier to notice.

    The comparand is not the job name, and the reason is worth writing down because the obvious
    substitutes are both wrong. Since the title line came off (2026-09-04) a DIRECT letter names
    the job nowhere, so `{{job_name}}` cannot be checked against the letter's half; and swapping
    the whole test to GC — whose letter DOES still say "this {{job_name}} project" — only moves
    the hole, because the GC proposal template carries its job name inside the page artwork and no
    text assertion can see it. So the check runs on two values both halves really print from the
    same dict: the system name and the estimator. A second values path would still be caught,
    which is the whole point of the test.
    """
    out = _generate(cover_letter_enabled=True)
    letter_half, proposal_half = _halves(client.get(out["docx_download_url"]).content)
    for shared in ("Treadwell MACRO Flake", "Kyle Loseke"):
        assert shared in letter_half, "%r is missing from the letter's half" % shared
        assert shared in proposal_half, "%r is missing from the proposal's half" % shared
    # And the job name still round-trips into the proposal, which is the only half of the pair
    # that prints it on a Direct bid.
    assert "Cover Letter QA" in proposal_half
    assert "Cover Letter QA" not in letter_half, (
        "Will's Direct copy has started naming the job — update _NAMES_THE_JOB, which the "
        "audience test above reads, rather than only this line")


# ── (b4) no letter exists for this bid, so none is invented ─────────────────
# `pick_template` resolves an unmapped work type to (epoxy, Direct) and always has: the document
# editor needed something to render, and the wrong letter on screen was better than an empty tab.
# That stopped being the right answer when the letter became signed paperwork. A sealer or budget
# bid has no letter of its own, and the epoxy one would open a GC sealer contract in the owner's
# voice, name Treadwell Epoxy as the system, and offer epoxy-only adders — to a customer, on
# page 1, above a price for different work.
#
# So `/api/generate` refuses by name (400) when `has_template` is False. Refusing is right and
# silently substituting is not, because the estimator ASKED for a letter: sending the wrong one
# and sending none are both worse than being told which work types have one.
@pytest.mark.parametrize("work_type", ["sealer", "budget"])
def test_a_work_type_with_no_letter_is_refused_by_name(monkeypatch, work_type):
    """The two work types the picker has no letter for. Refused with a message the UI can show as
    it stands — it names the work type and it names the way out — because a 400 whose body says
    "bad request" leaves an estimator with a button that does nothing.

    A SPY ON THE WRITER IS THE REAL ASSERTION. A 400 alone would also be satisfied by a route that
    built the epoxy letter, merged it, and then refused for some unrelated reason; what must be
    true is that no letter was filled at all. Asserted with the real `fill_cover_letter` replaced
    by something that fails the test if it is reached."""
    called = []
    monkeypatch.setattr(main.cover_letter_writer, "fill_cover_letter",
                        lambda **kw: called.append(kw) or b"")
    r = client.post("/api/generate", json=dict(BASE, work_type=work_type,
                                               cover_letter_enabled=True))
    assert r.status_code == 400, (
        "a %s bid with the cover letter ticked was not refused (%s). If it generated, the "
        "customer's page 1 is the EPOXY letter: wrong system, wrong adders, over a price for "
        "different work." % (work_type, r.status_code))
    detail = r.json()["detail"]
    assert work_type in detail, (
        "the refusal does not name the work type, so the estimator cannot tell which bids have a "
        "letter: %r" % detail)
    assert "Cover letter" in detail or "cover letter" in detail.lower(), detail
    assert "Untick" in detail or "untick" in detail, (
        "the refusal does not say how to proceed: %r" % detail)
    assert called == [], (
        "the fallback letter was built before the refusal — %d fill(s). `pick_template` resolves "
        "an unmapped work type to Direct/Epoxy, so this is the wrong document being produced, "
        "not merely wasted work." % len(called))


@pytest.mark.parametrize("work_type", ["sealer", "budget"])
def test_the_same_bid_still_generates_without_a_letter(work_type):
    """THE OTHER HALF, and without it the test above is satisfied by a route that refuses every
    sealer bid outright. The refusal is scoped to the letter: unticking the box is a real way out,
    which is what the message tells the estimator to do, so it has to work."""
    r = client.post("/api/generate", json=dict(BASE, work_type=work_type,
                                               cover_letter_enabled=False))
    assert r.status_code == 200, (
        "a %s bid cannot be generated at all now, so the refusal above tells the estimator to do "
        "something that does not help: %s" % (work_type, r.text[:200]))
    assert r.json()["docx_download_url"]


def test_the_work_types_that_do_have_a_letter_are_not_refused():
    """The counterexample for the refusal: a guard keyed on the wrong thing — a truthiness slip,
    an inverted `not` — would refuse everything, and both tests above would still pass. Every
    mapped variant is asserted, so the gate cannot be a blanket."""
    for wt, aud in VARIANTS:
        assert clw.has_template(wt, aud) is True, (wt, aud)
    r = client.post("/api/generate", json=dict(BASE, cover_letter_enabled=True))
    assert r.status_code == 200, (
        "an epoxy/Direct bid — which HAS a letter — was refused: %s" % r.text[:200])


# ── (b5) the signature's contact line ────────────────────────────────────────
# `{{estimator_contact_line}}` replaced the literal "[ESTIMATOR EMAIL]" that all seven templates
# printed at the customer until 2026-09-09. It was the one placeholder that needed no copy
# decision — the tool already knew who was signing — and it became urgent the moment the letter
# stopped being a document nobody rendered and became page 1 of the proposal .docx.
#
# THE WHOLE LINE IS ONE TOKEN, which is the design worth pinning: a template that said
# "{{estimator_email}} | wetreadwell.com" would show a customer " | wetreadwell.com" whenever the
# address was unresolvable, and a dangling pipe in a signature reads as a broken document.
def _signature_block(docx_bytes):
    """`[name line, contact line, company line]` from a letter or a merged proposal."""
    lines = [p.text.strip() for p in
             pw._iter_all_paragraphs(docx.Document(io.BytesIO(docx_bytes))) if p.text.strip()]
    i = next((i for i, t in enumerate(lines) if "| Estimator" in t), None)
    assert i is not None, (
        "no '<name> | Estimator' line in this document, so the signature cannot be located; "
        "the letter's closing block has been reworded and this helper needs re-deriving")
    return lines[i:i + 3]


@pytest.mark.parametrize("key", VARIANTS)
def test_every_letter_signs_with_a_resolved_contact_line(key):
    """No template may still print the literal, and none may print the raw token either. Per
    variant, because the placeholder was in all seven and a fix applied to six is a customer
    reading "[ESTIMATOR EMAIL]" on the seventh."""
    text = _rendered(clw.fill_cover_letter(
        work_type=key[0], audience=key[1],
        values=dict(FULL_VALUES, estimator_email="kyle@wetreadwell.com")))
    assert "[ESTIMATOR EMAIL]" not in text, (
        "%s/%s still prints the literal placeholder at the customer" % (key[0], key[1]))
    assert "{{estimator_contact_line}}" not in text, (
        "%s/%s prints the raw token — the value never reached the writer" % (key[0], key[1]))
    assert "kyle@wetreadwell.com | wetreadwell.com" in [
        ln.strip() for ln in text.splitlines()], (
        "%s/%s does not sign with the resolved contact line" % (key[0], key[1]))


def test_no_address_prints_the_site_alone_and_never_a_dangling_pipe():
    """THE REASON THE WHOLE LINE IS ONE TOKEN. With the separator baked into the template, an
    unresolvable address leaves a customer reading " | wetreadwell.com" under the estimator's
    name. Three ways of having no address are asserted — absent, empty, whitespace — because the
    writer's guard is a `_blank` check and "  " is the shape that slips past a truthiness test.

    The site alone is a true, complete line, which is why it is the fallback rather than nothing:
    a signature block with a hole in it reads as a document that failed to build."""
    for label, extra in (("absent", {}),
                         ("empty", {"estimator_email": ""}),
                         ("whitespace", {"estimator_email": "   "})):
        values = {k: v for k, v in FULL_VALUES.items() if k != "estimator_email"}
        values.update(extra)
        block = _signature_block(clw.fill_cover_letter(
            work_type="epoxy", audience="Direct", values=values))
        assert block[1] == "wetreadwell.com", (
            "with the address %s the contact line is %r — a dangling separator, or a hole"
            % (label, block[1]))
        assert "|" not in block[1], (
            "the separator survived without a value to separate (%s): %r" % (label, block[1]))
    # The positive control: with an address, the separator IS there. Without this the assertions
    # above would pass against a writer that had dropped the email half entirely.
    with_email = _signature_block(clw.fill_cover_letter(
        work_type="epoxy", audience="Direct",
        values=dict(FULL_VALUES, estimator_email="kyle@wetreadwell.com")))
    assert with_email[1] == "kyle@wetreadwell.com | wetreadwell.com", with_email[1]


def test_a_payload_frozen_before_the_token_existed_prints_no_raw_token():
    """Every draft sent between the cover letter shipping and 2026-09-09 has a `proposal_payload`
    with no `estimator_email` and no `estimator_contact_line` in it, and those payloads are
    replayed months later by a customer opening a portal link. The token must resolve to something
    true, not stand there in braces on page 1 of a contract.

    `estimator_name` is asserted alongside it for the same reason and by the same route: it is
    forced to EXIST rather than derived, because inventing a signatory for a customer's contract
    is worse than a short line — but a raw `{{estimator_name}}` is worse than both."""
    legacy = {k: v for k, v in FULL_VALUES.items()
              if k not in ("estimator_email", "estimator_name")}
    text = _rendered(clw.fill_cover_letter(work_type="epoxy", audience="Direct", values=legacy))
    for token in ("{{estimator_contact_line}}", "{{estimator_name}}", "{{estimator_email}}"):
        assert token not in text, (
            "a payload frozen before %s existed prints it raw on the customer's page 1" % token)
    # AN EXACT LINE, NOT A SUBSTRING, and CodeQL is why but the test is better for it:
    # `"wetreadwell.com" in text` also passes for "| wetreadwell.com", which is precisely the
    # dangling-separator bug `_ensure_cover_letter_values` builds the whole line to avoid. The
    # claim is that the line IS the site and nothing else.
    lines = [ln.strip() for ln in text.splitlines()]
    assert "wetreadwell.com" in lines, (
        "the fallback contact line is not the site on its own -- a payload with no "
        "estimator_email should print it with no separator. The signature block "
        "ended: %r" % lines[-4:])


def test_the_sent_document_and_the_customers_replay_sign_identically(monkeypatch):
    """THE PROPERTY THE TOKEN'S OWN COMMENT CLAIMS, executed end to end on both paths.

    /api/admin/proposal-pdf is service-token gated and sits in `_AUTH_PUBLIC_PATHS`, so it carries
    no bearer: `verify_token_claims` raises, `_user_email` returns None, and BOTH halves of
    main.py's estimator backfill no-op. A server-only resolution would therefore sign the document
    a customer re-opens differently from the one they were sent — the estimator's address on the
    email that went out, and a bare "wetreadwell.com" on the copy behind the link. The frontend
    puts `estimator_email` into `tokenValues`, which rides `proposal_payload.values`, so the
    frozen payload carries it and the replay resolves the same line from the same data.

    Asserted on the SIGNATURE BLOCK rather than on the whole document, because the two do
    legitimately differ elsewhere (the proposal_date is stamped per render)."""
    payload = dict(BASE, cover_letter_enabled=True)
    payload["values"] = dict(BASE["values"], estimator_email="kyle@wetreadwell.com",
                             estimator_name="Kyle Loseke")

    # 1. What the estimator generated and sent, through the authenticated route.
    sent = client.post("/api/generate", json=payload)
    assert sent.status_code == 200, sent.text
    sent_block = _signature_block(client.get(sent.json()["docx_download_url"]).content)
    assert sent_block[1] == "kyle@wetreadwell.com | wetreadwell.com", sent_block

    # 2. What the customer's on-demand render produces from the frozen copy of that same payload,
    #    with no bearer at all. LibreOffice is stubbed; the bytes it is handed are the real
    #    merged document.
    _pinned(monkeypatch, payload)
    rendered_from = {}

    def fake_pdf(blob):
        rendered_from["bytes"] = blob
        return b"%PDF-1.4"

    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", fake_pdf)
    r = client.get("/api/admin/proposal-pdf?draft_id=d1",
                   headers={"X-Service-Token": "svc-test"})
    assert r.status_code == 200, r.text
    replay_block = _signature_block(rendered_from["bytes"])

    assert replay_block == sent_block, (
        "the customer's re-opened document signs differently from the one they were sent.\n"
        "sent:   %r\nreplay: %r" % (sent_block, replay_block))


def test_the_replay_really_has_no_signed_in_user_to_fall_back_on(monkeypatch):
    """The counterexample for the test above, and it is the one that decides whether that test
    means anything. If the replay route could resolve the estimator from a session, the two paths
    would agree for a reason that has nothing to do with the frozen payload, and the test would go
    on passing after somebody removed `estimator_email` from `tokenValues`.

    So: strip the address OUT of the frozen payload and assert the replay signs with the site
    alone. That is the failure the frontend's copy of this field prevents — proved, rather than
    argued from the route's auth configuration."""
    payload = dict(BASE, cover_letter_enabled=True)
    payload["values"] = {k: v for k, v in BASE["values"].items() if k != "estimator_email"}
    payload["values"]["estimator_name"] = "Kyle Loseke"
    _pinned(monkeypatch, payload)
    rendered_from = {}

    def fake_pdf(blob):
        rendered_from["bytes"] = blob
        return b"%PDF-1.4"

    monkeypatch.setattr(main.pdf_writer, "docx_to_pdf", fake_pdf)
    r = client.get("/api/admin/proposal-pdf?draft_id=d1",
                   headers={"X-Service-Token": "svc-test"})
    assert r.status_code == 200, r.text
    block = _signature_block(rendered_from["bytes"])
    assert block[1] == "wetreadwell.com", (
        "the replay resolved an estimator address from somewhere other than the frozen payload, "
        "so test_the_sent_document_and_the_customers_replay_sign_identically is not testing what "
        "it says it is: %r" % (block,))


# ── (b3) the unfinished-wording scan ────────────────────────────────────────
# The copy in these seven templates is a DRAFT (templates/CoverLetter/README.md) and every one of
# them still carries bracketed instructions written TO the estimator — "[SHEEN - pick one: ...]".
# They reached nobody while the letter was a separate document the customer portal never rendered.
# They are page 1 of a customer's proposal now, and the document editor the README named as the
# way to delete them is gone, so /api/generate REPORTS them and the Done page prints them before
# anything is sent.
#
# WHICH DOCUMENT IS SCANNED IS THE WHOLE DESIGN, and it was got wrong once. Scanning the FILLED
# letter reported the estimator's own free text: construction estimators write bracketed uppercase
# shorthand as a matter of course, and "Amazon DFW7 [PHASE 2]" is a correct job name, not
# unfinished template copy. The warning told them to untick a page they wanted, about words they
# had typed on purpose. `template_placeholders` reads the TEMPLATE instead — no estimator text can
# reach it, and a placeholder added by a future `prepare_cover_letter_templates.py` run is still
# found with no list of known prefixes to maintain.
#
# `_expected_placeholders` below is DERIVED, not transcribed, and derived through a different
# property than the function under test uses. The generator marks every placeholder ITALIC (`_ph`
# is `_seg(text, italic=True)` and nothing else in that file sets italic); the scanner matches
# brackets. So the two agree only if the shipped .docx really carries the instructions the
# generator declares, and a hardcoded count would have gone stale the moment Hanz edits the copy.

# Estimator free text, of the kind that made the filled-letter scan cry wolf. Real shapes: a
# phase suffix on an Amazon job name, a schedule not yet fixed by the GC, an area that points at
# a drawing. Every one matches the scanner's own pattern, which is exactly why they are the
# regression guard: a scanner reading the filled letter reports all of them.
#
# KEYED BY AUDIENCE, because the two letters print different fields and a fixture that never
# reaches the page proves nothing. Direct names no job at all (Will's copy, see _NAMES_THE_JOB)
# and takes `work_areas` through {{cover_area_line}}; GC opens "this {{job_name}} project" and has
# a {{schedule_notes}} token Direct does not. `system_name` is the one both print, so it appears
# in both. Established by rendering them, not by reading the templates — and asserted per field in
# the test below, so a copy change that drops one goes red rather than quietly weakening this.
_ESTIMATOR_BRACKETS = {
    "Direct": {
        "work_areas": "Bays 1-4 [SEE PLAN A1.1]",
        "system_name": "Treadwell MACRO Flake [ALT 1]",
    },
    "GC": {
        "job_name": "Amazon DFW7 [PHASE 2]",
        "project_name": "Amazon DFW7 [PHASE 2]",
        "schedule_notes": "[TBD] pending GC schedule",
        "system_name": "Treadwell MACRO Flake [ALT 1]",
    },
}


def _expected_placeholders(key):
    """Every bracketed instruction the SHIPPED template for `key` carries, derived from the
    ITALIC runs rather than from the scanner's own rule.

    Two independent representations of one fact: `prepare_cover_letter_templates._ph` writes
    placeholders italic ("so it is impossible to miss on the page") and nothing else in that
    generator sets italic, while `cover_letter_writer.template_placeholders` finds them by their
    brackets. Agreement means the .docx on disk really contains the instructions the generator
    declares. Bracket-splitting is done here too, because two adjacent `_ph` segments land in one
    italic run and the scanner is right to report them as the two separate instructions they are.
    """
    d = docx.Document(str(clw.pick_template(*key)))
    seen, out = set(), []
    for para in pw._iter_all_paragraphs(d):
        for run in para.runs:
            if not run.italic:
                continue
            for piece in re.findall(r"\[[^\[\]]*\]", run.text or ""):
                text = " ".join(piece.split())
                if text not in seen:
                    seen.add(text)
                    out.append(text)
    return out


@pytest.mark.parametrize("key", VARIANTS)
def test_every_instruction_the_template_carries_is_reported(key):
    """Per variant, and in template order, because the Done page prints this list verbatim and an
    estimator reading it is comparing it against the page in front of them.

    Not vacuous in either direction. The expected set is derived from the italic runs (see
    `_expected_placeholders`), so a scanner that found nothing fails on the missing entries and a
    scanner that started matching ordinary prose fails on the extra ones. And the assertion below
    that the set is non-empty is what stops the whole thing passing on a template set that had
    quietly lost its instructions — which would be good news, but news this test must not deliver
    silently."""
    expected = _expected_placeholders(key)
    assert expected, (
        "%s/%s carries no italic bracketed instruction at all. If the copy pass has landed, that "
        "is the good outcome — but it makes this test vacuous, so delete it deliberately rather "
        "than letting it pass on nothing." % (key[0], key[1]))
    got = clw.template_placeholders(*key)
    assert got == expected, (
        "the scan of %s/%s does not match the instructions the template actually carries.\n"
        "missing: %r\nextra:   %r" % (key[0], key[1],
                                      [x for x in expected if x not in got],
                                      [x for x in got if x not in expected]))


def test_the_seven_variants_do_not_all_carry_the_same_list():
    """The counterexample for the parametrized test above. Seven variants each compared against
    their own derived set would pass just as well if the scanner ignored its argument and returned
    one fixed list — as it would if `pick_template`'s epoxy fallback were reached for every call.
    A GC bid carries thickness and cove-height instructions a Direct bid does not, so the lists
    genuinely differ, and this fails with a note if they ever stop differing."""
    lists = {key: tuple(clw.template_placeholders(*key)) for key in VARIANTS}
    assert len(set(lists.values())) > 1, (
        "every variant now reports an identical list, so the parametrized test above cannot tell "
        "a per-variant scan from a constant: %r" % (lists,))
    direct, gc = tuple(lists[("epoxy", "Direct")]), tuple(lists[("epoxy", "GC")])
    assert set(direct) < set(gc), (
        "the GC epoxy letter used to carry strictly more instructions than the Direct one "
        "(thickness, cove height, schedule); that relationship has changed, so re-derive what "
        "this test is protecting. Direct=%r GC=%r" % (direct, gc))


@pytest.mark.parametrize("audience", sorted(_ESTIMATOR_BRACKETS))
def test_the_estimators_own_bracketed_text_is_not_called_unfinished(audience):
    """THE REGRESSION GUARD, and the defect it guards is a warning that lied to the person it was
    written for. Estimators type bracketed uppercase shorthand constantly — "[TBD] pending GC
    schedule", "Amazon DFW7 [PHASE 2]", "Bays 1-4 [SEE PLAN A1.1]", "[NIC]", "[ALT 1]" — and the
    first version of this scan read the FILLED letter, so it reported all of it as unfinished
    template copy and offered to fix it by unticking a page the estimator wanted. It told them
    their own correct job name was a mistake.

    Both halves are asserted, and both are needed. That the strings reach the DOCUMENT is what
    makes the second half meaningful: without it, a writer that silently dropped `work_areas`
    would pass by never printing the text at all rather than by classifying it correctly. Writing
    it caught exactly that — the first draft of this test put the job name on a DIRECT letter,
    which names no job, so half two was asserting the absence of a string that was never there.

    It was also a latent trap rather than only a present annoyance. While every template still
    ships real instructions the banner is up regardless, so the false positives were invisible —
    they would have become the SOLE trigger the moment the copy pass landed and somebody started
    trusting the warning."""
    fields = _ESTIMATOR_BRACKETS[audience]
    values = dict(FULL_VALUES, **fields)
    text = _rendered(clw.fill_cover_letter(work_type="epoxy", audience=audience, values=values))
    # Half one: the estimator's words are really on the page.
    for field, phrase in sorted(fields.items()):
        assert phrase in text, (
            "%r (%s) never reached the %s letter, so the second half of this test would pass for "
            "the wrong reason. Move the fixture to the audience whose template prints it."
            % (phrase, field, audience))
    # Half two: none of them is reported as unfinished template copy.
    reported = clw.template_placeholders("epoxy", audience)
    joined = "\n".join(reported)
    for field, phrase in sorted(fields.items()):
        bracketed = re.findall(r"\[[^\[\]]*\]", phrase)
        assert bracketed, "the %s fixture has no brackets, so it tests nothing" % field
        for piece in bracketed:
            assert piece not in joined, (
                "%r — the estimator's own %s — is being reported as unfinished template copy. "
                "The scan is reading the filled letter again; it must read the template. "
                "Reported: %r" % (piece, field, reported))


@pytest.mark.parametrize("audience", sorted(_ESTIMATOR_BRACKETS))
def test_the_estimator_fixtures_would_be_caught_by_a_filled_letter_scan(audience):
    """The counterexample for the guard above, and it needs one badly: a handful of phrases absent
    from a list would be absent whether the scanner was right or wrong, and the test would go on
    passing after somebody pointed it back at the filled document.

    So this asserts the fixtures are genuinely dangerous — that the scanner's OWN pattern matches
    every one of them in the FILLED letter, which is what the old implementation scanned. If a
    future pattern legitimately stops matching "[TBD]" and friends, this fails and says so, at
    which point the guard above has become untested rather than unneeded and the fixtures need
    replacing with shapes the new pattern does match."""
    fields = _ESTIMATOR_BRACKETS[audience]
    values = dict(FULL_VALUES, **fields)
    filled = docx.Document(io.BytesIO(clw.fill_cover_letter(
        work_type="epoxy", audience=audience, values=values)))
    would_report = set()
    for para in pw._iter_all_paragraphs(filled):
        for hit in clw._PLACEHOLDER_RE.findall(para.text or ""):
            would_report.add(" ".join(hit.split()))
    for field, phrase in sorted(fields.items()):
        for piece in re.findall(r"\[[^\[\]]*\]", phrase):
            assert piece in would_report, (
                "%r (%s) is no longer matched by _PLACEHOLDER_RE, so it cannot demonstrate the "
                "false positive and test_the_estimators_own_bracketed_text_is_not_called_"
                "unfinished has become vacuous. Matched: %r" % (piece, field,
                                                                sorted(would_report)))
    # And the two strategies really do disagree on this document, which is the whole point.
    assert would_report - set(clw.template_placeholders("epoxy", audience)), (
        "scanning the filled %s letter finds nothing the template scan does not, so the two "
        "strategies are indistinguishable here and this section proves nothing" % audience)


def test_the_pattern_skips_ordinary_prose_in_brackets():
    """The two bounds `_PLACEHOLDER_RE` states in its own comment, pinned because nothing else
    can reach them: every bracketed span in all seven shipped templates is uppercase-initial and
    long, so widening the pattern changes no current output at all and no template-level test
    could tell. It would matter the first time a copy pass added a prose aside — "[sic]", "[see
    plan A1.1]" — which would then be reported to an estimator as unfinished wording.

    UPPERCASE FIRST LETTER, and at least three characters inside. Both directions asserted with a
    positive control from the real set, so a pattern that stopped matching anything at all fails
    here rather than looking strict."""
    for prose in ("[sic]", "[see plan A1.1]", "[note - lowercase instruction]", "[2 phases]",
                  "[]", "[OK]", "[AB]"):
        assert clw._PLACEHOLDER_RE.findall(prose) == [], (
            "%r reads as an unfinished instruction, so a prose aside or a two-letter bracket in "
            "a future copy pass would be reported to the estimator as one" % prose)
    for instruction in ("[TBD]", "[NIC]", "[ALT 1]", "[PHASE 2]",
                        "[SHEEN - pick one: Level 2 (400 grit) / Level 3 (800 grit).]"):
        assert clw._PLACEHOLDER_RE.findall(instruction) == [instruction], (
            "%r is no longer matched; the pattern has become too strict to find the real "
            "instructions" % instruction)


def test_the_scan_survives_a_template_it_cannot_open():
    """A warning must never be the thing that fails a generate. `template_placeholders` catches
    everything and returns an empty list, because the estimator's document is already built by
    the time it runs and refusing to hand it over because the ADVISORY scan tripped would be the
    tail wagging the dog. The log line is what carries the fault."""
    with mock.patch.object(clw.docx, "Document", side_effect=RuntimeError("package is corrupt")):
        assert clw.template_placeholders("epoxy", "Direct") == [], (
            "an unreadable template makes the placeholder scan raise, which fails a generate "
            "whose documents are already complete")


def test_an_unmapped_work_type_is_never_scanned_for_a_letter_it_cannot_have():
    """`template_placeholders` resolves through `pick_template`, which falls back to Direct/Epoxy
    for an unmapped work type — so asked about a sealer bid it would return the EPOXY letter's
    instructions, describing a page that is never built. That is not a defect in the scanner: as
    of 2026-09-09 `_generate` refuses a sealer or budget bid with the letter ticked before it gets
    anywhere near this function (`has_template`, 400).

    Pinned here so the two stay in step. If the refusal is ever relaxed, this is the test that
    says the scan needs its own `has_template` guard rather than quietly reporting an epoxy
    letter's unfinished wording on a sealer proposal."""
    assert clw.has_template("sealer", "GC") is False
    assert clw.has_template("budget", "Direct") is False
    # The fallback really does happen, which is why the route's refusal is load-bearing.
    assert (clw.template_placeholders("sealer", "GC")
            == clw.template_placeholders("epoxy", "Direct")), (
        "pick_template's epoxy fallback has changed shape; re-derive whether the placeholder "
        "scan still needs the route's has_template refusal in front of it")


# ── (b6) the placeholder endpoint, and the log line behind it ───────────────
# `GET /api/cover-letter/placeholders?work_type=&audience=` -> `{work_type, audience, has_letter,
# placeholders}`. The Done page asks this before anything is sent, with the variant out of the
# `proposal_payload` it is about to pin.
#
# WHY AN ENDPOINT AND NOT A FIELD ON THE GENERATE RESPONSE. It was a field for one day and broke
# five ways, every one the same sentence: the warning's input was not the input the document is
# built from. `generate_result` is persisted on the draft, never cleared, and Continue does not
# regenerate — so the page's copy could predate the estimator ticking the box, could describe the
# epoxy/Direct letter (1 instruction) while a GC letter (4) was about to be pinned, or could
# arrive in a shape indistinguishable from "scanned and clean". Four of the five UNDER-reported,
# which is the direction that reaches a customer. The list is a pure function of
# `(work_type, audience)` read off the TEMPLATE — no estimator input is in it at all — so asking
# for it is strictly better than remembering it, and there is nothing left to go stale.
#
# WHAT WAS DELETED WITH THE FIELD, rather than ported: two tests that asserted the WIRE SHAPE of
# `GenerateOut.cover_letter_placeholders` — that a letter-off generate answered `None` and a clean
# scan answered `[]`. Those pinned a null/empty/array trichotomy that the Done page had to
# disambiguate, and the whole point of the redesign is that it no longer has to. The claims have
# no subject any more; they are recorded here rather than left as tests of a field that is gone.
def test_the_placeholder_endpoint_answers_for_every_mapped_variant():
    """One request per variant, each answering ITS OWN template's instructions in template order.

    Expected is DERIVED, through a different property than the endpoint uses: the generator marks
    every placeholder ITALIC (`prepare_cover_letter_templates._ph` is `_seg(text, italic=True)`,
    and nothing else in that file sets italic) while the scan finds them by their brackets. See
    `_expected_placeholders`. A hardcoded count would go stale the moment Hanz edits the copy, and
    a self-comparison against `template_placeholders` would prove only that the route calls it."""
    for wt, aud in VARIANTS:
        r = client.get("/api/cover-letter/placeholders?work_type=%s&audience=%s"
                       % (wt, aud or ""))
        assert r.status_code == 200, (wt, aud, r.text)
        body = r.json()
        assert body["has_letter"] is True, (
            "%s/%s has a letter on disk and the endpoint says it does not, so the Done page "
            "cannot warn about a page it is going to send" % (wt, aud))
        expected = _expected_placeholders((wt, aud))
        assert expected, (
            "%s/%s carries no italic bracketed instruction at all. If the copy pass has landed "
            "that is the good outcome, but it makes this comparison vacuous for that variant — "
            "delete it deliberately rather than letting it pass on nothing." % (wt, aud))
        assert body["placeholders"] == expected, (
            "the endpoint's answer for %s/%s does not match the instructions the template "
            "actually carries.\nmissing: %r\nextra:   %r"
            % (wt, aud, [x for x in expected if x not in body["placeholders"]],
               [x for x in body["placeholders"] if x not in expected]))


def test_two_variants_that_differ_really_answer_differently():
    """THE GUARD FOR THE DEFECT THAT MADE THIS AN ENDPOINT. The cached list showed an estimator 1
    instruction while the customer received 4, because the list was for epoxy/Direct and the
    letter being pinned was epoxy/GC. If this endpoint answered the same thing for every variant —
    a hardcoded list, an ignored argument, `pick_template`'s epoxy fallback reached for every
    call — then the frontend asking with the right variant would buy nothing, and the test above
    would pass per-variant while proving nothing about the axis that broke.

    So: the answers must genuinely differ, and the specific relationship is pinned. If it ever
    stops holding, this fails with a note rather than going quietly vacuous."""
    answers = {}
    for wt, aud in VARIANTS:
        r = client.get("/api/cover-letter/placeholders?work_type=%s&audience=%s" % (wt, aud or ""))
        answers[(wt, aud)] = tuple(r.json()["placeholders"])
    assert len(set(answers.values())) > 1, (
        "every variant answers an identical list, so asking with the right variant cannot "
        "matter and the per-variant test above cannot tell a real scan from a constant: %r"
        % (answers,))
    direct, gc = answers[("epoxy", "Direct")], answers[("epoxy", "GC")]
    assert set(direct) < set(gc), (
        "the GC epoxy letter used to carry strictly more instructions than the Direct one "
        "(thickness, cove height, schedule) — that is the pair whose 1-versus-4 mismatch reached "
        "a customer. The relationship has changed; re-derive what this is protecting. "
        "Direct=%r GC=%r" % (direct, gc))
    assert len(gc) > len(direct), (len(direct), len(gc))


@pytest.mark.parametrize("work_type", ["sealer", "budget"])
def test_a_variant_with_no_letter_answers_false_and_an_empty_list(work_type):
    """Never a 404 — "this bid has no cover letter" is a true answer, not an error, and a screen
    that has to distinguish 404-because-unmapped from 404-because-the-route-moved will get it
    wrong.

    AND THE LIST IS EMPTY, NOT THE FALLBACK'S. `pick_template` resolves an unmapped work type to
    (epoxy, Direct), so a naive implementation would answer a sealer bid with the EPOXY letter's
    instructions: a list of things wrong with a page that is never going to be built, since
    /api/generate refuses that combination outright (400). The two fields would then contradict
    each other — `has_letter: false` beside a list of what is unfinished on it — and whichever the
    frontend believed, it would be describing a document that does not exist."""
    r = client.get("/api/cover-letter/placeholders?work_type=%s&audience=Direct" % work_type)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_letter"] is False, (
        "%s has no letter of its own and the endpoint claims it does; /api/generate refuses this "
        "combination, so the two halves of the product now disagree" % work_type)
    assert body["placeholders"] == [], (
        "%s answered %r — that is the epoxy fallback's list, describing a page that will never "
        "be built. Compare: epoxy/Direct answers %r."
        % (work_type, body["placeholders"], _expected_placeholders(("epoxy", "Direct"))))
    # The counterexample: the fallback really would have produced something, so the empty list is
    # a decision and not an accident of there being nothing to find.
    assert clw.template_placeholders(work_type, "Direct"), (
        "pick_template's epoxy fallback no longer yields any instruction for an unmapped work "
        "type, so the assertion above cannot fail and this guard has become vacuous")


def test_the_endpoint_takes_no_draft_and_no_estimator_input():
    """It is a pure function of the variant, and that is the property the whole redesign rests on:
    no estimator text can reach it, so nothing it reports can be the estimator's own words read
    back at them as an error. (That was its own defect once — "Amazon DFW7 [PHASE 2]" reported as
    unfinished template copy — fixed by scanning the template instead of the filled letter.)

    Asserted on the SIGNATURE, which is what makes it a claim rather than an observation: two
    query parameters, both strings, and no `Request`, no body model, no draft id. A route that
    grew a draft id would be able to reach a draft's values, and a route that grew a `Request`
    could reach headers and cookies — both of which put a caller's data into an answer that is
    supposed to depend on nothing but the variant."""
    import inspect
    params = inspect.signature(main.api_cover_letter_placeholders).parameters
    assert set(params) == {"work_type", "audience"}, (
        "the placeholder endpoint grew a parameter: %r. It answers a question about a TEMPLATE; "
        "anything caller-specific in here is a way for an estimator's own words to come back as "
        "an error." % sorted(params))
    for name, p in params.items():
        # `str` or the string "str": main.py has `from __future__ import annotations`, so
        # annotations arrive unevaluated. Both spellings mean the same declaration, and a test
        # that insisted on one would break on an unrelated import change.
        assert p.annotation in (str, "str"), (
            "%s is annotated %r — anything but a plain string is a richer type than a query "
            "parameter needs, and a model here is a body in disguise" % (name, p.annotation))
        assert p.default is not inspect.Parameter.empty, (
            "%s has no default, so the Done page's request must always send it" % name)
    route = next(r for r in main.app.routes
                 if getattr(r, "path", "") == "/api/cover-letter/placeholders")
    assert set(route.methods) == {"GET"}, (
        "the endpoint accepts %r — a POST twin is a second contract, and a body is exactly the "
        "thing this must not have" % (route.methods,))
    assert not route.dependant.body_params, route.dependant.body_params
    assert {p.name for p in route.dependant.query_params} == {"work_type", "audience"}
    # And it really is read-only: no draft is loaded, nothing is written.
    r = client.get("/api/cover-letter/placeholders")
    assert r.status_code == 200 and r.json()["work_type"] == "epoxy", r.text


def test_the_endpoint_echoes_the_variant_it_answered_about():
    """The Done page fires this while the estimator can still change things, and a stray earlier
    response arriving late is the browser's own version of the staleness this replaced. Echoing
    the variant is what lets a caller tell whose answer it is holding — worth pinning because a
    tidy-up that dropped the echo would take that ability away silently."""
    r = client.get("/api/cover-letter/placeholders?work_type=POLISH&audience=GC")
    body = r.json()
    assert body["work_type"] == "polish", (
        "the echo is not normalised, so a caller comparing it against its own lowercase "
        "work_type would read every answer as somebody else's: %r" % body["work_type"])
    assert body["audience"] == "GC", body["audience"]
    assert body["has_letter"] is True and body["placeholders"], body


def test_the_generate_log_still_records_what_went_out(caplog):
    """THE SCAN IS LOG-ONLY NOW, and its remaining job is the audit trail: a letter that went to a
    customer with draft instructions on it has to be answerable from container logs afterwards,
    because nothing is stored per send that would say so.

    KEPT FROM THE FIELD ERA, with its claim re-pointed. It used to assert that the scanner is not
    called on the letter-off path so nothing could leak onto the wire; the wire is gone, but the
    claim is not vacuous — it now says the log does not carry a warning about a letter that was
    never built, and DOES carry the instructions of the variant that actually was. A scan of the
    wrong variant would put the wrong list in the audit trail, which is worse than none: it would
    answer "what did we send" with somebody else's answer.

    The spy is still the load-bearing part. A route that scanned unconditionally and discarded the
    result would satisfy any assertion about the log while doing the work, and the next refactor
    keeps the scan and drops the discard."""
    calls = []
    # Held BEFORE the patch. `main.cover_letter_writer` IS the `clw` module object, so a spy that
    # reached for `clw.template_placeholders` by name would call ITSELF — an infinite recursion
    # that surfaces as a 500 from the route and reads like a product bug. (It did, once.)
    real = clw.template_placeholders

    def spy(work_type, audience=None):
        calls.append((work_type, audience))
        return real(work_type, audience)

    with mock.patch.object(main.cover_letter_writer, "template_placeholders", spy):
        with caplog.at_level("WARNING", logger="proposal_tool"):
            _generate()
            assert calls == [], (
                "the template was scanned for a bid with no cover letter: %r" % (calls,))
            assert not [r for r in caplog.records if "cover letter" in r.getMessage().lower()], (
                "a letter-off generate wrote a cover-letter warning to the log, so the audit "
                "trail claims a page 1 that was never built")
            caplog.clear()
            _generate(audience="GC", cover_letter_enabled=True)

    assert calls == [("epoxy", "GC")], (
        "the scan did not run exactly once for the variant actually being built: %r. A GC send "
        "logged against the Direct letter's instructions is an audit trail that lies." % (calls,))
    warned = [r.getMessage() for r in caplog.records
              if "placeholder" in r.getMessage().lower()]
    assert len(warned) == 1, (
        "expected exactly one placeholder warning for a letter-on generate, got %r" % (warned,))
    line = warned[0]
    # The GC letter's own instructions, which the Direct letter does not carry — so the log names
    # the variant by its content even though it does not print the variant itself.
    gc_only = [p for p in _expected_placeholders(("epoxy", "GC"))
               if p not in _expected_placeholders(("epoxy", "Direct"))]
    assert gc_only, "the two variants no longer differ; this assertion cannot fail"
    for phrase in gc_only:
        assert phrase in line, (
            "the log line does not carry the GC letter's own instruction %r, so it cannot be "
            "told from a Direct send afterwards. Line: %r" % (phrase, line))


# ── (b2) the label bullets: bold to the colon, normal after ──────────────────
# Hanz, 2026-09-04, looking at the Cover letter tab: "Only those words before and including the
# colon should be default bold. The other details should not be. So, material/system, area,
# schedule, options should be the only ones bold."
#
# The TEMPLATES always did that (`_add` writes `r.bold = bool(seg.get("bold"))`, so the detail
# carries an explicit `w:b val="0"`). An EDITED bullet did not: a plain-text override is one
# string, `_set_paragraph_text` keeps the paragraph's first run and drops the rest, and the first
# run is the bold label — so the estimator's whole sentence reached the customer's PDF in
# Cambria-Bold. `_split_label_overrides` re-splits it at the first colon.
#
# Everything here executes the real writer over the real templates for every variant. A source
# assertion could not tell the difference between these two states at all: the generator, the
# template and the override channel were each individually correct, and the document was wrong.

# The five labels these letters print. `Materials / System:` is the resinous row; `System:` is
# polish and gyp. Ordered longest-first so `startswith` cannot mistake one for another.
_BULLET_LABELS = ("Materials / System:", "Schedule:", "Options:", "System:", "Area:")


def _bullet_runs(d):
    """`{label: [(text, bold), ...]}` for every label bullet in a filled letter.

    Keyed on the label rather than on a block id because these assertions are about what the
    DOCUMENT says; the ids are checked by the override tests above.
    """
    out = {}
    for p in pw._iter_all_paragraphs(d):
        text = p.text.strip()
        for label in _BULLET_LABELS:
            if text.startswith(label):
                out[label] = [(r.text, r.bold) for r in p.runs if r.text]
                break
    return out


def _label_ids(key):
    """`{block id: label text}` — the template's own answer for which paragraphs are label
    bullets, read off the pristine file the override ids are resolved against."""
    return clw._label_paragraphs(docx.Document(str(clw.pick_template(*key))))


@pytest.mark.parametrize("key", VARIANTS)
def test_every_label_bullet_ships_bold_to_the_colon_and_normal_after(key):
    """The baseline, per variant: an UNEDITED letter already gets this right, and must keep
    getting it right. This is the state Hanz's screenshot was compared against — the editor was
    showing these lines fully bold while the .docx underneath was correct."""
    d = docx.Document(io.BytesIO(clw.fill_cover_letter(
        work_type=key[0], audience=key[1], values=FULL_VALUES)))
    rows = _bullet_runs(d)
    # Not vacuous: every variant has at least three of these bullets, and the count has to match
    # what the writer itself classified — a regex that stopped matching would otherwise pass here
    # by finding nothing.
    assert len(rows) >= 3, "found no label bullets in %s/%s: %r" % (key[0], key[1], rows)
    for label, runs in rows.items():
        assert runs[0][1] is True, "%s is not bold in %s/%s: %r" % (label, key[0], key[1], runs)
        assert runs[0][0].rstrip().endswith(":"), (
            "the bold run runs past the colon in %s/%s: %r" % (key[0], key[1], runs))
        assert all(b is False for _t, b in runs[1:]), (
            "detail after %s inherited the label's bold in %s/%s: %r"
            % (label, key[0], key[1], runs))


@pytest.mark.parametrize("key", VARIANTS)
def test_an_edited_label_bullet_keeps_its_bold_label_and_normal_detail(key):
    """THE ONE THAT WOULD HAVE CAUGHT IT — the round trip, for every variant.

    The estimator retypes a bullet in the document editor, which sends a plain string; the
    override is applied on generate. Before `_split_label_overrides` the rebuilt paragraph was a
    single run wearing the label's weight, and the customer's PDF rendered
    `Schedule: edited by the estimator` bold end to end (measured on Direct/Epoxy: one
    `Cambria-Bold` span across the whole line, where the unedited letter renders two).
    """
    labels = _label_ids(key)
    assert labels, "no label bullets classified in %s/%s" % (key[0], key[1])
    overrides = [{"id": bid, "text": label.strip() + " the estimator retyped this line."}
                 for bid, label in labels.items()]
    d = docx.Document(io.BytesIO(clw.fill_cover_letter(
        work_type=key[0], audience=key[1], values=FULL_VALUES,
        paragraph_overrides=overrides)))
    edited = [p for p in pw._iter_all_paragraphs(d)
              if "the estimator retyped this line." in p.text]
    assert len(edited) == len(labels), (
        "%d of %d edits reached the letter" % (len(edited), len(labels)))
    for p in edited:
        runs = [(r.text, r.bold) for r in p.runs if r.text]
        assert len(runs) == 2, "the edit was not split at the colon: %r" % (runs,)
        assert runs[0][1] is True and runs[0][0].rstrip().endswith(":"), runs
        assert runs[1][1] is False, "the estimator's detail came out bold: %r" % (runs,)


def test_the_estimators_own_formatting_outranks_the_split():
    """An override that carries `runs` is the estimator having pressed Bold themselves — PR #453
    is what made those buttons reach the letter. Their stated weight wins, exactly as
    `_user_bolded_runs` makes it win over the proposal's normalizer; re-splitting it would make
    the most-used button in the ribbon a no-op on these four rows."""
    labels = _label_ids(("epoxy", "Direct"))
    bid = next(i for i, lab in labels.items() if lab.strip() == "Schedule:")
    d = docx.Document(io.BytesIO(clw.fill_cover_letter(
        work_type="epoxy", audience="Direct", values=FULL_VALUES,
        paragraph_overrides=[{"id": bid, "runs": [
            {"text": "Schedule: ", "bold": False},
            {"text": "all of this is deliberately bold", "bold": True}]}])))
    runs = _bullet_runs(d)["Schedule:"]
    assert runs == [("Schedule: ", False), ("all of this is deliberately bold", True)], runs


def test_a_sentence_that_merely_ends_in_a_colon_is_not_a_label():
    """WHY THE RULE READS THE TEMPLATE'S RUNS AND NOT THE WORDS.

    Will's Direct copy opens `A few things to note:` — short, colon-terminated, no `.?!`, which is
    everything the proposal's text-driven `_normalize_work_label_formatting` looks for. Text
    heuristics would have bolded it. The template writes it as ONE run, so it is not a label
    bullet, and an edit of it stays as uniform as the line it replaced."""
    d0 = docx.Document(str(clw.pick_template("epoxy", "Direct")))
    intro = next(
        (idx for idx, _k, _pe, _ib, text, _t in pw.iter_editable_blocks(d0)
         if text.strip() == "A few things to note:"), None)
    assert intro is not None, "the Direct intro line moved — re-derive this test, don't delete it"
    assert intro not in clw._label_paragraphs(d0), "the intro was classified as a label bullet"
    d = docx.Document(io.BytesIO(clw.fill_cover_letter(
        work_type="epoxy", audience="Direct", values=FULL_VALUES,
        paragraph_overrides=[{"id": intro, "text": "A couple of things to note:"}])))
    p = next(p for p in pw._iter_all_paragraphs(d)
             if p.text.strip() == "A couple of things to note:")
    assert [r.bold for r in p.runs if r.text] == [False], (
        "the intro line picked up a label's bold: %r" % ([(r.text, r.bold) for r in p.runs],))


def test_a_group_heading_stays_bold_all_the_way_through():
    """Combo's `Epoxy / Resinous Flooring:` / `Polished Concrete:` headings are colon-terminated
    AND fully bold by design. They are single bold runs with no detail half, so they are not label
    bullets either — the split must not hand them a normal-weight tail."""
    d0 = docx.Document(str(clw.pick_template("combo", "Direct")))
    heads = {text.strip(): idx
             for idx, _k, _pe, _ib, text, _t in pw.iter_editable_blocks(d0)
             if text.strip() in ("Epoxy / Resinous Flooring:", "Polished Concrete:")}
    assert len(heads) == 2, heads
    labels = clw._label_paragraphs(d0)
    assert not [h for h in heads.values() if h in labels], "a heading was taken for a bullet"
    d = docx.Document(io.BytesIO(clw.fill_cover_letter(
        work_type="combo", audience="Direct", values=FULL_VALUES,
        paragraph_overrides=[{"id": i, "text": name.rstrip(":") + " Systems:"}
                             for name, i in heads.items()])))
    for name in ("Epoxy / Resinous Flooring Systems:", "Polished Concrete Systems:"):
        p = next(p for p in pw._iter_all_paragraphs(d) if p.text.strip() == name)
        assert [r.bold for r in p.runs if r.text] == [True], (
            "%s lost its heading weight: %r" % (name, [(r.text, r.bold) for r in p.runs]))


@pytest.mark.parametrize("typed, expect", [
    # Both sides of the split, so a change to either is deliberate.
    ("Schedule: two phases", [("Schedule:", True), (" two phases", False)]),
    # All label and nothing else — the whole thing is what he asked to be bold.
    ("Schedule:", [("Schedule:", True)]),
    # NO COLON, and this is where the letter diverges from the proposal on purpose: there the
    # normalizer stands down and a colon-less WORK row keeps its bold, because that row IS the
    # label. A cover-letter bullet is a two-word label in front of a two-line sentence, so
    # falling back to the label's weight bolds a paragraph that is nearly all detail — the exact
    # thing being fixed. The fallback is the DETAIL half's weight.
    ("Now a plain sentence with no label at all",
     [("Now a plain sentence with no label at all", False)]),
    # A leading colon leaves no label words in front of it.
    (": straight into the detail", [(": straight into the detail", False)]),
])
def test_the_edges_of_the_colon_rule(typed, expect):
    labels = _label_ids(("epoxy", "Direct"))
    bid = next(i for i, lab in labels.items() if lab.strip() == "Schedule:")
    d = docx.Document(io.BytesIO(clw.fill_cover_letter(
        work_type="epoxy", audience="Direct", values=FULL_VALUES,
        paragraph_overrides=[{"id": bid, "text": typed}])))
    p = next(p for p in pw._iter_all_paragraphs(d) if p.text.strip() == typed.strip())
    assert [(r.text, r.bold) for r in p.runs if r.text] == expect


def test_emptying_a_bullet_still_takes_the_blank_path():
    """A blank override must reach `_apply_paragraph_overrides` as the shape it expects, or the
    numbered-clause refusal stops protecting these bullets — they carry real Word numbering, so an
    emptied one would print a bare `3.` in a customer's letter. The split leaves blanks alone
    precisely so that guard still fires."""
    labels = _label_ids(("epoxy", "Direct"))
    bid = next(i for i, lab in labels.items() if lab.strip() == "Schedule:")
    d = docx.Document(io.BytesIO(clw.fill_cover_letter(
        work_type="epoxy", audience="Direct", values=FULL_VALUES,
        paragraph_overrides=[{"id": bid, "text": "   "}])))
    kept = _bullet_runs(d).get("Schedule:")
    assert kept, "the blank override emptied a numbered bullet instead of being refused"
    assert kept[0][1] is True and kept[0][0].rstrip().endswith(":"), kept


@pytest.mark.skipif(shutil.which("soffice") is None and shutil.which("libreoffice") is None,
                    reason="LibreOffice renders production's PDF; not installed on this box")
def test_the_rendered_pdf_shows_the_split_not_one_bold_line():
    """THE ARTEFACT THE CUSTOMER READS. LibreOffice renders the PDF in production and diverges
    from Word — it ignores docx text-box autofit — so a docx-level assertion is not by itself
    proof. `w:b` in flow text is not one of the divergences, and a letter has been pure flow since
    PR #453, but the whole point of this fix is a weight on a page: assert it on the page.

    Two spans on the line, one bold and one not. Before the fix this was ONE bold span.
    """
    import fitz                                  # noqa: PLC0415 — optional, dev-only
    import pdf_writer

    labels = _label_ids(("epoxy", "Direct"))
    bid = next(i for i, lab in labels.items() if lab.strip() == "Schedule:")
    docx_bytes = clw.fill_cover_letter(
        work_type="epoxy", audience="Direct", values=FULL_VALUES,
        paragraph_overrides=[{"id": bid, "text": "Schedule: the estimator retyped this."}])
    doc = fitz.open(stream=pdf_writer.docx_to_pdf(docx_bytes), filetype="pdf")
    try:
        spans = None
        for page in doc:
            for blk in page.get_text("dict")["blocks"]:
                for line in blk.get("lines", []):
                    joined = "".join(s["text"] for s in line["spans"])
                    if "the estimator retyped this." in joined:
                        spans = [s for s in line["spans"] if s["text"].strip()]
        assert spans, "the edited bullet never reached the rendered page"
        bold = ["bold" in s["font"].lower() or bool(s["flags"] & 2 ** 4) for s in spans]
        texts = [s["text"] for s in spans]
        label = next(i for i, t in enumerate(texts) if "Schedule:" in t)
        assert bold[label] is True, list(zip(texts, bold))
        assert any(b is False for b in bold[label + 1:]), (
            "the whole rendered line is bold: %r" % (list(zip(texts, bold)),))
    finally:
        doc.close()


# ── (c) PortalPublishIn.has_cover_letter ────────────────────────────────────────
def test_has_cover_letter_defaults_to_forwarding_nothing():
    """Same contract as require_deposit beside it: omitted means the portal keeps its stored
    value, so a re-send from an older page cannot switch a customer's letter off."""
    assert main.PortalPublishIn().has_cover_letter is None


@pytest.mark.parametrize("sent,expected", [
    (None, None),        # omitted -> absent from the forwarded body
    (True, True),
    (False, False),      # explicitly OFF must travel; it is not the same as omitted
])
def test_has_cover_letter_is_forwarded_only_when_chosen(monkeypatch, sent, expected):
    """Wired like test_portal_publish.py's `_wire`: the draft, the revision snapshot and the
    outbound call are all stubbed, so what is asserted is exactly the body the portal receives."""
    cap = {}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": {}})
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    monkeypatch.setattr(main.drafts, "create_revision", lambda did, data, by=None: 1)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main, "_portal",
                        lambda path, method="GET", body=None: cap.update(body=body) or {"ok": True})

    payload = {"emails": [], "assigned_estimator": "kyle@wetreadwell.com"}
    if sent is not None:
        payload["has_cover_letter"] = sent
    r = client.post("/api/portal/publish?draft_id=d1", json=payload)
    assert r.status_code == 200, r.text
    assert cap["body"].get("has_cover_letter") == expected
    if sent is None:
        assert "has_cover_letter" not in cap["body"], (
            "an omitted flag was forwarded anyway — that overwrites the portal's stored value")


# ── Will Buchanan's Direct wording (2026-09-03) ──────────────────────────────
def test_the_direct_letter_carries_wills_text_and_not_the_first_draft():
    """His email, verbatim: *"In addition to what Greg sent you for GC projects please use the
    text template below for direct projects. The highlighted text should be pulled from the
    intake form."* The three sentences he wrote out are fixed copy and must read exactly as he
    sent them -- a paraphrase is a different letter going to a customer."""
    d = docx.Document(str(clw.pick_template("epoxy", "Direct")))
    texts = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    assert "Thank you for the opportunity to provide a quote for this project." in texts
    assert "A few things to note:" in texts
    assert ("Schedule: This price is based on all work taking place in 1 phase/mobilization. "
            "If this needs to be split into multiple phases and/or over weekends, please let me "
            "know.") in texts
    assert "Feel free to reach out, if you have questions." in texts
    assert "Looking forward to working with you!" in texts
    body = "\n".join(texts)
    assert "Materials / System: {{cover_system_line}}" in body
    assert "Area: {{work_areas}}" in body


def test_the_direct_letter_no_longer_asks_the_estimator_to_pick_a_thickness():
    """Both placeholders it shipped with are answered now: the intake form asks for the thickness
    and `{{cover_system_line}}` composes the cove height. An instruction left beside a filled
    value is how a customer receives a document with "[COVE HEIGHT - pick one]" in it."""
    for wt in ("epoxy", "combo"):
        text = "\n".join(p.text for p in docx.Document(str(clw.pick_template(wt, "Direct"))).paragraphs)
        assert "[THICKNESS" not in text and "[COVE HEIGHT" not in text, wt
        assert "[SCHEDULE" not in text, wt


def test_the_gc_letter_did_not_move():
    """GC waits on Greg's text, which has not reached this repo. The module's standing rule --
    inventing contractor-flavoured sentences puts wording nobody approved in front of a customer
    -- is why Direct diverged alone rather than both letters moving together."""
    text = "\n".join(p.text for p in docx.Document(str(clw.pick_template("epoxy", "GC"))).paragraphs)
    assert "Thanks for the opportunity" in text
    assert "The pages that follow" in text
    assert "[THICKNESS" in text, "the GC letter lost its placeholder without Greg's wording"
    assert "{{cover_system_line}}" not in text
    assert prep.spec_for("epoxy", "GC") is prep.COPY["epoxy"]
    assert prep.spec_for("epoxy", "Direct") is prep.DIRECT_COPY["epoxy"]
    assert prep.spec_for("gyp", None) is prep.COPY["gyp"]


def test_the_polish_direct_letter_keeps_its_own_system_wording():
    """Will's Materials / System line is an epoxy one and he wrote nothing about polished
    concrete. Aggregate exposure and sheen are real spec decisions; guessing them to make the two
    letters look alike would put a spec claim in a customer document."""
    text = "\n".join(p.text for p in docx.Document(str(clw.pick_template("polish", "Direct"))).paragraphs)
    assert "{{cover_system_line}}" not in text
    assert "[AGGREGATE EXPOSURE" in text and "[SHEEN" in text
    assert "A few things to note:" in text            # his structure, though
    assert "Area: {{work_areas}}" in text


def test_the_area_line_appears_once_on_a_combo_letter():
    """It describes what the floor covers across the whole job. Under "Polished Concrete:" as
    well, the same words read as a second, different area."""
    text = "\n".join(p.text for p in docx.Document(str(clw.pick_template("combo", "Direct"))).paragraphs)
    assert text.count("Area: {{work_areas}}") == 1


@pytest.mark.parametrize("values, expect", [
    # Will's own example, end to end.
    ({"contact_name": "Brandon Weller", "system_name": "MACRO Flake Single Broadcast",
      "system_thickness": '1/4"', "cove_height": "6", "cove_lf": "420"},
     '1/4" MACRO Flake Single Broadcast with 6" Integral Cove Base'),
    # Three of Kyle's fifteen names already state a thickness. Prepending a DISAGREEING pick
    # would print two contradictory thicknesses in a spec line, so the name wins.
    ({"system_name": '3/16" Urethne Cement With Color Fast (SLB)', "system_thickness": '1/4"',
      "cove_lf": "0"},
     '3/16" Urethne Cement With Color Fast (SLB)'),
    # No cove, no cove clause. The proposal body still prints "with 0 LF of integral cove base"
    # on a no-cove job; the letter does not inherit that.
    ({"system_name": "MACRO Flake", "system_thickness": '1/8"', "cove_lf": "0"},
     '1/8" MACRO Flake'),
    ({"system_name": "MACRO Flake", "cove_lf": "1,200", "cove_height": "4"},
     'MACRO Flake with 4" Integral Cove Base'),      # thousands separator still reads as > 0
    ({"system_name": "MACRO Flake", "cove_lf": "420"},
     'MACRO Flake with 6" Integral Cove Base'),      # 6" is the default height
    ({"system_name": "Treadwell Polished Concrete", "cove_lf": "0"},
     "Treadwell Polished Concrete"),                 # polish: no thickness, no cove
])
def test_the_system_line_composes_what_no_template_text_could(values, expect):
    assert clw._ensure_cover_letter_values(values)["cover_system_line"] == expect


@pytest.mark.parametrize("contact, expect", [
    ("Brandon Weller", "Brandon,"),
    ("Brandon", "Brandon,"),
    ("brandon weller", "Brandon,"),        # capitalised
    ("McDonald Reyes", "McDonald,"),       # mixed case left as typed, never "Mcdonald,"
    ("", "Hello,"),                        # a bare comma is not a greeting
    (None, "Hello,"),
    ("brandon@acme.com", "Hello,"),        # Kyle sometimes has only an email
    # Found by this table, not confirmed by it: both sides greeted "B.," until the guard learned
    # to measure a name with an initial's punctuation removed. Kyle types this shape whenever he
    # has a surname and an initial and no more.
    ("B. Weller", "Hello,"),               # a lone initial is not a first name
    ("J.R. Weller", "J.R.,"),              # two real letters, and what that person is called
])
def test_the_greeting_is_a_first_name_or_an_honest_fallback(contact, expect):
    """Will's letter opens on the contact's first name and nothing else. NOTE a known wart, left
    alone on purpose: a contact typed "Weller, Brandon" greets "Weller," -- special-casing the
    comma would misfire on "Brandon Weller, PE", which is the commoner shape in this database."""
    assert clw._ensure_cover_letter_values({"contact_name": contact})["greeting"] == expect


def test_a_blank_area_box_prints_the_square_footage_rather_than_a_bare_label():
    """The letter's list items are static paragraphs -- `cover_letter_writer` deliberately does
    not port the `{{#block}}` expansion that could drop one -- so "Area:" with nothing after it
    is what an empty box would ship."""
    out = clw._ensure_cover_letter_values({"area_description": "~18,000 sf of epoxy flooring"})
    assert out["work_areas"] == "~18,000 sf of epoxy flooring"
    typed = clw._ensure_cover_letter_values(
        {"work_areas": "Warehouse expansion and 4 offices",
         "area_description": "~18,000 sf of epoxy flooring"})
    assert typed["work_areas"] == "Warehouse expansion and 4 offices"


def test_the_letter_prints_no_raw_token_with_the_new_fields_supplied():
    """The end-to-end shape: what the intake form now collects, through the real writer."""
    values = dict(FULL_VALUES, contact_name="Brandon Weller",
                  work_areas="Warehouse expansion and 4 offices", system_thickness='1/4"',
                  cove_height="6")
    for key in VARIANTS:
        d = docx.Document(io.BytesIO(clw.fill_cover_letter(
            work_type=key[0], audience=key[1], values=values)))
        assert clw.unfilled_tokens(d) == set(), key
    text = _rendered(clw.fill_cover_letter(work_type="epoxy", audience="Direct", values=values))
    assert "Brandon," in text
    assert "Area: Warehouse expansion and 4 offices" in text
    assert '1/4" Treadwell MACRO Flake with 6" Integral Cove Base' in text


# ── the two resolutions must agree ───────────────────────────────────────────
_HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "payload-sync-harness.js"
_FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture(scope="module")
def js_tokens():
    """What the BROWSER resolves, from the real `computeTokenValues` out of proposal-review.js.

    Executed, not read. A source assertion that both files "look the same" cannot catch a
    regex that behaves differently in the two languages, which is the whole risk here."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(_HARNESS), str(_FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    cases = json.loads(proc.stdout.strip().splitlines()[-1])["coverLetterTokens"]
    assert len(cases) >= 10, "the case table shrank; a thin table is how a fork survives"
    return cases


def test_the_screen_and_the_document_resolve_the_same_three_tokens(js_tokens):
    """THE BUG THIS EXISTS FOR. `{{greeting}}`, `{{work_areas}}` and `{{cover_system_line}}` are
    derived in two places: `computeTokenValues` (proposal-review.js) for the cover-letter editor's
    on-screen preview, and `_ensure_cover_letter_values` here for generate and for the portal's
    server-side replay of a pinned revision. A token resolved on only one side previews as a raw
    `{{token}}` over a correct PDF — exactly what PR #431 fixed for `{{proposal_date_short}}` —
    and an estimator proofreading on screen cannot tell that from a broken document.

    Neither side's answers are written down here. The JS side is executed, its answers and the
    upstream values it read are both returned, and Python is handed those same upstream values.
    So this asserts AGREEMENT, which is the property that matters; the per-branch expectations
    live in the parametrized tests above, where a literal is the point."""
    disagreements = []
    for case in js_tokens:
        up = {k: v for k, v in case["upstream"].items() if v is not None}
        out = clw._ensure_cover_letter_values(up)
        for token in ("greeting", "work_areas", "cover_system_line"):
            if out[token] != case[token]:
                disagreements.append(
                    "%s / %s: screen %r, document %r" % (case["name"], token, case[token], out[token]))
    assert not disagreements, (
        "the preview and the PDF have forked:\n  " + "\n  ".join(disagreements))


def test_the_agreement_table_actually_exercises_every_branch(js_tokens):
    """A green agreement test proves nothing if every row is the happy path — two identical
    implementations agree on anything. These are the branches that can fork."""
    lines = {c["name"]: c["cover_system_line"] for c in js_tokens}
    greets = {c["name"]: c["greeting"] for c in js_tokens}
    # a thickness prepended, and a thickness correctly NOT prepended
    assert lines["wills_own_example"].startswith('1/4"')
    assert lines["name_already_states_a_thickness"].startswith('3/16"'), lines
    assert "1/4" not in lines["name_already_states_a_thickness"], (
        "the estimator's pick was prepended onto a name that already states a different "
        "thickness — the letter now claims two")
    # the cove clause present and absent
    assert "Integral Cove Base" in lines["wills_own_example"]
    assert "Integral Cove Base" not in lines["no_cove_drops_the_clause"]
    # both greeting outcomes
    assert greets["wills_own_example"] == "Brandon,"
    assert set(greets.values()) >= {"Brandon,", "Hello,", "McDonald,"}
    # the fallback, and a typed value beating it
    fallback = next(c for c in js_tokens if c["name"] == "blank_area_falls_back_to_the_sf_line")
    assert "sf of" in fallback["work_areas"] and fallback["upstream"]["work_areas"] == ""
