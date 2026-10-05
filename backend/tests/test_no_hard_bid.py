"""The automatic hard-bid discount is gone; the typed one stays; no existing price moves.

Hanz, 2026-10-03: *"We also need to remove the hard bid discount. Even on active projects and direct
projects."* Asked to choose, he picked: remove ONLY the "Hard Bid?" switch -- Kyle's automatic
2.5% / 4% give-back --

    Epoxy!B74 = IF(B5="yes", IF(D70>=60000, -0.04, IF(B4="yes", IF(D70>=13000, -0.025, 0))))

(the same rule sits at Polish/Seal/'Seal (+Jnts)'!B68, 'Epoxy blank'!B71 and Leveling!B70) -- and
KEEP the "Hard Bid Discount" row exactly as it works today for an estimator who types his own rate
or dollar figure into it. And keep every existing project's price.

THE RULE, STATED ONCE: a "Hard Bid?" cell is never written. Not by the intake, not by the AI, not
by a saved draft, not by the grid. Kyle's template ships every one of them as "No" (and
'Seal (+Jnts)'!B5 as `=Seal!B5`), so his own formula prices the automatic part at zero, and a typed
B74/D74 (or its row on another layout) replaces his formula exactly as it always has. The cells are
`estimate_writer.HARD_BID_FLAG_CELLS`; the screen's copy of the layout list is
`HARD_BID_FLAG_LAYOUTS` in estimate-review.js, and test 1 fails if either drifts from the workbook.

WHERE IT IS ENFORCED, and why there are two places for one rule: the price exists in two engines.
  * the downloaded .xlsx  -- `estimate_writer.fill_estimate`, the only function that turns a
    draft's cell_values into a workbook (every /api/generate path, the To-Dropbox copy and the
    portal's replay all reach it);
  * the screen            -- `HF.setCellValue` in estimate-review.js, the only door into the
    HyperFormula engine, plus `dropHardBidFlags()` at load so a saved "Yes" stops being saved.
The proposal's lump sum is read off the screen's engine (`state.proposal_lump_sum` = its D88), so
it follows the screen.

EXECUTED, NOT GREPPED. The workbook half runs the real writer twice -- once as shipped, once with
the rule switched off (`HARD_BID_FLAG_CELLS` emptied, which is exactly the code path that existed
before) -- and compares every cell. The screen half runs the real `HF` wrapper and init()'s real
replay through tests/js/no-hard-bid-harness.js, before and after. Kyle's rate formula is then
evaluated, from its text in the workbook, against both sets of inputs.
"""
import io
import json
import pathlib
import re
import shutil
import subprocess
import warnings

import pytest

import estimate_writer as ew

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "no-hard-bid-harness.js"
TEMPLATE = ew.TEMPLATE_PATH

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _load(src):
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(io.BytesIO(src) if isinstance(src, bytes) else src)


@pytest.fixture(scope="module")
def wb():
    return _load(TEMPLATE)


# ── Kyle's rate formula, evaluated from its own text ────────────────────────────────────────────
# Just enough of Excel for the give-back cells: IF (two or three arguments), comparisons, numbers,
# strings, cell references, unary minus. String comparison is case-INSENSITIVE, as in Excel and in
# HyperFormula's default -- which is why "Yes" trips `B5="yes"`.
_TOK = re.compile(r'\s*(?:(\d+(?:\.\d+)?|\.\d+)|("(?:[^"]|"")*")|(\$?[A-Z]{1,3}\$?\d+)'
                  r'|(>=|<=|<>|[=<>(),\-])|([A-Za-z_]+))')


def _tokens(s):
    pos, out = 0, []
    s = s.strip()
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m or m.end() == pos:
            raise ValueError("cannot read %r at %d" % (s, pos))
        pos = m.end()
        num, st, ref, op, name = m.groups()
        out.append(("num", float(num)) if num else ("str", st[1:-1].replace('""', '"')) if st
                   else ("ref", ref.replace("$", "")) if ref else ("op", op) if op else ("name", name))
    return out


def evaluate(formula, cells):
    """`formula` ("=IF(...)") against `cells` {addr: value}; a missing cell is blank."""
    toks = _tokens(formula.lstrip("="))
    i = 0

    def peek():
        return toks[i] if i < len(toks) else (None, None)

    def take(kind=None, val=None):
        nonlocal i
        t = toks[i]
        assert kind is None or t[0] == kind, (t, kind)
        assert val is None or t[1] == val, (t, val)
        i += 1
        return t

    def cmp_(a, b, op):
        if isinstance(a, str) or isinstance(b, str):
            a, b = str(a).lower(), str(b).lower()
        return {"=": a == b, "<>": a != b, ">=": a >= b, "<=": a <= b, ">": a > b, "<": a < b}[op]

    def comparison():
        a = unary()
        if peek()[0] == "op" and peek()[1] in ("=", "<>", ">=", "<=", ">", "<"):
            op = take()[1]
            return cmp_(a, unary(), op)
        return a

    def unary():
        if peek() == ("op", "-"):
            take()
            return -unary()
        return primary()

    def primary():
        kind, val = take()
        if kind in ("num", "str"):
            return val
        if kind == "ref":
            v = cells.get(val)
            return "" if v is None else v
        if kind == "name" and val.upper() == "IF":
            take("op", "(")
            args = [comparison()]
            while peek() == ("op", ","):
                take()
                args.append(comparison())
            take("op", ")")
            return args[1] if args[0] else (args[2] if len(args) > 2 else False)
        if (kind, val) == ("op", "("):
            v = comparison()
            take("op", ")")
            return v
        raise ValueError("unsupported token %r" % ((kind, val),))

    v = comparison()
    assert i == len(toks), "trailing tokens in %r" % formula
    return 0 if v is False else v


