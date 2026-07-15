"""WORK 'Notes:' line ({{work_notes}}) — an editable per-job note that always
renders in the WORK section of the Direct epoxy/polish + gyp templates (Kyle:
"Note should always be present"). Combo/budget have a different WORK layout and
are handled separately. The backend coerces work_notes to a string so a blank
never leaks a raw {{work_notes}} token onto a customer proposal.
"""
import io
import re
import zipfile

import main
import proposal_writer as pw


def _vals(wt, **over):
    v = {
        "job_name": "WN QA", "project_name": "WN QA", "city_state": "KCK",
        "bid_date_formatted": "7/16/26", "system_name": "Sys", "texture": "OP",
        "epoxy_sf": "1,000", "cove_lf": "50", "polish_sf": "1,000",
        "disposal": "d", "scope_notes": "s", "schedule_notes": "~1w", "exclusions": "e",
        "base_bid_formatted": "$10,000.00", "total_formatted": "$10,000.00",
        "material_tax_formatted": "$0.00", "estimator_name": "K", "state_name": "Kansas",
        "site_visit_phrase": "per site visit", "base_tax_phrase": "(material sales tax INCLUDED)",
        "work_type": wt,
        "gyp_soft_sf": "1,000", "gyp_hard_sf": "0", "gyp_corridor_sf": "0",
        "gyp_soft_thickness": '3/4"', "gyp_hard_thickness": '1"', "gyp_corridor_thickness": '3/4"',
        "mobilizations_line": "1 Mob", "work_description": "per plans",
        "epoxy_system_name": "Epoxy System",   # combo WORK uses this
    }
    v.update(over)
    return v


def _gen(wt, **over):
    v = _vals(wt, **over)
    main._ensure_value_aliases(v, "Direct")
    out = pw.fill_proposal(work_type=wt, audience="Direct", values=v)
    xml = zipfile.ZipFile(io.BytesIO(out)).read("word/document.xml").decode("utf-8")
    text = " ".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.S))
    return xml, text


def test_work_notes_line_renders_for_epoxy_polish_gyp():
    for wt in ("epoxy", "polish", "gyp", "combo"):
        xml, text = _gen(wt, work_notes="VCT ghosting warning ZZZ")
        assert "{{work_notes}}" not in xml, f"{wt}: raw work_notes token leaked"
        assert "Notes:" in text, f"{wt}: WORK 'Notes:' label missing"
        assert "VCT ghosting warning ZZZ" in text, f"{wt}: work_notes value not rendered"


def test_blank_work_notes_never_leaks_raw_token():
    for wt in ("epoxy", "polish", "gyp", "combo"):
        # explicit empty
        xml, text = _gen(wt, work_notes="")
        assert "{{work_notes}}" not in xml, f"{wt}: raw token on empty work_notes"
        assert "Notes:" in text, f"{wt}: 'Notes:' label should still be present when blank"

    # omitted entirely — _ensure_value_aliases must still coerce it
    v = _vals("polish")
    v.pop("work_notes", None)
    main._ensure_value_aliases(v, "Direct")
    assert v.get("work_notes") == "", "work_notes must default to empty string"
    out = pw.fill_proposal(work_type="polish", audience="Direct", values=v)
    xml = zipfile.ZipFile(io.BytesIO(out)).read("word/document.xml").decode("utf-8")
    assert "{{work_notes}}" not in xml, "raw token leaked when work_notes omitted"
