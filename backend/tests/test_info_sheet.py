"""Project Info Sheet — the ops hand-off workbook.

Three things are worth pinning here, because each fails silently rather than
loudly:

  1. **The template.** Its dropdowns only survive because
     `prepare_info_sheet_template.py` rebuilt them around defined names. A
     regenerated or hand-edited template that loses them still opens fine, still
     fills, and still downloads — the estimator just gets free-text where the
     market segment should be, and Foundation gets a category nobody can report
     on. The market list in particular is Kyle's, verbatim, typo included.

  2. **The prefill mapping.** A wrong cell here is a plausible-looking number in
     an accounting document. Tax exempt is the sharp edge: the estimate stores
     "is this taxable", the info sheet asks the opposite question.

  3. **What fill refuses to write.** The other four tabs read the Info Sheet
     through formulas, so a stray key landing on B18 or on a label breaks
     Foundation Import and the Invoice, not this page.
"""
import io
import pathlib
import re

import openpyxl
import pytest
from fastapi.testclient import TestClient

import estimate_writer as ew
import info_sheet_writer as isw
import main

client = TestClient(main.app)


def _draft(**data):
    base = {
        "project_name": "Westport Commons", "address": "1200 Main St",
        "city": "Kansas City", "state": "MO", "zip": "64105",
        "audience": "Direct", "work_type": "epoxy",
        "contact_name": "Rita Alvarez", "contact_phone": "816-555-0134",
        "contact_email": "rita@acme.com",
        "system_name": "Treadwell MACRO Flake",
        "proposal_lump_sum": 82496.0,
    }
    base.update(data)
    return {"id": "d1", "owner_email": "kyle@wetreadwell.com", "data": base}


# ── 1. The template ───────────────────────────────────────────────────
def test_every_dropdown_survived_the_template_rebuild():
    """openpyxl drops the master's x14 validations on save. If these six are
    missing, the sheet still works and every picker is silently free-text."""
    drops = isw.read_grid()["dropdowns"]
    for addr in ("B16", "B17", "B19", "B60", "B62", "B59", "B61", "B63", "B64",
                 "B66", "B67", "B68", "F33"):
        assert drops.get(addr), f"{addr} lost its dropdown"
    assert drops["B59"] == ["N", "Y"]


def test_market_segments_are_kyles_list_verbatim():
    """Hanz: do not add, delete or reword the Project Class options. The
    "Industial" typo is in the master and stays until he fixes it there."""
    market = isw.read_grid()["dropdowns"]["B16"]
    assert market[0] == "-Select-"
    assert len(market) == 19
    for segment in ("Animal Care", "Correctional", "Food & Bev Manufacturing",
                    "Industial & Manufacturing", "Multifamily & Sr. Living",
                    "Religious", "Technology"):
        assert segment in market, segment


def test_the_dropdown_source_tab_is_gone_but_the_working_tabs_remain():
    wb = openpyxl.load_workbook(isw.TEMPLATE_PATH)
    assert "Packet " not in wb.sheetnames        # only ever fed the validations
    assert wb["Lists"].sheet_state == "hidden"
    for tab in ("Info Sheet", "SOV", "Foundation Import", "Invoice"):
        assert tab in wb.sheetnames


def test_the_other_tabs_still_read_the_info_sheet():
    """Foundation Import and the Invoice are pure formula mirrors — that is the
    whole reason this tool only writes one tab."""
    wb = openpyxl.load_workbook(isw.TEMPLATE_PATH)
    assert wb["Foundation Import"]["A1"].value == "='Info Sheet'!B14"   # job no.
    assert wb["Foundation Import"]["E1"].value == "='Info Sheet'!B57"   # contract
    assert wb["Invoice"]["C14"].value == "='Info Sheet'!B15"            # project


def test_derived_cells_are_marked_read_only():
    cells = {c["addr"]: c for c in isw.read_grid()["cells"]}
    for addr in ("B18", "F21", "B65", "B69", "B71"):
        assert cells[addr].get("readOnly"), f"{addr} is editable"
    assert not cells["B15"].get("readOnly")     # project name is typed