def test_the_evaluator_reads_kyles_cell_the_way_excel_does(wb):
    """The evaluator is only worth its output if it gets Kyle's own cell right on every branch."""
    f = wb["Epoxy"]["B74"].value
    assert evaluate(f, {"B5": "Yes", "B4": "Yes", "D70": 72000}) == -0.04
    assert evaluate(f, {"B5": "Yes", "B4": "No", "D70": 72000}) == -0.04
    assert evaluate(f, {"B5": "Yes", "B4": "Yes", "D70": 20000}) == -0.025
    assert evaluate(f, {"B5": "Yes", "B4": "No", "D70": 20000}) == 0
    assert evaluate(f, {"B5": "Yes", "B4": "Yes", "D70": 9800}) == 0
    assert evaluate(f, {"B5": "No", "B4": "Yes", "D70": 72000}) == 0
    assert evaluate(f, {"B5": "yes", "B4": "yes", "D70": 72000}) == -0.04, "Excel's = ignores case"


# ── 1. the cells, read out of the workbook ──────────────────────────────────────────────────────
def _readers_of(wb, sheet, addr):
    """Every formula in the workbook that reads `sheet`!`addr` -- on its own sheet unqualified, or
    qualified from anywhere."""
    q = re.escape(sheet)
    pat_own = re.compile(r"(?<![A-Za-z0-9_$!'])\$?%s\$?%s(?!\d)" % (addr[0], addr[1:]))
    pat_ext = re.compile(r"(?:'%s'|(?<![A-Za-z0-9_'])%s)!\$?%s\$?%s(?!\d)" % (q, q, addr[0], addr[1:]))
    out = []
    for ws in wb.worksheets:
        for c in ws._cells.values():
            v = c.value
            if not (isinstance(v, str) and v.startswith("=")):
                continue
            body = re.sub(r'"[^"]*"', '""', v)
            if (ws.title == sheet and pat_own.search(body)) or pat_ext.search(body):
                out.append((ws.title, c.coordinate))
    return sorted(out)


def test_the_flag_cells_are_every_hard_bid_question_in_the_workbook(wb):
    """Every sheet whose A5 asks "Hard Bid?" is in the map, at B5, and nothing else is. The gypsum
    tabs ask it at A7 and NO formula reads their B7 -- they never had the discount -- and their B5
    is Local?, which this rule must never touch."""
    asked = {ws.title: "B5" for ws in wb.worksheets
             if str(ws["A5"].value or "").strip().lower() == "hard bid?"}
    assert asked == ew.HARD_BID_FLAG_CELLS
    for ws in wb.worksheets:
        if str(ws["A7"].value or "").strip().lower() == "hard bid?":
            assert ws.title.startswith("Gyp")
            assert _readers_of(wb, ws.title, "B7") == [], ws.title + "!B7 now drives a price"
            assert str(ws["A5"].value).strip() == "Local?"


def test_kyles_template_ships_every_flag_off(wb):
    """The rule leans on this: an unwritten flag is Kyle's own "No". A template that ever shipped
    "Yes" would need the writer to stamp it, which it does (test 2) -- this says it is not needed
    today."""
    for sheet, addr in ew.HARD_BID_FLAG_CELLS.items():
        v = wb[sheet][addr].value
        assert v == "No" or v == "=Seal!B5", (sheet, v)


def test_the_flags_readers_are_the_give_back_cells_and_nothing_else(wb):
    """WHY a price can only move through the give-back. If any other formula read a Hard Bid?
    cell, pinning it would move that formula too, and the invariant below would be incomplete."""
    readers = {s: _readers_of(wb, s, a) for s, a in ew.HARD_BID_FLAG_CELLS.items()}
    assert readers == {
        "Epoxy": [("Epoxy", "B74")],
        "Polish": [("Polish", "B68")],
        "Seal": [("Seal", "B68"), ("Seal (+Jnts)", "B5")],
        "Seal (+Jnts)": [("Seal (+Jnts)", "B68")],
        "Epoxy blank": [("Epoxy blank", "B71")],
        "Leveling": [("Leveling", "B70")],
    }


