"""A price line saved in the OLD shape prints one line to a paragraph, the way the editor shows it.

The editor of before 2026-09-25 stored a re-worded price line and whatever was typed round it as ONE
string (`price_overrides.lines`), line breaks and all. Four of the 24 live production drafts hold
one (read-only replay of every live draft through production code and the 2026-09-26 release):
Carson Ross Aquatic Center Locker Room's option "\\n$23,115 – …\\n\\n", David Dyer Residence's
"\\n$24,911 – …", two more with blank lines after the price. Production printed each as one
paragraph with <w:br/> breaks, which read fine while the price box had no bullets. The release
bullets every money line (Kyle's REBID red square, numId 3 level 0), so a leading break left the
square ALONE on a blank first line with the price on the line under it, unbulleted, and the
trailing breaks sat inside the bulleted paragraph. Carson Ross and David Dyer are SENT proposals:
their customers would have seen it on the next re-render.

The editor already lays such a line out on load (TWPrice.migrateLine): the price line on its own,
the lines typed round it as lines of their own. A document built from a payload the editor never
re-saved (the portal's customer PDF, a pinned revision, To Dropbox of an old payload) now does the
same (price_rules.split_legacy_line): a blank line is a blank line with no bullet, the price line is
the bulleted paragraph, a line with words typed round it is its "o" sub-line. Every character
prints exactly as saved and in the same order; nothing is re-priced; a payload in the new shape
(`lines2`, `before`, `after`) is not touched.

One consequence, measured on the replay: the text-box shrink (`_estimate_txbx_fit`) counts lines by
text length and never counted a <w:br/>, so it now counts the blank lines it used to miss. Carson
Ross's price box goes from 9pt to 7.5pt in Word's copy, David Dyer's to 8.5pt: the size the editor
shows for the same draft once it has laid the line out (POST /api/proposal-fit runs this render).

EXECUTED: the split runs beside the real migrateLine under node over the same strings, the five
production strings included; the document half runs the real renderer (main._render_documents)
and reads the .docx back, in the text box and in its VML twin.
"""
import io
import json
import pathlib
import shutil
import subprocess

import docx
import pytest
from docx.oxml.ns import qn
from starlette.requests import Request

import main
import price_rules
import proposal_writer as pw

CORE = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js" / "price-lines-core.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
AMT, TAX = "⟦amount⟧", "⟦tax⟧"

# The five strings the production drafts hold, exactly (2026-09-26, read-only).
CARSON_ROSS = ("\n$23,115 – Treadwell 3/16\" Urethne Cement Hybrid System (material sales tax EXCLUDED)"
               " — Includes 6\" Cove Base\n\n")
DAVID_DYER = "\n$24,911 – Treadwell 3/16\" Urethne Cement With Color Fast (SOLID COLOR) (material sales tax INCLUDED)"
DAVID_DYER_HEADING = "\nOption: 1/8\" Quartz Broadcast System (Includes Moisture Mitigation Primer)"
RUBBER_BASE = "$6,940 – Treadwell solid color epoxy system — Includes 4\" Rubber Base\n\n"
ADD_PRIMER = ("Add $4,757 – Moisture mitigation primer if relative humidity of concrete exceeds 75% (Testing"
              " to be performed prior to commencemnet of work)\n\n")
PRODUCTION = [CARSON_ROSS, DAVID_DYER, DAVID_DYER_HEADING, RUBBER_BASE, ADD_PRIMER]


