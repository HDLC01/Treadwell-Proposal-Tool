"""The Review step's Man hours & budget card is Kyle's block, worked by his own formulas.

Hanz, 2026-10-27: "In the review tab we need to show the Man hours, the budget, this as well. Take it from the sheet." The
block he showed sits beside the markup on the Epoxy tab (Polish's is the same formulas a row up):

    8 hour days        Total Man Hours 144.00 / Total Days 6.00 / ^based on X crew size: 3.00
    Total "Estimated Costs" w/taxes + fees + bond   $7,239.00   $7.24 a SF
    Man Hour Budget (Raken) 144.00      GP per Day $987.17 based on 8 hour days
    Mark Up + Conting. $5,923.00 37.8%  GP / MH $41.13 ($32.20 LaborRate from Above)  MarkUp + Soft Costs $8,442.00 53.8%

js/bid-model.js manHourBudget answers it from the section's own labor rows and the chain's own lines, and
js/polish-estimate.js manHoursCard draws it, read only, on an Epoxy or a Polish sheet. Proven here three ways:

  1. THE WORKBOOK'S FORMULAS, EVALUATED. The block's cells are read from backend/templates/estimate_sheet_5.7.xlsx as formula
     text (openpyxl, data_only=False) and evaluated over the inputs of the job: the crew rows, the drive, the area and the
     chain's cells. No formula is retyped here; a template edit to the block changes what this side answers. The workbook
     oracle's HyperFormula is not installed in CI (tests/test_workbook_oracle.py says why), and none is needed: every cell
     of the block is SUM, IF, + - * / over cells, which `Sheet` below evaluates and refuses anything else.
  2. THE JOBS. The recorded real job (tests/fixtures/recorded_job_2026_10.json, the cells its workbook answered) and the
     440 jobs of the Epoxy golden (tests/fixtures/epoxy_jobs_golden.json), each priced by the harness that already proves
     v2's price is the workbook's (tests/js/man-hours-parity-harness.js borrows them whole), plus three variants of the
     recorded job for what it does not have (a drive, the fourth hand, a second crew line, a contingency, 10 hour days). The chain's
     cells on the workbook side are the RECORDED ones wherever the fixture has them; what a fixture does not record (the
     golden has no super, soft costs or discount cells) is v2's, held to the fixture's total by the sheet's own D88 sum.
     Equal to the cent and to 0.01 hour.
  3. THE PAGE. tests/js/man-hours-review-harness.js boots the real page, types a crew on the Labor step and a Contingency on
     the Review, reopens the saved draft the way jsonb hands it back, and reads the card the page drew.

Each figure's line in manHourBudget is broken in a scratch copy and the parity has to go red, and so do the card's own lines.
"""
from __future__ import annotations

import json
import pathlib
import re
import warnings
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

import openpyxl
import pytest
from openpyxl.utils import column_index_from_string, get_column_letter

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node
from _oracle_support import TEMPLATE_PATH
from _seed_support import plan_json

TESTS = pathlib.Path(__file__).resolve().parent
PARITY = TESTS / "js" / "man-hours-parity-harness.js"
REVIEW = TESTS / "js" / "man-hours-review-harness.js"
JOB = TESTS / "fixtures" / "recorded_job_2026_10.json"
GOLDEN = TESTS / "fixtures" / "epoxy_jobs_golden.json"
RECORDED = json.loads(JOB.read_text(encoding="utf-8"))
GOLDEN_CASES = {c["id"]: c for c in json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]}
PARITY_FILES = ["js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js", "js/library-core.js", "js/epoxy-takeoff.js",
                "js/seal-takeoff.js", "js/work-types.js", "js/markup-core.js", "js/excel-math.js"]
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]


# ── the workbook's formulas, evaluated ─────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=None)
def _template():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(TEMPLATE_PATH, data_only=False)
    return {name: {c.coordinate: c.value for row in wb[name].iter_rows() for c in row if c.value is not None}
            for name in ("Epoxy", "Polish")}


