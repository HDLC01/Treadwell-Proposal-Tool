"""The Review step shows how every figure was worked out (Hanz, 2026-10-19).

    "For the review tab show the break down of any thing that has a total like the patch new concrete. Show how its solved or how
    it got to that price. Make sure to label the columns as price/sf, SF or LF etc. thats for all items in the review tab."

Every card of the Review (the takeoff, the labor, Hotel and Per Diem, the tooling and the markups) is a table with a header row,
Item | Quantity | Unit | Rate | Total, and every row that has a total shows its working: a takeoff row its measurement and its rate
per unit, the patch its square feet and the rate the module charged, a labor line its hours and hourly rate, burden and the markups the
base each % is taken of.

PROVEN BY EXECUTION. tests/js/review-working-harness.js boots js/polish-estimate.js whole on a Polish bid and on a Jayhawk-like Epoxy bid
(5,482 SF of flake, 562 LF of cove, primer, four guys for twelve days at $33), takes each to the Review step and parses what the page drew.
`problems()` holds every figure on screen to the figure the chain priced with (the bid the page computed, the row prices the page's own
pricing answers, the rates the takeoff modules answer). The mutations at the bottom break one source of a Rate or a base in a scratch copy
of the page and the same checks go red.
"""
from __future__ import annotations

import re

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _seed_support import plan_json

import pathlib

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "review-working-harness.js"
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js"]
HEAD = ["Item", "Quantity", "Unit", "Rate", "Total"]


def run(frontend=FRONTEND, tmp=None):
    proc = run_node(HARNESS, frontend, plan_json(tmp))
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    require_node()
    return run(tmp=tmp_path_factory.mktemp("working"))


# ── reading what the page drew ───────────────────────────────────────────────
def num(text):
    """The number in a figure as it is printed: $1,234.50, 12,500, 4.5 hrs, -$40, 2.7%."""
    t = str(text).replace(",", "")
    m = re.search(r"-?\$?\s*-?[0-9]+(?:\.[0-9]+)?", t)
    if not m:
        return None
    return float(m.group(0).replace("$", "").replace(" ", ""))


def card(f, key, title=None):
    hits = [c for c in f["cards"] if c["key"] == key and (title is None or c["title"] == title)]
    return hits[0] if hits else None


def row(c, label):
    for r in (c or {"rows": []})["rows"]:
        if r["label"] == label or r["label"].startswith(label):
            return r
    return None


def cents(a, b):
    return abs(a - b) <= 0.005 + 1e-9


def rounded_up(total, product):
    """A figure the chain rounds UP to the dollar: the total is the product, rounded up."""
    return -1e-6 <= total - product < 1 + 1e-6


def pct_text(text):
    return None if text is None else num(text)