# ── 1b. Where the cost figures come from ──────────────────────────────
_JS = (pathlib.Path(__file__).resolve().parents[2]
       / "frontend" / "js" / "estimate-review.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("layout,sheet", [
    ("Epoxy", "Epoxy"), ("Polish", "Polish"), ("Gyp", 'Gyp (USG 1-8")'),
])
def test_the_cost_cells_are_the_ones_the_estimate_sheet_labels(layout, sheet):
    """B58 and I58 are read off the estimate via `state.cost_snapshot`, which
    snapshots two cells per layout. Kyle labels both on the sheet, one column to
    the right — so assert against his label rather than trusting a coordinate
    that was transcribed by hand and would otherwise fail as a plausible number.
    """
    # Scope to TOTAL_CELLS — AREA_SF_CELLS earlier in the file has its own
    # `Epoxy: {…}` and would match first.
    totals = re.search(r"const TOTAL_CELLS = \{(.*?)\n\};", _JS, re.S).group(1)
    block = re.search(rf"^\s*{layout}:\s*\{{(.*?)\}}", totals, re.S | re.M).group(1)
    coords = dict(re.findall(r'(\w+):\s*"([A-Z]+\d+)"', block))
    ws = openpyxl.load_workbook(ew.TEMPLATE_PATH)[sheet]

    def label_beside(addr):
        col, row = re.match(r"([A-Z]+)(\d+)", addr).groups()
        return str(ws[f"{chr(ord(col) + 1)}{row}"].value or "")

    assert 'Estimated Costs" w/taxes + fees' in label_beside(coords["costs"])
    assert "Man Hour Budget" in label_beside(coords["man_hours"])


# ── 2. The prefill ────────────────────────────────────────────────────
def test_fills_the_project_and_contact_block():
    pf = isw.build_prefill(_draft())
    assert pf["B13"] == "Kyle"                  # no estimator_name yet
    assert pf["B15"] == "Westport Commons"
    assert pf["B19"] == "MO - Missouri"
    assert (pf["B20"], pf["B21"], pf["D21"]) == ("1200 Main St", "Kansas City", "64105")
    assert pf["B25"] == "Kansas City, MO 64105"
    assert (pf["B29"], pf["B30"], pf["B31"]) == ("Rita Alvarez", "816-555-0134", "rita@acme.com")
    assert pf["B57"] == 82496.0


def test_a_typed_estimator_name_beats_the_account_it_was_saved_under():
    pf = isw.build_prefill(_draft(estimator_name="Troy Holmes"))
    assert pf["B13"] == "Troy Holmes"


def test_an_autopilot_draft_has_no_estimator_yet():
    """The lead autopilot creates drafts before anyone owns them. Printing
    "Autopilot" in the Estimator / Sales Rep box reads as a person's name on a
    document accounting files."""
    d = {"owner_email": "autopilot", "data": _draft()["data"]}
    assert "B13" not in isw.build_prefill(d)


def test_gc_jobs_bill_the_contractor_direct_jobs_bill_the_owner():
    assert isw.build_prefill(_draft())["B23"] == "Westport Commons"
    gc = isw.build_prefill(_draft(audience="GC", architect="Titan Construction"))
    assert gc["B23"] == "Titan Construction"


def test_tax_exempt_is_the_inverse_of_the_estimates_taxable_flag():
    """The estimate asks "Taxable?"; the info sheet asks "Tax Exempt?". Getting
    this backwards tells accounting to chase a certificate on a taxable job, or
    to charge tax on an exempt one."""
    taxed = isw.build_prefill(_draft(cell_values={"Epoxy!B6": "Yes"}))
    assert taxed["B66"] == "N"
    exempt = isw.build_prefill(_draft(cell_values={"Epoxy!B6": "No"}))
    assert exempt["B66"] == "Y"


def test_prevailing_wage_and_remodel_tax_carry_across():
    pf = isw.build_prefill(_draft(cell_values={"Epoxy!D5": "Yes", "Epoxy!D6": "Yes"}))
    assert pf["B63"] == "Y" and pf["B67"] == "Y"


def test_an_untouched_flag_leaves_the_templates_default_alone():
    pf = isw.build_prefill(_draft())
    for addr in ("B63", "B66", "B67"):
        assert addr not in pf


def test_gyp_reads_its_own_taxable_cell_and_falls_back_to_epoxy():
    """The gyp layout sits two rows lower and keeps its own Taxable cell, but
    mirrors Prevailing Wage off epoxy by formula — so an unset gyp key legitimately
    falls through rather than reading the wrong row."""
    gyp = _draft(work_type="gyp", cell_values={
        'Gyp (USG 1-8")!B8': "No",     # its own
        "Epoxy!D5": "Yes",             # mirrored
    })
    pf = isw.build_prefill(gyp)
    assert pf["B66"] == "Y"            # exempt
    assert pf["B63"] == "Y"            # prevailing wage found on epoxy
    assert pf["B17"] == "Gypsum Cement Underlayment"