_TOKEN = re.compile(r'\s*(?:("[^"]*")|(\$?[A-Z]{1,3}\$?\d+:\$?[A-Z]{1,3}\$?\d+)|([A-Z]+)\(|(\$?[A-Z]{1,3}\$?\d+)|'
                    r'(\d+(?:\.\d+)?)|(<>|<=|>=|=|[-+*/(),<>]))')


class _Text(str):
    """A text cell: Excel compares text without regard to case ("No" = "NO")."""

    def __eq__(self, other):
        return isinstance(other, str) and self.lower() == other.lower()

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = str.__hash__


class Sheet:
    """One tab of the template with the job's inputs typed over it. A cell given in `inputs` is that value; any other cell
    holding a formula is evaluated from its own text; an empty cell is 0. A constant the template holds is used only when it
    is named in `constants` (the "8 hour days" text): a constant reached by accident would be Kyle's sample crew (3 guys for
    5 days), and the comparison would pass on his numbers instead of the job's. Only SUM, IF, references, ranges, text,
    numbers and + - * / = <> are understood; anything else is refused, never guessed."""

    def __init__(self, tab, inputs, constants=()):
        self.cells, self.tab = _template()[tab], tab
        self.inputs = {k: (_Text(v) if isinstance(v, str) else v) for k, v in inputs.items()}
        self.constants = set(constants)

    def value(self, addr):
        addr = addr.replace("$", "")
        if addr in self.inputs:
            return self.inputs[addr]
        v = self.cells.get(addr)
        if v is None:
            return 0
        if isinstance(v, str) and v.startswith("="):
            return self.formula(v)
        if addr in self.constants:
            return _Text(v) if isinstance(v, str) else v
        raise AssertionError("%s!%s holds the template's own %r, and the job gave no value for it" % (self.tab, addr, v))

    def range(self, a, b):
        ca, ra = re.fullmatch(r"([A-Z]+)(\d+)", a.replace("$", "")).groups()
        cb, rb = re.fullmatch(r"([A-Z]+)(\d+)", b.replace("$", "")).groups()
        cols = range(column_index_from_string(ca), column_index_from_string(cb) + 1)
        return [self.value(get_column_letter(c) + str(r)) for r in range(int(ra), int(rb) + 1) for c in cols]

    def formula(self, text):
        py, pos, body = [], 0, text[1:]
        while pos < len(body):
            m = _TOKEN.match(body, pos)
            if not m or m.end() == pos:
                raise AssertionError("cannot evaluate %r at %r" % (text, body[pos:]))
            s, rng, fn, ref, n, op = m.groups()
            if s is not None:
                py.append("_t(%s)" % s)
            elif rng:
                py.append("_r(%r, %r)" % tuple(rng.split(":")))
            elif fn:
                if fn not in ("SUM", "IF"):
                    raise AssertionError("%s is not one of the functions this evaluator knows: %r" % (fn, text))
                py.append("_%s(" % fn.lower())
            elif ref:
                py.append("_v(%r)" % ref)
            elif n:
                py.append(n)
            else:
                py.append({"=": "==", "<>": "!="}.get(op, op))
            pos = m.end()

        def _sum(*args):
            t = 0
            for a in args:
                for x in (a if isinstance(a, list) else [a]):
                    t += x if isinstance(x, (int, float)) and not isinstance(x, bool) else 0
            return t

        env = {"_v": self.value, "_r": self.range, "_t": _Text, "_sum": _sum, "_if": lambda c, a, b=False: a if c else b}
        return eval("".join(py), {"__builtins__": {}}, env)  # noqa: S307 - the template's own formula text, tokenised above

    def get(self, addr):
        """A cell's value, or None where the sheet would show #DIV/0!."""
        try:
            return self.value(addr)
        except ZeroDivisionError:
            return None


