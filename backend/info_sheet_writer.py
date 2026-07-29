"""Project Info Sheet — the ops hand-off workbook.

When a bid turns into a job, someone re-types everything the estimate already
knows into Kyle's `$Project Info Sheet`: who sold it, where it is, who to call,
the contract amount, the tax flags. Accounting then imports a row of it into
Foundation and bills off the Invoice tab. This module fills the parts we can
already answer and leaves the judgement calls to a human.

Two colours drive the whole design, taken from a completed sheet (FBC Oak
Grove) that Hanz marked up:

  * **chartreuse** — data the tool already holds. Prefilled here.
  * **pink** — a decision (market segment, payment terms, retainage). Left
    empty on purpose, but the dropdown has to work, which is the awkward part
    (see `prepare_info_sheet_template.py`).

Everything the estimator changes in the browser is stored per draft as
`data.info_cell_values`, keyed `"Info Sheet!B14"`, and layered over the prefill
at download time — an edit always wins, and it survives a re-download.

Only the Info Sheet is written. `Foundation Import`, `Invoice` and `Deposit`
populate themselves from it through their own cross-sheet formulas, so touching
them would just break the links.

The grid reader and value coercion are imported from `estimate_writer` rather
than copied: those helpers are pure (they take a cell, not a workbook), and the
`_coerce` path in particular carries the formula-injection defence that any cell
fed from an API needs.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

import openpyxl

import leads
from estimate_writer import (
    _coerce,
    _fill_hex,
    _font_color,
    _normalize_cell_value,
    _serialize_cell,
)

log = logging.getLogger("proposal_tool.info_sheet")

TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "project_info_sheet.xlsx"
SHEET = "Info Sheet"

_WB_CACHE: Dict[str, tuple[float, Any]] = {}
_GRID_CACHE: Dict[float, Dict[str, Any]] = {}


# ─── The template's own formulas ───────────────────────────────────────
# Derived cells. The estimator sees their live result in the grid but cannot
# type over them: overwriting one silently breaks a downstream tab (B65 feeds
# payroll, B69 feeds the workers'-comp state, the C column prints the
# accounting instructions people act on).
READ_ONLY = frozenset({
    "B18",   # Division, derived from Primary Floor
    "F21",   # State, mirrors B19
    "B65",   # Payroll Tax Group (KC/MO special case)
    "B69",   # Workers' Comp State
    "B71",   # Risk Management Plan (required over $149k)
    "C59", "C61", "C62", "C63", "C66", "C67", "C68", "G63",   # action prompts
})


# ─── Where each answer comes from ──────────────────────────────────────
# The estimate sheet's tax/wage flags live in the project-info block, whose
# rows differ per layout: gyp sits two rows lower than epoxy and keeps its own
# Taxable cell. Polish mirrors epoxy by formula, so it reads from epoxy.
_FLAG_CELLS = {
    #                    epoxy   gyp
    "prevailing_wage":  ("D5",  "D7"),
    "taxable":          ("B6",  "B8"),
    "remodel_tax":      ("D6",  "D8"),
}
_GYP_BASE = 'Gyp (USG 1-8")'

_STATES = {
    "KS": "KS - Kansas", "MO": "MO - Missouri", "OK": "OK - Oklahoma",
    "NE": "NE - Nebraska", "IA": "IA - Iowa", "AR": "AR - Arkansas",
    "IL": "IL - Illinois",
}

# `data.source` (the intake "How did they find us?" picker) → the Lead Source
# dropdown. Deliberately partial: intake's "referral" does not say whether it
# came from a partner, a past customer or a supplier, and a bid invite off
# BasisBoard is not any of the listed sources. Anything unmapped clears the
# cell rather than keeping the template's "Repeat Customer" default — a guessed
# lead source gets reported out of Foundation as if it were fact.
_LEAD_SOURCES = {
    "google_lead": "Online",
    "referral": "Referral - Other",
    "other": "Other",
    "treadwell_vehicle": "Other",
}

# Primary Floor, matched against the system names the estimator picked on the
# sheet. Order matters: a hybrid flake system ("Flake with hybrid blend") is a
# urethane-cement floor, so the urethane test has to run before the flake one.
_FLOORS = [
    (("urethane", "poly-crete", "polycrete", "hybri"), "Epoxy - Urethane Cement"),
    (("quartz",), "Epoxy - Quartz"),
    (("flake",), "Epoxy - Flake"),
]
_POLISH_FLOORS = [
    (("large aggregate", "aggregate"), "Polish - Large Aggregate"),
    (("s&p", "salt", "pepper"), "Polish - S&P"),
    (("cream",), "Polish - Cream"),
]


# ─── Template access ───────────────────────────────────────────────────
def _load(*, data_only: bool):
    key = f"data_only={data_only}"
    mtime = TEMPLATE_PATH.stat().st_mtime
    hit = _WB_CACHE.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    wb = openpyxl.load_workbook(TEMPLATE_PATH, data_only=data_only)
    _WB_CACHE[key] = (mtime, wb)
    return wb


def template_version() -> str:
    """ETag seed — changes whenever the committed template is replaced."""
    return str(TEMPLATE_PATH.stat().st_mtime_ns)


def _named_range_options(wb, formula: str) -> list[str]:
    """Resolve a validation's `formula1` into its option strings.

    Every dropdown on this sheet except F33 points at a workbook-level name
    (`MarketList`, `YNList`, …) that resolves to a column on the hidden `Lists`
    tab. That indirection is not decoration — it is the only construction that
    both openpyxl and every Excel version round-trip for a cross-sheet list.
    """
    name = formula.lstrip("=").strip()
    defn = wb.defined_names.get(name)
    if defn is None:
        return []
    opts: list[str] = []
    for sheet_name, ref in defn.destinations:
        if sheet_name not in wb.sheetnames:
            continue
        cells = wb[sheet_name][ref.replace("$", "")]
        if not isinstance(cells, tuple):
            cells = ((cells,),)
        elif cells and not isinstance(cells[0], tuple):
            cells = (cells,)
        for row in cells:
            for cell in row:
                if cell.value is not None and str(cell.value).strip():
                    opts.append(str(cell.value))
    return opts


def read_grid() -> Dict[str, Any]:
    """The Info Sheet as the JSON the grid UI renders.

    Same shape as `estimate_writer.read_sheet_grid` so the frontend can reuse
    the estimate grid's rendering rules, plus `readOnly` — this sheet is mostly
    labels and derived cells, and marking them server-side keeps the client
    from having to know which is which.
    """
    mtime = TEMPLATE_PATH.stat().st_mtime
    if mtime in _GRID_CACHE:
        return _GRID_CACHE[mtime]

    wb = _load(data_only=False)
    ws = wb[SHEET]
    ws_vals = _load(data_only=True)[SHEET]

    merged, merged_inner = [], set()
    for mr in ws.merged_cells.ranges:
        anchor = mr.coord.split(":")[0]
        merged.append({
            "anchor": anchor, "range": mr.coord,
            "minRow": mr.min_row, "maxRow": mr.max_row,
            "minCol": mr.min_col, "maxCol": mr.max_col,
            "rowSpan": mr.max_row - mr.min_row + 1,
            "colSpan": mr.max_col - mr.min_col + 1,
        })
        for row in ws[mr.coord]:
            for cell in row:
                if cell.coordinate != anchor:
                    merged_inner.add(cell.coordinate)

    cells: list[Dict[str, Any]] = []
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            if cell.coordinate in merged_inner:
                continue
            value = cell.value
            fill_hex = _fill_hex(cell)
            is_formula = isinstance(value, str) and value.startswith("=")
            # Skip the blank filler, but never an input cell: the template ships
            # most of them empty, and dropping them would take their number
            # format with them — the contract amount would render as 82496
            # instead of $82,496.00.
            if (value is None and not fill_hex and not cell.font.bold
                    and cell.coordinate not in EDITABLE):
                continue
            if is_formula:
                cached = ws_vals[cell.coordinate].value
                display = None if (cached is None or (
                    isinstance(cached, str) and cached.startswith("="))) else cached
            else:
                display = value
            out = _serialize_cell(
                cell, display_value=_normalize_cell_value(display),
                is_formula=is_formula, fill_hex=fill_hex,
                font_color=_font_color(cell),
            )
            if is_formula:
                # The estimate grid hands formulas to HyperFormula so they
                # recalculate live; same here, so B18/B65/B71 react as the
                # estimator types. Editing them is still blocked.
                out["readOnly"] = True
            cells.append(out)

    dropdowns: Dict[str, list[str]] = {}
    for dv in ws.data_validations.dataValidation:
        if dv.type != "list" or not dv.formula1:
            continue
        f = dv.formula1.strip()
        opts = ([s.strip() for s in f.strip('"').split(",")]
                if f.startswith('"') and f.endswith('"')
                else _named_range_options(wb, f))
        if not opts:
            log.warning("info sheet: dropdown %s resolved to nothing", f)
            continue
        for rng in dv.sqref.ranges:
            got = ws[rng.coord]
            if not isinstance(got, tuple):
                got = ((got,),)
            elif got and not isinstance(got[0], tuple):
                got = (got,)
            for r in got:
                for cell in r:
                    dropdowns[cell.coordinate] = opts

    by_addr = {c["addr"]: c for c in cells}
    for addr in READ_ONLY:
        if addr in by_addr:
            by_addr[addr]["readOnly"] = True

    result = {
        "sheet": SHEET,
        "max_row": ws.max_row,
        "max_col": ws.max_column,
        "cells": cells,
        "merged": merged,
        "col_widths": {k: v.width for k, v in ws.column_dimensions.items() if v.width},
        "row_heights": {int(k): v.height for k, v in ws.row_dimensions.items() if v.height},
        "dropdowns": dropdowns,
        "editable": sorted(EDITABLE),
        # The browser has to know these too: it parses what the estimator types
        # before sending it, so "26.100" would arrive here as the number 26.1 and
        # no server-side guard could get the trailing zero back.
        "text_cells": sorted(TEXT_CELLS),
    }
    _GRID_CACHE[mtime] = result
    return result


# ─── Prefill ───────────────────────────────────────────────────────────
def _txt(v) -> str:
    return "" if v is None else str(v).strip()


def _num(v) -> Optional[float]:
    try:
        n = float(str(v).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None
    return n


def _yn(v) -> str:
    return "Y" if str(v).strip().lower() in ("yes", "y", "true", "1") else "N"


def _person(email: str) -> str:
    """"kyle@wetreadwell.com" → "Kyle". The same shorthand the CRM board and
    the Projects list show; real full names live in `profiles`, which this
    service does not read.

    A draft the lead autopilot created has no human owner yet — printing
    "Autopilot" as the Estimator / Sales Rep on an accounting document would
    read as a name. Blank, so whoever picks the job up fills it in.
    """
    local = (email or "").split("@")[0]
    if local.strip().lower() == leads.AUTOPILOT_ACTOR:
        return ""
    return " ".join(p.capitalize() for p in re.split(r"[._-]+", local) if p)


def _base_role(data: Dict[str, Any]) -> str:
    """Which layout the bid was priced on.

    The estimator's nominated base tab wins. Failing that, `work_type` decides —
    NOT "the first base-kind tab". On real drafts every priced tab carries
    `kind: "base"` (all seven of them, including the five gyp variants nobody
    priced), so picking the first would answer "epoxy" for every job.
    """
    tabs = [t for t in (data.get("priced_tabs") or []) if isinstance(t, dict)]
    base_id = data.get("base_tab_id")
    if base_id:
        for tab in tabs:
            if tab.get("id") == base_id:
                role = _txt(tab.get("role")).lower()
                if role:
                    return role

    work_type = _txt(data.get("work_type")).lower()
    if work_type in ("epoxy", "polish", "gyp"):
        return work_type
    if work_type == "combo":
        return "epoxy"        # block one of a combo is the resin system
    for tab in tabs:          # unknown work type: fall back to the first priced tab
        role = _txt(tab.get("role")).lower()
        if role:
            return role
    return "epoxy"


def _system_text(data: Dict[str, Any]) -> str:
    """Everything we know about what is being installed, lowercased, so the
    Primary Floor match can look at the product names the estimator actually
    picked on the sheet rather than just the marketing name."""
    parts = [_txt(data.get("system_name"))]
    for sysrow in data.get("sheet_systems") or []:
        if isinstance(sysrow, dict):
            parts.append(_txt(sysrow.get("name")))
    for tab in data.get("priced_tabs") or []:
        if isinstance(tab, dict):
            parts.extend(_txt(n) for n in (tab.get("sys_names") or []))
    return " ".join(p for p in parts if p).lower()


def _primary_floor(data: Dict[str, Any]) -> str:
    role = _base_role(data)
    if role == "gyp":
        return "Gypsum Cement Underlayment"
    text = _system_text(data)
    table = _POLISH_FLOORS if role == "polish" else _FLOORS
    for keywords, label in table:
        if any(k in text for k in keywords):
            return label
    return ""


# Which takeoff fields make up a floor area, per layout. The sheet-resolved
# names come first; the second tuple is what intake called them, for drafts
# saved before the sheet snapshot existed.
_SF_KEYS = {
    "epoxy":  (("epoxy_sf", "epoxy_sf_2"), ("system_1_sf", "system_2_sf")),
    "polish": (("polish_sf",), ("polish_sf",)),
    "gyp":    (("gyp_soft_sf", "gyp_hard_sf", "gyp_corridor_sf"),) * 2,
}
_LF_KEYS = (("cove_lf", "cove_lf_2"), ("cove_1_lf", "cove_2_lf"))


def _sum_area(source: Dict[str, Any], keys) -> Optional[float]:
    vals = [v for v in (_num(source.get(k)) for k in keys) if v]
    return sum(vals) if vals else None


def _areas(data: Dict[str, Any], role: str) -> tuple[Optional[float], Optional[float]]:
    """(floor SF, cove LF) for one layout. Sheet-resolved areas win, because
    they follow the estimator's takeoff edits on the grid."""
    area = data.get("sheet_area") if isinstance(data.get("sheet_area"), dict) else {}
    sheet_keys, intake_keys = _SF_KEYS.get(role, _SF_KEYS["epoxy"])
    sf = _sum_area(area, sheet_keys) or _sum_area(data, intake_keys)
    lf = _sum_area(area, _LF_KEYS[0]) or _sum_area(data, _LF_KEYS[1])
    return sf, (lf if role != "polish" else None)   # cove belongs to the resin systems


