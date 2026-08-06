"""ROUNDUP and CEILING must behave the way Excel's do, or every bid reads high.

THE BUG THIS EXISTS TO PREVENT.

The estimate workbook wraps nearly every subtotal in `ROUNDUP(...,0)` — 1,570 calls across the
sheets, 201 of them on Epoxy — plus 78 `CEILING`s. Excel quietly cleans a value sitting a hair
off a round number before rounding it; HyperFormula does not. So `17774.4 + 386.4 + 1159.2`,
which lands on 19320.000000000004 in binary floating point, rounds UP to 19321 in the browser and
stays 19320 in Excel.

The error only ever goes one way, and it compounds up the subtotal chain.

MEASURED, not theorised. Audited against Excel itself on six real Treadwell estimates from the
Dropbox folder — every rounding cell and every headline total, 10,208 cells, to the cent, each
engine configuration in its own process so nothing leaked between them:

    what shipped before ......... 98 cells wrong
    smartRounding: false ........ 97 cells wrong
    precisionRounding: 10 ....... 97 cells wrong
    with this override ........... 0 cells wrong

The worst were not polish. `Epoxy!D88`, the epoxy total base bid, read $15,219 where the
workbook says $15,213, and $11,033 where it says $11,029.

That last table is why these tests are worth having: two settings that look like obvious cheap
fixes move exactly one cell out of ninety-eight. Anybody reaching for one of them instead of the
override needs to fail a test with this reasoning attached.

The audit harness is in docs/excel-parity-audit/ and runs against any workbook.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
ROUNDING_JS = FRONTEND / "js" / "xl-excel-rounding.js"

# Every page that builds a HyperFormula engine.
ENGINE_PAGES = ["estimate-review.html", "info-sheet.html", "polish-estimate.html"]


@pytest.fixture()
def js():
    return ROUNDING_JS.read_text(encoding="utf-8")


def test_the_override_exists(js):
    assert "ROUNDUP" in js and "CEILING" in js
    assert "registerFunctionPlugin" in js


def test_both_functions_are_overridden(js):
    """CEILING has the same exposure as ROUNDUP — 78 of them on the Epoxy sheet."""
    i = js.index("implementedFunctions")
    block = js[i:i + 700]
    assert "ROUNDUP:" in block and "CEILING:" in block


def test_the_builtins_are_unregistered_first(js):
    """HyperFormula rejects a duplicate function name, so registration silently does nothing
    unless the built-in is removed first."""
    assert 'unregisterFunction("ROUNDUP")' in js
    assert 'unregisterFunction("CEILING")' in js
    assert js.index('unregisterFunction("ROUNDUP")') < js.index("registerFunctionPlugin")


def test_the_value_is_snapped_before_rounding_and_after_scaling(js):
    """Scaling by a power of ten to honour the `places` argument reintroduces exactly the noise
    being removed, so the snap has to happen twice."""
    # Matches the class-method form. It was `roundup = function`, from the prototype-based
    # version that could not be instantiated at all.
    i = js.index("roundup(ast, state)")
    block = js[i:i + 700]
    assert block.count("snap(") >= 2, "only one snap; the places argument reintroduces the noise"


def test_the_plugin_is_a_class_and_not_a_prototype_chain(js):
    """HyperFormula's FunctionPlugin is an ES class, and an ES class cannot be invoked without
    `new`. The prototype form threw inside buildEmpty(), so Estimate Review, the Info Sheet
    editor and the polish page would all have failed to OPEN — worse than the rounding bug being
    fixed. Only a browser caught it; these source tests could not."""
    # Comments stripped: the file explains the bug by QUOTING the broken form, so a raw grep
    # matches its own prose. That has now caught me out three times in this file's tests.
    code = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    assert re.search(r'class\s+ExcelRounding\s+extends\s+Plugin', code), (
        "the plugin is not a real class; HyperFormula cannot instantiate it")
    assert "Plugin.apply(this" not in code, (
        "calling an ES class constructor as a function throws when the engine is built")
    assert "Object.create(Plugin.prototype)" not in code


def test_twelve_significant_digits(js):
    """Fewer would discard real precision; more would keep the float noise."""
    assert "toPrecision(12)" in js


def test_a_failure_to_register_is_loud(js):
    """Silently skipping would leave every bid a few dollars high with nothing to explain it —
    the exact failure mode this file was written for."""
    assert js.count("console.error") >= 3
    for msg in ("HyperFormula is not loaded", "registration failed"):
        assert msg in js


@pytest.mark.parametrize("page", ENGINE_PAGES)
def test_every_engine_page_loads_the_override(page):
    html = (FRONTEND / page).read_text(encoding="utf-8")
    assert "/js/xl-excel-rounding.js" in html, (
        "%s builds a HyperFormula engine without the Excel-compatible rounding, so its totals "
        "read high" % page)


@pytest.mark.parametrize("page", ENGINE_PAGES)
def test_the_override_loads_after_hyperformula_and_before_the_page_script(page):
    """Registration is global and one-time: it has to happen after the library exists and before
    anything builds an engine."""
    html = (FRONTEND / page).read_text(encoding="utf-8")
    hf = html.index("hyperformula")
    ovr = html.index("/js/xl-excel-rounding.js")
    assert hf < ovr, "the override runs before HyperFormula is defined"

    # The page's own script, whichever it is, must come after.
    own = re.search(r'<script src="/js/(estimate-review|info-sheet|polish-estimate)\.js"', html)
    assert own, page
    assert ovr < own.start(), "a page script could build an engine before the override registers"


@pytest.mark.parametrize("page", ENGINE_PAGES)
def test_no_page_still_uses_the_settings_that_do_not_work(page):
    """precisionRounding: 4 also rounded every value READ out of the engine to 5 significant
    figures, so $59,642.37 came back as 59642 — cents could never show on a five-figure bid."""
    for name in ("estimate-review.js", "info-sheet.js", "polish-estimate.js", "xl-core.js"):
        p = FRONTEND / "js" / name
        if not p.exists():
            continue
        # Comments stripped first. The files explain WHY these settings were rejected, and quote
        # them to do it — a test that greps the raw source ends up matching its own prose, which
        # is how this test failed the first time it ran.
        src = "\n".join(l for l in p.read_text(encoding="utf-8", errors="replace").splitlines()
                        if not l.strip().startswith("//"))
        assert "precisionRounding: 4" not in src, (
            "%s still rounds reads to 5 significant figures" % name)
        assert "smartRounding: true" not in src, (
            "%s still lets smartRounding nudge a value that ROUNDUP then rounds up again" % name)


def test_the_audit_numbers_are_recorded_where_someone_will_find_them(js):
    """The next person to look at this will want to know why two obvious one-line fixes were
    rejected. Without the numbers they will try one."""
    assert "10,208" in js or "10208" in js
    assert "98" in js, "the count of wrong cells under the old config is not recorded"
    assert "D88" in js, "the worst affected cell is not named"
