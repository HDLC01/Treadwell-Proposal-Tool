"""frontend/js/markup-core.js, exercised under node.

This is the engine that will read the free-text `formula` column out of backend/markup.py's
markup_rules table and price a line. Prod's CSP has no unsafe-eval, so there is no shortcut
through eval/new Function -- this is a hand-rolled tokenizer, recursive-descent parser and tree
evaluator, and every one of those layers is a place a formula can be silently mispriced instead
of visibly refused. That is the property this file is protecting:

  * **A broken formula must not price as $0.** `IF(B5="Yes",.09,.1) - IF(...)` with B5 unset
    hits the 2-arg IF's false branch, which is boolean FALSE in Excel and sums as 0 there. This
    engine refuses instead -- arithmetic on a non-numeric value throws. A markup line that
    silently drops to zero is a bid that is wrong in the customer's favor and nobody notices.
  * **IF must be lazy.** A formula referencing a cell that only exists on the taken branch
    (`IF(B5="Yes", 1/E69, 0)` when E69 is legitimately absent off that branch) must not evaluate
    the branch it didn't take.
  * **ROUNDUP must match the workbook, not the spec.** frontend/js/polish-bid-core.js's own
    roundUp() is float-guarded via toPrecision(12) specifically because naive Math.ceil(n*100)/100
    disagrees with Excel at the boundary. This engine's excelRoundUp must match it, not
    re-derive it and drift.
  * **BAND's edge is "strictly below."** GP_BANDS in polish-bid-core.js is
    [[6500,.52],[15000,.45],[22500,.35],[32500,.32],[null,.30]] and a value sitting exactly on a
    ceiling takes the NEXT band, not the one it's touching. Off-by-one here is Kyle's example of
    the mistake that goes unnoticed longest, because both bands are plausible margins.
  * **Kyle's own Gyp soft-costs cell, verbatim.** markup.py's docstring gives the real formula
    text authors will paste in:
    IF(OR(B5="Yes",B5="No"), IF(B5="Yes",.09,.1) - IF(E69>334900,.05,IF(E69>234450,.035,0)),
    "error"). All three outer branches -- Yes, No, and the "error" sentinel for anything else --
    have to come out right, string literal and all.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "markup-core.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                 reason="node is not installed")

# Kyle's own Gyp soft-costs cell (markup.py's docstring), reproduced verbatim -- not
# paraphrased -- so a change to how string literals or nested IFs are handled shows up here.
GYP_SOFT_COSTS = (
    'IF(OR(B5="Yes",B5="No"), IF(B5="Yes",.09,.1) - '
    'IF(E69>334900,.05,IF(E69>234450,.035,0)), "error")'
)

# frontend/js/polish-bid-core.js RATES/GP_BANDS, restated here as the ground truth the engine's
# BAND/MARKUP/ROUNDUP built-ins must reproduce.
GP_BANDS = [[6500, .52], [15000, .45], [22500, .35], [32500, .32], [None, .30]]


def band_formula(value_expr):
    pairs = "".join(
        ("%s,%s," % (c, r)) for c, r in GP_BANDS[:-1]
    )
    default_rate = GP_BANDS[-1][1]
    return "BAND(%s,%s%s)" % (value_expr, pairs, default_rate)


def run(script: str):
    """Run `script` with `M` bound to the module; returns its printed JSON."""
    prelude = (
        "const M = require(%s);\n"
        "const out = (v) => console.log(JSON.stringify(v === undefined ? '<undefined>' : v));\n"
        "const threw = (fn) => { try { fn(); return null; } "
        "catch (e) { return e.message; } };\n"
        % json.dumps(str(CORE))
    )
    proc = subprocess.run(["node", "-e", prelude + script],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_module_loads():
    """A syntax error would make every test below fail with the same opaque message."""
    assert run("out(typeof M.run)") == "function"


# ── arithmetic and precedence ──────────────────────────────────────────
def test_operator_precedence_and_parens():
    assert run('out(M.run("2+3*4"))') == 14
    assert run('out(M.run("(2+3)*4"))') == 20
    assert run('out(M.run("-5+3"))') == -2
    assert run('out(M.run("10/2/5"))') == 1


def test_percent_literal():
    assert run('out(M.run("50%"))') == 0.5
    assert run('out(M.run("50%*200"))') == 100


def test_division_by_zero_throws():
    assert "division by zero" in run('out(threw(() => M.run("1/0")))')


# ── comparisons and string literals ─────────────────────────────────────
def test_numeric_comparisons():
    assert run('out(M.run("3>2"))') is True
    assert run('out(M.run("3<2"))') is False
    assert run('out(M.run("3<>2"))') is True
    assert run('out(M.run("3<=3"))') is True
    assert run('out(M.run("3>=4"))') is False


def test_string_equality_is_case_insensitive():
    """Excel comparisons are case-insensitive, and that is what makes B5="Yes" match a cell
    someone typed as "yes"."""
    assert run('out(M.run(\'"Yes"="yes"\'))') is True
    assert run('out(M.run(\'"Yes"<>"no"\'))') is True


def test_cell_ref_identifiers_are_case_insensitive_lookups():
    assert run('out(M.run("B5", {B5: 42}))') == 42
    assert run('out(M.run("b5", {B5: 42}))') == 42
    assert "unresolved name" in run('out(threw(() => M.run("Z9", {})))')


# ── IF laziness and the no-silent-zero safety property ──────────────────
def test_if_only_evaluates_the_taken_branch():
    """A cell reference that would throw on the branch NOT taken must never be touched."""
    assert run('out(M.run(\'IF(1>0, 5, 1/UNSET_CELL)\'))') == 5
    assert run('out(M.run(\'IF(1<0, 1/UNSET_CELL, 7)\'))') == 7


def test_two_arg_if_false_branch_cannot_be_summed():
    """THE COUNTEREXAMPLE this file exists for. Excel's 2-arg IF returns boolean FALSE on a
    failed condition and sums a bare FALSE as 0 -- so a markup line guarded by a condition that
    happens to be false would silently price as $0 in Excel. This engine refuses instead: the
    positive case (a 3-arg IF, or a true condition) must still price normally, and only the
    bare-FALSE case must throw, or this test would pass vacuously either way.

    Mutation: make requireNumber coerce non-numeric truthy/falsy values to 0 instead of
    throwing."""
    assert run('out(M.run(\'IF(1>0,5,0)+1\'))') == 6, "the normal path must still work"
    assert run('out(threw(() => M.run(\'IF(1<0,5)+1\')))') is not None, (
        "a bare 2-arg IF false-branch must not be summable")


def test_arithmetic_on_a_string_throws_rather_than_coercing():
    assert run('out(threw(() => M.run(\'1+"x"\')))') is not None
    assert run('out(M.run("1+2"))') == 3, "a real number pair must still add normally"


# ── boolean built-ins ────────────────────────────────────────────────────
def test_or_and_not():
    assert run('out(M.run(\'OR("No"="Yes","No"="No")\'))') is True
    assert run('out(M.run(\'AND("No"="Yes","No"="No")\'))') is False
    assert run('out(M.run("NOT(1>2)"))') is True


def test_min_max():
    assert run('out(M.run("MIN(4,1,9)"))') == 1
    assert run('out(M.run("MAX(4,1,9)"))') == 9


# ── ROUNDUP must match polish-bid-core.js's roundUp() ────────────────────
def test_roundup_matches_excel_away_from_zero():
    assert run('out(M.run("ROUNDUP(2.001)"))') == 3
    assert run('out(M.run("ROUNDUP(2)"))') == 2
    assert run('out(M.run("ROUNDUP(-2.001)"))') == -3, "away from zero, not toward positive infinity"


def test_roundup_is_float_guarded_like_the_workbook():
    """2875/275*11 lands on 11 exactly in real arithmetic but not in float -- this is the exact
    class of noise toPrecision(12) exists to absorb in polish-bid-core.js's roundUp()."""
    assert run('out(M.run("ROUNDUP(2875/275,0)"))') == 11