# ── the split, beside the editor's ──────────────────────────────────────────────────────────────
# Strings × parts. The production strings hold at most one line with words, so their split is the
# same whatever the parts say; the made-up ones hold two or more, where each step of migrateLine's
# order decides a different line.
_SHAPES = PRODUCTION + [
    "$7,447 – Epoxy flooring as described above (material sales tax INCLUDED)\n\nTHis is a test send to Hanz",
    "\n\n$31,054 – Sealed Concrete Option Alternate\nTest Test option: $5000\n\n",
    "Includes $500 allowance, inside the $7,447\nBase bid $7,447 for the warehouse",
    "$5,000 – a note that looks like a price line\n$7,447 – Epoxy flooring as described above",
    "$5,000 – a note that looks like a price line\n$9,860 – Polish alternative, a tab's own figure",
    "Polish alternative quoted separately at $9,860\n$1,870.00 – Epoxy flooring as described above",
    "$5,000 – a note that looks like a price line\n$1,870.00 – today's $1,870, frozen with cents",
    "A note\nAnother note\n(material sales tax INCLUDED) is what it says",
    "Deduct ($500) – VE for flake, in lieu of quartz\r\nas agreed with the owner\r\n",
    "  \n\t\n$1 – x\n\u00a0",
    "no figure on the first line\nnor on the second",
    "$0 – Total\n\nnote under a phantom",
    "\n\n",
    "\n \n\u3000",
    "$1 - a\n\n\nb",
    # Where JavaScript's idea of a blank line and Python's part: NEL is whitespace to Python and
    # words to JavaScript; the byte-order mark the other way round.
    "\n\x85\n",
    "\ufeff\n$1 – x",
    "one line, no break",
]
_PARTS = [
    {},
    {"amount": "$7,447", "phrase": "(material sales tax INCLUDED)", "slot": True, "candidates": ["$7,500"]},
    {"amount": "$1,870", "phrase": "", "candidates": ["$2,000"]},
    {"amount": "$23,115", "phrase": "(tax exempt)", "slot": True},
    {"amount": "Add $4,757", "phrase": ""},
    {"amount": "$6,307", "others": ["$9,860", "$7,447"]},
    {"amount": "$0", "zeroIsPhantom": True, "others": ["$1"]},
]


def _normalized(s):
    return s.replace("\r\n", "\n").replace("\r", "\n")


