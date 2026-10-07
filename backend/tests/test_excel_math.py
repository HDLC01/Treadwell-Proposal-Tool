"""js/excel-math.js: the number helpers Phase 5 moved out of the model, EXECUTED.

WHAT MOVED. `num`, `copyInto`, `roundUp`, `money`, `money2`, `pct`, `fmtSf` and `isBlank` sat at the top
of the model module (js/bid-model.js, which was then still named for Polish alone). The markup engine Phase 8 adds
needs the same ones, so they live in one leaf that depends on nothing, and the model binds them to the
names it always used and exports them again, so `B.roundUp` and the rest still work. `ceiling` is the
one NEW function (Excel's CEILING, the workbook engine's own arithmetic) and has no caller until the
Epoxy tab needs it: 78 of that tab's formulas are CEILING.

WHAT THIS FILE HOLDS, none of it a comment:

  * the helpers do what Excel (and the bid) say, on inputs written out here by hand. The expected
    answers are NOT computed by a second copy of the formulas. The polish chain golden and the
    saved-bid ratchet already prove no price moved; this proves the leaf is right on its own;
  * the model's `roundUp` (and the six others it exported before) IS the leaf's function, not a copy, and
    the model defines none of the eight itself. Two copies of ROUNDUP is the defect that cost a dollar on
    a bid once: PR 451, and the reason test_roundup_parity_js.py exists;
  * the Item Library's pack count (a CEIL with the same twelve-figure guard, written inline in
    library-core.js) is `ceiling(n, 1)` exactly. library-core.js keeps its own line on purpose: it is
    dependency-free and loads standalone in other tests, and one line is cheaper than a dependency. The
    price of that is a pair that must not drift, so a grid of over a thousand real pack counts holds
    them equal, and the grid is checked to contain cases where a bare ceil would say something else;
  * loaded as a script tag loads it (no `require`), the leaf stands alone and publishes one global; the
    model without it throws an error that names the file; the model after it loads.

EVERY CHECK CAN FAIL. The last table breaks a scratch copy of one line of one file for each check
(`break_source` refuses an anchor that is not in the file exactly once, so none can apply nowhere) and
requires that check, and no other test of the table's choosing, to go red. A final test requires that no
check is missing from the table.

Run under node; a missing node FAILS under CI (tests/_node.py).
"""
from __future__ import annotations

import pathlib
import re

import pytest

from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "excel-math-harness.js"
BOOT = TESTS / "js" / "core-boot-harness.js"

MOVED = ["num", "copyInto", "roundUp", "money", "money2", "pct", "fmtSf", "isBlank"]
RE_EXPORTED = ["num", "roundUp", "copyInto", "money", "money2", "pct", "fmtSf"]   # what the model exported before
LEAF_EXPORTS = MOVED + ["ceiling"]