def problems(d):
    """Every way the Review's working disagrees with the bid the chain priced. {area: [what is wrong]}; all empty when it is right."""
    out = {k: [] for k in ("header", "columns", "takeoff", "patch", "labor", "burden", "markup", "travel", "tooling",
                           "totals", "adjust", "supplier", "shipping")}
    for name in ("polish", "epoxy"):
        f = d[name]
        bid = f["bid"]
        why = lambda area, msg, name=name: out[area].append(name + ": " + msg)

        # a header row with the five labels, on every table; five cells on every row but a band
        for c in f["cards"]:
            if c["head"] != HEAD:
                why("header", "%s card has header %r" % (c["title"] or c["key"], c["head"]))
            for r in c["rows"]:
                if r["cls"] != "band" and len(r["cells"]) != 5:
                    why("columns", "%s / %r has %d cells" % (c["key"], r["label"], len(r["cells"])))
        # a subtotal or total row says only its Total
        for c in f["cards"]:
            for r in c["rows"]:
                if r["cls"] in ("tot", "sub") and any(x["text"] for x in r["cells"][1:4]):
                    why("totals", "%r shows more than its Total: %r" % (r["label"], [x["text"] for x in r["cells"]]))

        # a takeoff or material row: measurement x rate per unit = its cost, to the rounding of a 2 place rate
        tk = card(f, "takeoff", "Takeoff and Material")
        for rf in f["rows"]:
            if not rf["priced"] or not rf["measurement"]:
                continue
            r = row(tk, rf["name"])
            if not r:
                why("takeoff", "no row for %r" % rf["name"])
                continue
            q, u, rate, tot = num(r["cells"][1]["text"]), r["cells"][2]["text"], r["cells"][3]["text"], num(r["cells"][4]["text"])
            if q != rf["measurement"] or u != rf["unit"]:
                why("takeoff", "%r reads %r %r, the row is %r %r" % (rf["name"], q, u, rf["measurement"], rf["unit"]))
            if not rate.endswith("/ " + rf["unit"]):
                why("takeoff", "%r rate %r does not say per %s" % (rf["name"], rate, rf["unit"]))
            per = num(rate)
            if per is None or abs(q * per - rf["total"]) > q * 0.005 + 0.01:
                why("takeoff", "%r: %s x %s is not its cost %s" % (rf["name"], q, rate, rf["total"]))
            if not cents(tot, rf["total"]):
                why("takeoff", "%r total reads %s, the row costs %s" % (rf["name"], tot, rf["total"]))
            # the same figure the Material step's hint shows (rowPrice's per_unit, two places)
            if per is not None and not cents(per, round(rf["per_unit"] + 1e-12, 2)):
                why("takeoff", "%r rate %s is not the Material step's %s" % (rf["name"], per, rf["per_unit"]))
        rep = tk and next((r for r in tk["rows"] if r["label"].startswith("Patch")), None)
        if not rep:
            why("patch", "no Patch row")
        else:
            sf, unit, rate, tot = num(rep["cells"][1]["text"]), rep["cells"][2]["text"], num(rep["cells"][3]["text"]), num(rep["cells"][4]["text"])
            if sf != f["expect"]["sf"] or unit != "SF":
                why("patch", "patch reads %r %r, the whole area is %r SF" % (sf, unit, f["expect"]["sf"]))
            if rate is None or abs(rate - f["expect"]["patchRate"]) > 1e-9:
                why("patch", "patch rate %r is not the module's %r" % (rate, f["expect"]["patchRate"]))
            if rate is None or not cents(sf * rate, tot):
                why("patch", "patch: %s SF x %s is not %s" % (sf, rate, tot))
        # the Material Total's shipping line: the material it is taken of, the rate the chain used, the amount
        sh = row(tk, "Shipping")
        if sh:
            used = sh["cells"][3]["rates"].get("ship_pct")
            want = bid["ship_pct"] if bid.get("ship_pct") is not None else d["rates"]["SHIPPING"]
            if used is None or abs(num(used) / 100 - want) > 1e-9:
                why("shipping", "shipping rate %r is not the chain's %r" % (used, want))
            if num(sh["cells"][1]["text"]) is None or not cents(num(sh["cells"][1]["text"]), bid["material"]):
                why("shipping", "shipping base %r is not the material %r" % (sh["cells"][1]["text"], bid["material"]))
            if sh["cells"][2]["text"] != "of material" or sh["cells"][3]["inputs"] != 1:
                why("shipping", "shipping unit/box: %r %r" % (sh["cells"][2]["text"], sh["cells"][3]["inputs"]))
            if not rounded_up(bid["shipping"], bid["material"] * want):
                why("shipping", "shipping %r is not the material over its rate" % bid["shipping"])

        # a labor line: guys x days x hours a day = hours, hours x the hourly rate = its total
        lab = card(f, "labor")
        for i, lr in enumerate(f["expect"]["laborRows"]):
            if not lr["cost"] and lr["id"] != "travel":
                continue
            r = row(lab, lr["label"])
            if not r:
                why("labor", "no row for %r" % lr["label"])
                continue
            hrs = num(r["cells"][1]["rv"].get("lab.%d.q" % i))
            work = r["cells"][1]["rv"].get("lab.%d.w" % i, "")
            rate_txt = r["cells"][3]["rv"].get("lab.%d.rate" % i, "")
            rate, tot = num(rate_txt), num(r["cells"][4]["text"])
            want_hrs = lr["guys"] * lr["days"] * lr["perDay"]
            if hrs is None or abs(hrs - want_hrs) > 0.005:
                why("labor", "%r hours %r, guys x days x hours a day is %r" % (lr["label"], hrs, want_hrs))
            if r["cells"][2]["text"] != "hrs" or not rate_txt.endswith("/ hr"):
                why("labor", "%r unit/rate %r %r" % (lr["label"], r["cells"][2]["text"], rate_txt))
            if rate is None or abs(rate - lr["rate"]) > 0.005 or hrs is None or not cents(hrs * rate, tot) or not cents(tot, lr["cost"]):
                why("labor", "%r: %s hrs x %s is not %s" % (lr["label"], hrs, rate_txt, tot))
            if not work or [num(x) for x in work.split("×")][0:2] != [lr["guys"], lr["days"]]:
                why("labor", "%r working %r" % (lr["label"], work))
        # burden is its % of the labor (and escalation when there is some)
        bu = row(lab, "Labor burden")
        base, rate_txt = num(bu["cells"][1]["rv"].get("burden.q")), bu["cells"][3]["rv"].get("burden.rate")
        if base is None or not cents(base, bid["labor"] + bid["escalation"]):
            why("burden", "burden base %r is not labor + escalation %r" % (base, bid["labor"] + bid["escalation"]))
        if rate_txt != "12%" or (not bid["escalation"] and not rounded_up(bid["burden"], bid["labor"] * 0.12)):
            why("burden", "burden is %r at %r on a labor of %r" % (bid["burden"], rate_txt, bid["labor"]))
        if bu["cells"][2]["text"] != "of labor":
            why("burden", "burden unit %r" % bu["cells"][2]["text"])

        # Hotel and Per Diem: nights (or days) x the line's rate, rounded up
        tr = card(f, "travel")
        for r in tr["rows"]:
            if r["label"] in ("Hotel", "Per Diem"):
                q, unit, rate = num(r["cells"][1]["text"]), r["cells"][2]["text"], num(r["cells"][3]["text"])
                if not rounded_up(num(r["cells"][4]["text"]), q * rate) or unit not in ("nights", "days"):
                    why("travel", "%r: %s %s x %s is not %s" % (r["label"], q, unit, rate, r["cells"][4]["text"]))
        # the tooling card: every part is quantity x rate (to the module's own rounding), and the parts add up to the bid's tooling
        tools = [c for c in f["cards"] if c["title"] == "Tooling and consumables"]
        if bid["tooling"] > 0:
            if not tools:
                why("tooling", "no tooling card")
            else:
                parts = [r for r in tools[0]["rows"] if r["cls"] != "tot"]
                if not parts:
                    why("tooling", "the tooling card is one lump")
                if abs(sum(num(r["cells"][4]["text"]) for r in parts) - bid["tooling"]) > 0.005:
                    why("tooling", "the parts add to %r, the bid's tooling is %r" % (sum(num(r["cells"][4]["text"]) for r in parts), bid["tooling"]))
                for r in parts:
                    q, rate, tot = num(r["cells"][1]["text"]), num(r["cells"][3]["text"]), num(r["cells"][4]["text"])
                    if not (rounded_up(tot, q * rate) or (tot >= q * rate)):
                        why("tooling", "%r: %s x %s is not %s" % (r["label"], q, rate, tot))

        # the markups: the Rate is the % the chain used, and the base x the % comes to the amount (rounded up to the dollar)
        mk = card(f, "markup")
        rates = d["rates"]
        for label, rate_key, amt_key, chain_key, fallback in (
                ("GP", "gp_pct", "gp", "gp_pct", None), ("Superintendent", "super_pct", "super_pto", "super_pct", rates["SUPER_PTO"]),
                ("Soft costs", "soft_pct", "soft_costs", "soft_pct", rates["SOFT_COSTS"]),
                ("Sales tax", "sales_tax_pct", "sales_tax", "sales_tax_pct", None),
                ("Remodel tax", "remodel_pct", "remodel_tax", "remodel_pct", None), ("Bond", "bond_pct", "bond", "bond_pct", None)):
            r = row(mk, label)
            used = r["cells"][3]["rates"].get(rate_key)
            want = bid.get(chain_key) if bid.get(chain_key) is not None else fallback
            if used is None or want is None or abs(num(used) / 100 - want) > 1e-9:
                why("markup", "%s rate %r is not the chain's %r" % (label, used, want))
            q_txt = r["cells"][1]["text"]
            if q_txt and label != "GP":
                if not rounded_up(bid[amt_key], num(q_txt) * want):
                    why("markup", "%s: %s x %s%% is not %s" % (label, q_txt, want * 100, bid[amt_key]))
                if not r["cells"][2]["text"].startswith("of "):
                    why("markup", "%s unit %r" % (label, r["cells"][2]["text"]))
            elif label in ("Superintendent", "Soft costs", "Sales tax") and want:
                why("markup", "%s shows no base" % label)
            if not cents(num(r["cells"][4]["text"]), bid[amt_key]):
                why("markup", "%s total %r is not the chain's %r" % (label, r["cells"][4]["text"], bid[amt_key]))
        gp = row(mk, "GP")
        if gp["cells"][1]["text"] or gp["cells"][3]["inputs"] != 1:
            why("markup", "GP is a margin; it must show no base and keep its box: %r" % gp["cells"][1]["text"])
        grand = row(mk, "Total lump sum")
        if num(grand["cells"][1]["text"]) != bid["sf"] or grand["cells"][2]["text"] != "SF" or num(grand["cells"][3]["text"]) is None \
                or not cents(num(grand["cells"][3]["text"]), round(bid["per_sf"] + 1e-12, 2)) or num(grand["cells"][4]["text"]) != bid["total"]:
            why("markup", "the lump sum row reads %r" % [x["text"] for x in grand["cells"]])

    # the override boxes still type, reprice, and the working moves with them without a rebuild
    a = d["polish"]["adjust"]
    if not a["noRebuild"] or a["typed"] != "25":
        out["adjust"].append("typing a GP rebuilt the panel or lost the box: %r" % ((a["noRebuild"], a["typed"]),))
    if a["after"]["rates"].get("gp_pct") != "25%" or a["before"]["rates"].get("gp_pct") == "25%":
        out["adjust"].append("the GP rate did not move to 25%%: %r -> %r" % (a["before"]["rates"].get("gp_pct"), a["after"]["rates"].get("gp_pct")))
    b = a["bid"]
    hb = b.get("hard_bid") or 0
    for key, want in (("mk.super.q", b["sub_total"] + b["gp"] + hb + b["contingency"] + b["sales_tax"] + b["fees"]),
                      ("mk.soft.q", b["sub_total"] + b["gp"] + hb + b["super_pto"] + b["contingency"] + b["sales_tax"] + b["fees"])):
        got = num(a["after"]["rv"].get(key))
        if got is None or not cents(got, want):
            out["adjust"].append("%s after a typed GP reads %r, the chain's is %r" % (key, a["after"]["rv"].get(key), want))
        if a["after"]["rv"].get(key) == a["before"]["rv"].get(key):
            out["adjust"].append("%s did not move with the GP" % key)
    cb = a["withContingency"]["bid"]
    want = cb["sub_total"] + cb["gp"] + (cb.get("hard_bid") or 0) + cb["contingency"] + cb["sales_tax"] + cb["fees"]
    got = num(a["withContingency"]["live"]["rv"].get("mk.super.q"))
    if cb["contingency"] != 5000 or got is None or not cents(got, want):
        out["adjust"].append("the super base with a contingency reads %r, not %r" % (got, want))

    # a supplier discount typed on the Review reprices the takeoff rows' rate and total in place
    s = d["epoxy"]["discount"]
    moved = [(x["name"], x["total"], y["total"]) for x, y in zip(s["rowsBefore"], s["rowsAfter"]) if x["priced"] and x["total"] != y["total"]]
    if not moved:
        out["supplier"].append("the fixture's rows did not move with a supplier discount, so this proves nothing")
    if not s["noRebuild"]:
        out["supplier"].append("typing a supplier discount rebuilt the panel")
    for rf in s["rowsAfter"]:
        if not rf["priced"] or not rf["measurement"]:
            continue
        per, tot = num(s["live"]["rv"].get("tk.%d.rate" % rf["i"])), num(s["live"]["rv"].get("tk.%d.tot" % rf["i"]))
        if tot is None or not cents(tot, rf["total"]) or per is None or abs(rf["measurement"] * per - rf["total"]) > rf["measurement"] * 0.005 + 0.01:
            out["supplier"].append("%r after the discount reads %s x %s = %s, the row costs %s" % (rf["name"], rf["measurement"], per, tot, rf["total"]))
    sp = d["epoxy"]["shipping"]
    got = sp["live"]
    if num(got["rates"].get("ship_pct")) != 12 or num(got["rv"].get("ship.q")) is None             or not cents(num(got["rv"]["ship.q"]), sp["bid"]["material"]) or not rounded_up(sp["bid"]["shipping"], sp["bid"]["material"] * 0.12)             or not cents(num(got["mk"].get("shipping")), sp["bid"]["shipping"]):
        out["shipping"].append("typing 12%% into Shipping reads %r" % (got["rates"], ))
    return out