# Fallback wording for the second system block when a tab carries real area but
# no derived name — the sheet's own vocabulary for each layout.
_ROLE_LABELS = {"epoxy": "Epoxy", "polish": "Polished Concrete",
                "gyp": "Gypsum Underlayment"}


def _second_system(data: Dict[str, Any], base_role: str):
    """The other half of a combo bid, for the sheet's second system block.

    An epoxy+polish job prices both a resin and a polish tab. Only one can be
    block one, so without this the polish half never reaches the hand-off at all
    — the exact re-typing this page exists to remove.

    A tab only counts if it has FLOOR AREA. Every draft carries all five gyp
    variants as priced tabs at zero square feet; picking one of those by tab order
    would put "N12 1/8"" on the sheet as if somebody had bid it.
    """
    for tab in data.get("priced_tabs") or []:
        if not isinstance(tab, dict):
            continue
        role = _txt(tab.get("role")).lower()
        if not role or role == base_role:
            continue
        sf_src = tab.get("sf") if isinstance(tab.get("sf"), dict) else {}
        sheet_keys, _ = _SF_KEYS.get(role, _SF_KEYS["epoxy"])
        sf = _sum_area(sf_src, sheet_keys)
        if not sf:
            continue
        lf = _sum_area(sf_src, _LF_KEYS[0]) if role != "polish" else None
        return (_txt(tab.get("system_desc")) or _ROLE_LABELS.get(role, ""), sf, lf)
    return None