# The block's cells on each tab, and the words beside each in the template (the page prints the same words).
BLOCK = {
    "Epoxy": {"man_hours": "H64", "total_days": "H65", "crew": "H66", "est_costs": "F72", "est_costs_per_sf": "I72",
              "budget_hours": "F73", "gp_per_day": "F74", "markup_cont": "F87", "markup_cont_pct": "F88",
              "gp_per_mh": "G87", "labor_rate": "G88", "markup_soft": "H87", "markup_soft_pct": "H88"},
    "Polish": {"man_hours": "H56", "total_days": "H57", "crew": "H58", "est_costs": "F66", "est_costs_per_sf": "I66",
               "budget_hours": "F67", "gp_per_day": "F68", "markup_cont": "F81", "markup_cont_pct": "F82",
               "gp_per_mh": "G81", "labor_rate": "G82", "markup_soft": "H81", "markup_soft_pct": "H82"},
}
LABELS = {
    "Epoxy": {"G64": "Total Man Hours", "G65": "Total Days", "G66": "^based on X crew size",
              "G72": 'Total "Estimated Costs" w/taxes + fees + bond', "G73": "Man Hour Budget (Raken)", "G74": "GP per Day",
              "F86": "Mark Up + Conting.", "G86": "GP / MH", "H86": "MarkUp + Soft Costs", "G89": "LaborRate from Above"},
    "Polish": {"G56": "Total Man Hours", "G57": "Total Days", "G58": "^based on X crew size",
               "G66": 'Total "Estimated Costs" w/taxes + fees + bond', "G67": "Man Hour Budget (Raken)", "G68": "GP per Day",
               "F80": "Mark Up + Conting.", "G80": "GP / MH", "H80": "MarkUp + Soft Costs", "G83": "LaborRate from Above"},
}
PAGE_WORDS = {"^based on X crew size": "^based on X guys"}
# the chain's cells: Epoxy D70 sub-total, D73 GP, D74 discount, D75 super and PTO, D76 soft costs, D77 contingency, D82 taxes,
# D85 fees and bond, D88 total; Polish's are D64, D67 ... D71, D76, D79, D82
CHAIN_CELLS = {
    "Epoxy": {"sub_total": "D70", "gp": "D73", "hard_bid": "D74", "super_pto": "D75", "soft_costs": "D76", "contingency": "D77",
              "taxes": "D82", "fees_and_bond": "D85", "total": "D88"},
    "Polish": {"sub_total": "D64", "gp": "D67", "hard_bid": "D68", "super_pto": "D69", "soft_costs": "D70", "contingency": "D71",
               "taxes": "D76", "fees_and_bond": "D79", "total": "D82"},
}
# where each crew line is typed: Epoxy's four System rows; Polish's polishing, second polish, mock-up and joint-filler rows
CREW_ROWS = {"Epoxy": [47, 48, 49, 50], "Polish": {"polishing": 37, "other": 38, "mockup": 40, "jointfill": 42}}
DRIVE_ROW = {"Epoxy": 52, "Polish": 44}
DAY_SWITCH = {"Epoxy": "E45", "Polish": "E35"}
AREA = {"Epoxy": ("E20", "E24"), "Polish": ("E18",)}
RATE = {"Epoxy": "C47", "Polish": "C37"}


