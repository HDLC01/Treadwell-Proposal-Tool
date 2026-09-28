"""The PRICE block follows the estimate sheet's tax answers, adds up, and the screen shows the same one.

THE MODEL (Hanz, 2026-09-25, verbatim): "Remodel Tax should be triggered by remodel tax in the
estimate form. Taxable is where base bid and other options are taxable or not." And: "If remodel and
material sales tax is on then there should be both. If remodel is only the one on then only remodel
tax." And: "if one of the taxes is set to yes then broken out should be the default option."

So the sheet decides WHETHER there is tax, per priced tab (Taxable? → material sales tax, Remodel
Tax? → remodel tax), and the proposal's TAX control decides only the layout:

  * BROKEN OUT: the base line is the pre-tax figure with NO bracket wording; a Material Sales Tax row
    only when taxable; a Remodel Tax row only when remodel; then the Total — and they add up. Hanz's
    own example, Test33: "$6,767 – Epoxy flooring as described above / $72 – Material Sales Tax /
    $6,839 – Total". And 2026-09-28: "If it's remodel tax we can also break it out, it just
    wouldn't have the material tax."
  * ONE LINE: the whole bid, and the wording says which taxes are in it — "(Remodel Tax AND material
    sales tax INCLUDED)", "(material sales tax INCLUDED)", "(Remodel Tax INCLUDED)", "(tax exempt)".
    No tax rows and no Total.

A SHEET WITH NO TAX IS TAX EXEMPT, AND TAX EXEMPT IS ONE LINE (Hanz, 2026-09-28: "If it's tax exempted
then it should just be one line and not broken apart because there is no tax to be broken out ...
it's basis if it's taxable or not is on the estimate sheet"; exempt is set on the "Estimate sheet
only"). A stored Broken out cannot split it: it prints its whole total, "(tax exempt)", and no row —
not "$6,307" over "$6,307 – Total". The "Tax exempt" pick of #573, which printed a price without the
taxes the sheet kept in it, is gone; LAYOUTS below still carry a stored "EXEMPT", as a value that is
not a layout (a hand-built payload could hold one), and it prints the whole bid.

OPTIONS ARE ALWAYS ONE LINE (Hanz, 2026-09-28: "Options should only be total amount, cannot be broken
out. Only the base bid would be broken out or one line."), whatever the TAX control says: the whole
tax-inclusive total, worded by the option's own tab.

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
# The stored `tax_layout` values: the two layouts, and a stored "EXEMPT" (#573's pick, which no page
# writes now) — not a layout, so read as a payload or draft with none.
LAYOUTS = ["ONE_LINE", "BROKEN_OUT", "EXEMPT"]
TAXED = [f for f, (_t, s, r, _tx, _rm) in FIGURES.items() if s or r]
TEMPLATES = [("epoxy", "Direct"), ("polish", "Direct"), ("combo", "Direct"),
             ("epoxy", "GC"), ("polish", "GC"), ("sealer", "GC"), ("gyp", "Direct")]
PHRASE = {(True, True): "(Remodel Tax AND material sales tax INCLUDED)",
          (True, False): "(material sales tax INCLUDED)",
          (False, True): "(Remodel Tax INCLUDED)",
          (False, False): "(tax exempt)"}


def _free(work_type, audience):
    """Whether the template authors its tax rows as plain paragraphs (GC, Gyp)."""
    f = pw.template_free_tax_rows(work_type, audience)
    return bool(f["material"] or f["remodel"])


def _doc_prints(layout, work_type, audience, tx, rm):
    """The layout a document PRINTS for a payload holding `layout` and no `tax_inclusion` (as `_values`
    writes it) — worked out here from the rule's own terms, not by calling it. A sheet with no tax:
    one line, whatever is stored. Otherwise a layout is its own answer; anything else (a stored
    "EXEMPT") reads as a payload without the field — INCLUDED, which printed one line, except on a
    file whose rows are plain paragraphs, where the default answers: Broken out."""
    if not (tx or rm):
        return "ONE_LINE"
    if layout in ("ONE_LINE", "BROKEN_OUT"):
        return layout
    return "BROKEN_OUT" if _free(work_type, audience) else "ONE_LINE"


def _page_asks(layout, tx, rm):
    """The layout the PAGE reads off a draft holding `layout` (taxLayout): its own answer when it is
    one, else — a stored "EXEMPT" — the draft is undecided and the default follows the sheet."""
    if layout in ("ONE_LINE", "BROKEN_OUT"):
        return layout
    return "BROKEN_OUT" if (tx or rm) else "ONE_LINE"


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
        # RIGHT base Broken out on a sheet with both taxes — so a server that trusted it passed there.
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


# Three options, each off its own tab: one taxable with remodel, one remodel only (a seal sheet on an
# exempt-material job, say), and one whose tab says No to both — tax exempt, so "(tax exempt)" on its
# own line whatever the base does. Their figures are their own.
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
    {"id": "Polish", "name": "Polish", "is_base": False, "show": True, "price_mode": "total",
     "option_desc": "Polished Concrete", "system_desc": "Polished Concrete", "base_total": 6307.5,
     "bid": {"total": 4200, "sales_tax": 0, "remodel": 0, "taxable": False, "remodel_on": False}},
]
OPTION_TEMPLATES = [("epoxy", "Direct"), ("polish", "Direct"), ("gyp", "Direct")]

# Add/Deduct. The base: $10,000 with $950 material sales tax. Each option is priced as an Add/Deduct
# against it, off the two TAX-INCLUSIVE totals under every layout: Quartz "Add $100", Seal "Deduct
# ($500)", Urethane "Add $2,000". The figures are chosen so the two PRE-TAX figures disagree — Quartz
# $8,900 against $9,050 is a Deduct of $150, Seal an Add of $150, Urethane an Add of $1,950 — which
# is what #573 printed under its Tax exempt pick, and what nothing prints now. A manual "Add for"
# line prints as typed on every layout.
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
_DEDUCT_WORDS = ("Quartz broadcast", "Sealed Concrete", "Urethane cement", "moisture mitigation")
# A combo with no single base picked: the page prices Option 1 (Epoxy) and Option 2 (Polish) off
# these two tabs instead of drawing a base line. They sum to "both, to the cent" — $6,307.50 with
# $125.25 of sales tax (the epoxy tab's alone: polish is not Taxable?) and $471.13 of remodel tax.
COMBO_TABS = [
    {"id": "Epoxy", "role": "epoxy", "kind": "base", "total": 5000.00, "sales_tax": 125.25,
     "remodel": 300.00, "taxable": True, "remodel_on": True},
    {"id": "Polish", "role": "polish", "kind": "base", "total": 1307.50, "sales_tax": 0.00,
     "remodel": 171.13, "taxable": False, "remodel_on": True},
]
# The same combo with a polish tab that says No to BOTH taxes: tax exempt. Its Option 2 line prints
# one line, "(tax exempt)", under Broken out too, while the epoxy system breaks out beside it — each
# system is asked for itself. The base the page reads sums the two: $6,307.50, $125.25 sales tax
# (epoxy's), $300 remodel (epoxy's).
COMBO_TABS_POLISH_EXEMPT = [
    COMBO_TABS[0],
    {"id": "Polish", "role": "polish", "kind": "base", "total": 1307.50, "sales_tax": 0.00,
     "remodel": 0.00, "taxable": False, "remodel_on": False},
]
COMBO_POLISH_EXEMPT_BASE = (6307.50, 125.25, 300.00, True, True)

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
            body["rooms"] = DEDUCT_ROOMS
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
    """Every stored layout value on every template and every combination of the two taxes, judged by
    what it PRINTS (`_doc_prints`): Broken out itemises what applies and adds up; one line is the
    whole bid with the sheet's wording — and a sheet with no tax is one line under all of them."""
    total, sales, remodel, tx, rm = FIGURES[figure]
    rows = docs[("block", work_type, audience, layout, figure)]
    where = f"{work_type}/{audience} {layout} {figure}: {rows!r}"
    assert "base" in rows, f"no base line printed — {where}"
    if _doc_prints(layout, work_type, audience, tx, rm) == "BROKEN_OUT":
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
    else:
        assert not {"material", "remodel", "total"} & set(rows), f"one line printed a tax row — {where}"
        assert rows["base"] == total, f"one line is not the whole bid — {where}"
        assert rows["base_line"].endswith(PHRASE[(tx, rm)]), f"wrong wording for the sheet — {where}"
    assert rows["highlights"] == 0, f"a review highlight reached the customer — {where}"


