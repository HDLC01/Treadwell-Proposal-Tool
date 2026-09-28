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
  * **The two tax bases swapped.** Sales tax is on MATERIALS only; the remodel tax is on the
    labor side plus the markups and never on materials. Both bases are exercised with real
    material and real labor on the job, so swapping them moves the total instead of cancelling.
  * **The remodel tax charged at the sheet's 10%.** B75 hardcodes a rate that exists nowhere in
    Kansas law. The engine charges the county's real one instead — the state 6.5% plus the county
    portion, 7.975% in Johnson County, handed in as `remodel_rate` — and keeps the sheet's figure
    in `RATES.SHEET_REMODEL` purely so Layer 1 can still pin B75. Both halves are asserted here:
    that the pin holds, and that nothing prices from it. This is the ONE cell where the two files
    are meant to disagree, so it is the one place drift could hide behind "that's deliberate".
  * **A missing county rate confused with a zero one.** Absent/null/"" is "nobody has picked a
    county" and falls back to the Kansas state 6.5%; an explicit 0 is a KNOWN rate of nothing,
    because Missouri taxes remodel labor as exempt. Flatten the two through `num()` and every
    Missouri remodel is charged a Kansas tax on a screen that looks completely normal.
  * **`SUM(D64:D68)` read as five live rows.** D65 is empty and D66 holds the TEXT "Totals".
  * **Rounding once at the end.** The sheet rounds up at every step and the difference compounds
    through GP, super/PTO, soft costs and the remodel tax.
  * **A ten-hour day.** D37 multiplies by `IF($E$35="8 hour days",8,10)`. Kyle's own screenshot —
    3 guys x 5 days x $32.20 = $3,864 — is what pins the 8.

Hard bid was a SECOND cell the engine deliberately departs from, alongside B75/remodel-tax,
since 2026-09-22: Hanz, "remove all hard bids from the polish intake form. And also on the
markups" — Polish beta scope, controls and stored rules both. B68's formula is still pinned
below because it is still what Kyle's real workbook says; nothing in this engine transcribes it
any more, so there is no Layer 2 to compare it against.

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
    # labor: guys x days x hourly rate x hours-per-day
    "D37": '=(A37*B37*C37)*IF($E$35="8 hour days",8,10)',
    "E35": "8 hour days",
    # materials
    "D31": "=ROUNDUP(SUM(D17:D30),0)",
    "B32": 0.02,
    "D32": "=ROUNDUP(D31*B32,0)",
    "D33": "=SUM(D31:D32)",
    # labor, escalated and burdened
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
    # the hard-bid give-back, negative, with an else-less inner IF -- still real in Kyle's
    # workbook, and pinned here for that reason alone. Nothing in the beta engine reads it since
    # 2026-09-22 (Hanz: remove hard bid from the Polish beta, controls and rules both), which
    # makes this the second cell -- alongside B75 -- the engine deliberately does not transcribe.
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
    # dye (row 25) and joint filler (row 29), added 2026-09-18 -- Hanz: "die and joint
    # filler are supposed to be materials not something that is default". Transcribed into
    # polish-bid-core.js's dyeCost/jointFillerCost.
    "B25": '=IF(E25="Yes",E18)',
    "C25": 0.14,
    "D25": "=B25*C25",
    "B29": '=ROUNDUP(IF(E29="yes",(E18/3500),0),0)',
    "C29": 500,
    "D29": "=B29*C29",
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
    assert len(ran["vectors"]) >= 27, "the vector list has shrunk"
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
def test_the_dye_and_joint_filler_rates_come_from_the_cells_that_hold_them(ran, polish):
    """C25 (Dye, $/SF) and C29 (Joint Filler, $/kit) are hardcoded constants on the sheet,
    exactly like B32/C47/B69/B70/B78 above -- the same drift check, not a special case."""
    rates = ran["constants"]["rates"]
    for addr, key in [("C25", "DYE_PER_SF"), ("C29", "JOINT_FILLER_KIT_COST")]:
        assert float(polish[addr].value) == pytest.approx(rates[key]), (
            "Polish!%s is %r but RATES.%s is %r — %s"
            % (addr, polish[addr].value, key, rates[key], FIX_BOTH))


def _dye_cost(area, on):
    """B25 `=IF(E25="Yes",E18)`, C25 `0.14`, D25 `=B25*C25`. 0 when off or the area is not a
    positive number -- Excel's IF with no ELSE (E25 not "Yes") returns FALSE, which multiplies
    as 0 rather than raising, so the 0-guard here is not inventing a rule the sheet lacks."""
    a = _num(area)
    if not on or not (a > 0):
        return 0.0
    return a * 0.14


def _joint_filler_cost(area, on):
    """B29 `=ROUNDUP(IF(E29="yes",(E18/3500),0),0)`, C29 `500`, D29 `=B29*C29`."""
    a = _num(area)
    if not on or not (a > 0):
        return 0.0
    return round_up(a / 3500) * 500


@needs_node
def test_dye_and_joint_filler_price_by_the_sheets_own_formula(ran):
    """THE INVARIANT this feature is judged on: toggling either ON moves the Material total by
    EXACTLY what Kyle's formula says for that area, and toggling it OFF removes exactly that and
    nothing else. Every vector here is cross-checked against the REAL dyeCost/jointFillerCost run
    under node (ran["dyeJointFiller"]), so a JS-side typo in the rate or the rounding cannot hide
    behind a Python re-derivation that happens to make the same mistake.

    Mutations this proves red: RATES.DYE_PER_SF or RATES.JOINT_FILLER_KIT_COST off by a cent or a
    dollar; a bare Math.ceil in place of roundUp (would move on_3500 and on_7000, which sit
    exactly on the kit boundary); the ON check inverted or dropped; the area-positivity guard
    dropped (turns a null/undefined area into NaN, or a negative area into a negative price)."""
    d = ran["dyeJointFiller"]["dye"]
    j = ran["dyeJointFiller"]["jointFiller"]

    dye_vectors = [
        ("on_3500", 3500, True), ("on_12500", 12500, True), ("on_0", 0, True),
        ("on_null", None, True), ("on_undefined", None, True), ("off_3500", 3500, False),
    ]
    for key, area, on in dye_vectors:
        want = _dye_cost(area, on)
        assert d[key] == pytest.approx(want), (
            "dyeCost(%r, %r) is %r in JS, %r in Python — %s"
            % (area, on, d[key], want, FIX_BOTH))

    jf_vectors = [
        ("on_3500", 3500, True), ("on_3501", 3501, True), ("on_7000", 7000, True),
        ("on_0", 0, True), ("on_null", None, True), ("on_undefined", None, True),
        ("off_3500", 3500, False), ("off_7000", 7000, False),
    ]
    for key, area, on in jf_vectors:
        want = _joint_filler_cost(area, on)
        assert j[key] == pytest.approx(want), (
            "jointFillerCost(%r, %r) is %r in JS, %r in Python — %s"
            % (area, on, j[key], want, FIX_BOTH))

    # THE SPECIFIC NUMBERS, named rather than only cross-checked above -- a wrong Python
    # re-derivation that agreed with an equally wrong JS one would pass every assertion so far.
    assert d["on_3500"] == pytest.approx(490), "3,500 SF of dye at $0.14/SF should be $490"
    assert j["on_3500"] == 500, "an area that divides evenly into 3,500 is exactly one $500 kit"
    assert j["on_3501"] == 1000, (
        "one SF over 3,500 must round UP to a second kit, not price the first alone")
    assert j["on_7000"] == 1000, (
        "7,000 SF divides evenly into exactly two kits -- float dust must not buy a third")
    assert d["on_0"] == 0 and j["on_0"] == 0, "no area prices at nothing, not a negative or NaN"
    assert d["off_3500"] == 0 and j["off_3500"] == 0, (
        "the condition being off must zero the line even where the area would otherwise price it")


