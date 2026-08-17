"""The Polish BETA's bid maths, pinned to Kyle's workbook and re-derived in Python.

`frontend/js/polish-bid-core.js` is a transcription of the markup column on the Polish tab of
`backend/templates/estimate_sheet_5.7.xlsx`. Nothing on the screen loads that workbook any more,
so nothing on the screen can notice when the transcription and the file stop agreeing — and every
way this arithmetic can be wrong produces a number that looks exactly like a bid.

TWO LAYERS, BOTH EXECUTED.

**Layer 1 — the structure pin.** Open the real .xlsx without `data_only` and compare each formula
STRING against what the JS was written from. This is the half that fails when Kyle edits his file:
he changes a rate or moves a row, the pin goes red, and somebody updates both sides deliberately
instead of the tool quietly pricing last month's markup.

**Layer 2 — the value vectors.** Run the engine under node and re-derive every figure here in
Python, transliterated from the formula strings Layer 1 has just pinned. Two independent
implementations of the same twenty-six cells, compared to the cent. The vectors live in
`tests/js/polish-bid-harness.js` so the two sides cannot disagree about the INPUTS while agreeing
line for line about the answers.

THE FAILURES THIS IS SHAPED AROUND.

  * **A GP band off by one dollar.** B67 uses strictly `<`, so a $6,500 sub-total is a 45% job,
    not a 52% one — a $520 swing on a small floor. Every edge is tested from both sides.
  * **ROUNDUP the wrong way on a negative.** The hard-bid line (D68) is a give-back. Excel's
    ROUNDUP goes AWAY from zero, so -1,234.2 becomes -1,235; `Math.ceil` would make it -1,234 and
    silently raise every hard bid.
  * **The two tax bases swapped.** Sales tax is on MATERIALS only; the remodel tax is on the
    labour side plus the markups and never on materials. Both bases are exercised with real
    material and real labour on the job, so swapping them moves the total instead of cancelling.
  * **`SUM(D64:D68)` read as five live rows.** D65 is empty and D66 holds the TEXT "Totals".
  * **Rounding once at the end.** The sheet rounds up at every step and the difference compounds
    through GP, super/PTO, soft costs and the remodel tax.
  * **A ten-hour day.** D37 multiplies by `IF($E$35="8 hour days",8,10)`. Kyle's own screenshot —
    3 guys x 5 days x $32.20 = $3,864 — is what pins the 8.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import math
import pathlib
import re
import shutil
import subprocess
import warnings

import pytest

openpyxl = pytest.importorskip("openpyxl")

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
CORE = FRONTEND / "js" / "polish-bid-core.js"
TEMPLATE = ROOT / "backend" / "templates" / "estimate_sheet_5.7.xlsx"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "polish-bid-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

FIX_BOTH = ("update frontend/js/polish-bid-core.js AND this pin together — the engine no longer "
            "matches Kyle's workbook, and nothing on the polish screen can tell")


# ── Layer 1: the formulas this engine was transcribed from ────────────────────
# Read out of the template. Every one of them is quoted in polish-bid-core.js's header.
PINNED = {
    # labour: guys x days x hourly rate x hours-per-day
    "D37": '=(A37*B37*C37)*IF($E$35="8 hour days",8,10)',
    "E35": "8 hour days",
    # materials
    "D31": "=ROUNDUP(SUM(D17:D30),0)",
    "B32": 0.02,
    "D32": "=ROUNDUP(D31*B32,0)",
    "D33": "=SUM(D31:D32)",
    # labour, escalated and burdened
    "D45": "=ROUNDUP(SUM(D37:D44),0)",
    "C46": '=IF(D5="Yes",5%,0)',
    "D46": "=ROUNDUP((D45*C46),0)",
    "C47": 0.12,
    "D47": "=ROUNDUP((D45+D46)*C47,0)",
    # the cost sub-total, tooling (D55) and travel (D61) included in the range
    "D64": "=ROUNDUP(SUM(D33,D45:D47,D55,D61),0)",
    # gross profit: a margin divided up to, not a mark-on added
    "B67": "=IF(D64<6500,0.52,IF(D64<15000,0.45,IF(D64<22500,0.35,IF(D64<32500,0.32,0.3))))",
    "D67": "=ROUNDUP(SUM(D64,D74,D77)/(1-B67),0)-ROUNDUP(SUM(D64,D74,D77),0)",
    # the hard-bid give-back, negative, with an else-less inner IF
    "B68": '=IF(B5="yes",IF(D64>=60000,-0.04,IF(B4="yes",IF(D64>=13000,-0.025,0))))',
    "D68": "=ROUNDUP(SUM(D64,D67)*B68,0)",
    # supervision/PTO and soft costs
    "B69": 0.027,
    "D69": "=ROUNDUP(SUM(D64:D68,D71,D74,D77)*B69,0)",
    "B70": 0.16,
    "D70": "=(ROUNDUP(SUM(D64:D69,D71,D74,D77)*B70,0))+0",
    "D71": 0,
    # the two taxes
    "B74": '=IF($B$6="no",0,0.09475)',
    "D74": "=ROUNDUP(SUM(D33)*B74,0)",
    "B75": '=IF(D6="yes",0.1,0)',
    "D75": "=ROUNDUP(SUM(D45:D47,D55,D61,D67:D71,D77)*B75,0)",
    "D76": "=SUM(D74:D75)",
    # fees and bond
    "D77": "=ROUNDUP(B77*C77,0)",
    "B78": 0,
    "D78": "=ROUNDUP(SUM(D64,D67,D68,D69:D71,D74,D75:D77)*B78,0)",
    "D79": "=ROUNDUP(SUM(D77:D78),0)",
    # the bid, and the price per square foot
    "D82": "=SUM(D64,D67:D71,D76,D79)",
    "C81": "=B35",
    "B35": "=E18",
    "C82": "=D82/C81",
}


@pytest.fixture(scope="module")
def polish():
    """The Polish tab with its FORMULAS intact. `data_only` would hand back the last values Excel
    cached, which is the one thing this file must not be checked against."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")     # openpyxl warns about the sheet's data validations
        wb = openpyxl.load_workbook(TEMPLATE, data_only=False)
    return wb["Polish"]