def _js_layouts():
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    m = re.search(r"^const HARD_BID_FLAG_LAYOUTS = (\[[\s\S]*?\]);$", src, re.M)
    assert m, "HARD_BID_FLAG_LAYOUTS moved out of estimate-review.js"
    return json.loads(m.group(1))


def test_the_screen_and_the_writer_name_the_same_layouts():
    assert sorted(_js_layouts()) == sorted(ew.HARD_BID_FLAG_CELLS)
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    m = re.search(r'^const HARD_BID_FLAG_ADDR = "([A-Z]+\d+)";$', src, re.M)
    assert m and set(ew.HARD_BID_FLAG_CELLS.values()) == {m.group(1)}


# ── 2. the downloaded workbook ──────────────────────────────────────────────────────────────────
ALL_YES = {"%s!B5" % s: "Yes" for s in ew.HARD_BID_FLAG_CELLS}


def _fill(cell_values, *, enforce=True, **kw):
    if enforce:
        return ew.fill_estimate({}, cell_values=cell_values, **kw)
    saved = dict(ew.HARD_BID_FLAG_CELLS)
    ew.HARD_BID_FLAG_CELLS.clear()           # the code path as it was before this change
    try:
        return ew.fill_estimate({}, cell_values=cell_values, **kw)
    finally:
        ew.HARD_BID_FLAG_CELLS.update(saved)


# ── 3. THE PRICE INVARIANT ──────────────────────────────────────────────────────────────────────
# Shaped on production as of 2026-10-03. Five real drafts carry the flag "Yes" and it changes $0
# on each: their sub-total sits under $13k, or they are polish jobs whose flag only ever reached
# Epoxy!B5 (the AI autofill writes Epoxy only) while the bid is priced off Polish. Twenty-three
# carry a TYPED discount in the row -- a rate or a dollar figure -- which replaces Kyle's formula.
# `subtotal` / `markup` are the tab's D70 (D64 on Polish) and GP dollars: inputs to Kyle's formula,
# stated per fixture because they are formula results the evaluator does not compute.
RATE = {"Epoxy": ("B74", "D74", "D70", "D73"), "Polish": ("B68", "D68", "D64", "D67")}

FIXTURES = {
    "small local epoxy, flag on": {
        "cell_values": {"Epoxy!B4": "Yes", "Epoxy!B5": "Yes", "Polish!B4": "Yes", "Polish!B5": "Yes",
                        "Epoxy!E20": 1800},
        "tab": "Epoxy", "subtotal": 9800, "markup": 4200},
    "small travelling epoxy, flag on": {
        "cell_values": {"Epoxy!B4": "No", "Epoxy!B5": "Yes", "Epoxy!E20": 6000},
        "tab": "Epoxy", "subtotal": 41000, "markup": 15000},
    "polish only, flag on Epoxy": {
        "cell_values": {"Epoxy!B4": "Yes", "Epoxy!B5": "Yes", "Polish!B4": "Yes", "Polish!E19": 9000},
        "tab": "Polish", "subtotal": 26000, "markup": 9000},
    "typed rate -15%, flag on": {
        "cell_values": {"Epoxy!B4": "Yes", "Epoxy!B5": "Yes", "Epoxy!B74": -0.15, "Epoxy!E20": 20000},
        "tab": "Epoxy", "subtotal": 72000, "markup": 30000},
    "typed rate -2%": {
        "cell_values": {"Epoxy!B4": "Yes", "Epoxy!B5": "No", "Epoxy!B74": -0.02, "Epoxy!E20": 9000},
        "tab": "Epoxy", "subtotal": 30000, "markup": 12000},
    "typed dollar -$500 in D74, flag on": {
        "cell_values": {"Epoxy!B4": "Yes", "Epoxy!B5": "Yes", "Epoxy!D74": -500, "Epoxy!E20": 9000},
        "tab": "Epoxy", "subtotal": 30000, "markup": 12000},
    "typed dollar -$1,500 in Polish D68, flag on": {
        "cell_values": {"Polish!B4": "Yes", "Polish!B5": "Yes", "Polish!D68": -1500,
                        "Polish!E19": 12000},
        "tab": "Polish", "subtotal": 34000, "markup": 11000},
}
# The one shape whose price DOES move: a large local epoxy bid with the switch on. Production has
# exactly one such draft and it is a Test project.
LARGE = {"cell_values": {"Epoxy!B4": "Yes", "Epoxy!B5": "Yes", "Epoxy!E20": 30000},
         "tab": "Epoxy", "subtotal": 72000, "markup": 30000}
LARGE_TYPED = dict(LARGE, cell_values=dict(LARGE["cell_values"], **{"Epoxy!B74": -0.04}))
ALL_SHAPES = dict(FIXTURES, LARGE=LARGE, LARGE_TYPED=LARGE_TYPED)

