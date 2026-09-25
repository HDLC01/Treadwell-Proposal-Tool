"""ONE RULE, TWO LANGUAGES: frontend/js/price-lines-core.js and backend/price_rules.py.

The editor has to show the estimator the price block before anything is generated, and the document
has to print it from a payload that may have been frozen weeks earlier; neither side can borrow the
other's code. So the rule is written twice, kept small and free of the template, and this module
EXECUTES both over the same matrix — every combination of the sheet's two tax answers, both layouts,
cents that do not round cleanly, the legacy readings of the old three-way control, and the marker
substitution an edited price line goes through — and demands the same answer from each.

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
           (0, 0, 0), (100, 150, 0), ("6,307.50", "$125.25", None), (7696, None, 500)]
FLAGS = [True, False, None]
LEGACY = [None, "", "INCLUDED", "EXEMPT", "EXCLUDED", "BROKEN_OUT", "Broken Out", "ITEMIZED"]
LAYOUT = [None, "", "ONE_LINE", "BROKEN_OUT", "garbage"]
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
        if (c.kind === "rule") return P.taxRule({ total: c.total, sales_tax: c.sales, remodel: c.remodel,
                                                  taxable: c.taxable, remodel_on: c.remodel_on }, c.broken);
        if (c.kind === "layout") return P.layoutFor(c.layout, c.legacy, c.free, c.taxable, c.remodel_on);
        if (c.kind === "resolve") return P.resolveLine(c.text, c.amount, c.phrase);
        if (c.kind === "phrase") return P.phraseFor(c.taxable, c.remodel_on);
      });
      console.log(JSON.stringify(out));
    """, str(CORE)], input=json.dumps(expr_cases), capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _py_rule(c):
    r = price_rules.tax_rule(c["total"], c["sales"], c["remodel"], taxable=c["taxable"],
                             remodel_on=c["remodel_on"], broken=c["broken"])
    return {k: r[k] for k in ("broken", "taxable", "remodel_on", "total_cents", "sales_cents",
                              "remodel_cents", "base_cents", "phrase", "material", "remodel", "total")}


@needs_node
def test_the_tax_rule_is_the_same_rule_in_both_languages():
    cases = [{"kind": "rule", "total": t, "sales": s, "remodel": r, "taxable": tx,
              "remodel_on": rm, "broken": b}
             for (t, s, r), tx, rm, b in itertools.product(FIGURES, FLAGS, FLAGS, [True, False])]
    js = _node(cases)
    for c, j in zip(cases, js):
        py = _py_rule(c)
        assert {k: j[k] for k in py} == py, c


@needs_node
def test_the_layout_reading_is_the_same_in_both_languages():
    """Every explicit value either side can meet. (A payload with NEITHER field is the one place the
    two differ on purpose: the page has never been told — the default follows the sheet — while a
    payload that reaches the document without the field is hand-built or from an old page, which
    always carried it, and reads as INCLUDED.)"""
    cases = [{"kind": "layout", "layout": lay, "legacy": leg, "free": free, "taxable": tx,
              "remodel_on": rm}
             for lay, leg, free, tx, rm in itertools.product(LAYOUT, [l for l in LEGACY if l], [True, False],
                                                              [True, False], [True, False])]
    js = _node(cases)
    for c, j in zip(cases, js):
        py = price_rules.layout_is_broken(c["layout"], c["legacy"], free_rows=c["free"],
                                          taxable=c["taxable"], remodel_on=c["remodel_on"])
        assert (j == "BROKEN_OUT") is py, c


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


def test_no_flag_and_no_sales_figure_reads_as_taxable():
    """A hand-built payload or an old room that never said what its sales tax was has not said the
    job is exempt — it printed "(material sales tax INCLUDED)" before and still does."""
    assert price_rules.tax_rule(8310, None, 0)["phrase"] == "(material sales tax INCLUDED)"
    assert price_rules.tax_rule(8310, 0, 0)["phrase"] == "(tax exempt)"