@pytest.mark.parametrize("system,expected", [
    ("Treadwell MACRO Flake", "Epoxy - Flake"),
    ("Treadwell Decorative Quartz", "Epoxy - Quartz"),
    ("Treadwell Poly-Crete SLB", "Epoxy - Urethane Cement"),
    # A hybrid flake system is a urethane-cement floor — the urethane test has
    # to win over the flake one, which is why the match order is fixed.
    ("Flake with hybrid blend, no base", "Epoxy - Urethane Cement"),
    ("Something we have never installed", ""),
])
def test_primary_floor_is_read_off_the_system(system, expected):
    assert isw.build_prefill(_draft(system_name=system)).get("B17", "") == expected


def test_polish_variants_are_matched_too():
    pf = isw.build_prefill(_draft(work_type="polish", system_name="Polished Concrete, Salt & Pepper"))
    assert pf["B17"] == "Polish - S&P"


def test_the_designated_base_tab_beats_the_intake_work_type():
    """The estimator can price several tabs and nominate one. The hand-off has to
    describe the bid that was actually sent."""
    d = _draft(work_type="epoxy", base_tab_id="polish-2",
               system_name="Polished Concrete - Cream",
               priced_tabs=[{"id": "Epoxy", "kind": "base", "role": "epoxy"},
                            {"id": "polish-2", "role": "polish"}])
    assert isw.build_prefill(d)["B17"] == "Polish - Cream"


def test_areas_come_from_the_sheet_and_fall_back_to_intake():
    sheet = isw.build_prefill(_draft(
        sheet_area={"epoxy_sf": 8000, "epoxy_sf_2": 386, "cove_lf": 120}))
    assert sheet["B42"] == 8386 and sheet["D42"] == 120
    # A draft saved before the sheet snapshot existed still gets its takeoff.
    old = isw.build_prefill(_draft(system_1_sf=5000, cove_1_lf=40))
    assert old["B42"] == 5000 and old["D42"] == 40


def test_a_combo_job_fills_the_sheets_second_system_block():
    """Epoxy + polish prices two base tabs. Only one can be block one, so the
    other has to land in rows 45-49 or it never reaches the hand-off."""
    d = _draft(work_type="combo", system_name="Treadwell MACRO Flake",
               sheet_area={"epoxy_sf": 8000, "cove_lf": 120},
               priced_tabs=[
                   {"id": "Epoxy", "kind": "base", "role": "epoxy",
                    "sf": {"epoxy_sf": 8000, "cove_lf": 120}},
                   {"id": "Polish", "kind": "base", "role": "polish",
                    "system_desc": "Treadwell Polished Concrete",
                    "sf": {"polish_sf": 4200}},
               ])
    pf = isw.build_prefill(d)
    assert (pf["B40"], pf["B42"], pf["D42"]) == ("Treadwell MACRO Flake", 8000, 120)
    assert (pf["B46"], pf["B48"]) == ("Treadwell Polished Concrete", 4200)


def test_a_single_system_job_leaves_the_second_block_empty():
    pf = isw.build_prefill(_draft(sheet_area={"epoxy_sf": 8000}))
    for addr in ("B46", "B48", "D48"):
        assert addr not in pf


def test_cove_is_not_reported_against_a_polish_floor():
    """Cove base belongs to the resin systems; carrying an epoxy tab's LF onto a
    polish-only hand-off would have ops order material for work nobody bid."""
    pf = isw.build_prefill(_draft(work_type="polish",
                                  sheet_area={"polish_sf": 4200, "cove_lf": 120}))
    assert pf["B42"] == 4200 and "D42" not in pf


def test_costs_and_man_hours_come_from_the_snapshot_and_are_optional():
    filled = isw.build_prefill(_draft(cost_snapshot={"costs": 49614, "man_hours": 392}))
    assert filled["B58"] == 49614 and filled["I58"] == 392
    bare = isw.build_prefill(_draft())
    assert "B58" not in bare and "I58" not in bare


def test_deposit_answers_the_portal_not_the_draft():
    assert isw.build_prefill(_draft(), deposit_requested=True)["B59"] == "Y"
    assert isw.build_prefill(_draft())["B59"] == "N"


def test_an_unknown_lead_source_clears_the_templates_guess():
    """The template ships "Repeat Customer". Left alone it would be reported out
    of Foundation as though someone had chosen it."""
    assert isw.build_prefill(_draft(source="google_lead"))["B62"] == "Online"
    assert isw.build_prefill(_draft(source="email"))["B62"] == ""
    assert isw.build_prefill(_draft())["B62"] == ""


def test_nothing_pink_is_prefilled():
    """Market, payment terms, retainage, CCIP and the transition note are the
    estimator's call — Manufacturer and Color/Blend too, per Hanz."""
    pf = isw.build_prefill(_draft(cost_snapshot={"costs": 1, "man_hours": 1},
                                  cell_values={"Epoxy!B6": "Yes"}))
    for addr in ("B16", "B39", "B41", "B43", "B60", "B61", "B68", "B70"):
        assert addr not in pf, f"{addr} should be left blank"


