"""Proposal Area/SF sourced from the estimate sheet's BASE tab (not just intake).

Bug: the proposal "Area" line read only the intake `system_1_sf` + hardcoded
`Epoxy!E20`, so SF typed on a renamed / copy base tab (or a cove-only intake)
printed "~0 SF". Fix: the frontend snapshots the resolved base tab's SF/cove
cells into `state.sheet_area` + sends the resolved WORK picks as `sheet_systems`;
`_build_epoxy_systems` prefers them; and a cove-only row (0 SF + cove) drops the
"~0 SF of epoxy flooring and " prefix in both the preview and the .docx. Options
never contribute (base only).

Covers:
  (a) JS↔PY parity — AREA_SF_CELLS coords + both JS files carry the base-only
      aggregate helper (drift tripwire);
  (b) _sanitize_sheet_systems coercion;
  (c) _build_epoxy_systems prefers sheet_systems, else the legacy cell reads;
  (d) proposal_writer drops the "~0 SF …" prefix on a cove-only WORK row (real
      template) but keeps a plain 0-SF-no-cove line;
  (e) E2E /api/generate: sheet_systems SF prints; cove-only prints no "~0 SF".
"""
import io
import pathlib
import re

from docx import Document
from fastapi.testclient import TestClient

import main
import proposal_writer as pw

client = TestClient(main.app)

_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
_FE = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js"
_EST_JS = (_FE / "estimate-review.js").read_text(encoding="utf-8")
_PROP_JS = (_FE / "proposal-review.js").read_text(encoding="utf-8")


def _rendered(docx_bytes: bytes) -> str:
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
    v = {
        "job_name": "Area QA", "project_name": "Area QA",
        "city_state": "Olathe, KS", "bid_date_formatted": "6/22/26",
        "system_name": "Treadwell MACRO Flake Single Broadcast", "texture": "Orange Peel",
        "epoxy_sf": "0", "cove_lf": "0",
        "disposal": "a dumpster", "schedule_notes": "~5 days", "scope_notes": "scope",
        "lump_sum_formatted": "$61,162.00", "tax_amount_formatted": "$2,639.00",
        "total_formatted": "$63,801.00", "state_name": "Kansas",
        "base_bid_formatted": "$58,523.00", "material_tax_formatted": "$2,639.00",
        "site_visit_phrase": "per site visit on 6/22/26", "exclusions": "std",
        "estimator_name": "Kyle Loseke",
    }
    v.update(over)
    return v


# ── (a) JS↔PY parity ────────────────────────────────────────────────────
def test_area_sf_cells_map_parity():
    m = re.search(r"const AREA_SF_CELLS = \{(.*?)\};", _EST_JS, re.S)
    assert m, "AREA_SF_CELLS not found in estimate-review.js"
    body = m.group(1)
    for k, cell in (("epoxy_sf", "E20"), ("epoxy_sf_2", "E24"),
                    ("cove_lf", "E34"), ("cove_lf_2", "E37"), ("polish_sf", "E18")):
        assert re.search(rf'{k}\s*:\s*"{cell}"', body), f"{k}:{cell} missing from AREA_SF_CELLS"


def test_base_only_aggregate_helper_in_both_js():
    # The estimate snapshot and the proposal mirror must both carry the base-only
    # aggregate + the sheet-first read, or the two screens drift apart.
    assert "function baseAreaFrom" in _EST_JS and "function baseAreaFrom" in _PROP_JS
    assert "state.sheet_area" in _EST_JS and "state.sheet_area" in _PROP_JS
    assert "sheetFirst" in _PROP_JS       # proposal reads sheet-first w/ intake fallback


# ── (b) _sanitize_sheet_systems ──────────────────────────────────────────
def test_sanitize_sheet_systems_coerces_and_caps():
    out = main._sanitize_sheet_systems([
        {"name": "A", "sf": "1,200", "lf": "200"},
        {"name": "  ", "sf": -5, "lf": None},
        "junk",                                       # non-dict → dropped
        {"name": "B", "sf": 300, "lf": 0},
    ])
    assert out == [
        {"name": "A", "sf": 1200.0, "lf": 200.0},
        {"name": "", "sf": 0.0, "lf": 0.0},           # blank name kept; negative/none floored to 0
        {"name": "B", "sf": 300.0, "lf": 0.0},
    ]
    # cap is applied to the input list (first _SHEET_SYSTEMS_MAX=4 entries)
    assert len(main._sanitize_sheet_systems([{"name": str(i)} for i in range(9)])) == 4
    assert main._sanitize_sheet_systems(None) == []


