"""ONE RULE, TWO LANGUAGES: frontend/js/price-lines-core.js and backend/price_rules.py.

The editor has to show the estimator the price block before anything is generated, and the document
has to print it from a payload that may have been frozen weeks earlier; neither side can borrow the
other's code. So the rule is written twice, kept small and free of the template, and this module
EXECUTES both over the same matrix — every combination of the sheet's two tax answers, both layouts
and every stored value that is not one (a stored "EXEMPT", garbage), cents that do not round cleanly,
the legacy readings of the old three-way control, and the marker substitution an edited price line
goes through — and demands the same answer from each.

Hanz, 2026-09-28: whether a job is tax exempt is the estimate sheet's answer and nobody else's
("Estimate sheet only"), and a tax-exempt job is one line — "there is no tax to be broken out". So
the no-tax row of the matrix is asked under every stored layout and every legacy value, and has to
come out one line, its whole total, "(tax exempt)", no row, in both languages. The "Tax exempt"
pick of #573, which backed the taxes out of a price the sheet kept them in, is gone: a stored
"EXEMPT" reads as a value that is not a layout.

A comment promising the two agree is worth nothing; this is what makes it true.
"""
import itertools
import json
import pathlib
import shutil
import subprocess

import pytest

import price_rules

CORE = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js" / "price-lines-core.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

FIGURES = [(6839, 72, 0), (6307.5, 125.25, 471.13), (21260, 674, 1226), (1476, 0, 90),
           (0, 0, 0), (100, 150, 0), ("6,307.50", "$125.25", None), (7696, None, 500),
           (16015, 0, 0)]
FLAGS = [True, False, None]
LEGACY = [None, "", "INCLUDED", "EXEMPT", "EXCLUDED", "BROKEN_OUT", "Broken Out", "ITEMIZED"]
# Every value a draft or payload can hold in `tax_layout`: the two layouts, nothing, the #573
# "EXEMPT" pick (no page writes it now; a hand-built payload could carry one) and garbage.
LAYOUT = [None, "", "ONE_LINE", "BROKEN_OUT", "EXEMPT", " exempt ", "garbage"]
# What a caller hands the rule for its layout: the yes/no "broken out?" the older callers pass, or
# the layout itself, in any case, or something that is not one (which reads as one line).
MODES = [True, False, "ONE_LINE", "BROKEN_OUT", "EXEMPT", "exempt", "", "garbage"]
RULE_KEYS = ("layout", "broken", "taxable", "remodel_on", "total_cents", "sales_cents",
             "remodel_cents", "base_cents", "phrase", "material", "remodel", "total")
LINES = [
    ("⟦amount⟧ – Epoxy flooring as described above ⟦tax⟧", "$6,767", ""),
    ("⟦amount⟧ – Epoxy flooring as described above ⟦tax⟧", "$6,839", "(material sales tax INCLUDED)"),
    ("⟦amount⟧ – Epoxy flooring, warehouse only ⟦tax⟧ — per addendum 2", "$1", "(tax exempt)"),
    ("⟦amount⟧ – Epoxy flooring, warehouse only ⟦tax⟧ — per addendum 2", "$1", ""),
    ("$9,999 – typed by hand", "$6,839", "(material sales tax INCLUDED)"),
    ("⟦tax⟧", "", ""),
    ("no markers at all", "$5", "(x)"),
]