def test_every_formula_the_engine_was_written_from_is_still_there(polish):
    """One test, every cell, so a template edit reports all of its damage at once."""
    drifted = []
    for addr in sorted(PINNED):
        want = PINNED[addr]
        got = polish[addr].value
        if got != want:
            drifted.append("Polish!%s: engine assumes %r, workbook now says %r" % (addr, want, got))
    assert not drifted, ("%d cell(s) have moved under the polish engine — %s:\n  %s"
                         % (len(drifted), FIX_BOTH, "\n  ".join(drifted)))


def test_the_totals_label_is_why_the_d64_ranges_collapse(polish):
    """`SUM(D64:D68,...)` in D69 and `SUM(D64:D69,...)` in D70 look like five and six live rows.
    They are not: D65 is EMPTY and D66 holds the TEXT "Totals", both of which Excel's SUM skips.
    That is the ONLY reason polish-bid-core.js adds D64+D67+D68 there. Put a number in either cell
    and the engine starts under-charging super/PTO and soft costs on every job."""
    assert polish["D65"].value is None, (
        "D65 has gained a value, so SUM(D64:D68) is no longer D64+D67+D68 — %s" % FIX_BOTH)
    assert polish["D66"].value == "Totals", (
        "D66 is the text label that makes SUM(D64:D68) skip it; it now holds %r — %s"
        % (polish["D66"].value, FIX_BOTH))


# ── the executed engine ───────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a maths bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@needs_node
def test_the_module_loads_and_priced_every_vector(ran):
    """A syntax error would otherwise surface as thirty identical opaque failures."""
    assert len(ran["vectors"]) >= 25, "the vector list has shrunk"
    for v in ran["vectors"]:
        assert isinstance(v["out"]["total"], (int, float)), v["label"]


