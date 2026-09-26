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

AND NEVER FEWER THAN ONE. Hanz, 2026-09-26: "Base bid and options should always have atleast 1 or 2
spaces from each other". Both sides clamp the count to 1..20: a saved 0, or a gap typed over to its
last line, still shows and prints one blank line directly above the heading, and the key that would
take the last line only moves the caret.

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
    size check fails); drop options_gap between main.py and the writer (N != 2 goes to 2); take the
    floor off (a saved 0 prints none)."""
    _assert_gap(_docx(work_type, audience, gap), max(1, gap))


@pytest.mark.parametrize("work_type,audience", _TEMPLATES)
def test_a_draft_saved_before_the_count_existed_prints_two(work_type, audience):
    """No `options_gap` key at all: the 2 the editor has always shown. Mutation: default to 0."""
    out = _docx(work_type, audience)
    _assert_gap(out, 2)
    # The heading's anchor is private working state and never reaches the file, nor does a
    # namespace declaration for it.
    xml = _document_xml(out)
    assert "twOptionsHeading" not in xml and "urn:treadwell" not in xml


def _run_look(p):
    """(font, size, colour) of a paragraph's first run that carries text."""
    for r in p.findall(qn("w:r")):
        if not "".join(t.text or "" for t in r.iter(qn("w:t"))):
            continue
        rpr = r.find(qn("w:rPr"))
        if rpr is None:
            return (None, None, None)
        f, z, c = rpr.find(qn("w:rFonts")), rpr.find(qn("w:sz")), rpr.find(qn("w:color"))
        return (f.get(qn("w:ascii")) if f is not None else None,
                z.get(qn("w:val")) if z is not None else None,
                c.get(qn("w:val")) if c is not None else None)
    return None


def _above_heading(docx_bytes, typed=(), pattern=r"options\b"):
    """Per text-box copy: the paragraphs between the heading and the nearest line above it that is
    neither blank nor one of the `typed` texts (a price row; Gyp's mobilization line), top down."""
    d = Document(io.BytesIO(docx_bytes))
    out = {}
    for tx in d.element.body.iter(qn("w:txbxContent")):
        where = "fallback" if any(True for _ in tx.iterancestors(_MC + "Fallback")) else "choice"
        ps = [p for p in tx if p.tag == qn("w:p")]
        for i, p in enumerate(ps):
            if not re.match(pattern, _text(p).strip(), re.IGNORECASE):
                continue
            j = i - 1
            while j >= 0 and (_blank(ps[j]) or _text(ps[j]) in typed):
                j -= 1
            out[where] = {"row": ps[j] if j >= 0 else None, "lines": ps[j + 1:i]}
    return out


@pytest.mark.parametrize("work_type,audience", _TEMPLATES)
def test_the_lines_typed_on_the_gap_print_above_its_blank_lines(work_type, audience):
    """Hanz, 2026-09-26: "I cant write texts on this white space lines". What he typed on the gap
    (price_overrides.before.heading_options) prints as paragraphs of their own ABOVE the counted
    blank lines -- the order the editor draws -- in both copies, in the price row's own font, size
    and colour (not a bare run at the document default), a typed BLANK line kept as the line it is,
    and no working mark left in the file. Mutations: drop the typed lines between main.py and the
    writer; let the spacer walk eat a typed blank line; print them as bare runs."""
    typed = ["", "Pricing valid for 30 days", ""]
    out = _docx(work_type, audience, 1, price_overrides={"before": {"heading_options": typed}})
    seen = _above_heading(out, typed)
    assert sorted(seen) == ["choice", "fallback"], sorted(seen)
    for where, s in seen.items():
        texts = [_text(p) for p in s["lines"]]
        assert texts == ["", "Pricing valid for 30 days", "", ""], (where, texts)
        row_look = _run_look(s["row"])
        words = s["lines"][1]
        # The row's own look, whatever this template sets it to (9pt Epoxy, 8pt Combo, 7.5pt GC...);
        # a bare run would have no size at all and print at the 12pt default.
        assert _run_look(words) == row_look and None not in row_look, (where, _run_look(words), row_look)
        ppr = words.find(qn("w:pPr"))
        assert ppr is None or ppr.find(qn("w:numPr")) is None, "a typed line carries a bullet"
        for p in (s["lines"][0], s["lines"][2], s["lines"][3]):
            assert _blank(p) and _mark_size(p) == "18", (where, _mark_size(p))
    xml = _document_xml(out)
    assert "twTypedLine" not in xml and "twOptionsHeading" not in xml