# Everything below is what Excel, or the bid's own rule, says. Written by hand.
EXPECTED_NUM = {
    "12,500": 12500, "$1,200": 1200, " 12,500 ": 12500, "$1,200.50": 1200.5,
    "empty text": 0, "null": 0, "undefined": 0, "NaN": 0, "Infinity": 0, "-Infinity": 0,
    "abc": 0, "12abc": 0, "1e3": 0, "true": 0, "false": 0,
    "-5": -5, ".5": 0.5, "5.": 0, "0x10": 0, "zero": 0, "one": 1, "half": 0.5,
}
EXPECTED_ROUNDUP = {
    "27,500 x 1.10 (dust)": 110,          # 110.00000000000001 is 110: a bare ceil would buy a dollar
    "724 sf with dye (dust)": 362,
    "a real fraction": 221,               # 220.22 is really above 220
    "hard-bid give-back": -1235,          # away from zero: -1,234.2 becomes -1,235, a bigger give-back
    "PR 450's case": -857,
    "zero": 0, "text with a comma": 1235, "null": 0,
    "one cent over a dollar": 2,
}
EXPECTED_CEILING = {
    "7 to 5": 10, "10 to 5": 10, "0 to 5": 0, "4.2 to 0.5": 4.5, "2.5 to 1": 3,
    "2.5, significance left out": 3, "2.5, significance null": 3,
    "dust over 1": 110,                   # not 111
    "-2.5 to 2": -2,                      # Excel: a negative number rounds toward zero here
    "1234.1 to 100": 1300,
    "significance 0": 0,                  # Excel returns 0, not an error
    "text with a dollar sign": 1201, "null number": 0, "undefined number": 0, "text that is no number": 0,
    "0.234 to 0.01": 0.24,
    "0.07 to 0.01 (quotient dust)": 7 * 0.01,                # seven cents, not eight
    "0.27 to 0.09 (quotient dust)": 3 * 0.09,                # three steps of 0.09, not four
    "three steps of 0.1 (value and quotient dust)": 3 * 0.1,
}
EXPECTED_BLANK = {
    "null": True, "undefined": True, "empty text": True, "spaces": True, "tab and newline": True,
    "zero": False, "the text 0": False, "false": False, "an empty array": False, "a letter": False,
    "a space then a letter": False,
}
EXPECTED_COPY_INTO = {
    "returnsDestination": True, "keys": ["keep", "label", "n"], "label": "Polish", "zeroKept": True,
    "prototypeUntouched": True, "nothingPolluted": True, "constructorIsStillObject": True,
    "nullSource": ["a"], "undefinedSource": ["a"], "laterKeyWins": 3,
}
EXPECTED_TEXT = {
    "money": ["$15,681", "$0", "-$1,500", "$0", "$1,235", "$1,200", "$0"],
    "money2": ["$32.20", "$0.00", "$0.00", "-$4.50", "$1,234.50", "$0.00"],
    "pct": ["45%", "-2.5%", "9.475%", "2.7%", "0%", "100%", "0%"],
    "fmtSf": ["12,500", "1,234.57", "0", "12,500", "0"],
}


# ── the checks: each returns what is wrong, and [] when nothing is ───────────────────────────────
def _diff(section, got, want):
    return ["%s[%s] was %r, the rule says %r" % (section, k, got.get(k), v) for k, v in want.items() if got.get(k) != v]


def check_surface(r):
    got = r["exports"]
    return (["the leaf lacks %s" % n for n in LEAF_EXPORTS if n not in got] +
            ["the leaf exports %s as a %s: it holds functions only, no rate and no table" % (k, t)
             for k, t in got.items() if t != "function"])


def check_same_function(r):
    same = r["sameFunction"]
    return ["the model's %s is not the leaf's function (a second copy, or gone)" % k
            for k in RE_EXPORTED if not same.get(k)]


def check_num(r):
    return _diff("num", r["num"], EXPECTED_NUM)


def check_round_up(r):
    return _diff("roundUp", r["roundUp"], EXPECTED_ROUNDUP)


def check_ceiling(r):
    return _diff("ceiling", r["ceiling"], EXPECTED_CEILING)


def check_is_blank(r):
    return _diff("isBlank", r["isBlank"], EXPECTED_BLANK)


def check_copy_into(r):
    return _diff("copyInto", r["copyInto"], EXPECTED_COPY_INTO)


def check_text(r):
    return ["%s was %r, the rule says %r" % (fn, r["text"][fn], want)
            for fn, want in EXPECTED_TEXT.items() if r["text"][fn] != want]


def check_pack_count(r):
    p = r["packCount"]
    problems = []
    if p["disagreeCount"]:
        problems.append("%d of %d pack counts differ from ceiling(needed / pack, 1), first: %r" % (
            p["disagreeCount"], p["total"], p["disagree"]))
    if p["total"] < 1000:
        problems.append("the grid shrank to %d pack counts" % p["total"])
    if p["bites"] < 10:
        problems.append("only %d cases have a float-dust edge: the grid would pass against an unguarded ceil" % p["bites"])
    return problems