# ONE WORKBOOK FOR ALL OF THEM. A fill costs ~5 s, so every shape rides on its own COPY of the tab
# it is priced from ("E3" is shape 3's Epoxy, "P3" its Polish) -- the rule is keyed on the layout,
# so a copy is held to it exactly as the base tab is, and a copy is a whole independent bid. The
# base tabs carry the flag "Yes" everywhere (and a copy chain and the gyp cells next to it), so the
# same pair of files also proves where the rule reaches and where it must not.
_COPIES = [{"id": "Copy1", "source": "Epoxy"}, {"id": "Copy2", "source": "Copy1"},
           {"id": "Copy3", "source": "Leveling"}]
_EXTRA = dict(ALL_YES, **{"Copy1!B5": "Yes", "Copy2!B5": "yes", "Copy3!B5": "YES",
                          'Gyp (USG 1-8")!B5': "No",       # Local? on a gyp tab: NOT ours
                          'Gyp (USG 1-8")!B7': "Yes"})     # gyp's own Hard Bid?: reads nothing


def _tab_id(i, sheet):
    return ("E%d" if sheet == "Epoxy" else "P%d") % i


def _batch_draft():
    copies, cv = list(_COPIES), dict(_EXTRA)
    for i, fx in enumerate(ALL_SHAPES.values()):
        copies += [{"id": _tab_id(i, "Epoxy"), "source": "Epoxy"},
                   {"id": _tab_id(i, "Polish"), "source": "Polish"}]
        for key, val in fx["cell_values"].items():
            sheet, addr = key.split("!")
            cv["%s!%s" % (_tab_id(i, sheet), addr)] = val
    return cv, copies


@pytest.fixture(scope="module")
def batch():
    cv, copies = _batch_draft()
    after_bytes = _fill(cv, tab_copies=copies)
    return {"before": _load(_fill(cv, enforce=False, tab_copies=copies)),
            "after": _load(after_bytes), "after_bytes": after_bytes, "copies": copies}


def _roundup(x):
    import math
    return int(math.copysign(math.ceil(abs(x) - 1e-9), x)) if x else 0


def _give_back(cells, formulas, fx):
    """The tab's Hard Bid Discount in dollars, from the values the engine holds. A typed rate or
    dollar REPLACES Kyle's formula, so it is read as the literal it is."""
    rate_a, dollar_a, sub_a, _gp = RATE[fx["tab"]]
    if dollar_a in cells:
        return cells[dollar_a]
    rate = cells[rate_a] if rate_a in cells else evaluate(
        formulas[rate_a], dict(cells, **{sub_a: fx["subtotal"]}))
    return _roundup((fx["subtotal"] + fx["markup"]) * rate)


def _split(ws):
    cells = {c.coordinate: c.value for c in ws._cells.values() if c.value is not None}
    formulas = {k: v for k, v in cells.items() if isinstance(v, str) and v.startswith("=")}
    return {k: v for k, v in cells.items() if k not in formulas}, formulas


def _file_give_back(out, name):
    i = list(ALL_SHAPES).index(name)
    fx = ALL_SHAPES[name]
    literal, formulas = _split(out[_tab_id(i, fx["tab"])])
    return _give_back(literal, formulas, fx)


def test_a_saved_yes_never_reaches_the_file_on_any_tab_or_copy(batch):
    out = batch["after"]
    for s in ("Epoxy", "Polish", "Seal", "Epoxy blank", "Leveling", "Copy1", "Copy2", "Copy3"):
        assert out[s]["B5"].value == "No", s
    assert out["Seal (+Jnts)"]["B5"].value == "=Seal!B5", "a mirror stays a mirror"
    assert out['Gyp (USG 1-8")']["B5"].value == "No", "the gyp Local? write was lost"
    assert out['Gyp (USG 1-8")']["B7"].value == "Yes", "the rule reached a gyp cell"
    # and the counterexample: without the rule, every one of those lands
    before = batch["before"]
    assert before["Epoxy"]["B5"].value == "Yes" and before["Copy3"]["B5"].value == "YES"
    assert before["Seal (+Jnts)"]["B5"].value == "Yes"


@pytest.mark.parametrize("name", list(FIXTURES))
def test_the_downloaded_workbook_prices_every_real_shape_the_same(batch, name):
    before, after = _file_give_back(batch["before"], name), _file_give_back(batch["after"], name)
    assert before == after, (name, before, after)


def test_nothing_but_a_hard_bid_flag_differs_between_the_two_files(batch):
    """THE COMPLETENESS HALF of the invariant. Kyle's total is a function of the workbook's
    literals; if the only literals that differ are Hard Bid? cells, and their only readers are the
    give-back cells (test 1), then equal give-backs mean equal totals -- D88, the lump sum, all of it."""
    a, b = batch["before"], batch["after"]
    diff = set()
    for ws in a.worksheets:
        va = {c.coordinate: c.value for c in ws._cells.values()}
        vb = {c.coordinate: c.value for c in b[ws.title]._cells.values()}
        diff |= {"%s!%s" % (ws.title, k) for k in set(va) | set(vb) if va.get(k) != vb.get(k)}
    copy_flags = {"%s!B5" % c["id"] for c in batch["copies"]}
    flags = {"%s!%s" % kv for kv in ew.HARD_BID_FLAG_CELLS.items()} | copy_flags
    assert diff <= flags, sorted(diff - flags)
    assert "Epoxy!B5" in diff and "E0!B5" in diff, "the fixture stopped setting any flag"


