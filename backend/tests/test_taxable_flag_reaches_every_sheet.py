"""A tax-exempt job must be tax-exempt on every sheet it is priced from.

Kyle, mid-estimate: he copied a tab to make a priced option on a TAX-EXEMPT job and the copy
charged 9.475% sales tax while its own Taxable box read "No".

WHAT THE WORKBOOK ACTUALLY DOES. The sales-tax rate cell is SHEET-relative on all eleven priced
sheets -- ``=IF($B$6="no",0,0.09475)`` on Epoxy/Polish/Seal/Seal (+Jnts)/Epoxy blank/Leveling and
``=IF($B$8="no",0,0.09475)`` on all five gyp variants. ``$B$6`` is column- and row-absolute but
sheet-relative, so **each sheet reads its own flag cell**. Seven of those flag cells are mirrors
(``=Epoxy!B6``, ``=Polish!B6``, ``='Gyp (USG 1-8")'!B8``); four are independent literals:

    Epoxy!B6              'Yes'
    Leveling!B6           'Yes'
    'Gyp (USG 1-8")'!B8   'Yes'
    'Gyp (FR)'!B8         'Yes'    <- does NOT mirror the gyp base, unlike the other three variants

The tool wrote the estimator's answer to exactly one of them, ``Epoxy!B6``. So the reported bug
(a copied tab) was the visible third of it: **every tax-exempt gypsum and Leveling bid has been
quoted carrying 9.475% it should not have, with no copy involved at all.**

WHY THIS FILE READS THE WORKBOOK RATHER THAN RESTATING IT. The addresses above are not a
convention -- Kyle's gyp block sits one row lower than the epoxy block (B6 there is "Miles Away"),
and 'Gyp (FR)' breaks the pattern the other four gyp variants follow. A test that hard-codes what
this file's author believed would have agreed with the bug. So every address, every mirror and
every rate formula below comes out of ``estimate_sheet_5.7.xlsx`` live, and the fix's own maps are
checked AGAINST it.

WHY DOLLARS, NOT STRUCTURE. Asserting "B6 says No" passes while the rate cell is separately wrong.
openpyxl cannot evaluate a workbook, and neither LibreOffice nor HyperFormula is available here --
so the chain is walked with the workbook's OWN formula text at every step: resolve the flag
through its mirrors, evaluate Kyle's own ``IF(...)`` to get the RATE, then confirm the tax dollar
cell still multiplies by that rate cell and that the TOTAL still sums it. Rate 0 -> that row is
$0 -> the total drops by exactly the tax that used to be in it. Nothing here re-implements the
pricing; ``pricing.py`` is deliberately not involved (it respects ``taxable`` but is ~1% off on
quartz and ~30% wrong on polish, so routing the printed figure through it would swap one wrong
number for another).

THE THREE SURFACES. A fix that makes two of them agree is this bug again in a new disguise -- the
mirror-formula version of it would have had the screen and the .docx saying tax-free while the
downloaded .xlsx charged 9.475%, because ``_coerce`` turns a quoted-sheet-name formula into text.
So: the .xlsx is asserted here through the real ``fill_estimate``; the on-screen chip/total and
the proposal figure both come off the live HyperFormula engine, and ``taxable-flag-harness.js``
asserts the same literal reached it, cell for cell, out of the shipped ``copyTab``.

EVERY SHEET KEEPS ITS OWN (2026-09-30). Hanz: "for the options we follow each worksheets tax
options", "in the generation of the files, it would have the wording tax or not based off the
worksheet", and, asked whether an option should follow the base, "Stay independent". So the
one-answer-per-job fan-out above is now the LEGACY pass a never-split draft gets once, on the
open that splits it: from then on every flag-block sheet -- template or copy -- holds its own two
literals, a new project starts them all at the intake's answers, a copy starts at its source's,
and an option's price and its wording in the document come off its own sheet. Sections 5-7 below
execute that end to end: the real browser code, then the real ``fill_estimate`` and the real
document renderer on what it produced.
"""
import io
import json
import pathlib
import re
import shutil
import subprocess
import warnings

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "taxable-flag-harness.js"
TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "estimate_sheet_5.7.xlsx"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

# The sheets that carry a bid. Everything else in the workbook (Takeoff, Stnd Alts,
# Specs+Dwgs+Addn, validation, Unit Layouts) has no TAXES & FEES block at all, which the
# label walk below proves rather than assumes.
PRICED_SHEETS = ["Epoxy", "Polish", "Seal", "Seal (+Jnts)", "Epoxy blank", "Leveling",
                 'Gyp (USG 1-8")', "Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")',
                 "Gyp (GWorx SC190)", "Gyp (FR)"]


@pytest.fixture(scope="module")
def wb():
    """Kyle's shipped template, formulas not values. Read-only; never saved."""
    openpyxl = pytest.importorskip("openpyxl")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")     # the x14 dataValidation extension openpyxl drops
        return openpyxl.load_workbook(TEMPLATE, data_only=False)


def _template_cells(wb):
    """The shipped workbook's flag-block cells (and the two seal remodel-rate cells), handed to the
    harness so its sheets hold what Kyle's file holds rather than what this file believes."""
    import estimate_writer as ew
    out = {}
    for sheet, addrs in ew.FLAG_BLOCK_CELLS.items():
        out[sheet] = {a: wb[sheet][a].value for a in addrs}
    for sheet in ("Seal", "Seal (+Jnts)"):
        out[sheet]["B75"] = wb[sheet]["B75"].value
    return out