@pytest.mark.parametrize("work_type,audience", _TEMPLATES)
def test_a_gap_typed_over_still_prints_one_blank_line_above_the_heading(work_type, audience):
    """Hanz, 2026-09-26: "Base bid and options should always have atleast 1 or 2 spaces from each
    other". A payload whose gap was typed over to its last line (options_gap 0, saved before the
    floor) prints the typed lines and then ONE blank line, never the heading straight under his
    words, in both copies. Mutation: take the floor off options_gap_count."""
    typed = ["Pricing valid for 30 days"]
    out = _docx(work_type, audience, 0, price_overrides={"before": {"heading_options": typed}})
    seen = _above_heading(out, typed)
    assert sorted(seen) == ["choice", "fallback"], sorted(seen)
    for where, s in seen.items():
        texts = [_text(p) for p in s["lines"]]
        assert texts == ["Pricing valid for 30 days", ""], (where, texts)
        assert _blank(s["lines"][-1]) and _mark_size(s["lines"][-1]) == "18", where


def test_a_blank_line_typed_under_the_row_above_is_not_taken_for_a_spacer():
    """The gap replaces the TEMPLATE's spacers above the heading. A blank line the estimator typed
    under the Total row sits in the same place and looks the same, but it is his: the editor draws
    it, so the document keeps it. Mutation: the walk stops only at text again."""
    vals = dict(_VALS, tax_layout="BROKEN_OUT", material_tax_formatted="$1,000", price_taxable=True,
                price_remodel_on=False)
    out = _docx("epoxy", "Direct", 2, values=vals,
                price_overrides={"after": {"total": ["Includes one mobilization", ""]}})
    seen = _above_heading(out, ("Includes one mobilization",))
    assert sorted(seen) == ["choice", "fallback"], sorted(seen)
    for where, s in seen.items():
        assert [_text(p) for p in s["lines"]] == ["Includes one mobilization", "", "", ""], where
        assert _text(s["row"]).endswith("Total"), (where, _text(s["row"]))


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
        found = _assert_gap(_docx("combo", "Direct", gap, combo_options=combo), max(1, gap))
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
    # The floor: never fewer than one blank line above the heading.
    assert s({"options_gap": 0})["options_gap"] == pw.OPTIONS_GAP_MIN == 1
    assert s({"options_gap": "4"})["options_gap"] == 4
    assert s({"options_gap": -2})["options_gap"] == 1
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


def test_backspace_on_a_blank_line_removes_one(ran):
    b = ran["backspaceOnGap"]
    assert b["defaulted"] and b["lines"] == 1 and b["stored"] == 1 and b["caretOnGapLine"] == 0
    d = ran["deleteOnGap"]
    assert d["defaulted"] and d["lines"] == 2 and d["stored"] == 2 and d["caretOnGapLine"] == 0


def test_the_last_blank_line_is_never_taken_and_the_caret_just_moves(ran):
    """Hanz, 2026-09-26: "Base bid and options should always have atleast 1 or 2 spaces from each
    other". Backspace on the last blank line lands at the end of the line above, Delete on it at the
    start of the heading, Backspace at the heading's start goes up onto it, Delete at the end of the
    line above goes down onto it -- and the line is still there after every one of them. Mutation:
    let the keys take the last line again (the count goes to 0 and the gap is hidden)."""
    last = ran["backspaceLastGap"]
    assert last["defaulted"] and last["lines"] == 1 and last["stored"] == 1 and last["gapShown"]
    # Word's landing spot: the end of the line above.
    assert last["caretLine"] == "base-bid-row" and last["caretOffset"] == last["baseLen"]
    d = ran["deleteLastGap"]
    assert d["defaulted"] and d["lines"] == 1 and d["stored"] == 1
    assert d["caretLine"] == "options-heading" and d["caretOffset"] == 0
    h = ran["backspaceHeadingAtFloor"]
    assert h["defaulted"] and h["lines"] == 1 and h["stored"] == 1 and h["caretOnGapLine"] == 0
    assert h["headingText"] == "Options:"
    a = ran["deleteAboveAtFloor"]
    assert a["defaulted"] and a["lines"] == 1 and a["stored"] == 1 and a["caretOnGapLine"] == 0
    assert a["baseUnchanged"]