def test_typed_discounts_land_in_the_file_exactly_as_typed(batch):
    out, names = batch["after"], list(ALL_SHAPES)
    at = lambda name, sheet: out[_tab_id(names.index(name), sheet)]   # noqa: E731
    assert at("typed rate -15%, flag on", "Epoxy")["B74"].value == -0.15
    assert at("typed rate -15%, flag on", "Epoxy")["D74"].value.startswith("="), (
        "the dollar line still works itself out from the typed rate")
    assert at("typed rate -2%", "Epoxy")["B74"].value == -0.02
    assert at("typed dollar -$500 in D74, flag on", "Epoxy")["D74"].value == -500
    assert at("typed dollar -$1,500 in Polish D68, flag on", "Polish")["D68"].value == -1500


def test_a_large_local_epoxy_bid_no_longer_gets_four_percent(batch):
    """THE COUNTEREXAMPLE. Without it, every equality above would also pass against a rule that
    did nothing at all."""
    assert _file_give_back(batch["before"], "LARGE") == _roundup((72000 + 30000) * -0.04) == -4080
    assert _file_give_back(batch["after"], "LARGE") == 0


def test_a_typed_rate_still_wins_on_a_large_bid(batch):
    assert _file_give_back(batch["after"], "LARGE_TYPED") == -4080, (
        "an estimator who types the old 4% gets exactly the old 4%")


def test_the_flag_follows_a_structural_edit_to_its_real_address():
    """A row inserted above row 5 moves the flag to B6. The rule must follow it there -- and must
    not then eat the cell that moved INTO B5, which is the row the estimator inserted."""
    structs = [{"sheet": "Leveling", "kind": "insert_rows", "at": 3, "count": 1}]
    out = _load(_fill({"Leveling!B6": "Yes", "Leveling!B5": "typed note"}, tab_structs=structs))
    assert out["Leveling"]["A6"].value == "Hard Bid?"
    assert out["Leveling"]["B6"].value == "No"
    assert out["Leveling"]["B5"].value == "typed note"


def test_the_downloaded_file_offers_no_yes_no_picker_on_the_flag(batch):
    """Kyle's Yes/No list on B4:B5 is an x14 extension validation that openpyxl drops, and the
    writer only re-adds pickers to Taxable?/Remodel Tax? -- so the file carries a plain "No" with
    nothing inviting anyone to flip it. Pinned so a future picker pass cannot quietly bring it back."""
    import zipfile
    z = zipfile.ZipFile(io.BytesIO(batch["after_bytes"]))
    names = batch["after"].sheetnames
    for sheet in list(ew.HARD_BID_FLAG_CELLS) + [c["id"] for c in batch["copies"]]:
        xml = z.read("xl/worksheets/sheet%d.xml" % (names.index(sheet) + 1)).decode()
        for sq in re.findall(r'<dataValidation [^>]*sqref="([^"]*)"', xml):
            assert "B5" not in sq.split(), (sheet, sq)


def test_a_template_that_ever_shipped_yes_would_still_download_no(monkeypatch):
    """The writer does not lean on Kyle's template being "No": it stamps every literal flag "No"
    itself (step 2.05), and leaves the one mirror ('Seal (+Jnts)'!B5 = `=Seal!B5`) a mirror. Proven
    against a template doctored to ship "Yes" on every flag, because the real one cannot show it."""
    real = ew._fresh_template

    def doctored(*a, **kw):
        wb = real(*a, **kw)
        for sheet, addr in ew.HARD_BID_FLAG_CELLS.items():
            if not str(wb[sheet][addr].value).startswith("="):
                wb[sheet][addr] = "Yes"
        return wb
    monkeypatch.setattr(ew, "_fresh_template", doctored)
    out = _load(ew.fill_estimate({}, tab_copies=[{"id": "Copy1", "source": "Polish"}]))
    for sheet in list(ew.HARD_BID_FLAG_CELLS) + ["Copy1"]:
        want = "=Seal!B5" if sheet == "Seal (+Jnts)" else "No"
        assert out[sheet]["B5"].value == want, (sheet, out[sheet]["B5"].value)


def test_the_screen_grid_offers_no_picker_on_the_flag_either():
    for sheet in ew.HARD_BID_FLAG_CELLS:
        grid = ew.read_sheet_grid(sheet)
        assert "B5" not in grid["dropdowns"], sheet
    assert "B4" in ew.read_sheet_grid("Epoxy")["dropdowns"], "Local? lost its picker"
    assert "B5" in ew.read_sheet_grid('Gyp (USG 1-8")')["dropdowns"], "gyp Local? lost its picker"