@pytest.mark.parametrize("work_type,audience", TEMPLATES)
def test_a_sheet_with_no_tax_prints_one_line_under_a_stored_broken_out(docs, work_type, audience):
    """THE BUG THIS FIXES. Hanz, 2026-09-28: "If it's tax exempted then it should just be one line and
    not broken apart because there is no tax to be broken out." A payload saved with Broken out on a
    job whose sheet says No to both taxes printed "$6,307 – … as described above" over "$6,307 –
    Total". It prints the whole bid, "(tax exempt)", and nothing under it — no Material Sales Tax, no
    Remodel Tax, no Total — on every template, the GC / Gyp files' plain tax paragraphs included.

    Mutation: the no-tax line out of price_rules.tax_rule (the Total row prints again)."""
    rows = docs[("block", work_type, audience, "BROKEN_OUT", "exempt")]
    assert rows["base"] == 6307.0 and rows["base_line"].endswith("(tax exempt)"), rows
    assert not {"material", "remodel", "total"} & set(rows), rows
    assert not [ln for ln in rows["all"]
                if re.search(r"–\s*(Material Sales Tax|(Kansas\s+)?Remodel Tax|Total)$", ln)], rows["all"]
    # The same money as before — only the lines it is printed on changed.
    assert rows["base_line"] == docs[("block", work_type, audience, "ONE_LINE", "exempt")]["base_line"]


