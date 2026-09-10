"""A markup rate an admin files must move the bid — and only the lines it can move correctly.

WHAT WAS BROKEN. /markup.html has stored the markup chain's rates since it shipped, and nothing
has ever read them. An admin could change Super & PTO from 3% to 4%, watch it save with a green
tick, and no price anywhere would move. The page said so in a paragraph, because "a number that
quietly does nothing is how people come to distrust the whole form".

WHAT THE FIX DOES. `applyMarkupRates` in frontend/js/estimate-review.js writes a filed rate into
KYLE'S OWN rate cell as `=<rate>`, and his formula — his SUM ranges, his ROUNDUPs — works out the
dollars. Nothing in this path computes money, and `backend/pricing.py` is deliberately not
involved: it is ~1% off on quartz and ~30% wrong on polish, so routing the bid through it would
swap one wrong number for another.

TWO LINES, NOT SEVEN, AND EVERY EXCLUSION IS STRUCTURAL. Only `super_pto` and `soft_costs` have
an address in `MARKUP_RATE_TARGETS` -- 17 cells across eleven priced sheets. `gp` and `hard_bid`
have none on any layout; `soft_costs` has none on gyp; and **`bond` has none anywhere**, which was
a decision taken during this change rather than a starting assumption: wiring it up would have
exposed a tax double-count in Kyle's own bond formula that has never been exercised, always
over-charging, in front of a customer. See
test_no_layout_has_a_bond_address_and_the_admin_page_lists_none for the whole of that.

The exclusions are by LINE KEY rather than by a check on the formula's shape, for one measured
reason: an admin filing gp as **"45%" IS a bare percent**. It would pass any "does this look like
a rate?" guard and flatten a 5-, 6- or 7-tier GP ladder to one number, pricing plausibly and
wrongly with nothing on screen to show it. The guard is the second line of defence; it is never
the first.

WHY THE RATE IS PARSED FROM TEXT AND NEVER EVALUATED. The obvious writer is
`String(TWMarkup.run(rule.formula, {}))`, using the Markup page's own engine. A postfix `%` is a
divide-by-100 at eval time and binary floating point does not survive it — executed against the
real frontend/js/markup-core.js in this repo:

    run("2.7%")  ->  0.027000000000000003        Polish/Seal!B69 holds 0.027
    run("4.1%")  ->  0.040999999999999995        every Gyp!B74 holds 0.041

**A CORRECTION TO THE SPEC THIS WAS BUILT FROM, measured rather than inherited.** The spec said
that value changes the price, on the grounds that `Math.ceil(1000 * 0.027000000000000003)` is 28
where `Math.ceil(1000 * 0.027)` is 27. The bare arithmetic is right and the conclusion is not:
the shipped ROUNDUP is not `Math.ceil`. frontend/js/xl-excel-rounding.js snaps its argument to 12
significant digits first — deliberately, because without it 98 cells across six real estimates
read high — and Excel does its own tidy-up on the .xlsx side. Executed both ways: with the
override, 1000/2000/3000/4000/5000 x 0.027000000000000003 all still round to 27/54/81/108/135. So
evaluating would NOT have mispriced a bid today.

What it WOULD do is write `=0.027000000000000003` into Kyle's own workbook, where he can see it,
and make the price correct only because a rounding override happens to absorb it. Parsing the
text is exact, costs nothing, and means the estimate page loads no formula engine at all. The two
drift values are still named here so a future "simplification" back to `run()` fails
`test_evaluating_the_rate_instead_of_parsing_it_makes_the_round_trip_go_red` rather than quietly
putting a 17-digit float in an estimator's spreadsheet.

WHY DOLLARS AND NOT STRUCTURE. Asserting "the cell was written" passes while the total is wrong.
openpyxl cannot evaluate a workbook and neither LibreOffice nor HyperFormula is available here, so
the same route test_taxable_flag_reaches_every_sheet.py takes is taken again: **the markup chain
is walked using the workbook's OWN formula text**, with every input from above the chain read from
Excel's own last-computed value (a markup rate cannot move those).
`test_the_chain_evaluator_reproduces_excels_own_cached_totals` is what makes every dollar figure
below trustworthy — it reproduces D88 = 11029, Polish D82 = 13265, Seal D82 = 1450 and
'Seal (+Jnts)' D82 = 2883 to the cent, from formula text alone.

THE TWO INVARIANTS THIS SHIPS OR DIES ON.
  * **Filing nothing changes nothing.** `markup_rules` is verified empty on production (0 rows, 0
    deleted). Shipping this must not move one existing price until an admin files a rate.
  * **The round trip holds.** Filing a line's built-in value must produce a price identical to the
    built-in, on every layout and to the dollar.

ONE THING THIS FILE DOCUMENTS RATHER THAN GUARDS.
`test_bond_carries_a_dormant_tax_double_count_in_kyles_own_formula` describes a defect in the
WORKBOOK, not in this repo: the bond base counts the sales-tax and remodel-tax cells twice, once
individually and once through the 'Total Taxes' cell. It guards no shipped behaviour, because bond
is unwired -- it is there to explain the exclusion, so the next reader finds Kyle's formula rather
than assuming somebody forgot a line. The figures are asserted so the size is on record when he
is asked to fix it, and so that the test going red reads as "the double count is gone" rather than
as a pricing bug.
"""
import io
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys
import warnings

import openpyxl
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import estimate_writer as ew  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "markup-rate-harness.js"
TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "estimate_sheet_5.7.xlsx"

# Everything the two harnesses read, copied wholesale for the mutation runs at the bottom.
# markup.html and markup-core.js are in the list because markup-page-harness.js reads the element
# ids OUT OF THE PAGE and requires the real engine -- one mutation below drives that harness too.
MUTATE_FILES = ("js/estimate-review.js", "js/markup.js", "js/markup-core.js", "markup.html")

GYP_SHEETS = ['Gyp (USG 1-8")', 'Gyp (USG N12ULTRA)', 'Gyp (USG N25 1-4")',
              'Gyp (GWorx SC190)', 'Gyp (FR)']