# ── 4. the screen ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def screen(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    fixtures = {name: {"cell_values": fx["cell_values"]} for name, fx in FIXTURES.items()}
    fixtures["LARGE"] = {"cell_values": LARGE["cell_values"]}
    # Leveling has a row inserted above its flag, so ITS flag is B6 -- and its B5 is now Local?
    # (row 4 moved down), which must be left alone.
    yes = {k: v for k, v in ALL_YES.items() if k != "Leveling!B5"}
    fixtures["copies"] = {
        "cell_values": dict(yes, **{"Copy1!B5": "Yes", "Copy2!B5": "Yes", "Leveling!B6": "Yes",
                                    "Leveling!B5": "Yes", 'Gyp (USG 1-8")!B5': "No",
                                    "Copy1!B74": -0.03}),
        "tab_copies": [{"id": "Copy1", "source": "Epoxy"}, {"id": "Copy2", "source": "Copy1"}],
        "tab_structs": [{"sheet": "Leveling", "kind": "insert_rows", "at": 3, "count": 1}],
        "direct": ["Epoxy!B5", "Polish!B5", "Seal (+Jnts)!B5", "Copy2!B5", 'Gyp (USG 1-8")!B5',
                   "Epoxy!B74"],
        "probe": ["Leveling!B5", "Leveling!B6", "Epoxy!B4", 'Gyp (USG 1-8")!B7', "Copy2!B5"],
    }
    # Review of #605: the engine reads "B05" as B5. B50 is an ordinary cell that merely starts so.
    fixtures["zeros"] = {
        "cell_values": {"Epoxy!B05": "Yes", "Polish!B005": "Yes", "Copy1!B05": "Yes", "Epoxy!B50": 7},
        "tab_copies": [{"id": "Copy1", "source": "Epoxy"}],
        "direct": ["Epoxy!B05", "Seal (+Jnts)!B005", "Epoxy!B50"],
        "probe": ["Epoxy!B05", "Epoxy!b5", "Epoxy!B50", "Epoxy!B15"],
    }
    p = tmp_path_factory.mktemp("nohb") / "fixtures.json"
    p.write_text(json.dumps(fixtures), encoding="utf-8")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND), str(p)], capture_output=True,
                          text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _engine_tab(run, tab, template):
    """What the engine holds on `tab`: Kyle's literals with the replayed writes on top."""
    cells = {k: v for k, v in template.items()}
    for key, val in run["writes"].items():
        sheet, addr = key.split("!", 1)
        if sheet == tab:
            cells[addr] = val
    return cells


@needs_node
@pytest.mark.parametrize("name", list(FIXTURES))
def test_the_screen_prices_every_real_shape_the_same(screen, wb, name):
    fx = FIXTURES[name]
    cells = {c.coordinate: c.value for c in wb[fx["tab"]]._cells.values() if c.value is not None}
    formulas = {k: v for k, v in cells.items() if isinstance(v, str) and v.startswith("=")}
    literal = {k: v for k, v in cells.items() if k not in formulas}
    r = screen["fixtures"][name]
    before = _give_back(_engine_tab(r["before"], fx["tab"], literal), formulas, fx)
    after = _give_back(_engine_tab(r["after"], fx["tab"], literal), formulas, fx)
    assert before == after, (name, before, after)
    # and the engine was handed everything else exactly as before
    flags = {k for k in r["before"]["writes"] if k.endswith("!B5")}
    assert {k: v for k, v in r["before"]["writes"].items() if k not in flags} == r["after"]["writes"]


@needs_node
def test_the_screen_drops_the_large_bids_four_percent(screen, wb):
    cells = {c.coordinate: c.value for c in wb["Epoxy"]._cells.values() if c.value is not None}
    formulas = {k: v for k, v in cells.items() if isinstance(v, str) and v.startswith("=")}
    literal = {k: v for k, v in cells.items() if k not in formulas}
    r = screen["fixtures"]["LARGE"]
    assert _give_back(_engine_tab(r["before"], "Epoxy", literal), formulas, LARGE) == -4080
    assert _give_back(_engine_tab(r["after"], "Epoxy", literal), formulas, LARGE) == 0