@pytest.mark.parametrize("work_type,audience", TEMPLATES)
def test_remodel_only_broken_out_prints_no_material_sales_tax_row(docs, work_type, audience):
    """Hanz, 2026-09-28: "If it's remodel tax we can also break it out, it just wouldn't have the
    material tax." Taxable? No, Remodel Tax? Yes, Broken out: $5,836 – … as described above, $471 –
    Remodel Tax, $6,307 – Total, and no Material Sales Tax row — not a "$0" one either.

    Mutation: price_rules.tax_rule's broken-out branch printing a Material Sales Tax row on a
    remodel-only tab."""
    rows = docs[("block", work_type, audience, "BROKEN_OUT", "remodel tax only")]
    assert (rows["base"], rows.get("remodel"), rows.get("total")) == (5836.0, 471.0, 6307.0), rows
    assert "material" not in rows, rows
    assert not [ln for ln in rows["all"] if "Material Sales Tax" in ln], rows["all"]


@pytest.mark.parametrize("work_type,audience", TEMPLATES)
@pytest.mark.parametrize("figure", TAXED)
def test_a_stored_exempt_prints_the_whole_bid_never_a_price_without_its_tax(docs, work_type, audience,
                                                                           figure):
    """#573's "Tax exempt" printed the base less the taxes the sheet kept in the bid, with no row to
    make them up. It is gone, and a `tax_layout` "EXEMPT" left on a payload is not a layout: the
    document reads it as a payload with none (one line on a Direct file, the Broken-out default on a
    GC / Gyp one), and either way the base plus the rows that print is the whole tax-inclusive bid.

    Mutation: #573's EXEMPT reading and branch back in price_rules (the base prints short, no row)."""
    total, sales, remodel, tx, rm = FIGURES[figure]
    rows = docs[("block", work_type, audience, "EXEMPT", figure)]
    printed = round(rows["base"] + rows.get("material", 0.0) + rows.get("remodel", 0.0), 2)
    assert printed == total, (work_type, audience, figure, rows)
    assert not rows["base_line"].endswith("(tax exempt)"), rows["base_line"]


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
    "$4,200 – Polished Concrete as described above (tax exempt)",
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
@pytest.mark.parametrize("layout", LAYOUTS)
def test_each_option_carries_its_own_tax_wording_on_one_line(docs, work_type, audience, layout):
    """One line under every layout: the option's whole tax-inclusive price and the wording ITS tab's
    flags call for — "(tax exempt)" for the tab that says No to both, the INCLUDED wording for the
    others, and never a figure with its tax backed out (a stored "EXEMPT" included). These used to
    say "(material sales tax INCLUDED)" whatever the job, so Kyle typed EXCLUDED onto every option
    of every exempt job by hand.

    Mutation: main._build_options dropping the wording on a tab with no tax (the Polished Concrete
    line loses "(tax exempt)")."""
    opts = docs[("options", work_type, audience, layout, "both, to the cent")]["options"]
    assert opts == _ONE_LINE_OPTIONS, opts