# ── the sheet's own numbers, against the engine's constants ───────────────────
def _rate_in(formula):
    """The rate a one-condition IF chooses between, out of the formula's own text.

    Each of C46 / B74 / B75 is `IF(<flag>, <rate>, 0)` in some order, and in each of them the rate
    is the only percentage or the only fractional number — everything else in the string is a cell
    row or a zero. Picking it that way rather than by position means a reordered IF still reads
    correctly instead of quietly pinning the wrong token."""
    marked = re.findall(r"(\d+(?:\.\d+)?)%", formula)
    if marked:
        return float(marked[0]) / 100.0
    fractions = re.findall(r"\d+\.\d+", formula)
    assert len(fractions) == 1, "cannot tell which number is the rate in %s" % formula
    return float(fractions[0])


@needs_node
def test_the_flat_rates_come_from_the_cells_that_hold_them(ran, polish):
    """Each rate is read off the workbook and compared with the constant the engine ships. A
    hand-typed 0.02 that drifts from B32 is invisible from either side on its own."""
    rates = ran["constants"]["rates"]
    for addr, key in [("B32", "SHIPPING"), ("C47", "BURDEN"), ("B69", "SUPER_PTO"),
                      ("B70", "SOFT_COSTS"), ("B78", "BOND")]:
        assert float(polish[addr].value) == pytest.approx(rates[key]), (
            "Polish!%s is %r but RATES.%s is %r — %s"
            % (addr, polish[addr].value, key, rates[key], FIX_BOTH))
    # The three rates that live inside an IF, so the cell holds a formula rather than a number.
    for addr, key in [("C46", "ESCALATION"), ("B74", "SALES_TAX"), ("B75", "REMODEL")]:
        assert _rate_in(polish[addr].value) == pytest.approx(rates[key]), (
            "Polish!%s is %s but RATES.%s is %r — %s"
            % (addr, polish[addr].value, key, rates[key], FIX_BOTH))


@needs_node
def test_a_day_is_eight_hours_because_the_sheet_says_so(ran, polish):
    """D37 multiplies by `IF($E$35="8 hour days",8,10)`. Switch E35 to ten-hour days and every
    labour line in this tool is 20% light."""
    assert polish["E35"].value == "8 hour days"
    assert '8,10' in polish["D37"].value
    assert ran["constants"]["hoursPerDay"] == 8, (
        "HOURS_PER_DAY disagrees with E35 — %s" % FIX_BOTH)
    anchor = [l for l in ran["labor"] if "screenshot" in l["label"]][0]
    # 3 x 5 x 32.2 x 8. At ten-hour days this row costs $4,830 and nothing else here would notice.
    assert round(anchor["cost"], 6) == 3864, (
        "Kyle's own row prices at %r, not $3,864 — the hours per day are wrong" % anchor["cost"])


@needs_node
def test_the_gp_bands_are_the_ones_written_in_b67(ran, polish):
    """Parsed out of the formula text, then answered by the REAL gpPct at each edge and one dollar
    below it. `<=` instead of `<` moves the margin on every job that lands on a round number."""
    f = polish["B67"].value
    edges = [(int(e), float(r)) for e, r in re.findall(r"D64<(\d+),(\d*\.?\d+)", f)]
    floor_rate = float(re.search(r",(\d*\.?\d+)\)+$", f).group(1))
    bands = ran["constants"]["gpBands"]
    assert [[e, r] for e, r in edges] + [[None, floor_rate]] == bands, (
        "GP_BANDS %r no longer matches B67 %s — %s" % (bands, f, FIX_BOTH))

    probe = ran["gpProbe"]
    rates = [r for _, r in edges] + [floor_rate]
    for i, (edge, rate) in enumerate(edges):
        assert probe[str(edge - 1)] == pytest.approx(rate), \
            "a sub-total of %d should still be the %s band" % (edge - 1, rate)
        assert probe[str(edge)] == pytest.approx(rates[i + 1]), (
            "B67 is strictly `<`, so a sub-total of exactly %d belongs to the %s band, not %s"
            % (edge, rates[i + 1], rate))