@needs_node
def test_no_flag_reaches_the_engine_from_a_draft_a_copy_or_a_keystroke(screen):
    r = screen["fixtures"]["copies"]["after"]
    flags = (set(ALL_YES) - {"Leveling!B5"}) | {"Copy1!B5", "Copy2!B5", "Leveling!B6"}
    assert [k for k in r["writes"] if k in flags] == []
    assert r["writes"]["Leveling!B5"] == "Yes", "the moved Local? on Leveling was taken for the flag"
    assert r["writes"]['Gyp (USG 1-8")!B5'] == "No", "gyp's Local? never reached the engine"
    assert r["writes"]["Copy1!B74"] == -0.03, "a typed rate on a copy was dropped"
    d = r["direct"]
    assert d == {"Epoxy!B5": False, "Polish!B5": False, "Seal (+Jnts)!B5": False, "Copy2!B5": False,
                 'Gyp (USG 1-8")!B5': True, "Epoxy!B74": True}
    assert r["isFlag"] == {"Leveling!B5": False, "Leveling!B6": True, "Epoxy!B4": False,
                           'Gyp (USG 1-8")!B7': False, "Copy2!B5": True}
    before = screen["fixtures"]["copies"]["before"]
    assert before["direct"]["Epoxy!B5"] is True, "the counterexample: the old door let it in"


@needs_node
def test_a_saved_yes_is_dropped_from_the_draft_on_open_so_it_stops_being_saved(screen):
    r = screen["fixtures"]["copies"]["after"]
    flags = (set(ALL_YES) - {"Leveling!B5"}) | {"Copy1!B5", "Copy2!B5", "Leveling!B6"}
    assert r["dropped"] == len(flags) == 8
    for k in flags:
        assert k not in r["kept"], k
    assert r["kept"]["Copy1!B74"] == -0.03 and r["kept"]['Gyp (USG 1-8")!B5'] == "No"
    assert r["kept"]["Leveling!B5"] == "Yes"
    # The intake used to write "No" there on every flip. That is Kyle's own value: left, and the
    # draft does not save on open for it.
    clean = screen["fixtures"]["typed rate -2%"]["after"]
    assert clean["dropped"] == 0, "a draft whose flag already says No saved on open for nothing"
    assert clean["kept"]["Epoxy!B5"] == "No"


# ── 5. the AI autofill ──────────────────────────────────────────────────────────────────────────
def test_the_autofill_prompt_no_longer_asks_for_the_flag():
    import main
    p = main._AUTOFILL_SYSTEM_PROMPT
    assert '"Epoxy!B5":' not in p, "the prompt still asks for Hard Bid?"
    assert "Hard Bid=No" not in p
    assert "all 6 flag cells (B4, D5, B6, D6, B9, B10)" in p
    assert "Do NOT return Epoxy!B5" in p


def test_the_autofill_reply_is_stripped_of_the_flag_before_it_leaves_the_server(monkeypatch):
    """For a model that answers anyway: the reply that reaches the page has no Hard Bid? cell and
    no reasoning line for one, and every other answer is untouched."""
    from fastapi.testclient import TestClient
    import main
    monkeypatch.setattr(main, "_autofill_via_cli", lambda text: {
        "Epoxy!B5": "Yes", "Polish!b5": "Yes", "Epoxy!D5": "Yes", 'Gyp (USG 1-8")!B5': "No",
        "texture": "Smooth", "reasoning": {"Epoxy!B5": "competitive", "Epoxy!D5": "school"}})
    r = TestClient(main.app).post("/api/autofill", json={"notes": "hard bid, prevailing wage"},
                                  headers={"Authorization": "Bearer x", "X-Project-Id": "nohb-1"})
    assert r.status_code == 200, r.text
    cv = r.json()["cell_values"]
    assert cv == {"Epoxy!D5": "Yes", 'Gyp (USG 1-8")!B5': "No", "texture": "Smooth",
                  "reasoning": {"Epoxy!D5": "school"}}