@pytest.mark.parametrize("work_type,audience", OPTION_TEMPLATES)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_an_add_deduct_line_is_the_difference_of_what_the_page_prints(docs, work_type, audience, layout):
    """Add/Deduct is option − base, the two TAX-INCLUSIVE totals the customer reads, under every
    layout — a stored "EXEMPT" too. (#573's Tax exempt took it off the two pre-tax figures, which
    disagree here in amount and sign: Quartz $150 cheaper without its tax, $100 dearer with it.) No
    tax wording on an Add/Deduct line, and the manual "Add for" line prints as typed.

    Mutation: main._build_options taking the difference off the two pre-tax figures (Quartz prints
    "Deduct ($150)")."""
    got = _deduct_lines(docs[("deduct", work_type, audience, layout, "deduct")])
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
    total, sales, remodel, tx, rm = FIGURES["both, to the cent"]
    ct, cs, cr, ctx, crm = COMBO_POLISH_EXEMPT_BASE
    for layout in LAYOUTS:
        cases.append({"name": f"combo-lines/{layout}", "work_type": "combo", "audience": "Direct",
                      "blocks": _template_blocks("combo", "Direct"), "tax_layout": layout,
                      "taxable": tx, "remodel_on": rm, "total": total, "sales_tax": sales,
                      "remodel_tax": remodel, "state": {"priced_tabs": COMBO_TABS}})
        cases.append({"name": f"combo-polish-exempt/{layout}", "work_type": "combo", "audience": "Direct",
                      "blocks": _template_blocks("combo", "Direct"), "tax_layout": layout,
                      "taxable": ctx, "remodel_on": crm, "total": ct, "sales_tax": cs,
                      "remodel_tax": cr, "state": {"priced_tabs": COMBO_TABS_POLISH_EXEMPT}})
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
    the ones the customer reads — every template shape, every stored layout value, every combination
    of the two taxes. JS off the served blocks, Python off the template file.

    A stored ONE_LINE / BROKEN_OUT is judged against the document holding the SAME value — including
    Broken out on a sheet with no tax, where both halves must print one line, "(tax exempt)". A
    stored "EXEMPT" is no layout: the page reads the draft as undecided and sends the layout it
    resolved, so it is judged against the document of that layout (a payload that itself carries
    "EXEMPT" is judged in (1))."""
    total, sales, remodel, tx, rm = FIGURES[figure]
    r = screen[f"block/{work_type}/{audience}/{layout}/{figure}"]
    where = f"{work_type}/{audience} {layout} {figure}"
    tk = r["tokens"]
    asked = _page_asks(layout, tx, rm)
    prints = asked if (tx or rm) else "ONE_LINE"
    assert r["layout"] == asked, where
    # The payload says what PRINTS — never "EXEMPT", and one line on a sheet with no tax.
    assert tk["tax_layout"] == prints, where
    assert tk["tax_inclusion"] == {"ONE_LINE": "INCLUDED", "BROKEN_OUT": "BROKEN_OUT"}[prints], where
    rows = docs[("block", work_type, audience, layout if layout in ("ONE_LINE", "BROKEN_OUT") else prints,
                 figure)]
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
    whole total and its own wording, "(tax exempt)" on the tab with no tax, on one line under every
    layout. Mutation: renderOptionLinesPreview dropping the wording on a tab with no tax."""
    r = screen[f"options/{work_type}/{audience}/{layout}"]
    shown = [ln["text"] for ln in r["options"]]
    printed = docs[("options", work_type, audience, layout, "both, to the cent")]["options"]
    assert shown == _ONE_LINE_OPTIONS, f"{work_type}/{audience} {layout}: screen {shown}"
    assert shown == printed, f"{work_type}/{audience} {layout}: screen {shown} vs document {printed}"
    assert all(ln["key"].count(":") == 1 for ln in r["options"]), (
        f"the editor drew an option's own tax row: {[ln['key'] for ln in r['options']]}")


@needs_node
@pytest.mark.parametrize("work_type,audience", OPTION_TEMPLATES)
@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_screen_and_the_document_print_the_same_add_deduct_lines(screen, docs, work_type, audience,
                                                                     layout):
    """The Add/Deduct lines and the manual line, as the editor draws them, are the ones the document
    prints: option − base, the two tax-inclusive totals, on both halves and under every layout.
    Mutation: renderOptionLinesPreview taking the difference off the two pre-tax figures."""
    r = screen[f"deduct/{work_type}/{audience}/{layout}"]
    shown = [ln["text"] for ln in r["options"]]
    printed = _deduct_lines(docs[("deduct", work_type, audience, layout, "deduct")])
    assert shown == printed, f"{work_type}/{audience} {layout}: screen {shown} vs document {printed}"


# ── (4b) the payload the PAGE composes prints what the page shows ──────────────────────────────
# Every comparison above renders the document from `_values`, figures and flags this file writes
# itself. That proves the two rules agree; it does not prove the page SENDS what it shows. A page
# that painted one line "(tax exempt)" and told the server "taxable, Broken out" would print a
# Material Sales Tax row on the customer's copy while each half passed on its own. So here the document is
# rendered from the harness's `payload` — computeTokenValues' tokens over the draft, and
# comboLinesForPayload's lines, exactly as composeProposalPayload hands them to /api/generate —
# with only narrative text added, and every price line the page draws must print, verbatim.
_NARRATIVE = {k: v for k, v in _values(0, 0, 0, False, False, "ONE_LINE").items()
              if not re.search(r"formatted|label|tax_layout|price_", k)}
_FROM_PAGE: dict = {}