@needs_node
def test_the_hard_bid_gate_is_the_one_written_in_b68(ran, polish):
    """`=IF(B5="yes",IF(D64>=60000,-0.04,IF(B4="yes",IF(D64>=13000,-0.025,0))))` — B5 hard bid,
    B4 local. Four behaviours, all of them checked against the executed function: the 60k rule
    ignores local, the 13k rule requires it, the innermost IF has no else (Excel's FALSE, which
    sums as 0), and no hard bid means no give-back at any size."""
    f = polish["B68"].value
    gates = [(int(t), float(r)) for t, r in re.findall(r"D64>=(\d+),(-?\d*\.?\d+)", f)]
    assert len(gates) == 2, "B68 no longer has two thresholds: %s" % f
    (big_at, big_rate), (local_at, local_rate) = gates

    for row in ran["hardBidProbe"]:
        sub, hb, loc, got = row["sub"], row["hard_bid"], row["local"], row["pct"]
        if not hb:
            want = 0
        elif sub >= big_at:
            want = big_rate
        elif loc and sub >= local_at:
            want = local_rate
        else:
            want = 0
        assert got == pytest.approx(want), (
            "hard bid %s, local %s at a sub-total of %d gave %r, B68 says %r — %s"
            % (hb, loc, sub, got, want, FIX_BOTH))

    # And the two gates are genuinely different rules, or the test above proves less than it looks.
    assert big_rate < local_rate < 0, "both hard-bid rates should be give-backs: %s" % f


# ── Layer 2: the same twenty-six cells, re-derived in Python ───────────────────
# Transliterated from the formula strings PINNED above, deliberately not from the JS. Layer 1 ties
# those strings to Kyle's file; this ties the engine's answers to those strings.
def _num(raw):
    """polish-bid-core's num(): tolerant, and 0 rather than None, because this is arithmetic."""
    if raw is None or raw == "" or isinstance(raw, bool):
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = re.sub(r"[$,\s]", "", str(raw))
    if not re.match(r"^-?\d*\.?\d+$", s):
        return 0.0
    return float(s)


def round_up(n):
    """Excel ROUNDUP(n, 0): AWAY from zero, so the negative hard-bid line rounds down.

    The 12-significant-figure guard mirrors the engine's `toPrecision(12)`; without it a product
    like 110.00000000000001 buys a whole extra dollar off the back of a float's rounding error."""
    v = _num(n)
    g = float("%.12g" % v)
    return float(math.ceil(g)) if g >= 0 else float(-math.ceil(-g))


def _gp_pct(sub_total):
    """B67, strictly `<`."""
    if sub_total < 6500:
        return 0.52
    if sub_total < 15000:
        return 0.45
    if sub_total < 22500:
        return 0.35
    if sub_total < 32500:
        return 0.32
    return 0.30


def _hard_bid_pct(sub_total, cond):
    """B68. The else-less inner IF yields Excel's FALSE, which sums as 0."""
    if not cond.get("hard_bid"):
        return 0.0
    if sub_total >= 60000:
        return -0.04
    if cond.get("local") and sub_total >= 13000:
        return -0.025
    return 0.0