def test_backspace_at_the_heading_start_removes_one_and_never_goes_below_one(ran):
    h = ran["backspaceHeadingStart"]
    assert h["defaulted"] and h["lines"] == 2 and h["stored"] == 2
    assert h["caretLine"] == "options-heading" and h["caretOffset"] == 0
    assert h["headingText"] == "Options:"
    floor = ran["backspaceHeadingAtFloor"]
    assert floor["lines"] == 1 and floor["stored"] == 1 and floor["defaulted"]
    assert floor["headingText"] == "Options:"
    assert ran["backspaceMidHeading"] == {"lines": 2, "defaulted": False}


def test_enter_above_the_heading_adds_a_line_and_leaves_the_price_line_alone(ran):
    """The page's own Enter handler is bound here too. Mutation: skip the new Enter-above branch,
    and that handler writes a line break into the base line's override instead of adding a line.
    (Dropping the handler's stopPropagation changes nothing: it moves the caret onto the new blank
    line first, and the page's handler finds no line there to break.)"""
    e = ran["enterAtEndOfBase"]
    assert e["defaulted"] and e["lines"] == 2 and e["stored"] == 2 and e["caretOnGapLine"] == 0
    assert e["baseUnchanged"], e["baseAfter"]
    g = ran["enterOnGap"]
    assert g["lines"] == 3 and g["stored"] == 3 and g["caretOnGapLine"] == 1
    # Enter anywhere else in a price line is the page's own Enter: the text after the caret moves
    # to a line of its own under the price line (fix 5), never a break inside it -- and the gap is
    # not touched.
    m = ran["enterMidBase"]
    assert m["lines"] == 3 and m["defaulted"] and m["baseHead"] == m["headWas"]
    assert m["under"] == {"kind": "extra", "pos": "after", "text": m["tailWas"]}
    assert ran["noOptionsEnter"] == {"lines": 0, "newLineUnderBase": True, "baseUnchanged": True}


# ═══ the blank lines TAKE TEXT ═══════════════════════════════════════════════════════════════
# Hanz, 2026-09-26: "I cant write texts on this white space lines" -- #568 refused typing on them.
def test_a_character_typed_on_a_blank_line_makes_it_a_typed_line_where_it_was(ran):
    """Typed on blank line 1 of 2: line 1 holds the text, line 0 above it is a typed BLANK line so
    the text stays on the line it was typed on, and -- it was the last blank line -- a fresh one is
    kept under it, so the heading still has one above it (the floor). Every line is exactly one of
    the two. Stored as price_overrides.before.heading_options, the same storage as a line typed
    under any price line, and saved. Mutation: refuse the key again (#568)."""
    t = ran["typeOnGap"]
    assert t["defaulted"] and t["typed"] == ["", "x"] and t["drawn"] == ["", "x"]
    assert t["stored"] == 1 and t["lines"] == 1
    assert t["typedDirectlyAboveGap"] and t["gapDirectlyAboveHeading"]
    assert t["caretIsTyped"] and t["caretText"] == "x" and t["caretOffset"] == 1
    assert ran["typeOnGapSaved"]["before"] == {"heading_options": ["", "x"]}
    assert ran["typeOnGapSaved"]["options_gap"] == 1
    # On blank line 0 of 2: the typed line, then the one blank line still in the count.
    f = ran["typeOnFirstGap"]
    assert f["typed"] == ["a"] and f["stored"] == 1 and f["lines"] == 1 and f["typedDirectlyAboveGap"]