def _from_page(r):
    """The .docx rendered from the payload the page composed for screen case `r`, read back."""
    if r["name"] not in _FROM_PAGE:
        body = json.loads(json.dumps(r["payload"]))
        body["values"] = dict(_NARRATIVE, **body["values"])
        _FROM_PAGE[r["name"]] = _price_rows(_render(body))
    return _FROM_PAGE[r["name"]]


def _drawn(r):
    """The price lines the page draws, as text: the combo's Option lines where it draws them,
    else the base line and the rows shown under it — where the file MOUNTS those rows (a GC or Gyp
    file words its own free rows, "Kansas Remodel Tax", and is judged by figure and wording
    instead); then the option and manual lines."""
    if r["combo"]:
        lines = [ln["text"] for ln in r["combo"]]
    elif r["freeRows"]:
        lines = []
    else:
        p = r["painted"]
        lines = [p["base"]] + [p[k] for k, on in (("sales_tax", p["salesRowShown"]),
                                                  ("remodel", p["remodelRowShown"]),
                                                  ("total", p["totalRowShown"])) if on]
    return lines + [ln["text"] for ln in r["options"]]


@needs_node
@pytest.mark.parametrize("work_type,audience", TEMPLATES)
@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("figure", list(FIGURES))
def test_the_payload_the_page_composes_prints_the_price_block_it_shows(screen, work_type, audience,
                                                                        layout, figure):
    """The loop closed: the page's own payload, through the real renderer, prints the base line,
    its wording and the rows the page shows — on every template, every stored layout value and
    every combination of the two taxes, the sheet with none among them (one line, "(tax exempt)",
    under a stored Broken out too). The payload carries the SHEET's answers and figures as they are:
    they are what tells the server whether there is any tax to break out."""
    total, sales, remodel, tx, rm = FIGURES[figure]
    r = screen[f"block/{work_type}/{audience}/{layout}/{figure}"]
    rows = _from_page(r)
    where = f"{work_type}/{audience} {layout} {figure}: {rows['all']!r}"
    tk = r["payload"]["values"]
    assert (tk["price_taxable"], tk["price_remodel_on"]) == (tx, rm), where
    assert (tk["material_tax_formatted"], tk["tax_amount_formatted"], tk["total_formatted"]) == (
        main._fmt_usd(sales), main._fmt_usd(remodel), main._fmt_usd(total)), where
    p = r["painted"]
    assert rows["base"] == _usd(p["base"]), f"screen {p['base']!r} vs document — {where}"
    assert rows["base_line"].endswith(tk["base_tax_phrase"] or "as described above"), where
    doc_rows = {k for k in ("material", "remodel", "total") if k in rows}
    shown = {k for k in ("material", "remodel", "total") if tk[f"price_rows_{k}"]}
    assert doc_rows == shown, f"screen rows {shown} vs document {doc_rows} — {where}"
    for k, tok in (("material", "material_tax_formatted"), ("remodel", "tax_amount_formatted"),
                   ("total", "total_formatted")):
        if k in doc_rows:
            assert rows[k] == _usd(tk[tok]), f"{k} row — {where}"
    # Where the file mounts the rows the page paints, each prints as painted, word for word.
    missing = [ln for ln in _drawn(r) if ln not in rows["all"]]
    assert not missing, f"drawn but not printed: {missing} — {where}"


@needs_node
@pytest.mark.parametrize("case", [f"{kind}/{wt}/{aud}/{lay}" for kind in ("options", "deduct")
                                  for wt, aud in OPTION_TEMPLATES for lay in LAYOUTS]
                         + [f"{kind}/{lay}" for kind in ("combo-lines", "combo-polish-exempt")
                            for lay in LAYOUTS])
def test_the_payload_the_page_composes_prints_every_line_it_draws(screen, case):
    """The same loop over the lines under and instead of the base: each option (one line, its own
    tab), each Add/Deduct, the manual line, and a combo's Option 1 / Option 2 lines off the priced
    tabs, which follow the layout as the base does — each one the page draws prints, word for word."""
    r = screen[case]
    rows = _from_page(r)
    # Each case draws what it is about, or it proves nothing.
    assert (len(r["combo"]) >= 2) if case.startswith("combo-") else r["options"], (case, r["combo"], r["options"])
    missing = [ln for ln in _drawn(r) if ln not in rows["all"]]
    assert not missing, f"{case}: drawn but not printed: {missing} — document {rows['all']!r}"