def labor_inputs(tab, labor, conditions):
    """The job's labor rows typed into the tab's crew and drive cells, as Kyle types them."""
    inputs, crew = {}, [r for r in labor if r.get("id") != "travel"]
    drive = [r for r in labor if r.get("id") == "travel"]
    assert all(r.get("enabled", True) is not False for r in labor), "a row switched off has no cell on the sheet"
    hours = {int(r.get("hours_per_day") or 8) for r in crew}
    assert len(hours) <= 1, "the sheet's 8 / 10 hour switch is one for the tab"
    inputs[DAY_SWITCH[tab]] = "%d hour days" % (hours.pop() if hours else 8)
    if tab == "Epoxy":
        assert len(crew) <= 4, "the Epoxy tab has four crew rows"
        for row, r in zip(CREW_ROWS[tab], crew):
            inputs["A%d" % row], inputs["B%d" % row] = r["guys"], r["days"]
    else:
        seen = set()
        for r in crew:
            key = r["id"] if r["id"] in CREW_ROWS[tab] else "other"
            assert key not in seen, "two lines for one Polish row"
            seen.add(key)
            row = CREW_ROWS[tab][key]
            inputs["B%d" % row] = r["days"]
            if key == "jointfill" and float(r["guys"]) == 3:
                # A42 is Kyle's =IF(F29="NO",3,4): the fourth hand of Remove existing joint filler, left to his formula
                inputs["F29"] = "Yes" if conditions.get("joint_filler") and conditions.get("remove_existing_jf") else "No"
            else:
                inputs["A%d" % row] = float(r["guys"]) + (1 if key == "jointfill" and conditions.get("remove_existing_jf") else 0)
        for key, row in CREW_ROWS[tab].items():
            if key not in seen:              # a row the job has no line for is empty, never the template's sample crew
                inputs["A%d" % row], inputs["B%d" % row] = 0, 0
    # the drive: its guys over the sheet's man-days formula, and its hours (Polish B44 reads Epoxy!B52, typed here)
    inputs["A%d" % DRIVE_ROW[tab]] = float(drive[0]["guys"]) if drive else 0
    inputs["B%d" % DRIVE_ROW[tab]] = float(drive[0]["days"]) if drive else 0
    inputs[RATE[tab]] = float(crew[0]["rate"])
    return inputs


def workbook_block(tab, labor, conditions, chain, sf, extra_sf=0):
    """What the tab's own block formulas give for this job, keyed as manHourBudget answers."""
    inputs = labor_inputs(tab, labor, conditions)
    for key, cell in CHAIN_CELLS[tab].items():
        inputs[cell] = chain[key]
    inputs[AREA[tab][0]] = sf
    if len(AREA[tab]) > 1:
        inputs[AREA[tab][1]] = extra_sf
    sheet = Sheet(tab, inputs)
    out = {key: sheet.get(cell) for key, cell in BLOCK[tab].items()}
    out["hours_label"] = sheet.get("H74" if tab == "Epoxy" else "H68")
    return out


def differences(tab, got, want):
    """Every figure of the block v2 answered that is not the workbook's, to the cent and to 0.01 hour (a ratio to 1e-6)."""
    bad = []
    for key, w in want.items():
        if key == "hours_label":
            if str(w) != "%d hour days" % got["hours_per_day"]:
                bad.append("hours a day: the sheet says %r, v2 %r" % (w, got["hours_per_day"]))
            continue
        g = got[key]
        tol = 1e-6 if key.endswith("_pct") else 0.005
        if (w is None) != (g is None) or (w is not None and abs(float(g) - float(w)) > tol):
            bad.append("%s (%s!%s): the workbook says %r, v2 says %r" % (key, tab, BLOCK[tab][key], w, g))
    return bad


# ── running the harnesses ──────────────────────────────────────────────────────────────────────────────────────
def _parity(frontend, tmp):
    require_node()
    proc = run_node(PARITY, frontend, plan_json(tmp), JOB, GOLDEN)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def parity(tmp_path_factory):
    return _parity(FRONTEND, tmp_path_factory.mktemp("mh-parity"))


@pytest.fixture(scope="module")
def page(tmp_path_factory):
    require_node()
    proc = run_node(REVIEW, FRONTEND, plan_json(tmp_path_factory.mktemp("mh-page")))
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


def recorded_problems(d):
    """The recorded real job: the workbook side is the SHEET's own cells, as recorded, with the job's typed crew."""
    out = []
    for name, tab in (("epoxy", "Epoxy"), ("polish", "Polish")):
        rec, got = RECORDED[name], d["recorded"][name]
        s = rec["sheet"]
        chain = {"sub_total": s["sub_total"], "gp": s["gp"], "hard_bid": s["hard_bid"], "super_pto": s["super_pto"],
                 "soft_costs": s["soft_costs"], "taxes": s["sales_tax"] + s["remodel_tax"], "total": s["total"]}
        # D77 (contingency) and D85 (fees and bond) are not recorded: the sheet's own D88 = SUM(D70, D73:D77, D82, D85) says
        # what they come to together, which is nothing on this job
        rest = s["total"] - sum(v for k, v in chain.items() if k != "total")
        assert rest == 0, "%s: the recorded cells do not add up to D88 without a contingency or a fee" % name
        chain.update(contingency=0, fees_and_bond=0)
        want = workbook_block(tab, got["labor"], got["conditions"], chain, rec["in"]["sf"])
        out += [name + ": " + p for p in differences(tab, got["block"], want)]
    return out