# ── BAND must match GP_BANDS's strictly-below semantics exactly ─────────
def test_band_is_strictly_below_not_at_or_below():
    """A value sitting exactly on a ceiling takes the NEXT band -- the off-by-one Kyle called out
    as the mistake most likely to go unnoticed, since both adjacent rates are plausible."""
    formula = band_formula("V")
    assert run('out(M.run(%s, {V: 6499}))' % json.dumps(formula)) == pytest.approx(.52)
    assert run('out(M.run(%s, {V: 6500}))' % json.dumps(formula)) == pytest.approx(.45), (
        "sitting exactly on the 6500 ceiling must take the .45 band, not .52")
    assert run('out(M.run(%s, {V: 999999}))' % json.dumps(formula)) == pytest.approx(.30), (
        "past every ceiling falls through to the trailing default rate")


# ── MARKUP must match D67's divide-up-then-subtract shape ───────────────
def test_markup_matches_d67_gp_shape():
    """D67 = ROUNDUP(SUM(...)/(1-B67),0) - ROUNDUP(SUM(...),0). MARKUP(rate) takes `base` from
    context as that running sum."""
    assert run('out(M.run("MARKUP(0.52)", {base: 6000}))') == 6500

    # hand-checked against the formula directly, for a base that is not a round number
    import math
    base = 6172.34
    rate = 0.45
    expected = math.ceil(round(base / (1 - rate), 9)) - math.ceil(round(base, 9))
    got = run('out(M.run("MARKUP(%s)", {base: %s}))' % (rate, base))
    assert got == expected


