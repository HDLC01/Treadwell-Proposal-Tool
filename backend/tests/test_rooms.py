"""Per-room estimate + proposal feature.

- proposal_writer `{{#room}}` block (heading + price + stacked notes), the
  `{{#single_bid}}` toggle, and the \\n -> <w:br/> note rendering.
- main._build_options (tax phrase, system line + signed difference toggles, notes).
- estimate_writer.fill_estimate(tab_copies=…) duplicating a worksheet.

Block-engine tests run on synthetic docs (no template dependency); real-template
rendering is covered in test_price_lines.py once the Direct templates carry the
{{#room}} / {{#single_bid}} markers.
"""
import io

from docx import Document
from docx.oxml.ns import qn
from openpyxl import load_workbook

import estimate_writer as ew
import main
import proposal_writer as pw


def _doc(lines):
    d = Document()
    for line in lines:
        d.add_paragraph(line)
    return d


def _texts(d):
    return [p.text for p in d.paragraphs]


# ── {{#room}} block ────────────────────────────────────────────────────
def test_room_block_expands_heading_price_notes():
    for n in (0, 1, 3):
        rooms = [{"heading": f"Room {i}:", "price_formatted": f"${i},000",
                  "price_desc": "Epoxy flooring as described above (material sales tax INCLUDED)",
                  "notes_joined": 'Includes 6" Cove Base'} for i in range(1, n + 1)]
        d = _doc(["{{#room}}", "{{room.heading}}",
                  "{{room.price_formatted}} – {{room.price_desc}}",
                  "{{room.notes_joined}}", "{{/room}}"])
        pw._expand_all_blocks(d, {"room": rooms})
        txt = "\n".join(_texts(d))
        assert "{{#room}}" not in txt and "{{/room}}" not in txt
        assert "room." not in txt                       # all per-item tokens resolved
        for i in range(1, n + 1):
            assert f"Room {i}:" in txt
            assert f"${i},000 – Epoxy flooring as described above (material sales tax INCLUDED)" in txt
        if n:
            assert 'Includes 6" Cove Base' in txt


def test_room_notes_render_as_linebreaks():
    rooms = [{"heading": "Grooming:", "price_formatted": "$8,310",
              "price_desc": "Epoxy flooring (material sales tax INCLUDED)",
              "notes_joined": 'Includes 6" Cove Base\nTo be completed in separate mobilization'}]
    d = _doc(["{{#room}}", "{{room.heading}}", "{{room.notes_joined}}", "{{/room}}"])
    pw._expand_all_blocks(d, {"room": rooms})
    txt = "\n".join(_texts(d))
    assert 'Includes 6" Cove Base' in txt
    assert "To be completed in separate mobilization" in txt
    # stacked notes share one paragraph/bullet but split on a real <w:br/> line break
    assert d.element.body.findall(".//" + qn("w:br"))


def test_single_bid_block_toggles():
    for items, shown in (([{}], True), ([], False)):
        d = _doc(["before", "{{#single_bid}}", "Base Bid",
                  "{{total_formatted}} – Total", "{{/single_bid}}", "after"])
        pw._expand_all_blocks(d, {"single_bid": items})
        txt = "\n".join(_texts(d))
        assert "before" in txt and "after" in txt
        assert "{{#single_bid}}" not in txt and "{{/single_bid}}" not in txt
        assert ("Base Bid" in txt) is shown


# ── main._build_options ─────────────────────────────────────────────────
def test_build_options_tax_phrase_and_note_merge():
    rooms_in = [
        {"name": "Grooming", "bid": {"total": 8310, "remodel": 0},
         "notes_auto": ['Includes 6" Cove Base'], "notes_manual": ["separate mobilization"]},
        {"name": "Hallway :", "bid": {"total": 15035, "remodel": 120},
         "notes_auto": [], "notes_manual": []},
        {"name": "Empty", "bid": {"total": 0}},          # no total -> skipped
    ]
    out = main._build_options(rooms_in, {"state_name": "Kansas"})
    assert len(out) == 2
    g, h = out
    assert g["heading"] == "Grooming:"
    assert g["price_formatted"] == "$8,310"
    assert g["price_desc"] == "Epoxy flooring as described above (material sales tax INCLUDED)"
    assert g["notes_joined"] == 'Includes 6" Cove Base\nseparate mobilization'   # auto before manual
    assert h["heading"] == "Hallway:"                    # trailing " :" normalized
    assert "Remodel Tax AND material sales tax INCLUDED" in h["price_desc"]
    assert "Kansas" not in h["price_desc"]   # state name dropped from the label


def test_build_options_empty():
    assert main._build_options([], {}) == []
    assert main._build_options(None, {}) == []


