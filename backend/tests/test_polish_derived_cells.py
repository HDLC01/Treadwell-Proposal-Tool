"""The polish form must never write a cell the worksheet computes for itself.

THE BUG THIS EXISTS TO PREVENT.

The Polish tab is not a grid of blanks waiting to be filled. Most of what looks like an input is
a FORMULA:

    B20 = "=E18"                                  densifier quantity follows the area
    B29 = "=ROUNDUP(IF(E29=\"yes\",(E18/3500),0),0)"  joint filler kits, worked out from the area
    C17 = "=IF(B10=\"New\",0.05,0.15)"              patch rate, by new-build versus renovation
    D5  = "=Epoxy!D5"                             prevailing wage MIRRORS the epoxy tab

Write a number into one of those and the formula is gone — replaced by a constant, in the engine
AND in the downloaded .xlsx, because `cell_values` is what /api/generate fills the workbook from.
The line stops tracking the area for the life of that estimate, and Kyle's file comes back with
its arithmetic quietly removed.

MEASURED. Opening the page on staging project 396f2ba1 showed materials of $0 against 1,632 SF
and a bid of $14,953 where the old screen said $17,431. Twenty-two cells were being clobbered:
three conditions, eight material rows, four labour fields, four standard adds, three option
prices. `hydrateFromSheet` was half the mechanism — it read a formula's current result (0, while
the area was still loading) into form state, and the next save wrote it back as a constant.

WHY THIS TEST IS SHAPED THIS WAY.

It reads the REAL workbook. A hand-maintained list of "cells not to touch" is worth very little,
because the list and the template drift apart the first time Kyle edits his file — and the
failure is silent and looks like a plausible price. So the check is: run cellWrites() with a
fully-populated state, take every address it produces, open the template, and fail on any one
that holds a formula. That generalises to cells nobody has thought of yet, including any Kyle
adds later.

It would have caught all twenty-two.
"""
import json
import pathlib
import shutil
import subprocess
import warnings

import pytest

openpyxl = pytest.importorskip("openpyxl")

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
CORE = FRONTEND / "js" / "polish-estimate-core.js"
TEMPLATE = ROOT / "backend" / "templates" / "estimate_sheet_5.7.xlsx"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")

# Deliberately maximal: every field the form can offer, all set. A state with gaps in it would
# let a clobbering write escape simply because nothing filled that field.
FULL_STATE = """{
  areas: [ {name:'Main sales floor', sf:9000}, {name:'Back of house', sf:3500} ],
  system: 'S&P',
  tooling: 'traditional',
  conditions: { local:true, hard_bid:true, prevailing_wage:true, taxable:true, remodel_tax:true },
  materials: { 17:{qty:12500,cost:0.15}, 20:{qty:12500,cost:0.07}, 21:{qty:12500,cost:0.10},
               22:{qty:12500,cost:0.11}, 25:{qty:12500,cost:0.14}, 26:{qty:12500,cost:0.14},
               29:{qty:4,cost:500} },
  added: [ {name:'Stair nosing infill', qty:46, cost:12.50},
           {name:'Extra dye pass', qty:1, cost:900},
           {name:'Weekend premium', qty:2, cost:450},
           {name:'Dust containment', qty:1, cost:275} ],
  labour: { polishing:{crew:4,days:6,rate:520}, mockup:{crew:2,days:1,rate:480},
            joint_filler:{crew:2,days:2,rate:32.2} },
  adds: { ram_board:240, joint_filler:180, cove_4:60, cove_6:40, stripe_4:310, stripe_6:120 },
  options: { salt_pepper:true, standard_sheen:true, dye:true }
}"""


def _node(expr: str):
    src = (
        "const P = require(%s);\n"
        "const S = %s;\n"
        "console.log(JSON.stringify(%s));\n" % (json.dumps(str(CORE)), FULL_STATE, expr)
    )
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def polish_sheets():
    """Formula text for every cell, per sheet, straight out of Kyle's template."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(TEMPLATE, data_only=False)
    return wb


@pytest.fixture(scope="module")
def written():
    return _node("P.cellWrites(S)")


def _formula_at(wb, ref):
    sheet, _, addr = ref.partition("!")
    if sheet not in wb.sheetnames:
        return None
    v = wb[sheet][addr].value
    return v if isinstance(v, str) and v.startswith("=") else None


def test_no_write_lands_on_a_formula(written, polish_sheets):
    """The whole point. Every address the form produces, checked against the real workbook."""
    clobbered = []
    for ref in sorted(written):
        f = _formula_at(polish_sheets, ref)
        if f is not None:
            clobbered.append("%s holds %s but the form writes %r" % (ref, f, written[ref]))
    assert not clobbered, (
        "the form would replace %d worksheet formula(s) with constants, in the downloaded .xlsx "
        "as well as on screen:\n  %s" % (len(clobbered), "\n  ".join(clobbered)))


def test_every_write_target_actually_exists_on_its_sheet(written, polish_sheets):
    """A typo'd sheet name fails silently — the value goes nowhere and the bid looks fine."""
    for ref in written:
        sheet, sep, addr = ref.partition("!")
        assert sep, "%s is not sheet-qualified" % ref
        assert sheet in polish_sheets.sheetnames, "%s names a sheet that does not exist" % ref


