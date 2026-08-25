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
  * **The remodel tax charged at the sheet's 10%.** B75 hardcodes a rate that exists nowhere in
    Kansas law. The engine charges the county's real one instead — the state 6.5% plus the county
    portion, 7.975% in Johnson County, handed in as `remodel_rate` — and keeps the sheet's figure
    in `RATES.SHEET_REMODEL` purely so Layer 1 can still pin B75. Both halves are asserted here:
    that the pin holds, and that nothing prices from it. This is the ONE cell where the two files
    are meant to disagree, so it is the one place drift could hide behind "that's deliberate".
  * **A missing county rate confused with a zero one.** Absent/null/"" is "nobody has picked a
    county" and falls back to the Kansas state 6.5%; an explicit 0 is a KNOWN rate of nothing,
    because Missouri taxes remodel labour as exempt. Flatten the two through `num()` and every
    Missouri remodel is charged a Kansas tax on a screen that looks completely normal.
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

# B75 is the one cell the engine departs from ON PURPOSE, so its drift message has to be different:
# there is no "make them match" fix here, there is a decision to re-take.
FIX_SHEET_REMODEL = (
    "B75's rate is transcribed into RATES.SHEET_REMODEL and deliberately NOT charged — the engine "
    "prices the county's real Kansas rate (backend/reference_tax.py) because 10% is not a real "
    "rate anywhere. If Kyle has edited B75, reconcile SHEET_REMODEL, the PINNED formula string "
    "and this assertion TOGETHER and decide whether the departure still says what we mean; do not "
    "re-point either side at a rate this engine actually charges")


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
    assert len(ran["vectors"]) >= 35, "the vector list has shrunk"
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
    # B75 maps to SHEET_REMODEL, not to a rate the engine charges: the sheet still says 10%, the
    # engine records that same 10% so this pin can exist, and it prices the county's rate instead.
    # The test below is the other half — that SHEET_REMODEL reaches no bid.
    for addr, key, fix in [("C46", "ESCALATION", FIX_BOTH), ("B74", "SALES_TAX", FIX_BOTH),
                           ("B75", "SHEET_REMODEL", FIX_SHEET_REMODEL)]:
        assert _rate_in(polish[addr].value) == pytest.approx(rates[key]), (
            "Polish!%s is %s but RATES.%s is %r — %s"
            % (addr, polish[addr].value, key, rates[key], fix))


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


KS_STATE_RATE = 0.065       # RATES.KS_STATE — the floor when no county has been picked yet
SHEET_REMODEL_RATE = 0.10   # B75's own figure, transcribed and never charged


def _remodel_pct(inp, cond):
    """B75's rate — the ONE place this re-derivation departs from the formula string it pins.

    B75 is `=IF(D6="yes",0.1,0)`. Transliterating that literally is exactly what must NOT happen:
    Kansas charges sales tax on commercial remodel LABOUR at the state 6.5% plus the county portion
    only, so the engine takes the county's rate as an input and this mirrors that rule instead.
    Nothing here resolves to SHEET_REMODEL_RATE, and nothing in the engine does either.

    NULL IS NOT ZERO, and `_num` would flatten the two. Absent / None / "" is "no county picked
    yet" and stands the state rate up until one is; an explicit 0 is a KNOWN rate of nothing —
    Missouri taxes remodel labour as exempt — and must be charged as nothing. Reading that 0 as
    "unknown" would put a Kansas tax on every Missouri remodel."""
    if not cond.get("remodel_tax"):
        return 0.0
    given = inp.get("remodel_rate")
    if given is None or given == "":
        return KS_STATE_RATE
    return _num(given)


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

    remodel_pct = _remodel_pct(inp, cond)                                       # B75, the county's
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
    """The one vector whose label contains `needle`. Exactly one: a needle that matches two labels
    would quietly hand a test the wrong job — and since the vectors below are deliberately near
    duplicates of each other, that is a real way for a passing test to prove nothing."""
    hits = [v for v in ran["vectors"] if needle in v["label"]]
    assert len(hits) == 1, (
        "%r matches %d vectors, not 1 — %r" % (needle, len(hits), [v["label"] for v in hits]))
    return hits[0]["out"]