# ── system line + signed difference toggles ─────────────────────────────
_BASE = {"name": "Epoxy", "is_base": True, "base_total": 50000,
         "bid": {"total": 50000, "remodel": 0}, "system_desc": "Treadwell MACRO Flake",
         "show_system": True}


def test_build_options_system_line_toggle():
    on = main._build_options([dict(_BASE)], {})[0]
    assert on["notes_joined"].splitlines()[0] == "Treadwell MACRO Flake"
    off = main._build_options([{**_BASE, "show_system": False}], {})[0]
    assert "MACRO Flake" not in off["notes_joined"]
    # base item never shows a difference line
    assert "base bid" not in on["notes_joined"]


def test_build_options_signed_difference_both_ways():
    more = {"name": "Exam", "is_base": False, "base_total": 50000,
            "bid": {"total": 61000, "remodel": 0}, "show_system": False, "show_diff": True}
    less = {**more, "name": "Hall", "bid": {"total": 44000, "remodel": 0}}
    same = {**more, "name": "Same", "bid": {"total": 50000, "remodel": 0}}
    assert "+$11,000 more than the base bid" in main._build_options([more], {})[0]["notes_joined"]
    assert "$6,000 less than the base bid" in main._build_options([less], {})[0]["notes_joined"]
    assert "base bid" not in main._build_options([same], {})[0]["notes_joined"]   # 0 diff -> omitted
    # toggle off -> no difference line even when amounts differ
    assert "base bid" not in main._build_options([{**more, "show_diff": False}], {})[0]["notes_joined"]


def test_build_options_base_first_with_copy():
    opts = main._build_options([
        dict(_BASE),
        {"name": "Exam", "is_base": False, "base_total": 50000,
         "bid": {"total": 61000, "remodel": 0}, "show_system": False, "show_diff": True},
    ], {})
    assert [o["heading"] for o in opts] == ["Base Bid:", "Exam:"]   # base relabeled
    assert "+$11,000 more than the base bid" in opts[1]["notes_joined"]


# ── estimate_writer.fill_estimate(tab_copies=…) — duplicated worksheets ─
def test_fill_estimate_duplicates_tab():
    data = ew.fill_estimate({"project_name": "X"},
                            cell_values={"Copy1!E20": 4000},
                            tab_copies=[{"id": "Copy1", "source": "Epoxy"}])
    wb = load_workbook(io.BytesIO(data))
    assert "Copy1" in wb.sheetnames                   # copied worksheet created
    assert "Epoxy" in wb.sheetnames                   # source intact
    ws = wb["Copy1"]
    assert ws["E20"].value == 4000                    # copy's own cell write landed
    assert str(ws["D88"].value or "").startswith("=")            # bid formula copied (self-ref)
    assert ws["B1"].value == wb["Epoxy"]["B1"].value             # project info mirror copied


def test_fill_estimate_no_copies_unchanged():
    data = ew.fill_estimate({"project_name": "X"})
    wb = load_workbook(io.BytesIO(data))
    assert "Copy1" not in wb.sheetnames


# ── real Direct templates (epoxy + combo) render the {{#room}} block ────
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

_VALS = {
    "job_name": "J", "city_state": "C", "bid_date_formatted": "6/19/26",
    "base_bid_formatted": "$58,523.00", "material_tax_formatted": "$2,639.00",
    "state_name": "Kansas", "total_formatted": "$63,801.00",
    "system_name": "MACRO", "texture": "OP", "epoxy_sf": "12,000",
    "scope_notes": "demo + install", "schedule_notes": "~5 days",
    "work_description": "w", "site_visit_date": "6/19", "disposal": "d",
    "site_visit_phrase": "per site visit on 6/19/26",
    "base_tax_phrase": "(material sales tax INCLUDED)",
    "exclusions": "standard exclusions",
}
_ROOMS = [
    {"heading": "Grooming:", "price_formatted": "$8,310",
     "price_desc": "Epoxy flooring as described above (Remodel Tax AND material sales tax INCLUDED)",
     "notes_joined": 'Includes 6" Cove Base'},
    {"heading": "Exam Room:", "price_formatted": "$14,717",
     "price_desc": "Epoxy flooring as described above (material sales tax INCLUDED)",
     "notes_joined": 'Includes 6" Cove Base\nTo be completed in separate mobilization'},
]