def test_every_review_table_has_the_five_labelled_columns(ran):
    p = problems(ran)
    assert p["header"] == [] and p["columns"] == [], p["header"] + p["columns"]
    assert [c["key"] for c in ran["epoxy"]["cards"]] == ["takeoff", "labor", "travel", "takeoff", "markup"]
    assert ran["epoxy"]["cards"][0]["head"] == ["Item", "Quantity", "Unit", "Rate", "Total"]


def test_a_takeoff_row_shows_its_measurement_unit_and_rate_per_unit(ran):
    assert problems(ran)["takeoff"] == []
    rows = {r["label"]: [x["text"] for x in r["cells"]] for r in card(ran["epoxy"], "takeoff", "Takeoff and Material")["rows"]}
    assert rows["Cove: Epoxy 4\""][1:4] == ["562", "LF", "$1.66 / LF"], "a cove row is read per linear foot"
    assert rows["MACRO Flake Single Broadcast"][1:4] == ["5,482", "SF", "$1.85 / SF"]


def test_the_patch_row_is_the_area_times_the_rate_the_module_charged(ran):
    p = problems(ran)
    assert p["patch"] == [], p["patch"]
    assert ran["polish"]["expect"]["patchRate"] == 0.05 and ran["epoxy"]["expect"]["patchRate"] == 0.10