# ── 3. Fill ───────────────────────────────────────────────────────────
def _filled(prefill, overrides=None):
    return openpyxl.load_workbook(
        io.BytesIO(isw.fill_info_sheet(prefill, overrides)))["Info Sheet"]


def test_what_the_estimator_typed_beats_the_prefill():
    ws = _filled({"B15": "Westport Commons"}, {"Info Sheet!B15": "Westport Commons Ph2"})
    assert ws["B15"].value == "Westport Commons Ph2"


def test_clearing_a_cell_clears_it():
    ws = _filled({"B62": "Online"}, {"Info Sheet!B62": ""})
    assert ws["B62"].value is None


def test_the_job_number_stays_text():
    """"26.100" cast to a float is 26.1, and B14 is what the Invoice tab and
    Foundation Import both print."""
    ws = _filled({"B14": "26.100"})
    assert ws["B14"].value == "26.100"


def test_derived_cells_and_labels_are_never_written():
    ws = _filled({}, {"Info Sheet!B18": "Epoxy - Commercial",   # derived
                      "Info Sheet!A15": "hacked",              # a label
                      "Info Sheet!B71": "N/A"})                # derived
    assert str(ws["B18"].value).startswith("=IF(")
    assert ws["A15"].value == "Project Name (Description):"
    assert str(ws["B71"].value).startswith("=IF(")


def test_a_typed_formula_trigger_is_neutralized():
    ws = _filled({}, {"Info Sheet!B15": "=cmd|'/c calc'!A0",
                      "Info Sheet!B14": "@SUM(1,1)"})
    assert str(ws["B15"].value).startswith("'=")
    assert str(ws["B14"].value).startswith("'@")


def test_the_download_keeps_its_dropdowns_and_its_other_tabs():
    wb = openpyxl.load_workbook(io.BytesIO(isw.fill_info_sheet({"B15": "Westport"})))
    assert wb.sheetnames == ["Info Sheet", "SOV", "Foundation Import",
                             "Invoice", "Deposit", "Lists"]
    assert len(wb["Info Sheet"].data_validations.dataValidation) == 7
    assert "MarketList" in wb.defined_names


# ── The endpoints ─────────────────────────────────────────────────────
@pytest.fixture
def one_draft(monkeypatch):
    """A saved draft, a portal that says no deposit, and a capture of any
    write-back so the job-number mirror can be asserted."""
    saved = {}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: _draft() if i == "d1" else None)
    monkeypatch.setattr(main.drafts, "save_draft",
                        lambda i, d, **kw: saved.update(id=i, data=d))
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **kw: None)
    monkeypatch.setattr(main, "_portal", lambda *a, **kw: {"proposals": []})
    return saved


def test_get_returns_the_grid_and_the_prefill(one_draft):
    body = client.get("/api/info-sheet/d1").json()
    assert body["grid"]["sheet"] == "Info Sheet"
    assert body["prefill"]["B15"] == "Westport Commons"
    assert body["template_version"]


def test_get_404s_on_an_unknown_draft(one_draft):
    assert client.get("/api/info-sheet/nope").status_code == 404


def test_generate_returns_a_download_and_mirrors_the_job_number(one_draft, monkeypatch):
    """`job_number` is typed here for the first time anywhere in the tool, and
    the deposit invoice already reads it off the draft."""
    d = _draft(info_cell_values={"Info Sheet!B14": "26.153"})
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: d)
    r = client.post("/api/info-sheet/generate", json={"draft_id": "d1"})
    assert r.status_code == 200
    url = r.json()["xlsx_download_url"]
    assert client.get(url).status_code == 200
    assert one_draft["data"]["job_number"] == "26.153"


def test_generate_survives_an_unreachable_portal(one_draft, monkeypatch):
    """Deposits live in the portal. A bad minute there must not stop the
    hand-off sheet — the estimator can set B59 themselves."""
    monkeypatch.setattr(main, "_portal", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("down")))
    assert client.post("/api/info-sheet/generate", json={"draft_id": "d1"}).status_code == 200


def test_a_requested_deposit_reaches_the_sheet(one_draft, monkeypatch):
    monkeypatch.setattr(main, "_portal", lambda *a, **kw: {"proposals": [
        {"proposal_id": "d1", "deposit_requested_at": "2026-07-27T10:00:00Z"}]})
    assert client.get("/api/info-sheet/d1").json()["prefill"]["B59"] == "Y"