def chain(inp):
    """Kyle's markup column, cell by cell, in Python."""
    cond = inp.get("conditions") or {}
    sf = _num(inp.get("sf"))

    material = round_up(inp.get("material"))                                    # D31
    shipping = round_up(material * 0.02)                                        # D32, B32
    material_total = material + shipping                                        # D33

    labor = round_up(inp.get("labor"))                                          # D45
    escalation = round_up(labor * (0.05 if cond.get("prevailing_wage") else 0))  # D46, C46
    burden = round_up((labor + escalation) * 0.12)                              # D47, C47
    labor_total = labor + escalation + burden

    # D64: D55 (tooling) and D61 (travel) are in the range and are zero in the beta.
    sub_total = round_up(material_total + labor + escalation + burden)

    sales_tax_pct = 0.09475 if cond.get("taxable") else 0                       # B74
    sales_tax = round_up(material_total * sales_tax_pct)                        # D74, MATERIALS ONLY
    fees = 0.0                                                                  # D77, B77xC77 blank

    gp_pct = _gp_pct(sub_total)                                                 # B67
    gp = (round_up((sub_total + sales_tax + fees) / (1 - gp_pct))                # D67
          - round_up(sub_total + sales_tax + fees))
    hard_bid_pct = _hard_bid_pct(sub_total, cond)                               # B68
    hard_bid = round_up((sub_total + gp) * hard_bid_pct)                        # D68
    contingency = _num(inp.get("contingency"))                                  # D71

    # D69/D70: SUM(D64:D68) is D64+D67+D68 — D65 empty, D66 the text "Totals".
    super_pto = round_up((sub_total + gp + hard_bid + contingency + sales_tax + fees) * 0.027)
    soft_costs = round_up(
        (sub_total + gp + hard_bid + super_pto + contingency + sales_tax + fees) * 0.16)

    remodel_pct = 0.10 if cond.get("remodel_tax") else 0                        # B75
    remodel_tax = round_up(                                                     # D75
        (labor + escalation + burden + gp + hard_bid + super_pto + soft_costs + contingency + fees)
        * remodel_pct)
    taxes = sales_tax + remodel_tax                                             # D76

    bond_pct = 0.0                                                              # B78
    bond = round_up((sub_total + gp + hard_bid + super_pto + soft_costs + contingency             # D78
                     + sales_tax + remodel_tax + taxes + fees) * bond_pct)
    fees_and_bond = round_up(fees + bond)                                       # D79

    total = (sub_total + gp + hard_bid + super_pto + soft_costs                 # D82
             + contingency + taxes + fees_and_bond)

    return {
        "material": material, "shipping": shipping, "material_total": material_total,
        "labor": labor, "escalation": escalation, "burden": burden, "labor_total": labor_total,
        "sub_total": sub_total,
        "gp_pct": gp_pct, "gp": gp, "hard_bid_pct": hard_bid_pct, "hard_bid": hard_bid,
        "super_pto": super_pto, "soft_costs": soft_costs, "contingency": contingency,
        "sales_tax_pct": sales_tax_pct, "sales_tax": sales_tax,
        "remodel_pct": remodel_pct, "remodel_tax": remodel_tax, "taxes": taxes,
        "fees": fees, "bond": bond, "bond_pct": bond_pct, "fees_and_bond": fees_and_bond,
        "total": total, "sf": sf,
        "per_sf": (total / sf) if sf > 0 else None,       # C82 = D82/C81
    }


@needs_node
def test_every_vector_agrees_to_the_cent(ran):
    """THE TEST. Two independent implementations of the same chain, every key, every vector."""
    wrong = []
    for v in ran["vectors"]:
        want = chain(v["input"])
        got = v["out"]
        assert sorted(got) == sorted(want), (
            "the engine returns %r and this test expects %r — the shapes have to match or a "
            "missing line would never be compared" % (sorted(got), sorted(want)))
        for key in sorted(want):
            w, g = want[key], got[key]
            if w is None or g is None:
                ok = w is None and g is None
            else:
                ok = abs(float(g) - float(w)) <= 0.005
            if not ok:
                wrong.append("%s / %s: engine %r, Kyle's formulas %r" % (v["label"], key, g, w))
    assert not wrong, ("%d figure(s) disagree with the workbook's own arithmetic:\n  %s"
                       % (len(wrong), "\n  ".join(wrong)))


def _by(ran, needle):
    hits = [v for v in ran["vectors"] if needle in v["label"]]
    assert hits, "no vector labelled %r — the harness list has changed" % needle
    return hits[0]["out"]


@needs_node
def test_both_sides_of_every_gp_edge_are_covered(ran):
    """A band table is easy to get right in the middle and wrong at the edges, so the vector list
    has to actually LAND on them. This is the check that the coverage exists, not that it passes."""
    seen = {}
    for v in ran["vectors"]:
        seen[v["out"]["sub_total"]] = v["out"]["gp_pct"]
    for edge, below, above in [(6500, 0.52, 0.45), (15000, 0.45, 0.35),
                              (22500, 0.35, 0.32), (32500, 0.32, 0.30)]:
        assert edge - 1 in seen and edge in seen, (
            "no vector lands on %d and %d, so the %s/%s edge is untested"
            % (edge - 1, edge, below, above))
        assert seen[edge - 1] == below and seen[edge] == above