def variant_problems(d):
    out = []
    for name, v in d["variants"].items():
        tab = "Polish" if name.startswith("polish") else "Epoxy"
        want = workbook_block(tab, v["labor"], v["conditions"], v["chain"], v["chain"]["sf"])
        out += [name + ": " + p for p in differences(tab, v["block"], want)]
    return out


def golden_problems(d):
    """The Epoxy golden: D70, D73, D82 and D88 are the workbook's as recorded; the rest of the chain is v2's, and the sheet's
    own D88 sum must land on the recorded total with it, so what is borrowed is the workbook's too."""
    out, held = [], 0
    for r in d["golden"]:
        rec = GOLDEN_CASES[r["id"]]["out"]
        ch = dict(r["chain"])
        if (ch["sub_total"], ch["gp"], ch["taxes"], ch["total"]) != (rec["D70"], rec["D73"], rec["D82"], rec["D88"]):
            # a job a declared departure of tests/test_epoxy_v2_proof.py prices apart: its chain is not the workbook's
            continue
        held += 1
        ch.update(sub_total=rec["D70"], gp=rec["D73"], taxes=rec["D82"], total=rec["D88"])
        summed = sum(ch[k] for k in ("sub_total", "gp", "hard_bid", "super_pto", "soft_costs", "contingency", "taxes",
                                     "fees_and_bond"))
        if summed != rec["D88"]:
            out.append("%s: the borrowed cells do not add up to the recorded D88" % r["id"])
            continue
        spec = GOLDEN_CASES[r["id"]]["in"]
        want = workbook_block("Epoxy", r["labor"], r["conditions"], ch, spec.get("sf1") or 0, spec.get("sf2") or 0)
        out += [r["id"] + ": " + p for p in differences("Epoxy", r["block"], want)]
    return out, held


# ── 1. the template still has the block where this reads it ───────────────────────────────────────────────────
@pytest.mark.parametrize("tab", ["Epoxy", "Polish"])
def test_the_template_holds_the_block_with_its_words(tab):
    cells = _template()[tab]
    for addr, words in LABELS[tab].items():
        assert str(cells.get(addr, "")).strip().rstrip(":") == words, "%s!%s reads %r" % (tab, addr, cells.get(addr))
    for key, addr in BLOCK[tab].items():
        assert str(cells.get(addr, "")).startswith("="), "%s!%s (%s) is not a formula" % (tab, addr, key)
    assert cells[DAY_SWITCH[tab]] == "8 hour days"