def test_the_keys_around_a_typed_line_behave_like_word(ran):
    """Enter at the end of the typed line: one more blank line under it. Delete at its end: the
    blank line under it goes. Backspace on the last blank line: refused (the floor), the caret at
    the end of the typed line. Backspace at the start of "Options:" with one blank line left: the
    line and the words above it stay, the caret goes up onto the blank line. An EMPTY typed line
    above is still Backspace's to take, from its own start."""
    e = ran["enterAtEndOfTyped"]
    assert e["defaulted"] and e["typed"] == ["a"] and e["stored"] == 2 and e["caretOnGapLine"] == 0
    d = ran["deleteAtEndOfTyped"]
    assert d["defaulted"] and d["typed"] == ["a"] and d["stored"] == 1 and d["caretText"] == "a"
    b = ran["backspaceOntoTyped"]
    assert b["defaulted"] and b["stored"] == 1 and b["lines"] == 1
    assert b["caretText"] == "a" and b["caretOffset"] == 1
    h = ran["backspaceHeadingUnderTyped"]
    assert h["defaulted"] and h["typed"] == ["a"] and h["lines"] == 1 and h["caretOnGapLine"] == 0
    assert h["headingText"] == "Options:"
    # A draft saved with no blank line left (0, an empty typed line right above the heading) shows
    # the one the floor keeps; Backspace walks up from the heading onto it, then (refused) to the end
    # of the empty typed line, which the page's own Backspace then takes away.
    o = ran["backspaceHeadingOverTyped"]
    assert o["defaulted"] and o["lines"] == 1 and o["caretOnGapLine"] == 0 and o["drawn"] == ["kept", ""]
    f = ran["backspaceFloorOntoEmptyTyped"]
    assert f["defaulted"] and f["lines"] == 1 and f["caretOnEmptyTyped"] and f["caretOffset"] == 0
    k = ran["backspaceTakesEmptyTyped"]
    assert k["defaulted"] and k["drawn"] == ["kept"] and k["lines"] == 1
    assert k["caretText"] == "kept" and k["caretOffset"] == 4
    # An empty typed line under the price rows: Backspace takes it, and the caret lands at the end
    # of the line SHOWN above -- the base line, not the hidden tax rows between them.
    x = ran["backspaceEmptyFirstTyped"]
    assert x["defaulted"] and x["drawn"] == ["x"]
    assert x["caretLine"] == "base-bid-row" and x["caretOffset"] == x["baseLen"]


def test_paste_and_the_other_routes_land_as_typed_lines(ran):
    p = ran["pasteOnGap"]
    assert p["defaulted"] and p["typed"] == ["first", "second"] and p["stored"] == 1
    assert p["caretText"] == "second" and p["caretOffset"] == 6
    b = ran["beforeInputOnGap"]
    assert b["defaulted"] and b["typed"] == ["", "q"] and b["stored"] == 1 and b["lines"] == 1
    # A deletion by a route the keys do not cover is refused and changes nothing.
    r = ran["beforeInputDelete"]
    assert r["defaulted"] and r["typed"] is None and r["lines"] == 2


def test_a_base_bid_flip_keeps_the_gap_and_what_was_typed_on_it(ran):
    """The base-bid radio's own change handler, run. Typing on blank line 1 of 2 moved both lines
    out of the count into the typed lines; the flip cleared those with the old base's edits and
    kept the count, so the note was lost and the 2-line gap came back as 0. The gap and its lines
    do not depend on the base. Since the base-pick fix (Hanz, 2026-09-26: keep the words) the base
    line's own words and the lines typed round it survive the flip too: one rule
    (TWPrice.applyBasePick) for both pickers. Mutation: the flip clears before.heading_options
    again."""
    f = ran["flipKeepsGap"]
    # Typing on the last blank line keeps a fresh one under it (the gap's floor of one line).
    assert f["typedBefore"] == {"typed": ["", "N"], "lines": 1, "stored": 1}
    assert f["base"] == "Copy1"
    assert f["typed"] == ["", "N"] and f["drawn"] == ["", "N"], f
    assert f["stored"] == 1 and f["lines"] == 1 and f["typedDirectlyAboveGap"]
    assert f["oldBaseLine"] == "\u27e6amount\u27e7 – for the old base", f
    assert f["oldBaseTyped"] == ["typed under the old base"], f


def test_saved_typed_lines_are_drawn_above_the_blank_lines(ran):
    # Saved with options_gap 0, from before the floor: drawn with the one blank line it keeps.
    t = ran["reloadTyped"]
    assert t["drawn"] == ["kept", ""] and t["lines"] == 1 and t["typedDirectlyAboveGap"]