def test_markup_refuses_a_rate_at_or_above_100_percent():
    assert run('out(threw(() => M.run("MARKUP(1)", {base: 100})))') is not None


# ── Kyle's own Gyp soft-costs formula, verbatim, all three branches ──────
def test_gyp_soft_costs_yes_branch():
    got = run('out(M.run(%s, {B5: "Yes", E69: 400000}))' % json.dumps(GYP_SOFT_COSTS))
    assert got == pytest.approx(0.09 - 0.05)


def test_gyp_soft_costs_no_branch_mid_band():
    got = run('out(M.run(%s, {B5: "No", E69: 250000}))' % json.dumps(GYP_SOFT_COSTS))
    assert got == pytest.approx(0.1 - 0.035)


def test_gyp_soft_costs_no_branch_below_both_thresholds():
    got = run('out(M.run(%s, {B5: "No", E69: 100000}))' % json.dumps(GYP_SOFT_COSTS))
    assert got == pytest.approx(0.1 - 0)


def test_gyp_soft_costs_neither_yes_nor_no_hits_the_error_sentinel():
    """Kyle's own refuse-to-price-rather-than-guess branch. This is a STRING, not a thrown
    error -- the formula author chose to make "error" a value the caller has to check for."""
    got = run('out(M.run(%s, {B5: "Maybe", E69: 100000}))' % json.dumps(GYP_SOFT_COSTS))
    assert got == "error"


# ── validate() never throws, and parse errors name the position ─────────
def test_validate_ok():
    assert run('out(M.validate("1+2*3"))') == {"ok": True}


def test_validate_reports_unterminated_string():
    result = run('out(M.validate(\'IF(B5="Yes,1,0)\'))')
    assert result["ok"] is False
    assert "unterminated" in result["error"]


def test_validate_reports_unbalanced_parens():
    result = run('out(M.validate("IF(1>0,5,0"))')
    assert result["ok"] is False


def test_validate_reports_unknown_trailing_garbage():
    result = run('out(M.validate("1+2 3"))')
    assert result["ok"] is False


def test_empty_formula_is_invalid():
    assert run('out(M.validate(""))')["ok"] is False
    assert run('out(M.validate("   "))')["ok"] is False