@needs_node
def test_the_hard_bid_line_is_negative_and_rounds_away_from_zero(ran):
    """The give-back. `Math.ceil` on -2.5% of a $22,000 base would round TOWARDS zero and hand
    back less than Kyle's sheet does, on every hard bid, for ever."""
    out = _by(ran, "exactly 13,000: -2.5%")
    assert out["hard_bid_pct"] == -0.025
    assert out["hard_bid"] < 0, "the hard-bid line is a give-back, not an addition"
    raw = (out["sub_total"] + out["gp"]) * out["hard_bid_pct"]
    assert out["hard_bid"] == round_up(raw) <= math.floor(raw), (
        "%r is ROUNDUP-towards-zero of %r; Excel rounds away from it" % (out["hard_bid"], raw))
    # …and the give-back genuinely lowers the bid.
    assert out["total"] < _by(ran, "sub-total 13,000: the local gate withholds it")["total"]


@needs_node
def test_sales_tax_is_charged_on_materials_only(ran):
    """D74 takes D33, not the sub-total. Taxing the whole cost would add ~9.5% of the LABOUR to
    every taxable job — about $1,000 on this one."""
    on = _by(ran, "9.475% on the MATERIAL total only")
    off = _by(ran, "not taxable")
    assert off["sales_tax"] == 0 and off["sales_tax_pct"] == 0
    assert on["sales_tax_pct"] == 0.09475
    assert on["sales_tax"] == round_up(on["material_total"] * 0.09475)
    if_it_taxed_everything = round_up(on["sub_total"] * 0.09475)
    assert on["sales_tax"] != if_it_taxed_everything, "this vector cannot tell the two bases apart"
    assert on["total"] > off["total"]


@needs_node
def test_the_remodel_tax_skips_materials(ran):
    """D75 sums D45:D47 and D67:D71 — the labour side and the markups. D33 is deliberately absent,
    and this vector carries $12,000 of material so the two bases give different answers."""
    on = _by(ran, "10% on labour + markups")
    off = _by(ran, "not a remodel")
    assert off["remodel_tax"] == 0 and off["remodel_pct"] == 0
    assert on["remodel_pct"] == 0.10
    base = (on["labor"] + on["escalation"] + on["burden"] + on["gp"] + on["hard_bid"]
            + on["super_pto"] + on["soft_costs"] + on["contingency"] + on["fees"])
    assert on["remodel_tax"] == round_up(base * 0.10)
    with_materials = round_up((base + on["material_total"]) * 0.10)
    assert with_materials != on["remodel_tax"], (
        "this vector has no materials on it, so it cannot prove the base excludes them")
    assert on["remodel_tax"] < with_materials


@needs_node
def test_prevailing_wage_escalates_labour_and_the_burden_follows(ran):
    """C46 is 5% of labour, and D47 burdens labour PLUS the escalation — so prevailing wage moves
    two lines, not one."""
    on = _by(ran, "prevailing wage: 5% escalation")
    off = _by(ran, "no prevailing wage")
    assert off["escalation"] == 0
    assert on["escalation"] == round_up(on["labor"] * 0.05)
    assert on["burden"] == round_up((on["labor"] + on["escalation"]) * 0.12)
    assert on["burden"] > off["burden"], "the burden is being taken on bare labour"
    assert on["total"] > off["total"]


@needs_node
def test_a_contingency_feeds_the_markup_bases_not_just_the_total(ran):
    """D71 sits inside the super/PTO, soft-cost and remodel-tax ranges, so $5,000 of contingency
    adds MORE than $5,000 to the bid. Adding it once at the end would under-bid every job that
    carries one."""
    with_c = _by(ran, "contingency 5,000")
    without = _by(ran, "contingency 0, otherwise identical")
    assert with_c["contingency"] == 5000 and without["contingency"] == 0
    assert with_c["super_pto"] > without["super_pto"]
    assert with_c["soft_costs"] > without["soft_costs"]
    assert with_c["remodel_tax"] > without["remodel_tax"], "D71 is missing from the D67:D71 range"
    assert with_c["total"] - without["total"] > 5000, (
        "a contingency that only adds itself has been left out of three markup bases")


@needs_node
def test_the_price_per_sf_waits_for_an_area(ran):
    """C82 is `=D82/C81`. With no area typed the answer is not known — and 0 would read as free."""
    none_yet = _by(ran, "no area typed yet")
    assert none_yet["per_sf"] is None and none_yet["total"] > 0
    priced = _by(ran, "an area typed")
    assert priced["per_sf"] == pytest.approx(priced["total"] / priced["sf"])
    # Same job, same bid: the area divides the total, it does not change it.
    assert priced["total"] == none_yet["total"]