# What a combo with no single base draws when its polish tab has no tax: the epoxy system breaks out
# under Broken out, and the polish system is one line, "(tax exempt)", with no Total of its own —
# each system is asked for itself (Hanz, 2026-09-28). Under one line, both one line.
_COMBO_POLISH_EXEMPT = {
    "BROKEN_OUT": ["$4,574.75 – Option 1: Epoxy flooring as described above",
                   "$125.25 – Material Sales Tax",
                   "$300 – Remodel Tax",
                   "$5,000 – Total",
                   "$1,307.50 – Option 2: Polished Concrete flooring as described above (tax exempt)"],
    "ONE_LINE": ["$5,000 – Option 1: Epoxy flooring as described above "
                 "(Remodel Tax AND material sales tax INCLUDED)",
                 "$1,307.50 – Option 2: Polished Concrete flooring as described above (tax exempt)"],
}


@needs_node
@pytest.mark.parametrize("layout", LAYOUTS)
def test_a_combo_system_with_no_tax_is_one_line_beside_one_that_breaks_out(screen, layout):
    """A combo's Option 1 / Option 2 lines are the base price, so they follow the base's layout, and
    each system answers for its own tab. Broken out (the default here, the combined base being
    taxed; a stored "EXEMPT" reads as that default): the epoxy system itemises and adds up, and the
    polish system — Taxable? No, Remodel Tax? No — prints its whole $1,307.50 and "(tax exempt)", no
    "$1,307.50 – Total" under it. The page draws it and the document prints what the page sends.

    Mutation: the no-tax line out of TWPrice.taxRule (the polish system grows a Total row)."""
    r = screen[f"combo-polish-exempt/{layout}"]
    drawn = [ln["text"] for ln in r["combo"]]
    assert drawn == _COMBO_POLISH_EXEMPT[_page_asks(layout, True, True)], drawn
    printed = _from_page(r)["all"]
    assert [ln for ln in drawn if ln not in printed] == [], (drawn, printed)
    assert [ln for ln in printed if ln.endswith("– Total")] == (
        ["$5,000 – Total"] if _page_asks(layout, True, True) == "BROKEN_OUT" else []), printed