def test_a_labor_line_shows_guys_days_and_hours_at_its_hourly_rate(ran):
    p = problems(ran)
    assert p["labor"] == [] and p["burden"] == [], p["labor"] + p["burden"]
    lab = card(ran["epoxy"], "labor")
    install = row(lab, "Epoxy install")
    assert install["cells"][1]["rv"]["lab.1.q"] == "384" and install["cells"][1]["rv"]["lab.1.w"] == "4 × 12 × 8"
    assert install["cells"][3]["rv"]["lab.1.rate"] == "$33 / hr" and install["cells"][4]["text"] == "$12,672"
    assert ran["epoxy"]["bid"]["burden"] == 1521 and ran["epoxy"]["bid"]["labor"] == 12672, "burden is 12% of the labor"


def test_shipping_hotel_and_tooling_show_their_base_rate_and_parts(ran):
    p = problems(ran)
    assert p["shipping"] == [] and p["travel"] == [] and p["tooling"] == [], p["shipping"] + p["travel"] + p["tooling"]


def test_each_markup_line_shows_the_base_its_percentage_is_taken_of(ran):
    p = problems(ran)
    assert p["markup"] == [], p["markup"]
    mk = card(ran["epoxy"], "markup")
    assert row(mk, "Superintendent")["cells"][2]["text"] == "of subtotal + markups"
    assert row(mk, "GP")["cells"][2]["text"] == "margin on cost", "GP is a gross-up, so it says so and shows no base"