@needs_node
def test_an_empty_screen_prices_at_nothing_without_dividing_by_zero(ran):
    """The state the page opens in. GP divides by (1 - 0.52) on a zero sub-total, which must be
    0 rather than NaN, and the whole chain has to survive it."""
    out = _by(ran, "nothing entered at all")
    for key in ("material", "labor", "sub_total", "gp", "super_pto", "soft_costs", "total"):
        assert out[key] == 0, "%s is %r on an empty estimate" % (key, out[key])
    assert out["per_sf"] is None


@needs_node
def test_pasted_figures_price_the_same_as_typed_ones(ran):
    """These numbers arrive from a spreadsheet with dollar signs and commas on them."""
    out = _by(ran, "pasted out of a spreadsheet")
    assert out["material"] == 12001, "$12,000.50 of material rounds up to $12,001"
    assert out["labor"] == 8000
    assert out["contingency"] == 1000
    assert out["sf"] == 12500 and out["per_sf"] is not None


# ── the labour rows ───────────────────────────────────────────────────────────
@needs_node
def test_a_labour_row_is_guys_times_days_times_rate_times_eight(ran):
    for l in ran["labor"]:
        want = _num(l["row"].get("guys")) * _num(l["row"].get("days")) * _num(l["row"].get("rate")) * 8
        assert round(l["cost"], 6) == round(want, 6), l["label"]
    empty = [l for l in ran["labor"] if "empty row" in l["label"]][0]
    assert empty["cost"] == 0, "an empty row must cost nothing, not NaN"
    no_days = [l for l in ran["labor"] if "no days yet" in l["label"]][0]
    assert no_days["cost"] == 0


@needs_node
def test_the_labour_total_is_left_unrounded_for_d45_to_round(ran):
    """D45 is `=ROUNDUP(SUM(D37:D44),0)` — one rounding, at the sum. Rounding each row first and
    the sum again is a different number, and it is the sheet's job to say which."""
    t = ran["laborTotal"]
    want = sum(_num(r.get("guys")) * _num(r.get("days")) * _num(r.get("rate")) * 8
               for r in t["rows"])
    assert round(t["total"], 6) == round(want, 6)
    assert t["total"] != round_up(t["total"]), (
        "this fixture no longer distinguishes a rounded total from an unrounded one")
    assert t["empty"] == 0 and t["nothing"] == 0


@needs_node
def test_lf_rows_are_not_added_to_the_area(ran):
    """Cove, saw-cutting and striping are measured in linear feet. Adding them to the square feet
    would divide the bid by the wrong number and quote a price per SF that is too low."""
    t = ran["takeoff"]
    assert t["mixed"] == 12500, "9,000 SF + 3,500 SF, and the 240 LF of cove left out of it"
    assert t["lfOnly"] == 0
    assert t["empty"] == 0 and t["nothing"] == 0


# ── formatting, migration, and what blocks a price ────────────────────────────
@needs_node
def test_the_display_helpers_read_like_money_and_rates(ran):
    f = ran["formats"]
    assert f["money"] == ["$15,681", "$0", "$1,235", "-$1,235", "$0"]
    assert f["money2"] == ["$32.20", "$0.00", "$1,234.57", "-$32.20"]
    # Trailing zeros trimmed, and the precision that matters KEPT: 9.475% is the Kansas rate and
    # 9.5% is a different bid on a big floor.
    assert f["pct"] == ["2.7%", "45%", "-2.5%", "0%", "9.475%", "16%", "-4%", "7.975%"]
    assert f["sf"] == ["12,500", "0", "1,632.5"]
    assert f["num"] == [1200, 32.2, 0, 0, 0, 0], "pasted values, and 0 rather than null"


@needs_node
def test_roundup_goes_away_from_zero_and_survives_float_dust(ran):
    assert ran["formats"]["roundUp"] == [2, -2, 1, -1, 0, 110, 1, 0], (
        "ROUNDUP is Excel's: away from zero, and 110.00000000000001 is 110")