def _flag(data: Dict[str, Any], flag: str) -> Optional[str]:
    """Read a Yes/No estimate flag out of the saved grid edits.

    Gyp keeps its own Taxable cell but mirrors Prevailing Wage and Remodel from
    the epoxy tab by formula, so an unset gyp key legitimately falls through to
    epoxy. An answer that is nowhere means nobody touched the flag, and the
    template default (taxable, not prevailing wage) stands.
    """
    cells = data.get("cell_values") if isinstance(data.get("cell_values"), dict) else {}
    epoxy_addr, gyp_addr = _FLAG_CELLS[flag]
    if _base_role(data) == "gyp":
        v = cells.get(f"{_GYP_BASE}!{gyp_addr}")
        if v not in (None, ""):
            return str(v)
    v = cells.get(f"Epoxy!{epoxy_addr}")
    return None if v in (None, "") else str(v)


def build_prefill(draft: Dict[str, Any], *, deposit_requested: bool = False) -> Dict[str, Any]:
    """Info Sheet cells we can answer from the draft, keyed by address.

    An empty string means "clear the template's default" — used where the
    template ships a guess that would read as fact once printed (Lead Source).
    A key that is simply absent leaves the template alone.

    Nothing pink is written. Manufacturer (B39) and Color/Blend (B41) are
    chartreuse on the marked-up sheet but stay blank too: the estimate does not
    record the supplier, and the blend is chosen with the customer after award.
    """
    data = draft.get("data") if isinstance(draft.get("data"), dict) else {}
    out: Dict[str, Any] = {}

    def put(addr: str, value) -> None:
        if value is None or value == "":
            return
        out[addr] = value

    # Who sold it. `estimator_name` is typed on the proposal screen; before that
    # the draft only knows the account that created it.
    put("B13", _txt(data.get("estimator_name")) or _person(draft.get("owner_email") or ""))
    put("B14", _txt(data.get("job_number")))
    put("B15", _txt(data.get("project_name")))
    put("B17", _primary_floor(data))

    state = _txt(data.get("state")).upper()
    put("B19", _STATES.get(state, state))
    put("B20", _txt(data.get("address")))
    put("B21", _txt(data.get("city")))
    put("D21", _txt(data.get("zip")))

    # Who gets billed. On a GC job that is the general contractor; direct work
    # is billed to the owner, whose name is the project name.
    gc = _txt(data.get("architect"))
    put("B23", gc if _txt(data.get("audience")).upper() == "GC" and gc
               else _txt(data.get("project_name")))
    put("B24", _txt(data.get("address")))
    city_line = ", ".join(p for p in (_txt(data.get("city")),
                                      " ".join(p for p in (state, _txt(data.get("zip"))) if p))
                          if p)
    put("B25", city_line)
    put("B26", _txt(data.get("contact_phone")))

    put("B29", _txt(data.get("contact_name")))
    put("B30", _txt(data.get("contact_phone")))
    put("B31", _txt(data.get("contact_email")))

    role = _base_role(data)
    put("B40", _txt(data.get("system_name")))
    sf, lf = _areas(data, role)
    put("B42", sf)
    put("D42", lf)

    second = _second_system(data, role)
    if second:
        put("B46", second[0])
        put("B48", second[1])
        put("D48", second[2])

    put("B57", _num(data.get("proposal_lump_sum")))
    costs = data.get("cost_snapshot") if isinstance(data.get("cost_snapshot"), dict) else {}
    put("B58", _num(costs.get("costs")))
    put("I58", _num(costs.get("man_hours")))

    out["B59"] = "Y" if deposit_requested else "N"

    # Blank beats a plausible guess here — see _LEAD_SOURCES.
    out["B62"] = _LEAD_SOURCES.get(_txt(data.get("source")).lower(), "")

    pw = _flag(data, "prevailing_wage")
    if pw is not None:
        out["B63"] = _yn(pw)
    taxable = _flag(data, "taxable")
    if taxable is not None:
        out["B66"] = "N" if _yn(taxable) == "Y" else "Y"   # exempt is taxable inverted
    remodel = _flag(data, "remodel_tax")
    if remodel is not None:
        out["B67"] = _yn(remodel)

    return out