@needs_node
def test_the_default_layout_follows_the_sheet_until_somebody_picks():
    """"if one of the taxes is set to yes then broken out should be the default option." A draft
    that never chose a layout follows the sheet; one that did keeps it; a draft saved before the
    control became layout-only is read by what it printed (Broken out stays Broken out, Included and
    Exempt were one line — on a GC/Gyp file, whose rows always printed, the default answers).

    A `tax_layout` "EXEMPT" (#573's pick, gone) is no answer: the draft reads as one that never
    chose, or by its old `tax_inclusion`, exactly as before #573 — never as a layout of its own. And
    what the layout ASKED FOR is not always what prints: the old Broken out on a sheet with no tax is
    still read as Broken out, and prints one line, "(tax exempt)" — the one intended change to an
    untouched old draft, with the same money."""
    blocks = _template_blocks("epoxy", "Direct")
    gc = _template_blocks("epoxy", "GC")
    base = {"work_type": "epoxy", "audience": "Direct", "blocks": blocks,
            "total": 6839.0, "sales_tax": 72.0, "remodel_tax": 0.0}
    cases = [
        dict(base, name="new, taxable", taxable=True, remodel_on=False),
        dict(base, name="new, remodel only", taxable=False, remodel_on=True, sales_tax=0.0, remodel_tax=40.0),
        dict(base, name="new, neither", taxable=False, remodel_on=False, sales_tax=0.0),
        dict(base, name="picked one line", taxable=True, remodel_on=False, tax_layout="ONE_LINE"),
        dict(base, name="stored EXEMPT", taxable=True, remodel_on=True, remodel_tax=40.0,
             tax_layout="EXEMPT"),
        dict(base, name="stored EXEMPT, legacy EXEMPT", taxable=True, remodel_on=False,
             tax_layout="EXEMPT", tax_inclusion="EXEMPT"),
        dict(base, name="stored EXEMPT on GC", audience="GC", blocks=gc, taxable=True,
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
    ran = {r["name"]: r for r in json.loads(p.stdout)}
    got = {name: r["layout"] for name, r in ran.items()}
    assert got == {
        "new, taxable": "BROKEN_OUT", "new, remodel only": "BROKEN_OUT", "new, neither": "ONE_LINE",
        "picked one line": "ONE_LINE", "stored EXEMPT": "BROKEN_OUT",
        "stored EXEMPT, legacy EXEMPT": "ONE_LINE", "stored EXEMPT on GC": "BROKEN_OUT",
        "legacy BROKEN_OUT": "BROKEN_OUT",
        "legacy INCLUDED": "ONE_LINE", "legacy EXEMPT": "ONE_LINE",
        "legacy GC INCLUDED": "BROKEN_OUT", "legacy GC EXEMPT, exempt job": "ONE_LINE",
    }, got
    # The old Broken out on a sheet with no tax: asked for, and printed as one line.
    old = ran["legacy BROKEN_OUT"]
    assert old["painted"]["base"] == "$6,839 – Epoxy flooring as described above (tax exempt)", old["painted"]
    assert not (old["painted"]["salesRowShown"] or old["painted"]["remodelRowShown"]
                or old["painted"]["totalRowShown"]), old["painted"]
    # A stored "EXEMPT" never prints a price without its tax: the base and its rows make the bid.
    ex = ran["stored EXEMPT"]["tokens"]
    assert (ex["tax_layout"], ex["base_bid_formatted"]) == ("BROKEN_OUT", "$6,727"), ex
    # And the document reads a legacy payload the same way (no tax_layout on it), and a stored
    # "EXEMPT" as it reads the same payload without one.
    for layout, legacy, free, tx, rm, want in [(None, "INCLUDED", False, True, False, "ONE_LINE"),
                                               (None, "EXEMPT", False, True, True, "ONE_LINE"),
                                               (None, "BROKEN_OUT", False, False, False, "BROKEN_OUT"),
                                               (None, "INCLUDED", True, True, False, "BROKEN_OUT"),
                                               (None, "EXEMPT", True, False, False, "ONE_LINE"),
                                               (None, "EXEMPT", True, True, False, "BROKEN_OUT"),
                                               ("EXEMPT", "EXEMPT", False, True, True, "ONE_LINE"),
                                               ("EXEMPT", "INCLUDED", True, True, False, "BROKEN_OUT"),
                                               ("EXEMPT", None, False, True, False, "ONE_LINE")]:
        assert price_rules.layout_for(layout, legacy, free_rows=free, taxable=tx,
                                      remodel_on=rm) == want, (layout, legacy, free, tx, rm)


# ── (5) the TAX control: two layouts to pick, "Tax exempt" shown only off the sheet ────────────
_HTML = (FRONTEND / "proposal-review.html").read_text(encoding="utf-8")
_EXEMPT_TITLE = re.compile(r"estimate sheet.*Taxable\?.*Remodel Tax\?.*No", re.S)


def _tax_select_options():
    """The <option>s of the real #tax-treatment-select, as the page ships them."""
    m = re.search(r'<select id="tax-treatment-select">(.*?)</select>', _HTML, re.S)
    assert m, "proposal-review.html has no #tax-treatment-select"
    out = []
    for attrs, label in re.findall(r"<option\b([^>]*)>([^<]*)</option>", m.group(1)):
        v = re.search(r'value="([^"]*)"', attrs)
        out.append({"value": v.group(1) if v else label, "label": label,
                    "hidden": bool(re.search(r"\bhidden\b", attrs)),
                    "disabled": bool(re.search(r"\bdisabled\b", attrs))})
    return out


def _drive(**case):
    """Run the TAX control through the real wireRibbonTax and refreshPriceDisplay (pickFlow)."""
    c = dict({"name": "tax-control", "work_type": "epoxy", "audience": "Direct",
              "blocks": _template_blocks("epoxy", "Direct"), "select_options": _tax_select_options()},
             **case)
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], input=json.dumps([c]),
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)[0]["pick"]


def test_the_tax_control_ships_two_layouts_and_a_tax_exempt_that_starts_out_of_reach():
    """Hanz, 2026-09-28: exempt is set on the "Estimate sheet only". The select offers One line and
    Broken out; its "Tax exempt" is only the display of a base whose sheet says No to both taxes,
    and ships hidden and disabled, so nobody can pick it before the first repaint either."""
    assert _tax_select_options() == [
        {"value": "ONE_LINE", "label": "One line", "hidden": False, "disabled": False},
        {"value": "BROKEN_OUT", "label": "Broken out", "hidden": False, "disabled": False},
        {"value": "EXEMPT", "label": "Tax exempt", "hidden": True, "disabled": True},
    ]