@pytest.fixture(scope="module")
def result(wb):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    import estimate_writer as ew
    proc = subprocess.run(
        ["node", str(HARNESS), str(FRONTEND), json.dumps(ew.list_sheet_names()),
         json.dumps(_template_cells(wb))],
        capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed -- read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── reading the workbook's own formulas ──────────────────────────────────────

_MIRROR = re.compile(r"^=(?:'([^']+)'|([A-Za-z0-9 ()+\-]+))!\$?([A-Z]+)\$?(\d+)$")
_RATE = re.compile(r'^=IF\(\$?([A-Z]+)\$?(\d+)="([a-z]+)",([0-9.]+),([0-9.]+)\)$', re.I)


def _resolve_flag(wb, sheet, addr, _depth=0):
    """Follow a flag cell through its mirror chain to the cell that actually holds the answer.

    Returns (sheet, addr, value). Raises rather than guessing: an unrecognised formula in this
    block means the template changed shape and every address in the fix needs re-deriving."""
    assert _depth < 8, "mirror loop at %s!%s" % (sheet, addr)
    v = wb[sheet][addr].value
    if isinstance(v, str) and v.startswith("="):
        m = _MIRROR.match(v.strip())
        assert m, "%s!%s is a formula this walk does not understand: %r" % (sheet, addr, v)
        return _resolve_flag(wb, m.group(1) or m.group(2), m.group(3) + m.group(4), _depth + 1)
    return sheet, addr, v


def _rate_from(formula, flag_value):
    """Evaluate Kyle's own ``=IF($B$6="no",0,0.09475)`` for a given flag value.

    Deliberately strict: any other shape raises, because a silently-unparsed rate cell is how a
    green test would certify a bid that still charges tax."""
    m = _RATE.match(str(formula).strip())
    assert m, "the sales-tax rate cell is no longer an IF this walk understands: %r" % (formula,)
    _col, _row, needle, when_true, when_false = m.groups()
    hit = str(flag_value or "").strip().lower() == needle.strip().lower()
    return float(when_true if hit else when_false)


def _tax_row(wb, sheet):
    """(rate_addr, dollar_addr, flag_addr) for a sheet's Sales Tax line, found by its LABEL.

    By label, not by a typed address: the row differs per layout (Epoxy 80, Polish/Seal 74,
    Leveling 76, gyp 79) and the totals column differs too (D on epoxy/polish, E on gyp)."""
    ws = wb[sheet]
    for row in range(1, ws.max_row + 1):
        if str(ws.cell(row=row, column=1).value or "").strip().lower() != "sales tax":
            continue
        rate_addr = "B%d" % row
        formula = ws[rate_addr].value
        m = _RATE.match(str(formula).strip())
        assert m, "%s!%s is not the IF this walk understands: %r" % (sheet, rate_addr, formula)
        flag_addr = m.group(1) + m.group(2)
        dollar = next(("%s%d" % (c, row) for c in ("D", "E")
                       if str(ws["%s%d" % (c, row)].value or "").startswith("=ROUNDUP")), None)
        assert dollar, "%s has a Sales Tax rate with no dollar cell beside it" % sheet
        return rate_addr, dollar, flag_addr
    raise AssertionError("no 'Sales Tax' label in column A of %s" % sheet)


# ── 1. the workbook invariant that would have caught this ────────────────────


def test_every_priced_sheet_has_a_sales_tax_line_that_reads_a_flag_the_fix_writes(wb):
    """The walk whose absence let four sheets drift.

    For every sheet with a "Sales Tax" label, follow the rate formula's own reference through the
    mirror chain and assert it lands on a cell ``TAXABLE_FLAG_CELLS`` writes. That is the whole
    claim, stated over the shipped workbook rather than over a list somebody typed: add a sixth
    gyp variant, or make one of today's mirrors independent, and this fails until the map moves.

    Before 2026-09-05 the equivalent assertion existed only in test_intake_conditions.py and only
    looked at Polish -- the one sheet whose mirror was already correct."""
    import estimate_writer as ew

    written = {"%s!%s" % (s, a) for s, a in ew.TAXABLE_FLAG_CELLS.items()}
    assert written, "the fix writes nothing at all"
    seen = []
    for sheet in PRICED_SHEETS:
        rate_addr, _dollar, flag_addr = _tax_row(wb, sheet)
        src_sheet, src_addr, _v = _resolve_flag(wb, sheet, flag_addr)
        key = "%s!%s" % (src_sheet, src_addr)
        assert key in written, (
            "%s's sales tax reads %s!%s, which nothing writes -- a tax-exempt bid on that sheet "
            "keeps the template's 'Yes' and bills 9.475%%" % (sheet, src_sheet, src_addr))
        seen.append((sheet, rate_addr, key))
    # ...and every cell the fix writes is actually reached by some sheet's rate formula, so the
    # map cannot grow a target that changes nothing.
    assert {k for _s, _r, k in seen} == written, sorted(seen)


def test_the_sheets_with_no_bid_on_them_have_no_sales_tax_line(wb):
    """PRICED_SHEETS above is a list, and a list can go stale. This is what stops it: any other
    worksheet growing a Sales Tax row would be a priced sheet nobody added to the walk."""
    for name in wb.sheetnames:
        if name in PRICED_SHEETS:
            continue
        labels = {str(wb[name].cell(row=r, column=1).value or "").strip().lower()
                  for r in range(1, min(wb[name].max_row, 200) + 1)}
        assert "sales tax" not in labels, (
            "%s has a Sales Tax line and is not in PRICED_SHEETS" % name)


def test_the_gyp_block_sits_one_row_lower_and_gyp_fr_is_its_own_answer(wb):
    """Two facts that a generalised "write B6" would get wrong, in opposite directions.

    On a gyp layout B6 is *Miles Away* -- writing the tax answer there puts a word in a mileage
    cell and leaves the tax alone. And 'Gyp (FR)' does NOT mirror the gyp base the way the other
    three variants do, so a fix covering "the gyp sheets" as a group ships with it still broken."""
    gyp_base = 'Gyp (USG 1-8")'
    assert str(wb[gyp_base]["A6"].value).strip().lower().startswith("miles")
    assert str(wb[gyp_base]["A8"].value).strip().lower().startswith("taxable")
    assert str(wb["Epoxy"]["A6"].value).strip().lower().startswith("taxable")

    assert wb[gyp_base]["B8"].value == "Yes", "the gyp base's Taxable is a literal"
    assert wb["Gyp (FR)"]["B8"].value == "Yes", (
        "'Gyp (FR)'!B8 is no longer an independent literal -- re-derive TAXABLE_FLAG_CELLS")
    for variant in ("Gyp (USG N12ULTRA)", 'Gyp (USG N25 1-4")', "Gyp (GWorx SC190)"):
        assert wb[variant]["B8"].value == "='%s'!B8" % gyp_base, (
            "%s stopped mirroring the gyp base -- it now needs writing too" % variant)


def test_the_fixs_literal_map_matches_the_workbook_cell_for_cell(wb):
    """Every cell the fix writes really is an independent literal, and every mirror really is a
    mirror. A literal written into a mirror replaces a live reference and forks the two sheets
    apart for good -- the divergence found in Kyle's own filed workbooks, and the one PR #432
    refused to introduce for the remodel rate."""
    import estimate_writer as ew

    for sheet, addr in ew.TAXABLE_FLAG_CELLS.items():
        v = wb[sheet][addr].value
        assert isinstance(v, str) and not v.startswith("="), (
            "%s!%s is a formula (%r) -- writing a literal there forks a working mirror" %
            (sheet, addr, v))
        assert v.strip().lower() in ("yes", "no")
    mirrors = {"Polish": "B6", "Seal": "B6", "Seal (+Jnts)": "B6", "Epoxy blank": "B6",
               "Gyp (USG N12ULTRA)": "B8", 'Gyp (USG N25 1-4")': "B8", "Gyp (GWorx SC190)": "B8"}
    for sheet, addr in mirrors.items():
        assert sheet not in ew.TAXABLE_FLAG_CELLS
        assert str(wb[sheet][addr].value).startswith("="), (
            "%s!%s stopped being a mirror -- it now needs writing like the four literals" %
            (sheet, addr))


def test_remodel_tax_has_exactly_one_literal_and_it_is_epoxy(wb):
    """Kyle's twin defect, and the reason it ships in the same change rather than after it.

    Epoxy!D6 is the ONLY literal remodel toggle -- Leveling!D6, both gyp D8 and every other
    sheet's are ``=Epoxy!D6``. So the base tabs were always right and only a COPY of the Epoxy
    layout froze it, at the template's 'No'. That direction UNDERBIDS: it drops a remodel tax the
    estimator switched on, which is the error that costs Treadwell rather than the customer."""
    assert wb["Epoxy"]["D6"].value == "No"
    for sheet, addr in (("Polish", "D6"), ("Seal", "D6"), ("Seal (+Jnts)", "D6"),
                        ("Epoxy blank", "D6"), ("Leveling", "D6"),
                        ('Gyp (USG 1-8")', "D8"), ("Gyp (FR)", "D8"),
                        ("Gyp (USG N12ULTRA)", "D8")):
        v = str(wb[sheet][addr].value)
        assert v.startswith("="), "%s!%s is no longer a mirror: %r" % (sheet, addr, v)


# ── the flag block as a WHOLE, so this file cannot certify what it did not fix ──


def _flag_labels(wb, sheet):
    """Every Yes/No question in the sheet's A1:D10 block, as {label: addr}.

    "Yes/No" is decided by what the cell RESOLVES to, not by the label: the block also holds
    "< 70 miles?" pointing at a Google Earth hint and "Miles Away" holding a number, and neither
    is an answer this walk has anything to say about."""
    ws, out = wb[sheet], {}
    for row in range(1, 11):
        for label_col, value_col in (("A", "B"), ("C", "D")):
            label = str(ws["%s%d" % (label_col, row)].value or "").strip()
            if not label.endswith("?"):
                continue
            addr = "%s%d" % (value_col, row)
            if wb[sheet][addr].value is None:
                continue
            _s, _a, resolved = _resolve_flag(wb, sheet, addr)
            if str(resolved or "").strip().lower() not in ("yes", "no"):
                continue
            out[label.rstrip("?").strip().lower()] = addr
    return out


FIXED_FLAGS = {"taxable", "remodel tax"}
# Local? and Hard Bid? are frozen on copied tabs by the IDENTICAL mechanism and are NOT in this
# change: they drive markup tiers, the hard-bid discount, gyp soft costs and travel/lodging, none
# of them a flat percentage, and nobody has yet quantified how far off a real bid they put it.
# Raised as Issue 5, deliberately not fixed here.
KNOWN_UNFIXED_FLAGS = {"local", "hard bid"}


@pytest.mark.parametrize("sheet", PRICED_SHEETS)
def test_every_yes_no_flag_in_the_block_is_either_written_or_a_mirror(wb, sheet):
    """THE WALK IS DELIBERATELY WIDER THAN THE FIX, and that is the point of it.

    A walk scoped to "Taxable?" and "Remodel Tax?" would go green while Local? and Hard Bid? stay
    frozen by the same mechanism -- a vacuous invariant certifying the rest of the block as fine.
    So this looks at EVERY Yes/No question in A1:D10 and requires each one to be a mirror (it
    follows the master) or a cell the tool writes. The two that are neither are named out loud
    below and xfail against Issue 5, so a green run says "two known holes", not "no holes".

    Prevailing Wage is a third case and needs no entry: Epoxy!D5 is its only literal and the tool
    has always written it."""
    import estimate_writer as ew

    written = {"%s!%s" % (s, a) for s, a in ew.TAXABLE_FLAG_CELLS.items()}
    written |= {"Epoxy!D6", "Epoxy!D5", "Epoxy!B4", "Epoxy!B5", "Polish!B4", "Polish!B5"}
    unfixed = []
    for label, addr in _flag_labels(wb, sheet).items():
        src_sheet, src_addr, _v = _resolve_flag(wb, sheet, addr)
        if "%s!%s" % (src_sheet, src_addr) in written:
            continue
        unfixed.append((label, "%s!%s" % (src_sheet, src_addr)))
    stray = [u for u in unfixed if u[0] not in KNOWN_UNFIXED_FLAGS]
    assert not stray, "a Yes/No flag nothing writes and nobody has flagged: %r" % (stray,)
    if unfixed:
        pytest.xfail("Issue 5 -- Local?/Hard Bid? are frozen the same way and are not in this "
                     "change: %s carries %r" % (sheet, sorted(u[1] for u in unfixed)))


# ── 2. the .xlsx the estimator downloads ─────────────────────────────────────


def _fill(taxable, tab_copies=None, cell_values=None):
    import estimate_writer as ew
    from openpyxl import load_workbook
    cv = dict(cell_values or {})
    data = ew.fill_estimate({"taxable": taxable}, cell_values=cv, tab_copies=tab_copies)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_workbook(io.BytesIO(data), data_only=False)


# Filling this workbook costs ~5s, so the parametrised cases below share four of them rather
# than generating one per sheet. One copy PER priced layout in a single file also matches what
# an estimator with several options actually downloads.
COPY_OF = {"Copy%d" % (i + 1): s for i, s in enumerate(PRICED_SHEETS)}


def _copy_flag_values(answer):
    """What the browser's fan-out puts in cell_values for a bid with one copy of every layout."""
    import estimate_writer as ew
    out = {}
    for cid, src in COPY_OF.items():
        if src in ew.TAXABLE_FLAG_CELLS:
            out["%s!%s" % (cid, ew.TAXABLE_FLAG_CELLS[src])] = answer
    return out


@pytest.fixture(scope="module")
def exempt_wb():
    return _fill("No")


@pytest.fixture(scope="module")
def taxable_wb():
    return _fill("Yes")


@pytest.fixture(scope="module")
def exempt_copies_wb():
    return _fill("No", tab_copies=[{"id": c, "source": s} for c, s in COPY_OF.items()],
                 cell_values=_copy_flag_values("No"))


@pytest.fixture(scope="module")
def taxable_copies_wb():
    return _fill("Yes", tab_copies=[{"id": c, "source": s} for c, s in COPY_OF.items()],
                 cell_values=_copy_flag_values("Yes"))


def _sales_tax_rate(out_wb, sheet, source_wb=None):
    """The RATE the generated workbook's own Sales Tax formula produces on that sheet.

    Walks: label -> rate formula -> the flag address it references -> through the mirror chain ->
    the value actually sitting there -> Kyle's IF, evaluated. Every step reads the file that was
    just generated, so a write that lands on the wrong cell shows up as a rate, not as a silence."""
    rate_addr, dollar_addr, flag_addr = _tax_row(out_wb, sheet)
    _s, _a, value = _resolve_flag(out_wb, sheet, flag_addr)
    rate = _rate_from(out_wb[sheet][rate_addr].value, value)
    # ...and the money still hangs off that rate cell. A rate of 0 is only worth anything if the
    # dollar row still multiplies by it and the TOTAL still sums the row.
    dollar = str(out_wb[sheet][dollar_addr].value)
    assert re.search(r"\*%s\b" % rate_addr, dollar), (
        "%s's tax dollar cell stopped multiplying by %s: %r" % (sheet, rate_addr, dollar))
    return rate


@pytest.mark.parametrize("sheet", PRICED_SHEETS)
def test_a_tax_exempt_job_charges_no_sales_tax_on_any_priced_sheet(exempt_wb, sheet):
    """The bug, stated as money, one case per priced layout.

    Rate 0 makes the row ``ROUNDUP(SUM(<base>)*0,0)`` = $0 whatever the base is, so the TOTAL is
    the same total with the sales-tax row at zero -- which is what "tax exempt" means. Before this
    change Leveling and the two literal gyp sheets came back 0.09475 here."""
    assert _sales_tax_rate(exempt_wb, sheet) == 0.0, (
        "%s still bills 9.475%% on a tax-exempt job" % sheet)


@pytest.mark.parametrize("sheet", PRICED_SHEETS)
def test_a_taxable_job_still_charges_sales_tax_on_every_priced_sheet(taxable_wb, sheet):
    """The other direction, and it is not a formality: the cheapest way to make the test above
    pass is to switch sales tax off, which would quietly under-bill every ordinary job."""
    assert _sales_tax_rate(taxable_wb, sheet) == 0.09475, (
        "%s stopped charging sales tax on a TAXABLE job" % sheet)


def test_the_totals_chain_from_the_sales_tax_row_is_intact(wb):
    """Zeroing the rate only reaches the customer if the TOTAL still sums the row it zeroes.

    Epoxy: D80 (sales tax) -> D82 (Total Taxes, =SUM(D80:D81)) -> D88 (TOTAL, includes D82). The
    equivalent chain is asserted on every layout, out of the workbook's own formula text, so
    "rate 0" above is a statement about the printed price and not just about a cell."""
    for sheet in PRICED_SHEETS:
        _rate_addr, dollar_addr, _flag = _tax_row(wb, sheet)
        col, row = re.match(r"([A-Z]+)(\d+)", dollar_addr).groups()
        subtotal = "%s%d" % (col, int(row) + 2)          # "Total Taxes", two rows down
        assert dollar_addr in str(wb[sheet][subtotal].value), (
            "%s's Total Taxes (%s) no longer sums its sales-tax row" % (sheet, subtotal))
        total = next((("%s%d" % (col, r)) for r in range(int(row) + 3, int(row) + 12)
                      if str(wb[sheet]["A%d" % r].value or "").strip().upper() == "TOTAL"), None)
        assert total, "%s has no TOTAL row under its taxes block" % sheet
        assert subtotal in str(wb[sheet][total].value), (
            "%s's TOTAL (%s) no longer includes its Total Taxes cell" % (sheet, total))


@pytest.mark.parametrize("copy_id", sorted(COPY_OF, key=lambda c: int(c[4:])))
def test_a_copied_tab_on_a_tax_exempt_job_charges_no_sales_tax(exempt_copies_wb, exempt_wb,
                                                               copy_id):
    """Kyle's actual report, one case per copyable source.

    A copy is the ordinary way to put a priced option in front of a customer, and
    ``_create_copied_tabs`` clones it from the PRISTINE template -- so a copy of Epoxy, Leveling,
    the gyp base or 'Gyp (FR)' arrives holding the template's literal 'Yes'. ``copyTab``'s edit
    replay deliberately skips A1:D10, and ``canonicalTarget`` redirects any edit there to the
    master, so neither the copy nor the estimator could reach the cell. It read "No" and billed
    9.475%.

    The copy's own cell_values entry is what the browser fan-out produces; the mirrors need none,
    because ``copy_worksheet`` keeps ``=Epoxy!B6`` pointing at Epoxy."""
    source = COPY_OF[copy_id]
    assert copy_id in exempt_copies_wb.sheetnames
    assert _sales_tax_rate(exempt_copies_wb, copy_id) == 0.0, (
        "a copy of %s bills 9.475%% on a tax-exempt job" % source)
    # ...and the source sheet is unaffected by the copy existing
    assert _sales_tax_rate(exempt_copies_wb, source) == 0.0
    assert _sales_tax_rate(exempt_wb, source) == 0.0


@pytest.mark.parametrize("copy_id", sorted(COPY_OF, key=lambda c: int(c[4:])))
def test_a_copied_tab_on_a_taxable_job_still_charges_sales_tax(taxable_copies_wb, copy_id):
    """The other direction on a copy: put the template's 'Yes' back and the rate has to return to
    9.475%. Without it the case above would pass on a "fix" that simply switched sales tax off for
    every copied tab -- which is the same size of error, pointed at Treadwell."""
    assert _sales_tax_rate(taxable_copies_wb, copy_id) == 0.09475, COPY_OF[copy_id]


def test_the_writer_never_invents_a_sheets_answer(wb, exempt_wb):
    """Written into the .xlsx and read back. Each sheet's OWN answer reaches the file only as the
    draft's own ``cell_values`` entry -- which the estimate screen writes when it splits a draft
    (sections 5-7). ``fill_estimate`` itself stamps nothing onto a mirror: a draft that was never
    split downloads exactly the template's references, as it always did, so the file cannot hold an
    answer the screen never showed."""
    out = exempt_wb
    for sheet, addr in (("Polish", "B6"), ("Seal", "B6"), ("Seal (+Jnts)", "B6"),
                        ("Epoxy blank", "B6"), ("Gyp (USG N12ULTRA)", "B8"),
                        ('Gyp (USG N25 1-4")', "B8"), ("Gyp (GWorx SC190)", "B8")):
        assert out[sheet][addr].value == wb[sheet][addr].value, (
            "%s!%s was forked into a literal" % (sheet, addr))
        assert out[sheet][addr].data_type == "f"


def test_the_answer_arrives_as_a_word_and_never_as_a_formula():
    """``_coerce``'s whitelist is why this fix stamps literals instead of writing mirrors.

    Handed ``='Gyp (USG 1-8")'!B8`` it returns an apostrophe-escaped TEXT literal: the whitelist
    regex reads the quoted sheet-name prefix as a call to an un-whitelisted function ``Gyp``.
    HyperFormula would still get the working formula, so the SCREEN and the .docx would say
    tax-free while the downloaded .xlsx charged 9.475% -- three artefacts, two answers. Pinned
    here so nobody reintroduces it, along with the two forms that DO survive."""
    import estimate_writer as ew

    for word in ("Yes", "No"):
        assert ew._coerce(word) == word
    assert ew._coerce("=Epoxy!B6") == "=Epoxy!B6"
    assert ew._coerce("=Epoxy!D6") == "=Epoxy!D6"
    mangled = ew._coerce("='Gyp (USG 1-8\")'!B8")
    assert not str(mangled).startswith("='Gyp"), (
        "_coerce now passes quoted-sheet-name formulas through -- mirrors became an option "
        "again, but check info_sheet_writer._flag before taking it")


# ── 3. the hand-off sheet accounting reads ───────────────────────────────────


def test_the_info_sheet_still_reads_the_answer_as_yes_or_no():
    """``info_sheet_writer._flag`` is the second reason this fix writes literals.

    It expects a word. A mirror string is non-empty and not truthy, so ``_yn`` would return 'N'
    and B66 would print **"Tax Exempt? Y" on every gypsum job** -- plus the request-a-certificate
    instruction to Foundation, which is verbatim the failure that function exists to prevent,
    sign-flipped. The fan-out's own output is fed in here, not a hand-typed 'No'."""
    import info_sheet_writer as isw

    gyp_base = 'Gyp (USG 1-8")'
    draft = lambda cv: {"owner_email": "kyle@wetreadwell.com",
                        "data": {"project_name": "Westport Commons", "work_type": "gyp",
                                 "base_tab_id": gyp_base, "cell_values": cv}}
    exempt = isw.build_prefill(draft({"Epoxy!B6": "No", "Leveling!B6": "No",
                                      gyp_base + "!B8": "No", "Gyp (FR)!B8": "No"}))
    assert exempt["B66"] == "Y", "a tax-exempt gyp job must print Tax Exempt = Y"
    taxed = isw.build_prefill(draft({"Epoxy!B6": "Yes", "Leveling!B6": "Yes",
                                     gyp_base + "!B8": "Yes", "Gyp (FR)!B8": "Yes"}))
    assert taxed["B66"] == "N", (
        "a TAXABLE gyp job would tell Foundation to chase an exemption certificate")


def test_a_mirror_formula_in_the_gyp_flag_cell_would_be_read_as_taxable():
    """The counterexample that makes the test above bite.

    This is what the rejected mirror-formula fix would have put in that cell. Asserted so the
    consequence is on the record: it does not raise, it does not look wrong, it just prints the
    opposite answer on the sheet accounting works from."""
    import info_sheet_writer as isw

    gyp_base = 'Gyp (USG 1-8")'
    d = {"owner_email": "kyle@wetreadwell.com",
         "data": {"work_type": "gyp", "base_tab_id": gyp_base,
                  "cell_values": {gyp_base + "!B8": "='%s'!B8" % gyp_base}}}
    assert isw.build_prefill(d)["B66"] == "Y", (
        "a mirror string no longer reads as 'not taxable' -- if _yn changed, re-check whether "
        "mirrors are safe again")


# ── 4. the intake, which is where a base tab's answer comes from ─────────────


@needs_node
def test_the_intake_writes_the_answer_to_all_four_literal_cells(wb):
    """``frontend/js/index.js`` wrote ``Epoxy!B6`` alone, which is the whole of the base-tab half
    of this bug. The list is checked against the workbook rather than against itself."""
    import estimate_writer as ew

    src = (FRONTEND / "js" / "index.js").read_text(encoding="utf-8")
    m = re.search(r'\{ key: "taxable".*?cells: \[(.*?)\]', src, re.S)
    assert m, "the taxable condition moved -- re-derive this test"
    cells = [c.strip().strip("'\"") for c in m.group(1).split(",")]
    assert cells[0] == "Epoxy!B6", "hydrateConditions reads cells[0] to paint the switch"
    assert set(cells) == {"%s!%s" % (s, a) for s, a in ew.TAXABLE_FLAG_CELLS.items()}
    for c in cells:
        sheet, addr = c.split("!")
        v = wb[sheet][addr].value
        assert isinstance(v, str) and not v.startswith("="), (
            "the intake writes %s, which is a formula in the workbook" % c)


# ── 5. the browser half, executed ────────────────────────────────────────────
#
# Everything below runs the SHIPPED browser code (taxable-flag-harness.js) and, where a claim is
# about money or wording, hands what it produced to the real ``fill_estimate`` and the real
# document renderer. Hanz, 2026-09-30: every flag-block sheet keeps its own Taxable? and Remodel
# Tax?; a new project starts them at the intake's answers; a copy starts at its source's; an
# existing draft opens exactly as it did; an option's price and wording come off its own sheet.

GYP_BASE = 'Gyp (USG 1-8")'
N25 = 'Gyp (USG N25 1-4")'


def _flag_cells(sheet_or_layout):
    import estimate_writer as ew
    return ew.FLAG_BLOCK_CELLS[sheet_or_layout]


def _layout(sheet, copies):
    """A copy's template layout, through its source chain (as the browser and the writer walk it)."""
    by_id = {c["id"]: c["source"] for c in (copies or [])}
    guard = 0
    while sheet in by_id and guard < 20:
        sheet, guard = by_id[sheet], guard + 1
    return sheet


def _fill_cv(cell_values, tab_copies=None, tab_structs=None):
    """The downloaded workbook for a draft, through the real writer, formulas not values."""
    import estimate_writer as ew
    from openpyxl import load_workbook
    data = ew.fill_estimate({}, cell_values=dict(cell_values or {}), tab_copies=tab_copies,
                            tab_structs=tab_structs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return load_workbook(io.BytesIO(data), data_only=False)


def _cell_rate(out_wb, sheet, addr, _depth=0):
    """Evaluate one tax RATE cell of a generated workbook: a number, Kyle's IF on a flag of ITS OWN
    sheet (followed through that flag's mirror chain), or a mirror of another sheet's rate cell --
    which is exactly how 'Seal (+Jnts)'!B75 = =Seal!B75 prices remodel off SEAL's toggle."""
    assert _depth < 8, "rate mirror loop at %s!%s" % (sheet, addr)
    v = out_wb[sheet][addr].value
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    m = _MIRROR.match(s)
    if m:
        return _cell_rate(out_wb, m.group(1) or m.group(2), m.group(3) + m.group(4), _depth + 1)
    m = _RATE.match(s)
    assert m, "%s!%s is a rate formula this walk does not understand: %r" % (sheet, addr, v)
    col, row, needle, when_true, when_false = m.groups()
    _s, _a, value = _resolve_flag(out_wb, sheet, col + row)
    hit = str(value or "").strip().lower() == needle.strip().lower()
    return float(when_true if hit else when_false)


def _rates(out_wb, sheet):
    """(sales-tax rate, remodel-tax rate) a sheet of the generated workbook charges. The remodel
    rate cell is the row under Sales Tax on every layout (Epoxy B81, Polish/Seal B75, gyp B80 …);
    the sales-tax walk also re-checks that the dollar row still multiplies by its rate."""
    rate_addr, _dollar, _flag = _tax_row(out_wb, sheet)
    remodel_addr = "B%d" % (int(rate_addr[1:]) + 1)
    return (_sales_tax_rate(out_wb, sheet), _cell_rate(out_wb, sheet, remodel_addr))


@needs_node
def test_the_writer_and_the_screen_agree_on_which_sheets_have_a_flag_block(result):
    """One list of flag-block sheets and addresses, on both sides of the wire: the browser splits
    exactly the sheets the writer gives a picker to, at the same cells."""
    import estimate_writer as ew
    assert set(result["flagLayouts"]) == set(ew.FLAG_BLOCK_CELLS)
    for sheet, (t_addr, r_addr) in ew.FLAG_BLOCK_CELLS.items():
        key = "gyp" if sheet.startswith("Gyp") else "epoxy"
        assert (result["flagAddr"]["taxable"][key], result["flagAddr"]["remodel"][key]) == (t_addr, r_addr)
    assert set(ew.FLAG_BLOCK_CELLS) == set(PRICED_SHEETS)


@needs_node
def test_the_template_map_the_split_reads_matches_the_workbook(result, wb):
    """`JOB_FLAG_TEMPLATE` is how the split knows what a sheet holds without the sheet in the engine
    (init() defers 'Epoxy blank' and Leveling). Checked cell for cell against Kyle's file: a literal
    is the same word, a mirror names the same sheet AND that sheet's own flag cell."""
    import estimate_writer as ew
    t = result["template"]
    for flag, idx in (("taxable", 0), ("remodel", 1)):
        assert set(t[flag]) == set(ew.FLAG_BLOCK_CELLS), flag
        for sheet in ew.FLAG_BLOCK_CELLS:
            addr = ew.FLAG_BLOCK_CELLS[sheet][idx]
            v, entry = wb[sheet][addr].value, t[flag][sheet]
            if entry.startswith("="):
                m = _MIRROR.match(str(v).strip())
                assert m, "%s!%s is %r, but the map says it mirrors %s" % (sheet, addr, v, entry)
                target = m.group(1) or m.group(2)
                assert target == entry[1:], (sheet, flag, v, entry)
                assert m.group(3) + m.group(4) == ew.FLAG_BLOCK_CELLS[target][idx], (sheet, flag, v)
            else:
                assert v == entry, "%s!%s is %r, the map says %r" % (sheet, addr, v, entry)


@needs_node
def test_the_legacy_fan_out_a_never_split_draft_gets_once(result):
    """The one-answer-per-job fan-out, unchanged, because it is what an existing draft opened with
    until now: four literal cells for Taxable (never a mirror), one for Remodel. init() runs it
    exactly once on a draft that was never split, then freezes the result per sheet."""
    t = result["legacyTargets"]
    assert [tuple(x) for x in t["taxable"]] == [("Epoxy", "B6"), ("Leveling", "B6"),
                                                (GYP_BASE, "B8"), ("Gyp (FR)", "B8")]
    assert [tuple(x) for x in t["remodel"]] == [("Epoxy", "D6")]
    assert result["legacyFanout"] == {"Epoxy!B6": "No", "Leveling!B6": "No",
                                      GYP_BASE + "!B8": "No", "Gyp (FR)!B8": "No"}


@needs_node
def test_a_new_project_starts_every_sheet_with_the_intake_answers(result):
    """The intake said exempt and remodel. Every one of the eleven flag-block sheets -- the gyp
    variants at B8/D8, not B6 (Miles Away) -- now holds those two answers as its own literal, and
    the second open changes nothing, so it saves nothing."""
    p = result["newProject"]
    for sheet in PRICED_SHEETS:
        assert p["own"][sheet] == {"taxable": "No", "remodel": "Yes"}, sheet
        t_addr, r_addr = _flag_cells(sheet)
        assert p["written"]["%s!%s" % (sheet, t_addr)] == "No"
        assert p["written"]["%s!%s" % (sheet, r_addr)] == "Yes"
        assert p["engine"][sheet] == {"taxable": "No", "remodel": "Yes"}, sheet
    assert p["gypMilesAwayUntouched"] is True
    assert p["marker"] is True and p["first"] > 0
    assert p["second"] == 0 and p["unchangedBySecondOpen"] is True
    # nobody touched the intake: its defaults are the template's (Taxable on, Remodel off)
    u = result["newProjectUntouched"]
    assert u["first"] > 0 and u["second"] == 0
    assert all(v == {"taxable": "Yes", "remodel": "No"} for v in u["own"].values()), u["own"]
    # the two sheets init() leaves out of the engine get theirs off the template map
    d = result["newProjectDeferred"]
    assert d["leveling"] == d["blank"] == {"taxable": "No", "remodel": "Yes"}


@needs_node
def test_an_existing_draft_opens_with_the_same_answers_and_saves_once(result):
    """A draft saved by the job-wide build: the four literals and the literal-layout copies already
    carry the answer, everything else follows by formula (a copy of a copy among them). Opened, it
    computes the SAME two answers on every sheet -- and so the same tax, and the same proposal flags
    -- and every sheet now owns them. The first open saves once; the second saves nothing."""
    e = result["existing"]
    assert e["before"]["priced"] == e["after"]["priced"]
    assert e["before"]["proposal"] == e["after"]["proposal"]
    ids = set(PRICED_SHEETS) | {c["id"] for c in e["copies"]}
    assert set(e["own"]) == ids
    for sid, own in e["own"].items():
        assert own["taxable"] in ("Yes", "No") and own["remodel"] in ("Yes", "No"), (sid, own)
        # ...and the word it owns is the answer it priced with before
        pa = e["before"]["priced"][sid]
        assert (own["taxable"] == "Yes", own["remodel"] == "Yes") == (pa["taxable"], pa["remodel"]), sid
    assert e["marker"] is True
    assert e["savesOnFirst"] == 1 and e["savesOnSecond"] == 0 and e["second"] == 0
    assert e["untouchedCellKept"] == 5200


@pytest.fixture(scope="module")
def existing_files(result):
    e = result["existing"]
    return _fill_cv(e["cvBefore"], e["copies"]), _fill_cv(e["cvAfter"], e["copies"])


@needs_node
def test_an_existing_draft_prices_the_same_in_the_downloaded_workbook(result, existing_files):
    """The same claim as money, off the file the estimator downloads: the draft as it was saved and
    the draft as the first open saves it charge the same sales-tax and remodel-tax RATE on every
    priced sheet and every copy -- including 'Seal (+Jnts)', whose remodel rate stops being Seal's
    mirror and becomes its own IF on its own toggle at the same number."""
    before, after = existing_files
    e = result["existing"]
    for sid in list(PRICED_SHEETS) + [c["id"] for c in e["copies"]]:
        assert _rates(before, sid) == _rates(after, sid), sid
    assert str(before["Seal (+Jnts)"]["B75"].value) == "=Seal!B75"
    assert after["Seal (+Jnts)"]["B75"].value == '=IF(D6="yes",0.1,0)'


@needs_node
def test_the_downloaded_xlsx_carries_each_sheets_own_answer_with_a_picker(result, existing_files):
    """Every flag-block sheet and every copy: its two cells are a literal Yes/No -- the one the
    screen holds -- and carry a Yes/No list, so the estimator can still change either in Excel.
    Kyle's own pickers are x14 extension validations that openpyxl drops, so this is the writer's."""
    _before, after = existing_files
    e = result["existing"]
    for sid, own in e["own"].items():
        t_addr, r_addr = _flag_cells(_layout(sid, e["copies"]))
        for flag, addr in (("taxable", t_addr), ("remodel", r_addr)):
            cell = after[sid][addr]
            assert cell.data_type == "s" and cell.value == own[flag], (sid, addr, cell.value)
            pickers = [dv for dv in after[sid].data_validations.dataValidation
                       if addr in str(dv.sqref).split() and dv.type == "list"]
            assert pickers and pickers[0].formula1 == '"Yes,No"', (sid, addr)
            assert cell.protection.locked is False, "%s!%s is locked in the download" % (sid, addr)


@needs_node
def test_a_draft_from_before_the_job_wide_fix_opens_as_it_did_and_is_then_frozen(result):
    """The intake wrote Epoxy!B6 alone and a copy was made. The job-wide build healed that on open
    (the copy and the four literals all said No), so that is what this draft opens with -- once.
    A draft that is already split is never healed again: its Leveling keeps its own Yes even though
    Epoxy says No, which the fan-out would have overwritten."""
    for sid, own in result["legacyUnhealed"].items():
        assert own["taxable"] == "No", sid
    assert result["legacyUnhealed"]["Copy1"] == {"taxable": "No", "remodel": "No"}
    assert result["splitNotReHealed"]["leveling"] == "Yes"


@needs_node
def test_each_sheet_keeps_its_own_answer_when_another_changes(result):
    """THE RULE, through the grid's real edit listener. An option (Polish) says exempt: that
    keystroke reaches Polish and nothing else -- not Seal, whose template cell mirrors Polish's,
    and not Polish's own copy. The base flips Taxable and back and turns Remodel on: no option
    moves. A copy and a mirroring gyp variant answer for themselves, the variant at B8/D8 and not
    through the gyp base. Retyping the original answer keeps the literal (a deleted key would fall
    back to the template's mirror and start following another sheet again)."""
    i = result["independent"]
    assert i["optionCalls"] == [["Polish", "B6", "No"]]
    for sid, own in i["afterOption"].items():
        want = {"taxable": "No", "remodel": "No"} if sid == "Polish" else {"taxable": "Yes", "remodel": "No"}
        assert own == want, (sid, own)
    assert i["baseCalls"] == [["Epoxy", "B6", "No"], ["Epoxy", "B6", "Yes"], ["Epoxy", "D6", "Yes"]]
    assert i["otherCalls"] == [["Copy1", "D6", "Yes"], [N25, "B8", "No"], [N25, "D8", "Yes"]]
    f = i["final"]
    assert f["Epoxy"] == {"taxable": "Yes", "remodel": "Yes"}
    assert f["Polish"] == {"taxable": "No", "remodel": "No"}
    assert f["Seal"] == {"taxable": "Yes", "remodel": "No"}
    assert f["Copy1"] == {"taxable": "Yes", "remodel": "Yes"}
    assert f[N25] == {"taxable": "No", "remodel": "Yes"}
    assert f[GYP_BASE] == {"taxable": "Yes", "remodel": "No"}
    for sid in f:
        assert i["engine"][sid] == f[sid], "%s: the engine disagrees with the draft" % sid
    assert i["epoxyKeptAfterRevert"] == "Yes" and i["refreshed"] is True
    # the picker's blank is stamped as the word that prices the same, never left blank
    assert i["blank"] == {"taxable": "Yes", "remodel": "No"}
    p = i["proposal"]
    assert p["Epoxy"] == {"taxable": True, "remodel_on": True}
    assert p["Polish"] == {"taxable": False, "remodel_on": False}
    assert p["Copy1"] == {"taxable": True, "remodel_on": True}
    assert p["Seal"] == {"taxable": True, "remodel_on": False}


@needs_node
def test_changing_the_base_moves_no_option_in_the_downloaded_workbook(result):
    """The same, in the .xlsx. Polish exempt, the base taxed: Polish charges 0 and the base 9.475%.
    Seal -- whose template Taxable? is `=Polish!B6` -- still charges 9.475%, because it kept its own
    Yes; the base's Remodel Yes reaches the base and no option."""
    i = result["independent"]
    out = _fill_cv(i["cellValues"], i["copies"])
    assert _rates(out, "Polish") == (0.0, 0.0)
    assert _rates(out, "Epoxy") == (0.09475, 0.1)
    assert _rates(out, "Seal") == (0.09475, 0.0)
    assert _rates(out, "Copy1") == (0.09475, 0.1)
    assert _rates(out, N25) == (0.0, 0.1)
    assert _rates(out, GYP_BASE) == (0.09475, 0.0)


def _option_payload(flags, cell_values, copies):
    """A payload shaped the way the page ships one: the base and three options, each room's figures
    its own and each room's two flags exactly what snapshotLumpSumsToState read off its tab."""
    from test_price_block_reconciles import _values
    base_f = flags["Epoxy"]
    values = _values(10000.0, 950.0, 0.0, base_f["taxable"], base_f["remodel_on"], "ONE_LINE")
    values["base_bid_formatted"] = ""

    def opt(tid, desc, total, sales, remodel):
        f = flags[tid]
        return {"id": tid, "name": tid, "is_base": False, "show": True, "price_mode": "total",
                "option_desc": desc, "system_desc": desc, "base_total": 10000,
                "bid": {"total": total, "sales_tax": sales, "remodel": remodel,
                        "taxable": f["taxable"], "remodel_on": f["remodel_on"]}}
    rooms = [{"id": "Epoxy", "name": "Epoxy", "is_base": True,
              "bid": {"total": 10000, "sales_tax": 950, "remodel": 0,
                      "taxable": base_f["taxable"], "remodel_on": base_f["remodel_on"]}},
             opt("Polish", "Polished Concrete", 4200, 0, 0),
             opt("Seal", "Sealed Concrete", 1476, 0, 90),
             opt("Copy1", "Epoxy flooring", 9050, 0, 0)]
    return {"work_type": "epoxy", "audience": "Direct", "values": values, "rooms": rooms,
            "cell_values": cell_values, "tab_copies": copies}


@needs_node
def test_a_taxed_base_with_an_exempt_and_a_remodel_only_option_end_to_end(result):
    """Hanz's two sentences, from the sheet to the files. The base sheet says Taxable Yes; the
    Polish sheet says No to both; Seal says No / Yes; a copy of the base says No. One payload -- the
    cell_values and the per-tab flags the real browser code produced -- through the real renderer:

      * the .xlsx: Polish and the copy charge NO sales tax, Seal only remodel tax, the base 9.475%;
      * the .docx: each option ONE line, worded by its own sheet -- "(tax exempt)" and "(Remodel Tax
        INCLUDED)" -- while the base line keeps "(material sales tax INCLUDED)".

    Mutation: any one sheet's answer following the base instead of its own sheet -- the xlsx rate
    and the printed wording both flip."""
    import docx as _docx
    from starlette.requests import Request
    import main
    from test_price_block_reconciles import _price_rows
    s = result["optionShapes"]
    f = s["flags"]
    assert f["Epoxy"] == {"taxable": True, "remodel_on": False}
    assert f["Polish"] == {"taxable": False, "remodel_on": False}
    assert f["Seal"] == {"taxable": False, "remodel_on": True}
    assert f["Copy1"] == {"taxable": False, "remodel_on": False}
    req = Request({"type": "http", "method": "POST", "path": "/t", "headers": [], "query_string": b""})
    docs = main._render_documents(_option_payload(f, s["cellValues"], s["copies"]), req,
                                  want_estimate=True)
    from openpyxl import load_workbook
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xlsx = load_workbook(io.BytesIO(docs["xlsx"]["content"]), data_only=False)
    assert _rates(xlsx, "Epoxy") == (0.09475, 0.0)
    assert _rates(xlsx, "Polish") == (0.0, 0.0)
    assert _rates(xlsx, "Seal") == (0.0, 0.1)
    assert _rates(xlsx, "Copy1") == (0.0, 0.0)
    rows = _price_rows(docs["docx"]["content"])
    assert rows["options"] == [
        "$4,200 – Polished Concrete as described above (tax exempt)",
        "$1,476 – Sealed Concrete as described above (Remodel Tax INCLUDED)",
        "$9,050 – Epoxy flooring as described above (tax exempt)",
    ], rows["options"]
    assert rows["base_line"].endswith("(material sales tax INCLUDED)"), rows["base_line"]
    assert _usd(rows["base_line"]) == 10000.0


def _usd(s):
    m = re.search(r"\$([\d,]+(?:\.\d+)?)", str(s))
    assert m, s
    return float(m.group(1).replace(",", ""))


@needs_node
def test_a_new_copy_starts_with_its_sources_answers_then_keeps_its_own(result):
    """One copy per flag-block layout, of a source that answers DIFFERENTLY from the template and
    from Epoxy (exempt, remodel on). The copy gets the source's two answers as its own literal, in
    the engine too; changing the source afterwards leaves the copy alone; Epoxy is untouched by all
    of it; the copy's cache survives; the remodel rate is still stamped. A gyp copy is written at
    B8/D8, never at B6 (Miles Away)."""
    for src, c in result["copies"].items():
        assert c["copyId"], src
        assert (c["copyTaxable"], c["copyRemodel"]) == ("No", "Yes"), src
        assert c["engine"] == {"t": "No", "r": "Yes"}, src
        assert c["copyTaxableAfterSourceChanged"] == "No", "%s: the copy followed its source" % src
        if c["epoxyUntouched"] is not None:
            assert c["epoxyUntouched"] == ["Yes", "No"], src
        assert c["cacheAlive"] is True and c["remodelRateApplied"] == 1, src
        assert c["gypMilesAwayUntouched"] is True, src
    assert set(result["copies"]) == set(PRICED_SHEETS)
    assert result["copyChain"] == {"c1": "No", "c2": "No", "c2Engine": "No"}


@needs_node
def test_the_autofill_sets_the_base_and_moves_no_option(result):
    """The AI keys its seven flags to `Epoxy!…` whatever the work type. On a split draft the two tax
    answers are the BASE bid's: a polish job's land on Polish (Epoxy, an option there, keeps its
    own), a gyp job's on the gyp base (not 'Gyp (FR)'), a combo's on both halves of its combined
    base and on no option. A never-split draft still gets the old fan-out."""
    a = result["autofill"]
    assert a["polish"]["bases"] == ["Polish"]
    for sid, own in a["polish"]["own"].items():
        want = {"taxable": "No", "remodel": "Yes"} if sid == "Polish" else {"taxable": "Yes", "remodel": "No"}
        assert own == want, (sid, own)
    assert a["gyp"] == {"base": "No", "fr": "Yes", "epoxy": "Yes"}
    assert a["combo"] == {"bases": ["Epoxy", "Polish"], "epoxy": "No", "polish": "No", "seal": "Yes"}
    assert a["unsplitFansOut"] == "No"


@needs_node
def test_seal_with_joints_prices_remodel_off_its_own_toggle(result):
    """'Seal (+Jnts)'!B75, its remodel RATE, is `=Seal!B75` in the template, so its remodel tax was
    SEAL's whatever its own Remodel Tax? said. The split gives it the same IF on its own D6, at the
    rate Seal's cell holds -- Kyle's 0.1 or the county's -- and its copies too. A rate somebody typed
    as a bare number reads no toggle on either sheet and is left alone; an already split draft is
    not touched again."""
    s = result["sealJoints"]
    assert s["template"] == '=IF(D6="yes",0.1,0)' and s["copy"] == '=IF(D6="yes",0.1,0)'
    assert s["templateSealUntouched"] is True
    assert s["typedNumberLeftAlone"] is True
    assert s["county"] == '=IF(D6="yes",0.07975,0)'
    assert s["notOnASplitDraft"] is True


@needs_node
def test_the_joints_sheets_own_toggle_moves_its_price_in_the_workbook():
    """The same, as money in the file, with the counterexample beside it. Seal says Remodel No,
    'Seal (+Jnts)' says Yes. With the fork its remodel rate is 0.1; a copy of it left on the
    template's `=Seal!B75` charges Seal's 0 -- the price its own box would have contradicted.

    Also in this file: a copy with two rows inserted above its flag block gets its picker at the
    MOVED cells, B8/D8."""
    cv = {"Seal!D6": "No", "Seal (+Jnts)!D6": "Yes", "Seal (+Jnts)!B75": '=IF(D6="yes",0.1,0)',
          "Copy1!D6": "Yes", "Copy2!B8": "No", "Copy2!D8": "No"}
    out = _fill_cv(cv, [{"id": "Copy1", "source": "Seal (+Jnts)"}, {"id": "Copy2", "source": "Epoxy"}],
                   [{"sheet": "Copy2", "kind": "insert_rows", "at": 2, "count": 2}])
    assert _rates(out, "Seal")[1] == 0.0
    assert _rates(out, "Seal (+Jnts)")[1] == 0.1
    assert _rates(out, "Copy1")[1] == 0.0, "the mirror stopped pricing off Seal -- re-check the fork"
    moved = [a for dv in out["Copy2"].data_validations.dataValidation
             if dv.formula1 == '"Yes,No"' for a in str(dv.sqref).split()]
    assert set(moved) >= {"B8", "D8"}, moved
    assert out["Copy2"]["B8"].value == "No"


@needs_node
def test_each_tab_reports_where_its_own_two_cells_are(result):
    """`priced_tabs[].flag_cells`, which the intake reads to find the BASE's two cells on a split
    draft: through the layout and the structural edits, gyp one row lower, nothing for a sheet with
    no flag block."""
    c = result["flagCells"]
    assert c["epoxy"] == {"taxable": "Epoxy!B6", "remodel": "Epoxy!D6"}
    assert c["gyp"] == {"taxable": GYP_BASE + "!B8", "remodel": GYP_BASE + "!D8"}
    assert c["movedCopy"] == {"taxable": "Copy1!B8", "remodel": "Copy1!D8"}
    assert c["gypCopy"] == {"taxable": "Copy2!B8", "remodel": "Copy2!D8"}
    assert c["takeoff"] == {}


@needs_node
def test_an_ordinary_cell_edit_is_untouched_by_any_of_this(result):
    """Only the two flag addresses per layout are special -- not the cells beside them in the same
    block. ``Gyp!B6`` is *Miles Away*, and a "B6 is the tax flag" rule would have turned a mileage
    into a tax answer."""
    assert result["ordinaryEdits"] == {"Epoxy!E20": "5000", "Epoxy!B4": "No", "Epoxy!B5": "Yes",
                                       "Epoxy!D5": "Yes", GYP_BASE + "!B6": "12"}
    k = result["kinds"]
    assert k["epoxyB6"] == "taxable" and k["epoxyD6"] == "remodel"
    assert k["gypB8"] == "taxable" and k["gypD8"] == "remodel"
    assert k["gypB6"] is None, "Miles Away was mistaken for the Taxable flag"
    assert k["epoxyB4"] is None, "Local? is Issue 5, not this change"
    assert k["takeoffB6"] is None, "a sheet with no flag block must never match"
    assert k["copyOfGypB8"] == ["taxable", None], "a copy resolves through its LAYOUT"


@needs_node
def test_the_project_info_block_is_shared_except_the_two_flags(result):
    """The A1:D10 redirect exists to share project name / bid date / address across every tab, and
    it is right about those -- a copy's B1 still lands on Epoxy, a gyp variant's B2 (and its Miles
    Away) on the gyp base. The two flags are the one exception, on every layout: they stay on the
    sheet they were typed on."""
    p = result["projectInfo"]
    assert p["b1"] == {"sheet": "Epoxy", "addr": "B1"}
    assert p["b3"] == {"sheet": "Epoxy", "addr": "B3"}
    assert p["gypB2"] == {"sheet": GYP_BASE, "addr": "B2"}
    assert p["gypVariantB6"] == {"sheet": GYP_BASE, "addr": "B6"}
    assert p["copyB6"] == {"sheet": "Copy1", "addr": "B6"}
    assert p["polishB6"] == {"sheet": "Polish", "addr": "B6"}
    assert p["polishD6Key"] == "Polish!D6"
    assert p["gypVariantB8"] == {"sheet": "Gyp (USG N12ULTRA)", "addr": "B8"}
    assert p["gypVariantD8"] == {"sheet": "Gyp (USG N12ULTRA)", "addr": "D8"}
    assert p["typedB1"] == {"onMaster": "New Name", "forkedOntoTheCopy": False}


@needs_node
def test_a_structurally_edited_tab_is_split_at_its_real_address_or_not_at_all(result):
    """Rows inserted above the block move the flag; deleting its row removes it. The split goes
    through ``txAddr`` and skips a deleted cell rather than writing a word at a stale address."""
    s = result["structural"]
    assert s["movedWritten"] == "No" and s["movedRemodel"] == "No"
    assert s["movedNotAtStale"] is True
    assert s["goneWrittenAnywhere"] == []


@needs_node
def test_the_legacy_two_store_rule_decides_what_a_never_split_draft_opens_with(result):
    """What the job-wide build did on open, and so what these drafts open with, once. A gyp job whose
    estimator typed the real answer into the gyp tab (the workaround handed out for the original bug)
    opens exempt everywhere, not taxed by the intake's stale epoxy answer. A remodel toggle an older
    build forked onto the gyp base's D8 opens in step with the master. Both then freeze per sheet."""
    s = result["legacyStores"]
    assert all(v["taxable"] == "No" for v in s["gypJob"].values()), s["gypJob"]
    assert all(v["remodel"] == "No" for v in s["forked"].values()), s["forked"]
    assert s["blankAnswer"] is None


@needs_node
def test_the_proposal_reads_each_tabs_own_two_answers(result):
    """Hanz, 2026-09-25: "Remodel Tax should be triggered by remodel tax in the estimate form. Taxable
    is where base bid and other options are taxable or not." snapshotLumpSumsToState hands the
    proposal each priced tab's Taxable? and Remodel Tax? answers -- read off that tab's OWN flag
    cells, the same comparisons the sheet's tax cells make (sales tax unless Taxable? says "no";
    remodel tax only when Remodel Tax? says "yes", however it is spelled), a copy answering for
    itself and a gyp tab from its lower row. A tab with no flag block answers nothing."""
    f = result["proposalFlags"]
    assert f["shipped"] == {"taxable": True, "remodel_on": False}
    assert f["flipped"] == {"taxable": False, "remodel_on": True}
    assert f["copy"] == {"taxable": False, "remodel_on": False}
    assert f["copySource"] == {"taxable": True, "remodel_on": False}
    assert f["gyp"] == {"taxable": False, "remodel_on": True}
    assert f["noBlock"] == {}


def test_the_info_sheet_reads_the_base_tabs_own_answer():
    """Since every sheet keeps its own, Epoxy!B6 is the EPOXY sheet's answer -- on a polish job an
    option's. The hand-off sheet reads the base's, which the estimate screen snapshots off the base
    tab's own cells as proposal_taxable / proposal_remodel_on. Without them it falls back to the
    cells, as before, and on this draft that fallback would tell accounting the job is taxed."""
    import info_sheet_writer as isw
    cv = {"Epoxy!B6": "Yes", "Epoxy!D6": "No", "Polish!B6": "No", "Polish!D6": "Yes"}
    d = lambda extra: {"owner_email": "kyle@wetreadwell.com",
                       "data": dict({"project_name": "Westport Commons", "work_type": "polish",
                                     "base_tab_id": "Polish", "cell_values": cv}, **extra)}
    pf = isw.build_prefill(d({"proposal_taxable": False, "proposal_remodel_on": True}))
    assert pf["B66"] == "Y" and pf["B67"] == "Y"
    old = isw.build_prefill(d({}))
    assert old["B66"] == "N" and old["B67"] == "N", "the counterexample no longer reads Epoxy"


def test_every_flag_block_sheets_two_cells_are_an_editable_yes_no_on_screen():
    """The estimator changes an OPTION's answer on that option's own sheet, so every flag-block
    sheet's two cells have to be a Yes/No picker on screen (the grid builds its <select> from the
    sheet's dropdowns; a copy uses its source's) and unlocked -- in neither the screen's lock list
    nor the download's. Read off the real sheet payload and the real lock maps."""
    import estimate_writer as ew
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    block = src[src.index("const LOCKED_CELLS = {"):]
    block = block[:block.index("};")]
    screen = {m.group(1): set(re.findall(r'"([A-Z]+\d+)"', m.group(2)))
              for m in re.finditer(r'"([^"]+)":\s*\[([^\]]*)\]', block)}
    gyp_locked = set(re.findall(r'"([A-Z]+\d+)"', re.search(r"const GYP_LOCKED = \[([^\]]*)\]", src).group(1)))
    for sheet, addrs in ew.FLAG_BLOCK_CELLS.items():
        grid = ew.read_sheet_grid(sheet)
        on_screen = gyp_locked if sheet.startswith("Gyp") else screen.get(sheet, set())
        in_file = set(ew._lock_layout_for(sheet) or [])
        for a in addrs:
            assert grid["dropdowns"].get(a) == ["Yes", "No"], (sheet, a, grid["dropdowns"].get(a))
            assert a not in on_screen, "%s!%s is locked on screen" % (sheet, a)
            assert a not in in_file, "%s!%s is locked in the download" % (sheet, a)


def test_a_sheets_own_answer_in_the_draft_beats_the_job_answer_in_the_file():
    """``fill_estimate``'s legacy step 1.4 stamps ``values["taxable"]`` onto the four literal sheets.
    The draft's own ``cell_values`` land after it (step 2), so a sheet's own answer is the one the
    downloaded file prices with: Leveling and 'Gyp (FR)' exempt on a job whose values say taxable."""
    import estimate_writer as ew
    from openpyxl import load_workbook
    data = ew.fill_estimate({"taxable": "Yes"},
                            cell_values={"Leveling!B6": "No", "Gyp (FR)!B8": "No"})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = load_workbook(io.BytesIO(data), data_only=False)
    assert _rates(out, "Leveling")[0] == 0.0
    assert _rates(out, "Gyp (FR)")[0] == 0.0
    assert _rates(out, "Epoxy")[0] == 0.09475
    assert _rates(out, GYP_BASE)[0] == 0.09475


@needs_node
def test_the_autofill_click_puts_the_tax_answers_on_the_base_and_nothing_on_epoxy(result):
    """The shipped click handler, network and banner stubbed. On a split polish job the AI's two tax
    answers (keyed `Epoxy!B6` / `Epoxy!D6`, as it always keys them) land on POLISH, the base; Epoxy --
    an option on this job -- keeps its own; the AI's other flags still land where they always did,
    and the banner still reports the answer."""
    a = result["autofillClick"]
    assert a["bannerKind"] == "success", a["banner"]
    assert a["polish"] == {"taxable": "No", "remodel": "Yes"}
    assert a["epoxy"] == {"taxable": "Yes", "remodel": "No"}
    assert a["epoxyB4"] == "No"
    assert "Taxable: <b>No</b>" in a["banner"]


# ── 6. the call sites this harness cannot reach ─────────────────────────────
#
# `init()` is a 120-line async function that fetches before it gets here, and the autofill call
# site is an anonymous async click handler wrapped round a fetch. So these assert the ORDER out of
# the shipped source: where the call sits is the whole of what can go wrong with it.


def test_the_split_runs_after_the_copies_exist_and_before_the_first_paint():
    """The split has to see the whole bid: run before the copied tabs are rehydrated and it never
    reaches a copy; run after `showSheet` and the first paint shows the old answer. And the save
    comes after, because `/api/generate` fills the workbook from the STORED draft."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    body = src[src.index("async function init()"):src.index("\nfunction renderTabs()")]
    replay = body.index("// Apply saved overrides")
    split = body.index("_flagsHealed += ownJobFlags();")
    legacy = body.index("_flagsHealed += applyJobFlags();")
    paint = body.index("showSheet(initialSheet)")
    save = body.index("if (_flagsHealed")
    assert "persistTabState()" in body[save:save + 80], body[save:save + 80]
    assert replay < legacy < split < paint < save, (replay, legacy, split, paint, save)
    assert body.index("tab_copies.filter") < legacy
    # the legacy fan-out is behind the marker, and the marker is set in the same step
    gate = body.rindex("if (!state.tax_flags_per_sheet) {", 0, legacy)
    assert body.index("state.tax_flags_per_sheet = true", split) > split
    assert gate < legacy


def test_the_snapshot_tells_the_intake_where_each_tabs_two_cells_are():
    """The intake finds the base's own two cells on a split draft through
    ``priced_tabs[].flag_cells`` (test_intake_conditions.py executes that half). snapshotLumpSumsToState
    needs the whole totals engine to run, so its half is pinned here: every priced tab's snapshot
    carries the cells ``jobFlagCellsFor`` resolves (executed above)."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    body = src[src.index("function snapshotLumpSumsToState()"):src.index("\nfunction persistTabState()")]
    tabs = body[body.index("state.priced_tabs = pricedTabs().map("):]
    tabs = tabs[:tabs.index("state.sheet_area")]
    assert "flag_cells: jobFlagCellsFor(t.id)" in tabs


def test_the_autofill_puts_its_flags_on_the_base_before_the_page_re_renders():
    """The two tax answers are held back from Epoxy's own cells and written to the base inside the
    same apply, before the grid is redrawn off the values."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    body = src[src.index('document.getElementById("autofill-btn")'):]
    body = body[:body.index("function snapshotLumpSumsToState()")]
    write = body.index("cellValues[k] = v;")
    held = body.index("aiFlags[aiFlag] = v;")
    fan = body.index("applyAutofillJobFlags(aiFlags)")
    redraw = body.index("await showSheet(activeSheet)")
    assert held < fan and write < fan < redraw, (held, write, fan, redraw)



def test_the_ai_drawings_date_fills_a_blank_intake_date_only(result):
    """The AI Autofill writes Drawings Dated to Epoxy!B9, but the GC proposal's spec line reads the
    intake's `drawings_dated`: an intake left blank printed Kyle's placeholder date while the sheet
    showed the AI's (review of the GC templates, 2026-10-02). The click now fills the intake too --
    only when it is blank, and only with something that reads as a date.

    Mutation: drop the `!(live && ...)` guard (`typed` writes); drop the M/D/YY branch (`blankUs`)."""
    a = result["aiDrawingsDated"]
    assert a["blankUs"]["writes"] == [{"drawings_dated": "2026-09-03"}], a["blankUs"]
    assert a["blankUs"]["cell"] == "9/3/26", a["blankUs"]
    assert a["blankIso"]["writes"] == [{"drawings_dated": "2026-09-03"}], a["blankIso"]
    assert a["typed"]["writes"] == [], a["typed"]
    assert a["notADate"]["writes"] == [], a["notADate"]
