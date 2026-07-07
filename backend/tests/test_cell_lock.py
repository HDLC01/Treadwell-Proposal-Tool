"""Excel sheet-protection on the generated .xlsx (rate/markup/tax cell locking).

fill_estimate must lock exactly the LOCK_MAP cells (GP %, Hard Bid Discount,
Superintendent, Soft Costs, Contingency, Sales Tax %, Kansas Remodel Tax %, Bond)
per sheet layout and leave every other cell editable, with sheet protection ON
(no password) for the lock-mapped sheets and OFF for everything else. Copies
inherit their source's layout; the alternate tab and display-label renames must
not shake the protection loose (it's applied to worksheet objects, post-rename).
"""
import io

from openpyxl import load_workbook

import estimate_writer as ew


def _wb(data):
    return load_workbook(io.BytesIO(data))


def _locked_addrs(ws, addrs):
    return {a: bool(ws[a].protection.locked) for a in addrs}


# ── every lock-mapped template sheet is protected with exactly its set ──
def test_lock_map_sheets_protected_with_correct_cells():
    wb = _wb(ew.fill_estimate({"project_name": "P"}))
    for name, addrs in ew.LOCK_MAP.items():
        sheets = ([s for s in wb.sheetnames if s.lower().startswith("gyp")]
                  if name == "Gyp" else [name])
        assert sheets, f"no sheet found for layout {name!r}"
        for sheet in sheets:
            ws = wb[sheet]
            assert ws.protection.sheet is True, f"{sheet}: protection not enabled"
            assert not ws.protection.password, f"{sheet}: unexpected password"
            got = _locked_addrs(ws, addrs)
            assert all(got.values()), f"{sheet}: unlocked rate cells {got}"


def test_all_other_cells_stay_editable():
    wb = _wb(ew.fill_estimate({"project_name": "P", "sqft": 12000}))
    for sheet, lock_key in (("Epoxy", "Epoxy"), ("Polish", "Polish")):
        ws = wb[sheet]
        locked = set(ew.LOCK_MAP[lock_key])
        # Every cell that actually exists in the file must be explicitly
        # unlocked except the lock-map addrs. (Virgin cells materialized by
        # iter_rows on the RELOADED wb report openpyxl's locked-by-default
        # Protection, but Excel resolves them through the Normal named style —
        # asserted unlocked below — so they're editable in the real app.)
        stray = [c.coordinate for row in ws.iter_rows() for c in row
                 if c.protection.locked and c.coordinate not in locked
                 and (c.value is not None or c.has_style)]
        assert not stray, f"{sheet}: unexpectedly locked {stray[:10]}"


def test_virgin_cells_inherit_unlocked_normal_style():
    # Cells that don't exist in the file (blank rows/columns) inherit the
    # workbook "Normal" style under Excel's protection rules; fill_estimate
    # flips its locked flag off so Kyle can still type in blank cells on a
    # protected sheet. Assert the flag survives the save/load roundtrip.
    wb = _wb(ew.fill_estimate({"project_name": "P"}))
    normal = next(s for s in wb._named_styles if s.name == "Normal")
    assert normal.protection.locked is False


def test_non_lock_sheets_not_protected():
    wb = _wb(ew.fill_estimate({"project_name": "P"}))
    for sheet in ("Takeoff", "Stnd Alts", "validation", "Unit Layouts"):
        assert wb[sheet].protection.sheet is not True, f"{sheet}: should be unprotected"


# ── copies inherit the SOURCE layout ─────────────────────────────────────
def test_copy_inherits_source_lock_layout():
    wb = _wb(ew.fill_estimate({}, tab_copies=[{"id": "Copy1", "source": "Polish"}]))
    ws = wb["Copy1"]
    assert ws.protection.sheet is True
    assert all(_locked_addrs(ws, ew.LOCK_MAP["Polish"]).values())


def test_copy_of_copy_resolves_through_chain():
    wb = _wb(ew.fill_estimate({}, tab_copies=[
        {"id": "Copy1", "source": "Leveling"},
        {"id": "Copy2", "source": "Copy1"},
    ]))
    ws = wb["Copy2"]
    assert ws.protection.sheet is True
    assert all(_locked_addrs(ws, ew.LOCK_MAP["Leveling"]).values())


def test_gyp_copy_uses_gyp_set():
    wb = _wb(ew.fill_estimate({}, tab_copies=[{"id": "GypCopy", "source": 'Gyp (USG 1-8")'}]))
    ws = wb["GypCopy"]
    assert ws.protection.sheet is True
    got = _locked_addrs(ws, ew.LOCK_MAP["Gyp"])
    assert all(got.values()), got
    # Contingency on Gyp is col E, not D — D76 must stay editable.
    assert not ws["D76"].protection.locked


# ── protection survives the renames (alternate tab + display labels) ────
def test_alternate_rename_keeps_protection():
    wb = _wb(ew.fill_estimate({}, alternate={"sf": 9000, "material_sub": 4000,
                                             "label": "MMA alt"}))
    assert "Alternate System" in wb.sheetnames
    ws = wb["Alternate System"]
    assert ws.protection.sheet is True
    assert all(_locked_addrs(ws, ew.LOCK_MAP["Epoxy blank"]).values())


def test_tab_label_rename_keeps_protection():
    wb = _wb(ew.fill_estimate({"project_name": "P"},
                              tab_labels={"Epoxy": "Grooming Room"}))
    ws = wb["Grooming Room"]
    assert ws.protection.sheet is True
    assert all(_locked_addrs(ws, ew.LOCK_MAP["Epoxy"]).values())


def test_renamed_copy_keeps_protection():
    wb = _wb(ew.fill_estimate(
        {"project_name": "P"},
        tab_copies=[{"id": "Copy1", "source": "Epoxy"}],
        tab_labels={"Copy1": "Exam Room"},
    ))
    ws = wb["Exam Room"]
    assert ws.protection.sheet is True
    assert all(_locked_addrs(ws, ew.LOCK_MAP["Epoxy"]).values())


# ── the user's own edits still land in locked cells (tool writes bypass) ─
def test_cell_values_write_into_locked_cell_still_lands():
    # The 🔒-unlock flow on the frontend sends the edit via cell_values; sheet
    # protection guards EXCEL editing only, never the tool's own writes.
    wb = _wb(ew.fill_estimate({}, cell_values={"Epoxy!B75": 0.05}))
    ws = wb["Epoxy"]
    assert ws["B75"].value == 0.05
    assert ws["B75"].protection.locked
    assert ws.protection.sheet is True


def test_frontend_lock_map_parity():
    # The backend LOCK_MAP must mirror frontend/js/estimate-review.js
    # LOCKED_CELLS + GYP_LOCKED — same layouts, same addresses.
    import json
    import pathlib
    import re

    js = (pathlib.Path(__file__).resolve().parents[2]
          / "frontend" / "js" / "estimate-review.js").read_text(encoding="utf-8")
    m = re.search(r"const LOCKED_CELLS = (\{.*?\});", js, re.S)
    assert m, "LOCKED_CELLS not found in estimate-review.js"
    fe = json.loads(re.sub(r",(\s*[}\]])", r"\1", m.group(1)))   # tolerate trailing commas
    g = re.search(r"const GYP_LOCKED = (\[.*?\]);", js, re.S)
    assert g, "GYP_LOCKED not found in estimate-review.js"
    fe["Gyp"] = json.loads(g.group(1))
    assert fe == ew.LOCK_MAP