def _rendered(docx_bytes):
    """Text of paragraphs Word actually renders (mc:Choice copy), excluding the
    legacy mc:Fallback duplicate — same helper as test_price_lines.py."""
    d = Document(io.BytesIO(docx_bytes))
    out = []
    for p in d.element.xpath("//w:p"):
        if any(True for _ in p.iterancestors(f"{_MC}Fallback")):
            continue
        t = "".join(x.text or "" for x in p.xpath(".//w:t")).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def test_notes_block_editable_with_default_fallback():
    # Fix #6: NOTES are an editable {{#notes}} block. Custom notes render;
    # _notes_for falls back to the standard per-work-type boilerplate when empty.
    blob = _rendered(pw.fill_proposal(work_type="epoxy", audience="Direct", values=_VALS,
                                      notes=[{"text": "Custom note A"}, {"text": "Custom note B"}]))
    assert "Custom note A" in blob and "Custom note B" in blob
    assert "{{notes" not in blob and "{{#notes}}" not in blob
    items = main._notes_for("epoxy", [])             # empty -> standard boilerplate
    assert items and "Excludes saw cutting" in items[0]["text"]
    assert main._notes_for("epoxy", ["only this"]) == [{"text": "only this"}]
    blob2 = _rendered(pw.fill_proposal(work_type="polish", audience="Direct", values=_VALS,
                                       notes=main._notes_for("polish", [])))
    assert "Excludes saw cutting" in blob2


def test_site_visit_phrase_and_base_tax_tokens_render():
    # Fix #3/#4: epoxy template uses {{site_visit_phrase}} + {{base_tax_phrase}};
    # both must fill (never render literally) and the old hardcoded phrasing is gone.
    vals = {**_VALS, "site_visit_phrase": "per plans and specifications provided",
            "base_tax_phrase": "(tax exempt)"}
    blob = _rendered(pw.fill_proposal(work_type="epoxy", audience="Direct", values=vals))
    assert "per plans and specifications provided" in blob
    assert "(tax exempt)" in blob
    assert "{{site_visit_phrase}}" not in blob and "{{base_tax_phrase}}" not in blob
    assert "per site visit on N/A" not in blob


def test_exclusions_token_carries_to_doc():
    # Fix #1: the Exclusions box must drive the doc (was hardcoded boilerplate).
    for wt in ("epoxy", "combo", "polish"):
        blob = _rendered(pw.fill_proposal(work_type=wt, audience="Direct",
                                          values={**_VALS, "exclusions": "Existing floor demo only"}))
        assert "Existing floor demo only" in blob, f"{wt}: edited exclusions did not carry"
        assert "Multiple layers of floor to be removed" not in blob, f"{wt}: stale hardcoded exclusions"


def test_remodel_tax_label_has_no_state_name():
    # Fix #2: the remodel-tax line reads "Remodel Tax", never "Kansas/Missouri Remodel Tax".
    import re
    for wt in ("epoxy", "combo"):
        blob = _rendered(pw.fill_proposal(work_type=wt, audience="Direct", values=_VALS,
                                          remodel=[{"amount_formatted": "$1,200"}]))
        assert "Remodel Tax" in blob, f"{wt}: remodel line missing"
        assert not re.search(r"(Kansas|Missouri)\s+Remodel Tax", blob), f"{wt}: state name still on remodel tax"


def test_rooms_render_options_and_hide_single_bid():
    import re
    for wt in ("epoxy", "combo"):
        blob = _rendered(pw.fill_proposal(work_type=wt, audience="Direct",
                                          values=_VALS, rooms=_ROOMS, single_bid=[]))
        assert "Grooming:" in blob and "Exam Room:" in blob, f"{wt}: room headings missing"
        assert ("$8,310 – Epoxy flooring as described above "
                "(Remodel Tax AND material sales tax INCLUDED)") in blob, f"{wt}: room price line"
        assert 'Includes 6" Cove Base' in blob and "separate mobilization" in blob, f"{wt}: room notes"
        # single Base-Bid layout suppressed when rooms present
        assert "Base Bid" not in blob, f"{wt}: single-bid not hidden"
        assert "$63,801.00 – Total" not in blob, f"{wt}: single-bid Total not hidden"
        assert not re.search(r"\{\{[#/]", blob), f"{wt}: leftover block marker"


def test_no_rooms_keeps_single_bid():
    import re
    for wt in ("epoxy", "combo"):
        # tax_breakout=True so the itemized Total line renders (the point here is
        # that single-bid is NOT suppressed when there are no room copies).
        blob = _rendered(pw.fill_proposal(work_type=wt, audience="Direct", values=_VALS,
                                          tax_breakout=True))
        assert "Base Bid" in blob, f"{wt}: single-bid Base Bid missing"
        assert "$63,801.00 – Total" in blob, f"{wt}: single-bid Total missing"
        assert "Grooming:" not in blob, f"{wt}: room content leaked with no rooms"
        assert not re.search(r"\{\{[#/]", blob), f"{wt}: leftover block marker"