PRICED_SHEETS = ["Epoxy", "Polish", "Seal", "Seal (+Jnts)", "Epoxy blank",
                 "Leveling"] + GYP_SHEETS

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def drive(frontend: pathlib.Path):
    """Run the harness against a frontend directory and return its JSON."""
    proc = subprocess.run(["node", str(HARNESS), str(frontend)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed -- read this before assuming a product bug:\n" + proc.stderr)
    # Exit 0 with nothing printed is its own failure: node empties its event loop and leaves when
    # a scenario is still awaiting a promise that never settles, so the JSON line is never written.
    assert proc.stdout.strip(), (
        "the harness exited cleanly and printed nothing -- a scenario never settled:\n"
        + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return drive(FRONTEND)


# ─── the chain, walked with Kyle's own formula text ──────────────────────────
#
# (first chain row, total cell) per layout: the SUB-TOTAL COSTS row downwards. A cell at or below
# that row is EVALUATED from its formula; anything above it — material, labour, escalation, travel
# — is read from Excel's own cached value, because no markup rate can move it. That bound is what
# keeps this a chain verifier rather than a re-implementation of the workbook.
CHAIN = {
    "Epoxy": (70, "D88"), "Polish": (64, "D82"), "Seal": (64, "D82"),
    "Seal (+Jnts)": (64, "D82"), "Leveling": (66, "D84"), "Epoxy blank": (67, "D85"),
}
for _g in GYP_SHEETS:
    CHAIN[_g] = (69, "E87")

# The rate cells the writer actually WRITES, checked against the workbook by
# test_the_targets_match_the_workbook_cell_for_cell rather than trusted from here. 17 of them:
# two on each of the six non-gyp layouts, one on each of the five gyp variants.
WIRED = {
    "Epoxy": {"super_pto": "B75", "soft_costs": "B76"},
    "Polish": {"super_pto": "B69", "soft_costs": "B70"},
    "Seal": {"super_pto": "B69", "soft_costs": "B70"},
    "Seal (+Jnts)": {"super_pto": "B69", "soft_costs": "B70"},
    "Leveling": {"super_pto": "B71", "soft_costs": "B72"},
    "Epoxy blank": {"super_pto": "B72", "soft_costs": "B73"},
}
for _g in GYP_SHEETS:
    WIRED[_g] = {"super_pto": "B74"}

# Bond's own rate cells: ON RECORD, DELIBERATELY UNWIRED. Kept in this file rather than deleted
# because they are still workbook facts worth checking (plain numbers, 0.00%, on a row labelled
# 'Bond') and because re-adding bond is one line per layout the day Kyle's D84 stops
# double-counting the tax rows. Nothing in the shipped writer references them --
# test_no_layout_has_a_bond_address_and_the_admin_page_lists_none is what enforces that.
#
# 'Seal (+Jnts)' is absent for a SECOND, independent reason: its B78 is `=Seal!B78`, a mirror, so
# it would stay excluded even once bond is wired. See
# test_seal_joints_bond_is_a_mirror_and_appears_in_no_target_list.
BOND_CELLS = {"Epoxy": "B84", "Polish": "B78", "Seal": "B78", "Leveling": "B80",
              "Epoxy blank": "B81"}
for _g in GYP_SHEETS:
    BOND_CELLS[_g] = "B83"

MARKUP_LAYOUT_OF = {"Epoxy": "epoxy", "Epoxy blank": "epoxy", "Polish": "polish",
                    "Seal": "seal", "Seal (+Jnts)": "seal", "Leveling": "leveling"}
for _g in GYP_SHEETS:
    MARKUP_LAYOUT_OF[_g] = "gyp"

_TOK = re.compile(r"""
    \s*(?:
      (?P<str>"[^"]*")
    | (?P<ref>(?:'[^']+'|[A-Za-z][A-Za-z0-9\ ()+.\-]*)!\$?[A-Z]{1,3}\$?[0-9]{1,7}(?![A-Za-z0-9_.]))
    | (?P<fn>[A-Za-z][A-Za-z0-9_.]*)\s*\(
    | (?P<cell>\$?[A-Z]{1,3}\$?[0-9]{1,7}(?![A-Za-z0-9_.]))
    | (?P<num>[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)
    | (?P<name>[A-Za-z_][A-Za-z0-9_.]*)
    | (?P<op><=|>=|<>|[-+*/^,()<>=:&%])
    )""", re.X)


def _num(v):
    """Excel's own coercion for a SUM: text and blanks are zero, never an error."""
    if v is None or isinstance(v, (str, bool)):
        return 0.0
    return float(v)


def _colnum(c):
    n = 0
    for ch in c:
        n = n * 26 + (ord(ch) - 64)
    return n


def _colname(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


_LOADED = {}


def _books(path):
    """Parsed ONCE per path. openpyxl costs ~3s a pass and a scenario needs a fresh override
    map, not a fresh parse -- the first version of this file took 4 minutes for that reason."""
    key = str(path)
    if key not in _LOADED:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _LOADED[key] = (openpyxl.load_workbook(path, data_only=False),
                            openpyxl.load_workbook(path, data_only=True))
    return _LOADED[key]


class Chain:
    """One scenario's view of a workbook: Kyle's formulas, plus the cells we overrode.

    `chain_rows` lets a COPIED tab be evaluated too: a copy is a clone of its source worksheet,
    so it takes the source layout's row offsets under its own sheet name.
    """

    def __init__(self, path=TEMPLATE, chain_rows=None, cached_from=None):
        self.f, self.v = _books(path)
        if cached_from is not None:
            # A workbook openpyxl WROTE carries no cached results at all -- every formula reads
            # None on the data_only pass. So a generated file is evaluated with the chain from
            # ITS OWN formulas and the above-chain inputs (material, labour, travel) from the
            # template's cached values, which is exactly what the two files share.
            _f, self.v = _books(cached_from)
        self.rows = dict(CHAIN)
        self.src_of = dict(chain_rows or {})
        for sheet, src in self.src_of.items():
            self.rows[sheet] = CHAIN[src]
        self.over = {}
        self._cache = {}

    def put(self, sheet, addr, value):
        self.over[(sheet, addr.replace("$", ""))] = value
        self._cache.clear()
        return self

    def value(self, sheet, addr):
        a = addr.replace("$", "")
        key = (sheet, a)
        if key in self.over:
            return self.over[key]
        if key in self._cache:
            return self._cache[key]
        row = int(re.match(r"[A-Z]{1,3}([0-9]+)$", a).group(1))
        first = self.rows.get(sheet, (10 ** 9,))[0]
        raw = self.f[sheet][a].value
        is_formula = isinstance(raw, str) and raw.startswith("=")
        if row >= first and is_formula:
            self._cache[key] = 0.0                     # cycle guard
            out = _Eval(self, sheet).run(raw[1:])
        elif is_formula:
            # A COPY has no cached twin of its own; it is a clone, so its source's is the same
            # workbook's answer for the same inputs.
            out = self.v[self.src_of.get(sheet, sheet)][a].value
        else:
            out = raw
        self._cache[key] = out
        return out

    def total(self, sheet):
        return _num(self.value(sheet, self.rows[sheet][1]))

    def formula(self, sheet, addr):
        return self.f[sheet][addr.replace("$", "")].value


class _Eval:
    """A recursive-descent reader for the handful of Excel constructs the markup chain uses.

    Deliberately NARROW. It refuses a defined name and any function outside the list in `call`,
    so a formula shape nobody checked cannot quietly evaluate to something plausible -- the same
    fail-closed posture markup-core.js takes on the admin page.
    """

    def __init__(self, book, sheet):
        self.book, self.sheet = book, sheet

    def run(self, src):
        self.toks, pos = [], 0
        while pos < len(src):
            m = _TOK.match(src, pos)
            if not m or m.end() == pos:
                if not src[pos:].strip():
                    break
                raise ValueError("cannot tokenise %r at %r" % (src, src[pos:]))
            pos = m.end()
            self.toks.append((m.lastgroup, m.group(m.lastgroup)))
        self.i = 0
        v = self.expr()
        if self.i != len(self.toks):
            raise ValueError("trailing tokens in %r: %r" % (src, self.toks[self.i:]))
        return v

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def expr(self):
        left = self.arith()
        k, v = self.peek()
        if k == "op" and v in ("=", "<", ">", "<=", ">=", "<>"):
            self.take()
            right = self.arith()
            if isinstance(left, str) or isinstance(right, str):
                a, b = str(left).strip().lower(), str(right).strip().lower()
            else:
                a, b = _num(left), _num(right)
            return {"=": a == b, "<": a < b, ">": a > b, "<=": a <= b,
                    ">=": a >= b, "<>": a != b}[v]
        return left

    def arith(self):
        v = self.term()
        while True:
            k, o = self.peek()
            if k != "op" or o not in "+-":
                return v
            self.take()
            r = self.term()
            v = _num(v) + _num(r) if o == "+" else _num(v) - _num(r)

    def term(self):
        v = self.unary()
        while True:
            k, o = self.peek()
            if k != "op" or o not in "*/":
                return v
            self.take()
            r = self.unary()
            v = _num(v) * _num(r) if o == "*" else _num(v) / _num(r)

    def unary(self):
        k, o = self.peek()
        if k == "op" and o in "+-":
            self.take()
            v = _num(self.unary())
            return -v if o == "-" else v
        v = self.atom()
        while self.peek() == ("op", "%"):     # Excel's postfix percent
            self.take()
            v = _num(v) / 100.0
        return v

    def _split(self, tok):
        if "!" in tok:
            s, a = tok.rsplit("!", 1)
            return s.strip("'"), a
        return self.sheet, tok

    def atom(self):
        k, v = self.take()
        if k == "num":
            return float(v)
        if k == "str":
            return v[1:-1]
        if k == "op" and v == "(":
            e = self.expr()
            _k, close = self.take()
            assert close == ")", (close, self.toks)
            return e
        if k == "name":
            if v.lower() in ("true", "false"):
                return v.lower() == "true"
            raise ValueError("a defined name reached the markup chain: %r" % v)
        if k in ("cell", "ref"):
            sheet, addr = self._split(v)
            if self.peek() == ("op", ":"):
                self.take()
                _k3, tok2 = self.take()
                _s, addr2 = self._split(tok2)
                m1 = re.match(r"([A-Z]{1,3})([0-9]+)$", addr.replace("$", ""))
                m2 = re.match(r"([A-Z]{1,3})([0-9]+)$", addr2.replace("$", ""))
                c1, r1 = _colnum(m1.group(1)), int(m1.group(2))
                c2, r2 = _colnum(m2.group(1)), int(m2.group(2))
                return [self.book.value(sheet, _colname(c) + str(r))
                        for c in range(min(c1, c2), max(c1, c2) + 1)
                        for r in range(min(r1, r2), max(r1, r2) + 1)]
            return self.book.value(sheet, addr)
        if k == "fn":
            args = []
            if self.peek() != ("op", ")"):
                while True:
                    # An EMPTY argument is real: Leveling!D69 holds `SUM(D66,D76,D79,)`.
                    args.append(None if self.peek() in (("op", ","), ("op", ")"))
                                else self.expr())
                    if self.peek() == ("op", ","):
                        self.take()
                        continue
                    break
            _k, close = self.take()
            assert close == ")", (v, close, self.toks)
            return self.call(v.upper(), args)
        raise ValueError("unexpected token %r %r" % (k, v))

    def call(self, name, args):
        flat = []
        for a in args:
            flat.extend(a if isinstance(a, list) else [a])
        if name == "SUM":
            return sum(_num(x) for x in flat)
        if name in ("ROUNDUP", "ROUNDDOWN"):
            # The `round(x*f, 9)` is Excel's own tidy-up before rounding, and it is not optional:
            # xl-excel-rounding.js exists in the frontend for exactly this, because without it
            # 19320.000000000004 rounds UP to 19321 and Epoxy!D88 reads $11,033 for $11,029.
            f = 10 ** int(_num(args[1]) if len(args) > 1 else 0)
            g = math.ceil if name == "ROUNDUP" else math.floor
            return g(round(_num(args[0]) * f, 9)) / f
        if name == "CEILING":
            x, sig = _num(args[0]), _num(args[1])
            return math.ceil(round(x / sig, 9)) * sig if sig else 0.0
        if name == "ROUND":
            return round(_num(args[0]), int(_num(args[1])))
        if name == "IF":
            c = args[0]
            t = c.strip().lower() == "true" if isinstance(c, str) else bool(c)
            return args[1] if t else (args[2] if len(args) > 2 else False)
        if name == "OR":
            return any(bool(x) for x in flat)
        if name == "AND":
            return all(bool(x) for x in flat)
        raise ValueError("the markup chain used an unsupported function: %s" % name)


@pytest.fixture(scope="module")
def wb():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(TEMPLATE, data_only=False)


@pytest.fixture(scope="module")
def cached():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(TEMPLATE, data_only=True)


# ═══ 0. the verifier itself ══════════════════════════════════════════════════


@pytest.mark.parametrize("sheet", PRICED_SHEETS)
def test_the_chain_evaluator_reproduces_excels_own_cached_totals(sheet, cached):
    """Every dollar figure in this file rests on this one.

    The markup chain is walked from Kyle's formula TEXT, so the first thing to establish is that
    walking it reproduces what Excel itself last computed -- otherwise a "delta" below is a delta
    against my own arithmetic rather than against the workbook. Epoxy 11029, Polish 13265,
    Seal 1450 and 'Seal (+Jnts)' 2883 are four different numbers off four different chains, so a
    reader that agreed by accident would have to do it four ways.

    The five gyp variants total 0 because the template ships with no gyp takeoff on them. That
    half is vacuous and is NOT relied on: the gyp dollar tests below pin a sub-total in first."""
    addr = CHAIN[sheet][1]
    mine = Chain().total(sheet)
    theirs = _num(cached[sheet][addr].value)
    assert abs(mine - theirs) < 0.005, (
        "%s!%s evaluated to %s from formula text and Excel's own cached value is %s -- the chain "
        "reader disagrees with the workbook, so no dollar assertion in this file means anything "
        "until it is fixed" % (sheet, addr, mine, theirs))


def test_the_targets_match_the_workbook_cell_for_cell(wb):
    """The address table, checked against the artefact rather than against its own author.

    Every target must be a PLAIN NUMBER on a row whose A-column label names the line -- not a
    formula, not a mirror, not a coordinate somebody generalised from Epoxy. Kyle's gyp block sits
    at different offsets from the epoxy one, so a table reasoned out by pattern would agree with a
    bug.

    BOND'S CELLS ARE CHECKED HERE TOO, even though nothing writes them. They are what a re-add
    would use once the D84 double-count is fixed, and a coordinate nobody checks is a coordinate
    that has quietly moved by then."""
    labels = {"super_pto": "Superintendent & PTO", "soft_costs": "Soft Costs", "bond": "Bond"}
    checkable = {s: dict(spec) for s, spec in WIRED.items()}
    for sheet, addr in BOND_CELLS.items():
        checkable[sheet]["bond"] = addr
    for sheet, spec in checkable.items():
        for line_key, addr in spec.items():
            cell = wb[sheet][addr]
            row_label = wb[sheet]["A" + addr[1:]].value
            assert row_label == labels[line_key], (
                "%s!%s sits on a row labelled %r, not %r"
                % (sheet, addr, row_label, labels[line_key]))
            assert not (isinstance(cell.value, str) and cell.value.startswith("=")), (
                "%s!%s holds a FORMULA (%r) -- writing a literal over it deletes whatever it was "
                "working out" % (sheet, addr, cell.value))
            assert isinstance(cell.value, (int, float)), (
                "%s!%s is %r, not a number" % (sheet, addr, cell.value))
            assert cell.number_format == "0.00%", (
                "%s!%s is formatted %r; a rate written here would not read as a percent"
                % (sheet, addr, cell.number_format))


# ═══ 1. filing nothing changes nothing ══════════════════════════════════════


@needs_node
def test_filing_nothing_changes_nothing(ran):
    """THE DAY-ONE INVARIANT, and the reason this is safe to deploy at all.

    `markup_rules` on production holds 0 rows and 0 deleted rows, verified against the database.
    So the state every existing draft opens into is "no rule matches anything", and in that state
    the writer must not touch one cell, not push one value into HyperFormula, and not report a
    change -- because `init()` SAVES the draft when it reports one, and a save re-snapshots the
    figure the customer's proposal reads.

    The fixture is the whole bid, not one tab: all seven base layouts plus a copy of Epoxy and a
    copy of Gyp (FR), which is 32 live targets."""
    r = ran["nothingFiled"]
    # 20: seventeen base-tab targets (two lines on each of six non-gyp layouts, one on each of
    # five gyp variants), plus two for the copy of Epoxy and one for the copy of Gyp (FR). A
    # hand-written number on purpose -- a count derived from the same table it is checking would
    # pass whatever that table said.
    assert r["targetCount"] == 20, (
        "the fixture stopped covering what it claims to: %d targets" % r["targetCount"])
    assert r["cellValues"] == {}, (
        "an empty rules table wrote %s -- every existing bid would reprice on open"
        % r["cellValues"])
    assert r["hfCalls"] == 0, "an empty rules table pushed values into the live engine"
    assert r["changed"] == 0, (
        "an empty rules table reported a change, so merely opening a draft would save a new "
        "lump sum into it")
    assert r["refreshCalls"] == [], "an empty rules table repainted the grid"


@needs_node
@pytest.mark.parametrize("shape", ["appliesFalse", "appliesFalseWithFormula", "formulaNull",
                                   "formulaEmpty", "formulaBlank", "otherLayout", "otherLine"])
def test_every_degenerate_row_shape_is_also_a_no_op(ran, shape):
    """A row that exists but says nothing usable must leave Kyle's own value standing.

    `appliesFalse` is the one that is not merely arithmetic. backend/markup.py's docstring is
    emphatic that `applies=false, formula=NULL` ("this line does not exist on this tab") and
    `applies=true, formula='0'` ("it exists and prices to nothing") are DIFFERENT FACTS, and
    "collapsing them is the one mistake this module is shaped to prevent". So the writer does not
    turn the first into a zero. The honest consequence -- the tab goes on charging the template's
    rate for a line the admin just switched off -- is said out loud on the Markup page's own row
    instead, which is what test_the_admin_page_says_whether_each_row_reaches_the_workbook checks.
    """
    r = ran["degenerate"][shape]
    assert r["keys"] == [], "%s wrote %s" % (shape, r["keys"])
    assert r["changed"] == 0 and r["hf"] == 0


# ═══ 2. the deferral: gp and hard_bid, by line key ═════════════════════════


@needs_node
def test_a_bare_literal_gp_or_hard_bid_rule_reaches_no_cell(ran):
    """The sharpest hole in the design, and it is created BY the guard being permissive.

    "45%" is a bare percent. It parses. If the exclusion were "refuse anything that does not look
    like a rate", a gp rule filed as "45%" would sail through and replace Kyle's ladder --
    `=IF(D70<6500,0.52,IF(D70<15000,0.45,...))`, five to seven tiers depending on the tab -- with
    one flat number. Nothing would error. The bid would price plausibly and wrongly.

    Two more in the same fixture: a gyp soft-costs percent (which would delete a local/away
    branch, a job-size taper and Kyle's own "error" sentinel) and a gyp hard-bid rate (whose
    `Hard Bid?` cell is a frozen "No", so the discount is zero whatever is filed)."""
    r = ran["deferredLinesReachNothing"]
    assert r["keys"] == [], (
        "a deferred line reached the workbook: %s -- gp's own built-in returns DOLLARS from a "
        "tier ladder, and 1 - 4927 prices catastrophically wrong without erroring" % r["keys"])
    assert r["changed"] == 0 and r["hf"] == 0


@needs_node
def test_no_layouts_target_table_contains_gp_or_hard_bid(ran):
    """The structural half of the test above: the exclusion is an ABSENT ADDRESS.

    Asserting only the behaviour would stay green if somebody added `gp: "B73"` and relied on a
    formula check to hold it back. This says the lookup must MISS."""
    for layout, keys in ran["deferredLinesReachNothing"]["keysPerLayout"].items():
        assert "gp" not in keys, "%s has a gp address; the deferral has to be structural" % layout
        assert "hard_bid" not in keys, "%s has a hard_bid address" % layout
        assert set(keys) <= {"super_pto", "soft_costs", "bond"}, (layout, keys)


@needs_node
def test_gyp_soft_costs_has_no_address_while_the_workbook_cell_is_an_expression(ran, wb):
    """A per-(layout, line_key) exclusion, pinned to the artefact that justifies it.

    If Kyle ever flattens this cell to a plain percent, this test is what tells whoever notices
    that the table can now carry a gyp soft-costs address."""
    for sheet in GYP_SHEETS:
        f = wb[sheet]["B75"].value
        assert isinstance(f, str) and f.startswith("="), (sheet, f)
        assert 'IF(OR(B5="Yes",B5="No")' in f, (sheet, f)
        assert '"error"' in f, (
            "%s!B75 lost its refuse-to-price sentinel: %r" % (sheet, f))
        assert "E69>334900" in f and "E69>234450" in f, (
            "%s!B75 lost its job-size taper: %r" % (sheet, f))
    for layout, keys in ran["deferredLinesReachNothing"]["keysPerLayout"].items():
        if layout.startswith("Gyp"):
            assert "soft_costs" not in keys, "%s got a soft_costs address" % layout


@needs_node
def test_no_layout_has_a_bond_address_and_the_admin_page_lists_none(ran):
    """BOND IS UNWIRED ON PURPOSE, AND THE REASON IS A DEFECT IN KYLE'S OWN FORMULA.

    If you are here because you want to file a bond rate: read
    test_bond_carries_a_dormant_tax_double_count_in_kyles_own_formula first. Kyle's bond row
    multiplies a SUM that references the sales-tax and remodel-tax cells individually AND through
    the 'Total Taxes' cell that sums them, so each tax is counted twice in the bond base:

        Epoxy!D84 = ROUNDUP(SUM(D70,D73,D74,D75:D77,D80,D81:D83)*B84,0)
        Epoxy!D82 = SUM(D80:D81)                      <- inside D81:D83, D80/D81 also explicit

    Bond is 0 on every sheet in the shipped template, so the defect has never been exercised.
    Filing a bond rate is exactly the act that exercises it, and it always over-charges -- in
    front of a customer. Measured: +$110 where the honest figure is +$108 on the template's own
    Leveling tab, scaling with the tax rather than with the bid.

    It is Kyle's formula and his fix. Re-adding bond is one line per layout in
    MARKUP_RATE_TARGETS and one entry per layout in PRICES_THE_BID, once D84 and its ten siblings
    reference the tax rows once each. This test is what stops that happening the other way round.

    BOTH SIDES, because doing one is what actually happened while this was being cut: the writer's
    table and the sentence the admin reads are in different files, and dropping bond from only one
    of them was caught by test_the_writer_and_the_admin_page_never_disagree..., not by review."""
    for layout, keys in ran["targetTable"].items():
        assert "bond" not in keys, (
            "%s has a bond address again -- if Kyle's D84 is fixed, say so in this test's "
            "docstring and delete it; if it is not, this re-add over-charges a customer" % layout)
        assert set(keys) <= {"super_pto", "soft_costs"}, (layout, keys)
    for mk_layout, lines in ran["pricesTheBid"].items():
        assert "bond" not in lines, (
            "markup.js tells an admin bond prices the %s bid; nothing writes it" % mk_layout)
    # And the address it WOULD use is still where this file says it is, so a re-add starts from a
    # checked coordinate rather than a remembered one.
    assert set(BOND_CELLS) == set(PRICED_SHEETS) - {"Seal (+Jnts)"}


# ═══ 3. the round trip ══════════════════════════════════════════════════════


@needs_node
def test_every_built_in_parses_to_the_workbooks_literal_exactly(ran, wb):
    """The round trip, at the level of the number itself.

    For every (layout, line_key) that has an address, the built-in string the Markup page ships
    is parsed and compared against the literal in the .xlsx -- as a STRING first, so 0.027 and
    0.027000000000000003 cannot both pass, and then as a number.

    THE COUNTEREXAMPLE THIS IS NOT VACUOUS AGAINST: `TWMarkup.run("2.7%")` returns
    0.027000000000000003 and `run("4.1%")` returns 0.040999999999999995 -- both measured against
    the real markup-core.js. Both fail the comparison below, and
    test_evaluating_the_rate_instead_of_parsing_it_makes_the_round_trip_go_red proves it by
    committing that mutation."""
    parsed = ran["builtinsFiled"]["parsed"]
    checked = 0
    for sheet, spec in WIRED.items():
        layout = MARKUP_LAYOUT_OF[sheet]
        for line_key, addr in spec.items():
            key = layout + "/" + line_key
            assert key in parsed, "the Markup page ships no built-in for %s" % key
            text = parsed[key]
            assert text is not None, (
                "the built-in for %s does not parse, so filing it would leave %s!%s alone -- the "
                "round trip is broken for that line and it must not ship" % (key, sheet, addr))
            literal = wb[sheet][addr].value
            assert text == repr(float(literal)).rstrip("0").rstrip(".") or \
                float(text) == float(literal), (key, text, literal)
            # The string form is the assertion that bites: 0.027 != 0.027000000000000003 even
            # though both float() to something that looks right in a printout.
            assert float(text) == float(literal), (
                "%s parses to %r and %s!%s holds %r" % (key, text, sheet, addr, literal))
            assert repr(float(text)) == repr(float(literal)), (
                "%s parses to %r, which is not bit-identical to %s!%s's %r -- this is the "
                "0.027000000000000003 failure and it costs a dollar per round sub-total"
                % (key, text, sheet, addr, literal))
            checked += 1
    assert checked == 17, "expected 17 base-tab targets, checked %d" % checked


@needs_node
@pytest.mark.parametrize("sheet", PRICED_SHEETS)
def test_the_round_trip_holds_in_dollars_on_every_layout(ran, sheet, wb):
    """Filing a line's own built-in value must produce the SAME PRICE, to the dollar.

    Not "a similar price" and not "the same rate in the cell" -- the same total out of the bottom
    of Kyle's chain. This is the assertion the whole feature was gated on, and it is run on every
    priced sheet because the six chains differ in their SUM ranges.

    Gyp gets a pinned sub-total first: the template ships with no gyp takeoff, so without one the
    total is 0 before and after and the test would prove nothing at all."""
    parsed = ran["builtinsFiled"]["parsed"]
    layout = MARKUP_LAYOUT_OF[sheet]
    subtotal_addr = ("E69" if sheet.startswith("Gyp") else None)

    def book():
        c = Chain()
        if subtotal_addr:
            c.put(sheet, subtotal_addr, 50000)
        return c

    before = book().total(sheet)
    if subtotal_addr:
        assert before > 0, "the gyp fixture failed to pin a sub-total"

    after = book()
    for line_key, addr in WIRED[sheet].items():
        text = parsed[layout + "/" + line_key]
        assert text is not None
        after.put(sheet, addr, float(text))
    assert after.total(sheet) == before, (
        "%s: filing its own built-in rates moved the total from %s to %s. A round trip that does "
        "not hold means an admin cannot even record today's rates without repricing every bid"
        % (sheet, before, after.total(sheet)))


@needs_node
@pytest.mark.parametrize("sheet,expected_delta", [
    ("Epoxy", 107.0), ("Polish", 168.0), ("Seal", 19.0), ("Seal (+Jnts)", 36.0),
    ("Leveling", 104.0), ("Epoxy blank", 107.0),
])
def test_a_filed_super_pto_rate_moves_the_total_by_the_hand_computed_amount(sheet,
                                                                           expected_delta):
    """A DIFFERENT rate, in dollars, against a figure worked out by hand.

    Epoxy, longhand: D70 = 4548 and D73 = 4927, so super_pto's base
    `SUM(D70:D74,D77,D80,D83)` is 9475. At Kyle's 3% that is ROUNDUP(284.25) = 285; at 4% it is
    379. Soft costs then compounds on it -- base 4548+4927+379 = 9854, at 13% ROUNDUP(1281.02) =
    1282 against 1269 -- and D88 = SUM(D70,D73:D77,D82,D85) comes out 11136 against 11029. +107.

    Six different numbers off six different chains. A writer that reached the wrong cell, or the
    right cell on the wrong sheet, cannot produce this row by coincidence."""
    addr = WIRED[sheet]["super_pto"]
    before = Chain().total(sheet)
    after = Chain().put(sheet, addr, 0.04).total(sheet)
    assert after - before == expected_delta, (
        "%s: 4%% into %s moved the total by %+.2f, not %+.2f"
        % (sheet, addr, after - before, expected_delta))


@needs_node
@pytest.mark.parametrize("sheet", GYP_SHEETS)
def test_a_filed_gyp_rate_moves_all_five_variants_identically(sheet):
    """All five gyp variants carry INDEPENDENT literals -- none mirrors another -- so one filed
    `gyp` row has to reach five sheets. On a pinned $50,000 sub-total the arithmetic is the same
    on each, which is exactly why missing one would be invisible on the screen and visible on the
    customer's proposal."""
    before = Chain().put(sheet, "E69", 50000).total(sheet)
    after = Chain().put(sheet, "E69", 50000).put(sheet, "B74", 0.05).total(sheet)
    assert before == 84679.0, (
        "%s no longer prices a pinned $50,000 sub-total at 84679 -- its chain has changed and "
        "the delta below needs re-deriving: %s" % (sheet, before))
    assert after - before == 733.0, (
        "%s: 5%% into B74 moved the total by %+.2f, not +733" % (sheet, after - before))


# ═══ 4. the fan-out ════════════════════════════════════════════════════════


@needs_node
def test_the_fan_out_writes_exactly_these_cells(ran):
    """BY EQUALITY, not by containment. A superset is the PR #432 bug in the other direction.

    Five markup layouts against eleven priced sheets: one filed `seal` row reaches Seal AND
    'Seal (+Jnts)'; one filed `gyp` row reaches five variants; `epoxy` covers Epoxy AND
    'Epoxy blank' at DIFFERENT addresses. Writing only the obvious sheet is what left Seal,
    Leveling, blank tabs and every copy on the old remodel rate."""
    expected = sorted("%s!%s" % (sheet, addr)
                      for sheet, spec in WIRED.items() for addr in spec.values())
    assert ran["fanOut"]["written"] == expected
    assert ran["fanOut"]["changed"] == 17
    # The fixture files bond on all five layouts and none of it lands. That is the whole of
    # `bond`'s deferral, seen from the fan-out.
    assert not [k for k in ran["fanOut"]["written"] if k.split("!")[1] in BOND_CELLS.values()
                and k.split("!")[0] in BOND_CELLS
                and BOND_CELLS[k.split("!")[0]] == k.split("!")[1]], (
        "a bond cell was written: %s" % ran["fanOut"]["written"])
    assert ran["fanOut"]["hfWritten"] == sorted(k + " -> =0.04" for k in expected), (
        "the live engine and the .xlsx were sent different things")


@needs_node
def test_seal_joints_bond_is_a_mirror_and_appears_in_no_target_list(ran, wb):
    """A CORRECTION to the original brief, pinned to the workbook so it cannot be re-litigated.

    MOOT FOR SHIPPING -- bond is unwired on every layout -- and kept because it is the SECOND,
    INDEPENDENT reason this one cell stays excluded on the day bond is re-added. Somebody who
    fixes Kyle's D84 and puts bond back on every layout would otherwise fork two of his sheets,
    and the D84 fix is not the thing that makes this cell safe.

    'Seal (+Jnts)'!B78 holds `=Seal!B78`. Its absence from estimate_writer.LOCK_MAP (7 addresses
    against Seal's 8) and from LOCKED_CELLS in estimate-review.js is because it is a MIRROR, not
    because the line is missing. Writing a literal there forks the two sheets permanently -- the
    divergence PR #432 refused to introduce for the remodel rate, and the one found in Kyle's own
    filed workbooks. Writing Seal!B78 carries it, which the dollar assertion below shows.

    Its B69/B70 ARE its own literals and DO get written, which is why the table is keyed by
    (layout, line_key) rather than by layout."""
    assert wb["Seal (+Jnts)"]["B78"].value == "=Seal!B78", (
        "'Seal (+Jnts)'!B78 is no longer a mirror (%r) -- revisit the target table"
        % wb["Seal (+Jnts)"]["B78"].value)
    assert isinstance(wb["Seal (+Jnts)"]["B69"].value, (int, float))
    assert isinstance(wb["Seal (+Jnts)"]["B70"].value, (int, float))

    assert "bond" not in ran["targetTable"]["Seal (+Jnts)"]
    assert set(ran["targetTable"]["Seal (+Jnts)"]) == {"super_pto", "soft_costs"}
    assert "Seal (+Jnts)!B78" not in ran["fanOut"]["written"]
    # And the mirror still carries the rate, so excluding it costs nothing: a bond filed on Seal
    # moves 'Seal (+Jnts)' too, through Kyle's own formula.
    before = Chain().total("Seal (+Jnts)")
    after = Chain().put("Seal", "B78", 0.01).total("Seal (+Jnts)")
    assert after > before, (
        "writing Seal!B78 no longer reaches 'Seal (+Jnts)' through the mirror, so excluding its "
        "own B78 now leaves that tab unpriced -- the table needs revisiting")


@needs_node
def test_an_off_screen_template_sheet_is_still_written(ran):
    """All sixteen worksheets ship in the .xlsx Kyle opens, whether or not the tab is on screen.

    Pass 1 of the fan-out is the template layouts for that reason: an estimator sitting on Polish
    still downloads a workbook whose Epoxy tab must carry the filed rate."""
    assert ran["offScreenSheet"]["epoxy"] == "=0.04"
    assert ran["offScreenSheet"]["refreshCalls"] == [], (
        "the grid was repainted for a sheet that is not open")


# ═══ 5. copies and structural edits ════════════════════════════════════════


@needs_node
def test_a_copied_tab_takes_the_rate_at_its_own_layouts_address(ran):
    """A copy is the ordinary way to add a priced proposal option, and the backend clones it from
    the PRISTINE template -- so its rate cells arrive holding the template's own percent."""
    c = ran["copies"]["copyOfPolish"]
    assert c["copy1"] == "=0.04" and c["base"] == "=0.04"


@needs_node
def test_a_copy_of_a_copy_resolves_through_the_chain_to_its_template_layout(ran):
    """`layoutIdFor` walks copy-source chains 20 deep, mirroring `_resolve_ws_layouts`' own walk in
    estimate_writer.py. Copy2 -> Copy1 -> 'Gyp (FR)' has to land on B74 -- the gyp layout's own
    address, not Epoxy's.

    The fixture files a gyp BOND rate as well, and it must reach nothing: bond is unwired on every
    layout while Kyle's D84 double-counts the tax rows, and walking a copy chain is no reason for
    that to change. Reported as a boolean because JSON drops an undefined key, which would make
    "the assertion read the wrong name" and "bond was excluded" the same green."""
    c = ran["copies"]["copyOfCopy"]
    assert c["copy2super"] == "=0.05"
    assert c["copy1super"] == "=0.05" and c["baseSuper"] == "=0.05"
    assert c["bondWrittenAnywhere"] is False, (
        "a filed gyp bond rate reached a B83 cell somewhere in the copy chain")


@needs_node
def test_inserted_rows_move_the_target_and_leave_no_write_at_the_old_address(ran):
    """Every address goes through `txAddr`, so two rows inserted above the block move B69/B70/B78
    to B71/B72/B80 -- and nothing is written at the template coordinates, which on a shifted sheet
    are three unrelated cells."""
    c = ran["copies"]["insertedRows"]
    assert c["moved"] == ["=0.04", "=0.07"]
    assert c["staleWritten"] == [], (
        "a rate was written at the pre-shift address %s, which is now some other row"
        % c["staleWritten"])
    assert c["base"] == ["=0.04", "=0.07"], "the unshifted base tab stopped being written"
    # Bond's shifted address (B78 -> B80) and its unshifted one are both left alone.
    assert c["bondMoved"] is None and c["baseBond"] is None, (
        "a filed bond rate was written; it is unwired on every layout")


@needs_node
def test_a_deleted_rate_row_is_dropped_rather_than_written_at_a_stale_address(ran):
    """The case that keeps the screen, the .xlsx and the lock preset agreeing about a cell that is
    no longer there. `txAddr` returns null for a deleted coordinate and that ONE target is
    dropped, not the whole sheet -- soft costs (B70 -> B69) and bond (B78 -> B77) still move.

    The three rates are DIFFERENT here on purpose. Filed at one rate, a soft-costs value that had
    slid into the deleted super_pto's address would be byte-identical to the bug being ruled
    out."""
    c = ran["copies"]["deletedRow"]
    assert c["copyCells"] == {"Copy1!B69": "=0.07"}, (
        "after deleting row 69 the copy's writes are %s -- expected soft costs alone, shifted up "
        "from B70, with the deleted super_pto target dropped and bond unwired" % c["copyCells"])
    assert c["superPtoRateAnywhereOnTheCopy"] is False, (
        "the deleted super_pto rate was written somewhere on the copy anyway")
    assert c["base"] == ["=0.04", "=0.07"]


@needs_node
def test_writing_while_sitting_on_a_copied_tab_keeps_its_cache(ran):
    """A copy has no server-side worksheet, so the full re-render the autofill path uses
    (`delete sheetCache[activeSheet]; showSheet(...)`) 404s and renders "Failed to load Copy1"
    with its cache gone. That was found by driving a real browser and by nothing else, which is
    why the cheap `refreshActiveGridFromHF` path is the one this writer uses."""
    r = ran["onACopy"]
    assert r["copy1"] == "=0.04"
    assert r["cachePreserved"] is True, "the copied tab's cache was discarded"
    assert r["gridRefreshedFor"] == ["Copy1"]


@needs_node
def test_applying_twice_reports_no_second_change(ran):
    """`changed` is what `init()` decides to SAVE on, so an apply that is already in force must
    report 0 -- otherwise every page load writes the draft again."""
    assert ran["idempotent"]["first"] == 17
    assert ran["idempotent"]["second"] == 0
    assert ran["idempotent"]["keys"] == 17


@needs_node
def test_saved_draft_markup_cells_are_not_rewritten_on_load(ran):
    """A draft's saved rate cells must beat the current admin defaults when Estimate Review opens."""
    r = ran["savedDraftCellsWin"]
    assert r["changed"] == 16
    assert r["epoxySuperPto"] == "=0.025"
    assert r["epoxySoftCosts"] == "=0.04"
    assert r["wroteSkippedCell"] is False


@needs_node
def test_the_xlsx_still_gets_the_rate_when_the_engine_is_not_up(ran):
    """`cellValues` is what /api/generate fills the workbook from. A write that only reached
    HyperFormula would be a screen that agreed with nothing it produced."""
    assert ran["hfNotReady"]["epoxy"] == "=0.04"
    assert ran["hfNotReady"]["hf"] == 0
    assert ran["hfNotReady"]["changed"] == 2, "epoxy covers Epoxy and 'Epoxy blank'"


# ═══ 6. the parser ═════════════════════════════════════════════════════════


@needs_node
def test_the_percent_parser_accepts_only_a_plain_percent(ran):
    """THE `%` IS REQUIRED, which is stricter than the spec this was built from asked for.

    With it optional, the same digits mean a 100x different rate depending on a sign the admin may
    forget: "0.5" would read as fifty percent and "0.5%" as half a percent, and no ceiling can
    tell them apart because 0.5 is a perfectly ordinary number. The asymmetry is backwards from
    intuition too -- a bare "3" is refused while a bare "0.5" would be silently accepted as 50%.
    Every built-in on the Markup page carries an explicit `%`, so requiring it costs nothing and
    closes a 100x misprice. Combined with the bond findings below, a bond filed as "0.5" would
    have put half the bid on a customer's proposal.

    100% and above is refused as a typo: no Super & PTO, Soft Costs or Bond rate is ever that."""
    accepted = dict(ran["parser"]["accepted"])
    assert accepted == {
        "3%": "0.03", "13%": "0.13", "2.7%": "0.027", "16%": "0.16", "4.1%": "0.041",
        "0%": "0", " 2.7 % ": "0.027", "0.5%": "0.005", ".5%": "0.005", "99.9%": "0.999",
        "2.70%": "0.027", "10%": "0.1",
    }
    for text, got in ran["parser"]["refused"]:
        assert got is None, "%r was accepted and parsed to %r" % (text, got)
    refused = {t for t, _ in ran["parser"]["refused"]}
    for must in ("0.5", ".5", "0.03", "3", "1", "100%", "-4%"):
        assert must in refused, "%r is missing from the adversarial list" % must


@needs_node
def test_a_refused_formula_writes_nothing_at_all(ran):
    """Refusing to PARSE and refusing to WRITE are two different facts, so both are asserted.

    A parser that returned null while the caller wrote `=null` would be worse than no parser."""
    for text, keys in ran["parser"]["refusedWroteNothing"]:
        assert keys == [], "%r left %s in cellValues" % (text, keys)
    for text, keys in ran["parser"]["acceptedWrote"]:
        assert keys == ["Epoxy!B75", "Epoxy blank!B72"], (text, keys)


@needs_node
def test_the_writer_and_the_admin_page_never_disagree_about_what_reaches_the_bid(ran):
    """TWO COPIES OF ONE RULE, IN TWO FILES, executed against one input table.

    `rateTextFrom` (estimate-review.js) decides whether a rate is written; `ratePctFrom`
    (markup.js) decides whether the admin is told it will be. markup.js is not loaded on the
    estimate page and cannot be -- loading it would run its whole IIFE against a DOM it does not
    have -- so the duplication is real and this is what keeps it honest. A page that says "prices
    the bid" about a formula the writer skips is the exact failure the deleted paragraph existed
    to warn about."""
    for text, rate, pct in ran["parserAgreement"]:
        assert (rate is None) == (pct is None), (
            "%r: the writer says %r and the admin page says %r" % (text, rate, pct))
        if rate is None:
            continue
        # And they must agree on the MAGNITUDE, not just on yes/no: the percent shown to the
        # admin, shifted two places left, is the decimal written into Kyle's cell.
        assert float(pct.rstrip("%")) / 100.0 == pytest.approx(float(rate), abs=1e-12), (
            "%r: the admin is shown %s and the bid is charged %s" % (text, pct, rate))


# ═══ 7. the two-language seam ══════════════════════════════════════════════


@needs_node
def test_every_write_is_a_formula_and_coerce_keeps_it_one(ran):
    """The seam a JS-only test passes straight through while the download disagrees.

    `estimate_writer._coerce` runs on every cell_values entry. It tries float() and int() FIRST,
    so a bare "0.04" would land as a number -- which is a different bug, not this one -- and a
    string starting with "=" is kept as a formula only if `_is_safe_formula` accepts it. A
    rejected one gets an apostrophe and becomes TEXT, which is how a quoted-sheet-name mirror
    once made the screen say tax-free while the .xlsx charged 9.475%.

    Also asserted: `refreshDomFromHF`'s own gate, executed. All 27 target cells are PLAIN numbers
    in the template, so `=0.04` rather than `0.04` is what makes the rate cell itself repaint
    above its corrected totals instead of showing the old percent."""
    for key, value in ran["builtinsFiled"]["cellValues"].items():
        assert re.match(r"^=\d", value), "%s was written as %r" % (key, value)
        assert ew._is_safe_formula(value), "%s: _is_safe_formula rejects %r" % (key, value)
        assert ew._coerce(value) == value, (
            "%s: _coerce turned %r into %r -- the .xlsx would disagree with the screen"
            % (key, value, ew._coerce(value)))
    assert ran["builtinsFiled"]["hfMatchesCellValues"] is True
    assert ran["builtinsFiled"]["everyWriteIsAFormula"] is True

    gate = dict((k, v) for k, v in ran["userFormulaGate"])
    assert gate["=0.04"] is True and gate["=0"] is True
    assert gate["0.04"] is False and gate["'0.04'"] is False and gate["null"] is False


def test_coerce_would_turn_gps_own_built_in_into_text(wb):
    """WHY gp is deferred rather than guarded, in the backend's own words.

    The shipped built-in serialises to `MARKUP(BAND(subtotal, 6500,52%, ...))`. MARKUP and BAND
    are not in `_SAFE_FORMULA_FUNCS`, so `_coerce` apostrophe-escapes the whole thing and Kyle's
    `=ROUNDUP(SUM(D70,D80,D83)/(1-B73),0)-...` reads #VALUE!. And MARKUP() returns DOLLARS, not a
    rate: Epoxy's cached GP figure is 4927, and `1 - 4927` prices catastrophically wrong without
    erroring at all."""
    gp = "=MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 30%))"
    assert ew._is_safe_formula(gp) is False
    assert ew._coerce(gp) == "'" + gp
    ladder = wb["Epoxy"]["B73"].value
    assert isinstance(ladder, str) and ladder.startswith("=IF(D70<6500,0.52")


def _fill(cell_values, tab_copies=None, tab_structs=None):
    """The .xlsx an estimator actually downloads, built by the real writer."""
    data = ew.fill_estimate({}, cell_values=dict(cell_values or {}),
                            tab_copies=tab_copies, tab_structs=tab_structs)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(io.BytesIO(data), data_only=False)


@pytest.fixture(scope="module")
def filled():
    """One generated workbook shared by the tests below: super_pto 4% on epoxy and polish, with a
    copy of Polish, which is what a bid with one priced option looks like."""
    cv = {"Epoxy!B75": "=0.04", "Epoxy blank!B72": "=0.04",
          "Polish!B69": "=0.04", "Seal!B69": "=0.04", "Seal (+Jnts)!B69": "=0.04",
          "Copy1!B69": "=0.04"}
    return _fill(cv, tab_copies=[{"id": "Copy1", "source": "Polish"}])


def test_the_generated_xlsx_holds_the_rate_as_a_formula_not_as_text(filled):
    """Through the real fill_estimate, on the real template: the cell has to arrive as `=0.04`.

    Step ordering is already right and no lock change was needed for this -- copies land at step
    1.5, structural replay at 1.55, cell_values at step 2, and the sheet is protected LAST at step
    6 -- which is why `applyRemodelRateOverride` already writes the LOCK_MAP cell Epoxy!B81 in
    production on exactly this path."""
    for sheet, addr in [("Epoxy", "B75"), ("Polish", "B69"), ("Copy1", "B69")]:
        v = filled[sheet][addr].value
        assert v == "=0.04", "%s!%s came out as %r" % (sheet, addr, v)
        assert filled[sheet][addr].number_format == "0.00%", (
            "%s!%s lost its percent format, so it would read as 0.04 on screen" % (sheet, addr))


def test_the_downloaded_workbook_prices_the_filed_rate_on_the_base_tab_and_on_the_copy(filled):
    """THE THIRD ARTEFACT, in dollars. Two out of three is the failure this keeps shipping.

    The copy is the half that has burned this repo before: it is cloned from the pristine
    template, so a rate that reached only the sheets on screen leaves a priced option quoting the
    old number on the same customer's proposal."""
    data = ew.fill_estimate({}, cell_values={
        "Epoxy!B75": "=0.04", "Polish!B69": "=0.04", "Copy1!B69": "=0.04"},
        tab_copies=[{"id": "Copy1", "source": "Polish"}])
    tmp = pathlib.Path(__file__).resolve().parent / "_markup_rate_filled.xlsx"
    try:
        tmp.write_bytes(data)
        priced = Chain(path=tmp, chain_rows={"Copy1": "Polish"}, cached_from=TEMPLATE)
        assert priced.total("Epoxy") == 11136.0, priced.total("Epoxy")
        assert priced.total("Polish") == 13433.0, priced.total("Polish")
        assert priced.total("Copy1") == 13433.0, (
            "the copied tab priced at %s while its source priced at %s -- a priced option on the "
            "same proposal quoting a different rate is exactly the PR #432 failure"
            % (priced.total("Copy1"), priced.total("Polish")))
        # …and the un-filed lines are untouched, so nothing else moved.
        assert priced.formula("Polish", "B70") == Chain().formula("Polish", "B70")
        assert priced.formula("Polish", "B78") == Chain().formula("Polish", "B78")
    finally:
        _LOADED.pop(str(tmp), None)
        tmp.unlink(missing_ok=True)


# ═══ 8. the admin page ═════════════════════════════════════════════════════


@needs_node
def test_prices_the_bid_matches_the_writers_own_target_table(ran):
    """The Markup page's reachability list, checked against the writer's addresses.

    `PRICES_THE_BID` in markup.js is the (markup layout -> line keys) projection of
    `MARKUP_RATE_TARGETS` in estimate-review.js, taken as the UNION over the template layouts that
    map to it -- one filed `seal` row covers Seal's three lines and 'Seal (+Jnts)'' two. Computed
    here from the lifted tables rather than retyped, so adding a target without telling the admin
    page fails right here."""
    projected = {}
    for layout, spec in ran["targetTable"].items():
        mk = ran["layoutOf"][layout]
        projected.setdefault(mk, set()).update(spec.keys())
    claimed = {k: set(v) for k, v in ran["pricesTheBid"].items()}
    assert claimed == projected, (
        "markup.js tells the admin %s reaches the bid; the writer actually writes %s"
        % (claimed, projected))


@needs_node
def test_the_admin_page_says_whether_each_row_reaches_the_workbook(ran):
    """Five states, because they are five different things for the admin to do next.

    Without this an admin files a GP ladder, watches it save, and moves no price -- the precise
    failure the "not pricing anything yet" paragraph was written about, just relocated onto the
    four lines that are still not read. The sentence also echoes the RESOLVED PERCENT, so the page
    confirms the magnitude and not merely the fact of the write.

    The uncomfortable one is `switchedOff`: markup.py keeps "not used on this tab" apart from a
    zero, so the writer leaves Kyle's live literal alone -- and the row says so rather than
    letting the admin believe they have switched a charge off."""
    s = ran["reachSentence"]
    assert "does not read this line yet" in s["gpPolish"]
    assert "does not read this line yet" in s["hardBidEpoxy"]
    assert "does not read this line yet" in s["gypSoftCosts"]
    assert "does not read this line yet" in s["unknownLayout"], (
        "an unrecognised layout must claim nothing rather than promise a price")

    assert "does not read this line yet" in s["bondEpoxy"], (
        "bond is unwired on every layout while Kyle's D84 double-counts the tax rows, and an "
        "admin filing 1%% must be told it moves no price -- not left to find out from a bid")
    assert "does not read this line yet" in s["bondGyp"]

    assert "Prices the bid" in s["polishSoftCosts"] and "16%" in s["polishSoftCosts"]
    assert "Prices the bid" in s["filed"] and "4%" in s["filed"]
    assert "epoxy" in s["filed"]
    assert "0.5%" in s["filedSeal"] and "sealed concrete" in s["filedSeal"]
    assert "4.1%" in s["filedGypSuper"] and "gypsum underlayment" in s["filedGypSuper"]

    assert "keeps its own rate until a percent is filed" in s["unfiled"]
    assert "Only a plain percent" in s["unparseable"], (
        "a filed formula the writer will skip must say so; 0.04 with no %% sign is the realistic "
        "one, and silently doing nothing is what this sentence exists to prevent")
    assert "Switched off" in s["switchedOff"] and "still charges" in s["switchedOff"]

    assert s["readOnly"] == "", (
        "a read-only line got a sentence appended; test_markup_page.py compares contingency and "
        "remodel_tax against markup.py character for character and would go red")


def test_the_paragraph_promising_that_nothing_is_priced_is_gone():
    """The pin in test_markup_page.py:774-802 is two-directional and has now FLIPPED.

    It computes {js/*.js mentioning "api/markup"} - {markup.js} and, the moment that set is
    non-empty, requires the paragraph to be gone. estimate-review.js fetches the rules, so it is
    non-empty. Restated here so a reader of THIS file knows the deletion was forced rather than
    cosmetic -- and so the true half of the old paragraph is checked to have survived the
    rewrite."""
    html = (FRONTEND / "markup.html").read_text(encoding="utf-8")
    assert "Filed rates are not pricing anything yet." not in html
    assert "api/markup" in (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    # The clause that is still true: no filed rate reaches the Polish beta, which prices off
    # polish-bid-core.js's own RATES/GP_BANDS. Deleting the paragraph outright would have lost it.
    assert "Polish beta" in html and "its own engine" in html, (
        "the rewrite dropped the Polish beta caveat, which is still true -- a filed polish rate "
        "moves the workbook's price and not the beta's")
    # And the sentence test_markup_page.py keeps out by name is still out.
    assert "rows override the constants" not in html


def test_the_estimate_page_does_not_load_the_formula_engine():
    """The temptation removed at the source.

    markup-core.js is what evaluates a formula, and `run("2.7%")` is the 0.027000000000000003
    that breaks the round trip. The estimate page never loads it, so there is no engine on the
    pricing screen to reach for -- one fewer script tag, and `engine_pages` in
    test_markup_page.py's pin stays empty."""
    page = (FRONTEND / "estimate-review.html").read_text(encoding="utf-8")
    assert not re.search(r"<script[^>]+src=[\"'][^\"']*markup-core", page), (
        "the estimate page loads the formula engine; nothing on it may evaluate a filed formula")
    src = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    # The engine's global, never referenced. A comment naming it is fine and there is one -- it
    # records the two float values that make evaluating wrong -- so this looks for the reach, not
    # for the word.
    assert "window.TWMarkup" not in src
    assert not re.search(r"TWMarkup\s*\.\s*(run|validate)\s*\(", src), (
        "estimate-review.js calls the formula engine; run(\"2.7%\") is 0.027000000000000003 and "
        "prices a dollar high through every ROUNDUP")


@needs_node
def test_a_failed_rules_load_prices_nothing(ran):
    """A 500, a thrown fetch and a 200 with no `rules` key all have to mean "no rules".

    The feature going inert is a correct bid; a half-applied rate is not. `markup_rules` may not
    be applied on the separate staging Postgres yet, and an unapplied table there surfaces as a
    502 -- so the worst case has to be the feature doing nothing."""
    r = ran["load"]
    assert r["counts"] == [1, 0, 0, 0]
    assert r["okUrl"] == "/api/markup/rules", (
        "the fetch must be one un-filtered GET: a bid can carry tabs from several layouts")
    assert r["okSentAuth"] == ["Authorization"], "the GET went out unauthenticated"
    assert r["okApplied"] == 2 and r["okEpoxy"] == "=0.04"
    assert r["badApplied"] == 0 and r["badKeys"] == []
    assert r["thrownApplied"] == 0 and r["junkApplied"] == 0


# ═══ 9. the defect this feature makes reachable ════════════════════════════


@pytest.mark.parametrize("sheet,bond_addr,taxes_addr", [
    ("Epoxy", "B84", "D82"), ("Polish", "B78", "D76"), ("Seal", "B78", "D76"),
    ("Leveling", "B80", "D78"), ("Epoxy blank", "B81", "D79"),
    ('Gyp (USG 1-8")', "B83", "E81"),
])
def test_bond_carries_a_dormant_tax_double_count_in_kyles_own_formula(sheet, bond_addr,
                                                                     taxes_addr, wb):
    """DOCUMENTATION OF A LIVE DEFECT IN THE WORKBOOK. It guards no shipped behaviour, because
    **bond is deliberately unwired** -- nothing this repo ships writes a bond rate, and
    test_no_layout_has_a_bond_address_and_the_admin_page_lists_none is what keeps it that way.
    This test exists to explain WHY, so the next reader finds a formula defect rather than
    assuming somebody forgot a line.

    Kyle's bond base lists the sales-tax and remodel-tax cells individually AND the 'Total Taxes'
    cell that sums them, so each tax is counted twice:

        Epoxy!D84 = ROUNDUP(SUM(D70,D73,D74,D75:D77,D80,D81:D83)*B84,0)
        Epoxy!D82 = SUM(D80:D81)                     <- inside D81:D83, and D80/D81 also explicit

    Bond is 0 on every sheet in the shipped template, so this has never once been exercised in
    production. Filing a bond rate would be the act that exercises it. Direction is always an
    OVER-charge, and the size is roughly `rate x total tax` -- about $28 on a $36.7k bid carrying
    $2,763 of tax at 1%, in front of a customer.

    IT IS KYLE'S FORMULA, SO IT IS HIS FIX. Wiring the line up first and asking him afterwards
    would put the over-charge on a proposal before anybody had agreed to it. The workbook needs
    D84 and its ten siblings to reference the tax rows once each; after that, re-adding bond is
    one line per layout in MARKUP_RATE_TARGETS and one entry per layout in PRICES_THE_BID, and
    the round trip is already known to hold for it (see
    test_bonds_round_trip_would_have_held_which_is_not_why_it_is_unwired).

    THIS TEST GOING RED IS GOOD NEWS: it means the double count is gone. Check the formulas, then
    delete this test and the exclusion together."""
    col = "E" if sheet.startswith("Gyp") else "D"
    f = wb[sheet][col + bond_addr[1:]].value
    assert isinstance(f, str) and f.startswith("=ROUNDUP(SUM("), (sheet, f)

    # Expand the SUM's arguments, ranges included -- the double count arrives THROUGH a range
    # (D81:D83 on Epoxy), so a substring search for "D82" finds nothing and proves nothing.
    args = re.match(r"^=ROUNDUP\(SUM\((.*?)\)\*", f).group(1)
    counted = []
    for part in args.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            a, b = part.split(":")
            r1 = int(re.match(r"[A-Z]+([0-9]+)$", a).group(1))
            r2 = int(re.match(r"[A-Z]+([0-9]+)$", b).group(1))
            counted.extend(col + str(r) for r in range(min(r1, r2), max(r1, r2) + 1))
        else:
            counted.append(part)

    assert taxes_addr in counted, (
        "%s's bond base no longer includes the Total Taxes cell %s -- the double count may have "
        "been fixed, in which case delete this test: %r" % (sheet, taxes_addr, f))
    taxes_f = wb[sheet][taxes_addr].value
    assert isinstance(taxes_f, str) and taxes_f.startswith("=SUM("), (sheet, taxes_f)
    # …and its own components are counted a SECOND time, individually, in the same SUM.
    inner = re.match(r"^=SUM\((.*?)\)$", taxes_f).group(1)
    a, b = inner.split(":")
    r1 = int(re.match(r"[A-Z]+([0-9]+)$", a).group(1))
    r2 = int(re.match(r"[A-Z]+([0-9]+)$", b).group(1))
    components = [col + str(r) for r in range(min(r1, r2), max(r1, r2) + 1)]
    for c in components:
        assert c in counted, (
            "%s: %s is inside %s but not counted separately, so there is no double count here "
            "after all -- re-read this test's docstring before trusting it" % (sheet, c, taxes_addr))
    assert len(components) == 2, (sheet, components)


def test_the_bond_double_count_is_worth_two_dollars_on_the_templates_own_leveling_tab():
    """The same finding, in dollars rather than in formula text.

    Leveling is the one tab the shipped template carries real tax on ($157). At 1% bond the total
    moves +110; the honest figure on a base that counted the tax once is +108. Small here only
    because the tax is small: it scales with the tax, not with the bid."""
    before = Chain().total("Leveling")
    after = Chain().put("Leveling", "B80", 0.01).total("Leveling")
    assert before == 10763.0 and after == 10873.0, (before, after)

    # The base Kyle's formula actually multiplies, and the base without the double count.
    c = Chain().put("Leveling", "B80", 0.01)
    counted = sum(_num(c.value("Leveling", a)) for a in
                  ["D66", "D69", "D70", "D71", "D72", "D73", "D76", "D77", "D78", "D79"])
    taxes = _num(c.value("Leveling", "D78"))
    assert taxes == 157.0
    assert math.ceil(round(counted * 0.01, 9)) == 110
    assert math.ceil(round((counted - taxes) * 0.01, 9)) == 108, (
        "the double count is no longer worth $2 here; re-derive the figures in this docstring")


def test_bonds_round_trip_would_have_held_which_is_not_why_it_is_unwired():
    """Naming the argument that did NOT decide this, so nobody reaches for it later.

    Bond passes every gate the other two lines pass. Its literal is 0 on all eleven priced
    sheets, its built-in is "0%", and `0 x anything` is 0 -- so filing today's rate could not move
    a price, and the round-trip invariant holds for it exactly. It is unwired anyway, because the
    round trip is not the only thing that matters: the FIRST NON-ZERO rate anybody files goes
    through a formula that counts the tax twice, and a feature whose safe case is "nobody uses it"
    is not a feature.

    Recorded here so that when Kyle's D84 is fixed, the re-add starts from a checked fact instead
    of a re-derivation."""
    for sheet, bond_addr in BOND_CELLS.items():
        before = Chain().total(sheet)
        after = Chain().put(sheet, bond_addr, 0).total(sheet)
        assert after == before, (sheet, before, after)
    # …and the built-in the Markup page ships for it parses exactly onto that literal, so the
    # parser is not what would need revisiting either.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = openpyxl.load_workbook(TEMPLATE, data_only=False)
    for sheet, bond_addr in BOND_CELLS.items():
        assert float(book[sheet][bond_addr].value) == 0.0, (sheet, bond_addr)


# ═══ 10. the mutations: each guard above, proved able to fail ══════════════


def copy_src(tmp_path, path_rel, edits):
    """Copy every harness input into tmp_path, apply `edits`, and PROVE they landed AS BYTES.

    read_text() normalises CRLF, so a mutation whose anchor spans a line break silently matches
    nothing -- and the run then looks like a passing test defending nothing at all. These files
    are CRLF on this checkout, so the byte check is not theoretical.

    `edits` is a list of (old, new) pairs, because one mutation below has to change a regex AND
    the call that reads its capture groups; changing only one of them would be a third behaviour
    that nobody is arguing for."""
    dest = tmp_path / "frontend"
    (dest / "js").mkdir(parents=True, exist_ok=True)
    for rel in MUTATE_FILES:
        (dest / rel).write_text((FRONTEND / rel).read_text(encoding="utf-8"),
                                encoding="utf-8", newline="\n")
    target = dest / path_rel
    src = target.read_text(encoding="utf-8")
    for old, new in edits:
        assert src.count(old) == 1, (
            "the mutation's anchor is not in %s exactly once -- the source moved and this test "
            "is no longer proving anything: %r" % (path_rel, old))
        src = src.replace(old, new)
    target.write_text(src, encoding="utf-8", newline="\n")
    landed = target.read_bytes().decode("utf-8")
    for old, new in edits:
        assert new in landed, "the mutation %r did not reach the disk" % new
        assert old not in landed, "the original %r survived on disk" % old
    return dest


@needs_node
def test_evaluating_the_rate_instead_of_parsing_it_makes_the_round_trip_go_red(tmp_path):
    """MUTATED: the "simplification" this design exists to refuse.

    `shiftDecimalText(m[1], -2)` is replaced by `Number(m[1]) / 100`, which is what the Markup
    page's own engine does to a postfix `%` -- verified against the real markup-core.js in this
    repo, not assumed:

        TWMarkup.run("2.7%")  ->  0.027000000000000003
        TWMarkup.run("4.1%")  ->  0.040999999999999995
        Number("2.7") / 100   ->  0.027000000000000003        (the same drift, same cause)

    Under the mutation, filing Polish's own 2.7% writes `=0.027000000000000003` into B69, which is
    not what the workbook holds -- so the round-trip assertion goes red, which is the point of
    this test.

    AND THE PRICE, HONESTLY. Bare `Math.ceil(1000 * 0.027000000000000003)` is 28 against 27, and
    the spec this was built from concluded from that the price moves. It does not, today: the
    shipped ROUNDUP snaps to 12 significant digits (xl-excel-rounding.js) and Excel tidies up on
    its own side, so both artefacts still say 27. The assertion below records the bare arithmetic
    as the hazard it is and the snapped result as the reason it is currently harmless -- so a
    change to the rounding override cannot quietly make it harmful again, and nobody reading this
    file is told a price moved when it did not."""
    dest = copy_src(tmp_path, "js/estimate-review.js", [(
        "  const t = shiftDecimalText(m[1], -2);",
        "  const t = String(Number(m[1]) / 100);")])
    mutant = drive(dest)
    parsed = mutant["builtinsFiled"]["parsed"]
    assert parsed["polish/super_pto"] == "0.027000000000000003", (
        "the mutation changed nothing, so the round-trip assertion was vacuous -- got %r"
        % parsed["polish/super_pto"])
    assert parsed["gyp/super_pto"] == "0.040999999999999995", parsed["gyp/super_pto"]
    assert mutant["builtinsFiled"]["cellValues"]["Polish!B69"] == "=0.027000000000000003"

    # The round trip, re-run against the mutant's own parse: it no longer lands on the literal.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        literal = openpyxl.load_workbook(TEMPLATE, data_only=False)["Polish"]["B69"].value
    assert repr(float(parsed["polish/super_pto"])) != repr(float(literal))

    # The hazard, bare: one ulp of drift crosses an integer boundary on a round base, and every
    # sub-total cell in the workbook is itself a ROUNDUP, so round bases are what it produces.
    drift = float(parsed["polish/super_pto"])
    assert math.ceil(1000 * 0.027) == 27
    assert math.ceil(1000 * drift) == 28

    # …and why it is harmless TODAY, which is a dependency and not a design: both engines snap
    # before rounding. If either stops, the line above is what the bid would do.
    def snapped_roundup(x):
        return math.ceil(float("%.12g" % float("%.12g" % x)))

    assert snapped_roundup(1000 * 0.027) == 27
    assert snapped_roundup(1000 * drift) == 27, (
        "the rounding override no longer absorbs the drift, so evaluating a filed rate would now "
        "misprice the bid as well as writing a 17-digit float into Kyle's workbook")


@needs_node
def test_moving_one_target_address_makes_the_fan_out_and_the_dollars_go_wrong(tmp_path):
    """MUTATED, so the round trip is not a green test over a table nothing checks.

    Polish's super_pto address is moved from B69 to B70 -- the soft-costs cell, one row down and a
    plausible typo. The fan-out and the built-in write then land on the wrong cell, and the
    dollars change."""
    dest = copy_src(tmp_path, "js/estimate-review.js", [(
        '"Polish":       { super_pto: "B69", soft_costs: "B70" },',
        '"Polish":       { super_pto: "B70", soft_costs: "B70" },')])
    mutant = drive(dest)
    assert "Polish!B69" not in mutant["fanOut"]["written"], (
        "the mutation changed nothing, so the fan-out assertion was vacuous")
    expected = sorted("%s!%s" % (s, a) for s, spec in WIRED.items() for a in spec.values())
    assert mutant["fanOut"]["written"] != expected
    assert mutant["fanOut"]["changed"] == 16, (
        "16, not 17: two lines now collide on one cell and Polish!B69 is never written")

    # AND IN DOLLARS, which is the half that matters. Filing 4% on all three polish lines prices
    # 12044 correctly. Under the mutation Polish!B69 keeps Kyle's 2.7% and only the soft-costs
    # cell is written, which comes out 11893 -- $151 out, on a bid nothing on screen flags.
    correct = Chain().put("Polish", "B69", 0.04).put("Polish", "B70", 0.04).total("Polish")
    mutated = Chain().put("Polish", "B70", 0.04).total("Polish")
    assert correct == 12044.0 and mutated == 11893.0, (correct, mutated)
    assert correct != mutated, "moving the address would not have changed a price"


@needs_node
def test_making_the_percent_sign_optional_reopens_the_hundredfold_misprice(tmp_path):
    """MUTATED: the exact permissive parser the original spec called for.

    With `%` optional, "0.5" parses to 0.5 -- fifty percent -- and reaches Kyle's cell. On the
    template's own Epoxy tab that turns an $11,029 bid into $17,000-odd. Nothing errors. This is
    what the stricter regex buys, and it is why the deviation from the spec is deliberate."""
    dest = copy_src(tmp_path, "js/estimate-review.js", [
        ("const _RATE_LITERAL_RE = /^\\s*(\\d*\\.?\\d*)\\s*%\\s*$/;",
         "const _RATE_LITERAL_RE = /^\\s*(\\d*\\.?\\d*)\\s*(%?)\\s*$/;"),
        ("  const t = shiftDecimalText(m[1], -2);",
         "  const t = shiftDecimalText(m[1], m[2] ? -2 : 0);"),
    ])
    mutant = drive(dest)
    refused = dict(mutant["parser"]["refused"])
    assert refused["0.5"] == "0.5", (
        "the mutation changed nothing, so the parser test was vacuous -- expected a permissive "
        "regex to read 0.5 as a bare rate, got %r" % refused["0.5"])
    assert refused["0.03"] == "0.03"
    # What that costs on the real workbook: 0.5 in the super_pto cell.
    before = Chain().total("Epoxy")
    after = Chain().put("Epoxy", "B75", 0.5).total("Epoxy")
    assert (before, after) == (11029.0, 16061.0), (
        "the figures in this docstring need re-deriving: %s -> %s" % (before, after))
    assert after - before == 5032.0, (
        "a bare 0.5 read as fifty percent overcharges the template's own epoxy bid by $5,032 "
        "(46%%); it moved by %+.2f" % (after - before))


@needs_node
def test_adding_a_gp_address_makes_the_deferral_test_go_red(tmp_path):
    """MUTATED: gp given Epoxy's own ladder cell, which is what a well-meaning "finish the
    feature" change looks like. The bare-literal "45%" in the fixture then reaches B73 and
    replaces five tiers with one rate -- and the workbook prices it without complaining."""
    dest = copy_src(tmp_path, "js/estimate-review.js", [(
        '"Epoxy":        { super_pto: "B75", soft_costs: "B76" },',
        '"Epoxy":        { gp: "B73", super_pto: "B75", soft_costs: "B76" },')])
    mutant = drive(dest)
    assert mutant["deferredLinesReachNothing"]["keys"] != [], (
        "the mutation changed nothing, so the deferral test was vacuous")
    assert "Epoxy!B73" in mutant["deferredLinesReachNothing"]["keys"]
    assert "gp" in mutant["deferredLinesReachNothing"]["keysPerLayout"]["Epoxy"]
    # And the price it would have quoted, for the record.
    before = Chain().total("Epoxy")
    after = Chain().put("Epoxy", "B73", 0.45).total("Epoxy")
    assert after != before, (before, after)


@needs_node
def test_dropping_the_reach_sentence_makes_the_admin_page_test_go_red(tmp_path):
    """MUTATED: item D removed. Proves the sentence is actually rendered rather than merely
    defined -- which is the difference the CRM board's `STAGE_CREATED is not defined` outage was
    made of."""
    dest = copy_src(tmp_path, "js/markup.js",
                    [("    explain += reachSentence(r);", '    explain += "";')])
    mutant = drive(dest)
    # The sentence builder still exists, so the harness can still lift it; what changes is that
    # nothing on the page appends it. Checked through the page harness, which renders for real.
    page = subprocess.run(
        ["node", str(pathlib.Path(__file__).resolve().parent / "js" / "markup-page-harness.js"),
         str(dest)], capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert page.returncode == 0, page.stderr
    rendered = json.loads(page.stdout.strip().splitlines()[-1])
    rows = {r["line"]: r["explain"] for r in rendered["dayOnePolish"]["rows"]}
    assert "does not read this line yet" not in rows["gp"], (
        "the mutation changed nothing, so the rendered-sentence assertion was vacuous")
    assert mutant["reachSentence"]["gpPolish"], "the builder itself should be untouched"


@needs_node
def test_re_adding_bond_makes_the_bond_exclusion_test_go_red(tmp_path):
    """MUTATED: bond wired back up on the epoxy layout, in BOTH files, exactly the way a
    well-meaning "finish the feature" change would do it.

    This is the mutation that matters most, because the exclusion it defends is an omission --
    and an omission is the easiest thing in this file to read as an oversight and helpfully
    correct. Without this test, `test_no_layout_has_a_bond_address_and_the_admin_page_lists_none`
    would be a green assertion about a table nobody had ever seen disagree with it.

    The dollars are asserted too, because that is the actual harm: on the template's own Leveling
    tab (the one sheet shipping with real tax on it) a 1% bond charges $110 where the honest base
    charges $108, and the gap grows with the tax -- roughly $28 on a $36.7k bid carrying $2,763."""
    dest = copy_src(tmp_path, "js/estimate-review.js", [(
        '"Epoxy":        { super_pto: "B75", soft_costs: "B76" },',
        '"Epoxy":        { super_pto: "B75", soft_costs: "B76", bond: "B84" },')])
    # The other half, so the mutant is internally consistent -- otherwise the cross-file
    # agreement test would catch it first and this one would never be exercised.
    mk = dest / "js" / "markup.js"
    mk_src = mk.read_text(encoding="utf-8")
    old = '    epoxy:    ["super_pto", "soft_costs"],'
    assert mk_src.count(old) == 1, "the PRICES_THE_BID anchor moved"
    mk.write_text(mk_src.replace(old, '    epoxy:    ["super_pto", "soft_costs", "bond"],'),
                  encoding="utf-8", newline="\n")
    assert '"bond"' in mk.read_bytes().decode("utf-8")

    mutant = drive(dest)
    assert "bond" in mutant["targetTable"]["Epoxy"], (
        "the mutation changed nothing, so the bond exclusion test was vacuous")
    assert "bond" in mutant["pricesTheBid"]["epoxy"]
    assert "Epoxy!B84" in mutant["fanOut"]["written"]
    # The two sides still agree with each other, which is the point: consistency is not safety.
    projected = {}
    for layout, spec in mutant["targetTable"].items():
        projected.setdefault(mutant["layoutOf"][layout], set()).update(spec.keys())
    assert {k: set(v) for k, v in mutant["pricesTheBid"].items()} == projected, (
        "the mutant is internally inconsistent, so this test is measuring the wrong failure")

    # …and what that consistent, agreed, over-charging bid actually costs.
    honest_base = sum(_num(Chain().put("Leveling", "B80", 0.01).value("Leveling", a))
                      for a in ["D66", "D69", "D70", "D71", "D72", "D73", "D76", "D77", "D79"])
    charged = Chain().put("Leveling", "B80", 0.01).total("Leveling")
    assert charged == 10873.0, charged
    assert math.ceil(round(honest_base * 0.01, 9)) == 108
    assert charged - Chain().total("Leveling") == 110.0, (
        "the bond over-charge is no longer $110 against an honest $108 -- if Kyle's D84 has been "
        "fixed, re-add bond for real and delete this test")


@needs_node
def test_dropping_a_line_from_prices_the_bid_makes_the_agreement_test_go_red(tmp_path):
    """MUTATED: the admin page told that bond does not reach the bid while the writer still writes
    it. Proves the cross-file agreement test bites, which is the only thing standing between two
    files that each look right on their own."""
    dest = copy_src(tmp_path, "js/markup.js", [(
        '    epoxy:    ["super_pto", "soft_costs"],',
        '    epoxy:    ["super_pto"],')])
    mutant = drive(dest)
    projected = {}
    for layout, spec in mutant["targetTable"].items():
        projected.setdefault(mutant["layoutOf"][layout], set()).update(spec.keys())
    claimed = {k: set(v) for k, v in mutant["pricesTheBid"].items()}
    assert claimed != projected, (
        "the mutation changed nothing, so the agreement test was vacuous")
    assert claimed["epoxy"] == {"super_pto"}