def test_init_drops_a_saved_yes_before_the_replay_and_saves_the_draft_after():
    """init() is a 120-line async function that fetches before it gets here, so the CALL SITE is
    pinned from the shipped source (the rule itself is executed above): the drop has to run before
    "Apply saved overrides" replays the draft into the engine, and its count has to reach the save,
    or a reopened draft keeps carrying the switch it can no longer use."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    body = src[src.index("async function init()"):src.index("\nfunction renderTabs()")]
    # Comments out first (review of #605): `/* const _hardBidDropped = dropHardBidFlags(); */`
    # still contained the text, so a commented-out call passed.
    body = re.sub(r"/\*[\s\S]*?\*/", "", body)
    body = re.sub(r"(?m)^[ \t]*//.*$", "", body)
    drop = body.index("const _hardBidDropped = dropHardBidFlags();")
    replay = body.index("for (const [key, val] of Object.entries(cellValues)) {")
    assert drop < replay < body.index("if (_flagsHealed")
    save = body[body.index("if (_flagsHealed"):]
    assert save.startswith("if (_flagsHealed || _ratesApplied || _hardBidDropped) persistTabState();")



# ── 6. review of #605: the address as the engines read it, and the downloaded file's lock ─────────
@needs_node
def test_a_leading_zero_spelling_of_the_flag_is_refused_on_the_screen_too(screen):
    """The engine's own parser reads "B05" / "B005" as B5, so a guard comparing the raw text let a
    saved or AI-sent "Epoxy!B05": "Yes" switch the discount back on, on screen and in the proposal's
    lump sum, while the downloaded file priced without it.

    Mutation: compare `String(addr).toUpperCase()` in isHardBidFlagCell again."""
    z = screen["fixtures"]["zeros"]
    before, after = z["before"], z["after"]
    assert {"Epoxy!B5", "Polish!B5", "Copy1!B5"} <= set(before["writes"]), (
        "the counterexample: the engine does read B05 as B5")
    assert [k for k in after["writes"] if k.endswith("!B5")] == [], after["writes"]
    assert after["writes"].get("Epoxy!B50") == 7, "an ordinary cell that starts with B5 was refused"
    assert after["dropped"] == 3
    assert after["direct"] == {"Epoxy!B05": False, "Seal (+Jnts)!B005": False, "Epoxy!B50": True}
    assert after["isFlag"] == {"Epoxy!B05": True, "Epoxy!b5": True, "Epoxy!B50": False,
                               "Epoxy!B15": False}


def test_the_canonical_spelling_is_the_engines():
    for raw, want in [("B5", "B5"), ("b5", "B5"), ("B05", "B5"), ("B005", "B5"), (" B05 ", "B5"),
                      ("B50", "B50"), ("B500", "B500"), ("B0", "B0"), ("AA07", "AA7"),
                      ("Epoxy", "EPOXY"), ("", "")]:
        assert ew.canonical_cell_addr(raw) == want, (raw, ew.canonical_cell_addr(raw), want)


@pytest.fixture(scope="module")
def zeros_file():
    return _load(ew.fill_estimate(
        {}, cell_values={"Epoxy!B05": "Yes", "Seal (+Jnts)!B005": "Yes", "Copy1!B05": "Yes",
                         "Epoxy!B50": 3},
        tab_copies=[{"id": "Copy1", "source": "Epoxy"}], tab_labels={"Copy1": "EPOXY 2"}))


def test_a_leading_zero_spelling_never_reaches_the_file(zeros_file):
    """openpyxl reads "B05" as B5 too. The literal flags were saved by the "No" stamp after the
    writes, but 'Seal (+Jnts)'!B5's formula `=Seal!B5` was overwritten by the leading-zero write
    and turned into a literal. Mutation: compare `addr.upper()` in fill_estimate's skip again."""
    out = zeros_file
    assert out["Epoxy"]["B5"].value == "No"
    assert out["Seal (+Jnts)"]["B5"].value == "=Seal!B5", out["Seal (+Jnts)"]["B5"].value
    assert out["EPOXY 2"]["B5"].value == "No"
    assert out["Epoxy"]["B50"].value == 3, "an ordinary cell that starts with B5 was not written"


def test_the_flag_is_locked_in_the_downloaded_file_wherever_the_sheet_is_protected(zeros_file):
    """One keystroke in Excel used to switch Kyle's automatic discount back on in the downloaded
    file and nowhere else: the rate cells were locked, Hard Bid? beside them was not. Unprotect
    Sheet (no password) still reaches it, as it does a rate. Held by worksheet, so a copy renamed
    to its label in step 5 is locked too. Mutation: drop the step-6 addition."""
    out = zeros_file
    for title in list(ew.HARD_BID_FLAG_CELLS) + ["EPOXY 2"]:
        ws = out[title]
        if not ws.protection.sheet:
            continue
        assert ws["B5"].protection.locked is True, title
    for title in ("Epoxy", "Polish", "EPOXY 2"):
        assert out[title].protection.sheet, title + " is not protected at all"
    assert out["Epoxy"]["B4"].protection.locked is False, "Local? beside it was locked too"
    assert out["Epoxy"]["E20"].protection.locked is False, "an input cell was locked"


def test_the_autofill_strip_reads_the_address_the_way_the_engines_do():
    import main
    out = main._without_hard_bid_flags({"Epoxy!B05": "Yes", "Polish!b005": "Yes", "Epoxy!B50": 1,
                                        "reasoning": {"Epoxy!B05": "x", "Epoxy!D5": "y"}})
    assert out == {"Epoxy!B50": 1, "reasoning": {"Epoxy!D5": "y"}}


def test_the_screen_cell_is_read_only_not_disabled():
    """Review of #605: `disabled` cannot take focus, so Enter / the arrow keys stopped dead beside
    B5, and multi-cell paste and clear (which skip only readOnly cells, _commitCellWrite) wrote
    through it. And the 🔒 block must leave it alone, or an unlock would make it typeable."""
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    block = src[src.index("  if (isHardBidFlagCell(sheet, cell.addr)) {"):]
    block = block[:block.index("\n  }")]
    assert "inp.readOnly = true;" in block and "inp.disabled" not in block, block
    assert "if (lockedCellsFor(sheet).has(cell.addr) && !isHardBidFlagCell(sheet, cell.addr)) {" in src
    commit = src[src.index("function _commitCellWrite(inp, text) {"):]
    assert commit.index("if (inp.readOnly) return false;") < 80, "the readOnly skip moved"