# Cells the estimator may type into: everything the prefill can write, plus the
# pink decisions and the free-text blocks the sheet leaves for a human.
EDITABLE = frozenset({
    "B13", "B14", "B15", "B16", "B17", "B19", "B20", "B21", "D21",
    "B23", "B24", "B25", "B26", "B27",
    "B29", "B30", "B31", "B33", "B34", "B35",
    "F23", "F24", "F25", "F28", "F32", "F33", "F34", "F35", "F36",
    "B37", "B38",
    "B39", "B40", "B41", "B42", "D42", "B43",
    "B45", "B46", "B47", "B48", "D48", "B49",
    "B51", "B52", "B53", "B54", "B55",
    "B57", "B58", "I57", "I58",
    "B59", "B60", "B61", "B62", "B63", "B64", "B66", "B67", "B68", "B70",
    "B73", "B75", "B76",
})

# Cells that must stay text even when they look numeric. A job number is the
# clearest case: "26.100" cast to a float is 26.1, and the Invoice and
# Foundation Import tabs both print it straight from B14. Phones lose their
# shape the same way.
TEXT_CELLS = frozenset({"B14", "B26", "B30", "F35", "B27"})


def _as_text(v) -> str:
    """Keep the string, keep the injection guard `_coerce` would have applied."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


# ─── Fill ──────────────────────────────────────────────────────────────
def fill_info_sheet(prefill: Dict[str, Any],
                    overrides: Optional[Dict[str, Any]] = None) -> bytes:
    """Render the workbook. Overrides are what the estimator typed, so they win.

    Only cells on `EDITABLE` are written, from either source: a stray key can
    otherwise land on a label or blow away one of the derived formulas the other
    tabs read.
    """
    wb = openpyxl.load_workbook(TEMPLATE_PATH)   # fresh — never the cached copy
    ws = wb[SHEET]

    values: Dict[str, Any] = {k: v for k, v in (prefill or {}).items()}
    for key, val in (overrides or {}).items():
        addr = key.split("!", 1)[1] if "!" in key else key
        values[addr] = val

    for addr, val in values.items():
        if addr not in EDITABLE or addr in READ_ONLY:
            continue
        if val == "" or val is None:
            ws[addr] = None
        elif addr in TEXT_CELLS:
            ws[addr] = _as_text(val)
        else:
            ws[addr] = _coerce(val)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
