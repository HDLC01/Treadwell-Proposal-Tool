"""Kyle's proposal-feedback fixes — one test per note, asserting the CORRECTED
behavior on the REAL generation path so we prove each fix actually landed (not
just that some code exists).

Maps 1:1 to Kyle's notes:
  #1 exclusions you edit carry into the Word doc          (was hardcoded in the template)
  #2 the tax line reads "Remodel Tax" (no state name)     (was "Missouri/Kansas Remodel Tax")
  #3 tax-exempt jobs print "(tax exempt)"
  #4 no-site-visit jobs read "per plans and specifications provided"  (was "per site visit on N/A")
  #5 cove base height is noted in the WORK description
  #6 the NOTES section is editable per job                (else falls back to standard boilerplate)

#1/#2/#5/#6 exercise proposal_writer.fill_proposal against the real Direct
templates. #3/#4 are computed in main.api_generate, so they go through the real
/api/generate endpoint and download the generated .docx (conftest bypasses auth;
no X-Project-Id => no DB write).
"""
import io

from docx import Document
from fastapi.testclient import TestClient

import main
import proposal_writer as pw

client = TestClient(main.app)

_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


def _rendered(docx_bytes: bytes) -> str:
    """Visible text Word renders (the mc:Choice copy), skipping mc:Fallback dupes."""
    d = Document(io.BytesIO(docx_bytes))
    out = []
    for p in d.element.xpath("//w:p"):
        if any(True for _ in p.iterancestors(f"{_MC}Fallback")):
            continue
        t = "".join(x.text or "" for x in p.xpath(".//w:t")).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def _vals(**over):
    """A minimal-but-complete epoxy value dict, mirroring what Screen 3 sends."""
    v = {
        "job_name": "Kyle QA", "project_name": "Kyle QA",
        "city_state": "Olathe, KS", "bid_date_formatted": "6/22/26",
        "system_name": "Treadwell MACRO Flake Single Broadcast", "texture": "Orange Peel",
        "epoxy_sf": "12,000", "cove_lf": "250",
        "disposal": "a dumpster", "schedule_notes": "~5 days",
        "scope_notes": "demo + install scope",
        "lump_sum_formatted": "$61,162.00", "tax_amount_formatted": "$2,639.00",
        "total_formatted": "$63,801.00", "state_name": "Kansas",
        "base_bid_formatted": "$58,523.00", "material_tax_formatted": "$2,639.00",
        "estimator_name": "Kyle Loseke",
    }
    v.update(over)
    return v


def _generate_doc(values, **payload_over):
    """Drive the real /api/generate endpoint and return the rendered .docx text.
    Exercises main.py's phrase computation (tax-exempt + site-visit), not just
    template rendering."""
    body = {"work_type": "epoxy", "audience": "Direct", "values": values}
    body.update(payload_over)
    r = client.post("/api/generate", json=body)          # no X-Project-Id => no DB save
    assert r.status_code == 200, r.text
    f = client.get(r.json()["docx_download_url"])
    assert f.status_code == 200, f.text
    return _rendered(f.content)


# ── #1 exclusions you edit carry into the doc ──────────────────────────
def test_kyle1_exclusions_carry_into_doc():
    """Kyle's "existing floor demo" edit didn't carry over — exclusions were
    hardcoded in the template. They're now a {{exclusions}} token, so whatever
    the estimator types must appear (and a different edit must NOT bleed through)."""
    edited = "EXISTING FLOOR DEMO ONLY - Kyle edit"
    blob = _rendered(pw.fill_proposal(
        work_type="epoxy", audience="Direct",
        values=_vals(exclusions=edited,
                     base_tax_phrase="(material sales tax INCLUDED)",
                     site_visit_phrase="per site visit on 6/22/26")))
    assert edited in blob

    other = "No demo - owner removes flooring"
    blob2 = _rendered(pw.fill_proposal(
        work_type="epoxy", audience="Direct",
        values=_vals(exclusions=other,
                     base_tax_phrase="(material sales tax INCLUDED)",
                     site_visit_phrase="per site visit on 6/22/26")))
    assert other in blob2 and edited not in blob2     # value-driven, not pinned


