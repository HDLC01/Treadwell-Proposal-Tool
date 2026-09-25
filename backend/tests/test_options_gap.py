"""The blank lines above the PRICE "Options" heading are a real, editable count.

Hanz, 2026-09-25, clicking through the Proposal step on staging: "I cant edit this part" / "I cant
back space before options".

WHAT WAS WRONG, three ways at once:

  * THE EDITOR drew the gap as `margin:24pt` on #options-heading. Nothing to put a caret on, nothing
    for Backspace to take.
  * THE DOCUMENT printed no gap at all on the Epoxy and Combo Direct files. The writer's
    `_space_before_options` inserted blank paragraphs only before a heading reading exactly
    "Options", and those two templates say "Options:". Polish ("Options ") got two, but as bare
    `<w:p/>` at the 12pt document default rather than the box's 9pt.
  * Gyp and the GC files printed the template's own single small spacer.

NOW: `price_overrides.options_gap` = N real lines (absent = 2, what the editor has always shown).
The editor draws N line elements the caret can sit on (js/options-gap-harness.js drives the real
key handlers). The writer prints EXACTLY N blank 9pt paragraphs directly above the heading on every
template that has one, in both text-box copies, REPLACING the template's own spacer
(proposal_writer._apply_options_gap), anchored on the heading paragraph, not on its words.

Every document test here goes through the real `main._generate`, the function Download, Send and the
customer PDF all render through. LibreOffice is not installed on the dev box, so the checks are made
on the .docx itself, in both the mc:Choice copy (Word) and the mc:Fallback copy (what LibreOffice
renders to PDF).
"""
import io
import json
import pathlib
import re
import shutil
import subprocess
import zipfile

import pytest
from docx import Document
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
from starlette.requests import Request

import main
import proposal_writer as pw

client = TestClient(main.app)

_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "options-gap-harness.js"

_VALS = {
    "job_name": "Gap QA", "project_name": "Gap QA", "city_state": "Olathe, KS",
    "bid_date_formatted": "9/25/26", "total_formatted": "$36,763", "base_bid_formatted": "$36,763",
    "state_name": "Kansas", "system_name": "MACRO", "texture": "OP", "epoxy_sf": "12,000",
    "scope_notes": "s", "schedule_notes": "~5d", "work_description": "w",
    "site_visit_date": "9/25", "disposal": "d", "exclusions": "std",
    "mobilizations_line": "1 Mobilization to Site.",
}

# One of each template family that prints an Options heading. "epoxy/GC" is the GC Resinous file.
_TEMPLATES = [("epoxy", "Direct"), ("polish", "Direct"), ("combo", "Direct"),
              ("epoxy", "GC"), ("gyp", "Direct")]
_ABSENT = object()


def _docx(work_type, audience, gap=_ABSENT, *, options=True, **extra):
    """The .docx the real generate path produces, read straight out of its file cache."""
    pov = dict(extra.pop("price_overrides", {}))
    if gap is not _ABSENT:
        pov["options_gap"] = gap
    body = {"work_type": work_type, "audience": audience, "values": dict(_VALS),
            "price_overrides": pov,
            "price_lines": [{"label": "Add dye", "amount": 1500}] if options else []}
    body.update(extra)
    req = Request({"type": "http", "headers": [], "method": "POST", "path": "/api/generate"})
    out = main._generate(main.GenerateIn(**body), req, persist=False, want_estimate=False)
    return main._FILE_CACHE[out.docx_download_url.rstrip("/").split("/")[-1]]["content"]


def _text(p):
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def _blank(p):
    """Prints as one empty line. Defined here, not borrowed from the writer under test."""
    if p.tag != qn("w:p") or _text(p).strip():
        return False
    return not any(next(p.iter(qn(t)), None) is not None
                   for t in ("w:br", "w:cr", "w:tab", "w:drawing", "w:pict", "w:object"))


def _mark_size(p):
    ppr = p.find(qn("w:pPr"))
    rpr = ppr.find(qn("w:rPr")) if ppr is not None else None
    sz = rpr.find(qn("w:sz")) if rpr is not None else None
    return sz.get(qn("w:val")) if sz is not None else None