def test_the_derived_list_matches_the_template(polish_sheets):
    """DERIVED is documentation as well as a guard, and documentation rots. If Kyle turns one of
    these cells back into a constant, or the quoted formula drifts from the file, say so here
    rather than letting the page silently refuse to write a cell that is now a real input."""
    derived = _node("P.DERIVED")
    ws = polish_sheets["Polish"]
    wrong = []
    for addr, quoted in sorted(derived.items()):
        actual = ws[addr].value
        if not (isinstance(actual, str) and actual.startswith("=")):
            wrong.append("%s is listed as derived but the template has %r" % (addr, actual))
        elif actual != quoted:
            wrong.append("%s: listed as %r, template says %r" % (addr, quoted, actual))
    assert not wrong, "DERIVED has drifted from the workbook:\n  " + "\n  ".join(wrong)


def test_the_three_mirrored_conditions_are_written_to_the_epoxy_tab(written):
    """Polish!D5/B6/D6 are "=Epoxy!D5" and friends. Writing the Polish cell would set the right
    number once and cut the link that keeps the two tabs agreeing — so a later change on the
    epoxy side would stop reaching polish, with nothing on screen to show it."""
    for ref in ("Epoxy!D5", "Epoxy!B6", "Epoxy!D6"):
        assert ref in written, "%s is not written, so the condition never reaches the sheet" % ref
        assert written[ref] in ("Yes", "No"), "the sheet stores the literal words Yes/No"
    for ref in ("Polish!D5", "Polish!B6", "Polish!D6"):
        assert ref not in written, "%s is a formula mirroring the epoxy tab; writing it cuts the link" % ref


def test_the_two_conditions_polish_owns_stay_on_polish(written):
    """B4 and B5 are the tab's own constants, not mirrors. Sending them to Epoxy would set the
    wrong tab's flags and leave polish reading its stale defaults."""
    for ref in ("Polish!B4", "Polish!B5"):
        assert ref in written
        assert written[ref] in ("Yes", "No")


def test_a_derived_cell_is_refused_even_when_the_state_supplies_one(polish_sheets):
    """The state that reaches cellWrites is not always one the current page produced: a draft
    saved by the earlier build carries {"Polish!B20": 0}, and a future field could be added
    without noticing the cell is computed. The refusal has to live in the write path, not in
    what the page happens to render."""
    got = _node(
        "P.cellWrites(Object.assign({}, S, {"
        "  materials: {20:{qty:99999,cost:0.07}, 29:{qty:77,cost:500}},"
        "  labour: {polishing:{crew:9,days:9,rate:9}, joint_filler:{crew:9,days:9,rate:9}},"
        "  adds: {ram_board:9999, cove_4:9999}"
        "}))")
    for ref in ("Polish!B20", "Polish!B29", "Polish!B37", "Polish!A44", "Polish!B44",
                "Polish!J17", "Polish!J19"):
        assert ref not in got, "%s is computed by the worksheet and must never be written" % ref
    # ...while the genuine inputs beside them still get through, or the guard is just breakage.
    assert got.get("Polish!C20") == 0.07
    assert got.get("Polish!C29") == 500
    assert got.get("Polish!A37") == 9
    assert got.get("Polish!J21") == 9999 or "Polish!J21" not in got


def _page_code():
    page = (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")
    return "\n".join(l for l in page.splitlines() if not l.strip().startswith("//"))


def _body(code, name):
    """The source of one function, to the start of the next top-level one.

    Scoping matters. An earlier version of these tests grepped the WHOLE file for "isDerived",
    which passed happily while the materials panel emitted raw inputs — the string was present
    because the labour panel used it. A file-wide grep cannot tell you which panel was fixed.
    """
    i = code.index("function " + name)
    j = code.find("\n  function ", i + 1)
    return code[i:j if j != -1 else len(code)]


@pytest.mark.parametrize("panel,marker", [
    ("materialsPanel", "data-mat="),
    ("labourPanel", "data-lab="),
    ("addsPanel", "data-add="),
])
def test_no_panel_renders_a_bare_input_without_checking_derived_first(panel, marker):
    """Every panel that draws worksheet cells has to ask whether each one is computed. An
    editable-looking box beside a derived figure asks the estimator for a number that already
    has an answer — and any answer typed replaces the formula."""
    code = _page_code()
    body = _body(code, panel)
    if marker not in body:
        pytest.skip("%s does not render %s inputs" % (panel, marker))
    assert "isDerived" in body or "qtyOrCostCell" in body, (
        "%s emits %s inputs unconditionally, so a computed cell is offered as a field" %
        (panel, marker))


def test_the_helper_that_gates_material_fields_actually_checks(polish_sheets):
    """qtyOrCostCell is where the materials panel delegates the decision. If it stops checking,
    the panel is back to rendering formulas as inputs while still looking gated."""
    body = _body(_page_code(), "qtyOrCostCell")
    assert "isDerived" in body and "derivedCell" in body


def test_hydrate_never_reads_a_formula_into_form_state():
    """The other half of the bug. hydrate read a formula's current result — 0, while the area
    was still loading — into form state, and the next save wrote it back as a constant."""
    body = _body(_page_code(), "hydrateFromSheet")
    assert "isDerived" in body, (
        "hydrateFromSheet reads computed values into form state, which is how a formula gets "
        "written back as a constant")


def test_poisoned_drafts_are_cleaned_rather_than_merged_forward():
    """Refusing to write is not enough. Both the load and the save are a MERGE, so an entry
    written by the earlier build outlives the fix and keeps the line pinned at zero."""
    page = (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in page.splitlines() if not l.strip().startswith("//"))
    assert "dropDerived" in code
    assert code.count("dropDerived(") >= 3, (
        "dropDerived must run on the initial load AND on every save; a merge on either side "
        "reintroduces the poison")
