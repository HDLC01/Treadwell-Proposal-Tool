#!/usr/bin/env python
"""Seed the Items & Assemblies library from Kyle's estimate workbook (Phase 12 of the v2 program).

WHAT IT DOES. Reads backend/templates/estimate_sheet_5.7.xlsx and PLANS the library rows that make the same
materials priceable in Estimating Tool v2: the Epoxy tab's products (as library_items), its fifteen floor
systems and six wall systems and its primers (as library_assemblies), the price sources its code-priced
formulas read (a patch, the cove materials), one epoxy crew line (library_labor and library_labor_calc),
and the Gyp tabs: their material products (library_items; the USG and GrassWorx ones from the first Gyp tab, the
Treadstone ones from Gyp (FR)), the three area rows a Gyp takeoff is made of (library_assemblies) and the five crew
lines priced by the hour (library_labor), and the two Seal tabs, the Seal option of a bid (Phase 15): the sealer, the
joint filler kit and the patch's two prices (library_items), the four assemblies a new option opens with (one coat or
two, with and without joint filler) and the three crew lines priced by the day (library_labor and library_labor_calc), and the Polish tab (Phase 16): the three per-SF
materials the sheet charges (densifier, sealer, grout compound) and one assembly for each polish system it prices.

DRY RUN IS THE DEFAULT. With no flag it prints the plan and writes nothing. `--apply --target staging`
writes it, and nothing else is accepted: PRODUCTION IS NOT APPROVED (Hanz, 2026-10-12: staging only).

THE FOUR PROMISES, each held by a test (backend/tests/test_seed_library.py):
  deterministic   the same workbook gives the same plan, byte for byte, with ids made from the names
                  ('wb-epoxy-...' and 'wb-gyp-...'), never from a clock or a random number
  insert-only     every statement is `insert ... on conflict (...) do nothing`, so a row Kyle edited is
                  left exactly as he left it, and the statements contain no update, delete, drop or truncate
  idempotent      applying the plan twice writes it once
  loud            a workbook shape the planner has not seen (a new kind of formula, a duplicate name, a
                  price cell with no saved value) stops the run with the cell named. It never guesses.

WHERE A PRICE COMES FROM. The workbook keeps a price in a cell and its escalation in another; the library
row holds the ESCALATED figure the workbook shows today (the saved value of the price cell, to the four
places a library cost has). A material that is cheaper in bulk keeps that price as `bulk_cost`, and flake
and quartz keep their small-lot price and their large-lot `price_breaks`. Coverage, waste and roundup live on
the material (Hanz, 2026-09-22), so a material that the workbook buys at two coverages is two rows.

WHAT A LIBRARY ROW CANNOT SAY (named modelling gaps, listed for Kyle and Hanz in `plan.gaps` and in the PR):
  * coverage is kept to three places, so a bag of flake that covers 266.6667 SF is stored as 266.667. The
    planner rounds a coverage UP, which on a whole number of square feet can never buy a bag the sheet does
    not (see _round_up_3); an area typed to two decimals within 0.003 SF past a bag edge buys one fewer.
  * a flake or quartz price break is judged on the TWO broadcast lines added together in the sheet, and the
    library now reads it the same way: the estimate buys each COAT (one line of one assembly) once for the
    section (js/library-core.js pricePool, Hanz 2026-10-13, "Round each coat like Kyle"), and a system's two
    broadcast lines, which are two library rows on one price ladder, are pooled for the break. Each coat keeps
    its own whole-pack rounding as the sheet does, so a single-area job is the workbook to the cent on every
    recorded job and nothing is left of this gap (see test_epoxy_v2_proof.py). Only the SAME coat on two
    areas is pooled across them, which the sheet cannot say.
  * a library cost is kept to four places and the sheet's prices have more, so at a few sizes (about 5 jobs
    in 1,500 scanned) a sum lands a hair either side of a whole dollar and ROUNDUP differs by one.
  * the cove is two ROUNDUPs deep and its aggregate follows System 1 (Kyle's odd rule 11); a library line
    cannot say either. The cove is priced by a formula in js/epoxy-takeoff.js, and the rows seeded here
    (ids below, RESERVED_PRICE_ROWS) are its editable price sources. A constant in the code is only the
    fallback, and test_epoxy_takeoff.py pins row and constant equal.
  * Bulk Discount is a switch the v2 model does not carry yet, so `bulk_cost` is stored and not used.

THE FOUR DELIBERATE EXCEPTIONS TO INSERT-ONLY (each behind its own flag, each in its own clearly named statement
group, none emitted by default, each held by a test that runs it against a row Kyle edited):
  --tag-vendors         fills `vendor` on the Epoxy rows where it is still NULL ("Sherwin-Williams" or "Poly-Crete", worked
                        out from the discount cell the row's own price cell reads: T141 or T142), and adds the two vendor
                        names to the dropdown list unless a live vendor of that name is already there. It never changes
                        a vendor that has a value, and it changes no other column.
  --gyp-sand-40         moves the Gyp sand price from 35 to 40 (Kyle's 10.01 master, Gyp (USG 1-8") D33) ONLY where it is
                        still 35, so a price Kyle edited is left alone.
  --retire-beta-sample  soft-deletes the two beta placeholder rows (the "Polish - Salt & Pepper (beta sample)" assembly and
                        the "OPF - 5 gal pail (beta sample)" item) by name, only where they are not already deleted.

Usage (from backend/):
    python ops/seed_library_from_workbook.py                       print the plan, write nothing
    python ops/seed_library_from_workbook.py --only epoxy          one tab's rows (epoxy, gyp, seal or polish)
    python ops/seed_library_from_workbook.py --sql                 print the statements it would run
    python ops/seed_library_from_workbook.py --sql --tag-vendors   ... and the vendor fill-in group
    python ops/seed_library_from_workbook.py --apply --target staging
"""
from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import subprocess
import sys
import warnings
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

BACKEND = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BACKEND / "templates" / "estimate_sheet_5.7.xlsx"

EPOXY_SHEET = "Epoxy"
GYP_SHEET = 'Gyp (USG 1-8")'
GYP_FR_SHEET = "Gyp (FR)"
# The five Gyp tabs, in the workbook's order. The plan reads the first and Gyp (FR); the others are loaded too so a
# test can hold the code's presets to every one of them.
GYP_SHEETS = [GYP_SHEET, "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)", GYP_FR_SHEET]
# The two Seal tabs (the Seal option of a v2 bid, Phase 15). Seal (+Jnts) reads almost everything from Seal.
SEAL_SHEET = "Seal"
SEAL_JNTS_SHEET = "Seal (+Jnts)"
SEAL_SHEETS = [SEAL_SHEET, SEAL_JNTS_SHEET]
POLISH_SHEET = "Polish"

# What the staging database is, and how this script reaches it. The staging stack is a Postgres container
# on the VPS (see the memory note on the staging data store). Nothing here names a password: the psql runs
# INSIDE the container over ssh, as the container's own database user.
STAGING_SSH_HOST = "treadwell-vps"
STAGING_DB_CONTAINER = "treadwell-staging-db"
STAGING_DB_USER = "postgres"
STAGING_DB_NAME = "treadwell"


class PlanError(ValueError):
    """The workbook is not in a shape this planner knows. The message names the cell."""


# ── reading the workbook ─────────────────────────────────────────────────────
class Sheet:
    """One sheet twice over: its formulas (or constants) and the values Excel saved beside them."""

    def __init__(self, name: str, formulas, values, names: Dict[str, str]):
        self.name = name
        self.f = formulas
        self.v = values
        self.names = names            # defined name -> "Sheet!$T$146"

    def formula(self, addr: str) -> Any:
        return self.f[addr].value

    def value(self, addr: str) -> Any:
        return self.v[addr].value

    def text(self, addr: str) -> str:
        v = self.value(addr)
        return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def load(path: pathlib.Path = TEMPLATE_PATH) -> Dict[str, Sheet]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wf = openpyxl.load_workbook(path)
        wv = openpyxl.load_workbook(path, data_only=True)
    names = {n: d.attr_text for n, d in wf.defined_names.items()}
    return {s: Sheet(s, wf[s], wv[s], names) for s in [EPOXY_SHEET] + GYP_SHEETS + SEAL_SHEETS + [POLISH_SHEET]}


