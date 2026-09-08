"""The four figures in the PRICE block have to add up, and the screen has to show the same ones.

Kyle, 2026-09-08, two reports with one cause:

    "the proposal says $6,182 and my estimate says $6,307"

and, found while chasing that, a GC Polish proposal printing

    Base Bid
    $6,307.00 – Polished Concrete & Joint Filler as described above (material sales tax INCLUDED)
      $125.00 – Material Sales Tax
        $0.00 – Remodel Tax
    $6,307.00 – Total

6,307 + 125 + 0 = 6,432, under a Total of 6,307. The Total was right; the itemisation could not
be reconciled by anyone holding a calculator.

ONE RULE FIXES BOTH: **the base line equals the Total minus whatever tax lines actually print.**

  · Kyle's four Direct files wrap their Material Sales Tax / Remodel rows in {{#tax_breakout}} /
    {{#remodel}}. In the default "INCLUDED" layout those rows are STRIPPED — nothing prints for
    the base to be net of — so the base line carries the whole tax-inclusive bid ($6,307). The
    page was subtracting the sales tax anyway, which is the $6,182 Kyle read: a $125 discount on
    the only price the document shows.
  · The three GC files and the Gyp file author the same rows as PLAIN paragraphs that no flag can
    strip. They always print, so the base line has to be ex-tax ($6,182) and 6,182 + 125 + 0 =
    6,307.

KEYED ON THE TEMPLATE'S SHAPE, NEVER ON THE AUDIENCE. `audience == "GC"` answers today's eight
files and silently mis-answers the ninth — the layout-keyed-vs-label-keyed hole PR #432/#433
closed for the remodel rate, and the reason the old `work_type == "gyp"` special case in
`_generate` never reached GC. `proposal_writer.free_tax_rows` reads it off the file, from the same
`in_block` walk `/api/proposal-template` serves the browser, so both halves answer from one source.

WHY IN DOLLARS, ON THE REAL ARTEFACTS. Every money case here fills a real template through the
real `/api/generate`, reads the printed strings back out of the .docx, and adds them up. A test
that asserted `base_bid_formatted` was computed by the right helper would pass on a helper handed
its arguments in the wrong order. The screen half runs the page's OWN two writers
(`refreshPriceDisplay` and `computeTokenValues`) in Node over the shapes walked out of those same
template files — see js/price-block-harness.js for why that is executed rather than grepped.

A GENERATE COSTS ~4s (it fills Kyle's 16-tab workbook too), so every document this module needs
is rendered ONCE in the `docs` fixture and read many times. The figure sweep runs where the
arithmetic lives; the shape x mode matrix runs on one figure set, the hardest one.
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
from fastapi.testclient import TestClient

import main
import proposal_writer as pw

client = TestClient(main.app)

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "price-block-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

# Kyle's Viracor figures, and the variations that move each printed row on its own. The last case
# carries cents because a remodel tax is a real percentage of a real number: the rule has to hold
# to the cent, not to the dollar.
#         name                 (total,   sales,  remodel)
FIGURES = {
    "no tax at all":     (6307.00,   0.00,   0.00),
    "sales tax only":    (6307.00, 125.00,   0.00),      # Kyle's own job
    "remodel tax only":  (6307.00,   0.00, 471.00),
    "both, to the cent": (6307.50, 125.25, 471.13),
}
# The figure set the shape x mode matrix runs on: both taxes, and neither is a round number.
HARDEST = "both, to the cent"

GC_TEMPLATES = [("polish", "GC"), ("epoxy", "GC"), ("sealer", "GC")]
DIRECT_TEMPLATES = [("epoxy", "Direct"), ("polish", "Direct"), ("combo", "Direct")]
ALL_TEMPLATES = GC_TEMPLATES + DIRECT_TEMPLATES + [("gyp", "Direct")]
MODES = ["INCLUDED", "BROKEN_OUT", "EXCLUDED"]

# Two figures are enough for the Direct cases: Kyle's own job, and the fractional one.
DIRECT_FIGURES = ["sales tax only", HARDEST]


def _needed():
    """Every (work_type, audience, mode, figure) this module reads a real document for, so the
    fixture renders each exactly once."""
    want = set()
    for wt, aud in GC_TEMPLATES:                       # (1) the reported defect
        want.update((wt, aud, "INCLUDED", f) for f in FIGURES)
    for wt, aud in DIRECT_TEMPLATES:                   # (2) Kyle's original report + the flip side
        want.update((wt, aud, "INCLUDED", f) for f in DIRECT_FIGURES)
        want.update((wt, aud, "BROKEN_OUT", f) for f in DIRECT_FIGURES)
    want.update(("gyp", "Direct", "INCLUDED", f) for f in FIGURES)   # (3) the removed special case
    for wt, aud in ALL_TEMPLATES:                      # (5) shape x mode, screen vs document
        want.update((wt, aud, m, HARDEST) for m in MODES)
    return sorted(want)


# ── reading the printed price block back off the .docx ───────────────────────
def _lines(docx_bytes):
    """Every non-empty paragraph of the generated document, once.

    `pw._own_text`, NOT a `.//w:t` join. A paragraph that merely ANCHORS a floating text box
    reports that box's entire contents as its own text under a recursive join — here, a 2,522-
    character run of NOTES and PRICE rows that happens to end in "– Total" and whose first dollar
    figure is the $4,500 additional-phase note. A price-row parser reading that gets a Total of
    $4,500 and calls the arithmetic broken while the document is perfectly correct. Same helper
    `iter_editable_blocks` uses, for the same reason.

    The PRICE box is also authored twice (mc:Choice + mc:Fallback) so a Word that cannot render
    the shape still shows the text; the Fallback copy is dropped so no row is counted twice."""
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
    """The number in a printed price string. Refuses rather than returning 0.0 — a row read as
    zero is how a broken price block looks balanced."""
    m = re.search(r"\$([\d,]+(?:\.\d+)?)", str(s))
    assert m, f"no dollar figure in {s!r}"
    return float(m.group(1).replace(",", ""))


def _price_rows(docx_bytes):
    """`{base, base_line, material, remodel, total}` — the figure on each PRICE row that PRINTED,
    keyed by that row's own static wording. A row the layout strips is ABSENT, which is the
    distinction the whole rule turns on, so it is reported as a missing key and never as 0.0."""
    rows = {}
    for line in _lines(docx_bytes):
        if re.search(r"–\s*Material Sales Tax$", line):
            rows.setdefault("material", _usd(line))
        elif re.search(r"–\s*(Kansas\s+)?Remodel Tax$", line):
            rows.setdefault("remodel", _usd(line))
        elif re.search(r"–\s*Total$", line):
            rows.setdefault("total", _usd(line))
        elif "as described above" in line and line.lstrip().startswith("$"):
            rows.setdefault("base", _usd(line))
            rows.setdefault("base_line", line)
    return rows


def _values(total, sales, remodel, mode):
    """A generate payload's `values`, formatted the way the page ships them — through the same
    `_fmt_usd` the document prints with, so the strings under test are the strings a customer
    reads."""
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
        # The Direct POLISH template's Total row is the whole-line {{total_label}} token, not
        # "{{total_formatted}} – Total" — so it has to be sent, spelled exactly as the page
        # spells it. FOUND WHILE WRITING THIS AND NOT FIXED HERE (reported instead): nothing
        # backfills `total_label`, so a caller that omits it prints a literal "{{total_label}}"
        # where the Total belongs, in a customer-facing document. The live browser path always
        # sends it; a REPLAY of a payload frozen without it (the on-demand customer PDF, a
        # revision's files, the To-Dropbox re-file) does not. `area_description` has the same
        # gap. Both are outside this fix.
        "total_label": f"{main._fmt_usd(total)} – Total",
        "lump_sum_formatted": main._fmt_usd(total - remodel),
        "lump_sum_label": f"{main._fmt_usd(total - remodel)} – Polished Concrete Flooring as described above",
        "area_description": "~3,000 sf of polished concrete flooring",
        # DELIBERATELY THE WRONG BASE FOR HALF THESE CASES: the unconditional ex-tax figure the
        # page used to send. `_generate` has to re-derive it from the template's own shape rather
        # than trust the payload, which is what keeps a replayed or hand-built payload correct.
        "base_bid_formatted": main._fmt_usd(total - sales - remodel),
        "tax_inclusion": mode,
        # gyp-only area tokens, so the gyp template never prints a raw {{token}} here
        "gyp_soft_sf": "3,000", "gyp_hard_sf": "0", "gyp_corridor_sf": "0",
        "gyp_soft_thickness": '3/4"', "gyp_hard_thickness": '1"',
        "gyp_corridor_thickness": '3/4"', "mobilizations_line": "1 Mobilization to Site.",
        "work_description": "per plans",
    }


# Rendered documents, memoized for the whole module. NOT a module-scoped fixture: conftest's
# `_bypass_auth` is function-scoped and autouse, so a module-scoped fixture runs OUTSIDE it and
# every /api/generate comes back 401. The `docs` fixture below is per-test (auth patched) and
# fills this dict on first use.
_DOCS: dict = {}


@pytest.fixture
def docs():
    """Every document this module reads, rendered once through the real /api/generate."""
    out = _DOCS
    if out:
        return out
    for wt, aud, mode, fig in _needed():
        total, sales, remodel = FIGURES[fig]
        body = {"work_type": wt, "audience": aud,
                "values": _values(total, sales, remodel, mode),
                # The {{#remodel}} region's own row, for the templates that HAVE one. The page
                # sends it only when a remodel tax applies, exactly like this.
                "remodel": ([{"amount_formatted": main._fmt_usd(remodel)}] if remodel else [])}
        r = client.post("/api/generate", json=body)
        assert r.status_code == 200, f"{wt}/{aud}/{mode}/{fig}: {r.text}"
        f = client.get(r.json()["docx_download_url"])
        assert f.status_code == 200, f.text
        out[(wt, aud, mode, fig)] = _price_rows(f.content)
    return out


# ── (1) the GC templates: four rows that always print, and always sum ────────
@pytest.mark.parametrize("work_type,audience", GC_TEMPLATES)
@pytest.mark.parametrize("figure", list(FIGURES))
def test_the_gc_price_block_adds_up(docs, work_type, audience, figure):
    """The reported defect, in dollars, on all three GC files at every combination of the two
    taxes. These templates print Material Sales Tax and Remodel Tax as plain paragraphs — there
    is no layout in which they are hidden — so the base line has to be net of both."""
    total, sales, remodel = FIGURES[figure]
    rows = docs[(work_type, audience, "INCLUDED", figure)]
    for row in ("base", "material", "remodel", "total"):
        assert row in rows, f"{work_type}/{audience}: the {row} row did not print ({rows!r})"
    assert rows["material"] == sales and rows["remodel"] == remodel
    assert rows["total"] == total
    assert rows["base"] + rows["material"] + rows["remodel"] == rows["total"], (
        f"{work_type}/{audience} {figure}: printed {rows['base']} + {rows['material']} + "
        f"{rows['remodel']} = {rows['base'] + rows['material'] + rows['remodel']}, "
        f"but the Total says {rows['total']}")
    assert rows["base"] == total - sales - remodel


def test_kyles_gc_polish_block_reconciles_line_for_line(docs):
    """The exact block Kyle was shown, spelled out, because "it adds up" is a property and this
    is the artefact. $6,307 tax-inclusive, $125 of material sales tax, no remodel."""
    rows = docs[("polish", "GC", "INCLUDED", "sales tax only")]
    assert rows["base"] == 6182.0 and rows["material"] == 125.0
    assert rows["remodel"] == 0.0 and rows["total"] == 6307.0
    assert rows["base"] + rows["material"] + rows["remodel"] == 6307.0
    # And the base line no longer claims to include a tax that is itemised right below it.
    assert "INCLUDED" not in rows["base_line"], rows["base_line"]


# ── (2) the Direct templates: one all-in line, carrying the whole bid ────────
@pytest.mark.parametrize("work_type,audience", DIRECT_TEMPLATES)
@pytest.mark.parametrize("figure", DIRECT_FIGURES)
def test_a_direct_proposal_prints_the_whole_bid_on_the_base_line(docs, work_type, audience, figure):
    """Kyle's original report. These templates gate their tax rows behind {{#tax_breakout}} /
    {{#remodel}}, and the default layout strips them: the base line is the ONLY price on the
    page, so it must be the whole tax-inclusive bid. A base line net of a row that never printed
    is a silent discount."""
    total, _sales, _remodel = FIGURES[figure]
    rows = docs[(work_type, audience, "INCLUDED", figure)]
    assert "base" in rows, f"{work_type}/{audience}: no base line printed ({rows!r})"
    assert rows["base"] == total, (
        f"{work_type}/{audience} {figure}: base line printed {rows['base']} under a {total} bid")
    assert "material" not in rows, "a Material Sales Tax row printed in the INCLUDED layout"


def test_kyles_report_the_direct_proposal_prints_6307_not_6182(docs):
    """The words of the report: the estimate said $6,307, the proposal said $6,182."""
    rows = docs[("polish", "Direct", "INCLUDED", "sales tax only")]
    assert rows["base"] == 6307.0, "the Direct base line is back to the ex-tax figure"
    assert "$6,307" in rows["base_line"] and "$6,182" not in rows["base_line"]
    assert "material sales tax INCLUDED" in rows["base_line"], (
        "with no tax row printing, the base line has to say the tax is in there")


@pytest.mark.parametrize("work_type,audience", DIRECT_TEMPLATES)
@pytest.mark.parametrize("figure", DIRECT_FIGURES)
def test_a_direct_proposal_broken_out_itemises_and_sums(docs, work_type, audience, figure):
    """"Sales tax broken out" un-strips those same rows, and then the base line has to be net of
    them — the same rule, the other way round, on the same file."""
    total, _sales, _remodel = FIGURES[figure]
    rows = docs[(work_type, audience, "BROKEN_OUT", figure)]
    assert "base" in rows and "material" in rows, f"{work_type} broken out: {rows!r}"
    printed = rows["base"] + rows["material"] + rows.get("remodel", 0.0)
    assert printed == total, (
        f"{work_type}/{audience} {figure} broken out: printed {printed}, Total {total} ({rows!r})")


# ── (3) gyp: the same shape as GC, and it must not have regressed ───────────
@pytest.mark.parametrize("figure", list(FIGURES))
def test_the_gyp_price_block_still_adds_up(docs, figure):
    """Gyp already reconciled, via a `work_type == "gyp"` special case in `_generate` that said
    "gyp always itemizes". That sentence was true of the FILE, not of the work type, and this is
    the case that proves replacing it with the file's own shape kept gyp working."""
    total, sales, remodel = FIGURES[figure]
    rows = docs[("gyp", "Direct", "INCLUDED", figure)]
    assert rows["base"] + rows["material"] + rows["remodel"] == rows["total"]
    assert rows["base"] == total - sales - remodel


# ── (4) the discriminator is the wrapper, not the folder ────────────────────
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

    # One row wrapped and one not: the two answers are independent, so a template that gains a
    # wrapper on only one of them still gets a base bid that sums.
    assert pw.free_tax_rows(_synthetic(
        "{{#tax_breakout}}", "{{material_tax_formatted}} – Material Sales Tax",
        "{{/tax_breakout}}", "{{tax_amount_formatted}} – Remodel Tax")) == {
            "material": False, "remodel": True}

    # A template with no tax rows at all (the Budget sheet) is not "free" — there is nothing to
    # subtract, and answering True would print a tax-excluded bid with no tax line under it.
    assert pw.free_tax_rows(_synthetic("Budget pricing", "{{total_formatted}} – Total")) == {
        "material": False, "remodel": False}


@pytest.mark.parametrize("work_type,audience,expected", [
    ("epoxy", "Direct", False), ("polish", "Direct", False), ("combo", "Direct", False),
    ("budget", "Direct", False),
    ("epoxy", "GC", True), ("polish", "GC", True), ("sealer", "GC", True), ("combo", "GC", True),
    ("gyp", "Direct", True), ("gyp", "GC", True),
])
def test_every_shipped_template_is_classified_from_its_own_file(work_type, audience, expected):
    """What the eight real files actually say today, cross-checked against an INDEPENDENT walk of
    the same document rather than against the function's own answer. A cached answer keyed on a
    path is exactly the kind of thing that keeps returning yesterday's shape."""
    got = pw.template_free_tax_rows(work_type, audience)
    assert got == {"material": expected, "remodel": expected}, pw.pick_template(
        work_type, audience).name

    d = docx.Document(str(pw.pick_template(work_type, audience)))
    walked = [in_block for _i, _k, _p, in_block, text, _x in pw.iter_editable_blocks(d)
              if "material_tax_formatted" in (text or "")]
    if expected:
        assert walked and all(b is None for b in walked), walked
    else:
        # Either gated, or absent entirely (Budget) — both mean "nothing unconditional to print".
        assert all(b is not None for b in walked), walked


def test_an_unreadable_template_says_why_instead_of_guessing(monkeypatch, caplog):
    """A shape it cannot read must not silently become "GC-shaped" — that prints a tax-excluded
    base bid on a template that never itemises, i.e. a discount. It answers "nothing
    unconditional", and it logs the exception TYPE and MESSAGE: a "refused" line that does not say
    why costs an SSH session and a container probe. `fill_proposal` then raises on the same file a
    moment later with its name in the error, which is the failure worth surfacing.

    Reachable, not hypothetical: a template missing from the image, or a bad mount. (An unmapped
    work_type does NOT come here — `pick_template` falls back to epoxy/Direct by design.)"""
    gone = pw.TEMPLATES_ROOT / "Direct" / "not-in-the-image.docx"
    monkeypatch.setattr(pw, "pick_template", lambda work_type, audience: gone)
    with caplog.at_level("WARNING", logger="proposal_tool.proposal_writer"):
        assert pw.template_free_tax_rows("polish", "GC") == {"material": False, "remodel": False}
    msg = caplog.text
    assert "tax-row shape" in msg, msg
    assert "polish" in msg and "GC" in msg, "the warning does not name the template it refused"
    assert "Error" in msg or "Exception" in msg, f"no exception type in the warning: {msg}"


def test_the_shape_read_is_cached_per_file_version():
    """One 11ms walk per template, not one per generate. Keyed on mtime so a template Kyle
    re-authors is re-read anyway (the same staleness contract as `_template_proposal_version`)."""
    pw._free_tax_rows_cached.cache_clear()
    pw.template_free_tax_rows("polish", "GC")
    first = pw._free_tax_rows_cached.cache_info()
    pw.template_free_tax_rows("polish", "GC")
    second = pw._free_tax_rows_cached.cache_info()
    assert second.hits == first.hits + 1 and second.misses == first.misses


# ── (5) the screen and the document print the same base bid ─────────────────
def _template_blocks(work_type, audience):
    """The template as `/api/proposal-template` serves it — id, in_block, text — which is the
    only thing the page has to answer "do my tax rows print" with."""
    d = docx.Document(str(pw.pick_template(work_type, audience)))
    return [{"id": i, "in_block": in_block, "text": text}
            for i, _k, _p, in_block, text, _x in pw.iter_editable_blocks(d)]


@pytest.fixture(scope="module")
def screen():
    """Run the page's own two price-block writers, in Node, over the real template shapes. Cheap
    (no document render), so this one sweeps every figure as well as every shape and mode."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    cases = []
    for work_type, audience in ALL_TEMPLATES:
        blocks = _template_blocks(work_type, audience)
        for mode in MODES:
            for figure, (total, sales, remodel) in FIGURES.items():
                cases.append({"name": f"{work_type}/{audience}/{mode}/{figure}",
                              "work_type": work_type, "audience": audience,
                              "tax_inclusion": mode, "blocks": blocks,
                              "total": total, "sales_tax": sales, "remodel_tax": remodel})
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                       input=json.dumps(cases), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return {r["name"]: r for r in json.loads(p.stdout)}


@needs_node
@pytest.mark.parametrize("work_type,audience", ALL_TEMPLATES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("figure", list(FIGURES))
def test_the_page_writes_the_base_bid_once(screen, work_type, audience, mode, figure):
    """THE PROPERTY BEING FIXED. This page has two writers for the base-bid line —
    `refreshPriceDisplay` paints the mounted rows, `computeTokenValues` fills the
    {{base_bid_formatted}} the free-paragraph templates print — and they used to compute it with
    two different expressions. That is how the estimator could approve $6,182 while the document
    said $6,307. Both go through `baseBidFigure` now, and this asserts the FIGURES agree rather
    than asserting that both call it."""
    r = screen[f"{work_type}/{audience}/{mode}/{figure}"]
    assert r["tokens"]["base_bid_formatted"] in r["painted"]["base"], (
        f"the painted base line {r['painted']['base']!r} does not carry the document's base bid "
        f"{r['tokens']['base_bid_formatted']!r}")
    phrase = r["tokens"]["base_tax_phrase"]
    assert r["painted"]["base"].endswith(phrase if phrase else "as described above"), (
        f"the painted parenthetical disagrees with {{{{base_tax_phrase}}}} ({phrase!r}): "
        f"{r['painted']['base']!r}")


@needs_node
@pytest.mark.parametrize("work_type,audience", ALL_TEMPLATES)
@pytest.mark.parametrize("mode", MODES)
def test_the_screen_and_the_document_print_the_same_base_bid(screen, docs, work_type, audience, mode):
    """And the page's figure is the one `/api/generate` prints — every shape, every tax mode. Two
    independent implementations of one rule (JS off the served blocks, Python off the template
    file) have to land on the same dollar, or the estimator proofreads a price the customer never
    sees. Which was the whole incident."""
    r = screen[f"{work_type}/{audience}/{mode}/{HARDEST}"]
    rows = docs[(work_type, audience, mode, HARDEST)]
    assert rows["base"] == _usd(r["tokens"]["base_bid_formatted"]), (
        f"{work_type}/{audience}/{mode}: the screen shows "
        f"{r['tokens']['base_bid_formatted']} and the document prints ${rows['base']:,.2f}")
    # And whatever the document printed, it sums.
    printed = rows["base"] + rows.get("material", 0.0) + rows.get("remodel", 0.0)
    assert printed == rows.get("total", rows["base"]), (
        f"{work_type}/{audience}/{mode}: the printed price block does not sum ({rows!r})")