def _node(expr_cases):
    p = subprocess.run(["node", "-e", """
      const P = require(process.argv[1]);
      const cases = JSON.parse(require("fs").readFileSync(0, "utf8"));
      const out = cases.map(c => {
        const sys = { total: c.total, sales_tax: c.sales, remodel: c.remodel,
                      taxable: c.taxable, remodel_on: c.remodel_on };
        if (c.kind === "rule") return P.taxRule(sys, c.mode);
        if (c.kind === "layout") return P.layoutFor(c.layout, c.legacy, c.free, c.taxable, c.remodel_on);
        // What the page prints for a draft holding this layout: the sheet's two answers resolved by
        // the rule, the stored layout read against them, the rule asked for that layout.
        if (c.kind === "stored") {
          const f = P.taxRule(sys, false);
          return P.taxRule(sys, P.layoutFor(c.layout, c.legacy, c.free, f.taxable, f.remodel_on));
        }
        if (c.kind === "resolve") return P.resolveLine(c.text, c.amount, c.phrase);
        if (c.kind === "phrase") return P.phraseFor(c.taxable, c.remodel_on);
      });
      console.log(JSON.stringify(out));
    """, str(CORE)], input=json.dumps(expr_cases), capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _py_rule(c):
    """The document's half, asked the way its callers ask: a layout string as `layout=`, the older
    yes/no as `broken=` (TWPrice.taxRule takes either in its one second argument)."""
    how = {"layout": c["mode"]} if isinstance(c["mode"], str) else {"broken": c["mode"]}
    r = price_rules.tax_rule(c["total"], c["sales"], c["remodel"], taxable=c["taxable"],
                             remodel_on=c["remodel_on"], **how)
    return {k: r[k] for k in RULE_KEYS}


def _py_stored(c):
    """What the document prints for a payload holding this layout, composed as main._generate
    composes it: the sheet's answers, layout_for over them, the rule asked for that layout."""
    f = price_rules.tax_rule(c["total"], c["sales"], c["remodel"], taxable=c["taxable"],
                             remodel_on=c["remodel_on"])
    lay = price_rules.layout_for(c["layout"], c["legacy"], free_rows=c["free"],
                                 taxable=f["taxable"], remodel_on=f["remodel_on"])
    r = price_rules.tax_rule(c["total"], c["sales"], c["remodel"], taxable=c["taxable"],
                             remodel_on=c["remodel_on"], layout=lay)
    return {k: r[k] for k in RULE_KEYS}


def _stored_cases(legacies):
    return [{"kind": "stored", "total": t, "sales": s, "remodel": r, "taxable": tx, "remodel_on": rm,
             "layout": lay, "legacy": leg, "free": free}
            for (t, s, r), tx, rm, lay, leg, free in itertools.product(
                FIGURES, FLAGS, FLAGS, LAYOUT, legacies, [True, False])]


def _is_one_line_exempt(r, where):
    """One line, the whole total, "(tax exempt)", and not one row — Hanz's tax-exempt job."""
    assert (r["layout"], r["broken"]) == ("ONE_LINE", False), where
    assert r["base_cents"] == r["total_cents"], where
    assert r["phrase"] == "(tax exempt)", where
    assert (r["material"], r["remodel"], r["total"]) == (False, False, False), where


@needs_node
def test_the_tax_rule_is_the_same_rule_in_both_languages():
    cases = [{"kind": "rule", "total": t, "sales": s, "remodel": r, "taxable": tx,
              "remodel_on": rm, "mode": m}
             for (t, s, r), tx, rm, m in itertools.product(FIGURES, FLAGS, FLAGS, MODES)]
    js = _node(cases)
    for c, j in zip(cases, js):
        py = _py_rule(c)
        assert {k: j[k] for k in py} == py, c


@needs_node
def test_the_layout_reading_is_the_same_in_both_languages():
    """Every explicit value either side can meet, and the same one of the two layouts out of both.
    (A payload with NEITHER field is the one place the two differ on purpose: the page has never
    been told — the default follows the sheet — while a payload that reaches the document without
    the field is hand-built or from an old page, which always carried it, and reads as INCLUDED.)"""
    cases = [{"kind": "layout", "layout": lay, "legacy": leg, "free": free, "taxable": tx,
              "remodel_on": rm}
             for lay, leg, free, tx, rm in itertools.product(LAYOUT, [l for l in LEGACY if l], [True, False],
                                                              [True, False], [True, False])]
    js = _node(cases)
    for c, j in zip(cases, js):
        py = price_rules.layout_for(c["layout"], c["legacy"], free_rows=c["free"],
                                    taxable=c["taxable"], remodel_on=c["remodel_on"])
        assert j == py, c
        assert py in ("ONE_LINE", "BROKEN_OUT"), c


@needs_node
def test_a_stored_exempt_is_not_a_layout_in_either_language():
    """Hanz, 2026-09-28: exempt is set on the estimate sheet only. The #573 "Tax exempt" pick is gone,
    and a `tax_layout` "EXEMPT" left on a hand-built payload (none on staging or prod) is no answer at
    all: it reads EXACTLY as the same draft or payload with no `tax_layout` — its old `tax_inclusion`,
    or the default — as layoutFor / layout_for read it before #573. Never as a layout of its own, so
    nothing can back the taxes out of a price the sheet keeps them in.

    Mutation: "EXEMPT" back among the layouts either side accepts (LAYOUTS / layoutFor's list)."""
    cases = [{"kind": "layout", "layout": lay, "legacy": leg, "free": free, "taxable": tx,
              "remodel_on": rm}
             for lay, leg, free, tx, rm in itertools.product(["EXEMPT", " exempt ", None], LEGACY,
                                                              [True, False], [True, False], [True, False])]
    js = _node(cases)
    got = {}
    for c, j in zip(cases, js):
        py = price_rules.layout_for(c["layout"], c["legacy"], free_rows=c["free"],
                                    taxable=c["taxable"], remodel_on=c["remodel_on"])
        assert "EXEMPT" not in (j, py), c
        got[(c["layout"], c["legacy"], c["free"], c["taxable"], c["remodel_on"])] = (j, py)
    for (lay, leg, free, tx, rm), both in got.items():
        assert both == got[(None, leg, free, tx, rm)], (lay, leg, free, tx, rm)
    # Undecided on a taxed Direct draft: the page's default, Broken out; the document's reading of a
    # payload with no field, INCLUDED — one line with its whole tax-inclusive figure.
    assert got[("EXEMPT", None, False, True, False)] == ("BROKEN_OUT", "ONE_LINE")
    # The old three-way "EXEMPT" beside it: one line, as it printed.
    assert got[("EXEMPT", "EXEMPT", False, True, False)] == ("ONE_LINE", "ONE_LINE")


@needs_node
def test_every_stored_layout_prints_the_same_price_block_in_both_languages():
    """The composition itself — what the page draws and the document prints for a draft or payload
    holding each `tax_layout` value beside each legacy `tax_inclusion` — over the whole figure x flag
    matrix, in both languages. (Legacy values only where both sides were told one: see
    test_the_layout_reading_is_the_same_in_both_languages.)"""
    cases = _stored_cases([l for l in LEGACY if l])
    js = _node(cases)
    for c, j in zip(cases, js):
        py = _py_stored(c)
        assert {k: j[k] for k in py} == py, c


@needs_node
def test_a_sheet_with_no_tax_is_one_line_under_every_stored_layout_in_both_languages():
    """"If it's tax exempted then it should just be one line and not broken apart because there is no
    tax to be broken out." Every row of the matrix whose sheet says No to both taxes — the flags
    saying so, or no flag and figures of $0 — under every stored layout, legacy value (none and blank
    included) and template shape: one line, the whole total, "(tax exempt)", no Material Sales Tax,
    no Remodel Tax and no Total, on the page and in the document alike. A Broken out stored before
    the sheet said No, or by an old page, cannot split it into "$16,015" and "$16,015 – Total".

    Mutations: the no-tax line taken out of price_rules.tax_rule (Python prints a Total row), or out
    of TWPrice.taxRule (the page does)."""
    cases = _stored_cases(LEGACY)
    js = _node(cases)
    no_tax = 0
    for c, j in zip(cases, js):
        py = _py_stored(c)
        if py["taxable"] or py["remodel_on"]:
            continue
        no_tax += 1
        _is_one_line_exempt(py, ("document", c))
        _is_one_line_exempt(j, ("page", c))
    # Not vacuous: the no-tax rows are here, and they include the stored Broken outs.
    assert no_tax > 500, no_tax
    assert any(c["layout"] == "BROKEN_OUT" for c in cases), cases[:1]


@needs_node
def test_broken_out_on_a_sheet_with_no_tax_prints_one_line_in_both_languages():
    """The case this change is for, as it was verified on the page before it: TWPrice.taxRule(
    {total:'16015', sales_tax:'0', remodel:'0', taxable:false, remodel_on:false}, 'BROKEN_OUT') drew
    "$16,015 – Epoxy flooring as described above" and "$16,015 – Total". Asked for Broken out, the
    rule says what it prints — One line — so no caller can itemise it anyway.

    Mutations: as above, one language at a time."""
    sys16 = {"total": "16015", "sales": "0", "remodel": "0", "taxable": False, "remodel_on": False}
    for mode in ("BROKEN_OUT", True):
        [j] = _node([dict(sys16, kind="rule", mode=mode)])
        py = _py_rule(dict(sys16, mode=mode))
        for who, r in (("page", j), ("document", py)):
            _is_one_line_exempt(r, (who, mode))
            assert r["base_cents"] == 1601500, (who, r)


@needs_node
def test_remodel_only_broken_out_prints_no_material_row_in_both_languages():
    """Hanz, 2026-09-28: "If it's remodel tax we can also break it out, it just wouldn't have the
    material tax." Taxable? No, Remodel Tax? Yes, Broken out: the pre-tax line (the Total less the
    remodel tax only), a Remodel Tax row, the Total — and no Material Sales Tax row, even with a
    stale sales figure beside it.

    Mutation: the broken-out branch printing a Material Sales Tax row on a remodel-only tab (either
    language)."""
    for sales in (0, 125):
        c = {"total": 6307, "sales": sales, "remodel": 471, "taxable": False, "remodel_on": True,
             "mode": "BROKEN_OUT"}
        [j] = _node([dict(c, kind="rule")])
        py = _py_rule(c)
        for who, r in (("page", j), ("document", py)):
            assert (r["layout"], r["material"], r["remodel"], r["total"]) == (
                "BROKEN_OUT", False, True, True), (who, sales, r)
            assert r["base_cents"] == 630700 - 47100, (who, sales, r)
            assert r["phrase"] == "", (who, sales, r)


@needs_node
def test_an_edited_line_resolves_the_same_in_both_languages():
    cases = [{"kind": "resolve", "text": t, "amount": a, "phrase": p} for t, a, p in LINES]
    js = _node(cases)
    for c, j in zip(cases, js):
        assert j == price_rules.resolve_line(c["text"], c["amount"], c["phrase"]), c


@needs_node
def test_the_one_line_wording_is_hanzs_four_sentences_in_both_languages():
    cases = [{"kind": "phrase", "taxable": tx, "remodel_on": rm}
             for tx, rm in itertools.product([True, False], [True, False])]
    js = _node(cases)
    want = {(True, True): "(Remodel Tax AND material sales tax INCLUDED)",
            (True, False): "(material sales tax INCLUDED)",
            (False, True): "(Remodel Tax INCLUDED)",
            (False, False): "(tax exempt)"}
    for c, j in zip(cases, js):
        k = (c["taxable"], c["remodel_on"])
        assert j == price_rules.phrase_for(*k) == want[k], c


def test_broken_out_backs_the_taxes_out_of_the_bid_and_adds_up():
    """The bid is tax-inclusive: the rows are taken OUT of the Total, never added on top, and the
    printed figures sum to the cent. Hanz's Test33: $6,839 bid, $72 material sales tax, remodel off."""
    r = price_rules.tax_rule(6839, 72, 0, taxable=True, remodel_on=False, broken=True)
    assert (r["base_cents"], r["material"], r["remodel"], r["total"]) == (676700, True, False, True)
    r = price_rules.tax_rule(6307.5, 125.25, 471.13, taxable=True, remodel_on=True, broken=True)
    assert r["base_cents"] + r["sales_cents"] + r["remodel_cents"] == r["total_cents"] == 630750
    # A tax whose flag is off is not taken out, even with a stale figure beside it.
    r = price_rules.tax_rule(6307, 125, 471, taxable=False, remodel_on=True, broken=True)
    assert r["base_cents"] == 630700 - 47100 and not r["material"]


def test_no_layout_backs_a_tax_out_of_the_price_without_printing_it():
    """What #573's Tax exempt did, and what nothing may do now: a figure short of the tax-inclusive
    bid with no row to make it up. Under every layout value a caller can hand the rule, on every
    figure and flag, the base line plus the rows that print is the whole Total — a tax that is not
    shown is still in the price. Test33 asked for "EXEMPT" is $6,839 "(material sales tax
    INCLUDED)", as one line prints it.

    Mutation: the #573 EXEMPT branch back in price_rules.tax_rule (Test33 prints $6,767, no row)."""
    for (t, s, r), tx, rm, m in itertools.product(FIGURES, FLAGS, FLAGS, MODES):
        how = {"layout": m} if isinstance(m, str) else {"broken": m}
        got = price_rules.tax_rule(t, s, r, taxable=tx, remodel_on=rm, **how)
        printed = (got["base_cents"] + (got["sales_cents"] if got["material"] else 0)
                   + (got["remodel_cents"] if got["remodel"] else 0))
        if got["base_cents"] > 0:
            assert printed == got["total_cents"], ((t, s, r), tx, rm, m, got)
    r = price_rules.tax_rule(6839, 72, 0, taxable=True, remodel_on=False, layout="EXEMPT")
    assert (r["base_cents"], r["phrase"], r["total"]) == (683900, "(material sales tax INCLUDED)", False)


def test_no_flag_and_no_sales_figure_reads_as_taxable():
    """A hand-built payload or an old room that never said what its sales tax was has not said the
    job is exempt — it printed "(material sales tax INCLUDED)" before and still does."""
    assert price_rules.tax_rule(8310, None, 0)["phrase"] == "(material sales tax INCLUDED)"
    assert price_rules.tax_rule(8310, 0, 0)["phrase"] == "(tax exempt)"