def _remodel_base(out):
    """D75's base: `SUM(D45:D47,D55,D61,D67:D71,D77)` — the labour side and every markup. D33 is
    deliberately absent; D55 (tooling) and D61 (travel) are zero in the beta. Note the base does
    not depend on the RATE, which is what lets these tests re-price it at a different one."""
    return (out["labor"] + out["escalation"] + out["burden"] + out["gp"] + out["hard_bid"]
            + out["super_pto"] + out["soft_costs"] + out["contingency"] + out["fees"])


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
    """D75 sums D45:D47 and D67:D71 — the labour side and the markups. D33 is deliberately absent.

    This is a test about the BASE, so it is re-expressed against whatever rate its vector actually
    prices at rather than a hardcoded one. The vector carries $12,000 of material and a real,
    non-zero county rate, so a base that wrongly included D33 answers a DIFFERENT number — the two
    cannot agree by cancellation, which is the only thing that makes a base test worth running."""
    on = _by(ran, "on labour + markups, never on materials")
    off = _by(ran, "not a remodel: no remodel-tax line")
    assert off["remodel_tax"] == 0 and off["remodel_pct"] == 0
    rate = on["remodel_pct"]
    assert rate == pytest.approx(0.07975), (
        "this vector is meant to price at Johnson County's 7.975%% and priced at %r — the base "
        "check below only means something at a real, non-zero rate" % rate)

    base = _remodel_base(on)
    assert on["remodel_tax"] == round_up(base * rate), (
        "D75 came out %r; the labour side plus the markups at %r is %r"
        % (on["remodel_tax"], rate, round_up(base * rate)))
    with_materials = round_up((base + on["material_total"]) * rate)
    assert with_materials != on["remodel_tax"], (
        "this vector has no materials on it, so it cannot prove the base excludes them")
    assert on["remodel_tax"] < with_materials, (
        "the remodel tax is being charged on the $%d of material too — %r of tax nobody owes"
        % (on["material_total"], with_materials - on["remodel_tax"]))
    assert on["total"] > off["total"]


@needs_node
def test_the_remodel_rate_is_the_countys_and_only_the_toggle_charges_it(ran):
    """Hanz, 2026-08-18: "For the Remodel tax please use the real state tax or city tax, DONT USE
    10%". `markupChain` resolves B75's rate from the project's county, and each step of that can be
    wrong in a way that still prints something an estimator would send:

      * a rate that arrived from a county lookup must NOT switch the tax on by itself — only the
        remodel toggle (D6) may, or every non-remodel job in Johnson County is over-bid;
      * a supplied rate is charged verbatim, not snapped to a house figure: a county 0.8 points
        cheaper has to reach the BID (D82), not just the D75 line;
      * a job with no county on it yet falls back to the Kansas state 6.5%.

    The silent one is the last. A bid at the sheet's 10% on a job whose county nobody has picked
    looks entirely ordinary on the screen, and is 3.5 points of invented tax."""
    johnson = _by(ran, "Johnson County's 7.975%")
    lower = _by(ran, "a lower county rate of 7.15%")
    assert johnson["remodel_pct"] == pytest.approx(0.07975)
    assert lower["remodel_pct"] == pytest.approx(0.0715), (
        "a supplied county rate must be charged as given; 7.15%% came out as %r"
        % lower["remodel_pct"])
    assert lower["remodel_tax"] < johnson["remodel_tax"], (
        "the cheaper county charged %r of tax against Johnson's %r — the rate is being ignored"
        % (lower["remodel_tax"], johnson["remodel_tax"]))
    assert lower["total"] < johnson["total"], (
        "the county rate moves D75 but not the bid — the customer is quoted the same price in "
        "both counties")

    # A rate on the input is a lookup result, not a decision to tax.
    with_rate_off = _by(ran, "remodel toggle OFF")
    plain_off = _by(ran, "not a remodel: no remodel-tax line")
    assert with_rate_off["remodel_pct"] == 0 and with_rate_off["remodel_tax"] == 0, (
        "a county rate on the input switched the remodel tax on with the toggle OFF — %r of tax on "
        "a job that is not a remodel" % with_rate_off["remodel_tax"])
    assert with_rate_off["total"] == plain_off["total"], (
        "the same non-remodel job bids %r with a county rate attached and %r without one; the "
        "rate has to be inert until the toggle is on"
        % (with_rate_off["total"], plain_off["total"]))


@needs_node
def test_no_county_yet_is_the_state_floor_and_a_zero_county_rate_is_exempt(ran):
    """The null-is-not-zero rule, on the one input where flattening it mis-taxes a whole state.

    Absent / null / "" all mean "nobody has picked a county", and the engine stands the Kansas STATE
    rate up until somebody does. An explicit 0 is the opposite: a KNOWN rate of nothing. Missouri
    taxes remodel LABOUR as exempt, so a Missouri county carries no remodel rate on purpose and the
    page hands down a 0.

    Read that 0 as "unknown" and every Missouri remodel job is charged 6.5% of Kansas tax it does
    not owe — on this job, $1,731 — while the screen shows a perfectly plausible bid. `num()` would
    flatten the two, which is exactly why the engine tests the raw value before converting it."""
    needles = ("no county picked yet", "a null county rate", "an empty-string county rate")
    floors = [_by(ran, n) for n in needles]
    for needle, out in zip(needles, floors):
        assert out["remodel_pct"] == pytest.approx(KS_STATE_RATE), (
            "%s should fall back to the Kansas state %r and used %r instead"
            % (needle, KS_STATE_RATE, out["remodel_pct"]))
        assert out["remodel_tax"] > 0, (
            "%s charged no remodel tax at all — the fallback is not standing the state rate up"
            % needle)
    assert len(set(f["total"] for f in floors)) == 1, (
        "an absent rate, a null one and an empty string all mean 'no county yet' and must bid "
        "alike; they bid %r" % [f["total"] for f in floors])

    exempt = _by(ran, "an explicit 0")
    plain_off = _by(ran, "not a remodel: no remodel-tax line")
    assert exempt["remodel_pct"] == 0, (
        "a county rate of exactly 0 is Missouri's exempt labour, and it resolved to %r — a 0 read "
        "as 'unknown' taxes every Missouri remodel at a Kansas rate" % exempt["remodel_pct"])
    assert exempt["remodel_tax"] == 0, (
        "an exempt county was charged %r of remodel tax" % exempt["remodel_tax"])
    assert exempt["remodel_tax"] != floors[0]["remodel_tax"], (
        "an explicit 0 and no county at all price the same, so this vector cannot tell the two "
        "apart — the whole point of the distinction")
    assert exempt["total"] == plain_off["total"], (
        "an exempt remodel must bid what the same job bids with the remodel toggle off: %r vs %r"
        % (exempt["total"], plain_off["total"]))