# ── #2 tax line reads "Remodel Tax" (no state name) ────────────────────
def test_kyle2_remodel_tax_label_has_no_state_name():
    """The itemized tax line must read just "Remodel Tax" — never prefixed with a
    state name (Kyle: "missouri tax should be labeled as just remodel tax")."""
    blob = _rendered(pw.fill_proposal(
        work_type="epoxy", audience="Direct",
        values=_vals(base_tax_phrase="(Remodel Tax AND material sales tax INCLUDED)",
                     site_visit_phrase="per site visit on 6/22/26", exclusions="standard"),
        remodel=[{"amount_formatted": "$2,639.00"}]))
    assert "Remodel Tax" in blob
    assert "Missouri Remodel Tax" not in blob
    assert "Kansas Remodel Tax" not in blob


# ── #3 tax-exempt jobs print "(tax exempt)" — end-to-end ───────────────
def test_kyle3_tax_exempt_phrase_end_to_end():
    """A tax-exempt job (tax_inclusion in the exempt set) prints "(tax exempt)";
    a taxable one prints the included-tax phrasing. Computed in api_generate."""
    exempt = _generate_doc(_vals(tax_inclusion="EXEMPT"))
    assert "(tax exempt)" in exempt
    assert "(material sales tax INCLUDED)" not in exempt

    taxable = _generate_doc(_vals(tax_inclusion="INCLUDED"))
    assert "(tax exempt)" not in taxable
    assert "(material sales tax INCLUDED)" in taxable


# ── #4 no-site-visit reads "per plans and specifications provided" ─────
def test_kyle4_no_site_visit_phrase_end_to_end():
    """No site visit (explicit toggle, or blank / N/A date) reads "per plans and
    specifications provided" — never "per site visit on N/A". A real date is kept."""
    nov = _generate_doc(_vals(no_site_visit=True, site_visit_date="N/A"))
    assert "per plans and specifications provided" in nov
    assert "per site visit on N/A" not in nov

    visited = _generate_doc(_vals(site_visit_date="6/22/26"))
    assert "per site visit on 6/22/26" in visited


# ── #5 cove base height noted in WORK description ──────────────────────
def test_kyle5_cove_height_in_work_line():
    """The WORK line notes the cove base height — default 6", configurable per job —
    and the chosen height renders into the actual proposal."""
    sys6 = main._build_epoxy_systems({}, _vals(cove_lf="250"))
    assert any('6" epoxy cove base' in s["lf_clause"] for s in sys6)

    sys4 = main._build_epoxy_systems({}, _vals(cove_lf="250", cove_height="4"))
    assert any('4" epoxy cove base' in s["lf_clause"] for s in sys4)

    blob = _rendered(pw.fill_proposal(
        work_type="epoxy", audience="Direct",
        values=_vals(base_tax_phrase="(material sales tax INCLUDED)",
                     site_visit_phrase="per site visit on 6/22/26", exclusions="x"),
        systems=sys4))
    assert '4" epoxy cove base' in blob


# ── #6 NOTES section editable per job ──────────────────────────────────
def test_kyle6_notes_editable_else_default():
    """The estimator's edited notes win; a blank list falls back to the standard
    per-work-type boilerplate so the notes section never vanishes."""
    custom = main._notes_for("epoxy", ["Crew on site 7am", "Owner clears the floor"])
    assert custom == [{"text": "Crew on site 7am"}, {"text": "Owner clears the floor"}]

    default = main._notes_for("epoxy", [])
    assert default and all("text" in n for n in default)   # non-empty boilerplate

    blob = _rendered(pw.fill_proposal(
        work_type="epoxy", audience="Direct",
        values=_vals(base_tax_phrase="(material sales tax INCLUDED)",
                     site_visit_phrase="per site visit on 6/22/26", exclusions="x"),
        notes=[{"text": "Crew on site 7am"}]))
    assert "Crew on site 7am" in blob