def test_the_evaluator_reads_kyles_own_sample_crew_as_his_sheet_does():
    """The evaluator, on the template's own crew (3 guys for 5 days on System 1, the drive's man-days at 0 hours): 120 man
    hours over 5 days, the figures the template's cached values print. Proves the evaluator is the sheet, not a copy of v2."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cached = openpyxl.load_workbook(TEMPLATE_PATH, data_only=True)["Epoxy"]
    sheet = Sheet("Epoxy", {}, constants={"A47", "B47", "A48", "B48", "A49", "B49", "A50", "B50", "B52", "E45"})
    for addr in ("H64", "H65", "H66", "F73"):
        assert sheet.get(addr) == pytest.approx(cached[addr].value, abs=0.005), addr
    assert (sheet.get("H64"), sheet.get("H65")) == (120, 5)


# ── 2. the jobs ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_recorded_real_jobs_block_is_the_workbooks(parity):
    assert recorded_problems(parity) == []
    e = parity["recorded"]["epoxy"]["block"]
    # the job's own figures, for a reader: 4 guys for 12 days is 384 man hours; GP + discount is $13,736 - $1,254
    assert (e["man_hours"], e["total_days"], e["crew"], e["markup_cont"], e["est_costs"]) == (384, 12, 4, 12482, 31852)


def test_the_variants_with_a_drive_a_fourth_hand_a_second_crew_and_ten_hour_days_are_the_workbooks(parity):
    assert variant_problems(parity) == []
    v = parity["variants"]
    assert v["polishDriveAndHand"]["block"]["man_hours"] == 228 + 3 * 6.5 + 1 * 1 * 8, "the drive and the fourth hand count"
    assert v["epoxyTenHourDays"]["block"]["hours_per_day"] == 10
    assert v["epoxyDriveAndSecondCrew"]["chain"]["contingency"] == 750, "no job here has a contingency, so D77 is untested"


def test_every_epoxy_golden_jobs_block_is_the_workbooks(parity):
    bad, held = golden_problems(parity)
    assert bad == [], bad[:10]
    assert held >= len(GOLDEN_CASES) - 7, "only %d of %d golden jobs were compared" % (held, len(GOLDEN_CASES))


def test_a_figure_that_divides_by_nothing_is_left_blank_as_the_sheet_shows_an_error(parity):
    none = [r for r in parity["golden"] if r["chain"]["sf"] == 0]
    assert none, "the golden has no job without an area, so this proves nothing"
    assert all(r["block"]["est_costs_per_sf"] is None for r in none)


# ── 3. the page ────────────────────────────────────────────────────────────────────────────────────────────────
def _half_up(d, places):
    return d.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _two(n):
    """toLocaleString's two places: the shortest decimal of the double, a half rounded away from zero (ECMA-402 halfExpand)."""
    return "" if n is None else "{:,.2f}".format(_half_up(Decimal(repr(float(n))), 2))


def _cash(n):
    return "" if n is None else ("-" if n < 0 else "") + "$" + _two(abs(n))


def _share(n):
    """toFixed(1) of n x 100: the double's exact value, a tie going to the larger."""
    return "" if n is None else "%s%%" % _half_up(Decimal(float(n) * 100), 1)


def shown(want, sf):
    """The card's figures as the page must print them, from the model's answer."""
    day = "%d hour days" % want["hours_per_day"]
    per = want["est_costs_per_sf"]
    return {"mh.hours": _two(want["man_hours"]), "mh.days": _two(want["total_days"]), "mh.days.u": day,
            "mh.guys": _two(want["crew"]), "mh.est.q": "" if per is None else "{:,}".format(sf), "mh.est.u": "" if per is None else "SF",
            "mh.est.rate": "" if per is None else _cash(per) + " / SF", "mh.est": _cash(want["est_costs"]),
            "mh.budget": _two(want["budget_hours"]), "mh.gpday.u": "based on " + day, "mh.gpday": _cash(want["gp_per_day"]),
            "mh.mc.pct": _share(want["markup_cont_pct"]), "mh.mc": _cash(want["markup_cont"]), "mh.gpmh": _cash(want["gp_per_mh"]),
            "mh.rate": "" if want["labor_rate"] is None else _cash(want["labor_rate"]) + " / hr",
            "mh.ms.pct": _share(want["markup_soft_pct"]), "mh.ms": _cash(want["markup_soft"])}


def page_problems(p):
    out = []
    e = p["epoxy"]
    for name, card, want, sf in (("epoxy", e["card"], e["want"], e["bid"]["sf"]),
                                 ("epoxy after a day", e["afterDay"]["card"], e["afterDay"]["want"], e["bid"]["sf"]),
                                 ("reopened", p["reload"]["card"], p["reload"]["want"], e["bid"]["sf"]),
                                 ("polish", p["polish"]["card"], p["polish"]["want"], p["polish"]["bid"]["sf"])):
        if not card.get("present"):
            out.append(name + ": no card")
            continue
        if card["figs"] != shown(want, sf):
            out.append("%s: the card reads %r, the model says %r" % (name, card["figs"], shown(want, sf)))
    live = e["afterContingency"]
    if live["live"] != shown(live["want"], e["bid"]["sf"]):
        out.append("a Contingency typed on the Review left the card at %r" % live["live"])
    return out