def _headings(docx_bytes, pattern=r"options\b"):
    """Every text-box paragraph whose words start with `pattern`, with the blank run above it."""
    d = Document(io.BytesIO(docx_bytes))
    found = []
    for tx in d.element.body.iter(qn("w:txbxContent")):
        where = "fallback" if any(True for _ in tx.iterancestors(_MC + "Fallback")) else "choice"
        ps = [p for p in tx if p.tag == qn("w:p")]
        for i, p in enumerate(ps):
            if not re.match(pattern, _text(p).strip(), re.IGNORECASE):
                continue
            blanks, j = [], i - 1
            while j >= 0 and _blank(ps[j]):
                blanks.append(ps[j])
                j -= 1
            found.append({"copy": where, "heading": _text(p).strip(), "blanks": blanks,
                          "above": _text(ps[j]).strip() if j >= 0 else None})
    return found


def _assert_gap(docx_bytes, n, pattern=r"options\b"):
    found = _headings(docx_bytes, pattern)
    assert sorted(f["copy"] for f in found) == ["choice", "fallback"], (
        "expected the heading once in each text-box copy", [(f["copy"], f["heading"]) for f in found])
    for f in found:
        assert len(f["blanks"]) == n, (
            f"{f['copy']} copy: {len(f['blanks'])} blank line(s) above {f['heading']!r}, expected {n}")
        for p in f["blanks"]:
            # 9pt, the price box's own size: not the 12pt default a bare <w:p/> prints at.
            assert _mark_size(p) == "18", (f["copy"], _mark_size(p))
            ppr = p.find(qn("w:pPr"))
            assert ppr is None or ppr.find(qn("w:numPr")) is None, "a blank line carries a bullet"
        # Directly under a real price row, not under some other blank the count missed.
        assert f["above"] and "$" in f["above"] or f["above"] == "1 Mobilization to Site.", f
    return found


def _document_xml(docx_bytes):
    return zipfile.ZipFile(io.BytesIO(docx_bytes)).read("word/document.xml").decode("utf-8")


# ═══ the document: EXACTLY N blank lines, every template, both copies ════════════════════════
@pytest.mark.parametrize("work_type,audience", _TEMPLATES)
@pytest.mark.parametrize("gap", [0, 1, 2, 3])
def test_exactly_n_blank_lines_print_above_the_options_heading(work_type, audience, gap):
    """Mutations: anchor the heading on its exact words again (Epoxy/Combo go to 0); stop replacing
    the template's own spacer (Gyp/GC print one extra); build the blank lines as bare <w:p/> (the
    size check fails); drop options_gap between main.py and the writer (N != 2 goes to 2)."""
    _assert_gap(_docx(work_type, audience, gap), gap)


@pytest.mark.parametrize("work_type,audience", _TEMPLATES)
def test_a_draft_saved_before_the_count_existed_prints_two(work_type, audience):
    """No `options_gap` key at all: the 2 the editor has always shown. Mutation: default to 0."""
    out = _docx(work_type, audience)
    _assert_gap(out, 2)
    # The heading's anchor is private working state and never reaches the file, nor does a
    # namespace declaration for it.
    xml = _document_xml(out)
    assert "twOptionsHeading" not in xml and "urn:treadwell" not in xml


@pytest.mark.parametrize("work_type,audience", [("epoxy", "Direct"), ("polish", "Direct"),
                                                ("combo", "Direct"), ("gyp", "Direct")])
def test_no_options_prints_no_heading_and_no_gap(work_type, audience):
    """As before: with nothing to introduce, the heading is stripped and so is its gap -- and the
    count has nothing to act on, so any value gives the same document."""
    a = _docx(work_type, audience, 0, options=False)
    b = _docx(work_type, audience, 5, options=False)
    assert _headings(a) == [] and _headings(b) == []
    assert _document_xml(a) == _document_xml(b)


def test_the_combo_breakout_heading_takes_the_gap_too():
    """On the combo breakout the heading is a restored "Options:" price row (main.py), not the
    {{#has_options}} paragraph. It is the same heading to the estimator, so it gets the same lines.
    Mutation: drop the `_options_heading` flag on that row."""
    combo = [{"label": "Epoxy flooring as described above", "amount_formatted": "$20,000"},
             {"label": "Polished concrete as described above", "amount_formatted": "$16,763"}]
    for gap in (0, 3):
        found = _assert_gap(_docx("combo", "Direct", gap, combo_options=combo), gap)
        assert all("Polished concrete" in f["above"] for f in found), found