# ── (c) _build_epoxy_systems source precedence ───────────────────────────
def test_build_systems_prefers_sheet_systems():
    sys = main._build_epoxy_systems({}, _vals(),
                                    [{"name": "Grind & Seal", "sf": 1400, "lf": 0}])
    assert len(sys) == 1
    assert sys[0]["name"] == "Grind & Seal"
    assert sys[0]["sqft"] == "1,400"
    # empty name in a sheet_system falls back to the values' system_name
    sys2 = main._build_epoxy_systems({}, _vals(system_name="Fallback Sys"),
                                     [{"name": "", "sf": 0, "lf": 200}])
    assert sys2[0]["name"] == "Fallback Sys"
    assert sys2[0]["sqft"] == "0"
    assert '200 LF' in sys2[0]["lf_clause"]


def test_build_systems_legacy_cells_when_no_sheet_systems():
    # No sheet_systems → the pre-existing Epoxy! grid-cell reads are unchanged.
    sys = main._build_epoxy_systems(
        {"Epoxy!A22": "Treadwell Epoxy", "Epoxy!E20": "9,000", "Epoxy!E34": "120"},
        _vals(), None)
    assert sys[0]["name"] == "Treadwell Epoxy"
    assert sys[0]["sqft"] == "9,000"
    assert '120 LF' in sys[0]["lf_clause"]
    # [] behaves the same as None
    assert main._build_epoxy_systems({}, _vals(cove_lf="250"), [])[0]["lf_clause"] \
        == main._build_epoxy_systems({}, _vals(cove_lf="250"))[0]["lf_clause"]


# ── (d) writer: cove-only prefix drop (real template) ────────────────────
def test_writer_drops_zero_sf_prefix_when_cove_only():
    systems = main._build_epoxy_systems({}, _vals(epoxy_sf="0", cove_lf="200"),
                                        [{"name": "Cove only", "sf": 0, "lf": 200}])
    blob = _rendered(pw.fill_proposal(work_type="epoxy", audience="Direct",
                                      values=_vals(epoxy_sf="0", cove_lf="200"),
                                      systems=systems))
    assert "~0 SF of epoxy flooring and" not in blob
    assert '200 LF of 6" epoxy cove base' in blob


def test_writer_keeps_zero_sf_line_when_no_cove():
    systems = main._build_epoxy_systems({}, _vals(epoxy_sf="0", cove_lf="0"),
                                        [{"name": "Bare", "sf": 0, "lf": 0}])
    blob = _rendered(pw.fill_proposal(work_type="epoxy", audience="Direct",
                                      values=_vals(epoxy_sf="0", cove_lf="0"),
                                      systems=systems))
    assert "~0 SF of epoxy flooring" in blob     # no cove → today's line kept


# ── (e) E2E /api/generate ────────────────────────────────────────────────
def test_generate_uses_sheet_systems_sf():
    body = {"work_type": "epoxy", "audience": "Direct",
            "values": _vals(epoxy_sf="0"),        # intake/flat SF is 0
            "sheet_systems": [{"name": "System A", "sf": 1400, "lf": 0}]}
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200, r.text
    blob = _rendered(client.get(r.json()["docx_download_url"]).content)
    assert "1,400 SF of epoxy flooring" in blob   # from the base-tab pick, not intake


def test_generate_cove_only_drops_zero_sf():
    body = {"work_type": "epoxy", "audience": "Direct",
            "values": _vals(epoxy_sf="0", cove_lf="200"),
            "sheet_systems": [{"name": "", "sf": 0, "lf": 200}]}
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200, r.text
    blob = _rendered(client.get(r.json()["docx_download_url"]).content)
    assert "~0 SF of epoxy flooring and" not in blob
    assert '200 LF of 6" epoxy cove base' in blob