def test_the_review_draws_the_block_in_the_sheets_words_from_the_model(page):
    assert page_problems(page) == []
    c = page["epoxy"]["card"]
    assert c["title"] == "Man hours & budget" and c["head"] == ["Item", "Quantity", "Unit", "Rate", "Total"]
    # the sheet's words, but for "crew", which the page never says (test_nothing_on_screen_says_labour_or_crew: it is Guys)
    words = {PAGE_WORDS.get(w, w) for w in LABELS["Epoxy"].values()}
    assert [r[0] for r in c["rows"]] and all(r[0] in words for r in c["rows"]), [r[0] for r in c["rows"]]
    assert {r[0] for r in c["rows"]} == words, "every figure of the block is on the card"
    # Hanz's own block: 3 guys for 6 days at $32.20 is 144 man hours over 6 days
    assert (c["figs"]["mh.hours"], c["figs"]["mh.days"], c["figs"]["mh.guys"], c["figs"]["mh.budget"]) == ("144.00", "6.00", "3.00", "144.00")
    assert c["figs"]["mh.rate"] == "$32.20 / hr" and c["figs"]["mh.days.u"] == "8 hour days"


def test_the_card_moves_with_a_keystroke_and_with_the_crew(page):
    e = page["epoxy"]
    before, after = e["want"], e["afterContingency"]["want"]
    assert after["markup_cont"] == before["markup_cont"] + 500 and after["markup_soft"] > before["markup_soft"] + 500
    assert e["afterContingency"]["rebuilt"] == e["afterContingency"]["live"], "the repaint and a fresh paint disagree"
    assert e["afterDay"]["want"]["man_hours"] == 3 * 7 * 8 and e["afterDay"]["card"]["figs"]["mh.hours"] == "168.00"


def test_a_reopened_bid_draws_the_same_card_and_saves_nothing(page):
    r = page["reload"]
    assert r["card"]["figs"] == page["epoxy"]["afterDay"]["card"]["figs"]
    assert r["total"] == r["savedTotal"] and r["saves"] == 0


def test_a_polish_root_draws_it_and_a_seal_option_does_not(page):
    w = page["polish"]["want"]
    assert (w["man_hours"], w["crew"], w["total_days"]) == (3 * 5 * 8 + 3 * 0.5 * 8, 3, 5.5)
    assert page["seal"]["card"] == {"present": False} and page["seal"]["epoxyCard"] is True