@needs_node
def test_the_sheets_ten_percent_remodel_rate_is_recorded_and_never_charged(ran, polish):
    """The deliberate departure, asserted from both ends.

    B75 is `=IF(D6="yes",0.1,0)`. RATES.SHEET_REMODEL holds that same 10% so the Layer-1 pin above
    has something to compare Kyle's cell against — and nothing may price from it. There is a silent
    failure available in each direction:

      * the sheet's 10% creeping back in as a constant, a default or a fallback, which is the bid
        Hanz explicitly told us not to send;
      * somebody "tidying" SHEET_REMODEL to the rate we DO charge, after which the B75 pin compares
        6.5% against a cell that says 10%, fails for a reason nobody can act on, and gets loosened
        — and then a real edit to Kyle's file goes unnoticed for ever."""
    rates = ran["constants"]["rates"]
    assert "REMODEL" not in rates, (
        "RATES.REMODEL is back. The remodel rate is a per-county INPUT now, not a constant — a "
        "flat rate in RATES is exactly how the sheet's 10% gets charged again")
    assert rates["SHEET_REMODEL"] == pytest.approx(SHEET_REMODEL_RATE), (
        "SHEET_REMODEL is %r. It exists to record what Kyle's B75 says, which is %r — %s"
        % (rates["SHEET_REMODEL"], SHEET_REMODEL_RATE, FIX_SHEET_REMODEL))
    assert _rate_in(polish["B75"].value) == pytest.approx(rates["SHEET_REMODEL"]), (
        "Polish!B75 is %s and SHEET_REMODEL is %r — %s"
        % (polish["B75"].value, rates["SHEET_REMODEL"], FIX_SHEET_REMODEL))
    assert rates["KS_STATE"] == pytest.approx(KS_STATE_RATE), (
        "the fallback floor is the Kansas STATE rate, %r, and the engine ships %r"
        % (KS_STATE_RATE, rates["KS_STATE"]))
    assert rates["SHEET_REMODEL"] != rates["KS_STATE"], (
        "SHEET_REMODEL and KS_STATE have converged, so nothing here can tell the sheet's invented "
        "rate apart from the one we charge — %s" % FIX_SHEET_REMODEL)

    # And the engine, executed. The fallback is where 10% would come back if it ever did: it is the
    # branch with no county to argue with. It prices at the state floor, NOT at what B75 would say.
    fallback = _by(ran, "no county picked yet")
    assert fallback["remodel_pct"] == pytest.approx(rates["KS_STATE"])
    base = _remodel_base(fallback)
    if_the_sheet_ran_it = round_up(base * rates["SHEET_REMODEL"])
    assert if_the_sheet_ran_it - fallback["remodel_tax"] > 1, (
        "remodel on with no county charged %r and the sheet's 10%% would charge %r. Those are the "
        "same bid, so either B75's rate is being used after all or this vector's base is too small "
        "to tell the two apart" % (fallback["remodel_tax"], if_the_sheet_ran_it))
    # No vector anywhere may land on the sheet's rate, whatever its label claims.
    charged = sorted(set(v["out"]["remodel_pct"] for v in ran["vectors"]))
    assert rates["SHEET_REMODEL"] not in charged, (
        "a vector priced its remodel tax at %r, the sheet's own rate — rates in play: %r"
        % (rates["SHEET_REMODEL"], charged))


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
    # $33.00 from 2026-08-26 (Kyle: "The new epoxy/polish/sealed rate is $33/hr"). These seeds
    # stand in for the workbook's own Polish!C37 / C44, so they move with it or the beta prices a
    # polish job at a rate the spreadsheet no longer uses.
    assert [r["rate"] for r in fresh["labor"]] == [33.0, 33.0, 33.0]
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
