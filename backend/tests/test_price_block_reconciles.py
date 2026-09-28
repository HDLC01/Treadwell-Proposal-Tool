"""The PRICE block follows the estimate sheet's tax answers, adds up, and the screen shows the same one.

THE MODEL (Hanz, 2026-09-25, verbatim): "Remodel Tax should be triggered by remodel tax in the
estimate form. Taxable is where base bid and other options are taxable or not." And: "If remodel and
material sales tax is on then there should be both. If remodel is only the one on then only remodel
tax." And: "if one of the taxes is set to yes then broken out should be the default option."

So the sheet decides WHETHER there is tax, per priced tab (Taxable? → material sales tax, Remodel
Tax? → remodel tax), and the proposal's TAX control decides the layout:

  * BROKEN OUT: the base line is the pre-tax figure with NO bracket wording; a Material Sales Tax row
    only when taxable; a Remodel Tax row only when remodel; then the Total — and they add up. Hanz's
    own example, Test33: "$6,767 – Epoxy flooring as described above / $72 – Material Sales Tax /
    $6,839 – Total".
  * ONE LINE: the whole bid, and the wording says which taxes are in it — "(Remodel Tax AND material
    sales tax INCLUDED)", "(material sales tax INCLUDED)", "(Remodel Tax INCLUDED)", "(tax exempt)".
    No tax rows and no Total.
  * TAX EXEMPT (Hanz, 2026-09-28): the customer pays no tax. The base line is the pre-tax figure
    Broken out prints, then "(tax exempt)", and NO row — no Material Sales Tax, no Remodel Tax, no
    Total. It is the one layout whose base line is net of taxes that do not print, on purpose. The
    whole job is exempt: every option prints its own pre-tax figure with "(tax exempt)", and an
    Add/Deduct line is the difference of the two pre-tax figures. The estimate sheet is not changed.
    It is judged on the TAXED rows below: on a sheet with no tax it prints exactly what one line
    prints, so a row with no tax proves nothing about it.

OPTIONS ARE ALWAYS ONE LINE (Hanz, 2026-09-28: "Options should only be total amount, cannot be broken
out. Only the base bid would be broken out or one line."), whatever the TAX control says.

ON EVERY TEMPLATE. The GC and Gyp files author their tax rows as plain paragraphs, which used to
print whatever the tax ("$0.00 – Remodel Tax", a $0 Material Sales Tax on an exempt job). The render
now takes out every row the rule does not print, whether the file wraps it in a {{#block}} or not.

THE BID IS TAX-INCLUSIVE — D88 already contains both taxes — so Broken out backs them OUT using the
sheet's own tax cells (never a guessed rate: sales tax compounds through markup). Kyle's 2026-09-08
report is the reason this file adds up printed dollars rather than trusting a helper: "the proposal
says $6,182 and my estimate says $6,307".

WHY IN DOLLARS, ON THE REAL ARTEFACTS. Every document here is filled from a real template through
the real renderer (`_render_documents`, the path Download, Send and the customer's PDF share), and
the printed strings are read back out of the .docx and added up. The screen half runs the page's own
writers in Node (js/price-block-harness.js) over the shapes walked out of the same template files,
and the two are compared figure for figure.
"""
import io
import json
import pathlib
import re
import shutil
import subprocess

import docx
import pytest
from docx import Document
from starlette.requests import Request

import main
import price_rules
import proposal_writer as pw

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "price-block-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

# (total, sales tax cell, remodel tax cell, Taxable?, Remodel Tax?) — the figures always agree with
# the flags, as the sheet's own cells do (sales tax is 0 exactly when Taxable? is No).
FIGURES = {
    "exempt":            (6307.00,   0.00,   0.00, False, False),
    "sales tax only":    (6307.00, 125.00,   0.00, True,  False),    # Kyle's own job
    "remodel tax only":  (6307.00,   0.00, 471.00, False, True),
    "both, to the cent": (6307.50, 125.25, 471.13, True,  True),
    "Test33":            (6839.00,  72.00,   0.00, True,  False),    # Hanz's own example
}
LAYOUTS = ["ONE_LINE", "BROKEN_OUT", "EXEMPT"]
TAXED = [f for f, (_t, s, r, _tx, _rm) in FIGURES.items() if s or r]
TEMPLATES = [("epoxy", "Direct"), ("polish", "Direct"), ("combo", "Direct"),
             ("epoxy", "GC"), ("polish", "GC"), ("sealer", "GC"), ("gyp", "Direct")]
PHRASE = {(True, True): "(Remodel Tax AND material sales tax INCLUDED)",
          (True, False): "(material sales tax INCLUDED)",
          (False, True): "(Remodel Tax INCLUDED)",
          (False, False): "(tax exempt)"}


# ── reading the printed price block back off the .docx ───────────────────────
def _lines(docx_bytes):
    """Every non-empty paragraph of the document, once: its OWN text (a paragraph that anchors a
    text box must not report the box's contents) and the mc:Fallback twin dropped."""
    d = Document(io.BytesIO(docx_bytes))
    out = []
    for p in d.element.xpath("//w:p"):
        if any(True for _ in p.iterancestors(f"{_MC}Fallback")):
            continue
        t = pw._own_text(p).strip()
        if t:
            out.append(t)
    return out


def _usd(s):
    """The number in a printed price string. Refuses rather than returning 0.0 — a row read as zero
    is how a broken price block looks balanced."""
    m = re.search(r"\$([\d,]+(?:\.\d+)?)", str(s))
    assert m, f"no dollar figure in {s!r}"
    return float(m.group(1).replace(",", ""))