# ── 4. each figure's line, broken, goes red ────────────────────────────────────────────────────────────────────
FORMULA_BREAKS = {
    "man hours are the labor dollars": ("    var hours = laborTotal(atOne, conditions, 0);",
                                        "    var hours = laborTotal(rows, conditions, 0);"),
    "the fourth hand is left out": ("    var hours = laborTotal(atOne, conditions, 0);",
                                    "    var hours = laborTotal(atOne, null, 0);"),
    "the crew is one more": ("    var crew = crewRow ? num(crewRow.guys) : null;",
                             "    var crew = crewRow ? num(crewRow.guys) + 1 : null;"),
    "the crew is the drive's": ("      if (!isTravelRow(r) && rowOn(r) && num(r.guys) > 0) crewRow = r;",
                                "      if (rowOn(r) && num(r.guys) > 0) crewRow = r;"),
    "the day is always 8 hours": ("    var perDay = crewRow ? dayHours(crewRow) : HOURS_PER_DAY;",
                                  "    var perDay = HOURS_PER_DAY;"),
    "the days are not over the crew": ("    var days = crew && hours > 0 ? hours / perDay / crew : null;",
                                       "    var days = crew && hours > 0 ? hours / perDay : null;"),
    "the estimated costs leave out the taxes": ("    var est = num(bid.sub_total) + num(bid.taxes) + num(bid.fees_and_bond);",
                                                "    var est = num(bid.sub_total) + num(bid.fees_and_bond);"),
    "the estimated costs a square foot": ("      est_costs: est, est_costs_per_sf: sf > 0 ? est / sf : null,",
                                          "      est_costs: est, est_costs_per_sf: sf > 0 ? total / sf : null,"),
    "the budget is not the man hours": ("      budget_hours: hours,", "      budget_hours: hours - num(rows.length),"),
    "the markup leaves out the discount": ("    var markup = num(bid.gp) + num(bid.hard_bid) + num(bid.contingency);",
                                           "    var markup = num(bid.gp) + num(bid.contingency);"),
    "the markup leaves out the contingency": ("    var markup = num(bid.gp) + num(bid.hard_bid) + num(bid.contingency);",
                                              "    var markup = num(bid.gp) + num(bid.hard_bid);"),
    "the markup share is of the sub-total": ("      markup_cont: markup, markup_cont_pct: total ? markup / total : null,",
                                             "      markup_cont: markup, markup_cont_pct: total ? markup / num(bid.sub_total) : null,"),
    "GP per day is the soft figure": ("      gp_per_day: days ? markup / days : null,", "      gp_per_day: days ? soft / days : null,"),
    "GP a man hour is over the days": ("      gp_per_mh: hours > 0 ? markup / hours : null,", "      gp_per_mh: hours > 0 ? markup / days : null,"),
    "the labor rate is one more": ("      labor_rate: crewRow ? laborRateOf(crewRow, pw) : null,",
                                   "      labor_rate: crewRow ? laborRateOf(crewRow, pw) + 1 : null,"),
    "the soft costs are left out": ("    var soft = markup + num(bid.super_pto) + num(bid.soft_costs);",
                                    "    var soft = markup + num(bid.super_pto);"),
    "the soft share is the markup's": ("      markup_soft: soft, markup_soft_pct: total ? soft / total : null",
                                       "      markup_soft: soft, markup_soft_pct: total ? markup / total : null"),
}


@pytest.mark.parametrize("name", sorted(FORMULA_BREAKS))
def test_the_parity_goes_red_when_a_figures_line_is_broken(tmp_path, name):
    old, new = FORMULA_BREAKS[name]
    frontend = break_source(tmp_path, "js/bid-model.js", old.strip(), new.strip())
    copy_unmodified(frontend, PARITY_FILES)
    got = _parity(frontend, tmp_path)
    found = recorded_problems(got) + variant_problems(got) + golden_problems(got)[0]
    assert found, "the parity did not notice: " + name


PAGE_BREAKS = {
    "the card prints the crew as the days": ('      ["Total Days", rvc("mh.days", two(f.total_days)), { raw: rv("mh.days.u", day) }, "", ""],',
                                             '      ["Total Days", rvc("mh.days", two(f.crew)), { raw: rv("mh.days.u", day) }, "", ""],'),
    "the card's percentages are whole": ('    var share = function (n) { return n === null ? "" : (B.num(n) * 100).toFixed(1) + "%"; };',
                                         '    var share = function (n) { return n === null ? "" : (B.num(n) * 100).toFixed(0) + "%"; };'),
    "the card reads the root's labor": ("    var f = B.manHourBudget(M.labor, M.conditions, B.prevailingApplied(M), b);",
                                        "    var f = B.manHourBudget(ROOT.labor, M.conditions, B.prevailingApplied(M), b);"),
    "the card is drawn on every sheet": ('    if (layout !== "epoxy" && layout !== "polish") return "";', "    void layout;"),
    "the card is not drawn": ("    html += manHoursCard(b, onShow);", "    void manHoursCard;"),
}


@pytest.mark.parametrize("name", sorted(PAGE_BREAKS))
def test_the_page_checks_go_red_when_the_card_is_broken(tmp_path, name):
    old, new = PAGE_BREAKS[name]
    frontend = break_source(tmp_path, "js/polish-estimate.js", old.strip(), new.strip())
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(REVIEW, frontend, plan_json(tmp_path))
    if proc.returncode != 0:
        return                                               # a crash is the loudest way to go red
    got = last_json_line(proc.stdout)
    noticed = page_problems(got) or got["seal"]["card"] != {"present": False}
    assert noticed, "the page checks did not notice: " + name