CHECKS = {
    "surface": check_surface, "same function": check_same_function, "num": check_num,
    "roundUp": check_round_up, "ceiling": check_ceiling, "isBlank": check_is_blank,
    "copyInto": check_copy_into, "text": check_text, "pack count": check_pack_count,
}


def _run(frontend):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return _run(FRONTEND)


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_the_leaf_does_what_excel_and_the_bid_say(ran, name):
    problems = CHECKS[name](ran)
    assert problems == [], "\n".join(problems)


# ── the model defines none of the moved helpers itself ───────────────────────────────────────────
def model_owns_a_helper_itself(source: str):
    """What the model's source does wrong about the helpers the leaf owns: defines one, or fails to
    bind one to the leaf's. [] when it only binds them."""
    problems = []
    for name in MOVED:
        if re.search(r"^[ \t]*function[ \t]+%s[ \t]*\(" % re.escape(name), source, re.M):
            problems.append("defines function %s itself" % name)
        if "%s = deps.math.%s" % (name, name) not in source:
            problems.append("does not bind %s to the leaf's deps.math.%s" % (name, name))
    return problems


def test_the_model_defines_none_of_the_moved_helpers_and_binds_all_eight_to_the_leaf():
    source = (FRONTEND / "js" / "bid-model.js").read_text(encoding="utf-8")
    assert model_owns_a_helper_itself(source) == []


def test_the_source_check_sees_a_definition_and_a_missing_binding():
    bound = "\n".join("  var %s = deps.math.%s;" % (n, n) for n in MOVED)
    assert model_owns_a_helper_itself(bound) == []
    assert model_owns_a_helper_itself(bound + "\n  function roundUp(n) { return 1; }\n") == [
        "defines function roundUp itself"]
    unbound = bound.replace("var pct = deps.math.pct;", "var pct = function (n) { return n; };")
    assert model_owns_a_helper_itself(unbound) == ["does not bind pct to the leaf's deps.math.pct"]
    assert model_owns_a_helper_itself("  function money2 (n) {}\n  function fmtSf(n) {}") != []


# ── loaded the way a page loads it ───────────────────────────────────────────────────────────────
def _boot(*scripts):
    require_node()
    proc = run_node(BOOT, FRONTEND, *scripts)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)["scripts"]


def test_the_leaf_loads_alone_as_a_script_tag_and_publishes_one_global():
    (leaf,) = _boot("js/excel-math.js")
    assert leaf["threw"] is None, leaf["threw"]
    assert leaf["published"] == ["TWExcelMath"]
    assert leaf["members"]["TWExcelMath"] == sorted(LEAF_EXPORTS)


def test_the_model_without_the_leaf_throws_an_error_that_names_the_file():
    (model,) = _boot("js/bid-model.js")
    assert model["published"] == [], "a model that threw must not leave a half-built global behind"
    assert model["threw"] == "bid-model.js needs excel-math.js loaded before it", model["threw"]


def test_the_model_loads_after_the_leaf_and_not_before_it():
    # The model needs two leaves since Phase 7 (this one and js/work-types.js), so a page loads both first.
    leaf, types, model = _boot("js/excel-math.js", "js/work-types.js", "js/bid-model.js")
    assert leaf["threw"] is None and types["threw"] is None and model["threw"] is None, (leaf, types, model)
    assert model["published"] == ["TWBidModel"]
    assert {"markupChain", "roundUp", "num", "money", "pct", "copyInto"} <= set(model["members"]["TWBidModel"])
    early_model, late_leaf, late_types = _boot("js/bid-model.js", "js/excel-math.js", "js/work-types.js")
    assert early_model["threw"] == "bid-model.js needs excel-math.js loaded before it"
    assert late_leaf["threw"] is None, "the leaf is fine anywhere: the mistake is the model's position"
    assert late_types["threw"] is None, "the vocabulary is fine anywhere too"