def test_typing_on_the_last_blank_line_keeps_a_fresh_one_under_it(ran):
    """The one blank line left takes text like any other, and the floor keeps one more under it, so
    "Options:" never ends up directly under a line. Mutation: store n - 1 - at unfloored (0)."""
    t = ran["typeOnLastGap"]
    assert t["defaulted"] and t["typed"] == ["z"] and t["drawn"] == ["z"]
    assert t["lines"] == 1 and t["stored"] == 1 and t["typedDirectlyAboveGap"]
    assert t["gapDirectlyAboveHeading"] and t["caretText"] == "z" and t["caretOffset"] == 1
    assert ran["typeOnLastGapSaved"]["options_gap"] == 1
    assert ran["typeOnLastGapSaved"]["before"] == {"heading_options": ["z"]}


def test_gc_draws_the_typed_line_between_its_spacer_and_the_gap(ran):
    """The writer takes the template's own spacer out and prints the typed lines, then the blank
    lines: the spacer stays hidden here too, above the typed line."""
    g = ran["gcTyped"]
    assert g["typed"] == ["G"] and g["stored"] == 1 and g["typedDirectlyAboveGap"]
    assert g["spacerHidden"] and g["spacerAboveTyped"]


def test_the_count_is_saved_through_price_overrides_and_a_reload_restores_it(ran):
    assert ran["persisted"] == {"price_overrides": {"options_gap": 2}}
    assert ran["refitted"] >= 1
    r = ran["reload"]
    assert r["three"] == {"lines": 3, "shown": True, "counted": 3}
    # A saved 0 (or less) is drawn at the floor: one line.
    assert r["zero"] == {"lines": 1, "shown": True, "counted": 1}
    assert r["string"]["lines"] == 4 and r["garbage"]["lines"] == 2
    assert r["negative"]["lines"] == 1 and r["huge"]["lines"] == 20 and r["fraction"]["lines"] == 2
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
    for v, want in ((3, 3), (0, 1), ("4", 4), ("lots", 2), (-2, 1), (99, 20), (2.5, 2)):
        assert pw.options_gap_count(v) == want, v
    r = ran["reload"]
    assert [r[k]["counted"] for k in ("three", "zero", "string", "garbage", "negative", "huge",
                                      "fraction")] == [3, 1, 4, 2, 1, 20, 2]


def test_a_line_emptied_and_kept_above_the_gap_is_not_taken_into_it(ran):
    """The editor's half of test_line_removal.py's kept-line document test. The gap takes in a blank
    template paragraph directly above the heading -- the placeholder break an emptied spacer holds
    included, since collectOverrides sends that as no change at all -- but never a template line the
    estimator emptied and KEPT: the writer prints that one (`kept`), so this page draws it. A
    `text: ""` saved before the flag, restored as an empty line, is taken in on both sides."""
    got = ran["keptAboveGap"]
    assert got["kept"] == {"mobilShown": True, "spacerHidden": True, "lines": 2}
    assert got["cleared"] == {"spacerHidden": True, "totalShown": True}
    assert got["gcKept"] == {"totalShown": True, "spacerHidden": True}
    assert got["legacy"] == {"mobilShown": False, "spacerHidden": True}


def test_changing_the_gap_asks_for_the_size_again(ran):
    """The review's case: Enter four times on the blank lines above "Options:" and the PRICE box kept
    the scale it had (0.93) while the document printed it at 0.75. The gap's keys consume their
    keystroke, so no `input` reached the page's refit; a price_overrides change now asks
    POST /api/proposal-fit again (queuePovSave -> scheduleFit)."""
    got = ran["gapAsksFit"]
    assert got["before"] == 0
    assert got["afterEnter"] == 1 and got["afterBackspace"] == 2
    assert got["lines"] == 2


def test_enter_in_the_hidden_options_heading_writes_nothing_there(ran):
    """A caret inside the hidden "Options:" heading (a bid with no options) takes no Enter: no typed
    line is made of it (it would print once options are added), the heading keeps its words and stays
    hidden, and the caret goes to the end of the base line, the line shown above."""
    got = ran["enterInHiddenHeading"]
    assert got["defaulted"] is True
    assert got["heading"] == "Options:" and got["headingHidden"] is True
    assert got["extraLines"] == 0 and got["typedHeading"] is None
    assert got["caretLine"] == "base-bid-row"
    assert got["caretOffset"] == len("$36,763 – Epoxy flooring as described above (material sales tax INCLUDED)")