def test_a_renamed_heading_keeps_its_gap():
    """Anchored on the paragraph, not the words: the heading_options whole-line override renames
    the heading in place and the gap stays above it."""
    out = _docx("epoxy", "Direct", 3,
                price_overrides={"lines": {"heading_options": "Add-ons & Alternates:"}})
    _assert_gap(out, 3, pattern=r"add-ons")
    assert _headings(out) == []


def test_a_renamed_gc_heading_keeps_its_gap_and_the_endpoint_names_it():
    """The GC heading is a free paragraph, so the editor gets its id from /api/proposal-template
    (`options_heading_ids`) and can rewrite it through paragraph_overrides. The gap follows it."""
    r = client.get("/api/proposal-template?work_type=epoxy&audience=GC")
    assert r.status_code == 200, r.text
    j = r.json()
    ids = j["options_heading_ids"]
    by_id = {b["id"]: b for b in j["blocks"]}
    assert len(ids) == 1 and by_id[ids[0]]["text"].startswith("Options & Unit Prices")
    assert by_id[ids[0]]["in_block"] is None
    out = _docx("epoxy", "GC", 1,
                paragraph_overrides=[{"id": ids[0], "text": "Alternates & Unit Prices"}])
    # A paragraph override lands on the mc:Choice copy only (its ids come from the non-Fallback
    # walk; that is how every paragraph edit has always travelled). The gap is anchored on the
    # PARAGRAPH, so both copies carry it whatever their words now say.
    renamed, original = _headings(out, r"alternates"), _headings(out)
    assert [f["copy"] for f in renamed] == ["choice"], renamed
    assert [f["copy"] for f in original] == ["fallback"], original
    for f in renamed + original:
        assert len(f["blanks"]) == 1 and all(_mark_size(p) == "18" for p in f["blanks"]), f
        assert f["above"] == "$36,763 – Total", f


def test_a_region_heading_is_not_named_as_a_free_block():
    """On the Direct files the heading lives in {{#has_options}}: the editor's own #options-heading
    stands in for it, so no template block is named."""
    for wt in ("epoxy", "polish", "combo"):
        r = client.get(f"/api/proposal-template?work_type={wt}&audience=Direct")
        assert r.status_code == 200 and r.json()["options_heading_ids"] == [], wt


def test_the_sanitizer_keeps_the_count_and_only_when_it_was_stated():
    """A payload saved before the key existed stays exactly as it was (no key = the writer's 2).
    Same clamp and same rules as the editor's optionsGapCount."""
    s = main._sanitize_price_overrides
    assert "options_gap" not in s({})
    assert "options_gap" not in s({"options_gap": None})
    assert s({"options_gap": 3})["options_gap"] == 3
    assert s({"options_gap": 0})["options_gap"] == 0
    assert s({"options_gap": "4"})["options_gap"] == 4
    assert s({"options_gap": -2})["options_gap"] == 0
    assert s({"options_gap": 99})["options_gap"] == pw.OPTIONS_GAP_MAX == 20
    assert s({"options_gap": 3.0})["options_gap"] == 3
    for junk in ("lots", 2.5, True):
        assert s({"options_gap": junk})["options_gap"] == pw.OPTIONS_GAP_DEFAULT == 2, junk
    assert "options_gap" not in s({"options_gap": {"n": 3}})


# ═══ the editor: the real key handlers ═══════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed; read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_heading_carries_no_margin_standing_in_for_the_gap(ran):
    """The 24pt top margin was the bug: it drew a gap nothing could click into."""
    assert ran["headingMargin"] == "0 0 1pt" and not ran["headingMarginTop"]
    order = ran["mountOrder"]
    assert order.index("options-gap") == order.index("options-heading") - 1


def test_a_legacy_draft_shows_two_real_lines_inside_the_editing_host(ran):
    assert ran["legacyDraft"]["lines"] == 2 and ran["legacyDraft"]["gapDirectlyAboveHeading"]
    # A paragraph with a placeholder break, inheriting the box's contenteditable: a click lands a
    # caret on it and the arrow keys walk through it.
    assert ran["lineInHost"] == {"host": "tw-txbx", "ownHost": None, "isParagraph": "P",
                                 "placeholder": ["BR"]}
    assert ran["clickLandsOnLine"] == 1
    assert ran["arrowDown"] is False and ran["arrowUp"] is False
    assert ran["typeOnGap"] == {"refused": True, "lines": 2}


