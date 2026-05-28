"""
Estimate-sheet writer.

Takes a dict of form values from the frontend, opens Kyle's actual
`estimate sheet - 5.7.xlsx` template (in `templates/`), writes the
typed values into the right input cells, returns the filled workbook
as bytes ready for download.

Kyle's template is the source of truth — we never modify it on disk.
Every call clones it into memory first.

Cell map (input cells per tab) was discovered by inspecting the
workbook with openpyxl. The map is intentionally narrow — only the
cells Troy actually types into. Computed cells (formulas) are left
alone; Excel re-evaluates them when the file is opened.

The mapping is data-driven (one dict per tab) so adding new fields
later means adding rows to the dict, not rewriting logic.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, Mapping

from openpyxl import load_workbook
from openpyxl.workbook import Workbook


TEMPLATE_PATH = (
    Path(__file__).parent / "templates" / "estimate_sheet_5.7.xlsx"
)


# ─── Cell maps per tab ─────────────────────────────────────────────────
# Each entry: form_field_name → (cell_coordinate, value_transformer?)
# Value transformer is optional; identity by default.

EPOXY_CELL_MAP: Dict[str, str] = {
    # Project-level metadata
    "bid_date":          "B2",
    "address":           "B3",
    "local":             "B4",     # "Yes" / "No"
    "prevailing_wage":   "D5",     # "Yes" / "No"
    "taxable":           "B6",     # "Yes" / "No"
    "remodel_tax":       "D6",     # "Yes" / "No"
    "approx_start_date": "B7",
    "architect":         "B8",
    "drawings_dated":    "B9",
    "new_or_reno":       "B10",    # "New" / "Reno"

    # System 1
    "system_1_cost_per_sf": "C18",
    "system_1_sf":          "E20",

    # System 2 (optional add-on epoxy run)
    "system_2_sf":          "E24",

    # Cove
    "cove_1_lf":   "E34",
    "cove_2_lf":   "E37",

    # Discounts / margin
    "discount_overage":   "B41",

    # Labor — Crew 1
    "labor_crew_size":    "A47",
    "labor_days":         "B47",
    "labor_rate":         "C47",

    # Travel
    "travel_hours":       "B52",
    "travel_rate":        "C52",
    "labor_burden_pct":   "C55",

    # Tooling
    "moisture_test_cost":    "C58",
    "tooling_consumables":   "C59",
    "demo_tooling":          "C60",

    # Travel — lodging / food
    "travel_lodging_per_day":  "C65",
    "travel_food_per_day":     "C66",

    # Markup
    "superintendent_pto_pct":  "B75",
    "soft_costs_pct":          "B76",
    "contingency":             "D77",
    "bond":                    "B84",
}

POLISH_CELL_MAP: Dict[str, str] = {
    "local":            "B4",
    "patch_material_sf": "E18",
    "floor_material_lf": "E19",
    "densifier_cost":    "C20",
    "sealer_cost":       "C21",
    "grout_compound_cost": "C22",
    "dye_cost_1":        "C25",
    "apply_dye":         "E25",
    "dye_cost_2":        "C26",
    "joint_filler_qty":  "C29",
    "apply_joint_filler": "E29",
    "remove_existing_jf": "F29",
    "shipping":          "B32",
    "polish_labor_crew_size": "A37",
    "polish_labor_rate":      "C37",
    "mockup_crew":            "A40",
    "mockup_days":            "B40",
    "joint_filler_crew":      "A44",
    "polish_labor_burden_pct": "C47",
    "polish_demo_tooling":   "C52",
    "slurry_hardener_qty":   "C53",
    "plastic_per_lf":        "C54",
    "polish_travel_lodging": "C58",
    "polish_travel_food":    "C59",
    "polish_superintendent_pto_pct": "B69",
    "polish_soft_costs_pct":         "B70",
    "polish_contingency":            "D71",
    "polish_bond":                   "B78",
}

# Computed total cells we surface back to the frontend (read-only).
# Used by /api/compute-estimate to drive Screen 2's live totals.
EPOXY_TOTALS: Dict[str, str] = {
    "material_total":  "D43",
    "labor_install":   "D53",
    "tooling_total":   "D62",
    "travel_total":    "D68",
    "subtotal":        "D70",
    "lump_sum":        "D88",   # final TOTAL after markup + taxes
    "price_per_sf":    "D16",
}

POLISH_TOTALS: Dict[str, str] = {
    "material_total":  "D33",
    "labor_total":     "D45",
    "tooling_total":   "D55",
    "travel_total":    "D61",
    "subtotal":        "D64",
    "lump_sum":        "D82",
    "price_per_sf":    "D15",
}


# ─── Public API ────────────────────────────────────────────────────────
def fill_estimate(values: Mapping[str, Any]) -> bytes:
    """Open the template, write input cells, return filled workbook bytes.

    `values` is a flat dict from the frontend. Keys not present in the
    cell maps are silently ignored — the frontend can send a superset of
    fields without breaking the backend.

    Always writes to BOTH Epoxy and Polish tabs (each map handles its
    own field names with prefixes where they collide). The Combo case
    is implicit — if Troy fills both tabs' fields, both get written.
    """
    wb = load_workbook(TEMPLATE_PATH, keep_vba=False)

    # Epoxy tab
    epoxy = wb["Epoxy"]
    for field, coord in EPOXY_CELL_MAP.items():
        if field in values and values[field] not in (None, ""):
            epoxy[coord] = values[field]

    # Polish tab
    polish = wb["Polish"]
    for field, coord in POLISH_CELL_MAP.items():
        if field in values and values[field] not in (None, ""):
            polish[coord] = values[field]

    # Stream to bytes
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def read_totals(filled_xlsx_bytes: bytes) -> Dict[str, Dict[str, Any]]:
    """Read computed totals back out of a saved-and-reopened workbook.

    NOTE: openpyxl reads CACHED computed values (last time Excel saved).
    A workbook we just filled with openpyxl will have stale cached
    totals — the formulas weren't actually evaluated. Excel evaluates
    on next open.

    So this function is only useful AFTER a workbook has been opened in
    Excel and saved again, OR for previewing totals from a workbook
    Troy filled in Excel and uploaded.

    For Screen 2's live totals we compute totals in Python instead (see
    `compute_estimate_totals` below), so this function is mostly here
    for completeness.
    """
    wb = load_workbook(io.BytesIO(filled_xlsx_bytes), data_only=True)
    out: Dict[str, Dict[str, Any]] = {"epoxy": {}, "polish": {}}
    for name, coord in EPOXY_TOTALS.items():
        out["epoxy"][name] = wb["Epoxy"][coord].value
    for name, coord in POLISH_TOTALS.items():
        out["polish"][name] = wb["Polish"][coord].value
    return out


def compute_estimate_totals(values: Mapping[str, Any]) -> Dict[str, Any]:
    """Pure-Python totals computation for Screen 2's live preview.

    Mirrors the SUM/markup formulas in the workbook, but kept simple —
    this is for the on-screen "running total" only. The authoritative
    totals come from Excel re-evaluating the workbook on open.

    Returns a flat dict (epoxy + polish + combined) for easy frontend
    binding.
    """
    # Epoxy material total = SUM of system 1 + system 2 SF * their cost/SF
    sys1_cost = float(values.get("system_1_cost_per_sf") or 0)
    sys1_sf   = float(values.get("system_1_sf")          or 0)
    sys2_sf   = float(values.get("system_2_sf")          or 0)
    cove_1_lf = float(values.get("cove_1_lf")            or 0)
    cove_2_lf = float(values.get("cove_2_lf")            or 0)

    epoxy_material = (sys1_sf * sys1_cost) + (sys2_sf * sys1_cost) \
                   + ((cove_1_lf + cove_2_lf) * 8.0)  # rough cove $/LF

    epoxy_labor_rate = float(values.get("labor_rate") or 32.20)
    epoxy_crew       = float(values.get("labor_crew_size") or 0)
    epoxy_days       = float(values.get("labor_days") or 0)
    epoxy_labor      = epoxy_crew * epoxy_days * 8 * epoxy_labor_rate
    epoxy_burden     = epoxy_labor * float(values.get("labor_burden_pct") or 0.12)

    epoxy_tooling_per_sf = float(values.get("tooling_consumables") or 0.33)
    epoxy_tooling = (sys1_sf + sys2_sf) * epoxy_tooling_per_sf

    epoxy_subtotal = epoxy_material + epoxy_labor + epoxy_burden + epoxy_tooling

    super_pto = float(values.get("superintendent_pto_pct") or 0.03)
    soft_pct  = float(values.get("soft_costs_pct") or 0.13)
    epoxy_markup = epoxy_subtotal * (super_pto + soft_pct)
    epoxy_lump_sum = round(epoxy_subtotal + epoxy_markup
                           + float(values.get("contingency") or 0)
                           + float(values.get("bond") or 0))

    # Polish material — simpler approximation
    polish_sf       = float(values.get("polish_sf")
                            or values.get("patch_material_sf") or 0)
    polish_dens     = float(values.get("densifier_cost") or 0.07)
    polish_seal     = float(values.get("sealer_cost") or 0.10)
    polish_material = polish_sf * (polish_dens + polish_seal)

    polish_rate = float(values.get("polish_labor_rate") or 32.20)
    polish_crew = float(values.get("polish_labor_crew_size") or 0)
    polish_labor = polish_crew * 8 * polish_rate * 5  # rough: 5 days

    polish_subtotal = polish_material + polish_labor
    polish_lump_sum = round(polish_subtotal * (1 +
        float(values.get("polish_superintendent_pto_pct") or 0.027) +
        float(values.get("polish_soft_costs_pct")         or 0.16)))

    return {
        "epoxy": {
            "material_total": round(epoxy_material),
            "labor_install":  round(epoxy_labor + epoxy_burden),
            "tooling_total":  round(epoxy_tooling),
            "subtotal":       round(epoxy_subtotal),
            "lump_sum":       epoxy_lump_sum,
        },
        "polish": {
            "material_total": round(polish_material),
            "labor_install":  round(polish_labor),
            "subtotal":       round(polish_subtotal),
            "lump_sum":       polish_lump_sum,
        },
        "combined_lump_sum": epoxy_lump_sum + polish_lump_sum,
    }