# ── red without the code ─────────────────────────────────────────────────────────────────────────
LEAF = "js/excel-math.js"
BREAKS = {
    "ceiling rounds down instead of up": (
        LEAF, "    return Math.ceil(q) * s;", "    return Math.floor(q) * s;", ["ceiling"]),
    "ceiling forgets the float guard on the quotient": (
        LEAF, "    var q = parseFloat((v / s).toPrecision(12));", "    var q = v / s;", ["ceiling"]),
    "ceiling forgets the float guard altogether": (
        LEAF, "    var q = parseFloat((v / s).toPrecision(12));", "    var q = num(n) / s;", ["ceiling", "pack count"]),
    "a significance of 0 stops giving 0": (
        LEAF, "    if (s === 0) return 0;", "    void 0;", ["ceiling"]),
    "a missing significance is no longer 1": (
        LEAF, "    var s = (significance === undefined || significance === null) ? 1 : num(significance);",
        "    var s = (significance === undefined || significance === null) ? 0 : num(significance);", ["ceiling"]),
    "roundUp rounds toward zero on a negative": (
        LEAF, "    return g >= 0 ? Math.ceil(g) : -Math.ceil(-g);", "    return Math.ceil(g);", ["roundUp"]),
    "copyInto lets a prototype key through": (
        LEAF, "    return Object.assign(dst, Object.fromEntries(safe));", "    return Object.assign(dst, src || {});",
        ["copyInto"]),
    "num lets a non-finite number through": (
        LEAF, '    if (typeof raw === "number") return isFinite(raw) ? raw : 0;',
        '    if (typeof raw === "number") return raw;', ["num"]),
    "num stops reading a dollar sign": (
        LEAF, '    var s = String(raw).replace(/[$,\\s]/g, "");', '    var s = String(raw).replace(/[,\\s]/g, "");', ["num"]),
    "isBlank counts zero as blank": (
        LEAF, '    return v === null || v === undefined || (typeof v === "string" && v.replace(/\\s/g, "") === "");',
        '    return v === null || v === undefined || v === 0 || (typeof v === "string" && v.replace(/\\s/g, "") === "");',
        ["isBlank"]),
    "money prints a minus sign on a zero": (
        LEAF, '    return (v < 0 && r !== 0 ? "-$" : "$") + r.toLocaleString("en-US");',
        '    return (v < 0 ? "-$" : "$") + r.toLocaleString("en-US");', ["text"]),
    "pct rounds to a tidy two places": (
        LEAF, "    var s = parseFloat(v.toPrecision(12)).toFixed(4);", "    var s = parseFloat(v.toPrecision(12)).toFixed(2);",
        ["text"]),
    "fmtSf drops the decimals": (
        LEAF, '    return num(n).toLocaleString("en-US", { maximumFractionDigits: 2 });',
        '    return num(n).toLocaleString("en-US", { maximumFractionDigits: 0 });', ["text"]),
    "the leaf starts holding a rate": (
        LEAF, "    isBlank: isBlank", "    isBlank: isBlank, SHIPPING_RATE: 0.02", ["surface"]),
    "the model grows its own roundUp again": (
        "js/bid-model.js", "  var num = deps.math.num, copyInto = deps.math.copyInto, roundUp = deps.math.roundUp,",
        "  var num = deps.math.num, copyInto = deps.math.copyInto, roundUp = function (n) { return Math.ceil(num(n)); },",
        ["same function"]),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    """A copy of one line of one file is broken, and the named checks must notice. The harness needs the
    model and the library beside the leaf, so they come along unmodified (`also`)."""
    require_node()
    rel, old, new, must_notice = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new, also=["js/bid-model.js", "js/library-core.js"])
    broken = _run(frontend)
    for check in must_notice:
        assert CHECKS[check](broken), "the %r check did not notice: %s" % (check, name)


def test_every_check_has_a_break_in_the_table_that_it_notices():
    covered = {check for *_, notices in BREAKS.values() for check in notices}
    assert covered == set(CHECKS), "a check no break turns red proves nothing: %s" % sorted(set(CHECKS) - covered)