def test_backspace_on_a_blank_line_removes_one(ran):
    b = ran["backspaceOnGap"]
    assert b["defaulted"] and b["lines"] == 1 and b["stored"] == 1 and b["caretOnGapLine"] == 0
    last = ran["backspaceLastGap"]
    assert last["lines"] == 0 and last["stored"] == 0 and not last["gapShown"]
    # Word's landing spot: the end of the line above.
    assert last["caretLine"] == "base-bid-row" and last["caretOffset"] == last["baseLen"]
    d = ran["deleteOnGap"]
    assert d["defaulted"] and d["lines"] == 2 and d["stored"] == 2 and d["caretOnGapLine"] == 0


def test_backspace_at_the_heading_start_removes_one_and_never_goes_below_zero(ran):
    h = ran["backspaceHeadingStart"]
    assert h["defaulted"] and h["lines"] == 1 and h["stored"] == 1
    assert h["caretLine"] == "options-heading" and h["caretOffset"] == 0
    assert h["headingText"] == "Options:"
    zero = ran["backspaceHeadingAtZero"]
    assert zero["lines"] == 0 and zero["stored"] == 0 and zero["defaulted"]   # the page's refusal
    assert zero["headingText"] == "Options:"
    assert ran["backspaceMidHeading"] == {"lines": 1, "defaulted": False}


def test_enter_above_the_heading_adds_a_line_and_leaves_the_price_line_alone(ran):
    """The page's own Enter handler is bound here too. Mutation: skip the new Enter-above branch,
    and that handler writes a line break into the base line's override instead of adding a line.
    (Dropping the handler's stopPropagation changes nothing: it moves the caret onto the new blank
    line first, and the page's handler finds no line there to break.)"""
    e = ran["enterAtEndOfBase"]
    assert e["defaulted"] and e["lines"] == 1 and e["stored"] == 1 and e["caretOnGapLine"] == 0
    assert e["baseUnchanged"], e["baseAfter"]
    g = ran["enterOnGap"]
    assert g["lines"] == 2 and g["stored"] == 2 and g["caretOnGapLine"] == 1
    # Enter anywhere else in a price line is still the page's own line break.
    assert ran["enterMidBase"] == {"lines": 2, "defaulted": True, "baseHasBreak": True}
    assert ran["noOptionsEnter"] == {"lines": 0, "baseGotBreak": True}


def test_the_count_is_saved_through_price_overrides_and_a_reload_restores_it(ran):
    assert ran["persisted"] == {"price_overrides": {"options_gap": 2}}
    assert ran["refitted"] >= 1
    r = ran["reload"]
    assert r["three"] == {"lines": 3, "shown": True, "counted": 3}
    assert r["zero"] == {"lines": 0, "shown": False, "counted": 0}
    assert r["string"]["lines"] == 4 and r["garbage"]["lines"] == 2
    assert r["negative"]["lines"] == 0 and r["huge"]["lines"] == 20 and r["fraction"]["lines"] == 2
    assert ran["noOptions"] == {"lines": 0, "shown": False}


def test_gc_and_gyp_hide_the_template_spacer_the_writer_replaces(ran):
    """The writer replaces the template's own spacer, so the editor must not draw it as well."""
    assert ran["gc"] == {"lines": 2, "gapDirectlyAboveHeading": True, "gapInBox": True,
                         "spacerHidden": True, "trailingBlankKept": True}
    assert ran["gcBackspaceHeading"]["lines"] == 1 and ran["gcBackspaceHeading"]["defaulted"]
    t = ran["gcEnterAtTotal"]
    assert t["lines"] == 2 and t["totalUnchanged"] and t["caretOnGapLine"] == 0
    assert ran["gcTypedSpacer"] == {"spacerHidden": False}
    assert ran["gyp"] == {"lines": 2, "gapDirectlyAboveHeading": True, "spacerHidden": True,
                          "mobilShown": True}
    assert ran["gypEnterAtMobil"]["lines"] == 3


def test_the_editor_and_the_writer_agree_on_the_count_rule(ran):
    """Same input, same count, both sides: optionsGapCount in the page vs options_gap_count here."""
    for v, want in ((3, 3), (0, 0), ("4", 4), ("lots", 2), (-2, 0), (99, 20), (2.5, 2)):
        assert pw.options_gap_count(v) == want, v
    r = ran["reload"]
    assert [r[k]["counted"] for k in ("three", "zero", "string", "garbage", "negative", "huge",
                                      "fraction")] == [3, 0, 4, 2, 0, 20, 2]