def _col_index(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_letter(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def shift(col: str, by: int) -> str:
    """'A' shifted 26 columns is 'AA': the System 2 half of the Epoxy tab is the System 1 half moved right."""
    return _col_letter(_col_index(col) + by)


def _number(v: Any, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PlanError("%s should hold a number, found %r" % (where, v))
    return float(v)


def _dec(v: float) -> Decimal:
    """A float as the decimal a person typed: 0.6665 stays 0.6665 and does not become 0.66649999..."""
    return Decimal(repr(round(float(v), 10)))


def _round_up_3(x: Fraction) -> Decimal:
    """A coverage to the three places the library stores, rounded UP.

    A coverage that is rounded down makes a unit look as if it covers LESS, so a job whose area is an exact
    multiple of the true coverage needs a hair more than a whole pack and buys one more (333.333 for a bag
    that really covers 333.3333: 1,000 SF is then 3.000003 bags and rounds up to 4, where the sheet buys 3).
    Rounded up it can only look like it covers a hair more, which on a whole number of square feet cannot
    cross a pack boundary the sheet does not (the area would have to be within 0.0005 of a multiple). It CAN
    fail to cross one the sheet does: an area typed to two decimals just past a bag edge (2,666.67 SF is 0.003
    past ten 40 lb bags of flake) buys one bag fewer than the sheet. That is the cost of three places, and it
    is a declared departure (tests/test_epoxy_v2_proof.py)."""
    milli = Fraction(x.numerator, x.denominator) * 1000
    return (Decimal(milli.numerator) / Decimal(milli.denominator)).to_integral_value(ROUND_CEILING) / 1000


def _slug(text: str) -> str:
    s = text.lower().replace('"', "in").replace("+", " plus ").replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def _money4(x: float) -> float:
    return float(round(Decimal(repr(round(float(x), 8))), 4))


def _g(x: float) -> str:
    """A number as a person writes it in a name: 0.15, 125, 17.5."""
    return ("%g" % x)


# ── the plan ─────────────────────────────────────────────────────────────────
class Plan:
    """The rows the seed would write. Four lists and the gaps, all in a fixed order."""

    def __init__(self) -> None:
        self.items: Dict[str, Dict[str, Any]] = {}
        self.assemblies: Dict[str, Dict[str, Any]] = {}
        self.labor: Dict[str, Dict[str, Any]] = {}
        self.labor_calc: Dict[str, Dict[str, Any]] = {}
        self.vendors: Dict[str, Dict[str, Any]] = {}     # the supplier names the items' `vendor` text uses (not in counts)
        self.gaps: List[str] = []
        self.combined_breaks: set = set()      # materials whose price break the sheet judges on two lines added

    def add_item(self, row: Dict[str, Any]) -> str:
        have = self.items.get(row["id"])
        if have is not None and have != row:
            raise PlanError("two different materials would both be %r: %r and %r"
                            % (row["id"], have["name"], row["name"]))
        self.items[row["id"]] = row
        return row["id"]

    def add_assembly(self, row: Dict[str, Any]) -> None:
        have = self.assemblies.get(row["id"])
        if have is not None and have != row:
            raise PlanError("two different assemblies would both be %r (%r)" % (row["id"], row["name"]))
        self.assemblies[row["id"]] = row

    def gap(self, text: str) -> None:
        if text not in self.gaps:
            self.gaps.append(text)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "items": [self.items[k] for k in sorted(self.items)],
            "assemblies": [self.assemblies[k] for k in sorted(self.assemblies)],
            "labor": [self.labor[k] for k in sorted(self.labor)],
            "labor_calc": [self.labor_calc[k] for k in sorted(self.labor_calc)],
            "gaps": list(self.gaps),
        }

    def counts(self) -> Dict[str, int]:
        return {"items": len(self.items), "assemblies": len(self.assemblies),
                "labor": len(self.labor), "labor_calc": len(self.labor_calc)}


def _item(id_: str, name: str, unit: str, buy_qty: float, unit_cost: float, coverage: Optional[float],
          division: str, work_type: str, notes: str, bulk_cost: Optional[float] = None,
          price_breaks: Optional[List[Dict[str, float]]] = None) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "id": id_, "name": name, "unit": unit, "buy_qty": buy_qty, "unit_cost": unit_cost,
        "coverage": coverage, "waste_pct": 0, "roundup": True,
        "divisions": [division], "category": division,
        "default_work_types": [work_type], "notes": notes,
    }
    if bulk_cost is not None:
        row["bulk_cost"] = bulk_cost
    if price_breaks:
        row["price_breaks"] = price_breaks
    return row


def _set_vendor(row: Dict[str, Any], vendor: Optional[str]) -> None:
    if vendor is not None:
        row["vendor"] = vendor


# ── the price a formula points at ────────────────────────────────────────────
_CELL = re.compile(r"^\$?([A-Z]{1,3})\$?(\d+)$")


def resolve_price(sh: Sheet, token: str, where: str) -> Tuple[str, float]:
    """A price token from a cost formula (a defined name, or a cell like $T$158) as (address, saved value)."""
    token = token.strip()
    target = sh.names.get(token)
    if target is not None:
        sheet, _, ref = target.rpartition("!")
        if sheet.strip("'") != sh.name:
            raise PlanError("%s: the name %s points at another sheet (%s)" % (where, token, target))
        token = ref
    m = _CELL.match(token)
    if not m:
        raise PlanError("%s: %r is neither a defined name nor a cell" % (where, token))
    addr = m.group(1) + m.group(2)
    value = sh.value(addr)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError("%s: the price cell %s holds %r, not a saved number" % (where, addr, value))
    return addr, float(value)


def price_label(sh: Sheet, addr: str) -> str:
    """The words beside a price cell: the cell one column to its left (T146's label is S146)."""
    m = _CELL.match(addr)
    return sh.text(_col_letter(_col_index(m.group(1)) - 1) + m.group(2))


def bulk_price(sh: Sheet, addr: str) -> Optional[float]:
    """The bulk figure of a price cell whose formula switches on Bulk Discount, else None.
    The Epoxy tab writes it `=IF($D$41=$V$136,W153,((U153*$T$141)+U153))`: the W cell is the bulk price."""
    f = sh.formula(addr)
    if isinstance(f, str):
        m = re.match(r"^=IF\(\$D\$41=\$V\$136,([A-Z]{1,3}\d+),", f)
        if m:
            v = sh.value(m.group(1))
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
            raise PlanError("%s: the bulk price cell %s holds %r" % (addr, m.group(1), v))
    return None


# ── the discount group of a price cell (the `vendor` of an Epoxy row) ─────────
# Kyle's sheet discounts a material by the price COLUMN it sits in: every T-column liquid reads the Epoxy discount in
# T141 (B41), except the few that read the Poly-Crete discount in T142 (C41, which follows B41). A W-column material
# (silica, flake, quartz, zinc cap, mat) is never discounted. The group is read off the price cell's own formula, so a
# product Kyle moves to the other discount moves with it on the next plan, and the seed never keeps a list of them.
# discount cell -> (the label the sheet puts beside it, the vendor name the library row gets)
DISCOUNT_VENDORS: Dict[str, Tuple[str, str]] = {"T141": ("Epoxy", "Sherwin-Williams"), "T142": ("Poly-Crete", "Poly-Crete")}


def discount_vendor(sh: Sheet, addr: str, plan: Optional[Plan] = None) -> Optional[str]:
    """The vendor a price cell's discount group names, or None when the cell is not discounted (a W-column material, a
    constant). A formula that reads two discount cells stops the run: the group would be a guess."""
    for cell, (label, _vendor) in DISCOUNT_VENDORS.items():
        if sh.text("S" + cell[1:]) != label:
            raise PlanError("%s!S%s should label the discount %r, found %r" % (sh.name, cell[1:], label, sh.text("S" + cell[1:])))
    f = sh.formula(addr)
    if not isinstance(f, str):
        return None
    hits = sorted({"T" + n for n in re.findall(r"\$T\$(\d+)", f)} & set(DISCOUNT_VENDORS))
    if len(hits) > 1:
        raise PlanError("%s!%s reads two discounts (%s): its vendor would be a guess" % (sh.name, addr, ", ".join(hits)))
    if not hits:
        return None
    vendor = DISCOUNT_VENDORS[hits[0]][1]
    if plan is not None:
        plan.vendors[vendor] = {"id": "wb-vendor-" + _slug(vendor), "name": vendor,
                                "notes": "Added by the library seed: the discount group Kyle's workbook prices these materials in."}
    return vendor


# ── Epoxy: the systems ───────────────────────────────────────────────────────
UNIT_WORDS = {"Gal": "Gallon", "Kit": "Kit", "Large Kit": "Large Kit"}
EPOXY_NOTE = "Seeded from Kyle's estimate workbook, Epoxy tab, price cell Epoxy!%s (the escalated price saved in the file)."


def _coverage_cell(sh: Sheet, addr: str) -> float:
    return _number(sh.value(addr), "Epoxy!" + addr)


def _liquid_line(sh: Sheet, row: int, off: int, area: str, plan: Plan, where: str) -> Optional[Dict[str, Any]]:
    """One liquid line of a system block, or None when the row is not one (a header, a total, a gap)."""
    col = lambda c: shift(c, off) + str(row)       # noqa: E731
    product = sh.text(col("B"))
    cov_cell = col("C")
    e_formula = sh.formula(col("E"))
    if not product or not isinstance(e_formula, str) or not e_formula.startswith("="):
        return None
    if not isinstance(sh.value(cov_cell), (int, float)):
        return None
    cov = _coverage_cell(sh, cov_cell)
    unit_text = sh.text(col("D"))
    cref = shift("C", off) + str(row)
    pack_mult = 1
    if re.fullmatch(r"=ROUNDUP\(%s/%s,0\)" % (re.escape(area), re.escape(cref)), e_formula):
        pass
    elif re.fullmatch(r"=\(CEILING\(%s/%s,5\)\)/5" % (re.escape(area), re.escape(cref)), e_formula):
        pack_mult = 5                              # a 5 gallon kit: one kit covers 5 gallons' worth of area
    else:
        raise PlanError("%s: the quantity formula %s is not one this planner reads" % (where + col("E"), e_formula))
    f_formula = sh.formula(col("F"))
    m = re.fullmatch(r"=%s\*(\$?[A-Za-z_][A-Za-z0-9_$]*)" % re.escape(shift("E", off) + str(row)), str(f_formula))
    if not m:
        raise PlanError("%s: the cost formula %s is not one this planner reads" % (where + col("F"), f_formula))
    addr, price = resolve_price(sh, m.group(1), where + col("F"))
    unit_word = unit_text.split("/")[-1].strip()
    if unit_word not in UNIT_WORDS:
        raise PlanError("%s: the unit %r is not one this planner reads" % (where + col("D"), unit_text))
    unit = "Kit" if pack_mult == 5 else UNIT_WORDS[unit_word]
    coverage = cov * pack_mult
    bulk = bulk_price(sh, addr)
    name = "%s, %s SF/%s" % (product, _g(coverage), unit)
    item = _item("wb-epoxy-" + _slug(name), name, unit, 1, _money4(price), coverage, "Epoxy", "epoxy",
                 EPOXY_NOTE % addr, bulk_cost=_money4(bulk) if bulk is not None else None)
    _set_vendor(item, discount_vendor(sh, addr, plan))
    plan.add_item(item)
    return {"role": sh.text(col("A")) or "Liquids", "item_id": item["id"]}


def _media_line(sh: Sheet, row: int, off: int, area: str, plan: Plan, where: str) -> Optional[Dict[str, Any]]:
    """One broadcast-media line of a system block (flake, quartz, silica, a mat), or None."""
    col = lambda c: shift(c, off) + str(row)       # noqa: E731
    product = sh.text(col("L"))
    cov_cell = col("M")
    o_formula = sh.formula(col("O"))
    p_formula = sh.formula(col("P"))
    if not product or not isinstance(o_formula, str) or not isinstance(sh.value(cov_cell), (int, float)):
        return None
    if product.lower() in ("grip", "n/a"):
        return None                                # "NOT used" in the sheet
    per_sf = _number(sh.value(cov_cell), where + cov_cell)
    mref = shift("M", off) + str(row)
    m = re.fullmatch(r"=CEILING\(%s\*%s,(\d+)\)" % (re.escape(area), re.escape(mref)), o_formula)
    if not m:
        raise PlanError("%s: the media quantity formula %s is not one this planner reads" % (where + col("O"), o_formula))
    bag = float(m.group(1))
    oc = shift("O", off) + str(row)
    pf = str(p_formula)
    small = large_token = None
    combined = False
    simple = re.fullmatch(r"=%s\*(\$?[A-Za-z_][A-Za-z0-9_$]*)" % re.escape(oc), pf)
    if simple:
        large_token = simple.group(1)
    else:
        brk = re.fullmatch(r"=IF\(\(?([A-Z]{1,3}\d+(?:\+[A-Z]{1,3}\d+)?)\)?<(\d+),\(%s\*(\$[A-Z]+\$\d+)\),\(%s\*([A-Za-z_][A-Za-z0-9_]*)\)\)"
                           % (re.escape(oc), re.escape(oc)), pf)
        if not brk:
            raise PlanError("%s: the media cost formula %s is not one this planner reads" % (where + col("P"), pf))
        combined = "+" in brk.group(1)
        threshold_lb = float(brk.group(2))
        small = brk.group(3)
        large_token = brk.group(4)
    large_addr, large = resolve_price(sh, large_token, where + col("P"))
    label = price_label(sh, large_addr) or product
    pack_large = bag * large
    price_breaks = None
    unit_cost = pack_large
    if small is not None:
        small_addr, small_price = resolve_price(sh, small, where + col("P"))
        unit_cost = bag * small_price
        price_breaks = [{"min_qty": threshold_lb / bag, "unit_cost": _money4(pack_large)}]
        if combined:
            plan.combined_breaks.add(label)
    coverage = _round_up_3(Fraction(_dec(bag)) / Fraction(_dec(per_sf)))
    per = sh.text(col("N"))
    if per == "Lb/SF":
        word, unit = "lb", "Bag"
    elif per == "SF/SF":
        word, unit = "SF", "Pack"
    else:
        raise PlanError("%s: the media unit %r is not one this planner reads" % (where + col("N"), per))
    name = "%s, %s %s %s, %s %s per SF" % (label, _g(bag), word, unit.lower(), _g(per_sf), word)
    item = _item("wb-epoxy-" + _slug(name), name, unit, 1, _money4(unit_cost), float(coverage), "Epoxy", "epoxy",
                 EPOXY_NOTE % large_addr, price_breaks=price_breaks)
    _set_vendor(item, discount_vendor(sh, large_addr, plan))
    plan.add_item(item)
    return {"role": "Media: " + label, "item_id": item["id"]}


def _system_headers(sh: Sheet, off: int, first: int, last: int) -> List[Tuple[int, str, str]]:
    """The rows where a system block starts: its name in column A, and in column I a formula that names the
    area cell the whole block divides. Returns (row, name, area cell)."""
    out = []
    a, i = shift("A", off), shift("I", off)
    for r in range(first, last + 1):
        name = sh.text("%s%d" % (a, r))
        f = sh.formula("%s%d" % (i, r))
        if name and isinstance(f, str) and re.fullmatch(r"=\$?%s\$?\d+" % re.escape(i), f):
            out.append((r, name, "%s%d" % (i, r)))     # the block divides ITS OWN area cell, column I of its first row
    return out


def plan_epoxy(sheets: Dict[str, Sheet], plan: Plan) -> None:
    sh = sheets[EPOXY_SHEET]
    seen: Dict[str, Tuple[str, List[Dict[str, Any]]]] = {}

    # the systems: the left half is System 1, the right half System 2 (the same floors again, and the walls)
    for off in (0, 26):
        heads = _system_headers(sh, off, 160, 345)
        ends = [h[0] for h in heads[1:]] + [346]
        for (row, name, _area), end in zip(heads, ends):
            area = _area
            lines: List[Dict[str, Any]] = []
            for r in range(row + 1, end):
                where = "Epoxy!"
                liquid = _liquid_line(sh, r, off, area, plan, where)
                if liquid:
                    lines.append(liquid)
            for r in range(row + 1, end):
                media = _media_line(sh, r, off, area, plan, "Epoxy!")
                if media:
                    lines.append(media)
            if not lines:
                raise PlanError("Epoxy!%s%d: the system %r has no lines" % (shift("A", off), row, name))
            if name in seen:
                if seen[name][1] != lines:
                    raise PlanError("the system %r is written twice in the Epoxy tab, and the two copies differ" % name)
                continue
            seen[name] = (name, lines)

    for name, lines in seen.values():
        plan.add_assembly({
            "id": "wb-epoxy-sys-" + _slug(name), "name": name, "unit": "SF", "category": "Epoxy",
            "description": "Seeded from Kyle's estimate workbook, Epoxy tab. One system: its liquids and its broadcast media.",
            "lines": lines, "default_work_types": ["epoxy"],
        })

    # the primers: one one-line assembly each (the sheet picks a primer per system)
    seen_primers: Dict[str, Dict[str, Any]] = {}
    for off in (0, 26):
        for r in range(161, 169):
            line = _liquid_line(sh, r, off, shift("I", off) + "160", plan, "Epoxy!")
            if not line:
                continue
            pname = sh.text("%s%d" % (shift("B", off), r))
            seen_primers[pname] = {"role": "Primer", "item_id": line["item_id"]}
    for pname, line in seen_primers.items():
        plan.add_assembly({
            "id": "wb-epoxy-primer-" + _slug(pname), "name": "Primer: " + pname, "unit": "SF",
            "category": "Epoxy",
            "description": "Seeded from Kyle's estimate workbook, Epoxy tab. The primer options of System 1 and System 2.",
            "lines": [line], "default_work_types": ["epoxy"],
        })

    _plan_epoxy_price_rows(sh, plan)
    _plan_epoxy_cove_assemblies(sh, plan)
    _plan_epoxy_labor(sh, plan)

    if plan.combined_breaks:
        plan.gap("A price break the sheet judges on two broadcast lines added together is read the same way by the "
                 "estimate: the two lines, two library rows on one price ladder, are pooled for the break, and each "
                 "coat keeps its own whole-pack rounding as the sheet does, so a single-area job is the workbook's "
                 "price. Materials: %s." % ", ".join(sorted(plan.combined_breaks)))
    plan.gap("Coverage is kept to three places (a bag of flake that covers 266.6667 SF is stored as 266.667, "
             "rounded up so it cannot buy a bag the sheet does not).")
    plan.gap("Cove is two ROUNDUPs deep and its aggregate follows System 1 (Kyle's odd rule 11): it is priced by "
             "a formula in code, from the editable price rows this seed writes.")
    plan.gap("Bulk Discount is stored (bulk_cost) and not used: the v2 model has no Bulk Discount switch yet.")


# the price sources the code-priced formulas read. id -> (what it is, where its price sits, the unit, the pack)
RESERVED_PRICE_ROWS: Dict[str, Dict[str, Any]] = {
    "wb-epoxy-patch": {"name": "Patch, per SF", "cell": "C18", "unit": "SF", "pack": 1},
    "wb-epoxy-cove-rez": {"name": "Cove Rez, per gallon", "cell": "T152", "unit": "Gallon", "pack": 1},
    "wb-epoxy-cove-wr": {"name": "WR cove kit", "cell": "T167", "unit": "Kit", "pack": 1},
    "wb-epoxy-cove-silica": {"name": "Silica for cove, 50 lb bag", "cell": "W145", "unit": "Bag", "pack": 50},
    "wb-epoxy-cove-q28": {"name": "Q28 / 40-S quartz for cove, 50 lb bag", "cell": "W148", "unit": "Bag", "pack": 50},
    "wb-epoxy-cove-zinc-cap": {"name": "Zinc cove cap, per LF", "cell": "W150", "unit": "LF", "pack": 1},
}

COVE_ASSEMBLIES_FROM = ("S125", "S136")      # the twelve names of the Cove 1 Options list


def _plan_epoxy_price_rows(sh: Sheet, plan: Plan) -> None:
    for id_, spec in RESERVED_PRICE_ROWS.items():
        addr = spec["cell"]
        v = sh.value(addr)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise PlanError("Epoxy!%s should hold the price of %s, found %r" % (addr, spec["name"], v))
        pack = spec["pack"]
        row = _item(
            id_, spec["name"], spec["unit"], float(pack), _money4(float(v) * pack), 1.0, "Epoxy", "epoxy",
            "Price source for a formula in js/epoxy-takeoff.js (Epoxy!%s). Edit the price here; the formula is code." % addr)
        row["roundup"] = False        # a price source is read per unit by the formula; nothing is bought from it by pack
        _set_vendor(row, discount_vendor(sh, addr, plan))
        plan.add_item(row)


def _plan_epoxy_cove_assemblies(sh: Sheet, plan: Plan) -> None:
    first = int(COVE_ASSEMBLIES_FROM[0][1:])
    last = int(COVE_ASSEMBLIES_FROM[1][1:])
    for r in range(first, last + 1):
        name = sh.text("S%d" % r)
        if not name:
            raise PlanError("Epoxy!S%d should name a cove option" % r)
        wr = name.startswith("WR")
        lines = [{"role": "Cove liquids", "item_id": "wb-epoxy-cove-wr" if wr else "wb-epoxy-cove-rez"}]
        if not wr:
            lines.append({"role": "Aggregate", "item_id": "wb-epoxy-cove-silica"})
        if "Cap" in name:
            lines.append({"role": "Cap", "item_id": "wb-epoxy-cove-zinc-cap"})
        plan.add_assembly({
            "id": "wb-epoxy-cove-" + _slug(name), "name": "Cove: " + name, "unit": "LF", "category": "Epoxy",
            "description": "Seeded from Kyle's estimate workbook, Epoxy tab (Cove 1 Options). Priced by a formula in "
                           "code (it rounds twice); the rows listed here are the prices it reads.",
            "lines": lines, "default_work_types": ["epoxy"],
        })


def _plan_epoxy_labor(sh: Sheet, plan: Plan) -> None:
    """Kyle's Epoxy tab has one crew line with a crew in it: System 1, three guys (A47), at $33 (C47). Days are
    left blank, as they are on the Polish crew lines, because the estimator judges them."""
    guys = _number(sh.value("A47"), "Epoxy!A47")
    rate = _number(sh.value("C47"), "Epoxy!C47")
    label = sh.text("E47")
    if label != "System 1":
        raise PlanError("Epoxy!E47 should label the first crew line System 1, found %r" % label)
    plan.labor["epoxy-install"] = {
        "id": "epoxy-install", "name": "Epoxy install", "rate": rate, "unit": "days", "guys_auto": False,
        "sort": 4, "favorite": True, "default_work_types": ["epoxy"],
    }
    plan.labor_calc["epoxy-install"] = {
        "line_id": "epoxy-install", "mode": "fixed", "hours_per_day": 8, "guys": guys,
    }


# ── Gyp: the products, the three areas of a takeoff, and the crew ────────────
GYP_NOTE = "Seeded from Kyle's estimate workbook, %s tab, cell %s. A price source for js/gyp-takeoff.js: edit the price here, the formula is code."

# The three areas a Gyp takeoff is made of. A row of each is a line of the takeoff; js/gyp-takeoff.js prices it (a
# bag's yield depends on the thickness, which a library line cannot say), so the line listed here is the gypsum the
# sheet reads its price from. `cell` is the sheet's own SF cell for the area.
GYP_AREAS = [
    ("wb-gyp-area-soft", "Gypsum: soft surfaces", "F23"),
    ("wb-gyp-area-hard", "Gypsum: hard surfaces over the sound mat", "F24"),
    ("wb-gyp-area-corridor", "Gypsum: corridors", "F25"),
]

# The five crew lines of the Gyp sheets, priced by the hour (A45:C49): the sheet's label, the name the library row
# gets, and the guys the sheet puts on it. Guys and hours are the estimator's to type, so only the line and its rate
# are seeded; the crew goes into the gap text.
GYP_CREW = [
    ("gyp-prepour", "Pre-pour", "Pre-Pours Hours", "A45"),
    ("gyp-prep", "Prep, prime and seal", "Prep/Prime/Seal Hours", "A46"),
    ("gyp-mat", "Mat time", "Mat Time Hours", "A47"),
    ("gyp-pour", "Pour", "Pour Hours", "A48"),
    ("gyp-unload", "Semi delivery unload", "Semi Delivery Unload Hours", "A49"),
]


def _gyp_item(plan: Plan, sheet: Sheet, id_: str, name: str, unit: str, addr: str, pack: float = 1.0,
              coverage: Optional[float] = None, cost: Optional[float] = None) -> str:
    """One Gyp product at the price its cell holds. `pack` is the units a purchase buys (a 53 gallon drum), so the
    row's cost is the cell's value times the pack and a price per unit comes back exactly (891 / 53)."""
    v = sheet.value(addr) if cost is None else cost
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise PlanError("%s!%s should hold the price of %s, found %r" % (sheet.name, addr, name, v))
    return plan.add_item(_item(id_, name, unit, pack, _money4(float(v) * pack), coverage,
                               "Gypsum Underlayment", "gyp", GYP_NOTE % (sheet.name, addr)))


def _gyp_mats(plan: Plan, sh: Sheet, rows: Tuple[int, ...], name_col: str, price_col: str, sf_col: str,
              seen: Dict[str, Tuple[float, float]]) -> None:
    """The sound mats of one Gyp tab's table: a roll's price and the SF a roll covers. A mat that both tabs carry
    (the GrassWorx ones) must say the same on both, or the plan stops."""
    for r in rows:
        name = sh.text("%s%d" % (name_col, r))
        price, per_roll = sh.value("%s%d" % (price_col, r)), sh.value("%s%d" % (sf_col, r))
        if not name or not isinstance(price, (int, float)) or not isinstance(per_roll, (int, float)):
            raise PlanError("%s!%s%d:%s%d should hold a sound mat, its roll price and its roll size" % (
                sh.name, name_col, r, sf_col, r))
        label = "Sound mat %s, roll" % name
        figures = (_money4(float(price)), float(per_roll))
        if name in seen:
            if seen[name] != figures:
                raise PlanError("the sound mat %r is %r on one Gyp tab and %r on another" % (name, seen[name], figures))
            continue                       # the same product on both tabs is one library row
        seen[name] = figures
        plan.add_item(_item("wb-gyp-" + _slug(label), label, "Roll", 1.0, figures[0], figures[1],
                            "Gypsum Underlayment", "gyp", GYP_NOTE % (sh.name, "%s%d" % (price_col, r))))


def plan_gyp(sheets: Dict[str, Sheet], plan: Plan) -> None:
    sh = sheets[GYP_SHEET]
    fr = sheets[GYP_FR_SHEET]
    # the USG tabs: bag, primer (a 53 gallon drum, so the gallon is exactly 891 / 53), ISO strip, tape, sand
    _gyp_item(plan, sh, "wb-gyp-levelrock-2500-bag", "Levelrock 2500, bag", "Bag", "D23")
    _gyp_item(plan, sh, "wb-gyp-levelrock-3500-bag", "Levelrock 3500, bag", "Bag", "V37")
    _gyp_item(plan, sh, "wb-gyp-usg-primer-53-gallon-drum", "USG primer, 53 gallon drum", "Gallon", "D27", pack=53.0,
              cost=_number(sh.value("D27"), GYP_SHEET + "!D27"))
    _gyp_item(plan, sh, "wb-gyp-wood-primer-5-gallon-per-gallon", "Wood primer, 5 gallon, per gallon", "Gallon", "T38")
    _gyp_item(plan, sh, "wb-gyp-iso-strip-3-inch-adhesive-roll", "ISO strip, 3 inch adhesive roll", "Roll", "D28")
    _gyp_item(plan, sh, "wb-gyp-joint-tape-roll", "Joint tape roll", "Roll", "D29")
    _gyp_item(plan, sh, "wb-gyp-sand-per-ton", "Sand, per ton", "Ton", "D33")
    # Gyp (FR): its own bag, primer (5 gallons at 139.50) and ISO strip. Its joint tape and sand cost what the USG
    # tabs' do, which the plan checks rather than assumes.
    _gyp_item(plan, fr, "wb-gyp-treadstone-fr25-bag", "Treadstone FR25, bag", "Bag", "D23")
    _gyp_item(plan, fr, "wb-gyp-treadstone-primer-tp1-gallon", "Treadstone primer TP1, 5 gallon", "Gallon", "D27",
              pack=5.0, cost=_number(fr.value("D27"), GYP_FR_SHEET + "!D27"))
    _gyp_item(plan, fr, "wb-gyp-iso-strip-roll", "ISO strip, roll (Gyp FR)", "Roll", "D28")
    for addr in ("D29", "D33"):
        if sh.value(addr) != fr.value(addr):
            raise PlanError("Gyp (FR)!%s is %r and the USG tab's is %r: the two tabs no longer share this price" % (
                addr, fr.value(addr), sh.value(addr)))
    # the sound mats: a price per roll and the SF a roll covers. The USG and GrassWorx table (O37:Q44) on the first
    # tab, and Gyp (FR)'s own (N37:P44, one column further left).
    seen: Dict[str, Tuple[float, float]] = {}
    _gyp_mats(plan, sh, (37, 38, 39, 40, 42, 43, 44), "O", "P", "Q", seen)
    _gyp_mats(plan, fr, (37, 38, 39, 42, 43, 44), "N", "O", "P", seen)

    # the three areas of a takeoff, each listing the gypsum bag its price is read from
    for id_, name, cell in GYP_AREAS:
        plan.add_assembly({
            "id": id_, "name": name, "unit": "SF", "category": "Gypsum Underlayment",
            "description": "Seeded from Kyle's estimate workbook, Gyp tabs (%s). One area of a Gyp takeoff. Priced by "
                           "a formula in code (a bag's yield depends on the thickness); the bag listed here is the "
                           "price it reads. The primer, ISO strip, tape, sand and sound mat are worked out from all "
                           "the areas together." % cell,
            "lines": [{"role": "Gypsum bags", "item_id": "wb-gyp-levelrock-2500-bag"}],
            "default_work_types": ["gyp"],
        })

    # the crew: five lines priced by the hour at the Gyp tabs' rate
    rate = _number(sh.value("C45"), GYP_SHEET + "!C45")
    for sort, (id_, name, label, guys_cell) in enumerate(GYP_CREW, start=10):
        if not sh.text("F%s" % guys_cell[1:]).startswith(label):
            raise PlanError("%s!F%s should label the line %r, found %r" % (GYP_SHEET, guys_cell[1:], label,
                                                                          sh.text("F%s" % guys_cell[1:])))
        plan.labor[id_] = {
            "id": id_, "name": name, "rate": rate, "unit": "hours", "guys_auto": False, "sort": sort,
            "favorite": True, "default_work_types": ["gyp"],
        }
    crew = [int(_number(sh.value(c[3]), GYP_SHEET + "!" + c[3])) for c in GYP_CREW]
    plan.gap("Gyp bags are fractional and their yield depends on the thickness and the mix (Kyle's odd rule 7): they are "
             "priced by a formula in js/gyp-takeoff.js from the editable price rows above, as are the sand, the "
             "primer, the ISO strip and the tape. The sound mat's rolls and the truckload that waives its shipping are "
             "counted there too (odd rule 6).")
    plan.gap("The Gyp sheets work the labor hours out of the takeoff (mobilizations, bags a pour hour, the hard area a mat "
             "hour). v2 seeds the five lines (guys %s on the sheet) at $%s an hour and leaves the hours to be typed, "
             "quoting the sheet's own figures beside them." % (", ".join(str(c) for c in crew), _g(rate)))
    plan.gap("Gyp (FR) has its own bag, primer and ISO strip, and a catalogue of its own mats; the truckload on that "
             "tab is a typed 448 whichever mat is picked, where the other four tabs follow the mat.")


# ── Seal: the sealer, the joint filler, the patch's two prices, and the crew ──
SEAL_NOTE = "Seeded from Kyle's estimate workbook, %s tab, cell %s. %s"
# The Seal tab's own formulas, checked by text, so a sheet that Kyle changes stops the run with the cell named instead
# of seeding a price for a rule the code no longer matches.
SEAL_PATCH_FORMULA = re.compile(r'^=IF\(B10="New",(\d*\.?\d+),(\d*\.?\d+)\)$')
SEAL_JF_FORMULA = '=ROUNDUP(IF(E29="yes",(E18/3500),0),0)'
SEAL_JF_COVERAGE = 3500.0
SEAL_JF_GUYS_FORMULA = '=IF(F29="NO",2,4)'

# The four assemblies a Seal option is made of, by name: the sheet ships with both sealer lines filled in (D20, D21:
# "Grind + Seal = 2 Coats"; delete the second for "Clean + Seal = 1 Coat"), and Seal (+Jnts) adds the joint filler kit.
SEAL_ASSEMBLIES = [
    ("wb-seal-1-coat", "Seal, 1 coat (clean + seal)", 1, False),
    ("wb-seal-2-coats", "Seal, 2 coats (grind + seal)", 2, False),
    ("wb-seal-jnts-1-coat", "Seal + joint filler, 1 coat (clean + seal)", 1, True),
    ("wb-seal-jnts-2-coats", "Seal + joint filler, 2 coats (grind + seal)", 2, True),
]
# The crew: the sheet's three crew lines (A37, A40 and A42), at the Seal sheet's rate. Guys and days are the estimator's,
# so only the line and its rate are seeded, as for the Epoxy and Gyp crews.
SEAL_CREW = [("seal-install", "Seal install", "A37", 20), ("seal-mockup", "Mock-up", "A40", 21),
             ("seal-jointfill", "Joint filler", "A42", 22)]


def _seal_price_row(plan: Plan, id_: str, name: str, unit: str, cost: float, coverage: float, roundup: bool,
                    where: str, how: str) -> None:
    row = _item(id_, name, unit, 1.0, _money4(cost), coverage, "Polished Concrete", "seal",
                SEAL_NOTE % (SEAL_SHEET, where, how))
    row["roundup"] = roundup
    plan.add_item(row)


def plan_seal(sheets: Dict[str, Sheet], plan: Plan) -> None:
    sh = sheets[SEAL_SHEET]
    jn = sheets[SEAL_JNTS_SHEET]
    # the patch: one formula, two prices (a new floor and a renovation), read by js/seal-takeoff.js
    f = sh.formula("C17")
    m = SEAL_PATCH_FORMULA.match(f) if isinstance(f, str) else None
    if not m:
        raise PlanError('Seal!C17 should be =IF(B10="New",<new price>,<reno price>), found %r' % (f,))
    new_price, reno_price = float(m.group(1)), float(m.group(2))
    howp = "Price source for a formula in js/seal-takeoff.js. Edit the price here; the formula is code."
    _seal_price_row(plan, "wb-seal-patch-new", "Patch, new concrete, per SF", "SF", new_price, 1.0, False, "C17", howp)
    _seal_price_row(plan, "wb-seal-patch-reno", "Patch, renovation, per SF", "SF", reno_price, 1.0, False, "C17", howp)
    # the sealer: the two lines of the sheet are the same product at the same price
    c20, c21 = _number(sh.value("C20"), SEAL_SHEET + "!C20"), _number(sh.value("C21"), SEAL_SHEET + "!C21")
    if c20 != c21:
        raise PlanError("Seal!C20 is %r and C21 is %r: the two sealer lines no longer cost the same" % (c20, c21))
    if sh.text("A20") != "Sealer" or sh.text("A21") != "Sealer":
        raise PlanError("Seal!A20 and A21 should both name the sealer, found %r and %r" % (sh.text("A20"), sh.text("A21")))
    _seal_price_row(plan, "wb-seal-sealer", "Sealer, per coat, per SF", "SF", c20, 1.0, False, "C20 and C21",
                    "One coat of sealer over one square foot. Edit the price here.")
    # the joint filler kit: Seal (+Jnts) buys one kit (a 10 gallon kit, $500) for every 3,500 SF
    if jn.formula("B29") != SEAL_JF_FORMULA:
        raise PlanError("%s!B29 should be %s, found %r" % (SEAL_JNTS_SHEET, SEAL_JF_FORMULA, jn.formula("B29")))
    kit = _number(jn.value("C29"), SEAL_JNTS_SHEET + "!C29")
    jf = _item("wb-seal-joint-filler-kit", "Joint filler, 10 gal kit (Seal)", "Kit", 1.0, _money4(kit), SEAL_JF_COVERAGE,
               "Polished Concrete", "seal", SEAL_NOTE % (SEAL_JNTS_SHEET, "C29", "One kit for every 3,500 SF, rounded up."))
    plan.add_item(jf)
    # the four assemblies
    for id_, name, coats, joints in SEAL_ASSEMBLIES:
        lines = [{"role": "Sealer coat %d" % (n + 1), "item_id": "wb-seal-sealer"} for n in range(coats)]
        if joints:
            lines.append({"role": "Joint filler", "item_id": "wb-seal-joint-filler-kit"})
        plan.add_assembly({
            "id": id_, "name": name, "unit": "SF", "category": "Polished Concrete",
            "description": "Seeded from Kyle's estimate workbook, Seal tabs. A new Seal option opens with %s. The patch "
                           "and the tooling are added by js/seal-takeoff.js, not listed here." % (
                               "the sealer" + (" and the joint filler" if joints else "")),
            "lines": lines, "default_work_types": ["seal"],
        })
    # the crew
    rate = _number(sh.value("C37"), SEAL_SHEET + "!C37")
    if jn.formula("A42") != SEAL_JF_GUYS_FORMULA:
        raise PlanError("%s!A42 should be %s, found %r" % (SEAL_JNTS_SHEET, SEAL_JF_GUYS_FORMULA, jn.formula("A42")))
    guys = {"A37": _number(sh.value("A37"), SEAL_SHEET + "!A37"), "A40": _number(sh.value("A40"), SEAL_SHEET + "!A40"),
            "A42": 2.0}     # two guys on the joint filler unless existing joint filler is removed, which makes it four
    for id_, name, cell, sort in SEAL_CREW:
        plan.labor[id_] = {"id": id_, "name": name, "rate": rate, "unit": "days", "guys_auto": False, "sort": sort,
                           "favorite": True, "default_work_types": ["seal"]}
        plan.labor_calc[id_] = {"line_id": id_, "mode": "fixed", "hours_per_day": 8, "guys": guys[cell]}
    plan.gap("The Seal patch is charged on the whole area, always, at the new-concrete price or the renovation price by the "
             "job's Renovation answer (Seal!B10), as the sheet does. v2 reads that answer off the draft; the sheet's "
             "'Exclude Patching?' note is a typed edit of the price, which v2 does not carry.")
    plan.gap("Tooling and consumables are $0.27 a square foot with a $150 floor, in code (js/seal-takeoff.js). The sheet's "
             "demo tooling, slurry hardener and plastic are typed quantities that v2 does not carry.")
    plan.gap("The Seal sheets work the joint filler crew's days out of the area (Seal (+Jnts)!B42) and the mock-up is half a "
             "day by default. v2 seeds the three crew lines (guys 3, 3 and 2 on the sheet) at $%s a day and leaves the days "
             "to be typed." % _g(rate))
    plan.gap("The Seal sheets charge their OWN lodging, per diem and travel labor (the drive hours are copied from the Polish "
             "tab). v2 charges the job's travel once, on the base bid; an option carries its own Lodging and Per Diem for its own "
             "crew when the job is on the road (the sheet works its nights out from labor dollars, v2 from the crew's man-days, "
             "so a crew on mixed rates differs by a night or two), and its drive hours are typed.")


# ── Polish: the three per-SF materials, and one assembly for each polish system ──
POLISH_NOTE = "Seeded from Kyle's estimate workbook, %s tab, cell %s. %s"
# The Polish tab's material formulas, checked by text so a sheet Kyle changes stops the run with the cell named. None of
# them reads the polish system (F36): the SYSTEM changes the labor and the tooling (the calculator at P4:W16), never the
# material lines. The one condition is the grout, which the sheet charges when I36 says "Yes Grout" (a note at I35 says
# "Grout for Full Agg Only").
POLISH_AREA_FORMULA = "=E18"
POLISH_GROUT_FORMULA = '=IF(I36="Yes Grout",E18)'
# the polish systems the sheet's labor calculator prices (P14:P16), the name an assembly gets, and whether grout is in it
POLISH_SYSTEMS = [
    ("S&P", "wb-polish-sys-salt-and-pepper", "Polish — Salt & Pepper", False),
    ("Cream", "wb-polish-sys-cream", "Polish — Cream", False),
    ("Full", "wb-polish-sys-full-aggregate", "Polish — Full aggregate", True),
]


def _polish_price_row(sh: Sheet, plan: Plan, id_: str, name: str, cell: str, how: str) -> None:
    price = _number(sh.value(cell), POLISH_SHEET + "!" + cell)
    row = _item(id_, name, "SF", 1.0, _money4(price), 1.0, "Polished Concrete", "polish",
                POLISH_NOTE % (POLISH_SHEET, cell, how))
    row["roundup"] = False        # per square foot, so the cost is the area times the price and never a whole pack
    plan.add_item(row)


def plan_polish(sheets: Dict[str, Sheet], plan: Plan) -> None:
    sh = sheets[POLISH_SHEET]
    where = POLISH_SHEET + "!"
    # the three material lines: label, the quantity formula (the whole area, never the system) and the cost formula
    for row, label, qty in ((20, "Densifier", POLISH_AREA_FORMULA), (21, "Sealer", POLISH_AREA_FORMULA),
                            (22, "Grout Compound", POLISH_GROUT_FORMULA)):
        if not sh.text("A%d" % row).startswith(label):
            raise PlanError("%sA%d should name the %s line, found %r" % (where, row, label.lower(), sh.text("A%d" % row)))
        if sh.formula("B%d" % row) != qty:
            raise PlanError("%sB%d should be %s, found %r: the quantity rule of the %s line has changed"
                            % (where, row, qty, sh.formula("B%d" % row), label.lower()))
        if sh.formula("D%d" % row) != "=B%d*C%d" % (row, row):
            raise PlanError("%sD%d should be =B%d*C%d, found %r" % (where, row, row, row, sh.formula("D%d" % row)))
    if "full agg" not in sh.text("I35").lower():
        raise PlanError("%sI35 should say the grout is for Full Aggregate only, found %r" % (where, sh.text("I35")))
    _polish_price_row(sh, plan, "wb-polish-densifier", "Densifier, per SF", "C20",
                      "One square foot of the whole area. Edit the price here.")
    _polish_price_row(sh, plan, "wb-polish-sealer", "Polish sealer, per SF", "C21",
                      "One square foot of the whole area, one coat. This is the POLISH sealer; the Seal tab's sealer "
                      "is its own row. Edit the price here.")
    _polish_price_row(sh, plan, "wb-polish-grout-compound", "Grout compound, per SF", "C22",
                      "One square foot of the whole area, charged by the sheet only when the floor is grouted (a "
                      "full aggregate polish). Edit the price here.")
    # the systems: the names come from the calculator's own labels (P14:P16), so a renamed system stops the run
    for label, id_, name, grout in POLISH_SYSTEMS:
        cell = {"Cream": "P14", "S&P": "P15", "Full": "P16"}[label]
        if sh.text(cell) != label:
            raise PlanError("%s%s should label the %s system, found %r" % (where, cell, label, sh.text(cell)))
        lines = [{"role": "Densifier", "item_id": "wb-polish-densifier"}, {"role": "Sealer", "item_id": "wb-polish-sealer"}]
        if grout:
            lines.append({"role": "Grout compound", "item_id": "wb-polish-grout-compound"})
        plan.add_assembly({
            "id": id_, "name": name, "unit": "SF", "category": "Polished Concrete",
            "description": "Seeded from Kyle's estimate workbook, Polish tab (%s). The per-SF materials the sheet charges for "
                           "this system: %s. Dye and joint filler are priced by the job's conditions and the patch by the "
                           "job's New / Reno answer, so none is listed here." % (
                               cell, "densifier, sealer" + (" and grout compound" if grout else "")),
            "lines": lines, "default_work_types": ["polish"],
        })
    plan.gap("The sheet's material lines do not depend on the polish system: Salt & Pepper and Cream charge the same "
             "densifier (C20) and sealer (C21), and the system changes the labor and tooling (the calculator at P4:W16). "
             "The three assemblies exist so the estimator picks by name; only Full aggregate adds the grout compound (C22).")
    plan.gap("The sheet charges grout (B22) whenever the Grout? box (I36) says Yes Grout, on any system, though its own note "
             "(I35) says full aggregate only. The library says it the way the note does: grout is a line of the Full "
             "aggregate assembly, and a Salt & Pepper or Cream job cannot carry it by the picker.")
    plan.gap("Not in the library, priced by code or typed: the patch (C17, D17: New / Reno price rows are the Seal tab's), dye "
             "(C25, C26, E25) and joint filler (B29, C29, E29) by the job's conditions, shipping (B32, D32, 2%), the "
             "sub-total roundup (D31), tooling and consumables (C51, D51, from the calculator V10:W10), demo tooling "
             "(C52), slurry hardener (B53, C53) and plastic (B54, C54), the Standard Add's table (H17:K22, priced from "
             "the validation tab's tiers) and the Potential Add Options (I28:I30).")


# ── the whole plan ───────────────────────────────────────────────────────────
def make_plan(path: pathlib.Path = TEMPLATE_PATH, only: str = "all", sheets: Optional[Dict[str, Sheet]] = None) -> Plan:
    """The plan for the workbook at `path`. `sheets` is for a caller that has already read it (reading the template
    takes several seconds, planning takes a tenth of one) and wants to plan from it again."""
    if only not in ("all", "epoxy", "gyp", "seal", "polish"):
        raise PlanError("--only is epoxy, gyp, seal, polish or all")
    if sheets is None:
        sheets = load(path)
    plan = Plan()
    if only in ("all", "epoxy"):
        plan_epoxy(sheets, plan)
    if only in ("all", "gyp"):
        plan_gyp(sheets, plan)
    if only in ("all", "seal"):
        plan_seal(sheets, plan)
    if only in ("all", "polish"):
        plan_polish(sheets, plan)
    return plan


# ── statements ───────────────────────────────────────────────────────────────
def _lit(v: Any) -> str:
    """One value as a SQL literal. Text is quoted with its quotes doubled, so a name with an apostrophe or a
    double quote in it cannot break the statement."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise PlanError("a number that is not a number cannot be written")
        return repr(v) if isinstance(v, float) else str(v)
    if isinstance(v, (list, dict)):
        return "'" + json.dumps(v, sort_keys=True).replace("'", "''") + "'::jsonb"
    return "'" + str(v).replace("'", "''") + "'"


ITEM_COLUMNS = ["id", "name", "unit", "buy_qty", "unit_cost", "coverage", "waste_pct", "roundup", "divisions",
                "category", "default_work_types", "notes", "bulk_cost", "price_breaks", "vendor"]
ASSEMBLY_COLUMNS = ["id", "name", "unit", "lines", "category", "description", "default_work_types"]
LABOR_COLUMNS = ["id", "name", "rate", "unit", "guys_auto", "sort", "favorite", "default_work_types"]
CALC_COLUMNS = ["line_id", "mode", "hours_per_day", "guys"]

TABLES = [
    ("library_items", ITEM_COLUMNS, "id", "items"),
    ("library_assemblies", ASSEMBLY_COLUMNS, "id", "assemblies"),
    ("library_labor", LABOR_COLUMNS, "id", "labor"),
    ("library_labor_calc", CALC_COLUMNS, "line_id", "labor_calc"),
]


def statements(plan: Plan) -> List[str]:
    """One `insert ... on conflict do nothing` per row, in a fixed order. Nothing else is ever written."""
    data = plan.as_dict()
    out: List[str] = []
    for table, columns, key, bucket in TABLES:
        for row in data[bucket]:
            cols = [c for c in columns if c in row]
            out.append("insert into public.%s (%s) values (%s) on conflict (%s) do nothing;" % (
                table, ", ".join(cols), ", ".join(_lit(row[c]) for c in cols), key))
    return out


def vendor_statements(plan: Plan) -> List[str]:
    """The supplier names the items' `vendor` text uses, as dropdown rows. Still an insert that cannot overwrite: a row is
    added only when no live vendor of that name is there already (the Items tab refuses a duplicate name the same way,
    ignoring case and space), and the id is the name's slug, so a second run adds nothing."""
    out: List[str] = []
    for name in sorted(plan.vendors):
        v = plan.vendors[name]
        out.append("insert into public.library_vendors (id, name, notes) select %s, %s, %s where not exists "
                   "(select 1 from public.library_vendors where lower(trim(name)) = lower(%s) and deleted_at is null) "
                   "on conflict (id) do nothing;" % (_lit(v["id"]), _lit(v["name"]), _lit(v["notes"]), _lit(v["name"])))
    return out


# ── the exceptions to insert-only: each behind its own flag, in its own named group ──
GROUP_TAG_VENDORS = "tag-vendors"
GROUP_GYP_SAND = "gyp-sand-40"
GROUP_BETA_SAMPLE = "retire-beta-sample"
GROUPS = (GROUP_TAG_VENDORS, GROUP_GYP_SAND, GROUP_BETA_SAMPLE)

# Kyle's 10.01 master has Gyp (USG 1-8") D33, Sand (per Ton), at 40 where the 5.7 template says 35. The template file is
# not changed (the plan, the code's fallbacks and their pin tests all read 35), so the move is its own statement.
GYP_SAND_ID = "wb-gyp-sand-per-ton"
GYP_SAND_FROM = 35.0
GYP_SAND_TO = 40.0
# The two rows the beta placed in the library to try the Polish section with. Their ids were generated by the library
# API and are not in any file, so they are found by exact name; a statement touches a row only if it is still live.
BETA_ASSEMBLY_NAME = "Polish — Salt & Pepper (beta sample)"
BETA_ITEM_NAME = "OPF — 5 gal pail (beta sample)"


def tag_vendor_statements(plan: Plan) -> List[str]:
    """Fill `vendor` on a row that already exists and has none. Only the vendor column, only where it is NULL."""
    tagged = [it for it in plan.as_dict()["items"] if it.get("vendor")]
    if not tagged:
        raise PlanError("--tag-vendors found no row with a discount group in the plan: it needs the epoxy plan "
                        "(--only all or epoxy)")
    return ["update public.library_items set vendor = %s where id = %s and vendor is null;" % (_lit(it["vendor"]), _lit(it["id"]))
            for it in tagged]


def gyp_sand_statements(plan: Plan) -> List[str]:
    it = plan.items.get(GYP_SAND_ID)
    if it is None:
        raise PlanError("--gyp-sand-40 needs the gyp plan (--only all or gyp)")
    if it["unit_cost"] != GYP_SAND_FROM:
        raise PlanError("the workbook's sand is %r now, not %r: the 35 to 40 move was written for the 5.7 template"
                        % (it["unit_cost"], GYP_SAND_FROM))
    return ["update public.library_items set unit_cost = %s where id = %s and unit_cost = %s;"
            % (_lit(GYP_SAND_TO), _lit(GYP_SAND_ID), _lit(GYP_SAND_FROM))]


def _ascii_lit(text: str) -> str:
    """A text literal with every character outside ASCII written as chr(code), so the script is plain ASCII and no console,
    pipe or ssh encoding can turn the em dash of a name into another character and make a statement match nothing."""
    parts = re.split(r"([^\x00-\x7f])", text)
    return " || ".join("chr(%d)" % ord(p) if len(p) == 1 and ord(p) > 127 else _lit(p) for p in parts if p != "")


def beta_sample_statements() -> List[str]:
    return ["update public.library_assemblies set deleted_at = now() where name = (%s) and deleted_at is null;" % _ascii_lit(BETA_ASSEMBLY_NAME),
            "update public.library_items set deleted_at = now() where name = (%s) and deleted_at is null;" % _ascii_lit(BETA_ITEM_NAME)]


def exception_statements(plan: Plan, groups: Tuple[str, ...]) -> List[str]:
    """The statements of the groups asked for, each under a comment that names it. Empty for no groups."""
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        raise PlanError("unknown statement group %s (the groups are %s)" % (", ".join(unknown), ", ".join(GROUPS)))
    makers = {GROUP_TAG_VENDORS: ("fill vendor where it is still NULL", lambda: tag_vendor_statements(plan)),
              GROUP_GYP_SAND: ("sand 35 to 40, only where it is still 35", lambda: gyp_sand_statements(plan)),
              GROUP_BETA_SAMPLE: ("soft-delete the two beta sample rows, only where live", beta_sample_statements)}
    out: List[str] = []
    for g in GROUPS:
        if g in groups:
            out.append("-- EXCEPTION GROUP %s (not insert-only): %s" % (g, makers[g][0]))
            out.extend(makers[g][1]())
    return out


def sql_script(plan: Plan, groups: Tuple[str, ...] = ()) -> str:
    body = statements(plan) + vendor_statements(plan) + exception_statements(plan, tuple(groups))
    return "begin;\n" + "\n".join(body) + "\ncommit;\n"


# ── applying it ──────────────────────────────────────────────────────────────
def apply_to_staging(plan: Plan, runner=None, groups: Tuple[str, ...] = ()) -> str:
    """Run the statements inside the staging database container, over ssh. `runner(args, input)` is how a test
    stands in for ssh. Returns what psql printed."""
    script = sql_script(plan, groups)
    args = ["ssh", STAGING_SSH_HOST, "docker", "exec", "-i", STAGING_DB_CONTAINER,
            "psql", "-U", STAGING_DB_USER, "-d", STAGING_DB_NAME, "-v", "ON_ERROR_STOP=1", "-q"]
    if runner is None:
        done = subprocess.run(args, input=script, capture_output=True, text=True, encoding="utf-8", check=False)
        if done.returncode != 0:
            raise PlanError("psql over ssh failed (%d): %s" % (done.returncode, done.stderr.strip()))
        return done.stdout
    return runner(args, script)


def describe(plan: Plan) -> str:
    c = plan.counts()
    lines = ["PLAN (a dry run writes nothing)",
             "  library_items       %4d" % c["items"],
             "  library_assemblies  %4d" % c["assemblies"],
             "  library_labor       %4d" % c["labor"],
             "  library_labor_calc  %4d" % c["labor_calc"], ""]
    for it in plan.as_dict()["items"]:
        extra = ""
        if it.get("price_breaks"):
            extra += "  breaks " + json.dumps(it["price_breaks"])
        if it.get("bulk_cost") is not None:
            extra += "  bulk %s" % it["bulk_cost"]
        if it.get("vendor"):
            extra += "  vendor " + it["vendor"]
        lines.append("  item  %-62s %-8s pack %-5s cost %-10s cov %-9s%s" % (
            it["id"], it["unit"], _g(it["buy_qty"]), it["unit_cost"], it["coverage"], extra))
    for a in plan.as_dict()["assemblies"]:
        lines.append("  asm   %-62s %-3s %d line(s)" % (a["id"], a["unit"], len(a["lines"])))
    for name in sorted(plan.vendors):
        lines.append("  vendor %-61s (dropdown row, added only if no live vendor has the name)" % name)
    for r in plan.as_dict()["labor"]:
        lines.append("  labor %-62s %s/%s" % (r["id"], r["rate"], r["unit"]))
    lines += ["", "NAMED MODELLING GAPS (for Kyle):"] + ["  - " + g for g in plan.gaps]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--only", default="all", choices=["all", "epoxy", "gyp", "seal", "polish"])
    ap.add_argument("--sql", action="store_true", help="print the statements, write nothing")
    ap.add_argument("--json", action="store_true", help="print the plan as JSON, write nothing (what the tests read)")
    ap.add_argument("--tag-vendors", action="store_true",
                    help="also fill vendor on existing Epoxy rows, only where it is NULL (an exception to insert-only)")
    ap.add_argument("--gyp-sand-40", action="store_true",
                    help="also move the Gyp sand price from 35 to 40, only where it is still 35 (an exception to insert-only)")
    ap.add_argument("--retire-beta-sample", action="store_true",
                    help="also soft-delete the two beta sample rows by name (an exception to insert-only)")
    ap.add_argument("--apply", action="store_true", help="write the plan (needs --target staging)")
    ap.add_argument("--target", default=None, help="staging is the only target; production is not approved")
    args = ap.parse_args(argv)
    groups = tuple(g for g, on in ((GROUP_TAG_VENDORS, args.tag_vendors), (GROUP_GYP_SAND, args.gyp_sand_40),
                                   (GROUP_BETA_SAMPLE, args.retire_beta_sample)) if on)
    try:
        plan = make_plan(only=args.only)
        if args.apply:
            if args.target != "staging":
                print("refused: --apply needs --target staging, and staging is the only target "
                      "(production is not approved).", file=sys.stderr)
                return 2
            sys.stdout.write(describe(plan))
            exception_statements(plan, groups)      # a group that cannot be built stops the run before anything is sent
            apply_to_staging(plan, groups=groups)
            print("applied to staging: %s%s" % (json.dumps(plan.counts()),
                                                 (" + exception groups: " + ", ".join(groups)) if groups else ""))
            return 0
        if args.target is not None:
            print("refused: --target means nothing without --apply.", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(plan.as_dict(), indent=1, sort_keys=True))
        else:
            if groups and not args.sql:
                print("refused: the statement groups (%s) are SQL; add --sql to print them." % ", ".join(groups), file=sys.stderr)
                return 2
            sys.stdout.write(sql_script(plan, groups) if args.sql else describe(plan))
        return 0
    except PlanError as err:
        print("stopped: %s" % err, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