@needs_node
def test_the_document_splits_an_old_shape_line_where_the_editor_does():
    """price_rules.split_legacy_line against the real TWPrice.migrateLine, every string with every
    set of parts: the same lines above, the same price line, the same lines below — so the line the
    document bullets is the line the editor draws as the price line. And not a character lost,
    added or moved: the three parts put back together are the saved string.

    Where migrateLine finds no line with anything on it the document declines (None) and prints the
    string as it always has; where there is no line break there is nothing to lay out (None too),
    and migrateLine has nothing above or below. A phantom "$0 – Total" migrateLine drops is still
    printed by the document (its words are the payload's), on the same line."""
    cases = [[s, p] for s in _SHAPES for p in _PARTS]
    out = subprocess.run(
        ["node", "-e", "const P = require(process.argv[1]); let s = '';"
         "process.stdin.on('data', d => s += d); process.stdin.on('end', () => {"
         "console.log(JSON.stringify(JSON.parse(s).map(c => P.migrateLine(c[0], c[1])))); });", str(CORE)],
        input=json.dumps(cases), capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    js = json.loads(out.stdout)
    split_somewhere = 0
    for (s, parts), m in zip(cases, js):
        got = price_rules.split_legacy_line(s, parts.get("amount"), parts.get("phrase"),
                                            parts.get("candidates") or (), parts.get("others") or ())
        lines = _normalized(s).split("\n")
        if got is None:
            no_main = m["main"] is None and not m["before"] and not m["after"]
            assert no_main or len(lines) == 1, (s, parts, m)
            continue
        before, main_line, after = got
        assert (before, after) == (m["before"], m["after"]), (s, parts, m, got)
        assert main_line == lines[len(m["before"])], (s, parts, m, got)
        assert "\n".join(before + [main_line] + after) == _normalized(s), (s, got)
        split_somewhere += len(before) + len(after) > 0
    assert split_somewhere > 50, split_somewhere


def test_the_production_strings_split_the_same_whatever_the_parts():
    """The five production strings each hold one line with words, so the price line is that line
    under ANY parts — including `others`, the tab figures the proposal payload does not carry."""
    want = {CARSON_ROSS: ([""], CARSON_ROSS.strip("\n"), ["", ""]),
            DAVID_DYER: ([""], DAVID_DYER.strip("\n"), []),
            DAVID_DYER_HEADING: ([""], DAVID_DYER_HEADING.strip("\n"), []),
            RUBBER_BASE: ([], RUBBER_BASE.strip("\n"), ["", ""]),
            ADD_PRIMER: ([], ADD_PRIMER.strip("\n"), ["", ""])}
    for s in PRODUCTION:
        for p in _PARTS:
            got = price_rules.split_legacy_line(s, p.get("amount"), p.get("phrase"),
                                                p.get("candidates") or (), p.get("others") or ())
            assert got == want[s], (s, p, got)


# ── the document ────────────────────────────────────────────────────────────────────────────────
def _render(payload):
    req = Request({"type": "http", "method": "POST", "path": "/t", "headers": [], "query_string": b""})
    return main._render_documents(payload, req, want_estimate=False)["docx"]["content"]


def _text(p):
    """A paragraph's own text, its <w:br/> breaks as "\\n"."""
    out = []
    for el in p.iter(qn("w:t"), qn("w:br")):
        if any(True for _ in el.iterancestors(qn("w:txbxContent"))) != any(
                True for _ in p.iterancestors(qn("w:txbxContent"))):
            continue
        out.append("\n" if el.tag == qn("w:br") else (el.text or ""))
    return "".join(out)


def _copies(blob):
    """Each copy of the document's paragraphs a reader can print: the text boxes' mc:Choice (Word)
    and their VML mc:Fallback twin (an older reader), as [(text, (numId, ilvl) | None)]."""
    d = docx.Document(io.BytesIO(blob))
    choice, fallback = [], []
    for p in d.element.body.iter(qn("w:p")):
        if p.find(".//" + qn("w:txbxContent")) is not None:
            continue
        row = (_text(p), pw._para_num_ref(p))
        (fallback if any(True for _ in p.iterancestors(MC + "Fallback")) else choice).append(row)
    assert fallback, "the template has no VML twin to check"
    return choice, fallback


def _no_lone_square(blob):
    """No PRICE-list paragraph (numId 3) is blank or carries a line break, in either copy."""
    for rows in _copies(blob):
        bad = [t for t, ref in rows if ref and ref[0] == "3" and (not t.strip() or "\n" in t)]
        assert not bad, bad


def _run(rows, main_text):
    """The paragraphs round the price line: [(text, level or None)] from 3 above to 3 below."""
    i = [t for t, _r in rows].index(main_text)
    return i, [(t, int(r[1]) if r else None) for t, r in rows[max(0, i - 3):i + 4]]


def _vals(**over):
    v = {"project_name": "Legacy", "job_name": "Legacy", "city_state": "Olathe, KS", "texture": "Smooth",
         "system_name": "Treadwell 3/16\" Urethne Cement", "scope_notes": "s", "schedule_notes": "s",
         "exclusions": "e", "estimator_name": "Kyle", "bid_date_formatted": "9/26/26",
         "total_formatted": "$7,447", "material_tax_formatted": "$96", "tax_amount_formatted": "$0",
         "base_bid_formatted": "$7,447", "base_tax_phrase": "(material sales tax INCLUDED)",
         "tax_layout": "ONE_LINE", "price_taxable": True, "price_remodel_on": False,
         "epoxy_sf": "99", "sqft": "99"}
    v.update(over)
    return v


def _option(oid, total, **over):
    r = {"id": oid, "name": oid, "is_base": False, "show": True, "price_mode": "total",
         "option_desc": "Treadwell option " + oid, "base_total": 7447,
         "bid": {"total": total, "sales_tax": 0, "remodel": 0, "taxable": False, "remodel_on": False}}
    r.update(over)
    return r


def _payload(lines, **over):
    p = {"work_type": "epoxy", "audience": "Direct", "values": _vals(), "remodel": [],
         "rooms": [{"id": "Epoxy", "name": "Epoxy", "is_base": True,
                    "bid": {"total": 7447, "sales_tax": 96, "remodel": 0}},
                   _option("Copy1", 23115), _option("Copy2", 24911),
                   _option("Copy3", 12187, price_mode="deduct", base_total=7430)],
         "price_overrides": {"lines": lines}}
    p.update(over)
    return p


@pytest.mark.parametrize("key,legacy,above,below", [
    ("option:Copy1", CARSON_ROSS, [("", None)], [("", None), ("", None)]),
    ("option:Copy2", DAVID_DYER, [("", None)], []),
    ("option:Copy1", RUBBER_BASE, [], [("", None), ("", None)]),
    ("option:Copy3", ADD_PRIMER, [], [("", None), ("", None)]),
    ("option:Copy1", "\n$23,115 – Urethane cement\nIncludes 6\" Cove Base\n", [("", None)],
     [("Includes 6\" Cove Base", 1), ("", None)]),
], ids=["carson-ross", "david-dyer", "rubber-base", "add-primer", "typed-words-under-it"])
def test_an_old_shape_option_line_prints_one_line_to_a_paragraph(key, legacy, above, below):
    """The production option lines, each in both copies of the price box: a blank line typed above
    the price is a blank line with no bullet, the price line is the red square on its own, and the
    lines under it are blank lines (no bullet) or, with words on them, its "o" sub-line. The price
    line's words are exactly as saved."""
    blob = _render(_payload({key: legacy}))
    _no_lone_square(blob)
    main_text = legacy.strip("\n").split("\n")[0]
    for rows in _copies(blob):
        _i, got = _run(rows, main_text)
        at = got.index((main_text, 0))
        assert got[at - len(above):at] == above, got
        assert got[at - len(above) - 1][0] != "", got      # nothing more above it than was typed
        assert got[at + 1:at + 1 + len(below)] == below, got


def test_old_shape_base_tax_rows_and_total_print_one_line_to_a_paragraph():
    """The rows the writer rewrites in place (the base line, Material Sales Tax, the Total) carry
    their split lines as paragraphs of their own, cloned from the row: a blank one unbulleted, one
    with words his "o" sub-line."""
    blob = _render(_payload({
        "base": "\n$7,447 – Epoxy flooring in the warehouse (material sales tax INCLUDED)\n\nold note",
        "sales_tax": "$96 – Material Sales Tax\nper the state's rate",
        "total": "\n$7,447 – Total"}, values=_vals(tax_layout="BROKEN_OUT", base_bid_formatted="$7,351",
                                                  base_tax_phrase="")))
    _no_lone_square(blob)
    for rows in _copies(blob):
        _i, got = _run(rows, "$7,447 – Epoxy flooring in the warehouse (material sales tax INCLUDED)")
        at = got.index(("$7,447 – Epoxy flooring in the warehouse (material sales tax INCLUDED)", 0))
        assert got[at - 1] == ("", None) and got[at + 1:at + 3] == [("", None), ("old note", 1)], got
        _i, got = _run(rows, "$96 – Material Sales Tax")
        at = got.index(("$96 – Material Sales Tax", 0))
        assert got[at + 1] == ("per the state's rate", 1), got
        _i, got = _run(rows, "$7,447 – Total")
        at = got.index(("$7,447 – Total", 0))
        assert got[at - 1] == ("", None), got


def test_an_old_shape_manual_line_prints_one_line_to_a_paragraph():
    """The {{#price_line}} rows other than an option's own line: a manual "Add for" line. Broken out
    here, as the base is — an option's own Total row went with the rule that options are one line
    (Hanz, 2026-09-28), so a line stored under one (`option:Copy1:total`) prints nothing and leaves
    no lone square behind; no saved draft holds one."""
    blob = _render(_payload(
        {"manual:0": "\n$1,200 – Add for moisture mitigation\nif RH exceeds 75%",
         "option:Copy1:total": "\n$23,115 – Total for the hybrid"},
        values=_vals(tax_layout="BROKEN_OUT"),
        price_lines=[{"label": "Add for moisture mitigation", "amount": 1200}]))
    _no_lone_square(blob)
    for rows in _copies(blob):
        _i, got = _run(rows, "$1,200 – Add for moisture mitigation")
        at = got.index(("$1,200 – Add for moisture mitigation", 0))
        assert got[at - 1] == ("", None) and got[at + 1] == ("if RH exceeds 75%", 1), got
        assert not [t for t, _r in rows if "Total for the hybrid" in t], rows


def test_an_old_shape_alternate_row_prints_one_line_to_a_paragraph():
    """The ALTERNATE SYSTEM block's money rows, rewritten in place inside {{#alternate}}."""
    blob = _render(_payload(
        {"alt_total": "\n$30,000 – Total\nfor the alternate"},
        alternate_computed_bid={"alternate_full_bid": {"total_base_bid": 30000, "remodel_tax": 1000},
                                "alternate": {"label": "MACRO Flake"}},
        alternate_label="MACRO Flake"))
    _no_lone_square(blob)
    for rows in _copies(blob):
        _i, got = _run(rows, "$30,000 – Total")
        at = got.index(("$30,000 – Total", 0))
        assert got[at - 1] == ("", None) and got[at + 1] == ("for the alternate", 1), got


def test_an_old_shape_combo_line_prints_one_line_to_a_paragraph():
    """A combo payload composed before the combo lines carried their keys: the old page sent the
    old-shape line itself as the label."""
    blob = _render({"work_type": "combo", "audience": "Direct", "values": _vals(), "remodel": [],
                    "combo_options": [
                        {"label": "\n$10,000 – Option 1: Epoxy flooring as described above\nkitchen only\n",
                         "amount_formatted": ""},
                        {"label": "$5,000 – Option 2: Polished Concrete flooring as described above",
                         "amount_formatted": ""}]})
    _no_lone_square(blob)
    for rows in _copies(blob):
        _i, got = _run(rows, "$10,000 – Option 1: Epoxy flooring as described above")
        at = got.index(("$10,000 – Option 1: Epoxy flooring as described above", 0))
        assert got[at - 1] == ("", None), got
        assert got[at + 1:at + 3] == [("kitchen only", 1), ("", None)], got
        assert got[at + 3] == ("$5,000 – Option 2: Polished Concrete flooring as described above", 0), got


def test_the_price_line_is_the_one_the_editor_picks_when_two_look_like_one():
    """Two price-shaped lines in one old-shape line: the price line is the one priced at one of the
    line's own figures, as migrateLine reads it — here the figure an old line froze in under one
    line, today's Total, where the base line now prints its pre-tax amount Broken out (the editor's
    `candidates`: the base's Total, an option's own tax-inclusive total). The other is a line typed
    above it. An option is one line, its whole $23,115 (2026-09-28), so its own figure answers."""
    note = "$5,000 – a note that reads like a price line"
    blob = _render(_payload(
        {"base": note + "\n$7,447 – Epoxy flooring in the warehouse",
         "option:Copy1": note + "\n$23,115 – Hybrid as described above"},
        values=_vals(tax_layout="BROKEN_OUT", base_bid_formatted="$7,351", base_tax_phrase=""),
        rooms=[{"id": "Epoxy", "name": "Epoxy", "is_base": True,
                "bid": {"total": 7447, "sales_tax": 96, "remodel": 0}},
               _option("Copy1", 23115, bid={"total": 23115, "sales_tax": 1000, "remodel": 0,
                                            "taxable": True, "remodel_on": False})]))
    _no_lone_square(blob)
    for rows in _copies(blob):
        for line in ("$7,447 – Epoxy flooring in the warehouse", "$23,115 – Hybrid as described above"):
            _i, got = _run(rows, line)
            at = got.index((line, 0))
            assert got[at - 1] == (note, 1), got


def test_a_bullet_stored_for_the_line_under_it_is_the_split_lines():
    """The editor makes the split lines the line's own `after` when it has none there yet, so a
    bullet the ribbon stored for that position is theirs (after_props, by position); lines typed
    under it since keep theirs, and print after the split ones, nearest their own row last."""
    blob = _render(_payload({}, price_overrides={
                                "lines": {"option:Copy1": "\n$23,115 – Urethane cement\nold note",
                                          "option:Copy2": "$24,911 – Quartz\nold note two",
                                          "base": "$7,447 – Epoxy flooring, warehouse\nold base note"},
                                "after": {"option:Copy2": ["typed since"], "base": ["typed since too"]},
                                "after_props": {"option:Copy1": [{"bullet": False, "indent": 576}],
                                                "option:Copy2": [{"bullet": True, "level": 0}]}}))
    for rows in _copies(blob):
        _i, got = _run(rows, "$7,447 – Epoxy flooring, warehouse")
        at = got.index(("$7,447 – Epoxy flooring, warehouse", 0))
        assert got[at + 1:at + 3] == [("old base note", 1), ("typed since too", 1)], got
        _i, got = _run(rows, "$23,115 – Urethane cement")
        at = got.index(("$23,115 – Urethane cement", 0))
        assert got[at + 1] == ("old note", None), got
        _i, got = _run(rows, "$24,911 – Quartz")
        at = got.index(("$24,911 – Quartz", 0))
        assert got[at + 1:at + 3] == [("old note two", 1), ("typed since", 0)], got


def test_a_line_in_the_new_shape_is_not_touched():
    """`lines2` is the editor's own shape: whatever it holds prints as it did, a break included —
    and it wins over an old-shape line still stored under the same key."""
    blob = _render(_payload({}, price_overrides={
        "lines2": {"option:Copy1": AMT + " – Urethane cement\nas agreed"},
        "lines": {"option:Copy1": "\n$20,000 – stale words\n"}}))
    for rows in _copies(blob):
        assert ("$23,115 – Urethane cement\nas agreed", ("3", "0")) in rows, rows
        assert not any("stale words" in t for t, _r in rows), rows
