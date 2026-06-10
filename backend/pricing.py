"""
Treadwell material pricing — extracted from Kyle's estimate sheet 5.7.

Single source of truth so the tool can price a job from (selections + SF/LF)
WITHOUT the estimate sheet's duplicated per-system tables, and without the
browser hitting #NAME? on the sheet's named-range formulas.

Recipes live in pricing_recipes.json, pulled from
`Numbers 5.7.26/estimate sheet - 5.7.xlsx` and verified to reproduce the sheet
(MACRO Flake @ 1000 SF = $1,744.48 liquids + $368.00 media; cross-checked
against real 2025 estimates — quantity logic matches exactly).

Three product families:
  EPOXY systems  — compute_system(name, sf): liquids ROUNDUP(sf/coverage)*price
                   + media CEILING(sf*lb_per_sf, bag)*price (bulk break)
  POLISH         — compute_polish(sf, reno, grout, dye, joint_filler): per-SF
                   component rates + 2% shipping
  COVE           — compute_cove(option, lf, quartz_system): Cove Rez/WR liquid
                   + silica/Q28 aggregate (+ zinc cap)
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List

_RECIPES_PATH = Path(__file__).parent / "pricing_recipes.json"


def _load() -> Dict[str, Any]:
    try:
        return json.loads(_RECIPES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"epoxy_systems": {}, "polish": {}, "cove": {}, "cove_prices": {}}


_DATA: Dict[str, Any] = _load()
_EPOXY: Dict[str, Any] = _DATA.get("epoxy_systems", {})
_POLISH: Dict[str, Any] = _DATA.get("polish", {})
_COVE: Dict[str, Any] = _DATA.get("cove", {})
_COVE_PRICES: Dict[str, Any] = _DATA.get("cove_prices", {})


def recipes_version() -> str:
    """Cache-version token for the pricing data — the recipes file's mtime.
    Changes on deploy when pricing_recipes.json changes, busting ETag caches."""
    try:
        return str(_RECIPES_PATH.stat().st_mtime_ns)
    except OSError:
        return "0"

_JF_SF_PER_KIT = 3500  # joint filler: ROUNDUP(sf / 3500) kits


def _num(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _ceil_to(value: float, multiple: float) -> float:
    """Round `value` UP to the next whole `multiple` (Excel CEILING)."""
    if not multiple:
        return value
    return math.ceil(value / multiple) * multiple


def list_systems() -> List[str]:
    """Epoxy system names (the System-Options dropdown)."""
    return list(_EPOXY.keys())


def list_cove_options() -> List[str]:
    return list(_COVE.keys())


# ── EPOXY ────────────────────────────────────────────────────────────
def compute_system(name: str, sf: float, *, bulk_discount: bool = False) -> Dict[str, Any]:
    """Material pricing for epoxy system `name` at `sf` square feet.

    `bulk_discount` mirrors Kyle's D41 "BULK Discount ON" toggle: 6 materials
    (Glaze #4, the Armor Top variants, Poly-Crete SL) drop to their bulk rate.
    """
    recipe = _EPOXY.get(name)
    sf = _num(sf) or 0.0
    if recipe is None or sf <= 0:
        return {"family": "epoxy", "system": name, "sf": sf, "liquids": 0.0,
                "media": 0.0, "material": 0.0, "detail": [], "found": recipe is not None,
                "bulk_discount": bulk_discount}

    detail: List[Dict[str, Any]] = []
    liquids_total = 0.0
    for coat in recipe.get("liquids", []):
        coverage = _num(coat.get("coverage_sf_per_unit"))
        bulk = coat.get("bulk_price")
        price = _num(bulk) if (bulk_discount and bulk is not None) else _num(coat.get("unit_price"))
        if not coverage or price is None:
            continue
        qty = math.ceil(sf / coverage)
        cost = qty * price
        liquids_total += cost
        detail.append({"kind": "liquid", "product": coat.get("product"),
                       "qty": qty, "unit_price": price, "cost": round(cost, 2)})

    media_total = 0.0
    for item in recipe.get("media", []):
        coverage = _num(item.get("coverage_lb_per_sf"))
        bag = _num(item.get("bag_size"))
        if not coverage or not bag:
            continue
        lbs = _ceil_to(sf * coverage, bag)
        if item.get("unit_price") is not None:
            price = _num(item.get("unit_price")) or 0.0
        else:
            thresh = _num(item.get("price_break_lbs"))
            below = _num(item.get("price_below"))
            above = _num(item.get("price_above"))
            price = (below if (thresh is None or lbs < thresh) else above) or 0.0
        cost = lbs * price
        media_total += cost
        detail.append({"kind": "media", "product": item.get("product"),
                       "lbs": lbs, "unit_price": price, "cost": round(cost, 2)})

    return {"family": "epoxy", "system": name, "sf": sf,
            "liquids": round(liquids_total, 2), "media": round(media_total, 2),
            "material": round(liquids_total + media_total, 2),
            "detail": detail, "found": True}


# ── POLISH ───────────────────────────────────────────────────────────
def compute_polish(sf: float, *, reno: bool = False, grout: bool = False,
                   dye: bool = False, joint_filler: bool = False) -> Dict[str, Any]:
    """Material pricing for a polish floor at `sf` square feet.

    Densifier + sealer + patch are always included; grout / dye / joint
    filler are optional. Mirrors the Polish tab (per-SF rates + 2% shipping).
    """
    sf = _num(sf) or 0.0
    P = _POLISH
    if sf <= 0 or not P:
        return {"family": "polish", "sf": sf, "material": 0.0, "detail": [], "found": bool(P)}

    detail: List[Dict[str, Any]] = []

    def line(label, cost):
        detail.append({"product": label, "cost": round(cost, 2)})
        return cost

    sub = 0.0
    sub += line("Patch", sf * _num(P.get("patch_reno" if reno else "patch_new")))
    sub += line("Densifier", sf * _num(P.get("densifier")))
    sub += line("Sealer", sf * _num(P.get("sealer")))
    if grout:
        sub += line("Grout compound", sf * _num(P.get("grout")))
    if dye:
        sub += line("Dye", sf * _num(P.get("dye_per_coat")) * _num(P.get("dye_coats") or 2))
    if joint_filler:
        kits = math.ceil(sf / _JF_SF_PER_KIT)
        sub += line(f"Joint filler ({kits} kit)", kits * _num(P.get("joint_filler_per_kit")))

    sub = math.ceil(sub)  # Material Sub Total = ROUNDUP(...)
    shipping = math.ceil(sub * _num(P.get("shipping_pct") or 0.02))
    return {"family": "polish", "sf": sf, "subtotal": float(sub),
            "shipping": float(shipping), "material": float(sub + shipping),
            "detail": detail, "found": True}


# ── COVE ─────────────────────────────────────────────────────────────
def compute_cove(option: str, lf: float, *, quartz_system: bool = False) -> Dict[str, Any]:
    """Material pricing for cove base `option` at `lf` linear feet.

    `quartz_system` switches the aggregate to Q28 (the sheet keys this off
    whether the selected epoxy system is a quartz system).
    """
    c = _COVE.get(option)
    lf = _num(lf) or 0.0
    if c is None or lf <= 0:
        return {"family": "cove", "option": option, "lf": lf, "material": 0.0,
                "detail": [], "found": c is not None}

    cp = _COVE_PRICES
    divisor = _num(c.get("divisor")) or 1
    C = math.ceil(lf / divisor)
    E = math.ceil(C / 8) + math.ceil(C / 4)
    resin_price = _num(cp.get("CoveRez")) if c.get("resin") == "CoveRez" else _num(cp.get("WR"))
    liquid = E * (resin_price or 0.0)

    silica_lbs = _ceil_to(C * (_num(c.get("agg_coverage")) or 0), 50)
    agg_price = _num(cp.get("q28")) if quartz_system else _num(cp.get("silica"))
    aggregate = silica_lbs * (agg_price or 0.0)

    cap = 0.0
    if c.get("has_cap"):
        cap = _ceil_to(lf, 8) * (_num(cp.get("zinc")) or 0.0)

    detail = [{"product": f"{c.get('resin')} liquid", "qty": E, "cost": round(liquid, 2)},
              {"product": "Silica/Q28 aggregate", "lbs": silica_lbs, "cost": round(aggregate, 2)}]
    if c.get("has_cap"):
        detail.append({"product": "Zinc cap", "cost": round(cap, 2)})
    return {"family": "cove", "option": option, "lf": lf,
            "material": round(liquid + aggregate + cap, 2), "detail": detail, "found": True}


# ── MATERIAL ROLL-UP (matches the sheet's D40 -> D42 -> D43) ──────────
EPOXY_PATCH_RATE = 0.10   # epoxy patch material $/SF (sheet D18 = E20 * 0.10)


def shipping_escalation_pct(material_sub: float) -> float:
    """Sheet B42 = 0.05 + (0.10 if sub<=5000 else 0.06 if sub<=10000 else 0.04)."""
    sub = _num(material_sub) or 0.0
    extra = 0.10 if sub <= 5000 else (0.06 if sub <= 10000 else 0.04)
    return round(0.05 + extra, 4)


def roll_up(system_results: List[Dict[str, Any]], *, cove_total: float = 0.0,
            polish_total: float = 0.0, patch_sf: float = 0.0,
            extras_total: float = 0.0) -> Dict[str, Any]:
    """Combine component costs into the sheet's Material Total.

      D40 Material Sub  = ROUNDUP(systems + patch + cove + polish + extras)
      D42 Shipping+Escl = ROUNDUP(D40 * shipping_escalation_pct(D40))
      D43 Material Total= D40 + D42

    `extras_total` mirrors the sheet's spare manual material rows (the
    `=B*C` lines like "Super Stick" / "Floor Graphic") that fall inside
    D40's SUM(D18:D39) range — custom edge-case materials the estimator
    adds by qty x unit price.
    """
    sub_raw = sum((_num(r.get("material")) or 0.0) for r in system_results)
    sub_raw += (_num(cove_total) or 0.0) + (_num(polish_total) or 0.0)
    sub_raw += (_num(patch_sf) or 0.0) * EPOXY_PATCH_RATE
    sub_raw += (_num(extras_total) or 0.0)
    material_sub = float(math.ceil(sub_raw))
    pct = shipping_escalation_pct(material_sub)
    shipping = float(math.ceil(material_sub * pct))
    return {"material_sub": material_sub, "shipping_pct": pct,
            "shipping_escalation": shipping, "material_total": material_sub + shipping}


# ── FULL BID (labor + tooling + travel + markup + taxes + bond -> D88) ──
def _gp_pct(subtotal: float) -> float:
    """Sheet B73 — GP margin tiered by SUB-TOTAL COSTS (D70)."""
    if subtotal < 6500:  return 0.52
    if subtotal < 15000: return 0.45
    if subtotal < 22500: return 0.35
    if subtotal < 32500: return 0.32
    return 0.30


def compute_full_bid(material_total: float, sf: float, *,
                     crews=None, labor_rate: float = 32.2, day_hours: int = 8,
                     travel_hours: float = 0, prevailing_wage: bool = False,
                     burden_pct: float = 0.12, demo_sf: float = 0, plastic: float = 0,
                     local: bool = True, lodging_rate: float = 70, food_rate: float = 45,
                     super_pct: float = 0.03, soft_pct: float = 0.13, contingency: float = 0,
                     hard_bid: bool = False, hard_bid_pct=None, gp_pct=None,
                     taxable: bool = True,
                     sales_tax_rate: float = 0.09475, remodel: bool = False,
                     remodel_rate: float = 0.10, fees: float = 0, bond_pct: float = 0) -> Dict[str, Any]:
    """Full Total Base Bid (sheet D88) from material_total (D43) + labor/markup.

    Replicates the Epoxy tab's cost+markup chain exactly. `crews` is a list of
    (guys, days); defaults to the sheet's [(3, 5)]. Inputs default to the
    sheet's values and are meant to be overridable (manual inputs).
    Note: the sheet hardcodes remodel at 10%; pass remodel_rate to use the
    accurate state+county rate instead.
    """
    ceil = math.ceil
    crews = crews if crews is not None else [(3, 5)]
    D43 = _num(material_total) or 0.0
    sf = _num(sf) or 0.0

    # Labor (D47-D53), escalation (D54), burden (D55)
    labor_raw = sum((g * d * labor_rate * day_hours) for g, d in crews)
    man_days = sum(g * d for g, d in crews)
    travel_labor = man_days * travel_hours * labor_rate
    D53 = ceil(labor_raw + travel_labor)
    D54 = ceil(D53 * (0.05 if prevailing_wage else 0))
    D55 = ceil((D53 + D54) * burden_pct)

    # Tooling (D58-D62)
    D58 = ceil((ceil(sf / 1000) if sf > 2000 else 2) * 35)
    D59 = ceil(max(sf * 0.33, 150))
    D60 = ceil(demo_sf * 0.33)
    D62 = D58 + D59 + D60 + plastic

    # Travel (D65-D68)
    if local:
        D68 = 0
    else:
        nights = ((D53 - travel_labor) / labor_rate) / 8
        D68 = ceil(nights * lodging_rate) + ceil(nights * food_rate)

    # Sub-total costs (D70)
    D70 = ceil(D43 + D53 + D54 + D55 + D62 + D68)

    # Taxes feed the markup, so compute the bases first
    D80 = ceil(D43 * sales_tax_rate) if taxable else 0   # sales tax on MATERIAL
    D83 = ceil(fees)                                     # fees

    # GP markup (D73), hard-bid (D74), super (D75), soft (D76), contingency (D77).
    # gp_pct / hard_bid_pct let the estimator's actual grid cells (B73 / B74)
    # override the sheet's default formulas — e.g. a hand-typed -17% hard-bid
    # discount on a competitive job. When not supplied, fall back to the sheet's
    # tiered defaults so existing behavior is unchanged.
    gp = gp_pct if gp_pct is not None else _gp_pct(D70)
    D73 = ceil((D70 + D80 + D83) / (1 - gp)) - ceil(D70 + D80)
    if hard_bid_pct is not None:
        b74 = hard_bid_pct
    elif hard_bid:
        b74 = -0.04 if D70 >= 60000 else (-0.025 if D70 >= 13000 else 0)
    else:
        b74 = 0
    D74 = ceil((D70 + D73) * b74)
    D77 = ceil(contingency)
    D75 = ceil((D70 + D73 + D74 + D77 + D80 + D83) * super_pct)
    D76 = ceil((D70 + D73 + D74 + D75 + D77 + D80 + D83) * soft_pct)

    # KS remodel tax (D81) — on the labor/service+markup portion
    remodel_base = D53 + D54 + D55 + D62 + D68 + (D73 + D74 + D75 + D76 + D77) + D83
    D81 = ceil(remodel_base * remodel_rate) if remodel else 0
    D82 = D80 + D81

    # Bond (D84), fees+bond (D85)
    D84 = ceil((D70 + D73 + D74 + D75 + D76 + D77 + D80 + D81 + D82 + D83) * bond_pct)
    D85 = ceil(D83 + D84)

    # Total Base Bid (D88)
    D88 = D70 + (D73 + D74 + D75 + D76 + D77) + D82 + D85
    return {
        "install_labor": D53, "labor_escalation": D54, "labor_burden": D55,
        "tooling": D62, "travel": D68, "subtotal_costs": D70,
        "gp_pct": gp, "gp_markup": D73, "hard_bid": D74,
        "superintendent_pto": D75, "soft_costs": D76, "contingency": D77,
        "sales_tax": D80, "remodel_tax": D81, "total_taxes": D82,
        "fees": D83, "bond": D84, "fees_bond": D85,
        "total_base_bid": float(D88), "per_sf": round(D88 / sf, 4) if sf else 0,
    }