def _price_rows(docx_bytes):
    """`{base, base_line, material, remodel, total, options, highlights}` — each PRICE row that
    PRINTED, keyed by its own wording. A row the layout takes out is ABSENT, never 0.0.

    `options` is every line under the Options heading, in order, as printed; `all` every line of
    the document."""
    blob = docx_bytes
    rows = {"options": []}
    lines = _lines(blob)
    rows["all"] = lines
    in_opts = False
    for line in lines:
        if re.match(r"^Options\b", line):
            in_opts = True
            continue
        if in_opts:
            if re.match(r"^(Pigtail|\*|Excludes|NOTES|Add \$|Treadwell typically)", line):
                in_opts = False
            elif line.startswith("$") or line.startswith("Add ") or line.startswith("Deduct"):
                rows["options"].append(line)
                continue
            else:
                in_opts = False
        if re.search(r"–\s*Material Sales Tax$", line):
            rows.setdefault("material", _usd(line))
        elif re.search(r"–\s*(Kansas\s+)?Remodel Tax$", line):
            rows.setdefault("remodel", _usd(line))
        elif re.search(r"–\s*Total$", line):
            rows.setdefault("total", _usd(line))
        elif "as described above" in line and line.lstrip().startswith("$"):
            rows.setdefault("base", _usd(line))
            rows.setdefault("base_line", line)
    d = Document(io.BytesIO(blob))
    rows["highlights"] = len(list(d.element.body.iter(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}highlight")))
    return rows


def _values(total, sales, remodel, taxable, remodel_on, layout):
    """A payload's `values`, formatted the way the page ships them — through the same `_fmt_usd`
    the document prints with."""
    return {
        "project_name": "Viracor", "job_name": "Viracor", "city_state": "Lees Summit, MO",
        "sqft": "3,000", "epoxy_sf": "3,000", "polish_sf": "3,000", "cove_lf": "0",
        "estimator_name": "Kyle", "bid_date_formatted": "9/8/26", "texture": "OP",
        "system_name": "MACRO", "scope_notes": "scope", "schedule_notes": "~1w",
        "exclusions": "std", "disposal": "d", "state_name": "Kansas",
        "site_visit_phrase": "per site visit on 9/8",
        "total_formatted": main._fmt_usd(total),
        "material_tax_formatted": main._fmt_usd(sales),
        "tax_amount_formatted": main._fmt_usd(remodel),
        "total_label": f"{main._fmt_usd(total)} – Total",
        "area_description": "~3,000 sf of polished concrete flooring",
        # DELIBERATELY THE WRONG BASE: `_generate` must re-derive it by the rule, never trust it. A
        # figure no layout prints on any row. It used to be the total less both taxes, which is the
        # RIGHT base Broken out and under Tax exempt — so a server that trusted the payload passed.
        "base_bid_formatted": "$1,234.56",
        "tax_layout": layout, "price_taxable": taxable, "price_remodel_on": remodel_on,
        "gyp_soft_sf": "3,000", "gyp_hard_sf": "0", "gyp_corridor_sf": "0",
        "gyp_soft_thickness": '3/4"', "gyp_hard_thickness": '1"',
        "gyp_corridor_thickness": '3/4"', "mobilizations_line": "1 Mobilization to Site.",
        "work_description": "per plans",
    }


def _render(payload):
    """The real renderer every document goes through (Download, Send, the customer's PDF)."""
    req = Request({"type": "http", "method": "POST", "path": "/t", "headers": [], "query_string": b""})
    return main._render_documents(payload, req, want_estimate=False)["docx"]["content"]


# Two options, each off its own tab: one taxable with remodel, one remodel only (a seal sheet on an
# exempt-material job, say). Their figures are their own.
OPTION_ROOMS = [
    {"id": "Epoxy", "name": "Epoxy", "is_base": True,
     "bid": {"total": 6307.5, "sales_tax": 125.25, "remodel": 471.13}},
    {"id": "Copy1", "name": "Epoxy copy", "is_base": False, "show": True, "price_mode": "total",
     "option_desc": "Treadwell 3/16\" Urethane Cement", "system_desc": "Treadwell 3/16\" Urethane Cement",
     "base_total": 6307.5,
     "bid": {"total": 7696, "sales_tax": 96, "remodel": 500, "taxable": True, "remodel_on": True}},
    {"id": "Seal", "name": "Seal", "is_base": False, "show": True, "price_mode": "total",
     "option_desc": "Sealed Concrete", "system_desc": "Sealed Concrete", "base_total": 6307.5,
     "bid": {"total": 1476, "sales_tax": 0, "remodel": 90, "taxable": False, "remodel_on": True}},
]
OPTION_TEMPLATES = [("epoxy", "Direct"), ("polish", "Direct"), ("gyp", "Direct")]

# Add/Deduct under Tax exempt. The base: $10,000 with $950 material sales tax — $9,050 pre-tax. Each
# option is priced as an Add/Deduct against it, and each one's tax-inclusive difference and pre-tax
# difference disagree: Quartz is "Add $100" tax-inclusive but $8,900 − $9,050 = "Deduct ($150)"
# pre-tax; Seal the other way round ("Deduct ($500)" → "Add $150"); Urethane the same sign and a
# different amount ("Add $2,000" → "Add $1,950"). A manual "Add for" line prints as typed on every
# layout.
DEDUCT_BASE = (10000.00, 950.00, 0.00, True, False)
DEDUCT_ROOMS = [
    {"id": "Epoxy", "name": "Epoxy", "is_base": True,
     "bid": {"total": 10000, "sales_tax": 950, "remodel": 0}},
    {"id": "Quartz", "name": "Quartz", "is_base": False, "show": True, "price_mode": "deduct",
     "option_desc": "Quartz broadcast", "system_desc": "Quartz broadcast", "base_desc": "Epoxy flooring",
     "base_total": 10000,
     "bid": {"total": 10100, "sales_tax": 1200, "remodel": 0, "taxable": True, "remodel_on": False}},
    {"id": "Seal", "name": "Seal", "is_base": False, "show": True, "price_mode": "deduct",
     "option_desc": "Sealed Concrete", "system_desc": "Sealed Concrete", "base_desc": "Epoxy flooring",
     "base_total": 10000,
     "bid": {"total": 9500, "sales_tax": 0, "remodel": 300, "taxable": False, "remodel_on": True}},
    {"id": "Ure", "name": "Urethane", "is_base": False, "show": True, "price_mode": "deduct",
     "option_desc": "Urethane cement", "system_desc": "Urethane cement", "base_desc": "Epoxy flooring",
     "base_total": 10000,
     "bid": {"total": 12000, "sales_tax": 1000, "remodel": 0, "taxable": True, "remodel_on": False}},
]
DEDUCT_PRICE_LINES = [{"label": "Add for moisture mitigation", "amount": 1200}]
# The same job with a COMBINED combo base (Epoxy + Polish, no single base picked): rebuildPricing's
# mkRoom gives the base room the combined total but only the EPOXY tab's tax cells ($500 of the
# $950). The base line, on screen and on paper, backs the full $950 out; an Add/Deduct taken off
# the base ROOM would be taken off $9,500 instead of the $9,050 the page prints.
DEDUCT_ROOMS_COMBINED = [dict(DEDUCT_ROOMS[0], bid={"total": 10000, "sales_tax": 500, "remodel": 0})] + DEDUCT_ROOMS[1:]
_DEDUCT_WORDS = ("Quartz broadcast", "Sealed Concrete", "Urethane cement", "moisture mitigation")

_DOCS: dict = {}


def _need():
    for wt, aud in TEMPLATES:
        for lay in LAYOUTS:
            for fig in FIGURES:
                yield ("block", wt, aud, lay, fig)
    for wt, aud in OPTION_TEMPLATES:
        for lay in LAYOUTS:
            yield ("options", wt, aud, lay, "both, to the cent")
            yield ("deduct", wt, aud, lay, "deduct")
    yield ("deduct", "combo", "Direct", "EXEMPT", "combined")


@pytest.fixture
def docs():
    """Every document this module reads, rendered once through the real renderer."""
    if _DOCS:
        return _DOCS
    for kind, wt, aud, lay, fig in _need():
        total, sales, remodel, tx, rm = DEDUCT_BASE if kind == "deduct" else FIGURES[fig]
        body = {"work_type": wt, "audience": aud,
                "values": _values(total, sales, remodel, tx, rm, lay),
                "remodel": ([{"amount_formatted": main._fmt_usd(remodel)}] if remodel else [])}
        if kind == "options":
            body["rooms"] = OPTION_ROOMS
            body["values"]["base_bid_formatted"] = ""
        if kind == "deduct":
            body["rooms"] = DEDUCT_ROOMS_COMBINED if fig == "combined" else DEDUCT_ROOMS
            body["price_lines"] = DEDUCT_PRICE_LINES
        _DOCS[(kind, wt, aud, lay, fig)] = _price_rows(_render(body))
    return _DOCS


def _deduct_lines(rows):
    """The Add/Deduct and manual lines as printed, in order (the Options parser stops at a line
    that starts "Add $", which is also how the Polish template's own boilerplate starts)."""
    return [ln for ln in rows["all"] if any(w in ln for w in _DEDUCT_WORDS)
            and (ln.startswith("Add $") or ln.startswith("Deduct (") or ln.startswith("$"))]


# ── (1) the document: rows by the sheet, layout by the control, and it adds up ─────────────────
@pytest.mark.parametrize("work_type,audience", TEMPLATES)
@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("figure", list(FIGURES))
def test_the_printed_price_block_follows_the_sheet_and_adds_up(docs, work_type, audience, layout, figure):
    total, sales, remodel, tx, rm = FIGURES[figure]
    rows = docs[("block", work_type, audience, layout, figure)]
    where = f"{work_type}/{audience} {layout} {figure}: {rows!r}"
    assert "base" in rows, f"no base line printed — {where}"
    if layout == "BROKEN_OUT":
        # A row prints exactly when its tax applies; the Total always.
        assert ("material" in rows) == tx, f"Material Sales Tax row wrong — {where}"
        assert ("remodel" in rows) == rm, f"Remodel Tax row wrong — {where}"
        assert rows.get("total") == total, f"Total wrong — {where}"
        if tx:
            assert rows["material"] == sales
        if rm:
            assert rows["remodel"] == remodel
        printed = round(rows["base"] + rows.get("material", 0.0) + rows.get("remodel", 0.0), 2)
        assert printed == total, f"the printed rows do not sum to the Total — {where}"
        assert "(" not in rows["base_line"], f"a broken-out base line carries bracket wording — {where}"
    elif layout == "EXEMPT":
        # No row of any kind, and the base is the total less the taxes the sheet put in it — the
        # figure Broken out prints on its base line, and not the Total beside "(tax exempt)".
        assert not {"material", "remodel", "total"} & set(rows), f"tax exempt printed a tax row — {where}"
        pre_tax = round(total - (sales if tx else 0.0) - (remodel if rm else 0.0), 2)
        assert rows["base"] == pre_tax, f"tax exempt is not the pre-tax figure — {where}"
        assert rows["base_line"].endswith("(tax exempt)"), f"tax exempt without its wording — {where}"
    else:
        assert not {"material", "remodel", "total"} & set(rows), f"one line printed a tax row — {where}"
        assert rows["base"] == total, f"one line is not the whole bid — {where}"
        assert rows["base_line"].endswith(PHRASE[(tx, rm)]), f"wrong wording for the sheet — {where}"
    assert rows["highlights"] == 0, f"a review highlight reached the customer — {where}"


@pytest.mark.parametrize("work_type,audience", TEMPLATES)
@pytest.mark.parametrize("figure", TAXED)
def test_tax_exempt_is_not_one_line_on_a_taxed_sheet(docs, work_type, audience, figure):
    """THE COUNTEREXAMPLE for the column above. On a sheet with no tax, Tax exempt and One line print
    the same line, so a Tax exempt that quietly printed One line would pass there. On every TAXED
    row they must differ: the figure (pre-tax, not the whole bid) and, where the sheet charged a
    tax, the wording. Mutation: EXEMPT read as ONE_LINE by either half of the rule."""
    ex = docs[("block", work_type, audience, "EXEMPT", figure)]
    one = docs[("block", work_type, audience, "ONE_LINE", figure)]
    assert ex["base"] < one["base"], (work_type, audience, figure, ex, one)
    assert ex["base_line"] != one["base_line"]


@pytest.mark.parametrize("work_type,audience", [("epoxy", "GC"), ("polish", "GC"), ("sealer", "GC"),
                                                ("gyp", "Direct")])
def test_tax_exempt_on_a_taxed_gc_or_gyp_job_takes_its_tax_paragraphs_out(docs, work_type, audience):
    """The GC and Gyp files author Material Sales Tax, Remodel Tax and Total as plain paragraphs.
    Picked Tax exempt on a job whose sheet charges both taxes, none of them may print — not as a row,
    not as a "$0" — and the base is the pre-tax $5,711.12 (6,307.50 − 125.25 − 471.13). This is what
    tells the Tax exempt pick apart from a sheet with no tax (test_an_exempt_gc_job_prints_no_zero_rows)."""
    rows = docs[("block", work_type, audience, "EXEMPT", "both, to the cent")]
    assert rows["base_line"].startswith("$5,711.12 – ") and rows["base_line"].endswith("(tax exempt)"), rows
    assert not {"material", "remodel", "total"} & set(rows), rows
    assert not [ln for ln in rows["all"] if re.search(r"–\s*(Material Sales Tax|(Kansas\s+)?Remodel Tax|Total)$", ln)], (
        rows["all"])


def test_hanz_test33_prints_exactly_what_he_sent(docs):
    """His own words for a correct broken-out base: Taxable Yes, Remodel No, $6,839 bid."""
    rows = docs[("block", "epoxy", "Direct", "BROKEN_OUT", "Test33")]
    assert rows["base_line"] == "$6,767 – Epoxy flooring as described above"
    assert rows["material"] == 72.0 and rows["total"] == 6839.0
    assert "remodel" not in rows


def test_kyles_gc_polish_block_reconciles_line_for_line(docs):
    """The exact block Kyle was shown, Broken out: 6,182 + 125 = 6,307, and no "$0.00 – Remodel Tax"
    row between them — a remodel row prints only when Remodel Tax? says Yes."""
    rows = docs[("block", "polish", "GC", "BROKEN_OUT", "sales tax only")]
    assert rows["base"] == 6182.0 and rows["material"] == 125.0
    assert "remodel" not in rows and rows["total"] == 6307.0
    assert "INCLUDED" not in rows["base_line"], rows["base_line"]


def test_an_exempt_gc_job_prints_no_zero_rows(docs):
    """A GC file's tax rows are plain paragraphs, so an exempt job used to print "$0 – Material Sales
    Tax" under "(tax exempt)". One line now: one line."""
    rows = docs[("block", "epoxy", "GC", "ONE_LINE", "exempt")]
    assert rows["base_line"].endswith("(tax exempt)")
    assert not {"material", "remodel", "total"} & set(rows), rows


# ── (2) every option off its own tab, on one line ───────────────────────────────────────────────
_ONE_LINE_OPTIONS = [
    "$7,696 – Treadwell 3/16\" Urethane Cement as described above "
    "(Remodel Tax AND material sales tax INCLUDED)",
    "$1,476 – Sealed Concrete as described above (Remodel Tax INCLUDED)",
]


@pytest.mark.parametrize("work_type,audience", OPTION_TEMPLATES)
def test_an_option_prints_one_line_even_when_the_base_is_broken_out(docs, work_type, audience):
    """Hanz, 2026-09-28: "Options should only be total amount, cannot be broken out. Only the base
    bid would be broken out or one line." Broken out itemises the BASE — its own rows still print —
    and every option stays its whole total with its own tab's wording, no Material Sales Tax,
    Remodel Tax or Total of its own. (For three days from 2026-09-25 each option printed its own
    pre-tax line and rows; that shape is gone from both halves.)"""
    rows = docs[("options", work_type, audience, "BROKEN_OUT", "both, to the cent")]
    assert rows["options"] == _ONE_LINE_OPTIONS, rows["options"]
    assert not [o for o in rows["options"]
                if re.search(r"–\s*(Material Sales Tax|Remodel Tax|Total)$", o)], rows["options"]
    assert {"material", "remodel", "total"} <= set(rows), f"the base stopped breaking out: {rows!r}"


@pytest.mark.parametrize("work_type,audience", OPTION_TEMPLATES)
def test_each_option_carries_its_own_tax_wording_on_one_line(docs, work_type, audience):
    """One line: the option's whole price and the wording ITS tab's flags call for. These used to
    say "(material sales tax INCLUDED)" whatever the job, so Kyle typed EXCLUDED onto every option
    of every exempt job by hand."""
    opts = docs[("options", work_type, audience, "ONE_LINE", "both, to the cent")]["options"]
    assert opts == _ONE_LINE_OPTIONS, opts


@pytest.mark.parametrize("work_type,audience", OPTION_TEMPLATES)
def test_tax_exempt_prices_every_option_off_its_own_tab_without_its_tax(docs, work_type, audience):
    """The WHOLE job is exempt: each option prints its own tab's total less the taxes ITS flags put
    in it — $7,696 − $96 − $500 and $1,476 − $90 (the seal tab is not taxable, so only its remodel
    comes out) — with "(tax exempt)", still one line. Mutation: the options left on the one-line
    rule under Tax exempt (they print $7,696 / $1,476 with the INCLUDED wording)."""
    opts = docs[("options", work_type, audience, "EXEMPT", "both, to the cent")]["options"]
    assert opts == [
        "$7,100 – Treadwell 3/16\" Urethane Cement as described above (tax exempt)",
        "$1,386 – Sealed Concrete as described above (tax exempt)",
    ], opts


@pytest.mark.parametrize("work_type,audience", OPTION_TEMPLATES)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_an_add_deduct_line_is_the_difference_of_what_the_page_prints(docs, work_type, audience, layout):
    """Add/Deduct is option − base, of the figures the customer reads. One line and Broken out print
    the base tax-inclusive, so the difference is of the two tax-inclusive totals, as it always was.
    Tax exempt prints the base PRE-TAX ($10,000 − $950 = $9,050), so the difference is of the two
    pre-tax figures: base less the deduct is then the option's price. The two differ here in amount
    and in SIGN — Quartz is $100 dearer with its tax and $150 cheaper without it. No tax wording on
    an Add/Deduct line, and the manual "Add for" line prints as typed, in every layout.

    Mutations: the tax-inclusive difference under Tax exempt (Quartz prints "Add $100"); the
    option's pre-tax figure against the base's tax-inclusive one (every line shifts by $950)."""
    got = _deduct_lines(docs[("deduct", work_type, audience, layout, "deduct")])
    if layout == "EXEMPT":
        want = ["Deduct ($150) – VE for Quartz broadcast, in lieu of Epoxy flooring.",
                "Add $150 – Sealed Concrete",
                "Add $1,950 – Urethane cement"]
    else:
        want = ["Add $100 – Quartz broadcast",
                "Deduct ($500) – VE for Sealed Concrete, in lieu of Epoxy flooring.",
                "Add $2,000 – Urethane cement"]
    assert got == want + ["$1,200 – Add for moisture mitigation"], got


# ── (3) the discriminator is the wrapper, not the folder ────────────────────
def _synthetic(*texts):
    d = docx.Document()
    for t in texts:
        d.add_paragraph(t)
    return d


def test_free_tax_rows_follows_the_wrapper():
    """THE COUNTEREXAMPLE. `free_tax_rows` claims to answer "does this row print unconditionally",
    and a green test over eight files that happen to split GC-vs-Direct would pass for a function
    that just read the folder name. These documents differ ONLY by the {{#tax_breakout}} /
    {{#remodel}} wrappers, so the answer has to move with them."""
    free = pw.free_tax_rows(_synthetic(
        "Base Bid",
        "{{base_bid_formatted}} – Polished Concrete as described above {{base_tax_phrase}}",
        "{{material_tax_formatted}} – Material Sales Tax",
        "{{tax_amount_formatted}} – Remodel Tax",
        "{{total_formatted}} – Total"))
    assert free == {"material": True, "remodel": True}

    gated = pw.free_tax_rows(_synthetic(
        "Base Bid",
        "{{base_bid_formatted}} – Polished Concrete as described above {{base_tax_phrase}}",
        "{{#tax_breakout}}",
        "{{material_tax_formatted}} – Material Sales Tax",
        "{{/tax_breakout}}",
        "{{#remodel}}",
        "{{remodel.amount_formatted}} – Remodel Tax",
        "{{/remodel}}",
        "{{total_formatted}} – Total"))
    assert gated == {"material": False, "remodel": False}

    assert pw.free_tax_rows(_synthetic(
        "{{#tax_breakout}}", "{{material_tax_formatted}} – Material Sales Tax",
        "{{/tax_breakout}}", "{{tax_amount_formatted}} – Remodel Tax")) == {
            "material": False, "remodel": True}

    assert pw.free_tax_rows(_synthetic("Budget pricing", "{{total_formatted}} – Total")) == {
        "material": False, "remodel": False}


@pytest.mark.parametrize("work_type,audience,expected", [
    ("epoxy", "Direct", False), ("polish", "Direct", False), ("combo", "Direct", False),
    ("budget", "Direct", False),
    ("epoxy", "GC", True), ("polish", "GC", True), ("sealer", "GC", True), ("combo", "GC", True),
    ("gyp", "Direct", True), ("gyp", "GC", True),
])
def test_every_shipped_template_is_classified_from_its_own_file(work_type, audience, expected):
    """What the eight real files say today, cross-checked against an INDEPENDENT walk. The shape
    still matters for one thing: how a draft saved before the TAX control became layout-only is read
    (price_rules.layout_for)."""
    got = pw.template_free_tax_rows(work_type, audience)
    assert got == {"material": expected, "remodel": expected}, pw.pick_template(
        work_type, audience).name
    d = docx.Document(str(pw.pick_template(work_type, audience)))
    walked = [in_block for _i, _k, _p, in_block, text, _x in pw.iter_editable_blocks(d)
              if "material_tax_formatted" in (text or "")]
    if expected:
        assert walked and all(b is None for b in walked), walked
    else:
        assert all(b is not None for b in walked), walked


def test_an_unreadable_template_says_why_instead_of_guessing(monkeypatch, caplog):
    gone = pw.TEMPLATES_ROOT / "Direct" / "not-in-the-image.docx"
    monkeypatch.setattr(pw, "pick_template", lambda work_type, audience: gone)
    with caplog.at_level("WARNING", logger="proposal_tool.proposal_writer"):
        assert pw.template_free_tax_rows("polish", "GC") == {"material": False, "remodel": False}
    msg = caplog.text
    assert "tax-row shape" in msg, msg
    assert "polish" in msg and "GC" in msg, "the warning does not name the template it refused"
    assert "Error" in msg or "Exception" in msg, f"no exception type in the warning: {msg}"


def test_the_shape_read_is_cached_per_file_version():
    pw._free_tax_rows_cached.cache_clear()
    pw.template_free_tax_rows("polish", "GC")
    first = pw._free_tax_rows_cached.cache_info()
    pw.template_free_tax_rows("polish", "GC")
    second = pw._free_tax_rows_cached.cache_info()
    assert second.hits == first.hits + 1 and second.misses == first.misses


# ── (4) the screen and the document print the same price block ──────────────
def _template_blocks(work_type, audience):
    d = docx.Document(str(pw.pick_template(work_type, audience)))
    return [{"id": i, "in_block": in_block, "text": text}
            for i, _k, _p, in_block, text, _x in pw.iter_editable_blocks(d)]


@pytest.fixture(scope="module")
def screen():
    """Run the page's own price-block writers, in Node, over the real template shapes."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    cases = []
    for work_type, audience in TEMPLATES:
        blocks = _template_blocks(work_type, audience)
        for layout in LAYOUTS:
            for figure, (total, sales, remodel, tx, rm) in FIGURES.items():
                cases.append({"name": f"block/{work_type}/{audience}/{layout}/{figure}",
                              "work_type": work_type, "audience": audience, "blocks": blocks,
                              "tax_layout": layout, "taxable": tx, "remodel_on": rm,
                              "total": total, "sales_tax": sales, "remodel_tax": remodel})
    for work_type, audience in OPTION_TEMPLATES:
        blocks = _template_blocks(work_type, audience)
        total, sales, remodel, tx, rm = FIGURES["both, to the cent"]
        for layout in LAYOUTS:
            cases.append({"name": f"options/{work_type}/{audience}/{layout}",
                          "work_type": work_type, "audience": audience, "blocks": blocks,
                          "tax_layout": layout, "taxable": tx, "remodel_on": rm,
                          "total": total, "sales_tax": sales, "remodel_tax": remodel,
                          "rooms": OPTION_ROOMS})
            dt, ds, dr, dtx, drm = DEDUCT_BASE
            cases.append({"name": f"deduct/{work_type}/{audience}/{layout}",
                          "work_type": work_type, "audience": audience, "blocks": blocks,
                          "tax_layout": layout, "taxable": dtx, "remodel_on": drm,
                          "total": dt, "sales_tax": ds, "remodel_tax": dr,
                          "rooms": DEDUCT_ROOMS, "state": {"price_lines": DEDUCT_PRICE_LINES}})
    dt, ds, dr, dtx, drm = DEDUCT_BASE
    cases.append({"name": "deduct/combo/Direct/EXEMPT/combined", "work_type": "combo", "audience": "Direct",
                  "blocks": _template_blocks("combo", "Direct"), "tax_layout": "EXEMPT",
                  "taxable": dtx, "remodel_on": drm, "total": dt, "sales_tax": ds, "remodel_tax": dr,
                  "rooms": DEDUCT_ROOMS_COMBINED, "state": {"price_lines": DEDUCT_PRICE_LINES}})
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                       input=json.dumps(cases), capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return {r["name"]: r for r in json.loads(p.stdout)}


def _free_row_kind(text):
    if re.search(r"\{\{\s*material_tax_formatted\s*\}\}", text or ""):
        return "material"
    if re.search(r"\{\{\s*(tax_amount_formatted|remodel\.amount_formatted)\s*\}\}", text or ""):
        return "remodel"
    if re.search(r"\{\{\s*(total_formatted|total_label)\s*\}\}", text or ""):
        return "total"
    return None


@needs_node
@pytest.mark.parametrize("work_type,audience", TEMPLATES)
@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("figure", list(FIGURES))
def test_the_screen_and_the_document_print_the_same_price_block(screen, docs, work_type, audience,
                                                                layout, figure):
    """THE PROPERTY BEING FIXED: the figures, the wording and the rows the estimator proofreads are
    the ones the customer reads — every template shape, all three layouts, every combination of the
    two taxes. JS off the served blocks, Python off the template file. (The document's base under
    Tax exempt is re-derived by the server, never read off the payload: see _values' base.)"""
    r = screen[f"block/{work_type}/{audience}/{layout}/{figure}"]
    rows = docs[("block", work_type, audience, layout, figure)]
    where = f"{work_type}/{audience} {layout} {figure}"
    tk = r["tokens"]
    assert tk["tax_layout"] == layout and r["layout"] == layout, where
    # The old field's closest meaning, for a reader that knows no third layout.
    assert tk["tax_inclusion"] == {"ONE_LINE": "INCLUDED", "BROKEN_OUT": "BROKEN_OUT",
                                   "EXEMPT": "EXEMPT"}[layout], where
    # The base bid and its wording, as the document prints them.
    assert rows["base"] == _usd(tk["base_bid_formatted"]), (
        f"{where}: screen {tk['base_bid_formatted']} vs document ${rows['base']:,.2f}")
    assert rows["base_line"].endswith(tk["base_tax_phrase"] or "as described above"), (
        f"{where}: the document's wording {rows['base_line']!r} is not the screen's "
        f"{tk['base_tax_phrase']!r}")
    # Which rows print, three ways: the tokens the payload carries, the rows the page paints (the
    # Direct files mount them), and the free rows the page shows (the GC / Gyp files).
    doc_rows = {k for k in ("material", "remodel", "total") if k in rows}
    screen_rows = {k for k in ("material", "remodel", "total") if tk[f"price_rows_{k}"]}
    assert screen_rows == doc_rows, f"{where}: screen {screen_rows} vs document {doc_rows}"
    free = r["freeRows"]
    blocks = {b["id"]: b for b in _template_blocks(work_type, audience)}
    for bid, shown in free.items():
        kind = _free_row_kind(blocks[int(bid)]["text"])
        assert shown == (kind in doc_rows), f"{where}: free {kind} row shown={shown}, document {doc_rows}"
    p = r["painted"]
    painted_rows = {k for k, on in (("material", p["salesRowShown"]), ("remodel", p["remodelRowShown"]),
                                    ("total", p["totalRowShown"])) if on}
    if not free:
        assert painted_rows == doc_rows, f"{where}: painted {painted_rows} vs document {doc_rows}"
        assert _usd(p["base"]) == rows["base"], f"{where}: painted {p['base']!r}"


@needs_node
@pytest.mark.parametrize("work_type,audience", OPTION_TEMPLATES)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_screen_and_the_document_print_the_same_option_lines(screen, docs, work_type, audience, layout):
    """Every option line, as drawn in the editor, is the line the document prints — its own tab's
    figures and its own wording, on one line under every layout (pre-tax, "(tax exempt)", under Tax
    exempt)."""
    r = screen[f"options/{work_type}/{audience}/{layout}"]
    shown = [ln["text"] for ln in r["options"]]
    printed = docs[("options", work_type, audience, layout, "both, to the cent")]["options"]
    assert shown == printed, f"{work_type}/{audience} {layout}: screen {shown} vs document {printed}"
    assert all(ln["key"].count(":") == 1 for ln in r["options"]), (
        f"the editor drew an option's own tax row: {[ln['key'] for ln in r['options']]}")


@needs_node
@pytest.mark.parametrize("work_type,audience", OPTION_TEMPLATES)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_screen_and_the_document_print_the_same_add_deduct_lines(screen, docs, work_type, audience,
                                                                     layout):
    """The Add/Deduct lines and the manual line, as the editor draws them, are the ones the document
    prints: the screen's difference is taken off its own base line (baseTaxRule), the document's off
    the rule call that printed its base — pre-tax under Tax exempt on both halves."""
    r = screen[f"deduct/{work_type}/{audience}/{layout}"]
    shown = [ln["text"] for ln in r["options"]]
    printed = _deduct_lines(docs[("deduct", work_type, audience, layout, "deduct")])
    assert shown == printed, f"{work_type}/{audience} {layout}: screen {shown} vs document {printed}"


@needs_node
def test_a_combined_combo_base_takes_the_deduct_off_the_base_line_not_the_base_room(screen, docs):
    """Under Tax exempt the Add/Deduct is taken off the base's pre-tax figure AS THE BASE LINE PRINTS
    IT — main._generate passes its own rule's figure into _build_options — not off the base room.
    They differ on a combined Epoxy + Polish combo base, whose room carries only the epoxy tab's tax
    cells against the combined total: off the room, Quartz would be $8,900 − $9,500, "Deduct ($600)",
    under a base line reading $9,050. Screen and document agree on $150.

    Mutation: _generate stops passing base_pre_tax_cents (the base room answers)."""
    rows = docs[("deduct", "combo", "Direct", "EXEMPT", "combined")]
    assert rows["base_line"].startswith("$9,050 – "), rows["base_line"]
    printed = _deduct_lines(rows)
    assert printed == ["Deduct ($150) – VE for Quartz broadcast, in lieu of Epoxy flooring.",
                       "Add $150 – Sealed Concrete", "Add $1,950 – Urethane cement",
                       "$1,200 – Add for moisture mitigation"], printed
    shown = [ln["text"] for ln in screen["deduct/combo/Direct/EXEMPT/combined"]["options"]]
    assert shown == printed, f"screen {shown} vs document {printed}"


@needs_node
def test_the_default_layout_follows_the_sheet_until_somebody_picks():
    """"if one of the taxes is set to yes then broken out should be the default option." A draft
    that never chose a layout follows the sheet; one that did keeps it; a draft saved before the
    control became layout-only is read by what it printed (Broken out stays Broken out, Included and
    Exempt were one line — on a GC/Gyp file, whose rows always printed, the default answers).

    Tax exempt (2026-09-28) is only ever a pick: picked, it wins over the Broken-out default on a
    taxed sheet; the old "EXEMPT" in `tax_inclusion` keeps printing the one line it printed, with
    the tax-inclusive figure — an untouched old payload may not print different money."""
    blocks = _template_blocks("epoxy", "Direct")
    gc = _template_blocks("epoxy", "GC")
    base = {"work_type": "epoxy", "audience": "Direct", "blocks": blocks,
            "total": 6839.0, "sales_tax": 72.0, "remodel_tax": 0.0}
    cases = [
        dict(base, name="new, taxable", taxable=True, remodel_on=False),
        dict(base, name="new, remodel only", taxable=False, remodel_on=True, sales_tax=0.0, remodel_tax=40.0),
        dict(base, name="new, neither", taxable=False, remodel_on=False, sales_tax=0.0),
        dict(base, name="picked one line", taxable=True, remodel_on=False, tax_layout="ONE_LINE"),
        dict(base, name="picked tax exempt", taxable=True, remodel_on=True, remodel_tax=40.0,
             tax_layout="EXEMPT"),
        dict(base, name="picked tax exempt on GC", audience="GC", blocks=gc, taxable=True,
             remodel_on=False, tax_layout="EXEMPT", tax_inclusion="INCLUDED"),
        dict(base, name="legacy BROKEN_OUT", taxable=False, remodel_on=False, sales_tax=0.0,
             tax_inclusion="BROKEN_OUT"),
        dict(base, name="legacy INCLUDED", taxable=True, remodel_on=False, tax_inclusion="INCLUDED"),
        dict(base, name="legacy EXEMPT", taxable=True, remodel_on=False, tax_inclusion="EXEMPT"),
        dict(base, name="legacy GC INCLUDED", audience="GC", blocks=gc, taxable=True,
             remodel_on=False, tax_inclusion="INCLUDED"),
        dict(base, name="legacy GC EXEMPT, exempt job", audience="GC", blocks=gc, taxable=False,
             remodel_on=False, sales_tax=0.0, tax_inclusion="EXEMPT"),
    ]
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], input=json.dumps(cases),
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    got = {r["name"]: r["layout"] for r in json.loads(p.stdout)}
    assert got == {
        "new, taxable": "BROKEN_OUT", "new, remodel only": "BROKEN_OUT", "new, neither": "ONE_LINE",
        "picked one line": "ONE_LINE", "picked tax exempt": "EXEMPT",
        "picked tax exempt on GC": "EXEMPT", "legacy BROKEN_OUT": "BROKEN_OUT",
        "legacy INCLUDED": "ONE_LINE", "legacy EXEMPT": "ONE_LINE",
        "legacy GC INCLUDED": "BROKEN_OUT", "legacy GC EXEMPT, exempt job": "ONE_LINE",
    }, got
    # And the document reads a legacy payload the same way (no tax_layout on it), and a pick of Tax
    # exempt as Tax exempt whatever the legacy field beside it says.
    for layout, legacy, free, tx, rm, want in [(None, "INCLUDED", False, True, False, "ONE_LINE"),
                                               (None, "EXEMPT", False, True, True, "ONE_LINE"),
                                               (None, "BROKEN_OUT", False, False, False, "BROKEN_OUT"),
                                               (None, "INCLUDED", True, True, False, "BROKEN_OUT"),
                                               (None, "EXEMPT", True, False, False, "ONE_LINE"),
                                               (None, "EXEMPT", True, True, False, "BROKEN_OUT"),
                                               ("EXEMPT", "EXEMPT", False, True, True, "EXEMPT"),
                                               ("EXEMPT", "INCLUDED", True, True, False, "EXEMPT")]:
        assert price_rules.layout_for(layout, legacy, free_rows=free, taxable=tx,
                                      remodel_on=rm) == want, (layout, legacy, free, tx, rm)


# ── (5) the TAX control offers Tax exempt, and a pick of it is stored and shown ─────────────────
_HTML = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")


def _tax_select_options():
    """The <option>s of the real #tax-treatment-select, as (value, label)."""
    m = re.search(r'<select id="tax-treatment-select">(.*?)</select>', _HTML, re.S)
    assert m, "proposal-review.html has no #tax-treatment-select"
    return re.findall(r'<option value="([^"]*)">([^<]*)</option>', m.group(1))


@needs_node
def test_the_tax_control_offers_tax_exempt_and_stores_the_pick():
    """Hanz, 2026-09-28: "Tax exempt" returns to the TAX dropdown. The select offers One line /
    Broken out / Tax exempt; picking Tax exempt runs the page's own change handler (wireRibbonTax,
    lifted verbatim), which stores the draft's top-level `tax_layout` "EXEMPT" — the only place the
    pick lives — and fires the form's `input` for the repaint and the save. The repaint shows the
    pick rather than snapping back to One line, a reload paints it again from what was saved, the
    Base Bid is the pre-tax $6,767 of Hanz's Test33 with "(tax exempt)" and no row under it, and the
    estimate sheet's cells are not touched.

    Mutations: the handler's `=== "BROKEN_OUT" ? … : "ONE_LINE"` coercion (stores ONE_LINE); the
    repaint's two-way `rule.broken ? "BROKEN_OUT" : "ONE_LINE"` (the pick snaps back); the option
    missing from the HTML (the double reads back "")."""
    options = _tax_select_options()
    assert options == [("ONE_LINE", "One line"), ("BROKEN_OUT", "Broken out"), ("EXEMPT", "Tax exempt")], options
    blocks = _template_blocks("epoxy", "Direct")
    case = {"name": "pick", "work_type": "epoxy", "audience": "Direct", "blocks": blocks,
            "total": 6839.0, "sales_tax": 72.0, "remodel_tax": 0.0, "taxable": True, "remodel_on": False,
            "pick": "EXEMPT", "select_options": [v for v, _l in options]}
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], input=json.dumps([case]),
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    got = json.loads(p.stdout)[0]["pick"]
    assert got["wired"] == 1, "the TAX select has no change handler"
    assert got["painted"] == "BROKEN_OUT", "a taxed sheet's default is Broken out until somebody picks"
    assert got["picked"] == "EXEMPT"
    assert got["saved"] == [{"tax_layout": "EXEMPT"}], got["saved"]
    assert got["moduleState"] == "EXEMPT" and got["inputs"] == ["input"], got
    assert got["repainted"] == "EXEMPT", "the repaint snapped the pick back"
    assert got["reloaded"] == "EXEMPT", "a reload does not show the saved pick"
    assert got["base"] == "$6,767 – Epoxy flooring as described above (tax exempt)", got["base"]
    assert got["rowsShown"] == [], got["rowsShown"]
    assert got["tokens"] == {"tax_layout": "EXEMPT", "tax_inclusion": "EXEMPT",
                             "base_bid_formatted": "$6,767", "base_tax_phrase": "(tax exempt)"}, got["tokens"]
    assert got["cellsUntouched"] is True, "picking Tax exempt wrote the estimate sheet"