@needs_node
def test_on_a_taxed_sheet_the_control_picks_a_layout_and_never_stores_tax_exempt():
    """Hanz's Test33 ($6,839, $72 material sales tax): the select is usable, shows the Broken-out
    default, and a person can choose One line or Broken out — never Tax exempt, which stays hidden
    and disabled. Picking One line runs the page's own change handler (wireRibbonTax, lifted
    verbatim): it stores the draft's top-level `tax_layout` "ONE_LINE" and fires the form's `input`.
    A script forcing the select to "EXEMPT" and firing `change` stores NOTHING and the repaint puts
    the select back. A reload paints the saved pick. Then the sheet changes under it — Taxable? goes
    to No (a base pick, a re-priced estimate) — and the repaint shows "Tax exempt", disabled, with
    its reason in the tooltip. The estimate sheet's cells are never written.

    Mutations: the handler storing "EXEMPT" (#573's coercion); the repaint leaving the Tax exempt
    option choosable on a taxed sheet."""
    got = _drive(total=6839.0, sales_tax=72.0, remodel_tax=0.0, taxable=True, remodel_on=False,
                 pick="ONE_LINE", force="EXEMPT",
                 reflag={"proposal_taxable": False, "proposal_sales_tax": 0})
    assert got["wired"] == 1, "the TAX select has no change handler"
    assert got["painted"] == {"value": "BROKEN_OUT", "disabled": False, "title": "",
                              "choosable": ["ONE_LINE", "BROKEN_OUT"]}, got["painted"]
    assert got["picked"] is True and got["repainted"]["value"] == "ONE_LINE", got
    assert got["forced"] == {"value": "ONE_LINE", "disabled": False, "title": "",
                             "choosable": ["ONE_LINE", "BROKEN_OUT"]}, got["forced"]
    assert got["saved"] == [{"tax_layout": "ONE_LINE"}], got["saved"]
    assert got["moduleState"] == "ONE_LINE" and got["inputs"] == ["input"], got
    assert got["base"] == "$6,839 – Epoxy flooring as described above (material sales tax INCLUDED)", got
    assert got["tokens"]["tax_layout"] == "ONE_LINE", got["tokens"]
    assert got["reloaded"]["value"] == "ONE_LINE", "a reload does not show the saved pick"
    assert got["cellsUntouched"] is True, "the TAX control wrote the estimate sheet"
    # The sheet now says No to both: the select follows it.
    r = got["reflagged"]
    assert (r["value"], r["disabled"], r["choosable"]) == ("EXEMPT", True, []), r
    assert _EXEMPT_TITLE.search(r["title"]), r["title"]
    assert got["reflaggedBase"] == "$6,839 – Epoxy flooring as described above (tax exempt)", got
    assert got["reflaggedRows"] == [], got["reflaggedRows"]


@needs_node
def test_on_a_sheet_with_no_tax_the_control_shows_tax_exempt_disabled_whatever_is_stored():
    """Taxable? No and Remodel Tax? No, on a draft that stored Broken out (the bug case): the select
    shows "Tax exempt", selected and disabled, with a tooltip saying it is set on the estimate sheet
    (Taxable? and Remodel Tax? are No); nothing on it can be chosen, so nothing is stored. The base
    line is the whole bid, "(tax exempt)", no row; the payload says one line. A reload shows the same.
    Then the sheet gains a tax (Taxable? Yes, $72): the select comes back usable, Tax exempt out of
    reach again, and the stored Broken out is back in force — the pick was never overwritten.

    Mutation: the repaint leaving the select enabled on a sheet with no tax."""
    got = _drive(total=6307.0, sales_tax=0.0, remodel_tax=0.0, taxable=False, remodel_on=False,
                 tax_layout="BROKEN_OUT", pick="ONE_LINE",
                 reflag={"proposal_taxable": True, "proposal_sales_tax": 72})
    p = got["painted"]
    assert (p["value"], p["disabled"], p["choosable"]) == ("EXEMPT", True, []), p
    assert _EXEMPT_TITLE.search(p["title"]), p["title"]
    assert got["picked"] is False, "a person picked a layout on a disabled select"
    assert got["saved"] == [] and got["inputs"] == [] and got["moduleState"] == "BROKEN_OUT", got
    assert got["base"] == "$6,307 – Epoxy flooring as described above (tax exempt)", got["base"]
    assert got["rowsShown"] == [], got["rowsShown"]
    assert got["tokens"] == {"tax_layout": "ONE_LINE", "tax_inclusion": "INCLUDED",
                             "base_bid_formatted": "$6,307", "base_tax_phrase": "(tax exempt)"}, got["tokens"]
    assert (got["reloaded"]["value"], got["reloaded"]["disabled"]) == ("EXEMPT", True), got["reloaded"]
    assert got["reloadedBase"] == got["base"], got
    # The sheet gains a tax: the stored Broken out prints again.
    r = got["reflagged"]
    assert r == {"value": "BROKEN_OUT", "disabled": False, "title": "",
                 "choosable": ["ONE_LINE", "BROKEN_OUT"]}, r
    assert got["reflaggedBase"] == "$6,235 – Epoxy flooring as described above", got["reflaggedBase"]
    assert got["reflaggedRows"] == ["sales-tax-row", "total-row"], got["reflaggedRows"]
