"""A field nobody filled in prints nothing, never "0".

`computeTokenValues` (proposal-review.js) ran every narrative field through
`safe = v => (blank ? "0" : v)`, and the backend copies those values straight into the document.
So a blank Texture printed "Texture: 0": 18 of the 29 real proposals on prod on 2026-09-25 carried
`values.texture == "0"`. Viracor went out with "System: 0". The editor's own Work rows read
`String(merged.texture || "")`, so the estimator proofreading the screen saw a blank and the customer
saw a zero. A literal "0" also defeats every `_blank()` backfill in `_ensure_value_aliases`.

Pinned revisions are untouched by this: their payloads already hold "0", and they must keep
printing what the customer was sent. The fix is in what a NEW payload carries.

The first test RUNS the shipped computeTokenValues in Node (tests/js/price-block-harness.js); the
second runs the real `_generate` on the templates that print these tokens.
"""
import io
import json
import pathlib
import shutil
import subprocess

import pytest
from docx import Document
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "price-block-harness.js"
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

TEXT_FIELDS = ("texture", "system_name", "system_name_epoxy", "system_name_polish", "city_state",
               "address", "work_description", "scope_notes", "schedule_notes", "exclusions",
               "bid_date", "site_visit_date")


def _run(cases):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], input=json.dumps(cases),
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return {r["name"]: r for r in json.loads(p.stdout)}


def _case(name, state):
    return {"name": name, "work_type": "epoxy", "audience": "Direct", "tax_inclusion": "INCLUDED",
            "blocks": [], "total": 1000, "sales_tax": 0, "remodel_tax": 0, "state": state}


def test_blank_and_missing_text_fields_carry_no_zero():
    blank = {k: "" for k in TEXT_FIELDS}
    nulls = {k: None for k in TEXT_FIELDS}
    got = _run([_case("blank", blank), _case("null", nulls), _case("missing", {})])
    for name in ("blank", "null", "missing"):
        for k in TEXT_FIELDS:
            v = got[name]["narrative"][k]
            assert v != "0", f"{name}: {k} would print a literal 0"
            assert v in ("", None), (name, k, v)


def test_a_filled_field_is_passed_through_untouched():
    """Including a real zero someone typed on purpose, and an address standing in for the
    work description (the fallback that used to end in "0")."""
    got = _run([_case("filled", {"texture": "Orange Peel", "system_name": "Treadwell MACRO",
                                 "city_state": "Olathe, KS", "address": "1 Main St"}),
                _case("typed-zero", {"texture": "0"})])
    n = got["filled"]["narrative"]
    assert n["texture"] == "Orange Peel"
    assert n["system_name"] == n["system_name_epoxy"] == "Treadwell MACRO"
    assert n["city_state"] == "Olathe, KS"
    assert n["work_description"] == "1 Main St"
    assert got["typed-zero"]["narrative"]["texture"] == "0"


def test_values_carry_the_documents_work_type_not_the_intake_echo():
    """`_ensure_value_aliases` picks the default Scope/Schedule/Exclusions off values.work_type,
    and a blank field now reaches it. An epoxy base tab on a job whose intake said polish must not
    get polish wording."""
    got = _run([_case("echo", {"work_type": "polish", "base_tab_id": "t1",
                               "priced_tabs": [{"id": "t1", "role": "epoxy"}]})])
    assert got["echo"]["narrative"]["work_type"] == "epoxy"


def test_no_dates_at_all_prints_no_site_visit_on_screen_or_in_the_document():
    """With no bid date and no site-visit date the screen says "per plans and specifications
    provided". The header date defaults to TODAY, and the backend used to backfill a blank
    site_visit_date from it, so the document said "per site visit on <today>", a visit nobody
    made. The values the page really sends, straight into the real _generate. (Nothing is added
    to the payload for this: a flag would be written back onto the draft as a ticked box.)"""
    n = _run([_case("nodates", {"bid_date": "", "site_visit_date_display": ""})])["nodates"]["narrative"]
    assert n["site_visit_phrase"] == "per plans and specifications provided"
    assert not n.get("no_site_visit"), "the page must not invent a No-site-visit tick"
    assert n["bid_date_formatted"], "the header date should still default"
    values = {"job_name": "No Dates QA", "project_name": "No Dates QA", "bid_date": n["bid_date"],
              "bid_date_formatted": n["bid_date_formatted"], "site_visit_date": n["site_visit_date"],
              "area_description": "~1,000 sf of epoxy flooring"}
    r = client.post("/api/generate", json={"work_type": "epoxy", "audience": "Direct", "values": values})
    assert r.status_code == 200, r.text
    text = "\n".join(_rendered(client.get(r.json()["docx_download_url"]).content))
    assert "per plans and specifications provided" in text
    assert "per site visit on" not in text


def test_a_real_site_visit_date_still_prints():
    n = _run([_case("visit", {"site_visit_date_display": "9/10/26"})])["visit"]["narrative"]
    assert n["site_visit_phrase"] == "per site visit on 9/10/26"
    assert not n.get("no_site_visit")


def _rendered(docx_bytes):
    d = Document(io.BytesIO(docx_bytes))
    out = []
    for p in d.element.xpath("//w:p"):
        if any(True for _ in p.iterancestors(f"{_MC}Fallback")):
            continue
        t = "".join(x.text or "" for x in p.xpath(".//w:t")).strip()
        if t:
            out.append(t)
    return out


@pytest.mark.parametrize("work_type,audience", [("epoxy", "Direct"), ("combo", "Direct"),
                                                ("polish", "Direct"), ("epoxy", "GC")])
def test_the_document_prints_a_blank_texture_and_system_as_blank(work_type, audience):
    """The backend half: an empty value from the new payload must not come back as a token or a
    zero on the Texture / System rows of any template that prints them."""
    values = {"job_name": "Blank Field QA", "project_name": "Blank Field QA",
              "bid_date_formatted": "9/25/26", "texture": "", "system_name": "",
              "system_name_epoxy": "", "system_name_polish": "", "city_state": "",
              "epoxy_sf": "1,000", "polish_sf": "1,000", "cove_lf": "0", "sqft": "1,000",
              # Always set by the browser (never through `safe`), so a real payload has it.
              "area_description": "~1,000 sf of epoxy flooring"}
    r = client.post("/api/generate", json={"work_type": work_type, "audience": audience,
                                           "values": values})
    assert r.status_code == 200, r.text
    # Split on the labels: several WORK rows share one text-box paragraph in some templates.
    text = "\n".join(_rendered(client.get(r.json()["docx_download_url"]).content))
    seen = 0
    for label in ("Texture:", "System:"):
        for chunk in text.split(label)[1:]:
            seen += 1
            value = chunk.split("\n", 1)[0].split("Area:", 1)[0].split("Texture:", 1)[0].strip()
            assert value != "0" and not value.startswith("0 "), f"{work_type}/{audience}: {label} {value!r}"
            assert "{{" not in value, f"{work_type}/{audience}: raw token after {label} {value!r}"
    assert seen, f"{work_type}/{audience}: no Texture/System row found — the test checked nothing"
