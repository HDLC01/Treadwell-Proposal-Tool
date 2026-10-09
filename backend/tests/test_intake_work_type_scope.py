"""Intake shows only the quantity fields the chosen work type actually uses.

Hanz, 2026-08-06, looking at the live intake with Epoxy selected:

    "You picked epoxy, you should not show Polish Floor SF, only in combo."

He was right, and it was worse than one stray field. `renderSystems()` hardcoded Epoxy floor
SF, Polish floor SF and Cove LF into every system block for every work type, while
`syncScopeToWorkType()` toggled only gyp-versus-everything-else. So a polish job asked for cove
(an epoxy detail) and an epoxy job asked for polish area. A form that asks for things that do
not apply teaches people to ignore it, which is how a real field gets skipped.

TWO HALVES, and the second is the one with teeth:

  * Intake HIDES the fields, and deliberately keeps their values — somebody who typed a polish
    area under Combo and then switched to Epoxy should find it again on switching back.
  * Because the value survives, a stale quantity can still be sitting in the draft. Filtering
    happens where intake values reach CELLS (`autofillFromIntake` in estimate-review.js), so an
    orphaned polish area can never be written onto the sheet for an epoxy job.

Hiding without the second half would be the worse outcome: invisible on screen, still priced.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture()
def index_js():
    return (FRONTEND / "js" / "index.js").read_text(encoding="utf-8")


@pytest.fixture()
def scope_js():
    return (FRONTEND / "js" / "intake-scope.js").read_text(encoding="utf-8")


@pytest.fixture()
def review_js():
    return (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")


# ── intake: the right fields for the work type ────────────────────────────────
# Since Phase 9a the fields are drawn and shown by js/intake-scope.js, and the live intake delegates to
# it. These checks EXECUTE the real module (and, in test_intake_scope_module.py, the real page against
# golden snapshots) instead of reading source text.
@pytest.fixture(scope="module")
def scopes():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    code = ("const m=require(process.argv[1]);"
            "const o={};for(const j of ['epoxy','polish','combo','gyp'])o[j]=m.scopesFor(j);"
            "o.markup=m.systemsMarkup(2);console.log(JSON.stringify(o));")
    proc = subprocess.run(["node", "-e", code, str(FRONTEND / "js" / "intake-scope.js")],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_every_quantity_field_declares_which_work_types_it_belongs_to(scopes):
    for scope in ("epoxy", "polish", "cove"):
        assert 'data-scope="%s"' % scope in scopes["markup"], (
            "the %s field is not tagged, so nothing can gate it" % scope)


def test_the_work_type_map_matches_what_hanz_asked_for(scopes):
    """Cove is an epoxy detail: a polish-only job never shows it."""
    assert set(scopes["epoxy"]) == {"epoxy", "cove"}
    assert set(scopes["polish"]) == {"polish"}, "polish must not be asked for epoxy SF or cove"
    assert set(scopes["combo"]) == {"epoxy", "polish", "cove"}
    assert set(scopes["gyp"]) == set(), "gyp uses its own three SF buckets"


def test_polish_is_never_asked_for_cove(scopes):
    """The specific domain fact Hanz confirmed. Worth its own test so a later edit that adds
    cove back to polish has to argue with this name."""
    assert "cove" not in scopes["polish"]


def test_fields_are_hidden_and_never_removed(scope_js):
    """The field NAMES are what saved drafts and the estimate-cell mappings key on. Removing an
    input would break both, and would also lose a value the estimator may want back."""
    i = scope_js.index("function applyScope")
    block = scope_js[i:i + 1500]
    assert "style.display" in block, "expected a visibility toggle"
    for bad in (".remove()", "removeChild", "innerHTML =", "outerHTML"):
        assert bad not in block, "applyScope destroys fields instead of hiding them (%s)" % bad


def test_a_row_left_with_no_visible_fields_is_collapsed(scope_js):
    """Otherwise polish shows an empty gap where the cove row used to be."""
    i = scope_js.index("function applyScope")
    block = scope_js[i:i + 1500]
    assert ".row" in block and "anyShown" in block


def test_the_gating_runs_on_load_not_only_on_change(index_js):
    """A restored draft opens with a work type already chosen. Without this the fields are wrong
    until somebody touches the radios."""
    after = index_js[index_js.index("function syncScopeToWorkType"):]
    assert re.search(r'\n\s*syncScopeToWorkType\(\);', after), (
        "syncScopeToWorkType is defined and wired to change, but never called on load")


# ── the half with teeth: an orphaned value must not reach the sheet ───────────
def test_intake_values_are_filtered_by_work_type_before_they_reach_cells(review_js):
    assert "SCOPED_FIELDS" in review_js
    assert "fieldAppliesTo" in review_js
    block = review_js[review_js.index("(function autofillFromIntake"):][:900]
    assert "fieldAppliesTo(field" in block, (
        "every intake field is still seeded regardless of work type, so a hidden polish area "
        "typed under Combo still gets written to the Polish sheet on an epoxy job")


def test_the_scoped_field_list_covers_every_quantity_cell(review_js):
    """Anything in FORM_TO_CELL that is a QUANTITY must be scoped. Project name, contacts and
    dates are common to every job and must NOT be scoped, or they would stop being seeded."""
    i = review_js.index("const SCOPED_FIELDS")
    block = review_js[i:i + 700]
    scoped = set(re.findall(r'^\s*(\w+):\s*\[', block, re.M))
    assert scoped == {"system_1_sf", "system_2_sf", "cove_1_lf", "cove_2_lf", "polish_sf"}, scoped
    for common in ("project_name", "contact_name", "bid_date", "architect"):
        assert common not in scoped, "%s applies to every job and must stay unscoped" % common


def test_cove_is_scoped_to_epoxy_and_combo_only(review_js):
    i = review_js.index("const SCOPED_FIELDS")
    block = review_js[i:i + 700]
    for field in ("cove_1_lf", "cove_2_lf"):
        types = re.search(field + r':\s*\[([^\]]*)\]', block).group(1)
        assert "polish" not in types, "%s can be written on a polish job" % field
        assert "epoxy" in types and "combo" in types


def test_an_unlisted_field_still_gets_seeded(review_js):
    """fieldAppliesTo must default to TRUE. Defaulting to false would silently stop seeding
    every common field the moment somebody added one."""
    i = review_js.index("function fieldAppliesTo")
    block = review_js[i:i + 260]
    assert "!types" in block, (
        "an unscoped field is treated as not applying, which would stop seeding project name, "
        "contacts and dates")