@needs_node
def test_a_v1_draft_opens_as_a_v2_model(ran):
    """v1 had named areas and materials typed straight into worksheet rows; v2 has assemblies. The
    areas survive as measurements waiting for an assembly, the labour comes across with `crew`
    read as the GUYS COUNT — reading it as money would multiply a saved estimate by eight — and
    the six replaced keys are dropped rather than half-carried."""
    m = [x for x in ran["migrations"] if "v1 draft" in x["label"]][0]
    before, after = m["before"], m["after"]
    assert after["version"] == 2
    assert [r["measurement"] for r in after["takeoff"]] == [9000, 3500], "the areas are the takeoff"
    assert all(r["unit"] == "SF" for r in after["takeoff"])
    assert all(r["assembly_id"] == "" for r in after["takeoff"]), (
        "v1 had no assemblies, so inventing an id would point at nothing")
    assert [r["guys"] for r in after["labor"]] == [4, 2, 2], "crew is the guys count"
    assert [r["id"] for r in after["labor"]] == ["polishing", "mockup", "jointfill"]
    assert [r["days"] for r in after["labor"]] == [6, 1, 2]
    assert after["conditions"] == before["conditions"]
    assert after["contingency"] == 0
    for gone in ("system", "tooling", "materials", "added", "adds", "options"):
        assert gone not in after, "%s is replaced by assemblies and must not be carried over" % gone
    assert ran["migrationIsIdempotent"], "migrating twice reshapes the model again"


@needs_node
def test_no_saved_model_however_broken_throws(ran):
    """A draft is whatever was in localStorage or the drafts table, including something a
    half-shipped build wrote. An estimator opening an old job gets a working screen."""
    fresh = ran["fresh"]
    for m in ran["migrations"]:
        after = m["after"]
        assert after["version"] == 2, m["label"]
        assert isinstance(after["takeoff"], list) and after["takeoff"], m["label"]
        assert isinstance(after["labor"], list) and after["labor"], m["label"]
        assert sorted(after["conditions"]) == sorted(fresh["conditions"]), m["label"]
        assert after["contingency"] is not None and after["contingency"] != "", m["label"]
    partial = [x for x in ran["migrations"] if "one condition saved" in x["label"]][0]["after"]
    assert partial["conditions"]["taxable"] is False, "the saved condition was overwritten"
    assert partial["conditions"]["local"] is True, "the missing ones fall back to the defaults"


@needs_node
def test_the_fresh_model_carries_the_templates_own_labour_seeds(ran):
    """A37 = 3 guys, C37 = $32.20/hr, B40 = half a day for the mock-up. Days are left blank on the
    two an estimator has to judge, which is why a fresh model reports them as unfinished."""
    fresh = ran["fresh"]
    assert [r["guys"] for r in fresh["labor"]] == [3, 3, 3]
    assert [r["rate"] for r in fresh["labor"]] == [32.2, 32.2, 32.2]
    assert [r["days"] for r in fresh["labor"]] == ["", 0.5, ""]
    assert fresh["conditions"] == {"local": True, "hard_bid": False, "prevailing_wage": False,
                                  "taxable": True, "remodel_tax": False}
    assert len(fresh["takeoff"]) == 1 and fresh["takeoff"][0]["unit"] == "SF"


@needs_node
def test_what_blocks_a_price_is_said_in_words_an_estimator_can_act_on(ran):
    says = {b["label"]: b["says"] for b in ran["blockers"]}
    assert "Pick an assembly for takeoff row 1" in says["a measurement with no assembly picked"]
    assert says["an assembly with no measurement"] == \
        ["Add a measurement for Salt & Pepper polish"]
    assert says["an assembly with no measurement and no name either"] == \
        ["Add a measurement for takeoff row 1"]
    assert says["every takeoff row empty"] == ["Add at least one takeoff row"]
    # Name only the empty box. "guys, days and rate" at a row whose guys and rate are already
    # filled sends the estimator hunting through fields that are fine.
    assert "Add the days for Polishing" in \
        says["a labour row with guys and a rate but no days"]
    # A row at 0 days is switched off on purpose, and a wholly empty one was never started.
    # Neither is half-filled, and neither should stop a bid.
    assert says["ready to price: a switched-off labour row is not half-filled"] == []
    assert says["a model that is not a model at all"], "a broken model is not ready to price"