def test_subtotal_and_total_rows_show_only_their_total(ran):
    assert problems(ran)["totals"] == []


def test_the_override_boxes_still_type_and_reprice_and_the_working_moves_with_them(ran):
    p = problems(ran)
    assert p["adjust"] == [] and p["supplier"] == [], p["adjust"] + p["supplier"]


def test_the_tables_scroll_inside_their_own_box_so_a_phone_never_scrolls_the_page():
    page = (FRONTEND / "polish-estimate.html").read_text(encoding="utf-8")
    assert re.search(r"\.tscroll\{[^}]*overflow-x:auto", page), "the table must scroll in its own box"
    assert re.search(r"\.rev-t,\.mk\{min-width:\d+px\}", page)


def test_every_figure_is_still_the_chain_the_money_cells_are_all_the_chains_keys(ran):
    """The existing rule, kept: a data-mk cell is a key of the chain's own answer."""
    for name in ("polish", "epoxy"):
        keys = set(re.findall(r'data-mk="([^"]*)"', ran[name]["html"]))
        assert keys <= set(ran[name]["bid"]) | {"sub_total", "total"}, keys - set(ran[name]["bid"])


# ── the checks go red when one source of a rate or a base is broken ────────────────────────────────────────────
BREAKS = {
    "the patch rate is retyped": ("js/polish-estimate.js",
        '        SL.unitPrice(ITEMS, polishReno ? "patchReno" : "patchNew").cost, patchNow));',
        '        SL.unitPrice(ITEMS, polishReno ? "patchReno" : "patchNew").cost + 0.01, patchNow));', "patch"),
    "the epoxy patch rate is wrong": ("js/polish-estimate.js",
        '      if (epPatch > 0) tkRows.push(patchRow(\'Patch <span class="note">epoxy rate</span>\', areaSf, E.unitPrice(epItems, "patch").cost, epPatch));',
        '      if (epPatch > 0) tkRows.push(patchRow(\'Patch <span class="note">epoxy rate</span>\', areaSf, E.unitPrice(epItems, "patch").cost * 2, epPatch));',
        "patch"),
    "a labor rate is wrong": ("js/polish-estimate.js",
        '                    "hrs", rvc("lab." + i + ".rate", moneyAuto(B.laborRateOf(r, pwRev)) + " / hr"),',
        '                    "hrs", rvc("lab." + i + ".rate", moneyAuto(B.laborRateOf(r, pwRev) + 1) + " / hr"),', "labor"),
    "burden is taken of the wrong base": ("js/polish-estimate.js",
        '    labRows.push(["Labor burden", rvc("burden.q", moneyAuto(B.num(b.labor) + B.num(b.escalation))),',
        '    labRows.push(["Labor burden", rvc("burden.q", moneyAuto(B.num(b.labor_total))),', "burden"),
    "a takeoff rate is wrong": ("js/polish-estimate.js",
        '                   rvc("tk." + i + ".rate", perUnitText(per, unit)), rv("tk." + i + ".tot", rc.text)]);',
        '                   rvc("tk." + i + ".rate", perUnitText(per * 1.1, unit)), rv("tk." + i + ".tot", rc.text)]);', "takeoff"),
    "a markup rate is read from the rule, not the chain": ("js/polish-estimate.js",
        '      case "super_pct": return b.super_pct != null ? b.super_pct : B.RATES.SUPER_PTO;',
        '      case "super_pct": return B.RATES.SUPER_PTO + 0.01;', "markup"),
    "the repaint leaves the working stale": ("js/polish-estimate.js",
        '        if (Object.prototype.hasOwnProperty.call(figs, k)) el.textContent = figs[k];',
        '        void figs;', "adjust"),
    "shipping is taken of the wrong base": ("js/polish-estimate.js",
        '      tkRows.push(["Shipping", rvc("ship.q", moneyAuto(b.material)), "of material",',
        '      tkRows.push(["Shipping", rvc("ship.q", moneyAuto(b.material_total)), "of material",', "shipping"),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_a_source_of_the_working_is_broken(tmp_path, name):
    require_node()
    rel, old, new, area = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend, plan_json(tmp_path))
    if proc.returncode != 0:
        return                                               # a crash is the loudest way to go red
    found = problems(last_json_line(proc.stdout))
    assert found[area], "the checks did not notice: " + name + " (" + ", ".join(k for k, v in found.items() if v) + ")"