@needs_node
def test_a_day_is_eight_hours_because_the_sheet_says_so(ran, polish):
    """D37 multiplies by `IF($E$35="8 hour days",8,10)`. Switch E35 to ten-hour days and every
    labor line in this tool is 20% light."""
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


# B68's gate used to be pinned here, executed against the engine's own hardBidPct(). Both the
# probe and the function are gone since 2026-09-22 -- the engine no longer transcribes B68 at
# all, so there is nothing left to run it against. The formula string itself stays pinned above,
# because it is still what Kyle's real workbook says.


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
    Kansas charges sales tax on commercial remodel LABOR at the state 6.5% plus the county portion
    only, so the engine takes the county's rate as an input and this mirrors that rule instead.
    Nothing here resolves to SHEET_REMODEL_RATE, and nothing in the engine does either.

    NULL IS NOT ZERO, and `_num` would flatten the two. Absent / None / "" is "no county picked
    yet" and stands the state rate up until one is; an explicit 0 is a KNOWN rate of nothing —
    Missouri taxes remodel labor as exempt — and must be charged as nothing. Reading that 0 as
    "unknown" would put a Kansas tax on every Missouri remodel."""
    if not cond.get("remodel_tax"):
        return 0.0
    given = inp.get("remodel_rate")
    if given is None or given == "":
        return KS_STATE_RATE
    return _num(given)


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
    # B68/D68, the hard-bid give-back, is not transcribed here at all -- removed 2026-09-22
    # alongside the engine's own hardBidPct(). D69/D70's SUM(D64:D68) reduces to D64+D67+D68 in
    # Kyle's sheet, and with D68 out of this reckoning it is D64+D67 on this side of the mirror.
    contingency = _num(inp.get("contingency"))                                  # D71

    # D69/D70: SUM(D64:D68) is D64+D67 here — D65 empty, D66 the text "Totals", D68 not charged.
    super_pto = round_up((sub_total + gp + contingency + sales_tax + fees) * 0.027)
    soft_costs = round_up(
        (sub_total + gp + super_pto + contingency + sales_tax + fees) * 0.16)

    remodel_pct = _remodel_pct(inp, cond)                                       # B75, the county's
    remodel_tax = round_up(                                                     # D75
        (labor + escalation + burden + gp + super_pto + soft_costs + contingency + fees)
        * remodel_pct)
    taxes = sales_tax + remodel_tax                                             # D76

    bond_pct = 0.0                                                              # B78
    bond = round_up((sub_total + gp + super_pto + soft_costs + contingency                        # D78
                     + sales_tax + remodel_tax + taxes + fees) * bond_pct)
    fees_and_bond = round_up(fees + bond)                                       # D79

    total = (sub_total + gp + super_pto + soft_costs                            # D82
             + contingency + taxes + fees_and_bond)

    return {
        "material": material, "shipping": shipping, "material_total": material_total,
        "labor": labor, "escalation": escalation, "burden": burden, "labor_total": labor_total,
        "sub_total": sub_total,
        "gp_pct": gp_pct, "gp": gp,
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
    """D75's base: `SUM(D45:D47,D55,D61,D67:D71,D77)` — the labor side and every markup. D33 is
    deliberately absent; D55 (tooling) and D61 (travel) are zero in the beta. Note the base does
    not depend on the RATE, which is what lets these tests re-price it at a different one."""
    return (out["labor"] + out["escalation"] + out["burden"] + out["gp"]
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
def test_sales_tax_is_charged_on_materials_only(ran):
    """D74 takes D33, not the sub-total. Taxing the whole cost would add ~9.5% of the LABOR to
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
    """D75 sums D45:D47 and D67:D71 — the labor side and the markups. D33 is deliberately absent.

    This is a test about the BASE, so it is re-expressed against whatever rate its vector actually
    prices at rather than a hardcoded one. The vector carries $12,000 of material and a real,
    non-zero county rate, so a base that wrongly included D33 answers a DIFFERENT number — the two
    cannot agree by cancellation, which is the only thing that makes a base test worth running."""
    on = _by(ran, "on labor + markups, never on materials")
    off = _by(ran, "not a remodel: no remodel-tax line")
    assert off["remodel_tax"] == 0 and off["remodel_pct"] == 0
    rate = on["remodel_pct"]
    assert rate == pytest.approx(0.07975), (
        "this vector is meant to price at Johnson County's 7.975%% and priced at %r — the base "
        "check below only means something at a real, non-zero rate" % rate)

    base = _remodel_base(on)
    assert on["remodel_tax"] == round_up(base * rate), (
        "D75 came out %r; the labor side plus the markups at %r is %r"
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
    taxes remodel LABOR as exempt, so a Missouri county carries no remodel rate on purpose and the
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
        "a county rate of exactly 0 is Missouri's exempt labor, and it resolved to %r — a 0 read "
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
def test_prevailing_wage_escalates_labor_and_the_burden_follows(ran):
    """C46 is 5% of labor, and D47 burdens labor PLUS the escalation — so prevailing wage moves
    two lines, not one."""
    on = _by(ran, "prevailing wage: 5% escalation")
    off = _by(ran, "no prevailing wage")
    assert off["escalation"] == 0
    assert on["escalation"] == round_up(on["labor"] * 0.05)
    assert on["burden"] == round_up((on["labor"] + on["escalation"]) * 0.12)
    assert on["burden"] > off["burden"], "the burden is being taken on bare labor"
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


# ── the labor rows ───────────────────────────────────────────────────────────
@needs_node
def test_a_labor_row_is_guys_times_days_times_rate_times_eight(ran):
    for l in ran["labor"]:
        want = _num(l["row"].get("guys")) * _num(l["row"].get("days")) * _num(l["row"].get("rate")) * 8
        assert round(l["cost"], 6) == round(want, 6), l["label"]
    empty = [l for l in ran["labor"] if "empty row" in l["label"]][0]
    assert empty["cost"] == 0, "an empty row must cost nothing, not NaN"
    no_days = [l for l in ran["labor"] if "no days yet" in l["label"]][0]
    assert no_days["cost"] == 0


@needs_node
def test_the_labor_total_is_left_unrounded_for_d45_to_round(ran):
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
    areas survive as measurements waiting for an assembly, the labor comes across with `crew`
    read as the GUYS COUNT — reading it as money would multiply a saved estimate by eight — and
    the six replaced keys are dropped rather than half-carried."""
    m = [x for x in ran["migrations"] if "v1 draft" in x["label"]][0]
    before, after = m["before"], m["after"]
    assert after["version"] == 2
    assert [r["measurement"] for r in after["takeoff"]] == [9000, 3500], "the areas are the takeoff"
    assert all(r["unit"] == "SF" for r in after["takeoff"])
    assert all(r["assembly_id"] == "" for r in after["takeoff"]), (
        "v1 had no assemblies, so inventing an id would point at nothing")
    assert [r["guys"] for r in after["labor"]] == [4, 2, 2, ""], "crew is the guys count"
    assert [r["id"] for r in after["labor"]] == ["polishing", "mockup", "jointfill", "travel"]
    assert [r["days"] for r in after["labor"]] == [6, 1, 2, ""]
    # Every condition the v1 draft stated survives untouched. `bond` is the one it could not have
    # stated — it postdates every v1 draft — so migrateModel backfills freshModel's default rather
    # than leaving the key absent for markupChain to read as undefined.
    for key, was in before["conditions"].items():
        assert after["conditions"][key] == was, (
            "migration changed the v1 draft's %r: %r -> %r" % (key, was, after["conditions"][key]))
    # FOUR keys a v1 draft could not have stated, not one. `bond` postdates every v1 draft; dye,
    # joint_filler and remove_existing_jf arrived on 2026-09-16 when they moved off the intake
    # form and into the model -- before that they lived in a separate `carry` object on
    # polish-intake.js, deliberately outside what the engine is handed.
    #
    # THE BACKFILL IS WHAT MATTERS, NOT THE COUNT. markupChain reads these keys; a draft that
    # simply lacked them would hand it `undefined`, which is falsy and so silently answers "No" to
    # a question nobody asked. an absent key would flip a real workbook cell the wrong
    # way on every draft written before today, whichever way the literal points.
    assert (set(after["conditions"]) - set(before["conditions"])
            == {"bond", "dye", "joint_filler", "remove_existing_jf"})
    assert after["conditions"]["bond"] is False
    assert after["conditions"]["joint_filler"] is False, (
        "joint filler must arrive OFF. It shipped ON until 2026-09-19 -- the way Kyle's sheet "
        "ships and the way the intake toggle defaulted -- and moved when the line started "
        "costing $500 a kit per 3,500 sq ft")
    assert after["conditions"]["dye"] is False
    assert after["conditions"]["remove_existing_jf"] is False
    assert after["contingency"] == 0
    for gone in ("system", "tooling", "materials", "added", "adds", "options"):
        assert gone not in after, "%s is replaced by assemblies and must not be carried over" % gone
    assert ran["migrationIsIdempotent"], "migrating twice reshapes the model again"


@needs_node
def test_a_stale_v2_draft_backfills_travel_without_disturbing_anything_else(ran):
    """#491 added Travel as a fourth labor row to `freshModel()`, but a sandbox already saved
    before that ships with three rows forever — `migrateModel` only ever replaced the WHOLE `labor`
    array, and only when it was missing or empty, so a non-empty three-row array passed straight
    through untouched. This is exactly what Hanz saw on "Akoya Omakase (beta test)": travel never
    appeared no matter how many times the page was reopened. The fix backfills any row id
    `freshModel()` seeds that the saved draft lacks, additively."""
    m = [x for x in ran["migrations"] if "before Travel existed" in x["label"]][0]
    before, after = m["before"], m["after"]
    assert [r["id"] for r in after["labor"]] == \
        ["polishing", "mockup", "jointfill", "u_1699999999_1", "travel"], (
        "travel is appended, not spliced in ahead of the estimator's own custom row")
    # The pre-existing rows, INCLUDING the estimator-typed 4-guy Polishing value and the hand-added
    # custom row, must come across byte-for-byte — the backfill only ever appends.
    assert after["labor"][:4] == before["labor"]
    # The new row is exactly freshModel()'s Travel seed — one definition, so the migration cannot
    # hand out a different Travel from the one a brand-new sandbox gets. $33 and `hours` are the
    # sheet's own (Polish rows 43-44); `guys` is blank here because the PAGE derives it on adopt.
    travel = after["labor"][4]
    assert travel == {"id": "travel", "label": "Travel", "guys": "", "days": "", "rate": 33,
                      "unit": "hours", "guys_auto": True}
    # Untouched elsewhere: this bug was about `labor` specifically, not a symptom of a bigger
    # migration regression.
    assert after["conditions"]["taxable"] is False and after["conditions"]["local"] is True
    assert after["contingency"] == 500
    assert ran["staleLaborBackfillIsIdempotent"], (
        "re-opening an already-backfilled draft must not push a second travel row on")


@needs_node
def test_travel_is_priced_per_hour_not_per_eight_hour_day(ran):
    """The sheet heads the crew rows `Guys | Days` over `=(A37*B37*C37)*8`, and Travel `Guys |
    HOURS` over `=(A44*B44*C44)` — no multiplier. Its middle number is already hours, so applying
    the eight-hour day would bill a two-hour drive as sixteen.

    Mutation: drop `unit` from laborCost's per-day branch. 6 × 2 × $33 becomes $3,168 instead of
    $396 — an eightfold overcharge on a line nobody reads closely, on every out-of-town bid."""
    t = ran["travelHourlyCost"]
    assert t["hoursPerDay"] == 8, "the day is still eight hours for a crew row"
    assert t["perHour"] == 6 * 2 * 33, "travel must not be multiplied by the day"
    assert t["perDay"] == 6 * 2 * 33 * 8, "a row without unit=hours is still a day row"
    assert t["perDay"] == t["perHour"] * 8


@needs_node
def test_the_travel_guys_column_is_the_man_day_sum(ran):
    """Polish A44 is `=(A37*B37)+(A38*B38)+(A40*B40)+(A42*B42)` — guys × days over the crew rows.
    So "Guys" on a travel row is not a head count, it is how many man-days are driving; the
    sheet's own screenshot shows 18 against a 3-guy crew (3×5 + 3×0.5 + 3×0.5).

    A travel row never counts itself, or turning travel on would inflate its own basis."""
    d = ran["travelManDays"]
    assert d["sheetScreenshot"] == 18, (
        "3x5 + 3x0.5 + 3x0.5 is 18 man-days, and the hours row must not count itself: %r"
        % d["sheetScreenshot"])
    assert d["blanksContributeNothing"] == 0
    assert d["empty"] == 0


@needs_node
def test_a_travel_row_with_no_hours_does_not_block_the_review_step(ran):
    """THE CARVE-OUT THAT KEEPS REVIEW REACHABLE, and the reason it is needed is the auto-fill.

    `blockers` reads a labor row as half-filled when 1 or 2 of guys/days/rate are empty, and
    ignores a row where all three are — "switched off". Travel used to qualify: it seeded fully
    blank. It no longer can. It arrives with $33 off the sheet and a Guys figure the page derives
    from the man-days, so on a bid nobody has typed a travel hour into, exactly one box is empty.
    Without the carve-out every draft in the system opens saying "Add the days for Travel",
    including the local jobs that will never drive anywhere.

    Hours is what means "we are doing this" — guys and rate are both defaults nobody chose."""
    b = ran["travelBlockers"]
    assert b["noHours"] == [], (
        "a travel row with no hours is unused, not unfinished: %r" % b["noHours"])
    assert any("Travel" in x for x in b["hoursButNoGuys"]), (
        "a travel row that IS being used is checked like any other: %r" % b["hoursButNoGuys"])
    assert any("Polishing" in x for x in b["crewRowStillChecked"]), (
        "the carve-out must not leak onto the crew rows: %r" % b["crewRowStillChecked"])


@needs_node
def test_a_draft_saved_while_travel_was_a_day_row_is_brought_forward(ran):
    """Travel shipped priced like a crew row and was corrected the same day. A sandbox opened in
    between holds `{guys: 6, days: 2, rate: ""}` with no `unit` — which bills a 2-hour drive as 16
    hours and then prices it at nothing, the rate being blank.

    Additive, like the row backfill it sits beside: the fields Travel GAINED are filled, and the
    `guys: 6` somebody typed is left exactly where it is. `guys_auto` is decided from the row
    rather than defaulted on, because nothing auto-filled that 6 — turning the auto on would
    overwrite it on the next keystroke anywhere in the panel."""
    m = [x for x in ran["migrations"] if "priced per day" in x["label"]][0]
    travel = [r for r in m["after"]["labor"] if r["id"] == "travel"][0]
    assert travel["unit"] == "hours", "the row still prices by the eight-hour day"
    assert travel["rate"] == 33, "a blank rate prices travel at nothing forever"
    assert travel["guys"] == 6, "the estimator's own figure was overwritten"
    assert travel["days"] == 2, "the estimator's own hours were overwritten"
    assert travel["guys_auto"] is False, (
        "auto would overwrite a hand-typed guys figure on the next keystroke")
    # The crew row beside it is untouched.
    pol = [r for r in m["after"]["labor"] if r["id"] == "polishing"][0]
    assert (pol["guys"], pol["days"], pol["rate"]) == (3, 5, 33)
    assert pol.get("unit") is None, "a crew row must not become an hours row"
    assert ran["travelFieldBackfillIsIdempotent"], (
        "re-opening an already-corrected draft must not rewrite its travel row again")


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
def test_the_fresh_model_carries_the_templates_own_labor_seeds(ran):
    """A37 = 3 guys, C37 = $32.20/hr, B40 = half a day for the mock-up. Days are left blank on the
    two an estimator has to judge, which is why a fresh model reports them as unfinished.

    TRAVEL IS TRANSCRIBED TOO, from Polish rows 43-44, which an earlier version of this test said
    did not exist. They do: `Travel: Guys | Hours` over `=(A44*B44*C44)` at C44 = 33. So it seeds
    at the same $33 as the crew rows, with hours blank (the one figure an estimator must judge)
    and `guys` derived rather than typed -- A44 is the man-day sum of the rows above it, which is
    what `guys_auto` marks and the page fills in."""
    fresh = ran["fresh"]
    # Travel's guys is blank in the SEED and filled by the page on adopt: freshModel is the core's
    # answer, and deriving it here would need the core to know about the page's sync.
    assert [r["guys"] for r in fresh["labor"]] == [3, 3, 3, ""]
    # $33.00 from 2026-08-26 (Kyle: "The new epoxy/polish/sealed rate is $33/hr"). These seeds
    # stand in for the workbook's own Polish!C37 / C44, so they move with it or the beta prices a
    # polish job at a rate the spreadsheet no longer uses.
    assert [r["rate"] for r in fresh["labor"]] == [33.0, 33.0, 33.0, 33.0]
    assert [r["days"] for r in fresh["labor"]] == ["", 0.5, "", ""]
    # The two fields that make Travel price per HOUR instead of per eight-hour day.
    assert [r.get("unit") for r in fresh["labor"]] == [None, None, None, "hours"]
    assert [r.get("guys_auto") for r in fresh["labor"]] == [None, None, None, True]
    # Bond joins them off, matching B78, which the sheet ships at zero. It is stored so the Review
    # step's switch has somewhere to write; markupChain() never reads it.
    # THE LAST THREE ARE NOT PRICED BY ANYTHING HERE, and that is why they are in this list rather
    # than absent from it. dye, joint_filler and remove_existing_jf moved off the intake form on
    # 2026-09-16 and into the model; markupChain() reads none of them, exactly as it reads no bond.
    # They are stored so the Takeoff step's switches have somewhere to write, and so the one shared
    # cell writer can put their Yes/No into Kyle's workbook from either screen.
    #
    # ALL THREE TAKEOFF CONDITIONS SHIP OFF since 2026-09-19. joint_filler shipped ON before
    # that, because Kyle's sheet ships Polish!E29 = "Yes" and the intake toggle followed it. That
    # stopped being a harmless transcription on 2026-09-18, when the condition started charging a
    # $500 kit per 3,500 sq ft: a 17,500 SF bid opened $2,500 higher than anybody had asked for.
    # Hanz's call is that all three start off and the estimator switches on what the job needs.
    assert fresh["conditions"] == {"local": True, "prevailing_wage": False,
                                  "taxable": True, "remodel_tax": False, "bond": False,
                                  "dye": False, "joint_filler": False,
                                  "remove_existing_jf": False}
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
        says["a labor row with guys and a rate but no days"]
    # A row at 0 days is switched off on purpose, and a wholly empty one was never started.
    # Neither is half-filled, and neither should stop a bid.
    assert says["ready to price: a switched-off labor row is not half-filled"] == []
    assert says["a model that is not a model at all"], "a broken model is not ready to price"


# ── the library's default labor lines ─────────────────────────────────────────
# Library -> Default Items & Assemblies grew a real table (public.library_labor) on 2026-09-17,
# because "+ Add a labor line" had shipped with nothing behind it. These four tests are the seam
# between that table and this model, and the third one is the one that matters: a default is a
# starting point for a bid nobody has worked on yet, and NOTHING about it may reach a bid that
# somebody has.
@needs_node
def test_a_library_labor_line_is_read_onto_the_model_by_one_mapping(ran):
    """`name` on the table, `label` on the model -- the two shapes differ and neither is renamed
    to match the other, so exactly one mapping bridges them. travelSeed's own note directly above
    it records why that mapping is stated once: the same row written out twice drifted within a
    day, and the migration's copy went on handing out the old shape after the seed had moved on.

    Mutation: change `label: r.name` to `label: r.label` in libraryLaborRow -- every default lands
    on the Labor step with a blank name, which is what a second copy of this mapping looks like
    after the column is renamed on one side."""
    lib = ran["libraryLabor"]
    assert [r["label"] for r in lib["mapped"]] == ["Densify", "Night shift premium"], (
        "the table's `name` did not become the model's `label`: %r" % lib["mapped"])
    assert [r["id"] for r in lib["mapped"]] == ["lab-densify", "lab-night"]
    assert [r["unit"] for r in lib["mapped"]] == ["days", "hours"]
    assert [r["guys_auto"] for r in lib["mapped"]] == [False, True], (
        "guys_auto did not survive as a real boolean")
    # PostgREST hands numeric back as TEXT. A rate left as a string prices correctly today (num()
    # coerces it) and then sits on the saved draft as "40.00" for the life of the bid.
    assert lib["rateType"] == "number", "the rate stayed a string off the API"
    assert [r["rate"] for r in lib["mapped"]] == [40.0, 12.5]
    # THE ESTIMATOR'S OWN BOXES START EMPTY. A default says what the line is and what it costs per
    # unit; how much of it this job needs is nobody's to guess, and a seeded quantity would be a
    # number no one chose sitting inside a customer's price.
    assert [r["guys"] for r in lib["mapped"]] == ["", ""]
    assert [r["days"] for r in lib["mapped"]] == ["", ""]


@needs_node
def test_the_defaults_stand_beside_travel_and_never_double_it(ran):
    """A default is an addition BESIDE the four rows off Kyle's own Polish tab -- never a
    substitution for one. `travel` is the single reserved exception and it is the subject of the
    test below; everything else here is the rule it is an exception to.

    Mutation: drop the `seen[rid]` guard from seedLibraryLabor's second loop, and a library row
    whose id is already on the model lands a second time."""
    lib = ran["libraryLabor"]
    assert lib["seededIds"] == ["polishing", "mockup", "jointfill", "travel",
                                "lab-densify", "lab-night"], (
        "the defaults did not land after the four built-in rows, in the server's order: %r"
        % lib["seededIds"])
    assert lib["builtInsUntouched"], "seeding rewrote one of the four built-in rows"
    assert lib["inputUntouched"], "seeding mutated the array it was handed"
    assert lib["isANewArray"], "seeding returned the same array it was handed"
    # Nothing to add, in all three shapes "nothing" arrives in -- an empty table, a read that
    # could not answer, and a row the API should never have served.
    built_in = ["polishing", "mockup", "jointfill", "travel"]
    assert lib["emptyList"] == built_in
    assert lib["missingList"] == built_in
    assert lib["rowsWithoutIds"] == built_in


@needs_node
def test_travel_is_overridden_in_place_and_never_becomes_a_second_row(ran):
    """TRAVEL IS EDITABLE FROM 2026-09-19 AND STILL CANNOT BE DUPLICATED OR LOST. Hanz, on the
    BUILT IN chip the Defaults tab drew beside it: "again this too how can we edit this?", and
    twice before that, "don't put in a hard coded or built in line items". The rate was a literal
    inside travelSeed() with no row behind it, so nothing on the page could change it.

    THE TWO FAILURE MODES THIS PINS ARE OPPOSITE ONES, which is why one test holds both:

      * A stored `travel` row SKIPPED is an edit that silently does nothing -- the admin types
        $41.50, the list shows $41.50, and every bid still prices at $33.00.
      * A stored `travel` row PUSHED BESIDE the built-in one puts two rows carrying the id
        `travel` on the estimate. migrateModel's backfill finds Travel by that exact id, so it
        would start filling fields onto whichever it reached first, and the row an admin typed a
        rate into is not the row that prices the job.

    AND THE THIRD CASE IS PRODUCTION. `library_labor` does not exist there yet; list_labor()
    answers [] and never raises, so Travel must be the sheet's own $33.00/hr row exactly as it
    was. That arm is not hypothetical -- it is the only state prod is in until the DDL runs.

    Mutation: restore the old `seen[String(r.id)]` skip for the travel arm, and the override case
    comes back as Travel/$33.00 -- the edit reaches nothing. Or push instead of overlaying, and
    `count` is 2."""
    lib = ran["libraryLabor"]
    over = lib["travelIsOverriddenInPlace"]
    assert over["count"] == 1 and over["rowCount"] == 4, (
        "the stored travel row was pushed beside the built-in one instead of onto it: %r" % over)
    assert over["label"] == "Drive time" and over["rate"] == 99, (
        "the stored travel row did not reach the model -- the Defaults tab edit prices nothing:"
        " %r" % over)
    assert over["unit"] == "days" and over["guysAuto"] is False, (
        "unit and guys_auto did not come off the stored row: %r" % over)
    # IN PLACE. Travel is the sheet's fourth labor row; re-ordering it would move the line the
    # estimator reads under Joint Filler.
    assert over["at"] == 3 and over["ids"] == ["polishing", "mockup", "jointfill", "travel"], (
        "Travel moved position when its stored row was applied: %r" % over["ids"])

    # PRODUCTION: no travel row in the library at all. The constant stands and Travel is untouched.
    none = lib["travelWithNoStoredRow"]
    assert none["count"] == 1, "Travel is not on the bid when the library has no row for it"
    assert none["label"] == "Travel" and none["rate"] == 33.0, (
        "a library with no travel row did not leave Travel on the shipped rate: %r" % none)
    assert none["unit"] == "hours" and none["guysAuto"] is True

    # THE FALLBACK ITSELF, which everything above is an override of.
    shipped = lib["shippedTravel"]
    assert shipped == {"id": "travel", "label": "Travel", "guys": "", "days": "",
                       "rate": 33.0, "unit": "hours", "guys_auto": True}, (
        "travelSeed() with no row is no longer the sheet's own row: %r" % shipped)

    # numeric(10,2) commonly arrives as TEXT off PostgREST. A rate left as a string would price
    # (num() coerces it) and then sit on the saved draft as "41.50" for the life of the bid.
    text = lib["storedTravelFromText"]
    assert text["rate"] == 41.5 and isinstance(text["rate"], float), (
        "a rate served as text did not become a number: %r" % text)
    assert text["id"] == "travel", "the id came off the payload rather than being the reserved one"

    # ZERO IS AN ANSWER. Travel written off for local work is a thing an admin can mean, and
    # reading it as blank would quietly put 33.00 back into every new bid.
    assert lib["storedTravelAtZero"]["rate"] == 0, (
        "a stored rate of zero fell back to the shipped 33.00: %r" % lib["storedTravelAtZero"])
    # …but a rate that is not a number at all falls back rather than becoming NaN on the model.
    assert lib["storedTravelWithJunkRate"]["rate"] == 33.0, (
        "an unparseable rate reached the model: %r" % lib["storedTravelWithJunkRate"])
    # A BLANK RATE IS NOT ZERO, and this is a different question from the one above rather than a
    # restatement of it. `Number("")` and `Number(null)` are both 0 and both isFinite, so a guard
    # written as `!isFinite(rate)` alone reads an empty rate as travel being FREE -- silently, on
    # every new bid, with the row still showing a line. `isBlank` is what separates "nobody filled
    # this in" from the deliberate zero asserted directly above.
    for shape in ("storedTravelWithEmptyRate", "storedTravelWithNullRate",
                  "storedTravelWithNoRateKey"):
        assert lib[shape]["rate"] == 33.0, (
            "%s priced travel at %r instead of falling back to the shipped rate"
            % (shape, lib[shape]["rate"]))
    # THE RESERVED ID IS RESERVED. Everything else here hands travelSeed a row already carrying
    # `travel`, where "use the reserved id" and "copy the row's id" cannot disagree. This is the
    # one input that separates them, and it matters because `travel` is the only handle anything
    # has on this line: migrateModel's backfill finds it by that exact string on every draft ever
    # saved, and the Defaults tab addresses its PATCH to it.
    assert lib["travelSeedIgnoresAForeignId"]["id"] == "travel", (
        "travelSeed took the id off the row (%r) -- the line stops being the one migrateModel "
        "backfills and the one the library can edit"
        % lib["travelSeedIgnoresAForeignId"]["id"])
    assert lib["travelSeedIgnoresAForeignId"]["rate"] == 44, (
        "the rest of the row stopped being read while the id was being reserved")

    # And blank TEXT falls back too: an unnamed line, or a unit the estimate has no branch for.
    blank = lib["storedTravelWithBlankText"]
    assert blank["label"] == "Travel" and blank["unit"] == "hours", (
        "a row with a blank name or unit drew an anonymous line or an unpriceable one: %r"
        % blank)
    assert blank["rate"] == 44, "the rate was lost while falling back on the text fields"

    # GUYS AND DAYS ARE THE BID'S. Editing a rate in the library has no business touching how much
    # of the line this job needs.
    q = lib["travelKeepsItsQuantities"]
    assert q["guys"] == 6 and q["days"] == 2 and q["rate"] == 44, (
        "applying the stored rate wiped the quantities on the row: %r" % q)


@needs_node
def test_both_schema_files_seed_the_travel_row_the_engine_actually_ships(ran):
    """THE ROW AND THE FALLBACK HAVE TO AGREE, and they live in three files.

    `travelSeed()` states what Travel costs when no row answers. `supabase_schema.sql` and
    `backend/staging/schema_pg.sql` each seed the row that overrides it. Nothing at runtime
    compares them: a seed of 35.00 against a fallback of 33.00 would price a bid differently on a
    database that has the DDL from one that does not, both would look right on screen, and the
    disagreement would surface as two estimators quoting different travel for the same job. This
    is the only place the three can be held together, and it is exactly the drift the note above
    travelSeed already records happening once.

    DDL LANDS TWICE HERE. Prod Supabase and the staging Postgres are different databases with
    different files; a seed added to one only is how a feature works on staging and does nothing
    on prod. So BOTH files are read and both are required to say the same thing.

    IDEMPOTENT, and that is not decoration: these files are re-run by hand. Without `on conflict
    (id) do nothing` the second run raises on the primary key, halfway through a migration.

    THE ENGINE'S SIDE IS EXECUTED, not grepped — `shippedTravel` is a real `P.travelSeed()` call
    in the harness. A regex over the literal `33.0` in the source could not tell you what the
    function returns.

    Mutation: change the rate in either .sql file, or in travelSeed(), and this names which two
    disagree."""
    shipped = ran["libraryLabor"]["shippedTravel"]
    files = {
        "backend/supabase_schema.sql": ROOT / "backend" / "supabase_schema.sql",
        "backend/staging/schema_pg.sql": ROOT / "backend" / "staging" / "schema_pg.sql",
    }
    seeds = {}
    for name, path in files.items():
        # COMMENTS STRIPPED FIRST. Both files are mostly prose -- every statement here has a
        # paragraph above it -- and without this the regex happily matches a seed somebody has
        # commented OUT. Proven: commenting the first line of the insert in supabase_schema.sql
        # left this test green while the row would never have been created on production.
        sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        m = re.search(
            r"insert into public\.library_labor\s*\(([^)]*)\)\s*values\s*\(([^)]*)\)\s*"
            r"on conflict \(id\) do nothing;", sql, re.I)
        assert m, (
            "%s does not seed the travel row with an idempotent insert. Without it the row does "
            "not exist, so the Defaults tab has nothing to address and Travel goes back to being "
            "a literal nobody can edit." % name)
        cols = [c.strip() for c in m.group(1).split(",")]
        vals = [v.strip().strip("'") for v in m.group(2).split(",")]
        seeds[name] = dict(zip(cols, vals))
        # EXACTLY ONE. A second insert for the same id is two statements of one row, which is the
        # shape this whole line of work exists to stop.
        assert len(re.findall(r"insert into public\.library_labor", sql, re.I)) == 1, (
            "%s seeds library_labor more than once" % name)

    a, bfile = list(seeds.values())
    assert a == bfile, (
        "the two schema files seed DIFFERENT travel rows, so prod and staging would price travel "
        "differently: %r vs %r" % (a, bfile))

    seed = a
    assert seed["id"] == shipped["id"], (
        "the seeded id is %r but migrateModel and seedLibraryLabor find Travel by %r — the row "
        "would be an ordinary extra labor line on every bid" % (seed["id"], shipped["id"]))
    assert seed["name"] == shipped["label"], (
        "the seeded name %r is not what travelSeed() calls the line (%r)"
        % (seed["name"], shipped["label"]))
    assert float(seed["rate"]) == shipped["rate"], (
        "the schema seeds Travel at %s and travelSeed() falls back to %s — a database with the "
        "DDL prices travel differently from one without it"
        % (seed["rate"], shipped["rate"]))
    assert seed["unit"] == shipped["unit"], (
        "the seeded unit %r is not travelSeed()'s %r, so the rate would multiply the wrong thing"
        % (seed["unit"], shipped["unit"]))
    assert (seed["guys_auto"].lower() == "true") == shipped["guys_auto"], (
        "the seeded guys_auto disagrees with travelSeed(), so Travel stops following the crew's "
        "man-days on any database that has the row")


@needs_node
def test_the_gate_on_the_defaults_only_opens_where_no_labor_was_ever_stated(ran):
    """laborUnstated is the only thing standing between an admin editing the default list and an
    estimator's finished bid, and it is asked of the SAVED BLOB rather than of a model. It has to
    be: migrateModel fills a missing `labor` in from freshModel() before it hands the model back,
    so every model has four labor rows whether or not anybody chose them.

    The v1 row is the one to read twice. A v1 draft keeps its crew under `labour`, so its `labor`
    is missing for a reason that has nothing to do with the estimator not having worked on it.

    Mutation: drop the `saved.version !== 2` line. Every v1 draft on staging then reads as
    unstated, and opening one on the calculator appends the library's defaults to crew rows its
    estimator typed months ago."""
    says = {c["label"]: c["unstated"] for c in ran["laborUnstated"]}
    assert says["nothing saved at all"] is True
    assert says["null"] is True
    assert says["a v2 model that states no labor"] is True, (
        "the model the beta intake now mints does not read as seedable, so the defaults are "
        "unreachable in the normal flow")
    assert says["a v2 model with an empty labor array"] is True
    assert says["a v2 model with labor on it"] is False
    assert says["a v1 draft, whose crew lives under `labour`"] is False, (
        "a v1 draft reads as having no labor, so the defaults would land on top of its crew rows")
    assert says["a version-less partial blob"] is False
    assert says["a string"] is True


@needs_node
def test_a_saved_bids_labor_is_never_touched_by_the_defaults(ran):
    """THE HARD CONSTRAINT. An estimator's saved labor rows are their work. A bid that has been
    worked on comes back EXACTLY as it was saved -- the same rows, the same order, the same typed
    numbers -- no matter what the default list says today.

    The fixture is a real visit's worth of work: the four built-in rows with their own numbers, and
    one library default the estimator kept and then re-rated from $40 to $55.

    NOT VACUOUS. `wouldHaveAdded` seeds that same array with that same library list and shows a row
    arriving, so the library demonstrably holds something that COULD have landed here. Without it,
    "nothing was added" would pass just as happily against an empty library and prove nothing.

    Mutation: make laborUnstated return `true` for a v2 model that states rows (drop the final
    `!saved.labor.length` clause and invert it). Every reopened bid then grows the defaults again
    on every load, and the $55 the estimator typed sits next to a $40 duplicate."""
    s = ran["savedLaborIsUntouchable"]
    assert s["unstated"] is False, "a bid with five labor rows on it read as never having stated any"
    assert s["afterMigrate"] == s["saved"], (
        "a saved bid's labor came back changed:\n saved: %r\n after: %r"
        % (s["saved"], s["afterMigrate"]))
    # The estimator's own re-rate, named rather than left to the deep compare above, because this
    # is the number a default overwriting a kept row would quietly put back.
    kept = [r for r in s["afterMigrate"] if r["id"] == "lab-densify"]
    assert len(kept) == 1 and kept[0]["rate"] == 55, (
        "the library's rate was written back over the estimator's own: %r" % kept)
    assert len(s["wouldHaveAdded"]) > len(s["saved"]), (
        "the library list holds nothing this bid is missing, so 'nothing was added' proves "
        "nothing: %r" % s["wouldHaveAdded"])
    # REQUIREMENT 3: removing a default from the library must not remove it from bids already
    # holding it. Once saved, the row is the BID's -- nothing consults the library about it again.
    assert "lab-densify" in s["survivesAnEmptyLibrary"], (
        "deleting the default took it off a bid that was already holding it: %r"
        % s["survivesAnEmptyLibrary"])
    assert len(s["survivesAnEmptyLibrary"]) == len(s["saved"])


@needs_node
def test_a_stored_condition_answer_wins_over_the_one_the_tool_ships(ran):
    """The three Takeoff conditions stopped being "built in" on 2026-09-18 (Hanz, twice:
    "don't put in a hard coded or built in line items", then "I told you to remove the built-in
    and keep and make everything editable in the takeoff"). freshModel() still states what the
    tool SHIPS; a row in `condition_defaults` is an override of ONE key, and seedConditionDefaults
    is where the two meet.

    EVERY ROW IN THE FIXTURE DISAGREES WITH THE SHIPPED ANSWER, which is what makes this
    non-vacuous: joint filler ships ON and the library says off, dye and remove-existing ship off
    and the library says on. A fixture that agreed with freshModel could not tell a merge that
    works from one that does nothing at all.

    Mutation: `return out;` immediately after the Object.assign in seedConditionDefaults. The
    Defaults tab then shows the shipped answers back whatever anybody sets, and an admin who
    switched joint filler off finds it on in the next bid."""
    c = ran["conditionDefaults"]
    assert not any(c["shipped"][k] for k in ("joint_filler", "dye", "remove_existing_jf")), (
        "freshModel no longer ships all three Takeoff conditions off, so this fixture -- which "
        "sets every one of them ON -- is no longer a counterexample to anything: %r" % c["shipped"])
    assert c["seeded"]["joint_filler"] is True, "the stored answer did not beat the shipped one"
    assert c["seeded"]["dye"] is True and c["seeded"]["remove_existing_jf"] is True
    assert c["intakeFiveUntouched"], (
        "the merge moved a condition nobody stored an answer for; only the three keys it was "
        "handed may change")
    assert c["inputUntouched"], "the merge mutated the conditions object it was handed"
    assert c["isANewObject"], "the merge returned the same object it was handed"
    # A key the model does not carry is skipped rather than added: migrateModel whitelists
    # condition keys against freshModel().conditions and DROPS every other one, so a seeded
    # stranger would look applied on screen and come back missing on the next load.
    assert c["offVocabularyIgnored"], (
        "an off-vocabulary condition was written onto the model, where migrateModel will drop it")
    # Nothing to apply, in every shape "nothing" arrives in -- an unpromoted table, a read that
    # could not answer, and a half-written row.
    assert c["emptyList"] == c["shipped"]
    assert c["missingList"] == c["shipped"]
    assert c["rowsWithoutKeys"] == c["shipped"]


@needs_node
def test_the_gate_on_the_condition_defaults_only_opens_on_a_blank_bid(ran):
    """conditionsUnstated is the only thing standing between a Defaults-tab edit and an
    estimator's saved answers, and it is STRICTER than laborUnstated on purpose.

    An empty `labor` array is a shape a real model holds and genuinely means "no rows chosen".
    `conditions` has no equivalent: migrateModel backfills every key from freshModel on the way
    out, so a saved v2 blob that omitted `conditions` was still SHOWN an answer, and its next save
    wrote that answer into Kyle's workbook through conditionCellWrites. Reading that as unstated
    would move a Yes/No literal on a bid somebody has already worked on.

    The beta intake's first save is the row to read twice. It is `{conditions: {...}}` with no
    version at all, and it carries the estimator's own intake answers -- so it must read as
    STATED, or a company-wide default would land on top of them.

    Mutation: return `true` from conditionsUnstated for anything that is not a v2 model (copy
    laborUnstated's shape). The intake's first save then reads as blank and the defaults overwrite
    the answers the estimator just gave."""
    says = {c["label"]: c["unstated"] for c in ran["conditionsUnstated"]}
    assert says["nothing saved at all"] is True
    assert says["null"] is True
    assert says["an empty blob"] is True
    assert says["a v2 model that states no conditions"] is False, (
        "a saved v2 bid read as blank; migrateModel has already shown it answers for every "
        "condition, and its next save writes them into Kyle's workbook")
    assert says["a v2 model with conditions on it"] is False
    assert says["a v1 draft, whose conditions predate these three"] is False
    assert says["the beta intake's first save: conditions and no version"] is False, (
        "the intake's own save read as blank, so a library default would land on top of the "
        "answers the estimator just gave on the intake step")
    assert says["a string"] is True


@needs_node
def test_a_saved_bids_conditions_are_never_touched_by_the_defaults(ran):
    """THE HARD CONSTRAINT, and the assertion this whole feature is judged on. Hanz, verbatim:
    changing a default must not change any estimate that already exists, because an estimator's
    saved answers are their work.

    A bid that has been worked on comes back EXACTLY as it was saved, whatever the library says
    today. joint_filler is the one that bites: it SHIPS on, so a bid where somebody deliberately
    turned it off is exactly the bid a careless default would quietly turn back on -- and the
    downloaded workbook would then say Yes in Polish!E29 with nothing on screen admitting it.

    NOT VACUOUS. `wouldHaveChanged` applies the same library rows to the same migrated model and
    shows all three answers moving, so "it came back as saved" is a fact about the gate and not
    about a fixture that happened to agree. `freshTakesThem` is the other half: a brand new bid
    DOES take the stored answers, or the feature does nothing at all and this test would pass
    against a seeder that was never wired up.

    Mutation: call seedConditionDefaults unconditionally in polish-estimate.js's init instead of
    behind `conditionDefaults`. Every reopened bid then adopts today's defaults, and the next save
    writes them over the estimator's answers in Polish!E25/E29/F29."""
    s = ran["savedConditionsAreUntouchable"]
    assert s["unstated"] is False, (
        "a bid with nine answered conditions read as never having stated one")
    assert s["afterMigrate"] == s["saved"], (
        "a saved bid's conditions came back changed:\n saved: %r\n after: %r"
        % (s["saved"], s["afterMigrate"]))
    # Named rather than left to the deep compare above, because these three are the ones the
    # Defaults tab can move and the ones whose literals reach Kyle's workbook.
    assert s["afterMigrate"]["joint_filler"] is False
    assert s["afterMigrate"]["dye"] is False
    assert s["afterMigrate"]["remove_existing_jf"] is False
    moved = [k for k in ("joint_filler", "dye", "remove_existing_jf")
             if s["wouldHaveChanged"][k] != s["saved"][k]]
    assert len(moved) == 3, (
        "the library's answers agree with this bid's, so 'it came back unchanged' proves "
        "nothing -- only %r would have moved" % moved)
    took = [k for k in ("joint_filler", "dye", "remove_existing_jf")
            if s["freshTakesThem"][k] != ran["conditionDefaults"]["shipped"][k]]
    assert len(took) == 3, (
        "a brand new bid does not take the stored answers either, so nothing is being gated: %r"
        % s["freshTakesThem"])
    assert s["migrationIsIdempotent"], "migrating twice reshapes the conditions again"
